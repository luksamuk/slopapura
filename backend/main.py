"""
TSE 2026 Results API — FastAPI backend.
Puxa os JSONs oficiais (resultados.tse.jus.br/oficial/...) com cache de 45s
(respeitando o TSE), e expõe endpoints agregados pro dashboard.
"""
import os
import time
import asyncio
import json as _json
from datetime import datetime, timezone
from typing import Any, Optional
from urllib import request as _ur
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------- config
TSE_BASE = "https://resultados.tse.jus.br/oficial"
CONFIG_URL = f"{TSE_BASE}/comum/config/ele-c.json"
UA = "tse-dashboard-2026/0.1 (projeto local, cache >=45s)"
# ele2026 1T: federal=6257 (2ºt 6258), estadual=6259 (2ºt 6260) — do config canônico (dg 02/10/2026)
ELE2026 = {"federal_1t": "6257", "federal_2t": "6258", "estadual_1t": "6259", "estadual_2t": "6260"}
CARGO_NOMES = {1: "Presidente", 3: "Governador", 5: "Senador", 6: "Dep. Federal", 7: "Dep. Estadual", 8: "Dep. Distrital"}
TTL_DADOS_S = 270  # 4.5 min: o painel do front pede a cada 5; deixa margem pra requests manuais
CACHE_TTL_S = TTL_DADOS_S

_cache: dict[str, tuple[float, Any, str | None, str | None]] = {}  # url -> (ts, data, lm, etag)


def _fetch_json(url: str, ttl: float = CACHE_TTL_S) -> Any:
    """GET condicional (If-Modified-Since/In-None-Match) + cache TTL.
    404 propagado como None (arquivo ainda não publicado); 304 = cache fresco estendido.
    """
    now = time.monotonic()
    hit = _cache.get(url)
    if hit and now - hit[0] < ttl:
        return hit[1]
    # CDN do TSE cacheia 404 e arquivos defasados nas rajadas de pico (20h) — no-cache força revalidação
    headers = {"User-Agent": UA, "Accept": "application/json", "Cache-Control": "no-cache", "Pragma": "no-cache"}
    if hit:
        if hit[2]: headers["If-Modified-Since"] = hit[2]
        if hit[3]: headers["If-None-Match"] = hit[3]
    req = _ur.Request(url, headers=headers)
    try:
        with _ur.urlopen(req, timeout=20) as r:
            data = _json.loads(r.read().decode("utf-8"))
            lm, etag = r.headers.get("Last-Modified"), r.headers.get("ETag")
    except HTTPError as e:
        if e.code == 304 and hit:
            _cache[url] = (now, hit[1], hit[2], hit[3])  # refresh do timestamp, mantém dados
            return hit[1]
        if e.code == 404:
            # 404 = arquivo não publicado OU throttle disfarçado do TSE (404 em vez de 429).
            # TTL curto (30s) cobre os dois: pré-apuração continua sem marretar o origin,
            # e um 404-for-throttle se recupera em ≤30s em vez de sumir 270s.
            _cache[url] = (now - (CACHE_TTL_S - 30), None, None, None)
            return None
        raise
    _cache[url] = (now, data, lm, etag)
    return data


def _int(s):
    try: return int(str(s).replace(".", "")) if s not in (None, "") else 0
    except ValueError: return 0
def _pct(s):
    try: return float(str(s).replace(".", "").replace(",", ".")) if s not in (None, "") else 0.0
    except ValueError: return 0.0


def _eleicao_cod(cargo_cd: int, uf: str, turno: int = 1) -> str:
    """presidente = federal; governador/senador/deputados = estadual."""
    if cargo_cd == 1:
        return ELE2026["federal_2t" if turno == 2 else "federal_1t"]
    return ELE2026["estadual_2t" if turno == 2 else "estadual_1t"]


