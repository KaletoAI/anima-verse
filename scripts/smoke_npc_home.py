#!/usr/bin/env python3
"""Smoke run for the temporary-NPC HOME AREA, stage 1 — the circle
(spec-npc-heimat-zeitfenster § E3.1).

Throwaway storage, throwaway world DB — no server, no real world is touched
and no LLM is called: the action turn is a fake that hands back a canned
string, so what is measured is the GEOMETRY, the PLACEMENT and the
APPLICATION, not a model.

Two stubs, both so the run stays offline:
  * ``app.core.embedding.embed`` returns None — ``set_pose_intent`` then
    resolves its catalog key by plain alias equality instead of downloading
    the built-in embedding model (same rule the pose catalog states for a
    missing backend).
  * nothing else. The nav grid, the travel engine, ``force_set_status``, the
    terrain query and the cooldown clock all run for real.

THE RULE, by hand — a slot with ``radius_m > 0`` gives its NPC a HOME CIRCLE
instead of a room: the NPC is placed at a random passable point inside the
circle, carries ``npc_home`` on its profile, and its action turn answers only
what it is DOING while the tick walks it to the next point of that circle.

── the fixture world (all coordinates in metres) ──────────────────────────

  terrain  grass      x −250…250, z −150…150   (passable, speed_factor 1.0)
           deep_water x  −30…0,   z  −30…30    (passable: false)
           deep_water x  170…230, z   70…130   (passable: false)

  Old Mill        pos (0, 0),     footprint 6 m  → x −3…3,    z −3…3
  Toolshed        pos (15, 0),    footprint 8 m  → x 11…19,   z −4…4
  Forest Clearing pos (100, 0),   NO boundary    → covers no point at all
  Great Hall      pos (−100, 0),  footprint 60 m → x −130…−70, z −30…30
  Sunken Post     pos (200, 100), NO boundary    → sits in the second lake

``grass``/``deep_water`` are the shared terrain types (``shared/terrain/
types.json``): grass is passable, deep_water is not.

── hand-derived expectations ──────────────────────────────────────────────

  (a) ``random_point`` NEVER LEAVES THE CIRCLE AND NEVER PICKS GROUND THE
      NPC CANNOT STAND ON. For the Old Mill circle (centre (0, 0), radius
      25) every one of 200 draws satisfies all three:

        1. |p − (0, 0)| ≤ 25.0 — it is a point of THIS circle;
        2. it is not inside the Toolshed's footprint. The shed lies fully
           inside the circle (11…19 ≤ 25) and is a DIFFERENT place: a point
           journey runs no entry gate at its goal, so an NPC roaming the
           mill's yard must never be sent into the neighbour's shed;
        3. ``x ≥ 0`` OR the point lies inside the Old Mill's own footprint.
           The lake covers x −30…0 of the circle, so out in the open only
           x ≥ 0 is walkable — but THE PLACE WINS inside a footprint,
           exactly as it does at a journey goal
           (``travel_engine.start_journey_to_point``): the mill brings its
           own floor, so its 6 m footprint stays legal even where the
           painted water reaches into it (x −3…0).

      ``min_dist_from=(0, 0)`` additionally rejects everything closer than
      ``MIN_ROAM_DIST_M`` (3.0 m) to that point — the guard that keeps the
      action tick from starting a one-step journey to where the NPC already
      stands. 200 draws, all ≥ 3.0 m away.

      A circle that is ENTIRELY unwalkable answers None: Sunken Post's
      circle (centre (200, 100), radius 20) lies inside the second lake and
      the place has no footprint of its own to save it, so all 40 attempts
      are rejected.

  (b) PLACEMENT. ``revive_from_pool(..., radius_m=25)`` puts the NPC at a
      point instead of into a room:
        * ``get_character_pos`` is inside the circle;
        * ``npc_home`` is stamped as
          {"kind": "circle", "location_id": <mill>, "cx": 0.0, "cz": 0.0,
           "radius_m": 25.0};
        * the status is '' (it is in the world);
        * ``current_location`` is DERIVED from the point, never handed in —
          it equals whatever ``location_at_point`` answers for the pos.
      The derivation is pinned at both ends with two circles whose answer is
      certain:
        * Great Hall, radius 5 around (−100, 0): the whole circle lies
          inside the hall's 60 m footprint → ``current_location`` is the
          hall;
        * Forest Clearing, radius 20 around (100, 0): the place has no
          boundary at all, so no point of that circle lies in any location →
          ``current_location`` is ''.
      ``radius_m=0`` is the old behaviour unchanged: location + room are
      written, and NO ``npc_home`` is stamped.

  (c) POOLING FORGETS THE HOME. ``pool_npc`` pops ``npc_home`` with the
      other slot stamps — a recycled sheet must not carry yesterday's forest
      into the next town.

  (d) THE ACTION TURN HAS A SECOND VARIANT. An NPC with ``npc_home`` is
      asked ONLY what it is doing (``{"activity": "…"}`` — there is no room
      list and no room in the answer). The application is the activity plus
      a WALK: ``force_set_status`` writes the sentence, and a point journey
      to a fresh ``random_point`` of the same circle is started.
        * the result is {"name", "room": "", "activity", "moved": True};
        * ``profile["journey"]["target"]`` is '' and its ``target_point``
          lies inside the circle (that is what a point journey is);
        * no room was written — the NPC stands in the open, ``current_room``
          stays '';
        * the prompt carries the home description ("within 20 m of Forest
          Clearing") and NOT the room list of the room variant.
      The next tick during that journey finds no candidate — the existing
      journey guard, proven with the cooldown stamp REMOVED so the journey
      is the only possible reason.

  (e) A PARTY FOLLOWER DOES NOT ROAM. A follower is dragged along by its
      leader and loses its own travel; the party engine cancels a follower's
      journey at the join. So a roaming NPC that is a follower is no
      candidate, while its leader — same place, same kind of home — is.

  (f) NOTHING ELSE CHANGED. An NPC with neither a location nor a home still
      yields ``prompt_vars`` == {} (there is nothing to ask it), and the
      slot schema carries ``radius_m`` as an int ≥ 0 with default 0.

  (g) THE TEMPLATE RENDERS UNDER StrictUndefined — BOTH branches, with
      exactly the variable sets the module passes. A placeholder one branch
      forgets is a crash in production, not a warning.

Usage:  ./.venv/bin/python scripts/smoke_npc_home.py
"""
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="npchome-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="npchome-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()
from app.core.task_queue import get_task_queue  # noqa: E402
get_task_queue()._started = True

