"""Last user activity — an in-memory monotonic stamp.  Touched by state-changing
player actions and manual admin generations; never by GET polls.  Improvement steps
run under `suppressed()` so their own generations do not end the idle window."""
import contextvars
import threading
import time
from contextlib import contextmanager

_lock = threading.Lock()
_last = time.monotonic()          # boot counts as activity: after a restart wait the full idle window
_suppress: contextvars.ContextVar[bool] = contextvars.ContextVar("user_activity_suppress", default=False)


def touch() -> None:
    if _suppress.get():
        return
    global _last
    with _lock:
        _last = time.monotonic()


def seconds_since() -> float:
    with _lock:
        return max(0.0, time.monotonic() - _last)


@contextmanager
def suppressed():
    tok = _suppress.set(True)
    try:
        yield
    finally:
        _suppress.reset(tok)


def is_suppressed() -> bool:
    return _suppress.get()


def _set_for_test(seconds_ago: float) -> None:
    global _last
    with _lock:
        _last = time.monotonic() - seconds_ago
