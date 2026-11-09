"""Normalises a model in place: real height, feet on the ground, origin
under the feet, transforms baked into the geometry.

What today every renderer corrects at runtime (scale from the profile height,
ground offset from the bounding box, Z-up uprighting) is done ONCE here, so a
number read anywhere outside a renderer is the real one — the architecture
rule behind ``scene_recipe.py``: geometry lives in exactly one place.

    target_height_m   the height the model must end up with (> 0, metres)

Height basis (plan-blender-veredelung.md § 2.0, decided 2026-08-06): a Mixamo
rig is measured at its CROWN JOINT (``HeadTop_End``) — hair, hats and horns
above the crown must not shrink the body, which is exactly what a bounding-box
scale does. The gateway's 52-joint rigs END AT ``Head`` (no crown joint), so
for them the crown is ESTIMATED: measured over the whole store (73 models,
2026-08-07), the head joint sits at median 0.877 of the visual height with a
0.82..0.92 spread — the estimate ``(head - floor) / 0.875`` is therefore only
trusted when the box is CLEARLY taller than anatomy allows (head ratio below
0.80, i.e. headwear adds more than ~9 %); inside the normal band the box is
exact and anatomy would only add noise. Anything without a head joint
(generic rigs, props) keeps the box.

Steps, in order:

    0. untwist   correct Neck/Head forward twist, bake skin and rest pose
    0b. posture  with input ``source`` (the UNRIGGED mesh the rigger was
                 given): put the trunk/neck/head chain back into the posture
                 of that source, bake skin and rest pose — see
                 ``_restore_posture``
    1. measure   bounding box, crown joint, triangles, joints
    2. scale     measured height -> target_height_m, uniformly
    3. ground    X/Y centre of the box to 0, lowest point to z=0
    4. bake      transforms applied, so scale/rotation live in the geometry
                 and no importer heuristic ("is this Z-up?") has to guess
    5. repair    with ``repair_limb_weights`` (humanoid rigs), remove hand/foot
                 weights the rigger put on the pelvis (``_limb_weights.py``)

Reported under ``data``: ``height_basis`` ("crown"|"bbox"), ``scale``, and
``before``/``after`` with {dims_m, center_xy, min_z, tris, joints} each —
the numbers the sidecar keeps against double normalisation.

The exporter writes the same format the input had (GLB in practice — the
caller gates on it). Nothing here validates the result; the application side
holds it to the same check as a fresh delivery and keeps the original if the
export broke anything (§ 2.2).
"""
import sys
import math
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bpy                                                    # noqa: E402
from mathutils import Matrix, Vector                          # noqa: E402


_common.app_root_on_path()
from app.core.head_twist import bone_name, twist_degrees


def _untwist_head():
    # "applied" = the rotation actually turned about each joint's own axis,
    # in degrees — exactly how far that joint's LOCAL frame moves (the head's
    # angle is measured after the neck has been corrected). The joint-frame
    # gate in refine.apply_script allows these and nothing else.
    report = {"before": {}, "after": {}, "applied": {}, "corrected": False, "error": ""}
    for arm in list(bpy.context.scene.objects):
        if arm.type != "ARMATURE":
            continue
        bones = {bone_name(p.name): p for p in arm.pose.bones}
        if not all(n in bones for n in ("hips", "neck", "head")):
            continue
        def world(p):
            return arm.matrix_world @ p.matrix
        forward = world(bones["hips"]).to_3x3() @ Vector((0, 0, 1))
        def angle(n):
            return twist_degrees(world(bones[n]).to_3x3(), forward)
        # Raw angles: measure both before correcting the parent.
        report["before"] = {n: round(angle(n), 1) for n in ("neck", "head")}
        if any(abs(angle(n)) > 120 for n in ("neck", "head")):
            report["error"] = "Implausible head twist exceeds 120 degrees; skipped"
            report["after"] = dict(report["before"])
            return report
        if any(sum(mod.type == "ARMATURE" and mod.object == arm for mod in obj.modifiers) > 1
               for obj in _mesh_objects()):
            report["error"] = "several armature modifiers; head twist left as is"
            report["after"] = dict(report["before"])
            return report
        bpy.ops.object.select_all(action="DESELECT")
        arm.select_set(True)
        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.mode_set(mode="POSE")
        for n in ("neck", "head"):
            twist = angle(n)
            if abs(twist) <= 2:
                continue
            report["applied"][n] = round(twist, 3)
            p = bones[n]
            matrix = world(p)
            axis = (matrix.to_3x3() @ Vector((0, 1, 0))).normalized()
            pivot = matrix.translation
            rotation = (Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(-twist), 4, axis)
                        @ Matrix.Translation(-pivot))
            p.matrix = arm.matrix_world.inverted() @ rotation @ matrix
            bpy.context.view_layer.update()
            report["corrected"] = True
        report["after"] = {n: round(angle(n), 1) for n in ("neck", "head")}
        bpy.ops.object.mode_set(mode="OBJECT")
        if report["corrected"]:
            _bake_pose_as_rest(arm)
        return report
    return report


