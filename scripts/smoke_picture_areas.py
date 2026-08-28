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
  * the two-class gate of ``thickness_footprint`` dropped (every
    mesh gets a footprint)                                       -> fixtures I, F6, F7
  * the per-side edge refinement dropped (every edge stays one
    raster cell inside the leaf)                             -> fixtures F, G, G', H
  * the snap onto the nearest vertex coordinate dropped         -> fixtures F, G, G'
    (the footprint then misses the leaf's own edge faces, which
    sit ON the leaf edge and are only admitted when it is EXACT)

NOT KILLED BY ANY FIXTURE, and measured to be so (2026-08-28): taking EVERY
thick cell as frame instead of only the thick region CONNECTED TO THE
BORDER.  The footprint is a BOUNDING rectangle and a bounding rectangle
cannot see an enclosed island — fixture H's lock rail and handle are thick
and sit inside the leaf, and dropping the connectivity walk changes neither
the rectangle nor the 84 prism faces, on the fixture or on any of the four
measured wooden doors.  (It cannot: a thick island that would shorten a
side has to span a whole edge row of the leaf, and spanning it means
touching the jambs, which is what makes it border-connected in the first
place.)  The walk is kept because it is what the word "frame" MEANS here,
not because a fixture can tell the difference.

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

[F2] SILHOUETTE + THE THICKNESS FOOTPRINT.  Every vertex projected on
(u, v) spans (0, 0)..(1.0, 2.2), so the raster cell is 0.025 * 2.2 = 0.055 m
and the grid is ceil(1.0/0.055) x ceil(2.2/0.055) = 19 x 40 cells.  MATERIAL
THICKNESS per cell = max - min of the sampled surface points' depth: the
bars run z -0.05..0.02 -> 0.07, the plate z -0.02..0 -> 0.02, and a cell
holding both (the columns/rows where they meet) reads 0.07.  So there are
exactly two values; Otsu splits them at (0.02 + 0.07) / 2 = **0.045** with
m_thin = 0.02 and m_thick = 0.07 -> ratio 3.5 >= 1.3, difference 0.05 >=
0.015 -> a frame exists.

The bars fill the cell columns 0..1 (x 0..0.1, and x = 0.1 falls in column
1 = 0.055..0.11) and 16..18 (x 0.9..1.0), plus the rows 0..1 and 38..39;
each of those cells touches the outermost row or column, so the border BFS
takes exactly them.  The leaf cells are the rest: columns 2..15 x rows
2..37 = 14 * 36 = 504 of the 760 cells (thin share 0.663 >= 0.30) ->
COARSE rectangle 0.11..0.88 x 0.11..2.09.

EDGE REFINEMENT at fine = 0.055 / 5 = 0.011, band = the middle half of the
coarse rectangle:
  left   the fine column 0.099..0.11 holds the left bar's and the plate's
         faces at x = 0.1 -> 0.07, not thin -> the edge stays at 0.11.
  right  0.88..0.891 holds plate skin only (0.02) -> thin, the edge moves
         to 0.891; 0.891..0.902 holds x = 0.9 (bar and plate) -> 0.07,
         stop.
  bottom 0.099..0.11 holds y = 0.1 (bottom bar and plate) -> stop at 0.11.
  top    2.09..2.101 holds y = 2.1 -> stop at 2.09.
SNAP each edge onto the nearest vertex coordinate within +-0.011:
0.11 -> 0.1 (0.010), 0.891 -> 0.9 (0.009), 0.11 -> 0.1, 2.09 -> 2.1 (0.010)

    thickness_footprint(...) == ((0.1, 0.1), (0.9, 2.1))

— EXACTLY the plate's own coordinates, which is what lets ``prism_faces``'
edge rule admit the plate's four edge faces (normals pointing OUT of the
footprint) and reject the bars' jamb faces (pointing IN).

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

[F6] A BARE LEAF IS NOT A DOOR: the plate ALONE (one box, faces 0..11).
Every non-empty cell reads the same 0.02, so Otsu's two classes have the
same mean: the difference 0 is below 0.015 and the ratio 1.0 below 1.3.
No thickness split, no frame, no footprint -> ``thickness_footprint`` is
None, ``leaf_plane`` is None and ``detect_leaf`` answers None (the Blender
side reports "no leaf", exactly as it does for a glass door).

[F7] THE SAME GATE FROM THE OTHER SIDE: the four bars alone (no plate).
The largest cluster is a vertical bar's front (0.22 m2, offset 0.02; the
side faces are 0.154 m2, see above).  The hole in the middle is EMPTY —
no surface, no thickness — and every cell that does hold material reads
0.07, so again there is only one class: ``detect_leaf`` answers None, now
at the footprint instead of at the 30 % share gate.  ``leaf_candidates``
(v1, kept as the reference) still answers ``[]`` for a plane built by
hand.

==========================================================================
FIXTURE H — the MEASURED wooden door (plan-blatt-dicke.md, 2026-08-28)
==========================================================================
The shape the thickness method was designed on, rebuilt from closed boxes
in the model metres of "Door - wood old" variant 2 (a mesh normalised to
1 m height).  Silhouette x 0..0.585, y 0..1.0; ten boxes:

    left jamb    x 0.000..0.075  y 0.000..1.000  z -0.075..0.075   0.15
    right jamb   x 0.510..0.585  y 0.000..1.000  z -0.075..0.075   0.15
    lintel       x 0.000..0.585  y 0.925..1.000  z -0.075..0.075   0.15
    leaf filling x 0.075..0.510  y 0.000..0.925  z -0.010..0.010   0.02
    frieze left  x 0.075..0.150  y 0.000..0.925  z -0.020..0.020   0.04
    frieze right x 0.435..0.510  y 0.000..0.925  z -0.020..0.020   0.04
    frieze top   x 0.075..0.510  y 0.850..0.925  z -0.020..0.020   0.04
    frieze bott. x 0.075..0.510  y 0.000..0.075  z -0.020..0.020   0.04
    handle       x 0.090..0.140  y 0.450..0.500  z  0.010..0.110   0.12*
    lock rail    x 0.075..0.510  y 0.400..0.450  z -0.050..0.050   0.10

