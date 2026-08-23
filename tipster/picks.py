# -*- coding: utf-8 -*-
"""Picks ATLAS (2026-08-16, Tipster ATLAS, Objetivo 3/4/5/7). Flujo:

  partidos futuros -> motores ATLAS (pocket_engine_results.json, ya
  calculado por 01_rebuild_upcoming_matches.py) -> probabilidad ATLAS ->
  cuota disponible (oddspapi_lean.json, ya capturado por
  10_fetch_oddspapi_odds.py -- incluye partidos de varios dias en el futuro,
  ver evidencia real: hasta 13 dias de anticipacion, sin ninguna request
  nueva) -> probabilidad implicita (1/cuota) -> EV% (misma formula exacta
  que el resto de ATLAS LAB: (prob*cuota-1)*100) -> filtro de gobernanza YA
  EXISTENTE (tipster/governance.py, reutilizado de
  atlas_pocket/context/analyst_conclusion.py, sin inventar umbral nuevo) ->
  decision PICK ATLAS.

3 estados distintos, nunca colapsados en uno solo (Objetivo 4):
  CANDIDATO       -> probabilidad ATLAS valida Y cuota real disponible.
  VALUE DETECTADO -> candidato con EV% > 0 (existe valor matematico).
  PICK ATLAS      -> value detectado que ADEMAS pasa el filtro de
                      gobernanza (governance.passes_governance_gate) --
                      un EV positivo por si solo NUNCA se autoconvierte en
                      pick si la gobernanza no corresponde.

Mercados automatizados iniciales (Objetivo 3): 1X2, Over/Under goles,
Asian Handicap, BTTS -- EXACTAMENTE los mismos 4 que ya cubre OddsPapi en
ATLAS LAB, ningun mercado mas. Corners/Cards/SOT/otras lineas siguen
100% manuales, nunca se les inventa cuota aqui.

Registro inmutable (Objetivo 5): pick_id determinista
"{event_id}:{market}:{selection}" -- una vez registrado un PICK, nunca se
vuelve a registrar aunque una corrida posterior recalcule una probabilidad o
cuota distinta (mismo principio de inmutabilidad que rankings.py). El
Director puede tomar o ignorar el pick; eso no afecta este registro."""
from __future__ import annotations

import json as _json
import os as _os
import sys
from pathlib import Path

_ROOT_PATH = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT_PATH))

from atlas_lab_mockup.tipster import governance  # noqa: E402
from atlas_lab_mockup.tipster.common import (  # noqa: E402
    ROOT, WORK, load_json, oddspapi_selection_is_valid, save_json, utc_now_iso,
)

PICKS_STATE_PATH = ROOT + r"\tipster_picks_estado.json"
PICKS_HISTORY_PATH = ROOT + r"\tipster_picks_history.jsonl"

AUTOMATED_MARKETS = ("1X2_FT", "OU25_GOALS_FT", "HANDICAP_FT", "BTTS")

_MARKET_SELECTIONS = {
    "1X2_FT": ("home", "draw", "away"),
    "OU25_GOALS_FT": ("over", "under"),
    "HANDICAP_FT": ("home_covers", "away_covers"),
    "BTTS": ("yes",),
}
# ATLAS usa "home_covers"/"away_covers" para Handicap (ver
# atlas_pocket/trackrecord/resolution.py::_resolve_handicap); OddsPapi usa
# "home"/"away" (ver oddspapi/line_extraction.py) -- mapeo explicito, nunca
# una sustitucion de linea, solo el nombre de la seleccion.
_ODDSPAPI_SELECTION = {
    ("1X2_FT", "home"): "home", ("1X2_FT", "draw"): "draw", ("1X2_FT", "away"): "away",
    ("OU25_GOALS_FT", "over"): "over", ("OU25_GOALS_FT", "under"): "under",
    ("HANDICAP_FT", "home_covers"): "home", ("HANDICAP_FT", "away_covers"): "away",
    ("BTTS", "yes"): "yes",
}

_MARKET_LINE = {"OU25_GOALS_FT": 2.5}  # linea fija; 1X2/BTTS sin linea, Handicap usa market_context (variable por partido)


