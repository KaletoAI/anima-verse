"""Deterministic, scene-frame polygon builders shared by hull generators."""
import math
import random
from typing import Any, Dict, List
from app.core.scene_recipe import _r, _ring_ccw

Part = Dict[str, Any]


def rng(seed: int, tag: str) -> random.Random:
    return random.Random(f'{seed}:{tag}')


def _normal(points):
    return [sum((a[(i+1)%3]-b[(i+1)%3])*(a[(i+2)%3]+b[(i+2)%3])
                for a, b in zip(points, points[1:]+points[:1])) for i in range(3)]


class PartBuilder:
    """Collect planar faces with per-corner UVs and neutral vertex colors."""
    def __init__(self, tag: str, material: str, *, uv_size_m: float = 1.0,
                 protrudes: bool = False):
        if uv_size_m <= 0:
            raise ValueError('uv_size_m must be positive')
        self.uv_size_m = uv_size_m
        self._part = dict(tag=tag, material=material, protrudes=protrudes,
                          vertices=[], faces=[], uvs=[], colors=[])

    def poly(self, points, uv=None):
        points = [[_r(v) for v in p] for p in points]
        normal = _normal(points)
        magnitude = math.sqrt(sum(v*v for v in normal))
        if magnitude < 2e-6:
            return
        if any(abs(sum(normal[k]*(p[k]-points[0][k]) for k in range(3))) > magnitude*2e-4 for p in points):
            raise ValueError('face must be planar')
        if uv is None:
            axis = max(range(3), key=lambda i: abs(normal[i]))
            axes = [i for i in range(3) if i != axis]
            uv = [[p[i]/self.uv_size_m for i in axes] for p in points]
        if len(uv) != len(points):
            raise ValueError('UV count must match corners')
        start = len(self._part['vertices'])
        self._part['vertices'].extend(points)
        self._part['faces'].append(list(range(start, start+len(points))))
        self._part['uvs'].append([list(pair) for pair in uv])
        self._part['colors'].append([1.0]*len(points))

    def quad(self, p0, p1, p2, p3, uv=None):
        self.poly([p0, p1, p2, p3], uv)

    def box(self, center, size, yaw_rad=0.0):
        c, s = math.cos(yaw_rad), math.sin(yaw_rad)
        dx, dy, dz = [v/2 for v in size]
        outline = [[center[0]+x*c+z*s, center[2]-x*s+z*c]
                   for x,z in ((-dx,-dz),(dx,-dz),(dx,dz),(-dx,dz))]
        self.prism(outline, center[1]-dy, center[1]+dy)

    def prism(self, outline_xz, y0, y1):
        outline = list(outline_xz)
        if not _ring_ccw(outline):
            outline.reverse()
        bottom = [[x,y0,z] for x,z in outline]
        top = [[x,y1,z] for x,z in outline]
        self.poly(bottom)
        self.poly(top[::-1])
        for i in range(len(outline)):
            j = (i+1)%len(outline)
            self.quad(bottom[i], top[i], top[j], bottom[j])

    def cylinder(self, cx, cz, y0, y1, r, sides, r_top=None):
        if sides < 3:
            raise ValueError('cylinder needs at least three sides')
        r_top = r if r_top is None else r_top
        bottom = [[cx+r*math.cos(2*math.pi*i/sides), y0,
                   cz+r*math.sin(2*math.pi*i/sides)] for i in range(sides)]
        top = [[cx+r_top*math.cos(2*math.pi*i/sides), y1,
                cz+r_top*math.sin(2*math.pi*i/sides)] for i in range(sides)]
        self.poly(bottom)
        self.poly(top[::-1])
        for i in range(sides):
            j = (i+1)%sides
            if r_top == 0:
                self.poly([bottom[i], top[i], bottom[j]])
            else:
                self.quad(bottom[i], top[i], top[j], bottom[j])

    def part(self) -> Part:
        return self._part


def offset_ring(outline, ccw, distance) -> List[List[float]]:
    """Offset edge lines outward, beveling miters longer than 3 distances."""
    if distance == 0:
        return [[_r(x), _r(z)] for x,z in outline]
    result = []
    sign = 1 if ccw else -1
    for i,p in enumerate(outline):
        before, after = outline[i-1], outline[(i+1)%len(outline)]
        u = [p[k]-before[k] for k in range(2)]
        v = [after[k]-p[k] for k in range(2)]
        lu, lv = math.hypot(*u), math.hypot(*v)
        u, v = [x/lu for x in u], [x/lv for x in v]
        n, m = [sign*u[1], -sign*u[0]], [sign*v[1], -sign*v[0]]
        denom = 1+n[0]*m[0]+n[1]*m[1]
        delta = [distance*(n[k]+m[k])/denom for k in range(2)] if denom > 1e-10 else [math.inf]*2
        if math.hypot(*delta) <= 3*abs(distance):
            result.append([_r(p[k]+delta[k]) for k in range(2)])
        else:
            # A bevel joins the two perpendicular offset feet.
            result.extend([[_r(p[k]+distance*q[k]) for k in range(2)] for q in (n,m)])
    return result


def tri_count(parts) -> int:
    return sum(len(face)-2 for part in parts for face in part['faces'])


def bounds(parts):
    points = [p for part in parts for p in part['vertices']]
    return {key: [fn(p[i] for p in points) if points else 0.0 for i in range(3)]
            for key,fn in (('min',min),('max',max))}
