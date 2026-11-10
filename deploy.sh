#!/usr/bin/env bash
# Zet de laatste commit live op de Synology (Container Manager), via SSH.
# Zelfde werkwijze als ~/projects/financien/deploy.sh.
#
#   ./deploy.sh    tests, bouwen en herstarten
#
# Werkt thuis of via de VPN. Vereist: SSH-sleutel voor $NAS, sudo-regel voor docker,
# en $DIR/.env met XTREAM_SERVER, XTREAM_USER en XTREAM_PASS.
set -euo pipefail
cd "$(dirname "$0")"

NAS="${NAS:-claude@172.28.9.10}"
HOST="${NAS#*@}"
DIR=/volume1/docker/iptv
DOWNLOADS=/volume1/Video/IPTV
PORT=8774
UID_GID=1037:100   # gebruiker claude, zodat de opnames van claude zijn

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "Er zijn niet-gecommitte wijzigingen. Commit eerst; er gaat alleen een commit live." >&2
  exit 1
fi
REV=$(git rev-parse --short HEAD)

echo "› tests"
.venv/bin/python -m pytest -q

echo "› code $REV naar $HOST"
ssh "$NAS" "test -f $DIR/.env" || { echo "Ontbreekt: $DIR/.env met de Xtream-gegevens." >&2; exit 1; }
ssh "$NAS" "rm -rf $DIR/app.new && mkdir -p $DIR/app.new $DIR/cache $DOWNLOADS"
git archive HEAD | ssh "$NAS" "tar -x -C $DIR/app.new && echo $REV > $DIR/app.new/VERSIE && rm -rf $DIR/app && mv $DIR/app.new $DIR/app"

echo "› bouwen en herstarten"
ssh "$NAS" "set -e
  sudo /usr/local/bin/docker build -q -t iptv:$REV -t iptv:latest $DIR/app >/tmp/iptv-build.log 2>&1 \
    || { cat /tmp/iptv-build.log; exit 1; }
  sudo /usr/local/bin/docker rm -f iptv >/dev/null 2>&1 || true
  sudo /usr/local/bin/docker run -d --name iptv --restart unless-stopped \
    -p $PORT:5123 --user $UID_GID -v $DIR/cache:/cache -v $DOWNLOADS:/downloads \
    --env-file $DIR/.env iptv:$REV >/dev/null"

echo "› controle"
for _ in $(seq 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://$HOST:$PORT/" || true)
  [[ "$code" == 200 ]] && { echo "Live: http://$HOST:$PORT (versie $REV)"; exit 0; }
  sleep 1
done
echo "Server reageert niet zoals verwacht (HTTP $code). Logs: ssh $NAS sudo /usr/local/bin/docker logs iptv" >&2
exit 1
