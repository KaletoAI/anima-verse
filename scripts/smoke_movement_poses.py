#!/usr/bin/env python3
"""Smoke movement poses with isolated catalogs, clips and world storage.

Usage: ./.venv/bin/python scripts/smoke_movement_poses.py

Hand-derived Task 2 expectations: seven poses map to idle/walk/run/swim/
treading-water/crawl/crawl-rest. Two world overrides affect played kinds
only. Female walk wins over neutral; licensed walk shadows free walk only
when licensed clips are allowed. Missing and pair-only kinds resolve to None.
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
        init_schema()
        from app.routes.assets import list_animation_clips
        kinds = {"standing": "idle", "walking": "walk", "running": "run",
                 "swimming": "swim", "treading_water": "treading-water",
                 "crawling": "crawl", "crawling_rest": "crawl-rest"}
        entries = {key: {"animation": kind, "prompt": key} for key, kind in kinds.items()}
        catalog = root / "pose_catalog.json"
        catalog.write_text(json.dumps({"entries": entries}), encoding="utf-8")
        for name in (*kinds.values(), "breast-stroke", "pair__a", "pair__b"):
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
            pc.replace_world_entries("pose", {})
            pc.reload_catalogs()
            for file in licensed.iterdir():
                file.unlink()
            check("[M3] public", movement_pose_kinds() == {key: {"kind": kind, "public_kind": kind} for key, kind in kinds.items()} and all(clip_file_for(kind, [], free_only=False)["library"] == "free" for kind in kinds.values()))
            (licensed / "walk.fbx").write_bytes(b"clip")
            check("[M4] set chain", clip_file_for("walk", ["missing", "female"], free_only=False)["set"] == "female")
            played = clip_file_for("walk", [], free_only=False)
            public = clip_file_for("walk", [], free_only=True)
            check("[M5] licensed shadow", played["library"] == "licensed" and public["library"] == "free" and played["url"].startswith("/assets/animation-clips/licensed/walk.fbx?v=") and public["url"].startswith("/assets/animation-clips/walk.fbx?v="))
            (licensed / "mob1-walk.fbx").write_bytes(b"clip")
            check("[M6] missing", clip_file_for("fly", ["female"], free_only=False) is None and clip_file_for("mob1-walk", [], free_only=True) is None and clip_file_for("pair", [], free_only=False) is None)
            payload = list_animation_clips()
            check("[M7] payload", payload.get("movement_poses") == movement_pose_kinds() and "locomotion" not in payload)
        pc.reload_catalogs()
    print(f"{len(FAILURES)} failures")
    return bool(FAILURES)


if __name__ == "__main__":
    sys.exit(main())
