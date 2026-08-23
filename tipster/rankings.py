# -*- coding: utf-8 -*-
"""Rankings de partidos por probabilidad ATLAS (2026-08-16, Tipster ATLAS,
Objetivo 1/2). Reutiliza EXCLUSIVAMENTE probabilidades ya calculadas por los
motores de atlas_pocket (pocket_engine_results.json) y por el estimador de
lambda de mercado ya existente (historical_stats_results.json) -- ningun
modelo nuevo, ninguna cuota/partido/cobertura inventada.

4 rankings independientes, TOP 10 cada uno, JAMAS relleno artificial:
  OVER25          -> OU25_GOALS_FT.probability.over  (motor real BASELINE)
  UNDER25         -> OU25_GOALS_FT.probability.under (motor real BASELINE)
  BTTS            -> hist.btts_general_pct / 100      (dato historico, sin
                      motor -- mismo estatus que ya tiene en el resto de
                      ATLAS LAB, ver disclaimer existente en index.html
                      "BTTS/Corners no tienen edge probado")
  CORNERS_OVER105 -> Poisson(lambda_total, 10.5), lambda_total =
                      hist.home_home_lambda.cornerKicks +
                      hist.away_away_lambda.cornerKicks -- MISMA formula
                      exacta que nonCertLambda()/poissonOverProb() en
                      index.html:2158-2198 (replicada aqui en Python, la
                      MISMA linea que el Director veria si abriera
                      Corners/Tiros de ese partido, no un modelo nuevo).

Diario: partidos cuyo kickoff cae "Hoy" en hora Chile (mismo criterio que
matchWhen()/chileDateLabel() en index.html) -- se regenera en cada corrida
(una vez al dia).

Semanal: ventana rodante de 7 dias desde el dia de generacion. El ranking
semanal vigente NO se recalcula mientras queden partidos sin terminar en su
propio TOP 10 (permanece congelado tal cual quedo el dia que se genero) --
recien cuando TODOS terminaron (verificado contra soccer_analytics.db, mismo
patron que atlas_pocket/trackrecord/resolution.py) se genera uno nuevo para
la siguiente ventana.

Cuota/bookmaker (Objetivo 2, "si existe"): se busca en _work/oddspapi_lean.json
(ya generado por el paso 10 existente, sin ninguna request nueva) -- Corners
nunca tiene cobertura de OddsPapi, la cuota queda null como es esperado.
"""
from __future__ import annotations

import datetime as _dt
import json as _json
import math
import os as _os
import sys
from pathlib import Path

_ROOT_PATH = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT_PATH))

from atlas_lab_mockup.tipster.common import (  # noqa: E402
    ROOT, WORK, chile_date_of, chile_today, load_json, oddspapi_selection_is_valid, save_json, utc_now_iso,
)
from atlas_lab_mockup.tipster.pick_governance import matching_hypothesis  # noqa: E402

# Mapeo mercado-de-ranking -> mercado/motor real esperado por una hipotesis
# congelada (2026-08-22, PICK GOVERNANCE) -- BTTS/CORNERS_OVER105 nunca tienen
# "engine_id" real (son formula/dato historico, ver build_candidates), asi
# que nunca podran coincidir con una hipotesis -- comportamiento correcto,
# no un defecto: ningun estado de gobernanza de pick existe todavia para
# ellos porque nunca pasaron por Gate (ver AUDITORIA_PICK_GOVERNANCE_2026-08-22.md).
_HYPOTHESIS_MARKET = {"OVER25": "OU25_GOALS_FT", "UNDER25": "OU25_GOALS_FT", "BTTS": "BTTS", "CORNERS_OVER105": "OU10.5_CORNERS_FT"}
_HYPOTHESIS_SELECTION = {"OVER25": "over", "UNDER25": "under", "BTTS": "yes", "CORNERS_OVER105": "over"}


