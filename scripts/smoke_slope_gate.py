#!/usr/bin/env python3
"""Smoke run for the HEIGHT GATE of free walking — step and slope
(Seamless World, E8 task 1).

Runs against a THROWAWAY storage directory — never touches a real world. The
route level is the handler function of ``app/routes/play.py`` itself (a
minimal request stand-in supplies the JSON body), so the whole gate chain runs
exactly as it does behind uvicorn — without a server.

WHAT IS NEW HERE. Until E8 no RULE in this world ever asked how high anything
was: the scene payload lifted props and the renderers draped the ground, but
one could walk up a cliff face as easily as across a lawn. This is the first
consumer of a height. ``POST /play/pos`` now compares the ground under the
last valid point with the ground under the reported one and refuses the report
when the difference is not walkable:

    Δh > 0 only  -> a SLOPE: atan(Δh / dist) > game.max_slope_deg   (def. 40)
    dist < 1 m   -> AND a STEP: Δh > game.max_step_height_m     (default 0.4)

ONLY A CLIMB IS JUDGED (user rule, 2026-08-28): Δh is signed — the ground under
the reported point minus the ground under the last one — and a descent
(Δh ≤ 0) always passes, however deep. Walking downhill is what a body does
without asking; the accepted price is that a walker can drop somewhere it
cannot climb back out of and be stranded there.

Two limits rather than one, because a 1 m wall and a 1 m rise over 20 m are not
the same obstacle — and they hold TOGETHER rather than either/or, because each
alone can be walked round (review finding F1/F2, 2026-08-13): with an either/or
the client, which tests a 0.15 m walking lead, was blind to everything the
server refused between 40° and 69°, and any slope could be climbed by reporting
0.1 m at a time. Section [1e] is the counter-probe against that older form.
The predicate is pure (``relief.slope_blocks``) and the CLIENT owns the
identical one (``client3d/src/game/walk.ts`` ``slopeBlocks``, hand-derived in
``client3d/scripts/smoke_walk_math.mjs``) — the two are checked against the
same table, section [1] below.

THE HEIGHT ITSELF is ``relief.ground_at``, and since "Ein Boden" E5a that is
``world_geometry.ground_y`` and nothing else — the ONE baked heightfield, with
every authored hill, every water carve and every location plateau already in it.
The per-location 17 x 17 scene relief that used to be ADDED on top of it
(``scene_recipe.compose_terrain`` -> ``relief.scene_ground_lift`` ->
``relief.ground_lift_at``) is deleted (user decision 1 of plan-ein-boden.md
§ 5), together with the "innermost ENCLOSING location that has a field" search
this file used to measure in section [5]. Local relief is authored as HEIGHT
AREAS of the map now, which is exactly what the fixture below paints.

THE WORLD used below — three painted height areas and two places:

    CLIFF AREA  (5004,5000)-(5044,5040), height 5 m, falloff 2 m
                -> a wall: 0 m at its own outline, the full 5 m two metres in
    LEDGE       a NATURAL location (no building outline, no closed room, so it
                stamps no plateau) pinned at (5000, 5020), 8 m square, with ONE
                boundary opening on its east edge -> world (5004, 5020), i.e.
                exactly at the foot of the cliff
    SLOPE AREA  (5200,5000)-(5240,5040), height 5 m, falloff 20 m
                -> a long flank: h = d/4 with d the distance to the outline
    GROVE       a NATURAL location on that flank, pinned at (5210, 5020),
                8 m square — the case that a place which draws no floor lets
                the landscape run straight through it
    PLAIN       (1600, 1000) a place on ground nobody shaped: the inert case
    HILL/HOUSE  section [6]'s own pair, unchanged

HAND-DERIVED EXPECTATIONS.

The cliff. A height area with ``falloff_m`` 2 rises linearly over the first two
metres INSIDE its outline: ``h = 5 · min(1, d/2)`` with ``d`` the distance to
that outline. The world lattice is anchored on the origin at a 2 m step
(``heightfield.TILE_STEP_M``), so on the line z = 5020 it carries

    x = 5004  d = 0  ->  0.0        (the support point ON the outline)
    x = 5006  d = 2  ->  5.0
    x = 5008  d = 4  ->  5.0        (past the falloff, the full height)

and ``ground_y`` mixes that lattice bilinearly, which makes every number in
section [4] exact arithmetic rather than a sample:

    h(5004.1) = 0.25     h(5004.2) = 0.5
    h(5004.5) = 1.25     h(5005.0) = 2.5

The flank. ``falloff_m`` 20 over the same 5 m gives ``h = d/4``, so on z = 5020

    x = 5202  d = 2  -> 0.5     x = 5206  d = 6  -> 1.5

  [1] THE PREDICATE, the same table the client checks (limits 0.4 m / 40°):
      1.2 m over 0.5 m -> a STEP, 1.2 > 0.4                 -> blocked
      0.3 m over 2 m   -> atan(0.15) = 8.5308°              -> free
      0.3 m over 0.5 m -> step 0.3 ≤ 0.4, angle 30.9638°    -> free
      0.4 m over 0.5 m -> the step limit itself passes (strict >), and
                          atan(0.8) = 38.6598° < 40         -> free
      −1.2 m over 0.5 m -> a DROP is never judged            -> free
      −0.9 m over 0.5 m -> nor this one, though the climb of
                          +0.9 m over the same 0.5 m is a step
                          twice the cap                      -> free
      −3 m over 1 m    -> a three-metre drop, atan(3) = 71.5651°
                          as a climb, is walked down all the same
                                                             -> free
      +0.9 m over 0.5 m -> the same rise UPWARDS is a step,
                          0.9 > 0.4                          -> blocked
      2 m over 2 m     -> atan(1) = 45° > 40                -> blocked
      1.6 m over 2 m   -> atan(0.8) = 38.6598° < 40         -> free
      1.6 m over 0.99 m -> a STEP as well there             -> blocked
      0.5 m over 1 m   -> no step regime at 1 m, 26.5651°   -> free
      0 m              -> level ground never blocks
      AND the two cases the OLD either/or form let through — the whole reason
      the two limits hold together (finding F1/F2):
      0.18 m over 0.15 m -> the client's walking lead. The step limit is
                          untouched (0.18 ≤ 0.4), but atan(1.2) = 50.1944°
                          -> blocked. Under the either/or this was free here
                          and refused on the server's own 1.12 m report step.
      0.4 m over 0.1 m -> THE CRAWL. Exactly the step limit (0.4 ≤ 0.4), so
                          the either/or form waved it through and one climbed
                          any wall by reporting 10 cm at a time;
                          atan(4) = 75.9638° -> blocked.

  [2] THE SETTINGS. Both getters follow the ``get_travel_speed_m_s`` pattern:
      missing, non-numeric, bool, NaN, zero or negative fall back to the
      default (an emptied admin field arrives as 0, and reading that as "no
      step at all" would nail every walker to the spot), everything else is
      clamped — step into [0.05, 5], slope into [10, 89]. 89° and not 90°:
      at 90° the tangent explodes and the rule stops meaning anything.

  [3] THE HEIGHT IS THE WORLD BAKE, and there is no second one. ``ground_at``
      answers what ``ground_y`` answers, the scene payload carries NO
      ``terrain`` block any more, and the four symbols the old second ground
      was made of are GONE from their modules — a deletion is the one thing a
      positive check cannot measure, so it is asserted by name:
      ``relief.scene_ground_lift``, ``relief.ground_lift_at``,
      ``scene_recipe.compose_terrain`` and ``scatter_curves.terrain_grid``.

  [4] THE GATE, on the real route, at the cliff:
      a) (5004.5, 5020) -> (5005.0, 5020) is 0.5 m apart with Δh = 2.5 − 1.25 =
         +1.25 m: a step three times the limit -> 409 ``too_steep``, the
         message names the STEP, and the last valid point comes back so the
         client can snap the figure onto it. Both ends are 0.5 m / 1.0 m from
         the LEDGE opening at (5004, 5020) — but neither point lies IN the
         ledge, so no opening of any location the report touches is asked and
         the exemption cannot fire.
      b) THE SHALLOW FLANK: (5202, 5020) -> (5206, 5020) is 4 m apart with
         Δh = 1.5 − 0.5 = +1.0 m: atan(0.25) = 14.0362° < 40 -> accepted.
      c) THE COUNTER-PROBE, red without the rule: with ``max_step_height_m``
         at 5 m and ``max_slope_deg`` at 89° the IDENTICAL report of (a) is
         accepted. Nothing else in the chain changed, so the refusal in (a)
         was the height gate and only the height gate.
      d) THE OPENING IS A RAMP END (E8 inventory finding 8). Walking IN through
         the ledge's door, (5004.5, 5020) -> (5003.5, 5020), is Δh = 0 − 1.25 =
         −1.25 m over 1.0 m — a DESCENT, and since 2026-08-28 those are not
         judged at all, so this crossing passes before the exemption is even
         asked. The exemption is measured in the direction that still can
         refuse: back OUT and up, (5003.5, 5020) -> (5004.5, 5020), is
         Δh = +1.25 m over 1.0 m, i.e. atan(1.25) = 51.3402° and blocked on its
         own — but the departing point lies in the ledge and 0.5 m from its
         opening, inside the 1.5 m crossing tolerance -> accepted. Without the
         exemption a place at the foot of a cliff would be locked behind its
         own door.
      e) INERT WITHOUT A RELIEF: the same kind of report on PLAIN, where
         nobody shaped the ground, is accepted with both heights 0. That is why
         the gate cannot break a world without a relief — and why
         ``scripts/smoke_play_pos.py`` still passes unchanged.
      f) A 10 cm LEAD UP THE SAME FACE — finding F1 in one report.
         (5004.1, 5020) -> (5004.2, 5020) is Δh = 0.5 − 0.25 = +0.25 m, INSIDE
         the 0.4 m step cap, and atan(0.25 / 0.1) = 68.1986° all the same. The
         step limit alone is blind to a wall one approaches in small enough
         moves, which is exactly what the client's 0.15 m lead does. The
         message must name the SLOPE here, not a step that never fired.

  [5] A NATURAL PLACE DOES NOT FLATTEN THE GROUND IT STANDS ON. The GROVE on
      the flank draws no built floor (``draws_built_floor`` is False), so no
      plateau is stamped and the landscape runs through it: 1.5 m at its west
      edge, 2.5 m at its pin, 3.5 m at its east edge — the flank's own numbers.
      RED COUNTER-PROBE: give the very same plot ONE CLOSED ROOM and it becomes
      built, so the stamp fires and the whole footprint goes flat at the MEDIAN
      of the natural heights under it. Those 25 lattice samples are 5 × 1.5,
      5 × 2.0, 5 × 2.5, 5 × 3.0 and 5 × 3.5 (the flank depends on x alone
      there), whose 13th value is 2.5 — so west edge, pin and east edge all
      read 2.5 afterwards.

      This section used to measure the opposite arrangement: a hut WITHOUT a
      relief of its own inside a dome WITH one, resolved by "the innermost
      enclosing location that has a field wins". That whole mechanism is gone
      with the second ground (user decision 1) — there is one field, and who
      shapes it is decided in the bake, once, by :func:`draws_built_floor`.

  [6] THE WORLD RELIEF (E8 task 4). Until now the gate only ever saw a
      location's own scene field; outside every footprint the world was flat
      and the rule was inert there. ``ground_lift_at`` adds ``ground_y`` under
      all of it, and this section walks the OPEN WORLD.

      THE HILL: a height area (3000,3000)-(3040,3040), height 5, falloff 4 —
      rastered on the origin-anchored lattice of the TILES (step 2 since
      2026-08-14; ``ground_y`` reads those), so the support point (3000, z)
      sits ON the outline (height 0), (3002, z) is 2 m in (height 5·2/4 = 2.5)
      and (3004, z) is 4 m in (the full 5) for every z well inside.

      a) THE FLANK, in the wilderness, on the line z = 3008:
           h(3002, 3008) = 2.5      a support point, the ramp itself
           h(3003, 3008) = 2.5·0.5 + 5·0.5 = 3.75
         so a step of one metre rises 1.25 m: no step limit (dist is not below
         1 m) but atan(1.25 / 1) = 51.3402° > 40° -> 409 ``too_steep``, naming
         the SLOPE. The identical pair is what the client mirror is checked on
         (``smoke_world_height.mjs`` [4]) — same numbers, both sides.
      b) THE SAME HILL AT A SHALLOWER ANGLE: (3002,3008) -> (3006,3008) is
         2.5 m over 4 m, atan(0.625) = 32.0054° < 40° -> accepted. So it is
         the ANGLE that refuses, not the hill.
      c) RED COUNTER-PROBE: the location-free half of the height is 0 —
         ``scene_ground_lift(None, …)`` — so before task 4 the pair in (a) was
         0 against 0 and walked through. With ``max_slope_deg`` at 89 the very
         same report is accepted again, which pins the refusal on this rule.
      d) THE PLATEAU MAKES A PLACE ON A SLOPE WALKABLE, which is the whole
         point of the stamp — AND SINCE "EIN BODEN" E1 (§ G5) IT IS NOT A FLAG
         BUT A LAW: HOUSE gets a CLOSED ROOM, i.e. it draws a built floor, or
         it would stand on the untouched flank and repeat case (a) inside its
         own walls. HOUSE at (3000, 3020), plan_width_m 8 (so the drawn
         boundary is the centred 8 m square, world x ∈ [2996,3004],
         z ∈ [3016,3024]), no relief of its own, one opening on the E edge at
         0.5 -> world (3004, 3020).

         THE TARGET IS THE MEDIAN over the footprint, on the 2 m world
         lattice: x = 2996, 2998, 3000, 3002, 3004 in each of 5 rows, i.e.
         5 × (0, 0, 0, 2.5, 5.0) = 15 zeros, 5 × 2.5 and 5 × 5.0. The 13th of
         those 25 values is 0.0, so

             h0 = 0.0                     (the same number the old single
                                           interior probe gave, from a rule
                                           that no longer depends on one point)

         and the whole plot, edge included, is flat at 0:
           inside, (3001,3020) -> (3002,3020): Δh = 0 -> accepted, while the
           IDENTICAL metre out on the open flank (a) is refused.

      e) THE RAMP IS METRES WIDE NOW, and its width is derived. The 35° cap
         is on the STEEPEST metre, and a smoothstep peaks at 1.5× its mean
         gradient, so the widening carries the factor
         (``SMOOTHSTEP_PEAK = 1.5``):
             area = 64 m²  ->  0.5·sqrt(64/pi) = 4/sqrt(pi) = 2.256758… m
             rim step  = |0.0 − 5.0| = 5.0 m at the east edge (the hill is at
                         full height there)
             peak of that width: 1.5·5.0/2.256758 = 3.323… m/m, far over
             tan(35°) = 0.700208, so the width is WIDENED
             w = 1.5·5.0 / tan(35°) = 10.711110… m
         The tile lattice then carries, east of the plot (d = x − 3004),
         heights rounded to the raster's mm:
             (3004,3020) d = 0            -> 0.0
             (3006,3020) d = 2            -> 5·smoothstep(2/w)  = 0.458
             (3008,3020) d = 4            -> 5·smoothstep(4/w)  = 1.571
             (3012,3020) d = 8  < w!      -> 5·smoothstep(8/w)  = 4.201
             (3016,3020) d = 12 > w       -> the landscape, 5.0
         and ``ground_y`` mixes the lattice, so (3005,3020) is
         (0 + 0.458)/2 = 0.229.

         THE OPENING IS CROSSED WITHOUT ANY EXEMPTION: walking
         (3005,3020) -> (3003,3020) is 0.229 -> 0.0 over 2 m, atan(0.1145) =
         6.5°, far under the 40° gate. Before E1 the same crossing needed the
         pinned ring, and one cell further out it was a 68° wall; now it is a
         ramp.

         AND THE WHOLE RAMP IS WALKABLE BY CONSTRUCTION: the peak gradient is
         exactly tan(35°) at the ramp's midpoint, so no lattice segment can
         exceed it — the steepest measured 2-m segment is (3008 -> 3010),
         (2.949 − 1.571)/2 = 0.689 m/m = atan(0.689) = 34.57° < 35° < 40°.
         (The first cut of this wave capped the MEAN gradient instead, which
         left a steepest metre of 44.9° — over the gate; that behaviour is the
         red counter-probe below.)

Usage:  ./.venv/bin/python scripts/smoke_slope_gate.py
"""
import asyncio
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="slope-gate-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(
    prefix="slope-gate-smoke-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from fastapi import HTTPException  # noqa: E402

