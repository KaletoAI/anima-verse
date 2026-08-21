"""Retargets CMU ASF/AMC motion onto the Mixamo rig and writes clip FBX files.

One run produces ONE clip kind: either a solo clip (one ASF/AMC) or a PAIR
(two ASF/AMC recorded together, written as ``<kind>__a`` / ``<kind>__b``).
Invoked through ``app.blender.runner.run("cmu_clip", inputs=…, params=…)``:

    inputs   rig            FBX with the Mixamo skeleton to drive
                            (``shared/models/figure/x-bot.fbx``)
             asf, amc       the solo take, or
             asf_a, amc_a, asf_b, amc_b   the two takes of a pair
    params   kind           file stem, e.g. "handshake"
             fps            output frame rate (the library is 30 fps)
             start_s        first second of the take to keep (default 0)
             end_s          last second (default: whole take)
             anchor_s       PAIR ONLY — the second whose geometry defines the
                            anchor frame (default: when the roots are closest)
             in_place       SOLO ONLY — strip the horizontal root travel
                            (Mixamo "In Place")
             loop_s         SOLO ONLY — cut the take to its best-closing
                            window of at least this many seconds and ease
                            the tail into the head (a seamless cycle)
             source_takes   names of the source takes, for the sidecar credit

The FBX files and the ``<kind>.json`` sidecar land in the runner's out dir.

How the retarget works
----------------------
CMU's rest pose is a T-pose with every bone frame aligned to the WORLD axes, so
a bone's world rotation at a frame IS its rotation away from rest. The Mixamo
rig's rest pose is a T-pose too, in the same Y-up / +X-left / +Z-forward space.
So for every mapped bone the pose matrix in armature space is

    P_i = R_cmu_i(t) · A_i · R_i

with ``R_i`` the Mixamo rest matrix, and ``A_i`` the fixed rotation that turns
the Mixamo rest direction of the bone onto the CMU rest direction — applied to
the limbs only (``ALIGN_BONES``: CMU's T-pose splays the legs ~20°), identity
everywhere else, because clavicles and feet are DIFFERENT segments on the two
skeletons and aligning them shrugged the shoulders and kinked the feet.
Rotation deltas carry the twist with them — unlike an aim-only retarget, the
forearm and hips keep their roll. Unmapped bones (fingers, eyes, end bones)
get NO track at all, like in Mixamo clips, so a model keeps its own finger
pose. The hips take the CMU root POSITION as well.

Frames of reference the clips are written in
--------------------------------------------
* SOLO: root at the origin in XZ at the first kept frame, facing +Z; with
  ``in_place`` the horizontal root travel is removed entirely.
* PAIR: a common ANCHOR frame for both files — origin at the XZ midpoint of
  the two roots at ``anchor_s``, +X pointing from A to B. Both clips keep their
  full root motion inside that frame, so A and B stay where they were
  recorded relative to each other; a client places the anchor in the world
  and plays both files in lockstep. The sidecar records the geometry.
* Floor: the lowest joint over the whole (pair) take sits at y = 0.

Units stay Mixamo's: centimetres in armature space, the armature object
carrying the usual 0.01 scale / +90° X, which is what the library's clips and
``x-bot.fbx`` carry.
"""
import json
import math
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
import _cmu                                                   # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bpy                                                    # noqa: E402
from mathutils import Matrix, Vector                          # noqa: E402

