"""Register HAAR strands onto the wearer's head (strand-hair spec 2026-11-13 § 6.3.1 step 1).

A port of the HAAR spike's ``register.py`` with its body preparation (``body.py``), user-approved in spike 2
(``~/claude-out/haar-spike2``). HAAR grows its strands on its own template head (``<input_name>_head.obj``, a FLAME
head, same space as the strands). Registration moves them onto the wearer:

1. The head frame (``body_frame``): chin, crown, ear line, shoulder top, the Head-weighted box, the landmarks, the
   head centre ``hc`` (the middle of the box, ``HC_DOWN`` of the way from the crown to the chin), the head's
   ``garment_fit.body_sdf`` (``HEAD_CROP_M`` round ``hc``) and the RADIAL map of the outer skin: per 1° direction
   from ``hc`` the outermost inside→outside crossing of the filled field (the base GLBs have mixed winding and inner
   shells; the filled field has neither). ``skin`` = those points.
2. The template head onto the skin (``icp_template``): its largest component (FLAME's eyeballs dropped), scaled by
   the width of a slice ``SLICE_M`` below its crown against the skin's, crowns on each other, then a trimmed
   bidirectional ICP of the template above its nose tip onto the skin above the wearer's (similarity, Umeyama,
   ``ICP_ITERATIONS``, the worst ``100 - TRIM_PERCENTILE`` % of each direction dropped). The strands take that
   similarity.
3. The hairline (``hairline=True``): HairDeck's placement rule — the strands are pitched about ``hc``'s x axis
   (within ±``HAIRLINE_TILT_MAX_DEG``, bisection) until the front hairline (the ``HAIRLINE_PERCENTILE`` height of the
   roots in the front strip) sits at ``garment_hairdeck.hairline_target(brow, crown)``, the brow of
   ``garment_hairdeck.placement_landmarks`` (a beard modelled into the base falls back to the proportions). A head
   without a face profile (a sphere) gets no tilt.
4. Each root snaps onto the radial skin + ``ROOT_LIFT_M`` by moving its whole strand; the strands are resampled to
   ``N_POINTS`` points by arc length (``N_STRANDS`` of them, a fixed-seed sample, so a refit is bitwise the same).
5. The head part (above the ear line, roots excluded) leaves the skull layer-keeping (``garment_hairdeck.layer_push``)
   and every head segment whose MIDPOINT still lies within ``MID_MIN_M`` of the skull (it cuts an ear rim between two
   clear points) is pushed out by its midpoint, up to ``MID_PASSES`` passes.

Pure numpy / scipy on a ``glb_mesh.BodyMesh``; no file, no world state.
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, Optional, Tuple

import numpy as np

#: The strands kept per hairstyle (a fixed-seed sample of HAAR's ~11k) and the points per strand after resampling.
N_STRANDS = 4000
N_POINTS = 96
SAMPLE_SEED = 0
#: The head centre lies this share of the way from the crown down to the chin (the spike's ``hc``).
HC_DOWN = 0.45
#: The head SDF crop round ``hc`` (m): x / z ± ``HEAD_CROP_M``, y ``hc - HEAD_CROP_M`` .. crown + ``CROWN_UP_M``.
HEAD_CROP_M = 0.18
CROWN_UP_M = 0.06
#: The radial skin map: 1° directions (theta from +y, phi round y), radii ``RADIAL_R0`` .. ``RADIAL_R1`` every
#: ``RADIAL_DR`` m.
RADIAL_DEG = 1.0
RADIAL_R0, RADIAL_R1, RADIAL_DR = 0.02, 0.17, 0.001
#: Template placement: the slice ``SLICE_M`` below the crown sets the start scale (3 rounds); the nose tip is the
#: template's frontmost point ``NOSE_BAND_M`` below its crown (scaled); ICP above the nose tip - ``NOSE_DOWN_M``.
SLICE_M = (0.03, 0.05)
NOSE_BAND_M = (0.09, 0.19)
NOSE_DOWN_M = 0.01
ICP_ITERATIONS = 60
TRIM_PERCENTILE = 90
#: The hairline tilt: |tilt| <= ``HAIRLINE_TILT_MAX_DEG``; the front strip is ``|x - cx| < HAIRLINE_STRIP_M`` in
#: front of ``cz + HAIRLINE_FRONT * head_d``; its hairline the ``HAIRLINE_PERCENTILE`` of the root heights.
HAIRLINE_TILT_MAX_DEG = 15.0
HAIRLINE_STRIP_M = 0.02
HAIRLINE_FRONT = 0.3
HAIRLINE_PERCENTILE = 5
HAIRLINE_BISECT = 40
#: The scalp target (roots residual): skin above ear + ``SCALP_EAR_UP_M``, the front only above brow +
#: ``SCALP_BROW_UP_M`` (front = in front of ``cz + SCALP_FRONT * head_d``), the low temples (``|x - cx| >
#: SCALP_TEMPLE_X_M`` below ``hc + SCALP_TEMPLE_UP_M``) left out.
SCALP_EAR_UP_M = 0.02
SCALP_FRONT = 0.15
SCALP_BROW_UP_M = 0.02
SCALP_TEMPLE_X_M = 0.07
SCALP_TEMPLE_UP_M = 0.005
#: A root sits this far outside the skin; the head part is pushed ``HEAD_CLEAR_M`` out (band ``HEAD_BAND_M``).
ROOT_LIFT_M = 0.0015
HEAD_CLEAR_M = 0.004
HEAD_BAND_M = 0.006
MID_MIN_M = 0.003
MID_PASSES = 6
#: A strand shorter than this is dropped; an extent beyond 3 / 300 marks a cm / mm file.
MIN_LENGTH_M = 1e-4


# --- The head --------------------------------------------------------------------------------------------------

def _dirs(step_deg: float = RADIAL_DEG) -> Tuple[np.ndarray, Tuple[int, int]]:
    th = np.radians(np.arange(step_deg / 2, 180, step_deg))
    ph = np.radians(np.arange(step_deg / 2, 360, step_deg))
    T, P = np.meshgrid(th, ph, indexing="ij")
    d = np.stack([np.sin(T) * np.cos(P), np.cos(T), np.sin(T) * np.sin(P)], -1)
    return d.reshape(-1, 3), T.shape


def radial_map(sdf, hc: np.ndarray) -> np.ndarray:
    """(180, 360) radius of the outer skin from ``hc`` per 1° direction: the outermost inside→outside crossing of
    ``sdf`` along the ray (linear between the two samples), 0 where the ray never leaves the body."""
    dirs, shape = _dirs()
    rs = np.arange(RADIAL_R0, RADIAL_R1, RADIAL_DR)
    out = np.zeros(len(dirs))
    chunk = 6000
    for a in range(0, len(dirs), chunk):
        d = dirs[a:a + chunk]
        X = hc[None, None] + d[:, None] * rs[None, :, None]
        s = np.asarray(sdf.sample(X.reshape(-1, 3))).reshape(len(d), len(rs))
        inside = s < 0
        last = np.where(inside.any(1), len(rs) - 1 - np.argmax(inside[:, ::-1], 1), -1)
        ok = (last >= 0) & (last < len(rs) - 1)
        i = np.clip(last, 0, len(rs) - 2)
        rows = np.arange(len(d))
        s0, s1 = s[rows, i], s[rows, i + 1]
        frac = np.clip(s0 / np.where(np.abs(s0 - s1) > 1e-12, s0 - s1, 1e-12), 0, 1)
        out[a:a + chunk] = np.where(ok, rs[i] + frac * RADIAL_DR, 0.0)
    return out.reshape(shape)


def body_frame(body, *, sdf=None) -> Dict[str, Any]:
    """The wearer's head for registration (module docstring, step 1): ``chin``, ``top``, ``ear``, ``shoulder``,
    ``cx`` / ``cz`` / ``head_w`` / ``head_d`` (``garment_hairdeck._head_box``), ``landmarks`` / ``landmark_source``
    (``placement_landmarks``), ``hc``, ``sdf`` (the head crop; ``sdf`` given: used as is), ``Rh`` (the radial map),
    ``skin`` (its points), ``head_w_col`` (the Head weight per body vertex). ValueError without a skin."""
    from app.core import garment_fit as gf
    from app.core import garment_hairdeck as gh
    if not body.joint_names:
        raise ValueError("The rigged base has no skin")
    P = np.asarray(body.positions, np.float64)
    head_w = gf.dense_weights(body)[:, gf.joint_index(body, "head")]
    head_v = head_w > 0.5
    chin = gf.chin_height(body)
    top = float(P[head_v, 1].max())
    cx, cz, hw, hd = gh._head_box(P, head_v)
    hc = np.array([cx, top - HC_DOWN * (top - chin), cz])
    if sdf is None:
        lo = np.array([cx - HEAD_CROP_M, hc[1] - HEAD_CROP_M, cz - HEAD_CROP_M])
        hi = np.array([cx + HEAD_CROP_M, top + CROWN_UP_M, cz + HEAD_CROP_M])
        sdf = gf.body_sdf(P, np.asarray(body.faces, np.int64).reshape(-1, 3), vox=gf.VOX_M, bounds=(lo, hi))
    Rh = radial_map(sdf, hc)
    dirs, _ = _dirs()
    flat = Rh.reshape(-1)
    skin = (hc + dirs * flat[:, None])[flat > 0]
    lm, source, _rejected = gh.placement_landmarks(P, head_v, chin, top)
    return {"chin": float(chin), "top": top, "ear": float(gf.ear_line_height(body)),
            "shoulder": float(gf.shoulder_top_height(body)), "cx": cx, "cz": cz, "head_w": hw, "head_d": hd,
            "hc": hc, "sdf": sdf, "Rh": Rh, "skin": skin, "landmarks": lm or {}, "landmark_source": source,
            "head_w_col": head_w}


def scalp_target(B: Dict[str, Any]) -> np.ndarray:
    """The skin points the hair grows from (module constants): above the ear line, the forehead only above the
    brow, the low temples left out."""
    S = B["skin"]
    brow = float(B["landmarks"].get("brow_y", B["top"] - 0.09))
    front = S[:, 2] > B["cz"] + SCALP_FRONT * B["head_d"]
    keep = (S[:, 1] > B["ear"] + SCALP_EAR_UP_M) & ((~front) | (S[:, 1] > brow + SCALP_BROW_UP_M))
    keep &= ~((np.abs(S[:, 0] - B["cx"]) > SCALP_TEMPLE_X_M) & (S[:, 1] < B["hc"][1] + SCALP_TEMPLE_UP_M))
    return S[keep]


# --- Registration ----------------------------------------------------------------------------------------------

def umeyama(src: np.ndarray, dst: np.ndarray) -> Tuple[float, np.ndarray, np.ndarray]:
    """The similarity ``(s, R, t)`` with ``dst ≈ s R src + t`` in the least-squares sense (Umeyama 1991)."""
    ms, md = src.mean(0), dst.mean(0)
    a, b = src - ms, dst - md
    U, D, Vt = np.linalg.svd(b.T @ a / len(src))
    S = np.eye(3)
    S[2, 2] = np.sign(np.linalg.det(U @ Vt)) or 1.0
    R = U @ S @ Vt
    s = float((D * np.diag(S)).sum() / (a ** 2).sum(1).mean())
    return s, R, md - s * R @ ms


def largest_component(V: np.ndarray, F: Optional[np.ndarray]) -> np.ndarray:
    """The vertices of ``V``'s largest connected component (``F`` None or empty: all of them)."""
    V = np.asarray(V, np.float64).reshape(-1, 3)
    if F is None or not len(F):
        return V
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    F = np.asarray(F, np.int64).reshape(-1, 3)
    A = coo_matrix((np.ones(F.size), (F.ravel(), np.roll(F, 1, 1).ravel())), shape=(len(V), len(V)))
    _, comp = connected_components(A, directed=False)
    return V[comp == np.bincount(comp).argmax()]


