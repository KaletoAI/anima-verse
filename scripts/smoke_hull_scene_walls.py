"""Hull scene fallback and conservative legacy cleanup, isolated in temp storage."""
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths


def main():
    with tempfile.TemporaryDirectory(prefix='hull-scene-walls-') as tmp:
        paths.init(Path(tmp))
        from app.core import db, hull_model, hull_styles, location_model3d, scene_recipe
        from app.models.world import (upsert_location, get_location_by_id,
                                      get_world_setting)
        from _hull_fixtures import stepped_house
        from app.core.model_store import read_sidecar, write_sidecar

        db.init_schema()

        def save(loc, style='steinhaus'):
            assert upsert_location(loc, sync_world=True)
            location_model3d.save_hull_model(loc['id'], b'glTF', b'glTF',
                placement_full={}, placement_low={}, description={},
                fingerprint='', style_id=style, walls={'0': 'g', '1': 'w'})

        loc = stepped_house()
        # Inset rooms leave contour stretches for the hull to own.
        for room in loc['rooms']:
            room['layout'].update(x=2, y=2, w=2, d=2, openings=[])
        save(loc)
        for fields, expected in [({}, {0: 'g', 1: 'w'}),
                                 ({'wall_kind': 'a'}, {0: 'a', 1: 'a'}),
                                 ({'level_walls': {'1': 'b'}}, {0: 'g', 1: 'b'})]:
            current = deepcopy(loc)
            current['map3d'].update(fields)
            scene = scene_recipe.compose_scene(
                current, building_meta=location_model3d.get_client_meta(loc['id']))
            for level, kind in expected.items():
                pieces = [p for p in scene['walls'] if p['level'] == level and 'room_id' not in p]
                assert pieces and all(p.get('texture_kind') == kind for p in pieces), (level, pieces)
        # Empty hull kinds keep the current untextured contract; an archived
        # plan hull must not affect a selected ordinary building model.
        selected = location_model3d.find_building_model(loc['id'], tier='full')
        original_meta = read_sidecar(selected)
        for meta in ({**original_meta, 'plan_hull': False},
                     {**original_meta, 'hull': {**original_meta['hull'], 'walls': {}}}):
            write_sidecar(selected, meta)
            pieces = [p for p in scene_recipe.compose_scene(
                loc, building_meta=location_model3d.get_client_meta(loc['id']))['walls'] if 'room_id' not in p]
            assert pieces and all('texture_kind' not in p for p in pieces)
        write_sidecar(selected, original_meta)
        print('PASS scene fallback, floor-plan precedence, inactive and empty hull')

        style = hull_styles.get_style('fachwerk')['materials']
        ground = {'0': style['wall_ground']} if style['wall_ground'] else {}
        originals = {}
        for name, fields in [('exact', {'wall_kind': style['wall'], 'level_walls': ground}),
                             ('different', {'wall_kind': 'authored', 'level_walls': ground}),
                             ('extra', {'wall_kind': style['wall'], 'level_walls': {**ground, '2': 'extra'}})]:
            item = deepcopy(loc)
            item['id'] = name
            item['map3d'].update(fields)
            item['map3d']['keep'] = 'sentinel'
            save(item, 'fachwerk')
            originals[name] = get_location_by_id(name)
        for name, level_walls in [('no-ground-absent', None), ('no-ground-empty', {})]:
            item = deepcopy(loc)
            item['id'] = name
            item['map3d']['wall_kind'] = hull_styles.get_style('steinhaus')['materials']['wall']
            if level_walls is not None:
                item['map3d']['level_walls'] = level_walls
            save(item)
            originals[name] = get_location_by_id(name)
        assert hull_model.cleanup_wall_write_back() == 3
        for name in ('exact', 'no-ground-absent', 'no-ground-empty'):
            expected = deepcopy(originals[name])
            expected['map3d'].pop('wall_kind')
            expected['map3d'].pop('level_walls', None)
            assert get_location_by_id(name) == expected
        for name in ('different', 'extra'):
            assert get_location_by_id(name) == originals[name]
        assert get_world_setting('hull_wall_kinds_cleanup_v1') == 'done'
        assert hull_model.cleanup_wall_write_back() == 0
        print('PASS exact cleanup, authored values preserved, flag rerun')


if __name__ == '__main__':
    main()
