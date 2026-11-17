"""A195 — renders a character figure GLB from the front, orthographic, on a transparent ground.

Invoked through ``runner.run("figure_front", inputs={"model": glb}, params={"height_px": 1024,
"margin_m": 0.04, "engine": "BLENDER_WORKBENCH"}, out_dir=...)``. The camera comes from
``app.core.front_camera.camera_for`` over the model's evaluated (skinned, rest pose) box, so the server maps
metres to pixels with the same numbers; the result's ``data.camera`` carries them, ``outputs.front`` the PNG.

glTF -> Blender axes: (x, y, z) -> (x, -z, y). The figure faces glTF +z = Blender -y, so the camera stands on the
-y side looking along +y (rotation x = 90°), image right = +x.
Engine BLENDER_WORKBENCH (flat studio light, the textures' colours); CYCLES (CPU, few samples) is the fallback for a
host without a GL context — the caller retries with it when the first run fails.
"""
import math
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bpy                                                    # noqa: E402

_common.app_root_on_path()
from app.core import front_camera                             # noqa: E402


def _box():
    """(xmin, xmax, ymin, ymax) in glTF metres of every mesh's evaluated vertices."""
    dg = bpy.context.evaluated_depsgraph_get()
    xs, ys = [], []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or obj.hide_render:
            continue
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        mw = ev.matrix_world
        for v in me.vertices:
            p = mw @ v.co
            xs.append(p.x)
            ys.append(p.z)
        ev.to_mesh_clear()
    if not xs:
        raise ValueError("the model has no mesh")
    return min(xs), max(xs), min(ys), max(ys)


def _lights(scene):
    world = scene.world or bpy.data.worlds.new("w")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs["Color"].default_value = (0.8, 0.8, 0.8, 1.0)
        bg.inputs["Strength"].default_value = 0.9
    for name, rot, energy in (("key", (math.radians(60), 0, math.radians(-25)), 3.0),
                              ("fill", (math.radians(70), 0, math.radians(30)), 1.2)):
        data = bpy.data.lights.new(name, "SUN")
        data.energy = energy
        obj = bpy.data.objects.new(name, data)
        obj.rotation_euler = rot
        scene.collection.objects.link(obj)


def run(args):
    params = args.get("params") or {}
    bpy.ops.wm.read_factory_settings(use_empty=True)
    _common.import_model(args["inputs"]["model"])
    scene = bpy.context.scene
    cam = front_camera.camera_for(_box(), int(params.get("height_px") or front_camera.HEIGHT_PX),
                                  float(params.get("margin_m", front_camera.MARGIN_M)))
    cdata = bpy.data.cameras.new("front")
    cdata.type = "ORTHO"
    cdata.ortho_scale = cam["ortho_scale"]
    cdata.sensor_fit = "AUTO"
    cdata.clip_start, cdata.clip_end = 0.01, 100.0
    cobj = bpy.data.objects.new("front", cdata)
    cobj.location = (cam["cx"], -20.0, cam["cy"])
    cobj.rotation_euler = (math.radians(90), 0.0, 0.0)
    scene.collection.objects.link(cobj)
    scene.camera = cobj
    r = scene.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = cam["w"], cam["h"], 100
    r.pixel_aspect_x = r.pixel_aspect_y = 1.0
    r.film_transparent = True
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGBA"
    engine = str(params.get("engine") or "BLENDER_WORKBENCH")
    r.engine = engine
    if engine == "CYCLES":
        scene.cycles.device = "CPU"
        scene.cycles.samples = int(params.get("samples") or 12)
        _lights(scene)
    else:
        sh = scene.display.shading
        sh.light = "STUDIO"
        sh.color_type = "TEXTURE"
    try:
        scene.view_settings.view_transform = "Standard"
    except TypeError:
        pass
    out = Path(args["out_dir"]) / "front.png"
    r.filepath = str(out)
    bpy.ops.render.render(write_still=True)
    if not out.is_file():
        raise RuntimeError("render wrote no picture")
    return {"camera": cam, "engine": engine}, {"front": str(out)}


if __name__ == "__main__":
    _common.main(run)
