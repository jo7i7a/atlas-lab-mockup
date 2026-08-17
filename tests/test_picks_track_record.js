// -*- coding: utf-8 -*-
// Building:     ATLAS_LAB_MOCKUP (Edificio 5)
// Type:         Test
// Status:       Produccion
//
// Mejora de interfaz/analisis del Track Record de Picks ATLAS (2026-08-16,
// Carril A). Prueba el agregador nuevo (aggregatePicks), los filtros del
// Historico (Mercado + Fecha, distintos de los filtros de "Picks activos"
// ya probados en test_picks_atlas_filters.js) y las funciones de render de
// las secciones nuevas: Resultados de hoy, Rentabilidad por mercado,
// Rentabilidad del filtro actual, Historial de Picks. Ninguna de estas
// funciones toca tipster_picks_history.jsonl -- solo leen
// PICKS_ATLAS_DATA.history (ya horneado, solo lectura).
//
// Corre con: node atlas_lab_mockup/tests/test_picks_track_record.js
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const INDEX_HTML = path.join(__dirname, "..", "index.html");
const src = fs.readFileSync(INDEX_HTML, "utf-8");

function extractFunction(name) {
  const m = src.match(new RegExp("function\\s+" + name + "\\s*\\("));
  if (!m) throw new Error("No se encontro function " + name + "() en index.html");
  const start = m.index;
  const braceStart = src.indexOf("{", start);
  let depth = 0, i = braceStart;
  for (; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}") { depth--; if (depth === 0) { i++; break; } }
  }
  return src.slice(start, i);
}
function extractConst(name) {
  const re = new RegExp("const\\s+" + name + "\\s*=\\s*[^;]*;");
  const m = src.match(re);
  if (!m) throw new Error("No se encontro const " + name + " en index.html");
  return m[0];
}
// PICKS_ATLAS_DATA es un objeto grande (todo el historico real horneado por
// 03_export_lean_js.py) -- se extrae completo, no con extractConst (que
// asume terminar en el primer ';', y este objeto puede contener ';' dentro
// de strings). Se busca el marcador "const PICKS_ATLAS_DATA = " y se
// balancea llaves, igual tecnica que extractFunction.
function extractDataConst(name) {
  const marker = "const " + name + " = ";
  const start = src.indexOf(marker);
  if (start === -1) throw new Error("No se encontro const " + name + " en index.html");
  const braceStart = start + marker.length; // apunta al '{' o '[' inicial
  const open = src[braceStart];
  const close = open === "{" ? "}" : "]";
  let depth = 0, i = braceStart;
  for (; i < src.length; i++) {
    if (src[i] === open) depth++;
    else if (src[i] === close) { depth--; if (depth === 0) { i++; break; } }
  }
  return "const " + name + " = " + src.slice(braceStart, i) + ";";
}

const CORE = [
  extractConst("CHILE_UTC_OFFSET"),
  extractFunction("toChileDate"),
  extractFunction("todayChileMidnightUTC"),
  extractFunction("chileDayOffset"),
  extractFunction("chileNowParts"),
  extractFunction("pyRound"),
  extractFunction("aggregatePicks"),
  extractFunction("pickIsSettled"),
  extractFunction("pickMatchesDateFilter"),
].join("\n\n");

function runInSandbox(code) {
  const sandbox = {};
  vm.createContext(sandbox);
  return vm.runInContext(code, sandbox);
}

function kickoffDaysFromNow(days) {
  return new Date(Date.now() + days * 86400000).toISOString().replace(/\.\d+Z$/, "Z");
}
function pick(overrides) {
  return Object.assign({
    market: "1X2_FT", kickoff_utc: kickoffDaysFromNow(0), partido: "A vs B",
    estado: "PENDIENTE", roi_pct: null, ev_pct: 5.0, cuota: 2.0, probabilidad_atlas: 0.55,
  }, overrides);
}

let passed = 0;
function test(name, fn) {
  try {
    fn();
    passed++;
    console.log("ok - " + name);
  } catch (e) {
    console.error("FAIL - " + name);
    console.error(e.stack || e);
    process.exitCode = 1;
  }
}

// ---------------------------------------------------------------------
// aggregatePicks -- REGLA FUNDAMENTAL (Objetivo 6/7)
// ---------------------------------------------------------------------

test("aggregatePicks: ROI/Yield no incluyen PENDIENTES (roi_pct null)", () => {
  const records = [
    pick({ estado: "GANADO", roi_pct: 100 }),
    pick({ estado: "PERDIDO", roi_pct: -100 }),
    pick({ estado: "PENDIENTE", roi_pct: null }),
    pick({ estado: "PENDIENTE", roi_pct: null }),
  ];
  const code = CORE + `\n\naggregatePicks(${JSON.stringify(records)});`;
  const s = runInSandbox(code);
  assert.strictEqual(s.total, 4);
  assert.strictEqual(s.pendientes, 2);
  // promedio solo de los 2 liquidados (100 + -100)/2 = 0, NO incluye los 2 nulls
  assert.strictEqual(s.roi_pct, 0);
  assert.strictEqual(s.yield_pct, 0);
});

