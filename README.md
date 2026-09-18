# VoltPilot — Team MAJesty

An LLM-powered, minimum-cost 24-hour energy scheduler for the BUP GridWise challenge.
The model interprets operator notes; validated constraints feed a SciPy/HiGHS linear
program. An independent replay checks every serialized schedule before success.

**Release status:** 37 local tests, all 10 offline public cases, and a Linux Docker
build/publish/pull/run cycle passed. The image was tested as non-root with a read-only
filesystem. No public API or frontend is deployed yet. A privately configured
hosted-model credential and working VPS access are required to finish deployment.
Do not claim judge readiness from offline tests alone.

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

For Linux with variables already privately supplied:

```bash
cd /opt/voltpilot
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

### Verified fallback reference (2026-09-18)

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

There is **no custom frontend in this minimal judging repository**. `/docs` is API
documentation, not a dashboard. A separately built frontend may be deployed on
Vercel without moving the Python/SciPy service there.

1. Give the VPS API a working HTTPS URL. An HTTPS Vercel page cannot directly fetch
   an HTTP API because browsers block mixed content.
2. Set backend `CORS_ORIGINS` to the exact Vercel production origin (or custom
   domain), then restart only the VoltPilot container. Add specific preview origins
   deliberately; wildcard Vercel domains are rejected. Localhost HTTP origins are
   allowed for development.
3. Configure only the public API base URL in the browser frontend. Keep
   `LLM_API_KEY` exclusively in the backend runtime. JSON requests use
   `Content-Type: application/json`; cookies/login are not required.
4. Test preflight, successful responses and safe errors from the actual frontend.

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

- Local baseline: 32 unit/API/provider-mock tests and all 10 offline public costs
  passed. Five additional CORS/configuration tests also pass (37 total).
- Prior authorized Pollinations SAMPLE-01 smoke: production interpreter through
  local ASGI, 2 notes correct, 24 hours replayed, 38,365 BDT; 11.55 seconds and two
  provider attempts. This was one scenario, not a live full-suite or p95 result.
- Linux x86-64 CPython 3.12 Docker build succeeded. All 37 tests and all 10 offline
  public cases passed inside the image with test-network access disabled. The
  published image was removed locally, pulled by digest and retested successfully,
  including real HTTP readiness, invalid input, safe missing-model failure and
  OpenAPI checks. No live inference was used in those checks.
- No public VPS endpoint, real-model container run, complete live public suite or
  independent language holdout benchmark is verified yet. The confirmed VPS host
  identity was accepted only after independent owner verification; the configured
  SSH login was rejected. No VPS services or configuration were changed.
- Submission still needs the verified public API URL, exact tested image digest
  with judge access, secure runtime model access, live latency/reliability evidence,
  and the required accessible video of at most three minutes.

Credits: Python, FastAPI, Pydantic, Uvicorn, HTTPX, NumPy, SciPy/HiGHS; organizer
GridWise challenge/sample pack; Pollinations gateway (requested model
`google/gemini-3.8-flash`); AI-assisted implementation and review. Team MAJesty must
understand, verify and own its submission. No shortlist or hidden-score guarantee.