# Mixamo bone → CMU bone. Spine2 takes the thorax so the shoulders sit on the
# thorax frame like in the source; Head takes upperneck (CMU's "head" bone is
# the skull cap and carries no dof of its own).
BONE_MAP = {
    "Hips": "root",
    "Spine": "lowerback", "Spine1": "upperback", "Spine2": "thorax",
    "Neck": "lowerneck", "Head": "upperneck",
    "LeftShoulder": "lclavicle", "LeftArm": "lhumerus",
    "LeftForeArm": "lradius", "LeftHand": "lhand",
    "RightShoulder": "rclavicle", "RightArm": "rhumerus",
    "RightForeArm": "rradius", "RightHand": "rhand",
    "LeftUpLeg": "lfemur", "LeftLeg": "ltibia",
    "LeftFoot": "lfoot", "LeftToeBase": "ltoes",
    "RightUpLeg": "rfemur", "RightLeg": "rtibia",
    "RightFoot": "rfoot", "RightToeBase": "rtoes",
}
PREFIX = "mixamorig:"
# Bones whose CMU and Mixamo rest DIRECTIONS describe the same segment, so the
# fixed rest alignment A_i (Mixamo rest dir → CMU rest dir) is meaningful:
# CMU's T-pose splays the legs ~20° and the arms match. NOT aligned:
#  * clavicles — CMU's runs chest centre → shoulder, Mixamo's neck base →
#    arm; a 20° difference that is anatomy, not pose (aligning it shrugged
#    every shoulder up, 2026-08-21 finding);
#  * feet/toes — CMU's foot is ankle → ball at 15°, Mixamo's at ~33°; aligning
#    lifted the ball and kinked the toes up (same finding);
#  * spine/neck/head — the differences are ~1° and the torso twist is better
#    kept exactly as the actor's.
# Those bones take the actor's rotation DELTA on the Mixamo rest unchanged.
ALIGN_BONES = {"LeftUpLeg", "RightUpLeg", "LeftLeg", "RightLeg",
               "LeftArm", "RightArm", "LeftForeArm", "RightForeArm",
               "LeftHand", "RightHand"}


def _m3(m):
    """_cmu 3x3 list → mathutils Matrix (3x3)."""
    return Matrix(m)


def _rot_between(a: Vector, b: Vector) -> Matrix:
    """Shortest rotation taking direction a onto direction b."""
    a = a.normalized()
    b = b.normalized()
    return a.rotation_difference(b).to_matrix()


def _ry(theta: float) -> Matrix:
    return Matrix.Rotation(theta, 3, "Y")


def _load_rig(path: str):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=path, global_scale=1.0)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    for o in list(bpy.data.objects):
        if o is not arm:
            bpy.data.objects.remove(o, do_unlink=True)
    arm.animation_data_clear()
    if not any(b.name.startswith(PREFIX) for b in arm.data.bones):
        raise ValueError("rig carries no mixamorig bones")
    return arm


class _Take:
    """One ASF/AMC pair solved to world poses, already resampled."""

    def __init__(self, entry, fps, start_s, end_s):
        self.role = entry.get("role", "")
        self.sk, frames = _cmu.load_clip(Path(entry["asf"]), Path(entry["amc"]))
        n = len(frames)
        first = int(round(start_s * _cmu.CMU_FPS))
        last = n if end_s is None else min(n, int(round(end_s * _cmu.CMU_FPS)))
        step = _cmu.CMU_FPS / fps
        idx = []
        t = float(first)
        while t < last - 1e-6:
            idx.append(int(round(t)))
            t += step
        self.poses = [_cmu.solve_frame(self.sk, frames[i]) for i in idx]
        self.source_frames = n

    def root_xz(self, i):
        p = self.poses[i].pos["root"]
        return (p[0], p[2])

    def lowest(self):
        return min(_cmu.lowest_point_cm(self.sk, p) for p in self.poses)


def _apply_rigid(take: _Take, theta: float, shift, floor: float, in_place: bool):
    """Rotates every pose about Y by theta, then translates by ``shift``
    (x, z) and lifts by ``-floor``; with in_place the root XZ is pinned."""
    r = _ry(theta)
    r3 = [[r[i][j] for j in range(3)] for i in range(3)]
    for pose in take.poses:
        for name in list(pose.rot):
            pose.rot[name] = _cmu.mat_mul(r3, pose.rot[name])
            p = _cmu.mat_vec(r3, pose.pos[name])
            pose.pos[name] = (p[0] + shift[0], p[1] - floor, p[2] + shift[1])
    if in_place:
        for pose in take.poses:
            rx, _, rz = pose.pos["root"]
            for name in list(pose.pos):
                p = pose.pos[name]
                pose.pos[name] = (p[0] - rx, p[1], p[2] - rz)


LOOP_BLEND_FRAMES = 8
LOOP_BONES = ("lfemur", "ltibia", "lfoot", "rfemur", "rtibia", "rfoot", "lhumerus",
              "lradius", "rhumerus", "rradius", "lowerback", "thorax", "upperneck")


