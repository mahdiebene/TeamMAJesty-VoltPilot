"""Exercise a built Docker image without sending any real provider requests."""

import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]


def docker(*args: str) -> str:
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True, timeout=180).stdout.strip()


def probe(base: str, path: str, body: bytes | None = None) -> tuple[int, dict]:
    request = Request(base + path, data=body, headers={"Content-Type": "application/json"})
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
            return response.status, json.load(response)
    except HTTPError as response:
        return response.code, json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    # Mount only verification inputs; all production code/dependencies come from the image.
    mounts = []
    for name in ("tests", "scripts", "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"):
        mounts.extend(["--mount", f"type=bind,src={ROOT / name},dst=/srv/gridwise/{name},readonly"])
    security = ["--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--memory", "2g", "--cpus", "2", "--pids-limit", "128"]
    for command in (("unittest", "discover", "-s", "tests", "-t", ".", "-q"),
                    ("scripts.validate_public_cases", "--offline")):
        output = docker("run", "--rm", "--network", "none", *security, *mounts, "--entrypoint", "python",
                        args.image, "-B", "-m", *command)
        print(output or "PASS in-image deterministic tests")
    user = docker("image", "inspect", "--format", "{{.Config.User}}", args.image)
    assert user not in ("", "root", "0", "0:0"), "Image must run as non-root"
    for configured in (False, True):
        name = "voltpilot-smoke-" + uuid.uuid4().hex[:12]
        environment = []
        if configured:
            # Readiness is local configuration, not a claim that this fake provider works.
            environment = ["--env", "LLM_API_KEY=container-readiness-test-only",
                           "--env", "LLM_BASE_URL=https://example.invalid/v1",
                           "--env", "LLM_MODEL=container-readiness-test-only"]
        try:
            docker("run", "--detach", "--name", name, *security, *environment,
                   "--publish", "127.0.0.1::8080", args.image)
            port = docker("inspect", "--format", '{{(index (index .NetworkSettings.Ports "8080/tcp") 0).HostPort}}', name)
            base = "http://127.0.0.1:" + port
            deadline = time.monotonic() + 55
            while True:
                try:
                    status, payload = probe(base, "/health")
                    break
                except (URLError, OSError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Container startup exceeded 55 seconds") from None
                    time.sleep(0.25)
            assert (status, payload) == ((200, {"status": "ok"}) if configured else (503, {"status": "not_ready"}))
            with build_opener(ProxyHandler({})).open(base + "/", timeout=3) as response:
                assert response.status == 200 and b"VoltPilot" in response.read()
                assert response.headers["X-Content-Type-Options"] == "nosniff"
            status, samples = probe(base, "/assets/samples.json")
            assert status == 200 and len(samples) == 10 and "expected_output" not in samples[0]
            assert probe(base, "/optimize-energy", b"{") == (400, {"error": {"code": "invalid_request"}})
            status, schema = probe(base, "/openapi.json")
            assert status == 200 and "/optimize-energy" in schema["paths"]
            if not configured:
                case = json.loads((ROOT / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json").read_text(encoding="utf-8-sig"))["cases"][0]
                assert probe(base, "/optimize-energy", json.dumps(case["input"]).encode()) == (
                    500, {"error": {"code": "model_not_configured"}})
            print(f"PASS container HTTP, non-root, read-only; configured={configured}; no live inference")
        finally:
            subprocess.run(["docker", "rm", "--force", name], capture_output=True, timeout=20)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError:
        # Do not echo command environments or arbitrary Docker/provider diagnostics.
        raise SystemExit("Container command failed; inspect the build/runtime safely.") from None