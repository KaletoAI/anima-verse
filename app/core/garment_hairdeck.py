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

``fit_hairdeck`` reads no file and no profile: the colour target is decided by the caller (the override, else
``hair_colour_from_image`` on the profile picture — ruling R1).
"""
from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
# Front hairline region: z > head centre z + 0.25 * head depth and |x - head cx| < 0.15 * head width. The plan said
# 0.3 * width (+-5.1 cm on the spike's head): that strip reaches the face-framing strands, whose tips hang at eye
# level (x +-4.5..5.6 cm, y 1.572), and the cap then covered forehead and temples (seen in the render, and 52 cap
# triangles below that hairline). The centre strip (+-2.5 cm) finds the forehead hairline at the parting (1.645).
HAIRLINE_FRONT_DEPTH = 0.25
HAIRLINE_HALF_WIDTH = 0.15
CAP_COLOUR_PERCENTILE = 20
# hair_colour_from_image: skin disk at (box centre x, box top + 0.55 h), radius 0.04 w; skin = dE76 < 20.
SKIN_DISK_Y = 0.55
SKIN_DISK_R = 0.04
SKIN_DELTA_E = 20.0
MATTE_THRESHOLD = 128

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


def _lab(rgb: np.ndarray) -> np.ndarray:
    """CIE Lab (D65) of sRGB values in [0, 1], shape (..., 3)."""
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = srgb_to_linear(rgb) @ m.T / np.array([0.95047, 1.0, 1.08883])
    eps = (6 / 29) ** 3
    f = np.where(xyz > eps, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def hair_colour_from_image(image_path: Path, box: Sequence[float]) -> Tuple[float, float, float]:
    """The hair colour (sRGB, 0..1) of a character image inside ``box = (x0, y0, x1, y1)`` (pixels, HairDeck's
    head+hair box).

    Foreground = the portrait matte (``run_rembg`` with ``PORTRAIT_REMBG_MODEL``, >= 128; an alpha channel, if any,
    must be >= 128 too). Skin reference = median of the disk at ``(box centre x, y0 + 0.55 h)``, radius ``0.04 w``
    (its foreground pixels; all of them if none is foreground). Pixels within dE76 < 20 of it are dropped; the
    median of the rest is returned. ValueError when no foreground or no non-skin pixel is left.
    """
    import io
    from PIL import Image
    from app.models.character import PORTRAIT_REMBG_MODEL, run_rembg
    data = Path(image_path).read_bytes()
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        rgb = np.asarray(im.convert("RGB"), np.float64) / 255.0
        alpha = np.asarray(im.getchannel("A")) if "A" in im.getbands() else None
    h_img, w_img = rgb.shape[:2]
    with Image.open(io.BytesIO(run_rembg(data, PORTRAIT_REMBG_MODEL, only_mask=True))) as mk:
        matte = mk.convert("L")
        if matte.size != (w_img, h_img):
            matte = matte.resize((w_img, h_img), Image.Resampling.BILINEAR)
        fg = np.asarray(matte) >= MATTE_THRESHOLD
    if alpha is not None:
        fg &= alpha >= MATTE_THRESHOLD
    if len(box) != 4 or not all(math.isfinite(float(v)) for v in box):
        raise ValueError(f"The hair box must be four finite numbers, got {box!r}")
    x0, y0, x1, y1 = (float(v) for v in box)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        raise ValueError(f"The hair box is empty: {box!r}")
    yy, xx = np.mgrid[0:h_img, 0:w_img]
    inside = (xx >= x0) & (xx < x1) & (yy >= y0) & (yy < y1)
    pick = inside & fg
    if not pick.any():
        raise ValueError("No foreground pixel inside the hair box")
    cx, cy, r = x0 + w / 2, y0 + SKIN_DISK_Y * h, max(SKIN_DISK_R * w, 1.0)
    disk = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
    skin_px = rgb[disk & fg] if (disk & fg).any() else rgb[disk]
    if len(skin_px) == 0:
        raise ValueError("The skin sample disk lies outside the image")
    skin_lab = _lab(np.median(skin_px, 0))
    px = rgb[pick]
    hair = px[np.linalg.norm(_lab(px) - skin_lab, axis=1) >= SKIN_DELTA_E]
    if len(hair) == 0:
        raise ValueError("No hair-coloured pixel inside the hair box (everything matches the skin)")
    med = np.median(hair, 0)
    return float(med[0]), float(med[1]), float(med[2])


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
    and whose nearest hair vertex is within ``CAP_REACH_M``; offset ``CAP_OFFSET_M`` along the outward vertex normals.
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
            "front_hair_vertices": int(front.sum()), "flipped_faces": int(flip.sum())}
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