def _probability_map(market, pocket_entry, hist_entry):
    if market == "BTTS":
        pct = (hist_entry or {}).get("btts_general_pct")
        return ({"yes": pct / 100.0} if pct is not None else {}), None, None
    data = (pocket_entry or {}).get(market)
    if not data or "error" in data:
        return {}, None, None
    return (data.get("probability") or {}), data.get("governance_status"), data.get("engine_id")


def _line_for(market, selection, pocket_entry):
    if market == "HANDICAP_FT":
        ctx = (pocket_entry or {}).get("HANDICAP_FT", {}).get("market_context") or {}
        return (ctx.get("home_line") if selection == "home_covers" else ctx.get("away_line")), ctx
    return _MARKET_LINE.get(market), None


def _odds_for(oddspapi_lean, mid, market, selection):
    odds_sel = _ODDSPAPI_SELECTION[(market, selection)]
    entry = (oddspapi_lean or {}).get(mid, {}).get(market)
    sel = entry and entry.get("sel", {}).get(odds_sel)
    if not sel or not (sel.get("p") and sel["p"] > 1):
        return None
    # 2026-08-16, auditoria EV extremo en Picks ATLAS: una cuota con
    # active=False (por seleccion), marketActive=False o bookmakerIsActive=
    # False NO es una cuota disponible -- sigue exactamente el mismo camino
    # que una cuota inexistente, nunca genera candidato/value/pick.
    if not oddspapi_selection_is_valid(entry, sel):
        return None
    return {"price": sel["p"], "bookmaker": entry.get("bk"), "cuota_timestamp": sel.get("t")}


def build_candidates(pocket, hist, match_list, match_event_ids, oddspapi_lean):
    """Un candidato = probabilidad ATLAS valida Y cuota real ya capturada.
    Sin cuota -> NO es candidato (Objetivo 3: nunca se inventa una cuota
    para evaluar). Cubre partidos de cualquier dia futuro presente en
    pocket/oddspapi_lean -- no se limita a "hoy" (Objetivo 7)."""
    by_id = {m["id"]: m for m in match_list if "kickoffUTC" in m}
    candidates = []
    for mid, m in by_id.items():
        pocket_entry = pocket.get(mid)
        hist_entry = hist.get(mid)
        if not pocket_entry or not pocket_entry.get("resolved"):
            continue
        pocket_markets = pocket_entry.get("markets", {}) or {}
        event_id = (match_event_ids or {}).get(mid, {}).get("event_id")
        if event_id is None:
            continue
        for market in AUTOMATED_MARKETS:
            prob_map, governance_status, engine_id = _probability_map(market, pocket_markets, hist_entry)
            if not prob_map:
                continue
            for selection in _MARKET_SELECTIONS[market]:
                prob = prob_map.get(selection)
                if prob is None:
                    continue
                odds = _odds_for(oddspapi_lean, mid, market, selection)
                if odds is None:
                    continue  # sin cuota real -> no es candidato, nunca se inventa
                line, market_context = _line_for(market, selection, pocket_markets)
                implied_prob = 1.0 / odds["price"]
                ev_pct = (prob * odds["price"] - 1) * 100
                candidates.append({
                    "match_id": mid, "event_id": event_id, "home": m["home"], "away": m["away"],
                    "league": m["league"], "kickoff_utc": m["kickoffUTC"],
                    "market": market, "line": line, "selection": selection,
                    "probability": prob, "governance_status": governance_status, "engine_id": engine_id,
                    "price": odds["price"], "bookmaker": odds["bookmaker"], "cuota_timestamp": odds["cuota_timestamp"],
                    "implied_probability": round(implied_prob, 4), "ev_pct": round(ev_pct, 2),
                    "market_context": market_context,
                })
    return candidates


def classify(candidate):
    """(es_value, es_pick) -- ver docstring del modulo para la distincion
    candidato/value/pick. Gate de Pick ATLAS (2026-08-22, PICK GOVERNANCE):
    unica autoridad es governance.passes_governance_gate(mercado, seleccion,
    probabilidad, motor) -- exige una hipotesis congelada en estado
    CERTIFICADO (tipster/pick_governance.py). EV%>0 sigue siendo la condicion
    de "value", pero YA NO autopromueve a pick por si sola (causa raiz
    corregida de AUDITORIA_PICK_GOVERNANCE_2026-08-22.md)."""
    es_value = candidate["ev_pct"] > 0
    es_pick = es_value and governance.passes_governance_gate(
        candidate["market"], candidate["selection"], candidate["probability"], candidate["engine_id"],
    )
    return es_value, es_pick


