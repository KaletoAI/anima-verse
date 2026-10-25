#!/usr/bin/env python3
"""Smoke movement poses with isolated catalogs, clips and world storage.

Usage: ./.venv/bin/python scripts/smoke_movement_poses.py [--http]
The optional --http also checks the admin router through TestClient.

Hand-derived Task 2 expectations: seven poses map to idle/walk/run/swim/
treading-water/crawl/crawl-rest. Two world overrides affect played kinds
only. Female walk wins over neutral; licensed walk shadows free walk only
when licensed clips are allowed. Missing and pair-only kinds resolve to None.
Task 4: seven fixed keys; four movement-only keys excluded from activities;
world overrides deletable, shipped movement entries protected; one rename/drop rule.
Task 3: sleeping→walking expands to two pairs, the seat wildcard to one;
unknown poses contribute none. Exact beats exit beats enter; accel caps at 8.
Task 6: seven ordered rows; female walk beats neutral licensed walk; missing
swim stays null. Reading resolves played/public separately; unknown is null.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
FAILURES = []


def check(label, ok):
    print(f"{'OK' if ok else 'FAIL'} {label}")
    if not ok:
        FAILURES.append(label)


def transition_checks(ac, path, fixture):
    # By hand: exact beats exit beats enter, regardless of file order.
    rules = [{"from": "*", "to": "walking", "kind": "run"}, {"from": "sitting at table", "to": "*", "kind": "idle"}, {"from": "sitting at table", "to": "walking", "kind": "walk"}]
    ac.save_transitions(rules)
    check("specificity", [ac.resolve_transition(a,b)["kind"] for a,b in [("sitting at table", "walking"), ("sitting at table", "running"), ("standing", "walking")]] == ["walk", "idle", "run"])
    check("empty/same/unruled", all(ac.resolve_transition(a,b) is None for a,b in [("", "walking"), ("walking", ""), ("walking", "walking"), ("standing", "running")]))
    bad_lists = [[dict(fixture[0], kind=k)] for k in ("missing", "pair")]
    bad_lists += [[dict(fixture[0], **changes)] for changes in ({"from": "*", "to": "*"}, {"from": ""}, {"from": "bad/key"}, {"to": "bad*key"})]
    bad_lists += [rules + [rules[0]], {}, [{"from": "sleeping", "kind": "idle"}]]
    for bad in bad_lists:
        try:
            ac.save_transitions(bad)
        except ac.ClipLibraryError:
            check("invalid rule rejected", True)
        else:
            check("invalid rule rejected", False)
    check("refused calls preserve list", len(ac.load_transitions()) == 3)
    check("accel defaults/cap", [ac.save_transitions([dict(fixture[0], accel=v)])[0]["accel"] for v in (None, 1.5, "junk", -2, 0, 99)] == [0, 1.5, 0, 0, 0, 8])
    check("replacement/reload", len(ac.load_transitions()) == 1 and ac.load_transitions()[0]["accel"] == 8)
    path.write_text("junk")
    check("junk file", ac.load_transitions() == [])
    path.write_text(json.dumps({"transitions": [fixture[0], {"from": "sleeping"}, "junk", fixture[0]]}))
    check("junk entries", len(ac.load_transitions()) == 1)
    ac.save_transitions(fixture)
    missing_bridge = [dict(fixture[0], kind="absent-bridge"), fixture[1]]
    path.write_text(json.dumps({"transitions": missing_bridge}))
    check("rename preserves unavailable bridges", ac.rename_transition_pose("sleeping", "asleep") == 1)
    check("drop preserves unavailable bridges", ac.drop_transition_pose("sitting at table") == 1 and ac.load_transitions()[0]["kind"] == "absent-bridge")
    ac.save_transitions(fixture)
    collision = fixture + [dict(fixture[0], kind="get-up-chair")]
    check("annotations/conflict", ac.annotated_transitions(collision)[-1]["conflict"] and ac.annotated_transitions()[0]["bridge_public"])
    check("first wins", ac.client_transition_rules(collision)[0]["kind"] == "get-up-bed")
    check("same clip skipped", ac.client_transition_rules([dict(fixture[0], to="sleeping")]) == [])


def world_transition_checks(ac, fixture):
    """By hand: replacement keeps slot 0; addition follows three seeds.

    A pair present in both stores counts twice for rename/drop. Licensed
    bridges are world-only. Writes use the caller's temporary file and DB.
    """
    ac.save_transitions(fixture)
    override = dict(fixture[0], kind="mob1-walk", accel=1.5)
    extra = {"from": "standing", "to": "walking", "kind": "mob1-walk"}
    ac.replace_world_transitions([override, extra])
    effective = ac.load_transitions()
    check("[T8] world replaces in place", len(effective) == 4 and
          effective[0] == dict(override, store="world") and
          effective[1]["store"] == "shared" and
          ac.resolve_transition("sleeping", "walking")["kind"] == "mob1-walk")
    check("[T9] world-only appended/client", effective[-1]["from"] == "standing" and
          effective[-1]["store"] == "world" and any(
              r["from"] == "idle" and r["to"] == "walk" and r["kind"] == "mob1-walk"
              for r in ac.client_transition_rules()))
    try:
        ac.save_transitions([extra])
    except ac.ClipLibraryError as exc:
        check("[T10] licensed shared refused", str(exc) ==
              "rule 1: bridge clip mob1-walk is licensed — it belongs to the world layer")
    else:
        check("[T10] licensed shared refused", False)
    check("[T10] rejected save preserves layers", ac.load_transitions() == effective)
    for bad in ([override, override], [dict(extra, kind="pair")], [dict(extra, to="*", **{"from": "*"})]):
        try:
            ac.replace_world_transitions(bad)
        except ac.ClipLibraryError:
            check("world validation preserves layer", ac.load_transitions() == effective)
        else:
            check("world validation preserves layer", False)
    ac.replace_world_transitions([])
    check("world deletion restores shared", ac.load_transitions()[0]["kind"] == "get-up-bed" and
          ac.load_transitions()[0]["store"] == "shared")
    ac.save_transitions([dict(extra, store="world")])
    check("[T10] licensed world saved", ac.load_shared_transitions() == [] and
          ac.world_transitions() == [dict(extra, accel=0)] and
          ac.annotated_transitions()[0]["store"] == "world")
    ac.save_transitions(fixture + [dict(override, store="world")])
    check("[T11] rename both layers", ac.rename_transition_pose("sleeping", "asleep") == 2 and
          ac.load_shared_transitions()[0]["from"] == "asleep" and
          ac.world_transitions()[0]["from"] == "asleep")
    check("[T11] drop both layers", ac.drop_transition_pose("asleep") == 2 and
          ac.world_transitions() == [] and len(ac.load_shared_transitions()) == 2)
    # The editor saves the EFFECTIVE list back, where the world rule hides the
    # shared one of its pair: that round trip must leave the seed whole.
    ac.save_transitions(fixture)
    seed = ac.load_shared_transitions()
    ac.replace_world_transitions([override])
    ac.save_transitions(ac.load_transitions())
    check("[T13] editor round trip keeps the hidden shared rule",
          ac.load_shared_transitions() == seed and
          ac.world_transitions() == [dict(override, accel=1.5)])
    ac.replace_world_transitions([])
    ac.save_transitions(fixture)
    repo = Path(__file__).resolve().parents[1]
    free = {e["kind"] for e in ac._scan_library(repo / "shared/models/clips", "free")
            if not e["role"]}
    check("[T12] tracked bridges free", all(r["kind"] in free for r in
          ac.load_shared_transitions(repo / "shared/config/clip_transitions.json")))


def fixed_checks(pc, ac):
    from app.core.movement import MOVEMENT_POSES, MOVEMENT_ONLY_POSES
    from app.core.pose_rename import CODE_NAMED_POSE_KEYS
    check("[F1] code-named", {"running", "swimming", "crawling_rest", "sleeping"} <= CODE_NAMED_POSE_KEYS)
    activity = pc.activity_catalog()
    check("[F2] no activity match", pc.resolve_to_catalog("schwimmen", "pose", _embed=lambda _: None)[0] != "swimming" and not MOVEMENT_ONLY_POSES.intersection(activity))
    check("[F3] still activity", {"standing", "walking", "running"} <= activity.keys())
    check("place activities", not MOVEMENT_ONLY_POSES.intersection(pc.poses_without_place() + pc.poses_in_group("stand") + pc.poses_in_group("ground")))
    embedded = pc._alias_embeddings("pose", lambda _: [1.0, 0.0])
    check("embedding aliases excluded", not ({"schwimmen", *MOVEMENT_ONLY_POSES} & embedded.keys()))
    from app.core.decision_points import catalog_questions
    questions, then = catalog_questions("pose")
    if then:
        from app.core.decision import Answer
        options = set()
        for group in questions["group"].options:
            followup = then({"group": Answer(value=group, p_yes=None, confidence=1.0, distribution={})})
            options.update(followup["entry"].options)
    else:
        options = set(questions["entry"].options)
    check("decision activities", not MOVEMENT_ONLY_POSES.intersection(options))
    from app.core.npc_actions import _solo_pose_keys
    check("solo activities", not MOVEMENT_ONLY_POSES.intersection(_solo_pose_keys()))
    from fastapi import HTTPException
    from app.routes import poses
    pc.replace_world_entries("pose", {"walking": {"animation": "walk", "prompt": "world walking", "group": "stand"}})
    pc.reload_catalogs()
    if "--http" in sys.argv:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.core.auth_dependency import require_admin
        app = FastAPI()
        app.include_router(poses.router)
        app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
        client = TestClient(app)
        response = client.delete("/poses/walking?axis=pose")
        check("HTTP world override allowed", response.status_code == 200 and "walking" in pc.get_catalog("pose"))
        response = client.delete("/poses/swimming?axis=pose")
        check("HTTP shipped movement refused", response.status_code == 400 and response.json()["detail"] == "fixed movement pose")
        check("HTTP fixed rename refused", client.post("/poses/crawling/rename?axis=pose", json={"new_key": "x"}).status_code == 400)
        pc.replace_world_entries("pose", {"walking": {"animation": "walk", "prompt": "world walking", "group": "stand"}})
        pc.reload_catalogs()
    rows = {r["key"]: r for r in poses.list_entries("pose", {})["entries"]}
    check("movement flags", all(rows[k]["movement"] and not rows[k]["renamable"] for k in MOVEMENT_POSES))
    check("delete flags", rows["walking"]["deletable"] and not rows["swimming"]["deletable"])
    ac.save_transitions([{"from": "walking", "to": "swimming", "kind": "walk"}])
    check("[F4] world allowed", poses.delete_entry("walking", "pose", {})["transitions_removed"] == 0 and "walking" in pc.get_catalog("pose") and len(ac.load_transitions()) == 1)
    for key in MOVEMENT_POSES:
        try:
            poses.delete_entry(key, "pose", {})
        except HTTPException as exc:
            check("[F4] shipped refused " + key, exc.status_code == 400)
        else:
            check("[F4] shipped refused " + key, False)
        try:
            poses._rename_entry_sync(key, "pose", {"new_key": "x"})
        except HTTPException as exc:
            check("[F5] rename refused " + key, exc.status_code == 400)
        else:
            check("[F5] rename refused " + key, False)
    ac.save_transitions([{"from": "sitting at table", "to": "walking", "kind": "walk"}])
    response = poses._rename_entry_sync("sitting at table", "pose", {"new_key": "seated"})
    check("rename transitions", response.get("transitions_rewritten") == 1 and ac.load_transitions()[0]["from"] == "seated")
    response = poses.delete_entry("seated", "pose", {})
    check("delete transitions", response.get("transitions_removed") == 1 and ac.load_transitions() == [])


def character_checks(pc, free):
    from app.core.db import transaction
    from app.core.movement import MOVEMENT_POSES
    from app.routes import characters

    now = "2026-10-25T00:00:00Z"
    with transaction() as conn:
        conn.execute(
            "INSERT INTO characters (name, template, profile_json, config_json,"
            " created_at, updated_at) VALUES (?, '', ?, '{}', ?, ?)",
            ("movement-demo", json.dumps({"animation_set": "female", "gender": "female"}), now, now))
    pc.replace_world_entries("pose", {"reading": {"animation": "mob1-walk"}})
    pc.reload_catalogs()
    (free / "swim.fbx").unlink()
    payload = characters.get_character_animations("movement-demo")
    rows = {row["pose"]: row for row in payload["situations"]}
    check("[C1] set/order", payload["sets"] == ["female"] and
          [row["pose"] for row in payload["situations"]] == list(MOVEMENT_POSES))
    check("[C1] female walk", rows["walking"]["file"]["set"] == "female" and
          rows["walking"]["public_file"]["set"] == "female")
    check("[C1] missing swim", rows["swimming"]["file"] is None and
          rows["swimming"]["public_file"] is None)
    check("[C1] neutral file", rows["standing"]["file"]["set"] == "" and
          rows["standing"]["file"]["library"] == "free")
    check("[C2] no activity", payload["activity"] is None)
    row = characters.get_character_animations("movement-demo", "reading")["activity"]
    check("[C2] reading played/public", row is not None and row["pose"] == "reading" and
          row["kind"] == "mob1-walk" and row["public_kind"] == "walk" and
          row["file"]["library"] == "licensed" and row["file"]["set"] == "" and
          row["public_file"]["library"] == "free" and row["public_file"]["set"] == "female")
    check("[C2] unknown activity", characters.get_character_animations(
        "movement-demo", "missing")["activity"] is None)
    if "--http" in sys.argv:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(characters.router)
        with TestClient(app) as client:
            response = client.get("/characters/movement-demo/animations?pose=reading")
            check("[C2] HTTP reading", response.status_code == 200 and
                  response.json()["activity"]["pose"] == "reading")
    from app.models.character import get_character_profile, save_character_profile
    profile = get_character_profile("movement-demo")
    profile["animation_set"] = "special"
    assert save_character_profile("movement-demo", profile)
    payload = characters.get_character_animations("movement-demo")
    check("[C1] explicit then derived", payload["sets"] == ["special", "female"] and
          payload["situations"][1]["file"]["set"] == "female" and
          payload["situations"][1]["public_file"]["set"] == "female")
    (free / "swim.fbx").write_bytes(b"clip")
    pc.replace_world_entries("pose", {})
    pc.reload_catalogs()


def main():
    with tempfile.TemporaryDirectory(prefix="movement-poses-") as tmp:
        root = Path(tmp)
        free, licensed = root / "free", root / "licensed"
        free.mkdir()
        licensed.mkdir()
        os.environ["ANIMATION_CLIPS_DIR"] = str(free)
        os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(licensed)
        from app.core import paths
        paths.init(root / "world")
        from app.core.movement import movement_of, movement_pose_kinds, clip_file_for, played_pose_kind, shared_pose_kind
        from app.core import pose_catalog as pc
        from app.core.db import init_schema
        from app.core import animation_clips as ac
        check("world table absent before schema", ac.world_transitions() == [])
        init_schema()
        from app.routes.assets import list_animation_clips
        kinds = {"standing": "idle", "walking": "walk", "running": "run",
                 "swimming": "swim", "treading_water": "treading-water",
                 "crawling": "crawl", "crawling_rest": "crawl-rest"}
        entries = {key: {"animation": kind, "prompt": key, "group": "ground" if key.startswith("crawling") else "stand", "synonyms": ["schwimmen"] if key == "swimming" else []} for key, kind in kinds.items()}
        entries.update({"reading": {"animation": "walk"}, "sleeping": {"animation": "sleeping-side"}, "sitting at table": {"animation": "sitting-at-the-table"}})
        catalog = root / "pose_catalog.json"
        catalog.write_text(json.dumps({"entries": entries, "groups": {"stand": {"default": "standing", "needs_place": False}, "ground": {"default": "crawling_rest", "needs_place": False}}}), encoding="utf-8")
        for name in (*kinds.values(), "breast-stroke", "get-up-bed", "get-up-chair", "sleeping-side", "sitting-at-the-table", "pair__a", "pair__b"):
            (free / f"{name}.fbx").write_bytes(b"clip")
        (free / "female").mkdir()
        (free / "female" / "walk.fbx").write_bytes(b"clip")
        for name in ("mob1-walk", "walk"):
            (licensed / f"{name}.fbx").write_bytes(b"clip")
        with patch.object(pc, "catalog_path", return_value=catalog):
            pc.reload_catalogs()
            pc.replace_world_entries("pose", {
                "walking": dict(entries["walking"], animation="mob1-walk"),
                "swimming": dict(entries["swimming"], animation="breast-stroke")})
            check("[M1] movement_of", [movement_of(m) for m in ({}, {"movement": "swim"}, {"movement": "fly"}, None, {"movement": []})] == ["walk_run", "swim", "walk_run", "walk_run", "walk_run"])
            k = movement_pose_kinds()
            check("[M2] played/public", len(k) == 7 and k["walking"] == {"kind": "mob1-walk", "public_kind": "walk"} and k["swimming"] == {"kind": "breast-stroke", "public_kind": "swim"} and k["crawling_rest"] == {"kind": "crawl-rest", "public_kind": "crawl-rest"})
            check("unknown poses", played_pose_kind("missing") == shared_pose_kind("missing") == "")
            from app.core import animation_clips as ac
            rules_path = root / "transitions.json"
            fixture = [{"from": "sleeping", "to": "walking", "kind": "get-up-bed"}, {"from": "sitting at table", "to": "*", "kind": "get-up-chair"}, {"from": "ghost pose", "to": "*", "kind": "get-up-chair"}]
            with patch.object(ac, "clip_transitions_path", return_value=rules_path):
                ac.save_transitions(fixture)
                check("[T1] pose precedence", ac.resolve_transition("sleeping", "walking")["kind"] == "get-up-bed" and ac.resolve_transition("sitting at table", "running")["kind"] == "get-up-chair" and ac.resolve_transition("walking", "walking") is None)
                annotated = ac.annotated_transitions()[0]
                check("annotation kinds", {k: annotated[k] for k in ("from_kind", "to_kind", "from_public_kind", "to_public_kind")} == {"from_kind": "sleeping-side", "to_kind": "mob1-walk", "from_public_kind": "sleeping-side", "to_public_kind": "walk"})
                check("missing public bridge", not ac.annotated_transitions([dict(fixture[0], kind="mob1-walk")])[0]["bridge_public"])
                (free / "female" / "set-bridge.fbx").write_bytes(b"clip")
                check("public bridge in a set", ac.annotated_transitions([dict(fixture[0], kind="set-bridge")])[0]["bridge_public"])
                c = ac.client_transition_rules()
                pairs = {(r["from"], r["to"]) for r in c}
                check("[T2] expanded played+public", {("sleeping-side", "mob1-walk"), ("sleeping-side", "walk")} <= pairs)
                check("[T3] wildcard kept", ("sitting-at-the-table", "*") in pairs)
                check("[T4] unknown pose skipped", len(c) == 3)
                check("[T5] unknown survives save", any(r["from"] == "ghost pose" for r in ac.save_transitions(ac.load_transitions())))
                check("[T7] rename/drop", ac.rename_transition_pose("sleeping", "asleep") == 1 and ac.drop_transition_pose("asleep") == 1)
                transition_checks(ac, rules_path, fixture)
                world_transition_checks(ac, fixture)
            pc.replace_world_entries("pose", {})
            pc.reload_catalogs()
            for file in licensed.iterdir():
                file.unlink()
            check("[M3] public", movement_pose_kinds() == {key: {"kind": kind, "public_kind": kind} for key, kind in kinds.items()} and all(clip_file_for(kind, [], free_only=False)["library"] == "free" for kind in kinds.values()))
            with patch.object(ac, "clip_transitions_path", return_value=rules_path):
                check("[T6] public rules", all("mob1" not in r["from"] + r["to"] for r in ac.client_transition_rules()))
            (licensed / "walk.fbx").write_bytes(b"clip")
            check("[M4] set chain", clip_file_for("walk", ["missing", "female"], free_only=False)["set"] == "female")
            played = clip_file_for("walk", [], free_only=False)
            public = clip_file_for("walk", [], free_only=True)
            check("[M5] licensed shadow", played["library"] == "licensed" and public["library"] == "free" and played["url"].startswith("/assets/animation-clips/licensed/walk.fbx?v=") and public["url"].startswith("/assets/animation-clips/walk.fbx?v="))
            (licensed / "mob1-walk.fbx").write_bytes(b"clip")
            check("[M6] missing", clip_file_for("fly", ["female"], free_only=False) is None and clip_file_for("mob1-walk", [], free_only=True) is None and clip_file_for("pair", [], free_only=False) is None)
            character_checks(pc, free)
            payload = list_animation_clips()
            check("[M7] payload", payload.get("movement_poses") == movement_pose_kinds() and "locomotion" not in payload)
            with patch.object(ac, "clip_transitions_path", return_value=rules_path):
                fixed_checks(pc, ac)
                payload = list_animation_clips()
                check("transition payload", payload["transitions"] == ac.annotated_transitions() and payload["transition_clips"] == ac.client_transition_rules())
        pc.reload_catalogs()
    print(f"{len(FAILURES)} failures")
    return bool(FAILURES)


if __name__ == "__main__":
    sys.exit(main())
