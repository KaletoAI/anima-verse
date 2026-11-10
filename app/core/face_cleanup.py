"""Face cleanup of a freshly generated humanoid mesh — BEFORE the face retexture.

Two defects of the image-to-mesh step, both inherited from what the image model paints on the face
(user request 2026-11-09, measured on Kira's base meshes in ``~/claude-out/eye-lashes``):

1. EYES — painted lashes become geometry. The mesher turns the mascara-like lash lines into thin flaps that
   stand proud of the eyelids: an upper flap juts forward like a visor, a lower one hangs down. Measured
   against a smooth lid surface fitted to the orbit around each eye, the dark (lash-painted) vertices stood
   up to 19-25 mm proud (character scale), p90 9-21 mm. Version 1 pressed every proud vertex straight back
   onto that fitted lid, x and y kept. On a visor that hangs in FRONT of the eye that lands the flap on the
   eyeball (Lirien 2026-11-10: the flap's top sheet ended 0.5-1.4 mm above the lid, its underside 0.6-2.6 mm
   below it, the eyeball itself sits 2.2 mm below — the pressed black sheet covered the eye and the user saw
   the eyes "fallen inward" with black rims, 37 turned faces per eye). Version 2 FOLDS each flap back onto
   its root instead: the connected set of vertices standing more than ``EYE_FREE_MM`` proud of the fitted lid
   (top side and underside alike) is collapsed onto the lid skin it grows out of — every flap vertex takes
   the position of the anchor (a visible lid vertex at lid height next to the flap) its root reaches first,
   ``INSET_MM`` under the lid along the lid normal, assigned by a breadth-first walk from the root ring so a
   flap never tears across the eye. The flap's triangles end with no area (or sub-millimetre, under the skin);
   the eyeball, the lids, the sockets and the brow keep their exact bytes, because only the flap set moves.
   Topology, UVs, normals and the texture stay byte-identical.

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

Numbers gate (``smoke_face_cleanup.py``, hand-derived on a synthetic head): after the cleanup no vertex the eye
step moved stands above the lid it was folded onto (its height against the lid refitted on the result is at most
``EYE_LIMIT_MM`` = 1.0 mm — the inset puts it below), vertices the step did not move keep their exact bytes, and the
lips/skin saturation ratio ends at most ``LIP_RATIO_LIMIT`` (1.3) when the mouth was corrected.
"""
from __future__ import annotations

import io
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.timeutils import utc_now_iso

VERSION = 2
REFERENCE_HEIGHT_MM = 1700.0

# Eyes.
DARK_LUMINANCE = 0.25           # a lash-painted texel (linear-ish sRGB luminance of the 8-bit colour)
HEAD_SHARE = 0.15               # the head segment: the top 15 % of the figure's height
EYE_BAND = (0.45, 0.70)         # the eye line within the head segment
EYE_MIN_VERTICES = 30
EYE_HALF_WIDTH_MM = (8.0, 32.0)
# Separation of the two lash-paint CENTRES, not of the pupils: smoky paint and lash flaps widen toward the outer
# corner, so the paint median sits outward of the eye. Measured on the unrigged base meshes 2026-11-10: Kai 82 mm,
# Kira 88 mm, Lirien 100 mm — 90 refused Lirien and left her lash flaps black through the face retexture
# (smoke_face_cleanup_eye_separation.py).
EYE_SEPARATION_MM = (35.0, 110.0)
EYE_SYMMETRY_MM = 10.0          # |(xL - mid) + (xR - mid)|
EYE_LEVEL_MM = 8.0              # |yL - yR|
EYE_Y_TRIM_MM = 12.0            # paint farther than this from the eye line (brows, nostrils) is not the eye
EYE_REGION_MARGIN_MM = 10.0     # region ellipse: a = half_width + margin
EYE_REGION_ASPECT = 0.7         # region ellipse: b = aspect * half_width + margin
EYE_DEPTH_WINDOW_MM = 25.0
FIT_MIN_POINTS = 60             # depth-map cells a ray must hit for a usable lid surface
FIT_CELL_MM = 1.0               # the depth-map grid
BASE_SIGMAS_MM = (8.0, 16.0)    # the two scales of the smooth base: the fine one keeps the socket shape, the coarse one
                                # still sees a 3-4 mm wide frame as relief; the lid is the lower of the two envelopes
CONE_SLOPES = (1.0, 0.5)        # the slope limit per scale: 45 degrees against the fine base, 30 against the coarse
                                # one (a 4 mm wide rim may keep 4 mm at 45 degrees, 2 mm at 30)
