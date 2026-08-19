"""Renders ONE context plate of a placement spot — the dumb half.

Everything this script does was decided in ``app/core/scene_context.py``: it
receives a job JSON with finished vertex lists, a camera position and
quaternion, a sun direction, and the sidecar to write. It builds, it renders,
it writes — it computes no geometry and it converts no coordinate, because a
second opinion about a frame is exactly how the two renderers used to drift
apart (contract § B5a).

Job (``inputs["job"]``), ALL coordinates already in Blender's Z-up frame::

    render     {width, height, samples, engine, device, png, sidecar}
    camera     {position, quaternion (w,x,y,z), lens_mm, sensor_mm, sensor_fit}
    sun        {direction (towards the light), color, strength, angle_deg}
    world      {color, strength}
    primitives [ {kind: "mesh",   vertices, faces, color, roughness}
               , {kind: "figure", at, height_m, radius_m, color}
               , {kind: "model",  slot, quat_measure, quat_draw, measure,
                                  max_m, anchor, bottom_z} ]
    sidecar    the JSON to write out VERBATIM

Outputs: ``png`` (the render) and ``sidecar`` (the camera record, with the
render settings that were actually used appended under ``render``).
"""
import json
import math
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bpy                                                    # noqa: E402
from mathutils import Quaternion, Vector                      # noqa: E402


def _material(name, color, roughness=0.85):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        r, g, b = (list(color) + [0.5, 0.5, 0.5])[:3]
        bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
        try:
            bsdf.inputs["Roughness"].default_value = float(roughness)
        except KeyError:
            pass
    return mat


def _add_mesh(prim):
    me = bpy.data.meshes.new(prim.get("name") or "mesh")
    me.from_pydata([tuple(v) for v in prim.get("vertices") or []], [],
                   [list(f) for f in prim.get("faces") or []])
    me.update()
    obj = bpy.data.objects.new(prim.get("name") or "mesh", me)
    obj.data.materials.append(_material(f"m_{obj.name}",
                                        prim.get("color") or (0.5, 0.5, 0.5),
                                        prim.get("roughness", 0.85)))
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _add_figure(prim):
    """The scale reference: a capsule of the contract's figure height.

    Built from Blender's own primitives rather than from a vertex list — a
    capsule is the one shape whose tessellation nobody has to agree on.
    """
    height = float(prim.get("height_m") or 1.7)
    radius = float(prim.get("radius_m") or 0.19)
    at = Vector(tuple(prim.get("at") or (0, 0, 0)))
    body = max(height - 2 * radius, 0.01)
    parts = []
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=radius,
                                        depth=body,
                                        location=at + Vector((0, 0, radius + body / 2)))
    parts.append(bpy.context.object)
    for z in (radius, radius + body):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8,
                                             radius=radius,
                                             location=at + Vector((0, 0, z)))
        parts.append(bpy.context.object)
    mat = _material("m_figure", prim.get("color") or (0.55, 0.55, 0.58), 0.6)
    for obj in parts:
        obj.data.materials.clear()
        obj.data.materials.append(mat)
    return parts


def _bounds(objects):
    """World bounding box over the MESH objects only — an empty or an armature
    contributes a zero-size box at its own location and would falsify it."""
    lo = Vector((float("inf"),) * 3)
    hi = Vector((float("-inf"),) * 3)
    for obj in [o for o in objects if o.type == "MESH"]:
        for corner in obj.bound_box:
            p = obj.matrix_world @ Vector(corner)
            for i in range(3):
                lo[i] = min(lo[i], p[i])
                hi[i] = max(hi[i], p[i])
    return lo, hi


def _add_model(prim, path):
    """Imports one stored mesh and runs place() (§ B2) with the given angles.

    The two quaternions are the contract's two rotations: ``quat_measure`` is
    the fix rounded to 90° (plus the yaw for ``yawed_xz``) and only ever
    MEASURES, ``quat_draw`` is the real fix under the yaw and is what stays on
    the object. Rounding the measurement is the fix for a fine angle inflating
    the axis-aligned hull and shrinking the model with it.
    """
    before = set(bpy.context.scene.objects)
    _common.import_model(path)
    fresh = [o for o in bpy.context.scene.objects if o not in before]
    roots = [o for o in fresh if o.parent not in fresh]
    if not roots:
        return [], None

    holder = bpy.data.objects.new(f"place_{prim.get('name') or 'model'}", None)
    bpy.context.scene.collection.objects.link(holder)
    for obj in roots:
        obj.parent = holder
        obj.matrix_parent_inverse.identity()
    holder.rotation_mode = "QUATERNION"

    holder.rotation_quaternion = Quaternion(tuple(prim.get("quat_measure")
                                                  or (1, 0, 0, 0)))
    bpy.context.view_layer.update()
    lo, hi = _bounds(fresh)
    if lo.x == float("inf"):
        return fresh, None                 # imported file carries no geometry
    size = hi - lo
    measure = str(prim.get("measure") or "xyz")
    # Blender's Y is the scene's −z, so the contract's "xz" pair is (x, y) here
    # and its "xyz" is all three; nothing else changes with the frame.
    if measure in ("xz", "yawed_xz"):
        extent = max(size.x, size.y)
    else:
        extent = max(size.x, size.y, size.z)
    scale = float(prim.get("max_m") or 1.0) / (extent or 1.0)

    holder.rotation_quaternion = Quaternion(tuple(prim.get("quat_draw")
                                                  or (1, 0, 0, 0)))
    holder.scale = (scale, scale, scale)
    bpy.context.view_layer.update()
    lo, hi = _bounds(fresh)
    anchor = prim.get("anchor") or [0.0, 0.0]
    holder.location = (float(anchor[0]) - (lo.x + hi.x) / 2.0,
                       float(anchor[1]) - (lo.y + hi.y) / 2.0,
                       float(prim.get("bottom_z") or 0.0) - lo.z)
    bpy.context.view_layer.update()
    lo, hi = _bounds(fresh)
    return fresh, [round(v, 5) for v in (lo.x, lo.y, lo.z, hi.x, hi.y, hi.z)]


