"""Picture-area maths — chroma-key faces, components, plane fit, planar UVs.

STDLIB ONLY, AND THAT IS LOAD-BEARING. This module is imported by the
headless Blender refinement script through ``sys.path`` from Blender's own
bundled Python interpreter, which has neither this project's virtualenv nor
its dependencies. So: no numpy, no third-party packages, no ``app.*``
imports — ``math``, ``typing`` and ``collections`` are the whole budget.
Everything here is pure geometry over plain tuples; the caller (Blender)
supplies triangles, per-vertex UVs and a pixel sampler, and gets back plane,
frame, planar UVs and boundary edges.

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

The colour rule mirrors ``app/core/messaging_frame.py`` (the 8-bit chroma
key used for messaging frames), only expressed on 0..1 floats.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Callable, Dict, List, Sequence, Tuple

Point = Tuple[float, float, float]
Face = Tuple[int, int, int]
UV = Tuple[float, float]
SampleFn = Callable[[float, float], Tuple[float, float, float]]

# The 8-bit rule of messaging_frame.py on 0..1 floats: 100/255 ~ 0.39 is the
# "clearly bright" level, 30/255 ~ 0.12 the "clearly above/below" margin.
KEY_LEVEL = 0.39
KEY_MARGIN = 0.12

KINDS = ("picture", "glass")

_EPS = 1e-12


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
    return (a[0] / n, a[1] / n, a[2] / n)


def _edge_key(a: int, b: int) -> Tuple[int, int]:
    """Undirected edge key — a face's winding must not split a component."""
    return (a, b) if a < b else (b, a)


# ---------------------------------------------------------------------------
# 1. colour classification
# ---------------------------------------------------------------------------
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
    if kind not in KINDS:
        raise ValueError(f"unknown key colour kind {kind!r} (expected one of {KINDS})")
    r, g, b = float(rgb[0]), float(rgb[1]), float(rgb[2])
    if kind == "picture":
        return g > KEY_LEVEL and g > r + KEY_MARGIN and g > b + KEY_MARGIN
    return (
        r > KEY_LEVEL
        and b > KEY_LEVEL
        and g < r - KEY_MARGIN
        and g < b - KEY_MARGIN
    )


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
    merely grazes the panel count as panel.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown key colour kind {kind!r} (expected one of {KINDS})")
    flags: List[bool] = []
    for face in faces:
        hits = 0
        for u, v in face_samples(uvs, face):
            if is_key_colour(sample_rgb(u, v), kind):
                hits += 1
        flags.append(hits >= 2)
    return flags


# ---------------------------------------------------------------------------
# 2. connected components
# ---------------------------------------------------------------------------
def components(flags: Sequence[bool], faces: Sequence[Face]) -> List[List[int]]:
    """Group the flagged faces into patches connected over SHARED EDGES.

    Two faces are neighbours when they share two vertex indices, not merely
    one — a single shared corner (two panels touching at a frame joint) must
    not fuse two patches.

    Returns the face indices per patch, each list ascending, the patches
    sorted by face count descending, ties by smallest face index.
    """
    keyed = [n for n, f in enumerate(flags) if f]
    if not keyed:
        return []
    keyed_set = set(keyed)

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
                    if m not in seen and m in keyed_set:
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

    Fewer than three points, or a degenerate cloud, falls back to +z.
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
    smallest = min(range(3), key=lambda k: values[k])
    normal = _unit(vectors[smallest])
    if _norm(normal) <= _EPS:
        normal = (0.0, 0.0, 1.0)
    return centroid, _orient(normal)


def planar_frame(normal: Point) -> Tuple[Point, Point]:
    """A right-handed in-plane frame ``(u_axis, v_axis)`` for ``normal``.

    ``u`` starts from the world axis with the SMALLEST ``|dot(normal)|``
    (ties go to the earlier axis, x before y before z) — the axis most nearly
    parallel to the plane, so the projection can never collapse. That axis is
    projected into the plane and normalised. ``v = normal x u`` completes a
    right-handed triple.

    Finally, if ``v . (0, 1, 0) < 0`` BOTH axes are flipped: that keeps the
    triple right-handed while making ``v`` point roughly "up" in the world,
    so a picture hung on a wall is not stored upside down. (For a plane whose
    normal is world-up, ``v`` has no up-component and the frame is left as
    it is.)
    """
    n = _unit(normal)
    if _norm(n) <= _EPS:
        return (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)

    axes = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    best = min(range(3), key=lambda k: (abs(_dot(n, axes[k])), k))
    axis = axes[best]
    d = _dot(axis, n)
    u = _unit((axis[0] - d * n[0], axis[1] - d * n[1], axis[2] - d * n[2]))
    if _norm(u) <= _EPS:            # cannot happen for a unit normal, but be safe
        u = (1.0, 0.0, 0.0)
    v = _unit(_cross(n, u))
    if v[1] < -_EPS:
        u = (-u[0], -u[1], -u[2])
        v = (-v[0], -v[1], -v[2])
    return u, v


def planar_uvs(
    points: Sequence[Point],
    centroid: Point,
    frame: Tuple[Point, Point],
) -> Tuple[List[UV], Tuple[float, float]]:
    """Project ``points`` into ``frame`` and normalise to 0..1 over the bbox.

    Returns ``(uvs, size_m)`` where ``size_m`` is the bounding-box extent in
    METRES along the u and v axes — i.e. the physical width and height of the
    panel, which is what the picture's aspect ratio has to be fitted to.
    A degenerate extent maps to 0 instead of dividing by zero.
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

    A component is dropped when its summed 3D triangle area is below
    ``min_area_m2`` OR it has fewer than ``min_faces`` faces — a chroma
    speck on the frame is not a picture panel.

    Returns one dict per surviving component, sorted by area descending
    (ties by smallest face index)::

        {"kind": str,
         "faces": [face index, …],          # ascending
         "normal": (x, y, z),                # unit, oriented per fit_plane
         "centroid": (x, y, z),              # metres
         "size_m": (w, h),                   # bbox extent along u / v
         "uvs": {vertex index: (u, v)}}      # 0..1 over that bbox
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
