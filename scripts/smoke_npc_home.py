#!/usr/bin/env python3
"""Smoke run for the temporary-NPC HOME AREA — the circle (spec § E3.1) and
the painted TERRAIN AREA (spec § E3.2).

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

      EVERY test runs on the ROUNDED point, ``contains`` included — the
      rounded point is what the function returns and what the world stores.
      A draw near the rim rounds OUTWARD often enough to matter: at 45° on
      the 25 m rim the raw point is 25·cos45° = 17.6776695… on both axes,
      which rounds to 17.68/17.68 and is |p| = 17.68·√2 = 25.00331… m from
      the centre — outside the circle ``contains`` describes. A stub rng
      that draws exactly that pair (u = 1.0 → r = 25·√1 = 25, v = 0.125 →
      θ = 45°) must therefore be rejected on every one of its 40 attempts,
      so the answer is None and never a point two functions of this module
      disagree about. The 200-draw loops run on SEEDED rngs and must hold
      for any seed.

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

  (b3) THE GAME-ADMIN ROW SAYS WHERE A ROAMING NPC LIVES. A circle or area
      NPC stands out in the open, so ``npc_summary``'s ``location_id``,
      ``location_name`` and ``room_id`` are all "" — without the home the row
      would say nothing at all about where that NPC is. ``home`` is
      ``npc_home.describe``: "within 20 m of Forest Clearing" for the circle,
      the painted LABEL ("Hunting Ground", checked in (k)) for an area, and
      "" for an NPC placed into a room. ``slot_area`` rides beside it — the
      painted area whose slot the NPC holds, "" for a location slot — so the
      list can tell the two wordings apart.

  (b2) A FAILED PLACEMENT IS NOT A FINISHED JOB. ``npc_home.place_npc``
      answers "" instead of raising (its other two callers turn that into
      their own False), but for the assets job the placement IS the job and
      nothing else will ever place this NPC. So ``_place`` raises on "",
      after putting the status back to POOLED — the NPC waits in the pool
      exactly as it did before the attempt, the queue retries, and the panel
      shows the reason. Proven with a ``set_character_pos`` that throws — on
      an NPC carrying the GATE's own ``npc_pooled_reason``, because since the
      resurrection fix ``_place`` places only what the gate pooled (see
      ``scripts/smoke_npc_assets.py`` [16]).

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

  (e) NOBODY IN A PARTY ROAMS — NEITHER HALF. A FOLLOWER is dragged along by
      its leader and loses its own travel; the party engine cancels a
      follower's journey at the join, so a roaming turn could only produce a
      journey somebody else deletes. A LEADER is the other half of the same
      problem: followers are dragged along by a LOCATION change only, and a
      roaming journey to a free point inside the home area moves the leader
      and nobody else — the party would be stranded where it set out from.
      The same two NPCs are candidates before the party is formed and again
      after it is left, so what the check measures is the party and not their
      cooldown, their journey or their home.

  (f) NOTHING ELSE CHANGED. An NPC with neither a location nor a home still
      yields ``prompt_vars`` == {} (there is nothing to ask it), and the
      slot schema carries ``radius_m`` as an int ≥ 0 with default 0.
      ``normalize_slot`` runs inside the LOCATION SAVE, so no authored value
      may raise out of it: "inf" and "1e400" reach ``int()`` as infinity
      (``OverflowError``, which is NOT a ValueError) and "nan" as NaN, and
      all three have to come back as 0 with a warning.

  (g) THE TEMPLATE RENDERS UNDER StrictUndefined — BOTH branches, with
      exactly the variable sets the module passes. A placeholder one branch
      forgets is a crash in production, not a warning.

── stage 2: the painted TERRAIN AREA as a home (§ E3.2) ───────────────────

Three more painted areas, all of kind ``grass`` and all inside the big grass
rectangle above, so only the two lakes and the placed footprints can reject
anything:

  Hunting Ground  x 120…240, z  40…140   (label "Hunting Ground")
                  → the second lake (170…230 × 70…130) lies WHOLLY inside it
  Shed Yard       x   0…40,  z −40…40    (label "Shed Yard")
                  → the Toolshed (11…19 × −4…4) lies wholly inside it, and
                    the eastern half of the Old Mill (0…3 × −3…3) as well
  Drowned Reach   x 175…225, z  75…125   (label "Drowned Reach")
                  → wholly inside the second lake

  (h) ``random_point`` ON A POLYGON obeys the SAME two rules as the circle,
      only the shape differs — rejection sampling in ``polygon_bounds`` with
      ``point_in_polygon`` instead of a radius:
        · Hunting Ground, 200 draws per seed: every point is inside the
          polygon, ``contains`` agrees, and NONE lies in the lake — the lake
          is 60 × 60 m of the 120 × 100 m area, i.e. 30 % of the bounding
          box, so a missing passability test would show up in every loop;
        · Shed Yard, 200 draws: none lies inside ANY location footprint. For
          an AREA home every location is foreign — the area is the home, not
          the place, so there is no "own" location the way the circle has
          one;
        · Drowned Reach answers None: all of it is water, so all 40 attempts
          are rejected;
        · an area id nothing is painted under answers None as well, and
          ``contains`` says False — a deleted area must not place anybody.
      ``describe`` is the area's LABEL, which is what the roaming prompt
      renders ("it roams Hunting Ground").

      THE BUDGET FOLLOWS THE SHAPE. Rejection sampling in the BOUNDING BOX
      throws every draw outside the polygon away before a rule is even asked,
      so a flat attempt count buys less the thinner the shape. The Long Ride
      is the case: a 5 m wide parallelogram running diagonally from
      (600, 600) to (700, 700), on nothing but grass.
        bounding box   x 600…705 × z 600…700     = 105 × 100 = 10500 m²
        shoelace area  base (5,0) × side (100,100)         =   500 m²
        in-box hit rate                            500/10500 = 4.7619 %
      With a flat 40 attempts a draw gives up with probability
      (1 − 0.047619)^40 = 0.142 — one placement in seven fails on ground that
      is entirely walkable, which on the pool-return path used to cost a
      living ghost and an LLM generation. Scaled by box ÷ shape = 21 the
      budget is 840, capped at ``MAX_AREA_ATTEMPTS`` = 400, and the failure
      probability becomes 0.952381^400 = 3.3e-9. Checked as 200 draws per
      seed on three seeds: not one None, and every point inside the strip.

  (i) THE SLOTS ARE AREA DATA, normalized by the very sanitizer every write
      goes through (``terrain.sanitize_area``):
        · the slot list runs through ``npc_spawn.normalize_slots``, and
          ``room``/``radius_m`` are FORCED to ""/0 — the area IS the home, so
          a room or a radius on such a slot is meaningless;
        · an unknown key inside a slot does not survive;
        · slots WITHOUT a label raise ValueError: the label is what the
          generator's briefing and the roaming prompt name the place by, and
          an area called "" is nothing anybody can be told about;
        · an empty list drops the key instead of storing "wants nobody";
        · ``save_area`` → ``get_area`` returns the stored slots unchanged,
          and ``get_area`` of an unknown id is None.

  (j) THE BAKE DOES NOT SEE THE SLOTS. ``meta.npc_slots`` is inert for the
      ground: re-saving one and the same area with slots leaves
      ``models.heightfield.height_sig()`` (the token that decides whether the
      world raster is rebuilt) and ``terrain_layers.layer_table`` byte-for-
      byte identical. Both are computed over PROJECTIONS of the areas
      (``relief_basis`` takes kind/polygon/relief, the layer table takes kind
      and the cut keys), which is why an authoring key may live in `meta`
      at all.

  (k) PLACEMENT FROM THE POOL WITH AN AREA HOME. ``revive_from_pool`` with
      ``home=area_home(<Hunting Ground>)`` and no location at all:
        · the NPC stands at a point of the polygon;
        · ``npc_home`` is {"kind": "area", "area_id": …};
        · the slot stamp is ``npc_slot_area`` — ``npc_slot_location`` stays
          "" so a location's own count cannot pick it up;
        · ``held_roles_at_area`` reports ["guard"] for that area and nothing
          for the location;
        · ``current_location`` is "" — the point lies in no footprint.
      Pooling forgets the home again, exactly as it does for a circle.

  (l) THE WINDOW SWEEP READS AREA SLOTS TOO. The Hunting Ground's guard slot
      is authored ``22:00-05:00``; at game 12:00 that window is shut, so
      ``npc_ops.sweep_closed_windows`` pools the area's NPC with the reason
      "window closed" — the same mechanic that empties a location's night
      slot, resolved over ``npc_slot_area`` instead of ``npc_slot_location``.

Usage:  ./.venv/bin/python scripts/smoke_npc_home.py
"""
import math
import os
import random
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
from app.core import npc_assets as na  # noqa: E402
from app.core.npc_ops import apply_npc  # noqa: E402
from app.core.npc_pool import pool_npc, revive_from_pool  # noqa: E402
from app.core.party_engine import add_to_party, leave_party  # noqa: E402
from app.core.prompt_templates import render_task  # noqa: E402
from app.core.terrain_query import passability_at  # noqa: E402
from app.core.world_geometry import boundary_contains, location_at_point  # noqa: E402
from app.models import character as character_model, terrain, world  # noqa: E402
from app.models.character import (POOLED_STATUS,  # noqa: E402
                                  get_character_current_location,
                                  get_character_current_room,
                                  get_character_pos,
                                  get_character_profile,
                                  get_character_status,
                                  get_effective_activity,
                                  list_temporary_npcs,
                                  save_character_profile)
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


