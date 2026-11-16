"""Hand-pose gate of the base-body FRONT render (``base_body.generate_base_images``).

The base front is an A-pose render that should show the palms facing the
thighs; depending on the seed the palms face the camera instead. Prompt
wording does not decide it, so the front is measured and re-rendered.

What is measured, on the stored (matted, RGBA) front: per side, the hand is
the arm end at the outermost foreground column between ``TIP_BAND`` of the
body height. From that tip the arm end is grown inside the mask (geodesic
distance, up to ``ARM_REACH``·H) and its axis is the line from the tip to the
mean of its forearm part. The width profile along that axis (pixel count per
``BIN``·H slice / slice length) gives the wrist — the narrowest slice in
``WRIST_ZONE`` — and the hand — the widest slice between the tip and the
wrist. A palm facing the camera is seen flat and wide; a palm facing the
thigh is seen edge-on and narrow.

The score is the hand width as a fraction of the body height H (top of the
head to the soles), the worse (wider) hand of the two; ``ok`` when it is at
most ``HAND_LIMIT``. Calibrated 2026-11-09 on 11 Qwen fronts (6 palms
forward, 5 palms toward the thighs, BiRefNet-DIS matte): forward 0.060 ..
0.073, toward the thighs 0.033 .. 0.040 — the limit sits in the middle of
the gap. The hand/wrist ratio is recorded too; it separates less (forward
>= 1.68, toward the thighs <= 1.55) because the forearm turns with the hand.

The mask is resampled so the body is ``WORK_HEIGHT`` px tall first: the
numbers are fractions of H, the work size only bounds the cost.

FRAMING (Ruling A100): a front whose figure runs out of the image — figure
pixels on its top or bottom row (``EDGE_CUT_PX`` or more: the head or the
feet cut off) — never passes, whatever its hands, and ranks behind every
attempt in frame (score + ``EDGE_CUT_PENALTY``): Ylva's re-render 2026-11-15
kept the attempt without feet because it had the better hands. Measured on
the stored mesh-input views of the test world: the views in frame keep a
margin of 5 .. 135 rows; the cut ones carry 41 .. 406 figure pixels on the
edge row.

numpy/scipy/PIL only. An image that cannot be measured (no alpha, no
figure, no arm end) passes with ``score None`` and a ``reason``: a re-render
would not make it measurable.
"""
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

#: Worst-hand width / body height above which the palms face the camera.
HAND_LIMIT = 0.050
#: The body is resampled to this height (px) before measuring.
WORK_HEIGHT = 600
#: Rows (fractions of H below the head top) in which the hand tip is looked for.
TIP_BAND = (0.30, 0.70)
#: Geodesic reach from the tip (fraction of H): hand plus most of the forearm.
ARM_REACH = 0.24
#: Geodesic distance (fraction of H) beyond which the arm end counts as forearm (axis).
FOREARM_FROM = 0.12
#: Slice length along the arm axis (fraction of H).
BIN = 0.01
#: Axis range (fraction of H from the tip) in which the wrist is the narrowest slice.
WRIST_ZONE = (0.04, 0.16)
#: A mask covering more than this share of the frame is no cut-out.
MAX_FILL = 0.6


#: Figure pixels on the top or bottom image row from which the figure counts as cut off (Ruling A100).
EDGE_CUT_PX = 8
#: Added to the score of a cut-off attempt so ``best_attempt`` keeps one in frame.
EDGE_CUT_PENALTY = 1.0


def edge_cut(alpha: np.ndarray) -> Optional[str]:
    """"top" / "bottom" when the figure (alpha > 127) runs out of the image there, else None."""
    alpha = np.asarray(alpha)
    if alpha.ndim != 2 or alpha.shape[0] < 2:
        return None
    if int((alpha[-1] > 127).sum()) >= EDGE_CUT_PX:
        return "bottom"
    if int((alpha[0] > 127).sum()) >= EDGE_CUT_PX:
        return "top"
    return None


def _unmeasurable(reason: str) -> Dict[str, Any]:
    return {"ok": True, "score": None, "limit": HAND_LIMIT, "left": None, "right": None,
            "reason": reason}


