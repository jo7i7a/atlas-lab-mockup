# -*- coding: utf-8 -*-
"""Matching de partido ATLAS <-> fixture de OddsPapi -- exclusivo de ATLAS
LAB (Edificio 5). Via PRIMARIA: el campo real `externalProviders.sofascoreId`
que OddsPapi ya incluye en cada fixture (confirmado real durante la
validacion de esta sesion) coincide DIRECTAMENTE con el event_id de
SofaScore que ATLAS ya usa -- mucho mas simple y confiable que el matching
por nombre de equipo usado para Odds-API.io (que no comparte ningun ID con
ATLAS). Via de respaldo: matching por nombre, para el caso en que
sofascoreId venga null/ausente en un fixture especifico.

Building:     ATLAS_LAB_MOCKUP (Edificio 5) / Laboratorio de Estrategias
Type:         Implementation
Status:       Produccion

FAIL-CLOSED: nunca se elige arbitrariamente entre candidatos ambiguos.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from atlas_engine.data.team_name_reconciliation import normalize  # noqa: E402

MIN_PREFIX_LEN = 4

MATCH_UNICO_POR_ID = "MATCH_UNICO_POR_ID"
MATCH_UNICO_POR_NOMBRE = "MATCH_UNICO_POR_NOMBRE"
NO_MATCH = "NO_MATCH"
NO_MATCH_AMBIGUO = "NO_MATCH_AMBIGUO"


def _tokens_compatible(a: str, b: str) -> bool:
    if a == b:
        return True
    if {a, b} == {"man", "manchester"}:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= MIN_PREFIX_LEN and longer.startswith(shorter)


def _name_similarity(a: str, b: str) -> bool:
    na, nb = normalize(a).split(), normalize(b).split()
    if not na or not nb:
        return False
    a_in_b = all(any(_tokens_compatible(ta, tb) for tb in nb) for ta in na)
    b_in_a = all(any(_tokens_compatible(tb, ta) for ta in na) for tb in nb)
    return a_in_b or b_in_a


def _sofascore_id_of(fixture: dict) -> int | None:
    ext = fixture.get("externalProviders") or {}
    sid = ext.get("sofascoreId")
    return sid if isinstance(sid, int) else None


def match_fixture(event_id: int, home_name: str, away_name: str, fixtures: list[dict]) -> dict:
    """Empareja UN partido de ATLAS (identificado por su SofaScore event_id +
    nombres de equipo) contra la lista de fixtures ya descargados de OddsPapi
    para el/los torneo(s) correspondiente(s) (0 llamadas adicionales --
    comparacion local). Retorna {"estado": ..., "fixture": dict|None,
    "candidatos": [...], "motivo": str|None}."""
    # Via primaria: sofascoreId directo
    por_id = [f for f in fixtures if _sofascore_id_of(f) == event_id]
    if len(por_id) == 1:
        return {"estado": MATCH_UNICO_POR_ID, "fixture": por_id[0], "candidatos": por_id, "motivo": None}
    if len(por_id) > 1:
        return {"estado": NO_MATCH_AMBIGUO, "fixture": None, "candidatos": por_id,
                "motivo": f"{len(por_id)} fixtures de OddsPapi comparten sofascoreId={event_id} (no deberia pasar, fail-closed defensivo)"}

    # Via de respaldo: matching por nombre, solo para fixtures SIN sofascoreId
    # (si un fixture ya tiene sofascoreId y no matcheo arriba, no es este
    # partido -- no se reintenta por nombre para evitar falsos positivos)
    sin_id = [f for f in fixtures if _sofascore_id_of(f) is None]
    candidatos = [
        f for f in sin_id
        if _name_similarity(home_name, f.get("participant1Name") or "")
        and _name_similarity(away_name, f.get("participant2Name") or "")
    ]
    if not candidatos:
        return {"estado": NO_MATCH, "fixture": None, "candidatos": [],
                "motivo": "sin candidatos por sofascoreId ni por nombre"}
    if len(candidatos) > 1:
        return {"estado": NO_MATCH_AMBIGUO, "fixture": None, "candidatos": candidatos,
                "motivo": f"{len(candidatos)} candidatos por nombre, ninguno elegido automaticamente"}
    return {"estado": MATCH_UNICO_POR_NOMBRE, "fixture": candidatos[0], "candidatos": candidatos, "motivo": None}