def _resultado_bruto(uf: str, cargo_cd: int, turno: int = 1) -> Optional[dict]:
    """Estrutura 2026 REAL (validada ao vivo): /dados/<uf>/<uf>-c<cargo>-e<eleicao>-u.json
    (agregado por unidade federativa; br = agregado nacional). O -r (dados-simplificados)
    do formato 2022 segue 404 na 2026 — o feed vivo usa o bruto navegável carg/agr/par/cand."""
    uf = uf.lower()
    cod = _eleicao_cod(cargo_cd, uf, turno)
    url = f"{TSE_BASE}/ele2026/{cod}/dados/{uf}/{uf}-c{cargo_cd:04d}-e{int(cod):06d}-u.json"
    return _fetch_json(url)


def _blk(raw: dict, k: str) -> dict:
    """Bloco 's'/'e'/'v' do payload: 2026 = dict aninhado, 2022/fixture = escalar. Sempre retorna dict."""
    v = raw.get(k)
    return v if isinstance(v, dict) else {}

def _flatten_bruto(raw: dict, cargo_cd: int) -> list[dict]:
    """Navega a estrutura bruta 2026: carg[].agr[].par[].cand[] (com vice e partido no agr/par)."""
    cands = []
    for carg in raw.get("carg", []):
        if str(carg.get("cd")) != str(cargo_cd):
            continue
        for agr in carg.get("agr", []):
            comp = agr.get("com")
            for par in agr.get("par", []):
                sg = par.get("sg", "")
                for c in par.get("cand", []):
                    c = dict(c)
                    if c.get("cc") is None:
                        c["cc"] = f"{sg} - {comp}" if comp else sg
                    cands.append(c)
    return cands


def _projeta(raw: dict, cands: list[dict], cargo_cd: int) -> tuple[list[dict], str]:
    """Projeção conservadora p/ candidatos ainda SEM selo do TSE (campo e/st vázio).
    P = eleitores em seções pendentes (teto 100% comparecimento+validade = pior caso).
    Maioria (pres/gov/sen): vaga j assegurada se (v_j - v_{vagas+1}) > P.
    Pres: líder que não atinge 50% mesmo com 100% P → 2º turno garantido p/ top2.
    Proporcional: vaga INDIVIDUAL assegurada se v_i > QE pior-caso = (nominais+P)/vagas."""
    e, s = _blk(raw, "e"), _blk(raw, "s")
    te = _int(e.get("te"))
    ts, st = _int(s.get("ts")), _int(s.get("st"))
    pend = max(0, ts - st)
    P_pend = (te * pend / ts) if ts else 0.0
    try:
        vagas = max(1, _int(((raw.get("carg") or [{}])[0]).get("v")))
    except Exception:
        vagas = 1
    votos = [max(0, _int(c.get("votos"))) for c in cands]
    tot = sum(votos)
    nota = ""
    if cargo_cd in (1, 3, 5) and votos and len(votos) > vagas:
        if cargo_cd == 1 and vagas == 1 and tot + P_pend > 0:
            max_lider_pc = (votos[0] + P_pend) / (tot + P_pend) * 100
            if max_lider_pc < 50:
                for c in cands[:2]:
                    c["proj_eleito"], c["proj_tipo"] = True, "2º turno"
                nota = "2º turno matematicamente garantido"
        for j in range(min(vagas, len(votos))):
            rival = votos[vagas] if vagas < len(votos) else 0
            if votos[j] - rival > P_pend:
                cands[j]["proj_eleito"] = True
                cands[j]["proj_tipo"] = cands[j].get("proj_tipo") or "eleito"
                if not nota:
                    nota = f"vantagem de {votos[j]-rival:,.0f} votos > eleitores pendentes ({P_pend:,.0f})"
    elif cargo_cd in (6, 7, 8) and tot > 0 and vagas > 1:
        qe_pc = (tot + P_pend) / vagas
        for i, c in enumerate(cands):
            if votos[i] > qe_pc:
                c["proj_eleito"] = True
                c["proj_tipo"] = "QP indiv."
        if any(c.get("proj_eleito") for c in cands):
            nota = f"QP individual pior-caso: votos > {qe_pc:,.0f}"
    return cands, nota


