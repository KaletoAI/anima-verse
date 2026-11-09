"""HairDeck hair fit: place a HairDeck hair-card mesh on the rigged base body, push it out of the body, correct its
vertex colours and add a scalp cap — pure numpy/scipy on GLB bytes (plan 2026-11-09-hairdeck-hair, Task 3).

A port of the HairDeck fit spike (``~/claude-out/hairdeck/fit/src/fit.py``, user-approved). HairDeck delivers one
character image as hair cards (node ``hair_cards``, ``COLOR_0`` linear, double-sided) plus a ``head_proxy`` sphere
in the same space (the "with head" result file). Facts the code relies on:

- Proxy and body face the same way (+z, yaw 0) and HairDeck's space is uniform: placement is scale + translation.
- The proxy is matched to the CRANIUM, the part of the head the hair rests on: rigged vertices with Head weight
  > 0.5 above ``chin + 0.6 * (top - chin)``. A skin-weight criterion, so an unskinned stray mesh in the body GLB
  (all weights 0) never enters it.
- Cards are separate pieces: no component is dropped and there is no largest-component gate.
- Everything is in the rigged body's metres (k = 1); the push-out uses the garment-fit SDF and spread constants.

Colour: HairDeck samples its vertex colours from the character image itself; they are used unchanged. The only
correction is a manual override (``colour_target``, sRGB), decided by the caller — ``fit_hairdeck`` reads no file
and no profile. (A plan-time sampler of the hair colour from the profile picture was dropped after the spike
renders: its skin reference landed on the shadowed neck in HairDeck's long-hair box and it turned blond hair pink.)
"""
from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.garment_fit import (MOVED_EPS_M, SDF_MARGIN_M, SPREAD_DEPTH_M, SPREAD_M, VOX_M, FitResult, body_sdf,
                                  chin_height, dense_weights, gate as _gate_against, hair_weights, joint_index,
                                  push_out, vertex_normals, weld)
from app.core.glb_mesh import GarmentMesh, body_arrays, card_arrays

# Clearance of a card from the body surface (the spike's 0.004 m; cards are thin, unlike a generated hair shell).
CARD_CLEAR_M = 0.004
# Cranium = Head-weighted vertices above chin + CRANIUM_FROM * (top - chin).
CRANIUM_FROM = 0.6
ICP_ITERATIONS = 30
# Neighbours of the PCA normals the point-to-plane ICP measures along.
PCA_NORMAL_K = 12
# Scalp cap: body triangles within CAP_REACH_M of a hair vertex, offset CAP_OFFSET_M along the outward normal.
CAP_OFFSET_M = 0.0015
CAP_REACH_M = 0.03
# A cap triangle whose centroid lies deeper than this inside the body solid belongs to an inner wall (the generator
# body is double-walled: on the spike's head 43 % of the candidate triangles sat ~4.5 mm inside) and is dropped.
CAP_INNER_DEPTH_M = VOX_M
# Front hairline region: z > head centre z + 0.25 * head depth and |x - head cx| < 0.15 * head width. The plan said
# 0.3 * width (+-5.1 cm on the spike's head): that strip reaches the face-framing strands, whose tips hang at eye
# level (x +-4.5..5.6 cm, y 1.572), and the cap then covered forehead and temples (seen in the render, and 52 cap
# triangles below that hairline). The centre strip (+-2.5 cm) finds the forehead hairline at the parting (1.645).
HAIRLINE_FRONT_DEPTH = 0.25
HAIRLINE_HALF_WIDTH = 0.15
CAP_COLOUR_PERCENTILE = 20

GATES = {
    "max_push_m": ("max", 0.12, "largest push-out"),
    "moved_share": ("max", 0.90, "share of vertices moved by the push-out"),
    "icp_resid_p95_m": ("max", 0.012, "95th percentile of the proxy-to-cranium distance"),
}


