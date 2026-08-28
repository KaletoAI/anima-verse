"""Picture-area maths — chroma-key faces, components, plane fit, planar UVs.

STDLIB ONLY, AND THAT IS LOAD-BEARING. This module is imported by the
headless Blender refinement script through ``sys.path`` from Blender's own
bundled Python interpreter, which has neither this project's virtualenv nor
its dependencies. So: no numpy, no third-party packages, no ``app.*``
imports — ``math``, ``typing`` and ``collections`` are the whole budget.
Everything here is pure geometry over plain tuples; the caller (Blender)
supplies triangles, per-vertex UVs and a pixel sampler, and gets back plane,
frame, planar UVs and boundary edges.

MODEL SPACE IS glTF **Y-UP** — the same convention as the meshes this
project ships and as three.js in both renderers (``docs/schnittstellen-3d.md``:
the ground plane is ``(pos_x, pos_z)``, height is ``y``). Blender works z-up,
so the Blender caller converts its coordinates to y-up BEFORE handing them
in. ``planar_frame`` relies on that: it needs to know which way is up to keep
a picture on a wall from being stored on its side.

The pipeline a caller runs:

1. ``classify_faces`` — which triangles show the key colour (the image model
   was asked to paint the picture panel chroma green and the glass panel
   magenta on the frame mesh; the mesh arrives with ONE anonymous atlas
   material, so the colour in the texture is the only marker there is).
2. ``components`` — group the key triangles into connected patches over
   SHARED EDGES, so two panels on the same frame stay apart.
3. ``fit_plane`` / ``planar_frame`` / ``planar_uvs`` — each patch gets its
   own plane, a right-handed in-plane frame and UVs normalised to 0..1 over
   the patch bounding box, plus its physical size in metres.
4. ``detect_areas`` wraps 1–3 and drops patches that are too small to be a
   real panel; ``area_edges`` yields the outline for the editor overlay.
5. THE DOOR LEAF (spec § 6, decision D7) is geometry, not colour: a door
   render always shows frame AND leaf, and the leaf has to become its OWN
   glTF node so a renderer can swing it alone. ``detect_leaf`` finds it —
   the leaf plane (``planar_clusters``) and, in it, the leaf's FOOTPRINT
   read off the MATERIAL THICKNESS (``thickness_map`` /
   ``thickness_footprint``, plan-blatt-dicke.md 2026-08-28): the silhouette
   is rastered, every cell measures how DEEP the mesh is there, an Otsu
   split separates a thick class from a thin one, the thick region
   CONNECTED TO THE SILHOUETTE'S BORDER is the frame, and the rectangle
   around everything that region encloses is the leaf. Since
   spec-bild-props-v2.md E2 the leaf itself is the
   PRISM through that footprint (``prism_faces``: every face whose centre
   projects into it, at ANY depth and with ANY normal — front skin, back
   skin, edges, handles) and the ``bbox_of`` that becomes ``leaf_bbox``.
   A hand-drawn face list becomes the same kind of prism through its own
   footprint (``list_footprint`` / ``leaf_prism``), ``leaf_residual``
   counts what a cut left behind inside the footprint it was made through,
   and ``clamp_bbox`` holds ``leaf_bbox`` to that footprint in the plane. ``leaf_candidates`` is the v1
   SKIN heuristic (seed + edge growth), kept as the reference the prism is
   measured against — a real door's back skin is one continuous surface
   with the frame's, and the skin cut left 979 frame triangles behind the
   leaf (befunde 2026-08-28, Wurzel 2).
   Kind ``leaf`` is deliberately NOT in ``KINDS``: those are the COLOUR kinds
   with a chroma-key predicate and a prompt fragment; ``is_key_colour`` /
   ``classify_faces`` raise on it. (The scene payload also knows a WALL
   piece kind ``leaf`` — the flat panel filling a door hole; that one has
   nothing to do with this node and is never touched here.)

The colour rule mirrors ``app/core/messaging_frame.py`` (the 8-bit chroma
key used for messaging frames), only expressed on 0..1 floats.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Callable, Dict, List, Optional, Sequence, Tuple

Point = Tuple[float, float, float]
Face = Tuple[int, int, int]
UV = Tuple[float, float]
SampleFn = Callable[[float, float], Tuple[float, float, float]]

# The 8-bit rule of messaging_frame.py on 0..1 floats: 100/255 ~ 0.39 is the
# "clearly bright" level, 30/255 ~ 0.12 the "clearly above/below" margin.
KEY_LEVEL = 0.39
KEY_MARGIN = 0.12

WORLD_UP: Point = (0.0, 1.0, 0.0)   # glTF y-up, see the module docstring

# --- the door leaf (section 5) ---------------------------------------------
#: "Coplanar" for the leaf heuristic: within this many metres of the plane
#: (spec § 6: ±2 cm — img2mesh surfaces are bumpy, a leaf is not a lens).
LEAF_TOL_M = 0.02
#: …and within this cosine of the plane normal (about 18°).
COPLANAR_COS = 0.95
#: A face centre within this of a footprint's edge is ON that edge
#: (:func:`prism_faces`): float32 positions of a 2 m door are exact to
#: about 2.4e-7 m, so a modelled leaf edge and the jamb it hangs in — the
#: same coordinate by construction — both land here, and nothing else does.
PRISM_EDGE_M = 1e-6
#: The seed has to cover this share of the silhouette, or the model has no
#: leaf worth cutting out (spec § 6: "Mindestanteil 30 % der Frontfläche").
#: It is also the least share of cells the THIN thickness class must hold
#: before :func:`thickness_footprint` believes in a leaf at all.
LEAF_MIN_SHARE = 0.30
#: The thickness raster's cell = this share of the LONGER silhouette side,
#: i.e. 40 cells along it (2.5 cm on a door normalised to 1 m height).
THICK_CELL_SHARE = 0.025
#: The per-side edge refinement then runs at cell / THICK_FINE_DIV.
THICK_FINE_DIV = 5
#: The frame class has to be at least this much thicker than the leaf class …
THICK_MIN_RATIO = 1.3
#: … and at least this much thicker in metres. Both together are what keeps
#: a glass door out: its mesh measures 0.027 m against 0.021 m all over
#: (a pane is a HOLE, not a leaf) and fails either test.
THICK_MIN_DIFF_M = 0.015
#: The middle half of the OTHER axis: only samples there refine a side's
#: edge, so the lintel never measures against the jamb.
THICK_BAND = (0.25, 0.75)
#: Sampling guard: no triangle is split into more than this many steps per
#: edge. A door mesh never comes close — the cap only stops a pathological
#: sliver from costing a quadratic number of samples.
_THICK_MAX_DIV = 128

_EPS = 1e-12
# A plane is "horizontal" when its normal is within this of the up axis —
# then up projects to nothing and the frame needs the documented fallback.
_PARALLEL = 1.0 - 1e-6
# fit_plane calls a cloud degenerate when the two smallest eigenvalues are
# this close (relative to the trace): a line or a point has no unique plane.
_RANK_TOL = 1e-9


# ---------------------------------------------------------------------------
# tiny vector helpers (kept private — this is not a vector library)
# ---------------------------------------------------------------------------
def _sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Point, b: Point) -> Point:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a: Point) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a: Point) -> Point:
    n = _norm(a)
    if n <= _EPS:
        return (0.0, 0.0, 0.0)
    # "+ 0.0" only normalises a signed zero (-0.0 + 0.0 == 0.0) and is exact
    # for every other value — a "-0.0" in a stored normal is noise the
    # sidecar and the clients do not need to carry.
    return (a[0] / n + 0.0, a[1] / n + 0.0, a[2] / n + 0.0)


def _edge_key(a: int, b: int) -> Tuple[int, int]:
    """Undirected edge key — a face's winding must not split a component."""
    return (a, b) if a < b else (b, a)


