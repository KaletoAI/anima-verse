#!/usr/bin/env python3
"""Smoke run for the Journey-v2 TICKER + party following
(Seamless World, E3 Task 3).

Runs against a THROWAWAY storage directory — never touches a real world.

Rules every expectation below is derived from BY HAND:

  * ``journey_state`` is a pure function of the GAME clock. The clock is
    pinned here: ``set_game_factor(0.0)`` stops it, ``set_game_time(GameTime)``
    jumps it exactly — so "tick at t = 30 s" is an exact statement, not a
    race against wall time.
  * The ticker's GOAL WINDOW (``_at_goal``) reads the clock FACTOR, and a
    stopped clock reports 0.0 — so the factor is injected here instead
    (``set_factor``, which replaces ``travel_engine.game_speed_factor``).
    That keeps the two apart on purpose: the CLOCK stays frozen, so every
    position below is exact, while the FACTOR is whatever the case under
    test wants. Everything outside [7e] runs at factor 1.0, which is where
    the "one tick = 5 s × speed" of [7b]/[7d] comes from.
  * The ticker writes the interpolated point every tick via
    ``set_character_pos(..., preserve_movement_target=True)``. The point
    DERIVES the location (``location_at_point``, footprint test inclusive):
    inside a footprint its id, outside the empty string — walking over open
    terrain with an empty ``current_location`` is the NORMAL state of a
    journey, and the preserving write is what keeps ``movement_target`` and
    the journey dict alive while it happens.
  * A footprint is the square of edge ``map3d.plan_width_m`` around
    (``pos_x``, ``pos_z``), turned by ``yaw_deg``; an opening's world point
    sits on that edge at ``(at − 0.5)·w`` (see smoke_journey_v2 [4]).
  * Arrival = the elapsed time reached the last waypoint's ``t_cum``.

The route used everywhere below (HOME at (0,0) w 10, opening S at 0.5 →
(0,5); MARKET at (100,0) w 10, opening W at 0.5 → (95,0), room link "Hall"):

    W0 [ 0,  0,   0]   HOME centre, the character's real position
    W1 [ 0,  5,   5]   HOME's own opening —  5 m in  5 s
    W2 [ 0, 30,  30]   out into the open   — 25 m in 25 s
    W3 [60, 30,  90]   across the meadow   — 60 m in 60 s
    W4 [60,  0, 120]   turning south       — 30 m in 30 s
    W5 [95,  0, 155]   MARKET's W opening  — 35 m in 35 s

  Every segment is 1 m per game second (the hand-picked t_cum), so a
  position is read off the polyline directly. Only W5 touches MARKET's
  footprint (x = 95 is its west edge, and the footprint test is inclusive)
  — every earlier point of the route lies outside every footprint except
  HOME's own (|x| ≤ 5 and |z| ≤ 5, i.e. W0 and W1).

Hand-derived expectations:

  [1] ``start_journey`` remembers WHICH opening the route aimed at:
      HOME → MARKET stores ``entry_edge`` "W" (MARKET's only opening).
      A target with NO opening at all (the footprint-edge fallback) stores
      '' — the arrival then falls back to ``get_arrival_room_id``.

  [2] Three ticks in flight, positions read off the route above:
        t =   2 → (0, 2)   inside HOME (|z| = 2 ≤ 5) → current_location HOME
        t =  30 → (0, 30)  outside every footprint   → current_location ''
                           and current_room '' — WILDERNESS mid-journey is
                           the normal case, and movement_target + journey
                           MUST survive it (the trap this task exists for)
        t = 120 → (60, 0)  still wilderness
      Arrival at t = 155: current_location MARKET, current_room = the room
      the W opening links to (NOT the ground room the arrival rule would
      pick), movement_target '' and journey gone; the position is dragged
      to MARKET's centre (100, 0) by the location write's own sync.

  [3] Party: leader + 2 followers, offsets 1.2 m perpendicular to the
      CURRENT segment, index-based (first follower left, second right):
        t =   2 → leader (0, 2), segment W0→W1 points (0, 1),
                  perpendicular (−1, 0) → f1 (−1.2, 2.0), f2 (1.2, 2.0)
        t =  30 → leader (0, 30), segment W2→W3 points (1, 0),
                  perpendicular (0, 1) → f1 (0, 31.2), f2 (0, 28.8)
      On the leader's arrival the EXISTING _drag_party_followers_to_location
      hook pulls both followers to MARKET, and the settle then spreads them
      with the SAME formation instead of stacking them on the centre (E4):
      the last segment W4→W5 points (1, 0), perpendicular (0, 1), so the
      leader stands on MARKET's centre (100, 0) and the followers at
      (100, 1.2) and (100, −1.2) — both still inside MARKET
      (x ∈ [95, 105], z ∈ [−5, 5]), so neither yields.
      The formation never puts a follower where the leader is not: SHED sits
      at (0, 32) with edge 2 m, i.e. x ∈ [−1, 1] and z ∈ [31, 33], so it
      swallows f1's offset point (0, 31.2) while the leader at (0, 30) and
      f2 at (0, 28.8) stay outside — f1 therefore stands on the LEADER's own
      point (0, 30) instead of entering a shed the party walks past.
      A follower that joined WHILE travelling keeps a journey of its own; the
      formation cancels it (whichever of the two writes lands last, the end
      state is the same — pinned by asserting both).

  [4] Access-blocked arrival: a block rule (action "enter", scope location,
      condition "always") on MARKET → the journey ends on the last point of
      its route that does NOT lie in MARKET. The goal (95, 0) sits on
      MARKET's west edge and the footprint test is inclusive, so parking
      there would BE standing in the refused location; the walk steps back
      along the polyline in 0.5 m increments until a point is outside.
      MARKET spans x ∈ [95, 105], z ∈ [−5, 5]:
        · the main route approaches head-on along z = 0 (W4→W5, 35 m east)
          → the FIRST step back, (94.5, 0), is already outside
        · wall-collinear approach, start (95, 40) straight down x = 95: every
          back-step keeps x = 95, i.e. ON the west wall and INSIDE, until z
          leaves the wall — 0.5·11 = 5.5 → (95, 5.5) is the first outside
          point (5.0 would still be the inclusive corner)
        · through the target's own footprint, start (97, 10) → (95, 0):
          length √(2² + 10²) = √104 = 10.198039…, and the step distance d
          puts the point at x = 95 + 2·d/√104, z = 10·d/√104. z leaves the
          footprint at d > 5.0990…, so d = 5.5 is the first outside step:
          frac = 5.5/√104 = 0.5393182…, x = 96.078636…, z = 5.393182… →
          rounded (96.08, 5.39), and 5.39 > 5 survives the snap.
        · a route running ENTIRELY inside the target (centre (100, 0) → its
          own opening (95, 0)) has no outside point at all: the fallback
          keeps the door point (95, 0) and clears location + room outright.
      In every case: current_location is never MARKET (also when the whole
      journey settles in the SAME tick it started, straight out of HOME),
      movement_target + journey gone, an ``access_denied`` entry with action
      "enter" in state_history, a ``travel_blocked`` state event — and an
      ordinary ``set_character_pos`` at the character's OWN resulting
      position does not enter the target either.

  [5] The latent equal-location arrival: a character that ALREADY stands in
      the journey's target settles without a location change — the location
      setter then clears nothing, so the ticker must clear the journey
      itself. Pinned by a SECOND ticker call that must be a complete no-op
      (no event at all), instead of re-settling every 5 seconds forever.

  [6] A NON-preserving position write kills a running journey — otherwise
      the next tick teleports the character back onto its baked polyline:
        a) editor re-place of the location the traveller stands in
           (``_shift_location_occupants``: pure position shift, NO location
           change, so the movement_target lifecycle never fires — the
           explicit cancel lives there)
        b) ``set_character_pos`` in the wilderness (no location change
           either — same hole, same fix, on the setter itself)
        c) ``set_character_pos`` INTO a location (a real location change:
           here the cancel falls out of the existing lifecycle in
           ``save_character_current_location``)

  [7] The THROUGH-TARGET route (final review, finding C1). The nav grid
      exempts the target's OWN footprint, so a route to an opening that faces
      away legally crosses the building — and an in-flight point inside the
      target must never be written as an ordinary derived position (that
      would enter it with no access gate, no accessible_when, the ground room
      instead of the opening's, and would silently clear the journey mid-
      route, because the location setter clears target + journey exactly when
      the new location IS the target). Such a tick settles as an EARLY
      ARRIVAL through the very same gate.

      EASTGATE at (300, 0), width 10 → footprint x ∈ [295, 305],
      z ∈ [−5, 5]; its ONLY opening sits on the E edge at 0.5 → (305, 0),
      linked to the room "Yard". The route (1 m per game second again) comes
      from the west, cuts straight through the footprint and walks around to
      the far door:

          W0 [290,  0,  0]   5 m west of the west wall — outside
          W1 [300,  0, 10]   the centre — INSIDE the target
          W2 [300, 30, 40]   out the north side
          W3 [305, 30, 45]   east, level with the door's x
          W4 [305,  0, 75]   down the east wall to the E opening

        · t =  2 → (292, 0): outside every footprint → an ordinary in-flight
          write, location '' and the journey alive.
        · t =  8 → (298, 0): INSIDE EASTGATE → early arrival.

      (a) with a block rule (enter/location/always) on EASTGATE: refused, and
          the standoff walks back over the WALKED PREFIX
          [[290, 0], [298, 0]] — never over the whole polyline. Steps of
          0.5 m from (298, 0) leave the footprint when 298 − d < 295, i.e.
          d > 3.0 (d = 3.0 lands on x = 295, the inclusive west wall) → the
          first outside step is d = 3.5 → (294.5, 0.0), and it survives the
          snap. The full polyline would instead have stepped back from the
          door (305, 0) up the east wall (inclusive until z > 5) to
          (305, 5.5) — 30 m AHEAD of the traveller and on the far side of the
          building it was just refused. So (294.5, 0.0) is the assertion that
          pins "never teleport forward".
      (b) without the rule: the same tick settles as a proper arrival —
          location EASTGATE, journey and movement_target gone, the point
          dragged to the centre (300, 0). The room is the ARRIVAL room (the
          ground), NOT the Yard the E opening links to: the route is 75 m
          long and 8 m of it are walked, so 67 m of REMAINING ROUTE stand
          against one tick's 5 m (5 s × 1 m/game-s) — this crossing is not
          the final approach to that door and has no claim on the room
          behind it (see [7d] for the case that is). A second tick is a
          complete no-op — the settle happens once.
      (d) THE GOAL TOLERANCE IS THE REMAINING ROUTE, NOT A EUCLIDEAN RADIUS
          (E4, E3-residual). The wall-collinear approach walks EASTGATE's
          east wall straight down to its own door: route [[305, 40], [305, 0]]
          at 1 m per game second, 40 m in total. x = 305 IS the east wall and
          the footprint test is inclusive, so every point with |z| ≤ 5 already
          derives EASTGATE — the crossing is caught at t = 36, i.e. at
          (305, 4), four metres in FRONT of the door it is walking to.
          The old 0.5 m Euclid test called that "not at the goal" and handed
          out the arrival room (the ground) although the traveller is on the
          final approach to an authored opening. The rule is now the REMAINING
          ROUTE against one tick's travel:
            remaining   = total_m − progress_m = 40 − 36 = 4.0 m
            tick travel = 5.0 s × speed_m_s 1.0 = 5.0 m
            4.0 ≤ 5.0   → at the goal → the E opening's room "Yard"
          [7b] is the counter-case on the same building: the crossing there
          happens 67 m before the end of the route, so the ground room stands.
      (e) THE WINDOW RIDES THE GAME-CLOCK FACTOR (final E4 review, I1). One
          tick is 5 REAL seconds; how many METRES that is depends on how fast
          the game clock runs:
            window_m = 5.0 s × factor (game s per real s) × speed (m/game s)
          Same wall route, same speed 1.0, total 40 m:
            · factor 0.5 → window 2.5 m. At t = 36 the remaining 4.0 m are
              MORE than the window, so the very crossing that gave "Yard" in
              [7d] now hands out the arrival room; at t = 38 the remaining
              2.0 m fit and the door's room wins again.
            · factor 0.0 (a frozen world) → the floor 0.1 → window 0.5 m: at
              t = 36 the ground room, at t = 39.7 (remaining 0.3 m) "Yard".
              Without the floor the window would be 0 m and NO crossing could
              ever be the goal.
      (c) ``accessible_when`` is a wall at the arrival gate too (it used to be
          enforced only on the avatar's /play/travel route, so every NPC and
          every rule-flip-while-on-the-road walked past it). VAULT at
          (500, 0), width 10 → x ∈ [495, 505]; opening W at 0.5 → (495, 0),
          room "Vault Hall"; ``accessible_when: ["has_item:silver_key"]``.
          The route [[460, 0, 0], [495, 0, 35]] arrives head-on at t = 35:
            · without the key → refused, standoff one step back from the
              door → (494.5, 0.0), outside, denial + travel_blocked;
            · with the key → enters, and because the arrival point IS the
              journey's goal the opening's room link wins → "Vault Hall".

Usage:  ./.venv/bin/python scripts/smoke_travel_ticker.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="travel-ticker-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="travel-ticker-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import state_events, travel_engine  # noqa: E402
from app.core.party_engine import add_to_party  # noqa: E402
from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_current_location, get_character_current_room,
    get_character_pos, get_character_profile, get_movement_target,
    save_character_current_location, save_character_profile,
    set_character_pos, set_known_locations)
from app.models.inventory import add_item, add_to_inventory  # noqa: E402
from app.models.rules import add_rule, delete_rule  # noqa: E402
from app.models.world import (  # noqa: E402
    GROUND_ROOM_ID, _load_world_data, _save_world_data, add_location, add_room,
    update_location_position)

FAILURES = []
CHECKED = 0

# Game time is the world calendar: a canonical stamp, no date, no timezone.
START = "Y0001-D001T12:00:00"
START_GT = GameTime.parse(START)

# The route of the module docstring — [x, z, t_cum], 1 m per game second.
ROUTE = [[0.0, 0.0, 0.0], [0.0, 5.0, 5.0], [0.0, 30.0, 30.0],
         [60.0, 30.0, 90.0], [60.0, 0.0, 120.0], [95.0, 0.0, 155.0]]

EVENTS = []


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


def _capture(event_type, character, **fields):
    EVENTS.append({"type": event_type, "character": character, **fields})


state_events.publish = _capture       # every publisher imports it lazily


def set_map3d(location_id: str, **fields) -> None:
    """Merge fields into a location's map3d blob (scale anchor, openings)."""
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            map3d = dict(loc.get("map3d") or {})
            map3d.update(fields)
            loc["map3d"] = map3d
    _save_world_data(data)


