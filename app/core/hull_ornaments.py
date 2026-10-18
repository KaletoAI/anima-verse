"""Style ornaments derived exclusively from supplied hull and roof facts."""
import math
from typing import Dict, List, Optional

from app.core.hull_facades import module_count
from app.core.hull_mesh import Part, PartBuilder, _normal, offset_ring, rng
from app.core.hull_walls import _axes, _cells, _span, wall_offsets
from app.core.scene_recipe import WALL_SINK_M, _ring_ccw, _point_in_polygon
from app.core.world_geometry import polygon_distance, point_segment_distance
from app.core.hull_roofs import clip_detail, roof_top_y, _detail_samples, detail_breaks, _fully_covered


def _builder(tag, material, uv_sizes, *, protrudes=False):
    return PartBuilder(tag, material, uv_size_m=uv_sizes.get(material, 2.0),
                       protrudes=protrudes)


def _append(parts, builder):
    if builder.part()["faces"]:
        parts.append(builder.part())


def _point(edge, span, height, depth):
    tangent, normal = _axes(edge)
    return [edge["a"][0] + tangent[0] * span + normal[0] * depth, height,
            edge["a"][1] + tangent[1] * span + normal[1] * depth]


def _extrude(builder, first, second):
    """Close matching planar rings with consistently outward faces."""
    delta = [second[0][axis] - first[0][axis] for axis in range(3)]
    if sum(value * step for value, step in zip(_normal(first), delta)) > 0:
        first, second = first[::-1], second[::-1]
    builder.poly(first)
    builder.poly(second[::-1])
    for i in range(len(first)):
        following = (i + 1) % len(first)
        builder.quad(first[i], second[i], second[following], first[following])


def _block(builder, edge, left, right, bottom, top, back, front):
    if right - left <= 1e-5 or top - bottom <= 1e-5:
        return
    outline = [[_point(edge, span, bottom, depth)[axis] for axis in (0, 2)]
               for span, depth in ((left, back), (right, back), (right, front), (left, front))]
    builder.prism(outline, bottom, top)


def _beam(edge, start, end, outer, uv_sizes, parts):
    """Extrude a .16 m wide facade beam .05 m proud of the wall."""
    length = math.dist(start, end)
    if length < 1e-5:
        return
    offset = [-(end[1] - start[1]) * .08 / length, (end[0] - start[0]) * .08 / length]
    corners = [[point[axis] + sign * offset[axis] for axis in (0, 1)]
               for point, sign in ((start, -1), (end, -1), (end, 1), (start, 1))]
    builder = _builder("timber", "trim", uv_sizes)
    _extrude(builder, [_point(edge, span, height, outer) for span, height in corners],
             [_point(edge, span, height, outer + .05) for span, height in corners])
    builder.part()["diagonal"] = True
    _append(parts, builder)


def _timber_block(edge, bounds, outer, holes, uv_sizes, parts, roof_info=None, number=0):
    """Clip axis-aligned framing against all supplied aperture rectangles."""
    left, right, bottom, top = bounds
    touching = [hole for hole in holes if hole["s0"] < right and hole["s1"] > left
                and hole["y0"] < top and hole["y1"] > bottom]
    breaks = detail_breaks(roof_info, number, edge, (outer, outer + .05))
    for start, end, low, high in _cells(*bounds, touching, extra_s=breaks):
        builder = _builder("timber", "trim", uv_sizes)
        _block(builder, edge, start, end, low, high, outer, outer + .05)
        _append(parts, builder)


def _posts(left, right, holes):
    """Keep opening flanks and subdivide only the solid facade spans."""
    fixed = sorted({left + .08, right - .08,
                    *(max(left + .08, min(right - .08, hole[key] + offset))
                      for hole in holes for key, offset in (("s0", -.08), ("s1", .08)))})
    posts = set(fixed)
    for start, end in zip(fixed, fixed[1:]):
        if any(hole["s0"] < end - .08 and hole["s1"] > start + .08 for hole in holes):
            continue
        fields = max(1, math.ceil((end - start) / 1.6))
        posts.update(start + (end - start) * index / fields for index in range(1, fields))
    return sorted(posts)


