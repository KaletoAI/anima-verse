#!/usr/bin/env python3
"""The face cleanup's eye-separation gate admits the wide-set lash paint of the generated base bodies.

Measured (2026-11-10, read-only copies of the unrigged base meshes, ``face_cleanup._locate_eyes`` on the 1.70 m
reference scale): the separation of the two lash-paint centres is 82 mm (Kai), 88 mm (Kira) and 100 mm (Lirien).
The paint centre is not the pupil: smoky paint and lash flaps widen toward the outer corner, so the median of the
painted x sits outward of the eye. Lirien's 100 mm failed the old upper bound of 90 mm ("eye separation 100 mm is
not a face"), the cleanup skipped, and her unpressed lash flaps stayed black through the face retexture (13.9 % of
the eye-band texels near-black on the final model, against 4.8 % on Kira's cleaned one). With the bound at 110 mm
the same mesh is located and cleaned (lash p90 9.1 -> 0.5 mm proud, lips/skin saturation 1.65 -> 1.31).

Fixture: the synthetic head of ``smoke_face_cleanup.py`` (sphere R = 0.055 units, 1 mm = 0.975 / 1700 units,
paint ellipse 22 x 7 mm per eye) with the eye centres moved to x = +-50 mm and +-60 mm. The paint is mapped
planar, but the locator takes the median of the painted VERTICES, and on a sphere of radius 96 mm their density per
millimetre of x grows toward the rim (1 / cos of the surface angle: 1.05 at x = 28 mm, 1.17 at 50, 1.51 at 72), so
the median lands a little outward of the paint centre: the located separation reads 2 * |x| plus a few millimetres
(about 103 and 123 mm) — inside 110 for the first, outside for the second.

Hand-derived expectations:
- 100 mm: located (two eyes, |centre x| within 45..55 mm), the cleanup records ``applied`` for the eyes;
- 120 mm: still refused — the reason reads "eye separation 12x mm is not a face" (a pair of clusters that far
  apart is not one face's eyes; the bound stays a bound);
- the canonical 69.7 mm fixture is untouched by the change (``smoke_face_cleanup.py`` keeps passing).
On b1c42502 (bound 90 mm) the 100 mm case fails with the reason "eye separation 103 mm is not a face".

Usage: ./.venv/bin/python scripts/smoke_face_cleanup_eye_separation.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import smoke_face_cleanup as head  # noqa: E402

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def main():
    from app.core import face_cleanup as fc

    head.EYE_X = 50 * head.MM
    glb, *_ = head.build_head()
    eyes = fc.measure_face(glb)["eyes"]
    rows = eyes.get("eyes") or []
    check(eyes.get("status") == "measured" and len(rows) == 2,
          f"100 mm: eyes located ({eyes.get('status')}, {eyes.get('reason', '')})")
    for r in rows:
        check(45 <= abs(r["centre_mm"][0]) <= 55, f"100 mm: {r['side']} centre x {r['centre_mm'][0]} mm (expected +-50)")
    _out, record = fc.clean_face(glb)
    check(record["eyes"].get("status") == "applied", f"100 mm: eye cleanup {record['eyes'].get('status')}")

    head.EYE_X = 60 * head.MM
    glb, *_ = head.build_head()
    eyes = fc.measure_face(glb)["eyes"]
    check(eyes.get("status") == "skipped" and re.fullmatch(r"eye separation 12\d mm is not a face", eyes.get("reason") or ""),
          f"120 mm: refused ({eyes.get('status')}: {eyes.get('reason')})")

    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        sys.exit(1)
    print("PASS: eye-separation gate admits 100 mm lash paint, still refuses 120 mm")


if __name__ == "__main__":
    main()
