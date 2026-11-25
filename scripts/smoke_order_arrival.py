#!/usr/bin/env python3
"""The avatar reports its own arrival: ``POST /play/order/arrived`` and
``/play/pos`` during an approach (plan E3 Task 7, Review B2).

Usage: ./.venv/bin/python scripts/smoke_order_arrival.py

Runs on the private fixture of ``smoke_prop_action_runs.py`` (temporary storage
and instance, ``paths.init(<tmp>)`` before every world import, no server); the
HTTP cases use the in-process app of ``smoke_orders_route.py`` (the real auth
gate, the play and prop-action routers, no lifespan). The motion clock is the
hand-set ``F.MOTION``.

Fixture (hand-derived, ``smoke_order_timer.py`` STANDING): the avatar stands at
(1, 5) in "hall" and asks for "rest" on "device" at (8, 5); its access is
(8, 7), the entry clip 2.0 s, issued 100. ARRIVE_TOL_M = 0.5
(``motion_orders``): a report closer than that counts.

  [A1] arrived at (8.4, 7) (0.4 m off), reported at motion second 101:
       {"ok": true}; the run is entering, the avatar EXACTLY on (8, 7); the
       order flips at the report's second + the entry = 101 + 2.0 = 103.0.
  [A2] (8.6, 7) (0.6 m off): 409 arrive_too_far; the run still approaches.
  [A3] the report names the room "adjacent": 409 room_mismatch.
  [A4] an unknown order id: 409 order_unknown.
  [A7] no session: 401.
  [A5] /play/pos at (2, 5.5) in the target room while walking: written (the
       stored point is (2, 5.5)), the run still approaches.
  [A6] the avatar moved to (11, 5) first (that write ends the first run), a
       new run asked at 110; /play/pos at (12.5, 5), 1.5 m on, in the adjacent
       room before the arrival: the run is cancelled and ONE cancel order
       names the avatar (it held no place: a row without steps).
  [A8] after the arrival (phase entry) /play/pos at (8.1, 7): dropped
       (server_owned), the point stays (8, 7); at 103.1 the run is active.
  [A8b] the avatar entered in arrived (on its access) while the entry has not
       begun (phase "", as in a pair run waiting for the partner): /play/pos at
       (8.1, 7) is dropped as well (server_owned), the point stays (8, 7).
  [A9] a recorder on _validate: whenever the avatar is in arrived, it stands
       exactly on its access — the position is written BEFORE the entry.
"""
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_prop_action_runs as S                                       # noqa: E402

F, A, R = S.F, S.A, S.R
from app.core import paths                                               # noqa: E402
paths.init(F.ROOT / "world")    # the fixture's private world, named here once more
from fastapi.testclient import TestClient                                # noqa: E402
from app.core import motion_orders as MO                                 # noqa: E402
import smoke_orders_route as OR                                          # noqa: E402

ACCESS = {"x": 8.0, "z": 7.0}


