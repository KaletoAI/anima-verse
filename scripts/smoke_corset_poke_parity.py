"""Corset v3 (review 2026-11-22): an independent check of "the skin shows through the corset" by RAY PARITY — the
drape's own ``poke_share`` (``garment_template_drape``) casts from the bone to each skin vertex; this one casts from
each skin vertex horizontally away from the piece's vertical axis and counts the cloth triangles it crosses. The
drape GLB's cloth is a SHELL of two layers (the outer face and the inner face, 2-3 mm apart: one ray from the cup's
skin met them at 57.46 and 54.57 mm), so: an even, non-zero count = the skin lies under the cloth (2; 4 past a
fold); odd = the skin sits inside the fabric's thickness (the outer face still covers it — counted, not a poke);
0 = the skin shows. No server, no world DB, no Blender.

[1] Hand-derived, synthetic: the cloth a shell of two open cylinders r 0.100 and r 0.097 round the y axis,
    y 0.9 .. 1.2 (48 segments x 6 rows, two triangles per quad; the inscribed 48-gons' flat sides lie at
    r cos(pi / 48) = 0.99786 r: 0.09979 / 0.09679 at the least). Skin: 32 points at y 1.06 (inside a row, never on a
    row edge): every 4th (8) at r 0.11 (outside both: 0 crossings, shows), every 4th + 1 (8) at r 0.0985 (between
    the layers: 1, in the fabric), the other 16 at r 0.09 (inside both: 2, covered) -> shows 8 / 32 = 0.25, in the
    fabric 8. A fold (the shell doubled: two more cylinders r 0.103 / 0.106) -> the covered points cross 4, the
    in-fabric ones 3, the outside ones 0: still shows 0.25. A point at y 1.30 (over the cloth) is not in the region.
[2] On a real build (optional): ``--glb <shaped body .glb> <drape .glb>`` — the region is the body's vertices within
    0.25 m of the piece's axis (the cloth's mean x / z) between 1 cm over the cloth's lowest and 1 cm under its
    highest point in the vertex's 3-degree sector (narrow: the sweetheart's V between the cups is ~5 degrees wide,
    a 10-degree sector took the cups' top for the V's and counted the bare skin over the V: 54 vertices, all 4-7 cm
    from the cloth); the share that shows must stay under ``garment_template.THRESHOLDS["poke_share"]`` (0.005).
    The synthetic cylinders of [1] (7.5 degrees per segment) use 10-degree sectors.

Usage: ./.venv/bin/python scripts/smoke_corset_poke_parity.py [--glb BODY.glb DRAPE.glb]
"""
import math
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f"  ({detail})" if not ok and detail != "" else ""))
    if not ok:
        FAILS.append(label)


def crossings(origins: np.ndarray, dirs: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """The number of triangles (``tris`` (m, 3, 3)) each ray (origin, unit horizontal direction) crosses ahead of
    its origin (Moller-Trumbore); only triangles spanning the ray's height are tested."""
    ymin, ymax = tris[:, :, 1].min(axis=1), tris[:, :, 1].max(axis=1)
    out = np.zeros(len(origins), int)
    for i, (o, d) in enumerate(zip(origins, dirs)):
        t = tris[(ymin <= o[1]) & (ymax >= o[1])]
        if not len(t):
            continue
        e1, e2 = t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]
        p = np.cross(d, e2)
        det = np.einsum("ij,ij->i", e1, p)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        s = o - t[:, 0]
        u = np.einsum("ij,ij->i", s, p) * inv
        q = np.cross(s, e1)
        v = (q @ d) * inv
        dist = np.einsum("ij,ij->i", e2, q) * inv
        out[i] = int((ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (dist > 1e-6)).sum())
    return out


def parity_share(body: np.ndarray, cloth: np.ndarray, faces: np.ndarray, *, reach=0.25, sector_deg=3.0,
                 band=0.01):
    """``(share, region, shows, in_fabric)`` of the body vertices in the cloth's region: ``shows`` = no crossing,
    ``in_fabric`` = an odd count (see the module doc)."""
    cx, cz = float(cloth[:, 0].mean()), float(cloth[:, 2].mean())
    ang_c = np.degrees(np.arctan2(cloth[:, 2] - cz, cloth[:, 0] - cx))
    sec_c = np.floor((ang_c + 180.0) / sector_deg).astype(int)
    lo = float(cloth[:, 1].min()) + band
    top = {s: float(cloth[sec_c == s, 1].max()) - band for s in np.unique(sec_c)}
    rel = body[:, [0, 2]] - np.array([cx, cz])
    rad = np.linalg.norm(rel, axis=1)
    sec_b = np.floor((np.degrees(np.arctan2(rel[:, 1], rel[:, 0])) + 180.0) / sector_deg).astype(int)
    sel = (rad > 1e-4) & (rad < reach) & (body[:, 1] > lo) \
        & (body[:, 1] < np.array([top.get(int(s), -1e9) for s in sec_b]))
    idx = np.where(sel)[0]
    dirs = np.zeros((len(idx), 3))
    dirs[:, 0], dirs[:, 2] = rel[idx, 0] / rad[idx], rel[idx, 1] / rad[idx]
    n = crossings(body[idx], dirs, cloth[faces])
    shows = int((n == 0).sum())
    return shows / max(len(idx), 1), int(len(idx)), shows, int((n % 2 == 1).sum())