def _hypothesis_id_for(candidate):
    from atlas_lab_mockup.tipster.pick_governance import matching_hypothesis
    hyp = matching_hypothesis(candidate["market"], candidate["selection"], candidate["probability"], candidate["engine_id"])
    return hyp.hypothesis_id if hyp else None


def _razon(candidate, es_value, es_pick):
    base = (f"EV%={candidate['ev_pct']:+.1f} = (prob ATLAS {candidate['probability']*100:.1f}% × cuota "
            f"{candidate['price']:.2f} {candidate['bookmaker'] or 'OddsPapi'} − 1) × 100")
    if not es_value:
        return base + f"; sin value (EV%<=0), no se evalúa gobernanza de hipótesis."
    hyp_id = _hypothesis_id_for(candidate)
    if not es_pick:
        if hyp_id is None:
            return base + "; value detectado pero ninguna hipótesis congelada cubre este mercado/selección/umbral -- no es Pick (PICK GOVERNANCE, 2026-08-22)."
        return base + f"; value detectado, hipótesis '{hyp_id}' coincide pero su estado aún no es CERTIFICADO -- no es Pick."
    return base + f"; hipótesis '{hyp_id}' CERTIFICADA -> PICK ATLAS."


def _load_history_keys(path):
    seen = set()
    if not path or not _os.path.exists(path):
        return seen
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = _json.loads(line)
            seen.add((rec["event_id"], rec["market"], rec["selection"]))
    return seen


def _apply_1x2_mutual_exclusion(eligible):
    """Regla de exclusion mutua obligatoria para 1X2 (mandato del Director,
    2026-08-22): nunca puede existir mas de un Pick 1X2 accionable para el
    mismo partido. Determinista y auditable -- agrupa por (event_id, market),
    y para el mercado 1X2_FT con mas de una seleccion elegible, conserva SOLO
    la de mayor EV% (desempate por nombre de seleccion, alfabetico, para que
    el resultado sea 100% reproducible incluso ante un empate exacto de EV%
    -- mismo criterio de ev_pct descendente que index.html ya usa en otras
    listas, ver sección 7.3 del informe). Las NO dominantes NUNCA se
    descartan -- se devuelven aparte para quedar registradas igual en el
    historico inmutable, con su propia razon de exclusion (Condicion 5 del
    mandato: "conservar internamente todas las evaluaciones... conservar la
    razon de exclusion de las demas")."""
    by_match_market = {}
    for c in eligible:
        key = (c["event_id"], c["market"])
        by_match_market.setdefault(key, []).append(c)

    dominant, excluded = [], []
    for (_event_id, market), group in by_match_market.items():
        if market == "1X2_FT" and len(group) > 1:
            group_sorted = sorted(group, key=lambda c: (-c["ev_pct"], c["selection"]))
            dominant.append(group_sorted[0])
            for loser in group_sorted[1:]:
                excluded.append((loser, group_sorted[0]["selection"]))
        else:
            dominant.extend(group)
    return dominant, excluded


