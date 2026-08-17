"""14_sync_results_intraday.py -- captura intradia de resultados reales.

building  : ATLAS_LAB_MOCKUP (Edificio 5, mockup publico GitHub Pages)
type      : Implementation (captura de resultados para Tipster ATLAS)
status    : Produccion

Unica responsabilidad: invocar extractor_master.py (BASELINE CONGELADO, sin
modificar) como subproceso, una vez por cada liga de la lista acotada de
abajo, con --sync-only (sincroniza rondas + escribe matches.status/
score_home/score_away/played_at via _db_import_core -- NO descarga el batch
pesado de detalle/stats/alineaciones/incidents por evento, eso queda para
la corrida diaria completa de las 06:30).

Este script NO toca git, NO publica index.html, NO llama a settlement, NO
llama a rankings/picks/OddsPapi/motores. Su unico efecto es que
soccer_analytics.db quede con resultados mas frescos para que el proximo
ciclo de run_settlement_cycle.ps1 (settlement.py, sin cambios) los encuentre.

Lista acotada de configs -- por que estas 20 y no un barrido de configs/*.json
--------------------------------------------------------------------------
seasons.status en soccer_analytics.db NO es fiable para distinguir temporada
vigente de temporada historica (174 de 175 configs aparecian "active";
auditoria 2026-08-16). La lista de abajo se construyo cruzando
future_robot/tournaments_robot.json (las ligas que ATLAS LAB realmente seguia
a esa fecha) contra configs/*.json, resolviendo la identidad real de cada
liga via soccer_analytics.db.tournaments/seasons (tournament_id/season_id no
usan la misma convencion en los dos archivos: tournaments_robot.json mezcla
ids internos de la DB con sofascore_id reales segun cuando se agrego cada
liga; configs/*.json siempre usa el sofascore_id real, que es lo que
extractor_master.py envia a la API). Verificado por consulta directa,
read-only, el 2026-08-16.

6 ligas de tournaments_robot.json NO tienen config de temporada vigente en
configs/*.json (CONMEBOL Sudamericana 2026, UEFA Champions League 26/27,
Challenge League 26/27, J1 League temporada real mas reciente, Liga Portugal
Betclic 26/27, Leagues Cup) -- quedan fuera de esta captura intradia hasta
que exista una config para esa temporada. No se crea una config nueva aqui:
eso es una decision de alcance fuera de este cambio.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(r"C:\SoccerAnalyticsExtractor")
_PYTHON = _REPO_ROOT / ".venv" / "Scripts" / "python.exe"
_EXTRACTOR = "extractor_master.py"
_PER_CONFIG_TIMEOUT_S = 90

# Lista acotada, verificada read-only el 2026-08-16 (ver docstring arriba).
CONFIGS = [
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


def _sync_one(config_name: str) -> tuple[str, bool, str]:
    """Invoca extractor_master.py --config <cfg> --scheduled --sync-only.

    Tolera fallos individuales (misma politica que orchestrator_master.py):
    una liga que falla no detiene a las demas. Nunca usa --force/--full
    (eso reprocesa todo, innecesario y pesado para un ciclo de 40 min).
    """
    config_path = f"configs/{config_name}"
    cmd = [
        str(_PYTHON), _EXTRACTOR,
        "--config", config_path,
        "--scheduled",
        "--sync-only",
    ]
    try:
        res = subprocess.run(
            cmd,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=_PER_CONFIG_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return config_name, False, f"timeout tras {_PER_CONFIG_TIMEOUT_S}s"

    if res.returncode != 0:
        tail = (res.stderr or res.stdout or "").strip()[-500:]
        return config_name, False, tail

    return config_name, True, ""


def main() -> int:
    if not _PYTHON.exists():
        print(f"ERROR: no se encontro el interprete Python en {_PYTHON}")
        return 2

    t0 = time.time()
    ok_count = 0
    fail_count = 0

    print(f"=== 14_sync_results_intraday.py -- {len(CONFIGS)} liga(s) ===")
    for name in CONFIGS:
        league_t0 = time.time()
        league, ok, detail = _sync_one(name)
        elapsed_ms = int((time.time() - league_t0) * 1000)
        if ok:
            ok_count += 1
            print(f"  OK    {league:<32} ({elapsed_ms} ms)")
        else:
            fail_count += 1
            print(f"  ERROR {league:<32} ({elapsed_ms} ms) -- {detail}")

    elapsed_s = time.time() - t0
    print("-" * 60)
    print(f"OK: {ok_count}/{len(CONFIGS)}   ERROR: {fail_count}/{len(CONFIGS)}   "
          f"duracion total: {elapsed_s:.1f}s")

    # Nunca falla el proceso completo por fallos individuales de liga (misma
    # tolerancia que orchestrator_master.py) -- el run_results_capture_cycle.ps1
    # que invoca este script no toca git de ningun modo, asi que no hay nada
    # que revertir. Solo se reporta codigo != 0 si NINGUNA liga funciono, como
    # senal de que algo estructural fallo (ej. extractor_master.py roto).
    return 0 if ok_count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
