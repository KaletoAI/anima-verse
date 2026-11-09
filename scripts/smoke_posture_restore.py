#!/usr/bin/env python3
"""Numeric check of normalize's POSTURE RESTORE — ``_restore_posture`` in
``app/blender/scripts/normalize.py`` and its frame allowance in
``app/blender/refine.py``.

Usage:
    ./.venv/bin/python scripts/smoke_posture_restore.py

Needs Blender (auto-discovered, or image_generation.blender_executable), no
server, no world DB. Works in a temp directory only. The result is verified
by RE-READING the produced GLB's vertices, not by trusting the report.

WHY THE STEP EXISTS
===================
The rigger (Make-It-Animatable, alias ``mesh-mia``) re-poses the mesh into
its own canonical rest and mis-estimates the spine pitch by a noisy amount:
over 25 Kira deliveries (2026-11-09) the mesher's output had the head
-3.7..+2.8 cm in front of the hips, the rigged result of the SAME mesh
-3.3..+16.4 cm. The unrigged mesh is the ground truth, so normalize turns
the trunk chain back onto it. The clients keep every joint's bind relative
to the pelvis on purpose, so a lean the rigger left is a lean in every clip.

THE FIXTURE, AND THE EXPECTATIONS DERIVED BY HAND
=================================================
A vertical column, radius 0.08 m, z 0..1.70, a ring every 2 cm, Blender
world (Z up, the figure faces -Y). Skinned rigidly to a Mixamo chain:
Hips 0.95, Spine 1.05, Spine1 1.15, Spine2 1.27, Neck 1.43, Head 1.52..1.70
(each vertex to the bone whose segment holds its z; below Hips to Hips).
The SOURCE is the same column without any rig. Being uniform, every
sagittal band of the source has centre y = 0 — whatever band the step picks.

The LEANING rig is that column with Spine2 pitched 10 deg FORWARD about +X
through its joint and Neck another 10 deg (20 deg above the neck), baked as
rest — the rigger's deed. Forward is -Y, so a rotation about +X by +10 deg
moves the skin above the pivot to negative y. Positions after the lean:

    neck joint : z = 1.27 + 0.16 cos10 = 1.4276,  y = -0.16 sin10 = -0.0278
    head joint : z = 1.4276 + 0.09 cos20 = 1.5122, y = -0.0278 - 0.09 sin20 = -0.0586
    crown axis : z = 1.4276 + 0.18 cos20 = 1.5967, y = -0.0278 - 0.18 sin20 = -0.0894

[1] THE MEASUREMENT READS THE LEAN. ``before`` (cm of a 1.70-m figure, the
    rigged height is ~1.62 after the lean so to_cm = 1.70/1.62): the neck band
    sits ~2.9 cm and the head band ~6.1 cm forward, the spine1 and spine2
    bands (below the pivot) ~0 — checked to +-1.0 cm, a band is 2.5 cm tall
    on a tilted column so its centre is not exactly the axis. The head middle
    (z ~1.57) has its axis 7.9 cm forward, but the band also catches the
    tilted OPEN RIM of the column whose forward edge sits at 16.5 cm, so its
    centre lands between the axis and that edge: checked as "at least 1.5 cm
    more than the head band and under 12 cm" (a round skull has no rim).

[2] THE RULE UNDOES THE LEAN. The excess profile e(z) sampled every 1.2 % of
    the height is 0 up to the Spine2 joint, then rises with slope tan10 to
    the neck joint and with tan20 above it — exactly two hinges of 10 deg at
    Spine2 and Neck. Every rotation is about the same axis (+X), so the
    orientation of the top of the chain changes by the SUM of the applied
    angles whatever the split: a straight column again means a total of
    -20 deg (checked to +-2). The split itself is the ridge's: five hinges
    0.09..0.55 m above the hips are nearly collinear, and the penalty trades
    a little residual for spreading each 10-deg hinge onto its neighbours, so
    Spine2 and Neck each keep -4..-12 deg and no neighbour exceeds 5 deg
    (measured -7.5 / -6.7 with -3.3 / -3.6 beside them). Two passes leave
    every ``after`` band within 0.6 cm of zero.

[3] THE GEOMETRY IS STRAIGHT AGAIN. Re-read from the output GLB (Y up,
    forward +Z): the mean z of all vertices above y = 1.55 is within 0.6 cm of
    zero — before the restore it was 8.9 cm (the crown axis above).

[4] A STRAIGHT RIG IS LEFT ALONE. The unleaned rig with the same source:
    every ``before`` band under the 1.5-cm trigger, ``corrected`` False,
    ``applied`` empty, and every output vertex within 1e-6 of the input (the
    column is already centred and grounded, so normalize moves nothing).

[5] THE FRAME GATE LETS EXACTLY THE REPORTED PITCH THROUGH. The output of
    [2] turned the Spine2 and Neck frames by ~10 deg each — more than the 5-deg
    tolerance, so ``rig_frames_preserved`` REJECTS it without an allowance and
    ACCEPTS it with ``normalize_allowance(data)`` (10 + 5). The production path
    ``refine.normalize(path, 1.70, posture_source=source)`` therefore applies.

[6] THE ALLOWANCE SUMS. normalize_allowance({head_twist applied neck 3,
    posture applied spine2 -10, neck -9.8}) = {neck: 12.8, spine2: 10.0};
    nothing without ``corrected``, nothing for a joint outside the chain.
"""
import json
import math
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.blender import refine, runner                        # noqa: E402

