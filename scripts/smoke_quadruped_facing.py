#!/usr/bin/env python3
"""The quadruped rigger finds the head end of an animal whose tail is raised.

The old rule took the end with the higher top as the head. A fox walking with
its tail up therefore got the whole fox skeleton back to front, and every later
test still passed (review 04b#1). ``facing`` now decides by two signals that
pitching the tail or the head in the body's mid-plane cannot change, and a
skinning acceptance check catches a skeleton that still ends up reversed.

Pure part (always runs, no Blender). A synthetic creature, head towards -Y:
a torso tube (y -0.5..0.5, half widths 0.2 x / 0.15 z, centre z 0.75), a
head tube (y -0.5..-0.85, half widths 0.18 / 0.12, centre z 0.85), a thin
tail (radius 0.04, length 0.6) from (0, 0.5, 0.8) pitched up by a, and four
leg columns (radius 0.04, x +-0.15, y +-0.35) whose three lowest rings
(z 0, 0.02, 0.04) sit 0.06 towards the head: the toes.
- Rotating the tail or the head about X changes neither the area of a
  triangle nor its |x|, so the lateral signal keeps its sign (head 0.18 wide
  against a tail 0.04 wide); the toes give the legs a positive lean. Expected
  facing = +1 for a = 0, 30, 60, 90 degrees, for the tail curled over the back
  and for the head pitched 40 degrees down; -1 for each of them turned 180
  degrees about Z.
- Old rule, by hand: head top z = 0.85 + 0.12 = 0.97. At a = 30 the tail top is
  0.8 + 0.6 sin 30 + 0.04 cos 30 = 1.135 at y = 0.5 + 0.6 cos 30 + 0.02 = 1.04,
  the far end of the body, inside its last 15 %: 1.135 > 0.97 flips the animal.
  At a = 0 the tail top is 0.84 < 0.97: no flip. The old rule, inlined below,
  must give exactly these two answers.
- A creature symmetric under y -> -y (a second tail instead of the head, the
  hind toes pointing to +Y) has a lateral log ratio of 0 and a lean of 0:
  NotApplicable "facing ambiguous". A wide head at -Y with every toe pointing
  to +Y makes the signals disagree: NotApplicable too.
- skinned_spread: one triangle owned by the head bones with |x| 0.3 at every
  corner, one owned by Tail_Mid at |x| 0.1: spreads 0.3 and 0.1. Owner swap:
  0.1 and 0.3, which the skin check rejects.

Blender part (skips when no Blender 5.2-5.x is found). The shipped fox and
posed copies of it (tail raised 30/45/60/90 degrees, curled over the back,
head lowered to graze), each also turned 180 degrees about Z, run through
``run`` in-process. The input's nose is the vertex furthest along the input's
own facing; after the fit the same vertex index must lie nearer the Head.tip
bone than Tail_Tip, and the head bones must own it (weight > .5). A run with
``facing`` inverted must end NotApplicable "reversed skeleton" (the check that
would have caught the reviewed failure). Through ``runner.run`` (the job
directory the server uses): the fox reports its progress stages up to
"exporting" into the progress file (review 04b#3), and the symmetric creature
comes back ok False with data.not_applicable.
Usage: ./.venv/bin/python scripts/smoke_quadruped_facing.py [--pure-only]
"""
import ast
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SCRIPT = ROOT / 'app/blender/scripts/quadruped_rig.py'
PURE = {'NotApplicable', 'landmarks', 'slice_at', 'trace_leg', 'facing', 'skinned_spread'}
CONSTANTS = {'LEGS', 'FACING_LATERAL_MIN', 'FACING_LEAN_MIN', 'HEAD_BONES'}


def production():
    """The production NumPy helpers, compiled from the script without bpy."""
    tree = ast.parse(SCRIPT.read_text())
    body = [n for n in tree.body
            if (isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in PURE)
            or (isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in CONSTANTS for t in n.targets))]
    scope = {'np': np, 'math': math, 'json': json}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(SCRIPT), 'exec'), scope)
    assert PURE | CONSTANTS <= set(scope), sorted(PURE | CONSTANTS - set(scope))
    return scope


