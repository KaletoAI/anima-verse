#!/usr/bin/env python3
"""Smoke: the teeth of the built mouth (Ruling A206) — the pure maths of ``mouth_math.py``, the options and the group,
the renderers' and LOD's handling. Every expected number is derived by hand here.

Usage:
    ./.venv/bin/python scripts/smoke_mouth_teeth.py

No server, no world DB, no Blender (``mouth_teeth.py`` imports bpy: its defaults are read with ``ast``).

[1] teeth_scale(half_width, size): half width / 0.0265 clamped to [0.85, 1.15], times size. 0.0287 -> 1.083019;
    the same with size 1.2 -> 1.299623; 0.020 -> 0.754717 -> 0.85; 0.040 -> 1.509434 -> 1.15.
[2] channel_half_width(d, widest 0.028, radius 0.02, taper 0.03) = widest (1 + (radius / widest - 1) smoothstep(d /
    taper)): d 0 -> 0.028; d 0.015 (smoothstep 0.5) -> 0.028 x (1 - 0.285714 x 0.5) = 0.024; d 0.03 and 0.05 -> 0.02.
[3] arch_curve(d0 0.005, front_w 0.018, front_l 0.011, limit, d_max 0.04, step 0.0005). With limit = 0.017 everywhere:
    x = min(0.018 sqrt((d - 0.005) / 0.011), 0.017); at d = 0.0075 (sample 5): 0.018 sqrt(0.0025 / 0.011) =
    0.018 x 0.476731 = 0.0085812; the parabola reaches 0.017 at d = 0.005 + 0.011 (17/18)^2 = 0.0148117, from there
    on x = 0.017; the arc length at sample 0 is 0. With a NARROWING limit 0.020 - 0.1 d the cap is the narrowest limit
    from d back to d_max, here everywhere 0.020 - 0.004 = 0.016: the arch never gets narrower toward the back, its
    widest x is 0.016 (the raw limit at the front would allow 0.0195).
[4] tooth_spans(widths, total): widths [0.0085, 0.0065, 0.0075, 0.007, 0.0065, 0.01] side by side from 0 ->
    (0, 0.0085), (0.0085, 0.015), (0.015, 0.0225), (0.0225, 0.0295), (0.0295, 0.036), (0.036, 0.046); total 0.04 cuts
    the last to (0.036, 0.04); total 0.03 -> five spans, the fifth (0.0295, 0.03), the molar block left out.
[5] teeth_gap: upper incisal edge U = (0, 0, 0), lower L = (0, 0.002, 0.0005) (2 mm behind, 0.5 mm over it), hinge
    H = (0, 0.08, 0.03), theta 30 degrees, up +Z. L - H = (0, -0.078, -0.0295); turned about +X by 30 degrees:
    y' = -0.078 x 0.8660254 + 0.0295 x 0.5 = -0.0528000, z' = -0.078 x 0.5 - 0.0295 x 0.8660254 = -0.0645477 ->
    L' = (0, 0.0272, -0.0345477); gap = (U - L') . up = 0.0345477. The chord 2 R sin(theta / 2), R = |L - H| =
    sqrt(0.078^2 + 0.0295^2) = 0.0833921: 2 x 0.0833921 x 0.2588190 = 0.0431669 = |L' - L|; its vertical part
    0.0350477, less the 0.5 mm overlap = the gap. At 26 degrees (before A206) the same pair gives 2 R sin 13 =
    0.0375183 chord and less gap: the 30 degrees open the teeth further.
[6] Options: mouth_channel.TEETH_DEFAULTS == the Blender build's mouth_teeth.DEFAULTS for enabled / tongue / shade /
    size (read with ast). validate_teeth: None -> the defaults; {shade 2, size 0.9} -> complete with them; shade 3,
    size 1.3, enabled "yes", an unknown key -> ValueError. The group: a profile without options has no params.teeth;
    {mouth_teeth {shade 2}} -> params.teeth {shade 2} (only what differs) and another extension fingerprint (the step
    becomes due); {mouth_teeth {enabled True}} (= the default) -> no params.teeth, the same fingerprint.
[7] OP_BUILDS["mouth_part"] is 5 now; at the commit before A206 (7458a196e) it was 4 and the Blender op's jaw opened
    26 degrees (DEFAULTS jaw.open_deg 26.), now 30.
[8] The opening pass leaves the teeth alone: channelOpening.ts filters a mesh by `isRigidTeeth` in
    `bindChannelOpening`'s traverse; at 7458a196e the filter had no such test (every skinned body mesh was bound).
    The numbers of the pass itself: scripts/smoke_mouth_open.mjs [5].
[10] Every re-export of a rigged body keeps COLOR_0 on the teeth only (_common.keep_mouth_teeth_colours, called after
    the export in mouth_part, extension_bones, hand_restore, limb_weights and posture_match). Synthetic GLB: mesh 0 =
    primitives skin (POSITION acc 0, COLOR_0 acc 1), mouth_teeth (POSITION 2, COLOR_0 3), mouth_tongue (POSITION 4,
    COLOR_0 5); mesh 1 = a garment with its own COLOR_0 (POSITION 6, COLOR_0 7); 8 accessors of 3 vertices on 8 views
    (36 bytes each for VEC3, 48 for VEC4 colours). After: skin and tongue without COLOR_0, teeth and garment keep theirs;
    2 accessors and 2 views gone -> 6 accessors, 6 views, binary 4 x 40 (36 padded to 8) + 2 x 48 = 256 bytes; the kept accessors
    read back the same bytes (teeth colour 0.75, garment 0.2). A file without teeth: byte-identical.
[9] lod.py removes the teeth and tongue faces (``_drop_mouth_teeth``, materials mouth_teeth / mouth_tongue) BEFORE it
    adds the DECIMATE modifier, in the same loop over the meshes.
"""
import ast
import math
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app/blender/scripts"))
import mouth_math as mm  # noqa: E402