# ---------------------------------------------------------------------------
# 1. colour classification
# ---------------------------------------------------------------------------
def _is_green(r: float, g: float, b: float) -> bool:
    return g > KEY_LEVEL and g > r + KEY_MARGIN and g > b + KEY_MARGIN


def _is_magenta(r: float, g: float, b: float) -> bool:
    return (
        r > KEY_LEVEL
        and b > KEY_LEVEL
        and g < r - KEY_MARGIN
        and g < b - KEY_MARGIN
    )


_KEY_TESTS: Dict[str, Callable[[float, float, float], bool]] = {
    "picture": _is_green,
    "glass": _is_magenta,
}
KINDS = tuple(_KEY_TESTS)


def _key_test(kind: str) -> Callable[[float, float, float], bool]:
    """Resolve the predicate ONCE — the callers sample per face, not per kind."""
    try:
        return _KEY_TESTS[kind]
    except KeyError:
        raise ValueError(
            f"unknown key colour kind {kind!r} (expected one of {KINDS})"
        ) from None


def is_key_colour(rgb: Tuple[float, float, float], kind: str) -> bool:
    """Is this 0..1 RGB triple the chroma key of ``kind``?

    ``picture`` is green:  ``g > 0.39 and g > r + 0.12 and g > b + 0.12``
    ``glass``   is magenta: ``r > 0.39 and b > 0.39 and g < r - 0.12 and
    g < b - 0.12``

    Same rule as ``messaging_frame.py`` (8-bit: ``g > 100``, ``g > r + 30``),
    scaled to 0..1. Alpha is not considered here — the Blender caller has
    already resolved the texel it wants.

    Raises ``ValueError`` for an unknown ``kind``.
    """
    test = _key_test(kind)
    return test(float(rgb[0]), float(rgb[1]), float(rgb[2]))


def face_samples(uv: Sequence[UV], face: Face) -> List[UV]:
    """Three UV points to sample for one triangle.

    The centroid ``c = (A + B + C) / 3`` plus ``c + (P - c) / 3`` for the
    face's FIRST TWO vertices — i.e. one third of the way from the centroid
    towards A and towards B, which is a point on the median through that
    vertex. In barycentric terms ``c + (A - c)/3 = (5/9)A + (2/9)B +
    (2/9)C``: all three weights are positive, so every sample lies strictly
    inside the triangle and can never fall onto a neighbouring texel block
    across the triangle's own edge.
    """
    a, b, c = uv[face[0]], uv[face[1]], uv[face[2]]
    cu = (a[0] + b[0] + c[0]) / 3.0
    cv = (a[1] + b[1] + c[1]) / 3.0
    out: List[UV] = [(cu, cv)]
    for p in (a, b):
        out.append((cu + (p[0] - cu) / 3.0, cv + (p[1] - cv) / 3.0))
    return out


def classify_faces(
    faces: Sequence[Face],
    uvs: Sequence[UV],
    sample_rgb: SampleFn,
    kind: str,
) -> List[bool]:
    """One flag per face: True when >= 2 of its 3 samples show the key colour.

    Two of three tolerates a single stray texel (JPEG ringing, a seam, a
    speck of the frame bleeding into the panel) without letting a face that
    merely grazes the panel count as panel: a triangle straddling the panel
    edge with only one sample inside stays frame.

    Raises ``ValueError`` for an unknown ``kind``.
    """
    test = _key_test(kind)
    flags: List[bool] = []
    for face in faces:
        hits = 0
        for u, v in face_samples(uvs, face):
            r, g, b = sample_rgb(u, v)
            if test(r, g, b):
                hits += 1
        flags.append(hits >= 2)
    return flags


# ---------------------------------------------------------------------------
# 2. connected components
# ---------------------------------------------------------------------------
def components(flags: Sequence[bool], faces: Sequence[Face]) -> List[List[int]]:
    """Group the flagged faces into patches connected over SHARED EDGES.

    Two faces are neighbours when they share two vertex indices, not merely
    one — two panels that touch at a single frame-joint corner must stay two
    patches, or they would be fitted to one averaged plane.

    Returns the face indices per patch, each list ascending, the patches
    sorted by face count descending, ties by smallest face index.
    """
    keyed = [n for n, f in enumerate(flags) if f]
    if not keyed:
        return []

    by_edge: Dict[Tuple[int, int], List[int]] = {}
    for n in keyed:
        a, b, c = faces[n]
        for e in (_edge_key(a, b), _edge_key(b, c), _edge_key(c, a)):
            by_edge.setdefault(e, []).append(n)

    seen = set()
    out: List[List[int]] = []
    for start in keyed:
        if start in seen:
            continue
        group: List[int] = []
        seen.add(start)
        queue = deque([start])
        while queue:
            n = queue.popleft()
            group.append(n)
            a, b, c = faces[n]
            for e in (_edge_key(a, b), _edge_key(b, c), _edge_key(c, a)):
                for m in by_edge.get(e, ()):
                    if m not in seen:
                        seen.add(m)
                        queue.append(m)
        group.sort()
        out.append(group)

    out.sort(key=lambda g: (-len(g), g[0]))
    return out


# ---------------------------------------------------------------------------
# 3. plane fit, frame, planar UVs
# ---------------------------------------------------------------------------
def _jacobi_eigen(m: List[List[float]], sweeps: int = 64):
    """Symmetric 3x3 eigen-decomposition by cyclic Jacobi rotations.

    Pure Python because numpy is not available inside Blender's interpreter
    for this module. Returns ``(eigenvalues, eigenvectors)`` where
    ``eigenvectors[k]`` is the unit vector belonging to ``eigenvalues[k]``.
    """
    a = [row[:] for row in m]
    v = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    for _ in range(sweeps):
        off = abs(a[0][1]) + abs(a[0][2]) + abs(a[1][2])
        if off <= 1e-15:
            break
        for p, q in ((0, 1), (0, 2), (1, 2)):
            apq = a[p][q]
            if abs(apq) <= 1e-18:
                continue
            theta = (a[q][q] - a[p][p]) / (2.0 * apq)
            t = math.copysign(1.0, theta) / (abs(theta) + math.sqrt(theta * theta + 1.0))
            cos = 1.0 / math.sqrt(t * t + 1.0)
            sin = t * cos
            for k in range(3):
                akp, akq = a[k][p], a[k][q]
                a[k][p] = cos * akp - sin * akq
                a[k][q] = sin * akp + cos * akq
            for k in range(3):
                apk, aqk = a[p][k], a[q][k]
                a[p][k] = cos * apk - sin * aqk
                a[q][k] = sin * apk + cos * aqk
            for k in range(3):
                vkp, vkq = v[k][p], v[k][q]
                v[k][p] = cos * vkp - sin * vkq
                v[k][q] = sin * vkp + cos * vkq
    values = [a[0][0], a[1][1], a[2][2]]
    vectors = [(v[0][k], v[1][k], v[2][k]) for k in range(3)]
    return values, vectors


def _orient(n: Point) -> Point:
    """Sign convention: the normal points towards +z, else +y, else +x.

    The first component of ``(z, y, x)`` that is non-zero must be positive.
    A plane has two normals and nothing in the mesh tells us which one the
    author meant, so the choice only has to be DETERMINISTIC — the same
    patch must yield the same normal on every re-run, or the stored planar
    UVs would mirror themselves between refinements.
    """
    for c in (n[2], n[1], n[0]):
        if abs(c) > _EPS:
            return (-n[0], -n[1], -n[2]) if c < 0.0 else n
    return n


