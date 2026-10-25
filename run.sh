#!/bin/bash
# SLOPAPURA — sobe tudo local sem Docker (venv backend + servidor único python).
# Docker é opcional: backend/Dockerfile. `up.sh` sobe de novo sem rebuild; `down.sh` mata tudo.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -x "$DIR/backend/.venv/bin/uvicorn" ]; then
  echo "venv do backend não existe — criando…"
  python3 -m venv "$DIR/backend/.venv"
  "$DIR/backend/.venv/bin/pip" install -q -r "$DIR/backend/requirements.txt"
fi

# backend (env -u PYTHONPATH: o gateway vaza numpy de outro runtime em venvs de projeto)
(cd "$DIR/backend" && nohup env -u PYTHONPATH .venv/bin/uvicorn main:app --port 8891 --host 0.0.0.0 &> /tmp/tse_api.log & echo $! > /tmp/tse_api.pid)

# frontend + proxy /api (uma porta só: serve.py repassa o que vem de /api/* pro 8891)
nohup env -u PYTHONPATH python3 "$DIR/serve.py" 8892 &> /tmp/tse_serve.log &
echo $! > /tmp/tse_serve.pid

sleep 2
echo "API:  http://localhost:8891/docs"
echo "UI:   http://localhost:8892"
echo "pids: api=$(cat /tmp/tse_api.pid 2>/dev/null), serve=$(cat /tmp/tse_serve.pid 2>/dev/null)"