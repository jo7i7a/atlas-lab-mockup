# -*- coding: utf-8 -*-
"""REPORTE READ-ONLY de precisión del Ranking BTTS diario de ATLAS LAB.

Building:     ATLAS_LAB_MOCKUP (Edificio 5) / Tipster ATLAS
Type:         Implementation (reporte, SOLO LECTURA -- nunca escribe nada)
Status:       Producción (autorizado por el Director 2026-08-29)
Dependencies: atlas_lab_mockup/tipster_rankings_history.jsonl (única fuente,
              solo lectura), tipster/common.py

Autorización del Director (2026-08-29): "NO crear otro tracker. NO crear una
segunda fuente. NO reconstruir histórico artificialmente. Usar exclusivamente
tipster_rankings_history.jsonl como fuente forward oficial."

Este módulo NO genera ranking, NO liquida, NO consulta soccer_analytics.db,
NO escribe ningún archivo. Solo lee el log forward que ya produce
rankings.py + settlement.py y lo agrega en las métricas de precisión pedidas.

REGLA METODOLÓGICA CENTRAL (mandato del Director, ver
AUDITORIA_TRAZABILIDAD_RANKING_BTTS_2026-08-22.md y
feedback_intraday_snapshot_identification_rule): el Top 10 diario ROTA
intradía. Cada `(window_key, predicted_at_utc)` es UN snapshot = UNA
observación independiente. NUNCA se combinan partidos de snapshots
distintos. La lista manual "10/10" del 2026-08-22 se compuso a mano a
partir de 2 snapshots -- este reporte NO reproduce esa metodología.

Patrón de Única Fuente de Verdad: API pública mínima (build_report,
render_text, load_btts_rows), internals privados (_*).
"""
from __future__ import annotations

import json
import os
from collections import defaultdict

from atlas_lab_mockup.tipster.common import ROOT

HISTORY_PATH = ROOT + r"\tipster_rankings_history.jsonl"

TOP_CUTS = (1, 3, 5, 10)

# El "10/10" localizado en el forense 2026-08-28 -- se documenta SIEMPRE con
# esta redacción exacta, nunca como evidencia de rendimiento del algoritmo.
NOTA_10_DE_10 = (
    "Lista manual compuesta a partir de dos snapshots distintos del "
    "2026-08-22 (10:36 UTC y 21:21 UTC); 10/10 real en los partidos "
    "seleccionados, pero NO representa un Top-10 único ni una fotografía "
    "única del ranking ATLAS. No se usa como evidencia de rendimiento del "
    "algoritmo. Ningún snapshot individual del sistema es 10/10 (el mejor: "
    "2026-08-22 21:21 UTC = 5/5, con solo 5 partidos finalizados)."
)


def load_btts_rows(history_path: str | None = None, ranking_type: str = "daily") -> list[dict]:
    """Lee el log forward y devuelve SOLO las filas BTTS del ranking_type
    pedido ('daily' por defecto). Solo lectura, tolerante a archivo ausente."""
    path = history_path or HISTORY_PATH
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("market") == "BTTS" and r.get("ranking_type") == ranking_type:
                rows.append(r)
    return rows


def _snapshot_key(r: dict) -> tuple:
    return (r.get("window_key"), r.get("predicted_at_utc"))


def _group_by_snapshot(rows: list[dict]) -> dict[tuple, list[dict]]:
    g: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        g[_snapshot_key(r)].append(r)
    return g


def _tally(rows: list[dict]) -> dict:
    """Cuenta finalizadas / aciertos / fallos / pendientes sobre una lista
    de filas ya seleccionada (nunca mezcla snapshots -- eso lo hace el
    llamador)."""
    fin = [r for r in rows if r.get("estado") == "FINALIZADO"]
    ac = sum(1 for r in fin if r.get("acierto") == "acierto")
    fa = sum(1 for r in fin if r.get("acierto") == "fallo")
    pend = sum(1 for r in rows if r.get("estado") != "FINALIZADO")
    return {
        "n_total": len(rows), "n_finalizado": len(fin),
        "aciertos": ac, "fallos": fa, "pendientes": pend,
        "pct_acierto": round(100 * ac / len(fin), 1) if fin else None,
    }


