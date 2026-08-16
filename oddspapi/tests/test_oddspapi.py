# -*- coding: utf-8 -*-
"""Validacion obligatoria de la integracion OddsPapi FREE en ATLAS LAB
(Edificio 5) -- ver plan de implementacion (2026-08-16). EXCLUSIVA de la
herramienta pre-partido, no relacionada con Odds-API.io/sistema LIVE.

Cubre, sin ninguna llamada de red real y sin tocar ningun archivo de
produccion (todo el I/O de estos tests va a tmp_path, aislado):
  - importacion correcta de los 6 modulos.
  - la API key se lee EXCLUSIVAMENTE de la variable de entorno
    ODDSPAPI_API_KEY (nunca hardcodeada, nunca ODDS_API_KEY).
  - presupuesto MENSUAL: cuenta por mes calendario, respeta el 80%, sembrado
    idempotente.
  - mapeo de liga fail-closed: 0 candidatos -> LIGA_NO_MAPEADA, 2+ ->
    LIGA_AMBIGUA, nunca adivina.
  - matching de fixture: sofascoreId directo (via primaria) y fallback por
    nombre, con los 4 estados fail-closed.
  - extraccion de linea exacta: linea presente -> precio correcto; linea
    ausente -> LINE_UNAVAILABLE, NUNCA sustituye por otra linea.
  - BOOKMAKER_PRIMARIO_ODDSPAPI == "Pinnacle" (decision del Director,
    2026-08-16, bloqueada por este test igual que el patron hermano bloquea
    "Bet365").
  - aislamiento total: ningun modulo de esta integracion importa nada del
    sistema LIVE (12 estrategias, notify/, IP001, odds_api_io_*, etc.).
"""
import inspect

import atlas_lab_mockup.oddspapi.client as client
import atlas_lab_mockup.oddspapi.rate_budget as rate_budget
import atlas_lab_mockup.oddspapi.league_mapping as league_mapping
import atlas_lab_mockup.oddspapi.matching as matching
import atlas_lab_mockup.oddspapi.line_extraction as line_extraction
import atlas_lab_mockup.oddspapi.capture as capture


# ---------------------------------------------------------------------------
# 1) Importacion correcta
# ---------------------------------------------------------------------------

def test_los_6_modulos_importan_y_exponen_su_api_publica():
    assert callable(client.get_account)
    assert callable(client.get_tournaments)
    assert callable(client.get_markets)
    assert callable(client.get_odds_by_tournaments)
    assert callable(rate_budget.status)
    assert callable(rate_budget.can_call)
    assert callable(rate_budget.record_call)
    assert callable(rate_budget.seed_current_month)
    assert callable(league_mapping.resolve_tournament_id)
    assert callable(league_mapping.refresh_tournament_catalog)
    assert callable(matching.match_fixture)
    assert callable(line_extraction.extract_1x2)
    assert callable(line_extraction.extract_btts)
    assert callable(line_extraction.extract_over_under_25)
    assert callable(line_extraction.extract_asian_handicap)
    assert callable(capture.run)


# ---------------------------------------------------------------------------
# 2) API key EXCLUSIVAMENTE por variable de entorno, nombre distinto al LIVE
# ---------------------------------------------------------------------------

def test_api_key_ausente_produce_error_controlado_sin_llamada_de_red(monkeypatch):
    monkeypatch.delenv(client.ENV_VAR_NAME, raising=False)
    import pytest
    with pytest.raises(client.MissingApiKeyError):
        client._api_key()

    resp = client.get_account()
    assert resp["status"] is None
    assert "MissingApiKeyError" in (resp["error"] or "")
    assert resp["data"] is None


def test_env_var_name_es_distinto_del_sistema_live():
    assert client.ENV_VAR_NAME == "ODDSPAPI_API_KEY"
    assert client.ENV_VAR_NAME != "ODDS_API_KEY"


_FAKE_KEY_PARA_TEST = "aaaa0000-1111-2222-3333-bbbbccccdddd"


