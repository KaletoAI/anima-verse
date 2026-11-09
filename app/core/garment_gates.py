"""Image gates of the garment chain — pure numpy on arrays
(plan ``docs/superpowers/plans/2026-11-09-base-body-phase4-hair.md``, R7).

Every function takes same-shaped arrays: RGB as ``(H, W, 3)`` (any numeric
dtype) and masks as ``(H, W)`` bool. The caller resamples an edit to the
base view's size first (pure scale, R6). The zones come from the BASE mask:
``y0`` = its top row, ``Hb`` = its last row minus ``y0``.

Two image gates, one per edit step (values from the spike report, pixel
limits as fractions of the image height H — the spike ran at H = 1536):

- ``haired_gate`` (step 1, the base view with hair added): the body below
  ``y0 + 0.30·Hb`` must stay as it was — mask XOR share and mean |ΔRGB|
  there — and on the front the chest box must stay free of hair. On the back
  the body-RGB check leaves out the central column where back hair falls.
- ``ghost_gate`` (step 2, the hair alone on an invisible head): the hair
  must keep its place and width against the hair of the haired view
  (``hair_ref``), and no piece of the body may be left ("body left": ghost
  pixels on the base body below the chin line that still have its colour).

``bottoms_agree`` compares the bottom edges of the front and back hair.
"""
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

#: The image height the spike's pixel numbers were measured at.
SPIKE_HEIGHT = 1536

# --- Zones (fractions of the base figure height Hb, below its top y0) --------
BODY_ZONE = 0.30        # rows below: the body that must stay unchanged
CHEST_TOP = 0.17        # chest box rows CHEST_TOP .. BODY_ZONE
SHOULDER_ROW = 0.19     # the row whose mask span gives centre + shoulder half-width
CHEST_HALF = 0.6        # chest box / back column: ± this share of the half-width
HAIR_REF_ROW = 0.22     # hair of the haired view is looked for above this row
CHIN_ROW = 0.13         # "body left" is counted below this row

# --- Haired view (S1) -----------------------------------------------------
BODY_XOR_MAX = 0.015        # share of the base body area below BODY_ZONE
BODY_DRGB_MAX = 6.0         # mean |ΔRGB| on the body below BODY_ZONE
CHEST_DRGB_MAX = 8.0        # mean |ΔRGB| in the chest box (front only)

# --- Hair-only view (S2) --------------------------------------------------
TOP_DY_MAX = 0.0052         # |top edge offset| / H   (8 px @1536)
CENTRE_DX_MAX = 0.0065      # |centre offset| / H     (10 px @1536)
W_RATIO_MIN = 0.93
W_RATIO_MAX = 1.07
BODY_LEFT_DRGB = 20.0       # a ghost pixel this close to the base colour is body
# Share of the base body area (ruling, Task 4 calibration). Catches large
# leftovers only (neck/shoulders >= ~0.15 measured); a thin neck stub is
# indistinguishable from light hair by colour (clean spike ghosts of
# medium blonde hair scored 0.0075..0.0186) — the mesh gates (bib, largest
# part) are the second net.
BODY_LEFT_MAX = 0.05
BOTTOM_AGREE = 0.05         # front/back bottom edges within this × hair height

# --- hair_ref (measure_s2.hair_ref, scaled by H / SPIKE_HEIGHT) -------------
HAIR_REF_DRGB = 20.0        # haired pixel that differs this much from the base is hair
HAIR_REF_OPEN = 2           # opening iterations @1536
HAIR_REF_CLOSE = 4          # closing iterations @1536
HAIR_REF_MIN_AREA = 400     # smallest kept component in px @1536


def _check(rgb_a, mask_a, rgb_b, mask_b) -> None:
    shapes = {np.shape(mask_a), np.shape(mask_b), np.shape(rgb_a)[:2], np.shape(rgb_b)[:2]}
    if len(shapes) != 1:
        raise ValueError(f"gate inputs differ in size: {sorted(shapes)}")