# ---------------------------------------------------------------------------
# A. Rendimiento acumulado por Top-N (cada snapshot evaluado como unidad
#    independiente, luego sumado)
# ---------------------------------------------------------------------------

def accumulated_by_topn(rows: list[dict]) -> dict[int, dict]:
    by_snap = _group_by_snapshot(rows)
    out: dict[int, dict] = {}
    for cut in TOP_CUTS:
        acc = {"n_total": 0, "n_finalizado": 0, "aciertos": 0, "fallos": 0, "pendientes": 0}
        for snap_rows in by_snap.values():
            top = [r for r in snap_rows if (r.get("posicion") or 999) <= cut]
            t = _tally(top)
            for k in acc:
                acc[k] += t[k]
        acc["pct_acierto"] = round(100 * acc["aciertos"] / acc["n_finalizado"], 1) if acc["n_finalizado"] else None
        out[cut] = acc
    return out


# ---------------------------------------------------------------------------
# B. Rendimiento por snapshot (unidad independiente)
# ---------------------------------------------------------------------------

def by_snapshot(rows: list[dict]) -> list[dict]:
    by_snap = _group_by_snapshot(rows)
    out = []
    for (wk, pat), snap_rows in sorted(by_snap.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or "")):
        srt = sorted(snap_rows, key=lambda r: (r.get("posicion") or 999))
        t = _tally(srt)
        out.append({
            "window_key": wk,
            "predicted_at_utc": pat,
            "n_encuentros": len(srt),
            "n_finalizado": t["n_finalizado"],
            "aciertos": t["aciertos"],
            "fallos": t["fallos"],
            "pendientes": t["pendientes"],
            "completo": t["pendientes"] == 0,
            "pct_acierto": t["pct_acierto"],
            "por_topn": {cut: _tally([r for r in srt if (r.get("posicion") or 999) <= cut]) for cut in TOP_CUTS},
            "encuentros": [
                {
                    "posicion": r.get("posicion"),
                    "partido": r.get("partido"),
                    "liga": r.get("liga"),
                    "probabilidad_atlas": r.get("probabilidad_atlas"),
                    "cuota": r.get("cuota"),
                    "bookmaker": r.get("bookmaker"),
                    "estado": r.get("estado"),
                    "resultado_real": r.get("resultado_real"),
                    "acierto": r.get("acierto"),
                }
                for r in srt
            ],
        })
    return out


# ---------------------------------------------------------------------------
# C. Desgloses
# ---------------------------------------------------------------------------

def by_league(rows: list[dict]) -> dict[str, dict]:
    g: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        g[r.get("liga") or "(sin liga)"].append(r)
    return {liga: _tally(rs) for liga, rs in sorted(g.items(), key=lambda kv: -_tally(kv[1])["n_finalizado"])}


def by_position(rows: list[dict]) -> dict[int, dict]:
    g: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        p = r.get("posicion")
        if p is not None:
            g[p].append(r)
    return {p: _tally(g[p]) for p in sorted(g)}


def temporal(rows: list[dict]) -> list[dict]:
    """Evolución día a día (window_key). Cada día agrega TODOS sus snapshots
    (siguen sin mezclarse entre sí en el conteo por-snapshot de la sección B;
    aquí es una vista diaria agregada, explícitamente etiquetada)."""
    g: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        g[r.get("window_key") or "(sin fecha)"].append(r)
    out = []
    ac_acc = fin_acc = 0
    for wk in sorted(g):
        t = _tally(g[wk])
        ac_acc += t["aciertos"]
        fin_acc += t["n_finalizado"]
        out.append({
            "window_key": wk,
            "n_snapshots": len({_snapshot_key(r) for r in g[wk]}),
            "n_finalizado": t["n_finalizado"],
            "aciertos": t["aciertos"],
            "fallos": t["fallos"],
            "pendientes": t["pendientes"],
            "pct_dia": t["pct_acierto"],
            "pct_acumulado": round(100 * ac_acc / fin_acc, 1) if fin_acc else None,
        })
    return out


