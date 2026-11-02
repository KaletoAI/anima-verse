#!/usr/bin/env python3
"""Follow pose after the normal end of a pose or action (plan-folge-pose.md F1).

Usage: ./.venv/bin/python scripts/smoke_follow_pose.py

Runs on the private furniture fixture of smoke_prop_action_runs (temporary
storage + instance, no server, no real world). Expected values, by hand:

[1] CATALOG. ``follow_pose`` is trimmed/lower case; ``{a, b}`` keeps per
    clip role. ``follow_pose_for`` order: the field, then the provider
    ``pose.follow_pose``, then the place type's ``follow`` (shared seed
    seat -> sitting, lie -> lying). A pose never follows itself (sitting
    ends -> ""), a pair pose is no follow (-> ""), an unknown key -> "".
[2] VALIDATION. A -> B -> A is reported once as a circle; ``{a, b}`` on a
    solo pose and a follow naming a pair pose are reported.
[3] BED PAIR, TWO SLOTS. The fixture seat: capacity 2, slots 0.6 m apart
    (spacing_m .6), clip halves at -0.3 / +0.3 m of the anchor — every
    figure sits ON a slot. The pair pose ``run-pair`` (seat) has no field,
    so seat -> ``sitting`` applies to both roles. The actor ends it
    (``cancel`` = normal end): the pair run completes, and TWO new runs of
    the piece's solo action ``sit`` (pose sitting) go active in place, one
    per person, each on the slot it already sat on (distance 0 < 0.6 to the
    other slot), ``follow_of`` = the pair run. Both are NPCs: limit 1200 s.
[4] ONE SEAT. The shared-seat pair (``places`` 1, capacity 1, halves at
    +-0.094 m — both 0.094 m from the one slot, a tie the name order
    breaks): exactly ONE follow run, for the first name; the other stands
    (no place, an exit motion recorded on the pair run).
[5] NO FOLLOW. A manual position change (walking off) cancels the pair:
    no follow run. Asking for another action of the piece while seated
    (``_replace``) ends the old run without a follow: one live run only.
[6] NPC LIMIT. A follow run of an NPC ends after 1200 game seconds with
    reason ``follow_elapsed`` — and no further follow (sitting -> "").
[7] FREE PAIR. A free pair pose ``free-pair`` (stand) with follow
    ``kneeling`` (ground, needs no place) ends by "avatar": both kneel,
    each with a ``follow_pose_until`` 1200 s ahead; ``expire_follow_poses``
    before that changes nothing, after it clears both poses. An end by
    "moved" gives no follow.
[8] FINISH. ``/play/self/activity`` with ``finish``: a free ``dancing``
    with follow ``kneeling`` goes into kneeling; without a follow it clears.
    The HUD offer (``/play/self`` ``follow``, F3) names ``kneeling`` for the
    free ``dancing`` and nothing once kneeling, and nothing while a furniture
    action holds the avatar (it ends through its own path).
[9] BRIDGE RULES FOR THE CLIENTS (F2). The clients play a pair half as
    ``<kind>__<role>`` and keep that as the clip they leave. A rule
    ``run-pair -> sitting`` with bridge ``run-up`` therefore reaches them as
    ``run-pair__a -> sit`` and ``run-pair__b -> sit``, both ``run-up`` — and,
    with the finale ``run-pair-end``, ``run-pair-end__a/b -> sit`` too: 4 rows.
    A per-role bridge ``{a: run-up, b: run-up-b}`` gives the b halves
    ``run-up-b``; ``{a: run-up}`` alone leaves the b halves out (2 rows).
    A solo pose with a finale (``dancing`` -> ``run-end``) names both its own
    clip ``dance`` and ``run-end`` as ``from`` (to ``kneeling``, its own kind).
[10] VALIDATION. A per-role bridge on a solo ``from`` is refused; a per-role
    bridge naming a clip no library has is refused; the world table stores
    the map and reads it back equal.
"""
import json
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_prop_action_runs as RUNS                                 # noqa: E402

