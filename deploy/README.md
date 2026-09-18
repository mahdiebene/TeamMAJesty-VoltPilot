# GCP deployment and testing handoff

Target: **gcp001**, `voltpilot@35.222.65.204`. Do not change the old VPS alias,
Oracle container, port-8000 application, existing tunnels, or broad firewall rules.

The image runs non-root on a read-only filesystem with 2 CPUs, 2 GiB RAM, 128 PIDs,
dropped capabilities, no-new-privileges and bounded Docker logs. The default binding
is `127.0.0.1:18080`. The explicit `--public-http` flag additionally publishes port
80, after refusing ports belonging to unrelated services; it does not edit firewalls.
The deployed judging origin is **http://35.222.65.204**. Keep the VM/IP allocated.
Only synthetic data belongs on this unencrypted origin; model credentials remain
server-side and go to the provider over HTTPS. No live success is implied by startup.

## 1. Private runtime configuration

In an interactive GCP browser SSH terminal:

```bash
sudo python3 -B /opt/voltpilot/current/scripts/configure_model.py
```

The prompt does not echo the key or put it in shell history. The root-owned
`/etc/voltpilot/voltpilot.env` is mode 600 inside a mode-700 directory. The helper
refuses an existing file unless `--rotate` is explicitly supplied. Keys never enter
Git, Docker build context, frontend assets, CLI arguments, logs or this document.
The helper requests Pollinations `google/gemini-3.8-flash`; live access is unverified
until the bounded test below passes. A limited key can be used for private testing,
but rotate any chat-exposed key before public release and set a provider hard budget.

## 2. Launch or reload only this project

After build and `scripts.container_smoke` pass, record the exact local image ID in
`/opt/voltpilot/current-image-id`. A first private, unconfigured staging launch is:

```bash
sudo bash /opt/voltpilot/current/deploy/start.sh \
  "$(sudo cat /opt/voltpilot/current-image-id)" --allow-unconfigured
```

This deliberately returns HTTP 503 from `/health`. The dashboard is usable, but
optimization safely fails until configured. Do not present that state as healthy.

After entering a real key, recreate the managed container to load it:

```bash
sudo bash /opt/voltpilot/current/deploy/start.sh \
  "$(sudo cat /opt/voltpilot/current-image-id)" --replace --public-http
```

The script validates settings **without network access**, refuses unrelated
containers, and restores the prior managed container if startup fails. Do not use
`--replace` for the first launch. A plain Docker restart does not reload env-files.

## 3. Open the dashboard privately from Windows

In PowerShell, keep this SSH tunnel running while using the browser:

```powershell
ssh -N -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes -i C:\Users\MSI\.ssh\id_ed25519 -L 127.0.0.1:18080:127.0.0.1:18080 voltpilot@35.222.65.204
```

Open **http://127.0.0.1:18080**. No public firewall change is needed. Leave the API
base blank for same-origin access. Checking health spends no provider quota;
clicking Optimize sends one scenario with at most two backend provider attempts.

## 4. Bounded live acceptance check

Run on the VM after configuring and reloading. The temporary verifier uses the
production image and read-only verification inputs, without access to the key:

```bash
IMAGE="$(sudo cat /opt/voltpilot/current-image-id)"
ROOT="$(sudo readlink -f /opt/voltpilot/current)"
sudo docker run --rm --network host --user 10001:10001 \
  --cpus 2 --memory 2g --pids-limit 128 --cap-drop ALL \
  --security-opt no-new-privileges --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --mount "type=bind,src=$ROOT/scripts,dst=/srv/gridwise/scripts,readonly" \
  --mount "type=bind,src=$ROOT/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json,dst=/srv/gridwise/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json,readonly" \
  --entrypoint python "$IMAGE" -B -m scripts.validate_public_cases \
  --base-url http://127.0.0.1:18080 --case SAMPLE-01
```

Begin with one case, not an unbounded benchmark. Only after it passes and quota is
approved, omit `--case` for ten cases. Later use `--repeat 2` for a 20-request serial
latency sample. Document all failures and actual model identity; this is not a load
guarantee. Independently labeled new-language testing is still required.

## 5. Rotate the temporary key

```bash
sudo python3 -B /opt/voltpilot/current/scripts/configure_model.py --rotate
sudo bash /opt/voltpilot/current/deploy/start.sh \
  "$(sudo cat /opt/voltpilot/current-image-id)" --replace --public-http
```

Rotation atomically changes only the key and preserves settings including CORS.
Revoke the old key at the provider after the new one passes a bounded live test.
The script does not revoke provider credentials itself.

## 6. Public HTTP, temporary HTTPS, and Vercel frontend

The rubric permits public HTTP. Both exact API endpoints and the dashboard share
http://35.222.65.204, enabled explicitly with `--public-http`. Always pass that flag
when recreating this public deployment or it will revert to loopback-only access.

The project-specific `voltpilot-demo-tunnel.service` provides the temporary HTTPS
mirror https://fame-choice-amended-diabetes.trycloudflare.com. It does not modify
existing tunnels. Its URL changes on process restart and it has no uptime guarantee;
use the fixed-address HTTP origin for the form unless a named HTTPS origin is ready.

An owner-controlled DNS name or named tunnel is needed for stable HTTPS. Existing
Cloudflare processes on the VM belong to other services: do not replace or inspect
their tokens. A random quick-tunnel URL is not a stable judging endpoint.

Route the approved HTTPS origin to `http://127.0.0.1:18080`, preserve the exact
`/health` and `/optimize-energy` paths, and use proxy timeouts above the 25-second
application deadline. Verify externally before declaring the API public.

For Vercel, deploy only `/opt/voltpilot/current/frontend` (or the repository's
`frontend` root) as static files; the backend stays on GCP. The included
`vercel.json` rewrites exact judging paths to the fixed HTTP backend. Keep the
automatic same-origin connection: browser requests stay on Vercel HTTPS with no CORS
requirement. Disable Vercel production Deployment Protection so judges can call
the service without login. No Vercel credentials are bundled.
