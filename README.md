# VoltPilot — Team MAJesty

24-hour campus energy scheduling for the GridWise challenge. A real LLM interprets
operator notes; deterministic guardrails and a SciPy/HiGHS optimizer produce a
minimum-grid-cost schedule, checked by independent physical replay.

| Link | Purpose |
| --- | --- |
| http://35.222.65.204 | Direct API base URL for judging |
| https://volt-pilot-one.vercel.app/ | Frontend with same-origin API proxy |
| http://35.222.65.204/docs | Interactive API reference |
| https://github.com/mahdiebene/TeamMAJesty-VoltPilot | Source repository |

The frontend connects automatically. Public samples contain inputs, not stored
answers. Loading inputs and checking health do not call the model. Running a
scenario requires explicit consent and uses provider quota.

## Architecture

```text
Scenario + operator notes
  → OpenAI-compatible LLM: structured directive interpretation
  → Strict JSON/Pydantic validation and directive bounds
  → SciPy/HiGHS linear program: minimum total grid cost
  → Independent replay of the serialized schedule
  → API response, chart, hourly dispatch and JSON export
```

The model is used for interpretation, not arithmetic or schedule generation.
There is no sample-matching or regex interpretation fallback. Invalid model output
cannot silently become a no-op. Backend dependencies are FastAPI, Pydantic,
Uvicorn, HTTPX, NumPy and SciPy; the frontend uses native HTML/CSS/JavaScript.

## Local setup

Python 3.12 is required. Private repository access must already be configured.
Linux example using a writable checkout at `/opt/voltpilot`:

```bash
git clone https://github.com/mahdiebene/TeamMAJesty-VoltPilot.git /opt/voltpilot
cd /opt/voltpilot
python3.12 -m venv /opt/voltpilot/.venv
/opt/voltpilot/.venv/bin/python -m pip install --only-binary=:all: -r /opt/voltpilot/requirements-lock.txt
/opt/voltpilot/.venv/bin/python -m pip check
```

Set backend environment variables in the same terminal that starts the server.
There is no automatic dotenv loader. `.env.example` contains names/examples only.

| Variable | Default / purpose |
| --- | --- |
| `LLM_BASE_URL` | Required HTTPS OpenAI-compatible base; selected `https://gen.pollinations.ai/v1` |
| `LLM_MODEL` | Required provider model ID; selected `google/gemini-3.8-flash` |
| `LLM_API_KEY` | Required backend-only provider secret |
| `LLM_TIMEOUT_SECONDS` | 10 seconds per attempt; at most two attempts |
| `REQUEST_DEADLINE_SECONDS` | 25 seconds |
| `MAX_CONCURRENT_REQUESTS` | 2 active requests per process |
| `MAX_PENDING_REQUESTS` | 6 active plus queued requests |
| `CORS_ORIGINS` | Empty; optional comma-separated exact HTTPS browser origins |
| `PORT` | Docker listening port, default 8080 |

The selected gateway is Pollinations. Provider model IDs and availability can
change. No local model is bundled. Never commit a real key or place one in Vercel,
frontend code, build arguments or images. Rotate previously exposed credentials.

`app/config.py` reads `LLM_API_KEY` from the backend environment; `app/llm.py`
sends it as `Authorization: Bearer ...` to `LLM_BASE_URL/chat/completions` when
interpreting notes. The browser calls our API, not Pollinations directly. Health
checks and sample loading do not use the key; optimization does. SciPy itself
does not need an API key.

```bash
export LLM_BASE_URL='https://gen.pollinations.ai/v1'
export LLM_MODEL='google/gemini-3.8-flash'
read -rsp 'Backend API key: ' LLM_API_KEY; echo
export LLM_API_KEY
/opt/voltpilot/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 1 --no-access-log
```

## API and sample request

- `GET /health`: 200 `{"status":"ok"}` when locally initialized with model
  configuration; otherwise 503 `{"status":"not_ready"}`. This does **not** verify
  provider access or quota.
- `POST /optimize-energy`: exact challenge schema. Requests include `scenario_id`,
  1–3 `operator_notes`, `battery`, and all 24 `hours`. Responses include
  `directive_interpretation`, `hourly_plan`, totals and `plan_summary`.
- Invalid input returns controlled 400 JSON. Provider, solver, overload and deadline
  failures return sanitized 500 JSON, never a fabricated schedule.
- `/docs` and `/openapi.json` document the full request/response shapes.

In another terminal, test locally:

```bash
curl --fail --max-time 5 http://127.0.0.1:8080/health
/opt/voltpilot/.venv/bin/python -c 'import json; from pathlib import Path; print(json.dumps(json.loads(Path("/opt/voltpilot/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json").read_text(encoding="utf-8-sig"))["cases"][0]["input"]))' \
  | curl --fail --max-time 30 -H 'Content-Type: application/json' --data-binary @- http://127.0.0.1:8080/optimize-energy
```

The second command consumes model quota. Use the direct API base URL above in
place of `http://127.0.0.1:8080` for external checks.

## Tests

From `/opt/voltpilot`, these checks do not spend provider quota:

```bash
/opt/voltpilot/.venv/bin/python -B -m unittest discover -s /opt/voltpilot/tests -t /opt/voltpilot -v
/opt/voltpilot/.venv/bin/python -B -m scripts.validate_public_cases --offline
/opt/voltpilot/.venv/bin/python -B -m scripts.validate_paraphrases --offline
node --test /opt/voltpilot/frontend/tests/core.test.mjs
```