F, A, R, clips, pose_catalog = RUNS.F, RUNS.A, RUNS.R, RUNS.clips, RUNS.pose_catalog
from app.core import paths                                            # noqa: E402
paths.init(F.ROOT / "world")    # the fixture's private world, named here once more
from app.core import hooks                                            # noqa: E402
from app.core.game_time import GameDuration                           # noqa: E402

SIT = {"id": "sit", "name": "Sit", "description": "Fixture follow", "enabled": True,
       "ability": "pose", "pose_key": "sitting", "participants": 1,
       "presence": "any", "interrupt_on_presence_change": False,
       "phases": [], "requirements": [], "effects": []}


def set_entry(key, **fields):
    entries = pose_catalog.world_entries("pose")
    if key not in entries:
        entries[key] = dict(pose_catalog._read_shared("pose")["entries"].get(key) or {})
    for field, value in fields.items():
        if value is None:
            entries[key].pop(field, None)
        else:
            entries[key][field] = value
    pose_catalog.replace_world_entries("pose", entries)
    pose_catalog.reload_catalogs()


def with_sit_action(pid, target):
    """The piece gets a solo ``sit`` beside its pair action, and entries for
    both poses (the direct switch still asks for an entry capability)."""
    doc = F.props.read_sidecar(pid)
    doc["actions"].append(dict(SIT))
    # Automatic access per slot, as on a real piece: the fixture's fixed
    # per-role points would send a solo action of slot 1 to slot 0's side.
    doc["model_variants"][0]["markers"][0].pop("access", None)
    F.props._write_sidecar(pid, doc)
    target["definition_revision"] = F.props.get_prop(pid)["revision"]
    clips._write_world_transitions([{"from": "walking", "to": pose, "kind": "run-enter", "accel": 0}
                                    for pose in ("run-pair", "sitting")])


def active_pair(shared=False):
    name, partner, target, pid = (RUNS.authored_shared_pair() if shared else RUNS.authored_pair())
    with_sit_action(pid, target)
    result = RUNS.request(name, target, partner=partner)
    A.respond(partner, result["execution_id"], True)
    for _ in range(40):
        RUNS.tick(2)
        if R.get(result["execution_id"])["status"] == "active":
            break
    run = R.get(result["execution_id"])
    assert run["status"] == "active", run
    return name, partner, target, pid, run


def follow_runs(old_id):
    return [r for r in R.live_runs() if r["data"].get("follow_of") == old_id]


