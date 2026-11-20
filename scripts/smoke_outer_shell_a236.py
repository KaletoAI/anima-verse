#!/usr/bin/env python3
"""Hair lying off the skin is no collider and no skin: the air-gap rule of the template drape (A236).

Usage: ./.venv/bin/python scripts/smoke_outer_shell_a236.py
Runs Blender 5.2 on the CPU against hand-built boxes; no world, no server, no network.

Geometry (world = object space, closed boxes wound outward, y and z from -.05 to .05):
  body  x -.10 .. .10
  hair  x  .12 .. .14     (an air gap of .02 m from the body's face at x = .10)
  fold  x  .105 .. .125 at y .3 (a second body at y .3 with its own slab .005 m off it)
Rays start at the origin (inside the body) and run along +x — ``_air_gap(tree, q, c)``, hand-derived:
  [1] c = (.10, 0, 0) the skin itself                -> 0 (the first exit IS the point)
  [2] c = (.12, 0, 0) the hair's inner face          -> .02 (exit .10, entry .12)
  [3] c = (.14, 0, 0) the hair's outer face          -> .02
  [4] c = (.20, 0, 0) floating beyond the hair       -> max(.02, .20 - .14) = .06
  [5] c = (.13, 0, 0) inside the hair slab           -> .02
  [6] from (0, .3, 0) to (.125, .3, 0), a slab .005 off the skin -> .005, under OUTER_GAP_M .008 (fused, kept)
  [7] OUTER_GAP_M is .008 (above the collider voxel .005, which fuses anything closer anyway)
A grazing re-entry: a ledge x .12 .. .40, y .015 .. .05 (z -.05 .. .05 shifted to z .3, like a third body there); the
ray from (0, 0, .3) to (.40, .02, .3) has slope .02 / .40 = .05 in y, so it leaves the body at x .10 and enters the
ledge's underside (normal -y) with cosine .05 / sqrt(1 + .0025) = .0499 < OUTER_ENTRY_COS .3:
  [7a] that is no air gap (a ray skimming a dip of the body): gap 0 (the end point lies inside the ledge);
  [7b] OUTER_ENTRY_COS is .3.
Armhole bottom (``garment_template_build._exit_out`` from inside an arm box z -.03 .. .03 straight down; a sleeve slab
z -.06 .. -.056 under it, .026 of air; a hip box z -.5 .. -.4):
  [17] default gap (LAYER_GAP_M .015 < .026): .03, the arm's own underside;
  [18] gap ARM_LAYER_GAP_M: carried through the sleeve -> .06; the hip (.34 of air) stops it;
  [19] ARM_LAYER_GAP_M is .08.
Source checks: [8] measure_pose skips the recorded shell vertices; [9] rest_collider, skinned_collider and the drape's
own remesh drop the shells; [10] the body + lower-layer collider judges them on a body-only remesh (layered).
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
    import bpy  # noqa: F401
    from mathutils.bvhtree import BVHTree
    sys.path.insert(0, scripts)
    import garment_template_drape as gd
    verts, faces = [], []

    def box(x0, x1, y0, y1):
        s = len(verts)
        for x in (x0, x1):
            for y in (y0, y1):
                for z in (-.05, .05):
                    verts.append((x, y, z))
        # vertex index = s + 4*ix + 2*iy + iz; quads wound outward
        faces.extend([(s + 0, s + 1, s + 3, s + 2), (s + 4, s + 6, s + 7, s + 5),
                      (s + 0, s + 4, s + 5, s + 1), (s + 2, s + 3, s + 7, s + 6),
                      (s + 0, s + 2, s + 6, s + 4), (s + 1, s + 5, s + 7, s + 3)])
    box(-.10, .10, -.05, .05)
    box(.12, .14, -.05, .05)
    box(-.10, .10, .25, .35)
    box(.105, .125, .25, .35)
    tree = BVHTree.FromPolygons(verts, faces)
    o = (0.0, 0.0, 0.0)
    res = {k: gd._air_gap(tree, o, c) for k, c in (("skin", (.10, 0, 0)), ("hair_in", (.12, 0, 0)),
                                                    ("hair_out", (.14, 0, 0)), ("float", (.20, 0, 0)),
                                                    ("inside", (.13, 0, 0)))}
    res["fold"] = gd._air_gap(tree, (0.0, .3, 0.0), (.125, .3, 0))
    res["gap_m"] = gd.OUTER_GAP_M
    # a ledge x .12 .. .40, y .015 .. .05 beside a third body at z .3: the ray from (0, 0, .3) to (.40, .02, .3)
    # leaves the body at x .10 and enters the ledge's underside (normal -y) at a grazing angle
    box(-.10, .10, -.05, .05)
    for k in range(len(verts) - 8, len(verts)):
        verts[k] = (verts[k][0], verts[k][1], verts[k][2] + .3)
    box(.12, .40, .015, .05)
    for k in range(len(verts) - 8, len(verts)):
        verts[k] = (verts[k][0], verts[k][1], verts[k][2] + .3)
    tree = BVHTree.FromPolygons(verts, faces)
    res["graze"] = gd._air_gap(tree, (0.0, 0.0, .3), (.40, .02, .3))
    res["entry_cos"] = gd.OUTER_ENTRY_COS
    import garment_template_build as gb
    # an arm (x 1 .. 1.2, z -.03 .. .03) and a sleeve hanging .026 under it (z -.06 .. -.056); the hip far below
    av, af = [], []
    for (x0, x1, z0, z1) in ((1.0, 1.2, -.03, .03), (1.0, 1.2, -.06, -.056), (1.0, 1.2, -.5, -.4)):
        s0 = len(av)
        for x in (x0, x1):
            for y in (-.05, .05):
                for z in (z0, z1):
                    av.append((x, y, z))
        af.extend([(s0 + 0, s0 + 1, s0 + 3, s0 + 2), (s0 + 4, s0 + 6, s0 + 7, s0 + 5),
                   (s0 + 0, s0 + 4, s0 + 5, s0 + 1), (s0 + 2, s0 + 3, s0 + 7, s0 + 6),
                   (s0 + 0, s0 + 2, s0 + 6, s0 + 4), (s0 + 1, s0 + 5, s0 + 7, s0 + 3)])
    at = BVHTree.FromPolygons(av, af)
    res["under_body"] = gb._exit_out(at, (1.1, 0, 0), (0, 0, -1), 0.3)[0]
    res["under_layers"] = gb._exit_out(at, (1.1, 0, 0), (0, 0, -1), 0.3, gap=gb.ARM_LAYER_GAP_M)[0]
    res["arm_gap"] = gb.ARM_LAYER_GAP_M
    Path(out).write_text(json.dumps(res))


def main():
    failures = []

    def check(label, ok, detail=''):
        print(('ok   ' if ok else 'FAIL ') + label + (f'  ({detail})' if detail else ''))
        if not ok:
            failures.append(label)
    with tempfile.TemporaryDirectory(prefix='a236-shell-') as directory:
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
    near = lambda a, b: abs(a - b) < 2e-4  # noqa: E731 — the ray steps 1e-4 past every hit
    check('[1] skin: gap 0', near(d['skin'], 0.0), d['skin'])
    check('[2] hair inner face: gap .02', near(d['hair_in'], .02), d['hair_in'])
    check('[3] hair outer face: gap .02', near(d['hair_out'], .02), d['hair_out'])
    check('[4] floating point: gap .06', near(d['float'], .06), d['float'])
    check('[5] inside the hair: gap .02', near(d['inside'], .02), d['inside'])
    check('[6] slab .005 off the skin: gap .005 < OUTER_GAP_M', near(d['fold'], .005) and d['fold'] < d['gap_m'],
          d['fold'])
    check('[7] OUTER_GAP_M .008', d['gap_m'] == .008, d['gap_m'])
    check('[7a] a grazing re-entry (cosine .05) is no air gap: gap 0', near(d['graze'], 0.0), d['graze'])
    check('[7b] OUTER_ENTRY_COS .3', d['entry_cos'] == .3, d['entry_cos'])
    check('[17] under the arm, LAYER_GAP_M: the arm itself, .03', near(d['under_body'], .03), d['under_body'])
    check('[18] under the arm, ARM_LAYER_GAP_M: through the hanging sleeve, .06',
          near(d['under_layers'], .06), d['under_layers'])
    check('[19] ARM_LAYER_GAP_M .08 (the hip .34 below is never reached)', d['arm_gap'] == .08, d['arm_gap'])
    src = (ROOT / 'app/blender/scripts/garment_template_drape.py').read_text()
    check('[8] measure_pose skips the shell vertices', 'shell = OUTER_BODY.get(body.name)' in src
          and 'if shell is not None and shell[i]:' in src)
    check('[9] rest / skinned / drape colliders drop the shells',
          src.count('drop_outer_shells(col, body, layered=') == 3)
    check('[10] layered collider judged on a body-only remesh',
          'layered=bool(extra), faces=faces, record=True' in src and 'layered=bool(extra), faces=collider_faces' in src)
    import shutil
    scratch = Path(tempfile.mkdtemp(prefix='a236-text-'))
    try:
        os.environ['STORAGE_DIR'] = str(scratch / 'world')
        os.environ['INSTANCE_DIR'] = str(scratch / 'instance')
        sys.path.insert(0, str(ROOT))
        from app.core import paths
        paths.init(scratch / 'world')
        paths.init_instance(scratch / 'instance')
        from app.core import garment_template as gt

        def rec(kind, z, **extra):
            params, _e = gt.validate_params({'kind': kind, **extra})
            return {'params': params, 'metrics': {'measure': {'shoulder_y': 1.2991},
                                                  'drape': {'stretch_at': {'z': z}} if z is not None else {}}}
        check('[11] top at 1.35: neck sentence', gt.stretch_line(rec('top', 1.35)) == 'stretch_max_neck')
        check('[12] jacket at 1.288: neck sentence', gt.stretch_line(rec('jacket', 1.288)) == 'stretch_max_neck')
        check('[13] top at 1.20: plain sentence', gt.stretch_line(rec('top', 1.20)) == 'stretch_max')
        check('[14] skirt at 1.35: plain sentence', gt.stretch_line(rec('skirt', 1.35)) == 'stretch_max')
        check('[15] no stretch_at: plain sentence', gt.stretch_line(rec('top', None)) == 'stretch_max')
        info = gt.failure_info({**rec('top', 1.35), 'rows': [{'check': 'stretch_max', 'value': 2.46, 'limit': 1.3,
                                                             'ok': False, 'gate': True}]})
        check('[16] failure_info speaks the neck sentence', info['lines'] == [
            {'text': gt.FAILURE_SENTENCES['stretch_max_neck'], 'values': {'value': '2.46', 'limit': '1.3'}}],
            info['lines'])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if failures:
        raise SystemExit('FAIL a236 outer shell: ' + ', '.join(failures))
    print('PASS a236 outer shell: hair lying off the skin is measured by its air gap')


if __name__ == '__main__':
    if '--blender' in sys.argv:
        i = sys.argv.index('--blender')
        blender_side(sys.argv[i + 1], sys.argv[i + 2])
    else:
        main()
