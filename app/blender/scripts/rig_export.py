"""Writes the RETARGET REFERENCE skeleton — one FBX with the armature alone.

Invoked through ``app.blender.runner.run("rig_export", inputs=…, params=…)``:

    inputs   src    an FBX carrying the project's ``mixamorig:`` armature
                    (a library clip, a rigged character export)
    params   name   file stem of the result (default "reference")

Everything but the armature is dropped — meshes, materials, and every action
or animation datablock — while the armature itself is kept exactly as it comes
in: the object's 0.01 scale / +90° X rotation and the centimetre bone lengths
of the Mixamo convention (see ``cmu_clip.py``, "Frames of reference"). Import
and export therefore use the SAME axis settings the clip exporter uses, so the
result reads back as the source armature bone for bone.

The result is what ``app.core.cmu_import.default_rig()`` hands to a
conversion: the skeleton every clip is retargeted onto, and nothing else.
"""
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bpy                                                    # noqa: E402

PREFIX = "mixamorig:"


def run(job):
    src = (job.get("inputs") or {})["src"]
    name = str((job.get("params") or {}).get("name") or "reference")
    out = Path(job["out_dir"]) / f"{name}.fbx"

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(src), global_scale=1.0)
    arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if arm is None:
        raise ValueError("the source FBX carries no armature")
    if not any(b.name.startswith(PREFIX) for b in arm.data.bones):
        raise ValueError("the armature carries no mixamorig bones")
    for o in list(bpy.data.objects):
        if o is not arm:
            bpy.data.objects.remove(o, do_unlink=True)
    arm.animation_data_clear()
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action)

    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.fbx(
        filepath=str(out), use_selection=True, object_types={"ARMATURE"},
        add_leaf_bones=False, bake_anim=False,
        armature_nodetype="NULL", axis_forward="-Z", axis_up="Y",
    )

    bones = sorted(b.name for b in arm.data.bones)
    return ({"bones": len(bones), "names": bones,
             "scale": list(arm.scale), "rotation_euler": list(arm.rotation_euler),
             "hips_head_cm": list(arm.data.bones[PREFIX + "Hips"].head_local)
             if (PREFIX + "Hips") in arm.data.bones else None},
            {"rig": str(out)})


_common.main(run)
