"""Closed roof slabs over supplied hull footprints, without storage or Blender."""
import math
from typing import Any, Dict, List, Optional, Tuple

from app.core.hull_mesh import Part, PartBuilder, _normal, offset_ring, rng
from app.core.hull_walls import wall_offsets
from app.core.scene_recipe import _point_in_polygon, _ring_ccw


def _rotate(point, angle):
    """Rotate a footprint point counterclockwise in the x/z plane."""
    cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    x, z = point
    return [x * cosine - z * sine, x * sine + z * cosine]


def orthogonal_frame(outline: List[List[float]]) -> Optional[float]:
    """Return the longest edge's frame if all edges align within 0.5 degrees."""
    edges = [(math.dist(first, second), math.degrees(math.atan2(
        second[1] - first[1], second[0] - first[0])))
        for first, second in zip(outline, outline[1:] + outline[:1])
        if math.dist(first, second) > 1e-8]
    if not edges:
        return None
    angle = max(edges, key=lambda edge: edge[0])[1] % 180
    if any(abs((direction - angle + 45) % 90 - 45) > 0.5 + 1e-8
           for _, direction in edges):
        return None
    return angle


def _merge_cells(cells, swap):
    """Merge equal contiguous runs on successive grid rows."""
    rows = {}
    for x, z in cells:
        column, row = (z, x) if swap else (x, z)
        rows.setdefault(row, []).append(column)
    active, rectangles = {}, []
    previous = None
    for row in sorted(rows):
        if previous is None or row != previous + 1:
            rectangles.extend(active.values())
            active = {}
        columns = sorted(rows[row])
        runs = []
        for column in columns:
            if runs and runs[-1][1] == column:
                runs[-1] = (runs[-1][0], column + 1)
            else:
                runs.append((column, column + 1))
        following = {}
        for run in runs:
            rectangle = active.pop(run, [run[0], run[1], row, row])
            rectangle[3] = row + 1
            following[run] = rectangle
        rectangles.extend(active.values())
        active, previous = following, row
    rectangles.extend(active.values())
    return [[entry[2], entry[3], entry[0], entry[1]] if swap else entry
            for entry in rectangles]


def decompose(outline: List[List[float]], covered: Optional[List[List[float]]],
              angle_deg: float) -> List[Dict[str, Any]]:
    """Tile exposed cells with rectangles; covered_sides use x_min/x_max/z_min/z_max.

    Side names refer to the rectangle's local frame. Ties prefer x runs.
    Coordinates are clustered at 1e-6 m to suppress rotation roundoff.
    """
    local = [_rotate(point, -angle_deg) for point in outline]
    above = [_rotate(point, -angle_deg) for point in (covered or [])]
    xs, zs = [sorted({round(point[axis], 6) for point in local + above})
              for axis in (0, 1)]
    exposed, occupied = set(), set()
    for i in range(len(xs) - 1):
        for j in range(len(zs) - 1):
            x, z = (xs[i] + xs[i + 1]) / 2, (zs[j] + zs[j + 1]) / 2
            if above and _point_in_polygon(x, z, above):
                occupied.add((i, j))
            elif _point_in_polygon(x, z, local):
                exposed.add((i, j))
    candidates = [_merge_cells(exposed, swap) for swap in (False, True)]
    rectangles = min(candidates, key=len)
    result = []
    for first, last, bottom, top in sorted(rectangles):
        sides = []
        for name, neighbors in (
            ("x_min", [(first - 1, j) for j in range(bottom, top)]),
            ("x_max", [(last, j) for j in range(bottom, top)]),
            ("z_min", [(i, bottom - 1) for i in range(first, last)]),
            ("z_max", [(i, top) for i in range(first, last)]),
        ):
            if any(neighbor in occupied for neighbor in neighbors):
                sides.append(name)
        result.append({"rect": {
            "center": _rotate([(xs[first] + xs[last]) / 2, (zs[bottom] + zs[top]) / 2], angle_deg),
            "length": xs[last] - xs[first], "depth": zs[top] - zs[bottom],
            "angle_deg": angle_deg}, "covered_sides": sides})
    return result


def _builder(tag, material, uv_sizes):
    """Apply material UV scale and the shared protrusion convention."""
    return PartBuilder(tag, material, uv_size_m=uv_sizes.get(material, 2.0),
                       protrudes=tag == "roof")


