# VoltPilot — Team MAJesty

An LLM-powered, minimum-cost 24-hour energy scheduler for the BUP GridWise challenge.
The model interprets operator notes; validated constraints feed a SciPy/HiGHS linear
program. An independent replay checks every serialized schedule before success.

**Backend API:** http://35.222.65.204

**Temporary HTTPS mirror:** https://fame-choice-amended-diabetes.trycloudflare.com

**Submission checklist:** [SUBMISSION.md](SUBMISSION.md) ·
**2:50 video narration:** [VIDEO_SCRIPT.md](VIDEO_SCRIPT.md)

**Current verified state:** the same-origin dashboard is deployed on GCP. Its public
page returns 200 and malformed JSON returns a controlled 400. The fixed-address
HTTP origin is permitted by the challenge and serves synthetic data only; keep the
VM and its external IP allocated throughout judging. The temporary
Cloudflare quick-tunnel URL can change on process restart and has no uptime guarantee.
The VM model is configured and `/health` returns 200. A real external SAMPLE-01
request passed interpretation, independent replay and the 38,365 BDT optimum in
**1.784 seconds**. The full live public suite subsequently passed **10/10 cases**,
with serial p50 **6.341s** and p95 **8.045s**. HTTP does
not provide encryption; do not enter credentials or personal data into the dashboard.

The frontend is packaged for **Vercel**, with exact API routes proxied to the GCP
backend. No manual API URL or CORS configuration is needed for that deployment.
See [deploy/README.md](deploy/README.md) for private
credential setup, managed startup and rotation without affecting other VM services.

```text
Scenario + operator notes
        -> Real LLM: structured interpretation of every note
        -> Deterministic JSON / Pydantic guardrails
        -> Directive bounds -> SciPy / HiGHS minimum-cost LP
        -> Independent serialized-schedule replay
        -> Exact API JSON + dashboard / export
```

## Minimal submission

This private repository contains the runtime, pinned dependencies, Dockerfile,
tests, public sample fixture, verification scripts and build workflows. It excludes
the original repository history, PDFs, planning documents, local environments,
logs and credentials. Keep it private during the event and arrange organizer access
and the post-deadline visibility change according to the official rules. A new
private repository does not by itself certify reveal-time compliance.

## Quickstart (Python 3.12)

Linux checkout location used below: `/opt/voltpilot`. Clone somewhere writable or
have the VPS administrator provision this directory without changing other apps.

```bash
git clone https://github.com/mahdiebene/TeamMAJesty-VoltPilot.git /opt/voltpilot
cd /opt/voltpilot
python3.12 -m venv /opt/voltpilot/.venv
/opt/voltpilot/.venv/bin/python -m pip install --only-binary=:all: -r /opt/voltpilot/requirements-lock.txt
/opt/voltpilot/.venv/bin/python -m pip check
/opt/voltpilot/.venv/bin/python -B -m unittest discover -s /opt/voltpilot/tests -t /opt/voltpilot -v
/opt/voltpilot/.venv/bin/python -B -m scripts.validate_public_cases --offline
```

Windows PowerShell, using a fresh writable checkout:

```powershell
git clone https://github.com/mahdiebene/TeamMAJesty-VoltPilot.git 'F:\TeamMAJesty-VoltPilot'
Set-Location 'F:\TeamMAJesty-VoltPilot'
python -m venv 'F:\TeamMAJesty-VoltPilot\.venv'
& 'F:\TeamMAJesty-VoltPilot\.venv\Scripts\python.exe' -m pip install --only-binary=:all: -r 'F:\TeamMAJesty-VoltPilot\requirements-lock.txt'
& 'F:\TeamMAJesty-VoltPilot\.venv\Scripts\python.exe' -B -m unittest discover -s 'F:\TeamMAJesty-VoltPilot\tests' -t 'F:\TeamMAJesty-VoltPilot' -v
& 'F:\TeamMAJesty-VoltPilot\.venv\Scripts\python.exe' -B -m scripts.validate_public_cases --offline
```

Private-clone access must already be configured. Never put a token into a clone URL.
Offline tests need no provider credentials. All ten sample costs must match within
0.01 BDT; equivalent optimal schedules need not match reference hourly actions.

## Runtime configuration

The adapter uses an HTTPS OpenAI-compatible chat-completions API with JSON-object
response mode. Selected gateway: Pollinations. Requested model:
`google/gemini-3.8-flash`. Gateway IDs/pricing can change; confirm current availability
and evaluate interpretation quality before release. No local model is bundled.

