# -*- coding: utf-8 -*-
"""
Building:     ATLAS_LAB_MOCKUP
Type:         Implementation (pipeline diario, paso 2/5)
Status:       Produccion

Calcula, para cada partido resuelto por 01_rebuild_upcoming_matches.py:
forma reciente, desempeno local/visita (FT y HT reales), y la lambda de
mercado (recencia + shrinkage a liga) para el Explorador de Lineas. Todo
sobre datos reales de soccer_analytics.db.
"""
import sys, json, sqlite3
sys.path.insert(0, r"C:\SoccerAnalyticsExtractor")

WORK = r"C:\SoccerAnalyticsExtractor\atlas_lab_mockup\pipeline\_work"

conn = sqlite3.connect(r"C:\SoccerAnalyticsExtractor\soccer_analytics.db")
conn.row_factory = sqlite3.Row

with open(WORK + r"\pocket_engine_results.json", encoding="utf-8") as f:
    pocket = json.load(f)

STAT_FIELDS = ["expectedGoals", "totalShotsOnGoal", "shotsOnGoal", "cornerKicks", "fouls", "yellowCards", "redCards",
               "totalShotsInsideBox", "totalShotsOutsideBox"]
# Nota real verificada 2026-07-27: en el esquema de SofaScore, "totalShotsOnGoal"
# es en realidad TOTAL DE TIROS (todos los intentos: on+off+blocked), NO tiros a
# puerta pese al nombre -- confirmado con datos reales: shotsOnGoal + shotsOffGoal
# + blockedScoringAttempt = totalShotsOnGoal en la misma fila. El campo real de
# "tiros a puerta" (shots on target) es "shotsOnGoal" (sin el prefijo "total").

def match_stat_agg(match_ids, team_id, period="ALL"):
    if not match_ids:
        return {}
    placeholders = ",".join("?" * len(match_ids))
    rows = conn.execute(f"""
        SELECT stat_name, AVG(stat_value) avg_val, COUNT(*) n
        FROM match_stats
        WHERE period=? AND team_id=? AND match_id IN ({placeholders})
        AND stat_name IN ({",".join("?"*len(STAT_FIELDS))})
        GROUP BY stat_name
    """, [period, team_id] + match_ids + STAT_FIELDS).fetchall()
    return {r["stat_name"]: {"avg": round(r["avg_val"], 2), "n": r["n"]} for r in rows}

def match_stat_agg_against(match_ids, team_id, period="ALL"):
    if not match_ids:
        return {}
    placeholders = ",".join("?" * len(match_ids))
    rows = conn.execute(f"""
        SELECT ms.stat_name, AVG(ms.stat_value) avg_val, COUNT(*) n
        FROM match_stats ms
        JOIN matches m ON m.id = ms.match_id
        WHERE ms.period=? AND ms.match_id IN ({placeholders})
          AND ms.team_id = (CASE WHEN m.home_team_id = ? THEN m.away_team_id ELSE m.home_team_id END)
          AND ms.stat_name IN ({",".join("?"*len(STAT_FIELDS))})
        GROUP BY ms.stat_name
    """, [period] + match_ids + [team_id] + STAT_FIELDS).fetchall()
    return {r["stat_name"]: {"avg": round(r["avg_val"], 2), "n": r["n"]} for r in rows}

def match_stat_series(match_ids_ordered, team_id, period="ALL"):
    if not match_ids_ordered:
        return {stat: [] for stat in STAT_FIELDS}
    placeholders = ",".join("?" * len(match_ids_ordered))
    rows = conn.execute(f"""
        SELECT match_id, stat_name, stat_value
        FROM match_stats
        WHERE period=? AND team_id=? AND match_id IN ({placeholders})
        AND stat_name IN ({",".join("?"*len(STAT_FIELDS))})
    """, [period, team_id] + match_ids_ordered + STAT_FIELDS).fetchall()
    by_match = {}
    for r in rows:
        by_match.setdefault(r["match_id"], {})[r["stat_name"]] = r["stat_value"]
    series = {stat: [] for stat in STAT_FIELDS}
    for mid in match_ids_ordered:
        vals = by_match.get(mid, {})
        for stat in STAT_FIELDS:
            if stat in vals:
                series[stat].append(vals[stat])
    return series

