# -*- coding: utf-8 -*-
"""
Building:     ATLAS_LAB_MOCKUP
Type:         Implementation (pipeline diario, paso 4/5)
Status:       Produccion

Reemplaza en index.html: (a) el bloque `const MATCHES = [...]` con los
partidos reales seleccionados hoy, (b) el fragmento POCKET_DATA/HIST_DATA/
REFEREES_BY_LEAGUE, y (c) `const LEAGUES_ORDERED = [...]` con las ligas
activas reales leidas de future_robot/tournaments_robot.json en el paso 01
(single source of verdad -- evita que la lista de ligas del mockup se
desalinee del Robot, causa raiz del hallazgo de auditoria 2026-07-29).
Aborta (exit 1) sin escribir nada si algo no calza -- nunca deja index.html
a medio actualizar.
"""
import json, re, sys

WORK = r"C:\SoccerAnalyticsExtractor\atlas_lab_mockup\pipeline\_work"
HTML_PATH = r"C:\SoccerAnalyticsExtractor\atlas_lab_mockup\index.html"

with open(WORK + r"\match_list.json", encoding="utf-8") as f:
    match_list = json.load(f)
with open(WORK + r"\pocket_engine_results.json", encoding="utf-8") as f:
    pocket = json.load(f)
with open(WORK + r"\match_data_fragment.js", encoding="utf-8") as f:
    frag = f.read()
with open(WORK + r"\leagues_used.json", encoding="utf-8") as f:
    leagues_used = json.load(f)

if len(match_list) < 10:
    print("ABORTA: match_list.json tiene muy pocos partidos"); sys.exit(1)

match_list.sort(key=lambda m: m["kickoffUTC"])

lines = ["const MATCHES = ["]
by_league = {}
for m in match_list:
    by_league.setdefault(m["league"], []).append(m)
for league, ms in by_league.items():
    lines.append(f"  // {league}")
    for m in ms:
        gov = pocket.get(m["id"], {}).get("markets", {}).get("1X2_FT", {}).get("governance_status")
        status = "certified" if gov == "CERTIFICADO" else "none"
        flagship = " flagship: true," if m is match_list[0] else ""
        home = m["home"].replace("'", "\\'")
        away = m["away"].replace("'", "\\'")
        lines.append(
            f'  {{ id: "{m["id"]}", home: "{home}", away: "{away}", league: "{league}", '
            f'kickoffUTC: "{m["kickoffUTC"]}", status: "{status}",{flagship} }},'
        )
lines.append("];")
new_matches_block = "\n".join(lines)

with open(HTML_PATH, encoding="utf-8") as f:
    html = f.read()

matches_pattern = re.compile(r"const MATCHES = \[.*?\n\];", re.S)
html, n1 = matches_pattern.subn(new_matches_block, html, count=1)
if n1 != 1:
    print(f"ABORTA: esperaba reemplazar 1 bloque MATCHES, encontro {n1}"); sys.exit(1)

leagues_block = "const LEAGUES_ORDERED = [\n  " + ",\n  ".join(json.dumps(lg, ensure_ascii=False) for lg in leagues_used) + ",\n];"
html, n_lg = re.subn(r"const LEAGUES_ORDERED = \[.*?\];", lambda m: leagues_block, html, count=1, flags=re.S)
if n_lg != 1:
    print("ABORTA: esperaba reemplazar 1 bloque LEAGUES_ORDERED, encontro", n_lg); sys.exit(1)

start_marker = "/* Datos reales de los 18 motores certificados/BASELINE de Atlas Pocket,"
end_marker = "function toChileDate(kickoffUTC) {"
if start_marker not in html or end_marker not in html:
    print("ABORTA: marcadores de datos no encontrados en index.html"); sys.exit(1)
start_idx = html.index(start_marker)
end_idx = html.index(end_marker)
html = html[:start_idx] + frag + "\n\n" + html[end_idx:]

with open(HTML_PATH, "w", encoding="utf-8") as f:
    f.write(html)

print("index.html actualizado:", len(match_list), "partidos,", len(leagues_used), "ligas activas, flagship =", match_list[0]["home"], "vs", match_list[0]["away"])