FIXTURE = r'''
import bpy, math, sys
from mathutils import Matrix, Vector
out = sys.argv[sys.argv.index("--") + 1]
SEGMENTS = [("mixamorig:Hips", 0.95, 1.05), ("mixamorig:Spine", 1.05, 1.15),
            ("mixamorig:Spine1", 1.15, 1.27), ("mixamorig:Spine2", 1.27, 1.43),
            ("mixamorig:Neck", 1.43, 1.52), ("mixamorig:Head", 1.52, 1.70)]

def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)

def column():
    verts, faces = [], []
    rings = 86
    for r in range(rings):
        z = 0.02 * r
        for k in range(16):
            a = 2 * math.pi * k / 16
            verts.append((0.08 * math.cos(a), 0.08 * math.sin(a), z))
    for r in range(rings - 1):
        for k in range(16):
            a, b = r * 16 + k, r * 16 + (k + 1) % 16
            faces.append((a, b, b + 16, a + 16))
    me = bpy.data.meshes.new("column")
    me.from_pydata(verts, [], faces)
    obj = bpy.data.objects.new("column", me)
    bpy.context.scene.collection.objects.link(obj)
    return obj

def rig(obj):
    arm = bpy.data.armatures.new("rig")
    armo = bpy.data.objects.new("Armature", arm)
    bpy.context.scene.collection.objects.link(armo)
    bpy.context.view_layer.objects.active = armo
    bpy.ops.object.mode_set(mode="EDIT")
    parent = None
    for name, z0, z1 in SEGMENTS:
        b = arm.edit_bones.new(name)
        b.head = (0, 0, z0); b.tail = (0, 0, z1)
        if parent is not None:
            b.parent = parent
        parent = b
    bpy.ops.object.mode_set(mode="OBJECT")
    for name, z0, z1 in SEGMENTS:
        vg = obj.vertex_groups.new(name=name)
        idx = [v.index for v in obj.data.vertices
               if (z0 <= v.co.z < z1) or (name.endswith("Hips") and v.co.z < z0)
               or (name.endswith("Head") and v.co.z >= z1)]
        vg.add(idx, 1.0, "REPLACE")
    mod = obj.modifiers.new("Armature", "ARMATURE")
    mod.object = armo
    obj.parent = armo
    return armo

def export(path):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB")

# the source: the bare column
fresh(); column(); export(out + "/source.glb")

# the straight rig
fresh(); obj = column(); rig(obj); export(out + "/straight.glb")

# the leaning rig: Spine2 +10 deg, Neck +10 deg about +X through the joint, baked as rest
fresh(); obj = column(); armo = rig(obj)
bpy.context.view_layer.objects.active = armo
bpy.ops.object.mode_set(mode="POSE")
for name in ("mixamorig:Spine2", "mixamorig:Neck"):
    p = armo.pose.bones[name]
    m = armo.matrix_world @ p.matrix
    pivot = m.translation
    rot = Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(10), 4, Vector((1, 0, 0))) @ Matrix.Translation(-pivot)
    p.matrix = armo.matrix_world.inverted() @ rot @ m
    bpy.context.view_layer.update()
bpy.ops.object.mode_set(mode="OBJECT")
bpy.context.view_layer.objects.active = obj
bpy.ops.object.modifier_copy(modifier="Armature")
bpy.ops.object.modifier_apply(modifier="Armature")
bpy.context.view_layer.objects.active = armo
bpy.ops.object.mode_set(mode="POSE")
bpy.ops.pose.armature_apply(selected=False)
bpy.ops.object.mode_set(mode="OBJECT")
export(out + "/leaning.glb")
print("FIXTURES_OK")
'''