def give_journey(name: str, target: str, entry_edge: str = "W",
                 waypoints=None, started: str = START) -> None:
    """Hand-written journey on the profile — the ticker's INPUT, so the
    expectations below never depend on what the router happens to route."""
    prof = get_character_profile(name)
    prof["movement_target"] = target
    prof["journey"] = {"target": target,
                       "waypoints": [list(w) for w in (waypoints or ROUTE)],
                       "started_at_game": started, "speed_m_s": 1.0,
                       "entry_edge": entry_edge}
    save_character_profile(name, prof)


def tick_at(seconds: float) -> None:
    """Pin the game clock to START + seconds and run ONE ticker pass."""
    set_game_time(START_GT + GameDuration.of(seconds=seconds))
    travel_engine.advance_all_journeys()


def set_factor(factor: float) -> None:
    """Pin the CLOCK FACTOR the goal window reads, without starting the clock.

    ``set_game_factor`` would do both — and a running clock makes every
    position in this file a race. The ticker asks exactly one question of the
    factor (``_at_goal``), so injecting the answer is enough.
    """
    travel_engine.game_speed_factor = lambda: factor


def pos_of(name):
    p = get_character_pos(name)
    return None if p is None else (round(p["x"], 2), round(p["z"], 2))


def denials(name):
    rows = db.get_connection().execute(
        "SELECT state_json FROM state_history WHERE character_name=? "
        "ORDER BY ts DESC LIMIT 20", (name,)).fetchall()
    import json
    out = []
    for (raw,) in rows:
        try:
            st = json.loads(raw or "{}")
        except Exception:
            continue
        if st.get("type") == "access_denied":
            out.append(st.get("metadata") or {})
    return out


