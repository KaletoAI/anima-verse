"""Continuous AgentLoop — replaces the old probabilistic ThoughtRunner tick.

Picks the next agent via weighted round-robin (importance 1=Low, 2=Medium,
3=High → 1/2/3 tickets per agent, reshuffled each round). Runs one thought
turn at a time (LLM/GPU is the bottleneck). Sleeping characters and the
user-controlled avatar are excluded.

Chat-response bumps (``bump_respond``) do NOT go through the serial loop:
they live in their own respond lane — a dispatcher task spawns a respond
turn whenever the responder's LLM ENTRY has a free cache lane (no global turn
lock, no min_turn_gap), so a conversation never waits behind unrelated
thought turns. There is no second parallelism knob any more
(plan-cache-lanes.md § 6 P3): how many replies run at once is what
``max_concurrent`` of that entry says, because that is the number the backend
can serve without evicting each other's prompt cache. Answers in the SAME
room stay serialized via a per-room lock (each answer must see the previous
one in the perception stream).

Eligibility (per turn):
    - thoughts_enabled feature is true for the character
    - character is not currently sleeping
    - character is not the user-controlled avatar
    - global pause is off (see _is_paused)

Pause source: shared with the existing TaskQueue admin pause for the
"default" queue. When that's paused, the AgentLoop sleeps too. Persistent
across restarts because the TaskQueue pause lives in the world DB.

Public API:
    get_agent_loop() -> AgentLoop
    AgentLoop.start() / stop() — bootstrap hooks
    AgentLoop.status() -> dict — current/recent/queue snapshot for admin

The forced_thought handler stays on ThoughtRunner (registered separately at
startup); this loop does not handle external triggers.
"""
import asyncio
import logging
import random
from datetime import datetime, timedelta

from app.core.timeutils import parse_iso, utc_now
from app.core.turn_trace import begin_trace, set_trace
from typing import Any, Callable, Dict, List, Optional, Sequence

from app.core.log import get_logger
from app.core.perception import STORYTELLER_SPEAKER

logger = get_logger("agent_loop")


# Sleep when nothing is eligible (everyone sleeping, world paused, etc.)
_IDLE_SLEEP_SECONDS = 30
# Boot grace before the loops start firing turns — lets the rest of the
# server finish wiring up. Module-level so tests can zero it.
_BOOT_GRACE_SECONDS = 15
# Per-turn timeout — guards a hung LLM call from blocking the loop forever.
_TURN_TIMEOUT_SECONDS = 600
# Cap on importance (defensive — config could be junk).
_MIN_IMPORTANCE = 1
_MAX_IMPORTANCE = 3
# How many recent agent picks to keep for the admin status panel.
_RECENT_HISTORY = 20

# In-chat window: defines what counts as "currently chatting with avatar".
# < HOT_MIN: skip the turn entirely — the player is actively writing, the
#   character has nothing useful to offer mid-message.
# HOT_MIN .. WARM_MIN: use the trimmed in-chat template (focus stays on
#   the conversation, no random initiatives).
# > WARM_MIN: regular thought template.
_IN_CHAT_HOT_MIN = 10
_IN_CHAT_WARM_MIN = 30

# Phase 3b: window in which another character's room utterance counts as an
# "active conversation". If the autonomous loop picks someone present within
# that window, their turn runs as a Chime (real utterance or SKIP) instead of
# a discarded in-chat thought. The Backstop caps the chain on top of that.
_ROOM_CONVO_ACTIVE_SEC = 240

# Pacing — keeps the loop from over-ticking with few characters.
# Values are read live from the world config (admin tab "Gedanken"):
#   thoughts.min_turn_gap_seconds        (default 30)
#   thoughts.min_per_char_cooldown_minutes (default 5)
# Both cooldowns apply in addition to the importance round-robin and the
# in-chat-skip / no_llm backoffs.
_MIN_TURN_GAP_DEFAULT = 30
_MIN_PER_CHAR_COOLDOWN_MIN_DEFAULT = 5

# The task ids whose PROMPT a loop turn produces — they decide the cache key
# and the LLM entry the turn will run on (plan-cache-lanes.md § 3).
# A respond turn calls chat_engine.run_chat_turn with task_type
# "character_talk"; an autonomous turn registers as "thought".
_RESPOND_TASK_TYPE = "character_talk"
_THOUGHT_TASK_TYPE = "thought"


def _get_min_turn_gap() -> int:
    """Read thoughts.min_turn_gap_seconds from config (live)."""
    try:
        from app.core import config as _cfg
        return int(_cfg.get("thoughts.min_turn_gap_seconds") or _MIN_TURN_GAP_DEFAULT)
    except Exception:
        return _MIN_TURN_GAP_DEFAULT


def _get_per_char_cooldown_min() -> int:
    """Read thoughts.min_per_char_cooldown_minutes from config (live)."""
    try:
        from app.core import config as _cfg
        return int(_cfg.get("thoughts.min_per_char_cooldown_minutes")
                   or _MIN_PER_CHAR_COOLDOWN_MIN_DEFAULT)
    except Exception:
        return _MIN_PER_CHAR_COOLDOWN_MIN_DEFAULT


def _pool_for(task_type: str, character_name: str) -> str:
    """The lane pool a turn of this character will really run on.

    Resolved the way the turn itself resolves it — ``resolve_llm`` with the
    character's name, so a per-character routing override counts — and turned
    into the pool key of that LLM entry (``provider/model``). One place for
    both loops.

    Unresolvable (task disabled, no provider available, config unreadable) is
    answered with the pool key of the unknown entry, ``?/?``. That is a real
    pool of one lane, so a character whose route cannot be read gets one turn
    at a time instead of an unbounded number — the safe answer, and the
    dispatcher's LLM gate has usually already stopped the lane before it.
    """
    from app.core.llm_lanes import pool_key_for
    try:
        from app.core.llm_router import resolve_llm
        instance = resolve_llm(task_type, agent_name=character_name)
    except Exception as e:  # noqa: BLE001 — routing must never stop a turn
        logger.debug("pool lookup for %s/%s failed: %s",
                     task_type, character_name, e)
        instance = None
    if instance is None:
        return pool_key_for("", "")
    return pool_key_for(instance.provider_name, instance.model)


def _has_hot_lane(character_name: str) -> bool:
    """R5: is this character's thought prompt still on a FREE lane of the
    entry its turn would run on (plan-cache-lanes.md § 4 R5)?

    True means the backend would most likely serve the beginning of that
    prompt from its cache. It is the only thing R5 asks, and it is asked only
    about characters that are due anyway — never to make anybody due.

    Never raises: an unreadable route or lane state answers False, and the
    loop keeps the order it had.
    """
    try:
        from app.core.llm_lanes import cache_key_for, get_lane_manager
        pool_key = _pool_for(_THOUGHT_TASK_TYPE, character_name)
        key = cache_key_for(_THOUGHT_TASK_TYPE, character_name)
        return get_lane_manager().hot_free_lane(pool_key, key)
    except Exception as e:  # noqa: BLE001 — an order hint never stops a turn
        logger.debug("hot-lane check for %s failed: %s", character_name, e)
        return False


def _respond_pool_of(character_name: str) -> str:
    """The pool a reply of this character runs on — the chat entry the reply
    path itself picks (``chat_engine.chat_llm_task``: a temporary NPC answers
    through ``npc_talk``, everyone else through ``chat_stream``)."""
    try:
        from app.core.chat_engine import chat_llm_task
        task = chat_llm_task(character_name)
    except Exception as e:  # noqa: BLE001
        logger.debug("chat task for %s not readable: %s", character_name, e)
        task = "chat_stream"
    return _pool_for(task, character_name)


# Transient network error types the LLM stream can raise when the provider
# drops the connection mid-stream. Caught in the turn handler so they are not
# logged as ERROR with a traceback.
def _is_transient_network_error(err: BaseException) -> bool:
    name = type(err).__name__
    if name in {"ReadTimeout", "ConnectTimeout", "WriteTimeout", "PoolTimeout",
                "RemoteProtocolError", "ConnectError", "ReadError",
                "APIConnectionError", "APITimeoutError"}:
        return True
    module = type(err).__module__ or ""
    return module.startswith("httpx") or module.startswith("httpcore")