def tube(centres, u, w, ra, rb, sides=8):
    """Rings of ``sides`` vertices around each centre, joined by triangles.
    ``w`` is one vector or one per centre (the ring's second axis)."""
    angle = np.linspace(0, 2 * np.pi, sides, endpoint=False)
    ws = w if isinstance(w, list) else [w] * len(centres)
    rings = [c + ra * np.cos(angle)[:, None] * u + rb * np.sin(angle)[:, None] * n
             for c, n in zip(centres, ws)]
    tris = []
    for i in range(len(centres) - 1):
        for k in range(sides):
            a, b = i * sides + k, i * sides + (k + 1) % sides
            tris += [(a, b, b + sides), (a, b + sides, a + sides)]
    return np.concatenate(rings), np.array(tris)


def creature(tail_deg=0., curl=False, head_down=0., kind='normal'):
    """The synthetic animal of the docstring (head towards -Y)."""
    parts = []
    x, y, z = np.eye(3)
    steps = np.arange(-.5, .5001, .05)
    parts.append(tube([np.array((0, s, .75)) for s in steps], x, z, .2, .15))

    def appendage(base, length, ra, rb, pitch, direction):
        """A tube from ``base`` along ``direction``*Y pitched up by ``pitch``
        (a curled tail turns a further 17.5 degrees per segment after two)."""
        centres, normals = [], []
        d = np.array((0, direction * math.cos(pitch), math.sin(pitch)))
        p = np.array(base, dtype=float)
        for i in range(13):
            centres.append(p.copy())
            normals.append(np.cross(d, x))
            p = p + d * length / 12
            if curl and direction > 0 and i >= 2:
                c, s = math.cos(math.radians(17.5)), math.sin(math.radians(17.5))
                d = np.array((0, c * d[1] - s * d[2], s * d[1] + c * d[2]))
        return tube(centres, x, normals, ra, rb)

    if kind == 'symmetric':
        parts.append(appendage((0, -.5, .8), .6, .04, .04, math.radians(tail_deg), -1))
    else:
        parts.append(appendage((0, -.5, .85), .35, .18, .12, -math.radians(head_down), -1))
    parts.append(appendage((0, .5, .8), .6, .04, .04, math.radians(90 if curl else tail_deg), 1))
    for lx in (.15, -.15):
        for ly in (-.35, .35):
            toe = -.06
            if kind == 'symmetric' and ly > 0 or kind == 'conflict':
                toe = .06
            centres = [np.array((lx, ly + (toe if h < .05 else 0), h)) for h in np.arange(0, .6001, .02)]
            parts.append(tube(centres, x, y, .04, .04))
    verts, tris, offset = [], [], 0
    for v, t in parts:
        verts.append(v)
        tris.append(t + offset)
        offset += len(v)
    return np.concatenate(verts), np.concatenate(tris)


def old_flips(v):
    """The replaced rule, inlined: the end with the higher top is the head."""
    length = np.ptp(v[:, 1])
    lo = v[v[:, 1] < v[:, 1].min() + .15 * length, 2].max()
    hi = v[v[:, 1] > v[:, 1].max() - .15 * length, 2].max()
    return hi > lo


def centred(v):
    v = v.copy()
    v[:, 0] -= (v[:, 0].max() + v[:, 0].min()) / 2
    v[:, 1] -= (v[:, 1].max() + v[:, 1].min()) / 2
    v[:, 2] -= v[:, 2].min()
    return v


def check_pure():
    q = production()
    turn = np.array((-1., -1., 1.))
    cases = {'tail 0': creature(0), 'tail 30': creature(30), 'tail 60': creature(60), 'tail 90': creature(90),
             'tail curled over the back': creature(curl=True), 'head lowered 40': creature(head_down=40),
             'head lowered 40, tail 60': creature(60, head_down=40)}
    for name, (v, tris) in cases.items():
        v = centred(v)
        assert q['facing'](v, tris) == 1, name
        assert q['facing'](v * turn, tris) == -1, name + ' turned'
    assert not old_flips(centred(cases['tail 0'][0])), 'old rule control: a level tail does not flip'
    assert old_flips(centred(cases['tail 30'][0])), 'old rule control: a 30 degree tail flips'
    print('PASS facing +1 (and -1 turned) for tails 0-90, curled, head lowered; old rule flips at 30 degrees',
          flush=True)
    for kind in ('symmetric', 'conflict'):
        v, tris = creature(kind=kind)
        try:
            q['facing'](centred(v), tris)
        except q['NotApplicable'] as exc:
            assert 'facing ambiguous' in str(exc), exc
            print('PASS', kind, 'creature NotApplicable:', exc, flush=True)
        else:
            raise AssertionError(kind + ' creature was given a head end')
    p = np.array([[.3, 0, 0], [.3, 1, 0], [.3, 0, 1], [-.1, 5, 0], [-.1, 6, 0], [-.1, 5, 1]])
    tris = np.array([[0, 1, 2], [3, 4, 5]])
    names = ['Head', 'Tail_Mid']
    weights = np.array([[1., 0]] * 3 + [[0., 1]] * 3)
    assert np.allclose(q['skinned_spread'](p, tris, names, weights), (.3, .1))
    assert np.allclose(q['skinned_spread'](p, tris, names, weights[:, ::-1]), (.1, .3))
    assert q['skinned_spread'](p, tris, names, np.array([[1., 0]] * 6))[1] is None
    print('PASS skinned_spread 0.3/0.1, swapped 0.1/0.3, tailless None', flush=True)
    return creature