# ── the world ───────────────────────────────────────────────────────────
HOME = add_location(name="Ticker Home", description="travel ticker smoke")["id"]
update_location_position(HOME, 0.0, 0.0)
set_map3d(HOME, plan_width_m=10.0,
          boundary_openings=[{"edge": "S", "at": 0.5, "width_m": 4.0,
                              "type": "passage"}])
MARKET = add_location(name="Ticker Market", description="travel ticker smoke")["id"]
update_location_position(MARKET, 100.0, 0.0)
HALL = add_room(MARKET, "Hall", "the room the west gate opens into")["id"]
set_map3d(MARKET, plan_width_m=10.0,
          boundary_openings=[{"edge": "W", "at": 0.5, "width_m": 4.0,
                              "type": "passage", "room": HALL}])
BARN = add_location(name="Ticker Barn", description="no opening at all")["id"]
update_location_position(BARN, 0.0, 200.0)
set_map3d(BARN, plan_width_m=10.0)
# 1.2 m beside the route at t = 30 — close enough to swallow a follower's
# offset point, far enough to leave the leader's own point alone.
SHED = add_location(name="Ticker Shed", description="beside the route")["id"]
update_location_position(SHED, 0.0, 32.0)
set_map3d(SHED, plan_width_m=2.0)

set_game_factor(0.0)                  # the game clock stands still — pinned
set_game_time(START_GT)
set_factor(1.0)                       # …but the goal window runs at 1× (see
#                                       the module docstring); [7e] varies it.