def _hypothesis_estado_for(ranking_key: str, candidate: dict) -> str:
    """Anota, sin cambiar el orden ni el contenido del Top 10 (aditivo puro),
    el estado de gobernanza de la hipotesis que cubriria esta señal, si
    existe una. 'SIN_EVALUAR' si ningun hypothesis_id congelado cubre
    todavia este mercado/seleccion -- nunca se inventa un estado."""
    mercado = _HYPOTHESIS_MARKET.get(ranking_key)
    seleccion = _HYPOTHESIS_SELECTION.get(ranking_key)
    motor = candidate.get("engine_id")
    if mercado is None or motor is None:
        return "SIN_EVALUAR"
    hyp = matching_hypothesis(mercado, seleccion, candidate.get("probability"), motor)
    return hyp.estado.value if hyp else "SIN_EVALUAR"

DAILY_STATE_PATH = ROOT + r"\tipster_rankings_daily_estado.json"
WEEKLY_STATE_PATH = ROOT + r"\tipster_rankings_weekly_estado.json"
HISTORY_PATH = ROOT + r"\tipster_rankings_history.jsonl"

TOP_N = 10
WEEKLY_WINDOW_DAYS = 7

MARKETS = ("OVER25", "UNDER25", "BTTS", "CORNERS_OVER105")

_ODDSPAPI_LOOKUP = {
    "OVER25": ("OU25_GOALS_FT", "over"),
    "UNDER25": ("OU25_GOALS_FT", "under"),
    "BTTS": ("BTTS", "yes"),
    "CORNERS_OVER105": None,  # OddsPapi FREE no cubre Corners -- nunca se inventa
}


def _poisson_over_prob(lam, line):
    if lam is None or lam < 0:
        return None
    k_max = math.floor(line)
    cdf = 0.0
    p = math.exp(-lam)
    cdf += p
    for k in range(1, k_max + 1):
        p *= lam / k
        cdf += p
    return max(0.001, min(0.999, 1 - cdf))


def _oddspapi_price(oddspapi_lean, mid, market):
    lookup = _ODDSPAPI_LOOKUP.get(market)
    if not lookup:
        return None, None
    market_code, sel_key = lookup
    entry = (oddspapi_lean or {}).get(mid, {}).get(market_code)
    sel = entry and entry.get("sel", {}).get(sel_key)
    if not sel or not (sel.get("p") and sel["p"] > 1):
        return None, None
    # 2026-08-16, auditoria EV extremo: una cuota inactiva (active/
    # marketActive/bookmakerIsActive=False) no participa en rankings
    # basados en cuota -- mismo camino que "sin cuota" (Objetivo Estados).
    if not oddspapi_selection_is_valid(entry, sel):
        return None, None
    return sel["p"], entry.get("bk")


def build_candidates(pocket, hist, match_list, oddspapi_lean):
    """Devuelve {market: [candidato, ...]} -- solo partidos con probabilidad
    valida del motor/estimador correspondiente, nunca inventada."""
    by_id = {m["id"]: m for m in match_list if "kickoffUTC" in m}
    out = {mkt: [] for mkt in MARKETS}
    for mid, m in by_id.items():
        entry = pocket.get(mid)
        h = hist.get(mid)
        if not entry or not entry.get("resolved"):
            continue
        base = {
            "match_id": mid, "home": m["home"], "away": m["away"],
            "league": m["league"], "kickoff_utc": m["kickoffUTC"],
        }

        goals = (entry.get("markets", {}) or {}).get("OU25_GOALS_FT")
        if goals and "error" not in goals and goals.get("probability"):
            prob = goals["probability"]
            if prob.get("over") is not None:
                price, bk = _oddspapi_price(oddspapi_lean, mid, "OVER25")
                out["OVER25"].append({**base, "market": "OU25_GOALS_FT", "line": 2.5, "selection": "over",
                                       "probability": prob["over"], "engine_id": goals.get("engine_id"),
                                       "governance_status": goals.get("governance_status"),
                                       "price": price, "bookmaker": bk})
            if prob.get("under") is not None:
                price, bk = _oddspapi_price(oddspapi_lean, mid, "UNDER25")
                out["UNDER25"].append({**base, "market": "OU25_GOALS_FT", "line": 2.5, "selection": "under",
                                        "probability": prob["under"], "engine_id": goals.get("engine_id"),
                                        "governance_status": goals.get("governance_status"),
                                        "price": price, "bookmaker": bk})

        if h and h.get("btts_general_pct") is not None:
            price, bk = _oddspapi_price(oddspapi_lean, mid, "BTTS")
            out["BTTS"].append({**base, "market": "BTTS", "line": None, "selection": "yes",
                                 "probability": h["btts_general_pct"] / 100.0, "engine_id": "btts_historico",
                                 "governance_status": None, "price": price, "bookmaker": bk})

        if h:
            hh = (h.get("home_home_lambda") or {}).get("cornerKicks")
            aa = (h.get("away_away_lambda") or {}).get("cornerKicks")
            if hh is not None and aa is not None:
                lam_total = hh + aa
                prob = _poisson_over_prob(lam_total, 10.5)
                if prob is not None:
                    out["CORNERS_OVER105"].append({**base, "market": "OU10.5_CORNERS_FT", "line": 10.5, "selection": "over",
                                                     "probability": prob, "engine_id": "market_lambda_poisson",
                                                     "governance_status": None, "price": None, "bookmaker": None})
    return out


