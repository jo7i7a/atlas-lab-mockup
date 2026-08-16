# -*- coding: utf-8 -*-
"""Control local de presupuesto MENSUAL de requests para OddsPapi FREE --
exclusivo de ATLAS LAB (Edificio 5). Ventana de MES CALENDARIO (no hora/dia
como el patron hermano de Odds-API.io, ver
atlas_engine/data/odds_api_io_rate_budget.py) porque el limite real de
OddsPapi FREE es 250 requests/MES.

Building:     ATLAS_LAB_MOCKUP (Edificio 5) / Laboratorio de Estrategias
Type:         Implementation
Status:       Produccion

Free Plan real: 250 req/mes. Este modulo se autolimita al 80% (200/250) --
NUNCA espera a que la API devuelva un error real; el margen de seguridad es
deliberado.

Archivo de estado propio, aislado, nunca compartido con ningun otro
componente de ATLAS (ni con odds_api_io_rate_budget_estado.json, que es de
la integracion LIVE hermana y tiene ventana hora/dia, no mes).

SEMBRADO (decision del Director, 2026-08-16): antes de la primera corrida
real, se consulto GET /v4/account (no metered) para obtener el request_count
real del mes ya gastado durante la validacion manual de esta sesion -- el
contador local NUNCA debe arrancar en 0 si ya hubo consumo real fuera de este
modulo. Ver seed_current_month().
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
_MOCKUP = _ROOT / "atlas_lab_mockup"
STATE_PATH = _MOCKUP / "oddspapi_rate_budget_estado.json"

MONTHLY_LIMIT_REAL = 250
MONTHLY_SAFETY_MARGIN = 0.80  # se detiene a 200/250
MONTHLY_CAP = int(MONTHLY_LIMIT_REAL * MONTHLY_SAFETY_MARGIN)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _current_month_key(now: datetime | None = None) -> str:
    return (now or _now()).strftime("%Y-%m")


def _load() -> dict:
    if not STATE_PATH.exists():
        return {"call_timestamps_utc": [], "seed": None}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        data.setdefault("call_timestamps_utc", [])
        data.setdefault("seed", None)
        return data
    except Exception:
        return {"call_timestamps_utc": [], "seed": None}


def _save(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")


def _parse_ts(ts: str) -> datetime:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _prune(timestamps: list[str], now: datetime) -> list[str]:
    """Conserva las marcas de los ultimos ~40 dias -- suficiente para cubrir
    cualquier mes calendario en curso sin crecer sin limite."""
    cutoff = now - timedelta(days=40)
    kept = []
    for ts in timestamps:
        try:
            if _parse_ts(ts) >= cutoff:
                kept.append(ts)
        except Exception:
            continue
    return kept


def seed_current_month(count: int) -> None:
    """Precarga el contador del mes calendario actual con `count` requests ya
    gastados por fuera de este modulo (ej. validacion manual con curl/
    PowerShell). Idempotente por mes: si ya existe un seed para el mes actual,
    NO lo pisa (para no perder llamadas ya registradas via record_call() en
    el intervalo) -- solo siembra si el mes cambio o nunca hubo seed."""
    now = _now()
    state = _load()
    month_key = _current_month_key(now)
    existing = state.get("seed")
    if existing and existing.get("month") == month_key:
        return  # ya sembrado este mes, no se pisa
    state["seed"] = {"month": month_key, "count": count, "seeded_at_utc": now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")}
    _save(state)


def status() -> dict:
    """Retorna el consumo actual del mes calendario sin registrar ninguna
    llamada nueva."""
    now = _now()
    state = _load()
    timestamps = _prune(state.get("call_timestamps_utc", []), now)
    month_key = _current_month_key(now)

    n_month = 0
    for ts in timestamps:
        try:
            if _parse_ts(ts).strftime("%Y-%m") == month_key:
                n_month += 1
        except Exception:
            continue

    seed = state.get("seed")
    seed_count = seed["count"] if seed and seed.get("month") == month_key else 0
    n_month += seed_count

    return {
        "requests_este_mes": n_month, "cap_mes_80pct": MONTHLY_CAP, "limite_real_mes": MONTHLY_LIMIT_REAL,
        "mes": month_key, "seed_aplicado": seed_count,
        "puede_llamar": n_month < MONTHLY_CAP,
    }


def can_call() -> bool:
    return status()["puede_llamar"]


def record_call() -> None:
    """Registra que se hizo 1 llamada real a la API, en el momento exacto de
    la llamada -- se invoca inmediatamente despues de cada request real,
    nunca de forma anticipada."""
    now = _now()
    state = _load()
    timestamps = _prune(state.get("call_timestamps_utc", []), now)
    timestamps.append(now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
    state["call_timestamps_utc"] = timestamps
    _save(state)
