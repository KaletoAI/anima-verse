#!/usr/bin/env python3
"""Real temporary world/profile/indoor journey execution regressions.

Reuses Task3's canonical published-variant fixture and external-work tripwire.
Controller: ./.venv/bin/python scripts/smoke_prop_action_runs.py
"""
import json
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Thread, current_thread
import unittest
from unittest.mock import patch

OPTIONS = argparse.ArgumentParser(add_help=False)
OPTIONS.add_argument("--scenario-dir", type=Path)
STAGES = ("arrive-crash", "resume-entry", "resume", "terminal", "missing-target", "missing-resume",
          "sleep-pending-stop", "sleep-resume-stop", "sleep-cleanup-resume")
OPTIONS.add_argument("--scenario-stage", choices=STAGES)
OPTIONS_ARGS, REMAINDER = OPTIONS.parse_known_args()
sys.argv = [sys.argv[0], *REMAINDER]
if OPTIONS_ARGS.scenario_dir:
    root = OPTIONS_ARGS.scenario_dir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / ".prop-action-scenario").write_text("Task4 private Core scenario\\n")
    environment = dict(os.environ, PROP_ACTION_SMOKE_RESUME_ROOT=str(root))
    for stage in STAGES:
        subprocess.run([sys.executable, __file__, "--scenario-stage", stage], env=environment, check=True)
    print(f"Real stopped/restarted Core execution: {root / 'execution.json'}")
    raise SystemExit(0)

import smoke_prop_action_paths as F
# Keep complete shipped catalogs, but all authored test entries/templates are
# private. In particular no save_template call can touch repository/shared.
SHARED = F.ROOT / "shared"
ORIGINAL_SHARED = F.paths.get_shared_dir()
for folder in ("templates", "config", "terrain"):
    destination = SHARED / folder
    if not destination.exists():
        shutil.copytree(ORIGINAL_SHARED / folder, destination)
F.paths.get_shared_dir = lambda: SHARED
from app.models import character_template
character_template.clear_template_cache()
template = character_template.get_template("npc-temporary")
template["sections"].append(dict(id="run-status", fields=[
    dict(key="run_energy", type="bar", store="status_effects", label="Run energy")]))
character_template.save_template("run-person", template)
from app.core import prop_action_engine as A, prop_action_store as R
from app.core import animation_clips as clips
from app.core import pose_catalog
from app.core.game_time import GameDuration


def measured_entry(pose="sitting"):
    """Real asset discovery/sidecar/transition paths; never patched success."""
    directory = F.ROOT / "clips"
    directory.mkdir(exist_ok=True)
    (directory / "run-enter.fbx").write_bytes(b"private deterministic asset fixture")
    (directory / "run-enter.json").write_text(json.dumps(dict(
        kind="run-enter", duration_s=2, loop=False,
        geometry=dict(root_motion=dict(mode="foot_lock", travel_m=[0, 2], ref_height_m=1.7)))))
    clips._clear_entries_cache()
    clips._write_world_transitions([{"from": "walking", "to": pose, "kind": "run-enter", "accel": 0}])


def authored_pair():
    name, target, pid = setup_run()
    partner = F.actor(target["location_id"], at=(2, 5))
    entries = pose_catalog.world_entries("pose")
    entries["run-pair"] = dict(solo=False, animation="run-pair", group="seat", places=2,
                               yaw_offset=90, prompt="Two people sharing a seat")
    pose_catalog.replace_world_entries("pose", entries)
    pose_catalog.reload_catalogs()
    directory = F.ROOT / "clips"
    directory.mkdir(exist_ok=True)
    for role in ("a", "b"):
        (directory / f"run-pair__{role}.fbx").write_bytes(b"private pair fixture")
    (directory / "run-pair.json").write_text(json.dumps(dict(
        kind="run-pair", pair=True, duration_s=2, loop=True,
        geometry=dict(roles=dict(a=dict(anchor_xz_m=[-.3, 0]), b=dict(anchor_xz_m=[.3, 0]))))))
    doc = F.props.read_sidecar(pid)
    doc["actions"][0].update(ability="pair", participants=2, pose_key="run-pair")
    variant = doc["model_variants"][0]
    variant["markers"][0].update(capacity=2, spacing_m=.6)
    variant["markers"][0]["access"] = dict(
        actor=dict(x=-.3, z=2, yaw=180), partner=dict(x=.3, z=2, yaw=180))
    F.props._write_sidecar(pid, doc)
    target["definition_revision"] = F.props.get_prop(pid)["revision"]
    measured_entry("run-pair")
    return name, partner, target, pid


def setup_run(ability="pose"):
    clips._write_world_transitions([])
    name, target, pid = F.fixture()
    doc = F.props.read_sidecar(pid)
    definition = doc["actions"][0]
    definition["ability"] = ability
    if ability == "combined":
        definition["phases"] = [dict(id=p, label=p, duration_game_s=5, pose_key="sitting")
                                for p in ("prepare", "drink")]
    F.props._write_sidecar(pid, doc)
    target["definition_revision"] = F.props.get_prop(pid)["revision"]

    profile = F.C.get_character_profile(name)
    profile["height"] = 170
    profile["template"] = "run-person"
    profile["status_effects"] = {"run_energy": 50}
    F.C.save_character_profile(name, profile)
    measured_entry()
    return name, target, pid


def request(name, target, **kw):
    return A.request(name, {k: target[k] for k in ("location_id", "room_id", "placement_id", "variant_uid")},
                     target["action_id"], target["definition_revision"], **kw)


def tick(seconds=1):
    F.set_game_time(F.game_time() + GameDuration.of(seconds=seconds))
    F.E.advance_all_journeys()
    A.advance(F.game_time())