def _top10(candidates):
    ranked = sorted(candidates, key=lambda c: c["probability"], reverse=True)
    return ranked[:TOP_N]  # nunca se rellena si hay menos de 10


def _filter_daily(candidates_by_market, today):
    return {mkt: [c for c in cands if chile_date_of(c["kickoff_utc"]) == today] for mkt, cands in candidates_by_market.items()}


def _filter_window(candidates_by_market, start, end):
    return {mkt: [c for c in cands if start <= chile_date_of(c["kickoff_utc"]) <= end] for mkt, cands in candidates_by_market.items()}


def _append_history(ranking_type, window_key, ranked_by_market, match_event_ids, seen_keys):
    now_iso = utc_now_iso()
    new_lines = []
    for mkt, ranked in ranked_by_market.items():
        for pos, c in enumerate(ranked, start=1):
            ev = (match_event_ids or {}).get(c["match_id"], {})
            event_id = ev.get("event_id")
            # Clave por (market, selection), NUNCA el nombre de bucket interno
            # (mkt="OVER25"/"UNDER25" comparten market="OU25_GOALS_FT") -- debe
            # coincidir EXACTO con la reconstruida en _load_history_keys() a
            # partir del registro ya escrito, o la deduplicacion nunca
            # encuentra coincidencia entre corridas (bug real encontrado en
            # tests: cada corrida volvia a duplicar la entrada diaria).
            key = (ranking_type, c["market"], c["selection"], event_id, window_key)
            if event_id is None or key in seen_keys:
                continue
            seen_keys.add(key)
            ev_pct = None
            if c.get("price"):
                ev_pct = (c["probability"] * c["price"] - 1) * 100
            new_lines.append({
                "ranking_type": ranking_type, "market": c["market"], "line": c["line"], "selection": c["selection"],
                "event_id": event_id, "match_id": c["match_id"], "partido": f"{c['home']} vs {c['away']}",
                "liga": c["league"], "kickoff_utc": c["kickoff_utc"],
                "predicted_at_utc": now_iso, "window_key": window_key,
                "probabilidad_atlas": round(c["probability"], 4), "posicion": pos,
                "cuota": c.get("price"), "bookmaker": c.get("bookmaker"), "ev_pct": round(ev_pct, 2) if ev_pct is not None else None,
                "engine_id": c.get("engine_id"), "governance_status": c.get("governance_status"),
                "estado": "PENDIENTE", "resultado_real": None, "acierto": None,
            })
    return new_lines


def _load_history_keys(path):
    seen = set()
    lines = []
    if not path or not _os.path.exists(path):
        return seen, lines
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = _json.loads(line)
            lines.append(rec)
            seen.add((rec["ranking_type"], rec["market"], rec["selection"], rec["event_id"], rec.get("window_key")))
    return seen, lines


