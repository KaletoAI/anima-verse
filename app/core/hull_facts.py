"""Building footprints and contour holes read from the scene composer's walls."""
from copy import deepcopy
import hashlib
import json
import math
from typing import Any, Dict

from app.core import scene_recipe as sr
from app.core.location_model3d import derive_plan_width_m


def _edge_openings(walls, level, a, frame, floor, height):
    """Complement the union of solid wall rectangles within one facade band."""
    ux, uz, length = frame
    ceiling = floor + height
    solid, leaves = [], []
    breaks = {0.0, length}
    for wall in walls:
        if wall['level'] != level:
            continue
        span = sr._colinear_span(a, ux, uz, length, wall['from'], wall['to'])
        if span is None:
            continue
        if wall.get('leaf'):
            leaves.append((*span, wall.get('door_style', '')))
            continue
        if wall.get('glass'):
            continue
        lo = max(floor, wall['base_y'])
        hi = min(ceiling, wall['base_y'] + wall['height'])
        if hi <= lo:
            continue
        s0, s1 = span
        solid.append((s0, s1, lo, hi))
        breaks.update(span)

    holes = []
    active = []
    points = sorted(breaks)
    for s0, s1 in zip(points, points[1:]):
        middle = (s0 + s1) / 2
        bands = sorted((lo, hi) for start, end, lo, hi in solid
                       if start <= middle <= end)
        cursor = floor
        gaps = []
        for lo, hi in bands:
            if lo - cursor >= 0.05 - 1e-9:
                gaps.append((cursor, lo))
            cursor = max(cursor, hi)
        if ceiling - cursor >= 0.05 - 1e-9:
            gaps.append((cursor, ceiling))
        following = []
        for lo, hi in gaps:
            previous = next((h for h in active
                             if abs(h['y0'] - lo) <= 1e-3
                             and abs(h['y1'] - hi) <= 1e-3), None)
            if previous is None:
                previous = dict(s0=s0, s1=s1, y0=lo, y1=hi)
                holes.append(previous)
            else:
                previous['s1'] = s1
            following.append(previous)
        active = following

    result = []
    for hole in holes:
        if hole['s1'] - hole['s0'] < sr.MIN_WALL_PIECE_M:
            continue
        kind = 'window' if hole['y0'] > floor + 0.05 else (
            'door' if any(min(end, hole['s1']) > max(start, hole['s0'])
                          for start, end, _style in leaves) else 'passage')
        door_style = next((style for start,end,style in leaves
                           if min(end,hole['s1']) > max(start,hole['s0'])), '')
        result.append({**({'door_style': door_style} if kind == 'door' else {}),
                       **{key: sr._r(value) for key, value in hole.items()},
                       'kind': kind})
    return sorted(result, key=lambda h: (h['s0'], h['y0'], h['s1'], h['y1']))


def _room_spans(walls, level, a, frame):
    """Merged [s0, s1] stretches of one contour edge that a real room's own
    wall runs along. Blind windows go only where no room stands behind the
    wall, i.e. in front of a storey corridor or an empty stretch (user ruling
    2026-10-21): a room's author decided its windows there."""
    ux, uz, length = frame
    spans = sorted(span for wall in walls
                   if wall['level'] == level and wall.get('room_id')
                   and not wall.get('glass') and not wall.get('leaf')
                   for span in [sr._colinear_span(a, ux, uz, length, wall['from'], wall['to'])]
                   if span is not None)
    merged = []
    for s0, s1 in spans:
        if merged and s0 <= merged[-1][1] + 1e-3:
            merged[-1][1] = max(merged[-1][1], s1)
        else:
            merged.append([s0, s1])
    return [[sr._r(s0), sr._r(s1)] for s0, s1 in merged]


def _door_meta(description: Any) -> Any:
    """The door-relevant part of a hull description, shaped like the client meta."""
    if not isinstance(description, dict) or not description.get('style'):
        return None
    from app.core.hull_styles import get_style
    overrides = description.get('overrides') or {}
    return {'hull_style': get_style(str(description['style'])) or {},
            'hull_shopfront': overrides.get('shopfront') is True,
            'hull_door_color': overrides.get('door_color') or '',
            'hull_frame_color': overrides.get('frame_color') or '',
            'hull_ornament_density': overrides.get('ornament_density', .5)}


