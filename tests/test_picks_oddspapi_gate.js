// -*- coding: utf-8 -*-
// Building:     ATLAS_LAB_MOCKUP (Edificio 5)
// Type:         Test
// Status:       Produccion
//
// Regresion del fix 2026-08-16: la pestaña Picks (tabPicksPre) quedaba
// "bloqueada" aunque OddsPapi ya hubiera resuelto la cuota de 1X2/BTTS/Goles,
// porque el gate (liveTabGateStatus) solo miraba localStorage (cuota
// tipeada a mano), nunca ODDSPAPI_DATA. Este archivo prueba, sin depender
// del DOM (las funciones bajo prueba son puras -- ver comentario en
// index.html junto a effectiveOdds()), que:
//   1. Sin ninguna cuota (ni manual ni OddsPapi) el gate sigue bloqueado.
//   2. Cuota manual sigue desbloqueando, como siempre.
//   3. Cuota SOLO de OddsPapi desbloquea (el bug reportado).
//   4. Una mezcla de OddsPapi + manual desbloquea.
//   5. Si existen las dos para el mismo mercado, la manual gana siempre.
//   6. Corners (mercado no automatizado) nunca bloquea el resto de Picks,
//      pero su propio pick sigue exigiendo cuota manual (sin cambios).
// Corre con: node atlas_lab_mockup/tests/test_picks_oddspapi_gate.js
// Sale con exit code 0 si todo pasa, 1 si algo falla (mismo patron que
// node --check ya usado por run_daily.ps1/run_weekly.ps1).
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const INDEX_HTML = path.join(__dirname, "..", "index.html");
const src = fs.readFileSync(INDEX_HTML, "utf-8");

// ---- Extractores robustos a cambios de numero de linea (no dependen de
// offsets fijos, escanean el codigo real de index.html por nombre). ----
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
function extractRealDataConst(name) {
  // POCKET_DATA/HIST_DATA/ODDSPAPI_DATA se hornean como UNA linea de JSON
  // minificado (ver 03_export_lean_js.py) -- extraccion directa por regex
  // de linea completa, sin necesidad de un parser JS.
  const re = new RegExp("^const " + name + " = (.*);$", "m");
  const m = src.match(re);
  if (!m) return null;
  return JSON.parse(m[1]);
}

// ---- Sandbox minimo: SOLO las funciones puras bajo prueba, con
// localStorage/ODDSPAPI_DATA controlados por cada test. Sin document/window
// -- estas funciones no tocan el DOM (ver comentario junto a effectiveOdds
// en index.html: tabPicksPre corre ANTES de que exista el DOM de las otras
// pestañas, por eso lee ODDSPAPI_DATA directo en vez de inputs). ----
function buildSandbox(oddspapiData) {
  const store = new Map();
  const localStorage = {
    getItem: k => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: k => store.delete(k),
  };
  const sandbox = { localStorage, ODDSPAPI_DATA: oddspapiData || {}, console };
  vm.createContext(sandbox);
  const code = [
    extractConst("ATLAS_ODDS_LS_PREFIX"),
    extractFunction("atlasOddsKey"),
    extractFunction("readSavedOdds"),
    extractFunction("oddsPapiSelectionPrice"),
    extractFunction("effectiveOdds"),
    extractFunction("liveTabRequiredKeys"),
    extractFunction("liveTabGateStatus"),
    extractFunction("evPct"),
    extractFunction("oddsBadgeTime"),
    extractFunction("livePickCardHtml"),
  ].join("\n\n");
  vm.runInContext(code, sandbox);
  return sandbox;
}