from app.core import config, relief, scene_recipe  # noqa: E402
from app.core.config_schema import SECTIONS  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models.account import set_active_character  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_pos, save_character_current_location, save_character_profile,
    set_character_pos, set_known_locations)
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location, get_location_by_id,
    list_locations, update_location_position)
from app.routes import play as play_route  # noqa: E402
from app.routes.play import play_pos  # noqa: E402

FAILURES = []
CHECKED = 0

# Game time is the world calendar — a canonical stamp, never a date.
START_GT = GameTime.parse("Y0001-D001T12:00:00")
USER = {"username": "demo", "role": "user"}
AVATAR = "demo_avatar"

# The fixture's dials, all of them authored numbers rather than defaults.
WIDTH_M = 8.0
#: The CLIFF: a height area whose ramp is two metres wide, so the 2 m world
#: lattice carries 0 at its outline and the full height one step in.
CLIFF_BOX = (5004.0, 5000.0, 5044.0, 5040.0)
CLIFF_H_M = 5.0
CLIFF_FALLOFF_M = 2.0
#: The FLANK: the same height over a twenty-metre ramp, i.e. h = d/4.
SLOPE_BOX = (5200.0, 5000.0, 5240.0, 5040.0)
SLOPE_H_M = 5.0
SLOPE_FALLOFF_M = 20.0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_true(label, cond, detail=""):
    global CHECKED
    CHECKED += 1
    ok = bool(cond)
    print(f"  {'✓' if ok else '✗'} {label}" + (f": {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def near(label, actual, expected, tol=1e-9):
    check_true(f"{label} = {expected}", abs(actual - expected) <= tol,
               f"{actual}")


# ── the hand-derived reference (§ B5a) ──────────────────────────────────

def ref_height(x: float, z: float, box, height: float, falloff: float
               ) -> float:
    """The height area rule, RE-IMPLEMENTED here — the smoke never trusts the
    source it verifies. Zero outside the outline, else
    ``height · min(1, d / falloff)`` with ``d`` the distance to the outline.
    Axis-aligned boxes only, which is what this fixture paints."""
    x0, z0, x1, z1 = box
    if not (x0 <= x <= x1 and z0 <= z <= z1):
        return 0.0
    d = min(x - x0, x1 - x, z - z0, z1 - z)
    return height * min(1.0, d / falloff) if falloff > 0 else height


def cliff_ref(x: float) -> float:
    """The cliff's LATTICE value at a support point on the line z = 5020."""
    return ref_height(x, 5020.0, CLIFF_BOX, CLIFF_H_M, CLIFF_FALLOFF_M)


def cliff_mix(x: float) -> float:
    """…and the bilinear read between two of them (the field is constant in z
    around z = 5020, so only the x pair mixes)."""
    lo = math.floor(x / 2.0) * 2.0
    t = (x - lo) / 2.0
    return cliff_ref(lo) * (1.0 - t) + cliff_ref(lo + 2.0) * t


# ── the world ───────────────────────────────────────────────────────────

def set_map3d(location_id: str, **fields) -> None:
    """Merge fields into a location's map3d blob (boundary, openings).

    A ``plan_width_m`` handed in is DRAWN as the centred square of that edge
    (clockwise in map view) and the width is kept alongside — exactly what
    ``_sanitize_map3d`` stores for such an outline. Since 2026-08-19 the width
    alone is no shape at all: a location without a drawn boundary has no area
    anywhere, so every fixture that wants ground has to say so.
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


def make_built(location_id: str) -> None:
    """Give a place a CLOSED room, which is what makes it stamp its plot.

    Since "Ein Boden" E1 (§ G5) the plateau is not a flag any more: a location
    that draws a BUILT floor — a ``map3d.outline`` or at least one room that
    is not ``always_visible`` — planes the ground under itself, and a natural
    one (a lake, a clearing) leaves the landscape running through it. A house
    on a flank is the case the rule was written for.
    """
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            rooms = list(loc.get("rooms") or [])
            rooms.append({"id": "hall", "name": "Hall", "layout": {}})
            loc["rooms"] = rooms
    _save_world_data(data)


def place(name: str, x: float, z: float, *, width: float = WIDTH_M,
          opening_edge=None) -> str:
    """A NATURAL location: a drawn boundary and nothing else.

    No ``map3d.outline`` and no room at all, so ``draws_built_floor`` is False
    and the bake stamps NO plateau under it (§ G5) — which is exactly what
    every place in this fixture needs, because a plateau would plane away the
    very flank the gate is measured on. ``opening_edge`` draws one boundary
    opening in the middle of that edge (edge 1 = the east side of a centred
    square, i.e. world ``(x + width/2, z)``).
    """
    loc_id = add_location(name=name, description="slope-gate smoke")["id"]
    update_location_position(loc_id, x, z)
    fields = {"plan_width_m": width}
    if opening_edge is not None:
        fields["boundary_openings"] = [
            {"edge": int(opening_edge), "at": 0.5, "width_m": 2.0,
             "type": "passage", "room": ""}]
    set_map3d(loc_id, **fields)
    return loc_id


class _FakeRequest:
    """Minimal stand-in: the route only ever awaits ``request.json()``."""

    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


def report(x: float, z: float):
    """POST /play/pos → ("ok", payload) or ("refused", (status, detail))."""
    try:
        return "ok", asyncio.run(play_pos(_FakeRequest({"x": x, "z": z}),
                                          user=USER))
    except HTTPException as exc:
        return "refused", (exc.status_code, exc.detail)


def park(x: float, z: float, location_id: str = "") -> None:
    """World setup, not a move: put the avatar at a point (and in a place) and
    forget the report clock, so the next report is judged like a session's
    first one — no step-plausibility baseline, which is exactly the state the
    height gate has to work in as well."""
    set_character_pos(AVATAR, x, z)
    save_character_current_location(AVATAR, location_id, sync_pos=False)
    play_route._pos_report_at.pop(AVATAR, None)


def refusal_of(res):
    status, detail = res[1]
    detail = detail if isinstance(detail, dict) else {"message": detail}
    return status, detail.get("reason"), detail.get("pos"), \
        detail.get("message")


set_game_factor(0.0)
set_game_time(START_GT)

# The two painted flanks the gate is measured on. They are WORLD height areas
# — the only kind of relief left (user decision 1) — and they are stored before
# any place is put on them, so every number below is the landscape's own.
from app.models import heightfield as store  # noqa: E402
store.save_height_area({"id": "cliff", "height_m": CLIFF_H_M,
                        "falloff_m": CLIFF_FALLOFF_M,
                        "polygon": [[CLIFF_BOX[0], CLIFF_BOX[1]],
                                    [CLIFF_BOX[2], CLIFF_BOX[1]],
                                    [CLIFF_BOX[2], CLIFF_BOX[3]],
                                    [CLIFF_BOX[0], CLIFF_BOX[3]]]})
store.save_height_area({"id": "flank", "height_m": SLOPE_H_M,
                        "falloff_m": SLOPE_FALLOFF_M,
                        "polygon": [[SLOPE_BOX[0], SLOPE_BOX[1]],
                                    [SLOPE_BOX[2], SLOPE_BOX[1]],
                                    [SLOPE_BOX[2], SLOPE_BOX[3]],
                                    [SLOPE_BOX[0], SLOPE_BOX[3]]]})

# The LEDGE sits at the foot of the cliff, its east opening exactly on the
# outline the wall starts at: world (5000 + 4, 5020) = (5004, 5020).
LEDGE = place("Smoke Ledge", 5000.0, 5020.0, opening_edge=1)
# The GROVE stands ON the long flank — a place that draws no floor.
GROVE = place("Smoke Grove", 5210.0, 5020.0)
# A place on ground nobody shaped: the inert case.
PLAIN = place("Smoke Flat", 1600.0, 1000.0)

save_character_profile(AVATAR, {"current_location": "", "language": "en"},
                       create_new=True)
set_character_pos(AVATAR, 0.0, 0.0)
set_known_locations(AVATAR, [LEDGE, GROVE, PLAIN])
set_active_character(AVATAR)
# The throttle is the one rule about wall time and is not what this file
# measures — off, so no case has to sleep.
play_route._POS_REPORT_INTERVAL_S = 0.0


def main() -> int:
    print("\n[1] slope_blocks — the pure rule, mirrored by the client")
    STEP, SLOPE = 0.4, 40.0
    check("1.2 m over 0.5 m is a wall",
          relief.slope_blocks(1.2, 0.5, STEP, SLOPE), True)
    check("0.3 m over 2 m (8.53°) is walked",
          relief.slope_blocks(0.3, 2.0, STEP, SLOPE), False)
    check("0.3 m over 0.5 m stays under the step cap",
          relief.slope_blocks(0.3, 0.5, STEP, SLOPE), False)
    check("the cap itself passes (strictly greater blocks)",
          relief.slope_blocks(0.4, 0.5, STEP, SLOPE), False)
    check("a DROP is never judged — only climbing is (rule 2026-08-28)",
          relief.slope_blocks(-1.2, 0.5, STEP, SLOPE), False)
    check("...nor a 0.9 m drop over 0.5 m",
          relief.slope_blocks(-0.9, 0.5, STEP, SLOPE), False)
    check("...nor three metres straight down over one",
          relief.slope_blocks(-3.0, 1.0, STEP, SLOPE), False)
    check("but the SAME 0.9 m upwards over 0.5 m is a step",
          relief.slope_blocks(0.9, 0.5, STEP, SLOPE), True)
    check("45° over 2 m is refused",
          relief.slope_blocks(2.0, 2.0, STEP, SLOPE), True)
    check("38.66° over the same 2 m is not",
          relief.slope_blocks(1.6, 2.0, STEP, SLOPE), False)
    check("...and the same rise a hair under the metre is a step",
          relief.slope_blocks(1.6, 0.99, STEP, SLOPE), True)
    check("one metre exactly is already a slope (26.57°)",
          relief.slope_blocks(0.5, 1.0, STEP, SLOPE), False)
    check("level ground never blocks",
          relief.slope_blocks(0.0, 0.0, STEP, SLOPE), False)
    check("the step/slope line is one metre", relief.STEP_DISTANCE_M, 1.0)

    print("\n[1e] the two limits hold TOGETHER (findings F1/F2)")
    # The angle both cases turn on, spelled out rather than trusted.
    near("0.18 m over a 0.15 m walking lead",
         math.degrees(math.atan2(0.18, 0.15)), 50.1944, 1e-4)
    near("0.4 m over a 0.1 m crawl", math.degrees(math.atan2(0.4, 0.1)),
         75.9638, 1e-4)
    check("the client's 0.15 m lead sees the 50° wall too",
          relief.slope_blocks(0.18, 0.15, STEP, SLOPE), True)
    check("...and crawling 10 cm at a time does not climb it either",
          relief.slope_blocks(0.4, 0.1, STEP, SLOPE), True)

    def old_either_or(dh, dist, max_step, max_slope):
        """THE RED COUNTER-PROBE: the either/or form this rule started as —
        a step under a metre, a slope above it, never both."""
        rise = abs(dh)
        if not rise:
            return False
        if dist < 1.0:
            return rise > max_step
        return math.degrees(math.atan2(rise, dist)) > max_slope

    check("the old form let the 50° lead through",
          old_either_or(0.18, 0.15, STEP, SLOPE), False)
    check("...and the crawl as well — which is why it is gone",
          old_either_or(0.4, 0.1, STEP, SLOPE), False)
    # THE SHARED TABLE, the one the client's `smoke_walk_math.mjs` checks its
    # own mirror against, row for row. Every negative Δh answers False since
    # the climbing rule of 2026-08-28.
    for dh, dist, expected in ((1.2, 0.5, True), (0.3, 2.0, False),
                               (0.3, 0.5, False), (0.4, 0.5, False),
                               (-1.2, 0.5, False), (-0.9, 0.5, False),
                               (-3.0, 1.0, False), (0.9, 0.5, True),
                               (2.0, 2.0, True),
                               (1.6, 2.0, False), (1.6, 0.99, True),
                               (0.5, 1.0, False), (0.0, 0.0, False)):
        check(f"the shared table: {dh} m / {dist} m",
              relief.slope_blocks(dh, dist, STEP, SLOPE), expected)

    print("\n[2] the two world settings (the get_travel_speed_m_s pattern)")
    game = config._CONFIG.setdefault("game", {})
    game.pop("max_step_height_m", None)
    game.pop("max_slope_deg", None)
    near("unset step → default", relief.get_max_step_height_m(), 0.4)
    near("unset slope → default", relief.get_max_slope_deg(), 40.0)
    for raw, expected in ((0.8, 0.8), (0.01, 0.05), (9, 5.0), (0, 0.4),
                          (-1, 0.4), ("high", 0.4), (True, 0.4),
                          (float("nan"), 0.4), (None, 0.4)):
        game["max_step_height_m"] = raw
        near(f"step {raw!r}", relief.get_max_step_height_m(), expected)
    for raw, expected in ((55, 55.0), (5, 10.0), (120, 89.0), (0, 40.0),
                          (-3, 40.0), ("steep", 40.0), (True, 40.0),
                          (float("nan"), 40.0), (None, 40.0)):
        game["max_slope_deg"] = raw
        near(f"slope {raw!r}", relief.get_max_slope_deg(), expected)
    game.pop("max_step_height_m", None)
    game.pop("max_slope_deg", None)
    check("the step limit is in the admin schema",
          "max_step_height_m" in SECTIONS["game"]["fields"], True)
    check("...and so is the slope limit",
          "max_slope_deg" in SECTIONS["game"]["fields"], True)

    print("\n[3] ONE ground — the world bake, and the deleted second one")
    from app.core import scatter_curves  # noqa: E402
    from app.core.world_geometry import ground_y  # noqa: E402
    # The cliff, as the lattice carries it and as the mix reads it. Every
    # number of section [4] comes off these four.
    near("the support point ON the outline is 0", ground_y(5004.0, 5020.0),
         cliff_ref(5004.0))
    near("...and it really is 0", ground_y(5004.0, 5020.0), 0.0)
    near("two metres in, the full 5 m", ground_y(5006.0, 5020.0),
         cliff_ref(5006.0))
    near("...and it really is 5", ground_y(5006.0, 5020.0), 5.0)
    for probe in (5004.1, 5004.2, 5004.5, 5005.0):
        near(f"the mix at x = {probe}", ground_y(probe, 5020.0),
             cliff_mix(probe), 1e-9)
    near("...which spells 1.25 at 5004.5", ground_y(5004.5, 5020.0), 1.25)
    near("...and 2.5 at 5005.0", ground_y(5005.0, 5020.0), 2.5)
    # THE RULE ASKS THE SAME FUNCTION, with no location in the question.
    near("relief.ground_at IS ground_y", relief.ground_at(5004.5, 5020.0),
         ground_y(5004.5, 5020.0))
    near("...out in the flat world too", relief.ground_at(0.0, 0.0),
         ground_y(0.0, 0.0))
    # THE SECOND GROUND IS GONE. A deletion is the one thing a positive check
    # cannot measure, so the four names are asserted by absence.
    scene = scene_recipe.compose_scene(get_location_by_id(LEDGE),
                                       plan_width_m=WIDTH_M)
    check_true("the scene payload carries no `terrain` block",
               "terrain" not in scene)
    check_true("...and no `natural_floor` flag either",
               "natural_floor" not in scene)
    for mod, name in ((relief, "scene_ground_lift"),
                      (relief, "ground_lift_at"),
                      (relief, "has_relief"),
                      (scene_recipe, "compose_terrain"),
                      (scene_recipe, "terrain_frame"),
                      (scatter_curves, "terrain_grid"),
                      (scatter_curves, "relief_cells"),
                      (scatter_curves, "terrain_height")):
        check_true(f"red: {mod.__name__.split('.')[-1]}.{name} is deleted",
                   not hasattr(mod, name))

    print("\n[4a] the cliff refuses: 1.25 m of step over 0.5 m")
    a_x, a_z = 5004.5, 5020.0
    b_x, b_z = 5005.0, 5020.0
    near("the rise between them",
         ground_y(b_x, b_z) - ground_y(a_x, a_z), 1.25, 1e-9)
    check_true("...which is a STEP, three times the 0.4 m cap",
               relief.slope_blocks(1.25, 0.5, 0.4, 40.0))
    park(a_x, a_z, "")
    res = report(b_x, b_z)
    status, reason, pos, message = refusal_of(res)
    check("refused", res[0], "refused")
    check("the status", status, 409)
    check("the reason", reason, "too_steep")
    check("the message names the STEP", message,
          "That step is too high to climb.")
    check("the last valid point comes back", pos, {"x": a_x, "z": a_z})
    check("the avatar did not move", get_character_pos(AVATAR),
          {"x": a_x, "z": a_z})
    # …and the exemption is NOT what could have saved it: neither end lies in
    # the ledge, so no opening of any location this report touches is read.
    from app.core.world_geometry import location_at_point  # noqa: E402
    check("neither end of [4a] lies in a location",
          [location_at_point(a_x, a_z, list_locations()),
           location_at_point(b_x, b_z, list_locations())], [None, None])

    print("\n[4b] the gentle flank is walked: 14.04° over 4 m")
    c_x, c_z = 5202.0, 5020.0
    d_x, d_z = 5206.0, 5020.0
    near("the flank at 5202", ground_y(c_x, c_z), 0.5, 1e-9)
    near("...and at 5206", ground_y(d_x, d_z), 1.5, 1e-9)
    near("its angle", math.degrees(math.atan2(1.0, 4.0)), 14.0362, 1e-4)
    park(c_x, c_z, "")
    status, payload = report(d_x, d_z)
    check("accepted", (payload or {}).get("ok") if status == "ok" else status,
          True)
    check("the avatar stands on the new point", get_character_pos(AVATAR),
          {"x": d_x, "z": d_z})

    print("\n[4c] THE COUNTER-PROBE — with the limits wide open it goes")
    game["max_step_height_m"] = 5.0
    game["max_slope_deg"] = 89.0
    park(a_x, a_z, "")
    status, payload = report(b_x, b_z)
    check("the very same report of [4a] is accepted",
          (payload or {}).get("ok") if status == "ok" else status, True)
    check("...and the avatar really moved up the cliff",
          get_character_pos(AVATAR), {"x": b_x, "z": b_z})
    game.pop("max_step_height_m", None)
    game.pop("max_slope_deg", None)

    print("\n[4d] an opening is a RAMP END — walking in is let through")
    from app.core.boundary_entry import opening_world_points  # noqa: E402
    check("the ledge's opening sits on its east edge",
          opening_world_points(get_location_by_id(LEDGE)),
          [(1, (5004.0, 5020.0))])
    in_x, in_z = 5003.5, 5020.0
    near("the ground inside the ledge is untouched flat", ground_y(in_x, in_z),
         0.0)
    check_true("walking IN is a DESCENT and is not judged at all",
               not relief.slope_blocks(0.0 - 1.25, 1.0, 0.4, 40.0))
    near("its angle", math.degrees(math.atan2(1.25, 1.0)), 51.3402, 1e-4)
    near("but the arriving point is 0.5 m from the opening",
         math.dist((in_x, in_z), (5004.0, 5020.0)), 0.5, 1e-9)
    park(a_x, a_z, "")
    status, payload = report(in_x, in_z)
    check("accepted at the door", (payload or {}).get("ok")
          if status == "ok" else status, True)
    check("...and it is the ledge one stands in",
          (payload or {}).get("location_id"), LEDGE)
    # THE OTHER WAY, which is the one the exemption is still for: back out and
    # UP the same 1.25 m over the same metre blocks on its own, and only the
    # opening lets it through.
    check_true("the way back OUT and up blocks on its own",
               relief.slope_blocks(1.25 - 0.0, 1.0, 0.4, 40.0))
    park(in_x, in_z, LEDGE)
    status, payload = report(a_x, a_z)
    check("...but the door exempts it", (payload or {}).get("ok")
          if status == "ok" else status, True)
    check("...and the avatar climbed out", get_character_pos(AVATAR),
          {"x": a_x, "z": a_z})

    print("\n[4f] a 10 cm lead up the same face — the SLOPE limit catches it")
    lead_a, lead_b = 5004.1, 5004.2
    near("the height 10 cm up the face", ground_y(lead_a, 5020.0), 0.25, 1e-9)
    near("...and 10 cm further", ground_y(lead_b, 5020.0), 0.5, 1e-9)
    check_true("the step cap alone would let it pass", 0.25 <= 0.4)
    near("its angle", math.degrees(math.atan2(0.25, 0.1)), 68.1986, 1e-4)
    park(lead_a, 5020.0, "")
    res = report(lead_b, 5020.0)
    status, reason, _pos, message = refusal_of(res)
    check("refused", res[0], "refused")
    check("the reason", reason, "too_steep")
    check("the message names the SLOPE", message,
          "That slope is too steep to climb.")

    print("\n[4e] inert where nobody shaped the ground")
    near("both heights are 0", ground_y(1600.5, 1000.0), 0.0)
    park(1600.0, 1000.0, PLAIN)
    status, payload = report(1600.5, 1000.0)
    check("the identical geometry on flat ground is accepted",
          (payload or {}).get("ok") if status == "ok" else status, True)

    print("\n[5] a NATURAL place lets the landscape run through it")
    from app.models.heightfield import draws_built_floor  # noqa: E402
    grove = get_location_by_id(GROVE)
    check("the grove draws no built floor", draws_built_floor(grove), False)
    for x, expected in ((5206.0, 1.5), (5210.0, 2.5), (5214.0, 3.5)):
        near(f"...so the flank runs on at x = {x}", ground_y(x, 5020.0),
             expected, 1e-9)
    # RED COUNTER-PROBE: one closed room makes the very same plot BUILT, the
    # stamp fires, and the footprint goes flat at the MEDIAN of the 25 lattice
    # samples under it — 5 each of 1.5/2.0/2.5/3.0/3.5, whose 13th is 2.5.
    make_built(GROVE)
    check("...and ONE closed room makes it built",
          draws_built_floor(get_location_by_id(GROVE)), True)
    for x in (5206.0, 5210.0, 5214.0):
        near(f"red: the plot is now flat at the median, x = {x}",
             ground_y(x, 5020.0), 2.5, 1e-9)

    print("\n[6] THE WORLD RELIEF — the gate outside every scene")
    store.save_height_area({"id": "hill", "height_m": 5.0, "falloff_m": 4.0,
                            "polygon": [[3000, 3000], [3040, 3000],
                                        [3040, 3040], [3000, 3040]]})
    near("the flank at (3002, 3008)", ground_y(3002, 3008), 2.5)
    near("the flank at (3003, 3008)", ground_y(3003, 3008), 3.75)
    near("the rule reads the world and nothing else",
         relief.ground_at(3002, 3008), 2.5)
    near("the angle over one metre",
         math.degrees(math.atan2(1.25, 1.0)), 51.3402, 1e-4)
    park(3002.0, 3008.0, "")
    res = report(3003.0, 3008.0)
    status, reason, pos, message = refusal_of(res) if res[0] == "refused" \
        else (200, "", None, "")
    check("a metre up the world flank is refused", res[0], "refused")
    check("the reason", reason, "too_steep")
    check("the message names the SLOPE", message,
          "That slope is too steep to climb.")
    check("...and the last valid point comes back", pos,
          {"x": 3002.0, "z": 3008.0})

    near("the same hill over four metres", ground_y(3006, 3008), 5.0)
    near("its angle", math.degrees(math.atan2(2.5, 4.0)), 32.0054, 1e-4)
    park(3002.0, 3008.0, "")
    status, payload = report(3006.0, 3008.0)
    check("the shallower way up the same hill is accepted",
          (payload or {}).get("ok") if status == "ok" else status, True)

    config._CONFIG.setdefault("game", {})["max_slope_deg"] = 89.0
    park(3002.0, 3008.0, "")
    status, payload = report(3003.0, 3008.0)
    check("RED COUNTER-PROBE: at 89° the identical report passes",
          (payload or {}).get("ok") if status == "ok" else status, True)
    config._CONFIG.setdefault("game", {}).pop("max_slope_deg", None)

    HOUSE = add_location(name="Smoke House",
                         description="slope-gate smoke")["id"]
    update_location_position(HOUSE, 3000.0, 3020.0)
    set_map3d(HOUSE, plan_width_m=8.0,
              boundary_openings=[{"edge": 1, "at": 0.5, "width_m": 2.0,
                                  "type": "passage", "room": ""}])
    # A place stamps its plot because it DRAWS A BUILT FLOOR (E1, § G5) —
    # here one closed room. Without it this house would stand on the untouched
    # flank, which is case (a) all over again.
    make_built(HOUSE)
    set_known_locations(AVATAR, [LEDGE, GROVE, PLAIN, HOUSE])
    check("the opening sits on the east edge (index 1)",
          opening_world_points(get_location_by_id(HOUSE)),
          [(1, (3004.0, 3020.0))])
    near("the plateau target is the MEDIAN under the footprint",
         ground_y(3000, 3020), 0.0)
    near("...flat across the footprint, (3001,3020)", ground_y(3001, 3020), 0.0)
    near("...and (3002,3020)", ground_y(3002, 3020), 0.0)
    near("...right up to its own east edge, (3004,3020)",
         ground_y(3004, 3020), 0.0)
    # RED COUNTER-PROBE for the levelling: the SAME metre on the raster
    # WITHOUT the plateau pass rises 1.25 m (1.25 -> 2.5, the flank), i.e. the
    # very 51° the open flank is refused for.
    from app.core import heightfield as hf  # noqa: E402
    # The HILL alone: the fixture also paints the cliff and the flank two
    # kilometres east, and a raster over all three spans a box wide enough for
    # ``_step_for`` to coarsen it — which would measure the doubling, not the
    # plateau.
    _bare = hf.rasterize([a for a in store.list_height_areas()
                          if a["id"] == "hill"])
    near("unlevelled, the house's floor would rise from 1.25...",
         hf.sample_height(_bare, 3001, 3020), 1.25)
    near("...to 2.5 over that same metre",
         hf.sample_height(_bare, 3002, 3020), 2.5)
    check_true("...which is exactly the 51° the open flank is refused for",
               relief.slope_blocks(1.25, 1.0, 0.4, 40.0))
    park(3001.0, 3020.0, HOUSE)
    status, payload = report(3002.0, 3020.0)
    check("a metre INSIDE the place on the slope is accepted",
          (payload or {}).get("ok") if status == "ok" else status, True)
    park(3005.0, 3020.0, "")
    status, payload = report(3003.0, 3020.0)
    check("...and so is walking in through the opening",
          (payload or {}).get("ok") if status == "ok" else status, True)
    check("...into the house", (payload or {}).get("location_id"), HOUSE)
    def _ss(t):
        t = min(max(t, 0.0), 1.0)
        return t * t * (3.0 - 2.0 * t)

    _w0 = 0.5 * math.sqrt(64.0 / math.pi)
    _tan35 = math.tan(math.radians(35.0))
    near("the un-capped ramp would be 0.5·sqrt(64/pi) = 2.2568 m", _w0,
         2.2567583341910251, 1e-12)
    check_true("...but its PEAK 1.5·5.0/w0 would be steeper than tan(35°)",
               1.5 * 5.0 > _tan35 * _w0)
    W_RAMP = 1.5 * 5.0 / _tan35
    near("so the ramp is widened to 1.5·5.0/tan(35°) = 10.71111 m", W_RAMP,
         10.71111005056586, 1e-9)
    near("the RAMP outside, h(3006,3020) = 5·smoothstep(2/w)",
         ground_y(3006, 3020), round(5.0 * _ss(2.0 / W_RAMP), 3), 1e-9)
    near("...which is 0.458", ground_y(3006, 3020), 0.458, 1e-9)
    near("...h(3008,3020) = 5·smoothstep(4/w) = 1.571",
         ground_y(3008, 3020), 1.571, 1e-9)
    near("...d = 8 is still INSIDE this wider ramp, h(3012,3020) = 4.201",
         ground_y(3012, 3020), 4.201, 1e-9)
    near("...and past the ramp the landscape is untouched, h(3016,3020)",
         ground_y(3016, 3020), 5.0)
    near("...so the mixed lattice puts (3005,3020) at 0.229",
         ground_y(3005, 3020), 0.229, 1e-9)
    check_true("WALKABLE BY CONSTRUCTION: the steepest 2-m segment "
               "(3008 -> 3010) stays under the 40° gate",
               not relief.slope_blocks(
                   ground_y(3010, 3020) - ground_y(3008, 3020),
                   2.0, 0.4, 40.0))
    near("...its angle is 34.57° — under the 35° peak cap itself",
         math.degrees(math.atan2(
             ground_y(3010, 3020) - ground_y(3008, 3020), 2.0)),
         34.5662, 1e-3)
    # RED COUNTER-PROBE of the first cut (mean-gradient cap, w = Δ/tan35 =
    # 7.14074 m): its lattice would carry h(3006) = 0.957 and h(3008) = 2.949,
    # a segment of (2.949 − 0.957)/2 = 0.996 m/m = 44.9° — OVER the gate. The
    # baked field must NOT reproduce those numbers.
    check_true("red: the mean-cap ramp value 0.957 at (3006,3020) is gone",
               abs(ground_y(3006, 3020) - 0.957) > 1e-6)
    check_true("red: the 44.9° segment of the mean-cap ramp does not exist",
               math.degrees(math.atan2(
                   ground_y(3008, 3020) - ground_y(3006, 3020), 2.0)) < 35.0)

    print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
    for f in FAILURES:
        print(f"  ✗ {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        import shutil
        shutil.rmtree(STORAGE, ignore_errors=True)