test("aggregatePicks: Win Rate no incluye PENDIENTES ni ANULADOS", () => {
  const records = [
    pick({ estado: "GANADO", roi_pct: 100 }),
    pick({ estado: "GANADO", roi_pct: 80 }),
    pick({ estado: "PERDIDO", roi_pct: -100 }),
    pick({ estado: "ANULADO", roi_pct: 0 }),
    pick({ estado: "PENDIENTE", roi_pct: null }),
    pick({ estado: "PENDIENTE", roi_pct: null }),
  ];
  const code = CORE + `\n\naggregatePicks(${JSON.stringify(records)});`;
  const s = runInSandbox(code);
  // win rate = 2G / (2G + 1P) = 66.7%, NUNCA sobre los 6 totales
  assert.strictEqual(s.win_rate_pct, 66.7);
});

test("aggregatePicks: un pick pendiente nunca cuenta como resultado liquidado", () => {
  const records = [pick({ estado: "PENDIENTE", roi_pct: null })];
  const code = CORE + `\n\naggregatePicks(${JSON.stringify(records)});`;
  const s = runInSandbox(code);
  assert.strictEqual(s.ganados, 0);
  assert.strictEqual(s.perdidos, 0);
  assert.strictEqual(s.anulados, 0);
  assert.strictEqual(s.pendientes, 1);
  assert.strictEqual(s.win_rate_pct, null);
  assert.strictEqual(s.roi_pct, null);
});

test("aggregatePicks: sin registros no rompe (nulls, no NaN)", () => {
  const code = CORE + `\n\naggregatePicks([]);`;
  const s = runInSandbox(code);
  assert.strictEqual(s.total, 0);
  assert.strictEqual(s.win_rate_pct, null);
  assert.strictEqual(s.roi_pct, null);
  assert.strictEqual(s.ev_medio_pct, null);
});

test("aggregatePicks GANADO/PERDIDO se cuentan correctamente", () => {
  const records = [
    pick({ estado: "GANADO", roi_pct: 50 }),
    pick({ estado: "PERDIDO", roi_pct: -100 }),
    pick({ estado: "PERDIDO", roi_pct: -100 }),
  ];
  const code = CORE + `\n\naggregatePicks(${JSON.stringify(records)});`;
  const s = runInSandbox(code);
  assert.strictEqual(s.ganados, 1);
  assert.strictEqual(s.perdidos, 2);
});

// ---------------------------------------------------------------------
// pickMatchesDateFilter -- filtro de fecha del Historico (distinto del de
// Picks activos: aqui HOY/AYER/ULT7/ULT30/ESTEMES/TODO/FECHA)
// ---------------------------------------------------------------------

function matchesDate(dateFilter, specificDate, kickoffOffsetDays) {
  const code = CORE + `\n\npickMatchesDateFilter(${JSON.stringify(pick({ kickoff_utc: kickoffDaysFromNow(kickoffOffsetDays) }))}, ${JSON.stringify(dateFilter)}, ${JSON.stringify(specificDate)});`;
  return runInSandbox(code);
}

test("filtro Hoy solo deja pasar kickoff de hoy", () => {
  assert.strictEqual(matchesDate("HOY", null, 0), true);
  assert.strictEqual(matchesDate("HOY", null, -1), false);
  assert.strictEqual(matchesDate("HOY", null, 1), false);
});

test("filtro Ultimos 7 dias cubre hoy hasta -6, no mas alla, no futuro", () => {
  assert.strictEqual(matchesDate("ULT7", null, 0), true);
  assert.strictEqual(matchesDate("ULT7", null, -6), true);
  assert.strictEqual(matchesDate("ULT7", null, -7), false);
  assert.strictEqual(matchesDate("ULT7", null, 1), false);
});

test("filtro Todo no filtra nada", () => {
  assert.strictEqual(matchesDate("TODO", null, -400), true);
  assert.strictEqual(matchesDate("TODO", null, 400), true);
});

// ---------------------------------------------------------------------
// Combinacion mercado + fecha (pickMatchesHistFilters)
// ---------------------------------------------------------------------

test("combinacion mercado + fecha: ambos deben cumplirse", () => {
  const code = CORE + `
  let picksHistMarketFilter = "BTTS";
  let picksHistDateFilter = "HOY";
  let picksHistSpecificDate = null;
  ${extractFunction("pickMatchesHistFilters")}
  const p = ${JSON.stringify(pick({ market: "BTTS", kickoff_utc: kickoffDaysFromNow(0) }))};
  const results = {
    ok: pickMatchesHistFilters(p),
    wrongMarket: pickMatchesHistFilters(Object.assign({}, p, { market: "1X2_FT" })),
    wrongDate: pickMatchesHistFilters(Object.assign({}, p, { kickoff_utc: "${kickoffDaysFromNow(-10)}" })),
  };
  results;
  `;
  const r = runInSandbox(code);
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.wrongMarket, false);
  assert.strictEqual(r.wrongDate, false);
});

// ---------------------------------------------------------------------
// Filtros por los 4 mercados (via pickMatchesHistFilters, market-only)
// ---------------------------------------------------------------------

