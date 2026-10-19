"""Streaming ASGI gzip for explicitly compressible representations only.

Large chunks are compressed in a worker thread to keep the event loop responsive.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import zlib

from starlette.datastructures import Headers, MutableHeaders


# Below this, inline is cheaper than a thread hop; above it, a worker uses CPython zlib's GIL release to keep the loop running.
OFFLOAD_BYTES = 64 * 1024


# Bounded to spare the default executor shared by sync_stream and other asyncio.to_thread callers; two workers suffice because compression releases the GIL and more only compete for CPU.
_COMPRESS_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="gzip")


async def _offload(fn):
    return await asyncio.get_running_loop().run_in_executor(_COMPRESS_POOL, fn)


_ALLOWED = (
    "application/json", "text/html", "text/css", "text/plain",
    "application/javascript", "text/javascript", "image/svg+xml",
)


def _accepts_gzip(value: str) -> bool:
    qualities = {}
    for item in value.lower().split(","):
        coding, *params = item.strip().split(";")
        quality = 1.0
        for param in params:
            key, sep, val = param.strip().partition("=")
            if key.strip() == "q" and sep:
                try:
                    quality = float(val)
                except ValueError:
                    quality = 0.0
        qualities[coding.strip()] = quality if 0 <= quality <= 1 else 0.0
    return qualities.get("gzip", qualities.get("*", 0.0)) > 0


class SelectiveGZipMiddleware:
    """Buffer only eligible bodies until the threshold, then gzip chunkwise."""

    def __init__(self, app, minimum_size: int = 1024, level: int = 5):
        self.app = app
        self.minimum_size = minimum_size
        self.level = level

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        accepts = _accepts_gzip(Headers(scope=scope).get("accept-encoding", ""))
        start = None
        pending = []
        size = 0
        decided = False
        compressor = None
        disconnected = False

        async def receive_wrapper():
            nonlocal disconnected
            message = await receive()
            if message["type"] == "http.disconnect":
                disconnected = True
                pending.clear()
            return message

        async def send_wrapper(message):
            nonlocal start, size, decided, compressor
            if disconnected:
                return
            if message["type"] == "http.response.start":
                start = dict(message, headers=list(message.get("headers", [])))
                headers = MutableHeaders(scope=start)
                allowed = headers.get("content-type", "").lower().startswith(_ALLOWED)
                if allowed or message["status"] == 304:
                    vary = ", ".join(headers.getlist("vary"))
                    if "accept-encoding" not in {v.strip().lower() for v in vary.split(",")}:
                        headers["Vary"] = vary + ", Accept-Encoding" if vary else "Accept-Encoding"
                eligible = (allowed and accepts and scope["method"] != "HEAD"
                            and message["status"] not in (204, 304, 206)
                            and "content-range" not in headers and "content-encoding" not in headers)
                if not eligible:
                    decided = True
                    await send(start)
                return
            if message["type"] != "http.response.body":
                await send(message)
                return
            if not decided:
                pending.append(message)
                size += len(message.get("body", b""))
                if size < self.minimum_size and message.get("more_body", False):
                    return
                if size >= self.minimum_size:
                    compressor = zlib.compressobj(self.level, zlib.DEFLATED, 31)
                    headers = MutableHeaders(scope=start)
                    if "content-length" in headers:
                        del headers["content-length"]
                    headers["Content-Encoding"] = "gzip"
                    etag = headers.get("etag")
                    if etag and etag.startswith('"'):
                        headers["ETag"] = "W/" + etag
                decided = True
                await send(start)
                buffered = pending[:]
                pending.clear()
                for block in buffered:
                    await send_body(block)
                return
            await send_body(message)

        async def send_body(message):
            if compressor is None:
                await send(message)
                return
            body_in = message.get("body", b"")
            if len(body_in) >= OFFLOAD_BYTES:
                # One coroutine owns the compressor and awaits each call before the
                # next, so no two threads ever use it concurrently. A request cancelled
                # while its job runs leaves it to finish on its own captured compressor,
                # which nobody else can reach.
                def compress_body(compressor=compressor):
                    body = compressor.compress(body_in)
                    if not message.get("more_body", False):
                        body += compressor.flush()
                    return body

                body = await _offload(compress_body)
                if disconnected:
                    return
            else:
                body = compressor.compress(message.get("body", b""))
                if not message.get("more_body", False):
                    body += compressor.flush()
            await send(dict(message, body=body))

        try:
            await self.app(scope, receive_wrapper, send_wrapper)
        finally:
            # Never flush an incomplete response after disconnect or an exception.
            pending.clear()
            compressor = None
            start = None
