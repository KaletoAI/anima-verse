#!/usr/bin/env python3
"""Published motion orders: the worldmap row field, ``GET /play/orders``, the
``orders`` topic and the revisions of a furniture run (plan E3 task 4).

Usage: ./.venv/bin/python scripts/smoke_orders_route.py

Runs on the private furniture fixture of ``smoke_prop_action_runs.py``
(``smoke_prop_action_paths.py`` underneath: temporary storage + instance,
``paths.init(<tmp>)`` before every world import, no server, no real world, no
model call). The HTTP cases use an in-process FastAPI app without lifespan:
the real auth gate, the play router and the prop-action router.

The fixture (hand-built, see ``F.fixture`` / ``S.setup_run``): one location,
rooms "hall" (12 x 10 m) and "adjacent"; the piece "device" at (8, 5) with one
seat marker and the solo action "rest" (pose "sitting", catalog group "seat").
The entry clip "run-enter" lasts 2 s (``duration_s`` 2, authored by
``S.measured_entry``). The NPC starts STANDING at (1, 5). The observer avatar
O stands in the same room at (2, 8) and knows the location. The motion clock
is the fixture's hand-moved ``F.MOTION`` (factor-1 lockstep with game time).

Expectations, by hand from the plan's decisions (E3 decisions 2-6, 18, 19):

[R1] A request of the standing NPC publishes ONE order on its row:
     kind "prop_action", revision 1, status "approaching", steps
     walk -> entry -> loop (no exit: it holds no place). Its times follow the
     journey the run still walks (task 4): issued = started_at_s - exit_s
     (exit_s 0 when standing), eta = started_at_s + the stamp of the last
     waypoint, flip = eta + 2.0 (the catalog length of "run-enter"),
     deadline = eta + max(10, 0.5 * (eta - issued)). entry and loop name the
     pose "sitting" of kind "seat"; the entry's nominal_s is 2.0.
[R4c] O is no participant: the row's order has no ``awaits``, its target
     neither ``execution_id`` nor ``slot``, its actor no ``role``; the
     movement fields (order_id, times, sequence, access, anchor) are there.
[R2] ``GET /play/orders?since=0`` lists that order (same order_id, seq >= 1)
     with ``motion_now`` = the fixture clock; ``since=<its seq>`` lists none.
[R3] Ticking until the run's phase is "entry" (``_begin_entry``): revision 2,
     status "entering", flip = entry_started_s + 2.0, seq above the R2 seq.
     Two seconds more: revision 3, status "active".
[R4] O in another location (it knows the NPC's location, so the NPC's ROW is
     still not the question): no order in the route; O in the adjacent room
     of the same location: the NPC's row is there, without ``order``, and the
     route lists nothing.
[R4b] Out in the open (no location), decision 4: an order of an NPC 3000 m
     away from O (far beyond the sight range) is neither on a row nor in the
     route; the same NPC 3 m beside O (within sight, on the ground O's near
     view covers) IS in the route — the rule is sight, not "never outdoors".
     The same NPC 3000 m away but with a journey to a location (the one row
     exception of ``_visible_row``) still stays out of the route: it is not in
     O's sight.
[R5] The publication pushes ``orders`` to AtLocation(<the location>) and
     Avatars((npc,)) — never Everyone (recorded through a patched
     ``sync_topics.notify``).
[R6] ``GET /play/orders`` without a session: 401 (default-deny gate).
[R7] A SEATED NPC (active in "rest" on "device") asks for "rest" on a second
     placement "device2" at (4, 2): the new order's steps are exit -> walk ->
     entry -> loop; the exit names the pose "sitting" of kind "seat" and its
     nominal_s is the exit clip "run-exit" (authored sitting -> walking,
     duration_s 1.5) = 1.5; the plan holds ``departure_seat`` with that kind
     (captured by ``_start`` BEFORE the journey releases the seat), and after
     the start the NPC holds no place any more. The replaced run publishes
     NO cancel (the NPC kept its seat for the departure).
[R8] A combined run (phases "prepare" 5 s, "drink" 5 s of game time): once
     active, its order carries phase "prepare"; after 5 more game seconds the
     next revision carries phase "drink" (revision + 1).
[R9] The normal end of the active solo run (cancel by the actor, no follow
     pose for "sitting"): exactly one NEW order of kind "cancel" (another
     order_id) with the one actor and its ``stand`` = the point it stands on
     after the release; the run's own order keeps its revision (no "ended"
     revision of a prop_action, decision 19) and the row now carries the
     cancel.
[R9b] Follow pose (``smoke_follow_pose`` [3]): the pair on two slots ends;
     both stay seated in a follow run each — no cancel at all, and each
     follow run's order begins WITHOUT exit (entry -> loop).
[R9c] Switch in place (``smoke_prop_action_switch`` [8]): the consent carries,
     the new pair run is active at once; no cancel for either member, and
     its order's sequences have no exit.
[R9d] One shared seat (``smoke_follow_pose`` [4]): the first name keeps the
     seat in a follow run, the second stands up: exactly one cancel, with
     exactly that one actor and its stand point.
[R10] The worldmap root carries ``order_seq`` >= the seq of every row order
     and ``motion_now``; an order published WHILE the rows are built (a patch
     publishes on the first row) is either on its row or has a seq above
     ``order_seq`` (read before the rows).
[R11] The avatar's own request answer carries ``order`` (the avatar is a
     participant: the whole order, with ``execution_id``) beside ``motion``.
"""
import json
import math
import os
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_prop_action_runs as S                                       # noqa: E402
import smoke_follow_pose as FP                                           # noqa: E402

