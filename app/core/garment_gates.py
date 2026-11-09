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

``bottoms_agree`` compares the bottom edges of the front and back hair;
``bottoms_reason`` words a disagreement as a refusal of a front attempt.
``hair_length`` measures where the hair of the haired BACK view ends against
the figure (the front prompts get it as a length phrase).

Clothing (an own-mesh outfit piece, plan
``docs/superpowers/plans/2026-11-09-base-body-phase5-mesh-items.md``, Task 2)
has its own two gates and its own pair check, see "Clothing" below.
"""
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

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


#: The haired view's hair is measured above this share of the figure height
#: (``hair_length``): far below the longest hair the prompts describe.
HAIR_LENGTH_ZONE = 0.50


def hair_length(bald_rgb, bald_mask, haired_rgb, haired_mask) -> Optional[Dict[str, Any]]:
    """Where the hair of a haired view ends, against the base figure:
    ``{"bottom": row, "t": (row − y0) / Hb}`` or None (no figure, no hair).

    Hair = haired mask AND (|ΔRGB| > 20 OR outside the base mask) above
    ``y0 + 0.5·Hb``, opened ``HAIR_REF_OPEN`` iterations (scaled by H / 1536,
    as ``hair_ref``); the LARGEST component is the hair mass that hangs from
    the head, its lowest row the bottom. Meant for the BACK view, where the
    whole length is visible; the front hides the ends behind the body."""
    from scipy import ndimage
    _check(bald_rgb, bald_mask, haired_rgb, haired_mask)
    m0, m1 = np.asarray(bald_mask, dtype=bool), np.asarray(haired_mask, dtype=bool)
    zones = _zones(m0)
    if zones is None or zones[1] <= 0:
        return None
    y0, hb = zones
    hair = m1 & ((_diff(bald_rgb, haired_rgb) > HAIR_REF_DRGB) | ~m0)
    hair[int(y0 + HAIR_LENGTH_ZONE * hb):] = False
    hair = ndimage.binary_opening(hair, iterations=_iterations(HAIR_REF_OPEN, m0.shape[0]))
    labels, count = ndimage.label(hair)
    if not count:
        return None
    largest = int(np.argmax(np.bincount(labels.ravel())[1:])) + 1
    bottom = int(np.nonzero((labels == largest).any(1))[0].max())
    return {"bottom": bottom, "t": round((bottom - y0) / hb, 4)}


def bottoms_gap(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> Optional[tuple]:
    """``(|bottom_front − bottom_back|, limit)`` with limit = 0.05 × the
    taller hair height (all as fractions of H); None when a record lacks
    the numbers (a gate that stopped before measuring)."""
    try:
        fb, bb = float(front_gate["bottom"]), float(back_gate["bottom"])
        height = max(float(front_gate["hair_h"]), float(back_gate["hair_h"]))
    except (KeyError, TypeError, ValueError):
        return None
    return abs(fb - bb), BOTTOM_AGREE * height


def bottoms_agree(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> bool:
    """Front and back hair end at the same height: |bottom_front − bottom_back|
    ≤ 0.05 × the taller hair height (all as fractions of H)."""
    gap = bottoms_gap(front_gate, back_gate)
    return gap is not None and gap[0] <= gap[1]


def bottoms_reason(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> Optional[str]:
    """The refusal reason of a front hair-only attempt that does not end
    where the accepted back view's hair ends (``bottoms_agree``); None when
    they agree or the attempt has no measured hair."""
    gap = bottoms_gap(front_gate, back_gate)
    if gap is None or gap[0] <= gap[1]:
        return None
    return (f"hair ends at another height than in the back view: |Δ| {_r(gap[0], 4)} H > {_r(gap[1], 4)} H "
            f"(front {front_gate.get('bottom')}, back {back_gate.get('bottom')})")


# --- Clothing ---------------------------------------------------------------
#
# The clothing chain edits the bald, bare base view into ``worn`` (the figure
# wearing only the piece) and that into ``ghost`` (the piece alone on an
# invisible body). Every pixel number below is a fraction of the base figure
# height Hb (``_zones`` of the base mask), every area a share of an area, so
# the limits hold at any image size.
#
# Calibration (``~/claude-out/phase5-calib/calibrate.py`` on the S1 spike:
# ``kleid/dress_front|back.png`` against the bald base views
# ``bald/cur_apose_s41.png`` / ``bald/userback_a0f40bdb.png``, the ghosts
# ``kleid/ghost_front_s51..s53.png`` + ``ghost_back.png``; 1536², BiRefNet-DIS
# masks as ``garment_images._mask``; base figure y0 30 / 27, Hb 1452 / 1427):
#
# worn                    front     back      limit
#   garment_share         0.701     0.7102    >= 0.01   (something was put on)
#   outside_dRGB          5.26      4.30      < 8.0
#   outside_xor           0.0074    0.0048    < 0.015
#   head_garment          0.0       0.0       <= 0.05
# refused on purpose: the worn front moved 3 px right (outside_xor 0.0366),
# 6 px (dRGB 8.86, xor 0.0392, head 0.074), the other view's worn image
# (xor 0.1314, head 0.381), the head 20 % darker (head_garment 0.869).
#
# ghost (front vs the worn front's garment region; back vs the worn back's)
#                 top_dy     centre_dx  w_ratio  skin_left  outside  neck_fill
#   s52 (taken)   +0.00069   +0.00034   0.998    0.00014    0.0010   0.542
#   s51           -0.00413    0.0       1.004    0.0002     0.0005   0.774
#   s53           -0.00482    0.0       1.004    0.00009    0.0003   0.802
#   unseeded      -0.00207   +0.00069   1.088    0.00096    0.2478   0.594
#   s52 + legs    +0.00069   -0.00413   1.207    0.2223     0.3065   0.542
#   worn front    -0.146     +0.00069   1.580    0.4389     0.5829   0.998
#   back (taken)  -0.0028    +0.00035   1.007    0.0        0.0002   (no neckline)
#   limit       |..|<=0.0055 |..|<=0.007 [0.95,1.05] <=0.005 <=0.05  (reported)
# s51 and s53 differ from s52 at the neckline: the inside of the back
# fills 77 % / 80 % of the worn neckline opening instead of 54 %. A gate at
# 0.70 was cut between them and RETIRED after the first end-to-end run
# (2026-11-09, Kira, a green linen dress): the ghost front refused at
# neck_fill 0.832 was meshed and fitted anyway (UniForge3D-Multiview, fit on
# the same base) against the accepted ghost (0.411) — the neck opening of
# the prepared mesh, seen from above, was 144 cm² against 166 cm² (both
# wider than the neck), no face within 1 cm of the neck in the 3 cm below the
# neckline in either fit, 0/63 throat rays covered, fit accepted (max push
# 5.4 cm against 4.9 cm). The generator closes no sheet over a filled
# notch, so ``neck_fill`` is recorded and shown, never refused. The s51/s53
# shoulders also sit 6 and 7 px higher (top_dy -0.0041 / -0.0048 against
# +0.0007), but the accepted BACK ghost moved 4 px (-0.0028), so top_dy keeps
# the hair gate's 8 px (0.0055 Hb) instead of a cut between 4 and 6 px on
# one sample.
# The front neckline is 31 px deep (0.0213 Hb), the back's 13 px (0.0091 Hb):
# a neckline counts from NECKLINE_MIN_DEPTH, so only the front reports neck_fill.
# ``outside`` leaves the neckline opening out (s52 shows the inside of the
# back there: 0.0036 with it, 0.0010 without).
#
# hems_agree: the ghost bottoms against each view's own figure — front s52
# (975 − 30) / 1452 = 0.65083, back (968 − 27) / 1427 = 0.65943, |Δ| 0.0086
# <= HEM_AGREE 0.02 (≈ 3.4 cm on a 1.70 m figure).
GARMENT_DRGB = 20.0         # a worn pixel this far from the base belongs to the garment
GARMENT_OPEN = 2            # opening iterations @1536 (thin outline fringes go)
GARMENT_CLOSE = 4           # closing iterations @1536
GARMENT_MIN_COMPONENT = 0.002   # smallest kept part, share of the base body area
GARMENT_MARGIN = 8          # px @1536 around the garment region that belong to its edge
GARMENT_MIN = 0.01          # garment region / base body area, at least
OUTSIDE_DRGB_MAX = 8.0      # mean |ΔRGB| on the figure outside the garment region
OUTSIDE_XOR_MAX = 0.015     # outline change outside the garment region / base body area
HEAD_ZONE = CHIN_ROW        # the head: base figure rows above y0 + 0.13·Hb
HEAD_GARMENT_MAX = 0.05     # share of the head zone inside the garment region
#: The protected zones of the worn gate a piece may change because it is worn
#: there: piece slot -> zones. ONE zone today, ``head`` (rows above the chin
#: row y0 + 0.13·Hb); only a ``head`` piece (hat, hood) frees it. ``neck`` is
#: not in it: the neck lies below the chin row (the shoulder row is 0.19·Hb),
#: so a scarf or collar never reaches the head zone and needs nothing freed.
SLOT_ZONES: Dict[str, Tuple[str, ...]] = {"head": ("head",)}


def occupied_zones(slots: Iterable[str]) -> Tuple[str, ...]:
    """The protected zones (``SLOT_ZONES``) a piece with ``slots`` occupies,
    sorted; the worn gate does not check them."""
    return tuple(sorted({zone for slot in slots or () for zone in SLOT_ZONES.get(str(slot), ())}))
CLOTH_TOP_DY_MAX = 0.0055   # |top edge offset| / Hb (8 px at Hb 1452)
CLOTH_CENTRE_DX_MAX = 0.007  # |centre offset| / Hb
CLOTH_W_RATIO_MIN = 0.95
CLOTH_W_RATIO_MAX = 1.05
SKIN_FACE_ROWS = (0.04, 0.10)   # the skin sample: rows of the base head (y0 + t·Hb)
SKIN_DRGB = 30.0            # a ghost pixel this close to the sampled skin is skin
SKIN_LEFT_MAX = 0.005       # skin outside the garment region / garment area
CLOTH_OUTSIDE_MAX = 0.05    # ghost pixels outside the garment region / garment area
NECKLINE_MIN_DEPTH = 0.012  # notch depth / Hb from which the garment has a neckline
NECKLINE_BAND = 0.03        # ± this share of the garment width around its centre column
HEM_AGREE = 0.02            # |hem_t front − hem_t back|, fractions of Hb


def garment_region(base_rgb, base_mask, worn_rgb, worn_mask) -> np.ndarray:
    """The garment of a worn view: worn mask AND (|ΔRGB| to the base > 20 OR
    outside the base mask), opened 2 and closed 4 iterations (scaled by
    H / 1536, at least 1), parts below 0.2 % of the base body area dropped,
    holes filled (a garment colour close to the skin leaves no gap)."""
    from scipy import ndimage
    _check(base_rgb, base_mask, worn_rgb, worn_mask)
    m0, m1 = np.asarray(base_mask, dtype=bool), np.asarray(worn_mask, dtype=bool)
    height = m0.shape[0]
    region = m1 & ((_diff(base_rgb, worn_rgb) > GARMENT_DRGB) | ~m0)
    region = ndimage.binary_closing(
        ndimage.binary_opening(region, iterations=_iterations(GARMENT_OPEN, height)),
        iterations=_iterations(GARMENT_CLOSE, height))
    labels, count = ndimage.label(region)
    if count:
        sizes = np.bincount(labels.ravel())
        keep = np.nonzero(sizes >= GARMENT_MIN_COMPONENT * max(int(m0.sum()), 1))[0]
        region = np.isin(labels, keep[keep > 0])
    return ndimage.binary_fill_holes(region)


def _margin(region, height: int) -> np.ndarray:
    from scipy import ndimage
    return ndimage.binary_dilation(region, iterations=_iterations(GARMENT_MARGIN, height))


def worn_gate(base_rgb, base_mask, worn_rgb, worn_mask, *, view: str,
              occupied: Iterable[str] = ()) -> Dict[str, Any]:
    """Step 1 gate of clothing: the base view with the piece put on.

    The garment region G = ``garment_region``; everything of the figure
    outside G grown by 8 px @1536 (head, arms, hands, legs, feet for a dress)
    must stay as it was: ``outside_dRGB`` = mean |ΔRGB| where both masks hold
    there (< 8.0), ``outside_xor`` = (base XOR worn mask) there / base body
    area (< 0.015 — a moved limb or a re-framed figure). ``head_garment`` =
    share of the base head zone (rows above y0 + 0.13·Hb) inside G (<= 0.05:
    a changed face joins G and must not pass as garment) — measured always,
    gated only when the piece does not occupy the head (``occupied``, from
    its slots via ``occupied_zones``; ``head_gated`` says which). ``garment_share`` =
    G / base body area (>= 0.01: the edit put something on). ``garment_top``
    / ``garment_bottom`` are G's rows. Limits and their calibration: see the
    "Clothing" block above."""
    _check(base_rgb, base_mask, worn_rgb, worn_mask)
    m0, m1 = np.asarray(base_mask, dtype=bool), np.asarray(worn_mask, dtype=bool)
    zones = _zones(m0)
    if zones is None or zones[1] <= 0:
        return {"view": view, "ok": False, "reasons": ["no figure in the base view"]}
    y0, hb = zones
    height = m0.shape[0]
    region = garment_region(base_rgb, base_mask, worn_rgb, worn_mask)
    area = int(m0.sum())
    share = float(region.sum() / area)
    grown = _margin(region, height)
    outside = m0 & m1 & ~grown
    d_out = _mean(_diff(base_rgb, worn_rgb)[outside])
    xor = float(((m0 ^ m1) & ~grown).sum() / area)
    head = np.zeros_like(m0)
    head[:int(y0 + HEAD_ZONE * hb)] = True
    head &= m0
    head_garment = float((region & head).sum() / max(int(head.sum()), 1))
    box = _bbox(region)
    reasons = []
    if not share >= GARMENT_MIN:
        reasons.append(f"nothing put on: garment {_r(share, 4)} < {GARMENT_MIN}")
    if not d_out < OUTSIDE_DRGB_MAX:
        reasons.append(f"body outside the garment changed colour: {_r(d_out, 2)} >= {OUTSIDE_DRGB_MAX}")
    if not xor < OUTSIDE_XOR_MAX:
        reasons.append(f"body outline outside the garment changed: XOR {_r(xor, 4)} >= {OUTSIDE_XOR_MAX}")
    head_gated = "head" not in set(occupied or ())
    if head_gated and head_garment > HEAD_GARMENT_MAX:
        reasons.append(f"head changed: {_r(head_garment, 3)} of the head > {HEAD_GARMENT_MAX}")
    return {"view": view, "garment_share": _r(share, 4), "outside_dRGB": _r(d_out, 2),
            "outside_xor": _r(xor, 4), "head_garment": _r(head_garment, 4), "head_gated": head_gated,
            "garment_bbox": box,
            "garment_top": box[1] if box else None, "garment_bottom": box[3] if box else None,
            "body_top": y0, "body_h": hb, "ok": not reasons, "reasons": reasons}


def skin_colour(base_rgb, base_mask) -> Optional[np.ndarray]:
    """The skin of the base view: the median RGB of the base head between
    rows y0 + 0.04·Hb and y0 + 0.10·Hb, columns within half the head's
    half-width of its centre (on the back the bald back of the head — the
    same skin). None without a figure."""
    m0 = np.asarray(base_mask, dtype=bool)
    zones = _zones(m0)
    if zones is None or zones[1] <= 0:
        return None
    y0, hb = zones
    r0, r1 = int(y0 + SKIN_FACE_ROWS[0] * hb), max(int(y0 + SKIN_FACE_ROWS[1] * hb), int(y0 + SKIN_FACE_ROWS[0] * hb) + 1)
    span = _span(m0, (r0 + r1) // 2)
    if span is None:
        return None
    cx, hw = span
    x0, x1 = int(cx - hw / 2), int(cx + hw / 2) + 1
    pixels = np.asarray(base_rgb, dtype=np.float32)[r0:r1, x0:x1, :3][m0[r0:r1, x0:x1]]
    return np.median(pixels, 0) if len(pixels) else None


def neckline(region) -> Dict[str, Any]:
    """The neckline of a garment region: ``depth`` = how far the region's
    top edge dips at its centre (median first row of the columns within
    ± 3 % of its width around the bbox centre, minus the region's top row,
    in px) and ``notch`` = the opening as a mask — on every row from the top
    down to the centre's first row, the pixels between the innermost region
    pixels left and right of the centre."""
    region = np.asarray(region, dtype=bool)
    box = _bbox(region)
    notch = np.zeros_like(region)
    if box is None:
        return {"depth": 0, "notch": notch}
    x0, top, x1, _bottom = box
    cx = (x0 + x1) / 2.0
    band = max(1, int(round(NECKLINE_BAND * (x1 - x0))))
    firsts = []
    for x in range(int(cx) - band, int(cx) + band + 1):
        rows = np.nonzero(region[:, x])[0]
        if len(rows):
            firsts.append(int(rows.min()))
    if not firsts:
        return {"depth": 0, "notch": notch}
    centre_top = int(np.median(firsts))
    for row in range(top, centre_top):
        xs = np.nonzero(region[row])[0]
        left, right = xs[xs < cx], xs[xs > cx]
        if len(left) and len(right):
            notch[row, left.max() + 1:right.min()] = True
    return {"depth": centre_top - top, "notch": notch}


def ghost_clothing_gate(base_rgb, base_mask, garment_mask, ghost_rgb, ghost_mask, *,
                        view: str) -> Dict[str, Any]:
    """Step 2 gate of clothing: the piece alone against the garment region of
    the accepted worn view (``garment_region``).

    ``top_dy`` / ``centre_dx`` (fractions of Hb) and ``w_ratio`` / ``h_ratio``
    from the bounding boxes of the region and the ghost mask (|top_dy| <=
    0.0055, |centre_dx| <= 0.007, w_ratio in [0.95, 1.05]); ``skin_left`` =
    ghost pixels outside the region grown by 8 px @1536 whose mean |ΔRGB| to
    the base's skin (``skin_colour``) is <= 30, over the region's area (<=
    0.005: no head, arm, leg or foot left; a skin-coloured garment is not
    counted inside its own region); ``outside`` = every ghost pixel out
    there except in the neckline opening (the inside of the back shows
    there), over the region's area (<= 0.05: no stand, hanger or wider
    garment). When the region has a neckline (``neckline`` depth >= 0.012·Hb)
    ``neck_fill`` = the share of its opening the ghost mask covers — reported,
    not gated (a filled notch still meshes into an open neckline, see the
    calibration block).
    ``bottom`` (row) and ``hem_t`` = (bottom − y0) / Hb feed ``hems_agree``.
    Calibration: the "Clothing" block above."""
    _check(base_rgb, base_mask, ghost_rgb, ghost_mask)
    m0 = np.asarray(base_mask, dtype=bool)
    region = np.asarray(garment_mask, dtype=bool)
    ghost = np.asarray(ghost_mask, dtype=bool)
    if region.shape != m0.shape:
        raise ValueError("garment_mask differs in size from the base")
    height = m0.shape[0]
    zones = _zones(m0)
    if zones is None or zones[1] <= 0:
        return {"view": view, "ok": False, "reasons": ["no figure in the base view"]}
    y0, hb = zones
    a, b = _bbox(region), _bbox(ghost)
    out: Dict[str, Any] = {"view": view, "H": height, "body_top": y0, "body_h": hb,
                           "bbox_garment": a, "bbox_ghost": b}
    if a is None:
        return {**out, "ok": False, "reasons": ["no garment found in the worn view"]}
    if b is None:
        return {**out, "ok": False, "reasons": ["no garment in the ghost image"]}
    top_dy = (b[1] - a[1]) / hb
    centre_dx = (b[0] + b[2] - a[0] - a[2]) / 2.0 / hb
    w_ratio = (b[2] - b[0]) / max(a[2] - a[0], 1)
    h_ratio = (b[3] - b[1]) / max(a[3] - a[1], 1)
    area = max(int(region.sum()), 1)
    beyond = ghost & ~_margin(region, height)
    skin = skin_colour(base_rgb, base_mask)
    if skin is None:
        skin_left = 0.0
    else:
        near = np.abs(np.asarray(ghost_rgb, dtype=np.float32)[..., :3] - skin).mean(2) <= SKIN_DRGB
        skin_left = float((beyond & near).sum() / area)
    neck = neckline(region)
    depth = neck["depth"] / hb
    has_neckline = depth >= NECKLINE_MIN_DEPTH and bool(neck["notch"].any())
    # The inside of the back seen through the neckline is garment, not "more".
    outside = float((beyond & ~neck["notch"]).sum() / area) if has_neckline else float(beyond.sum() / area)
    neck_fill = float((ghost & neck["notch"]).sum() / neck["notch"].sum()) if has_neckline else None
    iou = float((region & ghost).sum() / max((region | ghost).sum(), 1))
    reasons = []
    if abs(top_dy) > CLOTH_TOP_DY_MAX:
        reasons.append(f"garment top moved: {_r(top_dy, 4)} Hb, limit {CLOTH_TOP_DY_MAX}")
    if abs(centre_dx) > CLOTH_CENTRE_DX_MAX:
        reasons.append(f"garment centre moved: {_r(centre_dx, 4)} Hb, limit {CLOTH_CENTRE_DX_MAX}")
    if not CLOTH_W_RATIO_MIN <= w_ratio <= CLOTH_W_RATIO_MAX:
        reasons.append(f"garment width changed: ratio {round(w_ratio, 3)} outside "
                       f"[{CLOTH_W_RATIO_MIN}, {CLOTH_W_RATIO_MAX}]")
    if skin_left > SKIN_LEFT_MAX:
        reasons.append(f"skin left in the image: {_r(skin_left, 4)} > {SKIN_LEFT_MAX}")
    if outside > CLOTH_OUTSIDE_MAX:
        reasons.append(f"more than the garment in the image: {_r(outside, 4)} > {CLOTH_OUTSIDE_MAX}")
    return {**out, "top_dy": _r(top_dy, 5), "centre_dx": _r(centre_dx, 5), "w_ratio": round(w_ratio, 3),
            "h_ratio": round(h_ratio, 3), "iou": round(iou, 3), "skin_left": _r(skin_left, 5),
            "outside": _r(outside, 5), "neckline_depth": _r(depth, 4), "neck_fill": _r(neck_fill, 3),
            "bottom": b[3], "hem_t": _r((b[3] - y0) / hb, 5),
            "ok": not reasons, "reasons": reasons}


def hems_gap(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> Optional[tuple]:
    """``(|hem_t_front − hem_t_back|, HEM_AGREE)`` — both hems against their
    own view's figure (fractions of Hb); None when a record lacks ``hem_t``."""
    try:
        gap = abs(float(front_gate["hem_t"]) - float(back_gate["hem_t"]))
    except (KeyError, TypeError, ValueError):
        return None
    return gap, HEM_AGREE


