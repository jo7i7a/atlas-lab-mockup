# -*- coding: utf-8 -*-
"""
Building:     ATLAS_LAB_MOCKUP (Edificio 5, mockup publico de alta fidelidad)
Type:         Implementation (pipeline diario, paso 1/5)
Status:       Produccion
Dependencies: atlas_pocket (registry real), soccer_analytics.db (future_fixtures real)

Selecciona partidos REALES genuinamente futuros (future_fixtures.start_timestamp
real >= ahora, status='notstarted') resolviendo sofascore ids -> ids internos
via resolve_team()/resolve_tournament(), e invoca los 18 motores certificados
reales de Atlas Pocket para cada uno. Reemplaza el set fijo original (48
partidos horneados el 2026-07-27, quedaban obsoletos con el paso del tiempo
real -- hallazgo del Director 2026-07-27/28). Corre a diario via
run_daily.ps1 / Task Scheduler.
"""
import sys, json, sqlite3, time, datetime
sys.path.insert(0, r"C:\SoccerAnalyticsExtractor")

from atlas_pocket.data.fixtures import Fixture
from atlas_pocket.data.teams import resolve_team, resolve_tournament
from atlas_pocket.engines.setup import init_registry

WORK = r"C:\SoccerAnalyticsExtractor\atlas_lab_mockup\pipeline\_work"

LEAGUES = [
    "Brasileirão Série B", "Brasileirão Betano", "Brasileirão Série C",
    "Liga Profesional de Fútbol", "Liga MX, Apertura", "Liga de Primera",
    "Liga de Ascenso", "Copa Chile", "Eliteserien", "Allsvenskan",
]
PER_LEAGUE = 5

DB_PATH = r"C:\SoccerAnalyticsExtractor\soccer_analytics.db"
# Patron de conexion de solo-lectura replicado de future_robot/export_future_fixtures.py
# y atlas_content_engine/data/extractor_client.py -- este pipeline corre desatendido
# (Task Scheduler diario) y jamas debe poder escribir en la base frozen-baseline.
import os as _os
if not _os.path.exists(DB_PATH):
    raise FileNotFoundError(f"soccer_analytics.db no encontrado en {DB_PATH}")
conn = sqlite3.connect(DB_PATH, timeout=10)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA query_only=ON")

now_epoch = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

selected = []
for league_name in LEAGUES:
    rows = conn.execute("""
        SELECT event_id, start_timestamp, home_team_id, away_team_id, home_team_name, away_team_name
        FROM future_fixtures
        WHERE status='notstarted' AND start_timestamp >= ? AND league_name=?
        ORDER BY start_timestamp ASC
    """, (now_epoch, league_name)).fetchall()
    picked = 0
    for r in rows:
        home = resolve_team(r["home_team_id"])
        away = resolve_team(r["away_team_id"])
        if not home or not away:
            continue
        selected.append({
            "league": league_name, "event_id": r["event_id"], "start_timestamp": r["start_timestamp"],
            "home_id": home["id"], "home_name": home["name"],
            "away_id": away["id"], "away_name": away["name"],
        })
        picked += 1
        if picked >= PER_LEAGUE:
            break
    print(f"{league_name}: {picked}/{PER_LEAGUE} seleccionados (de {len(rows)} candidatos)")

print(f"\nTotal seleccionados: {len(selected)}")
if len(selected) < 10:
    print("ABORTA: muy pocos partidos resolubles, algo esta mal (futuro sync roto?)")
    sys.exit(1)

league_tournament = {}
for league_name in LEAGUES:
    row = conn.execute("SELECT tournament_id FROM future_fixtures WHERE league_name=? LIMIT 1", (league_name,)).fetchone()
    league_tournament[league_name] = resolve_tournament(row["tournament_id"]) if row else None

registry = init_registry()
print("Mercados registrados:", registry.markets())

def slugify(home_name, away_name, event_id):
    def clean(s):
        return "".join(c for c in s.lower().replace(" ", "-") if c.isalnum() or c == "-")[:20]
    return f"{clean(home_name)}-{clean(away_name)}-{event_id}"

results = {}
match_list = []
t0 = time.time()
for i, sel in enumerate(selected):
    tourn = league_tournament[sel["league"]]
    mid = slugify(sel["home_name"], sel["away_name"], sel["event_id"])
    entry = {"resolved": False}
    if tourn:
        kickoff_iso = datetime.datetime.fromtimestamp(sel["start_timestamp"], datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fixture = Fixture(
            event_id=sel["event_id"], date=kickoff_iso[:10], kickoff_utc=kickoff_iso,
            league_name=sel["league"], round_=None, status="notstarted", referee_name=None,
            home_sofascore_id=None, home_name=sel["home_name"], home_team_id=sel["home_id"],
            away_sofascore_id=None, away_name=sel["away_name"], away_team_id=sel["away_id"],
            league_sofascore_id=None, league_id=tourn["id"],
        )
        if fixture.has_history:
            markets = {}
            for market in registry.markets():
                try:
                    est = registry.estimate(market, fixture)
                    markets[market] = {
                        "source_type": est.source_type.value, "engine_id": est.engine_id,
                        "governance_status": est.governance_status.value,
                        "probability": est.probability, "n_trained": est.data_coverage,
                    }
                except Exception as e:
                    markets[market] = {"error": str(e)}
            entry.update(resolved=True, home_team_id=sel["home_id"], away_team_id=sel["away_id"],
                          league_id=tourn["id"], markets=markets)
            match_list.append({"id": mid, "home": sel["home_name"], "away": sel["away_name"],
                                "league": sel["league"], "kickoffUTC": kickoff_iso})
    results[mid] = entry
    print(f"[{i+1}/{len(selected)}] {sel['home_name']} vs {sel['away_name']} ({sel['league']}) -> resolved={entry['resolved']} ({time.time()-t0:.1f}s)")

with open(WORK + r"\pocket_engine_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=1)
with open(WORK + r"\match_list.json", "w", encoding="utf-8") as f:
    json.dump(match_list, f, ensure_ascii=False, indent=1)

n_resolved = sum(1 for v in results.values() if v.get("resolved"))
print(f"\nTotal resuelto: {n_resolved}/{len(selected)}")
if n_resolved < 10:
    print("ABORTA: muy pocos partidos con motores resueltos")
    sys.exit(1)
