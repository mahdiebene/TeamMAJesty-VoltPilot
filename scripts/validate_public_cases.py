"""Replay public cases offline or through a live endpoint, never by schedule equality."""

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path

import httpx

from app.errors import GridWiseError
from app.optimizer import optimize
from app.replay import replay
from app.schemas import Directive, Scenario

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true", help="Use reference directives, no model/API readiness claim")
    mode.add_argument("--base-url", help="Live GridWise service URL")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    cases = json.loads((ROOT / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json").read_text(encoding="utf-8-sig"))["cases"]
    failures = 0
    timings = []
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
        for _ in range(args.repeat):
            for case in cases:
                start = time.perf_counter()
                try:
                    scenario = Scenario.model_validate(case["input"])
                    expected = case["expected_output"]
                    directives = [Directive.model_validate(d) for d in expected["directive_interpretation"]]
                    if args.offline:
                        payload = json.loads(optimize(scenario, directives).model_dump_json())
                    else:
                        response = client.post(args.base_url.rstrip("/") + "/optimize-energy", json=case["input"])
                        if response.status_code != 200:
                            raise GridWiseError("http_" + str(response.status_code))
                        payload = response.json()
                    result = replay(scenario, directives, payload)
                    if abs(result.total_cost_bdt - expected["total_cost_bdt"]) > 0.01:
                        raise GridWiseError("nonoptimal_cost")
                    elapsed = time.perf_counter() - start
                    if elapsed >= 30:
                        raise GridWiseError("latency_exceeded")
                    print(f"PASS {case['id']} cost={result.total_cost_bdt:.6f} elapsed={elapsed:.3f}s")
                except Exception as exc:
                    failures += 1
                    category = exc.code if isinstance(exc, GridWiseError) else type(exc).__name__
                    print(f"FAIL {case['id']} category={category}")
                finally:
                    timings.append(time.perf_counter() - start)
    ordered = sorted(timings)
    p95 = ordered[math.ceil(len(ordered) * 0.95) - 1]
    print(f"requests={len(timings)} failures={failures} concurrency=1 p50={statistics.median(timings):.3f}s p95={p95:.3f}s")
    print("OFFLINE reference-directive checks only." if args.offline else "LIVE requests; record actual configured model identity separately.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())