["1X2_FT", "OU25_GOALS_FT", "HANDICAP_FT", "BTTS"].forEach(mkt => {
  test(`filtro de mercado ${mkt} deja pasar solo ese mercado`, () => {
    const code = `
    ${extractConst("PICKS_MARKET_LABELS")}
    let picksHistMarketFilter = ${JSON.stringify(mkt)};
    let picksHistDateFilter = "TODO";
    let picksHistSpecificDate = null;
    ${CORE}
    ${extractFunction("pickMatchesHistFilters")}
    const results = {
      same: pickMatchesHistFilters(${JSON.stringify(pick({ market: mkt }))}),
      other: pickMatchesHistFilters(${JSON.stringify(pick({ market: mkt === "BTTS" ? "1X2_FT" : "BTTS" }))}),
    };
    results;
    `;
    const r = runInSandbox(code);
    assert.strictEqual(r.same, true);
    assert.strictEqual(r.other, false);
  });
});

// ---------------------------------------------------------------------
// Render: "Resultados de hoy" -- mensaje exacto, nunca muestra pendientes
// ---------------------------------------------------------------------

test("renderPicksAtlasToday usa el mensaje exacto pedido y filtra por pickIsSettled", () => {
  const rSrc = extractFunction("renderPicksAtlasToday");
  assert.ok(rSrc.includes("No hay picks liquidados hoy."), "debe usar el texto exacto pedido");
  assert.ok(rSrc.includes("pickIsSettled"), "debe excluir PENDIENTES via pickIsSettled");
});

test("renderPicksByMarket recorre los 4 mercados fijos, sin depender del filtro de mercado", () => {
  const rSrc = extractFunction("renderPicksByMarket");
  assert.ok(rSrc.includes("PICKS_MARKET_ORDER"), "debe iterar siempre los 4 mercados");
  assert.ok(!/picksHistMarketFilter/.test(rSrc), "el filtro de MERCADO no debe afectar esta seccion");
  assert.ok(/picksHistDateFilter/.test(rSrc), "el filtro de FECHA si debe afectar esta seccion");
});

test("renderPicksFilteredSummary responde a mercado + fecha combinados", () => {
  const rSrc = extractFunction("renderPicksFilteredSummary");
  assert.ok(/pickMatchesHistFilters/.test(rSrc), "debe usar el filtro combinado (mercado + fecha)");
});

test("renderPicksHistList ordena por kickoff_utc descendente (mas reciente primero)", () => {
  const rSrc = extractFunction("renderPicksHistList");
  assert.ok(/sort\(\(a, b\) => new Date\(b\.kickoff_utc\) - new Date\(a\.kickoff_utc\)\)/.test(rSrc));
});

test("picksPerformanceHtml (Objetivo 1) sigue sin depender de ningun filtro nuevo", () => {
  const perfSrc = extractFunction("picksPerformanceHtml");
  assert.ok(!/picksHistMarketFilter|picksHistDateFilter|picksHistSpecificDate/.test(perfSrc),
    "la card de Rentabilidad historica (Objetivo 1) nunca debe leer el estado de los filtros del historico");
});

// ---------------------------------------------------------------------
// Consistencia (Objetivo 7/8): aggregatePicks sin filtros == performance_summary()
// ---------------------------------------------------------------------

test("aggregatePicks(history completo) coincide EXACTO con PICKS_ATLAS_DATA.performance", () => {
  const dataSrc = extractDataConst("PICKS_ATLAS_DATA");
  const code = CORE + "\n\n" + dataSrc + "\n\n" + `
  const agg = aggregatePicks(PICKS_ATLAS_DATA.history);
  const perf = PICKS_ATLAS_DATA.performance;
  ({ agg, perf });
  `;
  const { agg, perf } = runInSandbox(code);
  assert.strictEqual(agg.total, perf.total);
  assert.strictEqual(agg.ganados, perf.ganados);
  assert.strictEqual(agg.perdidos, perf.perdidos);
  assert.strictEqual(agg.anulados, perf.anulados);
  assert.strictEqual(agg.pendientes, perf.pendientes);
  assert.strictEqual(agg.win_rate_pct, perf.win_rate_pct);
  assert.strictEqual(agg.roi_pct, perf.roi_pct);
  assert.strictEqual(agg.yield_pct, perf.yield_pct);
  assert.strictEqual(agg.ev_medio_pct, perf.ev_medio_pct);
});

test("PICKS_ATLAS_DATA.history tiene exactamente el mismo total que .performance (nada se pierde/duplica)", () => {
  const dataSrc = extractDataConst("PICKS_ATLAS_DATA");
  const code = dataSrc + `\n\n({ historyLen: PICKS_ATLAS_DATA.history.length, perfTotal: PICKS_ATLAS_DATA.performance.total });`;
  const { historyLen, perfTotal } = runInSandbox(code);
  assert.strictEqual(historyLen, perfTotal);
});

console.log(`\n${passed} test(s) OK` + (process.exitCode ? " -- HAY FALLAS ARRIBA" : ""));
