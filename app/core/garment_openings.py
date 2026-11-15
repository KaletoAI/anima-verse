"""Openings from the worn view in the cut-out (Ruling A60, 2026-11-14).

The multiview mesher builds whatever the cut-out shows as a surface. Kira's blazer (``item_5bfe0cbc``) is cut out
from a piece-only view (``ghost``) that shows the INSIDE back lining through the V neckline — black like the
blazer — and the mesher closed the V with a front sheet. The worn view says what the V is: the body shows there,
inside the piece's outline. Before the mesh, the cut-out is made TRANSPARENT there, so the mesher sees a hole.

The mask (``opening``; pixel numbers at 1536 px of the ghost's height, scaled with it; the cut-out frame is the
ghost frame cropped and scaled by ``final / side`` of the cut-out record):

1. EVIDENCE (worn frame = ghost frame: the piece-only view is registered onto the worn view): the base copy's
   figure outside the A46 piece mask (``garment_from_worn.piece_mask`` — the worn view minus the base it was
   edited from): there the worn view shows the body as the base shows it. FRAMING: ``piece_mask`` refuses a worn
   view whose trimmed framing cost is above ``garment_from_worn.ALIGN_COST_MAX`` (12). That cost is the mean of
   the best-agreeing 90 % of ALL pixels, so a piece that covers more than a tenth of the image raises it by its
   own area: Kira's blazer covers 0.17 of the image and costs 11.7 / 12.7 at shift 0 although the figure outside
   it agrees to 3.8 / 4.7 (a worn view shifted by 2 px or scaled by 1 % costs only 0.0 / +0.9 more). Here the
   worn step's own outline check vouches for the framing instead (``framing_vouched``): the accepted worn view's
   gate measured the figure outline outside the garment against the same base — ``outside_xor`` within its
   ``outside_xor_limit`` and an outline drift of at most ``VOUCH_DRIFT_PX`` (the three blazer groups: 0.29 /
   0.38 / 0.57 px; the gate's own edited-view limit is 2.0). Without that, a refused framing gives no evidence.
2. SEED (ghost frame): the components of evidence ∩ garment (the cut-out's alpha), opened by
   ``garment_fit.OPEN_ERODE_PX``, of at least ``garment_fit.OPEN_MIN_SHARE`` of the garment, whose ring of
   ``garment_fit.OPEN_RING_PX`` lies at most ``garment_fit.OPEN_SHOWN_OUTLINE_MAX`` outside the garment (A51's
   ring rule: the garment encloses the opening — a gap at the hem or a notch at the edge stays closed) AND of which
   at least ``DIFFERS_MIN_SHARE`` differs between the worn view and the piece-only view by more than
   ``garment_fit.OPEN_DIFF`` in some channel (the A51 fit's own opening test, ``garment_source.opening_masks``):
   through a real opening the worn view shows the body and the piece-only view its inside (Ruling A81). The
   evidence alone is no proof: the A46 piece mask is lenient on purpose (a 5 px match disc, skin-hued areas taken
   out), so the shaded folds of a light, warm piece match a skin pixel nearby and leave gaps in it — Ylva's linen
   blouse got 7 holes cut in plain fabric (worn vs piece-only 4–28 per channel mean there; of an enclosed component
   at most 0.161 past ``OPEN_DIFF`` on the front, 0.001 on the back; Kira's blazer V: 155 / 163, 0.994 / 0.987).
3. COLLAR: nothing above the NECK BASE opens — the first row below the neck's narrowest row (searched in
   ``NECK_SEARCH`` of the figure's height) where the base figure is ``NECK_BASE_RATIO`` times as wide. The back of
   the collar the piece-only view shows behind the neck stays a closed band (the worn view shows the neck there,
   which hides the collar, not a hole).
4. EDGE SNAP (cut-out frame): the seed comes from the worn view, whose opening and the piece-only view's lapels
   never lie on exactly the same pixels — taken as it is, its border is a saw-tooth with a strip of lining beside
   it. Per component and per row, its left border moves to the steepest luminance step between the garment's shade
   and the inside's within ``SNAP_REACH`` of the piece's width (the luminance smoothed by ``EDGE_SIGMA_PX``; a step
   below ``EDGE_STEP_MIN`` per pixel leaves the seed's border), its right border to the steepest step back; which
   way the step goes (a dark lining in a light piece or the reverse) is measured, not assumed. The borders are
   smoothed (a running median over ``BORDER_ROWS`` rows, then a short running mean); a pair that converges below
   the seed (a V whose tip the worn view hides behind the body) runs on to its tip, at most ``EXTEND_REACH``.
5. SMOOTH: opened and closed by a disc of ``SMOOTH_PX``, holes filled, nothing above the collar line; the alpha is
   feathered by ``FEATHER_PX``. The record keeps the saw-tooth (``sawtooth``) and the lining pixels beside the hole
   (``lining_left_px``) of the seed and of the snapped hole.

The SETTING (``SETTING_KEY`` of the item's ``outfit_piece``, ``{view: "off"}``; Auto = no key — like the A46
"Piece-only views from" beside it): per piece and view "Auto" (an opening is cut where the worn view shows enclosed
body inside the piece) or "Off". Not part of the fingerprint. Every cut-out records the opening it found and
whether it applied it (``opening``: ``{version, choice, applied, found, px, share, …}``; the opening is looked
for under Off too, so the record knows what Auto would cut). A cut-out is DUE (``due``) when the setting now
would apply another opening than the one it carries (or the rule ``VERSION`` changed): the chain makes it again
from its own stored colours on the CPU (``garment_images.cut_out`` reuses the upscaled colours of the same
piece-only image — no hub job), then the mesh. A cut-out made before Ruling A60 (no ``opening`` record) stays
current; its own button makes it again on the CPU.
"""
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.log import get_logger

