"""Scene helpers shared by the clip scripts: sample a posed armature, write root keys. bpy only.

Moved out of ``clip_orient`` so ``cmu_clip`` can use them too — ``clip_orient``
imports ``cmu_clip``, so this module imports neither.
"""
import bpy
from mathutils import Matrix


def sample(arm, frames):
    """Per frame the pose matrices in armature space AND every bone's posed
    head/tail — the first for the rigid check, the second for the floor."""
    scene = bpy.context.scene
    mats, joints = {}, {}
    for f in frames:
        scene.frame_set(f)
        bpy.context.view_layer.update()
        mats[f] = {pb.name: pb.matrix.copy() for pb in arm.pose.bones}
        joints[f] = {pb.name: (pb.head.copy(), pb.tail.copy())
                     for pb in arm.pose.bones}
    return mats, joints


def write_track(action, path: str, values: dict, size: int) -> None:
    """``values``: {frame: tuple of ``size`` floats} onto the curves of one
    data path — created when the clip did not drive them so far."""
    curves, points = [], []
    order = sorted(values)
    for i in range(size):
        fc = action.fcurves.find(path, index=i)
        if fc is None:
            fc = action.fcurves.new(data_path=path, index=i)
            fc.keyframe_points.add(len(order))
            for k, f in enumerate(order):
                fc.keyframe_points[k].co = (float(f), 0.0)
        curves.append(fc)
        points.append({int(round(kp.co[0])): kp for kp in fc.keyframe_points})
    for f in order:
        for i, v in enumerate(values[f]):
            kp = points[i].get(int(f))
            if kp is None:
                kp = curves[i].keyframe_points.insert(float(f), v, options={"FAST"})
                points[i][int(f)] = kp
            kp.co[1] = v
    for fc in curves:
        fc.update()


def write_root(arm, action, bone: str, mats: dict, rest: Matrix) -> None:
    """Puts the transformed root poses back as keys: the bone has no parent,
    so its basis is ``rest⁻¹ · M`` (``cmu_clip._bake``'s formula)."""
    quats, locs = {}, {}
    prev = None
    for f in sorted(mats):
        basis = rest.inverted() @ mats[f]
        q = basis.to_quaternion()
        if prev is not None and q.dot(prev) < 0.0:
            q.negate()          # same rotation, continuous sign between keys
        prev = q
        quats[f] = (q.w, q.x, q.y, q.z)
        t = basis.to_translation()
        locs[f] = (t.x, t.y, t.z)
    arm.pose.bones[bone].rotation_mode = "QUATERNION"
    write_track(action, f'pose.bones["{bone}"].rotation_quaternion', quats, 4)
    write_track(action, f'pose.bones["{bone}"].location', locs, 3)
