"""A195 — renders a character figure GLB from the front, orthographic, on a transparent ground.

Invoked through ``runner.run("figure_front", inputs={"model": glb}, params={"height_px": 1024,
"margin_m": 0.04, "engine": "BLENDER_EEVEE"}, out_dir=...)``. The camera comes from
``app.core.front_camera.camera_for`` over the model's evaluated (skinned, rest pose) box, so the server maps
metres to pixels with the same numbers; the result's ``data.camera`` carries them, ``outputs.front`` the PNG.

glTF -> Blender axes: (x, y, z) -> (x, -z, y). The figure faces glTF +z = Blender -y, so the camera stands on the
-y side looking along +y (rotation x = 90°), image right = +x.
THE LIGHT: a uniform white world of strength 1 and nothing else — no lamps, view transform Standard. A diffuse
surface open to that world reflects radiance 1 x its albedo, so a texel comes out at its own sRGB value (~1x albedo;
concave or self-shadowed parts a little darker), and the material's node tree is evaluated: vertex colours (the
hair's COLOR_0 = the profile hair colour, the teeth) reach the picture through the importer's Mix node.
Engine BLENDER_EEVEE (GPU, ``samples`` TAA samples, default 16); CYCLES (CPU, ``samples``, default 12) is the fallback
for a host without a GL context — the caller retries with it when the first run fails. Both see the same world.
Workbench is gone (finding 2026-11-20): with ``color_type TEXTURE`` it ignores the node tree, so the vertex colours
were lost, and its studio light gave ~0.36x albedo.
"""
import math
import sys
import time
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


def _uniform_world(scene):
    """A white world of strength 1 as the ONLY light (no lamps are created; the factory scene has none)."""
    world = bpy.data.worlds.new("uniform")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is None:
        raise RuntimeError("the world has no Background node")
    bg.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    bg.inputs["Strength"].default_value = 1.0


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
    engine = str(params.get("engine") or "BLENDER_EEVEE")
    if engine not in ("BLENDER_EEVEE", "CYCLES"):
        raise ValueError(f"unsupported engine {engine!r}")
    r.engine = engine
    if engine == "CYCLES":
        scene.cycles.device = "CPU"
        scene.cycles.samples = int(params.get("samples") or 12)
    else:
        scene.eevee.taa_render_samples = int(params.get("samples") or 16)
    _uniform_world(scene)
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    out = Path(args["out_dir"]) / "front.png"
    r.filepath = str(out)
    t0 = time.monotonic()
    bpy.ops.render.render(write_still=True)
    render_s = round(time.monotonic() - t0, 2)
    if not out.is_file():
        raise RuntimeError("render wrote no picture")
    return {"camera": cam, "engine": engine, "render_s": render_s}, {"front": str(out)}


if __name__ == "__main__":
    _common.main(run)
