# -*- coding: utf-8 -*-
"""
Building:     ATLAS_LAB_MOCKUP
Type:         Implementation (pipeline diario, paso 7/8)
Status:       Produccion

Inyecta `const STANDINGS_BY_LEAGUE = {...};` en index.html con la salida de
08_compute_standings.py. Si el marcador ya existe lo reemplaza; si es la
primera corrida (todavia no existe en index.html) lo inserta justo despues
de LEAGUE_STATS. Aborta (exit 1) sin escribir nada si algo no calza.
"""
import json, re, sys

WORK = r"C:\SoccerAnalyticsExtractor\atlas_lab_mockup\pipeline\_work"
HTML_PATH = r"C:\SoccerAnalyticsExtractor\atlas_lab_mockup\index.html"

with open(WORK + r"\standings_by_league.json", encoding="utf-8") as f:
    standings = json.load(f)

with open(HTML_PATH, encoding="utf-8") as f:
    html = f.read()

block = "const STANDINGS_BY_LEAGUE = " + json.dumps(standings, ensure_ascii=False) + ";"

if "const STANDINGS_BY_LEAGUE = " in html:
    html, n = re.subn(r"const STANDINGS_BY_LEAGUE = \{.*?\};", lambda m: block, html, count=1)
    if n != 1:
        print("ABORTA: esperaba reemplazar 1 bloque STANDINGS_BY_LEAGUE, encontro", n); sys.exit(1)
else:
    anchor = "const LEAGUE_STATS = "
    if anchor not in html:
        print("ABORTA: no encontro el marcador de anclaje LEAGUE_STATS"); sys.exit(1)
    idx = html.index(anchor)
    html = html[:idx] + block + "\n\n" + html[idx:]

with open(HTML_PATH, "w", encoding="utf-8") as f:
    f.write(html)

n_leagues = len(standings)
n_teams = sum(len(v["general"]) for v in standings.values())
print(f"index.html actualizado: {n_leagues} ligas con clasificacion, {n_teams} filas de tabla general")
