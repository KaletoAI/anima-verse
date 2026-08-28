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

==========================================================================
FIXTURE F — the DOOR: a ring of four boxes around a set-back plate
(spec-picture-props.md § 6, D7 — the leaf heuristic)
==========================================================================
Five closed boxes, 8 shared vertices and 12 outward-wound triangles each
(front/back/left/right/bottom/top, two triangles per face), all in glTF
y-up model space; the four FRAME bars first, the PLATE last:

    left bar    x 0.0..0.1   y 0.0..2.2   z -0.05..0.02    faces  0..11
    right bar   x 0.9..1.0   y 0.0..2.2   z -0.05..0.02    faces 12..23
    bottom bar  x 0.1..0.9   y 0.0..0.1   z -0.05..0.02    faces 24..35
    top bar     x 0.1..0.9   y 2.1..2.2   z -0.05..0.02    faces 36..47
    plate       x 0.1..0.9   y 0.1..2.1   z -0.02..0.00    faces 48..59

The bars' fronts stand at z = 0.02, the plate's front at z = 0.00 — the
plate is SET BACK 2 cm, its back at -0.02. The bars are 7 cm deep, so a
bar's SIDE face (0.07 x 2.2 = 0.154 m2) stays smaller than its front
(0.22 m2) — at 12 cm it would not, and the side would become the largest
cluster of fixture F7. Nothing shares a vertex with anything else (40
vertices, 60 triangles).

