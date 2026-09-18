"""HTTP contract, whole-request deadline, bounded execution, and safe errors."""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.config import Settings
from app.errors import GridWiseError
from app.json_utils import load_json
from app.llm import ModelInterpreter
from app.optimizer import optimize
from app.schemas import Scenario, Schedule
from app.web import router as web_router

LOG = logging.getLogger("gridwise")


class RequestBoundary:
    """ASGI deadline includes body receive, queueing, work, and serialization.

    Buffer the small JSON response until complete so an error never follows a
    partially sent success. Network delivery to a slow/disconnected client cannot
    be guaranteed; response bytes must be produced within the internal deadline.
    """

    def __init__(self, app, seconds: float):
        self.app = app
        self.seconds = seconds

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        start = time.monotonic()
        scope["gridwise.deadline"] = start + self.seconds
        messages = []
        size = 0

        async def bounded_receive():
            nonlocal size
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > 1024 * 1024:
                    raise GridWiseError("request_too_large")
            return message

        async def collect(message):
            messages.append(message)

        code = None
        try:
            async with asyncio.timeout(self.seconds):
                await self.app(scope, bounded_receive, collect)
            # CPU-only parsing/serialization may finish without an await at which
            # cancellation can fire. Never send a late buffered success anyway.
            if time.monotonic() >= scope["gridwise.deadline"]:
                code = "request_deadline"
        except TimeoutError:
            code = "request_deadline"
        except GridWiseError as exc:
            code = exc.code
        except Exception:
            # No exception text, request contents, provider body, or stack trace.
            code = "internal_error"
        if code:
            LOG.warning("request_failed category=%s elapsed_ms=%.1f", code, (time.monotonic() - start) * 1000)
            response = JSONResponse({"error": {"code": code}}, status_code=400 if code == "request_too_large" else 500)
            await response(scope, receive, send)
        else:
            for message in messages:
                await send(message)


def create_app(settings: Settings | None = None, interpreter=None) -> FastAPI:
    settings = settings or Settings.from_environment()

    @asynccontextmanager
    async def lifespan(application):
        async with httpx.AsyncClient(
            follow_redirects=False, trust_env=False,
            limits=httpx.Limits(max_connections=settings.concurrency, max_keepalive_connections=settings.concurrency),
        ) as client:
            application.state.interpreter = interpreter or ModelInterpreter(settings, client)
            application.state.slots = asyncio.Semaphore(settings.concurrency)
            application.state.pending = 0
            executor = ThreadPoolExecutor(max_workers=settings.concurrency, thread_name_prefix="gridwise-lp")
            application.state.executor = executor
            try:
                yield
            finally:
                executor.shutdown(wait=True, cancel_futures=True)

    application = FastAPI(title="VoltPilot | GridWise", version="0.1.0", lifespan=lifespan)
    application.include_router(web_router)
    application.add_middleware(RequestBoundary, seconds=settings.deadline_seconds)
    if settings.cors_origins:
        # Outside RequestBoundary so safe error responses also carry CORS headers.
        application.add_middleware(
            CORSMiddleware, allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
            allow_credentials=False, max_age=600,
        )

    def contract_openapi():
        if application.openapi_schema is None:
            document = get_openapi(title=application.title, version=application.version, routes=application.routes)
            schema = Scenario.model_json_schema(ref_template="#/components/schemas/{model}")
            components = document.setdefault("components", {}).setdefault("schemas", {})
            components.update(schema.pop("$defs", {}))
            components["Scenario"] = schema
            document["paths"]["/optimize-energy"]["post"]["requestBody"] = {
                "required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Scenario"}}},
            }
            application.openapi_schema = document
        return application.openapi_schema

    application.openapi = contract_openapi

    @application.get("/health")
    async def health():
        if not application.state.interpreter.ready:
            return JSONResponse({"status": "not_ready"}, status_code=503)
        return {"status": "ok"}

    @application.post("/optimize-energy", response_model=Schedule)
    async def optimize_energy(request: Request):
        try:
            scenario = Scenario.model_validate(load_json(await request.body()))
        except (ValueError, TypeError, RecursionError, ValidationError):
            return JSONResponse({"error": {"code": "invalid_request"}}, status_code=400)
        state = application.state
        if not state.interpreter.ready:
            raise GridWiseError("model_not_configured")
        if state.pending >= settings.max_pending:
            raise GridWiseError("service_busy")
        state.pending += 1
        acquired = False
        future = None

        def release(completed=None):
            state.slots.release()
            state.pending -= 1
            if completed is not None and not completed.cancelled():
                completed.exception()  # Consume late solver failure after request cancellation.

        try:
            await state.slots.acquire()
            acquired = True
            deadline = request.scope["gridwise.deadline"]
            directives = await state.interpreter.interpret(scenario, deadline)
            budget = min(3.0, deadline - time.monotonic() - 0.1)
            if budget <= 0:
                raise GridWiseError("request_deadline")
            future = asyncio.get_running_loop().run_in_executor(state.executor, optimize, scenario, directives, budget)
            result = await asyncio.shield(future)
            return JSONResponse(result.model_dump(mode="json"))
        finally:
            if not acquired:
                state.pending -= 1
            elif future is not None and not future.done():
                # Cancellation doesn't stop a native solver. Retain its slot until done.
                future.add_done_callback(release)
            else:
                release()

    return application


app = create_app()