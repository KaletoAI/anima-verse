#!/usr/bin/env python3
"""Approach arrival beat, ticker wake-up and the compose/geometry memos.

Usage: ./.venv/bin/python scripts/smoke_travel_beat.py

Runs on a private temp storage (paths.init before any world-DB import); every
DB reader is patched, nothing is composed for real. The MOTION clock
(``timeutils.motion_time`` / ``motion_rate`` — real seconds the world has run
unfrozen) is pinned; movement runs in REAL time since 2026-11-05
(plan-bewegung-echtzeit.md), so the game clock's factor appears below only to
show that it changes nothing about a walk or an entry clip.

Hand-derived expectations (fixed tick 5 s, early beat +0.1 s, motion now
M = 1000.0, a 1.4 m leg baked at 1.4 m/s = 1 real second). Since plan E3
Task 7 a furniture approach walks no journey: its beats come from the run's
own times (due_in_s), a journey row gives no early beat any more:
- no journeys                                   -> 5.0
- an (old) furniture journey 1 real s to go     -> 5.0
- an overland journey 1 s from arrival           -> 5.0 (fixed beat only)
- a frozen world (motion rate 0)                 -> 5.0
- a run's next step in 2 real s                  -> 2 + 0.1 = 2.1
- the same at factor 4                           -> 2.1 (due_in_s is REAL seconds)
- a step already overdue                         -> 0.1
The ticker advances the runs only when a step is due (due <= 0), and then
only the due ones (advance(due_only=True)).
due_in_s (REAL seconds, from the run's absolute motion seconds), motion
now = M + 1, game now = last game stamp + 1 game s:
- an entry with flip_s M + 2                     -> 2 - 1 = 1
- the same at factor 4                           -> 1 (flip = motion clock)
- combined phase 5 game s, 2 elapsed, factor 1   -> (5 - 2 - 1) / 1 = 2
- the same at factor 2                           -> (5 - 2 - 1) / 2 = 1
- an NPC walking, eta_s M + 3, deadline M + 13   -> 3 - 1 = 2
- the earliest wins (factor 1)                   -> 1; an active plain pose
  run waits on no clock                          -> None
A woken ticker starts its next pass at once instead of after its 5 s sleep.
places._compose and room_stand.room_geometry compose once per scene
fingerprint, recompose when it moves, and hand out private copies; since
da084dc88 the fingerprint is the narrowed one (compose_recorded /
narrowed_fingerprint) and places.invalidate() leaves the composed markers.
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

from app.core import places, room_stand, timeutils, travel_engine as T  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402

NOW = GameTime.parse("Y0003-D054T11:00:00")
LATER = GameTime.parse("Y0003-D054T11:00:01")
M = 1000.0
failures = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"   [{detail}]"))
    if not ok:
        failures.append(label)


def row(journey_id, *, approach=True, started=M):
    # 1.4 m at 1.4 m/s: arrival 1 real second after the start. `approach`: a
    # journey a prop-action run walked before plan E3 (its owner kind).
    journey = dict(journey_id=journey_id, started_at_s=started,
                   waypoints=[[0.0, 0.0, 0.0], [1.4, 0.0, 1.0]])
    if approach:
        journey.update(execution_kind="prop_action", execution_ref="run-old")
    return dict(name=journey_id, journey=journey)


class Engine:
    """Stand-in for the prop-action engine the ticker finds in sys.modules."""

    def __init__(self, due):
        self.due, self.advanced = due, []

    def due_in_s(self, now):
        return self.due

    def advance(self, now, *, due_only=False):
        self.advanced.append((now, due_only))


def clocks(*, factor=1.0, rate=1.0, motion=M, game=NOW):
    """Pin the motion clock, its rate and the game clock (+ its factor)."""
    return (patch.object(timeutils, "motion_time", return_value=motion),
            patch.object(timeutils, "motion_rate", return_value=rate),
            patch.object(timeutils, "game_speed_factor", return_value=factor),
            patch.object(T, "game_time", return_value=game))


def beat(rows, *, factor=1.0, rate=1.0, motion=M, engine=None):
    c = clocks(factor=factor, rate=rate, motion=motion)
    with patch("app.models.character.list_active_journeys", return_value=rows), \
            c[0], c[1], c[2], c[3], \
            patch.object(T, "_prop_action_engine", return_value=engine):
        return T._next_beat_s()


def beats():
    check("no journeys -> fixed 5 s", beat([]) == 5.0, beat([]))
    got = beat([row("a")])
    check("an approach journey gives no early beat any more", got == 5.0, got)
    got = beat([row("o", approach=False)])
    check("overland journey keeps the fixed beat", got == 5.0, got)
    got = beat([row("a")], rate=0.0)
    check("frozen world keeps the fixed beat", got == 5.0, got)


def entry_beats():
    got = beat([], engine=Engine(2.0))
    check("entry ends in 2 real s, factor 1 -> 2.1 s", abs(got - 2.1) < 1e-9, got)
    got = beat([], factor=4.0, engine=Engine(2.0))
    check("entry ends in 2 real s, factor 4 -> 2.1 s", abs(got - 2.1) < 1e-9, got)
    got = beat([], engine=Engine(-0.5))
    check("an overdue entry -> 0.1 s", got == 0.1, got)
    check("no timed run keeps the fixed beat", beat([], engine=Engine(None)) == 5.0)
    for due, expected in ((0.0, 1), (-1.0, 1), (0.5, 0), (None, 0)):
        engine = Engine(due)
        with patch.object(T, "_prop_action_engine", return_value=engine), \
                patch.object(T, "game_time", return_value=NOW):
            T._advance_due_prop_actions()
        check(f"due {due} -> {expected} advance call(s)", len(engine.advanced) == expected, engine.advanced)
        check(f"due {due}: only the due runs (due_only)", all(only for _now, only in engine.advanced),
              engine.advanced)


def due_steps():
    from app.core import prop_action_engine as A
    stamp = NOW.canonical()
    base = dict(execution_id="run-x", actor="a", members=[])
    entry = dict(base, status="approaching", phase="entry", definition=dict(ability="pose"),
                 data=dict(last_game=stamp, last_motion=M, flip_s=M + 2))
    combined = dict(base, status="active", phase="drink",
                    definition=dict(ability="combined", phases=[dict(id="prepare", duration_game_s=1),
                                                               dict(id="drink", duration_game_s=5)]),
                    data=dict(last_game=stamp, last_motion=M, phase_elapsed=2.0))
    walking = dict(base, status="approaching", phase="", definition=dict(ability="pose"),
                   data=dict(last_game=stamp, last_motion=M, arrived=[], eta_s={"a": M + 3},
                             deadline_s=M + 13))
    sitting = dict(base, status="active", phase="active", definition=dict(ability="pose"),
                   data=dict(last_game=stamp, last_motion=M))
    for runs, factor, expected in (([entry], 1.0, 1), ([entry], 4.0, 1), ([combined], 1.0, 2),
                                   ([combined], 2.0, 1), ([walking], 1.0, 2),
                                   ([combined, entry, walking], 1.0, 1), ([sitting], 1.0, None)):
        with patch.object(A.store, "live_runs", return_value=runs), \
                patch.object(timeutils, "motion_time", return_value=M + 1), \
                patch.object(A, "_meters", return_value=[]), \
                patch.object(A, "game_speed_factor", return_value=factor):
            got = A.due_in_s(LATER)
        check(f"due_in_s at factor {factor} -> {expected}", got == expected, got)


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
    # Since da084dc88 both memos key on the props their own compose read: the key comes from
    # ``scene_recipe.compose_recorded`` and a hit is checked with ``narrowed_fingerprint`` (their own rules are
    # smoke_places_read_set.py's). Here both seams return the fixture's fingerprint; ``places.invalidate()``
    # drops only the TTL inventory since then ("the composed markers stay"), so it composes nothing.
    loc = {"id": "l", "pos_x": 0.0, "pos_z": 0.0, "rooms": []}
    fingerprint = ["f1"]
    composed = []

    def keyed(_loc, _lid, compose):
        return compose(), frozenset(), fingerprint[0]

    def fresh(location_id, location):
        composed.append(location_id)
        return {"r": [{"id": "p", "slots": [[1.0, 2.0]]}]}

    places.invalidate()
    with patch("app.models.world.get_location_by_id", return_value=loc), \
            patch("app.core.scene_recipe.compose_recorded", side_effect=keyed), \
            patch("app.core.scene_recipe.narrowed_fingerprint", side_effect=lambda *_: fingerprint[0]), \
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
        check("places: invalidate() keeps the memo (da084dc88)", len(composed) == 2, composed)

    geometry = []

    def geometry_fresh(location, room_id):
        geometry.append(room_id)
        return ([(0.0, 0.0), (4.0, 0.0), (4.0, 4.0)], [], [])

    fingerprint[0] = "g1"
    with patch("app.models.world.get_location_by_id", return_value=loc), \
            patch("app.core.scene_recipe.compose_recorded", side_effect=keyed), \
            patch("app.core.scene_recipe.narrowed_fingerprint", side_effect=lambda *_: fingerprint[0]), \
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
    wake()
    memos()
    if failures:
        print(f"\n{len(failures)} check(s) failed")
        sys.exit(1)
    print("\nOK — all checks passed")


if __name__ == "__main__":
    main()
