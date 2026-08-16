# -*- coding: utf-8 -*-
"""Settlement de Rankings/Picks ATLAS contra el resultado real ya conocido
(2026-08-16, Tipster ATLAS, Objetivo 2/5/6). Reutiliza el patron y las
funciones YA EXISTENTES de atlas_pocket/trackrecord/resolution.py --
`_load_finished_match_results()` (consulta de solo lectura a
soccer_analytics.db, tablas matches/match_stats -- exactamente el mismo
join por sofascore_event_id que ya usa
atlas_lab_mockup/pipeline/01_rebuild_upcoming_matches.py para finalScore) y
`resolve_prediction()` (para 1X2_FT/HANDICAP_FT/OU25_GOALS_FT, mismos
umbrales `_OU_THRESHOLDS` congelados contra el target real de entrenamiento).

Solo 2 mercados no vienen de ahi porque atlas_pocket no los loguea en su
Track Record propio (ver docstring de resolution.py): BTTS y la linea NO
certificada Over 10.5 Corners (la certificada, 9.5, si esta en
_OU_THRESHOLDS pero con umbral 10 -- Over 10.5 usa umbral 11, calculado
aqui mismo sobre el MISMO `corner_total` que ya expone MatchResult).

Principio de inmutabilidad (Objetivo 2/5): settle_history()/settle_picks()
SOLO completan los campos estado/resultado_real/acierto de una linea
PENDIENTE cuyo partido ya termino -- ningun otro campo (probabilidad, cuota,
bookmaker, posicion, EV%, etc.) se recalcula ni se sobreescribe jamas.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT_PATH = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT_PATH))

from atlas_pocket.trackrecord.resolution import _load_finished_match_results, resolve_prediction  # noqa: E402

# Mercados que atlas_pocket/trackrecord/resolution.py YA sabe resolver --
# se delega directo, sin reimplementar la logica.
_DELEGATED_MARKETS = {"1X2_FT", "DC_FT", "DNB_FT", "HANDICAP_FT", "OU25_GOALS_FT",
                       "OU9.5_CORNERS_FT", "OU24.5_SHOTS_FT", "OU8.5_SOT_FT", "OU4.5_CARDS_FT"}

# Umbral propio SOLO para la linea Over 10.5 Corners (no certificada, no
# esta en _OU_THRESHOLDS de resolution.py a proposito -- esa tupla debe
# coincidir EXACTO con el target de entrenamiento del motor, ver comentario
# ahi). corner_total >= 11 <=> Over 10.5 (>=10 seria Over 9.5, la certificada).
_CORNERS_OVER105_THRESHOLD = 11


def finished_event_ids(event_ids):
    """set[int] de event_ids ya finalizados con marcador conocido -- solo
    lectura contra soccer_analytics.db."""
    if not event_ids:
        return set()
    return set(_load_finished_match_results(list(event_ids)).keys())


def _resolve_btts(seleccion, result):
    actual = "yes" if (result.score_home >= 1 and result.score_away >= 1) else "no"
    return ("acierto" if seleccion == actual else "fallo"), actual


def _resolve_corners_over105(seleccion, result):
    if result.corner_total is None:
        return None, None  # dato no registrado -- pendiente honesto, nunca se inventa
    actual = "over" if result.corner_total >= _CORNERS_OVER105_THRESHOLD else "under"
    return ("acierto" if seleccion == actual else "fallo"), actual


def resolve_entry(market, seleccion, market_context_json, result):
    """Devuelve (acierto, resultado_real) en {'acierto','fallo','push'}, o
    (None, None) si no se puede resolver todavia (dato faltante) -- nunca
    inventa un resultado."""
    if market in _DELEGATED_MARKETS:
        return resolve_prediction(market, seleccion, market_context_json, result)
    if market == "BTTS":
        return _resolve_btts(seleccion, result)
    if market == "OU10.5_CORNERS_FT":
        return _resolve_corners_over105(seleccion, result)
    return None, None


# Mapeo de "acierto" (vocabulario interno de resolve_entry/resolve_prediction)
# al campo `estado` visible -- Rankings (Objetivo 2) pide "pendiente/finalizado"
# + acierto/fallo por separado; Picks ATLAS (Objetivo 5) pide el vocabulario
# de tipster profesional PENDIENTE/GANADO/PERDIDO/ANULADO. Mismo resolver,
# distinto rotulo de salida -- no se duplica logica de resolucion.
_ESTADO_RANKINGS = {"acierto": "FINALIZADO", "fallo": "FINALIZADO", "push": "FINALIZADO"}
_ESTADO_PICKS = {"acierto": "GANADO", "fallo": "PERDIDO", "push": "ANULADO"}


def _roi_pct(acierto, cuota):
    """ROI% a stake=1 unidad -- solo si hay cuota real capturada (Objetivo 6)."""
    if not cuota:
        return None
    if acierto == "acierto":
        return round((cuota - 1) * 100, 2)
    if acierto == "push":
        return 0.0
    return -100.0


def _settle_jsonl(path, estado_map):
    """Reescribe SOLO estado/resultado_real/acierto/roi_pct de las lineas
    PENDIENTE cuyo partido ya termino. Todo lo demas (probabilidad, cuota,
    bookmaker, posicion/razon, etc.) queda identico -- ver docstring del
    modulo, principio de inmutabilidad."""
    if not os.path.exists(path):
        return {"settled": 0, "still_pending": 0}
    with open(path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]

    pending_event_ids = sorted({r["event_id"] for r in records if r.get("estado") == "PENDIENTE" and r.get("event_id") is not None})
    results = _load_finished_match_results(pending_event_ids) if pending_event_ids else {}

    settled = 0
    for r in records:
        if r.get("estado") != "PENDIENTE":
            continue
        result = results.get(r.get("event_id"))
        if result is None:
            continue
        acierto, actual = resolve_entry(r["market"], r["selection"], r.get("market_context_json"), result)
        if acierto is None:
            continue
        r["estado"] = estado_map[acierto]
        r["resultado_real"] = actual
        r["acierto"] = acierto
        if "roi_pct" in r:
            r["roi_pct"] = _roi_pct(acierto, r.get("cuota"))
        settled += 1

    still_pending = sum(1 for r in records if r.get("estado") == "PENDIENTE")
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"settled": settled, "still_pending": still_pending}


def settle_history(history_path=None):
    from atlas_lab_mockup.tipster.rankings import HISTORY_PATH
    return _settle_jsonl(history_path or HISTORY_PATH, _ESTADO_RANKINGS)


def settle_picks(picks_history_path=None):
    from atlas_lab_mockup.tipster.picks import PICKS_HISTORY_PATH
    return _settle_jsonl(picks_history_path or PICKS_HISTORY_PATH, _ESTADO_PICKS)


def prune_settled_picks_from_estado(picks_estado_path=None, picks_history_path=None):
    """2026-08-16, ciclo de settlement intraday (Objetivo: 'Picks activos'
    debe reflejar solo lo que sigue PENDIENTE). Quita de
    tipster_picks_estado.json (la lista "picks activos" que consume
    index.html) cualquier pick_id que settle_picks() ya haya liquidado
    (estado != PENDIENTE) en tipster_picks_history.jsonl -- NUNCA liquida
    nada aqui, NUNCA reescribe el jsonl, NUNCA recalcula probabilidad/
    cuota/EV. picks.py sigue siendo el UNICO que agrega picks nuevos a este
    archivo; esta funcion solo depura lo que ya se resolvio, para no tener
    que re-ejecutar picks.py (motores/OddsPapi) cada 30-60 min. Devuelve
    cuantos picks se quitaron (0 si no habia nada que quitar -- estado.json
    NO se reescribe en ese caso, para no generar un diff de git vacio)."""
    from atlas_lab_mockup.tipster.picks import PICKS_HISTORY_PATH, PICKS_STATE_PATH
    estado_path = picks_estado_path or PICKS_STATE_PATH
    history_path = picks_history_path or PICKS_HISTORY_PATH
    if not os.path.exists(estado_path) or not os.path.exists(history_path):
        return 0

    settled_ids = set()
    with open(history_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("estado") != "PENDIENTE":
                settled_ids.add(rec["pick_id"])
    if not settled_ids:
        return 0

    with open(estado_path, encoding="utf-8") as f:
        estado = json.load(f)
    picks = estado.get("picks", [])
    remaining = [p for p in picks if p["pick_id"] not in settled_ids]
    removed = len(picks) - len(remaining)
    if removed:
        estado["picks"] = remaining
        estado["picks_activos"] = len(remaining)
        with open(estado_path, "w", encoding="utf-8") as f:
            json.dump(estado, f, ensure_ascii=False, indent=1)
    return removed


def _breakdown(records, key):
    groups = {}
    for r in records:
        g = groups.setdefault(r[key], {"total": 0, "ganados": 0, "perdidos": 0, "_roi_sum": 0.0, "_roi_n": 0})
        g["total"] += 1
        if r["estado"] == "GANADO":
            g["ganados"] += 1
        elif r["estado"] == "PERDIDO":
            g["perdidos"] += 1
        if r.get("roi_pct") is not None:
            g["_roi_sum"] += r["roi_pct"]
            g["_roi_n"] += 1
    return {
        k: {"total": v["total"], "ganados": v["ganados"], "perdidos": v["perdidos"],
            "roi_pct": round(v["_roi_sum"] / v["_roi_n"], 2) if v["_roi_n"] else None}
        for k, v in groups.items()
    }


def performance_summary(picks_history_path=None):
    """Rentabilidad historica del Tipster ATLAS (Objetivo 6) -- se calcula
    SIEMPRE sobre tipster_picks_history.jsonl (registro inmutable), nunca
    sobre candidatos/value no promovidos a pick. Yield% == ROI% aqui porque
    el stake es constante (1 unidad por pick, sin gestion de capital) --
    misma definicion, un solo numero."""
    from atlas_lab_mockup.tipster.picks import PICKS_HISTORY_PATH
    path = picks_history_path or PICKS_HISTORY_PATH
    empty = {"total": 0, "ganados": 0, "perdidos": 0, "anulados": 0, "pendientes": 0,
             "win_rate_pct": None, "roi_pct": None, "yield_pct": None, "ev_medio_pct": None,
             "por_mercado": {}, "por_liga": {}}
    if not os.path.exists(path):
        return empty
    with open(path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    if not records:
        return empty

    ganados = sum(1 for r in records if r["estado"] == "GANADO")
    perdidos = sum(1 for r in records if r["estado"] == "PERDIDO")
    anulados = sum(1 for r in records if r["estado"] == "ANULADO")
    pendientes = sum(1 for r in records if r["estado"] == "PENDIENTE")
    roi_vals = [r["roi_pct"] for r in records if r.get("roi_pct") is not None]
    win_rate = round(100 * ganados / (ganados + perdidos), 1) if (ganados + perdidos) > 0 else None
    roi = round(sum(roi_vals) / len(roi_vals), 2) if roi_vals else None
    ev_medio = round(sum(r["ev_pct"] for r in records) / len(records), 2)

    return {
        "total": len(records), "ganados": ganados, "perdidos": perdidos, "anulados": anulados, "pendientes": pendientes,
        "win_rate_pct": win_rate, "roi_pct": roi, "yield_pct": roi, "ev_medio_pct": ev_medio,
        "por_mercado": _breakdown(records, "market"), "por_liga": _breakdown(records, "liga"),
    }


if __name__ == "__main__":
    print("rankings:", settle_history())
    print("picks:", settle_picks())
