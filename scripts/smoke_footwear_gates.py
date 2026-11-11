#!/usr/bin/env python3
"""Footwear, task 3: the pure gates of the empty shoe image and the shoe mesh
(plan ``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md`` Task 3; spec
``docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md`` § 5.2, § 5.3).

Usage:
    ./.venv/bin/python scripts/smoke_footwear_gates.py

Pure numpy on synthetic masks and meshes — no world, no storage, no hub, no
GPU. Every expectation is derived by hand below. Masks are 200 x 400 (H x W),
row 0 at the top; a "rectangle L x h" spans L columns and h rows, its bottom
row is the shoe's ground.

Column heights (empty_gate): per column of the largest component, ground row
(its last row) - the column's top row + 1. Ends = round(0.15 * L) columns at
each end, middle = columns [round(0.35 L), round(0.65 L)) from the left end.

[G1] One shoe. Rectangle 300 x 100 (cols [50, 350), rows [80, 180)) + a speck
     30 x 50 = 1500 px (5 % of 30000) at cols [10, 40), rows [150, 200) —
     separate, not touching the top row.
     single_share = 30000 / (30000 + 1500) = 0.9524 < 0.98 -> refused, reason
     "single_share".
[G2] Leg. The rectangle of G1 (no speck) with the heel 40 px taller at the
     right 15 % (L = 300 -> 45 columns, cols [305, 350), rows [40, 180)) and a
     30-px strip from the throat to the top edge (cols [185, 215) = offsets
     [135, 165) inside the middle [105, 195), rows [0, 80)).
     Ends: left max height 100, right 140 -> heel = right, counter = 140.
     Middle max height = 179 - 0 + 1 = 180; 180 - 140 = 40 > 0.12 * 300 = 36
     -> leg True, reason "leg" (LEG_EXCESS_SHARE 0.12 since the boots round's
     P1, see [G9]).
     Without the strip: middle 100 - 140 = -40 -> leg False.
     The strip disconnected (rows [0, 60), shoe = the plain rectangle): it is a
     component touching the top row, 30 px wide < 0.25 * 300 = 75 -> leg True.
[G3] Side view. Rectangle 300 x 100 -> aspect 300 / 100 = 3.0 > 2.6 -> refused,
     reason "aspect"; rectangle 300 x 180 (rows [10, 190)) -> aspect
     300 / 180 = 1.667, single share 1.0, no leg (every column 180 high,
     excess 0) -> ok, reasons [].
[G9] A men's Derby (boots round P1 calibration, 2026-11-11; the real numbers in
     footwear_gates.EMPTY_GATES / LEG_EXCESS_SHARE): rectangle 300 x 105 (rows
     [75, 180)) with the laced throat 15 px taller over the middle (cols
     [185, 215), rows [60, 75)): the bbox is 120 high -> aspect 300 / 120 =
     2.5, inside 1.1..2.6 (the Derby deliveries read 2.43 / 2.45); counter =
     105 (both ends 105), middle max 120, excess 15 = 0.05 L <= 0.12 L -> no
     leg, ok, reasons []. The same throat rising to row 0 (cols [185, 215),
     rows [0, 75)): middle max 180, excess 75 = 0.25 L > 36 -> leg. Rectangle
     300 x 110 -> aspect 2.727 > 2.6 -> refused.
[G4] silhouette_iou (both cropped to their bbox, resampled to 256 x 256, max
     over the horizontal flip of b):
     - rectangle 300 x 100 vs its copy shifted by 30 px (10 % of its width):
       identical crops -> 1.0.
     - right trapezoid (row r of 100 is 201 + r px wide from the left edge:
       top 201, bottom 300; area 100 * 200 + 5050 = 25050) vs its mirror:
       the flip of b gives the same crop -> 1.0 (without the flip the overlap
       per row is 2 * (201 + r) - 300 = 102 + 2r, sum 20100, union
       50100 - 20100 = 30000 -> 0.67, so the 1.0 really comes from the flip).
     - that trapezoid vs the rectangle 300 x 100: same bbox, intersection =
       the trapezoid -> 25050 / 30000 = 0.835 (continuous 250/300 = 0.8333;
       +-0.01 for the resampling).
[G5] component_shares: unit cube (area 6), a cube scaled 0.5 inside its bbox
     (area 6 * 0.25 = 1.5) and a cube scaled sqrt(0.1) far away (area 0.6):
     largest = 6 / 8.1 = 0.7407, enclosed = (6 + 1.5) / 8.1 = 0.9259.
[G6] iou_below_topline = envelope_iou: both shoes on a length-normalised,
     ground-anchored grid; the item kept only at or below the EMPTY shoe's
     own top edge per column; IoU with the empty shoe, max over the item's
     flip. Shapes (ground = row 179, L = 300, cols [50, 350)):
     pump P  = vamp rows [140, 180) x cols [50, 350) (40 high, 12000 px) +
               heel counter rows [40, 180) x cols [305, 350) (45 cols, 140
               high, 4500 px more) -> 16500 px; ends: left 40, right 140 ->
               counter 140; middle 40 -> no leg; aspect 300 / 140 = 2.143.
     item I  = P + a foot filling the throat rows [60, 140) x cols [110, 305)
               (195 x 80 = 15600) + a leg rows [0, 60) x cols [250, 300)
               (50 x 60 = 3000), mirrored (toe the other way).
     [G6a] empty = P: per column the empty top is 40 rows over [50, 305) and
           140 over [305, 350); below it the (flipped) item holds exactly
           the vamp and the counter — the foot (rows < 140 there) and the
           leg drop out -> I' = P -> IoU 16500 / 16500 = 1.0 (+-0.01 for the
           256-column resampling) -> ok.
           (The old cut at the counter height, 140 / 300 of each length,
           kept the foot and the leg's rows [40, 60): 16500 / (16500 + 15600
           + 1000) = 0.4985 — the 0.556 / 0.629 of the acceptance run.)
     [G6b] empty = P + a toe cap rows [120, 140) x cols [50, 110) (60 x 20 =
           1200; left end now 60 high, counter still 140): the item has no
           cap, so I' = P and the cap is empty-only -> 16500 / 17700 =
           0.9322 (+-0.01) -> ok.
     [G6c] empty = a filled block rows [40, 180) x cols [50, 350) (the edit
           painted the throat shut; 42000 px, every column 140 high -> no
           leg, aspect 2.143): the envelope is 140 everywhere, so the item
           keeps P + the foot + the leg's rows [40, 60) = 16500 + 15600 +
           1000 = 33100, all inside the block -> 33100 / 42000 = 0.7881
           (+-0.01) < 0.85 -> refused for iou_below_topline.
[G7] shoe_frame + side_silhouette. Box length 0.26 (X) x height 0.08 (Y) x
     width 0.10 (Z): up = +Y, x = the footprint PCA = +-X, length 0.26.
     Adding a heel block x [0.22, 0.26] up to 0.12 makes the +X end taller ->
     x_axis = (-1, 0, 0), z_axis = x x up = (0, 0, -1), origin = (0.26, 0, 0).
     The box rotated 30 deg about Y -> |x_axis . R e_x| = 1, length 0.26.
     side_silhouette(box, size=256): scale 255 / 0.26 -> 256 columns, height
     0.08 * 255 / 0.26 = 78.5 px -> 78..80 rows, the bbox filled (>= 0.99);
     IoU against a 325 x 100 rectangle matte (same aspect 3.25) >= 0.99.
[G8] Gate tables: EMPTY_GATES single_share ("min", 0.98), aspect ("range",
     (1.1, 2.6)), iou_below_topline ("min", 0.85); MESH_GATES component_share
     ("min", 0.98), mesh_iou ("min", 0.75 — calibrated on the real Business Heels deliveries, 0.77–0.78 against
     their side-view cut-out; 0.80 before the P3 acceptance). check_gates refuses a missing value
     unless it is optional.
"""
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, cond, detail=None):
    print(("PASS " if cond else "FAIL ") + label + (f"  ({detail})" if detail is not None and str(detail) != "" else ""))
    if not cond:
        FAILS.append(label)