There is NO bottom rail (the measured door has none either), and the
handle stands 3.5 cm PROUD of the frame's front, so the model's total
depth (-0.075..0.11 = 0.185) is set by the handle — a rim measured against
the total depth would be nonsense here.  (*) the handle's cells also hold
the filling underneath it, so they read 0.11 - (-0.01) = 0.12.

[H1] THE LEAF PLANE.  The largest planar cluster is the filling's front
(0.435 * 0.925 = 0.402 m2, at z = 0.01; the tie against its back at
z = -0.01 goes to +z) -> normal (0, 0, 1), offset 0.01, u = +x, v = +y,
silhouette (0, 0)..(0.585, 1.0).

[H2] THE RASTER.  cell = 0.025 * max(0.585, 1.0) = 0.025 -> 24 x 40 cells,
the same grid the measurement printed.  Thicknesses: 0.15 (jambs, lintel),
0.10 (rail), 0.12 (handle, whose cells hold the filling under it: 0.11 -
(-0.01)), 0.04 (friezes), 0.02 (filling); a mixed cell reads the union's
extent, and the deepest of all is 0.185 — the handle's front (0.11) over
the left jamb's back (-0.075) in the column x 0.075..0.10 the two share,
which is the model's WHOLE depth.  That is the fixture's second point: a
rim measured as a fraction of the total depth would measure against the
handle.  Otsu puts the split between the friezes and the rail, so the THICK
class is jambs + lintel + rail + handle and the THIN class filling +
friezes.  The thin class therefore holds only the values 0.02 and 0.04 and
its mean must lie strictly between them; the thick class holds 0.10, 0.12,
0.15 and 0.185, so its mean must lie between 0.10 and 0.185; and the split
must fall between 0.04 and 0.10.  Both gates clear with room to spare.

COUNTING THE THIN CELLS — with the BOUNDARY CAVEAT that runs through this
whole fixture.  Several boxes have an edge that falls exactly on a raster
line, and TWO different things happen there.  A sample sitting exactly ON
the line bins into the cell ABOVE it (``floor`` of an exact integer), so
the rail's TOP face at y = 0.450 — 0.450 / 0.025 is exactly 18.0 — lands in
row 18, the row above the rail's own two rows.  And the barycentric weights
sum to 1 only to within a rounding unit, so a MINORITY of the samples on
such a line come out an ulp low and drop into the cell below: of the 6940
samples on the lintel's bottom face at y = 0.925 (exactly 37.0), 812 land
in row 36 and make that row read the lintel's depth in every column but 8
and 14, which none of them reached.  Where the division is
NOT exact the two columns simply share the line: 0.075 / 0.025 =
2.9999999999999996, and the 19302 samples on the jambs' inner faces split
15266 into column 2 and 4036 into column 3.  Structurally:

    columns 4..19 x rows 0..36              16 * 37 = 592 candidate cells
      (columns 0..3 and 20..23 hold jamb material in every row, rows
       37..39 the lintel)
    - the rail's rows 16 and 17 (y 0.400..0.450)      -2 * 16 =  -32
    - row 18, which the rail's TOP face bins into       -16 =  -16
    - row 36, which a minority of the lintel's bottom
      face drops into                                   -16 =  -16
    - the handle, columns 4..5 x rows 19..20             -4  =   -4
                                                          = 524 thin cells

and FIVE single cells fall the other way — cells whose CLASS HANGS ON WHICH
BOUNDARY SAMPLES HAPPENED TO REACH THEM, which shows up in two ways.  Three
of them land a hair off the split 0.08741: +1 (row 18, column 10, extent
0.08571), -1 (row 15, column 14, extent 0.08857 — the rail's bottom face at
y = 0.400 dropping an ulp low) and +1 (column 3, row 33, extent 0.08625,
where the jamb samples that arrived spanned a slightly narrower depth than
in the rows above and below).  The other two are nowhere near it: +2 (row
36, columns 8 and 14) read 0.040 — the top frieze alone — and 0.063,
because no ulp-low lintel sample reached those two columns at all.
Together: **527 of 960**, a thin share of **0.549** >= 0.30.  Those five are
why the check asserts the share with a tolerance instead of the exact
count, and why it asserts the class means as BOUNDS.

[H3] THE THICK PARTS OF THE LEAF.  The rail spans the full leaf width and
touches BOTH jambs; the handle hangs off the left jamb as a thick
peninsula.  Both are thick, so both come out as FRAME cells — and both lie
INSIDE the leaf, so the bounding rectangle of the remaining cells is
unaffected by them: the coarse leaf cells are columns 3..19 x rows 0..36,
i.e. x 0.075..0.500 and y 0.0..0.925, and the prism of [H5] takes rail and
handle along.  That column 3 rests on ONE knife-edge cell — (3, 33), see
[H2] — so a different sampling density would leave the coarse rectangle at
columns 4..19, x 0.100..0.500; [H4] shows the footprint comes out the same
either way, which is why the checks below assert the FOOTPRINT and not the
coarse rectangle.  This is what the plan's measurement demanded ("neither
may crop the rectangle"); note that the border walk is not what achieves it —
see the mutant list above.

[H4] EDGES.  Only the RIGHT edge is refined at all; the other three come
out of the coarse rectangle already final.

  right   0.500 walks outward at fine = 0.005: the columns 0.500..0.505
          and 0.505..0.510 hold nothing but the right frieze (0.04), the
          next one holds the right jamb's inner face at x = 0.51 (0.15)
          and stops the walk.  Two steps -> 0.510.
  left    0.075 already, but only just: the jambs' inner faces reach into
          column 3 (4036 of their samples bin there), so column 3 reads
          thick in 39 of its 40 rows, and the ONE thin cell (3, 33) is the
          whole reason the coarse rectangle starts at column 3 rather than
          4.  There is nothing to walk to either way — the fine column
          0.070..0.075 holds jamb material at once.
  bottom  0.0 is the silhouette edge (there is no bottom rail): the walk
          has nowhere to go.
  top     0.925 already, because the lintel's bottom edge rounds down into
          row 36 and makes row 36 the last leaf row.

    thickness_footprint(...) == ((0.075, 0.0), (0.51, 0.925))

