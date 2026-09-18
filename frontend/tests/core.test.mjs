import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {apiBase, parseScenario, validateSchedule, requestJSON} from "../assets/core.mjs";

const cases = JSON.parse(readFileSync(new URL("../../BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json", import.meta.url), "utf8").replace(/^\uFEFF/, "")).cases;

test("API origins are explicit and credential-free", () => {
  assert.equal(apiBase("", "https://api.example"), "https://api.example");
  assert.equal(apiBase("", "http://35.222.65.204"), "http://35.222.65.204");
  assert.equal(apiBase(" https://api.example/ ", "https://page.example"), "https://api.example");
  assert.equal(apiBase("http://localhost:18080", "https://page.example"), "http://localhost:18080");
  assert.equal(apiBase("http://[::1]:18080", "https://page.example"), "http://[::1]:18080");
  for (const value of ["http://remote.example", "https://user:key@api.example", "https://api.example/path", "https://api.example?key=secret", "https://api.example#secret", "javascript:alert(1)", "https://api.\nexample"]) {
    assert.throws(() => apiBase(value, "https://page.example"));
  }
});

test("Vercel keeps exact judging endpoints on its own origin", () => {
  const config = JSON.parse(readFileSync(new URL("../vercel.json", import.meta.url), "utf8"));
  for (const path of ["/health", "/optimize-energy", "/docs", "/openapi.json"]) {
    assert.ok(config.rewrites.some(rule => rule.source === path && rule.destination === "http://35.222.65.204" + path));
  }
  assert.equal(config.framework, null);
});

test("all public requests and responses pass display validation", () => {
  for (const entry of cases) {
    const scenario = parseScenario(JSON.stringify(entry.input));
    assert.deepEqual(validateSchedule(entry.expected_output, scenario), entry.expected_output);
  }
});

test("malformed requests are rejected before spending", () => {
  for (const text of ["{", "null", "[]", "{}", " ".repeat(1024 * 1024 + 1)]) assert.throws(() => parseScenario(text));
  const mutations = [
    value => value.operator_notes = [], value => value.operator_notes = [" "],
    value => value.hours.pop(), value => value.hours[0].hour = 1,
    value => value.hours[0].demand_kwh = "90", value => value.hours[0].solar_kwh = true,
    value => value.hours[0].solar_kwh = -1, value => value.battery.initial_energy_kwh = 1e10
  ];
  for (const mutate of mutations) {
    const scenario = structuredClone(cases[0].input);
    mutate(scenario);
    assert.throws(() => parseScenario(JSON.stringify(scenario)));
  }
});

test("malformed schedules cannot become displayed results", () => {
  const mutations = [
    value => value.scenario_id = "wrong", value => value.total_cost_bdt = "42",
    value => value.hourly_plan.pop(), value => value.hourly_plan[0].hour = 8,
    value => value.hourly_plan[0].grid_kwh = -1, value => value.hourly_plan[0].battery_kwh = NaN,
    value => value.directive_interpretation = [], value => value.directive_interpretation[0].note_index = 2,
    value => value.directive_interpretation[0].structured_adjustment.factor = 2,
    value => value.directive_interpretation[0].structured_adjustment.hours = [12, 12]
  ];
  for (const mutate of mutations) {
    const schedule = structuredClone(cases[0].expected_output);
    mutate(schedule);
    assert.throws(() => validateSchedule(schedule, cases[0].input));
  }
});

test("client sends JSON once without credentials or redirects", async () => {
  let calls = 0;
  const actual = await requestJSON("https://api.example", "/optimize-energy", cases[0].input, 1000, async (url, options) => {
    calls++;
    assert.equal(url, "https://api.example/optimize-energy");
    assert.equal(options.credentials, "omit");
    assert.equal(options.redirect, "error");
    assert.equal(options.method, "POST");
    assert.deepEqual(JSON.parse(options.body), cases[0].input);
    return new Response(JSON.stringify(cases[0].expected_output), {status: 200});
  });
  assert.equal(calls, 1);
  assert.equal(actual.scenario_id, cases[0].input.scenario_id);
});

test("health is a GET and unconfigured health is not success", async () => {
  await assert.rejects(requestJSON("https://api.example", "/health", undefined, 1000, async (url, options) => {
    assert.equal(options.method, "GET");
    assert.equal(options.body, undefined);
    return new Response('{"status":"not_ready"}', {status: 503});
  }), /not ready/);
});

test("provider errors are sanitized and never automatically retried", async () => {
  let calls = 0;
  await assert.rejects(requestJSON("https://api.example", "/optimize-energy", {}, 1000, async () => {
    calls++;
    return new Response('{"error":{"code":"private-provider-text","secret":"must-not-appear"}}', {status: 500});
  }), error => !error.message.includes("private-provider-text") && !error.message.includes("must-not-appear"));
  assert.equal(calls, 1);
});

test("HTML and network errors fail safely", async () => {
  await assert.rejects(requestJSON("https://api.example", "/health", undefined, 1000,
    async () => new Response("<html>not an API</html>")), /did not return JSON/);
  await assert.rejects(requestJSON("https://api.example", "/health", undefined, 1000,
    async () => { throw new TypeError("fetch failed"); }), /Cannot reach the API/);
});

test("request timeout aborts once without retry", async () => {
  let calls = 0;
  await assert.rejects(requestJSON("https://api.example", "/optimize-energy", {}, 5, async (url, options) => {
    calls++;
    return new Promise((resolve, reject) => options.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))));
  }), /timed out/);
  assert.equal(calls, 1);
});