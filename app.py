#!/usr/bin/env python3
from flask import Flask, jsonify, render_template, request, Response
import base64
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, date, timedelta, timezone

from dotenv import load_dotenv
load_dotenv()

import f1

app = Flask(__name__)

SERVER       = os.environ["XTREAM_SERVER"]
USER         = os.environ["XTREAM_USER"]
PASS         = os.environ["XTREAM_PASS"]
DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", os.path.expanduser("~/Downloads"))

NL_CAT_IDS = {
    "1430","1511","1422","1431","1424",
    "1425","1427","1426","1428","1151",
    "1927",
}

_active_downloads = {}  # id -> {"proc": ..., "log": [...], "done": bool}

F1_CACHE_SECONDS = 6 * 3600
_f1_best = {"channel": None, "at": 0.0}  # probing is slow, so remember the winner


def player_api(action, **params):
    query = "".join(f"&{k}={v}" for k, v in params.items())
    url = f"{SERVER}/player_api.php?username={USER}&password={PASS}&action={action}{query}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


XMLTV_CACHE_SECONDS = 15 * 60
_xmltv_cache = {}  # epg channel id -> (fetched at, listings)


def xmltv_listings(channel_id, days):
    """Fallback guide. The 90 MB XMLTV export has data when player_api answers
    with an empty list, as it did from 1-11-2026. When the export itself fails
    (404 on 2-11-2026), the last good copy is used, minus what has left the
    catch-up window."""
    hit = _xmltv_cache.get(channel_id)
    if hit and time.time() - hit[0] < XMLTV_CACHE_SECONDS:
        return hit[1]
    url = f"{SERVER}/xmltv.php?username={USER}&password={PASS}"
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            listings = f1.xmltv_listings(r, channel_id, days=int(days))
    except Exception:
        if not hit:
            raise
        cutoff = time.time() - int(days) * 86400
        return [e for e in hit[1] if e["start_timestamp"] >= cutoff]
    _xmltv_cache[channel_id] = (time.time(), listings)
    return listings


SKY_API = "https://awk.epgsky.com/hawk/linear"
CACHE_DIR = os.environ.get("CACHE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache"))
HISTORY_FILE = os.path.join(CACHE_DIR, "guide.json")


