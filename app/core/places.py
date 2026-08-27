"""Places — the seats, beds and standing spots of a room, and who holds them
(plan-posen-plaetze.md § 3.6, § 4).

A place is a scene marker (room or prop) finished in world metres by
``scene_recipe`` — the SAME geometry every renderer draws, so the server
seats a character exactly where the client draws the seat. Occupancy is not
a table: a character that sits somewhere carries ``profile["place"]``
(``{"id", "slot", "room_id"}``), and "free" is computed from the profiles of
the room's present characters — a character that walks out of the room or
whose marker vanished simply stops counting. The inventory is cached per
location and dropped whenever a layout, a prop sidecar or the catalog is
written (every writer calls :func:`invalidate`); the TTL only covers a
writer nobody thought of.

``assign`` is the one entry: keep your own place when the new pose is of the
same group, else the place with the fewest occupants, nearest free slot to
where the character stands. ``prefer`` insists on one place and raises
:class:`PlaceUnavailable` instead of falling back.

What the LLM is told about all this lives here too (plan § 5):
:func:`room_offer` is the prompt block every chat/thought consumer shows —
free places with the poses they allow, busy ones by name, the room's
free-text ``activity_hint`` as the tail; :func:`room_offer_short` is the
per-group free count the NPC director picks a room by; :func:`place_label`
names the seat a character holds for the 2D prompt and the presence line.
"""
import math
import threading
from typing import Any, Dict, List, Optional, Tuple

from app.core.keyed_lock import keyed_lock
from app.core.log import get_logger
from app.core.timeutils import utc_now

logger = get_logger("places")

Place = Dict[str, Any]
#: The slot value a PAIR holds: the interaction owns ``pose_places`` slots
#: of the place from slot 0 upwards, not one numbered seat.
PAIR_SLOT = "pair"
_CACHE_TTL_S = 300.0          # belt and braces — every writer invalidates anyway

_lock = threading.Lock()      # guards ``_cache`` only, never held around a compose
_cache: Dict[str, Tuple[Any, Dict[str, List[Place]]]] = {}   # location_id -> (stamp, {room_id: places})


class PlaceUnavailable(ValueError):
    """The place the caller insisted on has no free slot."""


def invalidate() -> None:
    """Drop the whole inventory cache — called by every layout, prop-sidecar
    and catalog writer."""
    with _lock:
        _cache.clear()


def _compose(location_id: str) -> Dict[str, List[Place]]:
    """The location's markers, composed by the scene recipe, keyed by room."""
    from app.core.scene_recipe import compose_scene, scene_inputs
    from app.models.world import get_location_by_id
    loc = get_location_by_id(location_id)
    if not loc:
        return {}
    plan_width_m, building_meta, room_metas = scene_inputs(loc, location_id)
    scene = compose_scene(loc, plan_width_m=plan_width_m,
                          building_meta=building_meta, room_metas=room_metas)
    by_room: Dict[str, List[Place]] = {}
    for m in scene.get("markers") or []:
        if not m.get("id") or not m.get("group"):
            continue
        room_id = str(m.get("room_id") or "")
        by_room.setdefault(room_id, []).append({
            "id": m["id"], "group": m["group"], "label": m.get("label") or m["group"],
            "capacity": int(m.get("capacity") or 1), "slots": m.get("slots") or [m["at_world"]],
            "facing": m.get("facing"), "y_world": m.get("y_world", 0.0),
            "root_offset": m.get("root_offset", 0.0), "source": m.get("source", "room"),
            "room_id": room_id,
        })
    return by_room


def room_places(location_id: str, room_id: str) -> List[Place]:
    """Every place of one room (a copy of the cached list). Composes the
    location on a cache miss; a location the composer chokes on has no
    places rather than no poses."""
    if not location_id or not room_id:
        return []
    now = utc_now()
    with _lock:
        hit = _cache.get(location_id)
        if hit and (now - hit[0]).total_seconds() < _CACHE_TTL_S:
            return list(hit[1].get(room_id) or [])
    try:
        by_room = _compose(location_id)
    except Exception as e:                 # a broken layout must not break a pose
        logger.warning("places: compose failed for %s: %s", location_id, e)
        return []
    with _lock:
        _cache[location_id] = (now, by_room)
    return list(by_room.get(room_id) or [])