def test_api_key_nunca_aparece_hardcodeada_en_el_codigo_fuente():
    fuente = inspect.getsource(client)
    assert _FAKE_KEY_PARA_TEST not in fuente
    assert "os.environ.get(ENV_VAR_NAME)" in fuente


def test_mask_key_nunca_expone_la_clave_completa():
    masked = client._mask_key(_FAKE_KEY_PARA_TEST)
    assert _FAKE_KEY_PARA_TEST not in masked
    assert masked.startswith("aaaa")


# ---------------------------------------------------------------------------
# 3) Presupuesto MENSUAL (aislado en tmp_path, nunca el estado real)
# ---------------------------------------------------------------------------

def test_presupuesto_mensual_cuenta_y_respeta_margen_80_por_ciento(tmp_path, monkeypatch):
    monkeypatch.setattr(rate_budget, "STATE_PATH", tmp_path / "rate_budget_test.json")

    assert rate_budget.can_call() is True
    for _ in range(rate_budget.MONTHLY_CAP):
        rate_budget.record_call()
    st = rate_budget.status()
    assert st["requests_este_mes"] == rate_budget.MONTHLY_CAP
    assert st["puede_llamar"] is False
    assert rate_budget.can_call() is False
    assert rate_budget.MONTHLY_CAP == int(250 * 0.80) == 200


def test_presupuesto_mensual_resetea_en_mes_calendario_nuevo(tmp_path, monkeypatch):
    monkeypatch.setattr(rate_budget, "STATE_PATH", tmp_path / "rate_budget_test.json")
    import json as _json

    # 5 llamadas registradas en julio, ninguna debe contar para agosto
    state = {"call_timestamps_utc": [
        "2026-07-31T23:59:00.000000Z", "2026-07-31T23:58:00.000000Z",
        "2026-07-30T10:00:00.000000Z", "2026-07-29T10:00:00.000000Z", "2026-07-28T10:00:00.000000Z",
    ], "seed": None}
    (tmp_path / "rate_budget_test.json").write_text(_json.dumps(state), encoding="utf-8")

    monkeypatch.setattr(rate_budget, "_now", lambda: __import__("datetime").datetime(
        2026, 8, 1, 0, 1, 0, tzinfo=__import__("datetime").timezone.utc))
    st = rate_budget.status()
    assert st["requests_este_mes"] == 0  # ninguna de julio cuenta en agosto
    assert st["mes"] == "2026-08"


def test_sembrado_es_idempotente_por_mes(tmp_path, monkeypatch):
    monkeypatch.setattr(rate_budget, "STATE_PATH", tmp_path / "rate_budget_test.json")
    rate_budget.seed_current_month(12)
    assert rate_budget.status()["requests_este_mes"] == 12
    rate_budget.seed_current_month(999)  # NO debe pisar el seed ya aplicado este mes
    assert rate_budget.status()["requests_este_mes"] == 12


# ---------------------------------------------------------------------------
# 4) Mapeo de liga fail-closed
# ---------------------------------------------------------------------------

_CATALOGO_SINTETICO = [
    {"id": 17, "name": "Premier League", "category": "England"},
    {"id": 8, "name": "LaLiga", "category": "Spain"},
    {"id": 999, "name": "Copa Regional Amateur", "category": "Testland"},
    {"id": 1000, "name": "Copa Regional Amateur", "category": "Otroland"},  # nombre ambiguo a proposito, NO es un override real
    # Hallazgo real 2026-08-16 (regresion): "Serie C" (Italia) NO debe
    # resolver para la liga de ATLAS "Brasileirão Série C" (Brasil) solo
    # porque comparte 2 de 3 tokens -- antes de este fix, si resolvia.
    {"id": 2000, "name": "Serie C", "category": "Italy"},
    {"id": 2001, "name": "Brasileiro Serie C", "category": "Brazil"},
    # Hallazgo real 2026-08-16 (regresion): "Championship" NO debe resolver
    # para "UEFA Champions League" solo porque "champions"/"championship"
    # comparten prefijo.
    {"id": 3000, "name": "Championship", "category": "England"},
    {"id": 3001, "name": "UEFA Champions League", "category": "International Clubs"},
    # Hallazgo real 2026-08-16: alias de pais necesario (South Korea ATLAS
    # vs Republic of Korea OddsPapi) para resolver via Tier 2.
    {"id": 4000, "name": "K-League 1", "category": "Republic of Korea"},
    {"id": 4001, "name": "League 1", "category": "Scotland"},
]