def recency_weighted_mean(values, decay=0.85):
    if not values:
        return None
    n = len(values)
    weights = [decay ** (n - 1 - i) for i in range(n)]
    wsum = sum(weights)
    return sum(v * w for v, w in zip(values, weights)) / wsum

_league_scope_cache = {}
def league_scope_mean(tournament_id, stat_name, scope, period="ALL"):
    key = (tournament_id, stat_name, scope, period)
    if key in _league_scope_cache:
        return _league_scope_cache[key]
    side_col = "m.home_team_id" if scope == "home" else "m.away_team_id"
    row = conn.execute(f"""
        SELECT AVG(ms.stat_value) avg_val, COUNT(*) n
        FROM match_stats ms
        JOIN matches m ON m.id = ms.match_id
        JOIN seasons s ON s.id = m.season_id
        WHERE ms.period=? AND ms.stat_name=? AND s.tournament_id=?
          AND ms.team_id = {side_col} AND m.status='finished'
    """, (period, stat_name, tournament_id)).fetchone()
    val = round(row["avg_val"], 2) if row and row["avg_val"] is not None else None
    _league_scope_cache[key] = val
    return val

def team_goal_values(match_ids_ordered, is_home_flag, period="ALL"):
    if not match_ids_ordered:
        return []
    if period == "ALL":
        placeholders = ",".join("?" * len(match_ids_ordered))
        col = "score_home" if is_home_flag else "score_away"
        rows = conn.execute(f"SELECT id, {col} as v FROM matches WHERE id IN ({placeholders})", match_ids_ordered).fetchall()
        vmap = {r["id"]: r["v"] for r in rows}
        return [vmap[i] for i in match_ids_ordered if i in vmap and vmap[i] is not None]
    placeholders = ",".join("?" * len(match_ids_ordered))
    valid_ids = [r["id"] for r in conn.execute(
        f"SELECT id FROM matches WHERE id IN ({placeholders}) AND has_incidents=1", match_ids_ordered).fetchall()]
    if not valid_ids:
        return []
    placeholders2 = ",".join("?" * len(valid_ids))
    is_home_val = 1 if is_home_flag else 0
    rows = conn.execute(f"""
        SELECT match_id, COUNT(*) as v FROM match_incidents
        WHERE incident_type='goal' AND rescinded=0 AND is_home=? AND time_min<=45
          AND match_id IN ({placeholders2})
        GROUP BY match_id
    """, [is_home_val] + valid_ids).fetchall()
    cmap = {r["match_id"]: r["v"] for r in rows}
    return [cmap.get(i, 0) for i in valid_ids]

_league_goals_cache = {}
def league_scope_mean_goals(tournament_id, scope, period="ALL"):
    key = (tournament_id, scope, period)
    if key in _league_goals_cache:
        return _league_goals_cache[key]
    if period == "ALL":
        col = "score_home" if scope == "home" else "score_away"
        row = conn.execute(f"""
            SELECT AVG(m.{col}) avg_val, COUNT(*) n
            FROM matches m JOIN seasons s ON s.id = m.season_id
            WHERE s.tournament_id=? AND m.status='finished'
        """, (tournament_id,)).fetchone()
    else:
        is_home_val = 1 if scope == "home" else 0
        row = conn.execute("""
            SELECT AVG(cnt) avg_val, COUNT(*) n FROM (
              SELECT m.id, COUNT(mi.id) as cnt
              FROM matches m
              JOIN seasons s ON s.id = m.season_id
              LEFT JOIN match_incidents mi ON mi.match_id = m.id AND mi.incident_type='goal'
                AND mi.rescinded=0 AND mi.is_home=? AND mi.time_min<=45
              WHERE s.tournament_id=? AND m.status='finished' AND m.has_incidents=1
              GROUP BY m.id
            )
        """, (is_home_val, tournament_id)).fetchone()
    val = round(row["avg_val"], 2) if row and row["avg_val"] is not None else None
    _league_goals_cache[key] = val
    return val

