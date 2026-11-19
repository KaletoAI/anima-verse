"""Mesh mode "Shell from the body" of a clothing piece (Ruling A48d; spikes A48 / A48b B1, no lift; its own mode
since A168).

An outfit piece in mode ``shell`` (``garment_set.SHELL``, on the ITEM like every mode) gets its mesh made from the
BASE BODY's own surface over the region the piece covers in its worn views — no generated mesh, no cut-outs, CPU
only, no hub job. A piece in mode ``own_mesh`` always uses its generated mesh (``as_generated``), placed and fitted
by ``garment_fit.fit_clothing``. ``shape_of`` is the one rule: the shape a fit of an item makes.

**How the shell is made** (``build_shell``, pure: bytes and arrays in, a ``garment_fit.FitResult`` out):

1. The region: the unrigged body's vertices seen by the front or the back view (z-buffer, within 1.5 cm of the
   front-most surface) whose pixel lies in the piece's ghost mask (dilated 2 px), arms excluded (arm weight < 0.3);
   4 rings closed, components under 5 % dropped, grown 2 rings, and 8 more rings into the side band no view sees
   head-on (so the side bridge has room).
2. Onto the rigged body by UV, OUTER WALL only (``outer_faces``: front-most from one of 26 directions) — the doubled
   body surface's hidden inner wall never becomes part of the piece; small enclosed holes (< 8 cm²) closed.
3. Two midpoint subdivisions; a per-vertex signed membership scalar (mm inside the view's ghost mask for head-on
   points, the side bridge's margin for side points — ``SideBridge``: the bands that reach the head-on edge are
   matched front↔back by height and carried around the side; a grazing point seen deep inside a mask is a bump, not
   a side), smoothed 4 passes, and the triangles CLIPPED at its zero line (marching triangles on the unwelded mesh,
   UV seams intact): the border follows the scalar, not the pixel grid.
4. Offset along the smoothed outward normals by the piece's ``shell_offset`` (A166; default ``THICKNESS_M`` = 4 mm,
   ``SHELL_OFFSET_CHOICES``); skin weights = the body's top 4.
5. Texture baked at ``TEXTURE_PX`` in the body's UV atlas: a head-on sample takes the nearest pixel inside the
   eroded ghost mask (no background grey), a side sample the median of the 12 nearest head-on samples at the band's
   matched height, blended front→back along the arc. A see-through piece (its noun / prompt names lace, net, sheer
   …: A219, ``see_through_text``) whose views look like a lace loses the backdrop that shows through its openings in
   every view first (``unmix_backdrop``) — black lace baked grey otherwise.

**Side views** (A185, the piece's fit setting "Side views for the shell", ``shell_sides``, off by default): the piece
also has left / right piece-only views, and ``build_shell`` reads them as 3rd / 4th views — projected along the body's
depth (z horizontal, the camera on the ±x side the silhouette names). A side view counts a point only where it sees
it well (``side_view_ok``: normal · view >= ``SIDE_FACING_MIN``, depth window 1.5 cm like the front / back) and
neither the front nor the back sees it frontally (>= ``FRONTAL_MIN``): there the front / back masks decide and a
side never adds. In the side band its mask replaces the bridge's estimate; it colours what it sees. "Take from the
body" and "Fill holes up to" apply after the merge as before.

**Arms up** (A190): a side view made from the ARMS-UP base side view (``shell_base_views``; the view's ``arms_up``)
is projected onto the body POSED the same way (``pose_arms_up``: the rigged body's arm chains turned about the
shoulder joints until the arm points ``ARMS_UP_TILT_DEG`` off vertical, linear blend skinning on the CPU). The posed
positions keep the rest mesh's vertex indices, so what the posed body shows covered maps back to the rest mesh by
index; every later step (region, clip, colour) reads that view through the posed positions carried alongside.

The shell is already on the body (bind space of the rigged base), so the fit step only grafts it: no placement, no
push, no allowance (the width/depth/sleeve settings do not apply to a shell). Its record names ``mesh_shape:
"shell"`` and the metrics (``inside_share`` = vertices more than 2 mm under the skin, exact point-triangle distance).
"""
from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

AS_GENERATED = "as_generated"
SHELL = "shell"
#: The close-fitting slots (``app.models.inventory.VALID_PIECE_SLOTS``) the old Auto rule made a shell for.
CLOSE_SLOTS: Tuple[str, ...] = ("underwear_top", "underwear_bottom", "legs")
#: The shell's distance from the skin (m) — the default of the per-piece setting ``shell_offset``.
THICKNESS_M = 0.004
#: A166: the choices of the per-piece shell offset (mm along the smoothed outward normal; ``garment_fit_settings``
#: key ``shell_offset``): a molded cup stands off the breast, a slip lies on the skin.
SHELL_OFFSET_CHOICES: Tuple[int, ...] = (4, 6, 8, 10, 12, 16)
SHELL_OFFSET_DEFAULT = 4
#: A184 (cause of the holes and lost straps on a bra): the region step excluded every vertex weighted > 0.3 on a
#: ``Shoulder`` bone too — the Mixamo shoulder bones weigh the trapezius and collarbone where straps lie. Arms and
#: hands stay excluded.
#: A184: "Take from the body" — mm the shell's border is moved outward around the piece's outline in its views.
MARGIN_CHOICES: Tuple[int, ...] = (0, 3, 6, 10, 15)
MARGIN_DEFAULT = 3
#: A184: "Fill holes up to" — cm² of an enclosed gap in the piece's outline / body region that is closed.
FILL_CHOICES: Tuple[int, ...] = (0, 2, 5, 10, 20, 50)
FILL_DEFAULT = 2


def shell_offset_choice(raw: Optional[Dict[str, Any]]) -> int:
    """The shell offset (mm) of a piece's fit settings (``shell_offset``): one of ``SHELL_OFFSET_CHOICES``, else the
    default."""
    value = (raw or {}).get("shell_offset") if isinstance(raw, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value in SHELL_OFFSET_CHOICES:
        return int(value)
    return SHELL_OFFSET_DEFAULT


def shell_margin_choice(raw: Optional[Dict[str, Any]]) -> int:
    """"Take from the body" (mm, ``shell_margin``, A184): one of ``MARGIN_CHOICES``, else the default."""
    value = (raw or {}).get("shell_margin") if isinstance(raw, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value in MARGIN_CHOICES:
        return int(value)
    return MARGIN_DEFAULT


def shell_fill_choice(raw: Optional[Dict[str, Any]]) -> int:
    """"Fill holes up to" (cm², ``shell_fill``, A184): one of ``FILL_CHOICES``, else the default."""
    value = (raw or {}).get("shell_fill") if isinstance(raw, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value in FILL_CHOICES:
        return int(value)
    return FILL_DEFAULT


def shell_sides_choice(raw: Optional[Dict[str, Any]]) -> bool:
    """"Side views for the shell" (``shell_sides``, A185): True only for a stored ``True`` (default off)."""
    return isinstance(raw, dict) and raw.get("shell_sides") is True


#: A185: the views a shell piece with "Side views for the shell" adds as its 3rd / 4th piece-only views.
SIDE_VIEWS: Tuple[str, ...] = ("left", "right")
#: A185: a side view counts a body vertex as covered only where the surface faces its camera at least this much
#: (normal · view direction; measured on Glut's bra, see the A185 report) — a grazing surface is seen too thin.
SIDE_FACING_MIN = 0.5
#: A185: where the front or back camera sees a vertex at least this frontally, ITS mask decides and a side view never
#: adds the vertex (front/back win where they look frontally).
FRONTAL_MIN = 0.6

#: The fit settings that shape a shell only (a generated mesh's fit is not due for them).
SHELL_SETTING_KEYS: Tuple[str, ...] = ("shell_offset", "shell_margin", "shell_fill", "shell_sides")
#: Texture size of the baked shell (px).
TEXTURE_PX = 2048
#: A vertex this far under the skin (m) counts as inside (``inside_share``).
INSIDE_M = 0.002
#: A190: the arms-up pose of a side view — each arm points this many degrees off vertical, outward (the base side
#: view's edit asks for "both arms straight up above the head").
ARMS_UP_TILT_DEG = 12.0
#: A190: the joints that turn with an arm — a joint whose name ends with ``<side>`` + one of these (Mixamo names;
#: the fingers hang under the hand: every name holding ``<side>Hand``).
ARM_CHAIN = ("Arm", "ForeArm", "Hand")
#: A190: an arms-up base side view passes when its figure matches the posed body's silhouette at least this well
#: (0.8 until A210: an edit at 0.74 posed vs 0.666 at rest was a good base, refused).
ARMS_UP_IOU_MIN = 0.7
#: A210: ... and better than the body at rest by at least this much (the arms really went up).
ARMS_UP_IOU_MARGIN = 0.05
#: Bumped when the shell's construction changes: a shell made by another version reads stale.
#: 4 (A199, review 06#4): the body's z-buffer samples are spaced by the views' mask pixel (``ZBUF_SPACING_PX``)
#: instead of 1/2500 of the body height — ~13 samples per mask pixel became ~4, a third of the memory.
#: 5 (A219): a see-through piece's views lose their backdrop share (``unmix_backdrop``) and a limb's misregistered
#: edge strip is worn where both views show the ring worn (``ring_closed``).
#: 6 (A220): side bridges match runs by overlap and continue the panel's pattern; the shell is lifted over the body's
#: extension parts and never offset into the body from a wall seen from behind; an arm the piece covers stays in.
#: 7 (A226): a bottom piece's front and back panels are joined under the crotch (``crotch_run`` / ``crotch_bridge``),
#: the bridge relaxed over the body's folds; ``lift_over_surfaces`` marches its rays (same test, ~20× faster).
SHELL_VERSION = 7
#: A199: the spacing of the body's z-buffer samples (``samples``' ``px``: about 4 per spacing²) in mask pixels of
#: the finest view. 4 random samples per pixel leave a pixel empty with p ≈ e⁻⁴ on a face-on surface; the 3×3
#: maximum filter of the z-buffer closes such a pixel.
ZBUF_SPACING_PX = 1.0
#: A191: bumped when only the side-view merge changes — a shell made WITH side views by another version reads stale
#: (1: the arm no longer occludes the flank for a side view); a shell without side views is not touched by it.
SIDES_VERSION = 1


def construction_due(inputs: Optional[Dict[str, Any]]) -> bool:
    """Whether a shell fit's recorded ``inputs`` were made by another construction: another ``SHELL_VERSION``, or
    (A191) side views read by another ``SIDES_VERSION``."""
    inputs = inputs or {}
    if inputs.get("shell_version") != SHELL_VERSION:
        return True
    return bool(shell_sides_choice(inputs.get("fit_settings"))) and inputs.get("shell_sides_version") != SIDES_VERSION

BIN_M = 0.002
WINDOWS = ((6.0, 0), (20.0, 1))
MATCH_M = 0.03
EXT_M = 0.008


# --- The shape of a piece ----------------------------------------------------------------------------------------

def shape_of(item: Optional[Dict[str, Any]]) -> str:
    """The shape a fit of the outfit piece ``item`` makes: ``shell`` for an item in mode ``shell``
    (``garment_set.SHELL``), ``as_generated`` for every other."""
    from app.core import garment_set
    return SHELL if garment_set.mesh_mode_of(item) == garment_set.SHELL else AS_GENERATED


def close_fitting(item: Optional[Dict[str, Any]]) -> bool:
    """Whether ``item`` is a close-fitting piece (the old Auto rule of the mesh shape, read once by the mode
    migration ``shell_mode_migration``): at least one slot, EVERY slot in ``CLOSE_SLOTS``, no ``covers`` and not
    closable."""
    from app.core import garment_set
    piece = (item or {}).get("outfit_piece")
    piece = piece if isinstance(piece, dict) else {}
    slots = [str(s) for s in (piece.get("slots") or [])]
    return (bool(slots) and all(s in CLOSE_SLOTS for s in slots) and not (piece.get("covers") or [])
            and not garment_set.closable_of(item))


# --- geometry helpers ------------------------------------------------------------------------------------------------

#: Samples per chunk of ``samples`` / ``_posed_samples`` (A198: the body's z-buffer takes ~15 M samples; the whole
#: (n, 3) corner gathers at once peaked near 2 GB per shell build).
SAMPLE_CHUNK = 1_000_000


def samples(P, F, px: float, seed: int = 1):
    """Random points on the faces, about 4 per ``px``² (capped at 600 per face): ``(X, None, tri, bary)``. A198: the
    second entry (per-sample face normals) is no longer built — no caller read it, and it cost ``3·n`` floats; the
    points are computed in chunks of ``SAMPLE_CHUNK`` from the same random draws, so ``X`` is the same bit for bit."""
    P = np.asarray(P)
    F = np.asarray(F)
    rng = np.random.default_rng(seed)
    A, B, C = P[F[:, 0]], P[F[:, 1]], P[F[:, 2]]
    area = np.linalg.norm(np.cross(B - A, C - A), axis=1) / 2
    n = np.clip(np.ceil(area / (px * px) * 4).astype(int), 1, 600)
    tri = np.repeat(np.arange(len(F)), n)
    r1, r2 = rng.random(len(tri)), rng.random(len(tri))
    X = np.empty((len(tri), 3), np.result_type(P.dtype, np.float64))
    bary = np.empty((len(tri), 3), np.float64)
    for lo in range(0, len(tri), SAMPLE_CHUNK):
        hi = min(lo + SAMPLE_CHUNK, len(tri))
        t = tri[lo:hi]
        s_ = np.sqrt(r1[lo:hi])
        a, b, c = 1 - s_, s_ * (1 - r2[lo:hi]), s_ * r2[lo:hi]
        X[lo:hi] = A[t] * a[:, None] + B[t] * b[:, None] + C[t] * c[:, None]
        bary[lo:hi, 0], bary[lo:hi, 1], bary[lo:hi, 2] = a, b, c
    return X, None, tri, bary


def _posed_samples(bary, Pp, faces, tri) -> np.ndarray:
    """``einsum("nk,nkj->nj", bary, Pp[faces[tri]])`` in chunks of ``SAMPLE_CHUNK`` (A198: the whole (n, 3, 3)
    gather was ~1 GB for the body's z-buffer samples)."""
    out = np.empty((len(tri), 3), np.float64)
    for lo in range(0, len(tri), SAMPLE_CHUNK):
        hi = min(lo + SAMPLE_CHUNK, len(tri))
        out[lo:hi] = np.einsum("nk,nkj->nj", bary[lo:hi], Pp[faces[tri[lo:hi]]])
    return out


def _rotation(a, b) -> np.ndarray:
    """The rotation matrix turning unit direction ``a`` onto unit direction ``b`` (Rodrigues)."""
    a = np.asarray(a, np.float64) / np.linalg.norm(a)
    b = np.asarray(b, np.float64) / np.linalg.norm(b)
    v, c = np.cross(a, b), float(a @ b)
    if np.linalg.norm(v) < 1e-12:
        return np.eye(3) if c > 0 else -np.eye(3)
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K * (1.0 / (1.0 + c))


def arm_joints(joint_names: List[str], side: str) -> Tuple[Optional[int], Optional[int], List[int]]:
    """``(upper arm joint, hand joint, every joint of the chain)`` of ``side`` ("Left" / "Right") by name (A190)."""
    def ends(name, tail):
        return name.split(":")[-1] == f"{side}{tail}"
    upper = next((i for i, n in enumerate(joint_names) if ends(n, "Arm")), None)
    hand = next((i for i, n in enumerate(joint_names) if ends(n, "Hand")), None)
    chain = [i for i, n in enumerate(joint_names)
             if any(ends(n, t) for t in ARM_CHAIN) or f"{side}Hand" in n.split(":")[-1]]
    return upper, hand, chain


def pose_arms_up(P, joints, weights, joint_names: List[str], joint_positions: Dict[str, np.ndarray], *,
                 tilt_deg: float = ARMS_UP_TILT_DEG) -> np.ndarray:
    """A190: the body ``P`` (bind space, skinned by ``joints`` / ``weights``) with both arms raised: per side the arm
    chain (``arm_joints``) turns rigidly about the upper-arm joint's head until the upper arm → hand direction points
    ``tilt_deg`` off vertical toward the shoulder's side of the body (+y up, the depth component dropped), blended by the skin weights
    (linear blend skinning; a vertex weighted half on the arm moves half). The result keeps ``P``'s vertex order —
    index i of the posed body is index i of the rest body. A side without its joints stays as it is."""
    P = np.asarray(P, np.float64)
    J = np.asarray(joints, np.int64)
    W = np.asarray(weights, np.float64)
    disp = np.zeros_like(P)
    for side in ("Left", "Right"):
        upper, hand, chain = arm_joints(joint_names, side)
        if upper is None or hand is None:
            continue
        def head(name):
            # ``BodyMesh.joint_positions`` keys are the bare lower-case names ("leftarm"); accept the full name too
            found = joint_positions.get(name)
            return found if found is not None else joint_positions.get(name.split(":")[-1].lower())
        a = np.asarray(head(joint_names[upper]), np.float64)
        h = np.asarray(head(joint_names[hand]), np.float64)
        if a.shape != (3,) or h.shape != (3,):
            continue
        out = 1.0 if a[0] >= float(np.mean(P[:, 0])) else -1.0   # outward: the shoulder's side of the body
        t = np.radians(tilt_deg)
        Rm = _rotation(h - a, np.array([out * np.sin(t), np.cos(t), 0.0]))
        moved = (P - a) @ Rm.T + a - P
        w = np.zeros(len(P))
        for j in chain:
            w += (W * (J == j)).sum(1)
        disp += np.clip(w, 0.0, 1.0)[:, None] * moved
    return P + disp


def outer_faces(P, F, px: float = 0.002, tol: float = 0.0025) -> np.ndarray:
    """Faces of the OUTER wall of a (possibly double-walled) mesh: a face is outer when one of its samples is
    front-most (within ``tol``) in an orthographic z-buffer from one of 26 directions."""
    return outer_faces_oriented(P, F, px, tol)[0]


def outer_faces_oriented(P, F, px: float = 0.002, tol: float = 0.0025) -> Tuple[np.ndarray, np.ndarray]:
    """``(outer, back_seen)``: ``outer`` as ``outer_faces``; ``back_seen`` (A220) the outer faces that are never
    front-most from a direction their outward normal (the winding, signed by the mesh's volume) faces — only their
    back is seen. Such a face is a wall seen through an opening of the mesh: an inset extension part is its own
    primitive, so the body's own surface there is the part's inner wall seen through the cut, wound inward. A shell
    made on it must take the face reversed, or it is offset into the body."""
    P = np.asarray(P, np.float64)
    F = np.asarray(F, np.int64).reshape(-1, 3)
    X, _, tri, _ = samples(P, F, px * 0.7)
    Nf = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    vol = np.einsum("ij,ij->i", P[F[:, 0]], np.cross(P[F[:, 1]], P[F[:, 2]])).sum()
    Ns = (Nf * (1.0 if vol >= 0 else -1.0))[tri]
    vis = np.zeros(len(F), bool)
    facing = np.zeros(len(F), bool)
    for d in [(i, j, k) for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1) if (i, j, k) != (0, 0, 0)]:
        d = np.array(d, float) / np.linalg.norm(d)
        up = np.array([0, 1.0, 0]) if abs(d[1]) < 0.9 else np.array([1.0, 0, 0])
        u = np.cross(up, d)
        u /= np.linalg.norm(u)
        v = np.cross(d, u)
        a, b, z = X @ u, X @ v, X @ d
        i = ((a - a.min()) / px).astype(np.int64)
        j = ((b - b.min()) / px).astype(np.int64)
        key = i * (j.max() + 1) + j
        zb = np.full(key.max() + 1, -np.inf)
        np.maximum.at(zb, key, z)
        front = z >= zb[key] - tol
        vis[tri[front]] = True
        facing[tri[front & (Ns @ d > 0)]] = True
    return vis, vis & ~facing


def signed_distance(X, Pb, Fb, kq: int = 12) -> np.ndarray:
    """Exact signed distance of the points ``X`` to the closed body ``(Pb, Fb)`` (negative inside, by the outward
    winding normal of the nearest of the ``kq`` nearest faces by centroid)."""
    from scipy.spatial import cKDTree
    from app.core.garment_fit import point_triangle_closest
    X = np.asarray(X, np.float64)
    Pb = np.asarray(Pb, np.float64)
    Fb = np.asarray(Fb, np.int64).reshape(-1, 3)
    vol = np.einsum("ij,ij->i", Pb[Fb[:, 0]], np.cross(Pb[Fb[:, 1]], Pb[Fb[:, 2]])).sum() / 6
    Cb = Pb[Fb].mean(1)
    kq = min(kq, len(Fb))
    _, cand = cKDTree(Cb).query(X, k=kq)
    cand = cand.reshape(len(X), -1)
    best = np.full(len(X), np.inf)
    sgn = np.ones(len(X))
    Nb = np.cross(Pb[Fb[:, 1]] - Pb[Fb[:, 0]], Pb[Fb[:, 2]] - Pb[Fb[:, 0]]) * np.sign(vol)
    for j in range(cand.shape[1]):
        f = Fb[cand[:, j]]
        cp = point_triangle_closest(X, Pb[f[:, 0]], Pb[f[:, 1]], Pb[f[:, 2]])
        d = np.linalg.norm(X - cp, axis=1)
        better = d < best
        best = np.where(better, d, best)
        sgn = np.where(better, np.sign(((X - cp) * Nb[cand[:, j]]).sum(1) + 1e-12), sgn)
    return best * sgn


def inside_share(X, Pb, Fb, depth: float = INSIDE_M) -> float:
    """Share of the points ``X`` more than ``depth`` under the surface of the body ``(Pb, Fb)``."""
    if len(X) == 0:
        return 0.0
    return float((signed_distance(X, Pb, Fb) < -depth).mean())


def subdivide(V, F, attrs):
    """One midpoint subdivision of ``(V, F)`` carrying the per-vertex ``attrs``."""
    E = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), 1)
    Eu, inv = np.unique(E, axis=0, return_inverse=True)
    inv = inv.ravel()
    m = len(V) + np.arange(len(Eu))
    nF = len(F)
    a, b, c = m[inv[:nF]], m[inv[nF:2 * nF]], m[inv[2 * nF:]]
    F2 = np.concatenate([np.stack([F[:, 0], a, c], 1), np.stack([a, F[:, 1], b], 1),
                         np.stack([c, b, F[:, 2]], 1), np.stack([a, b, c], 1)])

    def mid(X):
        return np.concatenate([X, 0.5 * (X[Eu[:, 0]] + X[Eu[:, 1]])])
    return mid(V), F2, mid(attrs)


