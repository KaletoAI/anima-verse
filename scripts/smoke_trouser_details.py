#!/usr/bin/env python3
"""Smoke: round 2026-11-25 — a trouser's construction details painted on the cut atlas (Kai's jeans: the fly, the
waistband and the back pockets the parameters ask for never appeared).

Usage:
    ./.venv/bin/python scripts/smoke_trouser_details.py

No server, no hub, no Blender, no world: ``cut_texture_post`` on a synthetic ``islands.json`` at 10 px/cm, the cut's
record rule of ``garment_template_cut`` and the text rules of ``garment_cut_texture``.

The synthetic cut (image pixels, y down, every island oriented up as the builder's): front_r x 0..400, front_l
x 500..900, back_l x 1000..1400, back_r x 1500..1900, all y 0..1000; the waistband x 100..1700, y 1100..1140 (its
vertices every 10 px on both edges). Seam chains, 1 cm (10 px) per sample, each listed on both sides:
centre front front_l x 500 / front_r x 400, y 0..300; centre back back_l x 1400 / back_r x 1500, y 0..400;
outseams front_l x 900 / back_l x 1000 and front_r x 0 / back_r x 1900, y 0..1000; inseams front_l x 500 / back_l
x 1400 and front_r x 400 / back_r x 1500, y 400..1000; the waist seams (panel side y 0, band side y 1140): front_l
x 500..900 <-> band x 900..1300, front_r 400..0 <-> 900..500, back_l 1400..1000 <-> 1700..1300, back_r
1500..1900 <-> 100..500 (the band runs back_r | front_r | front_l | back_l, opened at the centre back).

Expected by hand (fly zip, waist belt, jeans):

[W] ``trouser_wanted``: zip + belt -> fly, both front and back pockets, band_stitch, band_button, belt_loops; none +
    elastic -> band_stitch only; zip + none -> the fly and the pockets, no band detail; none + none -> nothing.
    ``trouser_style``: "Blue denim trousers" / "Jeans" -> jeans, "grey wool trousers" -> tailored.
[F] the fly on front_l: the centre front is 30 cm, so its length is min(17, 30 - 4) = 17 cm = 170 px; FLY_W 35 px;
    front_l's middle (700, 500) lies at +x. Row 1 starts at (535, 0) and ends on the seam at (500, 170); row 2 (radius
    35 - 6 = 29, the same centre (500, 135)) starts at (529, 0) and ends at (500, 164); the groove runs (500, 0) ->
    (500, 170); the bar tack at t 170 - 2: (501, 168) -> (509, 168).
[P] the front pocket on front_l: the waist from its centre end (500, 0) to (900, 0); p0 at 10 cm: (600, 0); down
    +y; the outseam's top (900, 0), p1 at 8 cm: (900, 80); the scoop's control (600, 80); its middle
    0.25 p0 + 0.5 c + 0.25 p1 = (675, 60); rivets at p0 + 5 down = (600, 5) and p1 + 5 toward p0 = (900, 80) +
    5 x (-300, -80) / 310.48349 = (895.16871, 78.71166). front_r mirrored: p0 (300, 0), p1 (0, 80).
[B] the back of back_l: the centre back (1400, 0..400), the outseam (1000, 0..1000), the waist from (1400, 0) to
    (1000, 0); the yoke from (1400, 65) to (1000, 35): across = (-400, -30) / 401.12342 = (-0.99719, -0.07479), down
    its normal toward the middle (1200, 500): (-0.07479, 0.99719). w0 = the waist at 9 cm = (1310, 0). The yoke's
    depth under w0 along down: ((90)(-30) - (65)(-400)) / ((-0.07479)(-30) - (0.99719)(-400)) = 23300 / 401.12342 =
    58.087 px, + 10 = 68.09 < 75: the top stays 75 px. Top centre tc = w0 + 75 down = (1304.39075, 74.78993); top
    left tl = tc - 70 across = (1374.19468, 80.02524) (the pocket's first corner), the point
    tc + 150 down = (1293.17225, 224.36978).
[D] the waistband: its axis +x, centre (900, 1120), up (0, -1); its height measured 40 px (4 cm); rows at
    y 1140 - 3 = 1137 and 1140 - 37 = 1103; the centre front where the front_l and front_r runs meet: u 0 -> the
    button at (900, 1120); the sides at u +-400; the loops at u (the band's ends -800 / +800, front +-90, sides
    400 + 15 and -415, back -800 + 70 / 800 - 70) -> x 100, 1700, 990, 810, 1315, 485, 170, 1630, each from y 1140 to
    1100.
[G] painted on a plain atlas (fabric (60, 90, 140) on every island, white elsewhere) with the thread (196, 152, 64):
    the pixel (row 1, col 535) on row 1's first dash (0..3 px, half width 0.5) is the thread; the button's centre
    pixel (row 1120, col 900) is the metal (L* 60 grey) under its rim (8.5 px) and outside its highlight (radius 2.55
    round (898.3, 1118.3): 3.11 px away); no white pixel changed; ``trouser_detail_gate`` is empty. A thread of the
    fabric's own colour (62, 92, 142) is replaced by the contrast shade (``thread_colour`` -> "contrast").
[M] without the centre-front chain the fly and both front pockets are missing (the seam is both front panels'
    centre: neither has a frame), the other five details stay; without the
    waistband (waist none: no band island, no waist chains) the front pocket takes the panel's top edge from its
    boundary loop between the two seam tops: p0 is (600, 0) again.
[R] the cut record (``garment_template_cut``): ``details_due`` only for a record with missing details not yet cut
    again; ``trouser_details`` lists wanted / placed / missing; ``thread_text_colour`` reads "orange stitching" ->
    orange, a text without a thread noun -> None.
"""
import copy
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="trouser-details-")
os.environ.setdefault("STORAGE_DIR", _tmp)
os.environ.setdefault("INSTANCE_DIR", _tmp)
FAILS = []