def _bake_pose_as_rest(arm):
    """Makes the CURRENT pose the rest: the skin is deformed into it (a copy
    of each armature modifier is applied, the live one stays bound) and the
    armature takes it as its new rest. Object mode on return."""
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in _mesh_objects():
        for mod in list(obj.modifiers):
            if mod.type != "ARMATURE" or mod.object != arm:
                continue
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_copy(modifier=mod.name)
            bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.armature_apply(selected=False)
    bpy.ops.object.mode_set(mode="OBJECT")


# --- Posture restore ----------------------------------------------------------
#
# WHY. The rigger (Make-It-Animatable behind the ``mesh-mia`` alias) does not
# only place joints: it RE-POSES the mesh into its own canonical rest pose,
# and its estimate of the input's spine pitch is noisy. Measured over 25 Kira
# deliveries (2026-11-09, stored-mesh sagittal slice centres at 1.70 m): the
# mesher's output has the head 0.3..5.3 cm in front of the armpit-level trunk
# centre and -3.7..+2.8 cm in front of the hips — the rigged result of the SAME
# mesh ranges -0.3..10.6 and -3.3..+16.4. The worst case (base20d5701a) got
# +7.9 cm head-over-trunk and +14.8 cm head-over-hips from the rigger alone;
# the T-pose images and the mesher were upright (image 1.5 cm, mesh 1.6 cm
# head-over-hips). Nothing downstream touches that: the clients' clip
# transplant keeps every joint's own bind relative to the pelvis by design,
# so the figure walks with the head where the rigger left it.
#
# WHAT. The unrigged mesh the rigger was given is the ground truth of the
# posture, so the trunk chain is turned back onto it. Both meshes are read as
# SAGITTAL PROFILES — per height band the centre between the front-most and
# back-most vertex of the central column (|x| < 5.5 % of the height, so arms
# in any pose stay out of it; the min/max centre is far steadier than a
# median, which follows the surface density), relative to the hips band.
#
# IN THE HIPS FRAME. The clients compare rests in the ROOT BONE's frame and
# stand the figure upright as a piece (clipRetarget.ts), so a lean the
# rigger put into the hips bone itself divides out there and must NOT be
# corrected here — correcting it would make the trunk lean BACKWARD once
# the clients level the pelvis. The rigged skin is therefore read with the
# hips bone's pitch taken out (rotated about the medio-lateral axis through
# the hips joint); what remains is exactly the chain-internal lean the
# clients show. base20d5701a: 8.6 deg of hips pitch, and the head still 5.7 cm
# in front of where the source has it.
#
# THE FIT. The forward excess e(z) over the source is sampled on ~30 bands
# from just above the spine joint to the crown and explained by HINGES at the
# chain joints — e(z) = sum_b phi_b * max(0, z - z_b), which is what rotating
# each bone about the medio-lateral axis does to a rigidly skinned column —
# by ridge least squares (lambda * n * |phi|^2). Without the ridge, five
# nearly collinear hinges zig-zag (+8/-8 deg on neighbouring joints for a
# 2-cm lean); with it the lean is spread smoothly down the chain. Two passes,
# because the skin near a joint only partly follows it. Hips are never
# rotated (the legs hang on them).
#
# Reported: ``before``/``after`` = forward excess per named band in cm of a
# 1.70-m figure, ``applied`` = degrees per bone (negative = pitched back),
# exactly what the joint-frame gate of ``refine.apply_script`` is allowed to
# see move; ``hips_pitch_deg`` the attitude that was divided out.