def _diff(a, b) -> np.ndarray:
    """Per-pixel mean |ΔRGB|."""
    return np.abs(np.asarray(a, dtype=np.float32)[..., :3] - np.asarray(b, dtype=np.float32)[..., :3]).mean(2)


def _zones(mask) -> Optional[tuple]:
    """``(y0, Hb)`` of a mask, None when it is empty."""
    rows = np.nonzero(np.asarray(mask).any(1))[0]
    if not len(rows):
        return None
    return int(rows.min()), int(rows.max() - rows.min())


def _span(mask, row: int) -> Optional[tuple]:
    """``(centre x, half-width)`` of the mask's extent on ``row``."""
    xs = np.nonzero(np.asarray(mask)[row])[0]
    if not len(xs):
        return None
    return (xs.min() + xs.max()) / 2.0, (xs.max() - xs.min()) / 2.0


def _bbox(mask) -> Optional[List[int]]:
    ys, xs = np.nonzero(mask)
    if not len(ys):
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]


def _mean(values) -> float:
    return float(values.mean()) if values.size else float("inf")


def _r(value: float, digits: int) -> Optional[float]:
    return None if value is None or not np.isfinite(value) else round(float(value), digits)


def haired_gate(bald_rgb, bald_mask, haired_rgb, haired_mask, *, view: str) -> Dict[str, Any]:
    """Step 1 gate (``measure_s1.run`` + ``ok``/``reasons``).

    ``body_xor`` = (base XOR haired mask) below the body zone / base body area
    there; ``body_dRGB`` = mean |ΔRGB| where both masks hold below the zone —
    on the back without the column |x − cx| ≤ 0.6·half-width; ``chest_dRGB`` =
    mean |ΔRGB| on the base mask inside rows 0.17..0.30·Hb, x within
    ± 0.6·half-width (gated on the front only). ``hair_added_*`` = new mask
    pixels above the body zone."""
    _check(bald_rgb, bald_mask, haired_rgb, haired_mask)
    m0, m1 = np.asarray(bald_mask, dtype=bool), np.asarray(haired_mask, dtype=bool)
    zones = _zones(m0)
    if zones is None:
        return {"view": view, "ok": False, "reasons": ["no figure in the base view"]}
    y0, hb = zones
    yb = int(y0 + BODY_ZONE * hb)
    span = _span(m0, int(y0 + SHOULDER_ROW * hb))
    if span is None:
        return {"view": view, "ok": False, "reasons": ["no shoulder row in the base view"]}
    cx, hw = span
    body0, body1 = m0[yb:], m1[yb:]
    body_area = int(body0.sum())
    xor = float((body0 ^ body1).sum() / body_area) if body_area else float("inf")
    d = _diff(bald_rgb, haired_rgb)
    both = body0 & body1
    if view == "back":
        cols = np.abs(np.arange(m0.shape[1]) - cx) <= CHEST_HALF * hw
        both = both & ~cols[None, :]
    dbody = _mean(d[yb:][both])
    cy0, cy1 = int(y0 + CHEST_TOP * hb), yb
    cx0, cx1 = int(cx - CHEST_HALF * hw), int(cx + CHEST_HALF * hw)
    dchest = _mean(d[cy0:cy1, cx0:cx1][m0[cy0:cy1, cx0:cx1]])
    added = m1 & ~m0
    added[yb:] = False
    top_rows = np.nonzero(m1.any(1))[0]
    reasons = []
    if not xor < BODY_XOR_MAX:
        reasons.append(f"body outline changed: XOR {_r(xor, 4)} >= {BODY_XOR_MAX}")
    if not dbody < BODY_DRGB_MAX:
        reasons.append(f"body colour changed: {_r(dbody, 2)} >= {BODY_DRGB_MAX}")
    if view == "front" and not dchest < CHEST_DRGB_MAX:
        reasons.append(f"hair over the chest: {_r(dchest, 2)} >= {CHEST_DRGB_MAX}")
    return {"view": view, "body_xor": _r(xor, 4), "body_dRGB": _r(dbody, 2), "chest_dRGB": _r(dchest, 2),
            "hair_added_px": int(added.sum()), "hair_added_bbox": _bbox(added),
            "head_top_bald": y0, "body_h": hb,
            "top_haired": int(top_rows.min()) if len(top_rows) else None,
            "ok": not reasons, "reasons": reasons}


