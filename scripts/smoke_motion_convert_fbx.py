#!/usr/bin/env python3
"""Real-Blender smoke: a reference-rig FBX enters the generated-clip converter.

Usage: ./.venv/bin/python scripts/smoke_motion_convert_fbx.py
Skips (exit 0) when no usable Blender is installed.

Fixture: shared/models/clips/celebrating.fbx — a library clip on the reference
rig (69 ``mixamorig:`` bones, one action over frames 2..181), the same shape a
reference_rig backend (Kimodo) delivers. Expected by hand (plan v3 Task 4):
1. glb_to_ref_fbx with inputs {src: celebrating.fbx, ref: reference.fbx} and
   format "fbx" -> ok, frames 181 - 2 + 1 = 180, fps 30, scale 1.0 (no
   rescale: the file already sits on the reference rig), bones 69, and both
   motion.fbx and rest.fbx are written.
2. The reference rig itself (no action) as src -> not ok, "exactly one animation".
3. An unknown format "obj" -> not ok, "unsupported format".
4. The output of 1 goes on through the real chain: import_source -> a clip of
   180 frames with a sidecar; clip_measure -> 69 bones; check_clip for the
   place type "stand" finds no structural defect (bones, tracks, duration).
5. The same clip re-saved at 24 fps WITHOUT retiming its keys (frames 2..181
   now span 179 / 24 = 7.458 s): the converter resamples to 30 fps keeping
   that duration -> fps 30, frames 179 * 30 / 24 + 1 = 224.75 -> 224 or 225.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.blender import runner

FIXTURE = ROOT / "shared/models/clips/celebrating.fbx"
REF = ROOT / "shared/models/rig/reference.fbx"


def convert(src, fmt, out):
    return runner.run("glb_to_ref_fbx", inputs={"src": src, "ref": REF},
                      params={"format": fmt}, out_dir=out, timeout_s=300)


def main():
    if not runner.status().get("usable"):
        print("SKIP: no usable Blender")
        return
    with tempfile.TemporaryDirectory() as td:
        got = convert(FIXTURE, "fbx", Path(td) / "a")
        assert got["ok"], got["error"]
        assert got["data"] == {"frames": 180, "fps": 30, "scale": 1.0, "bones": 69}, got["data"]
        for name in ("motion", "rest"):
            assert Path(got["outputs"][name]).stat().st_size > 0
        print("PASS 1: reference-rig FBX converts without rescale (180 frames, 69 bones)")
        got = convert(REF, "fbx", Path(td) / "b")
        assert not got["ok"] and "exactly one animation" in got["error"], got
        print("PASS 2: an FBX without animation is refused")
        got = convert(FIXTURE, "obj", Path(td) / "c")
        assert not got["ok"] and "unsupported format" in got["error"], got
        print("PASS 3: unknown format refused")
        os.environ.update(STORAGE_DIR=td, INSTANCE_DIR=td,
                          ANIMATION_CLIPS_DIR=td + "/clips", ANIMATION_CLIPS_INBOX_DIR=td + "/inbox",
                          ANIMATION_CLIPS_LICENSED_DIR=td + "/licensed")
        from app.core import paths
        paths.init(td)
        from app.core.fbx_import import import_source
        from app.core.pose_animation import check_clip
        good = convert(FIXTURE, "fbx", Path(td) / "d")
        clip = import_source("celebrating-gen", Path(good["outputs"]["motion"]),
                             Path(good["outputs"]["rest"]), out_dir=Path(td) / "d" / "clip",
                             loop_s=None, root_motion="strip",
                             source_extra={"generator": "kimodo", "generated_for_pose": "x"})
        assert clip["meta"]["frames"] == 180 and Path(clip["sidecar"]).is_file(), clip["meta"]
        measured = runner.run("clip_measure", inputs={"clip": clip["fbx"]}, out_dir=Path(td) / "m")
        assert measured["ok"] and len(measured["data"]["bones"]) == 69, measured.get("error")
        structural = [r for r in check_clip(clip["meta"], measured["data"], "stand", False)
                      if "hip height" not in r and "foot" not in r]
        assert structural == [], structural
        print("PASS 4: the converted FBX imports, measures 69 bones and has no structural defect")
        slow = Path(td) / "slow.fbx"
        script = ("import bpy, sys\n"
                  "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
                  "bpy.context.scene.render.fps = 30\n"
                  f"bpy.ops.import_scene.fbx(filepath={str(FIXTURE)!r})\n"
                  "act = bpy.data.actions[0]\n"
                  "bpy.context.scene.frame_start, bpy.context.scene.frame_end = "
                  "int(act.frame_range[0]), int(act.frame_range[1])\n"
                  "bpy.context.scene.render.fps = 24\n"
                  f"bpy.ops.export_scene.fbx(filepath={str(slow)!r}, object_types={{'ARMATURE'}}, "
                  "add_leaf_bones=False, bake_anim=True, bake_anim_use_all_actions=False, "
                  "bake_anim_use_nla_strips=False)\n")
        subprocess.run([runner.status()["executable"], "-b", "--python-expr", script],
                       check=True, capture_output=True, timeout=300)
        got = convert(slow, "fbx", Path(td) / "e")
        assert got["ok"], got["error"]
        assert got["data"]["fps"] == 30 and got["data"]["frames"] in (224, 225), got["data"]
        print("PASS 5: a 24 fps FBX is resampled to 30 fps over the same duration")
    print("All motion FBX conversion smokes passed")


if __name__ == "__main__":
    main()
