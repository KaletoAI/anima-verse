"""Concurrency caps for expensive SYNC route handlers.

``limited(name, limit)`` wraps a plain ``def`` route handler (FastAPI runs those in
its threadpool). At most ``limit`` calls of all handlers that share ``name``
execute their body at the same time; the others block on a semaphore. A
blocked thread is not runnable, so it costs the event loop no GIL hand-offs —
unlike a running poll, which makes every syscall of the loop slower.

This is a stop-gap: the proper fix (single-flight per roster/character plus
client polls that never stack) is the plan
``docs/superpowers/plans/2026-11-24-figure-poll-caches.md``. It changes no
payload and no behaviour other than waiting:

- A waiter that has waited ``MAX_WAIT_S`` stops waiting and runs anyway,
  without a slot. A cap must never turn into an outage. Counted as
  ``<name>:overdue``.
- Every call that did not get a slot at once is counted as ``<name>:waited``
  (an overdue call therefore counts in both).
- Re-entrant per thread: a call made while the same thread already holds a
  slot of ``name`` runs without taking a second one, so a decorated handler
  calling another one of the same pool can never wait on itself.
- The slot is released in a ``finally``, also when the body raises.
- Fairness is not guaranteed.

Counters go to ``hot_path_stats.count("route_limit", ...)``; statistics never
disturb the call.

The global AnyIO threadpool limiter is deliberately left alone: hundreds of
sync handlers share it, and only these few polls are the problem.
"""
import functools
import inspect
import threading
from typing import Any, Callable, Dict, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

# How long a call waits for a slot before it runs anyway (seconds). Read at
# call time, so a smoke can patch it.
MAX_WAIT_S = 30.0

# The two admin figure polls share this pool: GET /characters/open-steps and
# GET /characters/{c}/figure (GET /characters/{c}/model3d has its own, below).
# Evidence (logs/request_timing.jsonl since
# 2026-11-22, only requests > 250 ms): /model3d 5972 requests / 15,554 s total,
# up to 12 in flight; /open-steps 1550 / 11,689 s (max 764 s), up to 10 in
# flight; /figure 1134 / 7,293 s, up to 7 in flight. Their clients poll with
# an unguarded setInterval, so requests pile up and every running one is a
# runnable thread competing with the event loop for the GIL.
FIGURE_POLLS = "figure_polls"
FIGURE_POLLS_LIMIT = 3

# GET /characters/{c}/model3d has its own pool: the 3D clients fetch it per
# figure when a player enters a room, and it must not wait behind the two
# admin polls above, which run for minutes during a Build.
MODEL3D_POLL = "model3d_poll"
MODEL3D_POLL_LIMIT = 4

_pools_lock = threading.Lock()
_pools: Dict[str, threading.Semaphore] = {}
_limits: Dict[str, int] = {}
_held = threading.local()   # .depth: Dict[name, int] — slots of this thread


def _pool(name: str, limit: int) -> threading.Semaphore:
    with _pools_lock:
        known = _limits.get(name)
        if known is not None and known != limit:
            raise ValueError(f"route limit {name!r} already registered with limit {known}, not {limit}")
        sem = _pools.get(name)
        if sem is None:
            sem = _pools[name] = threading.Semaphore(limit)
            _limits[name] = limit
        return sem


def _count(name: str, what: str) -> None:
    try:
        from app.core import hot_path_stats
        hot_path_stats.count("route_limit", f"{name}:{what}")
    except Exception:  # noqa: BLE001 — statistics never disturb the call
        pass


def _depths() -> Dict[str, int]:
    depth = getattr(_held, "depth", None)
    if depth is None:
        depth = _held.depth = {}
    return depth


def limited(name: str, limit: int) -> Callable[[F], F]:
    """Decorator: at most ``limit`` calls of all functions sharing ``name`` run
    their body at once (see the module docstring). For SYNC functions only;
    ``functools.wraps`` keeps the signature FastAPI reads its parameters and
    dependencies from."""
    if limit < 1:
        raise ValueError("limit must be >= 1")
    sem = _pool(name, limit)

    def decorate(fn: F) -> F:
        if inspect.iscoroutinefunction(fn):
            raise TypeError(f"limited() is for sync handlers, {fn.__qualname__} is async")

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            depth = _depths()
            if depth.get(name, 0) > 0:
                # Re-entrant: this thread already holds a slot of the pool.
                depth[name] += 1
                try:
                    return fn(*args, **kwargs)
                finally:
                    depth[name] -= 1
            got = sem.acquire(blocking=False)
            if not got:
                _count(name, "waited")
                got = sem.acquire(timeout=MAX_WAIT_S)
                if not got:
                    _count(name, "overdue")
            depth[name] = 1
            try:
                return fn(*args, **kwargs)
            finally:
                depth[name] = 0
                if got:
                    sem.release()

        return wrapper  # type: ignore[return-value]

    return decorate
