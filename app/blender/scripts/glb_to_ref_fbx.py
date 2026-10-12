"""Convert a generated motion to motion and canonical-rest FBX files.

``format`` "glb": a Mixamo GLB on the puppet, scaled back to the reference
hips (UniMate). ``format`` "fbx": an FBX already retargeted onto the
reference rig (Kimodo) — no rescale, but every bone of the ``ref`` input
must be present. Both strip the ``mixamorig:`` prefix for the inbox
importer's mixamo-noprefix family.
"""
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common
sys.path.remove(_SCRIPTS_DIR)

import bpy


PREFIX = "mixamorig:"


def _strip(name):
    return name[len(PREFIX):] if name.startswith(PREFIX) else name


def _reference_bones(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=path)
    arms = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    if len(arms) != 1:
        raise ValueError(f"reference rig: expected one armature, found {len(arms)}")
    return {_strip(b.name) for b in arms[0].data.bones}


def run(job):
    params = {"ref_hips_m": 1.13032, "format": "glb", **job.get("params", {})}
    fmt = params["format"]
    if fmt not in ("glb", "fbx"):
        raise ValueError(f"unsupported format '{fmt}'")
    src = job["inputs"]["src"]
    required = _reference_bones(job["inputs"]["ref"]) if fmt == "fbx" else set()
    motion_out = str(Path(job["out_dir"]) / "motion.fbx")
    rest_out = str(Path(job["out_dir"]) / "rest.fbx")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = 30          # BEFORE the import: keys are seconds
    if fmt == "glb":
        bpy.ops.import_scene.gltf(filepath=src)
    else:
        bpy.ops.import_scene.fbx(filepath=src)
    arms = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    if len(arms) != 1:
        raise ValueError(f"expected one armature, found {len(arms)}")
    arm = arms[0]
    act = arm.animation_data.action if arm.animation_data else None
    if act is None or len(bpy.data.actions) != 1:
        raise ValueError("expected exactly one animation")
    for b in arm.data.bones:                     # the inbox importer knows mixamo-noprefix only
        b.name = _strip(b.name)
    missing = sorted(required - {b.name for b in arm.data.bones})
    if missing:
        raise ValueError("bones missing against the reference rig: " + ", ".join(missing))
    scene = bpy.context.scene
    if fmt == "fbx":
        # The FBX importer adopts the file's frame rate; retime its keys to 30 fps
        # over the same duration, so every clip leaves here at 30 fps.
        src_fps = scene.render.fps / scene.render.fps_base
        if abs(src_fps - 30.0) > 1e-6:
            factor, start = 30.0 / src_fps, act.frame_range[0]
            for fc in act.fcurves:
                for kp in fc.keyframe_points:
                    for point in (kp.co, kp.handle_left, kp.handle_right):
                        point.x = start + (point.x - start) * factor
                fc.update()
            scene.render.fps, scene.render.fps_base = 30, 1.0
    scene.frame_start, scene.frame_end = int(act.frame_range[0]), int(act.frame_range[1])
    k = 1.0
    if fmt == "glb":
        # UniMate normalises the rig size: scale back to the reference hips (object
        # scale, NOT applied, so the action's hip translations scale with the bones).
        arm.animation_data.action = None
        for pb in arm.pose.bones:
            pb.matrix_basis.identity()
        bpy.context.view_layer.update()
        hips = arm.pose.bones["Hips"]
        rest_h = (arm.matrix_world @ hips.matrix).translation.z
        k = float(params["ref_hips_m"]) / rest_h
        arm.scale = arm.scale * k
        arm.animation_data.action = act
    for o in [o for o in scene.objects if o.type == "MESH"]:
        bpy.data.objects.remove(o, do_unlink=True)
    common = dict(use_selection=False, object_types={"ARMATURE"}, add_leaf_bones=False,
                  apply_scale_options="FBX_SCALE_ALL")
    bpy.ops.export_scene.fbx(filepath=motion_out, bake_anim=True, bake_anim_use_all_actions=False,
                             bake_anim_use_nla_strips=False, **common)
    arm.animation_data.action = None
    for pb in arm.pose.bones:
        pb.matrix_basis.identity()
    bpy.ops.export_scene.fbx(filepath=rest_out, bake_anim=False, **common)
    result = {"frames": scene.frame_end - scene.frame_start + 1, "fps": 30,
              "scale": round(k, 5), "bones": len(arm.data.bones)}
    return result, {"motion": motion_out, "rest": rest_out}


if __name__ == "__main__":
    _common.main(run)
