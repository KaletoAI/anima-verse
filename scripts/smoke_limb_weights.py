#!/usr/bin/env python3
"""Usage: .venv/bin/python scripts/smoke_limb_weights.py

Hand-derived expectations: U has four fixed neighbours: two Hips, one
LeftUpLeg, one RightUpLeg. Thus U = (.5, .25, .25). Coincident C has
only U as neighbour: C=U, U=(4*fixed_mean+C)/5, giving the same result.
P keeps .5 Hips and fills .5 from three LeftUpLeg neighbours: (.5, .5).
K keeps (.8 LeftUpLeg, .2 LeftLeg). O and T lie outside the window.
Three vertices change, two are fully foreign, none unresolved, and removed
weight is 1+1+.5=2.5. Report bone keys are normalised: {'lefthand': 3}.

The quad fixture is checked in-scene. GLB triangulates its quads, adding
one LeftUpLeg and one RightUpLeg neighbour at U: the exported graph gives
Hips/LeftUpLeg/RightUpLeg each 1/3. C uses two outside-window anchors with
that distribution to remain a valid exported triangle; its fixed point is
also 1/3 each. All three changed counts and P/K/O/T expectations stay equal.

The rig_weight_repair candidate key is ``character:demo:demo:<t>``, <t> = the
first 12 hex of sha256 over the JSON [created_at, job_id] of the sidecar —
both absent in the fixture, so ["", ""].

The hand_restore type (same re-run pattern, ``model3d.restore_model_hands``),
character ``hand``, model ``hand.glb`` (bytes "rigged") with an unrigged
source and a derived low tier; ``refine.hand_restore`` is a stand-in that
writes "restored" when it applies:
  * key ``character:hand:hand:<t>``, <t> = sha256 over JSON [1, "", ""]
    (HANDS_VERSION 1, no created_at/job_id); a generic rig or a model without
    the unrigged source is no candidate; a record of version 0 is due again;
    the character in ``_generating`` -> no candidate, withheld
    ("character:hand",).
  * Left applied, Right refused "edge stretch 1.42x": in place, bytes
    "restored", collision 1 call, build_lod 1 call (low source lod), result
    "hand: Left hand: restored to the mesher's fingers · Right hand: kept as
    rigged (the skin would tear at the knuckles)", no candidate any more.
  * both refused (ok, not applied): bytes stay "rigged", collision 0,
    build_lod 0, decided -> no candidate (the step closes fulfilled).
  * the script crashes (ok False): ok False, nothing published, still due.
  * "Repair rig weights" in place on that model (limb_weights nothing to do):
    hand_restore 0 calls, bytes "rigged", still due (fails on 1398fffc4,
    where the in-place catch-up moved the fingers without follow-ups).
  * prerig + applied extension rig: the source applied -> one forced
    rebuild_extension_rig; the source both kept -> no rebuild, the model
    takes the source's record.
  * apply's follow-up of a changed model: base body -> after_base_face_change
    once; outfit body -> refit_body + figure.invalidate + one Build request
    "body_change"; already followed up -> none of them.

"""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURE = r'''
import bpy, sys, json
from pathlib import Path
root = Path(sys.argv[sys.argv.index('--')+1])
sys.path.insert(0, str(Path.cwd()/'app/blender/scripts'))
import _common
_common.app_root_on_path()
from _limb_weights import repair
bpy.ops.wm.read_factory_settings(use_empty=True)
data = bpy.data.armatures.new('demo')
arm = bpy.data.objects.new('demo', data)
bpy.context.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
arm.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
for name, start, end in [
 ('Hips',(0,0,1),(0,0,1.1)),
 ('LeftUpLeg',(.1,0,.95),(.1,0,.5)),
 ('RightUpLeg',(-.1,0,.95),(-.1,0,.5)),
 ('LeftLeg',(.1,0,.5),(.1,0,.1)),
 ('LeftHand',(.8,0,1.4),(.9,0,1.4)),
 ('RightHand',(-.8,0,1.4),(-.9,0,1.4)),
 ('Head',(0,0,1.6),(0,0,1.8))]:
    b=data.edit_bones.new('mixamorig:'+name); b.head=start; b.tail=end
bpy.ops.object.mode_set(mode='OBJECT')
points=[(x,-.1,z) for z in (.80,.85,.90) for x in (-.06,-.04,-.02,0,.02,.04,.06)]
quads=[(r*7+c,r*7+c+1,(r+1)*7+c+1,(r+1)*7+c) for r in range(2) for c in range(6)]
def mesh(name, coords, faces, weights):
    me=bpy.data.meshes.new(name); me.from_pydata(coords,[],faces)
    obj=bpy.data.objects.new(name,me); bpy.context.collection.objects.link(obj)
    for i, distribution in enumerate(weights):
        for n,w in distribution.items():
            group=obj.vertex_groups.get('mixamorig:'+n) or obj.vertex_groups.new(name='mixamorig:'+n)
            group.add([i],w,'REPLACE')
    obj.modifiers.new('demo','ARMATURE').object=arm
    obj.parent=arm
    return obj
weights=[{'RightUpLeg' if x<0 else 'LeftUpLeg' if x>0 else 'Hips':1} for x,y,z in points]
weights[10]={'LeftHand':1}; weights[19]={'Hips':.5,'LeftHand':.5}
weights[6]={'LeftUpLeg':.8,'LeftLeg':.2}
obj=mesh('demo',points,quads,weights)
c=mesh('demo_copy',[(0,-.1,.85)],[(0,0,0)],[{'LeftHand':1}])
mesh('demo_out',[(.5,-.1,.85)],[(0,0,0)],[{'LeftHand':1}])
mesh('demo_top',[(0,-.1,1.05)],[(0,0,0)],[{'Head':1}])
# Bounds keep normalize at scale one and shift zero.
mesh('demo_bounds',[(-1,-.2,0),(1,.2,1.8)],[(0,0,0),(1,1,1)],[{'Hips':1}]*2)
def distribution(o,i):
    return {o.vertex_groups[g.group].name.split(':')[-1]:g.weight for g in o.data.vertices[i].groups if g.weight>1e-6}
def check_report(report):
    assert not report['error'], report
    for k,v in {'vertices':3,'fully_foreign':2,'unresolved':0,'removed_weight':2.5,'bones':{'lefthand':3}}.items():
        assert report[k]==v,(k,report)
def check(o,i,want):
    got=distribution(o,i)
    assert set(got)==set(want),(got,want)
    assert max(abs(got[n]-w) for n,w in want.items())<1e-5,(got,want)
report=repair(); check_report(report)
check(obj,10,{'Hips':.5,'LeftUpLeg':.25,'RightUpLeg':.25})
check(c,0,{'Hips':.5,'LeftUpLeg':.25,'RightUpLeg':.25})
check(obj,19,{'Hips':.5,'LeftUpLeg':.5})
check(obj,6,{'LeftUpLeg':.8,'LeftLeg':.2})
# Restore the input before the independent GLB round trip.
for i,w in enumerate(weights):
    for group in obj.vertex_groups: group.remove([i])
    for n,v in w.items(): obj.vertex_groups['mixamorig:'+n].add([i],v,'REPLACE')
bpy.data.objects.remove(c,do_unlink=True)
for name in ('demo_out','demo_top','demo_bounds'):
    bpy.data.objects.remove(bpy.data.objects[name],do_unlink=True)
thirds={'Hips':1/3,'LeftUpLeg':1/3,'RightUpLeg':1/3}
mesh('demo_copy',[(0,-.1,.85),(.2,0,.85),(.2,.1,.85)],[(0,1,2)],[{'LeftHand':1},thirds,thirds])
mesh('demo_out',[(.5,-.1,.85),(.6,0,.85),(.6,.1,.85)],[(0,1,2)],[{'LeftHand':1}]*3)
mesh('demo_top',[(0,-.1,1.05),(.2,0,1.05),(.2,.1,1.05)],[(0,1,2)],[{'Head':1}]*3)
mesh('demo_bounds',[(-1,-.2,0),(1,-.2,0),(1,.2,1.8),(-1,.2,1.8)],[(0,1,2,3)],[{'Hips':1}]*4)
bpy.ops.export_scene.gltf(filepath=str(root/'demo.glb'),export_format='GLB')
print('PASS exact quad fixture')
'''

