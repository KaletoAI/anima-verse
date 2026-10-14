#!/usr/bin/env python3
"""Smoke for per-route ASGI timing; no server or world database is imported.

Hand calculation: two /a/1 calls each sleep 0.3 s = 300 ms, so one
/a/{x} bucket has n=2, median >=300 ms and two slow JSONL rows. Each
response is b"demo" = 4 bytes. /b throws once and /c returns 503 once:
each has errors=1. SSE yields immediately, then waits 0.5 s: streams=1,
first-chunk time <250 ms, and zero log rows despite its 500 ms lifetime.
The Starlette app uses FastAPI APIRoute objects, which populate scope["route"]
during real matching (plain Starlette Route objects do not).
A disconnect followed by CancelledError contributes exactly one aborted
sample, under the fixed unmatched bucket rather than the raw URL.
Four mid-body send failures each add n=1, aborted=1, errors=0.
Two FOO requests (ordinary and SSE) each use OTHER with n=1; only SSE
has streams=1. Neither adds a slow log row. The production stack adds
two /stack/items/{x} successes (n=2, errors=0) and one /stack/error
failure after 0.3 s (n=1, errors=1, status=500, bytes=0).
The log therefore has 2 + 1 = 3 rows. Timing is registered last, outside
three passthrough HTTP layers and CORS, inside ServerErrorMiddleware.
"""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace

from anyio import BrokenResourceError, ClosedResourceError
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import ClientDisconnect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from starlette.applications import Starlette
from starlette.responses import Response, StreamingResponse
from fastapi.routing import APIRoute
from fastapi.middleware.asyncexitstack import AsyncExitStackMiddleware
from starlette.requests import Request
from starlette.concurrency import run_in_threadpool
from app.core import request_timing