def gate(m: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """``(ok, reasons)`` against the HairDeck ``GATES``; a missing or non-finite number refuses."""
    return _gate_against(m, GATES)


# --- colour --------------------------------------------------------------------------------------------------------

def srgb_to_linear(c) -> np.ndarray:
    c = np.asarray(c, np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _correct_colours(C: np.ndarray, colour_target) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Per-channel linear gain mapping the median of ``C`` to the sRGB ``colour_target``, clamped to 1."""
    C = np.asarray(C, np.float64).copy()
    median = np.median(C[:, :3], 0)
    info: Dict[str, Any] = {"median_before_linear": [round(float(v), 4) for v in median]}
    if colour_target is None:
        return C, info
    target = np.asarray(colour_target, np.float64).ravel()
    if target.shape != (3,) or not np.isfinite(target).all() or (target < 0).any() or (target > 1).any():
        raise ValueError(f"The hair colour target must be three sRGB values in 0..1, got {colour_target!r}")
    lin = srgb_to_linear(target)
    gain = lin / np.maximum(median, 1e-6)
    C[:, :3] = np.minimum(C[:, :3] * gain, 1.0)
    info.update({"target_linear": [round(float(v), 4) for v in lin], "gain": [round(float(v), 4) for v in gain],
                 "median_after_linear": [round(float(v), 4) for v in np.median(C[:, :3], 0)]})
    return C, info


# --- placement -----------------------------------------------------------------------------------------------------

def _pca_normals(X: np.ndarray, k: int = PCA_NORMAL_K) -> np.ndarray:
    """Unsigned surface normals of a point set: the least-variance axis of each point's ``k`` nearest neighbours.
    No winding is read (the generator body's is not trusted); point-to-plane residuals are squared, so the sign
    does not matter."""
    from scipy.spatial import cKDTree
    _, nn = cKDTree(X).query(X, k=min(k, len(X)))
    Y = X[nn] - X[nn].mean(1, keepdims=True)
    _, vectors = np.linalg.eigh(np.einsum("nki,nkj->nij", Y, Y))
    return vectors[:, :, 0]


def place_proxy(proxy: np.ndarray, cranium: np.ndarray, *, iterations: int = ICP_ITERATIONS
                ) -> Tuple[float, np.ndarray, Dict[str, Any]]:
    """Scale + translation ``(s, t)`` with ``s * proxy + t`` on the cranium (yaw 0).

    Start: the bounding-box match of the proxy's upper half (vertices above the proxy's bbox centre y) and the
    cranium (s = mean of the three extent ratios, bbox centres aligned). Each ICP iteration pairs every upper-half
    point with its nearest cranium point and every cranium point with its nearest point of the WHOLE proxy (the
    spike's symmetric pairing: the cranium's lower rim may find the proxy's equator), then solves s and t in closed
    form, POINT-TO-PLANE (residual along the partner's normal). Point-to-point, as in the spike, is biased by how
    the two surfaces are sampled: on a sphere sampled 60 x 128 against 61 x 120 it settled 1.8 % large; point-to-
    plane lands within 0.1 % for every sampling tried, and on the spike's real files within 0.2 % of the spike.
    Residual = distance of each mapped upper-half point to its nearest cranium point (the spike's measure).
    """
    from scipy.spatial import cKDTree
    centre = (proxy.min(0) + proxy.max(0)) / 2
    upper = proxy[proxy[:, 1] > centre[1]]
    if len(upper) < PCA_NORMAL_K or len(cranium) < PCA_NORMAL_K:
        raise ValueError("Too few proxy or cranium points to place the hair")
    ext_u, ext_c = np.ptp(upper, 0), np.ptp(cranium, 0)
    if (ext_u <= 0).any():
        raise ValueError("The head proxy is flat")
    s = float(np.mean(ext_c / ext_u))
    t = (cranium.min(0) + cranium.max(0)) / 2 - s * (upper.min(0) + upper.max(0)) / 2
    s0, t0 = s, t.copy()
    n_cranium, n_proxy = _pca_normals(cranium), _pca_normals(proxy)
    tree_c = cKDTree(cranium)
    for _ in range(iterations):
        _, j = tree_c.query(s * upper + t)
        _, k = cKDTree(s * proxy + t).query(cranium)
        A = np.concatenate([upper, proxy[k]])
        B = np.concatenate([cranium[j], cranium])
        N = np.concatenate([n_cranium[j], n_proxy[k]])
        # residual n . (s A + t - B), linear in (s, tx, ty, tz)
        x = np.linalg.lstsq(np.column_stack([(N * A).sum(1), N]), (N * B).sum(1), rcond=None)[0]
        s, t = float(x[0]), x[1:]
    if not (s > 0 and math.isfinite(s)):
        raise ValueError("Could not place the hair on the head (degenerate scale)")
    resid, _ = tree_c.query(s * upper + t)
    info = {"scale_init": round(s0, 4), "translation_init": [round(float(v), 5) for v in t0],
            "scale": round(s, 5), "translation": [float(v) for v in t], "iterations": iterations,
            "proxy_centre": [round(float(v), 5) for v in centre],
            "proxy_size": [round(float(v), 5) for v in np.ptp(proxy, 0)],
            "upper_points": int(len(upper)), "cranium_points": int(len(cranium)), "resid": resid}
    return s, t, info


# --- scalp cap -----------------------------------------------------------------------------------------------------

def _scalp_cap(body, head_w: np.ndarray, hair_X: np.ndarray, sdf) -> Tuple[np.ndarray, np.ndarray, np.ndarray,
                                                                           Optional[float], Dict[str, Any]]:
    """``(positions, faces, normals, hairline_y, info)`` of the scalp cap (faces index the returned positions).

    Rigged body triangles whose three vertices carry Head weight > 0.5, whose centroid lies above the front hairline
    and whose nearest hair vertex is within ``CAP_REACH_M``, minus the inner-wall ones (centroid deeper than
    ``CAP_INNER_DEPTH_M`` inside the body SDF); offset ``CAP_OFFSET_M`` along the outward vertex normals.
    The front hairline is the lowest hair vertex with ``z > head cz + 0.25 depth`` and ``|x - head cx| < 0.15 width``
    (head bbox = the Head-weighted vertices). Face normals are oriented by the SDF gradient at the centroid before
    they are accumulated into vertex normals — the generator body's winding is never trusted — and the winding is
    flipped to match, so a cap face looks outward.
    """
    from scipy.spatial import cKDTree
    P, F = body.positions, body.faces
    head_v = head_w > 0.5
    H = P[head_v]
    lo, hi = H.min(0), H.max(0)
    cx, cz = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2
    width, depth = hi[0] - lo[0], hi[2] - lo[2]
    front = ((hair_X[:, 2] > cz + HAIRLINE_FRONT_DEPTH * depth)
             & (np.abs(hair_X[:, 0] - cx) < HAIRLINE_HALF_WIDTH * width))
    empty = (np.zeros((0, 3)), np.zeros((0, 3), np.int64), np.zeros((0, 3)))
    if not front.any():
        return (*empty, None, {"note": "no hair in front of the head: no hairline, no cap"})
    hairline = float(hair_X[front, 1].min())
    centroid = P[F].mean(1)
    near, _ = cKDTree(hair_X).query(centroid, distance_upper_bound=CAP_REACH_M * 1.0001)
    sel = head_v[F].all(1) & (centroid[:, 1] > hairline) & (near <= CAP_REACH_M)
    candidates = int(sel.sum())
    sel[sel] = sdf.sample(centroid[sel]) > -CAP_INNER_DEPTH_M
    if not sel.any():
        return (*empty, hairline, {"note": "no scalp triangle above the hairline near the hair"})
    Fc = F[sel]
    used, Fl = np.unique(Fc, return_inverse=True)
    Fl = Fl.reshape(-1, 3)
    V = P[used]
    fn = np.cross(V[Fl[:, 1]] - V[Fl[:, 0]], V[Fl[:, 2]] - V[Fl[:, 0]])
    flip = (fn * sdf.grad(centroid[sel])).sum(1) < 0
    fn[flip] *= -1
    Fl[flip] = Fl[flip][:, [0, 2, 1]]
    N = np.zeros_like(V)
    for i in range(3):
        np.add.at(N, Fl[:, i], fn)
    length = np.linalg.norm(N, axis=1, keepdims=True)
    grad = sdf.grad(V)
    fallback = grad / np.maximum(np.linalg.norm(grad, axis=1, keepdims=True), 1e-12)
    N = np.where(length > 1e-12, N / np.maximum(length, 1e-12), fallback)
    V = V + CAP_OFFSET_M * N
    info = {"head_centre_xz": [round(float(cx), 5), round(float(cz), 5)],
            "head_width_m": round(float(width), 5), "head_depth_m": round(float(depth), 5),
            "front_hair_vertices": int(front.sum()), "flipped_faces": int(flip.sum()),
            "inner_wall_dropped": candidates - int(sel.sum())}
    return V, Fl, N, hairline, info


# --- the fit -------------------------------------------------------------------------------------------------------

def fit_hairdeck(nohead_glb: bytes, proxy_glb: bytes, rigged_base_glb: bytes, *,
                 colour_target: Optional[Tuple[float, float, float]]) -> FitResult:
    """Fit HairDeck hair onto the rigged base body.

    ``nohead_glb``: the hair (node ``hair_cards``, ``COLOR_0``); ``proxy_glb``: the result file with the
    ``head_proxy`` node (same space); ``colour_target``: sRGB 0..1 the hair's median colour is mapped to, None =
    keep HairDeck's colours. Returns the hair plus scalp cap as ONE garment (rigged bind space, Head -> Spine2
    weights, cap all Head, ``COLOR_0``, double-sided), the metrics and the ``GATES`` verdict.
    """
    from scipy.spatial import cKDTree
    P, F, U, C, material = card_arrays(nohead_glb, node="hair_cards")
    if C is None:
        raise ValueError("The HairDeck hair has no vertex colours (COLOR_0)")
    proxy, _, _, _, _ = card_arrays(proxy_glb, node="head_proxy")
    body = body_arrays(rigged_base_glb)
    if not body.joint_names:
        raise ValueError("The rigged base has no skin")
    F = np.asarray(F, np.int64).reshape(-1, 3)

    # cranium
    head_w = dense_weights(body)[:, joint_index(body, "head")]
    head_v = head_w > 0.5
    chin = chin_height(body)
    top = float(body.positions[head_v, 1].max())
    threshold = chin + CRANIUM_FROM * (top - chin)
    cranium = body.positions[head_v & (body.positions[:, 1] > threshold)]

    s, t, icp = place_proxy(proxy, cranium)
    resid = icp.pop("resid")
    Q = s * np.asarray(P, np.float64) + t

    # push-out on the rigged body
    Pw, Fw, inv = weld(Q, F, U)
    sdf = body_sdf(body.positions, body.faces, vox=VOX_M,
                   bounds=(Pw.min(0) - SDF_MARGIN_M, Pw.max(0) + SDF_MARGIN_M))
    d0 = sdf.sample(Pw)
    Qp, disp = push_out(Pw, Fw, sdf, clear=CARD_CLEAR_M, spread=SPREAD_M, spread_depth=SPREAD_DEPTH_M)
    d1 = sdf.sample(Qp)
    mag = np.linalg.norm(disp, axis=1)
    X = Qp[inv]
    names, J, W = hair_weights(X, body)
    normals = vertex_normals(X, F)

    colours, colour_info = _correct_colours(C, colour_target)

    # scalp cap
    Vc, Fc, Nc, hairline, cap_info = _scalp_cap(body, head_w, Qp, sdf)
    nc = len(Vc)
    cap_colour = np.r_[np.percentile(colours[:, :3], CAP_COLOUR_PERCENTILE, axis=0), 1.0]
    below = int((Vc[Fc].mean(1)[:, 1] < hairline).sum()) if len(Fc) else 0
    Jc = np.zeros((nc, 4), np.int64)
    Jc[:, 1] = 1
    Wc = np.zeros((nc, 4))
    Wc[:, 0] = 1.0

    material = copy.deepcopy(material or {})
    material["doubleSided"] = True
    garment = GarmentMesh(positions=np.vstack([X, Vc]), normals=np.vstack([normals, Nc]),
                          uvs=np.vstack([np.asarray(U, np.float64), np.zeros((nc, 2))]),
                          indices=np.vstack([F, Fc + len(X)]), joints=np.vstack([J, Jc]),
                          weights=np.vstack([W, Wc]), joint_names=names, image=b"", mime="", material=material,
                          colors=np.vstack([colours, np.tile(cap_colour, (nc, 1))]))

    m = {
        "max_push_m": round(float(mag.max()) if len(mag) else 0.0, 4),
        "moved_share": round(float((mag > MOVED_EPS_M).mean()) if len(mag) else 0.0, 4),
        "icp_scale": round(s, 4),
        "icp_resid_median_m": round(float(np.median(resid)), 5),
        "icp_resid_p95_m": round(float(np.percentile(resid, 95)), 5),
        "cap_tris": int(len(Fc)),
        "cap_tris_below_hairline": below,
        "colour_target": [float(v) for v in colour_target] if colour_target is not None else None,
    }
    ok, reasons = gate(m)
    near_hair, _ = cKDTree(Qp).query(cranium)
    report = {
        "cranium": {"chin_y": round(chin, 5), "top_y": round(top, 5), "threshold_y": round(threshold, 5),
                    "points": int(len(cranium))},
        "icp": icp,
        "push": {"clear_m": CARD_CLEAR_M, "welded_vertices": int(len(Pw)), "inside_before": int((d0 < 0).sum()),
                 "closer_than_clear_before": int((d0 < CARD_CLEAR_M).sum()), "inside_after": int((d1 < 0).sum()),
                 "min_clear_after_m": round(float(d1.min()), 5) if len(d1) else None,
                 "p95_push_m": round(float(np.percentile(mag[mag > MOVED_EPS_M], 95)), 4)
                 if (mag > MOVED_EPS_M).any() else 0.0},
        "weights": {"joints": names, "all_head": int((W[:, 0] == 1).sum()),
                    "blended": int(((W[:, 0] < 1) & (W[:, 0] > 0)).sum()), "all_spine2": int((W[:, 0] == 0).sum())},
        "colour": colour_info,
        "cap": dict(cap_info, hairline_y=None if hairline is None else round(hairline, 5),
                    offset_m=CAP_OFFSET_M, colour_linear=[round(float(v), 4) for v in cap_colour[:3]],
                    cranium_without_hair_within_2cm=round(float((near_hair > 0.02).mean()), 4)
                    if len(near_hair) else None),
        "vertices": {"hair": int(len(X)), "cap": int(nc)},
    }
    return FitResult(garment=garment, metrics=m, ok=ok, reasons=reasons, report=report)
