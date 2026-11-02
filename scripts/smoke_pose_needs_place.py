#!/usr/bin/env python3
"""A sitting or lying pose is never struck in mid-air: without a free place
it is not written, the furniture that has it is taken instead, and the
start-up repair clears the ones written before.

Usage: ./.venv/bin/python scripts/smoke_pose_needs_place.py

On 2026-11-01 the chat-state extraction gave an NPC the pose "lounging"
("stretches on the sofa"); the sofa is a furniture prop, which a raw pose
never takes, so the pose was stored without a place and the 3D client
played it standing in the air.

Real temporary world (``smoke_prop_action_runs.setup_run``, with the entry
transition the action needs): room "hall"
12 x 10 m, ONE furniture prop "Approach fixture" at (8, 5) whose action
"Rest" holds the pose "sitting"; no room-owned marker. Catalog groups:
standing -> stand, kneeling -> ground (both need no place), sitting and
lounging -> seat, lying -> lie (both need one). Hand-derived:

  [1] set_pose_intent(A, "lounging") -> False, pose "" and no place.
      (Fails on 837538f1: returns None, pose "lounging" without a place.)
  [2] set_pose_key_detail(A, "lounging", ..., unknown="keep") -> "".
  [3] free_seat_groups(A) = {} (the prop's seat is the furniture's);
      seat_missing: lounging True, standing False, kneeling False.
  [4] strikable_pose_keys(A, [standing, sitting, lounging, lying,
      kneeling]) -> [standing, sitting, lounging, kneeling]: seat stays
      (the Rest action holds a seat pose), lie goes (nothing holds one);
      with keep="lying" lying stays as well.
  [5] furniture_for_pose: "sitting" -> [Rest] (exact), "lounging" -> [Rest]
      (same group), "lying" -> [].
  [6] take_furniture_for_pose(A, "lounging") -> status "approaching",
      label "Rest" on "Approach fixture"; A has a live run.
  [7] Start-up repair: B holds "lounging" written raw without a place,
      A is in its furniture run -> clear_placeless_poses() == [B], B's pose
      "", A's run still live.
  [8] A room-owned seat marker "chair" in hall: free_seat_groups(B) =
      {seat}, set_pose_intent(B, "lounging") -> True, place "chair".
"""
import sys
import unittest

import smoke_prop_action_runs as S
from smoke_prop_action_runs import F
# Use the shared fixture's private world for the direct app imports below.
F.paths.init(F.ROOT / "world")
from app.core import places, prop_action_engine as A, prop_action_store as R
from app.core.prop_actions import furniture_for_pose, strikable_pose_keys
from app.models import character as C

KEYS = ["standing", "sitting", "lounging", "lying", "kneeling"]


class PoseNeedsPlace(unittest.TestCase):
    def tearDown(self):
        for run in R.live_runs():
            A.cancel(run["actor"], run["execution_id"])
        F.assert_no_external_work()

    def test_all(self):
        a, target, _ = S.setup_run()

        print("[1] no free place: not written")
        self.assertIs(C.set_pose_intent(a, "lounging"), False)
        profile = C.get_character_profile(a)
        self.assertEqual((profile.get("pose_key") or "", profile.get("place")), ("", None))

        print("[2] key + detail")
        self.assertEqual(C.set_pose_key_detail(a, "lounging", "stretches on the sofa",
                                               unknown="keep"), "")

        print("[3] seat check")
        self.assertEqual(places.free_seat_groups(a), set())
        self.assertEqual([places.seat_missing(a, k) for k in ("lounging", "standing", "kneeling")],
                         [True, False, False])

        print("[4] the menu")
        self.assertEqual(strikable_pose_keys(a, KEYS), ["standing", "sitting", "lounging", "kneeling"])
        self.assertEqual(strikable_pose_keys(a, KEYS, keep="lying"), KEYS)

        print("[5] matching furniture")
        self.assertEqual([o["label"] for o in furniture_for_pose(a, "sitting")], ["Rest"])
        self.assertEqual([(o["label"], o["pose_key"]) for o in furniture_for_pose(a, "lounging")],
                         [("Rest", "sitting")])
        self.assertEqual(furniture_for_pose(a, "lying"), [])

        print("[6] take it")
        taken = A.take_furniture_for_pose(a, "lounging")
        self.assertEqual((taken["status"], taken["label"], taken["prop_label"]),
                         ("approaching", "Rest", "Approach fixture"))
        self.assertTrue(A.has_semantic_action(a))

        print("[7] start-up repair")
        b = F.actor(target["location_id"], at=(3, 5))
        profile = C.get_character_profile(b)
        profile["pose_key"] = "lounging"
        self.assertTrue(C.save_character_profile(b, profile))
        self.assertEqual(C.get_character_pose_key(b), "lounging")
        self.assertEqual(places.clear_placeless_poses(), [b])
        self.assertEqual(C.get_character_pose_key(b), "")
        self.assertTrue(A.has_semantic_action(a))

        print("[8] a room-owned seat")
        loc = F.W.get_location_by_id(target["location_id"])
        hall = next(r for r in loc["rooms"] if r["id"] == "hall")
        hall["layout"]["markers"] = [{"id": "chair", "group": "seat", "at": [2, 8], "rotation": 0}]
        F.W.upsert_location(loc, sync_world=True)
        places.invalidate()
        self.assertEqual(places.free_seat_groups(b), {"seat"})
        self.assertIs(C.set_pose_intent(b, "lounging"), True)
        self.assertEqual((C.get_character_profile(b).get("place") or {}).get("id"), "chair")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *F.REST])