def _timber(level, style, desc, density, uv_sizes, parts, roof_info, resolved, storey_m):
    """Place bands, opening posts, window rails and seeded free-field braces."""
    number = level["level"]
    bottom = style.get("plinth_height_m", 0) if number == 0 else level["floor_y"]
    top = level["top_y"]
    outer = wall_offsets(style, number)[1]
    ring = offset_ring(level["outline"], level["ccw"], outer)
    for edge in level["edges"]:
        left, right = _span(ring, edge, outer)
        if module_count(level, style, resolved, right-left, storey_m):
            continue
        holes = edge["openings"]
        posts = _posts(left, right, holes)
        for low, high in ((bottom, min(top, bottom + .16)), (max(bottom, top - .16), top)):
            _timber_block(edge, (left, right, low, high), outer, holes, uv_sizes, parts, roof_info, number)
        for post in posts:
            _timber_block(edge, (post - .08, post + .08, bottom, top), outer, holes, uv_sizes, parts, roof_info, number)
        for hole in holes:
            if hole["kind"] != "window":
                continue
            before = max((post for post in posts if post <= hole["s0"]), default=posts[0])
            after = min((post for post in posts if post >= hole["s1"]), default=posts[-1])
            for low, high in ((hole["y0"] - .16, hole["y0"]), (hole["y1"], hole["y1"] + .16)):
                _timber_block(edge, (before, after, max(bottom, low), min(top, high)),
                              outer, holes, uv_sizes, parts, roof_info, number)
        for field, (start, end) in enumerate(zip(posts, posts[1:])):
            if any(hole["s0"] < end and hole["s1"] > start
                   and hole["y0"] < top and hole["y1"] > bottom for hole in holes):
                continue
            choice = rng(desc.get("seed", 0), f"brace:{number}:{edge['index']}:{field}").choices(
                ("none", "brace_l", "brace_r", "cross"),
                weights=(1 - density, density / 3, density / 3, density / 3))[0]
            low, high = bottom + .16, top - .16
            if end - start < .32 or high - low < .32:
                continue
            if choice in ("brace_l", "cross"):
                _beam(edge, [start + .08, low + .08], [end - .08, high - .08], outer, uv_sizes, parts)
            if choice in ("brace_r", "cross"):
                _beam(edge, [start + .08, high - .08], [end - .08, low + .08], outer, uv_sizes, parts)


def _corners(level):
    """Yield only outward turns, preserving original contour indices."""
    outline = level["outline"]
    sign = 1 if level["ccw"] else -1
    for i, point in enumerate(outline):
        before, after = outline[i - 1], outline[(i + 1) % len(outline)]
        turn = ((point[0] - before[0]) * (after[1] - point[1])
                - (point[1] - before[1]) * (after[0] - point[0]))
        if sign * turn > 1e-8:
            yield i, point


def _rows(bottom, top, pitch):
    """Keep full-radius rows whose centers remain below the wall head."""
    index = 0
    while bottom + (index + .5) * pitch <= top + 1e-8:
        yield index, bottom + (index + .5) * pitch
        index += 1


def _log(builder, edge, left, right, height, outer, half):
    """Extrude four half-cylinder segments, or an eight-sided full log."""
    angles = [math.pi * index / 4 for index in range(5)] if half else [math.pi * index / 4 for index in range(8)]
    section = [(height + .14 * math.cos(angle), outer + .14 * math.sin(angle)) for angle in angles]
    _extrude(builder, [_point(edge, left, y, depth) for y, depth in section],
             [_point(edge, right, y, depth) for y, depth in section])


