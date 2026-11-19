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

Part 2 (Ruling A99b, Tilda's dressed front and back 2026-11-16): a cream blouse over PALE skin, which the base's
skin model calls skin. Same layout; skin Lab (76, 7, 13), the draft's torso a blouse Lab (85, 4.1, 14.2), feet boots
Lab (30, 12, 20) in rows 520..580.

* blouse vs skin: ΔE76 = sqrt(9² + 2.9² + 1.2²) = sqrt(81 + 8.41 + 1.44) = 9.53 — above DE_UNSKIN 8, below
  DE_GARMENT 16; |ΔL| 9 < SKIN_SAME_DL 15. Chroma distance sqrt(2.9² + 1.2²) = 3.14, Mahalanobis 3.14 / sqrt(1.5)
  = 2.56 < SKIN_MAHA 3, L 85 > the model's floor 76 - 8 = 68: the blouse IS skin by the base's model, so neither the
  ΔE test nor A99's "skin by neither model" test sees it per pixel (the real case: ΔE 9.5, Mahalanobis 2.71).
  Its hue: atan2(14.2, 4.1) = 73.9° against atan2(13, 7) = 61.7° — turned 12.2° > BROAD_HUE_DEG 10 (the real
  case 14° / 21°), both chromas (14.8, 14.8) >= BROAD_MIN_CHROMA 5: another material.
* without the broad rule (``_broad_change`` replaced by "nothing") and with A99's ``dropped_garment`` body (its
  skin test ``~skin_b.like(draft)``, inline below) — the old code: the torso is left out (under 5 % of it is the
  draft), ``dropped`` is 0 and the composite passed. Today's ``dropped`` on that mask: the torso below the head
  rows (rows 90..300 x cols 100..200 = 21 000 px; the head rows end at 20 + round(0.12 x 560) = 87 < 90) of a
  figure of 4 200 + 21 000 + 2 x 205 x 60 + 280 x 90 = 75 000 px = 0.28, less the 2 px opening and the blurred
  edge — between 0.25 and 0.28, over DROP_MAX: the gate refuses it.
* with the broad rule: the torso (0.28 >= BROAD_MIN 0.03, hue turned) is garment — at least 95 % of it is the
  draft — and the composite passes with ``dropped`` <= DROP_MAX.
* the blouse alone (no boots — Tilda's first outfit, stored 2026-11-16 as an EMPTY composite, put-on region
  0.0019): the put-on region needs ΔE > PUT_ON_REGION_DE 20, the blouse differs by 9.53, so the coverage says
  "nothing" (region < 0.03). The old ``check`` returned no reason for "nothing" + aligned before looking at
  ``dropped`` -> EMPTY, the base unchanged. Now: the broad change is put on — not EMPTY, ``broad`` 0.25..0.28, at
  least 95 % of the torso is the draft, ok; with the broad rule off ``check`` refuses it for the DROPPED garment
  although the coverage says "nothing".
* the same skin re-rendered lighter (torso Lab (85, 7, 13): ΔE 9 > DE_UNSKIN over 0.28 of the figure, hue turned
  0°) is no garment: not put on, not counted as left out — the draft wears nothing, the composite is EMPTY (the
  base unchanged). Gelina's case: her body re-rendered darker under a bandeau, hue turned 5°.
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


def figure(torso, legs, skin_lab=(72, 11, 23), feet=None):
    img = np.zeros((600, 300, 4))
    skin = rgb(skin_lab)
    def put(r0, r1, c0, c1, c):
        img[r0:r1, c0:c1, :3] = c
        img[r0:r1, c0:c1, 3] = 255
    put(20, 90, 120, 180, skin)          # head
    put(90, 300, 100, 200, rgb(torso))   # torso
    put(95, 300, 40, 100, skin)          # left arm
    put(95, 300, 200, 260, skin)         # right arm
    put(300, 580, 105, 195, rgb(legs))   # legs
    if feet is not None:
        put(520, 580, 105, 195, rgb(feet))
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

# --- Part 2: a cream blouse over pale skin (Ruling A99b) ---
PALE, BLOUSE, BOOTS = (76, 7, 13), (85, 4.1, 14.2), (30, 12, 20)
base = figure(PALE, PALE, skin_lab=PALE)
draft = figure(BLOUSE, PALE, skin_lab=PALE, feet=BOOTS)
de = float(np.linalg.norm(np.array(BLOUSE) - np.array(PALE)))
expect(abs(de - 9.53) < 0.01 and vc.DE_UNSKIN < de < vc.DE_GARMENT, f"blouse vs skin ΔE76 {de:.2f} = 9.53")
skin_b = vc.Skin(vc._lab(base), vc.figure_mask(base))
maha = skin_b._maha(np.array(BLOUSE[1:], float))
expect(abs(maha - 2.56) < 0.02 and bool(skin_b.like(vc._lab(rgb(BLOUSE)[None, None, :]))[0, 0]),
       f"the blouse is skin by the base's model: Mahalanobis {maha:.2f} = 2.56 < {vc.SKIN_MAHA}")
