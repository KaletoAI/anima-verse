"""Wall shells and aperture details built exclusively from hull facts."""
import math
from typing import Dict, List, Optional, Tuple
from app.core.door_geometry import build_door, leaves_for
from app.core.door_styles import load_door_styles
from app.core.hull_facades import module_count, mullions, street_edges, shop_band
from app.core.hull_mesh import Part, PartBuilder, offset_ring, rng, _normal
from app.core.scene_recipe import WALL_THICKNESS, WALL_SINK_M


def wall_offsets(style: Dict, level: int) -> Tuple[float, float]:
    inner = WALL_THICKNESS/2 + 0.005
    outer = inner + style['wall_thickness_m']
    if level >= 1 and style.get('timber_frame', 'none') != 'none':
        outer += style.get('jetty_m', 0)
    return inner, outer


def door_style_id(hole, level, style, desc):
    """Keep doorway resolution; prop leaves use this hull's exterior style."""
    return hole.get('door_style') or style.get(
        'shop_door_style' if level == 0 and desc.get('overrides', {}).get('shopfront')
        else 'door_style', 'panel')


def used_door_styles(facts, style, desc):
    return sorted({door_style_id(h, level['level'], style, desc)
                   for level in facts['levels'] for edge in level['edges']
                   for h in edge['openings'] if h['kind'] == 'door' and not h.get('blind')})


def _cells(s0, s1, y0, y1, holes, extra_y=(), extra_s=()):
    """Tile the complement of the union of clipped aperture rectangles."""
    if s1 <= s0 or y1 <= y0:
        return
    xs = sorted({s0, s1, *(v for v in extra_s if s0 < v < s1), *(max(s0, min(s1, h[k])) for h in holes for k in ('s0','s1'))})
    ys = sorted({y0, y1, *(v for v in extra_y if y0 < v < y1),
                 *(max(y0, min(y1, h[k])) for h in holes for k in ('y0','y1'))})
    for a,b in zip(xs, xs[1:]):
        for c,d in zip(ys, ys[1:]):
            if (b-a)*(d-c) < 1e-6:
                continue
            x,y = (a+b)/2, (c+d)/2
            if not any(h['s0'] < x < h['s1'] and h['y0'] < y < h['y1'] for h in holes):
                yield a,b,c,d


def _axes(edge):
    """Use the edge tangent to remove rounding drift from supplied normals."""
    a,b = edge['a'],edge['b']
    length = math.dist(a,b)
    u = [(b[k]-a[k])/length for k in range(2)]
    n = [u[1],-u[0]]
    if sum(n[k]*edge['normal'][k] for k in range(2)) < 0:
        n = [-v for v in n]
    return u,n


def _on_edge(points, edge, distance):
    _,n = _axes(edge)
    return all(abs(sum((p[k]-edge['a'][k])*n[k] for k in range(2))-distance) < 3e-4
               for p in points)


def _span(ring, edge, distance):
    a = edge['a']
    u,n = _axes(edge)
    ss = [sum((p[k]-a[k])*u[k] for k in range(2)) for p in ring
          if abs(sum((p[k]-a[k])*n[k] for k in range(2))-distance) < 3e-4]
    return min(ss),max(ss)