def figure_mask(alpha: np.ndarray) -> Optional[np.ndarray]:
    """The figure as a bool mask at ``WORK_HEIGHT`` body height: alpha > 127,
    the largest connected part, holes filled. None without a figure."""
    from PIL import Image
    from scipy import ndimage as ndi
    mask = np.asarray(alpha) > 127
    rows = np.nonzero(mask.any(axis=1))[0]
    if rows.size == 0 or rows[-1] - rows[0] < 8:
        return None
    scale = WORK_HEIGHT / float(rows[-1] - rows[0])
    h, w = mask.shape
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    img = Image.fromarray(mask.astype(np.uint8) * 255).resize(size, Image.BOX)
    mask = np.asarray(img) > 127
    labels, count = ndi.label(mask)
    if count == 0:
        return None
    if count > 1:
        sizes = ndi.sum(mask, labels, range(1, count + 1))
        mask = labels == 1 + int(np.argmax(sizes))
    return ndi.binary_fill_holes(mask)


def width_profile(mask: np.ndarray, side: int) -> Optional[np.ndarray]:
    """Widths (fractions of H) of the ``BIN`` slices along the arm end of one
    side (``-1`` image left, ``+1`` image right), from the tip inward, over
    ``ARM_REACH``. None when no arm end is found."""
    from scipy import ndimage as ndi
    rows = np.nonzero(mask.any(axis=1))[0]
    top, height = int(rows[0]), float(rows[-1] - rows[0])
    y0 = top + int(TIP_BAND[0] * height)
    y1 = top + int(TIP_BAND[1] * height)
    band = mask[y0:y1]
    cols = np.nonzero(band.any(axis=0))[0]
    if cols.size == 0:
        return None
    tx = int(cols[0] if side < 0 else cols[-1])
    ty = y0 + int(round(np.nonzero(band[:, tx])[0].mean()))
    reach = int(round(ARM_REACH * height))
    r0, c0 = max(0, ty - reach), max(0, tx - reach)
    window = mask[r0:ty + reach + 1, c0:tx + reach + 1]
    grown = np.zeros_like(window)
    grown[ty - r0, tx - c0] = True
    dist = np.full(window.shape, -1, dtype=np.int32)
    dist[ty - r0, tx - c0] = 0
    eight = ndi.generate_binary_structure(2, 2)
    for step in range(1, reach + 1):
        more = ndi.binary_dilation(grown, eight) & window
        new = more & ~grown
        if not new.any():
            break
        dist[new] = step
        grown = more
    ys, xs = np.nonzero(grown)
    pts = np.stack([xs + c0, ys + r0], axis=1).astype(float)
    tip = np.array([tx, ty], dtype=float)
    forearm = pts[dist[ys, xs] > FOREARM_FROM * height]
    if len(forearm) < 4:
        return None
    axis = forearm.mean(axis=0) - tip
    norm = float(np.linalg.norm(axis))
    if norm == 0.0:
        return None
    along = (pts - tip) @ (axis / norm) / height
    slices = int(round(ARM_REACH / BIN))
    counts = np.histogram(along, bins=slices, range=(0.0, slices * BIN))[0]
    return counts / (BIN * height) / height


def measure_side(profile: np.ndarray) -> Optional[Dict[str, float]]:
    """``{hand, wrist, ratio}`` of one width profile (fractions of H)."""
    starts = np.arange(len(profile)) * BIN
    zone = np.nonzero((starts >= WRIST_ZONE[0] - 1e-9) & (starts <= WRIST_ZONE[1] + 1e-9))[0]
    if zone.size == 0:
        return None
    wrist_at = int(zone[np.argmin(profile[zone])])
    wrist = float(profile[wrist_at])
    hand = float(profile[:wrist_at].max()) if wrist_at > 0 else 0.0
    if wrist <= 0.0 or hand <= 0.0:
        return None
    return {"hand": round(hand, 4), "wrist": round(wrist, 4), "ratio": round(hand / wrist, 3),
            "wrist_at": round(float(starts[wrist_at]), 3)}


def hand_pose_gate_mask(alpha: np.ndarray) -> Dict[str, Any]:
    """The gate on an alpha channel (``(H, W)``, 0..255): the hands, then the framing (module docstring);
    ``left``/``right`` are the image sides, ``cut`` "top" / "bottom" for a figure out of the image."""
    result = _hand_gate(alpha)
    cut = edge_cut(np.asarray(alpha)) if np.asarray(alpha).ndim == 2 else None
    if cut and float((np.asarray(alpha) > 127).mean()) <= MAX_FILL:
        score = result.get("score")
        result = {**result, "ok": False, "cut": cut,
                  "score": round((score or 0.0) + EDGE_CUT_PENALTY, 4)}
    return result


