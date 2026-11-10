"""The CPU fit of a rigid shoe onto a wearer's body (plan
``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md`` Task 9, spec
``docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md`` § 5.5 steps 1–8, § 5.7, § 6.1).

A pure numpy port of the spike's ``bl_assemble2.py`` v3 (``~/claude-out/shoe-spike/src``), without
Blender. Every length is in the body's bind space (metres, Y up); the shoe comes in its mesher
coordinates and is read in the frame of its ``insole.json`` (``footwear_insole``: ``x`` heel -> toe,
``height`` up, ``z`` = x × up, i.e. to the shoe's right).

1. **Foot on the MESH** (``measure_feet``): the vertices weighted > ``FOOT_WEIGHT_MIN`` to a side's
   Foot + ToeBase. The foot axis ``forward`` = the horizontal direction Foot head -> ToeBase head (the
   ToeBase tail is not in a GLB; the spike's tail sat 7 cm beyond the toes anyway). Length = the extent
   along it; plantar vertices = normal up component < ``PLANTAR_NORMAL_MAX`` within ``PLANTAR_BAND_M``
   of the floor (the body's lowest vertex); heel contact = the mean of the plantar vertices in the rear
   ``HEEL_BAND_M`` (height = their lowest), ball contact = the plantar vertices within ``BALL_BAND_M``
   of the ToeBase head along the axis; toe height = the height range of the vertices within
   ``TOE_BAND_M`` of the toe tip; rest pitch = the slope heel contact -> ball contact along the axis.
2. **Scale** (one per pair): k = (the longer foot + ``ALLOW_M``) / the insole arc from the heel end to
   the cavity end, where the cavity end is recomputed at the real scale: the last profile station whose
   insole-to-roof gap (``insole["cavity"]`` x k) holds the taller toes; an unroofed station counts as
   open (unlimited) in the rear ``OPEN_THROAT_SHARE`` of the length and as closed in front of it. The
   spike's fixed-point iteration (``SCALE_ITERATIONS``) from k = foot / arc(0.9 L).
3. **Extension per side** = the 2-point chord minus the rest pitch: the heel contact sits on the insole
   ``d_heel_m`` from the heel end, the ball on the insole at the chord distance from it; the Foot turns
   by that angle about its lateral axis (horizontal, ⟂ the foot axis) at the ankle, toe down. The ToeBase
   turns back so the toes lie on the forepart slope (the insole slope over ``FOREPART_SPAN_M`` in front of
   the ball): its net pitch is the slope, its own turn ``-(extension + slope)``. (The spike turned it by
   ``-(extension - slope)``, i.e. the toes DOWN by an up-going slope — a sign slip; 1.6 / 0.2 deg on the
   Stilettos.) THE BALL IS THE SKINNED BALL (fit version 2): the plantar ball band skinned with Foot and
   ToeBase in the stand pose (mean xz, lowest y), not the bind contact carried rigidly by Foot — the
   counter-turn moves it 4–5 mm on the real material and the shoe has to meet the ball the clips show. The
   ball depends on the pose and the pose on the chord to the ball, so the extension is a fixed point:
   start from the rigid solve (``heel_ball_m``, ``rest_pitch_deg``), then repeat — pose, skin the ball,
   chord of the posed heel-ball distance, correct the extension by chord minus the posed heel-over-ball
   pitch — until the correction is under ``BALL_SOLVE_TOL_RAD`` (``BALL_SOLVE_STEPS`` at most; three
   turns on the real material).
4. **Placement** (posed, before the root lift): yaw = the horizontal direction heel -> ball after the
   extension; the shoe's insole heel point on the posed heel contact; the left foot gets the source, the
   right foot its mirror (the shoe's lateral axis negated). Then the footprint midline goes onto the
   insole midline (the spike's v2: a line fitted to (foot slab middle - insole middle) over
   ``MIDLINE_SLABS`` slabs from the heel contact to ``MIDLINE_PAST_BALL_M`` past the ball, the shoe turned
   and shifted by it) and the shoe is widened by ONE width factor for the pair, ``min(width_cap,
   max(1, needed))`` with needed = foot width / insole width at the ball (each side's needed is recorded;
   what the cap leaves is ``slim_needed`` = the share of the ball width the forefoot slimming of Task 14
   must take off). No vertical rest step (the spike's 3rd-percentile plantar rest moved 1 mm).
5. **Root lift** = the largest per-side lift that puts that side's shoe ground on the floor; the gate
   ``lift_asymmetry_mm`` bounds the other side's float.
6. **Mirror**: the right shoe = the left's mirror image, winding flipped so its faces face out again;
   normals transform with the inverse transpose (still outward).
7. **Rigid bind**: weights Foot (1 - w) / ToeBase w, ``w`` = smoothstep over ±``BLEND_M`` around the ball
   along the shoe axis; the bind position is the inverse skinning of the posed placement (so in the bind
   pose the shoe is turned back by the extension, spec § 6.3). No leg bone gets weight.
8. **The cut** (fit version 3): a fit that passed its gates carries ``record["cut"]`` =
   ``footwear_cut.cut_description`` — the geometric description (no vertex indices) of what the shoe hides of
   the body, per side in the shoe's frame on the Foot / ToeBase bones. The fit step (``garment_footwear.fit``)
   applies it to the fit GLB's body and runs ``footwear_cut.cut_gates``; the assembly applies it per tier.

Gates (``FIT_GATES``, every one refuses a fit since version 3): ``ball_placement_mm`` (the
posed SKINNED ball of step 3 vs the shoe's chord ball point under the heel-anchored placement, before the
midline step — the residual of the fixed point plus whatever the chord's elevation misses; the spike read
the ball rigid on Foot, 4–5 mm off on the real material), ``lift_asymmetry_mm``,
``slim_needed``, ``stand_floor_mm`` (the lowest shoe point in the shod stand vs the floor — a BIND-pose
number; floor contact under clips is the renderer's shared ground measure, ``packages/scene-render``
``clipGround.ts``), ``boot`` (mm by which the shoe's topline stands above the shod ankle +
``footwear_insole.BOOT_MARGIN_M``; refused with ``footwear_insole.BOOT_REFUSED``).

The record's ``insole`` block also carries ``wall_top_raw`` — the shoe's wall top per station (raw units; the
lower of the two sides' top edges, every point farther than ``WALL_SIDE_M`` from the midline counted) — which
``footwear_cut.cut_description`` turns into the cut's cap; insole.json keeps only the analysis' topline.
"""
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

