"""Director scenes for temporary NPCs (spec-npc-conversation § 4).

Mode ``scene`` of ``npc.conversation_mode``: instead of one NPC opening a
conversation and the others answering turn by turn, ONE small JSON call per
room writes the whole short exchange — two to four lines, optionally a pair
pose (an invitation, answered at once by a temporary NPC and walked over if
needed) and new activities. The lines land in the perception stream like spoken
lines (an avatar in the room reads them, a character present may chime in),
but the participants themselves get NO cascade: they have already said their
part, and a respond turn on top would be the expensive path this mode exists
to avoid.

Rooms only. An NPC out in a home area keeps the action tick's opener
(``npc_actions.talk_allowed``) — a hearing circle has no walls to group by.

Cost model, like the action tick: the sub-task LOOKS every 60 s, the real
rhythm is a per-room GAME cooldown (``npc.scene_interval_game_minutes``),
stamped BEFORE the call so a babbling model buys quiet, not retries; at most
``npc.scene_batch`` rooms per check.
"""
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.game_time import GameDuration, GameTime
from app.core.log import get_logger
from app.core.timeutils import game_time, utc_now_iso

logger = get_logger("npc_scenes")

TASK = "npc_scene"

_last_scene: Dict[str, GameTime] = {}

_DEFAULT_INTERVAL_MIN = 45
_DEFAULT_BATCH = 1
_DEFAULT_MAX_NPCS = 3
_MAX_LINES = 4
_MAX_LINE_CHARS = 300
_MAX_ANSWER_TOKENS = 600
_RECENT_LINES = 6
_RECENT_FETCH = 24


def _cfg_int(key: str, default: int, lo: int) -> int:
    from app.core import config
    try:
        return max(lo, int(config.get(f"npc.{key}", default)))
    except (TypeError, ValueError):
        return default


def _interval() -> GameDuration:
    return GameDuration.of(minutes=_cfg_int("scene_interval_game_minutes",
                                            _DEFAULT_INTERVAL_MIN, 1))


def _room_key(location_id: str, room_id: str) -> str:
    return f"{location_id}/{room_id}"


def _free(name: str) -> bool:
    """A living, placed, awake NPC that is not walking, pairing, chatting
    with an avatar or bound to a party — the ones a scene may script."""
    from app.core import npc_actions
    from app.models.character import (get_character_profile,
                                      get_character_status,
                                      is_character_sleeping)
    if get_character_status(name):
        return False
    profile = get_character_profile(name) or {}
    if is_character_sleeping(name) or profile.get("journey"):
        return False
    if npc_actions._is_busy(name, profile) or npc_actions._in_chat(name):
        return False
    if npc_actions._in_party(name):
        return False
    return True


def candidate_rooms() -> List[Tuple[str, str, List[str]]]:
    """``(location_id, room_id, participants)`` for the rooms that get a
    scene in THIS check: mode ``scene``, an avatar at the location, at least
    two free temporary NPCs in the room, cooldown elapsed; deterministic
    order (by key), at most ``scene_batch`` rooms, the first
    ``scene_max_npcs`` NPCs of each.
    """
    from app.core import npc_actions
    from app.models.character import (get_character_current_location,
                                      get_character_current_room,
                                      list_temporary_npcs)
    if npc_actions.conversation_mode() != "scene":
        return []
    groups: Dict[Tuple[str, str], List[str]] = {}
    for name in list_temporary_npcs():
        try:
            loc = get_character_current_location(name) or ""
            room = get_character_current_room(name) or ""
            if not loc or not room or not _free(name):
                continue
            groups.setdefault((loc, room), []).append(name)
        except Exception as e:  # noqa: BLE001
            logger.debug("scene candidate check for %s failed: %s", name, e)
    now = game_time()
    interval = _interval()
    batch = _cfg_int("scene_batch", _DEFAULT_BATCH, 1)
    max_npcs = _cfg_int("scene_max_npcs", _DEFAULT_MAX_NPCS, 2)
    out: List[Tuple[str, str, List[str]]] = []
    for (loc, room), names in sorted(groups.items()):
        if len(out) >= batch:
            break
        if len(names) < 2:
            continue
        _room = _room_key(loc, room)
        last = _last_scene.get(_room)
        if last is not None:
            _delta = now - last
            if _delta < GameDuration.ZERO:
                # Game clock set backwards -> re-anchor to now instead of
                # standing still until the clock has caught up again
                # (same treatment as random_events.check_and_generate).
                _last_scene[_room] = now
                continue
            if _delta < interval:
                continue
        if not npc_actions.avatar_at_place(names[0]):
            continue
        out.append((loc, room, sorted(names)[:max_npcs]))
    return out