def check(label, got, want, tol=None):
    if tol is not None:
        g, w = np.asarray(got, float), np.asarray(want, float)
        ok = g.shape == w.shape and bool(np.all(np.abs(g - w) <= tol))
    else:
        ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def rect(name, part, x0, x1, y0, y1, step=None):
    if step:
        xs = list(range(x0, x1 + 1, step))
        verts = [[x, y0] for x in xs] + [[x, y1] for x in xs]
        n = len(xs)
        tris = []
        for i in range(n - 1):
            tris += [[i, i + 1, n + i], [i + 1, n + i + 1, n + i]]
    else:
        verts = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
        tris = [[0, 1, 2], [0, 2, 3]]
    loop = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return {"name": name, "part": part, "bbox_px": [x0, y0, x1, y1], "loops_px": [loop], "verts_px": verts,
            "tris": tris}


def chain(seams, k, a, pa, b, pb):
    for p, q in zip(pa, pb):
        seams.append({"seam": k, "a": a, "b": b, "uv_a_px": [float(p[0]), float(p[1])],
                      "uv_b_px": [float(q[0]), float(q[1])]})


def vline(x, y0, y1):
    return [(x, y) for y in range(y0, y1 + 1, 10)]


def hline(y, x0, x1):
    step = 10 if x1 >= x0 else -10
    return [(x, y) for x in range(x0, x1 + step, step)]


def synthetic(band=True, centre_front=True):
    islands = [rect("front_r", 11, 0, 400, 0, 1000), rect("front_l", 10, 500, 900, 0, 1000),
               rect("back_l", 12, 1000, 1400, 0, 1000), rect("back_r", 13, 1500, 1900, 0, 1000)]
    if band:
        islands.append(rect("waistband", 14, 100, 1700, 1100, 1140, step=10))
    seams = []
    if centre_front:
        chain(seams, 0, "front_l", vline(500, 0, 300), "front_r", vline(400, 0, 300))
    chain(seams, 1, "back_l", vline(1400, 0, 400), "back_r", vline(1500, 0, 400))
    chain(seams, 2, "back_l", vline(1000, 0, 1000), "front_l", vline(900, 0, 1000))
    chain(seams, 3, "back_r", vline(1900, 0, 1000), "front_r", vline(0, 0, 1000))
    chain(seams, 4, "back_l", vline(1400, 400, 1000), "front_l", vline(500, 400, 1000))
    chain(seams, 5, "back_r", vline(1500, 400, 1000), "front_r", vline(400, 400, 1000))
    if band:
        chain(seams, 6, "front_l", hline(0, 500, 900), "waistband", hline(1140, 900, 1300))
        chain(seams, 7, "front_r", hline(0, 400, 0), "waistband", hline(1140, 900, 500))
        chain(seams, 8, "back_l", hline(0, 1400, 1000), "waistband", hline(1140, 1700, 1300))
        chain(seams, 9, "back_r", hline(0, 1500, 1900), "waistband", hline(1140, 100, 500))
    return {"version": 1, "atlas_px": 2048, "px_per_cm": 10.0, "margin_cm": 1.5, "islands": islands, "seams": seams}


