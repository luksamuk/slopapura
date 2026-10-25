#!/bin/bash
# TSE Dashboard 2026 — sobe tudo local (sem Docker = modo dev; com Docker = opcional)
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

# se Docker existir e preferir: docker build -t tse-dashboard-2026 "$DIR/backend" && docker run -d --rm --name tse2026-api -p 8891:8891 tse-dashboard-2026
# modo dev (sem Docker) usa venv local:

if [ ! -d "$DIR/backend/.venv" ]; then
  python3 -m venv "$DIR/backend/.venv"
  "$DIR/backend/.venv/bin/pip" install -q fastapi "uvicorn[standard]"
fi

# backend
if [ -f "$DIR/backend/.venv/bin/uvicorn" ]; then
  (cd "$DIR/backend" && .venv/bin/uvicorn main:app --port 8891 --host 0.0.0.0 &> /tmp/tse_api.log & echo $! > /tmp/tse_api.pid)
fi

# frontend+proxy único
nohup python3 "$DIR/serve.py" 8892 &> /tmp/tse_serve.log &
echo $! > /tmp/tse_serve.pid

sleep 2
echo "API:  http://localhost:8891/docs"
echo "UI:   http://localhost:8892"
echo "pids: api=$(cat /tmp/tse_api.pid 2>/dev/null), serve=$(cat /tmp/tse_serve.pid 2>/dev/null)"