READBACK = r'''
import bpy, sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'app/blender/scripts'))
import _common
_common.reset_scene(); _common.import_model(sys.argv[sys.argv.index('--')+1])
checks=[((0,-.1,.85),{'Hips':1/3,'LeftUpLeg':1/3,'RightUpLeg':1/3},2),
 ((.04,-.1,.90),{'Hips':.5,'LeftUpLeg':.5},1),
 ((.06,-.1,.80),{'LeftUpLeg':.8,'LeftLeg':.2},1),
 ((.5,-.1,.85),{'LeftHand':1},1),((0,-.1,1.05),{'Head':1},1)]
for pos,want,count in checks:
    found=0
    for obj in bpy.context.scene.objects:
        if obj.type!='MESH': continue
        for v in obj.data.vertices:
            if max(abs(a-b) for a,b in zip(obj.matrix_world@v.co,pos))>1e-5: continue
            got={obj.vertex_groups[g.group].name.split(':')[-1]:g.weight for g in v.groups if g.weight>1e-5}
            assert set(got)==set(want),(pos,got,want)
            assert max(abs(got[n]-w) for n,w in want.items())<1e-5,(pos,got,want)
            found+=1
    assert found==count,(pos,found,count)
print('PASS exported distributions')
'''


def application_checks(root):
    from app.core import paths
    paths.init(root)
    # The legacy whole-body path this smoke covers: since Task 11h (Ruling A13) every humanoid is on
    # the base-body pipeline and only a non-humanoid takes it; the humanoid fixture keeps it via this stub.
    from app.core import base_body as _legacy_bb
    _legacy_bb.is_base_pipeline = lambda *_a, **_k: False
    from app.core import model3d
    from app.blender import refine, runner
    report = {'vertices': 3, 'fully_foreign': 2, 'error': ''}
    source = root/'demo.glb'
    def result(data, applied=True):
        return {'ok': True, 'applied': applied, 'data': data, 'error': '' if applied else 'nothing to do'}
    with patch.object(refine, 'auto_normalize_enabled', return_value=True), \
         patch.object(model3d, '_target_height_m', return_value=1.8), \
         patch.object(model3d, '_validator_for', return_value=None), \
         patch.object(runner, 'version', return_value='5.2'), \
         patch.object(refine, 'normalize', return_value=result({'limb_weights': report})) as norm, \
         patch.object(refine, 'limb_weights', return_value=result(report, False)) as limb:
        meta = {'rig': 'mixamo'}
        model3d._auto_normalize('demo', source, meta)
        assert meta['blender']['steps'] == ['normalize', 'limb_weights'], meta
        assert norm.call_args.kwargs['repair_limb_weights'] is True
        meta = {'rig': 'mixamo', 'blender': {'steps': ['normalize']}}
        norm.reset_mock()
        model3d._auto_normalize('demo', source, meta)
        assert not norm.called and limb.call_count == 1
        assert meta['blender']['steps'] == ['normalize', 'limb_weights']
        limb.return_value = {'ok': False, 'applied': False, 'data': {}, 'error': 'demo failure'}
        meta = {'rig': 'mixamo', 'blender': {'steps': ['normalize']}}
        model3d._auto_normalize('demo', source, meta, required=True)
        assert meta['blender']['steps'] == ['normalize']
        assert meta['blender']['limb_weights']['error'] == 'demo failure'
        limb.side_effect = RuntimeError('demo exception')
        model3d._auto_normalize('demo', source, meta, required=True)
        assert meta['blender']['steps'] == ['normalize']
        limb.reset_mock()
        model3d._auto_normalize('demo', source, {'rig': 'generic', 'blender': {'steps': ['normalize']}})
        assert not limb.called
    from app.core.improvements.types.rig_weight_repair import RigWeightRepair
    from app.core.improvements.types import subjects
    directory = root/'models'; directory.mkdir()
    (directory/'demo.glb').write_bytes(b'demo')
    side = directory/'demo.json'
    side.write_text(json.dumps({'rig': 'mixamo'}))
    improvement = RigWeightRepair()
    with patch.object(subjects, 'characters', return_value=['demo']), \
         patch.object(subjects, 'character_model_signatures', return_value={'demo'}), \
         patch.object(model3d, 'get_model3d_dir', return_value=directory):
        candidates = improvement.find_candidates({})
        # The key token is over the sidecar's (created_at, job_id) — both absent here: JSON ["", ""].
        token = hashlib.sha256(json.dumps(['', '']).encode('utf-8')).hexdigest()[:12]
        assert [c.key for c in candidates] == [f'character:demo:demo:{token}'], [c.key for c in candidates]
        side.write_text(json.dumps({'rig': 'mixamo', 'blender': {'steps': ['limb_weights']}}))
        assert improvement.is_done(candidates[0], {})
        assert improvement.find_candidates({}) == []
    print('PASS normalization branches and improvement candidates')
    full = directory/'demo.glb'
    low = directory/'low'/'demo.glb'; low.parent.mkdir(); low.write_bytes(b'demo')
    pre = directory/'prerig'/'demo.glb'; pre.parent.mkdir(); pre.write_bytes(b'demo')
    model3d._publish_sidecar(full, {'rig': 'mixamo', 'blender': {'steps': ['normalize']}})
    model3d._publish_sidecar(pre, {'rig': 'mixamo', 'blender': {'steps': ['normalize']}})
    model3d._publish_sidecar(low, {'rig': 'mixamo', 'source': 'lod'})
    with patch.object(model3d, 'find_model3d', return_value=full), \
         patch.object(model3d, '_validator_for', return_value=None), \
         patch.object(refine, 'auto_normalize_enabled', return_value=True), \
         patch.object(refine, 'limb_weights', return_value=result(report, False)), \
         patch.object(model3d, 'build_lod', return_value={'ok': True}) as lod:
        repaired = model3d.repair_model_weights('demo', 'demo')
        assert repaired['ok'] and repaired['repaired']['full']['vertices'] == 3, repaired
        assert lod.call_count == 1
        assert 'limb_weights' in model3d._read_sidecar(pre)['blender']['steps']
        assert 'limb_weights' in model3d._read_sidecar(full)['blender']['steps']
    print('PASS stored source repair and derived low rebuild')
    low_pre = low.parent/'prerig'/low.name
    low_pre.parent.mkdir(); low_pre.write_bytes(b'demo')
    initial = {'rig': 'mixamo', 'blender': {'steps': ['normalize']},
               'extension_rig': {'status': 'applied', 'has_applied': True}}
    for target in (full, pre, low, low_pre):
        model3d._publish_sidecar(target, initial)
    def rebuild(name, signature, *, tier, force):
        target = full if tier == 'full' else low
        meta = model3d._read_sidecar(target)
        meta['blender'] = model3d._read_sidecar(pre if tier == 'full' else low_pre)['blender']
        model3d._publish_sidecar(target, meta)
        return {'ok': True, 'noop': True, 'applied': False}
    with patch.object(model3d, 'find_model3d', return_value=full), \
         patch.object(model3d, '_validator_for', return_value=None), \
         patch.object(refine, 'auto_normalize_enabled', return_value=True), \
         patch.object(refine, 'limb_weights', return_value=result(report, False)), \
         patch.object(model3d, 'rebuild_extension_rig', side_effect=rebuild) as rebuild_call:
        repaired = model3d.repair_model_weights('demo', 'demo')
        assert repaired['ok'], repaired
        assert [c.kwargs['tier'] for c in rebuild_call.call_args_list] == ['full', 'low']
        assert 'limb_weights' in model3d._read_sidecar(low)['blender']['steps']
    print('PASS independent low source after full rebuild no-op')
    # Exercise real publication staging: a failed low tier must stay retryable.
    from app.models.character import get_character_dir
    actual = get_character_dir('demo', create=True)/'model3d'
    (actual/'low').mkdir(parents=True)
    for target in (actual/'demo.glb', actual/'low/demo.glb'):
        target.write_bytes(b'demo')
        model3d._publish_sidecar(target, {'rig': 'mixamo', 'blender': {'steps': ['normalize']}})
    calls = []
    fail_low = True
    def repair_tier(path, validator=None):
        calls.append(path.parent.name)
        if path.parent.name == 'low' and fail_low:
            return {'ok': False, 'applied': False, 'data': {}, 'error': 'demo low failure'}
        path.write_bytes(b'repaired')
        return result(report)
    candidate = candidates[0]
    with patch.object(model3d, '_validator_for', return_value=None), \
         patch.object(refine, 'auto_normalize_enabled', return_value=True), \
         patch.object(refine, 'limb_weights', side_effect=repair_tier), \
         patch('app.core.sync_topics.changed_at'):
        failed = model3d.repair_model_weights('demo', 'demo')
        assert not failed['ok'] and failed['error'] == 'demo low failure', failed
        assert not improvement.is_done(candidate, {})
        assert (actual/'demo.glb').read_bytes() == b'demo'
        fail_low = False
        retry = model3d.repair_model_weights('demo', 'demo')
        assert retry['ok'] and improvement.is_done(candidate, {}), retry
        assert (actual/'demo.glb').read_bytes() == b'repaired'
        assert (actual/'low/demo.glb').read_bytes() == b'repaired'
    print('PASS low failure leaves all tiers unchanged and retries successfully')
    from app.core.extension_rig import extension_rig_fingerprint
    target = directory/'demo.glb'
    target.write_bytes(b'demo')
    pre.write_bytes(b'repaired')
    source_meta = {'rig': 'mixamo', 'blender': {'steps': ['normalize', 'limb_weights'],
                                              'limb_weights': report}}
    model3d._publish_sidecar(pre, source_meta)
    meta = {'rig': 'mixamo', 'blender': {'steps': ['normalize']},
            'extension_rig': {'attempted': True, 'status': 'applied',
                              'fingerprint': extension_rig_fingerprint([], {})}}
    with patch('app.core.extension_rig.rig_groups_for', return_value=[]), \
         patch('app.core.extension_rig.resolved_extension_groups', return_value=[]), \
         patch('app.models.character.get_character_profile', return_value={}), \
         patch('app.core.model_validate.validate_glb', return_value={'ok': True}):
        rebuilt = model3d._auto_extension_rig('demo', target, meta, force=True)
        assert rebuilt['ok'] and rebuilt['applied'], rebuilt
        assert target.read_bytes() == b'repaired'
        assert meta['blender'] == source_meta['blender']
    print('PASS force rebuild detects repaired source despite unchanged fingerprint')
    # The panel's Rebuild on a model whose source predates the repair: source
    # and served model carry the same old block, so only the missing step can
    # tell the rebuild apart from a no-op.
    target.write_bytes(b'demo')
    pre.write_bytes(b'demo')
    old_block = {'steps': ['normalize']}
    model3d._publish_sidecar(pre, {'rig': 'mixamo', 'blender': dict(old_block)})
    meta = {'rig': 'mixamo', 'blender': dict(old_block),
            'extension_rig': {'attempted': True, 'status': 'applied',
                              'fingerprint': extension_rig_fingerprint([], {})}}
    with patch('app.core.extension_rig.rig_groups_for', return_value=[]), \
         patch('app.core.extension_rig.resolved_extension_groups', return_value=[]), \
         patch('app.models.character.get_character_profile', return_value={}), \
         patch('app.core.model_validate.validate_glb', return_value={'ok': True}), \
         patch.object(model3d, '_validator_for', return_value=None), \
         patch.object(refine, 'limb_weights', side_effect=repair_tier):
        rebuilt = model3d._auto_extension_rig('demo', target, meta, force=True)
        assert not rebuilt.get('noop') and rebuilt['applied'], rebuilt
        assert target.read_bytes() == b'repaired'
        assert meta['blender']['steps'] == ['normalize', 'limb_weights'], meta['blender']
        assert 'limb_weights' in model3d._read_sidecar(pre)['blender']['steps']
        again = model3d._auto_extension_rig('demo', target, meta, force=True)
        assert not again['applied'] and target.read_bytes() == b'repaired', again
    print('PASS force rebuild repairs a source that predates the weight repair, once')