def test_liga_conocida_resuelve_tournament_id(tmp_path, monkeypatch):
    monkeypatch.setattr(league_mapping, "CATALOG_PATH", tmp_path / "catalog_test.json")
    league_mapping._save_catalog(_CATALOGO_SINTETICO)
    res = league_mapping.resolve_tournament_id("Premier League")
    assert res["estado"] == league_mapping.LIGA_RESUELTA
    assert res["tournament_id"] == 17


def test_liga_desconocida_nunca_adivina(tmp_path, monkeypatch):
    monkeypatch.setattr(league_mapping, "CATALOG_PATH", tmp_path / "catalog_test.json")
    league_mapping._save_catalog(_CATALOGO_SINTETICO)
    res = league_mapping.resolve_tournament_id("Liga Completamente Inventada XYZ")
    assert res["estado"] == league_mapping.LIGA_NO_MAPEADA
    assert res["tournament_id"] is None


def test_liga_ambigua_sin_country_hint_nunca_elige_arbitrariamente(tmp_path, monkeypatch):
    monkeypatch.setattr(league_mapping, "CATALOG_PATH", tmp_path / "catalog_test.json")
    league_mapping._save_catalog(_CATALOGO_SINTETICO)
    res = league_mapping.resolve_tournament_id("Copa Regional Amateur")  # sin country_hint
    assert res["estado"] == league_mapping.LIGA_AMBIGUA
    assert res["tournament_id"] is None
    assert len(res["candidatos"]) == 2


def test_liga_ambigua_se_resuelve_con_country_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(league_mapping, "CATALOG_PATH", tmp_path / "catalog_test.json")
    league_mapping._save_catalog(_CATALOGO_SINTETICO)
    res = league_mapping.resolve_tournament_id("Copa Regional Amateur", country_hint="Otroland")
    assert res["estado"] == league_mapping.LIGA_RESUELTA
    assert res["tournament_id"] == 1000


def test_league_name_override_traduce_sinonimo_verificado(tmp_path, monkeypatch):
    """'Liga de Ascenso' (ATLAS, Chile) es un override real de produccion ->
    'Primera B' (nombre real en OddsPapi) -- verifica que el override se
    aplique de punta a punta, no solo que la tecnica de matching funcione."""
    monkeypatch.setattr(league_mapping, "CATALOG_PATH", tmp_path / "catalog_test.json")
    league_mapping._save_catalog([{"id": 1240, "name": "Primera B", "category": "Chile"}])
    res = league_mapping.resolve_tournament_id("Liga de Ascenso", country_hint="Chile")
    assert res["estado"] == league_mapping.LIGA_RESUELTA
    assert res["tournament_id"] == 1240


def test_nunca_resuelve_silenciosamente_contra_otro_pais_por_subset_de_tokens(tmp_path, monkeypatch):
    """Regresion del hallazgo real 2026-08-16: 'Brasileirão Série C' NO debe
    resolver contra 'Serie C' (Italia). Con el alias brasileirao->brasileiro
    aplicado tambien en la coincidencia EXACTA (Nivel 1), esto ahora resuelve
    correctamente incluso SIN country_hint -- lo importante (y lo que este
    test verifica) es que NUNCA elige la Serie C de Italia."""
    monkeypatch.setattr(league_mapping, "CATALOG_PATH", tmp_path / "catalog_test.json")
    league_mapping._save_catalog(_CATALOGO_SINTETICO)
    res = league_mapping.resolve_tournament_id("Brasileirão Série C")  # sin country_hint
    assert res["tournament_id"] != 2000  # NUNCA la Serie C de Italia
    assert res["estado"] == league_mapping.LIGA_RESUELTA
    assert res["tournament_id"] == 2001  # Brasileiro Serie C, via Nivel 1 (exacto + alias)