PRE_FIX = "7458a196e"
failed = 0


def check(label, ok, got=""):
    global failed
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  (got {got})"))
    failed += 0 if ok else 1


def near(a, b, tol=1e-6):
    return abs(float(a) - float(b)) <= tol


def show(rev_path):
    return subprocess.run(["git", "-C", str(ROOT), "show", rev_path], capture_output=True, text=True, check=True).stdout


print("[1] teeth_scale")
check("0.0287 -> 1.083019", near(mm.teeth_scale(.0287), 1.083019))
check("size 1.2 -> 1.299623", near(mm.teeth_scale(.0287, 1.2), 1.299623))
check("clamped 0.85 / 1.15", near(mm.teeth_scale(.020), .85) and near(mm.teeth_scale(.040), 1.15))

print("[2] channel_half_width")
w = mm.channel_half_width(np.array([0., .015, .03, .05]), .028, .02, .03)
check("0.028 / 0.024 / 0.02 / 0.02", np.allclose(w, [.028, .024, .02, .02], atol=1e-9), w)

print("[3] arch_curve")
x, d, s = mm.arch_curve(.005, .018, .011, lambda dd: np.full(len(dd), .017), .04)
check("d at sample 5 is 0.0075", near(d[5], .0075, 1e-12), d[5])
check("x there 0.0085812", near(x[5], .0085812, 1e-7), x[5])
reach = .005 + .011 * (17 / 18) ** 2
check("x = 0.017 from d 0.0148117 on", near(reach, .0148117, 1e-7) and np.all(np.abs(x[d >= reach + 1e-9] - .017) < 1e-12)
      and np.all(x[d < reach - 1e-6] < .017), reach)
check("arc length 0 at the midline, growing", s[0] == 0 and np.all(np.diff(s) > 0))
x2, d2, _s2 = mm.arch_curve(.005, .018, .011, lambda dd: .020 - .1 * dd, .04)
check("narrowing limit: never wider than 0.016", near(x2.max(), .016, 1e-12), x2.max())
check("... and not narrowing toward the back", np.all(np.diff(x2) >= -1e-15))

print("[4] tooth_spans")
widths = [.0085, .0065, .0075, .007, .0065, .01]
sp = mm.tooth_spans(widths, .04)
want = [(0, .0085), (.0085, .015), (.015, .0225), (.0225, .0295), (.0295, .036), (.036, .04)]
check("six spans, the last cut to 0.04", len(sp) == 6 and all(near(a, c, 1e-12) and near(b, e, 1e-12)
                                                            for (a, b), (c, e) in zip(sp, want)), sp)
sp = mm.tooth_spans(widths, .03)
check("total 0.03: five, the fifth (0.0295, 0.03)", len(sp) == 5 and near(sp[4][0], .0295, 1e-12)
      and near(sp[4][1], .03, 1e-12), sp)

