"""Deterministic blind-window dimensions and facade-edge raster."""
import math
from statistics import median
from typing import Optional

from app.core.hull_mesh import rng


def blind_dims(style, seed):
    """Draw one building-wide bay, width and height, in that order."""
    random = rng(seed, "blind_windows")
    config = style["blind_windows"]
    return {**{key: random.uniform(*config[key + "_m"])
               for key in ("bay", "width", "height")}, "sill": config["sill_m"]}


def blind_raster(lo, hi, bay, width):
    """Center windows in equal fields of the supplied outer span."""
    count = math.floor((hi - lo) / bay)
    if count <= 0:
        return []
    field = (hi - lo) / count
    width = min(width, field - .3)
    if width <= 0:
        return []
    return [(lo + (i + .5) * field - width / 2,
             lo + (i + .5) * field + width / 2) for i in range(count)]


def blind_windows(level, edge, style, seed, lo, hi):
    """Return blind aperture metadata clipped to the outside wall span."""
    dims = blind_dims(style, seed)
    bottom = level["floor_y"] + dims["sill"]
    if level["level"] == 0:
        bottom = max(bottom, style.get("plinth_height_m", 0))
    top = min(bottom + dims["height"], level["top_y"] - .25)
    if top <= bottom:
        return []
    return [dict(kind="window", blind=True, index=i, s0=max(lo, left), s1=min(hi, right),
                 y0=bottom, y1=top)
            for i, (left, right) in enumerate(blind_raster(lo, hi, dims["bay"], dims["width"]))]


def storey_window_dims(level) -> Optional[dict]:
    """Use independent medians of real window width, sill and height."""
    windows = [h for edge in level["edges"] for h in edge["openings"]
               if h["kind"] == "window" and not h.get("blind", False)]
    if not windows:
        return None
    return dict(width=median(h["s1"]-h["s0"] for h in windows),
                sill=median(h["y0"]-level["floor_y"] for h in windows),
                height=median(h["y1"]-h["y0"] for h in windows))


def wall_blind_windows(level, edge, dims, bay, lo, hi, roof_tops):
    """Drop unsafe raster slots; roof_tops(s) returns lower roof heights.

    A slot in front of a real room (``edge["rooms"]``) drops too: blind
    windows fill only corridor and empty stretches (ruling 2026-10-21).

    dims carries the style plinth height in addition to the storey dimensions.
    Unlike filler windows, real-storey windows retain the supplied height.
    """
    bottom = level["floor_y"] + dims["sill"]
    top = bottom + dims["height"]
    if (top <= bottom
            or (level["level"] == 0 and bottom < dims.get("plinth", 0)+.1)):
        return []
    real = [h for h in edge["openings"] if not h.get("blind", False)]
    result = []
    for i, (left, right) in enumerate(blind_raster(lo, hi, bay, dims["width"])):
        if left < lo+.6 or right > hi-.6:
            continue
        # A real room stands behind this stretch (hull_facts._room_spans).
        if any(left < r1 and right > r0 for r0, r1 in edge.get("rooms", ())):
            continue
        if any(h["y0"] < top and h["y1"] > bottom
               and left < h["s1"]+.5 and right > h["s0"]-.5 for h in real):
            continue
        if any(height is not None and height > bottom-.1
               for height in roof_tops((left+right)/2)):
            continue
        result.append(dict(kind="window", blind=True, index=i, s0=left, s1=right,
                           y0=bottom, y1=top))
    return result


def module_bays(span, storey_m):
    """Choose the least distorted square fields, preferring fewer on ties."""
    if span < .75*storey_m:
        return 0
    lower = max(1, math.floor(span/storey_m))
    return min((lower, lower+1), key=lambda n: (abs(span/n-storey_m), n))


def mullions(s0, s1):
    """Return evenly spaced centres for wide-window vertical bars."""
    width = s1-s0
    if width <= 1.8:
        return []
    fields = math.ceil(width/1.6)
    return [s0+width*i/fields for i in range(1,fields)]


def module_count(level, style, resolved, span, storey_m):
    """Return module bays only on eligible, resolved facade edges."""
    return (module_bays(span, storey_m) if level.get("filler", False)
            and style.get("materials", {}).get("facade_module")
            and "facade_module" in resolved else 0)


def street_edges(level) -> set[int]:
    """Select ground exterior entrances, falling back to the longest edge."""
    if level['level'] != 0 or not level['edges']:
        return set()
    entrances = {edge['index'] for edge in level['edges']
                 if any(h['kind'] in ('door','passage') for h in edge['openings'])}
    return entrances or {max(level['edges'], key=lambda edge: edge['length'])['index']}


def shop_band(level, edge):
    """Return sign limits even when the available band is too short to emit."""
    highest = max((h['y1'] for h in edge['openings']), default=level['floor_y'])
    bottom = max(highest+.15, level['top_y']-.75)
    return bottom, min(bottom+.5, level['top_y']-.05)