def where(name: str) -> Tuple[str, str]:
    """``(location_id, room_id)`` the character is in — empty strings when
    it is nowhere."""
    from app.models.character import get_character_current_location, get_character_current_room
    return (get_character_current_location(name) or "", get_character_current_room(name) or "")


def _present(location_id: str, room_id: str) -> List[Tuple[str, Dict[str, Any]]]:
    """``(name, profile)`` of every roster character in the room — pooled
    NPCs stand nowhere and are not on the roster. One profile read per
    character: location, room and place all live in that dict."""
    from app.models.character import get_character_profile, list_available_characters
    out: List[Tuple[str, Dict[str, Any]]] = []
    for n in list_available_characters():
        prof = get_character_profile(n) or {}
        if (prof.get("current_location") or "") == location_id \
                and (prof.get("current_room") or "") == room_id:
            out.append((n, prof))
    return out


def _held_slot(pl: Any, place: Place, room_id: str) -> Optional[Any]:
    """The slot a profile ``place`` field holds OF ``place`` — None when it
    names another place, another room (marker ids are per room: ``s1`` in
    the kitchen is another chair), or a slot index today's capacity does
    not have (a shrunk marker reads like a vanished one). A pair's
    ``PAIR_SLOT`` passes as it is."""
    if not isinstance(pl, dict) or pl.get("id") != place["id"] \
            or (pl.get("room_id") or "") != room_id:
        return None
    slot = pl.get("slot", 0)
    if slot == PAIR_SLOT:
        return slot
    if isinstance(slot, int) and 0 <= slot < place["capacity"]:
        return slot
    return None


def occupancy(location_id: str, room_id: str, exclude: str = "") -> Dict[str, List[Tuple[str, Any]]]:
    """``{place_id: [(name, slot), …]}`` of the room's present characters. A
    pair holds ``PAIR_SLOT`` and counts as ``pose_places`` slots. A held
    place that today's inventory does not know — unknown id, another
    room's id, a slot beyond the capacity — is no occupancy."""
    known = {p["id"]: p for p in room_places(location_id, room_id)}
    out: Dict[str, List[Tuple[str, Any]]] = {}
    for name, prof in _present(location_id, room_id):
        if name == exclude:
            continue
        pl = prof.get("place")
        place = known.get(pl.get("id")) if isinstance(pl, dict) else None
        slot = _held_slot(pl, place, room_id) if place else None
        if slot is not None:
            out.setdefault(place["id"], []).append((name, slot))
    return out


def _taken_count(place: Place, taken: List[Tuple[str, Any]]) -> int:
    from app.core.pose_catalog import pose_places
    from app.models.character import get_character_pose_key
    n = 0
    for name, slot in taken:
        n += pose_places(get_character_pose_key(name)) if slot == PAIR_SLOT else 1
    return min(n, place["capacity"])


def free_slots(place: Place, taken: List[Tuple[str, Any]]) -> List[int]:
    """The slot indices of ``place`` nobody in ``taken`` holds. A pair
    occupies its slots from 0 upwards, so the free ones are the tail."""
    if any(slot == PAIR_SLOT for _, slot in taken):
        used = _taken_count(place, taken)
        return list(range(used, place["capacity"]))
    held = {slot for _, slot in taken if isinstance(slot, int)}
    return [i for i in range(place["capacity"]) if i not in held]


def _dist(a: Optional[Dict[str, float]], slot: List[float]) -> float:
    if not a:
        return 0.0
    return math.dist((a["x"], a["z"]), (slot[0], slot[1]))