def new_npc(name, location="", x=None, z=None, known=(HOME, MARKET, BARN)):
    save_character_profile(name, {"current_location": ""}, create_new=True)
    if location:
        save_character_current_location(name, location)
    if x is not None:
        set_character_pos(name, x, z)
    set_known_locations(name, list(known))


# ── [1] start_journey remembers the opening it aimed at ─────────────────
print("[1] start_journey stores entry_edge")
new_npc("edge_npc", HOME, 0.0, 0.0)
journey, reason = travel_engine.start_journey("edge_npc", MARKET)
check("reason", reason, "")
check("entry_edge is MARKET's only opening",
      (journey or {}).get("entry_edge"), "W")
travel_engine.cancel_journey("edge_npc")
journey_b, reason_b = travel_engine.start_journey("edge_npc", BARN)
check("reason (target without an opening)", reason_b, "")
check("entry_edge is empty for the footprint-edge fallback",
      (journey_b or {}).get("entry_edge"), "")
travel_engine.cancel_journey("edge_npc")

# ── [2] three ticks in flight, then the arrival ─────────────────────────
print("[2] the ticker walks the route and settles at the door")
new_npc("demo_npc", HOME, 0.0, 0.0)
give_journey("demo_npc", MARKET)

tick_at(2)
check("t=2 position", pos_of("demo_npc"), (0.0, 2.0))
check("t=2 still inside HOME", get_character_current_location("demo_npc"), HOME)
check("t=2 movement_target survives", get_movement_target("demo_npc"), MARKET)

tick_at(30)
check("t=30 position", pos_of("demo_npc"), (0.0, 30.0))
check("t=30 wilderness — no location",
      get_character_current_location("demo_npc"), "")
check("t=30 wilderness — no room", get_character_current_room("demo_npc"), "")
check("t=30 movement_target SURVIVES the wilderness",
      get_movement_target("demo_npc"), MARKET)
check_true("t=30 the journey is still there",
           travel_engine.get_journey("demo_npc") is not None)

tick_at(120)
check("t=120 position", pos_of("demo_npc"), (60.0, 0.0))
check("t=120 still wilderness",
      get_character_current_location("demo_npc"), "")
check_true("t=120 the journey is still there",
           travel_engine.get_journey("demo_npc") is not None)

tick_at(155)
check("arrived at the target", get_character_current_location("demo_npc"),
      MARKET)
check("the arrival room is the one the W opening links to",
      get_character_current_room("demo_npc"), HALL)
check_true("… and not the room the arrival rule would pick",
           HALL != GROUND_ROOM_ID, f"{HALL} vs {GROUND_ROOM_ID}")
check("movement_target cleared", get_movement_target("demo_npc"), "")
check("journey gone", travel_engine.get_journey("demo_npc"), None)
check("the location write dragged the point to MARKET's centre",
      pos_of("demo_npc"), (100.0, 0.0))

print("[2b] an arrival WITHOUT an opening edge falls back to the arrival room")
new_npc("fallback_npc", "", 60.0, 0.0)
give_journey("fallback_npc", MARKET, entry_edge="")
tick_at(155)
check("arrived", get_character_current_location("fallback_npc"), MARKET)
check("room = get_arrival_room_id (the ground)",
      get_character_current_room("fallback_npc"), GROUND_ROOM_ID)

