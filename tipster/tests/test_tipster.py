# -*- coding: utf-8 -*-
"""Tests de atlas_lab_mockup/tipster/ (Tipster ATLAS, 2026-08-16). Patron
pytest ya usado en atlas_lab_mockup/oddspapi/tests/test_oddspapi.py:
monkeypatch + tmp_path, datos sinteticos, sin red/DB real -- las funciones
que consultan soccer_analytics.db (finished_event_ids/settle_*) se
inyectan/monkeypatchean, nunca se golpea la base real en un test."""
import datetime
import json
import os
from pathlib import Path

import pytest

from atlas_lab_mockup.tipster import common, governance, hypothesis_shadow, picks, pick_governance, rankings, settlement


def _hyp(hypothesis_id="AWAY_1X2_P50_V1", mercado="1X2_FT", seleccion="away",
         motor_esperado="form_calculator", umbral_prob=0.50,
         estado=pick_governance.HypothesisStatus.CERTIFICADO, retirada=False):
    return pick_governance.Hypothesis(
        hypothesis_id=hypothesis_id, mercado=mercado, seleccion=seleccion,
        motor_esperado=motor_esperado, umbral_prob=umbral_prob, estado=estado, retirada=retirada,
    )


# ---------------------------------------------------------------------
# pick_governance.py (2026-08-22, PICK GOVERNANCE -- REEMPLAZA el criterio
# "EV%>0 + familia con gobernanza fuerte" que quedo RECHAZADO por el
# Director tras AUDITORIA_PICK_GOVERNANCE_2026-08-22.md)
# ---------------------------------------------------------------------

def test_matching_hypothesis_encuentra_coincidencia_exacta():
    h = _hyp()
    found = pick_governance.matching_hypothesis("1X2_FT", "away", 0.55, "form_calculator", hypotheses=[h])
    assert found is h


def test_matching_hypothesis_prob_bajo_umbral_no_coincide():
    h = _hyp(umbral_prob=0.50)
    found = pick_governance.matching_hypothesis("1X2_FT", "away", 0.45, "form_calculator", hypotheses=[h])
    assert found is None


def test_matching_hypothesis_motor_distinto_no_coincide():
    h = _hyp(motor_esperado="form_calculator")
    found = pick_governance.matching_hypothesis("1X2_FT", "away", 0.60, "otro_motor", hypotheses=[h])
    assert found is None


def test_matching_hypothesis_mercado_o_seleccion_distinta_no_coincide():
    h = _hyp(mercado="1X2_FT", seleccion="away")
    assert pick_governance.matching_hypothesis("1X2_FT", "home", 0.60, "form_calculator", hypotheses=[h]) is None
    assert pick_governance.matching_hypothesis("OU25_GOALS_FT", "away", 0.60, "form_calculator", hypotheses=[h]) is None


def test_matching_hypothesis_ignora_hipotesis_retirada():
    h = _hyp(retirada=True)
    found = pick_governance.matching_hypothesis("1X2_FT", "away", 0.60, "form_calculator", hypotheses=[h])
    assert found is None


def test_matching_hypothesis_sin_prob_ni_motor_no_coincide():
    h = _hyp()
    assert pick_governance.matching_hypothesis("1X2_FT", "away", None, "form_calculator", hypotheses=[h]) is None
    assert pick_governance.matching_hypothesis("1X2_FT", "away", 0.60, None, hypotheses=[h]) is None


def test_passes_pick_gate_solo_certificado_pasa():
    assert pick_governance.passes_pick_gate(_hyp(estado=pick_governance.HypothesisStatus.CERTIFICADO)) is True
    assert pick_governance.passes_pick_gate(_hyp(estado=pick_governance.HypothesisStatus.CANDIDATO)) is False
    assert pick_governance.passes_pick_gate(_hyp(estado=pick_governance.HypothesisStatus.EN_OBSERVACION)) is False
    assert pick_governance.passes_pick_gate(_hyp(estado=pick_governance.HypothesisStatus.SUSPENDIDO)) is False
    assert pick_governance.passes_pick_gate(_hyp(estado=pick_governance.HypothesisStatus.NO_BACKTESTEABLE)) is False
    assert pick_governance.passes_pick_gate(None) is False


def test_load_hypotheses_archivo_ausente_devuelve_vacio(tmp_path):
    # Comportamiento seguro por defecto: sin config, ninguna senal puede
    # convertirse en Pick (nunca "falla abierto").
    assert pick_governance.load_hypotheses(str(tmp_path / "no_existe.json")) == []


def test_load_hypotheses_lee_el_archivo_real_de_produccion():
    # El archivo real debe tener, como minimo, la hipotesis piloto congelada
    # por el Director (2026-08-22): 1X2 Visita >=50%, EN_OBSERVACION, nunca
    # CERTIFICADO todavia -- si esto falla, algo modifico el archivo de forma
    # que rompe la garantia de "ningun pick sin certificacion".
    hyps = pick_governance.load_hypotheses()
    pilot = next(h for h in hyps if h.hypothesis_id == "AWAY_1X2_P50_V1")
    assert pilot.mercado == "1X2_FT" and pilot.seleccion == "away"
    assert pilot.motor_esperado == "form_calculator"
    assert pilot.umbral_prob == pytest.approx(0.50)
    assert pilot.estado == pick_governance.HypothesisStatus.EN_OBSERVACION
    assert pilot.retirada is False
    assert not any(h.estado == pick_governance.HypothesisStatus.CERTIFICADO for h in hyps)  # ninguna certificada todavia


# ---------------------------------------------------------------------
# governance.py -- ahora delega 100% en pick_governance.py
# ---------------------------------------------------------------------

def test_strong_governance_son_los_3_valores_reales():
    # Se preserva solo por compatibilidad de lectura/documentacion -- ya NO
    # decide si algo es Pick (ver test_gate_* abajo).
    assert governance.STRONG_GOVERNANCE == ("CERTIFICADO", "PROMOVIDO", "BASELINE")


def test_gate_sin_hipotesis_congelada_nunca_pasa(monkeypatch):
    monkeypatch.setattr(pick_governance, "load_hypotheses", lambda path=None: [])
    assert governance.passes_governance_gate("1X2_FT", "away", 0.90, "form_calculator") is False


def test_gate_hipotesis_en_observacion_nunca_pasa(monkeypatch):
    # Decision explicita del Director 2026-08-22: rechaza por completo el
    # criterio anterior (EV>0+gobernanza de familia autopromueve). Una
    # hipotesis EN_OBSERVACION, aunque coincida exacto, NUNCA es Pick.
    monkeypatch.setattr(pick_governance, "load_hypotheses", lambda path=None: [_hyp(estado=pick_governance.HypothesisStatus.EN_OBSERVACION)])
    assert governance.passes_governance_gate("1X2_FT", "away", 0.90, "form_calculator") is False


def test_gate_hipotesis_certificada_pasa(monkeypatch):
    monkeypatch.setattr(pick_governance, "load_hypotheses", lambda path=None: [_hyp(estado=pick_governance.HypothesisStatus.CERTIFICADO)])
    assert governance.passes_governance_gate("1X2_FT", "away", 0.90, "form_calculator") is True


def test_gate_btts_sin_hipotesis_ya_no_pasa_por_defecto(monkeypatch):
    # REVERSION explicita de la decision de 2026-08-16 ("BTTS puede ser pick
    # sin gobernanza"): tras el backtest de AUDITORIA_PICK_GOVERNANCE_2026-
    # 08-22.md (ROI negativo en las 8 bandas de probabilidad, N=29447), el
    # Director rechazo ese criterio. BTTS, como cualquier otro mercado, solo
    # puede ser pick con una hipotesis CERTIFICADA -- hoy no existe ninguna.
    monkeypatch.setattr(pick_governance, "load_hypotheses", lambda path=None: [])
    assert governance.passes_governance_gate("BTTS", "yes", 0.65, "btts_historico") is False


# ---------------------------------------------------------------------
# common.py -- oddspapi_selection_is_valid (auditoria EV extremo 2026-08-16)
# ---------------------------------------------------------------------

def test_oddspapi_selection_active_false_es_invalida():
    market_entry = {"bk": "Pinnacle", "bookmakerIsActive": True}
    sel_entry = {"p": 28.56, "t": "T", "active": False, "marketActive": True}
    assert common.oddspapi_selection_is_valid(market_entry, sel_entry) is False


def test_oddspapi_selection_market_active_false_es_invalida():
    market_entry = {"bk": "Pinnacle", "bookmakerIsActive": True}
    sel_entry = {"p": 28.56, "t": "T", "active": True, "marketActive": False}
    assert common.oddspapi_selection_is_valid(market_entry, sel_entry) is False


def test_oddspapi_selection_bookmaker_is_active_false_es_invalida():
    market_entry = {"bk": "Pinnacle", "bookmakerIsActive": False}
    sel_entry = {"p": 28.56, "t": "T", "active": True, "marketActive": True}
    assert common.oddspapi_selection_is_valid(market_entry, sel_entry) is False


def test_oddspapi_selection_todo_true_es_valida():
    market_entry = {"bk": "Pinnacle", "bookmakerIsActive": True}
    sel_entry = {"p": 1.90, "t": "T", "active": True, "marketActive": True}
    assert common.oddspapi_selection_is_valid(market_entry, sel_entry) is True


def test_oddspapi_selection_campos_ausentes_nunca_se_tratan_como_false():
    # Compatibilidad con oddspapi_lean.json capturado antes de esta auditoria
    # (sin active/marketActive/bookmakerIsActive) -- debe seguir funcionando
    # exactamente como antes, nunca invalidarse por un campo que no existe.
    market_entry = {"bk": "Pinnacle"}
    sel_entry = {"p": 1.90, "t": "T"}
    assert common.oddspapi_selection_is_valid(market_entry, sel_entry) is True


# ---------------------------------------------------------------------
# rankings.py -- candidatos y Poisson de Corners
# ---------------------------------------------------------------------

