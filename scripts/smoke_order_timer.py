#!/usr/bin/env python3
"""Furniture runs on the estimate timer (plan E3 Task 7, decisions 7a-7d, 8, 17).

Usage: ./.venv/bin/python scripts/smoke_order_timer.py

Runs on the private fixture of ``smoke_prop_action_runs.py`` (temporary storage
and instance, ``paths.init(<tmp>)`` before every world import, no server, no
model call). The motion clock is the fixture's hand-set ``F.MOTION``; a step is
``at(t)`` = set the clock to t, then ``advance`` (the full round unless
``due_only``). Speed 1.4 m/s (``travel.DEFAULT_SPEED_M_S``), START_SLACK_S 0.5,
DEADLINE_MIN_S 10 (``motion_orders``): eta = issued + exit + L / 1.4 + 0.5,
flip = eta + entry, deadline = eta + max(10, 0.5 * (eta - issued)). Stored
seconds are rounded to 3 decimals.

Geometries (hand-derived from ``F.fixture``: a 1 x 1 m piece whose seat
marker's access lies 2 m in front of the placement, yaw 180; hall 12 x 10 m):

  STANDING  NPC at (1, 5), "device" at (8, 5) -> access (8, 7); the straight
            line passes the piece's 0.3 m margin box (x 7.2..8.8, z 4.2..5.8)
            at z = 5 + 2 * 6.2 / 7 = 6.771 > 5.8, so the plan is [[1,5],[8,7]]:
            L = sqrt(7^2 + 2^2) = sqrt(53) = 7.280110, L / 1.4 = 5.200078.
            Entry clip "run-enter" 2.0 s. Issued 100:
            eta 105.700078, flip 107.700078, deadline 105.700 + 10 = 115.700.
  O1        (Task 1 O1) the NPC SEATED on "device" moved to (4, 2) (access
            (4, 4)), asks for "device2" at (6.5, 3.25) (access (6.5, 5.25),
            anchor (6.5, 3.25)); exit clip "run-exit" 1.2 s whose root motion
            ends 2 m in front (the bridge stand = the access (4, 4)); entry
            "run-enter" rewritten to 2.4 s. L = sqrt(2.5^2 + 1.25^2) =
            sqrt(7.8125) = 2.795085, L / 1.4 = 1.996489. Issued 100:
            eta = 100 + 1.2 + 1.996489 + 0.5 = 103.696489,
            flip = 106.096489, deadline = 103.696 + 10 = 113.696.
  PAIR      ``S.authored_pair`` (actor (1, 5), partner (2, 5), one marker of
            capacity 2: actor access (7.7, 7), partner access (8.3, 7)),
            entry rewritten to 2.4 s, issued 95. Both lines clear the margin box
            (z at x = 7.2: 6.851 and 6.651 > 5.8):
            L_actor = sqrt(6.7^2 + 2^2) = sqrt(48.89) = 6.992138 -> eta 100.494384,
            L_partner = sqrt(6.3^2 + 2^2) = sqrt(43.69) = 6.609841 -> eta 100.221315;
            run eta 100.494, deadline 110.494.

Cases:
  [E1]  O1: order issued 100, eta 103.696, flip 106.096, deadline 113.696; at
        103.6 still approaching; at 103.7 entering, the NPC exactly on its
        access (6.5, 5.25), the revision keeps flip 106.096 (the NPC's own eta
        + 2.4); at 106.1 active, on the slot (6.5, 3.25).
  [E2]  during that approach no profile journey and no travel_changed.
  [E12] O1: the sequence is exit -> walk -> entry -> loop, the exit nominal
        1.2 s of kind "seat"; right after the request the NPC holds no place
        and pose_key "".
  [E3]  PAIR with consent react: at 100.3 the partner alone has arrived
        (still approaching); at 100.5 both: status waiting, awaits reaction,
        no flip_motion_s; react(accept) at 105.0 -> entering, flip 107.4;
        at 107.41 active.
  [E11] the same wait 30 s past the deadline (at 140.5, full rounds) -> still
        waiting (no approach_timeout once everyone is there).
  [E4]  the reaction wait runs out (waited 61 s > 60) at 141.0 -> entering,
        reaction "timeout", flip = 141.0 + 2.4 = 143.4.
  [E10] PAIR asked and accepted at 95 (no reaction): at 100.3 the partner is in
        arrived, exactly on (8.3, 7); a full round at 100.4 -> still
        approaching (no access_position_lost); at 100.5 entering.
  [E5]  STANDING, motion_alive_s 101, boot at 131: shift 30 -> issued 130, eta
        135.700, flip 137.700, deadline 145.700, revision 1 -> 2, the order
        marked boot_alive_s 101; due_in_s = 135.700 - 131 = 4.700 > 0.
  [E6]  STANDING frozen at 200: advance moves nothing (approaching, phase "").
  [E7]  STANDING (issued 100, eta 105.700) plus a second NPC at (1, 8) to a
        piece "device2" at (4, 2) (access (4, 4), L = 5, issued 104 -> eta
        104 + 3.571429 + 0.5 = 108.071): advance(due_only) at 106 counts
        advance_validate exactly once, and only the first run moved (entering).
  [E8]  O1 with the NPC taken over as an avatar (reports_arrival): no
        arrival by itself; at 113.6 approaching, at 113.8 failed
        approach_timeout, and ONE cancel order whose actor stands where its
        order has it: (113.8 - 100 - 1.2) * 1.4 = 17.64 m > L = 2.795 -> the end
        of the polyline, the access (6.5, 5.25), written as its position too.
  [E17] O1 NPC (plan [[4, 4], [6.5, 5.25]]) cancelled at 102.5: it has walked
        (102.5 - 100 - 1.2) * 1.4 = 1.82 m along the unit (2.5, 1.25) / 2.795085
        = (0.894427, 0.447214) -> (4 + 1.627857, 4 + 0.813929) = (5.628, 4.814),
        stored at centimetres (set_character_pos rounds to 0.01) -> (5.63, 4.81):
        the cancel's stand and its position, place None (never the seat (4, 2)).
  [E17b] the same cancelled at 100.5, inside the 1.2 s exit: 0 m -> the
        polyline's first point (4, 4).
  [E18] O1 NPC on the way at 102 (walk point (5.00, 4.50): (102 - 100 - 1.2)
        * 1.4 = 1.12 m along (0.894427, 0.447214)) is moved by its OWN write
        set_character_pos(2, 8) made under keyed_lock("character_profile"):
        the interrupt is delivered after the lock, so _finish runs after the
        write. The run is cancelled "position"; the stored point stays the
        write's (2, 8), never the walk point, and the cancel's stand is (2, 8).
  [E18b] the same write without a lock (the interrupt runs before it):
        position (2, 8) after the write, run cancelled "position".
  [E19] _walk_point of a run whose _start failed before issued_s: a member
        with a recorded departure_seat stands at the polyline's first point
        (4, 4) (its exit's end, the seat was released); one without -> None.
  [E9]  boot (a)/(b): a run without data.order -> cancelled e3_migration; a
        profile journey with an approach_target -> removed.
  [E13] STANDING combined (prepare 5 s, drink 5 s game): only due_only steps:
        105.8 entering, 107.8 active "prepare", +4 game s still "prepare",
        +1 game s "drink".
  [E14] STANDING in the entry (at 106: entering, flip 107.700), motion_alive_s
        = 106.700, boot at 126.700: shift 20 -> flip 127.700; at 127.69 still
        entering, at 127.71 active.
  [E15] missing motion_alive_s -> shift 0 (times and revision unchanged);
        stamp 101, boot at 131 -> +30, then the stamp put back to 101 (a crash
        before the heartbeat) and a second boot at 131.5 -> no second shift.
  [E16] heartbeat: no live order -> no motion_alive_s write over 20 beats;
        with one, a write at its publication and then at most one per 5 s
        (20 one-second beats -> 4 more); 60 s idle, then a new order's
        publication writes at once; a boot 2 s later shifts by 2 s, not 62.
"""
import json
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
from app.core import hooks, sync_topics                                  # noqa: E402
from app.core import motion_orders as MO                                 # noqa: E402
from app.core.game_time import GameDuration                              # noqa: E402
import smoke_orders_route as OR                                          # noqa: E402

