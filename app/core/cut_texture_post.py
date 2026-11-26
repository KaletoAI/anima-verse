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


import math
import re

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
#: (``outline_rim``'s fine pass, ``RIM_MAX_PX`` 20). 11 (2026-11-22): the eroded rim and the bleed MIRROR the core
#: across its border instead of regrowing rays from it (``cut_and_bleed``; the waist line of Lirien's dress).
#: 12 (2026-11-23, stage "details"): an invented texture field round a decorated front's motif is filled with the plain
#: fabric (``busy_halo``; Dario's dot grid).
POST_VERSION = 12
#: The version of ``draw_placket``'s painting: part of the assembly key of a piece with a placket (it is drawn onto
#: the composed atlas at assembly, never into the record's atlas — a changed placket costs no image job). 2: phase E,
#: the model's own placket is wiped first. 3: the wipe keeps a decoration reaching into its band
#: (``PLACKET_GUARD_REACH``). 4 (stage "details", 2026-11-23): the buttons take the ITEM's button colour (its text, else
#: its picture — ``garment_cut_texture.button_rgb``) instead of a lighter shade of the fabric.
PLACKET_VERSION = 4

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
    inside the islands), then filled up to ``erode_px + bleed_px`` px (chessboard) and over the whole mask by MIRRORING
    the core across its border (POST_VERSION 11; the mean-of-neighbours regrow before drew streaks). An ISLAND thinner than the erosion (no core
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
    if not core.any():
        return np.full(rgb.shape, 255, np.uint8)
    # the grown area: what the old ring-by-ring regrow reached (8-neighbour rings = chessboard distance), and the mask
    reach = ndimage.distance_transform_cdt(~core, metric="chessboard")
    filled = core | mask | (reach <= int(erode_px) + int(bleed_px))
    # MIRROR, not rays (POST_VERSION 11): a pixel outside the core takes the core pixel mirrored across the core's
    # border (nearest core pixel q, then q + (q - p)), its nearest core pixel where the mirror leaves the core. The
    # mean-of-neighbours regrow carried each border pixel straight outward: a 14 px band of streaks along every island
    # edge (Lirien's dress, live 2026-11-22: the bodice's and the skirt's bands meet at the waist and read as a
    # streaked seam line on the figure). The mirror keeps the weave's grain and brightness up to the border.
    _dist, (iy, ix) = ndimage.distance_transform_edt(~core, return_indices=True)
    h, w = mask.shape
    my = np.clip(2 * iy - np.arange(h)[:, None], 0, h - 1)
    mx = np.clip(2 * ix - np.arange(w)[None, :], 0, w - 1)
    inside = core[my, mx]
    sy = np.where(inside, my, iy)
    sx = np.where(inside, mx, ix)
    col = rgb[sy, sx]
    out = np.full(rgb.shape, 255, np.uint8)
    out[filled] = np.clip(np.rint(col[filled]), 0, 255).astype(np.uint8)
    return out


#: ``bleed_streaks`` (review 2026-11-23): a pixel of the ring round the islands (bleed + pocket fill, ``POCKET_CM``)
#: whose L* differs from the nearest island pixel's by
#: more than ``STREAK_DL`` is a streak; at most ``STREAK_SHARE`` of the ring may be one (the e2e check reads it).
STREAK_DL = 20.0
STREAK_SHARE = 0.01


def bleed_streaks(atlas, islands, bleed_px: int) -> dict:
    """The light / dark streaks in the ring of a composed atlas (``bleed_px`` round ``islands``; the record reads it at
    ``POCKET_CM``, the bleed and the pocket fill): every ring pixel
    against its nearest island pixel's L* (``STREAK_DL``). The ring is what a mip level or a bilinear sample at an
    island's border mixes in — Rosi's corset showed its pale rays as streaks on the flank. ``{ring, light, dark, share,
    limit, ok}``; an empty ring (no bleed) is ok."""
    from scipy import ndimage

    islands = np.asarray(islands, bool)
    if bleed_px <= 0 or not islands.any():
        return {"ring": 0, "light": 0, "dark": 0, "share": 0.0, "limit": STREAK_SHARE, "ok": True}
    dist, (iy, ix) = ndimage.distance_transform_edt(~islands, return_indices=True)
    ring = ~islands & (dist <= float(bleed_px))
    rgb = np.asarray(atlas)[..., :3]
    L = srgb_to_lab(rgb[ring].astype(np.float64))[:, 0]
    L0 = srgb_to_lab(rgb[iy[ring], ix[ring]].astype(np.float64))[:, 0]
    light = int((L - L0 > STREAK_DL).sum())
    dark = int((L0 - L > STREAK_DL).sum())
    n = int(ring.sum())
    share = round((light + dark) / max(1, n), 5)
    return {"ring": n, "light": light, "dark": dark, "share": share, "limit": STREAK_SHARE, "ok": share <= STREAK_SHARE}


#: ``narrow_overhang`` (review round 2026-11-25): an island narrower than this (twice its largest inner distance to
#: the background) has its overhang filled from itself. Lirien's cupped top, live: the two upper cup parts (15 x 4 cm)
#: carried a light rim from the image model into the ring round them — 25-30 % of their ring were streaks, the atlas
#: 2.07 % (``STREAK_SHARE`` 1 %); every wider island stayed at 3 % or less.
NARROW_ISLAND_CM = 5.0


def narrow_overhang(atlas, labels, px_per_cm: float, reach_px: int) -> tuple[np.ndarray, dict]:
    """The composed atlas with the ring round every NARROW island (``NARROW_ISLAND_CM``; ``labels``: the island raster,
    0 = background) taken from the island itself: each ring pixel within ``reach_px`` whose nearest island pixel
    belongs to a narrow island gets that pixel's colour (exact Euclidean distance transform) — what a bilinear sample or
    a mip level at its border mixes in is then the island's own cloth. Texture post-processing only: no key changes.
    Returns ``(atlas, {"islands": [ids], "px": n})``."""
    from scipy import ndimage

    out = np.asarray(atlas).copy()
    labels = np.asarray(labels)
    isl = labels > 0
    if not isl.any() or px_per_cm <= 0 or reach_px <= 0:
        return out, {"islands": [], "px": 0}
    inner = ndimage.distance_transform_edt(isl)
    ids = [int(i) for i in np.unique(labels[isl])]
    widest = ndimage.maximum(inner, labels, ids)
    narrow = [i for i, w in zip(ids, np.atleast_1d(widest)) if 2.0 * float(w) < NARROW_ISLAND_CM * px_per_cm]
    if not narrow:
        return out, {"islands": [], "px": 0}
    dist, (iy, ix) = ndimage.distance_transform_edt(~isl, return_indices=True)
    sel = ~isl & (dist <= float(reach_px)) & np.isin(labels[iy, ix], narrow)
    out[sel] = out[iy[sel], ix[sel]]
    return out, {"islands": narrow, "px": int(sel.sum())}


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


#: ``body_seen``: a pixel of a picture is the BODY seen through a sheer cloth when its colour is skin-like — chroma at
#: least ``C_MIN``, hue angle (a*b*, degrees) within ``HUE``, L* at least ``L_MIN`` — and everything within ``RIM`` x
#: the picture's long side of such a pixel goes with it (the cloth's outline over the leg). Review of stage 3
#: (Gelina's Moon Silk Skirt): her sheer skirt's picture read detail 0.146 (> ``DECORATED_DETAIL`` 0.10) — the legs'
#: outlines through the cloth, 28 % of its pixels skin-like —, so the front got the decorated prompt and MiniMax
#: painted a floral embroidery the skirt does not have. Without the body it reads 0.032 (plain; the glitter is fine
#: surface). Kira's lace stockings keep 0.240 (decorated), the lace thong 0.266. Measured on the item pictures with
#: the same matte (``scripts/smoke_cut_texture_detail_gates.py``).
BODY_SEEN = {"C_MIN": 15.0, "HUE": (25.0, 75.0), "L_MIN": 25.0, "RIM": 0.006}


def body_seen(rgb: np.ndarray) -> np.ndarray:
    """The ``BODY_SEEN`` mask of an (h, w, 3) picture: its skin-like pixels and their rim."""
    from scipy import ndimage
    lab = srgb_to_lab(np.asarray(rgb)[..., :3].astype(np.float64))
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    hue = np.degrees(np.arctan2(lab[..., 2], lab[..., 1]))
    b = BODY_SEEN
    skin = (chroma >= b["C_MIN"]) & (hue >= b["HUE"][0]) & (hue <= b["HUE"][1]) & (lab[..., 0] >= b["L_MIN"])
    rim = max(1, int(round(b["RIM"] * max(skin.shape))))
    return ndimage.binary_dilation(skin, iterations=rim) if skin.any() else skin


def picture_reference(rgba: np.ndarray, *, matte=garment_matte.birefnet_matte) -> dict:
    """What the answer gates and the pre-fill read from a picture (the item picture, the back view), with ONE
    ``garment_matte.cut``: ``{"colour": fabric_colour of the garment (alpha >= 128), "detail": detail_density of it,
    "detail_cloth": detail_density of it without the body seen through it (``body_seen``; None when nothing else is
    left), "fabric": the colour match's fabric pixels (alpha > 0, trimmed)}``."""
    cut, _info = garment_matte.cut(_rgba(rgba), matte=matte)
    rgb, alpha = cut[..., :3], cut[..., 3]
    garment = alpha >= 128
    cloth = garment & ~body_seen(rgb) if garment.any() else garment
    return {"colour": fabric_colour(rgb, garment) if garment.any() else None,
            "detail": detail_density(rgb, garment) if garment.any() else None,
            "detail_cloth": detail_density(rgb, cloth) if cloth.any() else None,
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


#: The weave gate (``weave_levels`` / ``weave_gates``, review of stage 3: Dario's Worn Linen Shirt, live 2026-11-22): the
#: back job painted a grey-speckled, cross-woven linen behind the front job's fine vertical stripes — every answer gate
#: passed (its detail density 0.0: ``DETAIL_SIGMA`` smooths a weave away), and the side and arm seams showed the jump.
#: ``weave_levels`` reads the high-pass ``hp`` = L* minus its Gaussian of ``sigma_cm`` over the main panel resampled to
#: ``px_per_cm`` and eroded by ``erode_cm``, twice:
#:   - ``level`` = the std of ``hp`` — the AMPLITUDE of the weave and the motif;
#:   - ``grain`` = the root of the mean MINOR eigenvalue of ``hp``'s structure tensor (its gradient products under a
#:     Gaussian of ``sigma_cm``) — the energy that has NO preferred direction. Stripes, a rib or a twill line put their
#:     whole gradient across the line (minor 0), a speckle or a cross weave puts it into both axes (minor = major).
#: The amplitude alone cannot separate the structure: the world's atlas of the same shirt (csig 3fbadeae2a1f, a
#: speckled back) reads level 5.03 -> 4.94 and passed, while the live run's comparable back 3.20 -> 5.35 failed — only
#: the front's random stripe contrast differed. The grain of the striped fronts is stable (0.50 / 0.54 in two
#: independent fronts whose level differs by 36 %), the speckled backs read 2.63-3.47: the grain is the cloth's
#: structure, not one front sample's contrast. A back answer is rejected when its level exceeds ``factor`` x the front
#: answer's + ``slack`` OR its grain exceeds ``grain_factor`` x the front answer's + ``grain_slack`` (one-sided: a
#: plainer back behind a decorated front is lower, never a fault). Measured on the saved answers (front -> back,
#: level / grain; the three linen pairs through ``post_job`` on main's islands cdacdafeb5b1 where they exist, the rest
#: registered to the template they were sent with, its main panel):
#:   bad  — Dario's linen, stage 3: 3.45 / 2.57 -> 6.06 / 3.47 (level limit 5.32: rejected); the world atlas
#:          3fbadeae2a1f: 5.03 / 0.50 -> 4.94 / 2.74 (grain limit 1.12: rejected); live 2026-11-22: 3.20 / 0.54 ->
#:          MiniMax 4.69 / 2.63, P-H3 5.35 / 3.47 (grain limit 1.17: both rejected); Tilda's cardigan 0.36 / 0.35 ->
#:          10.90 / 3.86 (an invented motif) and 8.78 / 3.22 (a rib the front lacks); Tilda's blouse be2b0531102e
#:          0.12 / 0.19 -> 12.59 / 5.36 (an invented illustration);
#:   good — Glut's gloves 12.40 / 5.08 -> 14.19 / 5.62 (limits 16.50 / 6.85), Glut's scale brief 13.28 / 6.03 ->
#:          11.78 / 5.16, Lirien's dress 0.60 / 0.44 -> 0.88 / 0.61 (limits 1.75 / 1.04), Kai's T-shirt
#:          2.41 / 1.29 -> 0.26 / 0.29, Dario's embroidered shirt (three atlases) 10.61 / 3.04 -> 0.72 / 0.42,
#:          5.93 / 2.31 -> 2.95 / 1.77, 5.99 / 2.18 -> 2.44 / 1.24.
#: ``factor`` 1.25 sits over the largest legitimate amplitude rise (1.15 x, the same scales front and back), ``slack``
#: 1.0 is two plain panels' noise; ``grain_factor`` 1.25 over the largest legitimate grain rise (1.11 x, the gloves),
#: ``grain_slack`` 0.5 over a plain panel's grain noise (Lirien +0.17). The world atlas 3fbadeae2a1f is a NEGATIVE
#: case. ``scripts/smoke_cut_texture_detail_gates.py``.
#: ``stripe_factor`` (stage "details", 2026-11-23): when the front AND the back are striped along the same axis
#: (``stripe_words``) the level limit is ``stripe_factor`` x the front's + ``slack`` — the level of a stripe is its
#: contrast, which the model draws at random (the two striped fronts above differ by 36 %). Live A/B on Dario's linen
#: back with "fine vertical stripes" (front 3.20 / 0.54): P-H3 drew faithful beige stripes, 7.47 / 0.96 (the 1.25 x
#: limit 5.00 rejected it, the grain passed); MiniMax drew blue and red candy stripes, 17.16 / 0.68 (colour gate 9.0
#: passed). Both through ``post_job`` in a dry replay of the Build. 3.0 -> limit 10.59 lies between them (their
#: geometric middle is 11.3); a speckled back is not striped and keeps ``factor``.
WEAVE_GATE = {"sigma_cm": 0.5, "px_per_cm": 10.0, "erode_cm": 1.0, "factor": 1.25, "slack": 1.0,
              "grain_factor": 1.25, "grain_slack": 0.5, "stripe_factor": 3.0}


def _weave_hp(rgb: np.ndarray, mask: np.ndarray, px_per_cm: float):
    """The high-pass of ``weave_levels`` / ``stripe_axis``: ``(hp, m, sigma)`` at ``WEAVE_GATE`` px/cm over ``mask``
    eroded, or None for a region too small to measure."""
    from scipy import ndimage
    mask = np.asarray(mask, bool)
    if px_per_cm <= 0 or mask.sum() < 16:
        return None
    g = WEAVE_GATE
    ys, xs = np.nonzero(mask)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    crop = np.asarray(rgb)[y0:y1, x0:x1, :3].astype(np.uint8)
    cm = mask[y0:y1, x0:x1]
    s = g["px_per_cm"] / float(px_per_cm)
    size = (max(1, round(cm.shape[1] * s)), max(1, round(cm.shape[0] * s)))
    small = np.asarray(Image.fromarray(crop).resize(size, Image.BOX if s < 1 else Image.BILINEAR), np.float64)
    m = np.asarray(Image.fromarray(cm.astype(np.uint8) * 255).resize(size, Image.BOX)) >= 128
    m = ndimage.binary_erosion(m, iterations=max(1, int(round(g["erode_cm"] * g["px_per_cm"]))))
    if m.sum() < 16:
        return None
    sigma = g["sigma_cm"] * g["px_per_cm"]
    L = srgb_to_lab(small)[..., 0]
    hp = L - ndimage.gaussian_filter(L, sigma)
    return hp, m, sigma


def weave_levels(rgb: np.ndarray, mask: np.ndarray, px_per_cm: float) -> dict | None:
    """``{"level", "grain"}`` of ``mask`` (``WEAVE_GATE``): None for a region too small to measure."""
    from scipy import ndimage
    got = _weave_hp(rgb, mask, px_per_cm)
    if got is None:
        return None
    hp, m, sigma = got
    gy, gx = np.gradient(hp)
    sxx, syy, sxy = (ndimage.gaussian_filter(a, sigma) for a in (gx * gx, gy * gy, gx * gy))
    minor = (sxx + syy) / 2.0 - np.sqrt(((sxx - syy) / 2.0) ** 2 + sxy ** 2)
    return {"level": round(float(hp[m].std()), 3), "grain": round(float(np.sqrt(max(minor[m].mean(), 0.0))), 3)}


def weave_axis(rgb: np.ndarray, mask: np.ndarray, px_per_cm: float) -> dict | None:
    """The weave's direction over ``mask`` (``WEAVE_GATE``'s high-pass): the mean structure tensor of ``hp``
    (``sxx`` / ``syy`` / ``sxy``, gradient products averaged over the eroded panel) gives ``coherence`` = (major -
    minor) / (major + minor) — 1 for parallel lines, 0 for a speckle or lines in every direction — and ``angle`` = the
    direction the LINES run, in degrees from the vertical (0 = vertical, 90 = horizontal; the gradient runs across
    them). None for a region too small to measure."""
    got = _weave_hp(rgb, mask, px_per_cm)
    if got is None:
        return None
    hp, m, _sigma = got
    gy, gx = np.gradient(hp)
    sxx, syy, sxy = float((gx * gx)[m].mean()), float((gy * gy)[m].mean()), float((gx * gy)[m].mean())
    root = math.hypot((sxx - syy) / 2.0, sxy)
    tr = (sxx + syy) / 2.0
    coherence = root / tr if tr > 1e-12 else 0.0
    grad = 0.5 * math.degrees(math.atan2(2.0 * sxy, sxx - syy))     # the gradient's angle from the x axis
    angle = abs(((grad + 90.0) % 180.0) - 90.0)                       # lines run across it: 0 = vertical lines
    return {"coherence": round(coherence, 3), "angle": round(angle, 1)}


#: Stage "details" (2026-11-23, Dario's Worn Linen Shirt): the back job's prompt said "the fine weave", and both
#: backends painted a speckled cross weave (grain 2.63 / 3.47) behind the front answer's fine vertical stripes (grain
#: 0.54) — the back view itself reads grain 0.67, the models invented the speckle, the weave gate rejected it rightly.
#: So the back prompt NAMES the stripes when the FRONT answer's main panel is striped (``stripe_words``): its grain at
#: most ``grain_share`` x its level, its level at least ``min_level``, its ``weave_axis`` coherence at least
#: ``coherence`` and its lines within ``axis_deg`` of the vertical or the horizontal. Measured on the 53 saved front
#: answers (the template's largest island over the raw answer; grain / level, coherence, line angle): the striped linen
#: 0.18, 0.95, 0.6 deg — the only one named; Glut's scale bra 0.14, 0.84, 55.7 deg (diagonal scales: "fine weave"; a
#: bra has no back job anyway); Ylva's wrap skirt (a pasted product photo) 0.23, 0.17; Dario's embroidered fronts
#: 0.35-0.69, coherence <= 0.13; every other front 0.35 and up. ``grain_share`` 0.22 lies between 0.18 and 0.23, the
#: coherence floor 0.5 keeps an oriented photo or embroidery out on a second count, ``min_level`` 1.5 is above a plain
#: panel's noise (<= 0.9). ``scripts/smoke_cut_texture_details.py`` [1].
STRIPES = {"grain_share": 0.22, "min_level": 1.5, "coherence": 0.5, "axis_deg": 30.0}
#: The weave words of the back prompt: the default (every non-striped front, the old wording byte for byte) and the
#: striped ones by axis.
WEAVE_WORDS = {"": "fine weave", "vertical": "fine vertical stripes", "horizontal": "fine horizontal stripes"}


def stripe_words(levels: dict | None, axis: dict | None) -> str:
    """The back prompt's weave words (``STRIPES``, ``WEAVE_WORDS``) from the FRONT answer's ``weave_levels`` and
    ``weave_axis``: "fine vertical stripes" / "fine horizontal stripes" for a striped front, else "fine weave"."""
    g = STRIPES
    if not isinstance(levels, dict) or not isinstance(axis, dict):
        return WEAVE_WORDS[""]
    level, grain = float(levels.get("level") or 0.0), float(levels.get("grain") or 0.0)
    if level < g["min_level"] or grain > g["grain_share"] * level or float(axis.get("coherence") or 0.0) < g["coherence"]:
        return WEAVE_WORDS[""]
    angle = float(axis.get("angle") or 0.0)
    if angle <= g["axis_deg"]:
        return WEAVE_WORDS["vertical"]
    if angle >= 90.0 - g["axis_deg"]:
        return WEAVE_WORDS["horizontal"]
    return WEAVE_WORDS[""]


def weave_gates(back: dict | None, front: dict | None) -> list[dict]:
    """The weave gates of a back answer (``WEAVE_GATE``) against the front answer's levels: ``weave`` (the level) and
    ``grain``; [] without both (a level of another shape — a float — is none)."""
    if not isinstance(back, dict) or not isinstance(front, dict):
        return []
    g = WEAVE_GATE
    out = []
    # stage "details": front and back striped along the same axis (``stripe_words``) — the level is the stripes'
    # contrast, which the model draws at random, so it gets ``stripe_factor``; the grain gate is unchanged
    words = stripe_words(front, front.get("axis"))
    striped = words != WEAVE_WORDS[""] and stripe_words(back, back.get("axis")) == words
    for gate, key, factor, slack in (("weave", "level", g["stripe_factor"] if striped else g["factor"], g["slack"]),
                                     ("grain", "grain", g["grain_factor"], g["grain_slack"])):
        if back.get(key) is None or front.get(key) is None:
            continue
        b, f = float(back[key]), float(front[key])
        lim = round(factor * f + slack, 3)
        ok = b <= lim
        out.append({"gate": gate, "ok": ok, "value": b, "limit": lim, "front": f, "striped": striped,
                    "text": "" if ok else f"back {gate} {b:.2f} > {lim:.2f} (the front's {f:.2f})"})
    return out


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


#: Stage "details" (2026-11-23, Dario's embroidered shirt: MiniMax set the embroidery on a rectangle of raised dots —
#: a "dot grid" the item does not show — and every gate passed; the plain linen around it is the item's).
#: ``busy_halo`` finds such an invented texture field on a FRONT panel: the DECORATION is every pixel more than
#: ``deco_de`` (dE76) from the panel's base fabric whose component's box is at least ``deco_cm`` long (an embroidery
#: stroke, a print; a single dot of the grid is ~0.3 cm), grown by ``keep_cm``; the decoration is set to the base
#: lightness, then the local texture energy = the root of the Gaussian (``energy_cm``) mean of the squared L* high-pass
#: (L* minus its Gaussian of ``hp_cm``). The panel's quiet level is the median energy of the panel away from the
#: decoration (``away_cm``); a pixel is busy above ``factor`` x that level and ``floor``; busy components smaller
#: than ``min_cm`` square are dropped, and so is every busy pixel within ``near_cm`` of the decoration (the gaps between
#: strokes and a faint motif round them stay). Applied only to the FRONT job of a top-family piece whose prompt was
#: "decorated" (``refs["halo"]``): on the 53 saved fronts the measure also flags a plain leather jacket's zip shading
#: (0.118 of the panel), Kai's jeans' whiskers (0.103) and Kira's lace (0.150) — real details, none decorated-top.
#: Measured on the registered ANSWER (``resample_register``: the answer at the atlas frame; the colour match after it
#: flattens the contrast, so it is not measured there), 13.5-13.9 px/cm, high-pass 0.3 cm, energy 0.75 cm, inside the
#: panel eroded by ``edge_cm`` (its outline is no texture field). Group B's dot grid (Dario, 1947cab1874c): quiet 2.32
#: -> limit 4.18, 0.139 of the panel cleared. This stage's live answer (2026-11-23, MiniMax again, 7f908766420a): a
#: fainter grid on smoother linen — plain 0.55-0.60 (p10-p90), dots 3.0-4.7, median 3.7, quiet 0.65: ``floor`` 3.0
#: kept most of it, 2.0 clears 0.041. At 2.0 Dario's clean front 849e gives 0.051 (the model's own placket line, which
#: the placket wipes anyway), dario-v7 0.004, Ylva's moon dress 0.001 (its grey motif is decoration), Tilda's
#: blouses 0-0.016, the linen fronts 0-0.012. The busy pixels that are not decoration are filled from the panel's
#: plainest patch (``tile_fill``).
HALO = {"deco_de": 30.0, "deco_cm": 1.0, "keep_cm": 0.15, "hp_cm": 0.3, "energy_cm": 0.75, "away_cm": 1.0,
        "factor": 1.8, "floor": 2.0, "min_cm": 2.0, "near_cm": 0.6, "edge_cm": 0.9}


def busy_halo(img: np.ndarray, panel: np.ndarray, base_lab, px_per_cm: float) -> tuple[np.ndarray, dict]:
    """The invented texture field of a front panel (``HALO``): ``(mask of the busy non-decoration pixels, info)`` —
    ``info`` = ``{"px", "quiet", "limit"}``; an empty mask when the panel is too small or nothing is busy."""
    from scipy import ndimage
    g = HALO
    empty = np.zeros(np.asarray(panel).shape, bool)
    if px_per_cm <= 0:
        return empty, {"px": 0}
    # the panel's own border (the answer's outline, the rim) is never a texture field
    panel = ndimage.binary_erosion(np.asarray(panel, bool), iterations=max(1, int(round(g["edge_cm"] * px_per_cm))))
    if panel.sum() < 64:
        return empty, {"px": 0}
    ys, xs = np.nonzero(panel)
    y0, y1 = max(0, ys.min() - 2), ys.max() + 3
    x0, x1 = max(0, xs.min() - 2), xs.max() + 3
    sub = np.asarray(img)[y0:y1, x0:x1, :3].astype(np.float64)
    pm = panel[y0:y1, x0:x1]
    lab = srgb_to_lab(sub)
    base = np.asarray(base_lab, np.float64)
    far = (np.linalg.norm(lab - base, axis=-1) > g["deco_de"]) & pm
    labels, _n = ndimage.label(far)
    long_px = g["deco_cm"] * px_per_cm
    deco = np.zeros_like(far)
    for i, sl in enumerate(ndimage.find_objects(labels), 1):
        if sl is not None and max(sl[0].stop - sl[0].start, sl[1].stop - sl[1].start) >= long_px:
            deco[sl] |= labels[sl] == i
    keep = ndimage.binary_dilation(deco, iterations=max(1, int(round(g["keep_cm"] * px_per_cm)))) if deco.any() \
        else deco
    L = np.where(keep | ~pm, base[0], lab[..., 0])
    hp = L - ndimage.gaussian_filter(L, g["hp_cm"] * px_per_cm)
    energy = np.sqrt(ndimage.gaussian_filter(hp * hp, g["energy_cm"] * px_per_cm))
    away = pm & ~(ndimage.binary_dilation(deco, iterations=max(1, int(round(g["away_cm"] * px_per_cm))))
                  if deco.any() else deco)
    if away.sum() < 64:
        return empty, {"px": 0}
    quiet = float(np.median(energy[away]))
    limit = max(g["factor"] * quiet, g["floor"])
    busy = (energy > limit) & pm
    if deco.any():
        # only a field AWAY from the decoration: the gaps between strokes and a faint motif round them stay
        busy &= ndimage.distance_transform_edt(~deco) >= g["near_cm"] * px_per_cm
    lab_b, _nb = ndimage.label(busy)
    min_area = (g["min_cm"] * px_per_cm) ** 2
    sizes = ndimage.sum(busy, lab_b, range(1, _nb + 1)) if _nb else []
    big = np.zeros(_nb + 1, bool)
    big[1:] = np.asarray(sizes) >= min_area
    busy = big[lab_b] & ~keep
    out = empty.copy()
    out[y0:y1, x0:x1] = busy
    return out, {"px": int(busy.sum()), "quiet": round(quiet, 3), "limit": round(limit, 3)}


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


def button_colours(base_lab, button_rgb=None) -> dict:
    """B13: the disc and the rim of a button on a fabric of ``base_lab`` -> {"disc": L*, "rim": L*, sRGB both}. With
    the item's own ``button_rgb`` (stage "details") the disc is that colour and the rim ``BUTTON_RIM_OWN_DL`` darker
    (lighter on a disc darker than L* 30)."""
    if button_rgb is not None:
        disc = np.clip(np.rint(np.asarray(button_rgb, np.float64)[:3]), 0, 255).astype(np.uint8)
        lab = srgb_to_lab(disc.astype(np.float64))
        rim_lab = np.array(lab, np.float64)
        rim_lab[0] = float(np.clip(lab[0] - BUTTON_RIM_OWN_DL if lab[0] >= 30.0 else lab[0] + BUTTON_RIM_OWN_DL,
                                   0.0, 100.0))
        rim = np.clip(np.rint(lab_to_srgb(rim_lab)), 0, 255).astype(np.uint8)
    else:
        disc, rim = _shade(base_lab, BUTTON_DL), _shade(base_lab, BUTTON_RIM_DL)
    return {"disc": disc, "rim": rim, "disc_l": float(srgb_to_lab(disc)[0]), "rim_l": float(srgb_to_lab(rim)[0])}


#: The rim of a button in the item's own colour: this much darker in L* (``button_colours``).
BUTTON_RIM_OWN_DL = 15.0
#: Stage "details" (2026-11-23, Dario's embroidered shirt: the painted buttons came out light green — a shade of the
#: fabric — where the item picture shows copper-brown ones). ``picture_buttons`` finds the buttons in an item picture
#: that is a garment on white: the picture at ``long`` px on its long side; the garment = not near-white (any channel
#: below 225), eroded 3 px; a candidate pixel is more than ``de`` (dE76) from the picture's base fabric
#: (``fabric_colour``); a button is a candidate component whose box's long side is ``d_min``-``d_max`` of the garment's
#: width, at most ``aspect`` long for its width and filling at least ``fill`` of its box (a round disc fills 0.79, a
#: thin embroidery star or a stroke far less); the buttons are the largest set of at least ``min_count`` such discs
#: whose centres lie within ``column`` x the width of one another's x (one placket line). Measured: Dario's embroidered
#: shirt (512 px, width 383): 8 discs, the five on x 194-196 (d 8-9 px, fill 0.68-0.78), the three embroidery stars
#: at x 261-277 (d 5) -> copper (140, 68, 19); his linen shirt: 3 at x 152-166 -> wood (166, 134, 109); Kira's blazer
#: (two buttons on black): 1 disc -> none (her text names "silver buttons").
BUTTON_FIND = {"long": 512, "de": 25.0, "d_min": 0.012, "d_max": 0.06, "aspect": 1.6, "fill": 0.55, "column": 0.04,
               "min_count": 3}


def picture_buttons(rgb) -> dict | None:
    """The buttons of an item picture on white (``BUTTON_FIND``): ``{"rgb", "count", "x"}`` — the median colour of
    the discs' inner pixels, their number and their mean x (share of the picture width) —, or None."""
    from scipy import ndimage
    g = BUTTON_FIND
    im = Image.fromarray(np.asarray(rgb)[..., :3].astype(np.uint8))
    s = g["long"] / float(max(im.size))
    im = im.resize((max(1, round(im.size[0] * s)), max(1, round(im.size[1] * s))), Image.LANCZOS)
    a = np.asarray(im).astype(np.float64)
    garment = ndimage.binary_erosion((255.0 - a).max(-1) > 30.0, iterations=3)
    if garment.sum() < 64:
        return None
    xs = np.nonzero(garment)[1]
    width = float(xs.max() - xs.min() + 1)
    fab = fabric_colour(np.asarray(im), garment)
    if not fab:
        return None
    de = np.linalg.norm(srgb_to_lab(a) - np.asarray(fab["lab"], np.float64), axis=-1)
    labels, _n = ndimage.label((de > g["de"]) & garment)
    discs = []
    for i, sl in enumerate(ndimage.find_objects(labels), 1):
        if sl is None:
            continue
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        d = max(h, w)
        if not (g["d_min"] * width <= d <= g["d_max"] * width) or d / max(1, min(h, w)) > g["aspect"]:
            continue
        if (labels[sl] == i).sum() / float(h * w) < g["fill"]:
            continue
        discs.append(((sl[1].start + sl[1].stop) / 2.0, i))
    best: list = []
    for cx, _i in discs:
        group = [d for d in discs if abs(d[0] - cx) <= g["column"] * width]
        if len(group) > len(best):
            best = group
    if len(best) < g["min_count"]:
        return None
    sel = np.isin(labels, [i for _x, i in best])
    inner = ndimage.binary_erosion(sel)
    px = a[inner if inner.sum() >= 10 else sel]
    return {"rgb": [int(round(v)) for v in np.median(px, axis=0)], "count": len(best),
            "x": round(float(np.mean([x for x, _i in best])) / a.shape[1], 3)}


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


#: Phase E: before the code paints a placket, the model's own (a picture of a buttoned shirt or a laced front shows one,
#: whatever the prompt says) is wiped — every island pixel within the painted placket's half width plus this margin
#: of the line takes the pixel twice that distance further out on its side (the weave goes on, nothing doubles).
PLACKET_CLEAR_CM = 0.4
#: ``_wipe_line``: a source pixel farther than this (largest channel) from the ring's median fabric is a detail.
PLACKET_CLEAR_DETAIL = 40
#: ``_wipe_line``, review of stage 3 (Dario's embroidered shirt: the embroidery on the chest beside the placket): a
#: connected detail (8-connected pixels ``PLACKET_CLEAR_DETAIL`` off the ring's median, inside the island) is the
#: item's DECORATION and is never wiped when at least as many of its pixels lie outside the wipe band as inside it
#: (counted within ``PLACKET_GUARD_REACH`` x the band's half width of the line). The model's own placket — stitch
#: lines and buttons on the line — lies inside the band; an embroidery, a print or a pocket that reaches into it from
#: the side lies mostly outside. Its pixels and a ``PLACKET_GUARD_PX`` rim round them (the soft edge) keep their colour.
PLACKET_GUARD_REACH = 3.0
PLACKET_GUARD_PX = 1


def placket_clear_px(kind: str, style: str, px_per_cm: float, lapel: bool = False) -> float:
    """The wipe's half width in pixels: the widest thing ``draw_placket`` paints across the line for ``style`` (the
    placket band / a button, the zip's pull, the eyelets) + ``PLACKET_CLEAR_CM``."""
    if style == "buttons":
        half = max(0.0 if lapel else PLACKET_W_CM.get(kind, 3.0) / 2.0, BUTTON_D_CM.get(kind, 1.1) / 2.0)
    elif style == "zip":
        half = max(ZIP_W_CM, ZIP_PULL_CM[0]) / 2.0
    elif style == "lacing":
        half = LACE_HALF_CM + LACE_EYE_CM / 2.0
    else:
        return 0.0
    return round((half + PLACKET_CLEAR_CM) * px_per_cm, 6)


def _wipe_line(out: np.ndarray, src: np.ndarray, sel: np.ndarray, p: np.ndarray, half: float) -> dict:
    """Replace the ``sel`` pixels within ``half`` of the polyline ``p`` with the pixel 2 x ``half`` further out along
    their own direction from the line (read from ``src``); one whose source lies off the island (or off the atlas) or
    is a detail (``PLACKET_CLEAR_DETAIL`` off the median) takes the median colour of the island's pixels between ``half`` and 2 x ``half`` of the line.
    A decoration reaching into the band from the side is kept (``PLACKET_GUARD_REACH``). Returns ``{"wiped",
    "kept"}`` — the pixels replaced and the band pixels a decoration kept — and ``"guard"``, the kept decoration's
    pixels (with their rim) as a mask of the atlas (None without one): ``draw_placket`` paints nothing on them."""
    from scipy import ndimage
    h, w = sel.shape
    r = int(np.ceil(PLACKET_GUARD_REACH * half)) + 2
    x0, x1 = max(0, int(p[:, 0].min()) - r), min(w, int(p[:, 0].max()) + r + 1)
    y0, y1 = max(0, int(p[:, 1].min()) - r), min(h, int(p[:, 1].max()) + r + 1)
    if x1 <= x0 or y1 <= y0:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1]
    q = np.stack([xx + 0.5, yy + 0.5], -1).reshape(-1, 2)
    best = np.full(len(q), np.inf)
    near = np.zeros((len(q), 2))
    for a, b in zip(p[:-1], p[1:]):
        ab = b - a
        t = np.clip(((q - a) @ ab) / max(float(ab @ ab), 1e-9), 0.0, 1.0)
        c = a + t[:, None] * ab
        d = np.linalg.norm(q - c, axis=1)
        m = d < best
        best[m], near[m] = d[m], c[m]
    tg = p[-1] - p[0]
    tg = tg / max(float(np.linalg.norm(tg)), 1e-9)
    nrm = np.array([-tg[1], tg[0]])
    off = q - near
    ln = np.linalg.norm(off, axis=1)
    side = np.where(ln[:, None] > 1e-6, off / np.maximum(ln, 1e-6)[:, None], nrm[None, :] * np.sign(off @ nrm + 1e-9)[:, None])
    inside = sel[y0:y1, x0:x1].reshape(-1)
    wipe = inside & (best <= half)
    ring = inside & (best > half) & (best <= 2 * half)
    if not wipe.any():
        return {"wiped": 0, "kept": 0, "guard": None}
    fallback = np.median(src[y0:y1, x0:x1].reshape(-1, 3)[ring], axis=0) if ring.any() else None
    kept = 0
    guard_full = None
    if fallback is not None:
        # the decoration guard: a connected detail mostly outside the band is the item's own (an embroidery beside
        # the placket), never the model's placket — its band pixels stay
        win = src[y0:y1, x0:x1].reshape(-1, 3).astype(np.int32)
        det = inside & (np.abs(win - fallback.astype(np.int32)).max(axis=1) > PLACKET_CLEAR_DETAIL) \
            & (best <= PLACKET_GUARD_REACH * half)
        comp, n = ndimage.label(det.reshape(y1 - y0, x1 - x0), structure=np.ones((3, 3), bool))
        if n:
            flat = comp.reshape(-1)
            n_in = np.bincount(flat, weights=(best <= half).astype(float), minlength=n + 1)
            n_out = np.bincount(flat, weights=(best > half).astype(float), minlength=n + 1)
            deco = (n_out >= n_in) & (n_out > 0)
            deco[0] = False
            guard = deco[comp]
            if guard.any():
                guard = ndimage.binary_dilation(guard, structure=np.ones((3, 3), bool), iterations=PLACKET_GUARD_PX)
                guard_full = np.zeros((h, w), bool)
                guard_full[y0:y1, x0:x1] = guard & sel[y0:y1, x0:x1]
                guard = guard.reshape(-1)
                kept = int((wipe & guard).sum())
                wipe &= ~guard
        if not wipe.any():
            return {"wiped": 0, "kept": kept, "guard": guard_full}
    s_ = np.rint(q[wipe] + side[wipe] * 2 * half - 0.5).astype(int)
    ok = (s_[:, 0] >= 0) & (s_[:, 0] < w) & (s_[:, 1] >= 0) & (s_[:, 1] < h)
    ok[ok] = sel[s_[ok, 1], s_[ok, 0]]
    tgt = np.argwhere(wipe.reshape(y1 - y0, x1 - x0)) + np.array([y0, x0])
    vals = np.empty((len(tgt), 3), out.dtype)
    vals[ok] = src[s_[ok, 1], s_[ok, 0]]
    if fallback is not None:
        # a source pixel that is a detail (a print, an embroidery stitch) is not copied in: the median fabric instead
        far = np.abs(vals.astype(np.int32) - fallback.astype(np.int32)).max(axis=1) > PLACKET_CLEAR_DETAIL
        ok &= ~far
    if (~ok).any():
        vals[~ok] = fallback if fallback is not None else src[tgt[~ok, 0], tgt[~ok, 1]]
    out[tgt[:, 0], tgt[:, 1]] = vals
    return {"wiped": int(len(tgt)), "kept": kept, "guard": guard_full}


#: Corset v3 (review 2026-11-22): a sewn seam with its boning channel (``draw_seams``) — a groove SEAM_GROOVE_CM wide
#: SEAM_DL darker than the fabric under it, a stitch line STITCH_DL darker SEAM_HALF_CM either side. A seam is a shadow,
#: so it is darker on every fabric of L* >= SEAM_DARK_MIN_L (``_shade`` turns at L* 50: on a red of L* 45 the first
#: dry run drew light lines); only a near-black fabric gets lighter lines. Part of the assembly key
#: (``garment_cut_texture.placket_key``).
#: 2 / 3 (corset v7, review 2026-11-23 of v6; 3 adds ``_forward_points``): a seam that crosses the grid's rows (``seam_cup_*``, under the cups) runs
#: through the vertices of the row nearest its line in each column, a stair of one row at each change, and the pattern
#: folds back on itself at the centre front: a point that steps back across the panel is dropped (``_forward_points``)
#: and the rest smoothed (``SEAM_CROSS_SMOOTH`` rounds of (1, 2, 1) / 4, the two ends held) before it is drawn.
SEAM_VERSION = 3
SEAM_CROSS_PREFIX = "seam_cup_"
SEAM_CROSS_SMOOTH = 6
SEAM_GROOVE_CM = 0.12
SEAM_DL = 16.0
SEAM_HALF_CM = 0.35
SEAM_DARK_MIN_L = 25.0


def _seam_shade(base_lab, dl: float) -> np.ndarray:
    """``base_lab`` with L* lowered by ``dl`` (raised for a negative one), as sRGB uint8."""
    lab = np.asarray(base_lab, np.float64).copy()
    lab[0] = float(np.clip(lab[0] - dl, 0.0, 100.0))
    return np.clip(np.rint(lab_to_srgb(lab)), 0, 255).astype(np.uint8)


def _forward_points(px) -> np.ndarray:
    """``px`` (n x 2) without the points that step back across the panel (SEAM_VERSION 2): a seam that runs across the
    panel (first to last point) keeps a point only when it lies further along x than every point kept before it — where
    the panel's pattern folds back on itself between two columns (the centre front between the cups) the line would
    otherwise draw a loop, a spike on the model."""
    p = np.asarray(px, np.float64).reshape(-1, 2)
    if len(p) < 3:
        return p
    sign = 1.0 if p[-1, 0] >= p[0, 0] else -1.0
    keep, far = [0], sign * p[0, 0]
    for i in range(1, len(p)):
        if sign * p[i, 0] > far:
            keep.append(i)
            far = sign * p[i, 0]
    return p[keep]


def _smooth_points(px, rounds: int) -> np.ndarray:
    """``px`` (n x 2) after ``rounds`` of (1, 2, 1) / 4 on every inner point, the two ends held (SEAM_VERSION 2)."""
    p = np.asarray(px, np.float64).reshape(-1, 2).copy()
    for _ in range(max(0, int(rounds))):
        if len(p) < 3:
            break
        p[1:-1] = (p[:-2] + 2.0 * p[1:-1] + p[2:]) / 4.0
    return p


def draw_seams(atlas: np.ndarray, masks: dict, marks: dict, *, px_per_cm: float) -> tuple[np.ndarray, dict]:
    """Paint every ``seam_*`` line of the cut's ``marks`` (``corset_darts.seam_lines``) into ``atlas``, each only
    inside its own island (``masks``): the groove on the line, the two stitch lines beside it (``SEAM_*``), shaded
    from the fabric's median L*a*b* within 2 cm of the line. Returns the new atlas and ``{"seams": [names]}``."""
    out = np.array(atlas, copy=True)
    info: dict = {"seams": []}
    if not marks or px_per_cm <= 0:
        return out, info
    for name, line in sorted(marks.items()):
        if not name.startswith("seam_") or not line.get("px") or len(line["px"]) < 2 \
                or line.get("island") not in masks:
            continue
        sel = np.asarray(masks[line["island"]], bool)
        px = line["px"]
        if name.startswith(SEAM_CROSS_PREFIX):
            px = _smooth_points(_forward_points(px), SEAM_CROSS_SMOOTH)
        p, s = _polyline(px)
        if s[-1] <= 1.0:
            continue
        near = np.zeros_like(sel)
        for t in np.linspace(0.0, s[-1], max(2, int(s[-1] // max(1.0, px_per_cm)) + 1)):
            c, _ = _at(p, s, t)
            _disc(near, np.ones_like(sel), c, 2 * px_per_cm, True)
        pick = near & sel
        fab = np.median(srgb_to_lab(np.asarray(atlas, np.float64)[pick]), axis=0) if pick.any() \
            else np.array([50.0, 0.0, 0.0])
        sign = 1.0 if fab[0] >= SEAM_DARK_MIN_L else -1.0
        groove = _seam_shade(fab, sign * SEAM_DL)
        stitch = _seam_shade(fab, sign * STITCH_DL)
        ts = np.linspace(0.0, s[-1], max(16, int(s[-1] // 2)))
        frames = [_at(p, s, t) for t in ts]
        for d, half, col in ((0.0, max(0.6, SEAM_GROOVE_CM * px_per_cm / 2.0), groove),
                             (SEAM_HALF_CM * px_per_cm, 0.5, stitch), (-SEAM_HALF_CM * px_per_cm, 0.5, stitch)):
            pts = [c + np.array([-tg[1], tg[0]]) * d for c, tg in frames]
            for a, b in zip(pts, pts[1:]):
                _band(out, sel, a, b, half, col)
        info["seams"].append(name)
    return out, info


def draw_placket(atlas: np.ndarray, masks: dict, marks: dict, *, kind: str, style: str, buttons: int,
                 px_per_cm: float, lapel: bool = False, button_rgb=None) -> tuple[np.ndarray, dict]:
    """Paint the placket ``style`` (``garment_template.PLACKETS``: buttons / zip / lacing; "none" draws nothing) of a
    ``kind`` piece into ``atlas`` along the cut's ``marks`` lines (``marks.json`` ``lines``: ``centre_front`` of a
    closed front; ``edge_left`` / ``edge_right`` of an open one), each only inside the pixels of its own island
    (``masks`` = {island name: bool mask}) — nothing outside an island changes. The fabric is read under the line
    (the median L*a*b* of the island's pixels within one placket width of it). Phase E: first the model's own placket
    is wiped along every line (``placket_clear_px``, ``_wipe_line``), so the code's placket is the only one.

    - buttons, closed front: the placket's two edges stitched ``PLACKET_W_CM`` apart (none for a ``lapel``), the
      buttons on the line (``button_centres``, ``BUTTON_D_CM``, ``button_colours``: the item's ``button_rgb`` when
      known, else a shade of the fabric; two holes);
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
    # phase E: the model's own placket goes first (a second one beside the painted one was the risk)
    clean = np.array(atlas, copy=True)
    clear_px = placket_clear_px(kind, style, px_per_cm, lapel=lapel)
    info["wipe"] = {"wiped": 0, "kept": 0}
    protect = None
    for name, line in sorted(lines.items()):
        p, s = _polyline(line["px"])
        if s[-1] > 1.0 and clear_px > 0:
            got = _wipe_line(clean, np.asarray(atlas), np.asarray(masks[line["island"]], bool), p, clear_px)
            info["wipe"] = {k: info["wipe"][k] + got[k] for k in ("wiped", "kept")}
            if got.get("guard") is not None:
                protect = got["guard"] if protect is None else protect | got["guard"]
    out = np.array(clean, copy=True)
    atlas = clean
    for name, line in sorted(lines.items()):
        sel = np.asarray(masks[line["island"]], bool)
        p, s = _polyline(line["px"])
        if s[-1] <= 1.0:
            continue
        if protect is not None:
            # a kept decoration (``_wipe_line``) is painted over by nothing — no stitch line, button or zip across it
            sel = sel & ~protect
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
        if not name.startswith("centre_"):
            side = _inward(p, s, sel, px_per_cm)
        off = side * width / 2.0

        def shifted(t, d=off):
            c, tg = _at(p, s, t)
            return c + np.array([-tg[1], tg[0]]) * d, tg
        if style == "buttons":
            col = button_colours(fab, button_rgb)
            info["button_l"] = round(col["disc_l"], 2)
            info["rim_l"] = round(col["rim_l"], 2)
            d_px = BUTTON_D_CM.get(kind, 1.1) * px_per_cm
            if name.startswith("centre_") and width > 0:
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
            zoff = side * zw / 2.0 if not name.startswith("centre_") else 0.0
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


# ----------------------------------------------------------------------------------------------------------- trousers

#: Round 2026-11-25 (Kai's jeans: the fly, the waistband and the back pockets the parameters ask for never appeared —
#: no step of the chain asked for them): a trouser's construction details are painted by code onto the composed atlas at
#: assembly, like the placket (``draw_trouser_details``), along lines derived from the cut's own seams
#: (``trouser_lines``: the ``islands.json`` seam samples, 1 cm apart in 3D, matched on both sides) — no image job, no
#: Blender run. Part of the assembly key of a trouser piece (``garment_cut_texture.placket_key``).
TROUSER_DETAIL_VERSION = 1
#: The fly (``fly`` zip / buttons): a J-shaped double topstitch on the LEFT front panel (the wearer's; fixed side, no
#: parameter) FLY_W_CM inside the centre-front seam, FLY_LEN_CM down from the waist seam — at most to FLY_CROTCH_CLEAR_CM
#: above the seam's lower end (the crotch); under FLY_MIN_CM of seam there is no fly. A button fly shows FLY_BUTTONS
#: buttons of FLY_BUTTON_D_CM half way between the seam and the J.
FLY_W_CM = 3.5
FLY_LEN_CM = 17.0
FLY_CROTCH_CLEAR_CM = 4.0
FLY_MIN_CM = 8.0
FLY_BUTTONS = 4
FLY_BUTTON_D_CM = 1.1
#: Double topstitching: the second row this far from the first; a thread THREAD_W_CM wide, dashed THREAD_DASH_CM on /
#: THREAD_GAP_CM off; the first row of a seam lies THREAD_IN_CM off it.
STITCH_GAP_CM = 0.6
THREAD_W_CM = 0.1
THREAD_DASH_CM = 0.3
THREAD_GAP_CM = 0.12
THREAD_IN_CM = 0.2
#: A sewn edge (the fly's edge, a patch pocket's outline, a yoke, a belt loop's sides) is a groove SEAM_GROOVE_CM wide,
#: SEAM_DL darker (``_seam_shade``; lighter only on a near-black fabric, as ``draw_seams``).
TROUSER_GROOVE_CM = 0.12
#: The waistband's button (a fly and a waistband): a metal shank button of BAND_BUTTON_D_CM at the centre front, in the
#: middle of the band's height; rivets of RIVET_D_CM at the jeans' front-pocket corners.
BAND_BUTTON_D_CM = 1.7
RIVET_D_CM = 0.55
#: Belt loops (``trouser_waist`` belt): LOOP_W_CM wide over the band's height, at the centre back (split by the band's
#: opening: half at each end), BACK_LOOP_CM either side of it, SIDE_LOOP_BACK_CM behind each side seam and
#: FRONT_LOOP_CM either side of the centre front — 7 loops. A loop is LOOP_DL lighter than the band (darker on a light
#: fabric) with grooved sides and a bar tack at each end.
LOOP_W_CM = 1.0
BACK_LOOP_CM = 7.0
SIDE_LOOP_BACK_CM = 1.5
FRONT_LOOP_CM = 9.0
LOOP_DL = 6.0
#: A bar tack: BAR_TACK_CM long across its line, BAR_TACK_W_CM wide, solid thread.
BAR_TACK_CM = 0.8
BAR_TACK_W_CM = 0.18
#: Front pockets: the opening runs from the waist seam FRONT_POCKET_IN_CM from the centre front to the side seam
#: FRONT_POCKET_DEPTH_CM under its top — a scoop (jeans: the quadratic curve through the corner under its start) or a
#: slant (tailored: straight, TAILORED_POCKET_DEPTH_CM deep).
FRONT_POCKET_IN_CM = 10.0
FRONT_POCKET_DEPTH_CM = 8.0
TAILORED_POCKET_DEPTH_CM = 16.0
#: Back (jeans): the yoke from the centre-back seam YOKE_CB_CM under the waist seam to the side seam YOKE_SIDE_CM under
#: it; a patch pocket BACK_POCKET_W_CM wide, BACK_POCKET_SIDE_CM down its sides and BACK_POCKET_H_CM down its middle
#: (a point), its top centre BACK_POCKET_FROM_CB_CM along the waist seam from the centre back and
#: BACK_POCKET_TOP_CM under it (at least BACK_POCKET_UNDER_YOKE_CM under the yoke), parallel to the yoke; its opening
#: hemmed BACK_POCKET_HEM_CM under its top. Tailored: a welt pocket — two lips WELT_CM apart, BACK_POCKET_W_CM - 1 wide.
YOKE_CB_CM = 6.5
YOKE_SIDE_CM = 3.5
BACK_POCKET_W_CM = 14.0
BACK_POCKET_SIDE_CM = 13.5
BACK_POCKET_H_CM = 15.0
BACK_POCKET_FROM_CB_CM = 9.0
BACK_POCKET_TOP_CM = 7.5
BACK_POCKET_UNDER_YOKE_CM = 1.0
BACK_POCKET_HEM_CM = 1.5
WELT_CM = 1.0
#: The waistband's two topstitch rows lie BAND_STITCH_IN_CM inside its edges.
BAND_STITCH_IN_CM = 0.3
#: The thread colour must differ by at least THREAD_MIN_DE (dE76) from the fabric; else (the item names or shows a
#: thread of the fabric's own colour) it is the fabric moved by THREAD_DL in L*.
THREAD_MIN_DE = 12.0
THREAD_DL = 22.0
#: The gate (``trouser_detail_gate``): a configured detail is painted when at least DETAIL_MIN_PX of its pixels changed,
#: by at least DETAIL_MIN_DE on average.
DETAIL_MIN_PX = 20
DETAIL_MIN_DE = 6.0
#: The seam polylines are evened by this many rounds of (1, 2, 1) / 4 (the fitted cut's borders are jagged), chains of
#: one seam within JOIN_CM of each other's ends joined.
LINE_SMOOTH = 3
BAND_SMOOTH = 12
JOIN_CM = 3.0
#: The jeans words of an item's text (``trouser_style``): yoke, patch pockets with rivets, a scooped front pocket.
JEANS_WORDS = ("jeans", "jean", "denim", "denims")


def trouser_style(text: str) -> str:
    """"jeans" when the item text names jeans or denim, else "tailored" (slant front pockets, welt back pockets, no
    yoke, no rivets)."""
    words = set(re.findall(r"[a-z]+", (text or "").lower()))
    return "jeans" if words & set(JEANS_WORDS) else "tailored"


def trouser_wanted(fly: str, waist: str) -> list[str]:
    """The details a trouser's parameters ask for: ``fly`` (zip / buttons) -> the fly, the front pockets, the back
    pockets; a waistband (``trouser_waist`` not none) -> its topstitching, with a fly its button, a belt band its
    loops."""
    out = []
    fly_on = fly not in (None, "", "none")
    band = waist not in (None, "", "none")
    if fly_on:
        out += ["fly", "front_pocket_l", "front_pocket_r", "back_pocket_l", "back_pocket_r"]
    if band:
        out.append("band_stitch")
        if fly_on:
            out.append("band_button")
        if waist == "belt":
            out.append("belt_loops")
    return out


def seam_pairs(islands: dict, one: str, other: str) -> list[tuple[np.ndarray, np.ndarray]]:
    """Every seam chain between the islands ``one`` and ``other`` (``islands.json`` ``seams``, samples in chain order)
    as ``(px on one's side, px on other's side)``, each (n, 2); chains of fewer than 2 samples left out."""
    chains: dict[int, dict] = {}
    for smp in islands.get("seams") or []:
        c = chains.setdefault(int(smp["seam"]), {"a": smp["a"], "b": smp["b"], "pa": [], "pb": []})
        c["pa"].append(smp["uv_a_px"])
        c["pb"].append(smp["uv_b_px"])
    out = []
    for k in sorted(chains):
        c = chains[k]
        if (c["a"], c["b"]) == (one, other):
            pair = (np.asarray(c["pa"], float), np.asarray(c["pb"], float))
        elif (c["a"], c["b"]) == (other, one):
            pair = (np.asarray(c["pb"], float), np.asarray(c["pa"], float))
        else:
            continue
        if len(pair[0]) >= 2:
            out.append(pair)
    return out


def _join(lines: list, join_px: float) -> np.ndarray | None:
    """The polylines ``lines`` (each (n, 2)) joined end to end into one, starting from the longest: the line whose end
    lies nearest an end of the joined one (within ``join_px``) is added there, reversed when needed. None without a
    line; lines too far from it are left out."""
    rest = [np.asarray(x, float) for x in lines if len(x) >= 2]
    if not rest:
        return None
    rest.sort(key=len, reverse=True)
    cur = rest.pop(0)
    while rest:
        best = None
        for i, ln in enumerate(rest):
            for at_end in (True, False):
                end = cur[-1] if at_end else cur[0]
                for rev in (False, True):
                    seg = ln[::-1] if rev else ln
                    d = float(np.linalg.norm((seg[0] if at_end else seg[-1]) - end))
                    if best is None or d < best[0]:
                        best = (d, i, at_end, seg)
        if best[0] > join_px:
            break
        _d, i, at_end, seg = best
        cur = np.vstack([cur, seg]) if at_end else np.vstack([seg, cur])
        rest.pop(i)
    return cur


def _from(p: np.ndarray, q) -> np.ndarray:
    """``p`` ordered to start at its end nearer the point ``q``."""
    return p if np.linalg.norm(p[0] - q) <= np.linalg.norm(p[-1] - q) else p[::-1]


def _top_first(p: np.ndarray) -> np.ndarray:
    """``p`` ordered to start at its higher end (smaller image y: the islands are oriented up)."""
    return p if p[0][1] <= p[-1][1] else p[::-1]


def _normal_to(p: np.ndarray, s: np.ndarray, t: float, towards) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(point, unit tangent, unit normal)`` at arc length ``t`` of the polyline, the normal turned to the side of the
    point ``towards``."""
    c, tg = _at(p, s, t)
    n = np.array([-tg[1], tg[0]])
    if (np.asarray(towards, float) - c) @ n < 0:
        n = -n
    return c, tg, n


def _offset_line(p: np.ndarray, d: float, towards) -> np.ndarray:
    """The polyline ``p`` moved ``d`` px along its normals, to the side of the point ``towards`` (the normal at each
    point from its neighbours, turned consistently with the first)."""
    p = np.asarray(p, float)
    if len(p) < 2:
        return p.copy()
    tg = np.gradient(p, axis=0)
    tg /= np.maximum(np.linalg.norm(tg, axis=1), 1e-9)[:, None]
    n = np.stack([-tg[:, 1], tg[:, 0]], 1)
    mid = p[len(p) // 2]
    if (np.asarray(towards, float) - mid) @ n[len(p) // 2] < 0:
        n = -n
    return p + n * d


def _upto(p: np.ndarray, s: np.ndarray, t: float) -> np.ndarray:
    """The polyline from its start to arc length ``t`` (the end point interpolated)."""
    k = int(np.searchsorted(s, t, side="right"))
    pts = list(p[:k])
    end, _ = _at(p, s, t)
    if not pts or np.linalg.norm(pts[-1] - end) > 1e-9:
        pts.append(end)
    return np.asarray(pts, float)


def _bezier(a, c, b, n: int = 32) -> np.ndarray:
    t = np.linspace(0.0, 1.0, n)[:, None]
    a, c, b = (np.asarray(v, float) for v in (a, c, b))
    return (1 - t) ** 2 * a + 2 * (1 - t) * t * c + t * t * b


def _island(islands: dict, name: str) -> dict | None:
    return next((i for i in islands.get("islands") or [] if i["name"] == name), None)


def _centroid(isl: dict) -> np.ndarray:
    return np.asarray(isl["verts_px"], float).mean(0)


def _loop_path(isl: dict, a, b) -> np.ndarray | None:
    """The shorter way along the island's (longest) boundary loop from the loop point nearest ``a`` to the one nearest
    ``b`` — a panel's top edge between two corners when no waistband seam marks it."""
    loops = [np.asarray(lp, float) for lp in isl.get("loops_px") or [] if len(lp) >= 3]
    if not loops:
        return None
    lp = max(loops, key=len)
    i = int(np.argmin(np.linalg.norm(lp - np.asarray(a, float), axis=1)))
    j = int(np.argmin(np.linalg.norm(lp - np.asarray(b, float), axis=1)))
    n = len(lp)
    fwd = [lp[(i + k) % n] for k in range(((j - i) % n) + 1)]
    bwd = [lp[(i - k) % n] for k in range(((i - j) % n) + 1)]

    def length(path):
        q = np.asarray(path)
        return float(np.linalg.norm(np.diff(q, axis=0), axis=1).sum()) if len(q) > 1 else 0.0
    return np.asarray(fwd if length(fwd) <= length(bwd) else bwd, float)


def _panel_frame(islands: dict, panel: str, centre_mate: str, side_mate: str, join_px: float) -> dict | None:
    """The construction lines of one leg panel (``front_l`` ...), image pixels, every polyline evened
    (``LINE_SMOOTH``): ``centre`` = the seam to ``centre_mate`` (the other front / back panel: centre front / back)
    from its top down; ``side`` = the outseam to ``side_mate`` (of the panel's seams to it the one reaching highest)
    from its top down; ``waist`` = the panel's top edge from the centre end to the side end (its seam to the waistband,
    else its boundary between the two tops). None when the centre or the side seam is missing."""
    isl = _island(islands, panel)
    if isl is None:
        return None
    centre = _join([a for a, _b in seam_pairs(islands, panel, centre_mate)], join_px)
    sides = [a for a, _b in seam_pairs(islands, panel, side_mate)]
    if centre is None or not sides:
        return None
    side = _top_first(min(sides, key=lambda q: float(q[:, 1].min())))
    centre = _top_first(centre)
    band = _join([a for a, _b in seam_pairs(islands, panel, "waistband")], join_px)
    waist = _from(band, centre[0]) if band is not None else _loop_path(isl, centre[0], side[0])
    if waist is None or len(waist) < 2:
        return None
    sm = lambda q: _smooth_points(q, LINE_SMOOTH)  # noqa: E731
    return {"centre": sm(centre), "side": sm(side), "waist": sm(waist), "banded": band is not None,
            "mid": _centroid(isl)}


def trouser_lines(islands: dict, *, fly: str, waist: str, style: str = "jeans",
                  band_cm: float = 4.0) -> dict:
    """The detail geometry of a trouser cut (``TROUSER_*`` constants), in the atlas pixels of ``islands`` — no mask, no
    picture: ``{"lines": {name: {"island", "px", "kind"}}, "points": {name: {"island", "px", "d_cm", "kind"}},
    "loops": [{"island", "a", "b"}], "wanted": [...], "placed": [...], "missing": [...]}`` — ``kind`` "stitch" (a
    dashed thread), "groove" (a sewn edge) or "tack" (a bar tack, a line across); a point "button" / "rivet".
    ``wanted`` = ``trouser_wanted(fly, waist)``; a detail is "placed" when its geometry could be derived from the
    cut's seams (the fly needs the centre-front seam of ``front_l``, the band its seams to the panels, a pocket its
    panel's centre and side seams), else "missing"."""
    ppc = float(islands.get("px_per_cm") or 0.0)
    out: dict = {"lines": {}, "points": {}, "loops": [], "wanted": trouser_wanted(fly, waist), "placed": [],
                 "missing": []}
    if ppc <= 0:
        out["missing"] = list(out["wanted"])
        return out
    jp = JOIN_CM * ppc
    gap = STITCH_GAP_CM * ppc
    jeans = style == "jeans"

    def line(name, island, px, kind="stitch"):
        out["lines"][name] = {"island": island, "px": [[round(float(x), 2), round(float(y), 2)] for x, y in px],
                              "kind": kind}

    def point(name, island, px, d_cm, kind):
        out["points"][name] = {"island": island, "px": [round(float(px[0]), 2), round(float(px[1]), 2)],
                               "d_cm": d_cm, "kind": kind}

    placed = set()
    frames = {}
    for sd, ot in (("l", "r"), ("r", "l")):
        frames["front_" + sd] = _panel_frame(islands, "front_" + sd, "front_" + ot, "back_" + sd, jp)
        frames["back_" + sd] = _panel_frame(islands, "back_" + sd, "back_" + ot, "front_" + sd, jp)
    # the fly: on the left front, along the centre-front seam
    fr = frames.get("front_l")
    if "fly" in out["wanted"] and fr is not None:
        p, s = _polyline(fr["centre"])
        length = min(FLY_LEN_CM * ppc, s[-1] - FLY_CROTCH_CLEAR_CM * ppc)
        if length >= FLY_MIN_CM * ppc:
            w = FLY_W_CM * ppc
            for k, r in enumerate((w, w - gap)):
                pts = []
                for t in np.linspace(0.0, length - w, max(2, int((length - w) / ppc) + 1)):
                    c, _tg, n = _normal_to(p, s, t, fr["mid"])
                    pts.append(c + n * r)
                for phi in np.linspace(0.0, math.pi / 2, 16)[1:]:
                    c, _tg, n = _normal_to(p, s, length - w + r * math.sin(phi), fr["mid"])
                    pts.append(c + n * r * math.cos(phi))
                line(f"fly_{k + 1}", "front_l", pts)
            line("fly_edge", "front_l", _upto(p, s, length), "groove")
            c, tg, n = _normal_to(p, s, length - THREAD_IN_CM * ppc, fr["mid"])
            line("fly_tack", "front_l", [c + n * 0.1 * ppc, c + n * (0.1 * ppc + BAR_TACK_CM * ppc)], "tack")
            if fly == "buttons":
                for j in range(FLY_BUTTONS):
                    t = 2.0 * ppc + j * (length - w - 2.0 * ppc) / max(1, FLY_BUTTONS - 1)
                    c, _tg, n = _normal_to(p, s, t, fr["mid"])
                    point(f"fly_button_{j + 1}", "front_l", c + n * w / 2.0, FLY_BUTTON_D_CM, "button")
            placed.add("fly")
    # the front pockets
    for sd in ("l", "r"):
        fr = frames.get("front_" + sd)
        if f"front_pocket_{sd}" not in out["wanted"] or fr is None:
            continue
        wp, ws = _polyline(fr["waist"])
        sp, ss = _polyline(fr["side"])
        if ws[-1] < FRONT_POCKET_IN_CM * ppc + 2.0 * ppc or ss[-1] < TAILORED_POCKET_DEPTH_CM * ppc:
            continue
        p0, _tg, down = _normal_to(wp, ws, FRONT_POCKET_IN_CM * ppc, fr["mid"])
        p1, _ = _at(sp, ss, (FRONT_POCKET_DEPTH_CM if jeans else TAILORED_POCKET_DEPTH_CM) * ppc)
        isl = "front_" + sd
        if jeans:
            curve = _bezier(p0, p0 + down * float((p1 - p0) @ down), p1)
            line(f"front_pocket_{sd}_edge", isl, curve, "groove")
            # the rows run on the pocket's facing side: toward the panel's middle from the opening
            line(f"front_pocket_{sd}_1", isl, _offset_line(curve, THREAD_IN_CM * ppc, fr["mid"]))
            line(f"front_pocket_{sd}_2", isl, _offset_line(curve, THREAD_IN_CM * ppc + gap, fr["mid"]))
            point(f"front_pocket_{sd}_rivet_1", isl, p0 + down * 0.5 * ppc, RIVET_D_CM, "rivet")
            point(f"front_pocket_{sd}_rivet_2", isl, p1 + (p0 - p1) / max(1e-9, float(np.linalg.norm(p0 - p1)))
                  * 0.5 * ppc, RIVET_D_CM, "rivet")
        else:
            curve = np.array([p0, p1])
            line(f"front_pocket_{sd}_edge", isl, curve, "groove")
            line(f"front_pocket_{sd}_1", isl, _offset_line(curve, THREAD_IN_CM * ppc, fr["mid"]))
        placed.add(f"front_pocket_{sd}")
    # the back: yoke and patch pockets (jeans) or welt pockets (tailored)
    for sd in ("l", "r"):
        fr = frames.get("back_" + sd)
        if f"back_pocket_{sd}" not in out["wanted"] or fr is None:
            continue
        isl = "back_" + sd
        cp, cs = _polyline(fr["centre"])
        sp, ss = _polyline(fr["side"])
        wp, ws = _polyline(fr["waist"])
        if ws[-1] < BACK_POCKET_FROM_CB_CM * ppc + BACK_POCKET_W_CM / 2.0 * ppc or cs[-1] < YOKE_CB_CM * ppc:
            continue
        w0, wt, down = _normal_to(wp, ws, BACK_POCKET_FROM_CB_CM * ppc, fr["mid"])
        across = wt
        top = BACK_POCKET_TOP_CM * ppc
        if jeans:
            ya, _ = _at(cp, cs, YOKE_CB_CM * ppc)
            yb, _ = _at(sp, ss, YOKE_SIDE_CM * ppc)
            yoke = np.array([ya, yb])
            line(f"yoke_{sd}_edge", isl, yoke, "groove")
            line(f"yoke_{sd}_1", isl, _offset_line(yoke, THREAD_IN_CM * ppc, fr["mid"]))
            line(f"yoke_{sd}_2", isl, _offset_line(yoke, THREAD_IN_CM * ppc + gap, fr["mid"]))
            across = (yb - ya) / max(1e-9, float(np.linalg.norm(yb - ya)))
            down = np.array([-across[1], across[0]])
            if (fr["mid"] - w0) @ down < 0:
                down = -down
            # the yoke's depth under w0 along ``down``: where the yoke line crosses the ray
            ab = yb - ya
            den = down[0] * ab[1] - down[1] * ab[0]
            if abs(den) > 1e-9:
                wx = ya - w0
                depth = (wx[0] * ab[1] - wx[1] * ab[0]) / den
                top = max(top, depth + BACK_POCKET_UNDER_YOKE_CM * ppc)
        tc = w0 + down * top
        hw = BACK_POCKET_W_CM / 2.0 * ppc
        if jeans:
            tl, tr = tc - across * hw, tc + across * hw
            bl, br = tl + down * BACK_POCKET_SIDE_CM * ppc, tr + down * BACK_POCKET_SIDE_CM * ppc
            bot = tc + down * BACK_POCKET_H_CM * ppc
            outline = np.array([tl, bl, bot, br, tr])
            line(f"back_pocket_{sd}_edge", isl, np.vstack([outline, tl]), "groove")
            inner = np.array([tc, tc + down * BACK_POCKET_SIDE_CM * ppc])    # a point inside the pocket
            mid_in = inner.mean(0)

            def inset(d):
                return _inset_polygon(outline, d, mid_in)
            line(f"back_pocket_{sd}_1", isl, inset(THREAD_IN_CM * ppc))
            line(f"back_pocket_{sd}_2", isl, inset(THREAD_IN_CM * ppc + gap))
            line(f"back_pocket_{sd}_hem", isl, [tl + down * BACK_POCKET_HEM_CM * ppc + across * 0.3 * ppc,
                                                 tr + down * BACK_POCKET_HEM_CM * ppc - across * 0.3 * ppc])
            for k, corner in enumerate((tl, tr)):
                inward = across if k == 0 else -across
                line(f"back_pocket_{sd}_tack_{k + 1}", isl,
                     [corner + inward * 0.15 * ppc, corner + inward * 0.15 * ppc + down * BAR_TACK_CM * ppc], "tack")
        else:
            hw -= 0.5 * ppc
            for k, d in enumerate((0.0, WELT_CM * ppc)):
                a, b = tc - across * hw + down * d, tc + across * hw + down * d
                line(f"back_pocket_{sd}_welt_{k + 1}", isl, [a, b], "groove")
            line(f"back_pocket_{sd}_1", isl, [tc - across * hw + down * WELT_CM / 2.0 * ppc,
                                              tc + across * hw + down * WELT_CM / 2.0 * ppc])
        placed.add(f"back_pocket_{sd}")
    # the waistband: its two rows, the button at the centre front, the belt loops
    band = _island(islands, "waistband")
    if band is not None and any(d in out["wanted"] for d in ("band_stitch", "band_button", "belt_loops")):
        runs = []
        for panel in ("back_r", "front_r", "front_l", "back_l"):
            for _a, b in seam_pairs(islands, "waistband", panel):
                runs += [(q, panel) for q in _a]
        if len(runs) >= 4:
            P = np.array([q for q, _ in runs])
            lab = [n for _, n in runs]
            V = np.asarray(band["verts_px"], float)
            ctr = V.mean(0)
            ev = np.linalg.eigh(np.cov((V - ctr).T))[1][:, -1]
            if ev[0] < 0:
                ev = -ev
            order = np.argsort((P - ctr) @ ev, kind="stable")
            P, lab = P[order], [lab[i] for i in order]
            # the junctions are read on the samples as cut (``u_between``: two runs meeting share a sample); the
            # evened bottom edge drops one of each pair closer than a quarter cm
            raw_u, raw_lab = (P - ctr) @ ev, list(lab)
            keep = [0] + [i for i in range(1, len(P)) if float(np.linalg.norm(P[i] - P[i - 1])) >= 0.25 * ppc]
            P = P[keep]
            up = np.array([-ev[1], ev[0]])
            if (ctr - P.mean(0)) @ up < 0:
                up = -up
            bottom = _smooth_points(P, BAND_SMOOTH)
            u = (bottom - ctr) @ ev
            # the band's height as cut: per seam sample the farthest band vertex up within 1 cm along the band, the
            # median of those (the fitted cut's band is jagged and a little higher than ``band_cm``)
            vu = (V - ctr) @ ev
            reach = [float(((V[np.abs(vu - uu) < ppc] - q) @ up).max()) for q, uu in zip(bottom, u)
                     if (np.abs(vu - uu) < ppc).any()]
            h = float(np.median(reach)) if reach else float(band_cm) * ppc
            out["band_h_cm"] = round(h / ppc, 3)
            if "band_stitch" in out["wanted"]:
                line("band_stitch_1", "waistband", bottom + up * BAND_STITCH_IN_CM * ppc)
                line("band_stitch_2", "waistband", bottom + up * (h - BAND_STITCH_IN_CM * ppc))
                placed.add("band_stitch")

            def u_between(x, y):
                """The band coordinate of the junction of the runs of panels x and y (the mean of the nearest pair)."""
                ix = [i for i, n in enumerate(raw_lab) if n == x]
                iy = [i for i, n in enumerate(raw_lab) if n == y]
                if not ix or not iy:
                    return None
                best = min(((abs(raw_u[i] - raw_u[j]), i, j) for i in (ix[0], ix[-1]) for j in (iy[0], iy[-1])))
                return float((raw_u[best[1]] + raw_u[best[2]]) / 2.0)

            def at_u(uu, lift):
                """The point of the band's bottom edge at band coordinate ``uu``, ``lift`` px up (past the first /
                last seam sample along the band's axis)."""
                if uu <= u[0]:
                    return bottom[0] + ev * (uu - u[0]) + up * lift
                if uu >= u[-1]:
                    return bottom[-1] + ev * (uu - u[-1]) + up * lift
                k = int(np.clip(np.searchsorted(u, uu), 1, len(u) - 1))
                f = float(np.clip((uu - u[k - 1]) / max(1e-9, u[k] - u[k - 1]), 0.0, 1.0))
                return bottom[k - 1] * (1 - f) + bottom[k] * f + up * lift

            cf = u_between("front_l", "front_r")
            if "band_button" in out["wanted"] and cf is not None:
                point("band_button", "waistband", at_u(cf, h / 2.0), BAND_BUTTON_D_CM, "button")
                placed.add("band_button")
            if "belt_loops" in out["wanted"] and cf is not None:
                side_l, side_r = u_between("front_l", "back_l"), u_between("front_r", "back_r")
                if side_l is not None and side_r is not None:
                    to_l = 1.0 if side_l > cf else -1.0
                    # the centre back is the band's opening: its two ends (the island's extent along the band)
                    e0, e1 = float(vu.min()), float(vu.max())
                    us = [e0, e1, cf + to_l * FRONT_LOOP_CM * ppc, cf - to_l * FRONT_LOOP_CM * ppc,
                          side_l + to_l * SIDE_LOOP_BACK_CM * ppc, side_r - to_l * SIDE_LOOP_BACK_CM * ppc,
                          e0 + BACK_LOOP_CM * ppc, e1 - BACK_LOOP_CM * ppc]
                    for uu in us:
                        out["loops"].append({"island": "waistband",
                                             "a": [round(float(v), 2) for v in at_u(uu, 0.0)],
                                             "b": [round(float(v), 2) for v in at_u(uu, h)]})
                    placed.add("belt_loops")
    out["placed"] = [d for d in out["wanted"] if d in placed]
    out["missing"] = [d for d in out["wanted"] if d not in placed]
    return out


def _inset_polygon(poly: np.ndarray, d: float, inside) -> np.ndarray:
    """The open polyline ``poly`` with every vertex moved ``d`` px toward ``inside`` along the bisector of its two edge
    normals (an end vertex along its one edge's normal) — the rows inside a patch pocket's outline."""
    p = np.asarray(poly, float)
    out = []
    for i in range(len(p)):
        ns = []
        for a, b in ((p[i - 1], p[i]) if i > 0 else (None, None), (p[i], p[i + 1]) if i + 1 < len(p) else (None, None)):
            if a is None:
                continue
            tg = (b - a) / max(1e-9, float(np.linalg.norm(b - a)))
            n = np.array([-tg[1], tg[0]])
            if (np.asarray(inside, float) - (a + b) / 2.0) @ n < 0:
                n = -n
            ns.append(n)
        if len(ns) == 2:
            bis = ns[0] + ns[1]
            ln = float(np.linalg.norm(bis))
            cosh = max(0.2, ln / 2.0)
            out.append(p[i] + bis / max(ln, 1e-9) * d / cosh)
        else:
            out.append(p[i] + ns[0] * d)
    return np.asarray(out)


def _dashed(out: np.ndarray, sel: np.ndarray, p: np.ndarray, half: float, dash: float, gap: float, rgb) -> int:
    """Paint the polyline ``p`` as dashes ``dash`` px on, ``gap`` px off (within ``half`` of it, ``sel`` only).
    Returns the dashes painted."""
    p, s = _polyline(p)
    if s[-1] <= 0:
        return 0
    n = 0
    t = 0.0
    while t < s[-1]:
        t1 = min(s[-1], t + dash)
        a, _ = _at(p, s, t)
        k0 = int(np.searchsorted(s, t, side="right"))
        k1 = int(np.searchsorted(s, t1, side="left"))
        pts = [a] + [p[k] for k in range(k0, k1)] + [_at(p, s, t1)[0]]
        for x, y in zip(pts, pts[1:]):
            _band(out, sel, x, y, half, rgb)
        n += 1
        t = t1 + gap
    return n


def thread_colour(fabric_lab, thread_rgb=None) -> tuple[np.ndarray, str]:
    """The topstitch thread's sRGB and its source: the item's own ``thread_rgb`` (its text or its picture,
    ``garment_cut_texture.thread_rgb``) when it differs by ``THREAD_MIN_DE`` from the fabric, else the fabric moved by
    ``THREAD_DL`` in L* (``_shade``: darker on a light fabric) — "contrast"."""
    if thread_rgb is not None:
        rgb = np.clip(np.rint(np.asarray(thread_rgb, np.float64)[:3]), 0, 255).astype(np.uint8)
        if float(np.linalg.norm(srgb_to_lab(rgb.astype(np.float64)) - np.asarray(fabric_lab, float))) >= THREAD_MIN_DE:
            return rgb, "item"
    return _shade(fabric_lab, THREAD_DL), "contrast"


def draw_trouser_details(atlas: np.ndarray, masks: dict, lines: dict, *, px_per_cm: float, thread_rgb=None,
                         button_rgb=None) -> tuple[np.ndarray, dict]:
    """Paint a trouser's ``trouser_lines`` into ``atlas`` — each element only inside its own island (``masks`` =
    {island name: bool mask}), nothing outside an island changes. The fabric is the median L*a*b* of each island.

    - a groove (``TROUSER_GROOVE_CM`` wide, ``SEAM_DL`` darker, ``_seam_shade``) on every "groove" line;
    - a dashed thread (``THREAD_*``, ``thread_colour``) on every "stitch" line, a solid bar on every "tack";
    - a belt loop per ``loops`` entry: a ``LOOP_W_CM`` strip over the band, ``LOOP_DL`` off the band, grooved sides,
      a bar tack at each end;
    - a button / rivet per point: a metal disc (``button_rgb``, else the zip's metal L*) with a darker rim and a
      lighter centre.

    Returns the new atlas and ``{"thread", "thread_source", "painted": {detail: pixels}, "de": {detail: mean dE76 of
    its changed pixels}}`` — a detail is the name's stem (``fly_1`` -> fly, ``back_pocket_l_edge`` -> back_pocket_l,
    the loops belt_loops, the band's rows band_stitch)."""
    src = np.asarray(atlas)
    out = np.array(atlas, copy=True)
    info: dict = {"painted": {}, "de": {}}
    if px_per_cm <= 0 or not lines:
        return out, info
    lab_of = {}
    for name, m in masks.items():
        m = np.asarray(m, bool)
        lab_of[name] = np.median(srgb_to_lab(src[m][:: max(1, int(m.sum() // 20000))].astype(np.float64)), axis=0) \
            if m.any() else np.array([50.0, 0.0, 0.0])
    main = next((lab_of[n] for n in ("front_l", "front_r", "back_l", "back_r") if n in lab_of), np.array([50.0, 0, 0]))
    thread, source = thread_colour(main, thread_rgb)
    info["thread"], info["thread_source"] = [int(v) for v in thread], source
    ppc = float(px_per_cm)
    half = max(0.5, THREAD_W_CM * ppc / 2.0)
    dash, gap = THREAD_DASH_CM * ppc, THREAD_GAP_CM * ppc
    touched: dict[str, np.ndarray] = {}

    def stem(name: str) -> str:
        for d in ("fly", "band_stitch", "band_button", "front_pocket_l", "front_pocket_r", "back_pocket_l",
                  "back_pocket_r"):
            if name == d or name.startswith(d + "_"):
                return d
        if name.startswith("yoke_"):
            return "back_pocket_" + name.split("_")[1]
        return name

    def mark(detail: str, before: np.ndarray, sel: np.ndarray) -> None:
        changed = (np.abs(out.astype(np.int16) - before.astype(np.int16)).max(-1) > 0) & sel
        touched[detail] = changed if detail not in touched else (touched[detail] | changed)

    groove_half = max(0.6, TROUSER_GROOVE_CM * ppc / 2.0)
    # grooves first, threads over them
    for kind in ("groove", "stitch", "tack"):
        for name, ln in sorted(lines.get("lines", {}).items()):
            if ln["kind"] != kind or ln["island"] not in masks or len(ln["px"]) < 2:
                continue
            sel = np.asarray(masks[ln["island"]], bool)
            fab = lab_of[ln["island"]]
            before = out.copy()
            pts = np.asarray(ln["px"], float)
            if kind == "groove":
                sign = 1.0 if fab[0] >= SEAM_DARK_MIN_L else -1.0
                col = _seam_shade(fab, sign * SEAM_DL)
                for a, b in zip(pts, pts[1:]):
                    _band(out, sel, a, b, groove_half, col)
            elif kind == "stitch":
                _dashed(out, sel, pts, half, dash, gap, thread)
            else:
                for a, b in zip(pts, pts[1:]):
                    _band(out, sel, a, b, max(half, BAR_TACK_W_CM * ppc / 2.0), thread)
            mark(stem(name), before, sel)
    for lp in lines.get("loops") or []:
        if lp["island"] not in masks:
            continue
        sel = np.asarray(masks[lp["island"]], bool)
        fab = lab_of[lp["island"]]
        before = out.copy()
        a, b = np.asarray(lp["a"], float), np.asarray(lp["b"], float)
        ax = (b - a) / max(1e-9, float(np.linalg.norm(b - a)))
        nrm = np.array([-ax[1], ax[0]])
        w = LOOP_W_CM * ppc
        lab = np.asarray(fab, float).copy()
        lab[0] = float(np.clip(lab[0] + (LOOP_DL if lab[0] < 50.0 else -LOOP_DL), 0.0, 100.0))
        body = np.clip(np.rint(lab_to_srgb(lab)), 0, 255).astype(np.uint8)
        _band(out, sel, a, b, w / 2.0, body)
        edge = _seam_shade(fab, SEAM_DL if fab[0] >= SEAM_DARK_MIN_L else -SEAM_DL)
        for sg in (1, -1):
            _band(out, sel, a + nrm * sg * w / 2.0, b + nrm * sg * w / 2.0, groove_half, edge)
        for end, inward in ((a, ax), (b, -ax)):
            c = end + inward * 0.35 * ppc
            _band(out, sel, c - nrm * w * 0.4, c + nrm * w * 0.4, max(half, BAR_TACK_W_CM * ppc / 2.0), thread)
        mark("belt_loops", before, sel)
    metal = np.clip(np.rint(lab_to_srgb(np.array([ZIP_L, 0.0, 0.0]))), 0, 255).astype(np.uint8)
    disc = np.clip(np.rint(np.asarray(button_rgb, np.float64)[:3]), 0, 255).astype(np.uint8) \
        if button_rgb is not None else metal
    dlab = srgb_to_lab(disc.astype(np.float64))
    rim = _seam_shade(dlab, 18.0)
    hi = _seam_shade(dlab, -12.0)
    for name, pt in sorted((lines.get("points") or {}).items()):
        if pt["island"] not in masks:
            continue
        sel = np.asarray(masks[pt["island"]], bool)
        before = out.copy()
        r = float(pt["d_cm"]) * ppc / 2.0
        c = np.asarray(pt["px"], float)
        _disc(out, sel, c, r, rim)
        _disc(out, sel, c, r * 0.8, disc)
        _disc(out, sel, c - np.array([0.2, 0.2]) * r, r * 0.3, hi)
        mark(stem(name) if not name.startswith("front_pocket") else stem(name), before, sel)
    for d, m in touched.items():
        n = int(m.sum())
        info["painted"][d] = n
        if n:
            diff = srgb_to_lab(out[m].astype(np.float64)) - srgb_to_lab(src[m].astype(np.float64))
            info["de"][d] = round(float(np.linalg.norm(diff, axis=1).mean()), 2)
    return out, info


def trouser_detail_gate(info: dict, wanted: list) -> list[str]:
    """The configured details (``wanted``) that the painting did not put on the atlas: under ``DETAIL_MIN_PX`` changed
    pixels or under ``DETAIL_MIN_DE`` mean change."""
    painted, de = info.get("painted") or {}, info.get("de") or {}
    return [d for d in wanted if painted.get(d, 0) < DETAIL_MIN_PX or de.get(d, 0.0) < DETAIL_MIN_DE]


#: ``picture_thread``: the item picture at ``long`` px on its long side; the garment = not near-white, eroded 3 px; a
#: candidate pixel lies more than ``de`` (dE76) from the picture's base fabric (``fabric_colour``), has a chroma over
#: ``chroma`` and a hue at least ``hue_deg`` from the fabric's; the thread is the THIN part of the candidates (what an
#: opening by one pixel removes: a stitch line, never a button, a rivet or a label patch) when it holds ``min_px``
#: pixels — their median colour. Measured on Kai's jeans picture (380 x 1024, at 768): 76 candidates, 68 thin, median
#: (139, 112, 92) — the tan topstitching on the blue denim (fabric L* 39.8, b* -22.1).
THREAD_FIND = {"long": 768, "de": 20.0, "chroma": 12.0, "hue_deg": 60.0, "min_px": 30}


def picture_thread(rgb) -> dict | None:
    """The topstitch thread of an item picture on white (``THREAD_FIND``): ``{"rgb", "pixels"}`` or None."""
    from scipy import ndimage
    g = THREAD_FIND
    im = Image.fromarray(np.asarray(rgb)[..., :3].astype(np.uint8))
    s = g["long"] / float(max(im.size))
    im = im.resize((max(1, round(im.size[0] * s)), max(1, round(im.size[1] * s))), Image.LANCZOS)
    a = np.asarray(im).astype(np.float64)
    garment = ndimage.binary_erosion((255.0 - a).max(-1) > 30.0, iterations=3)
    if garment.sum() < 64:
        return None
    fab = fabric_colour(np.asarray(im), garment)
    if not fab:
        return None
    lab = srgb_to_lab(a)
    fl = np.asarray(fab["lab"], np.float64)
    de = np.linalg.norm(lab - fl, axis=-1)
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    dh = np.abs(np.angle(np.exp(1j * (np.arctan2(lab[..., 2], lab[..., 1]) - math.atan2(fl[2], fl[1])))))
    cand = garment & (de > g["de"]) & (chroma > g["chroma"]) & (dh >= math.radians(g["hue_deg"]))
    thin = cand & ~ndimage.binary_opening(cand, iterations=1)
    if int(thin.sum()) < g["min_px"]:
        return None
    return {"rgb": [int(round(v)) for v in np.median(a[thin], axis=0)], "pixels": int(thin.sum())}