logger = get_logger("garment_openings")

#: Version of the opening rule; a cut-out made under another reads due (``due``). 2 (Ruling A81): a component opens
#: only where the piece-only view differs from the worn view (module docstring 2).
VERSION = 2
#: Key of the setting in the item's ``outfit_piece``: ``{view: "off"}``.
SETTING_KEY = "cutout_openings"
AUTO, OFF = "auto", "off"
CHOICES = (AUTO, OFF)

#: Share of a seed component that must differ between the worn view and the piece-only view by more than
#: ``garment_fit.OPEN_DIFF`` (module docstring 2): the blazer's V 0.994 / 0.987, the false holes in Ylva's blouse at
#: most 0.161.
DIFFERS_MIN_SHARE = 0.5
#: The worn gate's outline drift (px @1536) up to which it vouches for the framing (module docstring 1).
VOUCH_DRIFT_PX = 1.0
#: Share of the figure's height searched for the neck's narrowest row, from the figure's top.
NECK_SEARCH = (0.06, 0.22)
#: The neck base: the first row below the narrowest neck row this many times as wide.
NECK_BASE_RATIO = 1.5
#: Edge snap: per row, each border of the seed looks this far (share of the garment's width in the cut-out) for
#: the cut-out's own edge ...
SNAP_REACH = 0.02
#: ... the steepest luminance step between the garment's shade and the inside's (smoothed by ``EDGE_SIGMA_PX``,
#: px @1536), if at least ``EDGE_STEP_MIN`` per pixel (else the seed's border stays) ...
EDGE_SIGMA_PX = 1.0
EDGE_STEP_MIN = 1.0
#: ... then the borders are smoothed: a running median over ``BORDER_ROWS`` rows (px @1536), then a running mean
#: over a third of that.
BORDER_ROWS = 15
#: A border pair that converges below the seed (a V whose tip the worn view hides) runs on to its tip, at most
#: this share of the garment's width further down.
EXTEND_REACH = 0.04
#: Small morphological open / close of the hole (px @1536) and its alpha feather (sigma, px @1536).
SMOOTH_PX = 1
FEATHER_PX = 0.75
#: Ring (px @1536) beside the hole in which pixels of the inside's colour are counted (``lining_left``).
LINING_RING_PX = 4


def _px(value: float, height: int) -> int:
    return max(1, int(round(value * height / 1536.0)))


# --- The setting ------------------------------------------------------------------------------------------------

def clean_setting(raw: Any) -> Dict[str, str]:
    """``{view: "off"}`` with the known views (Auto = no key)."""
    from app.core.garment_store import GARMENT_VIEWS
    if not isinstance(raw, dict):
        return {}
    return {v: OFF for v in GARMENT_VIEWS if raw.get(v) == OFF}


def choice_of(item: Optional[Dict[str, Any]], view: str) -> str:
    piece = (item or {}).get("outfit_piece") if isinstance((item or {}).get("outfit_piece"), dict) else {}
    return clean_setting(piece.get(SETTING_KEY)).get(view, AUTO)


