"""One lock per key, handed out under a guard — the idiom the codebase grew
five times over (per-avatar position reports, per-tile heightfield bakes,
per-tile terrain-layer bakes, per-character mesh/reference generation).

WHY IT EXISTS. Routes that used to run ON the event loop were serialized by
it for free: two requests of the same kind could never sit inside the same
handler at once, so a read-modify-write ("read the profile, change one field,
save it") could not interleave. Since those routes moved into the threadpool
(2026-08-24) that guarantee is gone — two threads DO run the same body at the
same time, and the later read/earlier write pair silently drops one change.
The replacement is an explicit lock, and it has to be KEYED: one global lock
would serialize two players who have nothing to say to each other.

Usage::

    from app.core.keyed_lock import keyed_lock

    with keyed_lock("character_profile", name):
        profile = get_character_profile(name)
        profile["x"] = 1
        save_character_profile(name, profile)

The namespace keeps unrelated key spaces apart: ``("character_profile", "a")``
and ``("avatar_state", "a")`` are two different locks. Conversely, everything
that must serialize against each other has to agree on ONE namespace/key pair
— the position report and the room change of one avatar share
``("avatar_state", <avatar>)`` precisely so they cannot interleave.

RE-ENTRANT (2026-09-21). The handed-out lock wraps a ``threading.RLock``: the
SAME thread may enter the same key again, another thread still waits at the
door. That is what a nested read-modify-write needs — ``set_is_sleeping``
locks the profile, the equip route below it locks the same profile, and with
a plain ``Lock`` the request thread would deadlock on itself. Re-entrancy
does NOT make two DIFFERENT keys safe: the deadlock that matters is still the
one between threads, so the lock ORDER stands (places-lock before
``character_profile``; two characters' profile locks only ever in sorted-name
order; never a profile lock held across an LLM/HTTP/image call or a sleep).

The one non-blocking user is ``routes/play.py`` (``_pos_lock(avatar)
.acquire(blocking=False)``, a contended position report is dropped): it
contends between two REQUEST threads and reads identically on an RLock,
because a report never re-enters its own handler. Nothing asks a keyed lock
whether it is ``locked()`` — an RLock has no such method.

The locks are process-local and never freed: a lock is a few dozen bytes and
the key spaces here are bounded (avatars, characters, tiles, file paths).
"""
import threading
from collections import deque
from typing import Callable, Dict, Tuple


_LOCAL = threading.local()


def _drain_after_locks() -> None:
    """Deliver queued domain events only after this thread releases all locks."""
    if getattr(_LOCAL, "depth", 0) or getattr(_LOCAL, "draining", False):
        return
    _LOCAL.draining = True
    try:
        pending = getattr(_LOCAL, "pending", None)
        while pending and not getattr(_LOCAL, "depth", 0):
            pending.popleft()()
    finally:
        _LOCAL.draining = False


def _after_locks(callback: Callable[[], None]) -> None:
    """Queue a callback in write order, or deliver immediately without locks."""
    if not hasattr(_LOCAL, "pending"):
        _LOCAL.pending = deque()
    _LOCAL.pending.append(callback)
    _drain_after_locks()


class _DeferredRLock:
    """RLock with thread-local domain-event delivery after the outermost exit.

    World and keyed locks share the depth so nested movement callers cannot
    inadvertently run a room-entry listener under another profile/world lock.
    """

    def __init__(self):
        self._lock = threading.RLock()

    def acquire(self, blocking=True, timeout=-1):
        acquired = self._lock.acquire(blocking, timeout)
        if acquired:
            _LOCAL.depth = getattr(_LOCAL, "depth", 0) + 1
        return acquired

    def release(self):
        self._lock.release()
        _LOCAL.depth -= 1
        _drain_after_locks()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()

    def _is_owned(self):
        return self._lock._is_owned()


#: namespace -> key -> lock. Guarded by :data:`_GUARD` for creation only; the
#: locks themselves are held by their callers, never under the guard.
_LOCKS: Dict[str, Dict[str, _DeferredRLock]] = {}
_GUARD = threading.Lock()


def keyed_lock(namespace: str, key: str) -> _DeferredRLock:
    """The RE-ENTRANT lock of one ``(namespace, key)`` pair, created on first ask.

    The same pair always returns the SAME lock object; a different key or a
    different namespace returns a different one. Thread-safe: the creation
    runs under a global guard, which is held only for the dict lookup and
    never while a returned lock is held.

    The returned object wraps a ``threading.RLock`` — the owning thread may
    acquire it again (and must release it as often as it took it), any other
    thread blocks as before. See the module docstring for why.

    Room-entry events queued by movement setters are delivered after the
    outermost world/keyed lock is released, including caller-held locks.
    """
    ns = str(namespace)
    k = str(key)
    with _GUARD:
        bucket = _LOCKS.get(ns)
        if bucket is None:
            bucket = {}
            _LOCKS[ns] = bucket
        lock = bucket.get(k)
        if lock is None:
            lock = _DeferredRLock()
            bucket[k] = lock
        return lock


def _counts() -> Tuple[int, int]:
    """(namespaces, locks) currently held — diagnostics for the smoke check."""
    with _GUARD:
        return len(_LOCKS), sum(len(b) for b in _LOCKS.values())