| Variable | Meaning / default |
| --- | --- |
| `LLM_BASE_URL` | Required; selected `https://gen.pollinations.ai/v1` |
| `LLM_MODEL` | Required exact provider model ID |
| `LLM_API_KEY` | Required backend-only runtime secret |
| `LLM_TIMEOUT_SECONDS` | 10 seconds per attempt; at most two attempts |
| `REQUEST_DEADLINE_SECONDS` | 25 seconds, always below 30 |
| `MAX_CONCURRENT_REQUESTS` | 2 active model/solver slots per process |
| `MAX_PENDING_REQUESTS` | 6 active plus queued requests |
| `CORS_ORIGINS` | Empty by default; comma-separated exact HTTPS browser origins, no trailing slashes |
| `PORT` | Container listens on 8080 by default |

There is **no automatic dotenv loader**. `/opt/voltpilot/.env.example` (or
`F:\TeamMAJesty-VoltPilot\.env.example`) contains names and examples only. Use process
environment variables or a private Docker runtime env-file outside the checkout.
Never bake keys into images, Git, build arguments, frontend code, URLs or logs.
Previously shared credentials are exposed and should be rotated, even if used
temporarily by the owner. No inference credentials are included in this submission.

For local PowerShell use, configure the same terminal that starts Uvicorn:

```powershell
$env:LLM_BASE_URL = 'https://gen.pollinations.ai/v1'
$env:LLM_MODEL = 'google/gemini-3.8-flash'
$secret = Read-Host 'Backend API key (hidden)' -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
try { $env:LLM_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
Remove-Variable secret, ptr
Set-Location 'F:\TeamMAJesty-VoltPilot'
& 'F:\TeamMAJesty-VoltPilot\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 1 --no-access-log
```

For Linux, configure the same terminal that starts Uvicorn. The hidden key prompt
does not put the key in shell history:

```bash
cd /opt/voltpilot
export LLM_BASE_URL='https://gen.pollinations.ai/v1'
export LLM_MODEL='google/gemini-3.8-flash'
read -rsp 'Backend API key (hidden): ' LLM_API_KEY; echo
export LLM_API_KEY
/opt/voltpilot/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 1 --no-access-log
```

Do not enable HTTP header/provider-body debug logs. The model client disables
redirects and environment proxies to avoid accidental credential forwarding.

## API and sample request

- `GET /health`: 200 `{"status":"ok"}` after local initialization with configured
  model settings; 503 `{"status":"not_ready"}` without them. No paid provider call.
  This does not prove quota or provider connectivity.
- `POST /optimize-energy`: challenge request/response contract. Invalid input is
  400; model, solver, overload or deadline failure is sanitized 500 JSON. No partial
  schedule and no fabricated `no_op` after failed interpretation.
- `/docs` and `/openapi.json`: interactive API reference and machine-readable schema.
- `/`: testing dashboard; loading it and its public sample inputs uses no model quota.

Every request has `scenario_id`, 1–3 `operator_notes`, `battery` and 24 `hours`.
Successful responses contain `scenario_id`, `directive_interpretation`,
`hourly_plan`, `total_grid_kwh`, `total_cost_bdt`, `peak_grid_kwh`, `plan_summary`.
Full sample requests and reference responses are in
`/opt/voltpilot/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json`.

Linux sample request, from another terminal:

```bash
curl --fail --max-time 5 http://127.0.0.1:8080/health
/opt/voltpilot/.venv/bin/python -c 'import json; from pathlib import Path; p=Path("/opt/voltpilot/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"); print(json.dumps(json.loads(p.read_text(encoding="utf-8-sig"))["cases"][0]["input"]))' \
  | curl --fail-with-body --max-time 30 -H 'Content-Type: application/json' \
    --data-binary @- http://127.0.0.1:8080/optimize-energy
```

SAMPLE-01's optimum is **38,365 BDT**. Validate full semantics, balance, reserves,
caps, neutrality and totals, not just HTTP 200 or the reported cost:

```bash
cd /opt/voltpilot
/opt/voltpilot/.venv/bin/python -m scripts.validate_public_cases --base-url http://127.0.0.1:8080
# Optional authorized 20-request run; consumes provider quota.
/opt/voltpilot/.venv/bin/python -m scripts.validate_public_cases --base-url http://127.0.0.1:8080 --repeat 2
```

Use the deployed base URL for external validation. The runner includes failures in
timing statistics (nearest-rank p95, serial concurrency). A small serial benchmark
is not a load guarantee. The optional `scripts.check_model` command consumes one
semantic smoke request (up to two attempts); `--list-models` only checks the catalog.

## Build, fallback image and VPS

The image runs Python 3.12, one Uvicorn worker and a non-root UID. It contains only
runtime source and locked dependencies, not tests, fixtures or secrets. The
Docker build context is an explicit allowlist. It binds `0.0.0.0:8080` inside the
container and supports a read-only root filesystem.

```bash
docker build --tag voltpilot:local /opt/voltpilot
cd /opt/voltpilot
python3 -B -m scripts.container_smoke --image voltpilot:local
```