def prompt_vars(location_id: str, room_id: str,
                names: List[str]) -> Dict[str, Any]:
    """Every variable ``tasks/npc_scene.md`` needs."""
    from app.core import npc_actions
    from app.core.perception import STORYTELLER_SPEAKER
    from app.models import perception_store
    from app.models.character import get_character_profile, get_effective_activity
    from app.models.world import (get_location_name, get_room_activity_hint,
                                  get_room_name)
    participants = []
    for name in names:
        p = get_character_profile(name) or {}
        participants.append({
            "name": name,
            "role": str(p.get("npc_slot_role") or "").strip(),
            "standing_task": str(p.get("standing_task") or "").strip(),
            "dialogue_style": str(p.get("dialogue_style") or "").strip(),
            "arrival_reason": str(p.get("arrival_reason") or "").strip(),
            "goals": str(p.get("npc_goals") or "").strip(),
            "activity": get_effective_activity(name) or "",
        })
    # The last SPOKEN lines: the storyteller's movement traces (every room
    # change writes one) would crowd out the conversation within a few
    # comings and goings, so they are skipped and the window is measured
    # over what is left.
    spoken = [row for row in perception_store.get_room_utterances(
                  location_id, room_id, limit=_RECENT_FETCH)
              if (row.get("meta") or {}).get("source") != "movement"]
    recent = []
    for row in spoken[-_RECENT_LINES:]:
        speaker = row.get("speaker") or ""
        label = "Narrator" if speaker == STORYTELLER_SPEAKER else speaker
        recent.append({"speaker": label, "line": row.get("content") or ""})
    return {
        "location_name": get_location_name(location_id) or location_id,
        "room_name": get_room_name(location_id, room_id) or room_id,
        "room_hint": get_room_activity_hint(location_id, room_id) or "",
        "game_time_label": game_time().label(),
        "participants": participants,
        "recent": recent,
        "pair_keys": npc_actions._pair_pose_keys(),
    }


