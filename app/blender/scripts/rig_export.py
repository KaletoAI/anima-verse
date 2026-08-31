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

THE SOURCE MUST CARRY A BIND POSE
---------------------------------
The retarget composes ``R_cmu(t) · A · R_rest`` (``cmu_clip.py``) and reads the
actor's motion as the rotation away from CMU's T-pose — so the reference's REST
POSE has to be a T-pose too, and a symmetric one. A CLIP FBX cannot supply it:
``cmu_clip._export`` writes the armature alone (``object_types={"ARMATURE"}``),
which leaves no bind pose in the file, so Blender's importer rebuilds the rest
from the animated node transforms and hands back the clip's FIRST FRAME as the
rest pose. Building the reference out of a converted clip therefore freezes a
posed frame — arms hanging, torso tilted — and every clip driven onto it
inherits the tilt: the shoulder on the low side droops and its palm rolls out
(2026-08-31 finding).

``_check_rest`` refuses such a source instead of writing a silently posed
reference: rest arms have to point along ±X, the hips up, and the limbs have to
mirror each other. A rigged character export (mesh + bind pose) or a clip from
a source that ships one passes; a clip of this pipeline does not.
"""
import math
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bpy                                                    # noqa: E402
from mathutils import Matrix, Vector                          # noqa: E402

PREFIX = "mixamorig:"

# Tolerances for the rest-pose check. The project's T-pose rig measures 0.00°
# on the axis checks and 0.02° on the mirror check, a clip's frozen frame 75°
# and 80° — so anything in between separates them with room to spare.
AXIS_TOL_DEG = 10.0
MIRROR_TOL_DEG = 2.0
#: How far a bone head of the WRITTEN file may sit from the source's.
HEAD_TOL_CM = 0.05
#: Bones whose left and right rest basis must mirror each other.
MIRROR_BONES = ("Shoulder", "Arm", "ForeArm", "Hand", "UpLeg", "Leg", "Foot")


def _angle(a: Vector, b: Vector) -> float:
    if a.length < 1e-9 or b.length < 1e-9:
        return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, a.normalized().dot(b.normalized())))))


def _mirror_columns(m):
    """Columns of ``M·R·M`` for the mirror ``M = diag(-1, 1, 1)`` — the right
    bone's basis expressed as the left one would have to be."""
    out = []
    for j in range(3):
        v = Vector((m[0][j], m[1][j], m[2][j]))
        w = Vector((-v.x, v.y, v.z))
        out.append(-w if j == 0 else w)
    return out


def _check_rest(arm) -> dict:
    """Measures the rest pose and raises unless it is a symmetric T-pose."""
    bones = arm.data.bones

    def need(name):
        b = bones.get(PREFIX + name)
        if b is None:
            raise ValueError(f"the armature has no {PREFIX}{name}")
        return b

    hips = need("Hips")
    measured = {
        "hips_off_up_deg": round(_angle(hips.tail_local - hips.head_local,
                                        Vector((0.0, 1.0, 0.0))), 3),
        "hips_head_cm": round(hips.head_local.y, 3),
    }
    for side, axis in (("Left", 1.0), ("Right", -1.0)):
        b = need(side + "Arm")
        measured[f"{side.lower()}_arm_off_x_deg"] = round(
            _angle(b.tail_local - b.head_local, Vector((axis, 0.0, 0.0))), 3)
    worst = 0.0
    worst_bone = ""
    for short in MIRROR_BONES:
        left, right = bones.get(PREFIX + "Left" + short), bones.get(PREFIX + "Right" + short)
        if left is None or right is None:
            continue
        lm = left.matrix_local.to_3x3()
        mirrored = _mirror_columns(right.matrix_local.to_3x3())
        for j in range(3):
            d = _angle(Vector((lm[0][j], lm[1][j], lm[2][j])), mirrored[j])
            if d > worst:
                worst, worst_bone = d, short
    measured["worst_mirror_deg"] = round(worst, 3)
    measured["worst_mirror_bone"] = worst_bone

    posed = [f"{k} = {measured[k]}°" for k in
             ("hips_off_up_deg", "left_arm_off_x_deg", "right_arm_off_x_deg")
             if measured[k] > AXIS_TOL_DEG]
    if posed:
        raise ValueError(
            "the source's REST pose is not a T-pose (" + ", ".join(posed) +
            f", tolerance {AXIS_TOL_DEG}°) — a clip FBX of this pipeline carries "
            "no bind pose, so it reads back posed; use a rigged character export")
    if worst > MIRROR_TOL_DEG:
        raise ValueError(
            f"the source's REST pose is not left/right symmetric ({worst_bone}: "
            f"{worst:.2f}°, tolerance {MIRROR_TOL_DEG}°) — every clip driven onto "
            "it would inherit the tilt")
    return measured


def _verify_written(out: Path, heads: dict) -> dict:
    """Reads the written file back and checks it against the source rest.

    The reference is measured where it is CONSUMED — as a file, through the
    same importer ``cmu_clip._load_rig`` uses — not on the scene it was
    exported from: everything that went wrong here went wrong in the
    import/export round trip, not in the scene.
    """
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(out), global_scale=1.0)
    arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if arm is None:
        raise ValueError("the written file reads back without an armature")
    rest = _check_rest(arm)
    worst, worst_bone = 0.0, ""
    for b in arm.data.bones:
        src_head = heads.get(b.name)
        if src_head is None:
            raise ValueError(f"the written file has an extra bone: {b.name}")
        d = (b.head_local - src_head).length
        if d > worst:
            worst, worst_bone = d, b.name
    missing = sorted(set(heads) - {b.name for b in arm.data.bones})
    if missing:
        raise ValueError(f"the written file lost {len(missing)} bone(s), "
                         f"e.g. {missing[0]}")
    if worst > HEAD_TOL_CM:
        raise ValueError(
            f"the written file does not read back as the source skeleton "
            f"({worst_bone} is {worst:.2f} cm off, tolerance {HEAD_TOL_CM} cm)")
    rest["worst_head_delta_cm"] = round(worst, 4)
    return rest


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
    rest = _check_rest(arm)
    heads = {b.name: b.head_local.copy() for b in arm.data.bones}
    for o in list(bpy.data.objects):
        if o is not arm:
            bpy.data.objects.remove(o, do_unlink=True)
    arm.animation_data_clear()
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action)
    # Clearing the animation DATA leaves the POSE where the last evaluated
    # frame put it, and the FBX exporter writes bones from the pose — so a
    # source with an action exported its FIRST FRAME as the new rest pose
    # (the reference of 2026-08-30 was the idle clip's frame 1, not its
    # T-pose). Reset every pose bone to rest before writing.
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()

    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.fbx(
        filepath=str(out), use_selection=True, object_types={"ARMATURE"},
        add_leaf_bones=False, bake_anim=False,
        armature_nodetype="NULL", axis_forward="-Z", axis_up="Y",
    )

    # Everything read off the scene has to be collected BEFORE the
    # verification reloads it.
    bones = sorted(b.name for b in arm.data.bones)
    info = {"bones": len(bones), "names": bones,
            "scale": list(arm.scale), "rotation_euler": list(arm.rotation_euler),
            "rest": rest,
            "hips_head_cm": list(arm.data.bones[PREFIX + "Hips"].head_local)
            if (PREFIX + "Hips") in arm.data.bones else None}
    info["written"] = _verify_written(out, heads)
    return info, {"rig": str(out)}


_common.main(run)
