import {API_BASE_URL} from "./config.js";
import {apiBase, parseScenario, validateSchedule, requestJSON, MAX_BODY_BYTES} from "./core.mjs";

const $ = id => document.getElementById(id);
const number = value => new Intl.NumberFormat("en-US", {maximumFractionDigits: 2}).format(value);
let samples = [];
let result = null;
let busy = false;

function status(id, text, kind = "") {
  $(id).textContent = text;
  $(id).dataset.kind = kind;
}

function clearResult() {
  result = null;
  $("result-content").hidden = true;
  $("empty-state").hidden = false;
  $("download-button").disabled = true;
}

function updateButtons() {
  $("run-button").disabled = busy || !$("quota-consent").checked || !$("scenario-json").value.trim();
  for (const id of ["api-base", "health-button", "scenario-json", "import-file", "quota-consent"]) $(id).disabled = busy;
  $("sample").disabled = busy || !samples.length;
  $("load-sample").disabled = busy || !samples.length;
  $("download-button").disabled = busy || !result;
}

function base() {
  const value = apiBase($("api-base").value, window.location.origin);
  if (window.location.protocol === "https:" && value.startsWith("http:")) throw new Error("An HTTPS dashboard requires an HTTPS API (no mixed content).");
  $("docs-link").href = value + "/docs";
  try { localStorage.setItem("voltpilot-api-origin", $("api-base").value.trim()); } catch { /* Storage is optional. */ }
  return value;
}

function svgNode(tag, attributes) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  return node;
}

function renderChart(hours) {
  const svg = $("energy-chart");
  svg.replaceChildren();
  const series = [["grid_kwh", "series-grid"], ["solar_used_kwh", "series-solar"], ["battery_energy_after_kwh", "series-battery"]];
  const max = Math.max(1, ...hours.flatMap(hour => series.map(([key]) => hour[key])));
  for (let i = 0; i <= 4; i++) {
    const y = 15 + i * 48;
    svg.append(svgNode("line", {x1: 48, x2: 683, y1: y, y2: y, class: "grid-line"}));
    const text = svgNode("text", {x: 40, y: y + 4, "text-anchor": "end"});
    text.textContent = number(max * (1 - i / 4));
    svg.append(text);
  }
  for (const hour of [0, 6, 12, 18, 23]) {
    const text = svgNode("text", {x: 48 + hour / 23 * 635, y: 230, "text-anchor": "middle"});
    text.textContent = String(hour).padStart(2, "0");
    svg.append(text);
  }
  for (const [key, className] of series) {
    svg.append(svgNode("polyline", {points: hours.map((hour, i) => `${48 + i / 23 * 635},${207 - hour[key] / max * 192}`).join(" "), class: `series ${className}`}));
  }
}

function render(schedule, elapsed, endpoint) {
  $("metric-cost").textContent = number(schedule.total_cost_bdt);
  $("metric-grid").textContent = number(schedule.total_grid_kwh);
  $("metric-peak").textContent = number(schedule.peak_grid_kwh);
  $("result-context").textContent = `${schedule.scenario_id} · ${elapsed.toFixed(2)}s · ${endpoint}`;
  $("plan-summary").textContent = schedule.plan_summary;
  $("raw-response").textContent = JSON.stringify(schedule, null, 2);
  $("directives").replaceChildren();
  for (const directive of schedule.directive_interpretation) {
    const item = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = directive.directive_type.replaceAll("_", " ");
    const adjustment = document.createElement("code");
    adjustment.textContent = JSON.stringify(directive.structured_adjustment);
    const description = document.createElement("span");
    description.textContent = directive.explanation;
    item.append(title, adjustment, description);
    $("directives").append(item);
  }
  $("hourly-plan").replaceChildren();
  for (const hour of schedule.hourly_plan) {
    const row = document.createElement("tr");
    const delta = hour.battery_action === "discharge" ? -hour.battery_kwh : hour.battery_kwh;
    for (const [index, value] of [String(hour.hour).padStart(2, "0") + ":00", number(hour.grid_kwh), number(hour.solar_used_kwh), hour.battery_action, number(delta), number(hour.battery_energy_after_kwh)].entries()) {
      const cell = document.createElement("td");
      cell.textContent = value;
      if (index === 3) cell.dataset.action = hour.battery_action;
      row.append(cell);
    }
    $("hourly-plan").append(row);
  }
  renderChart(schedule.hourly_plan);
  result = schedule;
  $("empty-state").hidden = true;
  $("result-content").hidden = false;
}