class Arrival(unittest.TestCase):
    def setUp(self):
        MO.boot()
        self.name, self.target, _pid = S.setup_run()
        self.http = OR.client(self.name)
        F.MOTION[0] = 100.0
        answer = S.request(self.name, self.target)
        self.assertEqual(answer["status"], "approaching", answer)
        self.eid = answer["execution_id"]
        self.order = R.get(self.eid)["data"]["order"]
        self.assertTrue(self.order["actors"][0]["reports_arrival"])
        self.assertEqual(self.order["actors"][0]["access"]["x"], 8.0)
        self.assertEqual(self.order["actors"][0]["access"]["z"], 7.0)

    def tearDown(self):
        F.W.set_world_frozen(False)
        for run in R.live_runs():
            A.cancel(run["actor"], run["execution_id"])
        F.assert_no_external_work()

    def arrived(self, x, z, room="hall", order_id=None, http=None):
        return (http or self.http).post("/play/order/arrived", json=dict(
            order_id=order_id or self.order["order_id"], x=x, z=z, yaw=0.0, room_id=room))

    def test_a1_a8_a9_arrival(self):
        seen = []
        real = A._validate

        def recorder(run, **kw):
            data = run.get("data") or {}
            if self.name in data.get("arrived", []):
                seen.append(F.C.get_character_pos(self.name))
            return real(run, **kw)
        F.MOTION[0] = 101.0
        with patch.object(A, "_validate", recorder):
            answer = self.arrived(8.4, 7.0)
        print("[A1] 0.4 m: ok, entering, exactly on the access")
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(answer.json(), {"ok": True})
        run = R.get(self.eid)
        self.assertEqual((run["status"], run["phase"]), ("approaching", "entry"))
        self.assertEqual(F.C.get_character_pos(self.name), ACCESS)
        self.assertAlmostEqual(run["data"]["order"]["flip_motion_s"], 103.0, places=3)
        self.assertEqual(run["data"]["order"]["status"], "entering")
        print("[A9] in arrived only ever on the access")
        self.assertTrue(seen)
        self.assertTrue(all(p == ACCESS for p in seen), seen)
        print("[A8] a later report is dropped, the point stays")
        pos = self.http.post("/play/pos", json=dict(x=8.1, z=7.0))
        self.assertEqual(pos.status_code, 200, pos.text)
        self.assertEqual(pos.json(), {"ok": False, "server_owned": True})
        self.assertEqual(F.C.get_character_pos(self.name), ACCESS)
        F.MOTION[0] = 103.1
        A.advance(F.game_time())
        self.assertEqual(R.get(self.eid)["status"], "active")

    def test_a8b_arrived_before_entry(self):
        print("[A8b] in arrived, entry not begun: a report is dropped, the point stays")
        F.MOTION[0] = 101.0
        run = R.get(self.eid)
        with A._lock(self.eid):
            A._arrive(run, self.name, 101.0)    # arrived, but no _enter_or_wait (a pair waiting for B)
        run = R.get(self.eid)
        self.assertEqual((run["status"], run["phase"], run["data"]["arrived"]), ("approaching", "", [self.name]))
        pos = self.http.post("/play/pos", json=dict(x=8.1, z=7.0))
        self.assertEqual(pos.status_code, 200, pos.text)
        self.assertEqual(pos.json(), {"ok": False, "server_owned": True})
        self.assertEqual(F.C.get_character_pos(self.name), ACCESS)
        self.assertEqual(R.get(self.eid)["status"], "approaching")

    def test_a2_a3_a4_a7_refusals(self):
        print("[A2] 0.6 m: arrive_too_far")
        answer = self.arrived(8.6, 7.0)
        self.assertEqual((answer.status_code, answer.json()["detail"]["reason"]), (409, "arrive_too_far"))
        self.assertEqual(R.get(self.eid)["status"], "approaching")
        print("[A3] another room: room_mismatch")
        answer = self.arrived(8.2, 7.0, room="adjacent")
        self.assertEqual((answer.status_code, answer.json()["detail"]["reason"]), (409, "room_mismatch"))
        print("[A4] unknown order: order_unknown")
        answer = self.arrived(8.2, 7.0, order_id="ord-unknown")
        self.assertEqual((answer.status_code, answer.json()["detail"]["reason"]), (409, "order_unknown"))
        print("[A7] no session: 401")
        answer = self.arrived(8.2, 7.0, http=TestClient(OR.app()))
        self.assertEqual(answer.status_code, 401, answer.text)
        self.assertEqual(R.get(self.eid)["status"], "approaching")

    def test_a5_pos_in_target_room(self):
        print("[A5] a report in the target room is written, the run goes on")
        answer = self.http.post("/play/pos", json=dict(x=2.0, z=5.5))
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertTrue(answer.json().get("ok"), answer.json())
        self.assertEqual(F.C.get_character_pos(self.name), {"x": 2.0, "z": 5.5})
        self.assertEqual(R.get(self.eid)["status"], "approaching")

    def test_a6_pos_in_other_room(self):
        F.C.set_character_pos(self.name, 11.0, 5.0)    # ends the first run (a manual write)
        F.MOTION[0] = 110.0
        answer = S.request(self.name, self.target)
        self.assertEqual(answer["status"], "approaching", answer)
        eid = answer["execution_id"]
        seen, spy = OR.published()
        print("[A6] a report in the adjacent room ends the run")
        with spy:
            pos = self.http.post("/play/pos", json=dict(x=12.5, z=5.0))
        self.assertEqual(pos.status_code, 200, pos.text)
        run = R.get(eid)
        self.assertEqual(run["status"], "cancelled", (run["status"], run["reason"], pos.json()))
        cancels = [o for o in seen if o["kind"] == "cancel"]
        self.assertEqual(len(cancels), 1, cancels)
        self.assertEqual([a["name"] for a in cancels[0]["actors"]], [self.name])


if __name__ == "__main__":
    unittest.main(verbosity=2)
