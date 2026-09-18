// Pure browser-side helpers, also exercised with Node's built-in test runner.
export const MAX_BODY_BYTES = 1024 * 1024;

export function apiBase(value, pageOrigin) {
  const input = value.trim();
  const url = new URL(input || pageOrigin);
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  const sameOrigin = url.origin === new URL(pageOrigin).origin;
  if ((url.protocol !== "https:" && !(url.protocol === "http:" && (local || sameOrigin))) ||
      url.username || url.password || url.search || url.hash || url.pathname !== "/" ||
      /\s/.test(input)) {
    throw new Error("Use a credential-free HTTPS origin, the current origin, or HTTP localhost, without a path.");
  }
  return url.origin;
}

const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
const number = value => typeof value === "number" && Number.isFinite(value);
const energy = value => number(value) && value >= 0;

export function parseScenario(text) {
  if (new TextEncoder().encode(text).length > MAX_BODY_BYTES) throw new Error("Scenario exceeds 1 MiB.");
  let value;
  try { value = JSON.parse(text); } catch { throw new Error("Scenario must be valid JSON."); }
  if (!object(value) || typeof value.scenario_id !== "string" || !Array.isArray(value.operator_notes) ||
      value.operator_notes.length < 1 || value.operator_notes.length > 3 ||
      value.operator_notes.some(note => typeof note !== "string" || !note.trim())) {
    throw new Error("Include scenario_id and 1–3 nonempty operator_notes.");
  }
  const batteryKeys = ["capacity_kwh", "initial_energy_kwh", "minimum_energy_kwh",
    "max_charge_kwh_per_hour", "max_discharge_kwh_per_hour"];
  const battery = value.battery;
  if (!object(battery) || batteryKeys.some(key => !energy(battery[key])) ||
      battery.minimum_energy_kwh > battery.initial_energy_kwh || battery.initial_energy_kwh > battery.capacity_kwh) {
    throw new Error("Battery values must be nonnegative numbers with minimum ≤ initial ≤ capacity.");
  }
  if (!Array.isArray(value.hours) || value.hours.length !== 24 ||
      new Set(value.hours.map(hour => hour?.hour)).size !== 24 || value.hours.some(hour =>
        !object(hour) || !Number.isInteger(hour.hour) || hour.hour < 0 || hour.hour > 23 ||
        !energy(hour.demand_kwh) || !energy(hour.solar_kwh) || !number(hour.tariff_bdt_per_kwh))) {
    throw new Error("Provide exactly hours 0–23 with numeric demand, solar and tariff values.");
  }
  return value;
}

export function validateSchedule(value, scenario) {
  const types = ["solar_reduction", "minimum_battery_reserve", "no_charge_window",
    "no_discharge_window", "max_grid_window", "no_op"];
  if (!object(value) || value.scenario_id !== scenario.scenario_id || !energy(value.total_grid_kwh) ||
      !number(value.total_cost_bdt) || !energy(value.peak_grid_kwh) || typeof value.plan_summary !== "string" ||
      !Array.isArray(value.hourly_plan) || value.hourly_plan.length !== 24 ||
      !Array.isArray(value.directive_interpretation) || value.directive_interpretation.length !== scenario.operator_notes.length) {
    throw new Error("The API returned an invalid schedule. No result is displayed.");
  }
  for (const [index, hour] of value.hourly_plan.entries()) {
    if (!object(hour) || hour.hour !== index || !["grid_kwh", "solar_used_kwh", "battery_kwh", "battery_energy_after_kwh"].every(key => energy(hour[key])) ||
        !["charge", "discharge", "idle"].includes(hour.battery_action) ||
        (hour.battery_action === "idle" ? hour.battery_kwh !== 0 : hour.battery_kwh <= 0)) {
      throw new Error("The API returned malformed hourly data. No result is displayed.");
    }
  }
  for (const [index, directive] of value.directive_interpretation.entries()) {
    if (!object(directive) || directive.note_index !== index || !types.includes(directive.directive_type) ||
        typeof directive.explanation !== "string" || directive.applies !== (directive.directive_type !== "no_op")) {
      throw new Error("The API returned malformed directives. No result is displayed.");
    }
    const adjustment = directive.structured_adjustment;
    if (directive.directive_type === "no_op") {
      if (adjustment !== null) throw new Error("Invalid no-op adjustment.");
    } else if (!object(adjustment) || !Array.isArray(adjustment.hours) || !adjustment.hours.length ||
        adjustment.hours.some((hour, i) => !Number.isInteger(hour) || hour < 0 || hour > 23 || (i > 0 && hour <= adjustment.hours[i - 1])) ||
        (directive.directive_type === "solar_reduction" && (!energy(adjustment.factor) || adjustment.factor > 1)) ||
        (directive.directive_type === "minimum_battery_reserve" && !energy(adjustment.minimum_energy_kwh)) ||
        (directive.directive_type === "max_grid_window" && !energy(adjustment.max_grid_kwh))) {
      throw new Error("The API returned an invalid directive adjustment.");
    }
  }
  return value;
}

const errorMessages = {
  invalid_request: "The API rejected this scenario. Check its fields and numeric values.",
  request_too_large: "The request exceeds the API body limit.",
  model_not_configured: "The backend has no complete model configuration yet.",
  model_access_denied: "The provider rejected the backend credential. Check key permissions privately.",
  model_request_rejected: "The provider rejected the model request. Check model availability.",
  model_unavailable: "The model is unavailable or quota-limited. No automatic browser retry was sent.",
  model_timeout: "The model did not respond within its budget.",
  request_deadline: "The request exceeded the API deadline.",
  service_busy: "All request slots are occupied. Wait before manually retrying.",
  invalid_model_output: "Model output failed validation. No schedule was fabricated.",
  infeasible_schedule: "No schedule satisfies the interpreted constraints. Review the scenario."
};

export async function requestJSON(base, path, body, timeout = 29000, fetcher = globalThis.fetch) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetcher(base + path, {
      method: body === undefined ? "GET" : "POST", credentials: "omit", redirect: "error", cache: "no-store",
      signal: controller.signal,
      ...(body === undefined ? {} : {headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)})
    });
    let data;
    try { data = await response.json(); } catch {
      if (controller.signal.aborted) throw new Error("Request timed out; it may already have used model quota.");
      throw new Error("The endpoint did not return JSON. Check the API URL.");
    }
    if (!response.ok) {
      if (path === "/health" && response.status === 503) throw new Error("API reachable, but model configuration is not ready.");
      throw new Error(errorMessages[data?.error?.code] || `API request failed (HTTP ${response.status}). No result was accepted.`);
    }
    return data;
  } catch (error) {
    if (controller.signal.aborted) throw new Error("Request timed out; it may already have used model quota. No automatic retry was sent.");
    if (error instanceof TypeError) throw new Error("Cannot reach the API. Check HTTPS, the address, and the exact frontend CORS origin.");
    throw error;
  } finally { clearTimeout(timer); }
}