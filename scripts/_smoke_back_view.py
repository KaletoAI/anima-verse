"""Shared synthetic-figure fixture of the back-view / composite smokes (not a smoke itself: the leading
underscore keeps it out of ``run_smokes.py``'s ``smoke_*`` glob).

Used by ``smoke_bald_back_check.py``, ``smoke_composite_version_remake.py``, ``smoke_model_fit_remake.py`` and
``smoke_view_composite.py``. They test different functions (the bald-back gate, ``composite_outdated`` and the
remake, the model-fit remake, the composite itself) and stay separate smokes; what they share is here:

  * ``check`` + ``FAILS`` — the house check (prints ``OK``/``FAIL``, records the label; one list per process).
  * ``save`` — an RGBA float array rounded/clipped to uint8 and written as PNG (parents created).
  * ``box_figure`` — a figure from (y0, y1, x0, x1[, colour]) boxes on a ``rows`` x ``cols`` canvas, each box
    mapped y -> top + scale (y - 40), x -> 150 + scale (x - 150); at the defaults (scale 1, top 40) the boxes
    land verbatim. A box without a colour is ``SKIN``.
  * ``heads`` + ``head_figure`` — the bald-back fixture: 100 x 100 px heads (a real face from skimage's
    astronaut, a striped hair cap, a bald skin gradient, and the plain views' hairlines) on an 800 x 400 body
    whose torso colour is the outfit.

Nothing here imports ``app``; the storage redirect stays in each smoke, before its world-DB imports.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

FAILS: list = []
SKIN = np.array([224.0, 172.0, 140.0])
BLUE = np.array([40.0, 70.0, 200.0])
HAIR = np.array([70.0, 45.0, 30.0])
HAIR_LIGHT = np.array([120.0, 85.0, 55.0])


def check(label, got, want, *, limit=300):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:limit] + ("" if ok else f" — expected {want!r}"[:limit]))
    if not ok:
        FAILS.append(label)


def save(arr, path: Path) -> Path:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(np.round(arr), 0, 255).astype(np.uint8), "RGBA").save(path)
    return path


def box_figure(parts, rows=400, cols=300, scale=1.0, top=40):
    """RGBA float array: each (y0, y1, x0, x1[, colour]) box mapped y -> top + scale (y - 40), x -> 150 + scale (x - 150)."""
    a = np.zeros((rows, cols, 4))
    for part in parts:
        y0, y1, x0, x1 = part[:4]
        colour = part[4] if len(part) > 4 else SKIN
        Y0, Y1 = (int(round(top + (y - 40) * scale)) for y in (y0, y1))
        X0, X1 = (int(round(150 + (x - 150) * scale)) for x in (x0, x1))
        a[Y0:Y1, X0:X1, :3] = colour
        a[Y0:Y1, X0:X1, 3] = 255
    return a


def heads():
    from PIL import Image
    from skimage import data
    yy, xx = np.mgrid[0:100, 0:100]
    face = np.asarray(Image.fromarray(data.astronaut()[36:196, 143:303]).resize((100, 100), Image.BILINEAR), float)
    hair = np.where((xx // 6) % 2 == 0, 1.0, 0.0)[..., None] * (HAIR_LIGHT - HAIR) + HAIR
    bald = np.clip(SKIN * (1.05 - 0.25 * yy / 100)[..., None], 0, 255)

    def over(base, mask):
        out = base.copy()
        out[mask] = hair[mask]
        return out
    return {"face": face, "bald": bald, "hair": hair,
            "plain_front": over(face, (yy < 46) | (xx < 26) | (xx >= 74)),
            "plain_left": over(bald, xx < 55), "plain_right": over(bald, xx >= 45)}


def head_figure(head, torso):
    yy, xx = np.mgrid[0:100, 0:100]
    ellipse = ((yy - 49.5) / 50) ** 2 + ((xx - 49.5) / 42) ** 2 <= 1
    a = np.zeros((800, 400, 4))
    a[20:120, 150:250, :3] = head
    a[20:120, 150:250, 3] = ellipse * 255
    for (y0, y1, x0, x1), colour in [((120, 150, 185, 215), SKIN), ((150, 420, 120, 280), torso),
                                     ((155, 420, 90, 120), SKIN), ((155, 420, 280, 310), SKIN),
                                     ((420, 780, 130, 195), SKIN), ((420, 780, 205, 270), SKIN)]:
        a[y0:y1, x0:x1, :3] = colour
        a[y0:y1, x0:x1, 3] = 255
    return a
