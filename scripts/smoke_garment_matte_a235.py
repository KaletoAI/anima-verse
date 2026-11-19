"""A235 smoke: the cut-out of EVERY piece-only view (app/core/garment_matte.py) — green screen keyed by hue, enclosed
backdrop gaps opened, thin dark parts kept and despilled, a low-contrast piece left to the matte — and the green line
on every ghost prompt (app/core/garment_clothing.py).

Usage: ./.venv/bin/python scripts/smoke_garment_matte_a235.py

Pictures are synthetic (no BiRefNet: the matte is given), values derived by hand:
[1] 120x120 green screen (0, 255, 0); a dark ring (40, 30, 30) outer radius 30, inner 18, at the centre; its gap is a
    SHADOWED green (20, 140, 30): distance to the backdrop |(20, -115, 30)| = 120.5 > KEY_LO + KEY_RAMP + KEY_SURE
    = 110 — the distance key alone calls it piece; its lead 140 - 30 = 110 over the backdrop's lead 255 is 0.43 ->
    hue key (0.43 - 0.3) / 0.3 = 0.43... above HUE_KEY_HI? no: 110/255 = 0.431 -> 0.437 backdrop-ness < 0.5 — so the
    shadow is made (10, 160, 20): lead 140/255 = 0.549 -> (0.549 - 0.3)/0.3 = 0.83 >= 0.5: backdrop. The matte
    (a filled disc of radius 30, as BiRefNet fills small gaps) says piece there. Expected: the gap (pi 18^2 ~ 1018 px)
    is transparent, the ring (pi (30^2 - 18^2) ~ 1810 px) opaque.
[2] a 3 px black chain (0, 0, 0) with a green spill row (30, 90, 30) beside it, on the green screen; the matte misses
    the chain (0). Black is |(0, -255, 0)| = 255 >= 110 from the backdrop: kept by the key alone; the spill row's lead
    60/255 = 0.235 < HUE_KEY_LO: piece by hue, distance |(30, -165, 30)| = 170 >= 110: kept, and despilled — G is
    clamped to max(R, B) = 30 -> (30, 30, 30); with no inner part near it, it is not un-mixed.
[3] grey knit (120 +- 6) on grey (116): the matte's piece is mostly key-background (>= LOW_CONTRAST 0.03) -> "matte"
    mode, the matte's footprint kept whole.
[5] A219 un-mix on the green screen: a 60x60 lace (2 px checker of black (0, 0, 0) and the half mix (0, 127.5, 0))
    on (0, 255, 0): bg - F = (0, 255, 0), the mix sits at T = 0.5 on the line -> mixed share ~0.5 >= 0.15, pure ~0.5
    >= 0.2, interleave 1 -> gate; applied, a mixed pixel becomes (0, 127.5 - 0.5 * 255, 0) = (0, 0, 0).
[4] every ghost prompt ends with GREEN_LINE; ``green=False`` leaves it out."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import garment_matte as gm  # noqa: E402
from app.core import garment_clothing as gc  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + label + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


yy, xx = np.mgrid[:120, :120]
r = np.hypot(yy - 60, xx - 60)
img = np.zeros((120, 120, 3), np.uint8)
img[:] = (0, 255, 0)
img[(r < 30) & (r >= 18)] = (40, 30, 30)
img[r < 18] = (10, 160, 20)
rgba = np.dstack([img, np.full((120, 120), 255, np.uint8)])
out, info = gm.cut(rgba, matte=lambda _x: (r < 30).astype(float), keep_alpha=False)
gap = r < 16
ring = (r < 28) & (r >= 20)
check("[1] gap transparent", (out[..., 3][gap] == 0).mean() == 1.0, f"{(out[..., 3][gap] == 0).mean():.3f}")
check("[1] ring opaque", (out[..., 3][ring] == 255).mean() == 1.0, f"{(out[..., 3][ring] == 255).mean():.3f}")

img = np.zeros((60, 120, 3), np.uint8)
img[:] = (0, 255, 0)
img[20:23, 10:110] = (0, 0, 0)
img[23, 10:110] = (30, 90, 30)
img[35:55, 40:80] = (200, 60, 50)       # the piece the matte does see
m = np.zeros((60, 120))
m[35:55, 40:80] = 1.0
out, info = gm.cut(np.dstack([img, np.full((60, 120), 255, np.uint8)]), matte=lambda _x: m, keep_alpha=False)
check("[2] chain kept", (out[20:24, 10:110, 3] == 255).mean() == 1.0, f"{(out[20:24, 10:110, 3] == 255).mean():.3f}")
g = out[23, 12:108].astype(int)
check("[2] spill row despilled to (30, 30, 30)", bool((np.abs(g[:, :3] - 30) <= 1).all()),
      str(g[:3].tolist()))

rng = np.random.default_rng(1)
img = np.full((100, 100, 3), 116, np.float64)
yy, xx = np.mgrid[:100, :100]
piece = (abs(yy - 50) < 30) & (abs(xx - 50) < 25)
img[piece] = 120 + rng.normal(0, 6, (piece.sum(), 1))
img = np.clip(img, 0, 255).astype(np.uint8)
out, info = gm.cut(np.dstack([img, np.full((100, 100), 255, np.uint8)]), matte=lambda _x: piece.astype(float),
                   keep_alpha=False)
check("[3] low contrast -> matte mode", info["mode"] == "matte", info["mode"])
check("[3] footprint whole", int((out[..., 3] == 255).sum()) == int(piece.sum()))

for cls in gc.GHOST_TEXTS:
    for view in gc.EDIT_VIEWS:
        p = gc.ghost_prompt({"ghost_text": cls}, view)
        check(f"[4] {cls}/{view} ends green, no 'seamlessly'", p.endswith(gc.GREEN_LINE) and "seamlessly" not in p)
        check(f"[4] {cls}/{view} green=False", gc.GREEN_LINE not in gc.ghost_prompt({"ghost_text": cls}, view,
                                                                                    green=False))
from app.core.garment_shell import unmix_backdrop  # noqa: E402
img = np.zeros((100, 100, 3), np.float64)
img[:] = (0, 255, 0)
yy, xx = np.mgrid[:100, :100]
sq = (yy >= 20) & (yy < 80) & (xx >= 20) & (xx < 80)
mix = sq & (((yy // 2) + (xx // 2)) % 2 == 1)
img[sq] = (0, 0, 0)
img[mix] = (0, 127.5, 0)
res, inf = unmix_backdrop(img, sq, apply=None)
check("[5] lace gate on green", bool(inf["gate"]), str(inf))
check("[5] mix un-mixed to black", float(np.abs(res[mix]).max()) <= 1.0, f"{float(np.abs(res[mix]).max()):.2f}")
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