def hand_restore_checks():
    """The hand_restore improvement and ``model3d.restore_model_hands`` (module docstring)."""
    from app.core import model3d
    from app.blender import refine
    from app.core.improvements.types import subjects
    from app.core.improvements.types.hand_restore import HandRestore, model_token
    from app.models.character import get_character_dir
    directory = get_character_dir('hand', create=True)/'model3d'
    for sub in ('unrigged', 'low', 'prerig'):
        (directory/sub).mkdir(parents=True, exist_ok=True)
    full, low, pre = directory/'hand.glb', directory/'low'/'hand.glb', directory/'prerig'/'hand.glb'
    (directory/'unrigged'/'hand.glb').write_bytes(b'mesher')
    improvement = HandRestore()
    token = hashlib.sha256(json.dumps([1, '', '']).encode('utf-8')).hexdigest()[:12]
    assert model_token({}) == token
    normalized = {'rig': 'mixamo', 'blender': {'steps': ['normalize']}}

    def reset(meta=normalized):
        full.write_bytes(b'rigged')
        low.write_bytes(b'low')
        pre.unlink(missing_ok=True)
        model3d._publish_sidecar(full, json.loads(json.dumps(meta)))
        model3d._publish_sidecar(low, {'rig': 'mixamo', 'source': 'lod'})

    def keys():
        listing = improvement.list_candidates({})
        return [c.key for c in listing.candidates], listing.withheld

    side = lambda status, reason='': {'status': status, 'reason': reason,  # noqa: E731
                                      'max_displacement_mm': 4.0, 'displacement_left_mm': 4.0}
    verdict = {'Left': side('applied'), 'Right': side('refused', 'edge stretch 1.42x')}
    refused = {'Left': side('refused', 'spread_deg 20 -> 24'), 'Right': side('untouched')}
    script = {'data': verdict, 'applied': True, 'ok': True}

    def fake_restore(path, source, validator=None):
        assert source.read_bytes() == b'mesher', source
        if not script['ok']:
            return {'ok': False, 'applied': False, 'data': {}, 'error': 'demo crash'}
        if script['applied']:
            path.write_bytes(b'restored')
        return {'ok': True, 'applied': script['applied'], 'data': json.loads(json.dumps(script['data'])),
                'error': '' if script['applied'] else 'nothing to do'}

    def rebuild(name, signature, *, force):
        assert force is True
        here = model3d.get_model3d_dir(name)
        meta = model3d._read_sidecar(here/f'{signature}.glb')
        meta['blender'] = model3d._read_sidecar(here/'prerig'/f'{signature}.glb')['blender']
        (here/f'{signature}.glb').write_bytes((here/'prerig'/f'{signature}.glb').read_bytes())
        model3d._publish_sidecar(here/f'{signature}.glb', meta)
        return {'ok': True, 'low': {'ok': True}}

    with patch.object(subjects, 'characters', return_value=['hand']), \
         patch.object(model3d, '_validator_for', return_value=None), \
         patch.object(refine, 'hand_restore', side_effect=fake_restore) as restore_call, \
         patch.object(model3d, '_attach_measurement'), \
         patch.object(model3d, '_auto_collision', return_value=True) as collision, \
         patch.object(model3d, 'build_lod', return_value={'ok': True}) as lod, \
         patch.object(model3d, 'rebuild_extension_rig', side_effect=rebuild) as rebuild_call, \
         patch('app.core.sync_topics.changed_at'):
        reset({'rig': 'generic', 'blender': {'steps': ['normalize']}})
        assert keys() == ([], ()), keys()
        reset()
        (directory/'unrigged'/'hand.glb').rename(directory/'unrigged'/'kept.glb')
        assert keys() == ([], ()), keys()
        (directory/'unrigged'/'kept.glb').rename(directory/'unrigged'/'hand.glb')
        assert keys() == ([f'character:hand:hand:{token}'], ()), keys()
        reset({'rig': 'mixamo', 'blender': {'steps': ['normalize', 'hands'], 'hands': {'version': 0}}})
        assert keys() == ([f'character:hand:hand:{token}'], ()), keys()
        with model3d._lock:
            model3d._generating.add('hand', 'demo run')
        try:
            assert keys() == ([], ('character:hand',)), keys()
        finally:
            with model3d._lock:
                model3d._generating.discard('hand')
        print('PASS hand_restore candidates, token, versions and withheld')

        reset()
        candidate = improvement.list_candidates({}).candidates[0]
        note = improvement.apply(candidate, {}, 'task')
        assert note == ("hand: Left hand: restored to the mesher's fingers · Right hand: kept as rigged "
                        "(the skin would tear at the knuckles)"), note
        assert full.read_bytes() == b'restored'
        assert (collision.call_count, lod.call_count) == (1, 1), (collision.call_count, lod.call_count)
        assert model3d.hands_decided(model3d._read_sidecar(full))
        assert keys() == ([], ()), keys()
        print('PASS in-place reset, its follow-ups and the result line')

        reset(); collision.reset_mock(); lod.reset_mock()
        script.update(data=refused, applied=False)
        result = model3d.restore_model_hands('hand', 'hand')
        assert result['ok'] and not result['changed'], result
        assert full.read_bytes() == b'rigged'
        assert (collision.call_count, lod.call_count) == (0, 0)
        assert keys() == ([], ()), keys()
        print('PASS both hands kept: decided for this version, nothing rebuilt')

        reset()
        script.update(ok=False)
        result = model3d.restore_model_hands('hand', 'hand')
        assert not result['ok'] and result['error'] == 'demo crash', result
        assert 'hands' not in model3d._read_sidecar(full)['blender']['steps']
        assert keys() == ([f'character:hand:hand:{token}'], ()), keys()
        print('PASS a crashed run publishes nothing and stays due')

        # "Repair rig weights" in place on a model without the reset: the weights only, the fingers stay —
        # moving them there would skip the capsules / distance tier / Build follow-up (restore_model_hands has them).
        script.update(ok=True, data=verdict, applied=True)
        reset(); restore_call.reset_mock()
        with patch.object(refine, 'auto_normalize_enabled', return_value=True), \
             patch.object(refine, 'limb_weights', return_value={'ok': True, 'applied': False, 'data': {},
                                                                 'error': 'nothing to do'}):
            repaired = model3d.repair_model_weights('hand', 'hand')
        assert repaired['ok'] and restore_call.call_count == 0, (repaired, restore_call.call_count)
        assert full.read_bytes() == b'rigged'
        assert keys() == ([f'character:hand:hand:{token}'], ()), keys()
        print('PASS the in-place weight repair leaves the fingers to hand_restore')

        script.update(ok=True, data=verdict, applied=True)
        extension = {**normalized, 'extension_rig': {'status': 'applied', 'has_applied': True}}
        reset(extension)
        pre.write_bytes(b'rigged')
        model3d._publish_sidecar(pre, json.loads(json.dumps(normalized)))
        result = model3d.restore_model_hands('hand', 'hand')
        assert result['ok'] and result['changed'] and rebuild_call.call_count == 1, result
        assert full.read_bytes() == b'restored' and model3d.hands_decided(model3d._read_sidecar(full))
        reset(extension); rebuild_call.reset_mock()
        pre.write_bytes(b'rigged')
        model3d._publish_sidecar(pre, json.loads(json.dumps(normalized)))
        script.update(data=refused, applied=False)
        result = model3d.restore_model_hands('hand', 'hand')
        assert result['ok'] and not result['changed'] and rebuild_call.call_count == 0, result
        assert model3d._read_sidecar(full)['blender']['hands']['Left']['status'] == 'refused'
        assert model3d.hands_decided(model3d._read_sidecar(full))
        print('PASS extension models rebuilt from the reset source only when a hand changed')
        reset()
        candidate = improvement.list_candidates({}).candidates[0]

    done ={'ok': True, 'changed': True, 'followed_up': False, 'hands': verdict}
    for base, body, followed, want in ((True, False, False, (1, 0, 0, 0)), (False, True, False, (0, 1, 1, 1)),
                                       (True, False, True, (0, 0, 0, 0))):
        with patch.object(model3d, 'restore_model_hands', return_value={**done, 'followed_up': followed}), \
             patch('app.core.base_body.is_base_signature', return_value=base), \
             patch('app.core.base_body.is_outfit_body_signature', return_value=body), \
             patch.object(model3d, 'after_base_face_change') as after, \
             patch('app.core.outfit_bodies.refit_body') as refit, \
             patch('app.core.figure.invalidate') as invalidate, \
             patch('app.core.figure_build.request') as request:
            improvement.apply(candidate, {}, 'task')
            got = (after.call_count, refit.call_count, invalidate.call_count, request.call_count)
            assert got == want, (base, body, followed, got)
            if body:
                assert request.call_args.args == ('hand', 'body_change'), request.call_args
    print('PASS follow-ups of a changed base body / outfit body')