print("[5] teeth_gap")
U, L, H = np.zeros(3), np.array([0, .002, .0005]), np.array([0, .08, .03])
gap = mm.teeth_gap(U, L, H, math.radians(30), np.array([0, 0, 1.]))
check("gap 0.0345477", near(gap, .0345477, 1e-7), gap)
R = float(np.linalg.norm(L - H))
chord = 2 * R * math.sin(math.radians(15))
turned = mm.turned(L[None], H, math.radians(30))[0]
check("R 0.0833921, chord 0.0431669 = |L' - L|", near(R, .0833921, 1e-7) and near(chord, .0431669, 1e-7)
      and near(np.linalg.norm(turned - L), chord, 1e-9), (R, chord))
check("vertical part of the chord less the overlap = the gap", near((L - turned)[2] - .0005, gap, 1e-12))
check("26 degrees: chord 0.0375183, less gap", near(2 * R * math.sin(math.radians(13)), .0375183, 1e-7)
      and mm.teeth_gap(U, L, H, math.radians(26), np.array([0, 0, 1.])) < gap)

print("[6] options and the group")
from app.core import extension_rig, mouth_channel  # noqa: E402
tree = ast.parse((ROOT / "app/blender/scripts/mouth_teeth.py").read_text())
blender_defaults = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                        and any(getattr(t, "id", "") == "DEFAULTS" for t in node.targets))
check("defaults agree with the Blender build", {k: blender_defaults[k] for k in mouth_channel.TEETH_DEFAULTS}
      == mouth_channel.TEETH_DEFAULTS, blender_defaults)
check("None -> defaults", mouth_channel.validate_teeth(None) == mouth_channel.TEETH_DEFAULTS)
check("partial -> complete", mouth_channel.validate_teeth({"shade": 2, "size": 0.9})
      == {"enabled": True, "tongue": True, "shade": 2, "size": 0.9})
for bad in ({"shade": 3}, {"size": 1.3}, {"enabled": "yes"}, {"colour": 1}):
    try:
        mouth_channel.validate_teeth(bad)
        check(f"refused {bad}", False)
    except ValueError:
        check(f"refused {bad}", True)
with patch("app.core.model_refs.is_humanoid", return_value=True):
    plain = mouth_channel.group({})
    shaded = mouth_channel.group({"model3d_opts": {"mouth_teeth": {"shade": 2}}})
    default = mouth_channel.group({"model3d_opts": {"mouth_teeth": {"enabled": True}}})
check("no options: no params.teeth", "teeth" not in plain["params"], plain["params"])
check("shade 2: params.teeth {shade 2}", shaded["params"].get("teeth") == {"shade": 2}, shaded["params"])
check("the default stored: no params.teeth", "teeth" not in default["params"], default["params"])
fp = extension_rig.extension_rig_fingerprint
check("an option changes the fingerprint, the default does not", fp([shaded]) != fp([plain]) and fp([default]) == fp([plain]))

print("[7] the build number and the jaw angle")
check("mouth_part build 5", extension_rig.OP_BUILDS["mouth_part"] == 5, extension_rig.OP_BUILDS["mouth_part"])
check(f"{PRE_FIX}: build 4", '"mouth_part": 4}' in show(f"{PRE_FIX}:app/core/extension_rig.py"))
check(f"{PRE_FIX}: jaw 26 degrees, now 30", "'open_deg': 26.," in show(f"{PRE_FIX}:app/blender/scripts/mouth_part.py")
      and "'open_deg': 30.," in (ROOT / "app/blender/scripts/mouth_part.py").read_text())

print("[8] the opening pass leaves the teeth")


def bind_filter(text):
    start = text.index("export function bindChannelOpening")
    return next(line for line in text[start:].splitlines() if "meshes.push(mesh)" in line
                or ("isSkinnedMesh" in line and "inGarment" in line))


now = (ROOT / "packages/scene-render/src/channelOpening.ts").read_text()
check("now: the traverse skips isRigidTeeth", "!isRigidTeeth(" in bind_filter(now), bind_filter(now))
before = show(f"{PRE_FIX}:packages/scene-render/src/channelOpening.ts")
check(f"{PRE_FIX}: no such test (teeth would be bound)", "isRigidTeeth" not in before and "mouth_teeth" not in before,
      bind_filter(before))

print("[9] LOD drops the teeth before the collapse")
lod = (ROOT / "app/blender/scripts/lod.py").read_text()
loop = lod[lod.index("for obj in _mesh_objects():\n            if obj.get(\"lod_preserve\")"):]
check("_drop_mouth_teeth before DECIMATE", 0 <= loop.index("_drop_mouth_teeth(obj)") < loop.index('type="DECIMATE"'))
check("both materials named", 'MOUTH_TEETH_MATERIALS = ("mouth_teeth", "mouth_tongue")' in lod)

