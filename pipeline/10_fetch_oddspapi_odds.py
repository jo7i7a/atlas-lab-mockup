# -*- coding: utf-8 -*-
"""
Building:     ATLAS_LAB_MOCKUP (Edificio 5) / Laboratorio de Estrategias
Type:         Implementation (pipeline diario, paso nuevo -- corre entre 01 y 02)
Status:       Produccion

Fallback automatico de cuotas PRE-PARTIDO via OddsPapi FREE para 1X2/
Over-Under goles/Asian Handicap/BTTS -- EXCLUSIVO de ATLAS LAB (Edificio 5).
NO relacionado con Odds-API.io (fuente de cuotas del sistema LIVE) ni con
ninguna estrategia LIVE/IP001/captura AUTO/liquidacion AUTO/Telegram.

Consume _work/pocket_engine_results.json, _work/match_event_ids.json y
_work/leagues_used.json (producidos por 01_rebuild_upcoming_matches.py,
solo lectura). Escribe _work/oddspapi_lean.json, que 03_export_lean_js.py
inyecta como `const ODDSPAPI_DATA` en index.html (mismo mecanismo de
"horneado" ya usado para POCKET_DATA/HIST_DATA -- 04_resplice_index_html.py
no necesita saber que este paso existe).

NUNCA debe abortar el pipeline diario: si OddsPapi falla, esta corriendo sin
cupo mensual, o cualquier otra cosa sale mal, este script SIEMPRE termina
con exit code 0 y deja oddspapi_lean.json en un estado seguro (vacio si no
hay nada que ofrecer) -- run_daily.ps1 sigue publicando el mockup con los
mercados manuales funcionando exactamente igual que hoy.
"""
import json
import sys

sys.path.insert(0, r"C:\SoccerAnalyticsExtractor")

try:
    from atlas_lab_mockup.oddspapi import capture

    resumen = capture.run()
    print(json.dumps(resumen, indent=1, ensure_ascii=False, default=str))
    if resumen.get("error_no_controlado"):
        print(f"AVISO (no bloqueante): {resumen['error_no_controlado']}")
except Exception as exc:  # noqa: BLE001 -- este paso jamas debe tumbar run_daily.ps1
    print(f"AVISO (no bloqueante): fallo no controlado en 10_fetch_oddspapi_odds.py: {type(exc).__name__}: {exc}")

# Siempre exit 0 -- esta integracion es puramente aditiva, nunca bloquea la
# publicacion diaria del mockup (mismo principio que
# DISENO_FINAL_INTEGRACION_ODDS_API_IO_2026-08-15.md aplica a su integracion
# hermana: "el modulo nunca puede interferir con la produccion existente").
sys.exit(0)