STANDING = dict(issued=100.0, eta=105.700078, flip=107.700078, deadline=115.700)
O1 = dict(issued=100.0, eta=103.696489, flip=106.096489, deadline=113.696)


def at(t, due_only=False):
    F.MOTION[0] = float(t)
    return A.advance(F.game_time(), due_only=due_only)


def entry_seconds(seconds):
    """Rewrite the entry clip "run-enter" to ``seconds`` (same geometry)."""
    (F.ROOT / "clips" / "run-enter.json").write_text(json.dumps(dict(
        kind="run-enter", duration_s=seconds, loop=False,
        geometry=dict(root_motion=dict(mode="foot_lock", travel_m=[0, 2], ref_height_m=1.7)))))
    S.clips._clear_entries_cache()


def standing(ability="pose"):
    name, target, pid = S.setup_run(ability)
    F.MOTION[0] = 100.0
    answer = S.request(name, target)
    assert answer["status"] == "approaching", answer
    run = R.get(answer["execution_id"])
    assert run["data"]["plans"][name]["waypoints"] == [[1, 5], [8, 7]], run["data"]["plans"][name]["waypoints"]
    return name, target, answer["execution_id"]


def seated_o1():
    """The O1 geometry: seated on "device" (4, 2), target "device2"."""
    name, target, pid = S.setup_run()
    clips = F.ROOT / "clips"
    (clips / "run-exit.fbx").write_bytes(b"private deterministic exit fixture")
    (clips / "run-exit.json").write_text(json.dumps(dict(
        kind="run-exit", duration_s=1.2, loop=False,
        geometry=dict(root_motion=dict(mode="foot_lock", travel_m=[0, 2], ref_height_m=1.7)))))
    entry_seconds(2.4)
    S.clips._write_world_transitions([
        {"from": "walking", "to": "sitting", "kind": "run-enter", "accel": 0},
        {"from": "sitting", "to": "walking", "kind": "run-exit", "accel": 0}])
    loc = F.W.get_location_by_id(target["location_id"])
    hall = next(r for r in loc["rooms"] if r["id"] == "hall")
    device = hall["layout"]["props"][0]
    device["at"] = [4, 2]
    hall["layout"]["props"].append(dict(device, id="device2", at=[6.5, 3.25]))
    F.W.upsert_location(loc, sync_world=True)
    F.places.invalidate()
    # Seat it: from (1, 5) to the access (4, 4): sqrt(10) / 1.4 + 0.5 = 2.758770
    # after 50 -> eta 52.759, flip 55.159.
    F.MOTION[0] = 50.0
    first = S.request(name, target)
    assert first["status"] == "approaching", first
    at(53)
    at(56)
    assert R.get(first["execution_id"])["status"] == "active", R.get(first["execution_id"])
    assert F.C.get_character_pos(name) == {"x": 4.0, "z": 2.0}, F.C.get_character_pos(name)
    F.MOTION[0] = 100.0
    return name, dict(target, placement_id="device2")