F, A, R = S.F, S.A, S.R
from app.core import paths                                               # noqa: E402
paths.init(F.ROOT / "world")    # the fixture's private world, named here once more
from fastapi import FastAPI                                              # noqa: E402
from fastapi.testclient import TestClient                                # noqa: E402
from app.core import auth_dependency, hooks, sessions, sync_topics, users  # noqa: E402
from app.core import motion_orders as MO                                 # noqa: E402
from app.core.game_time import GameDuration                              # noqa: E402

TARGET_KEYS = ("location_id", "room_id", "placement_id", "variant_uid")


def app():
    instance = FastAPI()
    instance.middleware("http")(auth_dependency.auth_gate_middleware)
    instance.middleware("http")(auth_dependency.user_context_middleware)
    from app.routes.play import router as play_router
    from app.routes.prop_actions import router as prop_router
    instance.include_router(prop_router)
    instance.include_router(play_router)
    return instance


def client(name):
    uid = users.create_user("orders-" + os.urandom(6).hex(), "private-fixture-only",
                            role="user", allowed_characters=[name])
    users.update_user(uid, settings={"active_character": name})
    result = TestClient(app())
    result.cookies.set(sessions.SESSION_COOKIE_NAME, sessions.create_session(uid))
    return result


def observer(location_id, room="hall", at=(2, 8)):
    name = F.actor(location_id, room=room, at=at)
    F.C.add_known_location(name, location_id)
    return name


def rows(http):
    answer = http.get("/play/worldmap")
    assert answer.status_code == 200, answer.text
    payload = answer.json()
    return payload, {row["name"]: row for row in payload["characters"]}


def steps(order, i=0):
    return [s["step"] for s in order["actors"][i]["sequence"]]


def until_active(eid, seconds=2, rounds=60):
    for _ in range(rounds):
        if R.get(eid)["status"] == "active":
            return
        S.tick(seconds)
    raise AssertionError(R.get(eid))


def published():
    """Record every MO.publish (the published order) while active."""
    seen = []
    real = MO.publish

    def spy(order, *, names, locations):
        out = real(order, names=names, locations=locations)
        seen.append(out)
        return out
    return seen, patch.object(MO, "publish", spy)


