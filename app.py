#!/usr/bin/env python3
from flask import Flask, jsonify, render_template, request, Response
import base64
import json
import os
import subprocess
import threading
import urllib.request
from datetime import datetime, date, timedelta, timezone

from dotenv import load_dotenv
load_dotenv()

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
            "has_archive": e.get("has_archive", 0),
        })

    programs.sort(key=lambda p: p["start"], reverse=True)
    return jsonify(programs)


@app.route("/api/download", methods=["POST"])
def api_download():
    body = request.json
    stream_id  = body["stream_id"]
    start_date = body["date"]        # YYYY-MM-DD
    start_time = body["start_time"]  # HH:MM
    end_time   = body["end_time"]    # HH:MM
    name       = body["name"]

    sh, sm = map(int, start_time.split(":"))
    eh, em = map(int, end_time.split(":"))
    start_min = sh * 60 + sm
    end_min   = eh * 60 + em
    if end_min <= start_min:
        end_min += 24 * 60
    duration = end_min - start_min

    ts = start_date.replace("-", "") + f"_{sh:02d}{sm:02d}"
    safe = name.replace(" ", "_").replace("/", "-").replace("|", "").strip("_")
    out  = f"{DOWNLOAD_DIR}/{safe}_{ts}.ts"

    start_str = f"{start_date}:{sh:02d}-{sm:02d}"
    url = (
        f"{SERVER}/streaming/timeshift.php"
        f"?username={USER}&password={PASS}"
        f"&typeEnd=.ts&start={start_str}&duration={duration}&stream={stream_id}"
    )

    dl_id = f"{stream_id}_{ts}"
    _active_downloads[dl_id] = {"log": [], "done": False, "out": out, "duration": duration}

    def run():
        cmd = ["ffmpeg", "-y", "-i", url, "-c", "copy", "-stats", out]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        _active_downloads[dl_id]["proc"] = proc
        for line in proc.stdout:
            _active_downloads[dl_id]["log"].append(line.rstrip())
        proc.wait()
        _active_downloads[dl_id]["done"] = True
        _active_downloads[dl_id]["returncode"] = proc.returncode

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"dl_id": dl_id, "out": out, "duration": duration})


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
                yield f"data: {{\"done\": true, \"ok\": {str(rc == 0).lower()}, \"out\": \"{dl['out']}\"}}\n\n"
                break
            time.sleep(0.5)
    return Response(stream(), mimetype="text/event-stream")


@app.route("/api/cancel/<dl_id>", methods=["POST"])
def api_cancel(dl_id):
    dl = _active_downloads.get(dl_id)
    if dl and "proc" in dl:
        dl["proc"].terminate()
        return jsonify({"ok": True})
    return jsonify({"ok": False})


if __name__ == "__main__":
    print("Open browser: http://localhost:5123")
    app.run(port=5123, debug=False)
