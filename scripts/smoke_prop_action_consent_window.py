#!/usr/bin/env python3
"""The invitation window of a furniture action: how long it waits, what the
room hears when it runs out, and what a late "yes" still tells the inviter.

Usage: ./.venv/bin/python scripts/smoke_prop_action_consent_window.py

Real temporary world — the fixtures of ``smoke_prop_action_runs.py``
(``authored_pair``: A asks B) and ``smoke_prop_action_group.py``
(``authored_trio``: A asks B and C). The fixture moves the MOTION clock
(real seconds the world ran unfrozen) by the same N seconds as the game
clock on ``set_game_time``/``tick`` unless the world is frozen; the factor-2
case moves the two clocks apart by hand. Lines and notices are captured at
``_narrate`` / ``_tell_inviter``. Hand-derived from ``prop_action_engine``:

  window = CONSENT_WINDOW_S 300 + CONSENT_WINDOW_PER_EXTRA_INVITEE_S 120 per
  invitee beyond the first, in motion-clock seconds:
  pair (1 invitee) 300 + 120*0 = 300 s, trio (2 invitees) 300 + 120*1 = 420 s.

  [1] Pair: 299 s pass -> still "awaiting_consent", consent_wait_s 299; one
      more -> "cancelled"/"consent_expired". One line, the same as notice:
      "The invitation from {inviter} has expired — {silent} did not answer
      in time." inviter A, silent B (a pair has no parenthesis).
  [2] Trio: B agrees after 100 s; 419 s in total -> still waiting; 420 ->
      expired, line "... did not answer in time ({agreed} had agreed)."
      with silent C, agreed B (the old 300-s window would have closed at 300).
  [3] Game factor 2: the game clock runs 598 s while the motion clock runs
      299 s -> still waiting (the old GAME count, 598 >= 300, had expired it);
      +1 motion s (+2 game s) = 300 -> expired.
  [4] Frozen: 200 s, then the world freezes and 500 game-clock steps pass
      without motion; thawed, 99 s more (299 in total) -> waiting; +1 ->
      expired. A frozen world pauses the window, as the game count did.
  [5] Late "yes": the pair expired by the tick; 60 s later B says yes ->
      result "cancelled"/"consent_expired", ONE line and ONE notice
      "{name} would have agreed — the invitation had already expired."
      name B; B saying yes again -> nothing more.
  [6] Late "no": nothing is told.
  [7] Late "yes" 601 s after the expiry (LATE_ANSWER_WINDOW_S 600) ->
      nothing is told.
  [8] Expired before any tick noticed: 300 s pass without a tick, B says
      yes -> "cancelled"/"consent_expired", no claims; the expiry line
      (silent B), then the late line (name B) — lines and notices alike.
"""
import sys
import unittest
from unittest.mock import patch

import smoke_prop_action_group as G
import smoke_prop_action_runs as S
from smoke_prop_action_runs import A, F, R, tick
from app.core.game_time import GameDuration                             # noqa: E402

EXPIRED = "The invitation from {inviter} has expired — {silent} did not answer in time."
AGREED = "The invitation from {inviter} has expired — {silent} did not answer in time ({agreed} had agreed)."
LATE = "{name} would have agreed — the invitation had already expired."


def motion_only_step(motion_s, game_s):
    """``motion_s`` real seconds pass while the game clock runs ``game_s``
    (a game-speed factor of game_s / motion_s), then one engine tick."""
    F.MOTION[0] += motion_s
    F.timeutils.set_game_time(F.game_time() + GameDuration.of(seconds=game_s))
    A.advance(F.game_time())


