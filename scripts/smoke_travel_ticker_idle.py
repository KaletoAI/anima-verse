#!/usr/bin/env python3
"""Smoke run for the IDLE cost of the travel ticker (SIM-2, 2026-09-20 review).

Usage:
    ./.venv/bin/python scripts/smoke_travel_ticker_idle.py

Runs against a THROWAWAY storage directory — never touches a real world.
``ANIMATION_CLIPS_DIR`` is redirected before the app modules are imported.

WHAT IS MEASURED AND WHY

``advance_all_journeys`` used to answer "who is travelling?" by loading the
FULL profile of every character (``get_journey(name)`` with no profile
handed in). A profile load is two SELECTs plus ``_inject_soul_md_values``,
which deep-copies the character template and re-reads every ``source_file``
of it. The ticker runs every 5 s, around the clock, and the honest answer is
almost always "nobody".

The fix answers the same question with ONE query
(``character.list_active_journeys``): ``json_extract`` over
``characters.profile_json`` for ``journey`` joined with
``character_state.meta`` for ``movement_target`` — the two fields live in
DIFFERENT stores (``_STATE_META_KEYS`` moves ``movement_target`` into the
state meta on save), which is why the query needs the join.

Hand-derived expectations — the number of profile loads is counted by
wrapping ``app.models.character.get_character_profile``:

  [1] FIVE characters, nobody travelling: the JOURNEY pass must do no work
      at all — ``travel_engine.get_journey`` is never called and
      ``list_active_journeys()`` is empty. Before the fix that pass alone
      cost one full profile load per character in the roster.

  [1b] The whole tick then costs exactly ONE profile load per character, and
      that one belongs to the SECOND pass, not to the journeys: discovery by
      sight asks ``get_known_locations`` → ``get_character_config``, which
      reads the profile for ``tts_language``/``decency_preference``. (That
      used to be TWO loads per call — one per field; they are now one.) The
      second pass must run for non-travellers too — a teleport or an admin
      move puts someone beside a hut just as a road does — so this is the
      floor, not a leak. Pre-fix cost of the same tick: 3 loads per
      character (1 journey + 2 config).

  [2] ONE traveller among the five: the tick may load the TRAVELLER's
      profile (the settle path writes it) and every other character AT MOST
      the one discovery load of [1b] — never a second one for a journey
      they do not have.

  [3] The traveller arrives and is settled EXACTLY ONCE. After the arrival
      tick its ``current_location`` is the target and ``movement_target`` is
      empty; a second tick at the same clock therefore finds no journey and
      settles nothing (asserted through ``state_events``: exactly one
      ``travel_*`` arrival cascade, and no second location change).

  [4] The bulk answer agrees with the per-character reader: for every name,
      ``list_active_journeys`` reports a journey exactly when
      ``travel_engine.get_journey(name)`` does. That is what makes [1] a
      speed-up rather than a behaviour change.

The route below is the same shape smoke_travel_ticker.py uses: HOME at
(0,0) with a 10 m footprint and a south opening at (0,5); MARKET at (100,0)
with a 10 m footprint and a west opening at (95,0); 1 m per game second, so
the position at t seconds is read off the polyline directly and arrival is
at t = 155 s.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="ticker-idle-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="ticker-idle-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import travel_engine  # noqa: E402
from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models import character as character_model  # noqa: E402
from app.models.character import (get_character_current_location,  # noqa: E402
                                  get_character_profile,
                                  get_movement_target,
                                  list_active_journeys,
                                  save_character_current_location,
                                  save_character_profile, set_character_pos,
                                  set_known_locations)
from app.models.world import (_load_world_data, _save_world_data,  # noqa: E402
                              add_location, add_room,
                              update_location_position)

START = "Y0001-D001T12:00:00"
START_GT = GameTime.parse(START)
ROUTE = [[0.0, 0.0, 0.0], [0.0, 5.0, 5.0], [0.0, 30.0, 30.0],
         [60.0, 30.0, 90.0], [60.0, 0.0, 120.0], [95.0, 0.0, 155.0]]
ARRIVAL_S = 155.0

FAILURES = []


def check(label, ok, detail=""):
    print(f"  [{'ok' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def set_map3d(location_id, **fields):
    width = fields.get("plan_width_m")
    if width:
        h = round(float(width) / 2.0, 2)
        fields.setdefault("boundary", [[-h, -h], [h, -h], [h, h], [-h, h]])
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            m = dict(loc.get("map3d") or {})
            m.update(fields)
            loc["map3d"] = m
    _save_world_data(data)


# ── the world ───────────────────────────────────────────────────────────
HOME = add_location(name="Idle Home", description="ticker idle smoke")["id"]
update_location_position(HOME, 0.0, 0.0)
set_map3d(HOME, plan_width_m=10.0,
          boundary_openings=[{"edge": 2, "at": 0.5, "width_m": 4.0,
                              "type": "passage"}])
MARKET = add_location(name="Idle Market", description="ticker idle smoke")["id"]
update_location_position(MARKET, 100.0, 0.0)
HALL = add_room(MARKET, "Hall", "the room the west gate opens into")["id"]
set_map3d(MARKET, plan_width_m=10.0,
          boundary_openings=[{"edge": 3, "at": 0.5, "width_m": 4.0,
                              "type": "passage", "room": HALL}])

set_game_factor(0.0)                  # the game clock stands still — pinned
set_game_time(START_GT)
# The goal window (``_at_goal``) reads the clock factor, and a stopped clock
# reports 0.0. Injected at 1× so "one tick = 5 game seconds" holds.
travel_engine.game_speed_factor = lambda: 1.0

NAMES = ["Idle1", "Idle2", "Idle3", "Idle4", "Walker"]
for n in NAMES:
    save_character_profile(n, {"current_location": ""}, create_new=True)
    save_character_current_location(n, HOME)
    set_character_pos(n, 0.0, 0.0)
    set_known_locations(n, [HOME, MARKET])


# ── the profile-load counter ────────────────────────────────────────────
_real_get_profile = character_model.get_character_profile
LOADED = []


def counting_get_profile(name):
    LOADED.append(name)
    return _real_get_profile(name)


def tick_at(seconds):
    """Pin the game clock to START + seconds and run ONE ticker pass."""
    set_game_time(START_GT + GameDuration.of(seconds=seconds))
    travel_engine.advance_all_journeys()


#: Names the JOURNEY pass asked ``get_journey`` about during one measure().
JOURNEY_CALLS = []
_real_get_journey = travel_engine.get_journey


def counting_get_journey(name, profile=None):
    JOURNEY_CALLS.append(name)
    return _real_get_journey(name, profile=profile)


def measure(fn):
    """Run ``fn`` with both counters armed; returns (loaded_names, seconds)."""
    LOADED.clear()
    JOURNEY_CALLS.clear()
    character_model.get_character_profile = counting_get_profile
    travel_engine.get_journey = counting_get_journey
    t0 = time.perf_counter()
    try:
        fn()
    finally:
        character_model.get_character_profile = _real_get_profile
        travel_engine.get_journey = _real_get_journey
    return list(LOADED), time.perf_counter() - t0


def main():
    print("=" * 72)
    print("travel ticker: idle cost and single settle (SIM-2)")
    print("=" * 72)

    # ── [1] nobody travels ──────────────────────────────────────────────
    loaded, secs = measure(lambda: tick_at(0.0))
    print(f"\n[1] idle tick over {len(NAMES)} characters: "
          f"{len(loaded)} profile load(s), {secs * 1000:.2f} ms")
    check("[1] the journey pass asked get_journey zero times",
          JOURNEY_CALLS == [], repr(JOURNEY_CALLS))
    check("[1] …and list_active_journeys is empty",
          list_active_journeys() == [], repr(list_active_journeys()))
    check("[1b] exactly one profile load per character (the discovery pass)",
          len(loaded) == len(NAMES)
          and sorted(loaded) == sorted(NAMES), repr(sorted(loaded)))

    _, many = measure(lambda: [tick_at(float(i)) for i in range(20)])
    print(f"    20 idle ticks: {many * 1000:.2f} ms "
          f"({many * 1000 / 20:.2f} ms per tick)")

    # ── [4] the bulk answer agrees with the per-character reader ────────
    active = {a["name"] for a in list_active_journeys() if a["journey"]}
    per_char = {n for n in NAMES if travel_engine.get_journey(n) is not None}
    check("[4] bulk == per-character, nobody travelling",
          active == per_char == set(), f"{active} / {per_char}")

    # ── one traveller ───────────────────────────────────────────────────
    journey, reason = travel_engine.start_journey("Walker", MARKET)
    check("setup: the journey started", reason == "" and journey is not None,
          reason)
    # Hand-written waypoints so every position below is exact.
    prof = get_character_profile("Walker")
    prof["journey"] = {"target": MARKET, "waypoints": [list(w) for w in ROUTE],
                       "started_at_game": START, "speed_m_s": 1.0,
                       "entry_edge": 3}
    prof["movement_target"] = MARKET
    save_character_profile("Walker", prof)

    active = {a["name"] for a in list_active_journeys() if a["journey"]}
    per_char = {n for n in NAMES if travel_engine.get_journey(n) is not None}
    check("[4] bulk == per-character, one traveller",
          active == per_char == {"Walker"}, f"{active} / {per_char}")

    # ── [2] a tick in flight touches only the traveller ─────────────────
    loaded, secs = measure(lambda: tick_at(30.0))
    print(f"\n[2] in-flight tick: {len(loaded)} profile load(s), "
          f"{secs * 1000:.2f} ms — {sorted(set(loaded))}")
    check("[2] the journey pass asked get_journey only for the traveller",
          JOURNEY_CALLS == ["Walker"], repr(JOURNEY_CALLS))
    check("[2] no idle character is loaded more than the one discovery load",
          all(loaded.count(n) == 1 for n in NAMES[:4]),
          repr({n: loaded.count(n) for n in NAMES}))
    check("[2] the traveller is at (0, 30) — mid-route, outside every "
          "footprint", get_character_current_location("Walker") == "",
          get_character_current_location("Walker"))

    # ── [3] arrival settles exactly once ────────────────────────────────
    tick_at(ARRIVAL_S)
    at_first = get_character_current_location("Walker")
    target_after = get_movement_target("Walker")
    check("[3] arrived at the target", at_first == MARKET, at_first)
    check("[3] movement_target cleared by the arrival", target_after == "",
          repr(target_after))

    loaded2, _ = measure(lambda: tick_at(ARRIVAL_S))
    check("[3] the second tick finds no journey and settles nothing",
          travel_engine.get_journey("Walker") is None
          and get_character_current_location("Walker") == MARKET
          and not list_active_journeys(),
          repr(list_active_journeys()))
    check("[3] …and costs no journey-pass profile load either",
          JOURNEY_CALLS == [] and sorted(loaded2) == sorted(NAMES),
          f"{JOURNEY_CALLS} / {sorted(loaded2)}")

    print("\n" + "=" * 72)
    if FAILURES:
        print(f"FAIL — {len(FAILURES)} check(s):")
        for f in FAILURES:
            print(f"  {f}")
        return 1
    print("PASS — all checks green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
