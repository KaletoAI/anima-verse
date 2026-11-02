#!/usr/bin/env python3
"""Synthetic library BVH round trip, without a world DB.

Usage: ALSOFT_DRIVERS=null ./.venv/bin/python scripts/smoke_clip_bvh_export.py

Hand derivation: write_fixture has 31 samples at 30 Hz: (31-1)/30 = 1 s.
Hips Z moves 0 to -30 cm; keep-mode travel is -0.30 * hips_scale metres.
GATING: export has 31 frames, licensed provenance, and unprefixed joints.
Read the exported BVH directly with Blender: per-frame world positions of
Hips, LeftFoot, RightFoot, LeftToeBase and RightToeBase must differ from the
source by at most 0.1 cm. The exporter writes the same rig and animation,
so only float formatting may differ; this is export exactness, not retargeting.
The exported root travel must equal source travel within 0.001 m.
The root has six channels and units cm.
NON-GATING INFO: the import_fbx round trip uses mixamo-noprefix. Anima's
positional Mixamo-BVH re-import currently shows foot errors up to ~30 cm
(pre-existing, tracked separately). Print mean/max hips and foot errors,
without treating them as export failures. Generated clips return as SOMA BVH.
A .2.. .7 s crop has (.7-.2)*30+1 = 16 samples. Set overrides neutral;
a licensed twin overrides free. Fixtures are synthetic; no sample motions.
"""
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smoke_bvh_soma_import import write_fixture


def main():
    with tempfile.TemporaryDirectory(prefix="smoke-clip-bvh-") as temporary:
        root = Path(temporary)
        for var, name in (("ANIMATION_CLIPS_DIR", "free"),
                          ("ANIMATION_CLIPS_LICENSED_DIR", "licensed"),
                          ("ANIMATION_CLIPS_INBOX_DIR", "inbox")):
            (root / name).mkdir()
            os.environ[var] = str(root / name)
        from app.core.clip_bvh_export import export_clip_bvh
        from app.core.fbx_import import import_fbx, probe_fbx
        from app.blender import runner
        write_fixture(root / "inbox/src.bvh")
        source = import_fbx("smoke-src", [{"name": "src.bvh"}], root_motion="keep")
        src = root / "licensed/smoke-src.fbx"
        shutil.copy2(src, root / "free/smoke-src.fbx")
        out = root / "inbox/back.bvh"
        info = export_clip_bvh("smoke-src", "missing", out)
        assert info["frames"] == 31 and info["fps"] == 30, info
        assert abs(info["duration_s"] - 1) < 1e-6, info
        assert info["library"] == "licensed" and info["source_rel"] == "smoke-src.fbx", info
        text = out.read_text()
        assert "mixamorig:" not in text and "CHANNELS 6" in text.split("JOINT")[0]
        assert probe_fbx(out)["skeleton_family"] == "mixamo-noprefix"
        assert info["joints"] and all("mixamorig:" not in joint for joint in info["joints"]), info
        print(f"GATING frames={info['frames']}, library={info['library']}, joints={len(info['joints'])}, unprefixed=True", flush=True)
        measures = []
        for path in (src, out):
            result = runner.run("clip_measure", inputs={"clip": path}, timeout_s=900)
            assert result["ok"], result
            measures.append(result["data"]["joint_positions_m"])
        for name in ("Hips", "LeftFoot", "RightFoot", "LeftToeBase", "RightToeBase"):
            first, second = (m[name] for m in measures)
            assert len(first) == len(second) == 31
            errors = [100 * math.dist(x, y) for x, y in zip(first, second)]
            mean, maximum = sum(errors) / len(errors), max(errors)
            print(f"GATING direct {name}: mean_cm={mean:.6f}, max_cm={maximum:.6f}", flush=True)
            assert maximum <= .1, (name, mean, maximum)
        travels = [[points[-1][axis] - points[0][axis] for axis in (0, 2)]
                   for points in (m["Hips"] for m in measures)]
        error = math.dist(*travels)
        print(f"GATING root travel_src_m={travels[0]}, travel_bvh_m={travels[1]}, error_m={error:.9f}", flush=True)
        assert error <= .001, error
        # Diagnostic only: this re-import is not used by the generation pipeline.
        try:
            back = import_fbx("smoke-back", [{"name": "back.bvh"}], root_motion="keep")
            family = back["sidecar"]["source"]["bone_map"]
            result = runner.run("clip_measure", inputs={"clip": root / "licensed/smoke-back.fbx"}, timeout_s=900)
            if not result["ok"]:
                raise RuntimeError(result["error"])
            measured_back = result["data"]["joint_positions_m"]
            for name in ("Hips", "LeftFoot", "RightFoot"):
                first, second = measures[0][name], measured_back[name]
                if len(first) != len(second):
                    raise ValueError(f"{name} frame count differs: {len(first)} / {len(second)}")
                errors = [100 * math.dist(x, y) for x, y in zip(first, second)]
                print(f"INFO roundtrip family={family} {name}: mean_cm={sum(errors)/len(errors):.6f}, max_cm={max(errors):.6f}", flush=True)
        except Exception as exc:
            print(f"INFO roundtrip unavailable: {exc}", flush=True)
        (root / "free/female").mkdir()
        shutil.copy2(src, root / "free/female/smoke-src.fbx")
        info = export_clip_bvh("smoke-src", "female", root / "set.bvh", start_s=.2, end_s=.7)
        assert info["library"] == "free" and info["source_rel"] == "female/smoke-src.fbx", info
        assert info["frames"] == 16 and abs(info["duration_s"] - .5) < 1e-6, info
        print("OK smoke_clip_bvh_export")
    return 0


if __name__ == "__main__":
    sys.exit(main())
