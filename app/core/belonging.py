"""Where a character belongs when it stands nowhere — and the free bed.

Two rules (user decision 2026-11-08):

* **Sleeping without a place of one's own.** A character that goes to sleep
  without a ``home_location`` looks for a BED somewhere in the world: a room of
  a location it knows that holds a lying place (place group ``lie`` — a bed's
  marker or a room-owned one), in which no OTHER character is right now and to
  which no other character is walking. Only presence counts as "taken"; an
  empty room that is somebody's home room is free. The room the sleeper is in
  already, then the room it is already walking to, are kept while they stay
  free — otherwise a sleeper on its way would hop from bed to bed whenever a
  nearer location came into range. After that the nearest location wins
  (straight metres from the character's point, or from the place it will come
  back to when it is off the map; with neither, the order of its known
  locations), and inside it the first bed room in room order. The ground and the storey corridors are never a bed room:
  the outside is not where anybody should stay.
* **Standing nowhere.** A character with neither location, room, metre point
  nor journey is put where it belongs — at server start, and right after a
  fresh start (``character_reset``), which drops the whole state row. In this
  order: its NPC slot (``npc_home.place_npc``, the one placement helper for
  slots), its home, the location its daily schedule names for this game hour,
  a free bed. Left alone are the ones that stand nowhere on purpose: asleep off
  the map (a return marker, or ``home_location`` is the off-map sentinel) and
  an ``avatar_only_presence`` character nobody controls.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("belonging")

#: The place group a bed's lying place carries (``place_group_migration``
#: maps the old ``bed`` group onto it).
BED_GROUP = "lie"


def _is_reserved_room(room_id: str) -> bool:
    from app.models.world import GROUND_ROOM_ID, is_floor_room
    return not room_id or room_id == GROUND_ROOM_ID or is_floor_room(room_id)


def room_has_bed(location_id: str, room_id: str) -> bool:
    """Whether the room holds a lying place. The ground and the corridors
    never count, whatever stands there."""
    if not location_id or _is_reserved_room(room_id):
        return False
    from app.core import places
    return any(p.get("group") == BED_GROUP
               for p in places.room_places(location_id, room_id))


def _walking_targets(exclude: str) -> set:
    """``(location_id, room_id)`` every OTHER character is walking to."""
    from app.core.travel_engine import get_journey
    from app.models.character import list_available_characters
    out = set()
    for other in list_available_characters():
        if other == exclude:
            continue
        try:
            journey = get_journey(other)
        except Exception:
            continue
        if journey:
            out.add((str(journey.get("target") or "").strip(),
                     str(journey.get("target_room") or "").strip()))
    return out


def find_free_bed(name: str) -> Optional[Tuple[str, str]]:
    """``(location_id, room_id)`` of the bed room ``name`` should sleep in, or
    None when no known location has a free one. See the module docstring for
    the order. Read only."""
    from app.core.room_entry import characters_in_room
    from app.core.travel_engine import get_journey
    from app.models.character import (get_character_current_location,
                                      get_character_current_room,
                                      get_character_pos, get_character_profile,
                                      get_known_locations)
    from app.models.world import get_location_by_id

    walking = _walking_targets(name)

    def usable(location_id: str, room_id: str) -> bool:
        return (bool(location_id) and (location_id, room_id) not in walking
                and room_has_bed(location_id, room_id)
                and not characters_in_room(location_id, room_id, exclude=name))

    profile = get_character_profile(name) or {}
    here = ((get_character_current_location(name, profile=profile) or "").strip(),
            (get_character_current_room(name, profile=profile) or "").strip())
    if usable(*here):
        return here
    journey = get_journey(name, profile=profile)
    if journey:
        target = (str(journey.get("target") or "").strip(),
                  str(journey.get("target_room") or "").strip())
        if usable(*target):
            return target

    origin = get_character_pos(name)
    if origin is None:
        # Asleep off the map: measure from the place it will come back to.
        back = get_location_by_id(
            str(profile.get("_offmap_return_location") or "").strip()) or {}
        if back.get("pos_x") is not None and back.get("pos_z") is not None:
            origin = {"x": float(back["pos_x"]), "z": float(back["pos_z"])}

    candidates: List[Tuple[float, int, Dict[str, Any]]] = []
    for order, location_id in enumerate(get_known_locations(name)):
        loc = get_location_by_id(location_id)
        if not loc or loc.get("pos_x") is None or loc.get("pos_z") is None:
            continue  # unplaced: it has no rooms anybody can walk into
        dist = (math.hypot(float(loc["pos_x"]) - origin["x"],
                           float(loc["pos_z"]) - origin["z"])
                if origin else 0.0)
        candidates.append((dist, order, loc))
    candidates.sort(key=lambda c: (c[0], c[1]))
    for _dist, _order, loc in candidates:
        for room in loc.get("rooms") or []:
            room_id = str(room.get("id") or "").strip()
            if usable(loc["id"], room_id):
                return loc["id"], room_id
    return None


def _should_stand_nowhere(name: str, profile: Dict[str, Any],
                          config: Dict[str, Any]) -> bool:
    """The characters that stand nowhere on purpose."""
    from app.models.character import OFFMAP_SLEEP_SENTINEL
    if str(profile.get("_offmap_return_location") or "").strip():
        return True   # asleep off the map, wakes where it left
    if str(config.get("home_location") or "").strip() == OFFMAP_SLEEP_SENTINEL:
        return True   # sleeps off the map by its own setting
    if str(config.get("avatar_only_presence", "")).strip().lower() == "true":
        from app.models.account import is_player_controlled
        return not is_player_controlled(name)
    return False


def needs_placing(name: str) -> bool:
    """True for a character in the roster with no location, no room, no metre
    point and no journey that does not stand nowhere on purpose."""
    from app.core.travel_engine import get_journey
    from app.models.character import (get_character_config,
                                      get_character_current_location,
                                      get_character_current_room,
                                      get_character_pos, get_character_profile,
                                      get_character_status, is_out_of_world)
    if is_out_of_world(get_character_status(name)):
        return False
    profile = get_character_profile(name) or {}
    if (get_character_current_location(name, profile=profile) or "").strip():
        return False
    if (get_character_current_room(name, profile=profile) or "").strip():
        return False
    if get_character_pos(name) is not None or get_journey(name, profile=profile):
        return False
    return not _should_stand_nowhere(name, profile, get_character_config(name) or {})


def _place(name: str, location_id: str, room_id: str) -> bool:
    from app.models.character import (save_character_current_location,
                                      save_character_current_room)
    save_character_current_location(name, location_id)
    if room_id:
        save_character_current_room(name, room_id)
    return True


def _slot_place(name: str, profile: Dict[str, Any]) -> str:
    """Put a temporary NPC back into its slot. ``""`` when it has none or the
    placement wrote nothing."""
    from app.core.npc_home import area_home, place_npc
    from app.models.world import get_arrival_room_id, get_location_by_id
    area_id = str(profile.get("npc_slot_area") or "").strip()
    if area_id:
        return "slot" if place_npc(name, home=area_home(area_id)) else ""
    location_id = str(profile.get("npc_slot_location") or "").strip()
    loc = get_location_by_id(location_id) if location_id else None
    if not loc:
        return ""
    from app.core.npc_spawn import normalize_slots
    role = str(profile.get("npc_slot_role") or "").strip().lower()
    slot = next((s for s in normalize_slots(loc.get("npc_slots"))
                 if s["role"].lower() == role), None) if role else None
    room_id = (slot or {}).get("room") or get_arrival_room_id(loc)
    radius_m = int((slot or {}).get("radius_m") or 0)
    return "slot" if place_npc(name, location_id, room_id, radius_m) else ""


def _home_place(config: Dict[str, Any]) -> Tuple[str, str]:
    from app.models.character import OFFMAP_SLEEP_SENTINEL
    from app.models.world import get_arrival_room_id, get_location
    home = str(config.get("home_location") or "").strip()
    if not home or home == OFFMAP_SLEEP_SENTINEL:
        return "", ""
    loc = get_location(home)
    if not loc:
        return "", ""
    room = str(config.get("home_room") or "").strip()
    return loc["id"], room or get_arrival_room_id(loc)


def _schedule_place(name: str) -> Tuple[str, str]:
    """The location the daily schedule names for this game hour (a sleep hour
    names none — that is the bed's turn)."""
    from app.core.timeutils import game_time
    from app.models.character import get_character_daily_schedule
    from app.models.world import get_arrival_room_id, get_location
    schedule = get_character_daily_schedule(name) or {}
    if not schedule.get("enabled"):
        return "", ""
    hour = game_time().hour
    slot = next((s for s in schedule.get("slots") or []
                 if s.get("hour") == hour), None) or {}
    target = str(slot.get("location") or "").strip()
    if slot.get("sleep") or not target or target == "__sleep__":
        return "", ""
    loc = get_location(target)
    if not loc:
        return "", ""
    return loc["id"], get_arrival_room_id(loc)


def place_where_they_belong(name: str) -> str:
    """Put ``name`` where it belongs if it stands nowhere (:func:`needs_placing`).

    Returns how it was placed — ``"slot"``, ``"home"``, ``"schedule"``,
    ``"bed"`` — or ``""`` when nothing was written."""
    from app.models.character import get_character_config, get_character_profile
    if not needs_placing(name):
        return ""
    profile = get_character_profile(name) or {}
    config = get_character_config(name) or {}
    try:
        how = _slot_place(name, profile)
        if how:
            return how
        for how, (location_id, room_id) in (("home", _home_place(config)),
                                            ("schedule", _schedule_place(name))):
            if location_id and _place(name, location_id, room_id):
                return how
        bed = find_free_bed(name)
        if bed and _place(name, *bed):
            return "bed"
    except Exception as e:  # noqa: BLE001 — one character must not stop the rest
        logger.warning("%s could not be placed: %s", name, e)
        return ""
    logger.warning("%s stands nowhere and nothing says where it belongs "
                   "(no slot, home, schedule hour or free bed in a known location)",
                   name)
    return ""


def place_unplaced_characters() -> Dict[str, str]:
    """Start-up repair: :func:`place_where_they_belong` for the whole roster.
    Returns ``{name: how}`` for everyone it placed."""
    from app.models.character import list_available_characters
    placed: Dict[str, str] = {}
    for name in list_available_characters():
        how = place_where_they_belong(name)
        if how:
            placed[name] = how
    return placed