class FollowPose(unittest.TestCase):
    tearDown = RUNS.Runs.tearDown

    def test_1_catalog(self):
        RUNS.authored_pair()
        set_entry("dancing", follow_pose="  Kneeling ")
        self.assertEqual(pose_catalog.get_catalog("pose")["dancing"]["follow_pose"], "kneeling")
        self.assertEqual(pose_catalog.follow_pose_for("dancing"), "kneeling")
        set_entry("run-pair", follow_pose={"a": "Sitting", "b": " kneeling"})
        self.assertEqual(pose_catalog.get_catalog("pose")["run-pair"]["follow_pose"],
                         {"a": "sitting", "b": "kneeling"})
        self.assertEqual(pose_catalog.follow_pose_for("run-pair", "a"), "sitting")
        self.assertEqual(pose_catalog.follow_pose_for("run-pair", "b"), "kneeling")
        set_entry("run-pair", follow_pose=None)
        # Without the field: the provider, then the place type.
        self.assertEqual(pose_catalog.follow_pose_for("run-pair", "a"), "sitting")
        hooks.register_provider("pose.follow_pose", lambda **kw: "kneeling" if kw["group"] == "seat" else "")
        try:
            self.assertEqual(pose_catalog.follow_pose_for("run-pair", "b"), "kneeling")
        finally:
            hooks._providers.pop("pose.follow_pose", None)
        self.assertEqual(pose_catalog.follow_pose_for("sitting"), "")        # never itself
        self.assertEqual(pose_catalog.follow_pose_for("lying"), "")
        set_entry("dancing", follow_pose="run-pair")                         # a pair pose is no follow
        self.assertEqual(pose_catalog.follow_pose_for("dancing"), "")
        self.assertEqual(pose_catalog.follow_pose_for("no-such-pose"), "")
        set_entry("dancing", follow_pose=None)

    def test_2_validation(self):
        RUNS.authored_pair()
        set_entry("dancing", follow_pose="kneeling")
        set_entry("kneeling", follow_pose="dancing")
        problems = pose_catalog.validate_catalog("pose")
        circles = [p for p in problems if "circle" in p]
        self.assertEqual(len(circles), 1, problems)
        set_entry("kneeling", follow_pose={"a": "sitting"})
        set_entry("dancing", follow_pose="run-pair")
        problems = pose_catalog.validate_catalog("pose")
        self.assertIn("pose/kneeling: a per-role follow pose only makes sense on a pair pose", problems)
        self.assertIn("pose/dancing: follow pose 'run-pair' is not a solo pose", problems)
        set_entry("dancing", follow_pose=None)
        set_entry("kneeling", follow_pose=None)
        self.assertFalse([p for p in pose_catalog.validate_catalog("pose") if "follow" in p])

    def test_3_two_slot_pair_both_stay(self):
        name, partner, target, pid, run = active_pair()
        before = {n: F.C.get_character_pos(n) for n in (name, partner)}
        released = []
        release = F.C.release_prop_action_state

        def spy(person, execution_id):
            released.append((person, execution_id))
            return release(person, execution_id)
        with patch.object(F.C, "release_prop_action_state", spy):
            A.cancel(name, run["execution_id"])
        # Nobody got up in between: the pair's places went straight over.
        self.assertFalse([r for r in released if r[1] == run["execution_id"]], released)
        old = R.get(run["execution_id"])
        self.assertEqual((old["status"], old["reason"]), ("completed", "ended"))
        follows = {r["actor"]: r for r in follow_runs(run["execution_id"])}
        self.assertEqual(set(follows), {name, partner})
        slots = set()
        for person, follow in follows.items():
            self.assertEqual((follow["status"], follow["action_id"]), ("active", "sit"))
            self.assertEqual(follow["data"]["follow_limit_s"], 1200)
            profile = F.C.get_character_profile(person)
            self.assertEqual(profile["pose_key"], "sitting")
            self.assertEqual(profile["place"]["execution_id"], follow["execution_id"])
            anchor = follow["data"]["plans"]["actor"]["entry_anchor"]
            self.assertLess(F.math.dist((anchor["x"], anchor["z"]),
                                        (before[person]["x"], before[person]["z"])), .05)
            slots.add(anchor["slot"])
        self.assertEqual(slots, {0, 1})
        self.assertFalse(old["data"].get("exit_motions"))

    def test_4_one_seat_keeps_one(self):
        name, partner, target, pid, run = active_pair(shared=True)
        A.cancel(partner, run["execution_id"])
        follows = follow_runs(run["execution_id"])
        first, second = sorted((name, partner))
        self.assertEqual([r["actor"] for r in follows], [first])
        self.assertEqual(follows[0]["status"], "active")
        self.assertIsNone(F.C.get_character_profile(second).get("place"))
        self.assertIn(second, R.get(run["execution_id"])["data"].get("exit_motions", {}))

    def test_5_walking_off_and_replacement_have_no_follow(self):
        name, partner, target, pid, run = active_pair()
        F.C.set_character_pos(name, 2, 2)
        self.assertEqual(R.get(run["execution_id"])["status"], "cancelled")
        self.assertFalse(follow_runs(run["execution_id"]))
        # Seated alone in the sit action, asking for the pair's piece again:
        # a replacement, not an end — one live run.
        name, target, pid = RUNS.setup_run()
        doc = F.props.read_sidecar(pid)
        doc["actions"].append(dict(SIT, id="sit-2", name="Sit again"))
        F.props._write_sidecar(pid, doc)
        target["definition_revision"] = F.props.get_prop(pid)["revision"]
        first = RUNS.request(name, target)
        for _ in range(40):
            RUNS.tick(2)
            if R.get(first["execution_id"])["status"] == "active":
                break
        second = A.request(name, {k: target[k] for k in ("location_id", "room_id", "placement_id", "variant_uid")},
                           "sit-2", target["definition_revision"])
        self.assertNotEqual(second["status"], "refused", second)
        self.assertEqual(R.get(first["execution_id"])["status"], "completed")
        self.assertFalse(follow_runs(first["execution_id"]))
        self.assertEqual([r["execution_id"] for r in R.live_runs()], [second["execution_id"]])

    def test_6_npc_limit(self):
        name, partner, target, pid, run = active_pair()
        A.cancel(name, run["execution_id"])
        follows = follow_runs(run["execution_id"])
        self.assertEqual(len(follows), 2)
        RUNS.tick(1199)
        self.assertEqual({R.get(f["execution_id"])["status"] for f in follows}, {"active"})
        RUNS.tick(2)
        for follow in follows:
            row = R.get(follow["execution_id"])
            self.assertEqual((row["status"], row["reason"]), ("completed", "follow_elapsed"))
            self.assertFalse(follow_runs(follow["execution_id"]))
            self.assertIsNone(F.C.get_character_profile(follow["actor"]).get("place"))

    def free_pair(self):
        from app.core import interaction_engine as IE
        name, target, pid = RUNS.setup_run()
        partner = F.actor(target["location_id"], at=(1.6, 5))
        set_entry("free-pair", solo=False, animation="free-pair", group="stand", places=2,
                  prompt="Two people dancing", follow_pose="kneeling")
        directory = F.ROOT / "clips"
        for role in ("a", "b"):
            (directory / f"free-pair__{role}.fbx").write_bytes(b"private pair fixture")
        (directory / "free-pair.json").write_text(json.dumps(dict(
            kind="free-pair", pair=True, duration_s=2, loop=True,
            geometry=dict(roles=dict(a=dict(anchor_xz_m=[-.3, 0]), b=dict(anchor_xz_m=[.3, 0]))))))
        clips._clear_entries_cache()
        inter = IE.start_interaction(name, partner, "free-pair")
        return IE, name, partner, inter

    def test_7_free_pair(self):
        IE, name, partner, inter = self.free_pair()
        self.assertTrue(IE.end_interaction(name, reason="avatar"))
        start = F.game_time()
        for person in (name, partner):
            profile = F.C.get_character_profile(person)
            self.assertEqual(profile["pose_key"], "kneeling")
            mark = profile["follow_pose_until"]
            self.assertEqual(mark["pose_key"], "kneeling")
            self.assertEqual(mark["until_game"], (start + GameDuration.of(seconds=1200)).canonical())
        self.assertEqual(IE.expire_follow_poses(), 0)
        F.set_game_time(start + GameDuration.of(seconds=1200))
        self.assertEqual(IE.expire_follow_poses(), 2)
        for person in (name, partner):
            profile = F.C.get_character_profile(person)
            self.assertEqual(profile.get("pose_key") or "", "")
            self.assertNotIn("follow_pose_until", profile)
        IE, name, partner, inter = self.free_pair()
        IE.end_interaction(name, reason="moved")
        self.assertEqual({F.C.get_character_profile(p).get("pose_key") or "" for p in (name, partner)}, {""})

    def test_8_finish(self):
        from app.routes import play
        name, target, pid = RUNS.setup_run()
        set_entry("dancing", follow_pose="kneeling")
        F.C.set_pose_intent(name, "dancing")
        self.assertEqual(play._free_pose_follow(name), "kneeling")
        with patch("app.core.prop_action_engine.has_semantic_action", lambda actor: True):
            self.assertEqual(play._free_pose_follow(name), "")
        self.assertTrue(play._finish_into_follow(name))
        self.assertEqual(F.C.get_character_profile(name)["pose_key"], "kneeling")
        self.assertEqual(play._free_pose_follow(name), "")
        self.assertFalse(play._finish_into_follow(name))      # kneeling has no follow
        set_entry("dancing", follow_pose=None)