def cylinder(r, y0=0.9, y1=1.2, seg=48, rows=6):
    v, f = [], []
    for j in range(rows + 1):
        for k in range(seg):
            a = 2 * math.pi * k / seg
            v.append((r * math.cos(a), y0 + (y1 - y0) * j / rows, r * math.sin(a)))
    for j in range(rows):
        for k in range(seg):
            a, b = j * seg + k, j * seg + (k + 1) % seg
            c, d = a + seg, b + seg
            f += [(a, b, d), (a, d, c)]
    return np.array(v), np.array(f)


# [1]
def shell(*radii):
    vs, fs, off = [], [], 0
    for r in radii:
        v, f = cylinder(r)
        vs.append(v)
        fs.append(f + off)
        off += len(v)
    return np.vstack(vs), np.vstack(fs)


pts = []
for k in range(32):
    a = 2 * math.pi * (k + 0.37) / 32
    r = 0.11 if k % 4 == 0 else 0.0985 if k % 4 == 1 else 0.09
    pts.append((r * math.cos(a), 1.06, r * math.sin(a)))
pts = np.array(pts)
dirs = np.c_[pts[:, 0], np.zeros(32), pts[:, 2]] / np.linalg.norm(pts[:, [0, 2]], axis=1)[:, None]
cv, cf = shell(0.100, 0.097)
n = crossings(pts, dirs, cv[cf])
check("[1] crossings 0 / 1 / 2 by ring", sorted(set(n[0::4])) == [0] and sorted(set(n[1::4])) == [1]
      and sorted(set(n[2::4])) == [2] and sorted(set(n[3::4])) == [2], [int(x) for x in n[:8]])
got = parity_share(pts, cv, cf, band=0.0, sector_deg=10.0)
check("[1] shows 8 of 32 = 0.25, 8 in the fabric", (round(got[0], 4), got[1], got[2], got[3]) == (0.25, 32, 8, 8),
      got)
fv, ff = shell(0.100, 0.097, 0.103, 0.106)
n = crossings(pts, dirs, fv[ff])
check("[1] a fold: covered 4, in the fabric 3, outside 0", sorted(set(n[2::4])) == [4] and sorted(set(n[1::4]))
      == [3] and sorted(set(n[0::4])) == [0], [int(x) for x in n[:8]])
check("[1] with the fold it still shows 0.25",
      round(parity_share(pts, fv, ff, band=0.0, sector_deg=10.0)[0], 4) == 0.25)
above = np.vstack([pts, [[0.09, 1.30, 0.0]]])
check("[1] a point above the cloth is not in the region",
      parity_share(above, cv, cf, band=0.0, sector_deg=10.0)[1] == 32)

# [2]
if "--glb" in sys.argv:
    k = sys.argv.index("--glb")
    _SCRATCH = Path(tempfile.mkdtemp(prefix="smoke-poke-parity-"))
    from app.core import paths  # noqa: E402
    paths.init(_SCRATCH / "world")
    paths.init_instance(_SCRATCH / "instance")
    from app.core import garment_template as gt  # noqa: E402
    from app.core import glb_mesh  # noqa: E402
    B = glb_mesh.body_arrays(Path(sys.argv[k + 1]).read_bytes())
    G = glb_mesh.garment_arrays(Path(sys.argv[k + 2]).read_bytes(), node_prefix="garment_template")
    share, region, shows, inside = parity_share(np.asarray(B.positions), np.asarray(G.positions),
                                                np.asarray(G.indices))
    print(f"     (ray parity on the build: {shows} of {region} skin vertices show, share {share:.5f}; "
          f"{inside} inside the fabric's thickness)")
    check("[2] the real build: share under poke_share", share < gt.THRESHOLDS["poke_share"], share)

print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
