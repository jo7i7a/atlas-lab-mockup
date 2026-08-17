# -*- coding: utf-8 -*-
"""Tests de atlas_lab_mockup/pipeline/14_sync_results_intraday.py (captura
intradia de resultados, 2026-08-16). El modulo bajo prueba empieza con un
digito (convencion de los scripts numerados de pipeline/), asi que no se
puede usar `import` normal -- se carga por ruta via importlib, sin ejecutar
main() (el modulo no tiene efectos secundarios a nivel de import: CONFIGS es
una constante y _sync_one/main solo actuan cuando se llaman explicitamente).

Nunca golpea la red ni extractor_master.py real -- subprocess.run se
monkeypatchea en todos los tests que ejercitan _sync_one/main.
"""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(r"C:\SoccerAnalyticsExtractor")
_MODULE_PATH = _REPO_ROOT / "atlas_lab_mockup" / "pipeline" / "14_sync_results_intraday.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("sync_results_intraday", _MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load_module()


# ---------------------------------------------------------------------
# CONFIGS -- la lista acotada debe ser exactamente la aprobada
# ---------------------------------------------------------------------

APPROVED_CONFIGS = [
    "mundial_2026.json",
    "premier_league_2526.json",
    "bundesliga_2526.json",
    "la_liga_2526.json",
    "serie_a_2526.json",
    "serie_b_2026.json",
    "serie_c_2026.json",
    "copa_chile_2026.json",
    "brasileirao_a_2026.json",
    "liga_mx_apertura_2026.json",
    "eliteserien_2026.json",
    "allsvenskan_2026.json",
    "primera_2026.json",
    "arg_pd_2026.json",
    "primera_b_2026.json",
    "copa_lib_2026.json",
    "mls_2026.json",
    "k1_2026.json",
    "scottish_prem_2627.json",
    "eredivisie_2627.json",
]


def test_configs_es_exactamente_la_lista_aprobada(mod):
    assert mod.CONFIGS == APPROVED_CONFIGS


def test_configs_sin_duplicados(mod):
    assert len(mod.CONFIGS) == len(set(mod.CONFIGS))


def test_configs_20_ligas(mod):
    assert len(mod.CONFIGS) == 20


def test_cada_config_existe_en_disco(mod):
    configs_dir = _REPO_ROOT / "configs"
    faltantes = [c for c in mod.CONFIGS if not (configs_dir / c).exists()]
    assert faltantes == [], f"config(s) listadas pero ausentes en disco: {faltantes}"


def test_cada_config_tiene_tournament_id_y_season_id_reales(mod):
    configs_dir = _REPO_ROOT / "configs"
    for c in mod.CONFIGS:
        data = json.loads((configs_dir / c).read_text(encoding="utf-8"))
        assert "tournament_id" in data and "season_id" in data, c


# ---------------------------------------------------------------------
# _sync_one -- invocacion de extractor_master.py, tolerante a fallos
# ---------------------------------------------------------------------

def test_sync_one_usa_scheduled_y_sync_only_nunca_force(mod, monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    league, ok, detail = mod._sync_one("allsvenskan_2026.json")

    assert ok is True
    assert detail == ""
    cmd = captured["cmd"]
    assert "--config" in cmd and "configs/allsvenskan_2026.json" in cmd
    assert "--scheduled" in cmd
    assert "--sync-only" in cmd
    assert "--force" not in cmd
    assert "--full" not in cmd


def test_sync_one_falla_una_liga_sin_lanzar_excepcion(mod, monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    league, ok, detail = mod._sync_one("mls_2026.json")

    assert ok is False
    assert "boom" in detail


def test_sync_one_timeout_no_lanza_excepcion(mod, monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 0))

    monkeypatch.setattr(subprocess, "run", fake_run)
    league, ok, detail = mod._sync_one("mundial_2026.json")

    assert ok is False
    assert "timeout" in detail


# ---------------------------------------------------------------------
# main() -- tolerancia por-liga, nunca toca git (no hay ninguna llamada)
# ---------------------------------------------------------------------

def test_main_ok_si_al_menos_una_liga_funciona(mod, monkeypatch, capsys):
    def fake_sync_one(name):
        return (name, name == mod.CONFIGS[0], "" if name == mod.CONFIGS[0] else "err")

    monkeypatch.setattr(mod, "_sync_one", fake_sync_one)
    assert mod.main() == 0


def test_main_falla_si_ninguna_liga_funciona(mod, monkeypatch):
    def fake_sync_one(name):
        return (name, False, "err")

    monkeypatch.setattr(mod, "_sync_one", fake_sync_one)
    assert mod.main() == 1


def test_modulo_no_importa_subprocess_de_git(mod):
    src = _MODULE_PATH.read_text(encoding="utf-8")
    for token in ("git add", "git commit", "git push", "git checkout"):
        assert token not in src
