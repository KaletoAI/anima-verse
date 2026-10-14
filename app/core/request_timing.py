"""Pure ASGI request timing with bounded route samples and slow-request logs."""
import asyncio
from collections import deque
import json
import math
from statistics import median
import threading
from time import perf_counter

from anyio import BrokenResourceError, ClosedResourceError
from starlette.requests import ClientDisconnect

from app.core.timeutils import utc_now_iso
from app.utils import llm_logger

LOG_FILE = llm_logger.LOG_DIR / "request_timing.jsonl"
_stats_lock = threading.Lock()
_log_lock = threading.Lock()
_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
_samples: dict[tuple[str, str], deque] = {}


def _record(route, method, status, ms, size, outcome):
    method = method if method in _METHODS else "OTHER"
    with _stats_lock:
        _samples.setdefault((route, method), deque(maxlen=500)).append((ms, outcome))
    if ms <= 250 or outcome == "stream":
        return
    try:
        row = {"ts": utc_now_iso(), "route": route, "method": method,
               "status": status, "ms": ms, "bytes": size, "outcome": outcome}
        line = json.dumps(row, ensure_ascii=False)
        with _log_lock:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        # Diagnostics must never affect request handling.
        pass


def route_stats() -> list[dict]:
    """Snapshot the last 500 samples; p95 uses the nearest-rank percentile."""
    with _stats_lock:
        snapshot = [(key, list(values)) for key, values in _samples.items()]
    rows = []
    for (route, method), samples in snapshot:
        times = sorted(ms for ms, _ in samples)
        rows.append({"route": route, "method": method, "n": len(times),
                     "p50": median(times), "p95": times[math.ceil(.95 * len(times)) - 1],
                     "max": times[-1],
                     "errors": sum(outcome == "error" for _, outcome in samples),
                     "aborted": sum(outcome == "aborted" for _, outcome in samples),
                     "streams": sum(outcome == "stream" for _, outcome in samples)})
    return sorted(rows, key=lambda row: row["p95"], reverse=True)


class RequestTimingMiddleware:
    """Measure HTTP responses without buffering their bodies or altering exceptions."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "")
        method = method if method in _METHODS else "OTHER"
        started = perf_counter()
        route = "<unmatched>"
        status = 0
        size = 0
        stream = False
        first_body_ms = None
        last_body_ms = None
        disconnected = False
        outcome = None

        async def timed_receive():
            nonlocal disconnected
            message = await receive()
            if message["type"] == "http.disconnect":
                disconnected = True
            return message

        async def timed_send(message):
            nonlocal route, status, size, stream, first_body_ms, last_body_ms, disconnected
            if message["type"] == "http.response.start":
                route = getattr(scope.get("route"), "path", None) or "<unmatched>"
                status = message["status"]
                stream = any(k.lower() == b"content-type" and
                             v.split(b";", 1)[0].strip().lower() == b"text/event-stream"
                             for k, v in message.get("headers", []))
            try:
                await send(message)
            except (OSError, ClosedResourceError, BrokenResourceError, ClientDisconnect):
                disconnected = True
                raise
            if message["type"] == "http.response.body":
                size += len(message.get("body", b""))
                elapsed = (perf_counter() - started) * 1000
                if first_body_ms is None:
                    first_body_ms = elapsed
                if not message.get("more_body", False):
                    last_body_ms = elapsed

        try:
            await self.app(scope, timed_receive, timed_send)
        except asyncio.CancelledError:
            outcome = "aborted"
            raise
        except Exception:
            outcome = "aborted" if disconnected else "error"
            if status == 0 and outcome == "error":
                status = 500
            raise
        finally:
            route = getattr(scope.get("route"), "path", None) or route
            if outcome is None:
                # A disconnect after a complete response is normal in ASGI.
                if disconnected and last_body_ms is None:
                    outcome = "aborted"
                elif status >= 500:
                    outcome = "error"
                else:
                    outcome = "stream" if stream else "ok"
            elapsed = (perf_counter() - started) * 1000
            if stream and first_body_ms is not None:
                elapsed = first_body_ms
            elif outcome in ("ok", "error") and last_body_ms is not None:
                elapsed = last_body_ms
            # SSE lifetimes never belong in the slow-request log, even on failure.
            if stream:
                with _stats_lock:
                    _samples.setdefault((route, method), deque(maxlen=500)).append((elapsed, outcome))
            else:
                _record(route, method, status, elapsed, size, outcome)