def near(a, b, tol):
    return a is not None and abs(float(a) - float(b)) <= tol


def canvas():
    return np.zeros((200, 400), bool)


def shoe(*, heel=False, strip=False, strip_rows=(0, 80)):
    m = canvas()
    m[80:180, 50:350] = True
    if heel:
        m[40:180, 305:350] = True
    if strip:
        m[strip_rows[0]:strip_rows[1], 185:215] = True
    return m


def box(lo, hi):
    """A closed box mesh (8 vertices, 12 triangles) between corners lo and hi."""
    lo = np.asarray(lo, float)
    hi = np.asarray(hi, float)
    P = np.array([[lo[0] if i & 1 == 0 else hi[0],
                   lo[1] if i & 2 == 0 else hi[1],
                   lo[2] if i & 4 == 0 else hi[2]] for i in range(8)])
    F = np.array([[0, 2, 1], [1, 2, 3], [4, 5, 6], [5, 7, 6],
                  [0, 1, 4], [1, 5, 4], [2, 6, 3], [3, 6, 7],
                  [0, 4, 2], [2, 4, 6], [1, 3, 5], [3, 7, 5]])
    return P, F


def merge(*meshes):
    Ps, Fs, off = [], [], 0
    for P, F in meshes:
        Ps.append(P)
        Fs.append(F + off)
        off += len(P)
    return np.concatenate(Ps), np.concatenate(Fs)


