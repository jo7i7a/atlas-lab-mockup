# -*- coding: utf-8 -*-
"""
Building:     ATLAS_LAB_MOCKUP (Edificio 5, mockup publico GitHub Pages)
Type:         Implementation (pipeline semanal, paso 1/1)
Status:       Produccion
Dependencies: atlas_pocket (resolve_tournament real), soccer_analytics.db

Calcula TEAM_RADIOGRAPHY (por equipo, por liga, temporada 2026 real: BTTS/
Over2.5/Under2.5/Corners+9.5/Remates a puerta/Tarjetas -- TOTAL y separado
Local/Visita) y TEAM_LEADERBOARDS (ranking cruzado de las 10 ligas, lista
COMPLETA por categoria -- ya no capada a 10, el frontend decide cuanto
mostrar/expandir). Reemplaza el proceso ad-hoc original (sin script, horneado
a mano 2026-07-26) con un calculo real y repetible, corrido semanalmente via
run_weekly.ps1 / Task Scheduler.

Filtro de temporada: seasons.year = 2026 (confirmado via PRAGMA table_info,
no existe columna de "temporada actual" separada -- year=2026 es la unica
fuente de verdad real).

Piso minimo de muestra para el ranking cruzado (TEAM_LEADERBOARDS): 5
partidos -- mismo piso implicito ya observado en el ranking anterior, ahora
aplicado de forma UNIFORME a las 10 ligas (sin excepciones por liga).

Nota de continuidad (2026-08-04): el campo "shots"/"Remates a Puerta" usa
totalShotsOnGoal (que en el esquema real de SofaScore es el TOTAL de tiros,
no tiros a puerta pese al nombre -- ver nota en 02_compute_historical_
stats.py) porque asi estaba calculado el ranking original (verificado con
Botafogo: 12.7 real actual vs 12.95 horneado 2026-07-26, mismo campo). No se
cambia a shotsOnGoal (el campo real de tiros a puerta) para no alterar la
definicion ya publicada sin que el Director lo pida explicitamente.
"""
import sys, json, sqlite3
sys.path.insert(0, r"C:\SoccerAnalyticsExtractor")

from atlas_pocket.data.teams import resolve_tournament

WORK = r"C:\SoccerAnalyticsExtractor\atlas_lab_mockup\pipeline\_work"
DB_PATH = r"C:\SoccerAnalyticsExtractor\soccer_analytics.db"

import os as _os
if not _os.path.exists(DB_PATH):
    raise FileNotFoundError(f"soccer_analytics.db no encontrado en {DB_PATH}")
conn = sqlite3.connect(DB_PATH, timeout=10)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA query_only=ON")

SEASON_YEAR = 2026
MIN_MATCHES_LEADERBOARD = 5

# Mismas 10 ligas de LEAGUES_ORDERED (index.html) / LEAGUES (01_rebuild_upcoming_matches.py).
LEAGUES = [
    "Brasileirão Série B", "Brasileirão Betano", "Brasileirão Série C",
    "Liga Profesional de Fútbol", "Liga MX, Apertura", "Liga de Primera",
    "Liga de Ascenso", "Copa Chile", "Eliteserien", "Allsvenskan",
]

league_tournament = {}
for league_name in LEAGUES:
    row = conn.execute("SELECT tournament_id FROM future_fixtures WHERE league_name=? LIMIT 1", (league_name,)).fetchone()
    resolved = resolve_tournament(row["tournament_id"]) if row else None
    league_tournament[league_name] = resolved["id"] if resolved else None

team_name_cache = {}
def team_name(tid):
    if tid not in team_name_cache:
        row = conn.execute("SELECT name FROM teams WHERE id=?", (tid,)).fetchone()
        team_name_cache[tid] = row["name"] if row else None
    return team_name_cache[tid]

def team_ids_in_tournament(tournament_id):
    rows = conn.execute("""
        SELECT home_team_id AS tid FROM matches m JOIN seasons s ON m.season_id = s.id
        WHERE s.tournament_id=? AND s.year=? AND m.status='finished'
        UNION
        SELECT away_team_id AS tid FROM matches m JOIN seasons s ON m.season_id = s.id
        WHERE s.tournament_id=? AND s.year=? AND m.status='finished'
    """, (tournament_id, SEASON_YEAR, tournament_id, SEASON_YEAR)).fetchall()
    return [r["tid"] for r in rows]

def team_matches(team_id, tournament_id, side=None):
    extra, params = "", [team_id, team_id, tournament_id, SEASON_YEAR]
    if side == "home":
        extra, params = "AND m.home_team_id=?", params + [team_id]
    elif side == "away":
        extra, params = "AND m.away_team_id=?", params + [team_id]
    return conn.execute(f"""
        SELECT m.id, m.home_team_id, m.away_team_id, m.score_home, m.score_away
        FROM matches m JOIN seasons s ON m.season_id = s.id
        WHERE (m.home_team_id=? OR m.away_team_id=?) AND s.tournament_id=? AND s.year=?
          AND m.status='finished' {extra}
        ORDER BY m.id
    """, params).fetchall()

