# -*- coding: utf-8 -*-
"""
Building:     ATLAS_LAB_MOCKUP (Edificio 5, mockup publico GitHub Pages)
Type:         Implementation (pipeline diario, paso 6/8)
Status:       Produccion
Dependencies: atlas_pocket (resolve_tournament real), soccer_analytics.db

Calcula, por liga y temporada 2026 real, las tablas de posiciones reales
(General, Local, Visita, Rendimiento ultimos 5/10/15/20 partidos) y Maximos
Goleadores -- para la pestaña "Clasificacion" del Centro de Analisis.

La tabla `standings` de soccer_analytics.db se investigo y se descarto como
fuente: solo tiene filas reales para 1 de las 10+ ligas activas (Liga de
Primera de Chile, una importacion puntual nunca mantenida para el resto).
En su lugar, General/Local/Visita/Rendimiento se calculan aqui mismo desde
matches reales (status='finished', season.year=2026): W/D/L/GF/GA/PTS,
ordenado por (puntos desc, diferencia de gol desc, goles a favor desc) --
el criterio de desempate estandar de la mayoria de las ligas reales.

Corre a diario (no semanal, como el ranking cruzado de equipos) porque las
tablas de posiciones cambian con cada fecha jugada.

Maximos Goleadores: agregado real desde match_incidents (incident_type=
'goal', incident_class IN ('regular','penalty','goal'), rescinded=0,
player_id real) unido a la tabla players real. Autogoles (incident_class=
'ownGoal') se excluyen del conteo del anotador -- convencion estandar del
futbol, un autogol no se le acredita como gol al jugador. El equipo de cada
goleador se toma como el mas frecuente entre sus goles de la temporada
(cubre el caso raro de transferencia a mitad de temporada sin inventar
una regla de "equipo actual" que no exista en el dataset).
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
FORM_WINDOWS = [5, 10, 15, 20]
SCORERS_CAP = 20

TOURNAMENTS_ROBOT_CONFIG = r"C:\SoccerAnalyticsExtractor\future_robot\tournaments_robot.json"
with open(TOURNAMENTS_ROBOT_CONFIG, encoding="utf-8") as f:
    _robot_cfg = json.load(f)
LEAGUES = [t["league_name"] for t in _robot_cfg["tournaments"] if t.get("active")]

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

player_name_cache = {}
def player_name(pid):
    if pid not in player_name_cache:
        row = conn.execute("SELECT name FROM players WHERE id=?", (pid,)).fetchone()
        player_name_cache[pid] = row["name"] if row else None
    return player_name_cache[pid]

def season_id_for(tournament_id):
    row = conn.execute("SELECT id FROM seasons WHERE tournament_id=? AND year=?", (tournament_id, SEASON_YEAR)).fetchone()
    return row["id"] if row else None

def season_matches(season_id):
    return conn.execute("""
        SELECT id, home_team_id, away_team_id, score_home, score_away, played_at
        FROM matches WHERE season_id=? AND status='finished'
        ORDER BY played_at
    """, (season_id,)).fetchall()

def team_ids_in_season(matches_rows):
    ids = set()
    for m in matches_rows:
        ids.add(m["home_team_id"]); ids.add(m["away_team_id"])
    return ids

def team_matches(team_id, matches_rows, side=None):
    out = []
    for m in matches_rows:
        is_home = m["home_team_id"] == team_id
        is_away = m["away_team_id"] == team_id
        if not is_home and not is_away:
            continue
        if side == "home" and not is_home:
            continue
        if side == "away" and not is_away:
            continue
        out.append(m)
    return out

def summarize(matches_rows, team_id):
    w = d = l = gf = ga = 0
    for m in matches_rows:
        is_home = m["home_team_id"] == team_id
        my = m["score_home"] if is_home else m["score_away"]
        opp = m["score_away"] if is_home else m["score_home"]
        if my is None or opp is None:
            continue
        gf += my; ga += opp
        if my > opp: w += 1
        elif my == opp: d += 1
        else: l += 1
    played = w + d + l
    return {"played": played, "wins": w, "draws": d, "losses": l,
            "gf": gf, "ga": ga, "gd": gf - ga, "points": w * 3 + d}

def build_table(team_ids, matches_rows, side=None, last_n=None):
    rows = []
    for tid in team_ids:
        tm = team_matches(tid, matches_rows, side)
        if last_n:
            tm = tm[-last_n:]
        s = summarize(tm, tid)
        if s["played"] == 0:
            continue
        rows.append({"team": team_name(tid), **s})
    rows.sort(key=lambda r: (-r["points"], -r["gd"], -r["gf"]))
    for i, r in enumerate(rows):
        r["position"] = i + 1
    return rows

def top_scorers(matches_rows, cap=SCORERS_CAP):
    matches_by_id = {m["id"]: m for m in matches_rows}
    if not matches_by_id:
        return []
    match_ids = list(matches_by_id.keys())
    placeholders = ",".join("?" * len(match_ids))
    rows = conn.execute(f"""
        SELECT match_id, player_id, is_home FROM match_incidents
        WHERE incident_type='goal' AND incident_class IN ('regular','penalty','goal')
          AND rescinded=0 AND player_id IS NOT NULL AND match_id IN ({placeholders})
    """, match_ids).fetchall()
    agg = {}
    for r in rows:
        m = matches_by_id[r["match_id"]]
        team_id = m["home_team_id"] if r["is_home"] else m["away_team_id"]
        pid = r["player_id"]
        entry = agg.setdefault(pid, {"count": 0, "teams": {}})
        entry["count"] += 1
        entry["teams"][team_id] = entry["teams"].get(team_id, 0) + 1
    result = []
    for pid, d in agg.items():
        pname = player_name(pid)
        if not pname:
            continue
        team_id = max(d["teams"], key=d["teams"].get)
        result.append({"player": pname, "team": team_name(team_id), "goals": d["count"]})
    result.sort(key=lambda r: -r["goals"])
    return result[:cap]

standings_by_league = {}
for league_name, tid in league_tournament.items():
    if tid is None:
        continue
    sid = season_id_for(tid)
    if sid is None:
        continue
    matches_rows = season_matches(sid)
    if not matches_rows:
        continue
    team_ids = team_ids_in_season(matches_rows)
    entry = {
        "general": build_table(team_ids, matches_rows),
        "home": build_table(team_ids, matches_rows, side="home"),
        "away": build_table(team_ids, matches_rows, side="away"),
        "scorers": top_scorers(matches_rows),
    }
    for n in FORM_WINDOWS:
        entry[f"form{n}"] = build_table(team_ids, matches_rows, last_n=n)
    standings_by_league[league_name] = entry
    print(f"{league_name}: {len(entry['general'])} equipos, {len(matches_rows)} partidos, {len(entry['scorers'])} goleadores")

with open(WORK + r"\standings_by_league.json", "w", encoding="utf-8") as f:
    json.dump(standings_by_league, f, ensure_ascii=False, indent=1)

print(f"\nLigas con clasificacion real: {len(standings_by_league)}/{len(LEAGUES)}")
if len(standings_by_league) < 3:
    print("ABORTA: muy pocas ligas con datos, algo esta mal")
    sys.exit(1)