def raises(label, exc_type, fn, contains=""):
    """``fn`` must raise ``exc_type``; with ``contains`` the message must also
    carry that text (copied from ``smoke_npc_assets``)."""
    global CHECKED
    CHECKED += 1
    try:
        fn()
    except exc_type as e:
        if contains and contains not in str(e):
            print(f"  FAIL {label}: {str(e)[:160]!r} does not carry "
                  f"{contains!r}")
            FAILURES.append(label)
            return
        print(f"  OK  {label}: {exc_type.__name__}({str(e)[:120]!r})")
        return
    except Exception as e:  # noqa: BLE001 — anything else is the defect
        print(f"  FAIL {label}: {type(e).__name__}({e})")
        FAILURES.append(label)
        return
    print(f"  FAIL {label}: no exception")
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
print("(a) random_point: 200 seeded draws in the Old Mill circle, per seed")
LOCS = list_locations()
SHED_LOC = [loc for loc in LOCS if loc.get("id") == SHED][0]
MILL_LOC = [loc for loc in LOCS if loc.get("id") == MILL][0]

# SEEDED, and checked for SEVERAL seeds: the rules below must hold for every
# draw, not for a lucky one. An unseeded loop would only fail this run in
# about one run of forty (2.25 % of 200-draw loops hit the rim rounding).
for seed in (1, 7, 12345, 2026):
    rng = random.Random(seed)
    points = [npc_home.random_point(MILL_HOME, rng=rng) for _ in range(200)]
    good = [p for p in points if p is not None]
    check(f"seed {seed}: every draw delivered a point",
          sum(p is None for p in points), 0)
    check(f"seed {seed}: all inside the 25 m circle",
          sum(1 for x, z in good if math.hypot(x, z) > 25.0), 0)
    check(f"seed {seed}: … and contains() agrees about every one of them",
          sum(1 for x, z in good if not npc_home.contains(MILL_HOME, x, z)), 0)
    check(f"seed {seed}: none inside the neighbour's shed",
          sum(1 for x, z in good if boundary_contains(SHED_LOC, x, z)), 0)
    check(f"seed {seed}: none on the lake (x < 0 is water unless the mill's "
          f"floor covers it)",
          sum(1 for x, z in good
              if x < 0 and not boundary_contains(MILL_LOC, x, z)), 0)
    check(f"seed {seed}: and every point out in the open is passable terrain",
          sum(1 for x, z in good
              if not boundary_contains(MILL_LOC, x, z)
              and not passability_at(x, z)[0]), 0)