def _slab(builder, points, thickness=0.15):
    """Extrude a planar upward polygon inward by its physical thickness."""
    if _normal(points)[1] < 0:
        points = points[::-1]
    normal = _normal(points)
    magnitude = math.sqrt(sum(value * value for value in normal))
    delta = [value * thickness / magnitude for value in normal]
    bottom = [[point[axis] - delta[axis] for axis in range(3)] for point in points]
    builder.poly(points)
    builder.poly(bottom[::-1])
    for i in range(len(points)):
        following = (i + 1) % len(points)
        builder.poly([points[i], bottom[i], bottom[following], points[following]])


def _triangles(outline):
    """Ear-clip simple polygons so concave caps never rely on renderer fans."""
    ring = list(outline if _ring_ccw(outline) else outline[::-1])
    indices = list(range(len(ring)))
    triangles = []
    while len(indices) > 3:
        for position, index in enumerate(indices):
            before, after = indices[position - 1], indices[(position + 1) % len(indices)]
            triangle = [ring[before], ring[index], ring[after]]
            if _cross(*triangle) <= 1e-10:
                continue
            if any(all(_cross(triangle[i], triangle[(i + 1) % 3], ring[other]) >= -1e-10
                       for i in range(3)) for other in indices if other not in (before, index, after)):
                continue
            triangles.append(triangle)
            indices.pop(position)
            break
        else:
            raise ValueError("Cannot triangulate roof outline")
    triangles.append([ring[index] for index in indices])
    return triangles


def _cross(first, second, third):
    """Return twice the signed x/z triangle area."""
    return ((second[0] - first[0]) * (third[1] - first[1])
            - (second[1] - first[1]) * (third[0] - first[0]))


def _parapet(outline, y, style, uv_sizes):
    """Build closed parapet blocks along supplied cap edges."""
    parts = []
    thickness = style["wall_thickness_m"]
    for first, second in zip(outline, outline[1:] + outline[:1]):
        builder = _builder("parapet", "wall", uv_sizes)
        center = [(first[0] + second[0]) / 2, y + 0.5, (first[1] + second[1]) / 2]
        yaw = -math.atan2(second[1] - first[1], second[0] - first[0])
        builder.box(center, [math.dist(first, second) + thickness, 1.0, thickness], yaw)
        parts.append(builder.part())
        if style.get("parapet_cap"):
            cap = _builder("parapet_cap", "trim", uv_sizes)
            cap.box([center[0], y+1.025, center[2]],
                    [math.dist(first, second)+thickness+.06, .05, thickness+.06], yaw)
            parts.append(cap.part())
    return parts


def _flat(outline, level, base, style, overhang, uv_sizes, info, parts, *, expanded=False):
    """Emit the flat cap and report whether this top actually has a parapet."""
    outer = wall_offsets(style, level)[1]
    ring = outline if expanded else offset_ring(outline, _ring_ccw(outline), outer + overhang)
    # Individual triangular prisms are closed even for concave caps.
    for triangle in _triangles(ring):
        builder = _builder("roof", "roof", uv_sizes)
        _slab(builder, [[x, base + 0.25, z] for x, z in triangle], 0.25)
        parts.append(builder.part())
    parapet = bool(style["roof"].get("parapet", False))
    info["flat_tops"].append({"level": level, "outline": ring, "y": base + 0.25,
                              "parapet": parapet})
    if parapet:
        wall_ring = offset_ring(outline, _ring_ccw(outline), (0 if expanded else outer + overhang) - style["wall_thickness_m"] / 2)
        parts.extend(_parapet(wall_ring, base + 0.25, style, uv_sizes))


def _at(rect, x, y, z):
    """Transform rectangle-local coordinates into the scene frame."""
    point = _rotate([x, z], rect["angle_deg"])
    return [rect["center"][0] + point[0], y, rect["center"][1] + point[1]]


def _wing_axes(rect, covered_sides, form):
    """Run the ridge along the longer axis, or parallel to a covered shed side."""
    result = dict(rect)
    side = covered_sides[0] if covered_sides else "z_max"
    turn = (side.startswith("x") if form == "shed" and covered_sides
            else rect["depth"] > rect["length"])
    if turn:
        result.update(length=rect["depth"], depth=rect["length"],
                      angle_deg=rect["angle_deg"] + 90)
        side = {"x_min": "z_max", "x_max": "z_min",
                "z_min": "x_min", "z_max": "x_max"}[side]
    return result, -1 if side == "z_min" else 1


