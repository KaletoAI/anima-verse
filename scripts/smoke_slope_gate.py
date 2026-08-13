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

    ALWAYS       -> a SLOPE: atan(|Δh| / dist) > game.max_slope_deg  (def. 40)
    dist < 1 m   -> AND a STEP: |Δh| > game.max_step_height_m    (default 0.4)

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

THE HEIGHT ITSELF comes from ``relief.scene_ground_lift``, and it samples the
VERY grid ``compose_scene`` ships to the renderers (``scene_recipe``'s single
``compose_terrain``): seed, wave width, flat hulls, tile rotation, all of it
derived once. That is the whole reason this smoke cross-checks the gate's
height against the composed payload in section [3] — the rule and the picture
have to stand on one ground, and the only way they can drift is a second
derivation.

THE WORLD used below:

    CLIFF   (1000, 1000)  plan_width_m 8, yaw 0, area_detail with a relief
                          (seed 1, amplitude 6 m, wave 0.5 m), ONE opening on
                          the N edge at 0.5 -> world (1000, 996)
    TURNED  (1200, 1000)  the same location turned by yaw 90
    SPUN    (1400, 1000)  the same location with map3d.tile_rotation 90
    PLAIN   (1600, 1000)  the same geometry WITHOUT a relief (the inert case)
    DOME    (2000, 1000)  plan_width_m 8 with a WIDE wave (4 m -> 2 cells, so
                          3 × 3 support points and exactly ONE free value in
                          the middle): a single gentle dome, amplitude 4.
                          NO opening — a free boundary
    HUT     (2000, 1000)  2 m wide, NO relief and no opening either, sitting
                          INSIDE the dome — the nesting case of finding F3.
                          Neither draws a door, so nothing in [5] can be
                          exempt for standing at one

HAND-DERIVED EXPECTATIONS.

The grid. ``relief_cells(wave 0.5, extent 8) = round(8 / 0.5) = 16`` cells, so
17 support points per side and a cell of ``8 / 16 = 0.5`` m. Point (i, j) sits
at plan fraction (i/16, j/16); the border (i or j at 0 or 16) is pinned to 0,
and every other point draws ONE xorshift32 number from the spatial hash
``seed + i·73856093 + j·19349663``, mapped from [0, 1) to [−1, 1) and scaled by
the amplitude. This file re-implements that PRNG independently (§ B5a: the
smoke never trusts the source it verifies) and builds its own reference field,
so every height below is derived, not recorded. With seed 1 and amplitude 6 the
row j = 1 opens

    i = 1 -> +1.5555   i = 2 -> −3.4171   i = 5 -> +2.0343
    i = 8 -> +5.8997   i = 9 -> +3.9900