POSTURE_CHAIN = ("spine", "spine1", "spine2", "neck", "head")
POSTURE_BAND_HALF = 0.015        # band half-height, fraction of the height
POSTURE_COLUMN_HALF = 0.055      # central column half-width, fraction of the height
POSTURE_SAMPLE_STEP = 0.012      # band spacing of the fit, fraction of the height
POSTURE_TRIGGER_CM = 1.5         # smallest excess (at 1.70 m) worth a correction
POSTURE_MAX_DEG = 15.0           # a bone pitched more than this is not a posture: skip
POSTURE_RIDGE = 0.003            # lambda of the ridge, per sample (m^2 / rad^2)
POSTURE_PASSES = 2


def _skinned_meshes(arm):
    return [o for o in _mesh_objects()
            if any(m.type == "ARMATURE" and m.object == arm for m in o.modifiers)]


def _world_points(objects, *, evaluated):
    """All vertices of ``objects`` in world space as an (n, 3) array —
    the deformed skin when ``evaluated``."""
    import numpy as np
    dg = bpy.context.evaluated_depsgraph_get() if evaluated else None
    chunks = []
    for obj in objects:
        src = obj.evaluated_get(dg) if evaluated else obj
        me = src.to_mesh() if evaluated else obj.data
        n = len(me.vertices)
        if n:
            buf = np.empty(n * 3, dtype=np.float64)
            me.vertices.foreach_get("co", buf)
            mw = np.array(obj.matrix_world, dtype=np.float64)
            chunks.append(buf.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3])
        if evaluated:
            src.to_mesh_clear()
    return np.concatenate(chunks) if chunks else np.zeros((0, 3))


def _pitch_about_x(points, pivot, degrees):
    """``points`` turned about the medio-lateral axis (+X) through ``pivot``."""
    import numpy as np
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    rot = np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])
    return (points - pivot) @ rot.T + pivot


class _Profile:
    """Sagittal profile of one point cloud: band centres at fractions of its
    height, relative to its hips band."""

    def __init__(self, points, hips_fraction):
        self.points = points
        self.floor = float(points[:, 2].min())
        self.height = float(points[:, 2].max()) - self.floor
        self.x_mid = float((points[:, 0].min() + points[:, 0].max()) / 2.0)
        self.hips = self.centre(hips_fraction)

    def centre(self, fraction):
        """Centre (world y) between the front-most and back-most vertex of
        the central column in the band at ``fraction``; None when empty."""
        import numpy as np
        z = self.floor + fraction * self.height
        half = POSTURE_BAND_HALF * self.height
        mask = ((self.points[:, 2] >= z - half) & (self.points[:, 2] < z + half)
                & (np.abs(self.points[:, 0] - self.x_mid) < POSTURE_COLUMN_HALF * self.height))
        if int(mask.sum()) < 8:
            return None
        ys = self.points[mask, 1]
        return float((ys.min() + ys.max()) / 2.0)

    def relative(self, fraction):
        c = self.centre(fraction)
        return None if c is None or self.hips is None else c - self.hips


