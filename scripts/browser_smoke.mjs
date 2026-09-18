// Real Chromium smoke test using only Node built-ins and the browser's DevTools protocol.
// Intercept optimization requests with explicitly TEST-ONLY fixtures; never spend model quota.
import {spawn} from "node:child_process";
import {mkdtemp, rm, readFile, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import assert from "node:assert/strict";

const [browser, base = "http://127.0.0.1:18081", screenshot] = process.argv.slice(2);
if (!browser) throw new Error("Usage: node scripts/browser_smoke.mjs BROWSER_PATH [LOCAL_BASE_URL] [SCREENSHOT_PATH]");
const origin = new URL(base);
assert.ok(["localhost", "127.0.0.1"].includes(origin.hostname), "Browser smoke must target a local test server");
const cases = JSON.parse((await readFile(new URL("../BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json", import.meta.url), "utf8")).replace(/^\uFEFF/, "")).cases;
const directory = await mkdtemp(join(tmpdir(), "voltpilot-browser-"));
const child = spawn(browser, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-background-networking", "--remote-debugging-port=0", `--user-data-dir=${directory}`, "about:blank"], {stdio: ["ignore", "ignore", "pipe"]});
let socket;
let sequence = 0;
const pending = new Map();
const events = new Map();
const timeout = setTimeout(() => child.kill(), 60000);
function send(method, params = {}) {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`DevTools timeout: ${method}`)); }, 12000);
    pending.set(id, {resolve, reject, timer});
    socket.send(JSON.stringify({id, method, params}));
  });
}
async function evaluate(expression) {
  const output = await send("Runtime.evaluate", {expression, returnByValue: true, awaitPromise: true});
  assert.equal(output.exceptionDetails, undefined, "Browser evaluation failed");
  return output.result.value;
}
async function until(expression) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (await evaluate(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 80));
  }
  const diagnostic = await evaluate("JSON.stringify({url:location.href,title:document.title,status:document.querySelector('#run-status')?.textContent,html:document.documentElement.outerHTML.slice(0,800)})");
  throw new Error("Browser condition did not become true: " + expression + "\n" + diagnostic);
}