turn = float(np.degrees(np.arctan2(BLOUSE[2], BLOUSE[1]) - np.arctan2(PALE[2], PALE[1])))
expect(abs(turn - 12.2) < 0.1 and turn > vc.BROAD_HUE_DEG, f"the blouse turns the hue by {turn:.1f}° = 12.2°")
torso = np.zeros(base.shape[:2], bool)
torso[100:290, 110:190] = True


def put_on_share(out):
    return float((np.abs(out[..., :3] - draft[..., :3]).max(-1) < 8)[torso].mean())


def old_dropped_garment(base, dw, base_mask, dw_mask, mask, skin_b, head_share=vc.PUT_ON_HEAD_SHARE):
    """A99's ``dropped_garment`` body (before A99b): the draft pixel must not be skin by the base's model."""
    from scipy import ndimage as ndi
    lbs, lds = vc._blur3(vc._lab(base), 1.5), vc._blur3(vc._lab(dw), 1.5)
    de = np.linalg.norm(lbs - lds, axis=-1)
    left = (dw_mask & base_mask & skin_b.like(lbs) & ~skin_b.like(lds) & (de > vc.DE_UNSKIN)
            & ~ndi.binary_dilation(mask, vc._disk(3)))
    t, b, _l, _r = vc._bbox(base_mask)
    left[:t + int(round(head_share * (b - t)))] = False
    left = ndi.binary_opening(left, vc._disk(2))
    lab_, n = ndi.label(left)
    return 0.0 if not n else float(ndi.sum(left, lab_, range(1, n + 1)).max() / max(1, base_mask.sum()))


broad, dropped = vc._broad_change, vc.dropped_garment
vc._broad_change = lambda *args: np.zeros_like(args[4])
try:
    vc.dropped_garment = old_dropped_garment
    old_out, old_record, _s = vc._composite(base, draft, "outfit", base_alpha=True)   # the old code
    vc.dropped_garment = dropped
    gate_out, gate_record, _s = vc._composite(base, draft, "outfit", base_alpha=True)  # old mask, today's gate
finally:
    vc._broad_change, vc.dropped_garment = broad, dropped
expect(put_on_share(old_out) < 0.05, f"without the broad rule the blouse is left out: {put_on_share(old_out):.3f} "
       "of the torso is the draft (< 0.05)")
expect(old_record["dropped"] == 0.0 and old_record["ok"],
       f"the old code passed it: A99's dropped {old_record['dropped']}, ok {old_record['ok']}")
expect(0.25 <= gate_record["dropped"] <= 0.28, f"today's dropped on that mask {gate_record['dropped']} in 0.25..0.28")
expect(any(r.startswith(vc.DROPPED) for r in gate_record["reasons"]) and not gate_record["ok"],
       f"the gate refuses the composite that left the blouse out: {gate_record['reasons']}")

out, record, _support = vc._composite(base, draft, "outfit", base_alpha=True)
expect(put_on_share(out) >= 0.95, f"the blouse is put on: {put_on_share(out):.3f} of the torso is the draft (>= 0.95)")
expect(record["dropped"] <= vc.DROP_MAX and record["ok"],
       f"the composite passes, dropped {record['dropped']} <= {vc.DROP_MAX} ({record['reasons']})")

alone = figure(BLOUSE, PALE, skin_lab=PALE)
out, record, _support = vc._composite(base, alone, "outfit", base_alpha=True)
alone_share = float((np.abs(out[..., :3] - alone[..., :3]).max(-1) < 8)[torso].mean())
expect(record["coverage"].get("nothing") is True and not record.get("empty") and record["ok"]
       and 0.25 <= record["broad"] <= 0.28 and alone_share >= 0.95,
       f"the blouse alone is put on, not EMPTY (coverage {record['coverage']}, broad {record['broad']})")
vc._broad_change = lambda *args: np.zeros_like(args[4])
try:
    _o, record, _s = vc._composite(base, alone, "outfit", base_alpha=True)
finally:
    vc._broad_change = broad
expect(record["coverage"].get("nothing") is True and not record.get("empty") and not record["ok"]
       and any(r.startswith(vc.DROPPED) for r in record["reasons"]),
       f"left out, the blouse alone is refused although the coverage says nothing: {record['reasons']}")

lighter = figure((85, 7, 13), PALE, skin_lab=PALE)
out, record, _support = vc._composite(base, lighter, "outfit", base_alpha=True)
expect(record.get("empty") is True and record["ok"] and np.array_equal(out, base) and record["broad"] == 0.0,
       f"skin re-rendered ΔE 9 lighter, hue kept, is no garment: EMPTY, the base unchanged "
       f"(broad {record.get('broad')}, dropped {record.get('dropped')})")

print("FAILED" if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
