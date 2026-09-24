"""Places — the seats, lying places and standing spots of a room, and who
holds them (plan-posen-plaetze.md § 3.6, § 4; plan-platztypen.md).

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
same group, else the place with the fewest taken slots, nearest free slot to
where the character stands. ``prefer`` insists on one place and raises
:class:`PlaceUnavailable` instead of falling back. A PAIR (an interaction,
``interaction_engine``) takes ONE place for two through ``assign_pair``:
both profiles hold it as the ``PAIR_SLOT`` and the pair consumes the pose's
``places`` slots from slot 0 upwards; ``assign`` never re-seats a running
pair, ``release_pair`` stands both up. A place carries at most ONE pair —
its centre is the pair's anchor, unique per place — so ``assign_pair``
refuses a place another pair holds, however many slots are left.

What the LLM is told about all this lives here too (plan § 5):
:func:`room_offer` is the prompt block every chat/thought consumer shows —
free places with the poses they allow, busy ones by name, the room's
free-text ``activity_hint`` as the tail; :func:`room_offer_short` is the
per-group free count the NPC director picks a room by; :func:`place_label`
names the seat a character holds, :func:`place_phrase` puts the group's
preposition in front of it ("on the sofa") for the 2D prompt, the presence
line and the player's Others panel.

A seat NEVER evicts: ``set_character_pos`` derives the location from the
point, so a slot outside the location's boundary (a marker authored past
the footprint) is bookkept but the figure stays put (:func:`inside`), and
an unplaced location — no pin, no world frame — has no places at all.
"""
import json
import math
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.keyed_lock import keyed_lock
from app.core.log import get_logger
from app.core.timeutils import utc_now

logger = get_logger("places")

Place = Dict[str, Any]
#: The slot value a PAIR holds: the interaction owns ``pose_places`` slots
#: of the place — the first ones no solo sitter holds — not one numbered
#: seat. At most one pair per place (``assign_pair``).
PAIR_SLOT = "pair"
_CACHE_TTL_S = 300.0          # belt and braces — every writer invalidates anyway

_lock = threading.Lock()      # guards ``_cache`` only, never held around a compose
_cache: Dict[str, Tuple[Any, Dict[str, List[Place]]]] = {}   # location_id -> (stamp, {room_id: places})
_warned_outside: set = set()  # place ids already reported as lying outside their location


class PlaceUnavailable(ValueError):
    """The place the caller insisted on has no free slot."""


def invalidate() -> None:
    """Drop the whole inventory cache — called by every layout, prop-sidecar
    and catalog writer."""
    with _lock:
        _cache.clear()


