import os
import unittest
from unittest.mock import patch

import httpx

from app.config import Settings
from app.main import create_app
from tests.helpers import CASES, sample
from tests.test_api import FakeInterpreter


ORIGIN = "https://voltpilot-demo.vercel.app"


class CorsTests(unittest.IsolatedAsyncioTestCase):
    async def test_allowed_origin_preflight_success_and_safe_errors(self):
        _, directives = sample()
        interpreter = FakeInterpreter(directives)
        app = create_app(Settings(cors_origins=(ORIGIN,)), interpreter)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                preflight = await client.options("/optimize-energy", headers={
                    "Origin": ORIGIN, "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                })
                self.assertEqual(preflight.status_code, 200)
                self.assertEqual(interpreter.calls, 0)
                self.assertEqual(preflight.headers["access-control-allow-origin"], ORIGIN)
                self.assertNotIn("access-control-allow-credentials", preflight.headers)
                response = await client.post("/optimize-energy", headers={"Origin": ORIGIN}, json=CASES[0]["input"])
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["access-control-allow-origin"], ORIGIN)
                for body in (b"{", b" " * (1024 * 1024 + 1)):
                    response = await client.post("/optimize-energy", headers={"Origin": ORIGIN}, content=body)
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.headers["access-control-allow-origin"], ORIGIN)
                interpreter.ready = False
                response = await client.post("/optimize-energy", headers={"Origin": ORIGIN}, json=CASES[0]["input"])
                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.headers["access-control-allow-origin"], ORIGIN)

    async def test_unlisted_origins_and_methods_are_not_enabled(self):
        app = create_app(Settings(cors_origins=(ORIGIN,)))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                for origin, method in (("https://untrusted.vercel.app", "POST"), (ORIGIN, "DELETE")):
                    response = await client.options("/optimize-energy", headers={
                        "Origin": origin, "Access-Control-Request-Method": method,
                    })
                    self.assertEqual(response.status_code, 400)
                response = await client.get("/health", headers={"Origin": "https://untrusted.vercel.app"})
                self.assertNotIn("access-control-allow-origin", response.headers)

    async def test_cors_disabled_by_default(self):
        app = create_app(Settings())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/health", headers={"Origin": ORIGIN})
                self.assertNotIn("access-control-allow-origin", response.headers)


class CorsConfigurationTests(unittest.TestCase):
    def test_only_exact_safe_origins(self):
        for origin in (ORIGIN, "http://localhost:3000", "http://127.0.0.1:5173", "http://[::1]:3000"):
            Settings(cors_origins=(origin,))
        for origin in ("*", "null", "https://*.vercel.app", "https://site.test/", "https://site.test/path",
                       "http://site.test", "https://user:pass@site.test", "https://site.test?key=x",
                       "https://site.test#x", "https://site.test:invalid", "https://site.test\n"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                Settings(cors_origins=(origin,))

    def test_environment_parsing(self):
        with patch.dict(os.environ, {"CORS_ORIGINS": f" {ORIGIN}, http://localhost:3000, "}, clear=True):
            self.assertEqual(Settings.from_environment().cors_origins, (ORIGIN, "http://localhost:3000"))


if __name__ == "__main__":
    unittest.main()