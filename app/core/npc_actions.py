"""The action tick for temporary NPCs (plan-npc-leben § 0 B).

A temporary NPC is placed once and would otherwise stand in that one room for
its whole life. This module gives it a cheap heartbeat: every so often a few
of them get ONE small JSON turn that answers two questions — which room of
their OWN location they are in now, and what they are doing there.

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
  a room of the location the NPC already stands in.

The answer is applied through ``force_set_status``, which is what makes this
module short: the room change publishes the state event, writes the state
history and the movement trace, and the activity goes through the pose
catalog — perception, events and the 3D client's ``room_id`` all follow from
that setter, not from anything here.
"""
import json
import re
from typing import Any, Callable, Dict, List, Optional

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


def candidates() -> List[str]:
    """The NPCs that get an action turn in THIS check, at most ``action_batch``.

    Living temporary NPCs (``list_temporary_npcs`` is living-only, so a pooled
    NPC waiting for its assets is already out), standing somewhere, awake, not
    mid-interaction, cooldown elapsed.
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
            if not (get_character_current_location(name) or ""):
                continue
            profile = get_character_profile(name) or {}
            if profile.get("is_sleeping"):
                continue
            if _is_busy(name, profile):
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
    cannot be asked at all (no location, or a location without rooms).

    Public because the smoke renders the template with exactly this set — a
    placeholder the module forgets is a StrictUndefined crash in production.
    """
    from app.models.character import (get_character_current_location,
                                      get_character_current_room,
                                      get_character_profile,
                                      get_effective_activity)
    from app.models.world import (get_location_by_id, get_location_name,
                                  get_room_activity_hint, get_room_name)

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
                      "hint": get_room_activity_hint(location_id, room_id)})
    if not rooms:
        return {}

    profile = get_character_profile(name) or {}
    current_room = get_character_current_room(name) or ""
    return {
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
    answer back and is asked for valid JSON). ``None`` after that."""
    response = llm(task=TASK, system_prompt=system_prompt,
                   user_prompt=user_prompt, agent_name=name,
                   label=f"NPC action ({name})")
    raw = str(getattr(response, "content", "") or "")
    obj = _parse_json(raw)
    if obj is not None:
        return obj
    logger.info("npc_action(%s): unparsable answer, one repair attempt", name)
    repair = (f"{raw[:2000]}\n\n"
              "That was not valid JSON. Return the SAME content as a single "
              "valid JSON object — no markdown, no code fence, no explanation.")
    response = llm(task=TASK, system_prompt=system_prompt, user_prompt=repair,
                   agent_name=name, label=f"NPC action ({name}, repair)")
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


def run_action_for(name: str, *,
                   llm: Optional[Callable[..., Any]] = None
                   ) -> Optional[Dict[str, Any]]:
    """Give ONE NPC its action turn and apply the answer.

    Returns what was written (``name``/``room``/``activity``/``moved``), or
    ``None`` when the answer was unusable — unparsable twice, a room the
    location does not have, or a move the block rules deny. An unusable answer
    writes NOTHING, the activity included: it was composed for a room that
    does not exist or cannot be entered, so it describes nothing.

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
        from app.models.character import get_character_current_location
        from app.models.rules import check_access
        location_id = get_character_current_location(name) or ""
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
                logger.debug("npc_action(%s) failed: %s", name, e)
        if acted:
            logger.info("npc_actions: %d NPC(s) acted", acted)
    except Exception as e:  # noqa: BLE001
        logger.debug("npc_actions sub error: %s", e)
