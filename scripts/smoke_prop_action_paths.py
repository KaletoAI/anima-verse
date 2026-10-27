#!/usr/bin/env python3
"""Deterministic indoor geometry and typed journey-owner regressions.

Run: ./.venv/bin/python scripts/smoke_prop_action_paths.py
Fixtures use private storage AND instance roots before world imports; no media,
network, real world or prop execution engine is used. --observe-dir DIR retains
an isolated movement scenario and writes route.html for browser inspection.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
PARSER = argparse.ArgumentParser()
PARSER.add_argument("--observe-dir", type=Path)
ARGS, REST = PARSER.parse_known_args()
TEMP = None if ARGS.observe_dir else tempfile.TemporaryDirectory(prefix="prop-paths-")
ROOT = ARGS.observe_dir.resolve() if ARGS.observe_dir else Path(TEMP.name)
if ARGS.observe_dir:
    ROOT.mkdir(parents=True, exist_ok=False)
os.environ.update(STORAGE_DIR=str(ROOT / "world"), INSTANCE_DIR=str(ROOT / "instance"),
                  ANIMATION_CLIPS_DIR=str(ROOT / "clips"), ANIMATION_RIG_FILE=str(ROOT / "rig.fbx"))
from app.core import paths
paths.init(ROOT / "world")
paths.init_instance(ROOT / "instance")
from app.core import config, db, hooks, props, places, travel_engine as E
from app.blender import runner
runner.is_available = lambda: False  # authored bbox; never request Blender/media
config.load(ROOT / "world/config.json")
db.init_schema()
from app.core import prop_action_paths as N
from app.core import room_stand as S
from app.core.game_time import GameTime, GameDuration
from app.core.timeutils import game_time, set_game_factor, set_game_time
from app.models import character as C, world as W, intents as I
from app.core import party_engine as P, prompt_templates
from plugins.party import trip_intents as T

set_game_factor(0)
set_game_time(GameTime.parse("Y0001-D010T12:00:00"))
UID = "11111111-1111-4111-8111-111111111111"
SQUARE = [(0, 0), (12, 0), (12, 10), (0, 10)]
L_ROOM = [(0, 0), (4, 0), (4, 4), (10, 4), (10, 10), (0, 10)]
SERIAL = 0


def actor(location, room="hall", at=(1, 5)):
    global SERIAL
    SERIAL += 1
    name = f"path_person_{SERIAL}"
    assert C.save_character_profile(name, {"character_name": name, "template": "npc-temporary"}, create_new=True)
    C.save_character_current_location(name, location)
    C.save_character_current_room(name, room)
    C.set_character_pos(name, *at)
    return name


def fixture(*, yaw=0, support=False, floor_y=0):
    """Real sidecar -> published variant -> recipe -> world places/geometry."""
    # Replace previous PRIVATE fixtures so overlapping room footprints cannot
    # derive a previous test's location. Never touch a real instance.
    for name in C.list_available_characters():
        C.delete_character(name)
    for location in W.list_locations():
        W.delete_location(location["id"])
    pid = props.create_prop(name="Approach fixture")["id"]
    doc = props.read_sidecar(pid)
    doc.update(bbox=[1, 1, 1], mount="floor", actions=[{
        "id": "rest", "name": "Rest", "description": "Fixture", "enabled": True,
        "ability": "pose", "pose_key": "sitting", "participants": 1,
        "presence": "any", "interrupt_on_presence_change": False,
        "phases": [], "requirements": [], "effects": []}], model_variants=[{
        "stem": "model", "uid": UID, "active": True,
        "width_m": 1, "depth_m": 1, "height_m": 1, "dims_estimated": False,
        "markers": [{"id": "body", "group": "sit", "at": [.5, .5, .5], "facing": 0}],
        "action_bindings": [{"action_id": "rest", "variant_uid": UID, "supported": True,
                             "marker_ids": ["body"], "validation": "local_valid",
                             "access_points": {"actor": {"x": 0, "z": 2, "yaw": 180}}}]}])
    props._write_sidecar(pid, doc)
    directory = props._prop_dir(pid)
    (directory / "model_1.glb").write_bytes(b"opaque-fixture-no-processing")
    (directory / "model_1.json").write_text(json.dumps({"tier": "full"}))
    (directory / "selection.json").write_text(json.dumps({"model": {"full": "model_1.glb"}}))
    placement = {"id": "device", "prop_id": pid, "at": [8, 5], "yaw": yaw}
    furniture = [placement]
    if support:
        table = props.create_prop(name="Support fixture")["id"]
        table_doc = props.read_sidecar(table)
        table_doc.update(mount="floor", width_m=3, depth_m=2, height_m=1)
        props._write_sidecar(table, table_doc)
        furniture = [{"id": "table", "prop_id": table, "at": [8, 5], "yaw": yaw},
                     {**placement, "at": [0, 0], "yaw": 0, "on": "table"}]
    loc = W.add_location("Approach room", "Throwaway geometry", rooms=[{
        "id": "hall", "name": "Hall", "layout": {"x": 0, "y": 0, "w": 12, "d": 10,
        "floor_offset_y": floor_y, "props": furniture,
        "openings": [{"edge": 0, "at": .5, "width_m": 1, "type": "door"}]}},
        {"id": "adjacent", "name": "Adjacent", "layout": {"x": 12, "y": 0, "w": 3, "d": 10}}])
    loc.update(pos_x=0, pos_z=0, map3d={"plan_width_m": 30,
               "boundary": [[-2, -2], [17, -2], [17, 12], [-2, 12]]})
    W.upsert_location(loc, sync_world=True)
    places.invalidate()
    target = {"location_id": loc["id"], "room_id": "hall", "placement_id": "device",
              "variant_uid": UID, "action_id": "rest", "definition_revision": props.get_prop(pid)["revision"]}
    return actor(loc["id"]), target, pid


class Paths(unittest.TestCase):
    def assert_clear(self, route, poly, boxes=(), zones=()):
        """Independent dense check of the entire line, not just its vertices."""
        from app.core.furnish_geometry import point_in_poly, point_segment_distance
        self.assertIsNotNone(route)
        for a, b in zip(route, route[1:]):
            for i in range(501):
                p = (a[0] + (b[0] - a[0]) * i / 500, a[1] + (b[1] - a[1]) * i / 500)
                self.assertTrue(point_in_poly(p, poly), p)
                self.assertGreaterEqual(min(point_segment_distance(p, poly[j], poly[(j + 1) % len(poly)])
                                            for j in range(len(poly))), .35 - 1e-7)
                for box in boxes:
                    angle = math.radians(box.get("yaw", 0))
                    dx, dz = p[0] - box["at"][0], p[1] - box["at"][1]
                    x, z = dx * math.cos(angle) - dz * math.sin(angle), dx * math.sin(angle) + dz * math.cos(angle)
                    self.assertTrue(abs(x) > box["width_m"] / 2 + .3 or abs(z) > box["depth_m"] / 2 + .3, p)
                for zone in zones:
                    self.assertFalse(point_in_poly(p, zone), p)

    def test_shortest_direct_and_zero_distance(self):
        self.assertEqual(N.visibility_path((1, 5), (10, 5), SQUARE, []), [(1, 5), (10, 5)])
        self.assertEqual(N.visibility_path((1, 5), (1, 5), SQUARE, []), [(1, 5)])

    def test_concave_room_never_shortcuts_wall_or_adjacent_door(self):
        # Direct line (2,1)->(8,7) crosses the absent north-east square.
        # A real door zone sits on the notch wall; it does NOT permit exiting.
        zone = [(4, 2), (3, 2), (3, 3), (4, 3)]
        route = N.visibility_path((2, 1), (8, 7), L_ROOM, [], [zone])
        self.assertGreater(len(route), 2)
        self.assert_clear(route, L_ROOM, zones=[zone])
        self.assertEqual(route, N.visibility_path((2, 1), (8, 7), L_ROOM, [], [zone]))

    def test_composed_concave_room_and_mirrored_adjacent_door_do_not_allow_exit(self):
        name, target, _ = fixture()
        location = W.get_location_by_id(target["location_id"])
        hall = next(r for r in location["rooms"] if r["id"] == "hall")
        adjacent = next(r for r in location["rooms"] if r["id"] == "adjacent")
        hall["layout"].update(w=10, d=10, outline=[list(p) for p in L_ROOM], openings=[])
        hall["layout"]["props"][0]["at"] = [8, 7]
        # This actual adjoining room owns the door. compose_recipe mirrors it
        # onto the concave room's wall, but it remains an uncrossable boundary
        # for an action target required to stay in the current room.
        adjacent["layout"] = {"x": 4, "y": 0, "w": 6, "d": 4, "openings": [
            {"edge": 3, "at": .5, "width_m": 1, "type": "door", "to": "hall"}]}
        W.upsert_location(location, sync_world=True)
        C.set_character_pos(name, 2, 1)
        result = N.plan_approach(name, target, "actor")
        self.assertEqual(result["status"], "ok", result)
        self.assertGreater(len(result["waypoints"]), 2)
        poly, boxes, zones = S.room_geometry(target["location_id"], "hall")
        self.assertTrue(zones, "real sibling door must compose its keep-clear geometry")
        self.assert_clear(result["waypoints"], poly, boxes, zones)
        self.assertEqual(N.plan_approach(name, {**target, "room_id": "adjacent"}, "actor")["reason"],
                         "target_not_in_actor_room")

    def test_furniture_and_rotated_footprints_block_whole_segments(self):
        for yaw in (0, 35, 90):
            boxes = [{"at": [6, 5], "width_m": 2, "depth_m": 3, "yaw": yaw},
                     {"at": [9, 1.5], "width_m": .6, "depth_m": .6, "yaw": 0}]
            route = N.visibility_path((1, 5), (11, 5), SQUARE, boxes)
            self.assertGreater(len(route), 2)
            self.assert_clear(route, SQUARE, boxes)
            # Reordering the same geometry cannot change the tie-breaking.
            self.assertEqual(route, N.visibility_path((1, 5), (11, 5), SQUARE, list(reversed(boxes))))
            self.assertEqual(route, N.visibility_path((1, 5), (11, 5), list(reversed(SQUARE)), boxes))

    def test_no_route_no_teleport_and_radius_narrow_gap(self):
        # Two pieces leave only .5m: the .6m body cannot squeeze through.
        boxes = [{"at": [6, 2.375], "width_m": 1, "depth_m": 4.75},
                 {"at": [6, 7.625], "width_m": 1, "depth_m": 4.75}]
        self.assertIsNone(N.visibility_path((1, 5), (11, 5), SQUARE, boxes))
        self.assertIsNone(N.visibility_path((1, 5), (6, 2), SQUARE, boxes))

    def test_empty_nonfinite_degenerate_and_crossing_geometry_rejected(self):
        for poly in ([], [(0, 0)], [(0, 0), (1, 0), (2, 0)],
                     [(0, 0), (8, 6), (0, 6), (6, 0)]):
            self.assertIsNone(N.visibility_path((1, 1), (2, 2), poly, []))
        self.assertIsNone(N.visibility_path((float("nan"), 1), (2, 2), SQUARE, []))
        self.assertIsNone(N.visibility_path((1, 1), (2, 2), SQUARE,
                                          [{"at": [3, 3], "width_m": 0, "depth_m": 1}]))

    def test_real_target_current_room_revision_variant_and_safe_access(self):
        name, target, pid = fixture()
        result = N.plan_approach(name, target, "actor")
        self.assertEqual((result["status"], result["reason"]), ("ok", ""))
        self.assertEqual((result["access"]["x"], result["access"]["z"]), (8, 7))
        self.assertEqual(result["entry_anchor"]["placement_id"], "device")
        self.assertNotEqual(result["waypoints"][-1][:2], [result["entry_anchor"]["x"], result["entry_anchor"]["z"]])
        for change, reason in (({"room_id": "adjacent"}, "target_not_in_actor_room"),
                               ({"variant_uid": "stale"}, "stale_variant"),
                               ({"definition_revision": "stale"}, "stale_definition"),
                               ({"action_id": "absent"}, "binding_not_found")):
            failed = N.plan_approach(name, {**target, **change}, "actor")
            self.assertEqual((failed["status"], failed["reason"], failed["waypoints"]), ("blocked", reason, []))
        self.assertEqual(N.plan_approach(name, target, "partner")["reason"], "missing_role_access")
        self.assertEqual(N.plan_approach("", {}, "actor")["status"], "blocked")
        doc = props.read_sidecar(pid)
        doc["model_variants"][0]["action_bindings"][0]["access_points"]["actor"]["z"] = .6
        props._write_sidecar(pid, doc)
        target["definition_revision"] = props.get_prop(pid)["revision"]
        self.assertEqual(N.plan_approach(name, target, "actor")["reason"], "access_not_walkable")

    def test_real_unreachable_access_has_no_world_route_or_position_write(self):
        name, target, _ = fixture()
        before = C.get_character_pos(name)
        pid = props.create_prop(name="Full-width obstruction")["id"]
        doc = props.read_sidecar(pid)
        doc.update(mount="floor", width_m=1, depth_m=10, height_m=2)
        props._write_sidecar(pid, doc)
        location = W.get_location_by_id(target["location_id"])
        next(r for r in location["rooms"] if r["id"] == "hall")["layout"]["props"].append(
            {"id": "barrier", "prop_id": pid, "at": [5, 5]})
        W.upsert_location(location, sync_world=True)
        result = N.plan_approach(name, target, "actor")
        self.assertEqual((result["status"], result["reason"], result["waypoints"]), ("blocked", "no_route", []))
        self.assertEqual(C.get_character_pos(name), before)

    def test_supported_rotated_prop_access_stays_at_room_floor(self):
        name, target, _ = fixture(yaw=90, support=True, floor_y=.4)
        result = N.plan_approach(name, target, "actor")
        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(result["access"], {"x": 10, "z": 5, "y": .4, "yaw": 270})
        self.assertGreater(result["entry_anchor"]["y"], 1.4)
        self.assertGreater(len(result["waypoints"]), 2, "support table must force a real detour")
        poly, boxes, zones = S.room_geometry(target["location_id"], "hall")
        self.assert_clear(result["waypoints"], poly, boxes, zones)


class ScenarioOwner:
    """Separate real execution owner, NOT a pretend prop_action implementation."""
    def __init__(self):
        self.runs = {}

    @contextmanager
    def guard(self, name, journey):
        row = self.runs.get(journey["execution_ref"])
        allowed = bool(row and row["actor"] == name and row["journey_id"] == journey["journey_id"]
                       and row["status"] == "approaching")
        yield allowed

    def validate(self, name, journey, room):
        row = self.runs.get(journey["execution_ref"])
        return bool(row and row["actor"] == name and row["room"] == room), "scenario_owner_mismatch"

    def arrived(self, name, journey):
        self.runs[journey["execution_ref"]]["status"] = "arrived"

    def cancelled(self, name, journey, reason):
        self.runs[journey["execution_ref"]].update(status="cancelled", reason=reason)


class Ownership(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owner = ScenarioOwner()
        E.register_execution_owner("path_scenario", guard=cls.owner.guard,
                                   validate_arrival=cls.owner.validate,
                                   arrived=cls.owner.arrived, cancelled=cls.owner.cancelled)
        prompt_templates.register_package_template_dirs([
            Path(__file__).resolve().parents[1] / "plugins/party/templates/llm"])
        # Execute the real package on_load boundary as declared in plugin.yaml;
        # no replacement journey provider or synthetic party owner is installed.
        from plugins.party import register as party_registration
        T.register()

    def start(self):
        name, target, _ = fixture()
        plan = N.plan_approach(name, target, "actor")
        ref = "run-" + name
        jid = "journey-" + name
        self.owner.runs[ref] = {"actor": name, "journey_id": jid, "room": "hall", "status": "approaching"}
        journey, reason = E.start_approach_journey(name, target, "actor", execution_kind="path_scenario",
                                                 execution_ref=ref, journey_id=jid)
        self.assertEqual(reason, "")
        self.assertIsNotNone(journey)
        return name, target, plan, journey

    def test_positions_freeze_arrival_and_foreign_cancel(self):
        name, target, plan, j = self.start()
        origin = C.get_character_pos(name)
        E.cancel_journey(name, journey_id=j["journey_id"], execution_kind="party_intent", execution_ref=j["execution_ref"])
        self.assertIsNotNone(E.get_journey(name))
        set_game_time(game_time() + GameDuration.of(seconds=2))
        E.advance_all_journeys()
        midway = C.get_character_pos(name)
        self.assertNotEqual(midway, origin)
        self.assertNotEqual((midway["x"], midway["z"]), (plan["entry_anchor"]["x"], plan["entry_anchor"]["z"]))
        self.assertLess(math.dist((midway["x"], midway["z"]), (8, 7)), math.dist((origin["x"], origin["z"]), (8, 7)))
        W.set_world_frozen(True)
        E.advance_all_journeys()
        self.assertEqual(C.get_character_pos(name), midway)
        W.set_world_frozen(False)
        set_game_time(game_time() + GameDuration.of(minutes=1))
        E.advance_all_journeys()
        self.assertIsNone(E.get_journey(name))
        self.assertEqual((C.get_character_pos(name)["x"], C.get_character_pos(name)["z"]), (8, 7))
        self.assertEqual(C.get_character_current_room(name), "hall")
        self.assertEqual(self.owner.runs[j["execution_ref"]]["status"], "arrived")

    def test_existing_measured_seat_exit_precedes_polyline_without_early_move(self):
        from app.core import animation_clips as A
        name, target, _ = fixture()
        clip_dir = ROOT / "clips"
        clip_dir.mkdir(exist_ok=True)
        (clip_dir / "path-rise.json").write_text(json.dumps({
            "kind": "path-rise", "duration_s": 2, "loop": False,
            "geometry": {"root_motion": {"mode": "foot_lock", "travel_m": [0, 1], "ref_height_m": 1.7}}}))
        previous = A.world_transitions()
        A._write_world_transitions([{"from": "sitting", "to": "walking", "kind": "path-rise", "accel": 0}])
        self.addCleanup(A._write_world_transitions, previous)
        profile = C.get_character_profile(name)
        profile["height"] = 170
        C.save_character_profile(name, profile)
        C.set_pose_intent(name, "sitting", prefer="device/body")
        seat = C.get_character_pos(name)
        self.assertEqual((seat["x"], seat["z"]), (8, 5))
        plan = N.plan_approach(name, target, "actor")
        self.assertEqual(plan["status"], "ok", plan)
        self.assertEqual(plan["waypoints"][0], [8, 6])
        ref, jid = "seat-" + name, "seat-journey-" + name
        self.owner.runs[ref] = {"actor": name, "journey_id": jid, "room": "hall", "status": "approaching"}
        journey, reason = E.start_approach_journey(name, target, "actor", execution_kind="path_scenario",
                                                 execution_ref=ref, journey_id=jid)
        self.assertFalse(reason)
        self.assertEqual(journey["waypoints"][:2], [[8, 5, 0], [8, 6, 0]])
        self.assertEqual(C.get_character_pos(name), seat)
        set_game_time(game_time() + GameDuration.of(seconds=1))
        E.advance_all_journeys()
        self.assertEqual(C.get_character_pos(name), seat)
        set_game_time(game_time() + GameDuration.of(seconds=1))
        E.advance_all_journeys()
        self.assertEqual((C.get_character_pos(name)["x"], C.get_character_pos(name)["z"]), (8, 6))
        set_game_time(game_time() + GameDuration.of(seconds=1))
        E.advance_all_journeys()
        self.assertEqual((C.get_character_pos(name)["x"], C.get_character_pos(name)["z"]), (8, 7))
        self.assertEqual(self.owner.runs[ref]["status"], "arrived")

    def test_no_prop_owner_is_activated_and_existing_journey_cannot_be_replaced(self):
        name, target, _, journey = self.start()
        result, reason = E.start_approach_journey(name, target, "actor",
                                                execution_kind="prop_action", execution_ref="not-a-run")
        self.assertIsNone(result)
        self.assertEqual(reason, "unknown_execution_owner")
        result, reason = E.start_approach_journey(name, target, "actor",
                                                execution_kind="path_scenario", execution_ref="other")
        self.assertIsNone(result)
        self.assertEqual(reason, "journey_already_active")
        for kind, ref in (("", ""), ("path_scenario", "")):
            result, reason = E.start_approach_journey(name, {}, "actor",
                                                    execution_kind=kind, execution_ref=ref)
            self.assertIsNone(result)
            self.assertEqual(reason, "invalid_execution_owner")
        self.assertEqual(E.get_journey(name), journey)

    def test_freeze_excludes_real_elapsed_time_without_catchup(self):
        clock = [datetime(2040, 1, 1, tzinfo=timezone.utc)]
        with patch("app.core.timeutils.utc_now", side_effect=lambda: clock[0]):
            set_game_factor(1)
            set_game_time(GameTime.parse("Y0001-D010T12:00:00"))
            name, _, _, j = self.start()
            clock[0] += timedelta(seconds=2)
            E.advance_all_journeys()
            midway = C.get_character_pos(name)
            frozen_at = game_time()
            W.set_world_frozen(True)
            clock[0] += timedelta(hours=5)
            E.advance_all_journeys()
            self.assertEqual(game_time(), frozen_at)
            self.assertEqual(C.get_character_pos(name), midway)
            W.set_world_frozen(False)
            self.assertEqual(game_time(), frozen_at)
            clock[0] += timedelta(seconds=1)
            E.advance_all_journeys()
            self.assertNotEqual(C.get_character_pos(name), midway)
            self.assertEqual(self.owner.runs[j["execution_ref"]]["status"], "approaching")
            set_game_factor(0)

    def test_changed_room_geometry_cancels_before_large_tick_crosses_blocker(self):
        name, target, _, j = self.start()
        before = C.get_character_pos(name)
        blocker = props.create_prop(name="New obstruction")["id"]
        doc = props.read_sidecar(blocker)
        doc.update(mount="floor", width_m=1, depth_m=2, height_m=2)
        props._write_sidecar(blocker, doc)
        location = W.get_location_by_id(target["location_id"])
        next(r for r in location["rooms"] if r["id"] == "hall")["layout"]["props"].append(
            {"id": "barrier", "prop_id": blocker, "at": [4, 5.86]})
        W.upsert_location(location, sync_world=True)
        set_game_time(game_time() + GameDuration.of(hours=1))
        E.advance_all_journeys()
        self.assertIsNone(E.get_journey(name))
        self.assertEqual(C.get_character_pos(name), before)
        self.assertEqual(self.owner.runs[j["execution_ref"]]["reason"], "approach_route_changed")

    def test_manual_move_cancels_only_owned_run_and_stale_tick_does_not_restore(self):
        name, _, _, j = self.start()
        cached = next(row for row in C.list_active_journeys() if row["name"] == name)
        C.set_character_pos(name, 2, 3)
        self.assertEqual(self.owner.runs[j["execution_ref"]]["status"], "cancelled")
        with patch.object(C, "list_active_journeys", return_value=[cached]):
            E.advance_all_journeys()
        self.assertEqual((C.get_character_pos(name)["x"], C.get_character_pos(name)["z"]), (2, 3))
        self.assertIsNone(E.get_journey(name))

    def test_empty_owned_polyline_is_cancelled_without_origin_fallback(self):
        name, _, _, _ = self.start()
        before = C.get_character_pos(name)
        profile = C.get_character_profile(name)
        profile["journey"]["waypoints"] = []
        C.save_character_profile(name, profile)
        E.advance_all_journeys()
        self.assertNotIn("journey", C.get_character_profile(name))
        self.assertEqual(C.get_character_pos(name), before)
        self.assertEqual(C.get_character_profile(name)["last_journey_result"]["reason"], "invalid_journey_geometry")

    def test_unknown_owner_cancels_visibly_without_reaching_goal(self):
        name, _, _, j = self.start()
        before = C.get_character_pos(name)
        profile = C.get_character_profile(name)
        profile["journey"]["execution_kind"] = "missing_owner"
        C.save_character_profile(name, profile)
        E.advance_all_journeys()
        self.assertIsNone(E.get_journey(name))
        self.assertEqual(C.get_character_pos(name), before)
        self.assertEqual(C.get_character_profile(name)["last_journey_result"]["reason"], "unknown_execution_owner")

    def test_party_provider_and_separate_owner_and_ordinary_journey_coexist(self):
        name, home, _, j = self.start()
        party_provider = hooks.get_provider("journey_execution_context")
        away = W.add_location("Scenario destination", "Throwaway destination", rooms=[{"id": "hall", "name": "Hall"}])
        away.update(pos_x=100, pos_z=0, map3d={"plan_width_m": 10,
                    "boundary": [[-5, -5], [5, -5], [5, 5], [-5, 5]],
                    "boundary_openings": [{"edge": 3, "at": .5, "width_m": 4, "type": "passage"}]})
        W.upsert_location(away, sync_world=True)
        # The real party package claims its own journey, not a fake provider.
        lead, guest = actor(home["location_id"]), actor(home["location_id"])
        for who in (lead, guest):
            C.set_known_locations(who, [home["location_id"], away["id"]])
        action = T.intent_action_validate(lead, {lead: {"role": "leader"}, guest: {"role": "follower"}},
                    {"type": "travel_together", "destination": {"location_id": away["id"], "room_id": "hall"}, "scope": "pair"})
        intent = I.create_intent(owner=lead, title="Route coexistence", participants={lead: {"role": "leader"}, guest: {"role": "follower"}}, action=action, target_count=0)
        invite = I.get_intent(intent["id"])["meta"]["travel"]["invite_id"]
        self.assertEqual(P.resolve_pending_invite(invite, True)["status"], "accepted")
        party_j = E.get_journey(lead)
        self.assertIsNotNone(party_j)
        self.assertEqual(party_j["execution_kind"], "party_intent")
        ordinary = actor(home["location_id"])
        C.set_known_locations(ordinary, [home["location_id"], away["id"]])
        ordinary_j, error = E.start_journey(ordinary, away["id"], target_room="hall")
        self.assertFalse(error)
        self.assertNotIn("execution_kind", ordinary_j)
        self.assertIs(hooks.get_provider("journey_execution_context"), party_provider)
        # A legacy persisted party claim is normalized once, with no re-route.
        profile = C.get_character_profile(lead)
        profile["journey"].pop("execution_kind")
        C.save_character_profile(lead, profile)
        self.assertEqual(E.get_journey(lead)["execution_kind"], "party_intent")
        E.cancel_journey(name, journey_id=party_j["journey_id"], execution_ref=party_j["execution_ref"], execution_kind="party_intent")
        self.assertIsNotNone(E.get_journey(name))
        set_game_time(game_time() + GameDuration.of(seconds=2))
        E.advance_all_journeys()
        self.assertGreater(C.get_character_pos(name)["x"], 1)
        self.assertIsNotNone(E.get_journey(lead))
        set_game_time(game_time() + GameDuration.of(hours=1))
        E.advance_all_journeys()
        hooks.emit("world_tick")
        self.assertEqual(self.owner.runs[j["execution_ref"]]["status"], "arrived")
        self.assertEqual(I.get_intent(intent["id"])["status"], "done")
        self.assertEqual(C.get_character_current_location(ordinary), away["id"])


def observe_movement():
    """Run actual Core writes/ticks and render their recorded route, not a mock."""
    name, target, _ = fixture(yaw=90, support=True, floor_y=.4)
    owner = ScenarioOwner()
    E.register_execution_owner("path_observation", guard=owner.guard, validate_arrival=owner.validate,
                               arrived=owner.arrived, cancelled=owner.cancelled)
    ref, jid = "observed-run", "observed-journey"
    owner.runs[ref] = {"actor": name, "journey_id": jid, "room": "hall", "status": "approaching"}
    plan = N.plan_approach(name, target, "actor")
    assert plan["status"] == "ok", plan
    clock = [datetime(2040, 1, 1, tzinfo=timezone.utc)]
    snapshots = []
    with patch("app.core.timeutils.utc_now", side_effect=lambda: clock[0]):
        set_game_factor(1)
        set_game_time(GameTime.parse("Y0001-D010T12:00:00"))
        journey, reason = E.start_approach_journey(name, target, "actor",
                            execution_kind="path_observation", execution_ref=ref, journey_id=jid)
        assert journey and not reason, reason

        def record(label):
            pos = C.get_character_pos(name)
            snapshots.append(dict(label=label, game=game_time().canonical(), x=pos["x"], z=pos["z"],
                                  status=owner.runs[ref]["status"], frozen=W.is_world_frozen()))

        record("departure")
        for i in range(2):
            clock[0] += timedelta(seconds=1)
            E.advance_all_journeys()
            record(f"walking {i + 1}s")
        W.set_world_frozen(True)
        frozen = C.get_character_pos(name)
        clock[0] += timedelta(minutes=30)
        E.advance_all_journeys()
        assert C.get_character_pos(name) == frozen
        record("after 30 real minutes frozen")
        W.set_world_frozen(False)
        for i in range(60):
            clock[0] += timedelta(seconds=1)
            E.advance_all_journeys()
            record(f"resumed {i + 1}s")
            if not E.get_journey(name):
                break
        assert owner.runs[ref]["status"] == "arrived", owner.runs[ref]
        assert (snapshots[-1]["x"], snapshots[-1]["z"]) == (plan["access"]["x"], plan["access"]["z"])
        set_game_factor(0)
    poly, boxes, zones = S.room_geometry(target["location_id"], target["room_id"])
    data = dict(actor=name, target=target, plan=plan, journey=journey, polygon=poly,
                furniture=[S.footprint_corners(b) for b in boxes],
                grown=[S.footprint_corners(b, .3) for b in boxes], zones=zones, snapshots=snapshots)
    (ROOT / "movement.json").write_text(json.dumps(data, indent=2))
    # Every displayed position was read back from real character_state writes.
    # The slider only selects records; this HTML does not simulate the executor.
    html = """<!doctype html><meta charset="utf-8"><title>Recorded indoor approach</title>
