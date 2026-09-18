import json
import unittest
from pathlib import Path

import httpx

from app.config import Settings
from app.main import create_app
from app.web import ASSETS
from tests.helpers import CASES, sample
from tests.test_api import FakeInterpreter


class DashboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_dashboard_assets_never_invoke_model(self):
        _, directives = sample()
        fake = FakeInterpreter(directives)
        app = create_app(Settings(), fake)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                for path in ["/", *("/assets/" + name for name in sorted(ASSETS))]:
                    response = await client.get(path)
                    self.assertEqual(response.status_code, 200, path)
                    self.assertEqual(response.headers["x-content-type-options"], "nosniff")
                    self.assertEqual(response.headers["cache-control"], "no-cache")
                    self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
                self.assertIn("text/javascript", (await client.get("/assets/core.mjs")).headers["content-type"])
                self.assertEqual(fake.calls, 0)

    async def test_static_allowlist_does_not_expose_source_or_configuration(self):
        app = create_app(Settings())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                for path in ["/.env", "/assets/.env", "/assets/../app/config.py", "/assets/%2e%2e%2fapp%2fconfig.py",
                             "/app/main.py", "/assets/vercel.json", "/assets/no-such-file"]:
                    self.assertEqual((await client.get(path)).status_code, 404, path)
                self.assertEqual((await client.get("/health")).status_code, 503)
                self.assertEqual((await client.get("/")).status_code, 200)

    def test_samples_are_exact_inputs_only(self):
        root = Path(__file__).resolve().parents[1]
        inputs = json.loads((root / "frontend" / "assets" / "samples.json").read_text(encoding="utf-8"))
        self.assertEqual(inputs, [{key: case[key] for key in ("id", "label", "input")} for case in CASES])