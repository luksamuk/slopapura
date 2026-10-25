"""
apuracao.py — normalização do payload bruto do TSE + projeção local conservadora.

O feed é STREAM: o TSE REESCREVE o mesmo arquivo a cada lote (URL imutável; carimbo
dg/hg = última totalização daquele cargo). A estrutura 2026 é carg[].agr[].par[].cand[];
a do fixture 2022 é cand[] top-level com s/e/v escalares — daí os fallbacks escalar
junto dos blocos aninhados (o /api/demo testa os dois formatos, que coexistem).
"""
from typing import Optional

from tse_client import CARGO_NOMES

CARGOS_MAJORITARIOS = (1, 3, 5)   # presidente / governador / senador
CARGOS_PROPORCIONAIS = (6, 7, 8)  # deputados


def _int(s) -> int:
    try:
        return int(str(s).replace(".", "")) if s not in (None, "") else 0
    except (ValueError, TypeError):
        return 0


def _pct(s) -> float:
    try:
        return float(str(s).replace(".", "").replace(",", ".")) if s not in (None, "") else 0.0
    except (ValueError, TypeError):
        return 0.0


def _blk(raw: dict, k: str) -> dict:
    """Bloco 's'/'e'/'v': 2026 = dict aninhado, fixture 2022 = escalar. Sempre retorna dict."""
    v = raw.get(k)
    return v if isinstance(v, dict) else {}


def _flatten_bruto(raw: dict, cargo_cd: int) -> list[dict]:
    """Navega carg[].agr[].par[].cand[], promovendo nome de coligação (agr.com) ao candidato."""
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


# ---------------------------------------------------------------- projeção local
def _projeta(raw: dict, cands: list[dict], cargo_cd: int) -> tuple[list[dict], str]:
    """Projeção conservadora p/ candidatos ainda SEM selo do TSE (e/st vazio).
    P = eleitores em seções pendentes, com teto 100% de comparecimento+validade (pior caso).
    Maioria (pres/gov/sen, 1 vaga): vaga j assegurada se (v_j - v_{vagas+1}) > P.
    Pres: líder que não atinge 50% mesmo com 100% de P → 2º turno garantido pro top-2.
    Proporcional: vaga INDIVIDUAL assegurada se v_i > QE pior-caso = (nominais+P)/vagas.
    NUNCA marca bancada partidária (QP real depende do fator eleitoral, muda até o fim)."""
    e_blk, s_blk = _blk(raw, "e"), _blk(raw, "s")
    te = _int(e_blk.get("te") or raw.get("e"))
    ts = _int(s_blk.get("ts") or raw.get("s"))
    st = _int(s_blk.get("st") or raw.get("st"))
    pend = max(0, ts - st)
    p_pend = (te * pend / ts) if ts else 0.0
    try:
        vagas = max(1, _int(((raw.get("carg") or [{}])[0]).get("v")))
    except Exception:
        vagas = 1
    votos = [max(0, _int(c.get("votos"))) for c in cands]
    tot = sum(votos)
    nota = ""
    if cargo_cd in CARGOS_MAJORITARIOS and votos and len(votos) > vagas:
        if cargo_cd == 1 and vagas == 1 and tot + p_pend > 0:
            max_lider_pc = (votos[0] + p_pend) / (tot + p_pend) * 100
            if max_lider_pc < 50:
                for c in cands[:2]:
                    c["proj_eleito"], c["proj_tipo"] = True, "2º turno"
                nota = "2º turno matematicamente garantido"
        for j in range(min(vagas, len(votos))):
            rival = votos[vagas] if vagas < len(votos) else 0
            if votos[j] - rival > p_pend:
                cands[j]["proj_eleito"] = True
                cands[j]["proj_tipo"] = cands[j].get("proj_tipo") or "eleito"
                if not nota:
                    nota = f"vantagem de {votos[j]-rival:,.0f} votos > eleitores pendentes ({p_pend:,.0f})"
    elif cargo_cd in CARGOS_PROPORCIONAIS and tot > 0 and vagas > 1:
        qe_pc = (tot + p_pend) / vagas
        for i, c in enumerate(cands):
            if votos[i] > qe_pc:
                c["proj_eleito"] = True
                c["proj_tipo"] = "QP indiv."
        if any(c.get("proj_eleito") for c in cands):
            nota = f"QP individual pior-caso: votos > {qe_pc:,.0f}"
    return cands, nota


# ---------------------------------------------------------------- normalização
def normaliza(raw: Optional[dict], uf: str, cargo_cd: int, limite: int) -> Optional[dict]:
    if not raw:
        return None
    # formato bruto 2026 (carg/agr/par/cand) ou simplificado (-r / fixture: cand top-level)
    if "cand" not in raw and "carg" in raw:
        raw = dict(raw)
        raw["cand"] = _flatten_bruto(raw, cargo_cd)
    if not (raw.get("cand") or []):
        return None
    cands_sorted = sorted(raw.get("cand", []), key=lambda c: -_int(c.get("vap")))[:limite]
    cands_norm = [{
            "numero": c.get("n"),
            "nome": c.get("nmu") or c.get("nm"),
            "nome_completo": c.get("nm"),
            "partido": (c.get("cc") or "").split(" - ")[0],
            "coligacao": c.get("cc"),
            "vice": (c.get("vs") or [{}])[0].get("nm", "") if isinstance(c.get("vs"), list) else c.get("nv"),
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
        "atualizado_tse": f"{raw.get('dg', '')} {raw.get('hg', '')}".strip(),
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
        "matematicamente_definido": (raw.get("md") or "").lower() == "s",
        "id_geracao": raw.get("idg"),  # muda a cada tick do TSE (detecção de update real)
        "eleicao_codigo": raw.get("ele"),
        "turno": raw.get("t"),
        "dados_validos": raw.get("dv") == "s",
        "totalizacao_final": raw.get("tf") == "s",
        "cargo_nome_tse": ((raw.get("carg") or [{}])[0].get("nmn") or None),
        "proj_nota": proj_nota or None,
        "candidatos": cands_norm,
    }