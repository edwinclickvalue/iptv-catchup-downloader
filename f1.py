"""Sky Sports F1 block: find the best UK Sky Sports F1 stream with catch-up
and list the programmes that can be downloaded from it."""
import base64
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

AMSTERDAM = ZoneInfo("Europe/Amsterdam")

SKY_F1 = re.compile(r"sky\s*sports?\s*f1", re.I)
UK     = re.compile(r"^\s*UK\b", re.I)


def candidates(streams, categories):
    """UK Sky Sports F1 channels that have catch-up."""
    found = []
    for ch in streams:
        cat = categories.get(str(ch.get("category_id", "")), "")
        if ch.get("tv_archive", 0) != 1:
            continue
        if not SKY_F1.search(ch.get("name", "")):
            continue
        if not (UK.search(cat) or UK.search(ch.get("name", ""))):
            continue
        found.append({
            "id":   ch["stream_id"],
            "name": ch["name"],
            "days": ch.get("tv_archive_duration", 3),
            "epg":  ch.get("epg_channel_id") or "",
        })
    return found


def _b64(text):
    return base64.b64encode((text or "").encode("utf-8")).decode("ascii")


def xmltv_listings(source, channel_id, days=3, now_ts=None):
    """Guide entries of one channel from an XMLTV stream, in the shape of the
    player_api listings. XMLTV does not say what is archived, so every programme
    inside the catch-up window counts. Times are Amsterdam local time, which is
    what timeshift.php expects."""
    if now_ts is None:
        now_ts = datetime.now(timezone.utc).timestamp()
    window_start = now_ts - days * 86400
    out = []
    for _, el in ET.iterparse(source):
        if el.tag != "programme":
            el.clear() if el.tag == "channel" else None
            continue
        if el.get("channel") == channel_id:
            start = datetime.strptime(el.get("start"), "%Y%m%d%H%M%S %z")
            stop = datetime.strptime(el.get("stop"), "%Y%m%d%H%M%S %z")
            if start.timestamp() >= window_start:
                out.append({
                    "title":           _b64(el.findtext("title")),
                    "description":     _b64(el.findtext("desc")),
                    "start":           start.astimezone(AMSTERDAM).strftime("%Y-%m-%d %H:%M:%S"),
                    "end":             stop.astimezone(AMSTERDAM).strftime("%Y-%m-%d %H:%M:%S"),
                    "start_timestamp": int(start.timestamp()),
                    "stop_timestamp":  int(stop.timestamp()),
                    "has_archive":     1,
                })
        el.clear()
    return out


def pick_best(probed):
    """Highest resolution wins, then highest bitrate. Unprobeable streams last."""
    if not probed:
        return None
    return max(probed, key=lambda c: (c.get("height") or 0, c.get("bitrate") or 0))


def _decode(value):
    try:
        return base64.b64decode(value).decode("utf-8")
    except Exception:
        return value or ""


PRACTICE_NO = {"opening": 1, "first": 1, "second": 2, "third": 3, "final": 3}


def session_label(title, description):
    """What a programme actually is. Sky reuses "<GP> F1 GP" as title for every
    session, so the description is the only place the session is named."""
    t, d = title.lower(), description.lower()
    if "highlights" in t or "hlts" in t:
        return "Samenvatting"
    m = re.search(r"\bpractice (\d)\b", t)
    if m:
        return f"VT{m.group(1)}"
    if re.search(r"sprint (qualifying|shootout)", t):
        return "Sprint-kwalificatie"
    if re.search(r"\bqualifying\b", t):
        return "Kwalificatie"
    if re.search(r"\bsprint\b", t):
        return "Sprint"
    if re.search(r"\b(f1|formula 1) grand prix\b", t) and "live" in t:
        return "Race"
    m = re.search(r"\b(opening|first|second|third|final)\b[^.]*\bpractice\b", d)
    if m:
        return f"VT{PRACTICE_NO[m.group(1)]}"
    if re.search(r"sprint (qualifying|shootout)", d):
        return "Sprint-kwalificatie"
    if "qualifying" in d and "notebook" not in t:
        return "Kwalificatie"
    if re.search(r"\bsprint\b", d) and "practice" not in d:
        return "Sprint"
    # Alleen de race zelf: "lights out" staat in de omschrijving, en de shows eromheen
    # ("Grand Prix Sunday", "Chequered Flag", "Notebook") zijn het niet.
    if (re.search(r"\bgrand prix\b|\bf1 gp\b", t) and "lights out" in d
            and not re.search(r"sunday|saturday|chequered|notebook|show|wrapped|preview|press", t)):
        return "Race"
    return None