def clip_triangles(P, F, sval, attrs):
    """Marching triangles: the part of each triangle where ``sval >= 0`` (new vertices on the cut edges, shared per
    edge). Returns ``(P, F, attrs)``."""
    cache: Dict[Tuple[int, int], int] = {}
    n0 = len(P)
    extra_P: List[np.ndarray] = []
    extra_A: List[np.ndarray] = []

    def cut(a, b):
        key = (min(a, b), max(a, b))
        if key not in cache:
            t = sval[a] / (sval[a] - sval[b])
            extra_P.append(P[a] + t * (P[b] - P[a]))
            extra_A.append(attrs[a] + t * (attrs[b] - attrs[a]))
            cache[key] = n0 + len(extra_P) - 1
        return cache[key]
    ins = sval[F] >= 0
    cnt = ins.sum(1)
    new_F = []
    part = (cnt == 1) | (cnt == 2)
    for f, m in zip(F[part], ins[part]):
        r = int(np.argmax(m)) if m.sum() == 1 else int(np.argmin(m))
        a, b, c = int(f[r]), int(f[(r + 1) % 3]), int(f[(r + 2) % 3])
        ab, ac = cut(a, b), cut(a, c)
        if m.sum() == 1:
            new_F.append([a, ab, ac])
        else:
            new_F.append([ab, b, c])
            new_F.append([ab, c, ac])
    Fo = np.concatenate([F[cnt == 3], np.array(new_F, dtype=np.int64).reshape(-1, 3)])
    Po = np.concatenate([P, np.array(extra_P).reshape(-1, P.shape[1])]) if extra_P else P
    Ao = np.concatenate([attrs, np.array(extra_A).reshape(-1, attrs.shape[1])]) if extra_A else attrs
    return Po, Fo, Ao


# --- the side bridge (A48b) ---------------------------------------------------------------------------------------

class TorsoFrame:
    """Torso coordinates: height y and the angle around the torso axis (0 front, ±90 sides, 180 back)."""

    def __init__(self, P_torso):
        from scipy import ndimage
        y = P_torso[:, 1]
        self.y0 = y.min()
        nb = int(np.ceil((y.max() - self.y0) / 0.01)) + 1
        b = ((y - self.y0) / 0.01).astype(int)
        cx = np.full(nb, np.nan)
        cz = np.full(nb, np.nan)
        for i in np.unique(b):
            s = P_torso[b == i]
            cx[i] = 0.5 * (s[:, 0].min() + s[:, 0].max())
            cz[i] = 0.5 * (s[:, 2].min() + s[:, 2].max())
        ok = np.isfinite(cx)
        idx = np.arange(nb)
        self.cx = ndimage.gaussian_filter1d(np.interp(idx, idx[ok], cx[ok]), 2)
        self.cz = ndimage.gaussian_filter1d(np.interp(idx, idx[ok], cz[ok]), 2)

    def coords(self, P):
        i = np.clip((P[:, 1] - self.y0) / 0.01, 0, len(self.cx) - 1)
        cx = np.interp(i, np.arange(len(self.cx)), self.cx)
        cz = np.interp(i, np.arange(len(self.cz)), self.cz)
        th = np.degrees(np.arctan2(P[:, 0] - cx, P[:, 2] - cz))
        return th, P[:, 1], np.hypot(P[:, 0] - cx, P[:, 2] - cz)


def _runs(flags) -> List[Tuple[int, int]]:
    out = []
    i = 0
    while i < len(flags):
        if flags[i]:
            j = i
            while j + 1 < len(flags) and flags[j + 1]:
                j += 1
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def extend_run(run, wide) -> Tuple[int, int]:
    """A220: the run ``(i0, i1)`` grown down from ``i0`` and up from ``i1`` over the consecutive bins ``wide``
    (bool per bin) marks."""
    i0, i1 = run
    while i0 - 1 >= 0 and wide[i0 - 1]:
        i0 -= 1
    while i1 + 1 < len(wide) and wide[i1 + 1]:
        i1 += 1
    return int(i0), int(i1)


def match_runs(front_runs, back_runs) -> List[Optional[int]]:
    """A220: per front run ``(i0, i1)`` (height bins) the back run it is bridged to round the side, or None. A run
    pair whose height ranges OVERLAP is matched (the larger overlap first, then the nearer centre): a bra's cup ends
    tall at the side (14 cm) and the back band narrow (11 cm) with centres 3.9 cm apart — the centre rule alone
    (≤ ``MATCH_M``) left the side open. Without an overlap the centres must lie within ``MATCH_M``."""
    out: List[Optional[int]] = []
    for i0, i1 in front_runs:
        c = 0.5 * (i0 + i1)
        best = None
        for k, (j0, j1) in enumerate(back_runs):
            ov = min(i1, j1) - max(i0, j0) + 1
            d = abs(0.5 * (j0 + j1) - c) * BIN_M
            if ov <= 0 and d > MATCH_M:
                continue
            key = (-max(ov, 0), d)
            if best is None or key < best[0]:
                best = (key, k)
        out.append(None if best is None else best[1])
    return out


#: A220: how far (degrees round the trunk) a side bridge reads into its panel before the read turns back (a
#: triangle wave: the panel's edge strip is mirrored, then repeated).
PANEL_READ_DEG = 20.0


def panel_source_angle(th, edge, front: bool, span: float = PANEL_READ_DEG):
    """A220: the angle (``TorsoFrame`` theta, degrees, signed: + one side, - the other) a side-bridge point at
    ``th`` reads its colour from: its mirror image across the panel's ``edge`` angle, back into the panel (the
    front panel lies toward theta 0, the back toward ±180), folded into ``span`` degrees from the edge — 5° past
    the edge reads 5° inside it, 25° past it (span 20) reads 15° inside."""
    th = np.asarray(th, np.float64)
    edge = np.asarray(edge, np.float64)
    sgn = np.where(edge >= 0, 1.0, -1.0)
    d = np.abs(th - edge)
    d = span - np.abs(np.mod(d, 2.0 * span) - span)
    return edge - sgn * d if front else edge + sgn * d