def _logs(level, style, full, uv_sizes, parts, roof_info=None):
    """Interrupt wall rows at apertures and alternate corner log directions."""
    number = level["level"]
    bottom = style.get("plinth_height_m", 0) if number == 0 else level["floor_y"]
    outer = wall_offsets(style, number)[1]
    ring = offset_ring(level["outline"], level["ccw"], outer)
    for row, height in _rows(bottom, level["top_y"], .28):
        if full and style.get("log_walls"):
            for edge in level["edges"]:
                left, right = _span(ring, edge, outer)
                holes = [dict(hole, y0=0, y1=1) for hole in edge["openings"]
                         if hole["y0"] < height + .14 and hole["y1"] > height - .14]
                for start, end, _, _ in _cells(left, right, 0, 1, holes, extra_s=detail_breaks(roof_info, number, edge, (outer,outer+.14))):
                    builder = _builder("log", "wall", uv_sizes)
                    _log(builder, edge, start, end, height, outer, True)
                    _append(parts, builder)
        if style.get("corners") != "log_ends":
            continue
        for i, _ in _corners(level):
            edge = level["edges"][i if row % 2 == 0 else (i - 1) % len(level["edges"])]
            left, right = _span(ring, edge, outer)
            start, end = (left - .35, left + .14) if row % 2 == 0 else (right - .14, right + .35)
            for left_piece, right_piece, _, _ in _cells(start, end, 0, 1, [],
                    extra_s=detail_breaks(roof_info, number, edge, (outer-.14,outer+.14))):
                builder = _builder("log_end", "wall", uv_sizes, protrudes=True)
                _log(builder, edge, left_piece, right_piece, height, outer, False)
                _append(parts, builder)


def _corner_details(facts, style, uv_sizes, parts, roof_info=None):
    """Build quoins on each storey or standalone ground-floor corner posts."""
    for level in facts["levels"]:
        number = level["level"]
        bottom = style.get("plinth_height_m", 0) if number == 0 else level["floor_y"]
        outer = wall_offsets(style, number)[1]
        ring = offset_ring(level["outline"], level["ccw"], outer)
        for i, _ in _corners(level):
            if style.get("corners") == "posts" and number == 0 and style.get("timber_frame", "none") == "none":
                edge = level["edges"][i]
                left, _ = _span(ring, edge, outer)
                _timber_block(edge, (left, left + .16, bottom, level["top_y"]),
                              outer, edge["openings"], uv_sizes, parts, roof_info, number)
            if style.get("corners") != "quoins":
                continue
            datum = style.get("plinth_height_m", 0)
            row = max(0, math.floor((bottom - datum) / .3))
            while datum + row * .3 < min(level["top_y"], facts["eaves_y"]) - 1e-5:
                low = max(bottom, datum + row * .3)
                high = min(datum + (row + 1) * .3, level["top_y"], facts["eaves_y"])
                for side, index in enumerate(((i - 1) % len(level["edges"]), i)):
                    edge = level["edges"][index]
                    left, right = _span(ring, edge, outer)
                    length = .5 if (row + side) % 2 == 0 else .3
                    start, end = (right - length, right) if side == 0 else (left, left + length)
                    for bounds in _cells(start, end, low, high, edge["openings"],
                            extra_s=detail_breaks(roof_info, number, edge, (outer,outer+.03))):
                        builder = _builder("quoin", "trim", uv_sizes)
                        _block(builder, edge, *bounds, outer, outer + .03)
                        _append(parts, builder)
                row += 1


def _crenels(outline, base, thickness, uv_sizes, parts):
    """Center .6 m merlons at 1.1 m pitch on an inward parapet ring."""
    ring = offset_ring(outline, _ring_ccw(outline), -thickness / 2)
    for first, second in zip(ring, ring[1:] + ring[:1]):
        length = math.dist(first, second)
        count = max(0, math.floor((length + .5) / 1.1))
        if not count:
            continue
        margin = (length - (count * .6 + (count - 1) * .5)) / 2
        yaw = -math.atan2(second[1] - first[1], second[0] - first[0])
        for i in range(count):
            fraction = (margin + .3 + i * 1.1) / length
            center = [first[0] + (second[0] - first[0]) * fraction, base + .3,
                      first[1] + (second[1] - first[1]) * fraction]
            builder = _builder("crenel", "wall", uv_sizes)
            builder.box(center, [.6, .6, thickness], yaw)
            _append(parts, builder)


