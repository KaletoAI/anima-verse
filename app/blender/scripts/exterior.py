"""Renders ONE building exterior from a finished vertex list — the dumb half.

Everything this script does was decided in ``app/core/exterior_render.py``: it
receives a job JSON with the volume's vertices (already in Blender's Z-up
frame), its faces, one material index per face, the materials, a camera and a
render size. It builds the mesh, paints it, points a camera at it and writes
ONE PNG — it computes no geometry, so every number in the picture can be traced
back to a function on the server side and the smoke can check the same numbers
WITHOUT Blender.

Job (``inputs["job"]``)::

    mesh       {name, vertices [[x, y, z], ...], faces [[i, ...], ...],
                face_material [int, ...]}
    materials  [ {name, tone, color [linear r, g, b], roughness} ]
    camera     {elevation_deg, yaw_deg, lens_mm, sensor_mm, margin}
    render     {size, samples, background [r, g, b], png}

THE PICTURE IS MESH INPUT, and that dictates every lighting choice here — the
rules the ``building`` use case and ``app/core/model_refs.py`` state for a
render an image-to-3D pass has to eat:

* ISOLATED. No ground plane, no horizon, no sky. The background is ONE flat
  neutral colour, so the mesher's silhouette segmentation has nothing to
  mistake for the building.
* SHADOWLESS. Every lamp has its shadows switched off, so nothing lands on the
  ground (there is none) and no eave shades the wall beneath it — a cast
  shadow would bake into the generated texture as painted-on dirt.
* But NOT FLAT. Pure ambient light would render the body as a silhouette and
  the mesher would get no cue about which surface faces where. So two weak
  suns from opposite sides give the faces different values without ever
  casting anything.
* A LONG LENS from far away, so the verticals stay vertical. A wide-angle
  building converges towards the top, and the mesher rebuilds that convergence
  as a genuinely tapered building.

Output: ``png`` — one three-quarter view, square, on the neutral background.
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
from mathutils import Vector                                  # noqa: E402

#: The two suns, as (energy, elevation°, azimuth° relative to the camera yaw).
#: The key sits above and slightly left of the camera, the fill low on the
#: opposite side — enough to keep the shaded faces readable instead of black.
LAMPS = ((2.6, 55.0, -35.0), (1.1, 20.0, 145.0))
#: Ambient level of the neutral background, as a factor on its own colour. The
#: background doubles as the fill light; at 1.0 it would wash the body out.
WORLD_STRENGTH = 0.55


def _material(spec, index):
    mat = bpy.data.materials.new(str(spec.get("name") or f"m{index}"))
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        r, g, b = (list(spec.get("color") or []) + [0.5, 0.5, 0.5])[:3]
        bsdf.inputs["Base Color"].default_value = (float(r), float(g),
                                                   float(b), 1.0)
        try:
            bsdf.inputs["Roughness"].default_value = float(
                spec.get("roughness", 0.9))
        except KeyError:
            pass
        # A wall is not a mirror, and a specular highlight on a volume model
        # bakes into the texture as a painted-on light spot.
        try:
            bsdf.inputs["Metallic"].default_value = 0.0
        except KeyError:
            pass
    return mat


def _world(colour):
    """The neutral background — and, at the same time, the ambient fill."""
    world = bpy.data.worlds.new("Exterior")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        r, g, b = (list(colour or []) + [0.55, 0.55, 0.55])[:3]
        bg.inputs["Color"].default_value = (float(r), float(g), float(b), 1.0)
        bg.inputs["Strength"].default_value = WORLD_STRENGTH
    bpy.context.scene.world = world


def _sun(name, energy, elevation_deg, azimuth_deg):
    """One shadowless directional light.

    ``use_shadow`` off is the whole point: the lamp still shades the faces it
    hits at a grazing angle, but it casts nothing onto anything.
    """
    light = bpy.data.lights.new(name, "SUN")
    light.energy = float(energy)
    light.use_shadow = False
    # A sun's default direction is straight down (-Z); pitching it up by
    # (90° − elevation) and then spinning it by the azimuth puts it in the sky.
    obj = bpy.data.objects.new(name, light)
    obj.rotation_euler = (math.radians(90.0 - float(elevation_deg)), 0.0,
                          math.radians(float(azimuth_deg)))
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _bounds(verts):
    lo = [min(v[i] for v in verts) for i in range(3)]
    hi = [max(v[i] for v in verts) for i in range(3)]
    return lo, hi


def render(args):
    job_file = args["inputs"].get("job")
    if not job_file:
        raise ValueError("no input 'job'")
    job = json.loads(Path(job_file).read_text(encoding="utf-8"))
    mesh_spec = job.get("mesh") or {}
    verts = [tuple(float(c) for c in v) for v in mesh_spec.get("vertices") or []]
    faces = [list(int(i) for i in f) for f in mesh_spec.get("faces") or []]
    if len(verts) < 3 or not faces:
        raise ValueError("job carries no mesh")
    cam_spec = job.get("camera") or {}
    render_spec = job.get("render") or {}

    _common.reset_scene()
    name = str(mesh_spec.get("name") or "exterior")
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    # A face list the server got wrong must not travel on as a broken picture.
    me.validate(verbose=False)

    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)

    materials = job.get("materials") or [{"name": "wall",
                                          "color": [0.7, 0.7, 0.7],
                                          "roughness": 0.9}]
    for i, spec in enumerate(materials):
        obj.data.materials.append(_material(spec, i))
    per_face = mesh_spec.get("face_material") or []
    for i, poly in enumerate(me.polygons):
        idx = int(per_face[i]) if i < len(per_face) else 0
        poly.material_index = max(0, min(idx, len(materials) - 1))
        # Flat shading: a building is all creases, and a smoothed corner reads
        # as a dent from every distance — and meshes back as one.
        poly.use_smooth = False

    scene = bpy.context.scene
    size = int(render_spec.get("size") or 1024)
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = int(render_spec.get("samples") or 64)
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    # NOT transparent: the ``building`` use case asks for a plain neutral
    # background, and the world colour is exactly that.
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"

    _world(render_spec.get("background"))
    yaw = float(cam_spec.get("yaw_deg") or 35.0)
    for i, (energy, elevation, azimuth) in enumerate(LAMPS):
        _sun(f"Sun{i}", energy, elevation, yaw + azimuth)

    lo, hi = _bounds(verts)
    centre = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2,
                     (lo[2] + hi[2]) / 2))
    radius = max(math.dist(lo, hi) / 2, 1e-3)

    lens = float(cam_spec.get("lens_mm") or 85.0)
    sensor = float(cam_spec.get("sensor_mm") or 36.0)
    margin = float(cam_spec.get("margin") or 1.15)
    # The distance at which a sphere of ``radius * margin`` exactly fills the
    # frame: sin(half fov) = r / d. The resolution is square, so the same half
    # angle holds on both axes whatever the sensor fit resolves to.
    half_fov = math.atan((sensor / 2.0) / lens)
    distance = (radius * margin) / max(math.sin(half_fov), 1e-6)

    elevation = math.radians(float(cam_spec.get("elevation_deg") or 35.0))
    rad = math.radians(yaw)
    horizontal = math.cos(elevation) * distance
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = lens
    cam_data.sensor_width = sensor
    # Nothing may be clipped away: the body can be tens of metres across and
    # the camera stands several body-diameters back from it.
    cam_data.clip_start = max(distance * 0.01, 0.01)
    cam_data.clip_end = distance * 4.0 + radius * 4.0
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.location = (centre.x + math.sin(rad) * horizontal,
                    centre.y - math.cos(rad) * horizontal,
                    centre.z + math.sin(elevation) * distance)
    direction = centre - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    out = Path(args["out_dir"]) / str(render_spec.get("png") or "exterior.png")
    scene.render.filepath = str(out)
    bpy.ops.render.render(write_still=True)
    if not out.is_file():
        raise RuntimeError(f"render wrote no file: {out}")

    # What was actually built — the server compares it against what it asked
    # for (§ B5a: numbers, not screenshots).
    return ({"vertices": len(me.vertices), "faces": len(me.polygons),
             "tris": sum(max(0, len(f) - 2) for f in faces),
             "materials": len(materials),
             # Blender frame, the frame the job speaks.
             "bbox": [round(v, 5) for v in lo + hi],
             "size": size,
             "camera_distance": round(distance, 4),
             "bytes": out.stat().st_size},
            {"png": str(out)})


_common.main(render)