def _restore_posture(source_path):
    import numpy as np
    report = {"before": {}, "after": {}, "applied": {}, "corrected": False, "error": "",
              "hips_pitch_deg": None}
    arms = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    if len(arms) != 1:
        report["error"] = "posture needs exactly one armature; left as is"
        return report
    arm = arms[0]
    bones = {bone_name(p.name): p for p in arm.pose.bones}
    if not all(n in bones for n in ("hips",) + POSTURE_CHAIN):
        report["error"] = "posture needs the hips..head chain; left as is"
        return report
    meshes = _skinned_meshes(arm)
    if not meshes:
        report["error"] = "no skinned mesh; posture left as is"
        return report
    if any(sum(mod.type == "ARMATURE" and mod.object == arm for mod in obj.modifiers) > 1
           for obj in meshes):
        report["error"] = "several armature modifiers; posture left as is"
        return report

    # The source mesh: imported, read, removed again.
    before_names = {o.name for o in bpy.data.objects}
    _common.import_model(source_path)
    new_objects = [o for o in bpy.data.objects if o.name not in before_names]
    source_points = _world_points([o for o in new_objects if o.type == "MESH"], evaluated=False)
    for obj in new_objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.context.view_layer.update()
    if len(source_points) < 100:
        report["error"] = "posture source holds no mesh; left as is"
        return report

    def joint(name):
        return np.array(arm.matrix_world @ bones[name].head, dtype=np.float64)

    # The hips bone's pitch: its up axis (+Y of the bone frame) tipped toward
    # the figure's front (-Y of the world) counts positive.
    hips_matrix = (arm.matrix_world @ bones["hips"].matrix).to_3x3()
    up = hips_matrix @ Vector((0, 1, 0))
    hips_pitch = math.degrees(math.atan2(-up.y, up.z))
    report["hips_pitch_deg"] = round(hips_pitch, 1)
    hips_joint = joint("hips")

    def rigged():
        """The deformed skin as the clients see it: hips pitch divided out."""
        return _pitch_about_x(_world_points(meshes, evaluated=True), hips_joint, -hips_pitch)

    def joint_z(name):
        return float(_pitch_about_x(joint(name)[None, :], hips_joint, -hips_pitch)[0, 2])

    first = _Profile(rigged(), 0.0)
    if first.height <= 1e-6:
        report["error"] = "posture: degenerate height; left as is"
        return report
    # Anatomical heights come from the rigged joints, as fractions of the
    # height — fixed now, so every pass and the source read the same bands.
    fraction = {n: (joint_z(n) - first.floor) / first.height for n in ("hips",) + POSTURE_CHAIN}
    head_mid = fraction["head"] + 0.5 * (1.0 - fraction["head"])
    named = {"spine1": fraction["spine1"], "spine2": fraction["spine2"], "neck": fraction["neck"],
             "head": fraction["head"], "head_mid": head_mid}
    samples = np.arange(fraction["spine"] + 0.02, 0.985, POSTURE_SAMPLE_STEP)
    to_cm = 100.0 * 1.70 / first.height

    source = _Profile(source_points, fraction["hips"])
    if source.height <= 1e-6 or source.hips is None:
        report["error"] = "posture source: no hips band; left as is"
        return report
    scale = first.height / source.height

    def excess(profile, fr):
        """Forward excess (metres, +forward = -y) of the rigged profile over
        the source at ``fr`` of the height, both relative to their hips."""
        rig, src = profile.relative(fr), source.relative(fr)
        return None if rig is None or src is None else -(rig - src * scale)

    def named_excess(profile):
        return {band: excess(profile, fr) for band, fr in named.items()}

    def fit(profile):
        """Ridge hinge fit of the sampled excess: degrees per chain bone."""
        rows, ys = [], []
        for fr in samples:
            e = excess(profile, fr)
            if e is None:
                continue
            z = profile.floor + fr * profile.height
            rows.append([max(0.0, z - joint_z(b)) for b in POSTURE_CHAIN])
            ys.append(e)
        if len(ys) < 2 * len(POSTURE_CHAIN):
            return None, len(ys)
        a, y = np.array(rows), np.array(ys)
        phi = np.linalg.solve(a.T @ a + POSTURE_RIDGE * len(ys) * np.eye(len(POSTURE_CHAIN)), a.T @ y)
        return [math.degrees(v) for v in phi], len(ys)

    profile = _Profile(rigged(), fraction["hips"])
    before = named_excess(profile)
    if any(v is None for v in before.values()):
        report["error"] = "posture: a band holds no surface; left as is"
        return report
    report["before"] = {k: round(v * to_cm, 1) for k, v in before.items()}
    report["after"] = dict(report["before"])
    if max(abs(v) for v in before.values()) * to_cm < POSTURE_TRIGGER_CM:
        return report
    phi, count = fit(profile)
    if phi is None:
        report["error"] = f"posture: only {count} usable bands; left as is"
        return report
    if max(abs(v) for v in phi) > POSTURE_MAX_DEG:
        report["error"] = (f"posture: fit wants more than {POSTURE_MAX_DEG:.0f} degrees on one bone "
                           f"({', '.join(f'{b} {v:+.1f}' for b, v in zip(POSTURE_CHAIN, phi))}); left as is")
        return report

    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    applied = {b: 0.0 for b in POSTURE_CHAIN}
    for step_no in range(POSTURE_PASSES):
        if step_no:
            phi, _ = fit(_Profile(rigged(), fraction["hips"]))
            if phi is None:
                break
        for bone, degrees in zip(POSTURE_CHAIN, phi):
            if abs(degrees) < 0.2:
                continue
            p = bones[bone]
            matrix = arm.matrix_world @ p.matrix
            pivot = matrix.translation
            # About the medio-lateral axis (+X, the figure faces -Y): a positive
            # angle moves the skin above the pivot FORWARD, so pitch by -phi.
            rotation = (Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(-degrees), 4, Vector((1, 0, 0)))
                        @ Matrix.Translation(-pivot))
            p.matrix = arm.matrix_world.inverted() @ rotation @ matrix
            bpy.context.view_layer.update()
            applied[bone] += -degrees
    bpy.ops.object.mode_set(mode="OBJECT")
    report["applied"] = {b: round(v, 3) for b, v in applied.items() if abs(v) >= 0.2}
    after = named_excess(_Profile(rigged(), fraction["hips"]))
    report["after"] = {k: round((v if v is not None else 0.0) * to_cm, 1) for k, v in after.items()}
    if report["applied"]:
        report["corrected"] = True
        _bake_pose_as_rest(arm)
    return report


