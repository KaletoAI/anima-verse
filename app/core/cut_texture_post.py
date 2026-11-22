"""Texture from cut — the post-processing of a model's answer (plan
``docs/superpowers/plans/2026-11-20-template-cut-uv-texture.md``, Task 7). Pure numpy + PIL.

The model gets the clean island template (``garment_cut_texture.render_template``) and the item image, and answers
with a filled template — at its own size, a little shifted or scaled, too saturated. This module turns that answer
into an atlas on the piece's islands:

- ``resample_register`` — the answer resized back to the template frame (Lanczos), then ONE axis-aligned map
  template -> answer registered for the whole atlas (``register_raster``: the box fit, a scale grid, a pattern search —
  the search of ``app/blender/scripts/bake_register.register`` re-done raster-to-raster; the core does not import the
  Blender scripts), then the answer sampled through that map into the template frame (bilinear);
- ``gate`` — coverage / per-island coverage / IoU / spill against the island mask; a rejected answer falls back to the
  projection bake;
- ``cut_and_bleed`` — the model's outline eroded away, the islands regrown past their border (bleed padding, so
  mip-maps and bilinear lookups at a seam never read the white background);
- ``colour_match`` — a Lab mean/std transfer onto the item's fabric colours, the mean shift clamped at ``CLAMP_DE``;
- ``seam_continuity`` — the colour jump across the payload's seam pairs (a metric, not a gate);
- ``fabric_colour`` / ``delta_e00`` / ``detail_density`` / ``answer_gates`` — the item's base fabric colour (the
  template's pre-fill) and the answer gates against invented colours and content (user test 2026-11-21);
- ``fabric_patch`` / ``mirror_tile`` / ``tile_fill`` — the sleeves and the neckband filled from the front panel's
  plainest fabric window instead of the model's answer.

Frame: arrays are (rows, cols) with row 0 at the TOP (the template / atlas frame of ``islands.json``); a pixel
(i, j) covers ``[j, j + 1) x [i, i + 1)``, its centre is ``(j + 0.5, i + 0.5)``. A map is ``(sx, ox, sy, oy)``:
answer ``u = sx * x + ox``, ``v = sy * y + oy`` for a template point ``(x, y)``.
"""
from __future__ import annotations


import numpy as np
from PIL import Image

from app.core import garment_matte

#: The gate (``gate``): minimum coverage of the mask, minimum coverage of the worst island, minimum IoU, and the most
#: foreground allowed beyond ``SPILL_CM`` outside the mask (as a share of the mask area).
CUT_GATE = {"iou": 0.90, "coverage": 0.97, "island_coverage": 0.90, "spill": 0.03}
#: Foreground = the largest channel distance from white above this.
WHITE_TOL = 24
#: Bleed padding grown around every island (``cut_and_bleed``), in cm of the atlas.
BLEED_CM = 1.0
#: ``fill_pockets``: background this close to the islands + their bleed is filled too (nearest colour), and every
#: background pocket they enclose — the round notch between two leg islands at the crotch stayed white past the 1 cm
#: bleed (Lirien's trousers, live 2026-11-22: ~25 px of white beside the seam, a white spot on the figure).
POCKET_CM = 3.0
#: Foreground closer than this to an island is a smeared edge, not spill.
SPILL_CM = 1.0
#: ``colour_match``: the largest mean shift (dE76).
CLAMP_DE = 25.0
#: Enters the cut atlas key (``csig``): bump when anything here changes the atlas. 2 (2026-11-20): the post-processing
#: runs per job (front / back) on its own islands and the two are composed (``garment_cut_texture.compose``). 3
#: (2026-11-21): the islands go pre-filled with the item's fabric colour, the answer gates (``ANSWER_GATE``) and the
#: sleeves / neckband filled from the front panel's fabric patch. 4 (2026-11-21): the foreground pieces apart from the
#: islands are dropped before the registration (``drop_strays``). 5 (2026-11-21): the back job runs in its zoom frame
#: (``garment_cut_texture.job_frame``) and is put back into the atlas frame before the compose; the foreground threshold
#: is the answer's own (``answer_white_tol``). 6 (2026-11-21): a PLAIN back view (``garment_cut_texture.PLAIN_BACK_DETAIL``)
#: gets no back job — the back panel is the front panel's fabric (``garment_cut_texture.fill_plain_back``). 7 (2026-11-21):
#: the erosion before the bleed is the answer's own outline width (``outline_rim``) — MiniMax keeps a ~5 px dark
#: outline that the fixed 3 px left as a line along every seam. 8 (2026-11-21): only a whole island thinner than the
#: erosion keeps its own pixels; a thin part of an island with a core (a jagged fitted border's teeth, a corner) is
#: regrown from the core — the teeth kept the light outline as bleed seed (``cut_and_bleed``). 9 (2026-11-22): the
#: composed atlas fills the background pockets near and between the islands (``fill_pockets``). 10 (2026-11-22): the
#: colour match never adds contrast (``SIGMA_GAIN_MAX``) and moves base onto base when item and answer both have plain
#: fabric (``colour_match`` ``base``); the erosion before the bleed also takes a soft shading band inside the outline
#: (``outline_rim``'s fine pass, ``RIM_MAX_PX`` 20).
POST_VERSION = 10
#: The version of ``draw_placket``'s painting: part of the assembly key of a piece with a placket (it is drawn onto
#: the composed atlas at assembly, never into the record's atlas — a changed placket costs no image job).
PLACKET_VERSION = 1

#: ``outline_rim``: the erosion is never less than ``RIM_MIN_PX`` (the template's ``LINE_PX`` outline plus a pixel of
#: registration) and never more than ``RIM_MAX_PX``. A pixel more than ``RIM_DE`` (dE76) from the median colour of the
#: band ``RIM_REF_PX`` deep inside the islands is off; a ring with ``RIM_SHARE`` more off pixels than that band still
#: belongs to the outline.
RIM_MIN_PX = 3
RIM_MAX_PX = 20
RIM_DE = 12.0
RIM_SHARE = 0.05
RIM_REF_PX = (10, 20)
#: The second, FINE pass of ``outline_rim``: a pixel more than ``RIM_DE_FINE`` from the median of the deeper band
#: ``RIM_REF_FINE_PX`` is off. MiniMax shades a plain piece's border with a soft darker band inside its outline (Lirien's
#: brown leather, live 2026-11-22, registered front answer: ring L* 26.5 / 21.4 / 21.4 / 23.0 / 24.3 / 25.1 / 25.7 /
#: 26.2 at 3..10 px against 27.6 at 16..25 px, dE 5..8 — under ``RIM_DE``, so the coarse pass stopped at 7 px and the
#: bleed drew the band out as dark rays along every seam). The fine band's own share sets the bar, so a weave or a
#: print that is off everywhere raises it and only a real border band counts.
RIM_DE_FINE = 5.0
RIM_REF_FINE_PX = (20, 30)

#: Registration (the constants of ``bake_register``; the grid is finer: the atlas is one big picture).
GRID = 256
REGION_PAD = 0.3
SCALES = (0.8, 0.9, 1.0, 1.12, 1.25)
SCALE_LIMIT = 1.6
OFFSET_LIMIT = 0.35
STEP_LOG, STEP_OFF = 0.08, 0.06
MIN_STEP_LOG, MIN_STEP_OFF = 0.004, 0.003
#: ``colour_match``: the share of item fabric pixels dropped at each end of the luminance range.
FABRIC_TRIM = 0.05
#: ``colour_match``: the floor of the atlas' per-channel std (a uniform island: the transfer is a mean shift).
SIGMA_FLOOR = 1.0
#: ``colour_match``: the per-channel contrast gain is at most this — the match never adds contrast the answer does
#: not have (2026-11-22, Lirien's leather: the item photo's shading gave a 7.7 x gain over a plain answer).
SIGMA_GAIN_MAX = 1.0


# ---------------------------------------------------------------------------------------------------------------- masks

def foreground(img: np.ndarray, tol: int = WHITE_TOL) -> np.ndarray:
    """Bool (h, w): the largest channel distance from white exceeds ``tol`` (default ``WHITE_TOL``)."""
    rgb = np.asarray(img)[..., :3].astype(np.int16)
    return (255 - rgb).max(-1) > tol


#: ``answer_white_tol``: the background of an answer is the canvas farther than this share of its side from the
#: template's islands; its ``BG_PERCENTILE`` distance from white plus ``BG_MARGIN`` is the answer's own foreground
#: threshold, never below ``MIN_WHITE_TOL`` nor above ``WHITE_TOL``.
BG_AWAY = 0.03
BG_PERCENTILE = 99.0
BG_MARGIN = 6
MIN_WHITE_TOL = 8


def answer_white_tol(arr: np.ndarray, mask: np.ndarray) -> int:
    """The foreground threshold of ONE answer (live run 2026-11-21, Tilda's cream back: P-H3 painted the pre-filled
    cream island LIGHTER — median distance from white 34, folds' highlights 14 — on a clean white background (99.99 %
    of it within 2), and the fixed ``WHITE_TOL`` 24 read 23 % of a fully painted panel as uncovered: "coverage 0.79").
    The background's ``BG_PERCENTILE`` distance (the canvas ``BG_AWAY`` of its side away from ``mask``) +
    ``BG_MARGIN``, clamped to ``MIN_WHITE_TOL`` .. ``WHITE_TOL``: a clean white background lets a light fabric count,
    a background with grey shadows or a stray drawing keeps the old threshold. ``WHITE_TOL`` without background."""
    mask = np.asarray(mask, bool)
    r = max(1, int(round(BG_AWAY * max(mask.shape))))
    away = ~dilate(mask, r)
    if not away.any():
        return WHITE_TOL
    dist = (255 - np.asarray(arr)[..., :3].astype(np.int16)).max(-1)[away]
    tol = int(np.ceil(np.percentile(dist, BG_PERCENTILE))) + BG_MARGIN
    return int(min(WHITE_TOL, max(MIN_WHITE_TOL, tol)))


