"""Face cleanup of a freshly generated humanoid mesh — BEFORE the face retexture.

Two defects of the image-to-mesh step, both inherited from what the image model paints on the face
(user request 2026-11-09, measured on Kira's base meshes in ``~/claude-out/eye-lashes``):

1. EYES — painted lashes become geometry. The mesher turns the mascara-like lash lines into thin flaps that
   stand proud of the eyelids: an upper flap juts forward like a visor, a lower one hangs down. Measured
   against a smooth lid surface fitted to the orbit around each eye, the dark (lash-painted) vertices stood
   up to 19-25 mm proud (character scale), p90 9-21 mm. The cleanup presses every vertex of the eye region
   that stands proud of that fitted lid surface back toward it — a soft, monotonic compression along the lid
   normal, never outward, never anything that lies below the surface (the eye opening, the inner wall of the
   double-walled shell). Topology, UVs, normals and the texture stay byte-identical — the stored normals shade
   a pressed flap smoothly, normals recomputed on these double-walled shells (any orientation rule) facet the
   whole orbit; verified on textured renders.

2. MOUTH — crimson lips in the raw texture. The mesher paints the mouth far more saturated than every input
   image (lips/skin HSV saturation ratio 1.64 against 1.17-1.24 in the photos and renders). The face retexture
   fixes it when it runs; a model whose face retexture fails or is skipped keeps the red mouth. The cleanup pulls
   the lip texels toward a natural lip colour derived from the SURROUNDING SKIN of the same texture (saturation
   ``LIP_SATURATION_RATIO`` times the skin's, luminance ``LIP_LUMINANCE_RATIO`` of the skin's, a fixed natural
   lip chroma direction) under a soft-edged mask; the texture detail inside the lips is kept at reduced
   contrast. UVs and geometry are untouched; only the base-colour image bytes change.

Where in the chain: ``model3d._store_unrigged_model`` runs ``clean_face`` on the validated mesher result before
it is published as ``unrigged/<signature>.glb`` — the file the face retexture is frozen from, the rig reads and
every re-rig / standalone face retexture starts over from. The hub projects onto exactly these positions and
this texture (its result must match the input geometry byte for byte, ``face_retexture.bake_face_texture``), so
the corrected mesh is what every later stage sees, with or without a face retexture.

How the regions are found (no landmark model, no hub): the EYES by the lash paint itself — near-black texels
(luminance < ``DARK_LUMINANCE``) sampled at the vertices of the head's front half (top 15 % of the figure, the
side of the head centre where the paint is found) in the eye band (45-70 % of the head segment), one cluster
per side of the head's mid-plane, gated for size, symmetry and height (``_locate_eyes``). The MOUTH from the
eyes: saturated red texels in the window 0.6-1.4 interpupillary distances below the eye line
(``_locate_mouth``). A face without the paint has nothing to correct: the step records ``skipped`` with the
reason and leaves the bytes alone.

Scale: a generator mesh carries no unit. Every threshold is given in millimetres of a 1.70 m figure (the
reference height the normalize step scales to) and converted through the mesh's own height, so it is
proportional to the figure, never to the file's unit.

Numbers gate (``smoke_face_cleanup.py``, hand-derived on a synthetic head): after the cleanup no vertex of an
eye region stands more than ``EYE_LIMIT_MM`` (2.0 mm) proud of the fitted lid — the thickness of a natural lid
margin, a ridge of that height reads as the lid edge, not as a flap; the lips/skin saturation ratio ends at
most ``LIP_RATIO_LIMIT`` (1.3) when the mouth was corrected.
"""
from __future__ import annotations

import io
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.timeutils import utc_now_iso

VERSION = 1
REFERENCE_HEIGHT_MM = 1700.0

# Eyes.
DARK_LUMINANCE = 0.25           # a lash-painted texel (linear-ish sRGB luminance of the 8-bit colour)
HEAD_SHARE = 0.15               # the head segment: the top 15 % of the figure's height
EYE_BAND = (0.45, 0.70)         # the eye line within the head segment
EYE_MIN_VERTICES = 30
EYE_HALF_WIDTH_MM = (8.0, 32.0)
EYE_SEPARATION_MM = (35.0, 90.0)
EYE_SYMMETRY_MM = 10.0          # |(xL - mid) + (xR - mid)|
EYE_LEVEL_MM = 8.0              # |yL - yR|
EYE_Y_TRIM_MM = 12.0            # paint farther than this from the eye line (brows, nostrils) is not the eye
EYE_REGION_MARGIN_MM = 10.0     # region ellipse: a = half_width + margin (the fade zone starts at 0.71 a, past the paint)
EYE_REGION_ASPECT = 0.7         # region ellipse: b = aspect * half_width + margin
EYE_DEPTH_WINDOW_MM = 25.0
EYE_RING_OUTER = 1.8            # d^2 of the region ellipse where the lid-fit ring ends (it starts at 1.0)
FIT_MIN_POINTS = 40
RAY_START_MM = 60.0             # rays toward the head start this far in front of the lid plane
OUTER_TOLERANCE_MM = 1.0        # a vertex this close under the first surface a ray meets is on the outer shell
EYE_FREE_MM = 0.5               # lash-painted vertices proud of the fit up to this: untouched
EYE_LIMIT_MM = 2.0              # lash-painted vertices proud of the fit after the cleanup: never more than this
EYE_SLOPE = 0.06                # compression slope just above EYE_FREE_MM
SKIN_FREE_MM = 2.0              # skin of the eye region (lids, the brow's foot): a natural lid bulge stays ...
SKIN_LIMIT_MM = 4.0             # ... only what stands taller than a lid is pressed, to at most this
SKIN_SLOPE = 0.25
EYE_FADE = (0.5, 1.0)           # d^2 of the region ellipse over which the correction fades to nothing (no ledge)
EYE_PASSES = 3                  # refit and press again: a pressed flap no longer shadows the ring the lid is fitted on
SMOOTH_PASSES = 3               # height smoothing of the pressed vertices (the collapsed flap is a crumpled sheet)

