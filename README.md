# TSE Dashboard 2026 — Apuração ao vivo

Dashboard web local pra acompanhar a totalização oficial do TSE (eleições 2026),
com backend FastAPI e frontend estático. Sem dependências além do Docker (backend)
e Python stdlib (frontend).

## Subir

    ./run.sh

- API: http://localhost:8891 (FastAPI, docs em /docs)
- Dashboard: http://localhost:8892

Requisitos: Docker. Alternativa sem Docker:

    cd backend && pip install fastapi "uvicorn[standard]" && uvicorn main:app --port 8891 &
    cd frontend && python3 -m http.server 8892

## Endpoints

- `GET /api/health` — liveness
- `GET /api/config` — config canônico TSE (códigos de eleição)
- `GET /api/resultados?uf=mg&cargo=3` — um cargo numa UF (1=Pres 3=Gov 5=Sen 6=DepFed 7=DepEst 8=DepDist)
- `GET /api/painel?ufs=br,mg` — snapshot agregado pro dashboard (auto-refresh 30s no frontend)

## Fonte

`resultados.tse.jus.br/oficial/` — JSONs de divulgação oficiais (sem chave, sem cadastro).
O config vigente lista os códigos de 2026: **federal 1ºT = 6257** (2ºT = **6258**),
**estadual 1ºT = 6259** (2ºT = **6260**). Cache de 45s por URL (respeita o TSE;
os arquivos só nascem quando a apuração começa, após o fechamento às 17h).

## 2º turno (25/10)

Reaproveite: os códigos do 2º turno já estão no config (6258/6260) — a API
aceita `turno=2`. Só subir de novo os mesmos containers.

## Deletar

    docker stop tse2026-api && docker rmi tse-dashboard-2026 && rm -rf <esta pasta>