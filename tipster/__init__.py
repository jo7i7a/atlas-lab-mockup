# -*- coding: utf-8 -*-
"""Tipster ATLAS -- capa de Rankings + Picks + registro historico, exclusiva
de ATLAS LAB (Edificio 5). AISLAMIENTO TOTAL: este paquete no importa nada
de las 12 estrategias LIVE, run_live_strategies.py, captura_automatica_
cuotas_listener.py, liquidacion_captura_automatica.py, notify/, IP001,
signal_platform_capture.py ni atlas_engine/data/odds_api_io_*.py. Solo lee
datos ya generados por atlas_lab_mockup/pipeline/ (POCKET_DATA/HIST_DATA/
ODDSPAPI_DATA equivalentes en JSON) y consulta soccer_analytics.db de solo
lectura (mismo patron ya usado por 01_rebuild_upcoming_matches.py).

Los motores de prediccion (atlas_pocket) y OddsPapi (atlas_lab_mockup/
oddspapi/) siguen siendo responsables de probabilidad y precio -- esta capa
solo agrega PRECIO+VALUE+SELECCION+REGISTRO+EVALUACION encima de datos ya
calculados, sin recalcular ni sustituir nada.
"""