def _tower_crenels(point, radius, base, thickness, uv_sizes, parts):
    """Space crown merlons by circumference independently of cylinder resolution."""
    center_radius = radius - thickness / 2
    count = max(1, math.floor(2 * math.pi * center_radius / 1.1))
    for i in range(count):
        angle = 2 * math.pi * i / count
        builder = _builder("crenel", "wall", uv_sizes, protrudes=True)
        builder.box([point[0] + center_radius * math.cos(angle), base + .3,
                     point[1] + center_radius * math.sin(angle)],
                    [.6, .6, thickness], -angle - math.pi / 2)
        _append(parts, builder)


def _towers(facts, style, desc, density, tier, uv_sizes, parts):
    """Keep a shared seeded silhouette with tier-specific cylinder resolution."""
    towers = style.get("towers", {})
    chance = min(1, towers.get("chance", 0) * (.5 + density))
    top_level = max(level["level"] for level in facts["levels"])
    candidates = []
    for level in sorted(facts["levels"], key=lambda item: -item["level"]):
        for i, point in _corners(level):
            if any(other is not level and _point_in_polygon(*point, other["outline"])
                   and polygon_distance(*point, other["outline"]) > .05
                   for other in facts["levels"]):
                continue
            if any(math.dist(point, candidate[2]) < .05 for candidate in candidates):
                continue
            candidates.append((level, i, point))
    sides = 16 if tier == "full" else 8
    for level, i, point in candidates:
        random = rng(desc.get("seed", 0), f"tower:{level['level']}:{i}")
        if random.random() >= chance:
            continue
        radius = random.uniform(*towers["radius_m"])
        top = (facts["eaves_y"] if level["level"] == top_level else level["top_y"]) + random.uniform(*towers["rise_m"])
        roof = random.choice(towers["roof"])
        builder = _builder("tower", "wall", uv_sizes, protrudes=True)
        builder.cylinder(point[0], point[1], -WALL_SINK_M, top, radius, sides)
        if roof == "cone":
            cap = _builder("roof", "roof", uv_sizes, protrudes=True)
            cap.cylinder(point[0], point[1], top, top + (radius + .2) * math.tan(math.radians(60)),
                         radius + .2, sides, r_top=0)
            _append(parts, cap)
        else:
            # A hollow parapet has radial merlons above a continuous wall ring.
            thickness = min(style["wall_thickness_m"], radius / 2)
            outer = [[point[0] + radius * math.cos(2 * math.pi * index / sides),
                      point[1] + radius * math.sin(2 * math.pi * index / sides)] for index in range(sides)]
            inner = [[point[0] + (radius - thickness) * math.cos(2 * math.pi * index / sides),
                      point[1] + (radius - thickness) * math.sin(2 * math.pi * index / sides)] for index in range(sides)]
            for index in range(sides):
                following = (index + 1) % sides
                builder.prism([outer[index], outer[following], inner[following], inner[index]], top, top + 1)
            _tower_crenels(point, radius, top + 1, thickness, uv_sizes, parts)
        _append(parts, builder)


def _roof_drop(level, edge, vertices, top_at, roof_info, style):
    """Return the rigid vertical drop needed below same-storey pitched roofs."""
    drop = 0.0
    for wing in (roof_info or {}).get("wings", []):
        if wing["level"] != level["level"]:
            continue
        samples = _detail_samples(wing, vertices)
        if wing["form"] == "tent":
            # Fan slopes need not equal the requested pyramid pitch.
            normals = [_normal(plane) for plane in wing["planes"]]
            underside_drop = max(.15*math.sqrt(sum(v*v for v in n))/abs(n[1]) for n in normals)
        else:
            underside_drop = .15 / math.cos(math.radians(wing["pitch_deg"]))
        for x,_,z in samples:
            height = roof_top_y(wing,x,z,style)
            if height is None:
                continue
            cap_top = top_at(x, z)
            drop = max(drop, cap_top-height+underside_drop+.02)
    return drop


