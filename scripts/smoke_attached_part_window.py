#!/usr/bin/env python3
"""The flattened front window keeps a double-walled body closed and blends out without creases; a border beside its skin is judged by its side (Ruling A65e).

Usage: ./.venv/bin/python scripts/smoke_attached_part_window.py
Runs Blender 5.2 on the CPU against the synthetic body of
scripts/smoke_attached_part_placement.py without its ledge (the tilted front
skin runs on below the root), plus a Gaussian bump of height 12 mm and radius
15 mm on that skin, centred on the midline 45 mm below the root, and an inner
wall 4 mm behind the whole front skin facing back into the hollow body, as a
double-walled mesher delivers it, closed by a wide box open to the front;
written to a temp dir; no world, no server, no network. Size 1.0.

Fixture (metres, see the placement smoke): root R = (0, -.05925, .99828). The
flatten window spans x +-55 mm, z from R - 100 to R + 10 mm and y up to
R.y + 30 mm; the skin there faces the front (normal y < -.2). The bump's top
lies at y -.065 + .3 (.953 - 1) - .012 = -.091, its steepest flank, at
r / sqrt 2, rises h sqrt 2 / r e^-1/2 = .686 (34 degrees): its normal's y is
at most -cos 34 = -.83, so the whole bump lies in the window. On the 5 mm grid
the bump's own surface turns at most 2 h / r^2 x 5 mm = .53 rad (30.6 degrees)
between neighbouring quads, at its top; the glTF round trip splits every quad
into two triangles, which share that turn.

Hand-derived expectations:
- Closed: the inner wall moves with the skin point in front of it, so along
  every ray from the front through the window (x +-40 mm, z from R - 95 to
  R + 5 mm, a 5 mm raster offset 2.5 mm from the grid) the first surface faces
  the front and the second, the inner wall, lies at least half its 4 mm depth
  behind it (both move by the same interpolated displacement; half allows the
  bump's tilt between a wall vertex and its pairing point). The build reports
  window_skin_lost 0 and inner_wall_moved > 0.
- Deep enough to matter: the flattening moves the bump's top more than the
  wall's 4 mm, so without the wall following it the skin would cross it.
- No crease: the displacement is averaged with its neighbours' ten times
  over the skin around the window, so neighbouring faces there turn against
  each other by no more than the bump's own largest turn, 30.6 degrees, and no
  turn grows by more than that. The unblended window moved each vertex along
  its own normal and its neighbours outside the window not at all: a step of
  several mm over one 5 mm quad.
- Beside the skin (OuterSkin.inside_beside), on a closed cube of side .2 m
  (5 cm quads) without the four middle quads of its front face (y = -.1):
  (0, -.09, 0) lies inside, nearest the hole's rim at (+-.05, -.1, 0) with an
  offset of .051 m of which .01 along the front normal, under half: beside;
  its x, z and +y rays cross the cube once, the -y ray leaves through the hole
  (5 votes of 6): inside. (0, -.11, 0) is beside the rim too and only its +y
  ray crosses the cube (1 vote): outside. (0, -.12, .075) lies over a front
  quad: None.

Old-code proof: the builder at commit 63a161e12e525cca182ec4acbcc5cd3e3d9c8223
(Ruling A65d) flattens the bump's top by 10.3 mm through the 4 mm wall (29 rays
meet the wall first), reports neither metric, turns neighbouring faces by up to
45.9 degrees and has no inside_beside: all five checks fail there.
"""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BLENDER = Path.home() / 'tools/blender-5.2.2-linux-x64/blender'
OLD_COMMIT = '63a161e12e525cca182ec4acbcc5cd3e3d9c8223'
BUMP_H, BUMP_R, BUMP_BELOW, INNER = .012, .015, .045, .004
TURN_DEG = math.degrees(2 * BUMP_H / BUMP_R ** 2 * .005)


