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
- ``seam_continuity`` — the colour jump across the payload's seam pairs (a metric, not a gate).

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
#: Foreground closer than this to an island is a smeared edge, not spill.
SPILL_CM = 1.0
#: ``colour_match``: the largest mean shift (dE76).
CLAMP_DE = 25.0
#: Enters the cut atlas key (``csig``): bump when anything here changes the atlas.
POST_VERSION = 1

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


# ---------------------------------------------------------------------------------------------------------------- masks

def foreground(img: np.ndarray) -> np.ndarray:
    """Bool (h, w): the largest channel distance from white exceeds ``WHITE_TOL``."""
    rgb = np.asarray(img)[..., :3].astype(np.int16)
    return (255 - rgb).max(-1) > WHITE_TOL


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
    fg = foreground(arr)
    if not fg.any() or not mask.any():
        return arr.copy(), {"registered": False, "iou": 0.0, "size_in": size_in}
    mp, grid_iou, box_iou = register_raster(mask, fg)
    sx, ox, sy, oy = mp
    xs = np.arange(w) + 0.5
    ys = np.arange(h) + 0.5
    U = np.broadcast_to(sx * xs[None, :] + ox, (h, w))
    V = np.broadcast_to(sy * ys[:, None] + oy, (h, w))
    got = np.clip(np.rint(_sample_bilinear(arr.astype(np.float64), U, V)), 0, 255).astype(np.uint8)
    f2 = foreground(got)
    union = (f2 | mask).sum()
    iou = float((f2 & mask).sum() / union) if union else 0.0
    return got, {"registered": True, "iou": round(iou, 4), "size_in": size_in,
                 "map": [round(float(x), 6) for x in mp], "grid_iou": grid_iou, "box_iou": box_iou}


# ------------------------------------------------------------------------------------------------------------------ gate

def gate(img: np.ndarray, mask: np.ndarray, labels: np.ndarray, px_per_cm: float) -> tuple[bool, dict, str]:
    """``(ok, metrics, reason)`` of a registered answer against the island mask: ``coverage`` (share of the mask that
    is foreground), ``island_coverage`` (the worst island's share; ``islands`` = per label id), ``iou``, ``spill``
    (foreground beyond ``SPILL_CM`` outside the mask, as a share of the mask area). ``reason`` = the first failing
    gate in that order as ``"<name> <value> < <limit>"`` (``">"`` for spill), "" when it passes; every failure is in
    ``metrics["failures"]``."""
    mask = np.asarray(mask, bool)
    labels = np.asarray(labels)
    fg = foreground(img)
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

def cut_and_bleed(img, mask, bleed_px: int, erode_px: int = 3) -> np.ndarray:
    """The atlas cut to the islands with bleed padding: the mask eroded by ``erode_px`` (the model's outline, drawn
    inside the islands), then regrown ``erode_px + bleed_px`` times by one 8-neighbour ring whose pixels take the mean
    of their already filled neighbours. A part of an island thinner than the erosion keeps its own pixels. Returns
    (h, w, 3) uint8, white outside the grown area."""
    rgb = np.asarray(img)[..., :3].astype(np.float64)
    mask = np.asarray(mask, bool)
    core = erode(mask, erode_px)
    core |= mask & ~dilate(core, erode_px)
    filled = core.copy()
    col = np.where(filled[..., None], rgb, 0.0)
    h, w = mask.shape
    offs = [(di, dj) for di in (-1, 0, 1) for dj in (-1, 0, 1) if di or dj]
    for _ in range(int(erode_px) + int(bleed_px)):
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


# --------------------------------------------------------------------------------------------------------- colour match

def fabric_pixels(item_rgba: np.ndarray, *, matte=garment_matte.birefnet_matte) -> np.ndarray:
    """The item's fabric colours (n, 3) float: alpha > 0 after ``garment_matte.cut`` (``matte`` passed through; a
    smoke passes ``None`` or a stub so no BiRefNet session loads), the darkest and brightest ``FABRIC_TRIM`` of
    luminance dropped."""
    px = np.asarray(item_rgba, np.uint8)
    if px.ndim == 3 and px.shape[2] == 3:
        px = np.concatenate([px, np.full(px.shape[:2] + (1,), 255, np.uint8)], -1)
    cut, _info = garment_matte.cut(px, matte=matte)
    rgb = cut[..., :3][cut[..., 3] > 0].astype(np.float64)
    if not len(rgb):
        return rgb.reshape(0, 3)
    L = srgb_to_lab(rgb)[:, 0]
    lo, hi = np.quantile(L, FABRIC_TRIM), np.quantile(L, 1 - FABRIC_TRIM)
    return rgb[(L >= lo) & (L <= hi)]


def colour_match(img, mask, item_rgba: np.ndarray, *, matte=garment_matte.birefnet_matte) -> tuple[np.ndarray, dict]:
    """The islands' colours moved onto the item fabric's: per Lab channel ``(x - mu_atlas) * (sigma_item /
    sigma_atlas) + mu_item`` (``sigma_atlas`` floored at ``SIGMA_FLOOR``), the mean shift clamped to ``CLAMP_DE``
    (dE76). Only mask pixels change. Returns the (h, w, 3) uint8 image and ``{"de_before", "de_after", "clamped"}``
    (``de_*`` = dE76 of the island mean against the fabric mean); nothing to match (no mask, no fabric) -> the image
    unchanged and ``{"skipped": reason}``."""
    rgb = np.asarray(img)[..., :3].astype(np.uint8)
    mask = np.asarray(mask, bool)
    out = rgb.copy()
    if not mask.any():
        return out, {"skipped": "empty mask"}
    fab = fabric_pixels(item_rgba, matte=matte)
    if not len(fab):
        return out, {"skipped": "no fabric pixels"}
    item_lab = srgb_to_lab(fab)
    mu_i, sd_i = item_lab.mean(0), item_lab.std(0)
    lab = srgb_to_lab(rgb[mask].astype(np.float64))
    mu_a, sd_a = lab.mean(0), np.maximum(lab.std(0), SIGMA_FLOOR)
    shift = mu_i - mu_a
    de_before = float(np.linalg.norm(shift))
    clamped = de_before > CLAMP_DE
    if clamped:
        shift = shift * (CLAMP_DE / de_before)
    new = (lab - mu_a) * (sd_i / sd_a) + mu_a + shift
    out[mask] = np.clip(np.rint(lab_to_srgb(new)), 0, 255).astype(np.uint8)
    after = srgb_to_lab(out[mask].astype(np.float64)).mean(0)
    return out, {"de_before": round(de_before, 3), "de_after": round(float(np.linalg.norm(after - mu_i)), 3),
                 "clamped": bool(clamped)}


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
