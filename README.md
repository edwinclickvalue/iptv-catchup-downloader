# IPTV Catch-up Downloader

Local web app to download catch-up/time-shift recordings from an Xtream Codes IPTV provider.

## Features

- **Sky Sports F1 block**: on open, finds the UK Sky Sports F1 stream with catch-up in the highest quality (probed with ffprobe, cached 6 h) and lists every archived programme as a checkbox with its session (VT1–3, qualifying, sprint, race, highlights; read from the EPG description), live/repeat flag and description; selected programmes download one after another
- **Guide fallback**: the F1 block asks `player_api`, then the provider's `xmltv.php` (~90 MB, cached 15 min), then Sky's own schedule API (`awk.epgsky.com`, only today and later). The first source with entries wins and is merged into `.cache/guide.json` (git-ignored), so programmes of the last days stay listed after the sources stop serving them. A failing source counts as empty instead of breaking the page
- **Vernieuwen button**: reloads the F1 programme list without reloading the page and skips the 15 min guide cache (`/api/f1?refresh=1`); the measured best channel is kept
- **Queue on the server**: selected programmes wait in a queue in the app itself and download one at a time, so the browser can be closed; a reopened page shows per programme `in wachtrij`, the progress, `klaar` or `onvolledig` (`/api/downloads`). The queue is kept in memory: a restart or deploy empties it
- **Automatic race download** (`AUTO_RACE=1`, set on the NAS by `deploy.sh`; off locally): every 15 min the app looks in the guide for a live race broadcast on Sky Sports F1 that has ended and queues it by itself, with 30 min added to the slot for a race that runs over. Repeats, qualifying, sprint and the shows around the race are left out. A race already on disk is skipped, an incomplete one is tried up to 3 times, and `auto.json` in the cache folder remembers what was fetched over a restart. Tunable with `AUTO_CHECK_MINUTES` and `AUTO_EXTRA_MINUTES`
- **Gedownload overview**: a card that opens on click lists every `.ts` in the download folder, newest first, with broadcast time (from the file name), size and download time; read from disk (`/api/files`), so it also shows recordings from before a restart and from the automatic download
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

## On the Synology NAS

Runs as a Docker container on the NAS, the same way as the household budget app:

```bash
./deploy.sh
```

Runs the tests, copies the last commit over SSH (tar), builds the image and restarts container `iptv`. Only committed code goes live.

| What | Where |
|---|---|
| App | http://172.28.9.10:8774 (home network or VPN only; no password) |
| Recordings | `/volume1/Video/IPTV` |
| Guide history | `/volume1/docker/iptv/cache` |
| Credentials | `/volume1/docker/iptv/.env` (`XTREAM_SERVER`, `XTREAM_USER`, `XTREAM_PASS`) |

After changing `.env`, run `./deploy.sh` again: the container must be recreated to read it. Logs: `ssh claude@172.28.9.10 sudo /usr/local/bin/docker logs iptv`.

The container sets `HOST=0.0.0.0`, `DOWNLOAD_DIR=/downloads` and `CACHE_DIR=/cache`; run locally, the app keeps `127.0.0.1:5123`, `~/Downloads` and `.cache/`.
