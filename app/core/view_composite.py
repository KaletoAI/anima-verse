"""The CPU composite of a two-step view (plan 2026-11-12-unified-worn-pieces,
Task 11g, Ruling C1): what a DRAFT wears, put onto the stored base view.

A dressed back or side view of an outfit (``base_body._dress_view``) and the
worn back of an own-mesh piece (``garment_images._drafted_back``) are made in
two steps. The first stays a hub job: the DRAFT, an edit of the dressed (worn)
front turned around. The second used to be a model FIT of the draft onto the
base view; it is this module now — deterministic, pure CPU, no hub job, no
model fallback. It replaced the fit because the fit put nothing on, moved the
figure or invented clothing (spike ``~/claude-out/back-composite-spike/``,
2026-11-12: the composite beat the fit on 8 of 8 stored backs — figure IoU
0.97..1.00 against 0.59..0.93, garment coverage 98..100 % against 4..96 %).

The method (``composite_arrays``), on float RGBA arrays in 0..255:

1. ALIGN — height + centre: the draft's figure is scaled to the base
   figure's height, its top put on the base top and its centre on the base
   centre (``_similarity``; the model fit's canvas placed its draft the
   same way).
2. WARP — a smooth warp driven by the silhouettes: TV-L1 optical flow
   between the clipped signed distance fields of the two figures at
   ``FLOW_HEIGHT`` rows, Gaussian-smoothed (``FLOW_SMOOTH``) and applied to
   the aligned draft (``_shape_flow``). The flare of a skirt (draft garment
   bridging the base's leg gap in the hip-to-knee band, outside the base
   figure) is left out of the flow and pasted unwarped — trouser legs and
   sleeve cuffs are not flare (only a row whose whole leg gap the draft
   covers counts, ``_flare``).
3. MASK — the garment: the registered draft's figure pixels that differ
   from the base by colour (``DE_GARMENT``, Lab ΔE76 after a light blur) or
   texture (local L-contrast differing by ``TEXTURE_DIFF``), minus skin:
   skin is modelled from the BASE's own figure (``Skin``: the chroma mode and
   its spread) and re-centred on the draft's head; draft skin over base skin
   is never garment, draft skin outside the base silhouette is limb drift.
   Opened, closed, specks dropped, small holes filled (``_garment_mask``).
4. SEAM — colour matching at the seam only: inside a band along the mask's
   edge the draft is shifted toward the base by the local offset measured
   on the skin ring just outside it (``_seam_colour_match``).
5. COMPOSITE — the base everywhere, the (seam-matched) draft inside the
   feathered mask, the flare on top; the base's alpha unless the mask adds
   figure (``_blend``).

The record (``composite_arrays`` / ``compose``): ``alignment`` (scale, dx,
dy in base px), ``warp`` (mean / p95 / max displacement in base px inside
the base figure), ``mask_share`` (mask / base figure), ``flare_px``,
``coverage`` (the put-on score of Task 11f, below), ``seam_de`` (median
CIEDE2000 across the mask edge where the draft is skin on both sides),
``ring_offset_de``, ``iou`` (the ALIGNMENT IoU: the registered draft figure
against the base figure), ``composite_iou`` / ``drift_px`` (the composite's
figure against the base's: IoU, mean outline distance), ``runtime_s``.

The CHECKS (``ok`` / ``reasons``):

* ``iou >= IOU_MIN`` (0.93) — the draft could be aligned onto the base. The
  spike's registered drafts: 0.9535 (Rosi, a skirt that flares) .. 0.9853;
  the model fits it replaced: 0.59 .. 0.93. Below it the draft stands
  differently from the base (another pose, a turned figure).
* ``coverage >= COVERAGE_MIN`` (0.5) — the composite put on what the draft
  wears: the Task 11f put-on score of the composite against the base and the
  REGISTERED draft (``_put_on``: the draft cells differing from the base by
  more than ``PUT_ON_REGION_DE`` at ``PUT_ON_WORK_HEIGHT`` rows, opened,
  head rows dropped, dilated; score = base_de / (base_de + draft_de) inside
  it — 0 = the composite is the bare base, 1 = it is the draft). 11f
  measured the bare fits 0.052 .. 0.127, the dressed ones 0.681 .. 0.956.
  A garment region below ``PUT_ON_MIN_REGION`` (0.03 of the base figure)
  means the draft wears nothing that shows in this view — coverage 0,
  ``NOTHING_TO_PUT_ON``.

The callers re-draft once on a failed check, then refuse with the numbers
(``refusal``); a refused composite is never published into the views or the
texture. ``compose`` refuses to run on the event loop and inside a GPU-queue
worker (``_guard_thread``): it is 3..5 s of CPU per view at 1536 rows.
"""
import asyncio
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

