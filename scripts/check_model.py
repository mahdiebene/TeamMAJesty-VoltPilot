"""Explicit paid/quota-consuming provider smoke check; no secrets or raw replies printed."""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

from app.config import Settings
from app.errors import GridWiseError
from app.llm import ModelInterpreter
from app.schemas import Scenario


async def check(list_models: bool) -> int:
    settings = Settings.from_environment()
    if not settings.api_key or not settings.base_url or (not list_models and not settings.model):
        print("Model configuration missing; set process variables privately. See README.")
        return 1
    async with httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=10) as client:
        if list_models:
            async with asyncio.timeout(15):
                async with client.stream("GET", settings.base_url.rstrip("/") + "/models",
                                         headers={"Authorization": "Bearer " + settings.api_key}) as response:
                    if response.status_code != 200:
                        print(f"Model-list request failed: HTTP {response.status_code}; response body omitted.")
                        return 1
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 1024 * 1024:
                            raise GridWiseError("model_list_too_large")
                    data = json.loads(bytes(body))
                    for model in data["data"]:
                        print(model["id"])
                    print("Listing alone does not verify inference access/quota.")
                    return 0
        root = Path(__file__).resolve().parents[1]
        case = json.loads((root / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json").read_text(encoding="utf-8-sig"))["cases"][0]
        scenario = Scenario.model_validate(case["input"])
        start = time.monotonic()
        async with asyncio.timeout(settings.deadline_seconds):
            directives = await ModelInterpreter(settings, client).interpret(scenario, start + settings.deadline_seconds)
        actual = [d.model_dump(exclude={"explanation"}) for d in directives]
        expected = [{k: v for k, v in d.items() if k != "explanation"} for d in case["expected_output"]["directive_interpretation"]]
        if actual != expected:
            print("FAIL: live interpretation differs from SAMPLE-01 ground truth. No raw model text logged.")
            return 1
        print(f"PASS: live SAMPLE-01 semantic smoke check; elapsed={time.monotonic() - start:.3f}s")
        print("Run the complete public and new-language suites next; one sample is not a release gate.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-models", action="store_true")
    args = parser.parse_args()
    try:
        return asyncio.run(check(args.list_models))
    except Exception as exc:
        print("Model check failed:", exc.code if isinstance(exc, GridWiseError) else type(exc).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())