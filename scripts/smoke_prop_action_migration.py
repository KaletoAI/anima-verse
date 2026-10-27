#!/usr/bin/env python3
"""Isolated behavioral regressions for action migration, geometry and pack ingress.

Run: ./.venv/bin/python scripts/smoke_prop_action_migration.py
No media generation, real instance, runtime activation or network is used.
"""
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ROOT = Path(tempfile.mkdtemp(prefix="prop-action-migration-"))
os.environ["STORAGE_DIR"] = str(ROOT)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
from app.core import paths
paths.init(ROOT)
paths.init_instance(ROOT / "instance")
from app.core import db, props
from app.blender import runner
runner.is_available = lambda: False
db.init_schema()
from app.core.prop_action_migration import migrate_actions, normalize_import
from app.core.prop_actions import validate_document
from app.core.content_io import export_prop_to_zip, import_prop_from_zip

UID_A = "11111111-1111-4111-8111-111111111111"
UID_B = "22222222-2222-4222-8222-222222222222"
CATALOG = {"sleeping": {"group": "lie", "solo": True, "label": "Sleeping"},
           "sitting": {"group": "sit", "solo": True, "label": "Sitting"},
           "embrace": {"group": "lie", "solo": False, "label": "Embrace"},
           "standing": {"group": "stand", "solo": True},
           "kneeling": {"group": "ground", "solo": True},
           "swimming": {"group": "stand", "solo": True},
           "treading_water": {"group": "stand", "solo": True},
           "crawling": {"group": "ground", "solo": True},
           "crawling_rest": {"group": "ground", "solo": True}}
GROUPS = {key: {"label": key.title(), "default": default, "root_drop": 0,
                "needs_place": True}
          for key, default in (("lie", "sleeping"), ("sit", "sitting"),
                               ("stand", "standing"), ("ground", "kneeling"))}
CATALOG_FILE = ROOT / "fixture-pose-catalog.json"
CATALOG_FILE.write_text(json.dumps({"entries": CATALOG, "groups": GROUPS}))


def legacy():
    marker = {"id": "body", "group": "lie", "at": [.5, .5, .5],
              "facing": 0}
    return {"id": "fixture", "name": "Bed", "bbox": [2, 1, 1],
            "model_variants": [{"stem": stem, "uid": uid, "active": True,
                                "width_m": 2, "depth_m": 1, "height_m": 1,
                                "dims_estimated": False,
                                "markers": [copy.deepcopy(marker)]}
                               for stem, uid in (("model", UID_A), ("model-v2", UID_B))]}


def publish_fixture(name, document):
    """Publish an opaque mesh only; geometry comes from the authored bbox."""
    pid = props.create_prop(name=name)["id"]
    props._write_sidecar(pid, document)
    directory = props._prop_dir(pid)
    (directory / "model_1.glb").write_bytes(b"isolated-provenance-mesh")
    (directory / "model_1.json").write_text(json.dumps({"tier": "full"}))
    (directory / "selection.json").write_text(json.dumps({"model": {"full": "model_1.glb"}}))
    return pid


def child_binding(layout):
    from app.core.room_recipe import _join_placements
    _, markers = _join_placements(layout, lambda x, z: (x, z), 0, 0, 0)
    return next(m["action_bindings"][0] for m in markers if m["placement_id"] == "child")