function loadSample() {
  const sample = samples[Number($("sample").value)];
  if (!sample) return;
  $("scenario-json").value = JSON.stringify(sample.input, null, 2);
  clearResult();
  status("run-status", `${sample.id} loaded. No model call sent.`);
  updateButtons();
}

$("load-sample").addEventListener("click", loadSample);
$("quota-consent").addEventListener("change", updateButtons);
$("scenario-json").addEventListener("input", () => { clearResult(); status("run-status", "Input changed. Run to obtain a new result."); updateButtons(); });
$("api-base").addEventListener("input", () => { clearResult(); status("health-status", "Endpoint changed; not checked."); $("docs-link").removeAttribute("href"); updateButtons(); });
$("import-file").addEventListener("change", async event => {
  const file = event.target.files[0];
  if (!file || busy) return;
  busy = true;
  clearResult();
  updateButtons();
  try {
    if (file.size > MAX_BODY_BYTES) throw new Error("File exceeds 1 MiB.");
    const scenario = parseScenario(await file.text());
    $("scenario-json").value = JSON.stringify(scenario, null, 2);
    status("run-status", "Scenario imported. No model call sent.");
  } catch (error) { status("run-status", error.message, "error"); }
  finally { busy = false; event.target.value = ""; updateButtons(); }
});

$("health-button").addEventListener("click", async () => {
  if (busy) return;
  busy = true;
  updateButtons();
  status("health-status", "Checking local API configuration…");
  try {
    const response = await requestJSON(base(), "/health", undefined, 5000);
    if (response.status !== "ok") throw new Error("Unexpected health response.");
    status("health-status", "API configured · provider access and quota still require a live scenario test.", "success");
  } catch (error) { status("health-status", error.message, "error"); }
  finally { busy = false; updateButtons(); }
});

$("run-button").addEventListener("click", async () => {
  if (busy || !$("quota-consent").checked) return;
  clearResult();
  busy = true;
  updateButtons();
  try {
    const scenario = parseScenario($("scenario-json").value);
    const endpoint = base();
    const start = performance.now();
    status("run-status", "Interpreting notes and optimizing… one scenario, no automatic browser retry.");
    const schedule = validateSchedule(await requestJSON(endpoint, "/optimize-energy", scenario), scenario);
    render(schedule, (performance.now() - start) / 1000, endpoint);
    status("run-status", "Schedule received. Review directive meanings before trusting the plan.", "success");
  } catch (error) { clearResult(); status("run-status", error.message, "error"); }
  finally { busy = false; updateButtons(); }
});

$("download-button").addEventListener("click", () => {
  if (!result || busy) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], {type: "application/json"}));
  const link = document.createElement("a");
  link.href = url;
  link.download = "voltpilot-schedule.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

async function initialize() {
  let initial = API_BASE_URL;
  try { initial = localStorage.getItem("voltpilot-api-origin") ?? initial; } catch { /* Storage is optional. */ }
  $("api-base").value = initial;
  try { $("docs-link").href = apiBase(initial, window.location.origin) + "/docs"; } catch { $("docs-link").removeAttribute("href"); }
  try {
    const response = await fetch("/assets/samples.json", {credentials: "omit", redirect: "error", cache: "no-cache"});
    if (!response.ok) throw new Error("Samples unavailable");
    samples = await response.json();
    if (!Array.isArray(samples) || !samples.length) throw new Error("Invalid sample data");
    for (const sample of samples) parseScenario(JSON.stringify(sample.input));
    $("sample").replaceChildren(...samples.map((sample, index) => {
      const option = document.createElement("option");
      option.value = index;
      option.textContent = `${sample.id} · ${sample.label}`;
      return option;
    }));
    // Never overwrite an import or user typing that happened while samples loaded.
    if (!$("scenario-json").value && !busy) loadSample();
  } catch {
    samples = [];
    status("run-status", "Sample loading failed. You can still import or paste a scenario.", "error");
  }
  updateButtons();
}

initialize();