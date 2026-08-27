"""Last user activity — an in-memory monotonic stamp.

There is exactly ONE source of touches: an HTTP request that WRITES.  The rule
lives in ``activity_middleware_hook`` below and is applied by the single
middleware in ``app/server.py``; no route and no producer stamps by hand.  A
generation is therefore not activity in itself — the autonomous ones (agent
loop, queue handlers, animations) go through the same producer as a manual
render and would otherwise keep the idle window closed forever.

Improvement steps additionally run under ``suppressed()`` so anything they call
cannot end the idle window either.
"""
import contextvars
import threading
import time
from contextlib import contextmanager

_lock = threading.Lock()
_last = time.monotonic()          # boot counts as activity: after a restart wait the full idle window
_suppress: contextvars.ContextVar[bool] = contextvars.ContextVar("user_activity_suppress", default=False)

# Reads are polls, not activity: the player UI and the admin tabs poll on a
# timer, so a GET would keep every window open with nobody at the keyboard.
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# The improvements admin API is not player activity: watching the queue panel
# (or pausing an entry in it) must not push away the very window it waits for.
_IGNORED_PREFIX = "/improvements"


def touch() -> None:
    if _suppress.get():
        return
    global _last
    with _lock:
        _last = time.monotonic()


def activity_middleware_hook(method: str, path: str) -> bool:
    """Does this request count as the user being here?  Touches if so.

    Only humans issue HTTP writes — queue work, the agent loop and every
    background producer run without a request at all.  So one rule covers the
    whole app: any method that is not GET/HEAD/OPTIONS is a player action,
    except the improvements admin API itself.  Returns True when it touched.
    """
    if (method or "").upper() in _READ_METHODS:
        return False
    if (path or "").startswith(_IGNORED_PREFIX):
        return False
    touch()
    return True


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