def main():
    from app.blender import runner
    with tempfile.TemporaryDirectory(prefix='smoke-weights-') as tmp:
        root = Path(tmp)
        application_checks(root)
        hand_restore_checks()
        status = runner.status()
        if not status['usable'] or not str(status.get('version', '')).startswith('5.2'):
            print('SKIP Blender 5.2:', status); return
        def blender(script, argument):
            path = root/'script.py'; path.write_text(script)
            proc = subprocess.run([status['executable'], '-b', '-noaudio', '--factory-startup',
                                   '--python-exit-code', '1', '--python', str(path), '--', str(argument)],
                                  capture_output=True, text=True, timeout=120)
            assert proc.returncode == 0, proc.stdout[-6000:]+proc.stderr[-2000:]
        blender(FIXTURE, root)
        source = root/'demo.glb'
        result = runner.run('limb_weights', inputs={'model': source}, out_dir=root/'out')
        assert result['ok'], result
        report = result['data']
        assert (report['vertices'], report['fully_foreign'], report['unresolved'], report['removed_weight']) == (3, 2, 0, 2.5), report
        assert report['bones'] == {'lefthand': 3}, report
        repaired = Path(result['outputs']['model'])
        blender(READBACK, repaired)
        original = repaired.read_bytes()
        clean = runner.run('limb_weights', inputs={'model': repaired}, out_dir=root/'clean')
        assert clean['ok'] and clean['data']['vertices'] == 0 and not clean['outputs'], clean
        assert repaired.read_bytes() == original
        for enabled in (True, False):
            normalized = runner.run('normalize', inputs={'model': source},
                                    params={'target_height_m': 1.8, 'repair_limb_weights': enabled},
                                    out_dir=root/str(enabled))
            assert normalized['ok'], normalized
            assert ('limb_weights' in normalized['data']) == enabled
            if enabled:
                assert normalized['data']['limb_weights']['vertices'] == 3, normalized
                assert normalized['data']['limb_weights']['fully_foreign'] == 2, normalized
        print('PASS Blender runner, unchanged clean file, normalize opt-in')


if __name__ == '__main__':
    main()