print("[10] re-exports keep vertex colours on the teeth only")
import json as _json  # noqa: E402
import struct  # noqa: E402
import tempfile  # noqa: E402
import _common  # noqa: E402


def synthetic(with_teeth=True):
    names = ["skin", "mouth_teeth" if with_teeth else "lips", "mouth_tongue", "cloth"]
    chunks, views, accs = [], [], []
    def add(values, kind):
        data = struct.pack(f"<{len(values)}f", *values)
        views.append({"buffer": 0, "byteOffset": sum(len(c) for c in chunks), "byteLength": len(data)})
        chunks.append(data)
        accs.append({"bufferView": len(views) - 1, "componentType": 5126, "count": 3, "type": kind})
        return len(accs) - 1
    prims = []
    for k, colour in enumerate((0.9, 0.75, 0.5, 0.2)):
        pos = add([float(k)] * 9, "VEC3")
        col = add([colour] * 12, "VEC4")
        prims.append({"attributes": {"POSITION": pos, "COLOR_0": col}, "material": k})
    binary = b"".join(chunks)
    doc = {"asset": {"version": "2.0"}, "materials": [{"name": n} for n in names],
           "meshes": [{"primitives": prims[:3]}, {"primitives": prims[3:]}], "accessors": accs, "bufferViews": views,
           "buffers": [{"byteLength": len(binary)}]}
    raw = _json.dumps(doc).encode()
    raw += b" " * (-len(raw) % 4)
    blob = struct.pack("<4sII", b"glTF", 2, 20 + len(raw) + 8 + len(binary)) + struct.pack("<II", len(raw), 0x4E4F534A) \
        + raw + struct.pack("<II", len(binary), 0x004E4942) + binary
    path = Path(tempfile.mkdtemp()) / "m.glb"
    path.write_bytes(blob)
    return path


def read(path):
    blob = path.read_bytes()
    size = struct.unpack_from("<I", blob, 12)[0]
    doc = _json.loads(blob[20:20 + size])
    rest = blob[20 + size:]
    return doc, rest[8:8 + struct.unpack_from("<I", rest, 0)[0]]


def first_float(doc, binary, acc):
    view = doc["bufferViews"][doc["accessors"][acc]["bufferView"]]
    return struct.unpack_from("<f", binary, view.get("byteOffset", 0))[0]


path = synthetic()
_common.keep_mouth_teeth_colours(path)
doc, binary = read(path)
p0, p1 = doc["meshes"][0]["primitives"], doc["meshes"][1]["primitives"]
check("skin and tongue lose COLOR_0, teeth and garment keep it", "COLOR_0" not in p0[0]["attributes"]
      and "COLOR_0" in p0[1]["attributes"] and "COLOR_0" not in p0[2]["attributes"] and "COLOR_0" in p1[0]["attributes"])
check("6 accessors, 6 views, 256 bytes", len(doc["accessors"]) == 6 and len(doc["bufferViews"]) == 6
      and len(binary) == 256, (len(doc["accessors"]), len(doc["bufferViews"]), len(binary)))
check("kept colours read back 0.75 / 0.2", near(first_float(doc, binary, p0[1]["attributes"]["COLOR_0"]), .75)
      and near(first_float(doc, binary, p1[0]["attributes"]["COLOR_0"]), .2))
check("positions read back 0 / 1 / 2 / 3", [round(first_float(doc, binary, p["attributes"]["POSITION"])) for p in p0 + p1]
      == [0, 1, 2, 3])
plain = synthetic(False)
before = plain.read_bytes()
_common.keep_mouth_teeth_colours(plain)
check("without teeth: byte-identical", plain.read_bytes() == before)
for script in ("mouth_part", "extension_bones", "hand_restore", "limb_weights", "posture_match"):
    text = (ROOT / f"app/blender/scripts/{script}.py").read_text()
    check(f"{script} calls it after its export", "_common.keep_mouth_teeth_colours(" in text
          and text.index("_common.keep_mouth_teeth_colours(") > text.index("export_scene.gltf("))
check("material name agrees", _common.MOUTH_TEETH_MATERIAL == next(
    ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
    and any(getattr(t, "id", "") == "TEETH_MATERIAL" for t in n.targets)))

print("ALL OK" if not failed else f"FAILED ({failed})")
sys.exit(1 if failed else 0)