def archived_programs(listings, now_ts=None):
    """Programmes that already aired and are in the archive, newest first."""
    if now_ts is None:
        now_ts = datetime.now(timezone.utc).timestamp()
    programs = []
    for e in listings:
        if int(e.get("has_archive", 0)) != 1:
            continue
        if int(e.get("stop_timestamp", 0)) > now_ts:
            continue  # still on air: the archive is not complete yet
        title, desc = _decode(e.get("title", "")), _decode(e.get("description", ""))
        programs.append({
            "title":       title,
            "description": desc,
            "session":     session_label(title, desc),
            "start":       e.get("start", ""),
            "end":         e.get("end", ""),
            "live":        title.lower().startswith("live"),
        })
    programs.sort(key=lambda p: p["start"], reverse=True)
    return programs


def probe(url, timeout=30):
    """Resolution and bitrate of a stream, via ffprobe. Empty dict on failure."""
    cmd = [
        "ffprobe", "-v", "error", "-rw_timeout", str(timeout * 1_000_000),
        "-select_streams", "v:0",
        "-show_entries", "stream=height:format=bit_rate",
        "-of", "default=noprint_wrappers=1", url,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10).stdout
    except (subprocess.TimeoutExpired, OSError):
        return {}
    info = {}
    for line in out.splitlines():
        key, _, value = line.partition("=")
        if value.isdigit():
            info["height" if key == "height" else "bitrate"] = int(value)
    return info


def resume_plan(start_str, duration_min, got_seconds):
    """What is still missing after a download that ended early.

    ffmpeg ends with exit code 0 when the provider drops the connection, so the
    file length is the only proof that a download is complete. Returns None when
    it is, else (start_str, minutes) for a new timeshift request. timeshift.php
    works per minute, so the restart rounds down: a few seconds overlap instead
    of a gap.
    """
    expected = duration_min * 60
    if got_seconds >= expected - max(10, expected * 0.01):
        return None
    done_min = int(got_seconds // 60)
    start = datetime.strptime(start_str, "%Y-%m-%d:%H-%M") + timedelta(minutes=done_min)
    return start.strftime("%Y-%m-%d:%H-%M"), duration_min - done_min


def media_seconds(path):
    """Playing time of a file in seconds, 0 when it cannot be read."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=60).stdout.strip()
        return float(out)
    except (ValueError, subprocess.TimeoutExpired, OSError):
        return 0.0


SKY_SERVICE_NAME = "SkySp F1 HD"
SKY_SERVICE_FALLBACK = "3835"


def sky_service_id(services):
    """Sky's own id for Sky Sports F1 HD, from awk.epgsky.com/.../services."""
    items = services.get("services", []) if isinstance(services, dict) else services
    for svc in items:
        if svc.get("t") == SKY_SERVICE_NAME:
            return str(svc["sid"])
    return SKY_SERVICE_FALLBACK


def sky_listings(schedule):
    """Guide entries from one day of Sky's schedule API, in the shape of the
    player_api listings. Sky only serves today and later; past days are empty."""
    out = []
    for block in schedule.get("schedule", []) if isinstance(schedule, dict) else []:
        for ev in block.get("events", []):
            start = datetime.fromtimestamp(ev["st"], timezone.utc)
            stop = start + timedelta(seconds=ev["d"])
            out.append({
                "title":           _b64(ev.get("t")),
                "description":     _b64(ev.get("sy")),
                "start":           start.astimezone(AMSTERDAM).strftime("%Y-%m-%d %H:%M:%S"),
                "end":             stop.astimezone(AMSTERDAM).strftime("%Y-%m-%d %H:%M:%S"),
                "start_timestamp": int(start.timestamp()),
                "stop_timestamp":  int(stop.timestamp()),
                "has_archive":     1,
            })
    return out


def merge_history(history, fresh):
    """Add fresh guide entries to the saved ones, keyed by start time; a newer
    entry replaces an older one for the same slot. Returns the merged list."""
    by_start = {int(e["start_timestamp"]): e for e in history}
    for e in fresh:
        by_start[int(e["start_timestamp"])] = e
    return sorted(by_start.values(), key=lambda e: int(e["start_timestamp"]))


def within_window(listings, days, now_ts=None):
    """Entries that started inside the catch-up window; older ones are gone."""
    if now_ts is None:
        now_ts = datetime.now(timezone.utc).timestamp()
    cutoff = now_ts - days * 86400
    return [e for e in listings if int(e["start_timestamp"]) >= cutoff]