The snap onto the nearest vertex coordinate then moves nothing — all four
are vertex coordinates already.  THE RESULT DOES NOT HANG ON THE ROUNDING:
if the boundary-dependent cells of [H2] had read thick — (3, 33) and row
36's two — the coarse rectangle would be columns 4..19 x rows 0..35, i.e.
x 0.100..0.500, y 0.0..0.900, and the walk plus the snap answer the same
((0.075, 0.0), (0.51, 0.925)) — the left edge walks 0.100 -> 0.080 (the
handle is thick but only two of the band's rows tall, so the median keeps
the walk going) and snaps the last 0.005 onto 0.075, the top walks
0.900 -> 0.920 and snaps onto 0.925.  That left snap sits at EXACTLY the
tolerance, which is why ``_snap_edge`` compares against ``fine + _EPS``.

[H5] THE PRISM through that footprint, along +z: every face of the seven
boxes that stand over the leaf area — filling, four friezes, handle, rail
= 7 * 12 = **84** faces.  Their centres are either strictly inside or ON
an edge with the normal pointing OUT (the filling's and the friezes' left
face at x = 0.075, right at 0.51, bottom at y = 0, top at 0.925).  NOT the
jambs: the left jamb's right face sits at x = 0.075 too, but its normal
points +x, INTO the footprint (the edge rule), and its front/back centres
lie at x 0.025..0.05, outside.  NOT the lintel: its bottom face is at
y = 0.925 with the normal -y, pointing in.

[H6] SHARE = the prism's faces lying IN the leaf plane (facing +z, centre
within 2 cm of z = 0.01): the filling's front (0.402375) and the four
frieze fronts at z = 0.02 (2 * 0.075 * 0.925 + 2 * 0.435 * 0.075 =
0.204) = 0.606375 over the silhouette 0.585 -> 1.0365 >= 0.30.  The rail's
front (z = 0.05) and the handle's (z = 0.11) are further off than 2 cm and
do not count.

[H7] THE RESIDUAL of that cut is 0: of the 36 faces left in the frame (the
two jambs and the lintel) not one has its centre more than 2 cm inside the
footprint — a clean prism split raises no ``areas_warning``.

==========================================================================
FIXTURE I — the glass door: a frame with a HOLE, not a leaf
==========================================================================
The four bars of fixture F (no plate), but all of them z -0.01..0.01.
Every cell that holds material reads the same 0.02 and the pane's cells
hold nothing at all.  Otsu's best split of a single-valued sample has
m_thick - m_thin = 0 < 0.015 (and ratio 1.0 < 1.3), so there is no
two-class thickness: ``thickness_footprint`` is None and ``detect_leaf``
answers None.  This is the measured glass door (0.027 against 0.021 all
over, plan-blatt-dicke.md) in its purest form — a pane is a hole, and a
hole must never be cut out as a swinging leaf.

Usage:  ./.venv/bin/python scripts/smoke_picture_areas.py
        ./.venv/bin/python scripts/smoke_picture_areas.py --glb <path> [--cell M]