def _clip_polygon(points, limits):
    """Clip a 3D polygon to four local x/z half-planes, interpolating y."""
    for axis, boundary, sign in ((0, limits[0], 1), (0, limits[1], -1),
                                  (2, limits[2], 1), (2, limits[3], -1)):
        output = []
        for first, second in zip(points, points[1:] + points[:1]):
            a, b = sign*(first[axis]-boundary), sign*(second[axis]-boundary)
            if a >= -1e-10:
                output.append(first)
            if (a < 0) != (b < 0):
                fraction = a/(a-b)
                output.append([first[k]+fraction*(second[k]-first[k]) for k in range(3)])
        points = output
    return points


def roof_top_y(wing: Dict, x: float, z: float, style: Dict) -> Optional[float]:
    """Return the wing top at scene x/z, or None outside its slab footprint."""
    if wing["form"] == "tent":
        if not _point_in_polygon(x, z, wing["outline"]):
            from app.core.world_geometry import polygon_distance
            if polygon_distance(x, z, wing["outline"]) > 1e-4:
                return None
        heights = []
        for plane in wing["planes"]:
            normal = _normal(plane)
            first = plane[0]
            heights.append(first[1] - (normal[0]*(x-first[0])+normal[2]*(z-first[2]))/normal[1])
        return min(heights)
    rect = wing["rect"]
    x, z = _rotate([x-rect["center"][0], z-rect["center"][1]], -rect["angle_deg"])
    low_x, high_x, low_z, high_z = wing["limits"]
    if not (low_x-1e-4 <= x <= high_x+1e-4 and low_z-1e-4 <= z <= high_z+1e-4):
        return None
    return _roof_height(wing, x, z, style, wing["pitch_deg"])


def _detail_samples(wing, vertices):
    """Return conservative footprint intersections, including interior roof ridges."""
    rect = wing["rect"]
    local = [_rotate([p[0]-rect["center"][0],p[2]-rect["center"][1]], -rect["angle_deg"])
             for p in vertices]
    # A bounding rectangle is conservative for rotated corner/log pieces.
    bounds = [min(p[0] for p in local), max(p[0] for p in local),
              min(p[1] for p in local), max(p[1] for p in local)]
    if wing["form"] == "tent":
        footprint = [_rotate([x-rect["center"][0],z-rect["center"][1]], -rect["angle_deg"])
                     for x,z in wing["outline"]]
        polygon = [[x,0,z] for x,z in footprint]
    else:
        a,b,c,d = wing["limits"]
        polygon = [[a,0,c],[b,0,c],[b,0,d],[a,0,d]]
    samples = _clip_polygon(polygon, bounds)
    area = abs(sum(a[0]*b[2]-b[0]*a[2] for a,b in zip(samples,samples[1:]+samples[:1]))) / 2
    if area <= 1e-8:
        return []
    # Roof maxima can lie on an interior ridge or tent apex.
    if samples:
        for axis in (0, 2):
            for first, second in zip(samples[:], samples[1:]+samples[:1]):
                if first[axis]*second[axis] < 0:
                    fraction = first[axis]/(first[axis]-second[axis])
                    samples.append([first[k]+fraction*(second[k]-first[k]) for k in range(3)])
        if wing["form"] == "tent":
            # Fan-plane intersections may meet the detail between its corners.
            for corner in footprint:
                for first, second in zip(samples[:], samples[1:]+samples[:1]):
                    a = corner[0]*first[2]-corner[1]*first[0]
                    b = corner[0]*second[2]-corner[1]*second[0]
                    if a*b < 0:
                        fraction = a/(a-b)
                        samples.append([first[k]+fraction*(second[k]-first[k]) for k in range(3)])
        if bounds[0] <= 0 <= bounds[1] and bounds[2] <= 0 <= bounds[3]:
            samples.append([0,0,0])
    return [_at(rect, point[0], 0, point[2]) for point in samples]


def detail_breaks(roof_info, level, edge, depths):
    """Return facade s coordinates where relevant wing footprints cross a strip.

    Include both depth faces and boundary vertices within the depth range.
    Callers emit independent cells at these breaks before vertical clipping.
    """
    from app.core.hull_walls import _axes
    tangent, normal = _axes(edge)
    back, front = sorted(depths)
    breaks = set()
    for wing in (roof_info or {}).get("wings", []):
        if wing["level"] > level:
            continue
        if wing["form"] == "tent":
            ring = wing["outline"]
        else:
            a,b,c,d = wing["limits"]
            ring = [[_at(wing["rect"],x,0,z)[k] for k in (0,2)]
                    for x,z in ((a,c),(b,c),(b,d),(a,d))]
        local = [[sum((point[k]-edge["a"][k])*axis[k] for k in (0,1))
                  for axis in (tangent,normal)] for point in ring]
        for first, second in zip(local,local[1:]+local[:1]):
            if back-1e-8 <= first[1] <= front+1e-8:
                breaks.add(first[0])
            delta = second[1]-first[1]
            if abs(delta) < 1e-10:
                continue
            for depth in (back,front):
                fraction = (depth-first[1])/delta
                if -1e-8 <= fraction <= 1+1e-8:
                    breaks.add(first[0]+fraction*(second[0]-first[0]))
    return sorted(breaks)


