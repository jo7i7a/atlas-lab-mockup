# -*- coding: utf-8 -*-
"""Orquestador de la integracion OddsPapi FREE en ATLAS LAB (Edificio 5) --
fallback automatico de cuotas PRE-PARTIDO para 1X2/Over-Under goles/Asian
Handicap/BTTS. NUNCA reemplaza el motor de probabilidades de ATLAS, NUNCA
bloquea la publicacion diaria del mockup, NUNCA hace polling continuo.

Building:     ATLAS_LAB_MOCKUP (Edificio 5) / Laboratorio de Estrategias
Type:         Implementation
Status:       Produccion

AISLAMIENTO TOTAL (mismo mandato que la integracion LIVE hermana, aplicado
aqui de forma independiente):
  - NUNCA importa nada de las 12 estrategias, run_live_strategies.py,
    captura_automatica_cuotas_listener.py, liquidacion_automatica_cuotas.py,
    notify/, IP001, signal_platform_capture.py ni
    atlas_engine/data/odds_api_io_*.py (esa es otra integracion, de otra
    fuente de cuotas, para el sistema LIVE -- no relacionada).
  - UNICA lectura externa: _work/match_list.json, _work/pocket_engine_results.json,
    _work/leagues_used.json (todos producidos por
    atlas_lab_mockup/pipeline/01_rebuild_upcoming_matches.py, solo lectura).
  - UNICA escritura: sus propios archivos (oddspapi_evidence.json,
    oddspapi_estado.json, oddspapi_history.jsonl, _work/oddspapi_lean.json,
    catalogos cacheados). NUNCA toca localStorage, live_alerts_*,
    odds_api_io_*, ni ningun archivo de la integracion LIVE.
  - Bookmaker UNICO (decision del Director, 2026-08-16): solo Pinnacle en
    esta fase. Arquitectura preparada para agregar un secundario despues
    (ver BOOKMAKER_API_SLUG como unico punto de configuracion), pero no se
    implementa todavia.
  - Linea EXACTA obligatoria (ver oddspapi/line_extraction.py): si la linea
    que ATLAS calculo no esta publicada, el resultado es LINE_UNAVAILABLE,
    nunca se sustituye por otra linea.

Patron de Unica Fuente de Verdad: API publica minima (run), internals
privados (_*).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from atlas_lab_mockup.oddspapi import client  # noqa: E402
from atlas_lab_mockup.oddspapi import rate_budget  # noqa: E402
from atlas_lab_mockup.oddspapi import league_mapping  # noqa: E402
from atlas_lab_mockup.oddspapi import matching  # noqa: E402
from atlas_lab_mockup.oddspapi import line_extraction as lex  # noqa: E402

_MOCKUP_ROOT = _ROOT / "atlas_lab_mockup"
_WORK = _MOCKUP_ROOT / "pipeline" / "_work"

EVIDENCIA_PATH = _MOCKUP_ROOT / "oddspapi_evidence.json"
ESTADO_PATH = _MOCKUP_ROOT / "oddspapi_estado.json"
HISTORY_PATH = _MOCKUP_ROOT / "oddspapi_history.jsonl"
RAW_CACHE_PATH = _WORK / "oddspapi_raw_cache.json"
LEAN_OUTPUT_PATH = _WORK / "oddspapi_lean.json"

# Unico bookmaker en esta fase (decision del Director 2026-08-16). El slug
# de la API es en minuscula ("pinnacle"); el nombre de exhibicion para la
# evidencia/UI usa mayuscula inicial.
BOOKMAKER_API_SLUG = "pinnacle"
BOOKMAKER_PRIMARIO_ODDSPAPI = "Pinnacle"

TOURNAMENT_BATCH_SIZE = 5  # tope REAL confirmado empiricamente 2026-08-16: 5 tournamentIds
# funciona siempre (probado con 5 combinaciones distintas), 6+ devuelve 400
# de forma consistente sin importar cuales IDs se incluyan -- no es un
# limite conservador de diseno, es el limite real del proveedor.

ORIGEN_EVIDENCIA = "ODDSPAPI_FREE_CAPTURA_REAL"

RESULTADO_RESUELTO = "ODDSPAPI_ODDS_RESOLVED"
RESULTADO_LINE_UNAVAILABLE = "LINE_UNAVAILABLE"
RESULTADO_MARKET_UNAVAILABLE = "MARKET_UNAVAILABLE"
RESULTADO_NO_MATCH = matching.NO_MATCH
RESULTADO_NO_MATCH_AMBIGUO = matching.NO_MATCH_AMBIGUO
RESULTADO_LIGA_NO_MAPEADA = league_mapping.LIGA_NO_MAPEADA
RESULTADO_LIGA_AMBIGUA = league_mapping.LIGA_AMBIGUA
RESULTADO_MONTHLY_RATE_LIMIT = "MONTHLY_RATE_LIMIT_PROTECTED"
RESULTADO_PROVIDER_ERROR = "PROVIDER_ERROR"


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def _seed_from_account() -> None:
    """Consulta GET /v4/account (NO metered, no consume cuota) y siembra el
    contador del mes calendario actual -- idempotente (seed_current_month
    solo aplica UNA vez por mes, ver oddspapi/rate_budget.py). Nunca lanza
    excepcion: si la consulta falla, el contador local sigue funcionando con
    lo que ya tenga registrado (mejor un margen ligeramente impreciso que
    bloquear el ciclo)."""
    try:
        resp = client.get_account()
        if resp["status"] == 200 and resp["data"]:
            subs = resp["data"].get("subscriptions") or []
            if subs:
                real_count = subs[0].get("request_count")
                if isinstance(real_count, int):
                    rate_budget.seed_current_month(real_count)
    except Exception:  # noqa: BLE001
        pass


def _load_raw_cache() -> dict | None:
    cache = _load_json(RAW_CACHE_PATH, None)
    if cache and cache.get("date") == _today_key():
        return cache
    return None


def _save_raw_cache(fixtures_by_batch: list[dict]) -> None:
    _WORK.mkdir(parents=True, exist_ok=True)
    _save_json(RAW_CACHE_PATH, {"date": _today_key(), "fetched_at_utc": _now_utc_iso(),
                                 "fixtures_by_batch": fixtures_by_batch})


def _handicap_context(pocket_entry: dict) -> tuple[float, float] | None:
    handicap = (pocket_entry.get("markets") or {}).get("HANDICAP_FT")
    if not handicap or "error" in handicap:
        return None
    ctx = handicap.get("market_context")
    if not ctx or ctx.get("home_line") is None or ctx.get("away_line") is None:
        return None
    return ctx["home_line"], ctx["away_line"]


def run() -> dict:
    """API publica: corre UN ciclo completo (pensado para invocarse UNA vez
    por dia desde 10_fetch_oddspapi_odds.py). Nunca lanza excepcion no
    controlada -- cualquier fallo se registra en las metricas y el ciclo
    termina de forma segura, sin dejar oddspapi_lean.json a medio escribir."""
    metrics = {
        "requests_utilizados": 0, "partidos_evaluados": 0, "partidos_resueltos": 0,
        "ligas_evaluadas": 0, "ligas_mapeadas": 0, "ligas_no_mapeadas": 0, "ligas_ambiguas": 0,
        "no_match": 0, "no_match_ambiguo": 0, "line_unavailable": 0, "market_unavailable": 0,
        "cache_same_day_hit": False, "consumo_mes_antes": None, "consumo_mes_despues": None,
        "error_no_controlado": None,
    }
    metrics["consumo_mes_antes"] = rate_budget.status()["requests_este_mes"]

    try:
        _seed_from_account()

        pocket = _load_json(_WORK / "pocket_engine_results.json", {})
        event_ids = _load_json(_WORK / "match_event_ids.json", {})
        if not pocket or not event_ids:
            metrics["error_no_controlado"] = "pocket_engine_results.json / match_event_ids.json no disponibles -- correr 01 primero"
            _save_json(LEAN_OUTPUT_PATH, {})
            return metrics

        resolved_matches = [
            (mid, entry) for mid, entry in pocket.items()
            if entry.get("resolved") and mid in event_ids
        ]
        metrics["partidos_evaluados"] = len(resolved_matches)

        # liga -> country (real, de tournaments.country via match_event_ids.json)
        # -- necesario para desambiguar nombres de liga cortos/genericos de
        # forma segura (ver oddspapi/league_mapping.py). Un mismo league_name
        # de ATLAS siempre tiene el mismo country, cualquier entrada sirve.
        liga_country: dict[str, str | None] = {}
        for mid, _ in resolved_matches:
            liga_country.setdefault(event_ids[mid]["league"], event_ids[mid].get("country"))
        ligas = sorted(liga_country.keys())
        metrics["ligas_evaluadas"] = len(ligas)

        cat_result = league_mapping.refresh_tournament_catalog(rate_budget=rate_budget)
        if cat_result["error"] and cat_result["error"].startswith("MONTHLY_RATE_LIMIT"):
            metrics["requests_utilizados"] += 0
        elif cat_result["refrescado"]:
            metrics["requests_utilizados"] += 1

        liga_a_tournament: dict[str, int] = {}
        liga_estado: dict[str, dict] = {}
        for liga in ligas:
            res = league_mapping.resolve_tournament_id(liga, country_hint=liga_country.get(liga))
            liga_estado[liga] = res
            if res["estado"] == league_mapping.LIGA_RESUELTA:
                liga_a_tournament[liga] = res["tournament_id"]
                metrics["ligas_mapeadas"] += 1
            elif res["estado"] == league_mapping.LIGA_AMBIGUA:
                metrics["ligas_ambiguas"] += 1
            else:
                metrics["ligas_no_mapeadas"] += 1

        mkt_result = lex.refresh_markets_catalog(rate_budget=rate_budget, client_module=client)
        if mkt_result["refrescado"]:
            metrics["requests_utilizados"] += 1

        tournament_ids = sorted(set(liga_a_tournament.values()))
        estado_out: dict[str, dict] = {}
        evidencia = _load_json(EVIDENCIA_PATH, {})
        lean_out: dict[str, dict] = {}

        raw_cache = _load_raw_cache()
        if raw_cache is not None:
            metrics["cache_same_day_hit"] = True
            fixtures_by_tournament = raw_cache["fixtures_by_batch"]
        else:
            fixtures_by_tournament = {}
            batches = [tournament_ids[i:i + TOURNAMENT_BATCH_SIZE] for i in range(0, len(tournament_ids), TOURNAMENT_BATCH_SIZE)]
            for batch in batches:
                if not rate_budget.can_call():
                    break
                resp = client.get_odds_by_tournaments(BOOKMAKER_API_SLUG, batch)
                # Solo se registra consumo si REALMENTE se intento la red --
                # ver nota equivalente en league_mapping.py::refresh_tournament_catalog.
                if resp.get("attempted"):
                    rate_budget.record_call()
                    metrics["requests_utilizados"] += 1
                if resp["status"] == 200:
                    for fx in resp["fixtures"]:
                        tid = fx.get("tournamentId")
                        fixtures_by_tournament.setdefault(tid, []).append(fx)
            _save_raw_cache(fixtures_by_tournament)

        for mid, entry in resolved_matches:
            info = event_ids[mid]
            liga = info["league"]
            event_id = info["event_id"]
            home_name, away_name = info["home_name"], info["away_name"]

            liga_res = liga_estado[liga]
            if liga_res["estado"] != league_mapping.LIGA_RESUELTA:
                estado_out[mid] = {"estado": liga_res["estado"], "liga": liga,
                                    "motivo": liga_res["motivo"], "ultima_actualizacion_utc": _now_utc_iso()}
                continue

            tid = liga_a_tournament[liga]
            fixtures = fixtures_by_tournament.get(tid) or fixtures_by_tournament.get(str(tid)) or []
            match_result = matching.match_fixture(event_id, home_name, away_name, fixtures)

            if match_result["estado"] not in (matching.MATCH_UNICO_POR_ID, matching.MATCH_UNICO_POR_NOMBRE):
                if match_result["estado"] == matching.NO_MATCH:
                    metrics["no_match"] += 1
                else:
                    metrics["no_match_ambiguo"] += 1
                estado_out[mid] = {"estado": match_result["estado"], "liga": liga,
                                    "motivo": match_result["motivo"], "ultima_actualizacion_utc": _now_utc_iso()}
                continue

            fixture = match_result["fixture"]
            bk_markets = ((fixture.get("bookmakerOdds") or {}).get(BOOKMAKER_API_SLUG) or {}).get("markets") or {}

            resultados_mercado: dict[str, dict] = {}
            registros_evidencia = []

            r_1x2 = lex.extract_1x2(bk_markets)
            r_btts = lex.extract_btts(bk_markets)
            r_ou = lex.extract_over_under_25(bk_markets)
            ah_lines = _handicap_context(entry)
            r_ah = lex.extract_asian_handicap(bk_markets, ah_lines[0], ah_lines[1]) if ah_lines else None

            def _registrar(mkt_code: str, mercado_nombre: str, res: dict, linea=None):
                if res["resultado"] != RESULTADO_RESUELTO and res["resultado"] != lex.RESULTADO_RESUELTO:
                    if res["resultado"] == lex.RESULTADO_LINE_UNAVAILABLE:
                        metrics["line_unavailable"] += 1
                    else:
                        metrics["market_unavailable"] += 1
                    return
                resultados_mercado[mkt_code] = res["selecciones"]
                for seleccion, datos in res["selecciones"].items():
                    registros_evidencia.append({
                        "match_id": mid, "sofascore_event_id": event_id, "league": liga,
                        "home": home_name, "away": away_name,
                        "market_code": mkt_code, "market_name": mercado_nombre,
                        "line": datos.get("line", linea), "selection": seleccion,
                        "bookmaker": BOOKMAKER_PRIMARIO_ODDSPAPI,
                        "price_decimal": datos.get("price"),
                        "changedAt_proveedor": datos.get("changed_at"),
                        "fetched_at_utc": _now_utc_iso(),
                        "matching_status": match_result["estado"],
                        "resultado": RESULTADO_RESUELTO,
                        "origen": ORIGEN_EVIDENCIA,
                    })

            _registrar("1X2_FT", "Full Time Result", r_1x2)
            _registrar("BTTS", "Both Teams To Score", r_btts)
            _registrar("OU25_GOALS_FT", "Over Under Full Time", r_ou, linea=2.5)
            if r_ah:
                _registrar("HANDICAP_FT", "Asian Handicap", r_ah)

            if resultados_mercado:
                metrics["partidos_resueltos"] += 1
                estado_out[mid] = {"estado": RESULTADO_RESUELTO, "liga": liga,
                                    "mercados_resueltos": list(resultados_mercado.keys()),
                                    "ultima_actualizacion_utc": _now_utc_iso()}
                lean_out[mid] = {
                    code: {"bk": BOOKMAKER_PRIMARIO_ODDSPAPI,
                           "sel": {sel: {"p": d.get("price"), "t": d.get("changed_at"), "l": d.get("line")}
                                   for sel, d in sels.items()}}
                    for code, sels in resultados_mercado.items()
                }
                evidencia.setdefault(mid, []).extend(registros_evidencia)
            else:
                estado_out[mid] = {"estado": RESULTADO_MARKET_UNAVAILABLE, "liga": liga,
                                    "motivo": "ningun mercado de los 4 objetivo tuvo cuota poblada para este fixture/bookmaker",
                                    "ultima_actualizacion_utc": _now_utc_iso()}

        _save_json(ESTADO_PATH, estado_out)
        _save_json(EVIDENCIA_PATH, evidencia)
        _save_json(LEAN_OUTPUT_PATH, lean_out)

        with HISTORY_PATH.open("a", encoding="utf-8") as f:
            resumen = {"timestamp_utc": _now_utc_iso(), **{k: v for k, v in metrics.items() if k != "error_no_controlado"}}
            f.write(json.dumps(resumen, ensure_ascii=False) + "\n")

    except Exception as exc:  # noqa: BLE001 -- el ciclo completo nunca debe tumbar el pipeline diario
        metrics["error_no_controlado"] = f"{type(exc).__name__}: {exc}"
        _save_json(LEAN_OUTPUT_PATH, {})

    despues = rate_budget.status()
    metrics["consumo_mes_despues"] = despues["requests_este_mes"]
    metrics["cap_mes_80pct"] = rate_budget.MONTHLY_CAP
    return metrics


if __name__ == "__main__":
    resumen = run()
    print(json.dumps(resumen, indent=1, ensure_ascii=False, default=str))
