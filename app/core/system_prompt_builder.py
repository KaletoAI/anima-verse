"""System prompt data loader (slim).

The original ``build_system_prompt`` + ``THOUGHT_FULL/REACTION`` template
composer has been removed — the AgentLoop builds its slim prompt via
``app/core/thought_context.py`` and ``chat/agent_thought.md`` instead.

This module now only provides:

- ``load_prompt_data(character_name, sections)`` — collects the heavy
  per-character context (personality, location, presence, events,
  memory, relationships, ...) as ready-to-render strings. Used by the
  rp_first dual-LLM tool-system context in ``thoughts.py``.

- ``build_recent_activity_section(...)`` — bullet list of what the
  character recently did, queried from ``state_history``. Used by the
  chat_stream prompt and the rp_first tool-system context.

- The ``IDENTITY / SITUATION / ...`` section sentinels are kept as
  string constants because callers pass them as a ``Set[str]`` to
  ``load_prompt_data`` to opt into specific data loads.
"""
from datetime import datetime

from app.core.timeutils import parse_iso, utc_now
from typing import Any, Dict, Set

from app.core.log import get_logger

logger = get_logger("system_prompt_builder")


# ============================================================================
# Section labels — used by load_prompt_data() to opt into data loads.
# ============================================================================
IDENTITY = "identity"
TASK = "task"
ASSIGNMENTS = "assignments"
PENDING = "pending"
SITUATION = "situation"
PRESENCE = "presence"
EVENTS = "events"
MEMORY = "memory"
ARCS = "arcs"
RELATIONSHIPS = "relationships"
RULES_PRESENCE = "rules_presence"
INTENT = "intent"
RESPONSE_RULES = "response_rules"
RECENT_ACTIVITY = "recent_activity"

# Convenience: load everything (used by the rp_first tool-system builder).
THOUGHT_FULL: Set[str] = {
    IDENTITY, TASK, ASSIGNMENTS, PENDING, SITUATION, PRESENCE,
    EVENTS, MEMORY, ARCS, RULES_PRESENCE, INTENT, RESPONSE_RULES,
    RECENT_ACTIVITY,
}


# ============================================================================
# Data loader (loads only what's needed for the requested sections)
# ============================================================================

def load_prompt_data(character_name: str, sections: Set[str]) -> Dict[str, Any]:
    from app.models.character import (
        get_character_profile,
        get_character_current_location)
    from app.models.world import get_location_name

    profile = get_character_profile(character_name)
    data: Dict[str, Any] = {}

    data["personality"] = (profile.get("character_personality", "") or "").strip()
    data["task"] = (profile.get("character_task", "") or "").strip()

    location_id = profile.get("current_location", "")
    data["location_id"] = location_id
    data["location_name"] = get_location_name(location_id) if location_id else "Unknown"
    # Prompt line "Activity": DISPLAY text, not a render key — the sanitized
    # flavor when the character has one, otherwise the bare catalog key. Both
    # are already cleaned and length-capped at the write path (pose_catalog.
    # sanitize_flavor), so nothing is trimmed here.
    data["activity"] = ("Sleeping" if profile.get("is_sleeping")
                        else (profile.get("pose_flavor")
                              or profile.get("pose_key") or "")) or "None"
    data["feeling"] = profile.get("current_feeling", "") or "Neutral"
    from app.core.timeutils import game_local_now as _lnow
    data["time_of_day"] = _lnow().strftime("%H:%M")  # in-game clock (world TZ)

    if PRESENCE in sections:
        presence_lines, elsewhere_lines, anyone_nearby = _load_presence(
            character_name, location_id)
        data["presence_lines"] = presence_lines
        data["anyone_nearby"] = anyone_nearby
        # Pre-rendered text block for callers that want a single string
        # (rp_first tool-system content in thoughts.py).
        # Rendered whenever the location is KNOWN — the alone case included.
        # It used to be dropped on empty presence_lines, which threw away the
        # "You are ALONE" sentence in exactly the situation it is written for.
        data["nearby_hint"] = _format_presence_block(
            data["location_name"], presence_lines, elsewhere_lines,
            anyone_nearby
        ) if location_id else ""

    if EVENTS in sections:
        data["events_section"] = _load_events(location_id)

    if MEMORY in sections:
        data["memory_section"] = _load_memory(character_name)

    if ARCS in sections:
        data["arc_context"] = _load_arcs(character_name)

    if ASSIGNMENTS in sections:
        data["assignment_section"] = _load_assignments(character_name)

    if PENDING in sections:
        data["pending_section"] = _load_pending(character_name)

    if RELATIONSHIPS in sections:
        data["relationships_section"] = _load_relationships(character_name)

    return data