def _kickoff(days_from_today):
    d = rankings.chile_today() + datetime.timedelta(days=days_from_today)
    return d.strftime("%Y-%m-%dT18:00:00Z")


def test_build_candidates_excluye_partido_sin_probabilidad_valida():
    match_list = [{"id": "a-b-1", "home": "A", "away": "B", "league": "L", "kickoffUTC": _kickoff(0)}]
    pocket = {"a-b-1": {"resolved": True, "markets": {"OU25_GOALS_FT": {"error": "motor no disponible"}}}}
    hist = {"a-b-1": {}}
    out = rankings.build_candidates(pocket, hist, match_list, {})
    assert out["OVER25"] == []
    assert out["UNDER25"] == []
    assert out["BTTS"] == []
    assert out["CORNERS_OVER105"] == []


def test_build_candidates_goles_btts_corners_reales():
    match_list = [{"id": "a-b-1", "home": "A", "away": "B", "league": "L", "kickoffUTC": _kickoff(0)}]
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "OU25_GOALS_FT": {"probability": {"over": 0.62, "under": 0.38}, "engine_id": "poisson_goals", "governance_status": "BASELINE"},
    }}}
    hist = {"a-b-1": {
        "btts_general_pct": 58.0,
        "home_home_lambda": {"cornerKicks": 5.2},
        "away_away_lambda": {"cornerKicks": 4.1},
    }}
    out = rankings.build_candidates(pocket, hist, match_list, {})
    assert out["OVER25"][0]["probability"] == 0.62
    assert out["OVER25"][0]["governance_status"] == "BASELINE"
    assert out["UNDER25"][0]["probability"] == 0.38
    assert out["BTTS"][0]["probability"] == pytest.approx(0.58)
    assert out["BTTS"][0]["governance_status"] is None
    # Poisson(9.3, 10.5) calculado a mano (misma formula que index.html)
    expected = rankings._poisson_over_prob(9.3, 10.5)
    assert out["CORNERS_OVER105"][0]["probability"] == pytest.approx(expected)


def test_corners_sin_lambda_no_genera_candidato():
    match_list = [{"id": "a-b-1", "home": "A", "away": "B", "league": "L", "kickoffUTC": _kickoff(0)}]
    pocket = {"a-b-1": {"resolved": True, "markets": {}}}
    hist = {"a-b-1": {"home_home_lambda": {}, "away_away_lambda": {"cornerKicks": 4.1}}}  # falta el lado home
    out = rankings.build_candidates(pocket, hist, match_list, {})
    assert out["CORNERS_OVER105"] == []


def test_oddspapi_price_solo_para_mercados_cubiertos():
    lean = {"a-b-1": {"OU25_GOALS_FT": {"bk": "Pinnacle", "sel": {"over": {"p": 1.85, "t": "T"}}}}}
    price, bk = rankings._oddspapi_price(lean, "a-b-1", "OVER25")
    assert price == 1.85 and bk == "Pinnacle"
    price, bk = rankings._oddspapi_price(lean, "a-b-1", "CORNERS_OVER105")
    assert price is None and bk is None  # OddsPapi FREE nunca cubre Corners -- no se inventa


def test_ranking_no_usa_cuota_inactiva():
    # auditoria EV extremo 2026-08-16: active=False -> mismo camino que sin cuota
    lean = {"a-b-1": {"OU25_GOALS_FT": {"bk": "Pinnacle", "bookmakerIsActive": True,
                                         "sel": {"over": {"p": 28.56, "t": "T", "active": False, "marketActive": True}}}}}
    price, bk = rankings._oddspapi_price(lean, "a-b-1", "OVER25")
    assert price is None and bk is None


def test_ranking_no_usa_cuota_con_market_inactivo():
    lean = {"a-b-1": {"OU25_GOALS_FT": {"bk": "Pinnacle", "bookmakerIsActive": True,
                                         "sel": {"over": {"p": 1.85, "t": "T", "active": True, "marketActive": False}}}}}
    price, bk = rankings._oddspapi_price(lean, "a-b-1", "OVER25")
    assert price is None and bk is None


def test_ranking_usa_cuota_activa_sin_cambios():
    lean = {"a-b-1": {"OU25_GOALS_FT": {"bk": "Pinnacle", "bookmakerIsActive": True,
                                         "sel": {"over": {"p": 1.85, "t": "T", "active": True, "marketActive": True}}}}}
    price, bk = rankings._oddspapi_price(lean, "a-b-1", "OVER25")
    assert price == 1.85 and bk == "Pinnacle"


# ---------------------------------------------------------------------
# rankings.py -- TOP 10 sin relleno artificial
# ---------------------------------------------------------------------

def test_top10_nunca_rellena():
    candidates = [{"probability": 0.5 + i * 0.01} for i in range(4)]
    ranked = rankings._top10(candidates)
    assert len(ranked) == 4  # solo hay 4, nunca se completa a 10
    probs = [c["probability"] for c in ranked]
    assert probs == sorted(probs, reverse=True)


def test_top10_corta_en_10_si_hay_mas():
    candidates = [{"probability": i / 100.0} for i in range(25)]
    ranked = rankings._top10(candidates)
    assert len(ranked) == 10
    assert ranked[0]["probability"] == max(c["probability"] for c in candidates)


# ---------------------------------------------------------------------
# rankings.py -- run() end-to-end con paths/DB inyectados (tmp_path)
# ---------------------------------------------------------------------

@pytest.fixture
def _rankings_env(tmp_path, monkeypatch):
    work = tmp_path / "_work"
    work.mkdir()
    monkeypatch.setattr(rankings, "WORK", str(work))
    monkeypatch.setattr(rankings, "TOMORROW_STATE_PATH", str(tmp_path / "tomorrow.json"))
    monkeypatch.setattr(rankings, "DAILY_STATE_PATH", str(tmp_path / "daily.json"))
    monkeypatch.setattr(rankings, "WEEKLY_STATE_PATH", str(tmp_path / "weekly.json"))
    monkeypatch.setattr(rankings, "HISTORY_PATH", str(tmp_path / "history.jsonl"))
    return work


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def test_run_genera_diario_y_semanal_primera_vez(_rankings_env):
    work = _rankings_env
    match_list = [{"id": "a-b-1", "home": "A", "away": "B", "league": "L", "kickoffUTC": _kickoff(0)}]
    pocket = {"a-b-1": {"resolved": True, "markets": {"OU25_GOALS_FT": {"probability": {"over": 0.6, "under": 0.4}, "engine_id": "e", "governance_status": "BASELINE"}}}}
    hist = {"a-b-1": {"btts_general_pct": 55.0}}
    _write_json(work / "match_list.json", match_list)
    _write_json(work / "pocket_engine_results.json", pocket)
    _write_json(work / "historical_stats_results.json", hist)
    _write_json(work / "match_event_ids.json", {"a-b-1": {"event_id": 999}})
    _write_json(work / "oddspapi_lean.json", {})

    resumen = rankings.run(finished_event_ids_fn=lambda ids: set())
    assert resumen["weekly_regenerated"] is True
    assert resumen["daily_new_entries"] >= 1

    daily = json.load(open(rankings.DAILY_STATE_PATH, encoding="utf-8"))
    assert len(daily["rankings"]["OVER25"]) == 1
    weekly = json.load(open(rankings.WEEKLY_STATE_PATH, encoding="utf-8"))
    assert len(weekly["rankings"]["OVER25"]) == 1


def test_run_no_regenera_semanal_si_quedan_partidos_pendientes(_rankings_env):
    work = _rankings_env
    match_list = [{"id": "a-b-1", "home": "A", "away": "B", "league": "L", "kickoffUTC": _kickoff(0)}]
    pocket = {"a-b-1": {"resolved": True, "markets": {"OU25_GOALS_FT": {"probability": {"over": 0.6, "under": 0.4}, "engine_id": "e", "governance_status": "BASELINE"}}}}
    hist = {"a-b-1": {"btts_general_pct": 55.0}}
    _write_json(work / "match_list.json", match_list)
    _write_json(work / "pocket_engine_results.json", pocket)
    _write_json(work / "historical_stats_results.json", hist)
    _write_json(work / "match_event_ids.json", {"a-b-1": {"event_id": 999}})
    _write_json(work / "oddspapi_lean.json", {})

    rankings.run(finished_event_ids_fn=lambda ids: set())
    weekly_after_first = json.load(open(rankings.WEEKLY_STATE_PATH, encoding="utf-8"))

    # Segunda corrida el mismo dia -- partido 999 sigue sin terminar
    resumen2 = rankings.run(finished_event_ids_fn=lambda ids: set())
    assert resumen2["weekly_regenerated"] is False
    weekly_after_second = json.load(open(rankings.WEEKLY_STATE_PATH, encoding="utf-8"))
    assert weekly_after_second == weekly_after_first  # congelado, byte-identico

    # Tercera corrida -- ahora SI termino -> se regenera
    resumen3 = rankings.run(finished_event_ids_fn=lambda ids: set(ids))
    assert resumen3["weekly_regenerated"] is True


def test_run_no_duplica_history_en_corridas_repetidas(_rankings_env):
    work = _rankings_env
    match_list = [{"id": "a-b-1", "home": "A", "away": "B", "league": "L", "kickoffUTC": _kickoff(0)}]
    pocket = {"a-b-1": {"resolved": True, "markets": {"OU25_GOALS_FT": {"probability": {"over": 0.6, "under": 0.4}, "engine_id": "e", "governance_status": "BASELINE"}}}}
    hist = {"a-b-1": {"btts_general_pct": 55.0}}
    _write_json(work / "match_list.json", match_list)
    _write_json(work / "pocket_engine_results.json", pocket)
    _write_json(work / "historical_stats_results.json", hist)
    _write_json(work / "match_event_ids.json", {"a-b-1": {"event_id": 999}})
    _write_json(work / "oddspapi_lean.json", {})

    rankings.run(finished_event_ids_fn=lambda ids: set())
    rankings.run(finished_event_ids_fn=lambda ids: set())
    lines = open(rankings.HISTORY_PATH, encoding="utf-8").read().strip().split("\n")
    over25_lines = [l for l in lines if json.loads(l)["market"] == "OU25_GOALS_FT" and json.loads(l)["selection"] == "over"]
    assert len(over25_lines) == 2  # 1 daily + 1 weekly, nunca duplicado por la segunda corrida