def blender_side(scripts, directory):
    import bpy
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    sys.path.insert(0, scripts)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import attached_part
    from smoke_attached_part_placement import make_fixture
    out = Path(directory)
    results = {}
    # Beside the skin: the cube with a hole in its front face.
    verts, faces, index = [], [], {}

    def vert(p):
        key = tuple(round(c, 6) for c in p)
        if key not in index:
            index[key] = len(verts)
            verts.append(key)
        return index[key]
    steps = [-.1 + .05 * i for i in range(5)]
    for axis in range(3):
        for sign in (-1, 1):
            for i in range(4):
                for j in range(4):
                    if axis == 1 and sign == -1 and 1 <= i <= 2 and 1 <= j <= 2:
                        continue
                    corners = []
                    for a, b in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)):
                        p = [0., 0., 0.]
                        others = [k for k in range(3) if k != axis]
                        p[axis] = .1 * sign
                        p[others[0]], p[others[1]] = steps[a], steps[b]
                        corners.append(vert(p))
                    normal = Vector(verts[corners[1]]) - Vector(verts[corners[0]])
                    normal = normal.cross(Vector(verts[corners[3]]) - Vector(verts[corners[0]]))
                    if normal[axis] * sign < 0:
                        corners.reverse()
                    faces.append(corners)

    class Cube:
        tree = BVHTree.FromPolygons([Vector(v) for v in verts], faces)
    side = {}
    for name, point in (('inside', (0, -.09, 0)), ('outside', (0, -.11, 0)), ('over', (0, -.12, .075))):
        point = Vector(point)
        try:
            side[name] = attached_part.OuterSkin.inside_beside(Cube, point, Cube.tree.find_nearest(point))
        except AttributeError:
            side[name] = 'missing'
    results['beside'] = side
    # The window on the double-walled fixture.
    fixture, root, _ = make_fixture(scripts, out, ledge=False, bump=(BUMP_H, BUMP_R, .99828 - BUMP_BELOW), inner=INNER)
    chain = [{'bone': 'PartLink' + str(i + 1), 'parent': 'Hips' if i == 0 else 'PartLink' + str(i)} for i in range(5)]
    companion = {'id': 'pods', 'op': 'attached_part_bone', 'chains': [[{'bone': 'PartPods', 'parent': 'Hips'}]], 'params': {}}
    group = {'id': 'part', 'op': 'attached_part', 'chains': [chain],
             'params': {'size_factor': 1.0, 'voxel': .002, 'texture': {'bake': 128}}}
    import _common
    _common.reset_scene()
    _common.import_model(fixture)
    body = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and o.vertex_groups)
    before = [body.matrix_world @ v.co for v in body.data.vertices]
    data, _ = attached_part.attached_part({'inputs': {'model': str(fixture)},
                                           'params': {'groups': [group, companion]}, 'out_dir': str(out)})
    metrics = data['metrics']['part']
    body = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and o.vertex_groups and not o.get('attached_part'))
    after = [body.matrix_world @ v.co for v in body.data.vertices]
    polys = [p.vertices[:] for p in body.data.polygons]
    tree = BVHTree.FromPolygons(after, polys)
    rays = []
    for i in range(-8, 8):
        for k in range(-19, 1):
            x, z = (i + .5) * .005, root.z + (k + .5) * .005
            origin, hits = Vector((x, -.3, z)), []
            while len(hits) < 2:
                hit, normal, _, _ = tree.ray_cast(origin, Vector((0, 1, 0)))
                if hit is None:
                    break
                hits.append((hit.y, normal.y))
                origin = hit + Vector((0, 1e-6, 0))
            rays.append({'x': x, 'z': z, 'hits': hits})
    # Turns between neighbouring front-skin faces around the window (box + 30 mm);
    # the glTF round trip triangulates the quads, the shared edges pair them.
    def face_normal(co, p):
        n = Vector()
        for a in range(len(p)):
            n += co[p[a]].cross(co[p[(a + 1) % len(p)]])
        return n.normalized()
    edges = {}
    for f, p in enumerate(polys):
        centre = sum((before[v] for v in p), Vector()) / len(p)
        if face_normal(before, p).y > -.5 or abs(centre.x) > .085 or not root.z - .13 < centre.z < root.z + .04:
            continue
        for a in range(len(p)):
            edges.setdefault(frozenset((p[a], p[(a + 1) % len(p)])), []).append(f)
    turns = []
    for pair in edges.values():
        if len(pair) == 2:
            f, g = pair
            turns.append({'after': math.degrees(face_normal(after, polys[f]).angle(face_normal(after, polys[g]))),
                          'before': math.degrees(face_normal(before, polys[f]).angle(face_normal(before, polys[g])))})
    top = [i for i, v in enumerate(before) if abs(v.x) < 1e-6 and abs(v.z - (.99828 - BUMP_BELOW)) < .003 and v.y < -.08]
    moved = max((before[i] - after[i]).length for i in top) if top else 0.
    results['window'] = {'rays': rays, 'turns': turns, 'top_moved_mm': moved * 1000,
                         'window_skin_lost': metrics.get('window_skin_lost'),
                         'inner_wall_moved': metrics.get('inner_wall_moved')}
    (out / 'window.json').write_text(json.dumps(results))


