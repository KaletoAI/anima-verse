#!/usr/bin/env python3
"""Bridge smoke. Usage: .venv/bin/python scripts/smoke_studio_bridge.py

Hand derivation: a 1 s bridge keys root_z 0 -> -25 cm. The importer
multiplies horizontal travel by rig_leg / actor_leg. take_document sets
lhipjoint = rig_leg - lfemur - ltibia, hence actor_leg = rig_leg and the
ratio is 1. Expected published travel is [0, -0.25] m, within 1 cm.
The reversed fixture must travel [0, +0.25] m with equal duration; its
first joints equal the source last joints within 0.5 cm. Looped, pair
and licensed sources are refused.
FeetPlanted fixes both ankles in world space; a 10 cm hips drop provides
leg reach while the hips move backwards. Blender E2E runs when available.
Support hand case: copy the studio-built bridge and translate its whole body
by -30*t cm along armature Y with sample/write_root. Its start feet remain
at 0 and its last feet are -30 cm. Reversal must lift its first frame by
30 cm, leave its last pose equal to the source start (0.5 cm), and retain
[0, +0.25] m travel (0.5 cm). The midpoint correction is 15 cm because
the fixture hips descend linearly; the sidecar must record 30 cm unbaked.
Floor hand case: lower the whole source (including its planted toes) by
2 cm only at middle samples 13..16 of 31. Endpoints remain at floor 0.
Reversal preserves this -2 cm dip; H=0, so rendered_y=y_file. A radius-6
maximum spreads the four-sample deficit to 16 samples; a radius-6 mean
has a full 13-sample plateau window, hence maximum lift = 2 cm. Every dip
sample still sees 13 maxima of 2, so its corrected floor is 0 cm.
First/last correction is explicitly zero; expected endpoint error is 0 cm.
All outputs and publication use temporary directories; no commit is made.
"""
import json
import os
import sys
import tempfile
from dataclasses import replace
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'animation-studio'))
import animstudio
from animstudio import StudioError
from animstudio.dsl import Animation, Catalog, FeetPlanted, Key, Pose, validate, values_at
from animstudio.compile import compile_anim
from animstudio.rig import load_rest