def _format_presence_block(location_name: str, presence_lines: list,
                            elsewhere_lines: list,
                            anyone_nearby: bool) -> str:
    """Plain-text presence block (replaces former sections/presence.md).

    Room-scoped (2026-07-30): the block used to assert everyone at the
    LOCATION as present and invite TalkTo — which made NPCs stage physical
    scenes with people two rooms away who could never hear them. Now it
    lists the ROOM's people as present and everyone else at the location
    as explicitly out of reach.

    An omitted block reads as "no information" to an LLM, never as "nobody is
    here" — which is how absent people get pulled into a scene. So the empty
    case says so in words instead of staying silent."""
    parts = [f"In your room at '{location_name}':"]
    parts.extend(presence_lines or ["- nobody else, you are alone in this room"])
    if anyone_nearby:
        parts.append("You can talk to the people in your room (TalkTo).")
        parts.append(
            "IMPORTANT: ONLY the people listed for your room are with you. "
            "Do NOT invent further attendees.")
    else:
        parts.append(
            "NO other characters are in this room with you. "
            "Do NOT invent interactions with absent persons.")
    if elsewhere_lines:
        parts.append("Elsewhere at this location (NOT in your room — they "
                     "cannot see or hear you):")
        parts.extend(elsewhere_lines)
        parts.append(
            "To reach someone elsewhere at this location: go to them first "
            "(Move/SetLocation) or use SendMessage — TalkTo does NOT reach "
            "other rooms.")
    return "\n".join(parts)


def _load_presence(character_name: str, location_id: str) -> tuple:
    """Build ``(presence_lines, elsewhere_lines, anyone_in_room)`` for the
    active world. ``presence_lines`` = people in the character's ROOM,
    ``elsewhere_lines`` = people in OTHER rooms of this location. The
    location's ground is a room like any other (``world.GROUND_ROOM_ID``),
    so plain room equality decides both.
    Returns ([], [], False) when no location."""
    if not location_id:
        return [], [], False

    from app.models.character import (
        list_available_characters,
        get_character_current_location,
        get_character_current_room,
        get_character_language,
        get_effective_activity)
    from app.models.account import get_active_character
    from app.models.world import get_room_name

    lang = get_character_language(character_name) or "de"
    my_room = get_character_current_room(character_name) or ""
    player_char = get_active_character()

    candidates: list = []
    for other in list_available_characters():
        if other == character_name or other == player_char:
            continue
        other_loc = get_character_current_location(other)
        if not other_loc or other_loc != location_id:
            continue
        other_room = get_character_current_room(other) or ""
        candidates.append((other, other_room))

    player_loc = get_character_current_location(player_char) if player_char else ""
    player_room = get_character_current_room(player_char) or "" if player_char else ""
    player_at_location = bool(player_loc and player_loc == location_id)
    if player_char and player_at_location:
        candidates.insert(0, (player_char, player_room))

    same_room = [name for name, room in candidates if room == my_room]
    elsewhere = [(name, room) for name, room in candidates if room != my_room]
    player_present = bool(player_char) and player_char in same_room
    others_in_room = [o for o in same_room if o != player_char]
    anyone_in_room = player_present or bool(others_in_room)

    lines: list = []
    elsewhere_lines: list = []
    if player_present:
        lines.append(f"- {player_char} is present")
    elif player_char and not player_at_location:
        lines.append(
            f"- {player_char} is NOT here "
            f"(do NOT react as if {player_char} were present, "
            f"do NOT imagine an interaction with {player_char})"
        )

    for other in others_in_room:
        # Display text again (flavor or catalog key, "Sleeping" when asleep) —
        # what the others SEE, never the key an image or clip is picked with.
        other_act = get_effective_activity(other) or ""
        suffix = f" ({other_act})" if other_act else ""
        lines.append(f"- {other} is here{suffix}")

    # Every room resolves by name, the location's ground among them.
    for other, other_room in elsewhere:
        elsewhere_lines.append(
            f"- {other} — in: {get_room_name(location_id, other_room, lang)}")

    return lines, elsewhere_lines, anyone_in_room


def _load_events(location_id: str) -> str:
    if not location_id:
        return ""
    try:
        from app.models.events import build_events_prompt_section
        return build_events_prompt_section(location_id=location_id) or ""
    except Exception as e:
        logger.debug("Events laden fehlgeschlagen: %s", e)
    return ""


def _load_memory(character_name: str, partner_name: str = "") -> str:
    try:
        from app.models.memory import build_memory_prompt_section
        return build_memory_prompt_section(
            character_name, partner_name=partner_name, current_message="") or ""
    except Exception as e:
        logger.debug("Memory laden fehlgeschlagen: %s", e)
    return ""


