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
   the aligned draft (``_shape_flow``). The flare of a skirt (the draft
   bridging the base's leg gap in the hip-to-ankle band ``FLARE_BAND``,
   outside the base figure) is left out of the flow and pasted unwarped —
   trouser legs and sleeve cuffs are not flare (only a row whose leg gap the
   draft covers to 95 % counts, ``_flare``). It takes no skin test (fix
   round 2 of Task 11g): a skin-coloured skirt is flare too — Ylva's brown
   leather skirt read as skin, was left in the flow and warped into trouser
   legs.
3. MASK — the garment: the registered draft's figure pixels that differ
   from the base by colour (``DE_GARMENT``, Lab ΔE76 after a light blur) or
   texture (local L-contrast differing by ``TEXTURE_DIFF``), minus skin:
   skin is modelled from the BASE's own figure (``Skin``: the chroma mode and
   its spread) and re-centred on the draft — on the skin both share
   (``_shared_skin``: base skin the aligned draft repeats within
   ``SHARED_SKIN_DE``) when there is enough of it, else on the draft's head,
   never on the whole figure (a figure mostly in leather has the leather as
   its mode); draft skin over base skin of the same lightness
   (``SKIN_SAME_DL``) is never garment — a skin-coloured garment over skin is
   (fix round 2); draft skin outside the base silhouette is limb drift.
   Opened, closed, specks dropped, small holes filled (``_garment_mask``).
4. SEAM — colour matching at the seam only: inside a band along the mask's
   edge the draft is shifted toward the base by the local offset measured
   on the skin ring just outside it (``_seam_colour_match``).
5. COMPOSITE — the base everywhere, the (seam-matched) draft inside the
   mask and the flare (grown ``FLARE_FILL`` px back to the base outline),
   feathered as ONE region; the base's alpha unless the mask adds figure
   (``_blend``).

The record (``composite_arrays`` / ``compose``): ``alignment`` (scale, dx,
dy in base px), ``warp`` (mean / p95 / max displacement in base px inside
the base figure), ``mask_share`` (mask / base figure), ``flare_px``,
``coverage`` (the put-on score of Task 11f, below), ``seam_de`` (median
CIEDE2000 across the mask edge where the draft is skin on both sides),
``ring_offset_de``, ``iou`` (the ALIGNMENT IoU, below), ``iou_full`` (the
registered draft figure against the base figure everywhere — the check
until fix round 2, kept for the record), ``composite_iou`` / ``drift_px`` (the composite's
figure against the base's: IoU, mean outline distance), ``runtime_s``.

The CHECKS (``ok`` / ``reasons``):

* ``iou >= IOU_MIN`` (0.93) — the draft could be aligned onto the base.
  Measured OUTSIDE the garment (Ruling C3, fix round 2 of Task 11g:
  ``alignment_iou``): the registered draft figure (flare left out) against
  the base figure, the garment mask + flare grown by ``IOU_MARGIN`` px left
  out, disagreements thinner than ``IOU_TOLERANCE`` px opened away. A
  garment widens the silhouette by design — a long skirt or loose sleeves
  are no misalignment — while an arm, a leg or the head that stand
  elsewhere are. Measured 2026-11-13 on the 16 stored drafts of Anima
  Divide: 0.9313 (Lirien) .. 1.0, Ylva's two drafts 0.9643 / 0.9510 (the
  whole-figure IoU refused them at 0.902 / 0.901); refused: the drafts with
  an arm raised 30° of Ylva (0.85 / 0.88), Lirien 0.835 and Kai 0.929, her
  side view as the draft of her back 0.495. KNOWN LIMIT: an arm raised
  ~30° on a slim figure can be absorbed by the warp (Glut 0.934, Rosi
  0.976 — the whole-figure IoU passed them as well).
* ``coverage >= COVERAGE_MIN`` (0.5) — the composite put on what the draft
  wears: the Task 11f put-on score of the composite against the base and the
  REGISTERED draft (``_put_on``: the draft cells differing from the base by
  more than ``PUT_ON_REGION_DE`` at ``PUT_ON_WORK_HEIGHT`` rows, opened,
  head rows dropped, dilated; score = base_de / (base_de + draft_de) inside
  it — 0 = the composite is the bare base, 1 = it is the draft). 11f
  measured the bare fits 0.052 .. 0.127, the dressed ones 0.681 .. 0.956.
  A garment region below the rule's ``region_min`` (outfit 0.03 of the base
  figure, piece 0.002) means the draft wears nothing that shows in this
  view: see EMPTY below.

