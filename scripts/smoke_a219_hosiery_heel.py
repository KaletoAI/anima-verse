"""A219 — see-through shell colour, the closed limb tube, the shoe's heel taper.

Usage: ./.venv/bin/python scripts/smoke_a219_hosiery_heel.py   (no server, no world DB, no storage)

Expected values derived by hand:
[S1] ``garment_shell.unmix_backdrop`` on a lace: a 60x60 RGB image, backdrop (200, 200, 200), a ghost mask = the
     square rows/cols 10..49 (40x40). Inside, 2-px column stripes: cols with (j // 2) even are fabric (10, 10, 10),
     the others a 50 % mix with the backdrop: 10 + 0.5 * (200 - 10) = 105. Inner pixels (mask eroded 3 px) = rows/cols
     13..46 = 34 x 34 = 1156; F = median of the darkest 10 % = 10, bg = 200 (outside the 6-px dilation); mixed columns
     among 13..46 (j // 2 odd): 14, 15, 18, 19, ..., 42, 43, 46 and 13 -> 17 of the 34 columns -> mixed_share
     578 / 1156 = 0.5; every mixed pixel lies within 4 px of a fabric column -> interleave 1.0 >= 0.4 -> see-through;
     a mixed pixel becomes 105 - 0.5 * 190 = 10; a fabric pixel stays 10; the backdrop outside stays 200.
[S2] the same square, opaque: its left half (cols 10..29) fabric 10, its right half (cols 30..49) 105 (a smooth
     highlight). Inner mixed = cols 30..46 = 17 cols -> share 17 / 34 = 0.5; within 4 px of fabric (col 29): cols
     30..33 = 4 of 17 -> interleave 4 / 17 = 0.235 < 0.4 -> NOT see-through, the image unchanged (105 stays 105).
[S3] ``garment_shell.ring_closed``: a limb of 10 rings (RING_BIN_M 0.004, y = 0.003 + 0.004 i: mid-ring, no float
     edge), per ring 4 front
     head-on points, 4 back head-on points and 1 side point. (a) front members in every ring, back members in rings
     4..9 -> both worn 4..9 (the median of 5 keeps 4: [0,0,1,1,1]); below ring 4 the front still shows the ring worn
     -> closed down to ring 0: all 90 points True (the side point of ring 2 included). (b) front members in every
     ring, back members in rings 0..5 -> both 0..5 (ring 6's window [1,1,0,0,0] -> 0); ABOVE the run nothing is
     carried -> rings 0..5 closed (54 points), rings 6..9 not (36). (c) off the limb: False.
[S4] ``footwear_fit.width_taper``: stations x = 0..5 (raw), k 1, width factor 1.25, ball at x 4, clearance 0.002;
     insole widths 0.05, 0.06 x5; foot widths NaN, 0.050, 0.056, 0.0656, 0.04, NaN. Needs: x1 (0.054)/0.06 = 0.9
     -> 1.0; x2 0.060/0.06 = 1.0; x3 0.0696/0.06 = 1.16; x4, x5 at / past the ball -> 1.25; x0 unmeasured -> the
     first measured 1.0. Running max [1, 1, 1, 1.16, 1.25, 1.25] / 1.25 = shares [0.8, 0.8, 0.8, 0.928, 1, 1];
     kept: the stations behind the ball and the first at it -> x_raw [0, 1, 2, 3, 4], share [0.8, 0.8, 0.8, 0.928,
     1.0], min_factor 1.0. ``width_taper_at`` x 3.5 -> 0.964, x 9 -> 1.0, x -1 -> 0.8. A foot that needs the full
     factor everywhere (foot 0.1 at every station) -> None; width factor 1.0 -> None.
[S5] ``width_taper_map``: a point (1, 0.03, 0.01) -> z 0.01 * 0.8 = 0.008, x / y unchanged; (9, 0, 0.01) -> 0.01;
     a normal (0, 0, 1) at x 1 (the shares on both sides 0.8: slope 0) -> (0, 0, 1) renormalised.
[S6] versions: ``garment_shell.SHELL_VERSION`` 5, ``footwear_fit.FOOTWEAR_FIT_VERSION`` 20. Fails on the old code:
     commit baac1102c has neither ``ring_closed`` / ``unmix_backdrop`` nor ``width_taper`` (``git show``).
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402

from app.core import footwear_fit as ff  # noqa: E402
from app.core import garment_shell as gs  # noqa: E402

fails = []


def check(name, got, want, tol=None):
    ok = (abs(got - want) <= tol) if tol is not None else (got == want)
    print(("OK   " if ok else "FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(name)


print("[S1] lace on the backdrop")
img = np.full((60, 60, 3), 200.0)
mask = np.zeros((60, 60), bool)
mask[10:50, 10:50] = True
cols = np.arange(60)
lace = np.where((cols // 2) % 2 == 0, 10.0, 105.0)
img[10:50, 10:50] = lace[10:50][None, :, None]
out, info = gs.unmix_backdrop(img, mask)
check("[S1] see-through", info["see_through"], True)
check("[S1] mixed_share 0.5", info["mixed_share"], 0.5)
check("[S1] interleave 1.0", info["interleave"], 1.0)
check("[S1] mixed pixel -> 10", float(out[20, 14, 0]), 10.0, 1e-6)
check("[S1] fabric pixel stays 10", float(out[20, 12, 0]), 10.0, 1e-6)
check("[S1] backdrop stays 200", float(out[2, 2, 0]), 200.0, 1e-6)

print("[S2] an opaque piece with a smooth highlight")
img2 = np.full((60, 60, 3), 200.0)
img2[10:50, 10:30] = 10.0
img2[10:50, 30:50] = 105.0
out2, info2 = gs.unmix_backdrop(img2, mask)
check("[S2] not see-through", info2["see_through"], False)
check("[S2] interleave 4/17", info2["interleave"], round(4 / 17, 3))
check("[S2] highlight unchanged", float(out2[20, 40, 0]), 105.0, 1e-6)

print("[S3] the closed limb tube")
ys, head_f, head_b, ring = [], [], [], []
for i in range(10):
    for kind in ["f"] * 4 + ["b"] * 4 + ["s"]:
        ys.append(0.003 + 0.004 * i)
        head_f.append(kind == "f")
        head_b.append(kind == "b")
        ring.append(i)
y = np.array(ys)
head_f, head_b, ring = np.array(head_f), np.array(head_b), np.array(ring)
limb = np.ones(len(y), bool)
memb_f = head_f.copy()
closed = gs.ring_closed(y, limb, head_f, memb_f, head_b, head_b & (ring >= 4))
check("[S3a] back worn 4..9: all closed (down to the foot)", int(closed.sum()), 90)
check("[S3a] side point of ring 2", bool(closed[(ring == 2) & ~head_f & ~head_b][0]), True)
closed_b = gs.ring_closed(y, limb, head_f, memb_f, head_b, head_b & (ring <= 5))
check("[S3b] back worn 0..5: 54 closed", int(closed_b.sum()), 54)
check("[S3b] rings 6..9 open", bool(closed_b[ring >= 6].any()), False)
check("[S3c] off the limb", bool(gs.ring_closed(y, np.zeros(len(y), bool), head_f, memb_f, head_b, head_b).any()),
      False)

print("[S4] the heel taper")
st = np.arange(6, dtype=float)
iw = np.array([0.05, 0.06, 0.06, 0.06, 0.06, 0.06])
fw = np.array([np.nan, 0.050, 0.056, 0.0656, 0.04, np.nan])
tp = ff.width_taper(st, iw, fw, 1.0, 1.25, 4.0, 0.002)
check("[S4] x_raw", tp["x_raw"], [0.0, 1.0, 2.0, 3.0, 4.0])
check("[S4] shares", tp["share"], [0.8, 0.8, 0.8, 0.928, 1.0])
check("[S4] min_factor", tp["min_factor"], 1.0)
check("[S4] at 3.5", float(ff.width_taper_at(np.array([3.5]), tp)[0]), 0.964, 1e-9)
check("[S4] in front", float(ff.width_taper_at(np.array([9.0]), tp)[0]), 1.0, 1e-12)
check("[S4] behind", float(ff.width_taper_at(np.array([-1.0]), tp)[0]), 0.8, 1e-12)
check("[S4] full need -> None", ff.width_taper(st, iw, np.full(6, 0.1), 1.0, 1.25, 4.0, 0.002), None)
check("[S4] factor 1 -> None", ff.width_taper(st, iw, fw, 1.0, 1.0, 4.0, 0.002), None)

print("[S5] the taper map")
Q = np.array([[1.0, 0.03, 0.01], [9.0, 0.0, 0.01]])
Qt, nt = ff.width_taper_map(Q, tp, np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]]))
check("[S5] z at x 1", float(Qt[0, 2]), 0.008, 1e-12)
check("[S5] x, y kept", (float(Qt[0, 0]), float(Qt[0, 1])), (1.0, 0.03))
check("[S5] z in front", float(Qt[1, 2]), 0.01, 1e-12)
check("[S5] normal at x 1", [round(float(v), 9) for v in nt[0]], [0.0, 0.0, 1.0])

print("[S6] versions and the old code")
check("[S6] SHELL_VERSION", gs.SHELL_VERSION, 5)
check("[S6] FOOTWEAR_FIT_VERSION", ff.FOOTWEAR_FIT_VERSION, 20)
old_shell = subprocess.run(["git", "show", "baac1102c:app/core/garment_shell.py"], cwd=ROOT, capture_output=True,
                           text=True).stdout
old_fit = subprocess.run(["git", "show", "baac1102c:app/core/footwear_fit.py"], cwd=ROOT, capture_output=True,
                         text=True).stdout
check("[S6] old shell code read", len(old_shell) > 1000, True)
check("[S6] baac1102c: no ring_closed / unmix_backdrop",
      "def ring_closed" in old_shell or "def unmix_backdrop" in old_shell, False)
check("[S6] baac1102c: no width_taper", "def width_taper" in old_fit, False)

print("ALL OK" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