The second form is the REAL-MESH mode: it loads one door GLB, prints its
thickness map, the Otsu classes, the footprint and ``detect_leaf``'s share,
and exits without running the fixtures.
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

    print("  [F2] the thickness raster and the footprint it yields")
    plane = pa.leaf_plane(verts, faces, normals)
    check("F2: silhouette bbox (0,0)..(1.0,2.2)",
          plane is not None and vclose(plane["bbox2d"][0], (0, 0))
          and vclose(plane["bbox2d"][1], (1.0, 2.2)), str(plane and plane["bbox2d"]))
    grid = pa.thickness_map(verts, faces, plane, plane["bbox2d"], cell=0.055)
    check("F2: 19 x 40 cells of 0.055 m, none of them empty",
          (grid["nu"], grid["nv"]) == (19, 40)
          and all(t is not None for row in grid["thick"] for t in row),
          str((grid["nu"], grid["nv"])))
    levels = sorted({round(t, 6) for row in grid["thick"] for t in row})
    check("F2: exactly two thicknesses — the bars' 0.07 and the plate's 0.02",
          levels == [0.02, 0.07], str(levels))
    thin_cells = sum(1 for row in grid["thick"] for t in row if t < 0.045)
    check("F2: 14 x 36 = 504 thin cells of 760 (share 0.663 >= 0.30)",
          thin_cells == 504, str(thin_cells))
    check("F2: footprint (0.1,0.1)..(0.9,2.1) — the plate's own coordinates",
          plane is not None and vclose(plane["inner"][0], (0.1, 0.1))
          and vclose(plane["inner"][1], (0.9, 2.1)), str(plane and plane["inner"]))
    check("F2: thickness_footprint answers the same rectangle directly",
          vclose(pa.thickness_footprint(verts, faces, plane, plane["bbox2d"])[0], (0.1, 0.1))
          and vclose(pa.thickness_footprint(verts, faces, plane, plane["bbox2d"])[1],
                     (0.9, 2.1)),
          str(pa.thickness_footprint(verts, faces, plane, plane["bbox2d"])))

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

    print("  [F6] a bare leaf is not a door: the plate alone")
    pv, pf = build_door(bars=False)
    p_plane = {"normal": (0.0, 0.0, 1.0), "offset": 0.0,
               "u": (1.0, 0.0, 0.0), "v": (0.0, 1.0, 0.0)}
    check("F6: one thickness class (0.02 everywhere) -> no footprint",
          pa.thickness_footprint(pv, pf, p_plane, ((0.1, 0.1), (0.9, 2.1))) is None,
          str(pa.thickness_footprint(pv, pf, p_plane, ((0.1, 0.1), (0.9, 2.1)))))
    check("F6: leaf_plane is None", pa.leaf_plane(pv, pf) is None)
    check("F6: detect_leaf answers None", pa.detect_leaf(pv, pf) is None)

    print("  [F7] the same gate from the other side: bars without a plate")
    bv, bf = build_door(plate=False)
    bnormals = pa.face_normals(bv, bf)
    bclusters = pa.planar_clusters(bv, bf, bnormals)
    check("F7: the largest cluster is a bar front at 0.02",
          bool(bclusters) and close(bclusters[0]["offset"], 0.02),
          str(bclusters[:1]))
    check("F7: one thickness class (0.07 where there is material, the hole "
          "is empty) -> leaf_plane is None",
          pa.leaf_plane(bv, bf, bnormals) is None)
    hand_plane = {"normal": (0.0, 0.0, 1.0), "offset": 0.02,
                  "u": (1.0, 0.0, 0.0), "v": (0.0, 1.0, 0.0),
                  "tol": pa.LEAF_TOL_M, "cos_min": pa.COPLANAR_COS,
                  "inner": ((0.1, 0.1), (0.9, 2.1)), "front_offset": 0.02}
    check("F7: leaf_candidates (v1) on a hand-built plane is empty — the bar "
          "fronts' centres all lie outside the rectangle",
          pa.leaf_candidates(bv, bf, bnormals, hand_plane) == [],
          str(pa.leaf_candidates(bv, bf, bnormals, hand_plane)))
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
#   footprint    = the thickness raster over that plane, cell 0.025 * 2.2 =
#                  0.055: a leaf cell runs from the back skin at z = -0.05 to
#                  the slab's front at z = 0 -> 0.05, a frame cell from the
#                  back skin to a bar's front at z = 0.02 -> 0.07. Otsu splits
#                  at 0.06; ratio 0.07 / 0.05 = 1.4 >= 1.3 and difference
#                  0.02 >= 0.015, so the two classes hold (a 5 cm leaf in a
#                  7 cm frame is the tightest case the gate must still pass).
#                  Border BFS = the bars; refinement + snapping put the edges
#                  on the slab's own coordinates -> inner (-0.9, 0.1) ..
#                  (-0.1, 2.1), i.e. x 0.1..0.9, y 0.1..2.1.
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
#   residual     = frame faces whose centre lies more than 2 cm inside THE
#                  FOOTPRINT THE CUT WAS MADE THROUGH — not the leaf's own
#                  outline. For the automatic cut that footprint is the
#                  inner rect (x 0.1..0.9, y 0.1..2.1) and the frame that
#                  is left holds none: 0. For a plain manual list it is
#                  `list_footprint` of the listed faces: drop the central
#                  quad (4, 10) — tris 60 + 2 * 104 = 268, 269, centres
#                  (0.433, 1.067) / (0.467, 1.033) — from the list, and the
#                  remaining 330 centres still span exactly 0.1..0.9 x
#                  0.1..2.1 (the slab's four edge faces sit on those very
#                  lines), so the two faces left in the frame count 2.
#   list_footprint = the EXACT bounding rect of the listed faces' CENTRES,
#                  no padding. For ONE front triangle of the slab — 48 =
#                  (0.1, 0.1), (0.9, 0.1), (0.9, 2.1), centre (19/30,
#                  23/30) — that rect degenerates to that single point.
#   leaf_prism   = prism_faces through that rect, UNITED with the list. Over
#                  a degenerate rect every candidate centre lies ON the
#                  outline, so the EDGE RULE decides, and it admits only a
#                  face whose normal points OUT of the rect in the plane:
#                  the back twin 50 (the same three x/y at z -0.04) and the
#                  one back-skin triangle in the same column (the grid's
#                  first-type centres are ((3i+1)/30, (3j+2)/30), so i = 6,
#                  j = 7: quad (6, 7), tri 60 + 2 * 76 = 212) both face
#                  ±z — along the axis, no in-plane component at all — and
#                  stay out. -> leaf_prism([48]) == [48]: a lone skin
#                  triangle takes nothing with it.
def build_door_g(front_n=0):
    """``front_n`` > 0 replaces the slab's two front triangles by an n x n
    grid over x 0.1..0.9, y 0.1..2.1 at z = 0 (facing +z) — the finely
    triangulated front skin of a real img2mesh door (fixture G', [G7]):
    faces 48..57 are then the slab's back + edges, 58..(58 + 2 n² - 1) the
    front grid (quad (i, j) = tris 58 + 2 (n j + i), + 1), the back skin
    follows."""
    verts, faces = build_door(plate=False)
    box(0.1, 0.9, 0.1, 2.1, -0.04, 0.00, verts, faces)
    if front_n:
        del faces[48:50]                       # the slab's two front triangles
        b = len(verts)
        w, h = 0.8 / front_n, 2.0 / front_n
        for j in range(front_n + 1):
            for i in range(front_n + 1):
                verts.append((0.1 + i * w, 0.1 + j * h, 0.0))
        for j in range(front_n):
            for i in range(front_n):
                v00 = b + j * (front_n + 1) + i
                v10, v01, v11 = v00 + 1, v00 + front_n + 1, v00 + front_n + 2
                faces.append((v00, v10, v11))  # facing +z
                faces.append((v00, v11, v01))
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

    print("  [G1] the leaf plane is the back skin, 0.05 against the frame's 0.07")
    plane = pa.leaf_plane(verts, faces, normals)
    check("G1: normal (0, 0, -1), offset 0.05",
          plane is not None and vclose(plane["normal"], (0, 0, -1)) and close(plane["offset"], 0.05),
          str(plane and (plane["normal"], plane["offset"])))
    g_levels = sorted({round(t, 6) for row in pa.thickness_map(
        verts, faces, plane, plane["bbox2d"], cell=0.055)["thick"] for t in row})
    check("G1: exactly two thicknesses — 0.05 in the leaf, 0.07 in the frame "
          "(ratio 1.4 >= 1.3, difference 0.02 >= 0.015: the tightest pass)",
          g_levels == [0.05, 0.07], str(g_levels))
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

    print("  [G5] leaf_residual: frame faces more than 2 cm inside the split's footprint")
    frame = [k for k in range(len(faces)) if k not in set(expected)]
    rect, axis = plane["inner"], plane["normal"]
    check("G5: a clean prism split leaves 0 against the inner rect",
          pa.leaf_residual(verts, faces, rect, axis, frame) == 0,
          str(pa.leaf_residual(verts, faces, rect, axis, frame)))
    short = [k for k in expected if k not in (268, 269)]
    fp, ax = pa.list_footprint(verts, faces, short)
    check("G5: a plain list's footprint is the outline of its centres (0.1..0.9 x 0.1..2.1, +z)",
          vclose(fp[0], (0.1, 0.1)) and vclose(fp[1], (0.9, 2.1)) and vclose(ax, (0, 0, 1)),
          str((fp, ax)))
    check("G5: the central quad left behind counts 2 against that footprint",
          pa.leaf_residual(verts, faces, fp, ax, frame + [268, 269]) == 2,
          str(pa.leaf_residual(verts, faces, fp, ax, frame + [268, 269])))
    check("G5: the bars' jamb faces (ON the outline) never count",
          pa.leaf_residual(verts, faces, rect, axis, list(range(48))) == 0)

    print("  [G6] leaf_prism: a face list becomes the prism through its own footprint")
    check("G6: the whole prism listed gives EXACTLY the whole prism back (332, no jamb)",
          pa.leaf_prism(verts, faces, expected) == expected,
          str(len(pa.leaf_prism(verts, faces, expected))))
    front_and_edges = [48, 49] + list(range(52, 60))
    check("G6: the slab's front + its four edges (10 faces) reach the back and the "
          "back skin: the same 332",
          pa.leaf_prism(verts, faces, front_and_edges) == expected,
          str(len(pa.leaf_prism(verts, faces, front_and_edges))))
    check("G6: an empty list is an empty prism", pa.leaf_prism(verts, faces, []) == [])
    check("G6: ONE front triangle takes nothing along — its centres' rect is a "
          "point, and the edge rule keeps every ±z face out",
          pa.leaf_prism(verts, faces, [48]) == [48],
          str(pa.leaf_prism(verts, faces, [48])))

    print("  [G6b] clamp_bbox holds the box to the footprint in the plane")
    wide = ((0.0, 0.0, -0.05), (1.0, 2.2, 0.0))
    clamped = pa.clamp_bbox(wide, rect, axis)
    check("G6b: (0,0,-0.05)..(1,2.2,0) -> (0.1,0.1,-0.05)..(0.9,2.1,0), depth untouched",
          vclose(clamped[0], (0.1, 0.1, -0.05)) and vclose(clamped[1], (0.9, 2.1, 0.0)),
          str(clamped))
    check("G6b: a box inside the footprint is left alone",
          pa.clamp_bbox(((0.2, 0.3, -0.01), (0.5, 1.0, 0.0)), rect, axis)
          == ((0.2, 0.3, -0.01), (0.5, 1.0, 0.0)))

    print("[G7] fixture G': a 16 x 16 front grid — a fine skin is no frame")
    # 48 bar faces, 10 slab faces (back + edges), 512 front-grid faces
    # (58..569), 440 back-skin faces (570..1009) = 1010. Triangulating the
    # front finely changes no DEPTH anywhere, so the raster is the one of
    # fixture G — 0.05 in the leaf columns, 0.07 in the frame columns — and
    # the footprint stays (0.1..0.9 x 0.1..2.1). The prism then takes every
    # slab face (10 + 512, centres strictly inside) plus the 320 inner
    # back-skin faces: 842. Measured with the v2 rim (which read the FACE
    # ORIENTATION instead of the material thickness): rim (0.2, 0.475, 0.2,
    # 0.475), 386 faces, 272 front faces left behind, no warning.
    gv, gf = build_door_g(front_n=16)
    check("G7: 1010 faces", len(gf) == 1010, str(len(gf)))
    gplane = pa.leaf_plane(gv, gf, pa.face_normals(gv, gf))
    check("G7: thickness_footprint = (-0.9, 0.1)..(-0.1, 2.1), the same as "
          "for the coarse front of fixture G",
          gplane is not None
          and vclose(pa.thickness_footprint(gv, gf, gplane, gplane["bbox2d"])[0],
                     (-0.9, 0.1))
          and vclose(pa.thickness_footprint(gv, gf, gplane, gplane["bbox2d"])[1],
                     (-0.1, 2.1)),
          str(gplane and pa.thickness_footprint(gv, gf, gplane, gplane["bbox2d"])))
    check("G7: inner (-0.9, 0.1)..(-0.1, 2.1)",
          gplane is not None and vclose(gplane["inner"][0], (-0.9, 0.1))
          and vclose(gplane["inner"][1], (-0.1, 2.1)), str(gplane and gplane["inner"]))
    g_expected = list(range(48, 570)) + [570 + 2 * q + d for q in inner_quads for d in (0, 1)]
    g_leaf = pa.detect_leaf(gv, gf)
    check("G7: detect_leaf = every slab face + the 320 back-skin faces = 842",
          g_leaf is not None and g_leaf["faces"] == g_expected,
          str(g_leaf and (len(g_leaf["faces"]), len(g_expected))))
    check("G7: bbox (0.1, 0.1, -0.05)..(0.9, 2.1, 0), share 3.2 / 2.2",
          g_leaf is not None and vclose(g_leaf["bbox"][0], (0.1, 0.1, -0.05))
          and vclose(g_leaf["bbox"][1], (0.9, 2.1, 0.0)) and close(g_leaf["share"], 3.2 / 2.2, 1e-6),
          str(g_leaf and (g_leaf["bbox"], g_leaf["share"])))
    g_frame = [k for k in range(len(gf)) if k not in set(g_expected)]
    check("G7: residual 0 against the inner rect",
          pa.leaf_residual(gv, gf, gplane["inner"], gplane["normal"], g_frame) == 0)

    print("  [G8] a v1-style skin cut of the leaf's middle: the residual reports the back skin")
    # A plain list (no through) of the front grid's quads i 6..9, j 6..9 —
    # x 0.4..0.6, y 0.85..1.35, 32 tris. Its footprint is the outline of
    # its centres: x 0.4 + w/3 .. 0.6 - w/3 = 0.4167..0.5833, y 0.85 + h/3
    # .. 1.35 - h/3 = 0.8917..1.3083 (w = 0.05, h = 0.125); shrunk by 2 cm
    # -> x 0.4367..0.5633, y 0.9117..1.2883. Frame faces with centres in
    # it: only back-skin tris — first type (i/10 + 1/30, j/10 + 2/30): i = 5
    # (0.5333), j = 9..12 (0.9667..1.2667) -> 4; second type (i/10 + 2/30,
    # j/10 + 1/30): i = 4 (0.4667), j = 9..12 (0.9333..1.2333) -> 4. The
    # slab's back tris (0.367, 0.767) / (0.633, 1.433) and the neighbouring
    # front quads (x 0.3833 / 0.6167, y 0.8083 / 1.3917) lie outside: 8.
    patch = sorted(58 + 2 * (16 * j + i) + d for j in range(6, 10) for i in range(6, 10)
                   for d in (0, 1))
    pfp, pax = pa.list_footprint(gv, gf, patch)
    check("G8: the patch's footprint (0.4167, 0.8917)..(0.5833, 1.3083) along +z",
          vclose(pfp[0], (0.4 + 0.05 / 3, 0.85 + 0.125 / 3), 1e-9)
          and vclose(pfp[1], (0.6 - 0.05 / 3, 1.35 - 0.125 / 3), 1e-9) and vclose(pax, (0, 0, 1)),
          str((pfp, pax)))
    p_frame = [k for k in range(len(gf)) if k not in set(patch)]
    check("G8: residual 8 — the back skin behind the patch",
          pa.leaf_residual(gv, gf, pfp, pax, p_frame) == 8,
          str(pa.leaf_residual(gv, gf, pfp, pax, p_frame)))


