#!/usr/bin/env python3
"""Prop light contract smoke; Usage: .venv/bin/python scripts/smoke_prop_light.py.

Hand expectations: clamps turn 500/.1/[3,-1,.5]/-1 into
100/.5/[2,-.5,.5]/0. A [1,2,1] raw box scaled to [1,1,2]
has bottom centre [.5,0,.5]: at [.5,1,.5] gives [0,0], h=2.
At [1,.5,.5], yaw +90 maps (.5,0) to (0,-.5), h=1+.3=1.3 for a MARKER
(floor-relative). A LIGHT's height is relative to the placed object's base,
which already carries offset_y (bottom_y), so the light says h=1.0 and
bottom_y + 1.0 lands on the same 1.3 above the floor.
Only the patched variant gains a light; null removes it.
All storage is temporary; no server or Blender required.
"""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths


def main():
    with tempfile.TemporaryDirectory(prefix='prop-light-') as tmp:
        paths.init(Path(tmp))
        from app.core import props
        raw = dict(color='#FFB35C', intensity=500, range_m=.1, at=[3,-1,.5],
                   flicker='x', when='y', glow_m=-1, foo=1)
        assert props.sanitize_light(raw) == dict(color='#ffb35c', intensity=100.,
            range_m=.5, at=[2.,-.5,.5], flicker='none', when='always', glow_m=0.)
        assert props.sanitize_light(None) is None
        assert props.sanitize_light({'color':'red'}) is None
        pid = props.create_prop(name='Light fixture')['id']
        props.add_variant(pid)
        light = {'color':'#ffb35c'}
        props.bulk_update(pid, variants={'1':{'light':light}})
        variants = props.list_variants(pid)
        assert not variants[0].get('light')
        assert variants[1]['light'] == props.sanitize_light(light)
        props.bulk_update(pid, variants={'1':{'light':None}})
        assert not props.list_variants(pid)[1].get('light')
        print('PASS: light sanitization, variant bulk write/read/clear')
        from app.core import db, scene_recipe, room_recipe
        from app.core.model_store import write_sidecar
        from app.models import world_props
        db.init_schema()
        for i in (0, 1):
            gallery = props.model_gallery(pid, i)
            mesh = gallery.new_path()
            mesh.write_bytes(b'glTF-stub')
            write_sidecar(mesh, {'tier':'full', 'source':'upload'})
            gallery.select(mesh.name, 'full')
        meta = props.read_sidecar(pid)
        meta['bbox'] = [1,2,1]
        props._write_sidecar(pid, meta)
        props.bulk_update(pid, variants={str(i):{'dims':{
            'width_m':1, 'depth_m':1, 'height_m':2}} for i in (0,1)})
        loc = {'id':'light-room', 'map3d':{'plan_width_m':10,
            'outline':[[-5,-5],[5,-5],[5,5],[-5,5]]}, 'rooms':[
            {'id':'r', 'layout':{'x':-2,'y':-2,'w':4,'d':4,
             'props':[{'prop_id':pid,'at':[0,0], 'variant':1, 'yaw':90, 'offset_y':.3}]}}]}
        before = scene_recipe.scene_fingerprint(loc, loc['id'])
        assert before == scene_recipe.scene_fingerprint(loc, loc['id'])
        light = {'color':'#ffb35c','at':[1,.5,.5]}
        props.bulk_update(pid, variants={'1':{'light':light}})
        after = scene_recipe.scene_fingerprint(loc, loc['id'])
        assert before != after, 'light edit must invalidate scene fingerprint'
        for at, yaw, off, offset, height in [([.5,1,.5],0,0,[0,0],2),
                                           ([1,.5,.5],90,.3,[0,-.5],1.3)]:
            point = room_recipe.compose_prop_marker(bbox=[1,2,1], rotation={},
                dims=[1,1,2], frac=at, facing=None,
                placement_yaw=yaw, placement_offset_y=off)
            assert point['offset_m'] == offset and point['height_m'] == height
        scene = scene_recipe.compose_scene(loc, plan_width_m=10)
        spec = next(m for m in scene['models'] if m.get('id') == pid)
        assert spec['light']['offset_m'] == [0,-.5], spec
        assert spec['light']['height_m'] == 1.0, spec
        # The base already carries the trim: floor + .3 + 1.0 = marker's 1.3.
        unlifted = dict(loc, rooms=[dict(loc['rooms'][0], layout=dict(
            loc['rooms'][0]['layout'], props=[dict(loc['rooms'][0]['layout']['props'][0],
                                                   offset_y=0)]))])
        base0 = next(m for m in scene_recipe.compose_scene(unlifted, plan_width_m=10)['models']
                     if m.get('id') == pid)['bottom_y']
        assert abs(spec['bottom_y'] - base0 - .3) < 1e-6, (spec['bottom_y'], base0)
        assert abs(spec['bottom_y'] + spec['light']['height_m'] - (base0 + 1.3)) < 1e-6
        def assert_url_maps(item):
            for tier_map in [item['variants'], *item.get('model_variants', [])]:
                assert all(isinstance(url, str) for url in tier_map.values()), item

        assert_url_maps(spec)
        placement = loc['rooms'][0]['layout']['props'][0]
        placement['variant'] = 0
        primary = next(m for m in scene_recipe.compose_scene(loc, plan_width_m=10)['models']
                       if m.get('id') == pid)
        assert 'light' not in primary, primary
        assert_url_maps(primary)
        placement['variant'] = 1
        assert props.get_prop(pid)['variant_tiers'][1]['light']
        assert next(p for p in props.list_props() if p['id']==pid)['variant_tiers'][1]['light']
        world_props.save_world_prop({'prop_id':pid,'x':0,'z':0,'variant':1,
                                     'yaw_deg':90,'offset_y':.3})
        world_props.save_world_prop({'prop_id':pid,'x':1,'z':0,'variant':0})
        rows, sig = world_props.payload_snapshot()
        for row in rows:
            assert_url_maps(row)
            if row['variant'] == 0:
                assert 'light' not in row, row
            else:
                assert row['light']['color'] == '#ffb35c', row
        rows.sort(key=lambda row: row['variant'], reverse=True)
        assert rows[0]['light'] == spec['light'], rows
        from app.routes.world import get_world_props_route
        route_rows = get_world_props_route()['world_props']
        assert next(row for row in route_rows if row['variant'] == 1)['light'] == spec['light']
        props.bulk_update(pid, variants={'0':{'light':{'color':'#3366ff'}}})
        for variant, color in [(0, '#3366ff'), (1, '#ffb35c')]:
            placement['variant'] = variant
            shown = next(m for m in scene_recipe.compose_scene(loc, plan_width_m=10)['models']
                         if m.get('id') == pid)
            assert shown['light']['color'] == color, shown
            assert_url_maps(shown)
        for row in world_props.payload_rows():
            assert row['light']['color'] == ('#3366ff' if row['variant'] == 0 else '#ffb35c'), row
            assert_url_maps(row)
        props.bulk_update(pid, variants={'1':{'light':{'color':'#ffffff'}}})
        assert world_props.payload_snapshot()[1] != sig
        model = props.model_path(pid, variant=1)
        props.set_file_areas(model, rotation={'x':0,'y':0,'z':90})
        scene_recipe.invalidate_prop_lib_token()
        turned = next(row for row in world_props.payload_rows() if row['variant'] == 1)
        assert turned['fix_euler']['z'] == 90, turned
        print('PASS: hand geometry, scene variants, scene fingerprint, world payload/route/signature, variant orientation')


if __name__ == '__main__':
    main()