class MigrationTests(unittest.TestCase):
    def setUp(self):
        from app.core import pose_catalog
        pose_catalog.reload_catalogs()
        self.addCleanup(pose_catalog.reload_catalogs)
        catalog_file = patch("app.core.pose_catalog.catalog_path", return_value=CATALOG_FILE)
        catalog_file.start()
        self.addCleanup(catalog_file.stop)

    def test_shared_solo_action_preserves_sleep_pose_without_sleep_ability(self):
        source = legacy()
        normalized = normalize_import(source)
        self.assertEqual(source, legacy(), "normalization must not mutate its caller")
        self.assertEqual(len(normalized["actions"]), 1)
        action = normalized["actions"][0]
        self.assertEqual((action["pose_key"], action["ability"], action["participants"]),
                         ("sleeping", "pose", 1))
        self.assertEqual(action["name"], "Schlafpose (ohne Schlafzustand)")
        for original, variant in zip(source["model_variants"], normalized["model_variants"]):
            self.assertEqual(variant["markers"], original["markers"])
            self.assertEqual(variant["action_bindings"][0]["action_id"], action["id"])
            self.assertEqual(variant["action_bindings"][0]["variant_uid"], variant["uid"])
        self.assertEqual(validate_document(normalized), [])
        self.assertEqual(normalize_import(normalized), normalized)

    def test_migration_uses_activity_eligible_poses_for_live_and_snapshot_catalogs(self):
        from app.core.pose_catalog import poses_in_group
        source = legacy()
        for variant, group in zip(source["model_variants"], ("stand", "ground")):
            variant["markers"][0]["group"] = group
        self.assertEqual(poses_in_group("stand"), ["standing"])
        self.assertEqual(poses_in_group("ground"), ["kneeling"])
        normalized = normalize_import(source)
        self.assertEqual({a["pose_key"] for a in normalized["actions"]}, {"standing", "kneeling"})
        pid = props.create_prop(name="Activity-only migration")["id"]
        props._write_sidecar(pid, source)
        row = next(row for row in migrate_actions()["props"] if row["prop_id"] == pid)
        self.assertEqual({a["pose_key"] for a in row["document"]["actions"]}, {"standing", "kneeling"})

    def test_noncanonical_and_colliding_marker_ids_are_rejected_before_replace(self):
        pid = props.create_prop(name="Marker identity target")["id"]
        directory = props._prop_dir(pid)
        before = {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}
        for identities, code in ((("seat-left", "seatleft"), "invalid_marker_id"),
                                 (("seatleft", "seatleft"), "duplicate_marker_id")):
            with self.subTest(identities=identities):
                document = normalize_import(legacy())
                variant = document["model_variants"][0]
                variant["markers"] = [{**variant["markers"][0], "id": identity}
                                      for identity in identities]
                variant["action_bindings"][0]["marker_ids"] = [identities[0]]
                with self.assertRaises(ValueError) as error:
                    normalize_import(document)
                self.assertIn(code, {issue["code"] for issue in error.exception.issues})
                out = io.BytesIO()
                with zipfile.ZipFile(out, "w") as archive:
                    archive.writestr("manifest.json", json.dumps({"version": 1, "type": "prop", "prop_id": pid}))
                    archive.writestr("files/sidecar.json", json.dumps(document))
                with self.assertRaisesRegex(ValueError, code):
                    import_prop_from_zip(out.getvalue(), overwrite=True)
                self.assertEqual({p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}, before)

    def test_uncertain_access_is_blocked_not_claimed_as_route(self):
        source = legacy()
        source["model_variants"][0]["markers"][0].pop("facing")
        normalized = normalize_import(source)
        bad, good = [v["action_bindings"][0] for v in normalized["model_variants"]]
        self.assertEqual((bad["validation"], bad["supported"]), ("repair_required", False))
        self.assertEqual(good["validation"], "local_valid")
        self.assertNotIn("route_valid", good)
        self.assertEqual(set(good["access_points"]["actor"]), {"x", "z", "yaw"})
        pid = props.create_prop(name="Repair report")["id"]
        props._write_sidecar(pid, normalized)
        blob = export_prop_to_zip(pid)
        props.delete_prop(pid)
        imported = import_prop_from_zip(blob)
        self.assertTrue(any("repair_required" in warning for warning in imported["warnings"]))

    def test_decorative_creation_has_no_implicit_actions(self):
        prop = props.create_prop(name="Decorative cup")
        document = props.read_sidecar(prop["id"])
        self.assertEqual(document["actions"], [])
        self.assertEqual(normalize_import(document)["actions"], [])

    def test_authored_access_inside_footprint_is_preserved_but_blocked(self):
        document = normalize_import(legacy())
        point = {"x": 0, "z": 0, "yaw": 180}
        document["model_variants"][0]["action_bindings"][0]["access_points"]["actor"] = point
        normalized = normalize_import(document)
        binding = normalized["model_variants"][0]["action_bindings"][0]
        self.assertEqual(binding["access_points"]["actor"], point)
        self.assertEqual((binding["supported"], binding["validation"]), (False, "repair_required"))
        self.assertEqual(normalized["model_variants"][0]["markers"], document["model_variants"][0]["markers"])

    def test_autofurnish_marker_creates_disabled_suggestions_not_sleep(self):
        from app.core.room_furnish import _create_built_props
        needs = [{"build": True, "key": "bed", "kind": "Bed", "width_m": 2,
                  "depth_m": 1, "height_m": 1, "marker": legacy()["model_variants"][0]["markers"][0]},
                 {"build": True, "key": "vase", "kind": "Vase"}]
        rewrite, skipped, created = _create_built_props(needs, {"need:bed", "need:vase"})
        self.assertEqual((skipped, created), ([], 2))
        bed = props.read_sidecar(rewrite["need:bed"])
        self.assertEqual([(a["pose_key"], a["ability"], a["enabled"]) for a in bed["actions"]],
                         [("sleeping", "pose", False)])
        self.assertEqual(bed["model_variants"][0]["action_bindings"][0]["validation"], "suggested")
        self.assertFalse(bed["model_variants"][0]["action_bindings"][0]["supported"])
        self.assertEqual(props.read_sidecar(rewrite["need:vase"])["actions"], [])

    def test_migration_ids_use_store_identity_not_duplicate_names_or_stale_sidecar_id(self):
        ids = [props.create_prop(name="Same legacy name")["id"] for _ in range(2)]
        for pid in ids:
            props._write_sidecar(pid, legacy())
        report = migrate_actions()
        proposed = {row["prop_id"]: row["document"]["actions"][0]["id"]
                    for row in report["props"] if row["prop_id"] in ids}
        self.assertEqual(len(set(proposed.values())), 2)
        migrate_actions(dry_run=False)
        self.assertEqual({pid: props.read_sidecar(pid)["actions"][0]["id"] for pid in ids}, proposed)

    def test_invalid_variant_store_identity_is_rejected_without_lossy_projection(self):
        for bad in ("model_v1", "../model", "model"):
            document = legacy()
            document["model_variants"][1]["stem"] = bad
            with self.subTest(stem=bad), self.assertRaises(ValueError) as error:
                normalize_import(document)
            self.assertIn("invalid_variant_stem", {issue["code"] for issue in error.exception.issues})

    def test_sparse_dryrun_reads_shared_without_creating_database(self):
        sparse = ROOT / "sparse-world"
        folder = sparse / "props" / "legacy"
        folder.mkdir(parents=True)
        document = legacy()
        for variant in document["model_variants"]:
            variant.pop("uid")
        document["markers"] = document["model_variants"][0].pop("markers")
        document["markers"][0]["group"] = "bed"
        document["width_m"], document["depth_m"], document["height_m"] = 2, 1, 1
        document["model_variants"][1].pop("markers")
        (folder / "sidecar.json").write_text(json.dumps(document))
        before = {p.relative_to(sparse).as_posix(): p.read_bytes()
                  for p in sparse.rglob("*") if p.is_file()}
        tree = sorted(str(p.relative_to(sparse)) for p in sparse.rglob("*"))
        with patch("app.core.paths.get_storage_dir", return_value=sparse), \
             patch("app.core.db.get_db_path", return_value=sparse / "world.db"):
            report = migrate_actions()
        self.assertEqual(report["issues"], [])
        self.assertEqual(report["props"][0]["actions"], 1)
        self.assertFalse((sparse / "world.db").exists())
        self.assertEqual(sorted(str(p.relative_to(sparse)) for p in sparse.rglob("*")), tree)
        self.assertEqual({p.relative_to(sparse).as_posix(): p.read_bytes()
                          for p in sparse.rglob("*") if p.is_file()}, before)

    def test_unreadable_existing_database_is_an_issue_not_shared_fallback(self):
        corrupt = ROOT / "corrupt-world.db"
        corrupt.write_bytes(b"not sqlite")
        with patch("app.core.db.get_db_path", return_value=corrupt):
            report = migrate_actions()
        self.assertEqual(report["props"], [])
        self.assertEqual(report["issues"][0]["code"], "catalog_snapshot_unavailable")
        self.assertEqual(corrupt.read_bytes(), b"not sqlite")

    def test_changed_snapshot_aborts_visibly_and_removes_private_copy(self):
        import shutil
        import sqlite3
        database = ROOT / "changing-world.db"
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE fixture(value)")
        connection.commit()
        connection.close()
        copyfile = shutil.copyfile
        temporary_directory = tempfile.TemporaryDirectory
        temporary_paths = []

        def changed_copy(source, target):
            result = copyfile(source, target)
            stat = Path(source).stat()
            os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
            return result

        def private_directory(*args, **kwargs):
            result = temporary_directory(*args, **kwargs)
            temporary_paths.append(Path(result.name))
            self.assertEqual(Path(result.name).stat().st_mode & 0o777, 0o700)
            return result

        with patch("app.core.db.get_db_path", return_value=database), \
             patch("shutil.copyfile", side_effect=changed_copy), \
             patch("tempfile.TemporaryDirectory", side_effect=private_directory):
            report = migrate_actions()
        self.assertEqual(report["props"], [])
        self.assertEqual(report["issues"][0]["code"], "catalog_snapshot_unavailable")
        self.assertIn("inconsistent", report["issues"][0]["message"])
        self.assertTrue(temporary_paths)
        self.assertTrue(all(not p.exists() for p in temporary_paths))

    def test_readonly_snapshot_honors_world_pose_and_disabled_state_override(self):
        import sqlite3
        from app.core.pose_catalog import WORLD_TABLE
        sparse = ROOT / "override-world"
        folder = sparse / "props" / "bed"
        folder.mkdir(parents=True)
        path = folder / "sidecar.json"
        path.write_text(json.dumps(legacy()))
        database = sparse / "world.db"
        connection = sqlite3.connect(database)
        connection.execute(f"CREATE TABLE {WORLD_TABLE}(axis,kind,key,doc)")
        connection.executemany(f"INSERT INTO {WORLD_TABLE} VALUES(?,?,?,?)", [
            ("pose", "entry", "sleeping", json.dumps({"solo": False, "group": "lie"})),
            ("pose", "entry", "world-rest", json.dumps({"solo": True, "group": "lie", "label": "World rest"}))])
        connection.execute("CREATE TABLE prompt_filters(id,enabled)")
        connection.execute("INSERT INTO prompt_filters VALUES('fixture-state',0)")
        connection.commit()
        connection.close()
        before = {p.relative_to(sparse).as_posix(): p.read_bytes()
                  for p in sparse.rglob("*") if p.is_file()}
        with patch("app.core.paths.get_storage_dir", return_value=sparse), \
             patch("app.core.db.get_db_path", return_value=database), \
             patch("app.core.prompt_filters._load_shared", return_value=[{"id": "fixture-state", "enabled": True}]):
            report = migrate_actions()
            self.assertEqual(report["issues"], [])
            self.assertEqual([a["pose_key"] for a in report["props"][0]["document"]["actions"]], ["world-rest"])
            authored = normalize_import(legacy())
            authored["actions"][0]["requirements"] = [{"id": "r", "type": "condition", "target": "actor",
                "condition_id": "fixture-state", "present": True}]
            path.write_text(json.dumps(authored))
            invalid = migrate_actions()
            self.assertIn("unknown_requirement_reference",
                          {i["code"] for i in invalid["issues"][0]["issues"]})
        self.assertEqual(database.read_bytes(), before["world.db"])

    def test_dry_report_then_persist_is_idempotent_and_recreated_uid_is_new(self):
        prop = props.create_prop(name="Migration bed")
        pid = prop["id"]
        document = legacy()
        document["id"] = pid
        props._write_sidecar(pid, document)
        path = props._prop_dir(pid) / "sidecar.json"
        before = path.read_bytes()
        tree_before = sorted(str(p.relative_to(ROOT)) for p in ROOT.rglob("*"))
        report = migrate_actions()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(sorted(str(p.relative_to(ROOT)) for p in ROOT.rglob("*")), tree_before)
        # Legacy UID allocation must remain pure too, and catalog validation
        # must not create a missing template directory.
        raw = legacy()
        for variant in raw["model_variants"]:
            variant.pop("uid")
        path.write_text(json.dumps(raw))
        snapshot = {p.relative_to(ROOT).as_posix(): p.read_bytes()
                    for p in ROOT.rglob("*") if p.is_file()}
        with patch("app.models.character_template.get_templates_dir", return_value=ROOT / "absent-templates"):
            migrate_actions()
        self.assertEqual({p.relative_to(ROOT).as_posix(): p.read_bytes()
                          for p in ROOT.rglob("*") if p.is_file()}, snapshot)
        self.assertFalse((ROOT / "absent-templates").exists())
        from app.models import character_template
        with patch("app.models.character_template.get_templates_dir", return_value=ROOT / "template-write"):
            self.assertEqual(character_template.list_templates(), [])
            self.assertTrue(character_template.save_template("fixture", {"label": "Fixture"}))
            self.assertEqual(character_template.list_templates(),
                             [{"name": "fixture", "label": "Fixture", "type": "character"}])
        row = next(row for row in report["props"] if row["prop_id"] == pid)
        self.assertEqual(row["actions"], 1)
        self.assertEqual(row["variants"], 2)
        self.assertFalse(report["runtime_activated"])
        migrate_actions(dry_run=False)
        after = path.read_bytes()
        self.assertEqual(migrate_actions(dry_run=False)["changed"], 0)
        self.assertEqual(path.read_bytes(), after)
        old_uid = props.read_sidecar(pid)["model_variants"][1]["uid"]
        props.delete_variant(pid, 1)
        props.add_variant(pid)
        self.assertNotEqual(props.read_sidecar(pid)["model_variants"][1]["uid"], old_uid)

    def test_invalid_import_leaves_existing_directory_untouched(self):
        prop = props.create_prop(name="Pack original")
        pid = prop["id"]
        folder = props._prop_dir(pid)
        before = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
        document = normalize_import(legacy())
        document["model_variants"][0]["action_bindings"][0]["marker_ids"] = ["missing"]
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as archive:
            archive.writestr("manifest.json", json.dumps({"version": 1, "type": "prop", "prop_id": pid}))
            archive.writestr("files/sidecar.json", json.dumps(document))
        with self.assertRaises(ValueError):
            import_prop_from_zip(out.getvalue(), overwrite=True)
        self.assertEqual({p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}, before)

    def test_bundled_invalid_action_is_rejected_before_location_install(self):
        from app.core.content_io import import_location_from_zip
        from app.models.world import list_locations
        document = normalize_import(legacy())
        document["actions"][0]["requirements"] = [{"id": "missing", "target": "actor",
            "type": "condition", "condition_id": "missing-state", "present": True}]
        before = list_locations()
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as archive:
            archive.writestr("manifest.json", json.dumps({"version": 1, "type": "location"}))
            archive.writestr("db/location.json", json.dumps({"name": "Invalid bundled", "rooms": []}))
            archive.writestr("props/invalid-bundle/sidecar.json", json.dumps(document))
        with self.assertRaises(ValueError):
            import_location_from_zip(out.getvalue())
        self.assertEqual(list_locations(), before)
        self.assertFalse(props._prop_dir("invalid-bundle").exists())

    def test_temporary_pack_roundtrip_preserves_ids_bindings_and_dependencies(self):
        prop = props.create_prop(name="Action pack")
        pid = prop["id"]
        document = normalize_import(legacy())
        from app.core.prompt_filters import invalidate_filter_snapshot
        with db.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO prompt_filters "
                "(id,condition,label,drop_blocks,prompt_modifier,enabled,meta,icon,image_modifier,bone_pose) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("pack-fixture-state", "", "Fixture", "[]", "", 1, "{}", "", "", "{}"))
        invalidate_filter_snapshot()
        document["actions"][0]["requirements"] = [{"id": "state-required", "target": "actor",
            "type": "condition", "condition_id": "pack-fixture-state", "present": True}]
        document["actions"][0]["effects"] = [{"id": "state-effect", "target": "actor",
            "type": "condition_add", "condition_id": "pack-fixture-state", "when": "start",
            "duration_game_s": 60, "repeat": "refresh"}]
        props._write_sidecar(pid, document)
        blob = export_prop_to_zip(pid)
        props.delete_prop(pid)
        result = import_prop_from_zip(blob)
        self.assertEqual(result["status"], "success")
        self.assertEqual(props.read_sidecar(pid), document)
        broken = copy.deepcopy(document)
        broken["actions"][0]["requirements"] = [{"id": "condition", "target": "actor",
            "type": "condition", "condition_id": "absent-fixture-state", "present": True}]
        with self.assertRaises(ValueError) as error:
            normalize_import(broken)
        self.assertIn("unknown_requirement_reference", {issue["code"] for issue in error.exception.issues})

    def test_building_and_autofurnish_append_preserve_placement_provenance(self):
        from app.models.world import (GROUND_ROOM_ID, add_location, upsert_location,
            append_room_props, append_rooms_props, get_location_by_id)
        location = add_location("Action building", "Provenance fixture", rooms=[{"name": "A"}, {"name": "B"}])
        rooms = [r for r in location["rooms"] if r["id"] != GROUND_ROOM_ID]
        for room in rooms:
            room["layout"] = {"x": 0, "y": 0, "w": 6, "d": 4}
        upsert_location(location, sync_world=True)
        placement = {"id": "kept", "prop_id": "missing-but-valid-id", "at": [2, 2],
            "variant": 7, "variant_uid": UID_B, "definition_revision": "f" * 64,
            "action_dependency_invalid": True, "support_reason": "cycle"}
        self.assertTrue(append_room_props(location["id"], rooms[0]["id"], [placement]))
        self.assertEqual(append_rooms_props(location["id"], {rooms[1]["id"]: [placement]}),
                         {rooms[1]["id"]: True})
        back = get_location_by_id(location["id"])
        for room in back["rooms"]:
            if room["id"] in {r["id"] for r in rooms}:
                stored = room["layout"]["props"][0]
                for key, value in placement.items():
                    self.assertEqual(stored[key], value)

    def test_bundled_collision_reports_changed_geometry_and_blocks_placement(self):
        from app.core.content_io import import_location_from_zip
        from app.models.world import get_location_by_id
        pid = props.create_prop(name="Collision bed")["id"]
        incoming = normalize_import(legacy())
        props._write_sidecar(pid, incoming)
        local = props.read_sidecar(pid)
        local["model_variants"][0]["markers"][0]["at"][1] = .7
        props._write_sidecar(pid, local)
        original_bytes = (props._prop_dir(pid) / "sidecar.json").read_bytes()
        location = {"name": "Collision room", "rooms": [{"id": "room", "name": "A",
            "layout": {"x": 0, "y": 0, "w": 6, "d": 4,
                       "props": [{"id": "placed", "prop_id": pid, "at": [2, 2]}]}}]}
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as archive:
            archive.writestr("manifest.json", json.dumps({"version": 1, "type": "location"}))
            archive.writestr("db/location.json", json.dumps(location))
            archive.writestr(f"props/{pid}/sidecar.json", json.dumps(incoming))
        result = import_location_from_zip(out.getvalue())
        self.assertEqual(result["action_dependency_issues"],
                         [{"prop_id": pid, "code": "incompatible_prop_dependency"}])
        self.assertTrue(any(pid in warning and "blocked" in warning for warning in result["warnings"]))
        imported = get_location_by_id(result["location_id"])
        room = next(r for r in imported["rooms"] if r["name"] == "A")
        self.assertTrue(room["layout"]["props"][0]["action_dependency_invalid"])
        self.assertEqual((props._prop_dir(pid) / "sidecar.json").read_bytes(), original_bytes)

    def test_broken_support_survives_actual_append_and_pack_import(self):
        from app.models.world import (add_location, upsert_location, append_room_props,
                                      get_location_by_id)
        from app.core.content_io import export_location_to_zip, import_location_from_zip
        from app.core.world_ops import _sanitize_room_layout
        document = normalize_import(legacy())
        document["model_variants"][0]["action_bindings"][0]["access_points"]["actor"]["z"] = 1.6
        pid = publish_fixture("Broken support fixture", document)

        def placement(identity, parent=""):
            return {"id": identity, "prop_id": pid, "at": [0, 0], **({"on": parent} if parent else {})}

        cases = {
            "unknown": [placement("child", "absent")],
            "self": [placement("child", "child")],
            "cycle": [placement("child", "parent"), placement("parent", "child")],
            "depth": [placement("root"), placement("b", "root"), placement("c", "b"),
                      placement("d", "c"), placement("child", "d")],
        }
        for reason, placements in cases.items():
            with self.subTest(reason=reason):
                location = add_location("Broken support " + reason, "Isolated regression",
                                        rooms=[{"name": "A"}])
                room = next(r for r in location["rooms"] if r.get("name") == "A")
                room["layout"] = {"x": 0, "y": 0, "w": 12, "d": 12}
                upsert_location(location, sync_world=True)
                self.assertTrue(append_room_props(location["id"], room["id"], placements))
                stored = next(r for r in get_location_by_id(location["id"])["rooms"]
                              if r["id"] == room["id"])["layout"]
                child = next(p for p in stored["props"] if p["id"] == "child")
                self.assertNotIn("on", child)
                self.assertEqual(child["support_reason"], reason)
                self.assertFalse(child_binding(stored)["supported"])
                self.assertEqual(_sanitize_room_layout(stored), stored)
                # Feed the raw broken links through the actual import sanitizer
                # too, rather than only importing an already flagged layout.
                blob = export_location_to_zip(location["id"])
                rewritten = io.BytesIO()
                with zipfile.ZipFile(io.BytesIO(blob)) as source, zipfile.ZipFile(rewritten, "w") as target:
                    for member in source.namelist():
                        data = source.read(member)
                        if member == "db/location.json":
                            raw_location = json.loads(data)
                            next(r for r in raw_location["rooms"] if r.get("name") == "A")["layout"]["props"] = placements
                            data = json.dumps(raw_location).encode()
                        target.writestr(member, data)
                result = import_location_from_zip(rewritten.getvalue())
                imported = next(r for r in get_location_by_id(result["location_id"])["rooms"]
                                if r.get("name") == "A")["layout"]
                self.assertEqual(next(p for p in imported["props"] if p["id"] == "child")["support_reason"], reason)
                self.assertFalse(child_binding(imported)["supported"])
                self.assertEqual(child_binding(imported)["reason"], "invalid_support_chain")

    def test_incompatible_and_stale_support_blocks_child_without_parent_actions(self):
        from app.models.world import add_location, upsert_location, get_location_by_id
        from app.core.content_io import export_location_to_zip, import_location_from_zip
        table_document = legacy()
        table_document["actions"] = []
        table_document["bbox"] = [3, 1, 2]
        for variant in table_document["model_variants"]:
            variant.update(width_m=3, depth_m=2, height_m=1, action_bindings=[])
            variant.pop("markers")
        table = publish_fixture("Dependency table", table_document)
        machine_document = normalize_import(legacy())
        machine_document["model_variants"][0]["action_bindings"][0]["access_points"]["actor"]["z"] = 1.6
        machine = publish_fixture("Dependency machine", machine_document)
        location = add_location("Support dependency", "Isolated regression", rooms=[{"name": "A"}])
        room = next(r for r in location["rooms"] if r.get("name") == "A")
        room["layout"] = {"x": 0, "y": 0, "w": 12, "d": 12, "props": [
            {"id": "table", "prop_id": table, "at": [3, 4]},
            {"id": "child", "prop_id": machine, "at": [0, 0], "on": "table"}]}
        upsert_location(location, sync_world=True)
        self.assertTrue(child_binding(room["layout"])["supported"])
        archive = export_location_to_zip(location["id"])
        changed = props.read_sidecar(table)
        changed["model_variants"][0]["height_m"] = 2
        props._write_sidecar(table, changed)
        result = import_location_from_zip(archive)
        imported = next(r for r in get_location_by_id(result["location_id"])["rooms"]
                        if r.get("name") == "A")["layout"]
        self.assertTrue(next(p for p in imported["props"] if p["id"] == "table")["action_dependency_invalid"])
        self.assertFalse(child_binding(imported)["supported"])
        self.assertEqual(child_binding(imported)["reason"], "incompatible_prop_dependency")
        stale = copy.deepcopy(room["layout"])
        stale["props"][0]["variant_uid"] = UID_B
        self.assertFalse(child_binding(stale)["supported"])
        self.assertEqual(child_binding(stale)["reason"], "incompatible_prop_dependency")
        from app.core.world_ops import _sanitize_room_layout
        ancestor = copy.deepcopy(room["layout"])
        ancestor["props"][0]["on"] = "absent"
        ancestor = _sanitize_room_layout(ancestor)
        self.assertEqual(ancestor["props"][0]["support_reason"], "unknown")
        self.assertFalse(child_binding(ancestor)["supported"])
        self.assertEqual(child_binding(ancestor)["reason"], "invalid_support_chain")

    def test_support_body_height_and_floor_access_have_same_provenance(self):
        from app.core.room_recipe import _join_placements
        from app.core.scene_recipe import _markers
        doc = normalize_import(legacy())
        variant = doc["model_variants"][1]
        variant["action_bindings"][0]["access_points"]["actor"]["z"] = 1.6
        machine = {"name": "Coffee", "has_model": True, "bbox": [2, 1, 1],
                   "revision": "revision-coffee", "actions": doc["actions"],
                   "width_m": 2, "depth_m": 1, "height_m": 1,
                   "variant_tiers": [{**variant, "dims": {"width_m": 2, "depth_m": 1, "height_m": 1}}]}
        table = {"name": "Table", "height_m": 1, "width_m": 3, "depth_m": 2}
        layout = {"props": [{"id": "table", "prop_id": "table", "at": [3, 4], "yaw": 90},
                            {"id": "coffee", "prop_id": "coffee", "at": [0, 0], "on": "table", "variant": 7}]}
        with patch("app.core.props.get_prop", side_effect=lambda pid: {"table": table, "coffee": machine}[pid]):
            placements, markers = _join_placements(layout, lambda x, z: (x, z), 0, 0, 0)
        self.assertEqual(placements[1]["variant_uid"], UID_B)
        self.assertEqual(placements[1]["variant"], 7, "published selector is not a stable identity")
        recipe = {"placements": placements, "prop_markers": markers, "room_id": "kitchen", "level": 0}
        finished = _markers(recipe, {"layout": {}}, 3, False)
        body = finished[0]
        self.assertGreater(body["y_world"], 1.4)
        self.assertEqual(body["variant_uid"], UID_B)
        self.assertEqual(body["placement_id"], "coffee")
        binding = body["action_bindings"][0]
        self.assertEqual(binding["access_points"]["actor"]["y"], 0)
        self.assertEqual(binding["definition_revision"], "revision-coffee")
        self.assertNotEqual(binding["access_points"]["actor"]["x"], 3)
        self.assertTrue(binding["supported"])
        self.assertFalse(binding["route_checked"])
        from app.core.places import _compose
        with patch("app.models.world.get_location_by_id",
                   return_value={"id": "fixture-location", "pos_x": 100, "pos_z": 200, "yaw_deg": 90}), \
             patch("app.core.scene_recipe.scene_inputs", return_value=(10, {}, {})), \
             patch("app.core.scene_recipe.compose_scene", return_value={"markers": finished}):
            world_binding = _compose("fixture-location")["kitchen"][0]["action_bindings"][0]
        self.assertEqual(world_binding["location_id"], "fixture-location")
        self.assertEqual(world_binding["access_points"]["actor"], {"x": 104, "z": 195.4, "y": 0, "yaw": 0})
        # A locally safe machine approach can still stand inside its table.
        variant["action_bindings"][0]["access_points"]["actor"]["z"] = .95
        with patch("app.core.props.get_prop", side_effect=lambda pid: {"table": table, "coffee": machine}[pid]):
            _, blocked = _join_placements(layout, lambda x, z: (x, z), 0, 0, 0)
        self.assertFalse(blocked[0]["action_bindings"][0]["supported"])
        self.assertEqual(blocked[0]["action_bindings"][0]["reason"], "support_access_blocked")
        variant["action_bindings"][0]["access_points"]["actor"]["z"] = 1.6
        # A stale stable identity must not follow a reused published position.
        layout["props"][1]["variant_uid"] = UID_A
        with patch("app.core.props.get_prop", side_effect=lambda pid: {"table": table, "coffee": machine}[pid]):
            _, stale = _join_placements(layout, lambda x, z: (x, z), 0, 0, 0)
        self.assertFalse(stale[0]["action_bindings"][0]["supported"])
        self.assertEqual(stale[0]["action_bindings"][0]["reason"], "incompatible_prop_dependency")
        from app.core.room_recipe import _scatter_into
        scattered = []
        with patch("app.core.props.get_prop", return_value=machine):
            _scatter_into(scattered, [{"prop_id": "coffee", "scatter_count": 2,
                                      "scatter_seed": 4}], [[0, 0], [10, 0], [10, 10], [0, 10]], [])
        self.assertEqual(len(scattered), 2)
        self.assertTrue(all(not p.get("id") and not p.get("action_bindings") for p in scattered))



if __name__ == "__main__":
    unittest.main()
