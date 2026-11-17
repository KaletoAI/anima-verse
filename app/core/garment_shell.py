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
   matched height, blended front→back along the arc.

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
#: A190: an arms-up base side view passes when its figure matches the posed body's silhouette at least this well.
ARMS_UP_IOU_MIN = 0.8
#: Bumped when the shell's construction changes: a shell made by another version reads stale.
SHELL_VERSION = 3
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

def samples(P, F, px: float, seed: int = 1):
    """Random points on the faces, about 4 per ``px``² (capped at 600 per face): ``(X, normals, tri)``."""
    rng = np.random.default_rng(seed)
    A, B, C = P[F[:, 0]], P[F[:, 1]], P[F[:, 2]]
    N = np.cross(B - A, C - A)
    area = np.linalg.norm(N, axis=1) / 2
    N = N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-15)
    n = np.clip(np.ceil(area / (px * px) * 4).astype(int), 1, 600)
    tri = np.repeat(np.arange(len(F)), n)
    r1, r2 = rng.random(len(tri)), rng.random(len(tri))
    s = np.sqrt(r1)
    a, b, c = 1 - s, s * (1 - r2), s * r2
    X = A[tri] * a[:, None] + B[tri] * b[:, None] + C[tri] * c[:, None]
    return X, N[tri], tri, np.stack([a, b, c], 1)


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
    P = np.asarray(P, np.float64)
    F = np.asarray(F, np.int64).reshape(-1, 3)
    X, _, tri, _ = samples(P, F, px * 0.7)
    vis = np.zeros(len(F), bool)
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
        vis[tri[z >= zb[key] - tol]] = True
    return vis


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

            def build(ed, eb):
                ff = np.zeros(nb, bool)
                bf = np.zeros(nb, bool)
                for i in range(nb):
                    sel = (np.abs(bins - i) <= eb) & onside
                    if np.isfinite(fe[i]):
                        ff[i] = (sel & memb_f & (a >= fe[i] - ed)).any()
                    if np.isfinite(be[i]):
                        bf[i] = (sel & memb_b & (a <= be[i] + ed)).any()

                def end_angle(run, memb, front):
                    i0, i1 = run
                    sel = (bins >= i0) & (bins <= i1) & onside & memb
                    if not sel.any():
                        return None
                    vals = [a[sel & (bins == i)].max() if front else a[sel & (bins == i)].min()
                            for i in range(i0, i1 + 1) if (sel & (bins == i)).any()]
                    return float(np.median(vals))
                fr = [(r, end_angle(r, memb_f, True)) for r in _runs(ff)]
                brn = [(r, end_angle(r, memb_b, False)) for r in _runs(bf)]
                pairs = []
                usedb = set()
                for (i0, i1), fa in fr:
                    c = 0.5 * (i0 + i1)
                    best = None
                    for k, ((j0, j1), _ba) in enumerate(brn):
                        d = abs(0.5 * (j0 + j1) - c) * BIN_M
                        if d <= MATCH_M and (best is None or d < best[0]):
                            best = (d, k)
                    if best is not None:
                        pairs.append(((i0, i1), brn[best[1]][0], fa, brn[best[1]][1]))
                        usedb.add(best[1])
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


