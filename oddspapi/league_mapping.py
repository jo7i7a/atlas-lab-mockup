# -*- coding: utf-8 -*-
"""Mapeo DINAMICO liga ATLAS -> tournamentId de OddsPapi -- exclusivo de
ATLAS LAB (Edificio 5). Deliberadamente SIN lista fija hardcodeada de ligas
(a diferencia de LEAGUE_MAP en atlas_engine/data/odds_api_io_matching.py):
el catalogo completo de torneos de OddsPapi se cachea localmente y se
resuelve por nombre normalizado, para funcionar con CUALQUIER liga que
OddsPapi realmente cubra, no solo las que se probaron durante la
investigacion.

Building:     ATLAS_LAB_MOCKUP (Edificio 5) / Laboratorio de Estrategias
Type:         Implementation
Status:       Produccion

Reutiliza normalize() de atlas_engine/data/team_name_reconciliation.py (YA
EXISTENTE, ya validado en produccion) -- Patron de Unica Fuente de Verdad, no
se reinventa la normalizacion de texto. La tecnica de comparacion (subset de
tokens) se reimplementa de forma minima aqui porque resuelve un problema
distinto (matching de NOMBRES DE LIGA entre dos catalogos, no de nombres de
equipo) -- mismo criterio ya documentado en odds_api_io_matching.py.

FAIL-CLOSED (mismo principio que el patron hermano): 0 candidatos o 2+
candidatos ambiguos -> la liga NUNCA se consulta a OddsPapi, sin adivinar.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from atlas_engine.data.team_name_reconciliation import normalize  # noqa: E402
from atlas_lab_mockup.oddspapi import client  # noqa: E402

_MOCKUP = _ROOT / "atlas_lab_mockup"
CATALOG_PATH = _MOCKUP / "oddspapi_tournament_catalog_estado.json"

CATALOG_TTL_DAYS = 7  # los catalogos de torneos cambian con muy poca frecuencia
MIN_PREFIX_LEN = 4

LIGA_NO_MAPEADA = "LIGA_NO_MAPEADA"
LIGA_AMBIGUA = "LIGA_AMBIGUA"
LIGA_RESUELTA = "LIGA_RESUELTA"
LIGA_ERROR_PROVEEDOR = "LIGA_ERROR_PROVEEDOR"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_catalog() -> dict | None:
    if not CATALOG_PATH.exists():
        return None
    try:
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_catalog(tournaments: list[dict]) -> None:
    CATALOG_PATH.write_text(
        json.dumps({"fetched_at_utc": _now().strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                    "tournaments": tournaments}, indent=1, ensure_ascii=False),
        encoding="utf-8",
    )


def refresh_tournament_catalog(force: bool = False, rate_budget=None) -> dict:
    """Refresca el catalogo completo de torneos de futbol (sportId=10) si el
    cacheado tiene mas de CATALOG_TTL_DAYS, o si force=True. Consume 1
    request SOLO cuando efectivamente refresca. Retorna
    {"refrescado": bool, "n_torneos": int, "error": str|None}."""
    cached = _load_catalog()
    if not force and cached:
        try:
            fetched_at = datetime.strptime(cached["fetched_at_utc"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
            if _now() - fetched_at < timedelta(days=CATALOG_TTL_DAYS):
                return {"refrescado": False, "n_torneos": len(cached.get("tournaments", [])), "error": None}
        except Exception:
            pass  # cache corrupto/ilegible -- se refresca igual abajo

    if rate_budget is not None and not rate_budget.can_call():
        # sin cupo -- si hay cache viejo se sigue usando (mejor un catalogo
        # desactualizado que ninguno), nunca se bloquea el pipeline por esto
        if cached:
            return {"refrescado": False, "n_torneos": len(cached.get("tournaments", [])),
                     "error": "MONTHLY_RATE_LIMIT_PROTECTED -- se reutiliza catalogo cacheado existente"}
        return {"refrescado": False, "n_torneos": 0, "error": "MONTHLY_RATE_LIMIT_PROTECTED -- sin catalogo previo"}

    resp = client.get_tournaments(sport_id=10)
    # Solo se registra consumo si REALMENTE se intento la red (bug real
    # encontrado 2026-08-16: sin este chequeo, una corrida sin
    # ODDSPAPI_API_KEY en el entorno del proceso registraba consumo falso
    # sin haber hecho ninguna llamada real).
    if rate_budget is not None and resp.get("attempted"):
        rate_budget.record_call()
    if resp["status"] != 200 or not resp["tournaments"]:
        if cached:
            return {"refrescado": False, "n_torneos": len(cached.get("tournaments", [])),
                     "error": f"PROVIDER_ERROR (status={resp['status']}) -- se reutiliza catalogo cacheado existente"}
        return {"refrescado": False, "n_torneos": 0, "error": f"PROVIDER_ERROR (status={resp['status']})"}

    tournaments = [{"id": t.get("tournamentId"), "name": t.get("tournamentName"),
                     "category": t.get("categoryName")} for t in resp["tournaments"]]
    _save_catalog(tournaments)
    return {"refrescado": True, "n_torneos": len(tournaments), "error": None}


# Alias de nombre de pais (2026-08-16, hallazgo real): ATLAS usa
# tournaments.country de soccer_analytics.db (ej. "South Korea"), OddsPapi
# usa su propio categoryName (ej. "Republic of Korea") -- son el mismo pais
# con nombres distintos en cada fuente. Mismo patron ya usado en
# team_name_reconciliation.py::TOKEN_ALIASES para el mismo tipo de problema
# (variantes de nombre para la misma entidad real), NUNCA usado para
# adivinar una liga, solo para igualar el nombre de un pais conocido.
COUNTRY_ALIASES: dict[str, str] = {
    "south korea": "republic of korea",
}


# Alias de token especifico de LIGA (2026-08-16, hallazgo real): "Brasileirão"
# (ATLAS, forma adjetiva con nasal portuguesa) vs "Brasileiro" (OddsPapi,
# forma generica) son el mismo nombre de competicion -- no es una relacion
# de prefijo (difieren a media palabra: "brasileira[o]" vs "brasileir[o]"),
# por eso _tokens_compatible por si solo no lo resuelve. Mismo patron que
# TOKEN_ALIASES en team_name_reconciliation.py para el mismo tipo de
# problema (variante de nombre de la MISMA entidad real), aplicado aqui a
# nombres de liga -- SOLO usado dentro del Tier 2 (ya filtrado por pais),
# nunca para adivinar entre paises distintos.
_LEAGUE_TOKEN_ALIASES = {"brasileirao": "brasileiro"}

# Calificadores de categoria que NUNCA deben tratarse como variante de
# nombre (2026-08-16, hallazgo real): 'Brasileirão Série B' calzaba como
# subconjunto laxo de 'U20 Brasileiro Serie B' -- son competiciones
# DISTINTAS (categoria sub-20 vs. la liga real), no una variante de texto
# de la misma liga. Si el candidato trae uno de estos tokens y la liga de
# ATLAS no, se descarta sin excepcion dentro de la tecnica laxa.
_EXCLUDE_QUALIFIER_TOKENS = {"u17", "u18", "u19", "u20", "u21", "u23", "women", "reserve", "reserves", "youth"}


def _tokens_compatible(a: str, b: str) -> bool:
    a2, b2 = _LEAGUE_TOKEN_ALIASES.get(a, a), _LEAGUE_TOKEN_ALIASES.get(b, b)
    if a2 == b2:
        return True
    if {a, b} == {"man", "manchester"}:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= MIN_PREFIX_LEN and longer.startswith(shorter)


def _token_set(s: str) -> frozenset:
    tokens = normalize(s).split()
    return frozenset(_LEAGUE_TOKEN_ALIASES.get(t, t) for t in tokens)


# Sinonimos de nombre de liga VERIFICADOS (2026-08-16) contra el catalogo
# real de OddsPapi -- mismo criterio que VERIFIED_ALIASES en
# team_name_reconciliation.py: cada entrada se agrego solo tras confirmar
# el tournamentId real correspondiente, nunca por suposicion. Esto NO es
# una lista de ligas permitidas/restringida -- son traducciones de nombre
# para competiciones que ATLAS y OddsPapi nombran de forma distinta
# (sinonimos reales de la MISMA competicion), el mecanismo de resolucion
# sigue siendo dinamico para cualquier otra liga no listada aqui.
LEAGUE_NAME_OVERRIDE: dict[str, dict] = {
    "Liga de Ascenso": {"name": "Primera B"},  # Chile, segunda division -- confirmado id=1240
    "Liga de Primera": {"name": "Primera Division"},  # Chile -- confirmado id=244 (existe un duplicado exacto id=27665 en el propio catalogo de OddsPapi con la misma categoria; calidad de datos del proveedor, no de este modulo -- queda LIGA_AMBIGUA en ese caso, fail-closed correcto)
    "Brasileirão Betano": {"name": "Brasileiro Serie A", "country": "Brazil"},  # mismo alias ya usado en atlas_engine/data/odds_api_io_matching.py::LEAGUE_MAP
    "J1 League": {"name": "J.League"},  # Japan -- OddsPapi usa "J.League" (con punto), no "J1 League"
    "CONMEBOL Libertadores": {"name": "Copa Libertadores", "country": "International Clubs"},
    "CONMEBOL Sudamericana": {"name": "Copa Sudamericana", "country": "International Clubs"},
}


def _exact_token_set_match(a: str, b: str) -> bool:
    """Coincidencia EXACTA de conjunto de tokens (mismo conjunto, sin
    importar orden) -- deliberadamente estricta, sin prefijos ni
    subconjuntos. Es la unica comparacion segura para hacer GLOBALMENTE
    (contra las 1762 ligas de todos los paises a la vez): la tecnica de
    subconjunto/prefijo usada para nombres de EQUIPO (ver
    odds_api_io_matching.py) produce falsos positivos reales entre paises
    cuando se aplica a nombres de LIGA (hallazgo 2026-08-16: 'Brasileirão
    Série C' resolvia -sin avisar- contra 'Serie C' de Italia; 'UEFA
    Champions League' contra 'Championship' de Inglaterra/Escocia -- ambos
    via el mismo mecanismo de subconjunto+prefijo)."""
    sa, sb = _token_set(a), _token_set(b)
    return bool(sa) and sa == sb


def _loose_name_similarity(a: str, b: str) -> bool:
    """Subconjunto de tokens compatible en cualquier direccion (con
    prefijos) -- la tecnica ORIGINAL, ahora usada SOLO dentro de un conjunto
    de candidatos YA filtrado por pais (ver Tier 2 en resolve_tournament_id),
    donde el riesgo de colision entre paises distintos ya no existe."""
    na, nb = normalize(a).split(), normalize(b).split()
    if not na or not nb:
        return False
    # b (candidato) trae un calificador de categoria que a (ATLAS) no pidio
    # -- competicion DISTINTA, nunca variante de nombre (ver _EXCLUDE_QUALIFIER_TOKENS).
    if (set(nb) & _EXCLUDE_QUALIFIER_TOKENS) - (set(na) & _EXCLUDE_QUALIFIER_TOKENS):
        return False
    a_in_b = all(any(_tokens_compatible(ta, tb) for tb in nb) for ta in na)
    b_in_a = all(any(_tokens_compatible(tb, ta) for ta in na) for tb in nb)
    return a_in_b or b_in_a


def _country_matches(country_hint: str, category: str) -> bool:
    hc, cc = normalize(country_hint), normalize(category)
    if not hc or not cc:
        return False
    hc = COUNTRY_ALIASES.get(hc, hc)
    cc = COUNTRY_ALIASES.get(cc, cc)
    return hc == cc


def resolve_tournament_id(league_name: str, country_hint: str | None = None) -> dict:
    """Resuelve el tournamentId de OddsPapi para una liga de ATLAS, contra el
    catalogo cacheado (llamar refresh_tournament_catalog() antes en el
    orquestador). country_hint viene de tournaments.country (real, ver
    match_event_ids.json) -- es la unica forma segura de desambiguar
    nombres de liga cortos/genericos que existen en muchos paises ("MLS",
    "Liga de Ascenso", "K League 1", "Premiership"...).

    Algoritmo en 2 niveles, NUNCA adivina:
    1) Coincidencia EXACTA de conjunto de tokens contra `name` (global,
       segura). Si da 1 candidato -> resuelto. Si da 2+ (mismo nombre
       literal en varios paises, ej. "Liga de Ascenso") -> se filtra por
       country_hint; 1 remanente -> resuelto, si no LIGA_AMBIGUA.
    2) Solo si el nivel 1 no encontro NADA: si hay country_hint, se filtra
       el catalogo a ESE pais primero, y DENTRO de ese subconjunto ya
       acotado se aplica la tecnica laxa de subconjunto+prefijo (segura
       aqui porque no hay mas de un pais en juego). Sin country_hint, no se
       intenta el nivel 2 -- FAIL-CLOSED, LIGA_NO_MAPEADA en vez de
       arriesgar una coincidencia laxa sin ninguna señal de pais."""
    cached = _load_catalog()
    if not cached or not cached.get("tournaments"):
        return {"estado": LIGA_ERROR_PROVEEDOR, "tournament_id": None, "candidatos": [],
                "motivo": "catalogo de torneos no disponible localmente"}
    torneos = cached["tournaments"]

    override = LEAGUE_NAME_OVERRIDE.get(league_name)
    if override:
        league_name = override.get("name", league_name)
        country_hint = override.get("country", country_hint)

    # Nivel 1: coincidencia exacta de conjunto de tokens (global, segura)
    exactos = [t for t in torneos if _exact_token_set_match(league_name, t.get("name") or "")]
    if len(exactos) == 1:
        return {"estado": LIGA_RESUELTA, "tournament_id": exactos[0]["id"], "candidatos": exactos, "motivo": None}
    if len(exactos) > 1:
        if country_hint:
            por_pais = [t for t in exactos if _country_matches(country_hint, t.get("category") or "")]
            if len(por_pais) == 1:
                return {"estado": LIGA_RESUELTA, "tournament_id": por_pais[0]["id"], "candidatos": por_pais, "motivo": None}
        return {"estado": LIGA_AMBIGUA, "tournament_id": None, "candidatos": exactos,
                "motivo": f"{len(exactos)} candidatos con nombre EXACTO identico en distintos paises, country_hint={country_hint!r} no los desambiguo"}

    # Nivel 2: solo con country_hint -- filtra por pais PRIMERO, laxo despues
    if not country_hint:
        return {"estado": LIGA_NO_MAPEADA, "tournament_id": None, "candidatos": [],
                "motivo": f"'{league_name}' sin coincidencia exacta y sin country_hint para intentar coincidencia laxa de forma segura"}

    del_pais = [t for t in torneos if _country_matches(country_hint, t.get("category") or "")]
    candidatos = [t for t in del_pais if _loose_name_similarity(league_name, t.get("name") or "")]
    if not candidatos:
        return {"estado": LIGA_NO_MAPEADA, "tournament_id": None, "candidatos": [],
                "motivo": f"'{league_name}' (pais={country_hint!r}) sin coincidencia ni exacta ni laxa dentro de {len(del_pais)} torneos de ese pais en el catalogo"}
    if len(candidatos) > 1:
        return {"estado": LIGA_AMBIGUA, "tournament_id": None, "candidatos": candidatos,
                "motivo": f"{len(candidatos)} candidatos dentro de {country_hint!r}, ninguno elegido automaticamente"}
    return {"estado": LIGA_RESUELTA, "tournament_id": candidatos[0]["id"], "candidatos": candidatos, "motivo": None}