def clip_detail(part, level, roof_info, style, *, diagonal=False):
    """Shorten facade details conservatively using one shared clearance rule.

    The vertical affine map preserves closed planar solids, including log sections.
    Footprint intersections include wing corners and crossing edges, so long bands
    with endpoints outside a wing still receive clearance.
    """
    low = min(p[1] for p in part["vertices"])
    high = max(p[1] for p in part["vertices"])
    bottom, top = low, high
    for wing in (roof_info or {}).get("wings", []):
        if wing["level"] > level:
            continue
        heights = [roof_top_y(wing, point[0], point[2], style)
                   for point in _detail_samples(wing, part["vertices"])]
        heights = [y for y in heights if y is not None]
        if not heights:
            continue
        if wing["level"] == level:
            top = min(top, min(heights)-.02)
        else:
            bottom = max(bottom, max(heights)+.02)
    if top-bottom <= 1e-5 or (diagonal and (bottom > low+1e-6 or top < high-1e-6)):
        return None
    if bottom != low or top != high:
        for point in part["vertices"]:
            point[1] = round(bottom+(point[1]-low)*(top-bottom)/(high-low), 4)
    part["detail_level"] = level
    return part


def _pitched(rect, sides, form, number, base, pitch, overhang, style, uv_sizes, parts):
    """Use roof_model's wall-span pitch and shortened hip-ridge formulas."""
    original_angle = rect["angle_deg"]
    rect, high = _wing_axes(rect, sides, form)
    outer = wall_offsets(style, number)[1]
    half_length = rect["length"] / 2 + outer
    half_span = rect["depth"] / 2 + outer
    slope = math.tan(math.radians(pitch))
    end, edge = half_length + overhang, half_span + overhang
    # Covered limits use the upper shell's inner face; the pitch datum stays fixed.
    limits = [-end, end, -edge, edge]
    for side in sides:
        axis, direction = side.split("_")
        local_axis = _rotate([1, 0] if axis == "x" else [0, 1],
                             - (rect["angle_deg"] - original_angle))
        index = 0 if abs(local_axis[0]) > .5 else 2
        sign = (1 if direction == "max" else -1) * (local_axis[0] if index == 0 else local_axis[1])
        half = rect["length" if index == 0 else "depth"] / 2
        limits[index + (1 if sign > 0 else 0)] = math.copysign(
            half - wall_offsets(style, number + 1)[0] - .01, sign)
    ridge_y = base + half_span * slope
    ridge_half = half_length
    surfaces = []
    if form == "shed":
        ridge_y = base + 2 * half_span * slope
        heights = {side: base + (half_span + high * side * edge) * slope for side in (-1, 1)}
        surfaces = [[[-end, heights[-1], -edge], [end, heights[-1], -edge],
                     [end, heights[1], edge], [-end, heights[1], edge]]]
        ridge = [_at(rect, x, ridge_y, high * half_span) for x in (-half_length, half_length)]
    else:
        ridge_half = max(0.0, half_length - half_span) if form == "hip" else end
        low_y = base - overhang * slope
        for side in (-1, 1):
            surfaces.append([[-end, low_y, side * edge], [end, low_y, side * edge],
                             [ridge_half, ridge_y, 0], [-ridge_half, ridge_y, 0]])
        if form == "hip":
            for side in (-1, 1):
                surfaces.append([[side * end, low_y, -edge], [side * end, low_y, edge],
                                 [side * ridge_half, ridge_y, 0]])
        ridge = [_at(rect, x, ridge_y, 0) for x in (-ridge_half, ridge_half)]
    original_ridge_y = ridge_y
    if sides:
        ridge = [[*point] for point in ridge]
        for point in ridge:
            local = _rotate([point[0]-rect["center"][0], point[2]-rect["center"][1]], -rect["angle_deg"])
            x = max(limits[0], min(limits[1], local[0]))
            z = max(limits[2], min(limits[3], local[1]))
            y = base + (half_span + high*z)*slope if form == "shed" else ridge_y
            point[:] = _at(rect, x, y, z)
        ridge_y = max(point[1] for point in ridge)
    first_part = len(parts)
    for surface in surfaces:
        surface = _clip_polygon(surface, limits)
        # A square hip collapses both ridge points to one apex.
        points = []
        for x, y, z in surface:
            point = _at(rect, x, y, z)
            if point not in points:
                points.append(point)
        if len(points) < 3:
            continue
        builder = _builder("roof", "roof", uv_sizes)
        _slab(builder, points)
        parts.append(builder.part())
    ridge_y = original_ridge_y
    if form == "gable":
        material = "wall_ground" if number == 0 and style.get("materials", {}).get("wall_ground") else "wall"
        for side in (-1, 1):
            builder = _builder("gable", material, uv_sizes)
            points = [_at(rect, max(limits[0], min(limits[1], side * half_length)), base, z) for z in (-half_span, half_span)]
            points.append(_at(rect, max(limits[0], min(limits[1], side * half_length)), ridge_y, 0))
            outward = _rotate([side, 0], rect["angle_deg"])
            normal = _normal(points)
            if normal[0] * outward[0] + normal[2] * outward[1] < 0:
                points.reverse()
            local_points = []
            for point in points:
                x, z = _rotate([point[0]-rect["center"][0], point[2]-rect["center"][1]], -rect["angle_deg"])
                local_points.append([x, point[1], z])
            builder.poly([_at(rect, *point) for point in _clip_polygon(local_points, limits)])
            parts.append(builder.part())
    if form == "shed":
        material = "wall_ground" if number == 0 and style.get("materials", {}).get("wall_ground") else "wall"
        for side in (-1, 1):
            builder = _builder("gable", material, uv_sizes)
            points = [_at(rect, max(limits[0], min(limits[1], side * half_length)), base, -high * half_span),
                      _at(rect, max(limits[0], min(limits[1], side * half_length)), base, high * half_span),
                      _at(rect, max(limits[0], min(limits[1], side * half_length)), ridge_y, high * half_span)]
            normal = _normal(points)
            outward = _rotate([side, 0], rect["angle_deg"])
            if normal[0] * outward[0] + normal[2] * outward[1] < 0:
                points.reverse()
            local_points = []
            for point in points:
                x, z = _rotate([point[0]-rect["center"][0], point[2]-rect["center"][1]], -rect["angle_deg"])
                local_points.append([x, point[1], z])
            builder.poly([_at(rect, *point) for point in _clip_polygon(local_points, limits)])
            parts.append(builder.part())
        if not sides:
            builder = _builder("gable", material, uv_sizes)
            points = [_at(rect, x, y, high * half_span) for x, y in (
                (-half_length, base), (half_length, base),
                (half_length, ridge_y), (-half_length, ridge_y))]
            outward = _rotate([0, high], rect["angle_deg"])
            normal = _normal(points)
            if normal[0] * outward[0] + normal[2] * outward[1] < 0:
                points.reverse()
            local_points = []
            for point in points:
                x, z = _rotate([point[0]-rect["center"][0], point[2]-rect["center"][1]], -rect["angle_deg"])
                local_points.append([x, point[1], z])
            builder.poly([_at(rect, *point) for point in _clip_polygon(local_points, limits)])
            parts.append(builder.part())
    if sides:
        ridge_y = max(point[1] for point in ridge)
        for part in parts[first_part:]:
            if part["tag"] != "roof":
                continue
            normal = _normal([part["vertices"][i] for i in part["faces"][0]])
            for point in part["vertices"]:
                x, z = _rotate([point[0]-rect["center"][0], point[2]-rect["center"][1]], -rect["angle_deg"])
                moved = _at(rect, max(limits[0], min(limits[1], x)), point[1],
                            max(limits[2], min(limits[3], z)))
                # Keep both parallel slab planes when trimming the extrusion.
                moved[1] -= (normal[0]*(moved[0]-point[0])+normal[2]*(moved[2]-point[2]))/normal[1]
                point[:] = [round(v, 4) for v in moved]
    for part in parts[first_part:]:
        part["roof_level"] = number
    return {"rect": rect, "level": number, "form": form, "eaves_y": base,
            "ridge_y": ridge_y, "ridge": ridge, "pitch_deg": pitch,
            "overhang_m": overhang, "limits": limits, "high": high}


