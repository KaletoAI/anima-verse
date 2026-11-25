#!/usr/bin/env python3
"""Walk orders: room changes and strolls (plan E3 Task 9, decisions 9-11, 20).

Usage: ./.venv/bin/python scripts/smoke_walk_orders.py

Runs on the private fixture of ``smoke_prop_action_runs.py`` (temporary storage
and instance, ``paths.init(<tmp>)`` before every world import, no server, no
model call). The motion clock is the fixture's hand-set ``F.MOTION``. Speed 1.4
m/s (``travel.DEFAULT_SPEED_M_S``), START_SLACK_S 0.5, entry 0 (a walk has
none), so eta = flip = issued + exit + L / 1.4 + 0.5; stored seconds carry 3
decimals.

THE ORDERS WORLD (native/fixtures/README.md "Orders world", Task 1 O2): the
location "Navhaus" at world (100, 0), yaw 0, rooms r-a (storey 0, x 94..100),
r-b (storey 0, x 100..106), r-up (storey 1, x 100..106), all z -4..4. In r-a
a rug (2 x 1.5 x 0.02 m, a walkable floor piece: height under the blocker
minimum) at (97, 2) and an armchair (0.8 x 0.8 x 0.9 m) at (97, -2). The
scene recipe the room chain reads is the client fixture
native/fixtures/orders/scene_loc-nav.json (doorway D0 at local (0, 2)
between r-a and r-b, the outside door D1, stairs foot (1, 0, -3.3) head
(4.5, 3, -3.3), storey 1 at floor_y 3), served through
``scene_recipe.scene_for_location`` — the real compose of the authored rooms
builds the walls and the room geometry of r-a the stroll reads.

[W1]  An NPC in r-a at (97, -1) changes into r-up through
      ``movement_authority.move_character`` (a decision point: start read
      before the setter). The stand point the room hands out is pinned to the
      O2 goal (104, 2) (``room_stand.free_stand_point`` patched for r-up), so
      the estimate is Task 1 O2: chain r-a -D0 (100, 2)-> r-b -stairs-> r-up,
        horizontal (97,-1)->(100,2) 4.2426407 + (100,2)->(101,-3.3) 5.3935146
                   + (104.5,-3.3)->(104,2) 5.3235327 = 14.9596880 * 1.3
                   = 19.4475944
        flight sqrt(3.5^2 + 3^2) = 4.6097722
        L = 24.0573666, exit 0 -> eta - issued = 24.0573666 / 1.4 + 0.5
          = 17.683833 (the plan's 17.683834 summed rounded legs, Task 1).
      Room r-up and position (104, 2) are written at once (decision 10). The
      SAME room change straight through ``save_character_current_room`` (the
      admin/teleport path) publishes no walk (review W6).
[W2]  A stroll inside r-a from (97, -1) to (98, 2) (the rug is no obstacle,
      the armchair's box ends at z -1.6, its keep-out at -1.3 < -1): the
      visibility path is the straight line, L = sqrt(1^2 + 3^2) = 3.162278,
      eta - issued = 3.162278 / 1.4 + 0.5 = 2.258770 + 0.5 = 2.758770. The
      position stays (97, -1) until the flip, then (98, 2); the flip
      publishes the revision ``ended`` and no ``cancel`` order, and runs no
      ``cancel_for``, no ``_interrupt_prop_action``, no ``end_interaction``.
[W2b] The NPC holds a plain seat (``place`` set, pose_key "sitting", no run);
      sitting -> walking plays "run-exit" of 1.2 s: eta - issued = 1.2 +
      2.258770 + 0.5 = 3.958770, the sequence starts with exit (1.2 s); right
      after the order and after the flip ``place`` is None and pose_key "".
[W2c] The NPC holds the pose "sitting" WITHOUT a place (fix round 1): the
      same exit 1.2 s (eta - issued = 3.958770), and right after the order
      pose_key is "" (the held pose is let go like a plain seat).
[W2d] The profile write of a stroll fails (save_character_profile -> False,
      fix round 1): (None, "write_failed"), and the walk already published is
      taken back by a ``cancel`` order (no client keeps playing it).
[W3]  A stroll in the open (from (110, 10) to (115, 14), both outside every
      outline): ``hint_route`` has at least 2 points, starts at the start and
      ends at the target, and L = the length of that polyline:
      eta - issued = L / 1.4 + 0.5 (within the 3-decimal rounding).
[W4]  A party follower -> (None, "party_follower").
[W5]  W2 issued at 100 (flip 102.759), motion_alive_s 101, boot at 131:
      shift 30 -> issued 130, eta = flip 132.759, revision 2, boot_alive_s
      101; walk_due_in_s() = 1.759 > 0 (nothing due at once), walking True.
[W5b] W2, then the walker goes dormant (status "dormant", out of the world)
      before the boot: the boot drops its walk field (fix round 1) and files
      nothing in the index.
[W6]  ``nav_grid.route`` raises AssertionError: W1 and W2 still issue their
      walks (decision 11: no server path search inside a location).
[W7]  ``interaction_engine._walk_to_partner`` (two NPCs in the open, 4 m
      apart) still starts a point journey, no walk order (review W7).
[W8]  A teleport (an anchor spell, ``spell_engine.execute_cast``) of a walker
      -> a ``cancel`` order with snap true; the flip writes nothing.
[W9]  W2 at 100, now 101: ``travel_engine._next_beat_s()`` <= 102.759 - 101
      + 0.1 = 1.859.
[W10] W2, then ``set_character_pos(96, 0)`` at 101: a cancel order (stand
      (96, 0)); the flip at 103 writes nothing and interrupts nothing.
[W11] A stroll in the hall of the furniture fixture (1, 5) -> (3, 5), flip
      50 + 2 / 1.4 + 0.5 = 51.929; a prop-action request at 51: the run
      survives the flip at 52, the position stays (1, 5).
[W12] W2, then an overland journey (``start_journey`` to a second placed
      location) at 101: the walk is cancelled, the flip writes nothing, the
      journey lives.
[W13] While a stroll walk lives: ``npc_actions.candidates`` skips the NPC (it
      is a candidate without one), ``npc_scenes._free`` False (True without),
      ``check_can_pair`` "... is travelling" (a room-change walk does not
      block a pair: its room and point are written), ``npc_spawn._settle_wanderer``
      stops at the road check (it never asks ``_in_chat``),
      ``linked_characters.swap_refusal`` "journey"; the activity condition
      "travelling" passes during a stroll and during a room-change walk and
      fails again after their flips (decision 20, third review 4).
[W14] W2, then ``start_interaction`` of a free pair at 101: the walk is
      cancelled, the flip writes nothing, the interaction lives.
[W15] A stroll in the open, then ``_walk_to_partner``: the point journey
      lives, the walk is cancelled, the flip writes nothing.
[W16] A force rule (``periodic_jobs._sub_force_rules``, home room r-b in the
      same location) issues a walk; ``belonging._place`` and the scheduler's
      arrival room (the plain setter) issue none.
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
from app.core import interaction_engine as IE                            # noqa: E402
from app.core import motion_orders as MO                                 # noqa: E402
from app.core import nav_grid, room_stand, scene_recipe                   # noqa: E402
from app.core import travel_engine as T                                  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
RECIPE = json.loads((REPO / "native/fixtures/orders/scene_loc-nav.json").read_text())
_REAL_SCENE = scene_recipe.scene_for_location
_REAL_STAND = room_stand.free_stand_point


def _scene(location, location_id, fingerprint=""):
    if (location or {}).get("name") == "Navhaus":
        return RECIPE
    return _REAL_SCENE(location, location_id, fingerprint)


scene_recipe.scene_for_location = _scene
W1_ETA = 24.0573666 / 1.4 + 0.5          # 17.683833
W2_ETA = math.sqrt(10) / 1.4 + 0.5       # 2.758770


def nav_world():
    """The orders world (docstring); returns the location id."""
    for name in F.C.list_available_characters():
        F.C.delete_character(name)
    for loc in F.W.list_locations():
        F.W.delete_location(loc["id"])
    rug = F.furniture_prop("Rug", width=2, depth=1.5, height=0.02)
    chair = F.furniture_prop("Armchair", width=0.8, depth=0.8, height=0.9)
    loc = F.W.add_location("Navhaus", "orders fixture", rooms=[
        # Prop "at" is room-relative: r-a's corner (-6, -4) + (3, 6) = (-3, 2) local = (97, 2) world.
        {"id": "r-a", "name": "West", "layout": {
            "x": -6, "y": -4, "w": 6, "d": 8, "level": 0,
            "props": [{"id": "rug", "prop_id": rug, "at": [3, 6], "yaw": 0},
                      {"id": "armchair", "prop_id": chair, "at": [3, 2], "yaw": 0}],
            "openings": [{"edge": 0, "at": .5, "width_m": .9, "type": "door"}]}},
        {"id": "r-b", "name": "East", "layout": {
            "x": 0, "y": -4, "w": 6, "d": 8, "level": 0,
            "openings": [{"edge": 3, "at": .25, "width_m": .9, "type": "door", "to": "r-a"}]}},
        {"id": "r-up", "name": "Loft", "layout": {"x": 0, "y": -4, "w": 6, "d": 8, "level": 1}}])
    loc.update(pos_x=100, pos_z=0, map3d={
        "plan_width_m": 12, "storey_m": 3, "boundary": [[-6, -7], [6, -7], [6, 4], [-6, 4]],
        "stairs": [{"at": [1.5, -3.3], "from_level": 0, "dir_deg": 90}]})
    F.W.upsert_location(loc, sync_world=True)
    F.places.invalidate()
    return loc["id"]


SERIAL = [0]


def npc(at, loc_id="", room=""):
    SERIAL[0] += 1
    name = f"walker_{SERIAL[0]}"
    assert F.C.save_character_profile(name, {"character_name": name, "template": "npc-temporary"},
                                      create_new=True)
    if loc_id:
        F.C.save_character_current_location(name, loc_id)
        F.C.save_character_current_room(name, room)
    F.C.set_character_pos(name, *at)
    return name


def pos(name):
    p = F.C.get_character_pos(name)
    return (p["x"], p["z"])


def stroll(name, x=98.0, z=2.0, room="r-a"):
    order, reason = MO.issue_walk(name, x, z, room_id=room)
    assert reason == "ok", reason
    return order


def kind_of(name):
    order = MO.index_get(name)
    return (order or {}).get("kind")


class Recorder:
    """Counts the calls a settle must not make (second review N3)."""

    def __enter__(self):
        from app.models import character as C
        self.calls = []
        real_cancel, real_interrupt, real_end = MO.cancel_for, C._interrupt_prop_action, IE.end_interaction
        self._patches = [
            patch.object(MO, "cancel_for", lambda *a, **k: (self.calls.append("cancel_for"), real_cancel(*a, **k))[1]),
            patch.object(C, "_interrupt_prop_action",
                         lambda *a, **k: (self.calls.append("interrupt"), real_interrupt(*a, **k))[1]),
            patch.object(IE, "end_interaction",
                         lambda *a, **k: (self.calls.append("end_interaction"), real_end(*a, **k))[1]),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


def pin_up_stand(loc, room, start, **kw):
    return (104.0, 2.0) if room == "r-up" else _REAL_STAND(loc, room, start, **kw)


class Walks(unittest.TestCase):
    def setUp(self):
        F.MOTION[0] = 100.0
        MO.boot()
        self.loc = nav_world()

    def tearDown(self):
        F.W.set_world_frozen(False)
        F.set_game_factor(0)
        for run in R.live_runs():
            A.cancel(run["actor"], run["execution_id"])
        F.assert_no_external_work()

    def room_change(self, name):
        from app.core.movement_authority import move_character
        with patch.object(room_stand, "free_stand_point", pin_up_stand):
            return move_character(name, self.loc, "r-up", timed=True)

    def test_w1_room_change_at_the_decision_point(self):
        name = npc((97, -1), self.loc, "r-a")
        result = self.room_change(name)
        self.assertEqual(result["status"], "arrived", result)
        order = MO.index_get(name)
        self.assertEqual(order["kind"], "walk")
        self.assertAlmostEqual(order["eta_motion_s"] - order["issued_motion_s"], W1_ETA, delta=6e-4)
        self.assertEqual(order["flip_motion_s"], order["eta_motion_s"])
        self.assertEqual((order["target"]["room_id"], order["target"]["level"]), ("r-up", 1))
        self.assertEqual(order["actors"][0]["start"]["room_id"], "r-a")
        self.assertEqual(F.C.get_character_current_room(name), "r-up")
        self.assertEqual(pos(name), (104.0, 2.0))
        # The flip writes nothing for a room change (decision 10).
        F.MOTION[0] = 118.0
        with Recorder() as rec:
            self.assertEqual(MO.settle_due(), 1)
        self.assertEqual(rec.calls, [])
        self.assertEqual(pos(name), (104.0, 2.0))
        self.assertEqual(MO.index_get(name)["status"], "ended")
        # The plain setter (admin, teleport, spawn): no walk.
        other = npc((97, -1), self.loc, "r-a")
        with patch.object(room_stand, "free_stand_point", pin_up_stand):
            F.C.save_character_current_room(other, "r-up")
        self.assertEqual(F.C.get_character_current_room(other), "r-up")
        self.assertIsNone(MO.index_get(other))

    def test_w2_stroll_inside_the_room(self):
        name = npc((97, -1), self.loc, "r-a")
        order = stroll(name)
        self.assertAlmostEqual(order["eta_motion_s"] - 100.0, W2_ETA, delta=6e-4)
        self.assertEqual(order["hint_route"], [])
        self.assertTrue(MO.walking(name))
        F.MOTION[0] = 102.7
        self.assertEqual(MO.settle_due(), 0)
        self.assertEqual(pos(name), (97.0, -1.0))
        F.MOTION[0] = 102.76
        with Recorder() as rec:
            self.assertEqual(MO.settle_due(), 1)
        self.assertEqual(rec.calls, [])
        self.assertEqual(pos(name), (98.0, 2.0))
        self.assertEqual(F.C.get_character_current_room(name), "r-a")
        ended = MO.index_get(name)
        self.assertEqual((ended["kind"], ended["status"], ended["revision"]), ("walk", "ended", 2))
        self.assertFalse(MO.walking(name))
        self.assertNotIn("order", F.C.get_character_profile(name))

    def test_w2b_plain_seat_is_freed(self):
        clips = F.ROOT / "clips"
        (clips / "run-exit.fbx").write_bytes(b"private deterministic exit fixture")
        (clips / "run-exit.json").write_text(json.dumps(dict(kind="run-exit", duration_s=1.2, loop=False)))
        S.clips._write_world_transitions([{"from": "sitting", "to": "walking", "kind": "run-exit", "accel": 0}])
        try:
            name = npc((97, -1), self.loc, "r-a")
            profile = F.C.get_character_profile(name)
            profile.update(place={"id": "armchair-seat", "slot": 0, "room_id": "r-a"}, pose_key="sitting")
            self.assertTrue(F.C.save_character_profile(name, profile))
            order = stroll(name)
            self.assertAlmostEqual(order["eta_motion_s"] - 100.0, 1.2 + W2_ETA, delta=6e-4)
            first = order["actors"][0]["sequence"][0]
            self.assertEqual((first["step"], first["nominal_s"]), ("exit", 1.2))
            profile = F.C.get_character_profile(name)
            self.assertEqual((profile.get("place"), profile.get("pose_key")), (None, ""))
            F.MOTION[0] = 104.0
            self.assertEqual(MO.settle_due(), 1)
            profile = F.C.get_character_profile(name)
            self.assertEqual((profile.get("place"), profile.get("pose_key")), (None, ""))
            self.assertEqual(pos(name), (98.0, 2.0))
        finally:
            S.clips._write_world_transitions([])

    def test_w2c_sitting_pose_without_place_is_let_go(self):
        clips = F.ROOT / "clips"
        (clips / "run-exit.fbx").write_bytes(b"private deterministic exit fixture")
        (clips / "run-exit.json").write_text(json.dumps(dict(kind="run-exit", duration_s=1.2, loop=False)))
        S.clips._write_world_transitions([{"from": "sitting", "to": "walking", "kind": "run-exit", "accel": 0}])
        try:
            name = npc((97, -1), self.loc, "r-a")
            profile = F.C.get_character_profile(name)
            profile.update(place=None, pose_key="sitting")
            self.assertTrue(F.C.save_character_profile(name, profile))
            order = stroll(name)
            self.assertAlmostEqual(order["eta_motion_s"] - 100.0, 1.2 + W2_ETA, delta=6e-4)
            self.assertEqual(F.C.get_character_profile(name).get("pose_key"), "")
        finally:
            S.clips._write_world_transitions([])

    def test_w2d_failed_profile_write_takes_the_walk_back(self):
        name = npc((97, -1), self.loc, "r-a")
        with patch.object(F.C, "save_character_profile", lambda *a, **k: False):
            order, reason = MO.issue_walk(name, 98, 2, room_id="r-a")
        self.assertEqual((order, reason), (None, "write_failed"))
        self.assertEqual(kind_of(name), "cancel")
        self.assertFalse(MO.walking(name))
        self.assertEqual(pos(name), (97.0, -1.0))

    def test_w3_stroll_in_the_open(self):
        name = npc((110, 10))
        self.assertEqual(F.C.get_character_current_location(name), "")
        order, reason = MO.issue_walk(name, 115, 14)
        self.assertEqual(reason, "ok")
        route = order["hint_route"]
        self.assertGreaterEqual(len(route), 2)
        self.assertEqual(route[0], [110, 10])
        self.assertEqual(route[-1], [115, 14])
        length = sum(math.dist(a, b) for a, b in zip(route, route[1:]))
        self.assertGreaterEqual(length, math.hypot(5, 4) - 1e-6)
        self.assertAlmostEqual(order["eta_motion_s"] - 100.0, length / 1.4 + 0.5, delta=6e-4)
        F.MOTION[0] = 100.0 + length / 1.4 + 0.6
        self.assertEqual(MO.settle_due(), 1)
        self.assertEqual(pos(name), (115.0, 14.0))

    def test_w4_party_follower_is_refused(self):
        leader = npc((96, 0), self.loc, "r-a")
        follower = npc((97, -1), self.loc, "r-a")
        self.assertTrue(F.P.add_to_party(leader, follower))
        try:
            self.assertEqual(MO.issue_walk(follower, 98, 2, room_id="r-a"), (None, "party_follower"))
            self.assertIsNone(MO.index_get(follower))
        finally:
            F.P.leave_party(follower)

    def test_w5_restart_shifts_a_profile_walk(self):
        name = npc((97, -1), self.loc, "r-a")
        stroll(name)
        F.W.set_world_setting(MO.ALIVE_KEY, "101")
        F.MOTION[0] = 131.0
        MO.boot()
        order = MO.index_get(name)
        self.assertEqual(order["issued_motion_s"], 130.0)
        self.assertAlmostEqual(order["flip_motion_s"], 130.0 + W2_ETA, delta=6e-4)
        self.assertEqual((order["revision"], order["boot_alive_s"]), (2, 101.0))
        self.assertEqual(F.C.get_character_profile(name)["order"]["order"]["revision"], 2)
        self.assertAlmostEqual(MO.walk_due_in_s(), 1.759, delta=1e-3)
        self.assertTrue(MO.walking(name))
        self.assertEqual(MO.settle_due(), 0)
        # A second boot against the same stamp shifts nothing again.
        F.W.set_world_setting(MO.ALIVE_KEY, "101")
        F.MOTION[0] = 131.5
        MO.boot()
        self.assertEqual(MO.index_get(name)["revision"], 2)

    def test_w5b_dormant_walk_is_dropped_at_boot(self):
        name = npc((97, -1), self.loc, "r-a")
        stroll(name)
        self.assertTrue(F.C.set_character_status(name, F.C.DORMANT_STATUS))
        MO._INDEX.pop(name, None)
        F.W.set_world_setting(MO.ALIVE_KEY, "101")
        F.MOTION[0] = 131.0
        MO.boot()
        self.assertNotIn("order", F.C.get_character_profile(name))
        self.assertIsNone(MO.index_get(name))

    def test_w6_no_server_path_search_inside_a_location(self):
        def forbidden(*a, **k):
            raise AssertionError("nav_grid.route inside a location")
        with patch.object(nav_grid, "route", forbidden):
            a = npc((97, -1), self.loc, "r-a")
            self.assertEqual(self.room_change(a)["status"], "arrived")
            self.assertEqual(kind_of(a), "walk")
            b = npc((97, -1), self.loc, "r-a")
            stroll(b)
            self.assertEqual(kind_of(b), "walk")

    def pair_in_the_open(self):
        inviter, invitee = npc((110, 14)), npc((110, 10))
        return {"inviter": inviter, "invitee": invitee, "pose_key": "standing"}, invitee

    def test_w7_walk_to_partner_stays_a_point_journey(self):
        invitation, walker = self.pair_in_the_open()
        self.assertTrue(IE._walk_to_partner(invitation))
        self.assertIsNotNone(T.get_journey(walker))
        self.assertIsNone(MO.index_get(walker))

    def test_w8_teleport_snaps(self):
        from app.core import spell_engine
        from app.models import inventory
        name = npc((97, -1), self.loc, "r-a")
        stroll(name)
        spell = {"id": "anchor-spell", "success_chance": 100, "anchor_item_id": "anchor",
                 "teleport_subject": "caster", "copy_on_give": True}
        anchor = {"kind": "room", "location_id": self.loc, "room_id": "r-b"}
        with patch.object(inventory, "find_item_location", lambda *a, **k: anchor):
            result = spell_engine.execute_cast(name, "", spell)
        self.assertTrue(result["success"], result)
        cancel = MO.index_get(name)
        self.assertEqual((cancel["kind"], cancel["snap"]), ("cancel", True))
        here = pos(name)
        F.MOTION[0] = 103.0
        self.assertEqual(MO.settle_due(), 0)
        self.assertEqual(pos(name), here)

    def test_w9_next_beat_reaches_the_flip(self):
        name = npc((97, -1), self.loc, "r-a")
        order = stroll(name)
        F.MOTION[0] = 101.0
        self.assertLessEqual(T._next_beat_s(), order["flip_motion_s"] - 101.0 + 0.1 + 1e-9)

    def test_w10_manual_write_cancels_the_walk(self):
        name = npc((97, -1), self.loc, "r-a")
        stroll(name)
        F.MOTION[0] = 101.0
        F.C.set_character_pos(name, 96, 0)
        cancel = MO.index_get(name)
        self.assertEqual(cancel["kind"], "cancel")
        self.assertEqual((cancel["actors"][0]["stand"]["x"], cancel["actors"][0]["stand"]["z"]), (96.0, 0.0))
        self.assertNotIn("order", F.C.get_character_profile(name))
        F.MOTION[0] = 103.0
        with Recorder() as rec:
            self.assertEqual(MO.settle_due(), 0)
        self.assertEqual(rec.calls, [])
        self.assertEqual(pos(name), (96.0, 0.0))

    def test_w11_prop_action_request_replaces_the_walk(self):
        name, target, _pid = S.setup_run()
        F.MOTION[0] = 50.0
        order, reason = MO.issue_walk(name, 3, 5, room_id="hall")
        self.assertEqual(reason, "ok")
        self.assertAlmostEqual(order["flip_motion_s"], 50 + 2 / 1.4 + 0.5, delta=6e-4)
        F.MOTION[0] = 51.0
        answer = S.request(name, target)
        self.assertEqual(answer["status"], "approaching", answer)
        self.assertEqual(kind_of(name), "prop_action")
        self.assertNotIn("order", F.C.get_character_profile(name))
        F.MOTION[0] = 52.0
        self.assertEqual(MO.settle_due(), 0)
        self.assertEqual(pos(name), (1.0, 5.0))
        self.assertEqual(R.get(answer["execution_id"])["status"], "approaching")

    def test_w12_overland_journey_cancels_the_walk(self):
        far = F.W.add_location("Far", "fixture")
        far.update(pos_x=160, pos_z=0, map3d={"plan_width_m": 10, "boundary": [[-5, -5], [5, -5], [5, 5], [-5, 5]]})
        F.W.upsert_location(far, sync_world=True)
        name = npc((97, -1), self.loc, "r-a")
        F.C.set_known_locations(name, [self.loc, far["id"]])
        stroll(name)
        F.MOTION[0] = 101.0
        journey, reason = T.start_journey(name, far["id"])
        self.assertIsNotNone(journey, reason)
        self.assertEqual(kind_of(name), "cancel")
        F.MOTION[0] = 103.0
        self.assertEqual(MO.settle_due(), 0)
        self.assertEqual(pos(name), (97.0, -1.0))
        self.assertIsNotNone(T.get_journey(name))

    def test_w13_the_on_the_way_gates(self):
        from app.core import activity_engine, linked_characters, npc_actions, npc_scenes, npc_spawn
        name = npc((97, -1), self.loc, "r-a")
        partner = npc((96, -1), self.loc, "r-a")
        npc_actions._last_action.clear()
        with patch.object(npc_actions, "_in_chat", lambda n: False):
            self.assertIn(name, npc_actions.candidates())
            self.assertTrue(npc_scenes._free(name))
        self.assertEqual(linked_characters.swap_refusal(name) == "journey", False)
        self.assertFalse(activity_engine.evaluate_condition("travelling", name)[0])
        stroll(name)
        with patch.object(npc_actions, "_in_chat", lambda n: False):
            self.assertNotIn(name, npc_actions.candidates())
            self.assertFalse(npc_scenes._free(name))
        self.assertEqual(IE.check_can_pair(name, partner, ""), f"{name} is travelling")
        asked = []
        with patch.object(npc_actions, "_in_chat", lambda n: asked.append(n) or False):
            self.assertFalse(npc_spawn._settle_wanderer(name))
        self.assertEqual(asked, [])
        self.assertEqual(linked_characters.swap_refusal(name), "journey")
        self.assertTrue(activity_engine.evaluate_condition("travelling", name)[0])
        F.MOTION[0] = 103.0
        MO.settle_due()
        self.assertFalse(activity_engine.evaluate_condition("travelling", name)[0])
        with patch.object(npc_actions, "_in_chat", lambda n: False):
            self.assertIn(name, npc_actions.candidates())
        # A room-change walk counts as on the way for its seconds as well.
        mover = npc((97, -1), self.loc, "r-a")
        self.room_change(mover)
        self.assertTrue(activity_engine.evaluate_condition("travelling", mover)[0])
        # ... but it does not hold a pair off: room and point are already written.
        self.assertNotIn("travelling", IE.check_can_pair(mover, partner, ""))
        F.MOTION[0] = 121.0
        MO.settle_due()
        self.assertFalse(activity_engine.evaluate_condition("travelling", mover)[0])

    def test_w14_interaction_start_cancels_the_walk(self):
        from app.core import pose_catalog
        directory = F.ROOT / "clips"
        for role in ("a", "b"):
            (directory / f"walk-hug__{role}.fbx").write_bytes(b"private pair fixture")
        (directory / "walk-hug.json").write_text(json.dumps(dict(
            kind="walk-hug", pair=True, duration_s=2, loop=True,
            geometry=dict(roles=dict(a=dict(anchor_xz_m=[-.3, 0]), b=dict(anchor_xz_m=[.3, 0]))))))
        S.clips._clear_entries_cache()
        entries = pose_catalog.world_entries("pose")
        entries["walk-hug"] = dict(participants=2, animation="walk-hug", group="stand", places=2,
                                   yaw_offset=0, prompt="Two people hugging")
        pose_catalog.replace_world_entries("pose", entries)
        pose_catalog.reload_catalogs()
        name = npc((97, -1), self.loc, "r-a")
        partner = npc((96, -1), self.loc, "r-a")
        stroll(name)
        F.MOTION[0] = 101.0
        interaction = IE.start_interaction(name, partner, "walk-hug")
        self.assertTrue(interaction)
        self.assertEqual(kind_of(name), "cancel")
        held = pos(name)
        F.MOTION[0] = 103.0
        self.assertEqual(MO.settle_due(), 0)
        self.assertEqual(pos(name), held)
        self.assertIsNotNone(IE.get_interaction(name))

    def test_w15_walk_to_partner_cancels_the_walk(self):
        invitation, walker = self.pair_in_the_open()
        order, reason = MO.issue_walk(walker, 112, 8)
        self.assertEqual(reason, "ok")
        F.MOTION[0] = 101.0
        self.assertTrue(IE._walk_to_partner(invitation))
        self.assertEqual(kind_of(walker), "cancel")
        F.MOTION[0] = order["flip_motion_s"] + 0.1
        self.assertEqual(MO.settle_due(), 0)
        self.assertIsNotNone(T.get_journey(walker))
        self.assertNotEqual(pos(walker), (112.0, 8.0))

    def test_w16_force_rule_walks_belonging_and_scheduler_place(self):
        from app.core import belonging
        from app.core.periodic_jobs import _sub_force_rules
        from app.models import rules
        disabled = [{"id": r["id"], "type": "info"} for r in rules.load_rules()]
        rules.save_rules(disabled + [{"id": "home", "name": "Go home", "type": "force", "condition": "always",
                                      "force_action": {"go_to": "home"}}])
        try:
            name = npc((97, -1), self.loc, "r-a")
            F.C.save_character_config(name, {**F.C.get_character_config(name),
                                              "home_location": self.loc, "home_room": "r-b"})
            _sub_force_rules()
            self.assertEqual(F.C.get_character_current_room(name), "r-b")
            self.assertEqual(kind_of(name), "walk")
        finally:
            rules.save_rules(disabled)
        placed = npc((0, 0))
        F.C.set_character_pos(placed, 300, 300)
        belonging._place(placed, self.loc, "r-b")
        self.assertEqual(F.C.get_character_current_room(placed), "r-b")
        self.assertIsNone(MO.index_get(placed))
        scheduler = (REPO / "app/scheduler/scheduler_manager.py").read_text()
        self.assertNotIn("motion_orders", scheduler)


if __name__ == "__main__":
    unittest.main(verbosity=2)
