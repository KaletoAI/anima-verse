#!/usr/bin/env python3
"""THE READOUT ESTIMATE without a client (`app/core/pose_scene.py`
`estimate_readouts` / `figure_geometry_of`, the clip sidecar's
`channel_profile` — `animation_clips.set_clip_channel_profile`, route PATCH
`/assets/animation-clips/{library}/{rel}`; plan pair scene Task 6).

Usage:
    ./.venv/bin/python scripts/smoke_scene_readout_estimate.py

Runs on the temporary world of `smoke_prop_action_runs.py` (its fixtures):
no server, no real world DB, no real clips, no model files.

THE FORMULA (pose_scene module docstring)
=========================================
Per channel the clip's profile names (`{share_max, reaches_per_cycle}`), per
receiver R holding that channel (collision record: depth D = |b_pos - a_pos|,
rest radius = its r) and entering figure E with a part whose op the channel
accepts (length L = the sum of its chain's link lengths, surface radius r =
the largest r_surface of its links):
    insertion_of_depth = share_max * L / D
    part_radius_m = r, rest_radius_m = R's r, depth_m = D
    reaches = reaches_per_cycle * cycles when share_max * L >= D, else 0
with cycles = (clip_s now - clip_s at the previous estimate) / clip length
(clip_s from the scene's clip clock; a clock that went back, a pose switch,
counts from 0); whole reaches only, the fraction carried to the next call.

THE FIXTURE
===========
A and B of `authored_pair` play the FREE pair scene I, clip kind
"run-pair" (sidecar duration_s 2). The figure geometry is pinned
(`figure_geometry` patched): A holds channel "inset" (depth 0.15, rest radius
0.017, accepts "appendage_chain"), B carries one "appendage_chain" part
(L 0.16, r 0.02); A has no part, B no channel. The motion clock (REAL seconds
the clip clock runs on) is pinned; the tempo is 1 (no provider).

EXPECTATIONS, DERIVED BY HAND
=============================
[1] GEOMETRY FROM A RECORD (`figure_geometry_of`): channel a_pos (0, 0.9,
    0.05), b_pos (0, 0.9, 0.2), r 0.017 -> depth 0.15, rest radius 0.017.
    Chain Bone1 -> Bone2: Bone1 at (0, 1, 0.1), Bone2 at (0, 1, 0.2); link 1
    Bone1 -> Bone2 = 0.1, link 2 Bone2 -> its b_pos (0, 1, 0.26) = 0.06;
    L = 0.16; r_surface 0.018 / 0.02 -> r = 0.02. A chain whose second link
    has no capsule -> no part (its length is unknown).
[2] SHARE 0.95, reaches_per_cycle 2: 0.95 * 0.16 = 0.152 >= 0.15, so
    insertion_of_depth = 0.152 / 0.15 = 1.01333 and reaches count:
    motion 100 (the clock starts at clip_s 0) -> reaches 0;
    motion 105 -> clip_s 5, cycles 5 / 2 = 2.5 -> 2 * 2.5 = 5;
    motion 106 -> cycles 0.5 -> 1;
    motion 106.75 -> cycles 0.375 -> 0.75 -> 0 (0.75 carried);
    motion 107 -> cycles 0.125 -> 0.25 + 0.75 = 1 -> 1.
    Every row: part_radius_m 0.02, rest_radius_m 0.017, depth_m 0.15,
    source "estimate"; exactly one row (A, inset, B).
[3] SHARE 0.8: 0.8 * 0.16 = 0.128 < 0.15 -> insertion_of_depth
    0.128 / 0.15 = 0.85333, reaches 0 even after 2.5 cycles.
[4] NO DATA = NO ENTRY: profile removed -> []; A without a record
    (figure_geometry None) -> []; B's part of an op the channel does not
    accept -> [].
[5] FALLBACK PER KEY (`readouts`): a client report of (A, inset, B) at t0 ->
    readouts at t0 is that client row only; at t0 + 6 (older than
    READOUT_FRESH_S 5) -> the estimate row of the same key.
[6] THE BEAT CARRIES IT: no report, `emit_active` of I -> the
    `scene.active` listener sees [the estimate row].
[7] THE SIDECAR FIELD: `set_clip_channel_profile("free", "run-pair__a.fbx",
    {"inset": {"share_max": 0.95, "reaches_per_cycle": 2}})` -> both halves'
    listing views show it; share 1.5, share -0.1, reaches -1, reaches 1.5, an
    empty channel name, a missing field -> ClipLibraryError each; None
    removes it (views show None). The route: the same body -> 200 with the
    clips; share 1.5 -> 400.
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
import numpy as np                                                      # noqa: E402
from fastapi import HTTPException                                       # noqa: E402
from app.core import hooks, pose_scene as S                             # noqa: E402
from app.core import animation_clips as AC                              # noqa: E402
from app.core import interaction_engine as IE                            # noqa: E402
from app.core.rig_contract import norm_bone_name                        # noqa: E402
from app.routes import assets                                           # noqa: E402

BEATS = []
hooks.register("scene.active", lambda **kw: BEATS.append(kw), tag="smoke.scene_readout_estimate")
T0 = S.utc_now()
CLOCK = {"motion": 100.0}
CHANNEL = dict(depth_m=0.15, rest_radius_m=0.017, accepts=["appendage_chain"])
PART = dict(op="appendage_chain", length_m=0.16, surface_radius_m=0.02)


def start_pair(a, b, interaction_id):
    started = F.game_time().canonical()
    for name, role in ((a, "a"), (b, "b")):
        profile = F.C.get_character_profile(name)
        profile["interaction"] = dict(id=interaction_id, kind="run-pair", role=role,
                                      started_at_game=started, members={"a": a, "b": b},
                                      pose_key="run-pair")
        assert F.C.save_character_profile(name, profile)


class Estimate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a, cls.b, _target, _pid = RUNS.authored_pair()

    def setUp(self):
        S._readouts.clear()
        S._clocks.clear()
        S._estimates.clear()
        BEATS.clear()
        self.scene = "est-" + self._testMethodName
        start_pair(self.a, self.b, self.scene)
        self.geo = {self.a: dict(channels={"inset": dict(CHANNEL)}, parts=[]),
                    self.b: dict(channels={}, parts=[dict(PART)])}
        self.patches = [patch.object(S, "figure_geometry", lambda name: self.geo.get(name)),
                        patch.object(S, "motion_time", lambda: CLOCK["motion"])]
        for p in self.patches:
            p.start()
        self.profile({"inset": {"share_max": 0.95, "reaches_per_cycle": 2}})

    def tearDown(self):
        for p in self.patches:
            p.stop()
        IE.end_interaction(self.a, reason="ended")
        self.profile(None)

    def profile(self, value):
        return AC.set_clip_channel_profile("free", "run-pair__a.fbx", value)

    def estimate(self, motion):
        CLOCK["motion"] = motion
        return S.estimate_readouts(self.scene)

    def assertRow(self, row, insertion, reaches):
        self.assertEqual({k: row[k] for k in ("receiver", "channel", "entering", "source")},
                         dict(receiver=self.a, channel="inset", entering=self.b, source="estimate"))
        self.assertAlmostEqual(row["insertion_of_depth"], insertion, places=4)
        self.assertEqual((row["part_radius_m"], row["rest_radius_m"], row["depth_m"]), (0.02, 0.017, 0.15))
        self.assertEqual(row["reaches"], reaches)

    def test_1_geometry_of_a_record(self):
        k1, k2 = norm_bone_name("Bone1"), norm_bone_name("Bone2")
        record = {"channels": [{"id": "inset", "a_pos": [0, 0.9, 0.05], "b_pos": [0, 0.9, 0.2], "r": 0.017,
                                "accepts": ["appendage_chain"]}],
                  "capsules": [{"id": f"g:{k1}", "a": "Bone1", "b": "Bone2", "r": 0.015, "r_surface": 0.018},
                               {"id": f"g:{k2}", "a": "Bone2", "b": "Bone2", "b_pos": [0, 1, 0.26], "r": 0.016,
                                "r_surface": 0.02}]}
        groups = [{"group": "g", "op": "appendage_chain", "chains": [["Bone1", "Bone2"]]}]
        index_of = {k1: 0, k2: 1}
        positions = np.array([[0, 1, 0.1], [0, 1, 0.2]], np.float64)
        geo = S.figure_geometry_of(record, groups, index_of, positions)
        self.assertEqual(list(geo["channels"]), ["inset"])
        ch = geo["channels"]["inset"]
        self.assertAlmostEqual(ch["depth_m"], 0.15, places=9)
        self.assertEqual((ch["rest_radius_m"], ch["accepts"]), (0.017, ["appendage_chain"]))
        self.assertEqual(len(geo["parts"]), 1)
        part = geo["parts"][0]
        self.assertEqual((part["op"], part["surface_radius_m"]), ("appendage_chain", 0.02))
        self.assertAlmostEqual(part["length_m"], 0.16, places=9)
        record["capsules"].pop()
        self.assertEqual(S.figure_geometry_of(record, groups, index_of, positions)["parts"], [])

    def test_2_share_reaching(self):
        insertion = 0.95 * 0.16 / 0.15
        for motion, reaches in ((100, 0), (105, 5), (106, 1), (106.75, 0), (107, 1)):
            rows = self.estimate(motion)
            self.assertEqual(len(rows), 1, motion)
            self.assertRow(rows[0], insertion, reaches)

    def test_3_share_short(self):
        self.profile({"inset": {"share_max": 0.8, "reaches_per_cycle": 2}})
        self.estimate(100)
        rows = self.estimate(105)
        self.assertEqual(len(rows), 1)
        self.assertRow(rows[0], 0.8 * 0.16 / 0.15, 0)

    def test_4_no_data(self):
        self.profile(None)
        self.assertEqual(self.estimate(100), [])
        self.profile({"inset": {"share_max": 0.95, "reaches_per_cycle": 2}})
        self.geo[self.a] = None
        self.assertEqual(self.estimate(101), [])
        self.geo[self.a] = dict(channels={"inset": dict(CHANNEL)}, parts=[])
        self.geo[self.b] = dict(channels={}, parts=[dict(PART, op="other_op")])
        self.assertEqual(self.estimate(102), [])

    def test_5_fallback_per_key(self):
        client = dict(receiver=self.a, channel="inset", entering=self.b, insertion_of_depth=0.5,
                      part_radius_m=0.02, rest_radius_m=0.03, depth_m=0.2, reaches=1)
        with patch.object(S, "utc_now", lambda: T0):
            self.assertEqual(S.report_readouts(self.scene, [client], admin=True), 1)
            self.assertEqual(S.readouts(self.scene), [dict(client, source="client")])
        with patch.object(S, "utc_now", lambda: T0 + timedelta(seconds=6)):
            rows = S.readouts(self.scene)
        self.assertEqual(len(rows), 1)
        self.assertRow(rows[0], 0.95 * 0.16 / 0.15, 0)

    def test_6_beat(self):
        S.emit_active(scene_id=self.scene, kind="interaction", members=[self.a, self.b],
                      roles={"a": self.a, "b": self.b}, pose_key="run-pair", delta_game_s=1.0)
        self.assertEqual(len(BEATS), 1)
        self.assertEqual(len(BEATS[0]["readouts"]), 1)
        self.assertRow(BEATS[0]["readouts"][0], 0.95 * 0.16 / 0.15, 0)

    def test_7_sidecar(self):
        value = {"inset": {"share_max": 0.95, "reaches_per_cycle": 2}}
        views = self.profile(value)
        self.assertEqual(sorted(v["role"] for v in views), ["a", "b"])
        for view in views:
            self.assertEqual(view["channel_profile"], value)
        for bad in ({"inset": {"share_max": 1.5, "reaches_per_cycle": 2}},
                    {"inset": {"share_max": -0.1, "reaches_per_cycle": 2}},
                    {"inset": {"share_max": 0.5, "reaches_per_cycle": -1}},
                    {"inset": {"share_max": 0.5, "reaches_per_cycle": 1.5}},
                    {"": {"share_max": 0.5, "reaches_per_cycle": 1}},
                    {"inset": {"share_max": 0.5}}):
            with self.assertRaises(AC.ClipLibraryError, msg=str(bad)):
                self.profile(bad)
        for view in self.profile(None):
            self.assertIsNone(view["channel_profile"])
        answer = assets._patch_animation_clip_sync("free", "run-pair__a.fbx", {"channel_profile": value})
        self.assertEqual(answer["clips"][0]["channel_profile"], value)
        with self.assertRaises(HTTPException) as caught:
            assets._patch_animation_clip_sync("free", "run-pair__a.fbx",
                                              {"channel_profile": {"inset": {"share_max": 1.5, "reaches_per_cycle": 2}}})
        self.assertEqual(caught.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