def set_choice(character_name: str, item_id: str, view: str, choice: str) -> Dict[str, str]:
    """Store the choice of ``view`` (Auto drops the key) on the item in ONE read-modify-write under
    ``keyed_lock("garment_item", character_name)``; runs nothing. The stored setting. ValueError for a bad view
    or choice or an item that is no outfit piece."""
    from app.core.garment_store import GARMENT_VIEWS
    from app.core.keyed_lock import keyed_lock
    from app.models import inventory
    if view not in GARMENT_VIEWS:
        raise ValueError(f"view must be one of {', '.join(GARMENT_VIEWS)}")
    if choice not in CHOICES:
        raise ValueError(f"choice must be one of {', '.join(CHOICES)}")
    with keyed_lock("garment_item", character_name):
        item = inventory.get_item(item_id)
        if not isinstance(item, dict) or item.get("category") != "outfit_piece":
            raise ValueError(f"{str(item_id)[:80]!r} is no outfit piece")
        piece = dict(item.get("outfit_piece") or {})
        before = clean_setting(piece.get(SETTING_KEY))
        setting = dict(before)
        if choice == AUTO:
            setting.pop(view, None)
        else:
            setting[view] = choice
        if setting == before:
            return setting
        piece[SETTING_KEY] = setting
        if inventory.update_item(item_id, {"outfit_piece": piece}) is None:
            raise ValueError(f"{str(item_id)[:80]!r} could not be saved")
    logger.info("Cut-out openings of the %s view of %s (%s): %s", view, item_id, character_name, choice)
    return setting


