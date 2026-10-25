"""
main.py — FastAPI: rotas agregadas pro dashboard.

A fonte e o cache vivem em tse_client.py; normalização e projeção em apuracao.py.
Endpoints:
  GET /api/health                    liveness
  GET /api/config                    config canônico TSE (códigos de eleição do ciclo)
  GET /api/resultados?uf=&cargo=&turno=   um cargo numa UF
  GET /api/demo                      fixture real TSE 2022 (render pré-apuração)
  GET /api/painel?ufs=&turno=        snapshot agregado pro dashboard (mock=true = layout)
"""
import json as _json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from apuracao import normaliza
from tse_client import CONFIG_URL, CARGO_NOMES, _fetch_json, resultado_bruto

FIXTURE = Path(__file__).parent / "demo_fixture.json"

app = FastAPI(title="SlopApura — API da apuração TSE 2026", version="0.2")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.get("/api/health")
def health():
    return {"ok": True, "time": _agora()}


@app.get("/api/config")
def config():
    """Config canônico TSE (códigos de eleição do ciclo corrente)."""
    try:
        return _fetch_json(CONFIG_URL, ttl=300)
    except Exception as e:
        raise HTTPException(502, f"config TSE indisponível: {e}")


@app.get("/api/resultados")
def resultados(
    uf: str = Query("br", description="Sigla da UF ou 'br'"),
    cargo: int = Query(1, description="1=Presidente 3=Governador 5=Senador 6=DepFed 7=DepEst 8=DepDist", ge=1, le=8),
    turno: int = Query(1, ge=1, le=2),
    limite: int = Query(12, ge=1, le=60),
):
    cargo_cd = int(cargo)
    if cargo_cd not in CARGO_NOMES:
        raise HTTPException(400, "código de cargo inválido")
    uf = (uf or "br").lower()
    try:
        raw = resultado_bruto(uf, cargo_cd, turno)
    except (HTTPError, URLError, TimeoutError) as e:
        raise HTTPException(502, f"erro ao consultar TSE: {e}")
    out = normaliza(raw, uf, cargo_cd, limite)
    if out is None:
        raise HTTPException(404, "arquivo ainda não publicado pelo TSE (apuração começa após 17h)")
    out["poll_ts"] = _agora()
    return out


def _fixture() -> dict:
    if not FIXTURE.exists():
        raise HTTPException(404, "demo_fixture.json não encontrado")
    return _json.loads(FIXTURE.read_text())


@app.get("/api/demo")
def demo():
    """Fixture real TSE 2022 (presidente BR) pra testar o render do dashboard pré-17h."""
    return normaliza(_fixture(), "br", 1, 12)


def _demo_multi(turno: int = 1) -> dict:
    """Painel MOCK com 5 cards (fixture 2022 clonado) pra validar o layout multicoluna."""
    raw = _fixture()
    out = []
    for cargo_cd, abr in ((1, "BR"), (3, "MG"), (5, "MG"), (6, "MG"), (7, "MG")):
        n = normaliza(raw, abr.lower(), cargo_cd, 8)
        if n:
            n["cargo"], n["abrangencia"], n["mock"] = CARGO_NOMES[cargo_cd], abr, True
            out.append(n)
    return {"poll_ts": _agora(), "resultados": out,
            "avisos": ["MOCK de layout — dados do TSE 2022 clonados"]}


@app.get("/api/painel")
def painel(
    ufs: str = Query("br,mg", description="UFs separadas por vírgula (ex: br,mg,sp)"),
    turno: int = Query(1, ge=1, le=2),
    limite: int = Query(12, ge=1, le=60),
    mock: bool = Query(False, description="layout mock de 5 cards (fixture 2022)"),
):
    """Snapshot agregado pro dashboard: presidente BR (+ governador/senador/deps nas UFs dadas).
    Em 2º turno só existem arquivos pros cargos em disputa (presidente BR + governador);
    os finalizados no 1ºT simplesmente não aparecem (404 no feed do 2ºT)."""
    if mock:
        return _demo_multi(turno)

    def _normaliza_silencioso(uf: str, cargo_cd: int):
        try:
            return normaliza(resultado_bruto(uf, cargo_cd, turno), uf, cargo_cd, limite)
        except Exception:
            return None

    alvos = []
    for uf in [u.strip().lower() for u in ufs.split(",") if u.strip()]:
        for cargo_cd in ([1] if uf == "br" else [3, 5, 6, 7]):
            alvos.append((uf, cargo_cd))
    # fetch paralelo (o cache fica no tse_client por URL) — 27 UFs × 4 cargos em série estouraria
    # o timeout de 25s do proxy do front na primeira passada fria
    out = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futuros = [ex.submit(_normaliza_silencioso, uf, c) for uf, c in alvos]
        out = [n for n in (f.result() for f in futuros) if n]  # ordem de submissão = ordem UFs/cargos
    if not out:
        avisos = ["Ainda sem dados publicados pelo TSE — a apuração começa a aparecer quando os arquivos forem gerados. "
                  "Histórico: entre 17h30 e 18h15 no dia D." + (" Em 2º turno, só cargos em disputa aparecem." if turno == 2 else "")]
    else:
        avisos = ["Fonte: TSE divulga oficial (resultados.tse.jus.br) — parciais oficiais.",
                  "Projeção local (não oficial) aparece como dica ciano 'eleito (proj.)': só impossibilidade matemática no pior caso.",
                  "Deputados: top N por votos nominais (o cargo é proporcional — eleição por quociente/fator eleitoral, fechada pelo TSE no fim)."]
    return {"poll_ts": _agora(), "resultados": out, "avisos": avisos}