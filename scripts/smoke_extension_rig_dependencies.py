"""Hand-derived registry and scale contract checks in isolated storage.

A->B->C requires depth order regardless of ids. Missing A removes B and C;
cycles have no root and remove every member. Effective enable is conjunction.
Length 1.4 replaced by world 1.6 then multiplied by state 1.5 gives 2.4;
three factors of 2 with declared 3 clamp 24 to 4; .5*.5*.5 clamps .125 to .25.
Girth 1.2 is replaced by world 1.4 then character 1.6; state 1.5 gives 2.4.
Girth uses the same effective clamps. Only centroid and bone are valid axes.
A GLB may omit a complete dependent group while retaining its complete source.
"""
import copy
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    from app.core import paths
    with tempfile.TemporaryDirectory(prefix='rig-dependencies-') as tmp:
        root=Path(tmp); paths.init(root/'world')
        from app.core import config
        paths.get_config_path().write_text(json.dumps({"packages":{"enabled":"fixture"}}))
        config.load(paths.get_config_path(),instance_path=root/'instance.json')
        from app.plugins import registry
        from app.plugins.loader import _resolve_rig_dependencies, discover_packages
        from app.core.extension_rig import rig_groups_for, resolved_extension_groups, motion_payload
        from app.plugins.registry import RigSpec
        def rig(id,bone,parent,**values):
            return dict(id=id,op='fixture',chains=[[dict(bone=bone,parent=parent)]],templates='*',**values)
        source=rig('z_source','Source','Hips',length=1.4,girth=1.2,scale_axis='bone')
        assert RigSpec.parse(rig('default','Default','Hips')).scale_axis=='centroid'
        for invalid in ('other',None,1,[]):
            try: RigSpec.parse(dict(source,scale_axis=invalid))
            except ValueError: pass
            else: raise AssertionError('invalid scale_axis accepted')
        for invalid in (.49,2.01,True,float('nan')):
            try: RigSpec.parse(dict(source,girth=invalid))
            except ValueError: pass
            else: raise AssertionError('invalid girth accepted')
        child=rig('a_child','Tip','Source')
        third=rig('b_third','Marker','Tip')
        parsed=[RigSpec.parse(row) for row in (third,child,source)]
        accepted=_resolve_rig_dependencies(parsed,'fixture','slot')
        assert {r.id:r.depends_on for r in accepted}=={'z_source':None,'a_child':'z_source','b_third':'a_child'}
        assert not _resolve_rig_dependencies(parsed[:2],'fixture','slot')
        assert not _resolve_rig_dependencies([RigSpec.parse(rig('a','A','B')),RigSpec.parse(rig('b','B','A'))],'fixture','slot')
        bad=rig('invalid','First','Hips');bad['chains'][0].append(dict(bone='Second',parent='Foreign'))
        try: RigSpec.parse(bad)
        except ValueError: pass
        else: raise AssertionError('external non-first parent accepted')
        import yaml
        plugins=root/'plugins';package=plugins/'fixture';package.mkdir(parents=True)
        manifest=dict(name='Fixture',apply_to='*',body_slots=[dict(id='slot',rigs=[third,child,source])])
        path=package/'plugin.yaml'
        def load(data):
            path.write_text(yaml.safe_dump(data));discover_packages(plugins,force=True)
        load(manifest)
        profile=dict(template='human-default')
        assert [g['id'] for g in rig_groups_for('fixture',profile)]==['z_source','a_child','b_third']
        disabled=copy.deepcopy(profile);disabled['model3d_opts']={'extension_rig_models':{'model':{'z_source':{'enabled':False}}}}
        assert all(not g['enabled'] for g in resolved_extension_groups('fixture',disabled,'model'))
        data=copy.deepcopy(manifest);data['body_slots'][0]['rigs'][2]['applies_to']={'flag':[True]};load(data)
        assert rig_groups_for('fixture',profile)==[]
        data=copy.deepcopy(manifest);data['body_slots'][0]['rigs']=[child];data['body_slots'].append(dict(id='other',rigs=[source]));load(data)
        assert registry.get_package('fixture').body_slots[0].rigs==[]
        data=copy.deepcopy(manifest);data['body_slots'][0]['rigs'][2]['length']=99;load(data)
        assert registry.get_package('fixture').body_slots[0].rigs==[]
        data=copy.deepcopy(manifest);data['body_slots'][0]['rig']=source;load(data)
        assert registry.get_package('fixture').body_slots[0].rigs==[]
        data=copy.deepcopy(manifest);data['body_slots'].append(dict(id='other',rigs=[rig('conflict','Source','Hips')]))
        load(data)
        assert all(not slot.rigs for slot in registry.get_package('fixture').body_slots)
        load(manifest)
        def payload(length=None,states=()):
            world={} if length is None else {'z_source':{'length':length}}
            with patch.object(config,'get',return_value=world),patch('app.core.prompt_filters.collect_bone_poses',return_value=list(states)):
                return motion_payload('fixture',profile,apply_clothing=False)['groups']['z_source']['length']
        assert payload()==1.4
        assert payload(1.6)==1.6
        states=[dict(bone_pose={'z_source':{'length':1.5}})]
        assert abs(payload(1.6,states)-2.4)<1e-12
        assert payload(3,[dict(bone_pose={'z_source':{'length':2}})]*3)==4
        assert payload(.5,[dict(bone_pose={'z_source':{'length':.5}})]*2)==.25
        def girth(world=None,character=None,states=()):
            profile['model3d_opts']={'extension_motion':{'z_source':character or {}}}
            with patch.object(config,'get',return_value={'z_source':world or {}}),patch('app.core.prompt_filters.collect_bone_poses',return_value=list(states)):
                group=motion_payload('fixture',profile,apply_clothing=False)['groups']['z_source']
                assert group['scale_axis']=='bone'
                return group['girth']
        assert girth()==1.2
        assert girth({'girth':1.4})==1.4
        assert girth({'girth':1.4},{'girth':1.6})==1.6
        assert abs(girth({'girth':1.4},{'girth':1.6},[dict(bone_pose={'z_source':{'girth':1.5}})])-2.4)<1e-12
        assert girth({'girth':2},states=[dict(bone_pose={'z_source':{'girth':2}})]*3)==4
        assert girth({'girth':.5},states=[dict(bone_pose={'z_source':{'girth':.5}})]*2)==.25
        from app.core.extension_rig import validate_motion_overrides
        for overrides in ({'scale_axis':'bone'},{'girth':2.01}):
            try: validate_motion_overrides({'groups':{'z_source':overrides}})
            except ValueError: pass
            else: raise AssertionError('invalid override accepted')
        from scripts.smoke_extension_rig_p0 import glb
        from app.core.rig_contract import BASE_JOINT_NAMES
        from app.core.model_validate import validate_glb
        base=['mixamorig:'+name for name in BASE_JOINT_NAMES]
        from app.core.extension_rig import extension_bone_names
        verdict=validate_glb(glb(base+['Source'],{'Source':'mixamorig:Hips'}),extension_names=extension_bone_names('fixture',profile))
        assert verdict['ok'],verdict
        print('PASS dependency pruning, ordering, enable, applicability, retired key, length/girth layers, scale axis, absent group GLB')

if __name__=='__main__':
    main()
