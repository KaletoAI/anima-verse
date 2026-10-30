"""Opt-in facade balconies built from prepared window openings."""
import math

from app.core import hull_facades, hull_walls
from app.core.hull_mesh import Part, PartBuilder


def front_edges(facts, level):
    """Use the house frame's +z normal, otherwise ground street edges."""
    if facts.get('location_id', '').startswith('house-unit-'):
        return {e['index'] for e in level['edges'] if e['normal'][1] > 1-1e-6}
    ground = next((lv for lv in facts['levels'] if lv['level'] == 0), level)
    return hull_facades.street_edges(ground)


def balcony_bays(level: dict, edge: dict, spec: dict, lo: float, hi: float) -> list[tuple[float, float]]:
    """Return slab intervals, expanding each actual window by .2 m per side."""
    if level['level'] not in spec['storeys']:
        return []
    if spec['layout'] == 'continuous':
        return [(lo+.3, hi-.3)] if hi-lo > .6 else []
    return [(max(lo, h['s0']-.2), min(hi, h['s1']+.2))
            for h in edge['openings'] if h['kind'] == 'window'
            and min(hi, h['s1']+.2) > max(lo, h['s0']-.2)]


def build_balconies(facts: dict, style: dict, desc: dict, *, tier: str, uv_sizes) -> list[Part]:
    """Build slabs and three-sided railings, clipped at party planes."""
    spec = desc.get('overrides', {}).get('balconies')
    if not spec:
        return []
    parts = []
    for level in facts['levels']:
        parties = hull_walls.party_edges(level, desc)
        for edge in level['edges']:
            if edge['index'] not in front_edges(facts, level) or edge in parties:
                continue
            u, n = hull_walls._axes(edge)
            outer = hull_walls.wall_offsets(style, level['level'])[1]
            floor = level['floor_y']
            depth = spec['depth_m']
            bays = balcony_bays(level, edge, spec, 0, edge['length'])
            for left, right in bays:
                if spec['layout'] == 'continuous':
                    # A party corner reaches the join rather than stopping short.
                    for party in parties:
                        if edge['a'] in (party['a'], party['b']):
                            left = 0
                        if edge['b'] in (party['a'], party['b']):
                            right = edge['length']
                built = []

                def box(material, s0, s1, d0, d1, y0, y1):
                    b = PartBuilder('balcony', material, protrudes=True,
                                    uv_size_m=(uv_sizes or {}).get(material, 2.0))
                    ring = [[edge['a'][k]+u[k]*s+n[k]*d for k in range(2)]
                            for s, d in ((s0,d0),(s1,d0),(s1,d1),(s0,d1))]
                    b.prism(ring, y0, y1)
                    built.append(b.part())

                box('trim', left, right, outer, outer+depth, floor-.15, floor)
                # Keep every rail inside the slab footprint and exactly 1 m high.
                width = .12 if spec['railing'] == 'solid' else .05
                segments = [(left,right,outer+depth-width,outer+depth),
                            (left,left+width,outer,outer+depth-width),
                            (right-width,right,outer,outer+depth-width)]
                for s0,s1,d0,d1 in segments:
                    if spec['railing'] == 'solid':
                        box('trim',s0,s1,d0,d1,floor,floor+1)
                        continue
                    box('window_frame',s0,s1,d0,d1,floor+.95,floor+1)
                    along = s1-s0 >= d1-d0
                    span = s1-s0 if along else d1-d0
                    count = max(1, math.ceil((span-width)/1.0))
                    for i in range(count+1):
                        position = max(0,span-width)*i/count
                        ps = s0+position if along else s0
                        pd = d0 if along else d0+position
                        box('window_frame',ps,ps+width,pd,pd+width,floor,floor+.95)
                    if spec['railing'] == 'glass':
                        if along:
                            box('glass',s0+width,s1-width,(d0+d1)/2-.01,(d0+d1)/2+.01,floor+.05,floor+.95)
                        else:
                            box('glass',(s0+s1)/2-.01,(s0+s1)/2+.01,d0+width,d1-width,floor+.05,floor+.95)
                parts.extend(hull_walls.clip_party_parts(built, parties))
    return parts
