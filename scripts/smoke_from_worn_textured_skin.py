"""Smoke: "From the worn view" keeps a lit patch of the piece's own texture that has the skin's hue (A166).

Usage: ./.venv/bin/python scripts/smoke_from_worn_textured_skin.py

Glut's scale bra (fsig b1e4a8becb8e, 2026-11-17): the glowing scales on the outer upper cups have the skin's hue
and brightness, so the skin step cut three square bites out of the cups' outline (480 px taken out; the shell made
from that region lost its outer rims). Skin is smooth, the scales are not: an area goes only when its median local
brightness spread (5 px window) is <= SKIN_TEXTURE_SD 6.

Hand-built 1536 x 600 view (1 px = 1 px at 1536, so every radius is its nominal value): grey background, figure =
the rectangle x 100..499, y 100..1499 of flat skin S = (170, 100, 60) (lum 110). The worn view adds a dark-red band
(90, 20, 10), x 150..449, y 400..519, and inside it two 30 x 30 patches:
  T at x 200..229, y 440..469: a 1-px checker of S*1.3 = (221, 130, 78) and S*1.6 = (255, 160, 96)
    -> lums 143 / 170.3, spread about |170.3 - 143| / 2 = 13.7 > 6: TEXTURE, kept;
  F at x 350..379, y 440..469: flat S*1.3 -> spread 0 <= 6: SKIN, taken out (the A46 cleavage case).
Both differ from S by >= (51 + 30 + 18) / 3 = 33 > 20 everywhere within the 5 px disc (all skin there), both
have the skin's hue (shade distance 0) and >= 0.55 of its brightness. The 2 px opening (scipy's cross, i.e. a
diamond of radius 2) takes the 3 corner pixels with x + y < 2 off each corner of a square: 900 - 4 x 3 = 888. So
skin_textured_kept_px = 888 (T), skin_removed_px >= 888 (F, grown by 3 px), T stays in the mask, F's centre does not.
Without the A166 rule T went as well (both patches are skin areas by colour alone)."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.core import garment_from_worn as gw  # noqa: E402
from app.core.model_refs import VIEW_REFERENCE_BACKGROUND  # noqa: E402

H, W = 1536, 600
S = np.array([170, 100, 60], np.float32)
base = np.empty((H, W, 3), np.float32)
base[:] = VIEW_REFERENCE_BACKGROUND
figure = np.zeros((H, W), bool)
figure[100:1500, 100:500] = True
base[figure] = S
worn = base.copy()
worn[400:520, 150:450] = (90, 20, 10)
yy, xx = np.mgrid[440:470, 200:230]
worn[440:470, 200:230] = np.where(((yy + xx) % 2 == 0)[..., None], np.minimum(S * 1.3, 255), np.minimum(S * 1.6, 255))
worn[440:470, 350:380] = np.minimum(S * 1.3, 255)
mask, _alpha, n = gw.piece_mask(base.astype(np.uint8), figure, np.round(worn).astype(np.uint8))
fails = []


def check(name, got, want):
    print(("OK  " if got == want else "FAIL"), name, got, "" if got == want else f"— expected {want}")
    if got != want:
        fails.append(name)


check("textured patch kept (px)", n.get("skin_textured_kept_px"), 888)
check("flat patch taken out", n["skin_removed_px"] >= 888, True)
check("T in the mask, F's centre not", (bool(mask[455, 215]), bool(mask[455, 365])), (True, False))
if fails:
    print("FAILED: " + ", ".join(fails))
    sys.exit(1)
print("OK smoke_from_worn_textured_skin")
