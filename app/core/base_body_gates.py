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
    """The gate on an alpha channel (``(H, W)``, 0..255). See the module
    docstring; ``left``/``right`` are the image sides."""
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
