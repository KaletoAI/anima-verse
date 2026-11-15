#!/usr/bin/env python3
"""The inset part's back end: the levelled region ends before the channel closes, and slivers are mended (A77b).

Usage:
    ./.venv/bin/python scripts/smoke_inset_part_back_end.py

Runs inside Blender (bmesh), no world, no server. Hand-derived expectations:
[1] ``region_ends`` on envelope rows every 2 degrees from 20 to 100, half widths (narrower side) 32 mm up to 70
    degrees, then 10, 8, 5, 3 mm at 72, 74, 76, 78 and 2 mm beyond; minimum 6 mm, margin 3 degrees: the widest row
    is the first (20), the first row under 6 mm after it is 76 degrees, so the region ends at 76 - 3 = 73; its start
    stays 20 (nothing narrow before the widest row).
    Mirrored (narrow at the start: 2 mm up to 30 degrees, 32 mm after): the start is the last narrow row before the
    widest one, 30, plus 3 = 33; the end stays 100.
    No row under the minimum, every row under it, or minimum 0: the interval comes back unchanged.
[2] ``aspect`` = longest edge squared over twice the area: an equilateral triangle of side 1 gives
    1 / (sqrt 3 / 2) = 1.1547; the right isosceles one with legs 1 gives 2 / 1 = 2; a degenerate one inf.
[3] A flip: A (0, 0), B (40, 0) share the long edge of P (20, 1) and Q (20, -1). Each triangle has aspect
    40^2 / (2 x 20) = 40. Across P-Q instead: longest edge sqrt(20^2 + 1) = 20.025, area 20, aspect
    401 / 40 = 10.025 for both — lower, coplanar: ``flip_slivers`` connects P and Q.
[4] A needle: the 10 x 10 square C0 (0, 0), C1 (10, 0), C2 (10, 10), C3 (0, 10) with two inner vertices a
    (4.975, 5) and b (5.025, 5), 0.05 apart, in six triangles. (C0, b, a) and (b, C2, a) have area .5 x .05 x 5 =
    .125 and longest edge |C0 b| = 7.089, aspect 7.089^2 / .25 = 201. No flip helps (each other diagonal leaves a
    triangle of area .125 again), so the edge a-b is collapsed onto (5, 5): four triangles of aspect 10^2 / 50 = 2,
    all facing +z, the corners unmoved, and ``flat`` maps the surviving vertex to the flat midpoint (5, 5, 0).

No expected value is recorded from a run. Fails on f2f96c1ef1c3adfbee3692ad6e0e580261f58569: ``inset_part`` has no
``region_ends``, ``aspect`` or ``flip_slivers`` (the levelled region ran into the closing channel).
"""
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BLENDER = Path('/home/dev/tools/blender-5.2.2-linux-x64/blender')


