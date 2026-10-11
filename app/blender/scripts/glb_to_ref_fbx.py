"""Convert a generated Mixamo GLB to motion and canonical-rest FBX files."""
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common
sys.path.remove(_SCRIPTS_DIR)

import bpy


def run(job):
    glb = job["inputs"]["glb"]
    params = {"ref_hips_m": 1.13032, **job.get("params", {})}
    motion_out = str(Path(job["out_dir"]) / "motion.fbx")
    rest_out = str(Path(job["out_dir"]) / "rest.fbx")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = 30          # BEFORE the import: glTF keys are seconds
    bpy.ops.import_scene.gltf(filepath=glb)
    arms = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    if len(arms) != 1:
        raise ValueError(f"expected one armature, found {len(arms)}")
    arm = arms[0]
    act = arm.animation_data.action if arm.animation_data else None
    if act is None or len(bpy.data.actions) != 1:
        raise ValueError("expected exactly one animation")
    for b in arm.data.bones:                     # the inbox importer knows mixamo-noprefix only
        if b.name.startswith("mixamorig:"):
            b.name = b.name[len("mixamorig:"):]
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = int(act.frame_range[0]), int(act.frame_range[1])
    # UniMate normalises the rig size: scale back to the reference hips (object scale,
    # NOT applied, so the action's hip translations scale with the bones).
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