def _hand_gate(alpha: np.ndarray) -> Dict[str, Any]:
    alpha = np.asarray(alpha)
    if alpha.ndim != 2 or alpha.size == 0:
        return _unmeasurable("no alpha channel")
    if float((alpha > 127).mean()) > MAX_FILL:
        return _unmeasurable("no cut-out (opaque image)")
    mask = figure_mask(alpha)
    if mask is None:
        return _unmeasurable("no figure")
    sides: Dict[str, Optional[Dict[str, float]]] = {}
    for name, side in (("left", -1), ("right", 1)):
        profile = width_profile(mask, side)
        sides[name] = measure_side(profile) if profile is not None else None
    hands = [s["hand"] for s in sides.values() if s]
    if not hands:
        return _unmeasurable("no arm end found")
    score = max(hands)
    return {"ok": score <= HAND_LIMIT, "score": round(score, 4), "limit": HAND_LIMIT, **sides}


def hand_pose_gate(path: Path) -> Dict[str, Any]:
    """The gate on a stored front image: ``{ok, score, limit, left, right}``
    (+ ``reason`` when it could not measure; ``ok`` is then True)."""
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(path) as im:
            if im.mode not in ("RGBA", "LA", "PA") and "transparency" not in im.info:
                return _unmeasurable("no alpha channel")
            alpha = np.asarray(im.convert("RGBA"))[..., 3]
    except (OSError, UnidentifiedImageError) as e:
        return _unmeasurable(f"unreadable image: {e}")
    try:
        return hand_pose_gate_mask(alpha)
    except Exception as e:  # noqa: BLE001 — a measuring bug never costs the render
        return _unmeasurable(f"gate error: {type(e).__name__}: {e}")


def best_attempt(results: "list[Dict[str, Any]]") -> Tuple[int, bool]:
    """``(index, passed)``: the first passing gate result, else the one with
    the lowest score."""
    for i, result in enumerate(results):
        if result.get("ok"):
            return i, True
    scores = [(r.get("score") if r.get("score") is not None else float("inf"), i)
              for i, r in enumerate(results)]
    return min(scores)[1], False


