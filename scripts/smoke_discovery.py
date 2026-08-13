#!/usr/bin/env python3
"""Smoke run for DISCOVERY BY SIGHT — a place becomes known by coming CLOSE
to it, not only by entering it (Seamless World, E6 task 3).

Runs against a THROWAWAY storage directory — never touches a real world.

WHAT CHANGED. Before the metre world a location became known two ways:
by ENTERING it (``save_character_current_location`` → ``add_known_location``,
untouched here and still the first way) and through a ``discover`` RULE that
rolled over the GRID NEIGHBOURS of the cell one stood in. The seamless world
has no grid, so that rule walked an always-empty list — dead code with a UI in
front of it. Sight range replaces the neighbour list with a DISTANCE:
everything whose footprint lies within ``game.discovery_range_m`` metres of
where a character stands is discovered, deterministically, by the travel
ticker and by the avatar's own position report.

THE GEOMETRY, hand-derived (``footprint_distance``). A footprint is the square
of edge ``map3d.plan_width_m`` around (``pos_x``, ``pos_z``), turned by
``yaw_deg`` (§ A1.1). The distance is measured to the SQUARE, not to its
centre — 0 anywhere inside it, edge inclusive like ``point_in_footprint``:

    ALPHA at (50, 50), edge 10, yaw 0  →  x, z ∈ [45, 55]
      (50, 50) → 0        the centre, inside
      (55, 50) → 0        ON the east edge — inclusive, as everywhere else
      (60, 50) → 5        10 m east of the centre, 5 m past the edge
      (58, 58) → hypot(58-55, 58-55) = hypot(3, 3) = 4.2426…   the CORNER
                          region: both axes overshoot, so it is a diagonal
      (40, 50) → 5        the case every discovery below is built on

    TURNED at (200, 50), edge 10, yaw 45 — the same square, turned. Its
    corners sit at (200 ± 5√2, 50) and (200, 50 ± 5√2), i.e. ±7.0711:
      (207.0711, 50) → 0  exactly the rotated east corner
      (210, 50)      → 2.9289 = 10 − 5√2. Cross-check by the transform:
                      world_to_local turns (10, 0) into (7.0711, 7.0711),
                      both 2.0711 past the half-edge 5, and
                      hypot(2.0711, 2.0711) = 2.9289 — the same number the
                      plain corner distance 10 − 7.0711 gives.
      (200, 60)      → 2.9289 by the square's own symmetry.

    A footprint with no size claims no point (``placed_footprint`` refuses it,
    ``point_in_footprint`` says False): its distance is +inf, so no range ever
    reaches it.

THE RANGE. ``game.discovery_range_m``, default 50 m, clamped to [0, 1000].
Zero is MEANT here (unlike the hearing radius, whose 0 is an emptied field):
the schema minimum is 0 and its label says "0 switches discovery off". Garbage
— missing, non-numeric, bool, NaN/inf, NEGATIVE — falls back to the default.

WHO DISCOVERS, WHEN:
  * the travel ticker (``advance_all_journeys``, every 5 real seconds) for
    EVERY character with a point, not only for travellers: someone put down
    beside a hut by a spell or a scheduler sees the hut too. One
    ``list_locations()`` per tick is shared by both passes.
  * ``POST /play/pos`` after an ACCEPTED report — a refused one moved nobody,
    so it must reveal nothing.
  * ``check_discover_rules`` (agent loop, one roll per thought turn) — the
    same geometry, but condition-gated, probabilistic, ONE random place, and
    with a player-visible message.

Discovery is one-sided: known stays known (``add_known_location`` is
idempotent, ``known_locations`` stays strict — a missing list is NOT
"knows everything").

Cases:
  [1] ``footprint_distance`` — the hand table above, incl. rotation, and
      "distance 0 ⟺ inside" against ``point_in_footprint``.
  [2] ``get_discovery_range_m`` (schema field, default, garbage table) and
      ``discover_in_range`` at the boundary: the walker at (40, 50) is 5 m
      from ALPHA → range 4 does not reach it, range 5 does (inclusive),
      range 50 finds ALPHA and NOTHING else (FAR is 1000 m away, GHOST is
      unplaced).
  [3] the ticker discovers along the way: ROADSIDE at (500, 60) edge 10 has
      its south edge at z = 55, so a walker on the road x = 500 is 55 m away
      at z = 0 (out of range, nothing) and 45 m away at z = 10 (discovered).
      Plus an IDLER standing still: no journey, but a point — discovered.
  [4] ``/play/pos``: an accepted report reveals what it walks past; a REFUSED
      one (impassable water) reveals nothing, and the very next accepted
      report from the same spot does.
  [5] the discover RULE fires on DISTANCE — and in the WILDERNESS, where the
      old code returned early because there was no current location.
      Probability 0 → nothing; out of range → nothing.
  [6] range 0 switches every path off: helper, ticker, rule, route.
  [7] idempotent: the second pass discovers nothing new and writes no
      duplicate.
  [8] the KNOWLEDGE GATE bounds the rule's pool: a location with a
      ``knowledge_item_id`` the character does not carry is in range and
      unknown — the red counter-probe shows the OLD pool
      (``locations_within(exclude=known)``) would have handed it to the roll —
      yet the rule discovers nothing and, above all, writes NO state-history
      entry carrying the secret place's NAME. With the item in the inventory
      the same roll discovers it and the name may appear.

Usage:  ./.venv/bin/python scripts/smoke_discovery.py
"""
import asyncio
import math
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="discovery-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(
    prefix="discovery-smoke-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from fastapi import HTTPException  # noqa: E402

