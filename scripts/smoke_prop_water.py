#!/usr/bin/env python3
"""Payload, routes and carry-height smoke, all storage temporary.

Hand expectations: shared vectors contain a 4x4 pool at y=1.5 with a 1x1
hole, overlapped at (3.5,3.5) by a higher y=2 tub. Highest wins; the hole
and outside answer none. A .2 m level edit at scale 1 raises water .2 m.
A deck at 1.5 over a bed at 0 is a 1.5 m drop in .5 m, allowed downhill by the existing signed step rule; the return climb is
blocked. Water at 1.5 carries both directions to delta=0, permitting return.
Usage: ./.venv/bin/python scripts/smoke_prop_water.py
"""
import copy
import asyncio
import json
import math
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
from smoke_model_water import fixture


def resolve_args(value, fixtures):
    if isinstance(value, list):
        return [resolve_args(item, fixtures) for item in value]
    if isinstance(value, dict):
        if '$fixture' in value:
            result = copy.deepcopy(fixtures[value['$fixture']])
            if '$with' in value:
                result.update(copy.deepcopy(value['$with']))
            return result
        return {key: resolve_args(item, fixtures) for key, item in value.items()}
    return value


def near(expect, actual, eps):
    if expect is None:
        return actual is None
    if isinstance(expect, bool):
        return type(actual) is bool and expect == actual
    if isinstance(expect, (int, float)):
        return (type(actual) in (int, float) and math.isfinite(actual)
                and abs(expect - actual) <= eps)
    if isinstance(expect, list):
        return (isinstance(actual, list) and len(expect) == len(actual)
                and all(near(e, a, eps) for e, a in zip(expect, actual)))
    if isinstance(expect, dict):
        return (isinstance(actual, dict) and all(
            key in actual and near(value, actual[key], eps)
            for key, value in expect.items()))
    return type(expect) is type(actual) and expect == actual