import numpy as np

from app.core import glb_mesh
from app.core.footwear_gates import check_gates

#: Bumped when the fit changes what it produces (part of the footwear fsig and
#: ``garment_fit.FIT_VERSION["footwear"]``).
FOOTWEAR_FIT_VERSION = 3
#: Toe room: the insole arc is the longer foot plus this (metres).
ALLOW_M = 0.005
#: Half-width of the Foot -> ToeBase smoothstep around the ball (metres).
BLEND_M = 0.015
#: The largest width factor a fit may apply (spec § 5.5), also the default cap.
WIDTH_CAP = 1.10
#: The smallest per-fit width cap override.
WIDTH_CAP_MIN = 1.00
#: The largest share of the ball width the forefoot slimming may take off (gate ``slim_needed``).
SLIM_MAX_SHARE = 0.18

#: name -> (kind, limit) — ``footwear_gates.check_gates`` kinds.
FIT_GATES: Dict[str, Tuple[str, Any]] = {
    "ball_placement_mm": ("max", 3.0),
    "lift_asymmetry_mm": ("max", 10.0),
    "slim_needed": ("max", 0.18),
    "stand_floor_mm": ("range", (-3.0, 3.0)),
    "boot": ("max", 0.0),
}
GATE_LABELS = {
    "ball_placement_mm": "the posed ball contact vs the shoe's ball point, worse side",
    "lift_asymmetry_mm": "difference of the two sides' lifts",
    "slim_needed": "share of the ball width the forefoot slimming must take off, worse side",
    "stand_floor_mm": "lowest shoe point in the shod stand above the floor",
    "boot": "mm the topline stands above the shod ankle + the boot margin",
}

#: Foot vertices: Foot + ToeBase weight above this.
FOOT_WEIGHT_MIN = 0.5
#: Plantar vertices: normal up component below this ...
PLANTAR_NORMAL_MAX = -0.4
#: ... within this height above the floor (metres).
PLANTAR_BAND_M = 0.03
#: Heel contact: the plantar vertices this far in front of the heel back (metres).
HEEL_BAND_M = 0.045
#: Ball contact: the plantar vertices within this of the ToeBase head along the foot axis (metres).
BALL_BAND_M = 0.012
#: Toe height: the vertices within this of the toe tip (metres).
TOE_BAND_M = 0.006
#: Fixed-point iterations of the scale against the cavity end.
SCALE_ITERATIONS = 20
#: The extension against the SKINNED ball (step 3): most turns of the fixed point, and the chord-minus-pitch
#: correction (radians) under which it has converged.
BALL_SOLVE_STEPS = 8
BALL_SOLVE_TOL_RAD = 1e-7
#: An unroofed station counts as the open throat in this rear share of the length, else as closed.
OPEN_THROAT_SHARE = 0.6
#: The forepart slope runs this far (metres) in front of the ball.
FOREPART_SPAN_M = 0.05
#: Midline fit: slabs between the heel contact and this far (metres) past the ball.
MIDLINE_SLABS = 11
MIDLINE_PAST_BALL_M = 0.04
#: Width at the ball: foot vertices within this (metres) of the ball along the shoe axis.
BALL_WIDTH_BAND_M = 0.01
#: Toe room: the foot's front-most vertex below this height (metres, shoe frame).
TOE_ROOM_HEIGHT_M = 0.05
#: Version of the ``foot_pose`` payload (spec § 6.1).
FOOT_POSE_VERSION = 1
#: Shoe points farther than this (metres) from the shoe's midline count as a side wall for the wall top the cut
#: and its gates read (the spike's 4 mm; ``record["insole"]["wall_top_raw"]``).
WALL_SIDE_M = 0.004

SIDES = ("left", "right")
_UP = np.array([0.0, 1.0, 0.0])


