#!/usr/bin/env python3
"""A hole loop away from the skin is closed; the attachment loop and a hole on the skin stay open (A180).

Usage: ./.venv/bin/python scripts/smoke_a180_free_holes.py
Runs Blender 5.2 on the CPU against hand-built meshes; no world, no server, no network.

Skin: a 1 m quad at z = 0 (object space = world, identity matrix). Band = .006 m.
Part: three open axis-aligned unit-cube shells of edge .02 m, each missing its top face, so
each has ONE 4-vertex border loop at its top (z = top):
  A  centre (0, 0),   bottom .10, top .12 — closest to the root (0, 0, .12): the attachment loop.
  B  centre (.2, 0),  bottom .10, top .12 — loop median gap .12 m > .006: closed.
  C  centre (-.2, 0), bottom -.02, top 0  — loop on the skin, median gap 0 <= .006: stays open.
Hand-derived expectation for close_free_holes:
  returns 1; B gets one centre vertex at (.2, 0, .12) and 4 fan triangles (+1 vertex, +4 faces);
  open border edges go from 12 to 8 (A's 4 and C's 4); the centre of B carries the mean of its
  ring's weights: ring weights 1, 1, 0, 0 on group "g" -> .5.
  Every new fan face's normal points +z (outward through the former top opening of B).
Also the thigh reweight band of the part grows with the size: from/to .045/.095 m x 1.6 =
.072/.152 m (checked on the source text, the build uses exactly that product).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BLENDER = Path.home() / 'tools/blender-5.2.2-linux-x64/blender'


def blender_side(scripts, out):
    import bpy
    import bmesh
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from mathutils import Matrix
    sys.path.insert(0, scripts)
    import _common
    import attached_part
    _common.reset_scene()
    skin = BVHTree.FromPolygons([(-.5, -.5, 0), (.5, -.5, 0), (.5, .5, 0), (-.5, .5, 0)], [(0, 1, 2, 3)])
    verts, faces = [], []
    for cx, bottom in ((0, .10), (.2, .10), (-.2, -.02)):
        s = len(verts)
        for z in (bottom, bottom + .02):
            for x, y in ((-.01, -.01), (.01, -.01), (.01, .01), (-.01, .01)):
                verts.append((cx + x, y, z))
        faces += [(s + 3, s + 2, s + 1, s), (s, s + 1, s + 5, s + 4), (s + 1, s + 2, s + 6, s + 5),
                  (s + 2, s + 3, s + 7, s + 6), (s + 3, s, s + 4, s + 7)]
    me = bpy.data.meshes.new('P')
    me.from_pydata(verts, [], faces)
    me.update()
    obj = bpy.data.objects.new('P', me)
    bpy.context.collection.objects.link(obj)
    g = obj.vertex_groups.new(name='g')
    # B's top ring is vertices 12..15: weights 1, 1, 0, 0.
    g.add([12, 13], 1.0, 'REPLACE')
    g.add([14, 15], 0.0, 'REPLACE')

    def border_edges():
        count = {}
        for p in obj.data.polygons:
            for e in p.edge_keys:
                count[e] = count.get(e, 0) + 1
        return sum(1 for c in count.values() if c == 1)
    before = (len(obj.data.vertices), len(obj.data.polygons), border_edges())
    closed = attached_part.close_free_holes(obj, skin, Vector((0, 0, .12)), .006, Matrix.Identity(4))
    after = (len(obj.data.vertices), len(obj.data.polygons), border_edges())
    centre = obj.data.vertices[-1]
    weight = next((e.weight for e in centre.groups if e.group == g.index), 0.)
    fan = [p for p in obj.data.polygons if len(p.vertices) == 3]
    Path(out).write_text(json.dumps({
        'closed': closed, 'before': before, 'after': after, 'centre': list(centre.co), 'weight': weight,
        'fan_normals_z': [p.normal.z for p in fan]}))


def main():
    failures = []

    def check(label, ok, detail=''):
        print(('ok   ' if ok else 'FAIL ') + label + (f'  ({detail})' if detail else ''))
        if not ok:
            failures.append(label)
    with tempfile.TemporaryDirectory(prefix='a180-holes-') as directory:
        out = Path(directory) / 'out.json'
        log = Path(directory) / 'log.txt'
        with log.open('w') as stream:
            r = subprocess.run(['nice', '-n', '15', 'timeout', '600', str(BLENDER), '-b', '-noaudio', '--factory-startup',
                                '--python-exit-code', '1', '--python', str(Path(__file__).resolve()), '--', '--blender',
                                str(ROOT / 'app/blender/scripts'), str(out)], stdout=stream, stderr=subprocess.STDOUT,
                               env={**os.environ, 'PYTHONNOUSERSITE': '1'})
        if r.returncode:
            print(log.read_text()[-4000:])
            raise SystemExit(r.returncode)
        d = json.loads(out.read_text())
    check('[1] one loop closed (B)', d['closed'] == 1, d['closed'])
    check('[2] +1 vertex, +4 faces', d['after'][0] == d['before'][0] + 1 and d['after'][1] == d['before'][1] + 4,
          f"{d['before']} -> {d['after']}")
    check('[3] open border edges 12 -> 8', d['before'][2] == 12 and d['after'][2] == 8, f"{d['before'][2]} -> {d['after'][2]}")
    c = d['centre']
    check('[4] centre at (.2, 0, .12)', abs(c[0] - .2) < 1e-6 and abs(c[1]) < 1e-6 and abs(c[2] - .12) < 1e-6, c)
    check('[5] centre weight .5', abs(d['weight'] - .5) < 1e-6, d['weight'])
    check('[6] fan faces face +z', len(d['fan_normals_z']) == 4 and min(d['fan_normals_z']) > .99, d['fan_normals_z'])
    src = (ROOT / 'app/blender/scripts/attached_part.py').read_text()
    check('[7] reweight band x size_factor',
          "settings['reweight']['from'] * size_factor, settings['reweight']['to'] * size_factor" in src)
    if failures:
        raise SystemExit('FAIL a180 free holes: ' + ', '.join(failures))
    print('PASS a180 free holes: a hole away from the skin is closed, the attachment loop and a hole on the skin stay open')


if __name__ == '__main__':
    if '--blender' in sys.argv:
        i = sys.argv.index('--blender')
        blender_side(sys.argv[i + 1], sys.argv[i + 2])
    else:
        main()