def icp_template(T: np.ndarray, B: Dict[str, Any]) -> Tuple[float, np.ndarray, np.ndarray, float, np.ndarray]:
    """The template head ``T`` onto the wearer's skin (module docstring, step 2) -> ``(s, R, t, s_init, resid)``,
    ``resid`` = the distance of each placed template point used to its nearest skin point."""
    from scipy.spatial import cKDTree
    head = B["skin"]
    top, t_top = float(head[:, 1].max()), float(T[:, 1].max())

    def slice_box(P, y0, y1):
        q = P[(P[:, 1] > y0) & (P[:, 1] < y1)]
        if len(q) < 3:
            raise ValueError("The head slice below the crown is empty")
        return q[:, 0].min(), q[:, 0].max(), q[:, 2].min(), q[:, 2].max()
    s = 1.0
    for _ in range(3):
        bx0, bx1, bz0, bz1 = slice_box(head, top - SLICE_M[1], top - SLICE_M[0])
        fx0, fx1, fz0, fz1 = slice_box(T, t_top - SLICE_M[1] / s, t_top - SLICE_M[0] / s)
        s = 0.5 * ((bx1 - bx0) / (fx1 - fx0) + (bz1 - bz0) / (fz1 - fz0))
    fc = np.array([(fx0 + fx1) / 2, t_top, (fz0 + fz1) / 2])
    bc = np.array([(bx0 + bx1) / 2, top, (bz0 + bz1) / 2])
    R, t, s_init = np.eye(3), bc - s * fc, s
    band = T[(T[:, 1] < t_top - NOSE_BAND_M[0] / s) & (T[:, 1] > t_top - NOSE_BAND_M[1] / s)]
    nose = band[band[:, 2].argmax()] if len(band) else T[T[:, 2].argmax()]
    src = T[T[:, 1] > nose[1] - NOSE_DOWN_M / s]
    for _ in range(ICP_ITERATIONS):
        cur = s * src @ R.T + t
        cut = s * R @ nose + t
        tgt = head[head[:, 1] > cut[1] - NOSE_DOWN_M]
        d1, i1 = cKDTree(tgt).query(cur)
        d2, i2 = cKDTree(cur).query(tgt)
        k1, k2 = d1 < np.percentile(d1, TRIM_PERCENTILE), d2 < np.percentile(d2, TRIM_PERCENTILE)
        s, R, t = umeyama(np.vstack([src[k1], src[i2[k2]]]), np.vstack([tgt[i1[k1]], tgt[k2]]))
    cur = s * src @ R.T + t
    d, _ = cKDTree(head).query(cur)
    return float(s), R, t, float(s_init), d


