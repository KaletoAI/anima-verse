#!/usr/bin/env python3
"""Switching furniture actions: a running action never locks the piece for
the two people using it, an invitation ends nothing before its "yes" and
survives a step in between, a partner sitting alone can be asked, and a
switch on the piece both already use begins where they are.

Usage: ./.venv/bin/python scripts/smoke_prop_action_switch.py

On 2026-11-02 an NPC partner's own request for another pair action ended
the running one at once; the avatar's next position report then cancelled
the invitation, the NPC took an armchair for its "sitting" pose and from
there it counted as busy for every pair action; and a second action on the
sofa the two were using was offered as "no_free_slot".

Real temporary world — the fixtures of ``smoke_prop_action_runs.py``
(``authored_pair``: A at (1,5), P at (2,5), the pair action "rest" on a
two-place seat; 30 game seconds bring both to their access points, two
more through the entry). Added on the same piece: the pair actions
"share-again" / "share-third" (copies of "rest") and the solo action
"sit-alone" (ability pose, pose "sitting"). Hand-derived from
``prop_action_engine``:

  [1] A and P active in "rest" (R1, 4 claims). check(A, share-again, P) is
      enabled — the seats are their own (fails on a1c5af11: no_free_slot).
  [2] A asks P for "share-again": R2 "awaiting_consent", R1 still "active"
      with its 4 claims and both interactions. The same question again
      answers R2, ``already`` True.
  [3] P says no: R2 "cancelled" / "consent_declined", R1 untouched.
  [4] A asks again, P says yes: R1 "completed" / "ended"; the new run is
      "active" at once — no journey on either profile, both interactions
      carry its execution id, 4 claims, all of them its own.
  [5] A switches to "share-third" with consent "react": the answer is
      "active" at once, the run before "completed"; the reaction is still
      asked ("pending"), and a resisting partner ends the switched run:
      "cancelled" / "partner_resisted".
  [6] Nobody in a run: A asks P for "rest"; P steps aside
      (set_character_pos -> interrupt "position") -> still
      "awaiting_consent" (fails on a1c5af11: cancelled "position").
  [7] P sits alone ("sit-alone" active, 2 claims). check(A, rest, P) is
      enabled (fails on a1c5af11: participant_claimed); A's react request
      ends P's run ("completed") and starts the pair "approaching" — P is
      the only one already on the piece, so the two walk as usual.
"""
import sys
import unittest
from copy import deepcopy

import smoke_prop_action_runs as S
from smoke_prop_action_runs import A, F, R, tick
from app.core import hooks

TARGET_KEYS = ("location_id", "room_id", "placement_id", "variant_uid")