def main():
    from app.core import footwear_gates as fg
    from app.core.footwear_insole import ShoeFrame, shoe_frame

    # [G1]
    m = shoe()
    m[150:200, 10:40] = True
    r = fg.empty_gate(m)
    check("[G1] single_share = 0.9524", near(r["single_share"], 30000 / 31500, 1e-4), r["single_share"])
    check("[G1] refused for single_share", not r["ok"] and any(x.startswith("single_share") for x in r["reasons"]),
          r["reasons"])

    # [G2]
    r = fg.empty_gate(shoe(heel=True, strip=True))
    check("[G2] heel + strip in the throat -> leg", r["leg"] is True and not r["ok"]
          and any(x.startswith("leg") for x in r["reasons"]), r["reasons"])
    r = fg.empty_gate(shoe(heel=True))
    check("[G2] heel without strip -> no leg", r["leg"] is False, r)
    m = shoe()
    m[0:60, 185:215] = True
    r = fg.empty_gate(m)
    check("[G2] thin component at the top edge -> leg", r["leg"] is True, r)

    # [G3]
    r = fg.empty_gate(shoe())
    check("[G3] aspect 3.0 refused", near(r["aspect"], 3.0, 1e-9) and not r["ok"]
          and any(x.startswith("aspect") for x in r["reasons"]), r)
    m = canvas()
    m[10:190, 50:350] = True
    r = fg.empty_gate(m)
    check("[G3] aspect 1.667 ok", near(r["aspect"], 300 / 180, 1e-9) and r["ok"] and r["reasons"] == []
          and r["leg"] is False and r["iou_below_topline"] is None, r)

    # [G9]
    derby = np.zeros((200, 400), bool)
    derby[75:180, 50:350] = True
    throat = derby.copy()
    throat[60:75, 185:215] = True
    r = fg.empty_gate(throat)
    check("[G9] Derby 300 x 105 + 15 px throat: aspect 2.5, no leg, ok", near(r["aspect"], 2.5, 1e-9)
          and r["leg"] is False and r["ok"] and r["reasons"] == [], r)
    shin = derby.copy()
    shin[0:75, 185:215] = True
    r = fg.empty_gate(shin)
    check("[G9] the throat rising to the top edge (0.25 L) -> leg", r["leg"] is True and not r["ok"], r)
    low = np.zeros((200, 400), bool)
    low[70:180, 50:350] = True
    r = fg.empty_gate(low)
    check("[G9] 300 x 110 -> aspect 2.727 refused", near(r["aspect"], 300 / 110, 1e-9) and not r["ok"]
          and any(x.startswith("aspect") for x in r["reasons"]), r)

    # [G4]
    a = canvas()
    a[80:180, 50:350] = True
    b = canvas()
    b[80:180, 80:380] = True
    check("[G4] shifted copy -> 1.0", near(fg.silhouette_iou(a, b), 1.0, 1e-9), fg.silhouette_iou(a, b))
    trap = canvas()
    for r_ in range(100):
        trap[80 + r_, 50:50 + 201 + r_] = True
    check("[G4] trapezoid area 25050", int(trap.sum()) == 25050, int(trap.sum()))
    flipped = trap[:, ::-1].copy()
    check("[G4] trapezoid vs its mirror -> 1.0 (flip)", near(fg.silhouette_iou(trap, flipped), 1.0, 1e-9),
          fg.silhouette_iou(trap, flipped))
    v = fg.silhouette_iou(trap, a)
    check("[G4] trapezoid vs rectangle = 0.835", near(v, 25050 / 30000, 0.01), v)
    check("[G4] empty silhouette -> 0.0", fg.silhouette_iou(canvas(), a) == 0.0)

    # [G5]
    big = box((0, 0, 0), (1, 1, 1))
    inner = box((0.25, 0.25, 0.25), (0.75, 0.75, 0.75))
    s = math.sqrt(0.1)
    far = box((10, 10, 10), (10 + s, 10 + s, 10 + s))
    largest, enclosed = fg.component_shares(*merge(big, inner, far))
    check("[G5] largest share 0.7407", near(largest, 6 / 8.1, 1e-6), largest)
    check("[G5] enclosed share 0.9259", near(enclosed, 7.5 / 8.1, 1e-6), enclosed)
    check("[G5] single cube -> (1, 1)", fg.component_shares(*big) == (1.0, 1.0), fg.component_shares(*big))

    # [G6]
    pump = canvas()
    pump[140:180, 50:350] = True
    pump[40:180, 305:350] = True
    item = pump.copy()
    item[60:140, 110:305] = True
    item[0:60, 250:300] = True
    item = item[:, ::-1].copy()
    check("[G6] areas P 16500, I 35100", (int(pump.sum()), int(item.sum())) == (16500, 35100),
          (int(pump.sum()), int(item.sum())))
    r = fg.empty_gate(pump, item_matte=item)
    check("[G6a] aspect 2.143, no leg", near(r["aspect"], 300 / 140, 1e-9) and r["leg"] is False, r)
    check("[G6a] iou_below_topline = 1.0 (foot and leg drop out)", near(r["iou_below_topline"], 1.0, 0.01),
          r["iou_below_topline"])
    check("[G6a] ok", r["ok"] and r["reasons"] == [], r["reasons"])
    capped = pump.copy()
    capped[120:140, 50:110] = True
    r = fg.empty_gate(capped, item_matte=item)
    check("[G6b] toe cap only in the empty shoe -> 0.9322", near(r["iou_below_topline"], 16500 / 17700, 0.01),
          r["iou_below_topline"])
    check("[G6b] ok", r["ok"] and r["leg"] is False, r["reasons"])
    block = canvas()
    block[40:180, 50:350] = True
    r = fg.empty_gate(block, item_matte=item)
    check("[G6c] filled throat -> 0.7881", near(r["iou_below_topline"], 33100 / 42000, 0.01),
          r["iou_below_topline"])
    check("[G6c] refused for iou_below_topline", not r["ok"] and r["leg"] is False
          and any(x.startswith("iou_below_topline") for x in r["reasons"]), r["reasons"])
    check("[G6] without item_matte -> None", fg.empty_gate(pump)["iou_below_topline"] is None)

    # [G7]
    P, F = box((0, 0, -0.05), (0.26, 0.08, 0.05))
    fr = shoe_frame(P, F)
    check("[G7] ShoeFrame", isinstance(fr, ShoeFrame))
    check("[G7] up = +Y", np.allclose(fr.up, [0, 1, 0]), fr.up)
    check("[G7] box x = +-X, length 0.26", abs(abs(fr.x_axis[0]) - 1) < 1e-9 and near(fr.length, 0.26, 1e-9),
          (fr.x_axis, fr.length))
    Ph, Fh = merge((P, F), box((0.22, 0.08, -0.05), (0.26, 0.12, 0.05)))
    fr = shoe_frame(Ph, Fh)
    check("[G7] heel at +X -> x_axis (-1, 0, 0)", np.allclose(fr.x_axis, [-1, 0, 0]), fr.x_axis)
    check("[G7] z_axis = x x up = (0, 0, -1)", np.allclose(fr.z_axis, [0, 0, -1]), fr.z_axis)
    check("[G7] origin (0.26, 0, 0)", np.allclose(fr.origin, [0.26, 0, 0]), fr.origin)
    q = fr.to_frame(np.array([[0.0, 0.04, 0.05]]))
    check("[G7] to_frame: toe tip at x = 0.26, height 0.04, z = -0.05", np.allclose(q, [[0.26, 0.04, -0.05]]), q)
    ang = math.radians(30)
    R = np.array([[math.cos(ang), 0, math.sin(ang)], [0, 1, 0], [-math.sin(ang), 0, math.cos(ang)]])
    fr = shoe_frame(P @ R.T, F)
    check("[G7] rotated 30 deg -> x along R e_x", abs(abs(float(fr.x_axis @ (R @ [1, 0, 0]))) - 1) < 1e-9
          and near(fr.length, 0.26, 1e-9), (fr.x_axis, fr.length))
    sil = fg.side_silhouette(P, F, size=256)
    ys, xs = np.nonzero(sil)
    w, h = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    check("[G7] silhouette 256 x 78..80", sil.shape == (256, 256) and sil.dtype == bool and w == 256
          and 78 <= h <= 80, (sil.shape, w, h))
    check("[G7] silhouette bbox filled", sil.sum() / (w * h) >= 0.99, sil.sum() / (w * h))
    rect = np.zeros((200, 400), bool)
    rect[50:150, 30:355] = True
    v = fg.silhouette_iou(sil, rect)
    check("[G7] silhouette vs 325 x 100 rectangle >= 0.99", v >= 0.99, v)

    # [G8]
    check("[G8] EMPTY_GATES", fg.EMPTY_GATES["single_share"][:2] == ("min", 0.98)
          and fg.EMPTY_GATES["aspect"][:2] == ("range", (1.1, 2.6))
          and fg.EMPTY_GATES["iou_below_topline"][:2] == ("min", 0.85), fg.EMPTY_GATES)
    check("[G8] MESH_GATES", fg.MESH_GATES["component_share"][:2] == ("min", 0.98)
          and fg.MESH_GATES["mesh_iou"][:2] == ("min", 0.75), fg.MESH_GATES)
    ok, reasons = fg.check_gates({"component_share": 0.99}, fg.MESH_GATES)
    check("[G8] missing mesh_iou refuses", not ok and reasons and reasons[0].startswith("mesh_iou"), reasons)
    ok, reasons = fg.check_gates({"component_share": 0.99}, fg.MESH_GATES, optional=("mesh_iou",))
    check("[G8] optional missing passes", ok and reasons == [], reasons)

    print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nALL PASS")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