from app.core.log import get_logger

logger = get_logger("view_composite")

#: Bumped when the composite changes for the same inputs (recorded with every result).
VERSION = 1
#: Rows of the shape flow's work images.
FLOW_HEIGHT = 512
#: Gaussian sigma (work px) of the flow field.
FLOW_SMOOTH = 6.0
#: Clip (base px) of the signed distance fields the flow runs on.
SDF_CLIP = 40.0
#: Lab ΔE76 (after a 1.5 px blur) above which a draft pixel differs from the base.
DE_GARMENT = 16.0
#: Difference of the local L contrast (7 px window) above which a draft pixel differs in texture.
TEXTURE_DIFF = 6.0
#: Chroma Mahalanobis radius of "skin-like".
SKIN_MAHA = 3.0
#: Alpha above which a pixel belongs to a figure.
FIGURE_ALPHA = 127
#: Hip-to-knee band (share of the base figure's height from its top) where a skirt can flare.
FLARE_BAND = (0.40, 0.78)
#: The alignment IoU (registered draft figure / base figure) a composite needs.
IOU_MIN = 0.93
#: The put-on score a composite needs (Task 11f's limit).
COVERAGE_MIN = 0.5
#: The put-on measure of Task 11f (``base_body_gates`` 11f patch): work rows,
#: region ΔE, opening / dilation (cells), head share, minimum region.
PUT_ON_WORK_HEIGHT = 192
PUT_ON_REGION_DE = 20.0
PUT_ON_OPEN = 1
PUT_ON_DILATE = 2
PUT_ON_HEAD_SHARE = 0.12
PUT_ON_MIN_REGION = 0.03
#: The mask and coverage rule of a whole OUTFIT (the spike's; ``put_on``
#: = Task 11f's measure) and of ONE PIECE — the garment chain's worn back,
#: a draft that wears only that piece (measured 2026-11-12 on the 10
#: worn-back drafts of Anima Divide with an accepted worn back): a belt
#: (region 0.014 at 192 rows) and a necklace (0.0, in the head rows and
#: blurred into the skin by the cells) fell under the outfit's region
#: minimum although their composites were right. A piece keeps thin parts
#: (no opening, components from 30 px) and is measured at full resolution,
#: only the skull top (8 %) left out, without the dilation (it outweighs a
#: 3 px chain), with its own minimum region: belt 0.0196, necklace 0.0055,
#: a draft equal to its base 0.
RULES: Dict[str, Dict[str, Any]] = {
    "outfit": {"opening": 1, "min_component": 150,
               "put_on": {"work_height": PUT_ON_WORK_HEIGHT, "head_share": PUT_ON_HEAD_SHARE,
                          "dilate": PUT_ON_DILATE, "region_min": PUT_ON_MIN_REGION}},
    "piece": {"opening": 0, "min_component": 30,
              "put_on": {"work_height": None, "head_share": 0.08, "dilate": 0, "region_min": 0.002}},
}
#: The refusal reasons.
NOTHING_TO_PUT_ON = "nothing to put on"
NOT_ALIGNED = "the draft does not line up with the base"
NOT_COVERED = "the composite did not put on what the draft wears"
NO_FIGURE = "the draft has no figure"
#: Neutral grey of a flattened composite (``model_refs.VIEW_REFERENCE_BACKGROUND``).
GREY = (128, 128, 128)


class CompositeError(RuntimeError):
    """The composite cannot run (an input without a figure, a wrong thread)."""


# --- Helpers ------------------------------------------------------------------

def _largest(mask: np.ndarray) -> np.ndarray:
    from scipy import ndimage as ndi
    lab, n = ndi.label(mask)
    if n <= 1:
        return mask
    sizes = ndi.sum(mask, lab, range(1, n + 1))
    return lab == 1 + int(np.argmax(sizes))


def figure_mask(rgba: np.ndarray) -> np.ndarray:
    """The largest connected figure of an RGBA array (alpha > ``FIGURE_ALPHA``)."""
    return _largest(rgba[..., 3] > FIGURE_ALPHA)


def _bbox(mask: np.ndarray) -> Tuple[int, int, int, int]:
    rows = np.nonzero(mask.any(1))[0]
    cols = np.nonzero(mask.any(0))[0]
    return int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1


def _disk(r: int) -> np.ndarray:
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r * r


def _lab(rgba: np.ndarray) -> np.ndarray:
    from skimage import color
    return color.rgb2lab(np.clip(rgba[..., :3] / 255.0, 0, 1))


