#!/usr/bin/env python3
"""Approach arrival beat, ticker wake-up and the compose/geometry memos.

Usage: ./.venv/bin/python scripts/smoke_travel_beat.py

Runs on a private temp storage (paths.init before any world-DB import); every
DB reader is patched, nothing is composed for real.

Hand-derived expectations (fixed tick 5 s, early beat +0.1 s):
- no journeys                                   -> 5.0
- approach, 1 game s to go, factor 1            -> 1 + 0.1 = 1.1
- the same at factor 2 (game runs twice as fast) -> 1/2 + 0.1 = 0.6
- an overland journey 1 s from arrival           -> 5.0 (fixed beat only)
- an approach already arrived but not settled    -> 0.1 once, then 5.0
- a frozen world (factor 0)                      -> 5.0
- a run's entry clip ends in 2 game s, factor 1  -> 2 + 0.1 = 2.1
- the same at factor 2                           -> 2/2 + 0.1 = 1.1
- an entry already overdue                       -> 0.1
The ticker advances the runs only when a step is due (due <= 0).
due_in_game_s, now = last stamp + 1 s:
- entry clips 2 s and 3 s, 1 s elapsed           -> max(2, 3) - 1 - 1 = 1
- combined phase 5 s, 2 s elapsed                -> 5 - 2 - 1 = 2
- the earliest wins                              -> 1; nothing timed -> None
An approach starts on the first WHOLE game second >= exact now + max(exit
clip, 0.3 s lead) x factor (game time 1000, fraction 0.4 unless stated):
- no exit clip, factor 1     -> ceil(1000.4 + 0.3)  = 1001
- exit 2.23 s, factor 10     -> ceil(1000.4 + 22.3) = 1023
- fraction -0.2, factor 1    -> ceil(999.8 + 0.3)   = 1001
- frozen (factor 0)          -> lead unscaled: ceil(1000.4 + 0.3) = 1001
A woken ticker starts its next pass at once instead of after its 5 s sleep.
places._compose and room_stand.room_geometry compose once per scene
fingerprint, recompose when it moves, and hand out private copies.
"""
import asyncio
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths

paths.init(Path(tempfile.mkdtemp(prefix="smoke-travel-beat-")))

from app.core import places, room_stand, travel_engine as T  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402

NOW = GameTime.parse("Y0003-D054T11:00:00")
LATER = GameTime.parse("Y0003-D054T11:00:01")
failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"   [{detail}]"))
    if not ok:
        failures.append(label)


def row(journey_id, *, approach=True, started=NOW):
    # 1.4 m at 1.4 m/s: arrival 1 game second after the start.
    journey = dict(journey_id=journey_id, started_at_game=started.canonical(),
                   waypoints=[[0.0, 0.0, 0.0], [1.4, 0.0, 1.0]])
    if approach:
        journey["approach_target"] = {"location_id": "l", "room_id": "r"}
    return dict(name=journey_id, journey=journey)


class Engine:
    """Stand-in for the prop-action engine the ticker finds in sys.modules."""

    def __init__(self, due):
        self.due, self.advanced = due, []

    def due_in_game_s(self, now):
        return self.due

    def advance(self, now):
        self.advanced.append(now)


def beat(rows, *, factor=1.0, now=NOW, engine=None):
    with patch("app.models.character.list_active_journeys", return_value=rows), \
            patch.object(T, "game_speed_factor", return_value=factor), \
            patch.object(T, "game_time", return_value=now), \
            patch.object(T, "_prop_action_engine", return_value=engine):
        return T._next_beat_s()


def beats():
    T._early_beats.clear()
    check("no journeys -> fixed 5 s", beat([]) == 5.0, beat([]))
    got = beat([row("a")])
    check("approach 1 s out, factor 1 -> 1.1 s", abs(got - 1.1) < 1e-9, got)
    got = beat([row("a")], factor=2.0)
    check("approach 1 s out, factor 2 -> 0.6 s", abs(got - 0.6) < 1e-9, got)
    got = beat([row("o", approach=False)])
    check("overland journey keeps the fixed beat", got == 5.0, got)
    got = beat([row("a")], factor=0.0)
    check("frozen world keeps the fixed beat", got == 5.0, got)
    first = beat([row("z")], now=LATER)
    second = beat([row("z")], now=LATER)
    check("arrived approach gets ONE early beat, then the fixed one",
          (first, second) == (0.1, 5.0), (first, second))
    beat([], now=LATER)
    check("finished journeys leave the early-beat set", not T._early_beats, T._early_beats)


def entry_beats():
    got = beat([], engine=Engine(2.0))
    check("entry ends in 2 game s, factor 1 -> 2.1 s", abs(got - 2.1) < 1e-9, got)
    got = beat([], factor=2.0, engine=Engine(2.0))
    check("entry ends in 2 game s, factor 2 -> 1.1 s", abs(got - 1.1) < 1e-9, got)
    got = beat([], engine=Engine(-0.5))
    check("an overdue entry -> 0.1 s", got == 0.1, got)
    check("no timed run keeps the fixed beat", beat([], engine=Engine(None)) == 5.0)
    for due, expected in ((0.0, 1), (-1.0, 1), (0.5, 0), (None, 0)):
        engine = Engine(due)
        with patch.object(T, "_prop_action_engine", return_value=engine), \
                patch.object(T, "game_time", return_value=NOW):
            T._advance_due_prop_actions()
        check(f"due {due} -> {expected} advance call(s)", len(engine.advanced) == expected, engine.advanced)