def test_history_probabilidad_y_cuota_no_cambian_retroactivamente(_rankings_env):
    work = _rankings_env
    match_list = [{"id": "a-b-1", "home": "A", "away": "B", "league": "L", "kickoffUTC": _kickoff(0)}]
    pocket = {"a-b-1": {"resolved": True, "markets": {"OU25_GOALS_FT": {"probability": {"over": 0.60, "under": 0.40}, "engine_id": "e", "governance_status": "BASELINE"}}}}
    hist = {"a-b-1": {"btts_general_pct": 55.0}}
    _write_json(work / "match_list.json", match_list)
    _write_json(work / "pocket_engine_results.json", pocket)
    _write_json(work / "historical_stats_results.json", hist)
    _write_json(work / "match_event_ids.json", {"a-b-1": {"event_id": 999}})
    _write_json(work / "oddspapi_lean.json", {"a-b-1": {"OU25_GOALS_FT": {"bk": "Pinnacle", "sel": {"over": {"p": 1.80, "t": "T"}}}}})
    rankings.run(finished_event_ids_fn=lambda ids: set())

    first = json.load(open(rankings.WEEKLY_STATE_PATH, encoding="utf-8"))
    first_prob = first["rankings"]["OVER25"][0]["probabilidad_atlas"]
    first_cuota = first["rankings"]["OVER25"][0]["cuota"]
    assert first_prob == 0.6 and first_cuota == 1.80

    # ATLAS "recalcula" el partido con numeros distintos -- el snapshot de
    # historia YA escrito no debe cambiar (aunque el weekly congelado
    # tampoco se toque porque el partido sigue pendiente).
    pocket["a-b-1"]["markets"]["OU25_GOALS_FT"]["probability"] = {"over": 0.90, "under": 0.10}
    _write_json(work / "pocket_engine_results.json", pocket)
    rankings.run(finished_event_ids_fn=lambda ids: set())

    lines = [json.loads(l) for l in open(rankings.HISTORY_PATH, encoding="utf-8").read().strip().split("\n")]
    over25_weekly = [l for l in lines if l["market"] == "OU25_GOALS_FT" and l["selection"] == "over" and l["ranking_type"] == "weekly"]
    assert len(over25_weekly) == 1
    assert over25_weekly[0]["probabilidad_atlas"] == 0.6  # nunca 0.9 -- inmutable


# ---------------------------------------------------------------------
# rankings.py -- ventana "Mañana" (2026-08-22, mandato del Director):
# misma formula/mercados/orden que Diario, solo cambia la ventana temporal.
# ---------------------------------------------------------------------

def test_run_genera_manana_junto_con_diario_y_semanal(_rankings_env):
    work = _rankings_env
    match_list = [{"id": "a-b-1", "home": "A", "away": "B", "league": "L", "kickoffUTC": _kickoff(1)}]
    pocket = {"a-b-1": {"resolved": True, "markets": {"OU25_GOALS_FT": {"probability": {"over": 0.6, "under": 0.4}, "engine_id": "e", "governance_status": "BASELINE"}}}}
    hist = {"a-b-1": {"btts_general_pct": 55.0}}
    _write_json(work / "match_list.json", match_list)
    _write_json(work / "pocket_engine_results.json", pocket)
    _write_json(work / "historical_stats_results.json", hist)
    _write_json(work / "match_event_ids.json", {"a-b-1": {"event_id": 999}})
    _write_json(work / "oddspapi_lean.json", {})

    resumen = rankings.run(finished_event_ids_fn=lambda ids: set())
    assert resumen["tomorrow_new_entries"] >= 1

    tomorrow = json.load(open(rankings.TOMORROW_STATE_PATH, encoding="utf-8"))
    assert len(tomorrow["rankings"]["OVER25"]) == 1
    assert tomorrow["rankings"]["OVER25"][0]["probabilidad_atlas"] == 0.6

    # Un partido de mañana NUNCA debe aparecer en el ranking Diario (misma
    # separacion de ventanas que ya existe entre Diario y Semanal).
    daily = json.load(open(rankings.DAILY_STATE_PATH, encoding="utf-8"))
    assert daily["rankings"]["OVER25"] == []


def test_manana_no_incluye_partido_de_hoy(_rankings_env):
    work = _rankings_env
    match_list = [{"id": "a-b-1", "home": "A", "away": "B", "league": "L", "kickoffUTC": _kickoff(0)}]
    pocket = {"a-b-1": {"resolved": True, "markets": {"OU25_GOALS_FT": {"probability": {"over": 0.6, "under": 0.4}, "engine_id": "e", "governance_status": "BASELINE"}}}}
    hist = {"a-b-1": {"btts_general_pct": 55.0}}
    _write_json(work / "match_list.json", match_list)
    _write_json(work / "pocket_engine_results.json", pocket)
    _write_json(work / "historical_stats_results.json", hist)
    _write_json(work / "match_event_ids.json", {"a-b-1": {"event_id": 999}})
    _write_json(work / "oddspapi_lean.json", {})

    resumen = rankings.run(finished_event_ids_fn=lambda ids: set())
    assert resumen["tomorrow_new_entries"] == 0
    tomorrow = json.load(open(rankings.TOMORROW_STATE_PATH, encoding="utf-8"))
    assert tomorrow["rankings"]["OVER25"] == []  # un partido de HOY no es "Mañana"


def test_history_diferencia_ranking_type_manana_de_diario_y_semanal(_rankings_env):
    work = _rankings_env
    match_list = [{"id": "a-b-1", "home": "A", "away": "B", "league": "L", "kickoffUTC": _kickoff(1)}]
    pocket = {"a-b-1": {"resolved": True, "markets": {"OU25_GOALS_FT": {"probability": {"over": 0.6, "under": 0.4}, "engine_id": "e", "governance_status": "BASELINE"}}}}
    hist = {"a-b-1": {"btts_general_pct": 55.0}}
    _write_json(work / "match_list.json", match_list)
    _write_json(work / "pocket_engine_results.json", pocket)
    _write_json(work / "historical_stats_results.json", hist)
    _write_json(work / "match_event_ids.json", {"a-b-1": {"event_id": 999}})
    _write_json(work / "oddspapi_lean.json", {})

    rankings.run(finished_event_ids_fn=lambda ids: set())
    rankings.run(finished_event_ids_fn=lambda ids: set())  # segunda corrida el mismo dia

    lines = [json.loads(l) for l in open(rankings.HISTORY_PATH, encoding="utf-8").read().strip().split("\n")]
    over25_lines = [l for l in lines if l["market"] == "OU25_GOALS_FT" and l["selection"] == "over"]
    by_type = {l["ranking_type"] for l in over25_lines}
    assert by_type == {"tomorrow", "weekly"}  # cae en la ventana de mañana Y en la semanal, nunca en "daily"
    assert len(over25_lines) == 2  # 1 tomorrow + 1 weekly, nunca duplicado por la segunda corrida


# ---------------------------------------------------------------------
# settlement.py -- resolutores propios (BTTS / Corners 10.5), sin DB real
# ---------------------------------------------------------------------

class _FakeResult:
    def __init__(self, score_home, score_away, corner_total=None):
        self.score_home = score_home
        self.score_away = score_away
        self.corner_total = corner_total


def test_resolve_btts_si_y_no():
    acierto, actual = settlement._resolve_btts("yes", _FakeResult(1, 1))
    assert (acierto, actual) == ("acierto", "yes")
    acierto, actual = settlement._resolve_btts("yes", _FakeResult(2, 0))
    assert (acierto, actual) == ("fallo", "no")


def test_resolve_corners_over105_umbral_11():
    acierto, actual = settlement._resolve_corners_over105("over", _FakeResult(1, 0, corner_total=11))
    assert (acierto, actual) == ("acierto", "over")
    acierto, actual = settlement._resolve_corners_over105("over", _FakeResult(1, 0, corner_total=10))
    assert (acierto, actual) == ("fallo", "under")  # 10 corners = Over 9.5 SI, Over 10.5 NO


def test_resolve_corners_over105_sin_dato_queda_pendiente():
    acierto, actual = settlement._resolve_corners_over105("over", _FakeResult(1, 0, corner_total=None))
    assert (acierto, actual) == (None, None)


def test_settle_jsonl_solo_completa_pendientes_sin_tocar_lo_demas(tmp_path):
    path = tmp_path / "history.jsonl"
    records = [
        {"market": "BTTS", "selection": "yes", "event_id": 111, "estado": "PENDIENTE", "resultado_real": None, "acierto": None, "probabilidad_atlas": 0.55, "cuota": 1.8},
        {"market": "OU10.5_CORNERS_FT", "selection": "over", "event_id": 222, "estado": "FINALIZADO", "resultado_real": "over", "acierto": "acierto", "probabilidad_atlas": 0.4, "cuota": None},
    ]
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    class _Res:
        score_home, score_away, corner_total = 2, 1, None

    import atlas_lab_mockup.tipster.settlement as settlement_mod
    monkey_results = {111: _Res()}
    orig = settlement_mod._load_finished_match_results
    settlement_mod._load_finished_match_results = lambda ids: {k: v for k, v in monkey_results.items() if k in ids}
    try:
        resumen = settlement_mod._settle_jsonl(str(path), settlement_mod._ESTADO_RANKINGS)
    finally:
        settlement_mod._load_finished_match_results = orig

    assert resumen["settled"] == 1
    out = [json.loads(l) for l in open(path, encoding="utf-8").read().strip().split("\n")]
    btts = next(r for r in out if r["market"] == "BTTS")
    assert btts["estado"] == "FINALIZADO"
    assert btts["resultado_real"] == "yes"
    assert btts["acierto"] == "acierto"
    assert btts["probabilidad_atlas"] == 0.55 and btts["cuota"] == 1.8  # sin cambios
    # la fila ya finalizada no se toca
    corners = next(r for r in out if r["market"] == "OU10.5_CORNERS_FT")
    assert corners["acierto"] == "acierto" and corners["resultado_real"] == "over"


