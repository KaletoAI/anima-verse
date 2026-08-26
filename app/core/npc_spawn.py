"""Automatic temporary NPCs: location slots, approach trigger, wanderers.

plan-npc-auto-spawn.md. Three mechanics, one queue task:

* **Slots** are AUTHORED ON TWO SURFACES: on a location (``npc_slots`` on the
  location) and, since spec § E3.2, on a painted terrain area
  (``meta.npc_slots``). Both carry the same slot object — a role, how many of
  them the place wants, a time window and a briefing — and both count the same
  way: whether a slot is filled is a PURE function of the declaring object and
  the slot TAGS of the living NPCs (:func:`missing_slots`), never a name match
  (feedback_no_name_resolution). What differs is where the NPC then STANDS: a
  location slot puts it in a room (or a circle around the place), an area slot
  makes the polygon itself its home (``npc_home`` kind ``area``).
* **The approach trigger** runs inside the accepted position report. It is
  deliberately the cheapest check in this module: geometry against the
  location snapshot the report already read plus the painted areas that
  declare slots, a per-object game-time cooldown and a queue submit. It counts
  nothing, reads no profile and calls no LLM — everything expensive happens
  later, in the worker.
* **Wanderers** are ordinary temporary NPCs travelling between known places
  over the normal journey engine. A scheduler tick keeps up to
  ``npc.wanderer_quota`` of them alive; arriving pools them (or turns them
  around, 50/50).

Both spawn kinds take a POOL hit of the same role before they run the
generation pipeline (see ``npc_pool``), and both stop at ``npc.max_alive``.
"""
from __future__ import annotations

import math
import random
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.game_time import GameDuration, GameTime
from app.core.log import get_logger
from app.core.npc_windows import normalize_when, slot_window_open
from app.core.timeutils import game_time

logger = get_logger("npc_spawn")

#: Queue task type of one spawn job. One job = one location's slots, or one
#: wanderer. The report path only ever SUBMITS this; the worker does the work.
TASK_TYPE = "npc_spawn"


# ---------------------------------------------------------------------------
# Config (defaults mirror app/core/config_schema.py section "npc")
# ---------------------------------------------------------------------------

def _cfg(key: str, default: Any) -> Any:
    from app.core import config
    value = config.get(f"npc.{key}", None)
    return default if value in (None, "") else value


def spawn_enabled() -> bool:
    return bool(_cfg("auto_spawn_enabled", True))


def max_alive() -> int:
    """Hard cap on LIVING temporary NPCs. Reached = no spawn until the sweep."""
    try:
        return max(0, int(_cfg("max_alive", 10)))
    except (TypeError, ValueError):
        return 10


def wanderer_quota() -> int:
    try:
        return max(0, int(_cfg("wanderer_quota", 3)))
    except (TypeError, ValueError):
        return 3


def spawn_radius_m() -> float:
    """How close the avatar has to come for a place to fill its slots."""
    try:
        return max(1.0, float(_cfg("spawn_radius_m", 150)))
    except (TypeError, ValueError):
        return 150.0


def spawn_cooldown() -> GameDuration:
    """Per-location cooldown in GAME minutes — a border dance must not spam."""
    try:
        minutes = max(0.0, float(_cfg("spawn_cooldown_game_minutes", 10)))
    except (TypeError, ValueError):
        minutes = 10.0
    return GameDuration.of(minutes=minutes)


def slot_ttl_hours() -> float:
    try:
        return max(0.0, float(_cfg("slot_ttl_game_hours", 12)))
    except (TypeError, ValueError):
        return 12.0


def wanderer_ttl_hours() -> float:
    try:
        return max(0.0, float(_cfg("wanderer_ttl_game_hours", 24)))
    except (TypeError, ValueError):
        return 24.0


def alive_npc_count() -> int:
    """Temporary NPCs the world is paying for right now.

    Living ones PLUS the ones the finish gate holds back: an NPC whose
    portrait and mesh are still rendering is already generated and will walk
    in by itself, so counting only the visible ones would let every tick spawn
    another one on top of it (``npc_assets.list_awaiting_assets``).
    """
    from app.core.npc_assets import list_awaiting_assets
    from app.models.character import list_temporary_npcs
    return len(list_temporary_npcs()) + len(list_awaiting_assets())


def cap_reached() -> bool:
    return alive_npc_count() >= max_alive()


# ---------------------------------------------------------------------------
# Slots — pure
# ---------------------------------------------------------------------------

