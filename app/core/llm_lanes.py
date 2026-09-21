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
- **R7, a reply takes precedence** (plan § 4 R7 / § 6 P5 item 13): a queued
  chat reply is not a waiter — the respond dispatcher polls ``free_lanes`` and
  starts a turn when one is free, so it never sits in ``pool.waiting`` and R2
  cannot order it. A **reservation** (``reserve`` / ``release_reservation``)
  stands in for it: it takes no lane, it only forbids ``_next_in_line`` to
  hand a freed lane to a waiter of a LOWER class. Same class or higher is
  unaffected, so is a call coming back to its own lane (R1 step 1), and so is
  a call of a turn that is already RUNNING (``running_turn``) — a nested tool
  call held off here would only keep its own pool's lane busy for longer.
  The claim lives from the moment the reply is queued until the reply's own
  call HAS its lane: ``_take_lane`` consumes the claim of the key that just
  took one. Releasing it when the turn merely starts lost the lane again, to
  the parked thought the release itself woke up, while the reply was still
  building its prompt. The TTL (``RESERVATION_TTL_SECONDS``, refreshed by the
  holder) only backstops a holder that dies.
  The consequence, said plainly: while replies are queued for a model, ALL
  queued background work below the chat class on that model waits.

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
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.llm_queue import Priority
from app.core.log import get_logger

logger = get_logger("llm_lanes")

# Never block a caller on the condition variable for longer than this in one
# go: the deadline is computed from the INJECTED clock, so a stepped clock has
# to be re-read regularly for the timeout to land at all.
_WAIT_SLICE_SECONDS = 0.25