class AgentLoop:
    """Asyncio task that ticks one agent thought turn at a time."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._tickets: List[str] = []
        # Priority bumps — characters that should think on the very next
        # available slot, ahead of the round-robin schedule. Used by
        # external triggers (avatar enters room, message received,
        # access-denied, etc.). FIFO; deduplicated.
        self._bump_queue: List[str] = []
        # Optional hints attached to a bump. Pop'd in _run_turn and passed
        # to run_thought_turn as context_hint so the agent sees a "you
        # planned to do X — decide now" prompt prefix. Multiple hints for
        # the same character accumulate (newline-joined).
        self._bump_hints: Dict[str, str] = {}
        # Optional perception-event payload attached to a bump. When set,
        # the next turn for this character renders the given template
        # (e.g. tasks/perceive_announcement.md) instead of the default
        # agent_thought, with template_vars merged into the render context
        # and tools restricted by tool_whitelist. Latest perception wins
        # if multiple arrive before the tick.
        self._bump_perception: Dict[str, Dict[str, Any]] = {}
        # Respond lane (plan-parallel-bump-lane.md): bump_respond entries do
        # NOT share the serial loop. The dispatcher task pops from
        # _respond_queue (FIFO, obligatory-first) and starts a respond turn
        # for every FREE CACHE LANE of the responder's LLM entry
        # (plan-cache-lanes.md § 6 P3). A character never runs two turns at
        # once (_respond_active is checked by the round-robin too); answers in
        # the same room serialize on a per-room asyncio.Lock so each answer
        # sees the previous one.
        self._respond_queue: List[str] = []
        self._respond_to: Dict[str, Dict[str, Any]] = {}
        self._respond_active: Dict[str, asyncio.Task] = {}
        # Which pool each running respond turn is going to occupy. A turn
        # that has just been started does not hold its lane yet (it is still
        # building its prompt), so the free-lane count alone would let the
        # dispatcher start one more turn on every tick until the first of
        # them finally acquires. Entry added at the start, dropped in the
        # worker's finally.
        self._respond_pools: Dict[str, str] = {}
        # Per QUEUE ENTRY, resolved once in bump_respond: the pool key the
        # reply of this name would run on. The dispatcher asks every queued
        # name on every tick, and resolving the entry means a character-config
        # read plus a routing lookup — too much to redo twice a second for a
        # name that is only waiting. Dropped when the name leaves the queue,
        # overwritten by the next bump for the same name.
        self._respond_resolved: Dict[str, str] = {}
        # Per QUEUE ENTRY: why the dispatcher did not start it on its last
        # look ("active" / "no_lane"). Read back by the reservation sync
        # below, and bookkeeping for status().
        self._respond_wait_reason: Dict[str, str] = {}
        # Name -> pool this dispatcher currently RESERVES for a reply that is
        # waiting for a lane (plan-cache-lanes.md § 6 P5 item 13). A reply is
        # a poller, not a waiter, so without the reservation a thought parked
        # in acquire_lane takes every lane that frees. The reservation holds
        # no lane; it only stops lower-class work from taking one. It is
        # TTL-bounded and refreshed on every tick — see
        # _sync_respond_reservations.
        self._respond_reserved: Dict[str, str] = {}
        # Name -> pool whose claim was HANDED OVER to a turn that started
        # (_hand_over_respond_reservation). From that moment the claim belongs
        # to the turn, not to the dispatcher: it has to survive the whole
        # prompt build, and the reply's own LLM call consumes it when it takes
        # its lane. What is left of it is dropped in _respond_worker's finally
        # — for the turns that never reach that call at all.
        self._respond_turn_claims: Dict[str, str] = {}
        self._room_locks: Dict[str, asyncio.Lock] = {}
        self._respond_task: Optional[asyncio.Task] = None
        # Room conversation energy (plan-room-conversation phase 3b): per room
        # a counter of consecutive AI utterances since the last avatar input.
        # Decay per hop + a hard Backstop prevent endless cascades in emergent
        # NPC↔NPC conversations. Avatar input resets it.
        self._room_ai_turns: Dict[str, int] = {}
        # Rooms where the one-off visible exit (concept §5) has already fired
        # for the current cascade. Reset on avatar input.
        self._room_winddown_done: set = set()
        # Last scene idle check (§7 consolidation) — throttled, see below.
        self._last_scene_check: Optional[datetime] = None
        # "Lively" default: up to ~5 AI follow-up turns per avatar input, then
        # cooldown (silence) until the avatar speaks again. Configurable per
        # world/location later (concept §5: the decay rate is THE knob).
        self._chime_backstop: int = 5
        # Player priority (option A): with the avatar in the room, NPCs get
        # only ONE reaction, then the player has the stage — until they act OR
        # `chat.avatar_floor_timeout_minutes` pass without a reaction (then the
        # world may talk among itself again). _room_avatar_idle[key] = start of
        # the floor waiting phase (unix ts); None/missing = avatar just active.
        self._room_avatar_idle: Dict[str, float] = {}
        # Per-character last-real-turn timestamp for cooldown enforcement.
        # Real = full LLM turn (not in_chat_skip / no_llm / error). Used to
        # skip the same char if they ran within _MIN_PER_CHAR_COOLDOWN_MIN.
        self._last_real_turn_at: Dict[str, datetime] = {}
        self._current_agent: str = ""
        self._recent: List[Dict[str, Any]] = []  # [{name, ts, action}]
        self._lock = asyncio.Lock()
        # Standby mode: set when no 'thought' LLM is reachable. Loop polls
        # availability on each idle tick instead of running turns.
        self._llm_standby: bool = False
        # Per-character "in active chat" cooldown. Once an in_chat_skip fired,
        # the char is excluded from eligibility until this point in time —
        # otherwise the loop spins on them at 100Hz and floods the log. The
        # entry is dropped automatically once the time is reached.
        self._chat_skip_until: Dict[str, datetime] = {}
        # C2b: cooldown per (follower->leaver) so a follow suggestion is not
        # re-spammed on every movement event.
        self._follow_cooldown: Dict[str, datetime] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._task is not None:
            logger.debug("AgentLoop already running")
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_forever())
        self._respond_task = asyncio.create_task(self._respond_dispatcher())
        logger.info("AgentLoop started")

    async def stop(self) -> None:
        self._stop.set()
        tasks = [t for t in (self._task, self._respond_task) if t]
        tasks.extend(self._respond_active.values())
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._task = None
        self._respond_task = None
        self._respond_active.clear()
        # Belongs to the very same turns: a worker that was cancelled before
        # its coroutine ever ran never reaches its own finally, so without
        # this its entry would survive a stop/start of this instance and
        # shrink that pool's budget by one for good.
        self._respond_pools.clear()
        # Same reasoning for the claims of the respond dispatcher: nobody
        # refreshes them once its task is gone, and until they ran out by TTL
        # they would keep background work off those pools for nothing. The
        # claims of the turns go with them for the same reason as
        # _respond_pools above: a worker cancelled before its coroutine ever
        # ran never reaches its own finally.
        self._release_respond_reservations()
        for name in list(self._respond_turn_claims):
            self._release_turn_claim(name)
        logger.info("AgentLoop stopped")

    # ------------------------------------------------------------------
    # Status (admin panel)
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        return {
            "running": self._task is not None and not self._stop.is_set(),
            "paused": _is_paused(),
            "standby": self._llm_standby,
            "current_agent": self._current_agent,
            "remaining_in_round": list(self._tickets),
            # Hint bumps only — chat responses live in the respond lane.
            "bumped": list(self._bump_queue),
            "respond_queue": list(self._respond_queue),
            "respond_active": list(self._respond_active.keys()),
            # Why each queued name did not start on the dispatcher's last
            # look — "active" (already in a turn) or "no_lane" (its LLM entry
            # is full). The admin table of phase 4 reads it instead of
            # deriving it again.
            "respond_waiting": {n: self._respond_wait_reason.get(n, "")
                                for n in self._respond_queue},
            "recent": list(self._recent),
        }

    def bump(self, character_name: str, hint: str = "",
             perception_template: str = "",
             perception_vars: Optional[Dict[str, Any]] = None,
             tool_whitelist: Optional[List[str]] = None) -> bool:
        """Mark a character for priority processing — they think next.

        Used by external triggers (avatar room entry, incoming message,
        access-denied, etc.) when the recipient should react sooner than
        their normal importance-quota would allow. Bumps stack FIFO and
        are deduplicated. Bumped characters skip the normal round-robin
        once; afterwards they fall back to importance scheduling.

        Optional ``hint`` is plaintext context that will be prepended to
        the next thought turn for this character (via run_thought_turn's
        context_hint parameter). Multiple hints accumulate. Use this to
        pass scheduler-style "you planned to send Kai a message — decide
        now whether to send it" prompts so the LLM can act, adjust, or
        skip on its own.

        Optional ``perception_template`` swaps the default agent_thought
        prompt for a focused perception template (e.g.
        ``tasks/perceive_announcement.md``). ``perception_vars`` are
        merged into the render context. ``tool_whitelist`` restricts the
        tools the agent may call this turn. Latest perception wins if
        multiple arrive for the same character before the tick.

        Returns True if the bump was registered, False if the character
        is ineligible (sleeping / disabled / avatar / unknown).
        """
        if not character_name:
            return False
        if not _is_agent_eligible(character_name):
            logger.debug("AgentLoop.bump skipped: %s ineligible", character_name)
            return False
        if hint:
            existing = self._bump_hints.get(character_name, "")
            self._bump_hints[character_name] = (
                existing + "\n" + hint if existing else hint)
        if perception_template:
            self._bump_perception[character_name] = {
                "template": perception_template,
                "vars": dict(perception_vars or {}),
                "tool_whitelist": list(tool_whitelist) if tool_whitelist else None,
            }
        if character_name in self._bump_queue:
            return True  # already bumped
        self._bump_queue.append(character_name)
        logger.info("AgentLoop.bump: %s queued for next slot%s%s",
                    character_name,
                    " (with hint)" if hint else "",
                    f" (perception={perception_template})" if perception_template else "")
        return True

    def bump_respond(self, character_name: str, speaker: str,
                     content: str, volume: str = "normal",
                     obligatory: bool = True, hint: str = "",
                     winding_down: bool = False) -> bool:
        """Phase 3: character should react to a room utterance of the speaker.

        Unlike ``bump`` (thoughts/perception) this triggers a VISIBLE chat
        reply that is recorded as a room utterance. Bypasses in-chat gating
        (answers must always go out). Queued into the respond lane — the
        dispatcher runs these turns concurrently, outside the serial loop.

        ``obligatory`` True = addressed → mandatory answer. False = merely
        present → opportunity (chime-in): the turn may stay silent via SKIP.
        A pending mandatory answer is never downgraded by an opportunity.
        """
        if not character_name:
            return False
        if not _is_respond_eligible(character_name):
            logger.debug("AgentLoop.bump_respond skipped: %s ineligible", character_name)
            return False
        existing = self._respond_to.get(character_name)
        if existing and existing.get("obligatory") and not obligatory:
            return True  # obligation beats opportunity
        self._respond_to[character_name] = {
            "speaker": speaker, "content": content,
            "volume": volume, "obligatory": obligatory,
            "hint": hint, "winding_down": winding_down,
        }
        # Mandatory answers go to the FRONT (the lane pops FIFO) so they
        # never starve behind chime opportunities — otherwise the scene can
        # consolidate before the answer ran. A character already running a
        # respond turn stays queued: they answer again afterwards (new
        # utterance, new context); the dispatcher skips active names.
        if character_name in self._respond_queue:
            self._respond_queue.remove(character_name)
        if obligatory:
            self._respond_queue.insert(0, character_name)
        else:
            self._respond_queue.append(character_name)
        # The LLM entry of this reply, resolved HERE and kept for as long as
        # this queue entry lives: the dispatcher looks at every waiting name
        # twice a second, and the lookup behind it reads the character config
        # and the routing. A new bump for the same name resolves again — that
        # is the only invalidation, and it is enough, because the two things
        # that move the answer to another entry (the character becoming a
        # temporary NPC, an edit to the routing) both come with a new
        # utterance long before they matter.
        self._respond_resolved[character_name] = _respond_pool_of(character_name)
        self._respond_wait_reason.pop(character_name, None)
        logger.info("AgentLoop.bump_respond: %s %s to %s", character_name,
                    "answers" if obligatory else "(opportunity)", speaker)
        return True

    def _room_key(self, location_id: str, room_id: str, who: str = "") -> str:
        """Bucket key for the room-scoped loop state: chime budget
        (``_room_ai_turns``), winddown marker (``_room_winddown_done``),
        avatar-floor clock and the respond lock.

        Inside a location that is ``"<loc>/<room>"``. OUTSIDE (E6) it is the
        open-world CELL around ``who``'s point. The wilderness used to
        collapse into the single key ``"/"``, and that key is only ever reset
        by an avatar utterance in the same bucket — so a handful of autonomous
        outdoor lines ANYWHERE exhausted the backstop for the whole open
        world (obligatory answers included) and the winddown marker stayed set
        for the rest of the process. A cell per conversation ends that.

        ``who`` without a point falls back to the shared ``"/"``: a character
        the map does not place is not outdoors, it is nowhere.
        """
        if location_id:
            return f"{location_id}/{room_id or ''}"
        if who:
            from app.models.character import get_character_pos
            from app.core.perception import open_world_cell_key
            pos = get_character_pos(who)
            if pos:
                return open_world_cell_key(pos["x"], pos["z"])
        return "/"

    def reset_room_energy(self, location_id: str, room_id: str,
                          who: str = "") -> None:
        """A NEW conversation is a new beat: the chime budget of the bucket
        starts over and the one-off exit may fire again.

        The avatar does this implicitly with every line (``dispatch_room_
        reactions``, ``is_avatar``). The NPC action tick does it explicitly
        when it OPENS a conversation (spec-npc-conversation § 3): without it a
        room the avatar merely stands next to falls silent after its first
        cascade and never speaks again, because nothing else ever resets the
        counter. The player-priority floor is untouched — with an active
        avatar in the room the effective backstop is still 1.
        """
        key = self._room_key(location_id, room_id, who)
        self._room_ai_turns[key] = 0
        self._room_winddown_done.discard(key)

    def _rooms_with_pending_obligatory(self) -> set:
        """Room keys (loc/room) with a pending MANDATORY answer in the
        respond lane, or with a respond turn currently running. These rooms
        must NOT be idle-consolidated — the stream would be pruned before
        the answer ran (no-answer bug) or mid-answer.

        Location keys only, deliberately: the caller compares them against
        open SCENES, and the wilderness has none (see ``scene_manager.touch``).
        Outdoor cells here would be keys nothing could ever match."""
        keys: set = set()
        try:
            from app.models.character import (get_character_current_location,
                                              get_character_current_room)
            names = {n for n in list(self._respond_queue)
                     if (self._respond_to.get(n) or {}).get("obligatory")}
            names.update(self._respond_active.keys())
            for name in names:
                loc = get_character_current_location(name) or ""
                if loc:
                    room = get_character_current_room(name) or ""
                    keys.add(self._room_key(loc, room))
        except Exception as e:  # noqa: BLE001
            logger.debug("pending-obligatory rooms failed: %s", e)
        return keys

    def room_key(self, location_id: str, room_id: str, who: str = "") -> str:
        """Public form of ``_room_key`` for callers outside the loop (the
        storyteller silence check in ``/play/say``) — same bucket key the
        respond lane uses, so both sides talk about the same room."""
        return self._room_key(location_id, room_id, who)

    def _respond_pending_in_room(self, room_key: str, watch: set) -> bool:
        """Is a respond turn for this room still running or waiting?

        A queue entry is only a NAME — the room it belongs to is derived the
        same way the worker derives its lock (``_char_room_key``). That reads
        the character's CURRENT place, so someone who walked out mid-wait no
        longer counts for this room; ``watch`` (the names the dispatch just
        bumped) keeps them counted anyway, which also covers the open world,
        where two people in one conversation can sit in neighbouring cells.
        """
        for name in list(self._respond_active.keys()) + list(self._respond_queue):
            if not name:
                continue
            if name in watch:
                return True
            try:
                if self._char_room_key(name) == room_key:
                    return True
            except Exception:  # noqa: BLE001 — a lookup miss must not block
                continue
        return False

    async def wait_room_responds_settled(self, room_key: str,
                                         timeout_s: float = 90.0,
                                         names: Optional[Sequence[str]] = None
                                         ) -> bool:
        """Wait until the room has no respond turn active or queued any more.

        Returns True when it settled, False on timeout. Poll (~1 s) against
        the event loop's monotonic clock — this is a technical wait, not game
        time, so no game clock is involved.

        No lead-in wait needed: ``bump_respond`` appends to ``_respond_queue``
        SYNCHRONOUSLY inside ``dispatch_room_reactions``, so by the time the
        caller's task runs, everything this utterance triggered is already
        queued.

        While the loop is paused (admin pause, world freeze, world sleep) the
        dispatcher stalls but the queue KEEPS its entries — so a frozen world
        runs into the timeout and returns False instead of pretending the
        room fell silent.
        """
        watch = {n for n in (names or []) if n}
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, float(timeout_s))
        while True:
            if not self._respond_pending_in_room(room_key, watch):
                return True
            if loop.time() >= deadline:
                logger.info("wait_room_responds_settled: timeout (%.0fs) for room %s",
                            timeout_s, room_key)
                return False
            await asyncio.sleep(1)

    def _recently_conversed(self, npc: str, leaver: str, loc: str, room: str) -> bool:
        """True if the NPC perceived the leaver in this room recently
        (= they were in the same active scene)."""
        try:
            from app.models import perception_store
            for r in perception_store.get_character_room_stream(npc, loc, room, 15):
                if ((r.get("meta") or {}).get("speaker") or "") == leaver:
                    return True
        except Exception:
            pass
        return False

    def suggest_follow(self, leaver: str, from_loc: str, from_room: str,
                       to_loc: str, to_room: str, to_label: str) -> None:
        """C2b: when a conversation partner leaves the room, nudge (hint) the
        NPCs actively involved there so they decide THEMSELVES whether to
        follow (SetLocation) or stay — no forced movement, the NPC may
        say "no", which ends the pursuit naturally. Light per-pair cooldown
        against spam. The C1 movement trace is already in their perception;
        the hint makes the follow choice explicit."""
        if not (leaver and from_loc):
            return
        try:
            from app.core.room_entry import _list_characters_in_room
            present = [c for c in _list_characters_in_room(from_loc, from_room)
                       if c and c != leaver and _is_agent_eligible(c)]
            if not present:
                return
            now = utc_now()
            for npc in present:
                if not self._recently_conversed(npc, leaver, from_loc, from_room):
                    continue
                ck = f"{npc}->{leaver}"
                last = self._follow_cooldown.get(ck)
                if last and (now - last).total_seconds() < 60:
                    continue
                self._follow_cooldown[ck] = now
                self.bump(npc, hint=(
                    f"{leaver} has just left for {to_label}. You can follow "
                    f"with SetLocation or stay here — decide for yourself."))
        except Exception as e:  # noqa: BLE001
            logger.debug("suggest_follow failed: %s", e)

    def dispatch_room_reactions(self, *, speaker: str, content: str, volume: str,
                                location_id: str, room_id: str,
                                addressees: Optional[List[str]] = None,
                                is_avatar: bool = False,
                                hints: Optional[Dict[str, str]] = None,
                                exclude: Optional[List[str]] = None) -> Dict[str, List[str]]:
        """Phase 3b: distributes reactions to a room utterance across the loop.

        - Addressed characters present → mandatory answer (obligatory).
        - Remaining characters present → at most ONE chime, chosen
          server-side BEFORE any LLM runs (``chime_select``, plan
          ``plan-gespraechs-auswahl.md`` § 3.2, decision E2): a bystander
          stuck in a foreign pair stays out, a bystander NAMED in the line
          wins outright, everyone else is drawn against
          ``chattiness x relationship x aim``. Often that draw picks nobody —
          "Hello Liesa" is answered by Liesa, not by the whole room. The
          Backstop still caps the ROUNDS on top of that: avatar input
          recharges the room energy, every AI utterance consumes a hop.
        - Whispering distributes NO chimes (private).

        An EMPTY location_id is the WILDERNESS (E6): the earshot roster is
        then the hearing radius around the SPEAKER instead of the room, and
        the budget bucket is the speaker's open-world cell instead of the
        room (``_room_key``) — everything below works on both unchanged.

        Returns {"obligatory": [...], "chime": [...]} of the characters
        actually bumped.
        """
        from app.core.room_entry import _list_characters_in_room
        # exclude: characters that deliberately must NOT react here (e.g. an
        # NPC invited to a party who already answers via the consent path —
        # otherwise a double reaction).
        _excl = {e for e in (exclude or []) if e}
        # "Leaving" filter: whoever has a travel target AWAY from this location
        # is on their way out — they gave their farewell beat in the triggering
        # turn and get NO further room reactions (otherwise "X leaves but keeps
        # talking"). On arrival the target is cleared → they are back in.
        from app.models.character import get_character_current_location as _gcl
        from app.models.character import get_movement_target as _gmt
        def _leaving(c: str) -> bool:
            if not location_id:
                # Nobody is "walking out" of the open: everyone on the road
                # carries a travel target, so this filter would silence
                # exactly the chance encounters the wilderness branch exists
                # for. Out there you meet people who are on their way.
                return False
            if not (_gcl(c) or ""):
                # A radius neighbour standing OUTSIDE this location is not
                # leaving it — it was never in it. Judging it by the room's
                # own exit rule would silence every passer-by at the gate,
                # because a passer-by always carries a travel target.
                return False
            tgt = _gmt(c)
            return bool(tgt and tgt != location_id)
        # Who is in earshot at all? The room AND the hearing radius — the ONE
        # roster every step below reads, and the SAME union the fan-out
        # (``perception._resolve_presence``) and the addressee gate
        # (``perception.addressable_for``) answer with. Without the radius half
        # inside a location, an NPC waiting in front of the gate could be
        # addressed and would perceive the line, but nobody would ever bump it
        # to answer. The radius list holds only location-less characters, so
        # the two halves never overlap; the speaker is part of the room list
        # and not of the radius list, and every consumer filters it out anyway.
        #
        # A WHISPER stays inside the walls (same rule as ``compute_earshot``):
        # spoken from inside a location it reaches nobody out there.
        from app.core.perception import VOLUME_WHISPER, nearby_in_the_open
        if location_id:
            in_earshot = list(_list_characters_in_room(location_id, room_id))
            if volume != VOLUME_WHISPER:
                _room = set(in_earshot)
                in_earshot += [c for c in nearby_in_the_open(speaker)
                               if c not in _room]
        else:
            in_earshot = nearby_in_the_open(speaker)
        # The bucket the SPEAKER acts in — outside that is its open-world
        # cell, so two conversations far apart keep separate budgets.
        key = self._room_key(location_id, room_id, speaker)
        # Player priority (option A): avatar in the room? Then effective
        # Backstop = 1 (one reaction round, then the stage is free) — unless
        # the avatar has been idle past the timeout, then the world may talk on.
        from app.core.timeutils import utc_now as _un
        _now_ts = _un().timestamp()
        avatar_present = False
        try:
            from app.models.account import is_player_controlled
            avatar_present = any(is_player_controlled(c) for c in in_earshot)
        except Exception:
            avatar_present = False
        effective_backstop = self._chime_backstop
        floor_mode = False
        if avatar_present and not is_avatar:
            idle_since = self._room_avatar_idle.get(key)
            if idle_since is None:
                idle_since = _now_ts
                self._room_avatar_idle[key] = idle_since
            try:
                from app.core import config as _cfg
                timeout_min = float(_cfg.get("chat.avatar_floor_timeout_minutes", 8) or 8)
            except Exception:
                timeout_min = 8.0
            if (_now_ts - idle_since) < timeout_min * 60:
                effective_backstop = 1
                floor_mode = True

        if is_avatar:
            self._room_ai_turns[key] = 0  # avatar sets the beat: energy reset
            self._room_winddown_done.discard(key)  # new cascade → exit allowed again
            self._room_avatar_idle.pop(key, None)  # avatar active → floor clock reset
        else:
            if self._room_ai_turns.get(key, 0) >= effective_backstop:
                # With player priority: simply fall silent (the player is up),
                # NO visible exit beat.
                if floor_mode:
                    logger.info("room %s: avatar present → stage free after 1 round "
                                "(silence until player/timeout)", key)
                    return {"obligatory": [], "chime": []}
                # Otherwise (no avatar / avatar idle for longer): ONE visible
                # exit (concept §5), then silence until the avatar speaks.
                if key not in self._room_winddown_done:
                    self._room_winddown_done.add(key)
                    present = [c for c in in_earshot
                               if c and c != speaker and _is_respond_eligible(c)
                               and not _leaving(c) and c not in _excl]
                    if present:
                        closer = present[0]
                        if self.bump_respond(closer, speaker=speaker, content=content,
                                             volume=volume, obligatory=False,
                                             winding_down=True):
                            logger.info("room %s: Backstop (%d) → visible exit by %s",
                                        key, effective_backstop, closer)
                            return {"obligatory": [], "chime": [], "winddown": [closer]}
                logger.info("room %s: Chime Backstop (%d) reached → silence",
                            key, effective_backstop)
                return {"obligatory": [], "chime": []}

        present = [c for c in in_earshot
                   if c and c != speaker and not _leaving(c) and c not in _excl]
        addr = set(addressees or [])
        out: Dict[str, List[str]] = {"obligatory": [], "chime": []}

        # 1) Mandatory answers to the addressees (first → FIFO priority in the
        #    loop). An optional per-character hint (e.g. spell effect) is passed on.
        _hints = hints or {}
        for c in present:
            if c in addr and self.bump_respond(
                    c, speaker=speaker, content=content, volume=volume,
                    obligatory=True, hint=_hints.get(c, "")):
                out["obligatory"].append(c)
                _halt_addressed_wanderer(c)

        # 2) At most ONE chime among the remaining characters present, picked
        #    here and not by the models: the chime template asks for SKIP and
        #    the LLMs practically never take it, so a round-robin bump IS the
        #    round-robin answer. A whisper is private and distributes none.
        if volume != "whisper":
            from app.core.chime_select import (
                DEFAULT_CHATTINESS, NO_RELATIONSHIP_STRENGTH, Candidate,
                chime_scores, effective_chattiness, select_chimer)
            from app.core.conversation_pairs import partners_in_room
            from app.models.relationship import get_relationship
            from app.models.world import get_location_by_id

            # The pairs standing in this room — read ONCE for the whole
            # selection. Out in the open both keys are empty, and that empty
            # pair IS the wilderness bucket the lines out there are stored
            # under (``recent_room_utterances``), so this arm needs no case
            # of its own.
            partners = partners_in_room(location_id or "", room_id or "")

            def _strength(name: str) -> float:
                """Relationship strength candidate ↔ speaker (symmetric)."""
                try:
                    rel = get_relationship(name, speaker)
                    if rel and rel.get("strength") is not None:
                        return float(rel["strength"])
                except Exception:  # noqa: BLE001
                    logger.debug("chime: relationship %s/%s unreadable",
                                 name, speaker, exc_info=True)
                return NO_RELATIONSHIP_STRENGTH

            candidates = [
                Candidate(name=c, strength=_strength(c),
                          partner=partners.get(c))
                for c in present
                if c not in addr and _is_respond_eligible(c)
            ]
            try:
                chattiness = effective_chattiness(
                    get_location_by_id(location_id) if location_id else None)
            except Exception:  # noqa: BLE001
                logger.debug("chime: chattiness lookup failed for %s",
                             location_id, exc_info=True)
                chattiness = DEFAULT_CHATTINESS
            # E6: the player speaking to the room must never talk into the
            # void — then someone always answers (if anyone can at all).
            always_someone = bool(is_avatar and not addr)
            if candidates and logger.isEnabledFor(logging.DEBUG):
                logger.debug("room %s: chime scores %s",
                             key, chime_scores(
                                 candidates, speaker=speaker,
                                 addressees=list(addr), content=content,
                                 chattiness=chattiness))
            chosen = select_chimer(candidates, speaker=speaker,
                                   addressees=list(addr), content=content,
                                   chattiness=chattiness,
                                   always_someone=always_someone)
            if chosen and self.bump_respond(chosen, speaker=speaker,
                                            content=content, volume=volume,
                                            obligatory=False):
                out["chime"].append(chosen)
                logger.info("room %s: chime → %s (chattiness %.2f, "
                            "%d candidates)", key, chosen, chattiness,
                            len(candidates))
            else:
                logger.info("room %s: no chime (chattiness %.2f, "
                            "%d candidates)", key, chattiness, len(candidates))
        return out

    def pop_hint(self, character_name: str) -> str:
        """Pop accumulated hint text for the character. Returns empty string
        if there is none. Mutates internal state — caller must use the
        returned text in this turn or the hint is lost.
        """
        return self._bump_hints.pop(character_name, "")

    def pop_perception(self, character_name: str) -> Optional[Dict[str, Any]]:
        """Pop a queued perception payload (template/vars/tool_whitelist).

        Returns None if no perception was queued. Mutates internal state —
        caller must use the returned payload in this turn or it is lost.
        """
        return self._bump_perception.pop(character_name, None)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_forever(self) -> None:
        # Brief delay so the rest of the server finishes wiring up before we
        # start firing thought turns.
        try:
            await asyncio.sleep(_BOOT_GRACE_SECONDS)
        except asyncio.CancelledError:
            return

        while not self._stop.is_set():
            try:
                if _is_paused():
                    await asyncio.sleep(_IDLE_SLEEP_SECONDS)
                    continue

                # Health gate: don't pick an agent if no 'thought' LLM is
                # reachable. Without this, the loop would burn through every
                # character in milliseconds (each turn early-returns "no_llm")
                # — flooding logs and blocking the admin UI you'd use to fix
                # the LLM config. State transitions are logged once.
                if not _thought_llm_available():
                    if not self._llm_standby:
                        logger.warning("AgentLoop standby: no 'thought' LLM reachable — loop paused")
                        self._llm_standby = True
                    await asyncio.sleep(_IDLE_SLEEP_SECONDS)
                    continue
                if self._llm_standby:
                    logger.info("AgentLoop resumed: 'thought' LLM reachable again")
                    self._llm_standby = False

                # Scene consolidation (§7): close scenes that have ebbed away +
                # prune raw perceptions. Throttled (~every 60s), LLM/DB in a thread.
                _now = utc_now()
                if (self._last_scene_check is None
                        or (_now - self._last_scene_check).total_seconds() >= 60):
                    self._last_scene_check = _now
                    try:
                        from app.core import scene_manager
                        # Do NOT consolidate rooms with a pending mandatory answer.
                        _skip = self._rooms_with_pending_obligatory()
                        n = await asyncio.to_thread(
                            scene_manager.run_idle_consolidation, _skip)
                        if n:
                            logger.info("AgentLoop: %d scene(s) consolidated", n)
                    except Exception as _sce:
                        logger.debug("scene consolidation tick failed: %s", _sce)

                agent = self._pick_next_agent()
                if not agent:
                    await asyncio.sleep(_IDLE_SLEEP_SECONDS)
                    continue

                try:
                    await self._run_turn(agent)
                finally:
                    # _run_turn begins its trace in THIS context (await does
                    # not copy) — drop it again so the loop's own calls
                    # (scene consolidation) are not tagged with the last
                    # character's thought turn.
                    set_trace(None)

                # Back-off guard: if the last turn returned almost instantly
                # (no LLM, instant error) the loop would otherwise spin
                # through every character in milliseconds — saturating the
                # log and starving the rest of the server (incl. the admin
                # UI you'd use to fix the LLM config). Sleep when we detect
                # the symptom instead of trying to enumerate causes.
                last = self._recent[-1] if self._recent else None
                if last:
                    outcome_val = last.get("outcome")
                    if outcome_val == "in_chat_skip":
                        # in_chat_skip is OK + fast, but we need a minimal breath
                        # so the loop does not mow through other eligible chars
                        # at 100Hz (or hang in a hot spin with only one char —
                        # the per-char cooldown catches that, but we still don't
                        # want too tight a tick).
                        await asyncio.sleep(2)
                        continue
                    bad_outcome = outcome_val in ("no_llm", "timeout") \
                        or str(outcome_val or "").startswith("error")
                    too_fast = last.get("duration_s", 0) < 1.0
                    if bad_outcome or too_fast:
                        await asyncio.sleep(_IDLE_SLEEP_SECONDS)
                        continue
                    # Real turn — global minimum gap to the next one so the
                    # loop does not tick too tightly with few characters.
                    # The value comes from the admin config (tab
                    # "Gedanken" → Min Turn Gap).
                    gap = _get_min_turn_gap()
                    if gap > 0:
                        await asyncio.sleep(gap)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("AgentLoop tick error: %s", e, exc_info=True)
                # Avoid hot-spinning on persistent errors.
                await asyncio.sleep(5)

    # ------------------------------------------------------------------
    # Respond lane (plan-parallel-bump-lane.md)
    # ------------------------------------------------------------------

    def _room_lock(self, room_key: str) -> asyncio.Lock:
        """Per-room lock serializing answers within one room. The '' key
        (unknown location) is a shared fallback lock — conservative: answers
        without a resolvable room serialize against each other."""
        lock = self._room_locks.get(room_key)
        if lock is None:
            lock = asyncio.Lock()
            self._room_locks[room_key] = lock
        return lock

    def _char_room_key(self, character_name: str) -> str:
        """The bucket the character is in right now — its room inside a
        location, its open-world cell outside (E6). Empty only when the
        lookup itself fails.

        Outside used to collapse to one key, which serialized every outdoor
        respond turn in the world behind a single lock; cells make two distant
        conversations run in parallel again, exactly like two rooms."""
        try:
            from app.models.character import (get_character_current_location,
                                              get_character_current_room)
            loc = get_character_current_location(character_name) or ""
            room = get_character_current_room(character_name) or "" if loc else ""
            return self._room_key(loc, room, character_name)
        except Exception:
            return ""

    def _respond_lane_free(self, character_name: str, pool_key: str) -> bool:
        """May a reply of this character START right now — does its LLM entry
        have a lane for it (plan-cache-lanes.md § 6 P3, item 8)?

        Two numbers, and the smaller one decides:

        * ``free_lanes`` for THIS key, asked with the class the reply really
          carries (``Priority.CHAT``, see ``llm_lanes.lane_priority_for``):
          what the assignment rules would hand out at this instant, R4
          included.
        * capacity minus the respond turns already under way on the same pool:
          a turn that was started a moment ago has not acquired its lane yet,
          and without this term the dispatcher would start one more of them on
          every tick until the first one finally does.

        The pool is NOT synchronised with the config here — that is the job of
        the path that actually takes a lane (``ProviderQueue._wait_for_lane``
        calls ``sync_from_config`` before every acquire). Asking must not
        resize a pool a running call is on.

        EXACTLY WHAT THIS PROMISES, because it is not quite "starts only when
        a lane is free": the second term counts the replies THIS dispatcher
        has started, not every call on the pool. A lane taken by somebody else
        between the question and the reply's own acquire — a user chat turn, a
        thought, a nested tool call — is therefore counted as free once, and
        one reply too many can be started per pool. It is deliberately not
        accounted for: the reply then simply waits for its lane inside the
        queue, where every other call waits too, and the alternative — holding
        an actual LANE from the question until the reply's own acquire — would
        keep it empty for exactly as long as it saves. What this guarantees is
        that the dispatcher never starts a SECOND reply on a pool it already
        filled itself — the case that used to repeat on every tick.

        A reply that does NOT start here keeps its pool reserved against
        lower-class work (``_sync_respond_reservations``). That reservation is
        not a lane and changes no number in this method: it only decides who
        gets the lane when one frees.
        """
        from app.core.llm_lanes import cache_key_for, get_lane_manager
        from app.core.llm_queue import Priority

        manager = get_lane_manager()
        key = cache_key_for(_RESPOND_TASK_TYPE, character_name)
        free = manager.free_lanes(pool_key, key, priority=Priority.CHAT)
        starting = sum(1 for pool in self._respond_pools.values()
                       if pool == pool_key)
        return min(free, manager.lane_capacity(pool_key) - starting) >= 1

    def _sync_respond_reservations(self) -> None:
        """Hold the pool of every reply that is waiting for a lane — and let
        go of every other one (plan-cache-lanes.md § 6 P5, item 13).

        THE PROBLEM THIS SOLVES. A queued reply is a POLLER: the dispatcher
        asks ``free_lanes`` twice a second and starts a turn when one is free.
        It never parks in ``acquire_lane``, so it is not in ``pool.waiting``
        and R2 — which orders the calls that ARE waiting — cannot put it in
        front of anybody. A thought turn does park. So the lane a conversation
        was waiting for went to the parked thought the instant it freed, and
        the reply found the pool full again on its next tick: a conversation
        waited out a whole background turn although its class comes first.

        WHY A RESERVATION AND NOT AN ACQUIRE. Parking the dispatcher itself
        would mean holding the lane over the entire prompt build of the reply,
        plus a thread and the room lock behind every queued name. The
        reservation takes no lane: it only forbids the manager to hand a freed
        lane to a call of a LOWER class (``llm_lanes.reserve``). The freed
        lane may therefore idle for up to one tick (≤ 0.5 s) before the reply
        takes it — that is the trade, and it buys the reply a turn's wait
        instead of a background turn's.

        WHAT IS RESERVED. Exactly the names that are in the queue for want of
        a lane — the ``no_lane`` case ``_pop_next_respond`` already records. A
        name that is merely ``active`` (in a turn of its own) reserves
        nothing: its turn holds or will hold its own lane.

        WHEN IT GOES. Here, the moment the reason is no longer ``no_lane``
        and the name is not starting either — the entry left the queue, the
        character became ineligible — and by TTL if this dispatcher never asks
        again at all (cancelled, crashed, paused). The reason map is what is
        read, not the result of this tick's walk: ``_pop_next_respond``
        returns at the first name it can start and does not look at the ones
        behind it, so a name it did not reach keeps the reason, and the
        reservation, it had.

        THE NAME THAT STARTS IS NOT RELEASED HERE — it is not in
        ``_respond_reserved`` any more when this runs. Its claim was HANDED
        OVER to the turn a line earlier (``_hand_over_respond_reservation``),
        and a release would be exactly wrong: releasing notifies the pool, and
        the lower class parked there takes the freed lane in microseconds
        while the reply is still acquiring the room lock and building its
        prompt. That is the bug this whole rule exists against, re-introduced
        at the last possible moment.
        """
        from app.core.llm_lanes import (RESERVATION_TTL_SECONDS, cache_key_for,
                                        get_lane_manager, lane_priority_for)

        manager = get_lane_manager()
        want: Dict[str, str] = {}
        for name in self._respond_queue:
            if self._respond_wait_reason.get(name) != "no_lane":
                continue
            pool_key = self._respond_resolved.get(name)
            if pool_key:
                want[name] = pool_key
        for name, pool_key in list(self._respond_reserved.items()):
            if want.get(name) != pool_key:
                manager.release_reservation(
                    pool_key, cache_key_for(_RESPOND_TASK_TYPE, name))
                self._respond_reserved.pop(name, None)
        for name, pool_key in want.items():
            manager.reserve(pool_key, cache_key_for(_RESPOND_TASK_TYPE, name),
                            lane_priority_for(_RESPOND_TASK_TYPE),
                            ttl=RESERVATION_TTL_SECONDS,
                            holder="respond dispatcher")
            self._respond_reserved[name] = pool_key

    def _release_respond_reservations(self) -> None:
        """Drops every reservation this dispatcher holds.

        For the states in which no reply can start at all — an empty queue,
        the pause switch, an unreachable chat LLM — and for ``stop()``. In
        those the dispatcher does not tick through ``_pop_next_respond``, so
        nothing would refresh the claims; letting them run out by TTL instead
        would keep background work off the pool for three seconds for no
        reason at all.
        """
        from app.core.llm_lanes import cache_key_for, get_lane_manager

        if not self._respond_reserved:
            return
        manager = get_lane_manager()
        for name, pool_key in list(self._respond_reserved.items()):
            manager.release_reservation(
                pool_key, cache_key_for(_RESPOND_TASK_TYPE, name))
        self._respond_reserved.clear()

    def _hand_over_respond_reservation(self, name: str, pool_key: str) -> None:
        """The claim of a reply that STARTS passes from the dispatcher to the
        turn — it is not released (plan § 4 R7).

        The turn does not take its lane when it starts. Between here and the
        reply's own LLM call lie the room lock, the perception stream, the
        prompt build and the queue worker; that stretch is seconds, and it is
        precisely the stretch in which a parked thought used to take the lane
        the reply was waiting for. So the claim has to outlive the start.

        ORDER MATTERS. Re-reserving under the SAME key overwrites the entry in
        place (``reserve`` is a refresh, under the manager's own lock), so
        there is no instant without a claim. A release first would notify the
        pool and let the lower class in through exactly that gap.

        What changes is the holder and the lifetime: the dispatcher refreshed
        its claim every tick and will never look at this name again, so the
        TTL is stretched to the turn's own timeout — beyond which the turn
        does not exist any more either. The claim then ends where it should,
        by being CONSUMED by the reply's call (``llm_lanes._take_lane``), and
        whatever is left of it is dropped in ``_respond_worker``'s finally.
        """
        from app.core.llm_lanes import (cache_key_for, get_lane_manager,
                                        lane_priority_for)

        get_lane_manager().reserve(
            pool_key, cache_key_for(_RESPOND_TASK_TYPE, name),
            lane_priority_for(_RESPOND_TASK_TYPE),
            ttl=float(_TURN_TIMEOUT_SECONDS), holder="respond turn")
        self._respond_reserved.pop(name, None)
        self._respond_turn_claims[name] = pool_key

    def _release_turn_claim(self, name: str) -> None:
        """Drops what is left of a started turn's claim.

        Normally nothing is: the reply's own call consumed it when it took its
        lane. This is for the turns that never get that far — an avatar that
        returns early, an exception in the prompt build, a cancellation, the
        turn timeout. Without it those would hold their pool against
        background work until the turn timeout ran out, and the TTL would be
        doing the work that a finally should do.
        """
        from app.core.llm_lanes import cache_key_for, get_lane_manager

        pool_key = self._respond_turn_claims.pop(name, None)
        if pool_key:
            get_lane_manager().release_reservation(
                pool_key, cache_key_for(_RESPOND_TASK_TYPE, name))

    def _pop_next_respond(self) -> Optional[tuple]:
        """Pop the first queued respond that may start right now. Returns
        (name, payload, pool_key) or None.

        Three reasons not to take a name, and they are not the same:
        a character that is already running a turn is skipped (never two turns
        at once), one that became ineligible since the bump — taken over as an
        avatar, say — is DROPPED, and one whose LLM entry has no free lane
        keeps its place in the queue and is asked again on the next tick.

        The lane check is per candidate, not once per tick: two characters can
        answer through different entries (a temporary NPC on a fast model next
        to an ordinary character), and a full entry must not hold up a reply
        that would run on an empty one.

        WHAT IS CACHED AND WHAT IS NOT. This runs twice a second for every
        waiting name, so only what can actually change between two looks is
        looked up again: whether the character is in a turn (in memory),
        whether it is still eligible (one lookup — an avatar takeover must
        stop the answer) and the lane state. The LLM ENTRY is not re-derived:
        it was resolved when the name entered the queue (``bump_respond`` →
        ``_respond_resolved``) and stays that value until the next bump for
        that name. A name that is in the queue without a resolved entry — only
        possible for a queue that outlived a code path that filled it — is
        resolved here once and cached the same way.

        Every name that does not start keeps its reason in
        ``_respond_wait_reason`` (see ``status()``); it is dropped as soon as
        the name starts or leaves the queue.

        Both ways out end in ``_sync_respond_reservations``: the reasons this
        walk just wrote are what decides which pools stay reserved for a reply
        and which are let go (§ 4 R7). It runs on the way out, after the
        winner has left the queue — and the winner's own claim is handed to
        its turn one line before that, so the sync finds nothing of it to
        release (``_hand_over_respond_reservation``).
        """
        for name in list(self._respond_queue):
            if name in self._respond_active:
                self._respond_wait_reason[name] = "active"
                continue  # never two turns for the same character at once
            if not _is_respond_eligible(name):
                self._respond_queue.remove(name)
                self._respond_to.pop(name, None)
                self._respond_resolved.pop(name, None)
                self._respond_wait_reason.pop(name, None)
                logger.debug("respond lane: %s became ineligible — dropped", name)
                continue
            pool_key = self._respond_resolved.get(name)
            if pool_key is None:
                pool_key = _respond_pool_of(name)
                self._respond_resolved[name] = pool_key
            if not self._respond_lane_free(name, pool_key):
                self._respond_wait_reason[name] = "no_lane"
                continue  # its entry is busy — the name keeps its place
            self._respond_queue.remove(name)
            payload = self._respond_to.pop(name, None)
            self._respond_resolved.pop(name, None)
            self._respond_wait_reason.pop(name, None)
            if not payload:
                continue
            self._hand_over_respond_reservation(name, pool_key)
            self._sync_respond_reservations()
            return name, payload, pool_key
        self._sync_respond_reservations()
        return None

    async def _respond_dispatcher(self) -> None:
        """Own asyncio task feeding the respond lane. Spawns a respond turn
        for every FREE CACHE LANE of the responder's LLM entry — no global
        turn lock, no min_turn_gap, and no separate parallelism knob: how many
        replies may run at once is what ``max_concurrent`` of that entry says
        (plan-cache-lanes.md § 6 P3). Honors the shared pause switch (admin
        pause, world freeze, world sleep) and keeps the queue when the chat
        LLM is unreachable."""
        try:
            await asyncio.sleep(_BOOT_GRACE_SECONDS)
        except asyncio.CancelledError:
            return
        while not self._stop.is_set():
            try:
                # Nothing can start in these three states, so nothing may keep
                # a pool reserved either — and none of them ticks through
                # _pop_next_respond, which is what refreshes the claims.
                if not self._respond_queue:
                    self._release_respond_reservations()
                    await asyncio.sleep(1)
                    continue
                if _is_paused():
                    self._release_respond_reservations()
                    await asyncio.sleep(_IDLE_SLEEP_SECONDS)
                    continue
                if not _chat_llm_available():
                    self._release_respond_reservations()
                    await asyncio.sleep(_IDLE_SLEEP_SECONDS)
                    continue
                nxt = self._pop_next_respond()
                if not nxt:
                    # Either nobody is startable or every entry is busy — the
                    # short nap is what makes the second case a wait for a
                    # lane instead of a spin.
                    await asyncio.sleep(0.5)
                    continue
                name, payload, pool_key = nxt
                self._respond_pools[name] = pool_key
                self._respond_active[name] = asyncio.create_task(
                    self._respond_worker(name, payload))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Respond dispatcher tick error: %s", e, exc_info=True)
                await asyncio.sleep(5)

    async def _respond_worker(self, character_name: str,
                              respond: Dict[str, Any]) -> None:
        """One parallel respond turn: acquire the room lock, run the turn,
        record the outcome. Same outcome semantics as the serial loop
        (cooldown applies via _record_turn), but no min_turn_gap."""
        # Own trace for this turn — set INSIDE the worker coroutine, not in
        # the dispatcher: create_task copies the context, so every worker
        # writes into its own copy and parallel responds stay separable.
        begin_trace("respond", character_name)
        started_at = utc_now()
        outcome = "respond"
        turn_info: Dict[str, Any] = {}
        try:
            room_key = self._char_room_key(character_name)
            async with self._room_lock(room_key):
                turn_info = await asyncio.wait_for(
                    self._run_respond_turn(character_name, respond),
                    timeout=_TURN_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.error("Respond lane TIMEOUT (%ds) for %s",
                         _TURN_TIMEOUT_SECONDS, character_name)
            outcome = "timeout"
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception as e:
            if _is_transient_network_error(e):
                logger.warning(
                    "Respond lane aborted for %s — transient network error "
                    "from LLM provider: %s", character_name, type(e).__name__)
                outcome = "transient_network"
            else:
                logger.error("Respond lane error for %s: %s",
                             character_name, e, exc_info=True)
                outcome = f"error: {type(e).__name__}"
        finally:
            self._respond_active.pop(character_name, None)
            self._respond_pools.pop(character_name, None)
            # Whatever is left of this turn's claim on its pool (§ 4 R7). In
            # the normal case the reply's own LLM call consumed it long ago;
            # this is the backstop for a turn that never reached that call —
            # an avatar's early return, a failed prompt build, a cancellation,
            # the timeout above. The TTL then really only has to survive a
            # dying process.
            self._release_turn_claim(character_name)
            self._record_turn(character_name, started_at, outcome, turn_info)

    # ------------------------------------------------------------------
    # Agent selection (weighted round-robin)
    # ------------------------------------------------------------------

    def _pick_next_agent(self) -> Optional[str]:
        """Pop the next agent from priority bumps OR the current round.

        Order:
          1. Priority bumps (FIFO) — external triggers wanting immediate attention
          2. Round-robin tickets — importance-weighted regular schedule
          3. Refill round and try again

        Agents that became ineligible (sleep, disabled, removed) are
        silently skipped, as are characters currently running a respond
        turn (a character is never in two turns at once). The per-char
        cooldown is filtered here too — a char whose last real turn is
        < _MIN_PER_CHAR_COOLDOWN_MIN ago is skipped. Bumps bypass the
        cooldown deliberately (external triggers like avatar room entry
        must act immediately). Chat responses never appear here — they
        live in the respond lane.

        Among the candidates that are due ANYWAY, the cache lanes decide the
        order (R5, plan-cache-lanes.md § 4): see ``_take_from_tickets``. They
        decide nothing else — tickets, cooldowns and eligibility keep saying
        WHO is due, and a bump stays a bump.
        """
        # 1) Bumped agents come first — cooldown ignored (bump = priority).
        #    A bumped char who is mid-respond stays queued for later.
        deferred: List[str] = []
        picked: Optional[str] = None
        while self._bump_queue and picked is None:
            candidate = self._bump_queue.pop(0)
            if candidate in self._respond_active:
                deferred.append(candidate)
                continue
            if _is_agent_eligible(candidate):
                picked = candidate
        if deferred:
            self._bump_queue[:0] = deferred
        if picked:
            return picked

        cooldown = timedelta(minutes=_get_per_char_cooldown_min())
        now = utc_now()

        def _on_cooldown(name: str) -> bool:
            last = self._last_real_turn_at.get(name)
            if not last:
                return False
            return (now - last) < cooldown

        def _in_chat_skip(name: str) -> bool:
            until = self._chat_skip_until.get(name)
            if not until:
                return False
            if until <= now:
                # expired — drop the entry so the dict does not grow
                self._chat_skip_until.pop(name, None)
                return False
            return True

        def _due(name: str) -> bool:
            """Everything that decides whether this character may take a turn
            at all — unchanged, and asked before R5 ever sees a name."""
            if name in self._respond_active:
                return False   # mid-respond — never two turns at once
            if not _is_agent_eligible(name):
                return False
            if _on_cooldown(name):
                return False
            if _in_chat_skip(name):
                return False
            return True

        # 2) Current round.
        candidate = self._take_from_tickets(_due)
        if candidate:
            return candidate

        # 3) Refill round.
        self._tickets = _build_round_tickets()
        if not self._tickets:
            return None
        return self._take_from_tickets(_due)

    def _take_from_tickets(self,
                           is_due: Callable[[str], bool]) -> Optional[str]:
        """One turn out of the current round — R5 decides the order.

        The tickets are walked in their (shuffled) order, and the walk spends
        exactly the tickets the serial walk before R5 spent:

        * a ticket in FRONT of the first due character is spent right there.
          That is what makes a character on cooldown come up less often and
          not block the round, and it is the behaviour this loop always had;
        * from the first due character onwards a not-due ticket is only
          SKIPPED, never popped. The old loop returned at that point and never
          looked at those tickets at all, so they were judged only when they
          were actually reached — a character that is on cooldown at this
          instant but free again two picks later still gets all its turns.
          Spending them here instead would take an importance-3 character's
          whole round away for one moment of cooldown.

        Among the due characters the walk finds, the one whose prompt is still
        sitting on a free lane of its LLM entry wins
        (``llm_lanes.hot_free_lane``) — one turn where the backend can reuse
        the prompt beginning instead of one where it cannot. ONLY the chosen
        character's ticket is consumed.

        R5 therefore only ever changes the ORDER of characters that were all
        going to run in this round anyway:

        * a character that is not due is never looked at — ``is_due`` has
          already answered for it;
        * the tickets of the ones that are passed over stay in the list, so
          they are picked on the next turns of the same round. A character
          that is never hot therefore comes up in its normal turn; it cannot
          be starved, because the round runs out of hot candidates as they
          take their turns;
        * with nobody hot (the usual case on a fresh pool) the first due
          character wins, which is the order the round already had.

        The pool is read for the THOUGHT entry of each candidate. A turn that
        then turns out to be a chime runs on the chat entry instead — R5
        picked the wrong lane to look at, and the cost of that is nothing: the
        character was due either way and the order is all that changed.
        """
        due: List[str] = []
        verdict: Dict[str, bool] = {}
        index = 0
        while index < len(self._tickets):
            name = self._tickets[index]
            if name not in verdict:
                verdict[name] = bool(is_due(name))
            if not verdict[name]:
                if due:
                    index += 1     # behind the first due name — only skipped
                    continue
                self._tickets.pop(index)   # the ticket is spent, as before
                continue
            if name not in due:
                due.append(name)
            index += 1
        if not due:
            return None
        picked = next((name for name in due if _has_hot_lane(name)), due[0])
        self._tickets.remove(picked)
        return picked

    # ------------------------------------------------------------------
    # Turn execution
    # ------------------------------------------------------------------

    async def _run_respond_turn(self, character_name: str,
                                respond: Dict[str, Any]) -> Dict[str, Any]:
        """Phase 3: produces a chat reply (state-aware via run_chat_turn) and
        records it as a room utterance. Shadow write suppressed (otherwise
        duplicated — we record directly)."""
        import asyncio as _asyncio
        speaker = (respond.get("speaker") or "").strip()
        content = respond.get("content") or ""
        obligatory = bool(respond.get("obligatory", True))
        respond_opportunity = not obligatory  # chime-in may stay silent via SKIP
        winding_down = bool(respond.get("winding_down"))  # visible exit (§5)
        hint = respond.get("hint") or ""      # e.g. spell effect on this char
        if not content.strip():
            return {"preview": "respond: empty", "tools": [], "intents": []}

        # Wake on being addressed (like the old chat path): clear the sleep
        # flag, clear the activity, pull back from off-map. Afterwards the
        # character is awake — answers normally and rejoins the autonomous loop.
        try:
            from app.models.character import (
                is_character_sleeping, set_is_sleeping, wake_from_offmap)
            if is_character_sleeping(character_name):
                set_is_sleeping(character_name, False)
                try:
                    wake_from_offmap(character_name)
                except Exception:
                    pass
                logger.info("respond-turn: %s woken by being addressed", character_name)
        except Exception as e:
            logger.debug("respond-turn wake failed for %s: %s", character_name, e)

        # The responder's room perception stream as conversation context: what
        # they HEARD in the room (multi-party) instead of the old 1:1 history.
        # That way an addressed third party knows what was just said and
        # answers coherently. An empty location is not "no context" but the
        # wilderness stream (E6) — a character answering on the road needs the
        # words it just heard exactly as much as one in a tavern.
        _loc = _room = ""
        room_stream = []
        try:
            from app.models import perception_store
            from app.models.character import (get_character_current_location,
                                               get_character_current_room)
            _loc = get_character_current_location(character_name) or ""
            _room = get_character_current_room(character_name) or ""
            room_stream = perception_store.get_character_room_stream(
                character_name, _loc, _room, limit=40)
            # B (plan-follow-room-conversation-bug): direct follow → prepend
            # the previous room round with the conversation partner so the
            # conversation does not break on a room/location change.
            if speaker:
                carried = perception_store.get_followed_conversation_tail(
                    character_name, speaker, _loc, _room, limit=20)
                if carried:
                    _seen = {r.get("utterance_id") for r in room_stream}
                    carried = [c for c in carried if c.get("utterance_id") not in _seen]
                    room_stream = carried + room_stream
        except Exception as e:
            logger.debug("respond-turn %s: room_stream fetch failed: %s", character_name, e)

        reply = ""
        # Token usage of the reply call, prompt-cache hits included — rides on
        # the utterance as meta.llm_usage (admins see it under the line).
        llm_usage: Dict[str, Any] = {}
        try:
            from app.core import perception_shadow
            from app.core.chat_engine import run_chat_turn
            with perception_shadow.suppressed():
                reply = await _asyncio.to_thread(
                    run_chat_turn, "", character_name, speaker, content,
                    "in_person", "character_talk", True,  # post_process=True
                    room_stream=room_stream,
                    respond_opportunity=respond_opportunity,
                    hint=hint, winding_down=winding_down,
                    usage_out=llm_usage)
        except Exception as e:
            logger.error("respond-turn %s: run_chat_turn failed: %s", character_name, e)
        if reply and reply.strip():
            # MIRROR the volume: if the NPC was addressed in a whisper/shout,
            # they answer at the same volume (normal otherwise). This gives NPCs
            # whispering/shouting without having to "choose" it explicitly — a
            # whispered exchange stays private (only the addressee hears the
            # content), a shouted exchange stays loud.
            _reply_vol = (respond.get("volume") or "normal").strip() or "normal"
            try:
                from app.core.perception import record_utterance
                record_utterance(speaker=character_name, content=reply,
                                 volume=_reply_vol,
                                 addressees=[speaker] if speaker else [],
                                 source="loop",
                                 perception_meta=({"llm_usage": llm_usage}
                                                  if llm_usage else None))
            except Exception as e:
                logger.error("respond-turn %s: record_utterance failed: %s",
                             character_name, e)
            # Cascade: this AI utterance consumes a hop (decay) and gives the
            # remaining characters present a Chime opportunity — until the
            # Backstop kicks in. This is how emergent NPC↔NPC conversations
            # arise and ebb away.
            try:
                key = self._room_key(_loc, _room, character_name)
                self._room_ai_turns[key] = self._room_ai_turns.get(key, 0) + 1
                self.dispatch_room_reactions(
                    speaker=character_name, content=reply, volume=_reply_vol,
                    location_id=_loc, room_id=_room,
                    addressees=[speaker] if speaker else [], is_avatar=False)
            except Exception as e:
                logger.debug("respond-turn %s: cascade dispatch failed: %s",
                             character_name, e)
        elif obligatory:
            # The mandatory answer came back EMPTY (LLM SKIP/refusal) → make it
            # visible; otherwise it looks like "ignored" (no-answer bug).
            logger.warning("respond-turn %s: MANDATORY answer to %s came back "
                           "EMPTY — no utterance recorded",
                           character_name, speaker or "?")
        return {"preview": (reply or "(no reply)")[:80], "tools": [], "intents": [],
                # Full reply for the multi-line preview; the tool phase runs
                # inside run_chat_turn and is not surfaced here.
                "rp_response": reply or ""}

    def _maybe_active_conversation_chime(self, character_name: str) -> Optional[Dict[str, Any]]:
        """Phase 3b: if the character is in an ACTIVE room conversation, returns
        a respond dict for a Chime opportunity (real utterance or SKIP) — instead
        of a discarded in-chat thought. Unifies thought→speech for conversation
        participants.

        None when: no fresh utterance by someone else in the room, or the room
        energy (Backstop) is exhausted (then the loop falls back to the
        regular thought — the scene is ebbing away).

        Works outside a location too (E6): the wilderness stream is what the
        character heard in the open, so a conversation on the road keeps the
        same speech-instead-of-thought turn a room conversation gets — with
        the character's open-world cell as the backstop bucket (``_room_key``).
        """
        try:
            from app.models.character import (get_character_current_location,
                                               get_character_current_room)
            from app.models import perception_store
            from app.core.timeutils import utc_now as _now, parse_iso
            loc = get_character_current_location(character_name) or ""
            room = get_character_current_room(character_name) or ""
            if self._room_ai_turns.get(
                    self._room_key(loc, room, character_name), 0) >= self._chime_backstop:
                return None  # scene ebbing away → no more autonomous follow-ups
            stream = perception_store.get_character_room_stream(character_name, loc, room, limit=6)
            for row in reversed(stream):  # newest first (stream is oldest→newest)
                meta = row.get("meta") or {}
                sp = (row.get("speaker") or meta.get("speaker") or "").strip()
                content = (row.get("content") or "").strip()
                if not content or (row.get("kind") or "") == "whisper_meta":
                    continue
                if not sp or sp == character_name or sp == STORYTELLER_SPEAKER:
                    continue  # narrator events are perception, not a conversation partner
                # check freshness
                try:
                    age = (_now() - parse_iso(row.get("ts") or "")).total_seconds()
                except Exception:
                    return None
                if age < 0 or age > _ROOM_CONVO_ACTIVE_SEC:
                    return None
                # Pair gate (plan § 3.3): a line aimed at two other people is
                # THEIR conversation. Chiming in on it is exactly the
                # round-robin this strand removes on the dispatch side — so
                # the thought turn may only pick up a line that went to the
                # room, that went to this character, or that involves its own
                # conversation partner.
                raw_addr = meta.get("addressees")
                line_addr = [str(a).strip() for a in raw_addr
                             if str(a or "").strip()] \
                    if isinstance(raw_addr, (list, tuple)) else []
                if line_addr and character_name not in line_addr:
                    from app.core.conversation_pairs import conversation_partner
                    partner = conversation_partner(character_name, loc, room)
                    if not partner or (partner != sp
                                       and partner not in line_addr):
                        logger.debug("active-conversation chime %s: %s is in "
                                     "a foreign pair", character_name, sp)
                        return None
                return {"speaker": sp, "content": content, "volume": "normal",
                        "obligatory": False, "hint": "", "winding_down": False}
            return None
        except Exception as e:
            logger.debug("active-conversation chime check %s failed: %s", character_name, e)
            return None

    async def _run_turn(self, character_name: str) -> None:
        """Run a single thought turn for the given character."""
        # Trace root for the thought turn — also covers the chime path below,
        # which produces a spoken contribution instead of a thought. The
        # caller (_run_forever) clears it again after the await, because an
        # awaited coroutine sets context vars in ITS caller's context.
        begin_trace("thought", character_name)
        async with self._lock:
            self._current_agent = character_name
            started_at = utc_now()
            outcome = "ok"
            turn_info: Dict[str, Any] = {}

            try:
                # Phase 3b: in an active room conversation? Then run a chime
                # opportunity instead of a discarded in-chat thought — the
                # contribution is spoken (utterance) or deliberately skipped.
                # The backstop in the detection prevents endless chatter.
                # Chat-answer bumps do NOT pass through here anymore — they
                # run in the respond lane; the room lock below keeps this
                # serial-loop chime serialized with the lane's answers.
                _chime = self._maybe_active_conversation_chime(character_name)
                if _chime:
                    async with self._room_lock(self._char_room_key(character_name)):
                        turn_info = await self._run_respond_turn(character_name, _chime)
                    outcome = "respond"
                    return

                from app.core.thought_context import build_thought_context
                from app.core.prompt_templates import render
                from app.core.thoughts import get_thought_runner
                from app.core.agent_inbox import mark_thought_processed

                # In-chat gating: HOT (<10min) skip, WARM (10-30min) use the
                # trimmed in-chat template, otherwise regular thought.
                chat_age_min = _minutes_since_last_chat_with_avatar(character_name)
                if chat_age_min is not None and chat_age_min < _IN_CHAT_HOT_MIN:
                    # Set the per-char cooldown: while the chat is still HOT,
                    # eligible again only after the missing remainder.
                    # Otherwise the loop spins on this char at 100Hz.
                    remaining_s = max(60.0,
                        (_IN_CHAT_HOT_MIN - chat_age_min) * 60.0)
                    self._chat_skip_until[character_name] = (
                        utc_now() + timedelta(seconds=remaining_s))
                    logger.info(
                        "AgentLoop skip %s: in active chat (%.1f min ago) "
                        "— cooldown %.0fs",
                        character_name, chat_age_min, remaining_s)
                    outcome = "in_chat_skip"
                    turn_info = {"preview": f"in-chat skip ({chat_age_min:.1f}min)",
                                 "tools": [], "intents": []}
                    return

                # Deterministic auto-sleep: on exhaustion (stamina<10) the loop
                # sends the char home / offmap on its own, without consulting
                # the LLM thought. Prevents an exhausted character standing
                # around on the map forever because the LLM never turns the
                # "go home" instruction into a tool call.
                _auto_sleep = self._maybe_auto_sleep(character_name)
                if _auto_sleep:
                    outcome = _auto_sleep["outcome"]
                    turn_info = {"preview": _auto_sleep["preview"],
                                 "tools": _auto_sleep.get("tools", []),
                                 "intents": []}
                    return

                # Activity stat tick: the RUNNING activity influences status
                # values over time (gym drains stamina, resting restores) —
                # cheap interval gate here, LLM round in a background thread
                # (plan-activity-stat-effects.md Baustein 2).
                try:
                    from app.core.stat_effects import maybe_activity_tick
                    maybe_activity_tick(character_name)
                except Exception as e:
                    logger.debug("activity stat tick failed for %s: %s",
                                 character_name, e)

                template_name = "chat/agent_thought.md"
                if (chat_age_min is not None
                        and _IN_CHAT_HOT_MIN <= chat_age_min < _IN_CHAT_WARM_MIN):
                    template_name = "chat/agent_thought_in_chat.md"

                # Discovery check: before the thought build, so the discovered
                # place shows up in the list_locations_for_character context
                # right away and the character can think about it in this tick.
                # Live again since E6: the rule rolls over what is within
                # SIGHT RANGE in metres (it walked grid neighbours before, and
                # the seamless world has none). This is the condition-gated,
                # announced variant — the silent deterministic pass runs in
                # the travel ticker (``core/discovery.py``).
                try:
                    from app.models.rules import check_discover_rules
                    check_discover_rules(character_name)
                except Exception as _de:
                    logger.debug("Discover check for %s failed: %s",
                                 character_name, _de)

                # Perception payload (e.g. announcement) overrides the
                # template before render. Pop'd here so the choice stays
                # visible in the same scope as the system_prompt build.
                perception = self.pop_perception(character_name)
                ctx = build_thought_context(character_name)
                if perception and perception.get("template"):
                    template_name = perception["template"]
                    extra_vars = perception.get("vars") or {}
                    if extra_vars:
                        ctx.update(extra_vars)
                system_prompt = render(template_name, **ctx)

                thought_loop = get_thought_runner()
                if thought_loop is None:
                    logger.warning("ThoughtRunner instance missing — cannot run turn for %s",
                                   character_name)
                    outcome = "no_thought_runner"
                    return

                # Pop bump-hint (e.g. "scheduled message: …") and forward
                # it to the thought turn so the LLM sees the trigger.
                hint = self.pop_hint(character_name)
                _perception_whitelist = (perception or {}).get("tool_whitelist")

                try:
                    result = await asyncio.wait_for(
                        thought_loop.run_thought_turn(
                            character_name,
                            context_hint=hint,
                            tool_whitelist=_perception_whitelist,
                            system_prompt_override=system_prompt),
                        timeout=_TURN_TIMEOUT_SECONDS)
                    if isinstance(result, dict):
                        turn_info = result
                        if turn_info.get("status") == "no_llm":
                            outcome = "no_llm"
                except asyncio.TimeoutError:
                    logger.error("AgentLoop turn TIMEOUT (%ds) for %s",
                                 _TURN_TIMEOUT_SECONDS, character_name)
                    outcome = "timeout"

                # Mark inbox as processed regardless of outcome — even if the
                # agent ignored unread messages, we don't want them to pile
                # up indefinitely on every future turn.
                mark_thought_processed(character_name)

            except Exception as e:
                # Log transient network errors from the LLM provider (stream
                # timeout, dropped connection) as a one-liner — the next tick
                # retries anyway, no full traceback needed.
                if _is_transient_network_error(e):
                    logger.warning(
                        "AgentLoop turn aborted for %s — transient network "
                        "error from LLM provider: %s",
                        character_name, type(e).__name__)
                    outcome = "transient_network"
                else:
                    logger.error("AgentLoop turn error for %s: %s",
                                 character_name, e, exc_info=True)
                    outcome = f"error: {type(e).__name__}"
            finally:
                self._record_turn(character_name, started_at, outcome, turn_info)
                self._current_agent = ""

    def _maybe_auto_sleep(self, character_name: str) -> Optional[Dict[str, Any]]:
        """On exhaustion (stamina<10) send the character home autonomously.

        Three paths:
          1. home_location=__offmap__ → enter_offmap_sleep directly
          2. already at home_location → set activity to Sleeping
          3. elsewhere → start a timed journey home (travel ticker drives
             the movement; the next check here settles the sleep)

        Returns dict {outcome, preview, tools} when it acted, else None.
        Idempotent per tick: already home → sleep, journey home running →
        no-op, offmap → continue.
        """
        try:
            from app.models.character import (
                get_character_profile, get_character_config,
                get_character_current_location, OFFMAP_SLEEP_SENTINEL,
                enter_offmap_sleep, set_is_sleeping)
            profile = get_character_profile(character_name) or {}
            stamina = (profile.get("status_effects") or {}).get("stamina")
            if stamina is None or stamina >= 10:
                return None  # not exhausted

            cfg = get_character_config(character_name) or {}
            home_loc = (cfg.get("home_location") or "").strip()
            if not home_loc:
                return None  # no home_location -> nothing we can do

            cur_loc = (get_character_current_location(character_name) or "").strip()
            already_offmap = not cur_loc

            # Path 1: home is offmap
            if home_loc == OFFMAP_SLEEP_SENTINEL:
                if already_offmap:
                    set_is_sleeping(character_name, True)
                    logger.info("Auto-sleep: %s already offmap, activity=Sleeping",
                                character_name)
                    return {"outcome": "auto_sleep_offmap_continue",
                            "preview": f"already offmap, sleeping (stamina={stamina})",
                            "tools": ["Sleep"]}
                if enter_offmap_sleep(character_name):
                    set_is_sleeping(character_name, True)
                    logger.info("Auto-sleep: %s exhausted (stamina=%s) -> offmap",
                                character_name, stamina)
                    return {"outcome": "auto_sleep_offmap",
                            "preview": f"exhausted (stamina={stamina}) → offmap sleep",
                            "tools": ["SetLocation", "Sleep"]}

            # Path 2/3: home is a regular location
            if cur_loc == home_loc:
                # Already home — set activity to Sleeping
                set_is_sleeping(character_name, True)
                logger.info("Auto-sleep: %s at home, activity=Sleeping",
                            character_name)
                return {"outcome": "auto_sleep_at_home",
                        "preview": f"home & exhausted (stamina={stamina}) → sleeping",
                        "tools": ["Sleep"]}

            # Leave gate: a confined character cannot walk home even when
            # exhausted — sleeps in place instead.
            try:
                from app.models.rules import check_leave
                _auto_leave_ok, _auto_leave_reason = check_leave(character_name)
            except Exception:
                _auto_leave_ok, _auto_leave_reason = True, ""
            if not _auto_leave_ok:
                set_is_sleeping(character_name, True)
                logger.info("Auto-sleep: %s confined (%s) -> sleeping in place",
                            character_name, _auto_leave_reason)
                return {"outcome": "auto_sleep_confined",
                        "preview": f"exhausted (stamina={stamina}) → confined, sleeping in place",
                        "tools": ["Sleep"]}

            # Elsewhere — start a timed journey home. Arrival is handled by
            # the travel ticker; the NEXT auto-sleep check (stamina still
            # low, now at home) flips the character to sleeping.
            # Guard: if a journey home is already running, leave it alone —
            # restarting would reset started_at_game on every loop pick
            # (~30s) and the character would never walk a single metre.
            # Journeying toward somewhere ELSE is re-pointed home.
            from app.core.travel_engine import get_journey, start_journey
            j = get_journey(character_name)
            if j and j.get("target") == home_loc:
                return {"outcome": "auto_sleep_walking",
                        "preview": f"exhausted (stamina={stamina}) → journey home in progress",
                        "tools": []}
            j, reason = start_journey(character_name, home_loc)
            if j is None:
                # No way home at all — unknown, unplaced or unwalkable target
                # (the reason is logged, the outcome is the same): sleep in
                # place instead of pacing the loop forever.
                set_is_sleeping(character_name, True)
                logger.warning(
                    "Auto-sleep: no way home for %s (%s) — sleeping in place",
                    character_name, reason)
                return {"outcome": "auto_sleep_no_path",
                        "preview": f"exhausted (stamina={stamina}) → no path home, sleeping in place",
                        "tools": ["Sleep"]}
            logger.info("Auto-sleep: %s journeys home to %s (%d waypoints)",
                        character_name, home_loc, len(j["waypoints"]))
            return {"outcome": "auto_sleep_walking",
                    "preview": f"exhausted (stamina={stamina}) → journeying home",
                    "tools": ["SetLocation"]}
        except Exception as e:
            logger.debug("_maybe_auto_sleep failed for %s: %s",
                         character_name, e)
            return None

    def _record_turn(self, name: str, started_at: datetime, outcome: str,
                     turn_info: Optional[Dict[str, Any]] = None) -> None:
        info = turn_info or {}
        # Game time at turn end — same format as thoughts.game_ts (canonical
        # GameTime string); '' when the game clock is unavailable.
        try:
            from app.core.timeutils import game_time
            _game_ts = game_time().canonical()
        except Exception:
            _game_ts = ""
        self._recent.append({
            "agent": name,
            "started_at": started_at.isoformat(),
            "game_ts": _game_ts,
            "duration_s": round((utc_now() - started_at).total_seconds(), 1),
            "outcome": outcome,
            "tools": list(info.get("tools") or []),
            "intents": list(info.get("intents") or []),
            "preview": str(info.get("preview") or ""),
            # Untruncated RP / Tool-LLM answers for the multi-line preview.
            "rp_response": str(info.get("rp_response") or ""),
            "tool_response": str(info.get("tool_response") or ""),
        })
        if len(self._recent) > _RECENT_HISTORY:
            self._recent = self._recent[-_RECENT_HISTORY:]
        # Per-char cooldown only for REAL turns (the LLM ran, produced output
        # or triggered tools). Skips/errors deliberately do NOT trigger the
        # cooldown — otherwise an in_chat_skip would cause a 5min block even
        # though nothing happened.
        # respond counts as a real turn (the LLM ran) → set the cooldown so the
        # autonomous round-robin does not immediately pull the same char as a
        # Chime again. Cascade bumps bypass the cooldown anyway (the
        # conversation keeps flowing).
        is_real = (outcome == "ok" or (outcome or "").startswith("ok")
                   or outcome == "respond")
        if is_real:
            self._last_real_turn_at[name] = utc_now()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_paused() -> bool:
    """Global pause indicator. Mirrors the existing world-pause toggle so
    Admin/World-Dev pause buttons stop the AgentLoop too — PLUS the persistent
    world freeze (autonomous simulation frozen) and the world sleep mode (all
    NPCs asleep -> no NPC LLM turns; the periodic jobs / memory consolidation
    keep running separately)."""
    try:
        from app.models.world import is_world_frozen, is_world_sleeping
        if is_world_frozen() or is_world_sleeping():
            return True
    except Exception:
        pass
    try:
        from app.core.task_queue import get_task_queue
        tq = get_task_queue()
        return bool(tq and tq._is_paused("default"))
    except Exception:
        return False


def _chat_llm_available() -> bool:
    """Probe whether the chat route resolves to a live provider — the
    respond lane's counterpart to _thought_llm_available. Must probe the
    SAME task id the respond turn resolves (run_chat_turn →
    resolve_llm("chat_stream")): an id that is not in TASK_TYPES has no
    routing chain and resolves to None FOREVER, which silently parks the
    whole lane (2026-07-30 regression: the probe said "chat")."""
    try:
        from app.core.llm_router import resolve_llm
        return resolve_llm("chat_stream") is not None
    except Exception:
        return False


def _thought_llm_available() -> bool:
    """Probe whether the global 'thought' route resolves to a live provider.

    Per-character overrides are not considered — this is the cheap loop-wide
    gate. False positives (override exists but global down) just mean a
    handful of agents skip a round, which is acceptable.
    """
    try:
        from app.core.llm_router import resolve_llm
        return resolve_llm("thought") is not None
    except Exception:
        return False


def _last_chat_message_ts(character_name: str,
                          avatars: Sequence[str]) -> Optional[str]:
    """Timestamp of the newest ``chat_messages`` row between this character and
    one of ``avatars`` — the DM/phone/TalkTo/Telegram half of the in-chat rule.

    Both storage directions (A,B)/(B,A) are covered.
    """
    from app.core.db import get_connection
    names = list(avatars)
    if not names:
        return None
    marks = ",".join(["?"] * len(names))
    params = (names + [character_name]     # char=avatar AND partner=this
              + [character_name] + names)  # char=this AND partner=avatar
    sql = (f"SELECT MAX(ts) FROM chat_messages WHERE "
           f"(character_name IN ({marks}) AND partner=?) "
           f"OR (character_name=? AND partner IN ({marks}))")
    row = get_connection().execute(sql, params).fetchone()
    return row[0] if row and row[0] else None


def _minutes_since_last_chat_with_avatar(character_name: str) -> Optional[float]:
    """Minutes since this character last exchanged words **with an avatar
    (player-controlled character)** — None when it never did.

    THE in-chat rule of the whole app: the loop skips its own turns on it, and
    ``npc_actions._in_chat`` hands it to the action tick, the wanderer arrival,
    the TTL sweep and the window sweep. "Do not walk this character away, the
    player is writing to it."

    TWO SOURCES, because the app has two ways of talking:

    * the PERCEPTION STREAM (``perception_store.last_shared_utterance_ts``) —
      what ``/play`` produces. Room mode writes NO ``chat_messages`` rows at
      all (``chat_engine`` skips every ``save_message`` when ``room_mode`` is
      set, and every respond turn is room mode), so a whole conversation in
      the player UI used to leave this function answering None: the guards
      built on it were inert on the one path the player actually uses.
    * ``chat_messages`` — still the truth for DM/phone, TalkTo and Telegram.

    The newer of the two wins. Both are SYSTEM-time stamps (``utc_now_iso``),
    which is the right clock here: this is a technical "how long ago", not an
    in-world duration.

    NPC↔NPC talk does not count in either source — only rows/utterances shared
    with an AVATAR (``account.get_all_avatars``, multi-user, honours
    ``users.settings.active_character``). Without that a character was locked
    out of thinking the moment it used TalkTo.
    """
    try:
        from app.models.account import get_all_avatars
        from app.models import perception_store
        # Drop the char itself (it is never its own avatar — and if it were,
        # the loop would already skip it as is_player_controlled)
        avatars = sorted(a for a in (get_all_avatars() or set())
                         if a and a != character_name)
        if not avatars:
            return None
        stamps = [perception_store.last_shared_utterance_ts(character_name,
                                                            avatars),
                  _last_chat_message_ts(character_name, avatars)]
        newest = None
        for raw in stamps:
            if not raw:
                continue
            try:
                parsed = parse_iso(raw)
            except (ValueError, TypeError):
                continue
            if newest is None or parsed > newest:
                newest = parsed
        if newest is None:
            return None
        return (utc_now() - newest).total_seconds() / 60.0
    except Exception as e:
        logger.debug("chat-age check failed for %s: %s", character_name, e)
        return None


def _is_agent_eligible(character_name: str) -> bool:
    """Check thoughts_enabled feature, sleep state, and avatar exclusion."""
    if not character_name:
        return False
    try:
        from app.models.account import is_player_controlled
        if is_player_controlled(character_name):
            return False
    except Exception:
        pass
    # Avatar-only presence: not controlled -> stays gone, no autonomous
    # acting and NOT pulled back via wake_from_offmap.
    try:
        from app.models.character import get_character_config
        cfg = get_character_config(character_name) or {}
        if str(cfg.get("avatar_only_presence", "")).strip().lower() == "true":
            return False
    except Exception:
        pass
    try:
        from app.models.character import is_character_sleeping, wake_from_offmap
        if is_character_sleeping(character_name):
            return False
        # Char no longer in the sleep slot, but maybe still forgotten offmap?
        # Pull them back lazily so the loop works with them normally afterwards.
        wake_from_offmap(character_name)
    except Exception:
        pass
    try:
        from app.models.character_template import is_feature_enabled
        if not is_feature_enabled(character_name, "thoughts_enabled"):
            return False
    except Exception:
        return False
    return True


def _halt_addressed_wanderer(character_name: str) -> bool:
    """A WANDERER that was just addressed stops walking. True when it did.

    Being spoken to is the one thing a passer-by reacts to by standing still.
    Without this the answer goes out while the travel ticker keeps carrying
    the NPC down the road, and two exchanges later it is out of earshot in the
    middle of its own sentence — the "wanderer walks away mid-conversation"
    symptom.

    Only the JOURNEY is cancelled, never the road: ``wander_target`` stays on
    the profile, so ``npc_spawn._settle_wanderer`` picks the trip back up
    through its ordinary retry branch once the conversation has cooled (that
    branch is gated on the same HOT window as this one is triggered by an
    utterance). The cancel path is the one ``/play/travel/cancel`` uses, and
    it is idempotent — a wanderer already standing still has nothing to drop.

    Narrow on purpose: a temporary NPC carrying ``npc_wanderer``. An ordinary
    character on its way somewhere has its own reason to be travelling and
    keeps it (a rule cannot tell an errand from a stroll), and a wanderer that
    merely OVERHEARS a line was not addressed at all.
    """
    if not character_name:
        return False
    try:
        from app.models.character import (get_character_profile,
                                          is_temporary_npc)
        if not is_temporary_npc(character_name):
            return False
        profile = get_character_profile(character_name) or {}
        if not profile.get("npc_wanderer") or not profile.get("journey"):
            return False
        from app.core.travel_engine import cancel_journey
        cancel_journey(character_name)
        logger.info("Wanderer %s stops: it was addressed", character_name)
        return True
    except Exception as e:  # noqa: BLE001 — an answer is never blocked by this
        logger.debug("halt check for %s failed: %s", character_name, e)
        return False


def _is_respond_eligible(character_name: str) -> bool:
    """Eligibility for a DIRECT answer (phase 3, bump_respond).

    Reacting ≠ autonomous thinking: whoever is addressed answers — hence NO
    thoughts_enabled gate and NO sleep gate. Only the player-controlled avatar
    does not answer on its own.
    """
    if not character_name:
        return False
    try:
        from app.models.account import is_player_controlled
        if is_player_controlled(character_name):
            return False
    except Exception:
        pass
    return True


def _build_round_tickets() -> List[str]:
    """Fresh tickets list for one scheduling round.

    Each eligible character contributes ``importance`` tickets (1/2/3).
    The list is shuffled so order within a round varies, but the count
    guarantees High runs 3x as often as Low across rounds.
    """
    try:
        from app.models.character import (
            list_available_characters, get_character_config)
    except Exception as e:
        logger.error("AgentLoop: cannot list characters: %s", e)
        return []

    tickets: List[str] = []
    for name in list_available_characters():
        if not _is_agent_eligible(name):
            continue
        try:
            cfg = get_character_config(name)
            raw = cfg.get("importance", 1)
            try:
                weight = int(raw)
            except (TypeError, ValueError):
                weight = 1
            weight = max(_MIN_IMPORTANCE, min(_MAX_IMPORTANCE, weight))
        except Exception:
            weight = 1
        tickets.extend([name] * weight)

    random.shuffle(tickets)
    return tickets


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_agent_loop: Optional[AgentLoop] = None


def get_agent_loop() -> AgentLoop:
    global _agent_loop
    if _agent_loop is None:
        _agent_loop = AgentLoop()
    return _agent_loop