class Orders(unittest.TestCase):
    def setUp(self):
        self.name, self.target, self.pid = S.setup_run()
        MO.boot()

    def tearDown(self):
        F.W.set_world_frozen(False)
        F.set_game_factor(0)
        for run in R.live_runs():
            A.cancel(run["actor"], run["execution_id"])
        F.assert_no_external_work()

    def journey(self, name):
        return F.C.get_character_profile(name)["journey"]

    def test_r1_r2_r3_r4c_r5_npc_approach(self):
        obs = observer(self.target["location_id"])
        http = client(obs)
        notified = []
        real_notify = sync_topics.notify

        def record(topics, *, to):
            notified.append((topics, to))
            return real_notify(topics, to=to)
        with patch.object(sync_topics, "notify", record):
            answer = S.request(self.name, self.target)
        self.assertEqual(answer["status"], "approaching", answer)
        eid = answer["execution_id"]
        journey = self.journey(self.name)

        print("[R1] the row carries the order")
        payload, by_name = rows(http)
        order = by_name[self.name]["order"]
        self.assertEqual((order["kind"], order["revision"], order["status"]),
                         ("prop_action", 1, "approaching"))
        self.assertEqual(steps(order), ["walk", "entry", "loop"])
        started = float(journey["started_at_s"])
        exit_s = float(journey.get("exit_s", 0.0))
        eta = started + float(journey["waypoints"][-1][2])
        issued = started - exit_s
        self.assertAlmostEqual(order["issued_motion_s"], issued, places=3)
        self.assertAlmostEqual(order["eta_motion_s"], eta, places=3)
        self.assertAlmostEqual(order["flip_motion_s"], eta + 2.0, places=3)
        self.assertAlmostEqual(order["deadline_motion_s"], eta + max(10.0, .5 * (eta - issued)), places=3)
        entry, loop = order["actors"][0]["sequence"][1:]
        self.assertEqual((entry["pose_kind"], entry["pose_key"], entry["nominal_s"]), ("seat", "sitting", 2.0))
        self.assertEqual((loop["pose_kind"], loop["pose_key"]), ("seat", "sitting"))

        print("[R4c] a non-participant sees the movement fields only")
        self.assertNotIn("awaits", order)
        self.assertNotIn("execution_id", order["target"])
        self.assertNotIn("slot", order["target"])
        self.assertNotIn("role", order["actors"][0])
        for key in ("order_id", "issued_motion_s", "eta_motion_s", "flip_motion_s", "target"):
            self.assertIn(key, order)
        for key in ("start", "access", "anchor", "sequence", "entry_mode"):
            self.assertIn(key, order["actors"][0])
        full = R.get(eid)["data"]["order"]
        self.assertEqual(full["target"]["execution_id"], eid)
        self.assertEqual(full["order_id"], order["order_id"])

        print("[R5] the push goes to the location and the participant, never Everyone")
        pushes = [to for topics, to in notified if "orders" in ((topics,) if isinstance(topics, str) else topics)]
        self.assertEqual(len(pushes), 1, notified)
        recipients = list(pushes[0]) if not isinstance(pushes[0], sync_topics._RECIPIENT_TYPES) else [pushes[0]]
        self.assertIn(sync_topics.AtLocation(self.target["location_id"]), recipients)
        self.assertIn(sync_topics.Avatars((self.name,)), recipients)
        self.assertFalse([r for r in recipients if isinstance(r, sync_topics.Everyone)])

        print("[R2] GET /play/orders")
        listed = http.get("/play/orders", params={"since": 0}).json()
        ids = [o["order_id"] for o in listed["orders"]]
        self.assertEqual(ids, [order["order_id"]])
        seq = listed["orders"][0]["seq"]
        self.assertGreaterEqual(seq, 1)
        self.assertGreaterEqual(listed["seq"], seq)
        self.assertAlmostEqual(listed["motion_now"], F.MOTION[0], places=3)
        self.assertEqual(http.get("/play/orders", params={"since": seq}).json()["orders"], [])

        print("[R3] revisions at the entry and at the activation")
        for _ in range(60):
            if R.get(eid)["phase"] == "entry":
                break
            S.tick(1)
        run = R.get(eid)
        self.assertEqual(run["phase"], "entry", run)
        now = MO.index_get(self.name)
        self.assertEqual((now["revision"], now["status"]), (2, "entering"))
        self.assertAlmostEqual(now["flip_motion_s"], float(run["data"]["entry_started_s"]) + 2.0, places=3)
        self.assertGreater(now["seq"], seq)
        S.tick(2)
        S.tick(1)
        self.assertEqual(R.get(eid)["status"], "active")
        now = MO.index_get(self.name)
        self.assertEqual((now["revision"], now["status"]), (3, "active"))

    def test_r4_other_location_and_other_room(self):
        far = F.W.add_location("Far place", "Throwaway", rooms=[{
            "id": "yard", "name": "Yard", "layout": {"x": 0, "y": 0, "w": 6, "d": 6}}])
        far.update(pos_x=200, pos_z=0, map3d={"plan_width_m": 10,
                   "boundary": [[-5, -5], [5, -5], [5, 5], [-5, 5]]})
        F.W.upsert_location(far, sync_world=True)
        away = observer(far["id"], room="yard", at=(200, 0))
        F.C.add_known_location(away, self.target["location_id"])
        beside = observer(self.target["location_id"], room="adjacent", at=(13.5, 5))
        self.assertEqual(S.request(self.name, self.target)["status"], "approaching")
        print("[R4] another location: nothing")
        self.assertEqual(client(away).get("/play/orders", params={"since": 0}).json()["orders"], [])
        print("[R4] the adjacent room: the row without order, nothing in the route")
        http = client(beside)
        _payload, by_name = rows(http)
        self.assertIn(self.name, by_name)
        self.assertNotIn("order", by_name[self.name])
        self.assertEqual(http.get("/play/orders", params={"since": 0}).json()["orders"], [])

    def test_r4b_out_in_the_open(self):
        npc = self.name
        obs = F.actor(self.target["location_id"], at=(2, 8))
        for who, x in ((obs, 1000.0), (npc, 4000.0)):
            F.C.save_character_current_location(who, "")
            F.C.set_character_pos(who, x, 1000.0)
        order = MO.new_order("cancel", issued_s=F.MOTION[0], eta_s=F.MOTION[0], flip_s=F.MOTION[0] + 1,
                             deadline_s=F.MOTION[0] + 10, target=dict(location_id="", room_id="", level=0),
                             speed_m_s=0.0, gait="walk", status="ended",
                             actors=[MO.actor_row(npc, "actor", "", 170, dict(x=4000, y=0, z=1000, yaw=0,
                                                                                  room_id="", level=0))])
        MO.publish(order, names=[npc], locations=[""])
        http = client(obs)
        print("[R4b] out of sight: neither row nor route")
        _payload, by_name = rows(http)
        self.assertNotIn(npc, by_name)
        self.assertEqual(http.get("/play/orders", params={"since": 0}).json()["orders"], [])
        print("[R4b] a journey to a location is no sight line for the order")
        profile = F.C.get_character_profile(npc)
        with patch.object(F.E, "get_journey", lambda name, profile=None: (
                {"target": self.target["location_id"], "waypoints": [[4000, 1000, 0]], "started_at_s": 0}
                if name == npc else None)):
            self.assertEqual(http.get("/play/orders", params={"since": 0}).json()["orders"], [])
        print("[R4b] within sight: listed")
        F.C.set_character_pos(npc, 1003.0, 1000.0)
        listed = http.get("/play/orders", params={"since": 0}).json()["orders"]
        self.assertEqual([o["order_id"] for o in listed], [order["order_id"]])

    def test_r6_no_session(self):
        print("[R6] no session: 401")
        self.assertEqual(TestClient(app()).get("/play/orders", params={"since": 0}).status_code, 401)

    def test_r7_seated_npc_departs_with_exit(self):
        S.clips._write_world_transitions([
            {"from": "walking", "to": "sitting", "kind": "run-enter", "accel": 0},
            {"from": "sitting", "to": "walking", "kind": "run-exit", "accel": 0}])
        directory = F.ROOT / "clips"
        (directory / "run-exit.fbx").write_bytes(b"private deterministic exit fixture")
        (directory / "run-exit.json").write_text(json.dumps(dict(kind="run-exit", duration_s=1.5, loop=False)))
        S.clips._clear_entries_cache()
        first = S.request(self.name, self.target)["execution_id"]
        until_active(first)
        self.assertIsNotNone(F.C.get_character_profile(self.name).get("place"))
        loc = F.W.get_location_by_id(self.target["location_id"])
        hall = next(r for r in loc["rooms"] if r["id"] == "hall")
        device = next(p for p in hall["layout"]["props"] if p["id"] == "device")
        hall["layout"]["props"].append(dict(device, id="device2", at=[4, 2]))
        F.W.upsert_location(loc, sync_world=True)
        F.places.invalidate()
        other = dict(self.target, placement_id="device2")
        seen, spy = published()
        with spy:
            answer = S.request(self.name, other)
        self.assertEqual(answer["status"], "approaching", answer)
        print("[R7] exit -> walk -> entry -> loop, the seat is free after the start")
        run = R.get(answer["execution_id"])
        order = run["data"]["order"]
        self.assertEqual(steps(order), ["exit", "walk", "entry", "loop"])
        exit_step = order["actors"][0]["sequence"][0]
        self.assertEqual((exit_step["pose_kind"], exit_step["pose_key"], exit_step["nominal_s"]),
                         ("seat", "sitting", 1.5))
        self.assertEqual(run["data"]["plans"][self.name]["departure_seat"]["pose_kind"], "seat")
        self.assertIsNone(F.C.get_character_profile(self.name).get("place"))
        self.assertEqual([o["kind"] for o in seen], ["prop_action"])
        self.assertEqual(R.get(first)["status"], "completed")

    def test_r8_combined_phase_revision(self):
        name, target, _pid = S.setup_run("combined")
        MO.boot()
        eid = S.request(name, target)["execution_id"]
        until_active(eid, seconds=1)
        order = MO.index_get(name)
        self.assertEqual(order["phase"], "prepare")
        S.tick(5)
        S.tick(1)
        print("[R8] the phase change is a revision")
        self.assertEqual(R.get(eid)["phase"], "drink")
        after = MO.index_get(name)
        self.assertEqual((after["phase"], after["revision"]), ("drink", order["revision"] + 1))

    def test_r9_finish_publishes_a_cancel_for_who_stood_up(self):
        eid = S.request(self.name, self.target)["execution_id"]
        until_active(eid)
        before = R.get(eid)["data"]["order"]
        seen, spy = published()
        with spy:
            A.cancel(self.name, eid)
        print("[R9] one cancel with the stand point, no ended revision")
        self.assertEqual([o["kind"] for o in seen], ["cancel"])
        cancel = seen[0]
        self.assertNotEqual(cancel["order_id"], before["order_id"])
        self.assertEqual([a["name"] for a in cancel["actors"]], [self.name])
        pos = F.C.get_character_pos(self.name)
        stand = cancel["actors"][0]["stand"]
        self.assertAlmostEqual(stand["x"], pos["x"], places=3)
        self.assertAlmostEqual(stand["z"], pos["z"], places=3)
        self.assertEqual(steps(cancel), ["exit"])
        self.assertEqual(R.get(eid)["data"]["order"]["revision"], before["revision"])
        self.assertEqual(MO.index_get(self.name)["order_id"], cancel["order_id"])

    def test_r9b_follow_pose_publishes_no_cancel(self):
        name, partner, _target, _pid, run = FP.active_pair()
        MO.boot()
        seen, spy = published()
        with spy:
            A.cancel(name, run["execution_id"])
        print("[R9b] follow runs: no cancel, no exit")
        self.assertFalse([o for o in seen if o["kind"] == "cancel"], seen)
        follows = FP.follow_runs(run["execution_id"])
        self.assertEqual({f["actor"] for f in follows}, {name, partner})
        for follow in follows:
            order = R.get(follow["execution_id"])["data"]["order"]
            self.assertNotIn("exit", steps(order))
            self.assertEqual(steps(order)[0], "entry")

    def test_r9c_switch_in_place_publishes_no_exit(self):
        name, partner, target, pid = S.authored_pair()
        doc = F.props.read_sidecar(pid)
        again = deepcopy(doc["actions"][0])
        again.update(id="share-again", name="share-again")
        doc["actions"].append(again)
        F.props._write_sidecar(pid, doc)
        revision = F.props.get_prop(pid)["revision"]
        short = {k: target[k] for k in TARGET_KEYS}
        hooks.register_provider("pair_reaction", lambda **kw: None, owner="smoke.orders")
        self.addCleanup(hooks._providers.pop, "pair_reaction", None)
        r1 = A.request(name, short, "rest", revision, [partner])["execution_id"]
        A.respond(partner, r1, True)
        S.tick(30)
        S.tick(2)
        S.tick(2)
        self.assertEqual(R.get(r1)["status"], "active")
        seen, spy = published()
        with spy:
            r2 = A.request(name, short, "share-again", revision, [partner])
        self.assertEqual(r2["status"], "active", r2)
        print("[R9c] the switch: no cancel, no exit")
        self.assertFalse([o for o in seen if o["kind"] == "cancel"], seen)
        order = R.get(r2["execution_id"])["data"]["order"]
        for i in range(2):
            self.assertNotIn("exit", steps(order, i))

    def test_r9d_one_seat_one_cancel(self):
        name, partner, _target, _pid, run = FP.active_pair(shared=True)
        MO.boot()
        seen, spy = published()
        with spy:
            A.cancel(partner, run["execution_id"])
        first, second = sorted((name, partner))
        print("[R9d] one cancel, for the one who stood up")
        cancels = [o for o in seen if o["kind"] == "cancel"]
        self.assertEqual(len(cancels), 1, seen)
        self.assertEqual([a["name"] for a in cancels[0]["actors"]], [second])
        pos = F.C.get_character_pos(second)
        self.assertAlmostEqual(cancels[0]["actors"][0]["stand"]["x"], pos["x"], places=3)
        self.assertAlmostEqual(cancels[0]["actors"][0]["stand"]["z"], pos["z"], places=3)

    def test_r10_order_seq_read_before_the_rows(self):
        obs = observer(self.target["location_id"])
        http = client(obs)
        S.request(self.name, self.target)
        payload, by_name = rows(http)
        print("[R10] order_seq covers every row order")
        self.assertIn("motion_now", payload)
        self.assertGreaterEqual(payload["order_seq"], by_name[self.name]["order"]["seq"])
        late = []
        real = MO.index_get

        def publishing(name):
            if not late:
                order = MO.new_order("cancel", issued_s=F.MOTION[0], eta_s=F.MOTION[0],
                                     flip_s=F.MOTION[0] + 1, deadline_s=F.MOTION[0] + 10,
                                     target=dict(location_id=self.target["location_id"], room_id="hall"),
                                     speed_m_s=0.0, gait="walk", status="ended",
                                     actors=[MO.actor_row(self.name, "actor", "", 170,
                                                          dict(x=1, y=0, z=5, yaw=0, room_id="hall", level=0))])
                late.append(MO.publish(order, names=[self.name], locations=[self.target["location_id"]]))
            return real(name)
        with patch.object(MO, "index_get", publishing):
            payload, by_name = rows(http)
        on_row = (by_name[self.name].get("order") or {}).get("order_id") == late[0]["order_id"]
        self.assertTrue(on_row or late[0]["seq"] > payload["order_seq"], (payload["order_seq"], late[0]["seq"]))

    def test_r11_own_request_answer_carries_the_order(self):
        from app.routes import prop_actions as routes
        result = S.request(self.name, self.target)
        print("[R11] the participant's answer carries the whole order")
        answer = routes._with_motion(self.name, result)
        self.assertIn("motion", answer)
        self.assertEqual(answer["order"]["target"]["execution_id"], result["execution_id"])
        self.assertEqual([a["name"] for a in answer["order"]["actors"]], [self.name])


if __name__ == "__main__":
    unittest.main(verbosity=1)