def bridge_clips():
    directory = F.ROOT / "clips"
    directory.mkdir(exist_ok=True)
    for kind in ("run-up", "run-up-b", "run-end"):
        (directory / f"{kind}.fbx").write_bytes(b"private bridge fixture")
        (directory / f"{kind}.json").write_text(json.dumps(dict(kind=kind, duration_s=1.2, loop=False)))
    for role in ("a", "b"):
        (directory / f"run-pair-end__{role}.fbx").write_bytes(b"private finale fixture")
    (directory / "run-pair-end.json").write_text(json.dumps(dict(
        kind="run-pair-end", pair=True, duration_s=1.5, loop=False)))
    clips._clear_entries_cache()


class FollowBridge(unittest.TestCase):
    tearDown = RUNS.Runs.tearDown

    def rows(self, kind, **extra):
        rules = [dict(dict(extra.get("rule") or {}), **{"from": "run-pair", "to": "sitting", "kind": kind,
                                                       "accel": 0})]
        return [(r["from"], r["to"], r["kind"]) for r in clips.client_transition_rules(rules)]

    def test_9_pair_halves_and_finale(self):
        RUNS.authored_pair()
        bridge_clips()
        set_entry("run-pair", finale_animation=None)
        self.assertEqual(self.rows("run-up"), [("run-pair__a", "sit", "run-up"), ("run-pair__b", "sit", "run-up")])
        set_entry("run-pair", finale_animation="run-pair-end")
        self.assertEqual(self.rows("run-up"), [
            ("run-pair__a", "sit", "run-up"), ("run-pair__b", "sit", "run-up"),
            ("run-pair-end__a", "sit", "run-up"), ("run-pair-end__b", "sit", "run-up")])
        self.assertEqual(self.rows({"a": "run-up", "b": "run-up-b"}), [
            ("run-pair__a", "sit", "run-up"), ("run-pair__b", "sit", "run-up-b"),
            ("run-pair-end__a", "sit", "run-up"), ("run-pair-end__b", "sit", "run-up-b")])
        self.assertEqual(self.rows({"a": "run-up"}), [
            ("run-pair__a", "sit", "run-up"), ("run-pair-end__a", "sit", "run-up")])
        set_entry("run-pair", finale_animation=None)
        set_entry("dancing", finale_animation="run-end")
        solo = clips.client_transition_rules([{"from": "dancing", "to": "kneeling", "kind": "run-up", "accel": 0}])
        self.assertEqual([(r["from"], r["to"], r["kind"]) for r in solo],
                         [("dance", "kneeling", "run-up"), ("run-end", "kneeling", "run-up")])
        set_entry("dancing", finale_animation=None)

    def test_10_validation_and_world_roundtrip(self):
        RUNS.authored_pair()
        bridge_clips()
        with self.assertRaisesRegex(clips.ClipLibraryError, "needs a pair pose"):
            clips._validate_transitions([{"from": "dancing", "to": "sitting", "kind": {"a": "run-up"}}])
        with self.assertRaisesRegex(clips.ClipLibraryError, "no solo clip of kind 'no-such-bridge'"):
            clips._validate_transitions([{"from": "run-pair", "to": "sitting",
                                          "kind": {"a": "run-up", "b": "no-such-bridge"}}])
        saved = clips.replace_world_transitions([{"from": "run-pair", "to": "sitting",
                                                  "kind": {"b": "Run-Up-B", "a": "run-up"}}])
        self.assertEqual(saved[0]["kind"], {"a": "run-up", "b": "run-up-b"})
        self.assertEqual(clips.world_transitions()[0]["kind"], {"a": "run-up", "b": "run-up-b"})
        self.assertEqual(clips.rule_kind(clips.resolve_pose_transition("run-pair", "sitting"), "b"), "run-up-b")
        self.assertEqual(clips.rule_kind(clips.resolve_pose_transition("run-pair", "sitting")), "")
        clips._write_world_transitions([])


if __name__ == "__main__":
    unittest.main(verbosity=2)