# ---------------------------------------------------------------------------
# FIXTURE H — the measured wooden door (plan-blatt-dicke.md)
# ---------------------------------------------------------------------------
def build_door_h():
    """The ten boxes of fixture H, in the order of the header docstring:
    two jambs, the lintel, the leaf filling, four friezes, the handle and
    the lock rail — 10 * 12 = 120 triangles, 80 vertices."""
    verts, faces = [], []
    box(0.000, 0.075, 0.000, 1.000, -0.075, 0.075, verts, faces)   # left jamb
    box(0.510, 0.585, 0.000, 1.000, -0.075, 0.075, verts, faces)   # right jamb
    box(0.000, 0.585, 0.925, 1.000, -0.075, 0.075, verts, faces)   # lintel
    box(0.075, 0.510, 0.000, 0.925, -0.010, 0.010, verts, faces)   # filling
    box(0.075, 0.150, 0.000, 0.925, -0.020, 0.020, verts, faces)   # frieze left
    box(0.435, 0.510, 0.000, 0.925, -0.020, 0.020, verts, faces)   # frieze right
    box(0.075, 0.510, 0.850, 0.925, -0.020, 0.020, verts, faces)   # frieze top
    box(0.075, 0.510, 0.000, 0.075, -0.020, 0.020, verts, faces)   # frieze bottom
    box(0.090, 0.140, 0.450, 0.500, 0.010, 0.110, verts, faces)    # handle
    box(0.075, 0.510, 0.400, 0.450, -0.050, 0.050, verts, faces)   # lock rail
    return verts, faces