def normalize_slot(raw: Any) -> Optional[Dict[str, Any]]:
    """One authored slot, cleaned. ``None`` when it names no role.

    The role is the slot's identity: it is what the NPC is tagged with and
    what a pool hit is matched on, so a slot without one cannot be counted,
    filled or recycled.

    ``when`` is the slot's time window (spec § E2, :mod:`app.core.npc_windows`):
    "" = always, ``night``/``day`` = the season's sun, ``HH:MM-HH:MM`` = a
    literal span in GAME time. An unusable value becomes "" — a typo must not
    leave a slot shut forever without saying so, hence the warning.

    ``radius_m`` is the slot's HOME AREA (spec § E3, :mod:`app.core.npc_home`):
    0 = the old room placement, anything above it means the NPC stands at a
    free point within that many metres of the place and roams there. It WINS
    over ``room`` — a slot cannot be both in the taproom and out in the woods.
    An unusable value becomes 0 with a warning, for the same reason ``when``
    does: this runs inside the location save, and a typo must not raise there.
    """
    if not isinstance(raw, dict):
        return None
    role = str(raw.get("role") or "").strip()
    if not role:
        return None

    when = normalize_when(raw.get("when"))
    if not when and str(raw.get("when") or "").strip():
        logger.warning("slot %r: unusable time window %r — treated as always",
                       role, raw.get("when"))

    def _count(key: str, fallback: int) -> int:
        # `json.loads` accepts `Infinity`, and `int(inf)` raises OverflowError
        # — not ValueError. This runs inside the location SAVE (see the radius
        # guard below), so an authored "Infinity" must become the fallback with
        # a warning, never an exception escaping through `normalize_slots` into
        # the save, `missing_slots` and `location_gap`.
        try:
            value = float(raw.get(key, fallback))
            if not math.isfinite(value):
                raise ValueError(f"{key} must be finite")
            return max(0, min(20, int(value)))
        except (TypeError, ValueError, OverflowError):
            logger.warning("slot %r: unusable %s %r — using %d", role, key,
                           raw.get(key), fallback)
            return fallback

    count_min = _count("count_min", 1)
    count_max = max(count_min, _count("count_max", max(1, count_min)))
    # `int(float("inf"))` raises OverflowError, not ValueError, and this runs
    # inside the location SAVE — an authored "inf" must become 0 with a
    # warning, never an exception escaping through `normalize_slots` into the
    # save, `missing_slots` and `location_gap`. Same guard as `npc_home.
    # circle_home`: only a finite number is a radius.
    try:
        raw_radius = float(raw.get("radius_m", 0) or 0)
        radius_m = max(0, int(raw_radius)) if math.isfinite(raw_radius) else 0
    except (TypeError, ValueError, OverflowError):
        radius_m = 0
    if not radius_m and str(raw.get("radius_m", "") or "").strip() not in ("", "0"):
        logger.warning("slot %r: unusable home radius %r — treated as none "
                       "(rooms as before)", role, raw.get("radius_m"))
    return {
        "role": role,
        "template": str(raw.get("template") or "").strip(),
        "count_min": count_min,
        "count_max": count_max,
        "briefing": str(raw.get("briefing") or "").strip(),
        "room": str(raw.get("room") or "").strip(),
        "when": when,
        "radius_m": radius_m,
    }


