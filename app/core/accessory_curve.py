"""The neck curve of a necklace, on the skin of the plain body (Ruling A118, spec
``docs/superpowers/specs/2026-11-16-accessories-design.md`` § 4 / § 11; plan Task 4).

The chain lies on the skin around the neck. Seen from the front it is a U from one side of the neck to the other:

- the jugular notch: the skin straight in front of the ``Neck`` bone head (``jugular_notch``);
- the sides: the skin at the neck's left / right at ``side_height`` — the lowest height (from the Neck bone head up)
  where the rays to both sides and around the nape stay within the neck's width and within ``side_bound`` (1.3 ×
  the Shoulder bone heads' lateral offset), not out on the shoulder tops or a trapezius;
- the front half: the U from side to side down to ``drop_m`` below the notch, ``h(θ) = h_side + (h_front −
  h_side) sin²θ`` at ``x(θ) = x_c + w cos θ``, rays along +z (``_half``);
- the back: radial rays from the neck axis around the nape, from the sides' height down to the Neck bone head at
  the nape where the skin there is the neck (``_back``).

"The skin" is always the innermost layer a ray meets (``ray_hits`` pick ``layer``): never a hair or beard shell
farther out, never the generator's inner wall (A216 review H2). Points that stick out of the loop are dropped
(``_drop_outliers``); the loop is smoothed, resampled by arc length, pushed out along the skin normals by
``offset_m``; ``settle_out`` then holds every sample at ``offset_m`` from the skin patch under the chain. Pure numpy/scipy, rest
pose, positions in the body's bind space (metres). The front is +z (the rig contract's facing).
"""
from typing import Dict, Tuple

import numpy as np

#: The loop is resampled to this many points (``neck_curve``'s default).
SAMPLES = 96
#: ``settle``: passes of "push out to the offset, then smooth".
SETTLE_PASSES = 4
#: Closed-loop smoothing passes over the raw skin points (``neck_curve_detail``).
SMOOTH_PASSES = 12


def weld(P: np.ndarray, F: np.ndarray, tol: float = 1e-6) -> Tuple[np.ndarray, np.ndarray]:
    """``(P, F)`` with coincident vertices (UV seams) merged — a section walks across seams only on a welded mesh."""
    P = np.asarray(P, np.float64)
    keys = np.round(P / tol).astype(np.int64)
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    F2 = inverse.reshape(-1)[np.asarray(F, np.int64)]
    keep = (F2[:, 0] != F2[:, 1]) & (F2[:, 1] != F2[:, 2]) & (F2[:, 2] != F2[:, 0])
    return P[first], F2[keep]


def vertex_normals(P: np.ndarray, F: np.ndarray) -> np.ndarray:
    """Area-weighted unit vertex normals (outward for an outward-wound mesh)."""
    n = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    N = np.zeros_like(P)
    for k in range(3):
        np.add.at(N, F[:, k], n)
    return N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)


def resample(pts: np.ndarray, n: int) -> np.ndarray:
    """A closed polyline resampled to ``n`` points equally spaced by arc length."""
    closed = np.vstack([pts, pts[:1]])
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    cum = np.r_[0.0, np.cumsum(seg)]
    target = np.linspace(0.0, cum[-1], n, endpoint=False)
    out = np.empty((n, 3))
    for k in range(3):
        out[:, k] = np.interp(target, cum, closed[:, k])
    return out


#: The side height search (``side_height``): step and the most it rises above the Neck bone head.
LIFT_STEP_M = 0.002
LIFT_MAX_M = 0.06
#: A side point counts as "on the neck" when its distance from the neck axis is at most this times the neck's
#: half width measured ``NECK_PROBE_M`` above the Neck bone head.
NECK_WIDTH_SLACK = 1.3
NECK_PROBE_M = 0.05
#: Rays look for the skin at most this far from their origin (a 30 cm drop reaches a chest 16 cm in front of the
#: neck axis; the front rays start 10 cm behind it).
RAY_MAX_M = 0.40


#: One skin layer: the generator's inner wall lies a few mm under the skin (up to ~14 mm measured on the 14 stored
#: plain bodies, A216 review); hits within this of the first one are the same layer.
LAYER_M = 0.016
#: A side point lies at most this times the Shoulder bone head's lateral offset from the Neck bone head — the
#: anatomical bound that keeps the chain off hair, a beard or the shoulder tops (A216 review H2: the 14 plain bodies
#: measure neck half widths of 1.1–1.2× that offset).
SIDE_MAX_SHOULDER = 1.3
#: The skin under the chain: body faces whose centroid lies within this of the chain's skin points.
SKIN_BAND_M = 0.012