def compute_metrics(matches, team_id):
    n = len(matches)
    if n == 0:
        return None
    match_ids = [m["id"] for m in matches]
    gf = ga = btts = over25 = 0
    for m in matches:
        is_home = m["home_team_id"] == team_id
        my = m["score_home"] if is_home else m["score_away"]
        opp = m["score_away"] if is_home else m["score_home"]
        if my is None or opp is None:
            continue
        gf += my; ga += opp
        if my > 0 and opp > 0: btts += 1
        if my + opp >= 3: over25 += 1

    placeholders = ",".join("?" * len(match_ids))
    corner_rows = conn.execute(f"""
        SELECT match_id, SUM(stat_value) total FROM match_stats
        WHERE period='ALL' AND stat_name='cornerKicks' AND match_id IN ({placeholders})
        GROUP BY match_id HAVING COUNT(*) = 2
    """, match_ids).fetchall()
    corners_pct = None
    if corner_rows:
        over95 = sum(1 for r in corner_rows if r["total"] > 9.5)
        corners_pct = round(over95 / len(corner_rows) * 100, 1)

    shots_row = conn.execute(f"""
        SELECT AVG(stat_value) avg_val FROM match_stats
        WHERE period='ALL' AND team_id=? AND stat_name='totalShotsOnGoal' AND match_id IN ({placeholders})
    """, [team_id] + match_ids).fetchone()
    shots_avg = round(shots_row["avg_val"], 2) if shots_row and shots_row["avg_val"] is not None else None

    cards_row = conn.execute(f"""
        SELECT AVG(stat_value) avg_val FROM match_stats
        WHERE period='ALL' AND team_id=? AND stat_name='yellowCards' AND match_id IN ({placeholders})
    """, [team_id] + match_ids).fetchone()
    cards_avg = round(cards_row["avg_val"], 2) if cards_row and cards_row["avg_val"] is not None else None

    over25_pct = round(over25 / n * 100, 1)
    return {
        "matches": n, "gf": gf, "ga": ga,
        "btts": round(btts / n * 100, 1), "over25": over25_pct, "under25": round(100 - over25_pct, 1),
        "corners": corners_pct, "shots": shots_avg, "cards": cards_avg,
    }

team_radiography = {}
leaderboard_flat = {"btts": [], "over25": [], "corners": [], "shots": [], "cards": []}

for league_name, tid in league_tournament.items():
    if tid is None:
        continue
    rows = []
    for team_id in team_ids_in_tournament(tid):
        name = team_name(team_id)
        if not name:
            continue
        total_matches = team_matches(team_id, tid)
        total = compute_metrics(total_matches, team_id)
        if not total:
            continue
        home = compute_metrics(team_matches(team_id, tid, "home"), team_id)
        away = compute_metrics(team_matches(team_id, tid, "away"), team_id)
        row = {"team": name, **total, "home": home, "away": away}
        rows.append(row)
        if total["matches"] >= MIN_MATCHES_LEADERBOARD:
            for key in leaderboard_flat:
                if total[key] is not None:
                    leaderboard_flat[key].append({"team": name, "league": league_name, "value": total[key]})
    rows.sort(key=lambda r: -r["matches"])
    team_radiography[league_name] = rows
    print(f"{league_name}: {len(rows)} equipos (temporada {SEASON_YEAR})")

LB_META = {
    "btts": {"label": "Mayor % de BTTS", "unit": "%"},
    "over25": {"label": "Mejor Over 2.5", "unit": "%"},
    "corners": {"label": "Mayor % de Corners (+9.5)", "unit": "%"},
    "shots": {"label": "Más Remates a Puerta", "unit": " prom/partido"},
    "cards": {"label": "Equipos más tarjeteros", "unit": " prom/partido"},
}
team_leaderboards = {}
for key, entries in leaderboard_flat.items():
    entries.sort(key=lambda r: -r["value"])
    team_leaderboards[key] = {**LB_META[key], "rows": entries}
    print(f"leaderboard {key}: {len(entries)} equipos (min {MIN_MATCHES_LEADERBOARD} partidos)")

# Total real de partidos en toda la base (vista "Ligas": "partidos totales
# en la base de datos de ATLAS -- historico completo, todos los torneos") --
# sin filtro de status ni de temporada, coherente con esa etiqueta. Antes
# quedaba fijo desde que se horneo a mano (2026-07-26); ahora se recalcula
# en cada corrida semanal (hallazgo de la auditoria 2026-07-29: estaba
# desactualizado en 1 partido).
total_matches_atlas = conn.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"]
print(f"TOTAL_MATCHES_ATLAS real: {total_matches_atlas}")

with open(WORK + r"\team_radiography.json", "w", encoding="utf-8") as f:
    json.dump(team_radiography, f, ensure_ascii=False, indent=1)
with open(WORK + r"\team_leaderboards.json", "w", encoding="utf-8") as f:
    json.dump(team_leaderboards, f, ensure_ascii=False, indent=1)
with open(WORK + r"\total_matches_atlas.json", "w", encoding="utf-8") as f:
    json.dump({"total": total_matches_atlas}, f)

n_leagues_ok = sum(1 for v in team_radiography.values() if v)
print(f"\nLigas con datos: {n_leagues_ok}/{len(LEAGUES)}")
if n_leagues_ok < 3:
    print("ABORTA: muy pocas ligas con datos, algo esta mal")
    sys.exit(1)
