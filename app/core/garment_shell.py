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


#: The fit settings that shape a shell only (a generated mesh's fit is not due for them).
SHELL_SETTING_KEYS: Tuple[str, ...] = ("shell_offset", "shell_margin", "shell_fill")
#: Texture size of the baked shell (px).
TEXTURE_PX = 2048
#: A vertex this far under the skin (m) counts as inside (``inside_share``).
INSIDE_M = 0.002
#: Bumped when the shell's construction changes: a shell made by another version reads stale.
SHELL_VERSION = 2

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


# --- the shell ------------------------------------------------------------------------------------------------------

def _bridge_mm(marg, margin_mm: float):
    """The side bridge's margin (m) as membership mm, grown by ``margin_mm`` where the bridge measured a real margin
    (its "no bridge" value -0.01 m stays outside)."""
    mm = np.asarray(marg, np.float64) * 1000.0
    return np.clip(np.where(mm > -9.99, mm + margin_mm, mm), -5, 5 + margin_mm)


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
    for key, w in (("front", "f"), ("back", "b")):
        v = views.get(key) or {}
        bm, gm = gf._mask(v["body_mask"]), gf._mask(v["ghost_mask"])
        if not bm.any():
            raise ShellRefused(f"The {key} view has no body")
        img = np.asarray(v["image"], np.float64)[..., :3]
        masks[w] = (bm, gm, img)
    if not (masks["f"][1].any() or masks["b"][1].any()):
        raise ShellRefused("The piece-only views show no piece")
    colour_mask = {w: masks[w][1] for w in ("f", "b")}
    frames = {w: gf._frame(Pu, masks[w][0]) for w in ("f", "b")}
    # mm per pixel of each view on the rigged body
    mm_px = {w: frames[w][0] * k * 1000.0 for w in ("f", "b")}
    filled = {w: _fill_glints(masks[w][1], fill_cm2 * 100.0 / mm_px[w] ** 2) for w in ("f", "b")}

    def project(P, which, mirror):
        sb, cb, mb = frames[which]
        sx = -1.0 if mirror else 1.0
        return cb[0] + sx * (P[:, 0] - mb[0]) / sb, cb[1] - (P[:, 1] - mb[1]) / sb

    def sil_iou(bm, which, mirror):
        X = samples(Pu, bu.faces, float(np.ptp(Pu[:, 1])) / 1500)[0]
        px, py = project(X, which, mirror)
        h, w = bm.shape
        m = np.zeros_like(bm)
        ok = (px >= 0) & (px < w) & (py >= 0) & (py < h)
        m[py[ok].astype(int), px[ok].astype(int)] = True
        m = ndimage.binary_closing(m, iterations=2)
        return float((m & bm).sum() / max((m | bm).sum(), 1))
    mirror_b = sil_iou(masks["b"][0], "b", True) >= sil_iou(masks["b"][0], "b", False)
    report["back_mirrored"] = bool(mirror_b)
    VIEWS = [("f", False, 1.0), ("b", mirror_b, -1.0)]
    zbuf = {}
    Xs = samples(Pu, bu.faces, float(np.ptp(Pu[:, 1])) / 2500)[0]
    for which, mir, toward in VIEWS:
        h, w = masks[which][0].shape
        px, py = project(Xs, which, mir)
        ok = (px >= 0) & (px < w) & (py >= 0) & (py < h)
        zb = np.full((h, w), -np.inf)
        np.maximum.at(zb, (py[ok].astype(int), px[ok].astype(int)), toward * Xs[ok, 2])
        zbuf[which] = ndimage.maximum_filter(zb, size=3)
    maskinfo = {}
    for which, _mir, _t in VIEWS:
        inner = ndimage.binary_erosion(colour_mask[which], iterations=1)
        _, ind = ndimage.distance_transform_edt(~inner, return_indices=True)
        gm = filled[which]
        sdf = ndimage.distance_transform_edt(gm) - ndimage.distance_transform_edt(~gm)
        maskinfo[which] = (ind, sdf)

    def view_state(Pq, Nq):
        out = {}
        for which, mir, toward in VIEWS:
            h, w = masks[which][0].shape
            x, y = project(Pq, which, mir)
            i, j = np.clip(y.astype(int), 0, h - 1), np.clip(x.astype(int), 0, w - 1)
            seen = toward * Pq[:, 2] >= zbuf[which][i, j] - 0.015 / k
            sb = frames[which][0] * k * 1000
            out[which] = {"seen": seen, "facing": toward * Nq[:, 2], "sd_mm": maskinfo[which][1][i, j] * sb,
                          "i": i, "j": j, "in": filled[which][i, j]}
        return out

    # 1. coverage on the unrigged body
    corr_u2r, _ = gf.uv_correspondence(bu, br)
    Wd = np.zeros((len(R), len(br.joint_names)))
    np.add.at(Wd, (np.repeat(np.arange(len(R)), 4), br.joints.ravel()), br.weights.ravel())
    arm_cols = [i for i, n in enumerate(br.joint_names) if any(t in n for t in arm_tokens)]
    armw = Wd[corr_u2r][:, arm_cols].sum(1) if arm_cols else np.zeros(len(Pu))
    Nu = gf._unit(gf.vertex_normals(Pu, bu.faces))
    vs = view_state(Pu, Nu)
    cov = np.zeros(len(Pu), bool)
    for which, _m, _t in VIEWS:
        gmd = ndimage.binary_dilation(filled[which], iterations=2 + int(np.ceil(margin_mm / mm_px[which])))
        cov |= vs[which]["seen"] & gmd[vs[which]["i"], vs[which]["j"]]
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
    for which, _m, _t in VIEWS:
        np.logical_or.at(seen_w, inv_u, vs[which]["seen"] & (np.abs(vs[which]["facing"]) >= 0.6))
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
    ATTR = np.hstack([br.uvs[usedr], Pu[ui0], Wd[usedr][:, jcols]])   # uv(2) unrigged position(3) weights
    for _ in range(2):
        V, F, ATTR = subdivide(V, F, ATTR)

    # 3. membership scalar + clip
    Vw, Fw, winv = gf.weld(V, F)
    ATw = np.zeros((len(Vw), 5))
    np.add.at(ATw, winv, ATTR[:, :5])
    ATw /= np.maximum(np.bincount(winv, minlength=len(Vw)), 1)[:, None]
    Puw = ATw[:, 2:5]
    st = view_state(Puw, gf._unit(gf.vertex_normals(Puw, Fw)))
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
    for w in ("f", "b"):
        bump = side & st[w]["seen"] & (st[w]["sd_mm"] > 10)
        s = np.where(bump, np.maximum(s, st[w]["sd_mm"] + M), s)
    near_side = (np.abs(st["f"]["facing"]) < 0.6) & (np.abs(st["b"]["facing"]) < 0.6) & ~side & (s < 0)
    if near_side.any():
        m2 = bridge.query(Pref[near_side])[0]
        s[near_side] = np.where(m2 > 0, _bridge_mm(m2, M), s[near_side])
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
    UVc, Puc, Wc = Ac[:, :2], Ac[:, 2:5], Ac[:, 5:]

    # 4. offset along the smoothed outward normals
    Vcw, Fcw, cinv = gf.weld(Vc, Fc)
    volb = np.einsum("ij,ij->i", R[br.faces[:, 0]], np.cross(R[br.faces[:, 1]], R[br.faces[:, 2]])).sum() / 6
    Nw_ = gf._unit(gf._smooth(gf._unit(gf.vertex_normals(Vcw, Fcw)) * np.sign(volb),
                              gf._adjacency(Fcw, len(Vcw)), 3))
    X = Vc + Nw_[cinv] * offset_m

    # 5. colour, baked in the body's UV atlas
    Xq_, _, tri, bary = samples(Vc, Fc, 0.0008)
    Aq = np.einsum("nk,nkj->nj", bary, np.hstack([UVc, Puc])[Fc[tri]])
    UVq, Puq = Aq[:, :2], Aq[:, 2:5]
    Nq = gf._unit(gf._unit(gf.vertex_normals(Puc, Fc))[Fc[tri]].mean(1))
    stq = view_state(Puq, Nq)
    cols, valid = {}, {}
    for which, _m, _t in VIEWS:
        ind, _ = maskinfo[which]
        i, j = stq[which]["i"], stq[which]["j"]
        ii, jj = ind[0][i, j], ind[1][i, j]
        near_ok = (np.hypot(ii - i, jj - j) <= 3) | filled[which][i, j]
        valid[which] = stq[which]["seen"] & ((np.abs(stq[which]["facing"]) >= 0.3)
                                             | (stq[which]["sd_mm"] > 10)) & near_ok
        cols[which] = masks[which][2][ii, jj]
    nz = Nq[:, 2]
    wf = np.clip(0.5 + nz, 0, 1) * valid["f"]
    wb = np.clip(0.5 - nz, 0, 1) * valid["b"]
    real = (wf + wb) > 0
    col = np.zeros((len(Puq), 3))
    col[real] = ((cols["f"] * wf[:, None] + cols["b"] * wb[:, None]) / np.maximum(wf + wb, 1e-9)[:, None])[real]
    side_q = ~real
    src_dist = np.zeros(len(Puq))
    if side_q.any() and real.any():
        Pq_m = Puq * k
        _marg, t_q, yf_q, yb_q, th_q, fe_q, be_q = bridge.query(Pq_m[side_q])
        rf = np.nonzero(real & (wf >= wb))[0]
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