def _pose_distance(sk, a, b) -> float:
    """How far two solved frames are apart: summed rotation angle of the
    limb/torso bones (radians) plus the hips height difference (metres)."""
    d = 0.0
    for name in LOOP_BONES:
        if name not in a.rot:
            continue
        ra, rb = a.rot[name], b.rot[name]
        # angle of ra^T rb from its trace
        tr = sum(ra[i][j] * rb[i][j] for i in range(3) for j in range(3))
        d += math.acos(max(-1.0, min(1.0, (tr - 1.0) / 2.0)))
    d += abs(a.pos["root"][1] - b.pos["root"][1]) / 100.0
    return d


def _cut_loop(take, fps, min_s):
    """Trims the take to the window [i, j) whose end pose is closest to its
    start pose — the best place to cut a cycle — with at least ``min_s`` of
    motion in it. The last LOOP_BLEND_FRAMES keys are then eased into the
    first key at bake time (``_bake`` ``loop``), so the clip closes without
    a visible jump. Returns the chosen (i, j, distance)."""
    n = len(take.poses)
    min_len = max(2, int(round(min_s * fps)))
    if n <= min_len + 1:
        return 0, n, None
    best = None
    # every start i, every end j with the minimum length; O(n²) on a few
    # hundred frames is instant
    for i in range(0, n - min_len):
        for j in range(i + min_len, n):
            d = _pose_distance(take.sk, take.poses[i], take.poses[j])
            if best is None or d < best[2]:
                best = (i, j, d)
    i, j, d = best
    take.poses = take.poses[i:j]
    return i, j, d


def _frame_takes(takes, args):
    """Puts the takes into the clip's frame of reference; returns sidecar geometry."""
    floor = min(t.lowest() for t in takes)
    if len(takes) == 1:
        take = takes[0]
        fx, fz = _cmu.forward_xz(take.poses[0])
        # Rotate so the root faces +Z at the first frame.
        theta = math.atan2(fx, fz)
        r = _ry(-theta)
        x0, z0 = take.root_xz(0)
        p = r @ Vector((x0, 0.0, z0))
        _apply_rigid(take, -theta, (-p.x, -p.z), floor, bool(args.get("in_place")))
        return {"floor_shift_cm": round(-floor, 2), "in_place": bool(args.get("in_place"))}

    a = next(t for t in takes if t.role == "a")
    b = next(t for t in takes if t.role == "b")
    n = min(len(a.poses), len(b.poses))
    a.poses = a.poses[:n]
    b.poses = b.poses[:n]
    fps = args.get("fps", 30)
    if args.get("anchor_s") is not None:
        ai = min(n - 1, int(round(float(args["anchor_s"]) * fps)))
    else:
        ai = min(range(n), key=lambda i: math.dist(a.root_xz(i), b.root_xz(i)))
    ax, az = a.root_xz(ai)
    bx, bz = b.root_xz(ai)
    mid = ((ax + bx) / 2, (az + bz) / 2)
    # Angle that turns the A→B direction onto +X.
    theta = math.atan2(bz - az, bx - ax)
    r = _ry(theta)
    m = r @ Vector((mid[0], 0.0, mid[1]))
    for t in (a, b):
        _apply_rigid(t, theta, (-m.x, -m.z), floor, False)
    dist = math.dist(a.root_xz(ai), b.root_xz(ai))
    return {
        "anchor_frame": ai,
        "anchor_s": round(ai / fps, 3),
        "root_distance_m": round(dist / 100, 3),
        "floor_shift_cm": round(-floor, 2),
        "roles": {
            "a": {"start_xz_m": [round(v / 100, 3) for v in a.root_xz(0)],
                  "anchor_xz_m": [round(v / 100, 3) for v in a.root_xz(ai)]},
            "b": {"start_xz_m": [round(v / 100, 3) for v in b.root_xz(0)],
                  "anchor_xz_m": [round(v / 100, 3) for v in b.root_xz(ai)]},
        },
    }


# The floor is the lowest point of the WHOLE body, not of the feet: a lying
# or kneeling take has its head, hands or knees below the soles.
FLOOR_BONES = tuple(BONE_MAP) + ("LeftToe_End", "RightToe_End")


