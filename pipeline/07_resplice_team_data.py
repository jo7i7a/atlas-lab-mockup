# -*- coding: utf-8 -*-
"""
Building:     ATLAS_LAB_MOCKUP
Type:         Implementation (pipeline semanal, paso 2/2)
Status:       Produccion

Reemplaza en index.html los bloques `const TEAM_LEADERBOARDS = {...};` y
`const TEAM_RADIOGRAPHY = {...};` con la salida real de
06_compute_team_leaderboards.py. No toca TOTAL_MATCHES_ATLAS ni LEAGUE_STATS
(fuera del alcance de este cambio). Aborta (exit 1) sin escribir nada si
algo no calza.
"""
import json, re, sys

WORK = r"C:\SoccerAnalyticsExtractor\atlas_lab_mockup\pipeline\_work"
HTML_PATH = r"C:\SoccerAnalyticsExtractor\atlas_lab_mockup\index.html"

with open(WORK + r"\team_leaderboards.json", encoding="utf-8") as f:
    team_leaderboards = json.load(f)
with open(WORK + r"\team_radiography.json", encoding="utf-8") as f:
    team_radiography = json.load(f)

with open(HTML_PATH, encoding="utf-8") as f:
    html = f.read()

lb_block = "const TEAM_LEADERBOARDS = " + json.dumps(team_leaderboards, ensure_ascii=False) + ";"
rad_block = "const TEAM_RADIOGRAPHY = " + json.dumps(team_radiography, ensure_ascii=False) + ";"

html, n1 = re.subn(r"const TEAM_LEADERBOARDS = \{.*?\};", lambda m: lb_block, html, count=1)
if n1 != 1:
    print("ABORTA: esperaba reemplazar 1 bloque TEAM_LEADERBOARDS, encontro", n1); sys.exit(1)

html, n2 = re.subn(r"const TEAM_RADIOGRAPHY = \{.*?\};", lambda m: rad_block, html, count=1)
if n2 != 1:
    print("ABORTA: esperaba reemplazar 1 bloque TEAM_RADIOGRAPHY, encontro", n2); sys.exit(1)

with open(HTML_PATH, "w", encoding="utf-8") as f:
    f.write(html)

n_teams = sum(len(v) for v in team_radiography.values())
print(f"index.html actualizado: {n_teams} equipos en TEAM_RADIOGRAPHY, "
      f"{sum(len(v['rows']) for v in team_leaderboards.values())} filas en TEAM_LEADERBOARDS")
