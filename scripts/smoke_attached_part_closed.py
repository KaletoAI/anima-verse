#!/usr/bin/env python3
"""The attached part has no crack: its open border stays in the body, on the skin's weights (Ruling A65c).

Usage: ./.venv/bin/python scripts/smoke_attached_part_closed.py
Runs Blender 5.2 on the CPU against the synthetic body of
scripts/smoke_attached_part_placement.py (with its ledge, so the pods hang free
in front of the receded skin) plus the floor, an upward-facing skin quad
(x +-60 mm, y -100 to -10 mm) under the pods; written to a temp dir; no world,
no server, no network. The floor is that small so that no fan ray of the
outer-skin test (_common.enclosed) from the ledge reaches it: a larger one
made the ledge's underside an inner wall.

Fixture (metres, see the placement smoke): root R = (0, -.05925, .99828), pod
factor f = (1 + .55 (s - 1)) x 1.2 (1.2 at size 1.0, 1.596 at size 1.6), the pod
centre .024 f below R. The lowest declared pod ellipsoid (down .006 f, z radius
.024 f) bottoms out (.024 + .006 + .024) f = .054 f below R: 64.8 / 86.2 mm.
The floor lies 58 / 84 mm below R, so the pods reach at least 6.8 / 2.2 mm into
it. The attachment window ends at (body_window.radius + fall) s = 50 / 80 mm
from R, and every floor point is at least 58 / 84 mm from R.

Hand-derived expectations from the declared defaults (skin_sink .0008,
body_window.recede 2, seam.tuck .0004):
- Closed beyond the window: there the blend radius is 0, so the field is
  min(part, body + skin_sink + recede) with recede = 2 (|P - R| - reach). Where
  the pods dip under the floor the body distance is at least -6.8 / -2.2 mm
  (more pod web only adds a little) while recede is at least 2 x 8 = 16 /
  2 x 4 = 8 mm, so the body term stays above -6.8 + .8 + 16 = 10 /
  -2.2 + .8 + 8 = 6.6 mm: the body never wins and the pods keep their own
  surface through the floor. Hence no open border vertex lies beyond the window
  (more than 50 / 80 mm from R) or within 2 mm of the floor, and part vertices
  lie under the floor.
- In the body: every open border vertex lies inside the body (a ray to the
  front crosses its skin an odd number of times) at rest and with the first
  chain link turned -90 degrees. Hidden band edges and pinholes deep in the body
  may move with the part; they stay inside.
- Tucked and glued: an open border vertex on the skin (inside and within 1 mm
  of it) ends seam.tuck under the skin, so at most -.4 + .05 mm (export
  rounding; the exact -.4 on a flat skin is the seam smoke's check), and it
  carries the skin's weights alone (share max(fillet, strip) = 1 on a border,
  set again on the nearest skin polygon after decimation): the lift moves none
  of them, .001 mm allowed for float noise.

Old-code proof: the builder at commit d6a5fce3a83f5258524b503d0a0323f95023a5c9
(Ruling A65b) unions the body beyond the window as a hard minimum and cuts the
pods where they enter the floor: a second open border on the floor, beyond the
window, outside the body, nothing under the floor; it lands the border .4 mm
above the skin, and part of the part's own weights lifts it with the chain. At
least 10 of the 14 checks fail there.
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
OLD_COMMIT = 'd6a5fce3a83f5258524b503d0a0323f95023a5c9'
ROOT_Z = 1.0 - .00172
FLOOR_BELOW = {1.0: .058, 1.6: .084}
REACH_MM, FLOOR_CLEARANCE_MM, ON_SKIN_MM = 50., 2., 1.
TUCK_MM, STEP_TOLERANCE_MM, LIFT_TOLERANCE_MM = .4, .05, .001


def border_loops(part):
    """Open border loops of ``part`` by vertex index groups."""
    count = {}
    for poly in part.data.polygons:
        for edge in poly.edge_keys:
            count[edge] = count.get(edge, 0) + 1
    link = {}
    for (a, b), c in count.items():
        if c == 1:
            link.setdefault(a, []).append(b)
            link.setdefault(b, []).append(a)
    loops, seen = [], set()
    for start in link:
        if start in seen:
            continue
        loop, stack = [], [start]
        seen.add(start)
        while stack:
            v = stack.pop()
            loop.append(v)
            for w in link[v]:
                if w not in seen:
                    seen.add(w)
                    stack.append(w)
        loops.append(loop)
    return loops


def inside(skin, point):
    """Whether ``point`` lies in the fixture's body: a ray towards the front
    (-y) crosses its skin an odd number of times."""
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
    from mathutils.bvhtree import BVHTree
    sys.path.insert(0, scripts)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import attached_part
    from smoke_attached_part_placement import make_fixture
    out = Path(directory)
    chain = [{'bone': 'PartLink' + str(i + 1), 'parent': 'Hips' if i == 0 else 'PartLink' + str(i)} for i in range(5)]
    companion = {'id': 'pods', 'op': 'attached_part_bone', 'chains': [[{'bone': 'PartPods', 'parent': 'Hips'}]], 'params': {}}
    results = {'sizes': {}}
    for size, below in FLOOR_BELOW.items():
        target = out / ('size-' + str(size))
        target.mkdir()
        floor = ROOT_Z - below
        fixture, root, _ = make_fixture(scripts, target, ledge=True, floor=floor)
        group = {'id': 'part', 'op': 'attached_part', 'chains': [chain],
                 'params': {'size_factor': size, 'voxel': .002, 'texture': {'bake': 128}}}
        attached_part.attached_part({'inputs': {'model': str(fixture)},
                                     'params': {'groups': [group, companion]}, 'out_dir': str(target)})
        rig = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
        part = next(o for o in bpy.context.scene.objects if o.get('attached_part') == 'part')
        body = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and o.vertex_groups and not o.get('attached_part'))
        loops = border_loops(part)
        border = sorted({v for loop in loops for v in loop})
        link = rig.pose.bones['PartLink1']
        link.rotation_mode = 'XYZ'
        heights = {}
        lowest = None
        for label, angle in (('rest', 0.), ('lift', -90.)):
            link.rotation_euler = (math.radians(angle), 0, 0)
            bpy.context.view_layer.update()
            graph = bpy.context.evaluated_depsgraph_get()
            skin_eval = body.evaluated_get(graph)
            skin_mesh = skin_eval.to_mesh()
            skin = BVHTree.FromPolygons([body.matrix_world @ v.co for v in skin_mesh.vertices],
                                        [p.vertices[:] for p in skin_mesh.polygons])
            skin_eval.to_mesh_clear()
            part_eval = part.evaluated_get(graph)
            part_mesh = part_eval.to_mesh()
            points = [part.matrix_world @ v.co for v in part_mesh.vertices]
            part_eval.to_mesh_clear()
            rows = []
            for i in border:
                hit, normal, _, _ = skin.find_nearest(points[i])
                rows.append({'h_mm': (points[i] - hit).dot(normal) * 1000, 'z_mm': (points[i].z - floor) * 1000,
                             'd_mm': (points[i] - root).length * 1000, 'inside': inside(skin, points[i])})
            heights[label] = rows
            if label == 'rest':
                lowest = min(p.z for p in points)
        results['sizes'][str(size)] = {
            'root_z': root.z, 'loops': [len(loop) for loop in loops], 'border': heights,
            'below_floor_mm': (floor - lowest) * 1000}
    (out / 'closed.json').write_text(json.dumps(results))


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
    return json.loads((Path(directory) / 'closed.json').read_text())


def failures(data):
    """Every hand-derived expectation the build misses."""
    out = []
    for size in FLOOR_BELOW:
        row = data['sizes'][str(size)]
        if abs(row['root_z'] - ROOT_Z) > 1e-4:
            out.append(f'size {size}: fixture root at z {row["root_z"]:.5f}, expected {ROOT_Z:.5f}')
        rest, lift = row['border']['rest'], row['border']['lift']
        reach = REACH_MM * size
        far = max(r['d_mm'] for r in rest)
        if far > reach:
            out.append(f'size {size}: open border {far:.1f} mm from the root, beyond the window ({reach:.0f} mm)')
        low = min(r['z_mm'] for r in rest)
        if low < FLOOR_CLEARANCE_MM:
            out.append(f'size {size}: open border {low:.1f} mm above the floor, expected at least {FLOOR_CLEARANCE_MM}')
        if row['below_floor_mm'] <= 0:
            out.append(f'size {size}: nothing of the part under the floor (lowest {-row["below_floor_mm"]:.1f} mm above it)')
        for label, rows in (('rest', rest), ('lift', lift)):
            outside = sum(not r['inside'] for r in rows)
            if outside:
                out.append(f'size {size}: {outside} open border vertices outside the body ({label})')
        on_skin = [(a, b) for a, b in zip(rest, lift) if a['inside'] and a['h_mm'] > -ON_SKIN_MM]
        standing = max((a['h_mm'] for a, _ in on_skin), default=-TUCK_MM)
        if standing > -TUCK_MM + STEP_TOLERANCE_MM:
            out.append(f'size {size}: open border up to {standing:.2f} mm off the skin, '
                       f'expected at most {-TUCK_MM + STEP_TOLERANCE_MM:.2f}')
        moved = max((abs(a['h_mm'] - b['h_mm']) for a, b in on_skin), default=0.)
        if moved > LIFT_TOLERANCE_MM:
            out.append(f'size {size}: open border on the skin moves {moved:.3f} mm when the chain lifts, '
                       f'expected at most {LIFT_TOLERANCE_MM}')
    return out


def main():
    with tempfile.TemporaryDirectory(prefix='attached-part-closed-') as directory:
        data = run_blender(str(ROOT / 'app/blender/scripts'), str(Path(directory) / 'new'))
        problems = failures(data)
        assert not problems, problems
        for size in FLOOR_BELOW:
            row = data['sizes'][str(size)]
            rest, lift = row['border']['rest'], row['border']['lift']
            on_skin = [(a, b) for a, b in zip(rest, lift) if a['inside'] and a['h_mm'] > -ON_SKIN_MM]
            print(f'size {size}: open border loops {row["loops"]}, at most', round(max(r['d_mm'] for r in rest), 1),
                  'mm from the root, lowest', round(min(r['z_mm'] for r in rest), 1), 'mm above the floor; part reaches',
                  round(row['below_floor_mm'], 1), 'mm under it;', len(on_skin), 'border vertices on the skin, height max',
                  round(max(a['h_mm'] for a, _ in on_skin), 2), 'mm, moved by the lift',
                  round(max(abs(a['h_mm'] - b['h_mm']) for a, b in on_skin), 4), 'mm')
        # The same checks against the builder before Ruling A65c.
        old = Path(directory) / 'old-scripts'
        old.mkdir()
        for name in ('attached_part.py', '_common.py'):
            source = subprocess.run(['git', '-C', str(ROOT), 'show', f'{OLD_COMMIT}:app/blender/scripts/{name}'],
                                    capture_output=True, text=True, check=True).stdout
            (old / name).write_text(source)
        old_problems = failures(run_blender(str(old), str(Path(directory) / 'old')))
        assert len(old_problems) >= 10, old_problems
        print('old builder', OLD_COMMIT[:9], 'fails', len(old_problems), 'checks, e.g.', old_problems[0])
    print('PASS attached_part closed: the open border stays in the body and under the skin when the chain lifts')


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