def _mesh_objects():
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def _world_bounds(objects):
    lo = Vector((float("inf"),) * 3)
    hi = Vector((float("-inf"),) * 3)
    found = False
    for obj in objects:
        for corner in obj.bound_box:
            p = obj.matrix_world @ Vector(corner)
            for i in range(3):
                lo[i] = min(lo[i], p[i])
                hi[i] = max(hi[i], p[i])
            found = True
    return (lo, hi) if found else None


def _tris():
    total = 0
    for obj in _mesh_objects():
        me = obj.data
        try:
            me.calc_loop_triangles()
            total += len(me.loop_triangles)
        except Exception:
            total += sum(max(0, len(p.vertices) - 2) for p in me.polygons)
    return total


def _joints():
    return sum(len(o.data.bones) for o in bpy.context.scene.objects
               if o.type == "ARMATURE")


# The head joint's anatomical share of standing height, and the band below
# which a bounding box is considered inflated by headwear — both derived from
# the 2026-08-07 store survey (see the module docstring).
HEAD_SHARE = 0.875
HEAD_RATIO_TRUSTED = 0.80


def _head_joints():
    """(crown_z, head_z) world heights — either may be None.

    ``HeadTop_End`` is the exact crown where a rig has one; ``Head`` (the
    skull base) is what the gateway's 52-joint rigs end at and feeds the
    estimate."""
    crown = head = None
    for arm in bpy.context.scene.objects:
        if arm.type != "ARMATURE":
            continue
        for bone in arm.data.bones:
            name = bone.name.lower().replace(":", "").replace("_", "")
            z = (arm.matrix_world @ bone.head_local).z
            if "headtopend" in name:
                crown = z
            elif name.endswith("head"):
                head = z
    return crown, head


def _snapshot(bounds):
    lo, hi = bounds
    return {
        "dims_m": [round(hi[i] - lo[i], 4) for i in range(3)],
        "center_xy": [round((hi[0] + lo[0]) / 2, 4),
                      round((hi[1] + lo[1]) / 2, 4)],
        "min_z": round(lo[2], 4),
        "tris": _tris(),
        "joints": _joints(),
    }


