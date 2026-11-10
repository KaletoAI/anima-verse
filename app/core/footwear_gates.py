"""Pure gates of the shoe source (plan
``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md`` Task 3, spec
``docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md`` § 5.2,
§ 5.3) — numpy on masks and meshes, no storage, no service.

- ``empty_gate`` judges the matte of the empty-shoe image (step ``empty``):
  one shoe, no leg, a side view, and — when the item image's own matte is
  given — the same shoe below the empty shoe's own top edge.
- ``side_silhouette`` + ``silhouette_iou`` give the mesh's ``mesh_iou``
  against the cut-out; ``component_shares`` its ``component_share``.

Gate tables are ``{metric: (kind, limit, label)}`` with kind ``min`` /
``max`` / ``range`` (limit ``(lo, hi)``); ``check_gates`` applies one.
"""
import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

#: Gates of the empty-shoe matte (start values, calibrated in P1).
EMPTY_GATES: Dict[str, Tuple[str, Any, str]] = {
    "single_share": ("min", 0.98, "area share of the largest matte component"),
    "aspect": ("range", (1.1, 2.4), "side-view length / height of the shoe"),
    "iou_below_topline": ("min", 0.85, "silhouette IoU with the item image below the empty shoe's top edge"),
}
#: Gates of the prepared shoe mesh. ``component_share`` is the largest
#: component plus every component inside its bounding box (double outsole and
#: lining are separate shells).
MESH_GATES: Dict[str, Tuple[str, Any, str]] = {
    "component_share": ("min", 0.98, "area share of the largest component plus the ones inside it"),
    "mesh_iou": ("min", 0.80, "side-silhouette IoU against the empty-shoe cut-out"),
}

#: Share of the footprint length at each end; the taller end is the heel and
#: its maximum height the heel-counter height.
END_SHARE = 0.15
#: The throat region, as shares of the footprint length (symmetric, so it
#: does not depend on which end is the heel).
MIDDLE = (0.35, 0.65)
#: A leg: the throat stands taller than the counter by more than this share of
#: the length ...
LEG_EXCESS_SHARE = 0.05
#: ... or a component touches the top image row and is narrower than this
#: share of the length.
LEG_TOP_WIDTH_SHARE = 0.25

LEG_REASON = "leg: something rises above the heel counter (a foot or leg in the image)"
#: Columns of the length-normalised grid ``iou_below_topline`` compares on.
ENVELOPE_COLUMNS = 256


def check_gates(metrics: Dict[str, Any], gates: Dict[str, Tuple[str, Any, str]], *,
                optional: Iterable[str] = ()) -> Tuple[bool, List[str]]:
    """``(ok, reasons)`` of ``metrics`` against ``gates``. A missing or
    non-finite value refuses, unless its key is in ``optional`` and the value
    is ``None``."""
    optional = set(optional)
    reasons: List[str] = []
    for key, (kind, limit, label) in gates.items():
        value = metrics.get(key)
        if value is None and key in optional:
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            reasons.append(f"{key}: missing ({label})")
        elif kind == "min" and value < limit:
            reasons.append(f"{key} {value:.4g} < {limit:g} ({label})")
        elif kind == "max" and value > limit:
            reasons.append(f"{key} {value:.4g} > {limit:g} ({label})")
        elif kind == "range" and not (limit[0] <= value <= limit[1]):
            reasons.append(f"{key} {value:.4g} outside {limit[0]:g}..{limit[1]:g} ({label})")
    return not reasons, reasons


# --- masks --------------------------------------------------------------------------------------------------------------

def _as_mask(matte) -> np.ndarray:
    """A boolean H x W mask: bool as is, integers at >= 128, floats at >= 0.5."""
    arr = np.asarray(matte)
    if arr.ndim != 2:
        raise ValueError(f"a matte is H x W, got shape {arr.shape}")
    if arr.dtype == bool:
        return arr
    if np.issubdtype(arr.dtype, np.integer):
        return arr >= 128
    return arr >= 0.5


def _label(mask: np.ndarray) -> Tuple[np.ndarray, int]:
    from scipy import ndimage
    labels, count = ndimage.label(mask, structure=np.ones((3, 3), bool))
    return labels, int(count)