failures = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def positions(path):
    raw = Path(path).read_bytes()
    length = struct.unpack_from("<I", raw, 12)[0]
    doc = json.loads(raw[20:20 + length])
    start = 28 + length
    result = []
    for mesh in doc["meshes"]:
        for primitive in mesh["primitives"]:
            a = doc["accessors"][primitive["attributes"]["POSITION"]]
            v = doc["bufferViews"][a["bufferView"]]
            offset = start + v.get("byteOffset", 0) + a.get("byteOffset", 0)
            stride = v.get("byteStride", 12)
            result += [struct.unpack_from("<3f", raw, offset + i * stride) for i in range(a["count"])]
    return result


def main():
    print("[6] the allowance")
    allow = refine.normalize_allowance({"head_twist": {"corrected": True, "applied": {"neck": 3}},
                                        "posture": {"corrected": True, "applied": {"spine2": -10, "neck": -9.8}}})
    check("[6] sums per joint", allow == {"neck": 12.8, "spine2": 10.0}, str(allow))
    check("[6] nothing without corrected",
          refine.posture_allowance({"posture": {"corrected": False, "applied": {"spine2": 20}}}) == {})
    check("[6] nothing outside the chain",
          refine.posture_allowance({"posture": {"corrected": True, "applied": {"hips": 9, "head": float("nan")}}}) == {})

    st = runner.status()
    if not st["usable"]:
        print("SKIP Blender:", st["error"])
        return
    with tempfile.TemporaryDirectory(prefix="smoke-posture-") as tmp:
        root = Path(tmp)
        script = root / "fixture.py"
        script.write_text(FIXTURE)
        proc = subprocess.run([st["executable"], "-b", "--factory-startup", "--python-exit-code", "1",
                               "--python", str(script), "--", tmp], capture_output=True, text=True, timeout=240)
        assert "FIXTURES_OK" in proc.stdout, proc.stdout[-4000:] + proc.stderr[-2000:]
        source = root / "source.glb"

        print("[1]-[3] the leaning rig")
        res = runner.run("normalize", inputs={"model": root / "leaning.glb", "source": source},
                         params={"target_height_m": 1.70}, out_dir=root / "out_lean")
        assert res["ok"], res
        posture = res["data"]["posture"]
        print("   report:", json.dumps(posture))
        check("[1] no error", not posture["error"], posture["error"])
        before = posture["before"]
        check("[1] neck band ~2.9 cm", abs(before.get("neck", 0) - 2.9) <= 1.0, str(before.get("neck")))
        check("[1] head band ~6.1 cm", abs(before.get("head", 0) - 6.1) <= 1.0, str(before.get("head")))
        check("[1] head middle above the head band, under the rim",
              before.get("head", 0) + 1.5 <= before.get("head_mid", 0) <= 12.0, str(before.get("head_mid")))
        check("[1] spine bands ~0", all(abs(before.get(k, 0)) <= 1.0 for k in ("spine1", "spine2")),
              str({k: before.get(k) for k in ("spine1", "spine2")}))
        applied = posture["applied"]
        check("[2] corrected", posture["corrected"])
        total = sum(applied.values())
        check("[2] the chain is pitched back 20 deg in total", abs(total + 20) <= 2.0, f"{total:.2f}")
        check("[2] spine2 and neck carry the bulk (each -4..-12 deg)",
              all(-12 <= applied.get(k, 0) <= -4 for k in ("spine2", "neck")), str(applied))
        check("[2] the neighbours take the ridge's share only (|.| <= 5 deg)",
              all(abs(v) <= 5.0 for k, v in applied.items() if k not in ("spine2", "neck")), str(applied))
        check("[2] every band straight after", all(abs(v) <= 0.6 for v in posture["after"].values()),
              str(posture["after"]))
        out_lean = Path(res["outputs"]["model"])
        head = [p for p in positions(out_lean) if p[1] > 1.55]
        z_mean = sum(p[2] for p in head) / len(head)
        check("[3] head geometry straight (mean z above 1.55 m)", abs(z_mean) <= 0.006, f"{z_mean * 100:.2f} cm")
        lean_head = [p for p in positions(root / "leaning.glb") if p[1] > 1.55]
        z_lean = sum(p[2] for p in lean_head) / len(lean_head)
        check("[3] counter-probe: the input WAS leaning", z_lean > 0.06, f"{z_lean * 100:.2f} cm")

        print("[4] the straight rig")
        res = runner.run("normalize", inputs={"model": root / "straight.glb", "source": source},
                         params={"target_height_m": 1.70}, out_dir=root / "out_straight")
        assert res["ok"], res
        posture = res["data"]["posture"]
        print("   report:", json.dumps(posture))
        check("[4] under the trigger", all(abs(v) < 1.5 for v in posture["before"].values()), str(posture["before"]))
        check("[4] not corrected, nothing applied", not posture["corrected"] and not posture["applied"])
        before_pts = positions(root / "straight.glb")
        after_pts = positions(res["outputs"]["model"])
        check("[4] same vertex count", len(before_pts) == len(after_pts))
        worst = max(min(max(abs(a - b) for a, b in zip(p, q)) for q in after_pts[::7] + after_pts[:50])
                    for p in before_pts[::7])
        check("[4] geometry untouched", worst <= 1e-6, f"worst {worst:.2e}")

        print("[5] the frame gate")
        from app.core.model_validate import rig_frames_preserved
        lean_bytes = (root / "leaning.glb").read_bytes()
        out_bytes = out_lean.read_bytes()
        plain = rig_frames_preserved(lean_bytes, out_bytes)
        check("[5] rejected without an allowance", not plain["ok"], "; ".join(plain["errors"])[:160])
        allowed = rig_frames_preserved(lean_bytes, out_bytes,
                                       allowed_deg=refine.normalize_allowance(
                                           {"posture": {"corrected": True, "applied": applied}}))
        check("[5] accepted with the reported pitch", allowed["ok"], "; ".join(allowed["errors"])[:160])
        import shutil
        prod = root / "prod.glb"
        shutil.copy2(root / "leaning.glb", prod)
        res = refine.normalize(prod, 1.70, posture_source=source)
        check("[5] refine.normalize applies through the gate", bool(res.get("applied")), str(res.get("error")))

    if failures:
        print(f"\nFAILED: {len(failures)} check(s): {failures}")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