EMPTY (fix round 1 of Task 11g): a draft that lines up with the base
(``iou >= IOU_MIN``) but wears nothing that shows in this view — a necklace
or a front-only detail seen from behind — is NOT refused. The view is the
base view UNCHANGED (``empty`` True, ``coverage`` score None = n/a,
``mask_share`` 0); the sidecar says ``"composite": "empty"`` and keeps the
numbers under ``composite_record`` (``sidecar_fields``). A draft that does
not line up is refused as before: its "nothing" is no measurement.

``compose(mask_target=…)`` also writes the composite's SUPPORT — every pixel
it may have changed (the garment mask and the flare grown by
``SUPPORT_GROW`` px: the feathered blend reaches 2 px past the mask, the
flare's blur 3) — as a grey PNG: outside it the composite IS the base, so a
gate that compares it with the base (``garment_gates.worn_gate``'s head
share) leaves the support out.

HEAD (Ruling A21, Task 11g-fix4b): a dressed view of a shape whose head
differs from the plain views (a bald shape on haired plain views, D4 — the
caller measures it: ``base_body.head_match`` of the dressed front) is
composited with ``head=True``: everything above the draft's shoulder line
(``_head_zone``) is the draft — its head, neck and shoulder tops, the flow
there on the draft's own outline, the base's figure (its hair) gone — so the
result is never a bald head stretched into the haired outline. The record
gains ``head`` with the zone and the seam ΔE along its neck line. Without
``head`` the composite is byte for byte what it was.

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
VERSION = 3
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
#: Lab L difference (after the 1.5 px blur) under which draft skin over base skin stays skin (``_garment_mask``).
SKIN_SAME_DL = 15.0
#: Chroma Mahalanobis radius of "skin-like".
SKIN_MAHA = 3.0
#: Alpha above which a pixel belongs to a figure.
FIGURE_ALPHA = 127
#: Hip-to-ankle band (share of the base figure's height from its top) where a skirt can flare (to 0.78 =
#: the knee until fix round 2 of Task 11g: Ylva's calf-long wrap skirt warped into trouser legs below it).
FLARE_BAND = (0.40, 0.92)
#: Px the pasted flare grows back toward the base outline (``_composite``).
FLARE_FILL = 6
#: Lab ΔE76 under which an aligned draft pixel over the base's (eroded) skin still is that skin
#: (``_shared_skin``), and the share of the draft figure such pixels need to set the draft's skin mode.
SHARED_SKIN_DE = 15.0
SHARED_SKIN_MIN = 0.02
#: The alignment IoU (registered draft figure / base figure, outside the garment — ``alignment_iou``) a
#: composite needs.
IOU_MIN = 0.93
#: Px (base frame) the garment mask + flare are grown by before the alignment IoU leaves them out (Ruling
#: C3), and the outline tolerance (px) under which a disagreement there does not count (``alignment_iou``).
IOU_MARGIN = 12
IOU_TOLERANCE = 2
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
#: Px the support (``compose(mask_target=…)``) grows the garment mask + flare by.
SUPPORT_GROW = 4
#: The HEAD ZONE of a composite that takes the draft's head (``compose(head=True)``, Ruling A21): a dressed
#: view of a shape whose head differs from the plain views (a bald shape on haired plain views, D4). The
#: neck is the narrowest row of the aligned draft in ``HEAD_NECK_BAND`` (shares of its height from its
#: top); the zone ends ``HEAD_ZONE_MARGIN`` below the first row under the neck at least
#: ``HEAD_SHOULDER_RATIO`` times the neck's width (the shoulder line), searched down to
#: ``HEAD_SHOULDER_SEARCH``. Ylva's bald back draft (2026-11-13): neck 56 px at 0.124..0.144, 2x at 0.17,
#: the haired base 150..175 px wide down to 0.17 (the hair) — the base's head and hair above the line
#: go, the draft's head, neck and shoulder tops come in, the flow there runs on the draft's own outline.
HEAD_NECK_BAND = (0.06, 0.22)
HEAD_SHOULDER_RATIO = 2.0
HEAD_SHOULDER_SEARCH = 0.32
HEAD_ZONE_MARGIN = 0.04
#: The sidecar value of an empty composite (module docstring).
EMPTY = "empty"
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


def alignment_iou(draft_mask: np.ndarray, base_mask: np.ndarray, garment: np.ndarray, *,
                  margin: Optional[int] = None, tolerance: Optional[int] = None) -> float:
    """The ALIGNMENT IoU (Ruling C3): the IoU of the registered draft figure and the base figure OUTSIDE the
    garment — ``garment`` (the draft's garment mask and flare, base frame) grown by ``margin`` px (default
    ``IOU_MARGIN``) — where a disagreement thinner than the outline ``tolerance`` (default
    ``IOU_TOLERANCE``: a binary opening with a disk of that radius) does not count. A garment legitimately
    changes the silhouette (a long wrap skirt widens it); what is left — head, hair, arms, hands, legs —
    must line up, like the head gate leaving the composite's support out (fix round 1). The tolerance:
    outside a garment that covers most of the figure the remainder is small, and the 1–2 px outline noise
    along its long edge alone cost Ylva's draft 0.04. ``1 - |disagreement| / |union|`` outside the garment;
    1.0 when nothing is left outside it."""
    from scipy import ndimage as ndi
    grow = IOU_MARGIN if margin is None else int(margin)
    keep = IOU_TOLERANCE if tolerance is None else int(tolerance)
    out = ndi.binary_dilation(garment, _disk(grow)) if grow > 0 and garment.any() else garment
    union = (draft_mask | base_mask) & ~out
    if not union.any():
        return 1.0
    differ = (draft_mask ^ base_mask) & ~out
    if keep > 0:
        differ = ndi.binary_opening(differ, _disk(keep))
    return float(1.0 - differ.sum() / union.sum())


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


def _head_zone(mask: np.ndarray) -> Tuple[np.ndarray, Dict[str, Any]]:
    """``(zone, record)`` of a figure mask (the ALIGNED draft's, in the base
    frame): the rows above its shoulder line (``HEAD_*`` constants) as a
    bool array of the mask's shape, and ``{"neck_row", "cut_row"}`` (base
    px) with ``cut`` = the zone's end as a share of the figure height."""
    t, b, _l, _r = _bbox(mask)
    height = b - t
    widths = mask.sum(1)
    lo, hi = t + int(HEAD_NECK_BAND[0] * height), t + max(int(HEAD_NECK_BAND[1] * height), int(HEAD_NECK_BAND[0] * height) + 1)
    neck = lo + int(np.argmin(widths[lo:hi]))
    limit = HEAD_SHOULDER_RATIO * max(int(widths[neck]), 1)
    end = t + int(HEAD_SHOULDER_SEARCH * height)
    wide = np.nonzero(widths[neck:end] >= limit)[0]
    shoulder = neck + int(wide[0]) if wide.size else end
    cut = min(b, shoulder + int(round(HEAD_ZONE_MARGIN * height)))
    zone = np.zeros_like(mask)
    zone[:cut] = True
    return zone, {"neck_row": neck, "cut_row": cut, "cut": round((cut - t) / height, 4)}


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
                  max_shift: float = 15, shared: Optional[np.ndarray] = None) -> "Skin":
        """The same spread around the draft's own skin mode: its ``head``'s
        (a bald head, the spike's rule) when that mode is within
        ``max_shift`` and skin-bright (median L at least this model's 10th
        percentile — a haired head's mode is the hair: Kai's worn backs
        2026-11-12, hair chroma (2.5, 4.9) against his skin (10.2, 22.0)),
        else the mode of the whole draft ``figure`` when it is within
        ``max_shift`` (a draft whose skin is warmer than its base's), else
        this model. ``shared`` (fix round 2 of Task 11g): the draft's pixels
        that still look like the base's skin there (``_shared_skin``) — tried
        between the head and the whole figure, because a figure whose mode
        is a skin-coloured garment (Ylva's brown leather wrap skirt
        2026-11-13: the whole figure's mode was the leather, so the skirt
        read as skin — no flare, the skirt warped into trouser legs) must
        not become the skin; it needs ``SHARED_SKIN_MIN`` of the figure."""
        out = Skin.__new__(Skin)
        out.empty, out.icov, out.hi = self.empty, self.icov, 99.0
        out.centre, out.lo = self.centre, self.lo
        out.lum_median, out.lum_p10 = self.lum_median, self.lum_p10
        if self.empty:
            return out
        regions = [(head, True)]
        if shared is not None and shared.sum() >= SHARED_SKIN_MIN * max(1, figure.sum()):
            regions.append((shared, False))
        regions.append((figure, False))
        for region, bright in regions:
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