def _centroid(outline):
    """Return the area centroid rather than the vertex average."""
    area = sum(first[0] * second[1] - second[0] * first[1]
               for first, second in zip(outline, outline[1:] + outline[:1]))
    return [sum((first[axis] + second[axis]) * (first[0] * second[1] - second[0] * first[1])
                for first, second in zip(outline, outline[1:] + outline[:1])) / (3 * area)
            for axis in (0, 1)]


def _convex(outline):
    """Accept either winding and ignore straight boundary vertices."""
    turns = [_cross(outline[i - 1], point, outline[(i + 1) % len(outline)])
             for i, point in enumerate(outline)]
    return all(turn >= -1e-8 for turn in turns) or all(turn <= 1e-8 for turn in turns)


def _tent(level, base, pitch, overhang, style, uv_sizes, parts):
    """Put the apex over the area centroid and measure rise from outer walls."""
    outline = level["outline"]
    number = level["level"]
    outer = wall_offsets(style, number)[1]
    wall = offset_ring(outline, level["ccw"], outer)
    ring = offset_ring(outline, level["ccw"], outer + overhang)
    center = _centroid(outline)
    distances = [abs(_cross(first, second, center)) / math.dist(first, second)
                 for first, second in zip(wall, wall[1:] + wall[:1])]
    rise = min(distances) * math.tan(math.radians(pitch))
    apex = [center[0], base + rise, center[1]]
    planes = []
    corner_heights = [[] for _ in ring]
    # Each fan plane passes through its outer wall edge. This also handles
    # bevel vertices: the matching wall distance is measured to its edge line.
    for i, (first, second) in enumerate(zip(ring, ring[1:] + ring[:1])):
        distance = abs(_cross(first, second, center)) / math.dist(first, second)
        wall_distance = max(1e-8, distance - overhang)
        low = base - rise * overhang / wall_distance
        corner_heights[i].append(low)
        corner_heights[(i + 1) % len(ring)].append(low)
        builder = _builder("roof", "roof", uv_sizes)
        plane = [[first[0], low, first[1]], [second[0], low, second[1]], apex]
        planes.append(plane)
        _slab(builder, plane)
        parts.append(builder.part())
    for point, heights in zip(ring, corner_heights):
        if abs(heights[0] - heights[1]) < 1e-5:
            continue
        # Unequal tent slopes meet with a vertical corner facet beyond walls.
        points = [apex, [point[0], min(heights), point[1]],
                  [point[0], max(heights), point[1]]]
        normal = _normal(points)
        magnitude = math.sqrt(sum(value * value for value in normal))
        delta = [value * 0.15 / magnitude for value in normal]
        back = [[vertex[axis] - delta[axis] for axis in range(3)] for vertex in points]
        builder = _builder("roof", "roof", uv_sizes)
        builder.poly(points)
        builder.poly(back[::-1])
        for i in range(3):
            following = (i + 1) % 3
            builder.poly([points[i], back[i], back[following], points[following]])
        parts.append(builder.part())
    xs, zs = [list(point[axis] for point in outline) for axis in (0, 1)]
    return {"rect": {"center": center, "length": max(xs) - min(xs),
                     "depth": max(zs) - min(zs), "angle_deg": 0.0},
            "level": number, "form": "tent", "eaves_y": base,
            "ridge_y": base + rise, "ridge": None, "pitch_deg": pitch,
            "overhang_m": overhang, "outline": ring, "planes": planes}