async def main():
    async def a(request: Request):
        await run_in_threadpool(time.sleep, 0.3)
        return Response(b"demo")

    async def b(request: Request):
        raise RuntimeError("expected smoke error")

    async def c(request: Request):
        return Response(status_code=503)

    async def sse(request: Request):
        async def chunks():
            yield b"data: one\n\n"
            await asyncio.sleep(0.5)
            yield b"data: two\n\n"
        return StreamingResponse(chunks(), media_type="text/event-stream")

    app = request_timing.RequestTimingMiddleware(AsyncExitStackMiddleware(Starlette(routes=[
        APIRoute("/a/{x}", a), APIRoute("/b", b), APIRoute("/c", c), APIRoute("/sse", sse)])))

    async def call(target, path, method="GET", send_error=None):
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                 "method": method, "path": path, "raw_path": path.encode(),
                 "query_string": b"", "headers": [], "scheme": "http",
                 "server": ("test", 80), "client": ("test", 1), "root_path": ""}
        messages = []
        async def receive():
            return {"type": "http.disconnect"}
        async def send(message):
            if message["type"] == "http.response.start" and path.startswith("/a/"):
                assert scope["route"].path == "/a/{x}", scope
            if (send_error is not None and message["type"] == "http.response.body"
                    and messages[-1]["type"] == "http.response.body"):
                raise send_error
            messages.append(message)
        await target(scope, receive, send)
        return messages

    with tempfile.TemporaryDirectory() as tmp:
        request_timing.LOG_FILE = Path(tmp) / "logs/request_timing.jsonl"
        for _ in range(2):
            await call(app, "/a/1")
        try:
            await call(app, "/b")
        except RuntimeError:
            pass
        else:
            raise AssertionError("application exception was swallowed")
        await call(app, "/c")
        await call(app, "/sse")

        async def disconnected(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            assert (await receive())["type"] == "http.disconnect"
            raise asyncio.CancelledError()
        try:
            await call(request_timing.RequestTimingMiddleware(disconnected), "/unique/123")
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancellation was swallowed")

        for error_type in (OSError, ClosedResourceError, BrokenResourceError, ClientDisconnect):
            route = "/send/" + error_type.__name__

            async def mid_body(scope, receive, send):
                scope["route"] = SimpleNamespace(path=route)
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"one", "more_body": True})
                await send({"type": "http.response.body", "body": b"two"})

            try:
                await call(request_timing.RequestTimingMiddleware(mid_body), route,
                           send_error=error_type())
            except error_type:
                pass
            else:
                raise AssertionError("send exception was swallowed")
            sample = next(r for r in request_timing.route_stats() if r["route"] == route)
            assert sample["n"] == 1 and sample["aborted"] == 1 and sample["errors"] == 0, sample

        for is_stream, route in ((False, "/method/ordinary"), (True, "/method/sse")):
            async def unusual_method(scope, receive, send):
                scope["route"] = SimpleNamespace(path=route)
                headers = [(b"content-type", b"text/event-stream")] if is_stream else []
                await send({"type": "http.response.start", "status": 200, "headers": headers})
                await send({"type": "http.response.body", "body": b"demo"})

            await call(request_timing.RequestTimingMiddleware(unusual_method), route, method="FOO")
            sample = next(r for r in request_timing.route_stats() if r["route"] == route)
            assert sample["method"] == "OTHER" and sample["n"] == 1, sample
            assert sample["streams"] == int(is_stream), sample

        production = FastAPI()

        @production.get("/stack/items/{x}")
        async def stack_ok(x: str):
            return Response(b"demo")

        @production.get("/stack/error")
        async def stack_error():
            await asyncio.sleep(0.3)
            raise RuntimeError("expected production-stack error")

        @production.middleware("http")
        async def auth_passthrough(request, call_next):
            return await call_next(request)

        production.add_middleware(CORSMiddleware, allow_origins=["*"])

        @production.middleware("http")
        async def context_passthrough(request, call_next):
            return await call_next(request)

        @production.middleware("http")
        async def activity_passthrough(request, call_next):
            return await call_next(request)

        production.add_middleware(request_timing.RequestTimingMiddleware)
        for path in ("/stack/items/1", "/stack/items/2"):
            messages = await call(production, path)
            assert messages[0]["status"] == 200, messages
        try:
            await call(production, "/stack/error")
        except RuntimeError:
            pass
        else:
            raise AssertionError("production-stack exception was swallowed")

        stats = {r["route"]: r for r in request_timing.route_stats()}
        assert stats["/a/{x}"]["n"] == 2
        assert stats["/a/{x}"]["p50"] >= 300
        assert stats["/b"]["errors"] == stats["/c"]["errors"] == 1
        assert stats["/sse"]["streams"] == 1 and stats["/sse"]["max"] < 250
        assert stats["<unmatched>"]["aborted"] == 1
        assert "/a/1" not in stats and "/unique/123" not in stats
        assert stats["/stack/items/{x}"]["n"] == 2
        assert stats["/stack/items/{x}"]["errors"] == 0
        assert stats["/stack/items/{x}"]["aborted"] == stats["/stack/items/{x}"]["streams"] == 0
        assert stats["/stack/error"]["n"] == stats["/stack/error"]["errors"] == 1
        assert stats["/stack/error"]["aborted"] == stats["/stack/error"]["streams"] == 0
        assert "/stack/items/1" not in stats and "/stack/items/2" not in stats
        for row in stats.values():
            assert set(row) == {"route", "method", "n", "p50", "p95", "max", "errors", "aborted", "streams"}
        rows = [json.loads(line) for line in request_timing.LOG_FILE.read_text().splitlines()]
        assert len(rows) == 3, rows
        failure = [row for row in rows if row["route"] == "/stack/error"]
        assert len(failure) == 1, rows
        assert failure[0]["status"] == 500 and failure[0]["outcome"] == "error", failure
        assert failure[0]["ms"] > 250 and failure[0]["bytes"] == 0, failure
        for row in rows:
            assert set(row) == {"ts", "route", "method", "status", "ms", "bytes", "outcome"}
            if row["route"] == "/stack/error":
                continue
            assert row["route"] == "/a/{x}" and row["method"] == "GET"
            assert row["bytes"] == 4 and row["status"] == 200 and row["outcome"] == "ok"
            assert row["ms"] > 250 and row["ts"]
    print("PASS: request timing")


if __name__ == "__main__":
    asyncio.run(main())