from app.core import config, travel_engine  # noqa: E402
from app.core.config_schema import SECTIONS  # noqa: E402
from app.core.discovery import (  # noqa: E402
    discover_in_range, get_discovery_range_m, locations_within)
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.core.world_geometry import (  # noqa: E402
    footprint_distance, point_in_footprint)
from app.models import terrain  # noqa: E402
from app.models.account import set_active_character  # noqa: E402
from app.models.inventory import (  # noqa: E402
    add_item, add_to_inventory, has_item)
from app.models.character import (  # noqa: E402
    get_character_profile, get_known_locations, save_character_profile,
    set_character_pos, set_known_locations)
from app.models.rules import add_rule, check_discover_rules  # noqa: E402
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location, update_location_position)
from app.routes import play as play_route  # noqa: E402
from app.routes.play import play_pos  # noqa: E402

FAILURES = []
CHECKED = 0

START_DT = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
START_ISO = START_DT.isoformat()
USER = {"username": "demo", "role": "user"}
AVATAR = "demo_avatar"
WALKER = "demo_walker"
IDLER = "demo_idler"
SEEKER = "demo_seeker"
SPY = "demo_spy"
#: The shared baseline ships a discover rule ("Awareness", probability 0.3).
#: It is overridden by id below so no case here rolls a die it did not throw.
SHARED_AWARENESS_ID = "rule_04d219e2"


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_close(label, actual, expected, tol=1e-4):
    global CHECKED
    CHECKED += 1
    ok = actual is not None and abs(actual - expected) <= tol
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


class _FakeRequest:
    """Minimal stand-in: the route only ever awaits ``request.json()``."""

    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


def set_map3d(location_id: str, **fields) -> None:
    """Merge fields into a location's map3d blob (the scale anchor)."""
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            map3d = dict(loc.get("map3d") or {})
            map3d.update(fields)
            loc["map3d"] = map3d
    _save_world_data(data)


def set_knowledge_gate(location_id: str, item_id: str) -> None:
    """Put a knowledge item in front of a location (the world editor's field)."""
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            loc["knowledge_item_id"] = item_id
    _save_world_data(data)


def discovery_names_in_history(character_name: str) -> list:
    """Every ``discovery`` value the state history holds for a character —
    the field the admin diary and the recent-activity views read."""
    import json as _json
    from app.core.db import get_connection
    rows = get_connection().execute(
        "SELECT state_json FROM state_history WHERE character_name=?",
        (character_name,)).fetchall()
    out = []
    for (state_json,) in rows:
        try:
            entry = _json.loads(state_json or "{}")
        except Exception:
            continue
        if entry.get("type") == "discovery":
            out.append(entry.get("value", ""))
    return out


def set_yaw(location_id: str, yaw: float) -> None:
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            loc["yaw_deg"] = yaw
    _save_world_data(data)