def assign(name: str, pose_key: str, prefer: str = "") -> Optional[dict]:
    """Give ``name`` a free place of the pose's group in its room, write it to
    the profile and put the character on the slot; returns the profile field
    ``{"id", "slot", "room_id"}``. None when the room has no free place of
    that group (the pose stays, the client falls back) — and a place held
    from before is released then. A pose without a group (a standing pose)
    releases the place as well. ``prefer`` names the one place that will do;
    :class:`PlaceUnavailable` when it has no free slot."""
    from app.core.pose_catalog import get_catalog
    from app.models.character import (get_character_pos, get_character_profile,
                                      save_character_profile, set_character_pos)
    entry = get_catalog("pose").get((pose_key or "").strip().lower())
    group = (entry or {}).get("group", "")
    loc, room = where(name)
    if not group or not loc or not room:
        release(name)
        return None
    # One lock per location: two characters choosing in the same room must
    # not both read "slot 0 is free". room_places/occupancy take only the
    # cache lock, never this one — a keyed_lock is a plain Lock.
    with keyed_lock("places", loc):
        cands = [p for p in room_places(loc, room) if p["group"] == group]
        if prefer:
            cands = [p for p in cands if p["id"] == prefer]
        occ = occupancy(loc, room, exclude=name)
        profile = get_character_profile(name) or {}
        current = profile.get("place") if isinstance(profile.get("place"), dict) else None
        options = [(p, free_slots(p, occ.get(p["id"], []))) for p in cands]
        options = [(p, free) for p, free in options if free]
        chosen: Optional[Tuple[Place, int]] = None
        if current:
            # Same group, own place still there: stay seated (keep the very
            # slot when it is free, else any free one of the same place).
            for p, free in options:
                if p["id"] == current.get("id") and (current.get("room_id") or "") == room:
                    slot = current.get("slot") if current.get("slot") in free else free[0]
                    chosen = (p, slot)
        if chosen is None and options:
            pos = get_character_pos(name)
            options.sort(key=lambda pf: (len(occ.get(pf[0]["id"], [])),
                                         _dist(pos, pf[0]["slots"][pf[1][0]])))
            chosen = (options[0][0], options[0][1][0])
        if chosen is None:
            if prefer:
                raise PlaceUnavailable(f"{prefer} has no free slot")
            if current:
                profile["place"] = None
                save_character_profile(name, profile)
            return None
        place, slot = chosen
        field = {"id": place["id"], "slot": slot, "room_id": room}
        profile["place"] = field
        save_character_profile(name, profile)
        sx, sz = place["slots"][slot]
        # The slot lies inside the room's own location, so the point derives
        # the location it already has; preserve_movement_target keeps a
        # journey that just arrived from being cancelled by its own seat.
        set_character_pos(name, sx, sz, preserve_movement_target=True)
        return field


def release(name: str) -> None:
    """Clear ``profile["place"]`` if set — the character stands up, the
    position stays where it is."""
    from app.models.character import get_character_profile, save_character_profile
    profile = get_character_profile(name) or {}
    if profile.get("place"):
        profile["place"] = None
        save_character_profile(name, profile)


def place_of(name: str, profile: Optional[dict] = None) -> Optional[Place]:
    """The place a character holds, validated against today's inventory —
    a marker that vanished, another room's id or a slot beyond the capacity
    reads as no place. The dict is the place plus ``slot`` and the ``x, z``
    of the held slot (a pair sits on slot 0)."""
    from app.models.character import get_character_profile
    prof = profile if profile is not None else (get_character_profile(name) or {})
    pl = prof.get("place")
    if not isinstance(pl, dict) or not pl.get("id"):
        return None
    loc, room = where(name)
    for p in room_places(loc, room):
        slot = _held_slot(pl, p, room)
        if slot is not None:
            idx = 0 if slot == PAIR_SLOT else slot
            xz = p["slots"][idx] if idx < len(p["slots"]) else p["slots"][0]
            return dict(p, slot=slot, x=xz[0], z=xz[1])
    return None


# ── what the LLM is told ────────────────────────────────────────────────
_OFFER_MAX_LINES = 12


