#!/usr/bin/env python3
"""Smoke: texture from cut — the back's weave against the front answer's (``cut_texture_post.WEAVE_GATE``) and the
sheer piece's decorated decision without the body seen through it (``cut_texture_post.BODY_SEEN``,
``garment_cut_texture.decor_detail``). Review of group B stage 3.

Usage:
    ./.venv/bin/python scripts/smoke_cut_texture_detail_gates.py

No server, no world DB (a throwaway ``paths.init``), no Blender, no hub job, no BiRefNet (``matte=None``). Every
expectation is derived by hand:

[1] ``weave_level`` = std of L* minus its Gaussian (sigma 0.5 cm = 5 px at 10 px/cm) over the panel eroded 1 cm.
    A 100 x 100 panel at 10 px/cm whose rows alternate sRGB grey 110 / 130: L* = 116 f(Y) - 16 with
    Y = ((v / 255 + 0.055) / 1.055) ^ 2.4 gives 46.435 / 54.368; a 2-px period under a 5-px Gaussian keeps
    exp(-2 pi^2 25 / 4) ~ 1e-54 of its amplitude, so the high-pass IS the alternation: std = (54.368 - 46.435) / 2
    = 3.966 (within 0.15: the mirrored border is 10 px from the eroded panel, a Gaussian tail of ~2 %). A flat panel
    reads 0.0. The same weave drawn at 20 px/cm with 2-row stripes (a 4-px period) is resampled by 0.5 (BOX: each
    pair of equal rows averages to itself) to the same 2-px alternation: 3.966 again. A panel of 15 px eroded by
    10 px is too small: None.
[2] ``weave_gate``: the limit is 1.25 x front + 1.0. Dario's linen (the saved live answers) 4.707 -> 7.644: limit
    6.884, rejected, the text names both; Glut's gloves 12.565 -> 14.426: limit 16.706, ok; Lirien's dress
    0.773 -> 1.282: limit 1.966, ok; a back lower than its front (Kai 4.28 -> 0.98) ok; no front level: None.
[3] ``body_seen`` on single colours (L*, a*, b* from the sRGB formula): skin (222, 172, 140) = (74.15, 14.02, 23.50),
    chroma 27.4 >= 15, hue 59.2 deg in 25..75, L* >= 25 -> body; navy (60, 70, 110) hue -72.8 -> cloth; cream
    (235, 215, 190) chroma 15.1, hue 78.7 > 75 -> cloth (Tilda's blouse stays her cloth); a green (150, 200, 60)
    hue > 90 -> cloth.
[4] ``picture_reference`` (``matte=None``: the white backdrop is keyed) of a 1024 px picture: an 800 px navy panel with
    three vertical 96-px stripes. ``detail_density`` works at 128 px (the panel 128, eroded 4 px -> 120 columns);
    a navy/skin step (dL* 43.6) under the sigma-1 Gaussian has the gradient 43.6 / sqrt(2 pi) x exp(-x^2 / 2) =
    17.4 exp(-x^2 / 2) > 4 for |x| < 1.72 px: ~3.4 edge columns per step, 6 steps ~ 20 of 120 = 0.17 > 0.10
    (decorated). Without the body (the stripes plus a 0.006 x 1024 = 6 px rim = 1 px at 128): at most the
    1.72 - 1 ~ 0.7 px left of each band, ~ 6 x 1 / 120 = 0.05 <= 0.10 (plain). The same picture with GREEN stripes
    (no skin hue: ``body_seen`` is empty) keeps ``detail_cloth`` == ``detail`` exactly.
[5] ``decor_detail``: a sheer piece reads ``front_cloth`` (Gelina's sheer skirt, measured 0.146 -> 0.032: plain); an
    opaque one ``front`` (Dario's beige linen 0.277: its cloth is skin-toned, it stays decorated); a sheer piece
    whose cloth is all skin-toned (``front_cloth`` None) falls back to ``front``.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="smoke_detail_gates_"))

from app.core import cut_texture_post as post  # noqa: E402
from app.core import garment_cut_texture as gct  # noqa: E402

FAIL: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAIL.append(label)


def lstar(v: float) -> float:
    c = v / 255.0
    y = c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    f = y ** (1 / 3) if y > (6 / 29) ** 3 else y / (3 * (6 / 29) ** 2) + 4 / 29
    return 116 * f - 16


print("[1] weave_level")
expect = (lstar(130) - lstar(110)) / 2
check("hand L* of 110 / 130", abs(lstar(110) - 46.435) < 0.01 and abs(lstar(130) - 54.368) < 0.01,
      f"{lstar(110):.3f} / {lstar(130):.3f}")
img = np.full((140, 140, 3), 255, np.uint8)
mask = np.zeros((140, 140), bool)
mask[20:120, 20:120] = True
rows = np.where((np.arange(140) % 2) == 0, 110, 130).astype(np.uint8)
img[mask] = 0
img[20:120, 20:120] = rows[20:120, None, None]
w = post.weave_level(img, mask, 10.0)
check("alternating rows at 10 px/cm = 3.966", w is not None and abs(w - expect) < 0.15, f"{w}")
flat = np.full((140, 140, 3), 120, np.uint8)
check("flat panel = 0", post.weave_level(flat, mask, 10.0) == 0.0, f"{post.weave_level(flat, mask, 10.0)}")
big = np.full((280, 280, 3), 255, np.uint8)
bmask = np.zeros((280, 280), bool)
bmask[40:240, 40:240] = True
rows2 = np.where(((np.arange(280) - 40) // 2) % 2 == 0, 110, 130).astype(np.uint8)
big[40:240, 40:240] = rows2[40:240, None, None]
w2 = post.weave_level(big, bmask, 20.0)
check("2-row stripes at 20 px/cm = the same 3.966", w2 is not None and abs(w2 - expect) < 0.15, f"{w2}")
small = np.zeros((40, 40), bool)
small[10:25, 10:25] = True
check("a 15 px panel is too small", post.weave_level(flat[:40, :40], small, 10.0) is None)

print("[2] weave_gate")
g = post.weave_gate(7.644, 4.707)
check("Dario's linen back rejected", g is not None and not g["ok"] and abs(g["limit"] - 6.884) < 1e-6
      and "7.64" in g["text"] and "4.71" in g["text"], f"{g}")
g = post.weave_gate(14.426, 12.565)
check("Glut's gloves pass", g["ok"] and abs(g["limit"] - 16.706) < 1e-3, f"{g['limit']}")
g = post.weave_gate(1.282, 0.773)
check("Lirien's dress passes", g["ok"] and abs(g["limit"] - 1.966) < 1e-3, f"{g['limit']}")
check("a lower back passes", post.weave_gate(0.98, 4.28)["ok"])
check("no front level: None", post.weave_gate(5.0, None) is None and post.weave_gate(None, 5.0) is None)

print("[3] body_seen on single colours")
for rgb, body in (((222, 172, 140), True), ((60, 70, 110), False), ((235, 215, 190), False),
                  ((150, 200, 60), False)):
    one = np.full((40, 40, 3), rgb, np.uint8)
    got = bool(post.body_seen(one).all()) if body else not post.body_seen(one).any()
    check(f"{rgb} body={body}", got)

print("[4] picture_reference: detail with and without the body")


def picture(stripe):
    px = np.full((1024, 1024, 4), 255, np.uint8)
    px[112:912, 112:912, :3] = (60, 70, 110)
    for x0 in (232, 464, 696):
        px[112:912, x0:x0 + 96, :3] = stripe
    return px


ref = post.picture_reference(picture((222, 172, 140)), matte=None)
check("skin stripes: detail > 0.10 (would be decorated)", ref["detail"] is not None and ref["detail"] > 0.10,
      f"{ref['detail']}")
check("without the body: detail_cloth <= 0.10 (plain)", ref["detail_cloth"] is not None
      and ref["detail_cloth"] <= 0.10, f"{ref['detail_cloth']}")
ref2 = post.picture_reference(picture((150, 200, 60)), matte=None)
check("green stripes: detail_cloth == detail", ref2["detail_cloth"] == ref2["detail"] and ref2["detail"] > 0.10,
      f"{ref2['detail']} / {ref2['detail_cloth']}")

print("[5] decor_detail")
d = {"front": 0.146, "front_cloth": 0.032}
check("sheer reads front_cloth", gct.decor_detail(d, {"fabric": "sheer"}) == 0.032
      and not gct.is_decorated(gct.decor_detail(d, {"fabric": "sheer"})))
check("opaque reads front", gct.decor_detail({"front": 0.277, "front_cloth": 0.0}, {"fabric": "medium"}) == 0.277)
check("sheer without cloth falls back", gct.decor_detail({"front": 0.37, "front_cloth": None},
                                                         {"fabric": "sheer"}) == 0.37)
check("no params reads front", gct.decor_detail({"front": 0.2}, None) == 0.2)

print("ALL OK" if not FAIL else f"FAILED: {FAIL}")
sys.exit(1 if FAIL else 0)
