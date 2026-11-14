#!/usr/bin/env python3
"""The HAAR gate, judged after the drape (``app/core/garment_haar.py::gate``) — strand-hair plan 2026-11-13, Task 12
(spec § 6.3.2). Pure: no world, no Taichi, no network.

Usage: ./.venv/bin/python scripts/smoke_haar_gate.py

The gate refuses a seed only for what stays visibly wrong on the draped, carded hair (spec § 6.3.2):

- ``inside_head_3mm`` > 0: a draped strand with a point above the chin deeper than ``INSIDE_HEAD_MM`` = 3 mm in the
  body SDF;
- ``eye_cards`` > 0: a card centreline across the eye box (``eye_box(margin=0)``) after the face clearing;
- ``tip_p50_rel_shoulder_cm`` above the class bound — the spike's class limits plus a 5 cm slack:
  medium +8 + 5 = +13.0, long -6 + 5 = -1.0, very long -20 + 5 = -15.0 (``CLEARLY_SHORT_CM``); very short, short and
  no class are never refused; hair that is too long never is.

Expected (by hand from those rules):

  [1] {inside 0, eye 0, tip 12.9}, medium -> (True, []) — 12.9 <= 13.0
  [2] tip 13.1, medium -> refused, the one reason
      "too short for medium hair (tip 13.1 cm above the shoulder, at most 13.0)"
  [3] long: -0.9 > -1.0 -> refused; -1.0 (not above the bound) -> passes
  [4] very long: -15.1 <= -15.0 -> passes; -14.9 > -15.0 -> refused
  [5] short, tip 40.0 -> passes (short is never refused); no class (None), tip 25.0 -> passes
  [6] inside_head_3mm 1 -> refused (one reason); eye_cards 1 -> refused (one reason); all three at once (inside 1,
      eye 1, tip 13.1 medium) -> three reasons; a missing number refuses
  [7] the constants verbatim: HAAR_FIT_VERSION 1, INSIDE_HEAD_MM 3.0, CLEARLY_SHORT_CM, CLASS_TARGET_CM

Calibration on real hair (2026-11-14, Task 12; not re-run here — it needs the real bodies). The user saw the spike's
round-3 hairs after the drape and said "ALLE Haare, auch die Fail sehen so gut aus", so every one of them must pass.
``garment_haar.fit_haar`` ran on read-only copies of Kira's (``base20d5701a``) and Lirien's (``base729ed4c2``) base
bodies, with the spike's round-3 strands (``~/claude-out/haar-spike2/strands``) and the live alias's sample job
(``8132167b…``, seed 7, "shoulder-length wavy hair"); renders in ``~/claude-out/h3-fit/``. The length class is the
prompt's (``hair_length_class``: "shoulder-length …" names no class -> None) and, for the sample, the wearer's
hairstyle class (medium):

  | body   | strands                          | class     | inside_head_3mm | eye_cards | tip cm | bound  | gate  |
  |--------|----------------------------------|-----------|-----------------|-----------|--------|--------|-------|
  | Kira   | sample job 8132167b (seed 7)     | medium    | 0               | 0         | -15.5  | +13.0  | pass  |
  | Lirien | sample job 8132167b (seed 7)     | medium    | 0               | 0         | -14.1  | +13.0  | pass  |
  | Kira   | long-thick-curly…blades s2       | long      | 0               | 0         | -15.1  | -1.0   | pass  |
  | Kira   | very-long-wavy…waist s3          | very long | 0               | 0         | -19.2  | -15.0  | pass  |
  | Lirien | shoulder-length-straight s2      | None      | 0               | 0         | -8.7   | —      | pass  |
  | Lirien | very-long-wavy…waist s1          | very long | 0               | 0         | -28.9  | -15.0  | pass  |

  inside_head_3mm: every run 0. The drape keeps DRAPE_CLEAR_M = 4 mm outside; 3 to 8 of 4000 strands per run still
  touch the skin above the chin (inside_head_0mm), none deeper than 3 mm -> the spec's 3 mm limit refuses none.
  eye_cards: every run 0 — the keep-out during the drape and the box rule after it leave no centreline in the eye box
  (face_cards 51 .. 70 hang beside the face, inside the wider face box: framing locks, not refused).
  Tip: the smallest margin is very long Kira s3, -19.2 against -15.0 (4.2 cm); the sample, judged medium,
  lies 27 cm below its bound — so the 5 cm slack over the spike's class limits refuses none of the hair the user
  accepted, and the bounds in [1] .. [4] stay the spec's.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def m(inside=0, eye=0, tip=0.0):
    return {"inside_head_3mm": inside, "eye_cards": eye, "tip_p50_rel_shoulder_cm": tip}


def main():
    from app.core import garment_haar as gh
    g = gh.gate

    # [1]
    check(g(m(tip=12.9), "medium") == (True, []), f"[1] 12.9 medium passes (got {g(m(tip=12.9), 'medium')})")
    # [2]
    ok, reasons = g(m(tip=13.1), "medium")
    want = "too short for medium hair (tip 13.1 cm above the shoulder, at most 13.0)"
    check(not ok and reasons == [want], f"[2] 13.1 medium refused with {want!r} (got {reasons})")
    # [3]
    check(not g(m(tip=-0.9), "long")[0], f"[3] -0.9 long refused ({g(m(tip=-0.9), 'long')[1]})")
    check(g(m(tip=-1.0), "long") == (True, []), "[3] -1.0 long passes")
    # [4]
    check(g(m(tip=-15.1), "very long") == (True, []), "[4] -15.1 very long passes")
    check(not g(m(tip=-14.9), "very long")[0], f"[4] -14.9 very long refused ({g(m(tip=-14.9), 'very long')[1]})")
    # [5]
    check(g(m(tip=40.0), "short") == (True, []), "[5] 40.0 short passes (never refused)")
    check(g(m(tip=25.0), None) == (True, []), "[5] 25.0 without a class passes")
    check(g(m(tip=40.0), "very short") == (True, []), "[5] 40.0 very short passes")
    # [6]
    ok, reasons = g(m(inside=1, tip=0.0), "medium")
    check(not ok and len(reasons) == 1 and "head" in reasons[0], f"[6] inside 1 refused ({reasons})")
    ok, reasons = g(m(eye=1, tip=0.0), "medium")
    check(not ok and len(reasons) == 1 and "eyes" in reasons[0], f"[6] eye 1 refused ({reasons})")
    ok, reasons = g(m(inside=1, eye=1, tip=13.1), "medium")
    check(not ok and len(reasons) == 3, f"[6] all three -> three reasons ({reasons})")
    ok, reasons = g({"eye_cards": 0, "tip_p50_rel_shoulder_cm": 0.0}, "medium")
    check(not ok and len(reasons) == 1, f"[6] a missing number refuses ({reasons})")
    ok, reasons = g(m(tip=float("nan")), "long")
    check(not ok and len(reasons) == 1, f"[6] a non-finite tip refuses for a gated class ({reasons})")
    # [7]
    check(gh.HAAR_FIT_VERSION == 1, "[7] HAAR_FIT_VERSION 1")
    check(gh.INSIDE_HEAD_MM == 3.0, "[7] INSIDE_HEAD_MM 3.0")
    check(gh.CLEARLY_SHORT_CM == {"medium": 13.0, "long": -1.0, "very long": -15.0}, "[7] CLEARLY_SHORT_CM")
    check(gh.CLASS_TARGET_CM == {"very short": 20, "short": 14, "medium": 4, "long": -12, "very long": -30},
          "[7] CLASS_TARGET_CM")

    print("PASS" if not FAILS else f"FAIL ({len(FAILS)})")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