H_FOOTPRINT = ((0.075, 0.0), (0.51, 0.925))


def part_h():
    print("[H] the measured wooden door: handle peninsula and full-width rail")
    verts, faces = build_door_h()
    check("H: 80 vertices, 120 triangles", (len(verts), len(faces)) == (80, 120),
          str((len(verts), len(faces))))

    print("  [H1] the leaf plane is the filling's front")
    normals = pa.face_normals(verts, faces)
    plane = pa.leaf_plane(verts, faces, normals)
    check("H1: normal (0, 0, 1), offset 0.01",
          plane is not None and vclose(plane["normal"], (0, 0, 1))
          and close(plane["offset"], 0.01),
          str(plane and (plane["normal"], plane["offset"])))
    check("H1: silhouette (0, 0)..(0.585, 1.0)",
          plane is not None and vclose(plane["bbox2d"][0], (0.0, 0.0))
          and vclose(plane["bbox2d"][1], (0.585, 1.0)),
          str(plane and plane["bbox2d"]))

    print("  [H2] the 24 x 40 raster and its two classes")
    grid = pa.thickness_map(verts, faces, plane, plane["bbox2d"], cell=0.025)
    check("H2: 24 x 40 cells, none empty",
          (grid["nu"], grid["nv"]) == (24, 40)
          and all(t is not None for row in grid["thick"] for t in row),
          str((grid["nu"], grid["nv"])))
    thick = [t for row in grid["thick"] for t in row]
    check("H2: thinnest cell 0.02 (the filling), deepest 0.185 (the handle's "
          "front over a jamb's back — the model's WHOLE depth), with the "
          "jamb's own 0.15 and the handle-over-filling 0.12 both present",
          close(min(thick), 0.02, 1e-9) and close(max(thick), 0.185, 1e-9)
          and any(close(t, 0.15, 1e-9) for t in thick)
          and any(close(t, 0.12, 1e-9) for t in thick),
          f"min {min(thick)} max {max(thick)}")
    split, m_thin, m_thick = pa.otsu_split(thick)
    check("H2: the split falls between the friezes (0.04) and the rail (0.10)",
          0.04 < split < 0.10, f"{split}")
    check("H2: the thin class holds only 0.02 and 0.04, so its mean lies "
          "strictly between them; the thick class holds 0.10..0.185",
          0.02 < m_thin < 0.04 and 0.10 < m_thick < 0.185,
          f"m_thin {m_thin} m_thick {m_thick}")
    check("H2: both gates clear — ratio >= 1.3 and difference >= 0.015",
          m_thick >= pa.THICK_MIN_RATIO * m_thin
          and m_thick - m_thin >= pa.THICK_MIN_DIFF_M,
          f"ratio {m_thick / m_thin:.2f} diff {m_thick - m_thin:.4f}")
    thin_n = sum(1 for t in thick if t < split)
    check("H2: 527 of 960 cells thin (524 by the block count + 5 boundary "
          "cells, see the derivation) -> share 0.549 >= 0.30",
          abs(thin_n / len(thick) - 527 / 960.0) <= 0.01
          and thin_n / len(thick) >= pa.LEAF_MIN_SHARE,
          f"{thin_n} of {len(thick)} = {thin_n / len(thick):.4f}")

    print("  [H3/H4] rail and handle are thick but INSIDE the leaf; only the "
          "right edge is refined (0.500 -> 0.510)")
    check("H3: footprint (0.075, 0)..(0.51, 0.925) — the rail does not crop it",
          vclose(pa.thickness_footprint(verts, faces, plane, plane["bbox2d"])[0],
                 H_FOOTPRINT[0])
          and vclose(pa.thickness_footprint(verts, faces, plane, plane["bbox2d"])[1],
                     H_FOOTPRINT[1]),
          str(pa.thickness_footprint(verts, faces, plane, plane["bbox2d"])))
    check("H4: leaf_plane reports the same rectangle as its inner",
          plane is not None and vclose(plane["inner"][0], H_FOOTPRINT[0])
          and vclose(plane["inner"][1], H_FOOTPRINT[1]), str(plane and plane["inner"]))

    print("  [H5] the prism = the seven boxes over the leaf area, 84 faces")
    leaf = pa.detect_leaf(verts, faces)
    check("H5: detect_leaf takes faces 36..119 (filling, 4 friezes, handle, rail)",
          leaf is not None and leaf["faces"] == list(range(36, 120)),
          str(leaf and (len(leaf["faces"]), leaf["faces"][:3], leaf["faces"][-3:])))
    check("H5: no jamb and no lintel face (0..35)",
          leaf is not None and not any(k < 36 for k in leaf["faces"]))
    check("H5: bbox (0.075, 0, -0.05)..(0.51, 0.925, 0.11) — the rail sets the "
          "back, the handle the front",
          leaf is not None and vclose(leaf["bbox"][0], (0.075, 0.0, -0.05))
          and vclose(leaf["bbox"][1], (0.51, 0.925, 0.11)), str(leaf and leaf["bbox"]))
    check("H6: share 0.606375 / 0.585 = 1.0365",
          leaf is not None and close(leaf["share"], 0.606375 / 0.585, 1e-9),
          str(leaf and leaf["share"]))

    print("  [H7] the residual: a clean prism cut leaves no frame face inside")
    frame = list(range(36))          # the two jambs and the lintel
    check("H7: 0 frame faces inside the footprint",
          pa.leaf_residual(verts, faces, plane["inner"], plane["normal"], frame) == 0,
          str(pa.leaf_residual(verts, faces, plane["inner"], plane["normal"], frame)))


