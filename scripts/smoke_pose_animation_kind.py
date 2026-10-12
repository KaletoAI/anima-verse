#!/usr/bin/env python3
"""Smoke generated clip naming and provenance in disposable libraries.

Usage: .venv/bin/python scripts/smoke_pose_animation_kind.py

Names occupied anywhere require -u, then -u2; only the same UniMate pose
owns a replaceable root clip. Numeric underscores must survive name parsing.
"""
import json
import os
import sys
import tempfile
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        free = root / "clips"
        licensed = root / "clips-licensed"
        for p in (free, licensed):
            p.mkdir()
        os.environ.update(ANIMATION_CLIPS_DIR=str(free),
                          ANIMATION_CLIPS_LICENSED_DIR=str(licensed),
                          ANIMATION_CLIPS_INBOX_DIR=str(root / "inbox"),
                          ANIMATION_RIG_FILE=str(root / "reference.fbx"))
        from app.core import animation_clips as clips

        def put(name, meta=None, library=free):
            p = library / (name + ".fbx")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch()
            p.with_suffix(".json").write_text(json.dumps(meta or {}))

        def check(base, expected):
            actual = clips.reserve_kind(base, pose_key=base)
            assert actual == expected, (base, actual, expected)
            assert clips.parse_clip_name(actual + ".fbx") == actual

        check("sweeping", "sweeping")
        put("sweeping")
        check("sweeping", "sweeping-u")
        put("sweeping-u")
        check("sweeping", "sweeping-u2")
        put("sweeping", {"source": {"generator": "unimate", "pose_key": "sweeping"},
                         "license": "CC-BY-NC-4.0"})
        check("sweeping", "sweeping")
        entry = next(e for e in clips.clip_entries() if e["kind"] == "sweeping")
        view = clips.clip_view(entry)
        assert (view["origin"], view["generator"], view["license"]) == (
            "unimate", "unimate", "CC-BY-NC-4.0")
        put("sweeping", {"source": {"generator": "unimate", "pose_key": "other"}})
        (free / "sweeping-u.fbx").unlink()
        (free / "sweeping-u.json").unlink()
        check("sweeping", "sweeping-u")
        for p in free.iterdir():
            p.unlink()
        check("wave_02", "wave-02")
        check("Fegen Boden", "fegen boden")
        put("licensed-only", {"source": {"generator": "unimate", "pose_key": "licensed-only"}},
            library=licensed)
        check("licensed-only", "licensed-only-u")
        put("owned-twin", {"source": {"generator": "unimate", "pose_key": "owned-twin"}})
        put("owned-twin", {"source": {"generator": "other", "pose_key": "other"}},
            library=licensed)
        check("owned-twin", "owned-twin")
        put("invalid-owner")
        owner_sidecar = free / "invalid-owner.json"
        for contents in ("{", "[]", '{"source": []}', '{"source": "unimate"}'):
            owner_sidecar.write_text(contents)
            check("invalid-owner", "invalid-owner-u")
        owner_sidecar.unlink()
        check("invalid-owner", "invalid-owner-u")
        put("sit/sweeping", library=licensed)
        check("sweeping", "sweeping-u")
        put("dance__a")
        put("dance__b")
        check("dance", "dance-u")
        entry = next(e for e in clips.clip_entries() if e["kind"] == "dance")
        view = clips.clip_view(entry)
        assert (view["generator"], view["license"]) == ("", "")
        from app.core import fbx_import as importer
        src, rest = root / "motion.fbx", root / "rest.fbx"
        for path in (src, rest):
            path.write_text("Hips\nLeftUpLeg\nLeftForeArm\nSpine2\n")
        rig = root / "reference.fbx"
        rig.touch()
        out = root / "staging"

        def convert(script, *, inputs, params, out_dir, timeout_s):
            assert script == "fbx_clip"
            assert inputs == {"rig": rig, "src": src, "rest": rest}
            assert params["takes"] == [{"take": 0, "take_count": 0, "take_name": ""}]
            assert params["rest_take"] == {"take": None, "take_count": 0, "take_name": ""}
            assert params["fps"] == 30 and params["root_motion"] == "strip"
            (out_dir / "generated.fbx").touch()
            (out_dir / "generated.json").write_text(json.dumps({
                "source": {"bone_map": "mixamo-noprefix"}, "frames": 60}))
            return {"ok": True}

        with patch.object(importer.runner, "status", return_value={"executable": "fixture"}), \
                patch.object(importer.runner, "run", side_effect=convert), \
                patch.object(importer, "reload_clip_caches") as reload:
            result = importer.import_source(
                "generated", src, rest, out_dir=out, loop_s=None,
                source_extra={"generator": "unimate", "license": "CC-BY-4.0"})
            assert result["fbx"] == out / "generated.fbx"
            assert result["meta"]["frames"] == 60
            assert result["meta"]["source"] == {
                "bone_map": "mixamo-noprefix", "generator": "unimate", "license": "CC-BY-4.0"}
            assert json.loads(result["sidecar"].read_text()) == result["meta"]
            assert not reload.called
            assert sorted(p.name for p in out.iterdir()) == ["generated.fbx", "generated.json"]
            rest.write_text("Hips\nLeft_UpperLeg\nLeft_UpperArm\nChest\n")
            try:
                importer.import_source("generated", src, rest, out_dir=out, loop_s=None)
            except importer.ClipImportError as error:
                assert "SAME rig" in str(error)
            else:
                raise AssertionError("mismatched canonical rest accepted")
        print("PASS: generated kind reservation, roundtrips and provenance")


if __name__ == "__main__":
    main()
