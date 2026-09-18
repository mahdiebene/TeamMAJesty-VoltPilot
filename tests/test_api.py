import asyncio
import json
import time
import unittest
from unittest.mock import patch

import httpx

from app.config import Settings
from app.errors import GridWiseError
from app.llm import ModelInterpreter
from app.main import create_app
from app.replay import replay
from tests.helpers import CASES, sample


class FakeInterpreter:
    """Test-only injection. Production cannot select this through configuration."""

    ready = True

    def __init__(self, directives, delay=0):
        self.directives = directives
        self.delay = delay
        self.calls = 0

    async def interpret(self, scenario, deadline):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return self.directives


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_pipeline_with_injected_reference_interpreter(self):
        fake = FakeInterpreter([])
        app = create_app(Settings(), interpreter=fake)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                self.assertEqual((await client.get("/health")).json(), {"status": "ok"})
                for index, case in enumerate(CASES):
                    with self.subTest(case=case["id"]):
                        scenario, fake.directives = sample(index)
                        response = await client.post("/optimize-energy", json=case["input"])
                        self.assertEqual(response.status_code, 200, response.text)
                        result = replay(scenario, fake.directives, response.json())
                        self.assertAlmostEqual(result.total_cost_bdt, case["expected_output"]["total_cost_bdt"])
                self.assertEqual(fake.calls, 10)

    async def test_unconfigured_model_is_not_ready(self):
        app = create_app(Settings())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                self.assertEqual((await client.get("/health")).status_code, 503)
                response = await client.post("/optimize-energy", json=CASES[0]["input"])
                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.json()["error"]["code"], "model_not_configured")

    async def test_bad_input_does_not_call_model_and_service_recovers(self):
        _, items = sample()
        fake = FakeInterpreter(items)
        app = create_app(Settings(), fake)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                for body in ["{", "[]", "null", '{"a":1,"a":2}', '{"a":NaN}', "{}"]:
                    response = await client.post("/optimize-energy", content=body)
                    self.assertEqual(response.status_code, 400, response.text)
                oversized = await client.post("/optimize-energy", content=b" " * (1024 * 1024 + 1))
                self.assertEqual(oversized.status_code, 400)
                self.assertEqual(fake.calls, 0)
                self.assertEqual((await client.post("/optimize-energy", json=CASES[0]["input"])).status_code, 200)

    async def test_deadline_and_failure_recovery(self):
        _, items = sample()
        fake = FakeInterpreter(items, delay=0.15)
        app = create_app(Settings(deadline_seconds=0.1, attempt_seconds=0.05), fake)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/optimize-energy", json=CASES[0]["input"])
                self.assertEqual(response.json()["error"]["code"], "request_deadline")
                self.assertEqual(app.state.pending, 0)
                fake.delay = 0
                # Normal deployment uses 25s; this deliberately tiny test deadline
                # leaves no solver margin, but health and parsing still recover.
                self.assertEqual((await client.get("/health")).status_code, 200)
                self.assertEqual((await client.post("/optimize-energy", content="{")).status_code, 400)

    async def test_provider_failure_is_sanitized_and_next_request_works(self):
        _, items = sample()
        fake = FakeInterpreter(items)
        app = create_app(Settings(), fake)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                with patch.object(fake, "interpret", side_effect=RuntimeError("sensitive-provider-detail")):
                    response = await client.post("/optimize-energy", json=CASES[0]["input"])
                    self.assertEqual(response.status_code, 500)
                    self.assertNotIn("sensitive-provider-detail", response.text)
                response = await client.post("/optimize-energy", json=CASES[0]["input"])
                self.assertEqual(response.status_code, 200)

    async def test_concurrency_admission_is_bounded(self):
        _, items = sample()
        fake = FakeInterpreter(items, delay=0.1)
        app = create_app(Settings(concurrency=1, max_pending=1), fake)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                first = asyncio.create_task(client.post("/optimize-energy", json=CASES[0]["input"]))
                for _ in range(100):
                    if fake.calls:
                        break
                    await asyncio.sleep(0.001)
                second = await client.post("/optimize-energy", json=CASES[0]["input"])
                self.assertEqual(second.json()["error"]["code"], "service_busy")
                self.assertEqual((await first).status_code, 200)
                self.assertEqual(app.state.pending, 0)

    async def test_deadline_covers_body_receive(self):
        _, items = sample()
        app = create_app(Settings(deadline_seconds=0.05, attempt_seconds=0.02), FakeInterpreter(items))

        async def slow_body():
            yield b"{"
            await asyncio.sleep(0.2)
            yield b"}"

        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/optimize-energy", content=slow_body())
                self.assertEqual(response.json()["error"]["code"], "request_deadline")

    async def test_cancelled_solver_retains_slot_until_thread_finishes(self):
        import threading
        _, items = sample()
        scenario, _ = sample()
        from app.optimizer import optimize
        result = optimize(scenario, items)
        started, finish = threading.Event(), threading.Event()

        def held_solver(*args):
            started.set()
            finish.wait(timeout=2)
            return result

        app = create_app(Settings(deadline_seconds=0.3, attempt_seconds=0.1, concurrency=1, max_pending=1), FakeInterpreter(items))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                try:
                    with patch("app.main.optimize", side_effect=held_solver):
                        response = await client.post("/optimize-energy", json=CASES[0]["input"])
                        self.assertTrue(started.is_set())
                        self.assertEqual(response.json()["error"]["code"], "request_deadline")
                        self.assertEqual(app.state.pending, 1)
                        busy = await client.post("/optimize-energy", json=CASES[0]["input"])
                        self.assertEqual(busy.json()["error"]["code"], "service_busy")
                finally:
                    finish.set()
                for _ in range(100):
                    if app.state.pending == 0:
                        break
                    await asyncio.sleep(0.005)
                self.assertEqual(app.state.pending, 0)
                self.assertEqual((await client.post("/optimize-energy", json=CASES[0]["input"])).status_code, 200)


