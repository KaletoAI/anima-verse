#!/usr/bin/env python3
"""Selective gzip, with exactly one BaseHTTPMiddleware turning bodies into streams.

Hand-derived from P3 section 4.2: 2048 bytes exceed the 1024-byte threshold,
200 do not. Only eligible JSON is gzip, its strong validator becomes weak,
and decompression must recover every original byte. Allowed types and all
304s vary on Accept-Encoding, preserving Origin. HEAD, q=0, range, SSE, ZIP
and GLB remain byte-identical. An SSE producer waits for client receipt of
its first event before finishing: buffering even that small event deadlocks.
Raw ASGI send captures wire bytes (HTTP clients often auto-decompress).
Usage: .venv/bin/python scripts/smoke_selective_gzip.py
"""
import asyncio
import gzip
import sys
import tempfile
import zlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles
from app.core.http_files import etag_matches
from app.core.selective_gzip import SelectiveGZipMiddleware

LARGE = b'"' + b"a" * 2046 + b'"'
SMALL = b'"' + b"a" * 198 + b'"'

async def lifecycle_checks():
    """Incomplete streams must not flush; per-request state cannot escape."""
    scope = {"type": "http", "method": "GET", "headers": [(b"accept-encoding", b"gzip")]}
    for failure, prefix in (("disconnect", b"small"), ("exception", b"small"),
                            ("disconnect", LARGE), ("exception", LARGE)):
        messages = []
        async def receive():
            return {"type": "http.disconnect"}
        async def send(message):
            messages.append(message)
        async def incomplete(scope, receive, send):
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": prefix, "more_body": True})
            if failure == "exception":
                raise RuntimeError("producer failed")
            await receive()
            await send({"type": "http.response.body", "body": LARGE, "more_body": False})
        try:
            await SelectiveGZipMiddleware(incomplete)(scope, receive, send)
        except RuntimeError as exc:
            assert failure == "exception" and str(exc) == "producer failed"
        else:
            assert failure == "disconnect"
        if len(prefix) < 1024:
            assert messages == [], (failure, messages)
        else:
            assert messages[0]["type"] == "http.response.start"
            assert all(m.get("more_body", True) for m in messages)
            partial = b"".join(m.get("body", b"") for m in messages)
            decoder = zlib.decompressobj(31)
            decoder.decompress(partial)
            assert not decoder.eof, "incomplete response was flushed as complete"
    for headers, status, compressed in [
        ([(b"content-type", b"application/json")], 200, True),
        ([(b"content-type", b"application/json"), (b"content-encoding", b"br")], 200, False),
        ([(b"content-type", b"application/json"), (b"content-range", b"bytes 0-2047/4096")], 200, False),
        ([(b"content-type", b"application/json")], 204, False),
        ([(b"content-type", b"image/svg+xml")], 200, True),
        ([(b"content-type", b"image/png")], 200, False),
        ([(b"content-type", b"application/octet-stream")], 200, False),
    ]:
        messages = []
        async def send(message):
            messages.append(message)
        async def chunks(scope, receive, send):
            await send({"type": "http.response.start", "status": status, "headers": headers})
            for offset in range(0, len(LARGE), 400):
                await send({"type": "http.response.body", "body": LARGE[offset:offset + 400],
                            "more_body": offset + 400 < len(LARGE)})
        await SelectiveGZipMiddleware(chunks)(scope, receive, send)
        body = b"".join(m.get("body", b"") for m in messages)
        assert (gzip.decompress(body) if compressed else body) == LARGE
    async def other(scope, receive, send):
        assert scope["type"] == "lifespan"
        await send({"type": "lifespan.startup.complete"})
    messages = []
    await SelectiveGZipMiddleware(other)({"type": "lifespan"}, receive, send)
    assert messages == [{"type": "lifespan.startup.complete"}]
    print("PASS chunked compression, exclusions, lifecycle and non-HTTP")