def hull_facts(location: Dict[str, Any], location_id: str = '', *,
               description: Any = None) -> Dict[str, Any]:
    """Return rounded per-storey hull facts and their geometry and door-style fingerprint.

    A supplied dict is composed directly. Passing None with an id loads that
    location lazily; missing records return ``not_found``. ``description`` is
    the hull the facts are for (the one being built, or the active one when
    checking staleness): its style and shopfront pick the fallback doors.
    """
    if location is None and location_id:
        from app.models.world import get_location_by_id
        location = get_location_by_id(location_id)
        if location is None:
            return dict(ok=False, error='not_found', location_id=location_id)
    location = location or {}
    loc_id = location_id or str(location.get('id') or '')
    map3d = location.get('map3d') or {}
    width = derive_plan_width_m(loc_id, map3d)
    scene = sr.compose_scene(location, plan_width_m=width,
                             door_meta=_door_meta(description))
    extent, _, storey = sr.derive_scalars(map3d, width)
    levels = []
    used = {entry['level'] for entry in scene['levels']}
    for level in range(0, max(used, default=-1) + 1):
        filler = level not in used
        outline = sr._outline_world(map3d, level)
        if level < 0 or len(outline) < 3:
            continue
        floor = sr.storey_floor_y(level, storey)
        ccw = sr._ring_ccw(outline)
        edges = []
        for index, a in enumerate(outline):
            b = outline[(index + 1) % len(outline)]
            frame = sr._edge_frame(a, b)
            if frame is None:
                continue
            ux, uz, length = frame
            normal = (uz, -ux) if ccw else (-uz, ux)
            edges.append(dict(index=index, a=[sr._r(v) for v in a],
                              b=[sr._r(v) for v in b], length=sr._r(length),
                              normal=[sr._r(v) for v in normal],
                              openings=[] if filler else _edge_openings(scene['walls'], level, a,
                                                      frame, floor,
                                                      sr._wall_height(storey)),
                              rooms=[] if filler else _room_spans(scene['walls'], level, a, frame)))
        levels.append(dict(level=level, filler=filler, floor_y=sr._r(floor),
                           top_y=sr._r(floor + sr._wall_height(storey)),
                           outline=[[sr._r(v) for v in p] for p in outline],
                           ccw=ccw, edges=edges))
    if not levels:
        return dict(ok=False, error='no_outline', location_id=loc_id)
    for current, following in zip(levels, levels[1:]):
        current['top_y'] = following['floor_y']
    boundary = sr._boundary_local(map3d, extent)
    center = [sr._r((min(p[i] for p in boundary) + max(p[i] for p in boundary))/2)
              for i in (0, 1)]
    encoded = json.dumps(dict(storey_m=sr._r(storey),
                              levels=[{k: v for k, v in level.items() if k != 'filler'}
                                      for level in levels]),
                         sort_keys=True, separators=(',', ':'))
    lift = map3d.get('elevator')
    elevator = [sr._num(v, float('nan')) for v in lift] if isinstance(lift, (list, tuple)) and len(lift) == 2 else None
    if elevator is not None and not all(math.isfinite(v) for v in elevator):
        elevator = None
    return dict(ok=True, error='', location_id=loc_id, storey_m=sr._r(storey),
                eaves_y=levels[-1]['top_y'], boundary_center=center,
                elevator=elevator,
                fingerprint=hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:16],
                levels=levels)


def with_storeys(facts: dict, total: int) -> dict:
    """Copy facts and append facade storeys without changing their fingerprint."""
    result = deepcopy(facts)
    levels = result['levels']
    if total <= len(levels):
        return result
    storey = result['storey_m']
    template = deepcopy(levels[-1])
    for level in range(template['level'] + 1, total):
        floor = sr._r(sr.storey_floor_y(level, storey))
        levels[-1]['top_y'] = floor
        following = deepcopy(template)
        following.update(level=level, floor_y=floor, filler=True,
                         top_y=sr._r(floor + sr._wall_height(storey)))
        for edge in following['edges']:
            edge['openings'] = []
        levels.append(following)
    result['eaves_y'] = levels[-1]['top_y']
    return result