@dataclass
class FootMeasure:
    """One foot measured on the body mesh in the bind pose (``measure_feet``; points in bind space)."""
    side: str                    # "left" | "right"
    heel_back: np.ndarray        # the rearmost foot vertex along the foot axis
    toe_tip: np.ndarray          # the front-most foot vertex along the foot axis
    length_m: float              # heel back -> toe tip along the foot axis
    ball_width_m: float          # lateral extent of the foot vertices within BALL_WIDTH_BAND_M of the ball
    d_heel_m: float              # heel back -> heel contact along the foot axis
    heel_ball_m: float           # heel contact -> ball contact (3D distance)
    rest_pitch_deg: float        # slope heel contact -> ball contact along the axis (heel higher = positive)
    ankle: np.ndarray            # the Foot joint (head)
    ball_joint: np.ndarray       # the ToeBase joint (head)
    plantar: np.ndarray          # vertex ids of the plantar vertices
    vertex_ids: np.ndarray       # vertex ids of the foot (Foot + ToeBase weight > FOOT_WEIGHT_MIN)
    heel_contact: np.ndarray = field(default_factory=lambda: np.zeros(3))
    ball_contact: np.ndarray = field(default_factory=lambda: np.zeros(3))
    forward: np.ndarray = field(default_factory=lambda: np.array([1.0, 0.0, 0.0]))
    toe_height_m: float = 0.0
    foot_joint: str = ""         # the body's own joint names
    toe_joint: str = ""
    foot_index: int = -1         # skin indices
    toe_index: int = -1
    # vertex ids behind the two contacts: the plantar heel band and ball band (``measure_feet``)
    heel_ids: np.ndarray = field(default_factory=lambda: np.zeros(0, np.int64))
    ball_ids: np.ndarray = field(default_factory=lambda: np.zeros(0, np.int64))


@dataclass
class FootwearFit:
    """``fit_pair``'s result: ``ok`` = every gate passed; ``record`` = spec § 5.7 without ``accepted`` and the
    parents (``cut`` only when ``ok``); ``shoes[side]`` in bind space; ``foot_pose`` = spec § 6.1 without
    ``source``."""
    ok: bool
    reasons: List[str]
    record: Dict[str, Any]
    shoes: Dict[str, glb_mesh.GarmentMesh]
    foot_pose: Dict[str, Any]


class _Refused(Exception):
    """A shoe that cannot be put on this foot at all (no toe room, foot longer than the insole)."""


# --- small geometry ---------------------------------------------------------------------------------------------------

def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n <= 1e-12:
        raise ValueError("degenerate direction")
    return np.asarray(v, np.float64) / n