def _blur3(img: np.ndarray, sigma: float) -> np.ndarray:
    from scipy import ndimage as ndi
    return np.stack([ndi.gaussian_filter(img[..., i], sigma) for i in range(img.shape[-1])], -1)


def _local_std(lum: np.ndarray, size: int = 7) -> np.ndarray:
    from scipy import ndimage as ndi
    m = ndi.uniform_filter(lum, size)
    m2 = ndi.uniform_filter(lum * lum, size)
    return np.sqrt(np.maximum(m2 - m * m, 0))


def iou(a: np.ndarray, b: np.ndarray) -> float:
    return float((a & b).sum() / max(1, (a | b).sum()))


def contour_drift(a: np.ndarray, b: np.ndarray) -> float:
    """Symmetric mean outline distance (px) between two masks."""
    from scipy import ndimage as ndi
    ea = a & ~ndi.binary_erosion(a)
    eb = b & ~ndi.binary_erosion(b)
    if not ea.any() or not eb.any():
        return float("inf")
    da = ndi.distance_transform_edt(~eb)[ea]
    db = ndi.distance_transform_edt(~ea)[eb]
    return float((da.mean() + db.mean()) / 2)


# --- 1. Align -----------------------------------------------------------------

def _similarity(draft: np.ndarray, shape: Tuple[int, int], base_mask: np.ndarray
                ) -> Tuple[np.ndarray, Dict[str, float]]:
    """The draft resampled into the base frame: its figure scaled to the base
    figure's height, top on the base top, centre on the base centre.
    Returns ``(aligned RGBA, {"scale", "dx", "dy"})`` — dx / dy = where the
    draft figure's top-centre moved to, in base px."""
    from skimage import transform
    t0, b0, l0, r0 = _bbox(figure_mask(draft))
    t1, b1, l1, r1 = _bbox(base_mask)
    s = (b1 - t1) / (b0 - t0)
    cx0, cx1 = (l0 + r0) / 2, (l1 + r1) / 2
    # base(x, y) <- draft((x - cx1) / s + cx0, (y - t1) / s + t0)
    tf = transform.AffineTransform(matrix=np.array([[1 / s, 0, cx0 - cx1 / s], [0, 1 / s, t0 - t1 / s],
                                                    [0, 0, 1]]))
    out = transform.warp(draft / 255.0, tf, output_shape=shape, order=1, mode="constant", cval=0) * 255.0
    return out, {"scale": round(float(s), 4), "dx": round(float(cx1 - cx0), 2), "dy": round(float(t1 - t0), 2)}


# --- 2. Warp ------------------------------------------------------------------

def _sdf(mask: np.ndarray) -> np.ndarray:
    from scipy import ndimage as ndi
    inside = ndi.distance_transform_edt(mask)
    outside = ndi.distance_transform_edt(~mask)
    return np.clip(inside - outside, -SDF_CLIP, SDF_CLIP)