def _normaliza(raw: Optional[dict], uf: str, cargo_cd: int, limite: int) -> Optional[dict]:
    if not raw:
        return None
    # formato bruto 2026 (carg/agr/par/cand) ou simplificado (-r / fixture: cand top-level)
    if "cand" not in raw and "carg" in raw:
        raw = dict(raw)
        raw["cand"] = _flatten_bruto(raw, cargo_cd)
    cands_sorted = sorted(raw.get("cand", []), key=lambda c: -_int(c.get("vap")))[:limite]
    cands_norm = [{
            "numero": c.get("n"),
            "nome": c.get("nmu") or c.get("nm"),
            "nome_completo": c.get("nm"),
            "partido": (c.get("cc") or "").split(" - ")[0],
            "coligacao": c.get("cc"),
            "vice": c.get("nv") or (c.get("vs") or [{}])[0].get("nm", "") if isinstance(c.get("vs"), list) else c.get("nv"),
            "vice_sq": (c.get("vs") or [{}])[0].get("sqcand") if isinstance(c.get("vs"), list) else None,
            "sqcand": c.get("sqcand"),
            "foto": f"https://divulgacandcontas.tse.jus.br/divulga/rest/v1/candidatura/buscar/foto/2/2026/{c.get('sqcand')}" if c.get("sqcand") else None,
            "nascimento": c.get("dt"),
            "tipo_voto": c.get("dvt"),
            "seq": c.get("seq"),
            "votos": _int(c.get("vap")),
            "pct": _pct(c.get("pvap")),
            "pct_exato": _pct(c.get("pvapn")),
            "situacao": c.get("st") or None,
            "eleito": bool(c.get("e") == "s"),
        } for c in cands_sorted]
    cands_norm, proj_nota = _projeta(raw, cands_norm, cargo_cd)
    return {
        "cargo": CARGO_NOMES.get(cargo_cd, str(cargo_cd)),
        "abrangencia": uf.upper(),
        "atualizado_tse": f"{raw.get('dg','')} {raw.get('hg','')}".strip(),
        "transmissao_tse": raw.get("ht"),
        "apurado_pct": _pct(_blk(raw, "s").get("pst") or raw.get("pst")),
        "secoes": {"totalizadas": _int(_blk(raw, "s").get("st") or raw.get("st")),
                   "total": _int(_blk(raw, "s").get("ts") or raw.get("s")),
                   "instanciadas": _int(_blk(raw, "s").get("si")),
                   "ativas": _int(_blk(raw, "s").get("sa")),
                   "nao_transmitidas": _int(_blk(raw, "s").get("snt"))},
        "eleitorado": {"eleitorado": _int(_blk(raw, "e").get("te") or raw.get("e")),
                       "comparecimento": _int(_blk(raw, "e").get("c") or raw.get("c")),
                       "comparecimento_pct": _pct(_blk(raw, "e").get("pc") or raw.get("pc")),
                       "abstencao_pct": _pct(_blk(raw, "e").get("pa") or raw.get("pa"))},
        "votos": {"validos": _int(_blk(raw, "v").get("vvc") or raw.get("vv")),
                  "validos_nominais": _int(_blk(raw, "v").get("vnom") or 0),
                  "brancos": _int(_blk(raw, "v").get("vb") or raw.get("vb")),
                  "brancos_pct": _pct(_blk(raw, "v").get("pvb") or raw.get("pvb")),
                  "nulos": _int(_blk(raw, "v").get("tvn") or raw.get("tvn")),
                  "nulos_pct": _pct(_blk(raw, "v").get("ptvn") or raw.get("ptvn"))},
        "matematicamente_definido": raw.get("md") == "s" or raw.get("md") == "S",
        "id_geracao": raw.get("idg"),  # muda a cada tick do TSE (detecção de update real)
        "transmissao_tse": raw.get("ht"),
        "eleicao_codigo": raw.get("ele"),
        "turno": raw.get("t"),
        "dados_validos": raw.get("dv") == "s",
        "totalizacao_final": raw.get("tf") == "s",
        "cargo_nome_tse": ((raw.get("carg") or [{}])[0].get("nmn") or None),
        "proj_nota": proj_nota or None,
        "candidatos": cands_norm,
    }