def test_brasileirao_serie_c_resuelve_correctamente_con_country_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(league_mapping, "CATALOG_PATH", tmp_path / "catalog_test.json")
    league_mapping._save_catalog(_CATALOGO_SINTETICO)
    res = league_mapping.resolve_tournament_id("Brasileirão Série C", country_hint="Brazil")
    assert res["estado"] == league_mapping.LIGA_RESUELTA
    assert res["tournament_id"] == 2001  # Brasileiro Serie C, NUNCA la de Italia


def test_champions_league_no_colisiona_con_championship(tmp_path, monkeypatch):
    """Regresion del hallazgo real 2026-08-16: 'champions' es prefijo de
    'championship' -- la tecnica de subconjunto+prefijo los confundia."""
    monkeypatch.setattr(league_mapping, "CATALOG_PATH", tmp_path / "catalog_test.json")
    league_mapping._save_catalog(_CATALOGO_SINTETICO)
    res = league_mapping.resolve_tournament_id("UEFA Champions League")
    assert res["estado"] == league_mapping.LIGA_RESUELTA
    assert res["tournament_id"] == 3001  # NUNCA 3000 (Championship)


def test_alias_de_pais_resuelve_k_league(tmp_path, monkeypatch):
    """South Korea (ATLAS) == Republic of Korea (OddsPapi) via COUNTRY_ALIASES."""
    monkeypatch.setattr(league_mapping, "CATALOG_PATH", tmp_path / "catalog_test.json")
    league_mapping._save_catalog(_CATALOGO_SINTETICO)
    res = league_mapping.resolve_tournament_id("K League 1", country_hint="South Korea")
    assert res["estado"] == league_mapping.LIGA_RESUELTA
    assert res["tournament_id"] == 4000  # NUNCA 4001 (League 1 de Escocia)


# ---------------------------------------------------------------------------
# 5) Matching de fixture: sofascoreId directo + fallback por nombre
# ---------------------------------------------------------------------------

def test_match_por_sofascore_id_directo():
    fixtures = [
        {"externalProviders": {"sofascoreId": 111111}, "participant1Name": "Equipo A", "participant2Name": "Equipo B"},
        {"externalProviders": {"sofascoreId": 222222}, "participant1Name": "Equipo C", "participant2Name": "Equipo D"},
    ]
    res = matching.match_fixture(222222, "Equipo C", "Equipo D", fixtures)
    assert res["estado"] == matching.MATCH_UNICO_POR_ID
    assert res["fixture"]["externalProviders"]["sofascoreId"] == 222222


def test_match_sin_sofascore_id_cae_a_nombre():
    fixtures = [
        {"externalProviders": {"sofascoreId": None}, "participant1Name": "Real Madrid", "participant2Name": "Barcelona"},
    ]
    res = matching.match_fixture(999999, "Real Madrid", "Barcelona", fixtures)
    assert res["estado"] == matching.MATCH_UNICO_POR_NOMBRE


def test_no_match_ambiguo_nunca_elige_arbitrariamente():
    fixtures = [
        {"externalProviders": {}, "participant1Name": "Sporting", "participant2Name": "Braga"},
        {"externalProviders": {}, "participant1Name": "Sporting", "participant2Name": "Braga"},
    ]
    res = matching.match_fixture(1, "Sporting", "Braga", fixtures)
    assert res["estado"] == matching.NO_MATCH_AMBIGUO
    assert res["fixture"] is None


def test_no_match_sin_candidatos():
    res = matching.match_fixture(1, "Equipo X", "Equipo Y", [])
    assert res["estado"] == matching.NO_MATCH


# ---------------------------------------------------------------------------
# 6) Extraccion de linea exacta: nunca sustituye por otra linea
# ---------------------------------------------------------------------------

