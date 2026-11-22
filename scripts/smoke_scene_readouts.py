#!/usr/bin/env python3
"""CHANNEL READOUTS reported by the clients (`app/core/pose_scene.py`
`report_readouts` / `readouts`, route `POST /play/scene/readouts`, plan pair
scene Task 5): a client reports a <= 1 Hz summary per (scene, receiver,
channel, entering); the server keeps the latest per key and every beat of
the scene (`scene.active`) carries it.

Usage:
    ./.venv/bin/python scripts/smoke_scene_readouts.py

Runs on the temporary world of `smoke_prop_action_runs.py` (its fixtures):
no server, no real world DB, no real clips.

THE FIXTURE
===========
A and B of `authored_pair` play the FREE pair scene I (the interaction blob
on both profiles, roles a/b) in room "hall" of the fixture location. V stands
in the same room at (3, 5); X belongs to the same location but to no room
(the fixture refuses the room "cellar" it asks for: the location has only
"hall"), far off at (500, 500) — outside every earshot circle. The SYSTEM
clock pose_scene reads (`utc_now`) is pinned to t0 + the seconds named.
One report row: receiver A, channel "inset", entering B, insertion_of_depth
0.5, part_radius_m 0.02, rest_radius_m 0.03, depth_m 0.2, reaches 1.

EXPECTATIONS, DERIVED BY HAND
=============================
[1] ACCEPTED: V reports the row at t0 -> accepted 1; readouts(I) at t0 ->
    exactly that row with source "client".
[2] RATE: the same key again at t0 + 0.5 -> 0 (0.5 < READOUT_MIN_INTERVAL_S
    0.8); a second key (channel "mouth") at t0 + 0.5 -> 1 (its own key);
    the first key at t0 + 0.8 -> 1 (0.8 >= 0.8). One report with the same
    key twice counts once (the second is within 0 s of the first).
[3] WHO MAY REPORT: X (no room, far off) -> 0, no 403; a viewer with no
    avatar -> 0; the same viewer as admin -> 1; A itself (a member) -> 1.
[4] ONLY A LIVE SCENE AND ITS MEMBERS: scene id "nope" -> 0; entering V (not
    a member) -> 0; receiver == entering -> 0; after the pair ended -> 0.
[5] FRESHNESS (READOUT_FRESH_S 5): a report at t0 is handed out at t0 + 5
    and not at t0 + 5.01 (and then forgotten: still nothing at t0 + 5.01).
[6] REACHES ARE SUMMED UNTIL THE NEXT READ, then reset: reports at t0
    (reaches 2, insertion_of_depth 0.4) and t0 + 1 (reaches 3,
    insertion_of_depth 0.9) -> readouts at t0 + 1.5: reaches 2 + 3 = 5 and
    the values of the LATER report (0.9); read again at t0 + 1.5: reaches 0,
    the values still there; a report at t0 + 2 with reaches 1 -> 1.
[7] THE BEAT CARRIES THEM: a report (reaches 1) then `emit_active` of I ->
    the `scene.active` listener sees readouts == [that row, reaches 1]; a
    second beat -> the same row with reaches 0.
[8] INVALID ROWS ARE DROPPED: a negative depth_m, NaN insertion_of_depth, a
    receiver that is no string, reaches -1 or 1.5, a missing field -> 0 each.
[9] THE ROUTE (`_play_scene_readouts_sync`): V's user -> {"accepted": 1};
    X's user -> {"accepted": 0} (200, no 403); a body without scene_id ->
    400; readouts that are no list -> 400.
[10] THE SCENE'S END forgets its readouts: `end_finales(I)` -> readouts(I)
    is [] at once.
"""
import math
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_prop_action_runs as RUNS                                 # noqa: E402

F = RUNS.F
F.paths.init(F.ROOT / "world")
from fastapi import HTTPException                                       # noqa: E402
from app.core import hooks, pose_scene as S                             # noqa: E402
from app.core import interaction_engine as IE                            # noqa: E402
from app.models import account                                          # noqa: E402
from app.routes import play                                             # noqa: E402

BEATS = []
hooks.register("scene.active", lambda **kw: BEATS.append(kw), tag="smoke.scene_readouts")
T0 = S.utc_now()


def at(seconds):
    return patch.object(S, "utc_now", lambda: T0 + timedelta(seconds=seconds))


def row(receiver, entering, **kw):
    base = dict(receiver=receiver, channel="inset", entering=entering, insertion_of_depth=0.5,
                part_radius_m=0.02, rest_radius_m=0.03, depth_m=0.2, reaches=1)
    base.update(kw)
    return base


def stored(receiver, entering, **kw):
    return dict(row(receiver, entering, **kw), source="client")


def start_pair(a, b, interaction_id):
    started = F.game_time().canonical()
    for name, role in ((a, "a"), (b, "b")):
        profile = F.C.get_character_profile(name)
        profile["interaction"] = dict(id=interaction_id, kind="run-pair", role=role,
                                      started_at_game=started, members={"a": a, "b": b},
                                      pose_key="run-pair")
        assert F.C.save_character_profile(name, profile)