try {
  const endpoint = await new Promise((resolve, reject) => {
    let stderr = "";
    child.on("error", reject);
    child.on("exit", code => reject(new Error(`Browser exited early: ${code}`)));
    child.stderr.on("data", chunk => {
      stderr += chunk.toString();
      const match = stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) resolve(match[1]);
    });
  });
  const address = new URL(endpoint);
  const page = await (await fetch(`http://${address.host}/json/new?about:blank`, {method: "PUT"})).json();
  socket = new WebSocket(page.webSocketDebuggerUrl);
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const call = pending.get(message.id);
      pending.delete(message.id);
      clearTimeout(call.timer);
      if (message.error) call.reject(new Error(message.error.message)); else call.resolve(message.result);
    } else {
      for (const listener of events.get(message.method) || []) listener(message.params);
    }
  };
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  const runtimeErrors = [];
  events.set("Runtime.exceptionThrown", [event => runtimeErrors.push(event)]);
  await send("Runtime.enable");
  await send("Page.enable");
  let posts = 0;
  let fail = false;
  let healthChecks = 0;
  let healthReady = false;
  let lastBody;
  events.set("Fetch.requestPaused", [event => {
    const isHealth = new URL(event.request.url).pathname === "/health";
    try {
      assert.equal(new URL(event.request.url).origin, origin.origin, "Always use the page origin");
      assert.equal(event.request.method, isHealth ? "GET" : "POST");
      if (isHealth) healthChecks++;
      else { posts++; lastBody = JSON.parse(event.request.postData); }
    } catch (error) { runtimeErrors.push(error); }
    const response = structuredClone(cases[0].expected_output);
    response.plan_summary = "<img src=x onerror=window.__unsafe=true> TEST-ONLY browser fixture";
    send("Fetch.fulfillRequest", {
      requestId: event.requestId, responseCode: isHealth ? (healthReady ? 200 : 503) : (fail ? 500 : 200),
      responseHeaders: [{name: "Content-Type", value: "application/json"}],
      body: Buffer.from(JSON.stringify(isHealth ? {status: healthReady ? "ok" : "not_ready"} : (fail ? {error: {code: "model_unavailable"}} : response))).toString("base64")
    }).catch(error => runtimeErrors.push(error));
  }]);
  await send("Fetch.enable", {patterns: ["*/optimize-energy", "*/health"].map(urlPattern => ({urlPattern, requestStage: "Request"}))});
  await send("Page.addScriptToEvaluateOnNewDocument", {source: "localStorage.setItem('voltpilot-api-origin', 'https://stale.invalid')"});
  await send("Emulation.setDeviceMetricsOverride", {width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false});
  await send("Page.navigate", {url: base});
  await until("document.querySelector('#sample')?.options.length === 10 && document.querySelector('#scenario-json').value.length > 100");
  await send("Emulation.setDeviceMetricsOverride", {width: 2560, height: 1440, deviceScaleFactor: 1, mobile: false});
  assert.equal(await evaluate("document.querySelector('.workspace').getBoundingClientRect().width / window.innerWidth > 0.94"), true, "Wide-screen workspace should use at least 94% of the viewport");
  await send("Emulation.setDeviceMetricsOverride", {width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false});
  assert.equal(posts, 0);
  assert.equal(await evaluate("document.querySelector('#run-button').disabled"), true);
  await until("document.querySelector('#health-status').dataset.kind === 'error'");
  assert.equal(healthChecks, 1, "Health is checked automatically once");
  assert.equal(await evaluate("document.querySelector('#api-base') === null"), true);
  assert.equal(await evaluate("document.querySelector('#scenario-data').open"), false);
  assert.equal(await evaluate("document.querySelectorAll('#note-editors textarea').length"), cases[0].input.operator_notes.length);
  healthReady = true;
  await evaluate("document.querySelector('#health-button').click()");
  await until("document.querySelector('#health-status').dataset.kind === 'success'");
  assert.equal(healthChecks, 2);
  assert.equal(posts, 0, "Health must not send optimization requests");
  await evaluate("const note = document.querySelector('#operator-note-0'); note.value += ' '; note.dispatchEvent(new Event('input'))");
  assert.equal(await evaluate("JSON.parse(document.querySelector('#scenario-json').value).operator_notes[0]"), cases[0].input.operator_notes[0] + " ");
  await evaluate("document.querySelector('#quota-consent').click(); document.querySelector('#run-button').click()");
  await until("!document.querySelector('#result-content').hidden");
  assert.equal(posts, 1);
  assert.equal(lastBody.operator_notes[0], cases[0].input.operator_notes[0] + " ", "Edited notes reach POST body");
  assert.deepEqual(lastBody.hours, cases[0].input.hours);
  assert.equal(await evaluate("document.querySelectorAll('#hourly-plan tr').length"), 24);
  assert.equal(await evaluate("document.querySelectorAll('#energy-chart polyline').length"), 3);
  assert.equal(await evaluate("document.querySelector('#metric-cost').textContent"), "38,365");
  assert.equal(await evaluate("document.querySelector('#plan-summary img') !== null || window.__unsafe === true"), false);
  assert.equal(await evaluate("document.querySelector('#download-button').disabled"), false);
  await send("Browser.setDownloadBehavior", {behavior: "allow", downloadPath: directory});
  await evaluate("document.querySelector('#download-button').click()");
  let downloaded;
  for (let attempt = 0; attempt < 50; attempt++) {
    try { downloaded = JSON.parse(await readFile(join(directory, "voltpilot-schedule.json"), "utf8")); break; }
    catch { await new Promise(resolve => setTimeout(resolve, 100)); }
  }
  assert.equal(downloaded?.scenario_id, cases[0].input.scenario_id, "Export downloads the actual response");
  assert.equal(downloaded?.total_cost_bdt, cases[0].expected_output.total_cost_bdt);
  if (screenshot) {
    await evaluate("document.title = 'TEST FIXTURE — no live inference'; const banner = document.createElement('p'); banner.className = 'fixture-banner'; banner.textContent = 'UI TEST FIXTURE — NO LIVE INFERENCE'; banner.setAttribute('role', 'note'); document.querySelector('main').prepend(banner)");
    const image = await send("Page.captureScreenshot", {format: "png", captureBeyondViewport: false});
    await writeFile(screenshot, Buffer.from(image.data, "base64"));
  }
  for (const width of [320, 390, 768, 1024, 2560]) {
    await send("Emulation.setDeviceMetricsOverride", {width, height: 1000, deviceScaleFactor: 1, mobile: width < 760});
    assert.equal(await evaluate("document.documentElement.scrollWidth <= window.innerWidth"), true, `Results overflow at ${width}px`);
    if (screenshot && width === 390) {
      await evaluate("document.querySelector('.results').scrollIntoView()");
      const image = await send("Page.captureScreenshot", {format: "png", captureBeyondViewport: false});
      await writeFile(screenshot.replace(/\.png$/, "-mobile.png"), Buffer.from(image.data, "base64"));
    }
  }
  await evaluate("document.querySelector('#operator-note-0').dispatchEvent(new Event('input'))");
  assert.equal(await evaluate("document.querySelector('#result-content').hidden && document.querySelector('#download-button').disabled"), true, "Note edits clear stale results");
  fail = true;
  await evaluate("document.querySelector('#run-button').click()");
  await until("document.querySelector('#run-status').dataset.kind === 'error'");
  assert.equal(posts, 2);
  assert.equal(await evaluate("document.querySelector('#result-content').hidden && document.querySelector('#download-button').disabled"), true);
  await evaluate("document.querySelector('#scenario-json').value = '{'; document.querySelector('#scenario-json').dispatchEvent(new Event('input')); document.querySelector('#run-button').click()");
  await until("document.querySelector('#run-status').textContent.includes('valid JSON')");
  assert.equal(posts, 2, "Invalid scenario must not consume a provider request");
  await evaluate("document.querySelector('#load-sample').click(); const raw = document.querySelector('#scenario-json'); const input = JSON.parse(raw.value); input.operator_notes = ['Imported operator note']; raw.value = JSON.stringify(input); raw.dispatchEvent(new Event('input'))");
  assert.equal(await evaluate("document.querySelector('#operator-note-0').value"), "Imported operator note", "JSON changes refresh note editors");
  const imported = structuredClone(cases[0].input);
  imported.scenario_id = "IMPORT-TEST";
  await writeFile(join(directory, "import.json"), JSON.stringify(imported));
  await send("DOM.enable");
  const documentNode = await send("DOM.getDocument");
  const fileNode = await send("DOM.querySelector", {nodeId: documentNode.root.nodeId, selector: "#import-file"});
  await send("DOM.setFileInputFiles", {nodeId: fileNode.nodeId, files: [join(directory, "import.json")]});
  await until("document.querySelector('#scenario-id').textContent === 'IMPORT-TEST'");
  assert.equal(await evaluate("JSON.parse(document.querySelector('#scenario-json').value).scenario_id"), "IMPORT-TEST");
  assert.equal(posts, 2, "Import must not send a model request");
  await send("Emulation.setDeviceMetricsOverride", {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
  await evaluate("document.querySelector('#load-sample').click()");
  assert.equal(await evaluate("document.documentElement.scrollWidth <= window.innerWidth"), true, "Mobile layout overflow");
  assert.equal(runtimeErrors.length, 0, "Browser runtime errors occurred");
  console.log("PASS real Chromium: automatic health failure/success, same-origin requests ignoring stale override, sample loading, note/JSON synchronization, consent, exact POST body, fixture chart/table, JSON download/import, XSS text safety, stale/error clearing, invalid-input no-spend, results layout at 320/390/768/1024/2560px. Health and optimization intercepted. NO live inference.");
} finally {
  clearTimeout(timeout);
  for (const call of pending.values()) clearTimeout(call.timer);
  socket?.close();
  if (child.exitCode === null) {
    const exited = new Promise(resolve => child.once("exit", resolve));
    child.kill();
    await Promise.race([exited, new Promise(resolve => setTimeout(resolve, 4000))]);
  }
  await rm(directory, {recursive: true, force: true, maxRetries: 8, retryDelay: 250});
}