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

The rules (plan § 4), all of them live here:

- **R1 assignment**: the caller's OWN lane, when it passed one and it is free
  → a free lane whose key is already hot → a never-used lane → the least
  recently used free lane → queue up. The first step exists for R6: a turn
  that hands its lane back for its own nested tool call passes the lane id
  along (``own_lane``) and gets that lane, whatever its priority class. Left
  to the LRU step, two conversations on two lanes would take turns evicting
  each other — the LRU lane is precisely the other conversation's.
- **R2 selection** when a lane frees up (``_next_in_line``): a call that would
  take its OWN lane gets the pass first, whatever anyone else's class is —
  R1's first step decides nothing if R2 never lets that call through. Then
  only the highest waiting priority class is eligible; within it a waiter
  whose key matches the lane it would get wins, otherwise the oldest arrival.
  A waiter that has waited longer than ``lanes.wait_upgrade_seconds`` counts
  one class higher, which is what keeps background work from starving.
- **R3 affinity wait** (``_assignable_lane``): a call below the chat class
  takes a FOREIGN lane (used, different key) only once
  ``lanes.affinity_wait_seconds`` have passed since it arrived. Its own key
  and a never-used lane it takes at once.
- **R4 conversation hold** (``_on_hold``): a free lane whose hot key is of the
  ``chat`` class and whose last use is younger than
  ``lanes.conversation_hold_seconds`` counts as occupied for a different key —
  never as a blockade, though: when no call is running that could free a lane,
  it is taken after all. The hold protects a conversation against BACKGROUND
  work, not against the chat class: a waiter of ``Priority.CHAT`` is exempt
  from it, exactly as R3 already exempts it. A conversation must never wait
  behind a thought while a lane sits idle — and it costs next to nothing,
  because among the free lanes R1 takes the least recently USED one, so a lane
  a conversation just left is the last one anybody reaches for. The caller's
  own lane needs no exemption here: R1's first step hands it out before R3 and
  R4 are ever consulted, so R4 cannot protect a conversation against its own
  tool call.
- **R6**: a call may release its lane early and take one again from the same
  call path without blocking itself.

The priority a call carries IN THE LANES is not the priority the queue panel
shows: it follows the prompt class (``lane_priority_for``), so an AgentLoop
thought is background work here even though it registers as a chat.

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


def lane_priority_for(task_type: str) -> int:
    """The priority a call carries IN THE LANES, derived from its prompt class.

    The streaming path registers every turn with ``Priority.CHAT``. For the
    QUEUE that is right — the registration pauses the provider queue and the
    admin panel shows a running turn — but for the lanes it is not: an
    AgentLoop thought registers exactly the same way, so it would ignore R3's
    affinity wait and rank level with a user's conversation in R2. Those are
    the two things the rules exist to keep apart. The lane priority therefore
    follows the PROMPT class, never the surface:

      ``chat``    -> CHAT    a live conversation, it may displace
      ``thought`` -> LOW     background work, it waits its turn
      everything else -> NORMAL

    Only the lane priority changes; ``LLMTask.priority`` (panel, queue pause)
    stays what it was.
    """
    cls = task_class_for(task_type)
    if cls == "chat":
        return int(Priority.CHAT)
    if cls == "thought":
        return int(Priority.LOW)
    return int(Priority.NORMAL)


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


@dataclass(frozen=True)
class LaneRules:
    """The three global lane timings (plan § 5, config section ``lanes``).

    Seconds on the MANAGER's clock — SYSTEM time, like every other queue
    timing. They are read live (see ``configured_lane_rules``), so an admin
    save takes effect on the next selection pass without a restart.
    """
    affinity_wait: float = 3.0       # R3
    conversation_hold: float = 120.0  # R4
    wait_upgrade: float = 60.0       # R2


def configured_lane_rules() -> LaneRules:
    """The lane timings as the config has them right now.

    Read on every selection pass, never cached at import: the values are
    small integers and the read is a dict lookup, while a cached copy would
    quietly outlive the admin save that changed it.
    """
    defaults = LaneRules()
    try:
        from app.core import config

        section = config.get_section("lanes")
        return LaneRules(
            affinity_wait=float(section.get("affinity_wait_seconds",
                                            defaults.affinity_wait)),
            conversation_hold=float(section.get("conversation_hold_seconds",
                                                defaults.conversation_hold)),
            wait_upgrade=float(section.get("wait_upgrade_seconds",
                                           defaults.wait_upgrade)),
        )
    except Exception as e:  # pragma: no cover - config must never break a call
        logger.debug("lane rules not readable: %s", e)
        return defaults


