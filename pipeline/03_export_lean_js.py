# -*- coding: utf-8 -*-
"""
Building:     ATLAS_LAB_MOCKUP
Type:         Implementation (pipeline diario, paso 3/5)
Status:       Produccion

Combina pocket_engine_results.json + historical_stats_results.json +
referees_by_league.json (este ultimo NO se recalcula a diario -- son
estadisticas de carrera de arbitros, cambian con muy poca frecuencia; se
regenera manualmente solo si hace falta) en el fragmento JS que se
inyecta en index.html.
"""
import json

WORK = r"C:\SoccerAnalyticsExtractor\atlas_lab_mockup\pipeline\_work"

with open(WORK + r"\pocket_engine_results.json", encoding="utf-8") as f:
    pocket = json.load(f)
with open(WORK + r"\historical_stats_results.json", encoding="utf-8") as f:
    hist = json.load(f)
with open(WORK + r"\referees_by_league.json", encoding="utf-8") as f:
    referees = json.load(f)
# 2026-08-16, integracion OddsPapi Edificio 5: oddspapi_lean.json es opcional
# a proposito -- si 10_fetch_oddspapi_odds.py fallo o no corrio, esto NUNCA
# debe abortar el resto del pipeline (la integracion es puramente aditiva).
try:
    with open(WORK + r"\oddspapi_lean.json", encoding="utf-8") as f:
        oddspapi = json.load(f)
except FileNotFoundError:
    oddspapi = {}

GOV_SHORT = {"CERTIFICADO": "CERT", "PROMOVIDO": "PROM", "BASELINE": "BASE", "EXPERIMENTAL": "EXP", "NO_DISPONIBLE": "ND"}

lean_pocket = {}
for match_id, entry in pocket.items():
    if not entry.get("resolved"):
        lean_pocket[match_id] = None
        continue
    markets = {}
    for mkt, data in entry["markets"].items():
        if "error" in data:
            continue
        compact = {
            "p": {k: round(v, 4) for k, v in (data["probability"] or {}).items()},
            "g": GOV_SHORT.get(data["governance_status"], data["governance_status"]),
            "e": data["engine_id"],
        }
        # 2026-08-16, integracion OddsPapi Edificio 5: la linea de Handicap
        # (hl/al) no es fija como el resto de los mercados -- sin exponerla
        # aqui, ni la UI ni el matching de OddsPapi pueden saber contra que
        # linea comparar. market_context es None para mercados de linea fija.
        ctx = data.get("market_context")
        if mkt == "HANDICAP_FT" and ctx:
            compact["hl"] = ctx.get("home_line")
            compact["al"] = ctx.get("away_line")
        markets[mkt] = compact
    lean_pocket[match_id] = markets