def normalize_slots(raw: Any) -> List[Dict[str, Any]]:
    """The authored ``npc_slots`` list, cleaned and de-duplicated by role."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for entry in (raw if isinstance(raw, list) else []):
        slot = normalize_slot(entry)
        if not slot:
            continue
        key = slot["role"].lower()
        if key in seen:
            continue          # one slot per role — the counts say "how many"
        seen.add(key)
        out.append(slot)
    return out


def missing_slots(location: Dict[str, Any],
                  held_roles: Sequence[str],
                  now: Optional[GameTime] = None) -> List[Dict[str, Any]]:
    """PURE: which slots of this location are unfilled, and by how many.

    ``held_roles`` is one entry per LIVING NPC that holds a slot of this
    location — its ``npc_slot_role`` tag, nothing else. A slot counts as
    filled at ``count_min``: the minimum is what the place must have, the
    maximum is the ceiling nothing may push it past — a slot standing at its
    maximum is never spawned into, which is what caps a place that was filled
    from somewhere else (a manual NPC, a wanderer that took a slot).

    The counts come out of :func:`normalize_slots`, so ``count_max`` is never
    below ``count_min`` here — an inverted pair is an authoring slip and the
    MINIMUM is the binding half of it (a place that says "at least three" gets
    three).

    A slot whose TIME WINDOW is shut wants nobody, however empty it stands
    (spec § E2) — the forest's robber slot is simply not a gap at noon. The
    moment is the only impure input, so it is a parameter: ``now=None`` reads
    the game clock, a caller that already holds one passes it in and keeps the
    function pure.

    Returns the slot dicts with an added ``needed`` count, missing slots only.
    """
    held: Dict[str, int] = {}
    for role in held_roles:
        key = str(role or "").strip().lower()
        if key:
            held[key] = held.get(key, 0) + 1

    moment = now if now is not None else game_time()
    out: List[Dict[str, Any]] = []
    for slot in normalize_slots(location.get("npc_slots")):
        if not slot_window_open(slot["when"], moment):
            continue
        have = held.get(slot["role"].lower(), 0)
        needed = max(0, slot["count_min"] - have)
        if needed and have < slot["count_max"]:
            out.append({**slot, "needed": min(needed, slot["count_max"] - have)})
    return out


def area_slots(area: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The authored slots of a PAINTED AREA (spec § E3.2), cleaned.

    They live in ``meta.npc_slots`` and are written through the very same
    sanitizer the location slots use (``terrain.sanitize_area``), so this is
    only the read side of the same shape.
    """
    return normalize_slots(((area or {}).get("meta") or {}).get("npc_slots"))


def _held_roles(stamp_key: str, wanted: str) -> List[str]:
    """The slot tags of every NPC whose ``stamp_key`` points at ``wanted``.

    One loop for both slot surfaces — see :func:`held_roles_at` for what the
    tag means and why the NPCs the finish gate holds back are counted too.
    """
    from app.core.npc_assets import list_awaiting_assets
    from app.models.character import get_character_profile, list_temporary_npcs
    wanted = (wanted or "").strip()
    if not wanted:
        return []
    roles: List[str] = []
    for name in list_temporary_npcs() + list_awaiting_assets():
        profile = get_character_profile(name) or {}
        if str(profile.get(stamp_key) or "").strip() != wanted:
            continue
        role = str(profile.get("npc_slot_role") or "").strip()
        if role:
            roles.append(role)
    return roles


def held_roles_at_area(area_id: str) -> List[str]:
    """The slot tags of every NPC that holds a slot of this painted AREA.

    The area's counterpart of :func:`held_roles_at`, over the profile stamp
    ``npc_slot_area``. The two stamps are exclusive — an NPC belongs either to
    a place or to a painted shape — so neither count can ever pick up the
    other's NPCs.
    """
    return _held_roles("npc_slot_area", area_id)


def held_roles_at(location_id: str) -> List[str]:
    """The slot tags of every NPC that holds a slot of this location.

    The TAG decides, not where the figure currently stands: an NPC that
    stepped into the next room still holds the bar's barkeeper slot. It stops
    holding it when it is deleted or pooled — both take it out of
    ``list_temporary_npcs``.

    A slot NPC the finish gate holds back HOLDS ITS SLOT TOO. It never went
    through ``pool_npc``, so its ``npc_slot_role``/``npc_slot_location`` are
    still on the profile, and it will walk in by itself as soon as its
    portrait and mesh exist. Counting only the living ones would let every
    spawn tick run the whole generation pipeline again for a slot that is
    already taken — once per cooldown, for as long as the render takes.
    """
    return _held_roles("npc_slot_location", location_id)


def location_gap(location: Dict[str, Any]) -> List[Dict[str, Any]]:
    """:func:`missing_slots` for a real location — the DB half of the pair."""
    return missing_slots(location, held_roles_at(location.get("id") or ""))


def area_gap(area: Dict[str, Any]) -> List[Dict[str, Any]]:
    """:func:`missing_slots` for a painted area — its half of the same pair."""
    return missing_slots({"npc_slots": area_slots(area)},
                         held_roles_at_area(area.get("id") or ""))


# ---------------------------------------------------------------------------
# The approach trigger — the only part that runs inside the report path
# ---------------------------------------------------------------------------

#: location id → game time of the last submitted spawn check. In-process on
#: purpose: it throttles THIS server's report path, and a restart is allowed
#: to look at every place once. GAME time, so a frozen world freezes the
#: cooldown with everything else.
_last_check: Dict[str, GameTime] = {}
_last_check_lock = threading.Lock()


