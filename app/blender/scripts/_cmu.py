"""ASF/AMC reader for the CMU Graphics Lab Motion Capture Database.

Standard library only: this module is imported both by the bpy script that
retargets a clip onto the Mixamo rig (Blender's own Python, no venv) and by
the smoke checks under ``scripts/`` (no Blender). So the tiny bit of matrix
math it needs lives here instead of in ``mathutils``/``numpy``.

Format recap (mocap.cs.cmu.edu, "ASF/AMC"):

* ``.asf`` is the skeleton: a ``:root`` with translation+rotation, then one
  ``:bonedata`` block per bone with ``direction`` (unit vector, WORLD axes),
  ``length`` (in ASF units), ``axis`` (Euler angles that define the bone's
  local rotation frame ``C``) and ``dof`` (which channels the AMC carries).
  ``:hierarchy`` lists parent → children. The REST pose has every bone
  oriented to the world axes — the skeleton is a T-pose drawn from the
  ``direction`` vectors alone.
* ``.amc`` is the motion: one block per frame, ``<bone> <values…>`` with the
  values in ``dof`` order, degrees. The root carries ``TX TY TZ RX RY RZ``.
* World rotation of a bone at a frame is
  ``R_parent · C · R_amc · C⁻¹`` and its start point is the parent's start
  plus ``R_parent · direction_parent · length_parent`` — i.e. directions are
  rotated by the PARENT's world rotation, the bone's own rotation turns its
  children.
* Units: ``:units length 0.45`` means one ASF unit is ``1/0.45`` inch, so
  ``ASF_UNIT_CM = 2.54 / 0.45 = 5.644 cm``. The database is 120 fps.

Everything here stays in CMU space: Y up, right-handed, centimetres after
``to_cm``. The bpy script maps that onto the Mixamo rig.
"""
import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ASF_UNIT_CM = 2.54 / 0.45
CMU_FPS = 120

Mat3 = List[List[float]]
Vec3 = Tuple[float, float, float]


# ---------------------------------------------------------------- tiny linalg

def identity() -> Mat3:
    return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def mat_mul(a: Mat3, b: Mat3) -> Mat3:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def mat_vec(m: Mat3, v: Sequence[float]) -> Vec3:
    return (m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
            m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
            m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2])


def transpose(m: Mat3) -> Mat3:
    return [[m[j][i] for j in range(3)] for i in range(3)]


def rot_x(deg: float) -> Mat3:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[1, 0, 0], [0, c, -s], [0, s, c]]


def rot_y(deg: float) -> Mat3:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[c, 0, s], [0, 1, 0], [-s, 0, c]]


def rot_z(deg: float) -> Mat3:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


_AXIS_ROT = {"X": rot_x, "Y": rot_y, "Z": rot_z}


def euler(angles_deg: Sequence[float], order: str) -> Mat3:
    """Rotation matrix for Euler angles applied in ``order`` (e.g. "XYZ" =
    rotate about X first, then Y, then Z → ``Rz · Ry · Rx``)."""
    m = identity()
    for axis, ang in zip(order.upper(), angles_deg):
        m = mat_mul(_AXIS_ROT[axis](ang), m)
    return m