def _roof_height(wing, x, z, style, pitch):
    """Sample a rectangular wing in its local ridge frame."""
    outer = wall_offsets(style, wing["level"])[1]
    span = wing["rect"]["depth"] / 2 + outer
    slope = math.tan(math.radians(pitch))
    if wing["form"] == "hip":
        end = wing["rect"]["length"] / 2 + outer
        return wing["eaves_y"] + min(span - abs(z), end - abs(x)) * slope
    if wing["form"] == "shed":
        return wing["eaves_y"] + (span + z * wing["high"]) * slope
    return wing["ridge_y"] - abs(z) * slope


def _chimneys(info, style, desc, density, uv_sizes, parts):
    """Choose seeded ridge positions, falling back to flat roof triangles."""
    minimum, maximum = style.get("chimneys", [0, 0])
    count = round(minimum + (maximum - minimum) * density)
    top_level = info.get("topmost_level", max(
        (target["level"] for target in info["wings"]+info["flat_tops"]), default=0))
    candidates = ([wing for wing in info["wings"] if wing["level"] == top_level]
                  or [top for top in info["flat_tops"] if top["level"] == top_level]
                  or info["wings"] or info["flat_tops"])
    if not candidates:
        return
    for i in range(count):
        random = rng(desc.get("seed", 0), f"chimney:{i}")
        target = random.choice(candidates)
        width = style.get("chimney_width_m", 0.6)
        if "rect" in target:
            rect = target["rect"]
            ridge = target["ridge"]
            ridge_length = math.dist(*ridge) if ridge else 0
            x, z = (random.uniform(0.2, 0.8) - 0.5) * ridge_length, random.choice((-0.3, 0.3))
            if target["form"] == "shed":
                local = _rotate([ridge[0][0] - rect["center"][0],
                                 ridge[0][2] - rect["center"][1]], -rect["angle_deg"])
                z = local[1] - math.copysign(0.3, local[1])
            point = _at(rect, x, 0, z)
            top = target["ridge_y"] + 0.9
            # Starting below the wall line guarantees intersection with tent,
            # shed and hip surfaces including all four chimney corners.
            bottom = target["eaves_y"] - 0.15
        else:
            outline = target["outline"]
            triangle = random.choice(_triangles(outline))
            fraction = random.uniform(0.2, 0.8)
            center = [(triangle[0][axis] + triangle[1][axis]) / 2 for axis in (0, 1)]
            point = [center[0] * fraction + triangle[2][0] * (1 - fraction), 0,
                     center[1] * fraction + triangle[2][1] * (1 - fraction)]
            bottom, top = target["y"] - 0.25, target["y"] + 0.9
        builder = _builder("chimney", "chimney", uv_sizes)
        builder.box([point[0], (bottom + top) / 2, point[2]], [width, top - bottom, width])
        parts.append(builder.part())


