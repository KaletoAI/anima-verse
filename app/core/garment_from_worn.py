"""Piece-only views made from the worn view (Ruling A46, 2026-11-14).

The clothing chain makes its piece-only view (``ghost``) of each view by an image EDIT of the worn view
(``garment_images.run_edit_step``: "the person removed, the piece alone"). For a close-fitting piece the edit
model has nothing to invent — the worn view shows all of it — and yet it does: Glut's scale top (strapless
cups, a back band with a clasp, crossed chains) got two shoulder straps on its accepted ghost front, its ghost
back showed the cups' insides above the band, and a re-run of the back drew hanging straps and then the front
cups.

"From the worn view" makes the view without any job: the worn view MINUS the item's own base view (the base
copy of the image group, ``garment_source.base_copy`` — the very base the worn view was edited from, at the
same framing; without the copy the base view of the current base signature, which the run checks to be the
same image) gives the piece's mask, and the worn pixels inside it are placed on the neutral grey every ghost
is rendered on (``model_refs.VIEW_REFERENCE_BACKGROUND``). The result is a drop-in replacement of
``ghost_<view>``: the same size and frame, gated by the ghost gate like a rendered one, cut out by the
unchanged cut-out step (whose routed upscale stays as it is). 0 hub jobs for the view.

The mask (``piece_mask``; every pixel number at 1536 px, scaled with the image height):

- FRAMING: the worn view must be the base view's size; the integer shift (±``ALIGN_SEARCH_PX``) with the
  lowest trimmed mean |ΔRGB| between the two (the ``ALIGN_TRIM`` share of the pixels that agree best — the
  piece left out) registers the base onto the worn view. A best cost above ``ALIGN_COST_MAX`` means another
  framing: refused, nothing is made.
- SHADE NORMALISATION: the edit model tints the bare skin (Glut's front: ×0.98 / 0.93 / 0.86 per channel);
  the per-channel median ratio worn / base over the base figure's pixels that already agree within
  ``GAIN_AGREE`` takes that out (clipped to ``GAIN_RANGE``). Outside the figure the reference is the worn
  view's own background (the median of its border).
- DIFFERENCE: per pixel the smallest mean |ΔRGB| to the normalised reference within ``MATCH_RADIUS_PX``
  (a disc) — the skin a push-up moved a few pixels, or a 1 px outline drift, finds itself there; the
  piece does not. Garment = above ``garment_gates.GARMENT_DRGB`` (20, the worn region's own threshold).
- SKIN: a pixel of that mask is skin when it is at least as near the skin (``garment_gates.skin_colour``
  normalised the same way) as the piece (``garment_gates.piece_colour``) in its own light
  (``garment_gates.shade_distance``), within ``SKIN_SHADE`` of it, and at least ``SKIN_LUM`` of the skin's
  brightness (a dark chain has the skin's hue in shadow, never its brightness). Only AREAS of such pixels go
  (opened ``SKIN_OPEN``, grown ``SKIN_GROW``: the deepened cleavage between Glut's cups, 1 061 px) — a
  lit fleck on a chain is no area. A piece whose own colour is the skin's (within ``garment_gates.SKIN_DRGB``
  of it and within ``SKIN_SHADE`` in the same light) keeps everything: it cannot be told from the skin.
- MORPHOLOGY: opened ``OPEN_PX``, closed ``CLOSE_PX``; the parts of at least ``PART_SHARE`` of the largest
  one are kept (a re-shaded patch elsewhere is no piece); holes below ``HOLE_MAX`` of the figure's area are
  filled (specks of the piece's own highlights). Before the skin step, a pixel that differs from the base
  pixel at its own place and lies in the mask closed by ``FILL_PX`` joins it: the piece's own shadow can
  match a shaded skin pixel within the disc (the dark lower rim of Glut's right cup against the base's
  shadow under the breast, 1 210 px) and would leave a bite in the outline.
- EDGE: feathered INWARD (Gaussian ``FEATHER_PX`` from ``EDGE_IN_PX`` inside the mask, nothing outside it):
  the rim pixels mix the piece with the skin and would give the cut-out a skin-coloured fringe.

Measured on copies of Glut's scale top (fsig 4ef4525e4ac1, 2026-11-14; ``~/claude-out/a46``): front 20 869 px
= 0.0662 of the figure's 315 176 (shift 0/0 at cost 4.0, gain 0.98 / 0.93 / 0.86, 1 210 px rim filled, 1 061 px
of skin areas taken out — the deepened cleavage —, 7 holes filled), back 10 211 px = 0.0322 (the composite back:
the base back pixel for pixel outside the piece, cost 0.0, gain 1.0). The back shows band, clasp and chains, the
front cups, centre gore and chains — no strap, no cup inside; both pass the ghost gate (w_ratio 0.978 / 0.99,
skin_left 0, outside 0, added_reach 0; the front's hem 0.2944 against the worn 0.2958).

The SETTING (``SETTING_KEY`` of the item's ``outfit_piece``, ``{view: choice}``): per piece and view "Auto"
(the default, no key stored), "Generated" (the edit, as before) or "From the worn view". ``resolve`` turns it
into the source a view is made from and the reason in plain words:

- Generated / From the worn view: as chosen.
- Auto, a LOOSE piece (a slot of ``LOOSE_SLOTS``: the body hides parts of it in the worn view — the inside of
  a jacket at the neck, the sleeves, the hem — which only the generated view draws): Generated.
- Auto, a close-fitting piece: Generated until the generated view of that view is refused — its stored
  attempts all refused after the accepted image (or without one), or the accepted generated image refused
  by the current gate for a part it adds (``added_refused``, ``garment_gates.added_parts``) — then From the
  worn view. A view Auto made from the worn view stays so (the reason is in its record) until the user picks
  another choice or the image group changes; a run whose generated attempts are refused under Auto makes
  the view from the worn view in the same run (``garment_images.run_edit_step``).

Saving a choice runs nothing (``set_choice``). A view whose accepted image was made from another source
than ``resolve`` names now is DUE (``source_due``): the chain makes it again (0 jobs from the worn view), its
cut-out, the mesh and the fit after it — the Wardrobe's step grid states it beside the select.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.log import get_logger

logger = get_logger("garment_from_worn")

#: The step whose views can come from the worn view, and the step they come from.
STEP = "ghost"
WORN_STEP = "worn"
#: The item's ``outfit_piece`` key of the setting: ``{view: choice}``; a missing view is Auto.
SETTING_KEY = "piece_views"
AUTO, GENERATED, WORN = "auto", "generated", "worn"
CHOICES: Tuple[str, ...] = (AUTO, GENERATED, WORN)
#: The ``source`` of a ghost record made here (a rendered ghost has none).
RECORD_SOURCE = "worn_minus_base"
#: Slots of a piece the body hides parts of in the worn view: Auto keeps the generated view for it.
LOOSE_SLOTS = frozenset({"top", "outer", "bottom"})

# --- Mask (every pixel number at 1536 px; ``garment_gates._iterations`` scales it) --------------------------
ALIGN_SEARCH_PX = 3          # ± px searched for the base's shift onto the worn view
ALIGN_TRIM = 0.9             # share of the pixels (the best agreeing) the framing cost is the mean of
ALIGN_COST_MAX = 12.0        # mean |ΔRGB| of those pixels above which the two views are not one framing
GAIN_AGREE = 25.0            # a figure pixel within this of the base takes part in the shade normalisation
GAIN_RANGE = (0.7, 1.4)      # per-channel gain clip
MATCH_RADIUS_PX = 5          # the disc a worn pixel looks for its base pixel in
FILL_PX = 8                  # closing radius whose pixels that differ from the base in place join the piece
SKIN_SHADE = 12.0            # shade distance within which a pixel has the skin's hue
SKIN_LUM = 0.55              # ... and at least this share of the skin's brightness
SKIN_OPEN = 2                # skin pixels form an area after this opening (px @1536)
SKIN_GROW = 3                # ... which is grown by this before it is taken out (its shaded rim)
OPEN_PX = 1                  # opening of the piece mask (px @1536)
CLOSE_PX = 2                 # closing of the piece mask (px @1536)
PART_SHARE = 0.2             # a part is kept from this share of the largest part's area
HOLE_MAX = 0.001             # holes below this share of the figure's area are filled
FEATHER_PX = 1.0             # Gaussian sigma of the edge (px @1536)
EDGE_IN_PX = 1               # the feather starts this far inside the mask (its rim mixes piece and skin)
#: A piece below this share of the figure is no piece (``garment_gates.GARMENT_MIN``'s value).
PIECE_MIN = 0.002


class FromWornRefused(ValueError):
    """The worn view and the base view cannot give the piece (another framing, no piece found)."""

    def __init__(self, message: str, numbers: Dict[str, Any]):
        super().__init__(message)
        self.numbers = numbers


def _px(base: float, height: int) -> int:
    from app.core.garment_gates import _iterations
    return _iterations(int(round(base)), height) if base >= 1 else 1


def _shifted(array: np.ndarray, dx: int, dy: int) -> np.ndarray:
    """``array`` moved by (dx, dy) px, the edge repeated into the gap."""
    if not dx and not dy:
        return array
    h, w = array.shape[:2]
    pad = max(abs(dx), abs(dy))
    width = ((pad, pad), (pad, pad)) + ((0, 0),) * (array.ndim - 2)
    padded = np.pad(array, width, mode="edge")
    return padded[pad - dy:pad - dy + h, pad - dx:pad - dx + w]


def _framing_cost(worn: np.ndarray, base: np.ndarray) -> float:
    d = np.abs(worn - base).mean(2).ravel()
    k = max(int(len(d) * ALIGN_TRIM), 1)
    return float(np.partition(d, k - 1)[:k].mean())


def align(worn_rgb, base_rgb) -> Dict[str, Any]:
    """The integer shift of the base onto the worn view (±``ALIGN_SEARCH_PX``) with the lowest framing cost
    (``_framing_cost``; no shift on a tie): ``{shift: [dx, dy], cost, cost_unshifted, ok}``."""
    worn = np.asarray(worn_rgb, dtype=np.float32)[..., :3]
    base = np.asarray(base_rgb, dtype=np.float32)[..., :3]
    reach = _px(ALIGN_SEARCH_PX, worn.shape[0])
    step = max(1, worn.shape[0] // 768)   # the cost on every second row/column of a big image
    w_small = worn[::step, ::step]
    unshifted = _framing_cost(w_small, base[::step, ::step])
    # No shift unless one is better: a flat figure costs the same under several shifts.
    best = (unshifted, 0, 0)
    for dy in range(-reach, reach + 1):
        for dx in range(-reach, reach + 1):
            if dx or dy:
                cost = _framing_cost(w_small, _shifted(base, dx, dy)[::step, ::step])
                if cost < best[0] - 1e-6:
                    best = (cost, dx, dy)
    cost, dx, dy = best
    return {"shift": [int(dx), int(dy)], "cost": round(cost, 3), "cost_unshifted": round(unshifted, 3),
            "ok": cost <= ALIGN_COST_MAX}


def _border_colour(rgb: np.ndarray) -> np.ndarray:
    edge = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    return np.median(edge, 0)


def _disc_mask(radius: int) -> np.ndarray:
    r = np.arange(-radius, radius + 1)
    return (r[:, None] ** 2 + r[None, :] ** 2) <= radius * radius


def _disc(radius: int) -> List[Tuple[int, int]]:
    return [(dx, dy) for dy in range(-radius, radius + 1) for dx in range(-radius, radius + 1)
            if dx * dx + dy * dy <= radius * radius]


def piece_mask(base_rgb, base_mask, worn_rgb, *,
               framing_vouched: bool = False) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    """``(mask, alpha, numbers)`` of the piece in a worn view (module docstring): ``base_rgb`` the base view
    flattened on the neutral grey, ``base_mask`` its figure (bool), ``worn_rgb`` the worn view — same shape.
    ``alpha`` = the mask feathered (float 0..1). ``FromWornRefused`` for another framing or no piece.
    ``framing_vouched`` (Ruling A60, ``garment_openings.vouched_by_worn_gate``): another check has measured the
    framing (the worn gate's outline outside the garment), so a framing cost above ``ALIGN_COST_MAX`` does not
    refuse — that cost grows with the piece's own area (``garment_openings`` docstring 1)."""
    from scipy import ndimage
    from app.core import garment_gates as gg
    base = np.asarray(base_rgb, dtype=np.float32)[..., :3]
    worn = np.asarray(worn_rgb, dtype=np.float32)[..., :3]
    figure = np.asarray(base_mask, dtype=bool)
    if base.shape != worn.shape or figure.shape != worn.shape[:2]:
        raise FromWornRefused(f"the worn view ({worn.shape[1]}×{worn.shape[0]}) and the base view "
                              f"({base.shape[1]}×{base.shape[0]}) differ in size", {})
    height = worn.shape[0]
    numbers: Dict[str, Any] = {"size": [int(worn.shape[1]), int(height)], "figure_px": int(figure.sum())}
    if not figure.any():
        raise FromWornRefused("no figure in the base view", numbers)
    framing = align(worn, base)
    numbers["alignment"] = framing
    if not framing["ok"] and not framing_vouched:
        raise FromWornRefused(f"the worn view is not in the base view's framing: a mean difference of "
                              f"{framing['cost']} > {ALIGN_COST_MAX} at the best shift {framing['shift']}", numbers)
    dx, dy = framing["shift"]
    base, figure = _shifted(base, dx, dy), _shifted(figure, dx, dy)
    # Shade normalisation: the edit's tint of the bare figure.
    agree = figure & (np.abs(worn - base).mean(2) < GAIN_AGREE)
    if agree.sum() < 100:
        agree = figure
    gain = np.clip(np.median(worn[agree], 0) / np.maximum(np.median(base[agree], 0), 1.0), *GAIN_RANGE)
    numbers["gain"] = [round(float(g), 4) for g in gain]
    reference = np.where(figure[..., None], base * gain, _border_colour(worn)[None, None, :])
    # The smallest difference within the disc: a pixel the edit moved a little finds itself.
    radius = _px(MATCH_RADIUS_PX, height)
    nearest = np.full(worn.shape[:2], np.inf, dtype=np.float32)
    for ox, oy in _disc(radius):
        nearest = np.minimum(nearest, np.abs(worn - _shifted(reference, ox, oy)).mean(2))
    mask = nearest > gg.GARMENT_DRGB
    numbers["raw_px"] = int(mask.sum())
    # The piece's own shadow can match a shaded skin pixel nearby (a cup's dark lower rim against the base's
    # shadow under the breast) and leave a bite in the outline: a pixel that differs from the base pixel at its
    # own place AND lies in the mask closed by ``FILL_PX`` is the piece.
    direct = np.abs(worn - reference).mean(2) > gg.GARMENT_DRGB
    closed = ndimage.binary_closing(mask, structure=_disc_mask(_px(FILL_PX, height)))
    filled_in = closed & direct & ~mask
    numbers["rim_filled_px"] = int(filled_in.sum())
    mask |= filled_in
    # Skin areas the edit re-shaded (a deepened cleavage): skin hue, skin brightness, a solid area.
    skin = gg.skin_colour(base, figure)
    piece = gg.piece_colour(worn, mask)
    numbers["skin_removed_px"] = 0
    if skin is not None and piece is not None:
        skin = skin * gain
        to_skin = gg.shade_distance(worn, skin)
        if (float(np.abs(piece - skin).mean()) <= gg.SKIN_DRGB
                and float(gg.shade_distance(piece[None, None, :], skin)[0, 0]) <= SKIN_SHADE):
            numbers["skin_removed"] = "skipped: the piece's own colour is skin-like"
        else:
            skinlike = (mask & (to_skin <= gg.shade_distance(worn, piece)) & (to_skin <= SKIN_SHADE)
                        & (worn.mean(2) >= SKIN_LUM * float(skin.mean())))
            area = ndimage.binary_opening(skinlike, iterations=_px(SKIN_OPEN, height))
            area = ndimage.binary_dilation(area, iterations=_px(SKIN_GROW, height)) if area.any() else area
            numbers["skin_removed_px"] = int((mask & area).sum())
            mask &= ~area
        numbers["skin"] = [round(float(c), 1) for c in skin]
        numbers["piece_colour"] = [round(float(c), 1) for c in piece]
    mask = ndimage.binary_opening(mask, iterations=_px(OPEN_PX, height))
    mask = ndimage.binary_closing(mask, iterations=_px(CLOSE_PX, height))
    labels, count = ndimage.label(mask)
    if not count:
        raise FromWornRefused("no piece found: the worn view does not differ from the base view", numbers)
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    keep = np.nonzero(sizes >= PART_SHARE * sizes.max())[0]
    mask = np.isin(labels, keep)
    numbers["parts"] = int(len(keep))
    numbers["parts_dropped"] = int(count - len(keep))
    holes = ndimage.binary_fill_holes(mask) & ~mask
    hole_labels, hole_count = ndimage.label(holes)
    filled = 0
    if hole_count:
        hole_sizes = np.bincount(hole_labels.ravel())
        hole_sizes[0] = 0
        small = np.nonzero((hole_sizes > 0) & (hole_sizes < HOLE_MAX * numbers["figure_px"]))[0]
        mask |= np.isin(hole_labels, small)
        filled = int(len(small))
    numbers["holes_filled"] = filled
    share = float(mask.sum()) / max(numbers["figure_px"], 1)
    numbers["piece_px"] = int(mask.sum())
    numbers["piece_share"] = round(share, 5)
    ys, xs = np.nonzero(mask)
    numbers["bbox"] = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if len(ys) else None
    if share < PIECE_MIN:
        raise FromWornRefused(f"no piece found: {round(share, 5)} of the figure < {PIECE_MIN}", numbers)
    # The edge is feathered INWARD: the outermost pixels of the mask mix the piece with the skin (a shadow the
    # piece casts, a blend at its rim), so the blur starts one pixel in and nothing outside the mask is shown.
    sigma = FEATHER_PX * height / 1536.0
    inner = ndimage.binary_erosion(mask, iterations=_px(EDGE_IN_PX, height))
    alpha = (np.clip(ndimage.gaussian_filter(inner.astype(np.float32), sigma), 0.0, 1.0) if sigma > 0
             else inner.astype(np.float32))
    alpha = np.where(mask, alpha, 0.0)
    return mask, alpha, numbers


def compose(worn_rgb, alpha, background=None) -> np.ndarray:
    """The worn pixels under ``alpha`` on ``background`` (the neutral grey of every ghost) as uint8 RGB."""
    from app.core.model_refs import VIEW_REFERENCE_BACKGROUND
    bg = np.asarray(VIEW_REFERENCE_BACKGROUND if background is None else background, dtype=np.float32)
    a = np.asarray(alpha, dtype=np.float32)[..., None]
    out = np.asarray(worn_rgb, dtype=np.float32)[..., :3] * a + bg[None, None, :] * (1.0 - a)
    return np.clip(np.round(out), 0, 255).astype(np.uint8)


# --- The setting ---------------------------------------------------------------------------------------------

def clean_setting(raw: Any) -> Dict[str, str]:
    """``{view: choice}`` with the known views and a choice other than Auto (Auto = no key)."""
    from app.core.garment_store import GARMENT_VIEWS
    if not isinstance(raw, dict):
        return {}
    return {v: str(raw[v]) for v in GARMENT_VIEWS if str(raw.get(v) or "") in (GENERATED, WORN)}


def choice_of(item: Optional[Dict[str, Any]], view: str) -> str:
    piece = (item or {}).get("outfit_piece") if isinstance((item or {}).get("outfit_piece"), dict) else {}
    return clean_setting(piece.get(SETTING_KEY)).get(view, AUTO)


def is_loose(item: Optional[Dict[str, Any]]) -> bool:
    piece = (item or {}).get("outfit_piece") if isinstance((item or {}).get("outfit_piece"), dict) else {}
    slots = piece.get("slots") if isinstance(piece.get("slots"), (list, tuple)) else []
    return bool(LOOSE_SLOTS & {str(s) for s in slots})


def set_choice(character_name: str, item_id: str, view: str, choice: str) -> Dict[str, str]:
    """Store the choice of ``view`` (``auto`` drops the key) on the item in ONE read-modify-write under
    ``keyed_lock("garment_item", character_name)``; runs nothing. The stored setting. ValueError for a bad
    view or choice or an item that is no outfit piece."""
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
        setting = clean_setting(piece.get(SETTING_KEY))
        if choice == AUTO:
            setting.pop(view, None)
        else:
            setting[view] = choice
        if setting == clean_setting((item.get("outfit_piece") or {}).get(SETTING_KEY)):
            return setting
        piece[SETTING_KEY] = setting
        if inventory.update_item(item_id, {"outfit_piece": piece}) is None:
            raise ValueError(f"{str(item_id)[:80]!r} could not be saved")
    logger.info("Piece-only %s view of %s (%s): %s", view, item_id, character_name, choice)
    return setting


# --- Which source a view is made from --------------------------------------------------------------------------

def _record(path: Path) -> Dict[str, Any]:
    from app.core.garment_store import read_record
    return read_record(path.with_suffix(".json")) if path.is_file() else {}


def made_from(record: Dict[str, Any]) -> str:
    """The source an accepted ghost record was made from: ``worn`` or ``generated``."""
    return WORN if record.get("source") == RECORD_SOURCE else GENERATED


def _final_gate(record: Dict[str, Any]) -> Dict[str, Any]:
    from app.core.garment_images import _ORDINALS
    gates = record.get("gates") if isinstance(record.get("gates"), dict) else {}
    try:
        return gates.get(_ORDINALS[int(record.get("attempt") or 1) - 1]) or {}
    except (IndexError, TypeError, ValueError):
        return {}


def generated_refusal(character_name: str, item_id: str, fsig: str, view: str) -> Optional[Tuple[str, str]]:
    """Why the GENERATED view of ``view`` is refused — ``(why, detail)``: ``"added"`` when the accepted
    generated image's current gate record refuses a part it adds (``added_refused``; detail = its reach in
    figure heights), ``"refused"`` when its stored attempts are all refused and newer than an accepted
    generated image (or there is none; detail = the newest attempt's first gate reason) — or None. Read from
    the records only."""
    from app.core.garment_images import ATTEMPTS
    from app.core.garment_store import accepted_image, garment_path
    final = garment_path(character_name, item_id, fsig, "image", step=STEP, view=view)
    record = _record(final)
    generated_final = accepted_image(final) and made_from(record) == GENERATED
    if generated_final:
        gate = _final_gate(record)
        if gate.get("added_refused") is True:
            reach = gate.get("added_reach")
            return "added", (f"{reach}" if reach is not None else "")
    attempts = []
    for n in range(1, ATTEMPTS + 1):
        path = garment_path(character_name, item_id, fsig, "image", step=STEP, view=view, attempt=n)
        if path.is_file():
            sidecar = _record(path)
            gate = sidecar.get("gate") if isinstance(sidecar.get("gate"), dict) else None
            if gate is not None:
                attempts.append((str(sidecar.get("created_at") or ""), gate))
    if not attempts or any(g.get("ok") is True for _at, g in attempts):
        return None
    newest = max(at for at, _g in attempts)
    if generated_final and str(record.get("created_at") or "") >= newest:
        return None
    first = next((r for _at, g in sorted(attempts, reverse=True) for r in (g.get("reasons") or [])), "")
    return "refused", str(first)


# The reasons of ``resolve`` (``why``) in plain words — the Wardrobe says them through ``t()``; ``detail``
# (a gate reason, a reach) is appended as it is.
REASONS = {
    "set_generated": "Generated: you chose the image edit (the body removed by the edit model)",
    "set_worn": "From the worn view: you chose it (the worn view minus the body, no hub job)",
    "loose": "Auto → Generated: a loose piece — the body hides parts of it in the worn view (the inside at "
             "the neck, sleeves or hem), only the edit draws them",
    "by_hand": "Auto → Generated: you took this attempt with “Use this”",
    "added": "Auto → From the worn view: the generated view adds a part the worn piece does not have",
    "refused": "Auto → From the worn view: the generated view was refused",
    "passes": "Auto → Generated: a close-fitting piece — the edit is used while it passes its gate; refused, "
              "the view is made from the worn view",
}


def _said(choice: str, source: str, auto: bool, why: str, detail: str = "") -> Dict[str, Any]:
    text = REASONS[why] + (f" ({detail})" if detail and why == "added" else f": {detail}" if detail else "")
    return {"choice": choice, "source": source, "auto": auto, "why": why, "detail": detail, "reason": text}


def resolve(character_name: str, item_id: str, fsig: str, view: str, *,
            item: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """``{choice, source, auto, why, detail, reason}`` of ``view`` (module docstring): ``choice`` the setting,
    ``source`` what the view is made from (``generated`` / ``worn``), ``why`` the reason's key in ``REASONS``
    with its ``detail`` (a gate reason, a reach; "" without one), ``reason`` both in plain English (logs,
    records), ``auto`` True when a refused generated view falls back to the worn view in the same run (Auto
    on a close-fitting piece)."""
    from app.core.garment_store import accepted_image, garment_path
    if item is None:
        from app.models.inventory import get_item
        item = get_item(item_id) or {}
    choice = choice_of(item, view)
    if choice == GENERATED:
        return _said(choice, GENERATED, False, "set_generated")
    if choice == WORN:
        return _said(choice, WORN, False, "set_worn")
    if is_loose(item):
        return _said(choice, GENERATED, False, "loose")
    final = garment_path(character_name, item_id, fsig, "image", step=STEP, view=view)
    record = _record(final)
    made = record.get("choice") if isinstance(record.get("choice"), dict) else {}
    if accepted_image(final) and made_from(record) == WORN and made.get("auto"):
        # Sticky: an Auto view made from the worn view keeps that source (and the reason it was made for).
        why = str(made.get("why") or "")
        return _said(choice, WORN, True, why if why in ("added", "refused") else "refused",
                     str(made.get("detail") or ""))
    if accepted_image(final) and isinstance(record.get("used_by_hand"), dict):
        return _said(choice, GENERATED, False, "by_hand")
    refusal = generated_refusal(character_name, item_id, fsig, view)
    if refusal:
        return _said(choice, WORN, True, *refusal)
    return _said(choice, GENERATED, True, "passes")


def source_due(character_name: str, item_id: str, fsig: str, view: str, *,
               item: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the ACCEPTED ghost of ``view`` was made from another source than ``resolve`` names now — the
    view is due (made again, then its cut-out, the mesh and the fit). False without an accepted ghost."""
    from app.core.garment_store import accepted_image, garment_path
    final = garment_path(character_name, item_id, fsig, "image", step=STEP, view=view)
    if not accepted_image(final):
        return False
    return made_from(_record(final)) != resolve(character_name, item_id, fsig, view, item=item)["source"]


# --- Making the view -------------------------------------------------------------------------------------------

def _base_arrays(base: Path, refs_dir: Path) -> Tuple[np.ndarray, np.ndarray, bool]:
    """``(flat rgb, figure mask, from alpha)`` of a base view: its alpha when it has one, else the matte of
    the flattened image (``garment_images._mask``)."""
    from PIL import Image
    from app.core.model_refs import VIEW_REFERENCE_BACKGROUND
    with Image.open(base) as im:
        rgba = im.convert("RGBA")
        has_alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
    flat = Image.new("RGBA", rgba.size, VIEW_REFERENCE_BACKGROUND + (255,))
    flat.alpha_composite(rgba)
    rgb = np.asarray(flat.convert("RGB"))
    if has_alpha:
        return rgb, np.asarray(rgba)[..., 3] >= 128, True
    from app.core import garment_images
    from app.core.model_refs import neutral_view_reference
    with neutral_view_reference(base, refs_dir) as flat_path:
        return rgb, garment_images._mask(flat_path, rgba.size), False


def make_view(character_name: str, item_id: str, fsig: str, view: str, *, base: Path, refs_dir: Path,
              choice: Dict[str, Any],
              gate_record: Any, pair_check: Any = None) -> Path:
    """Make ``ghost_<view>`` from the worn view (module docstring) and publish it as the view's accepted
    image: ``base`` the base view the step reads (the group's base copy is preferred when it is on disk),
    ``gate_record(path)`` the step's gate of an image file (``garment_images.run_edit_step``), ``pair_check``
    the chain's check of a front against the accepted back. Its record: ``source`` = ``RECORD_SOURCE``,
    ``from_worn`` the mask numbers, ``choice`` the setting and reason, ``gates.first`` the gate.
    ``garment_images.GateRefused`` when the mask cannot be made or the gate refuses it (nothing published);
    ``base_body.MissingInput`` without an accepted worn view."""
    import os
    import threading
    from PIL import Image
    from app.core import base_body, garment_images, garment_source
    from app.core.garment_store import accepted_image, garment_path, write_record
    from app.core.timeutils import utc_now_iso
    worn = garment_path(character_name, item_id, fsig, "image", step=WORN_STEP, view=view)
    if not accepted_image(worn):
        raise base_body.MissingInput(f"The worn {view} image is missing — run that step first")
    copy = garment_source.base_copy(character_name, item_id, fsig, view)
    base_file = copy if copy.is_file() else Path(base)
    base_rgb, figure, from_alpha = _base_arrays(base_file, refs_dir)
    size = (base_rgb.shape[1], base_rgb.shape[0])
    worn_rgb = garment_images._rgb(worn)
    if (worn_rgb.shape[1], worn_rgb.shape[0]) != size:
        record = {"view": view, "ok": False, "source": RECORD_SOURCE,
                  "reasons": [f"the worn view ({worn_rgb.shape[1]}×{worn_rgb.shape[0]}) is not the base view's "
                              f"size ({size[0]}×{size[1]}) — another framing"]}
        raise garment_images.GateRefused(STEP, view, [record])
    try:
        _mask, alpha, numbers = piece_mask(base_rgb, figure, worn_rgb)
    except FromWornRefused as e:
        raise garment_images.GateRefused(STEP, view, [{"view": view, "ok": False, "source": RECORD_SOURCE,
                                                       "from_worn": e.numbers, "reasons": [str(e)]}])
    numbers.update(base=base_file.name, base_copy=copy.is_file(), figure_from_alpha=from_alpha)
    final = garment_path(character_name, item_id, fsig, "image", step=STEP, view=view)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_name(f".{final.stem}.{os.getpid()}.{threading.get_ident()}.fromworn.png")
    try:
        Image.fromarray(compose(worn_rgb, alpha)).save(tmp, format="PNG")
        record = gate_record(tmp)
        record = garment_images._with_pair(record, pair_check)
        record.update(attempt=0, source=RECORD_SOURCE)
        if not record.get("ok"):
            logger.info("Garment %s ghost %s from the worn view refused: %s", character_name, view,
                        record.get("reasons"))
            raise garment_images.GateRefused(STEP, view, [{**record, "from_worn": numbers}])
        os.replace(tmp, final)
    finally:
        tmp.unlink(missing_ok=True)
    write_record(final.with_suffix(".json"), {
        "accepted": True, "attempt": 0, "source": RECORD_SOURCE, "from_worn": numbers,
        "choice": {k: choice.get(k) for k in ("choice", "source", "reason", "auto", "why", "detail")},
        "garment": {"item_id": item_id, "fsig": fsig, "step": STEP, "view": view},
        "worn": worn.name, "created_at": utc_now_iso(), "gates": {"first": record}})
    garment_images._drop_later(character_name, item_id, fsig, STEP, view)
    logger.info("Garment %s ghost %s of %s made from the worn view: %d px (%s of the figure), shift %s, gain %s",
                character_name, view, item_id, numbers.get("piece_px"), numbers.get("piece_share"),
                (numbers.get("alignment") or {}).get("shift"), numbers.get("gain"))
    return final