class RimRng:
    """Draws the ONE pair whose point rounds OUT of the circle, every time.

    ``u`` = 1.0 → r = 25·√1 = 25.0 (the rim itself); ``v`` = 0.125 → θ = 45°.
    Raw point 25·cos45° = 17.6776695… on both axes → rounded 17.68/17.68 →
    |p| = 25.00331… m. Inside the shed? No (z = 17.68 is outside its −4…4).
    On water? No (x > 0). So the ONLY thing that may reject it is the shape
    test on the rounded point.
    """

    def __init__(self):
        self.values = [1.0, 0.125]
        self.calls = 0

    def random(self):
        value = self.values[self.calls % 2]
        self.calls += 1
        return value


print("(a) a draw that ROUNDS out of the circle is rejected, not returned")
_rim_x = round(25.0 * math.cos(math.pi / 4), 2)
check("the constructed rim point really rounds outward",
      (_rim_x, math.hypot(_rim_x, _rim_x) > 25.0), (17.68, True))
check("it is not rejected for any other reason",
      (boundary_contains(SHED_LOC, _rim_x, _rim_x),
       passability_at(_rim_x, _rim_x)[0]), (False, True))
_rim_rng = RimRng()
check("random_point refuses it", npc_home.random_point(MILL_HOME,
                                                       rng=_rim_rng), None)