def _shared_skin(lb: np.ndarray, la: np.ndarray, base_mask: np.ndarray, aligned: np.ndarray,
                 skin_b: "Skin") -> np.ndarray:
    """The aligned draft's pixels over the base's skin (the base figure eroded by 3 px, ``skin_b``) that
    differ from it by less than ``SHARED_SKIN_DE`` (Lab ΔE76) — the bare skin both images share (arms,
    shoulders, feet), whatever the garment's colour (``Skin.recentred``)."""
    from scipy import ndimage as ndi
    inner = ndi.binary_erosion(base_mask, _disk(3)) & (aligned[..., 3] > 240)
    return inner & skin_b.like(lb) & (np.linalg.norm(la - lb, axis=-1) < SHARED_SKIN_DE)


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
    # Draft skin over base skin is never garment (arm drift, tone shift) — unless it is much darker or
    # lighter than the base there (``SKIN_SAME_DL``): a skin-coloured garment (brown leather) is not skin.
    cand &= ~(skin_draft & skin_b.like(lbs) & (de < 30) & (tex < TEXTURE_DIFF)
              & (np.abs(lds[..., 0] - lbs[..., 0]) < SKIN_SAME_DL))
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


def _flare(aligned: np.ndarray, aligned_mask: np.ndarray, base_mask: np.ndarray) -> np.ndarray:
    """The draft's flare (a skirt) on the aligned draft: draft figure
    outside the base silhouette, in the hip-to-ankle band (``FLARE_BAND``),
    central, near the base or between its legs — only in rows where the
    draft covers the WHOLE leg gap of the base (a skirt bridges it; trouser
    legs that merely stand closer than the base's, and sleeve cuffs, do
    not). No skin test (fix round 2 of Task 11g): a skin-coloured skirt
    (brown leather) bridges the gap as well, and legs that stand together
    instead of apart leave the base's legs uncovered — the alignment IoU
    refuses that draft."""
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
    rows_gap = gap.sum(1)
    bridged = (rows_gap > 0) & ((gap & aligned_mask).sum(1) >= 0.95 * rows_gap)
    bridged = ndi.binary_opening(bridged, np.ones(9, bool))
    flare = (aligned_mask & ~ndi.binary_dilation(base_mask, _disk(4)) & band & central
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
           flare: np.ndarray, clear: Optional[np.ndarray] = None) -> np.ndarray:
    """The base with the draft inside the (1.2 px feathered) mask, the flare
    with it; alpha: the base's, raised where the mask adds figure.

    The flare and the mask are ONE pasted region, feathered once: each pixel
    takes the draft (``dw``) or the flare's source (``flare_rgba``), whichever
    region is nearer. Feathered apart, the two half-weights met where the
    flare touches the garment over a leg and left a half-transparent line
    down the skirt (alpha ~0.7, fix round 2 of Task 11g).

    ``clear`` (the head zone, Ruling A21): where the draft has no figure
    there the base's figure goes too — its alpha is not kept up."""
    from scipy import ndimage as ndi
    region = mask | flare
    source = dw
    if flare.any():
        nearer_flare = ndi.distance_transform_edt(~flare) < ndi.distance_transform_edt(~mask) if mask.any() \
            else np.ones_like(flare)
        source = np.where(nearer_flare[..., None], flare_rgba, dw)
    m = ndi.gaussian_filter(region.astype(float), 1.2)
    m = np.where(ndi.binary_dilation(region, _disk(2)), m, 0)
    out = base.copy()
    out[..., :3] = base[..., :3] * (1 - m[..., None]) + source[..., :3] * m[..., None]
    out[..., 3] = base[..., 3] * (1 - m) + source[..., 3] * m
    keep = mask & (base[..., 3] > FIGURE_ALPHA)
    if clear is not None:
        keep &= ~clear
    out[..., 3] = np.where(keep, np.maximum(out[..., 3], base[..., 3]), out[..., 3])
    if clear is not None:
        # The head zone IS the draft: no feathered remnant of the base's hair outline.
        inside = clear & region
        out[inside] = source[inside]
    return out


