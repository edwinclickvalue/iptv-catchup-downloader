# IPTV Catch-up Downloader

Local web app to download catch-up/time-shift recordings from an Xtream Codes IPTV provider.

## Features

- **Sky Sports F1 block**: on open, finds the UK Sky Sports F1 stream with catch-up in the highest quality (probed with ffprobe, cached 6 h) and lists every archived programme as a checkbox with its session (VT1–3, qualifying, sprint, race, highlights; read from the EPG description), live/repeat flag and description; selected programmes download one after another
- **Guide fallback**: when `player_api` answers with an empty guide (seen on 1-11-2026), the F1 block reads the provider's `xmltv.php` export instead (cached 15 min; the first load takes ~20 s because the file is ~90 MB)
- **Complete downloads**: ffmpeg exits 0 when the provider hangs up, so the app measures the finished file and fetches the missing rest (up to 6 times, with a few seconds overlap); a file that is still short is reported as `onvolledig (x/y min)` instead of `klaar`
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