class Runs(unittest.TestCase):
    def tearDown(self):
        F.W.set_world_frozen(False)
        F.set_game_factor(0)
        for run in R.live_runs():
            A.cancel(run["actor"], run["execution_id"])
        F.assert_no_external_work()


    def test_automatic_access_recheck_detects_height_change(self):
        name, target, pid = setup_run()
        doc = F.props.read_sidecar(pid)
        doc["model_variants"][0]["markers"][0].pop("access")
        F.props._write_sidecar(pid, doc)
        target["definition_revision"] = F.props.get_prop(pid)["revision"]
        answer = request(name, target)
        self.assertEqual(answer["status"], "approaching", answer)
        row = R.get(answer["execution_id"])
        profile = F.C.get_character_profile(name)
        profile["height"] = 85
        F.C.save_character_profile(name, profile)
        self.assertEqual(A._validate(row, require_claims=True), "approach_target_changed")

    def test_solo_tries_later_slot_when_first_access_is_blocked(self):
        name, target, pid = setup_run()
        doc = F.props.read_sidecar(pid)
        marker = doc["model_variants"][0]["markers"][0]
        marker.pop("access")
        marker.update(capacity=3, spacing_m=.6)
        F.props._write_sidecar(pid, doc)
        target["definition_revision"] = F.props.get_prop(pid)["revision"]
        # Entry travel +2 at facing0 starts at z3. The obstacle blocks only
        # the left slot x7.4; the next point (8,3) remains walkable.
        block = F.furniture_prop("First slot obstacle", width=.1, depth=.1, height=1)
        location = F.W.get_location_by_id(target["location_id"])
        location["rooms"][0]["layout"]["props"].append(
            dict(id="obstruction", prop_id=block, at=[7.4, 3], yaw=0))
        F.W.upsert_location(location, sync_world=True)
        from app.core.prop_action_paths import plan_approach
        planned = plan_approach(name, target, "actor")
        self.assertEqual(planned["status"], "ok", planned)
        self.assertEqual(planned["entry_anchor"]["slot"], 1)
        answer = request(name, target)
        self.assertEqual(answer["status"], "approaching", answer)
        plan = R.get(answer["execution_id"])["data"]["plans"]["actor"]
        self.assertEqual(plan["entry_anchor"]["slot"], 1)

    def test_automatic_bench_and_opposite_bed_entries(self):
        """Hand derivation for 170cm height / 1.7m reference, travel (0,-2):

        At facing0, delta=(0,-2): bench slots x=7.4,8,8.6 at z5
        start at z7. At facing90 delta=(-2,0), left bed slot x7.5
        starts x9.5; facing270 delta=(2,0), right x8.5 starts x6.5.
        Adding those deltas lands on every slot exactly (5cm guard passes).
        """
        name, target, pid = setup_run()
        directory = F.ROOT / "clips"
        metadata = directory / "run-enter.json"
        raw = json.loads(metadata.read_text())
        raw["geometry"]["root_motion"]["travel_m"] = [0, -2]
        metadata.write_text(json.dumps(raw))
        clips._clear_entries_cache()
        doc = F.props.read_sidecar(pid)
        marker = doc["model_variants"][0]["markers"][0]
        marker.pop("access")
        marker.update(capacity=3, spacing_m=.6)
        F.props._write_sidecar(pid, doc)
        target["definition_revision"] = F.props.get_prop(pid)["revision"]
        from app.core.prop_action_paths import plan_approach
        from app.core.prop_action_access import preview_access
        previews = preview_access(doc, prop_id=pid)["rest"][target["variant_uid"]]["body"]
        for slot, x in enumerate((-.6, 0, .6)):
            point = previews[str(slot)]["actor"]
            self.assertAlmostEqual(point["x"], x)
            self.assertAlmostEqual(point["z"], 2)
            self.assertEqual((point["yaw"], point["source"]), (0, "auto"))
        for slot, x in enumerate((7.4, 8, 8.6)):
            plan = plan_approach(name, dict(target, slot=slot), "actor")
            self.assertEqual(plan["status"], "ok", plan)
            self.assertAlmostEqual(plan["access"]["x"], x)
            self.assertAlmostEqual(plan["access"]["z"], 7)
            self.assertEqual(plan["access"]["yaw"], 0)
            self.assertEqual(A._entry_spec(name, plan, "sitting")[1], "")
        from copy import deepcopy
        left, right = deepcopy(marker), deepcopy(marker)
        left.update(id="left", at=[0, .5, .5], group="lie", facing=90, capacity=1)
        right.update(id="right", at=[1, .5, .5], group="lie", facing=270, capacity=1)
        variant = doc["model_variants"][0]
        variant["markers"] = [left, right]
        doc["actions"][0]["pose_key"] = "lying"
        F.props._write_sidecar(pid, doc)
        clips._write_world_transitions([{"from": "walking", "to": "lying", "kind": "run-enter", "accel": 0}])
        target["definition_revision"] = F.props.get_prop(pid)["revision"]
        for mid, x, yaw in (("left", 9.5, 90), ("right", 6.5, 270)):
            plan = plan_approach(name, dict(target, marker_id=mid, slot=0), "actor")
            self.assertEqual(plan["status"], "ok", plan)
            self.assertAlmostEqual(plan["access"]["x"], x)
            self.assertAlmostEqual(plan["access"]["z"], 5)
            self.assertEqual(plan["access"]["yaw"], yaw)
            self.assertEqual(A._entry_spec(name, plan, "lying")[1], "")
        doc["model_variants"][0]["markers"][0]["access"] = {"actor": dict(x=2, z=2, yaw=41)}
        F.props._write_sidecar(pid, doc)
        target["definition_revision"] = F.props.get_prop(pid)["revision"]
        plan = plan_approach(name, dict(target, marker_id="left", slot=0), "actor")
        self.assertEqual(plan["access"], dict(x=10, z=7, yaw=41, y=0))
        self.assertEqual(A._entry_spec(name, plan, "lying")[1], "entry_transition_mismatch")

    def test_multi_action_partner_offers_share_geometry_but_not_later_state(self):
        from copy import deepcopy
        from app.core import prop_actions, room_stand
        name, partner, target, pid = authored_pair()
        available = F.actor(target["location_id"], at=(3, 5))
        asleep = F.actor(target["location_id"], at=(4, 5))
        F.C.set_is_sleeping(asleep, True)
        doc = F.props.read_sidecar(pid)
        for action_id in ("share-again", "share-third"):
            action = deepcopy(doc["actions"][0])
            action.update(id=action_id, name=action_id)
            doc["actions"].append(action)
        F.props._write_sidecar(pid, doc)
        revision = F.props._document_revision(doc)
        exact = {k: target[k] for k in A._TARGET}
        expected = {action_id: {
            partner: dict(enabled=True, reason=""),
            available: dict(enabled=True, reason=""),
            asleep: dict(enabled=False, reason="participant_asleep")}
            for action_id in ("rest", "share-again", "share-third")}
        for action_id, checks in expected.items():
            for who, wanted in checks.items():
                self.assertEqual(A.check(name, exact, action_id, revision, who), wanted)
        before = {who: F.C.get_character_profile(who) for who in (name, partner, available, asleep)}
        with patch.object(F.places, "_compose", wraps=F.places._compose) as compose, \
                patch.object(room_stand, "room_geometry", wraps=room_stand.room_geometry) as geometry:
            rows = prop_actions.offers(name)
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertTrue(row["enabled"], row)
            self.assertEqual({entry["partner"]: {k: entry[k] for k in ("enabled", "reason")}
                              for entry in row["available_targets"]}, expected[row["action_id"]])
        self.assertEqual(compose.call_count, 1, "one location composition per offers operation")
        self.assertEqual(geometry.call_count, 1, "one collision geometry load per room")
        self.assertEqual({who: F.C.get_character_profile(who) for who in before}, before)
        self.assertFalse(R.claims())

        # An offer is not authorization: occupancy and author edits are observed
        # by the very next operation, without waiting for the places cache TTL.
        occupied = next(p for p in F.places._compose(target["location_id"])[target["room_id"]]
                        if p.get("placement_id") == target["placement_id"])
        profile = F.C.get_character_profile(available)
        profile["place"] = dict(id=occupied["id"], slot=0, room_id=target["room_id"])
        F.C.save_character_profile(available, profile)
        blocked = prop_actions.offers(name)
        self.assertTrue(all(not row["enabled"] for row in blocked), blocked)
        self.assertTrue(all(entry["reason"] == "no_free_slot" for row in blocked
                            for entry in row["available_targets"] if entry["partner"] != asleep), blocked)
        profile.pop("place")
        F.C.save_character_profile(available, profile)
        doc["actions"][0]["enabled"] = False
        F.props._write_sidecar(pid, doc)
        changed = {row["action_id"]: row for row in prop_actions.offers(name)}
        self.assertFalse(changed["rest"]["enabled"], changed)
        self.assertTrue(changed["share-again"]["enabled"], changed)
        self.assertEqual(A.check(name, exact, "share-again", revision, partner)["reason"], "stale_definition")
        location = F.W.get_location_by_id(target["location_id"])
        room = next(room for room in location["rooms"] if room["id"] == target["room_id"])
        room["layout"]["props"][0]["at"] = [40, 5]
        F.W.upsert_location(location, sync_world=True)
        moved = prop_actions.offers(name)
        self.assertEqual(len(moved), 3)
        self.assertTrue(all(not row["enabled"] for row in moved), moved)

    def test_pair_preflight_routes_match_fresh_public_planner(self):
        from app.core import prop_action_paths
        name, partner, target, _ = authored_pair()
        exact = {k: target[k] for k in A._TARGET}
        definition, reason = A._definition(exact, target["action_id"], target["definition_revision"])
        self.assertFalse(reason)
        run = dict(execution_id="", actor=name, partner=partner, action_id=target["action_id"],
                   definition_revision=target["definition_revision"], target=exact, definition=definition,
                   data=dict(plans={}, access_roles={}))
        plans, reason = A._plan(run, conn=R.db.get_connection())
        self.assertFalse(reason, plans)
        for role, who in (("actor", name), ("partner", partner)):
            anchor = plans[role]["entry_anchor"]
            fresh = prop_action_paths.plan_approach(who, dict(target, marker_id=anchor["marker_id"],
                                                             slot=anchor["slot"]),
                                                     run["data"]["access_roles"][role])
            self.assertEqual(plans[role], fresh)
            access_x = 7.7 if run["data"]["access_roles"][role] == "actor" else 8.3
            self.assertEqual(fresh["waypoints"], [[1, 5] if role == "actor" else [2, 5],
                                                 [access_x, 7]])

    def test_missing_entry_capability_blocks_before_route_search(self):
        from app.core import prop_actions, prop_action_paths
        name, _, _ = setup_run()
        clips._write_world_transitions([])
        with patch.object(prop_action_paths, "plan_approach",
                          wraps=prop_action_paths.plan_approach) as planner:
            rows = prop_actions.offers(name)
        self.assertEqual([(row["enabled"], row["reason"]) for row in rows],
                         [(False, "missing_entry_transition")])
        self.assertEqual(planner.call_count, 0)

    def test_exact_request_id_and_conflict_do_not_change_pose(self):
        name, target, _ = setup_run()
        one = request(name, target, request_id="retry")
        self.assertEqual(one["status"], "approaching", one)
        self.assertEqual(request(name, target, request_id="retry"), one)
        changed = request(name, target, request_id="retry", partner="other")
        self.assertEqual(changed["reason"], "request_id_conflict")
        self.assertFalse(F.C.get_character_profile(name).get("place"))

    def test_concurrent_slot_claim_and_person_claim(self):
        name, target, _ = setup_run()
        other = F.actor(target["location_id"], at=(2, 5))
        barrier = Barrier(2)
        def start(n):
            barrier.wait()
            return request(n, target)
        with ThreadPoolExecutor(max_workers=2) as pool:
            answers = list(pool.map(start, (name, other)))
        self.assertEqual(sum(a["status"] == "approaching" for a in answers), 1, answers)
        winner = next(n for n, a in zip((name, other), answers) if a["status"] == "approaching")
        self.assertEqual(request(winner, target)["reason"], "participant_claimed")
        self.assertEqual(len(R.claims()), 2)

    def test_stale_revision_and_deleted_variant_have_no_side_effect(self):
        name, target, pid = setup_run()
        before = F.C.get_character_profile(name)
        self.assertEqual(request(name, {**target, "definition_revision": "stale"})["reason"], "stale_definition")
        doc = F.props.read_sidecar(pid)
        doc["model_variants"][0]["uid"] = "22222222-2222-4222-8222-222222222222"
        F.props._write_sidecar(pid, doc)
        self.assertEqual(request(name, target)["status"], "refused")
        self.assertEqual(F.C.get_character_profile(name), before)
        self.assertFalse(R.claims())

    def test_cancel_old_execution_preserves_foreign_journey(self):
        name, target, _ = setup_run()
        result = request(name, target)
        F.E.cancel_journey(name)
        journey, reason = F.E.start_journey_to_point(name, 2, 3)
        self.assertTrue(journey, reason)
        A.cancel(name, result["execution_id"])
        self.assertEqual(F.E.get_journey(name)["journey_id"], journey["journey_id"])
        self.assertFalse(R.claims())

    def test_reentrant_cancellation_under_guard_releases_claims(self):
        name, target, _ = setup_run()
        result = request(name, target)
        journey = F.E.get_journey(name)
        with A.owner_guard(name, journey) as allowed:
            self.assertTrue(allowed)
            F.E.cancel_journey(name, journey_id=journey["journey_id"], execution_kind="prop_action",
                               execution_ref=result["execution_id"])
        self.assertEqual(R.get(result["execution_id"])["status"], "cancelled")
        self.assertFalse(R.claims())

    def test_actual_arrival_receipt_recovers_callback_loss(self):
        name, target, _ = setup_run()
        result = request(name, target)
        # Crash window: the actual core arrival persists its receipt, but its
        # registered callback raises before the executor records that arrival.
        with patch.object(A, "_arrived", side_effect=RuntimeError("process stopped")):
            tick(30)
        A.advance(F.game_time())
        row = R.get(result["execution_id"])
        self.assertEqual((row["status"], row["phase"]), ("approaching", "entry"), row)
        self.assertEqual(F.C.get_character_profile(name)["last_journey_result"]["status"], "arrived")
        self.assertIn(name, row["data"]["arrived"])
        access = row["data"]["plans"]["actor"]["access"]
        self.assertEqual(F.C.get_character_pos(name), {"x": access["x"], "z": access["z"]})
        self.assertFalse(F.C.get_character_profile(name).get("place"))
        self.assertEqual(row["data"]["entry_elapsed"], 0)
        tick(row["data"]["entries"][name]["duration_game_s"])
        activated = R.get(result["execution_id"])
        self.assertEqual(activated["status"], "active", activated)
        anchor = activated["data"]["plans"]["actor"]["entry_anchor"]
        self.assertEqual(F.C.get_character_pos(name), {"x": anchor["x"], "z": anchor["z"]})
        self.assertEqual(F.C.get_character_profile(name)["place"]["execution_id"], result["execution_id"])

    def test_deleted_target_during_approach_releases_only_own_claims(self):
        name, target, pid = setup_run()
        result = request(name, target)
        doc = F.props.read_sidecar(pid)
        doc["actions"] = []
        F.props._write_sidecar(pid, doc)
        tick()
        self.assertEqual(R.get(result["execution_id"])["status"], "failed")
        self.assertFalse(R.claims())
        self.assertIsNone(F.E.get_journey(name))

    def test_missing_entry_transition_is_visible_without_body_jump(self):
        name, target, _ = setup_run()
        clips._write_world_transitions([])
        before = F.C.get_character_pos(name)
        result = request(name, target)
        self.assertEqual(result["status"], "refused", result)
        self.assertEqual(result["reason"], "missing_entry_transition", result)
        self.assertEqual(F.C.get_character_pos(name), before)
        self.assertFalse(F.C.get_character_profile(name).get("place"))
        self.assertFalse(R.claims())

    def test_real_entry_waits_then_coffee_prepare_and_drink(self):
        name, target, _ = setup_run("combined")
        measured_entry()
        result = request(name, target)
        tick(30)
        self.assertEqual(R.get(result["execution_id"])["phase"], "entry")
        self.assertEqual(F.C.get_character_pos(name)["z"], 7)
        self.assertFalse(F.C.get_character_profile(name).get("place"))
        tick(2)
        self.assertEqual(R.get(result["execution_id"])["phase"], "prepare")
        self.assertEqual(F.C.get_character_profile(name)["place"]["slot"], 0)
        tick(5)
        self.assertEqual(R.get(result["execution_id"])["phase"], "drink")
        tick(5)
        self.assertEqual(R.get(result["execution_id"])["status"], "completed")
        self.assertFalse(R.claims())
        tick(3600)
        self.assertEqual(R.get(result["execution_id"])["reason"], "phases_completed")

    def test_open_pose_normal_end_and_manual_position_abort(self):
        for manual in (False, True):
            name, target, _ = setup_run()
            measured_entry()
            result = request(name, target)
            tick(30)
            tick(2)
            self.assertEqual(R.get(result["execution_id"])["status"], "active")
            if manual:
                F.C.set_character_pos(name, 2, 2)
            else:
                A.cancel(name, result["execution_id"])
            self.assertEqual(R.get(result["execution_id"])["status"], "cancelled" if manual else "completed")
            self.assertFalse(R.claims())

    def test_sleep_owns_exact_bed_until_real_wake_and_never_goes_offmap(self):
        name, target, pid = setup_run("sleep")
        doc = F.props.read_sidecar(pid)
        doc["actions"][0]["pose_key"] = "sleeping"
        doc["model_variants"][0]["markers"][0]["group"] = "lie"
        F.props._write_sidecar(pid, doc)
        target["definition_revision"] = F.props.get_prop(pid)["revision"]
        measured_entry("sleeping")
        result = request(name, target)
        tick(30)
        self.assertFalse(F.C.is_character_sleeping(name))
        tick(2)
        self.assertTrue(F.C.is_character_sleeping(name))
        self.assertEqual(R.get(result["execution_id"])["status"], "sleeping")
        self.assertEqual(F.C.get_character_profile(name)["place"]["id"], "device/body")
        self.assertEqual(F.C.get_character_current_location(name), target["location_id"])
        self.assertEqual(len(R.claims()), 2)
        with patch.object(A, "_PROCESS", "new-process"):
            tick(36000)
            self.assertEqual(R.get(result["execution_id"])["status"], "sleeping")
            self.assertEqual(len(R.claims()), 2)
            F.C.set_is_sleeping(name, False)
        self.assertEqual(R.get(result["execution_id"])["status"], "completed")
        self.assertFalse(R.claims())

    def test_consent_has_no_claims_exact_invitee_and_both_arrivals_required(self):
        name, partner, target, _ = authored_pair()
        result = request(name, target, partner=partner)
        self.assertEqual(result["status"], "awaiting_consent", result)
        self.assertFalse(R.claims())
        self.assertEqual(A.respond(name, result["execution_id"], True)["reason"], "not_invitee")
        accepted = A.respond(partner, result["execution_id"], True)
        self.assertEqual(accepted["status"], "approaching", accepted)
        self.assertEqual(len(R.claims()), 4)
        first = F.E.get_journey(name)
        F.set_game_time(F.game_time() + GameDuration.of(seconds=30))
        # Real single-journey core step, while the partner is still on its path.
        with A.owner_guard(name, first) as allowed:
            self.assertTrue(allowed)
            F.E._advance_approach(name, first, F.game_time())
        self.assertFalse(F.C.get_character_profile(name).get("interaction"))
        self.assertEqual(R.get(result["execution_id"])["data"]["arrived"], [name])
        F.E.advance_all_journeys()
        A.advance(F.game_time())
        tick(2)
        row = R.get(result["execution_id"])
        self.assertEqual(row["status"], "active", row)
        a, b = (F.C.get_character_profile(n) for n in (name, partner))
        self.assertEqual(a["interaction"]["id"], b["interaction"]["id"])
        self.assertEqual(a["interaction"]["execution_ref"], result["execution_id"])
        self.assertEqual((a["place"]["slot"], b["place"]["slot"]), (0, 1))
        self.assertEqual((a["place"]["id"], b["place"]["id"]), ("device/body", "device/body"))
        from app.core.interaction_engine import end_interaction
        end_interaction(partner, reason="manual", interaction_id=b["interaction"]["id"])
        self.assertEqual(R.get(result["execution_id"])["status"], "cancelled")
        self.assertFalse(R.claims())

    def test_freeze_deadline_and_process_restart_have_no_offline_phase_bonus(self):
        name, target, _ = setup_run("combined")
        measured_entry()
        result = request(name, target)
        F.W.set_world_frozen(True)
        A.advance(F.game_time())
        self.assertEqual(R.get(result["execution_id"])["data"]["elapsed"], 0)
        F.W.set_world_frozen(False)
        tick(30)
        tick(2)
        tick(3)
        self.assertEqual(R.get(result["execution_id"])["data"]["phase_elapsed"], 3)
        with patch.object(A, "_PROCESS", "restarted"):
            tick(36000)
            row = R.get(result["execution_id"])
            self.assertEqual(row["phase"], "prepare", row)
            self.assertEqual(row["data"]["phase_elapsed"], 3)
            tick(2)
            self.assertEqual(R.get(result["execution_id"])["phase"], "drink")

    def test_requirement_presence_pooling_and_timeout_release_claims(self):
        name, target, pid = setup_run()
        doc = F.props.read_sidecar(pid)
        doc["actions"][0]["presence"] = "alone"
        F.props._write_sidecar(pid, doc)
        target["definition_revision"] = F.props.get_prop(pid)["revision"]
        other = F.actor(target["location_id"])
        self.assertEqual(request(name, target)["reason"], "presence_not_met")
        F.C.set_character_status(other, "pooled")
        result = request(name, target)
        self.assertEqual(result["status"], "approaching", result)
        A.advance(F.game_time() + GameDuration.of(seconds=120))
        self.assertEqual(R.get(result["execution_id"])["reason"], "approach_timeout")
        self.assertFalse(R.claims())
        result = request(name, target)
        F.C.set_character_status(name, "pooled")
        self.assertEqual(R.get(result["execution_id"])["status"], "cancelled")
        self.assertFalse(R.claims())

    def test_effective_requirement_is_rechecked_during_approach(self):
        name, target, pid = setup_run()
        from app.core import prompt_filters
        with F.db.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO prompt_filters "
                "(id,condition,label,drop_blocks,prompt_modifier,enabled,meta,icon,image_modifier,bone_pose) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", ("run-boost", "condition:run-boost", "Boost", "[]", "", 1,
                    json.dumps({"stat_boosts": {"run_energy": 20}}), "", "", "{}"))
        prompt_filters.invalidate_filter_snapshot()
        profile = F.C.get_character_profile(name)
        profile["status_effects"]["run_energy"] = 30
        profile["active_conditions"] = [dict(name="run-boost", started_at=F.game_time().canonical(), duration_hours=1)]
        F.C.save_character_profile(name, profile)
        doc = F.props.read_sidecar(pid)
        doc["actions"][0]["requirements"] = [dict(id="energy", target="actor", type="stat",
                                                   stat="run_energy", op="ge", value=40)]
        F.props._write_sidecar(pid, doc)
        target["definition_revision"] = F.props.get_prop(pid)["revision"]
        result = request(name, target)
        self.assertEqual(result["status"], "approaching", result)
        profile = F.C.get_character_profile(name)
        profile["status_effects"]["run_energy"] = 10
        F.C.save_character_profile(name, profile)
        tick(1)
        self.assertEqual(R.get(result["execution_id"])["reason"], "requirement_not_met")
        self.assertFalse(R.claims())

    def test_missing_stat_unknown_reference_and_expired_condition_fail_closed(self):
        from app.core import prompt_filters
        name, target, pid = setup_run()
        with F.db.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO prompt_filters "
                "(id,condition,label,drop_blocks,prompt_modifier,enabled,meta,icon,image_modifier,bone_pose) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", ("run-rested", "condition:run-rested", "Rested", "[]", "", 1,
                    json.dumps({"stat_boosts": {"run_energy": 20}}), "", "", "{}"))
        prompt_filters.invalidate_filter_snapshot()
        doc = F.props.read_sidecar(pid)
        requirement = dict(id="rested", target="actor", type="condition", condition_id="run-rested", present=True)
        doc["actions"][0]["requirements"] = [requirement]
        F.props._write_sidecar(pid, doc)
        target["definition_revision"] = F.props.get_prop(pid)["revision"]
        profile = F.C.get_character_profile(name)
        profile["active_conditions"] = [dict(name="run-rested", duration_hours=1,
            started_at=(F.game_time() - GameDuration.of(hours=2)).canonical())]
        F.C.save_character_profile(name, profile)
        self.assertEqual(request(name, target)["reason"], "requirement_not_met")
        requirement = dict(id="energy", target="actor", type="stat", stat="run_energy", op="ge", value=40)
        doc["actions"][0]["requirements"] = [requirement]
        F.props._write_sidecar(pid, doc)
        target["definition_revision"] = F.props.get_prop(pid)["revision"]
        profile["status_effects"] = {}
        F.C.save_character_profile(name, profile)
        self.assertEqual(request(name, target)["reason"], "missing_character_stat")
        requirement["stat"] = "not-a-real-stat"
        F.props._write_sidecar(pid, doc)
        target["definition_revision"] = F.props.get_prop(pid)["revision"]
        self.assertEqual(request(name, target)["reason"], "unknown_requirement_reference")
        self.assertFalse(R.claims())

    def test_terminal_cleanup_recovery_does_not_reopen_or_cancel_a_new_way(self):
        name, target, _ = setup_run()
        result = request(name, target)
        # Simulate a crash AFTER the real terminal/claim commit but BEFORE its
        # separate physical cleanup. No journey receipt is fabricated.
        with patch.object(A, "_cleanup", side_effect=RuntimeError("crash before cleanup")):
            with self.assertRaises(RuntimeError):
                A.cancel(name, result["execution_id"])
        self.assertFalse(R.claims())
        A.advance(F.game_time())
        self.assertIsNone(F.E.get_journey(name))
        self.assertFalse(R.get(result["execution_id"])["data"]["cleanup_pending"])
        self.assertEqual(R.get(result["execution_id"])["status"], "cancelled")

    def test_competing_pair_consent_cannot_claim_shared_participant_twice(self):
        name, partner, target, _ = authored_pair()
        third = F.actor(target["location_id"], at=(3, 5))
        first = request(name, target, partner=partner)
        second = request(third, target, partner=partner)
        self.assertFalse(R.claims())
        self.assertEqual(A.respond(partner, first["execution_id"], True)["status"], "approaching")
        refused = A.respond(partner, second["execution_id"], True)
        self.assertEqual(refused["reason"], "participant_claimed")
        self.assertEqual(len(R.claims()), 4)
        self.assertEqual({c["execution_id"] for c in R.claims()}, {first["execution_id"]})

    def test_sleeping_partner_and_different_room_refuse_without_actor_side_effect(self):
        for asleep in (False, True):
            name, partner, target, _ = authored_pair()
            if asleep:
                F.C.set_is_sleeping(partner, True)
            else:
                F.C.save_character_current_room(partner, "adjacent")
            before = F.C.get_character_profile(name)
            answer = request(name, target, partner=partner)
            self.assertEqual(answer["reason"], "participant_asleep" if asleep else "target_not_in_actor_room")
            self.assertEqual(F.C.get_character_profile(name), before)
            self.assertFalse(R.claims())

    def test_real_world_freeze_pauses_run_deadline_across_five_hours(self):
        name, target, _ = setup_run()
        clock = [F.datetime(2040, 1, 1, tzinfo=F.timezone.utc)]
        with patch("app.core.timeutils.utc_now", side_effect=lambda: clock[0]):
            F.set_game_factor(1)
            F.set_game_time(F.GameTime.parse("Y0001-D010T12:00:00"))
            result = request(name, target)
            before = F.C.get_character_pos(name)
            F.W.set_world_frozen(True)
            clock[0] += F.timedelta(hours=5)
            F.E.advance_all_journeys()
            A.advance(F.game_time())
            self.assertEqual(R.get(result["execution_id"])["data"]["elapsed"], 0)
            self.assertEqual(F.C.get_character_pos(name), before)
            F.W.set_world_frozen(False)
            clock[0] += F.timedelta(seconds=1)
            F.E.advance_all_journeys()
            A.advance(F.game_time())
            self.assertEqual(R.get(result["execution_id"])["status"], "approaching")
            self.assertEqual(R.get(result["execution_id"])["data"]["elapsed"], 1)
            F.set_game_factor(0)


    def test_presence_entry_wakes_only_when_explicit_policy_requires_it(self):
        for interrupt in (False, True):
            name, target, pid = setup_run("sleep")
            doc = F.props.read_sidecar(pid)
            doc["actions"][0].update(pose_key="sleeping", presence="alone",
                                      interrupt_on_presence_change=interrupt)
            doc["model_variants"][0]["markers"][0]["group"] = "lie"
            F.props._write_sidecar(pid, doc)
            target["definition_revision"] = F.props.get_prop(pid)["revision"]
            measured_entry("sleeping")
            result = request(name, target)
            tick(30)
            tick(2)
            self.assertTrue(F.C.is_character_sleeping(name))
            F.actor(target["location_id"], at=(2, 3))
            self.assertEqual(F.C.is_character_sleeping(name), not interrupt)
            self.assertEqual(R.get(result["execution_id"])["status"], "cancelled" if interrupt else "sleeping")
            A.cancel(name, result["execution_id"])

    def test_outer_profile_lock_defers_owner_callback_until_release(self):
        from app.core.keyed_lock import keyed_lock
        name, target, _ = setup_run()
        result = request(name, target)
        with keyed_lock("character_profile", name):
            F.C.save_character_current_room(name, "adjacent")
            self.assertEqual(R.get(result["execution_id"])["status"], "approaching")
        self.assertEqual(R.get(result["execution_id"])["status"], "cancelled")
        self.assertFalse(R.claims())


    def test_pair_end_callback_defers_past_outer_profile_lock_during_restart(self):
        from app.core.keyed_lock import keyed_lock
        name, partner, target, _ = authored_pair()
        result = request(name, target, partner=partner)
        A.respond(partner, result["execution_id"], True)
        tick(30)
        tick(2)
        self.assertEqual(R.get(result["execution_id"])["status"], "active")
        held, move, moved, unlock, clock_entered, clock_continue = (Event() for _ in range(6))
        errors = []
        real_clock = A._clock
        def paused_clock(run, now):
            if current_thread().name == "restart-advance":
                clock_entered.set()
                if not clock_continue.wait(10):
                    raise AssertionError("restart clock was not released")
            return real_clock(run, now)
        def moving():
            try:
                with keyed_lock("character_profile", name):
                    held.set()
                    if not move.wait(10):
                        raise AssertionError("room move was not released")
                    F.C.save_character_current_room(name, "adjacent")
                    moved.set()
                    if not unlock.wait(10):
                        raise AssertionError("outer profile lock was not released")
            except BaseException as exc:
                errors.append(exc)
        def advancing():
            try:
                A.advance(F.game_time())
            except BaseException as exc:
                errors.append(exc)
        mover = Thread(target=moving, daemon=True)
        advancer = Thread(target=advancing, name="restart-advance", daemon=True)
        with patch.object(A, "_PROCESS", "pair-end-restart"), patch.object(A, "_clock", side_effect=paused_clock):
            try:
                mover.start()
                self.assertTrue(held.wait(10))
                advancer.start()
                self.assertTrue(clock_entered.wait(10))
                move.set()
                self.assertTrue(moved.wait(10), "owned pair end took its run lock under an outer profile lock")
            finally:
                move.set()
                unlock.set()
                clock_continue.set()
                mover.join(10)
                advancer.join(10)
        self.assertFalse(mover.is_alive())
        self.assertFalse(advancer.is_alive())
        self.assertFalse(errors, errors)
        self.assertFalse(R.claims(result["execution_id"]))

    def test_old_cleanup_cannot_erase_replacement_pose_or_new_owned_way(self):
        for new_run in (False, True):
            name, target, _ = setup_run()
            measured_entry()
            result = request(name, target)
            tick(30)
            tick(2)
            paused, resume = Event(), Event()
            errors = []
            real_release = F.C.release_prop_action_state
            def delayed_release(who, ref):
                if ref == result["execution_id"]:
                    paused.set()
                    if not resume.wait(10):
                        raise AssertionError("old cleanup was not released")
                return real_release(who, ref)
            def cancelling():
                try:
                    A.cancel(name, result["execution_id"])
                except BaseException as exc:
                    errors.append(exc)
            worker = Thread(target=cancelling, daemon=True)
            with patch.object(F.C, "release_prop_action_state", side_effect=delayed_release):
                try:
                    worker.start()
                    self.assertTrue(paused.wait(10))
                    F.C.set_pose_intent(name, "standing")
                    F.C.set_character_pos(name, 2, 3)
                    if new_run:
                        replacement = request(name, target)
                        self.assertEqual(replacement["status"], "approaching", replacement)
                    expected = F.C.get_character_profile(name)
                    position = F.C.get_character_pos(name)
                finally:
                    resume.set()
                    worker.join(10)
            self.assertFalse(worker.is_alive())
            self.assertFalse(errors, errors)
            actual = F.C.get_character_profile(name)
            self.assertEqual(actual.get("pose_key"), expected.get("pose_key"))
            self.assertEqual(actual.get("place"), expected.get("place"))
            self.assertEqual(actual.get("journey"), expected.get("journey"))
            self.assertEqual(F.C.get_character_pos(name), position)
            if new_run:
                A.cancel(name, replacement["execution_id"])

    def sleep_at_pending_boundary(self):
        name, target, pid = setup_run("sleep")
        doc = F.props.read_sidecar(pid)
        doc["actions"][0]["pose_key"] = "sleeping"
        doc["model_variants"][0]["markers"][0]["group"] = "lie"
        F.props._write_sidecar(pid, doc)
        target["definition_revision"] = F.props.get_prop(pid)["revision"]
        measured_entry("sleeping")
        result = request(name, target)
        tick(30)
        return name, target, result

    def test_restart_executes_persisted_pending_real_sleep_transition(self):
        name, target, result = self.sleep_at_pending_boundary()
        class ProcessStop(BaseException):
            pass
        with patch.object(F.C, "set_is_sleeping", side_effect=ProcessStop):
            with self.assertRaises(ProcessStop):
                tick(2)
        row = R.get(result["execution_id"])
        self.assertEqual(row["phase"], "sleep_pending")
        self.assertFalse(F.C.is_character_sleeping(name))
        self.assertEqual(F.C.get_character_profile(name)["place"]["execution_id"], row["execution_id"])
        with patch.object(A, "_PROCESS", "sleep-pending-restart"):
            F.set_game_time(F.game_time() + GameDuration.of(hours=12))
            A.advance(F.game_time())
        self.assertTrue(F.C.is_character_sleeping(name))
        self.assertEqual(R.get(row["execution_id"])["status"], "sleeping")
        self.assertEqual(F.C.get_character_current_location(name), target["location_id"])
        self.assertEqual(len(R.claims(row["execution_id"])), 2)

    def test_atomic_sleep_cleanup_rollback_and_post_commit_restart_protect_new_sleep(self):
        from contextlib import contextmanager
        name, _, result = self.sleep_at_pending_boundary()
        tick(2)
        real_transaction = F.C.transaction
        @contextmanager
        def stopped_transaction():
            with real_transaction() as conn:
                yield conn
                raise RuntimeError("crash before cleanup transaction commit")
        with patch.object(F.C, "transaction", stopped_transaction):
            with self.assertRaises(RuntimeError):
                A.cancel(name, result["execution_id"])
        self.assertTrue(F.C.is_character_sleeping(name))
        self.assertEqual(F.C.get_character_profile(name)["place"]["execution_id"], result["execution_id"])
        class ProcessStop(BaseException):
            pass
        with patch.object(R, "cleanup_finished", side_effect=ProcessStop):
            with self.assertRaises(ProcessStop):
                A.advance(F.game_time())
        self.assertFalse(F.C.is_character_sleeping(name), "bed removal and canonical wake must share a commit")
        self.assertFalse(F.C.get_character_profile(name).get("place"))
        F.C.set_is_sleeping(name, True)
        replacement = F.C.get_character_profile(name)
        position = F.C.get_character_pos(name)
        with patch.object(A, "_PROCESS", "cleanup-restart"):
            A.advance(F.game_time())
        self.assertTrue(F.C.is_character_sleeping(name))
        self.assertEqual(F.C.get_character_profile(name).get("place"), replacement.get("place"))
        self.assertEqual(F.C.get_character_pos(name), position)
        self.assertFalse(R.get(result["execution_id"])["data"]["cleanup_pending"])
        F.C.set_is_sleeping(name, False)

    def test_gender_assigned_pair_owns_correct_role_access_and_slots_before_walking(self):
        name, partner, target, _ = authored_pair()
        for who, gender in ((name, "female"), (partner, "male")):
            profile = F.C.get_character_profile(who)
            profile["gender"] = gender
            F.C.save_character_profile(who, profile)
        path = F.ROOT / "clips/run-pair.json"
        meta = json.loads(path.read_text())
        meta["role_gender"] = {"a": "male", "b": "female"}
        path.write_text(json.dumps(meta))
        result = request(name, target, partner=partner)
        A.respond(partner, result["execution_id"], True)
        run = R.get(result["execution_id"])
        self.assertEqual(run["data"]["clip_roles"], {"a": partner, "b": name})
        self.assertEqual(run["data"]["plans"]["actor"]["entry_anchor"]["slot"], 1)
        self.assertEqual(run["data"]["plans"]["partner"]["entry_anchor"]["slot"], 0)
        self.assertEqual(F.E.get_journey(name)["approach_role"], "partner")
        self.assertEqual(F.E.get_journey(partner)["approach_role"], "actor")
        tick(30)
        tick(2)
        run = R.get(result["execution_id"])
        self.assertEqual(run["status"], "active", run)
        self.assertEqual((F.C.get_character_profile(name)["interaction"]["role"],
                          F.C.get_character_profile(partner)["interaction"]["role"]), ("b", "a"))
        self.assertEqual((run["actor"], run["partner"]), (name, partner))

    def test_restart_preserves_travel_checkpoint_ahead_of_run_tick_and_reanchor_crash(self):
        name, target, _ = setup_run()
        # A genuinely longer timed route makes t10 and t15 interior points.
        previous = F.WORLD_CONFIG.read_text()
        settings = json.loads(previous)
        settings["game"] = {"travel_speed_m_s": .2}
        F.WORLD_CONFIG.write_text(json.dumps(settings))
        F.config.load(F.WORLD_CONFIG)
        try:
            result = request(name, target)
        finally:
            F.WORLD_CONFIG.write_text(previous)
            F.config.load(F.WORLD_CONFIG)
        stamp = F.game_time()
        F.set_game_time(stamp + GameDuration.of(seconds=10))
        F.E.advance_all_journeys()
        at_ten = F.C.get_character_pos(name)
        journey = F.E.get_journey(name)
        self.assertEqual(journey["position_checkpoint_game"], F.game_time().canonical())
        self.assertEqual(R.get(result["execution_id"])["data"]["last_game"], stamp.canonical())
        class ProcessStop(BaseException):
            pass
        F.set_game_time(stamp + GameDuration.of(seconds=100))
        with patch.object(A, "_PROCESS", "checkpoint-restart-1"), patch.object(A, "_save", side_effect=ProcessStop):
            with self.assertRaises(ProcessStop):
                A.advance(F.game_time())
        F.set_game_time(stamp + GameDuration.of(seconds=110))
        with patch.object(A, "_PROCESS", "checkpoint-restart-2"):
            A.advance(F.game_time())
            self.assertEqual(F.C.get_character_pos(name), at_ten)
            F.set_game_time(stamp + GameDuration.of(seconds=115))
            F.E.advance_all_journeys()
            after = F.C.get_character_pos(name)
            self.assertGreater(after["x"], at_ten["x"], "resumed way went backwards over its t10 checkpoint")
            stored = F.E.get_journey(name)
            self.assertEqual(stored["position_checkpoint_game"], F.game_time().canonical())
            expected = F.E.journey_state(stored["waypoints"], stored["started_at_game"], F.game_time())["pos"]
            self.assertAlmostEqual(after["x"], expected[0], places=2)
            self.assertAlmostEqual(after["z"], expected[1], places=2)

    def test_acceptance_enforces_consent_expiry_without_periodic_tick(self):
        name, partner, target, _ = authored_pair()
        result = request(name, target, partner=partner)
        F.set_game_time(F.game_time() + GameDuration.of(seconds=299))
        A.advance(F.game_time())
        self.assertEqual(R.get(result["execution_id"])["data"]["consent_elapsed"], 299)
        F.set_game_time(F.game_time() + GameDuration.of(seconds=2))
        before = {who: F.C.get_character_profile(who) for who in (name, partner)}
        expired = A.respond(partner, result["execution_id"], True)
        self.assertEqual((expired["status"], expired["reason"]), ("cancelled", "consent_expired"))
        self.assertFalse(R.claims())
        self.assertEqual({who: F.C.get_character_profile(who) for who in (name, partner)}, before)


    def test_cleanup_standing_preserves_concurrent_manual_position_and_origin(self):
        for same_xz in (False, True):
            name, target, _ = setup_run()
            measured_entry()
            result = request(name, target)
            tick(30)
            tick(2)
            initial = F.C.get_character_pos(name)
            F.C.set_character_pos(name, initial["x"], initial["z"], preserve_movement_target=True,
                                  origin=("owned-position", 1))
            calculated, resume = Event(), Event()
            errors = []
            real_stand = F.S.free_stand_point
            def paused_stand(*args, **kwargs):
                point = real_stand(*args, **kwargs)
                if current_thread().name == "paused-owned-standing":
                    calculated.set()
                    if not resume.wait(10):
                        raise AssertionError("standing calculation was not released")
                return point
            def cancelling():
                try:
                    A.cancel(name, result["execution_id"])
                except BaseException as exc:
                    errors.append(exc)
            worker = Thread(target=cancelling, name="paused-owned-standing", daemon=True)
            with patch.object(F.S, "free_stand_point", side_effect=paused_stand):
                try:
                    worker.start()
                    self.assertTrue(calculated.wait(10))
                    self.assertFalse(R.claims(result["execution_id"]))
                    self.assertEqual(F.C.get_character_profile(name)["place"]["execution_id"], result["execution_id"])
                    x, z = (initial["x"], initial["z"]) if same_xz else (2, 3)
                    F.C.set_character_pos(name, x, z, origin=("manual-position", 7))
                    # The actual canonical manual writer intentionally leaves
                    # the old solo place/pose intact in this terminal window.
                    self.assertEqual(F.C.get_character_profile(name)["place"]["execution_id"], result["execution_id"])
                    manual = tuple(F.db.get_connection().execute(
                        "SELECT pos_x,pos_z,pos_session,pos_seq FROM character_state WHERE character_name=?",
                        (name,)).fetchone())
                finally:
                    resume.set()
                    worker.join(10)
            self.assertFalse(worker.is_alive())
            self.assertFalse(errors, errors)
            actual = tuple(F.db.get_connection().execute(
                "SELECT pos_x,pos_z,pos_session,pos_seq FROM character_state WHERE character_name=?",
                (name,)).fetchone())
            self.assertEqual(actual, manual)
            self.assertEqual(actual, (x, z, "manual-position", 7))
            self.assertFalse(F.C.get_character_profile(name).get("place"))
            self.assertEqual(F.C.get_character_profile(name).get("pose_key"), "")

    def test_removed_authored_marker_keeps_furniture_and_releases_to_walkable_floor(self):
        name, target, pid = setup_run()
        measured_entry()
        result = request(name, target)
        tick(30)
        tick(2)
        original = F.props.read_sidecar(pid)
        saved = F.props.bulk_update(pid, base_revision=F.props._document_revision(original),
            variants={F.UID: {"markers": []}}, actions=[])
        self.assertTrue(saved)
        geometry = F.S.room_geometry(target["location_id"], target["room_id"])
        box = next(b for b in geometry[1] if b["placement_id"] == "device")
        self.assertEqual((box["width_m"], box["depth_m"]), (1, 1))
        before = F.C.get_character_pos(name)
        self.assertTrue(F.S._in_footprint(before["x"], before["z"], box, F.S.BODY_R_M))
        tick(1)
        row = R.get(result["execution_id"])
        self.assertEqual(row["status"], "failed", row)
        self.assertFalse(R.claims(result["execution_id"]))
        self.assertFalse(F.C.get_character_profile(name).get("place"))
        after = F.C.get_character_pos(name)
        self.assertFalse(F.S._in_footprint(after["x"], after["z"], box, F.S.BODY_R_M))
        variant = original["model_variants"][0]
        variant["markers"][0]["id"] = "replacement"
        current = F.props.read_sidecar(pid)
        saved = F.props.bulk_update(pid, base_revision=F.props._document_revision(current),
            variants={F.UID: {"markers": variant["markers"]}},
            actions=original["actions"])
        target["definition_revision"] = saved["revision"]
        restarted = request(name, target)
        self.assertEqual(restarted["status"], "approaching", restarted)
        self.assertEqual(F.E.get_journey(name)["approach_target"]["marker_id"], "replacement")