def _iterations(base: int, height: int) -> int:
    return max(1, int(round(base * height / SPIKE_HEIGHT)))


def hair_ref(bald_rgb, bald_mask, haired_rgb, haired_mask) -> np.ndarray:
    """The hair of the haired view (``measure_s2.hair_ref``): haired mask AND
    (|ΔRGB| > 20 OR outside the base mask), above ``y0 + 0.22·Hb``, opened 2
    and closed 4 iterations, components below 400 px dropped — iterations
    scaled by H / 1536 (at least 1), the area by its square."""
    from scipy import ndimage
    _check(bald_rgb, bald_mask, haired_rgb, haired_mask)
    m0, m1 = np.asarray(bald_mask, dtype=bool), np.asarray(haired_mask, dtype=bool)
    zones = _zones(m0)
    if zones is None:
        return np.zeros_like(m0)
    y0, hb = zones
    height = m0.shape[0]
    hair = m1 & ((_diff(bald_rgb, haired_rgb) > HAIR_REF_DRGB) | ~m0)
    hair[int(y0 + HAIR_REF_ROW * hb):] = False
    hair = ndimage.binary_closing(
        ndimage.binary_opening(hair, iterations=_iterations(HAIR_REF_OPEN, height)),
        iterations=_iterations(HAIR_REF_CLOSE, height))
    labels, count = ndimage.label(hair)
    if count:
        sizes = np.bincount(labels.ravel())
        min_area = HAIR_REF_MIN_AREA * (height / SPIKE_HEIGHT) ** 2
        keep = np.nonzero(sizes >= min_area)[0]
        hair = np.isin(labels, keep[keep > 0])
    return hair


def ghost_gate(bald_rgb, bald_mask, hair_ref_mask, ghost_rgb, ghost_mask, *, view: str) -> Dict[str, Any]:
    """Step 2 gate: the hair-only image against the hair of the haired view.

    ``top_dy`` / ``centre_dx`` / ``w_ratio`` / ``h_ratio`` from the bounding
    boxes of ``hair_ref_mask`` and the ghost mask; ``body_left_px`` = ghost
    pixels inside the base mask, at or below the chin row ``y0 + 0.13·Hb``,
    whose mean |ΔRGB| to the base image is ≤ 20, and ``body_left`` that count
    over the base body area. ``bottom`` / ``hair_h`` (fractions of H) feed
    ``bottoms_agree``. Limits: |top_dy| ≤ 0.0052·H, |centre_dx| ≤ 0.0065·H,
    w_ratio in [0.93, 1.07], body_left ≤ ``BODY_LEFT_MAX`` (large leftovers
    only — see the constant)."""
    _check(bald_rgb, bald_mask, ghost_rgb, ghost_mask)
    m0 = np.asarray(bald_mask, dtype=bool)
    ref = np.asarray(hair_ref_mask, dtype=bool)
    ghost = np.asarray(ghost_mask, dtype=bool)
    if ref.shape != m0.shape:
        raise ValueError("hair_ref_mask differs in size from the base")
    height = m0.shape[0]
    zones = _zones(m0)
    if zones is None:
        return {"view": view, "ok": False, "reasons": ["no figure in the base view"]}
    y0, hb = zones
    a, b = _bbox(ref), _bbox(ghost)
    out: Dict[str, Any] = {"view": view, "H": height, "bbox_hair": a, "bbox_ghost": b}
    if a is None:
        return {**out, "ok": False, "reasons": ["no hair found in the haired view"]}
    if b is None:
        return {**out, "ok": False, "reasons": ["no hair in the hair-only image"]}
    top_dy = b[1] - a[1]
    centre_dx = (b[0] + b[2] - a[0] - a[2]) / 2.0
    centre_dy = (b[1] + b[3] - a[1] - a[3]) / 2.0
    w_ratio = (b[2] - b[0]) / max(a[2] - a[0], 1)
    h_ratio = (b[3] - b[1]) / max(a[3] - a[1], 1)
    chin = int(y0 + CHIN_ROW * hb)
    left = ghost & m0 & (_diff(bald_rgb, ghost_rgb) <= BODY_LEFT_DRGB)
    left[:chin] = False
    body_left_px = int(left.sum())
    body_area = int(m0.sum())
    body_left = body_left_px / body_area
    iou = float((ref & ghost).sum() / max((ref | ghost).sum(), 1))
    reasons = []
    if abs(top_dy) > TOP_DY_MAX * height:
        reasons.append(f"hair top moved: {top_dy} px > {TOP_DY_MAX * height:.1f}")
    if abs(centre_dx) > CENTRE_DX_MAX * height:
        reasons.append(f"hair centre moved: {centre_dx} px > {CENTRE_DX_MAX * height:.1f}")
    if not W_RATIO_MIN <= w_ratio <= W_RATIO_MAX:
        reasons.append(f"hair width changed: ratio {round(w_ratio, 3)} outside [{W_RATIO_MIN}, {W_RATIO_MAX}]")
    if body_left > BODY_LEFT_MAX:
        reasons.append(f"body left in the image: {round(body_left, 4)} > {BODY_LEFT_MAX}")
    return {**out, "top_dy": int(top_dy), "centre_dx": centre_dx, "centre_dy": centre_dy,
            "w_ratio": round(w_ratio, 3), "h_ratio": round(h_ratio, 3), "iou": round(iou, 3),
            "body_left_px": body_left_px, "body_left": round(body_left, 5), "chin_row": chin,
            "bottom": round(b[3] / height, 5), "hair_h": round((b[3] - b[1]) / height, 5),
            "ok": not reasons, "reasons": reasons}