def _setup_world(world):
    scene = bpy.context.scene
    bg = bpy.data.worlds.new("ContextWorld")
    bg.use_nodes = True
    node = bg.node_tree.nodes.get("Background")
    if node:
        r, g, b = (list(world.get("color") or (0.4, 0.6, 0.9)) + [0, 0, 0])[:3]
        node.inputs["Color"].default_value = (r, g, b, 1.0)
        node.inputs["Strength"].default_value = float(world.get("strength") or 0.5)
    scene.world = bg


def _setup_sun(sun):
    light = bpy.data.lights.new("Sun", "SUN")
    light.energy = float(sun.get("strength") or 3.0)
    r, g, b = (list(sun.get("color") or (1, 1, 1)) + [1, 1, 1])[:3]
    light.color = (r, g, b)
    light.angle = math.radians(float(sun.get("angle_deg") or 1.5))
    obj = bpy.data.objects.new("Sun", light)
    # A sun lamp shines along its own −Z; the job gives the direction TOWARDS
    # the light, so the lamp is turned to look back down that vector.
    direction = Vector(tuple(sun.get("direction") or (0, 0, 1)))
    obj.rotation_euler = direction.to_track_quat("Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _setup_camera(cam):
    data = bpy.data.cameras.new("ContextCam")
    data.lens = float(cam.get("lens_mm") or 50.0)
    data.sensor_fit = str(cam.get("sensor_fit") or "VERTICAL")
    data.sensor_height = float(cam.get("sensor_mm") or 36.0)
    data.sensor_width = float(cam.get("sensor_mm") or 36.0)
    obj = bpy.data.objects.new("ContextCam", data)
    obj.location = tuple(cam.get("position") or (0, 0, 0))
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Quaternion(tuple(cam.get("quaternion")
                                               or (1, 0, 0, 0)))
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.scene.camera = obj
    return obj


def render(args):
    job_file = args["inputs"].get("job")
    if not job_file:
        raise ValueError("no input 'job'")
    job = json.loads(Path(job_file).read_text(encoding="utf-8"))
    rc = job.get("render") or {}

    _common.reset_scene()
    scene = bpy.context.scene
    scene.render.engine = str(rc.get("engine") or "CYCLES")
    if scene.render.engine == "CYCLES":
        scene.cycles.device = str(rc.get("device") or "CPU")
        scene.cycles.samples = int(rc.get("samples") or 48)
    scene.render.resolution_x = int(rc.get("width") or 1024)
    scene.render.resolution_y = int(rc.get("height") or 1024)
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"

    _setup_world(job.get("world") or {})
    _setup_sun(job.get("sun") or {})
    _setup_camera(job.get("camera") or {})

    built = {"mesh": 0, "figure": 0, "model": 0, "model_missing": 0}
    # Where each imported mesh ENDED UP — the placement is the one thing here
    # that cannot be read off the job file, so it travels back as data (not
    # into the sidecar, which stays what it was handed).
    placed = []
    for prim in job.get("primitives") or []:
        kind = str(prim.get("kind") or "")
        if kind == "mesh":
            _add_mesh(prim)
            built["mesh"] += 1
        elif kind == "figure":
            _add_figure(prim)
            built["figure"] += 1
        elif kind == "model":
            path = args["inputs"].get(str(prim.get("slot") or ""))
            if not path:
                built["model_missing"] += 1
                continue
            _objs, bbox = _add_model(prim, path)
            built["model"] += 1
            placed.append({"name": prim.get("name") or "", "bbox": bbox})

    out_dir = Path(args["out_dir"])
    png = out_dir / str(rc.get("png") or "context.png")
    scene.render.filepath = str(png)
    bpy.ops.render.render(write_still=True)

    # The sidecar is what the job handed over, VERBATIM, plus what the render
    # actually did — the pipeline behind this reads it as the truth about the
    # camera, so nothing in it may be recomputed here.
    sidecar = dict(job.get("sidecar") or {})
    sidecar["render"] = {
        "width": scene.render.resolution_x,
        "height": scene.render.resolution_y,
        "samples": int(getattr(scene.cycles, "samples", 0))
        if scene.render.engine == "CYCLES" else 0,
        "engine": scene.render.engine,
        "blender_version": bpy.app.version_string,
        "png": png.name,
        "objects": built,
    }
    side = out_dir / str(rc.get("sidecar") or "context.json")
    side.write_text(json.dumps(sidecar, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return ({"objects": built, "placed": placed,
             "resolution": [scene.render.resolution_x, scene.render.resolution_y]},
            {"png": str(png), "sidecar": str(side)})


_common.main(render)
