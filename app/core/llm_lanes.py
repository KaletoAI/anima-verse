"""Cache lanes — one serialized execution slot per LLM entry, assigned by
prompt prefix (development_instructions/plan-cache-lanes.md).

A backend keeps only a limited number of prompt caches. What we can steer is
not which slot it uses, but HOW MANY different prompt beginnings we produce at
the same time and in which order. That is what a lane is:

- **Lane** — one serialized execution slot of an LLM entry. It runs one call
  at a time and remembers its last **cache key** (its "hot" key).
- **Cache key** — what determines the beginning of the prompt:
  ``<task class>:<character>``, e.g. ``chat:Kira``, ``thought:Vallerie``.
  Without a character (a consolidation over the whole world) the key is
  ``<class>:`` — all of those share one lane.
- **Pool** — all lanes of one LLM entry, keyed ``provider/model``.

Phase 1 implements rule **R1** (assignment order: a free lane with the same
key → a never-used free lane → the least recently used free lane → wait) and
rule **R6** (a call may release its lane early and take one again from the
same call path without blocking itself). The waiting order is plain FIFO here;
R2 (priority queue with ageing), R3 (affinity wait) and R4 (conversation hold)
are phase 2 and slot into ``_assignable_lane`` / ``_is_next_in_line``.

The manager is thread-safe (the provider queue runs on threads). The clock is
injectable so checks can step time instead of sleeping.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from app.core.llm_queue import Priority
from app.core.log import get_logger

logger = get_logger("llm_lanes")

# Never block a caller on the condition variable for longer than this in one
# go: the deadline is computed from the INJECTED clock, so a stepped clock has
# to be re-read regularly for the timeout to land at all.
_WAIT_SLICE_SECONDS = 0.25


class LaneTimeout(TimeoutError):
    """No lane of the pool became free within the timeout.

    A typed error on purpose: the queue worker asks with ``timeout=0`` and
    catches exactly this one to put its task back unchanged, instead of
    parking a worker thread on a pool that is not even its own.
    """


# ── task classes ───────────────────────────────────────────────────────────

# The class a call without a declared one belongs to: background work, whose
# prompt beginning nobody shares and nobody protects.
DEFAULT_CACHE_CLASS = "bg"

# Streaming registrations and a few direct submits do not use catalog task ids
# — they name the SURFACE a turn came from ("user_chat", "group_chat"). The
# catalog cannot declare a class for an id it does not contain, so these few
# are mapped here, BY PROMPT: everything that writes a character's reply into
# a conversation is ``chat``; the storyteller surface writes the world's prose
# and shares no prompt beginning with anyone, so it is background.
_SURFACE_CLASSES: Dict[str, str] = {
    "user_chat": "chat",
    "character_talk": "chat",
    "talk_to": "chat",
    "send_message": "chat",
    "telegram_chat": "chat",
    "group_chat": "chat",
    "story": DEFAULT_CACHE_CLASS,
}


def _sub_task_parent(task: str) -> Optional[str]:
    """The parent of a ``<parent>_<sub>`` task id, or None.

    The rule itself lives in ``llm_router.fallback_parent()`` and is read from
    there, never re-derived. Only the ``<parent>_<sub>`` SHAPE is used:
    ``thought_reflect`` really is a thought and produces a thought prompt, so
    it belongs to its parent's class. The other entries of fallback_parent
    (``furnish`` → ``intent``, ``npc_*`` → ``chat_stream``) are ROUTING
    decisions — which model answers — and routing must never decide a prompt
    family: it would send an NPC action tick onto the lane that holds that
    character's live conversation and evict exactly the cache we protect.
    """
    from app.core.llm_router import fallback_parent

    parent = fallback_parent(task)
    if parent and task.startswith(parent + "_"):
        return parent
    return None


def task_class_for(task_type: str) -> str:
    """The prompt-prefix class of a task: ``chat`` / ``thought`` / ``tool`` /
    ``bg``.

    The class is a property of the TASK and is declared once, in the catalog
    (``cache_class`` in app/core/llm_tasks.py). A task id the catalog does not
    contain is resolved through the ``<parent>_<sub>`` rule above
    (``intent_move`` → ``intent`` → ``tool``); anything still unknown is
    background work, which is the safe answer — it shares its lane with other
    background calls and displaces no conversation.
    """
    from app.core.llm_tasks import TASK_TYPES

    surface = _SURFACE_CLASSES.get(task_type)
    if surface:
        return surface
    task = task_type
    seen = {task}
    while task not in TASK_TYPES:
        parent = _sub_task_parent(task)
        if not parent or parent in seen:
            break
        task = parent
        seen.add(task)
    entry = TASK_TYPES.get(task) or {}
    return str(entry.get("cache_class") or DEFAULT_CACHE_CLASS)


def cache_key_for(task_type: str, agent_name: str = "") -> str:
    """The cache key of a call: ``<task class>:<character>``.

    One place for the whole codebase (the AgentLoop reads it too). A call
    without a character keeps the trailing colon — ``bg:`` is a real key that
    all character-less background work shares.
    """
    return f"{task_class_for(task_type)}:{agent_name or ''}"


def pool_key_for(provider_name: str, model: str) -> str:
    """The pool of an LLM entry. The cache lives per model alias, not per
    provider — one AI-Hub provider serves several aliases on different
    hosts."""
    return f"{(provider_name or '?').strip()}/{(model or '?').strip()}"


def configured_lane_count(pool_key: str) -> int:
    """Lanes of this pool as the config has them right now.

    Reads ``max_concurrent`` of the matching ``llm_routing`` entries (LLM
    Routing › LLMs). Several enabled entries may name the same
    provider+model (one per sampling profile) — they all run against the SAME
    backend slot, so the pool is one, and the HIGHEST value of them wins:
    taking the first would silently cap the model at whichever entry happens
    to come first in the list. Unknown entry, disabled entry or no config at
    all = one lane, which is the old behaviour.
    """
    provider, _, model = pool_key.partition("/")
    found = 0
    try:
        from app.core import config

        for entry in (config.get("llm_routing", []) or []):
            if not isinstance(entry, dict) or entry.get("enabled") is False:
                continue
            if (entry.get("provider") or "").strip() != provider:
                continue
            if (entry.get("model") or "").strip() != model:
                continue
            found = max(found, int(entry.get("max_concurrent") or 1))
    except Exception as e:  # pragma: no cover - config must never break a call
        logger.debug("lane count for %s not readable: %s", pool_key, e)
    return max(1, found)


def configured_lane_total(provider_name: str) -> int:
    """Sum of the lanes of every enabled LLM entry of one provider.

    The provider queue sizes its worker pool with it: a worker thread can
    hold at most one lane, so fewer threads than lanes would cap the
    parallelism below what the entries allow. Entries that share a
    provider+model share ONE pool, so they count once, with the highest value
    (see ``configured_lane_count``).
    """
    per_pool: Dict[str, int] = {}
    try:
        from app.core import config

        for entry in (config.get("llm_routing", []) or []):
            if not isinstance(entry, dict) or entry.get("enabled") is False:
                continue
            if (entry.get("provider") or "").strip() != (provider_name or "").strip():
                continue
            key = (entry.get("model") or "").strip()
            per_pool[key] = max(per_pool.get(key, 0),
                                int(entry.get("max_concurrent") or 1),
                                1)
    except Exception as e:  # pragma: no cover
        logger.debug("lane total for %s not readable: %s", provider_name, e)
    return sum(per_pool.values())


# ── lanes, pools, handles ──────────────────────────────────────────────────


@dataclass
class Lane:
    """One execution slot. ``hot_key`` is the key of the LAST call that ran on
    it — empty means never used, which R1 prefers over displacing a key."""
    lane_id: int
    hot_key: str = ""
    last_used: float = 0.0
    busy: bool = False
    label: str = ""


@dataclass
class _Waiter:
    """One call queued on a pool. ``arrived`` is when the CALL first asked for
    a lane, not when this attempt started — a queued task asks again on every
    pass of the worker, and R2/R3 (phase 2) have to age it from its first
    attempt or it would never grow old. The caller therefore carries the stamp
    (``LLMTask._lane_arrived``) and hands it back in."""
    cache_key: str
    priority: int
    arrived: float
    ticket: int


@dataclass
class _Pool:
    key: str
    lanes: List[Lane] = field(default_factory=list)
    waiting: List[_Waiter] = field(default_factory=list)
    target: int = 1
    _next_lane_id: int = 0

    def new_lane(self) -> Lane:
        lane = Lane(lane_id=self._next_lane_id)
        self._next_lane_id += 1
        self.lanes.append(lane)
        return lane


class LaneHandle:
    """What a caller holds while it occupies a lane. ``release()`` is
    idempotent, which is what makes R6 work: a chat turn releases its lane
    before executing a tool that calls the same pool and takes one again
    afterwards."""

    def __init__(self, manager: "LaneManager", pool_key: str, lane: Lane,
                 cache_key: str):
        self._manager = manager
        self.pool_key = pool_key
        self.lane_id = lane.lane_id
        self.cache_key = cache_key
        self._released = False

    @property
    def released(self) -> bool:
        return self._released

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._manager._release(self.pool_key, self.lane_id)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"LaneHandle({self.pool_key} lane={self.lane_id} "
                f"key={self.cache_key!r}{' released' if self._released else ''})")


class LaneManager:
    """All pools of the process. One instance per server (see
    ``get_lane_manager``); checks build their own with a stepped clock."""

    def __init__(self, now: Optional[Callable[[], float]] = None,
                 lane_count: Optional[Callable[[str], int]] = None):
        self._now = now or time.monotonic
        self._lane_count = lane_count or configured_lane_count
        self._cond = threading.Condition()
        self._pools: Dict[str, _Pool] = {}
        self._ticket = 0

    # -- public API --------------------------------------------------------

    def now(self) -> float:
        """The manager's clock. A caller that stamps its own arrival time has
        to read the SAME clock the waiters are ordered by — in a check that is
        a stepped one, not time.monotonic()."""
        return self._now()

    def acquire_lane(self, pool_key: str, cache_key: str,
                     priority: int = Priority.NORMAL, *,
                     timeout: Optional[float] = None,
                     arrived: Optional[float] = None,
                     label: str = "") -> LaneHandle:
        """Occupies a lane of ``pool_key`` for ``cache_key``.

        ``timeout=None`` waits forever, ``timeout=0`` tries exactly once and
        never blocks; on expiry a ``LaneTimeout`` is raised. ``arrived`` is
        when the CALL first asked (see ``_Waiter``).

        Making a long wait VISIBLE is the caller's job, not this one's: the
        one path that really waits (ProviderQueue._acquire_chat_lane) asks in
        slices, so that between two slices it can run the cleanup that frees a
        lane held by a dead registration. A warning timer in here would only
        say the same thing without ever getting out of the wait.
        """
        deadline = None if timeout is None else self._now() + max(0.0, timeout)
        with self._cond:
            pool = self._ensure_pool(pool_key)
            self._ticket += 1
            started = self._now()
            waiter = _Waiter(
                cache_key=cache_key, priority=int(priority),
                arrived=float(arrived if arrived is not None else started),
                ticket=self._ticket)
            pool.waiting.append(waiter)
            try:
                while True:
                    lane = self._take_lane(pool, waiter, label)
                    if lane is not None:
                        return LaneHandle(self, pool_key, lane, cache_key)
                    if deadline is not None:
                        remaining = deadline - self._now()
                        if remaining <= 0:
                            raise LaneTimeout(
                                f"no free lane on {pool_key} for {cache_key!r} "
                                f"within {timeout}s")
                        self._cond.wait(min(remaining, _WAIT_SLICE_SECONDS))
                    else:
                        self._cond.wait(_WAIT_SLICE_SECONDS)
            finally:
                if waiter in pool.waiting:
                    pool.waiting.remove(waiter)

    @contextmanager
    def acquire(self, pool_key: str, cache_key: str,
                priority: int = Priority.NORMAL, *,
                timeout: Optional[float] = None, label: str = ""):
        """``acquire_lane`` as a context manager — the lane is released on the
        way out, also when the body raises."""
        handle = self.acquire_lane(pool_key, cache_key, priority,
                                   timeout=timeout, label=label)
        try:
            yield handle
        finally:
            handle.release()

    def free_lanes(self, pool_key: str, cache_key: str = "") -> int:
        """How many lanes of the pool ``cache_key`` could take right now.

        Phase 1: every free lane counts, because nothing keeps a key off a
        lane yet. R3/R4 (phase 2) narrow this for keys below the chat class;
        R5 (phase 3) and the respond dispatcher read it.
        """
        with self._cond:
            pool = self._pools.get(pool_key)
            if pool is None:
                return max(1, int(self._lane_count(pool_key)))
            return sum(1 for lane in pool.lanes if not lane.busy)

    def snapshot(self) -> Dict[str, Any]:
        """State of every pool for the admin view (phase 4) and for checks."""
        with self._cond:
            now = self._now()
            pools = {}
            for key, pool in self._pools.items():
                pools[key] = {
                    "lane_count": len(pool.lanes),
                    "target": pool.target,
                    "busy": sum(1 for x in pool.lanes if x.busy),
                    "free": sum(1 for x in pool.lanes if not x.busy),
                    "waiting": len(pool.waiting),
                    "lanes": [
                        {
                            "lane_id": lane.lane_id,
                            "busy": lane.busy,
                            "hot_key": lane.hot_key,
                            "label": lane.label,
                            "age_s": (round(now - lane.last_used, 2)
                                      if lane.last_used else None),
                        }
                        for lane in pool.lanes
                    ],
                }
            return {"pools": pools}

    def reconfigure(self, pool_key: str, lanes: int) -> None:
        """New lane count for a pool.

        Growing takes effect at once. Shrinking frees the unused lanes
        immediately and the busy ones as they are released — taking a lane
        away from a running call would be the one thing lanes exist to
        prevent.
        """
        with self._cond:
            pool = self._ensure_pool(pool_key, lanes)
            self._set_target(pool, lanes)
            self._cond.notify_all()

    def sync_from_config(self, pool_key: str) -> None:
        """Applies the configured lane count of this pool.

        The manager itself never re-reads the config — an explicit
        ``reconfigure`` would be overwritten again on the next call. The
        caller that wants live behaviour (the provider queue, before every
        acquire) calls this; a check that sets its lane counts by hand does
        not.
        """
        self.reconfigure(pool_key, int(self._lane_count(pool_key)))

    def reset(self) -> None:
        """Drops all pools — for checks only."""
        with self._cond:
            self._pools.clear()
            self._cond.notify_all()

    # -- internals ---------------------------------------------------------

    def _ensure_pool(self, pool_key: str, lanes: Optional[int] = None) -> _Pool:
        """Pool of ``pool_key``, sized on first use. Later changes come
        through ``reconfigure`` / ``sync_from_config``, never from here."""
        pool = self._pools.get(pool_key)
        if pool is None:
            pool = _Pool(key=pool_key)
            self._pools[pool_key] = pool
            self._set_target(
                pool, int(lanes if lanes is not None
                          else self._lane_count(pool_key)))
        return pool

    def _set_target(self, pool: _Pool, lanes: int) -> None:
        pool.target = max(1, int(lanes))
        while len(pool.lanes) < pool.target:
            pool.new_lane()
        self._retire_surplus(pool)

    def _retire_surplus(self, pool: _Pool) -> None:
        """Removes free lanes above the target, least recently used first."""
        while len(pool.lanes) > pool.target:
            free = [x for x in pool.lanes if not x.busy]
            if not free:
                return
            victim = min(free, key=lambda x: x.last_used)
            pool.lanes.remove(victim)

    def _is_next_in_line(self, pool: _Pool, waiter: _Waiter) -> bool:
        """Phase 1: plain FIFO — only the longest waiting call may take a
        lane. R2 replaces this with priority class, key affinity and ageing."""
        return bool(pool.waiting) and pool.waiting[0] is waiter

    def _assignable_lane(self, pool: _Pool, waiter: _Waiter) -> Optional[Lane]:
        """R1, in this order: a free lane whose key is already hot → a lane
        that was never used → the least recently used free lane."""
        free = [lane for lane in pool.lanes if not lane.busy]
        if not free:
            return None
        same = [lane for lane in free if lane.hot_key == waiter.cache_key]
        if same:
            # The hottest of them: whatever ran last is most likely still
            # cached in the backend.
            return max(same, key=lambda x: x.last_used)
        fresh = [lane for lane in free if not lane.hot_key]
        if fresh:
            return min(fresh, key=lambda x: x.lane_id)
        return min(free, key=lambda x: x.last_used)

    def _take_lane(self, pool: _Pool, waiter: _Waiter,
                   label: str) -> Optional[Lane]:
        if not self._is_next_in_line(pool, waiter):
            return None
        lane = self._assignable_lane(pool, waiter)
        if lane is None:
            return None
        lane.busy = True
        lane.hot_key = waiter.cache_key
        lane.last_used = self._now()
        lane.label = label
        pool.waiting.remove(waiter)
        # The head of the queue is gone, so the call behind it may be next in
        # line now — and a second lane that became free while this one held
        # the head would otherwise only be noticed after the poll slice.
        if pool.waiting:
            self._cond.notify_all()
        return lane

    def _release(self, pool_key: str, lane_id: int) -> None:
        with self._cond:
            pool = self._pools.get(pool_key)
            if pool is None:
                return
            for lane in pool.lanes:
                if lane.lane_id == lane_id:
                    lane.busy = False
                    lane.last_used = self._now()
                    lane.label = ""
                    break
            self._retire_surplus(pool)
            self._cond.notify_all()


_manager: Optional[LaneManager] = None
_manager_lock = threading.Lock()


def get_lane_manager() -> LaneManager:
    """The process-wide lane manager."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = LaneManager()
    return _manager
