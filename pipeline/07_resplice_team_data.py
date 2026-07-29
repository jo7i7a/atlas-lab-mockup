# -*- coding: utf-8 -*-
"""
Building:     ATLAS_LAB_MOCKUP
Type:         Implementation (pipeline semanal, paso 2/2)
Status:       Produccion

Reemplaza en index.html los bloques `const TEAM_LEADERBOARDS = {...};`,
`const TEAM_RADIOGRAPHY = {...};` y `const TOTAL_MATCHES_ATLAS = ...;` con la
salida real de 06_compute_team_leaderboards.py. No toca LEAGUE_STATS (fuera
del alcance de este cambio). Aborta (exit 1) sin escribir nada si algo no
calza.
"""
import json, re, sys

WORK = r"C:\SoccerAnalyticsExtractor\atlas_lab_mockup\pipeline\_work"
HTML_PATH = r"C:\SoccerAnalyticsExtractor\atlas_lab_mockup\index.html"

with open(WORK + r"\team_leaderboards.json", encoding="utf-8") as f:
    team_leaderboards = json.load(f)
with open(WORK + r"\team_radiography.json", encoding="utf-8") as f:
    team_radiography = json.load(f)
with open(WORK + r"\total_matches_atlas.json", encoding="utf-8") as f:
    total_matches_atlas = json.load(f)["total"]

with open(HTML_PATH, encoding="utf-8") as f:
    html = f.read()

lb_block = "const TEAM_LEADERBOARDS = " + json.dumps(team_leaderboards, ensure_ascii=False) + ";"
rad_block = "const TEAM_RADIOGRAPHY = " + json.dumps(team_radiography, ensure_ascii=False) + ";"
total_block = "const TOTAL_MATCHES_ATLAS = " + str(total_matches_atlas) + ";"

html, n1 = re.subn(r"const TEAM_LEADERBOARDS = \{.*?\};", lambda m: lb_block, html, count=1)
if n1 != 1:
    print("ABORTA: esperaba reemplazar 1 bloque TEAM_LEADERBOARDS, encontro", n1); sys.exit(1)

html, n2 = re.subn(r"const TEAM_RADIOGRAPHY = \{.*?\};", lambda m: rad_block, html, count=1)
if n2 != 1:
    print("ABORTA: esperaba reemplazar 1 bloque TEAM_RADIOGRAPHY, encontro", n2); sys.exit(1)

html, n3 = re.subn(r"const TOTAL_MATCHES_ATLAS = \d+;", lambda m: total_block, html, count=1)
if n3 != 1:
    print("ABORTA: esperaba reemplazar 1 bloque TOTAL_MATCHES_ATLAS, encontro", n3); sys.exit(1)

with open(HTML_PATH, "w", encoding="utf-8") as f:
    f.write(html)

n_teams = sum(len(v) for v in team_radiography.values())
print(f"index.html actualizado: {n_teams} equipos en TEAM_RADIOGRAPHY, "
      f"{sum(len(v['rows']) for v in team_leaderboards.values())} filas en TEAM_LEADERBOARDS, "
      f"TOTAL_MATCHES_ATLAS={total_matches_atlas}")