class SideBridge:
    """Per body side: the bands reaching the front view's head-on edge matched to those reaching the back's by height
    (≤ ``MATCH_M``) and carried around the side (lerped in height); an unmatched band end extends ``EXT_M``. The
    window a band 'reaches the edge' in is chosen per side (narrow unless that leaves more ends unmatched)."""

    def __init__(self, frame: TorsoFrame, P, headon_f, headon_b, memb_f, memb_b):
        from scipy import ndimage
        self.frame = frame
        th, y, _r = frame.coords(P)
        self.ylo = y.min() - 0.01
        nb = int(np.ceil((y.max() + 0.01 - self.ylo) / BIN_M)) + 1
        self.nb = nb
        bins = ((y - self.ylo) / BIN_M).astype(int)
        self.sides: Dict[int, Dict[str, Any]] = {}
        self.window: Dict[int, Tuple[float, int]] = {}
        for sgn in (1, -1):
            a = sgn * th
            onside = a > 0
            fe = np.full(nb, np.nan)
            be = np.full(nb, np.nan)
            for i in range(nb):
                sel = (bins == i) & onside
                if not sel.any():
                    continue
                if (sel & headon_f).any():
                    fe[i] = a[sel & headon_f].max()
                if (sel & headon_b).any():
                    be[i] = a[sel & headon_b].min()
            for e in (fe, be):
                ok = np.isfinite(e)
                if ok.sum() > 2:
                    e[:] = np.interp(np.arange(nb), np.nonzero(ok)[0], ndimage.median_filter(e[ok], 9))

            def reach(ed, eb):
                ff = np.zeros(nb, bool)
                bf = np.zeros(nb, bool)
                for i in range(nb):
                    sel = (np.abs(bins - i) <= eb) & onside
                    if np.isfinite(fe[i]):
                        ff[i] = (sel & memb_f & (a >= fe[i] - ed)).any()
                    if np.isfinite(be[i]):
                        bf[i] = (sel & memb_b & (a <= be[i] + ed)).any()
                return ff, bf

            def build(ed, eb):
                ff, bf = reach(ed, eb)

                def end_angle(run, memb, front):
                    i0, i1 = run
                    sel = (bins >= i0) & (bins <= i1) & onside & memb
                    if not sel.any():
                        return None
                    vals = [a[sel & (bins == i)].max() if front else a[sel & (bins == i)].min()
                            for i in range(i0, i1 + 1) if (sel & (bins == i)).any()]
                    return float(np.median(vals))
                # A220: a run reaches up / down as far as its panel still shows near the edge (the wide window) —
                # the narrow window's run ended below the panel's corner, the bridge's top dipped under it and the
                # panel's last head-on column stood up as a corner
                ffw, bfw = reach(WINDOWS[-1][0], WINDOWS[-1][1])
                fr = [(extend_run(r, ffw), end_angle(extend_run(r, ffw), memb_f, True)) for r in _runs(ff)]
                brn = [(extend_run(r, bfw), end_angle(extend_run(r, bfw), memb_b, False)) for r in _runs(bf)]
                pairs = []
                usedb = set()
                match = match_runs([r for r, _ in fr], [r for r, _ in brn])
                for ((i0, i1), fa), k in zip(fr, match):
                    if k is not None:
                        pairs.append(((i0, i1), brn[k][0], fa, brn[k][1]))
                        usedb.add(k)
                    else:
                        pairs.append(((i0, i1), None, fa, None))
                for k, (run, ba) in enumerate(brn):
                    if k not in usedb:
                        pairs.append((None, run, None, ba))
                return pairs
            best = None
            for ed, eb in WINDOWS:
                pr = build(ed, eb)
                unmatched = sum(1 for f_, b_, _, _ in pr if f_ is None or b_ is None)
                if best is None or unmatched < best[0]:
                    best = (unmatched, pr, (ed, eb))
            self.window[sgn] = best[2]
            self.sides[sgn] = {"fe": fe, "be": be, "pairs": best[1]}

    def query(self, P):
        """Per point: ``(margin m (> 0 on a bridge), t, front source y, back source y, theta, front end, back
        end)``."""
        th, y, r = self.frame.coords(P)
        n = len(P)
        margin = np.full(n, -0.01)
        t_out = np.full(n, np.nan)
        yf = np.full(n, np.nan)
        yb = np.full(n, np.nan)
        fe_out = np.full(n, np.nan)
        be_out = np.full(n, np.nan)
        for sgn, S in self.sides.items():
            a = sgn * th
            on = a > 0
            i = np.clip(((y - self.ylo) / BIN_M).astype(int), 0, self.nb - 1)
            fe, be = S["fe"][i], S["be"][i]
            fe_out = np.where(on, sgn * fe, fe_out)
            be_out = np.where(on, sgn * be, be_out)
            for fr, brn, fa, ba in S["pairs"]:
                if fr is not None and brn is not None:
                    fa_ = fa if fa is not None else fe
                    ba_ = ba if ba is not None else be
                    sp = ba_ - fa_
                    with np.errstate(invalid="ignore", divide="ignore"):
                        t = (a - fa_) / np.where(np.abs(sp) > 1e-6, sp, np.nan)
                    ins = on & np.isfinite(t) & (t > -0.02) & (t < 1.02)
                    tc = np.clip(np.nan_to_num(t), 0, 1)
                    lo = (fr[0] + (brn[0] - fr[0]) * tc) * BIN_M + self.ylo
                    hi = (fr[1] + (brn[1] - fr[1]) * tc) * BIN_M + self.ylo + BIN_M
                    m = np.minimum(y - lo, hi - y)
                    ok = ins & (m > margin)
                    margin = np.where(ok, m, margin)
                    t_out = np.where(ok, t, t_out)
                    yf = np.where(ok, y - (lo - (fr[0] * BIN_M + self.ylo)), yf)
                    yb = np.where(ok, y - (lo - (brn[0] * BIN_M + self.ylo)), yb)
                    fe_out = np.where(ok, sgn * fa_, fe_out)
                    be_out = np.where(ok, sgn * ba_, be_out)
                else:
                    run, from_front = (fr, True) if fr is not None else (brn, False)
                    end = fa if from_front else ba
                    if end is None:
                        continue
                    lo = run[0] * BIN_M + self.ylo
                    hi = (run[1] + 1) * BIN_M + self.ylo
                    d_arc = np.radians(np.maximum((a - end) if from_front else (end - a), 0)) * r
                    m = np.minimum(np.minimum(y - lo, hi - y), EXT_M - d_arc)
                    ok = on & (m > margin) & ((a >= end) if from_front else (a <= end))
                    margin = np.where(ok, m, margin)
                    t_out = np.where(ok, 0.0 if from_front else 1.0, t_out)
                    if from_front:
                        yf = np.where(ok, y, yf)
                        fe_out = np.where(ok, sgn * end, fe_out)
                    else:
                        yb = np.where(ok, y, yb)
                        be_out = np.where(ok, sgn * end, be_out)
        return margin, t_out, yf, yb, th, fe_out, be_out


# --- crotch bridge (A226) -------------------------------------------------------------------------------------------

#: A226: width of the crotch bridge's columns across the body (m).
CROTCH_BIN_M = 0.004
#: A226: a panel "reaches the crotch" when, within ``CROTCH_CENTRE_M`` of the body's middle, its lowest point lies at
#: most ``CROTCH_REACH_M`` above the lowest point its view sees head-on there (where the view's sight ends under the
#: body); a waist band ending higher is never bridged.
CROTCH_CENTRE_M = 0.006
CROTCH_REACH_M = 0.01
#: A226: the columns of a panel's crotch end — its bottom edge no more than this above the edge's lowest point (the
#: leg openings rise from there).
CROTCH_RISE_M = 0.015
#: A226: how far past a panel's edge (m, toward the other panel) a crotch point may lie and still be bridged at that
#: panel's width (its head-on rim under the edge), and how far it may lie above the line joining the two edges.
CROTCH_OVER_M = 0.02
CROTCH_ABOVE_M = 0.01
#: A226: ... and how far under the underside's middle line (``crotch_floor``): the inner thighs stay out.
CROTCH_UNDER_M = 0.005
#: A226: the Laplacian passes that relax the crotch bridge's shell over the body's folds.
CROTCH_RELAX = 30
#: A226: a crotch-bridge vertex whose normal points at least this much across (toward the other thigh) is never
#: lifted over the extension part.
CROTCH_SIDEWAYS = 0.5
#: A226: how far (m along the surface) a bridged crotch point reads into its panel before the read turns back.
CROTCH_READ_M = 0.02
#: A226: a piece whose views cover the middle column down to this far under the crotch is a skirt: never bridged
SKIRT_BELOW_M = 0.05
#: ... read from this far under it (a brief's tip stood 2 cm past the crotch in Glut's generated back view).
SKIRT_FROM_M = 0.03


def crotch_run(x, y, z, memb, headon, xc: float):
    """A226: the crotch end of ONE panel (front or back): ``(x0, x1, y_edge, z_edge)`` — the x range (m) of the
    columns (``CROTCH_BIN_M``) round the body's middle ``xc`` whose lowest member point lies within
    ``CROTCH_RISE_M`` of the panel's lowest point there, and that edge's median height / depth — or None when the
    panel does not reach the crotch (``CROTCH_REACH_M``) or has no member point at the middle."""
    x, y, z = (np.asarray(a, np.float64) for a in (x, y, z))
    memb, headon = np.asarray(memb, bool), np.asarray(headon, bool)
    mid = np.abs(x - xc) <= CROTCH_CENTRE_M
    if not (mid & memb).any() or not (mid & headon).any():
        return None
    if y[mid & memb].min() - y[mid & headon].min() > CROTCH_REACH_M:
        return None
    n = int(np.ceil(0.12 / CROTCH_BIN_M))
    edges = xc + (np.arange(-n, n + 1) - 0.5) * CROTCH_BIN_M
    b = np.searchsorted(edges, x) - 1
    low = np.full(2 * n, np.inf)
    ok = memb & (b >= 0) & (b < 2 * n)
    np.minimum.at(low, b[ok], y[ok])
    c = n
    floor = low[c - 1:c + 1].min()
    i0 = i1 = c
    while i0 - 1 >= 0 and low[i0 - 1] <= floor + CROTCH_RISE_M:
        i0 -= 1
    while i1 + 1 < 2 * n and low[i1 + 1] <= floor + CROTCH_RISE_M:
        i1 += 1
    sel = ok & (b >= i0) & (b <= i1)
    sel &= y <= low[np.clip(b, 0, 2 * n - 1)] + 0.002     # each column's bottom edge
    return float(edges[i0]), float(edges[i1 + 1]), float(np.median(y[sel])), float(np.median(z[sel]))


def crotch_floor(P, xc: float, front, back):
    """A226: the underside's height along the body's middle between the two edges — ``(z, y)`` per
    ``CROTCH_BIN_M`` of depth: the lowest point of ``P`` within ``CROTCH_CENTRE_M`` of ``xc`` (gaps interpolated),
    or None without such points. Nothing under it is bridged (the inner thighs run on down from there)."""
    P = np.asarray(P, np.float64)
    zb, zf = back[3], front[3]
    mid = (np.abs(P[:, 0] - xc) <= CROTCH_CENTRE_M) & (P[:, 2] >= zb - CROTCH_OVER_M) & (P[:, 2] <= zf + CROTCH_OVER_M)
    if mid.sum() < 2:
        return None
    zs = np.arange(zb - CROTCH_OVER_M, zf + CROTCH_OVER_M + CROTCH_BIN_M, CROTCH_BIN_M)
    i = np.clip(((P[mid, 2] - zs[0]) / CROTCH_BIN_M).astype(int), 0, len(zs) - 1)
    ys = np.full(len(zs), np.inf)
    np.minimum.at(ys, i, P[mid, 1])
    ok = np.isfinite(ys)
    return zs, np.interp(zs, zs[ok], ys[ok])


def crotch_bridge(P, front, back, floor=None):
    """A226: per point ``P`` (m, the rigged body: x across, y up, z forward) of the region: ``(margin m, t)`` on the
    bridge under the crotch between the ``front`` and the ``back`` panel's ``crotch_run`` — ``t`` 0 at the front
    edge, 1 at the back edge (by depth z); the band's x range runs linearly from the front run's to the back run's
    width; ``margin`` is the distance (m) to the nearer side of the band, -0.01 off the bridge (past an edge by
    more than ``CROTCH_OVER_M``, above the line joining the edges by more than ``CROTCH_ABOVE_M``, under ``floor``
    (``crotch_floor``) by more than ``CROTCH_UNDER_M``)."""
    P = np.asarray(P, np.float64)
    fx0, fx1, fy, fz = front
    bx0, bx1, by, bz = back
    span = fz - bz
    margin = np.full(len(P), -0.01)
    if span <= 1e-3:
        return margin, np.full(len(P), np.nan)
    t = (fz - P[:, 2]) / span
    tc = np.clip(t, 0.0, 1.0)
    lo = fx0 + (bx0 - fx0) * tc
    hi = fx1 + (bx1 - fx1) * tc
    m = np.minimum(P[:, 0] - lo, hi - P[:, 0])
    over = CROTCH_OVER_M / span
    top = fy + (by - fy) * tc + CROTCH_ABOVE_M
    on = (t >= -over) & (t <= 1 + over) & (P[:, 1] <= top)
    if floor is not None:
        on &= P[:, 1] >= np.interp(P[:, 2], floor[0], floor[1]) - CROTCH_UNDER_M
    margin = np.where(on, np.maximum(m, -0.01), margin)
    return margin, t


def crotch_source(P, t, front, back, read: float = CROTCH_READ_M):
    """A226: where a bridged crotch point ``P`` (``t`` from ``crotch_bridge``) reads its colour: ``(front y, back
    y)`` — the height in the front panel and in the back panel at the same x, mirrored across the panel's edge
    (as far past the edge as the point lies, along the surface, back into the panel) and folded into ``read``
    metres: 5 mm past the front edge reads 5 mm above it, 25 mm past it (read 20 mm) 15 mm above it."""
    P = np.asarray(P, np.float64)
    out = []
    for _x0, _x1, ey, ez in (front, back):
        d = np.hypot(P[:, 2] - ez, P[:, 1] - ey)
        d = read - np.abs(np.mod(d, 2.0 * read) - read)
        out.append(ey + d)
    return out[0], out[1]


# --- limb rings (A192) ----------------------------------------------------------------------------------------------

#: A192: the limbs a shell is closed round. The torso's side bridge works in ONE frame round the trunk's axis; a leg
#: has a side of its own toward the other leg and one outward, and neither camera sees them head-on — the lace
#: stockings stayed open in a strip down both sides of each leg. Per limb: the joint-name tokens whose weights mark it.
LIMBS: Tuple[Tuple[str, ...], ...] = (("LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToe"),
                                      ("RightUpLeg", "RightLeg", "RightFoot", "RightToe"))
#: Height of a limb ring (m).
RING_BIN_M = 0.004
#: A ring's view counts with at least this many head-on points; it is "worn" when this share of them is.
RING_MIN_POINTS = 3
RING_SHARE = 0.5


def limb_columns(joint_names, limbs: Tuple[Tuple[str, ...], ...] = LIMBS) -> List[List[int]]:
    """Per limb the indices in ``joint_names`` of its joints (a name that contains one of the limb's tokens)."""
    return [[i for i, n in enumerate(joint_names) if any(t in str(n) for t in limb)] for limb in limbs]


def ring_worn(y, limb, head_f, memb_f, head_b, memb_b, front_facing):
    """A192, the limb rule: a point of ``limb`` (bool) that no view sees head-on is worn when the limb's head-on
    points in its ring (``RING_BIN_M`` of height ``y``) are — in the front view AND in the back view; where only one
    view has head-on points in the ring, or the two disagree (a slanted top edge), the view the point faces
    (``front_facing``) decides. Returns bool (worn by the ring); False outside the limb and in a ring without
    head-on points."""
    from scipy import ndimage
    y = np.asarray(y, np.float64)
    out = np.zeros(len(y), bool)
    if not limb.any():
        return out
    y0 = y[limb].min()
    b = np.clip(((y - y0) / RING_BIN_M).astype(int), 0, None)
    nb = int(b[limb].max()) + 1
    state = {}
    for key, head, memb in (("f", head_f, memb_f), ("b", head_b, memb_b)):
        n = np.bincount(b[limb & head], minlength=nb)[:nb]
        m = np.bincount(b[limb & head & memb], minlength=nb)[:nb]
        known = n >= RING_MIN_POINTS
        worn = known & (m >= RING_SHARE * np.maximum(n, 1))
        if known.sum() > 5:
            worn = known & (ndimage.median_filter(np.where(known, worn, False).astype(np.uint8), 5) > 0)
        state[key] = (known, worn)
    (kf, wf), (kb, wb) = state["f"], state["b"]
    bi = b[limb]
    ff = np.asarray(front_facing, bool)[limb]
    pick_f = np.where(kf[bi] & kb[bi], np.where(wf[bi] == wb[bi], True, ff), kf[bi])
    out[limb] = np.where(pick_f, wf[bi], wb[bi]) & (kf[bi] | kb[bi])
    return out