def due_steps():
    from app.core import prop_action_engine as A
    stamp = NOW.canonical()
    entry = dict(status="approaching", phase="entry", definition=dict(ability="pose"),
                 data=dict(last_game=stamp, entry_elapsed=1.0,
                           entries={"a": dict(duration_game_s=2), "b": dict(duration_game_s=3)}))
    combined = dict(status="active", phase="drink",
                    definition=dict(ability="combined", phases=[dict(id="prepare", duration_game_s=1),
                                                               dict(id="drink", duration_game_s=5)]),
                    data=dict(last_game=stamp, phase_elapsed=2.0))
    walking = dict(status="approaching", phase="", definition=dict(ability="pose"),
                   data=dict(last_game=stamp, elapsed=0.0))
    for runs, expected in (([entry], 1), ([combined], 2), ([combined, entry, walking], 1), ([walking], None)):
        with patch.object(A.store, "live_runs", return_value=runs):
            got = A.due_in_game_s(LATER)
        check(f"due_in_game_s -> {expected}", got == expected, got)


def approach_start():
    for fraction, exit_s, factor, expected in ((0.4, 0.0, 1.0, 1001), (0.4, 2.23, 10.0, 1023),
                                               (-0.2, 0.0, 1.0, 1001), (0.4, 0.0, 0.0, 1001)):
        with patch("app.core.timeutils.game_time_exact", return_value=(GameTime(1000), fraction)), \
                patch.object(T, "game_speed_factor", return_value=factor):
            got = T._approach_start(exit_s).total_seconds
        check(f"approach start fraction {fraction} exit {exit_s} factor {factor} -> {expected}",
              got == expected, got)


def wake():
    passes = []

    async def scenario():
        ticker = T.TravelTicker()
        with patch.object(T, "advance_all_journeys", lambda: passes.append(time.monotonic())), \
                patch("app.core.interaction_engine.settle_approaches", lambda: None), \
                patch.object(T, "_advance_due_prop_actions", lambda: None), \
                patch.object(T, "_next_beat_s", return_value=5.0):
            await ticker.start()
            for _ in range(50):
                if passes:
                    break
                await asyncio.sleep(0.01)
            woken = time.monotonic()
            # Thread-safe on purpose: the real caller is a request worker thread.
            await asyncio.to_thread(ticker.wake)
            for _ in range(100):
                if len(passes) >= 2:
                    break
                await asyncio.sleep(0.01)
            await ticker.stop()
            return woken

    woken = asyncio.run(scenario())
    check("a woken ticker runs its next pass within 0.5 s, not after 5 s",
          len(passes) >= 2 and passes[1] - woken < 0.5, passes)


def memos():
    loc = {"id": "l", "pos_x": 0.0, "pos_z": 0.0, "rooms": []}
    fingerprint = ["f1"]
    composed = []

    def fresh(location_id, location):
        composed.append(location_id)
        return {"r": [{"id": "p", "slots": [[1.0, 2.0]]}]}

    places.invalidate()
    with patch("app.models.world.get_location_by_id", return_value=loc), \
            patch("app.core.scene_recipe.scene_fingerprint", side_effect=lambda *_: fingerprint[0]), \
            patch.object(places, "_compose_fresh", side_effect=fresh):
        first = places._compose("l")
        first["r"][0]["slots"][0][0] = 99.0
        second = places._compose("l")
        check("places: one compose per fingerprint", len(composed) == 1, composed)
        check("places: callers get private copies", second["r"][0]["slots"][0][0] == 1.0, second)
        fingerprint[0] = "f2"
        places._compose("l")
        check("places: a moved fingerprint recomposes", len(composed) == 2, composed)
        places.invalidate()
        places._compose("l")
        check("places: invalidate() drops the memo", len(composed) == 3, composed)

    geometry = []

    def geometry_fresh(location, room_id):
        geometry.append(room_id)
        return ([(0.0, 0.0), (4.0, 0.0), (4.0, 4.0)], [], [])

    fingerprint[0] = "g1"
    with patch("app.models.world.get_location_by_id", return_value=loc), \
            patch("app.core.scene_recipe.scene_fingerprint", side_effect=lambda *_: fingerprint[0]), \
            patch.object(room_stand, "_room_geometry_fresh", side_effect=geometry_fresh):
        a = room_stand.room_geometry("l", "r")
        a[0][0] = (9.0, 9.0)
        b = room_stand.room_geometry("l", "r")
        room_stand.room_geometry("l", "other")
        check("geometry: one compose per room and fingerprint", geometry == ["r", "other"], geometry)
        check("geometry: callers get private copies", b[0][0] == (0.0, 0.0), b)
        fingerprint[0] = "g2"
        room_stand.room_geometry("l", "r")
        check("geometry: a moved fingerprint recomposes", geometry == ["r", "other", "r"], geometry)


def main():
    beats()
    entry_beats()
    due_steps()
    approach_start()
    wake()
    memos()
    if failures:
        print(f"\n{len(failures)} check(s) failed")
        sys.exit(1)
    print("\nOK — all checks passed")


if __name__ == "__main__":
    main()