def _solve(arm, take: _Take):
    """Pose matrices (armature space, cm) of every bone for every frame, and
    per frame the lowest foot/toe joint of the RIG — the rig's legs are not
    the actor's, so the floor has to be measured on the rig."""
    bones = arm.data.bones
    order = [b for b in bones if b.parent is None]
    seen = []
    while order:
        b = order.pop(0)
        seen.append(b)
        order = list(b.children) + order
    rest = {b.name: b.matrix_local.copy() for b in seen}
    # Fixed rest alignment per mapped bone (Mixamo rest dir → CMU rest dir).
    align = {}
    for b in seen:
        short = b.name[len(PREFIX):] if b.name.startswith(PREFIX) else b.name
        cmu_name = BONE_MAP.get(short)
        if not cmu_name or cmu_name not in take.sk.bones:
            continue
        if cmu_name == "root" or short not in ALIGN_BONES:
            align[b.name] = (cmu_name, Matrix.Identity(3))
            continue
        mix_dir = (b.tail_local - b.head_local)
        cmu_dir = Vector(take.sk.bones[cmu_name].direction)
        if mix_dir.length < 1e-6 or cmu_dir.length < 1e-6:
            align[b.name] = (cmu_name, Matrix.Identity(3))
        else:
            align[b.name] = (cmu_name, _rot_between(mix_dir, cmu_dir))

    # Standing leg length of BOTH skeletons from their rest geometry (hips
    # joint to ankle, vertical): the hips translation is scaled by the ratio.
    # Measured on the rest, never on the take — a take that only sits or
    # kneels has no standing frame to measure on (first version did that and
    # put a sitter's hips at 0.95 m).
    # Bone LENGTHS along the chain on both sides (CMU's rest splays the legs,
    # so a vertical projection would understate the actor's leg).
    _chain = [bones[PREFIX + n].head_local for n in ("Hips", "LeftUpLeg", "LeftLeg", "LeftFoot")]
    rig_leg = sum((_chain[i + 1] - _chain[i]).length for i in range(3))
    act_leg = sum(take.sk.bones[n].length for n in ("lhipjoint", "lfemur", "ltibia")) * take.sk.unit_cm
    leg_ratio = rig_leg / act_leg if act_leg > 1 else 1.0
    frames = []
    lowest_per_frame = []
    for pose in take.poses:
        P = {}
        frame_low = math.inf
        for b in seen:
            R = rest[b.name]
            if b.name in align:
                cmu_name, A = align[b.name]
                rot = _m3(pose.rot[cmu_name]) @ A @ R.to_3x3()
                if cmu_name == "root":
                    pos = Vector(pose.pos["root"])
                else:
                    # Position follows the Mixamo hierarchy (bone lengths of
                    # the rig, not of the actor).
                    parent = P[b.parent.name]
                    pos = (parent @ rest[b.parent.name].inverted() @ R).to_translation()
                M = rot.to_4x4()
                M.translation = pos
            else:
                if b.parent is None:
                    M = R.copy()
                else:
                    M = P[b.parent.name] @ rest[b.parent.name].inverted() @ R
            P[b.name] = M
            short = b.name[len(PREFIX):] if b.name.startswith(PREFIX) else b.name
            if short in FLOOR_BONES:
                frame_low = min(frame_low, M.translation.y)
        frames.append(P)
        lowest_per_frame.append(frame_low)
    return [b.name for b in seen], rest, frames, lowest_per_frame, leg_ratio