# ── [3] party followers ─────────────────────────────────────────────────
print("[3] party followers walk beside the leader")
new_npc("lead_npc", HOME, 0.0, 0.0)
new_npc("f1_npc", HOME, 0.0, 0.0)
new_npc("f2_npc", HOME, 0.0, 0.0)
check_true("f1 joined the party", add_to_party("lead_npc", "f1_npc") is not None)
check_true("f2 joined the party", add_to_party("lead_npc", "f2_npc") is not None)
give_journey("lead_npc", MARKET)

tick_at(2)
check("t=2 leader", pos_of("lead_npc"), (0.0, 2.0))
check("t=2 follower 1 (perpendicular −x)", pos_of("f1_npc"), (-1.2, 2.0))
check("t=2 follower 2 (the other side)", pos_of("f2_npc"), (1.2, 2.0))
check("t=2 followers keep no journey of their own",
      travel_engine.get_journey("f1_npc"), None)

# f2 joins the road with a journey of its own — the formation must end it.
give_journey("f2_npc", MARKET)
tick_at(30)
check("t=30 leader", pos_of("lead_npc"), (0.0, 30.0))
check("t=30 follower 1 yields to the leader's point (SHED is in the way)",
      pos_of("f1_npc"), (0.0, 30.0))
check("t=30 follower 1 did NOT enter the shed",
      get_character_current_location("f1_npc"), "")
check("t=30 follower 2 keeps its offset (nothing in the way)",
      pos_of("f2_npc"), (0.0, 28.8))
check("t=30 the follower's own journey was cancelled by the formation",
      travel_engine.get_journey("f2_npc"), None)
check("t=30 followers are in the wilderness too",
      get_character_current_location("f2_npc"), "")

# f1 picks up a LONG journey of its own (BARN, far from arriving at t=155) —
# the leader's arrival tick has to end it, or the follower walks on alone.
give_journey("f1_npc", BARN, waypoints=[[0, 30, 0], [0, 200, 10000]])
tick_at(155)
check("the leader arrived", get_character_current_location("lead_npc"), MARKET)
check("the follower's own journey did not survive the arrival",
      travel_engine.get_journey("f1_npc"), None)
check("follower 1 was dragged along (existing party hook)",
      get_character_current_location("f1_npc"), MARKET)
check("follower 2 was dragged along",
      get_character_current_location("f2_npc"), MARKET)
check("the leader stands on the target's centre", pos_of("lead_npc"),
      (100.0, 0.0))
check("follower 1 arrives IN FORMATION, not on the leader's point",
      pos_of("f1_npc"), (100.0, 1.2))
check("follower 2 on the other side", pos_of("f2_npc"), (100.0, -1.2))

# ── [4] the blocked arrival ─────────────────────────────────────────────
print("[4] a block rule ends the journey in front of the door")
RULE = add_rule({"name": "market closed", "type": "block", "action": "enter",
                 "target": {"scope": "location", "location_id": MARKET},
                 "condition": "always", "message": "The gate is barred."})
new_npc("blocked_npc", "", 60.0, 0.0)
give_journey("blocked_npc", MARKET)
EVENTS.clear()
tick_at(155)
check("stands half a metre in FRONT of the door", pos_of("blocked_npc"),
      (94.5, 0.0))
check("did NOT enter", get_character_current_location("blocked_npc"), "")
check("movement_target gone", get_movement_target("blocked_npc"), "")
check("journey gone", travel_engine.get_journey("blocked_npc"), None)
# The standoff point is outside the footprint, so an ORDINARY write at the
# character's own position cannot walk it in through the closed door.
set_character_pos("blocked_npc", 94.5, 0.0)
check("a plain write at its own position still does not enter",
      get_character_current_location("blocked_npc"), "")
_d = denials("blocked_npc")
check_true("an access_denied entry was recorded", bool(_d), f"{_d}")
check("… with action 'enter'", (_d[0] if _d else {}).get("action"), "enter")
check("… naming the target", (_d[0] if _d else {}).get("location_id"), MARKET)
_blocked = [e for e in EVENTS if e["type"] == "travel_blocked"]
check_true("a travel_blocked event was published", bool(_blocked), f"{_blocked}")
check("… for the traveller", (_blocked[0] if _blocked else {}).get("character"),
      "blocked_npc")

print("[4a] a block that settles in the SAME tick leaves no stale location")
# The whole journey (start inside HOME, refusal at MARKET's gate) happens in
# one ticker pass: no in-flight write ever ran, so the location can only come
# from the standoff write — and it must be the open terrain, not HOME.
new_npc("instant_npc", HOME, 0.0, 0.0)
give_journey("instant_npc", MARKET)
tick_at(155)
check("stands in front of the door", pos_of("instant_npc"), (94.5, 0.0))
check("location is the open terrain, NOT the start location",
      get_character_current_location("instant_npc"), "")
check("and no room either", get_character_current_room("instant_npc"), "")
check("journey gone", travel_engine.get_journey("instant_npc"), None)


def blocked_run(npc, waypoints, arrive_at):
    """Run a blocked arrival and report (position, derived location)."""
    new_npc(npc, "", waypoints[0][0], waypoints[0][1])
    give_journey(npc, MARKET, waypoints=waypoints)
    tick_at(arrive_at)
    return pos_of(npc), get_character_current_location(npc)


