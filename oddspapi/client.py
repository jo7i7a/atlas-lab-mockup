# -*- coding: utf-8 -*-
"""Cliente de solo lectura para OddsPapi FREE -- fuente de cuotas pre-partido
para ATLAS LAB (Edificio 5), exclusivamente. NO relacionado con Odds-API.io
(fuente de cuotas del sistema LIVE) ni con ninguna estrategia LIVE.

Building:     ATLAS_LAB_MOCKUP (Edificio 5) / Laboratorio de Estrategias
Type:         Implementation
Status:       Produccion (uso interno pre-partido, plan FREE 250 req/mes)
Dependencies: curl_cffi (ya usado en todo el proyecto, ver
              atlas_engine/data/odds_api_io_client.py)

AISLAMIENTO TOTAL: este modulo no importa nada de las 12 estrategias,
run_live_strategies.py, captura_automatica_cuotas_listener.py,
liquidacion_captura_automatica.py, notify/, IP001, signal_platform_capture.py
ni atlas_engine/data/odds_api_io_*.py. Unicamente hace peticiones HTTP de
solo lectura a api.oddspapi.io.

La API key SIEMPRE se lee de la variable de entorno ODDSPAPI_API_KEY (nombre
deliberadamente distinto de ODDS_API_KEY, usada por la integracion LIVE
hermana) -- nunca hardcodeada, nunca escrita a disco, nunca incluida en
ningun print/log de este modulo (ver _mask_key).

Mismo patron defensivo que atlas_engine/data/odds_api_io_client.py (Patron de
Unica Fuente de Verdad para el manejo de credenciales en este proyecto): _get()
nunca lanza excepcion no controlada, errores de red/ausencia de key se
retornan como status=None + error para que el orquestador decida.
"""
from __future__ import annotations

import os
import time

from curl_cffi import requests as cffi

BASE = "https://api.oddspapi.io/v4"
_TIMEOUT_S = 30
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}

ENV_VAR_NAME = "ODDSPAPI_API_KEY"

# Espaciado minimo entre llamadas reales (2026-08-16, hallazgo real):
# llamadas consecutivas sin pausa devuelven 429 de forma intermitente
# (confirmado empiricamente -- no documentado explicitamente por OddsPapi).
# _throttle() se aplica DENTRO de _get(), justo antes de cada intento de red
# real, asi que cubre automaticamente cualquier caller (catalogo, odds-by-
# tournaments, account) sin tener que repetir el sleep en cada uno.
_MIN_INTERVAL_S = 1.1
_last_call_ts = 0.0


def _throttle() -> None:
    global _last_call_ts
    elapsed = time.time() - _last_call_ts
    if elapsed < _MIN_INTERVAL_S:
        time.sleep(_MIN_INTERVAL_S - elapsed)
    _last_call_ts = time.time()


class MissingApiKeyError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get(ENV_VAR_NAME)
    if not key:
        raise MissingApiKeyError(
            f"Variable de entorno {ENV_VAR_NAME} no configurada. "
            "La API key nunca se hardcodea -- configurar la variable de entorno "
            "de usuario Windows (setx) antes de ejecutar este modulo."
        )
    return key


def _mask_key(key: str) -> str:
    """Solo para diagnostico -- nunca expone la clave completa."""
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]} (len={len(key)})"


def _redact(msg: str, key: str | None) -> str:
    """Defensa en profundidad: si un mensaje de excepcion de red incluyera la
    URL completa (con apiKey como query param), la clave real nunca debe
    llegar a un archivo de log persistente."""
    if not key or key not in msg:
        return msg
    return msg.replace(key, "***REDACTED***")


