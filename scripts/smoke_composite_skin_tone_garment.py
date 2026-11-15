"""Smoke: a garment close to the base's skin colour is put on, and a composite that leaves one out is refused
(Ruling A99, ``app/core/view_composite.py``).

Usage: ./.venv/bin/python scripts/smoke_composite_skin_tone_garment.py

The case (Rurik's dressed back, 2026-11-15): an oatmeal linen shirt over a bare back. Synthetic figure, one flat
Lab colour per part, on 600 x 300 px:

* base: head + torso + arms + legs, all skin  Lab (72, 11, 23)
* draft: the same figure, arms skin (72, 11, 23), torso a shirt Lab (77, 3.4, 12.4), legs trousers Lab (12, 1, 1)

Expected numbers, by hand:

* shirt vs skin: ΔE76 = sqrt(5² + 7.6² + 10.6²) = sqrt(25 + 57.8 + 112.4) = 13.97 < DE_GARMENT 16, and below
  SHARED_SKIN_DE 15 — the old rule counted the shirt as skin both shared with the base: the torso (rows 90..300 of a
  560-row figure, 100 px wide = 21 000 px) is ~1/3 of the figure, far over SHARED_SKIN_MIN, so the draft's skin
  mode became the shirt and the shirt was dropped (old ``dropped`` = the torso's share of the figure ≈ 0.3).
* flat skin: the base model's spread is the 1.0 regulariser only, cov = 1.5 I -> the shirt's Mahalanobis distance
  = 13.0 (chroma distance sqrt(7.6² + 10.6²)) / sqrt(1.5) = 10.6 > SKIN_MAHA 3: not skin. So now the torso is
  garment: at least 95 % of the torso inside the mask, ``dropped`` <= DROP_MAX (0.03), ok.
* the gate alone: ``check`` on a record with ``dropped`` 0.3 lists the DROPPED reason.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from skimage import color  # noqa: E402

from app.core import view_composite as vc  # noqa: E402

FAILS = []


def expect(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAILS.append(what)


def rgb(lab):
    return np.clip(color.lab2rgb(np.array(lab, float)[None, None, :])[0, 0], 0, 1) * 255


def figure(torso, legs):
    img = np.zeros((600, 300, 4))
    skin = rgb((72, 11, 23))
    def put(r0, r1, c0, c1, c):
        img[r0:r1, c0:c1, :3] = c
        img[r0:r1, c0:c1, 3] = 255
    put(20, 90, 120, 180, skin)          # head
    put(90, 300, 100, 200, rgb(torso))   # torso
    put(95, 300, 40, 100, skin)          # left arm
    put(95, 300, 200, 260, skin)         # right arm
    put(300, 580, 105, 195, rgb(legs))   # legs
    return img


base = figure((72, 11, 23), (72, 11, 23))
draft = figure((77, 3.4, 12.4), (12, 1, 1))
de = float(np.linalg.norm(np.array([77, 3.4, 12.4]) - np.array([72, 11, 23])))
expect(abs(de - 13.97) < 0.02 and de < vc.DE_GARMENT, f"shirt vs skin ΔE76 {de:.2f} = 13.97 < {vc.DE_GARMENT}")

out, record, support = vc._composite(base, draft, "outfit")
torso = np.zeros(base.shape[:2], bool)
torso[100:290, 110:190] = True
covered = float((np.abs(out[..., :3] - draft[..., :3]).max(-1) < 8)[torso].mean())
expect(covered >= 0.95, f"the shirt is put on: {covered:.3f} of the torso is the draft (>= 0.95)")
expect(record["dropped"] <= vc.DROP_MAX, f"dropped {record['dropped']} <= {vc.DROP_MAX}")
expect(record["ok"], f"the composite passes ({record['reasons']})")

reasons = vc.check({**record, "dropped": 0.3})
expect(any(r.startswith(vc.DROPPED) for r in reasons), f"a record with dropped 0.3 is refused: {reasons}")

print("FAILED" if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
