#!/usr/bin/env python3
"""The running SCENE of a FREE pair (`app/core/pose_scene.py`): the finale
with a tempo, "end after the finale", the beat, meters, hold and alt halves —
the levers a furniture run had alone before.

Usage:
    ./.venv/bin/python scripts/smoke_pose_scene_finale.py

Runs on the temporary world of `smoke_prop_action_runs.py` (its fixtures):
no server, no real world DB, no real clips.

THE FIXTURE
===========
Two characters A and B of `authored_pair` and its pair pose `run-pair`
(clip kind run-pair, roles a/b). A FREE pair is the interaction blob both
profiles carry (no `execution_kind`): id I, kind run-pair, A on role a, B
on role b, pose run-pair. The pose gets `finale_animation` `fin-pair`: a
complete pair (`fin-pair__a` / `fin-pair__b`), sidecar `duration_s 1.2,
loop: false, loop_count 3`. The SYSTEM clock of `pose_scene` (`utc_now`)
is pinned to t0 and moved by hand; the game clock moves by `set_game_time`.

EXPECTATIONS, DERIVED BY HAND
=============================
[1] FINALE WITH A TEMPO. `begin_finale(I, A, tempo=0.5)` -> ok. The count
    belongs to the finale whether the clip loops or not, so it plays 3
    cycles: real length = 1.2 s * 3 / 0.5 = 7.2 s. At t0 + 0.4 A's block is
        {kind fin-pair, role a, alt "", elapsed_s 0.4, duration_s 7.2,
         loop_count 3, tempo 0.5}
    and B has none. A second begin for A -> `finale_playing`; a scene id
    that is not A's -> `no_scene`. B with tempo 5 is clamped to 1:
    duration_s 1.2 * 3 / 1 = 3.6, tempo 1.0; B with tempo 0.05 would be 0.2
    (clamp below) — checked on a third begin after B's ended: 1.2*3/0.2 = 18.0.
    `scene.finale_started` fired for A with scene_id I, kind fin-pair, pose run-pair.
[2] END AFTER THE FINALE. At t0 A's finale begins (7.2 s); at t0 + 1
    `end_after_finale(I, A, 3)` -> True: the end is due 7.2 + 3 = 10.2 s after
    the finale's start. `advance` at t0 + 10.1 leaves the pair running; at
    t0 + 10.2 it ends it (no interaction on A or B), and `scene.finale_done`
    fires for A (the scene end drops the finale).
    A NEW pair: `end_after_finale(I2, A, 3)` at t1 (no finale: due t1 + 3),
    then I2 ends by hand and a new I3 starts for the same two; `advance` at
    t1 + 5 leaves I3 running — the end was for I2 alone.
[3] THE BEAT. The first `advance` of the process only notes the boot. A pair
    started at game time g (after that) beats at g + 7 with ONE `scene.active`
        {scene_id I4, kind interaction, members [A, B], roles {a: A, b: B},
         pose_key run-pair, lead_role a (no stored lead role: role a),
         delta_game_s 7.0, readouts []}
    and at g + 12 with delta 5.0 (game time since the previous beat). A frozen
    world at g + 17 beats not at all.
[4] METERS / HOLD / ALT. A `scene.meters` provider answering 130 / -5 / "x"
    gives [{A, 100.0}, {B, 0.0}] (clamped, junk dropped, rate 0 with a
    stopped game clock). Without a `scene.meter_hold` provider `hold` ->
    `unsupported`; with one answering True -> ok and the provider saw
    (I4, A, True); a foreign scene id -> `no_scene`. `set_alt(I4, A, "nope")`
    -> `unknown_alt` (the clip has no alt halves); a foreign id -> `no_scene`.
[5] SCENE OF A NAME. `scene_of(A)` = {scene_id I4, kind interaction,
    members [A, B], roles {a: A, b: B}, pose_key run-pair}; None without one.
"""
import json
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_prop_action_runs as RUNS                                 # noqa: E402

