# IPTV Catch-up Downloader

Local web app to download catch-up/time-shift recordings from an Xtream Codes IPTV provider.

## Features

- **Sky Sports F1 block**: on open, finds the UK Sky Sports F1 stream with catch-up in the highest quality (probed with ffprobe, cached 6 h) and lists every archived programme as a checkbox; selected programmes download one after another
- Browse NL channels with catch-up enabled
- EPG guide per channel (last 3 days) — click a program to auto-fill times
- Manual date/time entry as fallback
- Live ffmpeg download progress in browser
- Downloads saved to `~/Downloads` (configurable)

## Requirements

- Python 3.9+
- [ffmpeg](https://ffmpeg.org/) — `brew install ffmpeg`

## Setup

```bash
git clone https://github.com/yourname/iptv-catchup-downloader
cd iptv-catchup-downloader

pip install -r requirements.txt

cp .env.example .env
# Edit .env with your Xtream credentials
```

## Run

```bash
python3 app.py
```

Open **http://localhost:5123**

## Tests

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest -q
```

## Configuration (`.env`)

| Variable | Description |
|---|---|
| `XTREAM_SERVER` | Full server URL incl. port, e.g. `http://example.com` (add a port only if your provider gives one) |
| `XTREAM_USER` | Xtream username |
| `XTREAM_PASS` | Xtream password |
| `DOWNLOAD_DIR` | Download folder (default: `~/Downloads`) |

> `.env` is git-ignored — never commit your credentials.