# Mouth.
LIP_SATURATION_FACTOR = 1.3     # a lip texel: saturation above this multiple of the skin's ...
LIP_REDNESS_STEP = 25.0         # ... and redness (R - max(G, B), 8-bit) this much above the skin's
LIP_MIN_SATURATION = 0.35
LIP_MIN_VERTICES = 20
LIP_WIDTH_MM = (18.0, 70.0)
MOUTH_WINDOW_IPD = (0.6, 1.4)   # below the eye line, in interpupillary distances
MOUTH_HALF_WIDTH_IPD = 0.6
CHEEK_X_IPD = (0.35, 0.85)      # the skin reference: the cheeks, between the mouth and the eye line
CHEEK_Y_MARGIN_MM = 10.0
LIP_SATURATION_RATIO = 1.15     # target lips/skin saturation (photos and renders: 1.17-1.24; the soft mask lands above it)
LIP_LUMINANCE_RATIO = 0.88      # target lip luminance / skin luminance
LIP_DETAIL_LUMA_GAIN = 0.7      # texture detail inside the lips: luminance kept at this contrast ...
LIP_DETAIL_CHROMA_GAIN = 0.35   # ... colour variation at this (the paint exaggerates both)
LIP_RATIO_LIMIT = 1.3           # the gate
LIP_CHROMA_DIRECTION = np.array([0.78, -0.33, -0.53])   # natural lips: redder, green down most
MASK_FEATHER_PX = 6

_LUMA = np.array([0.2126, 0.7152, 0.0722])


# --- helpers ----------------------------------------------------------------------------------------------------------

def _design(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.stack([np.ones_like(a), a, b, a * a, a * b, b * b], 1)


def _sample(texture: np.ndarray, uvs: np.ndarray) -> np.ndarray:
    """The 8-bit RGB texel under each vertex (nearest; glTF UV rows run top-down like the image)."""
    height, width = texture.shape[:2]
    u = np.clip((uvs[:, 0] * width).astype(int), 0, width - 1)
    v = np.clip((uvs[:, 1] * height).astype(int), 0, height - 1)
    return texture[v, u]


def _saturation(rgb: np.ndarray) -> np.ndarray:
    """HSV saturation of float RGB in [0, 1] (or 8-bit): (max - min) / max, 0 for black."""
    rgb = np.asarray(rgb, np.float64)
    mx = rgb.max(-1)
    mn = rgb.min(-1)
    return np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-9), 0.0)


def _compress(h_mm: np.ndarray, free: float, limit: float, slope: float) -> np.ndarray:
    """Height above the lid fit after the cleanup: identity up to ``free``, then a monotonic compression that
    saturates below ``limit`` (``slope`` at the knee). Monotonic, so a flap's two sides keep their order and
    never cross."""
    span = limit - free
    over = np.maximum(h_mm - free, 0.0)
    return np.where(h_mm <= free, h_mm, free + span * np.tanh(slope * over / span))


def _eye_compress(h_mm: np.ndarray, lash: Optional[np.ndarray] = None) -> np.ndarray:
    """The lash tier (painted vertices and their mesh neighbours) is pressed to EYE_LIMIT_MM, the skin of the
    region only from SKIN_FREE_MM to SKIN_LIMIT_MM; ``lash`` None = everything is lash."""
    pressed = _compress(h_mm, EYE_FREE_MM, EYE_LIMIT_MM, EYE_SLOPE)
    if lash is None:
        return pressed
    return np.where(lash, pressed, _compress(h_mm, SKIN_FREE_MM, SKIN_LIMIT_MM, SKIN_SLOPE))


# --- eyes -------------------------------------------------------------------------------------------------------------

def _locate_eyes(P: np.ndarray, lum: np.ndarray, mm: float) -> Tuple[Optional[List[Dict[str, Any]]], str, Dict[str, Any]]:
    """The two eye centres from the lash paint. Returns ``(eyes | None, reason, frame)`` with ``frame`` =
    {head (mask), centre, front (+1/-1 along z)}."""
    low, high = P.min(0), P.max(0)
    height = high[1] - low[1]
    head = P[:, 1] > high[1] - HEAD_SHARE * height
    if head.sum() < 200:
        return None, "no head segment", {}
    hp = P[head]
    centre = hp.mean(0)
    hy0, hy1 = hp[:, 1].min(), hp[:, 1].max()
    band = (P[:, 1] > hy0 + EYE_BAND[0] * (hy1 - hy0)) & (P[:, 1] < hy0 + EYE_BAND[1] * (hy1 - hy0))
    dark = (lum < DARK_LUMINANCE) & head & band
    best: Optional[Tuple[int, int]] = None
    for sign in (1, -1):
        count = int((dark & (sign * (P[:, 2] - centre[2]) > 0)).sum())
        if best is None or count > best[1]:
            best = (sign, count)
    front = best[0]
    frame = {"head": head, "centre": centre, "front": front}
    dark &= front * (P[:, 2] - centre[2]) > 0
    eyes: List[Dict[str, Any]] = []
    for side, sel in (("left" if front > 0 else "right", dark & (P[:, 0] > centre[0])),
                      ("right" if front > 0 else "left", dark & (P[:, 0] < centre[0]))):
        pts = P[sel]
        if len(pts) < EYE_MIN_VERTICES:
            return None, f"too little lash paint on the {side} side ({len(pts)} vertices)", frame
        y_med = np.median(pts[:, 1])
        pts = pts[np.abs(pts[:, 1] - y_med) < EYE_Y_TRIM_MM * mm]
        if len(pts) < EYE_MIN_VERTICES:
            return None, f"lash paint on the {side} side does not form an eye line", frame
        c = np.median(pts, 0)
        x3, x97 = np.percentile(pts[:, 0], [3, 97])
        half_width = (x97 - x3) / 2
        if not (EYE_HALF_WIDTH_MM[0] * mm <= half_width <= EYE_HALF_WIDTH_MM[1] * mm):
            return None, f"{side} eye paint {half_width / mm * 2:.0f} mm wide is not an eye", frame
        # The depth of the eye comes from the orbit ring around the paint, never from the paint itself: the
        # flaps ARE the paint, and a measurement after the cleanup must find the same eye.
        a_ = half_width + EYE_REGION_MARGIN_MM * mm
        b_ = EYE_REGION_ASPECT * half_width + EYE_REGION_MARGIN_MM * mm
        d2 = ((P[:, 0] - c[0]) / a_) ** 2 + ((P[:, 1] - c[1]) / b_) ** 2
        footprint = (d2 >= 1.0) & (d2 < EYE_RING_OUTER) & head & (front * (P[:, 2] - centre[2]) > 0) & (lum >= DARK_LUMINANCE)
        if footprint.sum() >= EYE_MIN_VERTICES:
            c = c.copy()
            c[2] = np.percentile(P[footprint, 2], 75)
        eyes.append({"side": side, "centre": c, "half_width": half_width, "vertices": int(len(pts))})
    a, b = eyes
    symmetry = abs((a["centre"][0] - centre[0]) + (b["centre"][0] - centre[0]))
    level = abs(a["centre"][1] - b["centre"][1])
    separation = abs(a["centre"][0] - b["centre"][0])
    if symmetry > EYE_SYMMETRY_MM * mm:
        return None, f"eye paint is not symmetric about the head ({symmetry / mm:.0f} mm)", frame
    if level > EYE_LEVEL_MM * mm:
        return None, f"eye paint is not level ({level / mm:.0f} mm)", frame
    if not (EYE_SEPARATION_MM[0] * mm <= separation <= EYE_SEPARATION_MM[1] * mm):
        return None, f"eye separation {separation / mm:.0f} mm is not a face", frame
    return eyes, "", frame