def _shape_flow(base_mask: np.ndarray, draft_mask: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """TV-L1 flow on the clipped signed distance fields at ``FLOW_HEIGHT``,
    smoothed and upsampled: ``(v, u)`` at full res such that
    ``draft(y + v, x + u) ~ base(y, x)``."""
    from scipy import ndimage as ndi
    from skimage import registration, transform
    h, w = base_mask.shape
    k = FLOW_HEIGHT / h
    work = (FLOW_HEIGHT, max(8, round(w * k)))
    a = (transform.resize(_sdf(base_mask), work, order=1, anti_aliasing=True) + SDF_CLIP) / (2 * SDF_CLIP)
    b = (transform.resize(_sdf(draft_mask), work, order=1, anti_aliasing=True) + SDF_CLIP) / (2 * SDF_CLIP)
    v, u = registration.optical_flow_tvl1(a, b, attachment=10, tightness=0.3, num_warp=10, num_iter=20)
    v = transform.resize(ndi.gaussian_filter(v, FLOW_SMOOTH), (h, w), order=1) / k
    u = transform.resize(ndi.gaussian_filter(u, FLOW_SMOOTH), (h, w), order=1) / k
    return v, u


def _apply_flow(img: np.ndarray, v: np.ndarray, u: np.ndarray) -> np.ndarray:
    from scipy import ndimage as ndi
    h, w = v.shape
    rr, cc = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    out = np.empty_like(img)
    for ch in range(img.shape[2]):
        out[..., ch] = ndi.map_coordinates(img[..., ch], [rr + v, cc + u], order=1, mode="constant", cval=0)
    return out


# --- 3. Skin and mask ---------------------------------------------------------

class Skin:
    """The chroma (a*, b*) model of skin: the histogram mode of a figure's
    pixels and its spread. A figure without enough mid-lightness pixels has
    no skin (``like`` is all False)."""

    def __init__(self, labimg: np.ndarray, mask: np.ndarray):
        from scipy import ndimage as ndi
        self.empty = True
        self.centre = np.zeros(2)
        self.icov = np.eye(2)
        self.lo, self.hi = 0.0, 99.0
        self.lum_median, self.lum_p10 = 0.0, 0.0
        lum = labimg[mask][:, 0]
        ab = labimg[mask][:, 1:]
        mid = (lum > 25) & (lum < 97)
        ab, lum = ab[mid], lum[mid]
        if len(ab) < 50:
            return
        hist, xe, ye = np.histogram2d(ab[:, 0], ab[:, 1], bins=60, range=[[-20, 60], [-20, 70]])
        hist = ndi.gaussian_filter(hist, 1.0)
        if hist.max() <= 0:
            return
        i, j = np.unravel_index(np.argmax(hist), hist.shape)
        centre = np.array([(xe[i] + xe[i + 1]) / 2, (ye[j] + ye[j + 1]) / 2])
        close = np.linalg.norm(ab - centre, axis=1) < 8
        if close.sum() < 10:
            return
        near = ab[close]
        self.centre = near.mean(0)
        cov = (np.cov(near.T) if len(near) > 1 else np.zeros((2, 2))) + np.eye(2) * 1.0
        self.icov = np.linalg.inv(cov * 1.5)
        self.lo = float(np.percentile(lum[close], 2)) - 8
        self.lum_median = float(np.median(lum[close]))
        self.lum_p10 = float(np.percentile(lum[close], 10))
        self.empty = False

    def recentred(self, labimg: np.ndarray, head: np.ndarray, figure: np.ndarray,
                  max_shift: float = 15) -> "Skin":
        """The same spread around the draft's own skin mode: its ``head``'s
        (a bald head, the spike's rule) when that mode is within
        ``max_shift`` and skin-bright (median L at least this model's 10th
        percentile — a haired head's mode is the hair: Kai's worn backs
        2026-11-12, hair chroma (2.5, 4.9) against his skin (10.2, 22.0)),
        else the mode of the whole draft ``figure`` when it is within
        ``max_shift`` (a draft whose skin is warmer than its base's), else
        this model."""
        out = Skin.__new__(Skin)
        out.empty, out.icov, out.hi = self.empty, self.icov, 99.0
        out.centre, out.lo = self.centre, self.lo
        out.lum_median, out.lum_p10 = self.lum_median, self.lum_p10
        if self.empty:
            return out
        for region, bright in ((head, True), (figure, False)):
            other = Skin(labimg, region)
            if other.empty or np.linalg.norm(other.centre - self.centre) >= max_shift:
                continue
            if bright and other.lum_median < self.lum_p10:
                continue
            out.centre, out.lo = other.centre, min(self.lo, other.lo)
            break
        return out

    def like(self, labimg: np.ndarray) -> np.ndarray:
        if self.empty:
            return np.zeros(labimg.shape[:2], bool)
        d = labimg[..., 1:] - self.centre
        m = np.einsum("...i,ij,...j->...", d, self.icov, d)
        lum = labimg[..., 0]
        return (np.sqrt(m) < SKIN_MAHA) & (lum > self.lo) & (lum < self.hi)


def _garment_mask(base: np.ndarray, dw: np.ndarray, base_mask: np.ndarray, dw_mask: np.ndarray,
                  skin_b: Skin, skin_d: Skin, *, opening: int = 1,
                  min_component: int = 150) -> Tuple[np.ndarray, np.ndarray]:
    """``(mask, ΔE map)`` of the garment in the registered draft ``dw``;
    ``opening`` / ``min_component``: the ``RULES`` entry's."""
    from scipy import ndimage as ndi
    lb, ld = _lab(base), _lab(dw)
    lbs, lds = _blur3(lb, 1.5), _blur3(ld, 1.5)
    de = np.linalg.norm(lbs - lds, axis=-1)
    tex = np.abs(_local_std(ld[..., 0]) - _local_std(lb[..., 0]))
    cand = dw_mask & ((de > DE_GARMENT) | (tex > TEXTURE_DIFF))
    skin_draft = skin_d.like(lds)
    # Draft skin over base skin is never garment (arm drift, tone shift).
    cand &= ~(skin_draft & skin_b.like(lbs) & (de < 30) & (tex < TEXTURE_DIFF))
    # Draft skin OUTSIDE the base silhouette is limb drift; inside it a bare
    # part may replace a base garment (shoes -> bare feet) and stays.
    cand &= ~(skin_draft & ~base_mask)
    m = ndi.binary_opening(cand, _disk(opening)) if opening else cand
    m = ndi.binary_closing(m, _disk(4))
    lab_, n = ndi.label(m)
    if n:
        sizes = ndi.sum(m, lab_, range(1, n + 1))
        keep = np.zeros(n + 1, bool)
        keep[1:] = sizes >= max(min_component, 0.02 * sizes.max())
        m = keep[lab_]
    # Fill small holes only (the skin between straps stays).
    holes = ndi.binary_fill_holes(m) & ~m
    hl, hn = ndi.label(holes)
    if hn:
        hs = ndi.sum(holes, hl, range(1, hn + 1))
        small = np.zeros(hn + 1, bool)
        small[1:] = hs < 2500
        m |= small[hl]
    return m & dw_mask, de


def _flare(aligned: np.ndarray, aligned_mask: np.ndarray, base_mask: np.ndarray, skin_d: Skin) -> np.ndarray:
    """The draft's flare (a skirt) on the aligned draft: non-skin draft
    figure outside the base silhouette, in the hip-to-knee band, central,
    near the base or between its legs — only in rows where the draft covers
    the WHOLE leg gap of the base (a skirt bridges it; trouser legs that
    merely stand closer than the base's, and sleeve cuffs, do not)."""
    from scipy import ndimage as ndi
    t, b, left, right = _bbox(base_mask)
    height = b - t
    band = np.zeros_like(base_mask)
    band[t + int(FLARE_BAND[0] * height):t + int(FLARE_BAND[1] * height)] = True
    near = ndi.distance_transform_edt(~base_mask) < 0.04 * height
    cs = np.cumsum(base_mask, axis=1)
    between = (cs > 0) & (cs < cs[:, -1:]) & ~base_mask
    cx = (left + right) / 2
    central = np.zeros_like(base_mask)
    central[:, max(0, int(cx - 0.17 * height)):int(cx + 0.17 * height)] = True
    gap = np.zeros_like(base_mask)
    ci = int(round(cx))
    for y in range(t + int(FLARE_BAND[0] * height), t + int(FLARE_BAND[1] * height)):
        if base_mask[y, ci]:
            continue
        row = base_mask[y]
        lft = np.nonzero(row[:ci])[0]
        rgt = np.nonzero(row[ci:])[0]
        if len(lft) and len(rgt):
            gap[y, lft[-1] + 1:ci + rgt[0]] = True
    lab_aligned = _lab(aligned)
    not_skin = ~skin_d.like(lab_aligned) & aligned_mask
    rows_gap = gap.sum(1)
    bridged = (rows_gap > 0) & ((gap & not_skin).sum(1) >= 0.95 * rows_gap)
    bridged = ndi.binary_opening(bridged, np.ones(9, bool))
    flare = (aligned_mask & ~skin_d.like(lab_aligned) & ~ndi.binary_dilation(base_mask, _disk(4)) & band & central
             & (near | between) & bridged[:, None])
    return ndi.binary_opening(flare, _disk(2))


# --- 4. Seam and 5. composite -------------------------------------------------

def _seam_colour_match(base: np.ndarray, dw: np.ndarray, mask: np.ndarray, skin_b: Skin, skin_d: Skin,
                       band: float = 10.0) -> Tuple[np.ndarray, float]:
    """The draft's Lab shifted toward the base only in a band inside the mask
    edge, by the local base-minus-draft offset on a skin ring just outside it
    (both images skin there). Returns ``(adjusted draft, median ring offset ΔE)``."""
    from scipy import ndimage as ndi
    from skimage import color
    lb, ld = _lab(base), _lab(dw)
    ring = ndi.binary_dilation(mask, _disk(6)) & ~mask & skin_b.like(lb) & skin_d.like(ld)
    if ring.sum() < 20:
        return dw, 0.0
    weight = ndi.gaussian_filter(ring.astype(float), 12)
    out = ld.copy()
    fade = np.exp(-ndi.distance_transform_edt(mask) / band) * mask
    for i in range(3):
        off = ndi.gaussian_filter((lb[..., i] - ld[..., i]) * ring, 12) / np.maximum(weight, 1e-3)
        off = np.where(weight > 1e-3, off, 0)
        out[..., i] = ld[..., i] + off * fade
    res = dw.copy()
    res[..., :3] = np.clip(color.lab2rgb(out), 0, 1) * 255
    return res, float(np.median(np.linalg.norm((lb - ld)[ring], axis=-1)))


def _blend(base: np.ndarray, dw: np.ndarray, mask: np.ndarray, flare_rgba: np.ndarray,
           flare: np.ndarray) -> np.ndarray:
    """The base with the draft inside the (1.2 px feathered) mask and the
    flare on top; alpha: the base's, raised where the mask adds figure."""
    from scipy import ndimage as ndi
    m = ndi.gaussian_filter(mask.astype(float), 1.2)
    m = np.where(ndi.binary_dilation(mask, _disk(2)), m, 0)
    out = base.copy()
    out[..., :3] = base[..., :3] * (1 - m[..., None]) + dw[..., :3] * m[..., None]
    out[..., 3] = base[..., 3] * (1 - m) + dw[..., 3] * m
    out[..., 3] = np.where(mask & (base[..., 3] > FIGURE_ALPHA), np.maximum(out[..., 3], base[..., 3]), out[..., 3])
    if flare.any():
        f = ndi.gaussian_filter(flare.astype(float), 1.0)
        out[..., :3] = out[..., :3] * (1 - f[..., None]) + flare_rgba[..., :3] * f[..., None]
        out[..., 3] = np.maximum(out[..., 3], flare_rgba[..., 3] * f)
    return out


# --- Measures -----------------------------------------------------------------

def _seam_de(img: np.ndarray, mask: np.ndarray, d_lab: np.ndarray, skin_d: Skin, k: int = 3) -> Optional[float]:
    """Median CIEDE2000 between the pixel ``k`` px outside and ``k`` px
    inside the mask edge where the registered draft is skin on both sides
    (the edge cuts skin, not a garment edge); None below 10 pairs."""
    from scipy import ndimage as ndi
    from skimage import color
    if not mask.any():
        return None
    lab_i = _lab(img)
    outside_d, (oi, oj) = ndi.distance_transform_edt(~mask, return_indices=True)
    outer = (outside_d > k - 0.5) & (outside_d <= k + 0.5)
    ys, xs = np.nonzero(outer)
    ny, nx = oi[ys, xs], oj[ys, xs]
    dy, dx = ny - ys, nx - xs
    n = np.maximum(np.hypot(dy, dx), 1e-6)
    iy = np.clip(np.round(ny + dy / n * (k - 1)).astype(int), 0, mask.shape[0] - 1)
    ix = np.clip(np.round(nx + dx / n * (k - 1)).astype(int), 0, mask.shape[1] - 1)
    skin = skin_d.like(d_lab)
    ok = mask[iy, ix] & skin[ys, xs] & skin[iy, ix]
    if ok.sum() < 10:
        return None
    return float(np.median(color.deltaE_ciede2000(lab_i[ys[ok], xs[ok]], lab_i[iy[ok], ix[ok]])))


def _cells(rgba: np.ndarray, size: Tuple[int, int]) -> Tuple[np.ndarray, np.ndarray]:
    """``(Lab cells, figure cells)`` of an RGBA array on neutral grey,
    box-resampled to ``size`` (w, h)."""
    from PIL import Image
    im = Image.fromarray(np.clip(np.round(rgba), 0, 255).astype(np.uint8), "RGBA")
    flat = Image.new("RGBA", im.size, GREY + (255,))
    flat.alpha_composite(im)
    rgb = np.asarray(flat.convert("RGB").resize(size, Image.BOX), dtype=np.float64)
    alpha = np.asarray(im.getchannel("A").resize(size, Image.BOX))
    return _lab(np.concatenate([rgb, np.full(rgb.shape[:2] + (1,), 255.0)], -1)), alpha >= 128


def put_on(base: np.ndarray, draft: np.ndarray, result: np.ndarray, *, work_height: Optional[int] = PUT_ON_WORK_HEIGHT,
           head_share: float = PUT_ON_HEAD_SHARE, region_min: float = PUT_ON_MIN_REGION,
           dilate: int = PUT_ON_DILATE) -> Dict[str, Any]:
    """The put-on score of Task 11f of ``result`` against ``base`` and the
    REGISTERED ``draft`` — three RGBA arrays in the base frame (module
    docstring). ``{"score", "region", "base_de", "draft_de"}``; a garment
    region below ``PUT_ON_MIN_REGION`` has score 0.0 and ``nothing`` True."""
    from scipy import ndimage as ndi
    h, w = base.shape[:2]
    size = (w, h) if work_height is None else (max(1, round(w * work_height / float(h))), work_height)
    lab_b, fig_b = _cells(base, size)
    lab_d, fig_d = _cells(draft, size)
    lab_r, _fig_r = _cells(result, size)
    rows = np.nonzero(fig_b.any(axis=1))[0]
    if rows.size == 0:
        return {"score": 0.0, "region": 0.0, "nothing": True}
    head = int(rows[0]) + int(round(head_share * (rows[-1] - rows[0] + 1)))
    region = fig_d & (np.linalg.norm(lab_d - lab_b, axis=-1) > PUT_ON_REGION_DE)
    if PUT_ON_OPEN:
        region = ndi.binary_opening(region, iterations=PUT_ON_OPEN)
    region[:head] = False
    share = float(region.sum()) / max(int(fig_b.sum()), 1)
    if share < region_min or not region.any():
        return {"score": 0.0, "region": round(share, 5), "nothing": True}
    if dilate:
        region = ndi.binary_dilation(region, iterations=dilate)
        region[:head] = False
    to_base = float(np.linalg.norm(lab_r - lab_b, axis=-1)[region].mean())
    to_draft = float(np.linalg.norm(lab_r - lab_d, axis=-1)[region].mean())
    score = to_base / (to_base + to_draft) if to_base + to_draft > 0 else 0.5
    return {"score": round(score, 4), "region": round(share, 4), "base_de": round(to_base, 2),
            "draft_de": round(to_draft, 2)}


# --- The composite ------------------------------------------------------------

def composite_arrays(base: np.ndarray, draft: np.ndarray, *, rule: str = "outfit"
                     ) -> Tuple[np.ndarray, Dict[str, Any]]:
    """``(composite RGBA array in the base frame, record)`` of a draft (RGBA
    float 0..255, any size) put onto a base view (RGBA float 0..255) — the
    module docstring; ``rule``: a ``RULES`` key ("outfit" / "piece"). Pure
    and deterministic. ``CompositeError`` when the base has no figure or the
    rule is unknown; a draft without a figure comes back as the base with
    ``ok`` False (``NO_FIGURE``)."""
    from scipy import ndimage as ndi
    started = time.perf_counter()
    if rule not in RULES:
        raise CompositeError(f"unknown composite rule {rule!r}")
    spec = RULES[rule]
    base = np.asarray(base, dtype=np.float64)
    draft = np.asarray(draft, dtype=np.float64)
    bm = figure_mask(base)
    if not bm.any():
        raise CompositeError("the base view has no figure")
    record: Dict[str, Any] = {"version": VERSION, "rule": rule, "iou_min": IOU_MIN, "coverage_min": COVERAGE_MIN}
    if not figure_mask(draft).any():
        return base.copy(), {**record, "ok": False, "reasons": [NO_FIGURE], "iou": 0.0,
                             "coverage": {"score": 0.0, "region": 0.0, "nothing": True}}
    shape = bm.shape
    aligned, alignment = _similarity(draft, shape, bm)
    aligned_mask = figure_mask(aligned)
    lb = _lab(base)
    skin_b = Skin(lb, bm & (base[..., 3] > 240))
    head = aligned_mask & (aligned[..., 3] > 240)
    top, bottom, _l, _r = _bbox(aligned_mask)
    head[top + int(0.09 * (bottom - top)):] = False
    skin_d = skin_b.recentred(_lab(aligned), head, aligned_mask & (aligned[..., 3] > 240))
    flare_aligned = _flare(aligned, aligned_mask, bm, skin_d)
    v, u = _shape_flow(bm, _largest(aligned_mask & ~flare_aligned))
    dw = _apply_flow(aligned, v, u)
    dwm = figure_mask(dw)
    mask, _de = _garment_mask(base, dw, bm, dwm, skin_b, skin_d, opening=spec["opening"],
                              min_component=spec["min_component"])
    # The flare only where it touches the garment.
    flare = flare_aligned & ~bm
    fl, fn = ndi.label(flare)
    if fn:
        touch = np.unique(fl[ndi.binary_dilation(mask, _disk(3)) & flare])
        flare = np.isin(fl, touch[touch > 0])
    matched, ring_offset = _seam_colour_match(base, dw, mask, skin_b, skin_d)
    out = _blend(base, matched, mask, aligned, flare)
    # The registered draft as the composite sees it: the warped draft, the flare unwarped.
    registered = np.where(flare[..., None], aligned, dw)
    cm = figure_mask(out)
    magnitude = np.hypot(v, u)[bm]
    coverage = put_on(base, registered, out, **spec["put_on"])
    seam = _seam_de(out, mask, _lab(dw), skin_d)
    record.update({
        "alignment": alignment,
        "warp": {"mean_px": round(float(magnitude.mean()), 2), "p95_px": round(float(np.percentile(magnitude, 95)), 2),
                 "max_px": round(float(magnitude.max()), 2)},
        "mask_share": round(float(mask.sum() / bm.sum()), 4),
        "flare_px": int(flare.sum()),
        "coverage": coverage,
        "seam_de": None if seam is None else round(seam, 2),
        "ring_offset_de": round(ring_offset, 2),
        "iou": round(iou(dwm & ~flare, bm), 4),
        "composite_iou": round(iou(cm, bm), 4),
        "drift_px": round(contour_drift(cm, bm), 2),
    })
    reasons = check(record)
    record.update(ok=not reasons, reasons=reasons, runtime_s=round(time.perf_counter() - started, 2))
    return out, record


def check(record: Dict[str, Any]) -> List[str]:
    """The refusal reasons of a composite record (empty = it passes)."""
    reasons = []
    coverage = record.get("coverage") or {}
    if coverage.get("nothing"):
        limit = RULES.get(str(record.get("rule") or "outfit"), RULES["outfit"])["put_on"]["region_min"]
        reasons.append(f"{NOTHING_TO_PUT_ON} (garment region {float(coverage.get('region') or 0.0):.4f} < {limit})")
    elif float(coverage.get("score") or 0.0) < COVERAGE_MIN:
        reasons.append(f"{NOT_COVERED} (coverage {float(coverage.get('score') or 0.0):.3f} < {COVERAGE_MIN})")
    if float(record.get("iou") or 0.0) < IOU_MIN:
        reasons.append(f"{NOT_ALIGNED} (IoU {float(record.get('iou') or 0.0):.3f} < {IOU_MIN})")
    return reasons


# --- Files --------------------------------------------------------------------

def _guard_thread() -> None:
    """``CompositeError`` on the event loop thread or a GPU-queue worker:
    seconds of CPU there would stall the server or hold a GPU slot."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise CompositeError("the view composite must not run on the event loop")
    if threading.current_thread().name.startswith("ProviderQueue-"):
        raise CompositeError("the view composite must not run inside a GPU-queue worker")


def load_rgba(path: Path) -> np.ndarray:
    """An image file as an RGBA float array — its own matte when it carries
    one, else the mesh-input matte (``base_body.cut_out``)."""
    from app.core.base_body import cut_out
    return np.asarray(cut_out(Path(path)), dtype=np.float64)


def to_image(rgba: np.ndarray, background: Optional[Tuple[int, int, int]] = None):
    """A PIL image of an RGBA array: RGBA, or flattened RGB on ``background``."""
    from PIL import Image
    image = Image.fromarray(np.clip(np.round(rgba), 0, 255).astype(np.uint8), "RGBA")
    if background is None:
        return image
    flat = Image.new("RGBA", image.size, tuple(background) + (255,))
    flat.alpha_composite(image)
    return flat.convert("RGB")


def compose(base_view: Path, draft: Path, target: Path, *, rule: str = "outfit",
            background: Optional[Tuple[int, int, int]] = None) -> Dict[str, Any]:
    """Composite ``draft`` onto ``base_view`` and write the result to
    ``target`` (PNG, in the base view's frame; RGBA, or flattened onto
    ``background``) — written whether or not it passes, the caller stages it;
    ``rule``: "outfit" (a dressed view) or "piece" (a worn back).
    Returns the record (``composite_arrays``). ``CompositeError`` on the
    event loop / a GPU-queue worker (``_guard_thread``) or for a base view
    without a figure."""
    _guard_thread()
    out, record = composite_arrays(load_rgba(base_view), load_rgba(draft), rule=rule)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    to_image(out, background).save(tmp, format="PNG")
    tmp.replace(target)
    logger.info("View composite %s onto %s: %s (IoU %s, coverage %s, mask %s, seam ΔE %s, %.2f s)",
                Path(draft).name, Path(base_view).name, "ok" if record["ok"] else "; ".join(record["reasons"]),
                record.get("iou"), (record.get("coverage") or {}).get("score"), record.get("mask_share"),
                record.get("seam_de"), record.get("runtime_s") or 0.0)
    return record


def summary(record: Dict[str, Any]) -> str:
    """One attempt's numbers in a refusal text."""
    coverage = record.get("coverage") or {}
    return (f"IoU {float(record.get('iou') or 0.0):.3f}, coverage {float(coverage.get('score') or 0.0):.3f}"
            f" (region {float(coverage.get('region') or 0.0):.3f}), mask {float(record.get('mask_share') or 0.0):.3f}"
            + (f": {'; '.join(record.get('reasons') or [])}" if record.get("reasons") else ""))


def refusal(what: str, records: Iterable[Dict[str, Any]]) -> str:
    """The refusal text of a view whose every draft failed its composite:
    ``what`` ("Dressed back", "worn back") and each attempt's numbers
    against the limits."""
    parts = [f"draft {n}: {summary(r)}" for n, r in enumerate(records, 1)]
    return (f"{what} refused — the composite of the draft failed (IoU >= {IOU_MIN}, coverage >= "
            f"{COVERAGE_MIN}): " + " | ".join(parts))
