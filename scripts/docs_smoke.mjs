// Render real Swagger UI and its live OpenAPI schema. No optimization calls or mocks.
import {spawn} from "node:child_process";
import {mkdtemp, rm, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import assert from "node:assert/strict";

const [browser, base = "https://volt-pilot-one.vercel.app", screenshot] = process.argv.slice(2);
if (!browser) throw new Error("Usage: node scripts/docs_smoke.mjs BROWSER_PATH [BASE_URL] [SCREENSHOT_PATH]");
const url = new URL("/docs", base);
assert.ok(["http:", "https:"].includes(url.protocol) && !url.username && !url.password);
const directory = await mkdtemp(join(tmpdir(), "voltpilot-docs-"));
const child = spawn(browser, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-background-networking", "--remote-debugging-port=0", `--user-data-dir=${directory}`, "about:blank"], {stdio: ["ignore", "ignore", "pipe"]});
const timeout = setTimeout(() => child.kill(), 60000);
let socket;
let sequence = 0;
const pending = new Map();
const errors = [];
const blocked = [];

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
    } else if (message.method === "Runtime.exceptionThrown") {
      errors.push(message.params.exceptionDetails.text);
    } else if (message.method === "Fetch.requestPaused") {
      const {requestId, request} = message.params;
      const safe = request.method === "GET";
      if (!safe) blocked.push(request.method);
      send(safe ? "Fetch.continueRequest" : "Fetch.failRequest",
        safe ? {requestId} : {requestId, errorReason: "BlockedByClient"}).catch(error => errors.push(error.message));
    }
  };
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  await send("Runtime.enable");
  await send("Page.enable");
  await send("Fetch.enable", {patterns: [{urlPattern: "*", requestStage: "Request"}]});
  await send("Page.addScriptToEvaluateOnNewDocument", {source: "window.__cspErrors = []; document.addEventListener('securitypolicyviolation', e => window.__cspErrors.push(e.violatedDirective + ': ' + e.blockedURI));"});
  await send("Emulation.setDeviceMetricsOverride", {width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false});
  await send("Page.navigate", {url: url.href});
  let loaded = false;
  for (let attempt = 0; attempt < 100; attempt++) {
    loaded = await evaluate("Boolean(document.querySelector('.opblock-post') && document.querySelector('.opblock-get'))");
    if (loaded) break;
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  const state = await evaluate("({title:document.title, text:document.body.innerText.slice(0,2000), violations:window.__cspErrors || [], paths:[...document.querySelectorAll('.opblock-summary-path')].map(e=>e.textContent.trim())})");
  assert.ok(loaded, `Swagger did not render: ${JSON.stringify(state)}`);
  assert.deepEqual(state.violations, [], "CSP must not block Swagger resources");
  assert.deepEqual(errors, [], "Swagger runtime errors");
  assert.deepEqual(blocked, [], "Docs must not attempt non-GET requests");
  assert.ok(state.paths.includes("/health") && state.paths.includes("/optimize-energy"));
  assert.match(state.text, /VoltPilot/);
  if (screenshot) {
    const image = await send("Page.captureScreenshot", {format: "png"});
    await writeFile(screenshot, Buffer.from(image.data, "base64"));
  }
  console.log(`PASS real Chromium Docs: ${url.href}; Swagger rendered both endpoints with live OpenAPI; no CSP/runtime errors; GET-only, no inference.`);
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