def ray_hits(P: np.ndarray, F: np.ndarray, origins: np.ndarray, dirs: np.ndarray,
             max_t: float = RAY_MAX_M, *, pick: str = "outer",
             min_t: float = 0.0) -> Tuple[np.ndarray, np.ndarray]:
    """Per ray ``(origin, dir)`` one hit within ``(min_t, max_t]`` (Möller–Trumbore over every triangle):
    ``pick`` ``outer`` = the OUTERMOST hit; ``layer`` = the outer surface of the INNERMOST layer — the first hit past
    ``min_t`` and the last one within ``LAYER_M`` of it (the skin over its inner wall, never a hair or beard shell
    farther out, A216 review H2). ``(t (k,), face index (k,))`` — t NaN and face −1 where a ray hits nothing."""
    A, B, C = P[F[:, 0]], P[F[:, 1]], P[F[:, 2]]
    e1, e2 = B - A, C - A
    t_out = np.full(len(origins), np.nan)
    f_out = np.full(len(origins), -1, np.int64)
    for i, (o, d) in enumerate(zip(origins, dirs)):
        h = np.cross(d, e2)
        a = np.einsum("ij,ij->i", e1, h)
        ok = np.abs(a) > 1e-14
        inv = np.where(ok, 1.0 / np.where(ok, a, 1.0), 0.0)
        s = o - A
        u = inv * np.einsum("ij,ij->i", s, h)
        q = np.cross(s, e1)
        v = inv * (q @ d)
        t = inv * np.einsum("ij,ij->i", e2, q)
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > min_t) & (t <= max_t)
        if not hit.any():
            continue
        idx = np.flatnonzero(hit)
        if pick == "layer":
            first = float(t[idx].min())
            idx = idx[t[idx] <= first + LAYER_M]
        j = idx[int(np.argmax(t[idx]))]
        t_out[i], f_out[i] = t[j], j
    return t_out, f_out


def _ring(P, F, centre: np.ndarray, heights: np.ndarray, phis: np.ndarray, *, allow_miss: bool = False):
    """The skin (``ray_hits`` pick ``layer``) of horizontal rays from the neck axis ``centre`` (x, z) at ``heights``
    toward the angles ``phis`` (0 = front +z, π/2 = +x): ``(points, face normals oriented outward, t)``. A ray that
    finds nothing raises ``ValueError`` — or, with ``allow_miss``, returns t NaN for it."""
    origins = np.c_[np.full(len(phis), centre[0]), heights, np.full(len(phis), centre[2])]
    dirs = np.c_[np.sin(phis), np.zeros(len(phis)), np.cos(phis)]
    t, f = ray_hits(P, F, origins, dirs, pick="layer")
    if np.isnan(t).any():
        if not allow_miss:
            raise ValueError("The neck was not found on this body (no skin around the neck bone)")
        return origins + np.nan_to_num(t)[:, None] * dirs, np.zeros_like(origins), t
    pts = origins + t[:, None] * dirs
    n = np.cross(P[F[f, 1]] - P[F[f, 0]], P[F[f, 2]] - P[F[f, 0]])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    n = np.where((np.einsum("ij,ij->i", n, dirs) < 0)[:, None], -n, n)
    return pts, n, t


#: Directions the side-height search checks (``side_height``): both sides and the nape between them.
SIDE_SEARCH_PHIS = np.linspace(np.pi / 2, 3 * np.pi / 2, 9)


def side_height(P, F, centre: np.ndarray, y_from: float, y_neck: float, max_side: float = np.inf) -> float:
    """The lowest height at or above ``y_from`` (``LIFT_STEP_M`` steps, at most ``LIFT_MAX_M`` higher) at which
    the rays from the neck axis to both sides and around the nape (``SIDE_SEARCH_PHIS``) all meet the skin within
    ``NECK_WIDTH_SLACK`` × the neck's half width ``NECK_PROBE_M`` above the Neck bone and within ``max_side`` of the
    axis — where the ring is the neck, not the shoulder tops or a trapezius under it (A216 review H2, Henrik). A
    ray that finds no skin lifts too (L3). ``ValueError`` when no height qualifies."""
    sides = np.array([np.pi / 2, -np.pi / 2])
    _, _, t_neck = _ring(P, F, centre, np.full(2, y_neck + NECK_PROBE_M), sides, allow_miss=True)
    if np.isnan(t_neck).any():
        raise ValueError("The neck was not found on this body (no skin at the sides of the neck)")
    limit = min(NECK_WIDTH_SLACK * float(t_neck.max()), float(max_side))
    phis = SIDE_SEARCH_PHIS
    y = y_from
    while y <= y_from + LIFT_MAX_M + 1e-9:
        _, _, t = _ring(P, F, centre, np.full(len(phis), y), phis, allow_miss=True)
        if not np.isnan(t).any() and float(t.max()) <= limit:
            return y
        y += LIFT_STEP_M
    raise ValueError("The sides of the neck were not found within the shoulders on this body")