def cooldown_ok(location_id: str, now: Optional[GameTime] = None) -> bool:
    """True when this location may be checked again — and MARKS it if so.

    Test and mark are one step because two walkers report at the same instant
    from two threadpool workers; a separate mark would let both through.
    """
    if not location_id:
        return False
    now = now or game_time()
    cooldown = spawn_cooldown()
    with _last_check_lock:
        last = _last_check.get(location_id)
        if last is not None and (now - last) < cooldown:
            return False
        _last_check[location_id] = now
    return True


#: The slot-bearing painted areas, reduced to what the approach check needs:
#: ``(stamp, [(area_id, polygon)])``. Painted areas are NOT part of the
#: location snapshot a position report already holds, so without this every
#: report at up to 4 Hz per walker would read AND JSON-parse every area in the
#: world just to find the handful that declare slots. The key is
#: ``terrain.area_stamps()`` — one cheap id/updated_at query — so any edit to
#: any area rebuilds it on the next report and a stale polygon is impossible.
_slot_areas_cache: Optional[Tuple[Dict[str, str], List[Tuple[str, Any]]]] = None
_slot_areas_lock = threading.Lock()


def reset_cooldowns() -> None:
    """Forget every cooldown (tests, and the admin's manual sweep)."""
    global _slot_areas_cache
    with _last_check_lock:
        _last_check.clear()
    with _slot_areas_lock:
        _slot_areas_cache = None


def _slot_areas() -> List[Tuple[str, Any]]:
    """``[(area_id, polygon)]`` of every painted area that declares NPC slots.

    Cached against :func:`terrain.area_stamps` — see :data:`_slot_areas_cache`.
    """
    global _slot_areas_cache
    from app.models.terrain import area_stamps, list_areas
    stamps = area_stamps()
    with _slot_areas_lock:
        cached = _slot_areas_cache
    if cached is not None and cached[0] == stamps:
        return cached[1]
    reduced = [(str(a.get("id") or ""), a.get("polygon"))
               for a in list_areas()
               if str(a.get("id") or "") and area_slots(a)]
    with _slot_areas_lock:
        _slot_areas_cache = (stamps, reduced)
    return reduced


def consider_point(avatar: str, x: float, z: float,
                   locations: Optional[Sequence[Dict[str, Any]]] = None,
                   areas: Optional[Sequence[Dict[str, Any]]] = None) -> List[str]:
    """The cheap check behind an accepted position report.

    Everything here is arithmetic over the location snapshot the report has
    already read plus one dict lookup per candidate: which placed locations
    within ``npc.spawn_radius_m`` DECLARE slots, and which of those are off
    cooldown. Whether their slots are actually unfilled is NOT decided here —
    that needs a profile read per living NPC, which is the worker's job.

    THE PAINTED AREAS ARE ASKED THE SAME QUESTION (spec § E3.2), only their
    geometry differs: ``polygon_distance`` is 0 anywhere INSIDE the shape, so
    "the avatar is standing in the wood" and "the avatar is within
    ``npc.spawn_radius_m`` of its edge" are one comparison.

    ``areas`` is the painted half of the same deal ``locations`` is: a caller
    that has just read the areas for its own reasons (``routes/play.py`` does,
    on the wilderness branch of every position report) hands them over instead
    of paying for a second read. Without it the check falls back to
    :func:`_slot_areas`, a stamp-keyed cache of the slot-bearing areas alone —
    a position report arrives up to four times a second per walker, and
    reading and JSON-parsing every painted area that often is what this fixes.

    Returns the ids a job was submitted for — location ids and area ids in one
    list (for the log and the smokes); never raises into the report path.
    """
    if not spawn_enabled():
        return []
    try:
        if locations is None:
            from app.models.world import list_locations
            locations = list_locations()
        radius = spawn_radius_m()
        submitted: List[str] = []
        now = game_time()
        for loc in locations or []:
            loc_id = str(loc.get("id") or "")
            if not loc_id or not normalize_slots(loc.get("npc_slots")):
                continue
            px, pz = loc.get("pos_x"), loc.get("pos_z")
            if px is None or pz is None:
                continue
            try:
                dist = math.hypot(float(px) - x, float(pz) - z)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(dist) or dist > radius:
                continue
            if not cooldown_ok(loc_id, now):
                continue
            if submit_spawn_job(location_id=loc_id, reason="slot",
                                triggered_by=avatar):
                submitted.append(loc_id)
        submitted.extend(_consider_areas(avatar, x, z, radius, now, areas))
        if submitted:
            logger.info("npc spawn check queued for %s (avatar %s)",
                        ", ".join(submitted), avatar)
        return submitted
    except Exception as e:  # noqa: BLE001
        # A walker must never be refused because of an NPC decision.
        logger.debug("consider_point failed: %s", e)
        return []


