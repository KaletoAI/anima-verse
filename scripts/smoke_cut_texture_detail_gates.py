#!/usr/bin/env python3
"""Smoke: texture from cut — the back's weave against the front answer's (``cut_texture_post.WEAVE_GATE``: its level
AND its grain) and the sheer piece's decorated decision without the body seen through it
(``cut_texture_post.BODY_SEEN``, ``garment_cut_texture.decor_detail``). Review of group B stage 3.

Usage:
    ./.venv/bin/python scripts/smoke_cut_texture_detail_gates.py

No server, no world DB (a throwaway ``paths.init``), no Blender, no hub job, no BiRefNet (``matte=None``). Every
expectation is derived by hand:

[1] ``weave_levels``: ``hp`` = L* minus its Gaussian (sigma 0.5 cm = 5 px at 10 px/cm) over the panel eroded 1 cm;
    ``level`` = std(hp), ``grain`` = sqrt(mean minor eigenvalue of hp's structure tensor, gradient products under the
    same 5-px Gaussian). sRGB grey 110 / 130 give L* = 116 f(Y) - 16 with Y = ((v / 255 + 0.055) / 1.055) ^ 2.4 =
    46.435 / 54.368, so a two-tone pattern of equal shares is mean +- d, d = (54.368 - 46.435) / 2 = 3.966. The whole
    140 px picture carries the pattern (no edge in the measured region), the panel is 100 px at 10 px/cm (resample
    factor 1), eroded 10 px.
    - STRIPES, 2-px rows (period 4: 110 110 130 130): the 5-px Gaussian keeps exp(-2 pi^2 25 / 16) ~ 4e-14 of the
      fundamental, so hp = +-d: level = 3.966. np.gradient along a row is 0 (rows are constant), so the tensor is
      diag(0, gy^2) and its minor eigenvalue is 0: grain = 0.0.
    - CHECKER of 2-px blocks (hp = d u(x) u(y), u = 1 1 -1 -1): level = 3.966 again. The central difference of u is
      u' = 1 -1 -1 1 (|u'| = 1), so gx^2 = gy^2 = d^2 everywhere, and gx gy = d^2 (u' u)(x) (u u')(y) with
      u' u = 1 -1 1 -1 — a period-2 checker the Gaussian keeps exp(-2 pi^2 25 / 4) ~ 1e-54 of: the tensor is d^2 I,
      grain = d = 3.966. The same amplitude, structure apart: that is what the amplitude alone missed.
    - a flat panel reads 0.0 / 0.0; 2-row stripes drawn at 20 px/cm are resampled by 0.5 (BOX: each pair of equal rows
      averages to itself) into the 1-px alternation of [1]'s level: 3.966; a panel of 15 px eroded by 10 px: None.
[2] ``weave_gates``: weave limit 1.25 x front level + 1.0, grain limit 1.25 x front grain + 0.5. The three linen pairs
    of Dario's Worn Linen Shirt, front -> back (level / grain), measured through ``post_job`` (``WEAVE_GATE``):
    - the WORLD atlas 3fbadeae2a1f (striped front, grey speckled back — a NEGATIVE case): 5.027 / 0.498 ->
      4.936 / 2.740. Weave limit 7.284: passes (the old amplitude-only gate let it through); grain limit
      1.25 x 0.498 + 0.5 = 1.1225: 2.740 rejected.
    - live 2026-11-22 (striped front 3.198 / 0.538, limits 4.998 / 1.1725): MiniMax 4.686 / 2.630 passes the weave and
      fails the grain; P-H3 5.347 / 3.471 fails both.
    - stage 3 (a speckled front 3.452 / 2.567 -> a coarser speckle 6.061 / 3.472): grain limit 3.709 passes (both
      speckled), weave limit 5.315 rejects — the amplitude gate is still needed.
    Good pairs pass both: Glut's gloves 12.396 / 5.077 -> 14.186 / 5.621 (limits 16.495 / 6.846), Lirien's dress
    0.596 / 0.436 -> 0.877 / 0.607 (limits 1.745 / 1.045), Kai's T-shirt 2.41 / 1.29 -> 0.26 / 0.29 (lower). No front
    levels: no gate; a front without a grain: the weave gate alone.
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


print("[1] weave_levels")
d_hand = (lstar(130) - lstar(110)) / 2
check("hand L* of 110 / 130", abs(lstar(110) - 46.435) < 0.01 and abs(lstar(130) - 54.368) < 0.01,
      f"{lstar(110):.3f} / {lstar(130):.3f}")
mask = np.zeros((140, 140), bool)
mask[20:120, 20:120] = True
u = np.where((np.arange(140) // 2) % 2 == 0, 1, -1)
stripes = np.repeat(np.where(u > 0, 110, 130).astype(np.uint8)[:, None], 140, axis=1)
stripes = np.repeat(stripes[..., None], 3, axis=2)
w = post.weave_levels(stripes, mask, 10.0)
check("2-px stripes: level 3.966", w is not None and abs(w["level"] - d_hand) < 0.05, f"{w}")
check("2-px stripes: grain 0.0", w is not None and w["grain"] < 0.01, f"{w}")
checker = np.where((u[:, None] * u[None, :]) > 0, 110, 130).astype(np.uint8)
checker = np.repeat(checker[..., None], 3, axis=2)
w = post.weave_levels(checker, mask, 10.0)
check("2-px checker: level 3.966", w is not None and abs(w["level"] - d_hand) < 0.05, f"{w}")
check("2-px checker: grain 3.966", w is not None and abs(w["grain"] - d_hand) < 0.05, f"{w}")
flat = np.full((140, 140, 3), 120, np.uint8)
check("flat panel = 0 / 0", post.weave_levels(flat, mask, 10.0) == {"level": 0.0, "grain": 0.0},
      f"{post.weave_levels(flat, mask, 10.0)}")
big = np.full((280, 280, 3), 255, np.uint8)
bmask = np.zeros((280, 280), bool)
bmask[40:240, 40:240] = True
rows2 = np.where(((np.arange(280) - 40) // 2) % 2 == 0, 110, 130).astype(np.uint8)
big[40:240, 40:240] = rows2[40:240, None, None]
w2 = post.weave_levels(big, bmask, 20.0)
check("2-row stripes at 20 px/cm: level 3.966", w2 is not None and abs(w2["level"] - d_hand) < 0.15, f"{w2}")
small = np.zeros((40, 40), bool)
small[10:25, 10:25] = True
check("a 15 px panel is too small", post.weave_levels(flat[:40, :40], small, 10.0) is None)

print("[2] weave_gates")


def gates(back, front):
    return {g["gate"]: g for g in post.weave_gates(back, front)}


g = gates({"level": 4.936, "grain": 2.740}, {"level": 5.027, "grain": 0.498})
check("world atlas 3fbadeae2a1f: weave passes (limit 7.284)", g["weave"]["ok"] and abs(g["weave"]["limit"] - 7.284) < 1e-3,
      f"{g['weave']}")
check("world atlas 3fbadeae2a1f: grain rejected (limit 1.1225)", not g["grain"]["ok"]
      and abs(g["grain"]["limit"] - 1.1225) < 1e-3 and "2.74" in g["grain"]["text"], f"{g['grain']}")
front = {"level": 3.198, "grain": 0.538}
g = gates({"level": 4.686, "grain": 2.630}, front)
check("live MiniMax back: weave passes, grain rejected", g["weave"]["ok"] and not g["grain"]["ok"]
      and abs(g["weave"]["limit"] - 4.998) < 1e-3 and abs(g["grain"]["limit"] - 1.1725) < 1e-3, f"{g}")
g = gates({"level": 5.347, "grain": 3.471}, front)
check("live P-H3 back: both rejected", not g["weave"]["ok"] and not g["grain"]["ok"], f"{g}")
g = gates({"level": 6.061, "grain": 3.472}, {"level": 3.452, "grain": 2.567})
check("stage 3: grain passes (limit 3.709), weave rejects (limit 5.315)", g["grain"]["ok"] and not g["weave"]["ok"]
      and abs(g["grain"]["limit"] - 3.709) < 1e-3 and abs(g["weave"]["limit"] - 5.315) < 1e-3, f"{g}")
g = gates({"level": 14.186, "grain": 5.621}, {"level": 12.396, "grain": 5.077})
check("Glut's gloves pass both", g["weave"]["ok"] and g["grain"]["ok"] and abs(g["weave"]["limit"] - 16.495) < 1e-3
      and abs(g["grain"]["limit"] - 6.846) < 1e-3, f"{g}")
g = gates({"level": 0.877, "grain": 0.607}, {"level": 0.596, "grain": 0.436})
check("Lirien's dress passes both", g["weave"]["ok"] and g["grain"]["ok"] and abs(g["grain"]["limit"] - 1.045) < 1e-3,
      f"{g}")
g = gates({"level": 0.26, "grain": 0.29}, {"level": 2.41, "grain": 1.29})
check("Kai's lower back passes both", g["weave"]["ok"] and g["grain"]["ok"])
check("no front levels: no gate", post.weave_gates({"level": 5.0, "grain": 1.0}, None) == []
      and post.weave_gates(None, {"level": 5.0, "grain": 1.0}) == [])
check("a front without a grain: the weave gate alone",
      [x["gate"] for x in post.weave_gates({"level": 5.0, "grain": 3.0}, {"level": 5.0, "grain": None})] == ["weave"])

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
