#!/usr/bin/env python3
"""Smoke: the face cleanup finds the eyes of a HAIRED head — frame from the face, not from the head's vertex mean
(``face_cleanup._locate_eyes`` version 3; Task 6 fix 1 of the plan "hair from the body mesh", 2026-11-12).

Usage: ./.venv/bin/python scripts/smoke_face_cleanup_haired.py

No world, no server, no real meshes. The synthetic head of ``smoke_face_cleanup.py`` (sphere R = 0.055 units at
y = 0.42, 1 mm = 0.975 / 1700 units, so R = 95.9 mm; lash paint ellipses 22 x 7 mm at x = +-34.9 mm, y = 0.415;
lash ridge and eye opening as there) gets what a haired base body brings, one mechanism per fixture, each mirroring
a refusal measured on the clone's haired bases (Task 6 acceptance):

- FEET: legs = two planes z = +-0.03 units (x -0.06..0.06, y BOTTOM + 0.03 .. -0.30, 11 x 41 vertices each) and
  feet = two planes y = BOTTOM and BOTTOM + 0.02 (x 11 values, z -0.03..+0.12 in 16 values: 352 vertices, mean
  z +0.045). The feet band (bottom 3 % = 0.02925 units) holds the 352 foot vertices and the torso box's 4 bottom
  corners (mean z 0): mean z 0.045 * 352 / 356 = 0.04449 units = 77.6 mm; the shin band (8-12 %) holds only leg
  rows, mean z 0. Lead 77.6 mm >= FOOT_FRONT_MM 20 -> front +1; the feet mirrored (z -0.12..+0.03) -> -1; the plain
  fixture (4 corners in the feet band, < 20 vertices) -> 0, the paint majority decides as before.
- F1 DARK BACK HAIR (Kai): the whole back hemisphere painted dark (40, 28, 20) — luminance 0.12 < 0.25. In the
  eye band (45-70 % of the head segment, 62 mm high) the back half carries far more dark vertices than the two lash
  ellipses, so version 2 turned the head around (front -z) and took the back band for the eyes: per side x spans
  ~0..95 mm, p3..p97 ~ 89 mm > 2 * 32 -> "<side> eye paint NN mm wide is not an eye". Version 3: front +1 from the
  feet; the back hair lies 96..192 mm behind the nose tip, outside EYE_DEPTH_MM 60.
- F2 SIDEBURNS (Kai): dark paint on the front hemisphere at 74 <= |x| <= 90 mm, |y - eye line| < 10 mm (the
  sphere is deep enough there: z = 61..33 mm, 35..63 mm behind the nose tip, so the LATERAL window does the work
  here; on Kai's real head the sideburns lie 70-100 mm deep and the depth window does). Version 2 (front +1): the
  left cluster holds the left ellipse (12.9..56.9 mm) and the left sideburn (74..90 mm, grazing the sphere, so
  dense in vertices) -> p97 near 88, p3 near 15 -> wider than 64 mm -> "left eye paint NN mm wide is not an eye".
  Version 3: |x - mid| < EYE_LATERAL_MM 72 drops the sideburns (74 > 72).
- F3 ASYMMETRIC HAIR (Kira): a blonde curtain — two planes z = -60 and +20 mm over x 100..160 mm, y 0.37..0.46
  units, 41 x 41 vertices each (3362, mean x 130 mm), luminance well above 0.25 (no paint). The head segment
  (y > 0.475 - 0.15 * 0.975 = 0.32875) holds the sphere's 161 x 320 = 51520 vertices, the 4 torso top corners and
  the curtain: head-mean x = 3362 * 130 / 54886 = 7.96 mm. The eye medians are symmetric about 0 (the paint split
  at 7.96 mm cuts no ellipse: the left one starts at 12.9 mm), so version 2 reads |(xL - 7.96) + (xR - 7.96)| =
  15.9 mm > 10 -> "eye paint is not symmetric about the head (16 mm)". Version 3: the mid-plane is the median x of
  the nose cap (the sphere's front, symmetric) -> 0 (|mid| < 1 mm), the eyes are symmetric.
- F4 ALL OF IT: every eye found as on the plain head (|centre x| 30..40 mm, half width 18..26 mm, front +z) and the
  ridge folded (eye cleanup ``applied``).

The proof that each fixture fails on the old code loads ``app/core/face_cleanup.py`` of 16fd3d2a from git.
"""
import importlib.util
import io
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