print("[4e] a wall-collinear approach steps back until it leaves the wall")
# Straight down x = 95, MARKET's west wall — every 0.5 m step stays ON the
# wall (and inside, the test is inclusive) until z passes the corner at 5.
_p, _l = blocked_run("wall_npc", [[95, 40, 0], [95, 0, 40]], 40)
check("stopped past the corner, not on the wall", _p, (95.0, 5.5))
check("did NOT end up in the barred location", _l, "")
set_character_pos("wall_npc", _p[0], _p[1])
check("a plain write at that point does not enter either",
      get_character_current_location("wall_npc"), "")

print("[4f] a route through the target's own footprint steps back out of it")
_p, _l = blocked_run("through_npc", [[97, 10, 0], [95, 0, 10]], 10)
check("stopped outside the footprint", _p, (96.08, 5.39))
check("did NOT end up in the barred location", _l, "")
set_character_pos("through_npc", _p[0], _p[1])
check("a plain write at that point does not enter either",
      get_character_current_location("through_npc"), "")

print("[4g] a route entirely inside the target has no point in front of it")
# MARKET's centre to MARKET's own opening: every point of the polyline lies
# in the refused location, so the fallback keeps the door point and clears
# location + room outright.
new_npc("inside_npc", "", 100.0, 0.0)
check("the start really was inside the target",
      get_character_current_location("inside_npc"), MARKET)
give_journey("inside_npc", MARKET, waypoints=[[100, 0, 0], [95, 0, 5]])
tick_at(5)
check("keeps the door point", pos_of("inside_npc"), (95.0, 0.0))
check("location cleared outright", get_character_current_location("inside_npc"),
      "")
check("room cleared too", get_character_current_room("inside_npc"), "")
check("journey gone", travel_engine.get_journey("inside_npc"), None)

delete_rule(RULE["id"])

print("[4d] _standoff_point over degenerate geometry")
# BARN stands at (0, 200) — none of the points below is anywhere near it, so
# "outside the target" is true from the first step and the walk stops there.
check("a long last segment steps back 0.5 m",
      travel_engine._standoff_point([[0, 0, 0], [10, 0, 10]], (10.0, 0.0),
                                    BARN), (9.5, 0.0))
check("a last segment shorter than the standoff continues into the one before",
      travel_engine._standoff_point(
          [[0, 0, 0], [10, 0, 10], [10.2, 0, 10.2]], (10.2, 0.0), BARN),
      (9.7, 0.0))
check("zero-length segments are skipped, not divided by",
      travel_engine._standoff_point(
          [[0, 0, 0], [10, 0, 10], [10, 0, 10]], (10.0, 0.0), BARN),
      (9.5, 0.0))
check("a route shorter than the standoff ends at its own start",
      travel_engine._standoff_point([[0, 0, 0], [0.2, 0, 0.2]], (0.2, 0.0),
                                    BARN), (0.0, 0.0))
check("no waypoints at all → the fallback point",
      travel_engine._standoff_point([], (3.0, 4.0), BARN), (3.0, 4.0))
check("a polyline entirely inside the target → None",
      travel_engine._standoff_point([[100, 0, 0], [95, 0, 5]], (95.0, 0.0),
                                    MARKET), None)

print("[4b] a leave rule aborts while the character is still at home")
LRULE = add_rule({"name": "pinned", "type": "block", "action": "leave",
                  "target": {"scope": "location", "location_id": HOME},
                  "condition": "always", "message": "You stay here."})
new_npc("pinned_npc", HOME, 0.0, 0.0)
give_journey("pinned_npc", MARKET)
tick_at(2)
check("journey cancelled by the leave rule",
      travel_engine.get_journey("pinned_npc"), None)
check("the character did not move", pos_of("pinned_npc"), (0.0, 0.0))
_pd = denials("pinned_npc")
check("a leave denial was recorded", (_pd[0] if _pd else {}).get("action"),
      "leave")
delete_rule(LRULE["id"])

print("[4c] the leave re-check stops once the start location is behind")
# Same rule, but the traveller is ALREADY in the wilderness: leaving is done,
# and re-asking would strand it halfway across the map.
LRULE2 = add_rule({"name": "pinned2", "type": "block", "action": "leave",
                   "target": {"scope": "any_room"},
                   "condition": "always", "message": "You stay here."})
new_npc("gone_npc", "", 0.0, 30.0)
give_journey("gone_npc", MARKET)
tick_at(120)
check_true("the journey survives a leave rule out in the open",
           travel_engine.get_journey("gone_npc") is not None)
check("… and the ticker kept walking", pos_of("gone_npc"), (60.0, 0.0))
delete_rule(LRULE2["id"])
travel_engine.cancel_journey("gone_npc")

# ── [5] the latent equal-location arrival ───────────────────────────────
print("[5] arriving where you already stand clears the journey exactly once")
new_npc("same_npc", MARKET, 100.0, 0.0)
give_journey("same_npc", MARKET)
tick_at(155)
check("still in the target", get_character_current_location("same_npc"), MARKET)
check("journey cleared although nothing changed",
      travel_engine.get_journey("same_npc"), None)
check("movement_target cleared too", get_movement_target("same_npc"), "")
EVENTS.clear()
travel_engine.advance_all_journeys()
check("the next tick is a complete no-op (no re-settle)", EVENTS, [])

