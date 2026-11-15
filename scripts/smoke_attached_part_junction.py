#!/usr/bin/env python3
"""The pouch's upper front, where the lifted sweep leaves it, shades without a midline band (Ruling A88).

Usage: ./.venv/bin/python scripts/smoke_attached_part_junction.py
Runs Blender 5.2 on the CPU against the synthetic body of
scripts/smoke_attached_part_placement.py (with its ledge, so nothing but the
sweep hides the pouch), at size 1.45 with the pouch's folds and raphe off (the
shape of the union alone); written to a temp dir; no world, no server, no
network. Each build takes about a minute.

Measured as the client shades it: the output GLB is imported again, the first
chain link turned -90 degrees about its x axis (the acceptance smoke's lift 90),
and the file normals skinned linearly with the same weights as the positions.
Rays from the front (+y) on a .5 mm grid hit the part; the normal there is
the barycentric blend of the three skinned vertex normals (smooth shading).
The upper band of the pouch's front runs from 55 % of the pouch's posed height
(vertices whose largest weight is the pouch bone) to 4 mm above its top; per
column the band averages n_x.

Hand-derived expectations:
- No midline band. The tilt angle a(x) = asin(n_x) is fitted with a straight
  line on each flank (4 to 10 mm from the midline) and both lines are
  extrapolated to x = 0. A surface that rolls evenly across the midline has
  one line on both flanks: jump 0. A ridge or a valley there turns the normal
  by the jump across a few mm. For any light L, Lambert n.L changes by at most
  the normal's turn in radians, so the jump bounds the band's Lambert step:
  at most .04 (the Ruling's limit), and inside |x| < 4 mm the tilt stays within
  .04 of the mean of the two lines.
- The underside ridge (ridges entry with phase pi) starts where the web is gone:
  at its start t0 the web radius pod_web.blend s w^2 (3 - 2 w),
  w = 1 - t0 / pod_web.until, is .016 x 1.45 x .0909^2 x 2.82 = .37 mm at
  t0 .5 and until .55, under 1 mm. With t0 .1 and until .4 it was
  .016 x 1.45 x .75^2 x 1.5 = 19.6 mm: the ridge ran through the junction.
- The pouch keeps its size: the width and height of its vertices outside the
  skin, and the front-to-back depth of its lowest quarter on each side (the
  tips), stay within 3 % of the old builder's (the change is on the sweep's
  underside and the web, not the ellipsoids).

Old-code proof: the builder at commit e3b7795bbc21fde1051d6a95ae0309715a6a423c
(Ruling A65e) starts the underside ridge at t0 .1 with a capsule of radius
rv = (.0007 + (.0005 - .0007) (t - .1) / .608) x 1.45, about 1 mm, whose centre
lies .25 rv outside the sweep's radius: a crest at least 1.25 rv = 1.2 mm high
over a base about rv + ridge_blend s / 2 = 2.3 mm to each side, a turn of
2 atan(1.2 / 2.3) = .96 rad at rest. Lifted, the junction it crosses is
stretched over the band and the crest's turn spreads (measured on the seven
stored models: .17 to .31 rad), so the proof demands only 2.5 times the limit,
.1 rad, and the web check fails there too.
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
OLD_COMMIT = 'e3b7795bbc21fde1051d6a95ae0309715a6a423c'
SIZE, TURN_MAX, OLD_TURN_MIN, WEB_AT_RIDGE_MAX, SIZE_TOLERANCE = 1.45, .04, .1, .001, .03


def midline_turn(xs, tilt, mid=.004, flank=.010):
    """Jump between the two flank lines at x = 0 and the largest offset from
    their mean inside |x| < mid (see the docstring); None without flanks."""
    import numpy as np
    fits = []
    for side in (-1, 1):
        sel = (side * xs >= mid - 1e-9) & (side * xs <= flank + 1e-9) & ~np.isnan(tilt)
        if sel.sum() < 4:
            return None
        fits.append(np.polyfit(xs[sel], tilt[sel], 1))
    jump = np.polyval(fits[1], 0) - np.polyval(fits[0], 0)
    inner = (abs(xs) < mid) & ~np.isnan(tilt)
    mean = .5 * (np.polyval(fits[0], xs[inner]) + np.polyval(fits[1], xs[inner]))
    offset = float(np.max(abs(tilt[inner] - mean))) if inner.any() else 0.
    return float(max(abs(jump), offset))


def blender_side(scripts, directory):
    import bpy
    import numpy as np
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    sys.path.insert(0, scripts)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _common
    import attached_part
    from smoke_attached_part_placement import make_fixture
    out = Path(directory)
    settings = attached_part.parameters({})
    underside = [r for r in settings['ridges'] if abs(r['phase'] - math.pi) < 1e-6]
    web = settings['pod_web']
    chain = [{'bone': 'PartLink' + str(i + 1), 'parent': 'Hips' if i == 0 else 'PartLink' + str(i)} for i in range(5)]
    companion = {'id': 'pods', 'op': 'attached_part_bone', 'chains': [[{'bone': 'PartPods', 'parent': 'Hips'}]], 'params': {}}
    fixture, root, _ = make_fixture(scripts, out, ledge=True)
    group = {'id': 'part', 'op': 'attached_part', 'chains': [chain],
             'params': {'size_factor': SIZE, 'texture': {'bake': 128},
                        'pods': {'folds': {'depth': 0, 'raphe': 0}}}}
    attached_part.attached_part({'inputs': {'model': str(fixture)},
                                 'params': {'groups': [group, companion]}, 'out_dir': str(out)})
    _common.reset_scene()
    _common.import_model(str(out / 'model.glb'))
    arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    part = next(o for o in bpy.context.scene.objects if o.get('attached_part') == 'part')
    body = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and not o.get('attached_part'))
    root = np.array(tuple(root))
    me = part.data
    count = len(me.vertices)
    co = np.array([part.matrix_world @ v.co for v in me.vertices])
    normals = np.zeros((count, 3))
    for loop in me.loops:
        normals[loop.vertex_index] += np.array(me.corner_normals[loop.index].vector)
    normals = normals @ np.array(part.matrix_world.to_3x3()).T
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    names = [g.name for g in part.vertex_groups]
    weights = []
    for v in me.vertices:
        pairs = [(names[g.group], g.weight) for g in v.groups if g.weight > 0]
        total = sum(w for _, w in pairs) or 1
        weights.append([(n, w / total) for n, w in pairs])
    pouch_bone = next(n for n in names if n.endswith('PartPods'))
    pouch = np.array([max(ws, key=lambda p: p[1])[0] == pouch_bone if ws else False for ws in weights])
    me.calc_loop_triangles()
    tris = np.array([t.vertices[:] for t in me.loop_triangles])
    skin = BVHTree.FromPolygons([body.matrix_world @ v.co for v in body.data.vertices],
                                [p.vertices[:] for p in body.data.polygons])

    def outside(p):
        q, n, _, _ = skin.find_nearest(Vector(p))
        return (Vector(p) - q).dot(n) > .0003
    out_skin = np.array([outside(p) for p in co])
    rel = co[pouch & out_skin] - root
    lowest = rel[rel[:, 2] < rel[:, 2].min() + .25 * (rel[:, 2].max() - rel[:, 2].min())]
    shape = {'width': float(np.ptp(rel[:, 0])), 'height': float(np.ptp(rel[:, 2])),
             'tip_left': float(np.ptp(lowest[lowest[:, 0] > .002][:, 1])),
             'tip_right': float(np.ptp(lowest[lowest[:, 0] < -.002][:, 1]))}
    # Lift 90: linear blend skinning of positions and file normals.
    for pb in arm.pose.bones:
        pb.rotation_mode = 'XYZ'
        pb.rotation_euler = (0, 0, 0)
    arm.pose.bones[next(b.name for b in arm.pose.bones if b.name.endswith('PartLink1'))].rotation_euler[0] = math.radians(-90)
    bpy.context.view_layer.update()
    A = np.array(arm.matrix_world)
    skinning = {pb.name: A @ np.array(pb.matrix) @ np.linalg.inv(np.array(pb.bone.matrix_local)) @ np.linalg.inv(A)
                for pb in arm.pose.bones}
    posed, posed_n = np.zeros_like(co), np.zeros_like(normals)
    for i, ws in enumerate(weights):
        M = sum(w * skinning[n] for n, w in ws) if ws else np.eye(4)
        posed[i] = M[:3, :3] @ co[i] + M[:3, 3]
        posed_n[i] = M[:3, :3] @ normals[i]
    posed_n /= np.linalg.norm(posed_n, axis=1)[:, None]
    tree = BVHTree.FromPolygons([Vector(p) for p in posed], [tuple(t) for t in tris])
    z = posed[pouch & out_skin, 2] - root[2]
    lo, hi = z.min() + .55 * (z.max() - z.min()), z.max() + .004
    xs = np.arange(-.012, .01201, .0005)
    columns = [[] for _ in xs]
    for zc in np.arange(lo, hi, .0005):
        for k, x in enumerate(xs):
            origin = root + np.array([x, -.3, zc])
            hit, _, face, _ = tree.ray_cast(Vector(origin), Vector((0, 1, 0)), .6)
            if hit is None:
                continue
            a, b, c = tris[face]
            v0, v1, v2 = posed[b] - posed[a], posed[c] - posed[a], np.array(hit) - posed[a]
            d00, d01, d11, d20, d21 = v0 @ v0, v0 @ v1, v1 @ v1, v2 @ v0, v2 @ v1
            den = d00 * d11 - d01 * d01
            if abs(den) < 1e-20:
                continue
            wb, wc = (d11 * d20 - d01 * d21) / den, (d00 * d21 - d01 * d20) / den
            n = (1 - wb - wc) * posed_n[a] + wb * posed_n[b] + wc * posed_n[c]
            columns[k].append(n[0] / np.linalg.norm(n))
    most = max(len(c) for c in columns)
    nx = np.array([np.mean(c) if len(c) >= max(3, .3 * most) else np.nan for c in columns])
    turn = midline_turn(xs, np.arcsin(np.clip(nx, -1, 1)))
    (out / 'junction.json').write_text(json.dumps({
        'turn': turn, 'rays': int(sum(len(c) for c in columns)), 'band_mm': [lo * 1000, hi * 1000], **shape,
        'underside_t0': [r['t0'] for r in underside], 'web_blend': web['blend'], 'web_until': web['until']}))


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
    return json.loads((Path(directory) / 'junction.json').read_text())


def web_at(data, t0):
    w = min(max(1 - t0 / data['web_until'], 0), 1)
    return data['web_blend'] * SIZE * w * w * (3 - 2 * w)


def failures(data, reference=None, turn_max=TURN_MAX):
    """Every hand-derived expectation the build misses."""
    out = []
    if data['turn'] is None or data['rays'] < 500:
        out.append(f'the band was not sampled ({data["rays"]} rays)')
    elif data['turn'] > turn_max:
        out.append(f'midline turn {data["turn"]:.3f} rad in the upper band, expected at most {turn_max}')
    for t0 in data['underside_t0']:
        if web_at(data, t0) > WEB_AT_RIDGE_MAX:
            out.append(f'the underside ridge starts at t {t0} inside a {web_at(data, t0) * 1000:.1f} mm web')
    if reference:
        for key in ('width', 'height', 'tip_left', 'tip_right'):
            if abs(data[key] / reference[key] - 1) > SIZE_TOLERANCE:
                out.append(f'pouch {key} {data[key] * 1000:.1f} mm, old {reference[key] * 1000:.1f} mm')
    return out


def main():
    with tempfile.TemporaryDirectory(prefix='attached-part-junction-') as directory:
        old = Path(directory) / 'old-scripts'
        old.mkdir()
        for name in ('attached_part.py', '_common.py'):
            source = subprocess.run(['git', '-C', str(ROOT), 'show', f'{OLD_COMMIT}:app/blender/scripts/{name}'],
                                    capture_output=True, text=True, check=True).stdout
            (old / name).write_text(source)
        before = run_blender(str(old), str(Path(directory) / 'old'))
        data = run_blender(str(ROOT / 'app/blender/scripts'), str(Path(directory) / 'new'))
        problems = failures(data, before)
        assert not problems, problems
        print(f'size {SIZE}: midline turn {data["turn"]:.3f} rad over {data["rays"]} rays '
              f'(band {data["band_mm"][0]:.1f} to {data["band_mm"][1]:.1f} mm), pouch '
              f'{data["width"] * 1000:.1f} x {data["height"] * 1000:.1f} mm, tips {data["tip_left"] * 1000:.1f} / '
              f'{data["tip_right"] * 1000:.1f} mm (old {before["width"] * 1000:.1f} x {before["height"] * 1000:.1f}, '
              f'{before["tip_left"] * 1000:.1f} / {before["tip_right"] * 1000:.1f})')
        old_problems = failures(before, turn_max=OLD_TURN_MIN)
        assert len(old_problems) >= 2, (before['turn'], old_problems)
        print('old builder', OLD_COMMIT[:9], 'fails', len(old_problems), 'checks, e.g.', old_problems[0])
    print('PASS attached_part junction: no midline band where the lifted sweep leaves the pouch, size kept')


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