def _consider_areas(avatar: str, x: float, z: float, radius: float,
                    now: GameTime,
                    areas: Optional[Sequence[Dict[str, Any]]] = None
                    ) -> List[str]:
    """The painted half of :func:`consider_point` — areas with slots.

    ``areas``: the caller's already-read area list, or None for the
    stamp-keyed :func:`_slot_areas` cache. Either way what this loop walks is
    ``(id, polygon)`` pairs of SLOT-BEARING areas only.

    The cooldown key is namespaced (``area:<id>``) so an area and a location
    can never share a slot in ``_last_check``: both ids come from different
    generators, and a collision would silently mute one of them.
    """
    from app.core.world_geometry import polygon_distance

    if areas is None:
        candidates = _slot_areas()
    else:
        candidates = [(str(a.get("id") or ""), a.get("polygon"))
                      for a in areas if str(a.get("id") or "")
                      and area_slots(a)]

    submitted: List[str] = []
    for area_id, polygon in candidates:
        # 0 anywhere inside the shape, so this one comparison covers both
        # "standing in it" and "walking up to it".
        dist = polygon_distance(x, z, polygon)
        if not math.isfinite(dist) or dist > radius:
            continue
        if not cooldown_ok(f"area:{area_id}", now):
            continue
        if submit_spawn_job(area_id=area_id, reason="slot",
                            triggered_by=avatar):
            submitted.append(area_id)
    return submitted


def submit_spawn_job(location_id: str = "", reason: str = "slot",
                     triggered_by: str = "", area_id: str = "") -> str:
    """Queue one spawn job. Returns the task id ('' when deduplicated).

    A job is anchored either at a LOCATION or at a painted AREA — never at
    both, and a wanderer top-up at neither.
    """
    from app.core.task_queue import get_task_queue
    return get_task_queue().submit(
        TASK_TYPE,
        {"location_id": location_id, "area_id": area_id, "reason": reason,
         "triggered_by": triggered_by},
        queue_name="background", priority=30,
        # One pending job per location, per area (and one per wanderer
        # top-up): the dedup key is the agent_name, so a second report while
        # the first job still waits adds nothing. The area's key is
        # namespaced for the same reason the cooldown's is.
        agent_name=(location_id or (f"area:{area_id}" if area_id
                                    else f"wanderer:{reason}")),
        deduplicate=True)


# ---------------------------------------------------------------------------
# The worker side
# ---------------------------------------------------------------------------

