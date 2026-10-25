#!/bin/bash
# TSE Dashboard 2026 — desliga tudo
for f in /tmp/tse_api.pid /tmp/tse_serve.pid; do
  [ -f "$f" ] && PID=$(cat "$f") && kill "$PID" 2>/dev/null && rm "$f" && echo "morto: $PID ($f)"
done
# fallback: matar por porta
for PORT in 8891 8892; do
  PID=$(ss -tlnp 2>/dev/null | grep ":$PORT" | grep -oP 'pid=\K[0-9]+' | head -1)
  [ -n "$PID" ] && kill "$PID" 2>/dev/null && echo "morto: $PID (porta $PORT)"
done
docker rm -f tse2026-api 2>/dev/null && echo "docker container removido"
echo "down completo"