def _ray_heights(origin: np.ndarray, t1: np.ndarray, t2: np.ndarray, normal: np.ndarray, plane: np.ndarray,
                 P: np.ndarray, F: np.ndarray, start: float) -> np.ndarray:
    """Height (along ``normal``) of the FIRST triangle a ray from ``start`` in front of each plane point meets
    on its way toward the head — the outer surface, whatever is layered behind it. NaN where nothing is hit."""
    origins = origin + np.outer(plane[:, 0], t1) + np.outer(plane[:, 1], t2) + start * normal
    direction = -normal
    v0 = P[F[:, 0]]
    e1, e2 = P[F[:, 1]] - v0, P[F[:, 2]] - v0
    pvec = np.cross(direction, e2)
    det = (e1 * pvec).sum(1)
    valid = np.abs(det) > 1e-18
    inv = np.where(valid, 1.0 / np.where(valid, det, 1.0), 0.0)
    out = np.full(len(origins), np.nan)
    for lo in range(0, len(origins), 64):
        o = origins[lo:lo + 64]
        tvec = o[:, None, :] - v0[None, :, :]                       # (m, k, 3)
        u = (tvec * pvec[None]).sum(2) * inv[None]
        qvec = np.cross(tvec, e1[None])
        v = (qvec @ direction) * inv[None]
        t = (qvec * e2[None]).sum(2) * inv[None]
        hit = valid[None] & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0)
        t = np.where(hit, t, np.inf).min(1)
        out[lo:lo + 64] = np.where(np.isfinite(t), start - t, np.nan)
    return out


