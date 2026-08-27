"""The action tick for temporary NPCs (plan-npc-leben § 0 B).

A temporary NPC is placed once and would otherwise stand in that one spot for
its whole life. This module gives it a cheap heartbeat: every so often a few
of them get ONE small JSON turn about what happens next.

THERE ARE TWO VARIANTS OF THAT TURN, and the NPC's own placement decides
which one it gets (spec-npc-heimat-zeitfenster § E3):

* **In a house** — the ordinary case. The turn answers two questions: which
  room of its OWN location the NPC is in now, and what it is doing there.
  Applied through ``force_set_status``.
* **In a home area** — an NPC placed by a slot with a ``radius_m`` carries
  ``npc_home`` and stands at a free metre point, usually outside every
  location. There is no room to pick, so the turn answers ONE question: what
  it is doing. The MOVEMENT is not asked at all — the tick draws the next
  point of the home area itself (``npc_home.random_point``) and starts an
  ordinary point journey to it. Asking a model for coordinates would only
  invite hallucinated ones.

Three properties make it cheap enough to run forever:

* **The clock is the GAME clock.** The sub-task is checked every 60 s, but
  what actually gates a turn is a per-NPC cooldown of
  ``npc.action_interval_game_minutes`` GAME minutes. A frozen world freezes
  the cooldowns with everything else (the tick loop is paused then anyway),
  and a fast game clock buys a livelier place without a config change.
  The stamps live in a module dict — losing them on a restart only means
  every NPC gets one turn early, which is harmless.
* **The batch caps the cost.** At most ``npc.action_batch`` NPCs per check,
  so the worst case per minute is a known number of small turns.
* **Nothing crosses a location border.** Wandering between places is the
  wanderer tick's job (``npc_spawn.wanderer_tick``); this one only ever picks
  a room of the location the NPC already stands in — or a point of the home
  area the NPC was placed in, which is bounded by its own radius.

The answer is applied through ``force_set_status``, which is what makes this
module short: the room change publishes the state event, writes the state
history and the movement trace, and the activity goes through the pose
catalog — perception, events and the 3D client's ``room_id`` all follow from
that setter, not from anything here.
"""
import json
import re
from typing import Any, Callable, Dict, List, Optional

from app.core import places
from app.core.game_time import GameDuration, GameTime
from app.core.log import get_logger
from app.core.timeutils import game_time

logger = get_logger("npc_actions")

TASK = "npc_action"

# Per-NPC cooldown stamps: name -> GAME time of its last action turn.
_last_action: Dict[str, GameTime] = {}

# Defaults mirror config_schema's `npc` section — a world whose config predates
# the section still ticks at the documented rate.
_DEFAULT_INTERVAL_MIN = 30
_DEFAULT_BATCH = 2

# The longest activity sentence we accept. `set_pose_intent` cuts the flavor
# to 120 chars anyway; this only keeps a runaway answer out of the write.
_MAX_ACTIVITY_CHARS = 200

# Completion budget of one turn. The answer is two short fields (a room id and
# one sentence) — roughly 40 tokens — so this is a generous cap and still an
# upper bound on what a babbling model can cost per NPC per interval.
_MAX_ANSWER_TOKENS = 200

_JSON_OBJ_RE = re.compile(r"\{.*\}", re.S)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _enabled() -> bool:
    from app.core import config
    return bool(config.get("npc.action_tick_enabled", True))


def _interval() -> GameDuration:
    from app.core import config
    try:
        minutes = int(config.get("npc.action_interval_game_minutes",
                                 _DEFAULT_INTERVAL_MIN))
    except (TypeError, ValueError):
        minutes = _DEFAULT_INTERVAL_MIN
    return GameDuration.of(minutes=max(1, minutes))


def _batch() -> int:
    from app.core import config
    try:
        return max(1, int(config.get("npc.action_batch", _DEFAULT_BATCH)))
    except (TypeError, ValueError):
        return _DEFAULT_BATCH


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------

