#!/usr/bin/env python3
"""The attached part grows out of the body: its seam with the skin (Ruling A65b).

Usage: ./.venv/bin/python scripts/smoke_attached_part_seam.py
Runs Blender 5.2 on the CPU against the tilted synthetic body of
scripts/smoke_attached_part_placement.py without its ledge (written to a temp
dir); no world, no server, no network.

Fixture skin (metres, front -Y, up +Z): the plane through (0, -.065, 1.0) with
outward normal n = (0, -1, .3)/|.| = (0, -.958, .287), so a point P lies
h = (P - (0, -.065, 1.0)) . n above the skin. The root R sits .006 under it (see
the placement smoke). The attachment region checked is the full body window
around R: |P - R| < body_window.radius .03 x size. A crease is the angle
between the part's shading normal and n, taken without its sign (min(a,
180 - a)): a double-sided material shades a reversed face from its other side.

Hand-derived expectations from the declared defaults (k_body .016,
skin_sink .0008, seam.lift .0004, seam.band .006, seam.normal_band .012):
- Step: every open border vertex there is in the strip (its distance along the
  mesh to a border is 0, strip = 1), so the seam pass moves one at h > lift by
  (h - lift) x max(s(..), 1) x max(fillet, 1) = h - lift: it ends exactly lift
  above the skin. A border vertex at or under lift stays where it is. So no open
  border vertex stands more than lift + .05 mm (export rounding) = 0.45 mm
  above the skin (the target was a step of at most 1 mm).
- Border crease: there the normal weight is max(s(1 - 0/.012), 1) x 1 = 1, so
  the shading normal IS the body's corner normal, here n: 0 degrees, allowed
  1 degree for the custom-normal encoding.
- Crossing crease, where the fillet passes through the skin: the field is
  U = smin(a, b, k) = min(a, b) - (k - |a - b|)^2 / 4k with a the part's
  distance and b = h + skin_sink. On the skin b = .0008, so U = 0 needs
  k - a + b = 2 sqrt(k b) = .00716, i.e. a = 9.64 mm, and grad U =
  (1 - .224) grad b + .224 grad a (.224 = .00716 / 2k). grad b = n and
  grad a a unit vector, so the surface normal lies within asin(.224/.776) =
  16.8 degrees of n. The seam pass (h <= lift there) turns the shading normal
  towards n with the fillet share s(a/k) = s(.6025) = .652, which leaves
  atan(.348 sin 16.8 / (.348 cos 16.8 + .652)) = 5.8 degrees at most; allowed
  8 degrees for the 2 mm voxel net, smoothing and decimation (target: p95 at
  most 15 degrees).
- Orientation: the faces wind counter-clockwise seen from outside, so at the
  apex (the vertex farthest from the root) the shading normal points away from
  the root: (N . (apex - R)/|apex - R|) > .5 (a rounded tip, nearly 1).

Old-code proof: the builder at commit a269ae4d218c2510fa6ed35e48a8b5995aca8357
(Ruling A65) sinks the fillet 3 mm (b = .003 on the skin: .433 grad a, up to
asin(.433/.567) = 49.8 degrees), smooths the open border off the skin (kept from
.6 mm up, then curled by the Smooth modifier), shades it with the fillet's own
normals and winds the faces inward. Its border stands above 0.45 mm, its
border and crossing normals tilt beyond the limits and its apex normal points
at the root: at least two sizes x three checks fail there.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BLENDER = Path.home() / 'tools/blender-5.2.2-linux-x64/blender'
OLD_COMMIT = 'a269ae4d218c2510fa6ed35e48a8b5995aca8357'
SIZES = (1.0, 1.6)
LIFT_MM, STEP_TOLERANCE_MM, CREASE_LIMIT_DEG, CROSSING_LIMIT_DEG = .4, .05, 1.0, 8.0


def blender_side(scripts, directory):
    import bpy
    import numpy as np
    from mathutils import Vector
    sys.path.insert(0, scripts)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import attached_part
    from smoke_attached_part_placement import make_fixture
    out = Path(directory)
    fixture, root, _ = make_fixture(scripts, out, ledge=False)
    plane_normal = Vector((0, -1, .3)).normalized()
    plane_point = Vector((0, -.065, 1.0))
    window = attached_part.DEFAULTS['body_window']['radius']
    chain = [{'bone': 'PartLink' + str(i + 1), 'parent': 'Hips' if i == 0 else 'PartLink' + str(i)} for i in range(5)]
    companion = {'id': 'pods', 'op': 'attached_part_bone', 'chains': [[{'bone': 'PartPods', 'parent': 'Hips'}]], 'params': {}}
    results = {'root': list(root), 'sizes': {}}
    for size in SIZES:
        group = {'id': 'part', 'op': 'attached_part', 'chains': [chain],
                 'params': {'size_factor': size, 'voxel': .002, 'texture': {'bake': 128}}}
        target = out / ('size-' + str(size))
        target.mkdir()
        attached_part.attached_part({'inputs': {'model': str(fixture)},
                                     'params': {'groups': [group, companion]}, 'out_dir': str(target)})
        part = next(o for o in bpy.context.scene.objects if o.get('attached_part') == 'part')
        me = part.data
        mw, nm = part.matrix_world, part.matrix_world.to_3x3()
        faces_per_edge = {}
        for poly in me.polygons:
            for edge in poly.edge_keys:
                faces_per_edge[edge] = faces_per_edge.get(edge, 0) + 1
        border = {v for edge, count in faces_per_edge.items() if count == 1 for v in edge}
        # Shading normals: the corner normals (custom normals where set), per vertex.
        shade = [Vector() for _ in me.vertices]
        for loop, corner in zip(me.loops, me.corner_normals):
            shade[loop.vertex_index] += corner.vector
        rows = []
        for i in border:
            point = mw @ me.vertices[i].co
            if (point - root).length >= window * size:
                continue
            normal = (nm @ shade[i]).normalized()
            angle = float(np.degrees(normal.angle(plane_normal)))
            rows.append({'h_mm': (point - plane_point).dot(plane_normal) * 1000,
                         'crease_deg': min(angle, 180 - angle)})
        # Where the fillet passes through the skin: edges whose ends lie on both sides.
        crossing = []
        height = [(mw @ v.co - plane_point).dot(plane_normal) for v in me.vertices]
        for edge in me.edges:
            a, b = edge.vertices
            if (height[a] > 0) == (height[b] > 0):
                continue
            t = height[a] / (height[a] - height[b])
            point = (mw @ me.vertices[a].co).lerp(mw @ me.vertices[b].co, t)
            if (point - root).length >= window * size:
                continue
            normal = (nm @ shade[a].normalized().lerp(shade[b].normalized(), t)).normalized()
            angle = float(np.degrees(normal.angle(plane_normal)))
            crossing.append(min(angle, 180 - angle))
        apex = max(me.vertices, key=lambda v: (mw @ v.co - root).length)
        apex_dir = (mw @ apex.co - root).normalized()
        results['sizes'][str(size)] = {'border': rows, 'crossing': crossing,
                                       'apex_facing': (nm @ shade[apex.index]).normalized().dot(apex_dir)}
    (out / 'seam.json').write_text(json.dumps(results))


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
    return json.loads((Path(directory) / 'seam.json').read_text())


def failures(data):
    """Every hand-derived expectation the build misses."""
    out = []
    for size in SIZES:
        row = data['sizes'][str(size)]
        border = row['border']
        if not border:
            out.append(f'size {size}: no open border on the skin around the root')
            continue
        step = max(r['h_mm'] for r in border)
        if step > LIFT_MM + STEP_TOLERANCE_MM:
            out.append(f'size {size}: open border up to {step:.2f} mm above the skin, '
                       f'expected at most {LIFT_MM + STEP_TOLERANCE_MM:.2f}')
        on_skin = [r['crease_deg'] for r in border if r['h_mm'] > -.1]
        crease = max(on_skin) if on_skin else 0.
        if crease > CREASE_LIMIT_DEG:
            out.append(f'size {size}: border normal {crease:.1f} deg off the skin normal, expected at most {CREASE_LIMIT_DEG}')
        crossing = max(row['crossing'], default=0.)
        if crossing > CROSSING_LIMIT_DEG:
            out.append(f'size {size}: normal where the fillet crosses the skin {crossing:.1f} deg off the skin normal, '
                       f'expected at most {CROSSING_LIMIT_DEG}')
        if row['apex_facing'] <= .5:
            out.append(f'size {size}: apex normal . outward {row["apex_facing"]:.2f}, expected above 0.5')
    return out


def main():
    with tempfile.TemporaryDirectory(prefix='attached-part-seam-') as directory:
        data = run_blender(str(ROOT / 'app/blender/scripts'), str(Path(directory) / 'new'))
        problems = failures(data)
        assert not problems, problems
        for size in SIZES:
            row = data['sizes'][str(size)]
            border = row['border']
            print(f'size {size}: {len(border)} border vertices on the skin around the root, step max',
                  round(max(r['h_mm'] for r in border), 2), 'mm, border crease max',
                  round(max((r['crease_deg'] for r in border if r['h_mm'] > -.1), default=0.), 2),
                  'deg; crossing crease max', round(max(row['crossing'], default=0.), 2), 'deg over',
                  len(row['crossing']), 'edges; apex facing', round(row['apex_facing'], 2))
        # The same checks against the builder before Ruling A65b.
        old = Path(directory) / 'old-scripts'
        old.mkdir()
        for name in ('attached_part.py', '_common.py'):
            source = subprocess.run(['git', '-C', str(ROOT), 'show', f'{OLD_COMMIT}:app/blender/scripts/{name}'],
                                    capture_output=True, text=True, check=True).stdout
            (old / name).write_text(source)
        old_problems = failures(run_blender(str(old), str(Path(directory) / 'old')))
        assert len(old_problems) >= 6, old_problems
        print('old builder', OLD_COMMIT[:9], 'fails', len(old_problems), 'checks, e.g.', old_problems[0])
    print('PASS attached_part seam: the border lies on the skin and shades with the body')


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