HELPER = r'''
import bpy, json, math, sys
from pathlib import Path
from mathutils import Matrix
root, assets = map(Path, sys.argv[sys.argv.index('--')+1:])
POSES = {'fox': [], 'tail30': [('Tail_Base', 30)], 'tail45': [('Tail_Base', 45)],
         'tail60': [('Tail_Base', 60)], 'tail90': [('Tail_Base', 90)],
         'curl': [('Tail_Base', 80), ('Tail_Mid', 45), ('Tail_Mid.001', 45), ('Tail_End', 40), ('Tail_Tip', 30)],
         'graze': [('Spine_3', 25), ('Spine_4', 30), ('Head', 20)]}
def export(obj, name):
    bpy.ops.object.select_all(action='DESELECT'); obj.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(root/(name+'.glb')), export_format='GLB', use_selection=True,
                              export_animations=False, export_skins=False)
for name, rotations in POSES.items():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(assets/'fox-animations.glb'))
    arm = next(o for o in bpy.data.objects if o.type=='ARMATURE')
    arm.animation_data_clear()
    for pb in arm.pose.bones: pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    for bone, deg in rotations:
        # Raise (+) a bone pointing to +Y, lower (+) one pointing to -Y: about world X at its head.
        pb = arm.pose.bones[bone]; head = pb.head.copy()
        pb.matrix = Matrix.Translation(head) @ Matrix.Rotation(math.radians(deg), 4, 'X') @ Matrix.Translation(-head) @ pb.matrix
        bpy.context.view_layer.update()
    body = next(o for o in bpy.data.objects if o.type=='MESH')
    mesh = bpy.data.meshes.new_from_object(body.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    mesh.transform(body.matrix_world)
    for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)
    for turn in (0, 180):
        obj = bpy.data.objects.new(name, mesh.copy()); bpy.context.collection.objects.link(obj)
        obj.data.transform(Matrix.Rotation(math.radians(turn), 4, 'Z'))
        export(obj, f'{name}-{turn}')
        bpy.data.objects.remove(obj, do_unlink=True)
data = json.loads((root/'symmetric.json').read_text())
mesh = bpy.data.meshes.new('symmetric'); mesh.from_pydata(data['v'], [], data['t']); mesh.update()
obj = bpy.data.objects.new('symmetric', mesh); bpy.context.collection.objects.link(obj)
export(obj, 'symmetric')
'''

