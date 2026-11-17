#!/usr/bin/env python3
"""One furniture action whose scheduler step raises must not stop the others;
it is retried, and ended with its claims and its people released when it
keeps failing (review 11#2).

Usage: ./.venv/bin/python scripts/smoke_prop_action_step_isolation.py

Real temporary world — the fixtures of ``smoke_prop_action_runs.py``
(``setup_run``: one solo "rest" action on a prop in a private world). The
marker gets capacity 3 with 0.6 m spacing and no access override, so three
actors (P1, P2, P3 at (1,5), (2,5), (3,5)) each request it and get one slot
each: three runs, all "approaching", each holding 2 claims (person + slot)
= 6 claims, created in the order P1, P2, P3 — the order ``store.live_runs()``
steps them (ORDER BY created_at).

The middle run's step is made to raise by wrapping ``_validate`` (called in
every live step, after ``_clock``) for P2's execution id. Each ``step`` moves
both clocks 1 s (the fixture's lockstep) and runs ``advance`` once; no
journey is advanced, so nobody arrives and the 60 s approach deadline is far.
Hand-derived from ``prop_action_engine`` (STEP_FAIL_LIMIT 3, STEP_RETRY_S 5,
the SYSTEM monotonic clock held still by hand unless moved):

  [1] P2 raises in every step. Steps 1 and 2: P1 and P3 "approaching" with
      ``data.elapsed`` 1 then 2 (motion_delta 1 s each); P2 still
      "approaching", elapsed 0 (its step rolled back), 6 claims, failure
      record count 1 then 2; ``advance`` returns 2 (P1, P3). ``due_in_s``
      over P2 alone is None while its last failure is < 5 s old. Step 3:
      count 3 = the limit -> P2 "failed"/"engine_error", 0 claims of its own,
      no journey on P2's profile (cleanup cancels it), 6 - 2 = 4 claims, no
      failure record left; P1/P3 elapsed 3.
      Old code: the exception left ``advance`` at P2 in step 1, so P3 kept
      elapsed 0 — and ``advance`` raised.
  [2] A passing fault: P2 raises in step 1 only. Step 2 steps it normally:
      the record is cleared and P2's elapsed is 2 — the rolled-back step
      never moved ``last_motion``, so step 2's motion_delta covers both
      seconds. All three keep their claims (6).
  [3] Its regular end raises too (``_finish`` for P2): after step 3 P2 is
      still ended "failed"/"engine_error" by the plain terminal save, 0 claims
      of its own, journey gone, 4 claims in total.
  [4] Even the terminal save raises: after step 3 P2 stays "approaching" with
      its record at the limit; step 4 does NOT step it again (the
      ``_validate`` wrapper stays at 3 calls for P2) — it only tries to end
      it — while P1/P3 reach elapsed 4. Once the save works, step 5 ends it:
      "failed"/"engine_error", 0 claims of its own, 4 in total, no record.
"""
import sys
import time
import unittest
from unittest.mock import patch

import smoke_prop_action_runs as S
from smoke_prop_action_runs import A, F, R
from app.core.game_time import GameDuration                             # noqa: E402


def three_runs():
    name, target, pid = S.setup_run()
    doc = F.props.read_sidecar(pid)
    marker = doc["model_variants"][0]["markers"][0]
    marker.pop("access", None)
    marker.update(capacity=3, spacing_m=.6)
    F.props._write_sidecar(pid, doc)
    target["definition_revision"] = F.props.get_prop(pid)["revision"]
    people = [name] + [F.actor(target["location_id"], at=(x, 5)) for x in (2, 3)]
    for person in people[1:]:
        profile = F.C.get_character_profile(person)
        profile["height"] = 170
        F.C.save_character_profile(person, profile)
    eids = []
    for person in people:
        answer = S.request(person, target)
        assert answer["status"] == "approaching", answer
        eids.append(answer["execution_id"])
    assert len(R.claims()) == 6
    assert all(R.get(e)["data"]["elapsed"] == 0 for e in eids)
    return people, eids


def step(seconds=1):
    F.set_game_time(F.game_time() + GameDuration.of(seconds=seconds))
    return A.advance(F.game_time())


