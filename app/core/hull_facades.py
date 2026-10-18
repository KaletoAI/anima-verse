"""Deterministic blind-window dimensions and facade-edge raster."""
import math

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
