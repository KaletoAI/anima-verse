"""GET /events/sync — the fog-filtered topic stream (P4 B), as a pure ASGI layer.

Sits inside the gzip layer and OUTSIDE every BaseHTTPMiddleware: those forward
a response through memory streams into tasks of their own, so cancelling the
stream would not reach a send blocked further out, and below ASGI spec 2.4
StreamingResponse reads `receive` itself. Here this layer owns receive and send
alone: one disconnect reader, and the lag watchdog's abort cancels the task
that is really blocked in send.

Same-origin only, like every API call of both apps; no CORS headers.
"""
import asyncio
import json

from app.core import sessions, sync_topics
from app.core.log import get_logger

logger = get_logger("sync_stream")
PATH = "/events/sync"
_batch_sleep = asyncio.sleep


def _frame(topics, resync: bool) -> bytes:
    return f"data: {json.dumps({'topics': topics, 'resync': resync})}\n\n".encode()


def _cookie(scope, name: str) -> str:
    from http.cookies import SimpleCookie
    for k, v in scope.get("headers") or []:
        if k == b"cookie":
            c = SimpleCookie()
            c.load(v.decode("latin-1"))
            if name in c:
                return c[name].value
    return ""


def _header(scope, name: bytes) -> str:
    for k, v in scope.get("headers") or []:
        if k == name:
            return v.decode("latin-1")
    return ""


def _recheck(conn) -> str:
    """'bye' when the session is gone; otherwise reconcile the binding with
    compare-and-set and fresh re-reads (R2-1, R3-1). Runs in the threadpool."""
    if not sessions.peek_session(conn.token):
        return "bye"
    sync_topics.reconcile(conn)
    return "ok"


class _RouteLabel:
    """What RequestTimingMiddleware reads at response start (`scope["route"].path`);
    this endpoint is no router route, so it names itself (R3-3)."""
    path = PATH


class SyncStreamMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope.get("type") != "http" or scope.get("path") != PATH
                or scope.get("method") != "GET"):
            await self.app(scope, receive, send)
            return
        scope["route"] = _RouteLabel()   # same dict the timing layer holds (Step 0 checks gzip passes it through)
        await _serve(scope, receive, send)


async def _unauthorized(send) -> None:
    body = b'{"detail":"Not authenticated"}'
    await send({"type": "http.response.start", "status": 401,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


async def _serve(scope, receive, send) -> None:
    from app.core import users

    token = _cookie(scope, sessions.SESSION_COOKIE_NAME)
    sess, refreshed = (await asyncio.to_thread(sessions.get_session, token)
                       if token else (None, False))
    user = await asyncio.to_thread(users.get_user_by_id, sess["user_id"]) if sess else None
    if not user:
        await _unauthorized(send)
        return
    headers = [(b"content-type", b"text/event-stream; charset=utf-8"),
               (b"cache-control", b"no-cache"), (b"x-accel-buffering", b"no")]
    if refreshed:
        from starlette.responses import Response
        helper = Response()
        sessions.set_session_cookie(helper, token, secure=sessions.is_secure_request(
            scope.get("scheme", "http"), _header(scope, b"x-forwarded-proto")))
        headers += [(k, v) for k, v in helper.raw_headers if k == b"set-cookie"]

    user_id = user["id"]          # key name per Step 0
    loop = asyncio.get_running_loop()
    wake = asyncio.Event()
    holder: dict = {}

    def _abort() -> None:
        task = holder.get("stream")
        if task is not None:
            loop.call_soon_threadsafe(task.cancel)

    conn = sync_topics.register(user_id, token, "", "",
                                wake=lambda: loop.call_soon_threadsafe(wake.set),
                                abort=_abort)

    try:
        async def tracked(message) -> None:
            """EVERY send of this layer is timed by the lag watchdog (R3-2)."""
            conn.send_started()
            await send(message)
            conn.delivered()

        async def body(chunk: bytes) -> None:
            await tracked({"type": "http.response.body", "body": chunk, "more_body": True})

        async def stream() -> None:
            await asyncio.to_thread(sync_topics.reconcile, conn)
            if conn.closed:
                return
            clock = sync_topics._clock
            await tracked({"type": "http.response.start", "status": 200, "headers": headers})
            topics, resync = conn.take()
            await body(b"retry: 5000\n" + _frame(topics, resync))
            next_beat = clock() + sync_topics.HEARTBEAT_S
            next_check = clock() + sync_topics.CHECK_S
            while not conn.closed:
                timeout = max(0.0, min(next_beat, next_check) - clock())
                try:
                    await asyncio.wait_for(wake.wait(), timeout)
                except asyncio.TimeoutError:
                    pass
                wake.clear()
                if conn.closed:
                    return
                if clock() >= next_check:
                    next_check = clock() + sync_topics.CHECK_S
                    if await asyncio.to_thread(_recheck, conn) == "bye":
                        await tracked({"type": "http.response.body",
                                       "body": b"event: bye\ndata: {}\n\n", "more_body": False})
                        return
                if conn.has_pending():
                    await _batch_sleep(sync_topics.BATCH_S)
                    topics, resync = conn.take()
                    if topics:
                        await body(_frame(topics, resync))
                        next_beat = clock() + sync_topics.HEARTBEAT_S
                        continue
                if clock() >= next_beat:
                    await body(b": ping\n\n")
                    next_beat = clock() + sync_topics.HEARTBEAT_S

        async def watch_disconnect() -> None:
            while (await receive())["type"] != "http.disconnect":
                pass

        task = asyncio.create_task(stream())
        holder["stream"] = task
        watcher = asyncio.create_task(watch_disconnect())
        try:
            await asyncio.wait({task, watcher}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in (task, watcher):
                t.cancel()
            await asyncio.gather(task, watcher, return_exceptions=True)
    finally:
        sync_topics.unregister(conn)