# The priority ladder a lane knows, highest first. Priority.IMAGE_GEN (25) is
# NOT a rung: a GPU job takes a SLOT of its channel, never a lane. A value
# between two rungs ages up to the next rung above it (25 -> 20).
_CLASS_LADDER = (int(Priority.CHAT), int(Priority.HIGH),
                 int(Priority.NORMAL), int(Priority.LOW))


def one_class_higher(priority: int) -> int:
    """The next rung up the ladder — R2's ageing step. CHAT stays CHAT."""
    higher = [rung for rung in _CLASS_LADDER if rung < int(priority)]
    return max(higher) if higher else int(priority)


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
    (``LLMTask._lane_arrived``) and hands it back in.

    ``own_lane`` is the lane this caller handed back a moment ago so that a
    nested call could run (R6). It is the FIRST step of R1 and wins before
    everything else, for every priority class: it is the lane this call's own
    prompt is cached on, so neither R4 nor the LRU order may send the call
    somewhere else (``_assignable_lane``) — and no other waiter's class may
    take that lane away from it either (``_next_in_line``)."""
    cache_key: str
    priority: int
    arrived: float
    ticket: int
    own_lane: Optional[int] = None


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
                 lane_count: Optional[Callable[[str], int]] = None,
                 rules: Optional[Callable[[], LaneRules]] = None):
        self._now = now or time.monotonic
        self._lane_count = lane_count or configured_lane_count
        # A CALLABLE, not a value: the timings are read on every selection
        # pass so an admin save lands without a restart. A check hands in its
        # own callable and changes what it returns between the steps.
        self._rules = rules or configured_lane_rules
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
                     own_lane: Optional[int] = None,
                     label: str = "") -> LaneHandle:
        """Occupies a lane of ``pool_key`` for ``cache_key``.

        ``timeout=None`` waits forever, ``timeout=0`` tries exactly once and
        never blocks; on expiry a ``LaneTimeout`` is raised. ``arrived`` is
        when the CALL first asked (see ``_Waiter``), ``own_lane`` the lane
        this caller just gave back for a nested call (R6).

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
                ticket=self._ticket,
                own_lane=(None if own_lane is None else int(own_lane)))
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
                    # This call gave up (timeout) or was the loser of a pass.
                    # Whoever is still waiting may be next in line now — R2
                    # decides among the waiters PRESENT, so one leaving can
                    # change the answer.
                    if pool.waiting:
                        self._cond.notify_all()

    @contextmanager
    def acquire(self, pool_key: str, cache_key: str,
                priority: int = Priority.NORMAL, *,
                timeout: Optional[float] = None,
                arrived: Optional[float] = None,
                own_lane: Optional[int] = None, label: str = ""):
        """``acquire_lane`` as a context manager — the lane is released on the
        way out, also when the body raises."""
        handle = self.acquire_lane(pool_key, cache_key, priority,
                                   timeout=timeout, arrived=arrived,
                                   own_lane=own_lane, label=label)
        try:
            yield handle
        finally:
            handle.release()

    def free_lanes(self, pool_key: str, cache_key: str = "",
                   priority: int = Priority.NORMAL) -> int:
        """How many lanes of the pool ``cache_key`` could take right now.

        R4 is applied (a protected conversation lane is not free for a
        different key, unless taking it is the only way out), R3 is NOT: the
        affinity wait is a WAIT of a few seconds, not a ban — a lane it holds
        a call off is still a lane that call will take. Without a cache key
        the plain number of free lanes comes back. R5 (phase 3) and the
        respond dispatcher read this.

        ``priority`` is the CALLER's lane class and it has to be handed in,
        because R4 does not apply to everybody: the chat class is exempt from
        the conversation hold (§ 4 R4), exactly as ``_assignable_lane``
        exempts it. Without the argument this answered every question as if
        the caller were background work and UNDER-reported for a chat key —
        the respond dispatcher of phase 3 asks for ``chat:<character>`` and
        would have left a free lane unused whenever a NEIGHBOURING
        conversation had been on it within the hold. The default keeps the
        old answer for callers that really are background.

        The answer is what could REALLY be taken, which in the blockade branch
        is exactly ONE, however many held lanes there are: the first caller to
        take one is then a running call, and from that moment the other held
        lanes are worth waiting for again. Counting them all would tell the
        phase-3 dispatcher to start three turns where one lane exists.
        """
        with self._cond:
            pool = self._pools.get(pool_key)
            if pool is None:
                return max(1, int(self._lane_count(pool_key)))
            free = [lane for lane in pool.lanes if not lane.busy]
            if not cache_key:
                return len(free)
            if int(priority) <= int(Priority.CHAT):
                return len(free)
            now = self._now()
            open_now = [lane for lane in free
                        if not self._on_hold(lane, cache_key, now)]
            if not open_now and free and not any(lane.busy for lane in pool.lanes):
                return 1   # no blockade, see _assignable_lane — but only one
            return len(open_now)

    def lane_capacity(self, pool_key: str) -> int:
        """How many lanes this pool has ALTOGETHER, busy ones included.

        The respond dispatcher (phase 3) needs it next to ``free_lanes``: a
        turn it has just started does not hold its lane yet — it is still
        building its prompt — so the free count alone would let it start one
        turn per tick until the first of them finally acquires. Capacity minus
        the turns already under way on this pool is the honest budget.

        A pool that has never been used answers from the config, without
        creating it: asking must never invent a pool the admin view then shows
        (the same rule ``free_lanes`` follows).
        """
        with self._cond:
            pool = self._pools.get(pool_key)
            if pool is None:
                return max(1, int(self._lane_count(pool_key)))
            return len(pool.lanes)

    def hot_free_lane(self, pool_key: str, cache_key: str) -> bool:
        """R5: is this key's prompt sitting on a lane that is free right now?

        The AgentLoop asks it about candidates that are due anyway, to decide
        the ORDER among them (plan § 4 R5) — never who is due. A pool that
        does not exist yet holds no prompt of anybody, so the answer is False:
        R5 then changes nothing and the loop keeps its own order.
        """
        if not cache_key:
            return False
        with self._cond:
            pool = self._pools.get(pool_key)
            if pool is None:
                return False
            return any(not lane.busy and lane.hot_key == cache_key
                       for lane in pool.lanes)

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

    def _effective_priority(self, waiter: _Waiter, now: float) -> int:
        """R2 ageing: the class a waiter counts as right now.

        Recomputed at SELECTION time from the injected clock — there is no
        background timer that promotes anyone, because a promotion only ever
        matters in the instant a lane is handed out. ``wait_upgrade <= 0``
        switches the ageing off rather than promoting everybody at once.
        """
        upgrade = self._rules().wait_upgrade
        if upgrade > 0 and (now - waiter.arrived) >= upgrade:
            return one_class_higher(waiter.priority)
        return int(waiter.priority)

    def _on_hold(self, lane: Lane, cache_key: str, now: float) -> bool:
        """R4: is this free lane a protected conversation for ``cache_key``?

        Only a lane whose hot key is of the ``chat`` class and whose last use
        is younger than ``conversation_hold`` protects anything, and only
        against a DIFFERENT key. Whether that protection may turn into a
        blockade is decided by the caller (``_assignable_lane``): it never may.
        """
        if not lane.hot_key or lane.hot_key == cache_key:
            return False
        if not lane.hot_key.startswith("chat:"):
            return False
        hold = self._rules().conversation_hold
        if hold <= 0:
            return False
        return (now - lane.last_used) < hold

    def _next_in_line(self, pool: _Pool, now: float) -> Optional[_Waiter]:
        """R2: which of the waiting calls may take a lane right now.

        Only waiters that COULD take a lane at this moment count — one held
        back by R3 or R4 blocks nobody.

        FIRST, before any class is compared: a contender whose assignable
        lane is its OWN lane (the oldest of them, should there be several).
        R1's first step is worth nothing if R2 never lets that call have its
        pass — and that is exactly what happened: a turn suspends its lane for
        its own nested call (R6), a waiter of a higher class is parked on the
        pool, and the higher class takes the lane the turn released a
        millisecond ago for itself. Suspending is a MOMENTARY release inside a
        RUNNING turn, not a re-entry into the queue. Letting another waiter
        take that lane preempts a turn that is already under way — something
        this system does nowhere else — and it destroys precisely the cache
        the lane exists for: the turn's own prompt, which is sitting on that
        lane. The waiter loses nothing it was entitled to. On a one-lane pool
        it gets the lane when that turn ENDS, one turn later, which is the
        normal wait; without this step it instead gets the lane in the middle
        of the turn, and the turn — tool call first, then its resume — waits
        behind the whole foreign turn, on a busy one-lane pool until the
        660 s stale sweep frees its registration.

        Among the rest only the highest (aged) priority class is eligible;
        within that class a waiter whose key is hot on the lane it would get
        wins, otherwise the oldest arrival (ticket as the tie-break, which is
        the arrival order).

        Exactly ONE winner per pass, even when several lanes are free: the
        winner notifies the rest on its way out, so the next pass picks the
        next one. Picking per lane instead would let two waiters each be
        beaten on the lane they want by someone who wants the other one — two
        free lanes and nobody moving.

        A QUEUED task is not a persistent waiter. The queue worker asks with
        ``timeout=0``, so a queued call is in ``pool.waiting`` only for the
        instant of its own attempt and leaves again when it loses; it then
        goes back into the queue and asks again on the next pass. It is
        therefore compared against everyone who is REALLY waiting at that
        moment (streaming registrations), which is what keeps a LOW thought
        from out-ranking a CHAT registration — but a CHAT call that arrives
        LATER cannot beat it retroactively: a queued call that has already
        won a lane runs, it is not preempted.
        """
        contenders = [(w, self._assignable_lane(pool, w, now))
                      for w in pool.waiting]
        contenders = [(w, lane) for w, lane in contenders if lane is not None]
        if not contenders:
            return None
        own = [(w, lane) for w, lane in contenders
               if w.own_lane is not None and lane.lane_id == w.own_lane]
        if own:
            return min(own, key=lambda item: (item[0].arrived,
                                              item[0].ticket))[0]
        best = min(self._effective_priority(w, now) for w, _ in contenders)
        peers = [(w, lane) for w, lane in contenders
                 if self._effective_priority(w, now) == best]
        matching = [(w, lane) for w, lane in peers if lane.hot_key == w.cache_key]
        field = matching or peers
        return min(field, key=lambda item: (item[0].arrived, item[0].ticket))[0]

    def _assignable_lane(self, pool: _Pool, waiter: _Waiter,
                         now: float) -> Optional[Lane]:
        """Which lane this waiter would take right now — R1, narrowed by R3
        and R4.

        R1 order: the caller's OWN lane, if it passed one and it is free → a
        free lane whose key is already hot → a lane that was never used → the
        least recently used free lane. R3 and R4 only ever remove FOREIGN,
        used lanes from that last step; the waiter's own key and a never-used
        lane are always taken at once.

        The own-lane step holds for EVERY priority class, and that is the
        point of it. ``own_lane`` is the lane this very call released a moment
        ago so that its nested tool call could run (R6) — the lane its own
        prompt is cached on. Without this step the LRU step decides, and with
        two lanes and two live conversations the LRU lane is the OTHER
        conversation's: every tool call of one chat would evict the other's
        cache and vice versa, which is the opposite of what lanes are for
        (review of phase 2, 2026-09-18: measured 6 evictions in 6 turns and no
        cache hit, against 4 hits and no eviction with this step).
        """
        free = [lane for lane in pool.lanes if not lane.busy]
        if not free:
            return None
        if waiter.own_lane is not None:
            mine = [lane for lane in free if lane.lane_id == waiter.own_lane]
            if mine:
                return mine[0]
        same = [lane for lane in free if lane.hot_key == waiter.cache_key]
        if same:
            # The hottest of them: whatever ran last is most likely still
            # cached in the backend.
            return max(same, key=lambda x: x.last_used)
        fresh = [lane for lane in free if not lane.hot_key]
        if fresh:
            return min(fresh, key=lambda x: x.lane_id)
        # Only foreign, used lanes left. R3: a call below the chat class waits
        # a moment for its own lane before displacing someone else's key.
        if int(waiter.priority) > int(Priority.CHAT):
            wait = self._rules().affinity_wait
            if wait > 0 and (now - waiter.arrived) < wait:
                return None
        # R4: a fresh conversation lane is not displaced ...
        if int(waiter.priority) <= int(Priority.CHAT):
            # ... by BACKGROUND work. The chat class itself is exempt, just as
            # it is from R3: a conversation that waits behind a thought while
            # a lane sits idle is the very thing lanes exist to prevent. It
            # displaces almost nothing, because the pick below is the least
            # recently USED lane — a lane a conversation just left is the last
            # one a chat call reaches for.
            allowed = free
        else:
            allowed = [lane for lane in free
                       if not self._on_hold(lane, waiter.cache_key, now)]
        if not allowed:
            # ... unless waiting for one would be a BLOCKADE instead of a
            # wait. A busy lane will free up by itself, so waiting for it is
            # bounded by a running call; if nothing is running at all, the
            # only thing left to wait for is the hold to expire — that is the
            # case the plan rules out ("no other lane exists at all", and its
            # general form: no other lane can come free).
            if any(lane.busy for lane in pool.lanes):
                return None
            allowed = free
        return min(allowed, key=lambda x: x.last_used)

    def _take_lane(self, pool: _Pool, waiter: _Waiter,
                   label: str) -> Optional[Lane]:
        now = self._now()
        if self._next_in_line(pool, now) is not waiter:
            return None
        lane = self._assignable_lane(pool, waiter, now)
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