CHECK = r'''
import bpy, json, math, sys, importlib.util
import numpy as np
from pathlib import Path
root, assets, script = map(Path, sys.argv[sys.argv.index('--')+1:])
spec = importlib.util.spec_from_file_location('quadruped_rig', script)
q = importlib.util.module_from_spec(spec); spec.loader.exec_module(q)
HEAD = set(q.HEAD_BONES)
report = {}
def job(name, out):
    out.mkdir(exist_ok=True)
    return {'inputs': {'mesh': str(root/(name+'.glb')), 'texture': str(root/'texture.png'),
            'ref': str(assets/'fox-animations.glb')}, 'params': {'clips': {}, 'tail_motion': 'calm'},
            'out_dir': str(out)}
for name in ('fox', 'tail30', 'tail45', 'tail60', 'tail90', 'curl', 'graze'):
    for turn in (0, 180):
        label = f'{name}-{turn}'
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(root/(label+'.glb')))
        v = q.vertices([o for o in bpy.data.objects if o.type == 'MESH'])
        facing = np.array((math.sin(math.radians(turn)), -math.cos(math.radians(turn)), 0.))
        nose = int(np.argmax(v @ facing))
        metrics, _ = q.run(job(label, root/label))
        body = next(o for o in bpy.data.objects if o.type == 'MESH')
        arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
        assert len(body.data.vertices) == len(v), label
        point = body.matrix_world @ body.data.vertices[nose].co
        head = (point - arm.matrix_world @ arm.data.bones['Head.tip'].tail_local).length
        tail = (point - arm.matrix_world @ arm.data.bones['Tail_Tip'].tail_local).length
        owned = sum(g.weight for g in body.data.vertices[nose].groups if body.vertex_groups[g.group].name in HEAD)
        report[label] = {'nose_to_head_tip': head, 'nose_to_tail_tip': tail, 'head_weight': owned,
                         'spread': metrics['facing']}
        assert head < tail and owned > .5, (label, report[label])
real = q.facing
calls = []
def inverted(v, tris):
    # Only the target's decision (the first call of a run); the reference fox
    # keeps its own, or both would turn and the fit would match again.
    calls.append(1)
    return -real(v, tris) if len(calls) == 1 else real(v, tris)
q.facing = inverted
for label in ('fox-0', 'tail45-0'):
    calls.clear()
    try:
        q.run(job(label, root/(label+'-inverted')))
    except q.NotApplicable as exc:
        assert 'reversed skeleton' in str(exc), exc
        report[label+' inverted'] = str(exc)
    else:
        raise AssertionError(label + ': a reversed skeleton was accepted')
(root/'facing.json').write_text(json.dumps(report, indent=1))
'''


def check_blender(creature):
    from app.blender import runner
    if not runner.is_available():
        print('SKIP Blender part: supported Blender unavailable:', runner.status()['error'])
        return
    from app.core.paths import get_quadruped_dir
    assets = get_quadruped_dir()
    with tempfile.TemporaryDirectory(prefix='av-smoke-facing-') as tmp:
        root = Path(tmp)
        v, tris = creature(kind='symmetric')
        (root/'symmetric.json').write_text(json.dumps({'v': v.tolist(), 't': tris.tolist()}))
        from PIL import Image
        Image.new('RGB', (16, 16), 'red').save(root/'texture.png')
        for name, source, args in (('helper', HELPER, [str(root), str(assets)]),
                                   ('check', CHECK, [str(root), str(assets), str(SCRIPT)])):
            path = root/(name+'.py')
            path.write_text(source)
            proc = subprocess.run([runner.find_executable(), '--background', '--factory-startup',
                                   '--python-exit-code', '1', '--python', str(path), '--', *args],
                                  capture_output=True, text=True, timeout=580)
            assert proc.returncode == 0, (proc.stdout + proc.stderr)[-6000:]
        report = json.loads((root/'facing.json').read_text())
        for label, entry in report.items():
            print('PASS', label, json.dumps(entry) if isinstance(entry, dict) else entry)
        # The server's path: job dir, args.json, the script's own entry point.
        runner.pin_slots(str(root/'slots'), 1)
        progress = root/'progress.json'
        seen = {}
        spawn = runner._spawn

        def keep_progress(cmd, timeout, env):
            # The runner deletes the progress file when the run ends; read it first.
            proc = spawn(cmd, timeout, env)
            seen['progress'] = progress.read_text() if progress.is_file() else None
            return proc
        runner._spawn = keep_progress
        res = runner.run('quadruped_rig', inputs={'mesh': root/'fox-0.glb', 'texture': root/'texture.png',
                         'ref': assets/'fox-animations.glb'},
                         params={'clips': {}, 'tail_motion': 'calm', 'progress_file': str(progress)},
                         out_dir=root/'runner-fox', timeout_s=300)
        runner._spawn = spawn
        assert res['ok'], res
        assert seen.get('progress'), 'the script wrote no progress file'
        stage = json.loads(seen['progress'])
        assert stage['stage'] == 'exporting', stage
        print('PASS runner: fox ok, progress file reached stage', stage['stage'])
        res = runner.run('quadruped_rig', inputs={'mesh': root/'symmetric.glb', 'texture': root/'texture.png',
                         'ref': assets/'fox-animations.glb'},
                         params={'clips': {}, 'tail_motion': 'calm'}, out_dir=root/'runner-sym', timeout_s=300)
        assert not res['ok'] and res['data'].get('not_applicable'), res
        assert 'facing ambiguous' in res['error'], res
        print('PASS runner: symmetric creature not applicable:', res['error'])


def main():
    creature = check_pure()
    if '--pure-only' in sys.argv:
        return
    check_blender(creature)


if __name__ == '__main__':
    main()