app = FastAPI(title="TSE 2026 Dashboard API", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}


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
    cargo: int = Query(1, description="1=Presidente 3=Governador 5=Senador 6=DepFed 7=DepEst",
                       ge=1, le=8),
    turno: int = Query(1, ge=1, le=2),
    limite: int = Query(12, ge=1, le=60),
):
    cargo_cd = int(cargo)
    if cargo_cd not in CARGO_NOMES:
        raise HTTPException(400, "código de cargo inválido")
    uf = uf.lower() or "br"
    if uf != "br" and cargo_cd != 1 and cargo_cd not in (3, 5, 6, 7, 8):
        raise HTTPException(400, "cargo sem cobertura BR")
    ifuf = uf if uf != "br" else "br"
    try:
        raw = _resultado_bruto(ifuf, cargo_cd, turno)
    except (HTTPError, URLError, TimeoutError) as e:
        raise HTTPException(502, f"erro ao consultar TSE: {e}")
    out = _normaliza(raw, ifuf, cargo_cd, limite)
    if out is None:
        raise HTTPException(404, "arquivo ainda não publicado pelo TSE (apuração começa após 17h)")
    out["poll_ts"] = datetime.now(timezone.utc).isoformat()
    return out


@app.get("/api/demo")
def demo():
    """Fixture real TSE 2022 (presidente BR) pra testar o render do dashboard pré-17h."""
    from pathlib import Path
    fixture = Path(__file__).parent / 'demo_fixture.json'
    if not fixture.exists():
        raise HTTPException(404, "demo_fixture.json não encontrado")
    raw = _json.loads(fixture.read_text())
    return _normaliza(raw, 'br', 1, 12)


def _demo_multi(turno: int = 1) -> dict:
    """Painel MOCK com 5 cards (fixture 2022 clonado) pra validar o layout multicoluna pré-apuração."""
    from pathlib import Path
    fixture = Path(__file__).parent / 'demo_fixture.json'
    raw = _json.loads(fixture.read_text())
    out = []
    for cargo_cd, abr in ((1, 'BR'), (3, 'MG'), (5, 'MG'), (6, 'MG'), (7, 'MG')):
        n = _normaliza(raw, abr.lower(), cargo_cd, 8)
        if n:
            n['cargo'] = f"{CARGO_NOMES[cargo_cd]}"
            n['abrangencia'] = abr
            n['mock'] = True
            out.append(n)
    return {"poll_ts": datetime.now(timezone.utc).isoformat(), "resultados": out, "avisos": ["MOCK de layout — dados do TSE 2022 clonados"]}


@app.get("/api/painel")
def painel(
    ufs: str = Query("br,mg", description="UFs separadas por vírgula (ex: br,mg,sp)"),
    turno: int = Query(1, ge=1, le=2),
    limite: int = Query(12, ge=1, le=60),
    mock: bool = Query(False, description="layout mock de 5 cards (fixture 2022)"),
):
    """Snapshot agregado pro dashboard: presidente BR + governador + senador nas UFs dadas."""
    if mock:
        return _demo_multi(turno)
    out = []
    for uf in [u.strip().lower() for u in ufs.split(",") if u.strip()]:
        cargos = ([3, 5, 6, 7] if uf != "br" else [1])
        for cargo_cd in cargos:
            try:
                raw = _resultado_bruto(uf, cargo_cd, turno)
            except Exception:
                raw = None
            n = _normaliza(raw, uf, cargo_cd, limite)
            if n:
                out.append(n)
    if not out:
        avisos = ["Ainda sem dados publicados pelo TSE — a apuração começa a aparecer quando os arquivos forem gerados."]
    else:
        avisos = ["Fonte: TSE divulg oficial (resultados.tse.jus.br). Parcial, sem projeção.",
                  "Depfederal/DepEstadual: top 12 por votos nominais (o cargo é proporcional — eleição por lista/fator eleitoral)."]
    return {"poll_ts": datetime.now(timezone.utc).isoformat(), "resultados": out, "avisos": avisos}