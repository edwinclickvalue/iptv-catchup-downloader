"""Sky Sports F1 block: find the best UK Sky Sports F1 stream with catch-up
and list the programmes that can be downloaded from it."""
import base64
import re
import subprocess
from datetime import datetime, timezone

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
        })
    return found


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
        programs.append({
            "title":       _decode(e.get("title", "")),
            "description": _decode(e.get("description", "")),
            "start":       e.get("start", ""),
            "end":         e.get("end", ""),
            "live":        _decode(e.get("title", "")).lower().startswith("live"),
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