def normalize(v: Sequence[float]) -> Vec3:
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def cross(a: Sequence[float], b: Sequence[float]) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def axis_angle(axis: Sequence[float], rad: float) -> Mat3:
    x, y, z = normalize(axis)
    c, s, t = math.cos(rad), math.sin(rad), 1.0 - math.cos(rad)
    return [[t * x * x + c, t * x * y - s * z, t * x * z + s * y],
            [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
            [t * x * z - s * y, t * y * z + s * x, t * z * z + c]]


def rot_between(a: Sequence[float], b: Sequence[float]) -> Mat3:
    """Shortest rotation taking direction ``a`` onto direction ``b`` — the
    stdlib twin of ``cmu_clip._rot_between`` (mathutils), so the smoke checks
    can measure the same alignment without Blender."""
    a, b = normalize(a), normalize(b)
    ax = cross(a, b)
    n = math.sqrt(dot(ax, ax))
    if n < 1e-9:
        return identity() if dot(a, b) > 0 else axis_angle((1.0, 0.0, 0.0), math.pi)
    return axis_angle(ax, math.atan2(n, dot(a, b)))


def frame(direction: Sequence[float], secondary: Sequence[float]) -> Optional[Mat3]:
    """Orthonormal frame whose COLUMNS are ``direction``, ``secondary``
    orthogonalised against it, and their cross product."""
    x = normalize(direction)
    y = [secondary[i] - x[i] * dot(secondary, x) for i in range(3)]
    if math.sqrt(dot(y, y)) < 1e-9:
        return None
    y = normalize(y)
    z = cross(x, y)
    return [[x[0], y[0], z[0]], [x[1], y[1], z[1]], [x[2], y[2], z[2]]]


def _to_quat(m: Mat3) -> List[float]:
    """(w, x, y, z) of a rotation matrix."""
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0.0:
        s = math.sqrt(tr + 1.0) * 2.0
        return [0.25 * s, (m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s]
    if m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2.0
        return [(m[2][1] - m[1][2]) / s, 0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s]
    if m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2.0
        return [(m[0][2] - m[2][0]) / s, (m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s]
    s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2.0
    return [(m[1][0] - m[0][1]) / s, (m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s]


def _from_quat(q: Sequence[float]) -> Mat3:
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    w, x, y, z = (c / n for c in q)
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def _qmul(a: Sequence[float], b: Sequence[float]) -> List[float]:
    return [a[0] * b[0] - a[1] * b[1] - a[2] * b[2] - a[3] * b[3],
            a[0] * b[1] + a[1] * b[0] + a[2] * b[3] - a[3] * b[2],
            a[0] * b[2] - a[1] * b[3] + a[2] * b[0] + a[3] * b[1],
            a[0] * b[3] + a[1] * b[2] - a[2] * b[1] + a[3] * b[0]]


def drop_swing(m: Mat3, axis: Sequence[float]) -> Mat3:
    """``m`` with its rotation component ABOUT ``axis`` removed (swing/twist
    split). A rotation purely about the axis becomes the identity, a rotation
    purely perpendicular to it survives untouched."""
    q = _to_quat(m)
    a = normalize(axis)
    d = q[1] * a[0] + q[2] * a[1] + q[3] * a[2]
    tw = [q[0], a[0] * d, a[1] * d, a[2] * d]
    n = math.sqrt(sum(c * c for c in tw))
    if n < 1e-9:
        return m
    tw = [c / n for c in tw]
    return _from_quat(_qmul(q, [tw[0], -tw[1], -tw[2], -tw[3]]))


# The world up of both spaces (CMU and the Mixamo armature are Y up).
UP: Vec3 = (0.0, 1.0, 0.0)


def rest_align(mix_dir: Sequence[float], bone: "Bone", keep_pitch: bool = False) -> Optional[Mat3]:
    """The fixed rest alignment ``A`` of ``P = R_cmu(t) · A · R_mix`` built on
    the whole rest FRAME of a segment, not just on its direction.

    A CMU bone's rest frame is its ``axis`` matrix ``C``, NOT the world axes:
    ``C``'s first column is the segment's medio-lateral axis. For the feet and
    toes every ``.asf`` of the database carries the same hard-coded template
    ``axis -90 0 ±20``, i.e. the rest foot is modelled 20° SUPINATED, while the
    Mixamo rest foot is flat. Driving the Mixamo bone with the CMU rotation
    alone therefore rolls every foot onto its outer edge for the whole clip.
    The same holds sideways for the neck and head, whose ASF rest directions
    carry the actor's calibration offset (up to 20° off the sagittal plane).

    ``keep_pitch`` divides the swing about the medio-lateral axis back out:
    the two skeletons legitimately DRAW the same foot at different pitches
    (Mixamo's ankle→ball bone runs 34° down, CMU's 11–34° per actor), and that
    difference is what the floor fit is calibrated on — aligning it lifts the
    ball off the ground.

    Returns ``None`` when the bone carries no axis frame (a duck-typed take
    from ``fbx_clip``) or the frames are degenerate: the caller then keeps the
    identity, i.e. the behaviour of before.
    """
    C = getattr(bone, "C", None)
    cmu_dir = getattr(bone, "direction", None)
    if C is None or not cmu_dir or not any(cmu_dir):
        return None
    if math.sqrt(dot(mix_dir, mix_dir)) < 1e-9:
        return None
    mix_ml = cross(mix_dir, UP)
    # A bone within ~3° of the vertical has no medio-lateral axis worth
    # building a frame on — the cross product is then noise, and its SIGN
    # flips with it. Answer None and let the caller keep the identity.
    if math.sqrt(dot(mix_ml, mix_ml)) < 0.05:
        return None
    mix_ml = normalize(mix_ml)
    cmu_ml = (C[0][0], C[1][0], C[2][0])
    if dot(cmu_ml, mix_ml) < 0:
        cmu_ml = (-cmu_ml[0], -cmu_ml[1], -cmu_ml[2])   # the axis is a line
    f_mix = frame(mix_dir, mix_ml)
    f_cmu = frame(cmu_dir, cmu_ml)
    if f_mix is None or f_cmu is None:
        return None
    a = mat_mul(f_cmu, transpose(f_mix))
    return drop_swing(a, mix_ml) if keep_pitch else a


# -------------------------------------------------------------------- skeleton

class Bone:
    __slots__ = ("name", "direction", "length", "axis", "axis_order", "dof",
                 "parent", "children", "C", "Cinv")

    def __init__(self, name: str):
        self.name = name
        self.direction: Vec3 = (0.0, 0.0, 0.0)
        self.length = 0.0
        self.axis: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self.axis_order = "XYZ"
        self.dof: List[str] = []
        self.parent: Optional["Bone"] = None
        self.children: List["Bone"] = []
        self.C: Mat3 = identity()
        self.Cinv: Mat3 = identity()

    def finish(self) -> None:
        self.C = euler(self.axis, self.axis_order)
        self.Cinv = transpose(self.C)


class Skeleton:
    def __init__(self) -> None:
        self.bones: Dict[str, Bone] = {}
        self.root = Bone("root")
        self.root.dof = ["tx", "ty", "tz", "rx", "ry", "rz"]
        self.bones["root"] = self.root
        self.unit_cm = ASF_UNIT_CM

    def order(self) -> List[Bone]:
        """Bones parent-first (depth first from the root)."""
        out: List[Bone] = []

        def walk(b: Bone) -> None:
            out.append(b)
            for c in b.children:
                walk(c)
        walk(self.root)
        return out


def parse_asf(text: str) -> Skeleton:
    sk = Skeleton()
    section = ""
    cur: Optional[Bone] = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(":"):
            section = line.split()[0][1:].lower()
            cur = None
            continue
        parts = line.split()
        if section == "units":
            if parts[0] == "length":
                sk.unit_cm = 2.54 / float(parts[1])
        elif section == "root":
            if parts[0] == "order":
                sk.root.dof = [p.lower() for p in parts[1:]]
            elif parts[0] == "axis":
                sk.root.axis_order = parts[1].upper()
            elif parts[0] == "orientation":
                sk.root.axis = tuple(float(x) for x in parts[1:4])  # type: ignore[assignment]
        elif section == "bonedata":
            if parts[0] == "begin":
                cur = Bone("")
            elif parts[0] == "end":
                assert cur is not None and cur.name
                cur.finish()
                sk.bones[cur.name] = cur
                cur = None
            elif cur is not None:
                key = parts[0]
                if key == "name":
                    cur.name = parts[1]
                elif key == "direction":
                    cur.direction = tuple(float(x) for x in parts[1:4])  # type: ignore[assignment]
                elif key == "length":
                    cur.length = float(parts[1])
                elif key == "axis":
                    cur.axis = tuple(float(x) for x in parts[1:4])  # type: ignore[assignment]
                    cur.axis_order = parts[4].upper() if len(parts) > 4 else "XYZ"
                elif key == "dof":
                    cur.dof = [p.lower() for p in parts[1:]]
        elif section == "hierarchy":
            if parts[0] in ("begin", "end"):
                continue
            parent = sk.bones[parts[0]]
            for child_name in parts[1:]:
                child = sk.bones[child_name]
                child.parent = parent
                parent.children.append(child)
    sk.root.finish()
    return sk


# ---------------------------------------------------------------------- motion

def parse_amc(text: str) -> List[Dict[str, List[float]]]:
    """Frames as ``[{bone: [values…]}, …]`` in file order (frame numbers in
    the file are 1-based and contiguous; they are not kept)."""
    frames: List[Dict[str, List[float]]] = []
    cur: Optional[Dict[str, List[float]]] = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(":"):
            continue
        parts = line.split()
        if len(parts) == 1 and parts[0].isdigit():
            cur = {}
            frames.append(cur)
            continue
        if cur is None:
            continue
        cur[parts[0]] = [float(x) for x in parts[1:]]
    return frames


class Pose:
    """World-space pose of one frame: rotation matrix and start point (cm)
    per bone, in CMU space (Y up)."""
    __slots__ = ("rot", "pos")

    def __init__(self) -> None:
        self.rot: Dict[str, Mat3] = {}
        self.pos: Dict[str, Vec3] = {}

    def end(self, sk: Skeleton, name: str) -> Vec3:
        """End point of a bone (its start plus its rotated direction)."""
        b = sk.bones[name]
        d = mat_vec(self.rot[name], b.direction)
        p = self.pos[name]
        ln = b.length * sk.unit_cm
        return (p[0] + d[0] * ln, p[1] + d[1] * ln, p[2] + d[2] * ln)


def _bone_rotation(bone: Bone, values: Sequence[float]) -> Mat3:
    """``C · R_amc · C⁻¹`` — the AMC angles live in the bone's axis frame."""
    angles = {"rx": 0.0, "ry": 0.0, "rz": 0.0}
    for key, val in zip(bone.dof, values):
        if key in angles:
            angles[key] = val
    # The AMC channels are applied in the bone's axis order (X, then Y, then Z
    # for the usual "XYZ"), regardless of the order they are listed in ``dof``.
    r = euler([angles["r" + a.lower()] for a in bone.axis_order], bone.axis_order)
    return mat_mul(mat_mul(bone.C, r), bone.Cinv)


def solve_frame(sk: Skeleton, frame: Dict[str, List[float]]) -> Pose:
    pose = Pose()
    root_vals = frame.get("root", [0.0] * 6)
    tx = ty = tz = 0.0
    for key, val in zip(sk.root.dof, root_vals):
        if key == "tx":
            tx = val
        elif key == "ty":
            ty = val
        elif key == "tz":
            tz = val
    pose.rot["root"] = _bone_rotation(sk.root, root_vals)
    pose.pos["root"] = (tx * sk.unit_cm, ty * sk.unit_cm, tz * sk.unit_cm)
    for bone in sk.order():
        if bone is sk.root:
            continue
        parent = bone.parent
        assert parent is not None
        prot = pose.rot[parent.name]
        local = _bone_rotation(bone, frame.get(bone.name, []))
        pose.rot[bone.name] = mat_mul(prot, local)
        if parent is sk.root:
            pose.pos[bone.name] = pose.pos["root"]
        else:
            pose.pos[bone.name] = pose.end(sk, parent.name)
    return pose


def load_clip(asf_path: Path, amc_path: Path) -> Tuple[Skeleton, List[Dict[str, List[float]]]]:
    sk = parse_asf(Path(asf_path).read_text(encoding="utf-8", errors="replace"))
    frames = parse_amc(Path(amc_path).read_text(encoding="utf-8", errors="replace"))
    return sk, frames


def lowest_point_cm(sk: Skeleton, pose: Pose) -> float:
    """Lowest joint of the frame (bone ends included) — the floor estimate."""
    ys = [p[1] for p in pose.pos.values()]
    ys += [pose.end(sk, name)[1] for name in pose.rot if name != "root"]
    return min(ys)


def forward_xz(pose: Pose) -> Tuple[float, float]:
    """Unit XZ vector the root faces (+Z of the root frame in CMU space)."""
    f = mat_vec(pose.rot["root"], (0.0, 0.0, 1.0))
    n = math.hypot(f[0], f[2]) or 1.0
    return (f[0] / n, f[2] / n)


# ------------------------------------------------------------ loop cutting

# The bones whose rotation decides how well two frames "close" into a cycle.
LOOP_BONES = ("lfemur", "ltibia", "lfoot", "rfemur", "rtibia", "rfoot", "lhumerus",
              "lradius", "rhumerus", "rradius", "lowerback", "thorax", "upperneck")


def pose_distance(a: Pose, b: Pose) -> float:
    """How far two solved frames are apart: summed rotation angle of the
    limb/torso bones (radians) plus the hips height difference (metres).
    Shared by the Blender converter (the cut it makes) and the server (the
    cut it previews) — ONE metric, so the preview shows the clip that will
    be written."""
    d = 0.0
    for name in LOOP_BONES:
        if name not in a.rot:
            continue
        ra, rb = a.rot[name], b.rot[name]
        tr = sum(ra[i][j] * rb[i][j] for i in range(3) for j in range(3))
        d += math.acos(max(-1.0, min(1.0, (tr - 1.0) / 2.0)))
    d += abs(a.pos["root"][1] - b.pos["root"][1]) / 100.0
    return d


def best_loop_window(poses: Sequence[Pose], fps: float, min_s: float):
    """``(i, j, distance)`` — the window [i, j) of at least ``min_s`` seconds
    whose end pose is closest to its start pose. ``(0, n, None)`` when the
    take is too short. O(n²) over a few hundred frames."""
    n = len(poses)
    min_len = max(2, int(round(min_s * fps)))
    if n <= min_len + 1:
        return 0, n, None
    best = None
    for i in range(0, n - min_len):
        for j in range(i + min_len, n):
            d = pose_distance(poses[i], poses[j])
            if best is None or d < best[2]:
                best = (i, j, d)
    return best


def resample_indices(n_frames: int, source_fps: float, fps: float,
                     start_s: float = 0.0, end_s: Optional[float] = None,
                     speed: float = 1.0) -> List[int]:
    """The source frame index for every output frame of a window, the same
    stepping the converter uses (``cmu_clip._Take``). ``speed`` is the
    playback factor: 0.5 plays the take at half speed — twice the output
    frames over the same source window. ``start_s``/``end_s`` stay SOURCE
    seconds."""
    first = int(round(start_s * source_fps))
    last = n_frames if end_s is None else min(n_frames, int(round(end_s * source_fps)))
    speed = float(speed) if speed and speed > 0 else 1.0
    step = source_fps * speed / fps
    idx = []
    t = float(first)
    while t < last - 1e-6:
        idx.append(int(round(t)))
        t += step
    return idx
