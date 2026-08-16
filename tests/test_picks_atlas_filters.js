// -*- coding: utf-8 -*-
// Building:     ATLAS_LAB_MOCKUP (Edificio 5)
// Type:         Test
// Status:       Produccion
//
// Filtros de "Picks activos" en la pestaña Picks ATLAS (2026-08-16, mejora
// UI puramente visual). Prueba que picksAtlasMatchesFilters() -- la unica
// funcion nueva que decide que tarjetas se muestran -- filtra
// correctamente por mercado y por fecha (usando kickoff_utc, el mismo
// campo que ya existe en el registro, nunca uno inventado), que "Todos"/
// "Todas" no filtra nada, y que la tarjeta de rentabilidad (perf) nunca
// depende de estas variables de filtro. No depende del DOM -- misma
// tecnica de extraccion por nombre que
// atlas_lab_mockup/tests/test_picks_oddspapi_gate.js.
//
// Corre con: node atlas_lab_mockup/tests/test_picks_atlas_filters.js
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

// picksAtlasMatchesFilters() depende de chileDayOffset()/toChileDate()/
// todayChileMidnightUTC()/CHILE_UTC_OFFSET (fecha real del sistema, sin
// mockear Date.now() -- los picks de prueba se generan relativos a "ahora"
// real, igual que _picks_kickoff() en tipster/tests/test_tipster.py).
function runMatchesFilters(marketFilter, dateFilter, specificDate, pick) {
  const code = [
    extractConst("CHILE_UTC_OFFSET"),
    extractFunction("toChileDate"),
    extractFunction("todayChileMidnightUTC"),
    extractFunction("chileDayOffset"),
    `let picksAtlasMarketFilter = ${JSON.stringify(marketFilter)};`,
    `let picksAtlasDateFilter = ${JSON.stringify(dateFilter)};`,
    `let picksAtlasSpecificDate = ${JSON.stringify(specificDate)};`,
    extractFunction("picksAtlasMatchesFilters"),
    `picksAtlasMatchesFilters(${JSON.stringify(pick)});`,
  ].join("\n\n");
  const sandbox = {};
  vm.createContext(sandbox);
  return vm.runInContext(code, sandbox);
}

function kickoffDaysFromNow(days) {
  return new Date(Date.now() + days * 86400000).toISOString().replace(/\.\d+Z$/, "Z");
}

function pick(overrides) {
  return Object.assign({ market: "1X2_FT", kickoff_utc: kickoffDaysFromNow(0), partido: "A vs B" }, overrides);
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

test("mercado ALL no filtra nada", () => {
  assert.strictEqual(runMatchesFilters("ALL", "ALL", null, pick({ market: "BTTS" })), true);
});

test("mercado especifico solo deja pasar ese mercado", () => {
  assert.strictEqual(runMatchesFilters("1X2_FT", "ALL", null, pick({ market: "1X2_FT" })), true);
  assert.strictEqual(runMatchesFilters("1X2_FT", "ALL", null, pick({ market: "BTTS" })), false);
});

test("fecha HOY solo deja pasar kickoff de hoy", () => {
  assert.strictEqual(runMatchesFilters("ALL", "HOY", null, pick({ kickoff_utc: kickoffDaysFromNow(0) })), true);
  assert.strictEqual(runMatchesFilters("ALL", "HOY", null, pick({ kickoff_utc: kickoffDaysFromNow(1) })), false);
  assert.strictEqual(runMatchesFilters("ALL", "HOY", null, pick({ kickoff_utc: kickoffDaysFromNow(-1) })), false);
});

test("fecha MANANA solo deja pasar kickoff de mañana", () => {
  assert.strictEqual(runMatchesFilters("ALL", "MANANA", null, pick({ kickoff_utc: kickoffDaysFromNow(1) })), true);
  assert.strictEqual(runMatchesFilters("ALL", "MANANA", null, pick({ kickoff_utc: kickoffDaysFromNow(0) })), false);
  assert.strictEqual(runMatchesFilters("ALL", "MANANA", null, pick({ kickoff_utc: kickoffDaysFromNow(2) })), false);
});

test("fecha PROX7 cubre hoy hasta +6 dias, no mas alla", () => {
  assert.strictEqual(runMatchesFilters("ALL", "PROX7", null, pick({ kickoff_utc: kickoffDaysFromNow(0) })), true);
  assert.strictEqual(runMatchesFilters("ALL", "PROX7", null, pick({ kickoff_utc: kickoffDaysFromNow(6) })), true);
  assert.strictEqual(runMatchesFilters("ALL", "PROX7", null, pick({ kickoff_utc: kickoffDaysFromNow(7) })), false);
  assert.strictEqual(runMatchesFilters("ALL", "PROX7", null, pick({ kickoff_utc: kickoffDaysFromNow(-1) })), false);
});

test("fecha especifica compara contra la fecha elegida en hora Chile", () => {
  const kickoff = kickoffDaysFromNow(3);
  // la fecha especifica se arma con el MISMO offset de Chile que usa
  // toChileDate() en produccion, para que el test no dependa de en que
  // zona horaria corre la maquina que ejecuta el test.
  const chileMs = Date.now() + 3 * 86400000 + (-4) * 3600 * 1000;
  const d = new Date(chileMs);
  const iso = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
  assert.strictEqual(runMatchesFilters("ALL", "FECHA", iso, pick({ kickoff_utc: kickoff })), true);
  assert.strictEqual(runMatchesFilters("ALL", "FECHA", iso, pick({ kickoff_utc: kickoffDaysFromNow(0) })), false);
});

test("fecha especifica sin elegir todavia no filtra (evita ocultar todo antes de elegir)", () => {
  assert.strictEqual(runMatchesFilters("ALL", "FECHA", null, pick({ kickoff_utc: kickoffDaysFromNow(5) })), true);
});

test("mercado y fecha combinados -- ambos deben cumplirse", () => {
  const p = pick({ market: "BTTS", kickoff_utc: kickoffDaysFromNow(0) });
  assert.strictEqual(runMatchesFilters("BTTS", "HOY", null, p), true);
  assert.strictEqual(runMatchesFilters("1X2_FT", "HOY", null, p), false);
  assert.strictEqual(runMatchesFilters("BTTS", "MANANA", null, p), false);
});

test("la tarjeta de rentabilidad no depende de ninguna variable de filtro", () => {
  const perfSrc = extractFunction("picksPerformanceHtml");
  assert.ok(!/picksAtlasMarketFilter|picksAtlasDateFilter|picksAtlasSpecificDate/.test(perfSrc),
    "picksPerformanceHtml() nunca debe leer el estado de los filtros -- siempre representa TODOS los picks acumulados");
});

test("renderPicksAtlasList muestra el mensaje exacto pedido cuando el filtro no matchea nada", () => {
  const listSrc = extractFunction("renderPicksAtlasList");
  assert.ok(listSrc.includes("No hay picks para este filtro."), "debe usar el texto exacto pedido, sin inventar ni duplicar resultados");
});

console.log(`\n${passed} test(s) OK` + (process.exitCode ? " -- HAY FALLAS ARRIBA" : ""));
