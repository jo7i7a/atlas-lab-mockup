# -*- coding: utf-8 -*-
"""
Building:     ATLAS_LAB_MOCKUP (Edificio 5) / Tipster ATLAS
Type:         Implementation (pipeline diario, paso nuevo -- corre despues de 01/02/10)
Status:       Produccion

Evalua candidato -> value -> pick para los 4 mercados automatizados por
OddsPapi (1X2/Over-Under goles/Asian Handicap/BTTS) -- ver
atlas_lab_mockup/tipster/picks.py para la logica real (reutiliza
pocket_engine_results.json/oddspapi_lean.json ya generados, sin recalcular
probabilidad ni cuota).

NUNCA debe abortar el pipeline diario -- mismo principio que
10_fetch_oddspapi_odds.py/11_build_rankings.py.
"""
import json
import sys

sys.path.insert(0, r"C:\SoccerAnalyticsExtractor")

try:
    from atlas_lab_mockup.tipster import picks

    resumen = picks.run()
    print(json.dumps(resumen, indent=1, ensure_ascii=False, default=str))
except Exception as exc:  # noqa: BLE001 -- este paso jamas debe tumbar run_daily.ps1
    print(f"AVISO (no bloqueante): fallo no controlado en 12_build_picks_atlas.py: {type(exc).__name__}: {exc}")

sys.exit(0)