class StepIsolation(unittest.TestCase):
    def setUp(self):
        self.clock = [time.monotonic()]
        for p in (patch.object(A.time, "monotonic", side_effect=lambda: self.clock[0]),
                  patch.object(A.logger, "exception"), patch.object(A.logger, "warning")):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        A._STEP_FAILED.clear()
        A._END_FAILED.clear()
        for run in R.live_runs():
            A.cancel(run["actor"], run["execution_id"])
        F.assert_no_external_work()

    def raising(self, eid, *, times=None):
        """``_validate`` raising for ``eid`` (``times`` calls, else always)."""
        real = A._validate
        calls = []

        def validate(run, *args, **kwargs):
            if run["execution_id"] == eid:
                calls.append(eid)
                if times is None or len(calls) <= times:
                    raise ValueError("participant_state_missing")
            return real(run, *args, **kwargs)
        return patch.object(A, "_validate", side_effect=validate), calls

    def elapsed(self, eid):
        return R.get(eid)["data"]["elapsed"]

    def assert_ended(self, people, eids):
        middle = R.get(eids[1])
        self.assertEqual((middle["status"], middle["reason"]), ("failed", "engine_error"))
        self.assertEqual(R.claims(eids[1]), [])
        self.assertEqual(len(R.claims()), 4)
        self.assertFalse((F.C.get_character_profile(people[1]) or {}).get("journey"))
        self.assertNotIn(eids[1], A._STEP_FAILED)

    def three_failing_steps(self, eids):
        for n in (1, 2):
            moved = step()
            self.assertEqual(moved, 2)
            self.assertEqual((self.elapsed(eids[0]), self.elapsed(eids[2])), (n, n))
            self.assertEqual((R.get(eids[1])["status"], self.elapsed(eids[1])), ("approaching", 0))
            self.assertEqual(len(R.claims()), 6)
            self.assertEqual(A._STEP_FAILED[eids[1]][0], n)
            with patch.object(R, "live_runs", return_value=[R.get(eids[1])]):
                self.assertIsNone(A.due_in_s(F.game_time()))
        step()
        self.assertEqual((self.elapsed(eids[0]), self.elapsed(eids[2])), (3, 3))

    def test_1_retried_then_ended(self):
        print("[1] the middle run keeps raising: the others advance, it ends after 3 failures")
        people, eids = three_runs()
        broken, calls = self.raising(eids[1])
        with broken:
            self.three_failing_steps(eids)
        self.assertEqual(len(calls), 3)
        self.assert_ended(people, eids)

    def test_2_passing_fault(self):
        print("[2] one failure, then a normal step: the record is cleared")
        people, eids = three_runs()
        broken, _ = self.raising(eids[1], times=1)
        with broken:
            step()
            self.assertEqual(A._STEP_FAILED[eids[1]][0], 1)
            step()
        self.assertNotIn(eids[1], A._STEP_FAILED)
        self.assertEqual([self.elapsed(e) for e in eids], [2, 2, 2])
        self.assertEqual(R.get(eids[1])["status"], "approaching")
        self.assertEqual(len(R.claims()), 6)

    def test_3_fallback_end(self):
        print("[3] its regular end raises too: ended without effects, claims free")
        people, eids = three_runs()
        broken, _ = self.raising(eids[1])
        real_finish = A._finish

        def finish(run, *args, **kwargs):
            if run["execution_id"] == eids[1]:
                raise ValueError("participant_state_missing")
            return real_finish(run, *args, **kwargs)
        with broken, patch.object(A, "_finish", side_effect=finish):
            self.three_failing_steps(eids)
        self.assert_ended(people, eids)

    def test_4_end_fails_too(self):
        print("[4] it cannot even be saved: no further step, ended once the save works")
        people, eids = three_runs()
        broken, calls = self.raising(eids[1])
        real_finish, real_save = A._finish, A._save

        def finish(run, *args, **kwargs):
            if run["execution_id"] == eids[1]:
                raise ValueError("participant_state_missing")
            return real_finish(run, *args, **kwargs)

        def save(run):
            if run["execution_id"] == eids[1]:
                raise RuntimeError("database is locked")
            return real_save(run)
        with broken, patch.object(A, "_finish", side_effect=finish):
            with patch.object(A, "_save", side_effect=save):
                self.three_failing_steps(eids)
                self.assertEqual(R.get(eids[1])["status"], "approaching")
                self.assertEqual(A._STEP_FAILED[eids[1]][0], A.STEP_FAIL_LIMIT)
                self.clock[0] += 1
                step()
                self.assertEqual(len(calls), 3, "a run at the limit is not stepped again")
                self.assertEqual((self.elapsed(eids[0]), self.elapsed(eids[2])), (4, 4))
            step()
        self.assertEqual(len(calls), 3)
        self.assert_ended(people, eids)


if __name__ == "__main__":
    result = unittest.main(argv=[sys.argv[0], "-v"], exit=False).result
    sys.exit(0 if result.wasSuccessful() else 1)