import smoke_face_cleanup as head  # noqa: E402

OLD_COMMIT = "16fd3d2a"
FAILS = []
DARK_HAIR = (40, 28, 20)
BLONDE = (205, 175, 120)
CURTAIN_UV = (0.47, 0.03)
BODY_UV = (0.5, 0.95)


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def grid(xs, ys, zs, axis):
    """A planar quad grid: ``axis`` 'z' = plane at zs[0] over xs x ys, 'y' = plane at ys[0] over xs x zs."""
    if axis == "z":
        X, Y = np.meshgrid(xs, ys, indexing="ij")
        P = np.stack([X.ravel(), Y.ravel(), np.full(X.size, zs[0])], 1)
        n0, n1 = len(xs), len(ys)
    else:
        X, Z = np.meshgrid(xs, zs, indexing="ij")
        P = np.stack([X.ravel(), np.full(X.size, ys[0]), Z.ravel()], 1)
        n0, n1 = len(xs), len(zs)
    F = []
    for i in range(n0 - 1):
        for j in range(n1 - 1):
            a, b, c, d = i * n1 + j, i * n1 + j + 1, (i + 1) * n1 + j, (i + 1) * n1 + j + 1
            F += [(a, c, b), (b, c, d)]
    return P, np.array(F, np.int64)


def texture(back_hair, sideburns, curtain):
    from PIL import Image
    img = np.array(Image.open(io.BytesIO(head.texture_png(True))).convert("RGB"))
    size = img.shape[0]
    cols = (np.arange(size) + 0.5) / size
    rows = (np.arange(size) + 0.5) / size
    if back_hair:
        img[:, cols >= 0.55] = DARK_HAIR
    if sideburns:
        xs = (cols - 0.25) * head.R / 0.2
        ys = head.HEAD_Y - (rows - 0.5) * head.R / 0.2
        sel_x = (np.abs(xs) >= 74 * head.MM) & (np.abs(xs) <= 90 * head.MM) & (cols >= 0.05) & (cols <= 0.45)
        sel_y = np.abs(ys - head.EYE_Y) < 10 * head.MM
        img[np.ix_(sel_y, sel_x)] = DARK_HAIR
    if curtain:
        img[(rows < 0.06)[:, None] & ((cols >= 0.46) & (cols <= 0.48))[None, :]] = BLONDE
    out = io.BytesIO()
    Image.fromarray(img).save(out, "PNG")
    return out.getvalue()


def build(feet=1, back_hair=False, sideburns=False, curtain=False):
    """The canonical head (+ ``feet``: +1 toes toward +z, -1 toward -z, 0 none) with the hair parts asked for."""
    _glb, P, F, U, ridge, opening = head.build_head()
    parts = []
    if feet:
        legs_y = np.linspace(head.BOTTOM + 0.03, -0.30, 41)
        legs_x = np.linspace(-0.06, 0.06, 11)
        for z in (-0.03, 0.03):
            parts.append(grid(legs_x, legs_y, [z], "z") + (BODY_UV,))
        foot_z = np.linspace(-0.03, 0.12, 16) * feet
        for y in (head.BOTTOM, head.BOTTOM + 0.02):
            parts.append(grid(legs_x, [y], foot_z, "y") + (BODY_UV,))
    if curtain:
        cx = np.linspace(100 * head.MM, 160 * head.MM, 41)
        cy = np.linspace(0.37, 0.46, 41)
        for z in (-60 * head.MM, 20 * head.MM):
            parts.append(grid(cx, cy, [z], "z") + (CURTAIN_UV,))
    for Pp, Fp, uv in parts:
        F = np.vstack([F, Fp + len(P)])
        P = np.vstack([P, Pp])
        U = np.vstack([U, np.tile(uv, (len(Pp), 1))])
    N = P - np.array([0, head.HEAD_Y, 0])
    N /= np.maximum(np.linalg.norm(N, axis=1), 1e-9)[:, None]
    return head.pack(P, N, U, F, texture(back_hair, sideburns, curtain)), ridge