def main():
    with tempfile.TemporaryDirectory(prefix='prop-water-') as tmp:
        paths.init(Path(tmp))
        paths.init_instance(Path(tmp) / 'instance')
        from app.core import model_water as w, model_surface as surf, props, scene_recipe as scene, db
        from app.core.model_store import write_sidecar
        from app.models import world_props
        vectors = json.loads(Path('shared/test-vectors/prop_water.json').read_text())
        for case in vectors['cases']:
            if case['fn'] != 'waterRegionAt':
                continue
            specs, x, z, *lift_arg = resolve_args(case['args'], vectors['fixtures'])
            lift = lift_arg[0] if lift_arg else 0
            actual = w.water_region_at(specs, x, z, lambda spec: lift)
            assert near(case['expect'], actual, case.get('eps', 1e-9)), case['label']
        assert scene.SCENE_RECIPE_VERSION >= 18  # water arrived in v18
        db.init_schema()
        pid = props.create_prop(name='Water fixture')['id']
        props.add_variant(pid)
        for i in (0, 1):
            gallery = props.model_gallery(pid, i)
            model = gallery.new_path()
            model.write_bytes(b'glTF-stub')
            write_sidecar(model, {'tier':'full', 'source':'upload'})
            gallery.select(model.name, 'full')
            if i == 1:
                data = fixture(model)
                data.update(target_m=2, measure='xyz')
                w.water_path(model).write_text(json.dumps(data))
        props.bulk_update(pid, variants={props.list_variants(pid)[int(key)]["uid"]: patch for key, patch in ({str(i):{'dims':{
            'width_m':2,'depth_m':2,'height_m':2}} for i in (0,1)}).items()}, base_revision=props.get_prop(pid)["revision"])
        loc = {'id':'water-room','map3d':{'plan_width_m':10,
            'outline':[[-5,-5],[5,-5],[5,5],[-5,5]]},'rooms':[
            {'id':'r','layout':{'x':-2,'y':-2,'w':4,'d':4,
              'props':[{'prop_id':pid,'at':[0,0],'variant':1}]}}]}
        before = scene.compose_scene(loc, plan_width_m=10)
        spec = next(m for m in before['models'] if m['id'] == pid)
        assert spec['water']['regions'][0]['swim_from_m'] == 1
        assert set(spec['water']['regions'][0]) == {'outline','holes','y','bed_y','tint','opacity','swim_from_m'}
        fp = scene.scene_fingerprint(loc, loc['id'])
        world_props.save_world_prop({'prop_id':pid,'x':10,'z':20,'variant':1,'offset_y':.3})
        rows, sig = world_props.payload_snapshot()
        assert rows[0]['water']['regions'][0]['outline'][0] == [9,19]
        assert abs(rows[0]['water']['regions'][0]['y']-.8) < 1e-8
        model = props.model_path(pid, variant=1)
        w.patch_water(model, {}, {'regions':[{'id':'r1','level':.7}]})
        after = scene.compose_scene(loc, plan_width_m=10)
        assert after['signature'] != before['signature']
        assert fp != scene.scene_fingerprint(loc, loc['id'])
        assert world_props.payload_snapshot()[1] != sig
        from app.routes.world import get_world_props_route
        assert get_world_props_route()['world_props'][0]['water'] == world_props.payload_rows()[0]['water']
        loc['rooms'][0]['layout']['props'][0]['variant'] = 0
        assert 'water' not in next(m for m in scene.compose_scene(loc, plan_width_m=10)['models'] if m['id'] == pid)
        # The gate sees water even when there is no walkable-tagged lattice.
        gate_spec = copy.deepcopy(vectors['fixtures']['SPECS'][0])
        gate_spec.update(anchor=[0,0], level=0)
        location = {'id':'gate','pos_x':0,'pos_z':0}
        with patch('app.core.relief.ground_at', return_value=0), \
             patch.object(surf, '_scene_specs', return_value=([gate_spec], [])):
            assert surf.stand_height_at(location, .5, .5) == 1.5
            assert surf.stand_height_at(location, 6, 6) == 0
            gate_spec['level'] = 1
            assert surf.stand_height_at(location, .5, .5) == 0
        from app.core.relief import slope_blocks
        assert slope_blocks(1.5, .5, .4, 45)
        assert not slope_blocks(-1.5, .5, .4, 45)
        assert not slope_blocks(0, .5, .4, 45)
        from app.routes import prop_variants as pv, world as wr
        from app.core import location_model3d as lm
        from app.models import world
        from app.core.auth_dependency import require_admin
        assert pv.prop_variant_water(pid, 1)['status'] == 'valid'
        assert pv.prop_variant_water(pid, 0) == {'status':'none','water':None}
        # Check all six route registrations explicitly require admin, including reads.
        routes = [r for router in (pv.router, wr.router) for r in router.routes
                  if '/water' in r.path and ('variants/' in r.path or 'model3d/' in r.path)]
        assert len(routes) == 6
        assert all(any(d.call is require_admin for d in r.dependant.dependencies) for r in routes)
        loc['name'] = 'Water room'
        assert world.upsert_location(loc, sync_world=False)
        room_gallery = lm._gallery(loc['id'], 'r')
        room_model = room_gallery.new_path()
        room_model.write_bytes(b'room-stub')
        write_sidecar(room_model, {'tier':'full','width_m':4,'rotation':{}})
        room_gallery.select(room_model.name, 'full')
        room_water = fixture(room_model)
        w.water_path(room_model).write_text(json.dumps(room_water))
        assert wr.room_model3d_water(loc['id'], 'r')['status'] == 'valid'
        with patch.object(lm, '_demand_low'):
            width, building, metas = scene.scene_inputs(loc, loc['id'])
            composed = scene.compose_scene(loc, plan_width_m=width, building_meta=building, room_metas=metas)
        room_spec = next(m for m in composed['models'] if m['role'] == 'room')
        # width 4 over model xz extent 2 => level .5 * 2 = 1 above base.
        assert room_spec['water']['regions'][0]['y'] == room_spec['bottom_y']+1
        class Body:
            async def json(self):
                return {'regions':[{'id':'r1','look':{'preset':'pond'}}]}
        async def inline_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)
        with patch('asyncio.to_thread', inline_thread):
            patched = asyncio.run(wr.room_model3d_water_patch(loc['id'], 'r', Body()))
        assert patched['water']['regions'][0]['look']['tint'] == '#4f6a3c'
        # Test the real waiting wrapper through the routes; only the process
        # boundary is replaced, just as in the storage smoke.
        with patch('app.blender.runner.is_available', return_value=True), \
             patch('app.blender.runner.run', return_value={'ok':True,'data':room_water}), \
             patch('app.blender.refine.take_lod_slot', return_value=True), \
             patch('app.blender.refine.free_lod_slot'):
            assert wr.room_model3d_water_detect(loc['id'], 'r', wait=True)['status'] == 'valid'
        # Capture thread creation to prove the request returns before detection;
        # execute its target afterwards against the same real wrapper.
        workers = []
        class Thread:
            def __init__(self, *, target, **kwargs):
                workers.append(target)
            def start(self):
                pass
        with patch('app.core.model_water.threading.Thread', Thread):
            assert pv.prop_variant_water_detect(pid, 1) == {'started':True}
            assert len(workers) == 1
        with patch('app.blender.runner.is_available', return_value=False):
            workers[0]()
        assert not w._detect_jobs
        # A rewritten mesh refreshes opt-in water in the surface worker.
        for index in (0, 1):
            mp = props.model_path(pid, variant=index)
            mp.write_bytes(b'rewritten model')
            with patch.object(surf, 'read_surface', return_value=None), \
                 patch.object(surf, 'bake_surface', return_value=None), \
                 patch('app.blender.runner.is_available', return_value=True), \
                 patch('app.blender.runner.run', return_value={'ok':True, 'data':fixture(mp)}) as run, \
                 patch('app.blender.refine.take_lod_slot', return_value=True), \
                 patch('app.blender.refine.free_lod_slot'):
                props.bake_surfaces(pid, index)
            assert run.call_count == index
            if index:
                assert run.call_args.args == ('waterdetect',)
                assert run.call_args.kwargs['params']['target_m'] == 2
                assert run.call_args.kwargs['params']['measure'] == 'xyz'
                assert w.water_status(mp, {})['status'] == 'valid'
                assert w.read_water(mp, {})['regions'][0]['level'] == .7
        stale_bytes = w.water_path(model).read_bytes()
        model.write_bytes(b'rewritten without Blender')
        with patch.object(surf, 'read_surface', return_value=None), \
             patch.object(surf, 'bake_surface', return_value=None), \
             patch('app.blender.runner.is_available', return_value=False):
            props.bake_surfaces(pid, 1)
        assert w.water_path(model).read_bytes() == stale_bytes
        # Busy detection also preserves stale bytes; a room uses the same worker hook.
        with patch('app.blender.runner.is_available', return_value=True), \
             patch('app.blender.refine.take_lod_slot', return_value=False):
            w.refresh_after_rewrite(model, {}, target_m=2, measure='xyz')
        assert w.water_path(model).read_bytes() == stale_bytes
        room_model.write_bytes(b'rewritten room model')
        workers.clear()
        with patch.object(lm.threading, 'Thread', Thread):
            lm.request_surface(loc['id'], 'r')
        assert len(workers) == 1
        with patch.object(surf, 'read_surface', return_value=None), \
             patch.object(surf, 'bake_surface', return_value=None), \
             patch('app.blender.runner.is_available', return_value=True), \
             patch('app.blender.runner.run', return_value={'ok':True, 'data':fixture(room_model)}) as run, \
             patch('app.blender.refine.take_lod_slot', return_value=True), \
             patch('app.blender.refine.free_lod_slot'):
            workers[0]()
        assert run.call_count == 1
        assert run.call_args.kwargs['params']['target_m'] == 4
        assert run.call_args.kwargs['params']['measure'] == 'xz'
        assert w.water_status(room_model, {})['status'] == 'valid'
        # Gallery deletion must collect water alongside its mesh.
        gallery = props.model_gallery(pid, 1)
        assert gallery.delete(model.name)
        assert not w.water_path(model).exists()
    print('smoke_prop_water: PASS')


if __name__ == '__main__':
    main()