def market_lambda_goals(match_ids_ordered, is_home_flag, tournament_id, period="ALL"):
    vals = team_goal_values(match_ids_ordered, is_home_flag, period)
    team_mean = recency_weighted_mean(vals)
    if team_mean is None:
        return None
    scope = "home" if is_home_flag else "away"
    league_mean = league_scope_mean_goals(tournament_id, scope, period)
    if league_mean is None:
        return round(team_mean, 2)
    n = len(vals)
    w = n / (n + SHRINK_K)
    return round(w * team_mean + (1 - w) * league_mean, 2)

SHRINK_K = 8

def market_lambda(match_ids_ordered, team_id, tournament_id, scope, period="ALL"):
    series = match_stat_series(match_ids_ordered, team_id, period)
    out = {}
    for stat in STAT_FIELDS:
        vals = series[stat]
        team_mean = recency_weighted_mean(vals)
        league_mean = league_scope_mean(tournament_id, stat, scope, period)
        if team_mean is None and league_mean is None:
            continue
        if league_mean is None:
            out[stat] = round(team_mean, 2)
        elif team_mean is None:
            out[stat] = round(league_mean, 2)
        else:
            n = len(vals)
            w = n / (n + SHRINK_K)
            out[stat] = round(w * team_mean + (1 - w) * league_mean, 2)
    return out

def last_n_matches(team_id, n=5, home_only=False, away_only=False):
    cond = ""
    if home_only:
        cond = "AND home_team_id=?"
        params = (team_id, team_id, team_id)
    elif away_only:
        cond = "AND away_team_id=?"
        params = (team_id, team_id, team_id)
    else:
        params = (team_id, team_id)
    rows = conn.execute(f"""
        SELECT id, home_team_id, away_team_id, score_home, score_away, played_at
        FROM matches
        WHERE status='finished' AND (home_team_id=? OR away_team_id=?) {cond}
        ORDER BY played_at DESC LIMIT ?
    """, params + (n,)).fetchall()
    return list(reversed(rows))

def form_wdl(team_id, matches):
    w = d = l = 0
    gf = ga = 0
    for m in matches:
        is_home = m["home_team_id"] == team_id
        my_score = m["score_home"] if is_home else m["score_away"]
        opp_score = m["score_away"] if is_home else m["score_home"]
        if my_score is None or opp_score is None:
            continue
        gf += my_score; ga += opp_score
        if my_score > opp_score: w += 1
        elif my_score == opp_score: d += 1
        else: l += 1
    return {"w": w, "d": d, "l": l, "gf": gf, "ga": ga, "n": len(matches)}

def h2h_stats(home_id, away_id, n=60):
    rows = conn.execute("""
        SELECT id, home_team_id, away_team_id, score_home, score_away, played_at
        FROM matches
        WHERE status='finished'
          AND ((home_team_id=? AND away_team_id=?) OR (home_team_id=? AND away_team_id=?))
        ORDER BY played_at DESC LIMIT ?
    """, (home_id, away_id, away_id, home_id, n)).fetchall()
    n_matches = len(rows)
    btts = over25 = same_orientation = 0
    home_wins = away_wins = draws = 0
    for r in rows:
        sh, sa = r["score_home"], r["score_away"]
        if sh is None or sa is None:
            continue
        if sh > 0 and sa > 0: btts += 1
        if sh + sa >= 3: over25 += 1
        if r["home_team_id"] == home_id:
            same_orientation += 1
            if sh > sa: home_wins += 1
            elif sh == sa: draws += 1
            else: away_wins += 1
        else:
            if sa > sh: home_wins += 1
            elif sa == sh: draws += 1
            else: away_wins += 1
    return {
        "n": n_matches, "same_orientation_n": same_orientation,
        "btts_pct": round(btts / n_matches * 100, 1) if n_matches else None,
        "over25_pct": round(over25 / n_matches * 100, 1) if n_matches else None,
        "home_wins": home_wins, "draws": draws, "away_wins": away_wins,
    }