def _dormers(info, style, desc, density, pitch, uv_sizes, parts):
    """Add closed trim fronts with raised louvers and small closed roof caps."""
    probability = min(1, style.get("dormers", 0) * density * 2)
    for i, wing in enumerate(info["wings"]):
        if wing["form"] not in ("gable", "hip"):
            continue
        rect = wing["rect"]
        outer = wall_offsets(style, wing["level"])[1]
        if rect["depth"] + 2 * outer < 6 or math.dist(*wing["ridge"]) < 4:
            continue
        for side in (-1, 1):
            if rng(desc.get("seed", 0), f"dormer:{i}:{side}").random() >= probability:
                continue
            z = side * (rect["depth"] / 2 + outer) * 0.55
            base = _roof_height(wing, 0, z, style, pitch)
            builder = _builder("dormer", "trim", uv_sizes)
            yaw = -math.radians(rect["angle_deg"])
            center = _at(rect, 0, base + 0.4, z)
            builder.box(center, [1.4, 0.8, 0.6], yaw)
            for j in range(4):
                center = _at(rect, 0, base + 0.15 + j * 0.16, z + side * 0.33)
                builder.box(center, [1.25, 0.07, 0.08], yaw)
            parts.append(builder.part())
            cap = _builder("dormer", "roof", uv_sizes)
            _slab(cap, [_at(rect, x, base + 0.85 + (0.3 - side * offset) * 0.4, z + offset)
                        for x, offset in ((-0.8, -0.4), (0.8, -0.4), (0.8, 0.4), (-0.8, 0.4))])
            parts.append(cap.part())


def _fully_covered(outline, covered):
    """Test containment, including boundary contact but excluding edge excursions."""
    from app.core.world_geometry import polygon_distance
    if outline == covered:
        return True
    if any(not _point_in_polygon(*p, covered) and polygon_distance(*p, covered)>1e-8 for p in outline):
        return False
    for a,b in zip(outline, outline[1:]+outline[:1]):
        cuts = [0.,1.]
        dx,dz = b[0]-a[0],b[1]-a[1]
        for c,d in zip(covered,covered[1:]+covered[:1]):
            ex,ez = d[0]-c[0],d[1]-c[1]
            det = dx*ez-dz*ex
            if abs(det)<1e-10:
                # Collinear boundary vertices also split the segment.
                if abs(_cross(a,b,c))<1e-8:
                    cuts.extend(((p[0]-a[0])*dx+(p[1]-a[1])*dz)/(dx*dx+dz*dz)
                                for p in (c,d))
                continue
            t=((c[0]-a[0])*ez-(c[1]-a[1])*ex)/det
            u=((c[0]-a[0])*dz-(c[1]-a[1])*dx)/det
            if 0<t<1 and -1e-8<=u<=1+1e-8:
                cuts.append(t)
        cuts=sorted(t for t in cuts if 0<=t<=1)
        for lo,hi in zip(cuts,cuts[1:]):
            t=(lo+hi)/2
            p=[a[0]+dx*t,a[1]+dz*t]
            if not _point_in_polygon(*p,covered) and polygon_distance(*p,covered)>1e-8:
                return False
    return True