function fakeMatch(id, home, away) {
  return { id, home, away };
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

// 1) Picks bloqueado sin cuotas (ni manual ni OddsPapi)
test("Picks bloqueado sin cuotas", () => {
  const sb = buildSandbox({});
  const m = fakeMatch("test-sin-cuotas", "Local", "Visita");
  const gate = sb.liveTabGateStatus(m.id, m);
  assert.strictEqual(gate.ok, false);
  assert.ok(gate.missing.length > 0);
});

// 2) Picks desbloqueado con cuota manual (comportamiento historico, sin
// tocar OddsPapi para nada)
test("Picks desbloqueado con cuota manual", () => {
  const sb = buildSandbox({});
  const m = fakeMatch("test-manual", "Local", "Visita");
  sb.localStorage.setItem(sb.atlasOddsKey(m.id, "m:Gana " + m.home), "2.10");
  sb.localStorage.setItem(sb.atlasOddsKey(m.id, "m:Empate"), "3.20");
  sb.localStorage.setItem(sb.atlasOddsKey(m.id, "m:Gana " + m.away), "3.40");
  sb.localStorage.setItem(sb.atlasOddsKey(m.id, "m:BTTS (Ambos anotan) — dato histórico, no modelo"), "1.80");
  sb.localStorage.setItem(sb.atlasOddsKey(m.id, "p:total|goals|0|Goles"), "1.90");
  const gate = sb.liveTabGateStatus(m.id, m);
  assert.strictEqual(gate.ok, true);
  assert.strictEqual(gate.missing.length, 0);
});

// 3) Picks desbloqueado con cuota SOLO de OddsPapi (el bug reportado: antes
// esto quedaba bloqueado porque el gate solo miraba localStorage)
test("Picks desbloqueado con cuota OddsPapi", () => {
  const odds = {
    "1X2_FT": { bk: "Pinnacle", sel: { home: { p: 2.1, t: "2026-08-16T00:00:00Z" }, draw: { p: 3.2, t: "2026-08-16T00:00:00Z" }, away: { p: 3.4, t: "2026-08-16T00:00:00Z" } } },
    "BTTS": { bk: "Pinnacle", sel: { yes: { p: 1.8, t: "2026-08-16T00:00:00Z" } } },
    "OU25_GOALS_FT": { bk: "Pinnacle", sel: { over: { p: 1.9, t: "2026-08-16T00:00:00Z" } } },
  };
  const sb = buildSandbox({ "test-oddspapi": odds });
  const m = fakeMatch("test-oddspapi", "Local", "Visita");
  const gate = sb.liveTabGateStatus(m.id, m);
  assert.strictEqual(gate.ok, true);
  assert.strictEqual(gate.missing.length, 0);
  // effectiveOdds debe reportar la fuente real (para el badge bookmaker/hora)
  const eff = sb.effectiveOdds(m.id, "m:Gana " + m.home, () => sb.oddsPapiSelectionPrice(m.id, "1X2_FT", "home"));
  assert.strictEqual(eff.source, "oddspapi");
  assert.strictEqual(eff.price, 2.1);
  assert.strictEqual(eff.bookmaker, "Pinnacle");
});

// 4) Mezcla: BTTS manual, 1X2 y Goles automaticos de OddsPapi
test("Picks desbloqueado con mezcla OddsPapi + manual", () => {
  const odds = {
    "1X2_FT": { bk: "Pinnacle", sel: { home: { p: 2.1, t: "T" }, draw: { p: 3.2, t: "T" }, away: { p: 3.4, t: "T" } } },
    "OU25_GOALS_FT": { bk: "Pinnacle", sel: { over: { p: 1.9, t: "T" } } },
  };
  const sb = buildSandbox({ "test-mezcla": odds });
  const m = fakeMatch("test-mezcla", "Local", "Visita");
  sb.localStorage.setItem(sb.atlasOddsKey(m.id, "m:BTTS (Ambos anotan) — dato histórico, no modelo"), "1.75");
  const gate = sb.liveTabGateStatus(m.id, m);
  assert.strictEqual(gate.ok, true);
  const bttsEff = sb.effectiveOdds(m.id, "m:BTTS (Ambos anotan) — dato histórico, no modelo",
    () => sb.oddsPapiSelectionPrice(m.id, "BTTS", "yes"));
  const golesEff = sb.effectiveOdds(m.id, "p:total|goals|0|Goles",
    () => sb.oddsPapiSelectionPrice(m.id, "OU25_GOALS_FT", "over"));
  assert.strictEqual(bttsEff.source, "manual");
  assert.strictEqual(bttsEff.price, 1.75);
  assert.strictEqual(golesEff.source, "oddspapi");
  assert.strictEqual(golesEff.price, 1.9);
});

// 5) Prioridad: si existen las dos cuotas para el MISMO mercado, la manual
// siempre gana (nunca se pisa una eleccion explicita del Director)
test("Prioridad de cuota manual sobre automática", () => {
  const odds = { "OU25_GOALS_FT": { bk: "Pinnacle", sel: { over: { p: 1.90, t: "T" } } } };
  const sb = buildSandbox({ "test-prioridad": odds });
  const m = fakeMatch("test-prioridad", "Local", "Visita");
  sb.localStorage.setItem(sb.atlasOddsKey(m.id, "p:total|goals|0|Goles"), "2.35"); // distinta de la de OddsPapi (1.90)
  const eff = sb.effectiveOdds(m.id, "p:total|goals|0|Goles", () => sb.oddsPapiSelectionPrice(m.id, "OU25_GOALS_FT", "over"));
  assert.strictEqual(eff.source, "manual");
  assert.strictEqual(eff.price, 2.35);
});

// 6) Corners (mercado NO automatizado) nunca bloquea el resto de Picks --
// no debe aparecer en absoluto en la lista de mercados requeridos del gate.
test("Corners no bloquea Picks (mercado manual, sin cobertura OddsPapi)", () => {
  const sb = buildSandbox({});
  const m = fakeMatch("test-corners", "Local", "Visita");
  const required = sb.liveTabRequiredKeys(m);
  assert.ok(!required.some(r => /corner/i.test(r.key) || /corner/i.test(r.label)),
    "Corners no debe estar en la lista de mercados que bloquean Picks");
  assert.strictEqual(required.length, 5); // 1X2 x3 + BTTS + Goles
});

// 7) livePickCardHtml conserva bookmaker/hora cuando la fuente es OddsPapi
// (nunca "Cuota Betano" generico para una cuota que no es manual)
test("livePickCardHtml conserva bookmaker/hora de OddsPapi", () => {
  const sb = buildSandbox({});
  const fuente = { source: "oddspapi", bookmaker: "Pinnacle", timestamp: "2026-08-16T02:37:22.615Z" };
  const html = sb.livePickCardHtml("BTTS \"Sí\"", 0.65, 1.82, "razon de prueba", fuente);
  assert.ok(html.includes("OddsPapi"), "debe mencionar OddsPapi");
  assert.ok(html.includes("Pinnacle"), "debe conservar el bookmaker real");
  assert.ok(!html.includes("Cuota Betano"), "no debe etiquetar una cuota OddsPapi como Betano");
  // EV% = (prob * cuota - 1) * 100 = (0.65 * 1.82 - 1) * 100 = 18.3 -- misma
  // formula existente, sin cambios (evPct no fue tocada por este fix).
  assert.ok(html.includes("+18.3% EV"), "debe calcular el EV real con la formula existente sin cambios");
});

// 8) Verificacion con datos REALES del partido de las capturas (Chapecoense
// vs Bahia): usa el ODDSPAPI_DATA real horneado en el index.html publicado
// hoy (2026-08-16) -- si el partido sigue existiendo y OddsPapi lo sigue
// cubriendo, el gate debe estar desbloqueado. Se salta (no falla la suite)
// si el fixture ya roto del dataset diario -- este archivo cambia cada dia.
test("Chapecoense vs Bahia (partido real de las capturas) -- Picks desbloqueado", () => {
  const realOdds = extractRealDataConst("ODDSPAPI_DATA");
  const matchId = "chapecoense-bahia-15235427";
  if (!realOdds || !realOdds[matchId]) {
    console.log("  (saltado -- el dataset diario de hoy ya no incluye este fixture, esperado con el tiempo)");
    return;
  }
  const sb = buildSandbox(realOdds);
  const m = fakeMatch(matchId, "Chapecoense", "Bahia");
  const gate = sb.liveTabGateStatus(m.id, m);
  assert.strictEqual(gate.ok, true, "Chapecoense vs Bahia debe desbloquear Picks con la cobertura real de OddsPapi de hoy");
});

// ---------------------------------------------------------------------
// Regresion 2026-08-16 -- bug real reportado (Colo-Colo vs O'Higgins):
// la pestaña "Reporte" (la primera que se ve al abrir un partido) tiene
// una tabla-resumen "Total del Partido" con SUS PROPIAS filas de 1X2 y
// Goles Total ("1X2: Gana X", "1X2: Empate", "Over 2.5 Goles"), generadas
// tambien con marketRowHtml() -- pero antes de este fix esas filas
// guardaban la cuota bajo una clave DISTINTA ("m:1X2: Gana X") a la que
// liveTabGateStatus() revisa ("m:Gana X", la de la pestaña Goles/1X2).
// Un Director que tipeaba la cuota manual en la fila de Reporte (la
// primera que ve) veia el EV% calcularse ahi mismo -- pero Picks seguia
// diciendo "pestaña bloqueada", porque el gate miraba una clave que
// nunca se llenaba. Fix: marketRowHtml(label, prob, quality, autoOdds,
// mktKeyOverride) -- mktKeyOverride fuerza la MISMA clave que la fila
// canonica sin cambiar el texto visible.
// ---------------------------------------------------------------------

function buildMarketRowSandbox() {
  const sandbox = { console };
  vm.createContext(sandbox);
  const code = [
    extractFunction("escAttr"),
    extractFunction("marketRowHtml"),
  ].join("\n\n");
  vm.runInContext(code, sandbox);
  return sandbox;
}

test("marketRowHtml sin override sigue usando 'm:' + label (comportamiento default sin cambios)", () => {
  const sb = buildMarketRowSandbox();
  const html = sb.marketRowHtml("Gana Local", 0.5, "");
  assert.ok(html.includes('data-mkt-key="m:Gana Local"'));
});

test("marketRowHtml con mktKeyOverride usa la clave del override, no la del label (fix del bug real)", () => {
  const sb = buildMarketRowSandbox();
  // mismo caso real: texto visible "1X2: Gana Colo-Colo", clave
  // compartida con la fila canonica "m:Gana Colo-Colo".
  const html = sb.marketRowHtml("1X2: Gana Colo-Colo", 0.5, "", undefined, "m:Gana Colo-Colo");
  assert.ok(html.includes('data-mkt-key="m:Gana Colo-Colo"'), "debe guardar bajo la clave canonica");
  assert.ok(!html.includes('data-mkt-key="m:1X2: Gana Colo-Colo"'), "nunca debe crear una clave duplicada nueva");
  assert.ok(html.includes(">1X2: Gana Colo-Colo<"), "el texto visible no cambia, solo la clave de guardado");
});

test("wiring: tabReporte usa las MISMAS claves literales que liveTabRequiredKeys() para 1X2 y Goles Total", () => {
  // Guarda de regresion: si alguien vuelve a tocar tabReporte() o
  // liveTabRequiredKeys() por separado, este test detecta que las claves
  // se desincronizaron de nuevo, sin depender del DOM ni de datos reales.
  const tabReporteSrc = extractFunction("tabReporte");
  assert.ok(tabReporteSrc.includes('"m:Gana " + m.home'), "1X2 Gana Local debe compartir clave con Goles/1X2");
  assert.ok(tabReporteSrc.includes('"m:Empate"'), "1X2 Empate debe compartir clave con Goles/1X2");
  assert.ok(tabReporteSrc.includes('"m:Gana " + m.away'), "1X2 Gana Visita debe compartir clave con Goles/1X2");
  assert.ok(tabReporteSrc.includes('"p:total|goals|0|Goles"'), "Goles Total debe compartir clave con Goles/1X2");
});

test("escenario real: cuota manual tipeada en la fila 'espejo' de Reporte desbloquea Picks", () => {
  // Reproduce el bug de punta a punta usando el MISMO liveTabGateStatus()
  // real -- simplemente escribe en localStorage bajo la clave que
  // marketRowHtml() ahora genera para la fila de Reporte (con override),
  // exactamente como haria atlasSaveOdds() al tipear ahi.
  const sb = buildSandbox({});
  const m = fakeMatch("colo-colo-ohiggins-15353093", "Colo-Colo", "O'Higgins");
  sb.localStorage.setItem(sb.atlasOddsKey(m.id, "m:Gana " + m.home), "1.85");
  sb.localStorage.setItem(sb.atlasOddsKey(m.id, "m:Empate"), "3.40");
  sb.localStorage.setItem(sb.atlasOddsKey(m.id, "m:Gana " + m.away), "4.20");
  sb.localStorage.setItem(sb.atlasOddsKey(m.id, "p:total|goals|0|Goles"), "1.95");
  sb.localStorage.setItem(sb.atlasOddsKey(m.id, "m:BTTS (Ambos anotan) — dato histórico, no modelo"), "1.90");
  const gate = sb.liveTabGateStatus(m.id, m);
  assert.strictEqual(gate.ok, true, "las 5 cuotas manuales (tipeadas en cualquier pestaña) deben desbloquear Picks");
  assert.strictEqual(gate.missing.length, 0);
});

test("escenario E: falta una sola cuota real -> Picks permanece bloqueada", () => {
  const sb = buildSandbox({});
  const m = fakeMatch("test-falta-una", "Local", "Visita");
  sb.localStorage.setItem(sb.atlasOddsKey(m.id, "m:Gana " + m.home), "1.85");
  sb.localStorage.setItem(sb.atlasOddsKey(m.id, "m:Empate"), "3.40");
  sb.localStorage.setItem(sb.atlasOddsKey(m.id, "m:Gana " + m.away), "4.20");
  sb.localStorage.setItem(sb.atlasOddsKey(m.id, "m:BTTS (Ambos anotan) — dato histórico, no modelo"), "1.90");
  // falta Goles Total a proposito
  const gate = sb.liveTabGateStatus(m.id, m);
  assert.strictEqual(gate.ok, false);
  assert.strictEqual(gate.missing.length, 1);
  assert.strictEqual(gate.missing[0], "Goles Total (Over/Under, por defecto 2.5)");
});

console.log(`\n${passed} test(s) OK` + (process.exitCode ? " -- HAY FALLAS ARRIBA" : ""));