def shell_glb(garment) -> bytes:
    """The shell alone as a static textured GLB (the Mesh step's 3D view): positions in the body's bind space."""
    from app.core.glb_mesh import static_glb
    return static_glb(np.asarray(garment.positions, np.float64), np.asarray(garment.indices, np.int64),
                      np.asarray(garment.uvs, np.float64), image=garment.image, mime=garment.mime,
                      material={"name": "shell", "doubleSided": True}, name="shell")


def shell_views(character_name: str, item_id: str, fsig: str, bsig: str) -> Dict[str, Dict[str, Any]]:
    """The two views ``build_shell`` reads, from the piece's stored files: per view the base body's figure mask (the
    bald base view the body was meshed from, flattened like the fit's), the accepted ghost view's mask in that frame
    and the ghost image. ``base_body.MissingInput`` when a view is missing; ``garment_source.FrameRefused`` when the
    front cannot be framed."""
    from PIL import Image
    from app.core import base_body, garment_source
    from app.core import garment_images as gi
    from app.core import garment_store as gs
    from app.core.model_refs import find_ref_image, get_model_refs_dir
    out: Dict[str, Dict[str, Any]] = {}
    front = find_ref_image(character_name, base_body._kind("front"), bsig)
    back = find_ref_image(character_name, base_body._kind("back"), bsig)
    if front is None or back is None:
        raise base_body.MissingInput(base_body.BASE_IMAGES_MISSING)
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
    return out