def _fixture_markets_sinteticos():
    return {
        "101": {"outcomes": {"101": {"players": {"0": {"bookmakerOutcomeId": "home", "price": 1.80, "changedAt": "2026-08-16T10:00:00Z"}}},
                              "102": {"players": {"0": {"bookmakerOutcomeId": "draw", "price": 3.50, "changedAt": "2026-08-16T10:00:00Z"}}},
                              "103": {"players": {"0": {"bookmakerOutcomeId": "away", "price": 4.20, "changedAt": "2026-08-16T10:00:00Z"}}}}},
        "104": {"outcomes": {"104": {"players": {"0": {"bookmakerOutcomeId": "yes", "price": 1.90, "changedAt": "2026-08-16T10:00:00Z"}}},
                              "105": {"players": {"0": {"bookmakerOutcomeId": "no", "price": 1.85, "changedAt": "2026-08-16T10:00:00Z"}}}}},
        "1010": {"outcomes": {"1010": {"players": {"0": {"bookmakerOutcomeId": "over", "price": 1.95, "changedAt": "2026-08-16T10:00:00Z"}}},
                               "1011": {"players": {"0": {"bookmakerOutcomeId": "under", "price": 1.87, "changedAt": "2026-08-16T10:00:00Z"}}}}},
    }


def test_extract_1x2_devuelve_precio_correcto():
    res = line_extraction.extract_1x2(_fixture_markets_sinteticos())
    assert res["resultado"] == line_extraction.RESULTADO_RESUELTO
    assert res["selecciones"]["home"]["price"] == 1.80


def test_extract_btts_devuelve_precio_correcto():
    res = line_extraction.extract_btts(_fixture_markets_sinteticos())
    assert res["resultado"] == line_extraction.RESULTADO_RESUELTO
    assert res["selecciones"]["yes"]["price"] == 1.90


def test_extract_over_under_25_devuelve_precio_correcto():
    res = line_extraction.extract_over_under_25(_fixture_markets_sinteticos())
    assert res["resultado"] == line_extraction.RESULTADO_RESUELTO
    assert res["selecciones"]["over"]["price"] == 1.95


def test_extract_1x2_mercado_ausente():
    res = line_extraction.extract_1x2({})
    assert res["resultado"] == line_extraction.RESULTADO_MARKET_UNAVAILABLE


def test_asian_handicap_linea_exacta_disponible(tmp_path, monkeypatch):
    monkeypatch.setattr(line_extraction, "MARKETS_CATALOG_PATH", tmp_path / "markets_test.json")
    line_extraction._save_catalog([
        {"marketId": 1070, "marketName": "Asian Handicap", "marketType": "spreads", "handicap": -0.25, "period": "fulltime", "sportId": 10},
        {"marketId": 1074, "marketName": "Asian Handicap", "marketType": "spreads", "handicap": 0.25, "period": "fulltime", "sportId": 10},
    ])
    fixture_markets = {
        "1070": {"outcomes": {"1": {"players": {"0": {"bookmakerOutcomeId": "-0.25/home", "price": 1.90, "changedAt": "t"}}}}},
        "1074": {"outcomes": {"1": {"players": {"0": {"bookmakerOutcomeId": "0.25/away", "price": 1.95, "changedAt": "t"}}}}},
    }
    res = line_extraction.extract_asian_handicap(fixture_markets, home_line=-0.25, away_line=0.25)
    assert res["selecciones"]["home"]["price"] == 1.90
    assert res["selecciones"]["away"]["price"] == 1.95