def _is_busy(name: str, profile: Dict[str, Any]) -> bool:
    """True while the NPC is tied up in a running pair interaction.

    ``interaction_engine.get_interaction`` is the one existing predicate for
    "currently interacting" — a validated interaction record on the profile.
    Moving such an NPC would tear its partner out of a clip that is still
    playing (``set_pose_intent`` ends the interaction for BOTH of them), so
    the tick simply waits for the next round.
    """
    try:
        from app.core.interaction_engine import get_interaction
        return get_interaction(name, profile) is not None
    except Exception as e:  # noqa: BLE001 — a broken record is not a reason to move
        logger.debug("interaction check for %s failed: %s", name, e)
        return True


def _in_chat(name: str) -> bool:
    """True while an avatar is talking to this NPC right now.

    THE SAME RULE the AgentLoop gates its own turns on, not a second
    definition of "in chat": ``_minutes_since_last_chat_with_avatar`` against
    its HOT window (``_IN_CHAT_HOT_MIN``). Every temporary NPC carries
    ``talk_to``, so without this the tick could walk the innkeeper down to
    the cellar and overwrite her activity while the player is still writing
    to her.

    The import is lazy because everything in this module is: ``agent_loop``
    pulls in the perception layer at module load, and this module is reached
    from the world tick.

    An unreadable answer counts as "not in chat" — that is what the helper
    itself does with a broken row (it returns None), and a chat check that
    cannot be made must not silence the whole tick.
    """
    try:
        from app.core.agent_loop import (_IN_CHAT_HOT_MIN,
                                         _minutes_since_last_chat_with_avatar)
        minutes = _minutes_since_last_chat_with_avatar(name)
        return minutes is not None and minutes < _IN_CHAT_HOT_MIN
    except Exception as e:  # noqa: BLE001
        logger.debug("in-chat check for %s failed: %s", name, e)
        return False


def _in_party(name: str) -> bool:
    """True while a party makes this NPC's roaming turn a bad idea — EITHER role.

    A FOLLOWER has lost SetLocation and Move, and the party engine cancels its
    journey at the join: the leader's move is what carries it. So a roaming
    turn for a follower can only produce a journey somebody else deletes —
    and, until it is deleted, one walking away from the party it just joined.

    A LEADER is the other half of the same problem. Followers are dragged
    along by a LOCATION change only; a roaming journey to a free point inside
    the home area moves the leader and nobody else, so the party would be
    stranded at the place it set out from while its leader wanders the wood.
    """
    try:
        from app.core.party_engine import is_party_follower, is_party_leader
        return is_party_follower(name) or is_party_leader(name)
    except Exception as e:  # noqa: BLE001 — a broken party row is not a bar
        logger.debug("party check for %s failed: %s", name, e)
        return False