class Switch(unittest.TestCase):
    def setUp(self):
        self.asked = []
        hooks.register_provider("pair_reaction", lambda **kw: self.asked.append(kw), owner="smoke")
        self.addCleanup(hooks._providers.pop, "pair_reaction", None)

    def tearDown(self):
        for run in R.live_runs():
            A.cancel(run["actor"], run["execution_id"])
        F.assert_no_external_work()

    def piece(self):
        name, partner, target, pid = S.authored_pair()
        doc = F.props.read_sidecar(pid)
        for action_id in ("share-again", "share-third"):
            action = deepcopy(doc["actions"][0])
            action.update(id=action_id, name=action_id)
            doc["actions"].append(action)
        alone = deepcopy(doc["actions"][0])
        alone.update(id="sit-alone", name="sit-alone", ability="pose", participants=1, pose_key="sitting")
        doc["actions"].append(alone)
        F.props._write_sidecar(pid, doc)
        self.revision = F.props.get_prop(pid)["revision"]
        self.target = {k: target[k] for k in TARGET_KEYS}
        return name, partner

    def ask(self, name, action_id, partner="", **kw):
        return A.request(name, self.target, action_id, self.revision, [partner] if partner else [], **kw)

    def check(self, name, action_id, partner=""):
        return A.check(name, self.target, action_id, self.revision, [partner] if partner else [])

    def active_pair(self, name, partner):
        eid = self.ask(name, "rest", partner)["execution_id"]
        self.assertEqual(A.respond(partner, eid, True)["status"], "approaching")
        S.tick(30)
        tick(2)
        tick(2)
        self.assertEqual(R.get(eid)["status"], "active", R.get(eid))
        return eid

    def interaction_ref(self, who):
        return (F.C.get_character_profile(who).get("interaction") or {}).get("execution_ref")

    def test_1_to_5_switch_on_the_piece(self):
        name, partner = self.piece()
        r1 = self.active_pair(name, partner)
        self.assertEqual(len(R.claims(r1)), 4)

        print("[1] the piece is not locked for the two")
        self.assertEqual(self.check(name, "share-again", partner), dict(enabled=True, reason=""))

        print("[2] an invitation ends nothing yet")
        r2 = self.ask(name, "share-again", partner)
        self.assertEqual(r2["status"], "awaiting_consent", r2)
        self.assertEqual((R.get(r1)["status"], len(R.claims(r1))), ("active", 4))
        self.assertEqual((self.interaction_ref(name), self.interaction_ref(partner)), (r1, r1))
        again = self.ask(name, "share-again", partner)
        self.assertEqual((again["execution_id"], again.get("already")), (r2["execution_id"], True))

        print("[3] a no keeps what runs")
        A.respond(partner, r2["execution_id"], False)
        self.assertEqual((R.get(r2["execution_id"])["status"], R.get(r2["execution_id"])["reason"]),
                         ("cancelled", "consent_declined"))
        self.assertEqual((R.get(r1)["status"], len(R.claims(r1))), ("active", 4))

        print("[4] a yes switches in place")
        r3 = self.ask(name, "share-again", partner)["execution_id"]
        result = A.respond(partner, r3, True)
        self.assertEqual(result["status"], "active", result)
        self.assertEqual((R.get(r1)["status"], R.get(r1)["reason"]), ("completed", "ended"))
        for who in (name, partner):
            self.assertIsNone(F.C.get_character_profile(who).get("journey"), who)
            self.assertEqual(self.interaction_ref(who), r3, who)
        self.assertEqual([c["execution_id"] for c in R.claims()], [r3] * 4)

        print("[5] just do it switches in place too")
        r4 = self.ask(name, "share-third", partner, consent="react")
        self.assertEqual(r4["status"], "active", r4)
        self.assertEqual(R.get(r3)["status"], "completed")
        self.assertEqual(R.get(r4["execution_id"])["data"]["reaction"]["state"], "pending")
        self.assertEqual(A.react(partner, r4["execution_id"], False)["reason"], "partner_resisted")

    def test_6_invitation_survives_a_step(self):
        name, partner = self.piece()
        eid = self.ask(name, "rest", partner)["execution_id"]
        print("[6] a step aside keeps the question")
        F.C.set_character_pos(partner, 2.5, 5.5)
        self.assertEqual(R.get(eid)["status"], "awaiting_consent", R.get(eid))

    def test_7_partner_sitting_alone_can_be_asked(self):
        name, partner = self.piece()
        # The fixture's measured entry, for the solo pose as well.
        S.clips._write_world_transitions([{"from": "walking", "to": pose, "kind": "run-enter", "accel": 0}
                                          for pose in ("run-pair", "sitting")])
        solo = self.ask(partner, "sit-alone")
        self.assertEqual(solo["status"], "approaching", solo)
        solo = solo["execution_id"]
        S.tick(30)
        tick(2)
        tick(2)
        self.assertEqual((R.get(solo)["status"], len(R.claims(solo))), ("active", 2))
        print("[7] the partner sitting alone is not busy")
        self.assertEqual(self.check(name, "rest", partner), dict(enabled=True, reason=""))
        result = self.ask(name, "rest", partner, consent="react")
        self.assertEqual(result["status"], "approaching", result)
        self.assertEqual(R.get(solo)["status"], "completed")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *F.REST])
