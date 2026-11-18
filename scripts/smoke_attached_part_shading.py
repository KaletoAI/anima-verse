#!/usr/bin/env python3
"""The attached part shades as its surface: no seam normal from an opposite skin wall, no line on the midline (Ruling A65d).

Usage: ./.venv/bin/python scripts/smoke_attached_part_shading.py
Runs Blender 5.2 on the CPU against the synthetic body of
scripts/smoke_attached_part_placement.py (with its ledge) plus a skin wall
facing -x at x = +24 mm (y -100 to -10 mm, z .93 to 1.0), like a thigh beside
the pods; written to a temp dir; no world, no server, no network.

Fixture at size 1.6 (metres, see the placement smoke): pod factor
f = 1.596; the lateral pod's centre lies .012 f = 19.2 mm to the side of the
root, its x radius .014 f = 22.3 mm, so it reaches 41.5 mm and passes through
the wall. The wall's nearest point is 24 mm from the root, inside the
attachment window ((.03 + .02) x 1.6 = 80 mm): the part fillets onto the wall,
and the pod surface beside the junction faces the wall across a fold, the
wall's normal (-x) opposite its own.

Hand-derived expectations:
- Seam normals: the seam pass blends a vertex's own normal n towards the body
  normal nb by the share c x s(clamp(2 (n . nb), 0, 1)) (Ruling A65d). Where
  n . nb <= 0 the factor is 0 and the shading normal stays n. Otherwise the
  angle between n and nb is under 90 degrees, and a blend of two unit vectors
  lies within that angle of n. So every visible part vertex (in front of the
  front skin and on the open side of the wall) shades within 90 degrees of its
  surface normal (the area-weighted face normals; n is Blender's angle-weighted
  one, a few degrees apart on a smooth surface). The metric
  seam_opposed_normals counts the vertices the factor reduced: more than 0 here.
- Midline ridge: the raphe adds h(x) = raphe exp(-(x / w)^2) to the pods (both
  x pod scale, so the slope does not scale). Its steepest flank, at x = w / sqrt 2,
  rises raphe sqrt 2 / w e^-1/2 = .858 raphe / w: .858 x .0005 / .005 = .0858,
  4.9 degrees, at most tan 5 degrees = .0875 allowed. At w = .0018 the flanks
  rose 13.4 degrees and the ridge shaded as a thin dark line down the pods.

Old-code proof: the builder at commit 47579fee573001283ff6620ba4c7e830a5da0966
(Ruling A65c) blends every seam vertex fully towards the nearest skin's normal,
so vertices beside the wall shade inside out (measured: 3 visible ones up to
123.5 degrees off; the new builder at most 78.8), reports no
seam_opposed_normals, and declares raphe_width .0018: all three checks fail.
"""
import json
import math
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _smoke_attached_part as _ap  # noqa: E402  (shared Blender harness)
BLENDER = _ap.BLENDER
OLD_COMMIT = '47579fee573001283ff6620ba4c7e830a5da0966'
WALL, SIZE = .024, 1.6
FLIP_DEG, RAPHE_SLOPE = 90., math.tan(math.radians(5))


def inside(skin, point):
    """Whether ``point`` lies behind the fixture's front skin: a ray towards the
    front (-y) crosses it an odd number of times (the wall runs parallel)."""
    from mathutils import Vector
    direction, crossings = Vector((0, -1, 0)), 0
    origin = point.copy()
    while True:
        hit = skin.ray_cast(origin, direction)[0]
        if hit is None:
            return crossings % 2 == 1
        crossings += 1
        origin = hit + direction * 1e-6