def candidates() -> List[str]:
    """The NPCs that get an action turn in THIS check, at most ``action_batch``.

    Living temporary NPCs (``list_temporary_npcs`` is living-only, so a pooled
    NPC waiting for its assets is already out), standing somewhere OR carrying
    a home area, awake, not mid-interaction, not mid-conversation with an
    avatar, cooldown elapsed.
    """
    if not _enabled():
        return []
    from app.models.character import (get_character_current_location,
                                      get_character_profile,
                                      get_character_status,
                                      list_temporary_npcs)

    now = game_time()
    interval = _interval()
    batch = _batch()
    picked: List[str] = []
    for name in list_temporary_npcs():
        if len(picked) >= batch:
            break
        try:
            if get_character_status(name):
                continue          # pooled or otherwise not in the world
            last = _last_action.get(name)
            if last is not None and (now - last) < interval:
                continue
            profile = get_character_profile(name) or {}
            home = profile.get("npc_home")
            if not (get_character_current_location(name) or "") and not home:
                # NOWHERE AT ALL. An NPC with a home area is allowed to stand
                # out in the open (that is the point of it); one without is
                # simply not in the world.
                continue
            if profile.get("is_sleeping"):
                continue
            if profile.get("journey"):
                # ON THE ROAD. During a journey `current_location` is whatever
                # transit cell the travel ticker last wrote, so this NPC would
                # be asked to pick a room of a place it is only passing
                # through — and the write would land on a character the ticker
                # is still moving. Same guard the wanderer tick uses
                # (`npc_spawn._settle_wanderer`: "still walking = nothing to
                # do"); arriving makes it a candidate again.
                continue
            if home and _in_party(name):
                continue
            if _is_busy(name, profile):
                continue
            if _in_chat(name):
                continue
        except Exception as e:  # noqa: BLE001
            logger.debug("candidate check for %s failed: %s", name, e)
            continue
        picked.append(name)
    return picked


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def prompt_vars(name: str) -> Dict[str, Any]:
    """Every variable ``tasks/npc_action.md`` needs, or ``{}`` when this NPC
    cannot be asked at all (no home area AND no location, or a location
    without rooms).

    Public because the smoke renders the template with exactly this set — a
    placeholder the module forgets is a StrictUndefined crash in production.

    BOTH variants always fill the SAME key set, the unused half empty:
    ``home`` is the switch the template branches on, and a key that exists in
    only one branch is a crash waiting for the other one.

    ``location_id`` rides along as bookkeeping the template ignores: it is the
    place the room list was taken from, and :func:`run_action_for` compares it
    against the character's location again before it writes anything. The home
    variant leaves it empty — a roaming NPC has no room to invalidate.
    """
    from app.models.character import (get_character_current_location,
                                      get_character_current_room,
                                      get_character_profile,
                                      get_effective_activity)
    from app.models.world import (get_location_by_id, get_location_name,
                                  get_room_activity_hint, get_room_name)

    profile = get_character_profile(name) or {}
    home = profile.get("npc_home")
    if isinstance(home, dict) and home:
        from app.core.npc_home import describe
        label = describe(home)
        if label:
            return {
                "location_id": "",
                "npc_name": name,
                "npc_role": str(profile.get("npc_slot_role") or "").strip(),
                "standing_task": str(profile.get("standing_task") or "").strip(),
                "location_name": "",
                "current_room_id": "",
                "current_room_name": "",
                "current_activity": get_effective_activity(name),
                "game_time_label": game_time().label(),
                "rooms": [],
                "home": label,
            }
        logger.warning("npc_action(%s): unreadable npc_home %r — asked as an "
                       "ordinary room NPC", name, home)

    location_id = get_character_current_location(name) or ""
    if not location_id:
        return {}
    location = get_location_by_id(location_id) or {}
    rooms = []
    for room in (location.get("rooms") or []):
        room_id = str((room or {}).get("id") or "").strip()
        if not room_id:
            continue
        rooms.append({"id": room_id,
                      "name": get_room_name(location_id, room_id),
                      "hint": get_room_activity_hint(location_id, room_id),
                      "places": places.room_offer_short(location_id, room_id)})
    if not rooms:
        return {}

    current_room = get_character_current_room(name) or ""
    return {
        "location_id": location_id,
        "npc_name": name,
        "npc_role": str(profile.get("npc_slot_role") or "").strip(),
        "standing_task": str(profile.get("standing_task") or "").strip(),
        "location_name": get_location_name(location_id) or location_id,
        "current_room_id": current_room,
        "current_room_name": (get_room_name(location_id, current_room)
                              if current_room else ""),
        "current_activity": get_effective_activity(name),
        "game_time_label": game_time().label(),
        "rooms": rooms,
        "home": "",
    }


# ---------------------------------------------------------------------------
# LLM turn
# ---------------------------------------------------------------------------