# ── [6] a non-preserving write kills the journey ────────────────────────
print("[6b] set_character_pos in the wilderness cancels a running journey")
new_npc("tele_npc", "", 0.0, 30.0)
give_journey("tele_npc", MARKET)
set_character_pos("tele_npc", 10.0, 30.0)      # no location change at all
check("journey gone", travel_engine.get_journey("tele_npc"), None)
check("movement_target gone", get_movement_target("tele_npc"), "")
tick_at(120)
check("the ticker does NOT pull it back onto the route",
      pos_of("tele_npc"), (10.0, 30.0))

print("[6c] a teleport INTO a location cancels it via the normal lifecycle")
new_npc("tele2_npc", "", 0.0, 30.0)
give_journey("tele2_npc", MARKET)
set_character_pos("tele2_npc", 0.0, 0.0)       # real location change → HOME
check("landed in HOME", get_character_current_location("tele2_npc"), HOME)
check("journey gone", travel_engine.get_journey("tele2_npc"), None)

print("[6a] an editor re-place of the location shifts and cancels")
new_npc("shift_npc", HOME, 0.0, 0.0)
give_journey("shift_npc", MARKET)
update_location_position(HOME, 20.0, 0.0)      # editor drags HOME east
check("the occupant was shifted with the location", pos_of("shift_npc"),
      (20.0, 0.0))
check("journey gone", travel_engine.get_journey("shift_npc"), None)
check("movement_target gone", get_movement_target("shift_npc"), "")
tick_at(120)
check("the ticker leaves it where the editor put it", pos_of("shift_npc"),
      (20.0, 0.0))

# ── [7] the through-target route (final review, finding C1) ─────────────
print("[7] a route through the target's footprint never enters it ungated")
EASTGATE = add_location(name="Ticker Eastgate",
                        description="its only door faces away")["id"]
update_location_position(EASTGATE, 300.0, 0.0)
YARD = add_room(EASTGATE, "Yard", "behind the east gate")["id"]
set_map3d(EASTGATE, plan_width_m=10.0,
          boundary_openings=[{"edge": "E", "at": 0.5, "width_m": 4.0,
                              "type": "passage", "room": YARD}])
THROUGH = [[290.0, 0.0, 0.0], [300.0, 0.0, 10.0], [300.0, 30.0, 40.0],
           [305.0, 30.0, 45.0], [305.0, 0.0, 75.0]]

print("[7a] blocked: it stops on the WALKED prefix, never past the building")
GRULE = add_rule({"name": "eastgate barred", "type": "block",
                  "action": "enter",
                  "target": {"scope": "location", "location_id": EASTGATE},
                  "condition": "always", "message": "The gate is barred."})
new_npc("through_block_npc", "", 290.0, 0.0)
give_journey("through_block_npc", EASTGATE, entry_edge="E",
             waypoints=THROUGH)
EVENTS.clear()
tick_at(2)
check("t=2 outside — an ordinary in-flight write",
      pos_of("through_block_npc"), (292.0, 0.0))
check("t=2 no location", get_character_current_location("through_block_npc"),
      "")
check("t=2 the journey is alive", get_movement_target("through_block_npc"),
      EASTGATE)
tick_at(8)
check("t=8 stopped on the walked prefix, in front of the west wall",
      pos_of("through_block_npc"), (294.5, 0.0))
check("did NOT enter the barred location",
      get_character_current_location("through_block_npc"), "")
check("no room either", get_character_current_room("through_block_npc"), "")
check("movement_target gone", get_movement_target("through_block_npc"), "")
check("journey gone", travel_engine.get_journey("through_block_npc"), None)
check_true("the standoff is BEHIND the walker, not past the building",
           pos_of("through_block_npc")[0] < 298.0, "294.5 < 298 < 305")
set_character_pos("through_block_npc", 294.5, 0.0)
check("a plain write at its own position still does not enter",
      get_character_current_location("through_block_npc"), "")
_d = denials("through_block_npc")
check("an enter denial was recorded", (_d[0] if _d else {}).get("action"),
      "enter")
check("… naming the target", (_d[0] if _d else {}).get("location_id"),
      EASTGATE)
_blocked = [e for e in EVENTS if e["type"] == "travel_blocked"]
check_true("a travel_blocked event was published", bool(_blocked),
           f"{_blocked}")
delete_rule(GRULE["id"])

print("[7b] unblocked: the same tick settles as a proper arrival, once")
new_npc("through_npc2", "", 290.0, 0.0)
give_journey("through_npc2", EASTGATE, entry_edge="E", waypoints=THROUGH)
tick_at(2)
check("t=2 still travelling", get_movement_target("through_npc2"), EASTGATE)
tick_at(8)
check("the early crossing IS the arrival",
      get_character_current_location("through_npc2"), EASTGATE)
check("the room is the arrival room, NOT the far door's",
      get_character_current_room("through_npc2"), GROUND_ROOM_ID)
check_true("… and the far door really links to another room",
           YARD != GROUND_ROOM_ID, f"{YARD} vs {GROUND_ROOM_ID}")
check("movement_target cleared", get_movement_target("through_npc2"), "")
check("journey gone", travel_engine.get_journey("through_npc2"), None)
check("the location write dragged the point to the centre",
      pos_of("through_npc2"), (300.0, 0.0))
EVENTS.clear()
tick_at(20)
check("the next tick is a complete no-op (settled exactly once)", EVENTS, [])
check("… and nothing moved", pos_of("through_npc2"), (300.0, 0.0))
check("… and the location stands",
      get_character_current_location("through_npc2"), EASTGATE)