def order_of(eid):
    return R.get(eid)["data"]["order"]


def set_alive(value):
    F.W.set_world_setting(MO.ALIVE_KEY, "" if value is None else str(value))


class Timer(unittest.TestCase):
    def setUp(self):
        MO.boot()
        MO._last_alive[0] = None    # a fresh process: no liveness write yet

    def tearDown(self):
        F.W.set_world_frozen(False)
        F.set_game_factor(0)
        for run in R.live_runs():
            A.cancel(run["actor"], run["execution_id"])
        F.assert_no_external_work()

    def test_e1_e2_e12_o1_npc(self):
        travel_changes = []
        with patch.object(sync_topics, "travel_changed", lambda *a, **k: travel_changes.append(a)):
            name, target = seated_o1()
            travel_changes.clear()
            answer = S.request(name, target)
            self.assertEqual(answer["status"], "approaching", answer)
            eid = answer["execution_id"]
            run = R.get(eid)
            plan = run["data"]["plans"][name]
            self.assertEqual(plan["waypoints"], [[4, 4], [6.5, 5.25]])
            order = order_of(eid)
            print("[E1] O1 times")
            self.assertAlmostEqual(order["issued_motion_s"], O1["issued"], places=3)
            self.assertAlmostEqual(order["eta_motion_s"], O1["eta"], places=3)
            self.assertAlmostEqual(order["flip_motion_s"], O1["flip"], places=3)
            self.assertAlmostEqual(order["deadline_motion_s"], O1["deadline"], places=3)
            print("[E12] seated start: exit -> walk -> entry -> loop, seat free")
            self.assertEqual([s["step"] for s in order["actors"][0]["sequence"]], ["exit", "walk", "entry", "loop"])
            exit_step = order["actors"][0]["sequence"][0]
            self.assertEqual((exit_step["pose_kind"], exit_step["nominal_s"]), ("seat", 1.2))
            profile = F.C.get_character_profile(name)
            self.assertIsNone(profile.get("place"))
            self.assertEqual(profile.get("pose_key") or "", "")
            self.assertEqual(plan["departure_seat"]["seat"], [4.0, 2.0])
            print("[E1] at 103.6 approaching, 103.7 entering on the access, 106.1 active")
            at(103.6)
            self.assertEqual((R.get(eid)["status"], R.get(eid)["phase"]), ("approaching", ""))
            print("[E2] no journey, no travel_changed")
            self.assertNotIn("journey", F.C.get_character_profile(name))
            at(103.7)
            run = R.get(eid)
            self.assertEqual((run["status"], run["phase"]), ("approaching", "entry"))
            self.assertEqual(F.C.get_character_pos(name), {"x": 6.5, "z": 5.25})
            self.assertEqual(order_of(eid)["status"], "entering")
            self.assertAlmostEqual(order_of(eid)["flip_motion_s"], O1["flip"], places=3)
            at(106.0)
            self.assertEqual(R.get(eid)["status"], "approaching")
            at(106.1)
            self.assertEqual(R.get(eid)["status"], "active")
            self.assertEqual(F.C.get_character_pos(name), {"x": 6.5, "z": 3.25})
            self.assertNotIn("journey", F.C.get_character_profile(name))
        self.assertEqual(travel_changes, [])

    def react_pair(self, consent="react"):
        self.asked = []
        hooks.register_provider("pair_reaction", lambda **kw: self.asked.append(kw), owner="smoke")
        self.addCleanup(hooks._providers.pop, "pair_reaction", None)
        name, partner, target, pid = S.authored_pair()
        entry_seconds(2.4)
        F.MOTION[0] = 95.0
        answer = S.request(name, target, members=[partner], consent=consent)
        if consent == "ask":
            self.assertEqual(answer["status"], "awaiting_consent", answer)
            answer = A.respond(partner, answer["execution_id"], True)
        self.assertEqual(answer["status"], "approaching", answer)
        eid = answer["execution_id"]
        plans = R.get(eid)["data"]["plans"]
        self.assertEqual(plans[name]["waypoints"], [[1, 5], [7.7, 7]])
        self.assertEqual(plans[partner]["waypoints"], [[2, 5], [8.3, 7]])
        etas = R.get(eid)["data"]["eta_s"]
        self.assertAlmostEqual(etas[name], 100.494384, places=3)
        self.assertAlmostEqual(etas[partner], 100.221315, places=3)
        return name, partner, eid

    def test_e3_e11_e4_reaction(self):
        name, partner, eid = self.react_pair()
        print("[E3] the partner first, then both: waiting without flip")
        at(100.3)
        run = R.get(eid)
        self.assertEqual((run["status"], run["phase"], run["data"]["arrived"]), ("approaching", "", [partner]))
        at(100.5)
        order = order_of(eid)
        self.assertEqual((order["status"], order["awaits"]), ("waiting", "reaction"))
        self.assertNotIn("flip_motion_s", order)
        print("[E11] 30 s past the deadline, full rounds: still waiting")
        at(120.5)
        at(140.5)
        run = R.get(eid)
        self.assertEqual((run["status"], run["phase"]), ("approaching", ""))
        self.assertEqual(order_of(eid)["status"], "waiting")
        print("[E4] the wait runs out: entering, flip = now + 2.4")
        with patch.object(A.pair_reaction, "waited_s", lambda asked_at: 61.0):
            at(141.0)
        run = R.get(eid)
        self.assertEqual((run["status"], run["phase"]), ("approaching", "entry"))
        self.assertEqual(run["data"]["reaction"]["state"], "timeout")
        self.assertAlmostEqual(order_of(eid)["flip_motion_s"], 143.4, places=3)

    def test_e3_react_accept(self):
        name, partner, eid = self.react_pair()
        at(100.5)
        self.assertEqual(order_of(eid)["awaits"], "reaction")
        print("[E3] react(accept) at 105.0 -> flip 107.4")
        F.MOTION[0] = 105.0
        A.react(partner, eid, True)
        order = order_of(eid)
        self.assertEqual((order["status"], order["awaits"]), ("entering", ""))
        self.assertAlmostEqual(order["flip_motion_s"], 107.4, places=3)
        at(107.39)
        self.assertEqual(R.get(eid)["status"], "approaching")
        at(107.41)
        self.assertEqual(R.get(eid)["status"], "active")

    def test_e10_single_arrivals(self):
        name, partner, eid = self.react_pair(consent="ask")
        print("[E10] the partner arrives first, exactly on its access")
        at(100.3)
        run = R.get(eid)
        self.assertEqual(run["data"]["arrived"], [partner])
        self.assertEqual(F.C.get_character_pos(partner), {"x": 8.3, "z": 7.0})
        at(100.4)    # a full round in between
        run = R.get(eid)
        self.assertEqual((run["status"], run["phase"]), ("approaching", ""), run["reason"])
        at(100.5)
        run = R.get(eid)
        self.assertEqual((run["status"], run["phase"]), ("approaching", "entry"), run["reason"])
        self.assertEqual(F.C.get_character_pos(name), {"x": 7.7, "z": 7.0})

    def test_e5_boot_shift(self):
        name, target, eid = standing()
        set_alive(101)
        F.MOTION[0] = 131.0
        MO.boot()
        order = order_of(eid)
        print("[E5] +30 on every time, revision 2")
        self.assertEqual(order["revision"], 2)
        for key, value in (("issued_motion_s", 130.0), ("eta_motion_s", 135.700078),
                           ("flip_motion_s", 137.700078), ("deadline_motion_s", 145.700)):
            self.assertAlmostEqual(order[key], value, places=3, msg=key)
        self.assertEqual(order["boot_alive_s"], 101.0)
        self.assertAlmostEqual(R.get(eid)["data"]["eta_s"][name], 135.700078, places=3)
        self.assertEqual(MO.index_get(name)["revision"], 2)
        self.assertAlmostEqual(A.due_in_s(F.game_time()), 4.700078, places=3)

    def test_e6_frozen(self):
        name, target, eid = standing()
        F.W.set_world_frozen(True)
        print("[E6] frozen: nothing flips")
        at(200)
        run = R.get(eid)
        self.assertEqual((run["status"], run["phase"], run["data"]["arrived"]), ("approaching", "", []))

    def test_e7_due_only(self):
        name, target, eid = standing()
        loc = F.W.get_location_by_id(target["location_id"])
        hall = next(r for r in loc["rooms"] if r["id"] == "hall")
        hall["layout"]["props"].append(dict(hall["layout"]["props"][0], id="device2", at=[4, 2]))
        F.W.upsert_location(loc, sync_world=True)
        F.places.invalidate()
        other = F.actor(target["location_id"], at=(1, 8))
        profile = F.C.get_character_profile(other)
        profile.update(height=170, template="run-person")
        F.C.save_character_profile(other, profile)
        F.MOTION[0] = 104.0
        second = S.request(other, dict(target, placement_id="device2"))
        self.assertEqual(second["status"], "approaching", second)
        self.assertEqual(R.get(second["execution_id"])["data"]["plans"][other]["waypoints"], [[1, 8], [4, 4]])
        self.assertAlmostEqual(R.get(second["execution_id"])["data"]["eta_s"][other], 108.071429, places=3)
        counted = []
        print("[E7] due_only steps the one due run")
        with patch.object(A, "_count_ticker", counted.append):
            at(106, due_only=True)
        self.assertEqual(counted.count("advance_validate"), 1)
        self.assertEqual(R.get(eid)["phase"], "entry")
        self.assertEqual(R.get(second["execution_id"])["phase"], "")

    def test_e8_player_deadline(self):
        name, target = seated_o1()
        OR.client(name)    # the NPC is an avatar now: it reports its own arrival
        seen, spy = OR.published()
        with spy:
            answer = S.request(name, target)
            eid = answer["execution_id"]
            self.assertTrue(order_of(eid)["actors"][0]["reports_arrival"])
            print("[E8] no arrival by itself; the deadline fails the run")
            at(110)
            self.assertEqual(R.get(eid)["data"]["arrived"], [])
            at(113.6)
            self.assertEqual(R.get(eid)["status"], "approaching")
            at(113.8)
        run = R.get(eid)
        self.assertEqual((run["status"], run["reason"]), ("failed", "approach_timeout"))
        cancels = [o for o in seen if o["kind"] == "cancel"]
        self.assertEqual(len(cancels), 1, cancels)
        self.assertEqual([a["name"] for a in cancels[0]["actors"]], [name])
        stand = cancels[0]["actors"][0]["stand"]
        # Its order has it at the access by now (17.64 m > L), not on the seat.
        self.assertEqual((stand["x"], stand["z"]), (6.5, 5.25))
        pos = F.C.get_character_pos(name)
        self.assertEqual((pos["x"], pos["z"]), (6.5, 5.25))

    def _cancel_o1_at(self, t):
        name, target = seated_o1()
        seen, spy = OR.published()
        with spy:
            eid = S.request(name, target)["execution_id"]
            self.assertEqual(R.get(eid)["data"]["plans"][name]["waypoints"], [[4, 4], [6.5, 5.25]])
            F.MOTION[0] = float(t)
            A.cancel(name, eid)
        self.assertEqual(R.get(eid)["status"], "cancelled")
        cancels = [o for o in seen if o["kind"] == "cancel"]
        self.assertEqual(len(cancels), 1, cancels)
        stand = cancels[0]["actors"][0]["stand"]
        pos = F.C.get_character_pos(name)
        return (stand["x"], stand["z"]), (pos["x"], pos["z"]), F.C.get_character_profile(name).get("place")

    def test_e17_cancel_on_the_way(self):
        print("[E17] a cancel on the way stands on the plan's polyline, never on the seat")
        stand, pos, place = self._cancel_o1_at(102.5)
        self.assertEqual(stand, (5.63, 4.81))
        self.assertEqual(pos, (5.63, 4.81))
        self.assertIsNone(place)

    def test_e17b_cancel_during_exit(self):
        stand, pos, place = self._cancel_o1_at(100.5)
        self.assertEqual(stand, (4.0, 4.0))
        self.assertEqual(pos, (4.0, 4.0))

    def _moved_on_the_way(self, locked):
        from app.core.keyed_lock import keyed_lock
        name, target = seated_o1()
        seen, spy = OR.published()
        with spy:
            eid = S.request(name, target)["execution_id"]
            F.MOTION[0] = 102.0
            if locked:
                with keyed_lock("character_profile", name):
                    F.C.set_character_pos(name, 2.0, 8.0)
            else:
                F.C.set_character_pos(name, 2.0, 8.0)
        run = R.get(eid)
        self.assertEqual((run["status"], run["reason"]), ("cancelled", "position"))
        pos = F.C.get_character_pos(name)
        self.assertEqual((pos["x"], pos["z"]), (2.0, 8.0))
        return [o for o in seen if o["kind"] == "cancel"]

    def test_e18_own_write_under_lock_wins(self):
        print("[E18] the member's own write ends the run and stays; the walk point does not overwrite it")
        cancels = self._moved_on_the_way(locked=True)
        self.assertEqual(len(cancels), 1, cancels)
        stand = cancels[0]["actors"][0]["stand"]
        self.assertEqual((stand["x"], stand["z"]), (2.0, 8.0))

    def test_e18b_own_write_without_lock(self):
        self._moved_on_the_way(locked=False)

    def test_e19_walk_point_before_issue(self):
        run = dict(data=dict(arrived=[], plans=dict(
            a=dict(waypoints=[[4, 4], [6.5, 5.25]], departure_seat=dict(exit_s=1.2, seat=[4, 2])),
            b=dict(waypoints=[[1, 5], [8, 7]], departure_seat=None))))
        self.assertEqual(A._walk_point(run, "a", 100.0), (4.0, 4.0))
        self.assertIsNone(A._walk_point(run, "b", 100.0))

    def test_e9_boot_migration(self):
        name, target, eid = standing()
        run = R.get(eid)
        run["data"].pop("order")
        with R.transaction() as conn:
            R.save(conn, run)
        profile = F.C.get_character_profile(name)
        profile["journey"] = dict(journey_id="old-approach", execution_kind="prop_action", execution_ref=eid,
                                  approach_target=dict(target, marker_id="body", slot=0),
                                  target="", waypoints=[[1, 5, 0.0], [8, 7, 5.2]], started_at_s=100.0,
                                  speed_m_s=1.4, gait="walk")
        F.C.save_character_profile(name, profile)
        print("[E9] boot cancels the old run and drops the journey")
        MO.boot()
        run = R.get(eid)
        self.assertEqual((run["status"], run["reason"]), ("cancelled", "e3_migration"))
        self.assertNotIn("journey", F.C.get_character_profile(name))
        self.assertEqual(R.claims(), [])

    def test_e13_combined_due_only(self):
        name, target, eid = standing("combined")
        print("[E13] the phase end is due without a full round")
        at(105.8, due_only=True)
        self.assertEqual(R.get(eid)["phase"], "entry")
        at(107.8, due_only=True)
        self.assertEqual((R.get(eid)["status"], R.get(eid)["phase"]), ("active", "prepare"))
        F.set_game_time(F.game_time() + GameDuration.of(seconds=4))
        A.advance(F.game_time(), due_only=True)
        self.assertEqual(R.get(eid)["phase"], "prepare")
        F.set_game_time(F.game_time() + GameDuration.of(seconds=1))
        A.advance(F.game_time(), due_only=True)
        self.assertEqual(R.get(eid)["phase"], "drink")

    def test_e14_restart_in_entry(self):
        name, target, eid = standing()
        at(106)
        self.assertEqual(R.get(eid)["phase"], "entry")
        self.assertAlmostEqual(order_of(eid)["flip_motion_s"], 107.700078, places=3)
        set_alive(106.700)
        F.MOTION[0] = 126.700
        MO.boot()
        print("[E14] activation at the shifted flip 127.700")
        self.assertAlmostEqual(order_of(eid)["flip_motion_s"], 127.700078, places=3)
        at(127.69)
        self.assertEqual(R.get(eid)["status"], "approaching")
        at(127.71)
        self.assertEqual(R.get(eid)["status"], "active")

    def test_e15_boot_idempotent(self):
        name, target, eid = standing()
        set_alive(None)
        F.MOTION[0] = 150.0
        MO.boot()
        print("[E15] missing stamp: shift 0")
        order = order_of(eid)
        self.assertEqual(order["revision"], 1)
        self.assertAlmostEqual(order["eta_motion_s"], 105.700078, places=3)
        set_alive(101)
        F.MOTION[0] = 131.0
        MO.boot()
        self.assertAlmostEqual(order_of(eid)["eta_motion_s"], 135.700078, places=3)
        print("[E15] a second boot against the same stamp shifts nothing")
        set_alive(101)
        F.MOTION[0] = 131.5
        MO.boot()
        order = order_of(eid)
        self.assertEqual(order["revision"], 2)
        self.assertAlmostEqual(order["eta_motion_s"], 135.700078, places=3)

    def test_e16_heartbeat(self):
        writes = []
        real = F.W.set_world_setting

        def record(key, value):
            if key == MO.ALIVE_KEY:
                writes.append((F.MOTION[0], value))
            return real(key, value)
        name, target, pid = S.setup_run()
        with patch.object(F.W, "set_world_setting", record):
            F.MOTION[0] = 100.0
            MO._last_alive[0] = None
            print("[E16] no live order: no write")
            for _ in range(20):
                F.MOTION[0] += 1
                MO.heartbeat()
            self.assertEqual(writes, [])
            first = S.request(name, target)
            self.assertEqual(len(writes), 1)
            self.assertEqual(writes[0][0], 120.0)
            for _ in range(20):
                F.MOTION[0] += 1
                MO.heartbeat()
            self.assertEqual([t for t, _ in writes], [120.0, 125.0, 130.0, 135.0, 140.0])
            A.cancel(name, first["execution_id"])
            for _ in range(60):
                F.MOTION[0] += 1
                MO.heartbeat()
            self.assertEqual(len(writes), 5)
            F.C.set_character_pos(name, 1, 5)
            second = S.request(name, target)
            self.assertEqual(second["status"], "approaching", second)
            self.assertEqual(writes[-1][0], 200.0)
        eta = order_of(second["execution_id"])["eta_motion_s"]
        print("[E16] a boot 2 s later shifts 2 s, not 62")
        F.MOTION[0] = 202.0
        MO.boot()
        self.assertAlmostEqual(order_of(second["execution_id"])["eta_motion_s"] - eta, 2.0, places=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