def run():
    pocket = load_json(WORK + r"\pocket_engine_results.json", {})
    hist = load_json(WORK + r"\historical_stats_results.json", {})
    match_list = load_json(WORK + r"\match_list.json", [])
    match_event_ids = load_json(WORK + r"\match_event_ids.json", {})
    oddspapi_lean = load_json(WORK + r"\oddspapi_lean.json", {})

    candidates = build_candidates(pocket, hist, match_list, match_event_ids, oddspapi_lean)
    seen = _load_history_keys(PICKS_HISTORY_PATH)
    now_iso = utc_now_iso()

    n_candidatos = len(candidates)
    n_value = 0
    n_picks_nuevos = 0
    new_lines = []
    estado_picks = []

    eligible = []
    razon_by_key = {}
    for c in candidates:
        es_value, es_pick = classify(c)
        if es_value:
            n_value += 1
        razon_by_key[(c["event_id"], c["market"], c["selection"])] = _razon(c, es_value, es_pick)
        if es_pick:
            eligible.append(c)

    dominant, excluded = _apply_1x2_mutual_exclusion(eligible)

    for c in dominant:
        key = (c["event_id"], c["market"], c["selection"])
        pick_id = f"{c['event_id']}:{c['market']}:{c['selection']}"
        estado_picks.append({
            "pick_id": pick_id, "event_id": c["event_id"], "match_id": c["match_id"], "partido": f"{c['home']} vs {c['away']}",
            "liga": c["league"], "kickoff_utc": c["kickoff_utc"], "market": c["market"], "line": c["line"],
            "selection": c["selection"], "probabilidad_atlas": round(c["probability"], 4),
            "cuota": c["price"], "bookmaker": c["bookmaker"], "ev_pct": c["ev_pct"],
        })
        if key in seen:
            continue
        seen.add(key)
        n_picks_nuevos += 1
        new_lines.append({
            "pick_id": pick_id, "event_id": c["event_id"], "match_id": c["match_id"],
            "partido": f"{c['home']} vs {c['away']}", "liga": c["league"], "kickoff_utc": c["kickoff_utc"],
            "market": c["market"], "line": c["line"], "selection": c["selection"],
            "probabilidad_atlas": round(c["probability"], 4), "cuota": c["price"], "bookmaker": c["bookmaker"],
            "ev_pct": c["ev_pct"], "implied_probability": c["implied_probability"],
            "engine_id": c["engine_id"], "governance_status": c["governance_status"],
            "hypothesis_id": _hypothesis_id_for(c),
            "detected_at_utc": now_iso, "cuota_captured_at_utc": c["cuota_timestamp"],
            "razon": razon_by_key[key],
            "market_context_json": _json.dumps(c["market_context"]) if c["market_context"] else None,
            "estado": "PENDIENTE", "resultado_real": None, "acierto": None, "roi_pct": None,
        })

    # Elegibles NO dominantes (exclusion mutua 1X2): se conservan integras en
    # el historico inmutable -- nunca se pierden, nunca se muestran como Pick
    # activo (no entran a estado_picks). Mismo mecanismo de deduplicacion por
    # key que el resto (nunca se re-registra ni se reescribe si ya existia).
    for c, dominant_selection in excluded:
        key = (c["event_id"], c["market"], c["selection"])
        if key in seen:
            continue
        seen.add(key)
        pick_id = f"{c['event_id']}:{c['market']}:{c['selection']}"
        new_lines.append({
            "pick_id": pick_id, "event_id": c["event_id"], "match_id": c["match_id"],
            "partido": f"{c['home']} vs {c['away']}", "liga": c["league"], "kickoff_utc": c["kickoff_utc"],
            "market": c["market"], "line": c["line"], "selection": c["selection"],
            "probabilidad_atlas": round(c["probability"], 4), "cuota": c["price"], "bookmaker": c["bookmaker"],
            "ev_pct": c["ev_pct"], "implied_probability": c["implied_probability"],
            "engine_id": c["engine_id"], "governance_status": c["governance_status"],
            "hypothesis_id": _hypothesis_id_for(c),
            "detected_at_utc": now_iso, "cuota_captured_at_utc": c["cuota_timestamp"],
            "razon": razon_by_key[key] + f" Excluido por regla de exclusión mutua 1X2 (selección dominante del mismo partido: '{dominant_selection}', mayor EV%).",
            "market_context_json": _json.dumps(c["market_context"]) if c["market_context"] else None,
            "estado": "ELEGIBLE_NO_DOMINANTE", "resultado_real": None, "acierto": None, "roi_pct": None,
        })

    if new_lines:
        with open(PICKS_HISTORY_PATH, "a", encoding="utf-8") as f:
            for rec in new_lines:
                f.write(_json.dumps(rec, ensure_ascii=False) + "\n")

    save_json(PICKS_STATE_PATH, {
        "generated_at_utc": now_iso,
        "candidatos_evaluados": n_candidatos, "value_detectado": n_value, "picks_activos": len(estado_picks),
        "picks": sorted(estado_picks, key=lambda p: p["ev_pct"], reverse=True),
    })

    return {"candidatos_evaluados": n_candidatos, "value_detectado": n_value,
            "picks_nuevos": n_picks_nuevos, "picks_activos_total": len(estado_picks)}


if __name__ == "__main__":
    print(run())
