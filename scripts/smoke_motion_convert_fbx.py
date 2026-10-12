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
"""
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
    print("All motion FBX conversion smokes passed")


if __name__ == "__main__":
    main()
