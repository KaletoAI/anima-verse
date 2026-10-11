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
    return {"frames": len(heights), "hips_y": heights, "min_foot_y": min(foot_heights),
            "head_tilt_deg_median": median(tilts) if tilts else 0.0}, {}


if __name__ == "__main__":
    _common.main(run)