def _get_json(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def sky_guide(days):
    """Third source: Sky's own schedule. Only today and later have data, so the
    past days come from the saved history."""
    sid = f1.sky_service_id(_get_json(f"{SKY_API}/services/4101/1"))
    listings = []
    for back in range(int(days), -2, -1):
        day = (datetime.now() - timedelta(days=back)).strftime("%Y%m%d")
        listings += f1.sky_listings(_get_json(f"{SKY_API}/schedule/{day}/{sid}"))
    return listings


def _load_history(key):
    try:
        with open(HISTORY_FILE, encoding="utf-8") as fh:
            return json.load(fh).get(key, [])
    except (OSError, ValueError):
        return []


def _save_history(key, listings):
    try:
        data = {}
        try:
            with open(HISTORY_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            pass
        data[key] = listings
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except OSError:
        pass  # history is a bonus; never fail the page over it


def _first_guide(sources):
    """The first source that yields entries. A source that fails counts as empty,
    so one broken endpoint cannot take the whole F1 block down."""
    for source in sources:
        try:
            listings = source()
        except Exception:
            continue
        if listings:
            return listings
    return []


def epg_listings(channel):
    """EPG entries of a channel, from the first source that answers: player_api
    (answers [] or resets the connection when it has no guide), the provider's
    XMLTV export, Sky's schedule API. Whatever comes back is merged into a saved
    history, so days the sources no longer serve stay available while the
    catch-up archive still holds them."""
    days = int(channel.get("days", 3))

    def player():
        data = player_api("get_simple_data_table", stream_id=channel["id"])
        return data.get("epg_listings", []) if isinstance(data, dict) else []

    sources = [player]
    if channel.get("epg"):
        sources.append(lambda: xmltv_listings(channel["epg"], days))
    sources.append(lambda: sky_guide(days))

    key = channel.get("epg") or str(channel["id"])
    fresh = _first_guide(sources)
    history = f1.within_window(f1.merge_history(_load_history(key), fresh), days)
    if fresh:
        _save_history(key, history)
    return history


def timeshift_url(stream_id, start_str, duration):
    """start_str is "YYYY-MM-DD:HH-MM" (Amsterdam time), duration in minutes."""
    return (
        f"{SERVER}/streaming/timeshift.php"
        f"?username={USER}&password={PASS}"
        f"&typeEnd=.ts&start={start_str}&duration={duration}&stream={stream_id}"
    )


def best_f1_channel():
    """The UK Sky Sports F1 stream with catch-up in the highest quality."""
    if _f1_best["channel"] and time.time() - _f1_best["at"] < F1_CACHE_SECONDS:
        return _f1_best["channel"]
    cats = {str(c["category_id"]): c["category_name"] for c in player_api("get_live_categories")}
    probed = []
    for ch in f1.candidates(player_api("get_live_streams"), cats):
        listings = epg_listings(ch)
        archived = f1.archived_programs(listings)
        if archived:
            start = archived[0]["start"]  # "2026-10-30 19:00:00"
            ch.update(f1.probe(timeshift_url(ch["id"], f"{start[:10]}:{start[11:13]}-{start[14:16]}", 1)))
        probed.append(ch)
    best = f1.pick_best(probed)
    # Alleen een gemeten keuze onthouden; zonder gids valt er niets te meten en
    # zou een gok 6 uur blijven hangen.
    if best and best.get("height"):
        _f1_best.update(channel=best, at=time.time())
    return best


def fetch_channels():
    url = f"{SERVER}/player_api.php?username={USER}&password={PASS}&action=get_live_streams"
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.load(r)
    channels = [
        {"id": ch["stream_id"], "name": ch["name"], "days": ch.get("tv_archive_duration", 3)}
        for ch in data
        if ch.get("tv_archive", 0) == 1 and ch.get("category_id", "") in NL_CAT_IDS
    ]
    channels.sort(key=lambda c: c["name"])
    return channels


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/channels")
def api_channels():
    return jsonify(fetch_channels())


@app.route("/api/epg/<int:stream_id>")
def api_epg(stream_id):
    url = (
        f"{SERVER}/player_api.php?username={USER}&password={PASS}"
        f"&action=get_simple_data_table&stream_id={stream_id}"
    )
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.load(r)

    listings = data.get("epg_listings", [])
    now_ts = datetime.now(timezone.utc).timestamp()
    cutoff = now_ts - 3 * 24 * 3600  # 3 days back

    programs = []
    for e in listings:
        start_ts = int(e.get("start_timestamp", 0))
        stop_ts  = int(e.get("stop_timestamp", 0))
        if start_ts < cutoff or start_ts > now_ts:
            continue
        try:
            title = base64.b64decode(e["title"]).decode("utf-8")
        except Exception:
            title = e.get("title", "")
        try:
            desc = base64.b64decode(e["description"]).decode("utf-8")
        except Exception:
            desc = ""

        # start/end in "YYYY-MM-DD HH:MM:SS" (Amsterdam time)
        start_str = e.get("start", "")
        end_str   = e.get("end", "")
        programs.append({
            "title":       title,
            "description": desc,
            "start":       start_str,       # "2026-05-02 20:30:00"
            "end":         end_str,
            # The provider's flag lags hours behind; an ended programme on a
            # catch-up channel is in the archive (see f1.archived_programs).
            "has_archive": 1 if 0 < stop_ts <= now_ts else e.get("has_archive", 0),
        })

    programs.sort(key=lambda p: p["start"], reverse=True)
    return jsonify(programs)


def expire_guide_cache():
    """Make the next guide request go to the provider again. The stale copy
    stays as the fallback for when the XMLTV export fails."""
    for channel_id, (_, listings) in list(_xmltv_cache.items()):
        _xmltv_cache[channel_id] = (0.0, listings)


@app.route("/api/f1")
def api_f1():
    # ?refresh=1 (the Vernieuwen button) skips the 15 min guide cache. The
    # measured best channel is kept: probing is slow and does not change.
    if request.args.get("refresh"):
        expire_guide_cache()
    channel = best_f1_channel()
    if not channel:
        return jsonify({"channel": None, "programs": []})
    listings = epg_listings(channel)
    return jsonify({"channel": channel, "programs": f1.archived_programs(listings), "auto": AUTO_RACE})


MAX_RESUMES = 6
_PROGRESS = re.compile(r"time=(\d+:\d+:\d+)")

# The queue lives on the server, so downloads go on with the browser closed.
# One worker: most IPTV subscriptions allow a single connection.
_queue = queue.Queue()
_worker = {"thread": None}
_worker_lock = threading.Lock()


def _run_download(dl_id):
    dl = _active_downloads[dl_id]
    stream_id, start_str, duration, out = dl["stream_id"], dl["start_str"], dl["duration"], dl["out"]

    def fetch(target, begin, minutes):
        cmd = ["ffmpeg", "-y", "-i", timeshift_url(stream_id, begin, minutes),
               "-c", "copy", "-stats", target]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        dl["proc"] = proc
        for line in proc.stdout:
            dl["log"].append(line.rstrip())
            seen = _PROGRESS.search(line)
            if seen:
                dl["progress"] = seen.group(1)
        proc.wait()
        return proc.returncode

    rc = fetch(out, start_str, duration)
    # Exit code 0 also means "the provider hung up". Check the real length and
    # fetch what is missing, instead of reporting a 1 minute file as done.
    for attempt in range(MAX_RESUMES):
        if rc != 0 or dl.get("cancelled"):
            break
        got = f1.media_seconds(out)
        plan = f1.resume_plan(start_str, duration, got)
        if plan is None:
            break
        begin, minutes = plan
        dl["log"].append(f"Onvolledig: {got / 60:.0f} van {duration} min. Rest ophalen vanaf {begin[-5:].replace('-', ':')} ({attempt + 1}/{MAX_RESUMES})")
        part = out + ".part"
        rc = fetch(part, begin, minutes)
        if os.path.exists(part):
            with open(out, "ab") as dst, open(part, "rb") as src:
                shutil.copyfileobj(src, dst)
            os.remove(part)
    got = f1.media_seconds(out)
    dl["got_min"] = round(got / 60)
    dl["returncode"] = rc
    dl["complete"] = rc == 0 and f1.resume_plan(start_str, duration, got) is None


def _work():
    while True:
        dl = _active_downloads.get(_queue.get())
        if dl is None or dl["done"]:
            continue  # cancelled while it waited
        dl["state"] = "running"
        try:
            _run_download(dl["id"])
        except Exception as exc:  # one broken job must not stop the queue
            dl["log"].append(f"Fout: {exc}")
            dl.update(returncode=-1, complete=False)
        dl.update(state="done", done=True)


def job_names(stream_id, name, start_date, start_time):
    """Id and file of a download; both follow from channel, name and start."""
    ts = start_date.replace("-", "") + "_" + start_time.replace(":", "")[:4].zfill(4)
    safe = name.replace(" ", "_").replace("/", "-").replace("|", "").replace(":", "").strip("_")
    return f"{stream_id}_{ts}", f"{DOWNLOAD_DIR}/{safe}_{ts}.ts"


def enqueue_download(stream_id, name, start_date, start_time, end_time):
    """Put a download in the queue. Returns the job; a job that is still
    waiting or running is returned as it is instead of being queued twice."""
    sh, sm = map(int, start_time.split(":"))
    eh, em = map(int, end_time.split(":"))
    start_min = sh * 60 + sm
    end_min   = eh * 60 + em
    if end_min <= start_min:
        end_min += 24 * 60
    duration = end_min - start_min

    dl_id, out = job_names(stream_id, name, start_date, start_time)

    with _worker_lock:
        current = _active_downloads.get(dl_id)
        if current and not current["done"]:
            return current
        waiting = sum(1 for d in _active_downloads.values() if not d["done"])
        dl = {
            "id": dl_id, "name": name, "stream_id": stream_id,
            "start_str": f"{start_date}:{sh:02d}-{sm:02d}", "duration": duration,
            "out": out,
            "log": [f"In de wachtrij, {waiting} download(s) ervoor."] if waiting else [],
            "state": "queued", "done": False,
        }
        _active_downloads[dl_id] = dl
        _queue.put(dl_id)
        if _worker["thread"] is None:
            _worker["thread"] = threading.Thread(target=_work, daemon=True)
            _worker["thread"].start()
    return dl


@app.route("/api/download", methods=["POST"])
def api_download():
    body = request.json
    dl = enqueue_download(body["stream_id"], body["name"], body["date"],
                          body["start_time"], body["end_time"])
    return jsonify({"dl_id": dl["id"], "out": dl["out"], "duration": dl["duration"]})


@app.route("/api/downloads")
def api_downloads():
    """Every job since the server started, so a reopened page can show where
    the queue stands."""
    return jsonify([
        {
            "id": dl["id"], "name": dl["name"], "stream_id": dl["stream_id"],
            "state": dl["state"], "ok": bool(dl.get("complete")),
            "cancelled": bool(dl.get("cancelled")), "progress": dl.get("progress", ""),
            "got": dl.get("got_min", 0), "want": dl["duration"], "out": dl["out"],
        }
        for dl in list(_active_downloads.values())
    ])


@app.route("/api/files")
def api_files():
    """The recordings in the download folder, newest first. Read from disk, so
    it also shows what was fetched before a restart or by the auto download."""
    busy = {os.path.basename(dl["out"]) for dl in _active_downloads.values() if not dl["done"]}
    files = []
    try:
        entries = list(os.scandir(DOWNLOAD_DIR))
    except OSError:
        entries = []
    for entry in entries:
        if not entry.name.endswith(".ts") or not entry.is_file():
            continue
        stat = entry.stat()
        files.append({"name": entry.name, "size": stat.st_size,
                      "modified": int(stat.st_mtime), "busy": entry.name in busy})
    files.sort(key=lambda f: f["modified"], reverse=True)
    return jsonify({"folder": DOWNLOAD_DIR, "files": files})


# --- Automatic race download ---------------------------------------------
# AUTO_RACE=1 (set on the NAS by deploy.sh) makes the app fetch every live race
# broadcast by itself. Off by default, so a local run does not fill ~/Downloads.
AUTO_RACE = os.environ.get("AUTO_RACE", "") == "1"
AUTO_CHECK_SECONDS = int(os.environ.get("AUTO_CHECK_MINUTES", "15")) * 60
AUTO_EXTRA_MIN = int(os.environ.get("AUTO_EXTRA_MINUTES", "30"))  # a race can run over its slot
AUTO_TRIES = 3
AUTO_FILE = os.path.join(CACHE_DIR, "auto.json")  # survives a restart: no race twice


def _load_auto():
    try:
        with open(AUTO_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def auto_check():
    """Queue the live races that have ended and are not on disk yet. Returns
    the ids it queued."""
    # A waiting or running job uses the one connection the provider allows;
    # measuring the best channel would get in its way. Next round.
    if any(not dl["done"] for dl in _active_downloads.values()):
        return []
    channel = best_f1_channel()
    if not channel:
        return []
    programs = f1.archived_programs(epg_listings(channel))
    state, queued = _load_auto(), []
    for p in f1.races_due(programs, time.time(), AUTO_EXTRA_MIN):
        date, start = p["start"][:10], p["start"][11:16]
        name = f"F1 {p['title']} {p['session']}"  # same name as the page gives it
        dl_id, out = job_names(channel["id"], name, date, start)
        entry = state.setdefault(dl_id, {"title": p["title"], "tries": 0, "ok": False})
        job = _active_downloads.get(dl_id)
        if job and job.get("complete"):
            entry["ok"] = True
        elif entry["tries"] == 0 and os.path.exists(out):
            entry["ok"] = True  # already fetched by hand
        if entry["ok"] or entry["tries"] >= AUTO_TRIES:
            continue
        entry["tries"] += 1
        enqueue_download(channel["id"], name, date, start, f1.padded_end(p["end"], AUTO_EXTRA_MIN))
        queued.append(dl_id)
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(AUTO_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except OSError:
        pass
    return queued


def _auto_loop():
    while True:
        try:
            for dl_id in auto_check():
                print(f"auto: race in de wachtrij gezet ({dl_id})", flush=True)
        except Exception as exc:  # provider down: try again next round
            print(f"auto: controle mislukt ({exc})", flush=True)
        time.sleep(AUTO_CHECK_SECONDS)


@app.route("/api/status/<dl_id>")
def api_status(dl_id):
    def stream():
        sent = 0
        import time
        while True:
            dl = _active_downloads.get(dl_id)
            if dl is None:
                yield "data: {\"error\": \"not found\"}\n\n"
                break
            log = dl["log"]
            while sent < len(log):
                line = log[sent].replace('"', "'")
                yield f"data: {{\"line\": \"{line}\", \"done\": false}}\n\n"
                sent += 1
            if dl["done"]:
                rc = dl.get("returncode", -1)
                ok = str(dl.get("complete", rc == 0)).lower()
                yield f"data: {{\"done\": true, \"ok\": {ok}, \"got\": {dl.get('got_min', 0)}, \"want\": {dl['duration']}, \"out\": \"{dl['out']}\"}}\n\n"
                break
            time.sleep(0.5)
    return Response(stream(), mimetype="text/event-stream")


@app.route("/api/cancel/<dl_id>", methods=["POST"])
def api_cancel(dl_id):
    dl = _active_downloads.get(dl_id)
    if dl and dl["state"] == "queued":  # not started: the worker skips it
        dl.update(cancelled=True, state="done", done=True, returncode=-1, complete=False)
        return jsonify({"ok": True})
    if dl and "proc" in dl:
        dl["cancelled"] = True
        dl["proc"].terminate()
        return jsonify({"ok": True})
    return jsonify({"ok": False})


if __name__ == "__main__":
    if AUTO_RACE:
        threading.Thread(target=_auto_loop, daemon=True).start()
    print("Open browser: http://localhost:5123")
    # HOST=0.0.0.0 in the NAS container; locally it stays on localhost.
    app.run(host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "5123")), debug=False)
