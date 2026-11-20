"""A195 — hand-derived checks of the dressed-front camera (``app/core/front_camera.py``), its use in the overlay's
registration (``garment_preview.Registration`` with ``frame["camera"]``) and, when Blender is installed, of the real
render (``app/blender/scripts/figure_front.py``).

Usage: ./.venv/bin/python scripts/smoke_template_front_a195.py   (no server, no world; files only in a temp dir)

Numbers derived by hand from the camera rule (module docstring of ``front_camera``):

A  camera_for((-0.9, 0.9, 0.0, 1.8), 1000, 0.05):
   framed height 1.8 + 2 x 0.05 = 1.9 m -> ppm = 1000 / 1.9 = 526.3158; framed width 1.9 m -> w = ceil(1000) = 1000;
   centre (0, 0.9); ortho_scale = max(1000, 1000) / 526.3158 = 1.9.
   to_px(0, 1.8) = (500, 500 - 0.9 x 526.3158) = (500, 26.3158)  (the margin above the head: 0.05 x ppm)
   to_px(0.9, 0) = (500 + 473.6842, 973.6842)
B  camera_for((-0.2, 0.6, 0.1, 1.1), 500, 0): ppm = 500 / 1.0 = 500; w = ceil(0.8 x 500) = 400; centre (0.2, 0.6);
   ortho_scale = max(400, 500) / 500 = 1.0. to_px(0.6, 1.1) = (200 + 0.4 x 500, 250 - 0.5 x 500) = (400, 0) — the
   top right corner; to_m(0, 500) = (0.2 - 200 / 500, 0.6 - 250 / 500) = (-0.2, 0.1) — the bottom left corner.
C  Registration on camera B with floor 0.1, height 1.0: px(x, y) == to_px(cam, x, y) for any point, e.g.
   px(0.3, 0.5) = (200 + 0.1 x 500, 250 + 0.1 x 500) = (250, 300); metres(250, 300) = (0.3, 0.5).
   The arm in the exact picture is the model's: joints leftarm (0.2, 0.9) -> lefthand (0.6, 0.6): direction
   (0.4, -0.3) / 0.5 = (0.8, -0.6), root (0.2, shoulder_y 0.9).
D  (Blender) a box x in [-0.2, 0.2], glTF y in [0, 1] (Blender z), rendered with height_px 600, margin 0.1:
   framed 1.2 m high -> ppm 500; framed 0.6 m wide -> w 300; centre (0, 0.5). The box's columns:
   to_px(-0.2) = 150 - 100 = 50 .. to_px(0.2) = 250 (exclusive) -> pixels 50 .. 249; rows: y 1 -> 300 - 250 = 50,
   y 0 -> 550 (exclusive) -> 50 .. 549. Checked within 1 px (antialiased edge).
E  (Blender) THE LIGHT (finding 2026-11-20): the picture is rendered under a uniform white world of strength 1 and
   nothing else, view transform Standard, so a front face shows its albedo at ~1x — and the material's node tree,
   vertex colours included, is honoured. Two boxes x in [-0.3, -0.1] and [0.1, 0.3], glTF y in [0, 1], height_px
   600, margin 0.1: framed 1.2 m -> ppm 500; width 0.8 m -> w 400, centre (0, 0.5); to_px(x) = 200 + 500 x, so the
   boxes cover columns 50 .. 149 and 250 .. 349, rows 50 .. 549; the medians are read inside (75..124 / 275..324,
   rows 200..399), away from the edges.
   Box 1: base colour linear 0.21586 (= sRGB 128), roughness 1, metallic 0. Box 2: base colour white x a COLOR_0
   vertex colour of linear (0.5, 0.15, 0.05) — the path the hair's profile colour takes.
   Expected per channel, a = linear albedo: the diffuse lobe of a face open to the whole world reflects radiance 1 x
   a, less what the dielectric specular layer takes (Fresnel F0 = 0.04 -> at most 4 %); that layer gives back at
   most F0 = 0.04 of the white world (roughness 1, normal incidence). So linear out in [0.96 a, a + 0.04]:
     a 0.21586 -> sRGB [125.6, 138.4]   (128 = exactly 1x)
     a 0.5     -> sRGB [184.1, 194.1]
     a 0.15    -> sRGB [106.0, 120.6]
     a 0.05    -> sRGB [ 61.9,  84.6]
   (measured 2026-11-20, EEVEE: grey 130, vertex colour (188, 111, 70) — about a + 0.005.)
   checked with 2 code values of slack for the 8-bit PNG and the render noise. The engines are tried in the order
   of ``garment_preview_front.ENGINES`` (EEVEE, then Cycles), as the server does. Workbench, the engine before,
   gave ~0.36x on box 1 and dropped the vertex colour entirely (box 2 white) — measured 2026-11-20 on Glut's figure,
   see the commit; it is no longer runnable through this script.
F  The cache key of the pictures carries ``RENDER_VERSION`` >= 2, so a dark Workbench picture (version 1) is never
   served for the same inputs: ``source()`` hashes ``[RENDER_VERSION, ...]`` (checked on the source text).
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="a195-smoke-")
os.environ.setdefault("STORAGE_DIR", _tmp)
os.environ.setdefault("INSTANCE_DIR", _tmp)
from app.core import paths  # noqa: E402

paths.init(_tmp)
import numpy as np  # noqa: E402

from app.core import front_camera as fc  # noqa: E402
from app.core import garment_preview as gp  # noqa: E402

FAILS = []


def check(name, got, want, tol=1e-3):
    if isinstance(want, (list, tuple)):
        ok = len(got) == len(want) and all(abs(a - b) <= tol for a, b in zip(got, want))
    else:
        ok = abs(got - want) <= tol
    print(("ok  " if ok else "FAIL"), name, got, "want", want)
    if not ok:
        FAILS.append(name)


# A
a = fc.camera_for((-0.9, 0.9, 0.0, 1.8), 1000, 0.05)
check("A ppm", a["ppm"], 526.3158)
check("A w,h", (a["w"], a["h"]), (1000, 1000), 0)
check("A centre", (a["cx"], a["cy"]), (0.0, 0.9))
check("A ortho", a["ortho_scale"], 1.9)
check("A head top", fc.to_px(a, 0, 1.8), (500, 26.3158))
check("A foot right", fc.to_px(a, 0.9, 0), (973.6842, 973.6842))
# B
b = fc.camera_for((-0.2, 0.6, 0.1, 1.1), 500, 0)
check("B ppm", b["ppm"], 500)
check("B w,h", (b["w"], b["h"]), (400, 500), 0)
check("B centre", (b["cx"], b["cy"]), (0.2, 0.6))
check("B ortho", b["ortho_scale"], 1.0)
check("B top right", fc.to_px(b, 0.6, 1.1), (400, 0))
check("B to_m bottom left", fc.to_m(b, 0, 500), (-0.2, 0.1))
# C
mask = np.zeros((500, 400), dtype=bool)
mask[10:490, 150:250] = True
frame = dict(gp.frame_of_mask(mask), camera=b)
meas = {"floor_y": 0.1, "height": 1.0, "hip_y": 0.5, "band_y": 0.75, "shoulder_y": 0.9,
        "joints": {"hips": [0.2, 0.55, 0], "neck": [0.2, 0.95, 0], "leftarm": [0.2, 0.9, 0],
                   "lefthand": [0.6, 0.6, 0]}}
reg = gp.Registration(frame, meas)
check("C exact", 1.0 if reg.exact else 0.0, 1.0, 0)
check("C px", reg.px(0.3, 0.5), (250, 300), 0.051)
check("C px == to_px", reg.px(-0.05, 0.93), fc.to_px(b, -0.05, 0.93), 0.051)
check("C metres", reg.metres(250, 300), (0.3, 0.5))
axis = reg.joint_arm_axis(1)
check("C arm root", axis[0], (0.2, 0.9))
check("C arm dir", axis[1], (0.8, -0.6))
check("C no right hand -> None", 1.0 if reg.joint_arm_axis(-1) is None else 0.0, 1.0, 0)

# D — the real render, when Blender is there
from app.blender import runner  # noqa: E402

exe = runner.find_executable()
if not exe:
    print("skip D: no Blender")
else:
    work = Path(_tmp) / "d"
    work.mkdir()
    box = work / "box.glb"
    make = work / "make.py"
    make.write_text(
        "import bpy\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        "bpy.ops.mesh.primitive_cube_add(size=1.0)\n"
        "o = bpy.context.active_object\n"
        "o.scale = (0.4, 0.2, 1.0)\n"
        "o.location = (0.0, 0.0, 0.5)\n"
        "bpy.ops.object.transform_apply(location=True, scale=True)\n"
        f"bpy.ops.export_scene.gltf(filepath={str(box)!r}, export_format='GLB')\n", encoding="utf-8")
    subprocess.run([exe, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(make)],
                   check=True, capture_output=True, timeout=120)
    res = runner.run("figure_front", inputs={"model": box}, params={"height_px": 600, "margin_m": 0.1},
                     out_dir=work / "out", timeout_s=120)
    if not res.get("ok"):
        res = runner.run("figure_front", inputs={"model": box},
                         params={"height_px": 600, "margin_m": 0.1, "engine": "CYCLES"}, out_dir=work / "out2",
                         timeout_s=300)
    if not res.get("ok"):
        FAILS.append("D render: " + str(res.get("error")))
        print("FAIL D render", res.get("error"))
    else:
        cam = res["data"]["camera"]
        check("D camera", (cam["ppm"], cam["w"], cam["h"], cam["cx"], cam["cy"]), (500, 300, 600, 0, 0.5), 1e-4)
        from PIL import Image
        with Image.open(res["outputs"]["front"]) as im:
            m = gp.silhouette(im)
        rows = np.where(m.any(axis=1))[0]
        cols = np.where(m.any(axis=0))[0]
        check("D box columns", (cols[0], cols[-1]), (50, 249), 1)
        check("D box rows", (rows[0], rows[-1]), (50, 549), 1)
        print(json.dumps(res["data"]))

# E — the light: albedo ~1x and the vertex colour, when Blender is there
if exe:
    from app.core import garment_preview_front as gpf  # noqa: E402
    work = Path(_tmp) / "e"
    work.mkdir()
    boxes = work / "boxes.glb"
    make = work / "make.py"
    make.write_text(
        "import bpy\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        "def box(x, mat):\n"
        "    bpy.ops.mesh.primitive_cube_add(size=1.0)\n"
        "    o = bpy.context.active_object\n"
        "    o.scale = (0.2, 0.2, 1.0)\n"
        "    o.location = (x, 0.0, 0.5)\n"
        "    bpy.ops.object.transform_apply(location=True, scale=True)\n"
        "    o.data.materials.append(mat)\n"
        "    return o\n"
        "def principled(name):\n"
        "    m = bpy.data.materials.new(name)\n"
        "    m.use_nodes = True\n"
        "    p = m.node_tree.nodes['Principled BSDF']\n"
        "    p.inputs['Roughness'].default_value = 1.0\n"
        "    p.inputs['Metallic'].default_value = 0.0\n"
        "    return m, p\n"
        "grey, p = principled('grey')\n"
        "p.inputs['Base Color'].default_value = (0.21586, 0.21586, 0.21586, 1.0)\n"
        "box(-0.2, grey)\n"
        "vc, p = principled('vc')\n"
        "attr = vc.node_tree.nodes.new('ShaderNodeVertexColor')\n"
        "attr.layer_name = 'Color'\n"
        "vc.node_tree.links.new(attr.outputs['Color'], p.inputs['Base Color'])\n"
        "o = box(0.2, vc)\n"
        "ca = o.data.color_attributes.new('Color', 'FLOAT_COLOR', 'CORNER')\n"
        "for d in ca.data:\n"
        "    d.color = (0.5, 0.15, 0.05, 1.0)\n"
        f"bpy.ops.export_scene.gltf(filepath={str(boxes)!r}, export_format='GLB')\n", encoding="utf-8")
    subprocess.run([exe, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(make)],
                   check=True, capture_output=True, timeout=120)
    res = {}
    for engine in gpf.ENGINES:
        res = runner.run("figure_front", inputs={"model": boxes},
                         params={"height_px": 600, "margin_m": 0.1, "engine": engine}, out_dir=work / engine,
                         timeout_s=300)
        if res.get("ok"):
            break
    if not res.get("ok"):
        FAILS.append("E render: " + str(res.get("error")))
        print("FAIL E render", res.get("error"))
    else:
        cam = res["data"]["camera"]
        print("E engine", res["data"].get("engine"), "render_s", res["data"].get("render_s"))
        check("E camera", (cam["ppm"], cam["w"], cam["h"], cam["cx"], cam["cy"]), (500, 400, 600, 0, 0.5), 1e-4)
        from PIL import Image
        with Image.open(res["outputs"]["front"]) as im:
            px = np.asarray(im.convert("RGBA")).astype(float)
        grey_med = np.median(px[200:400, 75:125, :3].reshape(-1, 3), axis=0)
        vc_med = np.median(px[200:400, 275:325, :3].reshape(-1, 3), axis=0)
        for name, got, lo, hi in (("E grey", grey_med, (125.6,) * 3, (138.4,) * 3),
                                  ("E vertex colour", vc_med, (184.1, 106.0, 61.9), (194.1, 120.6, 84.6))):
            ok = all(lo[i] - 2 <= got[i] <= hi[i] + 2 for i in range(3))
            print(("ok  " if ok else "FAIL"), name, got.tolist(), "want", lo, "..", hi)
            if not ok:
                FAILS.append(name)

# F — the cache key carries the render version
src_text = (Path(__file__).resolve().parent.parent / "app/core/garment_preview_front.py").read_text(encoding="utf-8")
from app.core import garment_preview_front as gpf  # noqa: E402
check("F RENDER_VERSION >= 2", 1.0 if gpf.RENDER_VERSION >= 2 else 0.0, 1.0, 0)
check("F key hashes the version", 1.0 if "json.dumps([RENDER_VERSION," in src_text else 0.0, 1.0, 0)
check("F engines EEVEE then Cycles", 1.0 if tuple(gpf.ENGINES) == ("BLENDER_EEVEE", "CYCLES") else 0.0, 1.0, 0)

print("FAILED:" if FAILS else "all ok", FAILS)
sys.exit(1 if FAILS else 0)