# --- Noise gate of the dressed two-step views (``base_body._composite_attempt``) ----
#
# Measured on the back FIT (an edit of the cut-out base back with the cut-out
# back draft as second reference, replaced by the CPU composite of
# ``view_composite`` in Task 11g), which sometimes came back grainy: skin and
# cloth carry a fine noise the base view does not have (seed-dependent, on
# turbo and non-turbo models alike). The composite carries the draft's
# pixels inside the garment, so a grainy draft still shows here. The
# background says nothing — the view is matted — so the noise is measured ON
# THE FIGURE.
# Both images are resampled to ``NOISE_WORK_HEIGHT`` px height first, RGB and
# alpha apart (an RGBA resample would premultiply the colours); the figure is
# alpha >= ``NOISE_ALPHA``, shrunk by ``NOISE_ERODE`` px (no matte edge); the
# per-pixel noise is the absolute difference between the grey image and its
# 3x3 box mean (float, no rounding).
#
# Version 2 (2026-11-12) judges the figure's NOISE FLOOR: the
# ``NOISE_QUANTILE`` percentile of the means of the ``NOISE_BLOCK`` x
# ``NOISE_BLOCK`` blocks lying wholly inside the figure — the noise of its
# smoothest tenth, wherever that is. Blocks whose mean grey lies outside
# ``NOISE_BLOCK_GREY`` do not count: near black and near white the noise is
# squashed (Kira's black blazer alone held the floor of her fit, 0.89, until
# it was left out: 1.29 on her skin and hair). Grain lifts every block; an
# outfit's own texture (knit, print, lace) and hair lift only the blocks they
# cover. Of the counted blocks a clean fit keeps 72-74 % (calibration fits)
# and 14 % (Kira ecba33c49418: long hair, lace stockings) under the limit
# times the base's floor, a grainy one 4 % — the floor needs 10 %, so an
# outfit plus hair that texture nine tenths of the mid-tone figure can read
# as grain (the view is then drafted again; the best attempt is kept with a
# warning, ``base_body._dress_view``). Version 1
# judged the mean over the HEAD (the top ``NOISE_HEAD_SHARE`` of the figure):
# bare skin on a bald base, but hair once the hair is part of the base body —
# hair's own strand texture (head noise 3.9-5.3 against 0.5-1.3 bald) made
# the score blind (Task 6 acceptance 2026-11-12: heavy grain 1.04-1.10, a
# clean real fit 1.39). The head and whole-figure ratios are still recorded
# (``head_score``, ``figure_score``), not judged.
#
# The score is the fit's floor over the base back's (the reference at least
# ``NOISE_FLOOR``); ``ok`` when it is at most ``NOISE_LIMIT`` (unchanged).
# Measured 2026-11-12 (synthetic grain = one Gaussian value per pixel added
# to R, G and B alike, seed 0, on the stored base back itself; v1 = head
# mean, v2 = floor):
#
#   back                                   v1 sigma 2 / 4 / 6     v2 sigma 2 / 4 / 6   clean
#   Kai, bald base (head 1.28)             1.13 / 1.44 / 1.82     1.27 / 1.83 / 2.48   1.00
#   Kira, bald base (head 1.31)            1.64 / 2.67 / 3.77     2.54 / 4.71 / 6.93   1.00
#   Kai, haired base (head 5.27)           1.01 / 1.03 / 1.06     1.73 / 2.99 / 4.35   1.00
#   Kira, haired base (head 3.89)          1.01 / 1.03 / 1.08     1.73 / 2.94 / 4.24   1.00
#
#   real fits                              v1      v2
#   calibration 2026-11-09, grainy s51     2.25    1.96   (refused by both)
#   calibration, good s52 / s53            1.38 / 1.29    1.14 / 1.12
#   Kira ecba33c49418 on the haired base   1.39    1.29
#
# (The calibration fits are RGB on black, matted by luminance > 10 for the
# measurement; their base back is the bald Kira of 2026-11-09.) The limit
# 1.75 still sits between the clean fits (at most 1.29) and real grain (1.96);
# sigma 4 and 6 are refused on every base, sigma 2 on the bald Kira only.
#
# Skin detail step (``base_skin``, 2026-11-12): the base front now carries
# real skin detail, and the back/side views are edits of it, so the gate's
# reference (the base back) and the dressed fits (edits of the detailed
# front, through the draft) may both carry it. Re-measured on the spike's
# fronts (claude-out/kai-base-skin/edit-step; Kai = the clone's Qwen2.1 Turbo
# front tpose_base634402e5, Glut = tpose_base07147615; "detailed" = the
# shipped ``transfer_detail`` of the spike's Qwen edit, identical to the
# spike's +hf3.0g within 1 grey level; grain as above, seed 0):
#
#   front                       floor      as a fit vs the       grain sigma 2 / 4 / 6
#                                          neutral reference     neutral vs neutral    detailed vs detailed   detailed vs neutral
#   Kai neutral -> detailed     0.3236 -> 0.3663   1.13          1.88 / 3.34 / 4.87    1.82 / 3.16 / 4.49     2.06 / 3.57 / 5.09
#   Glut neutral -> detailed    0.3299 -> 0.3542   1.07          1.84 / 3.24 / 4.70    1.82 / 3.14 / 4.49     1.96 / 3.37 / 4.82
#
# The detail lifts the floor by 7-13 % only (the smoothest tenth stays
# smooth: the face is the neutral render's, the transfer leaves invented
# shapes and the matte edge out). Worst case for a false refusal — a clean
# fit that carries the detail against a neutral base back: the clean fits
# (at most 1.29) x 1.13 = 1.46, under the limit. Worst case for missed grain
# — sigma 2 on a detailed fit against a detailed base back: 1.82 on both,
# still refused (margin 0.07 instead of 0.09-0.13). ``NOISE_LIMIT`` stays.

#: Version of the measurement (recorded with every gate result).
NOISE_VERSION = 2
#: Fit noise floor / base noise floor above which the fit counts as grainy.
NOISE_LIMIT = 1.75
#: The reference noise is at least this (a perfectly flat base).
NOISE_FLOOR = 0.05
#: Height (px) both images are resampled to before measuring.
NOISE_WORK_HEIGHT = 1024
#: Alpha from which a pixel belongs to the figure.
NOISE_ALPHA = 240
#: Share of the figure height (from the top) that is the head region (recorded only).
NOISE_HEAD_SHARE = 0.12
#: The regions are shrunk by this many pixels (matte edge).
NOISE_ERODE = 4
#: Fewer head pixels than this: no head number (recorded only).
NOISE_MIN_PIXELS = 200
#: Block size (px) of the noise floor.
NOISE_BLOCK = 8
#: The noise floor: this percentile of the block means.
NOISE_QUANTILE = 10
#: Only blocks whose mean grey (0..255) lies in this range count toward the floor.
NOISE_BLOCK_GREY = (32.0, 235.0)
#: Fewer counted blocks inside the figure than this: not measurable.
NOISE_MIN_BLOCKS = 20