def _load_arcs(character_name: str) -> str:
    try:
        from app.core.story_engine import get_story_engine
        return get_story_engine().inject_arc_context(character_name) or ""
    except Exception as e:
        logger.debug("Arc-Kontext nicht verfuegbar: %s", e)
    return ""


def _load_assignments(character_name: str) -> str:
    try:
        from app.models.intents import build_intents_prompt_section
        return build_intents_prompt_section(character_name) or ""
    except Exception as e:
        logger.debug("Intents-Section laden fehlgeschlagen: %s", e)
    return ""


def _load_pending(character_name: str) -> str:
    try:
        from app.core.pending_reports import build_prompt_section
        return build_prompt_section(character_name) or ""
    except Exception as e:
        logger.debug("Pending-Reports laden fehlgeschlagen: %s", e)
    return ""


def _load_relationships(character_name: str) -> str:
    try:
        from app.models.relationship import build_relationship_prompt_section
        return build_relationship_prompt_section(character_name) or ""
    except Exception as e:
        logger.debug("Relationships laden fehlgeschlagen: %s", e)
    return ""


# ============================================================================
# Recent Activity — rendered as a self-contained block (no template needed)
# ============================================================================

_RECENT_WINDOW_HOURS = 6
_RECENT_MAX_ENTRIES = 24


def _time_str(ts: str) -> str:
    """'HH:MM' from ISO string, empty on error."""
    try:
        return ts[11:16]
    except Exception:
        return ""


def _resolve_location_name(loc_id: str) -> str:
    if not loc_id:
        return ""
    try:
        from app.models.world import get_location_name
        name = get_location_name(loc_id)
        if name and name != loc_id:
            return name
    except Exception:
        pass
    return loc_id


def _enrich_activity_events(events: list, character_name: str) -> None:
    """Reichert Activity-Eintraege mit Kontext an (in-place).

    - `SetLocation` / `Character leaves location` (und aehnliche Tool-Namen
      ohne semantische Activity): nimmt den naechsten location-type-Eintrag
      und haengt den Ortsnamen an.
    - `Talking` ohne metadata.partner: schaut in chat_messages nach dem
      letzten Partner kurz vor diesem ts.
    """
    _LOCATION_TOOL_VALUES = {
        "setlocation", "set_location",
        "character leaves location", "character_leaves_location",
        "leave location", "leave_location",
    }
    n = len(events)
    for i, e in enumerate(events):
        if e.get("type") != "activity":
            continue
        val_lc = (e.get("value") or "").lower().strip()

        # 1) Tool-Namen → location ankleben
        if val_lc in _LOCATION_TOOL_VALUES:
            for j in range(i, n):
                future = events[j]
                if future.get("type") == "location":
                    loc_disp = future.get("value_display") or ""
                    if loc_disp:
                        e["value_display"] = f"{e['value']} → {loc_disp}"
                    break

        # 2) Talking ohne Partner → letzten chat_messages-Partner suchen
        elif val_lc == "talking" and not e.get("partner"):
            partner = _lookup_chat_partner(character_name, e.get("ts") or "")
            if partner:
                e["partner"] = partner


def _lookup_chat_partner(character_name: str, ts: str,
                          window_seconds: int = 120) -> str:
    """Sucht in chat_messages den juengsten Partner um ``ts`` herum."""
    if not character_name or not ts:
        return ""
    try:
        from app.core.db import get_connection
        from datetime import timedelta
        try:
            target = parse_iso(ts)
        except (ValueError, TypeError):
            return ""
        lower = (target - timedelta(seconds=window_seconds)).isoformat()
        upper = (target + timedelta(seconds=window_seconds)).isoformat()
        row = get_connection().execute(
            "SELECT partner FROM chat_messages "
            "WHERE character_name=? AND partner IS NOT NULL AND partner != '' "
            "AND ts BETWEEN ? AND ? "
            "ORDER BY ABS(julianday(ts) - julianday(?)) ASC LIMIT 1",
            (character_name, lower, upper, ts),
        ).fetchone()
        if row and row[0]:
            return str(row[0]).strip()
    except Exception as e:
        logger.debug("_lookup_chat_partner failed: %s", e)
    return ""


