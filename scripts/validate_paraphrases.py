"""Small independently labeled language suite; production never imports these cases."""

import argparse
import json
import time
from pathlib import Path

import httpx

from app.errors import GridWiseError
from app.optimizer import optimize
from app.replay import replay
from app.schemas import Directive, Scenario


ROOT = Path(__file__).resolve().parents[1]
# Labels are specified before any model request, not copied from model responses.
# Numeric conditions are equivalent to their public base cases, retaining known costs.
PARAPHRASES = (
    ("SAMPLE-01", [
        "Between 12:00 and 14:00 today, panel washing cuts the forecast PV output by seventy-five percent.",
        "Next month's sports registration closes on a different date.",
    ]),
    ("SAMPLE-02", [
        "Taking energy into the battery is prohibited starting at 02:00 and ending at 05:00 today; taking energy out is unaffected.",
    ]),
    ("SAMPLE-03", [
        "Throughout the 18:00 to 21:00 window, retain one-half of the battery's full nameplate capacity, not half of its starting charge.",
    ]),
    ("SAMPLE-04", [
        "During today's two-hour test beginning at 6 in the evening, no energy may be drawn out of storage. Charging remains permitted.",
    ]),
    ("SAMPLE-05", [
        "For each hourly interval from 18:00 up to 21:00, utility purchases are limited to one hundred fifty-five kilowatt-hours.",
    ]),
    ("SAMPLE-06", [
        "From ten in the morning until midday today, only fifty percent of predicted photovoltaic generation will be usable.",
        "Do not add energy to storage during the two hours beginning at 14:00 today.",
        "The library's new book-return policy starts next week, not today.",
    ]),
    ("SAMPLE-09", [
        "Between 11:00 and 14:00 today, rooftop PV is reduced TO twenty percent of forecast, rather than BY twenty percent.",
        "Tomorrow the student affairs office posts the club notices.",
    ]),
)


def cases() -> list[dict]:
    public = json.loads((ROOT / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json").read_text(encoding="utf-8-sig"))["cases"]
    by_id = {case["id"]: case for case in public}
    result = []
    for index, (base_id, notes) in enumerate(PARAPHRASES, 1):
        base = by_id[base_id]
        scenario = dict(base["input"], scenario_id=f"PARAPHRASE-{index:02d}", operator_notes=notes)
        result.append({"input": scenario, "expected_output": base["expected_output"]})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true", help="Validate labels and optimizer only; NOT a language-model test")
    mode.add_argument("--base-url", help="Send seven real scenarios (up to fourteen provider attempts)")
    args = parser.parse_args()
    failures = 0
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
        for case in cases():
            scenario = Scenario.model_validate(case["input"])
            expected = case["expected_output"]
            directives = [Directive.model_validate(value) for value in expected["directive_interpretation"]]
            start = time.perf_counter()
            try:
                if args.offline:
                    payload = optimize(scenario, directives).model_dump(mode="json")
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
                print(f"PASS {scenario.scenario_id} cost={result.total_cost_bdt:.6f} elapsed={elapsed:.3f}s")
            except Exception as exc:
                failures += 1
                category = exc.code if isinstance(exc, GridWiseError) else type(exc).__name__
                print(f"FAIL {scenario.scenario_id} category={category}")
    print(f"cases={len(PARAPHRASES)} failures={failures}; " + (
        "OFFLINE label checks, no language-model evidence." if args.offline else "LIVE independently labeled paraphrases; not organizer hidden tests."))
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())