def _rotation(axis: np.ndarray, angle: float) -> np.ndarray:
    """3x3 rotation by ``angle`` (radians, right hand) about the unit ``axis``."""
    x, y, z = axis
    c, s = math.cos(angle), math.sin(angle)
    C = 1.0 - c
    return np.array([[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
                     [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
                     [z * x * C - y * s, z * y * C + x * s, c + z * z * C]])


def _about(pivot: np.ndarray, axis: np.ndarray, angle: float) -> np.ndarray:
    """4x4 rotation about the line through ``pivot`` along ``axis``."""
    R = _rotation(axis, angle)
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = pivot - R @ pivot
    return M


def _translation(t) -> np.ndarray:
    M = np.eye(4)
    M[:3, 3] = t
    return M


def _apply(M: np.ndarray, X: np.ndarray) -> np.ndarray:
    X = np.asarray(X, np.float64)
    return X @ M[:3, :3].T + M[:3, 3]


def _smoothstep(u: np.ndarray) -> np.ndarray:
    u = np.clip(u, 0.0, 1.0)
    return u * u * (3.0 - 2.0 * u)


def _vertex_normals(P: np.ndarray, F: np.ndarray) -> np.ndarray:
    """Area-weighted vertex normals (zero for an unused vertex)."""
    fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    N = np.zeros_like(P)
    for k in range(3):
        np.add.at(N, F[:, k], fn)
    n = np.linalg.norm(N, axis=1, keepdims=True)
    return N / np.where(n > 0, n, 1.0)


def _joint_weight(body: glb_mesh.BodyMesh, index: int) -> np.ndarray:
    return np.where(body.joints == index, body.weights, 0.0).sum(axis=1)


def _r(v: Any, nd: int = 7) -> Any:
    """JSON-safe: floats rounded, NaN/inf -> None, arrays -> lists."""
    if isinstance(v, dict):
        return {k: _r(x, nd) for k, x in v.items()}
    if isinstance(v, np.ndarray):
        return _r(v.tolist(), nd)
    if isinstance(v, (list, tuple)):
        return [_r(x, nd) for x in v]
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return round(f, nd) if math.isfinite(f) else None
    if isinstance(v, np.integer):
        return int(v)
    return v


# --- step 1: the feet -------------------------------------------------------------------------------------------------

def _skin_index(body: glb_mesh.BodyMesh, key: str) -> int:
    from app.core.rig_contract import norm_bone_name
    for i, name in enumerate(body.joint_names):
        if norm_bone_name(name) == key:
            return i
    raise ValueError(f"The body has no joint '{key}'")


def measure_feet(body: glb_mesh.BodyMesh, joints: Dict[str, np.ndarray]) -> Dict[str, FootMeasure]:
    """Both feet measured on the MESH (module docstring, step 1); ``joints`` = ``glb_mesh.joint_bind_matrices``.
    ValueError when a side lacks its Foot / ToeBase joint or its heel / ball contact vertices."""
    P = np.asarray(body.positions, np.float64)
    F = np.asarray(body.faces, np.int64)
    N = _vertex_normals(P, F)
    floor = float(P[:, 1].min())
    out: Dict[str, FootMeasure] = {}
    for side in SIDES:
        cap = side.capitalize()
        fkey, tkey = f"{side}foot", f"{side}toebase"
        if fkey not in joints or tkey not in joints:
            raise ValueError(f"The body has no {cap}Foot / {cap}ToeBase joint")
        fi, ti = _skin_index(body, fkey), _skin_index(body, tkey)
        a = np.asarray(joints[fkey], np.float64)[:3, 3]
        b = np.asarray(joints[tkey], np.float64)[:3, 3]
        fwd = _unit(np.array([b[0] - a[0], 0.0, b[2] - a[2]]))
        lat = np.cross(fwd, _UP)
        wf = _joint_weight(body, fi) + _joint_weight(body, ti)
        idx = np.nonzero(wf > FOOT_WEIGHT_MIN)[0]
        if len(idx) < 8:
            raise ValueError(f"The {side} foot has no skinned vertices")
        sc = (P[idx] - a) @ fwd
        smin, smax = float(sc.min()), float(sc.max())
        plantar = idx[(N[idx, 1] < PLANTAR_NORMAL_MAX) & (P[idx, 1] < floor + PLANTAR_BAND_M)]
        ps = (P[plantar] - a) @ fwd
        hsel = plantar[ps < smin + HEEL_BAND_M]
        bs = float((b - a) @ fwd)
        bsel = plantar[np.abs(ps - bs) < BALL_BAND_M]
        if not len(hsel) or not len(bsel):
            raise ValueError(f"The {side} foot has no plantar heel or ball vertices")
        H = P[hsel].mean(0)
        H[1] = P[hsel, 1].min()
        B = P[bsel].mean(0)
        B[1] = P[bsel, 1].min()
        tsel = idx[sc > smax - TOE_BAND_M]
        near_ball = idx[np.abs(sc - bs) < BALL_WIDTH_BAND_M]
        lw = (P[near_ball] - a) @ lat
        out[side] = FootMeasure(
            side=side, heel_back=P[idx[int(np.argmin(sc))]].copy(), toe_tip=P[idx[int(np.argmax(sc))]].copy(),
            length_m=smax - smin, ball_width_m=float(lw.max() - lw.min()) if len(lw) else 0.0,
            d_heel_m=float((H - a) @ fwd - smin), heel_ball_m=float(np.linalg.norm(B - H)),
            rest_pitch_deg=math.degrees(math.atan2(H[1] - B[1], float((B - H) @ fwd))),
            ankle=a, ball_joint=b, plantar=plantar, vertex_ids=idx, heel_contact=H, ball_contact=B,
            forward=fwd, toe_height_m=float(np.ptp(P[tsel, 1])), foot_joint=body.joint_names[fi],
            toe_joint=body.joint_names[ti], foot_index=fi, toe_index=ti, heel_ids=hsel, ball_ids=bsel)
    return out


# --- the insole at real scale -----------------------------------------------------------------------------------------

def _floats(values: Any) -> np.ndarray:
    return np.array([np.nan if v is None else float(v) for v in values], np.float64)


class _Insole:
    """The profile of ``insole.json`` as a function of x (raw frame units)."""

    def __init__(self, insole: Dict[str, Any]):
        self.gx = _floats(insole["stations"])
        self.gz = _floats(insole["lateral"])
        self.prof = _floats(insole["profile"])
        self.cav = _floats(insole.get("cavity") or [None] * len(self.gx))
        ok = ~np.isnan(self.prof)
        if ok.sum() < 2:
            raise ValueError("The insole has no profile")
        self.ok = ok
        self.px, self.pz = self.gx[ok], self.prof[ok]
        self.x0, self.x1 = float(self.px.min()), float(self.px.max())
        self.arc = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(self.px), np.diff(self.pz)))])
        self.length = float(insole["length_raw"])

    def z(self, x):
        return np.interp(x, self.px, self.pz)

    def arc_at(self, x: float) -> float:
        return float(np.interp(x, self.px, self.arc))

    def chord_to(self, xh: float, d: float, k: float) -> float:
        """The first x >= xh whose insole point lies ``d`` metres from the insole point at ``xh`` (linear
        between dense samples); _Refused when the insole ends first."""
        xs = np.linspace(xh, self.x1, 8000)
        dd = np.hypot((xs - xh) * k, (self.z(xs) - self.z(xh)) * k)
        hit = np.nonzero(dd >= d)[0]
        if not len(hit) or hit[0] == 0:
            raise _Refused("The foot is longer than the shoe's insole")
        i = int(hit[0])
        f = (d - dd[i - 1]) / (dd[i] - dd[i - 1])
        return float(xs[i - 1] + f * (xs[i] - xs[i - 1]))


def _scale(ins: _Insole, foot_len: float, toe_h: float) -> Tuple[float, float]:
    """``(k, x_end)``: the spike's fixed point k = (foot + ALLOW) / arc(cavity end at k)."""
    k = foot_len / ins.arc_at(0.9 * ins.length)
    x_end = ins.x1
    for _ in range(SCALE_ITERATIONS):
        room = np.where(np.isnan(ins.cav), np.where(ins.gx > OPEN_THROAT_SHARE * ins.gx.max(), 0.0, np.inf),
                        ins.cav) * k
        xs_ok = ins.gx[(room >= toe_h) & ins.ok]
        if not len(xs_ok):
            raise _Refused("The toe box is lower than the toes everywhere")
        x_end = float(xs_ok.max())
        k = (foot_len + ALLOW_M) / ins.arc_at(x_end)
    return k, x_end


