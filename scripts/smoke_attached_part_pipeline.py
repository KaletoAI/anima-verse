#!/usr/bin/env python3
"""Hand-derived publication contract with a deterministic runner.

A part and companion must be sent only to attached_part; an independent group
must run second in extension_bones. Success publishes both. A failed part (also
a raised runner exception or an invalid export) publishes the remaining group
from the clean source, records failed per-group metrics, and returns ok=True.
A failed part without other groups replaces a stale part with the clean body.
An invalid attached export rejected by the refinement gate also falls back.
"""
import copy
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    from app.core import paths
    with tempfile.TemporaryDirectory(prefix='attached-pipeline-') as tmp:
        root=Path(tmp);paths.init(root/'world')
        from app.core import model3d,extension_rig
        from scripts.smoke_extension_rig_p0 import glb
        from app.core.rig_contract import BASE_JOINT_NAMES
        from app.blender import refine
        clean=glb(['mixamorig:'+name for name in BASE_JOINT_NAMES])
        path=root/'model.glb';source=root/'prerig/model.glb';source.parent.mkdir()
        part={'id':'part','op':'attached_part','params':{},'chains':[[{'bone':'PartLink','parent':'Hips'}]],'enabled':True}
        companion={'id':'pods','op':'attached_part_bone','params':{},'chains':[[{'bone':'PartPods','parent':'Hips'}]],'enabled':True}
        other={'id':'other','op':'fixture','params':{},'chains':[[{'bone':'Other','parent':'Hips'}]],'enabled':True}
        for failure,others in ((False,True),(True,True),('raise',True),('invalid',True),('both',True),(True,False),(False,False)):
            groups=[part,companion]+([other] if others else [])
            calls=[]
            source.write_bytes(clean);path.write_bytes(b'stale model')
            def run(staged,script,params,**kwargs):
                calls.append((script,[g['id'] for g in params['groups']]))
                if script=='attached_part':
                    assert staged.read_bytes()==clean
                    if failure=='raise':
                        staged.write_bytes(b'incomplete')
                        raise RuntimeError('fixture failure')
                    if failure == 'invalid':
                        assert not kwargs['validator'](b'invalid export')['ok']
                        return {'applied':False,'error':'fixture failure'}
                    if failure:
                        return {'applied':False,'error':'fixture failure'}
                    staged.write_bytes(clean+b'part')
                    return {'applied':True,'data':{'metrics':{'part':{'protrusion_mm':7},'pods':{}}}}
                assert staged.read_bytes()==(clean if failure else clean+b'part')
                if failure == 'both':
                    return {'applied':False,'error':'ordinary failure'}
                staged.write_bytes(staged.read_bytes()+b'other')
                return {'applied':True,'data':{'metrics':{'other':{'status':'applied','weighted_verts':3}}}}
            with ExitStack() as stack:
                stack.enter_context(patch('app.models.character.get_character_profile',return_value={}))
                stack.enter_context(patch.object(extension_rig,'rig_groups_for',return_value=groups))
                stack.enter_context(patch.object(extension_rig,'resolved_extension_groups',return_value=groups))
                stack.enter_context(patch.object(model3d,'_auto_normalize'))
                stack.enter_context(patch.object(model3d,'_validator_for',return_value=lambda blob:{'ok':blob.startswith(clean), 'errors':['invalid fixture export']}))
                stack.enter_context(patch.object(refine,'apply_script',side_effect=run))
                meta={'rig':'mixamo'}
                result=model3d._auto_extension_rig('fixture',path,meta)
            assert result['ok'] and result['applied'],result
            assert calls==[('attached_part',['part','pods'])]+([('extension_bones',['other'])] if others else []),calls
            metrics=meta['extension_rig']['metrics']
            assert metrics['part']['status']==('failed' if failure else 'applied')
            assert metrics['pods']['status']==metrics['part']['status']
            if failure:
                assert metrics['part']['reason']=='fixture failure'
            else:
                assert metrics['part']['protrusion_mm']==7
            assert path.read_bytes()==clean+(b'' if failure else b'part')+(b'other' if others and failure != 'both' else b'')
            if failure == 'both':
                assert metrics['other']['status']=='failed'
                assert meta['extension_rig']['reason']=='ordinary failure'
                assert meta['extension_rig']['has_applied'] is False
            elif others:
                assert metrics['other']['weighted_verts']==3
        # Retry contract: a clean source (prerig carries the same finished blender
        # block) makes a forced rebuild a no-op after a built part, but a part that
        # failed (body published without it, aggregate still "applied") is retried.
        import json
        block={'steps':['normalize','limb_weights']}
        source.with_suffix('.json').write_text(json.dumps({'rig':'mixamo','blender':block}))
        for failed,expect_runs in ((True,2),(False,1)):
            runs=[]
            source.write_bytes(clean);path.write_bytes(b'stale model')
            def run_once(staged,script,params,**kwargs):
                runs.append(script)
                if failed:
                    return {'applied':False,'error':'fixture failure'}
                staged.write_bytes(clean+b'part')
                return {'applied':True,'data':{'metrics':{'part':{},'pods':{}}}}
            with ExitStack() as stack:
                stack.enter_context(patch('app.models.character.get_character_profile',return_value={}))
                stack.enter_context(patch.object(extension_rig,'rig_groups_for',return_value=[part,companion]))
                stack.enter_context(patch.object(extension_rig,'resolved_extension_groups',return_value=[part,companion]))
                stack.enter_context(patch.object(model3d,'_auto_normalize'))
                stack.enter_context(patch.object(model3d,'_validator_for',return_value=lambda blob:{'ok':blob.startswith(clean),'errors':[]}))
                stack.enter_context(patch.object(refine,'apply_script',side_effect=run_once))
                meta={'rig':'mixamo','blender':dict(block)}
                model3d._auto_extension_rig('fixture',path,meta)
                second=model3d._auto_extension_rig('fixture',path,meta,force=True)
            assert len(runs)==expect_runs,(failed,runs,second)
            assert bool(second.get('noop'))==(not failed),second
        print('PASS attached_part pipeline ordering, metrics, failure/exception fallback, clean-body publication and forced retry of a failed part')


if __name__=='__main__': main()