class SceneReadouts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a, cls.b, target, _pid = RUNS.authored_pair()
        loc = target["location_id"]
        cls.v = F.actor(loc, room="hall", at=(3, 5))
        cls.x = F.actor(loc, room="cellar", at=(500, 500))

    def setUp(self):
        S._readouts.clear()
        BEATS.clear()
        self.scene = "ro-" + self._testMethodName
        start_pair(self.a, self.b, self.scene)

    def tearDown(self):
        IE.end_interaction(self.a, reason="ended")

    def report(self, rows, viewer=None, admin=False, scene=None):
        return S.report_readouts(scene or self.scene, rows, viewer=self.v if viewer is None else viewer,
                                 admin=admin)

    def test_1_accepted(self):
        with at(0):
            self.assertEqual(self.report([row(self.a, self.b)]), 1)
            self.assertEqual(S.readouts(self.scene), [stored(self.a, self.b)])

    def test_2_rate(self):
        a, b = self.a, self.b
        with at(0):
            self.assertEqual(self.report([row(a, b)]), 1)
        with at(0.5):
            self.assertEqual(self.report([row(a, b)]), 0)
            self.assertEqual(self.report([row(a, b, channel="mouth")]), 1)
        with at(0.8):
            self.assertEqual(self.report([row(a, b)]), 1)
        with at(10):
            self.assertEqual(self.report([row(a, b), row(a, b)]), 1)

    def test_3_who(self):
        a, b = self.a, self.b
        with at(0):
            self.assertEqual(self.report([row(a, b)], viewer=self.x), 0)
            self.assertEqual(self.report([row(a, b)], viewer=""), 0)
            self.assertEqual(self.report([row(a, b)], viewer="", admin=True), 1)
            self.assertEqual(self.report([row(a, b, channel="mouth")], viewer=a), 1)

    def test_4_live(self):
        a, b = self.a, self.b
        with at(0):
            self.assertEqual(self.report([row(a, b)], scene="nope"), 0)
            self.assertEqual(self.report([row(a, self.v)]), 0)
            self.assertEqual(self.report([row(a, a)]), 0)
            IE.end_interaction(a, reason="ended")
            self.assertEqual(self.report([row(a, b)]), 0)

    def test_5_fresh(self):
        with at(0):
            self.report([row(self.a, self.b)])
        with at(5):
            self.assertEqual(len(S.readouts(self.scene)), 1)
        with at(5.01):
            self.assertEqual(S.readouts(self.scene), [])
            self.assertEqual(S.readouts(self.scene), [])

    def test_6_reaches(self):
        a, b = self.a, self.b
        with at(0):
            self.report([row(a, b, reaches=2, insertion_of_depth=0.4)])
        with at(1):
            self.report([row(a, b, reaches=3, insertion_of_depth=0.9)])
        with at(1.5):
            self.assertEqual(S.readouts(self.scene), [stored(a, b, reaches=5, insertion_of_depth=0.9)])
            self.assertEqual(S.readouts(self.scene), [stored(a, b, reaches=0, insertion_of_depth=0.9)])
        with at(2):
            self.report([row(a, b, reaches=1, insertion_of_depth=0.9)])
            self.assertEqual(S.readouts(self.scene)[0]["reaches"], 1)

    def test_7_beat(self):
        a, b = self.a, self.b
        with at(0):
            self.report([row(a, b)])
            for _ in range(2):
                S.emit_active(scene_id=self.scene, kind="interaction", members=[a, b],
                              roles={"a": a, "b": b}, pose_key="run-pair", delta_game_s=1.0)
        self.assertEqual([beat["readouts"] for beat in BEATS],
                         [[stored(a, b)], [stored(a, b, reaches=0)]])

    def test_8_invalid(self):
        a, b = self.a, self.b
        bad = [row(a, b, depth_m=-0.1), row(a, b, insertion_of_depth=math.nan), row(7, b),
               row(a, b, reaches=-1), row(a, b, reaches=1.5)]
        missing = row(a, b)
        missing.pop("rest_radius_m")
        with at(0):
            for one in bad + [missing]:
                self.assertEqual(self.report([one]), 0, one)

    def test_9_route(self):
        a, b = self.a, self.b
        body = dict(scene_id=self.scene, readouts=[row(a, b)])
        user = dict(role="user")
        with at(0), patch.object(account, "get_active_character", lambda: self.v):
            self.assertEqual(play._play_scene_readouts_sync(user, body), {"accepted": 1})
        with at(5), patch.object(account, "get_active_character", lambda: self.x):
            self.assertEqual(play._play_scene_readouts_sync(user, body), {"accepted": 0})
            for broken in (dict(readouts=[]), dict(scene_id=self.scene, readouts={})):
                with self.assertRaises(HTTPException) as caught:
                    play._play_scene_readouts_sync(user, broken)
                self.assertEqual(caught.exception.status_code, 400)

    def test_10_end(self):
        with at(0):
            self.report([row(self.a, self.b)])
            S.end_finales(self.scene)
            self.assertEqual(S.readouts(self.scene), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