# --- Measures -----------------------------------------------------------------

def _seam_de(img: np.ndarray, mask: np.ndarray, d_lab: np.ndarray, skin_d: Skin, k: int = 3,
             rows: Optional[Tuple[int, int]] = None) -> Optional[float]:
    """Median CIEDE2000 between the pixel ``k`` px outside and ``k`` px
    inside the mask edge where the registered draft is skin on both sides
    (the edge cuts skin, not a garment edge); None below 10 pairs.
    ``rows`` (half-open): only the outer pixels in those rows (the neck
    line of a head zone, Ruling A21)."""
    from scipy import ndimage as ndi
    from skimage import color
    if not mask.any():
        return None
    lab_i = _lab(img)
    outside_d, (oi, oj) = ndi.distance_transform_edt(~mask, return_indices=True)
    outer = (outside_d > k - 0.5) & (outside_d <= k + 0.5)
    if rows is not None:
        outer[:max(0, rows[0])] = False
        outer[max(0, rows[1]):] = False
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

def composite_arrays(base: np.ndarray, draft: np.ndarray, *, rule: str = "outfit", head: bool = False
                     ) -> Tuple[np.ndarray, Dict[str, Any]]:
    """``(composite RGBA array in the base frame, record)`` of a draft (RGBA
    float 0..255, any size) put onto a base view (RGBA float 0..255) — the
    module docstring; ``rule``: a ``RULES`` key ("outfit" / "piece"). Pure
    and deterministic. ``CompositeError`` when the base has no figure or the
    rule is unknown; a draft without a figure comes back as the base with
    ``ok`` False (``NO_FIGURE``); an EMPTY one as the base with ``ok`` True.
    ``head``: take the draft's head as well (``_composite``)."""
    out, record, _support = _composite(base, draft, rule, take_head=head)
    return out, record