def arrays(glb):
    from app.core import face_cleanup as fc
    from app.core.glb_mesh import _parse
    parsed = _parse(glb, "Source")
    primitives, P, F, U, _N, _off = fc._body(parsed)
    mm = (P[:, 1].max() - P[:, 1].min()) / fc.REFERENCE_HEIGHT_MM
    _i, tex, _m = fc._texture(parsed, primitives[0])
    lum = (fc._sample(tex[..., :3], U).astype(np.float64) @ fc._LUMA) / 255.0
    return P, lum, mm


def old_module(tmp):
    source = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_COMMIT}:app/core/face_cleanup.py"],
                            capture_output=True, text=True, check=True).stdout
    path = Path(tmp) / "old_face_cleanup.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location("old_face_cleanup", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def located(fc, glb, label):
    P, lum, mm = arrays(glb)
    eyes, reason, frame = fc._locate_eyes(P, lum, mm)
    check(eyes is not None, f"{label}: eyes located ({reason or 'ok'})")
    if eyes is None:
        return
    check(frame["front"] == 1, f"{label}: front +z ({frame['front']})")
    check(abs(frame["centre"][0] / mm) < 1.0, f"{label}: face mid-plane x {frame['centre'][0] / mm:.2f} mm (expected 0)")
    for e in eyes:
        cx = (e["centre"][0] - frame["centre"][0]) / mm
        hw = e["half_width"] / mm
        check(30 <= abs(cx) <= 40 and 18 <= hw <= 26, f"{label}: {e['side']} eye x {cx:+.1f} mm, half width {hw:.1f} mm")


def main():
    from app.core import face_cleanup as fc

    print("[1] front from the feet")
    for feet, want in ((1, 1), (-1, -1)):
        P, _lum, mm = arrays(build(feet=feet)[0])
        got = fc._front_from_feet(P, mm)
        check(got == want, f"feet {feet:+d}: front {got} (expected {want})")
    P, _lum, mm = arrays(head.build_head()[0])
    check(fc._front_from_feet(P, mm) == 0, "no feet: 0 (the paint decides)")

    fixtures = {"F1 back hair": build(back_hair=True)[0], "F2 sideburns": build(sideburns=True)[0],
                "F3 curtain": build(curtain=True)[0]}
    combined, ridge = build(back_hair=True, sideburns=True, curtain=True)

    print("[2] version 3 locates the eyes")
    for label, glb in fixtures.items():
        located(fc, glb, label)
    located(fc, combined, "F4 all")
    _out, record = fc.clean_face(combined)
    check(record["eyes"]["status"] == "applied" and record["eyes"]["front_axis"] == "+z",
          f"F4: eye cleanup {record['eyes']['status']} ({record['eyes'].get('reason', '')}), front {record['eyes'].get('front_axis')}")
    moved = sum(int(e.get("moved_vertices") or 0) for e in record["eyes"].get("eyes") or [])
    check(moved >= int(ridge.sum()) - 10, f"F4: {moved} vertices folded (ridge {int(ridge.sum())})")

    print(f"[3] the same fixtures on {OLD_COMMIT} (version 2)")
    with tempfile.TemporaryDirectory() as tmp:
        old = old_module(tmp)
        P, lum, mm = arrays(fixtures["F1 back hair"])
        eyes, reason, frame = old._locate_eyes(P, lum, mm)
        check(eyes is None and frame.get("front") == -1 and re.fullmatch(r"(left|right) eye paint \d+ mm wide is not an eye", reason),
              f"F1 old: front {frame.get('front')}, {reason!r}")
        P, lum, mm = arrays(fixtures["F2 sideburns"])
        eyes, reason, frame = old._locate_eyes(P, lum, mm)
        width = re.fullmatch(r"left eye paint (\d+) mm wide is not an eye", reason or "")
        check(eyes is None and width is not None and int(width.group(1)) > 64, f"F2 old: {reason!r}")
        P, lum, mm = arrays(fixtures["F3 curtain"])
        eyes, reason, frame = old._locate_eyes(P, lum, mm)
        check(eyes is None and reason == "eye paint is not symmetric about the head (16 mm)", f"F3 old: {reason!r}")

    print()
    print("FAILED" if FAILS else "ALL OK", f"({len(FAILS)} failures)")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
