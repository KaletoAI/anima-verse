"""Window payload contract without Blender or HTTP.

A 4 by 3 room has north pane x=1.4..2.6: casing starts 1.4-.08=1.32,
y=.9-.07=.83, size=(1.2+.16,1.2+.13)=(1.36,1.33). Along +z
rotates by atan2(-1,0)=270 degrees; local +z then points toward -x.
Mirrored centres .10 m apart are within the .15 m sharing tolerance.
"""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths


def main():
    with tempfile.TemporaryDirectory() as tmp:
        paths.init(tmp)
        from app.core import scene_recipe as sr, door_models as dm, world_ops as wo
        from app.core.window_styles import load_window_styles
        styles = load_window_styles()
        assert hasattr(sr, 'window_choice'), 'missing window resolution'
        for own, default, hull, expected in [('stone','timber','metal','stone'),
                ('gone','timber','metal','timber'), ('gone','gone','metal','metal'),
                ('gone','gone','gone','plain')]:
            assert sr.window_choice({'window_style':own}, default_window_style=default,
                hull_style={'window_style':hull}, window_styles=styles) == expected
        op = dict(edge='N', at=.5, type='window', width_m=1.2, height_m=1.2, sill_m=.9)
        assert wo._sanitize_opening({**op,'window_style':'stone'})['window_style']=='stone'
        assert 'window_style' not in wo._sanitize_opening({**op,'window_style':'gone'})
        pane = dict(level=0, room_id='a', **{'from':[1.4,0], 'to':[2.6,0]},
                    base_y=.9,height=1.2,glass=True,outward_normal=[0,-1],window_style='plain')
        calls=[]
        def built(style,w,h,t,**kwargs):
            calls.append((style,w,h,t,kwargs))
            return dict(sig='fixture',size_m=[round(w+.16,3),round(h+.13,3)],url='/assets/doors/fixture/model')
        with patch.object(dm,'ensure_window_model',return_value=None):
            p=deepcopy(pane)
            assert sr._window_models([p],styles=styles,color=None,glass=None,bars=True)==[]
            assert 'window_model' not in p
        with patch.object(dm,'ensure_window_model',side_effect=built):
            p=deepcopy(pane); twin={**deepcopy(pane),'from':[2.6,.1],'to':[1.4,.1]}
            specs=sr._window_models([p,twin],styles=styles,color=None,glass=None,bars=True)
            assert len(specs)==1 and p['window_model'] and twin['window_model']
            spec=specs[0]
            assert spec['anchor']==[1.32,0] and spec['bottom_y']==.83 and spec['size_m']==[1.36,1.33]
            assert spec['yaw_deg']==0 and spec['slots']=={'glass':{'preset':'glass'}}
            assert calls[-1][3]==.07 and calls[-1][4]['outside']==-1
            east={**deepcopy(pane),'from':[4,1.4],'to':[4,2.6],'outward_normal':[1,0]}
            assert sr._window_models([east],styles=styles,color=None,glass=None,bars=True)[0]['yaw_deg']==270
            assert calls[-1][4]['outside']==-1
            for small in ({'to':[1.5,0]}, {'height':.1}):
                p={**deepcopy(pane),**small}; before=len(calls)
                assert sr._window_models([p],styles=styles,color=None,glass=None,bars=True)==[]
                assert len(calls)==before and 'window_model' not in p
        loc={'id':'loc','map3d':{'outline':[[-5,-5],[5,-5],[5,5],[-5,5]]},
             'rooms':[{'id':'a','layout':{'x':0,'y':0,'w':4,'d':3,'level':0,'openings':[op]}}]}
        signatures=[]
        for ready in (False,True):
            with patch.object(dm,'ensure_window_model',side_effect=built if ready else None,return_value=None):
                scene=sr.compose_scene(loc,plan_width_m=10)
                signatures.append(scene['signature'])
                panes=[w for w in scene['walls'] if w.get('glass')]
                assert panes and all(bool(w.get('window_model'))==ready for w in panes)
                specs=[m for m in scene['models'] if m['id'].startswith('window:')]
                assert bool(specs)==ready
                if ready:
                    assert specs[0]['anchor']==[1.32,0] and specs[0]['bottom_y']==.83

        assert signatures[0]!=signatures[1], 'window readiness must change scene signature'
        with patch.object(dm,'ensure_window_model',return_value=None):
            first=sr.compose_scene(loc,plan_width_m=10)['signature']
            loc['default_window_style']='stone'
            second=sr.compose_scene(loc,plan_width_m=10)['signature']
            del loc['default_window_style']
            assert first!=second, 'default window style must change scene signature'
        from app.core import hull_styles as hs, location_model3d as lm, hull_facts as hf
        expected = dict(fachwerk='timber', holzhuette='timber', steinhaus='stone', burg='stone', modern='metal')
        for name, style in expected.items():
            assert hs.get_style(name)['window_style'] == style
        assert hs.validate_style({'window_style':'gone'},'test')['window_style']=='plain'
        from app.models import world
        from app.core import places
        record={'id':'loc','name':'Location','rooms':[]}
        with patch.object(wo,'add_location',return_value=record), patch.object(wo,'get_location_by_id',return_value=record), \
             patch.object(world,'_load_world_data',return_value={'locations':[record]}), patch.object(world,'upsert_location'), patch.object(places,'invalidate'):
            wo.create_location_with_extras({'name':'Location','default_window_style':'metal'})
            assert record['default_window_style']=='metal'
            wo.update_location_with_extras('loc',{'default_window_style':'timber'})
            assert record['default_window_style']=='timber'
            wo.update_location_with_extras('loc',{'default_window_style':'gone'})
            assert record['default_window_style']==''
        description={'style':'modern','overrides':{'frame_color':'#abcdef','ornament_density':0}}
        meta=hf._door_meta(description)
        assert meta['hull_frame_color']=='#abcdef' and meta['hull_ornament_density']==0
        assert hf._door_meta({'style':'modern'})['hull_ornament_density']==.5
        gallery=MagicMock(); gallery.find.return_value=Path(tmp)/'active.glb'; gallery.tiers.return_value=[]
        with patch.object(lm,'_owner_id',return_value='loc'), patch.object(lm,'_gallery',return_value=gallery), \
             patch.object(lm,'read_sidecar',return_value={'plan_hull':True,'hull':{'description':description}}), patch.object(lm,'_demand_low'):
            exported=lm.get_client_meta('loc')
            assert exported['hull_frame_color']=='#abcdef' and exported['hull_ornament_density']==0
        with patch.object(dm,'ensure_window_model',side_effect=built):
            calls.clear()
            scene=sr.compose_scene(loc,plan_width_m=10,building_meta={'plan_hull':True,**meta})
            assert calls and calls[0][0]['id']=='metal' and calls[0][4]==dict(outside=-1,bars=False,color='#abcdef',glass='#2f3d47')
            loc['default_window_style']='stone'
            sr.compose_scene(loc,plan_width_m=10,building_meta={'plan_hull':True,**meta})
            assert calls[-1][0]['id']=='stone'
            del loc['default_window_style']
            shared={'id':'shared','map3d':loc['map3d'],'rooms':[
                {'id':'a','layout':{'x':-4,'y':-4,'w':4,'d':4,'level':0,'openings':[{**op,'edge':'S','to':'b'}]}},
                {'id':'b','layout':{'x':-4,'y':.1,'w':4,'d':4,'level':0}}]}
            calls.clear(); scene=sr.compose_scene(shared,plan_width_m=10)
            panes=[w for w in scene['walls'] if w.get('glass')]
            assert len(panes)==2 and all(w.get('window_model') for w in panes)
            assert len(calls)==1 and len([m for m in scene['models'] if m['id'].startswith('window:')])==1
        with patch.object(dm,'ensure_window_model',return_value=None):
            missing_facts=hf.hull_facts(loc)
        with patch.object(dm,'ensure_window_model',side_effect=built):
            assert hf.hull_facts(loc)==missing_facts
        assert sr.SCENE_RECIPE_VERSION==16
        print('PASS window scene: cascade, pane fallback, placement, dedup, small panes, sanitizers, v16')

if __name__=='__main__':
    main()
