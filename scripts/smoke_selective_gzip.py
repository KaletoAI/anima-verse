#!/usr/bin/env python3
"""Selective gzip, with exactly one BaseHTTPMiddleware turning bodies into streams.

Hand-derived from P3 section 4.2: 2048 bytes exceed the 1024-byte threshold,
200 do not. Only eligible JSON is gzip, its strong validator becomes weak,
and decompression must recover every original byte. Allowed types and all
304s vary on Accept-Encoding, preserving Origin. HEAD, q=0, range, SSE, ZIP
and GLB remain byte-identical. An SSE producer waits for client receipt of
its first event before finishing: buffering even that small event deadlocks.
Raw ASGI send captures wire bytes (HTTP clients often auto-decompress).
offload_equivalence: 1024, 65535, 65536 and ~3 MB JSON-ish bytes must
round-trip and equal level-5 gzip compress+flush of the identical chunks,
both whole and split. Nonempty splits below/equal 64 KiB stay inline;
a 65 KiB case split at 1 KiB and the ~3 MB split exercise offloaded tails.
offload_thread: 65535 bytes must make zero offload calls; 65536 must make
exactly one, executing on a thread whose name starts with "gzip". Both
outputs must decompress to the original bytes; the seam is restored finally.
offload_disconnect: start is sent before the first 70 KiB body enters the
gate. A concurrent app task calls receive, which sets receive_done just before
returning http.disconnect. The receive wrapper sets disconnected before that
task yields; the gate also yields once after the event, ensuring it resumes
after disconnect observation. Expect exactly one start and no body messages.
offload_keeps_loop: ~4 MB of varied JSON string data makes inline compression
occupy the loop for its full duration (planner measured >150 ms; print the
local measurement without asserting a machine-dependent lower bound).
A pre-started 2 ms ticker prints worst overshoot during middleware compression
as a diagnostic only; decompression must recover the original bytes. The
thread and disconnect checks above assert deterministic offload behavior.
Usage: .venv/bin/python scripts/smoke_selective_gzip.py
"""
import asyncio
import gzip
import random
import time
import sys
import tempfile
import threading
import zlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles
from app.core.http_files import etag_matches
from app.core import selective_gzip
from app.core.selective_gzip import SelectiveGZipMiddleware

LARGE = b'"' + b"a" * 2046 + b'"'
SMALL = b'"' + b"a" * 198 + b'"'

async def gzip_chunks(chunks):
    messages = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        for index, chunk in enumerate(chunks):
            await send({"type": "http.response.body", "body": chunk,
                        "more_body": index < len(chunks) - 1})

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    await SelectiveGZipMiddleware(app)(
        {"type": "http", "method": "GET", "headers": [(b"accept-encoding", b"gzip")]},
        receive, send)
    assert dict(messages[0]["headers"])[b"content-encoding"] == b"gzip"
    return b"".join(m.get("body", b"") for m in messages[1:])


def jsonish(size):
    # Seeded hex data is valid JSON, varied enough to avoid trivial compression.
    content = random.Random(73).randbytes((size + 1) // 2).hex().encode()
    return b'"' + content[:size - 2] + b'"'


async def offload_equivalence():
    for size in (1024, 64 * 1024 - 1, 64 * 1024, 65 * 1024, 3 * 1024 * 1024):
        original = jsonish(size)
        split = 1024 if size > 64 * 1024 else 1
        for chunks in ([original], [original[:split], original[split:]],
                       [original, b""]):
            reference = zlib.compressobj(5, zlib.DEFLATED, 31)
            expected = b"".join(reference.compress(chunk) for chunk in chunks)
            expected += reference.flush()
            wire = await gzip_chunks(chunks)
            assert gzip.decompress(wire) == original, (size, len(chunks))
            assert wire == expected, (size, len(chunks))
    print("PASS offload_equivalence")


async def offload_thread():
    original_offload = selective_gzip._offload
    calls = []
    threads = []

    async def spy(fn):
        calls.append(fn)

        def wrapped():
            threads.append(threading.current_thread().name)
            return fn()

        return await original_offload(wrapped)

    selective_gzip._offload = spy
    try:
        for size, expected in ((64 * 1024 - 1, 0), (64 * 1024, 1)):
            calls.clear()
            threads.clear()
            original = jsonish(size)
            wire = await gzip_chunks([original])
            assert gzip.decompress(wire) == original
            assert len(calls) == expected, (size, len(calls))
            assert len(threads) == expected, (size, threads)
            assert all(name.startswith("gzip") for name in threads), threads
    finally:
        selective_gzip._offload = original_offload
    print("PASS offload_thread")


async def offload_disconnect():
    original_offload = selective_gzip._offload
    receive_done = asyncio.Event()
    messages = []

    async def gated(fn):
        await receive_done.wait()
        await asyncio.sleep(0)
        return fn()

    async def receive():
        receive_done.set()
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    async def app(scope, receive, send):
        task = asyncio.create_task(receive())
        try:
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": jsonish(70 * 1024),
                        "more_body": False})
        finally:
            await task

    selective_gzip._offload = gated
    try:
        await SelectiveGZipMiddleware(app)(
            {"type": "http", "method": "GET",
             "headers": [(b"accept-encoding", b"gzip")]}, receive, send)
        assert [m["type"] for m in messages] == ["http.response.start"], messages
    finally:
        selective_gzip._offload = original_offload
    print("PASS offload_disconnect")


async def offload_keeps_loop():
    original = jsonish(4 * 1024 * 1024)
    reference = zlib.compressobj(5, zlib.DEFLATED, 31)
    started = time.perf_counter()
    reference.compress(original)
    reference.flush()
    print(f"inline compress+flush: {(time.perf_counter() - started) * 1000:.1f} ms",
          flush=True)
    loop = asyncio.get_running_loop()
    ready = asyncio.Event()
    done = False
    overshoots = []

    async def ticker():
        while not done:
            started = loop.time()
            ready.set()
            await asyncio.sleep(0.002)
            overshoots.append(max(0, loop.time() - started - 0.002))

    task = asyncio.create_task(ticker())
    try:
        await ready.wait()
        wire = await gzip_chunks([original])
        # Let the pending sleep record any stall even if compression never yielded.
        await asyncio.sleep(0.004)
    finally:
        done = True
        await task
    worst = max(overshoots)
    print(f"offloaded ticker worst overshoot: {worst * 1000:.1f} ms", flush=True)
    assert gzip.decompress(wire) == original
    print("PASS offload_keeps_loop")


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
    await offload_thread()
    await offload_disconnect()
    await offload_equivalence()
    await offload_keeps_loop()
    await lifecycle_checks()
    await request("sse_first")
    assert first_received.is_set() and ended
    print("PASS first SSE block arrives before stream ends")

if __name__ == "__main__":
    asyncio.run(main())