# ---------------------------------------------------------------------
# settlement.py -- prune_settled_picks_from_estado (ciclo intraday 2026-08-16)
# ---------------------------------------------------------------------

def _write_estado(path, picks_list):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"generated_at_utc": "T", "candidatos_evaluados": 10, "value_detectado": 5,
                    "picks_activos": len(picks_list), "picks": picks_list}, f)


def _write_history(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_prune_quita_solo_los_pick_id_ya_liquidados(tmp_path):
    estado_path = tmp_path / "picks_estado.json"
    history_path = tmp_path / "picks_history.jsonl"
    _write_estado(estado_path, [
        {"pick_id": "1:1X2_FT:home", "ev_pct": 10.0},
        {"pick_id": "2:BTTS:yes", "ev_pct": 5.0},
        {"pick_id": "3:OU25_GOALS_FT:over", "ev_pct": 8.0},
    ])
    _write_history(history_path, [
        {"pick_id": "1:1X2_FT:home", "estado": "GANADO", "probabilidad_atlas": 0.5, "cuota": 2.0},
        {"pick_id": "2:BTTS:yes", "estado": "PENDIENTE", "probabilidad_atlas": 0.6, "cuota": 1.8},
        {"pick_id": "3:OU25_GOALS_FT:over", "estado": "PERDIDO", "probabilidad_atlas": 0.55, "cuota": 1.9},
    ])
    removed = settlement.prune_settled_picks_from_estado(str(estado_path), str(history_path))
    assert removed == 2
    estado = json.load(open(estado_path, encoding="utf-8"))
    assert [p["pick_id"] for p in estado["picks"]] == ["2:BTTS:yes"]
    assert estado["picks_activos"] == 1


def test_prune_no_reescribe_el_archivo_si_no_hay_nada_que_quitar(tmp_path):
    estado_path = tmp_path / "picks_estado.json"
    history_path = tmp_path / "picks_history.jsonl"
    _write_estado(estado_path, [{"pick_id": "1:1X2_FT:home", "ev_pct": 10.0}])
    _write_history(history_path, [{"pick_id": "1:1X2_FT:home", "estado": "PENDIENTE", "probabilidad_atlas": 0.5, "cuota": 2.0}])
    before = estado_path.read_text(encoding="utf-8")
    removed = settlement.prune_settled_picks_from_estado(str(estado_path), str(history_path))
    assert removed == 0
    assert estado_path.read_text(encoding="utf-8") == before  # byte-identico, ni se toco


def test_prune_nunca_liquida_ni_toca_el_history_jsonl(tmp_path):
    estado_path = tmp_path / "picks_estado.json"
    history_path = tmp_path / "picks_history.jsonl"
    _write_estado(estado_path, [{"pick_id": "1:1X2_FT:home", "ev_pct": 10.0}])
    record = {"pick_id": "1:1X2_FT:home", "estado": "GANADO", "probabilidad_atlas": 0.5, "cuota": 2.0, "roi_pct": 100.0}
    _write_history(history_path, [record])
    before = history_path.read_text(encoding="utf-8")
    settlement.prune_settled_picks_from_estado(str(estado_path), str(history_path))
    assert history_path.read_text(encoding="utf-8") == before  # nunca se reescribe el jsonl aqui


def test_prune_archivos_ausentes_no_rompe(tmp_path):
    removed = settlement.prune_settled_picks_from_estado(str(tmp_path / "no_existe.json"), str(tmp_path / "no_existe.jsonl"))
    assert removed == 0


# ---------------------------------------------------------------------
# picks.py -- candidato / value / pick, mercados automatizados, cuota real
# ---------------------------------------------------------------------

def _picks_kickoff(days_from_today=0):
    d = rankings.chile_today() + datetime.timedelta(days=days_from_today)
    return d.strftime("%Y-%m-%dT18:00:00Z")


def _base_match_list(mid="a-b-1", days=0):
    return [{"id": mid, "home": "A", "away": "B", "league": "L", "kickoffUTC": _picks_kickoff(days)}]


def test_sin_cuota_no_es_candidato():
    match_list = _base_match_list()
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "OU25_GOALS_FT": {"probability": {"over": 0.6, "under": 0.4}, "governance_status": "BASELINE", "engine_id": "e"},
    }}}
    out = picks.build_candidates(pocket, {}, match_list, {"a-b-1": {"event_id": 1}}, {})  # oddspapi_lean vacio
    assert out == []  # sin cuota real -> nunca se inventa, no hay candidato


def test_candidato_con_cuota_calcula_implicita_y_ev_correctos():
    match_list = _base_match_list()
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "OU25_GOALS_FT": {"probability": {"over": 0.60, "under": 0.40}, "governance_status": "BASELINE", "engine_id": "goals_predictor"},
    }}}
    lean = {"a-b-1": {"OU25_GOALS_FT": {"bk": "Pinnacle", "sel": {"over": {"p": 2.00, "t": "T"}}}}}
    out = picks.build_candidates(pocket, {}, match_list, {"a-b-1": {"event_id": 1}}, lean)
    assert len(out) == 1
    c = out[0]
    assert c["implied_probability"] == 0.5  # 1/2.00
    assert c["ev_pct"] == pytest.approx((0.60 * 2.00 - 1) * 100)  # +20.0
    assert c["line"] == 2.5


def test_candidato_con_active_false_no_se_construye():
    # auditoria EV extremo 2026-08-16: el caso real que origino la
    # auditoria (Excelsior vs Sparta Rotterdam, active=False en 1X2).
    match_list = _base_match_list()
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "1X2_FT": {"probability": {"home": 0.65, "draw": 0.20, "away": 0.15}, "governance_status": "BASELINE", "engine_id": "form_calculator"},
    }}}
    lean = {"a-b-1": {"1X2_FT": {"bk": "Pinnacle", "bookmakerIsActive": True, "sel": {
        "home": {"p": 1.10, "t": "T", "active": False, "marketActive": False},
        "draw": {"p": 6.12, "t": "T", "active": False, "marketActive": False},
        "away": {"p": 28.56, "t": "T", "active": False, "marketActive": False},
    }}}}
    out = picks.build_candidates(pocket, {}, match_list, {"a-b-1": {"event_id": 1}}, lean)
    assert out == []  # active=False -> mismo camino que sin cuota, nunca candidato/value/pick


def test_candidato_con_market_active_false_no_se_construye():
    match_list = _base_match_list()
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "OU25_GOALS_FT": {"probability": {"over": 0.60, "under": 0.40}, "governance_status": "BASELINE", "engine_id": "e"},
    }}}
    lean = {"a-b-1": {"OU25_GOALS_FT": {"bk": "Pinnacle", "bookmakerIsActive": True,
                                         "sel": {"over": {"p": 2.00, "t": "T", "active": True, "marketActive": False}}}}}
    out = picks.build_candidates(pocket, {}, match_list, {"a-b-1": {"event_id": 1}}, lean)
    assert out == []


def test_candidato_con_bookmaker_is_active_false_no_se_construye():
    match_list = _base_match_list()
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "OU25_GOALS_FT": {"probability": {"over": 0.60, "under": 0.40}, "governance_status": "BASELINE", "engine_id": "e"},
    }}}
    lean = {"a-b-1": {"OU25_GOALS_FT": {"bk": "Pinnacle", "bookmakerIsActive": False,
                                         "sel": {"over": {"p": 2.00, "t": "T", "active": True, "marketActive": True}}}}}
    out = picks.build_candidates(pocket, {}, match_list, {"a-b-1": {"event_id": 1}}, lean)
    assert out == []


def test_candidato_con_active_true_sin_cambios():
    # Regresion: active=True explicito no debe alterar el comportamiento ya
    # validado (mismo caso que test_candidato_con_cuota_calcula_implicita_y_ev_correctos).
    match_list = _base_match_list()
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "OU25_GOALS_FT": {"probability": {"over": 0.60, "under": 0.40}, "governance_status": "BASELINE", "engine_id": "goals_predictor"},
    }}}
    lean = {"a-b-1": {"OU25_GOALS_FT": {"bk": "Pinnacle", "bookmakerIsActive": True,
                                         "sel": {"over": {"p": 2.00, "t": "T", "active": True, "marketActive": True}}}}}
    out = picks.build_candidates(pocket, {}, match_list, {"a-b-1": {"event_id": 1}}, lean)
    assert len(out) == 1
    assert out[0]["ev_pct"] == pytest.approx((0.60 * 2.00 - 1) * 100)


def test_candidato_campos_ausentes_compatibilidad_datos_antiguos():
    # Regresion: oddspapi_lean.json capturado ANTES de esta auditoria (sin
    # active/marketActive/bookmakerIsActive) debe seguir generando
    # candidatos exactamente igual que antes.
    match_list = _base_match_list()
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "OU25_GOALS_FT": {"probability": {"over": 0.60, "under": 0.40}, "governance_status": "BASELINE", "engine_id": "e"},
    }}}
    lean = {"a-b-1": {"OU25_GOALS_FT": {"bk": "Pinnacle", "sel": {"over": {"p": 2.00, "t": "T"}}}}}
    out = picks.build_candidates(pocket, {}, match_list, {"a-b-1": {"event_id": 1}}, lean)
    assert len(out) == 1


def test_regresion_1x2_activo_genera_candidato():
    match_list = _base_match_list()
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "1X2_FT": {"probability": {"home": 0.55, "draw": 0.25, "away": 0.20}, "governance_status": "BASELINE", "engine_id": "form_calculator"},
    }}}
    lean = {"a-b-1": {"1X2_FT": {"bk": "Pinnacle", "bookmakerIsActive": True, "sel": {
        "home": {"p": 2.00, "t": "T", "active": True, "marketActive": True},
    }}}}
    out = picks.build_candidates(pocket, {}, match_list, {"a-b-1": {"event_id": 1}}, lean)
    assert len(out) == 1 and out[0]["selection"] == "home"


