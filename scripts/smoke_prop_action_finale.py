#!/usr/bin/env python3
"""The FINALE of a running prop action — one participant's closing clip
(`prop_action_engine.begin_finale` / `finale_for`, the `prop_action.active`
beat, the `prop_action.meters` gauges, the catalog field `finale_animation`).

Usage:
    ./.venv/bin/python scripts/smoke_prop_action_finale.py

Runs on the temporary world of `smoke_prop_action_runs.py` (its fixtures and
`tick`): no server, no real world DB, no real clips.

THE FIXTURE
===========
The pair pose `run-pair` (loop `run-pair`, 2 s) gets `finale_animation`
`run-pair-end`: a complete pair, sidecar `duration_s` 1.5. The solo pose
`sitting` gets `run-end`: a solo clip in the neutral set, `duration_s` 0.8.
The SYSTEM clock of the engine (`utc_now`) is pinned to t0 and moved by hand;
the game clock moves only through `tick(seconds)`.

EXPECTATIONS, DERIVED BY HAND
=============================
[1] CATALOG. `finale_animation` is normalised (trimmed, lower case) and kept.
    A solo kind on a pair pose is a catalog problem; so is a pair kind on a
    solo pose.
[2] PAIR FINALE. Both active, `begin_finale(run, partner)` -> ok. The
    partner's block at t0 + 0.4 s is
        {id <12 hex>, kind run-pair-end, role <its clip role>, elapsed_s 0.4, duration_s 1.5}
    and the actor has none (the partner alone closes, the actor plays on).
    A second begin for the partner -> `finale_playing`; an outsider ->
    `not_participant`. `prop_action.finale_started` fired once, with the pose
    `run-pair`.
[3] IT ENDS ON ITS OWN. The block stays shown FINALE_SHOW_S (4 s) past the
    clip: at t0 + 5.4 it is still there (same id, elapsed 5.4) and a new
    begin is refused; at t0 + 5.5 (1.5 + 4.0) it is gone; a tick at t0 + 5.6
    drops it and fires `prop_action.finale_done` for the partner; a begin
    afterwards works again with a NEW id.
[4] THE BEAT. `tick(5)` fires `prop_action.active` for the run with members
    [actor, partner], pose `run-pair` and delta_game_s 5.0 (game seconds
    since the previous tick). A frozen world fires none.
[5] GAUGES. A `prop_action.meters` provider answering 130 / -5 / "x" gives
    the HUD row [{actor, 100.0}, {partner, 0.0}] (clamped, the junk row
    dropped) and `has_finale` true; without a provider the row says [].
[9] LIFECYCLE. A pair run turning active fires `prop_action.started` once
    (members [actor, partner], pose run-pair, ability pair); cancelling it
    fires `prop_action.ended` once with status completed. A solo pose run
    fires both as well (ability pose).
[10] HOLD. Without a provider `hold_meter` -> unsupported; an outsider ->
    not_participant; with a provider answering True -> ok and the provider
    saw (run, partner, True); a row's holdable/held pass through as booleans.
[6] THE RUN ENDS -> the finale ends. Cancelling the run while the partner's
    finale plays drops it at once and fires `finale_done`.
[7] SOLO. The pose action on `sitting` (finale `run-end`): `begin_finale`
    -> ok, block {kind run-end, role None, duration_s 0.8}; the offer of the
    action carries `finale` true, and false once the pose names no finale.
[8] AUTOMATIC. Without the catalog field a provider `pose.finale_animation`
    answering "<animation>-end" makes `run-pair` (animation run-pair) close
    with `run-pair-end` (a pair: accepted) and `sitting` (animation sit, solo)
    with `sit-end` (no such clip: ""). An explicit field wins over the
    provider; a provider answering a solo kind for the pair pose gives "".
    Without a provider: "".
"""
import json
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_prop_action_runs as RUNS                                 # noqa: E402

F, A, R, clips, pose_catalog = RUNS.F, RUNS.A, RUNS.R, RUNS.clips, RUNS.pose_catalog
# Use the shared fixture's private world for the direct app imports below.
F.paths.init(F.ROOT / "world")
from app.core import hooks, prop_actions as P                           # noqa: E402
from app.core.timeutils import utc_now                                  # noqa: E402

T0 = utc_now()
EVENTS = []
for event in ("prop_action.finale_started", "prop_action.finale_done", "prop_action.active",
              "prop_action.started", "prop_action.ended"):
    hooks.register(event, lambda event=event, **kw: EVENTS.append((event, kw)), tag="smoke.finale")


def clock(seconds):
    return patch.object(A, "utc_now", lambda: T0 + timedelta(seconds=seconds))


def set_finale(pose, kind):
    entries = pose_catalog.world_entries("pose")
    if pose not in entries:
        entries[pose] = dict(pose_catalog._read_shared("pose")["entries"][pose])
    if kind:
        entries[pose]["finale_animation"] = kind
    else:
        entries[pose].pop("finale_animation", None)
    pose_catalog.replace_world_entries("pose", entries)
    pose_catalog.reload_catalogs()


