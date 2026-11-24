"""The server's event loop never opens the world DB — this module watches it.

A blocking call on the event-loop thread stalls every request, every stream
and the agent loop at once, and under CPU-bound worker threads a single
SELECT can take hundreds of milliseconds (each call that drops the GIL waits
for it again). The watchdog only speaks once the loop has been stuck for a
whole second; this guard counts EVERY blocking call that reaches a choke
point (``db.get_connection``) on the loop thread and reports them once a
minute, so a regression shows up as a line in the log, not as a hang.

Without a registered loop (scripts, smokes, queue_cli) ``check`` is one
integer comparison and never counts.
"""
import sys
import threading
import time
from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional

from app.core.log import get_logger

logger = get_logger("loop_guard")

#: Seconds between two report lines.
REPORT_EVERY_S = 60.0
#: Keys named in one report line; the rest is summed as ``other``.
REPORT_TOP = 15


class LoopBlockingCall(RuntimeError):
    """A blocking call reached a choke point on the server's event loop
    (strict mode only — smokes use it to prove a path stays off the loop)."""


_tid: Optional[int] = None
_strict = False
_allow_depth = 0
_lock = threading.Lock()
_counts: Dict[str, int] = {}
_last_report = 0.0


def register_server_loop() -> None:
    """Remember the calling thread as the one that runs the server's loop."""
    global _tid, _last_report
    _tid = threading.get_ident()
    _last_report = time.monotonic()


def unregister() -> None:
    global _tid
    _tid = None


def on_server_loop() -> bool:
    return _tid is not None and threading.get_ident() == _tid


def strict(on: bool) -> None:
    """Strict mode: ``check`` raises instead of counting. For smokes only."""
    global _strict
    _strict = bool(on)


@contextmanager
def allowed() -> Iterator[None]:
    """A wanted exception: startup and shutdown work inside the lifespan,
    where nothing is served yet. Only meaningful on the loop thread."""
    global _allow_depth
    mine = on_server_loop()
    if mine:
        _allow_depth += 1
    try:
        yield
    finally:
        if mine:
            _allow_depth -= 1


def _caller_key() -> str:
    """``<entry> > <leaf>``: the first and the last application frame of the
    loop thread's stack — who put the work on the loop, and what it reads."""
    names: List[str] = []
    frame = sys._getframe(2)
    while frame is not None:
        filename = frame.f_code.co_filename
        cut = filename.rfind("/app/")
        if cut >= 0 and not filename.endswith(("/loop_guard.py", "/core/db.py")):
            names.append(f"{filename[cut + 1:-3]}:{frame.f_code.co_name}")
        frame = frame.f_back
    if not names:
        return "(no app frame)"
    return names[-1] if len(names) == 1 else f"{names[-1]}>{names[0]}"


def check(what: str) -> None:
    """Called by a choke point before it blocks. Off the loop: nothing."""
    if _tid is None or threading.get_ident() != _tid or _allow_depth:
        return
    if _strict:
        raise LoopBlockingCall(f"{what} on the event loop: {_caller_key()}")
    try:
        key = _caller_key()
        with _lock:
            _counts[key] = _counts.get(key, 0) + 1
            due = time.monotonic() - _last_report >= REPORT_EVERY_S
        if due:
            for line in flush():
                logger.warning(line)
    except Exception:
        pass   # statistics never disturb the caller


def flush(now: Optional[float] = None) -> List[str]:
    """Return the report lines and clear the counters."""
    global _last_report
    with _lock:
        counts = dict(_counts)
        _counts.clear()
        _last_report = time.monotonic() if now is None else now
    if not counts:
        return []
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    parts = [f"{key}={n}" for key, n in ordered[:REPORT_TOP]]
    rest = sum(n for _, n in ordered[REPORT_TOP:])
    if rest:
        parts.append(f"other={rest}")
    return [f"loop_sync n={sum(counts.values())} " + " ".join(parts)]