def _shoe(mask: np.ndarray) -> Optional[Dict[str, Any]]:
    """The largest component of ``mask`` and its column profile, ``None`` for
    an empty mask: ``labels``, ``count``, ``areas`` (per label, index 0 =
    background), ``comp`` (bool), ``x0``/``x1`` (columns), ``ground`` (its
    last row), ``top`` (its first row), ``length`` (columns), ``heights`` (per
    column, ground - top row + 1), ``counter`` (max height of the taller
    end)."""
    labels, count = _label(mask)
    if count == 0:
        return None
    areas = np.bincount(labels.ravel(), minlength=count + 1)
    best = int(np.argmax(areas[1:])) + 1
    comp = labels == best
    rows, cols = np.nonzero(comp)
    x0, x1 = int(cols.min()), int(cols.max())
    ground, top = int(rows.max()), int(rows.min())
    sub = comp[:, x0:x1 + 1]
    has = sub.any(axis=0)
    first = np.argmax(sub, axis=0)
    heights = np.where(has, ground - first + 1, 0)
    length = x1 - x0 + 1
    n_end = max(1, int(round(END_SHARE * length)))
    counter = int(max(heights[:n_end].max(), heights[-n_end:].max()))
    return {"labels": labels, "count": count, "areas": areas, "comp": comp, "x0": x0, "x1": x1,
            "ground": ground, "top": top, "length": length, "heights": heights, "counter": counter}


def _ground_grid(shoe: Dict[str, Any], columns: int) -> np.ndarray:
    """The shoe component on a length-normalised, ground-anchored grid:
    ``columns`` columns span its length, one row is one column's width
    (aspect kept), the last row is its ground. Rows = ``round(columns *
    bbox height / length)``."""
    from PIL import Image
    comp = shoe["comp"][shoe["top"]:shoe["ground"] + 1, shoe["x0"]:shoe["x1"] + 1]
    rows = max(1, int(round(columns * comp.shape[0] / shoe["length"])))
    img = Image.fromarray(comp.astype(np.uint8) * 255).resize((columns, rows), Image.BILINEAR)
    return np.asarray(img) >= 128


def envelope_iou(empty: Dict[str, Any], item: Dict[str, Any], *, columns: int = ENVELOPE_COLUMNS) -> float:
    """``iou_below_topline``: the two shoes length-normalised and ground-anchored
    (``_ground_grid``), the item restricted to what lies at or below the EMPTY
    shoe's own top edge in each column (its highest filled cell; a column the
    empty shoe does not fill keeps nothing of the item), then the IoU with the
    empty shoe — the max over the horizontal flip of the item. A foot or leg in
    the item image's throat stands above the empty shoe's top edge there and
    drops out; a shoe the edit changed (another heel, a filled throat, another
    length) does not."""
    ge, gi = _ground_grid(empty, columns), _ground_grid(item, columns)
    rows = max(ge.shape[0], gi.shape[0])
    pad = lambda g: np.vstack([np.zeros((rows - g.shape[0], columns), bool), g])  # noqa: E731 — ground = last row
    ge, gi = pad(ge), pad(gi)
    filled = ge.any(axis=0)
    top = np.where(filled, np.argmax(ge, axis=0), rows)        # first filled row from the top; none -> below the grid
    below = np.arange(rows)[:, None] >= top[None, :]
    best = 0.0
    for cand in (gi, gi[:, ::-1]):
        env = cand & below
        union = int((ge | env).sum())
        if union:
            best = max(best, int((ge & env).sum()) / union)
    return float(best)