print("[7d] the goal tolerance is the REMAINING ROUTE, not a 0.5 m radius")
# Straight down EASTGATE's own east wall to its own door: x = 305 is the wall
# (inclusive), so the crossing is caught 4 m before the goal — and that IS the
# final approach to the authored opening, so its room link must win.
WALL_ROUTE = [[305.0, 40.0, 0.0], [305.0, 0.0, 40.0]]
new_npc("wallwalk_npc", "", 305.0, 40.0)
give_journey("wallwalk_npc", EASTGATE, entry_edge="E", waypoints=WALL_ROUTE)
tick_at(36)
check("the crossing settles as the arrival",
      get_character_current_location("wallwalk_npc"), EASTGATE)
check("remaining 4 m ≤ one tick's 5 m → the opening's room wins",
      get_character_current_room("wallwalk_npc"), YARD)
check("journey gone", travel_engine.get_journey("wallwalk_npc"), None)

print("[7e] the goal window rides the GAME-CLOCK factor")
# window_m = 5.0 real s per tick x factor (game s per real s) x 1.0 m/game s.
# The route is [7d]'s: 40 m down EASTGATE's own east wall, every point with
# |z| <= 5 already derives EASTGATE, so the crossing is caught early and the
# ONLY question left is whether it counts as the final approach.
set_factor(0.5)                        # window 5.0 x 0.5 x 1.0 = 2.5 m
new_npc("halfpace_npc", "", 305.0, 40.0)
give_journey("halfpace_npc", EASTGATE, entry_edge="E", waypoints=WALL_ROUTE)
tick_at(36)
check("factor 0.5 still arrives",
      get_character_current_location("halfpace_npc"), EASTGATE)
check("...but remaining 4 m > the 2.5 m window -> the arrival room",
      get_character_current_room("halfpace_npc"), GROUND_ROOM_ID)

new_npc("halfpace_npc2", "", 305.0, 40.0)
give_journey("halfpace_npc2", EASTGATE, entry_edge="E", waypoints=WALL_ROUTE)
tick_at(38)
check("two seconds later remaining 2 m <= 2.5 m -> the opening's room",
      get_character_current_room("halfpace_npc2"), YARD)

set_factor(0.0)                        # frozen -> floor 0.1 -> window 0.5 m
new_npc("frozen_npc", "", 305.0, 40.0)
give_journey("frozen_npc", EASTGATE, entry_edge="E", waypoints=WALL_ROUTE)
tick_at(36)
check("a frozen world falls back on the floor: 4 m > 0.5 m -> arrival room",
      get_character_current_room("frozen_npc"), GROUND_ROOM_ID)

new_npc("frozen_npc2", "", 305.0, 40.0)
give_journey("frozen_npc2", EASTGATE, entry_edge="E", waypoints=WALL_ROUTE)
tick_at(39.7)
check("...and the floor is not zero: remaining 0.3 m <= 0.5 m -> the door",
      get_character_current_room("frozen_npc2"), YARD)
set_factor(1.0)                        # back to the file's default pace

print("[7c] accessible_when is a wall at the arrival gate too")
VAULT = add_location(name="Ticker Vault", description="needs the key")["id"]
update_location_position(VAULT, 500.0, 0.0)
VAULT_HALL = add_room(VAULT, "Vault Hall", "behind the west door")["id"]
set_map3d(VAULT, plan_width_m=10.0,
          boundary_openings=[{"edge": "W", "at": 0.5, "width_m": 4.0,
                              "type": "passage", "room": VAULT_HALL}])
_wd = _load_world_data()
for _loc in _wd.get("locations", []):
    if _loc.get("id") == VAULT:
        _loc["accessible_when"] = ["has_item:silver_key"]
_save_world_data(_wd)
add_item(name="Silver Key", description="opens the vault", item_id="silver_key")
VAULT_ROUTE = [[460.0, 0.0, 0.0], [495.0, 0.0, 35.0]]

new_npc("keyless_npc", "", 460.0, 0.0)
give_journey("keyless_npc", VAULT, entry_edge="W", waypoints=VAULT_ROUTE)
EVENTS.clear()
tick_at(35)
check("without the key it stops in front of the door", pos_of("keyless_npc"),
      (494.5, 0.0))
check("it did NOT enter", get_character_current_location("keyless_npc"), "")
check("journey gone", travel_engine.get_journey("keyless_npc"), None)
_kd = denials("keyless_npc")
check("an enter denial was recorded", (_kd[0] if _kd else {}).get("action"),
      "enter")
check("… naming the vault", (_kd[0] if _kd else {}).get("location_id"), VAULT)
check_true("a travel_blocked event was published",
           bool([e for e in EVENTS if e["type"] == "travel_blocked"]))

new_npc("keyed_npc", "", 460.0, 0.0)
add_to_inventory("keyed_npc", "silver_key")
give_journey("keyed_npc", VAULT, entry_edge="W", waypoints=VAULT_ROUTE)
tick_at(35)
check("with the key it enters", get_character_current_location("keyed_npc"),
      VAULT)
check("and the arrival point IS the door — the opening's room wins",
      get_character_current_room("keyed_npc"), VAULT_HALL)
check("journey gone", travel_engine.get_journey("keyed_npc"), None)

print()
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}: {FAILURES}")
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