def _composite(base: np.ndarray, draft: np.ndarray, rule: str, *, take_head: bool = False
               ) -> Tuple[np.ndarray, Dict[str, Any], np.ndarray]:
    """``composite_arrays`` plus the support mask (module docstring; all
    False when the result is the base).

    ``take_head`` (Ruling A21): the draft wears another head than the base (a
    bald shape on haired plain views) — the HEAD ZONE (``_head_zone`` of
    the aligned draft: everything above its shoulder line) comes from the
    draft: the flow runs on the draft's own outline there (the base's hair
    does not stretch the draft's head and neck), the zone joins the mask
    and the base's figure goes where the draft has none (no hair left on a
    bald head). Never EMPTY (the head is put on). The record gains
    ``head`` = the zone's rows and the seam ΔE along its neck line
    (``neck_seam_de``); without it nothing changes."""
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
                             "coverage": {"score": 0.0, "region": 0.0, "nothing": True}}, np.zeros_like(bm)
    shape = bm.shape
    aligned, alignment = _similarity(draft, shape, bm)
    aligned_mask = figure_mask(aligned)
    zone, zone_record = _head_zone(aligned_mask) if take_head else (None, None)
    lb = _lab(base)
    skin_b = Skin(lb, bm & (base[..., 3] > 240))
    head = aligned_mask & (aligned[..., 3] > 240)
    top, bottom, _l, _r = _bbox(aligned_mask)
    head[top + int(0.09 * (bottom - top)):] = False
    la = _lab(aligned)
    skin_d = skin_b.recentred(la, head, aligned_mask & (aligned[..., 3] > 240),
                              shared=_shared_skin(lb, la, bm, aligned, skin_b))
    flare_aligned = _flare(aligned, aligned_mask, bm)
    flow_base = bm if zone is None else (bm & ~zone) | (aligned_mask & zone)
    v, u = _shape_flow(flow_base, _largest(aligned_mask & ~flare_aligned))
    dw = _apply_flow(aligned, v, u)
    dwm = figure_mask(dw)
    mask, _de = _garment_mask(base, dw, bm, dwm, skin_b, skin_d, opening=spec["opening"],
                              min_component=spec["min_component"])
    if zone is not None:
        # Every base pixel of the zone (its hair's soft matte edge and loose strands too) and the draft's figure.
        mask = (mask & ~zone) | (zone & (dwm | (base[..., 3] > 0) | (dw[..., 3] > 0)))
    # The flare only where it touches the garment. Pasted up to the base outline (``FLARE_FILL``): the 4 px
    # ring ``_flare`` leaves out is draft figure too — without it the base's background showed as a grey line
    # between the flare and the garment over the legs (Ylva 2026-11-13).
    flare = (ndi.binary_dilation(flare_aligned, _disk(FLARE_FILL)) if flare_aligned.any() else flare_aligned) \
        & aligned_mask & ~bm
    fl, fn = ndi.label(flare)
    if fn:
        touch = np.unique(fl[ndi.binary_dilation(mask, _disk(3)) & flare])
        flare = np.isin(fl, touch[touch > 0])
    matched, ring_offset = _seam_colour_match(base, dw, mask, skin_b, skin_d)
    out = _blend(base, matched, mask, aligned, flare, clear=zone)
    # The registered draft as the composite sees it: the warped draft, the flare unwarped.
    registered = np.where(flare[..., None], aligned, dw)
    cm = figure_mask(out)
    magnitude = np.hypot(v, u)[bm]
    coverage = put_on(base, registered, out, **spec["put_on"])
    seam = _seam_de(out, mask, _lab(dw), skin_d)
    if zone_record is not None:
        cut = zone_record["cut_row"]
        neck_seam = _seam_de(out, mask, _lab(dw), skin_d, rows=(cut - 1, cut + 7))
        record["head"] = {**zone_record, "neck_seam_de": None if neck_seam is None else round(neck_seam, 2)}
    record.update({
        "alignment": alignment,
        "warp": {"mean_px": round(float(magnitude.mean()), 2), "p95_px": round(float(np.percentile(magnitude, 95)), 2),
                 "max_px": round(float(magnitude.max()), 2)},
        "mask_share": round(float(mask.sum() / bm.sum()), 4),
        "flare_px": int(flare.sum()),
        "coverage": coverage,
        "seam_de": None if seam is None else round(seam, 2),
        "ring_offset_de": round(ring_offset, 2),
        "iou": round(alignment_iou(dwm & ~flare, bm, mask | flare), 4),
        "iou_full": round(iou(dwm & ~flare, bm), 4),
        "composite_iou": round(iou(cm, bm), 4),
        "drift_px": round(contour_drift(cm, bm), 2),
    })
    reasons = check(record)
    support = ndi.binary_dilation(mask | flare, _disk(SUPPORT_GROW))
    if coverage.get("nothing") and not reasons and zone is None:
        # EMPTY: nothing of the draft shows in this view — the base unchanged.
        out, support = base.copy(), np.zeros_like(bm)
        record.update(empty=True, coverage={**coverage, "score": None}, mask_share=0.0, flare_px=0, seam_de=None,
                      composite_iou=1.0, drift_px=0.0)
    record.update(ok=not reasons, reasons=reasons, runtime_s=round(time.perf_counter() - started, 2))
    return out, record, support