def test_asian_handicap_linea_no_disponible_nunca_sustituye(tmp_path, monkeypatch):
    monkeypatch.setattr(line_extraction, "MARKETS_CATALOG_PATH", tmp_path / "markets_test.json")
    # catalogo SOLO tiene -0.25, NO tiene -0.10 -- no debe usar -0.25 como aproximacion
    line_extraction._save_catalog([
        {"marketId": 1070, "marketName": "Asian Handicap", "marketType": "spreads", "handicap": -0.25, "period": "fulltime", "sportId": 10},
    ])
    fixture_markets = {
        "1070": {"outcomes": {"1": {"players": {"0": {"bookmakerOutcomeId": "-0.25/home", "price": 1.90, "changedAt": "t"}}}}},
    }
    res = line_extraction.extract_asian_handicap(fixture_markets, home_line=-0.10, away_line=0.10)
    assert "home" not in res["selecciones"]
    assert "away" not in res["selecciones"]
    assert res["resultado"] == line_extraction.RESULTADO_LINE_UNAVAILABLE


# ---------------------------------------------------------------------------
# 7) Bookmaker primario bloqueado por decision explicita del Director
# ---------------------------------------------------------------------------

def test_bookmaker_primario_es_pinnacle():
    assert capture.BOOKMAKER_PRIMARIO_ODDSPAPI == "Pinnacle"
    assert capture.BOOKMAKER_API_SLUG == "pinnacle"


# ---------------------------------------------------------------------------
# 8) Aislamiento total del sistema LIVE
# ---------------------------------------------------------------------------

def test_sin_imports_hacia_el_sistema_live():
    """Verifica sentencias import reales (no menciones en comentarios/
    docstrings, ej. la referencia documental a odds_api_io_client.py como
    patron de disenio en client.py -- eso es texto explicativo, no un
    import)."""
    import ast
    prohibidos = [
        "odds_api_io_client", "odds_api_io_matching", "odds_api_io_rate_budget", "odds_api_io_capture",
        "run_live_strategies", "captura_automatica_cuotas_listener", "liquidacion_automatica_cuotas",
        "atlas_engine.notify", "inplay_ip001_capture", "signal_platform_capture",
    ]
    for modulo in (client, rate_budget, league_mapping, matching, line_extraction, capture):
        fuente = inspect.getsource(modulo)
        tree = ast.parse(fuente)
        importados = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                importados.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                importados.add(node.module)
                importados.update(f"{node.module}.{alias.name}" for alias in node.names)
        for nombre in prohibidos:
            assert not any(nombre in imp for imp in importados), \
                f"{modulo.__name__} IMPORTA algo relacionado con '{nombre}' (violacion de aislamiento): {importados}"


def test_capture_nunca_escribe_en_archivos_del_sistema_live():
    fuente = inspect.getsource(capture)
    prohibidos_paths = [
        "live_alerts_evidence.json", "live_alerts_evidence_automatica.json",
        "live_alerts_evidence_odds_api_io.json", "live_alerts_liquidacion.json",
        "odds_api_io_estado.json", "live_alerts_history.jsonl",
    ]
    for nombre in prohibidos_paths:
        assert nombre not in fuente


# ---------------------------------------------------------------------------
# 9) capture.run() nunca lanza excepcion no controlada (entrada vacia/faltante)
# ---------------------------------------------------------------------------

def test_run_sin_archivos_de_entrada_no_lanza_excepcion(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "_WORK", tmp_path)
    monkeypatch.setattr(capture, "EVIDENCIA_PATH", tmp_path / "oddspapi_evidence.json")
    monkeypatch.setattr(capture, "ESTADO_PATH", tmp_path / "oddspapi_estado.json")
    monkeypatch.setattr(capture, "HISTORY_PATH", tmp_path / "oddspapi_history.jsonl")
    monkeypatch.setattr(capture, "RAW_CACHE_PATH", tmp_path / "oddspapi_raw_cache.json")
    monkeypatch.setattr(capture, "LEAN_OUTPUT_PATH", tmp_path / "oddspapi_lean.json")
    monkeypatch.setattr(rate_budget, "STATE_PATH", tmp_path / "rate_budget_test.json")
    monkeypatch.setattr(client, "get_account", lambda: {"status": None, "data": None, "latency_ms": 0, "error": "sin key en test"})

    resumen = capture.run()
    assert isinstance(resumen, dict)
    assert (tmp_path / "oddspapi_lean.json").exists()