def figure_noise_arrays(grey: np.ndarray, alpha: np.ndarray) -> Optional[Dict[str, Optional[float]]]:
    """``{"floor", "head", "figure"}`` noise of a work-size grey image and its
    alpha (see the section note; ``head`` None for too small a head), None
    without a measurable figure."""
    from scipy import ndimage
    figure = np.asarray(alpha) >= NOISE_ALPHA
    if not figure.any() or figure.all():
        return None
    rows = np.where(figure.any(axis=1))[0]
    top, height = int(rows[0]), int(rows[-1] - rows[0] + 1)
    head = figure.copy()
    head[top + int(NOISE_HEAD_SHARE * height):] = False
    head = ndimage.binary_erosion(head, iterations=NOISE_ERODE, border_value=0)
    body = ndimage.binary_erosion(figure, iterations=NOISE_ERODE, border_value=0)
    grey = np.asarray(grey, dtype=np.float64)
    residual = np.abs(grey - ndimage.uniform_filter(grey, size=3, mode="nearest"))
    b = NOISE_BLOCK
    hb, wb = residual.shape[0] // b, residual.shape[1] // b
    means = residual[:hb * b, :wb * b].reshape(hb, b, wb, b).mean(axis=(1, 3))
    level = grey[:hb * b, :wb * b].reshape(hb, b, wb, b).mean(axis=(1, 3))
    inside = (body[:hb * b, :wb * b].reshape(hb, b, wb, b).all(axis=(1, 3))
              & (level >= NOISE_BLOCK_GREY[0]) & (level <= NOISE_BLOCK_GREY[1]))
    if int(inside.sum()) < NOISE_MIN_BLOCKS:
        return None
    return {"floor": float(np.percentile(means[inside], NOISE_QUANTILE)),
            "head": float(residual[head].mean()) if int(head.sum()) >= NOISE_MIN_PIXELS else None,
            "figure": float(residual[body].mean())}


def figure_noise(path: Path) -> Optional[Dict[str, Optional[float]]]:
    """The floor/head/figure noise of a matted image file, None when it cannot
    be measured (unreadable, no matte, no figure, too small a figure)."""
    from PIL import Image
    try:
        with Image.open(path) as opened:
            image = opened.convert("RGBA")
    except (OSError, ValueError):
        return None
    height = NOISE_WORK_HEIGHT
    width = max(1, round(image.width * height / image.height))
    grey = image.convert("RGB").convert("L").resize((width, height), Image.BILINEAR)
    alpha = image.getchannel("A").resize((width, height), Image.BILINEAR)
    return figure_noise_arrays(np.asarray(grey), np.asarray(alpha))


def _ratio(fit: Optional[float], base: Optional[float]) -> Optional[float]:
    return None if fit is None or base is None else round(fit / max(base, NOISE_FLOOR), 4)


def noise_gate(path: Path, reference: Optional[Path]) -> Dict[str, Any]:
    """``{"ok", "score", "limit", "version", "noise", "reference_noise",
    "head_score", "figure_score"}`` of a fitted back against the base back
    ``reference`` (``noise`` / ``reference_noise``: the two noise floors); an
    image that cannot be measured passes with ``score None`` and a
    ``reason``. The limit holds for skin-detailed bases too (measured, see
    the section note: the base front's skin step lifts the floor by 7-13 %,
    clean fits stay at most 1.46, sigma-2 grain reads 1.82)."""
    noise = figure_noise(path)
    base = figure_noise(reference) if reference is not None else None
    if noise is None or base is None:
        return {"ok": True, "score": None, "limit": NOISE_LIMIT, "version": NOISE_VERSION,
                "noise": noise and round(noise["floor"], 4), "reference_noise": base and round(base["floor"], 4),
                "reason": "fit not measurable" if noise is None else "base back not measurable"}
    score = noise["floor"] / max(base["floor"], NOISE_FLOOR)
    return {"ok": score <= NOISE_LIMIT, "score": round(score, 4), "limit": NOISE_LIMIT, "version": NOISE_VERSION,
            "noise": round(noise["floor"], 4), "reference_noise": round(base["floor"], 4),
            "head_score": _ratio(noise["head"], base["head"]),
            "figure_score": _ratio(noise["figure"], base["figure"])}


