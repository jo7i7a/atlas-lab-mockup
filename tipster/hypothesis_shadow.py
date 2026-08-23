# -*- coding: utf-8 -*-
"""Señales en Observación / Candidatos -- forward tracking de hipótesis de
Pick Governance (2026-08-22, mandato del Director tras
AUDITORIA_PICK_GOVERNANCE_2026-08-22.md, secciones 14-18).

MÓDULO HERMANO de atlas_pocket/engines/shadow.py -- comparte el ledger
(atlas_pocket.trackrecord.store) y el resolver (atlas_pocket.trackrecord.
resolution, indirectamente vía la resolución automática ya integrada en
store._connect()) sin tocar NINGUNA línea de shadow.py ni alterar su lógica
de negocio (comparación BASELINE-vs-Challenger, mercado 1X2_FT, motores
`form_calculator`/`form_calculator_lineup_challenger`). Nunca se fusionan
-- evita repetir el Defecto de Deduplicación de 2026-08-17 (colisión entre
log_shadow_predictions() y log_analysis_if_changed() sobre la misma tabla).

Namespace de motor SIEMPRE "{engine_id}+pickgov" (NUNCA el engine_id puro) --
reutiliza el mismo patrón de motor compuesto que YA existe en producción
para DC/DNB ("form_calculator+dc_formula", "form_calculator+dnb_formula").
Esto garantiza, para cualquier motor presente o futuro:
  1. NUNCA coincide con SHADOW_MODE_ENGINE_IDS -> la resolución automática
     de store.py (resolution.resolve_track_record(), ya corre sola una vez
     al día en cualquier conexión) SÍ procesa estas filas.
  2. NUNCA es leída por shadow.py::compute_shadow_evidence() (que filtra
     por los IDs exactos de baseline/challenger) -> cero contaminación de
     esa evidencia científica (336+ eventos ya resueltos al 2026-08-22).

Fuente de probabilidad y cuota: los MISMOS artefactos que ya usa
tipster/picks.py (pocket_engine_results.json / oddspapi_lean.json /
match_list.json / match_event_ids.json) -- cero motores nuevos invocados,
cero cuotas inventadas, cero fuga temporal (match_list.json ya viene
filtrado por 01_rebuild_upcoming_matches.py a fixtures genuinamente futuros,
status='notstarted' -- el mismo dato que ya usa Picks ATLAS, jamás un
partido ya jugado).

Inmutabilidad de hipótesis: hypothesis_id se registra tal cual está
congelado en pick_governance_thresholds.json en el momento de la corrida --
esta función NUNCA decide ni modifica el estado/umbral de una hipótesis,
solo registra evidencia bajo el id vigente.
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

_ROOT_PATH = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT_PATH))

from atlas_lab_mockup.tipster.common import WORK, load_json, oddspapi_selection_is_valid  # noqa: E402
from atlas_lab_mockup.tipster.pick_governance import load_hypotheses  # noqa: E402
from atlas_pocket.trackrecord.store import PredictionRecord, log_prediction, _connect as _trackrecord_connect  # noqa: E402

MOTOR_SUFFIX = "+pickgov"

_ODDSPAPI_SELECTION = {
    ("1X2_FT", "home"): "home", ("1X2_FT", "draw"): "draw", ("1X2_FT", "away"): "away",
    ("OU25_GOALS_FT", "over"): "over", ("OU25_GOALS_FT", "under"): "under",
    ("BTTS", "yes"): "yes",
}


def _odds_for(oddspapi_lean, mid, mercado, seleccion):
    odds_sel = _ODDSPAPI_SELECTION.get((mercado, seleccion))
    if odds_sel is None:
        return None
    entry = (oddspapi_lean or {}).get(mid, {}).get(mercado)
    sel = entry and entry.get("sel", {}).get(odds_sel)
    if not sel or not (sel.get("p") and sel["p"] > 1):
        return None
    if not oddspapi_selection_is_valid(entry, sel):
        return None
    return {"price": sel["p"], "bookmaker": entry.get("bk")}


def log_hypothesis_candidates(pocket=None, oddspapi_lean=None, match_list=None, match_event_ids=None) -> dict:
    """Registra en el ledger compartido una fila por cada (fixture futuro,
    hipótesis activa) donde la probabilidad real del motor esperado cumple
    el umbral congelado Y hay cuota real capturada. Idempotente -- nunca
    duplica (event_id, motor+pickgov, hypothesis_id) ya existente. Solo
    evalúa hipótesis con `retirada=false` (una versión retirada nunca vuelve
    a acumular evidencia nueva, aunque su fila permanezca en el archivo)."""
    pocket = pocket if pocket is not None else load_json(WORK + r"\pocket_engine_results.json", {})
    oddspapi_lean = oddspapi_lean if oddspapi_lean is not None else load_json(WORK + r"\oddspapi_lean.json", {})
    match_list = match_list if match_list is not None else load_json(WORK + r"\match_list.json", [])
    match_event_ids = match_event_ids if match_event_ids is not None else load_json(WORK + r"\match_event_ids.json", {})

    hypotheses = [h for h in load_hypotheses() if not h.retirada]
    by_id = {m["id"]: m for m in match_list if "kickoffUTC" in m}

    conn = _trackrecord_connect()
    existing = {(r["event_id"], r["motor"], r["hypothesis_id"]) for r in conn.execute(
        "SELECT DISTINCT event_id, motor, hypothesis_id FROM predictions WHERE hypothesis_id IS NOT NULL"
    ).fetchall()}
    conn.close()

    counts = {"candidatos_evaluados": 0, "registrados": 0, "ya_registrados": 0, "sin_cuota": 0, "motor_no_coincide": 0}

    for mid, m in by_id.items():
        pocket_entry = pocket.get(mid)
        if not pocket_entry or not pocket_entry.get("resolved"):
            continue
        event_id = (match_event_ids or {}).get(mid, {}).get("event_id")
        if event_id is None:
            continue
        pocket_markets = pocket_entry.get("markets", {}) or {}

        for hyp in hypotheses:
            data = pocket_markets.get(hyp.mercado)
            if not data or "error" in data:
                continue
            engine_id = data.get("engine_id")
            if engine_id != hyp.motor_esperado:
                counts["motor_no_coincide"] += 1
                continue  # la hipotesis congelo un motor especifico -- nunca se evalua con otro

            prob = (data.get("probability") or {}).get(hyp.seleccion)
            if prob is None:
                continue
            counts["candidatos_evaluados"] += 1
            if prob < hyp.umbral_prob:
                continue  # no cumple el umbral de ESTA hipotesis -- no es candidato

            motor_key = f"{engine_id}{MOTOR_SUFFIX}"
            key = (event_id, motor_key, hyp.hypothesis_id)
            if key in existing:
                counts["ya_registrados"] += 1
                continue

            odds = _odds_for(oddspapi_lean, mid, hyp.mercado, hyp.seleccion)
            if odds is None:
                counts["sin_cuota"] += 1
                continue  # sin cuota real -> nunca se inventa, no se registra

            implied = 1.0 / odds["price"]
            rec = PredictionRecord(
                event_id=event_id, fecha_partido=str(m["kickoffUTC"])[:10],
                partido=f"{m['home']} vs {m['away']}", mercado=hyp.mercado, seleccion=hyp.seleccion,
                prob_atlas=prob, cuota_justa=(round(1.0 / prob, 3) if prob > 0 else None),
                cuota_mercado=odds["price"], prob_implicita=round(implied, 4), diferencia=round(prob - implied, 4),
                motor=motor_key, version=hyp.hypothesis_id,
                governance_status=data.get("governance_status") or "UNKNOWN",
                competicion=m.get("league"), hypothesis_id=hyp.hypothesis_id,
            )
            log_prediction(rec)
            existing.add(key)
            counts["registrados"] += 1

    return counts


def compute_hypothesis_evidence(hypothesis_id: str) -> dict:
    """N, win rate, ROI, significancia (t-stat) y concentracion por liga para
    UNA hipotesis especifica -- generaliza compute_shadow_evidence() de
    shadow.py (mismo espiritu: veredicto explicito segun N, nunca fecha
    fija) pero mide economia (ROI real vs. cuota real) en vez de calibracion
    (Brier/LogLoss), que es la pregunta que Pick Governance necesita
    responder. Nunca lee/escribe fuera de las filas con este hypothesis_id
    exacto -- no puede tocar evidencia de otra hipotesis ni de Shadow Mode."""
    conn = _trackrecord_connect()
    rows = conn.execute("""
        SELECT p.event_id, p.cuota_mercado, p.competicion, r.acierto
        FROM predictions p JOIN resolutions r ON r.prediction_id = p.prediction_id
        WHERE p.hypothesis_id = ?
    """, (hypothesis_id,)).fetchall()
    conn.close()

    resolved = [r for r in rows if r["acierto"] in ("acierto", "fallo", "push")]
    n = len(resolved)
    if n == 0:
        return {"hypothesis_id": hypothesis_id, "n_resolved": 0,
                "verdict": "insufficient_evidence", "reason": "N=0 -- ninguna señal resuelta todavía"}

    profits, by_league = [], {}
    wins = 0
    for r in resolved:
        cuota = r["cuota_mercado"]
        if r["acierto"] == "acierto":
            wins += 1
            profit = (cuota - 1) if cuota else 0.0
        elif r["acierto"] == "push":
            profit = 0.0
        else:
            profit = -1.0
        profits.append(profit)
        lg = r["competicion"] or "desconocida"
        by_league.setdefault(lg, {"n": 0, "profit": 0.0})
        by_league[lg]["n"] += 1
        by_league[lg]["profit"] += profit

    win_rate = wins / n
    roi = sum(profits) / n
    std = statistics.pstdev(profits) if n > 1 else 0.0
    se = std / (n ** 0.5) if n > 1 else 0.0
    t_stat = (roi / se) if se > 0 else 0.0
    total_profit = sum(profits)
    max_league_abs_profit = max((abs(v["profit"]) for v in by_league.values()), default=0.0)
    concentration_pct = round(max_league_abs_profit / abs(total_profit) * 100, 1) if total_profit != 0 else None
    max_league_n_share_pct = round(max((v["n"] for v in by_league.values()), default=0) / n * 100, 1)

    verdict = "insufficient_evidence"
    reason = f"N resuelto = {n} (< 200 requerido)"
    if n >= 200:
        verdict = "ready_for_candidato_review"
        reason = f"N resuelto = {n} >= 200 -- evaluar promoción a CANDIDATO con los criterios de la sección 15"

    return {
        "hypothesis_id": hypothesis_id, "n_resolved": n, "win_rate": round(win_rate, 4),
        "roi": round(roi, 4), "t_stat": round(t_stat, 3), "n_leagues": len(by_league),
        "max_league_profit_concentration_pct": concentration_pct,
        "max_league_n_share_pct": max_league_n_share_pct,
        "verdict": verdict, "reason": reason,
    }


if __name__ == "__main__":
    print(log_hypothesis_candidates())
