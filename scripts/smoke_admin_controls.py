#!/usr/bin/env python3
"""Smoke run for the four admin controls kept from the old web UI (DE-2/3/9).

Usage:
    ./.venv/bin/python scripts/smoke_admin_controls.py

Runs against a THROWAWAY storage directory — never touches a real world.
``STORAGE_DIR`` and ``ANIMATION_CLIPS_DIR`` are redirected BEFORE any app
module is imported, so ``app.server``'s own ``paths.init()`` lands in the
same temp dir.

The 2026-09-21 decision ("Punkt 3") deleted the old vanilla-UI outfit /
character / location routes EXCEPT four functions that have no replacement.
Each of the four gets a control in the React Game-Admin; this check pins the
BACKEND halves plus the route inventory the UI talks to.

Hand-derived expectations
=========================

[1] OUTFIT LOCK — ``GET/POST /characters/{n}/outfit-lock``.
    ``is_outfit_locked`` reads ``outfit_intent.locked``
    (app/models/character.py); ``set_outfit_locked`` writes it through
    ``_update_outfit_intent``. Expected, by reading the two functions:
      1a  a fresh character is NOT locked (OUTFIT_INTENT_DEFAULT: locked=False)
      1b  set True  -> is_outfit_locked() is True
      1c  set False -> is_outfit_locked() is False again
      1d  with the lock ON, ``outfit_compliance.apply_outfit_compliance``
          returns ``status == "locked"`` and ``intent_locked is True`` — step
          2 of its own documented algorithm ("intent.locked -> no-op"),
      1e  with the lock OFF the same call does NOT answer "locked"
          (it answers "ok" or "skipped" depending on the room's decency —
          the point is only that the lock is what produced 1d).
    1f  the write is serialized: ``_update_outfit_intent`` takes
        ``keyed_lock("character_profile", name)`` around read AND write.
        Checked by source inspection, because a race is not reproducible in a
        single-threaded assertion.

[2] GALLERY IMAGE -> ROOM — ``POST /world/locations/{id}/gallery/{img}/room``
    -> ``world_ops.assign_gallery_image_room`` ->
    ``world.set_gallery_image_room``. Reading those three:
      2a  assigning room "taproom" puts the file into
          ``get_gallery_image_rooms(loc)`` with value "taproom",
      2b  assigning "" REMOVES the entry entirely (the setter pops on an
          empty room id) — that is the "No room" case of the picker,
      2c  an unknown image file is a 404 (the core checks the file exists
          before touching the meta).

[3] PROMPT CHANGED — ``POST /world/locations/{id}/prompt-changed`` ->
    ``world_ops.set_location_prompt_changed``. Reading it:
      3a  value=True on the location sets ``location["prompt_changed"]``,
      3b  value=False clears it (the key is popped, so a fresh read has no
          ``prompt_changed`` at all),
      3c  the same pair works with a ``room_id`` for one room,
      3d  a room id that does not exist raises 404 (so the badge cannot
          silently clear nothing).

[4] PLACE A CHARACTER BY HAND — ``POST /characters/{n}/place-on-map`` ->
    ``character_ops.apply_place_on_map``. The function is an ADMIN TELEPORT
    and delegates to the public setters, so the expectations below are the
    setters' documented effects:
      4a  location + room are stored (``current_location`` == the target id,
          ``current_room`` == the room asked for),
      4b  a running journey is GONE afterwards: ``cancel_journey`` runs
          before the move, so neither ``journey`` nor ``movement_target``
          survives — including the case where the location does not change,
          which ``save_character_current_location`` alone would not clear,
      4c  the activity is reset on a real location change: "activity" here IS
          ``pose_key``/``pose_flavor`` (see ``get_effective_activity``), and
          ``save_character_current_location`` clears both,
      4d  without a room the target's ARRIVAL room is used — for a location
          without a declared entry room that is its first real room (the
          ground is the fallback), i.e. never the empty string,
      4e  the place is DISCOVERED: the target id lands in
          ``get_known_locations`` (``add_known_location``),
      4f  an unknown location is a 400, an unknown room of a known location
          is a 400,
      4g  a party FOLLOWER is refused with 409 + reason "party_follower";
          the same call with ``leave_party: True`` succeeds and the character
          is out of the party afterwards,
      4h  a SLEEPING character is placed and stays asleep (no wake-up: an
          admin move is not the character's own manual move),
      4i  the party LEADER is placed normally and its follower is PULLED
          along — that effect lives in ``save_character_current_location``
          (``_drag_party_followers_to_location``), which is exactly why the
          route uses the setter instead of writing the profile itself.

[5] ROUTE INVENTORY of ``app.server.app`` — the deleted surface is really
    gone and the four kept routes are really there:
      5a  every path in DELETED below is absent,
      5b  every path in KEPT below is present,
      5c  ``POST /characters/{n}/place-on-map`` carries ``require_admin`` in
          its dependant tree (writes under /characters are open to logged-in
          non-admins for their own characters; moving any figure across the
          world is not),
      5d  ``POST /characters/{n}/outfit-lock`` does NOT carry require_admin
          (the wardrobe switch is an ordinary character write),
      5e  ``"current-outfit"`` is gone from
          ``auth_dependency._PUBLIC_CHARACTER_SEGMENTS`` — the route it named
          no longer exists, and a stale entry there widens access for
          whatever route takes the name next.

    The 2026-09-21 decision ("Punkt 5") added three groups of SUPERSEDED
    duplicates to the same two lists (DE-7/DE-8/DE-10). Each is a second way
    into data that another route already owns, so what 5a/5b pin is the pair:
    the duplicate is gone AND the surviving one answers.
      * the six per-field prop-variant routes (``/dims``, ``/description``,
        ``/ground-offset``, ``/markers``, ``/seasons``, ``/face-targets``)
        wrote what ``POST /world/props/{id}/bulk`` writes, but without its
        "check everything before writing anything" rule.
        ``/area-defaults``, ``/slot-values``, ``/picture`` and ``/recopy``
        STAY — the Areas tab calls them and the batch does not carry them.
      * the eight unqualified prop MESH routes in ``routes/world.py`` were the
        shorthand for variant 1 of what ``…/variants/{i}/…`` does to the
        variant the admin has open. ``POST /world/props/{id}/generate`` stays
        (it APPENDS a variant, which is why the Props tab calls it
        unqualified).
      * ``/inventory/characters/{n}/{item}/use``, ``…/cast-self`` and
        ``…/drop`` bypassed the avatar and party checks that ``/play/use-item``,
        ``/play/cast`` and ``/play/drop`` make. Their siblings ``…/give``,
        ``…/pickup``, ``…/equip``, ``…/unequip`` and ``…/apply-outfit-set``
        stay.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="admctl-smoke-"))
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="admctl-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

import asyncio  # noqa: E402
import inspect  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from app.core import character_ops, world_ops  # noqa: E402
from app.core.outfit_compliance import apply_outfit_compliance  # noqa: E402
from app.core.party_engine import add_to_party, get_party_of  # noqa: E402
from app.models import world  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_current_location, get_character_current_room,
    get_character_profile, get_known_locations, is_character_sleeping,
    is_outfit_locked, save_character_profile, set_is_sleeping,
    set_outfit_locked)

FAILURES = []


def check(label, ok, detail=""):
    print(f"  [{'ok' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def raises_http(status, fn, *args, **kwargs):
    """True when ``fn`` raises an HTTPException with exactly ``status``."""
    try:
        result = fn(*args, **kwargs)
        if inspect.iscoroutine(result):
            asyncio.run(result)
    except HTTPException as e:
        return e.status_code == status, f"got {e.status_code}"
    except Exception as e:  # noqa: BLE001 — any other error is a failure
        return False, f"{type(e).__name__}: {e}"
    return False, "no exception"


def place(name, **body):
    return asyncio.run(character_ops.apply_place_on_map(name, body))


# ── the world ───────────────────────────────────────────────────────────────

INN = world.add_location("Smoke Inn", "A stone house at the fork.", rooms=[
    {"id": "taproom", "name": "Taproom", "description": "Benches."},
    {"id": "cellar", "name": "Cellar", "description": "Barrels."},
])
INN_ID = INN["id"]
MARKET = world.add_location("Smoke Market", "Stalls in the open.", rooms=[
    {"id": "stalls", "name": "Stalls", "description": "Awnings."},
])
MARKET_ID = MARKET["id"]

LOCKED_CHAR = "Smoke Lock"
MOVER = "Smoke Mover"
LEADER = "Smoke Leader"
FOLLOWER = "Smoke Follower"
SLEEPER = "Smoke Sleeper"
for _n in (LOCKED_CHAR, MOVER, LEADER, FOLLOWER, SLEEPER):
    save_character_profile(_n, {"character_name": _n,
                                "template": "human-default",
                                "current_location": INN_ID,
                                "current_room": "taproom"},
                           create_new=True)


# ── [1] outfit lock ─────────────────────────────────────────────────────────

print("\n[1] outfit lock")
check("1a fresh character is unlocked", is_outfit_locked(LOCKED_CHAR) is False)
set_outfit_locked(LOCKED_CHAR, True)
check("1b set True sticks", is_outfit_locked(LOCKED_CHAR) is True)
res_locked = apply_outfit_compliance(LOCKED_CHAR)
check("1d compliance answers 'locked'", res_locked.get("status") == "locked",
      f"status={res_locked.get('status')!r}")
check("1d intent_locked flag", res_locked.get("intent_locked") is True)
set_outfit_locked(LOCKED_CHAR, False)
check("1c set False sticks", is_outfit_locked(LOCKED_CHAR) is False)
res_open = apply_outfit_compliance(LOCKED_CHAR)
check("1e unlocked compliance is not 'locked'",
      res_open.get("status") != "locked", f"status={res_open.get('status')!r}")

_upd_src = inspect.getsource(
    sys.modules["app.models.character"]._update_outfit_intent)
check("1f the intent RMW is inside keyed_lock('character_profile')",
      'keyed_lock("character_profile", character_name)' in _upd_src)


# ── [2] gallery image -> room ───────────────────────────────────────────────

print("\n[2] gallery image -> room")
gdir = world.get_gallery_dir(INN_ID)
gdir.mkdir(parents=True, exist_ok=True)
IMG = "smoke_taproom.png"
(gdir / IMG).write_bytes(b"\x89PNG\r\n\x1a\n")

world_ops.assign_gallery_image_room(INN_ID, IMG, "taproom")
check("2a assigned to the room",
      world.get_gallery_image_rooms(INN_ID).get(IMG) == "taproom",
      repr(world.get_gallery_image_rooms(INN_ID)))
world_ops.assign_gallery_image_room(INN_ID, IMG, "")
check("2b empty room clears the assignment",
      IMG not in world.get_gallery_image_rooms(INN_ID),
      repr(world.get_gallery_image_rooms(INN_ID)))
ok, detail = raises_http(404, world_ops.assign_gallery_image_room,
                         INN_ID, "does_not_exist.png", "taproom")
check("2c unknown image -> 404", ok, detail)


# ── [3] prompt changed ──────────────────────────────────────────────────────

print("\n[3] prompt changed")
world_ops.set_location_prompt_changed(INN_ID, "", True)
check("3a set on the location",
      world.get_location_by_id(INN_ID).get("prompt_changed") is True)
world_ops.set_location_prompt_changed(INN_ID, "", False)
check("3b cleared on the location",
      "prompt_changed" not in world.get_location_by_id(INN_ID),
      repr(world.get_location_by_id(INN_ID).get("prompt_changed")))


def _room(loc_id, room_id):
    loc = world.get_location_by_id(loc_id) or {}
    return next((r for r in loc.get("rooms", []) if r.get("id") == room_id), {})


world_ops.set_location_prompt_changed(INN_ID, "taproom", True)
check("3c set on the room", _room(INN_ID, "taproom").get("prompt_changed") is True)
world_ops.set_location_prompt_changed(INN_ID, "taproom", False)
check("3c cleared on the room",
      "prompt_changed" not in _room(INN_ID, "taproom"))
ok, detail = raises_http(404, world_ops.set_location_prompt_changed,
                         INN_ID, "no_such_room", True)
check("3d unknown room -> 404", ok, detail)


# ── [4] place a character by hand ───────────────────────────────────────────

print("\n[4] place on the map")

# 4b/4c pre-state: a running journey and a pose, INSIDE the target location —
# so the journey survives only if nothing cancels it explicitly.
prof = get_character_profile(MOVER)
prof.update({
    "movement_target": MARKET_ID,
    "journey": {"target": MARKET_ID,
                "waypoints": [[0.0, 0.0, 0.0], [10.0, 0.0, 10.0]],
                "started_at_game": "Y0001-D001T12:00:00",
                "speed_m_s": 1.0, "entry_edge": None},
    "pose_key": "walking", "pose_flavor": "strolling to the market",
})
save_character_profile(MOVER, prof)

out = place(MOVER, location_id=INN_ID, current_room="cellar")
check("4a location stored", get_character_current_location(MOVER) == INN_ID,
      get_character_current_location(MOVER))
check("4a room stored", get_character_current_room(MOVER) == "cellar",
      get_character_current_room(MOVER))
prof = get_character_profile(MOVER)
check("4b journey cancelled although the location did not change",
      not isinstance(prof.get("journey"), dict)
      and not (prof.get("movement_target") or ""),
      f"journey={prof.get('journey')!r} target={prof.get('movement_target')!r}")
check("4a response names the room", out.get("current_room") == "cellar", repr(out))

# 4c: a REAL location change clears the pose = the activity.
prof = get_character_profile(MOVER)
prof.update({"pose_key": "sitting", "pose_flavor": "nursing a beer"})
save_character_profile(MOVER, prof)
place(MOVER, location_id=MARKET_ID, current_room="stalls")
prof = get_character_profile(MOVER)
check("4c activity reset on a location change",
      not prof.get("pose_key") and not prof.get("pose_flavor"),
      f"pose_key={prof.get('pose_key')!r} flavor={prof.get('pose_flavor')!r}")

# 4d: no room -> the arrival room, never empty.
place(MOVER, location_id=INN_ID)
check("4d no room -> arrival room",
      get_character_current_room(MOVER)
      == world.get_arrival_room_id(world.get_location_by_id(INN_ID)),
      get_character_current_room(MOVER))

# 4e: discovery.
check("4e target discovered", MARKET_ID in (get_known_locations(MOVER) or []),
      repr(get_known_locations(MOVER)))

# 4f: unknown location / unknown room.
ok, detail = raises_http(400, place, MOVER, location_id="no_such_place")
check("4f unknown location -> 400", ok, detail)
ok, detail = raises_http(400, place, MOVER, location_id=INN_ID,
                         current_room="no_such_room")
check("4f unknown room -> 400", ok, detail)
ok, detail = raises_http(400, place, MOVER)
check("4f missing location_id -> 400", ok, detail)

# 4g/4i: a party of two, both in the Inn.
place(LEADER, location_id=INN_ID, current_room="taproom")
place(FOLLOWER, location_id=INN_ID, current_room="taproom")
party_id = add_to_party(LEADER, FOLLOWER)
check("4g party created", bool(party_id), repr(party_id))

ok, detail = raises_http(409, place, FOLLOWER, location_id=MARKET_ID)
check("4g placing a follower -> 409", ok, detail)

# 4i: the LEADER moves and drags the follower along.
place(LEADER, location_id=MARKET_ID, current_room="stalls")
check("4i follower pulled along by the leader",
      get_character_current_location(FOLLOWER) == MARKET_ID,
      get_character_current_location(FOLLOWER))

# 4g second half: an explicit leave_party places the follower anyway.
place(FOLLOWER, location_id=INN_ID, current_room="cellar", leave_party=True)
check("4g leave_party places the follower",
      get_character_current_location(FOLLOWER) == INN_ID,
      get_character_current_location(FOLLOWER))
check("4g follower left the party", get_party_of(FOLLOWER) is None,
      repr(get_party_of(FOLLOWER)))

# 4h: a sleeping character is placed and stays asleep.
set_is_sleeping(SLEEPER, True)
check("4h pre-state: asleep", is_character_sleeping(SLEEPER) is True)
place(SLEEPER, location_id=MARKET_ID, current_room="stalls")
check("4h placed", get_character_current_location(SLEEPER) == MARKET_ID,
      get_character_current_location(SLEEPER))
check("4h still asleep", is_character_sleeping(SLEEPER) is True)


# ── [5] route inventory ─────────────────────────────────────────────────────

print("\n[5] route inventory")

DELETED = [
    ("GET", "/characters/{character_name}/generate-appearance"),
    ("GET", "/characters/{character_name}/decency-preference"),
    ("PUT", "/characters/{character_name}/decency-preference"),
    ("GET", "/characters/{character_name}/outfits"),
    ("POST", "/characters/{character_name}/outfits"),
    ("DELETE", "/characters/{character_name}/outfits"),
    ("GET", "/characters/{character_name}/outfits/{outfit_id}/image-prompt"),
    ("POST", "/characters/{character_name}/outfits/{outfit_id}/generate-image"),
    ("POST", "/characters/{character_name}/outfits/generate-all-images"),
    ("GET", "/characters/{character_name}/outfits/{image_filename}"),
    ("GET", "/characters/{character_name}/current-outfit"),
    ("POST", "/characters/{character_name}/current-outfit/refresh"),
    ("GET", "/characters/{character_name}/default-outfit"),
    ("POST", "/characters/{character_name}/default-outfit"),
    ("DELETE", "/characters/{character_name}/outfit-expression/cache"),
    ("GET", "/characters/{character_name}/active-conditions"),
    ("POST", "/characters/{character_name}/images/{image_filename}/comment"),
    ("POST", "/characters/{character_name}/cleanup-images"),
    ("POST", "/characters/skills/reload"),
    ("GET", "/characters/skills/list"),
    ("POST", "/characters/{character_name}/enhance-image-prompt"),
    ("POST", "/characters/{character_name}/rebuild-image-prompt"),
    ("POST", "/characters/{character_name}/images/{image_name}/suggest-animate-prompt"),
    ("POST", "/characters/{character_name}/images/{image_name}/animate"),
    ("POST", "/world/locations/{location_name}/gallery/{image_name}/toggle-background"),
    # DE-7 — the per-field variant routes, superseded by the batch save.
    ("POST", "/world/props/{prop_id}/variants/{index}/face-targets"),
    ("POST", "/world/props/{prop_id}/variants/{index}/seasons"),
    ("POST", "/world/props/{prop_id}/variants/{index}/dims"),
    ("POST", "/world/props/{prop_id}/variants/{index}/description"),
    ("POST", "/world/props/{prop_id}/variants/{index}/ground-offset"),
    ("POST", "/world/props/{prop_id}/variants/{index}/markers"),
    # DE-8 — the unqualified prop mesh routes (shorthand for variant 1).
    ("POST", "/world/props/{prop_id}/upload"),
    ("POST", "/world/props/{prop_id}/source"),
    ("GET", "/world/props/{prop_id}/models"),
    ("POST", "/world/props/{prop_id}/models/select"),
    ("POST", "/world/props/{prop_id}/models/shrink"),
    ("POST", "/world/props/{prop_id}/models/lod"),
    ("DELETE", "/world/props/{prop_id}/models"),
    ("GET", "/world/props/{prop_id}/models/files/{filename}"),
    # DE-10 — the inventory action routes, superseded by /play/*.
    ("POST", "/inventory/characters/{character_name}/{item_id}/use"),
    ("POST", "/inventory/characters/{character_name}/{item_id}/cast-self"),
    ("POST", "/inventory/characters/{character_name}/{item_id}/drop"),
]
KEPT = [
    ("GET", "/characters/{character_name}/outfit-lock"),
    ("POST", "/characters/{character_name}/outfit-lock"),
    ("POST", "/characters/{character_name}/place-on-map"),
    ("POST", "/characters/{character_name}/clear-expression-cache"),
    ("POST", "/instagram/post/{post_id}/animate"),
    ("POST", "/world/locations/{location_name}/gallery/{image_name}/room"),
    ("POST", "/world/locations/{location_id}/prompt-changed"),
    # The survivors of the three duplicate groups above (2026-09-21).
    ("POST", "/world/props/{prop_id}/bulk"),
    ("POST", "/world/props/{prop_id}/generate"),
    ("POST", "/world/props/{prop_id}/variants/{index}/area-defaults"),
    ("POST", "/world/props/{prop_id}/variants/{index}/slot-values"),
    ("POST", "/world/props/{prop_id}/variants/picture"),
    ("POST", "/world/props/{prop_id}/variants/{index}/recopy"),
    ("POST", "/world/props/{prop_id}/variants/{index}/upload"),
    ("POST", "/world/props/{prop_id}/variants/{index}/source"),
    ("GET", "/world/props/{prop_id}/variants/{index}/models"),
    ("POST", "/world/props/{prop_id}/variants/{index}/models/select"),
    ("POST", "/world/props/{prop_id}/variants/{index}/models/shrink"),
    ("POST", "/world/props/{prop_id}/variants/{index}/models/lod"),
    ("DELETE", "/world/props/{prop_id}/variants/{index}/models"),
    ("GET", "/world/props/{prop_id}/variants/{index}/models/files/{filename}"),
    ("POST", "/play/use-item"),
    ("POST", "/play/cast"),
    ("POST", "/play/drop"),
    ("POST", "/inventory/characters/{character_name}/{item_id}/give"),
    ("POST", "/inventory/characters/{character_name}/pickup"),
    ("POST", "/inventory/characters/{character_name}/equip"),
    ("POST", "/inventory/characters/{character_name}/unequip"),
    ("POST", "/inventory/characters/{character_name}/apply-outfit-set"),
]

import app.server as server  # noqa: E402
from fastapi.routing import _IncludedRouter  # noqa: E402


def walk_routes(routes, prefix=""):
    """Flatten the app's route tree.

    FastAPI wraps an ``include_router`` call in an ``_IncludedRouter`` node,
    so ``app.routes`` holds ~50 wrappers rather than the ~680 endpoints. The
    endpoints keep their own router prefix in ``path``; the include context
    adds one only when ``include_router(prefix=...)`` was used.
    """
    for r in routes:
        if isinstance(r, _IncludedRouter):
            ctx = getattr(r, "include_context", None)
            yield from walk_routes(r.original_router.routes,
                                   prefix + (getattr(ctx, "prefix", "") or ""))
        elif getattr(r, "path", None):
            yield prefix + r.path, r


PAIRS = set()
ROUTE_BY_PAIR = {}
for _path, _route in walk_routes(server.app.routes):
    for m in (getattr(_route, "methods", None) or ()):
        PAIRS.add((m, _path))
        ROUTE_BY_PAIR[(m, _path)] = _route
check("5 route tree flattened (sanity: > 500 endpoints)", len(PAIRS) > 500,
      f"{len(PAIRS)} method/path pairs")

missing = [p for p in KEPT if p not in PAIRS]
alive = [p for p in DELETED if p in PAIRS]
check(f"5a all {len(DELETED)} deleted routes are gone", not alive, repr(alive))
check(f"5b all {len(KEPT)} kept routes are present", not missing, repr(missing))


def dependency_names(route):
    """Every dependency callable name in the route's dependant tree."""
    names, stack = set(), [getattr(route, "dependant", None)]
    while stack:
        dep = stack.pop()
        if dep is None:
            continue
        call = getattr(dep, "call", None)
        if call is not None:
            names.add(getattr(call, "__name__", ""))
        stack.extend(getattr(dep, "dependencies", []) or [])
    return names


place_route = ROUTE_BY_PAIR.get(("POST", "/characters/{character_name}/place-on-map"))
lock_route = ROUTE_BY_PAIR.get(("POST", "/characters/{character_name}/outfit-lock"))
check("5c place-on-map depends on require_admin",
      place_route is not None and "require_admin" in dependency_names(place_route),
      repr(sorted(dependency_names(place_route))) if place_route else "route missing")
check("5d outfit-lock is not admin-gated",
      lock_route is not None and "require_admin" not in dependency_names(lock_route),
      repr(sorted(dependency_names(lock_route))) if lock_route else "route missing")

from app.core.auth_dependency import _PUBLIC_CHARACTER_SEGMENTS  # noqa: E402
check("5e 'current-outfit' is out of the public segment list",
      "current-outfit" not in _PUBLIC_CHARACTER_SEGMENTS,
      repr(sorted(_PUBLIC_CHARACTER_SEGMENTS)))


# ── summary ─────────────────────────────────────────────────────────────────

print(f"\nstorage: {STORAGE}")
if FAILURES:
    print(f"\nFAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
    sys.exit(1)
print("\nall checks passed")