def ring_closed(y, limb, head_f, memb_f, head_b, memb_b, near_f, near_b):
    """A219, the misregistered tube: a HEAD-ON point of ``limb`` (bool) that a view misses only by misregistration
    (``near_f`` / ``near_b``: head-on in that view and on its ``misregistered_strip``) is worn when
    its ring (``RING_BIN_M`` of height ``y``) is worn in the front view AND in the back view (``ring_worn``'s per-view
    rule, median-filtered over 5 rings), or — below the lowest such ring, toward the foot — in either view. A
    generated leg standing wider than the body's leaves the body's inner calf a strip outside the ghost; a real
    opening (a cut-out inside the silhouette, a slit, a diagonal or high-low hem, a toeless foot) is no such strip and
    stays open. Returns bool; False outside the limb."""
    from scipy import ndimage
    y = np.asarray(y, np.float64)
    out = np.zeros(len(y), bool)
    if not limb.any():
        return out
    y0 = y[limb].min()
    b = np.clip(((y - y0) / RING_BIN_M).astype(int), 0, None)
    nb = int(b[limb].max()) + 1
    both = np.ones(nb, bool)
    either = np.zeros(nb, bool)
    for head, memb in ((head_f, memb_f), (head_b, memb_b)):
        n = np.bincount(b[limb & head], minlength=nb)[:nb]
        m = np.bincount(b[limb & head & memb], minlength=nb)[:nb]
        known = n >= RING_MIN_POINTS
        worn = known & (m >= RING_SHARE * np.maximum(n, 1))
        if known.sum() > 5:
            worn = known & (ndimage.median_filter(worn.astype(np.uint8), 5) > 0)
        both &= worn
        either |= worn
    rings = both.copy()
    if both.any():
        for i in range(int(np.nonzero(both)[0].min()) - 1, -1, -1):
            if not either[i]:
                break
            rings[i] = True
    near = (np.asarray(head_f, bool) & np.asarray(near_f, bool)) | (np.asarray(head_b, bool) & np.asarray(near_b, bool))
    out[limb] = rings[b[limb]] & near[limb]
    return out


#: A219: the most a generated view's limb may stand off the body's (mm) and still count as misregistration
#: (``misregistered_strip``): Kira's lace stockings' back view missed the inner calf by up to ~25 mm.
MISREG_MM = 30.0
#: A219: a misregistered limb stands OUT of the body's figure on its other side: ghost pixels at least
#: ``MISREG_MM / 3`` outside the figure within this distance (mm) along the same image row.
MISREG_SPAN_MM = 150.0


def _row_distance(mask) -> np.ndarray:
    """Per pixel the distance (px) to the nearest True pixel of ``mask`` in the SAME row (inf-like where the row has
    none)."""
    from scipy import ndimage
    m = np.asarray(mask, bool)
    if not m.any():
        return np.full(m.shape, np.inf)
    return ndimage.distance_transform_edt(~m, sampling=(1e4, 1.0))


def misregistered_strip(ghost, body, mm_px: float) -> np.ndarray:
    """A219: the pixels of a view where the body shows bare only because the generated piece-only view stands off
    the body's figure: inside the body's figure and within ``MISREG_MM`` of its edge, outside the ghost's outline
    with its holes filled (a cut-out stays open), within ``MISREG_MM`` of the ghost along the same row (a hem, a
    toeless foot — no ghost in the row — stays open), and the ghost stands out of the figure (by ``MISREG_MM / 3``)
    within ``MISREG_SPAN_MM`` along the row (a slit inside a piece that fits the figure stays open). Bool, the
    view's shape."""
    from scipy import ndimage
    g = np.asarray(ghost, bool)
    bm = np.asarray(body, bool)
    px = MISREG_MM / float(mm_px)
    hull = ndimage.binary_fill_holes(g)
    depth = ndimage.distance_transform_edt(bm)
    out = g & ~ndimage.binary_dilation(bm, iterations=max(1, int(np.ceil(px / 3.0))))
    return (bm & ~hull & (depth <= px) & (_row_distance(g) <= px)
            & (_row_distance(out) <= MISREG_SPAN_MM / float(mm_px)))

#: A219: words that make a piece SEE-THROUGH (``see_through_text``) — only such a piece's views lose their backdrop
#: (``unmix_backdrop``); an opaque melange, rib or glitter keeps its colours.
SEE_THROUGH_WORDS = frozenset({"lace", "lacy", "net", "netted", "fishnet", "fishnets", "mesh", "sheer", "tulle",
                               "chiffon", "organza", "voile", "transparent", "see-through", "seethrough", "spitze",
                               "netz", "durchsichtig", "crochet", "openwork"})
#: German compounds (``Spitzenstrümpfe``, ``Netzstrumpfhose``) start with these.
SEE_THROUGH_PREFIXES = ("spitzen", "netz", "fishnet", "lace")
#: The gate of a view (``unmix_backdrop``): at least this share of its inner pixels mixed with the backdrop ...
SEE_THROUGH_MIN_SHARE = 0.15
#: ... at least this share pure fabric (the two clusters of a lace: threads and openings) ...
SEE_THROUGH_MIN_PURE = 0.2
#: ... and at least this share of the mixed pixels within ``SEE_THROUGH_NEAR_PX`` of pure fabric (interleaved).
SEE_THROUGH_INTERLEAVE = 0.4
SEE_THROUGH_NEAR_PX = 4
#: A pixel is on the fabric→backdrop line when it lies at most this far (RGB) off it, with a backdrop share between
#: ``-SEE_THROUGH_T_OVER`` and ``1 + SEE_THROUGH_T_OVER``; mixed from ``SEE_THROUGH_T_MIN`` up, pure below
#: ``SEE_THROUGH_T_PURE``.
SEE_THROUGH_RESIDUAL = 15.0
SEE_THROUGH_T_OVER = 0.05
SEE_THROUGH_T_MIN = 0.15
SEE_THROUGH_T_PURE = 0.08
#: The backdrop must be neutral: its channels at most this far apart (a tinted backdrop is no reference).
SEE_THROUGH_BG_CHROMA = 12.0


def see_through_text(*texts: Any) -> bool:
    """A219: whether the piece's name / noun / prompt fragment names a see-through fabric (``SEE_THROUGH_WORDS``,
    whole words, hyphenated "see-through" included, or a compound starting with ``SEE_THROUGH_PREFIXES``)."""
    import re
    for text in texts:
        for word in re.findall(r"[a-zäöüß]+(?:-[a-zäöüß]+)?", str(text or "").lower()):
            if word in SEE_THROUGH_WORDS or any(part in SEE_THROUGH_WORDS for part in word.split("-")):
                return True
            if any(word.startswith(p) and len(word) > len(p) + 2 for p in SEE_THROUGH_PREFIXES):
                return True
    return False


def unmix_backdrop(image, ghost_mask, apply: Optional[bool] = None) -> Tuple[np.ndarray, Dict[str, Any]]:
    """A219: the piece-only view of a see-through piece shows its openings as a mix of the fabric and the view's
    BACKDROP — black lace on the grey / white backdrop bakes as a grey, mottled texture although the piece is black.
    The backdrop ``bg`` = the median outside the mask (dilated 6 px); the fabric ``F`` = the median of the darkest
    10 % of the mask's inner pixels, refined once to the median of the pure cluster (backdrop share ``T`` below
    ``SEE_THROUGH_T_PURE``). A pixel ``c = F + T (bg - F) + r`` with ``|r| <= SEE_THROUGH_RESIDUAL`` and ``T`` within
    ``[-SEE_THROUGH_T_OVER, 1 + SEE_THROUGH_T_OVER]`` is on the line. ``info["gate"]``: the view looks like a lace —
    a neutral backdrop (``SEE_THROUGH_BG_CHROMA``), ``SEE_THROUGH_MIN_SHARE`` mixed, ``SEE_THROUGH_MIN_PURE`` pure,
    ``SEE_THROUGH_INTERLEAVE`` of the mixed next to pure fabric. ``apply``: True takes the backdrop share out of
    every pixel on the line (``c - clip(T, 0, 1) (bg - F)``), False never, None when the gate holds (``build_shell``
    decides once per piece). ``info``: ``gate``, ``see_through`` (applied), ``mixed_share``, ``pure_share``,
    ``interleave``."""
    from scipy import ndimage
    img = np.asarray(image, np.float64)[..., :3]
    gm = np.asarray(ghost_mask, bool)
    info: Dict[str, Any] = {"gate": False, "see_through": False}
    outside = ~ndimage.binary_dilation(gm, iterations=6)
    inner = ndimage.binary_erosion(gm, iterations=3)
    if outside.sum() < 100 or inner.sum() < 100:
        return img, info
    bg = np.median(img[outside], 0)
    c = img[inner]
    lum = c.mean(1)
    F = np.median(c[lum <= np.percentile(lum, 10)], 0)
    d = bg - F
    dd = float(d @ d)
    if dd < 40.0 ** 2:          # the fabric is the backdrop's colour: nothing to tell apart
        return img, info

    def line(F_):
        d_ = bg - F_
        T_ = ((img - F_) @ d_) / float(d_ @ d_)
        res_ = np.linalg.norm(img - F_ - T_[..., None] * d_, axis=-1)
        on_ = gm & (res_ <= SEE_THROUGH_RESIDUAL) & (T_ >= -SEE_THROUGH_T_OVER) & (T_ <= 1.0 + SEE_THROUGH_T_OVER)
        return d_, T_, on_
    d, T, on_line = line(F)
    pure0 = on_line & inner & (T < SEE_THROUGH_T_PURE)
    if pure0.sum() >= 10:
        F = np.median(img[pure0], 0)
        if float((bg - F) @ (bg - F)) < 40.0 ** 2:
            return img, info
        d, T, on_line = line(F)
    mixed = on_line & (T >= SEE_THROUGH_T_MIN) & inner
    pure = on_line & (T < SEE_THROUGH_T_PURE)
    near = ndimage.binary_dilation(pure, iterations=SEE_THROUGH_NEAR_PX)
    share = float(mixed.sum()) / float(inner.sum())
    pure_share = float((pure & inner).sum()) / float(inner.sum())
    inter = float((mixed & near).sum()) / max(int(mixed.sum()), 1)
    neutral = float(bg.max() - bg.min()) <= SEE_THROUGH_BG_CHROMA
    info.update(mixed_share=round(share, 3), pure_share=round(pure_share, 3), interleave=round(inter, 3),
                gate=bool(neutral and share >= SEE_THROUGH_MIN_SHARE and pure_share >= SEE_THROUGH_MIN_PURE
                          and inter >= SEE_THROUGH_INTERLEAVE))
    if not (info["gate"] if apply is None else apply):
        return img, info
    info["see_through"] = True
    out = img.copy()
    t = np.clip(T, 0.0, 1.0)
    out[on_line] = img[on_line] - t[on_line][:, None] * d
    return np.clip(out, 0, 255), info


def mirror_into(x, lo, hi):
    """``x`` folded back into [``lo``, ``hi``] like a pattern mirrored at both ends (a triangle wave): the picture
    between ``lo`` and ``hi`` continues past either end without a seam."""
    span = np.maximum(np.asarray(hi, np.float64) - lo, 1e-9)
    u = np.mod(np.asarray(x, np.float64) - lo, 2.0 * span)
    return lo + np.where(u > span, 2.0 * span - u, u)


# --- the shell ------------------------------------------------------------------------------------------------------

def _bridge_mm(marg, margin_mm: float):
    """The side bridge's margin (m) as membership mm, grown by ``margin_mm`` where the bridge measured a real margin
    (its "no bridge" value -0.01 m stays outside)."""
    mm = np.asarray(marg, np.float64) * 1000.0
    return np.clip(np.where(mm > -9.99, mm + margin_mm, mm), -5, 5 + margin_mm)


def boundary_loops(P, F) -> List[List[int]]:
    """The boundary loops of the mesh ``(P, F)`` (vertex indices into ``P``, welded by position first; each loop as
    a list of ORIGINAL vertex indices, one representative per welded vertex)."""
    from app.core import garment_fit as gf
    Pw, Fw, inv = gf.weld(P, F)
    rep = np.zeros(len(Pw), np.int64)
    rep[inv] = np.arange(len(inv))
    E = np.concatenate([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]])
    key = np.sort(E, 1)
    u, cnt = np.unique(key, axis=0, return_counts=True)
    border = {(int(a), int(b)) for a, b in u[cnt == 1]}
    nxt: Dict[int, int] = {}
    for a, b in E:
        if (min(a, b), max(a, b)) in border:
            nxt[int(a)] = int(b)
    seen: set = set()
    loops = []
    for start in list(nxt):
        if start in seen:
            continue
        loop = [start]
        seen.add(start)
        v = nxt[start]
        while v != start and v in nxt and v not in seen:
            loop.append(v)
            seen.add(v)
            v = nxt[v]
        if v == start and len(loop) >= 3:
            loops.append([int(rep[w]) for w in loop])
    return loops


def loop_area(P, loop) -> float:
    """Area (m²) of the fan over a closed loop of points (the hole it encloses)."""
    Q = P[loop]
    c = Q.mean(0)
    return float(0.5 * np.linalg.norm(np.cross(Q - c, np.roll(Q, -1, 0) - c).sum(0)))


def fill_small_holes(P, F, attrs, max_area: float):
    """A184: close every hole of the mesh smaller than ``max_area`` (m²) with a fan from its centroid — a hole is
    a boundary loop that is not the longest loop of its connected part. Returns ``(P, F, attrs, closed)``."""
    from app.core import garment_fit as gf
    if max_area <= 0 or len(F) == 0:
        return P, F, attrs, 0
    loops = boundary_loops(P, F)
    if not loops:
        return P, F, attrs, 0
    Pw, Fw, inv = gf.weld(P, F)
    lab, _ = gf.components(Pw, Fw)
    per = [float(np.linalg.norm(P[lp] - P[np.roll(lp, -1)], axis=1).sum()) for lp in loops]
    longest: Dict[int, int] = {}
    for i, lp in enumerate(loops):
        c = int(lab[inv[lp[0]]])
        if c not in longest or per[i] > per[longest[c]]:
            longest[c] = i
    newP, newA, newF = [], [], []
    n = len(P)
    for i, lp in enumerate(loops):
        if longest.get(int(lab[inv[lp[0]]])) == i or loop_area(P, lp) >= max_area:
            continue
        ci = n + len(newP)
        newP.append(P[lp].mean(0))
        newA.append(attrs[lp].mean(0))
        # the loop runs with the boundary edges' orientation: the fan reverses it to match the faces' winding
        newF += [[lp[(k + 1) % len(lp)], lp[k], ci] for k in range(len(lp))]
    if not newP:
        return P, F, attrs, 0
    return (np.concatenate([P, np.array(newP)]), np.concatenate([F, np.array(newF, np.int64)]),
            np.concatenate([attrs, np.array(newA)]), len(newP))


