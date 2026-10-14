"""Localized season renames invalidate derived caches; unrelated saves stay warm."""
import copy
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths

with tempfile.TemporaryDirectory() as tmp:
    paths.init(Path(tmp))
    from app.core import config, db, props, scene_recipe, timeutils
    from app.core.game_time import GameTime
    from app.models import terrain, world_props as wp

    db.init_schema()
    config.load(paths.get_config_path(), instance_path=Path(tmp) / 'instance' / 'config.json')
    settings = copy.deepcopy(config._CONFIG)
    settings['game_seasons'][0]['name_de'] = 'Old Spring'
    config.save(settings)
    pid = props.create_prop(name='Season fixture', width_m=2, height_m=3, depth_m=1)['id']
    for i in range(2):
        if i:
            props.add_variant(pid)
        gallery = props.model_gallery(pid, i)
        mesh = gallery.new_path()
        mesh.write_bytes(b'fixture mesh')
        gallery.select(mesh.name, 'full')
    props.set_variant_dims(pid, 1, {'width_m': 4, 'height_m': 6})
    props.set_variant_seasons(pid, 0, ['Old Spring'])
    props.set_variant_seasons(pid, 1, ['New Spring'])
    wp.save_world_prop({'prop_id': pid, 'x': 0, 'z': 0})
    terrain.save_area({'id': 'area', 'kind': 'grass',
                      'polygon': [[0, 0], [10, 0], [10, 10], [0, 10]],
                      'meta': {'scatter': [{'model': f'/assets/props/{pid}/model'}]}})
    location = {'id': 'site', 'name': 'Site'}

    def snapshot():
        return (terrain.terrain_sig(), wp.payload_snapshot(),
                scene_recipe.scene_fingerprint(location, 'site'))

    with patch.object(timeutils, 'game_time', return_value=GameTime.parse('Y0001-D001T12:00:00')):
        assert props.primary_variant(pid) == 0
        before = snapshot()
        assert before[1][0][0]['max_m'] == 3
        with patch.object(terrain, 'terrain_sig', return_value='fixed terrain'):
            before_scene_key = scene_recipe.scene_fingerprint(location, 'site')
        before_keys = terrain._sig_cache[0], wp._payload_cache[0]
        settings = copy.deepcopy(config._CONFIG)
        settings['game_seasons'][0]['name_de'] = 'New Spring'
        config.save(settings)
        after = snapshot()
        after_keys = terrain._sig_cache[0], wp._payload_cache[0]
        assert all(a != b for a, b in zip(before_keys, after_keys)), 'season rename must change both cache keys'
        assert all(a != b for a, b in zip(before, after)), 'season rename must change terrain, props and fingerprint'
        assert props.primary_variant(pid) == 1
        assert after[1][0][0]['max_m'] == 6
        with patch.object(terrain, 'terrain_sig', return_value='fixed terrain'):
            assert scene_recipe.scene_fingerprint(location, 'site') != before_scene_key, 'scene must key on season independently of terrain'
        assert after[0] == terrain._terrain_sig(), 'terrain must equal fresh composition'
        assert after[1][0] == wp._build_payload_rows(), 'payload must equal fresh composition'
        terrain._sig_cache = (None, '')
        wp._payload_cache = (None, [], '')
        assert snapshot() == after, 'cold composition must agree'

        settings = copy.deepcopy(config._CONFIG)
        settings['game_seasons'][0]['weather_note'] = 'Unrelated weather note'
        config.save(settings)
        with patch.object(terrain, '_terrain_sig', side_effect=AssertionError('terrain cache miss')), patch.object(
                wp, '_build_payload_rows', side_effect=AssertionError('payload cache miss')):
            assert snapshot() == after, 'unrelated config save must keep caches and fingerprint'
print('smoke_season_cache_keys: OK')