def empty_gate(matte: np.ndarray, *, item_matte: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """Judge the matte of an empty-shoe side view -> ``{ok, reasons,
    single_share, aspect, leg, iou_below_topline}``.

    - ``single_share``: area of the largest component / matte area.
    - ``aspect``: the largest component's bbox width / height.
    - ``leg``: the max height over the middle ``MIDDLE`` of the length exceeds
      the heel-counter height (the taller of the two ``END_SHARE`` ends) by
      more than ``LEG_EXCESS_SHARE`` of the length, or any component touches
      the top image row and is narrower than ``LEG_TOP_WIDTH_SHARE`` of the
      length. A leg always refuses.
    - ``iou_below_topline`` (only with ``item_matte``, ``None`` otherwise or
      when the item matte is empty): ``envelope_iou`` — the item image's shoe
      compared with the empty shoe only below the empty shoe's OWN top edge in
      each column, so the foot and leg filling the item's throat never count
      (a cut at the heel-counter height kept them: on a pump the counter is the
      top of the whole shoe).
    """
    mask = _as_mask(matte)
    shoe = _shoe(mask)
    if shoe is None:
        return {"ok": False, "reasons": ["matte: empty"], "single_share": 0.0, "aspect": None, "leg": False,
                "iou_below_topline": None}
    length = shoe["length"]
    single_share = float(shoe["areas"][1:].max() / shoe["areas"][1:].sum())
    aspect = float(length / (shoe["ground"] - shoe["top"] + 1))

    heights = shoe["heights"]
    m0 = int(round(MIDDLE[0] * length))
    m1 = max(m0 + 1, int(round(MIDDLE[1] * length)))
    leg = bool(heights[m0:m1].max() - shoe["counter"] > LEG_EXCESS_SHARE * length)
    if not leg:
        labels = shoe["labels"]
        for lab in np.unique(labels[0][labels[0] > 0]):
            cols = np.nonzero((labels == lab).any(axis=0))[0]
            if cols.max() - cols.min() + 1 < LEG_TOP_WIDTH_SHARE * length:
                leg = True
                break

    iou = None
    if item_matte is not None:
        item = _shoe(_as_mask(item_matte))
        if item is not None:
            iou = envelope_iou(shoe, item)

    metrics = {"single_share": single_share, "aspect": aspect, "iou_below_topline": iou}
    ok, reasons = check_gates(metrics, EMPTY_GATES, optional=("iou_below_topline",))
    if leg:
        reasons.append(LEG_REASON)
    return {"ok": ok and not leg, "reasons": reasons, "single_share": single_share, "aspect": aspect,
            "leg": leg, "iou_below_topline": iou}


def _crop(mask: np.ndarray) -> Optional[np.ndarray]:
    rows = np.nonzero(mask.any(axis=1))[0]
    cols = np.nonzero(mask.any(axis=0))[0]
    if not len(rows):
        return None
    return mask[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]


def _resample(mask: np.ndarray, size: int) -> np.ndarray:
    from PIL import Image
    img = Image.fromarray(mask.astype(np.uint8) * 255).resize((size, size), Image.BILINEAR)
    return np.asarray(img) >= 128


def silhouette_iou(a: np.ndarray, b: np.ndarray, *, size: int = 256) -> float:
    """IoU of two silhouettes, each cropped to its bbox and resampled to
    ``size`` x ``size``; the max over ``b`` and its horizontal flip (the toe
    side of a mesh is only known after the insole analysis). 0.0 when either
    is empty."""
    ca, cb = _crop(_as_mask(a)), _crop(_as_mask(b))
    if ca is None or cb is None:
        return 0.0
    ra = _resample(ca, size)
    best = 0.0
    for cand in (cb, cb[:, ::-1]):
        rb = _resample(np.ascontiguousarray(cand), size)
        union = int((ra | rb).sum())
        if union:
            best = max(best, int((ra & rb).sum()) / union)
    return float(best)


# --- meshes -------------------------------------------------------------------------------------------------------------

def side_silhouette(positions: np.ndarray, faces: np.ndarray, *, size: int = 256) -> np.ndarray:
    """The ``size`` x ``size`` boolean side view of a shoe mesh: an
    orthographic projection on the length/up plane of
    ``footwear_insole.shoe_frame``, triangles filled, aspect kept (the longer
    extent spans the image, the up axis points to row 0)."""
    from PIL import Image, ImageDraw
    from app.core.footwear_insole import shoe_frame
    P = np.asarray(positions, np.float64).reshape(-1, 3)
    F = np.asarray(faces, np.int64).reshape(-1, 3)
    out = np.zeros((size, size), bool)
    if len(F) == 0:
        return out
    Q = shoe_frame(P, F).to_frame(P)[:, :2]
    used = Q[np.unique(F)]
    lo, hi = used.min(0), used.max(0)
    extent = float((hi - lo).max())
    if extent <= 0:
        return out
    scale = (size - 1) / extent
    uv = np.stack([(Q[:, 0] - lo[0]) * scale, (hi[1] - Q[:, 1]) * scale], axis=1)
    img = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(img)
    for tri in uv[F]:
        draw.polygon([tuple(p) for p in tri.tolist()], fill=255)
    return np.asarray(img) > 0


def component_shares(positions: np.ndarray, faces: np.ndarray) -> Tuple[float, float]:
    """``(largest, enclosed)`` area shares after ``garment_fit.weld``: the
    largest component, and the largest plus every component whose bbox lies
    inside the largest's bbox. ``(0.0, 0.0)`` without faces."""
    from app.core.garment_fit import components, weld
    Pw, Fw, _ = weld(positions, faces)
    if len(Fw) == 0:
        return 0.0, 0.0
    labels, share = components(Pw, Fw)
    count = len(share)
    lo = np.full((count, 3), np.inf)
    hi = np.full((count, 3), -np.inf)
    np.minimum.at(lo, labels, Pw)
    np.maximum.at(hi, labels, Pw)
    best = int(np.argmax(share))
    eps = 1e-9 * max(1.0, float(np.linalg.norm(hi[best] - lo[best])))
    inside = np.all(lo >= lo[best] - eps, axis=1) & np.all(hi <= hi[best] + eps, axis=1)
    return float(share[best]), float(share[inside].sum())
