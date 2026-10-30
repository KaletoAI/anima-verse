"""House specifications and in-memory locations for the existing hull pipeline."""
from copy import deepcopy
import math
from typing import Any

from app.core import door_styles, hull_styles, surface_textures
from app.core.hull_util import tone

HOUSE_DEFAULTS: dict = {
    "style": "steinhaus", "storeys": 2, "storey_m": 3.0, "units": 1,
    "unit_overrides": [], "wall": "", "door": {"style": "", "at": 0.5},
    "balconies": None, "overrides": {},
}


def _number(value, low, high, default):
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return default
    return max(low, min(high, value)) if math.isfinite(value) else default


def _dict(value):
    return value if isinstance(value, dict) else {}


def _choice(value, choices, default):
    return value if isinstance(value, str) and value in choices else default


def validate_house_spec(raw: Any, footprint_m: tuple[float, float]) -> dict:
    """Clamp a house spec; dimensions remain external to the stored spec."""
    width, depth = footprint_m
    if not (math.isfinite(width) and math.isfinite(depth) and width > 0 and depth > 0):
        raise ValueError("footprint")
    raw = _dict(raw)
    result = deepcopy(HOUSE_DEFAULTS)
    desc = hull_styles.validate_description(raw, hull_styles.load_styles())
    result.update(desc)
    result['storeys'] = int(_number(raw.get('storeys'), 1, 12, 2))
    result['storey_m'] = _number(raw.get('storey_m'), 2.6, 4.5, 3.0)
    result['units'] = min(int(_number(raw.get('units'), 1, 8, 1)),
                          max(1, math.floor(width / 2.5)))
    entries = raw.get('unit_overrides')
    entries = entries if isinstance(entries, list) else []
    result['unit_overrides'] = []
    for index in range(result['units']):
        entry = _dict(entries[index]) if index < len(entries) else {}
        result['unit_overrides'].append({key: colour for key in
            ('tint', 'door_color', 'roof_tint') if (colour := tone(entry.get(key), ''))})
    wall = raw.get('wall')
    result['wall'] = surface_textures.safe_kind(wall) if isinstance(wall, str) else ''
    door = _dict(raw.get('door'))
    result['door'] = {
        'style': _choice(door.get('style'), door_styles.load_door_styles(), ''),
        'at': _number(door.get('at'), .1, .9, .5),
    }
    balcony = _dict(raw.get('balconies'))
    if balcony and balcony.get('edge', 'front') == 'front':
        levels = balcony.get('storeys')
        levels = levels if isinstance(levels, list) else []
        result['balconies'] = {
            'edge': 'front',
            'storeys': sorted({lv for lv in levels if type(lv) is int
                               and 1 <= lv < result['storeys']}),
            'layout': _choice(balcony.get('layout'), ('per_window', 'continuous'), 'per_window'),
            'depth_m': _number(balcony.get('depth_m'), .5, 1.6, .9),
            'railing': _choice(balcony.get('railing'), ('iron', 'solid', 'glass'), 'iron'),
        }
    return result


def synthetic_locations(spec: dict, footprint_m: tuple[float, float]) -> list[dict]:
    """Split the centred footprint along x; edge 2 always faces +z.

    Corridor rooms use the server's ensure_floor_rooms shape. Their extent is
    the complement of ordinary rooms within the map outline, so no layout is
    needed to cover the whole footprint.
    """
    width, depth = footprint_m
    count = spec['units']
    locations = []
    for index in range(count):
        left = -width / 2 + index * width / count
        right = -width / 2 + (index + 1) * width / count
        opening = dict(type='door', level=0, edge=2, at=spec['door']['at'],
                       width_m=1.0, height_m=2.1)
        if spec['door']['style']:
            opening['door_style'] = spec['door']['style']
        map3d = dict(outline=[[left,-depth/2], [right,-depth/2],
                              [right,depth/2], [left,depth/2]],
                     storey_height_m=spec['storey_m'], hull_openings=[opening])
        if spec['wall']:
            map3d['wall_kind'] = spec['wall']
        locations.append(dict(id=f'house-unit-{index}', name=f'House unit {index}',
            map3d=map3d, rooms=[dict(id='__floor__0', level=0, name='',
                                   description='', activities=[])]))
    return locations


def unit_description(spec: dict, index: int) -> dict:
    """Return RAW overrides, including fields validated by later hull tasks."""
    if not 0 <= index < spec['units']:
        raise IndexError(index)
    overrides = deepcopy(spec['overrides'])
    overrides.update(storeys_total=spec['storeys'], blind_windows=True, blind_recess=True)
    overrides.update(deepcopy(spec['unit_overrides'][index]))
    # Rectangle edges 1 and 3 face +x and -x respectively.
    overrides['party_edges'] = ([3] if index > 0 else []) + (
        [1] if index < spec['units'] - 1 else [])
    if spec['units'] > 1:
        overrides['ridge'] = 'width'
    if spec['balconies'] is not None:
        overrides['balconies'] = deepcopy(spec['balconies'])
    return dict(style=spec['style'], seed=spec.get('seed', 0) + index, overrides=overrides)