Node 24 and an installed Chromium browser can also exercise the dashboard against
an unconfigured local server on port 18081. Start it in a separate terminal:

```bash
cd /opt/voltpilot
env -u LLM_API_KEY -u LLM_BASE_URL -u LLM_MODEL /opt/voltpilot/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18081 --workers 1
```

Then run:

```bash
node /opt/voltpilot/scripts/browser_smoke.mjs /usr/bin/google-chrome http://127.0.0.1:18081
```

This browser test intercepts health and optimization with **test-only fixtures**.
It checks note/JSON synchronization, same-origin POST forwarding, consent,
chart/table rendering, download/import, safe text, failure handling, and layout
at 320–2560px. It is not live-model evidence.

Check the production API reference in a real browser without sending optimization
requests (GET-only, no provider quota):

```bash
node /opt/voltpilot/scripts/docs_smoke.mjs /usr/bin/google-chrome https://volt-pilot-one.vercel.app
```

This checks rendered Swagger endpoints, the live OpenAPI schema, and CSP/runtime
errors—not just an HTTP 200 response. Docs alone allow pinned Swagger CDN assets
and a hashed initializer; the dashboard retains its stricter script policy.

For one real model request with independent ground-truth checks:

```bash
/opt/voltpilot/.venv/bin/python -B -m scripts.validate_public_cases --base-url http://35.222.65.204 --case SAMPLE-01
```

Omitting `--case` runs all ten public cases. Latest recorded live checks on
September 18, approximately 22:24–22:25 (+06:00): 10/10 public cases passed
interpretation, replay and optimum checks against the direct API (serial p50
1.031s, p95 1.419s); 7/7 separately labeled paraphrases passed through Vercel
(0.993–1.339s). An earlier provider timeout occurred; these observations do not
guarantee hidden-test performance or uptime.

Local regression: 50 Python tests discovered, 48 passed and 2 POSIX-only permission
tests skipped on Windows; 11/11 frontend tests passed. Browser checks are separate.

## Docker

Build and test locally, from `/opt/voltpilot`:

```bash
docker build --tag voltpilot:local /opt/voltpilot
/opt/voltpilot/.venv/bin/python -B -m scripts.container_smoke --image voltpilot:local
```

Published fallback from source `df5311bc5be57ce9c1b47d8abe7e036b93995bf9`:

```bash
IMAGE='ghcr.io/mahdiebene/teammajesty-voltpilot@sha256:1e4797c107df0d04b03765d34527193294aff2a71ff986e3b7c092c3ea22665c'
docker pull "$IMAGE"
docker run --detach --name voltpilot-api --restart unless-stopped \
  --cpus 2 --memory 2g --pids-limit 128 --cap-drop ALL \
  --security-opt no-new-privileges --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --env-file /etc/voltpilot/voltpilot.env \
  --publish 127.0.0.1:18080:8080 "$IMAGE"
curl --fail --max-time 5 http://127.0.0.1:18080/health
```

Create `/etc/voltpilot/voltpilot.env` privately with the required model variables
first. The container runs as non-root and binds `0.0.0.0:8080`; this host mapping is
loopback-only. Ensure its name and port are unused. The image contains no runtime
credentials. A judge needs both registry access and their own securely supplied
model configuration.

[Release run 35367777308](https://github.com/mahdiebene/TeamMAJesty-VoltPilot/actions/runs/35367777308)
successfully published, pulled and retested that digest. It includes the redesigned
planner; the subsequent Vercel-only Docs policy does not change its API behavior.
The package is private; anonymous pull is not promised. Before evaluation, grant
organizers package access or make the package public at the organizer-permitted
time. Repository visibility alone does not establish registry pull access.
The release workflow publishes newer revisions with source-SHA tags and records
their immutable digest in its summary. No workflow automatically deploys the VM.

## Vercel and GCP deployment

Import the repository into Vercel using root `frontend`, preset **Other**, empty
build/install commands, output directory `.`, and **no environment variables**.
Disable production login protection for judging. Vercel rewrites `/health`,
`/optimize-energy`, `/docs` and `/openapi.json` to the GCP API. Browser requests stay
same-origin HTTPS; the proxy-to-VM hop is HTTP. Use synthetic challenge data only.

The VM and external IP must stay allocated during judging. Provider-side hard
budgets are necessary: public endpoints and CORS are not spending protection.
See [deployment instructions](deploy/README.md) for managed startup and private
credential rotation. Keep the repository private during the event and change its
visibility after the deadline according to the organizer rules.

## Known limitations

- Replay proves physical consistency against interpreted directives, not the
  semantic correctness of the model's interpretation. Review the displayed notes.
- The 25-second budget covers body receive, queueing, model attempts and solving.
  Bodies are limited to 1 MiB. Slow clients and provider outages remain possible.
- Negative finite tariffs are accepted. Overlapping solar reductions and empty
  applicable windows are rejected rather than assigned invented semantics.
- Extreme finite values may exceed solver numerical limits. No invented losses,
  export, demand shedding or secondary peak objective are used.

Credits: organizer GridWise problem/sample pack; FastAPI, Pydantic, HTTPX,
NumPy, SciPy/HiGHS, Pollinations; AI-assisted implementation and review.