#!/usr/bin/env python3
"""The hair fit's bib gate counts a sheet that bridges the throat, not strands either side of it
(``garment_fit.bib_area_cm2``, ``BIB_FREE_THROAT_M``).

Usage: ./.venv/bin/python scripts/smoke_hair_bib_gate.py

No world, no server, no storage: every mesh is built here. Expectations derived by hand.

Body (metres, faces +z): Head-weighted rings of radius 0.08 at y 1.45..1.70 -> chin 1.45; the rings are symmetric
about x = 0 -> head centre line x 0. A neck cylinder of radius 0.05 at y 1.25..1.44 with 48 angles (90 deg is one of
them) -> the neck's front surface within |x| < 0.04 is z 0.05 in every 1 cm bin. The bib box: centroid
1.29 < y < 1.45, |x| < 0.06, z > 0.05 - 0.01 = 0.04. Every plate below is flat at z 0.07 (in front of the neck), so
the old metric counts its whole area. Plates are axis-aligned rectangles, area = width x height exactly.

[1] One plate across the centre line, x [-0.025, 0.025], y [1.37, 1.42]: a triangle spans x = 0 in every row ->
    nothing free -> 5 x 5 = 25 cm^2 (old 25 too).
[2] Two strands either side of the throat, x [-0.055, -0.03] and [0.03, 0.055], y [1.30, 1.42] (2.5 x 12 cm each):
    old 2 x 30 = 60 cm^2 > 50 (refused); every row leaves the throat free from -0.03 to 0.03 = 0.06 >= 0.03 -> 0.
[3] A bridge with a slit, x [-0.05, -0.01] and [0.01, 0.05], y [1.37, 1.42]: free 0.02 < 0.03 -> counted,
    2 x 4 x 5 = 40 cm^2 (old 40).
[4] Just above the threshold, x [-0.05, -0.016] and [0.016, 0.05], y [1.37, 1.42]: free 0.032 >= 0.03 -> 0
    (old 2 x 3.4 x 5 = 34).
[5] One strand on one side only, x [0.01, 0.035], y [1.30, 1.42]: the side without garment is free to the box edge
    -0.06 -> free 0.07 -> 0 (old 2.5 x 12 = 30).
[6] Never more than the box: [1] + [2] together (rows 1.37..1.42 hold the crossing plate, so the strands' triangles
    in those rows count with it) -> 25 <= new <= 25 + 60 = old.
[7] Fails on the old code: ``bib_area_cm2`` of commit 863a2726 (``git show``) gives [2] 60 +- 0.5 (> 50, the gate
    refuses strands framing the neck) and [5] 30 +- 0.5.

Real meshes (2026-11-11, ~/claude-out/hair/lirien, not part of this check): Lirien's edit-chain hair 187.96 -> 0.00
(two front strands at 2.7..6 cm either side, throat free 6.2..10.7 cm in every row); the spike's reference bib
job_07af5447 (a sheet across the throat) 208.51 -> 198.77, still refused; a Kira edit-chain hair with one front strand
156.26 -> 0.00.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

PIN = "863a2726"
FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def neck_body():
    from app.core.glb_mesh import BodyMesh
    angles = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    head = np.array([[0.08 * np.cos(a), y, 0.08 * np.sin(a)] for y in np.linspace(1.45, 1.70, 26) for a in angles])
    neck = np.array([[0.05 * np.cos(a), y, 0.05 * np.sin(a)] for y in np.arange(1.25, 1.445, 0.005) for a in angles])
    P = np.concatenate([head, neck])
    n = len(P)
    J = np.zeros((n, 4), np.int64)
    J[:, 0] = np.where(np.arange(n) < len(head), 2, 1)
    W = np.zeros((n, 4))
    W[:, 0] = 1.0
    uv = np.stack([(np.arange(n) % 1000) / 1000.0, (np.arange(n) // 1000) / 1000.0], 1)
    return BodyMesh(positions=P, faces=np.zeros((0, 3), np.int64), uvs=uv, joints=J, weights=W,
                    joint_names=["mixamorig:Hips", "mixamorig:Spine2", "mixamorig:Head"])


def plate(x0, x1, y0, y1, z=0.07, n=10):
    xs, ys = np.linspace(x0, x1, n + 1), np.linspace(y0, y1, n + 1)
    P = np.array([[x, y, z] for y in ys for x in xs])
    F = []
    for i in range(n):
        for j in range(n):
            a, b, c, d = i * (n + 1) + j, i * (n + 1) + j + 1, (i + 1) * (n + 1) + j + 1, (i + 1) * (n + 1) + j
            F += [(a, b, c), (a, c, d)]
    return P, np.array(F)


def merge(*parts):
    P, F, off = [], [], 0
    for p, f in parts:
        P.append(p)
        F.append(f + off)
        off += len(p)
    return np.concatenate(P), np.concatenate(F)


def old_bib():
    """``bib_area_cm2`` as of PIN, run against the current module's helpers."""
    from app.core import garment_fit as gf
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{PIN}:app/core/garment_fit.py"],
                         check=True, capture_output=True, text=True).stdout
    start = src.index("def bib_area_cm2")
    end = src.index("\ndef ", start + 10)
    ns = dict(vars(gf))
    exec(compile(src[start:end], f"garment_fit@{PIN}", "exec"), ns)
    return ns["bib_area_cm2"]