The smoke script runs offline tests inside the image with networking disabled,
then starts temporary loopback-only containers to check HTTP readiness, validation,
safe unconfigured failure and OpenAPI. It uses fake configuration only for the
readiness check and **never calls a real model**. Only its own randomly named
temporary containers are removed.

GitHub Actions verifies pushes. Manually dispatch **Build and publish verified
fallback image** to build/test, publish to GHCR with a source-SHA tag, remove the
local image, pull by digest and repeat the container checks. The job summary records
the exact digest. Package visibility is separate from repository visibility: verify
it remains private during the event and grant organizers authorized pull access.
No workflow deploys automatically to the VPS or receives an LLM key.

On an authorized Linux host with Docker, prepare `/etc/voltpilot/voltpilot.env`
privately (owner-only permissions) using the runtime variable names above. Confirm
the container name and port are unused. A local-image launch is:

```bash
docker run --detach --name voltpilot-api --restart unless-stopped \
  --cpus 2 --memory 2g --pids-limit 128 --cap-drop ALL \
  --security-opt no-new-privileges --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --env-file /etc/voltpilot/voltpilot.env \
  --publish 127.0.0.1:18080:8080 voltpilot:local
curl --fail --max-time 5 http://127.0.0.1:18080/health
```

For the published fallback, use the exact digest from the successful release job
instead of `voltpilot:local`, first performing `docker pull` on that digest with
authorized private-package access (`read:packages` where applicable). The judge
also needs securely supplied runtime model credentials, not just image access.

### Previous verified fallback reference (2026-09-18)

This reference predates the dashboard. For the current source, dispatch the private
release workflow and use its new digest; do not describe the historical image as
containing newer frontend or deployment changes.