def finale_clips():
    directory = F.ROOT / "clips"
    directory.mkdir(exist_ok=True)
    for role in ("a", "b"):
        (directory / f"run-pair-end__{role}.fbx").write_bytes(b"private finale fixture")
    (directory / "run-pair-end.json").write_text(json.dumps(dict(
        kind="run-pair-end", pair=True, duration_s=1.5, loop=False)))
    (directory / "run-end.fbx").write_bytes(b"private finale fixture")
    (directory / "run-end.json").write_text(json.dumps(dict(kind="run-end", duration_s=0.8, loop=False)))
    clips._clear_entries_cache()


def active_pair():
    name, partner, target, _ = RUNS.authored_pair()
    finale_clips()
    set_finale("run-pair", "run-pair-end")
    result = RUNS.request(name, target, partner=partner)
    A.respond(partner, result["execution_id"], True)
    RUNS.tick(30)
    RUNS.tick(2)
    run = R.get(result["execution_id"])
    assert run["status"] == "active", run["status"]
    return name, partner, run


def events(kind):
    return [kw for event, kw in EVENTS if event == kind]


class Finale(RUNS.Runs):
    def setUp(self):
        EVENTS.clear()

    def test_1_catalog_field(self):
        RUNS.authored_pair()
        set_finale("run-pair", "  Run-Pair-End ")
        self.assertEqual(pose_catalog.get_catalog("pose")["run-pair"]["finale_animation"], "run-pair-end")
        finale_clips()
        set_finale("run-pair", "run-end")
        self.assertTrue(any("run-pair" in p and "finale" in p for p in pose_catalog.validate_catalog("pose")))
        set_finale("run-pair", "")
        set_finale("sitting", "run-pair-end")
        self.assertTrue(any("sitting" in p and "finale" in p for p in pose_catalog.validate_catalog("pose")))
        set_finale("sitting", "")

    def test_2_3_pair_finale_plays_alone_and_ends(self):
        name, partner, run = active_pair()
        eid = run["execution_id"]
        role = next(r for r, m in run["data"]["clip_roles"].items() if m == partner)
        with clock(0):
            self.assertEqual(A.begin_finale(eid, partner), dict(ok=True, reason=""))
            self.assertEqual(A.begin_finale(eid, partner)["reason"], "finale_playing")
            self.assertEqual(A.begin_finale(eid, "nobody")["reason"], "not_participant")
        with clock(0.4):
            block = A.finale_for(partner)
            first = block.pop("id")
            self.assertRegex(first, r"^[0-9a-f]{12}$")
            self.assertEqual(block, dict(kind="run-pair-end", role=role, elapsed_s=0.4, duration_s=1.5))
            self.assertIsNone(A.finale_for(name))
        started = events("prop_action.finale_started")
        self.assertEqual(len(started), 1)
        self.assertEqual((started[0]["name"], started[0]["pose_key"]), (partner, "run-pair"))
        with clock(5.4):
            self.assertEqual((A.finale_for(partner)["id"], A.finale_for(partner)["elapsed_s"]), (first, 5.4))
            self.assertEqual(A.begin_finale(eid, partner)["reason"], "finale_playing")
        with clock(5.5):
            self.assertIsNone(A.finale_for(partner))
        with clock(5.6):
            RUNS.tick(1)
            done = events("prop_action.finale_done")
            self.assertEqual([d["name"] for d in done], [partner])
            self.assertTrue(A.begin_finale(eid, partner)["ok"])
            self.assertNotEqual(A.finale_for(partner)["id"], first)
        with clock(12):
            RUNS.tick(1)

    def test_4_beat(self):
        name, partner, run = active_pair()
        EVENTS.clear()
        RUNS.tick(5)
        beats = [b for b in events("prop_action.active") if b["execution_id"] == run["execution_id"]]
        self.assertEqual(len(beats), 1)
        self.assertEqual(beats[0]["members"], [name, partner])
        self.assertEqual(beats[0]["pose_key"], "run-pair")
        self.assertAlmostEqual(beats[0]["delta_game_s"], 5.0, places=6)
        EVENTS.clear()
        F.W.set_world_frozen(True)
        RUNS.tick(5)
        self.assertFalse(events("prop_action.active"))

    def test_5_gauges(self):
        name, partner, run = active_pair()
        row = next(r for r in A.state_for(name)["current"] if r["execution_id"] == run["execution_id"])
        self.assertEqual(row["meters"], [])
        self.assertTrue(row["has_finale"])
        hooks.register_provider("prop_action.meters", lambda execution_id, members, pose_key: [
            dict(name=members[0], value=130, label="x"), dict(name=members[1], value=-5),
            dict(name="junk", value="x")])
        try:
            row = next(r for r in A.state_for(name)["current"] if r["execution_id"] == run["execution_id"])
            self.assertEqual(row["meters"], [dict(name=name, value=100.0, label="x", holdable=False, held=False),
                                             dict(name=partner, value=0.0, label="", holdable=False, held=False)])
        finally:
            hooks._providers.pop("prop_action.meters", None)

    def test_6_run_end_ends_finale(self):
        name, partner, run = active_pair()
        with clock(0):
            self.assertTrue(A.begin_finale(run["execution_id"], partner)["ok"])
            A.cancel(name, run["execution_id"])
            self.assertIsNone(A.finale_for(partner))
        self.assertEqual([d["name"] for d in events("prop_action.finale_done")], [partner])

    def test_7_solo_finale_and_offer_flag(self):
        name, target, _ = RUNS.setup_run()
        finale_clips()
        set_finale("sitting", "run-end")
        offer = next(o for o in P.offers(name) if o["action_id"] == target["action_id"])
        self.assertTrue(offer["finale"])
        result = RUNS.request(name, target)
        RUNS.tick(30)
        RUNS.tick(2)
        self.assertEqual(R.get(result["execution_id"])["status"], "active")
        with clock(0):
            self.assertTrue(A.begin_finale(result["execution_id"], name)["ok"])
        with clock(0.2):
            block = A.finale_for(name)
            block.pop("id")
            self.assertEqual(block, dict(kind="run-end", role=None, elapsed_s=0.2, duration_s=0.8))
        A.cancel(name, result["execution_id"])
        set_finale("sitting", "")
        P._offers_cache.clear()
        offer = next(o for o in P.offers(name) if o["action_id"] == target["action_id"])
        self.assertFalse(offer["finale"])