def _get(path: str, params: dict | None = None):
    """GET de solo lectura. Retorna (status, data_json_o_None, latency_ms,
    error_o_None, attempted). `attempted` distingue "se intento realmente la
    red" (True, incluso si fallo por timeout/error del proveedor) de "nunca
    se llego a intentar" (False, key ausente) -- CRITICO para que
    rate_budget.record_call() nunca cuente una llamada que jamas salio a la
    red (bug real encontrado 2026-08-16: sin esto, una corrida sin
    ODDSPAPI_API_KEY en el entorno del proceso registraba consumo falso).
    Nunca lanza excepcion no controlada."""
    params = dict(params or {})
    try:
        key = _api_key()
    except MissingApiKeyError as exc:
        return None, None, 0.0, f"{type(exc).__name__}: {exc}", False
    params["apiKey"] = key
    _throttle()
    t0 = time.time()
    try:
        r = cffi.get(f"{BASE}{path}", headers=_HEADERS, params=params,
                     impersonate="chrome131", timeout=_TIMEOUT_S)
        latency_ms = (time.time() - t0) * 1000
        try:
            data = r.json()
        except Exception:
            data = None
        return r.status_code, data, latency_ms, None, True
    except Exception as exc:  # noqa: BLE001 -- nunca debe tumbar el ciclo completo
        latency_ms = (time.time() - t0) * 1000
        return None, None, latency_ms, _redact(f"{type(exc).__name__}: {exc}", key), True


def _as_list(data) -> list:
    """Normaliza la respuesta: algunos endpoints devuelven un array JSON en la
    raiz, otros lo envuelven en {"value": [...]}. Nunca asume una forma fija."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("value"), list):
        return data["value"]
    return []


def get_account() -> dict:
    """GET /account -- NO metered (no consume cuota), confirmado. Util para
    sembrar/verificar el consumo mensual real sin gastar presupuesto."""
    status, data, latency_ms, error, attempted = _get("/account")
    return {"status": status, "data": data if status == 200 else None,
            "latency_ms": latency_ms, "error": error, "attempted": attempted}


def get_tournaments(sport_id: int = 10) -> dict:
    """GET /tournaments?sportId=10 -- catalogo COMPLETO de torneos de un
    deporte en UNA sola llamada (confirmado real: 1762 torneos de futbol en
    una respuesta). Consume 1 request -- llamar con poca frecuencia
    (ver oddspapi/league_mapping.py, cacheado con TTL)."""
    status, data, latency_ms, error, attempted = _get("/tournaments", {"sportId": sport_id})
    return {"status": status, "tournaments": _as_list(data) if status == 200 else [],
            "latency_ms": latency_ms, "error": error, "attempted": attempted}


def get_markets() -> dict:
    """GET /markets -- catalogo COMPLETO de definiciones de mercado (todos los
    deportes) en UNA sola llamada (confirmado real: 32815 definiciones).
    Consume 1 request -- llamar con poca frecuencia (ver
    oddspapi/line_extraction.py, cacheado con TTL)."""
    status, data, latency_ms, error, attempted = _get("/markets")
    return {"status": status, "markets": _as_list(data) if status == 200 else [],
            "latency_ms": latency_ms, "error": error, "attempted": attempted}


def get_odds_by_tournaments(bookmaker: str, tournament_ids: list[int]) -> dict:
    """GET /odds-by-tournaments?bookmaker=X&tournamentIds=1,2,3&verbosity=3 --
    UNA llamada trae TODOS los partidos+cuotas de varios torneos para UN
    bookmaker (confirmado real). La API exige exactamente 1 bookmaker por
    llamada -- no admite "todos". Consume 1 request por llamada,
    independientemente de cuantos tournament_ids se incluyan.

    verbosity=3 es OBLIGATORIO aqui (hallazgo real 2026-08-16): sin este
    parametro, la respuesta NO incluye `externalProviders` (con
    sofascoreId) ni `participant1Name`/`participant2Name` -- exactamente
    los 2 campos que oddspapi/matching.py necesita para emparejar el
    fixture con el partido de ATLAS. Con verbosity=3 SI vienen ambos
    (confirmado con datos reales).

    MAX 5 tournament_ids por llamada (hallazgo real 2026-08-16, ver
    oddspapi/capture.py::TOURNAMENT_BATCH_SIZE): 6+ devuelve 400 de forma
    consistente sin importar cuales IDs se incluyan -- este limite se
    aplica en el orquestador (capture.py), no aqui, para que el cliente
    siga siendo una capa fina sin logica de negocio."""
    if not tournament_ids:
        return {"status": None, "fixtures": [], "latency_ms": 0.0, "error": "tournament_ids vacio", "attempted": False}
    status, data, latency_ms, error, attempted = _get(
        "/odds-by-tournaments",
        {"bookmaker": bookmaker, "tournamentIds": ",".join(str(t) for t in tournament_ids), "verbosity": 3},
    )
    return {"status": status, "fixtures": _as_list(data) if status == 200 else [],
            "latency_ms": latency_ms, "error": error, "attempted": attempted}
