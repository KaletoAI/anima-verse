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

print("FAILED:" if FAILS else "all ok", FAILS)
sys.exit(1 if FAILS else 0)
