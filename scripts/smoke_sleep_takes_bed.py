#!/usr/bin/env python3
"""Falling asleep in a room without a room-owned lying place takes the bed.

Usage: ./.venv/bin/python scripts/smoke_sleep_takes_bed.py

Runs on the private furniture fixture of smoke_prop_action_runs (temporary
storage + instance, no server, no real world). The fixture room has no
room-owned marker; its one piece carries the action under test. Before
2026-11-03 ``set_is_sleeping`` only asked ``places.assign``, which never
hands out furniture: every NPC put to sleep by a rule, the schedule or the
Sleep tool lay down on the floor next to its bed. Expected, by hand:

[1] BED. The piece's action is a sleep action (ability "sleep", pose
    "sleeping", marker group lie — as in test_sleep_owns_exact_bed of the
    runs smoke). ``set_is_sleeping(name, True)``: the character is NOT asleep
    yet; exactly one live run of that action, ``going_to_bed`` True. Asked
    again (the next rule tick): still that one run. After the approach
    (30 + 2 game seconds, as in the runs smoke) it sleeps, the run is
    "sleeping", its place is the bed's ("device/body"), ``going_to_bed``
    False.
[2] MENU. ``furniture_for_pose(name, "sleeping")`` names the sleep action
    first; for "lying" it is not offered (it puts to sleep, not to lie).
[3] NO BED. The piece's action is a plain pose action: ``set_is_sleeping``
    puts the character to sleep at once, no run is started.
"""
import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_prop_action_runs as RUNS                                 # noqa: E402

F, A, R = RUNS.F, RUNS.A, RUNS.R
from app.core import paths                                            # noqa: E402
paths.init(F.ROOT / "world")    # the fixture's private world, named here once more
from app.core import prop_actions                                     # noqa: E402


def bed():
    name, target, pid = RUNS.setup_run("sleep")
    doc = F.props.read_sidecar(pid)
    doc["actions"][0]["pose_key"] = "sleeping"
    doc["model_variants"][0]["markers"][0]["group"] = "lie"
    F.props._write_sidecar(pid, doc)
    target["definition_revision"] = F.props.get_prop(pid)["revision"]
    RUNS.measured_entry("sleeping")
    return name, target


def sleep_runs(name):
    return [r for r in R.live_runs() if r["actor"] == name and r["definition"]["ability"] == "sleep"]


class SleepTakesBed(unittest.TestCase):
    def tearDown(self):
        for run in R.live_runs():
            A.cancel(run["actor"], run["execution_id"])
        F.assert_no_external_work()

    def test_1_falling_asleep_walks_to_the_bed(self):
        name, target = bed()
        print("[1] the sleeper goes to bed first")
        F.C.set_is_sleeping(name, True)
        self.assertFalse(F.C.is_character_sleeping(name))
        runs = sleep_runs(name)
        self.assertEqual(len(runs), 1, runs)
        self.assertTrue(A.going_to_bed(name))
        F.C.set_is_sleeping(name, True)
        self.assertEqual([r["execution_id"] for r in sleep_runs(name)], [runs[0]["execution_id"]])
        RUNS.tick(30)
        RUNS.tick(2)
        self.assertTrue(F.C.is_character_sleeping(name))
        self.assertEqual(R.get(runs[0]["execution_id"])["status"], "sleeping")
        self.assertEqual(F.C.get_character_profile(name)["place"]["id"], "device/body")
        self.assertFalse(A.going_to_bed(name))
        F.C.set_is_sleeping(name, False)

    def test_2_the_sleep_menu(self):
        name, target = bed()
        print("[2] SetPose 'sleeping' finds the bed, 'lying' does not")
        sleeping = prop_actions.furniture_for_pose(name, "sleeping")
        self.assertEqual([o["ability"] for o in sleeping[:1]], ["sleep"], sleeping)
        self.assertFalse([o for o in prop_actions.furniture_for_pose(name, "lying") if o["ability"] == "sleep"])

    def test_3_no_bed_sleeps_in_place(self):
        name, target, pid = RUNS.setup_run("pose")
        print("[3] without a bed it sleeps where it is")
        F.C.set_is_sleeping(name, True)
        self.assertTrue(F.C.is_character_sleeping(name))
        self.assertFalse(sleep_runs(name))
        self.assertFalse(R.live_runs())
        F.C.set_is_sleeping(name, False)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *F.REST])