def _porches(level, style, uv_sizes, parts, roof_info=None):
    """Attach a closed shed slab and two .12 m posts to each ground door."""
    outer = wall_offsets(style, 0)[1]
    for edge in level["edges"]:
        for hole in edge["openings"]:
            if hole["kind"] != "door":
                continue
            left, right = hole["s0"] - .6, hole["s1"] + .6
            low = hole["y1"] + .3
            porch_start = len(parts)
            builder = _builder("porch", "trim", uv_sizes, protrudes=True)
            for span in (left + .06, right - .06):
                _block(builder, edge, span - .06, span + .06, -WALL_SINK_M, low,
                       outer + 1.6 - .12, outer + 1.6)
            _append(parts, builder)
            cap = _builder("roof", "roof", uv_sizes, protrudes=True)
            # The lower surface's outer edge is the required y1 + .3 datum.
            corners = [(left, outer, low + .4), (right, outer, low + .4),
                       (right, outer + 1.6, low), (left, outer + 1.6, low)]
            _extrude(cap, [_point(edge, span, height, depth) for span, depth, height in corners],
                     [_point(edge, span, height + .12, depth) for span, depth, height in corners])
            _, normal = _axes(edge)
            drop = _roof_drop(level, edge, cap.part()["vertices"],
                              lambda x,z: low+.52-((x-edge["a"][0])*normal[0]
                                  +(z-edge["a"][1])*normal[1]-outer)*.25, roof_info, style)
            if low-drop < hole["y1"]+.05-1e-8:
                del parts[porch_start:]
                continue
            for part in parts[porch_start:]+[cap.part()]:
                for point in part["vertices"]:
                    # Post feet stay at ground while their heads follow the cap.
                    if part["tag"] == "porch":
                        point[1] = round(-WALL_SINK_M+(point[1]+WALL_SINK_M)*(low-drop+WALL_SINK_M)/(low+WALL_SINK_M),4)
                    else:
                        point[1] = round(point[1]-drop,4)
                part["detail_level"] = level["level"]
            _append(parts, cap)


def _canopies(level, style, uv_sizes, parts, roof_info):
    """Fit rigid entrance plates below the wall head and nearby roof undersides."""
    outer = wall_offsets(style, 0)[1]
    for edge in level["edges"]:
        for hole in edge["openings"]:
            if hole["kind"] != "door":
                continue
            low = min(hole["y1"]+.25, level["top_y"]-.15)
            builder = _builder("canopy", "trim", uv_sizes, protrudes=True)
            _block(builder, edge, hole["s0"]-.5, hole["s1"]+.5, low, low+.15, outer, outer+1.2)
            part = builder.part()
            drop = _roof_drop(level, edge, part["vertices"], lambda x,z: low+.15, roof_info, style)
            if low-drop < hole["y1"]+.05-1e-8:
                continue
            for point in part["vertices"]:
                point[1] = round(point[1]-drop,4)
            part["detail_level"] = level["level"]
            _append(parts, builder)