The frame. The payload is anchored around the TILE CENTRE in the location's own
turned frame, so a node (i, j) sits at local ``(i·0.5 − 4, j·0.5 − 4)`` and, at
yaw 0, at world ``(1000 + i·0.5 − 4, 1000 + j·0.5 − 4)``. Sampling exactly on a
node returns that node's value (``u·n`` is a whole number, so the bilinear
weight is 0).

  [1] THE PREDICATE, the same table the client checks (limits 0.4 m / 40°):
      1.2 m over 0.5 m -> a STEP, 1.2 > 0.4                 -> blocked
      0.3 m over 2 m   -> atan(0.15) = 8.5308°              -> free
      0.3 m over 0.5 m -> step 0.3 ≤ 0.4, angle 30.9638°    -> free
      0.4 m over 0.5 m -> the step limit itself passes (strict >), and
                          atan(0.8) = 38.6598° < 40         -> free
      −1.2 m over 0.5 m -> a drop is the same wall           -> blocked
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

  [3] THE HEIGHT, against the composed payload. ``scene_ground_lift`` at the
      five nodes above returns exactly the reference values; the pinned border
      (1000, 996) returns 0; a location without a relief, an unplaced one and
      ``None`` return 0. And the grid the gate samples IS the grid
      ``compose_scene`` ships — checked cell by cell, because a second
      derivation of the field is the one way rule and picture can drift.
      TURNED (yaw 90) puts node (1, 1) at ``(cx + lz, cz − lx)`` =
      (1196.5, 1003.5) and must answer the same +1.5555. SPUN
      (tile_rotation 90) resamples the field as ``new[j][i] = old[16−i][j]``,
      so its node (1, 1) answers the reference field's ``old[15][1]``.

  [4] THE GATE, on the real route. The avatar stands INSIDE the location, so
      no transition gate is involved and nothing but the height can refuse:
      a) node (1,1) -> node (2,1) is 0.5 m apart with Δh = −3.4171 − 1.5555 =
         −4.9726 m: a step 12× the limit -> 409 ``too_steep``, the message
         names the STEP, and the last valid point comes back so the client can
         snap the figure onto it. Neither end is near the opening: node (1,1)
         is hypot(3.5, 0.5) = 3.5355 m from (1000, 996), node (2,1)
         hypot(3, 0.5) = 3.0414 m — both well past the 1.5 m tolerance.
      b) node (1,1) -> node (5,1) is 2 m apart with Δh = 2.0343 − 1.5555 =
         +0.4788 m: atan(0.4788 / 2) = 13.4632° < 40 -> accepted. The nearer
         end is still 1.5811 m from the opening, so this is the RULE letting
         it through and not the exemption.
      c) THE COUNTER-PROBE, red without the rule: with ``max_step_height_m``
         at 5 m and ``max_slope_deg`` at 89° the IDENTICAL report of (a) is
         accepted. Nothing else in the chain changed, so the refusal in (a)
         was the height gate and only the height gate.
      d) THE OPENING IS A RAMP END (E8 inventory finding 8). Node (8,1) ->
         node (9,1) is the same kind of cliff (Δh = 3.99 − 5.8997 = −1.9097 m
         over 0.5 m), but node (8,1) sits 0.5 m and node (9,1)
         hypot(0.5, 0.5) = 0.7071 m from the opening — inside the 1.5 m
         crossing tolerance -> accepted. Without the exemption a place on its
         own plateau would be locked behind its own door.
      e) INERT WITHOUT A RELIEF: the identical geometry on PLAIN (no
         ``map3d.relief``) is accepted, both heights being 0. That is why the
         gate cannot break a world that has no relief at all — and why
         ``scripts/smoke_play_pos.py`` still passes unchanged.
      f) A 2 cm LEAD UP THE SAME FACE — finding F1 in one report. The field is
         linear inside a cell, so 0.02 m along the (1,1)->(2,1) edge is 0.04 of
         it: h = 1.5555 · 0.96 + (−3.4171) · 0.04 = 1.356596, i.e.
         Δh = −0.198904 — INSIDE the 0.4 m step cap, and atan(0.198904 / 0.02)
         = 84.2582° all the same. The step limit alone is blind to a wall one
         approaches in small enough moves, which is exactly what the client's
         0.15 m lead does. The message must name the SLOPE here, not a step
         that never fired.

  [5] NESTING (finding F3). A place without a relief of its own does not
      flatten the ground it stands on — it stands ON it, so the height comes
      from the innermost ENCLOSING location that HAS a field
      (``relief.ground_lift_at``). DOME's field is hand-derivable to the last
      digit: 2 cells per axis means 3 × 3 support points, the border is pinned,
      so the ONLY free value is the middle one — grid[1][1] = 1.037 at the tile
      centre — and everything between is bilinear over a 4 m cell.
      The two probe points sit on the centre line (u = 0.5), 0.5 m apart:
        (2000, 1001.4) -> v = 1.4/8 + 0.5 = 0.675, fy = 1.35, ty = 0.35
                          -> 1.037 · 0.65  = 0.674050   (outside the hut)
        (2000, 1000.9) -> v = 0.9/8 + 0.5 = 0.6125, fy = 1.225, ty = 0.225
                          -> 1.037 · 0.775 = 0.803675   (INSIDE the hut)
      WITH the fix both come off DOME: Δh = −0.129625 over 0.5 m, no step
      (0.1296 ≤ 0.4) and atan(0.25925) = 14.534° < 40 -> accepted.
      RED COUNTER-PROBE: the hut's OWN lift is 0.0, so before the fix the pair
      read Δh = 0.674050 over 0.5 m — a step 1.7× the limit, i.e. a 53.4°
      cliff nobody authored, sealing an openingless hut from every side. The
      smoke asserts both: that ``scene_ground_lift`` on the hut alone is still
      0, that the old difference WOULD block, and that the route accepts.

