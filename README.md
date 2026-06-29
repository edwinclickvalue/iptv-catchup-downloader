# IPTV Catch-up Downloader

Local web app to download catch-up/time-shift recordings from an Xtream Codes IPTV provider.

## Features

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

## Configuration (`.env`)

| Variable | Description |
|---|---|
| `XTREAM_SERVER` | Full server URL incl. port, e.g. `http://example.com:8080` |
| `XTREAM_USER` | Xtream username |
| `XTREAM_PASS` | Xtream password |
| `DOWNLOAD_DIR` | Download folder (default: `~/Downloads`) |

> `.env` is git-ignored — never commit your credentials.