def main():
    from app.core import garment_fit as gf
    br = neck_body()
    check(abs(gf.chin_height(br) - 1.45) < 1e-9 and abs(gf._head_centre_x(br)) < 1e-9,
          "body: chin 1.45, head centre line x 0")
    check(gf.BIB_FREE_THROAT_M == 0.03, f"BIB_FREE_THROAT_M 0.03 (got {gf.BIB_FREE_THROAT_M})")
    across = plate(-0.025, 0.025, 1.37, 1.42)
    strands = merge(plate(-0.055, -0.03, 1.30, 1.42), plate(0.03, 0.055, 1.30, 1.42))
    slit = merge(plate(-0.05, -0.01, 1.37, 1.42), plate(0.01, 0.05, 1.37, 1.42))
    wide = merge(plate(-0.05, -0.016, 1.37, 1.42), plate(0.016, 0.05, 1.37, 1.42))
    one = plate(0.01, 0.035, 1.30, 1.42)
    both = merge(across, strands)
    new = {name: gf.bib_area_cm2(*mesh, br) for name, mesh in
           (("across", across), ("strands", strands), ("slit", slit), ("wide", wide), ("one", one), ("both", both))}
    check(abs(new["across"] - 25) <= 0.5, f"[1] plate across the centre line 25 cm^2 (got {new['across']:.2f})")
    check(new["strands"] == 0.0, f"[2] strands either side of the throat 0 (got {new['strands']:.2f})")
    check(abs(new["slit"] - 40) <= 0.5, f"[3] bridge with a 2 cm slit 40 cm^2 (got {new['slit']:.2f})")
    check(new["wide"] == 0.0, f"[4] 3.2 cm free throat 0 (got {new['wide']:.2f})")
    check(new["one"] == 0.0, f"[5] one strand on one side 0 (got {new['one']:.2f})")
    check(25 - 0.5 <= new["both"] <= 85 + 0.5, f"[6] crossing plate + strands within [25, 85] (got {new['both']:.2f})")
    old = old_bib()
    o_strands, o_one = old(*strands, br), old(*one, br)
    check(abs(o_strands - 60) <= 0.5 and o_strands > gf.GATES["bib_cm2"][1],
          f"[7] {PIN}: strands 60 cm^2 > 50, refused (got {o_strands:.2f})")
    check(abs(o_one - 30) <= 0.5, f"[7] {PIN}: one strand 30 cm^2 (got {o_one:.2f})")
    check(abs(old(*across, br) - new["across"]) <= 1e-9 and abs(old(*slit, br) - new["slit"]) <= 1e-9,
          f"[7] {PIN}: a bridge measures the same before and after")
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        sys.exit(1)
    print("\nALL OK")


if __name__ == "__main__":
    main()