# --- the fit ----------------------------------------------------------------------------------------------------------

def _frame_matrix(insole: Dict[str, Any]) -> np.ndarray:
    """4x4 mesh coordinates -> shoe frame ``(x, height, z)``."""
    from app.core.footwear_insole import frame_of
    fr = frame_of(insole)
    basis = np.stack([fr.x_axis, fr.up, fr.z_axis])
    M = np.eye(4)
    M[:3, :3] = basis
    M[:3, 3] = -basis @ fr.origin
    return M


def _pose(fm: FootMeasure, theta: float, slope: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """``(Bf, Bt, axis, toe_turn)``: the stand-pose skin matrices of Foot and ToeBase (bind -> posed, before
    the root lift) for an extension ``theta`` and a forepart slope ``slope`` (radians); ``axis`` = up x
    forward (a positive turn about it takes the toes down)."""
    axis = _unit(np.cross(_UP, fm.forward))
    Bf = _about(fm.ankle, axis, theta)
    toe_turn = -(theta + slope)
    Bt = _about(_apply(Bf, fm.ball_joint), axis, toe_turn) @ Bf
    return Bf, Bt, axis, toe_turn


def _skin(P: np.ndarray, body: glb_mesh.BodyMesh, ids: np.ndarray, mats: Dict[int, np.ndarray]) -> np.ndarray:
    """Linear blend skinning of the vertices ``ids`` with ``mats`` (skin index -> 4x4; others identity)."""
    X = P[ids]
    out = X.copy()
    for j, M in mats.items():
        w = _joint_weight(body, j)[ids][:, None]
        out += w * (_apply(M, X) - X)
    return out


def _local_axis(J: np.ndarray, axis_w: np.ndarray) -> np.ndarray:
    return _unit(np.linalg.solve(np.asarray(J, np.float64)[:3, :3], axis_w))


def fit_pair(insole: Dict[str, Any], shoe: glb_mesh.GarmentMesh, body: glb_mesh.BodyMesh,
             joints: Dict[str, np.ndarray], *, width_cap: float = WIDTH_CAP) -> FootwearFit:
    """Fit one shoe source (``shoe`` in its mesher coordinates, ``insole`` its analysis) to both feet of
    ``body`` (module docstring). A shoe that cannot be put on at all returns ``ok False`` with the reason
    and no shoes; a fit that ran returns everything, ``ok`` = every gate of ``FIT_GATES`` passed (the cut
    gates are the fit step's, ``garment_footwear.fit``). ValueError for a body without the foot joints."""
    width_cap = min(WIDTH_CAP, max(WIDTH_CAP_MIN, float(width_cap)))
    feet = measure_feet(body, joints)
    try:
        return _fit(insole, shoe, body, joints, feet, width_cap)
    except _Refused as exc:
        reason = str(exc)
        return FootwearFit(ok=False, reasons=[reason], record={"version": FOOTWEAR_FIT_VERSION, "error": reason},
                           shoes={}, foot_pose={})


def _fit(insole: Dict[str, Any], shoe: glb_mesh.GarmentMesh, body: glb_mesh.BodyMesh,
         joints: Dict[str, np.ndarray], feet: Dict[str, FootMeasure], width_cap: float) -> FootwearFit:
    from app.core.footwear_insole import BOOT_MARGIN_M, BOOT_REFUSED, BALL_SHARE, HEEL_SEAT_M, \
        PITCH_HEEL_SHARE, insole_map, topline_stations
    ins = _Insole(insole)
    P = np.asarray(body.positions, np.float64)
    floor = float(P[:, 1].min())
    FrameM = _frame_matrix(insole)
    S_pos = np.asarray(shoe.positions, np.float64)
    S_idx = np.asarray(shoe.indices, np.int64)
    Q = _apply(FrameM, S_pos)                        # the shoe in its frame (raw units)
    imap = insole_map(S_pos, S_idx, insole)
    gx, gz = ins.gx, ins.gz

    # 2. one scale for the pair
    foot_len = max(f.length_m for f in feet.values())
    toe_h = max(f.toe_height_m for f in feet.values())
    k, x_end = _scale(ins, foot_len, toe_h)

    def insole_cols(x: float) -> Tuple[int, np.ndarray]:
        i = int(np.argmin(np.abs(gx - x)))
        return i, np.nonzero(~np.isnan(imap[i]))[0]

    sides: Dict[str, Dict[str, Any]] = {}
    work: Dict[str, Dict[str, Any]] = {}
    for side, fm in feet.items():
        # 3. extension: the 2-point chord minus the rest pitch; the ToeBase back onto the forepart slope
        xh = ins.x0 + fm.d_heel_m / k
        # The ball the shoe is placed on is the ball AS SKINNED (Foot and ToeBase): the ToeBase
        # counter-turn moves the plantar ball vertices off the Foot-rigid point — 4–5 mm on the real
        # material — and the shoe has to meet the ball the clips show. That ball depends on the pose,
        # the pose on the chord to that ball: a fixed point, started from the rigid solve (the chord of
        # the bind heel–ball distance minus the rest pitch) and converged in a few turns
        # (|correction| < BALL_SOLVE_TOL_RAD, at most BALL_SOLVE_STEPS).
        xb = ins.chord_to(xh, fm.heel_ball_m, k)
        chord = math.atan2(float(ins.z(xh) - ins.z(xb)) * k, (xb - xh) * k)
        theta = chord - math.radians(fm.rest_pitch_deg)
        for _ in range(BALL_SOLVE_STEPS):
            x_fore = min(xb + FOREPART_SPAN_M / k, x_end)
            slope = (math.atan2(float(ins.z(x_fore) - ins.z(xb)) * k, (x_fore - xb) * k) if x_fore > xb else 0.0)
            Bf, Bt, axis, toe_turn = _pose(fm, theta, slope)
            H1 = _apply(Bf, fm.heel_contact)
            mats = {fm.foot_index: Bf, fm.toe_index: Bt}
            Bs = _skin(P, body, fm.ball_ids, mats)
            B1 = Bs.mean(0)
            B1[1] = Bs[:, 1].min()
            xb = ins.chord_to(xh, float(np.linalg.norm(B1 - H1)), k)
            chord = math.atan2(float(ins.z(xh) - ins.z(xb)) * k, (xb - xh) * k)
            pitch = math.atan2(float(H1[1] - B1[1]), float(np.hypot(B1[0] - H1[0], B1[2] - H1[2])))
            if abs(chord - pitch) < BALL_SOLVE_TOL_RAD:
                break
            theta += chord - pitch

        # 4. placement: yaw heel -> ball, the insole heel point on the posed heel contact; right = mirror
        d = _unit(np.array([B1[0] - H1[0], 0.0, B1[2] - H1[2]]))
        mirror = side == "right"
        right = np.cross(d, _UP)
        S = np.stack([d, _UP, -right if mirror else right], axis=1) * k
        P4 = np.eye(4)
        P4[:3, :3] = S
        P4[:3, 3] = H1 - S @ np.array([xh, float(ins.z(xh)), 0.0])
        ball_err = float(np.linalg.norm(_apply(P4, np.array([xb, float(ins.z(xb)), 0.0])) - B1))

        # the midline: foot slab middle - insole middle along the shoe, a line fitted to it
        Xf = _skin(P, body, fm.vertex_ids, mats)
        C = _apply(np.linalg.inv(P4), Xf)
        edges = np.linspace(xh, xb + MIDLINE_PAST_BALL_M / k, MIDLINE_SLABS + 1)
        dm, xm = [], []
        for xa, xc_ in zip(edges[:-1], edges[1:]):
            q = C[(C[:, 0] >= xa) & (C[:, 0] < xc_)]
            _, jj = insole_cols(0.5 * (xa + xc_))
            if len(q) < 5 or len(jj) < 3:
                continue
            dm.append(0.5 * (q[:, 2].min() + q[:, 2].max()) - 0.5 * (gz[jj.min()] + gz[jj.max()]))
            xm.append(0.5 * (xa + xc_))
        if len(xm) >= 2:
            sl, off = (float(v) for v in np.polyfit(np.array(xm), np.array(dm), 1))
        else:
            sl, off = 0.0, float(dm[0]) if dm else 0.0
        xc = float(np.mean(xm)) if xm else xh
        qb = C[np.abs(C[:, 0] - xb) < BALL_WIDTH_BAND_M / k]
        _, jb = insole_cols(xb)
        if not len(qb) or len(jb) < 2:
            raise _Refused("No foot or insole width at the ball")
        fw_ball = float(np.ptp(qb[:, 2])) * k
        iw_ball = float(gz[jb.max()] - gz[jb.min()]) * k
        work[side] = dict(fm=fm, xh=xh, xb=xb, chord=chord, theta=theta, slope=slope, Bf=Bf, Bt=Bt, axis=axis,
                          toe_turn=toe_turn, H1=H1, B1=B1, P4=P4, ball_err=ball_err, sl=sl, off=off, xc=xc,
                          fw_ball=fw_ball, iw_ball=iw_ball, Xf=Xf, mirror=mirror)

    # one width factor for the pair
    needed = {s: w["fw_ball"] / w["iw_ball"] for s, w in work.items()}
    width_factor = min(width_cap, max(1.0, max(needed.values())))
    slim = {s: max(0.0, 1.0 - w["iw_ball"] * width_factor / w["fw_ball"]) for s, w in work.items()}

    for side, w in work.items():
        fm = w["fm"]
        a = math.atan(w["sl"])
        c, s_ = math.cos(a), math.sin(a)
        R4 = np.eye(4)
        R4[:3, :3] = [[c, 0.0, -s_], [0.0, 1.0, 0.0], [s_, 0.0, c]]
        D4 = np.diag([1.0, 1.0, width_factor, 1.0])
        A = _translation([w["xc"], 0.0, w["off"] + w["sl"] * w["xc"]]) @ R4 @ _translation([-w["xc"], 0.0, 0.0]) @ D4
        Pf = w["P4"] @ A                          # shoe frame -> posed body (before the root lift)
        w["Pf"] = Pf
        w["lift"] = floor - float(Pf[1, 3])       # the shoe ground (frame height 0) onto the floor
        Cf = _apply(np.linalg.inv(Pf), w["Xf"])
        Bc = _apply(np.linalg.inv(Pf), w["B1"])
        w["xb_final"] = float(Bc[0])
        w["ball_gap_mm"] = (float(Bc[1]) - float(ins.z(Bc[0]))) * k * 1000.0
        low = Cf[Cf[:, 1] < TOE_ROOM_HEIGHT_M / k]
        w["toe_room_mm"] = (float(Q[:, 0].max()) - float(low[:, 0].max())) * k * 1000.0 if len(low) else None
        # arch gap: the plantar vertices against the insole map
        pl = _apply(np.linalg.inv(Pf), _skin(P, body, fm.plantar, {fm.foot_index: w["Bf"], fm.toe_index: w["Bt"]}))
        ix = np.rint((pl[:, 0] - gx[0]) / (gx[1] - gx[0])).astype(np.int64)
        iz = np.rint((pl[:, 2] - gz[0]) / (gz[1] - gz[0])).astype(np.int64)
        inside = (ix >= 0) & (ix < len(gx)) & (iz >= 0) & (iz < len(gz))
        zi = np.full(len(pl), np.nan)
        zi[inside] = imap[ix[inside], iz[inside]]
        gap = np.abs(pl[:, 1] - zi)[~np.isnan(zi)] * k * 1000.0
        w["arch_gap"] = (float(np.percentile(gap, 50)), float(np.percentile(gap, 95))) if len(gap) else (None, None)

    # 5. the root lift
    root_lift = max(w["lift"] for w in work.values())
    lifts = {s: w["lift"] for s, w in work.items()}

    # 6./7. mirror + rigid bind; contacts; the stand checks
    shoes: Dict[str, glb_mesh.GarmentMesh] = {}
    bones: Dict[str, Dict[str, Any]] = {}
    contacts_pose: Dict[str, List[Dict[str, Any]]] = {}
    lowest: List[float] = []
    toplines: List[float] = []
    shaft_raw = insole.get("shaft_h_raw")
    for side, w in work.items():
        fm = w["fm"]
        M = w["Pf"] @ FrameM                      # mesh coordinates -> posed body
        Pw = _apply(M, S_pos)
        lowest.append(float(Pw[:, 1].min()) + root_lift - floor)
        wt = _smoothstep((Q[:, 0] - (w["xb_final"] - BLEND_M / k)) / (2.0 * BLEND_M / k))
        Bfi, Bti = np.linalg.inv(w["Bf"]), np.linalg.inv(w["Bt"])
        bind = (1.0 - wt)[:, None] * _apply(Bfi, Pw) + wt[:, None] * _apply(Bti, Pw)
        normals = None
        if shoe.normals is not None:
            n = np.asarray(shoe.normals, np.float64) @ np.linalg.inv(M[:3, :3])    # inverse transpose
            n = (1.0 - wt)[:, None] * (n @ Bfi[:3, :3].T) + wt[:, None] * (n @ Bti[:3, :3].T)
            ln = np.linalg.norm(n, axis=1, keepdims=True)
            normals = n / np.where(ln > 0, ln, 1.0)
        n_v = len(S_pos)
        jw = np.zeros((n_v, 4))
        jw[:, 0], jw[:, 1] = 1.0 - wt, wt
        jj = np.zeros((n_v, 4), np.int64)
        jj[:, 1] = 1
        shoes[side] = glb_mesh.GarmentMesh(
            positions=bind, normals=normals, uvs=np.asarray(shoe.uvs, np.float64).copy(),
            indices=S_idx[:, [0, 2, 1]].copy() if w["mirror"] else S_idx.copy(), joints=jj, weights=jw,
            joint_names=[fm.foot_joint, fm.toe_joint], image=shoe.image, mime=shoe.mime,
            material=dict(shoe.material or {}),
            colors=None if shoe.colors is None else np.asarray(shoe.colors, np.float64).copy())
        Jf = np.asarray(joints[f"{side}foot"], np.float64)
        Jt = np.asarray(joints[f"{side}toebase"], np.float64)
        ax_f, ax_t = _local_axis(Jf, w["axis"]), _local_axis(Jt, w["axis"])
        bones[fm.foot_joint] = {"axis": ax_f, "deg": math.degrees(w["theta"])}
        bones[fm.toe_joint] = {"axis": ax_t, "deg": math.degrees(w["toe_turn"])}
        # contacts on the shoe sole: heel on Foot, ball and toe on ToeBase
        recs, pose = [], []
        for role, key, bone, J, Binv in (("heel", "heel_tip", fm.foot_joint, Jf, Bfi),
                                         ("ball", "ball", fm.toe_joint, Jt, Bti),
                                         ("toe", "toe_tip", fm.toe_joint, Jt, Bti)):
            pt = (insole.get("contacts") or {}).get(key)
            if pt is None:
                continue
            pos = _apply(Binv, _apply(w["Pf"], np.asarray(pt, np.float64)))
            recs.append({"bone": bone, "pos_local": _apply(np.linalg.inv(J), pos), "role": role})
            pose.append({"bone": bone, "pos": pos, "role": role})
        contacts_pose[side] = pose
        if shaft_raw is not None:
            # the topline in the shod stand vs the shod ankle (the shoe stays upright: heights scale by k)
            topline = float(shaft_raw) * k + (root_lift - w["lift"])
            ankle = float(fm.ankle[1]) + root_lift - floor
            toplines.append((topline - (ankle + BOOT_MARGIN_M)) * 1000.0)
        placement_bind = np.linalg.inv(Jf) @ Bfi @ M
        sides[side] = {
            "mirror": w["mirror"], "placement_bind": placement_bind, "blend_m": BLEND_M,
            "extension": {"axis_local": ax_f, "deg": math.degrees(w["theta"])},
            "toe_counter": {"axis_local": ax_t, "deg": math.degrees(w["toe_turn"])},
            "forepart_slope_deg": math.degrees(w["slope"]), "lift_m": w["lift"],
            "foot_len_m": fm.length_m, "foot_w_ball_mm": w["fw_ball"] * 1000.0,
            "insole_w_ball_mm": w["iw_ball"] * 1000.0, "toe_room_mm": w["toe_room_mm"], "contacts": recs,
        }

    ball_mm = max(w["ball_err"] for w in work.values()) * 1000.0
    metrics = {
        "ball_placement_mm": ball_mm,
        "lift_asymmetry_mm": abs(lifts["left"] - lifts["right"]) * 1000.0,
        "slim_needed": max(slim.values()),
        "stand_floor_mm": min(lowest) * 1000.0,
        "boot": max(toplines) if toplines else None,
    }
    table = {name: (kind, limit, GATE_LABELS[name]) for name, (kind, limit) in FIT_GATES.items()}
    ok, reasons = check_gates(metrics, table, optional=("boot",))
    if metrics["boot"] is not None and metrics["boot"] > FIT_GATES["boot"][1]:
        reasons.insert(0, BOOT_REFUSED)
    gates: Dict[str, Any] = {}
    for name, (kind, limit) in FIT_GATES.items():
        value = metrics[name]
        passed = check_gates({name: value}, {name: (kind, limit, GATE_LABELS[name])}, optional=("boot",))[0]
        gates[name] = {"value": value, "limit": list(limit) if isinstance(limit, tuple) else limit,
                       "ok": passed, "gating": True}

    seat = float(ins.z(ins.x0 + HEEL_SEAT_M / k))
    ball_h = float(ins.z(BALL_SHARE * ins.length))
    heel_h = float(ins.z(PITCH_HEEL_SHARE * ins.length))
    used = Q[np.unique(S_idx)]
    # the wall top per station (raw units, None where absent), for the cut (footwear_cut.cut_description;
    # insole.json keeps only the analysis' topline and the cut must be derivable from the record): the lower
    # of the two sides' top edges, every point farther than WALL_SIDE_M from the midline counted — the spike's
    # wall top, not the analysis' topline whose 75 % lateral filter reads a leaning heel counter 2 cm low
    wall_top = topline_stations(Q, S_idx, gx, side_share=0.0, min_abs=WALL_SIDE_M / k)[0]
    wall_top_raw = [None if math.isnan(v) else float(v) for v in wall_top]
    record = {
        "version": FOOTWEAR_FIT_VERSION,
        "scale": {
            "k_m_per_unit": k, "length_m": float(np.ptp(used[:, 0])) * k, "width_m": float(np.ptp(used[:, 2])) * k,
            "height_m": float(np.ptp(used[:, 1])) * k, "width_factor": width_factor,
            "width_needed": needed, "width_cap": width_cap, "slim_needed": slim,
            "insole_arc_m": ins.arc_at(x_end) * k, "foot_len_m": foot_len, "toe_h_m": toe_h,
        },
        "sides": sides,
        "root_lift_m": root_lift,
        "insole": {
            "pitch_deg": math.degrees(math.atan2(heel_h - ball_h, (BALL_SHARE - PITCH_HEEL_SHARE) * ins.length)),
            "heel_seat_h_m": seat * k, "heel_rise_m": (seat - ball_h) * k, "insole_ball_h_m": ball_h * k,
            "insole_cover": insole.get("insole_cover"), "cavity_end_x_m": x_end * k,
            "shaft_h_m": None if shaft_raw is None else float(shaft_raw) * k,
            "open_share": None if insole.get("vamp_cover") is None else 1.0 - float(insole["vamp_cover"]),
            "wall_top_raw": wall_top_raw,
        },
        "gates": gates,
        "diagnostics": {s: {
            "chord_pitch_deg": math.degrees(w["chord"]), "rest_pitch_deg": w["fm"].rest_pitch_deg,
            "ball_placement_mm": w["ball_err"] * 1000.0, "ball_gap_mm": w["ball_gap_mm"],
            "lateral_off_mm": w["off"] * k * 1000.0,
            "lateral_yaw_deg": math.degrees(math.atan(w["sl"])),
            "arch_gap_p50_mm": w["arch_gap"][0], "arch_gap_p95_mm": w["arch_gap"][1],
            "ball_x_m": w["xb_final"] * k, "heel_x_m": w["xh"] * k,
            "foot_vertices": int(len(w["fm"].vertex_ids)), "plantar_vertices": int(len(w["fm"].plantar)),
        } for s, w in work.items()},
    }
    if reasons and reasons[0] == BOOT_REFUSED:
        record["refusal"] = BOOT_REFUSED
    foot_pose = {"version": FOOT_POSE_VERSION, "bones": bones, "root_lift_m": root_lift,
                 "contacts": contacts_pose}
    result = FootwearFit(ok=ok, reasons=reasons, record=_r(record), shoes=shoes, foot_pose=_r(foot_pose))
    if ok:
        # 8. the cut: derived from the record and the bound shoes of this fit (footwear_cut imports this module,
        # hence the local import); a refused fit carries none — nothing applies it
        from app.core.footwear_cut import cut_description
        result.record["cut"] = cut_description(result, insole)
    return result