# ---------------------------------------------------------------------------
# D. Estado actual
# ---------------------------------------------------------------------------

def status(rows: list[dict]) -> dict:
    if not rows:
        return {"vacio": True}
    wks = sorted({r.get("window_key") for r in rows if r.get("window_key")})
    pats = sorted({r.get("predicted_at_utc") for r in rows if r.get("predicted_at_utc")})
    pendientes = [r for r in rows if r.get("estado") != "FINALIZADO"]
    # continuidad: días consecutivos desde el primero
    import datetime as _dt
    dias = [_dt.date.fromisoformat(w) for w in wks]
    gaps = [(dias[i], dias[i + 1]) for i in range(len(dias) - 1) if (dias[i + 1] - dias[i]).days != 1]
    return {
        "primer_window_key": wks[0],
        "ultimo_window_key": wks[-1],
        "ultimo_snapshot_utc": pats[-1] if pats else None,
        "dias_cubiertos": len(wks),
        "dias_consecutivos_sin_hueco": len(gaps) == 0,
        "huecos": [f"{a.isoformat()} -> {b.isoformat()}" for a, b in gaps],
        "snapshots_totales": len({_snapshot_key(r) for r in rows}),
        "filas_totales": len(rows),
        "filas_finalizadas": sum(1 for r in rows if r.get("estado") == "FINALIZADO"),
        "fixtures_pendientes_de_liquidacion": len(pendientes),
        "ejemplos_pendientes": [
            {"window_key": r.get("window_key"), "partido": r.get("partido"), "posicion": r.get("posicion")}
            for r in sorted(pendientes, key=lambda r: (r.get("window_key") or ""), reverse=True)[:10]
        ],
    }


# ---------------------------------------------------------------------------
# Reporte completo
# ---------------------------------------------------------------------------

def build_report(history_path: str | None = None) -> dict:
    rows = load_btts_rows(history_path)
    return {
        "fuente": history_path or HISTORY_PATH,
        "regla_metodologica": (
            "cada (window_key, predicted_at_utc) = 1 snapshot = 1 observación "
            "independiente; nunca se combinan partidos de snapshots distintos"
        ),
        "nota_10_de_10": NOTA_10_DE_10,
        "A_acumulado_por_topn": accumulated_by_topn(rows),
        "B_por_snapshot": by_snapshot(rows),
        "C_por_liga": by_league(rows),
        "C_por_posicion": by_position(rows),
        "C_evolucion_temporal": temporal(rows),
        "D_estado": status(rows),
    }