def test_regresion_handicap_activo_genera_candidato():
    match_list = _base_match_list()
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "HANDICAP_FT": {"probability": {"home_covers": 0.55, "away_covers": 0.45}, "governance_status": "BASELINE",
                         "engine_id": "handicap_predictor", "market_context": {"home_line": -0.5, "away_line": 0.5}},
    }}}
    lean = {"a-b-1": {"HANDICAP_FT": {"bk": "Pinnacle", "bookmakerIsActive": True, "sel": {
        "home": {"p": 1.90, "t": "T", "active": True, "marketActive": True},
    }}}}
    out = picks.build_candidates(pocket, {}, match_list, {"a-b-1": {"event_id": 1}}, lean)
    assert len(out) == 1 and out[0]["selection"] == "home_covers" and out[0]["line"] == -0.5


def test_regresion_btts_activo_genera_candidato():
    match_list = _base_match_list()
    lean = {"a-b-1": {"BTTS": {"bk": "Pinnacle", "bookmakerIsActive": True, "sel": {
        "yes": {"p": 1.80, "t": "T", "active": True, "marketActive": True},
    }}}}
    out = picks.build_candidates({"a-b-1": {"resolved": True, "markets": {}}}, {"a-b-1": {"btts_general_pct": 55.0}}, match_list, {"a-b-1": {"event_id": 1}}, lean)
    assert len(out) == 1 and out[0]["market"] == "BTTS"


def test_solo_evalua_mercados_automatizados_corners_nunca_aparece():
    match_list = _base_match_list()
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "OU9.5_CORNERS_FT": {"probability": {"over": 0.9}, "governance_status": "BASELINE", "engine_id": "e"},
    }}}
    lean = {"a-b-1": {"OU9.5_CORNERS_FT": {"bk": "Pinnacle", "sel": {"over": {"p": 3.0, "t": "T"}}}}}
    out = picks.build_candidates(pocket, {}, match_list, {"a-b-1": {"event_id": 1}}, lean)
    assert out == []  # Corners nunca tiene cuota OddsPapi Y ademas no esta en AUTOMATED_MARKETS


def test_handicap_mapea_seleccion_y_linea_correctas():
    match_list = _base_match_list()
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "HANDICAP_FT": {"probability": {"home_covers": 0.55, "away_covers": 0.45},
                         "governance_status": "BASELINE", "engine_id": "handicap_predictor",
                         "market_context": {"home_line": -0.5, "away_line": 0.5}},
    }}}
    lean = {"a-b-1": {"HANDICAP_FT": {"bk": "Pinnacle", "sel": {"home": {"p": 1.90, "t": "T"}, "away": {"p": 1.95, "t": "T"}}}}}
    out = picks.build_candidates(pocket, {}, match_list, {"a-b-1": {"event_id": 1}}, lean)
    home = next(c for c in out if c["selection"] == "home_covers")
    away = next(c for c in out if c["selection"] == "away_covers")
    assert home["price"] == 1.90 and home["line"] == -0.5
    assert away["price"] == 1.95 and away["line"] == 0.5
    assert home["market_context"] == {"home_line": -0.5, "away_line": 0.5}


def _cand(market="1X2_FT", selection="away", prob=0.55, ev=8.0, engine_id="form_calculator"):
    return {"market": market, "selection": selection, "probability": prob, "ev_pct": ev, "engine_id": engine_id}


def test_btts_sin_hipotesis_certificada_nunca_es_pick(monkeypatch):
    # REVERSION de la decision de 2026-08-16 -- ver test_gate_btts_* arriba.
    monkeypatch.setattr(pick_governance, "load_hypotheses", lambda path=None: [])
    c = _cand(market="BTTS", selection="yes", prob=0.65, ev=12.0, engine_id="btts_historico")
    es_value, es_pick = picks.classify(c)
    assert es_value is True and es_pick is False


def test_ev_negativo_no_es_value_ni_pick():
    c = _cand(ev=-5.0)
    es_value, es_pick = picks.classify(c)
    assert es_value is False and es_pick is False


def test_ev_positivo_sin_hipotesis_congelada_es_value_no_pick(monkeypatch):
    # PICK GOVERNANCE (2026-08-22): sin una hipotesis congelada que cubra
    # exactamente este mercado/seleccion/motor, ningun EV% autopromueve.
    monkeypatch.setattr(pick_governance, "load_hypotheses", lambda path=None: [])
    c = _cand(market="OU25_GOALS_FT", selection="over", prob=0.60, ev=8.0, engine_id="goals_predictor")
    es_value, es_pick = picks.classify(c)
    assert es_value is True and es_pick is False


def test_ev_positivo_hipotesis_en_observacion_es_value_no_pick(monkeypatch):
    monkeypatch.setattr(pick_governance, "load_hypotheses", lambda path=None: [_hyp(estado=pick_governance.HypothesisStatus.EN_OBSERVACION)])
    c = _cand(prob=0.55, ev=8.0)
    es_value, es_pick = picks.classify(c)
    assert es_value is True and es_pick is False


def test_ev_positivo_hipotesis_certificada_es_pick(monkeypatch):
    monkeypatch.setattr(pick_governance, "load_hypotheses", lambda path=None: [_hyp(estado=pick_governance.HypothesisStatus.CERTIFICADO)])
    c = _cand(prob=0.55, ev=8.0)
    es_value, es_pick = picks.classify(c)
    assert es_value is True and es_pick is True


def test_prob_bajo_umbral_de_hipotesis_certificada_no_es_pick(monkeypatch):
    monkeypatch.setattr(pick_governance, "load_hypotheses", lambda path=None: [_hyp(estado=pick_governance.HypothesisStatus.CERTIFICADO, umbral_prob=0.50)])
    c = _cand(prob=0.45, ev=8.0)  # bajo el umbral de la hipotesis
    es_value, es_pick = picks.classify(c)
    assert es_value is True and es_pick is False


# ---------------------------------------------------------------------
# picks.py -- exclusion mutua 1X2 (Condicion 5 del mandato, 2026-08-22):
# conservar TODAS las evaluaciones, elegir solo una para la ruta de senal,
# conservar la razon de exclusion, nunca mas de una seleccion 1X2 accionable
# para el mismo partido. Determinista (mayor EV%, desempate alfabetico).
# ---------------------------------------------------------------------

def test_exclusion_mutua_1x2_conserva_solo_la_de_mayor_ev():
    home = {**_cand(selection="home", prob=0.55, ev=5.0), "event_id": 1}
    away = {**_cand(selection="away", prob=0.52, ev=9.0), "event_id": 1}
    dominant, excluded = picks._apply_1x2_mutual_exclusion([home, away])
    assert len(dominant) == 1 and dominant[0]["selection"] == "away"
    assert len(excluded) == 1 and excluded[0][0]["selection"] == "home" and excluded[0][1] == "away"


def test_exclusion_mutua_1x2_desempate_alfabetico_deterministico():
    # EV% exactamente empatado -- debe ser 100% reproducible, nunca aleatorio.
    a = {**_cand(selection="home", prob=0.55, ev=7.0), "event_id": 1}
    b = {**_cand(selection="away", prob=0.55, ev=7.0), "event_id": 1}
    dominant, excluded = picks._apply_1x2_mutual_exclusion([a, b])
    assert dominant[0]["selection"] == "away"  # "away" < "home" alfabeticamente
    assert excluded[0][0]["selection"] == "home"


def test_exclusion_mutua_no_afecta_mercados_distintos_del_mismo_partido():
    home_1x2 = {**_cand(market="1X2_FT", selection="home", prob=0.55, ev=5.0), "event_id": 1}
    over_ou25 = {**_cand(market="OU25_GOALS_FT", selection="over", prob=0.60, ev=6.0), "event_id": 1}
    dominant, excluded = picks._apply_1x2_mutual_exclusion([home_1x2, over_ou25])
    assert len(dominant) == 2 and len(excluded) == 0  # mercados distintos -- ambos sobreviven, sin exclusion cruzada


def test_exclusion_mutua_no_afecta_1x2_de_partidos_distintos():
    home_p1 = {**_cand(selection="home", prob=0.55, ev=5.0), "event_id": 1}
    away_p2 = {**_cand(selection="away", prob=0.55, ev=5.0), "event_id": 2}
    dominant, excluded = picks._apply_1x2_mutual_exclusion([home_p1, away_p2])
    assert len(dominant) == 2 and len(excluded) == 0


def test_exclusion_mutua_una_sola_seleccion_elegible_no_se_excluye():
    home = {**_cand(selection="home", prob=0.55, ev=5.0), "event_id": 1}
    dominant, excluded = picks._apply_1x2_mutual_exclusion([home])
    assert dominant == [home] and excluded == []


@pytest.fixture
def _picks_env(tmp_path, monkeypatch):
    work = tmp_path / "_work"
    work.mkdir()
    monkeypatch.setattr(picks, "WORK", str(work))
    monkeypatch.setattr(picks, "PICKS_STATE_PATH", str(tmp_path / "picks.json"))
    monkeypatch.setattr(picks, "PICKS_HISTORY_PATH", str(tmp_path / "picks_history.jsonl"))
    return work