<style>body{font:16px system-ui;max-width:1100px;margin:2rem auto;background:#fafafa;color:#222}
svg{width:100%;height:600px;border:1px solid #777}pre{white-space:pre-wrap}input{width:100%}</style>
<h1>Recorded authoritative indoor approach</h1>
<p>Black: room wall. Grey: furniture. Dashed red: grown body footprint.
Blue: actual stored polyline. Green: floor access. Purple: body anchor (not the walking goal).
Orange: real persisted figure position. A door never grants an outside-room shortcut.</p>
<svg id="view" viewBox="-1 -1 14 12" xmlns="http://www.w3.org/2000/svg"></svg>
<label for="frame">Recorded movement / Freeze / arrival</label><input id="frame" type="range" min="0" value="0">
<pre id="record"></pre><p>Source: movement.json; this viewer selects observed records, not interpolated fake positions.</p>
<script>const d=DATA;const svg=document.querySelector('#view'), slider=document.querySelector('#frame');
const ns='http://www.w3.org/2000/svg';function shape(tag, attrs){const e=document.createElementNS(ns,tag);
for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);svg.appendChild(e);return e;}
const points=p=>p.map(v=>v[0]+','+v[1]).join(' ');
shape('polygon',{points:points(d.polygon),fill:'white',stroke:'black','stroke-width':.05});
for(const p of d.zones)shape('polygon',{points:points(p),fill:'#ffe5a8',stroke:'#af7600','stroke-width':.02});
for(const p of d.furniture)shape('polygon',{points:points(p),fill:'#bbb',stroke:'#555','stroke-width':.03});
for(const p of d.grown)shape('polygon',{points:points(p),fill:'none',stroke:'#b22','stroke-width':.02,'stroke-dasharray':'.1 .08'});
shape('polyline',{points:points(d.journey.waypoints),fill:'none',stroke:'#1674b6','stroke-width':.06});
shape('circle',{cx:d.plan.access.x,cy:d.plan.access.z,r:.14,fill:'green'});
shape('circle',{cx:d.plan.entry_anchor.x,cy:d.plan.entry_anchor.z,r:.14,fill:'purple'});
const figure=shape('circle',{r:.3,fill:'#ed9312','fill-opacity':.8,stroke:'#833','stroke-width':.025});
slider.max=d.snapshots.length-1;function show(){const s=d.snapshots[Number(slider.value)];
figure.setAttribute('cx',s.x);figure.setAttribute('cy',s.z);document.querySelector('#record').textContent=
JSON.stringify({frame:Number(slider.value),...s,access_y:d.plan.access.y,body_y:d.plan.entry_anchor.y},null,2);}
slider.addEventListener('input',show);show();</script>"""
    (ROOT / "route.html").write_text(html.replace("DATA", json.dumps(data)))
    print(f"Recorded movement: {ROOT / 'movement.json'}")
    print(f"Visual route: {(ROOT / 'route.html').as_uri()}")


if __name__ == "__main__":
    if ARGS.observe_dir:
        observe_movement()
    else:
        unittest.main(argv=[sys.argv[0], *REST])