def side_view_ok(seen_s, facing_s, seen_f, facing_f, seen_b, facing_b) -> np.ndarray:
    """A185: per point, whether a side view's mask may decide it — the side view sees it (``seen_s``, the depth
    window) facing its camera at least ``SIDE_FACING_MIN`` (normal · view direction), and neither the front nor the
    back sees it at least ``FRONTAL_MIN`` frontally (there the front / back masks decide, a side never adds)."""
    frontal = ((np.asarray(seen_f, bool) & (np.abs(facing_f) >= FRONTAL_MIN))
               | (np.asarray(seen_b, bool) & (np.abs(facing_b) >= FRONTAL_MIN)))
    return np.asarray(seen_s, bool) & (np.asarray(facing_s, float) >= SIDE_FACING_MIN) & ~frontal


#: A191: a sample of a face whose vertices carry this much arm weight or more is the arm (as ``cov &= armw < 0.3``).
ARM_MAX = 0.3


#: A220: an arm whose head-on (front / back) points the piece's views cover at least this share of is the piece's
#: own (a glove, an arm warmer); below it the arm stays out of the shell (a top's views over a hanging arm).
ARM_PIECE_SHARE = 0.2


def arm_pieces(armw, x, head_seen, head_cov, share: float = ARM_PIECE_SHARE) -> Tuple[np.ndarray, Dict[str, float]]:
    """A220: per arm (the arm points — ``armw`` ≥ ``ARM_MAX`` — on one side of x = the trunk's middle) whether the
    piece covers it: the share of its head-on points ``head_seen`` that ``head_cov`` marks reaches ``share``.
    Returns ``(keep: bool per point — an arm point of a covered arm, shares by side "+x" / "-x")``."""
    armw = np.asarray(armw, np.float64)
    x = np.asarray(x, np.float64)
    arm = armw >= ARM_MAX
    keep = np.zeros(len(armw), bool)
    shares: Dict[str, float] = {}
    if not arm.any():
        return keep, shares
    mid = float(np.median(x[~arm])) if (~arm).any() else 0.0
    for name, side in (("+x", x > mid), ("-x", x <= mid)):
        pts = arm & side & np.asarray(head_seen, bool)
        sh = float((pts & np.asarray(head_cov, bool)).sum() / max(pts.sum(), 1))
        shares[name] = round(sh, 3)
        if pts.sum() and sh >= share:
            keep |= arm & side
    return keep, shares


def occluding_samples(which: str, X, tri, faces, armw) -> np.ndarray:
    """The body samples ``X`` (on faces ``tri``) that may hide a point from view ``which`` (its z-buffer): all of them
    for the front / back ("f" / "b"); for a side view only the trunk's — A191: the arm hangs beside the trunk in the
    base side view and the piece-only side view shows the piece where the arm was, so the arm never occludes the
    flank for a side view (with it the flank under the arm was never "seen" and the side views added little)."""
    X = np.asarray(X)
    if which in ("f", "b"):
        return X
    return X[np.asarray(armw, float)[np.asarray(faces)[np.asarray(tri)]].max(1) < ARM_MAX]


class ShellRefused(ValueError):
    """The shell cannot be made (no region, empty masks)."""


def _fill_glints(m, max_px: float = 0.0):
    """Close holes in a ghost mask below 0.1 % of its area (specular glints) or below ``max_px`` pixels (the
    piece's "Fill holes up to", A184), whichever is larger."""
    from scipy import ndimage
    holes = ndimage.binary_fill_holes(m) & ~m
    lab, n = ndimage.label(holes)
    if n:
        sz = np.bincount(lab.ravel())
        sz[0] = 0
        m = m | np.isin(lab, np.nonzero((sz > 0) & (sz < max(0.001 * m.sum(), max_px)))[0])
    return m


#: A220: a shell vertex is lifted over a surface the ray along its normal meets within this reach (m) and this
#: lateral radius (m) of the surface's samples, when the surface faces the same way (cosine at least
#: ``LIFT_FACING``); lifts under ``LIFT_MIN_M`` are noise of the surface's own curvature.
PART_REACH_M = 0.04
PART_RADIUS_M = 0.003
LIFT_FACING = 0.5
LIFT_MIN_M = 0.001


#: A226: shell vertices per vectorised chunk of ``lift_over_surfaces``.
LIFT_CHUNK = 20000
#: A226: the march's sphere radius in ``radius`` units (≥ √(1 + ¼) covers the cylinder between two steps) and the
#: samples per sphere (spacing ``radius``/2: ~16 on one surface).
LIFT_BALL = 1.2
LIFT_K = 64


