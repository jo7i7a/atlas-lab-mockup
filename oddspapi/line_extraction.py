# -*- coding: utf-8 -*-
"""Extraccion de mercado+linea+cuota EXACTA de un fixture de OddsPapi --
exclusivo de ATLAS LAB (Edificio 5). NUNCA sustituye una linea por otra: si
la linea exacta que ATLAS calculo no esta publicada, el resultado es
LINE_UNAVAILABLE, nunca se aproxima con una linea vecina.

Building:     ATLAS_LAB_MOCKUP (Edificio 5) / Laboratorio de Estrategias
Type:         Implementation
Status:       Produccion

marketId de 1X2/BTTS/Over-Under 2.5 son CONSTANTES GLOBALES confirmadas en
vivo contra GET /v4/markets real (2026-08-16): 101="Full Time Result"
(marketType=1x2, period=fulltime), 104="Both Teams To Score"
(marketType=bothteamsscore, period=fulltime), 1010="Over Under Full Time"
handicap=2.5 (marketType=totals, period=fulltime) -- estos NUNCA varian
porque 1X2/BTTS no tienen linea y el Over/Under de goles de ATLAS SIEMPRE es
2.5 fijo (ver MARKET_DEFS.OU25_GOALS_FT.line en index.html). Se validan
igual contra el catalogo cacheado antes de usarse (defensivo, por si
OddsPapi renumerara su catalogo).

Asian Handicap SI varia por partido (line viene de
POCKET_DATA[matchId].HANDICAP_FT.hl/al, ver atlas_pocket/engines/
handicap_adapter.py::market_context) -- se resuelve dinamicamente contra el
catalogo cacheado de mercados: marketName="Asian Handicap",
marketType="spreads", period="fulltime", handicap==linea exacta (epsilon
0.001). Confirmado real (2026-08-16): dentro de UN marketId de Asian
Handicap, cada outcome trae bookmakerOutcomeId="{linea}/home" o
"{linea}/away" -- se busca el outcome cuyo sufijo coincide con el lado
pedido.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
_MOCKUP = _ROOT / "atlas_lab_mockup"
MARKETS_CATALOG_PATH = _MOCKUP / "oddspapi_markets_catalog_estado.json"

MARKETS_CATALOG_TTL_DAYS = 30  # el catalogo de definiciones de mercado cambia con muy poca frecuencia

MARKET_ID_1X2 = 101
MARKET_ID_BTTS = 104
MARKET_ID_OU25_GOALS_FT = 1010
_EPS = 0.001

RESULTADO_RESUELTO = "ODDSPAPI_ODDS_RESOLVED"
RESULTADO_LINE_UNAVAILABLE = "LINE_UNAVAILABLE"
RESULTADO_MARKET_UNAVAILABLE = "MARKET_UNAVAILABLE"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_catalog() -> dict | None:
    if not MARKETS_CATALOG_PATH.exists():
        return None
    try:
        return json.loads(MARKETS_CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_catalog(markets: list[dict]) -> None:
    MARKETS_CATALOG_PATH.write_text(
        json.dumps({"fetched_at_utc": _now().strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                    "markets": markets}, indent=1, ensure_ascii=False),
        encoding="utf-8",
    )


def refresh_markets_catalog(force: bool = False, rate_budget=None, client_module=None) -> dict:
    """Refresca el catalogo completo de definiciones de mercado (todos los
    deportes) si el cacheado tiene mas de MARKETS_CATALOG_TTL_DAYS o
    force=True. Consume 1 request SOLO cuando efectivamente refresca."""
    cached = _load_catalog()
    if not force and cached:
        try:
            fetched_at = datetime.strptime(cached["fetched_at_utc"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
            if _now() - fetched_at < timedelta(days=MARKETS_CATALOG_TTL_DAYS):
                return {"refrescado": False, "n_mercados": len(cached.get("markets", [])), "error": None}
        except Exception:
            pass

    if rate_budget is not None and not rate_budget.can_call():
        if cached:
            return {"refrescado": False, "n_mercados": len(cached.get("markets", [])),
                     "error": "MONTHLY_RATE_LIMIT_PROTECTED -- se reutiliza catalogo cacheado existente"}
        return {"refrescado": False, "n_mercados": 0, "error": "MONTHLY_RATE_LIMIT_PROTECTED -- sin catalogo previo"}

    if client_module is None:
        from atlas_lab_mockup.oddspapi import client as client_module
    resp = client_module.get_markets()
    # Solo se registra consumo si REALMENTE se intento la red -- ver nota
    # equivalente en league_mapping.py::refresh_tournament_catalog.
    if rate_budget is not None and resp.get("attempted"):
        rate_budget.record_call()
    if resp["status"] != 200 or not resp["markets"]:
        if cached:
            return {"refrescado": False, "n_mercados": len(cached.get("markets", [])),
                     "error": f"PROVIDER_ERROR (status={resp['status']}) -- se reutiliza catalogo cacheado existente"}
        return {"refrescado": False, "n_mercados": 0, "error": f"PROVIDER_ERROR (status={resp['status']})"}

    markets = [
        {"marketId": m.get("marketId"), "marketName": m.get("marketName"),
         "marketType": m.get("marketType"), "handicap": m.get("handicap"),
         "period": m.get("period"), "sportId": m.get("sportId")}
        for m in resp["markets"]
    ]
    _save_catalog(markets)
    return {"refrescado": True, "n_mercados": len(markets), "error": None}


def _outcome_price(fixture_markets: dict, market_id: int, outcome_suffix: str | None = None) -> dict | None:
    """Busca el marketId dado dentro de markets{} de un bookmaker de un
    fixture. Si outcome_suffix se indica (ej. 'home'), retorna la primera
    outcome cuyo bookmakerOutcomeId TERMINA en '/<suffix>'; si no, retorna
    (price, outcome_name) segun el orden real de outcomes del payload.

    2026-08-16, auditoria EV extremo en Picks ATLAS: ademas de price/
    changed_at, se propaga `active` (por outcome) y `market_active`
    (block["marketActive"]) -- campos reales que el payload de OddsPapi YA
    trae y que antes se descartaban. Un precio con active=False sigue
    devolviendose aqui (esta funcion solo EXTRAE, nunca decide "valido o
    no" -- esa decision es de tipster/picks.py y tipster/rankings.py, ver
    su docstring) -- campo ausente en el payload => None, nunca False."""
    block = fixture_markets.get(str(market_id)) or fixture_markets.get(market_id)
    if not block:
        return None
    market_active = block.get("marketActive")
    outcomes = block.get("outcomes") or {}
    for outcome_id, outcome_data in outcomes.items():
        players = outcome_data.get("players") or {}
        p0 = players.get("0")
        if not p0:
            continue
        bmk_outcome_id = str(p0.get("bookmakerOutcomeId") or "")
        if outcome_suffix is not None and not bmk_outcome_id.endswith(f"/{outcome_suffix}"):
            continue
        return {
            "outcome_id": outcome_id, "bookmaker_outcome_id": bmk_outcome_id,
            "price": p0.get("price"), "changed_at": p0.get("changedAt"),
            "active": p0.get("active"), "market_active": market_active,
        }
    return None


def extract_1x2(bookmaker_markets: dict) -> dict:
    """1X2 -- marketId fijo, 3 selecciones (home/draw/away, outcomeId 101/102/103)."""
    block = bookmaker_markets.get(str(MARKET_ID_1X2))
    if not block:
        return {"resultado": RESULTADO_MARKET_UNAVAILABLE, "selecciones": {}}
    market_active = block.get("marketActive")
    selecciones = {}
    outcomes = block.get("outcomes") or {}
    for outcome_id, outcome_data in outcomes.items():
        p0 = (outcome_data.get("players") or {}).get("0")
        if not p0:
            continue
        bmk = str(p0.get("bookmakerOutcomeId") or "")
        if bmk in ("home", "draw", "away"):
            selecciones[bmk] = {"price": p0.get("price"), "changed_at": p0.get("changedAt"),
                                 "active": p0.get("active"), "market_active": market_active}
    if not selecciones:
        return {"resultado": RESULTADO_MARKET_UNAVAILABLE, "selecciones": {}}
    return {"resultado": RESULTADO_RESUELTO, "selecciones": selecciones}


def extract_btts(bookmaker_markets: dict) -> dict:
    """BTTS -- marketId fijo, 2 selecciones (Yes/No)."""
    block = bookmaker_markets.get(str(MARKET_ID_BTTS))
    if not block:
        return {"resultado": RESULTADO_MARKET_UNAVAILABLE, "selecciones": {}}
    market_active = block.get("marketActive")
    selecciones = {}
    outcomes = block.get("outcomes") or {}
    ids = sorted(outcomes.keys(), key=lambda k: int(k))
    labels = ["yes", "no"]
    for label, outcome_id in zip(labels, ids):
        p0 = (outcomes[outcome_id].get("players") or {}).get("0")
        if p0:
            selecciones[label] = {"price": p0.get("price"), "changed_at": p0.get("changedAt"),
                                   "active": p0.get("active"), "market_active": market_active}
    if not selecciones:
        return {"resultado": RESULTADO_MARKET_UNAVAILABLE, "selecciones": {}}
    return {"resultado": RESULTADO_RESUELTO, "selecciones": selecciones}


def extract_over_under_25(bookmaker_markets: dict) -> dict:
    """Over/Under 2.5 goles -- marketId fijo (linea siempre 2.5 en ATLAS)."""
    block = bookmaker_markets.get(str(MARKET_ID_OU25_GOALS_FT))
    if not block:
        return {"resultado": RESULTADO_MARKET_UNAVAILABLE, "selecciones": {}}
    market_active = block.get("marketActive")
    selecciones = {}
    outcomes = block.get("outcomes") or {}
    for outcome_data in outcomes.values():
        p0 = (outcome_data.get("players") or {}).get("0")
        if not p0:
            continue
        name = str(p0.get("bookmakerOutcomeId") or "").lower()
        if "over" in name:
            selecciones["over"] = {"price": p0.get("price"), "changed_at": p0.get("changedAt"),
                                    "active": p0.get("active"), "market_active": market_active}
        elif "under" in name:
            selecciones["under"] = {"price": p0.get("price"), "changed_at": p0.get("changedAt"),
                                     "active": p0.get("active"), "market_active": market_active}
    if not selecciones:
        return {"resultado": RESULTADO_MARKET_UNAVAILABLE, "selecciones": {}}
    return {"resultado": RESULTADO_RESUELTO, "selecciones": selecciones}


def _find_handicap_market_id(line: float) -> int | None:
    cached = _load_catalog()
    if not cached:
        return None
    for m in cached.get("markets", []):
        if (m.get("sportId") == 10 and m.get("marketType") == "spreads"
                and m.get("marketName") == "Asian Handicap" and m.get("period") == "fulltime"
                and m.get("handicap") is not None and abs(m["handicap"] - line) < _EPS):
            return m.get("marketId")
    return None


def extract_asian_handicap(bookmaker_markets: dict, home_line: float, away_line: float) -> dict:
    """Asian Handicap -- linea EXACTA por lado (home_line/away_line vienen de
    POCKET_DATA[matchId].HANDICAP_FT, calculados por ATLAS). Cada lado se
    resuelve de forma INDEPENDIENTE: puede que home tenga cuota disponible y
    away no, o viceversa -- nunca se sustituye una linea por otra ni se
    inventa el lado faltante."""
    resultado = {"resultado": RESULTADO_RESUELTO, "selecciones": {}, "detalle": {}}
    tuvo_alguna = False

    for lado, line in (("home", home_line), ("away", away_line)):
        market_id = _find_handicap_market_id(line)
        if market_id is None:
            resultado["detalle"][lado] = {"resultado": RESULTADO_LINE_UNAVAILABLE,
                                           "motivo": f"linea {line} no encontrada en catalogo de Asian Handicap FT"}
            continue
        found = _outcome_price(bookmaker_markets, market_id, lado)
        if found is None:
            resultado["detalle"][lado] = {"resultado": RESULTADO_LINE_UNAVAILABLE,
                                           "motivo": f"marketId={market_id} (linea {line}) no publicado para este fixture/bookmaker"}
            continue
        resultado["selecciones"][lado] = {"price": found["price"], "changed_at": found["changed_at"], "line": line,
                                           "active": found["active"], "market_active": found["market_active"]}
        resultado["detalle"][lado] = {"resultado": RESULTADO_RESUELTO}
        tuvo_alguna = True

    if not tuvo_alguna:
        resultado["resultado"] = RESULTADO_LINE_UNAVAILABLE
    return resultado