[F1] THE LEAF PLANE = the largest planar cluster.  Coplanar clusters are
connected over shared edges with the same normal (cos >= 0.95) and the same
offset (+-2 cm).  Areas: plate front 0.8 x 2.0 = 1.6 m2, plate back the
same 1.6 m2, each vertical bar front 0.1 x 2.2 = 0.22, each horizontal bar
front 0.8 x 0.1 = 0.08.  The tie between the plate's front and back is
broken towards +z (then +y, then +x — the same preference as
``fit_plane``'s sign rule): normal (0, 0, 1), offset 0.0.  ``planar_frame``
of that normal is u = (1, 0, 0), v = (0, 1, 0) (fixture D).

[F2] SILHOUETTE + FRAME THICKNESS.  Every vertex projected on (u, v) spans
(0, 0)..(1.0, 2.2).  The rim rule per side: faces that DEVIATE from the
leaf plane (normal off by more than the cosine, or depth off by more than
2 cm), whose centre sits in the middle half of the OTHER axis and less than
25 % of this axis in from the edge; the inset is the face's innermost
vertex.  Left side (band y 0.55..1.65): the left bar's back, inner side and
inner side face reach x = 0.1 (its front at depth 0.02 does NOT deviate:
0.02 <= tol; its outer side face reaches only x = 0, and an inset <= tol
is no rim — the outermost faces of any model deviate at inset 0), the
plate's left edge face (x = 0.1, normal -x) too; the plate's front/back
centres sit 0.37+ in (excluded), the right bar 0.9+ (excluded) -> 0.1.
Right, bottom (band x 0.25..0.75: the bottom bar's back/top faces and the
plate's bottom edge reach y = 0.1) and top likewise
-> thickness (0.1, 0.1, 0.1, 0.1) and

    inner_rect(((0, 0), (1.0, 2.2)), 0.1) == ((0.1, 0.1), (0.9, 2.1))

[F3] THE FRAME FRONT = the largest cluster facing the leaf plane whose
centre lies OUTSIDE the inner rectangle: a vertical bar's front, 0.22 m2,
at depth 0.02.

[F4] leaf_candidates: the SEED is every face facing +z within 2 cm of
z = 0 whose centre lies strictly inside the inner rectangle — the plate's
two front triangles (centres (0.633, 1.433) and (0.367, 0.767)); the bars'
fronts sit at depth 0.02 (inside the tolerance!) but their centres lie
outside the rectangle (x 0.05 / 0.95, y 0.05 / 2.15).  From the seed the
selection grows over shared edges into every face that is not the frame
front (facing +z within 2 cm of depth 0.02 — the plate's BACK faces -z and
is never one, whatever its depth), whose vertices all lie inside the
SEED's own extent (0.1, 0.1)..(0.9, 2.1) widened by 2 cm and no more than
2 cm proud of the leaf plane:
the plate's four edge faces and its back — and nothing of the bars, which
share no edge with the plate.  => exactly faces 48..59 (the 12 plate
triangles), ascending.  Seed share 1.6 / (1.0 * 2.2) = 0.727 >= 0.30.

[F5] leaf_bbox over those faces' vertices:
    min (0.1, 0.1, -0.02)   max (0.9, 2.1, 0.0)

[F6] THE FALLBACK: the plate ALONE (one box, faces 0..11).  Its edge
faces deviate, but they sit ON the silhouette edge (inset 0 <= tol) and
its back is not in any band's 25 % -> no side has a rim -> every side
falls back to 8 % of the silhouette width 0.8 = 0.064; inner =
(0.164, 0.164)..(0.736, 2.036); the front's centres (0.633, 1.433) and
(0.367, 0.767) are still inside -> the seed is the front, and the growth
takes the edges and the back: it is bounded by the SEED's extent
(0.1..0.9 x 0.1..2.1) + 2 cm, not by the guessed inner rectangle (which
would cut the edges at x = 0.1 off), and the back faces -z, so it is not
the frame front (the leaf plane itself here) -> the leaf is the whole box,
share 1.6 / 1.6 = 1.0, bbox as the box.

[F7] THE 30 % GATE: the four bars alone (no plate) — the largest cluster
is a vertical bar's front (0.22 m2, offset 0.02; the side faces are
0.154 m2, see above); the silhouette is 1.0 x 2.2; the rim rule (the
bars' backs at depth -0.07 deviate) gives 0.1 all round; the bar fronts'
centres sit at x 0.05 / 0.95 or y < 0.1 / > 2.1 — nothing faces +z inside
(0.1..0.9, 0.1..2.1) -> no seed -> ``leaf_candidates`` is ``[]`` and
``detect_leaf`` answers None.

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


# ---------------------------------------------------------------------------
# FIXTURE F — the door
# ---------------------------------------------------------------------------
def box(x0, x1, y0, y1, z0, z1, verts, faces):
    """One closed box, 8 shared vertices, 12 outward-wound triangles."""
    b = len(verts)
    verts += [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
              (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    for tri in ((4, 5, 6), (4, 6, 7),     # front  +z
                (0, 2, 1), (0, 3, 2),     # back   -z
                (0, 4, 7), (0, 7, 3),     # left   -x
                (1, 2, 6), (1, 6, 5),     # right  +x
                (0, 1, 5), (0, 5, 4),     # bottom -y
                (3, 7, 6), (3, 6, 2)):    # top    +y
        faces.append(tuple(b + i for i in tri))


def build_door(bars=True, plate=True):
    verts, faces = [], []
    if bars:
        box(0.0, 0.1, 0.0, 2.2, -0.05, 0.02, verts, faces)
        box(0.9, 1.0, 0.0, 2.2, -0.05, 0.02, verts, faces)
        box(0.1, 0.9, 0.0, 0.1, -0.05, 0.02, verts, faces)
        box(0.1, 0.9, 2.1, 2.2, -0.05, 0.02, verts, faces)
    if plate:
        box(0.1, 0.9, 0.1, 2.1, -0.02, 0.00, verts, faces)
    return verts, faces


def part_f():
    print("[F] the door: ring of four bars around a set-back plate")
    verts, faces = build_door()
    check("F: 40 vertices, 60 triangles", (len(verts), len(faces)) == (40, 60),
          str((len(verts), len(faces))))
    normals = pa.face_normals(verts, faces)
    check("F: the plate's first front triangle faces +z",
          vclose(normals[48], (0, 0, 1)), str(normals[48]))

    print("  [F1] the leaf plane is the largest planar cluster, +z wins the tie")
    clusters = pa.planar_clusters(verts, faces, normals)
    top = clusters[0] if clusters else {}
    check("F1: largest cluster = the plate front, 2 faces, 1.6 m2",
          top.get("faces") == [48, 49] and close(top.get("area", 0), 1.6),
          str({k: top.get(k) for k in ("faces", "area")}))
    check("F1: normal (0, 0, 1), offset 0",
          vclose(top.get("normal", (9, 9, 9)), (0, 0, 1))
          and close(top.get("offset", 9), 0.0), str(top))
    check("F1: the plate back is the runner-up (same area, -z)",
          len(clusters) > 1 and clusters[1]["faces"] == [50, 51]
          and vclose(clusters[1]["normal"], (0, 0, -1)), str(clusters[1:2]))

    print("  [F2] inner_rect + the rim rule")
    check("F2: inner_rect(((0,0),(1,2.2)), 0.1) == ((0.1,0.1),(0.9,2.1))",
          pa.inner_rect(((0.0, 0.0), (1.0, 2.2)), 0.1) == ((0.1, 0.1), (0.9, 2.1)),
          str(pa.inner_rect(((0.0, 0.0), (1.0, 2.2)), 0.1)))
    check("F2: inner_rect with per-side thickness (0.1, 0, 0.1, 0.2)",
          pa.inner_rect(((0.0, 0.0), (1.0, 2.2)), (0.1, 0.0, 0.1, 0.2))
          == ((0.1, 0.0), (0.9, 2.0)),
          str(pa.inner_rect(((0.0, 0.0), (1.0, 2.2)), (0.1, 0.0, 0.1, 0.2))))
    plane = pa.leaf_plane(verts, faces, normals)
    check("F2: silhouette bbox (0,0)..(1.0,2.2)",
          plane is not None and vclose(plane["bbox2d"][0], (0, 0))
          and vclose(plane["bbox2d"][1], (1.0, 2.2)), str(plane and plane["bbox2d"]))
    check("F2: frame thickness 0.1 on all four sides",
          plane is not None and all(close(t, 0.1) for t in plane["thickness"]),
          str(plane and plane["thickness"]))
    check("F2: inner rectangle (0.1,0.1)..(0.9,2.1)",
          plane is not None and vclose(plane["inner"][0], (0.1, 0.1))
          and vclose(plane["inner"][1], (0.9, 2.1)), str(plane and plane["inner"]))

    print("  [F3] the frame front")
    check("F3: front_offset 0.02 (a vertical bar's front)",
          plane is not None and close(plane["front_offset"], 0.02),
          str(plane and plane["front_offset"]))

    print("  [F4] leaf_candidates (the v1 skin heuristic) = exactly the plate's 12 triangles")
    cand = pa.leaf_candidates(verts, faces, normals, plane)
    check("F4: faces 48..59", cand == list(range(48, 60)), str(cand))
    print("  [F4b] prism_faces over the inner rect along +z = the same 12 (E2)")
    prism = pa.prism_faces(verts, faces, plane["inner"], plane["normal"])
    check("F4b: faces 48..59 — the plate's edge faces sit ON the inner rect's "
          "edge and point OUT of it, the bars' jamb faces point IN",
          prism == list(range(48, 60)), str(prism))

    print("  [F5] detect_leaf + leaf_bbox")
    leaf = pa.detect_leaf(verts, faces)
    check("F5: detect_leaf finds the same 12 faces",
          leaf is not None and leaf["faces"] == list(range(48, 60)), str(leaf and leaf["faces"]))
    check("F5: bbox min (0.1, 0.1, -0.02)",
          leaf is not None and vclose(leaf["bbox"][0], (0.1, 0.1, -0.02)), str(leaf and leaf["bbox"]))
    check("F5: bbox max (0.9, 2.1, 0.0)",
          leaf is not None and vclose(leaf["bbox"][1], (0.9, 2.1, 0.0)), str(leaf and leaf["bbox"]))
    check("F5: seed share 1.6 / 2.2 = 0.727",
          leaf is not None and close(leaf["share"], 1.6 / 2.2, 1e-6), str(leaf and leaf["share"]))
    check("F5: bbox_of over the same faces agrees",
          vclose(pa.bbox_of(verts, faces, cand)[0], (0.1, 0.1, -0.02))
          and vclose(pa.bbox_of(verts, faces, cand)[1], (0.9, 2.1, 0.0)))

    print("  [F6] no rim to measure: the plate alone")
    pv, pf = build_door(bars=False)
    alone = pa.detect_leaf(pv, pf)
    # E2: nothing deviates from the leaf plane near any edge, so there is no
    # frame — the rim is 0 on every side and the silhouette is the footprint
    # (v1 shrank it by 8 % to find a seed strictly inside; the prism needs
    # no seed, and that shrink would cut the leaf's own edge faces off).
    check("F6: no rim measurable -> 0 on every side",
          alone is not None and all(close(t, 0.0) for t in alone["plane"]["thickness"]),
          str(alone and alone["plane"]["thickness"]))
    check("F6: the whole box is the leaf, share 1.0",
          alone is not None and alone["faces"] == list(range(12)) and close(alone["share"], 1.0),
          str(alone and (alone["faces"], alone["share"])))

    print("  [F7] the 30 % gate: bars without a plate find no leaf")
    bv, bf = build_door(plate=False)
    bplane = pa.leaf_plane(bv, bf, pa.face_normals(bv, bf))
    check("F7: the largest cluster is a bar front at 0.02",
          bplane is not None and close(bplane["offset"], 0.02), str(bplane and bplane["offset"]))
    check("F7: leaf_candidates is empty",
          bplane is not None and pa.leaf_candidates(bv, bf, pa.face_normals(bv, bf), bplane) == [])
    check("F7: detect_leaf answers None", pa.detect_leaf(bv, bf) is None)


# ---------------------------------------------------------------------------
# FIXTURE G — the two-skin door (spec-bild-props-v2.md E2)
# ---------------------------------------------------------------------------
# The four bars of F (faces 0..47, z -0.05..0.02), a LEAF SLAB with a front
# skin, a back skin and four edge faces — x 0.1..0.9, y 0.1..2.1,
# z -0.04..0.00, faces 48..59 — and a FRAME BACK SKIN WITHOUT A HOLE: a plane
# at z = -0.05 over the whole silhouette (0..1) x (0..2.2) as a 10 x 22 grid
# of 0.1 m quads facing -z, faces 60..499 (quad (i, j), i 0..9 along x,
# j 0..21 along y, tris 60 + 2 * (10 j + i) and + 1). 32 + 8 + 253 = 293
# vertices, 500 triangles. That back skin is what an img2mesh door carries: the leaf's
# back is part of one continuous rear surface, and the measured door had
# 979 frame triangles in exactly that place (befunde 2026-08-28, Wurzel 2).
#
# BY HAND:
#   leaf plane   = the largest planar cluster = the back skin (2.2 m2 > the
#                  slab front's 1.6): normal (0, 0, -1), offset 0.05; frame
#                  u = up x n = (-1, 0, 0), v = n x u = (0, 1, 0); silhouette
#                  u -1..0, v 0..2.2.
#   rim          = 0.1 on every side (the bars and the slab's edges reach in
#                  0.1; the slab's skins are more than a quarter in and do
#                  not measure) -> inner (-0.9, 0.1) .. (-0.1, 2.1), i.e.
#                  x 0.1..0.9, y 0.1..2.1.
#   PRISM        = every face whose centre projects inside that rect, ANY
#                  depth, ANY normal: the slab's front and back (centres x
#                  0.367 / 0.633), its four edge faces (centres ON the rect's
#                  edge, normals pointing OUT of it), and the back skin's
#                  inner 8 x 20 quads (i 1..8, j 1..20: centres at i/10 +
#                  0.033 / 0.067, all strictly inside) = 320 tris. NOT the
#                  bars (centres at x 0.05 / 0.95, y 0.05 / 2.15), NOT their
#                  jamb faces (centres ON the edge, normals pointing IN), NOT
#                  the back skin's outer ring (centres at 0.033 / 0.067 off
#                  the silhouette edge). 332 faces.
#   leaf_bbox    = (0.1, 0.1, -0.05) .. (0.9, 2.1, 0.0): the inner grid
#                  vertices span 0.1..0.9 x 0.1..2.1 like the slab.
#   share        = coplanar faces of the prism (facing -z within 2 cm of z =
#                  -0.05): the 320 inner grid tris (1.6 m2) + the slab's back
#                  at z = -0.04 (1.6 m2) = 3.2 over the silhouette's 2.2.
#   v1 heuristic = leaf_candidates on the same plane: the seed ties between
#                  the inner grid (1.6) and the slab's back (1.6) and falls to
#                  the smaller first index (the slab back, 50); the back skin
#                  is the "frame front" of that plane and not edge-connected
#                  to the slab -> the 12 slab faces only. The prism differs
#                  by exactly the 320 back-skin faces.
#   residual     = after the split the frame holds no face whose centre lies
#                  more than 2 cm inside the leaf's outline (the outline of
#                  its face centres, x 0.1..0.9, y 0.1..2.1): 0. Leave the
#                  central quad (4, 10) — tris 60 + 2 * 104 = 268, 269,
#                  centres (0.433, 1.067) / (0.467, 1.033) — in the frame
#                  and it is 2.
#   leaf_prism   = a listed face's own prism: ONE front triangle of the
#                  slab — 48 = (0.1, 0.1), (0.9, 0.1), (0.9, 2.1), centre
#                  (19/30, 23/30) — has a footprint that is that point
#                  (widened by a hair). Faces whose centre projects onto
#                  it: its back twin 50 (the same three x/y at z -0.04) and
#                  ONE back-skin triangle — the grid's first-type centres
#                  are ((3i+1)/30, (3j+2)/30), so i = 6, j = 7: quad (6, 7),
#                  tri 60 + 2 * 76 = 212 — the same column, so the same
#                  prism -> [48, 50, 212].
def build_door_g():
    verts, faces = build_door(plate=False)
    box(0.1, 0.9, 0.1, 2.1, -0.04, 0.00, verts, faces)
    b = len(verts)
    for j in range(23):
        for i in range(11):
            verts.append((i / 10.0, j / 10.0, -0.05))
    for j in range(22):
        for i in range(10):
            v00 = b + j * 11 + i
            v10, v01, v11 = v00 + 1, v00 + 11, v00 + 12
            faces.append((v00, v01, v11))     # facing -z
            faces.append((v00, v11, v10))
    return verts, faces


def part_g():
    print("[G] the two-skin door: the leaf is a PRISM through the whole door")
    verts, faces = build_door_g()
    check("G: 293 vertices, 500 triangles", (len(verts), len(faces)) == (293, 500),
          str((len(verts), len(faces))))
    normals = pa.face_normals(verts, faces)
    check("G: the back skin faces -z", vclose(normals[60], (0, 0, -1)) and vclose(normals[499], (0, 0, -1)),
          str((normals[60], normals[499])))
    inner_quads = [j * 10 + i for j in range(1, 21) for i in range(1, 9)]
    skin_inner = sorted(60 + 2 * q + d for q in inner_quads for d in (0, 1))
    expected = list(range(48, 60)) + skin_inner
    check("G: 332 expected prism faces by hand", len(expected) == 332, str(len(expected)))

    print("  [G1] the leaf plane is the back skin, the rim is 0.1 all round")
    plane = pa.leaf_plane(verts, faces, normals)
    check("G1: normal (0, 0, -1), offset 0.05",
          plane is not None and vclose(plane["normal"], (0, 0, -1)) and close(plane["offset"], 0.05),
          str(plane and (plane["normal"], plane["offset"])))
    check("G1: thickness 0.1 on every side",
          plane is not None and all(close(t, 0.1) for t in plane["thickness"]),
          str(plane and plane["thickness"]))
    check("G1: inner (-0.9, 0.1)..(-0.1, 2.1) in the (u, v) frame",
          plane is not None and vclose(plane["inner"][0], (-0.9, 0.1))
          and vclose(plane["inner"][1], (-0.1, 2.1)), str(plane and plane["inner"]))

    print("  [G2] prism_faces = slab + the back skin behind it, whatever the axis sign")
    prism = pa.prism_faces(verts, faces, plane["inner"], plane["normal"])
    check("G2: 332 faces along the plane normal (-z)", prism == expected,
          f"{len(prism)} faces; first/last {prism[:1]}..{prism[-1:]}")
    prism_z = pa.prism_faces(verts, faces, ((0.1, 0.1), (0.9, 2.1)), (0.0, 0.0, 1.0))
    check("G2: the same 332 along +z with the rect in x/y", prism_z == expected,
          str(len(prism_z)))
    check("G2: no bar face, no jamb face, no outer-ring face",
          not any(k < 48 for k in prism) and not any(60 + 2 * (j * 10 + i) + d in prism
                                                     for j in range(22) for i in range(10)
                                                     for d in (0, 1)
                                                     if i in (0, 9) or j in (0, 21)))

    print("  [G3] the v1 skin heuristic would have missed the back skin")
    old = pa.leaf_candidates(verts, faces, normals, plane)
    check("G3: leaf_candidates = the 12 slab faces only", old == list(range(48, 60)), str(old[:14]))
    check("G3: the prism adds exactly the 320 back-skin faces",
          sorted(set(prism) - set(old)) == skin_inner and not set(old) - set(prism))

    print("  [G4] detect_leaf + leaf_bbox + share")
    leaf = pa.detect_leaf(verts, faces)
    check("G4: detect_leaf = the prism", leaf is not None and leaf["faces"] == expected,
          str(leaf and len(leaf["faces"])))
    check("G4: bbox (0.1, 0.1, -0.05)..(0.9, 2.1, 0)",
          leaf is not None and vclose(leaf["bbox"][0], (0.1, 0.1, -0.05))
          and vclose(leaf["bbox"][1], (0.9, 2.1, 0.0)), str(leaf and leaf["bbox"]))
    check("G4: share 3.2 / 2.2", leaf is not None and close(leaf["share"], 3.2 / 2.2, 1e-6),
          str(leaf and leaf["share"]))

    print("  [G5] leaf_residual: frame faces more than 2 cm inside the leaf's outline")
    frame = [k for k in range(len(faces)) if k not in set(expected)]
    check("G5: a clean prism split leaves 0", pa.leaf_residual(verts, faces, expected, frame) == 0,
          str(pa.leaf_residual(verts, faces, expected, frame)))
    short = [k for k in expected if k not in (268, 269)]
    check("G5: the central quad left behind counts 2",
          pa.leaf_residual(verts, faces, short, frame + [268, 269]) == 2,
          str(pa.leaf_residual(verts, faces, short, frame + [268, 269])))
    check("G5: the bars' jamb faces (ON the outline) never count",
          pa.leaf_residual(verts, faces, expected, list(range(48))) == 0)

    print("  [G6] leaf_prism: a face list becomes the prism through its own footprint")
    through = pa.leaf_prism(verts, faces, [48])               # ONE front triangle
    check("G6: one front triangle reaches its back twin and the grid tri in its column: [48, 50, 212]",
          through == [48, 50, 212], str(through))
    check("G6: the listed faces are always part of their own prism",
          set(expected) <= set(pa.leaf_prism(verts, faces, expected)))
    check("G6: an empty list is an empty prism", pa.leaf_prism(verts, faces, []) == [])


def main():
    print("smoke_picture_areas")
    part_colour()
    part_f()
    part_g()
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