BROW_MARGIN_MM = 3.0            # protected: from this far below the brow crest upward ...
BROW_SHARE = 0.9                # ... but never below this share of the eye half width above the eye centre ...
NOSE_SHARE = 0.9                # ... and the nose flank beyond this share of the eye half width toward the mid-line
PROTECT_FADE_MM = 3.0           # the protection's soft edge
CONE_REACH_MM = 12.0            # how far the cone looks
RELIEF_FLOOR_MM = 0.0           # a pit (the eye opening) never carves its surroundings: only what RISES above the
                                # base is a flap
RAY_START_MM = 60.0             # rays toward the head start this far in front of the lid plane
OUTER_TOLERANCE_MM = 1.0        # a vertex this close under the first surface a ray meets is on the outer shell
EYE_FREE_MM = 2.5               # a vertex proud of the fit up to this is lid, above it flap; an anchor is at most this
                                # proud. A natural lid margin is a ridge of 1-2 mm, and the skin next to a flap or around
                                # the eye opening reads up to ~2 mm proud of the envelope (its base is a mean the opening
                                # pulls down; synthetic head: 1.5-2.0 mm at the rim) — that skin must stay
EYE_LIMIT_MM = 2.0              # a folded vertex against the lid after the cleanup: never more than this (it ends INSET_MM
                                # under an anchor of at most EYE_FREE_MM, so 1.9 at the most)
INSET_MM = 0.6                  # a folded vertex ends this far BELOW its anchor's lid height (under the skin, never
                                # fighting the lid for the same depth)
ANCHOR_DEPTH_MM = 1.0           # an anchor lies at lid height: at most EYE_FREE_MM proud, at most this deep — visible
                                # or not, because the root ring of a visor that overhangs the eye is hidden under it
                                # (Lirien's left visor: its only lid contact were 5 occluded nodes at 0.0-0.3 mm); the
                                # eyeball under the visor (1.2-2.2 mm deep), the rim of the eye opening and the inner
                                # wall of the double-walled shell lie deeper and never anchor

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
LIP_SATURATION_RATIO = 1.1      # target lips/skin saturation (photos and renders: 1.17-1.24; the soft mask lands above it)
LIP_LUMINANCE_RATIO = 0.88      # target lip luminance / skin luminance
LIP_DETAIL_LUMA_GAIN = 0.7      # texture detail inside the lips: luminance kept at this contrast ...
LIP_DETAIL_CHROMA_GAIN = 0.35   # ... colour variation at this (the paint exaggerates both)
LIP_RATIO_LIMIT = 1.3           # the gate
LIP_CHROMA_DIRECTION = np.array([0.78, -0.33, -0.53])   # natural lips: redder, green down most
MASK_FEATHER_PX = 6

_LUMA = np.array([0.2126, 0.7152, 0.0722])


# --- helpers ----------------------------------------------------------------------------------------------------------

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
        footprint = (d2 >= 1.0) & (d2 < 1.8) & head & (front * (P[:, 2] - centre[2]) > 0) & (lum >= DARK_LUMINANCE)
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


def _cone_erosion(field: np.ndarray, slope: float, reach: int) -> np.ndarray:
    """Grey erosion with a cone of the given slope (per cell): ``T[p] = min_q field[q] + slope * |p - q|`` over
    all ``q`` within ``reach`` cells — one shifted minimum per offset."""
    na, nb = field.shape
    out = field.copy()
    for di in range(-reach, reach + 1):
        for dj in range(-reach, reach + 1):
            dist = float(np.hypot(di, dj))
            if dist == 0 or dist > reach:
                continue
            shifted = np.full_like(field, np.inf)
            src_a = slice(max(0, -di), min(na, na - di))
            dst_a = slice(max(0, di), min(na, na + di))
            src_b = slice(max(0, -dj), min(nb, nb - dj))
            dst_b = slice(max(0, dj), min(nb, nb + dj))
            shifted[dst_a, dst_b] = field[src_a, src_b]
            np.minimum(out, shifted + slope * dist, out=out)
    return out


