# -*- coding: utf-8 -*-
"""
Building:     ATLAS_LAB_MOCKUP (Edificio 5) / Tipster ATLAS
Type:         Implementation (pipeline diario, paso nuevo -- corre despues de 01/02/10)
Status:       Produccion

Genera/mantiene los 4 rankings (Over2.5/Under2.5/BTTS/Over10.5 Corners) x
(diario/semanal) -- ver atlas_lab_mockup/tipster/rankings.py para la logica
real (reutiliza pocket_engine_results.json/historical_stats_results.json/
oddspapi_lean.json, ya generados por pasos anteriores, sin recalcular nada).

NUNCA debe abortar el pipeline diario -- mismo principio que
10_fetch_oddspapi_odds.py: si algo falla, el paso deja los rankings
existentes intactos y run_daily.ps1 sigue publicando el resto del mockup.
"""
import json
import sys

sys.path.insert(0, r"C:\SoccerAnalyticsExtractor")

try:
    from atlas_lab_mockup.tipster import rankings

    resumen = rankings.run()
    print(json.dumps(resumen, indent=1, ensure_ascii=False, default=str))
except Exception as exc:  # noqa: BLE001 -- este paso jamas debe tumbar run_daily.ps1
    print(f"AVISO (no bloqueante): fallo no controlado en 11_build_rankings.py: {type(exc).__name__}: {exc}")

sys.exit(0)
