"""Detect basin and painted water in the heightgrid fixed-glTF frame.

Only xyz (props) permits priority-flood basins. Rooms use colour evidence,
so the four walls of a room cannot flood its otherwise dry floor.
"""

import colorsys
import heapq
import math
import sys
from collections import defaultdict, deque
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common

# heightgrid calls its entry point at import. Load its frame helpers while
# suppressing that call, then restore the shared runner entry point.
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "_water_heightgrid", Path(__file__).with_name("heightgrid.py")
)
_heightgrid = importlib.util.module_from_spec(_spec)
_main = _common.main
_common.main = lambda fn: None
try:
    _spec.loader.exec_module(_heightgrid)
finally:
    _common.main = _main
sys.path.remove(_SCRIPTS_DIR)
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def _srgb(v):
    """Convert linear colour to sRGB for the colour tests in spec § 4.1."""
    v = max(0.0, min(1.0, v))
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def _raster_mesh(objects, fix):
    """Build fixed-glTF triangles and UV/colour/material data for spec § 4.1.

    Keep face metadata in BVH triangle order so each top hit samples its face."""
    verts, tris, faces = ([], [], [])
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in objects:
        ev = obj.evaluated_get(depsgraph)
        mesh = ev.to_mesh()
        try:
            mesh.calc_loop_triangles()
            base = len(verts)
            verts.extend(
                (fix @ _heightgrid._gltf(ev.matrix_world @ v.co) for v in mesh.vertices)
            )
            uv = mesh.uv_layers.active
            attr = mesh.color_attributes.active_color
            for tri in mesh.loop_triangles:
                tris.append([base + i for i in tri.vertices])
                mat = (
                    mesh.materials[tri.material_index]
                    if tri.material_index < len(mesh.materials)
                    else None
                )
                uvs = [tuple(uv.data[i].uv) for i in tri.loops] if uv else None
                cols = (
                    [
                        tuple(attr.data[i if attr.domain == "CORNER" else vi].color)
                        for i, vi in zip(tri.loops, tri.vertices)
                    ]
                    if attr
                    else None
                )
                faces.append((mat, uvs, cols))
        finally:
            ev.to_mesh_clear()
    return (verts, tris, faces)


def _colour(mat, uvs, cols, weights, images):
    """Sample image, material or vertex colour in that order (spec § 4.1).

    Interpolate UVs/attributes with hit weights and cache pixels per image."""
    base = None
    texture = None
    if mat:
        base = mat.diffuse_color[:3]
        if mat.use_nodes and mat.node_tree:
            bsdf = next(
                (n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None
            )
            if bsdf:
                socket = bsdf.inputs.get("Base Color")
                base = socket.default_value[:3]
                if socket.is_linked:
                    node = socket.links[0].from_node
                    if node.type == "TEX_IMAGE":
                        texture = node.image
    if texture and uvs and texture.size[0] and texture.size[1]:
        key = texture.as_pointer()
        if key not in images:
            images[key] = (texture.size[0], texture.size[1], list(texture.pixels[:]))
        w, h, pixels = images[key]
        u, v = [sum((uvs[i][k] * weights[i] for i in range(3))) % 1 for k in (0, 1)]
        offset = 4 * (min(h - 1, int(v * h)) * w + min(w - 1, int(u * w)))
        return tuple((_srgb(c) for c in pixels[offset : offset + 3]))
    if base is not None:
        return tuple((_srgb(c) for c in base))
    if cols:
        return tuple(
            (_srgb(sum((cols[i][k] * weights[i] for i in range(3)))) for k in range(3))
        )
    return None


def _blue(rgb):
    """Apply the sRGB HSV water-colour thresholds from spec § 4.1."""
    if rgb is None:
        return False
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    return 170 <= h * 360 <= 250 and s >= 0.2 and (v >= 0.2)


def _neighbors(i, cols, rows):
    """Yield four-connected raster neighbours for spec §§ 4.2–4.3."""
    x, z = (i % cols, i // cols)
    if x:
        yield (i - 1)
    if x + 1 < cols:
        yield (i + 1)
    if z:
        yield (i - cols)
    if z + 1 < rows:
        yield (i + cols)


def _flood(heights, cols, rows):
    """Priority-fill depressions from border/no-hit drains (spec § 4.2).

    No-hit drains use box bottom; shape basins are considered only for props."""
    filled = list(heights)
    seen = set()
    heap = []
    for i, h in enumerate(heights):
        if h is None or i % cols in (0, cols - 1) or i // cols in (0, rows - 1):
            seen.add(i)
            filled[i] = h if h is not None else 0.0
            heapq.heappush(heap, (filled[i], i))
    while heap:
        level, i = heapq.heappop(heap)
        for j in _neighbors(i, cols, rows):
            if j not in seen:
                seen.add(j)
                filled[j] = max(level, heights[j] if heights[j] is not None else 0.0)
                heapq.heappush(heap, (filled[j], j))
    return filled


def _components(mask, cols, rows):
    """Split a mask into four-connected components (spec §§ 4.2–4.3)."""
    unseen = set(mask)
    while unseen:
        root = unseen.pop()
        component = {root}
        queue = deque([root])
        while queue:
            for j in _neighbors(queue.popleft(), cols, rows):
                if j in unseen:
                    unseen.remove(j)
                    component.add(j)
                    queue.append(j)
        yield component


def _percentile(values, p):
    """Interpolate sorted heights for rim/flatness tests (spec § 4.3)."""
    values = sorted(values)
    pos = (len(values) - 1) * p
    a = int(pos)
    return values[a] + (values[min(a + 1, len(values) - 1)] - values[a]) * (pos - a)


def _simplify(points, tolerance):
    """Simplify an outline with Douglas–Peucker tolerance (spec § 4.5)."""
    if len(points) <= 2:
        return points
    a, b = (points[0], points[-1])
    dx, dz = (b[0] - a[0], b[1] - a[1])
    denom = dx * dx + dz * dz
    best, index = (-1.0, 0)
    for i, p in enumerate(points[1:-1], 1):
        t = (
            max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / denom))
            if denom
            else 0.0
        )
        dist = math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dz)
        if dist > best:
            best, index = (dist, i)
    if best <= tolerance:
        return [a, b]
    return _simplify(points[: index + 1], tolerance)[:-1] + _simplify(
        points[index:], tolerance
    )