def _handle_npc_spawn(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Queue handler: fill one location's slots, or start one wanderer."""
    if not spawn_enabled():
        return {"skipped": "disabled"}
    # A FROZEN WORLD SPAWNS NOBODY. The gate sits here and not in the report
    # path on purpose: this is the autonomous half, and asking the world-kv
    # table on every walking report would put a DB read into the one place
    # that must stay arithmetic. A job queued just before the freeze simply
    # answers "frozen" when the worker gets to it.
    try:
        from app.models.world import is_world_frozen
        if is_world_frozen():
            return {"skipped": "world frozen"}
    except Exception:  # noqa: BLE001
        pass
    reason = str(payload.get("reason") or "slot")
    if reason == "wanderer":
        return spawn_wanderer()
    area_id = str(payload.get("area_id") or "")
    if area_id:
        return fill_area_slots(area_id)
    location_id = str(payload.get("location_id") or "")
    return fill_location_slots(location_id)


def register_npc_spawn_handler() -> None:
    from app.core.task_queue import get_task_queue
    get_task_queue().register_handler(TASK_TYPE, _handle_npc_spawn)


def fill_location_slots(location_id: str) -> Dict[str, Any]:
    """Spawn what the location's slots are missing, one NPC per missing count.

    The hard cap is checked before EVERY single spawn, not once per job: one
    job may fill several slots, and the cap is about the world, not about this
    location.
    """
    from app.models.world import get_location_by_id

    location = get_location_by_id(location_id) or {}
    if not location:
        return {"skipped": "unknown location", "location_id": location_id}
    gaps = location_gap(location)
    if not gaps:
        return {"filled": 0, "location_id": location_id}

    filled: List[str] = []
    for slot in gaps:
        for _ in range(int(slot.get("needed") or 0)):
            if cap_reached():
                logger.info("npc cap %d reached — no spawn at %s",
                            max_alive(), location_id)
                return {"filled": len(filled), "spawned": filled,
                        "location_id": location_id, "capped": True}
            name = spawn_for_slot(location, slot)
            if name:
                filled.append(name)
    return {"filled": len(filled), "spawned": filled, "location_id": location_id}


def fill_area_slots(area_id: str) -> Dict[str, Any]:
    """The area's half of :func:`fill_location_slots` (spec § E3.2).

    Same rules, one origin further out: the painted shape is both what
    declares the slot and where the NPC lives, so there is no room to place
    into and no location id on the profile at all.
    """
    from app.models.terrain import get_area

    area = get_area(area_id)
    if not area:
        return {"skipped": "unknown area", "area_id": area_id}
    gaps = area_gap(area)
    if not gaps:
        return {"filled": 0, "area_id": area_id}

    filled: List[str] = []
    for slot in gaps:
        for _ in range(int(slot.get("needed") or 0)):
            if cap_reached():
                logger.info("npc cap %d reached — no spawn in %s",
                            max_alive(), area_id)
                return {"filled": len(filled), "spawned": filled,
                        "area_id": area_id, "capped": True}
            name = spawn_for_slot(area, slot, kind="area")
            if name:
                filled.append(name)
    return {"filled": len(filled), "spawned": filled, "area_id": area_id}


def _slot_briefing(location: Dict[str, Any], slot: Dict[str, Any]) -> str:
    """The generator's briefing: the slot's own text plus where it stands."""
    parts = [slot.get("briefing") or f"a {slot['role']}"]
    place = str(location.get("name") or "").strip()
    if place:
        parts.append(f"They are the {slot['role']} at {place}.")
    desc = str(location.get("description") or "").strip()
    if desc:
        parts.append(desc)
    return "\n\n".join(p for p in parts if p)


def _area_briefing(area: Dict[str, Any], slot: Dict[str, Any]) -> str:
    """The same briefing for an AREA slot — the LABEL takes the place's role.

    A painted area has no name and no description of its own beyond the two
    things an author gave it: the label and the terrain kind it is painted in.
    Both go into the briefing, because the generator has nothing else to build
    a person out of — "the poacher of the Hunting Ground, open woodland".
    """
    label = str(((area or {}).get("meta") or {}).get("label") or "").strip()
    parts = [slot.get("briefing") or f"a {slot['role']}"]
    if label:
        parts.append(f"They are the {slot['role']} of {label}, "
                     f"out in the open — no house, no room.")
    kind = str((area or {}).get("kind") or "").strip()
    if kind:
        parts.append(f"The ground there is {kind.replace('_', ' ')}.")
    return "\n\n".join(p for p in parts if p)


def _area_place_labels(area: Dict[str, Any]) -> Tuple[str, str]:
    """What the NPC schema calls "Location" and "Room" for an AREA slot.

    The schema header is two lines of prose the generator reads as "where this
    NPC belongs" (``shared/world_dev_schemas/npc_character.md``). An area
    fills them with the label and with an explicit "no room" — spelled out
    rather than left blank, so the model does not invent an interior for an
    NPC that lives on open ground.
    """
    label = str(((area or {}).get("meta") or {}).get("label") or "").strip()
    kind = str((area or {}).get("kind") or "").strip().replace("_", " ")
    place = f"{label} — open {kind} ground" if kind else label
    return (place or "(an unnamed area)",
            "(none — this NPC stands outdoors, not in a building)")


def spawn_for_slot(place: Dict[str, Any], slot: Dict[str, Any],
                   kind: str = "location") -> str:
    """POOL FIRST, pipeline second. Returns the NPC's name, or ''.

    The pool hit is what makes a recycled world cheap: a finished character
    sheet of the same role goes back on the map with no LLM turn at all. Only
    when the pool has nobody for this role does the three-stage pipeline run.

    ``kind`` says what ``place`` is — a LOCATION (the default: room or circle
    placement, ``npc_slot_location``) or a painted AREA (``npc_home`` of kind
    ``area``, ``npc_slot_area``, no room at all). Everything that differs
    between the two is decided right here, once, and handed on as ordinary
    arguments; neither the pool return nor the generator learns a second rule.
    """
    from app.core.npc_home import area_home
    from app.core.npc_ops import generate_npc_blocking
    from app.core.npc_pool import revive_from_pool, take_from_pool
    from app.models.world import get_arrival_room_id

    role = slot["role"]
    ttl = slot_ttl_hours()
    if kind == "area":
        where = str(place.get("id") or "")
        location_id, room, radius_m = "", "", 0
        home = area_home(where)
        briefing = _area_briefing(place, slot)
        labels = _area_place_labels(place)
    else:
        where = location_id = str(place.get("id") or "")
        # A slot without an authored room does NOT mean "roomless": since the
        # ground migration everybody standing in a location stands in one of
        # its rooms, and an NPC written without one is invisible to every
        # room-based gate (presence, addressees, room entry). The fallback is
        # THE arrival rule every other arrival path uses.
        room = slot.get("room") or get_arrival_room_id(place)
        radius_m = int(slot.get("radius_m") or 0)
        home = None
        briefing = _slot_briefing(place, slot)
        labels = None

    pooled = take_from_pool(role, template=slot.get("template") or "")
    if pooled and revive_from_pool(pooled, location_id, room, ttl_hours=ttl,
                                   slot_role=role,
                                   briefing=slot.get("briefing") or "",
                                   radius_m=radius_m, home=home):
        logger.info("Slot '%s' at %s filled from the pool: %s",
                    role, where, pooled)
        return pooled

    result = generate_npc_blocking(
        briefing=briefing, location_id=location_id,
        room_id=room, ttl_hours=ttl, template=slot.get("template") or "",
        slot_role=role, created_by="npc_slot", radius_m=radius_m,
        home=home, place_labels=labels)
    if not result.get("ok"):
        logger.warning("Slot '%s' at %s not filled: %s", role, where,
                       result.get("error"))
        return ""
    logger.info("Slot '%s' at %s filled by the pipeline: %s", role,
                where, result.get("character"))
    return str(result.get("character") or "")


# ---------------------------------------------------------------------------
# Wanderers
# ---------------------------------------------------------------------------

def _placed_locations() -> List[Dict[str, Any]]:
    """Locations a wanderer can walk to: placed, with an area to arrive in."""
    from app.core.world_geometry import effective_boundary
    from app.models.world import list_locations
    out: List[Dict[str, Any]] = []
    for loc in list_locations():
        if loc.get("pos_x") is None or loc.get("pos_z") is None:
            continue
        try:
            if effective_boundary(loc) is None:
                continue
        except Exception:  # noqa: BLE001
            continue
        out.append(loc)
    return out


def list_wanderers() -> List[str]:
    """The wanderers ON THE ROAD — living ones, the arrivals to settle."""
    from app.models.character import get_character_profile, list_temporary_npcs
    return [n for n in list_temporary_npcs()
            if (get_character_profile(n) or {}).get("npc_wanderer")]


def wanderer_count() -> int:
    """Wanderers against the quota: on the road plus waiting for their assets.

    Deliberately not part of :func:`list_wanderers` — that list drives
    ``_settle_wanderer``, and settling an NPC that has not set off yet would
    pool it and throw its route away.
    """
    from app.core.npc_assets import list_awaiting_assets
    from app.models.character import get_character_profile
    held = [n for n in list_awaiting_assets()
            if (get_character_profile(n) or {}).get("npc_wanderer")]
    return len(list_wanderers()) + len(held)


def wanderer_tick() -> Dict[str, Any]:
    """Keep the road populated: settle arrivals, then top the quota up.

    The tick itself never generates: a spawn is a queue job, so a slow LLM
    turn cannot hold up the world-admin tick that calls this.
    """
    if not spawn_enabled():
        return {"skipped": "disabled"}
    quota = wanderer_quota()
    arrived: List[str] = []
    for name in list_wanderers():
        try:
            if _settle_wanderer(name):
                arrived.append(name)
        except Exception as e:  # noqa: BLE001
            logger.debug("wanderer %s: %s", name, e)

    alive = list_wanderers()
    queued = 0
    if wanderer_count() < quota and not cap_reached():
        # ONE per tick. The quota is a target, not a burst: three pipeline
        # runs at once would occupy the chat provider for minutes, and the
        # tick comes back in five.
        if submit_spawn_job(reason="wanderer"):
            queued = 1
    return {"wanderers": len(alive), "quota": quota, "arrived": arrived,
            "queued": queued}


def _settle_wanderer(name: str) -> bool:
    """One wanderer's arrival. True when it arrived (pooled or turned around).

    Still walking = nothing to do. The journey itself belongs to the travel
    engine; this only reacts to it being over.

    An NPC an avatar is TALKING TO right now is left standing, whatever the
    arrival would otherwise decide — the same rule the action tick and the
    window sweep use (``npc_actions._in_chat``, the AgentLoop's HOT window).
    Without it the tick ends the arrival on the spot: it either turns the
    wanderer around and sends it off mid-sentence, or pools it, which deletes
    the very character the player is writing to. It settles on a later tick,
    once the conversation has cooled.
    """
    from app.core.npc_actions import _in_chat
    from app.models.character import (get_character_current_location,
                                      get_character_profile,
                                      save_character_profile)
    profile = get_character_profile(name) or {}
    if profile.get("journey"):
        return False                      # still on the road
    if _in_chat(name):
        logger.info("Wanderer '%s' stays: an avatar is talking to it", name)
        return False
    target = str(profile.get("wander_target") or "").strip()
    here = (get_character_current_location(name) or "").strip()
    if target and here != target:
        # The journey ended without arriving (cancelled, blocked). Try once
        # more; a second failure pools it in the next tick through the branch
        # below, because the retry clears the target when it cannot start.
        if _send_wanderer(name, target):
            return False

    from app.core.npc_pool import pool_npc
    origin = str(profile.get("wander_origin") or "").strip()
    if origin and origin != here and random.random() < 0.5:
        # Turn around instead of vanishing (§ 5, 50/50).
        profile["wander_target"] = origin
        profile["wander_origin"] = here
        save_character_profile(name, profile)
        if _send_wanderer(name, origin):
            logger.info("Wanderer '%s' turns around towards %s", name, origin)
            return True
    pool_npc(name, reason="wanderer arrived")
    return True


def _send_wanderer(name: str, target_id: str) -> bool:
    """Start the journey over the ORDINARY engine. True when it is walking."""
    from app.core.travel_engine import start_journey
    from app.models.character import add_known_location
    if not target_id:
        return False
    # A traveller knows where they are going — the knowledge gate in
    # start_journey is about characters discovering the world, and a wanderer
    # is created with its destination in mind.
    add_known_location(name, target_id)
    journey, reason = start_journey(name, target_id)
    if journey:
        return True
    logger.info("Wanderer '%s' cannot travel to %s: %s", name, target_id, reason)
    return False


def spawn_wanderer() -> Dict[str, Any]:
    """Create (or recycle) one wanderer and send it on its way."""
    from app.core.npc_assets import is_awaiting_assets
    from app.core.npc_ops import generate_npc_blocking
    from app.core.npc_pool import revive_from_pool, take_from_pool

    if cap_reached():
        return {"skipped": "cap", "alive": alive_npc_count()}
    if wanderer_count() >= wanderer_quota():
        return {"skipped": "quota"}
    places = _placed_locations()
    if len(places) < 2:
        return {"skipped": "fewer than two placed locations"}

    origin, target = random.sample(places, 2)
    origin_id = str(origin.get("id") or "")
    target_id = str(target.get("id") or "")
    ttl = wanderer_ttl_hours()

    # A wanderer holds no slot, so ANY pooled NPC fits — that is the whole
    # point of the pool: a face the world has seen before is walking the road
    # again, in a different place.
    name = take_from_pool("")
    if name and not revive_from_pool(name, origin_id, "", ttl_hours=ttl,
                                     wanderer=True, wander_target=target_id):
        name = None
    if not name:
        briefing = (
            f"A traveller passing through, on the road from "
            f"{origin.get('name') or origin_id} to "
            f"{target.get('name') or target_id}. Somebody with a reason to be "
            f"walking and a few words about the road.")
        result = generate_npc_blocking(briefing=briefing,
                                       location_id=origin_id, ttl_hours=ttl,
                                       wanderer=True, wander_target=target_id,
                                       created_by="npc_wanderer")
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error")}
        name = str(result.get("character") or "")
    if not name:
        return {"ok": False, "error": "no wanderer"}

    # THE ROAD IS ALREADY STAMPED — both paths above put origin and target on
    # the profile before they asked for the placement, because the finish gate
    # may have held this wanderer back. A held NPC stands nowhere, so starting
    # its journey here would only fail with "no route"; the assets job places
    # it AND sends it off once its portrait and mesh exist.
    if is_awaiting_assets(name):
        logger.info("Wanderer '%s' waits for its assets before setting off "
                    "from %s to %s", name, origin_id, target_id)
        return {"ok": True, "character": name, "from": origin_id,
                "to": target_id, "walking": False, "held_for_assets": True}

    walking = _send_wanderer(name, target_id)
    logger.info("Wanderer '%s' set off from %s to %s (%s)", name, origin_id,
                target_id, "walking" if walking else "stuck")
    return {"ok": True, "character": name, "from": origin_id, "to": target_id,
            "walking": walking, "held_for_assets": False}