# How long ONE reservation counts before it expires by itself (seconds on the
# manager's clock). The holder — the respond dispatcher — refreshes it on
# every one of its ticks, and its tick is at most 0.5 s, so three seconds are
# six missed ticks: enough that a slow tick (the eligibility lookup goes to
# the DB) never drops a reservation the reply still needs, and short enough
# that a dispatcher which dies, is cancelled or loses its queue entry cannot
# hold a pool against background work for longer than a lost turn would cost
# anyway. It is a CONSTANT on purpose: the number follows the dispatcher's
# tick, not an operator's taste, and a config field would only offer a way to
# set it below the tick and break the refresh.
RESERVATION_TTL_SECONDS = 3.0


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
    take that lane away from it either (``_next_in_line``).

    ``running_turn`` marks a call that belongs to a turn ALREADY UNDER WAY —
    the nested tool call of an rp_first turn and the resume behind it
    (``ProviderQueue._wait_for_lane(nested=True)``). It is not new work
    arriving: the lane it waits for is one a running turn will free, and that
    turn holds a lane of its own meanwhile. A reservation therefore does not
    hold it off (``_reservation_block``), for the same reason the ``own_lane``
    step exists — otherwise a thought's tool call on ANOTHER pool, held there
    by that pool's claim, keeps its own pool's lane busy until the turn times
    out, and the replies of that pool wait behind it. It is MARKED by the
    caller, never guessed from the key: from the key alone a nested call and a
    fresh one look the same."""
    cache_key: str
    priority: int
    arrived: float
    ticket: int
    own_lane: Optional[int] = None
    running_turn: bool = False


@dataclass
class _Reservation:
    """A claim on a pool for a call that is NOT in ``pool.waiting``.

    The respond dispatcher polls for a free lane instead of parking on the
    pool, so R2 never sees the reply it is about to start. While the reply is
    queued, the dispatcher holds one of these: it occupies no lane and delays
    nobody of its own class or above — it only stops ``_next_in_line`` from
    giving a lane that frees up to a waiter of a LOWER class (a parked
    thought), which would make the reply wait out a whole background turn.

    ``expires`` is on the manager's clock; ``holder`` is a plain name for the
    admin view ("respond dispatcher"), never anything the rules read.
    """
    cache_key: str
    priority: int
    expires: float
    holder: str = ""


@dataclass
class _Pool:
    key: str
    lanes: List[Lane] = field(default_factory=list)
    waiting: List[_Waiter] = field(default_factory=list)
    # Keyed by cache key: one reserving caller per key, so reserving again is
    # a refresh of its own claim and never a second one.
    reservations: Dict[str, _Reservation] = field(default_factory=dict)
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
                     running_turn: bool = False,
                     label: str = "") -> LaneHandle:
        """Occupies a lane of ``pool_key`` for ``cache_key``.

        ``timeout=None`` waits forever, ``timeout=0`` tries exactly once and
        never blocks; on expiry a ``LaneTimeout`` is raised. ``arrived`` is
        when the CALL first asked (see ``_Waiter``), ``own_lane`` the lane
        this caller just gave back for a nested call (R6), ``running_turn``
        that this call belongs to a turn already under way (see ``_Waiter``).

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
                own_lane=(None if own_lane is None else int(own_lane)),
                running_turn=bool(running_turn))
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
                own_lane: Optional[int] = None,
                running_turn: bool = False, label: str = ""):
        """``acquire_lane`` as a context manager — the lane is released on the
        way out, also when the body raises."""
        handle = self.acquire_lane(pool_key, cache_key, priority,
                                   timeout=timeout, arrived=arrived,
                                   own_lane=own_lane,
                                   running_turn=running_turn, label=label)
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

    def reserve(self, pool_key: str, cache_key: str,
                priority: int = Priority.CHAT, *,
                ttl: float = RESERVATION_TTL_SECONDS,
                holder: str = "") -> None:
        """Claims this pool for a call that cannot park on it — A REPLY TAKES
        PRECEDENCE (plan § 6 P5 item 13).

        A reservation is NOT a lane and takes none. It has exactly one effect:
        while it counts, ``_next_in_line`` refuses to hand a lane that frees
        up to a waiter of a LOWER class than ``priority``. A waiter of the
        same class or a higher one is not touched by it, and neither is a call
        coming back to its OWN lane (R1 step 1, which stands before every
        class comparison — a suspended turn is a running turn, and holding it
        off would mean the lane it needs never frees at all).

        Why a reservation instead of simply parking: a queued reply is not
        ready to run, it still has to build its prompt. Parking it would put a
        thread and, in the loop, a room lock behind every waiting reply and
        hold the lane empty for the whole prompt build. A reservation holds
        the ORDER, not the lane.

        THE COST, SAID PLAINLY: the freed lane may sit idle for up to one
        dispatcher tick (≤ 0.5 s) until the reply asks again and takes it.
        That is the intended trade — it buys the reply its turn instead of a
        whole background turn's wait.

        Reserving again with the same ``cache_key`` REFRESHES this caller's
        own claim (that is what the key is for); it never stacks. ``ttl`` is
        seconds on the manager's clock and is meant to be short: the holder
        refreshes on every tick, and a holder that dies must not block the
        pool (see ``RESERVATION_TTL_SECONDS``).

        HOW A CLAIM ENDS — three ways, and the first is the normal one:
        1. THE CALL IT WAS MADE FOR CONSUMES IT. ``_take_lane`` drops the
           claim whose key is the key of the waiter that just took a lane.
           That is what the own-key exemption in ``_reservation_block`` is
           really for: the claim holds the order from the moment the reply is
           queued until the reply's OWN LLM call has its lane — across the
           room lock, the perception stream and the prompt build, which is
           exactly the stretch where releasing early lost the lane again.
        2. ``release_reservation`` — the holder gives up (the reply left the
           queue, the character became ineligible, the turn ended without ever
           reaching its call).
        3. The TTL, which only backstops a holder that died mid-refresh.

        A claim is NOT made on a pool the manager does not know yet: like
        ``free_lanes`` and ``lane_capacity`` this asks about a pool, it does
        not bring one into being. Such a pool has no lanes and no waiters
        either, so there is nothing to hold off; the first call to touch it
        creates it and the next tick of the holder reserves it for real.
        """
        with self._cond:
            pool = self._pools.get(pool_key)
            if pool is None:
                return
            pool.reservations[cache_key] = _Reservation(
                cache_key=cache_key, priority=int(priority),
                expires=self._now() + max(0.0, float(ttl)),
                holder=holder)

    def release_reservation(self, pool_key: str, cache_key: str) -> None:
        """Drops this caller's claim because it GIVES UP on it — the reply
        left the queue, the character became ineligible, the turn ended
        without ever reaching its LLM call.

        Not the path a reply that RUNS takes: there the claim is consumed by
        the call it was made for, in ``_take_lane``, without anybody
        notifying. Releasing it at the START of the turn instead would wake
        the parked lower class right there, and it would win the lane in
        microseconds while the reply is still building its prompt.

        Idempotent, and it wakes the pool: a waiter the reservation held off
        may take the free lane in the same instant instead of waiting out its
        poll slice.
        """
        with self._cond:
            pool = self._pools.get(pool_key)
            if pool is None:
                return
            if pool.reservations.pop(cache_key, None) is not None:
                self._cond.notify_all()

    def snapshot(self) -> Dict[str, Any]:
        """State of every pool for the admin view (phase 4) and for checks.

        ``age_s`` is the age of the lane's last STAMP, and the stamp is set
        both when a call takes the lane and when it gives it back — so on a
        busy lane it is how long the running call has been on it, and on a
        free one how long the lane has been idle. The two are not the same
        reading, which is why ``running_s`` and ``idle_s`` carry them apart:
        exactly one of them is a number, the other is None, and a lane that
        has never run anything has neither.

        ``waiting`` stays the COUNT (checks and the queue read it as one);
        the calls themselves are ``waiting_calls``, each with the rule that
        holds it — from ``_assignable_lane_reason`` and ``_next_in_line``,
        never derived a second time by the reader.
        """
        with self._cond:
            now = self._now()
            pools = {}
            for key, pool in self._pools.items():
                winner = self._next_in_line(pool, now)
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
                            "running_s": (round(now - lane.last_used, 2)
                                          if lane.busy and lane.last_used
                                          else None),
                            "idle_s": (round(now - lane.last_used, 2)
                                       if not lane.busy and lane.last_used
                                       else None),
                            "used": bool(lane.hot_key),
                        }
                        for lane in pool.lanes
                    ],
                    "waiting_calls": [
                        self._waiter_view(pool, waiter, now, winner)
                        for waiter in pool.waiting
                    ],
                    # Claims, not waiters — they hold no lane and run nothing.
                    # Shown apart for exactly that reason (see ``reserve``).
                    "reservations": [
                        {
                            "cache_key": res.cache_key,
                            "priority": int(res.priority),
                            "holder": res.holder,
                            "expires_in_s": round(res.expires - now, 2),
                        }
                        for res in sorted(self._reservations(pool, now),
                                          key=lambda r: r.cache_key)
                    ],
                }
            return {"pools": pools}

    def _waiter_view(self, pool: _Pool, waiter: _Waiter, now: float,
                     winner: Optional[_Waiter]) -> Dict[str, Any]:
        """One waiting call for the admin view, with the reason it waits.

        Four reasons, and every one of them is what the code that decides
        actually answered — no fifth, invented one:

        ``all_busy`` / ``affinity_wait`` (R3) / ``conversation_hold`` (R4)
        come from ``_assignable_lane_reason``; ``reserved`` means a reply has
        reserved the pool and this call is of a lower class
        (``_reservation_block``); ``outranked`` means a lane IS assignable to
        this call and R2 gave this pass to somebody else. The winner of the
        pass is ``starting`` — it has a lane and is on its way out of the
        list. ``aged`` says whether R2's ageing has already lifted this call a
        class (the answer to "is background work starving").
        """
        lane, reason = self._assignable_lane_reason(pool, waiter, now)
        if lane is not None:
            if waiter is winner:
                reason = "starting"
            elif self._reservation_block(pool, waiter, now) is not None:
                reason = "reserved"
            else:
                reason = "outranked"
        effective = self._effective_priority(waiter, now)
        return {
            "cache_key": waiter.cache_key,
            "priority": int(waiter.priority),
            "effective_priority": effective,
            "aged": effective != int(waiter.priority),
            "waiting_s": round(now - waiter.arrived, 2),
            "reason": reason,
            "own_lane": waiter.own_lane,
            "lane_id": None if lane is None else lane.lane_id,
        }

    def reconfigure(self, pool_key: str, lanes: int) -> None:
        """New lane count for a pool.

        Growing takes effect at once. Shrinking frees the unused lanes
        immediately and the busy ones as they are released — taking a lane
        away from a running call would be the one thing lanes exist to
        prevent.

        Waiters are woken only when the pool really CHANGED. The queue path
        calls ``sync_from_config`` before every single lane attempt, and a
        full pool retries every 0.15 s per pending task: an unconditional
        ``notify_all`` on the one process-wide condition would be hundreds of
        thundering herds per second across ALL pools, each woken thread
        recomputing R1-R4 for every waiter — in exactly the situation where
        the CPU belongs to the running calls. A lane count changes when an
        admin saves, not when a task asks.
        """
        with self._cond:
            pool = self._ensure_pool(pool_key, lanes)
            before = (pool.target, len(pool.lanes))
            self._set_target(pool, lanes)
            if (pool.target, len(pool.lanes)) != before:
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

    def _reservations(self, pool: _Pool, now: float) -> List[_Reservation]:
        """The claims that still count. A PURE read — it changes nothing.

        An expired claim is simply not in the answer. Dropping it from the
        dict is the job of ``_expire_reservations``, which runs where a lane
        is actually handed out: a read (``snapshot``, the admin view, a
        waiter's reason) must not quietly change the state it reports on, or
        the state depends on who looked at it last.
        """
        return [res for res in pool.reservations.values() if res.expires > now]

    def _expire_reservations(self, pool: _Pool, now: float) -> None:
        """Forgets the claims that ran out. Called from the SELECTION pass.

        There is no timer that ends a reservation, because it only ever
        matters in the instant a lane is handed out — the same way R2's ageing
        is recomputed at selection time. A parked waiter re-runs its selection
        every poll slice (``_WAIT_SLICE_SECONDS``), so a claim that ran out is
        noticed a quarter of a second later at the latest, without anybody
        waking it.
        """
        for key in [key for key, res in pool.reservations.items()
                    if res.expires <= now]:
            pool.reservations.pop(key, None)

    def _reservation_block(self, pool: _Pool, waiter: _Waiter,
                           now: float) -> Optional[_Reservation]:
        """The reservation that keeps this waiter from a freed lane, if any.

        A waiter is held only by a claim of a HIGHER class than its own
        (effective, so R2's ageing counts here too — a background call that
        has already waited past ``wait_upgrade_seconds`` is compared with the
        class it has risen to). Its own claim never holds it: the reply that
        reserved the pool is exactly the call this is all for, and when it
        finally asks for its lane it must walk straight through — and consume
        the claim on its way (see ``_take_lane``).

        NEITHER IS A CALL OF A RUNNING TURN (``running_turn``): a nested tool
        call and the resume behind it are not new work, they are a turn that
        is already under way and whose END is what frees a lane. Holding one
        off on THIS pool because a reply is queued here brings that reply
        nothing — the turn keeps the lane it holds on ITS pool for as long as
        we stall it, and the replies waiting on that other pool pay for it
        until the turn times out. Same reasoning as the ``own_lane`` step of
        R1.
        """
        if waiter.running_turn:
            return None
        effective = self._effective_priority(waiter, now)
        for res in self._reservations(pool, now):
            if res.cache_key == waiter.cache_key:
                continue
            if effective > int(res.priority):
                return res
        return None

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
        # A REPLY TAKES PRECEDENCE: while a reservation counts, a waiter of a
        # lower class gets nothing, however long it has been parked. The
        # reserving call is not in this list at all — it is a reply the
        # respond dispatcher will start on its next tick — so without this the
        # parked thought takes the lane the moment it frees and the reply,
        # which only ever polls, finds the pool full again (plan § 6 P5 item
        # 13). Coming back to one's OWN lane is decided above and stays
        # untouched: that is a running turn, not a new arrival.
        self._expire_reservations(pool, now)
        contenders = [(w, lane) for w, lane in contenders
                      if self._reservation_block(pool, w, now) is None]
        if not contenders:
            return None
        best = min(self._effective_priority(w, now) for w, _ in contenders)
        peers = [(w, lane) for w, lane in contenders
                 if self._effective_priority(w, now) == best]
        matching = [(w, lane) for w, lane in peers if lane.hot_key == w.cache_key]
        field = matching or peers
        return min(field, key=lambda item: (item[0].arrived, item[0].ticket))[0]

    def _assignable_lane(self, pool: _Pool, waiter: _Waiter,
                         now: float) -> Optional[Lane]:
        """Which lane this waiter would take right now (see
        ``_assignable_lane_reason``); the reason is dropped."""
        return self._assignable_lane_reason(pool, waiter, now)[0]

    def _assignable_lane_reason(self, pool: _Pool, waiter: _Waiter,
                                now: float) -> Tuple[Optional[Lane], str]:
        """Which lane this waiter would take right now — R1, narrowed by R3
        and R4 — and, when the answer is "none", WHICH rule said so.

        The reason exists for the admin view (phase 4): a waiting name there
        has to carry the rule that holds it, and deriving that a second time
        somewhere else would be a copy of this method that drifts. It is
        therefore produced by the ONE place that decides, and it is one of
        ``all_busy`` / ``affinity_wait`` / ``conversation_hold`` — never a
        guess. A waiter that WOULD get a lane and still does not run is not
        held by any rule in here; that is R2's doing and ``_next_in_line``
        answers it (``outranked``).

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
            return None, "all_busy"
        if waiter.own_lane is not None:
            mine = [lane for lane in free if lane.lane_id == waiter.own_lane]
            if mine:
                return mine[0], ""
        same = [lane for lane in free if lane.hot_key == waiter.cache_key]
        if same:
            # The hottest of them: whatever ran last is most likely still
            # cached in the backend.
            return max(same, key=lambda x: x.last_used), ""
        fresh = [lane for lane in free if not lane.hot_key]
        if fresh:
            return min(fresh, key=lambda x: x.lane_id), ""
        # Only foreign, used lanes left. R3: a call below the chat class waits
        # a moment for its own lane before displacing someone else's key.
        if int(waiter.priority) > int(Priority.CHAT):
            wait = self._rules().affinity_wait
            if wait > 0 and (now - waiter.arrived) < wait:
                return None, "affinity_wait"
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
                return None, "conversation_hold"
            allowed = free
        return min(allowed, key=lambda x: x.last_used), ""

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
        # THE CALL THE CLAIM WAS MADE FOR CONSUMES IT (plan § 4 R7). The
        # reply was queued long before it got here — room lock, perception
        # stream, prompt build and queue worker all lie between the
        # dispatcher's claim and this line — and only now is its lane really
        # taken. Giving the claim up any earlier hands the lane to whoever is
        # parked, which is the very thing it exists to prevent. No notify: the
        # lane is busy from this instant, so there is nothing to take anyway.
        pool.reservations.pop(waiter.cache_key, None)
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


# ── admin view (plan § 6, item 10) ─────────────────────────────────────────

# The priority classes by value, for the admin table. IMAGE_GEN is left out
# on purpose — a GPU job takes a slot of its channel, never a lane, so a
# waiter can never carry it.
_PRIORITY_NAMES: Dict[int, str] = {
    int(Priority.CHAT): "CHAT",
    int(Priority.HIGH): "HIGH",
    int(Priority.NORMAL): "NORMAL",
    int(Priority.LOW): "LOW",
}


def priority_name(value: int) -> str:
    """``CHAT``/``HIGH``/``NORMAL``/``LOW`` — or the bare number for a value
    that is not a rung of the ladder, rather than a wrong label."""
    return _PRIORITY_NAMES.get(int(value), str(int(value)))


def _routing_pools() -> Dict[str, Dict[str, Any]]:
    """The pools the CONFIG defines, with the entries that feed each of them.

    One pool per ``provider/model``, because that is where the prompt cache
    lives: several enabled entries may name the same pair (one per sampling
    profile) and they all run against the same backend slot. Their lane
    counts are folded the same way ``configured_lane_count`` folds them — the
    highest wins — so the admin sees the number that is really in force, not
    the first entry's.

    Disabled entries are left out: they route nothing, so they have no lanes.
    """
    pools: Dict[str, Dict[str, Any]] = {}
    try:
        from app.core import config

        entries = config.get("llm_routing", []) or []
    except Exception as e:  # pragma: no cover - config must never break the view
        logger.debug("lane view: llm_routing not readable: %s", e)
        entries = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("enabled") is False:
            continue
        provider = (entry.get("provider") or "").strip()
        model = (entry.get("model") or "").strip()
        if not provider or not model:
            continue
        key = pool_key_for(provider, model)
        row = pools.setdefault(key, {"provider": provider, "model": model,
                                     "entries": [], "configured_lanes": 1})
        row["entries"].append((entry.get("name") or "").strip() or model)
        try:
            lanes = int(entry.get("max_concurrent") or 1)
        except (TypeError, ValueError):
            # A hand-edited config.json can hold anything; one bad entry must
            # not take the whole lane view down with a 500.
            logger.debug("lane view: %s has no usable max_concurrent", key)
            lanes = 1
        row["configured_lanes"] = max(int(row["configured_lanes"]), lanes)
    return pools


def admin_lane_view(manager: Optional[LaneManager] = None,
                    stats: Optional[Dict[str, Dict[str, Any]]] = None,
                    ) -> Dict[str, Any]:
    """Everything ``/admin/agent-loop`` shows about the lanes, in one payload.

    Two sources, joined on the pool key and never mixed up:

    * the CONFIG says which pools exist and how many lanes each may have —
      that is the only thing known about a pool nobody has called yet, and
      the view says so (``started: false``) instead of printing zeros that
      look like a measurement;
    * the running ``LaneManager`` says what the lanes are doing right now.
      Its numbers are passed through untouched: ``lane_count`` is the number
      of lanes that EXIST (a shrink takes effect as the running calls end, so
      it may lag the configured value for a moment, and seeing that lag is
      the point of showing both).

    The cache share comes from the ring in ``lane_cache_stats`` — the last
    calls of this pool as the logger saw them, with "not reported" kept apart
    from a cold 0 %.

    ``reservations`` is the third list next to lanes and waiters, and it is
    deliberately not folded into either: a reply that is queued in the
    AgentLoop holds no lane and is parked nowhere, it only keeps a freed lane
    from going to lower-class work until it asks again (see ``reserve``).

    A pool the manager knows but the config does not (a renamed entry, an
    unresolved provider ``?/model``) is listed too, marked ``configured:
    false``: hiding it would hide exactly the lanes nobody expects to exist.
    """
    from app.core import lane_cache_stats

    manager = manager or get_lane_manager()
    live = manager.snapshot().get("pools", {})
    stats = lane_cache_stats.snapshot() if stats is None else stats
    configured = _routing_pools()

    keys = list(configured)
    keys += [key for key in live if key not in configured]
    keys += [key for key in stats if key not in configured and key not in live]

    pools = []
    for key in keys:
        cfg = configured.get(key)
        pool = live.get(key)
        provider, _, model = key.partition("/")
        row: Dict[str, Any] = {
            "pool_key": key,
            "provider": (cfg or {}).get("provider", provider),
            "model": (cfg or {}).get("model", model),
            "entries": (cfg or {}).get("entries", []),
            "configured": cfg is not None,
            "configured_lanes": (cfg or {}).get("configured_lanes"),
            "started": pool is not None,
            "lane_count": (pool or {}).get("lane_count"),
            "busy": (pool or {}).get("busy"),
            "free": (pool or {}).get("free"),
            "waiting": (pool or {}).get("waiting", 0),
            "lanes": (pool or {}).get("lanes", []),
            "waiting_calls": (pool or {}).get("waiting_calls", []),
            # A reply that is queued in the AgentLoop and holds this pool
            # against lower-class work. It is NOT a waiting call and the view
            # keeps the two lists apart, because they mean different things:
            # a waiter is parked in the manager, a reservation is a claim for
            # somebody who will only ask on the next dispatcher tick.
            "reservations": (pool or {}).get("reservations", []),
            "cache": stats.get(key) or lane_cache_stats.pool_stats(key),
        }
        for res in row["reservations"]:
            res["priority_label"] = priority_name(res.get("priority", 0))
        for call in row["waiting_calls"]:
            call["priority_label"] = priority_name(call.get("priority", 0))
            call["effective_label"] = priority_name(
                call.get("effective_priority", call.get("priority", 0)))
        pools.append(row)

    pools.sort(key=lambda r: (not r["configured"], r["pool_key"]))
    return {"pools": pools, "ring_size": lane_cache_stats.RING_SIZE}