def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
    """The one JSON object in the answer; code fences and stray prose around
    it are tolerated, anything else is a parse failure."""
    match = _JSON_OBJ_RE.search((raw or "").strip())
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _ask(llm: Callable[..., Any], name: str, system_prompt: str,
         user_prompt: str) -> Optional[Dict[str, Any]]:
    """One turn plus EXACTLY one repair attempt (the model gets its own broken
    answer back and is asked for valid JSON). ``None`` after that.

    Both turns are capped at ``_MAX_ANSWER_TOKENS``: the answer is two short
    fields, and an uncapped budget is what lets a chatty model write an essay
    per NPC per interval (feedback_validate_llm_guards).
    """
    response = llm(task=TASK, system_prompt=system_prompt,
                   user_prompt=user_prompt, agent_name=name,
                   label=f"NPC action ({name})",
                   max_tokens=_MAX_ANSWER_TOKENS)
    raw = str(getattr(response, "content", "") or "")
    obj = _parse_json(raw)
    if obj is not None:
        return obj
    logger.info("npc_action(%s): unparsable answer, one repair attempt", name)
    repair = (f"{raw[:2000]}\n\n"
              "That was not valid JSON. Return the SAME content as a single "
              "valid JSON object — no markdown, no code fence, no explanation.")
    response = llm(task=TASK, system_prompt=system_prompt, user_prompt=repair,
                   agent_name=name, label=f"NPC action ({name}, repair)",
                   max_tokens=_MAX_ANSWER_TOKENS)
    return _parse_json(str(getattr(response, "content", "") or ""))


def _resolve_room(raw: Any, rooms: List[Dict[str, Any]]) -> str:
    """The room id the answer means, or ``""``.

    Exact match first, then case-insensitive — a model that shouts an id back
    has not hallucinated one. A room the location does not have is never
    guessed at: the answer is discarded whole by the caller.
    """
    wanted = str(raw or "").strip()
    if not wanted:
        return ""
    ids = [r["id"] for r in rooms]
    if wanted in ids:
        return wanted
    folded = wanted.casefold()
    for room_id in ids:
        if room_id.casefold() == folded:
            return room_id
    return ""


