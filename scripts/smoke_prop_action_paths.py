#!/usr/bin/env python3
"""Deterministic indoor geometry (plan_approach) and journey-owner regressions.

Run: ./.venv/bin/python scripts/smoke_prop_action_paths.py
Fixtures use private storage AND instance roots before world imports; no media,
network, real world or prop execution engine is used. Since plan E3 Task 8 a
furniture approach walks no journey, so the former approach-journey scenarios
(and the --observe-dir route recording built on them) are gone; the owned
journeys left are party trip intents (Ownership).
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
from threading import RLock
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
PARSER = argparse.ArgumentParser()
ARGS, REST = PARSER.parse_known_args()
RESUME_ROOT = os.environ.get("PROP_ACTION_SMOKE_RESUME_ROOT", "")
# A single root binding keeps the default temp path visible to the lint;
# a retained restart root still requires an explicit private scenario.
TEMP = None if RESUME_ROOT else tempfile.TemporaryDirectory(prefix="prop-paths-")
ROOT = Path(RESUME_ROOT).resolve() if RESUME_ROOT else Path(TEMP.name)
if RESUME_ROOT and not (ROOT / ".prop-action-scenario").is_file():
    raise ValueError("resume root is not an explicitly created private action scenario")
os.environ["STORAGE_DIR"] = str(ROOT / "world")
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ.update(ANIMATION_CLIPS_DIR=str(ROOT / "clips"),
                  ANIMATION_CLIPS_LICENSED_DIR=str(ROOT / "clips-licensed"),
                  ANIMATION_CLIPS_INBOX_DIR=str(ROOT / "clips-inbox"),
                  ANIMATION_CLIPS_TRIAL_DIR=str(ROOT / "clips-trial"),
                  ANIMATION_RIG_FILE=str(ROOT / "rig.fbx"), EVENT_ENTRY_ROLL_ENABLED="0")
from app.core import paths
paths.init(ROOT / "world")
paths.init_instance(ROOT / "instance")
# Disable actual external work at the same boundaries as the variant smoke.
# The door worker captures runner.run, so guard that alias explicitly as well.
from app.blender import refine, runner
refine.auto_retexture_enabled = lambda: False
refine.auto_lod_enabled = lambda: False
refine.auto_bake_vc_enabled = lambda: False
refine.measure_file = lambda path: None
runner.is_available = lambda: False
EXTERNAL_CALLS = []
EXTERNAL_LOCK = RLock()


def forbidden_blender(*args, **kwargs):
    with EXTERNAL_LOCK:
        EXTERNAL_CALLS.append(str(args[0]) if args else "unknown Blender job")
    raise AssertionError("indoor-path fixture attempted external Blender processing")


runner.run = forbidden_blender
from app.core import door_models
door_models._run_blender = forbidden_blender
# Unavailable optional visual assets retain the real scene's numeric door/
# window geometry; they must not schedule an asset build for a path fixture.
door_models.ensure_door_model = lambda *args, **kwargs: None
door_models.ensure_window_model = lambda *args, **kwargs: None


def assert_no_external_work():
    # A worker may catch AssertionError; recording BEFORE raising plus draining
    # the real queue makes that attempted binary call fail the test process.
    door_models._queue.join()
    with EXTERNAL_LOCK:
        if EXTERNAL_CALLS:
            raise AssertionError(f"unexpected external Blender jobs: {EXTERNAL_CALLS}")


from app.core import config, db, hooks, props, places, travel_engine as E
WORLD_CONFIG = ROOT / "world/config.json"
WORLD_CONFIG.write_text(json.dumps({"random_events": {
    "enabled": False, "entry_roll_enabled": False, "resolution_proactive": False}}))
config.load(WORLD_CONFIG)
from app.core import random_events
assert not random_events.is_enabled(), "temporary config must disable event generation after flattening"
assert not random_events.resolution_proactive_enabled(), "temporary config must disable proactive event resolution"
db.init_schema()
from app.core import prop_action_paths as N
from app.core import room_stand as S
from app.core.game_time import GameTime, GameDuration
from app.core import timeutils
from app.core.timeutils import game_time, set_game_factor
from app.models import character as C, world as W, intents as I
from app.core import party_engine as P, prompt_templates
from plugins.party import trip_intents as T

# The fixture's ONE hand-moved clock. Movement runs on the MOTION clock
# (timeutils.motion_time: real seconds the world ran unfrozen,
# plan-bewegung-echtzeit.md), gameplay durations on the game clock (factor 0
# here, so neither moves by itself). A forward step of ``set_game_time`` below
# is "N seconds pass": it moves the game clock AND — unless the world is frozen,
# exactly as the real motion clock — the motion clock by the same N seconds
# (factor-1 lockstep). A backward reset moves only the game clock. Tests that
# exercise the REAL clock against a pinned ``utc_now`` use ``real_motion_clock``.
REAL_MOTION_TIME = timeutils.motion_time
MOTION = [1000.0]
timeutils.motion_time = lambda: MOTION[0]


def set_game_time(when):
    step = (when - game_time()).seconds
    if step > 0 and not W.is_world_frozen():
        MOTION[0] += step
    timeutils.set_game_time(when)


def elapse(seconds):
    """``seconds`` pass, also a fraction: the motion clock moves exactly
    (unless frozen), the game clock by the nearest whole second it can hold."""
    if not W.is_world_frozen():
        MOTION[0] += seconds
    timeutils.set_game_time(game_time() + GameDuration.of(seconds=seconds))


@contextmanager
def real_motion_clock():
    """The real motion clock (derived from ``utc_now``) for this block."""
    with patch.object(timeutils, "motion_time", REAL_MOTION_TIME):
        yield


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


def furniture_prop(name, *, width, depth, height):
    """Author dimensions on the canonical variant, never ignored prop fields."""
    pid = props.create_prop(name=name)["id"]
    doc = props.read_sidecar(pid)
    doc["mount"] = "floor"
    doc["model_variants"][0].update(width_m=width, depth_m=depth, height_m=height,
                                    dims_estimated=False)
    props._write_sidecar(pid, doc)
    return pid


def pose_clips():
    """A private clip for every SOLO catalog pose, as an installation has
    them: a prop action is offered only when the actor's figure can play its
    pose (prop_action_engine.animated_for). Pair poses keep their role clips
    to the tests that author them."""
    from app.core import animation_clips
    from app.core.pose_catalog import get_catalog
    directory = ROOT / "clips"
    directory.mkdir(exist_ok=True)
    for entry in get_catalog("pose").values():
        kind = str(entry.get("animation") or "")
        if not kind or "/" in kind or entry.get("participants", 1) != 1:
            continue
        if not (directory / f"{kind}.fbx").exists():
            (directory / f"{kind}.fbx").write_bytes(b"private deterministic pose fixture")
            (directory / f"{kind}.json").write_text(json.dumps(dict(kind=kind, duration_s=2, loop=True)))
    animation_clips._clear_entries_cache()


def fixture(*, yaw=0, support=False, floor_y=0):
    """Real sidecar -> published variant -> recipe -> world places/geometry."""
    pose_clips()
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
        "markers": [{"id": "body", "group": "seat", "at": [.5, .5, .5], "facing": 0,
                     "access": {"actor": {"x": 0, "z": 2, "yaw": 180}}}],
    }])
    props._write_sidecar(pid, doc)
    directory = props._prop_dir(pid)
    (directory / "model_1.glb").write_bytes(b"opaque-fixture-no-processing")
    (directory / "model_1.json").write_text(json.dumps({"tier": "full"}))
    (directory / "selection.json").write_text(json.dumps({"model": {"full": "model_1.glb"}}))
    placement = {"id": "device", "prop_id": pid, "at": [8, 5], "yaw": yaw}
    furniture = [placement]
    if support:
        table = furniture_prop("Support fixture", width=3, depth=2, height=1)
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
    def tearDown(self):
        assert_no_external_work()

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

    def test_departure_exempts_only_held_furniture_never_walls_or_another_placement(self):
        own = {"placement_id": "chair", "at": [8, 5], "width_m": 1, "depth_m": 1}
        self.assertTrue(N._departure_walkable((8, 5), (8, 6), (SQUARE, [own], []), "chair"))
        other = {**own, "placement_id": "same-prop-other-placement"}
        self.assertFalse(N._departure_walkable((8, 5), (8, 6), (SQUARE, [own, other], []), "chair"))
        self.assertFalse(N._departure_walkable((8, 5), (8, 6), (SQUARE, [own], []), "another-chair"))
        self.assertFalse(N._departure_walkable((11.5, 5), (12.5, 5), (SQUARE, [], []), "chair"))
        door_zone = [(7.5, 5.4), (8.5, 5.4), (8.5, 5.6), (7.5, 5.6)]
        self.assertFalse(N._departure_walkable((8, 5), (8, 6), (SQUARE, [own], [door_zone]), "chair"))

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
        doc["model_variants"][0]["markers"][0]["access"]["actor"]["z"] = .6
        props._write_sidecar(pid, doc)
        target["definition_revision"] = props.get_prop(pid)["revision"]
        relaxed = N.plan_approach(name, target, "actor")
        self.assertEqual((relaxed["status"], relaxed["entry_mode"]), ("ok", "bridge"))

    def test_real_unreachable_access_has_no_world_route_or_position_write(self):
        name, target, _ = fixture()
        before = C.get_character_pos(name)
        pid = furniture_prop("Full-width obstruction", width=1, depth=10, height=2)
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
        # The raised support table blocks the entry bridge: direct uses its
        # full footprint (rotated depth 2 -> X halfwidth 1), grown by .3.
        # Radius 1.30 touches; 1.35 at angle zero is the nearest free ring.
        self.assertEqual(result["entry_mode"], "direct")
        self.assertEqual(result["access"], {"x": 9.35, "z": 5, "y": .4, "yaw": 270})
        self.assertEqual(result["bridge_access"], {"x": 10, "z": 5, "y": .4, "yaw": 270})
        self.assertGreater(result["entry_anchor"]["y"], 1.4)
        self.assertGreater(len(result["waypoints"]), 2, "support table must force a real detour")
        poly, boxes, zones = S.room_geometry(target["location_id"], "hall")
        self.assert_clear(result["waypoints"], poly, boxes, zones)
        self.assert_clear(result["waypoints"], poly,
                          [{"at": [8, 5], "yaw": 90, "width_m": 3, "depth_m": 2}], zones)


def seat_actor(test, name):
    """Seat ``name`` on the fixture seat with a measured exit clip (path-rise,
    1 m forward); the clip table is restored when ``test`` cleans up."""
    from app.core import animation_clips as A
    clip_dir = ROOT / "clips"
    clip_dir.mkdir(exist_ok=True)
    (clip_dir / "path-rise.fbx").write_bytes(b"private deterministic exit fixture")
    A._clear_entries_cache()
    (clip_dir / "path-rise.json").write_text(json.dumps({
        "kind": "path-rise", "duration_s": 2, "loop": False,
        "geometry": {"root_motion": {"mode": "foot_lock", "travel_m": [0, 1], "ref_height_m": 1.7}}}))
    previous = A.world_transitions()
    A._write_world_transitions([{"from": "sitting", "to": "walking", "kind": "path-rise", "accel": 0}])
    test.addCleanup(A._write_world_transitions, previous)
    profile = C.get_character_profile(name)
    profile["height"] = 170
    # Seed an already persisted historical seat to exercise departure
    # geometry, not the removed raw-pose furniture allocation API.
    loc, room = places.where(name, profile=profile)
    place = next(p for p in places.room_places(loc, room) if p["id"] == "device/body")
    C.set_character_pos(name, *place["slots"][0])
    profile = C.get_character_profile(name)
    profile.update(height=170, pose_key="sitting",
                   place={"id": place["id"], "slot": 0, "room_id": room})
    C.save_character_profile(name, profile)


class Ownership(unittest.TestCase):
    """The owned journeys left after plan E3 are party trip intents. A furniture
    approach is no journey any more (the run walks on its order), so an owned
    journey of any other kind — a "prop_action" one from before E3 included —
    has no owner and is cancelled visibly."""
    @classmethod
    def setUpClass(cls):
        prompt_templates.register_package_template_dirs([
            Path(__file__).resolve().parents[1] / "plugins/party/templates/llm"])
        # Execute the real package on_load boundary as declared in plugin.yaml;
        # no replacement journey provider or synthetic party owner is installed.
        from plugins.party import register as party_registration
        T.register()

    def tearDown(self):
        assert_no_external_work()

    def owned_point_journey(self, kind):
        """A real point journey of a fresh actor (1, 5) -> (4, 5), stamped
        with an execution owner of ``kind``."""
        name, _, _ = fixture()
        journey, reason = E.start_journey_to_point(name, 4, 5)
        self.assertTrue(journey, reason)
        profile = C.get_character_profile(name)
        profile["journey"].update(execution_kind=kind, execution_ref="run-" + name)
        self.assertTrue(C.save_character_profile(name, profile))
        return name

    def test_unknown_owner_cancels_visibly_without_reaching_goal(self):
        for kind in ("missing_owner", "prop_action"):
            with self.subTest(kind=kind):
                name = self.owned_point_journey(kind)
                before = C.get_character_pos(name)
                set_game_time(game_time() + GameDuration.of(seconds=2))
                E.advance_all_journeys()
                self.assertIsNone(E.get_journey(name))
                self.assertEqual(C.get_character_pos(name), before)
                self.assertEqual(C.get_character_profile(name)["last_journey_result"]["reason"],
                                 "unknown_execution_owner")

    def test_party_provider_and_ordinary_journey_coexist(self):
        _name, home, _ = fixture()
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
        # The party selectors never remove an ordinary journey.
        E.cancel_journey(ordinary, journey_id=party_j["journey_id"], execution_ref=party_j["execution_ref"],
                         execution_kind="party_intent")
        self.assertIsNotNone(E.get_journey(ordinary))
        set_game_time(game_time() + GameDuration.of(seconds=2))
        E.advance_all_journeys()
        self.assertIsNotNone(E.get_journey(lead))
        set_game_time(game_time() + GameDuration.of(hours=1))
        E.advance_all_journeys()
        hooks.emit("world_tick")
        self.assertEqual(I.get_intent(intent["id"])["status"], "done")
        self.assertEqual(C.get_character_current_location(ordinary), away["id"])


if __name__ == "__main__":
    result = unittest.main(argv=[sys.argv[0], *REST], exit=False).result
    assert_no_external_work()
    if not result.wasSuccessful():
        sys.exit(1)