# ---------------------------------------------------------------------------
# FIXTURE I — the glass door: a frame with a hole
# ---------------------------------------------------------------------------
def build_door_i():
    """The four bars of fixture F at a uniform 2 cm depth — a frame around a
    HOLE, which is what a glass door's mesh is."""
    verts, faces = [], []
    box(0.0, 0.1, 0.0, 2.2, -0.01, 0.01, verts, faces)
    box(0.9, 1.0, 0.0, 2.2, -0.01, 0.01, verts, faces)
    box(0.1, 0.9, 0.0, 0.1, -0.01, 0.01, verts, faces)
    box(0.1, 0.9, 2.1, 2.2, -0.01, 0.01, verts, faces)
    return verts, faces


def part_i():
    print("[I] the glass door: one thickness class, so no leaf at all")
    verts, faces = build_door_i()
    check("I: 32 vertices, 48 triangles", (len(verts), len(faces)) == (32, 48),
          str((len(verts), len(faces))))
    i_plane = {"normal": (0.0, 0.0, 1.0), "offset": 0.01,
               "u": (1.0, 0.0, 0.0), "v": (0.0, 1.0, 0.0)}
    grid = pa.thickness_map(verts, faces, i_plane, ((0.0, 0.0), (1.0, 2.2)), cell=0.055)
    levels = sorted({round(t, 6) for row in grid["thick"] for t in row if t is not None})
    check("I: every cell that holds material reads 0.02", levels == [0.02], str(levels))
    check("I: the pane is a HOLE — the middle cells are empty",
          any(t is None for row in grid["thick"] for t in row))
    check("I: thickness_footprint is None (difference 0 < 0.015)",
          pa.thickness_footprint(verts, faces, i_plane, ((0.0, 0.0), (1.0, 2.2))) is None,
          str(pa.thickness_footprint(verts, faces, i_plane, ((0.0, 0.0), (1.0, 2.2)))))
    check("I: leaf_plane is None", pa.leaf_plane(verts, faces) is None)
    check("I: detect_leaf is None", pa.detect_leaf(verts, faces) is None)


# ---------------------------------------------------------------------------
# the real-mesh mode: --glb <path> [--cell M]
# ---------------------------------------------------------------------------
# A minimal stdlib glTF-binary reader — enough to get the triangles of a
# door prop out of a .glb: the JSON chunk (type 0x4E4F534A) describes
# accessors into the BIN chunk (0x004E4942), and every mesh sits under a
# node whose TRS (or 4x4 matrix) has to be applied, parents first.
_GLB_COMPONENT = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
_GLB_COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _glb_chunks(path):
    import json
    import struct
    blob = Path(path).read_bytes()
    _magic, _ver, length = struct.unpack_from("<III", blob, 0)
    off, js, binc = 12, None, b""
    while off < length:
        clen, ctype = struct.unpack_from("<II", blob, off)
        off += 8
        chunk = blob[off:off + clen]
        off += clen
        if ctype == 0x4E4F534A:
            js = json.loads(chunk)
        elif ctype == 0x004E4942:
            binc = chunk
    return js, binc


