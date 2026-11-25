"""Serial flight: at most one computation per slot at a time, plus at most one follower.

``SerialFlight.run(slot, key_fn, compute, share=copy.deepcopy)`` (plan
docs/superpowers/plans/2026-11-24-figure-poll-caches.md, Task 2; review W1, B1):

- ``key_fn()`` is called under the internal lock BEFORE anything is read (the generation rule of CLAUDE.md:
  capture the whole key first).
- No run in the slot: the caller captures the key, starts the run and computes OUTSIDE the lock.
- A run of the slot is going with the SAME key: the caller waits for that run's future.
- A run is going with a DIFFERENT key (the figure generation moved, say): the caller joins the slot's ONE
  follower (created when there is none). The follower starts only when the running run has ended, captures the
  key THEN (under the lock, by the run that ended) and computes once for all of its callers. A caller that comes
  with the follower's key while the follower computes waits for it. So a slot has at most one run computing and
  one follower waiting, and nobody gets a state older than the one of their request.
- EVERY caller — the one that computed included — gets ``share(result)``; the original stays private in the
  future (nobody mutates it). An exception of the computation reaches every caller of that run.
- The entry is removed (or handed to the follower) in a ``finally``.
- Waiting happens on a ``concurrent.futures.Future`` outside every lock; no lock of the caller is touched.

It caches nothing: once a run has ended, the next caller computes again (the callers' own memos decide).
"""
import copy
import threading
from concurrent.futures import Future
from typing import Any, Callable, Dict, Hashable, Optional, TypeVar

T = TypeVar("T")

_UNSET = object()


class _Run:
    """One computation of a slot: its key (captured before it computes), the compute and the future."""

    __slots__ = ("key", "key_fn", "compute", "future", "started")

    def __init__(self, key_fn: Callable[[], Hashable], compute: Callable[[], Any]) -> None:
        self.key: Any = _UNSET
        self.key_fn = key_fn
        self.compute = compute
        self.future: Future = Future()
        self.started = threading.Event()   # a follower: set once it is promoted (its key is captured)


class _Slot:
    __slots__ = ("running", "follower", "computing")

    def __init__(self) -> None:
        self.running: Optional[_Run] = None
        self.follower: Optional[_Run] = None
        self.computing = 0


class SerialFlight:
    """See the module docstring."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slots: Dict[Hashable, _Slot] = {}
        self._max_concurrent = 0

    def in_flight(self) -> int:
        """How many slots have a run going or a follower waiting."""
        with self._lock:
            return len(self._slots)

    def max_concurrent(self) -> int:
        """The highest number of runs of one slot seen computing at the same time (for smokes; 1 by design)."""
        with self._lock:
            return self._max_concurrent

    def run(self, slot: Hashable, key_fn: Callable[[], Hashable], compute: Callable[[], T], *,
            share: Callable[[T], T] = copy.deepcopy) -> T:
        mine: Optional[_Run] = None
        follow: Optional[_Run] = None
        wait_on: Optional[_Run] = None
        with self._lock:
            entry = self._slots.get(slot)
            if entry is None or entry.running is None:
                entry = self._slots[slot] = entry or _Slot()
                mine = _Run(key_fn, compute)
                mine.key = key_fn()
                mine.started.set()
                entry.running = mine
            else:
                key = key_fn()
                if entry.running.key == key:
                    wait_on = entry.running
                elif entry.follower is not None:
                    wait_on = entry.follower
                else:
                    follow = entry.follower = _Run(key_fn, compute)
        if wait_on is not None:
            return share(wait_on.future.result())
        if follow is not None:
            # The follower's creator computes it once the running run has promoted it (and captured its key).
            follow.started.wait()
            if follow.future.done():   # its key could not be captured
                return share(follow.future.result())
            mine = follow
        assert mine is not None
        return share(self._compute(slot, mine))

    def _compute(self, slot: Hashable, run: _Run) -> Any:
        with self._lock:
            entry = self._slots[slot]
            entry.computing += 1
            self._max_concurrent = max(self._max_concurrent, entry.computing)
        result: Any = None
        error: Optional[BaseException] = None
        try:
            result = run.compute()
        except BaseException as e:  # noqa: BLE001 — handed to every caller of the run
            error = e
        finally:
            promoted: Optional[_Run] = None
            with self._lock:
                entry = self._slots[slot]
                entry.computing -= 1
                entry.running = None
                follower, entry.follower = entry.follower, None
                if follower is not None:
                    try:
                        follower.key = follower.key_fn()   # captured now, before the follower reads anything
                        entry.running = follower
                        promoted = follower
                    except BaseException as e:  # noqa: BLE001 — every caller of the follower gets it
                        follower.future.set_exception(e)
                        follower.started.set()
                if entry.running is None:
                    del self._slots[slot]
            if error is not None:
                run.future.set_exception(error)
            else:
                run.future.set_result(result)
            if promoted is not None:
                promoted.started.set()
        if error is not None:
            raise error
        return result
