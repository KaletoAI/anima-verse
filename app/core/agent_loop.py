"""Continuous AgentLoop — replaces the old probabilistic ThoughtRunner tick.

Picks the next agent via weighted round-robin (importance 1=Low, 2=Medium,
3=High → 1/2/3 tickets per agent, reshuffled each round). Runs one thought
turn at a time (LLM/GPU is the bottleneck). Sleeping characters and the
user-controlled avatar are excluded.

Chat-response bumps (``bump_respond``) do NOT go through the serial loop:
they live in their own respond lane — a dispatcher task spawns up to
``thoughts.max_parallel_responds`` concurrent respond turns (no global turn
lock, no min_turn_gap), so a conversation never waits behind unrelated
thought turns. Answers in the SAME room stay serialized via a per-room lock
(each answer must see the previous one in the perception stream); actual
LLM parallelism is still capped by the provider's max_concurrent
(plan-parallel-bump-lane.md).

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
import random
from datetime import datetime, timedelta

from app.core.timeutils import parse_iso, utc_now
from app.core.turn_trace import begin_trace, set_trace
from typing import Any, Dict, List, Optional

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
# Respond lane: how many bumped chat responses may run concurrently
# (thoughts.max_parallel_responds, read live).
_MAX_PARALLEL_RESPONDS_DEFAULT = 2


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


def _get_max_parallel_responds() -> int:
    """Read thoughts.max_parallel_responds from config (live), floor 1."""
    try:
        from app.core import config as _cfg
        return max(1, int(_cfg.get("thoughts.max_parallel_responds")
                          or _MAX_PARALLEL_RESPONDS_DEFAULT))
    except Exception:
        return _MAX_PARALLEL_RESPONDS_DEFAULT


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
        # _respond_queue (FIFO, obligatory-first) and runs up to
        # thoughts.max_parallel_responds concurrent respond turns. A
        # character never runs two turns at once (_respond_active is checked
        # by the round-robin too); answers in the same room serialize on a
        # per-room asyncio.Lock so each answer sees the previous one.
        self._respond_queue: List[str] = []
        self._respond_to: Dict[str, Dict[str, Any]] = {}
        self._respond_active: Dict[str, asyncio.Task] = {}
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
        - Remaining characters present → Chime opportunity (skippable) — only
          while the room energy is not exhausted (Backstop). Avatar input
          recharges it; every AI utterance consumes a hop (decay).
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
        from app.models.character import get_movement_target as _gmt
        def _leaving(c: str) -> bool:
            if not location_id:
                # Nobody is "walking out" of the open: everyone on the road
                # carries a travel target, so this filter would silence
                # exactly the chance encounters the wilderness branch exists
                # for. Out there you meet people who are on their way.
                return False
            tgt = _gmt(c)
            return bool(tgt and tgt != location_id)
        # Who is in earshot at all? The room decides inside a location, the
        # hearing radius outside — the ONE roster every step below reads.
        # The speaker is part of the room list and NOT of the radius list;
        # every consumer filters it out anyway.
        if location_id:
            in_earshot = _list_characters_in_room(location_id, room_id)
        else:
            from app.core.perception import nearby_in_the_open
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

        # 2) Chime opportunities for the remaining characters present (not on whisper)
        if volume != "whisper":
            for c in present:
                if c in addr:
                    continue
                if self.bump_respond(c, speaker=speaker, content=content,
                                     volume=volume, obligatory=False):
                    out["chime"].append(c)
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

    def _pop_next_respond(self) -> Optional[tuple]:
        """Pop the first queued respond whose character is not already
        running a turn. Re-checks eligibility at pop time (the character
        may have been taken over as avatar since the bump). Returns
        (name, payload) or None."""
        for name in list(self._respond_queue):
            if name in self._respond_active:
                continue  # never two turns for the same character at once
            self._respond_queue.remove(name)
            payload = self._respond_to.pop(name, None)
            if not payload:
                continue
            if not _is_respond_eligible(name):
                logger.debug("respond lane: %s became ineligible — dropped", name)
                continue
            return name, payload
        return None

    async def _respond_dispatcher(self) -> None:
        """Own asyncio task feeding the respond lane. Spawns respond turns
        as concurrent tasks up to thoughts.max_parallel_responds — no global
        turn lock, no min_turn_gap. Honors the shared pause switch (admin
        pause, world freeze, world sleep) and keeps the queue when the chat
        LLM is unreachable."""
        try:
            await asyncio.sleep(_BOOT_GRACE_SECONDS)
        except asyncio.CancelledError:
            return
        while not self._stop.is_set():
            try:
                if not self._respond_queue:
                    await asyncio.sleep(1)
                    continue
                if _is_paused():
                    await asyncio.sleep(_IDLE_SLEEP_SECONDS)
                    continue
                if len(self._respond_active) >= _get_max_parallel_responds():
                    await asyncio.sleep(0.5)
                    continue
                if not _chat_llm_available():
                    await asyncio.sleep(_IDLE_SLEEP_SECONDS)
                    continue
                nxt = self._pop_next_respond()
                if not nxt:
                    await asyncio.sleep(1)
                    continue
                name, payload = nxt
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

        # 2) Current round.
        while self._tickets:
            candidate = self._tickets.pop(0)
            if candidate in self._respond_active:
                continue  # mid-respond — never two turns at once
            if not _is_agent_eligible(candidate):
                continue
            if _on_cooldown(candidate):
                continue  # next ticket — skip this char
            if _in_chat_skip(candidate):
                continue  # char is actively chatting — no thought
            return candidate

        # 3) Refill round.
        self._tickets = _build_round_tickets()
        if not self._tickets:
            return None
        while self._tickets:
            candidate = self._tickets.pop(0)
            if candidate in self._respond_active:
                continue
            if not _is_agent_eligible(candidate):
                continue
            if _on_cooldown(candidate):
                continue
            if _in_chat_skip(candidate):
                continue
            return candidate
        return None

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
        try:
            from app.core import perception_shadow
            from app.core.chat_engine import run_chat_turn
            with perception_shadow.suppressed():
                reply = await _asyncio.to_thread(
                    run_chat_turn, "", character_name, speaker, content,
                    "in_person", "character_talk", True,  # post_process=True
                    room_stream=room_stream,
                    respond_opportunity=respond_opportunity,
                    hint=hint, winding_down=winding_down)
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
                                 source="loop")
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
        # Game time at turn end — same format as thoughts.game_ts (ISO with
        # world-tz offset); '' when the game clock is unavailable.
        try:
            from app.core.timeutils import game_local_now
            _game_ts = game_local_now().isoformat(timespec="seconds")
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


def _minutes_since_last_chat_with_avatar(character_name: str) -> Optional[float]:
    """Returns minutes since this character's last chat message **with an
    avatar (player-controlled character)**, or None if there is no such
    message.

    Used to gate AgentLoop turns: if a chat is active right now, the
    character should either skip or run a trimmed in-chat template instead
    of pursuing unrelated initiatives.

    Important: TalkTo NPC↔NPC messages do NOT count as "in-chat" — the skip
    should only apply to an active avatar↔char conversation. The function
    used to blindly take the latest chat_messages row, which locked a
    character out of thinking as soon as they talked to an NPC via TalkTo
    (0.5min ago = "in chat" → skip).

    Implementation: collect all current avatars (see
    ``account.get_all_avatars`` — multi-user, honours
    users.settings.active_character) and count only messages where the
    partner is an avatar.
    """
    try:
        from app.core.db import get_connection
        from app.models.account import get_all_avatars
        avatars = get_all_avatars() or set()
        # Drop the char itself (it is never its own avatar — and if it were,
        # the loop would already skip it as is_player_controlled)
        avatars = {a for a in avatars if a and a != character_name}
        if not avatars:
            return None
        # Latest message where character_name is in the chat AND the partner is
        # an avatar — cover both storage directions (A,B)/(B,A).
        placeholders = ",".join(["?"] * len(avatars))
        params = (
            list(avatars) + [character_name]   # condition 1: char=avatar AND partner=this
            + [character_name] + list(avatars) # condition 2: char=this AND partner=avatar
        )
        sql = (
            f"SELECT MAX(ts) FROM chat_messages WHERE "
            f"(character_name IN ({placeholders}) AND partner=?) "
            f"OR (character_name=? AND partner IN ({placeholders}))"
        )
        conn = get_connection()
        row = conn.execute(sql, params).fetchone()
        if not row or not row[0]:
            return None
        try:
            last = parse_iso(row[0])
        except (ValueError, TypeError):
            return None
        delta = utc_now() - last
        return delta.total_seconds() / 60.0
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
