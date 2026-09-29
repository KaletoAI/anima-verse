"""Renders a clip as a contact sheet: a jointed mannequin built ON the
clip's own armature (the reference skeleton — no figure mesh, so no
retarget and no licensed asset), seen from the front and from the figure's
left, at a few frames.

Invoked through ``runner.run("clip_sheet", inputs={"clip": fbx},
params={"frames": [...], "views": ["front", "side"], "size": [w, h],
"engine": "BLENDER_WORKBENCH"})``. Left limbs blue, right limbs orange.
Engine CYCLES (CPU, 8 samples) is the fallback for a host without a GL
context — the caller retries with it when the first run fails.
"""
import math
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bmesh                                                  # noqa: E402
import bpy                                                    # noqa: E402
from mathutils import Matrix, Vector                          # noqa: E402

COLORS = {"Left": (0.25, 0.45, 0.85, 1.0), "Right": (0.90, 0.50, 0.20, 1.0),
          "": (0.80, 0.80, 0.80, 1.0)}
RADIUS_CM = {"Hips": 9.0, "Spine": 9.0, "Spine1": 10.0, "Spine2": 11.0, "Neck": 4.0,
             "Shoulder": 3.5, "Arm": 4.5, "ForeArm": 3.5, "Hand": 3.0,
             "UpLeg": 7.0, "Leg": 5.0, "Foot": 4.0, "ToeBase": 3.0}
SKIP = ("_End", "Eye", "Ribbon")


def _side(short):
    return "Left" if short.startswith("Left") else "Right" if short.startswith("Right") else ""


def _material(side, engine):
    name = f"mq_{side or 'mid'}"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = COLORS[side]
    if engine == "CYCLES":
        mat.use_nodes = True
        mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = COLORS[side]
    return mat


def _limb(arm, bone, radius, length, mat):
    """A tapered cylinder in BONE space: bone parenting puts the child's
    origin at the bone's TAIL with +Y along the bone, so the cylinder spans
    y in [-length, 0]."""
    mesh = bpy.data.meshes.new(f"mq_{bone.name}")
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=radius,
                          radius2=radius * 0.85, depth=length)
    bmesh.ops.rotate(bm, verts=bm.verts, matrix=Matrix.Rotation(-math.pi / 2, 3, "X"))
    bmesh.ops.translate(bm, verts=bm.verts, vec=Vector((0.0, -length / 2, 0.0)))
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(mesh.name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(mat)
    obj.parent = arm
    obj.parent_type = "BONE"
    obj.parent_bone = bone.name
    obj.matrix_parent_inverse = Matrix.Identity(4)
    return obj


def _link(arm, bone, a, b, radius, mat):
    """A cylinder between two ARMATURE-space rest points, riding on ``bone``.

    The Hips bone points up from the hip joint, but the thighs start ~12 cm
    lower and 10 cm to the side (rest: Hips head y=113, UpLeg heads y=100.7,
    x=±10) — without a link the legs float free of the torso. The child
    frame of a bone parent is the bone's rest matrix moved to its TAIL, so
    the points are taken into that frame first."""
    to_local = (bone.matrix_local @ Matrix.Translation((0.0, bone.length, 0.0))).inverted()
    la, lb = to_local @ Vector(a), to_local @ Vector(b)
    axis = lb - la
    mesh = bpy.data.meshes.new(f"mq_link_{bone.name}_{len(bpy.data.meshes)}")
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=radius,
                          radius2=radius, depth=axis.length)
    rot = Vector((0.0, 0.0, 1.0)).rotation_difference(axis.normalized()).to_matrix()
    bmesh.ops.rotate(bm, verts=bm.verts, matrix=rot)
    bmesh.ops.translate(bm, verts=bm.verts, vec=(la + lb) / 2)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(mesh.name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(mat)
    obj.parent = arm
    obj.parent_type = "BONE"
    obj.parent_bone = bone.name
    obj.matrix_parent_inverse = Matrix.Identity(4)
    return obj


def _mannequin(arm, engine):
    for bone in arm.data.bones:
        short = bone.name.split(":")[-1]
        if any(s in short for s in SKIP) or short.endswith("4") or bone.length < 0.5:
            continue
        key = next((k for k in sorted(RADIUS_CM, key=len, reverse=True)
                    if short.endswith(k)), None)
        radius = RADIUS_CM.get(key, 0.9)
        _limb(arm, bone, radius, bone.length, _material(_side(short), engine))
        if short.endswith("UpLeg") and bone.parent is not None:
            _link(arm, bone.parent, bone.parent.head_local, bone.head_local,
                  radius, _material(_side(short), engine))
    head = arm.data.bones.get("mixamorig:Head")
    if head is not None:
        bpy.ops.mesh.primitive_uv_sphere_add(radius=10.0, segments=16, ring_count=8)
        s = bpy.context.active_object
        s.data.materials.append(_material("", engine))
        s.parent, s.parent_type, s.parent_bone = arm, "BONE", head.name
        s.matrix_parent_inverse = Matrix.Identity(4)
        s.location = (0.0, 2.0, 0.0)


def _bbox(arm, frames):
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for f in frames:
        bpy.context.scene.frame_set(f)
        for pb in arm.pose.bones:
            for p in (arm.matrix_world @ pb.head, arm.matrix_world @ pb.tail):
                lo = Vector(map(min, lo, p))
                hi = Vector(map(max, hi, p))
    return lo, hi


def run(job):
    params = dict(job.get("params") or {})
    engine = params.get("engine", "BLENDER_WORKBENCH")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=job["inputs"]["clip"], global_scale=1.0)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    frames = [int(f) for f in params["frames"]]
    _mannequin(arm, engine)
    lo, hi = _bbox(arm, frames)
    center = (lo + hi) / 2
    extent = max(hi.z - lo.z, hi.x - lo.x, hi.y - lo.y)
    bpy.ops.mesh.primitive_plane_add(size=max(4.0, extent * 2), location=(center.x, center.y, 0.0))
    bpy.context.active_object.data.materials.append(_material("", engine))
    scene = bpy.context.scene
    scene.render.engine = engine
    if engine == "CYCLES":
        scene.cycles.device = "CPU"
        scene.cycles.samples = 8
        bpy.ops.object.light_add(type="SUN", location=(2, -3, 5))
        world = bpy.data.worlds.new("w")
        scene.world = world
        world.use_nodes = True
        world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.8
    else:
        scene.display.shading.color_type = "MATERIAL"
    w, h = params.get("size", [300, 380])
    scene.render.resolution_x, scene.render.resolution_y = int(w), int(h)
    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = extent * 1.15 + 0.2
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    # The armature object turns +90 deg about X: the figure's front (+Z in
    # armature space) faces world -Y, its left (+X) is world +X, up is +Z.
    views = {"front": ((0.0, -10.0, 0.0), (math.pi / 2, 0.0, 0.0)),
             "side": ((10.0, 0.0, 0.0), (math.pi / 2, 0.0, math.pi / 2))}
    outputs = {}
    out_dir = Path(job["out_dir"])
    for view in params.get("views", ["front", "side"]):
        offset, rot = views[view]
        cam.location = center + Vector(offset)
        cam.rotation_euler = rot
        for i, f in enumerate(frames):
            scene.frame_set(f)
            path = out_dir / f"{view}_{i}.png"
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            outputs[f"{view}_{i}"] = str(path)
    return {"engine": engine, "frames": frames}, outputs


if __name__ == "__main__":
    _common.main(run)
