# -*- coding: utf-8 -*-
"""Tests de atlas_lab_mockup/tipster/ (Tipster ATLAS, 2026-08-16). Patron
pytest ya usado en atlas_lab_mockup/oddspapi/tests/test_oddspapi.py:
monkeypatch + tmp_path, datos sinteticos, sin red/DB real -- las funciones
que consultan soccer_analytics.db (finished_event_ids/settle_*) se
inyectan/monkeypatchean, nunca se golpea la base real en un test."""
import datetime
import json

import pytest

from atlas_lab_mockup.tipster import common, governance, picks, rankings, settlement


# ---------------------------------------------------------------------
# governance.py
# ---------------------------------------------------------------------

def test_strong_governance_son_los_3_valores_reales():
    assert governance.STRONG_GOVERNANCE == ("CERTIFICADO", "PROMOVIDO", "BASELINE")


def test_gate_pasa_baseline_y_rechaza_experimental():
    assert governance.passes_governance_gate("BASELINE") is True
    assert governance.passes_governance_gate("CERTIFICADO") is True
    assert governance.passes_governance_gate("EXPERIMENTAL") is False
    assert governance.passes_governance_gate("NO_DISPONIBLE") is False


def test_gate_sin_gobernanza_pasa_por_defecto_btts():
    # Decision explicita del Director 2026-08-16: BTTS no tiene motor
    # gobernado, pero puede llegar a ser PICK igual que los demas.
    assert governance.passes_governance_gate(None) is True


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


def test_btts_sin_gobernancia_puede_ser_pick_decision_del_director():
    c = {"ev_pct": 12.0, "governance_status": None}
    es_value, es_pick = picks.classify(c)
    assert es_value is True and es_pick is True  # decision explicita 2026-08-16


def test_ev_negativo_no_es_value_ni_pick():
    c = {"ev_pct": -5.0, "governance_status": "BASELINE"}
    es_value, es_pick = picks.classify(c)
    assert es_value is False and es_pick is False


def test_ev_positivo_pero_governance_experimental_es_value_no_pick():
    c = {"ev_pct": 8.0, "governance_status": "EXPERIMENTAL"}
    es_value, es_pick = picks.classify(c)
    assert es_value is True and es_pick is False  # gate de gobernanza -- no autopromueve


def test_ev_positivo_governance_baseline_es_pick():
    c = {"ev_pct": 8.0, "governance_status": "BASELINE"}
    es_value, es_pick = picks.classify(c)
    assert es_value is True and es_pick is True


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


def test_run_registra_pick_y_no_registra_candidato_experimental(_picks_env):
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
    assert resumen["value_detectado"] == 2  # ambos EV>0
    assert resumen["picks_nuevos"] == 1  # solo el BASELINE se promueve a pick

    estado = json.load(open(picks.PICKS_STATE_PATH, encoding="utf-8"))
    assert estado["picks_activos"] == 1
    assert estado["picks"][0]["event_id"] == 1

    lines = [json.loads(l) for l in open(picks.PICKS_HISTORY_PATH, encoding="utf-8").read().strip().split("\n")]
    assert len(lines) == 1
    assert lines[0]["pick_id"] == "1:OU25_GOALS_FT:over"
    assert lines[0]["estado"] == "PENDIENTE"


def test_run_no_reregistra_pick_ya_registrado_aunque_cambien_los_numeros(_picks_env):
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