def _area(ring):
    """Compute signed XZ ring area for outline/hole winding (spec § 4.5)."""
    return (
        sum((ring[i - 1][0] * p[1] - p[0] * ring[i - 1][1] for i, p in enumerate(ring)))
        / 2
    )


def _outlines(cells, cols, rows, lo, step):
    """Trace marching-squares rings and simplify at one step (spec § 4.5).

    Use iso 0.5 on a zero-padded mask; ambiguous diagonals stay separate
    for four-connected foreground. Integer half-grid endpoints stitch exactly.
    Return a counter-clockwise outer ring and clockwise holes, or None."""
    graph = defaultdict(list)
    table = {
        1: [(3, 0)],
        2: [(0, 1)],
        3: [(3, 1)],
        4: [(1, 2)],
        5: [(3, 0), (1, 2)],
        6: [(0, 2)],
        7: [(3, 2)],
        8: [(2, 3)],
        9: [(2, 0)],
        10: [(0, 1), (2, 3)],
        11: [(2, 1)],
        12: [(1, 3)],
        13: [(1, 0)],
        14: [(0, 3)],
    }

    def on(x, z):
        """Read the zero-padded node mask for marching squares (spec § 4.5)."""
        return 0 <= x < cols and 0 <= z < rows and (z * cols + x in cells)

    min_x, max_x = (min((i % cols for i in cells)), max((i % cols for i in cells)))
    min_z, max_z = (min((i // cols for i in cells)), max((i // cols for i in cells)))
    for z in range(min_z - 1, max_z + 1):
        for x in range(min_x - 1, max_x + 1):
            code = sum(
                (
                    1 << k
                    for k, (dx, dz) in enumerate(((0, 0), (1, 0), (1, 1), (0, 1)))
                    if on(x + dx, z + dz)
                )
            )
            edges = [
                (2 * x + 1, 2 * z),
                (2 * x + 2, 2 * z + 1),
                (2 * x + 1, 2 * z + 2),
                (2 * x, 2 * z + 1),
            ]
            for a, b in table.get(code, []):
                a, b = (edges[a], edges[b])
                graph[a].append(b)
                graph[b].append(a)
    rings = []
    while graph:
        start = next(iter(graph))
        ring, current, previous = ([], start, None)
        while True:
            ring.append([lo[0] + current[0] * step / 2, lo[2] + current[1] * step / 2])
            nxt = next((p for p in graph[current] if p != previous), start)
            graph[current].remove(nxt)
            if not graph[current]:
                del graph[current]
            graph[nxt].remove(current)
            if not graph[nxt]:
                del graph[nxt]
            previous, current = (current, nxt)
            if current == start:
                break
        # Split the closed ring at its farthest vertex for stable RDP.
        split = max(range(1, len(ring)), key=lambda i: math.dist(ring[0], ring[i]))
        simple = (
            _simplify(ring[: split + 1], step)[:-1]
            + _simplify(ring[split:] + [ring[0]], step)[:-1]
        )
        if len(simple) >= 3:
            rings.append(simple)
    if not rings:
        return None
    rings.sort(key=lambda r: abs(_area(r)), reverse=True)
    outer = rings[0]
    if _area(outer) < 0:
        outer.reverse()
    holes = rings[1:]
    for h in holes:
        if _area(h) > 0:
            h.reverse()
    return (outer, holes)


def _regions(
    heights, normals, blue, cols, rows, lo, step, scale, measure, footprint_area=None
):
    """Classify shape/colour basins and painted water (spec §§ 4.2–4.5).

    Shape flooding is props-only. Colour evidence also works for dioramas.
    Apply area/depth/flatness thresholds, confidence and default looks; split
    disconnected final masks before generating their outlines."""
    result, used = ([], set())
    cell_area = (step * scale) ** 2
    if footprint_area is None:
        footprint_area = (cols - 1) * (rows - 1) * cell_area

    def add(cells, level, kind, confidence, look):
        """Split the final wet mask before outlining (spec §§ 4.2–4.5)."""
        if not cells:
            return
        for part in _components(cells, cols, rows):
            add_part(part, level, kind, confidence, look)

    def add_part(cells, level, kind, confidence, look):
        """Emit one outlined region with confidence/defaults (spec §§ 4.4–4.5)."""
        rings = _outlines(cells, cols, rows, lo, step)
        if not rings:
            return
        bed = min((heights[i] for i in cells))
        defaults = {
            "pool": ("#3aa7c4", 0.75),
            "bath": ("#bfe3ea", 0.85),
            "lake": ("#2d6a86", 0.5),
        }
        tint, clarity = defaults[look]
        result.append(
            dict(
                id=f"r{len(result) + 1}",
                kind=kind,
                confidence=confidence,
                enabled=confidence == "sure",
                outline=rings[0],
                holes=rings[1],
                level=level,
                bed=bed,
                area_m2=len(cells) * cell_area,
                depth_m=(level - bed) * scale,
                level_user=False,
                look=dict(preset=look, tint=tint, clarity=clarity),
            )
        )
        used.update(cells)

    if measure == "xyz":
        filled = _flood(heights, cols, rows)
        mask = {
            i
            for i, h in enumerate(heights)
            if h is not None and (filled[i] - h) * scale >= 0.03
        }
        for comp in _components(mask, cols, rows):
            coloured = sum((blue[i] for i in comp)) / len(comp)
            if len(comp) * cell_area < 0.05 or (
                len(comp) * cell_area > 0.6 * footprint_area and coloured < 0.5
            ):
                continue
            spill = min((filled[i] for i in comp))
            depth = max((filled[i] - heights[i] for i in comp))
            level = spill - min(0.08 / scale, 0.2 * depth)
            add(
                {i for i in comp if heights[i] < level},
                level,
                "basin",
                "sure" if coloured >= 0.5 else "candidate",
                "pool" if coloured >= 0.5 else "bath",
            )
    mask = {i for i, b in enumerate(blue) if b and i not in used}
    for comp in _components(mask, cols, rows):
        area = len(comp) * cell_area
        if area < 0.05:
            continue
        rim = {
            j
            for i in comp
            for j in _neighbors(i, cols, rows)
            if j not in comp and heights[j] is not None
        }
        values = [heights[i] for i in comp]
        median = _percentile(values, 0.5)
        r = _percentile([heights[j] for j in rim], 0.1) if rim else median
        if (r - median) * scale >= 0.1:
            depth = max((r - h for h in values))
            level = r - min(0.08 / scale, 0.2 * depth)
            add({i for i in comp if heights[i] < level}, level, "basin", "sure", "pool")
        elif (
            sum((normals[i] >= 0.97 for i in comp)) / len(comp) >= 0.8
            and (_percentile(values, 0.9) - _percentile(values, 0.1)) * scale <= 0.03
            and (area >= 0.25)
        ):
            add(comp, median + 0.01 / scale, "painted", "candidate", "lake")
    return result


def _preview(path, colours, regions, cols, rows, lo, step):
    """Write the raster PNG with cyan/orange region outlines (spec § 4.6)."""
    pixels = []
    for colour in colours:
        pixels.extend([*(colour or (0.15, 0.15, 0.15)), 1.0])
    for region in regions:
        colour = (
            (0.0, 1.0, 1.0, 1.0)
            if region["confidence"] == "sure"
            else (1.0, 0.5, 0.0, 1.0)
        )
        for ring in [region["outline"], *region["holes"]]:
            for i, a in enumerate(ring):
                b = ring[i - 1]
                length = max(1, int(math.dist(a, b) / step * 2))
                for n in range(length + 1):
                    x, z = [
                        int(
                            round((a[k] + (b[k] - a[k]) * n / length - lo[axis]) / step)
                        )
                        for k, axis in ((0, 0), (1, 2))
                    ]
                    if 0 <= x < cols and 0 <= z < rows:
                        offset = 4 * (z * cols + x)
                        pixels[offset : offset + 4] = colour
    img = bpy.data.images.new("Water detection preview", width=cols, height=rows)
    img.pixels[:] = pixels
    img.filepath_raw = str(path)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def waterdetect(args):
    """Run spec § 4 detection in the shared fixed-glTF frame.

    Scale the world step and enforce the cell cap (§ 4); rasterize top hits
    and colours (§ 4.1), classify/outline regions (§§ 4.2–4.5), optionally
    write the preview (§ 4.6), and return runner metadata and output paths."""
    p = args.get("params") or {}
    rot = p.get("rotation") or {}
    measure = p.get("measure", "xz")
    _common.reset_scene()
    _common.import_model(args["inputs"]["model"])
    objects = _heightgrid._mesh_objects()
    if not objects:
        raise RuntimeError("no mesh objects")
    fix = _heightgrid._fix_matrix(rot, False)
    lo, hi = _heightgrid._three_box(objects, fix)
    slo, shi = _heightgrid._three_box(objects, _heightgrid._fix_matrix(rot, True))
    ext = [shi[k] - slo[k] for k in range(3)]
    extent = max(ext) if measure == "xyz" else max(ext[0], ext[2])
    target = float(p.get("target_m") or 0)
    scale = target / (extent or 1.0) if target > 0 else 1.0
    step = float(p.get("step") or 0.02) / scale
    max_cells = max(4, int(p.get("max_cells") or 250000))
    while True:
        cols, rows = [int(math.ceil((hi[k] - lo[k]) / step)) + 1 for k in (0, 2)]
        if cols * rows <= max_cells:
            break
        step *= 2
    verts, tris, faces = _raster_mesh(objects, fix)
    bvh = BVHTree.FromPolygons(verts, tris, all_triangles=True)
    heights, normals, colours, blue, images = ([], [], [], [], {})
    for j in range(rows):
        for i in range(cols):
            x = _heightgrid._inside(lo[0] + i * step, lo[0], hi[0])
            z = _heightgrid._inside(lo[2] + j * step, lo[2], hi[2])
            hit, normal, index, _ = bvh.ray_cast(
                Vector((x, hi[1] + 1, z)), Vector((0, -1, 0))
            )
            colour = None
            if hit is not None:
                a, b, c = [verts[k] for k in tris[index]]
                # Barycentric hit coordinates in the triangle plane.
                v0, v1, v2 = (b - a, c - a, hit - a)
                d00, d01, d11 = (v0.dot(v0), v0.dot(v1), v1.dot(v1))
                denom = d00 * d11 - d01 * d01
                u = (d11 * v2.dot(v0) - d01 * v2.dot(v1)) / denom if denom else 0
                v = (d00 * v2.dot(v1) - d01 * v2.dot(v0)) / denom if denom else 0
                colour = _colour(*faces[index], (1 - u - v, u, v), images)
            heights.append(hit.y - lo[1] if hit is not None else None)
            normals.append(normal.y if normal is not None else 0)
            colours.append(colour)
            blue.append(_blue(colour))
    regions = _regions(
        heights,
        normals,
        blue,
        cols,
        rows,
        lo,
        step,
        scale,
        measure,
        (hi[0] - lo[0]) * (hi[2] - lo[2]) * scale * scale,
    )
    outputs = {}
    if p.get("preview"):
        preview = Path(args["out_dir"]) / "water-preview.png"
        _preview(preview, colours, regions, cols, rows, lo, step)
        outputs["preview"] = preview.name
    return (
        dict(
            step=step,
            step_world=round(step * scale, 6),
            box_min=lo,
            box_max=hi,
            extent_snapped=ext,
            regions=regions,
        ),
        outputs,
    )


_common.main(waterdetect)