def first(line):
    return line["px"][0]


def last(line):
    return line["px"][-1]


def main() -> int:
    from app.core import cut_texture_post as ctp
    from app.core import garment_cut_texture as gct
    from app.core import garment_template_cut as gtc

    print("[W] what the parameters ask for")
    check("zip + belt", ctp.trouser_wanted("zip", "belt"),
          ["fly", "front_pocket_l", "front_pocket_r", "back_pocket_l", "back_pocket_r", "band_stitch", "band_button",
           "belt_loops"])
    check("none + elastic", ctp.trouser_wanted("none", "elastic"), ["band_stitch"])
    check("zip + none", ctp.trouser_wanted("zip", "none"),
          ["fly", "front_pocket_l", "front_pocket_r", "back_pocket_l", "back_pocket_r"])
    check("none + none", ctp.trouser_wanted("none", "none"), [])
    check("style", [ctp.trouser_style(t) for t in ("Blue denim trousers", "Jeans", "grey wool trousers")],
          ["jeans", "jeans", "tailored"])

    isl = synthetic()
    L = ctp.trouser_lines(isl, fly="zip", waist="belt", style="jeans", band_cm=4.0)
    check("all placed", L["missing"], [])
    ln = L["lines"]
    print("[F] the fly")
    check("row 1 start", first(ln["fly_1"]), [535.0, 0.0], 1e-6)
    check("row 1 end", last(ln["fly_1"]), [500.0, 170.0], 1e-6)
    check("row 2 start", first(ln["fly_2"]), [529.0, 0.0], 1e-6)
    check("row 2 end", last(ln["fly_2"]), [500.0, 164.0], 1e-6)
    check("groove", [first(ln["fly_edge"]), last(ln["fly_edge"])], [[500.0, 0.0], [500.0, 170.0]], 1e-6)
    check("tack", ln["fly_tack"]["px"], [[501.0, 168.0], [509.0, 168.0]], 1e-6)
    check("fly on front_l", ln["fly_1"]["island"], "front_l")

    print("[P] the front pockets")
    e = ln["front_pocket_l_edge"]["px"]
    check("left scoop start / end", [e[0], e[-1]], [[600.0, 0.0], [900.0, 80.0]], 1e-6)
    from app.core.cut_texture_post import _bezier
    check("left scoop middle", _bezier([600, 0], [600, 80], [900, 80], 3)[1].tolist(), [675.0, 60.0], 1e-9)
    check("left scoop = the Bezier", e, np.round(_bezier([600, 0], [600, 80], [900, 80]), 2).tolist(), 1e-6)
    P = L["points"]
    check("rivet 1", P["front_pocket_l_rivet_1"]["px"], [600.0, 5.0], 1e-6)
    check("rivet 2", P["front_pocket_l_rivet_2"]["px"], [895.17, 78.71], 0.006)
    e = ln["front_pocket_r_edge"]["px"]
    check("right scoop start / end", [e[0], e[-1]], [[300.0, 0.0], [0.0, 80.0]], 1e-6)

    print("[B] the back")
    check("yoke", ln["yoke_l_edge"]["px"], [[1400.0, 65.0], [1000.0, 35.0]], 1e-6)
    e = ln["back_pocket_l_edge"]["px"]
    check("pocket top left corner", e[0], [1374.19, 80.03], 0.006)
    check("pocket bottom point", e[2], [1293.17, 224.37], 0.006)
    check("pocket closed", e[-1], e[0])
    check("right pocket placed", "back_pocket_r_edge" in ln and "yoke_r_edge" in ln, True)

    print("[D] the waistband")
    check("band height", L["band_h_cm"], 4.0, 1e-9)
    ys = [sorted({round(p[1], 6) for p in ln[k]["px"]}) for k in ("band_stitch_1", "band_stitch_2")]
    check("band rows", ys, [[1137.0], [1103.0]])
    check("button", P["band_button"]["px"], [900.0, 1120.0], 1e-6)
    check("loops x", sorted(round(lp["a"][0], 3) for lp in L["loops"]),
          sorted([100.0, 1700.0, 990.0, 810.0, 1315.0, 485.0, 170.0, 1630.0]))
    check("loops span the band", sorted({(lp["a"][1], lp["b"][1]) for lp in L["loops"]}), [(1140.0, 1100.0)])

    print("[G] painted on a plain atlas")
    from app.core.garment_cut_texture import island_ids, rasterise_islands
    size = 2048
    labels = rasterise_islands(isl, size)
    ids = island_ids(isl)
    masks = {n: labels == ids[n] for n in ids}
    fabric = np.array([60, 90, 140], np.uint8)
    atlas = np.full((size, size, 3), 255, np.uint8)
    atlas[labels > 0] = fabric
    out, info = ctp.draw_trouser_details(atlas, masks, L, px_per_cm=10.0, thread_rgb=(196, 152, 64))
    check("thread from the item", info["thread_source"], "item")
    check("fly row 1 first dash", out[1, 535].tolist(), [196, 152, 64])
    metal = np.clip(np.rint(ctp.lab_to_srgb(np.array([ctp.ZIP_L, 0.0, 0.0]))), 0, 255).astype(np.uint8).tolist()
    check("button centre is metal", out[1120, 900].tolist(), metal)
    check("nothing outside the islands", bool((out[labels == 0] == 255).all()), True)
    check("gate", ctp.trouser_detail_gate(info, L["placed"]), [])
    check("every detail painted", sorted(info["painted"]), sorted(L["wanted"]))
    _o, info2 = ctp.draw_trouser_details(atlas, masks, L, px_per_cm=10.0, thread_rgb=(62, 92, 142))
    check("a thread of the fabric's colour -> contrast", info2["thread_source"], "contrast")

    print("[M] what the islands cannot carry")
    L2 = ctp.trouser_lines(synthetic(centre_front=False), fly="zip", waist="belt")
    check("no centre front", sorted(L2["missing"]), ["fly", "front_pocket_l", "front_pocket_r"])
    L3 = ctp.trouser_lines(synthetic(band=False), fly="zip", waist="none")
    check("no waistband: pocket from the top edge", L3["lines"]["front_pocket_l_edge"]["px"][0], [600.0, 0.0], 1e-6)
    check("no waistband: all placed", L3["missing"], [])

    print("[R] the cut record and the texts")
    check("due: missing, not retried", gtc.details_due({"details": {"missing": ["fly"], "retried": False}}), True)
    check("not due: retried", gtc.details_due({"details": {"missing": ["fly"], "retried": True}}), False)
    check("not due: nothing missing", gtc.details_due({"details": {"missing": []}}), False)
    check("not due: an old record", gtc.details_due({}), False)
    params = {"kind": "trousers", "fly": "zip", "trouser_waist": "belt"}
    got = gtc.trouser_details(params, {"name": "Jeans"}, copy.deepcopy(synthetic(centre_front=False)))
    check("record lists", (got["missing"], len(got["placed"])), (["fly", "front_pocket_l", "front_pocket_r"], 5))
    check("skirt: no record", gtc.trouser_details({"kind": "skirt"}, None, isl), None)
    check("text: orange stitching", gct.thread_text_colour("blue jeans with orange stitching"),
          tuple(gct.TRIM_COLOURS["orange"]))
    check("text: no thread noun", gct.thread_text_colour("blue jeans, brass buttons"), None)
    print("FAIL" if FAILS else "PASS", len(FAILS), "failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
