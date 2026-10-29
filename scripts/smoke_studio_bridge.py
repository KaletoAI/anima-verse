#!/usr/bin/env python3
"""Bridge smoke. Usage: .venv/bin/python scripts/smoke_studio_bridge.py

Hand derivation: a 1 s bridge keys root_z 0 -> -25 cm. The importer
multiplies horizontal travel by rig_leg / actor_leg. take_document sets
lhipjoint = rig_leg - lfemur - ltibia, hence actor_leg = rig_leg and the
ratio is 1. Expected published travel is [0, -0.25] m, within 1 cm.
FeetPlanted fixes both ankles in world space; a 10 cm hips drop provides
leg reach while the hips move backwards. Blender E2E runs when available.
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
        print('OK bridge build/check/publish/sheet:', rm)
        print('OK bridge source-only commit paths/trailer (mocked), slide/travel rejection')
    else:
        print('SKIP bridge Blender build/check/publish (Blender unavailable)')
