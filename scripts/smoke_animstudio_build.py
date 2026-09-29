#!/usr/bin/env python3
"""Smoke: an authored take goes through cmu_clip.run_takes UNCHANGED.

Usage: ./.venv/bin/python scripts/smoke_animstudio_build.py

Needs Blender (SKIP otherwise). No world, clip libraries are temp dirs, the
studio's out/ is redirected into a temp dir. Expectations by hand:

[1] IDENTITY: an animation with no values (1 s, standing) is the rig rest.
    Every exported quaternion is (1,0,0,0) within 1e-4. The floor:
    run_takes puts the LOWEST point of the take at y = 0; at rest that is
    the lowest bone TAIL of the 22 core bones (the ToeBase tail, measured
    -0.0086 cm - the rig does not stand exactly on 0). So the Hips head
    reads y = rest Hips y - min(core tails y) (= 113.0407) +- 0.01 cm in
    every frame, and floor_shift_cm = round(-min, 2) (= 0.01) +- 0.005.
    That proves the alignment A is the identity and the leg ratio exactly 1
    (a ratio != 1 lifts the hips by hips_y*(k-1), cmu_clip._hips_lift).
[2] ONE JOINT: l_arm_elev = 90 for 1 s -> the LeftForeArm head sits straight
    above the LeftArm head: dx, dz within 0.05 cm, dy = the upper-arm length
    (|head(LeftForeArm)-head(LeftArm)| from rig_rest.json) +- 0.05 cm.
[3] SIDECAR: fps 30, frames 31 (1 s -> 30 steps + 1), loop false,
    source.format "procedural", source_fps 30.0, root_motion.mode "strip".
[4] LYING: body_pitch = -90, hips_drop_cm 93 (1 s): the head stays at -Z
    of the hips - Head.z < Hips.z - 30 cm in frame 1 (the convention
    LIE_HEAD "-z"); without the yaw_deg pass-through _frame_takes would turn
    the body by the degenerate forward of a lying root.
[5] LIFT: the same lying take with lift_cm = 16 -> every joint 16.00 +- 0.01
    cm higher than in [4] (the lift is added after the floor normalisation),
    the sidecar says geometry.lift_cm 16.0 and carries NO geometry.yaw_deg
    (proc_clip strips the pass-through value - it is not a dial setting).
    The re-exported clip keeps its length: 31 keyed frames like [1] (1 s at
    30 fps), not the 250 of an empty Blender scene's default frame range,
    and its action frame range equals [4]'s (the probe imports both the
    same way): _finish re-imports with anim_offset=0, the importer's default
    offset of 1 would re-export every key one frame late.
[6] MEASURE: proc_clip writes measure.json next to the clip, one row per
    frame. The probe imports like _measure (scene fps 30, anim_offset 0),
    so row i of both is clip frame i. A MOVING clip (l_arm_elev keyed
    0 -> 90 linearly over 1 s: the hand swings ~ 55 cm * (pi/2) / 30 ~ 2.9
    cm per frame, asserted > 1 cm so a one-frame shift cannot hide): its 31
    measured rows equal the probe's row by row (LeftHand, LeftForeArm, Hips
    within 0.01 cm). build.json carries the checks (names include floor and
    tracks) with ok == all(check ok).
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FREE = Path(tempfile.mkdtemp(prefix="animstudio-free-"))
os.environ.setdefault("STORAGE_DIR", tempfile.mkdtemp(prefix="animstudio-world-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(FREE)
os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(FREE) + "-licensed"
sys.path.insert(0, str(ROOT / "animation-studio"))

import animstudio                                             # noqa: E402
animstudio.bootstrap()
animstudio.OUT = Path(tempfile.mkdtemp(prefix="animstudio-out-"))

from app.blender import runner                                # noqa: E402

if not runner.is_available():
    print("SKIP smoke_animstudio_build (no Blender)")
    sys.exit(0)

import numpy as np                                            # noqa: E402

from animstudio import build as B                             # noqa: E402
from animstudio.dsl import Animation, Catalog, Key, Pose      # noqa: E402
from animstudio.rig import CORE_BONES, load_rest              # noqa: E402

FAIL = []
CAT = Catalog(key="smoke", group="stand", prompt="standing")
rest = load_rest()

PROBE = r'''
import json, sys
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.context.scene.render.fps = 30
bpy.ops.import_scene.fbx(filepath=sys.argv[-2], global_scale=1.0, use_anim=True, anim_offset=0.0)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
act = arm.animation_data.action
quats = []
for fc in act.fcurves:
    if fc.data_path.endswith("rotation_quaternion"):
        quats += [(fc.array_index, k.co[1]) for k in fc.keyframe_points]
rows = []
f0, f1 = (int(v) for v in act.frame_range)
for f in range(f0, f1 + 1):
    bpy.context.scene.frame_set(f)
    rows.append({pb.name.split(":")[-1]: list(pb.head) for pb in arm.pose.bones})
json.dump({"quats": quats, "rows": rows, "range": [float(v) for v in act.frame_range]},
          open(sys.argv[-1], "w"))
'''


def probe(fbx: Path) -> dict:
    import subprocess
    script = animstudio.OUT / "probe.py"
    script.write_text(PROBE)
    res_path = animstudio.OUT / "probe.json"
    exe = runner.find_executable()
    subprocess.run([exe, "--background", "--factory-startup", "--python", str(script),
                    "--", str(fbx), str(res_path)], check=True, capture_output=True, timeout=600)
    return json.loads(res_path.read_text())


try:
    # [1] identity
    r = B.build("smoke-rest", anim=Animation(kind="smoke-rest", duration_s=1.0, loop=False, catalog=CAT))
    p = probe(Path(r["fbx"]))
    bad = [(i, v) for i, v in p["quats"] if abs(v - (1.0 if i == 0 else 0.0)) > 1e-4]
    if bad:
        FAIL.append(f"[1] non-identity quaternion keys: {bad[:3]}")
    low = min(float(rest.tail[b][1]) for b in CORE_BONES)
    hips_exp = float(rest.head["Hips"][1]) - low
    if len(p["rows"]) != 31:
        FAIL.append(f"[1] clip has {len(p['rows'])} frames, expected 31")
    hy = [row["Hips"][1] for row in p["rows"]]
    if max(abs(y - hips_exp) for y in hy) > 0.01:
        FAIL.append(f"[1] hips y {min(hy):.4f}..{max(hy):.4f}, expected {hips_exp:.4f}")
    names = {c["name"] for c in r["checks"]}
    if not {"floor", "tracks"} <= names or r["ok"] != all(c["ok"] for c in r["checks"]):
        FAIL.append(f"[6] report checks {sorted(names)} ok={r['ok']}")
    # [6] measure, row by row on a moving clip
    rm = B.build("smoke-move", anim=Animation(
        kind="smoke-move", duration_s=1.0, loop=False, catalog=CAT,
        keys=[Key(0.0, Pose(l_arm_elev=0)), Key(1.0, Pose(l_arm_elev=90), ease="linear")]))
    pm = probe(Path(rm["fbx"]))["rows"]
    meas = json.loads((animstudio.OUT / "smoke-move" / "measure.json").read_text())["frames"]
    step = min(float(np.linalg.norm(np.array(a["LeftHand"]) - np.array(b["LeftHand"])))
               for a, b in zip(pm, pm[1:]))
    if step <= 1.0:
        FAIL.append(f"[6] moving clip: smallest hand step {step:.2f} cm, not > 1")
    if len(meas) != 31 or len(pm) != 31:
        FAIL.append(f"[6] measure {len(meas)} rows, probe {len(pm)}, expected 31")
    else:
        worst = max(abs(a - b) for m_, q_ in zip(meas, pm)
                    for j in ("LeftHand", "LeftForeArm", "Hips")
                    for a, b in zip(m_[j], q_[j]))
        if worst > 0.01:
            FAIL.append(f"[6] measure vs probe row by row: {worst:.3f} cm")
    side = json.loads(Path(r["sidecar"]).read_text())
    if abs(side["geometry"]["floor_shift_cm"] - round(-low, 2)) > 0.005:
        FAIL.append(f"[1] floor_shift_cm {side['geometry']['floor_shift_cm']} vs {round(-low, 2)}")
    # [3] sidecar
    exp = {"fps": 30, "frames": 31, "loop": False, "source_fps": 30.0}
    for k, v in exp.items():
        if side.get(k) != v:
            FAIL.append(f"[3] sidecar {k} = {side.get(k)!r}, expected {v!r}")
    if side["source"].get("format") != "procedural":
        FAIL.append("[3] source.format")
    if side["geometry"]["root_motion"]["mode"] != "strip":
        FAIL.append("[3] root_motion.mode")
    # [2] one joint
    r = B.build("smoke-arm", anim=Animation(kind="smoke-arm", duration_s=1.0, loop=False, catalog=CAT,
                                            base=Pose(l_arm_elev=90)))
    row = probe(Path(r["fbx"]))["rows"][0]
    L = float(np.linalg.norm(rest.head["LeftForeArm"] - rest.head["LeftArm"]))
    d = np.array(row["LeftForeArm"]) - np.array(row["LeftArm"])
    if abs(d[0]) > 0.05 or abs(d[2]) > 0.05 or abs(d[1] - L) > 0.05:
        FAIL.append(f"[2] forearm offset {d.round(3).tolist()} vs (0,{L:.3f},0)")
    # [4] lying
    r = B.build("smoke-lie", anim=Animation(kind="smoke-lie", duration_s=1.0, loop=False,
                                            catalog=Catalog(key="l", group="lie", prompt="lying"),
                                            base=Pose(body_pitch=-90, hips_drop_cm=93)))
    p4 = probe(Path(r["fbx"]))
    row = p4["rows"][0]
    if not row["Head"][2] < row["Hips"][2] - 30:
        FAIL.append(f"[4] head z {row['Head'][2]:.1f} not behind hips z {row['Hips'][2]:.1f}")
    # [5] lift
    r5 = B.build("smoke-lift", anim=Animation(kind="smoke-lift", duration_s=1.0, loop=False,
                                              catalog=Catalog(key="l", group="lie", prompt="lying"),
                                              base=Pose(body_pitch=-90, hips_drop_cm=93), lift_cm=16.0))
    p5 = probe(Path(r5["fbx"]))
    if p5["range"] != p4["range"]:
        FAIL.append(f"[5] lifted clip frame range {p5['range']} vs unlifted {p4['range']}")
    if len(p5["rows"]) != 31:
        FAIL.append(f"[5] lifted clip has {len(p5['rows'])} frames, expected 31")
    row5 = p5["rows"][0]
    dy = [row5[j][1] - row[j][1] for j in ("Hips", "Head", "LeftFoot", "RightHand")]
    if max(abs(v - 16.0) for v in dy) > 0.01:
        FAIL.append(f"[5] lift deltas {dy}")
    g5 = json.loads(Path(r5["sidecar"]).read_text())["geometry"]
    if g5.get("lift_cm") != 16.0 or "yaw_deg" in g5:
        FAIL.append(f"[5] sidecar geometry {g5}")
except Exception as e:                                         # noqa: BLE001
    import traceback
    traceback.print_exc()
    FAIL.append(f"crashed: {e!r}")
finally:
    shutil.rmtree(FREE, ignore_errors=True)
    shutil.rmtree(animstudio.OUT, ignore_errors=True)

print("FAIL:\n" + "\n".join(FAIL) if FAIL else "OK smoke_animstudio_build")
sys.exit(1 if FAIL else 0)