def _wj(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def test_run_sin_hipotesis_certificada_nunca_genera_pick(_picks_env, monkeypatch):
    # PICK GOVERNANCE (2026-08-22): reemplaza el viejo comportamiento
    # (BASELINE se promovia, EXPERIMENTAL no) -- HOY, sin ninguna hipotesis
    # CERTIFICADA, NINGUNO de los dos se promueve, sin importar la
    # gobernanza de familia del motor. "Hoy no hay picks certificados" debe
    # ser el resultado honesto, no una excepcion.
    monkeypatch.setattr(pick_governance, "load_hypotheses", lambda path=None: [])
    work = _picks_env
    match_list = [
        {"id": "a-b-1", "home": "A", "away": "B", "league": "L", "kickoffUTC": _picks_kickoff(0)},
        {"id": "c-d-2", "home": "C", "away": "D", "league": "L", "kickoffUTC": _picks_kickoff(2)},
    ]
    pocket = {
        "a-b-1": {"resolved": True, "markets": {
            "OU25_GOALS_FT": {"probability": {"over": 0.60, "under": 0.40}, "governance_status": "BASELINE", "engine_id": "e"},
        }},
        "c-d-2": {"resolved": True, "markets": {
            "OU25_GOALS_FT": {"probability": {"over": 0.60, "under": 0.40}, "governance_status": "EXPERIMENTAL", "engine_id": "e2"},
        }},
    }
    lean = {
        "a-b-1": {"OU25_GOALS_FT": {"bk": "Pinnacle", "sel": {"over": {"p": 1.90, "t": "T1"}}}},
        "c-d-2": {"OU25_GOALS_FT": {"bk": "Pinnacle", "sel": {"over": {"p": 1.90, "t": "T2"}}}},
    }
    _wj(work / "match_list.json", match_list)
    _wj(work / "pocket_engine_results.json", pocket)
    _wj(work / "historical_stats_results.json", {})
    _wj(work / "match_event_ids.json", {"a-b-1": {"event_id": 1}, "c-d-2": {"event_id": 2}})
    _wj(work / "oddspapi_lean.json", lean)

    resumen = picks.run()
    assert resumen["candidatos_evaluados"] == 2
    assert resumen["value_detectado"] == 2  # ambos EV>0 -- "value" sigue siendo solo EV
    assert resumen["picks_nuevos"] == 0  # CAMBIO CENTRAL: ninguno se promueve sin certificacion

    estado = json.load(open(picks.PICKS_STATE_PATH, encoding="utf-8"))
    assert estado["picks_activos"] == 0
    assert not os.path.exists(picks.PICKS_HISTORY_PATH)  # nada elegible -> nunca se crea el archivo


def test_run_hipotesis_certificada_si_genera_pick(_picks_env, monkeypatch):
    # Camino positivo: con una hipotesis CERTIFICADA que coincide exacto
    # (mercado+seleccion+motor+umbral), el pick SI se genera -- prueba que
    # el nuevo gate no esta simplemente siempre cerrado.
    monkeypatch.setattr(pick_governance, "load_hypotheses", lambda path=None: [
        _hyp(hypothesis_id="OVER25_TEST_V1", mercado="OU25_GOALS_FT", seleccion="over",
             motor_esperado="e", umbral_prob=0.50, estado=pick_governance.HypothesisStatus.CERTIFICADO)
    ])
    work = _picks_env
    match_list = _base_match_list()
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "OU25_GOALS_FT": {"probability": {"over": 0.60, "under": 0.40}, "governance_status": "BASELINE", "engine_id": "e"},
    }}}
    lean = {"a-b-1": {"OU25_GOALS_FT": {"bk": "Pinnacle", "sel": {"over": {"p": 1.90, "t": "T"}}}}}
    _wj(work / "match_list.json", match_list)
    _wj(work / "pocket_engine_results.json", pocket)
    _wj(work / "historical_stats_results.json", {})
    _wj(work / "match_event_ids.json", {"a-b-1": {"event_id": 1}})
    _wj(work / "oddspapi_lean.json", lean)

    resumen = picks.run()
    assert resumen["picks_nuevos"] == 1
    estado = json.load(open(picks.PICKS_STATE_PATH, encoding="utf-8"))
    assert estado["picks_activos"] == 1
    lines = [json.loads(l) for l in open(picks.PICKS_HISTORY_PATH, encoding="utf-8").read().strip().split("\n")]
    assert lines[0]["hypothesis_id"] == "OVER25_TEST_V1"
    assert lines[0]["estado"] == "PENDIENTE"


def test_run_exclusion_mutua_1x2_end_to_end(_picks_env, monkeypatch):
    # Dos selecciones de 1X2 del MISMO partido, ambas bajo una hipotesis
    # certificada (umbral bajo a proposito para forzar el caso) -- solo la
    # de mayor EV% debe quedar como Pick activo; la otra se conserva en el
    # historico con estado ELEGIBLE_NO_DOMINANTE, nunca como pick simultaneo.
    monkeypatch.setattr(pick_governance, "load_hypotheses", lambda path=None: [
        _hyp(hypothesis_id="HOME_1X2_TEST_V1", mercado="1X2_FT", seleccion="home",
             motor_esperado="form_calculator", umbral_prob=0.10, estado=pick_governance.HypothesisStatus.CERTIFICADO),
        _hyp(hypothesis_id="AWAY_1X2_TEST_V1", mercado="1X2_FT", seleccion="away",
             motor_esperado="form_calculator", umbral_prob=0.10, estado=pick_governance.HypothesisStatus.CERTIFICADO),
    ])
    work = _picks_env
    match_list = _base_match_list()
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "1X2_FT": {"probability": {"home": 0.40, "draw": 0.20, "away": 0.40}, "governance_status": "BASELINE", "engine_id": "form_calculator"},
    }}}
    lean = {"a-b-1": {"1X2_FT": {"bk": "Pinnacle", "bookmakerIsActive": True, "sel": {
        "home": {"p": 2.00, "t": "T", "active": True, "marketActive": True},   # EV = 0.40*2.00-1 = -0.20 (no es value)
        "away": {"p": 3.00, "t": "T", "active": True, "marketActive": True},   # EV = 0.40*3.00-1 = +0.20 (si es value)
    }}}}
    _wj(work / "match_list.json", match_list)
    _wj(work / "pocket_engine_results.json", pocket)
    _wj(work / "historical_stats_results.json", {})
    _wj(work / "match_event_ids.json", {"a-b-1": {"event_id": 1}})
    _wj(work / "oddspapi_lean.json", lean)

    picks.run()
    estado = json.load(open(picks.PICKS_STATE_PATH, encoding="utf-8"))
    assert estado["picks_activos"] == 1
    assert estado["picks"][0]["selection"] == "away"  # unica con EV>0, "home" ni siquiera es "value"


def test_run_no_reregistra_pick_ya_registrado_aunque_cambien_los_numeros(_picks_env, monkeypatch):
    monkeypatch.setattr(pick_governance, "load_hypotheses", lambda path=None: [
        _hyp(hypothesis_id="OVER25_TEST_V1", mercado="OU25_GOALS_FT", seleccion="over",
             motor_esperado="e", umbral_prob=0.50, estado=pick_governance.HypothesisStatus.CERTIFICADO)
    ])
    work = _picks_env
    match_list = _base_match_list()
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "OU25_GOALS_FT": {"probability": {"over": 0.60, "under": 0.40}, "governance_status": "BASELINE", "engine_id": "e"},
    }}}
    lean = {"a-b-1": {"OU25_GOALS_FT": {"bk": "Pinnacle", "sel": {"over": {"p": 1.90, "t": "T"}}}}}
    _wj(work / "match_list.json", match_list)
    _wj(work / "pocket_engine_results.json", pocket)
    _wj(work / "historical_stats_results.json", {})
    _wj(work / "match_event_ids.json", {"a-b-1": {"event_id": 1}})
    _wj(work / "oddspapi_lean.json", lean)

    picks.run()
    first = json.load(open(picks.PICKS_STATE_PATH, encoding="utf-8"))["picks"][0]
    assert first["cuota"] == 1.90

    # ATLAS "recalcula" con una cuota/probabilidad distinta -- el pick ya
    # registrado en el historico NUNCA cambia (inmutabilidad, Objetivo 5).
    pocket["a-b-1"]["markets"]["OU25_GOALS_FT"]["probability"] = {"over": 0.90, "under": 0.10}
    lean["a-b-1"]["OU25_GOALS_FT"]["sel"]["over"]["p"] = 3.50
    _wj(work / "pocket_engine_results.json", pocket)
    _wj(work / "oddspapi_lean.json", lean)
    resumen2 = picks.run()
    assert resumen2["picks_nuevos"] == 0  # ya estaba registrado, no se duplica

    lines = [json.loads(l) for l in open(picks.PICKS_HISTORY_PATH, encoding="utf-8").read().strip().split("\n")]
    assert len(lines) == 1
    assert lines[0]["cuota"] == 1.90  # inmutable, nunca 3.50
    assert lines[0]["probabilidad_atlas"] == 0.6  # inmutable, nunca 0.9


# ---------------------------------------------------------------------
# settlement.py -- performance_summary (Objetivo 6)
# ---------------------------------------------------------------------

def test_performance_summary_agrega_correctamente(tmp_path, monkeypatch):
    path = tmp_path / "picks_history.jsonl"
    records = [
        {"pick_id": "1", "market": "OU25_GOALS_FT", "liga": "L1", "estado": "GANADO", "roi_pct": 90.0, "ev_pct": 10.0},
        {"pick_id": "2", "market": "OU25_GOALS_FT", "liga": "L1", "estado": "PERDIDO", "roi_pct": -100.0, "ev_pct": 5.0},
        {"pick_id": "3", "market": "BTTS", "liga": "L2", "estado": "PENDIENTE", "roi_pct": None, "ev_pct": 8.0},
    ]
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    resumen = settlement.performance_summary(str(path))
    assert resumen["total"] == 3
    assert resumen["ganados"] == 1 and resumen["perdidos"] == 1 and resumen["pendientes"] == 1
    assert resumen["win_rate_pct"] == 50.0
    assert resumen["roi_pct"] == pytest.approx((90.0 + -100.0) / 2)
    assert resumen["yield_pct"] == resumen["roi_pct"]
    assert resumen["por_mercado"]["OU25_GOALS_FT"]["total"] == 2
    assert resumen["por_liga"]["L2"]["total"] == 1


def test_performance_summary_vacio_no_rompe(tmp_path):
    resumen = settlement.performance_summary(str(tmp_path / "no_existe.jsonl"))
    assert resumen["total"] == 0
    assert resumen["win_rate_pct"] is None