class ModelClientTests(unittest.IsolatedAsyncioTestCase):
    def settings(self, **kwargs):
        return Settings(api_key="test-only-not-a-secret", base_url="https://model.example/v1", model="test-model", **kwargs)

    def reply(self, items):
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
            "directive_interpretation": [item.model_dump() for item in items],
        })}}]}

    async def test_actual_http_payload_and_validated_response(self):
        scenario, items = sample()
        seen = []

        def handler(request):
            seen.append(request)
            data = json.loads(request.content)
            self.assertEqual(data["response_format"], {"type": "json_object"})
            self.assertNotIn("hours", json.loads(data["messages"][1]["content"]))
            self.assertIn("battery", json.loads(data["messages"][1]["content"]))
            return httpx.Response(200, json=self.reply(items))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            output = await ModelInterpreter(self.settings(), client).interpret(scenario, time.monotonic() + 5)
        self.assertEqual(output, items)
        self.assertEqual(len(seen), 1)
        self.assertEqual(str(seen[0].url), "https://model.example/v1/chat/completions")

    async def test_malformed_output_has_one_repair(self):
        scenario, items = sample()
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={} if len(calls) == 1 else self.reply(items))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            self.assertEqual(await ModelInterpreter(self.settings(), client).interpret(scenario, time.monotonic() + 5), items)
        self.assertEqual(len(calls), 2)

    async def test_invalid_output_never_becomes_noop(self):
        scenario, _ = sample()
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={"secret-provider-body": "not-for-output"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaisesRegex(GridWiseError, "invalid_model_output"):
                await ModelInterpreter(self.settings(), client).interpret(scenario, time.monotonic() + 5)
        self.assertEqual(len(calls), 2)

    async def test_authentication_errors_not_retried(self):
        scenario, _ = sample()
        for status in [401, 403]:
            calls = []

            def handler(request):
                calls.append(request)
                return httpx.Response(status, text="sensitive-body")

            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with self.assertRaisesRegex(GridWiseError, "model_access_denied"):
                    await ModelInterpreter(self.settings(), client).interpret(scenario, time.monotonic() + 5)
            self.assertEqual(len(calls), 1)

    async def test_retry_after_cannot_exceed_budget(self):
        scenario, _ = sample()
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda r: httpx.Response(429, headers={"Retry-After": "120"}))) as client:
            with self.assertRaisesRegex(GridWiseError, "model_unavailable"):
                await ModelInterpreter(self.settings(), client).interpret(scenario, time.monotonic() + 2)

    async def test_provider_timeout_is_bounded(self):
        scenario, _ = sample()

        async def handler(request):
            await asyncio.sleep(0.2)
            return httpx.Response(200, json={})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaisesRegex(GridWiseError, "model_timeout"):
                await ModelInterpreter(self.settings(attempt_seconds=0.02), client).interpret(scenario, time.monotonic() + 5)


class ConfigurationTests(unittest.TestCase):
    def test_openapi_references_resolve(self):
        document = create_app(Settings()).openapi()

        def inspect(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    target = document
                    for key in value["$ref"].removeprefix("#/").split("/"):
                        target = target[key]
                for child in value.values():
                    inspect(child)
            elif isinstance(value, list):
                for child in value:
                    inspect(child)

        inspect(document)
        self.assertIn("requestBody", document["paths"]["/optimize-energy"]["post"])

    def test_unsafe_urls_and_timeouts(self):
        for url in ["http://remote.example/v1", "https://user:password@remote.example/v1", "https://remote.example/?key=x"]:
            with self.assertRaises(ValueError):
                Settings(base_url=url)
        for value in [0, 30, float("inf"), float("nan")]:
            with self.assertRaises(ValueError):
                Settings(deadline_seconds=value)
        self.assertNotIn("private-test-value", repr(Settings(api_key="private-test-value")))


if __name__ == "__main__":
    unittest.main()