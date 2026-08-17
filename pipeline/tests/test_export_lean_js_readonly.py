# -*- coding: utf-8 -*-
"""Test de regresion (2026-08-16, mejora de interfaz/analisis del Track
Record de Picks ATLAS): 03_export_lean_js.py ahora tambien lee
tipster_picks_history.jsonl para hornear PICKS_ATLAS_DATA.history -- este
test confirma, con el archivo REAL del proyecto, que esa lectura nunca lo
reescribe (Objetivo 8/9/13 de la auditoria: historicos permanecen
intactos). Corre el script real (subprocess, mismo binario que usa el
pipeline) -- no mockea nada, es la misma garantia que ya se verifico a
mano antes de publicar."""
import hashlib
import subprocess
import sys
from pathlib import Path

_ROOT = Path(r"C:\SoccerAnalyticsExtractor\atlas_lab_mockup")
_HISTORY_PATH = _ROOT / "tipster_picks_history.jsonl"
_ESTADO_PATH = _ROOT / "tipster_picks_estado.json"
_SCRIPT = _ROOT / "pipeline" / "03_export_lean_js.py"
_PYTHON = Path(r"C:\SoccerAnalyticsExtractor\.venv\Scripts\python.exe")


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_export_lean_js_no_reescribe_tipster_picks_history():
    if not _HISTORY_PATH.exists():
        return  # nada que verificar todavia si el archivo no existe (paso 12 no corrio)
    before = _sha256(_HISTORY_PATH)

    res = subprocess.run(
        [str(_PYTHON), str(_SCRIPT)],
        cwd=str(_ROOT / "pipeline"),
        capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0, res.stderr

    after = _sha256(_HISTORY_PATH)
    assert before == after, "03_export_lean_js.py NO debe modificar tipster_picks_history.jsonl (solo lectura)"


def test_export_lean_js_no_reescribe_tipster_picks_estado():
    if not _ESTADO_PATH.exists():
        return
    before = _sha256(_ESTADO_PATH)

    res = subprocess.run(
        [str(_PYTHON), str(_SCRIPT)],
        cwd=str(_ROOT / "pipeline"),
        capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0, res.stderr

    after = _sha256(_ESTADO_PATH)
    assert before == after, "03_export_lean_js.py NO debe modificar tipster_picks_estado.json (solo lectura)"