# ---------------------------------------------------------------------
# hypothesis_shadow.py -- Señales en Observación (2026-08-22, PICK
# GOVERNANCE). Aislamiento total del ledger real -- misma tecnica que
# atlas_engine/tests/unit/test_shadow_trackrecord_scoping.py (monkeypatch de
# TRACKRECORD_DB en store.py Y db_safety.py, nunca toca la base real).
# ---------------------------------------------------------------------

import atlas_pocket.trackrecord.store as trackrecord_store
import atlas_pocket.trackrecord.db_safety as trackrecord_db_safety
import atlas_pocket.trackrecord.resolution as trackrecord_resolution
from atlas_pocket.engines import shadow as pocket_shadow


@pytest.fixture
def _isolated_trackrecord_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_trackrecord.db"
    monkeypatch.setattr(trackrecord_store, "TRACKRECORD_DB", str(db_path))
    monkeypatch.setattr(trackrecord_db_safety, "TRACKRECORD_DB", str(db_path))
    return db_path


def _hyp_json(tmp_path, *hyps):
    path = tmp_path / "thresholds.json"
    path.write_text(json.dumps({"version": "test", "hypotheses": list(hyps)}), encoding="utf-8")
    return str(path)


def _hyp_dict(hypothesis_id="AWAY_1X2_P50_V1", mercado="1X2_FT", seleccion="away",
              motor_esperado="form_calculator", umbral_prob=0.50, estado="EN_OBSERVACION", retirada=False):
    return {"hypothesis_id": hypothesis_id, "mercado": mercado, "seleccion": seleccion,
            "motor_esperado": motor_esperado, "umbral_prob": umbral_prob, "estado": estado, "retirada": retirada}


def test_log_hypothesis_candidates_registra_con_namespace_pickgov(_isolated_trackrecord_db, monkeypatch, tmp_path):
    hyp_path = _hyp_json(tmp_path, _hyp_dict())
    monkeypatch.setattr(pick_governance, "THRESHOLDS_PATH", hyp_path)

    match_list = [{"id": "a-b-1", "home": "A", "away": "B", "league": "L", "kickoffUTC": "2026-09-01T18:00:00Z"}]
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "1X2_FT": {"probability": {"home": 0.30, "draw": 0.20, "away": 0.55}, "governance_status": "BASELINE", "engine_id": "form_calculator"},
    }}}
    lean = {"a-b-1": {"1X2_FT": {"bk": "Pinnacle", "sel": {"away": {"p": 2.10, "t": "T"}}}}}
    match_event_ids = {"a-b-1": {"event_id": 555}}

    result = hypothesis_shadow.log_hypothesis_candidates(pocket=pocket, oddspapi_lean=lean, match_list=match_list, match_event_ids=match_event_ids)
    assert result["registrados"] == 1

    conn = trackrecord_store._connect()
    try:
        row = conn.execute("SELECT * FROM predictions WHERE event_id=555").fetchone()
    finally:
        conn.close()
    assert row["motor"] == "form_calculator+pickgov"  # namespace obligatorio -- nunca "form_calculator" puro
    assert row["hypothesis_id"] == "AWAY_1X2_P50_V1"
    assert row["cuota_mercado"] == 2.10  # cuota REAL capturada (a diferencia de shadow.py, que la deja en None)
    assert row["prob_atlas"] == 0.55


def test_log_hypothesis_candidates_idempotente(_isolated_trackrecord_db, monkeypatch, tmp_path):
    hyp_path = _hyp_json(tmp_path, _hyp_dict())
    monkeypatch.setattr(pick_governance, "THRESHOLDS_PATH", hyp_path)
    match_list = [{"id": "a-b-1", "home": "A", "away": "B", "league": "L", "kickoffUTC": "2026-09-01T18:00:00Z"}]
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "1X2_FT": {"probability": {"home": 0.30, "draw": 0.20, "away": 0.55}, "governance_status": "BASELINE", "engine_id": "form_calculator"},
    }}}
    lean = {"a-b-1": {"1X2_FT": {"bk": "Pinnacle", "sel": {"away": {"p": 2.10, "t": "T"}}}}}
    match_event_ids = {"a-b-1": {"event_id": 555}}

    r1 = hypothesis_shadow.log_hypothesis_candidates(pocket=pocket, oddspapi_lean=lean, match_list=match_list, match_event_ids=match_event_ids)
    r2 = hypothesis_shadow.log_hypothesis_candidates(pocket=pocket, oddspapi_lean=lean, match_list=match_list, match_event_ids=match_event_ids)
    assert r1["registrados"] == 1
    assert r2["registrados"] == 0 and r2["ya_registrados"] == 1  # nunca duplica


def test_log_hypothesis_candidates_prob_bajo_umbral_no_registra(_isolated_trackrecord_db, monkeypatch, tmp_path):
    hyp_path = _hyp_json(tmp_path, _hyp_dict(umbral_prob=0.60))
    monkeypatch.setattr(pick_governance, "THRESHOLDS_PATH", hyp_path)
    match_list = [{"id": "a-b-1", "home": "A", "away": "B", "league": "L", "kickoffUTC": "2026-09-01T18:00:00Z"}]
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "1X2_FT": {"probability": {"home": 0.30, "draw": 0.20, "away": 0.55}, "governance_status": "BASELINE", "engine_id": "form_calculator"},
    }}}
    lean = {"a-b-1": {"1X2_FT": {"bk": "Pinnacle", "sel": {"away": {"p": 2.10, "t": "T"}}}}}
    result = hypothesis_shadow.log_hypothesis_candidates(pocket=pocket, oddspapi_lean=lean, match_list=match_list, match_event_ids={"a-b-1": {"event_id": 555}})
    assert result["registrados"] == 0  # 0.55 < 0.60 -- no cumple ESTA hipotesis


def test_log_hypothesis_candidates_motor_distinto_no_registra(_isolated_trackrecord_db, monkeypatch, tmp_path):
    # La hipotesis congelo "form_calculator" -- si el pipeline reporta un
    # motor distinto para ese mercado/seleccion, nunca se evalua con el motor
    # equivocado (inmutabilidad de la hipotesis: motor es parte de lo congelado).
    hyp_path = _hyp_json(tmp_path, _hyp_dict(motor_esperado="form_calculator"))
    monkeypatch.setattr(pick_governance, "THRESHOLDS_PATH", hyp_path)
    match_list = [{"id": "a-b-1", "home": "A", "away": "B", "league": "L", "kickoffUTC": "2026-09-01T18:00:00Z"}]
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "1X2_FT": {"probability": {"home": 0.30, "draw": 0.20, "away": 0.55}, "governance_status": "BASELINE", "engine_id": "form_calculator_lineup_challenger"},
    }}}
    lean = {"a-b-1": {"1X2_FT": {"bk": "Pinnacle", "sel": {"away": {"p": 2.10, "t": "T"}}}}}
    result = hypothesis_shadow.log_hypothesis_candidates(pocket=pocket, oddspapi_lean=lean, match_list=match_list, match_event_ids={"a-b-1": {"event_id": 555}})
    assert result["registrados"] == 0


def test_log_hypothesis_candidates_sin_cuota_real_no_registra(_isolated_trackrecord_db, monkeypatch, tmp_path):
    hyp_path = _hyp_json(tmp_path, _hyp_dict())
    monkeypatch.setattr(pick_governance, "THRESHOLDS_PATH", hyp_path)
    match_list = [{"id": "a-b-1", "home": "A", "away": "B", "league": "L", "kickoffUTC": "2026-09-01T18:00:00Z"}]
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "1X2_FT": {"probability": {"home": 0.30, "draw": 0.20, "away": 0.55}, "governance_status": "BASELINE", "engine_id": "form_calculator"},
    }}}
    result = hypothesis_shadow.log_hypothesis_candidates(pocket=pocket, oddspapi_lean={}, match_list=match_list, match_event_ids={"a-b-1": {"event_id": 555}})
    assert result["registrados"] == 0 and result["sin_cuota"] == 1  # nunca se inventa una cuota


def test_log_hypothesis_candidates_hipotesis_retirada_nunca_acumula(_isolated_trackrecord_db, monkeypatch, tmp_path):
    hyp_path = _hyp_json(tmp_path, _hyp_dict(retirada=True))
    monkeypatch.setattr(pick_governance, "THRESHOLDS_PATH", hyp_path)
    match_list = [{"id": "a-b-1", "home": "A", "away": "B", "league": "L", "kickoffUTC": "2026-09-01T18:00:00Z"}]
    pocket = {"a-b-1": {"resolved": True, "markets": {
        "1X2_FT": {"probability": {"home": 0.30, "draw": 0.20, "away": 0.55}, "governance_status": "BASELINE", "engine_id": "form_calculator"},
    }}}
    lean = {"a-b-1": {"1X2_FT": {"bk": "Pinnacle", "sel": {"away": {"p": 2.10, "t": "T"}}}}}
    result = hypothesis_shadow.log_hypothesis_candidates(pocket=pocket, oddspapi_lean=lean, match_list=match_list, match_event_ids={"a-b-1": {"event_id": 555}})
    assert result["registrados"] == 0


def test_migracion_no_toca_filas_existentes_ni_asigna_hypothesis_id_retroactivo(_isolated_trackrecord_db):
    # Simula una fila "antigua" (pre-hypothesis_id) escrita ANTES de que este
    # mecanismo existiera -- debe seguir con hypothesis_id=NULL para siempre,
    # nunca se le asigna uno retroactivamente.
    old_pid = trackrecord_store.log_prediction(trackrecord_store.PredictionRecord(
        event_id=1001, fecha_partido="2026-07-01", partido="Old vs Match",
        mercado="1X2_FT", seleccion="home", prob_atlas=0.5,
        cuota_justa=2.0, cuota_mercado=None, prob_implicita=None, diferencia=None,
        motor="form_calculator", version="1.0.0", governance_status="BASELINE",
    ))
    conn = trackrecord_store._connect()
    try:
        row = conn.execute("SELECT hypothesis_id FROM predictions WHERE prediction_id=?", (old_pid,)).fetchone()
    finally:
        conn.close()
    assert row["hypothesis_id"] is None