def blender_side(scripts, directory):
    import bpy
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    sys.path.insert(0, scripts)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import attached_part
    from smoke_attached_part_placement import make_fixture
    out = Path(directory)
    settings = attached_part.parameters({})
    folds = settings['pods']['folds']
    chain = [{'bone': 'PartLink' + str(i + 1), 'parent': 'Hips' if i == 0 else 'PartLink' + str(i)} for i in range(5)]
    companion = {'id': 'pods', 'op': 'attached_part_bone', 'chains': [[{'bone': 'PartPods', 'parent': 'Hips'}]], 'params': {}}
    fixture, root, _ = make_fixture(scripts, out, ledge=True, wall=WALL)
    group = {'id': 'part', 'op': 'attached_part', 'chains': [chain],
             'params': {'size_factor': SIZE, 'voxel': .002, 'texture': {'bake': 128}}}
    result, _ = attached_part.attached_part({'inputs': {'model': str(fixture)},
                                            'params': {'groups': [group, companion]}, 'out_dir': str(out)})
    part = next(o for o in bpy.context.scene.objects if o.get('attached_part') == 'part')
    body = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and o.vertex_groups and not o.get('attached_part'))
    skin = BVHTree.FromPolygons([body.matrix_world @ v.co for v in body.data.vertices],
                                [p.vertices[:] for p in body.data.polygons])
    me = part.data
    geometric = [Vector() for _ in me.vertices]
    for poly in me.polygons:
        for vi in poly.vertices:
            geometric[vi] += poly.normal * poly.area
    shading = [Vector() for _ in me.vertices]
    for loop in me.loops:
        shading[loop.vertex_index] += Vector(me.corner_normals[loop.index].vector)
    deviations = []
    for v in me.vertices:
        point = part.matrix_world @ v.co
        if inside(skin, point) or point.x > WALL:
            continue
        deviations.append(math.degrees(geometric[v.index].normalized().angle(shading[v.index].normalized(), 0)))
    (out / 'shading.json').write_text(json.dumps({
        'root': list(root), 'deviations': deviations,
        'opposed': result['metrics']['part'].get('seam_opposed_normals'),
        'raphe': folds['raphe'], 'raphe_width': folds['raphe_width']}))


def run_blender(scripts, directory):
    return _ap.run_blender(__file__, scripts, directory, 'shading.json')


def failures(data):
    """Every hand-derived expectation the build misses."""
    out = []
    flipped = sum(d > FLIP_DEG for d in data['deviations'])
    if not data['deviations']:
        out.append('no visible part vertex')
    if flipped:
        out.append(f'{flipped} visible part vertices shade more than {FLIP_DEG:.0f} degrees off their surface '
                   f'(max {max(data["deviations"]):.1f})')
    if not data['opposed']:
        out.append(f'seam_opposed_normals {data["opposed"]}: the wall reduced no seam normal')
    slope = .858 * data['raphe'] / data['raphe_width']
    if slope > RAPHE_SLOPE:
        out.append(f'raphe flank rises {math.degrees(math.atan(slope)):.1f} degrees, expected at most 5')
    return out


def main():
    with tempfile.TemporaryDirectory(prefix='attached-part-shading-') as directory:
        data = run_blender(str(ROOT / 'app/blender/scripts'), str(Path(directory) / 'new'))
        problems = failures(data)
        assert not problems, problems
        print(f'size {SIZE}: {len(data["deviations"])} visible part vertices, shading normal at most',
              round(max(data['deviations']), 1), 'degrees off the surface;', data['opposed'],
              'seam normals reduced by the wall; raphe flank',
              round(math.degrees(math.atan(.858 * data['raphe'] / data['raphe_width'])), 1), 'degrees')
        # The same checks against the builder before Ruling A65d.
        old = _ap.old_scripts(Path(directory) / 'old-scripts', OLD_COMMIT)
        old_problems = failures(run_blender(str(old), str(Path(directory) / 'old')))
        assert len(old_problems) >= 3, old_problems
        print('old builder', OLD_COMMIT[:9], 'fails', len(old_problems), 'checks, e.g.', old_problems[0])
    print('PASS attached_part shading: no seam normal from an opposite wall, a soft midline ridge')


if __name__ == '__main__':
    _ap.blender_entry(blender_side, main)
