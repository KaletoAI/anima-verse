"""Wall shells and aperture details built exclusively from hull facts."""
import math
from typing import Dict, List, Optional, Tuple
from app.core.hull_mesh import Part, PartBuilder, offset_ring, rng, _normal
from app.core.scene_recipe import WALL_THICKNESS, WALL_SINK_M


def wall_offsets(style: Dict, level: int) -> Tuple[float, float]:
    inner = WALL_THICKNESS/2 + 0.005
    outer = inner + style['wall_thickness_m']
    if level >= 1 and style.get('timber_frame', 'none') != 'none':
        outer += style.get('jetty_m', 0)
    return inner, outer


def _cells(s0, s1, y0, y1, holes, extra_y=()):
    """Tile the complement of the union of clipped aperture rectangles."""
    if s1 <= s0 or y1 <= y0:
        return
    xs = sorted({s0, s1, *(max(s0, min(s1, h[k])) for h in holes for k in ('s0','s1'))})
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
                uv_sizes: Optional[Dict[str, float]] = None) -> List[Part]:
    """Build full or low shells; every source aperture remains a real hole."""
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

    full = tier == 'full'
    for level in facts['levels']:
        number = level['level']
        floor, top = level['floor_y'],level['top_y']
        bottom = -WALL_SINK_M if number == 0 else floor
        inner,outer = wall_offsets(style, number)
        rings = {d: offset_ring(level['outline'],level['ccw'],d) for d in (inner,outer)}
        material = 'wall_ground' if number == 0 and style.get('materials',{}).get('wall_ground') else 'wall'
        plinth = style.get('plinth_height_m',0) if number == 0 else bottom
        for edge in level['edges']:
            a,b = edge['a'],edge['b']
            length = math.dist(a,b)
            u,n = _axes(edge)
            outward = [n[0],0,n[1]]

            def point(s,y,d):
                return [a[0]+u[0]*s+n[0]*d,y,a[1]+u[1]*s+n[1]*d]

            def face(tag,mat,s0,s1,y0,y1,d,reverse=False):
                emit(tag,mat,[point(s0,y0,d),point(s1,y0,d),point(s1,y1,d),point(s0,y1,d)],
                     [-v for v in outward] if reverse else outward)

            def block(tag,mat,s0,s1,y0,y1,d0,d1):
                if s1-s0 <= 1e-5 or y1-y0 <= 1e-5:
                    return
                build = builder(tag,mat)
                pieces = _cells(s0,s1,y0,y1,holes) if tag in ('frame','shutter') else [(s0,s1,y0,y1)]
                for c,d,e,f in pieces:
                    outline = [[point(s,e,depth)[k] for k in (0,2)]
                               for s,depth in ((c,d0),(d,d0),(d,d1),(c,d1))]
                    build.prism(outline,e,f)
                if build.part()['faces']:
                    parts.append(build.part())

            holes = []
            for index,h in enumerate(edge['openings']):
                clipped = dict(h, s0=max(0,h['s0']),s1=min(length,h['s1']),
                               y0=max(bottom,h['y0']),y1=min(top,h['y1']),index=index)
                if clipped['s1']-clipped['s0'] > 1e-5 and clipped['y1']-clipped['y0'] > 1e-5:
                    holes.append(clipped)
            lo,hi = _span(rings[outer],edge,outer)
            for s0,s1,y0,y1 in _cells(lo,hi,bottom,top,holes,(plinth,)):
                is_plinth = number == 0 and (y0+y1)/2 < plinth
                face('plinth' if is_plinth else 'wall','plinth' if is_plinth else material,
                     s0,s1,y0,y1,outer)
            if full:
                ilo,ihi = _span(rings[inner],edge,inner)
                for s0,s1,y0,y1 in _cells(ilo,ihi,bottom,top,holes):
                    face('interior','interior',s0,s1,y0,y1,inner,True)
                # Horizontal wall closures, split at apertures reaching the band limits.
                for y,sign in ((bottom,-1),(top,1)):
                    touching = [h for h in holes if h['y0']-1e-6 <= y <= h['y1']+1e-6]
                    for s0,s1,_,_ in _cells(lo,hi,0,1,
                            [dict(s0=h['s0'],s1=h['s1'],y0=0,y1=1) for h in touching]):
                        i0 = ilo if s0 == lo else s0
                        i1 = ihi if s1 == hi else s1
                        emit('interior','interior',[point(i0,y,inner),point(i1,y,inner),
                             point(s1,y,outer),point(s0,y,outer)],[0,sign,0])
                # Cornice and plinth ledges follow the same hole subtraction.
                bands = []
                if style.get('cornice'):
                    bands.append(('cornice','trim',top-.12,top,.08))
                if number == 0 and plinth > bottom:
                    bands.append(('plinth','plinth',plinth-.06,plinth,.04))
                for tag,mat,y0,y1,depth in bands:
                    for s0,s1,c,d in _cells(lo,hi,max(bottom,y0),min(top,y1),holes):
                        block(tag,mat,s0,s1,c,d,outer,outer+depth)
                if outer > inner+style['wall_thickness_m']+1e-6:
                    # Jetty underside from the un-jettied outside to the outer edge.
                    base = outer-style.get('jetty_m',0)
                    emit('wall',material,[point(lo,floor,base),point(hi,floor,base),
                         point(hi,floor,outer),point(lo,floor,outer)],[0,-1,0])
            for h in holes:
                s0,s1,y0,y1 = [h[k] for k in ('s0','s1','y0','y1')]
                kind = h['kind']
                if kind in ('window','door'):
                    depth = 0 if not full else (.10 if kind == 'window' else .08)
                    face('glass' if kind == 'window' else 'door',
                         'glass' if kind == 'window' else 'door',s0,s1,y0,y1,outer-depth)
                if not full:
                    continue
                # Each clipped aperture owns its four reveal polygons.
                for s,normal in ((s0,[u[0],0,u[1]]),(s1,[-u[0],0,-u[1]])):
                    emit('reveal',material,[point(s,y0,inner),point(s,y1,inner),
                         point(s,y1,outer),point(s,y0,outer)],normal)
                for y,normal in ((y0,[0,1,0]),(y1,[0,-1,0])):
                    emit('reveal',material,[point(s0,y,inner),point(s1,y,inner),
                         point(s1,y,outer),point(s0,y,outer)],normal)
                frame = style.get('frames','none')
                if frame == 'timber':
                    for c,d,e,f in ((s0-.12,s0,y0,y1),(s1,s1+.12,y0,y1),
                                    (s0-.12,s1+.12,y1,y1+.12)):
                        block('frame','trim',c,d,e,f,outer,outer+.06)
                    block('frame','trim',s0-.12,s1+.12,y0-.12,y0,outer,outer+.06)
                elif frame == 'stone':
                    block('frame','trim',s0-.05,s1+.05,y1,y1+.15,outer,outer+.10)
                    if kind == 'window':
                        block('frame','trim',s0-.05,s1+.05,y0-.15,y0,outer,outer+.10)
                chance = min(1,style.get('shutters',0)*desc.get('overrides',{}).get('ornament_density',1)*2)
                if kind == 'window' and rng(desc['seed'],f"shutter:{number}:{edge['index']}:{h['index']}").random() < chance:
                    width = (s1-s0)/2
                    for c,d in ((s0-width,s0),(s1,s1+width)):
                        block('shutter','trim',c,d,y0,y1,outer+.01,outer+.05)
        # Beveled offset corners introduce segments absent from the source edges.
        # Close those segments explicitly, rather than leaving vertical cracks.
        for distance, ring in rings.items():
            if distance == inner and not full:
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
        if full:
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
            if top == facts['eaves_y']:
                emit('interior','interior',[[x,top,z] for x,z in level['outline']],[0,-1,0])
    return parts