lean_hist = {}
for match_id, entry in hist.items():
    if not entry.get("resolved"):
        lean_hist[match_id] = None
        continue
    def trim_stats(d):
        return {k: v["avg"] for k, v in d.items()}
    lean_hist[match_id] = {
        "f5h": entry["home_form_last5"], "f5a": entry["away_form_last5"],
        "hh": entry["home_home_form"], "aa": entry["away_away_form"],
        "hhs": trim_stats(entry["home_home_stats"]), "aas": trim_stats(entry["away_away_stats"]),
        "hhsA": trim_stats(entry["home_home_stats_against"]), "aasA": trim_stats(entry["away_away_stats_against"]),
        "hhsHT": trim_stats(entry["home_home_stats_ht"]), "aasHT": trim_stats(entry["away_away_stats_ht"]),
        "hhsAHT": trim_stats(entry["home_home_stats_against_ht"]), "aasAHT": trim_stats(entry["away_away_stats_against_ht"]),
        "hhsLmb": entry["home_home_lambda"], "aasLmb": entry["away_away_lambda"],
        "hhsLmbHT": entry["home_home_lambda_ht"], "aasLmbHT": entry["away_away_lambda_ht"],
        "hhsLmbA": entry["home_home_lambda_against"], "aasLmbA": entry["away_away_lambda_against"],
        "hhsLmbAHT": entry["home_home_lambda_against_ht"], "aasLmbAHT": entry["away_away_lambda_against_ht"],
        "hhsLmb2ND": entry["home_home_lambda_2nd"], "aasLmb2ND": entry["away_away_lambda_2nd"],
        "h2h": entry["h2h"],
        # BTTS% descriptivo (no certificado) sobre ultimos-10 local/visita --
        # ver 02_compute_historical_stats.py::btts_pct_over(). Se preservan
        # los mismos nombres de campo del JSON fuente (sin abreviar) para
        # trazabilidad/auditoria directa. n real ya viene implicito en
        # hh["n"]/aa["n"] (misma lista de partidos), pero tambien se expone
        # aqui bajo nombre propio de BTTS (2026-08-02, pedido del Director)
        # junto con procedencia (years/mixed_seasons) y el flag de validez
        # de muestra minima -- nunca se oculta el % aunque la muestra sea chica.
        "home_btts_pct": entry["home_btts_pct"], "away_btts_pct": entry["away_btts_pct"],
        "btts_general_pct": entry["btts_general_pct"],
        "home_btts_n": entry["home_btts_n"], "away_btts_n": entry["away_btts_n"],
        "home_btts_years": entry["home_btts_years"], "away_btts_years": entry["away_btts_years"],
        "home_btts_mixed_seasons": entry["home_btts_mixed_seasons"],
        "away_btts_mixed_seasons": entry["away_btts_mixed_seasons"],
        "btts_sample_valid": entry["btts_sample_valid"],
    }

out = []
out.append("/* Datos reales de los 18 motores certificados/BASELINE de Atlas Pocket,")
out.append("   invocados en vivo (registry.estimate) para cada partido real -- horneado")
out.append("   a diario por el pipeline (run_daily.ps1 / Task Scheduler).")
out.append("   p=probability por resultado, g=governance_status abreviado, e=engine_id real.")
out.append("   El mockup no llama a Atlas Pocket en vivo, pero cada numero SI vino de sus")
out.append("   motores reales, no de un calculo propio del Content Engine. */")
out.append("const POCKET_DATA = " + json.dumps(lean_pocket, ensure_ascii=False) + ";")
out.append("")
out.append("/* Estadisticas historicas reales (forma ultimos 5, desempeno local/visita")
out.append("   ultimos 10 FT+HT, H2H directo, lambda de mercado con shrinkage a liga) --")
out.append("   consultas directas a soccer_analytics.db. Ver 02_compute_historical_stats.py. */")
out.append("const HIST_DATA = " + json.dumps(lean_hist, ensure_ascii=False) + ";")
out.append("")
out.append("/* Arbitros reales (tabla referees + match_referees), career stats -- NO se")
out.append("   recalcula a diario (cambia con poca frecuencia), regenerado manualmente. */")
out.append("const REFEREES_BY_LEAGUE = " + json.dumps(referees, ensure_ascii=False) + ";")
out.append("")
out.append("/* Cuotas automaticas reales de OddsPapi FREE (2026-08-16, ATLAS LAB Edificio 5")
out.append("   exclusivamente -- NO relacionado con Odds-API.io/sistema LIVE). Solo 4")
out.append("   mercados: 1X2_FT, OU25_GOALS_FT, HANDICAP_FT, BTTS. bk=bookmaker real,")
out.append("   sel={seleccion: {p:cuota decimal, t:timestamp del proveedor, l:linea}}.")
out.append("   Vacio o con huecos por partido/mercado es esperado y normal -- ver")
out.append("   oddspapi_estado.json para el motivo exacto de cada hueco. */")
out.append("const ODDSPAPI_DATA = " + json.dumps(oddspapi, ensure_ascii=False) + ";")

frag = "\n".join(out)
with open(WORK + r"\match_data_fragment.js", "w", encoding="utf-8") as f:
    f.write(frag)
print("bytes:", len(frag))