F, clips, pose_catalog = RUNS.F, RUNS.clips, RUNS.pose_catalog
F.paths.init(F.ROOT / "world")
from app.core import hooks, pose_scene as S                              # noqa: E402
from app.core import interaction_engine as IE                            # noqa: E402
from app.core.game_time import GameDuration                             # noqa: E402
from app.core.timeutils import utc_now                                  # noqa: E402

T0 = utc_now()
EVENTS = []
for event in ("scene.finale_started", "scene.finale_done", "scene.active"):
    hooks.register(event, lambda event=event, **kw: EVENTS.append((event, kw)), tag="smoke.pose_scene")


def clock(seconds):
    return patch.object(S, "utc_now", lambda: T0 + timedelta(seconds=seconds))


def events(kind):
    return [kw for event, kw in EVENTS if event == kind]


def fixture():
    name, partner, _target, _pid = RUNS.authored_pair()
    directory = F.ROOT / "clips"
    for role in ("a", "b"):
        (directory / f"fin-pair__{role}.fbx").write_bytes(b"private finale fixture")
    (directory / "fin-pair.json").write_text(json.dumps(dict(
        kind="fin-pair", pair=True, duration_s=1.2, loop=False, loop_count=3)))
    clips._clear_entries_cache()
    entries = pose_catalog.world_entries("pose")
    entries["run-pair"]["finale_animation"] = "fin-pair"
    pose_catalog.replace_world_entries("pose", entries)
    pose_catalog.reload_catalogs()
    return name, partner


def start_pair(a, b, interaction_id):
    """The blob a free pair leaves on both profiles (interaction_engine)."""
    started = F.game_time().canonical()
    for name, role in ((a, "a"), (b, "b")):
        profile = F.C.get_character_profile(name)
        profile["interaction"] = dict(id=interaction_id, kind="run-pair", role=role,
                                      started_at_game=started, members={"a": a, "b": b},
                                      pose_key="run-pair")
        assert F.C.save_character_profile(name, profile)


def advance():
    return S.advance(F.game_time())


