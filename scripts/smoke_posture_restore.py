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

THE FINGER RESET (``scripts/hand_restore.py`` + ``_hand_restore.py``, the
step right after normalize; hand analysis 2026-11-18 § 1.3)
==================================================================
The rigger also bends FINGERS against the palm (fans, hooks the mesher never
made); the unrigged mesh is the ground truth of the hand as of the trunk.

Fixture, Blender world (Z up). A body box x,y +-0.1, z 0..1.70 (Hips; it
only gives the figure its height H = 1.70, so the hand region is 0.16 H =
0.272 m around the hand joint and the palm radius 0.08 H = 0.136 m). A palm:
two 7x7 vertex grids x 0.51..0.60, y +-0.045, z 1.39 / 1.41 (98 vertices,
all on ``mixamorig:LeftHand``, joint at (0.51, 0, 1.40)). Five fingers along
+X from x = 0.605, axes at y = (n-2) x 19 mm (Thumb -38 .. Pinky +38), each
an octagonal prism r 7.5 mm, 80 mm long, 17 rings of 8 vertices; ring 0 is
the blend band (0.5 on the finger's bone 1, 0.5 on the hand), rings 1-16
belong to bone 1/2/3 by thirds, weight 1. Bone k of a finger runs from
x = 0.605 + 0.08 (k-1)/3 along its axis. Every vertex has its own UV
(1/256 apart), smooth-shaded, so the glTF round trip splits nothing and the
UV correspondence is unique. SOURCE = the same mesh, no armature.

FAN = the rig with each finger's bone 1 turned about +Z through its head —
Thumb -20, Index -10, Middle 0, Ring +10, Pinky +20 deg (outwards, nothing
touches) — and baked as rest: the rigger's deed.

[7] THE RESET RESTORES THE FAN. A finger turned by t about its base moves a
    vertex at distance d from the pivot by 2 d sin(t/2); the median vertex of
    a chain sits ~40.3 mm from it (axial 40 mm, radial offset up to 7.5 mm),
    so the rigger moved Thumb/Pinky by 2 x 40.3 x sin 10 = 14.0 mm and
    Index/Ring by 7.0 mm (+-0.5): ``max_displacement_mm`` 14.0. The palm is
    untouched, so the palm fit is the identity. ``before`` spread of the
    long fingers = Index -10 vs Pinky +20 = 30 deg (+-1), ``after`` <= 1 deg;
    ``displacement_left_mm`` <= 0.1; curl passes 5 -> 5 (separate prisms,
    hard weights); stretch <= 1.01 (a rigid turn back). Status ``applied``.
    Re-read from the output GLB: every vertex of rings 1-16 lies within
    0.02 mm of its source position (glTF floats), and the Pinky2 joint is
    back at the straight place x = 0.605 + 0.0267, y = +0.038 — in glTF
    coordinates (0.6317, 1.40, -0.038), 0.2 mm — where the fan had it at
    (0.605 + 0.0267 cos20, 0.038 + 0.0267 sin20) = (0.6301, 0.0471).
[8] ONLY POSITIONS MOVED. ``rig_frames_preserved(fan, output)`` holds with NO
    allowance (every local rest rotation kept), and the production path
    ``refine.hand_restore(copy, source)`` applies through its gates.
[9] AN UNMOVED HAND IS LEFT ALONE. The unbent rig with the same source:
    ``max_displacement_mm`` 0.0 < 2, status ``untouched``, no output file.
[10] A RESET THAT WOULD TEAR IS REFUSED. Source variant: the Middle finger
    20 mm higher (+Z) than the rig's. No turn about its base carries the
    finger there, so the blend ring (half finger, half hand) lands half-way
    — ~10 mm short of its source place — while ring 1 (pure finger) lands on
    it: the 5-mm edge between them becomes |(5, 0, 10)| = 11 mm, ~2.2 x
    the longer of its rigged and mesher lengths > 1.3. Status ``refused``,
    reason ``edge stretch``, no output file — the rigger's hand stays.
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

HAND_FIXTURE = r'''
import bpy, math, sys
from mathutils import Matrix, Vector
out = sys.argv[sys.argv.index("--") + 1]
FINGERS = ("Thumb", "Index", "Middle", "Ring", "Pinky")
FAN = {"Thumb": -20, "Index": -10, "Middle": 0, "Ring": 10, "Pinky": 20}
X0, Z0, R, L, RINGS, PITCH = 0.605, 1.40, 0.0075, 0.08, 16, 0.019

def build(raise_middle=0.0):
    verts, faces, owner = [], [], []
    def add(vs, fs, groups):
        base = len(verts)
        verts.extend(vs); owner.extend(groups)
        faces.extend(tuple(base + i for i in f) for f in fs)
    box = [(x, y, z) for x in (-0.1, 0.1) for y in (-0.1, 0.1) for z in (0.0, 1.70)]
    add(box, [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)],
        [{"mixamorig:Hips": 1.0}] * 8)
    for z in (1.39, 1.41):
        vs = [(0.51 + 0.015 * i, -0.045 + 0.015 * j, z) for i in range(7) for j in range(7)]
        fs = [(i * 7 + j, i * 7 + j + 1, (i + 1) * 7 + j + 1, (i + 1) * 7 + j) for i in range(6) for j in range(6)]
        if z > 1.4:
            fs = [tuple(reversed(f)) for f in fs]
        add(vs, fs, [{"mixamorig:LeftHand": 1.0}] * 49)
    for n, f in enumerate(FINGERS):
        cy = (n - 2) * PITCH
        dz = raise_middle if f == "Middle" else 0.0
        vs, groups = [], []
        for r in range(RINGS + 1):
            for k in range(8):
                vs.append((X0 + L * r / RINGS, cy + R * math.cos(math.pi * k / 4), Z0 + dz + R * math.sin(math.pi * k / 4)))
                if r == 0:
                    groups.append({f"mixamorig:LeftHand{f}1": 0.5, "mixamorig:LeftHand": 0.5})
                else:
                    groups.append({f"mixamorig:LeftHand{f}{min(3, 1 + 3 * (r - 1) // RINGS)}": 1.0})
        fs = [(r * 8 + k, r * 8 + (k + 1) % 8, (r + 1) * 8 + (k + 1) % 8, (r + 1) * 8 + k)
              for r in range(RINGS) for k in range(8)]
        fs += [tuple(range(7, -1, -1)), tuple(RINGS * 8 + k for k in range(8))]
        add(vs, fs, groups)
    me = bpy.data.meshes.new("body")
    me.from_pydata(verts, [], faces)
    me.shade_smooth()
    uv = me.uv_layers.new(name="UVMap")
    for loop in me.loops:
        i = loop.vertex_index
        uv.data[loop.index].uv = ((i % 256 + 0.5) / 256, (i // 256 + 0.5) / 256)
    obj = bpy.data.objects.new("body", me)
    bpy.context.scene.collection.objects.link(obj)
    return obj, owner

def rig(obj, owner):
    arm = bpy.data.armatures.new("rig")
    armo = bpy.data.objects.new("Armature", arm)
    bpy.context.scene.collection.objects.link(armo)
    bpy.context.view_layer.objects.active = armo
    bpy.ops.object.mode_set(mode="EDIT")
    hips = arm.edit_bones.new("mixamorig:Hips")
    hips.head, hips.tail = (0, 0, 0.9), (0, 0, 1.1)
    hand = arm.edit_bones.new("mixamorig:LeftHand")
    hand.head, hand.tail, hand.parent = (0.51, 0, Z0), (X0, 0, Z0), hips
    for n, f in enumerate(FINGERS):
        parent, cy = hand, (n - 2) * PITCH
        for k in (1, 2, 3):
            b = arm.edit_bones.new(f"mixamorig:LeftHand{f}{k}")
            b.head, b.tail = (X0 + L * (k - 1) / 3, cy, Z0), (X0 + L * k / 3, cy, Z0)
            b.parent = parent
            if k > 1:
                b.use_connect = True
            parent = b
    bpy.ops.object.mode_set(mode="OBJECT")
    for i, groups in enumerate(owner):
        for name, w in groups.items():
            vg = obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
            vg.add([i], w, "REPLACE")
    obj.modifiers.new("Armature", "ARMATURE").object = armo
    obj.parent = armo
    return armo

def export(path):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB")

def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)

fresh(); build(); export(out + "/hand_source.glb")
fresh(); build(raise_middle=0.02); export(out + "/hand_source_raised.glb")
fresh(); obj, owner = build(); rig(obj, owner); export(out + "/hand_straight.glb")
fresh(); obj, owner = build(); armo = rig(obj, owner)
bpy.context.view_layer.objects.active = armo
bpy.ops.object.mode_set(mode="POSE")
for f, deg in FAN.items():
    p = armo.pose.bones[f"mixamorig:LeftHand{f}1"]
    m = armo.matrix_world @ p.matrix
    pivot = m.translation.copy()
    rot = Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(deg), 4, Vector((0, 0, 1))) @ Matrix.Translation(-pivot)
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
export(out + "/hand_fan.glb")
print("HAND_FIXTURES_OK")
'''

failures = []


def node_world_positions(path):
    """{node name: world translation} of a GLB, composed from the node TRS (glTF coordinates, Y up)."""
    import numpy as np
    raw = Path(path).read_bytes()
    length = struct.unpack_from("<I", raw, 12)[0]
    doc = json.loads(raw[20:20 + length])

    def local(node):
        x, y, z, w = node.get("rotation", [0, 0, 0, 1])
        rot = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        m = np.eye(4)
        m[:3, :3] = rot * np.array(node.get("scale", [1, 1, 1]))
        m[:3, 3] = node.get("translation", [0, 0, 0])
        return m
    parent = {c: i for i, n in enumerate(doc["nodes"]) for c in n.get("children", [])}
    out = {}
    for i, node in enumerate(doc["nodes"]):
        m, j = local(node), i
        while j in parent:
            j = parent[j]
            m = local(doc["nodes"][j]) @ m
        out[node.get("name", str(i))] = m[:3, 3]
    return out


def hand_checks(executable, root):
    """[7]-[10] — the finger reset."""
    import math
    import shutil
    script = root / "hand_fixture.py"
    script.write_text(HAND_FIXTURE)
    proc = subprocess.run([executable, "-b", "--factory-startup", "--python-exit-code", "1",
                           "--python", str(script), "--", str(root)], capture_output=True, text=True, timeout=240)
    assert "HAND_FIXTURES_OK" in proc.stdout, proc.stdout[-4000:] + proc.stderr[-2000:]
    source = root / "hand_source.glb"

    print("[7] the fanned hand")
    res = runner.run("hand_restore", inputs={"model": root / "hand_fan.glb", "source": source},
                     params={}, out_dir=root / "out_fan")
    assert res["ok"], res
    left = res["data"]["Left"]
    print("   report:", json.dumps({k: left.get(k) for k in ("status", "reason", "displacement_mm",
                                                           "displacement_left_mm", "stretch_max", "self_intersections")}))
    disp = left.get("displacement_mm") or {}
    check("[7] the rigger moved Thumb/Pinky ~14.0 mm, Index/Ring ~7.0, Middle 0",
          all(abs(disp.get(f, -9) - v) <= 0.5 for f, v in
              (("Thumb", 14.0), ("Index", 7.0), ("Middle", 0.0), ("Ring", 7.0), ("Pinky", 14.0))), str(disp))
    check("[7] applied", left.get("status") == "applied", str(left.get("reason")))
    before, after = left.get("before") or {}, left.get("after") or {}
    check("[7] spread 30 deg before", abs(before.get("spread_deg", 0) - 30) <= 1.0, str(before.get("spread_deg")))
    check("[7] spread <= 1 deg after", after.get("spread_deg", 99) <= 1.0, str(after.get("spread_deg")))
    check("[7] displacement left <= 0.1 mm", left.get("displacement_left_mm", 99) <= 0.1,
          str(left.get("displacement_left_mm")))
    check("[7] curl passes 5 -> 5", before.get("curl_pass") == 5 and after.get("curl_pass") == 5,
          f"{before.get('curl_pass')} -> {after.get('curl_pass')}")
    check("[7] stretch <= 1.01", left.get("stretch_max", 99) <= 1.01, str(left.get("stretch_max")))
    out_fan = Path(res["outputs"]["model"])
    import numpy as np
    src = np.array(positions(source))
    fingers = src[src[:, 0] > 0.6075]          # rings 1-16 (ring 0 sits at x = 0.605, the palm ends at 0.60)

    def worst_gap(points):
        p = np.array(points)
        return max(float(np.min(np.linalg.norm(p - q, axis=1))) for q in fingers)
    check("[7] fixture: 5 x 16 x 8 finger vertices", len(fingers) == 640, str(len(fingers)))
    worst = worst_gap(positions(out_fan))
    check("[7] rings 1-16 back at their source places (0.02 mm)", worst <= 2e-5, f"worst {worst * 1000:.4f} mm")
    # Counter-probe, vertex by vertex (each vertex has its own UV — the product's own correspondence): the
    # farthest Pinky vertex sits sqrt(80^2 + 7.5^2) = 80.35 mm from its pivot, so the fan moved it
    # 2 x 80.35 x sin 10 = 27.9 mm.
    fan = np.array(positions(root / "hand_fan.glb"))

    def uv_key(uv):
        return tuple(int(round(c * 1024)) for c in uv)
    by_uv = {uv_key(uv): i for i, uv in enumerate(positions(root / "hand_fan.glb", "TEXCOORD_0", 2))}
    src_uv = positions(source, "TEXCOORD_0", 2)
    pairs = [(i, by_uv.get(uv_key(src_uv[i]))) for i in np.flatnonzero(src[:, 0] > 0.6075)]
    moved = max((float(np.linalg.norm(fan[j] - src[i])) for i, j in pairs if j is not None), default=0.0)
    check("[7] counter-probe: the fan WAS off by 27.9 mm (+-0.2) at the Pinky tip",
          abs(moved - 0.0279) <= 0.0002 and all(j is not None for _, j in pairs),
          f"{moved * 1000:.2f} mm over {sum(j is not None for _, j in pairs)} UV-matched vertices")
    joints = node_world_positions(out_fan)
    pinky2 = next(v for k, v in joints.items() if k.endswith("LeftHandPinky2"))
    want = (0.605 + 0.08 / 3, 1.40, -0.038)
    check("[7] Pinky2 joint back at the straight place", math.dist(pinky2, want) <= 2e-4,
          f"{[round(float(c), 4) for c in pinky2]} vs {want}")
    pinky2_fan = next(v for k, v in node_world_positions(root / "hand_fan.glb").items()
                      if k.endswith("LeftHandPinky2"))
    check("[7] counter-probe: the fan had it at (0.6301, 1.40, -0.0471)",
          math.dist(pinky2_fan, (0.6301, 1.40, -0.0471)) <= 2e-4, str([round(float(c), 4) for c in pinky2_fan]))

    print("[8] only positions moved")
    from app.core.model_validate import rig_frames_preserved
    frames = rig_frames_preserved((root / "hand_fan.glb").read_bytes(), out_fan.read_bytes())
    check("[8] rig frames preserved without an allowance", frames["ok"], "; ".join(frames["errors"])[:160])
    prod = root / "hand_prod.glb"
    shutil.copy2(root / "hand_fan.glb", prod)
    res_prod = refine.hand_restore(prod, source)
    check("[8] refine.hand_restore applies through the gates", bool(res_prod.get("applied")), str(res_prod.get("error")))

    print("[9] the unmoved hand")
    res = runner.run("hand_restore", inputs={"model": root / "hand_straight.glb", "source": source},
                     params={}, out_dir=root / "out_straight_hand")
    assert res["ok"], res
    left = res["data"]["Left"]
    check("[9] untouched, nothing moved", left.get("status") == "untouched"
          and left.get("max_displacement_mm") == 0.0, f"{left.get('status')} {left.get('max_displacement_mm')}")
    check("[9] no output", not res.get("outputs"), str(res.get("outputs")))

    print("[10] the tearing reset")
    res = runner.run("hand_restore", inputs={"model": root / "hand_fan.glb", "source": root / "hand_source_raised.glb"},
                     params={}, out_dir=root / "out_raised")
    assert res["ok"], res
    left = res["data"]["Left"]
    print("   report:", json.dumps({k: left.get(k) for k in ("status", "reason", "stretch_max")}))
    check("[10] refused for the stretch", left.get("status") == "refused" and "edge stretch" in (left.get("reason") or "")
          and left.get("stretch_max", 0) > 1.3, f"{left.get('status')}: {left.get('reason')}")
    check("[10] no output — the rigger's hand stays", not res.get("outputs"), str(res.get("outputs")))


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def positions(path, attribute="POSITION", width=3):
    raw = Path(path).read_bytes()
    length = struct.unpack_from("<I", raw, 12)[0]
    doc = json.loads(raw[20:20 + length])
    start = 28 + length
    result = []
    for mesh in doc["meshes"]:
        for primitive in mesh["primitives"]:
            a = doc["accessors"][primitive["attributes"][attribute]]
            v = doc["bufferViews"][a["bufferView"]]
            offset = start + v.get("byteOffset", 0) + a.get("byteOffset", 0)
            stride = v.get("byteStride", 4 * width)
            result += [struct.unpack_from(f"<{width}f", raw, offset + i * stride) for i in range(a["count"])]
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

        hand_checks(st["executable"], root)

    if failures:
        print(f"\nFAILED: {len(failures)} check(s): {failures}")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