def render_text(report: dict | None = None) -> str:
    if report is None:
        report = build_report()
    L = []
    L.append("=" * 78)
    L.append("REPORTE DE PRECISIÓN — RANKING BTTS DIARIO DE ATLAS LAB  (READ-ONLY)")
    L.append("=" * 78)
    L.append(f"Fuente: {report['fuente']}")
    L.append(f"Regla: {report['regla_metodologica']}")
    st = report["D_estado"]
    if st.get("vacio"):
        L.append("\n(sin filas BTTS en el log)")
        return "\n".join(L)

    L.append("")
    L.append("D. ESTADO ACTUAL")
    L.append(f"  Cobertura: {st['primer_window_key']} -> {st['ultimo_window_key']} "
             f"({st['dias_cubiertos']} días, {st['snapshots_totales']} snapshots, {st['filas_totales']} filas)")
    L.append(f"  Continuidad sin hueco: {st['dias_consecutivos_sin_hueco']}"
             + (f"  HUECOS: {st['huecos']}" if st["huecos"] else ""))
    L.append(f"  Último snapshot: {st['ultimo_snapshot_utc']}")
    L.append(f"  Finalizadas: {st['filas_finalizadas']}/{st['filas_totales']}  |  "
             f"Pendientes de liquidación: {st['fixtures_pendientes_de_liquidacion']}")

    L.append("")
    L.append("A. RENDIMIENTO ACUMULADO POR TOP-N  (snapshots como unidades independientes)")
    L.append(f"  {'corte':>7} {'n_fin':>6} {'acier':>6} {'fallo':>6} {'pend':>6} {'%acierto':>9}")
    for cut in TOP_CUTS:
        a = report["A_acumulado_por_topn"][cut]
        pct = f"{a['pct_acierto']}%" if a["pct_acierto"] is not None else "-"
        L.append(f"  Top{cut:>4} {a['n_finalizado']:>6} {a['aciertos']:>6} {a['fallos']:>6} {a['pendientes']:>6} {pct:>9}")

    L.append("")
    L.append("B. POR SNAPSHOT  (cada uno independiente -- NO se combinan entre sí)")
    for s in report["B_por_snapshot"]:
        flag = "COMPLETO" if s["completo"] else f"PARCIAL ({s['pendientes']} pend.)"
        pct = f"{s['pct_acierto']}%" if s["pct_acierto"] is not None else "-"
        L.append(f"  {s['window_key']}  {s['predicted_at_utc']}  n={s['n_encuentros']:>2}  "
                 f"fin={s['n_finalizado']:>2}  acier={s['aciertos']:>2}  fallo={s['fallos']:>2}  "
                 f"{pct:>6}  [{flag}]")
        t1, t3, t5 = s["por_topn"][1], s["por_topn"][3], s["por_topn"][5]
        L.append(f"       Top1 {t1['aciertos']}/{t1['n_finalizado']}  "
                 f"Top3 {t3['aciertos']}/{t3['n_finalizado']}  Top5 {t5['aciertos']}/{t5['n_finalizado']}")
        for e in s["encuentros"]:
            res = e["acierto"] or (e["estado"] or "?").lower()
            L.append(f"         #{e['posicion']:<2} {(e['partido'] or '?')[:44]:44} "
                     f"{(e['liga'] or '?')[:22]:22} p={e['probabilidad_atlas']}  -> {res}")

    L.append("")
    L.append("C. DESGLOSE POR LIGA  (solo finalizadas)")
    for liga, t in report["C_por_liga"].items():
        if t["n_finalizado"] == 0:
            continue
        pct = f"{t['pct_acierto']}%" if t["pct_acierto"] is not None else "-"
        L.append(f"  {liga[:34]:34} n={t['n_finalizado']:>3}  acier={t['aciertos']:>3}  fallo={t['fallos']:>3}  {pct:>7}")

    L.append("")
    L.append("C. DESGLOSE POR POSICIÓN DEL RANKING")
    for p, t in report["C_por_posicion"].items():
        pct = f"{t['pct_acierto']}%" if t["pct_acierto"] is not None else "-"
        L.append(f"  pos {p:>2}  n_fin={t['n_finalizado']:>3}  acier={t['aciertos']:>3}  fallo={t['fallos']:>3}  {pct:>7}")

    L.append("")
    L.append("C. EVOLUCIÓN TEMPORAL  (vista diaria agregada -- etiquetada como tal)")
    L.append(f"  {'fecha':>12} {'snaps':>6} {'n_fin':>6} {'acier':>6} {'%día':>7} {'%acum':>7}")
    for d in report["C_evolucion_temporal"]:
        pd = f"{d['pct_dia']}%" if d["pct_dia"] is not None else "-"
        pa = f"{d['pct_acumulado']}%" if d["pct_acumulado"] is not None else "-"
        L.append(f"  {d['window_key']:>12} {d['n_snapshots']:>6} {d['n_finalizado']:>6} "
                 f"{d['aciertos']:>6} {pd:>7} {pa:>7}")

    L.append("")
    L.append("NOTA SOBRE EL '10/10':")
    L.append(f"  {report['nota_10_de_10']}")
    L.append("=" * 78)
    return "\n".join(L)


if __name__ == "__main__":
    print(render_text())
