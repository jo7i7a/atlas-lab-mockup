# -*- coding: utf-8 -*-
"""
Building:     ATLAS_LAB_MOCKUP (Edificio 5) / Tipster ATLAS
Type:         Implementation (pipeline diario, paso nuevo -- corre al final)
Status:       Produccion

Liquida Rankings/Picks ATLAS pendientes cuyo partido ya termino, contra el
resultado real de soccer_analytics.db -- ver
atlas_lab_mockup/tipster/settlement.py (reutiliza
atlas_pocket/trackrecord/resolution.py, solo lectura). Corre AL FINAL del
pipeline diario (despues de 01, que ya refresco finalScore/status de los
partidos recien terminados).

NUNCA debe abortar el pipeline diario -- mismo principio que el resto de
los pasos de Tipster ATLAS. Solo completa campos pendientes; nunca altera
probabilidad/cuota/EV ya capturados (ver docstring de settlement.py).
"""
import json
import sys

sys.path.insert(0, r"C:\SoccerAnalyticsExtractor")

try:
    from atlas_lab_mockup.tipster import settlement

    resumen = {"rankings": settlement.settle_history(), "picks": settlement.settle_picks()}
    # 2026-08-16, ciclo de settlement intraday: quita de tipster_picks_estado.json
    # (lista "Picks activos") los pick_id que la liquidacion de arriba ya resolvio
    # -- no liquida nada nuevo, no toca el jsonl, solo depura la vista activa.
    resumen["picks_activos_removidos"] = settlement.prune_settled_picks_from_estado()
    print(json.dumps(resumen, indent=1, ensure_ascii=False, default=str))
except Exception as exc:  # noqa: BLE001 -- este paso jamas debe tumbar run_daily.ps1
    print(f"AVISO (no bloqueante): fallo no controlado en 13_settle_tipster.py: {type(exc).__name__}: {exc}")

sys.exit(0)
