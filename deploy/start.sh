#!/usr/bin/env bash
# Run as root on the approved VM. Never source the secret env-file into a shell.
set -euo pipefail
umask 077
if [[ ${EUID} -ne 0 || $# -lt 1 || $# -gt 3 ]]; then
  echo 'Usage: sudo bash /opt/voltpilot/current/deploy/start.sh IMAGE [--allow-unconfigured|--replace] [--public-http]'
  exit 1
fi
image=$1
shift
mode=
public_http=false
for option in "$@"; do
  case "$option" in
    --allow-unconfigured|--replace) [[ -z "$mode" ]] || { echo 'Conflicting modes'; exit 1; }; mode=$option ;;
    --public-http) public_http=true ;;
    *) echo 'Unknown option'; exit 1 ;;
  esac
done
name=voltpilot-api
backup=voltpilot-api-previous
env_file=/etc/voltpilot/voltpilot.env
env_args=()
if [[ -f "$env_file" ]]; then
  python3 - "$env_file" <<'PY'
import os
import stat
import sys
from pathlib import Path
p = Path(sys.argv[1])
for item, expected in ((p.parent, 0o700), (p, 0o600)):
    metadata = item.lstat()
    if item.is_symlink() or metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != expected:
        sys.exit('Unsafe runtime configuration ownership/permissions; refused.')
PY
  env_args=(--env-file "$env_file")
elif [[ "$mode" != --allow-unconfigured ]]; then
  echo 'Model environment is missing. Use the private configuration helper first.'
  exit 1
fi
image_id=$(docker image inspect --format '{{.Id}}' "$image")
source=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.source"}}' "$image_id")
[[ "$source" == https://github.com/mahdiebene/TeamMAJesty-VoltPilot ]] || { echo 'Unexpected image source; refused.'; exit 1; }
runtime_user=$(docker image inspect --format '{{.Config.User}}' "$image_id")
case "$runtime_user" in ''|root|0|0:*) echo 'Image must run as non-root; refused.'; exit 1 ;; esac
security=(--cpus 2 --memory 2g --pids-limit 128 --cap-drop ALL --security-opt no-new-privileges --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m)
check='from app.config import Settings; import sys; s=Settings.from_environment(); sys.exit(0 if s.ready else 1)'
if [[ ${#env_args[@]} -gt 0 ]]; then
  if ! docker run --rm --network none "${security[@]}" "${env_args[@]}" --entrypoint python "$image_id" -B -c "$check" >/dev/null 2>&1; then
    echo 'Runtime configuration is incomplete or invalid; no existing container changed.'
    exit 1
  fi
fi
existing=false
if docker container inspect "$name" >/dev/null 2>&1; then
  [[ "$mode" == --replace ]] || { echo 'Container already exists; use --replace to reload approved configuration.'; exit 1; }
  owner=$(docker inspect --format '{{index .Config.Labels "io.voltpilot.managed"}}' "$name")
  [[ "$owner" == true ]] || { echo 'Existing container is not managed by this script; refused.'; exit 1; }
  if docker container inspect "$backup" >/dev/null 2>&1; then echo 'Prior rollback container exists; inspect it before replacing.'; exit 1; fi
  existing=true
elif ss -H -lnt 'sport = :18080' | grep -q .; then
  echo 'Port 18080 is already occupied; refused.'
  exit 1
fi
publish=(--publish 127.0.0.1:18080:8080)
if [[ "$public_http" == true ]]; then
  # Only an explicit flag exposes this synthetic-data judge API. No firewall edits.
  if ss -H -lnt 'sport = :80' | grep -q .; then
    owned_port=
    if [[ "$existing" == true ]]; then
      owned_port=$(docker port "$name" 8080/tcp)
    fi
    grep -Fxq '0.0.0.0:80' <<< "$owned_port" || { echo 'Public port 80 belongs to another service; refused.'; exit 1; }
  fi
  publish+=(--publish 0.0.0.0:80:8080)
fi
created=false
renamed=false
rollback() {
  rc=$?
  if [[ $rc -ne 0 ]]; then
    if [[ "$created" == true ]]; then docker rm --force "$name" >/dev/null 2>&1 || true; fi
    if [[ "$renamed" == true ]]; then docker rename "$backup" "$name"; docker start "$name" >/dev/null; fi
    echo 'Deployment failed; previous managed container restored where available.'
  fi
  exit "$rc"
}
trap rollback EXIT
if [[ "$existing" == true ]]; then
  docker rename "$name" "$backup"
  renamed=true
  docker stop --time 30 "$backup" >/dev/null
fi
docker create --name "$name" --label io.voltpilot.managed=true --restart unless-stopped \
  "${security[@]}" "${env_args[@]}" --log-opt max-size=10m --log-opt max-file=3 \
  "${publish[@]}" "$image_id" >/dev/null
created=true
docker start "$name" >/dev/null
expected=200
if [[ ${#env_args[@]} -eq 0 ]]; then expected=503; fi
ready=false
for attempt in $(seq 1 45); do
  code=$(curl --silent --output /dev/null --max-time 2 --noproxy '*' --write-out '%{http_code}' http://127.0.0.1:18080/health || true)
  if [[ "$code" == "$expected" ]]; then ready=true; break; fi
  sleep 1
done
[[ "$ready" == true ]] || { echo 'Unexpected readiness status'; exit 1; }
curl --fail --silent --max-time 5 --noproxy '*' --output /dev/null http://127.0.0.1:18080/
if [[ "$renamed" == true ]]; then docker rm "$backup" >/dev/null; fi
trap - EXIT
printf 'VoltPilot running on 127.0.0.1:18080; health HTTP %s. No live model request sent.\n' "$expected"
if [[ "$expected" == 503 ]]; then echo 'Explicit unconfigured staging only: dashboard works; inference is NOT ready.'; fi
if [[ "$public_http" == true ]]; then echo 'Explicit public HTTP enabled on port 80; no TLS. Use synthetic inputs only.'; fi