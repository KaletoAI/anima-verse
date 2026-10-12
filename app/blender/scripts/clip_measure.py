"""Measure animated joint heights and head tilt on an imported FBX clip."""
import math
import sys
from pathlib import Path
from statistics import median

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common
sys.path.remove(_SCRIPTS_DIR)

import bpy
from mathutils import Vector


def _source_tracks(path):
    """Read authored channels; Blender's importer bakes extra loc/scale curves."""
    from io_scene_fbx import parse_fbx
    root, _version = parse_fbx.parse(str(path))
    objects = next(e for e in root.elems if e.id == b"Objects")
    connections = next(e for e in root.elems if e.id == b"Connections")
    models = {e.props[0]: e.props[1].split(b"\x00", 1)[0].decode("utf-8").split(":")[-1]
              for e in objects.elems if e.id == b"Model"}
    nodes = {e.props[0] for e in objects.elems if e.id == b"AnimationCurveNode"}
    keyed = set()
    for curve in objects.elems:
        if curve.id == b"AnimationCurve":
            fields = {e.id: e.props for e in curve.elems}
            if (fields.get(b"KeyTime") and len(fields[b"KeyTime"][0]) and
                    fields.get(b"KeyValueFloat") and len(fields[b"KeyValueFloat"][0])):
                keyed.add(curve.props[0])
    links = [e.props for e in connections.elems if e.id == b"C"]
    keyed_nodes = {p[2] for p in links if len(p) >= 3 and p[1] in keyed and p[2] in nodes}
    tracks = {"rot_tracks": set(), "loc_tracks": set(), "scale_tracks": set()}
    fields = {b"Lcl Rotation": "rot_tracks", b"Lcl Translation": "loc_tracks", b"Lcl Scaling": "scale_tracks"}
    for link in links:
        if len(link) >= 4 and link[1] in keyed_nodes and link[2] in models:
            field = fields.get(link[3])
            if field:
                tracks[field].add(models[link[2]])
    return {field: sorted(names) for field, names in tracks.items()}


def run(job):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 30
    bpy.ops.import_scene.fbx(filepath=job["inputs"]["clip"], automatic_bone_orientation=False)
    arms = [obj for obj in scene.objects if obj.type == "ARMATURE"]
    if len(arms) != 1:
        raise ValueError("expected one armature")
    arm = arms[0]
    action = arm.animation_data.action if arm.animation_data else None
    if action is None:
        raise ValueError("clip has no action")
    bones = {bone.name.split(":")[-1]: bone for bone in arm.pose.bones}
    hips = bones["Hips"]
    feet = [bone for name, bone in bones.items() if "Foot" in name or "Toe" in name]
    if not feet:
        raise ValueError("clip has no foot or toe joints")

    def position(bone):
        point = (arm.matrix_world @ bone.matrix).translation
        return Vector((point.x, point.z, -point.y))

    heights, foot_heights, tilts = [], [], []
    start, end = (int(value) for value in action.frame_range)
    for frame in range(start, end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        heights.append(float(position(hips).y))
        foot_heights.extend(float(position(bone).y) for bone in feet)
        if "Neck" in bones and "HeadTop_End" in bones:
            direction = position(bones["HeadTop_End"]) - position(bones["Neck"])
            if direction.length:
                tilts.append(math.degrees(direction.angle(Vector((0, 1, 0)))))
    tracks = _source_tracks(job["inputs"]["clip"])
    duration_s = float(action.frame_range[1] - action.frame_range[0]) / (scene.render.fps / scene.render.fps_base)
    return {"bones": list(bones), **tracks,
            "duration_s": duration_s, "frames": len(heights), "hips_y": heights, "min_foot_y": min(foot_heights),
            "head_tilt_deg_median": median(tilts) if tilts else 0.0}, {}


if __name__ == "__main__":
    _common.main(run)