def _half(P, F, centre: np.ndarray, side_r: np.ndarray, side_l: np.ndarray, h_side: float, h_mid: float,
          k: int, toward: float):
    """One half of the chain seen along z: ``k`` rays along ``toward`` · z (+1 the front, −1 the back) from 10 cm
    behind the neck axis, at lateral positions ``x(θ) = x_c + w cos θ`` between the side points (θ in (0, π), dense
    near the sides) and heights ``h_side + (h_mid − h_side) sin²θ`` (the U seen from the front / back). The
    skin is the innermost layer past the neck axis plane (``ray_hits`` pick ``layer``, ``min_t`` 0.10). ``(points (k, 3), outward normals)`` from the +x side to the −x side; a ray that
    finds nothing takes its neighbour's point."""
    theta = np.linspace(0.0, np.pi, k + 2)[1:-1]
    xc, w = (side_r[0] + side_l[0]) / 2, (side_r[0] - side_l[0]) / 2
    xs = xc + w * np.cos(theta)
    ys = h_side + (h_mid - h_side) * np.sin(theta) ** 2
    z0 = centre[2] - toward * 0.10
    origins = np.c_[xs, ys, np.full(k, z0)]
    dirs = np.tile([0.0, 0.0, toward], (k, 1))
    t, f = ray_hits(P, F, origins, dirs, pick="layer", min_t=0.10)
    pts = origins + np.nan_to_num(t)[:, None] * dirs
    n = np.cross(P[F[f, 1]] - P[F[f, 0]], P[F[f, 2]] - P[F[f, 0]])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    n = np.where((n[:, 2] * toward < 0)[:, None], -n, n)
    missing = np.isnan(t)
    if missing.all():
        raise ValueError("the chain found no skin in front of / behind the neck")
    good = np.flatnonzero(~missing)
    for i in np.flatnonzero(missing):
        j = good[np.argmin(np.abs(good - i))]
        pts[i], n[i] = pts[j], n[j]
    return pts, n


def side_bound(bones: Dict[str, np.ndarray]) -> float:
    """``SIDE_MAX_SHOULDER`` × the mean lateral offset of the two Shoulder bone heads from the Neck bone head (∞ when
    the skeleton has no shoulders)."""
    neck = np.asarray(bones["neck"], np.float64)
    offs = [abs(float(np.asarray(bones[k])[0]) - float(neck[0])) for k in ("leftshoulder", "rightshoulder")
            if k in bones]
    return SIDE_MAX_SHOULDER * float(np.mean(offs)) if offs else float("inf")


def _back(P, F, centre: np.ndarray, h: float, k: int, h_low: float = None, limit: float = np.inf):
    """The back of the chain: ``k`` radial rays from the neck axis around the nape (φ from π/2 to 3π/2, i.e. from
    the +x side over the nape to the −x side), the skin (pick ``layer``). Height ``h`` (the sides') at the sides
    down to ``h_low`` (the Neck bone head) at the nape, ``h + (h_low − h) sin²(φ − π/2)``; a ray there that finds
    no skin within ``limit`` of the axis (a trapezius under the nape, A216 review H2, Henrik) is cast again at
    ``h``. Radial rays are never tangent to the neck, where z-rays from the front slipped past it. ``(points,
    outward normals)``; a ray that finds nothing takes its neighbour's point."""
    phis = np.linspace(np.pi / 2, 3 * np.pi / 2, k + 2)[1:-1]
    lo = h if h_low is None else h_low
    heights = h + (lo - h) * np.sin(phis - np.pi / 2) ** 2
    pts, n, t = _ring(P, F, centre, heights, phis, allow_miss=True)
    redo = np.isnan(t) | (t > limit)
    if redo.any():
        p2, n2, t2 = _ring(P, F, centre, np.full(int(redo.sum()), h), phis[redo], allow_miss=True)
        pts[redo], n[redo], t[redo] = p2, n2, t2
    missing = np.isnan(t)
    if missing.all():
        raise ValueError("The back of the neck was not found on this body")
    good = np.flatnonzero(~missing)
    for i in np.flatnonzero(missing):
        j = good[np.argmin(np.abs(good - i))]
        pts[i], n[i] = pts[j], n[j]
    return pts, n