def _apply(location_id: str, room_id: str, names: List[str],
           answer: Dict[str, Any], pair_keys: List[str]) -> Optional[Dict[str, Any]]:
    """Writes what survived validation: the lines of known speakers (one
    shared system stamp for the whole exchange, the ids keep the answer
    order), the activities, the pair as an invitation the partner's hook
    answers; then ONE cascade for the last line with every participant
    excluded."""
    from app.core import npc_actions
    from app.core.perception import record_utterance
    from app.models.character import force_set_status
    by_fold = {n.casefold(): n for n in names}
    lines: List[Tuple[str, str]] = []
    raw_lines = answer.get("lines")
    if not isinstance(raw_lines, list):
        raw_lines = []
    for item in raw_lines[: _MAX_LINES * 2]:
        if not isinstance(item, dict):
            continue
        speaker = by_fold.get(str(item.get("speaker") or "").strip().casefold(), "")
        line = str(item.get("line") or "").strip()[:_MAX_LINE_CHARS]
        if speaker and line:
            lines.append((speaker, line))
        if len(lines) >= _MAX_LINES:
            break
    if not lines:
        logger.info("npc_scene(%s/%s): no usable line — nothing written",
                    location_id, room_id)
        return None
    # ONE stamp for the whole exchange: the store orders by ts, then id, so
    # the ids keep the answer order and no line is dated into the future.
    stamp = utc_now_iso()
    for speaker, line in lines:
        others = [n for n in names if n != speaker]
        record_utterance(speaker=speaker, content=line, volume="normal",
                         addressees=others if len(names) == 2 else [],
                         location_id=location_id, room_id=room_id,
                         source="npc_scene", ts=stamp)
    written = 0
    acts = answer.get("activities")
    if isinstance(acts, dict):
        for who, sentence in acts.items():
            name = by_fold.get(str(who or "").strip().casefold(), "")
            text = npc_actions.strip_subject(str(sentence or ""), name)[:200] if name else ""
            if name and text and force_set_status(name, activity=text):
                written += 1
    paired = False
    pair = answer.get("pair")
    if isinstance(pair, dict):
        a = by_fold.get(str(pair.get("a") or "").strip().casefold(), "")
        b = by_fold.get(str(pair.get("b") or "").strip().casefold(), "")
        pose = npc_actions._pose_from_answer({"pose": pair.get("pose")}, pair_keys)
        if a and b and a != b and pose:
            # An invitation, not a direct start: two free NPCs in a room are
            # usually farther apart than MAX_START_DISTANCE_M, and the
            # invite path (a temporary NPC accepts at once, resolve_invite
            # walks the partner over) is what bridges that.
            try:
                from app.core.interaction_engine import create_invite
                paired = bool(create_invite(a, b, pose))
            except Exception as e:  # noqa: BLE001
                logger.info("npc_scene(%s/%s): pair %s/%s not invited: %s",
                            location_id, room_id, a, b, e)
    try:
        from app.core.agent_loop import get_agent_loop
        last_speaker, last_line = lines[-1]
        loop = get_agent_loop()
        loop.reset_room_energy(location_id, room_id, last_speaker)
        loop.dispatch_room_reactions(speaker=last_speaker, content=last_line,
                                     volume="normal", location_id=location_id,
                                     room_id=room_id, addressees=[],
                                     is_avatar=False, exclude=list(names))
    except Exception as e:  # noqa: BLE001
        logger.warning("npc_scene(%s/%s): cascade failed: %s", location_id, room_id, e)
    logger.info("npc_scene(%s/%s): %d line(s) by %s", location_id, room_id,
                len(lines), ", ".join(names))
    return {"lines": len(lines), "activities": written, "pair": paired}


def run_scene_for(location_id: str, room_id: str, names: List[str], *,
                  llm: Optional[Callable[..., Any]] = None
                  ) -> Optional[Dict[str, Any]]:
    """One director call for one room; applies the answer. ``None`` when the
    answer was unusable (twice unparsable, or no line by a participant). The
    cooldown is stamped BEFORE the call."""
    from app.core import npc_actions
    from app.core.prompt_templates import render_task
    if llm is None:
        from app.core.llm_router import llm_call
        llm = llm_call
    _last_scene[_room_key(location_id, room_id)] = game_time()
    variables = prompt_vars(location_id, room_id, names)
    system_prompt, user_prompt = render_task(TASK, **variables)
    # agent_name="": the scene belongs to the ROOM, not to participant 0 — a
    # per-character model override must not decide how the room talks. The
    # label names the room instead, so the LLM log says which one it was.
    answer = npc_actions._ask(llm, "", system_prompt, user_prompt, task=TASK,
                              label=f"NPC scene {location_id}/{room_id}",
                              max_tokens=_MAX_ANSWER_TOKENS)
    if answer is None:
        logger.info("npc_scene(%s/%s): no usable answer", location_id, room_id)
        return None
    return _apply(location_id, room_id, names, answer, variables["pair_keys"])


def _sub_npc_scenes() -> None:
    """World-Admin-Tick sub-task: one director scene per due room."""
    try:
        done = 0
        for loc, room, names in candidate_rooms():
            try:
                if run_scene_for(loc, room, names):
                    done += 1
            except Exception as e:  # noqa: BLE001
                logger.warning("npc_scene(%s/%s) failed: %s", loc, room, e)
        if done:
            logger.info("npc_scenes: %d scene(s) written", done)
    except Exception as e:  # noqa: BLE001
        # Not debug: a candidate scan that breaks makes scene mode silently
        # inert — the same reasoning as in `_sub_npc_actions`.
        logger.warning("npc_scenes sub error: %s", e)