def run(finished_event_ids_fn=None):
    """finished_event_ids_fn: callable(event_ids: list[int]) -> set[int] ya
    finalizados -- inyectable para tests, por defecto usa settlement.py
    (soccer_analytics.db real, solo lectura)."""
    pocket = load_json(WORK + r"\pocket_engine_results.json", {})
    hist = load_json(WORK + r"\historical_stats_results.json", {})
    match_list = load_json(WORK + r"\match_list.json", [])
    match_event_ids = load_json(WORK + r"\match_event_ids.json", {})
    oddspapi_lean = load_json(WORK + r"\oddspapi_lean.json", {})

    candidates_by_market = build_candidates(pocket, hist, match_list, oddspapi_lean)
    today = chile_today()
    seen_keys, _ = _load_history_keys(HISTORY_PATH)
    all_new_lines = []

    # ---- Diario: se regenera SIEMPRE (una vez al dia, ver docstring) ----
    daily_candidates = _filter_daily(candidates_by_market, today)
    daily_ranked = {mkt: _top10(cands) for mkt, cands in daily_candidates.items()}
    daily_window_key = today.isoformat()
    all_new_lines += _append_history("daily", daily_window_key, daily_ranked, match_event_ids, seen_keys)
    save_json(DAILY_STATE_PATH, {
        "generated_at_utc": utc_now_iso(), "ranking_date": daily_window_key,
        "rankings": {mkt: [{"match_id": c["match_id"], "home": c["home"], "away": c["away"], "league": c["league"],
                             "kickoff_utc": c["kickoff_utc"], "probabilidad_atlas": round(c["probability"], 4),
                             "cuota": c.get("price"), "bookmaker": c.get("bookmaker"),
                             "hypothesis_estado": _hypothesis_estado_for(mkt, c)} for c in ranked]
                    for mkt, ranked in daily_ranked.items()},
    })

    # ---- Semanal: se congela hasta que termine el ultimo partido de la
    # ventana vigente (ver docstring) ----
    weekly_state = load_json(WEEKLY_STATE_PATH)
    regenerate = True
    if weekly_state:
        pending_event_ids = sorted({
            e["event_id"] for mkt_entries in weekly_state.get("rankings", {}).values() for e in mkt_entries
            if e.get("event_id") is not None
        })
        if finished_event_ids_fn is None:
            from atlas_lab_mockup.tipster import settlement as _settlement
            finished_event_ids_fn = _settlement.finished_event_ids
        finished = finished_event_ids_fn(pending_event_ids) if pending_event_ids else set()
        still_pending = [eid for eid in pending_event_ids if eid not in finished]
        regenerate = (len(still_pending) == 0)

    if regenerate:
        window_start = today
        window_end = today + _dt.timedelta(days=WEEKLY_WINDOW_DAYS - 1)
        weekly_candidates = _filter_window(candidates_by_market, window_start, window_end)
        weekly_ranked = {mkt: _top10(cands) for mkt, cands in weekly_candidates.items()}
        weekly_window_key = window_start.isoformat()
        all_new_lines += _append_history("weekly", weekly_window_key, weekly_ranked, match_event_ids, seen_keys)
        weekly_out = {
            "generated_at_utc": utc_now_iso(), "window_start": window_start.isoformat(), "window_end": window_end.isoformat(),
            "rankings": {mkt: [{"match_id": c["match_id"], "event_id": (match_event_ids.get(c["match_id"], {}) or {}).get("event_id"),
                                 "home": c["home"], "away": c["away"], "league": c["league"],
                                 "kickoff_utc": c["kickoff_utc"], "probabilidad_atlas": round(c["probability"], 4),
                                 "cuota": c.get("price"), "bookmaker": c.get("bookmaker"),
                                 "hypothesis_estado": _hypothesis_estado_for(mkt, c)} for c in ranked]
                        for mkt, ranked in weekly_ranked.items()},
        }
        save_json(WEEKLY_STATE_PATH, weekly_out)
    else:
        weekly_out = weekly_state

    if all_new_lines:
        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            for rec in all_new_lines:
                f.write(_json.dumps(rec, ensure_ascii=False) + "\n")

    return {"daily_new_entries": len([l for l in all_new_lines if l["ranking_type"] == "daily"]),
            "weekly_regenerated": regenerate,
            "weekly_new_entries": len([l for l in all_new_lines if l["ranking_type"] == "weekly"])}


if __name__ == "__main__":
    print(run())