def _shift_or(m: np.ndarray, di: int, dj: int) -> np.ndarray:
    """``m`` shifted by (di, dj), the uncovered border False."""
    h, w = m.shape
    out = np.zeros_like(m)
    out[max(0, di):h + min(0, di), max(0, dj):w + min(0, dj)] = m[max(0, -di):h - max(0, di),
                                                                  max(0, -dj):w - max(0, dj)]
    return out


def dilate(m: np.ndarray, r: int) -> np.ndarray:
    """Square (Chebyshev, 8-neighbour) dilation by ``r`` px; separable."""
    m = np.asarray(m, bool)
    r = int(r)
    if r <= 0:
        return m.copy()
    rows = m.copy()
    for d in range(1, r + 1):
        rows |= _shift_or(m, d, 0) | _shift_or(m, -d, 0)
    out = rows.copy()
    for d in range(1, r + 1):
        out |= _shift_or(rows, 0, d) | _shift_or(rows, 0, -d)
    return out


def erode(m: np.ndarray, r: int) -> np.ndarray:
    """Square erosion by ``r`` px (outside the canvas counts as empty)."""
    m = np.asarray(m, bool)
    if int(r) <= 0:
        return m.copy()
    pad = np.pad(~m, int(r), constant_values=True)
    return ~dilate(pad, int(r))[int(r):-int(r), int(r):-int(r)]


# ---------------------------------------------------------------------------------------------------------------- colour

_M = np.array([[0.4124564, 0.3575761, 0.1804375],
               [0.2126729, 0.7151522, 0.0721750],
               [0.0193339, 0.1191920, 0.9503041]])
_M_INV = np.linalg.inv(_M)
_WHITE = np.array([0.95047, 1.0, 1.08883])
_D = 6.0 / 29.0


def srgb_to_lab(rgb) -> np.ndarray:
    """sRGB 0..255 (..., 3) -> CIE L*a*b* (D65)."""
    c = np.asarray(rgb, np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = lin @ _M.T / _WHITE
    f = np.where(xyz > _D ** 3, np.cbrt(xyz), xyz / (3 * _D * _D) + 4.0 / 29.0)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def lab_to_srgb(lab) -> np.ndarray:
    """CIE L*a*b* (D65) -> sRGB 0..255 float (unclipped)."""
    lab = np.asarray(lab, np.float64)
    fy = (lab[..., 0] + 16) / 116
    f = np.stack([fy + lab[..., 1] / 500, fy, fy - lab[..., 2] / 200], -1)
    xyz = np.where(f > _D, f ** 3, 3 * _D * _D * (f - 4.0 / 29.0)) * _WHITE
    lin = np.clip(xyz @ _M_INV.T, 0.0, None)
    c = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)
    return c * 255.0


def delta_e(a_rgb, b_rgb) -> float:
    """CIE76 colour difference of two sRGB colours (0..255)."""
    return float(np.linalg.norm(srgb_to_lab(a_rgb) - srgb_to_lab(b_rgb)))


# ---------------------------------------------------------------------------------------------------------- registration

def _box(m):
    ys, xs = np.nonzero(m)
    return float(xs.min()), float(xs.max() + 1), float(ys.min()), float(ys.max() + 1)


class _Problem:
    """One registration: the answer's foreground on the search grid, the template mask sampled through a map."""

    def __init__(self, mask, fg):
        self.mask = np.asarray(mask, bool)
        self.fg = np.asarray(fg, bool)
        bx0, bx1, by0, by1 = _box(self.fg)
        self.bw, self.bh = bx1 - bx0, by1 - by0
        pad = REGION_PAD * max(self.bw, self.bh)
        step = (max(self.bw, self.bh) + 2 * pad) / GRID
        ncol = int(np.ceil((self.bw + 2 * pad) / step))
        nrow = int(np.ceil((self.bh + 2 * pad) / step))
        self.u = bx0 - pad + (np.arange(ncol) + 0.5) * step
        self.v = by0 - pad + (np.arange(nrow) + 0.5) * step
        self.want = self._sample(self.fg, self.u, self.v)

    @staticmethod
    def _sample(m, xs, ys):
        h, w = m.shape
        jj, ii = np.floor(xs).astype(int), np.floor(ys).astype(int)
        okj, oki = (jj >= 0) & (jj < w), (ii >= 0) & (ii < h)
        sub = m[np.clip(ii, 0, h - 1)][:, np.clip(jj, 0, w - 1)]
        return sub & oki[:, None] & okj[None, :]

    def iou(self, mp):
        sx, ox, sy, oy = mp
        got = self._sample(self.mask, (self.u - ox) / sx, (self.v - oy) / sy)
        union = (got | self.want).sum()
        return float((got & self.want).sum() / union) if union else 0.0

    def centred(self, sx, sy):
        """The map of scales (sx, sy) that puts the mask's centroid onto the foreground's centroid."""
        ys, xs = np.nonzero(self.mask)
        fy, fx = np.nonzero(self.fg)
        return (sx, fx.mean() + 0.5 - sx * (xs.mean() + 0.5), sy, fy.mean() + 0.5 - sy * (ys.mean() + 0.5))


def register_raster(mask: np.ndarray, fg: np.ndarray) -> tuple[tuple, float, float]:
    """``(map, iou, box_iou)``: the axis-aligned map template -> answer (module docstring) that maximises the IoU of
    the mapped ``mask`` against the answer's foreground ``fg`` on a ``GRID``-cell grid over the foreground region, and
    the IoU of the box fit it started from. Scales stay within ``SCALE_LIMIT`` of the box fit, the centre within
    ``OFFSET_LIMIT`` of the foreground box. Both rasters must be non-empty."""
    mask = np.asarray(mask, bool)
    fg = np.asarray(fg, bool)
    if not mask.any() or not fg.any():
        raise ValueError("register_raster needs a non-empty mask and foreground")
    pr = _Problem(mask, fg)
    mx0, mx1, my0, my1 = _box(mask)
    bx0, bx1, by0, by1 = _box(fg)
    sx0, sy0 = (bx1 - bx0) / (mx1 - mx0), (by1 - by0) / (my1 - my0)
    box = (sx0, bx0 - mx0 * sx0, sy0, by0 - my0 * sy0)
    box_iou = pr.iou(box)
    best, best_iou = box, box_iou
    for ks in SCALES:
        for ky in SCALES:
            m = pr.centred(box[0] * ks, box[2] * ky)
            i = pr.iou(m)
            if i > best_iou:
                best, best_iou = m, i
    # searched as (log sx, log sy, answer u, answer v of the mask box centre)
    cx, cy = (mx0 + mx1) / 2, (my0 + my1) / 2
    lim_s = np.log(SCALE_LIMIT)
    ref = (np.log(box[0]), np.log(box[2]), box[0] * cx + box[1], box[2] * cy + box[3])

    def make(v):
        sx, sy = float(np.exp(v[0])), float(np.exp(v[1]))
        return (sx, float(v[2] - sx * cx), sy, float(v[3] - sy * cy))

    def allowed(v):
        return (abs(v[0] - ref[0]) <= lim_s and abs(v[1] - ref[1]) <= lim_s
                and abs(v[2] - ref[2]) <= OFFSET_LIMIT * pr.bw and abs(v[3] - ref[3]) <= OFFSET_LIMIT * pr.bh)

    cur = [np.log(best[0]), np.log(best[2]), best[0] * cx + best[1], best[2] * cy + best[3]]
    if not allowed(cur):
        cur, best_iou = list(ref), box_iou
    step = [STEP_LOG, STEP_LOG, STEP_OFF * pr.bw, STEP_OFF * pr.bh]
    floor = [MIN_STEP_LOG, MIN_STEP_LOG, MIN_STEP_OFF * pr.bw, MIN_STEP_OFF * pr.bh]
    for _ in range(400):
        moved = False
        for d in range(4):
            for sgn in (1, -1):
                v = list(cur)
                v[d] += sgn * step[d]
                if not allowed(v):
                    continue
                i = pr.iou(make(v))
                if i > best_iou + 1e-9:
                    cur, best_iou, moved = v, i, True
        if not moved:
            step = [s / 2 for s in step]
            if all(s < f for s, f in zip(step, floor)):
                break
    return make(cur), round(best_iou, 4), round(box_iou, 4)