def build_roofs(facts: Dict, style: Dict, desc: Dict, *, tier: str,
                uv_sizes: Optional[Dict[str, float]] = None) -> Tuple[List[Part], Dict[str, Any]]:
    """Build roofs and shared ornament metadata exclusively from supplied facts.

    Wing rectangles describe contour dimensions, before outer wall offsets.
    eaves_y is the wall-head datum; sloping overhang edges sit below it.
    Flat-top y is the plate's upper surface, with a real parapet flag.
    """
    if tier not in ("full", "low"):
        raise ValueError("tier must be full or low")
    uv_sizes = uv_sizes or {}
    seed, overrides = desc.get("seed", 0), desc.get("overrides", {})
    roof = style["roof"]
    form = overrides.get("roof_form") or rng(seed, "roof_form").choice(roof["forms"])
    pitch = overrides.get("pitch_deg")
    if pitch is None:
        pitch = round(rng(seed, "roof_pitch").uniform(*roof["pitch_deg"]) * 2) / 2
    overhang = round(rng(seed, "roof_overhang").uniform(*roof["overhang_m"]) * 20) / 20
    info = {"form": form, "pitch_deg": float(pitch), "overhang_m": overhang,
            "wings": [], "flat_tops": []}
    parts = []
    levels = sorted(facts["levels"], key=lambda level: level["level"])
    info["topmost_level"] = levels[-1]["level"]
    for i, level in enumerate(levels):
        topmost = i == len(levels) - 1
        covered = None if topmost else levels[i + 1]["outline"]
        outline, number = level["outline"], level["level"]
        base = facts["eaves_y"] if topmost else level["top_y"]
        if topmost and form == "flat":
            _flat(outline, number, base, style, overhang, uv_sizes, info, parts)
            continue
        if covered and _fully_covered(outline, covered):
            continue
        angle = orthogonal_frame(outline)
        if angle is None or (covered and orthogonal_frame(covered) is None):
            if topmost and form != "flat" and _convex(outline):
                info["wings"].append(_tent(level, base, pitch, overhang, style, uv_sizes, parts))
            else:
                _flat(outline, number, base, style, overhang, uv_sizes, info, parts)
            continue
        for wing in decompose(outline, covered, angle):
            rect, sides = wing["rect"], wing["covered_sides"]
            wing_form = "shed" if not topmost and sides and form != "flat" else form
            if wing_form == "flat":
                half_length, half_span = rect["length"] / 2, rect["depth"] / 2
                ring = [[point[0], point[2]] for point in (
                    _at(rect, x, base, z) for x, z in ((-half_length, -half_span),
                    (half_length, -half_span), (half_length, half_span), (-half_length, half_span)))]
                if sides:
                    outer = wall_offsets(style, number)[1]
                    limits = [-half_length-outer-overhang, half_length+outer+overhang,
                              -half_span-outer-overhang, half_span+outer+overhang]
                    for side in sides:
                        index = (0 if side.startswith("x") else 2) + (1 if side.endswith("max") else 0)
                        half = half_length if index < 2 else half_span
                        limits[index] = (1 if index % 2 else -1)*(half-wall_offsets(style, number+1)[0]-.01)
                    a,b,c,d = limits
                    ring = [[_at(rect,x,base,z)[k] for k in (0,2)] for x,z in ((a,c),(b,c),(b,d),(a,d))]
                    # The ring is already expanded on exposed sides and trimmed on covered sides.
                    first_part = len(parts)
                    _flat(ring, number, base, style, 0, uv_sizes, info, parts, expanded=True)
                    for part in parts[first_part:]:
                        part["roof_level"] = number
                else:
                    _flat(ring, number, base, style, overhang, uv_sizes, info, parts)
            else:
                wing_pitch = min(pitch, 25) if not topmost and sides else pitch
                info["wings"].append(_pitched(rect, sides, wing_form, number, base,
                                              wing_pitch, overhang, style, uv_sizes, parts))
    density = overrides.get("ornament_density", 0.5)
    _chimneys(info, style, desc, density, uv_sizes, parts)
    if tier == "full":
        _dormers(info, style, desc, density, pitch, uv_sizes, parts)
    return parts, info