def normalize(args):
    src = args["inputs"].get("model")
    if not src:
        raise ValueError("no input 'model'")
    target = float(args["params"].get("target_height_m") or 0)
    if target <= 0:
        raise ValueError("target_height_m must be > 0")

    _common.reset_scene()
    _common.import_model(src)

    try:
        head_twist = _untwist_head()
    except Exception as exc:
        if bpy.context.object and bpy.context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        _common.reset_scene()
        _common.import_model(src)
        head_twist = {"before": {}, "after": {}, "corrected": False, "error": str(exc)}

    posture = None
    if args["inputs"].get("source"):
        try:
            posture = _restore_posture(args["inputs"]["source"])
        except Exception as exc:
            # A half-turned chain must not leave this script: start over with
            # the untwist alone and report the posture step as failed.
            if bpy.context.object and bpy.context.object.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            _common.reset_scene()
            _common.import_model(src)
            try:
                head_twist = _untwist_head()
            except Exception as twist_exc:
                head_twist = {"before": {}, "after": {}, "corrected": False, "error": str(twist_exc)}
            posture = {"before": {}, "after": {}, "applied": {}, "corrected": False, "error": str(exc)}

    bounds = _world_bounds(_mesh_objects())
    if not bounds:
        raise ValueError("model contains no mesh")
    before = _snapshot(bounds)
    lo, hi = bounds

    crown, head = _head_joints()
    box_height = hi.z - lo.z
    if crown is not None and crown > lo.z + 1e-6:
        basis, height_now = "crown", crown - lo.z
    elif (head is not None and box_height > 1e-6
          and (head - lo.z) / box_height < HEAD_RATIO_TRUSTED):
        # The box is taller than anatomy allows — headwear. Estimate the
        # crown from the head joint instead of letting the box shrink the
        # body (the Ondina case: box 2.33 m, head at 0.65 of it).
        basis, height_now = "head-est", (head - lo.z) / HEAD_SHARE
    else:
        basis, height_now = "bbox", box_height
    if height_now <= 1e-6:
        raise ValueError("model has no measurable height")
    scale = target / height_now
    if not 0.001 <= scale <= 1000:
        raise ValueError(f"refusing implausible scale {scale:.5f} "
                         f"(height {height_now:.4f} m -> {target:.4f} m)")

    # Scale and ground the TOP-LEVEL objects: children follow their parents,
    # and touching both would apply the factor twice.
    roots = [o for o in bpy.context.scene.objects if o.parent is None]
    for obj in roots:
        obj.matrix_world = Matrix.Scale(scale, 4) @ obj.matrix_world
    bpy.context.view_layer.update()
    lo, hi = _world_bounds(_mesh_objects())
    shift = Vector(((hi.x + lo.x) / -2, (hi.y + lo.y) / -2, -lo.z))
    for obj in roots:
        obj.matrix_world = Matrix.Translation(shift) @ obj.matrix_world
    bpy.context.view_layer.update()

    # Bake the transforms into the data. Selection-based: the operator wants
    # the objects selected and one active.
    bpy.ops.object.select_all(action="SELECT")
    if roots:
        bpy.context.view_layer.objects.active = roots[0]
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.context.view_layer.update()

    limb_weights = None
    if args["params"].get("repair_limb_weights", False):
        sys.path.insert(0, _SCRIPTS_DIR)
        try:
            from _limb_weights import repair
            limb_weights = repair()
        finally:
            sys.path.remove(_SCRIPTS_DIR)

    after = _snapshot(_world_bounds(_mesh_objects()))

    out_dir = Path(args["out_dir"])
    name = Path(src).name
    path = out_dir / name
    if Path(src).suffix.lower() in (".glb", ".gltf"):
        bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB")
    else:
        bpy.ops.export_scene.fbx(filepath=str(path))

    data = {
        "head_twist": head_twist,
        "height_basis": basis,
        "scale": round(scale, 6),
        "target_height_m": target,
        "before": before,
        "after": after,
    }
    if limb_weights is not None:
        data["limb_weights"] = limb_weights
    if posture is not None:
        data["posture"] = posture
    return data, {"model": str(path)}


_common.main(normalize)