def _sample_bilinear(rgb: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """``rgb`` (h, w, 3) float read bilinearly at the points (u, v) (pixel units, centres at +0.5); outside = white."""
    h, w = rgb.shape[:2]
    x, y = u - 0.5, v - 0.5
    j0, i0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = (x - j0)[..., None], (y - i0)[..., None]
    pad = np.pad(rgb, ((1, 1), (1, 1), (0, 0)), constant_values=255.0)
    j0p, i0p = np.clip(j0 + 1, 0, w + 1), np.clip(i0 + 1, 0, h + 1)
    j1p, i1p = np.clip(j0 + 2, 0, w + 1), np.clip(i0 + 2, 0, h + 1)
    return ((pad[i0p, j0p] * (1 - fx) + pad[i0p, j1p] * fx) * (1 - fy)
            + (pad[i1p, j0p] * (1 - fx) + pad[i1p, j1p] * fx) * fy)


def resample_register(out: Image.Image, mask: np.ndarray) -> tuple[np.ndarray, dict]:
    """The model's answer in the template frame: resized to the mask's frame (Lanczos), registered
    (``register_raster``), sampled through the map (bilinear). Returns the (h, w, 3) uint8 image and
    ``{"registered", "iou", "size_in", ["map", "grid_iou", "box_iou"]}``; ``iou`` is the full-resolution IoU of the
    returned image's foreground against ``mask``. An empty foreground skips the registration
    (``registered`` False, ``iou`` 0.0, the resized answer returned)."""
    mask = np.asarray(mask, bool)
    h, w = mask.shape
    im = out.convert("RGB")
    size_in = [im.width, im.height]
    if im.size != (w, h):
        im = im.resize((w, h), Image.LANCZOS)
    arr = np.asarray(im, np.uint8)
    tol = answer_white_tol(arr, mask) if mask.any() else WHITE_TOL
    fg = foreground(arr, tol)
    if not fg.any() or not mask.any():
        return arr.copy(), {"registered": False, "iou": 0.0, "size_in": size_in, "white_tol": tol}
    arr, fg, strays = drop_strays(arr, fg, mask)
    mp, grid_iou, box_iou = register_raster(mask, fg)
    sx, ox, sy, oy = mp
    xs = np.arange(w) + 0.5
    ys = np.arange(h) + 0.5
    U = np.broadcast_to(sx * xs[None, :] + ox, (h, w))
    V = np.broadcast_to(sy * ys[:, None] + oy, (h, w))
    got = np.clip(np.rint(_sample_bilinear(arr.astype(np.float64), U, V)), 0, 255).astype(np.uint8)
    f2 = foreground(got, tol)
    union = (f2 | mask).sum()
    iou = float((f2 & mask).sum() / union) if union else 0.0
    return got, {"registered": True, "iou": round(iou, 4), "size_in": size_in,
                 "map": [round(float(x), 6) for x in mp], "grid_iou": grid_iou, "box_iou": box_iou,
                 "strays": strays, "white_tol": tol}


#: ``drop_strays``: the answer's foreground pieces that touch the islands must cover at least this share of the mask
#: before the pieces that do not touch them are dropped as strays (below it the model moved the panel and the
#: registration has to find it in the whole foreground).
STRAY_KEEP_COVERAGE = 0.5


def drop_strays(arr: np.ndarray, fg: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """The answer without the foreground pieces that lie apart from the islands (user test 2026-11-21, Kai's and
    Tilda's back jobs: the model kept the panel in place AND drew a whole extra garment beside it — the foreground's
    box then spanned both, the registration scaled the template 2.4x onto the extra garment and the gate read
    "coverage 0.65"). A connected foreground piece (8-neighbourhood) that shares no pixel with ``mask`` (in the
    template frame, before any map) is painted white — but only when the pieces that do touch the mask already cover
    ``STRAY_KEEP_COVERAGE`` of it, i.e. the model kept the template's frame; otherwise nothing is dropped. Pieces apart
    from the islands never reach the atlas (``cut_and_bleed`` keeps the islands only), so this changes what the
    registration and the gate measure, never a pixel of a kept answer. ``(arr, fg, strays)`` — ``strays`` the dropped
    foreground as a share of the mask area (0.0 when nothing was dropped)."""
    from scipy import ndimage
    labels, count = ndimage.label(fg, structure=np.ones((3, 3), bool))
    if count < 2:
        return arr, fg, 0.0
    touching = np.zeros(count + 1, bool)
    touching[np.unique(labels[mask & fg])] = True
    touching[0] = False
    keep = touching[labels]
    area = int(mask.sum())
    if not area or float((keep & mask).sum()) / area < STRAY_KEEP_COVERAGE:
        return arr, fg, 0.0
    drop = fg & ~keep
    if not drop.any():
        return arr, fg, 0.0
    out = arr.copy()
    out[drop] = 255
    return out, keep, round(float(drop.sum()) / area, 4)


# ------------------------------------------------------------------------------------------------------------------ gate

def gate(img: np.ndarray, mask: np.ndarray, labels: np.ndarray, px_per_cm: float,
         tol: int = WHITE_TOL) -> tuple[bool, dict, str]:
    """``(ok, metrics, reason)`` of a registered answer against the island mask: ``coverage`` (share of the mask that
    is foreground), ``island_coverage`` (the worst island's share; ``islands`` = per label id), ``iou``, ``spill``
    (foreground beyond ``SPILL_CM`` outside the mask, as a share of the mask area). ``reason`` = the first failing
    gate in that order as ``"<name> <value> < <limit>"`` (``">"`` for spill), "" when it passes; every failure is in
    ``metrics["failures"]``. ``tol``: the answer's foreground threshold (``answer_white_tol``, the registration's
    ``white_tol``)."""
    mask = np.asarray(mask, bool)
    labels = np.asarray(labels)
    fg = foreground(img, tol)
    area = int(mask.sum())
    inter = int((fg & mask).sum())
    union = int((fg | mask).sum())
    per = {}
    for lid in np.unique(labels[labels > 0]):
        isl = labels == lid
        per[str(int(lid))] = round(float((fg & isl).sum() / isl.sum()), 4)
    r = max(1, int(round(float(px_per_cm) * SPILL_CM)))
    spill_px = int((fg & ~dilate(mask, r)).sum())
    met = {
        "coverage": round(inter / area, 4) if area else 0.0,
        "island_coverage": min(per.values()) if per else 0.0,
        "iou": round(inter / union, 4) if union else 0.0,
        "spill": round(spill_px / area, 4) if area else 1.0,
        "islands": per,
    }
    fails = []
    for name in ("coverage", "island_coverage", "iou"):
        if met[name] < CUT_GATE[name]:
            fails.append(f"{name} {met[name]:.2f} < {CUT_GATE[name]:.2f}")
    if met["spill"] > CUT_GATE["spill"]:
        fails.append(f"spill {met['spill']:.2f} > {CUT_GATE['spill']:.2f}")
    met["failures"] = fails
    return (not fails), met, (fails[0] if fails else "")


# ------------------------------------------------------------------------------------------------------- cut and bleed

def outline_rim(img, mask) -> dict:
    """How far the answer's outline reaches into the islands: ``{"px", "share", "ref", "fine"}``. Ring k = the pixels
    k px inside the mask's border; ``share`` per ring = its pixels more than ``RIM_DE`` from the median colour of the
    band ``RIM_REF_PX`` deep inside, ``ref`` the same share in that band (the cloth's own weave and print). The run =
    the length of the unbroken run of rings from the border whose share exceeds ``ref + RIM_SHARE``. The FINE pass
    (``fine``: ``{"share", "ref"}``, None when no pixel lies ``RIM_REF_FINE_PX[1]`` deep) does the same at
    ``RIM_DE_FINE`` against the deeper band ``RIM_REF_FINE_PX`` and catches a soft shading band inside the outline.
    ``px`` = the longer run plus one pixel of margin (0 when neither has one), clamped to ``[RIM_MIN_PX,
    RIM_MAX_PX]``; islands too thin for the band keep ``RIM_MIN_PX``. A SHARE, not a ring median: a registration a
    few pixels off pushes the outline deep into ONE side only, which a median over the whole ring does not see — and
    the 3 px erosion before left exactly that side's outline to seed the bleed (live 2026-11-21, Tilda's cream blouse
    on MiniMax-H3: a grey line along the side seams).

    Hand-measured on the live answers of 2026-11-21 (registered into the template frame): Tilda (MiniMax) ref 0.009,
    rings 0..4 at 0.82 / 0.65 / 0.35 / 0.19 / 0.062 (> 0.059), ring 5 at 0.007 -> run 5 -> 6 px; Kai's P-H3 answer ref
    0.053, rings 0..3 at 0.83 / 0.62 / 0.35 / 0.135 (> 0.103), ring 4 at 0.095 -> run 4 -> 5 px. Lirien's leather
    (MiniMax, 2026-11-22): coarse ref 0.0, run 6 (ring 5 at 0.066 > 0.05, ring 6 at 0.031) -> 7 px before; fine ref
    0.0, rings 0..13 at 0.999 / 0.988 / 0.941 / 0.847 / 0.782 / 0.662 / 0.495 / 0.338 / 0.238 / 0.163 / 0.119 / 0.098 /
    0.071 / 0.044 -> run 13 (ring 13 <= 0.05) -> 14 px."""
    mask = np.asarray(mask, bool)
    lab = srgb_to_lab(np.asarray(img)[..., :3])
    layers = [mask]
    for _ in range(max(RIM_REF_PX[1], RIM_REF_FINE_PX[1])):
        layers.append(erode(layers[-1], 1))

    def run_of(de: float, ref_px: tuple) -> tuple[int, list, float] | None:
        band = layers[ref_px[0]] & ~layers[ref_px[1]]
        if not band.any():
            return None
        dist = np.linalg.norm(lab - np.median(lab[band], axis=0), axis=-1)
        ref = float((dist[band] > de).mean())
        shares, run, on = [], 0, True
        for k in range(RIM_MAX_PX):
            ring = layers[k] & ~layers[k + 1]
            share = float((dist[ring] > de).mean()) if ring.any() else 0.0
            shares.append(round(share, 3))
            if on and share > ref + RIM_SHARE:
                run = k + 1
            else:
                on = False
        return run, shares, ref

    coarse = run_of(RIM_DE, RIM_REF_PX)
    if coarse is None:
        return {"px": RIM_MIN_PX, "share": [], "ref": None, "fine": None}
    fine = run_of(RIM_DE_FINE, RIM_REF_FINE_PX)
    run = max(coarse[0], fine[0] if fine else 0)
    return {"px": int(min(RIM_MAX_PX, max(RIM_MIN_PX, run + 1 if run else 0))), "share": coarse[1],
            "ref": round(coarse[2], 3),
            "fine": {"share": fine[1], "ref": round(fine[2], 3)} if fine else None}


def cut_and_bleed(img, mask, bleed_px: int, erode_px: int = RIM_MIN_PX) -> np.ndarray:
    """The atlas cut to the islands with bleed padding: the mask eroded by ``erode_px`` (the model's outline, drawn
    inside the islands), then regrown ``erode_px + bleed_px`` times by one 8-neighbour ring whose pixels take the mean
    of their already filled neighbours, until every mask pixel is filled. An ISLAND thinner than the erosion (no core
    left, a strap or a band) keeps its own pixels; a thin part of an island with a core is regrown from that core —
    the jagged border of a fitted piece's island (bisected triangles: teeth 10-30 px deep at 2048) held the model's
    light outline in every tooth, and the old per-pixel rule (``mask & ~dilate(core)``) kept it as seed: a pale
    zigzag along the waist seam of Kai's jeans (live 2026-11-21). Returns (h, w, 3) uint8, white outside the grown
    area."""
    from scipy import ndimage

    rgb = np.asarray(img)[..., :3].astype(np.float64)
    mask = np.asarray(mask, bool)
    core = erode(mask, erode_px)
    labels, count = ndimage.label(mask, structure=np.ones((3, 3), bool))
    if count:
        cored = np.zeros(count + 1, bool)
        cored[np.unique(labels[core])] = True
        cored[0] = True
        core |= mask & ~cored[labels]
    filled = core.copy()
    col = np.where(filled[..., None], rgb, 0.0)
    h, w = mask.shape
    offs = [(di, dj) for di in (-1, 0, 1) for dj in (-1, 0, 1) if di or dj]
    steps = 0
    while steps < int(erode_px) + int(bleed_px) or (mask & ~filled).any():
        steps += 1
        ring = dilate(filled, 1) & ~filled
        if not ring.any():
            break
        acc = np.zeros_like(col)
        cnt = np.zeros((h, w))
        pf = np.pad(filled, 1)
        pc = np.pad(col, ((1, 1), (1, 1), (0, 0)))
        for di, dj in offs:
            f = pf[1 + di:1 + di + h, 1 + dj:1 + dj + w]
            acc += pc[1 + di:1 + di + h, 1 + dj:1 + dj + w] * f[..., None]
            cnt += f
        col[ring] = acc[ring] / cnt[ring][:, None]
        filled |= ring
    out = np.full(rgb.shape, 255, np.uint8)
    out[filled] = np.clip(np.rint(col[filled]), 0, 255).astype(np.uint8)
    return out


def fill_pockets(img, filled, reach_px: int) -> tuple[np.ndarray, np.ndarray]:
    """The composed atlas with its background pockets filled: every pixel outside ``filled`` (islands + bleed) that
    lies within ``reach_px`` of it, or in a hole ``filled`` encloses, takes the colour of its nearest ``filled`` pixel
    (exact Euclidean distance transform). Returns ``(image, pocket mask)``; the rest stays as it was (white)."""
    from scipy import ndimage

    out = np.asarray(img).copy()
    filled = np.asarray(filled, bool)
    if not filled.any():
        return out, np.zeros(filled.shape, bool)
    holes = ndimage.binary_fill_holes(filled) & ~filled
    dist, (iy, ix) = ndimage.distance_transform_edt(~filled, return_indices=True)
    pocket = ~filled & ((dist <= float(reach_px)) | holes)
    out[pocket] = out[iy[pocket], ix[pocket]]
    return out, pocket


#: ``lace_alpha``: a SHEER piece's cut atlas whose fabric shows skin in this share of its fabric pixels or more is lace
#: (Kira's lace tights, live 2026-11-22: the model painted opaque skin into every gap of the lace although the
#: prompt said "without skin" — on the figure the legs read as grey-beige pantyhose). Below it the atlas is a plain
#: sheer cloth and keeps the uniform opacity. Above ``LACE_SKIN_MAX`` the cloth ITSELF is skin-coloured (the YCrCb
#: box holds browns too: Lirien's brown leather is 99 % "skin"), no lace either.
LACE_SKIN_SHARE = 0.10
LACE_SKIN_MAX = 0.70
#: Bumped when ``lace_alpha`` or the keyed piece's surface (``garment_assembly.LACE_SURFACE``) changes (part of the
#: assembly's texture identity, ``garment_assembly._texture_state``). 2 (2026-11-22): no sheen / clear coat / specular.
LACE_VERSION = 2


def lace_alpha(rgb, opacity: float, skin_mask) -> tuple[np.ndarray | None, dict]:
    """The RGBA atlas of a sheer lace piece: the skin the model painted into the lace's gaps becomes the sheer base
    cloth — its colour the threads' (the median of the non-skin fabric pixels), its alpha ``opacity`` — and the
    threads stay opaque (alpha 1). ``skin_mask`` = ``garment_template.skin_mask`` (YCrCb box). Fabric pixels = not
    near white (min channel < 235: the white background is no fabric). The gap mask is softened by a 3 x 3 box so the
    thread edges are not stair-stepped. Returns ``(None, info)`` when the skin share of the fabric pixels is under
    ``LACE_SKIN_SHARE`` or over ``LACE_SKIN_MAX`` (no lace: the caller keeps the uniform opacity), else
    ``(rgba uint8, info)``; ``info`` =
    ``{"skin_share", "thread_rgb", "opacity"}``."""
    rgb = np.asarray(rgb)[..., :3].astype(np.uint8)
    fabric = rgb.min(axis=-1) < 235
    skin = np.asarray(skin_mask(rgb), bool) & fabric
    n = int(fabric.sum())
    share = float(skin.sum()) / n if n else 0.0
    info = {"skin_share": round(share, 4), "thread_rgb": None, "opacity": float(opacity)}
    threads = fabric & ~skin
    if not LACE_SKIN_SHARE <= share <= LACE_SKIN_MAX or not threads.any():
        return None, info
    thread = np.median(rgb[threads], axis=0)
    info["thread_rgb"] = [int(round(v)) for v in thread]
    w = skin.astype(np.float64)
    pw = np.pad(w, 1, mode="edge")
    soft = sum(pw[1 + di:1 + di + w.shape[0], 1 + dj:1 + dj + w.shape[1]]
               for di in (-1, 0, 1) for dj in (-1, 0, 1)) / 9.0
    soft = np.where(skin, np.maximum(soft, 0.5), soft * (soft > 0.5))
    col = rgb.astype(np.float64) * (1.0 - soft[..., None]) + thread[None, None, :] * soft[..., None]
    alpha = 1.0 - (1.0 - float(opacity)) * soft
    out = np.empty(rgb.shape[:2] + (4,), np.uint8)
    out[..., :3] = np.clip(np.rint(col), 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(np.rint(alpha * 255), 0, 255).astype(np.uint8)
    return out, info


# --------------------------------------------------------------------------------------------------------- colour match

def _rgba(px) -> np.ndarray:
    px = np.asarray(px, np.uint8)
    if px.ndim == 3 and px.shape[2] == 3:
        px = np.concatenate([px, np.full(px.shape[:2] + (1,), 255, np.uint8)], -1)
    return px


def _trimmed(rgb: np.ndarray) -> np.ndarray:
    """The darkest and brightest ``FABRIC_TRIM`` of luminance dropped from (n, 3) colours."""
    if not len(rgb):
        return rgb.reshape(0, 3)
    L = srgb_to_lab(rgb)[:, 0]
    lo, hi = np.quantile(L, FABRIC_TRIM), np.quantile(L, 1 - FABRIC_TRIM)
    return rgb[(L >= lo) & (L <= hi)]


def fabric_pixels(item_rgba: np.ndarray, *, matte=garment_matte.birefnet_matte) -> np.ndarray:
    """The item's fabric colours (n, 3) float: alpha > 0 after ``garment_matte.cut`` (``matte`` passed through; a
    smoke passes ``None`` or a stub so no BiRefNet session loads), the darkest and brightest ``FABRIC_TRIM`` of
    luminance dropped."""
    cut, _info = garment_matte.cut(_rgba(item_rgba), matte=matte)
    return _trimmed(cut[..., :3][cut[..., 3] > 0].astype(np.float64))


def picture_reference(rgba: np.ndarray, *, matte=garment_matte.birefnet_matte) -> dict:
    """What the answer gates and the pre-fill read from a picture (the item picture, the back view), with ONE
    ``garment_matte.cut``: ``{"colour": fabric_colour of the garment (alpha >= 128), "detail": detail_density of it,
    "fabric": the colour match's fabric pixels (alpha > 0, trimmed)}``."""
    cut, _info = garment_matte.cut(_rgba(rgba), matte=matte)
    rgb, alpha = cut[..., :3], cut[..., 3]
    garment = alpha >= 128
    return {"colour": fabric_colour(rgb, garment) if garment.any() else None,
            "detail": detail_density(rgb, garment) if garment.any() else None,
            "fabric": _trimmed(rgb[alpha > 0].astype(np.float64))}


def colour_match(img, mask, item_rgba: np.ndarray | None = None, *, matte=garment_matte.birefnet_matte,
                 fabric: np.ndarray | None = None, base: tuple | None = None) -> tuple[np.ndarray, dict]:
    """The islands' colours moved onto the item fabric's: per Lab channel ``(x - mu_atlas) * gain + mu_atlas +
    shift`` with ``gain = min(SIGMA_GAIN_MAX, sigma_item / sigma_atlas)`` (``sigma_atlas`` floored at
    ``SIGMA_FLOOR``) and ``shift = mu_item - mu_atlas``, clamped to ``CLAMP_DE`` (dE76). Only mask pixels change. The
    fabric colours are ``fabric`` when given (``picture_reference``), else ``fabric_pixels(item_rgba)``.

    ``base`` = ``(item fabric_colour, answer fabric_colour)`` (the answer gate's two dicts): when BOTH have plain
    fabric (``plain`` >= ``FABRIC_MIN_PLAIN``) the shift is base onto base (``item.lab - answer.lab``), not mean onto
    mean — a photo's highlights and shading lift and grey the mean of its pixels (Lirien's brown leather, live
    2026-11-22: item mean L* 34.1 against its base 29.1, so a faithful answer at base L* 27.1 was lightened to taupe),
    and the base is what the gate compared. ``info["by"]`` = "base" or "mean".

    The gain never ADDS contrast: a photo's sigma is shading, highlights and folds, not the cloth's pattern, and the
    same answer (sigma L* 1.1 against the item's 8.6) was multiplied 7.7 x — a weave of noise over the plain leather
    and the bleed's faint seam residue turned into dark and light streaks.

    Returns the (h, w, 3) uint8 image and ``{"de_before", "de_after", "clamped", "by", "gain"}`` (``de_before`` =
    dE76 of the shift; ``de_after`` = the island mean against the item's for "mean", the clamp's residual for
    "base"); nothing to match
    (no mask, no fabric) -> the image unchanged and ``{"skipped": reason}``."""
    rgb = np.asarray(img)[..., :3].astype(np.uint8)
    mask = np.asarray(mask, bool)
    out = rgb.copy()
    if not mask.any():
        return out, {"skipped": "empty mask"}
    fab = fabric if fabric is not None else fabric_pixels(item_rgba, matte=matte)
    if not len(fab):
        return out, {"skipped": "no fabric pixels"}
    item_lab = srgb_to_lab(fab)
    mu_i, sd_i = item_lab.mean(0), item_lab.std(0)
    lab = srgb_to_lab(rgb[mask].astype(np.float64))
    mu_a, sd_a = lab.mean(0), np.maximum(lab.std(0), SIGMA_FLOOR)
    gain = np.minimum(SIGMA_GAIN_MAX, sd_i / sd_a)
    item_base, answer_base = base if base else (None, None)
    by_base = bool(item_base and answer_base
                   and float(item_base.get("plain", 0.0)) >= FABRIC_MIN_PLAIN
                   and float(answer_base.get("plain", 0.0)) >= FABRIC_MIN_PLAIN)
    src, dst = ((np.asarray(answer_base["lab"], float), np.asarray(item_base["lab"], float)) if by_base
                else (mu_a, mu_i))
    shift = dst - src
    de_before = float(np.linalg.norm(shift))
    clamped = de_before > CLAMP_DE
    if clamped:
        shift = shift * (CLAMP_DE / de_before)
    new = (lab - mu_a) * gain + mu_a + shift
    out[mask] = np.clip(np.rint(lab_to_srgb(new)), 0, 255).astype(np.uint8)
    # what is left: the island mean against the item's (by mean) / the shift's own residual (by base: non-zero only
    # when clamped)
    moved = srgb_to_lab(out[mask].astype(np.float64)).mean(0) if not by_base else src + shift
    return out, {"de_before": round(de_before, 3), "de_after": round(float(np.linalg.norm(moved - dst)), 3),
                 "clamped": bool(clamped), "by": "base" if by_base else "mean",
                 "gain": [round(float(g), 3) for g in gain]}


# ------------------------------------------------------------------------------------------------------ fabric colour
#
# User test 2026-11-21: P-H3 answered Kai's PLAIN blue T-shirt with an invented magenta shirt and a big text print
# (job adc0d92f) and, with the print words taken out of the prompt, a red one (dd179c81); for Dario it painted the
# chest embroidery onto one sleeve. The fix is not prompt wording alone: the islands go to the model PRE-FILLED with
# the item's base fabric colour (``fabric_colour``), the sleeves and the neckband come from a seamless fabric patch of
# the answer's own front panel (``fabric_patch`` / ``tile_fill``), and two gates measure the answer against the item
# picture — its base colour (``delta_e00`` of the two ``fabric_colour``) and its detail (``detail_density``).

#: ``fabric_colour``: the long side the picture is measured at (box-filtered down; the measure is a median).
FABRIC_SIDE = 512
#: ``fabric_colour``: the mask is eroded by this share of the garment's extent (the anti-aliased outline, the shadow
#: along the cut-out edge and the white background bleeding in never count).
FABRIC_ERODE = 0.02
#: ``fabric_colour``: a pixel whose L* differs from its local mean (a box of ``2r + 1``, r = ``FABRIC_DETAIL_R`` of the
#: extent) by more than ``FABRIC_DETAIL_L`` is a DETAIL (an embroidery stitch, a print edge, a button, a highlight on a
#: fold crest); every pixel within r of one is left out. A smooth fold shadow changes L* over many pixels: it stays.
FABRIC_DETAIL_R = 0.015
FABRIC_DETAIL_L = 6.0
#: ``fabric_colour``: under this share of plain pixels the detail filter is dropped (an all-over pattern has no plain
#: fabric: the mode below still finds its ground colour).
FABRIC_MIN_PLAIN = 0.05
#: ``fabric_colour``: the a*b* histogram (bins of ``FABRIC_AB_BIN``, smoothed by one bin) — its peak is the fabric's
#: chroma; the pixels within ``FABRIC_AB_RADIUS`` of it give the median L*a*b*. A print in another colour forms its own
#: peak; the larger one (the ground of the fabric) wins.
FABRIC_AB_BIN = 2.0
FABRIC_AB_RADIUS = 12.0


def _box_down(rgb: np.ndarray, mask: np.ndarray, side: int) -> tuple[np.ndarray, np.ndarray]:
    """``rgb`` / ``mask`` box-filtered so the long side is at most ``side`` (a mask pixel stays when >= half covered)."""
    h, w = mask.shape
    s = side / float(max(h, w))
    if s >= 1.0:
        return np.asarray(rgb)[..., :3].astype(np.uint8), np.asarray(mask, bool)
    size = (max(1, round(w * s)), max(1, round(h * s)))
    small = np.asarray(Image.fromarray(np.asarray(rgb)[..., :3].astype(np.uint8)).resize(size, Image.BOX))
    m = np.asarray(Image.fromarray(np.asarray(mask, np.uint8) * 255).resize(size, Image.BOX)) >= 128
    return small, m


def _extent(mask: np.ndarray) -> int:
    ys, xs = np.nonzero(mask)
    return int(max(np.ptp(ys), np.ptp(xs))) + 1 if len(ys) else 0


def fabric_colour(rgb, mask) -> dict | None:
    """The BASE fabric colour of the pixels under ``mask`` — robust against shading, highlights and small
    high-contrast details (prints, embroidery, buttons): box-down to ``FABRIC_SIDE``, erode by ``FABRIC_ERODE``, drop
    the detail pixels (``FABRIC_DETAIL_L`` / ``FABRIC_DETAIL_R``), then the peak of the a*b* histogram and the median
    L*a*b* of the pixels within ``FABRIC_AB_RADIUS`` of it. ``{"rgb": [r, g, b] (0..255 ints), "lab": [L, a, b],
    "plain": share of the eroded mask left after the detail filter, "peak": share of those within the radius,
    "pixels": n}``; None for an (almost) empty mask."""
    from scipy import ndimage
    rgb, mask = _box_down(rgb, mask, FABRIC_SIDE)
    ext = _extent(mask)
    if ext < 4:
        return None
    m = ndimage.binary_erosion(mask, iterations=max(1, round(FABRIC_ERODE * ext)))
    if m.sum() < 16:
        m = mask
    lab = srgb_to_lab(rgb.astype(np.float64))
    r = max(2, round(FABRIC_DETAIL_R * ext))
    L = lab[..., 0]
    detail = np.abs(L - ndimage.uniform_filter(L, 2 * r + 1)) > FABRIC_DETAIL_L
    keep = m & ~ndimage.binary_dilation(detail, iterations=r)
    plain = float(keep.sum() / max(1, m.sum()))
    if plain < FABRIC_MIN_PLAIN:
        keep = m
    px = lab[keep]
    ab = px[:, 1:]
    lo = np.floor(ab.min(0) / FABRIC_AB_BIN) - 1
    idx = np.floor(ab / FABRIC_AB_BIN - lo).astype(int)
    shape = tuple(int(v) for v in idx.max(0) + 2)
    hist = np.zeros(shape)
    np.add.at(hist, (idx[:, 0], idx[:, 1]), 1.0)
    hist = ndimage.uniform_filter(hist, 3, mode="constant")
    pi, pj = np.unravel_index(int(np.argmax(hist)), hist.shape)
    peak = (np.array([pi, pj], float) + lo + 0.5) * FABRIC_AB_BIN
    near = np.linalg.norm(ab - peak, axis=-1) <= FABRIC_AB_RADIUS
    sel = px[near] if near.any() else px
    med = np.median(sel, axis=0)
    out = np.clip(np.rint(lab_to_srgb(med)), 0, 255).astype(int)
    return {"rgb": [int(v) for v in out], "lab": [round(float(v), 2) for v in med], "plain": round(plain, 4),
            "peak": round(float(near.mean()), 4), "pixels": int(len(sel))}


def delta_e00(lab1, lab2) -> float:
    """CIEDE2000 colour difference of two L*a*b* colours (Sharma, Wu, Dalal 2005; kL = kC = kH = 1)."""
    L1, a1, b1 = (float(v) for v in lab1)
    L2, a2, b2 = (float(v) for v in lab2)
    c1, c2 = np.hypot(a1, b1), np.hypot(a2, b2)
    cm = 0.5 * (c1 + c2)
    g = 0.5 * (1 - np.sqrt(cm ** 7 / (cm ** 7 + 25.0 ** 7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360 if c1p else 0.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360 if c2p else 0.0
    dL, dC = L2 - L1, c2p - c1p
    if c1p * c2p == 0:
        dh = 0.0
    else:
        dh = h2p - h1p
        if dh > 180:
            dh -= 360
        elif dh < -180:
            dh += 360
    dH = 2 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh / 2))
    Lm, Cm = 0.5 * (L1 + L2), 0.5 * (c1p + c2p)
    if c1p * c2p == 0:
        hm = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hm = 0.5 * (h1p + h2p)
    else:
        hm = 0.5 * (h1p + h2p + 360) if h1p + h2p < 360 else 0.5 * (h1p + h2p - 360)
    t = (1 - 0.17 * np.cos(np.radians(hm - 30)) + 0.24 * np.cos(np.radians(2 * hm))
         + 0.32 * np.cos(np.radians(3 * hm + 6)) - 0.20 * np.cos(np.radians(4 * hm - 63)))
    sl = 1 + 0.015 * (Lm - 50) ** 2 / np.sqrt(20 + (Lm - 50) ** 2)
    sc = 1 + 0.045 * Cm
    sh = 1 + 0.015 * Cm * t
    rt = -2 * np.sqrt(Cm ** 7 / (Cm ** 7 + 25.0 ** 7)) * np.sin(np.radians(60 * np.exp(-(((hm - 275) / 25) ** 2))))
    return float(np.sqrt((dL / sl) ** 2 + (dC / sc) ** 2 + (dH / sh) ** 2 + rt * (dC / sc) * (dH / sh)))


#: ``detail_density``: the region is resampled so its long side is ``DETAIL_SIDE`` px (an item picture and a 2048
#: atlas panel are compared at one scale), smoothed by a Gaussian of ``DETAIL_SIGMA`` px (the photo's noise and weave),
#: eroded by ``DETAIL_ERODE`` of the side (the cut-out edge is no detail); a pixel is an EDGE when its L* gradient
#: magnitude exceeds ``DETAIL_EDGE`` per px.
DETAIL_SIDE = 128
DETAIL_SIGMA = 1.0
DETAIL_ERODE = 0.03
DETAIL_EDGE = 4.0


def detail_density(rgb, mask) -> float | None:
    """The share of EDGE pixels (``DETAIL_EDGE``) inside ``mask`` at the common scale ``DETAIL_SIDE`` — how much
    print, text, embroidery or pattern the region carries (a plain fabric with soft folds: near 0). None for an empty
    mask."""
    from scipy import ndimage
    mask = np.asarray(mask, bool)
    ys, xs = np.nonzero(mask)
    if len(ys) < 16:
        return None
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    crop = np.asarray(rgb)[y0:y1, x0:x1, :3].astype(np.uint8)
    cm = mask[y0:y1, x0:x1]
    s = DETAIL_SIDE / float(max(cm.shape))
    size = (max(1, round(cm.shape[1] * s)), max(1, round(cm.shape[0] * s)))
    small = np.asarray(Image.fromarray(crop).resize(size, Image.BOX if s < 1 else Image.BILINEAR), np.float64)
    m = np.asarray(Image.fromarray(cm.astype(np.uint8) * 255).resize(size, Image.BOX)) >= 128
    m = ndimage.binary_erosion(m, iterations=max(1, round(DETAIL_ERODE * DETAIL_SIDE)))
    if m.sum() < 16:
        return None
    L = ndimage.gaussian_filter(srgb_to_lab(small)[..., 0], DETAIL_SIGMA)
    gy, gx = np.gradient(L)
    edge = np.hypot(gx, gy) > DETAIL_EDGE
    return round(float(edge[m].mean()), 4)


#: The answer gates (user test 2026-11-21), measured on the job's MAIN panel (the front panel of the front job, the
#: back panel of the back job) of the registered answer, before the colour match moves anything:
#: - ``de00``: the CIEDE2000 distance of its base fabric colour (``fabric_colour``) from the ITEM picture's. Measured
#:   on the real answers: Kai's blue shirt (L 39, a 12, b -50) against the invented magenta panel (adc0d92f) 35.0,
#:   against the red one (dd179c81) 43.5; Dario's green shirt against its right answer 9.9 — P-H3's flat studio light
#:   lifts a dark fabric (L 18 -> 28.5) and greys it a little, which the colour match corrects (``CLAMP_DE``). 20 sits
#:   2x above Dario and 1.75x below Kai: a lighting shift passes, another colour does not;
#: - ``detail``: an "invented content" gate on ``detail_density``: the answer's panel may carry at most
#:   ``detail_factor`` x the detail of the job's Picture 2 (the item picture, the back view) plus ``detail_slack``.
#:   Measured at ``DETAIL_SIDE`` 128 (BiRefNet cut of the item): Kai's item 0.0154, its invented print panel 0.471;
#:   Dario's item 0.0976 (the embroidery and the crinkled weave), its right answer 0.212 — P-H3 draws an embroidery
#:   bolder than the photo shows it, 2.2x. Factor 4 leaves Dario 2x of room (limit 0.430); Kai's limit is 0.102 and
#:   the print 4.6x over it. The slack 0.04 lets a plain item (detail ~0) keep a visible weave; a print block of the
#:   adc0d92f kind on a quarter of a plain panel (~0.12) is still over its limit.
#:   Factor 3 since 2026-11-21 (POST_VERSION 4): Tilda's plain cream back view (0.0536) got an invented illustration on
#:   its back panel at 0.236 — under factor 4's limit 0.254, over factor 3's 0.201. The right answers stay far below
#:   factor 3: Dario 0.138 / 0.013 against 0.467 / 0.514, Kai 0.007 / 0.0 against 0.080 / 0.093.
ANSWER_GATE = {"de00": 20.0, "detail_factor": 3.0, "detail_slack": 0.04}


def detail_limit(reference: float | None) -> float | None:
    """The ``detail`` gate's limit for a Picture 2 of detail density ``reference`` (None: no reference, no gate)."""
    if reference is None:
        return None
    return round(ANSWER_GATE["detail_factor"] * float(reference) + ANSWER_GATE["detail_slack"], 4)


def answer_gates(reg: np.ndarray, panel: np.ndarray, item_colour: dict | None,
                 reference_detail: float | None) -> tuple[list[dict], dict]:
    """The colour and the invented-content gate (``ANSWER_GATE``) of a registered answer's main ``panel`` mask:
    ``([{"gate", "ok", "value", "limit", "text"}], {"fabric": {"item", "answer", "de00"}, "detail": {"reference",
    "answer", "limit"}})``. A gate whose input is missing (no item colour, an empty panel) is left out. An item
    picture with no plain fabric (``plain`` < ``FABRIC_MIN_PLAIN``: an all-over pattern such as scales) has no base
    colour to hold an answer to — its histogram peak lands on the dark gaps between the scales (Glut's scale pieces,
    live 2026-11-21: item (19, 8, 3) against a faithful red answer, ΔE00 26.9 / 30.6) — so the colour gate is
    recorded as ``skipped`` and passes; the detail gate still guards the answer."""
    gates: list[dict] = []
    ans = fabric_colour(reg, panel) if np.asarray(panel).any() else None
    de = round(delta_e00(item_colour["lab"], ans["lab"]), 2) if ans and item_colour else None
    if de is not None:
        lim = ANSWER_GATE["de00"]
        if float(item_colour.get("plain", 1.0)) < FABRIC_MIN_PLAIN:
            gates.append({"gate": "colour", "ok": True, "value": de, "limit": lim, "skipped": True,
                          "text": "", "note": "all-over pattern: no plain fabric in the item picture"})
        else:
            gates.append({"gate": "colour", "ok": de <= lim, "value": de, "limit": lim,
                          "text": f"colour \u0394E00 {de:.1f} > {lim:.0f}" if de > lim else ""})
    det = detail_density(reg, panel) if np.asarray(panel).any() else None
    lim_d = detail_limit(reference_detail)
    if det is not None and lim_d is not None:
        gates.append({"gate": "detail", "ok": det <= lim_d, "value": det, "limit": lim_d,
                      "text": f"invented content: detail {det:.2f} > {lim_d:.2f}" if det > lim_d else ""})
    return gates, {"fabric": {"item": item_colour, "answer": ans, "de00": de},
                   "detail": {"reference": reference_detail, "answer": det, "limit": lim_d}}


#: The split gate (``split_gate``, live run 2026-11-22, Gelina's moon silk skirt): MiniMax read the side slit of the
#: item picture as a cut and painted the front panel as TWO pieces with a white line between them (~1.7 cm wide, the
#: whole panel high) — coverage 0.97 and iou 0.97 still passed, and the line was on the figure. A background-coloured
#: component (not ``foreground`` at the answer's own ``white_tol``) inside a main island, the island eroded by
#: ``edge_cm`` (the outline and a smeared border are not a line), is a split when its bounding box's long side is at
#: least ``length`` x the island's own extent along that axis and its mean width (area / long side) at most
#: ``width_cm``. A fabric speck, a sparkle or a round hole is short; a line through the panel is long and thin.
#: Skipped when the ITEM's own fabric pixels are background-coloured in at least ``item_share`` of them (a white
#: stripe, a white print): there a white line can be the fabric.
SPLIT_GATE = {"edge_cm": 1.0, "length": 0.4, "width_cm": 3.0, "item_share": 0.02}


def split_gate(reg: np.ndarray, panel_labels: np.ndarray, px_per_cm: float, tol: int,
               item_fabric: np.ndarray | None = None) -> dict | None:
    """The split gate (``SPLIT_GATE``) of a registered answer over the job's main islands (``panel_labels``: the
    island ids of the main panel, 0 elsewhere): ``{"gate": "split", "ok", "value", "limit", "text", "lines"}`` —
    ``value`` the longest background line as a share of its island's extent, ``lines`` every split found as
    ``{"island", "length", "width_cm"}``; ``skipped`` when the item's fabric is background-coloured
    (``item_share``). None without a main island."""
    from scipy import ndimage
    labels = np.asarray(panel_labels)
    ids = [int(i) for i in np.unique(labels[labels > 0])]
    if not ids:
        return None
    g = SPLIT_GATE
    lim = g["length"]
    if item_fabric is not None and len(item_fabric):
        px = np.asarray(item_fabric, np.float64).reshape(-1, 3)
        share = float(((255.0 - px).max(-1) <= tol).mean())
        if share >= g["item_share"]:
            return {"gate": "split", "ok": True, "value": 0.0, "limit": lim, "skipped": True, "text": "",
                    "lines": [], "note": f"the item's fabric is background-coloured in {share:.3f} of its pixels"}
    fg = foreground(reg, tol)
    r = max(1, int(round(g["edge_cm"] * float(px_per_cm))))
    width_px = g["width_cm"] * float(px_per_cm)
    best, lines = 0.0, []
    for lid in ids:
        inner = erode(labels == lid, r)
        if not inner.any():
            continue
        ys, xs = np.nonzero(inner)
        ext = (int(ys.max() - ys.min() + 1), int(xs.max() - xs.min() + 1))
        comp, n = ndimage.label(inner & ~fg, structure=np.ones((3, 3), bool))
        if not n:
            continue
        for k, sl in enumerate(ndimage.find_objects(comp), start=1):
            h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
            along = 0 if h >= w else 1
            length = max(h, w)
            share = length / float(ext[along])
            area = int((comp[sl] == k).sum())
            if area / float(length) > width_px:
                continue
            best = max(best, share)
            if share >= lim:
                lines.append({"island": lid, "length": round(share, 3),
                              "width_cm": round(area / float(length) / float(px_per_cm), 2)})
    ok = not lines
    return {"gate": "split", "ok": ok, "value": round(best, 3), "limit": lim, "lines": lines,
            "text": "" if ok else f"split line through a panel: {best:.2f} of its extent"}


# ---------------------------------------------------------------------------------------------- the fabric patch
#
# Sleeves and neckband are NOT taken from the model by default (Dario 2026-11-21: P-H3 painted the chest embroidery
# onto one sleeve — it does not recognise the wide fan-shaped sleeve islands as sleeves). They are filled with a
# seamless patch of the answer's own front panel: its structure and colour, from its plainest window.

#: The patch side in cm of the atlas (``px_per_cm``), clamped to ``PATCH_PX``. 8 cm holds a few repeats of a weave or
#: a fine check and stays inside a narrow panel.
PATCH_CM = 8.0
PATCH_PX = (24, 256)
#: Windows whose mean is farther than this (dE76) from the panel's base fabric colour are never picked (a plain area
#: INSIDE a large print — its flat sky, a solid letter — is plain but not the fabric).
PATCH_MAX_DE = 10.0


def _integral(a: np.ndarray) -> np.ndarray:
    out = np.zeros((a.shape[0] + 1, a.shape[1] + 1))
    out[1:, 1:] = np.cumsum(np.cumsum(a, 0), 1)
    return out


def _window_sums(ii: np.ndarray, p: int) -> np.ndarray:
    """Sum of every p x p window (top-left (i, j), i <= h - p, j <= w - p) from an integral image."""
    return ii[p:, p:] - ii[:-p, p:] - ii[p:, :-p] + ii[:-p, :-p]


def fabric_patch(img: np.ndarray, panel: np.ndarray, px_per_cm: float, base_lab=None) -> tuple[np.ndarray, dict] | None:
    """The plainest square window of ``img`` fully inside ``panel``: side ``PATCH_CM`` (clamped to ``PATCH_PX``,
    halved while no window fits), the least mean L* gradient energy among the windows whose mean lies within
    ``PATCH_MAX_DE`` of ``base_lab`` (the panel's base fabric colour; every window when None or none qualifies).
    ``(patch uint8 (p, p, 3), {"xy": [x, y], "px": p, "energy"})``, None when not even ``PATCH_PX[0]`` fits."""
    from scipy import ndimage
    panel = np.asarray(panel, bool)
    rgb = np.asarray(img)[..., :3]
    p = int(min(PATCH_PX[1], max(PATCH_PX[0], round(PATCH_CM * float(px_per_cm or 0) or PATCH_PX[1]))))
    ys, xs = np.nonzero(panel)
    if not len(ys):
        return None
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    crop = rgb[y0:y1, x0:x1].astype(np.float64)
    cm = panel[y0:y1, x0:x1]
    lab = srgb_to_lab(crop)
    gy, gx = np.gradient(ndimage.gaussian_filter(lab[..., 0], 1.0))
    energy = np.hypot(gx, gy)
    while p >= PATCH_PX[0]:
        if min(cm.shape) >= p:
            inside = _window_sums(_integral((~cm).astype(np.float64)), p) == 0
            if inside.any():
                break
        p //= 2
    else:
        return None
    area = float(p * p)
    e = _window_sums(_integral(energy), p) / area
    ok = inside.copy()
    if base_lab is not None:
        mean = np.stack([_window_sums(_integral(lab[..., k]), p) / area for k in range(3)], -1)
        near = np.linalg.norm(mean - np.asarray(base_lab, float), axis=-1) <= PATCH_MAX_DE
        if (inside & near).any():
            ok &= near
    score = np.where(ok, e, np.inf)
    i, j = np.unravel_index(int(np.argmin(score)), score.shape)
    patch = rgb[y0 + i:y0 + i + p, x0 + j:x0 + j + p].astype(np.uint8).copy()
    return patch, {"xy": [int(x0 + j), int(y0 + i)], "px": int(p), "energy": round(float(score[i, j]), 4)}


def mirror_tile(patch: np.ndarray, h: int, w: int) -> np.ndarray:
    """``patch`` tiled over (h, w) with every other copy mirrored (left-right, up-down): the tile ``[[P, P|], [P_,
    P_|]]`` repeats with period 2p and has no seam — each edge meets its own mirror image."""
    row = np.concatenate([patch, patch[:, ::-1]], 1)
    tile = np.concatenate([row, row[::-1]], 0)
    reps = (int(np.ceil(h / tile.shape[0])), int(np.ceil(w / tile.shape[1])), 1)
    return np.tile(tile, reps)[:h, :w]


def tile_fill(img: np.ndarray, region: np.ndarray, patch: np.ndarray, target_lab) -> tuple[np.ndarray, dict]:
    """``img`` with ``region`` filled by ``mirror_tile(patch)``, the tile's Lab mean moved onto ``target_lab`` (the
    panel's base fabric colour: the sleeves continue the panel's fabric, not its print). Returns the new uint8 image
    and ``{"shift": dE76 of the move}``."""
    out = np.asarray(img)[..., :3].astype(np.uint8).copy()
    region = np.asarray(region, bool)
    if not region.any():
        return out, {"shift": 0.0}
    h, w = region.shape
    tile = mirror_tile(patch, h, w)
    lab = srgb_to_lab(tile[region].astype(np.float64))
    shift = np.asarray(target_lab, float) - srgb_to_lab(patch.reshape(-1, 3).astype(np.float64)).mean(0)
    out[region] = np.clip(np.rint(lab_to_srgb(lab + shift)), 0, 255).astype(np.uint8)
    return out, {"shift": round(float(np.linalg.norm(shift)), 3)}


# ------------------------------------------------------------------------------------------------------ seam continuity

def seam_continuity(atlas, seams) -> dict:
    """The colour jump across the payload's seam pairs (``islands.json`` ``seams``: ``{"seam", "uv_a_px",
    "uv_b_px", ...}``, image-frame pixels): dE76 of the atlas pixel under each side, the median per seam and over all
    pairs. ``{"median": float | None, "per_seam": {str(seam): median}, "pairs": n}``."""
    arr = np.asarray(atlas)[..., :3].astype(np.float64)
    h, w = arr.shape[:2]
    if not seams:
        return {"median": None, "per_seam": {}, "pairs": 0}

    def at(p):
        j = min(w - 1, max(0, int(np.floor(p[0]))))
        i = min(h - 1, max(0, int(np.floor(p[1]))))
        return arr[i, j]

    a = np.array([at(s["uv_a_px"]) for s in seams])
    b = np.array([at(s["uv_b_px"]) for s in seams])
    de = np.linalg.norm(srgb_to_lab(a) - srgb_to_lab(b), axis=-1)
    per: dict[str, list] = {}
    for s, d in zip(seams, de):
        per.setdefault(str(s.get("seam", 0)), []).append(float(d))
    return {"median": round(float(np.median(de)), 3),
            "per_seam": {k: round(float(np.median(v)), 3) for k, v in sorted(per.items())},
            "pairs": len(seams)}


# ------------------------------------------------------------------------------------------------------------ placket

#: Plan group B, B10-B13 (phase C): what closes a front is painted by code into the composed atlas along the cut's
#: ``marks.json`` lines — never a pattern piece, never the model's. Button pitch for an automatic count, button
#: diameter and the placket's width per kind (cm); a lapel jacket has no placket band (buttons only).
BUTTON_PITCH_CM = {"top": 7.0, "dress": 7.0, "jacket": 10.0}
BUTTON_D_CM = {"top": 1.1, "dress": 1.1, "jacket": 1.8}
PLACKET_W_CM = {"top": 3.0, "dress": 3.0, "jacket": 3.0}
#: B13: a button's disc is the fabric's L* moved by BUTTON_DL (darker on a light fabric, L* >= 50; lighter on a dark
#: one), its rim by BUTTON_RIM_DL; two holes in the rim's L*, 0.22 of the diameter apart. The placket's edges are
#: stitch lines STITCH_DL darker / lighter, 1 px wide.
BUTTON_DL = 25.0
BUTTON_RIM_DL = 40.0
STITCH_DL = 12.0
#: A zip: a ZIP_W_CM wide metal band of L* ZIP_L (a* = b* = 0), teeth across it every ZIP_TOOTH_CM (L* +-10), a pull
#: ZIP_PULL_CM (w x h) at its top.
ZIP_W_CM = 0.8
ZIP_L = 60.0
ZIP_TOOTH_CM = 0.25
ZIP_PULL_CM = (1.0, 2.2)
#: Lacing: eyelet pairs LACE_HALF_CM either side of the line every LACE_PITCH_CM, the cord crossing between them
#: (L* +-LACE_DL), eyelets LACE_EYE_CM across with a metal ring.
LACE_HALF_CM = 1.2
LACE_PITCH_CM = 2.5
LACE_DL = 30.0
LACE_EYE_CM = 0.5


def _polyline(px) -> tuple[np.ndarray, np.ndarray]:
    """A line's points (x, y) and the cumulative arc length at each."""
    p = np.asarray(px, np.float64).reshape(-1, 2)
    s = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]
    return p, s


def _at(p: np.ndarray, s: np.ndarray, t: float) -> tuple[np.ndarray, np.ndarray]:
    """The point at arc length ``t`` and the unit tangent there."""
    t = float(min(max(t, 0.0), s[-1]))
    k = int(min(max(np.searchsorted(s, t, side="right") - 1, 0), len(p) - 2))
    seg = p[k + 1] - p[k]
    ln = float(np.linalg.norm(seg)) or 1.0
    return p[k] + seg * ((t - s[k]) / ln), seg / ln


def _shade(base_lab, dl: float) -> np.ndarray:
    """``base_lab`` with L* moved by ``dl`` away from the fabric (darker when L* >= 50) as sRGB uint8."""
    lab = np.asarray(base_lab, np.float64).copy()
    lab[0] = float(np.clip(lab[0] - dl if lab[0] >= 50.0 else lab[0] + dl, 0.0, 100.0))
    return np.clip(np.rint(lab_to_srgb(lab)), 0, 255).astype(np.uint8)


def button_colours(base_lab) -> dict:
    """B13: the disc and the rim of a button on a fabric of ``base_lab`` -> {"disc": L*, "rim": L*, sRGB both}."""
    disc, rim = _shade(base_lab, BUTTON_DL), _shade(base_lab, BUTTON_RIM_DL)
    return {"disc": disc, "rim": rim, "disc_l": float(srgb_to_lab(disc)[0]), "rim_l": float(srgb_to_lab(rim)[0])}


def button_centres(length_px: float, px_per_cm: float, kind: str, buttons: int = 0) -> list[float]:
    """B12: the arc lengths of the buttons along a line ``length_px`` long: ``buttons`` of them (0 = automatic:
    max(1, round(length in cm / ``BUTTON_PITCH_CM[kind]``))), the j-th at (j + 0.5) x length / n."""
    n = int(buttons) if int(buttons or 0) > 0 else max(1, int(round(length_px / px_per_cm / BUTTON_PITCH_CM.get(kind, 7.0))))
    return [(j + 0.5) * length_px / n for j in range(n)]


def _disc(out: np.ndarray, sel: np.ndarray, centre, radius: float, rgb) -> None:
    h, w = sel.shape
    r = int(np.ceil(radius)) + 1
    x0, x1 = max(0, int(centre[0]) - r), min(w, int(centre[0]) + r + 1)
    y0, y1 = max(0, int(centre[1]) - r), min(h, int(centre[1]) + r + 1)
    if x1 <= x0 or y1 <= y0:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1]
    m = ((xx + 0.5 - centre[0]) ** 2 + (yy + 0.5 - centre[1]) ** 2 <= radius * radius) & sel[y0:y1, x0:x1]
    out[y0:y1, x0:x1][m] = rgb


def _band(out: np.ndarray, sel: np.ndarray, a, b, half: float, rgb) -> None:
    """Paint the pixels within ``half`` of the segment a-b."""
    h, w = sel.shape
    a, b = np.asarray(a, float), np.asarray(b, float)
    r = int(np.ceil(half)) + 1
    x0, x1 = max(0, int(min(a[0], b[0])) - r), min(w, int(max(a[0], b[0])) + r + 1)
    y0, y1 = max(0, int(min(a[1], b[1])) - r), min(h, int(max(a[1], b[1])) + r + 1)
    if x1 <= x0 or y1 <= y0:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1]
    q = np.stack([xx + 0.5, yy + 0.5], -1)
    ab = b - a
    t = np.clip(((q - a) @ ab) / max(float(ab @ ab), 1e-9), 0.0, 1.0)
    d = np.linalg.norm(q - (a + t[..., None] * ab), axis=-1)
    m = (d <= half) & sel[y0:y1, x0:x1]
    out[y0:y1, x0:x1][m] = rgb


def _inward(p: np.ndarray, s: np.ndarray, mask: np.ndarray, px_per_cm: float) -> float:
    """+1 / -1: the side of the line (left normal (-ty, tx) = +1) on which its island lies — the side whose points
    1 cm off the line fall inside ``mask`` more often (an open front's edge is the island's border)."""
    h, w = mask.shape
    score = 0
    for t in np.linspace(0.1, 0.9, 9) * s[-1]:
        c, tg = _at(p, s, t)
        nrm = np.array([-tg[1], tg[0]])
        for sign in (1, -1):
            q = c + sign * nrm * px_per_cm
            i, j = int(q[1]), int(q[0])
            if 0 <= i < h and 0 <= j < w and mask[i, j]:
                score += sign
    return 1.0 if score >= 0 else -1.0


def draw_placket(atlas: np.ndarray, masks: dict, marks: dict, *, kind: str, style: str, buttons: int,
                 px_per_cm: float, lapel: bool = False) -> tuple[np.ndarray, dict]:
    """Paint the placket ``style`` (``garment_template.PLACKETS``: buttons / zip / lacing; "none" draws nothing) of a
    ``kind`` piece into ``atlas`` along the cut's ``marks`` lines (``marks.json`` ``lines``: ``centre_front`` of a
    closed front; ``edge_left`` / ``edge_right`` of an open one), each only inside the pixels of its own island
    (``masks`` = {island name: bool mask}) — nothing outside an island changes. The fabric is read under the line
    (the median L*a*b* of the island's pixels within one placket width of it).

    - buttons, closed front: the placket's two edges stitched ``PLACKET_W_CM`` apart (none for a ``lapel``), the
      buttons on the line (``button_centres``, ``BUTTON_D_CM``, ``button_colours``, two holes);
    - buttons, open front: the buttons half a placket width inside the RIGHT front's edge (``edge_right``), the
      button holes (a slit of the diameter, the rim's L*) as far inside the LEFT front's edge — fixed sides, no
      wearer parameter (B12);
    - zip: a ``ZIP_W_CM`` metal band on the line (an open front: inside each edge), teeth, the pull at the top;
    - lacing: eyelet pairs ``LACE_HALF_CM`` either side of the line every ``LACE_PITCH_CM``, the cord crossing.

    Returns the new atlas and ``{"lines", "buttons": [[x, y], ...], "style", "fabric_l"}``."""
    out = np.array(atlas, copy=True)
    info: dict = {"style": style, "lines": [], "buttons": [], "holes": []}
    if style in (None, "", "none") or not marks or px_per_cm <= 0:
        return out, info
    lines = {k: v for k, v in marks.items() if v.get("px") and len(v["px"]) >= 2 and v.get("island") in masks}
    if not lines:
        return out, info
    width = 0.0 if lapel else PLACKET_W_CM.get(kind, 3.0) * px_per_cm
    for name, line in sorted(lines.items()):
        sel = np.asarray(masks[line["island"]], bool)
        p, s = _polyline(line["px"])
        if s[-1] <= 1.0:
            continue
        # the fabric under the line
        near = np.zeros_like(sel)
        for t in np.linspace(0.0, s[-1], max(2, int(s[-1] // max(1.0, px_per_cm)) + 1)):
            c, _ = _at(p, s, t)
            _disc(near, np.ones_like(sel), c, max(width, 2 * px_per_cm), True)
        pick = near & sel
        fab = np.median(srgb_to_lab(np.asarray(atlas, np.float64)[pick]), axis=0) if pick.any() \
            else np.array([50.0, 0.0, 0.0])
        info["fabric_l"] = round(float(fab[0]), 2)
        info["lines"].append(name)
        side = 0.0
        if name != "centre_front":
            side = _inward(p, s, sel, px_per_cm)
        off = side * width / 2.0

        def shifted(t, d=off):
            c, tg = _at(p, s, t)
            return c + np.array([-tg[1], tg[0]]) * d, tg
        if style == "buttons":
            col = button_colours(fab)
            info["button_l"] = round(col["disc_l"], 2)
            info["rim_l"] = round(col["rim_l"], 2)
            d_px = BUTTON_D_CM.get(kind, 1.1) * px_per_cm
            if name == "centre_front" and width > 0:
                stitch = _shade(fab, STITCH_DL)
                for sgn in (1, -1):
                    pts = [shifted(t, sgn * width / 2.0)[0] for t in np.linspace(0.0, s[-1], 64)]
                    for a, b in zip(pts, pts[1:]):
                        _band(out, sel, a, b, 0.5, stitch)
            for t in button_centres(s[-1], px_per_cm, kind, buttons):
                c, tg = shifted(t)
                if name == "edge_left":            # the holes side: a slit across the edge, the button's length
                    nrm = np.array([-tg[1], tg[0]])
                    _band(out, sel, c - nrm * d_px / 2.0, c + nrm * d_px / 2.0, max(1.0, 0.08 * d_px), col["rim"])
                    info["holes"].append([round(float(c[0]), 2), round(float(c[1]), 2)])
                    continue
                _disc(out, sel, c, d_px / 2.0, col["rim"])
                _disc(out, sel, c, d_px / 2.0 * 0.82, col["disc"])
                hole = 0.11 * d_px
                nrm = np.array([-tg[1], tg[0]])
                for sg in (1, -1):
                    _disc(out, sel, c + nrm * sg * hole, max(1.0, 0.09 * d_px), col["rim"])
                info["buttons"].append([round(float(c[0]), 2), round(float(c[1]), 2)])
        elif style == "zip":
            zw = ZIP_W_CM * px_per_cm
            zoff = side * zw / 2.0 if name != "centre_front" else 0.0
            metal = np.clip(np.rint(lab_to_srgb(np.array([ZIP_L, 0.0, 0.0]))), 0, 255).astype(np.uint8)
            lo = np.clip(np.rint(lab_to_srgb(np.array([ZIP_L - 10, 0.0, 0.0]))), 0, 255).astype(np.uint8)
            pts = [shifted(t, zoff)[0] for t in np.linspace(0.0, s[-1], 128)]
            for a, b in zip(pts, pts[1:]):
                _band(out, sel, a, b, zw / 2.0, metal)
            step = ZIP_TOOTH_CM * px_per_cm
            for k_, t in enumerate(np.arange(step / 2.0, s[-1], step)):
                if k_ % 2:
                    continue
                c, tg = shifted(t, zoff)
                nrm = np.array([-tg[1], tg[0]])
                _band(out, sel, c - nrm * zw * 0.4, c + nrm * zw * 0.4, max(0.5, step * 0.25), lo)
            c, tg = shifted(ZIP_PULL_CM[1] * px_per_cm / 2.0, zoff)
            nrm = np.array([-tg[1], tg[0]])
            pull = np.clip(np.rint(lab_to_srgb(np.array([ZIP_L - 5, 0.0, 0.0]))), 0, 255).astype(np.uint8)
            _band(out, sel, c - tg * ZIP_PULL_CM[1] * px_per_cm / 2.0, c + tg * ZIP_PULL_CM[1] * px_per_cm / 2.0,
                  ZIP_PULL_CM[0] * px_per_cm / 2.0, pull)
            info["zip_l"] = ZIP_L
        elif style == "lacing":
            cord = _shade(fab, LACE_DL)
            ring = np.clip(np.rint(lab_to_srgb(np.array([ZIP_L, 0.0, 0.0]))), 0, 255).astype(np.uint8)
            half = LACE_HALF_CM * px_per_cm
            step = LACE_PITCH_CM * px_per_cm
            ts = list(np.arange(step / 2.0, s[-1], step))
            pairs = []
            for t in ts:
                c, tg = shifted(t)
                nrm = np.array([-tg[1], tg[0]])
                pairs.append((c + nrm * half, c - nrm * half))
            for (a1, b1), (a2, b2) in zip(pairs, pairs[1:]):
                _band(out, sel, a1, b2, max(1.0, 0.12 * px_per_cm), cord)
                _band(out, sel, b1, a2, max(1.0, 0.12 * px_per_cm), cord)
            for a, b in pairs:
                for e in (a, b):
                    _disc(out, sel, e, LACE_EYE_CM * px_per_cm / 2.0, ring)
                    _disc(out, sel, e, LACE_EYE_CM * px_per_cm / 4.0, cord)
            info["eyelets"] = 2 * len(pairs)
    return out, info