def hems_agree(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> bool:
    """The front and back garment end at the same height of the figure:
    |hem_t_front − hem_t_back| <= 0.02 (fractions of the body height Hb)."""
    gap = hems_gap(front_gate, back_gate)
    return gap is not None and gap[0] <= gap[1]


def hems_reason(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> Optional[str]:
    """The refusal reason of a front ghost attempt whose hem is not where the
    accepted back's is (``hems_agree``); None when they agree or the attempt
    has no measured hem."""
    gap = hems_gap(front_gate, back_gate)
    if gap is None or gap[0] <= gap[1]:
        return None
    return (f"garment ends at another height than in the back view: |Δ| {_r(gap[0], 4)} Hb > {gap[1]} Hb "
            f"(front {front_gate.get('hem_t')}, back {back_gate.get('hem_t')})")


def gate_summary(records: Sequence[Dict[str, Any]]) -> str:
    """One line for a refusal: every attempt's reasons."""
    parts = []
    for n, record in enumerate(records, 1):
        parts.append(f"attempt {record.get('attempt', n)}: " + ("; ".join(record.get("reasons") or []) or "ok"))
    return " | ".join(parts)


def limits(kind: str = "hair") -> Dict[str, Dict[str, Dict[str, Any]]]:
    """The image-gate limits per step of a garment ``kind`` (``hair`` or
    ``clothing``), for the gate chips — read from the constants above so the
    UI never keeps its own copy. ``op``: ``lt`` / ``le`` / ``ge`` (value must
    stay below / at most / at least), ``abs_le`` (|value| at most), ``range``
    (``value`` = [min, max]); ``per_height``: the limit is a fraction of the
    record's image height ``H`` (pixel numbers; clothing records are already
    fractions of the figure height); ``views``: the views the limit is gated
    on (all when absent). ValueError for another kind."""
    if kind == "clothing":
        return {
            "worn": {
                "garment_share": {"op": "ge", "value": GARMENT_MIN},
                "outside_dRGB": {"op": "lt", "value": OUTSIDE_DRGB_MAX},
                "outside_xor": {"op": "lt", "value": OUTSIDE_XOR_MAX},
                # Not gated for a piece worn on one of ``free_slots`` (SLOT_ZONES).
                "head_garment": {"op": "le", "value": HEAD_GARMENT_MAX,
                                 "free_slots": sorted(s for s, z in SLOT_ZONES.items() if "head" in z)},
            },
            "ghost": {
                "top_dy": {"op": "abs_le", "value": CLOTH_TOP_DY_MAX},
                "centre_dx": {"op": "abs_le", "value": CLOTH_CENTRE_DX_MAX},
                "w_ratio": {"op": "range", "value": [CLOTH_W_RATIO_MIN, CLOTH_W_RATIO_MAX]},
                "skin_left": {"op": "le", "value": SKIN_LEFT_MAX},
                "outside": {"op": "le", "value": CLOTH_OUTSIDE_MAX},
            },
        }
    if kind != "hair":
        raise ValueError(f"no image gates for garment kind {kind!r}")
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