def _compose(location_id: str) -> Dict[str, List[Place]]:
    """The location's markers, composed by the scene recipe, keyed by room —
    in WORLD metres. The recipe composes in the location's LOCAL frame
    (origin = the pin, § A13a; the 3D client offsets the whole tile), so
    every slot goes through ``local_to_world`` with the location's pin and
    turn, and a turned location turns its markers' compass facing by the
    same angle (as a turned room does in ``scene_recipe._markers``). An
    UNPLACED location (no pin) has no world frame, so it has no places:
    its recipe-local metres would read as world metres, and a seat there
    would put the sitter somewhere on the map that is not this location."""
    from app.core.scene_recipe import compose_scene, scene_inputs
    from app.core.world_geometry import local_to_world
    from app.models.world import get_location_by_id
    loc = get_location_by_id(location_id)
    if not loc or loc.get("pos_x") is None or loc.get("pos_z") is None:
        return {}
    plan_width_m, building_meta, room_metas = scene_inputs(loc, location_id)
    scene = compose_scene(loc, plan_width_m=plan_width_m,
                          building_meta=building_meta, room_metas=room_metas)
    cx, cz = float(loc["pos_x"]), float(loc["pos_z"])
    yaw = float(loc.get("yaw_deg") or 0.0)

    def _world(pt: List[float]) -> List[float]:
        wx, wz = local_to_world(float(pt[0]), float(pt[1]), cx, cz, yaw)
        return [round(wx, 2), round(wz, 2)]

    by_room: Dict[str, List[Place]] = {}
    for m in scene.get("markers") or []:
        if not m.get("id") or not m.get("group"):
            continue
        room_id = str(m.get("room_id") or "")
        facing = m.get("facing")
        if facing is not None and yaw:
            facing = round((float(facing) + yaw) % 360.0, 1)
        by_room.setdefault(room_id, []).append({
            "id": m["id"], "group": m["group"], "label": m.get("label") or m["group"],
            "capacity": int(m.get("capacity") or 1),
            "slots": [_world(pt) for pt in (m.get("slots") or [m["at_world"]])],
            "facing": facing, "y_world": m.get("y_world", 0.0),
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


#: The census query behind :func:`_present` and :func:`location_occupancy`.
#: Where a character STANDS (``current_location``/``current_room``) are
#: ``character_state`` COLUMNS, what it SITS ON (``place``) is an ordinary
#: ``profile_json`` key — it is not in ``character._STATE_META_KEYS`` — so the
#: census is one join plus one ``json_extract``, the same shape
#: ``character.list_active_journeys`` uses. ``json_valid`` guards the extract:
#: a single unparsable blob must not abort the census for the whole room.
_CENSUS_SQL = (
    "SELECT c.name, COALESCE(c.status, ''), COALESCE(s.current_room, ''), "
    "       CASE WHEN json_valid(c.profile_json) "
    "            THEN json_extract(c.profile_json, '$.place') END "
    "FROM characters c "
    "LEFT JOIN character_state s ON s.character_name = c.name "
    "WHERE COALESCE(s.current_location, '') = ? "
)


def _census(location_id: str, room_id: Optional[str]) -> List[Tuple[str, str, Optional[dict]]]:
    """``(name, room_id, place)`` of every roster character in the location —
    in ONE query, never a profile load per character (DATA-10).

    ``room_id`` None asks about the whole location (:func:`location_occupancy`),
    a room id restricts the census to that room. ``place`` is the parsed
    profile field or None.

    The roster gate is the one of ``list_available_characters``: names with a
    leading underscore and reserved names are no characters, and a POOLED NPC
    stands nowhere. That function's filesystem fallback has NO counterpart
    here — world data is DB-only, and a world with no rows has nobody in any
    room either.
    """
    from app.core.db import get_connection
    from app.models.character import POOLED_STATUS, _is_real_character
    sql = _CENSUS_SQL
    params: List[Any] = [location_id]
    if room_id is not None:
        sql += "  AND COALESCE(s.current_room, '') = ? "
        params.append(room_id)
    sql += "ORDER BY c.name ASC"
    try:
        rows = get_connection().execute(sql, tuple(params)).fetchall()
    except Exception as e:                 # a broken row must not break a pose
        logger.warning("places: census failed for %s/%s: %s", location_id, room_id, e)
        return []
    out: List[Tuple[str, str, Optional[dict]]] = []
    for name, status, room, place_raw in rows:
        if not _is_real_character(name) or status == POOLED_STATUS:
            continue
        place: Any = None
        if place_raw:
            try:
                place = json.loads(place_raw)
            except Exception:
                place = None
        out.append((name, room or "", place if isinstance(place, dict) else None))
    return out


def _present(location_id: str, room_id: str) -> List[Tuple[str, Dict[str, Any]]]:
    """``(name, state)`` of every roster character in the room — pooled
    NPCs stand nowhere and are not on the roster.

    ONE query for the whole room (:func:`_census`), not one full profile per
    roster character: ``assign`` holds ``keyed_lock("places", loc)`` around
    this and ``room_offer`` runs it once per chat turn, so a 40-character
    world used to pay 40 profile loads for a single sitting down.

    ``state`` is NOT a profile — it carries exactly ``place``,
    ``current_location`` and ``current_room``, the three fields the two
    consumers read (:func:`occupancy` here, ``room_stand._mates``). Anything
    else has to be read where it lives.
    """
    return [(name, {"place": place,
                    "current_location": location_id,
                    "current_room": room_id})
            for name, _room, place in _census(location_id, room_id)]


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


def _has_pair(taken: List[Tuple[str, Any]]) -> bool:
    return any(slot == PAIR_SLOT for _, slot in taken)


def _held_slots(place: Place, taken: List[Tuple[str, Any]]) -> List[int]:
    """The slot indices of ``place`` the entries in ``taken`` hold — the ONE
    source ``free_slots`` and ``_taken_count`` both read. A solo entry holds
    its numbered slot; the PAIR entries (both partners list the place) are
    ONE pair — at most one per place, ``assign_pair`` sees to that — holding
    its pose's ``places`` slots: the first ones no solo sitter holds, counted
    once, never per partner."""
    from app.core.pose_catalog import pose_places
    from app.models.character import get_character_pose_key
    held = {slot for _, slot in taken if isinstance(slot, int)}
    need = max((pose_places(get_character_pose_key(name))
                for name, slot in taken if slot == PAIR_SLOT), default=0)
    for i in range(place["capacity"]):
        if need <= 0:
            break
        if i not in held:
            held.add(i)
            need -= 1
    return sorted(i for i in held if 0 <= i < place["capacity"])


def _taken_count(place: Place, taken: List[Tuple[str, Any]]) -> int:
    """How many slots of ``place`` are held (see :func:`_held_slots`)."""
    return len(_held_slots(place, taken))


def free_slots(place: Place, taken: List[Tuple[str, Any]]) -> List[int]:
    """The slot indices of ``place`` nobody in ``taken`` holds (the
    complement of :func:`_held_slots`)."""
    held = set(_held_slots(place, taken))
    return [i for i in range(place["capacity"]) if i not in held]


def _dist(a: Optional[Dict[str, float]], slot: List[float]) -> float:
    if not a:
        return 0.0
    return math.dist((a["x"], a["z"]), (slot[0], slot[1]))


def centre_of(place: Place) -> Tuple[float, float]:
    """The point a PAIR anchors at: the mean of the slots — capacity 1 is
    the marker itself, capacity 2 the marker position (the slots straddle
    it), a bench for three its middle seat."""
    slots = place["slots"]
    return (sum(float(s[0]) for s in slots) / len(slots),
            sum(float(s[1]) for s in slots) / len(slots))


def pair_yaw(place: Place, pose_key: str) -> float:
    """Y rotation (radians) of a pair clip on ``place``: the clip's +X
    (``interaction_engine``: mapped by ``atan2(−uz, ux)``) falls along the
    marker's facing. Compass facing f — 0 = south (+z), 90 = east (+x) — is
    the world direction (sin f, cos f), so ``atan2(−cos f, sin f)`` =
    f − 90°; the pose's ``yaw_offset`` (degrees) turns the frame further.
    No facing on the marker reads as 0 = south."""
    from app.core.pose_catalog import pose_yaw_offset
    facing = float(place.get("facing") or 0.0)
    return math.radians(facing - 90.0 + pose_yaw_offset(pose_key))


def inside(location_id: str, x: float, z: float) -> bool:
    """Does the point derive ``location_id`` — the same question
    ``set_character_pos`` asks (``location_at_point``: the smallest drawn
    boundary containing the point)? A slot that answers No must never be
    walked to: the write would evict the character from its location."""
    from app.core.world_geometry import location_at_point
    from app.models.world import list_locations
    loc = location_at_point(float(x), float(z), list_locations())
    return ((loc.get("id") or "") if loc else "") == (location_id or "")


def _warn_outside(location_id: str, place: Place, x: float, z: float) -> None:
    """Once per place id: the marker lies outside its location's boundary,
    so the seat is bookkept but nobody is moved onto it."""
    key = f"{location_id}/{place['room_id']}/{place['id']}"
    if key in _warned_outside:
        return
    _warned_outside.add(key)
    logger.warning("places: %s '%s' in %s/%s lies outside the location at (%.2f, %.2f) — "
                   "seated without moving the character", place["group"], place["id"],
                   location_id, place["room_id"], x, z)


def assign(name: str, pose_key: str, prefer: str = "") -> Optional[dict]:
    """Give ``name`` a free place of the pose's group in its room, write it to
    the profile and put the character on the slot; returns the profile field
    ``{"id", "slot", "room_id"}``. None when the room has no free place of
    that group (the pose stays, the client falls back) — and a place held
    from before is released then. A pose with no group at all (an ungrouped
    catalog entry) releases the place as well. ``prefer`` names the one place that will do;
    :class:`PlaceUnavailable` when it has no free slot.

    A PAIR pose is seated by :func:`assign_pair` only (one place for two):
    here it keeps the pair seat it holds — the setter calls this right
    after the engine seated the pair — and is never put on a solo slot;
    a pair without a place (it met halfway) stands up from whatever seat
    it held before."""
    from app.core.pose_catalog import get_catalog
    from app.models.character import (get_character_pos, get_character_profile,
                                      save_character_profile, set_character_pos)
    entry = get_catalog("pose").get((pose_key or "").strip().lower())
    group = (entry or {}).get("group", "")
    loc, room = where(name)
    if not group or not loc or not room:
        release(name)
        return None
    if not entry.get("solo", True):
        profile = get_character_profile(name) or {}
        current = profile.get("place") if isinstance(profile.get("place"), dict) else None
        if current and current.get("slot") == PAIR_SLOT \
                and (current.get("room_id") or "") == room \
                and any(p["id"] == current.get("id") and p["group"] == group
                        for p in room_places(loc, room)) \
                and (not prefer or prefer == current.get("id")):
            return dict(current)
        if prefer:
            raise PlaceUnavailable(f"{prefer}: a pair pose is seated with its partner")
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
            # Fewest TAKEN SLOTS first (a pair of two on a bench is two, not
            # one entry per partner), then the nearest free slot.
            options.sort(key=lambda pf: (_taken_count(pf[0], occ.get(pf[0]["id"], [])),
                                         _dist(pos, pf[0]["slots"][pf[1][0]])))
            chosen = (options[0][0], options[0][1][0])
        if chosen is None:
            if prefer:
                raise PlaceUnavailable(f"{prefer} has no free slot")
            if current:
                # Through :func:`release`, not by clearing the field here: a
                # character that loses its seat has stood up, and standing up
                # is where the free standing point is chosen (T4).
                release(name)
            return None
        place, slot = chosen
        field = {"id": place["id"], "slot": slot, "room_id": room}
        # LOCK ORDER: places-lock (held here) BEFORE character_profile —
        # never the reverse, and never two characters' profile locks at once.
        # The profile is READ AGAIN under the lock: the copy above was read
        # for the seating decision, and writing that stale dict back is what
        # loses a concurrent equip (which holds this very lock) — the whole
        # profile_json blob is written out, so the other writer's fields go
        # with it. The lock is released before ``set_character_pos``, which
        # reaches ``save_character_current_location`` and ``release`` further
        # down; a plain Lock is not re-entrant, so it must not be held there.
        with keyed_lock("character_profile", name):
            profile = get_character_profile(name) or {}
            profile["place"] = field
            save_character_profile(name, profile)
        sx, sz = place["slots"][slot]
        # The point derives the location: a slot inside the room's own
        # location keeps the one the character has, and preserve_movement_
        # target keeps a journey that just arrived from being cancelled by
        # its own seat. A slot OUTSIDE the boundary (a marker authored past
        # the footprint) would evict — the seat is bookkept, the figure
        # stays where it is.
        if inside(loc, sx, sz):
            set_character_pos(name, sx, sz, preserve_movement_target=True)
        else:
            _warn_outside(loc, place, sx, sz)
        return field


def release(name: str) -> None:
    """Clear ``profile["place"]`` if set — the character STANDS UP, next to the
    seat it just left (``room_stand``, T4): the freed point is whatever the
    room offers nearest to where the exit clip of its pose sets it down (the
    seat itself when that clip stays on the spot), so nobody stays standing
    in the armchair and nobody walks across the room for it. A room that
    offers no free point leaves the position where it is.
    """
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    # Read AND write under the per-character profile lock (DATA-3): the whole
    # profile_json blob is written out, so a stale read here would revert a
    # concurrent equip. ``stand_up`` stays OUTSIDE — it writes the profile
    # itself and a keyed_lock is a plain, non-re-entrant Lock.
    with keyed_lock("character_profile", name):
        profile = get_character_profile(name) or {}
        old = profile.get("place")
        pose = profile.get("pose_key") or ""
        released = bool(old)
        if released:
            profile["place"] = None
            save_character_profile(name, profile)
    if released:
        # The seat just left and the pose it was held for: the exit clip of
        # that pose may carry the figure off the seat, and the stand point
        # starts where it sets the figure down (``room_stand.stand_up``).
        from app.core.room_stand import stand_up
        stand_up(name, from_place=old if isinstance(old, dict) else None,
                 from_pose_key=pose)


def can_take(name: str, pose_key: str, place_id: str, ignore: Tuple[str, ...] = ()) -> bool:
    """ADVISORY: has ``place_id`` in ``name``'s room a free slot for the
    pose's group right now, with the characters in ``ignore`` (the one
    asking, a partner about to stand up with it) not counting? No lock, no
    write — the setter asks this BEFORE it ends a running interaction for
    an insisted place, so a taken seat is refused with nothing changed; the
    authoritative answer stays :func:`assign` under the lock."""
    from app.core.pose_catalog import group_of
    group = group_of(pose_key)
    loc, room = where(name)
    if not group or not loc or not room:
        return False
    place = next((p for p in room_places(loc, room)
                  if p["id"] == place_id and p["group"] == group), None)
    if place is None:
        return False
    taken = [(n, s) for n, s in occupancy(loc, room).get(place_id, []) if n not in ignore]
    return bool(free_slots(place, taken))


def assign_pair(actor: str, partner: str, pose_key: str) -> Optional[Tuple[Place, float]]:
    """ONE place for two: a place of the pose's group in the actor's room
    with room for the pose's ``places`` slots and NO other pair on it (one
    pair per place — the centre is the pair's anchor; the partners' own
    pair seat counts as free for a re-assignment) — the nearest to the
    pair's midpoint — written to BOTH profiles as the ``PAIR_SLOT``;
    returns ``(place, yaw_rad)`` (:func:`pair_yaw`). Nobody is moved: the
    interaction engine places the figures from the anchor — and asks
    :func:`inside` first, since a centre outside the location (warned here,
    once per place) would evict both partners. None when the
    actor stands in no location/room (outdoors: the caller anchors at the
    midpoint, whatever the group) or when no place of the group fits and
    the group needs none (``needs_place: false`` — a standing pair meets
    halfway); any group that DOES need a marker raises
    :class:`PlaceUnavailable` when none fits — a seated pair without a seat
    is no pair."""
    from app.core.pose_catalog import group_of, needs_place, pose_places
    from app.models.character import (get_character_pos, get_character_profile,
                                      save_character_profile)
    group = group_of(pose_key)
    need = pose_places(pose_key)
    loc, room = where(actor)
    if not group or not loc or not room:
        return None
    with keyed_lock("places", loc):
        occ = occupancy(loc, room)
        mine = {actor, partner}
        fitting = []
        for p in room_places(loc, room):
            if p["group"] != group:
                continue
            others = [(n, s) for n, s in occ.get(p["id"], []) if n not in mine]
            if not _has_pair(others) and len(free_slots(p, others)) >= need:
                fitting.append(p)
        if not fitting:
            if not needs_place(group):
                return None
            raise PlaceUnavailable(f"no free {group} for two")
        pa, pb = get_character_pos(actor), get_character_pos(partner)
        if pa and pb:
            mid = {"x": (pa["x"] + pb["x"]) / 2, "z": (pa["z"] + pb["z"]) / 2}
            fitting.sort(key=lambda p: _dist(mid, list(centre_of(p))))
        best = fitting[0]
        for name in (actor, partner):
            # ONE profile lock at a time (never both partners' at once — two
            # threads seating the same pair from opposite ends would deadlock
            # on a fixed pair order). Same order as ``assign``: places-lock
            # first, then character_profile.
            with keyed_lock("character_profile", name):
                prof = get_character_profile(name) or {}
                prof["place"] = {"id": best["id"], "slot": PAIR_SLOT,
                                 "room_id": room}
                save_character_profile(name, prof)
        cx, cz = centre_of(best)
        if not inside(loc, cx, cz):
            _warn_outside(loc, best, cx, cz)
        return best, pair_yaw(best, pose_key)


def release_pair(actor: str, partner: str) -> None:
    """Both partners stand up (:func:`release` each)."""
    release(actor)
    release(partner)


def place_of(name: str, profile: Optional[dict] = None) -> Optional[Place]:
    """The place a character holds, validated against today's inventory —
    a marker that vanished, another room's id or a slot beyond the capacity
    reads as no place. The dict is the place plus ``slot`` and the ``x, z``
    of the held slot — for a pair the place's centre, its anchor."""
    from app.models.character import get_character_profile
    prof = profile if profile is not None else (get_character_profile(name) or {})
    return resolve_place(name, prof.get("place"))


def resolve_place(name: str, pl: Any) -> Optional[Place]:
    """A profile ``place`` field (``{"id", "slot", "room_id"}``) resolved
    against today's inventory of the room ``name`` is in — the body of
    :func:`place_of`, for a caller that holds the field but no longer the
    profile it came from (``clear_pose_intent`` / :func:`release` have just
    cleared it when the character stands up). Same answer, same rules: None
    for a vanished marker, another room's id or a slot beyond the capacity."""
    if not isinstance(pl, dict) or not pl.get("id"):
        return None
    loc, room = where(name)
    for p in room_places(loc, room):
        slot = _held_slot(pl, p, room)
        if slot is not None:
            if slot == PAIR_SLOT:
                xz = centre_of(p)
            else:
                xz = p["slots"][slot] if slot < len(p["slots"]) else p["slots"][0]
            return dict(p, slot=slot, x=round(xz[0], 2), z=round(xz[1], 2))
    return None


# ── what the LLM is told ────────────────────────────────────────────────
_OFFER_MAX_LINES = 12
_ANYWHERE_MAX = 8             # poses on the "Anywhere here" line, defaults first
#: The preposition a prompt puts before a held place, per group — a group
#: nobody listed here (an admin-made place type) reads "at the". What is
#: named is the SURFACE, not the piece of furniture, so all of them read
#: "on": "on the couch", "on the bed", "on the floor". A group with
#: ``needs_place: false`` never appears here — its place is never named
#: (:func:`_named_place`).
_PREPOSITION = {"seat": "on", "lie": "on", "ground": "on"}


def _group_lines(location_id: str, room_id: str,
                 viewer: str) -> Tuple[List[str], Set[str]]:
    """One line per place — the markers of one prop collapse into a single
    line per group (a "2× Chair" is one row), room markers stay apart —
    busy ones by the names holding them, free ones with the poses of their
    group the free slots allow. A pair pose needs ``places`` free slots ON
    ONE place (a pair sits on one marker, never across two chairs), so the
    gate is the largest free count of any single place in the row, not the
    row's sum. A place that already holds a pair takes no second one (one
    pair per place), so it does not count towards that gate whatever is
    left on it. ``viewer`` never counts as an occupant: the block is written
    for them.

    Returns the lines AND the set of pose keys they already offered, so the
    "Anywhere here" line below can leave them out instead of naming the same
    pose twice. A row with no free slot offers nothing and therefore covers
    nothing — a standing spot that is taken must not stop anyone standing."""
    from app.core.pose_catalog import get_catalog, poses_in_group
    occ = occupancy(location_id, room_id, exclude=viewer)
    cat = get_catalog("pose")
    rows: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for p in room_places(location_id, room_id):
        key = (p["label"], p["group"]) if p["source"] == "prop" else (p["id"], p["group"])
        row = rows.setdefault(key, {"label": p["label"], "group": p["group"], "count": 0,
                                    "free": 0, "max_free": 0, "cap": 0, "who": []})
        taken = occ.get(p["id"], [])
        n_free = len(free_slots(p, taken))
        row["count"] += 1
        row["free"] += n_free
        row["max_free"] = max(row["max_free"], 0 if _has_pair(taken) else n_free)
        row["cap"] += p["capacity"]
        row["who"] += [n for n, _ in taken]
    lines: List[str] = []
    covered: Set[str] = set()
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
            elif row["max_free"] >= e["places"]:
                poses.append(f"{k} (with partner)")
            else:
                continue
            covered.add(k)
        state = ("free" if not row["who"]
                 else f"{row['free']} of {row['cap']} free, {', '.join(row['who'])} here")
        lines.append(f"- {head} ({state}): {', '.join(poses)}")
    return lines, covered


def room_offer(name: str, location_id: str, room_id: str) -> str:
    """The room's PLACE OFFER for ``name`` (plan § 5) — the block the chat,
    thought and tool prompts show::

        Places here:
        - Seat (occupied by Ann)
        - Lying place (free): lying, sleeping
        Anywhere here: standing, kneeling
        Also typical here: reading nooks

    Markers first (capped at ``_OFFER_MAX_LINES`` rows), then the poses that
    need no place at all — every pose of every group with
    ``needs_place: false``, each group's default first, then up to
    ``_ANYWHERE_MAX - 1`` more in catalog order and ``…and N more`` when
    there are more (they hold dozens of poses; the LLM may use any catalog
    key, the line is a reminder, not the menu) — then the room's free-text
    ``activity_hint`` as the tail.

    A pose a MARKER already offers is left out of "Anywhere here": a room
    with a standing spot used to repeat all 33 standing poses, once on the
    marker line and once here, which is 33 names of prompt for no new
    information. The marker line wins because it says something the other
    does not — WHERE. When every marker of the group is taken it offers
    nothing, so its poses come back here: a full room must not stop anyone
    standing.

    A room without markers still gets the last two lines; nothing at all
    yields ``""`` so a template can ``{% if %}`` it away."""
    from app.core.pose_catalog import get_catalog, poses_without_place
    from app.models.world import get_room_activity_hint
    if location_id and room_id:
        lines, covered = _group_lines(location_id, room_id, name)
    else:
        lines, covered = [], set()
    out: List[str] = []
    if lines:
        out.append("Places here:")
        out += lines[:_OFFER_MAX_LINES]
        if len(lines) > _OFFER_MAX_LINES:
            out.append(f"…and {len(lines) - _OFFER_MAX_LINES} more")
    cat = get_catalog("pose")
    anywhere = [k if cat[k]["solo"] else f"{k} (with partner)"
                for k in poses_without_place() if k not in covered]
    if anywhere:
        line = "Anywhere here: " + ", ".join(anywhere[:_ANYWHERE_MAX])
        if len(anywhere) > _ANYWHERE_MAX:
            line += f", …and {len(anywhere) - _ANYWHERE_MAX} more (any pose key works)"
        out.append(line)
    hint = get_room_activity_hint(location_id, room_id) if location_id else ""
    if hint:
        out.append(f"Also typical here: {hint}")
    return "\n".join(out)


def location_occupancy(location_id: str) -> Dict[str, Dict[str, List[Tuple[str, Any]]]]:
    """``{room_id: {place_id: [(name, slot), …]}}`` of the whole location
    from ONE census query (:func:`_census`) — for a caller that asks about
    every room (the NPC director), where per-room :func:`occupancy` would
    query once per room. Same validation as :func:`occupancy`."""
    out: Dict[str, Dict[str, List[Tuple[str, Any]]]] = {}
    if not location_id:
        return out
    for name, room, pl in _census(location_id, None):
        if not room or not isinstance(pl, dict):
            continue
        place = next((p for p in room_places(location_id, room) if p["id"] == pl.get("id")), None)
        slot = _held_slot(pl, place, room) if place else None
        if slot is not None:
            out.setdefault(room, {}).setdefault(place["id"], []).append((name, slot))
    return out


def room_offer_short(location_id: str, room_id: str,
                     occ: Optional[Dict[str, List[Tuple[str, Any]]]] = None) -> str:
    """Per group: free slots — ``"seat 2 free, bed 1 free"`` — what the NPC
    director needs to pick a room; ``""`` for a room without markers.
    ``occ`` is the room's precomputed occupancy (one entry of
    :func:`location_occupancy`); None reads it for this room alone."""
    if occ is None:
        occ = occupancy(location_id, room_id)
    free: Dict[str, int] = {}
    for p in room_places(location_id, room_id):
        free[p["group"]] = free.get(p["group"], 0) + len(free_slots(p, occ.get(p["id"], [])))
    return ", ".join(f"{g} {n} free" for g, n in free.items())


def _named_place(name: str) -> Optional[Place]:
    """The place ``name`` holds when it is worth naming — a place of a group
    that needs none is not: "standing, on the standing spot" tells a prompt
    nothing. The rule hangs on ``needs_place``, not on a group name."""
    from app.core.pose_catalog import needs_place
    p = place_of(name)
    return p if p and needs_place(p["group"]) else None


def place_label(name: str) -> str:
    """Label of the place ``name`` holds ("Seat", a prop's name) or ``""``
    (nothing held, or a place of a group that needs none)."""
    p = _named_place(name)
    return p["label"] if p else ""


def phrase_for(place: Place) -> str:
    """A place ALREADY in hand as a prompt reads it — ``"on the sofa"``,
    ``"on the bed"`` (:data:`_PREPOSITION` per group). For a caller that
    just read the place itself (``/play/others``) and would otherwise pay
    for a second roster pass through :func:`place_phrase`."""
    return f"{_PREPOSITION.get(place['group'], 'at')} the {place['label'].lower()}"


def place_phrase(name: str) -> str:
    """The held place as a prompt reads it — ``"on the sofa"``, ``"on the
    bed"`` (:func:`phrase_for`) — or ``""`` like :func:`place_label`. ONE
    phrase for the 2D scene prompt, the presence line and the player's
    Others panel."""
    p = _named_place(name)
    return phrase_for(p) if p else ""