def place(name: str, x=None, z=None, width: float = 10.0,
          yaw: float = 0.0) -> str:
    """A location with a scale anchor; without x/z it stays UNPLACED."""
    loc_id = add_location(name=name, description="discovery smoke")["id"]
    if x is not None:
        update_location_position(loc_id, x, z)
    set_map3d(loc_id, plan_width_m=width)
    if yaw:
        set_yaw(loc_id, yaw)
    return loc_id


def new_char(name: str, x=None, z=None, known=()) -> None:
    save_character_profile(name, {"current_location": "", "language": "en"},
                           create_new=True)
    if x is not None:
        set_character_pos(name, x, z)
    set_known_locations(name, list(known))


def give_journey(name: str, target: str, waypoints) -> None:
    """Hand-written journey on the profile — the ticker's INPUT, so nothing
    below depends on what the router happens to route."""
    prof = get_character_profile(name)
    prof["movement_target"] = target
    prof["journey"] = {"target": target,
                       "waypoints": [list(w) for w in waypoints],
                       "started_at_game": START_ISO, "speed_m_s": 1.0,
                       "entry_edge": ""}
    save_character_profile(name, prof)


def tick_at(seconds: float) -> None:
    """Pin the game clock to START + seconds and run ONE ticker pass."""
    set_game_time(START_DT + timedelta(seconds=seconds))
    travel_engine.advance_all_journeys()


def set_range(value) -> None:
    """Override the world setting the way the admin UI would."""
    config._CONFIG.setdefault("game", {})["discovery_range_m"] = value


def clear_range() -> None:
    config._CONFIG.setdefault("game", {}).pop("discovery_range_m", None)


def report(x: float, z: float):
    """POST /play/pos → ("ok", payload) or ("refused", (status, detail))."""
    try:
        return "ok", asyncio.run(play_pos(_FakeRequest({"x": x, "z": z}),
                                          user=USER))
    except HTTPException as exc:
        return "refused", (exc.status_code, exc.detail)


def park(x: float, z: float) -> None:
    """World setup, not a move: put the avatar at a point and forget the
    report clock, so the next report is judged like a session's first one.
    Deliberately NOT a discovery path — that is what the route is for."""
    set_character_pos(AVATAR, x, z)
    play_route._pos_report_at.pop(AVATAR, None)


# ── the world ───────────────────────────────────────────────────────────
set_game_factor(0.0)                  # the game clock stands still — pinned
set_game_time(START_DT)
travel_engine.game_speed_factor = lambda: 1.0   # …the goal window runs at 1×

ALPHA = place("Smoke Alpha", 50.0, 50.0)
TURNED = place("Smoke Turned", 200.0, 50.0, yaw=45.0)
ROADSIDE = place("Smoke Roadside", 500.0, 60.0)
POND_HOUSE = place("Smoke Pond House", 300.0, 300.0)
FAR = place("Smoke Far", 1000.0, 1000.0)
GHOST = place("Smoke Ghost")           # placed nowhere — no footprint at all
# Far from every other point in this file, so only [8] ever comes near it: a
# location nobody may even SEE without its knowledge item.
SECRET = place("Smoke Secret Grove", 2000.0, 2000.0)
SECRET_ITEM = add_item(name="Smoke Secret Map", description="discovery smoke",
                       item_id="item_smoke_secret_map")["id"]
set_knowledge_gate(SECRET, SECRET_ITEM)

# Impassable water NORTH of the pond house, for the refused report in [4].
terrain.save_area({"kind": "deep_water",
                   "polygon": [[290, 282], [310, 282], [310, 290], [290, 290]],
                   "z_order": 0})

new_char(WALKER)
new_char(IDLER)
new_char(SEEKER)
new_char(AVATAR)
set_active_character(AVATAR)

# The throttle is about wall time and has its own smoke (smoke_play_pos [13]);
# here it would only make the run sleep.
play_route._POS_REPORT_INTERVAL_S = 0.0

# Determinism: neutralise the shared "Awareness" rule (probability 0.3).
add_rule({"id": SHARED_AWARENESS_ID, "name": "Awareness (off for the smoke)",
          "type": "discover", "probability": 0.0})