def probe():
    import bmesh
    import numpy as np
    from mathutils import Vector
    sys.path.insert(0, str(ROOT / 'app/blender/scripts'))
    import inset_part
    rad = math.radians
    # [1] region_ends
    tg = np.radians(np.arange(20, 100.1, 2))
    deg = np.degrees(tg)
    half = np.select([deg <= 70, deg == 72, deg == 74, deg == 76, deg == 78], [.032, .010, .008, .005, .003], .002)
    walls = np.stack([half, half + .01], 1)
    t0, t1 = inset_part.region_ends(tg, walls, rad(20), rad(100), .006, rad(3))
    assert abs(math.degrees(t0) - 20) < 1e-9 and abs(math.degrees(t1) - 73) < 1e-9, (math.degrees(t0), math.degrees(t1))
    mirrored = np.where(deg <= 30, .002, .032)
    t0, t1 = inset_part.region_ends(tg, np.stack([mirrored, mirrored], 1), rad(20), rad(100), .006, rad(3))
    assert abs(math.degrees(t0) - 33) < 1e-9 and abs(math.degrees(t1) - 100) < 1e-9, (math.degrees(t0), math.degrees(t1))
    for w, minimum in ((np.full((len(tg), 2), .032), .006), (np.full((len(tg), 2), .002), .006), (walls, 0.)):
        assert inset_part.region_ends(tg, w, rad(20), rad(100), minimum, rad(3)) == (rad(20), rad(100))
    # [2] aspect
    V = Vector
    assert abs(inset_part.aspect([V((0, 0, 0)), V((1, 0, 0)), V((.5, math.sqrt(3) / 2, 0))]) - 2 / math.sqrt(3)) < 1e-9
    assert abs(inset_part.aspect([V((0, 0, 0)), V((1, 0, 0)), V((0, 1, 0))]) - 2) < 1e-9
    assert inset_part.aspect([V((0, 0, 0)), V((1, 0, 0)), V((2, 0, 0))]) == math.inf
    # [3] a flip
    bm = bmesh.new()
    A, B, P, Q = (bm.verts.new(p) for p in ((0, 0, 0), (40, 0, 0), (20, 1, 0), (20, -1, 0)))
    bm.faces.new((A, B, P)); bm.faces.new((B, A, Q))
    bm.normal_update()
    inset_part.flip_slivers(bm, {v: v.co.copy() for v in bm.verts})
    shared = [e for e in bm.edges if len(e.link_faces) == 2]
    assert len(shared) == 1 and set(shared[0].verts) == {P, Q}, [tuple(v.co) for e in shared for v in e.verts]
    worst = max(inset_part.aspect([v.co for v in f.verts]) for f in bm.faces)
    assert abs(worst - 401 / 40) < 1e-6, worst
    bm.free()
    # [4] a needle
    bm = bmesh.new()
    C0, C1, C2, C3 = (bm.verts.new(p) for p in ((0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)))
    a, b = bm.verts.new((4.975, 5, 0)), bm.verts.new((5.025, 5, 0))
    for face in ((C0, C1, b), (C1, C2, b), (b, C2, a), (a, C2, C3), (C0, a, C3), (C0, b, a)):
        bm.faces.new(face)
    bm.normal_update()
    assert abs(inset_part.aspect([C0.co, b.co, a.co]) - (7.089 ** 2 / .25)) < 1, inset_part.aspect([C0.co, b.co, a.co])
    flat = {v: v.co.copy() for v in bm.verts}
    inset_part.flip_slivers(bm, flat)
    assert len(bm.faces) == 4 and len(bm.verts) == 5, (len(bm.faces), len(bm.verts))
    for f in bm.faces:
        assert abs(inset_part.aspect([v.co for v in f.verts]) - 2) < 1e-6
        assert f.normal.z > .999, tuple(f.normal)
    corners = {(0, 0), (10, 0), (10, 10), (0, 10)}
    assert {(round(v.co.x, 9), round(v.co.y, 9)) for v in bm.verts} == corners | {(5, 5)}
    middle = next(v for v in bm.verts if (round(v.co.x, 9), round(v.co.y, 9)) == (5, 5))
    assert len(flat) == 5 and (flat[middle] - V((5, 5, 0))).length < 1e-9, dict((tuple(k.co), tuple(v)) for k, v in flat.items())
    bm.free()
    print('PASS inset back end: region ends 73 / starts 33 deg, aspect 1.1547 / 2 / inf, flip 40 -> 10.025, '
          'needle 201 -> 2')


if __name__ == '__main__':
    if '--probe' in sys.argv:
        try:
            probe()
        except BaseException:
            import traceback
            traceback.print_exc()
            sys.stdout.flush(); sys.stderr.flush()
            os._exit(1)
        sys.stdout.flush(); sys.stderr.flush()
        os._exit(0)
    subprocess.run([str(BLENDER), '-b', '-noaudio', '--factory-startup', '--python-exit-code', '1', '-t', '2',
                    '-P', __file__, '--', '--probe'], check=True)