class ConsentWindow(unittest.TestCase):
    def setUp(self):
        self.said, self.told = [], []
        narrate = patch.object(A, "_narrate", side_effect=lambda run, key, **fmt: self.said.append((key, fmt)))
        tell = patch.object(A, "_tell_inviter", side_effect=lambda run, key, **fmt: self.told.append((key, fmt)))
        narrate.start()
        tell.start()
        self.addCleanup(narrate.stop)
        self.addCleanup(tell.stop)

    def tearDown(self):
        F.W.set_world_frozen(False)
        for run in R.live_runs():
            A.cancel(run["actor"], run["execution_id"])
        F.assert_no_external_work()

    def lines(self):
        """What the room heard about the invitation (the 'suggests' line of
        the request is not part of what is checked here)."""
        return [line for line in self.said if "suggests" not in line[0]]

    def pair_invitation(self):
        name, partner, target, _ = S.authored_pair()
        eid = S.request(name, target, members=[partner])["execution_id"]
        self.assertEqual(R.get(eid)["status"], "awaiting_consent")
        return name, partner, eid

    def expired_pair(self):
        name, partner, eid = self.pair_invitation()
        tick(300)
        self.assertEqual((R.get(eid)["status"], R.get(eid)["reason"]), ("cancelled", "consent_expired"))
        self.said.clear()
        self.told.clear()
        return name, partner, eid

    def test_1_pair_window_300(self):
        print("[1] a pair waits 300 s")
        name, partner, eid = self.pair_invitation()
        self.assertEqual(A.consent_window_s(R.get(eid)), 300.0)
        tick(299)
        run = R.get(eid)
        self.assertEqual(run["status"], "awaiting_consent")
        self.assertEqual(run["data"]["consent_wait_s"], 299)
        tick(1)
        run = R.get(eid)
        self.assertEqual((run["status"], run["reason"]), ("cancelled", "consent_expired"))
        expected = [(EXPIRED, {"inviter": name, "silent": partner})]
        self.assertEqual(self.lines(), expected)
        self.assertEqual(self.told, expected)

    def test_2_trio_window_420(self):
        print("[2] a trio waits 420 s and names who had agreed")
        (a, b, c), target = G.authored_trio()
        eid = S.request(a, target, members=[b, c])["execution_id"]
        self.assertEqual(A.consent_window_s(R.get(eid)), 420.0)
        tick(100)
        self.assertEqual(A.respond(b, eid, True)["status"], "awaiting_consent")
        tick(200)
        tick(119)
        self.assertEqual(R.get(eid)["status"], "awaiting_consent")
        tick(1)
        run = R.get(eid)
        self.assertEqual((run["status"], run["reason"]), ("cancelled", "consent_expired"))
        expected = [(AGREED, {"inviter": a, "silent": c, "agreed": b})]
        self.assertEqual(self.lines(), expected)
        self.assertEqual(self.told, expected)

    def test_3_game_factor_does_not_shorten_it(self):
        print("[3] twice the game speed, the same 300 real seconds")
        _name, _partner, eid = self.pair_invitation()
        motion_only_step(299, 598)
        run = R.get(eid)
        self.assertEqual(run["status"], "awaiting_consent")
        self.assertEqual(run["data"]["consent_wait_s"], 299)
        motion_only_step(1, 2)
        self.assertEqual(R.get(eid)["reason"], "consent_expired")

    def test_4_frozen_world_pauses_it(self):
        print("[4] a frozen world pauses the window")
        _name, _partner, eid = self.pair_invitation()
        tick(200)
        F.W.set_world_frozen(True)
        tick(500)
        F.W.set_world_frozen(False)
        tick(99)
        self.assertEqual(R.get(eid)["status"], "awaiting_consent")
        self.assertEqual(R.get(eid)["data"]["consent_wait_s"], 299)
        tick(1)
        self.assertEqual(R.get(eid)["reason"], "consent_expired")

    def test_5_late_yes_tells_the_inviter_once(self):
        print("[5] a late yes reaches the inviter once")
        _name, partner, eid = self.expired_pair()
        tick(60)
        result = A.respond(partner, eid, True)
        self.assertEqual((result["status"], result["reason"]), ("cancelled", "consent_expired"))
        expected = [(LATE, {"name": partner})]
        self.assertEqual(self.lines(), expected)
        self.assertEqual(self.told, expected)
        A.respond(partner, eid, True)
        self.assertEqual(self.lines(), expected)
        self.assertEqual(self.told, expected)

    def test_6_late_no_says_nothing(self):
        print("[6] a late no says nothing")
        _name, partner, eid = self.expired_pair()
        tick(60)
        A.respond(partner, eid, False)
        self.assertEqual((self.lines(), self.told), ([], []))
        self.assertEqual(R.get(eid)["reason"], "consent_expired")

    def test_7_too_late_says_nothing(self):
        print("[7] a yes 601 s after the expiry says nothing")
        _name, partner, eid = self.expired_pair()
        tick(601)
        A.respond(partner, eid, True)
        self.assertEqual((self.lines(), self.told), ([], []))

    def test_8_expired_before_the_tick(self):
        print("[8] the answer finds the window closed before any tick")
        name, partner, eid = self.pair_invitation()
        F.set_game_time(F.game_time() + GameDuration.of(seconds=300))
        result = A.respond(partner, eid, True)
        self.assertEqual((result["status"], result["reason"]), ("cancelled", "consent_expired"))
        self.assertFalse(R.claims(eid))
        expected = [(EXPIRED, {"inviter": name, "silent": partner}), (LATE, {"name": partner})]
        self.assertEqual(self.lines(), expected)
        self.assertEqual(self.told, expected)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *F.REST])