results = {}
for match_id, entry in pocket.items():
    if not entry.get("resolved"):
        results[match_id] = {"resolved": False}
        continue
    home_id, away_id = entry["home_team_id"], entry["away_team_id"]
    league_id = entry["league_id"]

    home_last5 = last_n_matches(home_id, 5)
    away_last5 = last_n_matches(away_id, 5)
    home_form = form_wdl(home_id, home_last5)
    away_form = form_wdl(away_id, away_last5)

    home_home_matches = last_n_matches(home_id, 10, home_only=True)
    away_away_matches = last_n_matches(away_id, 10, away_only=True)
    home_home_form = form_wdl(home_id, home_home_matches)
    away_away_form = form_wdl(away_id, away_away_matches)
    home_ids = [m["id"] for m in home_home_matches]
    away_ids = [m["id"] for m in away_away_matches]
    home_home_stats = match_stat_agg(home_ids, home_id)
    away_away_stats = match_stat_agg(away_ids, away_id)
    home_home_stats_against = match_stat_agg_against(home_ids, home_id)
    away_away_stats_against = match_stat_agg_against(away_ids, away_id)

    home_home_stats_ht = match_stat_agg(home_ids, home_id, period="1ST")
    away_away_stats_ht = match_stat_agg(away_ids, away_id, period="1ST")
    home_home_stats_against_ht = match_stat_agg_against(home_ids, home_id, period="1ST")
    away_away_stats_against_ht = match_stat_agg_against(away_ids, away_id, period="1ST")

    home_home_lambda = market_lambda(home_ids, home_id, league_id, "home", "ALL")
    away_away_lambda = market_lambda(away_ids, away_id, league_id, "away", "ALL")
    home_home_lambda_ht = market_lambda(home_ids, home_id, league_id, "home", "1ST")
    away_away_lambda_ht = market_lambda(away_ids, away_id, league_id, "away", "1ST")

    home_home_lambda["goals"] = market_lambda_goals(home_ids, True, league_id, "ALL")
    away_away_lambda["goals"] = market_lambda_goals(away_ids, False, league_id, "ALL")
    home_home_lambda_ht["goals"] = market_lambda_goals(home_ids, True, league_id, "1ST")
    away_away_lambda_ht["goals"] = market_lambda_goals(away_ids, False, league_id, "1ST")

    h2h = h2h_stats(home_id, away_id)

    results[match_id] = {
        "resolved": True,
        "home_form_last5": home_form, "away_form_last5": away_form,
        "home_home_form": home_home_form, "away_away_form": away_away_form,
        "home_home_stats": home_home_stats, "away_away_stats": away_away_stats,
        "home_home_stats_against": home_home_stats_against, "away_away_stats_against": away_away_stats_against,
        "home_home_stats_ht": home_home_stats_ht, "away_away_stats_ht": away_away_stats_ht,
        "home_home_stats_against_ht": home_home_stats_against_ht, "away_away_stats_against_ht": away_away_stats_against_ht,
        "home_home_lambda": home_home_lambda, "away_away_lambda": away_away_lambda,
        "home_home_lambda_ht": home_home_lambda_ht, "away_away_lambda_ht": away_away_lambda_ht,
        "h2h": h2h,
    }

with open(WORK + r"\historical_stats_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=1)

n_ok = sum(1 for v in results.values() if v.get("resolved"))
print(f"Resuelto: {n_ok}/{len(results)}")
if n_ok < 10:
    print("ABORTA: muy pocos partidos con historial resuelto")
    sys.exit(1)
