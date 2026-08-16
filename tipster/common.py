# -*- coding: utf-8 -*-
"""Utilidades compartidas por rankings.py/picks.py/settlement.py -- rutas,
carga de JSON tolerante a archivos ausentes, y fecha "hoy" en hora Chile con
el MISMO offset fijo que ya usa index.html (CHILE_UTC_OFFSET=-4,
index.html:684 -- horario estandar de Chile continental, replicado aqui
para que un partido caiga en el mismo dia "Hoy"/"Mañana" que el Director ve
en la UI, ver toChileDate()/chileDateLabel() en index.html:1141-1161)."""
from __future__ import annotations

import datetime
import json
import os

ROOT = r"C:\SoccerAnalyticsExtractor\atlas_lab_mockup"
WORK = ROOT + r"\pipeline\_work"

CHILE_UTC_OFFSET_HOURS = -4


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def chile_now():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=CHILE_UTC_OFFSET_HOURS)


def chile_today():
    return chile_now().date()


def chile_date_of(kickoff_utc_iso):
    """kickoff_utc_iso viene siempre como '...Z' (ver kickoff_iso en
    01_rebuild_upcoming_matches.py) -- se parsea a UTC real y se corre a
    hora Chile antes de tomar la fecha, igual que toChileDate() en JS."""
    dt = datetime.datetime.strptime(kickoff_utc_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    return (dt + datetime.timedelta(hours=CHILE_UTC_OFFSET_HOURS)).date()


def utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def oddspapi_selection_is_valid(market_entry, sel_entry):
    """2026-08-16, auditoria EV extremo en Picks ATLAS: una cuota con
    active=False (por seleccion), marketActive=False o bookmakerIsActive=
    False NO es una cuota disponible -- debe seguir el mismo camino que una
    cuota inexistente (nunca genera candidato/value/pick). Campo AUSENTE
    (None) nunca se trata como False -- eso rompería la compatibilidad con
    evidencia capturada antes de esta correccion (ver
    atlas_lab_mockup/oddspapi/line_extraction.py y capture.py, que ahora
    propagan estos 3 campos reales del proveedor)."""
    if sel_entry.get("active") is False:
        return False
    if sel_entry.get("marketActive") is False:
        return False
    if market_entry.get("bookmakerIsActive") is False:
        return False
    return True