def _apply_home_answer(name: str,
                       answer: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Apply the ROAMING variant's answer: the activity, then a walk.

    The answer carries one field. The destination is drawn here, not asked:
    ``npc_home.random_point`` knows the shape, the painted terrain and the
    neighbouring places, and a model asked for coordinates would invent them.

    THE ACTIVITY IS WRITTEN FIRST. ``set_pose_intent`` ends a running pair
    interaction, and it must not do that to a journey this function has just
    started; the other way round there is nothing to lose — the sentence
    describes what the NPC does on its way, and a walk that cannot start
    leaves an NPC that at least does something new where it stands.

    ``None`` when the answer names no activity at all: it is the only field,
    so an empty one is an unusable answer, not a silent walk.
    """
    from app.core.npc_home import random_point
    from app.core.travel_engine import start_journey_to_point
    from app.models.character import (force_set_status, get_character_pos,
                                      get_character_profile)

    activity = str(answer.get("activity") or "").strip()[:_MAX_ACTIVITY_CHARS]
    if not activity:
        logger.info("npc_action(%s): the roaming answer names no activity — "
                    "discarded", name)
        return None
    profile = get_character_profile(name) or {}
    home = profile.get("npc_home") or {}
    if not force_set_status(name, activity=activity):
        return None

    pos = get_character_pos(name)
    here = (pos["x"], pos["z"]) if pos else None
    point = random_point(home, min_dist_from=here)
    moved = False
    if point is None:
        logger.info("npc_action(%s): nowhere to walk in its home area right "
                    "now — it stays where it is", name)
    else:
        _journey, reason = start_journey_to_point(name, point[0], point[1])
        moved = reason == "ok"
        if not moved:
            logger.info("npc_action(%s): cannot walk to %s (%s)", name, point,
                        reason)
    logger.debug("npc_action(%s): %s%s", name, "roams " if moved else "",
                 activity)
    return {"name": name, "room": "", "activity": activity, "moved": moved}


def run_action_for(name: str, *,
                   llm: Optional[Callable[..., Any]] = None
                   ) -> Optional[Dict[str, Any]]:
    """Give ONE NPC its action turn and apply the answer.

    Returns what was written (``name``/``room``/``activity``/``moved``), or
    ``None`` when the answer was unusable — unparsable twice, a room the
    location does not have, or a move the block rules deny. An unusable answer
    writes NOTHING, the activity included: it was composed for a room that
    does not exist or cannot be entered, so it describes nothing.

    An NPC with a home area takes the roaming branch instead
    (:func:`_apply_home_answer`): one field, no room, and the walk is drawn
    rather than asked.

    ``llm`` is injectable for the smoke; it has ``llm_call``'s call shape.
    """
    if llm is None:
        from app.core.llm_router import llm_call
        llm = llm_call

    variables = prompt_vars(name)
    if not variables:
        logger.debug("npc_action(%s): nowhere to act", name)
        return None

    # The turn is spent from here on: the cooldown is stamped BEFORE the call,
    # so a model that errors or babbles costs one interval of quiet instead of
    # a retry on every single check.
    _last_action[name] = game_time()

    from app.core.prompt_templates import render_task
    system_prompt, user_prompt = render_task(TASK, **variables)
    answer = _ask(llm, name, system_prompt, user_prompt)
    if answer is None:
        logger.info("npc_action(%s): no usable answer", name)
        return None

    if variables["home"]:
        # THE ROAMING VARIANT. No room to validate and no location to compare:
        # this NPC's place is its home area, and that cannot change during a
        # turn (only pooling clears it, and a pooled NPC is no candidate).
        return _apply_home_answer(name, answer)

    # THE PLACE MUST STILL BE THE PLACE. A turn takes seconds and the world
    # keeps running through it — a journey settling, an admin move, a party
    # pulling the NPC along. The room list came from ONE location; writing an
    # id from it into a location that does not have that room would leave an
    # invalid `room_id` behind for perception and the 3D client. The next tick
    # asks again, with the new place's rooms.
    from app.models.character import get_character_current_location
    location_id = variables["location_id"]
    location_now = get_character_current_location(name) or ""
    if location_now != location_id:
        logger.info("npc_action(%s): moved from %s to %s during the turn — "
                    "answer discarded", name, location_id, location_now)
        return None

    rooms = variables["rooms"]
    room = _resolve_room(answer.get("room"), rooms)
    if not room:
        logger.info("npc_action(%s): answer names room %r, which this place "
                    "does not have — discarded", name, answer.get("room"))
        return None

    activity = str(answer.get("activity") or "").strip()[:_MAX_ACTIVITY_CHARS]
    current_room = variables["current_room_id"]
    moved = room != current_room

    if moved:
        from app.models.rules import check_access
        allowed, reason = check_access(name, location_id, room_id=room)
        if not allowed:
            logger.info("npc_action(%s): move to %s blocked (%s)",
                        name, room, reason)
            return None

    from app.models.character import force_set_status
    written = force_set_status(name, room=room if moved else None,
                               activity=activity or None)
    if not written:
        return None
    logger.debug("npc_action(%s): %s%s", name,
                 f"-> {room} " if moved else "", activity)
    return {"name": name, "room": room, "activity": activity, "moved": moved}


# ---------------------------------------------------------------------------
# The sub-task
# ---------------------------------------------------------------------------

def _sub_npc_actions() -> None:
    """World-Admin-Tick sub-task: give the due NPCs their action turn.

    The 60 s in ``_SUB_TASKS`` are only how often this LOOKS; the real rhythm
    is the per-NPC GAME cooldown checked in :func:`candidates`.
    """
    try:
        acted = 0
        for name in candidates():
            try:
                if run_action_for(name):
                    acted += 1
            except Exception as e:  # noqa: BLE001 — one NPC must not stop the rest
                # WARNING, not debug: a provider that is down or a template
                # that no longer renders makes every NPC stand still, and at
                # debug level the world just looks lifeless for no reason.
                logger.warning("npc_action(%s) failed: %s", name, e)
        if acted:
            logger.info("npc_actions: %d NPC(s) acted", acted)
    except Exception as e:  # noqa: BLE001
        logger.debug("npc_actions sub error: %s", e)