def _roof_units(facts, style, desc, roof_info, density, uv_sizes, parts):
    """Place housing first, then independently seeded nonoverlapping roof boxes."""
    if roof_info.get("form") != "flat":
        return
    top = next((t for t in roof_info.get("flat_tops", [])
                if t["level"] == roof_info["topmost_level"]), None)
    if top is None:
        return
    outline = next(l["outline"] for l in facts["levels"] if l["level"]==top["level"])
    xs,zs = zip(*outline)
    limits = [min(xs), max(xs), min(zs), max(zs)]
    occupied = []

    def fits(x,z,w,d,margin):
        corners = [(x+sx*w/2,z+sz*d/2) for sx,sz in ((-1,-1),(1,-1),(1,1),(-1,1))]
        return (_fully_covered(corners, outline)
                and all(_point_in_polygon(a,b,outline) and min(point_segment_distance(a,b,*c,*e) for c,e in
                        zip(outline,outline[1:]+outline[:1]))>=margin-1e-8
                    for a,b in corners)
                and not any(x+w/2>a and x-w/2<b and z+d/2>c and z-d/2<e
                            for a,b,c,e in occupied))

    def emit(tag,material,x,z,w,d,h):
        builder = _builder(tag,material,uv_sizes)
        builder.box([x,top["y"]+h/2,z],[w,h,d])
        _append(parts,builder)
        occupied.append((x-w/2,x+w/2,z-d/2,z+d/2))

    if style.get("roof_housing") and facts.get("elevator") is not None:
        x,z = facts["elevator"]
        if limits[1]-limits[0]>=3 and limits[3]-limits[2]>=3:
            x=max(limits[0]+1.5,min(limits[1]-1.5,x))
            z=max(limits[2]+1.5,min(limits[3]-1.5,z))
            if fits(x,z,2.4,2.4,.3):
                emit("housing","wall",x,z,2.4,2.4,2.6)
                cap=_builder("housing","trim",uv_sizes)
                cap.box([x,top["y"]+2.625,z],[2.4,.05,2.4])
                _append(parts,cap)
    minimum,maximum = style.get("rooftop_units",[0,0])
    for i in range(round(minimum+(maximum-minimum)*density)):
        random = rng(desc.get("seed",0),f"rooftop:{i}")
        w,d,h = random.uniform(.8,1.6),random.uniform(.8,1.6),random.uniform(.8,1.4)
        if limits[1]-limits[0]<2 or limits[3]-limits[2]<2:
            continue
        for _ in range(8):
            x,z = random.uniform(limits[0]+1,limits[1]-1),random.uniform(limits[2]+1,limits[3]-1)
            if fits(x,z,w,d,1):
                emit("rooftop","chimney",x,z,w,d,h)
                break


def build_ornaments(facts: Dict, style: Dict, desc: Dict, roof_info: Dict, *, tier: str,
                    uv_sizes: Optional[Dict[str, float]] = None,
                    resolved: frozenset[str] = frozenset()) -> List[Part]:
    """Build style ornaments while preserving silhouette details in both tiers."""
    if tier not in ("full", "low"):
        raise ValueError("tier must be full or low")
    uv_sizes = uv_sizes or {}
    density = desc.get("overrides", {}).get("ornament_density", .5)
    parts = []
    levels = sorted(facts["levels"], key=lambda level: level["level"])
    for level in levels:
        start = len(parts)
        timber = style.get("timber_frame", "none")
        if tier == "full" and (timber == "all" or timber == "upper" and (len(levels) == 1 or level["level"] != 0)):
            _timber(level, style, desc, density, uv_sizes, parts, roof_info, resolved, facts.get("storey_m"))
        if style.get("log_walls") or style.get("corners") == "log_ends":
            _logs(level, style, tier == "full", uv_sizes, parts, roof_info)
        if level["level"] == 0 and style.get("porch"):
            _porches(level, style, uv_sizes, parts, roof_info)
        if level["level"] == 0 and style.get("entrance_canopy") and not style.get("porch"):
            _canopies(level, style, uv_sizes, parts, roof_info)
        clipped = []
        for part in parts[start:]:
            if part["tag"] in ("porch", "roof", "canopy"):
                clipped.append(part)
                continue
            result = clip_detail(part, level["level"], roof_info, style,
                                 diagonal=part.pop("diagonal", False))
            if result is not None:
                clipped.append(result)
        parts[start:] = clipped
    if tier == "full":
        for level in levels:
            corners = []
            _corner_details({**facts, "levels": [level]}, style, uv_sizes, corners, roof_info)
            for part in corners:
                result = clip_detail(part, level["level"], roof_info, style)
                if result is not None:
                    parts.append(result)
    if style.get("crenellations"):
        for flat in roof_info.get("flat_tops", []):
            if flat.get("parapet"):
                _crenels(flat["outline"], flat["y"] + 1, style["wall_thickness_m"], uv_sizes, parts)
    _roof_units(facts, style, desc, roof_info, density, uv_sizes, parts)
    _towers(facts, style, desc, density, tier, uv_sizes, parts)
    return parts
