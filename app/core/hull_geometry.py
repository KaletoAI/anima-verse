"""Assemble deterministic hull tiers with cutout metadata and vertex shades."""
from copy import deepcopy
import math
from typing import Any, Dict, List, Optional, Tuple

from app.core import hull_balconies, hull_facades, hull_facts, hull_mesh, hull_ornaments, hull_roofs, hull_walls
from app.core.hull_mesh import Part
from app.core.world_geometry import polygon_distance

TRI_BUDGET = {"full": 90000, "low": 12000}
_WEATHERED_MATERIALS = {"wall", "wall_ground", "plinth", "trim", "chimney"}
_EXTREMES = (("min", 0), ("max", 0), ("min", 2), ("max", 2), ("min", 1))
_TOLERANCE = 1e-4


def cutout_padding_m(style: Dict) -> float:
    """Return the wall, jetty and facade projection allowance in metres."""
    projection = 0.15 if style.get("log_walls") else 0.06
    return style["wall_thickness_m"] + style.get("jetty_m", 0) + projection + 0.05


def prepare_facts(facts: Dict, style: Dict, desc: Dict, resolved: frozenset[str]) -> Dict:
    """Copy facts, extend storeys and share blind openings with every builder."""
    prepared = hull_facts.with_storeys(facts, desc.get("overrides", {}).get("storeys_total", 0))
    balcony = desc.get("overrides", {}).get("balconies")
    if balcony:
        for level in prepared["levels"]:
            if level["level"] in balcony["storeys"]:
                for edge in level["edges"]:
                    if (edge["index"] in hull_balconies.front_edges(prepared, level)
                            and edge not in hull_walls.party_edges(level, desc)):
                        edge["balcony_openings"] = True
    for level in prepared["levels"]:
        for edge in hull_walls.party_edges(level, desc):
            edge["openings"] = []
        if not level.get("filler", False):
            continue
        outer = hull_walls.wall_offsets(style, level["level"])[1]
        ring = hull_mesh.offset_ring(level["outline"], level["ccw"], outer)
        for edge in level["edges"]:
            if edge in hull_walls.party_edges(level, desc):
                continue
            lo, hi = hull_walls._span(ring, edge, outer)
            module = (0 if edge.get("balcony_openings") else hull_facades.module_count(
                level, style, resolved, hi-lo, prepared["storey_m"]))
            edge["openings"] = ([] if module else
                                hull_facades.blind_windows(level, edge, style, desc.get("seed", 0), lo, hi))
    if desc.get("overrides", {}).get("blind_windows", False):
        _, roof_info = hull_roofs.build_roofs(prepared, style, desc, tier="full")
        fallback = hull_facades.blind_dims(style, desc.get("seed", 0))
        for level in prepared["levels"]:
            if level.get("filler", False):
                continue
            dims = dict(hull_facades.storey_window_dims(level) or fallback,
                        plinth=style.get("plinth_height_m", 0))
            outer = hull_walls.wall_offsets(style, level["level"])[1]
            ring = hull_mesh.offset_ring(level["outline"], level["ccw"], outer)
            lower = [wing for wing in roof_info["wings"] if wing["level"] < level["level"]]
            streets = (hull_facades.street_edges(level)
                       if desc.get("overrides", {}).get("shopfront") else set())
            for edge in level["edges"]:
                if edge["index"] in streets or edge in hull_walls.party_edges(level, desc):
                    continue
                lo, hi = hull_walls._span(ring, edge, outer)
                u, n = hull_walls._axes(edge)

                def roof_tops(s):
                    x, z = [edge["a"][k]+u[k]*s+n[k]*outer for k in range(2)]
                    return [hull_roofs.roof_top_y(wing, x, z, style) for wing in lower]

                edge["openings"].extend(hull_facades.wall_blind_windows(
                    level, edge, dims, fallback["bay"], lo, hi, roof_tops))
    if balcony:
        for level in prepared["levels"]:
            for edge in level["edges"]:
                if (edge["index"] not in hull_balconies.front_edges(prepared, level)
                        or edge in hull_walls.party_edges(level, desc)):
                    continue
                bays = hull_balconies.balcony_bays(level, edge, balcony, 0, edge["length"])
                for opening in edge["openings"]:
                    if opening["kind"] == "window" and any(
                            lo <= (opening["s0"]+opening["s1"])/2 <= hi for lo, hi in bays):
                        opening["y0"] = level["floor_y"]
    return prepared