with tempfile.TemporaryDirectory(prefix='studio-bridge-') as td:
    tmp = Path(td)
    os.environ['STORAGE_DIR'] = str(tmp / 'world')
    os.environ['ANIMATION_CLIPS_DIR'] = str(tmp / 'clips')
    os.environ['ANIMATION_CLIPS_LICENSED_DIR'] = str(tmp / 'licensed')
    animstudio.bootstrap()
    animstudio.OUT = tmp / 'out'
    animstudio.ANIMS = tmp / 'anims'
    animstudio.ANIMS.mkdir()
    source = """from animstudio.dsl import Animation, FeetPlanted, Key, Pose
ANIM = Animation(kind='smoke-bridge', duration_s=1, loop=False, bridge=True,
    base=Pose(hips_drop_cm=10), ik=[FeetPlanted()],
    keys=[Key(0, Pose(root_z_cm=0)), Key(1, Pose(root_z_cm=-25))])
"""
    (animstudio.ANIMS / 'smoke-bridge.py').write_text(source)
    from animstudio.build import load_anim, build
    from animstudio.dsl import Reversed
    from animstudio.reverse import source_clip
    for name, meta in [('looped', {'loop': True}), ('paired', {'pair': True}),
                       ('licensed', {})]:
        directory = tmp / ('licensed' if name == 'licensed' else 'clips')
        directory.mkdir(exist_ok=True)
        (directory / f'{name}.fbx').write_bytes(b'fixture')
        (directory / f'{name}.json').write_text(json.dumps(meta))
        try:
            source_clip(Reversed(kind='smoke-reverse', source=name))
        except StudioError:
            pass
        else:
            raise AssertionError(f'{name} source accepted')
    (animstudio.ANIMS / 'smoke-reverse.py').write_text(
        "from animstudio.dsl import Reversed\n"
        "ANIM = Reversed(kind='smoke-reverse', source='smoke-bridge')\n")
    print('OK reversed loop/pair/license refusal')
    anim = load_anim('smoke-bridge')
    validate(anim)
    for bad in (replace(anim, loop=True), replace(anim, catalog=Catalog('x','stand','x')),
                replace(anim, bridge=False, catalog=Catalog('x','stand','x'))):
        try:
            validate(bad)
        except StudioError:
            pass
        else:
            raise AssertionError('invalid bridge accepted')
    assert values_at(anim, .5)['root_z_cm'] == -12.5
    carry = replace(anim, keys=[Key(0, Pose(root_x_cm=0)),
                    Key(.5, Pose(root_x_cm=10), ease='linear'),
                    Key(1, Pose(root_z_cm=-25))])
    assert values_at(carry, .25)['root_x_cm'] == 5
    assert values_at(carry, 1)['root_x_cm'] == 10
    cp = compile_anim(anim, load_rest())
    assert abs(cp.frames[-1].pos['Hips'][2] - cp.frames[0].pos['Hips'][2] + 25) < 1e-8
    for side in ('Left', 'Right'):
        assert max(abs(f.pos[side+'Foot'] - cp.frames[0].pos[side+'Foot']).max()
                   for f in cp.frames) < 1e-6
    print('OK bridge DSL, root track, world-fixed feet')
    from app.blender import runner
    if runner.is_available():
        report = build(anim.kind)
        assert report['ok'], report['checks']
        from animstudio.publish import publish
        from app.core import pose_catalog as pc
        with patch.object(pc, 'catalog_file_lock', side_effect=AssertionError('catalog touched')):
            result = publish(anim.kind, commit=False)
        side = json.loads((tmp / 'clips/smoke-bridge.json').read_text())
        rm = side['geometry']['root_motion']
        assert rm['mode'] == 'keep' and side['duration_s'] > 0 and not side['loop']
        assert abs(rm['travel_m'][0]) <= .01 and abs(rm['travel_m'][1] + .25) <= .01, rm
        assert result['key'] == ''
        assert len(result['files']) == 2
        from animstudio.gitops import CommitResult
        with patch('animstudio.gitops.commit_with_entry', return_value=CommitResult('fake', True)) as commit:
            publish(anim.kind, replace=True, repo=tmp, trailer='Test-Trailer: smoke')
        args = commit.call_args.args
        assert args[1] == '' and set(args[4]) == {
            'clips/smoke-bridge.fbx', 'clips/smoke-bridge.json', 'anims/smoke-bridge.py'}
        assert args[5].endswith('\n\nTest-Trailer: smoke')
        from animstudio.checks import run_checks
        import copy
        measured = json.loads((animstudio.OUT / anim.kind / 'measure.json').read_text())
        sliding = copy.deepcopy(measured)
        sliding['frames'][-1]['LeftToeBase'][0] += 3
        assert not next(c for c in run_checks(anim, cp, sliding, side) if c.name == 'foot_slide').ok
        wrong = copy.deepcopy(side)
        wrong['geometry']['root_motion']['travel_m'][1] = -.27
        assert not next(c for c in run_checks(anim, cp, measured, wrong) if c.name == 'bridge_travel').ok
        from animstudio.sheet import sheet
        image = sheet(anim.kind, columns=2)
        assert image.is_file()
        side['source']['credit'] = 'Fixture credit retained verbatim.'
        (tmp / 'clips/smoke-bridge.json').write_text(json.dumps(side))
        reverse = build('smoke-reverse')
        assert reverse['ok'], reverse['checks']
        revside = json.loads(Path(reverse['sidecar']).read_text())
        revmeasure = json.loads((animstudio.OUT / 'smoke-reverse/measure.json').read_text())
        assert revside['geometry']['support_unbaked_cm'] == 0
        assert all(revside[k] == side[k] for k in ('duration_s', 'frames', 'fps'))
        assert revside['source']['reversed_from'] == anim.kind
        assert all(revside['source'][k] == v for k, v in side['source'].items())
        import math
        assert math.dist(revside['geometry']['root_motion']['travel_m'], [0, .25]) <= .01
        endpoint_error = max(math.dist(p, measured['frames'][-1][j])
                             for j, p in revmeasure['frames'][0].items())
        assert endpoint_error <= .5
        with patch.object(pc, 'catalog_file_lock', side_effect=AssertionError('catalog touched')):
            publish('smoke-reverse', commit=False)
        with patch('animstudio.gitops.commit_with_entry', return_value=CommitResult('fake', True)) as commit:
            publish('smoke-reverse', replace=True, repo=tmp)
        assert commit.call_args.args[5] == (
            'feat(clips): smoke-reverse — smoke-bridge reversed as a bridge (animation-studio)')
        assert sheet('smoke-reverse', columns=2).is_file()
        print('OK reversed build/travel/endpoint/duration/publish/sheet:',
              revside['geometry']['root_motion']['travel_m'],
              f'endpoint_error={endpoint_error:.6f} cm, duration={revside["duration_s"]} s')
        # Author the below-floor exit directly: the studio floors authored takes.
        fixture_script = tmp / 'fixture.py'
        fixture_script.write_text("""
import sys
sys.path.insert(0, %r)
import bpy
import _common, clip_orient, cmu_clip
from _clip_scene import sample, write_root
from mathutils import Matrix
from pathlib import Path

def run(job):
    _common.reset_scene()
    arm = clip_orient._import_armature(job['inputs']['src'], 30)
    f0, f1 = [int(round(f)) for f in arm.animation_data.action.frame_range]
    bpy.context.scene.frame_start, bpy.context.scene.frame_end = f0, f1
    frames = list(range(f0, f1 + 1))
    mats, joints = sample(arm, frames)
    hips = cmu_clip.PREFIX + 'Hips'
    moved = {f: Matrix.Translation((0, -30 * (1 if job['params'].get('flat') else
                                  (f-f0)/(f1-f0)), 0)) @ mats[f][hips]
             for f in frames}
    if job['params'].get('dip'):
        moved = {f: Matrix.Translation((0, -2 if 13 <= f-f0 <= 16 else 0, 0))
                 @ mats[f][hips] for f in frames}
    write_root(arm, hips, moved, arm.data.bones[hips].matrix_local.copy())
    cmu_clip.DRIVEN.update(b.name[len(cmu_clip.PREFIX):] for b in arm.pose.bones)
    dst = Path(job['out_dir']) / 'smoke-sink.fbx'
    cmu_clip._export(arm, dst)
    return {}, {'clip': str(dst)}
_common.main(run)
""" % str(ROOT / 'app/blender/scripts'))
        with patch.object(runner, 'SCRIPTS_DIR', tmp):
            fixture = runner.run('fixture', inputs={'src': tmp / 'clips/smoke-bridge.fbx'},
                                 out_dir=tmp / 'clips')
        assert fixture['ok'], fixture
        sinkside = copy.deepcopy(side)
        sinkside['kind'] = 'smoke-sink'
        (tmp / 'clips/smoke-sink.json').write_text(json.dumps(sinkside))
        (animstudio.ANIMS / 'smoke-unsink.py').write_text(
            "from animstudio.dsl import Reversed\n"
            "ANIM = Reversed(kind='smoke-unsink', source='smoke-sink')\n")
        unsink = build('smoke-unsink')
        assert unsink['ok'], unsink['checks']
        uside = json.loads(Path(unsink['sidecar']).read_text())
        uframes = json.loads((animstudio.OUT / 'smoke-unsink/measure.json').read_text())['frames']
        low = min(p[1] for p in uframes[0].values())
        end_error = max(math.dist(p, measured['frames'][0][j]) for j, p in uframes[-1].items())
        assert abs(low) <= 1, low
        assert end_error <= .5, end_error
        assert abs(uside['geometry']['support_unbaked_cm'] - 30) <= .5
        assert math.dist(uside['geometry']['root_motion']['travel_m'], [0, .25]) <= .005
        for i, row in enumerate(uframes):
            expected_y = measured['frames'][-1-i]['Hips'][1]
            assert abs(row['Hips'][1] - expected_y) <= .5
        print(f'OK support unbake: first_floor={low:.6f} cm, last_error={end_error:.6f} cm, '
              f'support={uside["geometry"]["support_unbaked_cm"]:.6f} cm, '
              f'travel={uside["geometry"]["root_motion"]["travel_m"]}')
        with patch.object(runner, 'SCRIPTS_DIR', tmp):
            dip = runner.run('fixture', inputs={'src': tmp / 'clips/smoke-bridge.fbx'},
                             params={'dip': True}, out_dir=tmp / 'clips')
        assert dip['ok'], dip
        # The fixture overwrites smoke-sink, retaining the same endpoint metadata.
        dipped = build('smoke-unsink')
        dside = json.loads(Path(dipped['sidecar']).read_text())
        dframes = json.loads((animstudio.OUT / 'smoke-unsink/measure.json').read_text())['frames']
        assert dside['geometry']['support_unbaked_cm'] == 0
        # With H=0 the client lift H*p is zero in every frame.
        for row, original in zip(dframes, reversed(measured['frames'])):
            for joint, point in row.items():
                assert math.dist([point[0], point[2]],
                                 [original[joint][0], original[joint][2]]) <= .1
        assert min(p[1] for row in dframes for p in row.values()) >= -.5
        lift = dside['geometry']['floor_lift_max_cm']
        assert abs(lift - 2) <= .5, lift
        for actual, expected in ((dframes[0], measured['frames'][-1]),
                                 (dframes[-1], measured['frames'][0])):
            assert max(math.dist(p, expected[j]) for j, p in actual.items()) <= .1
        assert math.dist(dside['geometry']['root_motion']['travel_m'], [0, .25]) <= .005
        assert dipped['ok'], dipped['checks']
        print(f'OK middle toe dip: floor_lift_max_cm={lift}, endpoints unchanged')
        with patch.object(runner, 'SCRIPTS_DIR', tmp):
            flat = runner.run('fixture', inputs={'src': tmp / 'clips/smoke-bridge.fbx'},
                              params={'flat': True}, out_dir=tmp / 'clips')
        assert flat['ok'], flat
        try:
            build('smoke-unsink')
        except StudioError as exc:
            assert 'hips start/end heights are equal' in str(exc), exc
        else:
            raise AssertionError('flat hips accepted for support unbaking')
        print('OK flat hips support unbake refused')
        print('OK bridge build/check/publish/sheet:', rm)
        print('OK bridge source-only commit paths/trailer (mocked), slide/travel rejection')
    else:
        print('SKIP bridge Blender build/check/publish (Blender unavailable)')