def _group_lines(location_id: str, room_id: str, viewer: str) -> List[str]:
    """One line per place — the markers of one prop collapse into a single
    line per group (a "2× Chair" is one row), room markers stay apart —
    busy ones by the names holding them, free ones with the poses of their
    group the free slots allow (a pair pose needs ``places`` free slots).
    ``viewer`` never counts as an occupant: the block is written for them."""
    from app.core.pose_catalog import get_catalog, poses_in_group
    occ = occupancy(location_id, room_id, exclude=viewer)
    cat = get_catalog("pose")
    rows: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for p in room_places(location_id, room_id):
        key = (p["label"], p["group"]) if p["source"] == "prop" else (p["id"], p["group"])
        row = rows.setdefault(key, {"label": p["label"], "group": p["group"], "count": 0,
                                    "free": 0, "cap": 0, "who": []})
        taken = occ.get(p["id"], [])
        row["count"] += 1
        row["free"] += len(free_slots(p, taken))
        row["cap"] += p["capacity"]
        row["who"] += [n for n, _ in taken]
    lines: List[str] = []
    for row in rows.values():
        head = f"{row['count']}× {row['label']}" if row["count"] > 1 else row["label"]
        if row["free"] == 0:
            lines.append(f"- {head} (occupied by {', '.join(row['who'])})")
            continue
        poses = []
        for k in poses_in_group(row["group"]):
            e = cat[k]
            if e["solo"]:
                poses.append(k)
            elif row["free"] >= e["places"]:
                poses.append(f"{k} (with partner)")
        state = ("free" if not row["who"]
                 else f"{row['free']} of {row['cap']} free, {', '.join(row['who'])} here")
        lines.append(f"- {head} ({state}): {', '.join(poses)}")
    return lines


def room_offer(name: str, location_id: str, room_id: str) -> str:
    """The room's PLACE OFFER for ``name`` (plan § 5) — the block the chat,
    thought and tool prompts show::

        Places here:
        - Seat (occupied by Ann)
        - Bed (free): sleeping
        Anywhere here: standing
        Also typical here: reading nooks

    Markers first (capped at ``_OFFER_MAX_LINES`` rows), then the poses
    that need no place at all, then the room's free-text ``activity_hint``
    as the tail. A room without markers still gets the last two lines;
    nothing at all yields ``""`` so a template can ``{% if %}`` it away."""
    from app.core.pose_catalog import get_catalog, poses_in_group
    from app.models.world import get_room_activity_hint
    lines = _group_lines(location_id, room_id, name) if location_id and room_id else []
    out: List[str] = []
    if lines:
        out.append("Places here:")
        out += lines[:_OFFER_MAX_LINES]
        if len(lines) > _OFFER_MAX_LINES:
            out.append(f"…and {len(lines) - _OFFER_MAX_LINES} more")
    cat = get_catalog("pose")
    anywhere = [k if cat[k]["solo"] else f"{k} (with partner)" for k in poses_in_group("stand")]
    if anywhere:
        out.append("Anywhere here: " + ", ".join(anywhere))
    hint = get_room_activity_hint(location_id, room_id) if location_id else ""
    if hint:
        out.append(f"Also typical here: {hint}")
    return "\n".join(out)


def room_offer_short(location_id: str, room_id: str) -> str:
    """Per group: free slots — ``"seat 2 free, bed 1 free"`` — what the NPC
    director needs to pick a room; ``""`` for a room without markers."""
    occ = occupancy(location_id, room_id)
    free: Dict[str, int] = {}
    for p in room_places(location_id, room_id):
        free[p["group"]] = free.get(p["group"], 0) + len(free_slots(p, occ.get(p["id"], [])))
    return ", ".join(f"{g} {n} free" for g, n in free.items())


def place_label(name: str) -> str:
    """Label of the place ``name`` holds ("Seat", "Bed", a prop's name) or
    ``""`` — also for a standing spot: "standing, on the standing spot"
    tells a prompt nothing."""
    p = place_of(name)
    return p["label"] if p and p["group"] != "stand" else ""