def fit_plane(points: Sequence[Point]) -> Tuple[Point, Point]:
    """Least-squares plane through ``points`` -> ``(centroid, unit normal)``.

    The normal is the eigenvector of the SMALLEST eigenvalue of the 3x3
    covariance (scatter) matrix — the direction of least spread. Sign per
    ``_orient``: towards +z, else +y, else +x.

    DEGENERATE INPUT falls back to ``(0, 0, 1)``: fewer than three points, or
    a cloud whose two smallest eigenvalues are not separated by more than
    ``1e-9 * trace``. A line and a single repeated point lie in infinitely
    many planes, and the eigenvector the solver happens to return for them is
    arbitrary — an arbitrary normal would silently produce arbitrary UVs, so
    the caller gets a stated fallback instead. The centroid is always the
    real mean.
    """
    pts = [(float(p[0]), float(p[1]), float(p[2])) for p in points]
    if not pts:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)
    n = float(len(pts))
    centroid = (
        sum(p[0] for p in pts) / n,
        sum(p[1] for p in pts) / n,
        sum(p[2] for p in pts) / n,
    )
    if len(pts) < 3:
        return centroid, (0.0, 0.0, 1.0)

    sxx = syy = szz = sxy = sxz = syz = 0.0
    for p in pts:
        dx, dy, dz = p[0] - centroid[0], p[1] - centroid[1], p[2] - centroid[2]
        sxx += dx * dx
        syy += dy * dy
        szz += dz * dz
        sxy += dx * dy
        sxz += dx * dz
        syz += dy * dz
    cov = [[sxx, sxy, sxz], [sxy, syy, syz], [sxz, syz, szz]]

    values, vectors = _jacobi_eigen(cov)
    order = sorted(range(3), key=lambda k: values[k])
    trace = max(values[0] + values[1] + values[2], 0.0)
    if values[order[1]] - values[order[0]] <= _RANK_TOL * trace:
        return centroid, (0.0, 0.0, 1.0)
    return centroid, _orient(_unit(vectors[order[0]]))


