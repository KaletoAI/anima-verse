"""Automatic temporary NPCs: location slots, approach trigger, wanderers.

plan-npc-auto-spawn.md. Three mechanics, one queue task:

* **Slots** are location data (``npc_slots`` on the location): a role, how many
  of them a place wants, and a briefing the generator gets. Whether a slot is
  filled is a PURE function of the location and the slot TAGS of the living
  NPCs (:func:`missing_slots`) — never a name match
  (feedback_no_name_resolution).
* **The approach trigger** runs inside the accepted position report. It is
  deliberately the cheapest check in this module: geometry against the
  location snapshot the report already read, a per-location game-time cooldown
  and a queue submit. It counts nothing, reads no profile and calls no LLM —
  everything expensive happens later, in the worker.
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
from typing import Any, Dict, List, Optional, Sequence

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
        try:
            return max(0, min(20, int(raw.get(key, fallback))))
        except (TypeError, ValueError):
            return fallback

    count_min = _count("count_min", 1)
    count_max = max(count_min, _count("count_max", max(1, count_min)))
    try:
        radius_m = max(0, int(float(raw.get("radius_m", 0) or 0)))
    except (TypeError, ValueError):
        radius_m = 0
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
    from app.core.npc_assets import list_awaiting_assets
    from app.models.character import get_character_profile, list_temporary_npcs
    wanted = (location_id or "").strip()
    roles: List[str] = []
    for name in list_temporary_npcs() + list_awaiting_assets():
        profile = get_character_profile(name) or {}
        if str(profile.get("npc_slot_location") or "").strip() != wanted:
            continue
        role = str(profile.get("npc_slot_role") or "").strip()
        if role:
            roles.append(role)
    return roles


def location_gap(location: Dict[str, Any]) -> List[Dict[str, Any]]:
    """:func:`missing_slots` for a real location — the DB half of the pair."""
    return missing_slots(location, held_roles_at(location.get("id") or ""))


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


def reset_cooldowns() -> None:
    """Forget every cooldown (tests, and the admin's manual sweep)."""
    with _last_check_lock:
        _last_check.clear()


def consider_point(avatar: str, x: float, z: float,
                   locations: Optional[Sequence[Dict[str, Any]]] = None) -> List[str]:
    """The cheap check behind an accepted position report.

    Everything here is arithmetic over the location snapshot the report has
    already read plus one dict lookup per candidate: which placed locations
    within ``npc.spawn_radius_m`` DECLARE slots, and which of those are off
    cooldown. Whether their slots are actually unfilled is NOT decided here —
    that needs a profile read per living NPC, which is the worker's job.

    Returns the location ids a job was submitted for (for the log and the
    smokes); never raises into the report path.
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
        if submitted:
            logger.info("npc spawn check queued for %s (avatar %s)",
                        ", ".join(submitted), avatar)
        return submitted
    except Exception as e:  # noqa: BLE001
        # A walker must never be refused because of an NPC decision.
        logger.debug("consider_point failed: %s", e)
        return []


def submit_spawn_job(location_id: str = "", reason: str = "slot",
                     triggered_by: str = "") -> str:
    """Queue one spawn job. Returns the task id ('' when deduplicated)."""
    from app.core.task_queue import get_task_queue
    return get_task_queue().submit(
        TASK_TYPE,
        {"location_id": location_id, "reason": reason,
         "triggered_by": triggered_by},
        queue_name="background", priority=30,
        # One pending job per location (and one per wanderer top-up): the
        # dedup key is the agent_name, so a second report while the first job
        # still waits adds nothing.
        agent_name=location_id or f"wanderer:{reason}", deduplicate=True)


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


def spawn_for_slot(location: Dict[str, Any],
                   slot: Dict[str, Any]) -> str:
    """POOL FIRST, pipeline second. Returns the NPC's name, or ''.

    The pool hit is what makes a recycled world cheap: a finished character
    sheet of the same role goes back on the map with no LLM turn at all. Only
    when the pool has nobody for this role does the three-stage pipeline run.
    """
    from app.core.npc_ops import generate_npc_blocking
    from app.core.npc_pool import revive_from_pool, take_from_pool

    location_id = str(location.get("id") or "")
    role = slot["role"]
    room = slot.get("room") or ""
    radius_m = int(slot.get("radius_m") or 0)
    ttl = slot_ttl_hours()

    pooled = take_from_pool(role, template=slot.get("template") or "")
    if pooled and revive_from_pool(pooled, location_id, room, ttl_hours=ttl,
                                   slot_role=role,
                                   briefing=slot.get("briefing") or "",
                                   radius_m=radius_m):
        logger.info("Slot '%s' at %s filled from the pool: %s",
                    role, location_id, pooled)
        return pooled

    result = generate_npc_blocking(
        briefing=_slot_briefing(location, slot), location_id=location_id,
        room_id=room, ttl_hours=ttl, template=slot.get("template") or "",
        slot_role=role, created_by="npc_slot", radius_m=radius_m)
    if not result.get("ok"):
        logger.warning("Slot '%s' at %s not filled: %s", role, location_id,
                       result.get("error"))
        return ""
    logger.info("Slot '%s' at %s filled by the pipeline: %s", role,
                location_id, result.get("character"))
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
    """
    from app.models.character import (get_character_current_location,
                                      get_character_profile,
                                      save_character_profile)
    profile = get_character_profile(name) or {}
    if profile.get("journey"):
        return False                      # still on the road
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
