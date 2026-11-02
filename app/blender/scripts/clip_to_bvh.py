"""Drive a library FBX onto the reference rig and export a plain cm BVH.

Runner inputs: clip, rig. Params: start_s, end_s, fps. Output: bvh.
The BVH exporter writes armature-local coordinates, ignoring object transforms.
Reference bones are already in cm and Y-up, so global_scale=1 is intentional;
Anima's BVH reader applies 0.01 to recover metres.
"""
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
import _common
import cmu_clip
import bpy


def run(job):
    inputs, params = job["inputs"], job.get("params", {})
    rig = cmu_clip._load_rig(inputs["rig"])
    scene = bpy.context.scene
    fps = int(params.get("fps", 30))
    scene.render.fps = fps
    scene.render.fps_base = 1.0
    before = set(scene.objects)
    bpy.ops.wm.fbx_import(filepath=inputs["clip"])
    arms = [o for o in scene.objects if o not in before and o.type == "ARMATURE"]
    if len(arms) != 1:
        raise ValueError("clip must carry exactly one armature")
    source = arms[0]
    action = source.animation_data.action if source.animation_data else None
    if action is None:
        raise ValueError("clip has no animation")
    first, last = map(float, action.frame_range)
    duration = (last - first) / fps
    start = float(params.get("start_s", 0.0))
    end = params.get("end_s")
    end = duration if end is None else min(float(end), duration)
    if not 0 <= start < end:
        raise ValueError("export range is empty or outside the clip")
    count = int(math.floor((end - start) * fps + 1e-6)) + 1
    # A library FBX has no reliable bind pose. Transfer evaluated world poses,
    # rather than assigning its action (whose basis depends on that bind pose).
    names = [b.name for b in rig.pose.bones]
    if any(name not in source.pose.bones for name in names):
        raise ValueError("clip does not carry the reference skeleton")
    poses = []
    for index in range(count):
        frame = first + start * fps + index
        scene.frame_set(int(frame), subframe=frame % 1)
        bpy.context.view_layer.update()
        to_rig = rig.matrix_world.inverted() @ source.matrix_world
        poses.append({name: to_rig @ source.pose.bones[name].matrix for name in names})
    for index, pose in enumerate(poses, 1):
        scene.frame_set(index)
        for bone in rig.pose.bones:
            bone.rotation_mode = "QUATERNION"
            bone.matrix = pose[bone.name]
            bpy.context.view_layer.update()
            for channel in ("location", "rotation_quaternion", "scale"):
                bone.keyframe_insert(channel, frame=index)
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    out = Path(job["out_dir"]) / "clip.bvh"
    bpy.ops.export_anim.bvh(filepath=str(out), frame_start=1, frame_end=count,
                            global_scale=1.0, rotate_mode="XYZ", root_transform_only=True)
    text = out.read_text(encoding="utf-8").replace("mixamorig:", "")
    out.write_text(text, encoding="utf-8")
    return {"frames": count, "fps": fps, "duration_s": (count - 1) / fps,
            "joints": [line.split()[1] for line in text.splitlines()
                       if line.strip().startswith(("ROOT ", "JOINT "))]}, {"bvh": str(out)}


if __name__ == "__main__":
    _common.main(run)
