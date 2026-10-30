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


def beat(rows, *, factor=1.0, now=NOW):
    with patch("app.models.character.list_active_journeys", return_value=rows), \
            patch.object(T, "game_speed_factor", return_value=factor), \
            patch.object(T, "game_time", return_value=now):
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


def wake():
    passes = []

    async def scenario():
        ticker = T.TravelTicker()
        with patch.object(T, "advance_all_journeys", lambda: passes.append(time.monotonic())), \
                patch("app.core.interaction_engine.settle_approaches", lambda: None), \
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
    wake()
    memos()
    if failures:
        print(f"\n{len(failures)} check(s) failed")
        sys.exit(1)
    print("\nOK — all checks passed")


if __name__ == "__main__":
    main()
