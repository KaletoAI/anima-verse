#!/usr/bin/env python3
"""Smoke run for the picture-area maths (``app.core.picture_areas``).

Pure geometry, stdlib only, no world, no DB, no Blender: a hand-built
triangle mesh with hand-built UVs and a hand-written ``sample_rgb`` goes
straight into the module. Every number below is derived BY HAND from the
rules — that is the point of the file: it catches a lost sample point, a
component split over vertices instead of edges, a flipped plane normal and a
UV normalisation that stopped spanning 0..1.

THE FIXTURE
-----------
A 1 m x 1 m plate in the XY plane at z = 0, cut into a 10 x 10 grid of
quads.  Vertex ``(i, j)`` (``i, j`` in 0..10, index ``j * 11 + i``) sits at
world ``(i/10, j/10, 0)`` and carries UV ``(i/10, j/10)`` — UVs ARE the grid
coordinates, so a UV rectangle is a world rectangle at the same numbers.
Quad ``(i, j)`` is two triangles::

    v00 = (i, j)   v10 = (i+1, j)   v11 = (i+1, j+1)   v01 = (i, j+1)
    tri A = (v00, v10, v11)         tri B = (v00, v11, v01)

so face index ``2 * (j * 10 + i)`` is A and ``+ 1`` is B — 200 faces.

``sample_rgb`` answers GREEN inside the half-open UV rectangle
``u in [0.2, 0.6)`` and ``v in [0.3, 0.9)``, GREY everywhere else (the glass
case answers MAGENTA in the same rectangle).  Colours: green (0.1, 0.8, 0.1),
magenta (0.8, 0.1, 0.8), grey (0.5, 0.5, 0.5).  Against the 0..1 key rule
(``picture``: g > 0.39 and g > r + 0.12 and g > b + 0.12) green passes
(0.8 > 0.39, 0.8 > 0.22) and grey fails (0.5 > 0.62 is false); against the
``glass`` rule (r > 0.39 and b > 0.39 and g < r - 0.12 and g < b - 0.12)
magenta passes (0.8 > 0.39 twice, 0.1 < 0.68) and grey fails (0.5 < 0.38 is
false).

Plus ONE STRAY GREEN TRIANGLE far off the plate: three fresh vertices
(2.00, 2.00, 0), (2.10, 2.00, 0), (2.05, 2.10, 0) — indices 121..123, face
index 200 — with UVs (0.30, 0.40), (0.35, 0.40), (0.32, 0.45), i.e. inside
the green rectangle.  It shares NO vertex with the plate, so it is its own
component.

[1] WHICH FACES ARE KEY — exactly 48
------------------------------------
``face_samples`` takes three points: the centroid ``c = (A+B+C)/3`` and
``c + (P - c)/3`` for the face's FIRST TWO vertices.  In barycentric terms
``c + (A - c)/3 = (5/9)A + (2/9)B + (2/9)C`` — all weights positive, so every
sample lies STRICTLY INSIDE the triangle, hence strictly inside its quad.
A face is key when >= 2 of the 3 samples match.

For quad column ``i`` the three u values of triangle A are therefore
``(i + 2/3)/10`` (centroid), ``(i + 4/9)/10`` and ``(i + 7/9)/10`` — all
strictly between ``i/10`` and ``(i+1)/10``.  So a quad's samples are green
exactly when the WHOLE quad lies in the rectangle:

    u in [0.2, 0.6)  ->  columns i = 2, 3, 4, 5   (quad u spans 0.2..0.6)
    v in [0.3, 0.9)  ->  rows    j = 3..8         (quad v spans 0.3..0.9)

Boundary checks by hand: column i = 5, the sample nearest the open upper
edge is ``(5 + 7/9)/10 = 0.5778 < 0.6`` -> still green; column i = 6 the
lowest sample is ``(6 + 4/9)/10 = 0.6444 > 0.6`` -> grey; column i = 1 the
highest is ``(1 + 7/9)/10 = 0.1778 < 0.2`` -> grey.  Row j = 8 highest
sample ``0.8778 < 0.9`` -> green; row j = 9 lowest ``0.9222 > 0.9`` -> grey.

=> 4 columns x 6 rows x 2 triangles = **48** key faces on the plate,
   plus the stray = 49 key faces overall.

[2] COMPONENTS — over shared EDGES
----------------------------------
Inside a quad, A and B share the diagonal ``v00-v11``.  Horizontally, quad
``(i, j)``'s A owns the edge ``v10-v11`` = the vertical grid line at
``i+1``, which is quad ``(i+1, j)``'s B edge ``v01-v00``.  Vertically, quad
``(i, j)``'s B owns ``v11-v01`` = the horizontal grid line at ``j+1``, which
is quad ``(i, j+1)``'s A edge ``v00-v10``.  So the 4 x 6 block is ONE
component of 48 faces; the stray triangle is a second component of 1 face.
Sorted by size descending: ``[48 faces, 1 face]``.

[3] PLANE FIT — flat block
--------------------------
The block's unique vertices are the grid nodes ``i = 2..6`` (5 values) times
``j = 3..9`` (7 values) = 35 nodes, all at z = 0.  Centroid: mean of
``i/10`` over 2..6 = 4/10 = **0.4**; mean of ``j/10`` over 3..9 = 6/10 =
**0.6**; z = **0.0**.  The covariance's z row/column is all zero, so the
smallest eigenvalue is 0 with eigenvector ``(0, 0, 1)``; the sign rule
(first non-zero component of z, then y, then x must be positive) keeps it:
normal = **(0, 0, 1)**.

[4] PLANAR FRAME for normal (0, 0, 1)
-------------------------------------
``|dot|`` against the world axes is x: 0, y: 0, z: 1 — the smallest is x
(ties go to the first), so ``u = (1,0,0)`` projected into the plane and
normalised = ``(1, 0, 0)``, and ``v = n x u = (0,0,1) x (1,0,0) =
(0, 1, 0)``.  ``v . (0,1,0) = 1 > 0`` — no flip.  u is world +x, v is
world +y.

[5] PLANAR UVs
--------------
Projected onto that frame the block spans x 0.2..0.6 and y 0.3..0.9, so
``size_m = (0.4, 0.6)`` and the corners map
``(0.2, 0.3, 0) -> (0, 0)`` and ``(0.6, 0.9, 0) -> (1, 1)``.

[6]/[7] DETECT_AREAS — the stray is filtered
--------------------------------------------
Block: area = 0.4 x 0.6 = 0.24 m2 >= 0.02 and 48 >= 12 faces -> survives.
Stray: 1 face < 12 AND area = 0.5 x 0.1 x 0.1 = 0.005 m2 < 0.02 -> dropped
by both filters.  So ``detect_areas`` returns exactly ONE area, with the 48
faces, normal (0,0,1), centroid (0.4, 0.6, 0), size_m (0.4, 0.6).  The
magenta fixture with ``kind="glass"`` yields the very same face set.

[8] BOUNDARY EDGES
------------------
The block is a 4 x 6 rectangle of quads.  Every diagonal is shared by the
two triangles of its quad, every interior grid edge by two triangles of
neighbouring quads — only the perimeter unit edges are used once:
``2 * (4 + 6) = 20`` boundary edges.

[9] PLANE FIT — tilted, so the Jacobi solver is not trivial
-----------------------------------------------------------
Nine points on the plane ``z = 0.5 * x``: ``x, y in {0, 1, 2}``,
``z = 0.5 x``.  Centroid = ``(1, 1, 0.5)``.  Centred coordinates: dx and dy
each run over {-1, 0, 1} three times, dz = 0.5 dx.  Scatter matrix::

    Sxx = 3*(1+0+1) = 6      Syy = 6        Szz = 0.25 * 6 = 1.5
    Sxy = (sum dx)(sum dy) = 0              Syz = 0.5 * Sxy = 0
    Sxz = 0.5 * Sxx = 3

        [ 6  0   3  ]
    S = [ 0  6   0  ]
        [ 3  0  1.5 ]

``(0,1,0)`` is an eigenvector with eigenvalue 6.  The x-z block
``[[6, 3], [3, 1.5]]`` has trace 7.5 and determinant ``6*1.5 - 9 = 0``, so
its eigenvalues are 7.5 and 0.  The zero eigenvector solves ``6a + 3c = 0``
-> ``c = -2a`` -> direction ``(1, 0, -2)/sqrt(5)``.  The sign rule (z first)
flips it to::

    normal = (-1/sqrt(5), 0, 2/sqrt(5))
           = (-0.4472135954999579, 0.0, 0.8944271909999159)

Usage:  ./.venv/bin/python scripts/smoke_picture_areas.py
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import picture_areas as pa  # noqa: E402

FAILURES = []

GREEN = (0.1, 0.8, 0.1)
MAGENTA = (0.8, 0.1, 0.8)
GREY = (0.5, 0.5, 0.5)

N = 10          # quads per edge
KEY_U = (0.2, 0.6)
KEY_V = (0.3, 0.9)


def check(label, ok, detail=""):
    if ok:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}  {detail}")
        FAILURES.append(label)


def close(a, b, eps=1e-9):
    return abs(a - b) <= eps


def vclose(a, b, eps=1e-9):
    return len(a) == len(b) and all(close(x, y, eps) for x, y in zip(a, b))


# --------------------------------------------------------------------------
# The fixture (built exactly as the docstring describes)
# --------------------------------------------------------------------------
def build_fixture():
    vertices = []
    uvs = []
    for j in range(N + 1):
        for i in range(N + 1):
            vertices.append((i / 10.0, j / 10.0, 0.0))
            uvs.append((i / 10.0, j / 10.0))

    def vid(i, j):
        return j * (N + 1) + i

    faces = []
    for j in range(N):
        for i in range(N):
            v00, v10 = vid(i, j), vid(i + 1, j)
            v11, v01 = vid(i + 1, j + 1), vid(i, j + 1)
            faces.append((v00, v10, v11))
            faces.append((v00, v11, v01))

    # the stray triangle, indices 121..123, face index 200
    stray_base = len(vertices)
    vertices.extend([(2.00, 2.00, 0.0), (2.10, 2.00, 0.0), (2.05, 2.10, 0.0)])
    uvs.extend([(0.30, 0.40), (0.35, 0.40), (0.32, 0.45)])
    faces.append((stray_base, stray_base + 1, stray_base + 2))
    return vertices, faces, uvs


def make_sampler(key_rgb):
    def sample_rgb(u, v):
        if KEY_U[0] <= u < KEY_U[1] and KEY_V[0] <= v < KEY_V[1]:
            return key_rgb
        return GREY
    return sample_rgb


# the hand rule: quad (i, j) with 2 <= i <= 5 and 3 <= j <= 8, both triangles
EXPECTED_KEY = {
    2 * (j * N + i) + t
    for i in range(2, 6)
    for j in range(3, 9)
    for t in (0, 1)
}
EXPECTED_KEY_WITH_STRAY = EXPECTED_KEY | {200}


def main():
    vertices, faces, uvs = build_fixture()
    sample_green = make_sampler(GREEN)
    sample_magenta = make_sampler(MAGENTA)

    print("smoke_picture_areas")
    check("fixture: 201 faces, 124 vertices",
          len(faces) == 201 and len(vertices) == 124,
          f"{len(faces)} / {len(vertices)}")

    # [0] the colour rule itself
    check("is_key_colour green/picture", pa.is_key_colour(GREEN, "picture") is True)
    check("is_key_colour grey/picture", pa.is_key_colour(GREY, "picture") is False)
    check("is_key_colour magenta/glass", pa.is_key_colour(MAGENTA, "glass") is True)
    check("is_key_colour grey/glass", pa.is_key_colour(GREY, "glass") is False)
    check("is_key_colour green is not glass", pa.is_key_colour(GREEN, "glass") is False)
    try:
        pa.is_key_colour(GREEN, "wallpaper")
        check("is_key_colour unknown kind raises", False)
    except ValueError:
        check("is_key_colour unknown kind raises", True)

    # face_samples: 3 points, all strictly inside the triangle
    samples = pa.face_samples(uvs, faces[2 * (3 * N + 2)])
    check("face_samples returns 3 points", len(samples) == 3, str(samples))
    # quad (2, 3), triangle A: u values (2+2/3)/10, (2+4/9)/10, (2+7/9)/10
    exp_u = sorted([(2 + 2 / 3) / 10, (2 + 4 / 9) / 10, (2 + 7 / 9) / 10])
    check("face_samples u values match the hand derivation",
          vclose(sorted(s[0] for s in samples), exp_u),
          f"{sorted(s[0] for s in samples)} != {exp_u}")

    # [1] classification
    flags = pa.classify_faces(faces, uvs, sample_green, "picture")
    got_key = {n for n, f in enumerate(flags) if f}
    check("classify_faces marks exactly 48 plate faces + 1 stray = 49",
          len(got_key) == 49, str(len(got_key)))
    check("classify_faces marks exactly the hand-derived faces",
          got_key == EXPECTED_KEY_WITH_STRAY,
          f"extra={sorted(got_key - EXPECTED_KEY_WITH_STRAY)[:5]} "
          f"missing={sorted(EXPECTED_KEY_WITH_STRAY - got_key)[:5]}")

    # [2] components
    comps = pa.components(flags, faces)
    check("components: two, sized 48 and 1",
          [len(c) for c in comps] == [48, 1], str([len(c) for c in comps]))
    check("components: the big one is the 4x6 block",
          set(comps[0]) == EXPECTED_KEY, "")
    check("components: the small one is the stray", comps[1] == [200], str(comps[1]))

    # [3] plane fit on the block
    block_verts = sorted({v for n in comps[0] for v in faces[n]})
    check("block has 35 unique vertices", len(block_verts) == 35, str(len(block_verts)))
    centroid, normal = pa.fit_plane([vertices[v] for v in block_verts])
    check("fit_plane centroid == (0.4, 0.6, 0.0)", vclose(centroid, (0.4, 0.6, 0.0)), str(centroid))
    check("fit_plane normal == (0, 0, 1)", vclose(normal, (0.0, 0.0, 1.0)), str(normal))

    # [4] planar frame
    u_axis, v_axis = pa.planar_frame((0.0, 0.0, 1.0))
    check("planar_frame u == (1, 0, 0)", vclose(u_axis, (1.0, 0.0, 0.0)), str(u_axis))
    check("planar_frame v == (0, 1, 0)", vclose(v_axis, (0.0, 1.0, 0.0)), str(v_axis))

    # [5] planar uvs
    pts = [vertices[v] for v in block_verts]
    puvs, size_m = pa.planar_uvs(pts, centroid, (u_axis, v_axis))
    check("planar_uvs size_m == (0.4, 0.6)", vclose(size_m, (0.4, 0.6)), str(size_m))
    idx_lo = block_verts.index(3 * (N + 1) + 2)      # grid node (2, 3) = (0.2, 0.3)
    idx_hi = block_verts.index(9 * (N + 1) + 6)      # grid node (6, 9) = (0.6, 0.9)
    check("planar_uvs corner (0.2, 0.3) -> (0, 0)", vclose(puvs[idx_lo], (0.0, 0.0)), str(puvs[idx_lo]))
    check("planar_uvs corner (0.6, 0.9) -> (1, 1)", vclose(puvs[idx_hi], (1.0, 1.0)), str(puvs[idx_hi]))
    check("planar_uvs stays inside 0..1",
          all(-1e-12 <= a <= 1 + 1e-12 and -1e-12 <= b <= 1 + 1e-12 for a, b in puvs))

    # [6] detect_areas — the stray is filtered out
    areas = pa.detect_areas(vertices, faces, uvs, sample_green, "picture")
    check("detect_areas returns exactly one area", len(areas) == 1, str(len(areas)))
    if areas:
        a = areas[0]
        check("area kind == picture", a["kind"] == "picture", str(a.get("kind")))
        check("area has the 48 block faces",
              set(a["faces"]) == EXPECTED_KEY and len(a["faces"]) == 48, str(len(a["faces"])))
        check("area normal == (0, 0, 1)", vclose(a["normal"], (0.0, 0.0, 1.0)), str(a["normal"]))
        check("area centroid == (0.4, 0.6, 0.0)", vclose(a["centroid"], (0.4, 0.6, 0.0)), str(a["centroid"]))
        check("area size_m == (0.4, 0.6)", vclose(a["size_m"], (0.4, 0.6)), str(a["size_m"]))
        check("area uvs cover all 35 vertices", len(a["uvs"]) == 35, str(len(a["uvs"])))
        check("area uv of (0.2, 0.3) == (0, 0)",
              vclose(a["uvs"][3 * (N + 1) + 2], (0.0, 0.0)), str(a["uvs"].get(3 * (N + 1) + 2)))
        check("area uv of (0.6, 0.9) == (1, 1)",
              vclose(a["uvs"][9 * (N + 1) + 6], (1.0, 1.0)), str(a["uvs"].get(9 * (N + 1) + 6)))

    # the stray survives when the filters are lowered — proof it was FILTERED,
    # not overlooked
    loose = pa.detect_areas(vertices, faces, uvs, sample_green, "picture",
                            min_area_m2=0.0, min_faces=1)
    check("detect_areas with loose filters finds both components",
          [len(x["faces"]) for x in loose] == [48, 1],
          str([len(x["faces"]) for x in loose]))

    # [7] magenta / glass
    g_areas = pa.detect_areas(vertices, faces, uvs, sample_magenta, "glass")
    check("glass: one area with the same 48 faces",
          len(g_areas) == 1 and set(g_areas[0]["faces"]) == EXPECTED_KEY,
          str([len(x["faces"]) for x in g_areas]))
    check("glass: kind is glass", bool(g_areas) and g_areas[0]["kind"] == "glass")
    check("glass sampler yields nothing for kind=picture",
          pa.detect_areas(vertices, faces, uvs, sample_magenta, "picture") == [])

    # [8] boundary edges
    edges = pa.area_edges(vertices, faces, sorted(EXPECTED_KEY))
    check("area_edges: 20 boundary edges", len(edges) == 20, str(len(edges)))
    perimeter = sum(math.dist(p, q) for p, q in edges)
    # 20 unit edges of 0.1 m = 2 * (0.4 + 0.6) = 2.0 m
    check("area_edges: perimeter == 2.0 m", close(perimeter, 2.0), str(perimeter))

    # [9] tilted plane — the Jacobi solver has to work for real
    tilted = [(x, y, 0.5 * x) for x in (0.0, 1.0, 2.0) for y in (0.0, 1.0, 2.0)]
    t_centroid, t_normal = pa.fit_plane(tilted)
    check("fit_plane tilted centroid == (1, 1, 0.5)", vclose(t_centroid, (1.0, 1.0, 0.5)), str(t_centroid))
    exp_n = (-1.0 / math.sqrt(5.0), 0.0, 2.0 / math.sqrt(5.0))
    check("fit_plane tilted normal == (-1, 0, 2)/sqrt(5)",
          vclose(t_normal, exp_n, 1e-9), f"{t_normal} != {exp_n}")

    print()
    if FAILURES:
        print(f"smoke_picture_areas: {len(FAILURES)} FAILED — {', '.join(FAILURES)}")
        return 1
    print("smoke_picture_areas: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