class _LidSurface:
    """The lid WITHOUT its flaps, as a height field over the eye region.

    Depth map first: on a FIT_CELL_MM grid in the lid plane (frame: normal radial from the head centre at the eye,
    tangents from world up) a ray from outside measures the height of the first surface it meets — the visible
    skin, flaps included, inner walls excluded (60-75 % of these shells' vertices lie on inner walls). The map is
    split into a smooth base S (a wide Gaussian over the measured cells — the head's own curvature, temple and
    nose fall-off) and the local relief R = D - S. The relief gets a SLOPE-LIMITED lower envelope (a grey erosion
    with a cone: T(p) = min_q R(q) + CONE_SLOPE * |p - q|): nothing in the lid may rise steeper than CONE_SLOPE
    from what lies next to it. That is exactly what a flap is — a visor jutting 10 mm out of the lid within 2-3 mm
    of lid plane, a lash ridge rising 8 mm within a millimetre — whether it stands alone or hangs off the brow (an
    OPENING kept the visor as part of the broad brow, a quadric spanned the socket like a drum skin and the pressed
    flap stayed a ledge); the brow, the cheekbone and the recessed eye opening rise gently out of S and come back
    as they are. The lid is S + T, lightly blurred against the grid's staircase. ``height`` reads a point's
    signed height above it, ``outer`` whether the point lies on the visible surface, ``protected`` the brow/nose bands."""

    def __init__(self, P: np.ndarray, F: np.ndarray, region: np.ndarray, eye: Dict[str, Any],
                 head_centre: np.ndarray, front: int, mm: float):
        from scipy import ndimage
        c = eye["centre"]
        normal = np.array([0.5 * (c[0] - head_centre[0]), 0.0, front * max(abs(c[2] - head_centre[2]), 1e-6)])
        self.normal = normal / np.linalg.norm(normal)
        t1 = np.cross(np.array([0.0, 1.0, 0.0]), self.normal)
        self.t1 = t1 / np.linalg.norm(t1)
        self.t2 = np.cross(self.normal, self.t1)
        self.origin = c.copy()
        self.faces = F[(np.linalg.norm(P[F[:, 0]] - c, axis=1) < 2 * RAY_START_MM * mm)]
        a, b, _h = self.local(P[region])
        cell = FIT_CELL_MM * mm
        margin = CONE_REACH_MM * mm
        self.a0, self.b0, self.cell = a.min() - margin, b.min() - margin, cell
        na = int(np.ceil((a.max() + margin - self.a0) / cell)) + 1
        nb = int(np.ceil((b.max() + margin - self.b0) / cell)) + 1
        ga, gb = np.meshgrid(self.a0 + np.arange(na) * cell, self.b0 + np.arange(nb) * cell, indexing="ij")
        plane = np.stack([ga.reshape(-1), gb.reshape(-1)], 1)
        depth = _ray_heights(self.origin, self.t1, self.t2, self.normal, plane, P, self.faces,
                             RAY_START_MM * mm).reshape(na, nb)
        hit = np.isfinite(depth)
        self.cells, self.hits = int(depth.size), int(hit.sum())
        self.ok = self.hits >= FIT_MIN_POINTS
        if not self.ok:
            self.visible = self.lid = np.zeros_like(depth)
            return
        if not hit.all():
            # A cell without a hit (silhouette, a hole) takes the nearest measured height.
            nearest = ndimage.distance_transform_edt(~hit, return_distances=False, return_indices=True)
            depth = depth[tuple(nearest)]
        envelope = np.full_like(depth, np.inf)
        fine = None
        reach = int(round(CONE_REACH_MM / FIT_CELL_MM))
        for sigma_mm, slope in zip(BASE_SIGMAS_MM, CONE_SLOPES):
            sigma = sigma_mm / FIT_CELL_MM
            base = (ndimage.gaussian_filter(np.where(hit, depth, 0.0), sigma)
                    / np.maximum(ndimage.gaussian_filter(hit.astype(np.float64), sigma), 1e-6))
            # A cell without a hit never carves its neighbours; a pit (the eye opening, a gap into the shell)
            # carves at most RELIEF_FLOOR_MM deep (0: not at all) — the lid around a socket is not a flap.
            relief = np.where(hit, np.maximum(depth - base, -RELIEF_FLOOR_MM * mm), np.inf)
            # The slope is height per lid-plane length: per grid cell that is slope * cell (mesh units).
            one = base + np.minimum(_cone_erosion(relief, slope * cell, reach), np.where(hit, depth - base, 0.0))
            envelope = np.minimum(envelope, one)
            fine = one if fine is None else fine
        # Protected bands: the brow (from BROW_MARGIN_MM under its crest upward) and the nose flank (beyond
        # NOSE_SHARE of the eye half width toward the mid-line) keep the visible surface — the coarse scale would
        # otherwise carve them. Found on the FINE envelope (flaps already removed there, the broad brow not): the
        # crest is its highest row of the central column band above the eye.
        hw = eye["half_width"]
        rows_b = self.b0 + np.arange(nb) * cell
        cols_a = self.a0 + np.arange(na) * cell
        central = np.abs(cols_a) < 0.6 * hw
        above = rows_b > 0.5 * hw
        crest = None
        if central.any() and above.any():
            profile = np.where(hit[central][:, above], fine[central][:, above], -np.inf).mean(0)
            if np.isfinite(profile).any():
                crest = rows_b[above][int(np.argmax(profile))]
        # The brow begins BROW_SHARE half widths above the eye centre at the latest; a crest found below that is
        # the flap itself (the face slopes back above it), never the brow.
        self.brow_from = max(BROW_SHARE * hw, (crest - BROW_MARGIN_MM * mm) if crest is not None else -np.inf)
        nose_sign = -1.0 if (c[0] - head_centre[0]) * (self.t1[0]) > 0 else 1.0   # toward the mid-line along t1
        self.nose_from = nose_sign * NOSE_SHARE * hw
        keep = np.minimum(1.0, np.maximum(0.0, (self.brow_from - gb) / (PROTECT_FADE_MM * mm)))
        toward = nose_sign * (ga - self.nose_from)
        keep *= np.minimum(1.0, np.maximum(0.0, -toward / (PROTECT_FADE_MM * mm)))
        self.protect = 1.0 - keep                      # 1 inside a protected band
        envelope = np.where(np.isfinite(envelope), envelope, depth)
        envelope = np.where(hit, envelope + (depth - envelope) * self.protect, envelope)
        self.visible = depth
        self.lid = ndimage.gaussian_filter(envelope, 1.0)
        ra, rb, _ = self.local(P[region])
        inside = np.zeros_like(hit)
        inside[np.clip(((ra - self.a0) / cell).round().astype(int), 0, na - 1),
               np.clip(((rb - self.b0) / cell).round().astype(int), 0, nb - 1)] = True
        self.removed_mm = float((depth - envelope)[inside & hit].max() / mm) if (inside & hit).any() else 0.0

    def local(self, Q: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        R = Q - self.origin
        return R @ self.t1, R @ self.t2, R @ self.normal

    def _grid(self, field: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        from scipy import ndimage
        coords = np.stack([(a - self.a0) / self.cell, (b - self.b0) / self.cell])
        return ndimage.map_coordinates(field, coords, order=1, mode="nearest")

    def protected(self, Q: np.ndarray) -> np.ndarray:
        """How protected each point is (1 = brow band or nose flank: never moved)."""
        a, b, _h = self.local(Q)
        return self._grid(self.protect, a, b)

    def height(self, Q: np.ndarray) -> np.ndarray:
        """Signed height of each point above the lid without flaps (along the lid normal)."""
        a, b, h = self.local(Q)
        return h - self._grid(self.lid, a, b)

    def outer(self, P: np.ndarray, Q: np.ndarray, mm: float) -> np.ndarray:
        """Which of the points ``Q`` lie on the visible surface (within OUTER_TOLERANCE_MM under the first
        surface a ray from outside meets above them)."""
        a, b, h = self.local(Q)
        return self._grid(self.visible, a, b) - h < OUTER_TOLERANCE_MM * mm

def _eye_region(P: np.ndarray, eye: Dict[str, Any], head: np.ndarray, mm: float) -> np.ndarray:
    """The eye region: the paint plus a margin (an ellipse in x/y, a depth window in z) — what the fold may touch."""
    c, hw = eye["centre"], eye["half_width"]
    a = hw + EYE_REGION_MARGIN_MM * mm
    b = EYE_REGION_ASPECT * hw + EYE_REGION_MARGIN_MM * mm
    d2 = ((P[:, 0] - c[0]) / a) ** 2 + ((P[:, 1] - c[1]) / b) ** 2
    depth = np.abs(P[:, 2] - c[2]) < EYE_DEPTH_WINDOW_MM * mm
    return (d2 < 1.0) & head & depth


def _flipped(P0: np.ndarray, P1: np.ndarray, faces: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """``(turned, collapsed)``: faces whose normal turned over between ``P0`` and ``P1`` (dot < 0) while keeping at
    least a quarter of their area, and faces that lost three quarters of it or more — a flap's own triangles once
    its vertices sit on their anchors, and the sub-millimetre slivers between an anchor and the vertices folded
    INSET_MM under it (a sliver points into the surface, its normal is anything; it is not a turned face)."""
    n0 = np.cross(P0[faces[:, 1]] - P0[faces[:, 0]], P0[faces[:, 2]] - P0[faces[:, 0]])
    n1 = np.cross(P1[faces[:, 1]] - P1[faces[:, 0]], P1[faces[:, 2]] - P1[faces[:, 0]])
    a0 = np.linalg.norm(n0, axis=1)
    a1 = np.linalg.norm(n1, axis=1)
    collapsed = (a1 < 0.25 * a0) & (a0 > 0)
    return ((n0 * n1).sum(1) < 0) & ~collapsed, collapsed


def _adjacency(n: int, F: np.ndarray):
    from scipy.sparse import coo_matrix
    i = np.concatenate([F[:, 0], F[:, 1], F[:, 2], F[:, 1], F[:, 2], F[:, 0]])
    j = np.concatenate([F[:, 1], F[:, 2], F[:, 0], F[:, 0], F[:, 1], F[:, 2]])
    adjacency = coo_matrix((np.ones(len(i)), (i, j)), shape=(n, n)).tocsr()
    adjacency.data[:] = 1.0
    return adjacency


def _weld(P: np.ndarray, F: np.ndarray, mm: float):
    """``(node of every vertex, adjacency of the nodes)``: vertices at the same position (within 0.01 mm) are ONE
    node — a glTF mesh is split along its UV seams into duplicated vertices, and a flap's top side, rim and
    underside meet across such seams. Connectivity by index alone fragments a flap into dozens of islands without
    lid contact (Lirien's left flap: 38 islands, 157 of 207 vertices without an anchor)."""
    from scipy.sparse import coo_matrix
    _unique, node = np.unique(np.round(P / mm, 2), axis=0, return_inverse=True)
    node = node.reshape(-1)
    n = int(node.max()) + 1
    i = node[np.concatenate([F[:, 0], F[:, 1], F[:, 2], F[:, 1], F[:, 2], F[:, 0]])]
    j = node[np.concatenate([F[:, 1], F[:, 2], F[:, 0], F[:, 0], F[:, 1], F[:, 2]])]
    keep = i != j
    adjacency = coo_matrix((np.ones(int(keep.sum())), (i[keep], j[keep])), shape=(n, n)).tocsr()
    adjacency.data[:] = 1.0
    return node, adjacency


def _fold_flaps(adjacency, proud: np.ndarray, anchor: np.ndarray, Q: np.ndarray) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
    """Which anchor each proud node folds onto. ``adjacency``: the welded node graph (CSR); ``proud``: the flap set
    (bool per node); ``anchor``: the nodes a flap may fold onto; ``Q``: a position per node (for the nearest root
    anchor). Returns ``(target, flaps)``: ``target[v]`` = the anchor node (-1 for a node not folded) and one record
    per connected flap set. A breadth-first walk from the root ring (flap nodes next to an anchor, each with its
    nearest adjacent anchor) assigns every reachable flap node the anchor of the neighbour it was reached from —
    contiguous, so a flap never tears across the eye; a set without an anchor is left alone."""
    from collections import deque
    from scipy.sparse.csgraph import connected_components
    n = len(proud)
    target = np.full(n, -1, int)
    proud_idx = np.flatnonzero(proud)
    if not len(proud_idx):
        return target, []
    sub = adjacency[proud_idx][:, proud_idx]
    count, labels = connected_components(sub, directed=False)
    indptr, indices = adjacency.indptr, adjacency.indices
    records = []
    for comp in range(count):
        verts = proud_idx[labels == comp]
        queue = deque()
        for v in verts:
            neighbours = indices[indptr[v]:indptr[v + 1]]
            near = neighbours[anchor[neighbours]]
            if len(near):
                d = np.linalg.norm(Q[near] - Q[v], axis=1)
                target[v] = near[int(np.argmin(d))]
                queue.append(v)
        roots = len(queue)
        while queue:
            v = queue.popleft()
            for w in indices[indptr[v]:indptr[v + 1]]:
                if proud[w] and target[w] < 0:
                    target[w] = target[v]
                    queue.append(w)
        folded = int((target[verts] >= 0).sum())
        records.append({"vertices": int(len(verts)), "roots": roots, "folded": folded})
    return target, records


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
    adjacency = _adjacency(len(P), F)
    lash_all = ((dark.astype(np.float64) + adjacency @ dark.astype(np.float64)) > 0)
    node, welded = _weld(P, F, mm)
    for eye in eyes:
        region = _eye_region(P, eye, head, mm)
        record: Dict[str, Any] = {"side": eye["side"], "centre_mm": [round(float(v) / mm, 1) for v in eye["centre"]],
                                  "half_width_mm": round(float(eye["half_width"]) / mm, 1),
                                  "paint_vertices": eye["vertices"], "region_vertices": int(region.sum())}
        idx = np.flatnonzero(region)
        lash = lash_all[idx]
        record["lash_vertices"] = int(lash.sum())
        fit = _LidSurface(P, F, region, eye, frame["centre"], front, mm)
        if not fit.ok:
            record.update(status="skipped", reason=f"only {fit.hits} depth cells hit over the eye")
            records.append(record)
            continue
        h = fit.height(P[idx]) / mm
        outer = fit.outer(P, P[idx], mm)
        protect = fit.protected(P[idx]) > 0.5
        record["protected_vertices"] = int(protect.sum())
        record["brow_from_mm"] = round(float(fit.brow_from / mm), 1)
        record["outer_vertices"] = int(outer.sum())
        record["before_mm"] = {"p90": round(float(np.percentile(h, 90)), 2), "max": round(float(h.max()), 2),
                               "outer_p90": round(float(np.percentile(h[outer], 90)), 2) if outer.any() else None,
                               "outer_max": round(float(h[outer].max()), 2) if outer.any() else None,
                               "lash_outer_p90": round(float(np.percentile(h[outer & lash], 90)), 2) if (outer & lash).any() else None,
                               "lash_outer_max": round(float(h[outer & lash].max()), 2) if (outer & lash).any() else None}
        # The flap set: everything that stands more than EYE_FREE_MM proud of the lid without flaps — the visor's top
        # and its underside alike (the envelope is slope-limited, so a gentle dome such as a bulging eyeball is part
        # of the lid and never proud). The anchors: vertices at lid height (ANCHOR_DEPTH_MM), the skin a flap grows
        # out of — visible or hidden under the flap's own overhang. Both on the WELDED nodes of the region: a node is
        # proud when any of its vertices is, an anchor when none is and one of them lies at lid height.
        proud_v = (h > EYE_FREE_MM) & ~protect
        anchor_v = ~proud_v & (h <= EYE_FREE_MM) & (h >= -ANCHOR_DEPTH_MM)
        n_nodes = welded.shape[0]
        proud_n = np.zeros(n_nodes, bool)
        anchor_n = np.zeros(n_nodes, bool)
        in_region = np.zeros(n_nodes, bool)
        in_region[node[idx]] = True
        proud_n[node[idx[proud_v]]] = True
        anchor_n[node[idx[anchor_v]]] = True
        anchor_n &= ~proud_n
        q = np.zeros((n_nodes, 3))
        q[node[idx]] = P[idx]
        # Only the region's nodes take part: an edge out of the region leads nowhere.
        sub_nodes = np.flatnonzero(in_region)
        local = welded[sub_nodes][:, sub_nodes].tocsr()
        target_l, components = _fold_flaps(local, proud_n[sub_nodes], anchor_n[sub_nodes], q[sub_nodes])
        target_n = np.full(n_nodes, -1, int)
        target_n[sub_nodes[target_l >= 0]] = sub_nodes[target_l[target_l >= 0]]
        target = target_n[node[idx]]
        fold = target >= 0
        record["flaps"] = {"sets": len(components), "folded_sets": sum(1 for c in components if c["folded"]),
                           "largest": max((c["vertices"] for c in components), default=0)}
        record["flap_vertices"] = int(proud_v.sum())
        record["flap_lash_share"] = round(float(lash[proud_v].mean()), 2) if proud_v.any() else None
        record["unanchored_vertices"] = int((proud_v & ~fold).sum())
        if not fold.any():
            record.update(status="skipped", reason="no flap stands proud of the lid" if not proud.any()
                          else "the proud vertices touch no lid skin to fold onto")
            record.setdefault("after_mm", record["before_mm"])
            records.append(record)
            continue
        out[idx[fold]] = q[target[fold]] - INSET_MM * mm * fit.normal
        # The numbers after, against the SAME lid (a refit on the result is no reference: once a visor is gone the
        # depth map sees the socket under it and the base drops by millimetres). The folded vertices sit INSET_MM
        # under anchors of at most EYE_FREE_MM; what the fold could not reach (a proud set without lid contact)
        # is left standing and reported as the residue.
        after = fit.height(out[idx]) / mm
        residue = proud_v & ~fold
        region_faces = F[region[F].any(1)]
        turned, collapsed = _flipped(P, out, region_faces)
        shift = np.linalg.norm(out[idx] - P[idx], axis=1) / mm
        record["after_mm"] = {"p90": round(float(np.percentile(after, 90)), 2), "max": round(float(after.max()), 2),
                              "folded_max": round(float(after[fold].max()), 2),
                              "lash_weighted_max": round(float(after[fold & lash].max()), 2) if (fold & lash).any() else round(float(after[fold].max()), 2),
                              "residual_max": round(float(after[residue].max()), 2) if residue.any() else None,
                              "fold_p90": round(float(np.percentile(shift[fold], 90)), 2), "fold_max": round(float(shift[fold].max()), 2)}
        record["protected_shift_mm"] = 0.0
        record["flipped_faces"] = {"after": int(turned.sum()), "collapsed": int(collapsed.sum())}
        record.update(status="applied", moved_vertices=int(fold.sum()))
        moved_all[idx[fold]] = True
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
    x3, x97 = np.percentile(pts[:, 0], [3, 97])
    y3, y97 = np.percentile(pts[:, 1], [3, 97])
    width = x97 - x3
    if not (LIP_WIDTH_MM[0] * mm <= width <= LIP_WIDTH_MM[1] * mm):
        return None, f"lip paint {width / mm:.0f} mm wide is not a mouth"
    # The mouth sits on the face's mid-line (between the eyes) and is symmetric about it — a one-sided paint
    # cluster must not shift or narrow the region onto one half (review 2026-11-09: half the lips left crimson).
    half_width = max(abs(x3 - mid_x), abs(x97 - mid_x))
    half_height = max((y97 - y3) / 2, 3 * mm)
    c = np.array([mid_x, (y3 + y97) / 2, float(np.median(pts[:, 2]))])
    return {"centre": c, "half_width": half_width, "half_height": half_height, "vertices": int(lips.sum()),
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
    # Every face is rasterised into the mask wherever its UV triangle lies, so the lips are covered on every UV
    # island they touch; the halves (by the face's 3D side of the mid-line) are measured separately.
    centroid_x = P[faces].mean(1)[:, 0]
    halves = {"left": _triangle_mask(U, faces[centroid_x >= c[0]], width, height),
              "right": _triangle_mask(U, faces[centroid_x < c[0]], width, height)}
    rgb = texture[..., :3].astype(np.float64)
    lips_sel, before = _mouth_stats(rgb, area, mouth)
    before["halves"] = {side: _mouth_stats(rgb, half, mouth)[1]["ratio"] if half.any() else None for side, half in halves.items()}
    record: Dict[str, Any] = {"centre_mm": [round(float(v) / mm, 1) for v in c], "paint_vertices": mouth["vertices"],
                              "area_texels": int(area.sum()), "lip_texels": before["lip_texels"],
                              "skin_rgb": [int(v) for v in mouth["skin_rgb"]], "skin_sat": round(mouth["skin_sat"], 3),
                              "lip_rgb_before": before["lip_rgb"], "ratio_before": before["ratio"],
                              "ratio_reddest30_before": before["ratio_reddest30"], "halves_before": before["halves"],
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
    skin_sat = max(mouth["skin_sat"], 1e-6)
    record.update(status="applied", lip_rgb_after=[int(v) for v in out[lips_sel].mean(0)],
                  ratio_after=round(float(np.mean(sat_after[lips_sel])) / skin_sat, 2),
                  ratio_reddest30_after=after["ratio_reddest30"], changed_texels=int((weight > 0.01).sum()),
                  halves_after={side: (round(float(np.mean(sat_after[lips_sel & half])) / skin_sat, 2)
                                       if (lips_sel & half).any() else None) for side, half in halves.items()})
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
    """The measurement alone (eye protrusion against the fitted lids — the flap set that would fold — and the
    lips/skin saturation), nothing changed — the smoke and the report run it on a file before and after
    ``clean_face``."""
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
    dark = lum < DARK_LUMINANCE
    adjacency = _adjacency(len(P), F)
    lash_all = ((dark.astype(np.float64) + adjacency @ dark.astype(np.float64)) > 0)
    for eye in eyes:
        region = _eye_region(P, eye, frame["head"], mm)
        lash = lash_all[region]
        fit = _LidSurface(P, F, region, eye, frame["centre"], frame["front"], mm)
        h = fit.height(P[region]) / mm if fit.ok else np.zeros(1)
        outer = fit.outer(P, P[region], mm) if fit.ok else np.ones(1, bool)
        protect = (fit.protected(P[region]) > 0.5) if fit.ok else np.zeros(1, bool)
        ho = h[outer] if outer.any() else np.zeros(1)
        hl = h[lash & outer] if (lash & outer).any() else np.zeros(1)
        proud = (h > EYE_FREE_MM) & ~protect
        rows.append({"side": eye["side"], "centre_mm": [round(float(v) / mm, 1) for v in eye["centre"]],
                     "half_width_mm": round(float(eye["half_width"]) / mm, 1), "region_vertices": int(region.sum()),
                     "outer_vertices": int(outer.sum()), "depth_cells_hit": fit.hits,
                     "protected_vertices": int(protect.sum()),
                     "removed_mm": round(fit.removed_mm, 2) if fit.ok else None,
                     "p90_mm": round(float(np.percentile(h, 90)), 2), "max_mm": round(float(h.max()), 2),
                     "outer_p50_mm": round(float(np.percentile(ho, 50)), 2), "outer_p90_mm": round(float(np.percentile(ho, 90)), 2),
                     "outer_max_mm": round(float(ho.max()), 2), "over_limit": int((h > EYE_LIMIT_MM).sum()),
                     "flap_vertices": int(proud.sum()), "flap_lash_share": round(float(lash[proud].mean()), 2) if proud.any() else None,
                     "lash_outer_p90_mm": round(float(np.percentile(hl, 90)), 2),
                     "lash_outer_max_mm": round(float(hl.max()), 2),
                     "outer_over_limit": int((ho > EYE_LIMIT_MM).sum()), "outer_over_5mm": int((ho > 5).sum())})
    out["eyes"] = {"status": "measured", "front_axis": "+z" if frame["front"] > 0 else "-z", "eyes": rows}
    mouth, reason = _locate_mouth(P, colours, eyes, frame, mm)
    if mouth is None:
        out["mouth"] = {"status": "skipped", "reason": reason}
        return out
    _texture_after, mouth_record = _neutralise_mouth(texture, U, F, P, mouth, mm)
    out["mouth"] = {k: v for k, v in mouth_record.items()
                    if k in ("centre_mm", "paint_vertices", "lip_texels", "skin_rgb", "skin_sat", "lip_rgb_before",
                             "ratio_before", "ratio_reddest30_before", "halves_before", "limit")}
    return out


def enabled_for(character_name: str) -> bool:
    """The per-character switch (``model3d_opts.face_cleanup``; default OFF — the fold exposes the eye
    socket the mesher built under the visor, and whether the face projection reads well in it is judged
    per character on the rendered model)."""
    from app.core.model3d import get_model3d_options
    return bool(get_model3d_options(character_name).get("face_cleanup"))


def summary(record: Dict[str, Any]) -> str:
    """One line for the model overview / logs."""
    parts = []
    eyes = record.get("eyes") or {}
    if eyes.get("status") == "applied":
        before = max((float((e.get("before_mm") or {}).get("lash_outer_max") or 0) for e in eyes.get("eyes") or []), default=0.0)
        after = max((float((e.get("after_mm") or {}).get("lash_weighted_max") or 0) for e in eyes.get("eyes") or []), default=0.0)
        moved = sum(int(e.get("moved_vertices") or 0) for e in eyes.get("eyes") or [])
        flips = max((int((e.get("flipped_faces") or {}).get("after") or 0) for e in eyes.get("eyes") or []), default=0)
        residue = [e for e in eyes.get("eyes") or [] if (e.get("after_mm") or {}).get("residual_max") is not None]
        left = sum(int(e.get("unanchored_vertices") or 0) for e in residue)
        tallest = max((float(e["after_mm"]["residual_max"]) for e in residue), default=0.0)
        parts.append(f"lashes {before:.1f} → {after:.1f} mm proud ({moved} vertices folded"
                     + (f", {left} left standing up to {tallest:.1f} mm" if left else "")
                     + (f", {flips} turned faces" if flips else "") + ")")
    elif eyes.get("status") == "skipped":
        parts.append("eyes: " + str(eyes.get("reason") or "skipped"))
    mouth = record.get("mouth") or {}
    if mouth.get("status") == "applied":
        parts.append(f"lips/skin saturation {mouth.get('ratio_before')} → {mouth.get('ratio_after')}")
    elif mouth.get("status") == "skipped":
        parts.append("mouth: " + str(mouth.get("reason") or "skipped"))
    return " · ".join(parts)


__all__ = ["clean_face", "measure_face", "enabled_for", "summary", "EYE_LIMIT_MM", "LIP_RATIO_LIMIT", "VERSION"]