Usage:  ./.venv/bin/python scripts/smoke_slope_gate.py
"""
import asyncio
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
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

START_DT = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
USER = {"username": "demo", "role": "user"}
AVATAR = "demo_avatar"

# The fixture's dials, all of them authored numbers rather than defaults.
SEED = 1
AMPLITUDE_M = 6.0
WAVE_M = 0.5
WIDTH_M = 8.0
CELLS = 16
CELL_M = WIDTH_M / CELLS          # 0.5 m


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


# ── an INDEPENDENT reference height field (§ B5a) ───────────────────────

def xorshift32_ref(seed: int):
    """Re-implementation of the contract PRNG — the smoke never trusts the
    source it verifies. Three lines on uint32: ``x ^= x<<13; x ^= x>>17;
    x ^= x<<5``, seed 0 reads as 1."""
    x = (seed & 0xFFFFFFFF) or 1
    while True:
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        yield x / 4294967296.0


def ref_grid(seed: int, amplitude: float, n: int):
    """The height field by hand: border pinned to 0, every other point ONE
    draw from the spatial hash ``seed + i·73856093 + j·19349663``, mapped to
    [−1, 1) and scaled — rounded to 4 places, never −0.0 (no flat hulls in
    this fixture, so the pinning rule is the border alone)."""
    grid = []
    for j in range(n + 1):
        row = []
        for i in range(n + 1):
            if i in (0, n) or j in (0, n):
                row.append(0.0)
                continue
            draw = next(xorshift32_ref((seed + i * 73856093 + j * 19349663)
                                       & 0xFFFFFFFF))
            value = round((draw * 2.0 - 1.0) * amplitude, 4)
            row.append(value if value else 0.0)
        grid.append(row)
    return grid


REF = ref_grid(SEED, AMPLITUDE_M, CELLS)


def node_local(i: int, j: int):
    """Tile-local metres of support point (i, j): plan fraction (i/n, j/n) of
    the reference square, whose centre is the tile centre."""
    return (i * CELL_M - WIDTH_M / 2, j * CELL_M - WIDTH_M / 2)


def node_world(cx: float, cz: float, i: int, j: int, yaw: float = 0.0):
    """The same point in world metres — the composer's own local→world turn
    (``world_geometry.local_to_world``, and the client's `tileToWorld`)."""
    from app.core.world_geometry import local_to_world
    lx, lz = node_local(i, j)
    return local_to_world(lx, lz, cx, cz, yaw)


# ── the world ───────────────────────────────────────────────────────────

def set_map3d(location_id: str, **fields) -> None:
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            map3d = dict(loc.get("map3d") or {})
            map3d.update(fields)
            loc["map3d"] = map3d
    _save_world_data(data)


def place(name: str, x: float, z: float, *, yaw: float = 0.0,
          tile_rotation: int = 0, with_relief: bool = True,
          width: float = WIDTH_M, wave: float = WAVE_M,
          amplitude: float = AMPLITUDE_M, openings: bool = True) -> str:
    """An area-detail location with ONE opening on its N edge (default 8 m
    edge). ``openings=False`` draws none — a free boundary, so the nesting
    case can walk in and out without the entry gate having anything to say."""
    loc_id = add_location(name=name, description="slope-gate smoke")["id"]
    update_location_position(loc_id, x, z)
    fields = {
        "plan_width_m": width,
        # A square outline, so the location composes a scene at all.
        "outline": [[0, 0], [1, 0], [1, 1], [0, 1]],
        "area_model": True,
        "area_detail": True,
        "boundary_openings": [{"edge": "N", "at": 0.5, "width_m": 2.0,
                               "type": "passage", "room": ""}]
        if openings else [],
    }
    if tile_rotation:
        fields["tile_rotation"] = tile_rotation
    if with_relief:
        fields["relief"] = {"amplitude_m": amplitude, "seed": SEED,
                            "wave_m": wave}
    set_map3d(loc_id, **fields)
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == loc_id:
            loc["yaw_deg"] = yaw
    _save_world_data(data)
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
set_game_time(START_DT)

CLIFF = place("Smoke Cliff", 1000.0, 1000.0)
TURNED = place("Smoke Cliff Turned", 1200.0, 1000.0, yaw=90.0)
SPUN = place("Smoke Cliff Spun", 1400.0, 1000.0, tile_rotation=90)
PLAIN = place("Smoke Flat", 1600.0, 1000.0, with_relief=False)
# The nesting pair of finding F3: a WIDE-wave dome (4 m wave over an 8 m
# square = 2 cells, so exactly one free support point in the middle) with a
# 2 m hut of its own standing in the middle of it, relief-less and
# opening-less.
DOME_AMPLITUDE_M = 4.0
# NEITHER of the two draws an opening: the entry gate then has nothing to
# say in this case, and no point can be exempt from the height rule for
# standing at a door — so what [5] measures is the height and only the height.
DOME = place("Smoke Dome", 2000.0, 1000.0, wave=4.0,
             amplitude=DOME_AMPLITUDE_M, openings=False)
HUT = place("Smoke Hut", 2000.0, 1000.0, width=2.0, with_relief=False,
            openings=False)

save_character_profile(AVATAR, {"current_location": "", "language": "en"},
                       create_new=True)
set_character_pos(AVATAR, 0.0, 0.0)
set_known_locations(AVATAR, [CLIFF, TURNED, SPUN, PLAIN, DOME, HUT])
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
    check("a DROP is the same obstacle as a climb",
          relief.slope_blocks(-1.2, 0.5, STEP, SLOPE), True)
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
    for dh, dist, expected in ((1.2, 0.5, True), (0.3, 2.0, False),
                               (0.3, 0.5, False), (0.4, 0.5, False),
                               (-1.2, 0.5, True), (2.0, 2.0, True),
                               (1.6, 2.0, False), (1.6, 0.99, True),
                               (0.5, 1.0, False), (0.0, 0.0, False)):
        check(f"unchanged for the old table: {dh} m / {dist} m",
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

    print("\n[3] scene_ground_lift — the height, against the composed payload")
    cliff = get_location_by_id(CLIFF)
    scene = scene_recipe.compose_scene(cliff, plan_width_m=WIDTH_M)
    payload_grid = (scene.get("terrain") or {}).get("grid") or []
    check("the payload ships a 17 × 17 field", len(payload_grid), CELLS + 1)
    near("...with the cell the wave asks for",
         (scene.get("terrain") or {}).get("step"), CELL_M)
    check_true("the payload field IS the reference field (cell by cell)",
               payload_grid == REF)
    for i, j in ((1, 1), (2, 1), (5, 1), (8, 1), (9, 1)):
        wx, wz = node_world(1000.0, 1000.0, i, j)
        near(f"node ({i},{j}) at world ({wx}, {wz})",
             relief.scene_ground_lift(cliff, wx, wz), REF[j][i], 1e-9)
    near("the pinned border under the opening is 0",
         relief.scene_ground_lift(cliff, 1000.0, 996.0), 0.0)
    near("a location without a relief lifts nothing",
         relief.scene_ground_lift(get_location_by_id(PLAIN), 1596.5, 996.5),
         0.0)
    near("no location at all lifts nothing",
         relief.scene_ground_lift(None, 0.0, 0.0), 0.0)
    unplaced = get_location_by_id(add_location(name="Smoke Unplaced",
                                              description="")["id"])
    near("an unplaced location lifts nothing",
         relief.scene_ground_lift(unplaced, 0.0, 0.0), 0.0)
    # The FRAME: yaw 90 maps local (lx, lz) to world (cx + lz, cz − lx).
    turned = get_location_by_id(TURNED)
    lx, lz = node_local(1, 1)
    near("yaw 90: node (1,1) sits at world x = cx + lz",
         node_world(1200.0, 1000.0, 1, 1, 90.0)[0], 1200.0 + lz, 1e-9)
    near("...and at world z = cz − lx",
         node_world(1200.0, 1000.0, 1, 1, 90.0)[1], 1000.0 - lx, 1e-9)
    wx, wz = node_world(1200.0, 1000.0, 1, 1, 90.0)
    near("...and answers the very same height",
         relief.scene_ground_lift(turned, wx, wz), REF[1][1], 1e-9)
    # TILE ROTATION: the payload turns, so the gate must judge the turned
    # field — new[j][i] = old[n−i][j].
    spun = get_location_by_id(SPUN)
    spun_scene = scene_recipe.compose_scene(spun, plan_width_m=WIDTH_M)
    check_true("the rotated payload follows new[j][i] = old[16−i][j]",
               spun_scene["terrain"]["grid"][1][1] == REF[CELLS - 1][1])
    wx, wz = node_world(1400.0, 1000.0, 1, 1)
    near("...and the gate samples that rotated field",
         relief.scene_ground_lift(spun, wx, wz), REF[CELLS - 1][1], 1e-9)

    print("\n[4a] the cliff refuses: 4.97 m of step over 0.5 m")
    a_x, a_z = node_world(1000.0, 1000.0, 1, 1)
    b_x, b_z = node_world(1000.0, 1000.0, 2, 1)
    near("the two nodes are one cell apart", math.dist((a_x, a_z), (b_x, b_z)),
         CELL_M, 1e-9)
    near("the drop between them", REF[1][2] - REF[1][1], -4.9726, 1e-9)
    near("neither end is near the opening (nearest is node (2,1))",
         round(math.dist((b_x, b_z), (1000.0, 996.0)), 4), 3.0414, 1e-9)
    park(a_x, a_z, CLIFF)
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

    print("\n[4b] the gentle rise is walked: 13.46° over 2 m")
    c_x, c_z = node_world(1000.0, 1000.0, 5, 1)
    near("the two nodes are 2 m apart", math.dist((a_x, a_z), (c_x, c_z)),
         2.0, 1e-9)
    near("the rise between them", REF[1][5] - REF[1][1], 0.4788, 1e-9)
    near("its angle", math.degrees(math.atan2(0.4788, 2.0)), 13.4632, 1e-4)
    near("...and it is NOT the opening exemption (1.58 m > 1.5 m)",
         round(math.dist((c_x, c_z), (1000.0, 996.0)), 4), 1.5811, 1e-9)
    park(a_x, a_z, CLIFF)
    status, payload = report(c_x, c_z)
    check("accepted", (payload or {}).get("ok") if status == "ok" else status,
          True)
    check("the avatar stands on the new point", get_character_pos(AVATAR),
          {"x": c_x, "z": c_z})

    print("\n[4c] THE COUNTER-PROBE — with the limits wide open it goes")
    game["max_step_height_m"] = 5.0
    game["max_slope_deg"] = 89.0
    park(a_x, a_z, CLIFF)
    status, payload = report(b_x, b_z)
    check("the very same report of [4a] is accepted",
          (payload or {}).get("ok") if status == "ok" else status, True)
    check("...and the avatar really moved onto the cliff",
          get_character_pos(AVATAR), {"x": b_x, "z": b_z})
    game.pop("max_step_height_m", None)
    game.pop("max_slope_deg", None)

    print("\n[4d] an opening is a RAMP END — the same cliff is let through")
    d_x, d_z = node_world(1000.0, 1000.0, 8, 1)
    e_x, e_z = node_world(1000.0, 1000.0, 9, 1)
    near("the drop between them", REF[1][9] - REF[1][8], -1.9097, 1e-9)
    check_true("it would block on its own",
               relief.slope_blocks(REF[1][9] - REF[1][8], CELL_M, 0.4, 40.0))
    near("but node (8,1) is 0.5 m from the opening",
         math.dist((d_x, d_z), (1000.0, 996.0)), 0.5, 1e-9)
    near("...and node (9,1) 0.7071 m",
         round(math.dist((e_x, e_z), (1000.0, 996.0)), 4), 0.7071, 1e-9)
    park(d_x, d_z, CLIFF)
    status, payload = report(e_x, e_z)
    check("accepted at the door", (payload or {}).get("ok")
          if status == "ok" else status, True)

    print("\n[4f] a 2 cm lead up the same face — the SLOPE limit catches it")
    # The field is linear inside one cell, so 2 cm along the (1,1)->(2,1) edge
    # is 0.04 of the cell: h = 1.5555·0.96 + (−3.4171)·0.04 = 1.356596, i.e.
    # Δh = −0.198904 — INSIDE the 0.4 m step cap, and atan(0.198904 / 0.02) =
    # 84.2582° all the same. This is finding F1 in one report: the step limit
    # alone is blind to a wall one approaches in small enough moves, and the
    # message has to name the SLOPE, not a step that never fired.
    lead_x, lead_z = a_x + 0.02, a_z
    near("the height 2 cm along the face",
         relief.ground_lift_at(lead_x, lead_z, list_locations()),
         REF[1][1] * 0.96 + REF[1][2] * 0.04, 1e-9)
    near("its angle", math.degrees(math.atan2(0.198904, 0.02)), 84.2582, 1e-4)
    check_true("the step cap alone would let it pass", 0.198904 <= 0.4)
    park(a_x, a_z, CLIFF)
    res = report(lead_x, lead_z)
    status, reason, _pos, message = refusal_of(res)
    check("refused", res[0], "refused")
    check("the reason", reason, "too_steep")
    check("the message names the SLOPE", message,
          "That slope is too steep to climb.")

    print("\n[4e] inert without a relief (why smoke_play_pos is untouched)")
    f_x, f_z = node_world(1600.0, 1000.0, 1, 1)
    g_x, g_z = node_world(1600.0, 1000.0, 2, 1)
    near("both heights are 0",
         relief.scene_ground_lift(get_location_by_id(PLAIN), g_x, g_z), 0.0)
    park(f_x, f_z, PLAIN)
    status, payload = report(g_x, g_z)
    check("the identical geometry on flat ground is accepted",
          (payload or {}).get("ok") if status == "ok" else status, True)

    print("\n[5] NESTING — a hut without a relief follows the ground it is on")
    dome = get_location_by_id(DOME)
    dome_grid = (scene_recipe.compose_scene(dome, plan_width_m=WIDTH_M)
                 .get("terrain") or {}).get("grid") or []
    check("the wide wave leaves a 3 × 3 field", len(dome_grid), 3)
    check_true("...with the border pinned and ONE free value in the middle",
               dome_grid == [[0.0, 0.0, 0.0], [0.0, dome_grid[1][1], 0.0],
                             [0.0, 0.0, 0.0]] and dome_grid[1][1] != 0.0)
    near("that value", dome_grid[1][1],
         ref_grid(SEED, DOME_AMPLITUDE_M, 2)[1][1], 1e-9)
    _all = list_locations()
    out_x, out_z = 2000.0, 1001.4         # inside DOME, outside the hut
    in_x, in_z = 2000.0, 1000.9           # inside the hut
    near("the dome's height outside the hut (1.037 · 0.65)",
         relief.ground_lift_at(out_x, out_z, _all), 0.674050, 1e-9)
    near("...and INSIDE it, which is the fix (1.037 · 0.775)",
         relief.ground_lift_at(in_x, in_z, _all), 0.803675, 1e-9)
    near("the hut's OWN field is still nothing",
         relief.scene_ground_lift(get_location_by_id(HUT), in_x, in_z), 0.0)
    check_true("...and THAT difference would have been a 53° wall",
               relief.slope_blocks(0.674050 - 0.0, 0.5, 0.4, 40.0))
    near("the real difference", 0.674050 - 0.803675, -0.129625, 1e-9)
    near("its angle", math.degrees(math.atan2(0.129625, 0.5)), 14.5340, 1e-4)
    park(out_x, out_z, DOME)
    status, payload = report(in_x, in_z)
    check("walking into the hut is accepted", (payload or {}).get("ok")
          if status == "ok" else status, True)
    check("...and it really is the hut one stands in",
          (payload or {}).get("location_id"), HUT)
    status, payload = report(out_x, out_z)
    check("and back out again", (payload or {}).get("ok")
          if status == "ok" else status, True)

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