def lift_over_surfaces(V, N, offset_m: float, surfaces, *, reach: float = PART_REACH_M,
                       radius: float = PART_RADIUS_M) -> Tuple[np.ndarray, np.ndarray]:
    """A220: the shell positions over the body point ``V`` along its unit normal ``N``: ``V + N × offset_m``, lifted
    to ``V + N × (t + offset_m)`` where the ray meets one of ``surfaces`` further out — a sample within ``radius`` of
    the ray at height ``t`` in (``LIFT_MIN_M``, ``reach``] whose face normal faces the ray's way (cosine ≥
    ``LIFT_FACING``; a surface facing back toward the vertex — the other thigh, a breast's underside — is not over
    it). ``surfaces``: ``[(P, F, oriented)]`` — ``oriented`` False takes the normal's sign as it comes (an extension
    part's winding is its own). The lift then spreads 2 rings (4 mm, halved per ring, taking the max) so a lifted
    patch's edge slopes instead of stepping. Returns ``(X, lift m per vertex)``."""
    from scipy.spatial import cKDTree
    V = np.asarray(V, np.float64)
    N = np.asarray(N, np.float64)
    if len(V) == 0:
        return V.copy(), np.zeros(0)
    # one ray per distinct position (a clipped shell repeats its seam vertices)
    Vw, first, inv = np.unique(np.round(V, 7), axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    Nw = N[first]
    lw = np.zeros(len(Vw))
    lo, hi = Vw.min(0) - reach, Vw.max(0) + reach
    for P, F, oriented in surfaces:
        P = np.asarray(P, np.float64)
        F = np.asarray(F, np.int64)
        if not len(F):
            continue
        C = P[F].mean(1)
        F = F[((C >= lo) & (C <= hi)).all(1)]
        if not len(F):
            continue
        S, _n, tri, _b = samples(P, F, radius * 0.5)
        Nf = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
        Nf = Nf / np.maximum(np.linalg.norm(Nf, axis=1, keepdims=True), 1e-12)
        NS = Nf[tri]
        tree = cKDTree(S)
        near = np.nonzero(np.isfinite(tree.query(Vw, distance_upper_bound=reach)[0]))[0]
        # A226: the ray is marched in steps of ``radius`` with a k-nearest query per step (spheres of radius
        # ``LIFT_BALL`` × radius cover the ray's cylinder) — the one ball round the ray's middle held every sample
        # within 2.3 cm, both thighs' at the crotch bridge, and the per-vertex loop over them took 95 s
        rb = radius * LIFT_BALL
        for c0 in range(0, len(near), LIFT_CHUNK):
            nc = near[c0:c0 + LIFT_CHUNK]
            for h in np.arange(LIFT_MIN_M, reach + radius, radius):
                dd, idx = tree.query(Vw[nc] + Nw[nc] * h, k=LIFT_K, distance_upper_bound=rb)
                hit = np.isfinite(dd)
                if not hit.any():
                    continue
                own = np.broadcast_to(nc[:, None], idx.shape)[hit]
                idx = idx[hit]
                nrm = Nw[own]
                d = S[idx] - Vw[own]
                t = np.einsum("ij,ij->i", d, nrm)
                lat = np.linalg.norm(d - t[:, None] * nrm, axis=1)
                cos = np.einsum("ij,ij->i", NS[idx], nrm)
                ok = (lat <= radius) & (t > LIFT_MIN_M) & (t <= reach) \
                    & ((cos if oriented else np.abs(cos)) >= LIFT_FACING)
                if ok.any():
                    np.maximum.at(lw, own[ok], t[ok])
    if (lw > 0).any():
        pairs = cKDTree(Vw).query_pairs(0.004, output_type="ndarray")
        for _ in range(2):
            if len(pairs):
                nxt = lw.copy()
                np.maximum.at(nxt, pairs[:, 0], 0.5 * lw[pairs[:, 1]])
                np.maximum.at(nxt, pairs[:, 1], 0.5 * lw[pairs[:, 0]])
                lw = nxt
    lift = lw[inv]
    return V + N * (offset_m + lift)[:, None], lift


def build_shell(rigged: bytes, unrigged: bytes, views: Dict[str, Dict[str, Any]], *,
                arm_tokens: Iterable[str] = ("Arm", "Hand"), offset_m: float = THICKNESS_M,
                margin_mm: float = MARGIN_DEFAULT, fill_cm2: float = FILL_DEFAULT, see_through: bool = False):
    """The shell of a piece on the body (module docstring) -> ``garment_fit.FitResult`` (``garment`` in the rigged
    body's bind space, skinned; ``metrics``: ``shell_faces``, ``inside_share``, ``over_skin_p50_mm``,
    ``side_colour_within_{1,2,5}cm``, ``seconds``). ``views``: ``{"front": {...}, "back": {...}}``, each
    ``body_mask`` (bool, the base view's figure), ``ghost_mask`` (bool, the piece-only view's), ``image`` (the
    piece-only view, RGB uint8, same size as its masks); the back view is mirrored onto the body when that matches
    its silhouette better. ``margin_mm`` (A184, "Take from the body"): the membership border is moved this far
    outward around the piece's outline in its views; ``fill_cm2`` ("Fill holes up to"): enclosed gaps of the
    piece's outline and of the body region up to this area are closed. ``see_through`` (A219, ``see_through_text``
    of the piece): its views may lose their backdrop (``unmix_backdrop``). ``ShellRefused`` when no region is found."""
    from scipy import ndimage
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree
    from PIL import Image
    from app.core import garment_fit as gf
    from app.core import glb_mesh
    started = time.monotonic()
    bu, br = glb_mesh.body_arrays(unrigged), glb_mesh.body_arrays(rigged)
    Pu = np.asarray(bu.positions, np.float64)
    R = np.asarray(br.positions, np.float64)
    k = float(np.ptp(R[:, 1])) / float(np.ptp(Pu[:, 1]))
    report: Dict[str, Any] = {"shell_version": SHELL_VERSION, "offset_mm": round(offset_m * 1000.0, 1),
                              "margin_mm": float(margin_mm), "fill_cm2": float(fill_cm2)}

    masks = {}
    # A185: the side views of a piece with "Side views for the shell" (left / right), read when given
    sides = [(key, w) for key, w in (("left", "l"), ("right", "r")) if views.get(key)]
    from app.core import cpu_progress
    shell_views = (("front", "f"), ("back", "b"), *sides)
    for view_no, (key, w) in enumerate(shell_views, 1):
        cpu_progress.sub("shell_views", view_no, len(shell_views))  # A194: live i/n, never raises
        v = views.get(key) or {}
        bm, gm = gf._mask(v["body_mask"]), gf._mask(v["ghost_mask"])
        if not bm.any():
            raise ShellRefused(f"The {key} view has no body")
        masks[w] = (bm, gm, np.asarray(v["image"], np.float64)[..., :3])
    # A219: a see-through piece (its name says so) whose views look like a lace loses the backdrop in EVERY view —
    # decided once for the piece; an opaque piece never
    gate = {w: unmix_backdrop(masks[w][2], masks[w][1], apply=False)[1] for _key, w in shell_views if w in masks}
    unmix = bool(see_through) and any(g_["gate"] for g_ in gate.values())
    report["see_through"] = {"named": bool(see_through), "applied": unmix,
                             **{key: gate[w] for key, w in shell_views if w in gate}}
    if unmix:
        for w in list(masks):
            bm_, gm_, img_ = masks[w]
            masks[w] = (bm_, gm_, unmix_backdrop(img_, gm_, apply=True)[0])
    if not (masks["f"][1].any() or masks["b"][1].any()):
        raise ShellRefused("The piece-only views show no piece")
    keys = list(masks)
    colour_mask = {w: masks[w][1] for w in keys}
    # A190: a side view made from the arms-up base side view is read on the body posed the same way; its positions
    # keep the rest mesh's indices (``pose_arms_up``)
    posed_keys = [w for key, w in sides if (views.get(key) or {}).get("arms_up")]
    corr_u2r = None
    Pp = Pu
    if posed_keys:
        corr_u2r, _ = gf.uv_correspondence(bu, br)
        Rp = pose_arms_up(R, br.joints, br.weights, br.joint_names, br.joint_positions)
        Pp = Pu + (Rp - R)[corr_u2r] / k
        report["arms_up_views"] = [key for key, w in sides if w in posed_keys]
        report["arms_up_tilt_deg"] = ARMS_UP_TILT_DEG
    #: the positions each view sees the body in (the posed ones for an arms-up side view)
    PV = {w: (Pp if w in posed_keys else Pu) for w in keys}
    frames = {w: gf._frame(PV[w], masks[w][0]) for w in keys}
    # mm per pixel of each view on the rigged body
    mm_px = {w: frames[w][0] * k * 1000.0 for w in keys}
    filled = {w: _fill_glints(masks[w][1], fill_cm2 * 100.0 / mm_px[w] ** 2) for w in keys}
    #: the image's horizontal axis per view: x for front / back, z (the body's depth) for a side view
    HAXIS = {"f": 0, "b": 0, "l": 2, "r": 2}

    def project(P, which, mirror):
        sb, cb, mb = frames[which]
        sx = -1.0 if mirror else 1.0
        a = HAXIS[which]
        return cb[0] + sx * (P[:, a] - mb[a]) / sb, cb[1] - (P[:, 1] - mb[1]) / sb

    def sil_iou(bm, which, mirror):
        X = samples(PV[which], bu.faces, float(np.ptp(Pu[:, 1])) / 1500)[0]
        px, py = project(X, which, mirror)
        h, w = bm.shape
        m = np.zeros_like(bm)
        ok = (px >= 0) & (px < w) & (py >= 0) & (py < h)
        m[py[ok].astype(int), px[ok].astype(int)] = True
        m = ndimage.binary_closing(m, iterations=2)
        return float((m & bm).sum() / max((m | bm).sum(), 1))
    mirror_b = sil_iou(masks["b"][0], "b", True) >= sil_iou(masks["b"][0], "b", False)
    report["back_mirrored"] = bool(mirror_b)
    #: per view: (key, mirrored, toward, depth axis) — the camera looks along -toward on the depth axis
    VIEWS = [("f", False, 1.0, 2), ("b", mirror_b, -1.0, 2)]
    for _key, w in sides:
        # A side profile: the body's front (+z) to the image's left means the camera stands on the body's +x side
        # (it sees the left flank, the base view "left"); mirrored, on the -x side. The silhouette decides (like the
        # back's mirror), the camera side follows from it.
        front_left = sil_iou(masks[w][0], w, True) >= sil_iou(masks[w][0], w, False)
        VIEWS.append((w, front_left, 1.0 if front_left else -1.0, 0))
        report[f"{_key}_camera"] = "+x" if front_left else "-x"
    DEPTH = {which: axis for which, _m, _t, axis in VIEWS}
    # the arm weight of every unrigged vertex (the shell never takes the arm, ``cov &= armw < 0.3`` below)
    if corr_u2r is None:
        corr_u2r, _ = gf.uv_correspondence(bu, br)
    Wd = np.zeros((len(R), len(br.joint_names)))
    np.add.at(Wd, (np.repeat(np.arange(len(R)), 4), br.joints.ravel()), br.weights.ravel())
    arm_cols = [i for i, n in enumerate(br.joint_names) if any(t in n for t in arm_tokens)]
    armw = Wd[corr_u2r][:, arm_cols].sum(1) if arm_cols else np.zeros(len(Pu))
    zbuf = {}
    Xs, _n, tri_s, bary_s = samples(Pu, bu.faces, ZBUF_SPACING_PX * min(frames[w][0] for w in keys))
    Xs_posed = _posed_samples(bary_s, Pp, bu.faces, tri_s) if posed_keys else Xs
    del bary_s
    for which, mir, toward, axis in VIEWS:
        h, w = masks[which][0].shape
        # A190: an arms-up side view reads the posed body (the arm is above the head, never in front of the flank);
        # A191: an arms-down (legacy) side view occludes with the trunk only — the arm hangs in front of the flank
        Xv = Xs_posed if which in posed_keys else occluding_samples(which, Xs, tri_s, bu.faces, armw)
        px, py = project(Xv, which, mir)
        ok = (px >= 0) & (px < w) & (py >= 0) & (py < h)
        zb = np.full((h, w), -np.inf)
        np.maximum.at(zb, (py[ok].astype(int), px[ok].astype(int)), toward * Xv[ok, axis])
        zbuf[which] = ndimage.maximum_filter(zb, size=3)
    del Xs, Xs_posed, tri_s, Xv, px, py, ok   # A198: the z-buffers are all they were for
    maskinfo = {}
    misreg: Dict[str, np.ndarray] = {}
    for which, _mir, _t, _a in VIEWS:
        inner = ndimage.binary_erosion(colour_mask[which], iterations=1)
        _, ind = ndimage.distance_transform_edt(~inner, return_indices=True)
        gm = filled[which]
        sdf = ndimage.distance_transform_edt(gm) - ndimage.distance_transform_edt(~gm)
        maskinfo[which] = (ind, sdf)
        # A219: where the body shows bare only by the generated view's misregistration
        misreg[which] = misregistered_strip(masks[which][1], masks[which][0], mm_px[which])

    def view_state(Pq, Nq, Qq=None, NQq=None):
        """Per view what it shows of the points ``Pq`` (normals ``Nq``); an arms-up view reads their posed
        positions ``Qq`` / normals ``NQq`` (A190; same order as ``Pq``)."""
        out = {}
        for which, mir, toward, axis in VIEWS:
            h, w = masks[which][0].shape
            P_, N_ = (Qq, NQq) if (which in posed_keys and Qq is not None) else (Pq, Nq)
            x, y = project(P_, which, mir)
            i, j = np.clip(y.astype(int), 0, h - 1), np.clip(x.astype(int), 0, w - 1)
            seen = toward * P_[:, axis] >= zbuf[which][i, j] - 0.015 / k
            sb = frames[which][0] * k * 1000
            out[which] = {"seen": seen, "facing": toward * N_[:, axis], "sd_mm": maskinfo[which][1][i, j] * sb,
                          "i": i, "j": j, "in": filled[which][i, j],
                          "misreg": misreg[which][i, j]}
        return out

    side_keys = [w for _key, w in sides]

    def side_ok(st_, w):
        return side_view_ok(st_[w]["seen"], st_[w]["facing"], st_["f"]["seen"], st_["f"]["facing"],
                            st_["b"]["seen"], st_["b"]["facing"])

    # 1. coverage on the unrigged body
    Nu = gf._unit(gf.vertex_normals(Pu, bu.faces))
    Np = gf._unit(gf.vertex_normals(Pp, bu.faces)) if posed_keys else Nu
    # A190: the posed body keeps the rest body's vertex order — a vertex an arms-up view shows covered is that index
    vs = view_state(Pu, Nu, Pp, Np)
    cov = np.zeros(len(Pu), bool)
    for which, _m, _t, _a in VIEWS:
        gmd = ndimage.binary_dilation(filled[which], iterations=2 + int(np.ceil(margin_mm / mm_px[which])))
        seen_ok = vs[which]["seen"] if which in ("f", "b") else side_ok(vs, which)
        hit = seen_ok & gmd[vs[which]["i"], vs[which]["j"]]
        if which not in ("f", "b"):
            report[f"side_{which}_added_vertices"] = int((hit & ~cov).sum())
        cov |= hit
    # A220: an arm the piece itself covers (a glove, a sleeve-only piece) keeps its arm vertices; the arm stays
    # out for a trunk piece, whose views show it over the arm only where the arm hangs in front of the trunk
    head_cov = np.zeros(len(Pu), bool)
    head_seen = np.zeros(len(Pu), bool)
    for which in ("f", "b"):
        h = vs[which]["seen"] & (np.abs(vs[which]["facing"]) >= 0.3)
        head_seen |= h
        head_cov |= h & filled[which][vs[which]["i"], vs[which]["j"]]
    arm_keep, arm_shares = arm_pieces(armw, Pu[:, 0], head_seen, head_cov)
    report["arm_covered_share"] = arm_shares
    arm_out = (armw >= 0.3) & ~arm_keep
    cov &= ~arm_out
    Pw_u, Fw_u, inv_u = gf.weld(Pu, bu.faces)
    arm_out_w = np.zeros(len(Pw_u), bool)
    np.logical_or.at(arm_out_w, inv_u, arm_out)
    covw = np.zeros(len(Pw_u), bool)
    np.logical_or.at(covw, inv_u, cov)
    armw_w = np.zeros(len(Pw_u))
    np.maximum.at(armw_w, inv_u, armw)
    A = (gf._adjacency(Fw_u, len(Pw_u))[0] > 0).astype(np.float32)
    c = covw.astype(np.float32)
    for _ in range(4):
        c = np.minimum(1, c + (A @ c > 0))
    for _ in range(4):
        c = c * ((A @ (1 - c)) == 0)
    covw = (c > 0) & ~arm_out_w
    Fr_ = Fw_u[covw[Fw_u].all(1)]
    if len(Fr_) == 0:
        raise ShellRefused("The piece covers no part of the body in its views")
    labels, share = gf.components(Pw_u, Fr_)
    keepv = np.zeros(len(Pw_u), bool)
    used = np.unique(Fr_)
    keepv[used] = (share >= 0.05)[labels[used]]
    c2 = keepv.astype(np.float32)
    for _ in range(2 + int(np.ceil(margin_mm / 10.0))):
        c2 = np.minimum(1, c2 + (A @ c2 > 0))
    seen_w = np.zeros(len(Pw_u), bool)
    for which, _m, _t, _a in VIEWS:
        if which in ("f", "b"):
            np.logical_or.at(seen_w, inv_u, vs[which]["seen"] & (np.abs(vs[which]["facing"]) >= 0.6))
        else:
            # A185: a side view decides the band it sees well — the region does not grow blindly into it
            np.logical_or.at(seen_w, inv_u, side_ok(vs, which))
    for _ in range(8):
        c2 = np.minimum(1, c2 + ((A @ c2 > 0) & ~seen_w))
    cand_u = ((c2 > 0) & ~arm_out_w)[inv_u]

    # 2. onto the rigged body, outer wall only
    outer_r, back_seen = outer_faces_oriented(R, br.faces, px=0.002, tol=0.0025)
    _, near = cKDTree(bu.uvs).query(br.uvs)
    selr = cand_u[near][br.faces].all(1) & outer_r
    _, _, inv_all = gf.weld(R, br.faces)
    Fw_all = inv_all[br.faces]
    nf = len(Fw_all)
    E_ = np.sort(np.concatenate([Fw_all[:, [0, 1]], Fw_all[:, [1, 2]], Fw_all[:, [2, 0]]]), 1)
    fid = np.tile(np.arange(nf), 3)
    o_ = np.lexsort((E_[:, 1], E_[:, 0]))
    Es, fs = E_[o_], fid[o_]
    same = (Es[1:] == Es[:-1]).all(1)
    fa, fb = fs[:-1][same], fs[1:][same]
    cent = R[br.faces].mean(1)
    if not selr.any():
        raise ShellRefused("The piece's region has no outer body surface")
    dsel, _ = cKDTree(cent[selr]).query(cent, distance_upper_bound=0.03)
    cand = ~selr & np.isfinite(dsel)
    m_ = cand[fa] & cand[fb]
    G_ = coo_matrix((np.ones(m_.sum()), (fa[m_], fb[m_])), shape=(nf, nf))
    _, lab_ = connected_components(G_, directed=False)
    lab_ = np.where(cand, lab_, -1)
    leak = np.zeros(lab_.max() + 2, bool)
    for x, y in ((fa, fb), (fb, fa)):
        bad = cand[x] & ~cand[y] & ~selr[y]
        leak[lab_[x[bad]]] = True
    area_ = gf.triangle_areas(R, br.faces)
    comp_area = np.bincount(lab_[cand], weights=area_[cand], minlength=len(leak))
    fillc = (~leak) & (comp_area < max(8e-4, fill_cm2 * 1e-4))
    add = cand & fillc[np.maximum(lab_, 0)] & (lab_ >= 0)
    report["region_holes_closed_faces"] = int(add.sum())
    selr = selr | add
    # A220: a face only seen from behind (``outer_faces_oriented``) is taken reversed, so its offset goes outward
    FR = np.where(back_seen[selr][:, None], br.faces[selr][:, ::-1], br.faces[selr])
    report["back_seen_faces_reversed"] = int((back_seen & selr).sum())
    Rw_, FRw, invr_ = gf.weld(R, FR)
    labels, share = gf.components(Rw_, FRw)
    FR = FR[share[labels[invr_[FR[:, 0]]]] >= 0.03]
    report["region_faces"] = int(len(FR))
    usedr = np.unique(FR)
    remap = np.full(len(R), -1)
    remap[usedr] = np.arange(len(usedr))
    V, F = R[usedr], remap[FR]
    inv_corr = np.full(len(R), -1)
    inv_corr[corr_u2r] = np.arange(len(corr_u2r))
    ui0 = inv_corr[usedr]
    ui0 = np.where(ui0 < 0, cKDTree(bu.uvs).query(br.uvs[usedr])[1], ui0)
    # only the joints that weigh anything in the region travel through the subdivision (memory)
    jcols = np.nonzero(Wd[usedr].max(0) > 0)[0]
    # uv(2), unrigged position(3), its posed position(3, A190: = the rest one without an arms-up view), weights
    ATTR = np.hstack([br.uvs[usedr], Pu[ui0], Pp[ui0], Wd[usedr][:, jcols]])
    limb_cols = limb_columns([br.joint_names[i] for i in jcols])
    for _ in range(2):
        V, F, ATTR = subdivide(V, F, ATTR)

    # 3. membership scalar + clip
    Vw, Fw, winv = gf.weld(V, F)
    ATw = np.zeros((len(Vw), 8))
    np.add.at(ATw, winv, ATTR[:, :8])
    ATw /= np.maximum(np.bincount(winv, minlength=len(Vw)), 1)[:, None]
    Puw, Ppw = ATw[:, 2:5], ATw[:, 5:8]
    st = view_state(Puw, gf._unit(gf.vertex_normals(Puw, Fw)), Ppw,
                    gf._unit(gf.vertex_normals(Ppw, Fw)) if posed_keys else None)
    Pref = Puw * k
    head_on = {w: st[w]["seen"] & (np.abs(st[w]["facing"]) >= 0.3) for w in ("f", "b")}
    side = ~(head_on["f"] | head_on["b"])
    M = float(margin_mm)
    s = np.full(len(Vw), -5.0)
    for w in ("f", "b"):
        s = np.where(head_on[w], np.maximum(np.where(s > -5, s, -1e9), st[w]["sd_mm"] + M), s)
    memb_f = head_on["f"] & st["f"]["in"]
    memb_b = head_on["b"] & st["b"]["in"]
    torso = armw < 0.3
    frame = TorsoFrame(Pu[torso] * k)
    bridge = SideBridge(frame, Pref, head_on["f"], head_on["b"], memb_f, memb_b)
    if side.any():
        marg = bridge.query(Pref[side])[0]
        s[side] = _bridge_mm(marg, M)
    # A192: round a limb the ring decides what no view sees head-on (``ring_worn``) — it only ever adds
    limb_w = np.zeros((len(Vw), len(limb_cols)))
    for li, cols_ in enumerate(limb_cols):
        if cols_:
            np.add.at(limb_w[:, li], winv, ATTR[:, 8:][:, cols_].sum(1))
    limb_w /= np.maximum(np.bincount(winv, minlength=len(Vw)), 1)[:, None]
    ring_added = 0
    ring_closed_added = 0
    for li in range(len(limb_cols)):
        on_limb = limb_w[:, li] > 0.5
        worn = ring_worn(Pref[:, 1], on_limb, head_on["f"], memb_f, head_on["b"], memb_b, st["f"]["facing"] >= 0)
        add = worn & side & (s <= 0)
        # A219: where the front and the back both show the limb worn, a head-on strip at the limb's edge that a view
        # misses by misregistration is worn too (``ring_closed``)
        closed = ring_closed(Pref[:, 1], on_limb, head_on["f"], memb_f, head_on["b"], memb_b, st["f"]["misreg"],
                             st["b"]["misreg"]) & (s <= 0) & ~add
        ring_closed_added += int(closed.sum())
        add = add | closed
        ring_added += int(add.sum())
        s = np.where(add, 5.0 + M, s)
    report["limb_ring_added_vertices"] = ring_added
    report["limb_ring_closed_vertices"] = ring_closed_added
    # A226: under the crotch no view sees the piece — the front panel's bottom edge is joined to the back panel's
    # across the underside like a side bridge (``crotch_run`` / ``crotch_bridge``); never for a skirt
    xc = 0.5 * float(R[:, 0].min() + R[:, 0].max())
    cr_f = crotch_run(Vw[:, 0], Vw[:, 1], Vw[:, 2], memb_f, head_on["f"], xc)
    cr_b = crotch_run(Vw[:, 0], Vw[:, 1], Vw[:, 2], memb_b, head_on["b"], xc)
    crotch = None
    report["crotch_bridge"] = {"front": cr_f and [round(v_, 4) for v_ in cr_f],
                               "back": cr_b and [round(v_, 4) for v_ in cr_b]}
    if cr_f is not None and cr_b is not None:
        skirt = {}
        # the crotch point: the lowest point the front sees head-on at the body's middle (the back's lowest one
        # there sits higher, at the top of the cleft)
        mid_h = (np.abs(Vw[:, 0] - xc) <= CROTCH_CENTRE_M) & head_on["f"]
        ic = np.nonzero(mid_h)[0][np.argmin(Vw[mid_h, 1])]
        for w, mir in (("f", False), ("b", mirror_b)):
            # the stretch of the view's middle column from 3 to 5 cm under the crotch point: a skirt covers it (over
            # the gap between the legs or over the closed legs), a brief ends above it
            cx, cy = project(Puw[ic:ic + 1], w, mir)
            gm_ = filled[w]
            r0, r1 = (int(np.clip(cy[0] + d_ * 1000.0 / mm_px[w], 0, gm_.shape[0] - 1))
                      for d_ in (SKIRT_FROM_M, SKIRT_BELOW_M))
            seg_g = gm_[r0:r1 + 1, int(np.clip(cx[0], 0, gm_.shape[1] - 1))]
            skirt[w] = bool(seg_g.mean() >= 0.5) if len(seg_g) else False
        report["crotch_bridge"]["skirt"] = skirt
        if not any(skirt.values()):
            fl = crotch_floor(Vw, xc, cr_f, cr_b)
            cm_, ct_ = crotch_bridge(Vw, cr_f, cr_b, fl)
            on_c = (cm_ > -0.01) & (s <= 0)
            val = _bridge_mm(cm_, M)
            add = on_c & (val > s)
            s = np.where(add, val, s)
            report["crotch_bridge"]["added_vertices"] = int((add & (val > 0)).sum())
            crotch = (cr_f, cr_b, fl)
    for w in ("f", "b"):
        bump = side & st[w]["seen"] & (st[w]["sd_mm"] > 10)
        s = np.where(bump, np.maximum(s, st[w]["sd_mm"] + M), s)
    near_side = (np.abs(st["f"]["facing"]) < 0.6) & (np.abs(st["b"]["facing"]) < 0.6) & ~side & (s < 0)
    if near_side.any():
        m2 = bridge.query(Pref[near_side])[0]
        s[near_side] = np.where(m2 > 0, _bridge_mm(m2, M), s[near_side])
    for w in side_keys:
        # A185: where a side view sees the point well, its mask is the measurement: it replaces the bridge's
        # estimate in the side band and may add to a grazing front / back point (never to a frontal one, side_ok)
        ok_s = side_ok(st, w)
        sd_s = np.clip(st[w]["sd_mm"] + M, -5, 5 + M)
        s = np.where(ok_s & side, sd_s, s)
        s = np.where(ok_s & ~side, np.maximum(s, sd_s), s)
    report["bridge_window"] = {str(k_): list(v) for k_, v in bridge.window.items()}
    Aw = (gf._adjacency(Fw, len(Vw))[0] > 0).astype(float)
    degw = np.asarray(Aw.sum(1)).ravel()
    sm = np.clip(s, -5, 5 + M)
    for _ in range(4):
        sm = 0.5 * sm + 0.5 * (Aw @ sm) / np.maximum(degw, 1)
    Vc, Fc, Ac = clip_triangles(V, F, sm[winv], ATTR)
    if len(Fc) == 0:
        raise ShellRefused("Nothing of the body lies inside the piece's views")
    Vcw, Fcw, cinv = gf.weld(Vc, Fc)
    labc, shc = gf.components(Vcw, Fcw)
    Fc = Fc[shc[labc[cinv[Fc[:, 0]]]] >= 0.01]
    usedc = np.unique(Fc)
    rm = np.full(len(Vc), -1)
    rm[usedc] = np.arange(len(usedc))
    Vc, Fc, Ac = Vc[usedc], rm[Fc], Ac[usedc]
    # A184: holes the clip left inside the region, up to "Fill holes up to", closed with a fan
    Vc, Fc, Ac, closed = fill_small_holes(Vc, Fc, Ac, fill_cm2 * 1e-4)
    report["shell_holes_closed"] = int(closed)
    UVc, Puc, Ppc, Wc = Ac[:, :2], Ac[:, 2:5], Ac[:, 5:8], Ac[:, 8:]

    # 4. offset along the smoothed outward normals
    Vcw, Fcw, cinv = gf.weld(Vc, Fc)
    volb = np.einsum("ij,ij->i", R[br.faces[:, 0]], np.cross(R[br.faces[:, 1]], R[br.faces[:, 2]])).sum() / 6
    Nw_ = gf._unit(gf._smooth(gf._unit(gf.vertex_normals(Vcw, Fcw)) * np.sign(volb),
                              gf._adjacency(Fcw, len(Vcw)), 3))
    X = Vc + Nw_[cinv] * offset_m
    # A220: the body's extension parts (an inset part's raised patch, an attached part) are their own primitives —
    # the region is cut from the plain surface, so the shell ran under a part standing up to 2 cm out of it
    # — and a region face can sit on a layer under the outer skin (an inset part's kept inner wall): the shell is
    # lifted over every surface its normal ray meets facing the same way (``lift_over_surfaces``)
    part_P, part_F = glb_mesh.part_arrays(rigged)
    body_surf = (R, br.faces if volb > 0 else br.faces[:, ::-1], True)
    X, lift = lift_over_surfaces(Vc, Nw_[cinv], offset_m, [body_surf, (part_P, part_F, False)])
    # A226: across the crotch the piece spans the body's folds instead of following them into each one. The thighs
    # nearly meet there: a crotch-bridge vertex's ray crossed into the other thigh (lifting it 4 cm), so it is
    # never lifted over the body; one facing the other thigh (|normal x| ≥ ``CROTCH_SIDEWAYS``) is not lifted over
    # the extension part either (its ray ran through the part's side), the others are. Then the bridge's vertices
    # are relaxed (``CROTCH_RELAX`` Laplacian passes; the rest of the shell holds still), none ending under the
    # offset over the surface it came from
    if crotch is not None:
        # the whole crotch stretch of the shell, the inner thigh's crease under the floor too (its rays cross as well)
        cv = crotch_bridge(Vc, crotch[0], crotch[1])[0] > -0.01
        on_w = np.zeros(len(Vcw), bool)
        np.logical_or.at(on_w, cinv, cv)
        sw_ = cv & (np.abs(Nw_[cinv][:, 0]) >= CROTCH_SIDEWAYS)
        up_ = cv & ~sw_
        if sw_.any():
            X[sw_], lift[sw_] = Vc[sw_] + Nw_[cinv][sw_] * offset_m, 0.0
        if up_.any():
            X[up_], lift[up_] = lift_over_surfaces(Vc[up_], Nw_[cinv][up_], offset_m, [(part_P, part_F, False)])
        if on_w.any():
            Xw = np.zeros((len(Vcw), 3))
            Xw[cinv] = X
            Vcw_ = np.zeros((len(Vcw), 3))
            Vcw_[cinv] = Vc
            Ac_ = (gf._adjacency(Fcw, len(Vcw))[0] > 0).astype(np.float64)
            deg_ = np.maximum(np.asarray(Ac_.sum(1)).ravel(), 1)[:, None]
            for _ in range(CROTCH_RELAX):
                Xw = np.where(on_w[:, None], 0.5 * Xw + 0.5 * (Ac_ @ Xw) / deg_, Xw)
            dep = np.einsum("ij,ij->i", Xw - Vcw_, Nw_)
            Xw = np.where((on_w & (dep < offset_m))[:, None], Xw + Nw_ * (offset_m - dep)[:, None], Xw)
            X = Xw[cinv]
            report["crotch_relaxed_vertices"] = int(on_w.sum())
            report["crotch_sideways_vertices"] = int(sw_.sum())
    report["lifted_vertices"] = int((lift > 0).sum())
    report["lift_max_mm"] = round(float(lift.max()) * 1000.0, 1) if len(lift) else 0.0

    # 5. colour, baked in the body's UV atlas
    Xq_, _, tri, bary = samples(Vc, Fc, 0.0008)
    Aq = np.einsum("nk,nkj->nj", bary, np.hstack([UVc, Puc, Ppc])[Fc[tri]])
    UVq, Puq, Ppq = Aq[:, :2], Aq[:, 2:5], Aq[:, 5:8]
    Nq = gf._unit(gf._unit(gf.vertex_normals(Puc, Fc))[Fc[tri]].mean(1))
    NPq = gf._unit(gf._unit(gf.vertex_normals(Ppc, Fc))[Fc[tri]].mean(1)) if posed_keys else None
    stq = view_state(Puq, Nq, Ppq, NPq)
    cols, valid = {}, {}
    for which, _m, _t, _a in VIEWS:
        ind, _ = maskinfo[which]
        i, j = stq[which]["i"], stq[which]["j"]
        ii, jj = ind[0][i, j], ind[1][i, j]
        near_ok = (np.hypot(ii - i, jj - j) <= 3) | filled[which][i, j]
        if which in ("f", "b"):
            valid[which] = stq[which]["seen"] & ((np.abs(stq[which]["facing"]) >= 0.3)
                                                 | (stq[which]["sd_mm"] > 10)) & near_ok
        else:
            valid[which] = side_ok(stq, which) & near_ok
        cols[which] = masks[which][2][ii, jj]
    nz = Nq[:, 2]
    wf = np.clip(0.5 + nz, 0, 1) * valid["f"]
    wb = np.clip(0.5 - nz, 0, 1) * valid["b"]
    # A185: a side view colours what it sees well, weighted by how squarely it faces it
    ws = {w: np.clip(stq[w]["facing"] - 0.3, 0, 1) * valid[w] for w in side_keys}
    wsum = wf + wb + sum(ws.values(), np.zeros(len(Puq)))
    real = wsum > 0
    col = np.zeros((len(Puq), 3))
    acc = cols["f"] * wf[:, None] + cols["b"] * wb[:, None]
    for w in side_keys:
        acc = acc + cols[w] * ws[w][:, None]
    col[real] = (acc / np.maximum(wsum, 1e-9)[:, None])[real]
    side_q = ~real
    src_dist = np.zeros(len(Puq))
    if side_q.any() and real.any():
        Pq_m = Puq * k
        _marg, t_q, yf_q, yb_q, th_q, fe_q, be_q = bridge.query(Pq_m[side_q])
        rf = np.nonzero(real & (wf >= wb) & (wf > 0))[0]
        rb = np.nonzero(real & (wb > wf))[0]
        th_all, y_all, _ = frame.coords(Pq_m)
        sc = np.array([1.5, 1000.0])

        def nearest(rows, th_, y_):
            kk = min(12, len(rows))
            d, j = cKDTree(np.c_[th_all[rows], y_all[rows]] * sc).query(np.c_[th_, y_] * sc, k=kk)
            d, j = d.reshape(len(th_), -1), j.reshape(len(th_), -1)
            return rows[j], d[:, 0] / 1000.0
        ok = np.isfinite(t_q)
        yfq = np.where(np.isfinite(yf_q), yf_q, Pq_m[side_q][:, 1])
        ybq = np.where(np.isfinite(yb_q), yb_q, Pq_m[side_q][:, 1])
        fq = np.where(np.isfinite(fe_q), fe_q, th_q)
        bq = np.where(np.isfinite(be_q), be_q, th_q)
        n_side = int(side_q.sum())
        jf, dfq = nearest(rf, fq, yfq) if len(rf) else (None, np.full(n_side, np.inf))
        jb, dbq = nearest(rb, bq, ybq) if len(rb) else (None, np.full(n_side, np.inf))
        tq = np.clip(np.where(ok, np.nan_to_num(t_q), np.where(dfq <= dbq, 0.0, 1.0)), 0, 1)
        cfq = np.median(col[jf], 1) if jf is not None else np.median(col[jb], 1)
        cbq = np.median(col[jb], 1) if jb is not None else cfq
        # A220: a bridged side point takes the PATTERN of the panel it continues — its colour is read at its mirror
        # image across the panel's edge (``panel_source_angle``), not the median at the edge (a flat streak)
        if ok.any():
            pf = panel_source_angle(th_q, fq, True)
            pb = panel_source_angle(th_q, bq, False)
            if len(rf):
                jm, _ = nearest(rf, pf[ok], yfq[ok])
                cfq[ok] = np.median(col[jm[:, :3]], 1)
            if len(rb):
                jm, _ = nearest(rb, pb[ok], ybq[ok])
                cbq[ok] = np.median(col[jm[:, :3]], 1)
            if not len(rf):
                cfq[ok] = cbq[ok]
            if not len(rb):
                cbq[ok] = cfq[ok]
        col[side_q] = cfq * (1 - tq[:, None]) + cbq * tq[:, None]
        src_dist[side_q] = np.where(tq < 0.5, dfq, dbq)
    # A192: round a limb the side takes the PATTERN, not a median colour — the front picture is continued past its
    # head-on edge along the surface at its own scale (mirrored back and forth between the limb's two head-on
    # edges, ``mirror_into``), the back picture likewise from the other end, cross-faded over the side.
    tiled = 0
    if side_q.any() and real.any():
        Wq = np.einsum("nk,nkj->nj", bary, Wc[Fc[tri]])
        Pm = Puq * k
        for cols_ in limb_cols:
            on = Wq[:, cols_].sum(1) > 0.5 if cols_ else np.zeros(len(Pm), bool)
            todo = np.nonzero(on & side_q)[0]
            if not len(todo) or not (on & real).any():
                continue
            y0 = Pm[on, 1].min()
            rb_ = np.clip(((Pm[:, 1] - y0) / RING_BIN_M).astype(int), 0, None)
            nbin = int(rb_[on].max()) + 1
            # the limb's axis per ring: the middle of its extent
            ax = np.full((nbin, 2), np.nan)
            for a_, lo_hi in ((0, 0), (2, 1)):
                lo = np.full(nbin, np.inf)
                hi = np.full(nbin, -np.inf)
                np.minimum.at(lo, rb_[on], Pm[on, a_])
                np.maximum.at(hi, rb_[on], Pm[on, a_])
                ax[:, lo_hi] = 0.5 * (lo + hi)
            dx, dz = Pm[:, 0] - ax[rb_.clip(0, nbin - 1), 0], Pm[:, 2] - ax[rb_.clip(0, nbin - 1), 1]
            rad = np.hypot(dx, dz)
            acc_c = np.zeros((len(todo), 3))
            acc_w = np.zeros(len(todo))
            for which, front in (("f", True), ("b", False)):
                src = on & real & ((wf >= wb) & (wf > 0) if front else (wb > wf))
                if not src.any():
                    continue
                jj = stq[which]["j"].astype(np.float64)
                # arc from the view's centre line (the front's +z, the back's -z), signed by the image column
                jc = np.full(nbin, np.nan)
                jlo = np.full(nbin, np.inf)
                jhi = np.full(nbin, -np.inf)
                np.minimum.at(jlo, rb_[src], jj[src])
                np.maximum.at(jhi, rb_[src], jj[src])
                okb = np.isfinite(jlo) & (jhi - jlo >= 4)
                if okb.sum() < 2:
                    continue
                idx = np.arange(nbin)
                jlo = np.interp(idx, idx[okb], jlo[okb])
                jhi = np.interp(idx, idx[okb], jhi[okb])
                jc = 0.5 * (jlo + jhi)
                ang = np.abs(np.arctan2(dx, dz if front else -dz))            # 0 at the view's centre line .. pi
                # the head-on edge's angle per ring and image side
                right = jj >= jc[rb_.clip(0, nbin - 1)]
                edge = np.zeros((nbin, 2))
                for sd in (0, 1):
                    m_ = src & (right == bool(sd))
                    e_ = np.zeros(nbin)
                    np.maximum.at(e_, rb_[m_], ang[m_])
                    have = e_ > 0
                    edge[:, sd] = np.interp(idx, idx[have], e_[have]) if have.sum() >= 2 else np.radians(72.0)
                q = todo
                bq_ = rb_[q].clip(0, nbin - 1)
                sd_q = right[q].astype(int)
                e_q = edge[bq_, sd_q]
                arc_px = rad[q] * np.maximum(ang[q] - e_q, 0.0) * 1000.0 / mm_px[which]
                j_edge = np.where(sd_q == 1, jhi[bq_], jlo[bq_])
                j_src = mirror_into(j_edge - np.where(sd_q == 1, 1.0, -1.0) * arc_px, jlo[bq_], jhi[bq_])
                ind, _ = maskinfo[which]
                h_, w_ = masks[which][0].shape
                i_s = stq[which]["i"][q]
                j_s = np.clip(np.rint(j_src).astype(int), 0, w_ - 1)
                c_ = masks[which][2][ind[0][i_s, j_s], ind[1][i_s, j_s]]
                # weight: 1 at this view's edge, 0 at the other view's (the far side of the limb)
                span = np.maximum(np.pi - e_q - np.radians(72.0), 1e-3)
                t_ = np.clip((ang[q] - e_q) / span, 0, 1)
                w_v = 1.0 - t_ * t_ * (3 - 2 * t_)
                acc_c += c_ * w_v[:, None]
                acc_w += w_v
            got = acc_w > 1e-6
            col[todo[got]] = acc_c[got] / acc_w[got][:, None]
            tiled += int(got.sum())
    report["limb_side_samples_tiled"] = tiled
    # A226: a crotch-bridge sample continues the two panels' pattern: its colour is read in the front panel and in
    # the back panel at its mirror image across that panel's edge (``crotch_source``), blended front→back by t
    crotch_coloured = 0
    if crotch is not None and real.any():
        cr_f, cr_b, fl = crotch
        cm_q, ct_q = crotch_bridge(Xq_, cr_f, cr_b, fl)
        todo = np.nonzero((cm_q > -0.01) & ~real)[0]
        rf_ = np.nonzero(real & (wf >= wb) & (wf > 0))[0]
        rb_ = np.nonzero(real & (wb > wf))[0]
        if len(todo) and (len(rf_) or len(rb_)):
            yfs, ybs = crotch_source(Xq_[todo], ct_q[todo], cr_f, cr_b)
            got = []
            for rows, ys in ((rf_, yfs), (rb_, ybs)):
                if not len(rows):
                    got.append(None)
                    continue
                _d, jj = cKDTree(Xq_[rows][:, :2]).query(np.c_[Xq_[todo, 0], ys], k=min(3, len(rows)))
                jj = jj.reshape(len(todo), -1)
                got.append(np.median(col[rows[jj]], 1))
            cf_, cb_ = (got[0] if got[0] is not None else got[1]), (got[1] if got[1] is not None else got[0])
            tq_ = np.clip(np.nan_to_num(ct_q[todo]), 0, 1)[:, None]
            col[todo] = cf_ * (1 - tq_) + cb_ * tq_
            crotch_coloured = int(len(todo))
    report["crotch_samples_coloured"] = crotch_coloured
    side_s = np.abs(nz) < 0.3
    metrics: Dict[str, Any] = {}
    for ncm in (1, 2, 5):
        okc = real | (src_dist <= ncm / 100.0)
        metrics[f"side_colour_within_{ncm}cm"] = round(float(okc[side_s].mean()), 3) if side_s.any() else None
    TS = TEXTURE_PX
    img = np.zeros((TS, TS, 3))
    cnt = np.zeros((TS, TS))
    ti = np.clip((UVq[:, 1] % 1.0) * (TS - 1), 0, TS - 1).astype(int)
    tj = np.clip((UVq[:, 0] % 1.0) * (TS - 1), 0, TS - 1).astype(int)
    np.add.at(img, (ti, tj), col)
    np.add.at(cnt, (ti, tj), 1)
    filled_px = cnt > 0
    img[filled_px] /= cnt[filled_px][:, None]
    for _ in range(6):
        grow = ndimage.binary_dilation(filled_px) & ~filled_px
        if not grow.any():
            break
        acc = np.zeros_like(img)
        n_ = np.zeros(cnt.shape)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            acc += np.roll(np.roll(img, dy, 0), dx, 1) * np.roll(np.roll(filled_px, dy, 0), dx, 1)[..., None]
            n_ += np.roll(np.roll(filled_px, dy, 0), dx, 1)
        img[grow] = acc[grow] / np.maximum(n_[grow], 1)[:, None]
        filled_px = filled_px | grow
    buf = io.BytesIO()
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(buf, "PNG")

    # 6. weights: the body's top 4
    joints_t, Wt, used_j = top4_weights(Wc)
    garment = glb_mesh.GarmentMesh(positions=X, normals=None, uvs=UVc, indices=Fc,
                                   joints=joints_t, weights=Wt,
                                   joint_names=[br.joint_names[jcols[i]] for i in used_j], image=buf.getvalue(),
                                   mime="image/png", material={"doubleSided": True})
    over = signed_distance(X, R, br.faces)
    metrics.update({"shell_faces": int(len(Fc)), "shell_vertices": int(len(X)),
                    "inside_share": round(float((over < -INSIDE_M).mean()), 5),
                    "over_skin_p50_mm": round(float(np.median(over)) * 1000, 2),
                    "over_skin_p95_mm": round(float(np.percentile(over, 95)) * 1000, 2),
                    "seconds": round(time.monotonic() - started, 1)})
    return gf.FitResult(garment=garment, metrics=metrics, ok=True, reasons=[],
                        report={"mesh_shape": SHELL, **report})


def top4_weights(Wc) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The shell's skin from the per-vertex weights ``Wc`` over the region's joint columns: ``(joints (n, 4) into
    ``used``, weights (n, 4) summing to 1, used column indices)``. A198 (review 06 #7 / 06B #3): a region skinned to
    fewer than 4 joints is padded with weight-0 columns, so the graft always gets (n, 4) arrays."""
    Wc = np.asarray(Wc, np.float64)
    if Wc.shape[1] < 4:
        Wc = np.pad(Wc, ((0, 0), (0, 4 - Wc.shape[1])))
    order = np.argsort(-Wc, 1)[:, :4]
    Wt = np.take_along_axis(Wc, order, 1)
    Wt = Wt / np.maximum(Wt.sum(1, keepdims=True), 1e-9)
    used_j = np.unique(order[Wt > 0])
    jr = np.zeros(Wc.shape[1], int)
    jr[used_j] = np.arange(len(used_j))
    return np.where(Wt > 0, jr[order], 0), Wt, used_j


def silhouette_mask(P, F, mask_shape: Tuple[int, int], body_mask, *, haxis: int, mirror: bool) -> np.ndarray:
    """The silhouette of the mesh ``(P, F)`` in a view of ``mask_shape`` framed like ``body_mask`` (``garment_fit.
    _frame``: the height is the scale), the image's horizontal axis the mesh axis ``haxis`` (0 front / back, 2 side),
    ``mirror`` flipping it. Closed 2 px like ``build_shell``'s silhouette check."""
    from scipy import ndimage
    from app.core import garment_fit as gf
    P = np.asarray(P, np.float64)
    sb, cb, mb = gf._frame(P, body_mask)
    X = samples(P, F, float(np.ptp(P[:, 1])) / 1500)[0]
    sx = -1.0 if mirror else 1.0
    px = cb[0] + sx * (X[:, haxis] - mb[haxis]) / sb
    py = cb[1] - (X[:, 1] - mb[1]) / sb
    h, w = mask_shape
    m = np.zeros((h, w), bool)
    ok = (px >= 0) & (px < w) & (py >= 0) & (py < h)
    m[py[ok].astype(int), px[ok].astype(int)] = True
    return ndimage.binary_closing(m, iterations=2)


def iou(a, b) -> float:
    a, b = np.asarray(a, bool), np.asarray(b, bool)
    return float((a & b).sum() / max((a | b).sum(), 1))


def arms_up_check(rigged: bytes, unrigged: bytes, side_mask) -> Dict[str, Any]:
    """A190, the gate of an arms-up base side view: its figure mask ``side_mask`` against the silhouette of the base
    body posed with ``pose_arms_up`` (the camera side the better match names) — ``{iou_posed, iou_rest, mirror, ok}``:
    ok when the posed body matches at least ``ARMS_UP_IOU_MIN`` and beats the body at rest by at least
    ``ARMS_UP_IOU_MARGIN`` (the arms really went up; ``arms_up_ok``)."""
    from app.core import garment_fit as gf
    from app.core import glb_mesh
    bu, br = glb_mesh.body_arrays(unrigged), glb_mesh.body_arrays(rigged)
    Pu = np.asarray(bu.positions, np.float64)
    R = np.asarray(br.positions, np.float64)
    k = float(np.ptp(R[:, 1])) / float(np.ptp(Pu[:, 1]))
    corr, _ = gf.uv_correspondence(bu, br)
    Pp = Pu + (pose_arms_up(R, br.joints, br.weights, br.joint_names, br.joint_positions) - R)[corr] / k
    mask = np.asarray(side_mask, bool)
    best = None
    for mirror in (False, True):
        posed = iou(silhouette_mask(Pp, bu.faces, mask.shape, mask, haxis=2, mirror=mirror), mask)
        if best is None or posed > best[0]:
            best = (posed, mirror)
    rest = iou(silhouette_mask(Pu, bu.faces, mask.shape, mask, haxis=2, mirror=best[1]), mask)
    return {"iou_posed": round(best[0], 3), "iou_rest": round(rest, 3), "mirror": best[1],
            "ok": arms_up_ok(round(best[0], 3), round(rest, 3))}


def arms_up_ok(iou_posed: float, iou_rest: float) -> bool:
    """A210: the arms-up decision on the (rounded, as reported) IoUs — posed ≥ ``ARMS_UP_IOU_MIN`` and posed − rest
    ≥ ``ARMS_UP_IOU_MARGIN`` (a 1e-9 slack so a reported difference of exactly the margin passes)."""
    return bool(iou_posed >= ARMS_UP_IOU_MIN - 1e-9 and iou_posed - iou_rest >= ARMS_UP_IOU_MARGIN - 1e-9)


def shell_glb(garment) -> bytes:
    """The shell alone as a static textured GLB (the Mesh step's 3D view): positions in the body's bind space."""
    from app.core.glb_mesh import static_glb
    return static_glb(np.asarray(garment.positions, np.float64), np.asarray(garment.indices, np.int64),
                      np.asarray(garment.uvs, np.float64), image=garment.image, mime=garment.mime,
                      material={"name": "shell", "doubleSided": True}, name="shell")


def shell_views(character_name: str, item_id: str, fsig: str, bsig: str, *,
                sides: bool = False) -> Dict[str, Dict[str, Any]]:
    """The two views ``build_shell`` reads, from the piece's stored files: per view the base body's figure mask (the
    bald base view the body was meshed from, flattened like the fit's), the accepted ghost view's mask in that frame
    and the ghost image. ``base_body.MissingInput`` when a view is missing; ``garment_source.FrameRefused`` when the
    front cannot be framed. ``sides`` (A185, "Side views for the shell"): the left / right views too — the base side
    view's figure mask and the piece-only side view's mask in its frame (both in the base side view's size)."""
    from PIL import Image
    from app.core import base_body, garment_source
    from app.core import garment_images as gi
    from app.core import garment_store as gs
    from app.core.model_refs import find_ref_image, get_model_refs_dir
    out: Dict[str, Dict[str, Any]] = {}
    from app.core import shell_base_views
    front = find_ref_image(character_name, base_body._kind("front"), bsig)
    back = find_ref_image(character_name, base_body._kind("back"), bsig)
    if front is None or back is None:
        raise base_body.MissingInput(base_body.BASE_IMAGES_MISSING)
    # A190: the frame of the base-view variant the worn views were made on (bald / arms up), when there is one
    front = shell_base_views.base_for(character_name, item_id, "front", bsig, front, make=False)[0]
    back = shell_base_views.base_for(character_name, item_id, "back", bsig, back, make=False)[0]
    # A198 (review 06B #2): an EMPTY drafted back (``garment_images.skipped_view``) has no ghost back by design —
    # nothing of the piece shows from behind: the back reads as an empty ghost mask over the base back.
    empty_back = bool(gi.skipped_view(character_name, item_id, fsig, "ghost", "back"))
    for view in ("front", "back"):
        ghost = gs.garment_path(character_name, item_id, fsig, "image", step="ghost", view=view)
        if not ghost.is_file() and not (view == "back" and empty_back):
            raise base_body.MissingInput(f"The ghost {view} image is missing — run the ghost step first")
    body_f, ghost_f, _frame = garment_source.fit_masks(character_name, item_id, fsig, body_front=front,
                                                        base_front=front)
    body_b, size_b = garment_source._flat_mask(Path(back), get_model_refs_dir(character_name))
    ghost_b_path = gs.garment_path(character_name, item_id, fsig, "image", step="ghost", view="back")
    if empty_back and not ghost_b_path.is_file():
        bm = np.asarray(body_b)
        out["back"] = {"body_mask": bm, "ghost_mask": np.zeros(bm.shape[:2], bool),
                       "image": np.zeros(bm.shape[:2] + (3,), np.uint8)}
    else:
        ghost_b = gi._mask(ghost_b_path, size_b)
    for view, bm, gm in (("front", body_f, ghost_f), ("back", body_b, None if "back" in out else ghost_b)):
        if view in out:
            continue
        path = gs.garment_path(character_name, item_id, fsig, "image", step="ghost", view=view)
        with Image.open(path) as im:
            rgb = im.convert("RGB")
            h, w = np.asarray(bm).shape[:2]
            if rgb.size != (w, h):
                rgb = rgb.resize((w, h))
            out[view] = {"body_mask": np.asarray(bm), "ghost_mask": np.asarray(gm), "image": np.asarray(rgb)}
    for view in (SIDE_VIEWS if sides else ()):
        base_s = find_ref_image(character_name, base_body._kind(view), bsig)
        if base_s is None:
            raise base_body.MissingInput(base_body.BASE_IMAGES_MISSING)
        # A190: a worn side made on the arms-up base side view is read on the posed body, framed by that view
        worn = gs.garment_path(character_name, item_id, fsig, "image", step="worn", view=view)
        made_on = str(gs.read_record(worn.with_suffix(".json")).get("base_variant") or "")
        posed = shell_base_views.arms_up(made_on)
        if made_on:
            hit = shell_base_views.current(character_name, view, bsig, made_on, base_s)
            if hit is None:
                raise base_body.MissingInput(f"The {view} base view with the arms up is missing — run the worn "
                                             f"{view} view again")
            base_s = hit
        ghost = gs.garment_path(character_name, item_id, fsig, "image", step="ghost", view=view)
        if not ghost.is_file():
            raise base_body.MissingInput(f"The ghost {view} image is missing — run the ghost step first")
        body_s, size_s = garment_source._flat_mask(Path(base_s), get_model_refs_dir(character_name))
        with Image.open(ghost) as im:
            rgb = im.convert("RGB")
            if rgb.size != tuple(size_s):
                rgb = rgb.resize(tuple(size_s))
        out[view] = {"body_mask": np.asarray(body_s), "ghost_mask": np.asarray(gi._mask(ghost, size_s)),
                     "image": np.asarray(rgb), "arms_up": posed}
    return out