def build_walls(facts: Dict, style: Dict, desc: Dict, *, tier: str,
                uv_sizes: Optional[Dict[str, float]] = None, roof_info: Optional[Dict] = None,
                resolved: frozenset[str] = frozenset()) -> List[Part]:
    """Build full or low shells; real apertures cut shells while blind panes sit outside."""
    if tier not in ('full','low'):
        raise ValueError('tier must be full or low')
    parts = []
    uv_sizes = uv_sizes or {}

    def builder(tag, material):
        return PartBuilder(tag, material, uv_size_m=uv_sizes.get(material, 2.0))

    def emit(tag, material, points, normal):
        b = builder(tag, material)
        actual = _normal(points)
        if sum(a*c for a,c in zip(actual,normal)) < 0:
            points = points[::-1]
        b.poly(points)
        if b.part()['faces']:
            parts.append(b.part())

    door_styles = load_door_styles()
    full = tier == 'full'
    for level in facts['levels']:
        number = level['level']
        filler = level.get('filler', False)
        floor, top = level['floor_y'],level['top_y']
        bottom = -WALL_SINK_M if number == 0 else floor
        inner,outer = wall_offsets(style, number)
        rings = {d: offset_ring(level['outline'],level['ccw'],d) for d in (inner,outer)}
        material = style.get("storey_slot", {}).get(number, 'wall_ground' if number == 0 and style.get('materials',{}).get('wall_ground') else 'wall')
        plinth = style.get('plinth_height_m',0) if number == 0 else bottom
        streets = street_edges(level) if desc.get('overrides',{}).get('shopfront') else set()
        for edge in level['edges']:
            shop = edge['index'] in streets
            band_bottom = shop_band(level,edge)[0] if shop else top
            a,b = edge['a'],edge['b']
            length = math.dist(a,b)
            u,n = _axes(edge)
            outward = [n[0],0,n[1]]

            def point(s,y,d):
                return [a[0]+u[0]*s+n[0]*d,y,a[1]+u[1]*s+n[1]*d]

            def face(tag,mat,s0,s1,y0,y1,d,reverse=False):
                emit(tag,mat,[point(s0,y0,d),point(s1,y0,d),point(s1,y1,d),point(s0,y1,d)],
                     [-v for v in outward] if reverse else outward)

            def block(tag,mat,s0,s1,y0,y1,d0,d1,*,cut_holes=True,door_surround=False):
                # The casing ends .02 proud. Surrounds start .001 beyond it,
                # avoiding coincident head/jamb faces while retaining the reveal.
                if door_surround:
                    d0 = max(d0, outer+.021)
                if s1-s0 <= 1e-5 or y1-y0 <= 1e-5:
                    return
                from app.core.hull_roofs import clip_detail, detail_breaks
                breaks = detail_breaks(roof_info, number, edge, (inner if tag == 'band' else d0,d1))
                spans = sorted({s0,s1,*(v for v in breaks if s0 < v < s1)})
                for left,right in zip(spans,spans[1:]):
                    if tag == 'band' and right-left <= 1e-5:
                        continue
                    build = builder(tag,mat)
                    pieces = (_cells(left,right,y0,y1,holes) if cut_holes and tag in ('frame','shutter')
                              else [(left,right,y0,y1)])
                    for c,d,e,f in pieces:
                        outline = [[point(s,e,depth)[k] for k in (0,2)]
                                   for s,depth in ((c,d0),(d,d0),(d,d1),(c,d1))]
                        build.prism(outline,e,f)
                    if build.part()['faces']:
                        part = build.part()
                        if tag == 'band':
                            # A band at a zero-overhang eave only touches the roof footprint.
                            # Probe through the wall so the covered strip still clears that roof.
                            probe = builder(tag,mat)
                            probe.prism([[point(s,y0,depth)[k] for k in (0,2)]
                                         for s,depth in ((left,inner),(right,inner),(right,d1),(left,d1))],y0,y1)
                            clearance = clip_detail(probe.part(), number, roof_info, style)
                            if clearance is None:
                                continue
                            low = min(v[1] for v in clearance['vertices'])
                            high = max(v[1] for v in clearance['vertices'])
                            for vertex in part['vertices']:
                                vertex[1] = round(low+(vertex[1]-y0)*(high-low)/(y1-y0),4)
                        clipped = clip_detail(part, number, roof_info, style)
                        if clipped is not None:
                            parts.append(clipped)

            lo,hi = _span(rings[outer],edge,outer)
            holes = []
            for index,h in enumerate(edge['openings']):
                clipped = dict(h, s0=max(lo if h.get('blind') else 0,h['s0']),
                               s1=min(hi if h.get('blind') else length,h['s1']),
                               y0=max(bottom,h['y0']),y1=min(top,h['y1']),index=index)
                if clipped['s1']-clipped['s0'] > 1e-5 and clipped['y1']-clipped['y0'] > 1e-5:
                    holes.append(clipped)
            real_holes = [h for h in holes if not h.get('blind')]
            bays = module_count(level, style, resolved, hi-lo, facts.get('storey_m'))
            if bays:
                start = max(floor,plinth) if number == 0 else floor
                build = builder('facade_module','facade_module')
                points = [point(lo,start,outer),point(hi,start,outer),point(hi,top,outer),point(lo,top,outer)]
                uv = [[0,(start-floor)/(top-floor)],[bays,(start-floor)/(top-floor)],[bays,1],[0,1]]
                if sum(v*w for v,w in zip(_normal(points),outward)) < 0:
                    points,uv = points[::-1],uv[::-1]
                build.poly(points,uv)
                if build.part()['faces']:
                    parts.append(build.part())
            shell_top = min(top,plinth) if bays and number == 0 else (bottom if bays else top)
            cuts = (plinth,band_bottom) if shop else (plinth,)
            for s0,s1,y0,y1 in _cells(lo,hi,bottom,shell_top,real_holes,cuts):
                is_plinth = number == 0 and (y0+y1)/2 < plinth
                paint = 'shop' if shop and (y0+y1)/2 < band_bottom else material
                face('plinth' if is_plinth else 'wall','plinth' if is_plinth else paint,
                     s0,s1,y0,y1,outer)
            if full and not filler:
                ilo,ihi = _span(rings[inner],edge,inner)
                for s0,s1,y0,y1 in _cells(ilo,ihi,bottom,top,real_holes):
                    face('interior','interior',s0,s1,y0,y1,inner,True)
                # Horizontal wall closures, split at apertures reaching the band limits.
                for y,sign in ((bottom,-1),(top,1)):
                    touching = [h for h in real_holes if h['y0']-1e-6 <= y <= h['y1']+1e-6]
                    for s0,s1,_,_ in _cells(lo,hi,0,1,
                            [dict(s0=h['s0'],s1=h['s1'],y0=0,y1=1) for h in touching]):
                        i0 = ilo if s0 == lo else s0
                        i1 = ihi if s1 == hi else s1
                        emit('interior','interior',[point(i0,y,inner),point(i1,y,inner),
                             point(s1,y,outer),point(s0,y,outer)],[0,sign,0])
            if full:
                # Cornice and plinth ledges follow the same hole subtraction.
                bands = []
                if style.get('cornice'):
                    bands.append(('cornice','trim',top-.12,top,.08))
                if number == 0 and plinth > bottom:
                    bands.append(('plinth','plinth',plinth-.06,plinth,.04))
                for tag,mat,y0,y1,depth in bands:
                    for s0,s1,c,d in _cells(lo,hi,max(bottom,y0),min(top,y1),real_holes):
                        block(tag,mat,s0,s1,c,d,outer,outer+depth)
                if style.get('storey_bands') and number >= 1:
                    previous = next((item for item in facts['levels'] if item['level'] == number-1), None)
                    band_holes = list(real_holes)
                    if previous is not None:
                        for prior_edge in previous['edges']:
                            if prior_edge['a'] == a and prior_edge['b'] == b:
                                band_holes.extend(h for h in prior_edge['openings'] if not h.get('blind'))
                    # Only vertically intersecting real apertures may subdivide the strip.
                    band_holes = [h for h in band_holes if h['y0'] < floor+.15 and h['y1'] > floor-.15
                                  and h['s0'] < hi and h['s1'] > lo]
                    for s0,s1,c,d in _cells(lo,hi,floor-.15,floor+.15,band_holes):
                        block('band','trim',s0,s1,c,d,outer,outer+.05)
                if outer > inner+style['wall_thickness_m']+1e-6:
                    # Jetty underside from the un-jettied outside to the outer edge.
                    base = outer-style.get('jetty_m',0)
                    emit('wall',material,[point(lo,floor,base),point(hi,floor,base),
                         point(hi,floor,outer),point(lo,floor,outer)],[0,-1,0])
            for h in holes:
                s0,s1,y0,y1 = [h[k] for k in ('s0','s1','y0','y1')]
                kind = h['kind']
                frame = style.get('frames','none')
                casement = full and kind == 'window' and frame != 'metal'
                if kind == 'door' and not h.get('blind'):
                    style_id = door_style_id(h, number, style, desc)
                    door_style = door_styles[style_id]
                    width, height = s1-s0, y1-y0
                    double = leaves_for(door_style, width) == 2
                    roles = {role: f'{role}_{style_id}' for role in ('door_leaf','door_frame','hardware')}
                    scales = {role: uv_sizes[name] for role,name in {**roles, 'glass':'glass'}.items() if name in uv_sizes}
                    for piece in (('double_a','double_b') if double else ('single',)):
                        geometry = build_door(door_style, width, height, thickness=outer-inner,
                                              piece=piece, outside=1, tier=tier, uv_sizes=scales)
                        shift = .07+.005+(width-.015)/2+.005 if piece == 'double_b' else 0
                        lift = .025 if piece == 'double_b' else 0
                        for part in geometry['parts']:
                            part.update(tag='door', protrudes=False,
                                        material=roles.get(part['material'],part['material']))
                            if piece == 'double_b':
                                part['node'] = 'leaf_b'
                            # B's hinge-local x runs back from the right jamb.
                            part['vertices'] = [[round(v,4) for v in point(
                                s0-.07+shift+((width-.015)/2-x if piece == 'double_b' else x),
                                y0+y+lift,(inner+outer)/2+z)]
                                                for x,y,z in part['vertices']]
                            # The edge frame can reflect z; preserve outward winding.
                            if (u[0]*n[1]-u[1]*n[0]) * (-1 if piece == 'double_b' else 1) < 0:
                                part['faces'] = [face[::-1] for face in part['faces']]
                                part['uvs'] = [uv[::-1] for uv in part['uvs']]
                            parts.append(part)
                if kind == 'window':
                    depth = -.02 if h.get('blind') else (0 if not full else .10)
                    if casement and not h.get('blind'):
                        depth = .12
                    face('glass','blind' if h.get('blind') else 'glass',s0,s1,y0,y1,outer-depth)
                if casement:
                    d0,d1 = (outer+.02,outer+.06) if h.get('blind') else (outer-.14,outer-.08)
                    for c,d,e,f in ((s0,s0+.06,y0,y1),(s1-.06,s1,y0,y1),
                                    (s0+.06,s1-.06,y0,y0+.06),(s0+.06,s1-.06,y1-.06,y1)):
                        block('casement','window_frame',c,d,e,f,d0,d1)
                    if desc.get('overrides',{}).get('ornament_density',.5) > 0:
                        centres = mullions(s0,s1) if s1-s0 > 1.8 else ([(s0+s1)/2] if s1-s0 >= .7 else [])
                        for centre in centres:
                            block('casement','window_frame',centre-.02,centre+.02,y0+.06,y1-.06,d0,d1)
                        if y1-y0 >= .9:
                            centre = y0+.62*(y1-y0)
                            block('casement','window_frame',s0+.06,s1-.06,centre-.02,centre+.02,d0,d1)
                    block('sill','trim',s0-.08,s1+.08,y0-.07,y0,outer,outer+.10)
                if not full or filler and desc.get('overrides',{}).get('ornament_density',.5) <= 0:
                    continue
                if not h.get('blind'):
                    # Each clipped aperture owns its four reveal polygons.
                    for s,normal in ((s0,[u[0],0,u[1]]),(s1,[-u[0],0,-u[1]])):
                        emit('reveal',material,[point(s,y0,inner),point(s,y1,inner),
                             point(s,y1,outer),point(s,y0,outer)],normal)
                    for y,normal in ((y0,[0,1,0]),(y1,[0,-1,0])):
                        emit('reveal',material,[point(s0,y,inner),point(s1,y,inner),
                             point(s1,y,outer),point(s0,y,outer)],normal)
                if frame == 'timber':
                    for c,d,e,f in ((s0-.12,s0,y0,y1),(s1,s1+.12,y0,y1),
                                    (s0-.12,s1+.12,y1,y1+.12)):
                        block('frame','trim',c,d,e,f,outer,outer+.06,door_surround=kind == 'door')
                    if kind != 'window':
                        block('frame','trim',s0-.12,s1+.12,y0-.12,y0,outer,outer+.06,door_surround=kind == 'door')
                elif frame == 'metal' and kind in ('window','door'):
                    for c,d,e,f in ((s0-.05,s0,y0,y1),(s1,s1+.05,y0,y1),
                                    (s0-.05,s1+.05,y1,y1+.05),(s0-.05,s1+.05,y0-.05,y0)):
                        block('frame','trim',c,d,e,f,outer,outer+.03,cut_holes=e < y1 and f > y0,door_surround=kind == 'door')
                    if kind == 'window':
                        block('frame','trim',s0-.05,s1+.05,y0-.05,y0,outer,outer+.06,cut_holes=False)
                        d0,d1 = (outer+.02,outer+.03) if h.get('blind') else (outer-.10,outer)
                        for centre in mullions(s0,s1):
                            block('frame','trim',centre-.025,centre+.025,y0,y1,d0,d1,cut_holes=False)
                elif frame == 'stone':
                    block('frame','trim',s0-.05,s1+.05,y1,y1+.15,outer,outer+.10,door_surround=kind == 'door')
                chance = min(1,style.get('shutters',0)*desc.get('overrides',{}).get('ornament_density',1)*2)
                if kind == 'window' and rng(desc['seed'],f"shutter:{number}:{edge['index']}:{h['index']}").random() < chance:
                    width = (s1-s0)/2
                    for c,d in ((s0-width,s0),(s1,s1+width)):
                        block('shutter','trim',c,d,y0,y1,outer+.01,outer+.05)
        # Beveled offset corners introduce segments absent from the source edges.
        # Close those segments explicitly, rather than leaving vertical cracks.
        for distance, ring in rings.items():
            if distance == inner and (not full or filler):
                continue
            for index, a in enumerate(ring):
                b = ring[(index+1)%len(ring)]
                on_edge = any(_on_edge((a,b), edge, distance) for edge in level['edges'])
                if on_edge:
                    continue
                sign = 1 if level['ccw'] else -1
                normal = [sign*(b[1]-a[1]),0,-sign*(b[0]-a[0])]
                if distance == inner:
                    normal = [-v for v in normal]
                cuts = sorted({bottom,top,*( [plinth] if bottom < plinth < top else [])})
                for y0,y1 in zip(cuts,cuts[1:]):
                    is_plinth = number == 0 and y1 <= plinth and distance == outer
                    tag = 'interior' if distance == inner else ('plinth' if is_plinth else 'wall')
                    mat = 'interior' if distance == inner else ('plinth' if is_plinth else material)
                    emit(tag,mat,[[a[0],y0,a[1]],[b[0],y0,b[1]],
                                  [b[0],y1,b[1]],[a[0],y1,a[1]]],normal)
        if full and not filler:
            # Offset bevels have matching topology at both distances.
            for i,a in enumerate(rings[outer]):
                j = (i+1)%len(rings[outer])
                b = rings[outer][j]
                if any(_on_edge((a,b), e, outer) for e in level['edges']):
                    continue
                c,d = rings[inner][i],rings[inner][j]
                for y,sign in ((bottom,-1),(top,1)):
                    emit('interior','interior',[[a[0],y,a[1]],[b[0],y,b[1]],
                         [d[0],y,d[1]],[c[0],y,c[1]]],[0,sign,0])
            emit('interior','interior',[[x,floor,z] for x,z in level['outline']],[0,1,0])
            following = next((item for item in facts['levels'] if item['level'] == number+1), None)
            if following is None or following.get('filler', False):
                emit('interior','interior',[[x,top,z] for x,z in level['outline']],[0,-1,0])
    return parts
