#!/usr/bin/env python3
"""Smoke run for the picture-area maths (``app.core.picture_areas``).

Pure geometry, stdlib only, no world, no DB, no Blender: hand-built triangle
meshes with hand-built UVs and hand-written ``sample_rgb`` functions go
straight into the module. Every number below is derived BY HAND from the
rules.

MUTANTS THIS FILE KILLS (each one verified by actually running it):

  * ``hits >= 2`` weakened to ``>= 1`` or tightened to ``>= 3``  -> fixture B
  * ``components`` joined over shared VERTICES instead of edges  -> fixture C
  * ``min_faces`` filter removed                                 -> fixture A
  * ``min_area_m2`` filter removed                               -> fixture A
  * ``detect_areas`` sorted by face count instead of area        -> fixture A
  * ``planar_frame`` derived from the least-parallel world axis  -> fixture D
  * ``fit_plane`` returning the raw eigenvector for a degenerate
    cloud, or its sign convention flipped                        -> fixture E

MODEL SPACE IS glTF Y-UP (``docs/schnittstellen-3d.md``: ground = x/z, height
= y). A picture hangs on a WALL, so its normal lies in the x-z plane and its
height must come out along +y — fixture D is what pins that down.

==========================================================================
FIXTURE A — the plate, the stray and the speck (classification, components,
plane, UVs, filters, outline)
==========================================================================
A 1 m x 1 m plate in the XY plane at z = 0, cut into a 10 x 10 grid of
quads.  Vertex ``(i, j)`` (``i, j`` in 0..10, index ``j * 11 + i``) sits at
world ``(i/10, j/10, 0)`` and carries UV ``(i/10, j/10)`` — UVs ARE the grid
coordinates, so a UV rectangle is a world rectangle at the same numbers.
Quad ``(i, j)`` is two triangles::

    v00 = (i, j)   v10 = (i+1, j)   v11 = (i+1, j+1)   v01 = (i, j+1)
    tri A = (v00, v10, v11)         tri B = (v00, v11, v01)

so face index ``2 * (j * 10 + i)`` is A and ``+ 1`` is B — 200 faces,
121 vertices (0..120).

``sample_rgb`` answers GREEN inside the half-open UV rectangle
``u in [0.2, 0.6)`` and ``v in [0.3, 0.9)``, GREY everywhere else (the glass
case answers MAGENTA in the same rectangle).  Colours: green (0.1, 0.8, 0.1),
magenta (0.8, 0.1, 0.8), grey (0.5, 0.5, 0.5).  Against the 0..1 key rule
(``picture``: g > 0.39 and g > r + 0.12 and g > b + 0.12) green passes
(0.8 > 0.39, 0.8 > 0.22) and grey fails (0.5 > 0.62 is false); against the
``glass`` rule (r > 0.39 and b > 0.39 and g < r - 0.12 and g < b - 0.12)
magenta passes (0.8 > 0.39 twice, 0.1 < 0.68) and grey fails (0.5 < 0.38 is
false).

Two more key patches, both disconnected from the plate and from each other:

  STRAY — ONE big triangle at vertices 121..123, face index 200:
  (2.00, 2.00, 0), (2.60, 2.00, 0), (2.30, 2.60, 0); UVs (0.30, 0.40),
  (0.35, 0.40), (0.32, 0.45) — inside the green rectangle.  Area =
  1/2 * 0.6 * 0.6 = **0.18 m2** >= 0.02, but **1 face < 12**: it can only be
  removed by ``min_faces``.

  SPECK — a 3 x 4 grid of 0.03 m quads at x = 3.00 + 0.03 i, y = 0.03 j,
  z = 0 (i 0..3, j 0..4), vertices 124..143, faces 201..224, same
  triangulation, UVs (0.30 + 0.01 i, 0.40 + 0.01 j) — all inside the green
  rectangle.  24 faces >= 12, but area = 0.09 x 0.12 = **0.0108 m2 < 0.02**:
  it can only be removed by ``min_area_m2``.

Totals: 144 vertices, 225 faces.

[A1] WHICH FACES ARE KEY — 48 on the plate
------------------------------------------
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
   + 1 stray + 24 speck = **73** key faces overall.

[A2] COMPONENTS — over shared EDGES
-----------------------------------
Inside a quad, A and B share the diagonal ``v00-v11``.  Horizontally, quad
``(i, j)``'s A owns the edge ``v10-v11`` = the vertical grid line at
``i+1``, which is quad ``(i+1, j)``'s B edge ``v01-v00``.  Vertically, quad
``(i, j)``'s B owns ``v11-v01`` = the horizontal grid line at ``j+1``, which
is quad ``(i, j+1)``'s A edge ``v00-v10``.  So the 4 x 6 block is ONE
component of 48 faces, the speck one of 24 and the stray one of 1 — sorted
by face count descending: ``[48, 24, 1]``.

[A3] PLANE FIT — flat block
---------------------------
The block's unique vertices are the grid nodes ``i = 2..6`` (5 values) times
``j = 3..9`` (7 values) = 35 nodes, all at z = 0.  Centroid: mean of
``i/10`` over 2..6 = 4/10 = **0.4**; mean of ``j/10`` over 3..9 = 6/10 =
**0.6**; z = **0.0**.  The covariance's z row/column is all zero, so the
smallest eigenvalue is 0 with eigenvector ``(0, 0, 1)``; the two smallest
eigenvalues are far apart (0 vs. the x spread), so it is not degenerate, and
the sign rule (first non-zero of z, then y, then x must be positive) keeps
it: normal = **(0, 0, 1)**.

[A4] FRAME + UVs for that normal (see fixture D for the rule)
-------------------------------------------------------------
``n = (0,0,1)``: ``|n . up| = 0``, so ``u = normalize(up x n) =
(0,1,0) x (0,0,1) = (1, 0, 0)`` and ``v = n x u = (0,0,1) x (1,0,0) =
(0, 1, 0)``.  Projected onto that frame the block spans x 0.2..0.6 and
y 0.3..0.9, so ``size_m = (0.4, 0.6)`` and the corners map
``(0.2, 0.3, 0) -> (0, 0)`` and ``(0.6, 0.9, 0) -> (1, 1)``.

[A5] THE TWO FILTERS, EACH ON ITS OWN
-------------------------------------
    defaults (12 faces / 0.02 m2)  -> only the block         [48]
    min_faces=1 (area filter only) -> block + stray          [48, 1]
    min_area_m2=0 (face filter only) -> block + speck        [48, 24]
    both off                       -> all three              [48, 1, 24]

The last line is also the ORDER assertion: sorted by area descending the
run is 0.24 m2 (48 faces), 0.18 m2 (1 face), 0.0108 m2 (24 faces) — a sort
by face count would answer ``[48, 24, 1]``.

[A6] BOUNDARY EDGES
-------------------
The block is a 4 x 6 rectangle of quads.  Every diagonal is shared by the
two triangles of its quad, every interior grid edge by two triangles of
neighbouring quads — only the perimeter unit edges are used once:
``2 * (4 + 6) = 20`` boundary edges, total length ``20 * 0.1 = 2.0 m``.

==========================================================================
FIXTURE B — the 2-of-3 threshold at its boundary
==========================================================================
Four free-standing triangles, world position irrelevant (x = u, y = v,
z = 0), sampled by a HALF-PLANE: green for ``u < 0.5``, grey otherwise. The
three sample u values of a triangle are ``cu``, ``cu + (Au - cu)/3`` and
``cu + (Bu - cu)/3``.

  T3  A(0.10) B(0.20) C(0.30):  cu = 0.20; toward A 0.1667; toward B 0.20
      -> 3 of 3 green -> KEY
  T2  A(0.40) B(0.40) C(0.70):  cu = 1.50/3 = 0.50 (NOT < 0.5 -> grey);
      toward A = 0.50 - 0.10/3 = 0.4667 -> green; toward B likewise 0.4667
      -> exactly **2 of 3** -> KEY  (a ``>= 3`` rule would drop it)
  T1  A(0.30) B(0.60) C(0.75):  cu = 1.65/3 = 0.55 -> grey;
      toward A = 0.55 - 0.25/3 = 0.4667 -> green;
      toward B = 0.55 + 0.05/3 = 0.5667 -> grey
      -> exactly **1 of 3** -> NOT key  (a ``>= 1`` rule would take it)
  T0  A(0.80) B(0.90) C(0.95):  cu = 0.8833; 0.8556; 0.8889
      -> 0 of 3 -> NOT key

  => flags == [True, True, False, False]

==========================================================================
FIXTURE C — two patches meeting at ONE corner
==========================================================================
Triangle 0 = vertices (0, 1, 2), triangle 1 = vertices (2, 3, 4): they share
vertex 2 and NOTHING else — no pair of vertices in common, so no shared
edge.  Both flagged key.  Edge connectivity therefore gives TWO components
``[[0], [1]]``; vertex connectivity would fuse them into ``[[0, 1]]``.

==========================================================================
FIXTURE D — planar_frame is world-up driven (ruling R2)
==========================================================================
``u = normalize(up x n)``, ``v = n x u`` with ``up = (0, 1, 0)``; for a
HORIZONTAL plane (``|n . up| > 1 - 1e-6``) instead ``u`` = +x projected into
the plane, ``v = n x u``.  Cross products by hand:

    n = ( 1, 0, 0):  up x n = (0,1,0)x(1,0,0) = ( 0, 0,-1) = u
                     v = n x u = (1,0,0)x(0,0,-1) = ( 0, 1, 0)
    n = (-1, 0, 0):  up x n = ( 0, 0, 1) = u ;  v = (0, 1, 0)
    n = ( 0, 0, 1):  up x n = ( 1, 0, 0) = u ;  v = (0, 1, 0)
    n = ( 0, 0,-1):  up x n = (-1, 0, 0) = u ;  v = (0, 1, 0)
    n = ( 0, 1, 0):  horizontal -> u = ( 1, 0, 0);  v = n x u = (0, 0,-1)
    n = ( 0,-1, 0):  horizontal -> u = ( 1, 0, 0);  v = n x u = (0, 0, 1)
    n = (1,0,1)/sqrt2: up x n = (0,1,0)x(1,0,1)/sqrt2 = (1, 0,-1)/sqrt2 = u
                     v = n x u = 1/2 * ((1,0,1) x (1,0,-1)) = 1/2*(0,2,0)
                       = (0, 1, 0)

``v`` is world-up for every non-horizontal plane, and ``u x v == n`` holds
in all seven cases (right-handed).

THE ASSERTION THAT CATCHES THE OLD RULE — the same 0.4 m wide, 0.6 m tall
panel in two orientations:

    facing +z:  corners (0,0,0) (0.4,0,0) (0.4,0.6,0) (0,0.6,0)
                normal (0,0,1) -> u = +x, v = +y -> size_m = (0.4, 0.6)
    facing +x:  corners (0,0,0) (0,0,0.4) (0,0.6,0.4) (0,0.6,0)
                normal (1,0,0) -> u = (0,0,-1), v = (0,1,0);
                centroid (0, 0.3, 0.2); the four projections are
                (+0.2,-0.3) (-0.2,-0.3) (-0.2,+0.3) (+0.2,+0.3)
                -> size_m = (0.4, 0.6) TOO.

With the old "least-parallel world axis" rule the second case picked
u = (0,1,0), v = (0,0,1) and answered (0.6, 0.4) — the picture on its side.

==========================================================================
FIXTURE E — fit_plane, tilted and degenerate (ruling R3)
==========================================================================
[E1] Nine points on the plane ``z = 0.5 * x``: ``x, y in {0, 1, 2}``,
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
its eigenvalues are 7.5 and 0.  Eigenvalues sorted: 0, 6, 7.5 — the two
smallest differ by 6, far more than ``1e-9 * trace = 1.35e-8``, so the fit
is NOT degenerate.  The zero eigenvector solves ``6a + 3c = 0`` ->
``c = -2a`` -> direction ``(1, 0, -2)/sqrt(5)``.  The sign rule (z first)
flips it to::

    normal = (-1/sqrt(5), 0, 2/sqrt(5))
           = (-0.4472135954999579, 0.0, 0.8944271909999159)

[E2] Degenerate clouds fall back to ``(0, 0, 1)`` with the true centroid:
  * ``[]``                       -> centroid (0,0,0)
  * two points (0,0,0),(1,0,0)   -> centroid (0.5,0,0)   (< 3 points)
  * five times (1,1,1)           -> centroid (1,1,1); scatter is all zero,
    trace 0, so eigenvalue gap 0 <= 1e-9 * 0 -> degenerate
  * collinear (0,0,0) (1,1,1) (2,2,2) (3,3,3) -> centroid (1.5,1.5,1.5);
    scatter has ONE non-zero eigenvalue and two zeros, so the two smallest
    are equal -> degenerate (there is no unique plane through a line)

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

N = 10          # quads per edge of the plate
KEY_U = (0.2, 0.6)
KEY_V = (0.3, 0.9)
SQ2 = math.sqrt(2.0)


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
# Fixture A — plate + stray + speck
# --------------------------------------------------------------------------
def build_fixture_a():
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

    # STRAY: one big triangle, 0.18 m2, 1 face — only min_faces can drop it
    base = len(vertices)
    vertices.extend([(2.00, 2.00, 0.0), (2.60, 2.00, 0.0), (2.30, 2.60, 0.0)])
    uvs.extend([(0.30, 0.40), (0.35, 0.40), (0.32, 0.45)])
    faces.append((base, base + 1, base + 2))

    # SPECK: 3 x 4 quads of 0.03 m, 24 faces, 0.0108 m2 — only min_area can drop it
    base = len(vertices)
    for j in range(5):
        for i in range(4):
            vertices.append((3.00 + 0.03 * i, 0.03 * j, 0.0))
            uvs.append((0.30 + 0.01 * i, 0.40 + 0.01 * j))
    for j in range(4):
        for i in range(3):
            s00, s10 = base + j * 4 + i, base + j * 4 + i + 1
            s11, s01 = base + (j + 1) * 4 + i + 1, base + (j + 1) * 4 + i
            faces.append((s00, s10, s11))
            faces.append((s00, s11, s01))
    return vertices, faces, uvs


def make_sampler(key_rgb):
    def sample_rgb(u, v):
        if KEY_U[0] <= u < KEY_U[1] and KEY_V[0] <= v < KEY_V[1]:
            return key_rgb
        return GREY
    return sample_rgb


# the hand rule: quad (i, j) with 2 <= i <= 5 and 3 <= j <= 8, both triangles
EXPECTED_BLOCK = {
    2 * (j * N + i) + t
    for i in range(2, 6)
    for j in range(3, 9)
    for t in (0, 1)
}
STRAY_FACE = 200
SPECK_FACES = set(range(201, 225))
EXPECTED_KEY = EXPECTED_BLOCK | {STRAY_FACE} | SPECK_FACES


def part_a():
    vertices, faces, uvs = build_fixture_a()
    sample_green = make_sampler(GREEN)
    sample_magenta = make_sampler(MAGENTA)

    check("A: fixture is 225 faces / 144 vertices",
          len(faces) == 225 and len(vertices) == 144,
          f"{len(faces)} / {len(vertices)}")

    # [A1] classification
    flags = pa.classify_faces(faces, uvs, sample_green, "picture")
    got = {n for n, f in enumerate(flags) if f}
    check("A1: 48 block + 1 stray + 24 speck = 73 key faces", len(got) == 73, str(len(got)))
    check("A1: exactly the hand-derived faces", got == EXPECTED_KEY,
          f"extra={sorted(got - EXPECTED_KEY)[:5]} missing={sorted(EXPECTED_KEY - got)[:5]}")

    # [A2] components
    comps = pa.components(flags, faces)
    check("A2: components sized [48, 24, 1]",
          [len(c) for c in comps] == [48, 24, 1], str([len(c) for c in comps]))
    check("A2: the big one is the 4x6 block", set(comps[0]) == EXPECTED_BLOCK)
    check("A2: the speck is its own component", set(comps[1]) == SPECK_FACES)
    check("A2: the stray is its own component", comps[2] == [STRAY_FACE], str(comps[2]))

    # [A3] plane fit
    block_verts = sorted({v for n in comps[0] for v in faces[n]})
    check("A3: block has 35 unique vertices", len(block_verts) == 35, str(len(block_verts)))
    centroid, normal = pa.fit_plane([vertices[v] for v in block_verts])
    check("A3: centroid == (0.4, 0.6, 0.0)", vclose(centroid, (0.4, 0.6, 0.0)), str(centroid))
    check("A3: normal == (0, 0, 1)", vclose(normal, (0.0, 0.0, 1.0)), str(normal))

    # [A4] frame + planar uvs
    frame = pa.planar_frame(normal)
    check("A4: frame == ((1,0,0), (0,1,0))",
          vclose(frame[0], (1.0, 0.0, 0.0)) and vclose(frame[1], (0.0, 1.0, 0.0)), str(frame))
    pts = [vertices[v] for v in block_verts]
    puvs, size_m = pa.planar_uvs(pts, centroid, frame)
    check("A4: size_m == (0.4, 0.6)", vclose(size_m, (0.4, 0.6)), str(size_m))
    lo = block_verts.index(3 * (N + 1) + 2)      # grid node (2, 3) = (0.2, 0.3)
    hi = block_verts.index(9 * (N + 1) + 6)      # grid node (6, 9) = (0.6, 0.9)
    check("A4: corner (0.2, 0.3) -> (0, 0)", vclose(puvs[lo], (0.0, 0.0)), str(puvs[lo]))
    check("A4: corner (0.6, 0.9) -> (1, 1)", vclose(puvs[hi], (1.0, 1.0)), str(puvs[hi]))
    check("A4: all uvs inside 0..1",
          all(-1e-12 <= a <= 1 + 1e-12 and -1e-12 <= b <= 1 + 1e-12 for a, b in puvs))

    # [A5] detect_areas + the two filters, each on its own
    areas = pa.detect_areas(vertices, faces, uvs, sample_green, "picture")
    check("A5: defaults -> exactly one area", len(areas) == 1, str(len(areas)))
    if areas:
        a = areas[0]
        check("A5: kind == picture", a["kind"] == "picture", str(a.get("kind")))
        check("A5: the 48 block faces", set(a["faces"]) == EXPECTED_BLOCK, str(len(a["faces"])))
        check("A5: normal == (0, 0, 1)", vclose(a["normal"], (0.0, 0.0, 1.0)), str(a["normal"]))
        check("A5: centroid == (0.4, 0.6, 0.0)", vclose(a["centroid"], (0.4, 0.6, 0.0)), str(a["centroid"]))
        check("A5: size_m == (0.4, 0.6)", vclose(a["size_m"], (0.4, 0.6)), str(a["size_m"]))
        check("A5: area_m2 == 0.24", close(a["area_m2"], 0.24), str(a["area_m2"]))
        check("A5: uvs cover all 35 vertices", len(a["uvs"]) == 35, str(len(a["uvs"])))
        check("A5: uv of (0.2, 0.3) == (0, 0)",
              vclose(a["uvs"][3 * (N + 1) + 2], (0.0, 0.0)), str(a["uvs"].get(3 * (N + 1) + 2)))
        check("A5: uv of (0.6, 0.9) == (1, 1)",
              vclose(a["uvs"][9 * (N + 1) + 6], (1.0, 1.0)), str(a["uvs"].get(9 * (N + 1) + 6)))

    only_area = pa.detect_areas(vertices, faces, uvs, sample_green, "picture", min_faces=1)
    check("A5: min_faces=1 -> block + stray (min_area_m2 alone drops the speck)",
          [len(x["faces"]) for x in only_area] == [48, 1],
          str([len(x["faces"]) for x in only_area]))
    check("A5: the stray survives with 0.18 m2",
          len(only_area) == 2 and close(only_area[1]["area_m2"], 0.18),
          str([x["area_m2"] for x in only_area]))

    only_faces = pa.detect_areas(vertices, faces, uvs, sample_green, "picture", min_area_m2=0.0)
    check("A5: min_area_m2=0 -> block + speck (min_faces alone drops the stray)",
          [len(x["faces"]) for x in only_faces] == [48, 24],
          str([len(x["faces"]) for x in only_faces]))
    check("A5: the speck survives with 0.0108 m2",
          len(only_faces) == 2 and close(only_faces[1]["area_m2"], 0.0108),
          str([x["area_m2"] for x in only_faces]))

    loose = pa.detect_areas(vertices, faces, uvs, sample_green, "picture",
                            min_area_m2=0.0, min_faces=1)
    check("A5: both filters off -> [48, 1, 24] faces, i.e. sorted by AREA not count",
          [len(x["faces"]) for x in loose] == [48, 1, 24],
          str([len(x["faces"]) for x in loose]))

    # magenta / glass
    g_areas = pa.detect_areas(vertices, faces, uvs, sample_magenta, "glass")
    check("A5: glass -> one area with the same 48 faces",
          len(g_areas) == 1 and set(g_areas[0]["faces"]) == EXPECTED_BLOCK,
          str([len(x["faces"]) for x in g_areas]))
    check("A5: glass kind is glass", bool(g_areas) and g_areas[0]["kind"] == "glass")
    check("A5: a magenta texture yields nothing for kind=picture",
          pa.detect_areas(vertices, faces, uvs, sample_magenta, "picture") == [])

    # [A6] boundary edges
    edges = pa.area_edges(vertices, faces, sorted(EXPECTED_BLOCK))
    check("A6: 20 boundary edges", len(edges) == 20, str(len(edges)))
    check("A6: perimeter == 2.0 m",
          close(sum(math.dist(p, q) for p, q in edges), 2.0),
          str(sum(math.dist(p, q) for p, q in edges)))


# --------------------------------------------------------------------------
# Fixture B — the 2-of-3 threshold at its boundary
# --------------------------------------------------------------------------
def part_b():
    tri_uvs = [
        [(0.10, 0.00), (0.20, 0.10), (0.30, 0.05)],   # 3 of 3
        [(0.40, 0.00), (0.40, 0.10), (0.70, 0.05)],   # 2 of 3
        [(0.30, 0.00), (0.60, 0.10), (0.75, 0.05)],   # 1 of 3
        [(0.80, 0.00), (0.90, 0.10), (0.95, 0.05)],   # 0 of 3
    ]
    vertices, uvs, faces = [], [], []
    for tri in tri_uvs:
        base = len(vertices)
        for u, v in tri:
            vertices.append((u, v, 0.0))
            uvs.append((u, v))
        faces.append((base, base + 1, base + 2))

    def half_plane(u, v):
        return GREEN if u < 0.5 else GREY

    # the sample u values, hand-derived above
    two = sorted(s[0] for s in pa.face_samples(uvs, faces[1]))
    one = sorted(s[0] for s in pa.face_samples(uvs, faces[2]))
    check("B: T2 samples u == [0.4667, 0.4667, 0.50]",
          vclose(two, [4.2 / 9, 4.2 / 9, 0.5]), str(two))
    check("B: T1 samples u == [0.4667, 0.55, 0.5667]",
          vclose(one, [4.2 / 9, 0.55, 5.1 / 9]), str(one))

    flags = pa.classify_faces(faces, uvs, half_plane, "picture")
    check("B: 3-of-3 and 2-of-3 are key, 1-of-3 and 0-of-3 are not",
          flags == [True, True, False, False], str(flags))


# --------------------------------------------------------------------------
# Fixture C — two patches meeting at ONE corner
# --------------------------------------------------------------------------
def part_c():
    vertices = [(0.0, 0.0, 0.0), (0.3, 0.0, 0.0), (0.15, 0.3, 0.0),
                (0.45, 0.3, 0.0), (0.3, 0.6, 0.0)]
    faces = [(0, 1, 2), (2, 3, 4)]      # share vertex 2 and nothing else
    comps = pa.components([True, True], faces)
    check("C: a shared CORNER does not fuse two patches", comps == [[0], [1]], str(comps))


# --------------------------------------------------------------------------
# Fixture D — planar_frame is world-up driven (ruling R2)
# --------------------------------------------------------------------------
def part_d():
    cases = [
        ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
        ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
        ((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        ((0.0, 0.0, -1.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        ((0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, -1.0)),
        ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        ((1.0 / SQ2, 0.0, 1.0 / SQ2), (1.0 / SQ2, 0.0, -1.0 / SQ2), (0.0, 1.0, 0.0)),
    ]
    for n, exp_u, exp_v in cases:
        u, v = pa.planar_frame(n)
        check(f"D: frame for n={n} -> u={exp_u}, v={exp_v}",
              vclose(u, exp_u) and vclose(v, exp_v), f"got u={u} v={v}")
        # right-handed: u x v == n
        cx = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        check(f"D: right-handed for n={n}", vclose(cx, n), str(cx))

    # the same 0.4 x 0.6 panel in two orientations must measure the same
    def measure(corners):
        c, nrm = pa.fit_plane(corners)
        _, size = pa.planar_uvs(corners, c, pa.planar_frame(nrm))
        return nrm, size

    n_z, size_z = measure([(0.0, 0.0, 0.0), (0.4, 0.0, 0.0), (0.4, 0.6, 0.0), (0.0, 0.6, 0.0)])
    n_x, size_x = measure([(0.0, 0.0, 0.0), (0.0, 0.0, 0.4), (0.0, 0.6, 0.4), (0.0, 0.6, 0.0)])
    check("D: wall panel facing +z -> normal (0,0,1), size_m (0.4, 0.6)",
          vclose(n_z, (0.0, 0.0, 1.0)) and vclose(size_z, (0.4, 0.6)), f"{n_z} {size_z}")
    check("D: the SAME panel facing +x -> normal (1,0,0), size_m (0.4, 0.6) too",
          vclose(n_x, (1.0, 0.0, 0.0)) and vclose(size_x, (0.4, 0.6)), f"{n_x} {size_x}")


# --------------------------------------------------------------------------
# Fixture E — fit_plane, tilted and degenerate (ruling R3)
# --------------------------------------------------------------------------
def part_e():
    tilted = [(x, y, 0.5 * x) for x in (0.0, 1.0, 2.0) for y in (0.0, 1.0, 2.0)]
    c, n = pa.fit_plane(tilted)
    check("E1: tilted centroid == (1, 1, 0.5)", vclose(c, (1.0, 1.0, 0.5)), str(c))
    exp = (-1.0 / math.sqrt(5.0), 0.0, 2.0 / math.sqrt(5.0))
    check("E1: tilted normal == (-1, 0, 2)/sqrt(5)", vclose(n, exp), f"{n} != {exp}")

    c, n = pa.fit_plane([])
    check("E2: no points -> ((0,0,0), (0,0,1))",
          vclose(c, (0.0, 0.0, 0.0)) and vclose(n, (0.0, 0.0, 1.0)), f"{c} {n}")
    c, n = pa.fit_plane([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])
    check("E2: two points -> centroid (0.5,0,0), normal (0,0,1)",
          vclose(c, (0.5, 0.0, 0.0)) and vclose(n, (0.0, 0.0, 1.0)), f"{c} {n}")
    c, n = pa.fit_plane([(1.0, 1.0, 1.0)] * 5)
    check("E2: a repeated point -> centroid (1,1,1), normal (0,0,1)",
          vclose(c, (1.0, 1.0, 1.0)) and vclose(n, (0.0, 0.0, 1.0)), f"{c} {n}")
    c, n = pa.fit_plane([(0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (2.0, 2.0, 2.0), (3.0, 3.0, 3.0)])
    check("E2: collinear points -> centroid (1.5,1.5,1.5), normal (0,0,1)",
          vclose(c, (1.5, 1.5, 1.5)) and vclose(n, (0.0, 0.0, 1.0)), f"{c} {n}")


# --------------------------------------------------------------------------
# the colour rule itself
# --------------------------------------------------------------------------
def part_colour():
    check("colour: green is picture", pa.is_key_colour(GREEN, "picture") is True)
    check("colour: grey is not picture", pa.is_key_colour(GREY, "picture") is False)
    check("colour: magenta is glass", pa.is_key_colour(MAGENTA, "glass") is True)
    check("colour: grey is not glass", pa.is_key_colour(GREY, "glass") is False)
    check("colour: green is not glass", pa.is_key_colour(GREEN, "glass") is False)
    try:
        pa.is_key_colour(GREEN, "wallpaper")
        check("colour: is_key_colour rejects an unknown kind", False)
    except ValueError:
        check("colour: is_key_colour rejects an unknown kind", True)
    try:
        pa.classify_faces([(0, 1, 2)], [(0.0, 0.0)] * 3, lambda u, v: GREEN, "wallpaper")
        check("colour: classify_faces rejects an unknown kind", False)
    except ValueError:
        check("colour: classify_faces rejects an unknown kind", True)

    samples = pa.face_samples([(0.0, 0.0), (0.3, 0.0), (0.0, 0.3)], (0, 1, 2))
    check("colour: face_samples returns 3 points", len(samples) == 3, str(samples))


def main():
    print("smoke_picture_areas")
    part_colour()
    part_a()
    part_b()
    part_c()
    part_d()
    part_e()
    print()
    if FAILURES:
        print(f"smoke_picture_areas: {len(FAILURES)} FAILED — {', '.join(FAILURES)}")
        return 1
    print("smoke_picture_areas: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
