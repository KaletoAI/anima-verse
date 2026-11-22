#!/usr/bin/env python3
"""The TEMPO and the CLIP CLOCK of a running scene (`app/core/pose_scene.py`,
plan pair scene Task 4): the server integrates one clip clock per scene,
`clip_s += (real unfrozen seconds since the last touch) * tempo before it`,
on every beat and every payload read; the tempo is refreshed on each beat
from the provider `scene.tempo(scene_id, members, roles, pose_key, lead_role)`,
clamped to [0.2, 1], 1 without a provider or an answer; a pose switch (same
scene id, new pose) resets the clock to 0. The worldmap's `interaction` block
(`interaction_engine.payload_for`) carries `tempo` and `clip_s`.

Usage:
    ./.venv/bin/python scripts/smoke_pose_scene_tempo.py

Runs on the temporary world of `smoke_prop_action_runs.py` (its fixtures):
no server, no real world DB, no real clips.

THE FIXTURE
===========
Two characters A and B of `authored_pair` and its pair pose `run-pair`
(roles a/b, no stored lead role -> lead role "a"). A FREE pair is the
interaction blob on both profiles, id I. The MOTION clock pose_scene reads
(`motion_time`: real seconds the world ran unfrozen) is pinned to M and moved
by hand, except in [3], which runs the real motion clock (the fixture's
`REAL_MOTION_TIME`, derived from a pinned `utc_now`) under a real freeze.

EXPECTATIONS, DERIVED BY HAND
=============================
[1] TWO BEATS 10 s APART. The provider answers 0.2, then 1.0.
    M = 0:  beat 1 -> the clock is new: clip_s 0, then the tempo becomes 0.2.
            The provider saw scene_id I, members [A, B], roles {a: A, b: B},
            pose_key run-pair, lead_role a.
    M = 10: beat 2 -> clip_s = 0 + 10 * 0.2 = 2.0 (the tempo BEFORE the
            beat), then the tempo becomes 1.0.
    M = 20: a payload read -> clip_s = 2.0 + 10 * 1.0 = 12.0, tempo 1.0 —
            the same numbers on A's and on B's row (one clock per scene).
            `elapsed_s` is still in the block.
[2] THE ANSWER IS CLAMPED. Each answer arrives on a beat, read back on the
    payload at the same M (so clip_s does not move): 5 -> 1.0; None -> 1.0;
    "x" -> 1.0; a provider that raises -> 1.0; 0.05 -> 0.2 (clamped below);
    0.5 -> 0.5; and with no provider at all -> 1.0.
[3] A FROZEN WORLD STOPS THE CLOCK. Real motion clock, tempo 1 (no
    provider). Read at system time s0 -> c. Freeze; read at s0 + 30 -> still
    c (and a beat at s0 + 30 changes nothing either). Thaw at s0 + 30; read at
    s0 + 40 -> c + 10 * 1.0 = c + 10.
[4] A POSE SWITCH RESETS THE CLOCK, the scene stays. Pinned M: the provider
    answers 0.5 at M = 0 (clip 0); at M = 4 the payload says 4 * 0.5 = 2.0.
    The blob switches to pose "run-pair-2" (same id): at M = 6 the payload
    says clip_s 0.0 — the new clip starts — and tempo 0.5 (kept); at M = 8,
    2 * 0.5 = 1.0.
[5] A FURNITURE PAIR is timed by its RUN's scene (scene id = the blob's
    `execution_ref`, the run's execution_id R): a beat of scene R with the
    answer 0.4 at M = 0, then a payload read of a blob with
    execution_kind "prop_action", execution_ref R at M = 5 -> clip_s
    5 * 0.4 = 2.0, tempo 0.4. The free scene I was not touched by it.
"""
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_prop_action_runs as RUNS                                 # noqa: E402

F = RUNS.F
F.paths.init(F.ROOT / "world")
from app.core import hooks, timeutils, pose_scene as S                  # noqa: E402
from app.core import interaction_engine as IE                            # noqa: E402

OWNER = "smoke.pose_scene_tempo"
SEEN = []


def provide(*answers):
    """Registers a `scene.tempo` provider answering `answers` in turn."""
    queue = list(answers)

    def tempo(**kw):
        SEEN.append(kw)
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer
    hooks.unregister_owned_providers(OWNER)
    hooks.register_provider("scene.tempo", tempo, owner=OWNER)


def no_provider():
    hooks.unregister_owned_providers(OWNER)


def motion(seconds):
    return patch.object(S, "motion_time", lambda: float(seconds))