def planar_frame(normal: Point, up: Point = WORLD_UP) -> Tuple[Point, Point]:
    """A right-handed in-plane frame ``(u_axis, v_axis)`` for ``normal``.

    ``v`` IS WORLD-UP PROJECTED INTO THE PLANE — that is the whole point.
    A picture hangs on a wall, so its normal lies in the horizontal plane and
    its "height" must come out along world up; deriving ``u`` from whichever
    axis happens to be most parallel to the plane would hand a wall panel a
    vertical ``u`` and return ``size_m`` transposed with the UVs rotated by
    90 degrees.

    ``u = normalize(up x n)``, ``v = n x u``. Then ``v`` is the up-component
    of the plane and ``u x v = n``, so the triple stays right-handed::

        n = (1, 0, 0)   ->  u = (0, 0, -1),  v = (0, 1, 0)
        n = (-1, 0, 0)  ->  u = (0, 0, 1),   v = (0, 1, 0)
        n = (0, 0, 1)   ->  u = (1, 0, 0),   v = (0, 1, 0)

    HORIZONTAL PLANE (``|n . up| > 1 - 1e-6``, e.g. a table top or a skylight):
    up projects to nothing, so there is no "up" in the plane at all. Then
    ``u`` = world +x projected into the plane and normalised, ``v = n x u`` —
    deterministic, no flip::

        n = (0, 1, 0)   ->  u = (1, 0, 0),   v = (0, 0, -1)
        n = (0, -1, 0)  ->  u = (1, 0, 0),   v = (0, 0, 1)

    ``up`` defaults to glTF world up ``(0, 1, 0)``; see the module docstring
    on why model space is y-up here and Blender converts before calling.
    """
    n = _unit(normal)
    if _norm(n) <= _EPS:
        return (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    up_u = _unit(up)
    if _norm(up_u) <= _EPS:
        up_u = WORLD_UP

    if abs(_dot(n, up_u)) > _PARALLEL:
        axis = (1.0, 0.0, 0.0)
        d = _dot(axis, n)
        u = _unit((axis[0] - d * n[0], axis[1] - d * n[1], axis[2] - d * n[2]))
    else:
        u = _unit(_cross(up_u, n))
    if _norm(u) <= _EPS:            # cannot happen for a unit normal, but be safe
        u = (1.0, 0.0, 0.0)
    return u, _unit(_cross(n, u))


def planar_uvs(
    points: Sequence[Point],
    centroid: Point,
    frame: Tuple[Point, Point],
) -> Tuple[List[UV], Tuple[float, float]]:
    """Project ``points`` into ``frame`` and normalise to 0..1 over the bbox.

    Returns ``(uvs, size_m)`` where ``size_m`` is the bounding-box extent in
    METRES along the u and v axes — i.e. the physical width and height of the
    panel, which is what the picture's aspect ratio has to be fitted to.
    A degenerate extent maps every UV on that axis to 0 (and reports 0 in
    ``size_m``) instead of dividing by zero.
    """
    u_axis, v_axis = frame
    flat = []
    for p in points:
        d = _sub((float(p[0]), float(p[1]), float(p[2])), centroid)
        flat.append((_dot(d, u_axis), _dot(d, v_axis)))
    if not flat:
        return [], (0.0, 0.0)

    umin = min(a for a, _ in flat)
    umax = max(a for a, _ in flat)
    vmin = min(b for _, b in flat)
    vmax = max(b for _, b in flat)
    du = umax - umin
    dv = vmax - vmin
    out = [
        (
            (a - umin) / du if du > _EPS else 0.0,
            (b - vmin) / dv if dv > _EPS else 0.0,
        )
        for a, b in flat
    ]
    return out, (du, dv)


# ---------------------------------------------------------------------------
# 4. the whole pipeline + the outline
# ---------------------------------------------------------------------------
def _triangle_area(vertices: Sequence[Point], face: Face) -> float:
    a, b, c = vertices[face[0]], vertices[face[1]], vertices[face[2]]
    return 0.5 * _norm(_cross(_sub(b, a), _sub(c, a)))


def detect_areas(
    vertices: Sequence[Point],
    faces: Sequence[Face],
    uvs: Sequence[UV],
    sample_rgb: SampleFn,
    kind: str,
    *,
    min_area_m2: float = 0.02,
    min_faces: int = 12,
) -> List[Dict]:
    """Find the key-coloured panels of one mesh.

    ``vertices`` are metres, ``uvs`` are per-vertex texture coordinates
    parallel to ``vertices``, ``sample_rgb(u, v)`` returns the texture's
    0..1 RGB at that coordinate.

    A component is dropped when it has fewer than ``min_faces`` faces OR its
    summed 3D triangle area is below ``min_area_m2``. The two filters are
    independent on purpose: a dense speck of chroma noise can carry plenty of
    tiny triangles, and a single huge stray triangle carries none.

    The result is re-sorted by AREA descending (ties by smallest face index)
    — unlike ``components``, which orders by face count. ``size_m`` can carry
    a 0 component when the patch is degenerate along one axis; see
    ``planar_uvs``.

    One dict per surviving component::

        {"kind": str,
         "faces": [face index, …],          # ascending
         "normal": (x, y, z),                # unit, oriented per fit_plane
         "centroid": (x, y, z),              # metres
         "size_m": (w, h),                   # bbox extent along u / v
         "uvs": {vertex index: (u, v)},      # 0..1 over that bbox
         "area_m2": float}                   # summed triangle area
    """
    flags = classify_faces(faces, uvs, sample_rgb, kind)
    out: List[Dict] = []
    for group in components(flags, faces):
        if len(group) < min_faces:
            continue
        area = sum(_triangle_area(vertices, faces[n]) for n in group)
        if area < min_area_m2:
            continue
        verts = sorted({v for n in group for v in faces[n]})
        points = [vertices[v] for v in verts]
        centroid, normal = fit_plane(points)
        frame = planar_frame(normal)
        flat, size_m = planar_uvs(points, centroid, frame)
        out.append(
            {
                "kind": kind,
                "faces": group,
                "normal": normal,
                "centroid": centroid,
                "size_m": size_m,
                "uvs": {v: flat[i] for i, v in enumerate(verts)},
                "area_m2": area,
            }
        )
    out.sort(key=lambda d: (-d["area_m2"], d["faces"][0]))
    return out


def area_edges(
    vertices: Sequence[Point],
    faces: Sequence[Face],
    face_idx: Sequence[int],
) -> List[Tuple[Point, Point]]:
    """The outline of a face set: every edge used by exactly ONE of its faces.

    Interior edges are shared by two faces of the set and drop out; what is
    left is the boundary polygon(s) as unordered segments, ready to draw as
    an overlay. Returned as world-metre point pairs.
    """
    counts: Dict[Tuple[int, int], int] = {}
    for n in face_idx:
        a, b, c = faces[n]
        for e in (_edge_key(a, b), _edge_key(b, c), _edge_key(c, a)):
            counts[e] = counts.get(e, 0) + 1
    return [
        (tuple(vertices[a]), tuple(vertices[b]))
        for (a, b), n in counts.items()
        if n == 1
    ]


# ---------------------------------------------------------------------------
# 5. the door leaf (spec § 6, D7) — geometry only, no colour
# ---------------------------------------------------------------------------
Rect2 = Tuple[Tuple[float, float], Tuple[float, float]]


def _centroid(vertices: Sequence[Point], face: Face) -> Point:
    a, b, c = vertices[face[0]], vertices[face[1]], vertices[face[2]]
    return ((a[0] + b[0] + c[0]) / 3.0, (a[1] + b[1] + c[1]) / 3.0,
            (a[2] + b[2] + c[2]) / 3.0)


def face_normals(vertices: Sequence[Point], faces: Sequence[Face]) -> List[Point]:
    """Unit normal per triangle from its winding (``(b − a) × (c − a)``);
    a degenerate triangle gets ``(0, 0, 0)`` and can never be coplanar with
    anything. Computed HERE rather than read off the mesh, so the leaf
    heuristic sees the same y-up coordinates the rest of the module does."""
    out: List[Point] = []
    for face in faces:
        a, b, c = vertices[face[0]], vertices[face[1]], vertices[face[2]]
        out.append(_unit(_cross(_sub(b, a), _sub(c, a))))
    return out


def _face_edges(face: Face):
    a, b, c = face
    return (_edge_key(a, b), _edge_key(b, c), _edge_key(c, a))


def _edge_index(faces: Sequence[Face], face_idx) -> Dict[Tuple[int, int], List[int]]:
    by_edge: Dict[Tuple[int, int], List[int]] = {}
    for n in face_idx:
        for e in _face_edges(faces[n]):
            by_edge.setdefault(e, []).append(n)
    return by_edge


def planar_clusters(vertices: Sequence[Point], faces: Sequence[Face],
                    normals: Sequence[Point], *, tol: float = LEAF_TOL_M,
                    cos_min: float = COPLANAR_COS) -> List[Dict]:
    """Connected, coplanar face groups: a neighbour over a SHARED EDGE joins
    when its normal is within ``cos_min`` of the cluster's first face and
    its centroid within ``tol`` of that face's plane.

    One dict per cluster — ``{"faces": [ascending], "normal": unit (the
    seed face's), "offset": area-weighted mean of ``normal · centroid``,
    "area": summed triangle area}`` — sorted by area DESCENDING; a tie
    (a plate's front and back have the same area) goes to the normal that
    points towards +z, then +y, then +x — the same preference
    :func:`fit_plane` states for its sign, so the "front view" of a symmetric
    model is the same on every run — and after that to the smallest face
    index.
    """
    by_edge = _edge_index(faces, range(len(faces)))
    seen = [False] * len(faces)
    out: List[Dict] = []
    for start in range(len(faces)):
        if seen[start]:
            continue
        n0 = normals[start]
        if _norm(n0) <= _EPS:
            seen[start] = True
            continue
        d0 = _dot(n0, _centroid(vertices, faces[start]))
        seen[start] = True
        group = [start]
        queue = deque([start])
        while queue:
            k = queue.popleft()
            for e in _face_edges(faces[k]):
                for m in by_edge.get(e, ()):
                    if seen[m]:
                        continue
                    if _dot(normals[m], n0) < cos_min:
                        continue
                    if abs(_dot(n0, _centroid(vertices, faces[m])) - d0) > tol:
                        continue
                    seen[m] = True
                    group.append(m)
                    queue.append(m)
        group.sort()
        areas = [_triangle_area(vertices, faces[k]) for k in group]
        total = sum(areas)
        offset = (sum(a * _dot(n0, _centroid(vertices, faces[k]))
                      for a, k in zip(areas, group)) / total) if total > _EPS else d0
        out.append({"faces": group, "normal": n0, "offset": offset, "area": total})
    out.sort(key=lambda c: (-round(c["area"], 9), -c["normal"][2], -c["normal"][1],
                            -c["normal"][0], c["faces"][0]))
    return out


def _project(plane: Dict, p: Point) -> Tuple[float, float, float]:
    """``(u, v, depth)`` of a point: in-plane coordinates along the frame
    axes (absolute, not centred) and the signed distance off the plane."""
    return (_dot(plane["u"], p), _dot(plane["v"], p),
            _dot(plane["normal"], p) - plane["offset"])


def _lattice_steps(a: Tuple[float, float, float], b: Tuple[float, float, float],
                   c: Tuple[float, float, float], step: float) -> int:
    """How many pieces a triangle's edges are cut into so no piece spans more
    than ``step`` in u, in v or in DEPTH — at least 2, at most
    ``_THICK_MAX_DIV``. Depth counts because a face standing EDGE-ON to the
    plane (a jamb's side, a leaf's own edge) has almost no reach in u and v
    and all of its reach in depth, and it is depth this raster measures."""
    if step <= _EPS:
        return 2
    reach = 0.0
    for p, q in ((a, b), (b, c), (c, a)):
        reach = max(reach, abs(q[0] - p[0]), abs(q[1] - p[1]), abs(q[2] - p[2]))
    return max(2, min(_THICK_MAX_DIV, int(math.ceil(reach / step))))


def _surface_samples(vertices: Sequence[Point], faces: Sequence[Face],
                     plane: Dict, step: float,
                     ) -> List[Tuple[float, float, float]]:
    """The mesh SURFACE as projected ``(u, v, depth)`` points, dense enough
    that a triangle marks every raster cell it covers with its true depth.

    Per triangle the barycentric lattice ``i + j + k = n`` plus the
    centroid, with ``n`` chosen so no lattice edge spans more than ``step``.
    For a triangle no bigger than ``step`` that is ``n = 2``: the three
    corners and the three edge midpoints, plus the centroid — SEVEN points,
    all an img2mesh door (edges around a centimetre against 2.5 cm cells)
    ever needs. A MODELLED fixture, though, carries triangles spanning the
    whole door, and seven points leave 95 % of the raster empty (measured
    on the smoke's fixture F: 43 of 760 cells); an empty raster has neither
    frame nor leaf. The lattice is symmetric in the three corners on
    purpose — a lattice built from two edges alone misses the third and
    reads a jamb's side face as half as deep as it is.
    """
    out: List[Tuple[float, float, float]] = []
    for face in faces:
        a = _project(plane, vertices[face[0]])
        b = _project(plane, vertices[face[1]])
        c = _project(plane, vertices[face[2]])
        n = _lattice_steps(a, b, c, step)
        for i in range(n + 1):
            for j in range(n + 1 - i):
                wa, wb, wc = i / n, j / n, (n - i - j) / n
                out.append((wa * a[0] + wb * b[0] + wc * c[0],
                            wa * a[1] + wb * b[1] + wc * c[1],
                            wa * a[2] + wb * b[2] + wc * c[2]))
        out.append(((a[0] + b[0] + c[0]) / 3.0, (a[1] + b[1] + c[1]) / 3.0,
                    (a[2] + b[2] + c[2]) / 3.0))
    return out


def _bin_thickness(samples: Sequence[Tuple[float, float, float]],
                   u0: float, v0: float, cell_u: float, cell_v: float,
                   nu: int, nv: int) -> List[List[Optional[float]]]:
    """Depth EXTENT per cell — ``dmax - dmin`` of the samples that fall into
    it, ``None`` for a cell no sample reached. A sample past the last row or
    column is put INTO it: that is the silhouette's own far edge, where
    ``ceil`` cut the raster off and the mesh goes on."""
    dmin: List[List[Optional[float]]] = [[None] * nu for _ in range(nv)]
    dmax: List[List[Optional[float]]] = [[None] * nu for _ in range(nv)]
    for su, sv, sd in samples:
        iu = min(nu - 1, max(0, int(math.floor((su - u0) / cell_u))))
        iv = min(nv - 1, max(0, int(math.floor((sv - v0) / cell_v))))
        lo, hi = dmin[iv][iu], dmax[iv][iu]
        if lo is None or sd < lo:
            dmin[iv][iu] = sd
        if hi is None or sd > hi:
            dmax[iv][iu] = sd
    return [[None if dmin[r][c] is None else dmax[r][c] - dmin[r][c]  # type: ignore[operator]
             for c in range(nu)] for r in range(nv)]


def thickness_map(vertices: Sequence[Point], faces: Sequence[Face],
                  plane: Dict, bbox2d: Rect2, *, cell: float) -> Dict:
    """HOW DEEP THE MESH IS, cell by cell over the silhouette.

    ``bbox2d = ((u0, v0), (u1, v1))`` is rastered into ``ceil`` cells of
    ``cell`` metres per axis; a point lands in ``floor((u - u0) / cell)``,
    clamped to the last row/column. Each cell reports ``dmax - dmin`` of the
    surface samples that fall into it — the material's DEPTH EXTENT along
    the plane normal, which is the one measure that tells a door's frame
    (a solid jamb) from its leaf (a thin panel) without asking any face
    which way it points. A cell no sample reached is ``None``: a hole, and
    a hole is neither.

    Returns ``{"nu", "nv", "cell", "thick"}`` — ``thick`` indexed
    ``[iv][iu]``, rows bottom-up in the plane's own v.
    """
    (u0, v0), (u1, v1) = bbox2d
    nu = max(1, int(math.ceil((u1 - u0) / cell)))
    nv = max(1, int(math.ceil((v1 - v0) / cell)))
    samples = _surface_samples(vertices, faces, plane, 0.5 * cell)
    return {"nu": nu, "nv": nv, "cell": cell,
            "thick": _bin_thickness(samples, u0, v0, cell, cell, nu, nv)}


def otsu_split(values: Sequence[float]) -> Tuple[float, float, float]:
    """Otsu's two-class threshold, computed EXACTLY (no histogram): sort the
    values and pick the cut ``k`` that maximises the between-class variance
    ``w0 * w1 * (m1 - m0)^2``. Returns ``(split, mean_low, mean_high)`` with
    ``split`` half way between the two values the cut separates.

    A single value answers itself three times — the caller's gate then sees
    a difference of 0 and knows there are no two classes. Raises
    ``ValueError`` on an empty sequence.
    """
    s = sorted(float(x) for x in values)
    n = len(s)
    if n == 0:
        raise ValueError("otsu_split needs at least one value")
    if n == 1:
        return s[0], s[0], s[0]
    prefix = [0.0]
    for x in s:
        prefix.append(prefix[-1] + x)
    best = -1.0
    split = m_low = m_high = s[0]
    for k in range(1, n):
        w0, w1 = k / n, (n - k) / n
        mean0 = prefix[k] / k
        mean1 = (prefix[n] - prefix[k]) / (n - k)
        var = w0 * w1 * (mean1 - mean0) ** 2
        if var > best:
            best = var
            split = (s[k - 1] + s[k]) / 2.0
            m_low, m_high = mean0, mean1
    return split, m_low, m_high


def _frame_cells(thick: List[List[Optional[float]]], nu: int, nv: int,
                 split: float):
    """The FRAME: the thick cells connected (4-neighbourhood) to a thick cell
    on the raster's outermost row or column. A door's jambs, rails and
    lintel form that ring; a handle bolted to the leaf and a lock rail
    spanning it are thick too, but they hang off the ring and come along
    with it, while an ENCLOSED thick island (or a hole, which is not thick
    at all) does not. Empty cells block the walk like thin ones do: a
    missing pane is not a frame."""
    def is_thick(iu: int, iv: int) -> bool:
        t = thick[iv][iu]
        return t is not None and t >= split

    seen = set()
    queue = deque()
    for iv in range(nv):
        for iu in range(nu):
            if (iu in (0, nu - 1) or iv in (0, nv - 1)) and is_thick(iu, iv):
                if (iu, iv) not in seen:
                    seen.add((iu, iv))
                    queue.append((iu, iv))
    while queue:
        iu, iv = queue.popleft()
        for du, dv in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nu_, nv_ = iu + du, iv + dv
            if 0 <= nu_ < nu and 0 <= nv_ < nv and (nu_, nv_) not in seen \
                    and is_thick(nu_, nv_):
                seen.add((nu_, nv_))
                queue.append((nu_, nv_))
    return seen


def _refine_edge(samples: Sequence[Tuple[float, float, float]], axis: int,
                 edge: float, sign: float, band: Tuple[float, float],
                 cell: float, fine: float, split: float, bound: float) -> float:
    """Walk ONE coarse edge outward while the next fine column is thin.

    The column is ``fine`` wide and reaches across the middle half of the
    other axis only (``THICK_BAND`` of the coarse rectangle), so the top
    rail never has a say about where the left edge is. It counts as thin
    when at least HALF of the band rows it does touch (rows ``cell`` tall,
    the raster's own rows) read less than ``split`` — a median, not a
    minimum, because a handle is a thick peninsula a few rows tall and must
    not stop the edge. Rows the column does not reach at all say nothing;
    a column that reaches none is thin, since nothing there is frame.
    The walk stops after one coarse cell, or at ``bound`` (the silhouette).
    """
    other = 1 - axis
    band_lo, band_hi = band
    n_rows = max(1, int(math.ceil((band_hi - band_lo) / cell)))
    limit = edge + sign * cell
    limit = max(limit, bound) if sign < 0 else min(limit, bound)
    strip_lo, strip_hi = min(edge, limit), max(edge, limit)
    strip = [s for s in samples
             if strip_lo <= s[axis] <= strip_hi and band_lo <= s[other] < band_hi]
    while abs(limit - edge) > _EPS:
        step = edge + sign * fine
        step = max(step, limit) if sign < 0 else min(step, limit)
        lo, hi = min(edge, step), max(edge, step)
        dmin: List[Optional[float]] = [None] * n_rows
        dmax: List[Optional[float]] = [None] * n_rows
        for s in strip:
            if not lo <= s[axis] < hi:
                continue
            r = int(math.floor((s[other] - band_lo) / cell))
            if r < 0 or r >= n_rows:
                continue
            if dmin[r] is None or s[2] < dmin[r]:
                dmin[r] = s[2]
            if dmax[r] is None or s[2] > dmax[r]:
                dmax[r] = s[2]
        solid = thin = 0
        for r in range(n_rows):
            if dmin[r] is None:
                continue
            solid += 1
            if dmax[r] - dmin[r] < split:   # type: ignore[operator]
                thin += 1
        if 2 * thin < solid:
            break
        edge = step
    return edge


def _snap_edge(coords: Sequence[float], edge: float, fine: float) -> float:
    """The vertex coordinate nearest to ``edge`` within ``±fine``, else
    ``edge`` itself. On a MODELLED mesh this reproduces the coincidence line
    "leaf edge = jamb inner face" exactly, which is what lets the edge rule
    of :func:`prism_faces` tell the two apart; on an img2mesh door it is a
    harmless vertex half a centimetre away."""
    best = None
    for c in coords:
        d = abs(c - edge)
        if d <= fine and (best is None or (d, c) < best):
            best = (d, c)
    return edge if best is None else best[1]


def thickness_footprint(vertices: Sequence[Point], faces: Sequence[Face],
                        plane: Dict, bbox2d: Rect2, *,
                        cell_share: float = THICK_CELL_SHARE,
                        fine_div: int = THICK_FINE_DIV,
                        min_ratio: float = THICK_MIN_RATIO,
                        min_diff: float = THICK_MIN_DIFF_M,
                        min_share: float = LEAF_MIN_SHARE,
                        ) -> Optional[Rect2]:
    """THE LEAF'S FOOTPRINT FROM THE MATERIAL THICKNESS (plan-blatt-dicke.md,
    2026-08-28) — ``((u_lo, v_lo), (u_hi, v_hi))`` in the absolute u/v of
    ``plane``, or None when this mesh has no leaf.

    1. Raster the silhouette into cells of ``cell_share`` of its longer side
       and measure each cell's depth extent (:func:`thickness_map`).
    2. Cut the non-empty cells into two classes with :func:`otsu_split`.
       They only count as a FRAME and a LEAF when the thick class is at
       least ``min_ratio`` times and ``min_diff`` metres thicker than the
       thin one and the thin class holds at least ``min_share`` of the
       cells — otherwise there is no leaf: a glass door is 2.7 cm all over
       (its pane is a hole), and a leaf lying on its own is 2 cm all over.
    3. The FRAME is the thick region touching the border
       (:func:`_frame_cells`); every other cell is leaf-side, the enclosed
       thick ones included — a handle stands proud of the leaf and a lock
       rail spans its full width, and neither is allowed to crop it.
    4. The coarse rectangle is the bounding box of the leaf cells, clipped
       to the silhouette.
    5. Each side is then refined at ``cell / fine_div``
       (:func:`_refine_edge`) and snapped onto the nearest vertex
       coordinate (:func:`_snap_edge`).

    WHY THIS AND NOT THE RIM v2 MEASURED: that one read the ORIENTATION of
    single faces (a normal sideways to the leaf plane) and mistook a bumpy
    img2mesh surface for a rim — three of four measured wooden doors ended
    up with a footprint around the middle third and no leaf at all.
    """
    (u0, v0), (u1, v1) = bbox2d
    du, dv = u1 - u0, v1 - v0
    if du <= _EPS or dv <= _EPS:
        return None
    cell = cell_share * max(du, dv)
    if cell <= _EPS:
        return None
    fine = cell / max(1, int(fine_div))
    nu = max(1, int(math.ceil(du / cell)))
    nv = max(1, int(math.ceil(dv / cell)))
    samples = _surface_samples(vertices, faces, plane, 0.5 * cell)
    thick = _bin_thickness(samples, u0, v0, cell, cell, nu, nv)

    flat = [t for row in thick for t in row if t is not None]
    if not flat:
        return None
    split, m_thin, m_thick = otsu_split(flat)
    if m_thick < min_ratio * m_thin or m_thick - m_thin < min_diff:
        return None
    if sum(1 for t in flat if t < split) < min_share * len(flat):
        return None

    frame = _frame_cells(thick, nu, nv, split)
    leaf = [(iu, iv) for iv in range(nv) for iu in range(nu)
            if (iu, iv) not in frame]
    if not leaf:
        return None
    c0 = min(c for c, _ in leaf)
    c1 = max(c for c, _ in leaf)
    r0 = min(r for _, r in leaf)
    r1 = max(r for _, r in leaf)
    u_lo, u_hi = max(u0, u0 + c0 * cell), min(u1, u0 + (c1 + 1) * cell)
    v_lo, v_hi = max(v0, v0 + r0 * cell), min(v1, v0 + (r1 + 1) * cell)

    band_u = (u_lo + THICK_BAND[0] * (u_hi - u_lo),
              u_lo + THICK_BAND[1] * (u_hi - u_lo))
    band_v = (v_lo + THICK_BAND[0] * (v_hi - v_lo),
              v_lo + THICK_BAND[1] * (v_hi - v_lo))
    u_lo = _refine_edge(samples, 0, u_lo, -1.0, band_v, cell, fine, split, u0)
    u_hi = _refine_edge(samples, 0, u_hi, 1.0, band_v, cell, fine, split, u1)
    v_lo = _refine_edge(samples, 1, v_lo, -1.0, band_u, cell, fine, split, v0)
    v_hi = _refine_edge(samples, 1, v_hi, 1.0, band_u, cell, fine, split, v1)

    us = [_dot(plane["u"], p) for p in vertices]
    vs = [_dot(plane["v"], p) for p in vertices]
    u_lo, u_hi = _snap_edge(us, u_lo, fine), _snap_edge(us, u_hi, fine)
    v_lo, v_hi = _snap_edge(vs, v_lo, fine), _snap_edge(vs, v_hi, fine)
    if u_hi - u_lo <= _EPS or v_hi - v_lo <= _EPS:
        return None
    return ((u_lo, v_lo), (u_hi, v_hi))


def leaf_candidates(vertices: Sequence[Point], faces: Sequence[Face],
                    normals: Sequence[Point], plane: Dict) -> List[int]:
    """THE v1 SKIN HEURISTIC (spec-picture-props.md § 6) — the faces of the
    door leaf for one leaf plane as seed + edge growth: ascending flat
    indices, ``[]`` when nothing qualifies. NOT what :func:`detect_leaf`
    cuts any more (E2 — :func:`prism_faces` is): kept as the measured
    reference the prism is compared against (fixture G of
    ``scripts/smoke_picture_areas.py`` shows it missing a frame's back
    skin behind the leaf), and as the one-flag way back to a skin cut.

    ``plane`` is what :func:`leaf_plane` builds: ``normal``, ``offset``
    (``normal · point`` on the leaf plane), the in-plane axes ``u`` / ``v``,
    ``inner`` (the leaf's footprint from the material thickness, in
    absolute u/v),
    ``front_offset`` (the frame front's ``normal · point``) and ``tol``.

    THE SEED (spec § 6): every face facing the plane normal (cos ≥
    ``COPLANAR_COS``) with its centroid within ``tol`` of the plane and
    STRICTLY inside ``inner`` — grouped over shared edges, the group with
    the largest area wins. THE GROWTH: from the seed over shared edges into
    every face that (a) is not the FRAME FRONT (facing the plane normal
    within ``tol`` of ``front_offset`` — same orientation only, so a 2 cm
    leaf's back is never mistaken for it), (b) has all its
    vertices inside the SEED's own in-plane extent widened by ``tol`` (the
    leaf front's true edges — ``inner`` is only an estimate) and (c) has no vertex more
    than ``tol`` proud of the leaf plane — the leaf's thickness and its back,
    but not the jamb the leaf hangs in and not the frame's back. A leaf set
    back into a proud frame therefore stops at the rebate; a leaf FLUSH with
    its frame takes the rebate strip along (at most ``tol`` deep).
    """
    n = plane["normal"]
    tol = float(plane.get("tol", LEAF_TOL_M))
    cos_min = float(plane.get("cos_min", COPLANAR_COS))
    (iu0, iv0), (iu1, iv1) = plane["inner"]
    front_depth = float(plane.get("front_offset", plane["offset"])) - plane["offset"]

    flags = []
    for k, face in enumerate(faces):
        cu, cv, cd = _project(plane, _centroid(vertices, face))
        flags.append(_dot(normals[k], n) >= cos_min and abs(cd) <= tol
                     and iu0 < cu < iu1 and iv0 < cv < iv1)
    groups = components(flags, faces)
    if not groups:
        return []
    seed = max(groups, key=lambda g: (sum(_triangle_area(vertices, faces[k]) for k in g),
                                      -g[0]))

    # The growth bound is the SEED'S OWN in-plane extent, widened by tol —
    # the leaf front's true edges. Not the footprint: that one is measured
    # off a raster and would cut the leaf's edge faces off whenever it comes
    # out a little tight.
    seed_pts = [_project(plane, vertices[i]) for k in seed for i in faces[k]]
    su0 = min(p[0] for p in seed_pts) - tol
    su1 = max(p[0] for p in seed_pts) + tol
    sv0 = min(p[1] for p in seed_pts) - tol
    sv1 = max(p[1] for p in seed_pts) + tol

    def grows(k: int) -> bool:
        cu, cv, cd = _project(plane, _centroid(vertices, faces[k]))
        if _dot(normals[k], n) >= cos_min and abs(cd - front_depth) <= tol:
            return False                        # the frame front
        for i in faces[k]:
            pu, pv, pd = _project(plane, vertices[i])
            if pu < su0 or pu > su1 or pv < sv0 or pv > sv1:
                return False
            if pd > tol:
                return False
        return True

    by_edge = _edge_index(faces, range(len(faces)))
    chosen = set(seed)
    queue = deque(seed)
    while queue:
        k = queue.popleft()
        for e in _face_edges(faces[k]):
            for m in by_edge.get(e, ()):
                if m in chosen or not grows(m):
                    continue
                chosen.add(m)
                queue.append(m)
    return sorted(chosen)


def leaf_plane(vertices: Sequence[Point], faces: Sequence[Face],
               normals: Optional[Sequence[Point]] = None, *,
               tol: float = LEAF_TOL_M, cos_min: float = COPLANAR_COS,
               ) -> Optional[Dict]:
    """The plane dict :func:`leaf_candidates` works on, or None: the largest
    planar cluster's plane (the "front view"), the silhouette ``bbox2d`` of
    ALL vertices in that plane, the ``inner`` rectangle from
    :func:`thickness_footprint` and the frame front — the largest cluster
    facing the same way whose centroid lies OUTSIDE that rectangle (falls
    back to the leaf plane itself).

    NONE for an empty mesh, a mesh without a planar cluster, and — since
    plan-blatt-dicke.md — for a mesh whose material thickness does not fall
    into two classes: no frame against a leaf means no leaf to cut, and the
    Blender side reports "no leaf" for it (a glass door, a bare panel)."""
    if not faces:
        return None
    if normals is None:
        normals = face_normals(vertices, faces)
    clusters = planar_clusters(vertices, faces, normals, tol=tol, cos_min=cos_min)
    if not clusters:
        return None
    top = clusters[0]
    n = top["normal"]
    u, v = planar_frame(n)
    plane: Dict = {"normal": n, "offset": top["offset"], "u": u, "v": v,
                   "tol": tol, "cos_min": cos_min}
    us = [_dot(u, p) for p in vertices]
    vs = [_dot(v, p) for p in vertices]
    bbox2d: Rect2 = ((min(us), min(vs)), (max(us), max(vs)))
    inner = thickness_footprint(vertices, faces, plane, bbox2d)
    if inner is None:
        return None
    plane.update({"bbox2d": bbox2d, "inner": inner})
    front = top["offset"]
    for c in clusters:
        if _dot(c["normal"], n) < cos_min:
            continue
        pts = [vertices[i] for k in c["faces"] for i in faces[k]]
        cu = sum(_dot(u, p) for p in pts) / len(pts)
        cv = sum(_dot(v, p) for p in pts) / len(pts)
        if inner[0][0] < cu < inner[1][0] and inner[0][1] < cv < inner[1][1]:
            continue
        front = c["offset"]
        break
    plane["front_offset"] = front
    return plane


def prism_faces(vertices: Sequence[Point], faces: Sequence[Face],
                footprint: Rect2, axis: Point, *,
                normals: Optional[Sequence[Point]] = None,
                edge: float = PRISM_EDGE_M) -> List[int]:
    """THE DOOR LEAF AS A PRISM (spec-bild-props-v2.md E2): every face whose
    centre projects into ``footprint`` along ``axis`` — at ANY depth, with
    ANY normal — as ascending flat indices. Front skin, back skin, edges and
    handles of a leaf all stand in one column over the leaf's footprint, and
    so does the part of a frame's back skin that sits behind the leaf: that
    part swings with the leaf or the door is "shut and open at once".

    ``footprint`` is ``((u0, v0), (u1, v1))`` in the in-plane frame
    :func:`planar_frame` builds for ``axis`` (absolute u/v, the coordinates
    :func:`leaf_plane` reports ``inner`` in); the sign of ``axis`` does not
    matter — the frame flips with it and the footprint is expressed in that
    same frame. Strictly inside is inside.

    ON THE EDGE (within ``edge`` of it — sub-micron, i.e. the same
    coordinate by construction, which only a modelled mesh produces): a
    leaf's own edge face and the jamb face it hangs against lie on exactly
    the footprint's edge, at the same u AND spanning the same v when the
    jamb is a rail — nothing in the plane tells them apart, but their
    normals do. The leaf's edge points OUT of the footprint, the jamb points
    INTO it. So a face on the edge belongs when its normal has a component
    along the outward direction of that edge, and stays out otherwise (a
    face lying flat on the edge line has none and stays out).
    """
    n = _unit(axis)
    if _norm(n) <= _EPS or not faces:
        return []
    u_axis, v_axis = planar_frame(n)
    if normals is None:
        normals = face_normals(vertices, faces)
    (u0, v0), (u1, v1) = footprint
    out: List[int] = []
    for k, face in enumerate(faces):
        c = _centroid(vertices, face)
        cu, cv = _dot(u_axis, c), _dot(v_axis, c)
        if cu < u0 - edge or cu > u1 + edge or cv < v0 - edge or cv > v1 + edge:
            continue
        ou = -1.0 if abs(cu - u0) <= edge else (1.0 if abs(cu - u1) <= edge else 0.0)
        ov = -1.0 if abs(cv - v0) <= edge else (1.0 if abs(cv - v1) <= edge else 0.0)
        if ou == 0.0 and ov == 0.0:
            out.append(k)
            continue
        nk = normals[k]
        if ou * _dot(u_axis, nk) + ov * _dot(v_axis, nk) > _EPS:
            out.append(k)
    return out


def list_footprint(vertices: Sequence[Point], faces: Sequence[Face],
                   listed: Sequence[int]) -> Tuple[Rect2, Point]:
    """The footprint a face list stands over: ``(rect, axis)`` — the axis
    is the normal of the least-squares plane of the listed faces' vertices
    (for a leaf picked front, back and edges together that is the door's
    depth axis, for a front skin alone it is the same), the rect the
    bounding rectangle of the listed faces' CENTRES in that plane's
    :func:`planar_frame`, EXACT (no padding: a face whose centre sits on
    its edge is decided by the edge rule of :func:`prism_faces`, which is
    what keeps a jamb coincident with the leaf's edge out). Centres, not
    vertices: a coarse triangle reaches far past where the list stands.
    Raises ``ValueError`` for an empty list.
    """
    idx = sorted({int(k) for k in listed})
    if not idx:
        raise ValueError("an empty face list has no footprint")
    verts = sorted({i for k in idx for i in faces[k]})
    _c, normal = fit_plane([vertices[i] for i in verts])
    u_axis, v_axis = planar_frame(normal)
    us, vs = [], []
    for k in idx:
        c = _centroid(vertices, faces[k])
        us.append(_dot(u_axis, c))
        vs.append(_dot(v_axis, c))
    return ((min(us), min(vs)), (max(us), max(vs))), normal


def leaf_prism(vertices: Sequence[Point], faces: Sequence[Face],
               listed: Sequence[int], *,
               normals: Optional[Sequence[Point]] = None) -> List[int]:
    """A hand-picked face list turned into the prism through ITS OWN
    footprint (E2, the manual cut with ``through``): :func:`prism_faces`
    through :func:`list_footprint`, UNITED with the list itself — what the
    admin ringed is always in, and a face on the footprint's edge that is
    not listed follows the edge rule (a jamb coincident with the leaf's
    edge stays out). A polygon the admin drew over the front therefore
    takes the back and the edges under it along, whatever the client
    tested; and a list that already IS a prism comes back as ITSELF
    (fixture G: the 332 prism faces listed give exactly 332). ``[]`` for
    an empty list.
    """
    idx = sorted({int(k) for k in listed})
    if not idx:
        return []
    footprint, normal = list_footprint(vertices, faces, idx)
    return sorted(set(idx) | set(prism_faces(vertices, faces, footprint, normal,
                                             normals=normals)))


def leaf_residual(vertices: Sequence[Point], faces: Sequence[Face],
                  footprint: Rect2, axis: Point, frame_faces: Sequence[int], *,
                  tol: float = LEAF_TOL_M) -> int:
    """How many ``frame_faces`` still stand inside THE SPLIT'S FOOTPRINT
    after a cut — the count of frame faces whose centre projects more than
    ``tol`` inside ``footprint`` along ``axis`` (E2 — "n Faces des Rahmens
    liegen in der Blatt-Grundfläche", the warning that keeps a skin cut
    from staying silent). The footprint is the one the cut was made
    through: the thickness footprint for an automatic cut, the list's
    :func:`list_footprint` for a manual one (with ``through`` that is the
    prism's; without it the outline of the faces the admin listed — and a
    v1-style skin list of a leaf's middle then reports the back skin it
    left behind). Shrunk by ``tol`` so a jamb face sitting ON the outline,
    or the ring of a bumpy mesh straddling it, is not a residual; a clean
    prism cut answers 0. 0 for an empty frame.
    """
    if not frame_faces:
        return 0
    n = _unit(axis)
    if _norm(n) <= _EPS:
        return 0
    u_axis, v_axis = planar_frame(n)
    # the footprint shrunk by tol on every side, never past its own middle
    (f0, g0), (f1, g1) = footprint
    mu, mv = (f0 + f1) / 2.0, (g0 + g1) / 2.0
    u0, v0 = min(f0 + tol, mu), min(g0 + tol, mv)
    u1, v1 = max(f1 - tol, mu), max(g1 - tol, mv)
    count = 0
    for k in frame_faces:
        c = _centroid(vertices, faces[k])
        cu, cv = _dot(u_axis, c), _dot(v_axis, c)
        if u0 < cu < u1 and v0 < cv < v1:
            count += 1
    return count


def clamp_bbox(box: Tuple[Point, Point], footprint: Rect2,
               axis: Point) -> Tuple[Point, Point]:
    """``leaf_bbox`` held to the split's footprint IN THE PLANE: a
    back-skin face straddling the footprint's edge is taken into the leaf
    by its centre and reaches past the edge with a vertex, and the hinge a
    renderer hangs on the box's edge (``leafPivot``: x = min) must land on
    the leaf's edge, not the door's outer edge. Each model axis that
    coincides with ±u or ±v of the footprint's frame (within 1e-6 — every
    axis-aligned door; a tilted footprint clamps nothing on that axis) has
    its range intersected with the footprint's range on that axis, sign
    respected; the depth axis is never touched. Never inverts: a footprint
    that does not overlap the box leaves the box alone on that axis.
    """
    n = _unit(axis)
    if _norm(n) <= _EPS:
        return box
    u_axis, v_axis = planar_frame(n)
    lo, hi = list(box[0]), list(box[1])
    for frame_axis, (f0, f1) in ((u_axis, (footprint[0][0], footprint[1][0])),
                                 (v_axis, (footprint[0][1], footprint[1][1]))):
        for m in range(3):
            comp = frame_axis[m]
            if abs(abs(comp) - 1.0) > 1e-6:
                continue
            a, b = (f0, f1) if comp > 0 else (-f1, -f0)
            new_lo, new_hi = max(lo[m], a), min(hi[m], b)
            if new_lo <= new_hi:
                lo[m], hi[m] = new_lo, new_hi
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


def bbox_of(vertices: Sequence[Point], faces: Sequence[Face],
            face_idx: Sequence[int]) -> Tuple[Point, Point]:
    """Axis-aligned box ``(min, max)`` over the vertices of ``face_idx`` in
    model space — what the sidecar stores as ``leaf_bbox`` (y-up, RAW model
    metres before any placement scaling). Empty -> two zero points."""
    ids = {i for k in face_idx for i in faces[k]}
    if not ids:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    pts = [vertices[i] for i in ids]
    lo = (min(p[0] for p in pts), min(p[1] for p in pts), min(p[2] for p in pts))
    hi = (max(p[0] for p in pts), max(p[1] for p in pts), max(p[2] for p in pts))
    return lo, hi


def detect_leaf(vertices: Sequence[Point], faces: Sequence[Face], *,
                tol: float = LEAF_TOL_M, cos_min: float = COPLANAR_COS,
                min_share: float = LEAF_MIN_SHARE) -> Optional[Dict]:
    """The whole § 6 heuristic, with E2's prism: ``{"faces", "bbox": (min,
    max), "plane", "share"}`` — or None, on THREE counts: the mesh has no
    planar cluster, its material thickness does not fall into a frame class
    and a leaf class (:func:`thickness_footprint`, so a glass door or a
    panel on its own), or the coplanar part of the prism covers less than
    ``min_share`` of the silhouette.
    The faces are :func:`prism_faces` through the plane's ``inner``
    footprint (:func:`thickness_footprint`) along its normal; ``bbox`` is
    :func:`bbox_of` those faces held to that footprint by
    :func:`clamp_bbox`; ``share`` is the
    summed area of the prism's faces that lie IN the leaf plane (facing its
    normal within the cosine, centre within ``tol``) over the area of the
    silhouette rectangle — the skin the cut found against the door's
    front. Below ``min_share`` there is no leaf worth cutting: the gate
    that keeps a bare frame (whose jambs alone would fill a prism) from
    becoming a leaf."""
    normals = face_normals(vertices, faces)
    plane = leaf_plane(vertices, faces, normals, tol=tol, cos_min=cos_min)
    if plane is None:
        return None
    chosen = prism_faces(vertices, faces, plane["inner"], plane["normal"],
                         normals=normals)
    if not chosen:
        return None
    n = plane["normal"]
    seed_area = 0.0
    for k in chosen:
        cu, cv, cd = _project(plane, _centroid(vertices, faces[k]))
        if _dot(normals[k], n) >= cos_min and abs(cd) <= tol:
            seed_area += _triangle_area(vertices, faces[k])
    (u0, v0), (u1, v1) = plane["bbox2d"]
    front = (u1 - u0) * (v1 - v0)
    share = seed_area / front if front > _EPS else 0.0
    if share < min_share:
        return None
    bbox = clamp_bbox(bbox_of(vertices, faces, chosen), plane["inner"], n)
    return {"faces": chosen, "bbox": bbox, "plane": plane, "share": share}