def run_blender(scripts, directory):
    env = {**os.environ, 'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '1', 'PYTHONUNBUFFERED': '1'}
    Path(directory).mkdir()
    log = Path(directory) / 'blender.log'
    with log.open('w') as stream:
        result = subprocess.run(['nice', '-n', '15', 'timeout', '900', str(BLENDER), '-b', '-noaudio', '--factory-startup',
                                 '--python-exit-code', '1', '--python', str(Path(__file__).resolve()), '--',
                                 '--blender', scripts, directory], stdout=stream, stderr=subprocess.STDOUT, env=env)
    if result.returncode:
        print(log.read_text()[-6000:])
        raise SystemExit(result.returncode)
    return json.loads((Path(directory) / 'window.json').read_text())


def failures(data):
    """Every hand-derived expectation the build misses."""
    out = []
    side = data['beside']
    if side != {'inside': True, 'outside': False, 'over': None}:
        out.append(f'beside the skin: {side}, expected inside True, outside False, over None')
    window = data['window']
    crossed = [r for r in window['rays'] if not r['hits'] or r['hits'][0][1] > 0]
    if crossed:
        r = crossed[0]
        out.append(f'{len(crossed)} rays through the window meet the inner wall first, e.g. x {r["x"] * 1000:.1f} '
                   f'z {r["z"] * 1000:.1f} mm')
    thin = [r for r in window['rays'] if len(r['hits']) == 2 and r['hits'][0][1] < 0 and r['hits'][1][0] - r['hits'][0][0] < INNER / 2]
    if thin:
        gap = min(r['hits'][1][0] - r['hits'][0][0] for r in thin) * 1000
        out.append(f'{len(thin)} rays find the inner wall less than {INNER * 500:.0f} mm behind the skin (down to {gap:.2f})')
    if window['window_skin_lost'] != 0 or not window['inner_wall_moved']:
        out.append(f'window_skin_lost {window["window_skin_lost"]}, inner_wall_moved {window["inner_wall_moved"]}: '
                   'expected 0 and more than 0')
    if window['top_moved_mm'] <= INNER * 1000:
        out.append(f'the bump top moved {window["top_moved_mm"]:.1f} mm, not more than the wall depth: the fixture proves nothing')
    sharpest = max(t['after'] for t in window['turns'])
    grown = max(t['after'] - t['before'] for t in window['turns'])
    if sharpest > TURN_DEG or grown > TURN_DEG:
        out.append(f'neighbouring faces turn up to {sharpest:.1f} degrees (grown by up to {grown:.1f}), '
                   f'expected at most {TURN_DEG:.1f}')
    return out


def main():
    with tempfile.TemporaryDirectory(prefix='attached-part-window-') as directory:
        data = run_blender(str(ROOT / 'app/blender/scripts'), str(Path(directory) / 'new'))
        problems = failures(data)
        assert not problems, problems
        window = data['window']
        print('window: bump top moved', round(window['top_moved_mm'], 1), 'mm; inner wall vertices moved',
              window['inner_wall_moved'], '; skin first on all', len(window['rays']), 'rays, wall at least',
              round(min(r['hits'][1][0] - r['hits'][0][0] for r in window['rays'] if len(r['hits']) == 2) * 1000, 2),
              'mm behind; sharpest turn', round(max(t['after'] for t in window['turns']), 1), 'degrees (limit',
              round(TURN_DEG, 1), ')')
        old = Path(directory) / 'old-scripts'
        old.mkdir()
        for name in ('attached_part.py', '_common.py'):
            source = subprocess.run(['git', '-C', str(ROOT), 'show', f'{OLD_COMMIT}:app/blender/scripts/{name}'],
                                    capture_output=True, text=True, check=True).stdout
            (old / name).write_text(source)
        old_problems = failures(run_blender(str(old), str(Path(directory) / 'old')))
        assert len(old_problems) >= 5, old_problems
        print('old builder', OLD_COMMIT[:9], 'fails', len(old_problems), 'checks, e.g.', old_problems[0])
    print('PASS attached_part window: the skin stays in front of its inner wall and blends out of the window; '
          'a border beside its skin is judged by its side')


if __name__ == '__main__':
    if '--blender' in sys.argv:
        try:
            index = sys.argv.index('--blender')
            blender_side(sys.argv[index + 1], sys.argv[index + 2])
        except BaseException:
            import traceback
            traceback.print_exc()
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(1)
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
    else:
        main()