def _bake(arm, take: _Take, fps: int, solved, floor_cm: float,
          hips_scale: float = 1.0, offset=(0.0, 0.0), loop: bool = False):
    """Writes the solved frames into a fresh action on ``arm``.

    Every frame is moved as a whole (rotations untouched): the hips height is
    multiplied by ``hips_scale`` (the rig's leg length over the actor's — a
    squat then takes the rig as deep as it took the actor, instead of leaving
    the rig's longer legs dangling in the air), the whole take is shifted by
    ``offset`` (x, z) cm (the pair's contact fit) and lifted by ``-floor_cm``
    so the planted foot touches y = 0."""
    seen, rest, frames, _low = solved
    action = bpy.data.actions.new(name=f"Armature|{take.role or 'solo'}")
    arm.animation_data_create()
    arm.animation_data.action = action
    curves = {}

    def fc(path, index):
        key = (path, index)
        if key not in curves:
            curves[key] = action.fcurves.new(data_path=path, index=index)
        return curves[key]

    nframes = len(frames)
    hips_name = PREFIX + "Hips"
    keys = {}   # (path, index) -> list of values
    for P in frames:
        hips_y = P[hips_name].translation.y
        lift = Matrix.Translation(Vector((offset[0], hips_y * (hips_scale - 1.0) - floor_cm,
                                          offset[1])))
        for b in seen:
            R = rest[b.name]
            M = lift @ P[b.name]
            if b.parent is None:
                basis = R.inverted() @ M
            else:
                basis = (lift @ P[b.parent.name] @ rest[b.parent.name].inverted() @ R).inverted() @ M
            q = basis.to_quaternion()
            path = f'pose.bones["{b.name}"].rotation_quaternion'
            for i, v in enumerate((q.w, q.x, q.y, q.z)):
                keys.setdefault((path, i), []).append(v)
            if b.parent is None:
                t = basis.to_translation()
                lpath = f'pose.bones["{b.name}"].location'
                for i, v in enumerate((t.x, t.y, t.z)):
                    keys.setdefault((lpath, i), []).append(v)
    if loop and nframes > 2 * LOOP_BLEND_FRAMES:
        # Ease the tail into the head: the last K keys blend towards key 0
        # (quaternions slerped per bone, the hips location lerped), so frame
        # n-1 → frame 0 is continuous when the clip repeats.
        K = LOOP_BLEND_FRAMES
        from mathutils import Quaternion
        by_path = {}
        for (path, index), vals in keys.items():
            by_path.setdefault(path, {})[index] = vals
        for path, comps in by_path.items():
            if path.endswith("rotation_quaternion"):
                q0 = Quaternion((comps[0][0], comps[1][0], comps[2][0], comps[3][0]))
                for k in range(K):
                    fi = nframes - K + k
                    w = (k + 1) / (K + 1)
                    q = Quaternion((comps[0][fi], comps[1][fi], comps[2][fi], comps[3][fi]))
                    qb = q.slerp(q0, w)
                    for c, v in enumerate((qb.w, qb.x, qb.y, qb.z)):
                        comps[c][fi] = v
            else:
                for c in comps:
                    v0 = comps[c][0]
                    for k in range(K):
                        fi = nframes - K + k
                        w = (k + 1) / (K + 1)
                        comps[c][fi] = comps[c][fi] * (1 - w) + v0 * w
    for (path, index), vals in keys.items():
        curve = fc(path, index)
        curve.keyframe_points.add(nframes)
        flat = []
        for fi, v in enumerate(vals):
            flat.extend((fi + 1, v))
        curve.keyframe_points.foreach_set("co", flat)
        curve.update()
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
    scene = bpy.context.scene
    scene.render.fps = fps
    scene.frame_start = 1
    scene.frame_end = nframes
    return action


def _patch_fbx_track_shape():
    """Makes the FBX exporter write the MIXAMO track shape: every bone's
    rotation curve (all samples) plus the hips translation — and nothing else.

    Blender's baker keys location, rotation and scale of every bone and then
    drops any curve with fewer than two distinct samples; a dropped curve
    falls back to the bone's rest value on import. Two things go wrong with
    that for a clip library: (1) the constant location/scale curves that DO
    survive (float noise keeps them alive) are bone offsets in centimetres —
    a consumer applying every track (the admin preview) smears them over a
    metre-scaled model ("a stick figure is all that is left of the mesh",
    2026-08-21); (2) a constant-but-NOT-rest rotation is lost entirely — the
    clavicles have no dof in CMU data, so their whole curve is the 20° rest
    alignment, and dropping it drops the shoulders. The only reliable place to
    decide per curve is the exporter's own write mask, so it is set here:
    rotation curves are always kept in full, the hips translation too, every
    other translation and every scale curve is discarded.
    """
    import io_scene_fbx.fbx_utils as fu
    if getattr(fu.AnimationCurveNodeWrapper, "_anima_patched", False):
        return
    orig = fu.AnimationCurveNodeWrapper.simplify

    def simplify(self, fac, step, force_keep=False):
        orig(self, fac, step, force_keep)
        mask = self._frame_write_mask_array
        if mask is None:
            return
        group = self.fbx_group[0]
        key = str(self.elem_keys[0])
        is_bone = PREFIX in key or PREFIX.rstrip(":") in key
        # Only the bones the actor data drives get a track. An unmapped bone
        # (fingers, eyes, toe/head ends) must NOT be written at rest: a
        # consumer would then overwrite its own model's finger pose with the
        # clip skeleton's — Mixamo clips carry no finger tracks either.
        mapped = is_bone and any(
            key.endswith(PREFIX + m) or key.endswith(PREFIX.rstrip(":") + m)
            or (PREFIX + m + "|") in key for m in BONE_MAP)
        if mapped and group == "Lcl Rotation":
            mask[:] = True
        elif mapped and group == "Lcl Translation" and key.endswith("Hips"):
            mask[:] = True
        else:
            mask[:] = False

    fu.AnimationCurveNodeWrapper.simplify = simplify
    fu.AnimationCurveNodeWrapper._anima_patched = True