def _radial(B: Dict[str, Any], P: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(r, unit direction, skin radius)`` of points ``P`` seen from ``hc``."""
    v = P - B["hc"]
    r = np.linalg.norm(v, axis=-1)
    d = v / np.maximum(r, 1e-9)[..., None]
    step = RADIAL_DEG
    ti = np.clip((np.degrees(np.arccos(np.clip(d[..., 1], -1, 1))) / step).astype(int), 0, B["Rh"].shape[0] - 1)
    pj = np.clip(((np.degrees(np.arctan2(d[..., 2], d[..., 0])) % 360) / step).astype(int), 0, B["Rh"].shape[1] - 1)
    return r, d, B["Rh"][ti, pj]


def resample(P: np.ndarray, n: int) -> Tuple[np.ndarray, np.ndarray]:
    """Strands ``P`` (S, K, 3) resampled to ``n`` points evenly by arc length -> ``(out, length)``."""
    P = np.asarray(P, np.float64)
    seg = np.linalg.norm(np.diff(P, axis=1), axis=2)
    cum = np.concatenate([np.zeros((len(P), 1)), np.cumsum(seg, 1)], 1)
    L = cum[:, -1]
    out = np.empty((len(P), n, 3))
    for i in range(len(P)):
        q = np.linspace(0, L[i], n)
        for a in range(3):
            out[i, :, a] = np.interp(q, cum[i], P[i, :, a])
    return out, L


def _pitch(X: np.ndarray, hc: np.ndarray, deg: float) -> np.ndarray:
    a = math.radians(deg)
    Rx = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    return (X - hc) @ Rx.T + hc


def _hairline_y(roots: np.ndarray, B: Dict[str, Any]) -> float:
    m = (np.abs(roots[:, 0] - B["cx"]) < HAIRLINE_STRIP_M) & (roots[:, 2] > B["cz"] + HAIRLINE_FRONT * B["head_d"])
    return float(np.percentile(roots[m, 1], HAIRLINE_PERCENTILE)) if m.sum() > 5 else float("nan")


def _hairline_tilt(X: np.ndarray, B: Dict[str, Any]) -> Tuple[float, Optional[float], Optional[float]]:
    """``(tilt, hairline before, target)``: the pitch about ``hc``'s x axis that puts the front hairline on the
    target (bisection; the nearer limit when the target lies outside the range); 0 without landmarks or front
    roots."""
    from app.core import garment_hairdeck as gh
    lm = B["landmarks"]
    if "brow_y" not in lm:
        return 0.0, None, None
    target = gh.hairline_target(float(lm["brow_y"]), float(B["top"]))
    roots = X[:, 0]
    hc = B["hc"]

    def f(deg):
        return _hairline_y(_pitch(roots, hc, deg), B) - target
    hl0 = _hairline_y(roots, B)
    lo, hi = -HAIRLINE_TILT_MAX_DEG, HAIRLINE_TILT_MAX_DEG
    f_lo, f_hi = f(lo), f(hi)
    if not (math.isfinite(hl0) and math.isfinite(f_lo) and math.isfinite(f_hi)):
        return 0.0, None if not math.isfinite(hl0) else hl0, target
    if f_lo * f_hi >= 0:
        return (lo if abs(f_lo) < abs(f_hi) else hi), hl0, target
    for _ in range(HAIRLINE_BISECT):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if fm * f_lo > 0:
            lo, f_lo = mid, fm
        else:
            hi = mid
    return 0.5 * (lo + hi), hl0, target


def register(strands: np.ndarray, template_head: np.ndarray, body, *, hairline: bool = True,
             template_faces: Optional[np.ndarray] = None, frame: Optional[Dict[str, Any]] = None,
             n_strands: int = N_STRANDS, n_points: int = N_POINTS, seed: int = SAMPLE_SEED
             ) -> Tuple[np.ndarray, Dict[str, Any]]:
    """HAAR ``strands`` (N, P, 3, template space) registered onto ``body`` (module docstring) -> ``(X, info)``:
    ``X`` (S, ``n_points``, 3) metres in the body's bind space, root first, S = min(N, ``n_strands``) (fewer when
    strands of no length are dropped). ``template_head``: the template's vertices (``template_faces``: its faces,
    so the largest component is kept); ``frame``: a ``body_frame`` of ``body`` the caller already has.
    ``info``: ``scale``, ``scale_init``, ``pitch_deg`` / ``yaw_deg`` of the similarity, ``icp_resid_median_m`` /
    ``icp_resid_p95_m`` (template to skin), ``root_resid_p50_m`` / ``root_resid_p95_m`` (the registered roots to the
    scalp target, before the snap), ``root_snap_p95_m``, ``roots_off_map``, ``hairline_tilt_deg`` (applied, 0 with
    ``hairline`` False) / ``hairline_tilt_needed_deg`` / ``hairline_y`` [before, after, target], ``unit``,
    ``n_in`` / ``k_in`` / ``n`` / ``k``, ``length_m_p5_50_95``, ``head_pts_inside_before``, ``head_midpoint_pushes``,
    ``t_s``. ValueError for an empty strand set."""
    from scipy.spatial import cKDTree
    from app.core import garment_fit as gf
    from app.core import garment_hairdeck as gh
    t0 = time.time()
    B = frame if frame is not None else body_frame(body)
    S = np.asarray(strands, np.float64)
    if S.ndim != 3 or S.shape[2] != 3 or S.shape[1] < 2 or not len(S):
        raise ValueError(f"register: strands of shape {S.shape}")
    n_in, k_in = S.shape[:2]
    ext = float(np.ptp(S[:, 0], axis=0).max())
    unit = 1.0 if ext < 3 else (0.01 if ext < 300 else 0.001)
    S = S * unit
    T = largest_component(np.asarray(template_head, np.float64) * unit, template_faces)
    L_raw = np.linalg.norm(np.diff(S, axis=1), axis=2).sum(1)
    S = S[L_raw > MIN_LENGTH_M]
    if not len(S):
        raise ValueError("register: every strand has no length")
    if len(S) > n_strands:
        rng = np.random.default_rng(seed)
        S = S[np.sort(rng.choice(len(S), n_strands, replace=False))]
    s, R, t, s_init, d = icp_template(T, B)
    X = s * S @ R.T + t
    tilt, hl0, target = _hairline_tilt(X, B)
    if hairline and tilt:
        X = _pitch(X, B["hc"], tilt)
    hl1 = _hairline_y(X[:, 0], B)
    roots_resid = cKDTree(scalp_target(B)).query(X[:, 0])[0]
    # root snap: onto the radial skin + ROOT_LIFT_M, the whole strand moves with its root
    r, dr, Rr = _radial(B, X[:, 0])
    ok = Rr > 0
    delta = np.where(ok[:, None], dr * (Rr + ROOT_LIFT_M - r)[:, None], 0.0)
    X = X + delta[:, None, :]
    Xr, L = resample(X, int(n_points))
    k = Xr.shape[1]
    sdf = B["sdf"]
    d0 = np.asarray(sdf.sample(Xr.reshape(-1, 3))).reshape(Xr.shape[:2])
    head = (Xr[:, :, 1] > B["ear"]) & (np.arange(k)[None] > 0)
    Xh = Xr.copy()
    if head.any():
        Xh[head] = Xr[head] + gh.layer_push(Xr[head], sdf, clear=HEAD_CLEAR_M, band=HEAD_BAND_M)
    # a head segment whose midpoint stays within MID_MIN_M of the skull cuts an ear rim: both ends take the
    # midpoint's push (a point shared by two pushed segments the larger one); the root stays on the scalp
    mid_fixed = 0
    for _ in range(MID_PASSES):
        segh = head[:, :-1] & head[:, 1:]
        M = 0.5 * (Xh[:, 1:] + Xh[:, :-1])
        dm = np.full(segh.shape, np.inf)
        if segh.any():
            dm[segh] = sdf.sample(M[segh])
        bad = dm < MID_MIN_M
        if not bad.any():
            break
        mid_fixed += int(bad.sum())
        g = gf._unit(sdf.grad(M[bad]))
        disp = np.zeros_like(M)
        disp[bad] = (HEAD_CLEAR_M - dm[bad])[:, None] * g
        D = np.zeros_like(Xh)
        for off in (0, 1):
            sl = slice(off, off + disp.shape[1])
            cur = D[:, sl]
            take = np.linalg.norm(disp, axis=2) > np.linalg.norm(cur, axis=2)
            cur[take] = disp[take]
        D[:, 0] = 0.0
        Xh = Xh + D
    yaw = math.degrees(math.atan2(R[0, 2], R[2, 2]))
    pitch = math.degrees(math.asin(float(np.clip(-R[1, 2], -1, 1))))

    def r5(v):
        return None if v is None or not math.isfinite(v) else round(float(v), 5)
    info = {
        "unit": unit, "n_in": int(n_in), "k_in": int(k_in), "n": int(len(Xh)), "k": int(k),
        "scale": round(s, 5), "scale_init": round(s_init, 5), "pitch_deg": round(pitch, 2), "yaw_deg": round(yaw, 2),
        "icp_resid_median_m": round(float(np.median(d)), 5), "icp_resid_p95_m": round(float(np.percentile(d, 95)), 5),
        "root_resid_p50_m": round(float(np.median(roots_resid)), 5),
        "root_resid_p95_m": round(float(np.percentile(roots_resid, 95)), 5),
        "root_snap_p95_m": round(float(np.percentile(np.linalg.norm(delta, axis=1), 95)), 5),
        "roots_off_map": int((~ok).sum()),
        "hairline_tilt_deg": round(float(tilt), 3) if hairline else 0.0,
        "hairline_tilt_needed_deg": round(float(tilt), 3),
        "hairline_y": [r5(hl0), r5(hl1), r5(target)],
        "landmarks": B["landmark_source"],
        "length_m_p5_50_95": [round(float(v), 4) for v in np.percentile(L, [5, 50, 95])],
        "head_pts_inside_before": round(float((d0[head] < 0).mean()), 4) if head.any() else 0.0,
        "head_midpoint_pushes": mid_fixed,
        "t_s": round(time.time() - t0, 2),
    }
    return Xh, info


__all__ = ["N_STRANDS", "N_POINTS", "body_frame", "radial_map", "scalp_target", "umeyama", "largest_component",
           "icp_template", "resample", "register"]