def jugular_notch(P, F, bones: Dict[str, np.ndarray]) -> np.ndarray:
    """The front-most surface point at the ``Neck`` bone head's height (the ray from the neck axis forward)."""
    neck = np.asarray(bones["neck"], np.float64)
    pts, _, _ = _ring(np.asarray(P, np.float64), np.asarray(F, np.int64), neck, np.array([neck[1]]), np.array([0.0]))
    return pts[0]


def _crop(P, F, centre: np.ndarray, reach: float = 0.3) -> np.ndarray:
    """The faces of ``F`` within ``reach`` of the neck bone head (box test) — the rays never see the rest."""
    lo, hi = centre - reach, centre + reach
    T = P[F]
    keep = np.all((T.min(1) <= hi) & (T.max(1) >= lo), axis=1)
    return F[keep]


#: A raw skin point lies at most this much farther from the neck axis (horizontally) than the median of its
#: ``OUTLIER_WINDOW`` neighbours on each side — farther is a ray that slipped past the neck onto the trapezius or a
#: hair strand (A216 review H2: Henrik's back rays at the neck side, tangent to it).
OUTLIER_M = 0.006
OUTLIER_WINDOW = 8


def _drop_outliers(pts: np.ndarray, normals: np.ndarray, neck: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """The closed raw loop without the points that stick out (``OUTLIER_M``); the resample bridges them."""
    r = np.linalg.norm(pts[:, [0, 2]] - neck[[0, 2]], axis=1)
    k = OUTLIER_WINDOW
    windows = np.stack([np.roll(r, s) for s in range(-k, k + 1) if s], 1)
    keep = r <= np.median(windows, axis=1) + OUTLIER_M
    if keep.sum() < len(pts) // 2:
        return pts, normals
    return pts[keep], normals[keep]


def neck_curve(P, F, bones: Dict[str, np.ndarray], *, drop_m: float, offset_m: float,
               n: int = SAMPLES) -> np.ndarray:
    """The closed ``(n, 3)`` chain centre line (module docstring) — ``offset_m`` off the skin."""
    return neck_curve_detail(P, F, bones, drop_m=drop_m, offset_m=offset_m, n=n)["curve"]


def neck_curve_detail(P, F, bones: Dict[str, np.ndarray], *, drop_m: float, offset_m: float,
                      n: int = SAMPLES, settle: bool = True) -> Dict[str, object]:
    """``neck_curve`` with what it was made of: ``{curve, surface, landmarks}`` — ``surface`` the skin points under
    the curve, ``landmarks`` ``{notch, front, back, side_y}`` (module docstring)."""
    Pw, Fw = weld(np.asarray(P, np.float64), np.asarray(F, np.int64))
    neck = np.asarray(bones["neck"], np.float64)
    Fc = _crop(Pw, Fw, neck)
    notch = jugular_notch(Pw, Fc, bones)
    h_back = float(neck[1])
    h_front = float(notch[1]) - float(drop_m)
    h_side = side_height(Pw, Fc, neck, h_back, h_back, max_side=side_bound(bones))
    k = 2 * n
    sides, n_sides, _ = _ring(Pw, Fc, neck, np.full(2, h_side), np.array([np.pi / 2, -np.pi / 2]))
    front, nf = _half(Pw, Fc, neck, sides[0], sides[1], h_side, h_front, k, +1.0)
    back, nb = _back(Pw, Fc, neck, h_side, k, h_low=h_back, limit=side_bound(bones))
    # Closed: +x side -> front -> -x side -> back (reversed) -> +x side.
    pts = np.vstack([sides[:1], front, sides[1:], back[::-1]])
    normals = np.vstack([n_sides[:1], nf, n_sides[1:], nb[::-1]])
    pts, normals = _drop_outliers(pts, normals, neck)
    # The two halves meet at the sides with a small jog (the front rays meet the neck's front, the side rays its
    # side): a few closed-loop smoothing passes before the resample even it out; ``settle_out`` puts the points
    # back off the skin afterwards.
    for _ in range(SMOOTH_PASSES):
        pts = 0.5 * pts + 0.25 * (np.roll(pts, 1, 0) + np.roll(pts, -1, 0))
    surface = resample(pts, n)
    from scipy.spatial import cKDTree
    _, near = cKDTree(pts).query(surface)
    outward = normals[near]
    # The skin under the chain: faces within ``SKIN_BAND_M`` of it — a hair or beard shell farther out never counts
    # for the settle and the gap (A216 review H2).
    centroids = Pw[Fw].mean(1)
    d, _ = cKDTree(surface).query(centroids, distance_upper_bound=SKIN_BAND_M)
    skin = Fw[np.isfinite(d)]
    curve = surface + outward * float(offset_m)
    if settle:
        curve = settle_out(curve, Pw, skin, float(offset_m), outward=outward)
    lowest = front[int(np.argmin(front[:, 1]))]
    back_mid = back[int(np.argmin(np.abs(back[:, 0] - neck[0])))]
    a = abs(float(sides[0][0] - sides[1][0])) / 2
    b = abs(float(notch[2] - back_mid[2])) / 2
    h = ((a - b) / (a + b)) ** 2 if a + b > 0 else 0.0
    ellipse = float(np.pi * (a + b) * (1 + 3 * h / (10 + np.sqrt(4 - 3 * h))))
    marks = {"notch": notch.tolist(), "front": lowest.tolist(), "back": back_mid.tolist(), "side_y": h_side,
             "side_half_width_m": round(a, 4), "neck_ellipse_m": round(ellipse, 4)}
    return {"curve": curve, "surface": surface, "outward": outward, "welded": (Pw, skin), "landmarks": marks}


def _closest(X: np.ndarray, P: np.ndarray, Fc: np.ndarray, tree, faces: bool = False):
    """The closest point on the faces ``Fc`` (centroid tree ``tree``, 16 candidates) to each point of ``X``; with
    ``faces`` also the index into ``Fc`` of the face it lies on."""
    from app.core.garment_fit import point_triangle_closest
    _, cand = tree.query(X, k=min(16, len(Fc)))
    cand = cand.reshape(len(X), -1)
    best = np.full(len(X), np.inf)
    out = np.zeros_like(X)
    which = np.zeros(len(X), np.int64)
    for j in range(cand.shape[1]):
        f = Fc[cand[:, j]]
        cp = point_triangle_closest(X, P[f[:, 0]], P[f[:, 1]], P[f[:, 2]])
        d = np.linalg.norm(X - cp, axis=1)
        better = d < best
        best = np.where(better, d, best)
        out = np.where(better[:, None], cp, out)
        which = np.where(better, cand[:, j], which)
    return (out, which) if faces else out


def settle_out(curve: np.ndarray, P: np.ndarray, F: np.ndarray, clearance: float,
               passes: int = SETTLE_PASSES, outward: np.ndarray = None) -> np.ndarray:
    """Every point of the closed ``curve`` at ``clearance`` off the surface ``(P, F)``: per pass a one-step
    neighbour smoothing, then each point put at exactly ``clearance`` along (point − its closest surface point) —
    out of the skin where the smoothing cut a convex stretch, back toward it where it bridged a hollow (A216:
    bridging the notch left Lirien's chain up to 3.2 mm off the skin in the sit clip). The side is the outward
    normal: ``outward`` (per point, the skin's normal under it — for an open skin patch, A216 review H2), else the
    closed surface's signed distance (``garment_shell.signed_distance``), so a point that fell inside comes out."""
    from scipy.spatial import cKDTree
    lo, hi = curve.min(0) - 0.06, curve.max(0) + 0.06
    keep = np.all((P[F].min(1) <= hi) & (P[F].max(1) >= lo), axis=1)
    Fc = F[keep]
    tree = cKDTree(P[Fc].mean(1))
    X = np.array(curve, np.float64)
    for p in range(passes):
        if p:
            X = 0.5 * X + 0.25 * (np.roll(X, 1, 0) + np.roll(X, -1, 0))
        for _ in range(2):
            cp = _closest(X, P, Fc, tree)
            away = X - cp
            away = away / np.maximum(np.linalg.norm(away, axis=1, keepdims=True), 1e-12)
            if outward is not None:
                inside = np.einsum("ij,ij->i", away, outward) < 0
            else:
                from app.core.garment_shell import signed_distance
                inside = signed_distance(X, P, F) < 0
            away = np.where(inside[:, None], -away, away)
            X = cp + away * clearance
    return X
