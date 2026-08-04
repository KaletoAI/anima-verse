"""Renders a model headlessly — the eyes of the pipeline.

Some questions are not numeric. Whether a reduced model still looks like
itself, whether a texture ended up upside down, whether a mesh is a chair at
all: those need a picture, and this produces one without a GPU and without
anybody opening Blender.

    size        pixel edge of the square image (default 384)
    samples     Cycles samples (default 24 — noise is irrelevant here)
    angles      list of yaw degrees, one image each (default [35])
    flat        True = unlit base colour only, for comparing SHAPE without
                lighting differences muddying the picture

The camera frames the model from its own bounding box, so a 40 m building and
a 20 cm cup both fill the frame. Measured cost: about half a second per view
at 256 px on eight CPU cores.
"""
import math
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bpy                                                    # noqa: E402
from mathutils import Vector                                  # noqa: E402

# How much larger than the model the camera framing is, so nothing is clipped.
FRAME_MARGIN = 1.35


def _bounds():
    lo = Vector((float("inf"),) * 3)
    hi = Vector((float("-inf"),) * 3)
    found = False
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        for corner in obj.bound_box:
            p = obj.matrix_world @ Vector(corner)
            for i in range(3):
                lo[i] = min(lo[i], p[i])
                hi[i] = max(hi[i], p[i])
            found = True
    return (lo, hi) if found else (Vector((0, 0, 0)), Vector((1, 1, 1)))


def render(args):
    src = args["inputs"].get("model")
    if not src:
        raise ValueError("no input 'model'")
    p = args["params"]
    size = int(p.get("size") or 384)
    samples = int(p.get("samples") or 24)
    angles = [float(a) for a in (p.get("angles") or [35])]
    flat = bool(p.get("flat", False))

    _common.reset_scene()
    _common.import_model(src)

    lo, hi = _bounds()
    centre = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 1e-3)
    distance = radius * 2.6

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.film_transparent = True
    if flat:
        # No lighting at all: every surface shows its own colour, so two
        # renders differ only where the GEOMETRY differs.
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.display.shading.light = "FLAT"
        scene.display.shading.color_type = "TEXTURE"
    else:
        sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
        sun.data.energy = 3.0
        sun.rotation_euler = (math.radians(50), 0, math.radians(30))
        scene.collection.objects.link(sun)

    cam_data = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    outputs = {}
    for angle in angles:
        rad = math.radians(angle)
        cam.location = (centre.x + math.sin(rad) * distance,
                        centre.y - math.cos(rad) * distance,
                        centre.z + radius * 0.55)
        direction = centre - cam.location
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        cam_data.lens = 55
        name = f"{Path(src).stem}_a{int(angle)}.png"
        out = Path(args["out_dir"]) / name
        scene.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        outputs[f"a{int(angle)}"] = str(out)

    return {"size": size, "angles": angles,
            "dims_m": [round(hi[i] - lo[i], 3) for i in range(3)]}, outputs


_common.main(render)