class Lifecycle(RUNS.Runs):
    def setUp(self):
        EVENTS.clear()

    def test_9_started_and_ended(self):
        name, partner, run = active_pair()
        started = [e for e in events("prop_action.started") if e["execution_id"] == run["execution_id"]]
        self.assertEqual(len(started), 1)
        self.assertEqual((started[0]["members"], started[0]["pose_key"], started[0]["ability"]),
                         ([name, partner], "run-pair", "pair"))
        A.cancel(name, run["execution_id"])
        ended = [e for e in events("prop_action.ended") if e["execution_id"] == run["execution_id"]]
        self.assertEqual(len(ended), 1)
        self.assertEqual(ended[0]["status"], "completed")
        solo, target, _ = RUNS.setup_run()
        result = RUNS.request(solo, target)
        RUNS.tick(30)
        RUNS.tick(2)
        self.assertEqual([e["ability"] for e in events("prop_action.started")
                          if e["execution_id"] == result["execution_id"]], ["pose"])
        A.cancel(solo, result["execution_id"])
        self.assertEqual(len([e for e in events("prop_action.ended")
                              if e["execution_id"] == result["execution_id"]]), 1)

    def test_10_hold(self):
        name, partner, run = active_pair()
        eid = run["execution_id"]
        self.assertEqual(A.hold_meter(eid, partner, True)["reason"], "unsupported")
        self.assertEqual(A.hold_meter(eid, "nobody", True)["reason"], "not_participant")
        seen = []
        hooks.register_provider("prop_action.meter_hold", lambda **kw: seen.append(kw) or True)
        hooks.register_provider("prop_action.meters", lambda execution_id, members, pose_key: [
            dict(name=members[0], value=10, holdable=True, held="yes")])
        try:
            self.assertEqual(A.hold_meter(eid, partner, True), dict(ok=True, reason=""))
            self.assertEqual(seen, [dict(execution_id=eid, name=partner, hold=True)])
            row = next(r for r in A.state_for(name)["current"] if r["execution_id"] == eid)
            self.assertEqual(row["meters"][0]["holdable"], True)
            self.assertEqual(row["meters"][0]["held"], False)
        finally:
            hooks._providers.pop("prop_action.meter_hold", None)
            hooks._providers.pop("prop_action.meters", None)


class Automatic(RUNS.Runs):
    def test_8_provider_derives_the_finale(self):
        RUNS.authored_pair()
        finale_clips()
        set_finale("run-pair", "")
        set_finale("sitting", "")
        catalog = pose_catalog.get_catalog("pose")
        self.assertEqual(catalog["run-pair"]["animation"], "run-pair")
        calls = []

        def provider(pose_key, animation, solo):
            calls.append((pose_key, animation, solo))
            return f"{animation}-end"
        self.assertEqual(A.finale_kind("run-pair"), "")
        hooks.register_provider("pose.finale_animation", provider)
        try:
            self.assertEqual(A.finale_kind("run-pair"), "run-pair-end")
            self.assertIn(("run-pair", "run-pair", False), calls)
            self.assertEqual(A.finale_kind("sitting"), "")
            set_finale("run-pair", "run-end")
            self.assertEqual(A.finale_kind("run-pair"), "")
            set_finale("run-pair", "")
            hooks.register_provider("pose.finale_animation", lambda **kw: "run-end")
            self.assertEqual(A.finale_kind("run-pair"), "")
        finally:
            hooks._providers.pop("pose.finale_animation", None)


if __name__ == "__main__":
    # Only the finale cases — the inherited regression suite runs in its own smoke.
    suite = unittest.TestSuite([Finale(m) for m in sorted(Finale.__dict__) if m.startswith("test_")]
                               + [Automatic("test_8_provider_derives_the_finale"),
                                  Lifecycle("test_9_started_and_ended"), Lifecycle("test_10_hold")])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