def build_recent_activity_section(character_name: str,
                                   hours: int = _RECENT_WINDOW_HOURS,
                                   max_entries: int = _RECENT_MAX_ENTRIES) -> str:
    """Build the "## Recently experienced" block from state_history."""
    try:
        from datetime import timedelta
        from app.core.db import get_connection
        import json as _json

        cutoff = (utc_now() - timedelta(hours=hours)).isoformat()
        conn = get_connection()
        rows = conn.execute(
            "SELECT state_json FROM state_history "
            "WHERE character_name=? AND ts>=? ORDER BY ts ASC",
            (character_name, cutoff),
        ).fetchall()
        if not rows:
            return ""

        # Activity-Werte die rein technisch sind und keinen Mehrwert im
        # Activity-Log haben — komplett rausfiltern.
        _DROP_ACTIVITY_VALUES = {"none", "skip", "greeting"}

        events: list = []
        for (sj,) in rows:
            try:
                d = _json.loads(sj or "{}")
            except Exception:
                continue
            t = d.get("type") or ""
            if t == "effects":
                continue
            val = (d.get("value") or "").strip()
            if not val:
                continue
            if t == "activity" and val.lower() in _DROP_ACTIVITY_VALUES:
                continue
            meta = d.get("metadata") or {}
            if not isinstance(meta, dict):
                meta = {}
            ts = d.get("timestamp") or ""
            entry = {"ts": ts, "type": t, "value": val,
                     "partner": (meta.get("partner") or "").strip(),
                     "reason": (meta.get("reason") or "").strip(),
                     "action": (meta.get("action") or "").strip(),
                     "displaced": [d for d in (meta.get("displaced") or []) if d],
                     "detail": (meta.get("detail") or "").strip()}
            if t == "location":
                entry["value_display"] = _resolve_location_name(val)
            elif t == "room":
                # Name liegt in metadata.name (gespeichert von save_character_current_room)
                entry["value_display"] = (meta.get("name") or val).strip()
            elif t == "access_denied":
                entry["value_display"] = val
            else:
                entry["value_display"] = val
            events.append(entry)

        if not events:
            return ""

        # Anreicherung: Tool-Namen-Activities mit Location/Partner befuellen.
        _enrich_activity_events(events, character_name)

        # Aggregation: collapse adjacent duplicates
        collapsed: list = []
        for e in events:
            if collapsed:
                last = collapsed[-1]
                if last["type"] == e["type"] and last["value"] == e["value"]:
                    last["end_ts"] = e["ts"]
                    if e.get("partner") and not last.get("partner"):
                        last["partner"] = e["partner"]
                    continue
            collapsed.append(dict(e, end_ts=e["ts"]))

        collapsed = collapsed[-max_entries:]

        lines: list = []
        for e in collapsed:
            start = _time_str(e["ts"])
            end = _time_str(e.get("end_ts") or "")
            if end and end != start:
                time_str = f"{start}-{end}"
            else:
                time_str = start
            t = e["type"]
            val = e["value_display"] or e["value"]
            if t == "location":
                lines.append(f"• {time_str}  → {val}")
            elif t == "room":
                lines.append(f"• {time_str}  ↳ Raum {val}")
            elif t == "activity":
                suffix = f" (with {e['partner']})" if e.get("partner") else ""
                if e.get("detail"):
                    suffix += f" — {e['detail'][:60]}"
                lines.append(f"• {time_str}  {val}{suffix}")
            elif t == "access_denied":
                reason_raw = (e.get("reason") or "").strip().rstrip(".")
                default_reason = reason_raw.lower() in ("", "zugang verweigert", "access denied")
                reason = "" if default_reason else f" — {reason_raw}"
                lines.append(f"• {time_str}  Wanted to go to {val}, access denied{reason}")
            elif t == "outfit":
                # M4 entries. The character reads its OWN log here, so the
                # source (skill/compliance/…) stays out — only what changed.
                verb = {"equip": "put on",
                        "unequip": "took off"}.get(e.get("action") or "", "changed")
                gone = e.get("displaced") or []
                suffix = f" (instead of {', '.join(gone)})" if gone else ""
                lines.append(f"• {time_str}  {verb} {val}{suffix}")
            elif t == "travel_failed":
                reason_raw = (e.get("reason") or "").strip()
                human = {
                    "path_lost_in_transit": "path lost in transit",
                    "no_path": "no path available",
                    "blocked": "blocked",
                }.get(reason_raw, reason_raw)
                suffix = f" — {human}" if human else ""
                lines.append(f"• {time_str}  travel to {val} failed{suffix}")
            else:
                lines.append(f"• {time_str}  {t}: {val}")

        if not lines:
            return ""

        header = f"## Recently experienced (last {hours}h):"
        return header + "\n" + "\n".join(lines)
    except Exception as e:
        logger.debug("build_recent_activity_section fehlgeschlagen: %s", e)
        return ""