async def main():
    first_received = asyncio.Event()
    ended = False

    async def endpoint(request):
        nonlocal ended
        case = request.path_params["case"]
        if case == "json_2k":
            if etag_matches(request.headers.get("if-none-match"), '"e1"'):
                return Response(status_code=304, headers={"ETag": '"e1"', "Cache-Control": "no-cache"})
            return Response(LARGE, media_type="application/json", headers={"ETag": '"e1"'})
        if case == "stream_304":
            return Response(status_code=304, headers={"ETag": '"e1"', "Cache-Control": "no-cache", "Vary": "Origin"})
        if case == "json_200b":
            async def small():
                yield SMALL[:100]
                yield SMALL[100:]
            return StreamingResponse(small(), media_type="application/json")
        if case == "sse_first":
            async def events():
                nonlocal ended
                yield b"data: first\n\n"
                await asyncio.wait_for(first_received.wait(), 2)
                ended = True
                yield b"data: last\n\n"
            return StreamingResponse(events(), media_type="text/event-stream")
        media = {"range": "audio/mpeg", "sse": "text/event-stream", "zip": "application/zip", "glb": "model/gltf-binary"}[case]
        return Response(LARGE, status_code=206 if case == "range" else 200,
                        media_type=media, headers={"Content-Range": "bytes 0-2047/4096"} if case == "range" else {})

    async def dispatch(request, call_next):
        return await call_next(request)

    app = Starlette(routes=[Route("/{case}", endpoint, methods=["GET", "HEAD"])])
    app.add_middleware(BaseHTTPMiddleware, dispatch=dispatch)
    wrapped = SelectiveGZipMiddleware(app)

    async def request(case, method="GET", encoding="gzip", inm=None):
        messages = []
        headers = [(b"accept-encoding", encoding.encode())]
        if inm:
            headers.append((b"if-none-match", inm.encode()))
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
                 "path": "/" + case, "raw_path": ("/" + case).encode(), "query_string": b"", "headers": headers}
        sent_request = False
        async def receive():
            nonlocal sent_request
            if not sent_request:
                sent_request = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await asyncio.Event().wait()
        async def send(message):
            messages.append(message)
            if case == "sse_first" and message["type"] == "http.response.body" and b"data: first\n\n" in message.get("body", b""):
                assert not ended, "first SSE event was buffered until stream completion"
                first_received.set()
        await asyncio.wait_for(wrapped(scope, receive, send), 5)
        start = messages[0]
        return start["status"], dict(start["headers"]), b"".join(m.get("body", b"") for m in messages[1:])

    status, headers, body = await request("json_2k")
    assert status == 200 and headers[b"content-encoding"] == b"gzip"
    assert headers[b"etag"] == b'W/"e1"' and gzip.decompress(body) == LARGE
    assert b"content-length" not in headers or int(headers[b"content-length"]) == len(body)
    assert b"accept-encoding" in headers[b"vary"].lower()
    print("PASS json_2k")
    for inm in ('W/"e1"', '"e1"'):
        status, headers, body = await request("json_2k", inm=inm)
        assert status == 304 and not body and b"accept-encoding" in headers[b"vary"].lower()
    print("PASS json_2k_inm")
    with tempfile.TemporaryDirectory() as directory:
        app.mount("/static", StaticFiles(directory=directory))
        for filename, content in (
            ("smoke.js", b"const value = 'gzip';\n" * 128),
            ("smoke.css", b"body { color: black; }\n" * 128),
        ):
            Path(directory, filename).write_bytes(content)
            status, headers, body = await request("static/" + filename)
            assert status == 200 and headers[b"content-encoding"] == b"gzip", filename
            assert gzip.decompress(body) == content, filename
            etag = headers[b"etag"].decode()
            assert etag.startswith("W/"), (filename, etag)
            status, headers, body = await request("static/" + filename, inm=etag)
            assert status == 304, (
                f"StaticFiles did not match the unchanged weak ETag for {filename}: "
                f"{etag!r} returned {status}. Minimal fix: subclass StaticFiles and "
                "use etag_matches for If-None-Match in is_not_modified, retaining "
                "the existing If-Modified-Since fallback."
            )
            assert not body, filename
            assert b"accept-encoding" in {
                value.strip().lower() for value in headers[b"vary"].split(b",")
            }, filename
            print("PASS StaticFiles gzip and unchanged weak ETag", filename)
    status, headers, body = await request("stream_304")
    assert status == 304 and not body
    assert {v.strip().lower() for v in headers[b"vary"].split(b",")} == {b"origin", b"accept-encoding"}
    print("PASS stream_304")
    for label, case, kwargs, expected in [
        ("json_200b", "json_200b", {}, SMALL), ("head", "json_2k", {"method": "HEAD"}, LARGE),
        ("q0", "json_2k", {"encoding": "gzip;q=0"}, LARGE),
        ("wildcard_q0", "json_2k", {"encoding": "gzip;q=0, *;q=1"}, LARGE),
        *[(c, c, {}, LARGE) for c in ("range", "sse", "zip", "glb")],
    ]:
        status, headers, body = await request(case, **kwargs)
        assert b"content-encoding" not in headers and body == expected, label
        if case.startswith("json"):
            assert b"accept-encoding" in headers[b"vary"].lower()
        if case == "range":
            assert status == 206 and headers[b"content-range"] == b"bytes 0-2047/4096"
        print("PASS", label)
    for encoding in ("*", "br, GZip;q=0.5"):
        _, headers, body = await request("json_2k", encoding=encoding)
        assert headers[b"content-encoding"] == b"gzip" and gzip.decompress(body) == LARGE
    await lifecycle_checks()
    await request("sse_first")
    assert first_received.is_set() and ended
    print("PASS first SSE block arrives before stream ends")

if __name__ == "__main__":
    asyncio.run(main())