class FreePairScene(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a, cls.b = fixture()
        advance()                                   # the boot beat: notes the process start

    def setUp(self):
        EVENTS.clear()
        S._finales.clear()
        F.W.set_world_frozen(False)

    def tearDown(self):
        F.W.set_world_frozen(False)
        IE.end_interaction(self.a, reason="ended")

    def test_1_finale_with_tempo(self):
        a, b = self.a, self.b
        start_pair(a, b, "scene-i1")
        with clock(0):
            self.assertEqual(S.begin_finale("scene-i1", a, tempo=0.5), dict(ok=True, reason=""))
            self.assertEqual(S.begin_finale("scene-i1", a)["reason"], "finale_playing")
            self.assertEqual(S.begin_finale("other", a)["reason"], "no_scene")
        with clock(0.4):
            block = S.finale_for(a)
            self.assertRegex(block.pop("id"), r"^[0-9a-f]{12}$")
            self.assertEqual(block, dict(kind="fin-pair", role="a", alt="", elapsed_s=0.4, duration_s=7.2,
                                         loop_count=3, tempo=0.5))
            self.assertIsNone(S.finale_for(b))
            self.assertTrue(S.begin_finale("scene-i1", b, tempo=5)["ok"])
            self.assertEqual((S.finale_for(b)["duration_s"], S.finale_for(b)["tempo"]), (3.6, 1.0))
        with clock(0.4 + 3.6 + S.FINALE_SHOW_S):
            self.assertTrue(S.begin_finale("scene-i1", b, tempo=0.05)["ok"])
            self.assertEqual((S.finale_for(b)["duration_s"], S.finale_for(b)["tempo"]), (18.0, 0.2))
        started = events("scene.finale_started")
        self.assertEqual((started[0]["scene_id"], started[0]["name"], started[0]["kind"], started[0]["pose_key"]),
                         ("scene-i1", a, "fin-pair", "run-pair"))

    def test_2_end_after_finale(self):
        a, b = self.a, self.b
        start_pair(a, b, "scene-i1")
        with clock(0):
            self.assertTrue(S.begin_finale("scene-i1", a, tempo=0.5)["ok"])
        with clock(1):
            self.assertTrue(S.end_after_finale("scene-i1", a, 3))
            self.assertFalse(S.end_after_finale("other", a, 3))
        with clock(10.1):
            advance()
            self.assertEqual((IE.get_interaction(a) or {}).get("id"), "scene-i1")
        with clock(10.2):
            advance()
            self.assertIsNone(IE.get_interaction(a))
            self.assertIsNone(IE.get_interaction(b))
        self.assertIn(a, [d["name"] for d in events("scene.finale_done")])
        # A scene that ended meanwhile is left alone; the next one runs on.
        start_pair(a, b, "scene-i2")
        with clock(100):
            self.assertTrue(S.end_after_finale("scene-i2", a, 3))
        IE.end_interaction(a, reason="ended")
        start_pair(a, b, "scene-i3")
        with clock(105):
            advance()
            self.assertEqual((IE.get_interaction(a) or {}).get("id"), "scene-i3")

    def test_3_beat(self):
        a, b = self.a, self.b
        start_pair(a, b, "scene-i4")
        EVENTS.clear()
        F.set_game_time(F.game_time() + GameDuration.of(seconds=7))
        advance()
        beats = [x for x in events("scene.active") if x["scene_id"] == "scene-i4"]
        self.assertEqual(len(beats), 1)
        beat = dict(beats[0])
        self.assertAlmostEqual(beat.pop("delta_game_s"), 7.0, places=6)
        self.assertEqual(beat, dict(scene_id="scene-i4", kind="interaction", members=[a, b],
                                    roles={"a": a, "b": b}, pose_key="run-pair", lead_role="a",
                                    readouts=[]))
        EVENTS.clear()
        F.set_game_time(F.game_time() + GameDuration.of(seconds=5))
        advance()
        beats = [x for x in events("scene.active") if x["scene_id"] == "scene-i4"]
        self.assertEqual(len(beats), 1)
        self.assertAlmostEqual(beats[0]["delta_game_s"], 5.0, places=6)
        EVENTS.clear()
        F.W.set_world_frozen(True)
        F.set_game_time(F.game_time() + GameDuration.of(seconds=5))
        advance()
        self.assertFalse(events("scene.active"))

    def test_4_meters_hold_alt(self):
        a, b = self.a, self.b
        start_pair(a, b, "scene-i4")
        hooks.register_provider("scene.meters", lambda scene_id, members, pose_key: [
            dict(name=members[0], value=130, label="x"), dict(name=members[1], value=-5),
            dict(name="junk", value="x")])
        try:
            self.assertEqual(S.meters("scene-i4", a), [
                dict(name=a, value=100.0, rate=0.0, label="x", holdable=False, held=False),
                dict(name=b, value=0.0, rate=0.0, label="", holdable=False, held=False)])
        finally:
            hooks._providers.pop("scene.meters", None)
        self.assertEqual(S.meters("scene-i4", a), [])
        self.assertEqual(S.hold("scene-i4", a, True)["reason"], "unsupported")
        seen = []
        hooks.register_provider("scene.meter_hold", lambda **kw: seen.append(kw) or True)
        try:
            self.assertEqual(S.hold("scene-i4", a, True), dict(ok=True, reason=""))
            self.assertEqual(seen, [dict(scene_id="scene-i4", name=a, hold=True)])
            self.assertEqual(S.hold("other", a, True)["reason"], "no_scene")
        finally:
            hooks._providers.pop("scene.meter_hold", None)
        self.assertEqual(S.set_alt("scene-i4", a, "nope")["reason"], "unknown_alt")
        self.assertEqual(S.set_alt("other", a, "")["reason"], "no_scene")

    def test_5_scene_of(self):
        a, b = self.a, self.b
        start_pair(a, b, "scene-i4")
        self.assertEqual(S.scene_of(a), dict(scene_id="scene-i4", kind="interaction", members=[a, b],
                                             roles={"a": a, "b": b}, pose_key="run-pair"))
        IE.end_interaction(a, reason="ended")
        self.assertIsNone(S.scene_of(a))


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(FreePairScene)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