def build_shell(rigged: bytes, unrigged: bytes, views: Dict[str, Dict[str, Any]], *,
                arm_tokens: Iterable[str] = ("Arm", "Hand"), offset_m: float = THICKNESS_M,
                margin_mm: float = MARGIN_DEFAULT, fill_cm2: float = FILL_DEFAULT):
    """The shell of a piece on the body (module docstring) -> ``garment_fit.FitResult`` (``garment`` in the rigged
    body's bind space, skinned; ``metrics``: ``shell_faces``, ``inside_share``, ``over_skin_p50_mm``,
    ``side_colour_within_{1,2,5}cm``, ``seconds``). ``views``: ``{"front": {...}, "back": {...}}``, each
    ``body_mask`` (bool, the base view's figure), ``ghost_mask`` (bool, the piece-only view's), ``image`` (the
    piece-only view, RGB uint8, same size as its masks); the back view is mirrored onto the body when that matches
    its silhouette better. ``margin_mm`` (A184, "Take from the body"): the membership border is moved this far
    outward around the piece's outline in its views; ``fill_cm2`` ("Fill holes up to"): enclosed gaps of the
    piece's outline and of the body region up to this area are closed. ``ShellRefused`` when no region is found."""
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
        img = np.asarray(v["image"], np.float64)[..., :3]
        masks[w] = (bm, gm, img)
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
    Xs, _n, tri_s, bary_s = samples(Pu, bu.faces, float(np.ptp(Pu[:, 1])) / 2500)
    Xs_posed = np.einsum("nk,nkj->nj", bary_s, Pp[bu.faces[tri_s]]) if posed_keys else Xs
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
    maskinfo = {}
    for which, _mir, _t, _a in VIEWS:
        inner = ndimage.binary_erosion(colour_mask[which], iterations=1)
        _, ind = ndimage.distance_transform_edt(~inner, return_indices=True)
        gm = filled[which]
        sdf = ndimage.distance_transform_edt(gm) - ndimage.distance_transform_edt(~gm)
        maskinfo[which] = (ind, sdf)

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
                          "i": i, "j": j, "in": filled[which][i, j]}
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
    cov &= armw < 0.3
    Pw_u, Fw_u, inv_u = gf.weld(Pu, bu.faces)
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
    covw = (c > 0) & (armw_w < 0.3)
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
    cand_u = ((c2 > 0) & (armw_w < 0.3))[inv_u]

    # 2. onto the rigged body, outer wall only
    outer_r = outer_faces(R, br.faces, px=0.002, tol=0.0025)
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
    FR = br.faces[selr]
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
    for li in range(len(limb_cols)):
        on_limb = limb_w[:, li] > 0.5
        worn = ring_worn(Pref[:, 1], on_limb, head_on["f"], memb_f, head_on["b"], memb_b, st["f"]["facing"] >= 0)
        add = worn & side & (s <= 0)
        ring_added += int(add.sum())
        s = np.where(add, 5.0 + M, s)
    report["limb_ring_added_vertices"] = ring_added
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
    order = np.argsort(-Wc, 1)[:, :4]
    Wt = np.take_along_axis(Wc, order, 1)
    Wt = Wt / np.maximum(Wt.sum(1, keepdims=True), 1e-9)
    used_j = np.unique(order[Wt > 0])
    jr = np.zeros(len(jcols), int)
    jr[used_j] = np.arange(len(used_j))
    garment = glb_mesh.GarmentMesh(positions=X, normals=None, uvs=UVc, indices=Fc,
                                   joints=np.where(Wt > 0, jr[order], 0), weights=Wt,
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
    ok when the posed body matches at least ``ARMS_UP_IOU_MIN`` and better than the body at rest (the arms really
    went up)."""
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
            "ok": bool(best[0] >= ARMS_UP_IOU_MIN and best[0] > rest)}


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
    for view in ("front", "back"):
        ghost = gs.garment_path(character_name, item_id, fsig, "image", step="ghost", view=view)
        if not ghost.is_file():
            raise base_body.MissingInput(f"The ghost {view} image is missing — run the ghost step first")
    body_f, ghost_f, _frame = garment_source.fit_masks(character_name, item_id, fsig, body_front=front,
                                                        base_front=front)
    body_b, size_b = garment_source._flat_mask(Path(back), get_model_refs_dir(character_name))
    ghost_b_path = gs.garment_path(character_name, item_id, fsig, "image", step="ghost", view="back")
    ghost_b = gi._mask(ghost_b_path, size_b)
    for view, bm, gm in (("front", body_f, ghost_f), ("back", body_b, ghost_b)):
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