def check(record: Dict[str, Any]) -> List[str]:
    """The refusal reasons of a composite record (none = it passes). Nothing
    to put on refuses only a draft that does not line up (module docstring,
    EMPTY)."""
    reasons = []
    coverage = record.get("coverage") or {}
    aligned = float(record.get("iou") or 0.0) >= IOU_MIN
    if coverage.get("nothing"):
        if aligned:
            return reasons
        limit = RULES.get(str(record.get("rule") or "outfit"), RULES["outfit"])["put_on"]["region_min"]
        reasons.append(f"{NOTHING_TO_PUT_ON} (garment region {float(coverage.get('region') or 0.0):.4f} < {limit})")
    elif float(coverage.get("score") or 0.0) < COVERAGE_MIN:
        reasons.append(f"{NOT_COVERED} (coverage {float(coverage.get('score') or 0.0):.3f} < {COVERAGE_MIN})")
    if not aligned:
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
            background: Optional[Tuple[int, int, int]] = None,
            mask_target: Optional[Path] = None, head: bool = False) -> Dict[str, Any]:
    """Composite ``draft`` onto ``base_view`` and write the result to
    ``target`` (PNG, in the base view's frame; RGBA, or flattened onto
    ``background``) — written whether or not it passes, the caller stages it;
    ``rule``: "outfit" (a dressed view) or "piece" (a worn back).
    ``mask_target``: where the support goes (``write_support``).
    ``head``: the draft's head comes too (Ruling A21, ``_composite``).
    Returns the record (``composite_arrays``). ``CompositeError`` on the
    event loop / a GPU-queue worker (``_guard_thread``) or for a base view
    without a figure."""
    _guard_thread()
    out, record, support = _composite(load_rgba(base_view), load_rgba(draft), rule, take_head=head)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    to_image(out, background).save(tmp, format="PNG")
    tmp.replace(target)
    if mask_target is not None:
        write_support(support, mask_target)
    logger.info("View composite %s onto %s: %s (IoU %s, coverage %s, mask %s, seam ΔE %s, %.2f s)",
                Path(draft).name, Path(base_view).name, "ok" if record["ok"] else "; ".join(record["reasons"]),
                record.get("iou"), (record.get("coverage") or {}).get("score"), record.get("mask_share"),
                record.get("seam_de"), record.get("runtime_s") or 0.0)
    return record