from app.core import embedding, npc_actions, npc_home, npc_spawn  # noqa: E402
from app.core.npc_ops import apply_npc  # noqa: E402
from app.core.npc_pool import pool_npc, revive_from_pool  # noqa: E402
from app.core.party_engine import add_to_party  # noqa: E402
from app.core.prompt_templates import render_task  # noqa: E402
from app.core.terrain_query import passability_at  # noqa: E402
from app.core.world_geometry import boundary_contains, location_at_point  # noqa: E402
from app.models import terrain, world  # noqa: E402
from app.models.character import (get_character_current_location,  # noqa: E402
                                  get_character_current_room,
                                  get_character_pos,
                                  get_character_profile,
                                  get_character_status,
                                  get_effective_activity,
                                  list_temporary_npcs)
from app.models.world import (_load_world_data, _save_world_data,  # noqa: E402
                              add_location, list_locations,
                              update_location_position)

# Offline: no embedding model is downloaded for the pose catalog.
embedding.embed = lambda text: None

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_true(label, cond, detail=""):
    global CHECKED
    CHECKED += 1
    ok = bool(cond)
    print(f"  {'OK ' if ok else 'FAIL'} {label}" + (f": {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


# ── the world ───────────────────────────────────────────────────────────────

def set_map3d(location_id: str, **fields) -> None:
    """Merge fields into a location's map3d blob (boundary).

    A ``plan_width_m`` handed in is DRAWN as the centred square of that edge
    — since 2026-08-19 the width alone is no shape at all, so a fixture that
    wants ground has to say so (copied from ``smoke_journey_point``).
    """
    width = fields.get("plan_width_m")
    if width:
        _h = round(float(width) / 2.0, 2)
        fields.setdefault("boundary", [[-_h, -_h], [_h, -_h],
                                       [_h, _h], [-_h, _h]])
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            map3d = dict(loc.get("map3d") or {})
            map3d.update(fields)
            loc["map3d"] = map3d
    _save_world_data(data)


terrain.save_area({"kind": "grass",
                   "polygon": [[-250, -150], [250, -150], [250, 150],
                               [-250, 150]],
                   "z_order": 0})
terrain.save_area({"kind": "deep_water",
                   "polygon": [[-30, -30], [0, -30], [0, 30], [-30, 30]],
                   "z_order": 1})
terrain.save_area({"kind": "deep_water",
                   "polygon": [[170, 70], [230, 70], [230, 130], [170, 130]],
                   "z_order": 1})

MILL = add_location("Old Mill", "A mill at the ford.",
                    rooms=[{"id": "millroom", "name": "Mill room",
                            "description": "Flour dust."}])["id"]
update_location_position(MILL, 0.0, 0.0)
set_map3d(MILL, plan_width_m=6)

SHED = add_location("Toolshed", "A neighbour's shed.",
                    rooms=[{"id": "inside", "name": "Inside",
                            "description": "Tools."}])["id"]
update_location_position(SHED, 15.0, 0.0)
set_map3d(SHED, plan_width_m=8)

CLEARING = add_location("Forest Clearing", "Open ground in the wood.",
                        rooms=[{"id": "glade", "name": "Glade",
                                "description": "Moss."}])["id"]
update_location_position(CLEARING, 100.0, 0.0)

HALL = add_location("Great Hall", "A long stone hall.",
                    rooms=[{"id": "nave", "name": "Nave",
                            "description": "Echoes."}])["id"]
update_location_position(HALL, -100.0, 0.0)
set_map3d(HALL, plan_width_m=60)

SUNKEN = add_location("Sunken Post", "A post in the marsh.",
                      rooms=[{"id": "hut", "name": "Hut",
                              "description": "Wet."}])["id"]
update_location_position(SUNKEN, 200.0, 100.0)

MILL_HOME = npc_home.circle_home(MILL, 0.0, 0.0, 25.0)
CLEARING_HOME = npc_home.circle_home(CLEARING, 100.0, 0.0, 20.0)
SUNKEN_HOME = npc_home.circle_home(SUNKEN, 200.0, 100.0, 20.0)


def set_npc_config(**values) -> None:
    cfg = config.get_all()
    cfg.setdefault("npc", {}).update(values)
    config.save(cfg, STORAGE / "config.json")


set_npc_config(require_assets=False, action_tick_enabled=True,
               action_interval_game_minutes=30, action_batch=5, max_alive=50)


def make_npc(name: str, *, task: str = "watches the road") -> str:
    """Create a temporary NPC through the real apply path, placed NOWHERE."""
    apply_npc({"character_name": name,
               "character_appearance": "a weathered poacher",
               "outfit_description": "a patched brown coat",
               "standing_task": task},
              "", "", template="npc-temporary",
              created_by="smoke_npc_home")
    return name


def pooled_npc(name: str) -> str:
    """A temporary NPC sitting in the pool, ready to be revived."""
    make_npc(name)
    pool_npc(name, reason="smoke")
    return name


def silence(*keep: str) -> None:
    """Stamp every living temporary NPC EXCEPT ``keep`` as having just acted."""
    from app.core.timeutils import game_time
    now = game_time()
    for name in list_temporary_npcs():
        if name not in keep:
            npc_actions._last_action[name] = now


def isolate(*keep: str) -> None:
    """``silence`` plus: the kept ones lose their stamp and are due right now."""
    silence(*keep)
    for name in keep:
        npc_actions._last_action.pop(name, None)


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    """Stands in for ``llm_call``: canned answers, in order."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, task, system_prompt, user_prompt, **kwargs):
        self.calls.append({"task": task, "system": system_prompt,
                           "user": user_prompt, "kwargs": kwargs})
        idx = min(len(self.calls) - 1, len(self.answers) - 1)
        return FakeResponse(self.answers[idx])


# ── (a) random_point stays inside, on walkable ground, out of the shed ──────
print("(a) random_point: 200 draws in the Old Mill circle")
LOCS = list_locations()
SHED_LOC = [loc for loc in LOCS if loc.get("id") == SHED][0]
MILL_LOC = [loc for loc in LOCS if loc.get("id") == MILL][0]

points = [npc_home.random_point(MILL_HOME) for _ in range(200)]
check("every draw delivered a point", sum(p is None for p in points), 0)
good = [p for p in points if p is not None]
check("all inside the 25 m circle",
      sum(1 for x, z in good if math.hypot(x, z) > 25.0), 0)
check("none inside the neighbour's shed",
      sum(1 for x, z in good if boundary_contains(SHED_LOC, x, z)), 0)
check("none on the lake (x < 0 is water unless the mill's floor covers it)",
      sum(1 for x, z in good
          if x < 0 and not boundary_contains(MILL_LOC, x, z)), 0)
check("and every point out in the open really is passable terrain",
      sum(1 for x, z in good
          if not boundary_contains(MILL_LOC, x, z)
          and not passability_at(x, z)[0]), 0)

print("(a) min_dist_from keeps the tick from walking on the spot")
near = [npc_home.random_point(MILL_HOME, min_dist_from=(0.0, 0.0))
        for _ in range(200)]
check("every draw delivered a point", sum(p is None for p in near), 0)
check(f"all at least {npc_home.MIN_ROAM_DIST_M} m away",
      sum(1 for p in near if p is not None
          and math.hypot(p[0], p[1]) < npc_home.MIN_ROAM_DIST_M), 0)

print("(a) a circle that is all water answers None")
check("the Sunken Post circle", npc_home.random_point(SUNKEN_HOME), None)

print("(a) describe")
check("the circle reads as a place", npc_home.describe(MILL_HOME),
      "within 25 m of Old Mill")
check("contains at the centre", npc_home.contains(MILL_HOME, 0.0, 0.0), True)
check("contains just outside", npc_home.contains(MILL_HOME, 25.1, 0.0), False)

# ── (b) placement ───────────────────────────────────────────────────────────
print("(b) revive_from_pool with radius_m places at a point")
B = pooled_npc("Wanda")
check("the revive succeeded",
      revive_from_pool(B, MILL, "millroom", ttl_hours=1, slot_role="poacher",
                       radius_m=25), True)
pos = get_character_pos(B)
check_true("it stands somewhere", pos is not None, f"{pos}")
if pos:
    check("inside the circle", math.hypot(pos["x"], pos["z"]) <= 25.0, True)
check("npc_home is stamped", (get_character_profile(B) or {}).get("npc_home"),
      MILL_HOME)
check("it is in the world", get_character_status(B), "")
if pos:
    derived = location_at_point(pos["x"], pos["z"], list_locations())
    check("current_location is DERIVED from the point, not handed in",
          get_character_current_location(B),
          (derived.get("id") or "") if derived else "")

print("(b) the derivation, pinned at both ends")
B2 = pooled_npc("Halla")
check("revived into the Great Hall's circle",
      revive_from_pool(B2, HALL, "nave", ttl_hours=1, slot_role="guard",
                       radius_m=5), True)
check("a circle wholly inside a footprint puts the NPC in that place",
      get_character_current_location(B2), HALL)

B3 = pooled_npc("Frida")
check("revived into the Clearing's circle",
      revive_from_pool(B3, CLEARING, "glade", ttl_hours=1, slot_role="poacher",
                       radius_m=20), True)
check("a place without a boundary leaves the NPC in the open",
      get_character_current_location(B3), "")
check("and it really has no room", get_character_current_room(B3), "")

print("(b) radius_m 0 is the old room placement, unchanged")
B4 = pooled_npc("Gerlind")
check("the revive succeeded",
      revive_from_pool(B4, MILL, "millroom", ttl_hours=1, slot_role="miller"),
      True)
check("location", get_character_current_location(B4), MILL)
check("room", get_character_current_room(B4), "millroom")
check("and NO home was stamped",
      (get_character_profile(B4) or {}).get("npc_home"), None)

# ── (c) pooling forgets the home ────────────────────────────────────────────
print("(c) pool_npc drops npc_home")
check("pooled", pool_npc(B, reason="smoke"), True)
check("npc_home is gone", (get_character_profile(B) or {}).get("npc_home"),
      None)

# ── (d) the roaming action turn ─────────────────────────────────────────────
print("(d) an NPC with a home is asked only what it is doing")
D = B3                       # Frida, at home in the Forest Clearing
isolate(D)
_vars = npc_actions.prompt_vars(D)
check("the home variant is chosen", _vars.get("home"),
      "within 20 m of Forest Clearing")
check("and it offers no rooms", _vars.get("rooms"), [])

LLM = FakeLLM('{"activity": "lauert im Unterholz"}')
res = npc_actions.run_action_for(D, llm=LLM)
check("the answer was applied",
      {k: res.get(k) for k in ("name", "room", "activity", "moved")}
      if res else None,
      {"name": D, "room": "", "activity": "lauert im Unterholz",
       "moved": True})
check("the activity really is written", get_effective_activity(D),
      "lauert im Unterholz")
check("exactly one LLM call", len(LLM.calls), 1)
check("the prompt names the home", "within 20 m of Forest Clearing"
      in LLM.calls[0]["user"], True)
check("and carries no room list",
      "Rooms of this place" in LLM.calls[0]["user"], False)
check("the answer shape is spelled out in the system prompt",
      '{"activity"' in LLM.calls[0]["system"], True)

journey = (get_character_profile(D) or {}).get("journey") or {}
check("a point journey is running", bool(journey), True)
check("with no location target", journey.get("target"), "")
tp = journey.get("target_point") or {}
check_true("the goal is a point", bool(tp), f"{tp}")
if tp:
    check("and it lies inside the home circle",
          npc_home.contains(CLEARING_HOME, tp.get("x"), tp.get("z")), True)
check("no room was written", get_character_current_room(D), "")

print("(d) the journey guard keeps the next tick away")
isolate(D)                   # cooldown removed — the journey is the only bar
check("not a candidate while walking", D in npc_actions.candidates(), False)

# ── (e) a party follower does not roam ──────────────────────────────────────
print("(e) a follower is dragged along, so it is no roaming candidate")
E_LEAD = pooled_npc("Ortrun")
revive_from_pool(E_LEAD, HALL, "nave", ttl_hours=1, slot_role="guard",
                 radius_m=5)
E_FOLLOW = pooled_npc("Sieglinde")
revive_from_pool(E_FOLLOW, HALL, "nave", ttl_hours=1, slot_role="guard",
                 radius_m=5)
check("both stand in the hall",
      (get_character_current_location(E_LEAD),
       get_character_current_location(E_FOLLOW)), (HALL, HALL))
check_true("the party formed", add_to_party(E_LEAD, E_FOLLOW) is not None)
isolate(E_LEAD, E_FOLLOW)
cands = npc_actions.candidates()
check("the leader acts", E_LEAD in cands, True)
check("the follower does not", E_FOLLOW in cands, False)

# ── (f) nothing else changed ────────────────────────────────────────────────
print("(f) an NPC with neither a location nor a home is not asked at all")
F = make_npc("Nirgend")          # created with no location and no radius
check("it really stands nowhere", get_character_current_location(F), "")
check("and carries no home",
      (get_character_profile(F) or {}).get("npc_home"), None)
check("prompt_vars is empty", npc_actions.prompt_vars(F), {})

print("(f) the slot schema carries radius_m")
check("default 0", npc_spawn.normalize_slot({"role": "poacher"})["radius_m"], 0)
check("a number is kept",
      npc_spawn.normalize_slot({"role": "poacher", "radius_m": 60})["radius_m"],
      60)
check("garbage falls back to 0",
      npc_spawn.normalize_slot({"role": "poacher", "radius_m": "wide"})["radius_m"],
      0)
check("a negative radius is no radius",
      npc_spawn.normalize_slot({"role": "poacher", "radius_m": -5})["radius_m"],
      0)

# ── (g) both template branches render ───────────────────────────────────────
print("(g) the template renders under StrictUndefined, both branches")
_home_vars = npc_actions.prompt_vars(D)
_sys_home, _user_home = render_task("npc_action", **_home_vars)
check("home: system part is non-empty", bool(_sys_home.strip()), True)
check("home: user part is non-empty", bool(_user_home.strip()), True)
check("home: the answer shape names only the activity",
      ('"activity"' in _sys_home, '"room"' in _sys_home), (True, False))

_room_vars = npc_actions.prompt_vars(B4)     # Gerlind, in the mill room
_sys_room, _user_room = render_task("npc_action", **_room_vars)
check("room: system part is non-empty", bool(_sys_room.strip()), True)
check("room: user part is non-empty", bool(_user_room.strip()), True)
check("room: the answer shape still names the room",
      '"room"' in _sys_room, True)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