def _export(arm, path: Path):
    _patch_fbx_track_shape()
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    # Track shape: see _patch_fbx_track_shape — the exporter's own options
    # cannot express "rotations + hips translation only".
    bpy.ops.export_scene.fbx(
        filepath=str(path), use_selection=True, object_types={"ARMATURE"},
        add_leaf_bones=False, bake_anim=True, bake_anim_use_all_bones=False,
        bake_anim_use_nla_strips=False, bake_anim_use_all_actions=False,
        bake_anim_force_startend_keying=True, bake_anim_simplify_factor=0.0,
        armature_nodetype="NULL", axis_forward="-Z", axis_up="Y",
    )


def _clip_entries(args):
    """The takes from the runner's input slots: solo (asf/amc) or pair."""
    inputs = args.get("inputs") or {}
    if "asf" in inputs:
        return [{"asf": inputs["asf"], "amc": inputs["amc"], "role": ""}]
    return [{"asf": inputs[f"asf_{r}"], "amc": inputs[f"amc_{r}"], "role": r}
            for r in ("a", "b")]


def run(job):
    args = dict(job.get("params") or {})
    args["clips"] = _clip_entries(job)
    args["rig"] = (job.get("inputs") or {})["rig"]
    args["out_dir"] = job["out_dir"]
    fps = int(args.get("fps", 30))
    start_s = float(args.get("start_s", 0) or 0)
    end_s = args.get("end_s")
    takes = [_Take(e, fps, start_s, None if end_s is None else float(end_s))
             for e in args["clips"]]
    loop_min = args.get("loop_s")
    loop = loop_min is not None and len(takes) == 1
    loop_info = None
    if loop:
        i, j, d = _cut_loop(takes[0], fps, float(loop_min))
        loop_info = {"min_s": float(loop_min), "cut_frames": [i, j],
                     "cut_s": [round(i / fps, 3), round(j / fps, 3)],
                     "seam_distance": None if d is None else round(d, 3),
                     "blend_frames": LOOP_BLEND_FRAMES}
    geometry = _frame_takes(takes, args)
    if loop_info:
        geometry["loop"] = loop_info
    out_dir = Path(args["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    kind = args["kind"]
    outputs = {}
    nframes = min(len(t.poses) for t in takes)
    # Solve every take first: a pair shares ONE floor, measured on the rig.
    solved = []
    for take in takes:
        arm = _load_rig(args["rig"])
        solved.append(_solve(arm, take))
    hips_name = PREFIX + "Hips"
    # LEG RATIO per take (from the rest geometry, see _solve): the rig's leg
    # over the actor's. The hips translation is multiplied by it, so a deep knee bend
    # lowers the rig as far as it lowered the actor (salsa finding: the rig,
    # legs ~9 % longer, kept its hips at 0.59 m where the actor dipped to
    # 0.45 m — and its feet came off the floor, "sitting in the air").
    scales = [sol[4] for sol in solved]
    geometry["hips_scale"] = [round(k, 4) for k in scales]
    # CONTACT FIT (pair): at the anchor frame the two closest hands of the
    # ACTORS are this far apart; the rig's arms are not the actors', so the
    # same pose leaves its hands farther apart (handshake: 25 cm instead of
    # 11). Both halves are shifted towards each other along the hand-to-hand
    # line by half the difference — a constant offset on the whole take, so
    # nothing else changes.
    offsets = [(0.0, 0.0) for _ in takes]
    if len(takes) == 2:
        ai = geometry["anchor_frame"]
        a_idx, b_idx = (0, 1) if takes[0].role == "a" else (1, 0)
        # A contact is a HAND on something: the other hand (handshake), a
        # shoulder (comfort), the head or the hips (an embrace) — the closest
        # such pair of the actors at the anchor frame is taken.
        hands = {"LeftHand": "lhand", "RightHand": "rhand"}
        targets = {**hands, "LeftArm": "lhumerus", "RightArm": "rhumerus",
                   "Head": "head", "Hips": "root"}
        best = None
        for ha, ca in targets.items():
            for hb, cb in targets.items():
                if ha not in hands and hb not in hands:
                    continue
                pa = Vector(takes[a_idx].poses[ai].pos[ca])
                pb = Vector(takes[b_idx].poses[ai].pos[cb])
                d = (pa - pb).length
                if best is None or d < best[0]:
                    best = (d, ha, hb)
        cmu_d, ha, hb = best
        ra = solved[a_idx][2][ai][PREFIX + ha].translation
        rb = solved[b_idx][2][ai][PREFIX + hb].translation
        rig_d = (ra - rb).length
        v = Vector((rb.x - ra.x, 0.0, rb.z - ra.z))
        delta = rig_d - cmu_d
        if v.length > 1e-6 and delta > 0:
            v.normalize()
            offsets[a_idx] = (v.x * delta / 2, v.z * delta / 2)
            offsets[b_idx] = (-v.x * delta / 2, -v.z * delta / 2)
        geometry["contact"] = {"hands": [ha, hb], "actor_distance_m": round(cmu_d / 100, 3),
                               "rig_distance_m": round(rig_d / 100, 3),
                               "shift_m": round(max(delta, 0.0) / 100, 3)}
        for role, off in (("a", offsets[a_idx]), ("b", offsets[b_idx])):
            r = geometry["roles"][role]
            r["start_xz_m"] = [round(r["start_xz_m"][0] + off[0] / 100, 3),
                               round(r["start_xz_m"][1] + off[1] / 100, 3)]
            r["anchor_xz_m"] = [round(r["anchor_xz_m"][0] + off[0] / 100, 3),
                                round(r["anchor_xz_m"][1] + off[1] / 100, 3)]
        ga, gb = geometry["roles"]["a"]["anchor_xz_m"], geometry["roles"]["b"]["anchor_xz_m"]
        geometry["root_distance_m"] = round(math.dist(ga, gb), 3)
    # The floor is the MEDIAN of the per-frame lowest foot point (after the
    # hips scaling): while walking one foot is always planted, so that median
    # is the planted foot's height; the absolute minimum would be a single
    # toe-off dip and leave the standing foot hovering (8-9 cm, handshake).
    lows = sorted(low + P[hips_name].translation.y * (k - 1.0)
                  for (_n, _r, frames, lows_t, _k), k in zip(solved, scales)
                  for P, low in zip(frames, lows_t) if math.isfinite(low))
    floor_cm = lows[len(lows) // 2] if lows else 0.0
    geometry["rig_floor_shift_cm"] = round(-floor_cm, 2)
    geometry["rig_floor_min_cm"] = round(lows[0] - floor_cm, 2) if lows else 0.0
    for take, sol, k, off in zip(takes, solved, scales, offsets):
        arm = _load_rig(args["rig"])
        # The solve ran on an earlier load of the rig (gone with the scene
        # reset) — bones are carried by NAME and re-resolved here.
        seen, rest, frames, low, _ratio = sol
        seen = [arm.data.bones[n] for n in seen]
        _bake(arm, take, fps, (seen, rest, frames, low), floor_cm, k, off, loop)
        stem = f"{kind}__{take.role}" if take.role else kind
        path = out_dir / f"{stem}.fbx"
        _export(arm, path)
        outputs[stem] = str(path)
    sidecar = {
        "kind": kind,
        "pair": len(takes) == 2,
        "roles": ["a", "b"] if len(takes) == 2 else [],
        "fps": fps,
        "frames": nframes,
        "duration_s": round(nframes / fps, 3),
        "geometry": geometry,
        "source": {
            "database": "CMU Graphics Lab Motion Capture Database (mocap.cs.cmu.edu)",
            "takes": list(args.get("source_takes") or []),
            "credit": "The data used in this project was obtained from mocap.cs.cmu.edu. "
                      "The database was created with funding from NSF EIA-0196217.",
        },
    }
    side = out_dir / f"{kind}.json"
    side.write_text(json.dumps(sidecar, indent=1), encoding="utf-8")
    outputs["sidecar"] = str(side)
    return sidecar, outputs


if __name__ == "__main__":
    _common.main(run)