def _glb_accessor(js, binc, idx):
    import struct
    acc = js["accessors"][idx]
    view = js["bufferViews"][acc["bufferView"]]
    n = _GLB_COUNT[acc["type"]]
    fmt = _GLB_COMPONENT[acc["componentType"]]
    item = struct.calcsize("<" + fmt)
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = view.get("byteStride") or n * item
    out = []
    for i in range(acc["count"]):
        out.append(struct.unpack_from("<" + fmt * n, binc, start + i * stride))
    return out


def _glb_matrix(node):
    if "matrix" in node:                       # glTF stores column-major
        m = node["matrix"]
        return [[m[0], m[4], m[8], m[12]], [m[1], m[5], m[9], m[13]],
                [m[2], m[6], m[10], m[14]], [m[3], m[7], m[11], m[15]]]
    tx, ty, tz = node.get("translation", (0.0, 0.0, 0.0))
    x, y, z, w = node.get("rotation", (0.0, 0.0, 0.0, 1.0))
    sx, sy, sz = node.get("scale", (1.0, 1.0, 1.0))
    rot = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
           [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
           [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    scale = (sx, sy, sz)
    return [[rot[r][c] * scale[c] for c in range(3)] + [(tx, ty, tz)[r]]
            for r in range(3)] + [[0.0, 0.0, 0.0, 1.0]]


def _mat_mul(a, b):
    return [[sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)]
            for r in range(4)]


def _mat_apply(m, p):
    return tuple(m[r][0] * p[0] + m[r][1] * p[1] + m[r][2] * p[2] + m[r][3]
                 for r in range(3))


def load_glb(path):
    """``(vertices, faces)`` of one GLB in scene space, y-up as authored."""
    js, binc = _glb_chunks(path)
    verts, faces = [], []

    def walk(ni, parent):
        node = js["nodes"][ni]
        m = _mat_mul(parent, _glb_matrix(node))
        if "mesh" in node:
            for prim in js["meshes"][node["mesh"]]["primitives"]:
                base = len(verts)
                for p in _glb_accessor(js, binc, prim["attributes"]["POSITION"]):
                    verts.append(_mat_apply(m, p))
                idx = [i[0] for i in _glb_accessor(js, binc, prim["indices"])]
                for k in range(0, len(idx) - 2, 3):
                    faces.append((base + idx[k], base + idx[k + 1], base + idx[k + 2]))
        for child in node.get("children", ()):
            walk(child, m)

    eye = [[1.0 if r == c else 0.0 for c in range(4)] for r in range(4)]
    for root in js["scenes"][js.get("scene", 0)]["nodes"]:
        walk(root, eye)
    return verts, faces


def run_glb(path, cell=None):
    """Print the thickness map, the Otsu classes, the footprint and the
    share for ONE real door mesh, then stop — the fixtures do not run."""
    verts, faces = load_glb(path)
    print(f"{path}: {len(verts)} vertices, {len(faces)} triangles")
    normals = pa.face_normals(verts, faces)
    clusters = pa.planar_clusters(verts, faces, normals)
    if not clusters:
        print("  no planar cluster — no leaf plane")
        return 0
    top = clusters[0]
    u_axis, v_axis = pa.planar_frame(top["normal"])
    plane = {"normal": top["normal"], "offset": top["offset"],
             "u": u_axis, "v": v_axis, "tol": pa.LEAF_TOL_M,
             "cos_min": pa.COPLANAR_COS}
    us = [pa._dot(u_axis, p) for p in verts]
    vs = [pa._dot(v_axis, p) for p in verts]
    bbox2d = ((min(us), min(vs)), (max(us), max(vs)))
    (u0, v0), (u1, v1) = bbox2d
    print(f"  plane normal {tuple(round(c, 4) for c in top['normal'])} "
          f"offset {top['offset']:.4f}")
    print(f"  silhouette u {u0:.4f}..{u1:.4f}  v {v0:.4f}..{v1:.4f}")
    if cell is None:
        cell = pa.THICK_CELL_SHARE * max(u1 - u0, v1 - v0)
    grid = pa.thickness_map(verts, faces, plane, bbox2d, cell=cell)
    flat = [t for row in grid["thick"] for t in row if t is not None]
    if not flat:
        print("  empty raster")
        return 0
    top_thick = max(flat)
    print(f"  raster {grid['nu']} x {grid['nv']} cells of {cell:.4f} m, "
          f"{len(flat)} of {grid['nu'] * grid['nv']} hold material "
          f"(rows top -> bottom, ' ' = empty, thickest = '@')")
    steps = " .:-=+*#%@"
    for r in range(grid["nv"] - 1, -1, -1):
        print("    " + "".join(
            " " if t is None else steps[min(9, int(t / top_thick * 9.999))]
            for t in grid["thick"][r]))
    split, m_thin, m_thick = pa.otsu_split(flat)
    thin = sum(1 for t in flat if t < split)
    print(f"  Otsu split {split:.4f}: thin mean {m_thin:.4f}, thick mean "
          f"{m_thick:.4f}, ratio {m_thick / m_thin if m_thin else float('inf'):.2f}, "
          f"difference {m_thick - m_thin:.4f}, thin share {thin / len(flat):.3f}")
    foot = pa.thickness_footprint(verts, faces, plane, bbox2d)
    if foot is None:
        print("  footprint: None — no two-class thickness, so no leaf")
    else:
        print(f"  footprint u {foot[0][0]:.4f}..{foot[1][0]:.4f}  "
              f"v {foot[0][1]:.4f}..{foot[1][1]:.4f}")
    leaf = pa.detect_leaf(verts, faces)
    if leaf is None:
        print("  detect_leaf: None")
    else:
        lo, hi = leaf["bbox"]
        print(f"  detect_leaf: {len(leaf['faces'])} faces, share "
              f"{leaf['share']:.3f}, bbox {tuple(round(c, 4) for c in lo)}.."
              f"{tuple(round(c, 4) for c in hi)}")
    return 0


def main():
    if "--glb" in sys.argv:
        args = sys.argv[1:]
        path = args[args.index("--glb") + 1]
        cell = float(args[args.index("--cell") + 1]) if "--cell" in args else None
        return run_glb(path, cell)
    print("smoke_picture_areas")
    part_colour()
    part_f()
    part_g()
    part_h()
    part_i()
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
