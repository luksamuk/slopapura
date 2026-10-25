#!/bin/bash
# Docker Compose equivalente — subiu o backend e o servidor estático do frontend
docker build -t tse-dashboard-2026 backend/
docker run -d --rm --name tse2026-api -p 8891:8891 tse-dashboard-2026
# frontend: python http.server (sem imagem, serve o static/)
cd "$(dirname "$0")/frontend" && python3 -m http.server 8892 --bind 0.0.0.0