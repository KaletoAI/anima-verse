#!/usr/bin/env python3
"""Acceptance from design §5.1/§7: two breast-stroke water rows become
swim, preserving 0.6 m sink; dry bog becomes walk_run with one warning.
Grass is unchanged. Only swimming differs from shipped clips. A 2:1 vote
wins by count, 1:1 alphabetically; conflicts warn. Temporary DB checks
full world pose copies, cache invalidation and no-op reruns. The world copy
is the STORED entry (shipped file or world layer) with only the clip changed.
"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix="terrain-movement-") as tmp:
    root = Path(tmp)
    os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
    os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(root / "licensed")
    from app.core import paths
    paths.init(root / "world")
    from app.core import pose_catalog
    catalog_dir = root / "catalog"
    catalog_dir.mkdir()
    for axis in ("pose", "expression"):
        source = pose_catalog.catalog_path(axis)
        (catalog_dir / source.name).write_bytes(source.read_bytes())
    # The expectations assume the SHIPPED clips (swim / treading-water); the
    # working-tree file may carry a local edit of them.
    pose_doc = json.loads((catalog_dir / "pose_catalog.json").read_text(encoding="utf-8"))
    pose_doc["entries"]["swimming"]["animation"] = "swim"
    pose_doc["entries"]["treading_water"]["animation"] = "treading-water"
    (catalog_dir / "pose_catalog.json").write_text(json.dumps(pose_doc), encoding="utf-8")
    original_path = pose_catalog.catalog_path
    pose_catalog.catalog_path = lambda axis: catalog_dir / original_path(axis).name
    from app.core import db, terrain_types
    db.init_schema()
    from app.core.terrain_movement_migration import plan_terrain_movement, migrate_terrain_movement_once
    from app.core.pose_catalog_edit import catalog_txn, read_store, write_store
    rows = [
        {"kind": "water", "meta": {"water": True, "move_anim": "breast-stroke", "idle_anim": "treading-water", "move_sink_m": 0.6}},
        {"kind": "deep_water", "meta": {"water": True, "move_anim": "breast-stroke"}},
        {"kind": "bog", "meta": {"move_anim": "wade"}},
        {"kind": "grass", "meta": {}}]
    before = copy.deepcopy(rows)
    out, ov, warn = plan_terrain_movement(rows, "swim", "treading-water")
    assert out[0]["meta"] == {"water": True, "movement": "swim", "move_sink_m": 0.6}
    assert out[2]["meta"] == {"movement": "walk_run"} and len(warn) == 1
    assert [r["kind"] for r in out] == ["water", "deep_water", "bog"]
    assert ov == {"swimming": "breast-stroke"}
    assert rows == before
    print("[W1-W4] pure conversion, warning, unchanged rows, override: OK")
    votes = [{"kind": str(i), "meta": {"water": True, "move_anim": clip, "idle_anim": "custom-tread"}} for i, clip in enumerate(["z", "a", "z"])]
    _, majority, warnings = plan_terrain_movement(votes, "swim", "treading-water")
    assert majority == {"swimming": "z", "treading_water": "custom-tread"} and len(warnings) == 1
    _, tie, warnings = plan_terrain_movement(votes[:2], "swim", "treading-water")
    assert tie["swimming"] == "a" and len(warnings) == 1
    assert plan_terrain_movement([{"kind": "pool", "meta": {"water": True, "idle_anim": "treading-water"}}], "swim", "treading-water")[0][0]["meta"] == {"water": True, "movement": "swim"}
    assert plan_terrain_movement([{"kind": "pool", "meta": {
        "water": True, "move_anim": "swim", "idle_anim": "treading-water"}}],
        "swim", "treading-water")[1:] == ({}, [])
    print("[W7] majority, alphabetical tie, tread, idle-only: OK")
    with catalog_txn("pose"):
        data = read_store("pose", "world")
        stored = copy.deepcopy(read_store("pose", "shared")["entries"]["swimming"])
        stored["prompt"] = "World-specific swimming prompt"
        data["entries"]["swimming"] = stored
        write_store("pose", data, "world")
    entry = copy.deepcopy(pose_catalog.get_catalog("pose")["swimming"])
    raw_shared = copy.deepcopy(read_store("pose", "shared")["entries"]["swimming"])
    with db.transaction() as conn:
        for row in rows:
            conn.execute("INSERT INTO terrain_types (kind, name, color, passable, speed_factor, meta, updated_at) VALUES (?, ?, '#123456', 1, 0.7, ?, '2026-10-25T00:00:00Z')", (row["kind"], row["kind"], json.dumps(row["meta"])))
    terrain_types._bump_types_generation()
    terrain_types.get_type("water")
    from app.models.world import get_world_setting
    with patch("app.core.pose_catalog_edit.write_store", side_effect=OSError("test catalog failure")):
        try:
            migrate_terrain_movement_once()
        except OSError:
            pass
        else:
            raise AssertionError("catalog failure should propagate to boot logger")
    assert not get_world_setting("migrated_terrain_movement_v1")
    with db.transaction() as conn:
        assert json.loads(conn.execute("SELECT meta FROM terrain_types WHERE kind='water'").fetchone()[0]) == rows[0]["meta"]
    print("[W8] catalog failure keeps legacy rows and guard unset for retry: OK")
    stats = migrate_terrain_movement_once()
    assert stats == {"rows": 4, "changed": 3, "overrides": 1, "warnings": 1}
    assert get_world_setting("migrated_terrain_movement_v1") == "1"
    world_before_rerun = read_store("pose", "world")
    assert migrate_terrain_movement_once() == {}
    assert read_store("pose", "world") == world_before_rerun
    assert terrain_types.get_type("water")["meta"] == out[0]["meta"]
    actual = pose_catalog.get_catalog("pose")["swimming"]
    assert actual["animation"] == "breast-stroke"
    assert {k: v for k, v in actual.items() if k not in ("animation", "_store")} == {k: v for k, v in entry.items() if k not in ("animation", "_store")}
    with db.transaction() as conn:
        assert json.loads(conn.execute("SELECT meta FROM terrain_types WHERE kind='water'").fetchone()[0]) == out[0]["meta"]
    assert terrain_types.get_type("water")["speed_factor"] == 0.7
    # The world copy is the STORED entry with the clip changed — never the
    # normalised catalog view (places/yaw_offset on a solo pose made
    # validate_catalog report "places/yaw_offset only make sense on a pair pose").
    assert read_store("pose", "world")["entries"]["swimming"] == {**stored, "animation": "breast-stroke"}
    assert not [p for p in pose_catalog.validate_catalog("pose") if "swimming" in p]
    print("[W5-W6] temporary DB, idempotency, full world override, cache: OK")
    # Without a world entry the copy comes from the shipped file, same rule.
    with catalog_txn("pose"):
        data = read_store("pose", "world")
        del data["entries"]["swimming"]
        write_store("pose", data, "world")
    with db.transaction() as conn:
        conn.execute("UPDATE terrain_types SET meta=? WHERE kind='water'", (json.dumps(rows[0]["meta"]),))
        conn.execute("DELETE FROM world_kv WHERE key='migrated_terrain_movement_v1'")
    terrain_types._bump_types_generation()
    assert migrate_terrain_movement_once()["overrides"] == 1
    assert read_store("pose", "world")["entries"]["swimming"] == {**raw_shared, "animation": "breast-stroke"}
    assert not [p for p in pose_catalog.validate_catalog("pose") if "swimming" in p]
    print("[W9] world copy = stored entry, no stray pair fields: OK")
print("terrain movement migration: PASS")