def execution_scenario(stage):
    """Real process stops/restarts, actual arrival receipts and partial phases."""
    path = F.ROOT / "execution.json"
    if stage == "sleep-pending-stop":
        name, target, pid = setup_run("sleep")
        doc = F.props.read_sidecar(pid)
        doc["actions"][0]["pose_key"] = "sleeping"
        doc["model_variants"][0]["markers"][0]["group"] = "lie"
        F.props._write_sidecar(pid, doc)
        target["definition_revision"] = F.props.get_prop(pid)["revision"]
        measured_entry("sleeping")
        result = request(name, target)
        tick(30)
        def stop_before_real_flag(*args, **kwargs):
            data = json.loads(path.read_text())
            data.update(sleep_actor=name, sleep_run=result["execution_id"],
                        pending_sleep=R.get(result["execution_id"]))
            if data["pending_sleep"]["phase"] != "sleep_pending" or F.C.is_character_sleeping(name):
                raise RuntimeError("sleep transition was not durably pending")
            path.write_text(json.dumps(data, indent=2))
            F.assert_no_external_work()
            os._exit(0)
        F.C.set_is_sleeping = stop_before_real_flag
        tick(2)
        raise RuntimeError("real pending sleep boundary was not reached")
    if stage == "sleep-resume-stop":
        data = json.loads(path.read_text())
        A.advance(F.game_time())
        name, ref = data["sleep_actor"], data["sleep_run"]
        if R.get(ref)["status"] != "sleeping" or not F.C.is_character_sleeping(name):
            raise RuntimeError("pending canonical sleep was not recovered")
        data["recovered_sleep"] = R.get(ref)
        def stop_after_atomic_wake(ref):
            if F.C.is_character_sleeping(name) or F.C.get_character_profile(name).get("place"):
                raise RuntimeError("wake and place removal did not commit atomically")
            data["atomic_wake_before_stop"] = dict(run=R.get(ref), profile=F.C.get_character_profile(name))
            path.write_text(json.dumps(data, indent=2))
            F.assert_no_external_work()
            os._exit(0)
        R.cleanup_finished = stop_after_atomic_wake
        A.cancel(name, ref)
        raise RuntimeError("real atomic wake boundary was not reached")
    if stage == "sleep-cleanup-resume":
        data = json.loads(path.read_text())
        name, ref = data["sleep_actor"], data["sleep_run"]
        if F.C.is_character_sleeping(name):
            raise RuntimeError("restart found an orphan sleeping flag")
        # A genuine replacement sleep is independent of the old terminal run.
        F.C.set_is_sleeping(name, True)
        replacement, position = F.C.get_character_profile(name), F.C.get_character_pos(name)
        A.advance(F.game_time())
        if (not F.C.is_character_sleeping(name) or F.C.get_character_profile(name).get("place") != replacement.get("place")
                or F.C.get_character_pos(name) != position or R.get(ref)["data"]["cleanup_pending"]):
            raise RuntimeError("old cleanup changed a replacement sleep")
        data["sleep_cleanup_recovery"] = R.get(ref)
        data["replacement_sleep_preserved"] = F.C.get_character_profile(name)
        F.C.set_is_sleeping(name, False)
        path.write_text(json.dumps(data, indent=2))
        F.assert_no_external_work()
        return
    if stage == "missing-target":
        name, target, pid = setup_run()
        result = request(name, target)
        if result["status"] != "approaching":
            raise RuntimeError(result)
        doc = F.props.read_sidecar(pid)
        doc["model_variants"][0]["uid"] = "22222222-2222-4222-8222-222222222222"
        F.props._write_sidecar(pid, doc)
        data = json.loads(path.read_text())
        data["missing_run"] = result["execution_id"]
        path.write_text(json.dumps(data, indent=2))
        F.assert_no_external_work()
        return
    if stage == "missing-resume":
        data = json.loads(path.read_text())
        A.advance(F.game_time())
        run = R.get(data["missing_run"])
        if run["status"] != "failed" or R.claims(run["execution_id"]):
            raise RuntimeError(run)
        data["missing_target_recovery"] = run
        path.write_text(json.dumps(data, indent=2))
        F.assert_no_external_work()
        return
    if stage == "arrive-crash":
        name, target, _ = setup_run("combined")
        measured_entry()
        result = request(name, target)
        if result["status"] != "approaching":
            raise RuntimeError(result)
        path.write_text(json.dumps(dict(actor=name, target=target, execution_id=result["execution_id"],
                                        snapshots=[R.get(result["execution_id"])]), indent=2))
        # The real travel engine commits position + last_journey_result before
        # invoking this boundary. No receipt is authored by this scenario.
        def crash_after_actual_receipt(*args):
            F.assert_no_external_work()
            os._exit(0)
        A._arrived = crash_after_actual_receipt
        tick(30)
        raise RuntimeError("real arrival never reached its callback")
    data = json.loads(path.read_text())
    run = R.get(data["execution_id"])
    A.register_owner()
    if stage == "terminal":
        if run["status"] != "completed" or R.claims(run["execution_id"]):
            raise RuntimeError("terminal execution reopened after process restart")
        A.advance(F.game_time() + GameDuration.of(hours=12))
        data["terminal_restart"] = R.get(run["execution_id"])
    else:
        profile = F.C.get_character_profile(data["actor"])
        receipt = profile.get("last_journey_result") or {}
        if receipt.get("execution_ref") != run["execution_id"] or receipt.get("status") != "arrived":
            raise RuntimeError("missing real persisted Core arrival receipt")
        # World time was stopped by process termination; an explicit large
        # game-clock jump models server downtime and must earn no active time.
        F.set_game_time(F.game_time() + GameDuration.of(hours=12))
        A.advance(F.game_time())
        data["snapshots"].append(R.get(run["execution_id"]))
        if stage == "resume-entry":
            tick(2)
            tick(3)
            active = R.get(run["execution_id"])
            if active["phase"] != "prepare" or active["data"]["phase_elapsed"] != 3:
                raise RuntimeError(active)
            data["snapshots"].append(active)
            data["active_before_stop"] = active["data"]["phase_elapsed"]
            path.write_text(json.dumps(data, indent=2))
            F.assert_no_external_work()
            os._exit(0)
        if R.get(run["execution_id"])["data"]["phase_elapsed"] != data["active_before_stop"]:
            raise RuntimeError("restart applied an offline phase bonus")
        tick(2)
        tick(5)
        tick(5)
        data["snapshots"].append(R.get(run["execution_id"]))
        if data["snapshots"][-1]["status"] != "completed" or R.claims(run["execution_id"]):
            raise RuntimeError(data["snapshots"][-1])
        data["actual_receipt"] = receipt
        data["actual_position"] = F.C.get_character_pos(data["actor"])
    F.assert_no_external_work()
    path.write_text(json.dumps(data, indent=2))


if __name__ == "__main__":
    if OPTIONS_ARGS.scenario_stage:
        execution_scenario(OPTIONS_ARGS.scenario_stage)
    else:
        unittest.main(argv=[sys.argv[0], *F.REST])