def main() -> int:
    print("\n[1] footprint_distance — the hand table")
    check_close("centre (50,50)", footprint_distance(50, 50, 50, 50, 10, 0), 0.0)
    check_close("on the east edge (55,50)",
                footprint_distance(55, 50, 50, 50, 10, 0), 0.0)
    check_close("5 m past the edge (60,50)",
                footprint_distance(60, 50, 50, 50, 10, 0), 5.0)
    check_close("the corner region (58,58)",
                footprint_distance(58, 58, 50, 50, 10, 0), math.hypot(3, 3))
    check_close("west side (40,50)",
                footprint_distance(40, 50, 50, 50, 10, 0), 5.0)
    check_close("north side (50,40)",
                footprint_distance(50, 40, 50, 50, 10, 0), 5.0)
    check_close("turned 45°: on the rotated east corner",
                footprint_distance(200 + 5 * math.sqrt(2), 50,
                                   200, 50, 10, 45), 0.0)
    check_close("turned 45°: (210,50) = 10 − 5√2",
                footprint_distance(210, 50, 200, 50, 10, 45),
                10 - 5 * math.sqrt(2))
    check_close("turned 45°: (200,60) by symmetry",
                footprint_distance(200, 60, 200, 50, 10, 45),
                10 - 5 * math.sqrt(2))
    check_close("yaw 90 is the same square (60,50)",
                footprint_distance(60, 50, 50, 50, 10, 90), 5.0)
    check("no size claims no point", footprint_distance(50, 50, 50, 50, 0, 0),
          math.inf)
    # 0 ⟺ inside, on the very samples point_in_footprint judges.
    for px, pz in ((50, 50), (55, 50), (45, 45), (55.001, 50), (60, 50),
                   (58, 58)):
        inside = point_in_footprint(px, pz, 50, 50, 10, 0)
        dist = footprint_distance(px, pz, 50, 50, 10, 0)
        check(f"({px},{pz}) inside ⟺ distance 0", (inside, dist == 0.0),
              (inside, inside))

    print("\n[2] the range setting and the boundary")
    check("the schema carries the field",
          "discovery_range_m" in SECTIONS["game"]["fields"], True)
    clear_range()
    check("unset → default", get_discovery_range_m(), 50.0)
    for raw, expected in ((0, 0.0), (0.0, 0.0), (12.5, 12.5), (1e9, 1000.0),
                          (-5, 50.0), ("nope", 50.0), (True, 50.0),
                          (None, 50.0), (float("nan"), 50.0),
                          (float("inf"), 50.0)):
        set_range(raw)
        check(f"{raw!r} → {expected}", get_discovery_range_m(), expected)
    clear_range()

    set_known_locations(WALKER, [])
    set_character_pos(WALKER, 40.0, 50.0)
    check("5 m away, range 4 does not reach",
          locations_within(40.0, 50.0, 4.0, None), [])
    check("range 5 does (inclusive)",
          locations_within(40.0, 50.0, 5.0, None), [ALPHA])
    set_range(4)
    check("discover_in_range respects it", discover_in_range(WALKER, 40.0, 50.0),
          [])
    check("nothing was written", get_known_locations(WALKER), [])
    set_range(5)
    check("at the boundary it discovers", discover_in_range(WALKER, 40.0, 50.0),
          [ALPHA])
    check("and it is known now", get_known_locations(WALKER), [ALPHA])
    set_known_locations(WALKER, [])
    clear_range()
    check("default range: ALPHA and nothing else",
          discover_in_range(WALKER, 40.0, 50.0), [ALPHA])
    check_true("the unplaced GHOST is never discovered",
               GHOST not in get_known_locations(WALKER),
               str(get_known_locations(WALKER)))
    check_true("FAR is 1000 m away and stays unknown",
               FAR not in get_known_locations(WALKER))
    check("a character without a point discovers nothing",
          discover_in_range("nobody_here", 0.0, 0.0), [])

    print("\n[3] the ticker discovers along the way")
    set_known_locations(WALKER, [])
    set_character_pos(WALKER, 500.0, 0.0)
    give_journey(WALKER, ROADSIDE, [[500, 0, 0], [500, 40, 40]])
    tick_at(0)
    check("at z=0 the roadside is 55 m away — out of range",
          get_known_locations(WALKER), [])
    tick_at(10)
    check("at z=10 it is 45 m away — discovered",
          get_known_locations(WALKER), [ROADSIDE])
    travel_engine.cancel_journey(WALKER)

    set_known_locations(IDLER, [])
    set_character_pos(IDLER, 40.0, 50.0)
    tick_at(11)
    check("a character standing still is covered too",
          get_known_locations(IDLER), [ALPHA])

    # …and the whole cast costs ONE position read, not one per character.
    # The sight pass runs inside the event loop every 5 seconds, so its cost
    # scales with the cast; hand-derived: 1 bulk SELECT
    # (list_character_positions) and 0 single reads (get_character_pos),
    # however many characters the world has.
    import app.models.character as char_mod
    from app.models.world import list_locations as _list_locations
    real_bulk = char_mod.list_character_positions
    real_single = char_mod.get_character_pos
    bulk_calls, single_calls = [], []

    def counting_bulk(*a, **kw):
        bulk_calls.append(1)
        return real_bulk(*a, **kw)

    def counting_single(*a, **kw):
        single_calls.append(1)
        return real_single(*a, **kw)

    _cast = char_mod.list_available_characters()
    char_mod.list_character_positions = counting_bulk
    char_mod.get_character_pos = counting_single
    try:
        travel_engine._discover_by_sight(_cast, _list_locations())
    finally:
        char_mod.list_character_positions = real_bulk
        char_mod.get_character_pos = real_single
    check_true("the cast is big enough for the count to mean something",
               len(_cast) >= 3, f"{len(_cast)} characters")
    check("one bulk position read for the whole sight pass", len(bulk_calls), 1)
    check("…and not a single per-character read", len(single_calls), 0)
    # The bulk read answers for characters INSIDE a location too — the wilderness
    # sibling would silently skip the idler the moment it steps into a house.
    check_true("the bulk read covers everyone with a point",
               set(p["name"] for p in real_bulk()) >= {WALKER, IDLER},
               str(sorted(p["name"] for p in real_bulk())))

    print("\n[4] /play/pos — accepted reveals, refused does not")
    set_known_locations(AVATAR, [])
    park(30.0, 50.0)
    status, _payload = report(40.0, 50.0)
    check("the report was accepted", status, "ok")
    check("what it walked past is known", get_known_locations(AVATAR), [ALPHA])

    park(300.0, 280.0)
    status, detail = report(300.0, 285.0)
    check("the water report was refused", status, "refused")
    check("…as impassable", detail[1].get("reason"), "impassable")
    check_true("a refused report reveals nothing",
               POND_HOUSE not in get_known_locations(AVATAR),
               str(get_known_locations(AVATAR)))
    park(300.0, 280.0)
    status, _payload = report(300.0, 281.0)
    check("a step aside is accepted", status, "ok")
    check_true("…and reveals the same house",
               POND_HOUSE in get_known_locations(AVATAR),
               str(get_known_locations(AVATAR)))

    # …and it does so WITHOUT reading the location table a second time. A
    # walking client sends up to four reports a second, so every avoidable
    # full read counts. Hand-derived: an accepted report reads it exactly
    # TWICE — once in the route (the transition gate's snapshot, handed on to
    # the sight discovery) and once inside ``set_character_pos``, which
    # derives the location of the point it writes. Three would mean the
    # discovery fetched its own copy.
    import app.models.world as world_module
    real_list_locations = world_module.list_locations
    calls = []

    def counting_list_locations(*a, **kw):
        calls.append(1)
        return real_list_locations(*a, **kw)

    park(300.0, 280.0)          # setup, OUTSIDE the counter: it writes a
    #                             position of its own and would be counted
    world_module.list_locations = counting_list_locations
    try:
        status, _payload = report(300.0, 279.0)   # clear of the water's edge
    finally:
        world_module.list_locations = real_list_locations
    check("the accepted report was accepted", status, "ok")
    check("…and read the location table exactly twice", len(calls), 2)

    print("\n[5] the discover rule fires on distance, in the wilderness")
    rule = add_rule({"name": "Smoke Sight", "type": "discover",
                     "probability": 1.0,
                     "message": "You spot a place you did not know."})
    set_known_locations(SEEKER, [])
    set_character_pos(SEEKER, 40.0, 50.0)
    check("the seeker has no location at all",
          (get_character_profile(SEEKER) or {}).get("current_location", ""), "")
    hit = check_discover_rules(SEEKER)
    check("the rule discovered ALPHA", (hit or {}).get("location_id"), ALPHA)
    check("it names the rule", (hit or {}).get("rule_name"), "Smoke Sight")
    check("the message is the rule's", (hit or {}).get("message"),
          "You spot a place you did not know.")
    check("known followed", get_known_locations(SEEKER), [ALPHA])
    check("a second roll finds nothing left in range",
          check_discover_rules(SEEKER), None)
    set_character_pos(SEEKER, 5000.0, 5000.0)
    check("out in the empty plain nothing is in range",
          check_discover_rules(SEEKER), None)
    set_known_locations(SEEKER, [])
    set_character_pos(SEEKER, 40.0, 50.0)
    add_rule({"id": rule["id"], "name": "Smoke Sight", "type": "discover",
              "probability": 0.0})
    check("probability 0 never fires", check_discover_rules(SEEKER), None)
    check("…and writes nothing", get_known_locations(SEEKER), [])
    add_rule({"id": rule["id"], "name": "Smoke Sight", "type": "discover",
              "probability": 1.0,
              "message": "You spot a place you did not know."})

    print("\n[6] range 0 switches discovery off")
    set_range(0)
    set_known_locations(WALKER, [])
    set_known_locations(IDLER, [])
    set_known_locations(SEEKER, [])
    set_known_locations(AVATAR, [])
    check("the helper stays silent", discover_in_range(WALKER, 40.0, 50.0), [])
    tick_at(12)
    check("the ticker stays silent (idler at ALPHA's door)",
          get_known_locations(IDLER), [])
    check("the rule stays silent", check_discover_rules(SEEKER), None)
    park(30.0, 50.0)
    status, _payload = report(40.0, 50.0)
    check("the report is still accepted", status, "ok")
    check("…but reveals nothing", get_known_locations(AVATAR), [])
    clear_range()

    print("\n[7] idempotent — the second pass adds nothing")
    set_known_locations(WALKER, [])
    # The walker's REAL point moves with it: [3] left it on the road. Put it
    # beside ALPHA, so the ticker below judges the same point the helper does.
    set_character_pos(WALKER, 40.0, 50.0)
    check("first pass", discover_in_range(WALKER, 40.0, 50.0), [ALPHA])
    check("second pass", discover_in_range(WALKER, 40.0, 50.0), [])
    check("no duplicate", get_known_locations(WALKER), [ALPHA])
    tick_at(13)
    tick_at(14)
    check("the ticker does not duplicate either",
          get_known_locations(IDLER), [ALPHA])
    check("…nor for the walker", get_known_locations(WALKER), [ALPHA])
    set_range(1)
    check("a shrinking range discovers nothing new",
          discover_in_range(WALKER, 40.0, 50.0), [])
    check("…and un-knows nothing", get_known_locations(WALKER), [ALPHA])
    clear_range()

    print("\n[8] the knowledge gate bounds the RULE's pool")
    new_char(SPY, 1990.0, 2000.0)     # 5 m from the grove's western edge
    # RED COUNTER-PROBE: the pool the rule drew from before this fix — known
    # ids excluded, nothing else — hands the gated grove straight to the roll.
    check("the old known-only pool would have rolled the grove",
          locations_within(1990.0, 2000.0, get_discovery_range_m(), None,
                           exclude=get_known_locations(SPY)), [SECRET])
    check("the spy does not carry the map", has_item(SPY, SECRET_ITEM), False)
    check("…so the rule discovers nothing", check_discover_rules(SPY), None)
    check("…nothing became known", get_known_locations(SPY), [])
    check("…and the secret NAME never reached the state history",
          discovery_names_in_history(SPY), [])
    check("adding the map", add_to_inventory(SPY, SECRET_ITEM), True)
    hit = check_discover_rules(SPY)
    check("with the map in hand the same roll discovers the grove",
          (hit or {}).get("location_id"), SECRET)
    check("…known followed", get_known_locations(SPY), [SECRET])
    check("…and only now the name is in the history",
          discovery_names_in_history(SPY), ["Smoke Secret Grove"])

    print()
    if FAILURES:
        print(f"FAILED {len(FAILURES)}/{CHECKED}")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print(f"OK — {CHECKED} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