def _build_parts(facts: Dict, style: Dict, desc: Dict, tier: str,
                 uv_sizes: Optional[Dict[str, float]], resolved: frozenset[str]) -> Tuple[List[Part], Dict]:
    """Build the dependent roof and ornament payloads in stable order."""
    roofs, roof_info = hull_roofs.build_roofs(facts, style, desc, tier=tier, uv_sizes=uv_sizes)
    parts = hull_walls.build_walls(facts, style, desc, tier=tier, uv_sizes=uv_sizes, roof_info=roof_info, resolved=resolved)
    parts.extend(roofs)
    ornaments = hull_ornaments.build_ornaments(
        facts, style, desc, roof_info, tier=tier, uv_sizes=uv_sizes, resolved=resolved)
    for level in facts['levels']:
        ornaments = hull_walls.clip_party_parts(
            ornaments, hull_walls.party_edges(level, desc), ornaments=True)
    parts.extend(ornaments)
    parts.extend(hull_balconies.build_balconies(facts, style, desc, tier=tier, uv_sizes=uv_sizes))
    return parts, roof_info


def _preserve_extremes(parts: List[Part], full_parts: List[Part]) -> None:
    """Copy full parts reaching extrema absent from the original low tier."""
    full_bounds, low_bounds = hull_mesh.bounds(full_parts), hull_mesh.bounds(parts)
    missing = [(key, axis) for key, axis in _EXTREMES
               if abs(full_bounds[key][axis] - low_bounds[key][axis]) > _TOLERANCE]
    for part in full_parts:
        if any(abs(point[axis] - full_bounds[key][axis]) <= _TOLERANCE
               for key, axis in missing for point in part["vertices"]):
            parts.append(deepcopy(part))


def _smoothstep(start: float, end: float, value: float) -> float:
    position = max(0.0, min(1.0, (value - start) / (end - start)))
    return position * position * (3 - 2 * position)


def _geometry_padding_m(parts: List[Part], facts: Dict, style: Dict) -> float:
    """Cover full-tier cuttable vertices with a centimetre-rounded margin."""
    outlines = [level["outline"] for level in facts["levels"]]
    maximum_distance = max(
        (min(polygon_distance(x, z, outline) for outline in outlines)
         for part in parts if not part["protrudes"] for x, _, z in part["vertices"]),
        default=0.0)
    return math.ceil((max(cutout_padding_m(style), maximum_distance) + 0.02) * 100) / 100


def _finish_parts(parts: List[Part], facts: Dict, style: Dict) -> None:
    """Apply weathering shades while preserving builder protrusion flags."""
    weathering = style.get("weathering", 0)
    eaves_y = facts["eaves_y"]
    for part in parts:
        part["colors"] = [
            [1 - weathering * 0.25 * (1 - _smoothstep(0, 1.5, part["vertices"][index][1]))
             - weathering * 0.12 * _smoothstep(eaves_y - 0.8, eaves_y, part["vertices"][index][1])
             if (part["material"] in _WEATHERED_MATERIALS or part["material"].startswith("wall_l")) else 1.0 for index in face]
            for face in part["faces"]
        ]


def build_hull(facts: Dict, style: Dict, desc: Dict, *, tier: str,
               uv_sizes: Optional[Dict[str, float]] = None,
               resolved: frozenset[str] = frozenset()) -> Dict[str, Any]:
    """Build one hull tier, preserving its footprint and enforcing its budget."""
    if tier not in TRI_BUDGET:
        raise ValueError("tier must be full or low")
    facts = prepare_facts(facts, style, desc, resolved)
    parts, roof_info = _build_parts(facts, style, desc, tier, uv_sizes, resolved)
    full_parts = parts
    if tier == "low":
        full_parts, _ = _build_parts(facts, style, desc, "full", uv_sizes, resolved)
        _preserve_extremes(parts, full_parts)
    padding = _geometry_padding_m(full_parts, facts, style)
    _finish_parts(parts, facts, style)
    triangles = hull_mesh.tri_count(parts)
    if triangles > TRI_BUDGET[tier]:
        raise ValueError(f"{tier} triangle budget exceeded: {triangles} > {TRI_BUDGET[tier]}")
    return {"parts": parts, "bounds": hull_mesh.bounds(parts), "tris": triangles,
            "padding_m": padding, "materials": sorted({part["material"] for part in parts}),
            "roof": roof_info}


def fit_budget(facts: Dict, style: Dict, desc: Dict, uv_sizes=None,
               resolved: frozenset[str] = frozenset()) -> Dict:
    """Fit both tiers using the same density, keeping the caller's description."""
    facts = prepare_facts(facts, style, desc, resolved)
    density = desc.get("overrides", {}).get("ornament_density", .5)
    for value in (density, density/2, 0):
        candidate = desc if value == density else deepcopy(desc)
        if candidate is not desc:
            candidate.setdefault("overrides", {})["ornament_density"] = value
        fits = True
        full_parts = []
        for tier in ("full", "low"):
            parts, _ = _build_parts(facts, style, candidate, tier, uv_sizes, resolved)
            if tier == "full":
                full_parts = parts
            else:
                _preserve_extremes(parts, full_parts)
            fits = fits and hull_mesh.tri_count(parts) <= TRI_BUDGET[tier]
        if fits:
            return candidate
    raise ValueError("hull too large")