# --- Framing of a dressed view (fix round T12-F1, ruling F14 h) ----------------
#
# A dressed edit must keep the figure where the base view has it: the shape
# and the texture are registered pixel-wise against the base view, so a
# figure that the edit model re-framed (moved up or down, scaled) puts wrong
# geometry into the shape. Measured on the silhouette — the alpha masks the
# other gates read (``view_guard``'s matte, ``noise_gate``'s alpha): its top
# and bottom rows as fractions of the frame height, against the base view's.
#
# The limit, derived from the measured cases:
# - a square-canvas edit (the source centred on a square, cropped back —
#   ``garment_images``) keeps the frame: body XOR 0.005–0.007 against the base
#   (2026-11-09 end-to-end run), i.e. well under 1 % of the height;
# - the same edit sent at its narrow crop size re-framed the figure by ~2 %
#   (2026-11-09: body XOR 0.111), a correct image that only moved;
# - hub job 0544b374 (Kira's dressed front, Qwen2.1-Turbo, 686×1536 sent at
#   1536²): the silhouette ran 0.036–0.999 against 0.024–0.968 — top +1.2 %,
#   bottom +3.1 %, the feet cut off at the frame.
# 3 % lies above the ~2 % re-frame the square canvas now prevents and below
# 0544's +3.1 % that cut the feet: refused only above it. Drift above 1 % (the
# square canvas's own spread is far below it) is kept with a warning.
FRAMING_LIMIT = 0.03
FRAMING_WARN = 0.01
# A dressed view must show the base view's body in its pose (Ruling A123): a garment only ADDS to the
# silhouette, so with both figures brought to one height and one horizontal centre, the dressed figure
# covers the whole base figure up to a matting rim. Glut 2026-11-16: a dressed front drawn as a NEW
# picture (re-posed from the outfit's reference, arms and legs elsewhere, the body 11 % narrower)
# covered 87 % and painted the background (white) onto arms, scalp and shin; the back, an edit of the
# base back, covered 99 %. Below 95 % the view is refused like a framing drift.
COVERAGE_MIN = 0.95


def _silhouette_rows(alpha: np.ndarray) -> Optional[Dict[str, float]]:
    """``{top, bottom, width}`` of the largest figure in an alpha matte as
    fractions of the frame height (``bottom`` = one past the last row),
    plus ``touches`` (the figure reaches the top or bottom frame row). None
    without a figure or a matte (no transparent pixel)."""
    from scipy import ndimage as ndi
    alpha = np.asarray(alpha)
    if alpha.size == 0 or alpha.min() > 127:
        return None
    mask = alpha > 127
    labels, count = ndi.label(mask)
    if count == 0:
        return None
    if count > 1:
        sizes = ndi.sum(mask, labels, range(1, count + 1))
        mask = labels == 1 + int(np.argmax(sizes))
    rows = np.nonzero(mask.any(axis=1))[0]
    cols = np.nonzero(mask.any(axis=0))[0]
    h = float(mask.shape[0])
    return {"top": float(rows[0]) / h, "bottom": float(rows[-1] + 1) / h,
            "width": float(cols[-1] + 1 - cols[0]) / h,
            "touches": bool(rows[0] == 0 or rows[-1] == mask.shape[0] - 1)}


def _coverage(mask: np.ndarray, base_mask: np.ndarray) -> float:
    """Share of the base figure's pixels that the dressed figure covers once both stand at one height and
    one horizontal centre (block above): each base pixel looks up the dressed pixel at the same place
    relative to the figure's top row and centroid column, scaled by the height ratio (the canvases may
    differ in width). 1.0 without a figure on either side (nothing to judge)."""
    if not mask.any() or not base_mask.any():
        return 1.0
    rows, cols = np.nonzero(mask)
    brows, bcols = np.nonzero(base_mask)
    ratio = (rows.max() + 1 - rows.min()) / float(brows.max() + 1 - brows.min())
    y = np.rint(rows.min() + (brows - brows.min()) * ratio).astype(int)
    x = np.rint(cols.mean() + (bcols - bcols.mean()) * ratio).astype(int)
    inside = (y >= 0) & (y < mask.shape[0]) & (x >= 0) & (x < mask.shape[1])
    covered = np.zeros(len(brows), dtype=bool)
    covered[inside] = mask[y[inside], x[inside]]
    return float(covered.mean())