def bottoms_agree(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> bool:
    """Front and back hair end at the same height: |bottom_front − bottom_back|
    ≤ 0.05 × the taller hair height (all as fractions of H)."""
    try:
        fb, bb = float(front_gate["bottom"]), float(back_gate["bottom"])
        height = max(float(front_gate["hair_h"]), float(back_gate["hair_h"]))
    except (KeyError, TypeError, ValueError):
        return False
    return abs(fb - bb) <= BOTTOM_AGREE * height


def gate_summary(records: Sequence[Dict[str, Any]]) -> str:
    """One line for a refusal: every attempt's reasons."""
    parts = []
    for n, record in enumerate(records, 1):
        parts.append(f"attempt {record.get('attempt', n)}: " + ("; ".join(record.get("reasons") or []) or "ok"))
    return " | ".join(parts)


def limits() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """The image-gate limits per step, for the Hair tab's chips — read from
    the constants above so the UI never keeps its own copy. ``op``: ``lt`` /
    ``le`` (value must stay below / at most), ``abs_le`` (|value| at most),
    ``range`` (``value`` = [min, max]); ``per_height``: the limit is a
    fraction of the record's image height ``H`` (pixel numbers); ``views``:
    the views the limit is gated on (all when absent)."""
    return {
        "haired": {
            "body_xor": {"op": "lt", "value": BODY_XOR_MAX},
            "body_dRGB": {"op": "lt", "value": BODY_DRGB_MAX},
            "chest_dRGB": {"op": "lt", "value": CHEST_DRGB_MAX, "views": ["front"]},
        },
        "ghost": {
            "top_dy": {"op": "abs_le", "value": TOP_DY_MAX, "per_height": True},
            "centre_dx": {"op": "abs_le", "value": CENTRE_DX_MAX, "per_height": True},
            "w_ratio": {"op": "range", "value": [W_RATIO_MIN, W_RATIO_MAX]},
            "body_left": {"op": "le", "value": BODY_LEFT_MAX},
        },
    }
