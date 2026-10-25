"""
tse_client.py — cliente do feed de divulgação oficial do TSE (resultados.tse.jus.br).

Sem lib de rede (urllib stdlib). Cache local com TTL + conditional request
(If-Modified-Since / If-None-Match → 304 estende o cache) + negative-cache de 404
(404 pré-apuração também é cacheado, senão cada painel refaz N hits mortos).
"""
import time
import json as _json
from typing import Any, Optional
from urllib import request as _ur
from urllib.error import HTTPError

TSE_BASE = "https://resultados.tse.jus.br/oficial"
CONFIG_URL = f"{TSE_BASE}/comum/config/ele-c.json"
UA = "SlopApura/0.2 (projeto local, cache >=270s, sem chave, sem cadastro)"

# ele2026 (do config canônico, dg 02/10/2026): 1ºT federal=6257 / 2ºT=6258; 1ºT estadual=6259 / 2ºT=6260.
ELE2026 = {"federal_1t": "6257", "federal_2t": "6258", "estadual_1t": "6259", "estadual_2t": "6260"}
CARGO_NOMES = {1: "Presidente", 3: "Governador", 5: "Senador", 6: "Dep. Federal", 7: "Dep. Estadual", 8: "Dep. Distrital"}

TTL_DADOS_S = 270   # o painel do front pede a cada 5 min; margem pra requests manuais
CACHE_TTL_S = TTL_DADOS_S
TTL_404_S = 30      # 404 = não publicado OU throttle disfarçado do TSE; recuperar em <=30s, não 270s

_cache: dict[str, tuple[float, Any, str | None, str | None]] = {}  # url -> (ts, data, last-modified, etag)


def _fetch_json(url: str, ttl: float = CACHE_TTL_S) -> Any:
    """GET condicional + cache TTL. 404 → None (ainda não publicado); 304 → cache fresco estendido.
    CDN do TSE cacheia o erro nas rajadas de pico, por isso os headers no-cache."""
    now = time.monotonic()
    hit = _cache.get(url)
    if hit and now - hit[0] < ttl:
        return hit[1]
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
            _cache[url] = (now - (CACHE_TTL_S - TTL_404_S), None, None, None)
            return None
        raise
    _cache[url] = (now, data, lm, etag)
    return data


def eleicao_cod(cargo_cd: int, turno: int = 1) -> str:
    """presidente = eleição federal; governador/senador/deputados = estadual."""
    chave = ("federal" if cargo_cd == 1 else "estadual") + ("_2t" if turno == 2 else "_1t")
    return ELE2026[chave]


def resultado_bruto(uf: str, cargo_cd: int, turno: int = 1) -> Optional[dict]:
    """Estrutura REAL 2026 (validada ao vivo no 1ºT): /dados/<uf>/<uf>-c<cargo>-e<eleicao>-u.json
    (agregado por unidade; br = agregado nacional). O -r (formato 2022) está 404 na 2026."""
    cod = eleicao_cod(cargo_cd, turno)
    uf = uf.lower()
    url = f"{TSE_BASE}/ele2026/{cod}/dados/{uf}/{uf}-c{cargo_cd:04d}-e{int(cod):06d}-u.json"
    return _fetch_json(url)