def framing_arrays(alpha: np.ndarray, base_alpha: np.ndarray) -> Dict[str, Any]:
    """``{"ok", "top", "bottom", "width", "limit", "warning"?, "cut"?}`` of a
    dressed view's matte against its base view's (block above): ``top`` /
    ``bottom`` the drift of the silhouette's top / bottom row (dressed minus
    base, fractions of the frame height, + = down), ``width`` the change of
    its horizontal extent (an outfit widens it — recorded, never judged);
    ``ok`` False when ``|top|`` or ``|bottom|`` exceeds ``FRAMING_LIMIT``,
    a ``warning`` above ``FRAMING_WARN``; ``cut`` when the dressed figure
    reaches the top or bottom frame row and the base figure does not. An
    unmeasurable pair passes with ``skipped``."""
    mine, base = _silhouette_rows(alpha), _silhouette_rows(base_alpha)
    if mine is None or base is None:
        return {"ok": True, "limit": FRAMING_LIMIT,
                "skipped": "dressed view without a matte" if mine is None else "base view without a matte"}
    top = round(mine["top"] - base["top"], 4)
    bottom = round(mine["bottom"] - base["bottom"], 4)
    coverage = round(_coverage(np.asarray(alpha) > 127, np.asarray(base_alpha) > 127), 4)
    out: Dict[str, Any] = {"ok": bool(max(abs(top), abs(bottom)) <= FRAMING_LIMIT and coverage >= COVERAGE_MIN),
                           "top": top, "bottom": bottom,
                           "width": round(mine["width"] - base["width"], 4), "limit": FRAMING_LIMIT,
                           "coverage": coverage, "coverage_min": COVERAGE_MIN}
    if mine["touches"] and not base["touches"]:
        out["cut"] = True
    drift = max(abs(top), abs(bottom))
    if drift > FRAMING_WARN:
        out["warning"] = framing_message(out)
    return out


def framing_message(record: Dict[str, Any], view: str = "") -> str:
    """The refusal / warning text of a framing record: which edge moved by how much, or how little of the
    base figure the dressed figure covers."""
    what = f"{view} view: " if view else ""
    edges = max(abs(record.get("top") or 0), abs(record.get("bottom") or 0))
    coverage = record.get("coverage")
    if coverage is not None and coverage < record.get("coverage_min", COVERAGE_MIN) and \
            edges <= record.get("limit", FRAMING_LIMIT):
        return (f"{what}the dressed image shows a different body or pose: it covers {coverage * 100:.1f} % of "
                f"the base figure (minimum {record.get('coverage_min', COVERAGE_MIN) * 100:.0f} %)")
    edge = "bottom" if abs(record.get("bottom") or 0) >= abs(record.get("top") or 0) else "top"
    drift = float(record.get(edge) or 0) * 100
    cut = " — cut at the frame" if record.get("cut") else ""
    return (f"{what}the figure moved: its {edge} edge shifted {drift:+.1f} % of the height "
            f"(limit {record.get('limit', FRAMING_LIMIT) * 100:.0f} %){cut}")


def framing_gate(path: Path, base_view: Optional[Path]) -> Dict[str, Any]:
    """``framing_arrays`` of a dressed view file against its base view file:
    the dressed view's alpha as stored (post-processed with the mesh-input
    matte), the base view's as stored or, without a matte, the mesh-input
    matte (``base_body.cut_out``). Never raises: an unreadable file passes
    with ``skipped``."""
    from PIL import Image
    if base_view is None:
        return {"ok": True, "limit": FRAMING_LIMIT, "skipped": "base view missing"}
    try:
        with Image.open(path) as im:
            alpha = np.asarray(im.convert("RGBA").getchannel("A"))
        from app.core.base_body import cut_out
        base_alpha = np.asarray(cut_out(Path(base_view)).getchannel("A"))
    except Exception as e:  # noqa: BLE001 — a gate that cannot read never blocks
        return {"ok": True, "limit": FRAMING_LIMIT, "skipped": f"not measurable: {e}"}
    return framing_arrays(alpha, base_alpha)