def recorded(record: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The ``opening`` a cut-out record was made with; None for a cut-out made before Ruling A60."""
    opening = (record or {}).get("opening")
    return opening if isinstance(opening, dict) else None


def wanted(record: Optional[Dict[str, Any]], choice: str) -> bool:
    """Whether ``choice`` applies the opening a cut-out ``record`` found (Auto and one was found)."""
    made = recorded(record) or {}
    return choice == AUTO and made.get("found") is True


def due(record: Optional[Dict[str, Any]], choice: str) -> bool:
    """Whether a cut-out ``record`` carries another opening than ``choice`` applies now (or was made under another
    rule ``VERSION``). A cut-out without an ``opening`` record (made before Ruling A60) is current; one whose
    opening search found nothing is current under either choice."""
    made = recorded(record)
    if made is None:
        return False
    if made.get("version") != VERSION:
        return True
    return bool(made.get("applied")) != wanted(record, choice)


def cutout_due(character_name: str, item_id: str, fsig: str, view: str, *,
               item: Optional[Dict[str, Any]] = None) -> bool:
    """``due`` for the accepted cut-out of ``view`` (False without one)."""
    from app.core.garment_store import accepted_image, garment_path, read_record
    path = garment_path(character_name, item_id, fsig, "image", step="cutout", view=view)
    if not accepted_image(path):
        return False
    if item is None:
        from app.models.inventory import get_item
        item = get_item(item_id) or {}
    return due(read_record(path.with_suffix(".json")), choice_of(item, view))


# --- Evidence -----------------------------------------------------------------------------------------------------

def vouched_by_worn_gate(worn_record: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The accepted worn view's own outline check, when it vouches for the framing (module docstring 1):
    ``{outside_drift_px, outside_xor, outside_xor_limit}`` or None."""
    from app.core.garment_from_worn import _final_gate
    gate = _final_gate(worn_record or {}) if (worn_record or {}).get("accepted") else {}
    drift, xor, limit = gate.get("outside_drift_px"), gate.get("outside_xor"), gate.get("outside_xor_limit")
    if not isinstance(drift, (int, float)) or not isinstance(xor, (int, float)) or not isinstance(limit, (int, float)):
        return None
    if gate.get("ok") is not True or drift > VOUCH_DRIFT_PX or xor > limit:
        return None
    return {"outside_drift_px": drift, "outside_xor": xor, "outside_xor_limit": limit}


def shown_body(base_rgb, figure, worn_rgb, *, vouch: Optional[Dict[str, Any]] = None
               ) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
    """``(shown, numbers)``: the base figure (shifted onto the worn view) outside the A46 piece mask — where the
    worn view shows the body as the base shows it; None with the reason in ``numbers["refused"]``. ``vouch``
    (``vouched_by_worn_gate``): a framing cost above the limit does not refuse."""
    from app.core import garment_from_worn as fw
    try:
        piece, _alpha, numbers = fw.piece_mask(base_rgb, figure, worn_rgb, framing_vouched=vouch is not None)
    except fw.FromWornRefused as e:
        return None, {"refused": str(e), **(e.numbers or {})}
    dx, dy = numbers["alignment"]["shift"]
    if vouch is not None and not numbers["alignment"].get("ok"):
        numbers["alignment"]["vouched_by"] = {"worn_gate": vouch}
    return fw._shifted(np.asarray(figure, bool), dx, dy) & ~piece, numbers


def neck_base_row(figure) -> Optional[int]:
    """The neck base of a figure mask (module docstring 3): the first row below the neck's narrowest row (in
    ``NECK_SEARCH`` of its height) where it is ``NECK_BASE_RATIO`` times as wide. None without a figure."""
    fig = np.asarray(figure, bool)
    widths = fig.sum(1)
    rows = np.nonzero(widths)[0]
    if not len(rows):
        return None
    top, bottom = int(rows[0]), int(rows[-1])
    height = bottom - top + 1
    lo = top + int(NECK_SEARCH[0] * height)
    hi = top + int(NECK_SEARCH[1] * height)
    if hi <= lo:
        return None
    neck = lo + int(np.argmin(widths[lo:hi]))
    wider = np.nonzero(widths[neck:] >= NECK_BASE_RATIO * max(int(widths[neck]), 1))[0]
    return int(neck + wider[0]) if len(wider) else None


def differs(worn_rgb, ghost_rgb) -> np.ndarray:
    """Where the worn view and the piece-only view (one frame) differ by more than ``garment_fit.OPEN_DIFF`` in some
    channel — the A51 fit's opening test (``garment_source.opening_masks``)."""
    from app.core import garment_fit as gf
    worn = np.asarray(worn_rgb)[..., :3].astype(np.int16)
    ghost = np.asarray(ghost_rgb)[..., :3].astype(np.int16)
    return np.abs(worn - ghost).max(2) > gf.OPEN_DIFF


def seed(shown, garment, differ, *, collar_row: Optional[int]) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
    """``(seed, components)`` in the ghost frame (module docstring 2 + 3): the enclosed components of shown body in
    the garment of which at least ``DIFFERS_MIN_SHARE`` lies on ``differ`` (``differs``), cut below ``collar_row``.
    ``components``: ``[{pixels, outline, differs, opening, bbox}]``."""
    from scipy import ndimage
    from app.core import garment_fit as gf
    gm = np.asarray(garment, bool)
    sh = np.asarray(shown, bool)
    dm = np.asarray(differ, bool)
    op = ndimage.binary_opening(sh & gm, iterations=gf.OPEN_ERODE_PX) & gm
    labels, n = ndimage.label(op)
    sizes = np.bincount(labels.ravel(), minlength=n + 1)
    keep = np.zeros(gm.shape, bool)
    comps: List[Dict[str, Any]] = []
    for c in range(1, n + 1):
        if sizes[c] < gf.OPEN_MIN_SHARE * gm.sum():
            continue
        comp = labels == c
        ring = ndimage.binary_dilation(comp, iterations=gf.OPEN_RING_PX) & ~op
        outline = float((ring & ~gm).sum()) / max(float(ring.sum()), 1.0)
        share = float((comp & dm).sum()) / max(float(sizes[c]), 1.0)
        ys, xs = np.nonzero(comp)
        opening = outline <= gf.OPEN_SHOWN_OUTLINE_MAX and share >= DIFFERS_MIN_SHARE
        comps.append({"pixels": int(sizes[c]), "outline": round(outline, 3), "differs": round(share, 3),
                      "opening": opening, "bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]})
        if opening:
            keep |= comp
    if collar_row is not None:
        keep[:max(collar_row, 0)] = False
    return keep, comps


# --- Into the cut-out ---------------------------------------------------------------------------------------------

def crop_of(record: Dict[str, Any]) -> Tuple[Tuple[int, int, int, int], int, int]:
    """``(crop box in the ghost frame, side, final side)`` of a cut-out record (``garment_images.cut_out``)."""
    x0, y0, x1, y1 = (int(v) for v in record["bbox"])
    side = int(record["side"])
    final = int((record.get("size") or [side])[0])
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    return (cx - side // 2, cy - side // 2, cx - side // 2 + side, cy - side // 2 + side), side, final


def to_cutout(mask, crop: Tuple[int, int, int, int], final: int) -> np.ndarray:
    """A ghost-frame mask in the cut-out frame (crop, then scaled to ``final``; outside the frame False)."""
    from PIL import Image
    m = np.asarray(mask, bool)
    h, w = m.shape
    side = crop[2] - crop[0]
    canvas = np.zeros((side, side), np.uint8)
    sx0, sy0, sx1, sy1 = max(crop[0], 0), max(crop[1], 0), min(crop[2], w), min(crop[3], h)
    if sx1 > sx0 and sy1 > sy0:
        canvas[sy0 - crop[1]:sy1 - crop[1], sx0 - crop[0]:sx1 - crop[0]] = m[sy0:sy1, sx0:sx1] * 255
    out = Image.fromarray(canvas).resize((final, final), Image.Resampling.BILINEAR)
    return np.asarray(out) >= 128


def _disc(radius: int) -> np.ndarray:
    r = np.arange(-radius, radius + 1)
    return (r[:, None] ** 2 + r[None, :] ** 2) <= radius * radius


def _borders(mask) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(rows, left, right)`` of a mask: per row that has pixels, its leftmost and rightmost column."""
    m = np.asarray(mask, bool)
    rows = np.nonzero(m.any(1))[0]
    left = np.array([np.argmax(m[y]) for y in rows], np.float64)
    right = np.array([m.shape[1] - 1 - np.argmax(m[y][::-1]) for y in rows], np.float64)
    return rows, left, right


def _smooth(x: np.ndarray, rows: int) -> np.ndarray:
    from scipy import ndimage
    if len(x) < 3:
        return x
    size = min(_odd(rows), len(x) if len(x) % 2 else len(x) - 1)
    out = ndimage.median_filter(x, size=max(size, 1), mode="nearest")
    return ndimage.uniform_filter1d(out, size=max(1, size // 3), mode="nearest")


def _extension(rows: np.ndarray, left: np.ndarray, right: np.ndarray, limit: int) -> List[Tuple[int, float, float]]:
    """Rows below a border pair that converges (module docstring 4): ``[(row, left, right)]`` down to the tip,
    at most ``limit`` rows; [] for a pair that does not converge."""
    k = max(5, len(rows) // 5)
    if len(rows) < 10:
        return []
    ys = rows[-k:].astype(np.float64)
    al, bl = np.polyfit(ys, left[-k:], 1)
    ar, br = np.polyfit(ys, right[-k:], 1)
    if al - ar <= 1e-3:
        return []
    tip = (br - bl) / (al - ar)
    out = []
    y = int(rows[-1]) + 1
    while y <= min(tip, rows[-1] + limit):
        xl, xr = al * y + bl, ar * y + br
        if xl >= xr:
            break
        out.append((y, xl, xr))
        y += 1
    return out


def snap(rgb, garment, seed_c, *, collar_c: Optional[int], scale: float, height: int
         ) -> Tuple[np.ndarray, Dict[str, Any]]:
    """The seed snapped onto the cut-out's own edges and smoothed (module docstring 4 + 5), cut-out frame:
    ``(hole, numbers {reach_px, snapped_rows, extended_rows, components})``. Per component of the seed and per row,
    its left border moves to the steepest step from the garment's shade into the inside's and its right border to
    the steepest step back (the inside darker or lighter than the garment around it, as measured) within
    ``SNAP_REACH``; the borders are smoothed and filled between, a converging pair runs on to its tip."""
    from scipy import ndimage
    rgb = np.asarray(rgb, np.float32)[..., :3]
    gm = np.asarray(garment, bool)
    s = np.asarray(seed_c, bool) & gm
    hole = np.zeros(gm.shape, bool)
    numbers: Dict[str, Any] = {"components": 0, "snapped_rows": 0, "extended_rows": 0}
    if not s.any():
        return hole, numbers
    lum = ndimage.gaussian_filter(rgb.mean(2), _px(EDGE_SIGMA_PX, height) * scale)
    # The step BETWEEN column x and x + 1 (a forward difference): a left border lies right of its step (x + 1, the
    # first pixel of the inside), a right border left of it (x) — never on the lapel's side.
    dx = np.zeros_like(lum)
    dx[:, :-1] = lum[:, 1:] - lum[:, :-1]
    cols = np.nonzero(gm.any(0))[0]
    width = int(cols.max() - cols.min() + 1)
    reach = max(1, int(round(SNAP_REACH * width)))
    limit = max(1, int(round(EXTEND_REACH * width)))
    border_rows = _px(BORDER_ROWS, height) * scale
    numbers["reach_px"] = reach
    labels, n = ndimage.label(s)
    w = gm.shape[1]
    for c in range(1, n + 1):
        rows, left, right = _borders(labels == c)
        if len(rows) < 3:
            hole |= labels == c
            continue
        numbers["components"] += 1
        comp = labels == c
        # Which way the step goes: the inside darker than the garment around it (a dark lining) or lighter.
        around = ndimage.binary_dilation(comp, iterations=reach) & ~comp & gm
        sign = (1.0 if not around.any() or float(np.median(lum[comp])) <= float(np.median(lum[around]))
                else -1.0)
        step = dx * sign          # > 0 where the luminance goes from the inside's shade toward the garment's
        new_l, new_r = left.copy(), right.copy()
        for i, y in enumerate(rows):
            lo, hi = int(max(left[i] - reach, 0)), int(min(left[i] + reach, w - 1))
            seg = step[y, lo:hi + 1]
            j = int(np.argmin(seg))
            if -seg[j] >= EDGE_STEP_MIN:
                new_l[i] = lo + j + 1
                numbers["snapped_rows"] += 1
            lo, hi = int(max(right[i] - reach, 0)), int(min(right[i] + reach, w - 1))
            seg = step[y, lo:hi + 1]
            j = int(np.argmax(seg))
            if seg[j] >= EDGE_STEP_MIN:
                new_r[i] = lo + j
                numbers["snapped_rows"] += 1
        new_l, new_r = _smooth(new_l, border_rows), _smooth(new_r, border_rows)
        spans = list(zip(rows.tolist(), new_l.tolist(), new_r.tolist()))
        more = _extension(rows, new_l, new_r, limit)
        numbers["extended_rows"] += len(more)
        for y, xl, xr in spans + more:
            if xr >= xl and 0 <= y < gm.shape[0]:
                hole[y, int(np.ceil(xl)):int(np.floor(xr)) + 1] = True
    radius = max(1, int(round(_px(SMOOTH_PX, height) * scale)))
    hole = ndimage.binary_closing(ndimage.binary_opening(hole, structure=_disc(radius)), structure=_disc(radius))
    hole = ndimage.binary_fill_holes(hole) & gm
    if collar_c is not None:
        hole[:max(collar_c, 0)] = False
    return hole, numbers


def feathered(hole, scale: float, height: int) -> np.ndarray:
    """The hole as a 0..1 cover with a soft edge of ``FEATHER_PX`` (fully 1 inside)."""
    from scipy import ndimage
    h = np.asarray(hole, bool)
    soft = ndimage.gaussian_filter(h.astype(np.float32), FEATHER_PX * height / 1536.0 * scale)
    return np.clip(np.maximum(soft, ndimage.binary_erosion(h, iterations=max(1, int(round(scale))))), 0, 1)


# --- Measures of the border --------------------------------------------------------------------------------------

def sawtooth(hole, *, rows: int = 31) -> Optional[Dict[str, float]]:
    """The saw-tooth of a hole's left and right border (px of its frame): per row the border's x minus its running
    median over ``rows`` rows — ``{mean, p95}`` of the absolute residual over both sides, the top and bottom 5 % of
    the rows left out. None for a hole of fewer than ``rows`` rows."""
    from scipy import ndimage
    ys, left, right = _borders(hole)
    if len(ys) < rows:
        return None
    trim = max(1, len(ys) // 20)
    left, right = left[trim:-trim], right[trim:-trim]
    res = np.abs(np.concatenate([left - ndimage.median_filter(left, size=rows, mode="nearest"),
                                 right - ndimage.median_filter(right, size=rows, mode="nearest")]))
    return {"mean": round(float(res.mean()), 2), "p95": round(float(np.percentile(res, 95)), 2)}


def lining_left(rgb, garment, hole, inside_lum: float, ring_px: int) -> int:
    """Garment pixels within ``ring_px`` beside the hole that have the inside's shade: nearer ``inside_lum`` (the
    seed's median luminance in the cut-out) than the median luminance of the garment 2–3 rings out (the lapel)."""
    from scipy import ndimage
    h = np.asarray(hole, bool)
    gm = np.asarray(garment, bool)
    if not h.any():
        return 0
    lum = np.asarray(rgb, np.float32)[..., :3].mean(2)
    near = ndimage.binary_dilation(h, iterations=ring_px)
    inner = near & ~h & gm
    outer = (ndimage.binary_dilation(h, iterations=3 * ring_px)
             & ~ndimage.binary_dilation(h, iterations=2 * ring_px) & gm)
    if not outer.any():
        return 0
    lapel = float(np.median(lum[outer]))
    return int((inner & (np.abs(lum - inside_lum) < np.abs(lum - lapel))).sum())


# --- The whole step ----------------------------------------------------------------------------------------------

def opening(worn_rgb, base_rgb, figure, ghost_rgb, ghost_mask, cut_rgb, cut_alpha, record: Dict[str, Any], *,
            vouch: Optional[Dict[str, Any]] = None) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
    """``(cover, numbers)`` of a cut-out (module docstring): ``worn_rgb`` / ``base_rgb`` / ``figure`` /
    ``ghost_rgb`` (the piece-only view) / ``ghost_mask`` in the ghost frame, ``cut_rgb`` / ``cut_alpha`` (0..255)
    the cut-out, ``record`` its crop
    (``crop_of``). ``cover`` (cut-out frame, 0..1: 1 = transparent) None when there is no opening; ``numbers``
    ``{found, reason?, px, share, components, collar_row, framing, snap, sawtooth_seed, sawtooth,
    lining_left_seed_px, lining_left_px}``."""
    worn = np.asarray(worn_rgb)
    height = worn.shape[0]
    numbers: Dict[str, Any] = {"found": False}
    if (np.asarray(base_rgb).shape != worn.shape or np.asarray(ghost_rgb)[..., :3].shape != worn.shape
            or np.asarray(ghost_mask).shape != worn.shape[:2]):
        numbers["reason"] = "the worn view, the base view and the piece-only view differ in size"
        return None, numbers
    shown, evidence = shown_body(base_rgb, figure, worn, vouch=vouch)
    numbers["framing"] = evidence.get("alignment")
    if shown is None:
        numbers["reason"] = f"no evidence: {evidence.get('refused')}"
        return None, numbers
    collar = neck_base_row(figure)
    if collar is not None and numbers["framing"]:
        collar += int(numbers["framing"]["shift"][1])
    numbers["collar_row"] = collar
    seed_g, comps = seed(shown, ghost_mask, differs(worn, ghost_rgb), collar_row=collar)
    numbers["components"] = comps
    if not seed_g.any():
        from app.core import garment_fit as gf
        enclosed = [c for c in comps if c["outline"] <= gf.OPEN_SHOWN_OUTLINE_MAX]
        if enclosed:
            # Ruling A81: enclosed, but the piece-only view shows the same there — the piece, not an opening.
            numbers["reason"] = (f"no opening: inside the piece the piece-only view shows what the worn view shows "
                                 f"(at most {max(c['differs'] for c in enclosed)} of it differs)")
        else:
            numbers["reason"] = ("no enclosed opening: the body the worn view shows inside the piece reaches its edge"
                                 if comps else "the worn view shows no body inside the piece")
        return None, numbers
    crop, side, final = crop_of(record)
    scale = final / float(side)
    seed_c = to_cutout(seed_g, crop, final)
    garment_c = np.asarray(cut_alpha) >= 128
    collar_c = int(round((collar - crop[1]) * scale)) if collar is not None else None
    hole, snapped = snap(cut_rgb, garment_c, seed_c, collar_c=collar_c, scale=scale, height=height)
    numbers["snap"] = snapped
    if not hole.any():
        numbers["reason"] = "the opening lies outside the cut-out"
        return None, numbers
    ring = max(1, int(round(_px(LINING_RING_PX, height) * scale)))
    seed_in = seed_c & garment_c
    inside = float(np.median(np.asarray(cut_rgb, np.float32)[..., :3].mean(2)[seed_in]))
    rows = _odd(31 * scale)
    numbers.update(
        found=True, px=int(hole.sum()), share=round(float(hole.sum()) / max(int(garment_c.sum()), 1), 4),
        sawtooth_seed=sawtooth(seed_in, rows=rows), sawtooth=sawtooth(hole, rows=rows),
        lining_left_seed_px=lining_left(cut_rgb, garment_c, seed_in, inside, ring),
        lining_left_px=lining_left(cut_rgb, garment_c, hole, inside, ring), ring_px=ring)
    return feathered(hole, scale, height), numbers


def _odd(value: float) -> int:
    n = max(3, int(round(value)))
    return n if n % 2 else n + 1


# --- In the cut-out step -----------------------------------------------------------------------------------------

#: The keys of ``opening``'s numbers the cut-out record keeps.
RECORD_KEYS = ("found", "reason", "px", "share", "components", "collar_row", "framing", "snap", "sawtooth_seed",
               "sawtooth", "lining_left_seed_px", "lining_left_px")


def _ghost_in_worn_frame(record: Dict[str, Any]) -> Optional[str]:
    """None when the accepted piece-only image lies in the worn view's frame (made from the worn view, or its
    registration was applied or negligible), else why not."""
    from app.core.garment_from_worn import RECORD_SOURCE
    if record.get("source") == RECORD_SOURCE:
        return None
    gates = record.get("gates") if isinstance(record.get("gates"), dict) else {}
    ordinals = ("first", "second", "third", "fourth", "fifth")
    try:
        attempt = int(record.get("attempt") or 1)
    except (TypeError, ValueError):
        attempt = 1
    gate = gates.get(ordinals[min(max(attempt, 1), len(ordinals)) - 1]) or gates.get("first") or {}
    reg = gate.get("registration") if isinstance(gate.get("registration"), dict) else None
    if reg is None or reg.get("applied") or reg.get("negligible"):
        return None
    return "the piece-only view was not moved onto the worn view (its registration is beyond the caps)"


def for_cutout(character_name: str, item_id: str, fsig: str, view: str, *, ghost_mask, colours, alpha,
               record: Dict[str, Any], item: Optional[Dict[str, Any]] = None):
    """The cut-out's alpha (PIL L, cut-out frame) with the opening cut when the setting applies it, and the
    ``opening`` record (``{version, choice, applied, found, …}``; module docstring). ``ghost_mask`` the piece-only
    view's mask in its own frame, ``colours`` / ``alpha`` the cut-out, ``record`` its crop (``crop_of``). The search
    runs under Off too (the record says what Auto would cut). A failure is recorded, never raised: the cut-out
    stays as it is."""
    from PIL import Image
    from app.core import garment_from_worn as fw, garment_images, garment_source
    from app.core.garment_store import accepted_image, garment_path, read_record
    from app.core.model_refs import get_model_refs_dir
    if item is None:
        from app.models.inventory import get_item
        item = get_item(item_id) or {}
    choice = choice_of(item, view)
    out: Dict[str, Any] = {"version": VERSION, "choice": choice, "applied": False, "found": False}
    worn = garment_path(character_name, item_id, fsig, "image", step="worn", view=view)
    ghost = garment_path(character_name, item_id, fsig, "image", step="ghost", view=view)
    copy = garment_source.base_copy(character_name, item_id, fsig, view)
    if not accepted_image(worn):
        out["reason"] = "no accepted worn view"
        return alpha, out
    if not copy.is_file():
        out["reason"] = "no base copy of the image group (the base view the worn view was edited from)"
        return alpha, out
    frame = _ghost_in_worn_frame(read_record(ghost.with_suffix(".json")))
    if frame:
        out["reason"] = frame
        return alpha, out
    try:
        base_rgb, figure, _from_alpha = fw._base_arrays(copy, get_model_refs_dir(character_name))
        worn_rgb = garment_images._rgb(worn)
        ghost_rgb = garment_images._rgb(ghost)
        vouch = vouched_by_worn_gate(read_record(worn.with_suffix(".json")))
        cut_a = np.asarray(alpha, np.float32)
        cover, numbers = opening(worn_rgb, base_rgb, figure, ghost_rgb, ghost_mask, np.asarray(colours.convert("RGB")),
                                 cut_a, record, vouch=vouch)
    except Exception as e:  # noqa: BLE001 — a later refinement never discards the cut-out (it stays as made)
        logger.warning("Cut-out %s %s %s: the opening search failed: %s", character_name, item_id, view, e)
        out["reason"] = f"the opening search failed: {e}"
        return alpha, out
    out.update({k: numbers[k] for k in RECORD_KEYS if k in numbers})
    if cover is None or choice != AUTO:
        return alpha, out
    out["applied"] = True
    logger.info("Cut-out %s %s %s: opening of %s px (%s of the garment) cut", character_name, item_id, view,
                numbers.get("px"), numbers.get("share"))
    return Image.fromarray(np.clip(np.round(cut_a * (1.0 - cover)), 0, 255).astype(np.uint8), "L"), out
