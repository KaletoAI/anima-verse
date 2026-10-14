"""Usage: ./.venv/bin/python scripts/smoke_terrain_sig_cache.py
Warm terrain signature: zero area reads. Each writer must invalidate its cached value.
One distinct prop across two placements requires one facts read until a placement write.
Deterministic writes between snapshot reads and cache publication must not
poison a newer generation (terrain, world props, and effective types).
The terrain one-shot list_areas hook commits after the internal read and
before publication. Capturing the key after that read would label the stale
signature with the new generation, failing the cache-key and next-call checks.
All storage and seed edits are confined to temporary files.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_tmp = tempfile.TemporaryDirectory()
from app.core import paths
paths.init(Path(_tmp.name))
from app.core import db
db.init_schema()
import json
from app.models import terrain, world_props as wp, world
from app.core import terrain_types as types
from app.core import terrain_relief_migration as relief, terrain_surface_migration as surface
seed = Path(_tmp.name) / 'types.json'
seed.write_text(types._shared_path().read_text())
area = {'id': 'area', 'kind': 'grass', 'polygon': [[0,0],[10,0],[10,10],[0,10]]}
def changed(label, writer, reader=terrain.terrain_sig):
    before = reader()
    writer()
    after = reader()
    assert before != after, label
    if isinstance(before, tuple):
        assert all(a != b for a, b in zip(before, after)), label
with patch.object(types, '_shared_path', return_value=seed):
    terrain.terrain_sig()
    with patch.object(terrain, 'list_areas', wraps=terrain.list_areas) as reads:
        terrain.terrain_sig()
        assert reads.call_count == 0, reads.call_count
    changed('save_area', lambda: terrain.save_area(area))
    # Force a cold read, then commit between its snapshot and publication.
    before_race = terrain._terrain_sig()
    terrain._sig_cache = (None, '')
    read_areas = terrain.list_areas
    pending_area_write = [True]
    def read_areas_then_write():
        rows = read_areas()
        if pending_area_write:
            pending_area_write.pop()
            terrain.save_area({**area, 'z_order': 6})
        return rows
    with patch.object(terrain, 'list_areas', side_effect=read_areas_then_write):
        stale_sig = terrain.terrain_sig()
    assert not pending_area_write, 'internal area read hook did not run'
    assert stale_sig == before_race, 'race did not retain the pre-write snapshot'
    fresh_sig = terrain._terrain_sig()
    assert fresh_sig != stale_sig, 'write did not change terrain signature'
    assert terrain._sig_cache[0] != terrain._terrain_sig_key(), 'stale signature stored under new generation'
    assert terrain.terrain_sig() == fresh_sig, 'internal read race poisoned next call'
    stale_areas = terrain.list_areas()
    terrain.save_area({**area, 'z_order': 7})
    terrain.terrain_sig(areas=stale_areas)
    assert terrain.terrain_sig() == terrain._terrain_sig(), 'stale areas poisoned current generation'
    areas_key, stale_areas = terrain.areas_snapshot()
    terrain.save_area({**area, 'z_order': 8})
    terrain.terrain_sig(areas=stale_areas, areas_key=areas_key)
    assert terrain.terrain_sig() == terrain._terrain_sig(), 'versioned stale snapshot accepted'
    changed('save_area must_exist', lambda: terrain.save_area({**area, 'z_order': 2}, must_exist=True))
    changed('delete_area', lambda: terrain.delete_area('area'))
    changed('save_areas_bulk', lambda: terrain.save_areas_bulk([{**area, 'id': '', 'temp_id': 'a'}], []))
    changed('save_world_type', lambda: types.save_world_type({'kind': 'grass', 'name': 'Changed'}))
    from app.routes.world import _put_terrain_type_route_sync
    changed('admin type route', lambda: _put_terrain_type_route_sync('grass', {'name': 'Admin changed'}))
    changed('delete_world_type', lambda: types.delete_world_type('grass'))
    changed('types stat', lambda: seed.write_text(json.dumps({'types': [{'kind': 'grass', 'name': 'Seed changed'}]})))
    changed('location generation', lambda: world.upsert_location({'id': 'site', 'name': 'Site'}), world.world_generation)

    # The shared seed is read once, and neither cache exposes mutable data.
    catalog = types.effective_catalog()
    catalog['grass']['name'] = 'mutated'
    with patch.object(Path, 'read_text', side_effect=AssertionError('warm seed read')):
        assert types.effective_catalog()['grass']['name'] == 'Seed changed'
    # A write after SELECT must leave the old catalog under its old key only.
    types.save_world_type({'kind': 'grass', 'name': 'Before race'})
    types._catalog_cache = (None, {})
    real_world_types = types._world_types
    pending_type_write = [True]
    def read_types_then_write():
        rows = real_world_types()
        if pending_type_write:
            pending_type_write.pop()
            types.save_world_type({'kind': 'grass', 'name': 'After race'})
        return rows
    with patch.object(types, '_world_types', side_effect=read_types_then_write):
        assert types.effective_catalog()['grass']['name'] == 'Before race'
    assert types.effective_catalog()['grass']['name'] == 'After race'
    # Legacy rows are seeded directly so the migrations have actual work.
    terrain.save_area(area)
    with db.transaction() as conn:
        conn.execute('UPDATE terrain_areas SET meta=? WHERE id=?', (json.dumps({'scatter': [{'yaw_mode': 'fixed'}]}), 'area'))
    terrain._bump_terrain_generation()
    changed('scatter migration', terrain.migrate_scatter_yaw_mode_once)
    types.save_world_type({'kind': 'grass', 'name': 'Grass'})
    changed('surface migration', lambda: surface.assign_surfaces(['grass']))
    with db.transaction() as conn:
        conn.execute('UPDATE terrain_types SET meta=? WHERE kind=?', (json.dumps({'relief_amplitude_m': 1, 'relief_wave_m': 32}), 'grass'))
    types._bump_types_generation()
    before_types = types.types_generation()
    before_terrain = terrain.terrain_generation()
    changed('relief migration', relief.move_relief_to_areas)
    assert types.types_generation() > before_types
    assert terrain.terrain_generation() > before_terrain
    from app.core import props
    props._write_sidecar('rock', {'name': 'Rock'})
    placement = wp.save_world_prop({'prop_id': 'rock', 'x': 0, 'z': 0})
    changed('upsert_location prop_boxes', lambda: world.upsert_location({
        'id': 'site', 'name': 'Site', 'pos_x': 0, 'pos_z': 0,
        'map3d': {'boundary': [[-5,-5],[5,-5],[5,5],[-5,5]]}}))
    wp.delete_world_prop(placement['id'])
    from app.core import heightfield
    from app.core.world_ops import build_worldmap_payload
    terrain._bump_terrain_generation()
    with patch.object(heightfield, 'current_sig', return_value='fixture'), patch.object(terrain, 'list_areas', wraps=terrain.list_areas) as area_reads:
        build_worldmap_payload(show_all=True)
        assert area_reads.call_count == 1, area_reads.call_count
    facts = {'name': 'Rock', 'variant_maps': [{'full': '/rock'}], 'max_list': [1], 'sink_list': [0], 'fix_euler': {}}
    def prop_signatures():
        return terrain.terrain_sig(), wp.world_props_sig()
    with patch.object(wp, '_prop_facts', return_value=facts) as reads, patch.object(wp, 'prop_boxes', side_effect=lambda: wp.list_world_props()):
        wp.save_world_prop({'id': 'p', 'prop_id': 'rock', 'x': 0, 'z': 0})
        wp.save_world_prop({'id': 'q', 'prop_id': 'rock', 'x': 2, 'z': 0})
        snapshot_rows, snapshot_sig = wp.payload_snapshot()
        assert snapshot_sig == wp.world_props_sig(snapshot_rows)
        first = wp.payload_rows()
        wp.payload_rows()
        assert reads.call_count == 1, reads.call_count
        first[0]['name'] = 'mutated'
        assert wp.payload_rows()[0]['name'] == 'Rock'
        changed('save_world_prop', lambda: wp.save_world_prop({'id': 'p', 'prop_id': 'rock', 'x': 1, 'z': 0}), prop_signatures)
        assert reads.call_count == 2, reads.call_count
        changed('save_world_prop must_exist', lambda: wp.save_world_prop({'id': 'p', 'prop_id': 'rock', 'x': 3, 'z': 0}, must_exist=True), prop_signatures)
        changed('delete_world_prop', lambda: wp.delete_world_prop('p'), prop_signatures)
        changed('save_world_props_bulk', lambda: wp.save_world_props_bulk([{'prop_id': 'rock', 'x': 4, 'z': 0, 'temp_id': 'new'}], []), prop_signatures)
        # Commit after reading finished rows, before publishing the cache entry.
        wp.save_world_prop({'id': 'race', 'prop_id': 'rock', 'x': 10, 'z': 0})
        build_rows = wp._build_payload_rows
        def read_rows_then_write():
            rows = build_rows()
            wp.save_world_prop({'id': 'race', 'prop_id': 'rock', 'x': 20, 'z': 0})
            return rows
        with patch.object(wp, '_build_payload_rows', side_effect=read_rows_then_write):
            old_rows, old_sig = wp.payload_snapshot()
        assert next(row for row in old_rows if row['id'] == 'race')['x'] == 10
        fresh_rows, fresh_sig = wp.payload_snapshot()
        assert next(row for row in fresh_rows if row['id'] == 'race')['x'] == 20
        assert fresh_sig != old_sig
        assert wp.world_props_sig() == wp.world_props_sig(fresh_rows)
        changed('delete_world_props_of', lambda: wp.delete_world_props_of('rock'), prop_signatures)
print('smoke_terrain_sig_cache: OK')