- Source revision: `696c4ef623191ee5f11fdd5c2fd3224ec4131710`.
- Tag: `ghcr.io/mahdiebene/teammajesty-voltpilot:sha-696c4ef623191ee5f11fdd5c2fd3224ec4131710`.
- Digest: `ghcr.io/mahdiebene/teammajesty-voltpilot@sha256:5bfde9c6503ff1fc9fbb57ab31e3ed83e920c2d965b5411d83b3b5a58b136b1f`.
- [Successful build, publish and pulled-image checks](https://github.com/mahdiebene/TeamMAJesty-VoltPilot/actions/runs/35358223728).
- Anonymous pull was denied. Authorized private-package access is required.

Exact commands, after private registry login and creating the runtime env-file:

```bash
IMAGE='ghcr.io/mahdiebene/teammajesty-voltpilot@sha256:5bfde9c6503ff1fc9fbb57ab31e3ed83e920c2d965b5411d83b3b5a58b136b1f'
docker pull "$IMAGE"
docker run --detach --name voltpilot-api --restart unless-stopped \
  --cpus 2 --memory 2g --pids-limit 128 --cap-drop ALL \
  --security-opt no-new-privileges --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --env-file /etc/voltpilot/voltpilot.env \
  --publish 127.0.0.1:18080:8080 "$IMAGE"
curl --fail --max-time 5 http://127.0.0.1:18080/health
```

This launch is loopback-only: an owner-approved HTTPS reverse proxy and narrow
firewall rules are needed for public access. Do not change existing services,
occupied ports, firewall policies, SSH security or perform broad Docker cleanup.
If SSH is unavailable, the VPS provider's authenticated browser console can run
the same commands. It still requires owner access; CI cannot bypass VPS login.

## Frontend on Vercel

The `frontend` directory is a dependency-free static dashboard, also served by the
backend at `/`. It loads only public sample **inputs**, accepts JSON imports, sends
one request on an explicit quota-confirmed click, and displays charts, directives,
hourly dispatch and exportable JSON. It never contains a model key or a production
mock/fallback. UI validation is not a replacement for backend replay.

For Vercel, import the private repository, choose Root Directory `frontend`,
Framework Preset **Other**, no build command, and Output Directory `.`.
`frontend/vercel.json` proxies `/health`, `/optimize-energy`, `/docs`, and
`/openapi.json` to the GCP backend at `http://35.222.65.204`. The browser uses only
the Vercel HTTPS origin, so there is no mixed-content request and no cross-origin
preflight. Leave the API override blank. No model or Vercel key belongs in frontend
configuration. The proxy-to-VM hop uses public HTTP for synthetic challenge data;
model credentials travel only from backend to provider over HTTPS.

Disable Vercel Deployment Protection for the production judging URL, then test
health and a live scenario from an incognito window. The judge must not need a
Vercel login. The Python/SciPy runtime stays on GCP; it is not a serverless function.

CORS is a browser policy, **not authentication or spending protection**. The judge
API must remain reachable without login. Provider-side hard budgets/quotas are
needed to limit exposure; concurrency alone does not cap aggregate spending.

## Architecture and limitations

1. Strict JSON/Pydantic validation rejects duplicate keys, nonfinite numbers,
   booleans/numeric strings in numeric fields, invalid mappings and shapes.
2. A real model interprets all notes together. One bounded retry is permitted;
   there is no regex or reference-case interpretation fallback.
3. Validated directives compile to solar, reserve, charge/discharge and grid bounds.
4. A 96-variable continuous LP minimizes grid cost with signed battery flow,
   curtailment, rate bounds, energy balance and final neutrality. No invented
   export, losses, demand shedding or secondary peak objective.
5. Independent replay checks serialized actions, every physical constraint and
   recomputed totals. Runtime replay cannot detect a semantically wrong but
   well-formed model interpretation; tests additionally use independent labels.

The 25-second request budget covers body receive, queueing, provider attempts,
solving and serialization. Late buffered successes are rejected. Native solver
threads retain their concurrency slot until they actually finish. Bodies are
limited to 1 MiB; slow client network delivery is outside a server completion
guarantee. Unknown request metadata is ignored; extra model/output fields are not.

Provisional policies: negative finite tariffs are accepted, empty applicable
windows are rejected, overlapping solar reductions fail safely until their
combination rule is clarified, and ambiguous cross-day language is not assigned
invented semantics. Extreme finite numbers outside the solver's numerical range
can fail safely. A dependency compatibility check is not a security audit.

## Verification evidence and remaining gates

- 49 Python tests discovered: 47 passed on Windows and two POSIX permission tests
  skipped there (covered by Linux container checks). Mocked provider tests are not
  live-model evidence.
- All 10 public cases pass **live** through the deployed Pollinations
  `google/gemini-3.8-flash` interpreter. Each response matches organizer directives,
  passes independent physical replay and matches the optimum within 0.01 BDT.
  Serial p50: **6.341s**, p95: **8.045s**, failures: **0/10**. This small sample is
  not a hidden-test or uptime guarantee. All **7/7 independently labeled paraphrases**
  also passed live (5.50–7.54s), covering all six directive types and BY/TO reductions.
  An earlier interrupted acceptance attempt produced one backend model timeout;
  do not interpret the completed run as proof that the provider never fails.
- All 10 frontend logic tests pass, including the Vercel proxy route contract.
  Real Chromium checks desktop/mobile and 2560-pixel full-width layout,
  input loading, consent, charts/table/export enablement, safe text, and stale-result
  clearing. Optimization is intercepted with TEST-ONLY fixtures in this smoke test.
- The dashboard image passed Linux in-container tests and both configured/unconfigured
  HTTP smoke paths under non-root, read-only, CPU/memory-limited execution.
- External checks confirm dashboard 200, safe malformed-input 400, configured
  health 200, and a real SAMPLE-01 pass in 1.784 seconds with the selected model.
- Still required: Vercel deployment,
  a matching pullable fallback image,
  post-deadline repository visibility, and an accessible video of at most 3 minutes.

### Dashboard and limited-quota verification

From the checkout root, run the existing Python regression commands plus:

```bash
node --test frontend/tests/core.test.mjs
python3 -B -m scripts.validate_public_cases --base-url http://127.0.0.1:18080 --case SAMPLE-01
```

The second command sends **one real scenario** (the backend can attempt the provider
twice). It checks interpretation against public ground truth and independently
replays all physical constraints and totals. It is not the full live release gate.
Repeat `--case` to select cases deliberately; omitting it runs all ten.

Independently labeled paraphrases include BY versus TO reductions, reserve
percentages of capacity, spelled-out numbers, time windows, and no-op distractors:

```bash
python3 -B -m scripts.validate_paraphrases --offline
# Seven real requests; run only with sufficient provider quota:
python3 -B -m scripts.validate_paraphrases --base-url http://127.0.0.1:18080
```

The paraphrases are development checks, not organizer hidden tests. Expected labels
exist only in verification inputs; production never imports or matches them.

`scripts/browser_smoke.mjs` uses Node 24 and an already-installed Chromium browser.
Run against an unconfigured local Uvicorn server on `127.0.0.1:18081`:

```bash
node scripts/browser_smoke.mjs /usr/bin/google-chrome http://127.0.0.1:18081
```

It intercepts optimization calls with clearly test-only fixtures, checks sample
loading, consent, result rendering, safe text, error clearing and mobile layout.
It never sends a provider request and is not live-model evidence. Python POSIX
credential-permission tests skip on Windows and run inside the Linux container.

Credits: Python, FastAPI, Pydantic, Uvicorn, HTTPX, NumPy, SciPy/HiGHS; organizer
GridWise challenge/sample pack; Pollinations gateway (requested model
`google/gemini-3.8-flash`); AI-assisted implementation and review. Team MAJesty must
understand, verify and own its submission. No shortlist or hidden-score guarantee.