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
  [2] A package vetoes the carried consent (``prop_action.consent_carries``
      answers False), so the question is put: A asks P for "share-again":
      R2 "awaiting_consent", R1 still "active" with its 4 claims and both
      interactions. The same question again answers R2, ``already`` True.
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

The consent CARRIES (2026-11-08, ``prop_action_engine._consent_carries``:
"the group need not agree again at every change of animation"); no veto
provider registered:

  [8] R1 active as in [1] (P said yes). A asks P for "share-again": the
      answer is "active" at once — not "awaiting_consent" — R1 "completed" /
      "ended", consents {P: yes}, ``consent_carried`` True, both
      interactions carry R2, the 4 claims are R2's, no journey on either
      profile; no "{inviter} suggests …" line and no ``prop_action.invited``.
  [9] P (R2's invitee) asks A, R2's actor, for "share-third": A requested
      R2 himself -> carries as well, "active" at once, R2 "completed".
  [10] A starts "rest" with consent "react" (R4, active in place, reaction
      pending): P never agreed to R4, so A's "ask" for "share-again" is put
      to P -> "awaiting_consent", R4 still "active".
  [11] Another piece: R1' active on "device" again; a second placement
      "device2" of the same prop in the hall. A asks P for "rest" on
      device2: the people are the same, the piece is not -> "awaiting_consent".
"""
import sys
import unittest
from copy import deepcopy
from unittest.mock import patch

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

        print("[2] a vetoed consent asks: an invitation ends nothing yet")
        hooks.register_provider(A.CONSENT_CARRIES, lambda old, new: False, owner="smoke.veto", multiple=True)
        self.addCleanup(hooks.unregister_owned_providers, "smoke.veto")
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

    def test_8_to_11_consent_carries(self):
        name, partner = self.piece()
        lines, invited = [], []
        hooks.register("prop_action.invited", lambda **kw: invited.append(kw), tag="smoke.carry")
        self.addCleanup(hooks._hooks.pop, ("prop_action.invited", "smoke.carry"), None)
        real_narrate = A._narrate

        def narrate(run, key, **kw):
            lines.append(key)
            return real_narrate(run, key, **kw)

        r1 = self.active_pair(name, partner)
        invited.clear()

        print("[8] the same two on the same piece: no second question")
        with patch.object(A, "_narrate", narrate):
            r2 = self.ask(name, "share-again", partner)
        self.assertEqual(r2["status"], "active", r2)
        r2 = r2["execution_id"]
        self.assertEqual((R.get(r1)["status"], R.get(r1)["reason"]), ("completed", "ended"))
        data = R.get(r2)["data"]
        self.assertEqual((data["consents"], data.get("consent_carried")), ({partner: "yes"}, True))
        for who in (name, partner):
            self.assertIsNone(F.C.get_character_profile(who).get("journey"), who)
            self.assertEqual(self.interaction_ref(who), r2, who)
        self.assertEqual([c["execution_id"] for c in R.claims()], [r2] * 4)
        self.assertFalse([k for k in lines if "suggests" in k], lines)
        self.assertEqual(invited, [])

        print("[9] the invitee of the run asks its actor: carries too")
        r3 = self.ask(partner, "share-third", name)
        self.assertEqual(r3["status"], "active", r3)
        self.assertEqual(R.get(r2)["status"], "completed")

        print("[10] a react run was never agreed: the next one asks")
        r4 = self.ask(name, "rest", partner, consent="react")
        self.assertEqual(r4["status"], "active", r4)
        r5 = self.ask(name, "share-again", partner)
        self.assertEqual(r5["status"], "awaiting_consent", r5)
        self.assertEqual(R.get(r4["execution_id"])["status"], "active")
        A.cancel(name, r5["execution_id"])
        A.cancel(name, r4["execution_id"])

        print("[11] another piece asks")
        r6 = self.active_pair(name, partner)
        loc = F.W.get_location(self.target["location_id"])
        hall = next(r for r in loc["rooms"] if r["id"] == "hall")
        device = next(p for p in hall["layout"]["props"] if p["id"] == "device")
        hall["layout"]["props"].append(dict(device, id="device2", at=[4, 2]))
        F.W.upsert_location(loc, sync_world=True)
        F.places.invalidate()
        other = dict(self.target, placement_id="device2")
        r7 = A.request(name, other, "rest", self.revision, [partner])
        self.assertEqual(r7["status"], "awaiting_consent", r7)
        self.assertEqual(R.get(r6)["status"], "active")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *F.REST])