def start_pair(a, b, interaction_id, pose="run-pair"):
    started = F.game_time().canonical()
    for name, role in ((a, "a"), (b, "b")):
        profile = F.C.get_character_profile(name)
        profile["interaction"] = dict(id=interaction_id, kind="run-pair", role=role,
                                      started_at_game=started, members={"a": a, "b": b},
                                      pose_key=pose)
        assert F.C.save_character_profile(name, profile)


def beat(scene_id, a, b, pose="run-pair"):
    S.emit_active(scene_id=scene_id, kind="interaction", members=[a, b], roles={"a": a, "b": b},
                  pose_key=pose, delta_game_s=1.0)


def block(name, profile=None):
    profile = profile if profile is not None else F.C.get_character_profile(name)
    return IE.payload_for(name, profile, F.game_time(), 1.0)


class SceneTempo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a, cls.b, _target, _pid = RUNS.authored_pair()

    def setUp(self):
        S._clocks.clear()
        SEEN.clear()
        no_provider()
        F.W.set_world_frozen(False)

    def tearDown(self):
        no_provider()
        F.W.set_world_frozen(False)
        IE.end_interaction(self.a, reason="ended")

    def test_1_two_beats(self):
        a, b = self.a, self.b
        start_pair(a, b, "tempo-i1")
        provide(0.2, 1.0)
        with motion(0):
            beat("tempo-i1", a, b)
        self.assertEqual(SEEN[0], dict(scene_id="tempo-i1", members=[a, b], roles={"a": a, "b": b},
                                       pose_key="run-pair", lead_role="a"))
        with motion(10):
            beat("tempo-i1", a, b)
            self.assertEqual(S._clocks["tempo-i1"]["clip_s"], 2.0)
        with motion(20):
            for name in (a, b):
                row = block(name)
                self.assertEqual((row["clip_s"], row["tempo"]), (12.0, 1.0))
                self.assertIn("elapsed_s", row)

    def test_2_clamp(self):
        a, b = self.a, self.b
        start_pair(a, b, "tempo-i2")
        cases = [(5, 1.0), (None, 1.0), ("x", 1.0), (RuntimeError("provider down"), 1.0),
                 (0.05, 0.2), (0.5, 0.5)]
        with motion(0):
            for answer, tempo in cases:
                provide(answer)
                beat("tempo-i2", a, b)
                self.assertEqual(block(a)["tempo"], tempo, answer)
            no_provider()
            beat("tempo-i2", a, b)
            self.assertEqual(block(a)["tempo"], 1.0)
            self.assertEqual(block(a)["clip_s"], 0.0)

    def test_3_freeze(self):
        a, b = self.a, self.b
        start_pair(a, b, "tempo-i3")
        s0 = timeutils.utc_now()

        def at(seconds):
            return patch.object(timeutils, "utc_now", lambda: s0 + timedelta(seconds=seconds))
        real = patch.object(S, "motion_time", F.REAL_MOTION_TIME)   # the fixture pins it otherwise
        real.start()
        self.addCleanup(real.stop)
        with at(0):
            c = block(a)["clip_s"]
            F.W.set_world_frozen(True)
        with at(30):
            self.assertEqual(block(a)["clip_s"], c)
            beat("tempo-i3", a, b)
            self.assertEqual(block(a)["clip_s"], c)
            F.W.set_world_frozen(False)
        with at(40):
            self.assertAlmostEqual(block(a)["clip_s"], c + 10.0, places=3)

    def test_4_pose_switch(self):
        a, b = self.a, self.b
        start_pair(a, b, "tempo-i4")
        provide(0.5)
        with motion(0):
            beat("tempo-i4", a, b)
        with motion(4):
            self.assertEqual(block(a)["clip_s"], 2.0)
        start_pair(a, b, "tempo-i4", pose="run-pair-2")
        with motion(6):
            self.assertEqual((block(a)["clip_s"], block(a)["tempo"]), (0.0, 0.5))
        with motion(8):
            self.assertEqual(block(a)["clip_s"], 1.0)

    def test_5_furniture_scene(self):
        a, b = self.a, self.b
        start_pair(a, b, "tempo-i5")
        provide(0.4)
        with motion(0):
            free = block(a)
            beat("run-r5", a, b)
        profile = F.C.get_character_profile(a)
        profile["interaction"] = dict(profile["interaction"], execution_kind="prop_action",
                                      execution_ref="run-r5")
        with motion(5):
            row = block(a, profile)
            self.assertEqual((row["clip_s"], row["tempo"]), (2.0, 0.4))
            self.assertEqual(block(a)["tempo"], 1.0)
            self.assertEqual(block(a)["clip_s"], free["clip_s"] + 5.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