class _LidFit:
    """A smooth lid surface around one eye: a quadric height field over the orbit ring around the eye region
    (lash paint excluded), in a frame whose normal points out of the head at the eye. The samples are the
    OUTER surface — the first triangle a ray from outside meets above each ring vertex — never the vertices
    themselves: 60-75 % of the vertices of these shells lie on inner walls behind the surface. Robust trimming
    drops what a flap or a hole leaves in the ring."""

    def __init__(self, P: np.ndarray, F: np.ndarray, ring: np.ndarray, eye: Dict[str, Any], head_centre: np.ndarray,
                 front: int, mm: float):
        c = eye["centre"]
        normal = np.array([0.5 * (c[0] - head_centre[0]), 0.0, front * max(abs(c[2] - head_centre[2]), 1e-6)])
        self.normal = normal / np.linalg.norm(normal)
        t1 = np.cross(np.array([0.0, 1.0, 0.0]), self.normal)
        self.t1 = t1 / np.linalg.norm(t1)
        self.t2 = np.cross(self.normal, self.t1)
        self.origin = c.copy()
        self.faces = F[(np.linalg.norm(P[F[:, 0]] - c, axis=1) < 2 * RAY_START_MM * mm)]
        a, b, _h = self.local(P[ring])
        plane = np.stack([a, b], 1)
        h = _ray_heights(self.origin, self.t1, self.t2, self.normal, plane, P, self.faces, RAY_START_MM * mm)
        good = np.isfinite(h)
        a, b, h = a[good], b[good], h[good]
        keep = np.ones(len(h), bool)
        coef = np.zeros(6)
        mad = 0.0
        for _ in range(6):
            if keep.sum() < FIT_MIN_POINTS:
                break
            coef, *_ = np.linalg.lstsq(_design(a[keep], b[keep]), h[keep], rcond=None)
            r = h - _design(a, b) @ coef
            mad = float(np.median(np.abs(r[keep])) * 1.4826) + 1e-12
            keep = np.abs(r) < 3 * mad
        self.coef = coef
        self.points = int(keep.sum())
        self.mad = mad
        self.ok = self.points >= FIT_MIN_POINTS

    def local(self, Q: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        R = Q - self.origin
        return R @ self.t1, R @ self.t2, R @ self.normal

    def height(self, Q: np.ndarray) -> np.ndarray:
        """Signed height of each point above the fitted lid (along the lid normal)."""
        a, b, h = self.local(Q)
        return h - _design(a, b) @ self.coef

    def outer(self, P: np.ndarray, Q: np.ndarray, mm: float) -> np.ndarray:
        """Which of the points ``Q`` lie on the outer shell (within OUTER_TOLERANCE_MM under the first surface
        a ray from outside meets above them)."""
        a, b, h = self.local(Q)
        surface = _ray_heights(self.origin, self.t1, self.t2, self.normal, np.stack([a, b], 1), P, self.faces,
                               RAY_START_MM * mm)
        return np.isfinite(surface) & (surface - h < OUTER_TOLERANCE_MM * mm)

    def place(self, Q: np.ndarray, h: np.ndarray) -> np.ndarray:
        """``Q`` pressed straight back along the front axis (x and y stay put, so the paint-based locator finds
        the same eye afterwards) until its height above the fit is ``h`` (Newton steps on the tilted
        quadric, the remainder along the normal)."""
        axis = np.array([0.0, 0.0, self.normal[2]])
        axis /= np.linalg.norm(axis)
        rate = float(axis @ self.normal)
        out = Q.copy()
        for _ in range(6):
            out = out - np.outer((self.height(out) - h) / rate, axis)
        # The last few hundredths of a millimetre exactly, along the normal.
        return out - np.outer(self.height(out) - h, self.normal)


def _eye_region(P: np.ndarray, eye: Dict[str, Any], head: np.ndarray, dark: np.ndarray,
                mm: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(region, ring, weight)``: the eye region (the paint plus a margin, what the cleanup may move), the orbit
    ring around it the lid is fitted on (no lash paint) and the correction weight of every vertex (1 inside,
    fading to 0 at the region border so the border never becomes a ledge)."""
    c, hw = eye["centre"], eye["half_width"]
    a = hw + EYE_REGION_MARGIN_MM * mm
    b = EYE_REGION_ASPECT * hw + EYE_REGION_MARGIN_MM * mm
    d2 = ((P[:, 0] - c[0]) / a) ** 2 + ((P[:, 1] - c[1]) / b) ** 2
    depth = np.abs(P[:, 2] - c[2]) < EYE_DEPTH_WINDOW_MM * mm
    region = (d2 < 1.0) & head & depth
    ring = (d2 >= 1.0) & (d2 < EYE_RING_OUTER) & head & depth & ~dark
    t = np.clip((EYE_FADE[1] - d2) / (EYE_FADE[1] - EYE_FADE[0]), 0.0, 1.0)
    weight = t * t * (3 - 2 * t)
    return region, ring, weight


def _adjacency(n: int, F: np.ndarray):
    from scipy.sparse import coo_matrix
    i = np.concatenate([F[:, 0], F[:, 1], F[:, 2], F[:, 1], F[:, 2], F[:, 0]])
    j = np.concatenate([F[:, 1], F[:, 2], F[:, 0], F[:, 0], F[:, 1], F[:, 2]])
    adjacency = coo_matrix((np.ones(len(i)), (i, j)), shape=(n, n)).tocsr()
    adjacency.data[:] = 1.0
    return adjacency


def _clean_eyes(P: np.ndarray, F: np.ndarray, lum: np.ndarray, mm: float) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    """Returns ``(positions, moved mask, record)``; ``positions`` is ``P`` itself when nothing changed."""
    eyes, reason, frame = _locate_eyes(P, lum, mm)
    if eyes is None:
        return P, np.zeros(len(P), bool), {"status": "skipped", "reason": reason, "limit_mm": EYE_LIMIT_MM}
    head, front = frame["head"], frame["front"]
    dark = lum < DARK_LUMINANCE
    out = P.copy()
    moved_all = np.zeros(len(P), bool)
    records = []
    adjacency = None
    for eye in eyes:
        region, ring, weight = _eye_region(P, eye, head, dark, mm)
        record: Dict[str, Any] = {"side": eye["side"], "centre_mm": [round(float(v) / mm, 1) for v in eye["centre"]],
                                  "half_width_mm": round(float(eye["half_width"]) / mm, 1),
                                  "paint_vertices": eye["vertices"], "region_vertices": int(region.sum())}
        idx = np.flatnonzero(region)
        w = weight[idx]
        if adjacency is None:
            adjacency = _adjacency(len(P), F)
        # The lash tier: the painted vertices and their one-ring neighbours (the flap's root and rim).
        lash_all = dark.astype(np.float64)
        lash_all = (lash_all + adjacency @ lash_all) > 0
        lash = lash_all[idx]
        record["lash_vertices"] = int(lash.sum())
        moved_eye = np.zeros(len(idx), bool)
        passes = []
        for n in range(EYE_PASSES):
            fit = _LidFit(out, F, ring, eye, frame["centre"], front, mm)
            if not fit.ok:
                record.update(status="skipped", reason=f"lid fit has only {fit.points} outer points")
                break
            h = fit.height(out[idx]) / mm
            if n == 0:
                outer = fit.outer(out, out[idx], mm)
                record["before_mm"] = {"p90": round(float(np.percentile(h, 90)), 2), "max": round(float(h.max()), 2),
                                       "outer_p90": round(float(np.percentile(h[outer], 90)), 2) if outer.any() else None,
                                       "outer_max": round(float(h[outer].max()), 2) if outer.any() else None,
                                       "lash_outer_p90": round(float(np.percentile(h[outer & lash], 90)), 2) if (outer & lash).any() else None,
                                       "lash_outer_max": round(float(h[outer & lash].max()), 2) if (outer & lash).any() else None}
                record["outer_vertices"] = int(outer.sum())
            target = h - w * (h - _eye_compress(h, lash))
            move = target < h - 1e-6
            passes.append({"fit_points": fit.points, "fit_mad_mm": round(fit.mad / mm, 2),
                           "max_mm": round(float(h.max()), 2), "moved": int(move.sum())})
            if not move.any():
                break
            out[idx[move]] = fit.place(out[idx[move]], target[move] * mm)
            moved_eye |= move
            after = fit.height(out[idx]) / mm
            record["after_mm"] = {"p90": round(float(np.percentile(after, 90)), 2), "max": round(float(after.max()), 2),
                                  "weighted_max": round(float((after * w).max()), 2)}
        if record.get("status") == "skipped":
            records.append(record)
            continue
        if moved_eye.any():
            # The collapsed flap is a crumpled sheet of interleaved layers: smooth its HEIGHT over the mesh
            # neighbours (x and y stay put), never above the pressed target, then set the record's numbers.
            local = adjacency[idx][:, idx]
            degree = np.maximum(np.asarray(local.sum(1)).reshape(-1), 1.0)
            h = fit.height(out[idx]) / mm
            cap = h.copy()
            for _ in range(SMOOTH_PASSES):
                mean = (local @ h) / degree
                h = np.where(moved_eye, np.minimum(0.5 * h + 0.5 * mean, cap), h)
            out[idx[moved_eye]] = out[idx[moved_eye]] - np.outer((fit.height(out[idx[moved_eye]]) / mm - h[moved_eye]) * mm, fit.normal)
            after = fit.height(out[idx]) / mm
            record["after_mm"] = {"p90": round(float(np.percentile(after, 90)), 2), "max": round(float(after.max()), 2),
                                  "weighted_max": round(float((after * w).max()), 2),
                                  "lash_weighted_max": round(float((after * w)[lash].max()), 2) if lash.any() else None}
        record.update(status="applied", moved_vertices=int(moved_eye.sum()), passes=passes)
        record.setdefault("after_mm", record.get("before_mm"))
        moved_all[idx[moved_eye]] = True
        records.append(record)
    applied = [r for r in records if r.get("status") == "applied"]
    status = "applied" if applied else "skipped"
    record = {"status": status, "limit_mm": EYE_LIMIT_MM, "front_axis": "+z" if front > 0 else "-z",
              "eyes": records}
    if status == "skipped":
        record["reason"] = "; ".join(r.get("reason", "") for r in records if r.get("reason"))
    return (out if moved_all.any() else P), moved_all, record


# --- mouth ------------------------------------------------------------------------------------------------------------

def _lip_like(rgb: np.ndarray, skin_sat: float, skin_red: float) -> np.ndarray:
    """Texels/vertices painted as lips: clearly more saturated and redder than the skin they sit in."""
    rgb = np.asarray(rgb, np.float64)
    sat = _saturation(rgb)
    redness = rgb[..., 0] - np.maximum(rgb[..., 1], rgb[..., 2])
    return (sat > max(LIP_MIN_SATURATION, skin_sat * LIP_SATURATION_FACTOR)) & (redness > skin_red + LIP_REDNESS_STEP)


def _locate_mouth(P: np.ndarray, colours: np.ndarray, eyes: List[Dict[str, Any]], frame: Dict[str, Any],
                  mm: float) -> Tuple[Optional[Dict[str, Any]], str]:
    """The mouth from the eyes: paint clearly more saturated and redder than the CHEEKS in the window below the
    eye line. Returns the centre, the ellipse half-axes and the cheek skin colour (sampled on the MESH between
    the mouth and the eye line, so UV islands and the reddish zone around the lips do not matter)."""
    a, b = eyes
    mid_x = (a["centre"][0] + b["centre"][0]) / 2
    eye_y = (a["centre"][1] + b["centre"][1]) / 2
    ipd = abs(a["centre"][0] - b["centre"][0])
    centre, front = frame["centre"], frame["front"]
    rgb = colours.astype(np.float64)
    sat = _saturation(rgb)
    redness = rgb[:, 0] - np.maximum(rgb[:, 1], rgb[:, 2])
    facing = frame["head"] & (front * (P[:, 2] - centre[2]) > 0)
    window = (facing & (P[:, 1] < eye_y - MOUTH_WINDOW_IPD[0] * ipd) & (P[:, 1] > eye_y - MOUTH_WINDOW_IPD[1] * ipd)
              & (np.abs(P[:, 0] - mid_x) < MOUTH_HALF_WIDTH_IPD * ipd))
    if window.sum() < 50:
        return None, "no mesh below the eyes"
    side = np.abs(P[:, 0] - mid_x)
    cheeks = (facing & (side > CHEEK_X_IPD[0] * ipd) & (side < CHEEK_X_IPD[1] * ipd)
              & (P[:, 1] < eye_y - CHEEK_Y_MARGIN_MM * mm) & (P[:, 1] > eye_y - MOUTH_WINDOW_IPD[1] * ipd + CHEEK_Y_MARGIN_MM * mm)
              & (rgb.max(1) > 40))
    if cheeks.sum() < 30:
        return None, "no cheek skin to compare the lips with"
    skin_sat = float(np.median(sat[cheeks]))
    skin_red = float(np.median(redness[cheeks]))
    lips = window & _lip_like(rgb, skin_sat, skin_red)
    if lips.sum() < LIP_MIN_VERTICES:
        return None, f"the lips are not more saturated than the cheeks ({int(lips.sum())} vertices) — nothing to neutralise"
    pts = P[lips]
    c = np.median(pts, 0)
    x3, x97 = np.percentile(pts[:, 0], [3, 97])
    y3, y97 = np.percentile(pts[:, 1], [3, 97])
    width = x97 - x3
    if not (LIP_WIDTH_MM[0] * mm <= width <= LIP_WIDTH_MM[1] * mm):
        return None, f"lip paint {width / mm:.0f} mm wide is not a mouth"
    return {"centre": c, "half_width": width / 2, "half_height": max((y97 - y3) / 2, 3 * mm), "vertices": int(lips.sum()),
            "skin_rgb": np.median(rgb[cheeks], 0), "skin_sat": skin_sat, "skin_red": skin_red,
            "skin_vertices": int(cheeks.sum())}, ""


def _triangle_mask(uvs: np.ndarray, faces: np.ndarray, width: int, height: int) -> np.ndarray:
    from PIL import Image, ImageDraw
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    for tri in faces:
        draw.polygon([(float(uvs[i, 0]) * width, float(uvs[i, 1]) * height) for i in tri], fill=255)
    return np.asarray(mask) > 0


def _blur(mask: np.ndarray, radius: int) -> np.ndarray:
    from PIL import Image, ImageFilter
    image = Image.fromarray((np.asarray(mask, np.float64) * 255).astype(np.uint8))
    return np.asarray(image.filter(ImageFilter.GaussianBlur(radius))).astype(np.float64) / 255


def _natural_lip(skin: np.ndarray, skin_sat: float) -> np.ndarray:
    """The target mean lip colour (8-bit RGB) for a skin colour: luminance LIP_LUMINANCE_RATIO of the skin's,
    saturation LIP_SATURATION_RATIO times the skin's, chroma along LIP_CHROMA_DIRECTION."""
    luminance = float(skin @ _LUMA) * LIP_LUMINANCE_RATIO
    target_sat = min(skin_sat * LIP_SATURATION_RATIO, 0.9)
    d = LIP_CHROMA_DIRECTION - LIP_CHROMA_DIRECTION @ _LUMA   # zero-luminance chroma
    # colour = L + k d; saturation = k (dmax - dmin) / (L + k dmax)
    dmax, dmin = d.max(), d.min()
    k = target_sat * luminance / max((dmax - dmin) - target_sat * dmax, 1e-6)
    return np.clip(luminance + k * d, 0, 255)


def _mouth_stats(rgb: np.ndarray, area: np.ndarray, mouth: Dict[str, Any]) -> Tuple[np.ndarray, Dict[str, Any]]:
    """``(lip texel mask, numbers)`` of the mouth area of a texture: the lips/skin saturation ratio over the
    lip-like texels and — comparable with the hand measurement on renders — over the reddest 30 % of the area."""
    sat = _saturation(rgb)
    redness = rgb[..., 0] - np.maximum(rgb[..., 1], rgb[..., 2])
    lips = area & _lip_like(rgb, mouth["skin_sat"], mouth["skin_red"])
    reddest = area & (redness >= np.percentile(redness[area], 70))
    skin_sat = max(mouth["skin_sat"], 1e-6)
    return lips, {"lip_texels": int(lips.sum()),
                  "ratio": round(float(np.mean(sat[lips])) / skin_sat, 2) if lips.any() else None,
                  "ratio_reddest30": round(float(np.mean(sat[reddest])) / skin_sat, 2),
                  "lip_rgb": [int(v) for v in rgb[lips].mean(0)] if lips.any() else None}


def _neutralise_mouth(texture: np.ndarray, U: np.ndarray, F: np.ndarray, P: np.ndarray, mouth: Dict[str, Any],
                      mm: float) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
    """Pull the lip texels toward the natural lip colour of the surrounding skin. Returns ``(texture | None,
    record)``; None when the mouth is already natural."""
    height, width = texture.shape[:2]
    c = mouth["centre"]
    a = mouth["half_width"] + 3 * mm
    b = mouth["half_height"] + 3 * mm
    d2 = ((P[:, 0] - c[0]) / a) ** 2 + ((P[:, 1] - c[1]) / b) ** 2
    inside = (d2 < 1.0) & (np.abs(P[:, 2] - c[2]) < 20 * mm)
    faces = F[inside[F].all(1)]
    if not len(faces):
        return None, {"status": "skipped", "reason": "mouth region has no triangles"}
    area = _triangle_mask(U, faces, width, height)
    rgb = texture[..., :3].astype(np.float64)
    lips_sel, before = _mouth_stats(rgb, area, mouth)
    record: Dict[str, Any] = {"centre_mm": [round(float(v) / mm, 1) for v in c], "paint_vertices": mouth["vertices"],
                              "area_texels": int(area.sum()), "lip_texels": before["lip_texels"],
                              "skin_rgb": [int(v) for v in mouth["skin_rgb"]], "skin_sat": round(mouth["skin_sat"], 3),
                              "lip_rgb_before": before["lip_rgb"], "ratio_before": before["ratio"],
                              "ratio_reddest30_before": before["ratio_reddest30"],
                              "target_ratio": LIP_SATURATION_RATIO, "limit": LIP_RATIO_LIMIT}
    if before["lip_texels"] < 50 or before["ratio"] is None:
        record.update(status="skipped", reason="no saturated lip texels inside the mouth region")
        return None, record
    if before["ratio"] <= LIP_RATIO_LIMIT:
        record.update(status="skipped", reason=f"lips/skin saturation {before['ratio']:.2f} is already natural",
                      ratio_after=before["ratio"], ratio_reddest30_after=before["ratio_reddest30"])
        return None, record
    target = _natural_lip(mouth["skin_rgb"], mouth["skin_sat"])
    target_sat = mouth["skin_sat"] * LIP_SATURATION_RATIO
    lip_mean = rgb[lips_sel].mean(0)
    # Soft mask: the feathered mouth area, weighted by how far a texel's saturation exceeds the target.
    sat = _saturation(rgb)
    excess = np.clip((sat - target_sat) / 0.03, 0.0, 1.0)
    weight = np.clip(2.0 * _blur(area, MASK_FEATHER_PX), 0.0, 1.0) * excess
    detail = rgb - lip_mean
    detail_luma = detail @ _LUMA
    pulled = target + detail_luma[..., None] * LIP_DETAIL_LUMA_GAIN + (detail - detail_luma[..., None]) * LIP_DETAIL_CHROMA_GAIN
    # Cap every pulled texel at the target saturation around its own luminance: the mean lands at or under the
    # target ratio, the luminance detail stays untouched.
    pulled = np.clip(pulled, 0, 255)
    pulled_luma = (pulled @ _LUMA)[..., None]
    pulled_sat = _saturation(pulled)
    scale = np.where(pulled_sat > target_sat, target_sat / np.maximum(pulled_sat, 1e-6), 1.0)[..., None]
    pulled = pulled_luma + (pulled - pulled_luma) * scale
    out = np.clip(rgb + (pulled - rgb) * weight[..., None], 0, 255)
    result = texture.copy()
    result[..., :3] = np.round(out).astype(np.uint8)
    _lips_after, after = _mouth_stats(np.round(out), area, mouth)
    # The gate is read on the SAME texels the before number used.
    sat_after = _saturation(np.round(out))
    record.update(status="applied", lip_rgb_after=[int(v) for v in out[lips_sel].mean(0)],
                  ratio_after=round(float(np.mean(sat_after[lips_sel])) / max(mouth["skin_sat"], 1e-6), 2),
                  ratio_reddest30_after=after["ratio_reddest30"], changed_texels=int((weight > 0.01).sum()))
    return result, record


# --- GLB IO -----------------------------------------------------------------------------------------------------------

def _body(parsed: dict) -> Tuple[List[dict], np.ndarray, np.ndarray, np.ndarray, Optional[np.ndarray], List[int]]:
    """``(primitives, P, F, U, N | None, vertex offsets)`` of the body primitives, concatenated."""
    from app.core.face_retexture import _body_primitives
    from app.core.glb_mesh import accessor_array, _triangles, _vertex_attr
    primitives = _body_primitives(parsed)
    if not primitives:
        raise ValueError("The GLB has no body primitive")
    P, F, U, N, offsets, base = [], [], [], [], [], 0
    for prim in primitives:
        pos = np.asarray(accessor_array(parsed, prim["attributes"]["POSITION"]), np.float64)
        n = len(pos)
        offsets.append(base)
        P.append(pos)
        F.append(_triangles(parsed, prim, n) + base)
        U.append(_vertex_attr(parsed, prim, "TEXCOORD_0", n, 2, np.float64))
        N.append(_vertex_attr(parsed, prim, "NORMAL", n, 3, np.float64) if "NORMAL" in prim["attributes"] else None)
        base += n
    normals = np.concatenate(N) if all(x is not None for x in N) else None
    return primitives, np.concatenate(P), np.concatenate(F), np.concatenate(U), normals, offsets


def _float_view(parsed: dict, binary: bytearray, index: int, components: int) -> np.ndarray:
    """A writable float32 view of accessor ``index`` inside ``binary`` (the file's layout, stride included)."""
    gltf = parsed["gltf"]
    accessor = gltf["accessors"][index]
    if accessor.get("componentType") != 5126 or accessor.get("sparse") is not None:
        raise ValueError("Only float32 vertex attributes can be rewritten")
    view = gltf["bufferViews"][accessor["bufferView"]]
    width = 4 * components
    stride = int(view.get("byteStride", width))
    start = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    count = int(accessor["count"])
    if stride < width or start + (count - 1) * stride + width > len(binary):
        raise ValueError("Vertex attribute accessor is truncated")
    return np.ndarray((count, components), dtype="<f4", buffer=binary, offset=start, strides=(stride, 4))


def _write_vertices(parsed: dict, binary: bytearray, primitives: List[dict], offsets: List[int],
                    attribute: str, values: np.ndarray, bounds: bool) -> None:
    for prim, base in zip(primitives, offsets):
        index = prim["attributes"].get(attribute)
        if index is None:
            continue
        accessor = parsed["gltf"]["accessors"][index]
        count = int(accessor["count"])
        chunk = values[base:base + count].astype(np.float32)
        _float_view(parsed, binary, index, chunk.shape[1])[:] = chunk
        if bounds:
            accessor["min"] = [float(v) for v in chunk.min(0)]
            accessor["max"] = [float(v) for v in chunk.max(0)]


def _texture(parsed: dict, primitive: dict) -> Tuple[int, np.ndarray, str]:
    """``(image index, HxWx3|4 uint8 array, mime)`` of the primitive's base colour."""
    from PIL import Image
    from app.core.face_retexture import _primitive_basecolor
    from app.core.model_validate import texture_image_index
    gltf = parsed["gltf"]
    material = gltf["materials"][primitive["material"]]
    texture = gltf["textures"][material["pbrMetallicRoughness"]["baseColorTexture"]["index"]]
    image_index = texture_image_index(gltf, texture)
    image, raw = _primitive_basecolor(parsed, primitive)
    decoded = Image.open(io.BytesIO(raw))
    decoded.load()
    mode = "RGBA" if decoded.mode in ("RGBA", "LA", "P") and "A" in decoded.getbands() or decoded.mode == "RGBA" else "RGB"
    return image_index, np.asarray(decoded.convert(mode)), image.get("mimeType") or ("image/webp" if decoded.format == "WEBP" else "image/png")


def _encode(texture: np.ndarray, mime: str) -> bytes:
    from PIL import Image
    out = io.BytesIO()
    image = Image.fromarray(texture)
    if mime == "image/webp":
        image.save(out, "WEBP", lossless=True)
    elif mime == "image/jpeg":
        image.convert("RGB").save(out, "JPEG", quality=95)
    else:
        image.save(out, "PNG")
    return out.getvalue()


def _replace_image(parsed: dict, binary: bytearray, image_index: int, payload: bytes) -> bytearray:
    """A new BIN with the image's bufferView replaced by ``payload``; every later view keeps its order and
    moves by the size difference (4-byte aligned), offsets in the JSON are updated in place."""
    gltf = parsed["gltf"]
    image = gltf["images"][image_index]
    target = int(image["bufferView"])
    views = gltf["bufferViews"]
    order = sorted(range(len(views)), key=lambda i: int(views[i].get("byteOffset", 0)))
    out = bytearray()
    for i in order:
        view = views[i]
        start = int(view.get("byteOffset", 0))
        length = int(view["byteLength"])
        data = payload if i == target else bytes(binary[start:start + length])
        out += b"\0" * (-len(out) % 4)
        view["byteOffset"] = len(out)
        view["byteLength"] = len(data)
        out += data
    out += b"\0" * (-len(out) % 4)
    gltf["buffers"][0]["byteLength"] = len(out)
    return out


# --- entry points -----------------------------------------------------------------------------------------------------

def clean_face(glb: bytes) -> Tuple[bytes, Dict[str, Any]]:
    """The cleanup of one unrigged humanoid mesh. Returns ``(bytes, record)`` — the input bytes themselves
    when nothing was changed. Raises ValueError for a mesh it cannot read; the caller decides what a failure
    means (``model3d._store_unrigged_model`` records it and keeps the mesher's file)."""
    from app.core.glb_mesh import pack_glb, _parse
    parsed = _parse(glb, "Source")
    primitives, P, F, U, N, offsets = _body(parsed)
    low, high = P.min(0), P.max(0)
    mm = (high[1] - low[1]) / REFERENCE_HEIGHT_MM
    if mm <= 0:
        raise ValueError("The mesh has no height")
    image_index, texture, mime = _texture(parsed, primitives[0])
    colours = _sample(texture[..., :3], U)
    lum = (colours.astype(np.float64) @ _LUMA) / 255.0
    record: Dict[str, Any] = {"status": "skipped", "version": VERSION, "at": utc_now_iso(),
                              "mm_per_unit": round(1.0 / mm, 1)}
    new_P, moved, eye_record = _clean_eyes(P, F, lum, mm)
    record["eyes"] = eye_record
    eyes, reason, frame = _locate_eyes(P, lum, mm)
    if eyes is None:
        record["mouth"] = {"status": "skipped", "reason": "eyes not found: " + reason}
        new_texture = None
    else:
        mouth, reason = _locate_mouth(P, colours, eyes, frame, mm)
        if mouth is None:
            record["mouth"] = {"status": "skipped", "reason": reason}
            new_texture = None
        else:
            new_texture, mouth_record = _neutralise_mouth(texture, U, F, P, mouth, mm)
            record["mouth"] = mouth_record
    changed = moved.any() or new_texture is not None
    if not changed:
        return glb, record
    binary = bytearray(parsed["bin"])
    if moved.any():
        _write_vertices(parsed, binary, primitives, offsets, "POSITION", new_P, bounds=True)
    if new_texture is not None:
        binary = _replace_image(parsed, binary, image_index, _encode(new_texture, mime))
    record["status"] = "applied"
    return pack_glb(parsed["gltf"], bytes(binary)), record


def measure_face(glb: bytes) -> Dict[str, Any]:
    """The measurement alone (eye protrusion against the fitted lids, lips/skin saturation), nothing
    changed — the smoke and the report run it on a file before and after ``clean_face``."""
    from app.core.glb_mesh import _parse
    parsed = _parse(glb, "Source")
    primitives, P, F, U, N, offsets = _body(parsed)
    low, high = P.min(0), P.max(0)
    mm = (high[1] - low[1]) / REFERENCE_HEIGHT_MM
    _index, texture, _mime = _texture(parsed, primitives[0])
    colours = _sample(texture[..., :3], U)
    lum = (colours.astype(np.float64) @ _LUMA) / 255.0
    eyes, reason, frame = _locate_eyes(P, lum, mm)
    out: Dict[str, Any] = {"mm_per_unit": round(1.0 / mm, 1), "vertices": int(len(P)), "triangles": int(len(F))}
    if eyes is None:
        out["eyes"] = {"status": "skipped", "reason": reason}
        return out
    rows = []
    for eye in eyes:
        dark = lum < DARK_LUMINANCE
        region, ring, weight = _eye_region(P, eye, frame["head"], dark, mm)
        fit = _LidFit(P, F, ring, eye, frame["centre"], frame["front"], mm)
        h = fit.height(P[region]) / mm if fit.ok else np.zeros(1)
        outer = fit.outer(P, P[region], mm) if fit.ok else np.ones(1, bool)
        ho = h[outer] if outer.any() else np.zeros(1)
        lash = ((dark.astype(np.float64) + _adjacency(len(P), F) @ dark.astype(np.float64)) > 0)[region]
        hl = (h * weight[region])[lash & outer] if (lash & outer).any() else np.zeros(1)
        rows.append({"side": eye["side"], "centre_mm": [round(float(v) / mm, 1) for v in eye["centre"]],
                     "half_width_mm": round(float(eye["half_width"]) / mm, 1), "region_vertices": int(region.sum()),
                     "outer_vertices": int(outer.sum()), "fit_points": fit.points, "fit_mad_mm": round(fit.mad / mm, 2),
                     "p90_mm": round(float(np.percentile(h, 90)), 2), "max_mm": round(float(h.max()), 2),
                     "outer_p50_mm": round(float(np.percentile(ho, 50)), 2), "outer_p90_mm": round(float(np.percentile(ho, 90)), 2),
                     "outer_max_mm": round(float(ho.max()), 2), "over_limit": int((h > EYE_LIMIT_MM).sum()),
                     "weighted_max_mm": round(float((h * weight[region]).max()), 2),
                     "lash_outer_weighted_p90_mm": round(float(np.percentile(hl, 90)), 2),
                     "lash_outer_weighted_max_mm": round(float(hl.max()), 2),
                     "outer_over_limit": int((ho > EYE_LIMIT_MM).sum()), "outer_over_5mm": int((ho > 5).sum())})
    out["eyes"] = {"status": "measured", "front_axis": "+z" if frame["front"] > 0 else "-z", "eyes": rows}
    mouth, reason = _locate_mouth(P, colours, eyes, frame, mm)
    if mouth is None:
        out["mouth"] = {"status": "skipped", "reason": reason}
        return out
    _texture_after, mouth_record = _neutralise_mouth(texture, U, F, P, mouth, mm)
    out["mouth"] = {k: v for k, v in mouth_record.items()
                    if k in ("centre_mm", "paint_vertices", "lip_texels", "skin_rgb", "skin_sat", "lip_rgb_before",
                             "ratio_before", "ratio_reddest30_before", "limit")}
    return out


def enabled_for(character_name: str) -> bool:
    """The per-character switch (``model3d_opts.face_cleanup``, default on)."""
    from app.core.model3d import get_model3d_options
    return bool(get_model3d_options(character_name).get("face_cleanup", True))


def summary(record: Dict[str, Any]) -> str:
    """One line for the model overview / logs."""
    parts = []
    eyes = record.get("eyes") or {}
    if eyes.get("status") == "applied":
        before = max((float((e.get("before_mm") or {}).get("lash_outer_max") or 0) for e in eyes.get("eyes") or []), default=0.0)
        after = max((float((e.get("after_mm") or {}).get("lash_weighted_max") or 0) for e in eyes.get("eyes") or []), default=0.0)
        moved = sum(int(e.get("moved_vertices") or 0) for e in eyes.get("eyes") or [])
        parts.append(f"lashes {before:.1f} → {after:.1f} mm proud ({moved} vertices)")
    elif eyes.get("status") == "skipped":
        parts.append("eyes: " + str(eyes.get("reason") or "skipped"))
    mouth = record.get("mouth") or {}
    if mouth.get("status") == "applied":
        parts.append(f"lips/skin saturation {mouth.get('ratio_before')} → {mouth.get('ratio_after')}")
    elif mouth.get("status") == "skipped":
        parts.append("mouth: " + str(mouth.get("reason") or "skipped"))
    return " · ".join(parts)


__all__ = ["clean_face", "measure_face", "enabled_for", "summary", "EYE_LIMIT_MM", "LIP_RATIO_LIMIT", "VERSION"]