check("and it really tried the full 40 attempts", _rim_rng.calls, 80)

print("(a) min_dist_from keeps the tick from walking on the spot")
_rng = random.Random(99)
near = [npc_home.random_point(MILL_HOME, rng=_rng, min_dist_from=(0.0, 0.0))
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

# ── (b3) the Game-Admin row says where a roaming NPC lives ──────────────────
print("(b3) npc_summary carries the home area")
from app.core.npc_ops import npc_summary  # noqa: E402
_row_b3 = npc_summary(B3)                 # Frida, the Clearing's 20 m circle
check("a roaming NPC has no location, no name and no room to show",
      (_row_b3["location_id"], _row_b3["location_name"], _row_b3["room_id"]),
      ("", "", ""))
check("…so the row carries its home instead", _row_b3["home"],
      "within 20 m of Forest Clearing")
check("…and the area stamp, empty for a location slot",
      _row_b3["slot_area"], "")
_row_b4 = npc_summary(B4)                 # Gerlind, plain room placement
check("a room NPC shows its place and no home",
      (_row_b4["location_id"], _row_b4["room_id"], _row_b4["home"]),
      (MILL, "millroom", ""))

# ── (b2) a failed placement fails the JOB ───────────────────────────────────
print("(b2) a placement that cannot be written fails the assets job")
B5 = pooled_npc("Radegund")
# THE JOB PLACES ONLY WHAT THE GATE POOLED. `pooled_npc` uses the ordinary
# `pool_npc`, whose reason is not the gate's — and since the resurrection fix
# (smoke_npc_assets [16]) `_place` refuses those, because "pooled" alone does
# not mean "waiting for this job". Stamping the gate's own reason is what
# `gate_placement` does for a real held-back NPC.
_b5 = get_character_profile(B5) or {}
_b5["npc_pooled_reason"] = na.GATE_REASON_PREFIX + "profile_image"
save_character_profile(B5, _b5)
_real_set_pos = character_model.set_character_pos
_real_complete = na.npc_assets_complete


def _broken_set_pos(*args, **kwargs):
    raise RuntimeError("smoke: the position column is on fire")


# The producers are not what this section is about — the job is told the NPC
# is finished so it reaches the placement step at all.
character_model.set_character_pos = _broken_set_pos
na.npc_assets_complete = lambda name: []
try:
    raises("the job raises instead of reporting ok", RuntimeError,
           lambda: na._handle_npc_assets({"name": B5, "location_id": MILL,
                                          "room_id": "", "radius_m": 25}),
           contains="could not be placed")
    check("and the NPC waits in the pool, exactly as before the attempt",
          get_character_status(B5), POOLED_STATUS)
    check("it stands nowhere", get_character_pos(B5), None)
finally:
    character_model.set_character_pos = _real_set_pos
    na.npc_assets_complete = _real_complete

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

# ── (e) nobody in a party roams ─────────────────────────────────────────────
print("(e) neither half of a party is a roaming candidate")
E_LEAD = pooled_npc("Ortrun")
revive_from_pool(E_LEAD, HALL, "nave", ttl_hours=1, slot_role="guard",
                 radius_m=5)
E_FOLLOW = pooled_npc("Sieglinde")
revive_from_pool(E_FOLLOW, HALL, "nave", ttl_hours=1, slot_role="guard",
                 radius_m=5)
check("both stand in the hall",
      (get_character_current_location(E_LEAD),
       get_character_current_location(E_FOLLOW)), (HALL, HALL))
isolate(E_LEAD, E_FOLLOW)
check("both roam while there is no party",
      (E_LEAD in npc_actions.candidates(),
       E_FOLLOW in npc_actions.candidates()), (True, True))
check_true("the party formed", add_to_party(E_LEAD, E_FOLLOW) is not None)
isolate(E_LEAD, E_FOLLOW)
cands = npc_actions.candidates()
check("the follower does not roam — the leader's move carries it",
      E_FOLLOW in cands, False)
check("and neither does the LEADER: a roaming journey to a free point moves "
      "nobody but itself, and would strand its followers", E_LEAD in cands,
      False)
leave_party(E_LEAD)
isolate(E_LEAD, E_FOLLOW)
check("once the party is gone both roam again",
      (E_LEAD in npc_actions.candidates(),
       E_FOLLOW in npc_actions.candidates()), (True, True))

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
for _bad in ("inf", "-inf", "1e400", "nan"):
    check(f"{_bad!r} does not escape the location save",
          npc_spawn.normalize_slot({"role": "poacher",
                                    "radius_m": _bad})["radius_m"], 0)
check("and neither does a float infinity",
      npc_spawn.normalize_slot({"role": "poacher",
                                "radius_m": float("inf")})["radius_m"], 0)
check("the whole list survives one poisoned slot",
      [s["radius_m"] for s in npc_spawn.normalize_slots(
          [{"role": "a", "radius_m": "inf"}, {"role": "b", "radius_m": 40}])],
      [0, 40])

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

# ═══ stage 2: the painted terrain area as a home (§ E3.2) ══════════════════

# LAYER 0, like the base grass and BELOW the two lakes (z_order 1): the
# topmost area at a point decides its kind, so a slot area painted over the
# water would make the Drowned Reach walkable and take rule (h) with it.
HUNT = terrain.save_area({"kind": "grass", "z_order": 0,
                          "polygon": [[120, 40], [240, 40], [240, 140],
                                      [120, 140]],
                          "meta": {"label": "Hunting Ground"}})["id"]
YARD = terrain.save_area({"kind": "grass", "z_order": 0,
                          "polygon": [[0, -40], [40, -40], [40, 40], [0, 40]],
                          "meta": {"label": "Shed Yard"}})["id"]
DROWNED = terrain.save_area({"kind": "grass", "z_order": 0,
                             "polygon": [[175, 75], [225, 75], [225, 125],
                                         [175, 125]],
                             "meta": {"label": "Drowned Reach"}})["id"]
HUNT_HOME = npc_home.area_home(HUNT)
YARD_HOME = npc_home.area_home(YARD)

# ── (h) random_point on a polygon ───────────────────────────────────────────
print("(h) random_point on a polygon: inside, passable, out of every place")
from app.core.world_geometry import point_in_polygon  # noqa: E402
HUNT_POLY = [[120, 40], [240, 40], [240, 140], [120, 140]]
YARD_POLY = [[0, -40], [40, -40], [40, 40], [0, 40]]

for seed in (3, 11, 4242):
    rng = random.Random(seed)
    points = [npc_home.random_point(HUNT_HOME, rng=rng) for _ in range(200)]
    good = [p for p in points if p is not None]
    check(f"seed {seed}: every draw delivered a point",
          sum(p is None for p in points), 0)
    check(f"seed {seed}: all inside the polygon",
          sum(1 for x, z in good if not point_in_polygon(x, z, HUNT_POLY)), 0)
    check(f"seed {seed}: … and contains() agrees",
          sum(1 for x, z in good if not npc_home.contains(HUNT_HOME, x, z)), 0)
    check(f"seed {seed}: none on the lake (170…230 × 70…130)",
          sum(1 for x, z in good
              if 170 <= x <= 230 and 70 <= z <= 130), 0)
    check(f"seed {seed}: and every point is passable ground",
          sum(1 for x, z in good if not passability_at(x, z)[0]), 0)

print("(h) for an AREA home every placed location is foreign")
_rng = random.Random(77)
yard = [npc_home.random_point(YARD_HOME, rng=_rng) for _ in range(200)]
_yard_good = [p for p in yard if p is not None]
check("every draw delivered a point", sum(p is None for p in yard), 0)
check("all inside the yard",
      sum(1 for x, z in _yard_good if not point_in_polygon(x, z, YARD_POLY)), 0)
check("none inside the Toolshed",
      sum(1 for x, z in _yard_good if boundary_contains(SHED_LOC, x, z)), 0)
check("none inside the Old Mill either",
      sum(1 for x, z in _yard_good if boundary_contains(MILL_LOC, x, z)), 0)
check("and location_at_point answers nothing for all of them",
      sum(1 for x, z in _yard_good
          if location_at_point(x, z, list_locations())), 0)

print("(h) a thin diagonal strip is sampled until it delivers")
# THE BUDGET FOLLOWS THE SHAPE. A polygon is sampled in its BOUNDING BOX, so
# a diagonal strip throws most draws away before any rule is asked. This one
# is a parallelogram, 5 m wide, running from (600,600) to (700,700):
#   bounding box   x 600…705 × z 600…700          = 105 × 100 = 10500 m²
#   shoelace area  base (5,0) × side (100,100)    = 500 m²
#   in-box hit rate                                 500/10500 = 4.7619 %
# With a flat 40 attempts a draw fails outright with probability
#   (1 − 0.047619)^40 = 0.14 — one placement in seven, on ground that is
# entirely walkable. Scaled by box ÷ shape = 21 the budget would be 840,
# capped at MAX_AREA_ATTEMPTS = 400, and the failure probability is
#   0.952381^400 = 3.3e-9 — never, in 600 draws.
STRIP_POLY = [[600, 600], [605, 600], [705, 700], [700, 700]]
STRIP = terrain.save_area({"kind": "grass", "polygon": STRIP_POLY,
                           "z_order": 0,
                           "meta": {"label": "The Long Ride"}})["id"]
STRIP_HOME = npc_home.area_home(STRIP)
from app.core.world_geometry import polygon_area, polygon_bounds  # noqa: E402
_b = polygon_bounds(STRIP_POLY)
check("the box is 105 × 100 m",
      ((_b[2] - _b[0]) * (_b[3] - _b[1])), 10500.0)
check("the strip itself is 500 m²", polygon_area(STRIP_POLY), 500.0)
for seed in (5, 23, 909):
    rng = random.Random(seed)
    strip = [npc_home.random_point(STRIP_HOME, rng=rng) for _ in range(200)]
    check(f"seed {seed}: no draw gave up on the 4.8 % strip",
          sum(p is None for p in strip), 0)
    check(f"seed {seed}: … and every point really is in it",
          sum(1 for p in strip
              if p is not None
              and not point_in_polygon(p[0], p[1], STRIP_POLY)), 0)

print("(h) an area that is all water, and an area that is not there")
check("the drowned reach", npc_home.random_point(npc_home.area_home(DROWNED)),
      None)
_ghost = npc_home.area_home("ta_does_not_exist")
check("a deleted area places nobody", npc_home.random_point(_ghost), None)
check("… and contains nothing", npc_home.contains(_ghost, 0.0, 0.0), False)
check("describe is the label", npc_home.describe(HUNT_HOME), "Hunting Ground")
check("contains inside", npc_home.contains(HUNT_HOME, 130.0, 50.0), True)
check("contains outside", npc_home.contains(HUNT_HOME, 119.0, 50.0), False)
check("the home dict is the two documented keys", HUNT_HOME,
      {"kind": "area", "area_id": HUNT})

# ── (i) slots are area data ─────────────────────────────────────────────────
print("(i) sanitize_area normalizes meta.npc_slots")
_raw = {"kind": "grass", "polygon": YARD_POLY,
        "meta": {"label": "Shed Yard",
                 "npc_slots": [{"role": " guard ", "count_min": 2,
                                "room": "taproom", "radius_m": 50,
                                "briefing": "watches the gate",
                                "when": "22:00-05:00", "junk": 1},
                               {"role": "guard"},
                               {"count_min": 3}]}}
_clean = terrain.sanitize_area(_raw)["meta"]["npc_slots"]
check("one slot per role, sanitized", _clean,
      [{"role": "guard", "template": "", "count_min": 2, "count_max": 2,
        "briefing": "watches the gate", "room": "", "when": "22:00-05:00",
        # `character` (the slot binding) survives the area sanitizer untouched:
        # binding an existing NPC works on a painted area exactly as it works
        # on a location — only `room`/`radius_m` are forced empty here.
        "radius_m": 0, "character": ""}])
raises("slots without a label are refused", ValueError,
       lambda: terrain.sanitize_area({"kind": "grass", "polygon": YARD_POLY,
                                      "meta": {"npc_slots": [
                                          {"role": "guard"}]}}),
       contains="label")
check("an empty list drops the key",
      "npc_slots" in terrain.sanitize_area(
          {"kind": "grass", "polygon": YARD_POLY,
           "meta": {"label": "x", "npc_slots": []}})["meta"], False)
check("a list of unusable slots drops it too",
      "npc_slots" in terrain.sanitize_area(
          {"kind": "grass", "polygon": YARD_POLY,
           "meta": {"label": "x", "npc_slots": [{"count_min": 1}]}})["meta"],
      False)

print("(i) save_area → get_area keeps the slots")
GUARD_SLOT = {"role": "guard", "count_min": 1, "count_max": 1,
              "briefing": "watches the wood", "when": "22:00-05:00"}
terrain.save_area({"id": HUNT, "kind": "grass", "z_order": 0,
                   "polygon": HUNT_POLY,
                   "meta": {"label": "Hunting Ground",
                            "npc_slots": [GUARD_SLOT]}})
_stored = terrain.get_area(HUNT) or {}
check("the label survives", (_stored.get("meta") or {}).get("label"),
      "Hunting Ground")
check("and so does the slot",
      [(s["role"], s["when"], s["room"], s["radius_m"])
       for s in (_stored.get("meta") or {}).get("npc_slots") or []],
      [("guard", "22:00-05:00", "", 0)])
check("an unknown id is None", terrain.get_area("ta_nothing"), None)

# ── (j) the bake does not see the slots ─────────────────────────────────────
print("(j) meta.npc_slots is inert for the ground")
from app.core.terrain_layers import layer_table  # noqa: E402
from app.core.terrain_types import effective_catalog  # noqa: E402
from app.models.heightfield import height_sig  # noqa: E402

_bare = {"id": YARD, "kind": "grass", "z_order": 0, "polygon": YARD_POLY,
         "meta": {"label": "Shed Yard"}}
terrain.save_area(_bare)
_sig_before = height_sig()
_table_before = layer_table(terrain.list_areas(), effective_catalog(), "grass")
terrain.save_area({**_bare, "meta": {"label": "Shed Yard",
                                     "npc_slots": [{"role": "stablehand"}]}})
check("the height signature does not move", height_sig(), _sig_before)
check("and the layer table is the same list",
      layer_table(terrain.list_areas(), effective_catalog(), "grass"),
      _table_before)
terrain.save_area(_bare)

# ── (k) placement from the pool with an area home ───────────────────────────
print("(k) revive_from_pool with an area home")
K = pooled_npc("Wulfhild")
check("the revive succeeded",
      revive_from_pool(K, "", "", ttl_hours=1, slot_role="guard",
                       home=HUNT_HOME), True)
kpos = get_character_pos(K)
check_true("it stands somewhere", kpos is not None, f"{kpos}")
if kpos:
    check("inside the polygon",
          point_in_polygon(kpos["x"], kpos["z"], HUNT_POLY), True)
kprof = get_character_profile(K) or {}
check("npc_home names the area", kprof.get("npc_home"), HUNT_HOME)
check("the slot stamp is the AREA one",
      (kprof.get("npc_slot_area"), kprof.get("npc_slot_location"),
       kprof.get("npc_slot_role")), (HUNT, "", "guard"))
check("it is in the world", get_character_status(K), "")
check("and stands in no location", get_character_current_location(K), "")
check("held_roles_at_area sees it", npc_spawn.held_roles_at_area(HUNT),
      ["guard"])
# The mill still holds Gerlind's `miller` from (b) — what matters is that the
# AREA's guard is not in that list: the two stamps never count each other.
check("the location count does not", npc_spawn.held_roles_at(MILL), ["miller"])
check("the roaming prompt names the area",
      npc_actions.prompt_vars(K).get("home"), "Hunting Ground")
_row_k = npc_summary(K)
check("and so does the Game-Admin row, with the area stamp beside it",
      (_row_k["home"], _row_k["slot_area"], _row_k["location_id"]),
      ("Hunting Ground", HUNT, ""))

# ── (l) the window sweep resolves area slots ────────────────────────────────
print("(l) sweep_closed_windows pools an area NPC when its window shuts")
from app.core.game_time import GameTime  # noqa: E402
from app.core.npc_ops import sweep_closed_windows  # noqa: E402
from app.core.timeutils import set_game_time  # noqa: E402

set_game_time(GameTime.from_parts(1, 20, 12, 0, 0))     # midday: 22:00-05:00 is shut
# Only K: no other living NPC's location authors slots at all, so every one
# of them leaves the sweep at "this slot does not exist".
check("exactly the area NPC goes back into the pool", sweep_closed_windows(), 1)
check("it really is pooled", get_character_status(K), POOLED_STATUS)
check("with the window reason",
      (get_character_profile(K) or {}).get("npc_pooled_reason"),
      "window closed")
check("and the home is forgotten again",
      (get_character_profile(K) or {}).get("npc_home"), None)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