def test_resolucion_automatica_procesa_filas_pickgov(_isolated_trackrecord_db, monkeypatch, tmp_path):
    # Condicion D del mandato: la resolucion automatica de store.py (via
    # resolution.resolve_track_record(), corre sola en cada conexion) SI
    # debe procesar las filas con namespace "+pickgov" -- a diferencia de las
    # de Shadow Mode puro, que quedan reservadas y excluidas a proposito.
    pid = trackrecord_store.log_prediction(trackrecord_store.PredictionRecord(
        event_id=2002, fecha_partido="2026-07-01", partido="Home vs Away",
        mercado="1X2_FT", seleccion="away", prob_atlas=0.55,
        cuota_justa=1.8, cuota_mercado=2.10, prob_implicita=0.48, diferencia=0.07,
        motor="form_calculator+pickgov", version="AWAY_1X2_P50_V1", governance_status="BASELINE",
        hypothesis_id="AWAY_1X2_P50_V1",
    ))

    class _Res:
        score_home, score_away, corner_total, sot_total, cards_total, shots_total = 0, 2, None, None, None, None

    monkeypatch.setattr(trackrecord_resolution, "_load_finished_match_results", lambda ids: {2002: _Res()} if 2002 in ids else {})
    result = trackrecord_resolution.resolve_track_record()
    assert result["resolved"] == 1

    conn = trackrecord_store._connect()
    try:
        row = conn.execute("SELECT acierto, resultado_real FROM resolutions WHERE prediction_id=?", (pid,)).fetchone()
    finally:
        conn.close()
    assert row["acierto"] == "acierto" and row["resultado_real"] == "away"


def test_pickgov_nunca_contamina_la_comparacion_baseline_vs_challenger(_isolated_trackrecord_db, monkeypatch):
    # Condicion E del mandato -- la MAS critica. HALLAZGO REAL durante la
    # implementacion (no anticipado en el diseno de la seccion 17.D): la
    # SELECT de compute_shadow_evidence() filtra SOLO por `mercado = ?`
    # (1X2_FT), sin filtrar por motor -- a diferencia de resolve_track_
    # record()/ranking.py, que SI excluyen por SHADOW_MODE_ENGINE_IDS. Esto
    # significa que el agregado top-level `n_resolved_events` SI puede
    # incluir eventos que tambien tienen una fila "+pickgov" para el mismo
    # mercado (comportamiento YA EXISTENTE de shadow.py, no introducido por
    # este cambio -- hoy no se manifiesta en produccion porque ningun otro
    # motor usaba mercado="1X2_FT" hasta ahora). Corregirlo requeriria tocar
    # shadow.py, prohibido explicitamente por el mandato ("no debe alterar la
    # logica de negocio actual") -- se documenta como limitacion residual,
    # NO se oculta. Lo que SI esta garantizado y se prueba aqui es lo
    # realmente critico: la comparacion CIENTIFICA por motor (Brier/LogLoss/
    # ECE/N de form_calculator vs. form_calculator_lineup_challenger) queda
    # EXACTA e inalterada -- el namespace "+pickgov" nunca aparece como
    # entrada propia salvo bajo su propia clave, separada.
    pid_shadow = trackrecord_store.log_prediction(trackrecord_store.PredictionRecord(
        event_id=3003, fecha_partido="2026-07-01", partido="Shadow vs Match",
        mercado="1X2_FT", seleccion="home", prob_atlas=0.5,
        cuota_justa=2.0, cuota_mercado=None, prob_implicita=None, diferencia=None,
        motor="form_calculator", version="1.0.0", governance_status="BASELINE",
    ))
    trackrecord_store.add_resolution(pid_shadow, "home", "acierto")

    evidence_before = pocket_shadow.compute_shadow_evidence()

    pid_pickgov = trackrecord_store.log_prediction(trackrecord_store.PredictionRecord(
        event_id=4004, fecha_partido="2026-07-01", partido="PickGov vs Match",
        mercado="1X2_FT", seleccion="away", prob_atlas=0.55,
        cuota_justa=1.8, cuota_mercado=2.10, prob_implicita=0.48, diferencia=0.07,
        motor="form_calculator+pickgov", version="AWAY_1X2_P50_V1", governance_status="BASELINE",
        hypothesis_id="AWAY_1X2_P50_V1",
    ))
    trackrecord_store.add_resolution(pid_pickgov, "away", "acierto")

    evidence_after = pocket_shadow.compute_shadow_evidence()

    # GARANTIA CRITICA (verificada, no asumida): los numeros cientificos por
    # motor de la comparacion real (form_calculator / lineup_challenger) son
    # BIT A BIT IDENTICOS antes y despues de que exista una fila pickgov.
    assert evidence_after["by_motor"]["form_calculator"] == evidence_before["by_motor"]["form_calculator"]
    assert "form_calculator_lineup_challenger" not in evidence_after["by_motor"] or \
        evidence_after["by_motor"]["form_calculator_lineup_challenger"] == evidence_before["by_motor"].get("form_calculator_lineup_challenger")
    # La fila pickgov aparece bajo SU PROPIA clave separada -- nunca se
    # mezcla dentro de "form_calculator".
    assert evidence_after["by_motor"]["form_calculator"]["n_events"] == 1
    assert evidence_after["by_motor"]["form_calculator+pickgov"]["n_events"] == 1
    # LIMITACION RESIDUAL DOCUMENTADA (no oculta): el agregado top-level SI
    # crece, porque cuenta distinct event_id sin filtrar motor -- ver
    # docstring de este test y AUDITORIA_PICK_GOVERNANCE_2026-08-22.md.
    assert evidence_before["n_resolved_events"] == 1
    assert evidence_after["n_resolved_events"] == 2


def test_hipotesis_v1_y_v2_nunca_mezclan_evidencia(_isolated_trackrecord_db):
    # Condicion 3/G del mandato: cambiar el umbral crea una hipotesis NUEVA
    # (hypothesis_id distinto) -- compute_hypothesis_evidence() de cada una
    # debe ser completamente independiente, aunque compartan mercado/motor.
    pid_v1 = trackrecord_store.log_prediction(trackrecord_store.PredictionRecord(
        event_id=5001, fecha_partido="2026-07-01", partido="V1 Match",
        mercado="1X2_FT", seleccion="away", prob_atlas=0.51,
        cuota_justa=1.9, cuota_mercado=2.20, prob_implicita=0.45, diferencia=0.06,
        motor="form_calculator+pickgov", version="AWAY_1X2_P50_V1", governance_status="BASELINE",
        hypothesis_id="AWAY_1X2_P50_V1",
    ))
    trackrecord_store.add_resolution(pid_v1, "away", "acierto")

    pid_v2 = trackrecord_store.log_prediction(trackrecord_store.PredictionRecord(
        event_id=5002, fecha_partido="2026-07-01", partido="V2 Match",
        mercado="1X2_FT", seleccion="away", prob_atlas=0.58,
        cuota_justa=1.7, cuota_mercado=1.60, prob_implicita=0.63, diferencia=-0.05,
        motor="form_calculator+pickgov", version="AWAY_1X2_P55_V2", governance_status="BASELINE",
        hypothesis_id="AWAY_1X2_P55_V2",
    ))
    trackrecord_store.add_resolution(pid_v2, "home", "fallo")

    ev_v1 = hypothesis_shadow.compute_hypothesis_evidence("AWAY_1X2_P50_V1")
    ev_v2 = hypothesis_shadow.compute_hypothesis_evidence("AWAY_1X2_P55_V2")
    assert ev_v1["n_resolved"] == 1 and ev_v1["win_rate"] == 1.0
    assert ev_v2["n_resolved"] == 1 and ev_v2["win_rate"] == 0.0
    assert ev_v1["hypothesis_id"] != ev_v2["hypothesis_id"]


def test_compute_hypothesis_evidence_sin_evidencia_devuelve_insuficiente(_isolated_trackrecord_db):
    result = hypothesis_shadow.compute_hypothesis_evidence("NO_EXISTE_TODAVIA")
    assert result["n_resolved"] == 0
    assert result["verdict"] == "insufficient_evidence"


def test_backup_diario_protege_tambien_las_filas_de_pickgov(_isolated_trackrecord_db, tmp_path, monkeypatch):
    # Condicion I del mandato: el backup existente (db_safety.py) no
    # distingue por tipo de fila -- protege la base entera, incluidas las
    # filas de hypothesis_shadow, sin ningun cambio en db_safety.py. Se
    # redirige DEFAULT_TRACKRECORD_DB (no solo TRACKRECORD_DB) para que
    # is_production_db() -- que compara ambos -- de True de forma honesta,
    # en vez de forzar su resultado.
    db_path = _isolated_trackrecord_db
    trackrecord_store.log_prediction(trackrecord_store.PredictionRecord(
        event_id=6006, fecha_partido="2026-07-01", partido="Backup Match",
        mercado="1X2_FT", seleccion="away", prob_atlas=0.55,
        cuota_justa=1.8, cuota_mercado=2.10, prob_implicita=0.48, diferencia=0.07,
        motor="form_calculator+pickgov", version="AWAY_1X2_P50_V1", governance_status="BASELINE",
        hypothesis_id="AWAY_1X2_P50_V1",
    ))
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(trackrecord_db_safety, "DEFAULT_TRACKRECORD_DB", str(db_path))
    monkeypatch.setattr(trackrecord_db_safety, "_backups_dir", lambda: backup_dir)

    result_path = trackrecord_db_safety.ensure_backup_if_production()
    assert result_path is not None and Path(result_path).exists()

    # El backup debe contener la fila de pickgov -- verificacion real, no solo
    # "se creo un archivo".
    import sqlite3 as _sqlite3
    bconn = _sqlite3.connect(str(result_path))
    try:
        row = bconn.execute("SELECT hypothesis_id FROM predictions WHERE event_id=6006").fetchone()
    finally:
        bconn.close()
    assert row is not None and row[0] == "AWAY_1X2_P50_V1"