def support_mask(base_view: Path, draft: Path, *, rule: str = "outfit") -> np.ndarray:
    """The support of the composite ``compose`` makes of ``draft`` on
    ``base_view`` (deterministic: the same as when it was made), for a
    stored composite without its support file. ``_guard_thread`` applies."""
    _guard_thread()
    return _composite(load_rgba(base_view), load_rgba(draft), rule)[2]


def write_support(support: np.ndarray, path: Path) -> None:
    """The support mask as a grey PNG (255 = may have changed), atomically."""
    from PIL import Image
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    Image.fromarray(np.where(support, 255, 0).astype(np.uint8), "L").save(tmp, format="PNG")
    tmp.replace(path)


def read_support(path: Path, size: Optional[Tuple[int, int]] = None) -> Optional[np.ndarray]:
    """A support PNG as a bool array (resized to ``size`` = (w, h) by nearest
    neighbour when given); None when the file is missing or unreadable."""
    from PIL import Image
    try:
        with Image.open(path) as im:
            grey = im.convert("L")
            if size is not None and grey.size != tuple(size):
                grey = grey.resize(tuple(size), Image.NEAREST)
            return np.asarray(grey) >= 128
    except (OSError, ValueError):
        return None


def is_empty(record: Any) -> bool:
    """Whether a composite record (or a sidecar's ``composite`` value) is EMPTY."""
    return record == EMPTY or (isinstance(record, dict) and record.get("empty") is True)


def sidecar_fields(record: Dict[str, Any]) -> Dict[str, Any]:
    """The sidecar fields of a composite: ``fit: "composite"`` and the record
    under ``composite`` — for an EMPTY one ``composite: "empty"`` and the
    record under ``composite_record`` (module docstring)."""
    if is_empty(record):
        return {"fit": "composite", "composite": EMPTY, "composite_record": record}
    return {"fit": "composite", "composite": record}


def summary(record: Dict[str, Any]) -> str:
    """One attempt's numbers in a refusal text."""
    coverage = record.get("coverage") or {}
    if is_empty(record):
        return (f"IoU {float(record.get('iou') or 0.0):.3f}, coverage n/a (region "
                f"{float(coverage.get('region') or 0.0):.4f}): {EMPTY} — the base view unchanged")
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
