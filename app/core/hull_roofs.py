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
    """Return the longest edge's frame if every edge aligns with it.

    An edge aligns within 0.5 degrees, or when its ends stray at most the
    decompose snap distance (0.15 m) across the axis it follows.
    """
    edges = [(math.dist(first, second), math.degrees(math.atan2(
        second[1] - first[1], second[0] - first[0])))
        for first, second in zip(outline, outline[1:] + outline[:1])
        if math.dist(first, second) > 1e-8]
    if not edges:
        return None
    angle = max(edges, key=lambda edge: edge[0])[1] % 180
    for length, direction in edges:
        deviation = abs((direction - angle + 45) % 90 - 45)
        if (deviation > 0.5 + 1e-8
                and length * math.sin(math.radians(deviation)) > .15 + 1e-8):
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

    Side names refer to the rectangle's local frame. Ties prefer shorter seams,
    then x runs; covered partitions retain their original x-run preference.
    Coordinates snap to their cluster mean; a cluster spans at most 0.15 m,
    so outline jitter never makes a sliver wing and a chain of close values
    never collapses a real step.
    """
    local = [_rotate(point, -angle_deg) for point in outline]
    above = [_rotate(point, -angle_deg) for point in (covered or [])]
    # Snap both rings together in the roof frame, before grid and polygon tests.
    for axis in (0, 1):
        points = sorted(local + above, key=lambda point: point[axis])
        groups = []
        for point in points:
            if not groups or point[axis] - groups[-1][0][axis] > .15 + 1e-10:
                groups.append([])
            groups[-1].append(point)
        for group in groups:
            mean = sum(point[axis] for point in group) / len(group)
            for point in group:
                point[axis] = mean
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
    def partition_key(rectangles):
        # Prefer shorter internal joins when equally many exposed wings tile
        # the outline: an L then has a continuous main wing and an abutting
        # ridge, rather than a short square behind one long eave.
        perimeter = sum(2 * (xs[b]-xs[a]+zs[d]-zs[c]) for a,b,c,d in rectangles)
        return len(rectangles), perimeter if not covered else 0
    rectangles = sorted(min(candidates, key=partition_key))
    owners = {(i,j): index for index,(a,b,c,d) in enumerate(rectangles)
              for i in range(a,b) for j in range(c,d)}
    result = []
    for first, last, bottom, top in rectangles:
        sides, seams = [], []
        for name, neighbors in (
            ("x_min", [(first - 1, j) for j in range(bottom, top)]),
            ("x_max", [(last, j) for j in range(bottom, top)]),
            ("z_min", [(i, bottom - 1) for i in range(first, last)]),
            ("z_max", [(i, top) for i in range(first, last)]),
        ):
            if any(neighbor in occupied for neighbor in neighbors):
                sides.append(name)
            for neighbor in sorted({owners[cell] for cell in neighbors if cell in owners}):
                seams.append({"side": name, "neighbor": neighbor})
        result.append({"rect": {
            "center": _rotate([(xs[first] + xs[last]) / 2, (zs[bottom] + zs[top]) / 2], angle_deg),
            "length": xs[last] - xs[first], "depth": zs[top] - zs[bottom],
            "angle_deg": angle_deg}, "covered_sides": sides, "seam_sides": seams})
    return result


def _builder(tag, material, uv_sizes):
    """Apply material UV scale and the shared protrusion convention."""
    return PartBuilder(tag, material, uv_size_m=uv_sizes.get(material, 2.0),
                       protrudes=tag == "roof")


def _slab(builder, points, thickness=0.15, *, vertical=False):
    """Extrude a planar upward polygon inward by its physical thickness."""
    if _normal(points)[1] < 0:
        points = points[::-1]
    normal = _normal(points)
    magnitude = math.sqrt(sum(value * value for value in normal))
    delta = ([0, thickness * magnitude / normal[1], 0] if vertical
             else [value * thickness / magnitude for value in normal])
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
            else (abs(math.sin(math.radians(rect["angle_deg"]))) > .5
                  if rect.get("ridge") == "width" else
                  abs(math.cos(math.radians(rect["angle_deg"]))) > .5
                  if rect.get("ridge") == "depth" else
                  rect["depth"] > rect["length"]))
    if turn:
        result.update(length=rect["depth"], depth=rect["length"],
                      angle_deg=rect["angle_deg"] + 90)
        side = {"x_min": "z_max", "x_max": "z_min",
                "z_min": "x_min", "z_max": "x_max"}[side]
    return result, -1 if side == "z_min" else 1


def _side_index(side, original_angle, ridge_angle):
    """Map an original rectangle side into its wing's ridge frame."""
    axis, direction = side.split("_")
    vector = _rotate([1, 0] if axis == "x" else [0, 1], original_angle-ridge_angle)
    index = 0 if abs(vector[0]) > .5 else 2
    sign = (1 if direction == "max" else -1) * vector[index//2]
    return index + int(sign > 0)


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
        return min(min(heights), wing["ridge_y"]) if wing.get("flat_top") else min(heights)
    rect = wing["rect"]
    x, z = _rotate([x-rect["center"][0], z-rect["center"][1]], -rect["angle_deg"])
    low_x, high_x, low_z, high_z = wing["limits"]
    if not (low_x-1e-4 <= x <= high_x+1e-4 and low_z-1e-4 <= z <= high_z+1e-4):
        return None
    if "footprint_regions" in wing and not any(
            a-1e-4 <= x <= b+1e-4 and c-1e-4 <= z <= d+1e-4
            for a,b,c,d in wing["footprint_regions"]):
        return None
    height = _roof_height(wing, x, z, style, wing["pitch_deg"])
    return min(height, wing["ridge_y"]) if wing.get("flat_top") else height


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


def _cap_pitch(pitch, span, style, explicit_pitch, max_rise):
    """Lower only automatic pitch, respecting the style minimum."""
    if not explicit_pitch and span * math.tan(math.radians(pitch)) > max_rise:
        return max(style["roof"].get("min_pitch_deg", 20),
                   math.degrees(math.atan(max_rise / span)))
    return pitch


def _clip_height(points, top):
    """Clip a polygon below a horizontal plane."""
    result = []
    for a, b in zip(points, points[1:] + points[:1]):
        if a[1] <= top:
            result.append(a)
        if (a[1] <= top) != (b[1] <= top):
            t = (top - a[1]) / (b[1] - a[1])
            result.append([a[k] + t * (b[k] - a[k]) for k in range(3)])
    return result


def _cap_surfaces(surfaces, top):
    """Clip convex slopes and close their cut with a horizontal roof slab."""
    surfaces = [_clip_height(surface, top) for surface in surfaces]
    cut = {(round(p[0], 10), round(p[2], 10)) for surface in surfaces
           for p in surface if abs(p[1] - top) < 1e-8}
    if len(cut) >= 3:
        cx = sum(p[0] for p in cut) / len(cut)
        cz = sum(p[1] for p in cut) / len(cut)
        ring = sorted(cut, key=lambda p: math.atan2(p[1] - cz, p[0] - cx))
        surfaces.append([[x, top, z] for x, z in ring])
    return surfaces


def _free_intervals(start, end, blocked):
    """Subtract seam intervals from an edge, preserving its direction."""
    reverse = start > end
    intervals = [tuple(sorted((start, end)))]
    for low, high in sorted(blocked):
        remaining = []
        for a, b in intervals:
            if high <= a or low >= b:
                remaining.append((a, b))
            else:
                if a < low:
                    remaining.append((a, low))
                if high < b:
                    remaining.append((high, b))
        intervals = remaining
    return [(b, a) if reverse else (a, b) for a, b in intervals]


def _subtract_region(region, cut):
    """Return disjoint rectangles outside an axis-aligned cut."""
    a, b, c, d = region
    left, right = max(a, cut[0]), min(b, cut[1])
    bottom, top = max(c, cut[2]), min(d, cut[3])
    if left >= right or bottom >= top:
        return [region]
    return [piece for piece in ([a, left, c, d], [right, b, c, d],
                               [left, right, c, bottom], [left, right, top, d])
            if piece[0] < piece[1] and piece[2] < piece[3]]


def _trim_board(first, second, outward, width, thickness, kind, number, uv_sizes, parts):
    """Closed rectangular board outside an edge; width runs down its face."""
    direction = [b - a for a, b in zip(first, second)]
    length = math.sqrt(sum(value * value for value in direction))
    if length < 1e-6:
        return
    # Downward perpendicular within the vertical edge plane (rakes included).
    down = [direction[1] * direction[0] / length,
            -(direction[0] ** 2 + direction[2] ** 2) / length,
            direction[1] * direction[2] / length]
    magnitude = math.sqrt(sum(value * value for value in down))
    down = [value * width / magnitude for value in down]
    points = [first, second, [second[k] + down[k] for k in range(3)],
              [first[k] + down[k] for k in range(3)]]
    points += [[point[k] + outward[k] * thickness for k in range(3)] for point in points]
    center = [sum(point[k] for point in points) / 8 for k in range(3)]
    builder = _builder("roof_trim", "trim", uv_sizes)
    for indices in ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
                    (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        face = [points[j] for j in indices]
        if sum(normal * (face[0][k] - center[k])
               for k, normal in enumerate(_normal(face))) < 0:
            face.reverse()
        builder.poly(face)
    part = builder.part()
    part.update(trim_kind=kind, roof_level=number, protrudes=True)
    parts.append(part)


def _eave_trim(first, second, outward, overhang, details, number, uv_sizes, parts):
    _trim_board(first, second, outward, .18, .03, "fascia", number, uv_sizes, parts)
    if details and overhang >= .15:
        ends = [[point[k] + outward[k] * .03 - (.18 if k == 1 else 0)
                 for k in range(3)] for point in (first, second)]
        _trim_board(*ends, outward, .10, .10, "gutter", number, uv_sizes, parts)


def _pitched_trim(rect, limits, blocked, form, high, base, span, slope, cap,
                  overhang, details, number, uv_sizes, parts):
    """Use free own-wing edges, never the extension into its neighbour."""
    a, b, c, d = limits

    def point(x, z):
        y = (base + (span + high * z) * slope if form == "shed"
             else base + (span - abs(z)) * slope)
        return _at(rect, x, min(y, cap), z)

    def outward(x, z):
        vector = _rotate([x, z], rect["angle_deg"])
        return [vector[0], 0, vector[1]]

    eaves = (range(4) if form == "hip" else
             (2 if high > 0 else 3,) if form == "shed" else (2, 3))
    for index in eaves:
        # Intervals live in the ridge frame, before scene rotation.
        low, upper = (c, d) if index < 2 else (a, b)
        for start, finish in _free_intervals(low, upper, blocked.get(index, [])):
            ends = ([point(a if index == 0 else b, start),
                     point(a if index == 0 else b, finish)] if index < 2 else
                    [point(start, c if index == 2 else d),
                     point(finish, c if index == 2 else d)])
            # Hip end eaves have the same height as the transverse eaves.
            if form == "hip":
                for vertex in ends:
                    vertex[1] = base - overhang * slope
            _eave_trim(*ends, outward(-1 if index == 0 else 1 if index == 1 else 0,
                                      -1 if index == 2 else 1 if index == 3 else 0),
                       overhang, details, number, uv_sizes, parts)
    if not details or form == "hip":
        return
    for index, x in ((0, a), (1, b)):
        if form == "shed":
            low, upper = sorted((c, d), key=lambda z: high * z)
            cut = (cap - base) / slope - span
            upper = min(upper, cut) if high > 0 else max(upper, -cut)
            intervals = [(low, upper)]
        else:
            cut = max(0, span - (cap - base) / slope)
            intervals = [(c, -cut), (d, cut)]
        intervals = [piece for start, end in intervals
                     for piece in _free_intervals(start, end, blocked.get(index, []))]
        for start, end in intervals:
            if min(c, d) - 1e-8 <= end <= max(c, d) + 1e-8 and abs(start - end) > 1e-8:
                _trim_board(point(x, start), point(x, end), outward(-1 if index == 0 else 1, 0),
                            .20, .03, "verge", number, uv_sizes, parts)


def _gable_panels(points, rect, limits, blocked, index, material, uv_sizes, parts):
    """Keep wall-end infill only on the free intervals of a wing side."""
    other = 2 if index < 2 else 0
    for low, high in _free_intervals(limits[other], limits[other + 1], blocked):
        region = list(limits)
        region[other:other + 2] = [low, high]
        clipped = _clip_polygon(points, region)
        if len(clipped) < 3:
            continue
        builder = _builder("gable", material, uv_sizes)
        builder.poly([_at(rect, *point) for point in clipped])
        parts.append(builder.part())


def _pitched(rect, sides, form, number, base, pitch, overhang, style, uv_sizes, parts, *, explicit_pitch=False, max_rise=6.0, seams=(), details=False):
    """Use wall-span pitch and shortened hip-ridge formulas."""
    original_angle = rect["angle_deg"]
    rect, high = _wing_axes(rect, sides, form)
    outer = wall_offsets(style, number)[1]
    half_length = rect["length"] / 2 + outer
    half_span = rect["depth"] / 2 + outer
    pitch = _cap_pitch(pitch, half_span, style, explicit_pitch, max_rise)
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
    covered_indices = {i for i, value in enumerate(limits) if abs(value-(-end,end,-edge,edge)[i])>1e-8}
    seam_indices = set()
    seam_regions = []
    higher_intervals = {}
    seam_bounds = {}
    normal_limits = list(limits)
    own_limits = list(limits)
    seam_intervals = {}
    for seam in seams:
        index = _side_index(seam["side"], original_angle, rect["angle_deg"])
        sign = 1 if index % 2 else -1
        seam_indices.add(index)
        neighbor = seam["rect"]
        corners = [_at(neighbor, x, 0, z)
                   for x in (-neighbor["length"] / 2, neighbor["length"] / 2)
                   for z in (-neighbor["depth"] / 2, neighbor["depth"] / 2)]
        local = [_rotate([p[0] - rect["center"][0], p[2] - rect["center"][1]],
                         -rect["angle_deg"]) for p in corners]
        transverse = 1 if index < 2 else 0
        low = min(p[transverse] for p in local)
        upper = max(p[transverse] for p in local)
        wall_half = rect["depth" if index < 2 else "length"] / 2
        other = 2 if index < 2 else 0
        # A seam reaching a wall corner also blocks that corner's overhang.
        low = normal_limits[other] if low <= -wall_half + 1e-8 else low
        upper = normal_limits[other + 1] if upper >= wall_half - 1e-8 else upper
        seam_intervals.setdefault(index, []).append((low, upper))
        if index < 2 and seam.get("higher", False):
            higher_intervals.setdefault(index, []).append((low, upper,
                math.copysign(rect["length"]/2 + seam["extension"], sign)))
        half = rect["length" if index < 2 else "depth"] / 2
        own_limits[index] = math.copysign(half, sign)
        bound = math.copysign(half + seam["extension"], sign)
        seam_bounds[index] = (max if sign > 0 else min)(seam_bounds.get(index, bound), bound)
        limits[index] = seam_bounds[index]
        if seam["extension"]:
            region = [min(p[0] for p in local)-outer-overhang,
                      max(p[0] for p in local)+outer+overhang,
                      min(p[1] for p in local)-outer-overhang,
                      max(p[1] for p in local)+outer+overhang]
            axis = 0 if index < 2 else 2
            region[axis:axis+2] = sorted((math.copysign(half,sign),bound))
            seam_regions.append(region)
    regions = [own_limits]
    trim_limits = list(own_limits)
    partial_indices = {index for index, intervals in seam_intervals.items()
                       if _free_intervals(normal_limits[2 if index < 2 else 0],
                                          normal_limits[3 if index < 2 else 1], intervals)}
    if partial_indices:
        # Subtract only the seam-facing strips from the normal eave rectangle.
        # The resulting disjoint rectangles are shared by slabs and height queries.
        regions = [normal_limits]
        for index, intervals in seam_intervals.items():
            axis = 0 if index < 2 else 2
            other = 2 - axis
            for low, upper in intervals:
                cut = list(normal_limits)
                cut[other:other + 2] = [low, upper]
                cut[axis + (1 if index % 2 == 0 else 0)] = own_limits[index]
                regions = [piece for region in regions for piece in _subtract_region(region, cut)]
        for index in partial_indices:
            trim_limits[index] = normal_limits[index]
            limits[index] = ((min if index % 2 == 0 else max)
                             (limits[index], normal_limits[index]))
    for region in seam_regions:
        region = [max(region[0], limits[0]), min(region[1], limits[1]),
                  max(region[2], limits[2]), min(region[3], limits[3])]
        if region[0] < region[1] and region[2] < region[3]:
            additions = [region]
            if partial_indices:
                for existing in regions:
                    additions = [piece for addition in additions
                                 for piece in _subtract_region(addition, existing)]
            regions.extend(additions)
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
        ridge_ends = [limits[0] if 0 in seam_indices else -ridge_half,
                      limits[1] if 1 in seam_indices else ridge_half]
        for side in (-1, 1):
            surfaces.append([[-end, low_y, side * edge], [end, low_y, side * edge],
                             [ridge_ends[1], ridge_y, 0], [ridge_ends[0], ridge_y, 0]])
        if form == "hip":
            for side in (-1, 1):
                if (0 if side < 0 else 1) in seam_indices:
                    continue
                surfaces.append([[side * end, low_y, -edge], [side * end, low_y, edge],
                                 [side * ridge_half, ridge_y, 0]])
        ridge = [_at(rect, x, ridge_y, 0) for x in ridge_ends]
    if seams:
        # Only ridge ends extend; side seams stop at their own wall line.
        for surface in surfaces:
            normal = _normal(surface)
            for point in surface:
                old_x, old_z = point[0], point[2]
                for axis, index in ((0,0),(0,1),(2,2),(2,3)):
                    bound = end if axis == 0 else edge
                    if index < 2 and index in seam_indices and abs(point[axis] - (-bound if index % 2 == 0 else bound)) < 1e-8:
                        point[axis] = limits[index]
                point[1] -= (normal[0]*(point[0]-old_x)+normal[2]*(point[2]-old_z))/normal[1]
        if form == "gable":
            ridge = [_at(rect, max(limits[0], min(limits[1], x)), ridge_y, 0)
                     for x in (limits[0], limits[1])]
    flat_top = ridge_y > base + max_rise + 1e-8
    if flat_top:
        ridge_y = base + max_rise
        surfaces = _cap_surfaces(surfaces, ridge_y)
        if form == "shed":
            cut_z = high * (max_rise / slope - half_span)
            a, b = (limits[:2] if seams else (-end, end))
            surfaces.append([[a, ridge_y, cut_z], [b, ridge_y, cut_z],
                             [b, ridge_y, high * edge], [a, ridge_y, high * edge]])
        for point in ridge:
            point[1] = ridge_y
    if seams and form == "shed":
        target_z = high * min(half_span, max(high * region[2 if high < 0 else 3] for region in regions))
        if flat_top:
            target_z = high * min(high * target_z, max_rise / slope - half_span)
        intervals = [region[:2] for region in regions if region[2]-1e-8 <= target_z <= region[3]+1e-8]
        ridge = [_at(rect, x, min(ridge_y, base+(half_span+high*target_z)*slope), target_z)
                 for x in (min(a for a,b in intervals) if 0 in seam_indices else -half_length,
                           max(b for a,b in intervals) if 1 in seam_indices else half_length)]
    original_ridge_y = ridge_y
    if sides or seams:
        ridge = [[*point] for point in ridge]
        for point in ridge:
            local = _rotate([point[0]-rect["center"][0], point[2]-rect["center"][1]], -rect["angle_deg"])
            x = max(limits[0], min(limits[1], local[0]))
            z = max(limits[2], min(limits[3], local[1]))
            y = min(base + (half_span + high*z)*slope, original_ridge_y) if form == "shed" else ridge_y
            point[:] = _at(rect, x, y, z)
        ridge_y = max(point[1] for point in ridge)
    first_part = len(parts)
    for surface in surfaces:
        for region in (regions if seams else [limits]):
            clipped = _clip_polygon(surface, region)
            # A square hip collapses both ridge points to one apex.
            points = []
            for x, y, z in clipped:
                point = _at(rect, x, y, z)
                if not any(math.dist(point, previous) < 1e-8 for previous in points):
                    points.append(point)
            if len(points) < 3 or abs(_normal(points)[1]) < 1e-10:
                continue
            builder = _builder("roof", "roof", uv_sizes)
            # Vertical extrusion preserves the clipped footprint and planar
            # cut faces while keeping .15 m perpendicular slab thickness.
            _slab(builder, points, vertical=bool(seams))
            parts.append(builder.part())
    ridge_y = original_ridge_y
    if form == "gable":
        material = style.get("storey_slot", {}).get(number, "wall_ground" if number == 0 and style.get("materials", {}).get("wall_ground") else "wall")
        for side in (-1, 1):
            index = 0 if side < 0 else 1
            if index in seam_indices and index not in partial_indices:
                continue
            points = [_at(rect, max(limits[0], min(limits[1], side * half_length)), base, z) for z in (-half_span, half_span)]
            if flat_top:
                cap_half = max(0, half_span - max_rise / slope)
                points.extend(_at(rect, max(limits[0], min(limits[1], side * half_length)), ridge_y, z)
                              for z in (cap_half, -cap_half))
            else:
                points.append(_at(rect, max(limits[0], min(limits[1], side * half_length)), ridge_y, 0))
            outward = _rotate([side, 0], rect["angle_deg"])
            normal = _normal(points)
            if normal[0] * outward[0] + normal[2] * outward[1] < 0:
                points.reverse()
            local_points = []
            for point in points:
                x, z = _rotate([point[0]-rect["center"][0], point[2]-rect["center"][1]], -rect["angle_deg"])
                local_points.append([x, point[1], z])
            _gable_panels(local_points, rect, limits, seam_intervals.get(index, []),
                          index, material, uv_sizes, parts)
    if form == "shed":
        material = style.get("storey_slot", {}).get(number, "wall_ground" if number == 0 and style.get("materials", {}).get("wall_ground") else "wall")
        for side in (-1, 1):
            index = 0 if side < 0 else 1
            if index in seam_indices and index not in partial_indices:
                continue
            points = [_at(rect, max(limits[0], min(limits[1], side * half_length)), base, -high * half_span),
                      _at(rect, max(limits[0], min(limits[1], side * half_length)), base, high * half_span),
                      _at(rect, max(limits[0], min(limits[1], side * half_length)), base + 2 * half_span * slope, high * half_span)]
            points = _clip_height(points, ridge_y)
            normal = _normal(points)
            outward = _rotate([side, 0], rect["angle_deg"])
            if normal[0] * outward[0] + normal[2] * outward[1] < 0:
                points.reverse()
            local_points = []
            for point in points:
                x, z = _rotate([point[0]-rect["center"][0], point[2]-rect["center"][1]], -rect["angle_deg"])
                local_points.append([x, point[1], z])
            _gable_panels(local_points, rect, limits, seam_intervals.get(index, []),
                          index, material, uv_sizes, parts)
        index = 2 if high < 0 else 3
        if not sides and (index not in seam_indices or index in partial_indices):
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
            _gable_panels(local_points, rect, limits, seam_intervals.get(index, []),
                          index, material, uv_sizes, parts)
    material = style.get("storey_slot", {}).get(number, "wall_ground" if number == 0 and style.get("materials", {}).get("wall_ground") else "wall")
    for index, intervals in higher_intervals.items():
        for low, upper, limit in intervals:
            if form == "shed":
                points = [[limit, base, -high*half_span], [limit, base, high*half_span],
                          [limit, base+2*half_span*slope, high*half_span]]
                points = _clip_height(points, ridge_y)
            else:
                cap_half = max(0, half_span-max_rise/slope) if flat_top else 0
                points = [[limit, base, -half_span], [limit, base, half_span],
                          [limit, ridge_y, cap_half]]
                if flat_top:
                    points.append([limit, ridge_y, -cap_half])
            if _normal(points)[0] * (-1 if index == 0 else 1) < 0:
                points.reverse()
            panel_limits = list(limits)
            panel_limits[0:2] = [min(limits[0],limit), max(limits[1],limit)]
            panel_limits[2:4] = [low,upper]
            _gable_panels(points, rect, panel_limits, [], index, material, uv_sizes, parts)
    if sides or seams:
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
    if any(form != "flat" for form in style["roof"]["forms"]):
        blocked = dict(seam_intervals)
        blocked.update({index: [(-math.inf, math.inf)] for index in covered_indices})
        _pitched_trim(rect, trim_limits, blocked, form, high, base,
                      half_span, slope, base+max_rise, overhang, details, number, uv_sizes, parts)
    for part in parts[first_part:]:
        part["roof_level"] = number
    return {**({"footprint_regions": regions} if seams else {}),
            "rect": rect, "level": number, "form": form, "eaves_y": base,
            "ridge_y": ridge_y, "flat_top": flat_top, "ridge": ridge, "pitch_deg": pitch,
            "gable_ends": sorted(seam_indices & {0, 1}) if form == "hip" else [],
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


def _tent(level, base, pitch, overhang, style, uv_sizes, parts, *, explicit_pitch=False, max_rise=6.0, details=False):
    """Put the apex over the area centroid and measure rise from outer walls."""
    outline = level["outline"]
    number = level["level"]
    outer = wall_offsets(style, number)[1]
    wall = offset_ring(outline, level["ccw"], outer)
    ring = offset_ring(outline, level["ccw"], outer + overhang)
    center = _centroid(outline)
    distances = [abs(_cross(first, second, center)) / math.dist(first, second)
                 for first, second in zip(wall, wall[1:] + wall[:1])]
    pitch = _cap_pitch(pitch, min(distances), style, explicit_pitch, max_rise)
    rise = min(distances) * math.tan(math.radians(pitch))
    flat_top = rise > max_rise + 1e-8
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
        if not flat_top:
            _slab(builder, plane)
            parts.append(builder.part())
    if flat_top:
        for surface in _cap_surfaces(planes, base + max_rise):
            builder = _builder("roof", "roof", uv_sizes)
            _slab(builder, surface)
            parts.append(builder.part())
    for point, heights in zip(ring, corner_heights):
        if abs(heights[0] - heights[1]) < 1e-5:
            continue
        # Unequal tent slopes meet with a vertical corner facet beyond walls.
        points = [apex, [point[0], min(heights), point[1]],
                  [point[0], max(heights), point[1]]]
        points = _clip_height(points, base + max_rise) if flat_top else points
        normal = _normal(points)
        magnitude = math.sqrt(sum(value * value for value in normal))
        delta = [value * 0.15 / magnitude for value in normal]
        back = [[vertex[axis] - delta[axis] for axis in range(3)] for vertex in points]
        builder = _builder("roof", "roof", uv_sizes)
        builder.poly(points)
        builder.poly(back[::-1])
        for i in range(len(points)):
            following = (i + 1) % len(points)
            builder.poly([points[i], back[i], back[following], points[following]])
        parts.append(builder.part())
    for plane in (planes if any(form != "flat" for form in style["roof"]["forms"]) else []):
        first, second = plane[:2]
        dx, dz = second[0] - first[0], second[2] - first[2]
        length = math.hypot(dx, dz)
        outward = [dz / length, 0, -dx / length]
        midpoint = [(first[k] + second[k]) / 2 for k in range(3)]
        if outward[0] * (midpoint[0] - center[0]) + outward[2] * (midpoint[2] - center[1]) < 0:
            outward = [-value for value in outward]
        _eave_trim(first, second, outward, overhang, details, number, uv_sizes, parts)
    xs, zs = [list(point[axis] for point in outline) for axis in (0, 1)]
    return {"rect": {"center": center, "length": max(xs) - min(xs),
                     "depth": max(zs) - min(zs), "angle_deg": 0.0},
            "level": number, "form": "tent", "eaves_y": base,
            "ridge_y": base + min(rise, max_rise), "flat_top": flat_top, "ridge": None, "pitch_deg": pitch,
            "overhang_m": overhang, "outline": ring, "planes": planes}


def _roof_height(wing, x, z, style, pitch):
    """Sample a rectangular wing in its local ridge frame."""
    outer = wall_offsets(style, wing["level"])[1]
    span = wing["rect"]["depth"] / 2 + outer
    slope = math.tan(math.radians(pitch))
    if wing["form"] == "hip":
        end = wing["rect"]["length"] / 2 + outer
        distances = [span - abs(z)]
        if 0 not in wing.get("gable_ends", []):
            distances.append(end + x)
        if 1 not in wing.get("gable_ends", []):
            distances.append(end - x)
        return wing["eaves_y"] + min(distances) * slope
    if wing["form"] == "shed":
        return wing["eaves_y"] + (span + z * wing["high"]) * slope
    return (wing["eaves_y"] + (span - abs(z)) * slope if wing.get("flat_top")
            else wing["ridge_y"] - abs(z) * slope)


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
        if wing["ridge_y"] - wing["eaves_y"] < 1.6 or wing["form"] not in ("gable", "hip"):
            continue
        rect = wing["rect"]
        outer = wall_offsets(style, wing["level"])[1]
        if rect["depth"] + 2 * outer < 6 or math.dist(*wing["ridge"]) < 4:
            continue
        for side in (-1, 1):
            if rng(desc.get("seed", 0), f"dormer:{i}:{side}").random() >= probability:
                continue
            z = side * (rect["depth"] / 2 + outer) * 0.55
            base = min(wing["ridge_y"], _roof_height(wing, 0, z, style, wing["pitch_deg"]))
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


def _party_seams(rect, level, desc):
    """Represent party boundaries as the same zero-extension wing seams."""
    from app.core.hull_walls import party_edges
    seams = []
    for edge in party_edges(level, desc):
        local = [_rotate([p[k]-rect["center"][k] for k in (0,1)],
                         -rect["angle_deg"]) for p in (edge['a'],edge['b'])]
        for axis, dimension in ((0, 'length'), (1, 'depth')):
            half = rect[dimension]/2
            for sign, suffix in ((-1,'min'), (1,'max')):
                if all(abs(p[axis]-sign*half)<1e-6 for p in local):
                    seams.append(dict(side=('x' if axis==0 else 'z')+'_'+suffix,
                                      rect=rect, extension=0))
    return seams


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
    explicit_pitch = "pitch_deg" in overrides
    max_rise = (overrides["max_rise_m"] if "max_rise_m" in overrides else
                min(roof.get("max_rise_m", 6.0),
                    roof.get("max_rise_ratio", 1.0) * facts["eaves_y"]))
    pitch = overrides.get("pitch_deg")
    if pitch is None:
        pitch = round(rng(seed, "roof_pitch").uniform(*roof["pitch_deg"]) * 2) / 2
    overhang = round(rng(seed, "roof_overhang").uniform(*roof["overhang_m"]) * 20) / 20
    info = {"form": form, "pitch_deg": float(pitch), "overhang_m": overhang,
            "wings": [], "flat_tops": []}
    parts = []
    details = tier == "full" and overrides.get("ornament_density", .5) > 0
    levels = sorted(facts["levels"], key=lambda level: level["level"])
    info["topmost_level"] = levels[-1]["level"]
    for i, level in enumerate(levels):
        topmost = i == len(levels) - 1
        covered = None if topmost else levels[i + 1]["outline"]
        outline, number = level["outline"], level["level"]
        base = facts["eaves_y"] if topmost else level["top_y"]
        from app.core.hull_walls import party_edges
        if topmost and form == "flat" and not party_edges(level, desc):
            _flat(outline, number, base, style, overhang, uv_sizes, info, parts)
            continue
        if covered and _fully_covered(outline, covered):
            continue
        angle = orthogonal_frame(outline)
        if angle is None or (covered and orthogonal_frame(covered) is None):
            if topmost and form != "flat" and _convex(outline):
                info["wings"].append(_tent(level, base, pitch, overhang, style, uv_sizes, parts, explicit_pitch=explicit_pitch, max_rise=max_rise, details=details))
            else:
                _flat(outline, number, base, style, overhang, uv_sizes, info, parts)
            continue
        wings = decompose(outline, covered, angle)
        if "ridge" in overrides:
            for wing in wings:
                wing["rect"]["ridge"] = overrides["ridge"]
        rises = []
        for wing in wings:
            wf = "shed" if not topmost and wing["covered_sides"] and form != "flat" else form
            wr, _ = _wing_axes(wing["rect"], wing["covered_sides"], wf)
            span = wr["depth"]/2 + wall_offsets(style, number)[1]
            wp = min(pitch,25) if not topmost and wing["covered_sides"] else pitch
            wp = _cap_pitch(wp, span, style, explicit_pitch, max_rise)
            rises.append(span * math.tan(math.radians(wp)) * (2 if wf == "shed" else 1))
        for wing_index, wing in enumerate(wings):
            rect, sides = wing["rect"], wing["covered_sides"]
            wing_form = "shed" if not topmost and sides and form != "flat" else form
            if wing_form == "flat":
                party_sides = [seam['side'] for seam in _party_seams(rect, level, desc)]
                sides = list(dict.fromkeys([*sides, *party_sides]))
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
                        limits[index] = (1 if index % 2 else -1)*(half if side in party_sides else half-wall_offsets(style, number+1)[0]-.01)
                    a,b,c,d = limits
                    ring = [[_at(rect,x,base,z)[k] for k in (0,2)] for x,z in ((a,c),(b,c),(b,d),(a,d))]
                    # The ring is already expanded on exposed sides and trimmed on covered sides.
                    first_part = len(parts)
                    _flat(ring, number, base, style, 0, uv_sizes, info, parts, expanded=True)
                    from app.core.hull_walls import clip_party_parts
                    generated = parts[first_part:]
                    caps = [p for p in generated if p['tag'] == 'roof']
                    parapets = [p for p in generated if p['tag'] != 'roof']
                    parapets = clip_party_parts(parapets, party_edges(level, desc), ornaments=True)
                    parts[first_part:] = caps + parapets
                    for part in parts[first_part:]:
                        part["roof_level"] = number
                else:
                    _flat(ring, number, base, style, overhang, uv_sizes, info, parts)
            else:
                # A lean-to under an upper storey stays at most 25° whatever the pitch —
                # a steeper one would run into that storey's windows.
                wing_pitch = min(pitch, 25) if not topmost and sides else pitch
                seams = []
                for seam in wing["seam_sides"]:
                    neighbor = seam["neighbor"]
                    dimension = "length" if seam["side"].startswith("x") else "depth"
                    ridge_rect, _ = _wing_axes(rect, sides, wing_form)
                    neighbor_wing = wings[neighbor]
                    neighbor_form = "shed" if not topmost and neighbor_wing["covered_sides"] and form != "flat" else form
                    neighbor_rect, _ = _wing_axes(neighbor_wing["rect"], neighbor_wing["covered_sides"], neighbor_form)
                    reciprocal = next(s for s in neighbor_wing["seam_sides"] if s["neighbor"] == wing_index)
                    end_seam = _side_index(seam["side"], rect["angle_deg"], ridge_rect["angle_deg"]) < 2
                    neighbor_end = _side_index(reciprocal["side"], neighbor_wing["rect"]["angle_deg"], neighbor_rect["angle_deg"]) < 2
                    extends = end_seam and (not neighbor_end or
                        (rises[wing_index], wing_index) < (rises[neighbor], neighbor))
                    extension = wings[neighbor]["rect"][dimension]/2 if extends else 0
                    seams.append(dict(seam, extension=extension, rect=wings[neighbor]["rect"],
                                      higher=rises[wing_index] > rises[neighbor] + 1e-6))
                seams.extend(_party_seams(rect, level, desc))
                info["wings"].append(_pitched(rect, sides, wing_form, number, base,
                                              wing_pitch, overhang, style, uv_sizes, parts,
                                              explicit_pitch=explicit_pitch, max_rise=max_rise, seams=seams, details=details))
    density = overrides.get("ornament_density", 0.5)
    _chimneys(info, style, desc, density, uv_sizes, parts)
    if tier == "full":
        _dormers(info, style, desc, density, pitch, uv_sizes, parts)
    return parts, info
