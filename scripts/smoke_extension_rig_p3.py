"""P3 effective motion in isolated worlds.

Usage: .venv/bin/python scripts/smoke_extension_rig_p3.py

Hand derivation (E4): occupied underwear_top with empty covers (.5) and
outer full coverage (.8) multiply .5*.8=.4; mirrors
count once and hidden layers still count. Partial .6 yields 1-(1-.6)/2=.8.
No pieces gives factor 1. Package gravity .35 times character 2 gives .7.
World gain .6 replaces 1 for its group only. Revisions track inputs even
when a zero gain masks a changed multiplier; identical reads stay stable.
These checks catch omitted layers, visual filtering, duplicate mirrors,
lost item fields, wrong config scope, and hashes of only effective output.
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths


def check(ok, label):
    assert ok, label
    print('PASS', label)


def main():
    with tempfile.TemporaryDirectory(prefix='extension-p3-') as tmp:
        root = Path(tmp)
        paths.init(root / 'a')
        paths.init_instance(root / 'instance')
        os.environ['ANIMATION_CLIPS_DIR'] = str(root / 'clips')
        os.environ['ANIMATION_RIG_FILE'] = str(root / 'rig.fbx')
        from app.core import db, config, config_admin, config_scope
        db.init_schema()
        config.load(paths.get_config_path(), instance_path=root / 'instance/config.json')
        from app.plugins.loader import discover_packages
        from app.plugins import registry
        import yaml
        plugins = root / 'plugins'
        package = plugins / 'sample'
        package.mkdir(parents=True)
        rig = {'id': 'sample_group', 'op': 'pair_protrusion',
               'chains': [[{'bone': 'SampleBone', 'parent': 'Hips'}]]}
        (package / 'plugin.yaml').write_text(yaml.safe_dump({
            'name': 'Sample', 'apply_to': '*', 'body_slots': [
                {'id': 'sample_slot', 'covered_by': ['underwear_top', 'underwear_bottom'], 'rig': rig},
                {'id': 'other_slot', 'rig': {**rig, 'id': 'other_group',
                    'chains': [[{'bone': 'OtherBone', 'parent': 'Hips'}]]}}]}))
        discover_packages(plugins, force=True)
        from app.models import inventory
        from app.core.extension_rig import motion_payload
        def item(iid, slots, factor, partial=False):
            return inventory.add_item(iid, category='outfit_piece', item_id=iid,
                outfit_piece={'slots': slots, 'motion_damping': factor,
                              'partially_covers' if partial else 'covers': ['underwear_top']})
        a = item('p3_a', ['top', 'bottom'], .5)
        check(a['outfit_piece'].get('motion_damping') == .5, 'create keeps damping')
        for bad_factor in (-.1, 1.1, float('nan'), True):
            try:
                item('p3_invalid', ['top'], bad_factor)
            except ValueError:
                pass
            else:
                raise AssertionError('invalid item damping accepted')
        check(True, 'item damping ranges')
        b = item('p3_b', ['outer'], .8)
        profile = {'template': 'human-default', 'equipped_pieces': {'top': a['id'], 'bottom': a['id'], 'outer': b['id']}}
        def motion(p=None):
            return motion_payload('sample', profile if p is None else p)
        def gain(p=None):
            return motion(p)['groups']['sample_group']['gain']
        check(abs(gain()-.4) < 1e-12, 'distinct covers .5 x .8; mirror once; hidden layer counts')
        check(gain({**profile, 'equipped_pieces': {'top': a['id'], 'bottom': a['id']}}) == .5, 'mirror once')
        occupied = inventory.add_item('occupied', category='outfit_piece', item_id='p3_occupied',
            outfit_piece={'slots': ['underwear_top'], 'motion_damping': .5,
                          'partially_covers': ['underwear_bottom']})
        check(occupied['outfit_piece']['covers'] == [], 'occupied fixture has empty covers')
        check(abs(gain({**profile, 'equipped_pieces': {
            'underwear_top': occupied['id'], 'outer': b['id']}}) - .4) < 1e-12,
            'occupied full beats partial; .5 x .8 gives .4')
        occupied_profile = {**profile, 'equipped_pieces': {'underwear_top': occupied['id']}}
        check(gain(occupied_profile) == .5, 'occupied snapshot warmed')
        check(inventory.delete_item(occupied['id']), 'delete occupied fixture')
        check(gain(occupied_profile) == 1, 'item deletion invalidates snapshot')
        from app.routes.inventory import _create_item_route_sync, _update_item_route_sync
        from fastapi import HTTPException
        for bad in (2, True, 'x'):
            for adapter in (
                lambda: _create_item_route_sync({'name': 'invalid', 'category': 'outfit_piece',
                    'outfit_piece': {'slots': ['top'], 'motion_damping': bad}}),
                lambda: _update_item_route_sync(a['id'], {'outfit_piece': {
                    **a['outfit_piece'], 'motion_damping': bad}}),
            ):
                try:
                    adapter()
                except HTTPException as exc:
                    check(exc.status_code == 400, 'HTTP adapter rejects invalid damping')
                else:
                    raise AssertionError('HTTP adapter accepted invalid damping')
        c = item('p3_c', ['legs'], .6, True)
        check(gain({**profile, 'equipped_pieces': {'legs': c['id']}}) == .8, 'partial cover .6 gives .8')
        check(gain({'template': 'human-default', 'outfit_description': 'plain outfit'}) == 1, 'free text no damping')
        from app.models.character import save_character_profile, get_character_profile
        from app.core.character_ops import apply_profile_update
        from fastapi import HTTPException
        check(save_character_profile('sample', profile, create_new=True), 'profile fixture')
        for bad_scale in (-1, 4, float('nan'), True):
            try:
                apply_profile_update('sample', {'fields': {'motion_gravity_scale': bad_scale}})
            except HTTPException as e:
                check(e.status_code == 400, 'character range rejected')
            else:
                raise AssertionError('invalid character scale accepted')
        apply_profile_update('sample', {'fields': {'motion_gravity_scale': 2}})
        check(get_character_profile('sample')['motion_gravity_scale'] == 2, 'character field round trip')
        from unittest.mock import patch
        with patch.object(inventory, '_load_items', wraps=inventory._load_items) as reads, \
                patch.object(inventory, '_load_shared_items', wraps=inventory._load_shared_items) as shared_reads:
            inventory.update_item(a['id'], {'name': 'counted'})
            reads.reset_mock()
            shared_reads.reset_mock()
            motion()
            motion_payload('second', profile)
            first_reads = reads.call_count
            first_shared_reads = shared_reads.call_count
            motion()
            motion_payload('second', profile)
            check(first_reads > 0 and reads.call_count == first_reads
                  and first_shared_reads == 1 and shared_reads.call_count == first_shared_reads,
                  'two unchanged polls: second poll has zero new item reads')
        with patch('app.core.extension_rig.rig_groups_for', return_value=[]), \
                patch.object(inventory, '_load_items', side_effect=AssertionError('unexpected read')):
            check(motion()['groups'] == {}, 'no applicable groups skips item reads')
        shared_file = root / 'shared-items.json'
        shared_file.write_text(json.dumps({'items': [{'id': 'shared_fixture', 'category': 'outfit_piece',
            'outfit_piece': {'slots': ['underwear_top'], 'motion_damping': .5}}]}))
        shared_profile = {**profile, 'equipped_pieces': {'underwear_top': 'shared_fixture'}}
        with patch.object(inventory, '_get_shared_items_file', return_value=shared_file):
            check(gain(shared_profile) == .5, 'shared snapshot resolves item')
            before_shared = motion(shared_profile)
            inventory.update_item('shared_fixture', {'outfit_piece': {
                'slots': ['underwear_top'], 'motion_damping': .4}})
            check(gain(shared_profile) == .4 and motion(shared_profile)['rev'] != before_shared['rev'],
                  'shared item edit invalidates snapshot and revision')
            shared_file.write_text(json.dumps({'items': [{'id': 'shared_fixture', 'category': 'outfit_piece',
                'outfit_piece': {'slots': ['underwear_top'], 'motion_damping': .25}}]}))
            check(gain(shared_profile) == .25, 'shared file reload invalidates snapshot')
        baseline = motion()
        check(motion() == baseline, 'stable reads')
        changed = copy.deepcopy(profile)
        changed['equipped_pieces'].pop('outer')
        check(motion(changed)['rev'] != baseline['rev'], 'equipment changes revision')
        changed['motion_gravity_scale'] = 2
        check(motion(changed)['groups']['sample_group']['gravity'] == .7, 'character doubles gravity')
        check(motion(changed)['rev'] != motion({**changed, 'motion_gravity_scale': 1})['rev'], 'character changes revision')
        inventory.update_item(a['id'], {'outfit_piece': {**a['outfit_piece'], 'motion_damping': .3}})
        check(inventory.get_item(a['id'])['outfit_piece']['motion_damping'] == .3, 'update keeps damping')
        check(motion()['rev'] != baseline['rev'], 'item damping changes revision')
        before = motion()
        inventory.update_item(a['id'], {'outfit_piece': {**a['outfit_piece'], 'covers': ['underwear_bottom']}})
        check(motion()['rev'] != before['rev'], 'item covers changes revision even equal output')
        from app.core import model3d, world_ops
        from app.models.character import set_character_pos
        from app.routes.world_settings import get_extension_motion
        set_character_pos('sample', 0, 0)
        check(save_character_profile('second', profile, create_new=True), 'second poll character fixture')
        set_character_pos('second', 0, 0)
        def world_row():
            return next(row for row in world_ops.build_worldmap_payload(show_all=True)['characters']
                        if row['name'] == 'sample')
        from scripts.smoke_extension_rig_p0 import glb
        from app.core.rig_contract import BASE_JOINT_NAMES
        mesh = model3d.get_model3d_dir('sample') / 'p3_example.glb'
        mesh.parent.mkdir(parents=True, exist_ok=True)
        mesh.write_bytes(glb(['mixamorig:' + name for name in BASE_JOINT_NAMES]))
        mesh.with_suffix('.json').write_text(json.dumps({'pieces': profile['equipped_pieces'], 'items': []}))
        from app.core.motion_item_cache import invalidate
        invalidate()
        with patch.object(inventory, '_load_items', wraps=inventory._load_items) as reads:
            old_row = world_row()
            first_reads = reads.call_count
            world_row()
            check(first_reads > 0 and reads.call_count == first_reads,
                  'worldmap second poll has zero new item reads')
        check(bool(old_row.get('model_sig')) and bool(old_row.get('model_rev')), 'real mesh fixture served')
        old_info = model3d.get_model3d_info('sample')
        check(old_row['motion'] == old_info['motion'], 'worldmap and model metadata parity')
        declared = get_extension_motion()['groups']
        check(next(g for g in declared if g['id'] == 'sample_group')['defaults']['gain'] == 1,
              'Setup read endpoint returns package defaults')
        values = config_admin.layer_part('world')
        values['extension_motion'] = {'groups': {'sample_group': {'gain': .6, 'spill': .5}}}
        config_admin.save_layer('world', values)
        bare = {'template': 'human-default'}
        check(gain(bare) == .6 and motion(bare)['groups']['other_group']['gain'] == 1, 'world override group only')
        check(motion(bare)['groups']['sample_group']['spill'] == .5, 'world spill override')
        spill_rev = motion(bare)['rev']
        config_admin.save_layer('world', {'extension_motion': {'groups': {'sample_group': {'gain': .6, 'spill': 0}}}})
        check(motion(bare)['rev'] != spill_rev, 'spill alone changes revision')
        config_admin.save_layer('world', values)
        check(motion()['rev'] != before['rev'], 'world changes revision')
        new_row = world_row()
        new_info = model3d.get_model3d_info('sample')
        check(new_row['motion'] == new_info['motion'] and new_row['motion']['rev'] != old_row['motion']['rev'],
              'effective worldmap and model metadata update together')
        check((new_row.get('model_sig'), new_row.get('model_rev')) ==
              (old_row.get('model_sig'), old_row.get('model_rev')) and new_info['signature'] == old_info['signature'],
              'world motion change keeps mesh identities')
        check(config_scope.scope_of('extension_motion.groups.sample_group.gain') == 'world', 'world scope')
        try:
            config_admin.save_layer('instance', {'extension_motion': values['extension_motion']})
        except config_admin.LayerSaveError:
            check(True, 'instance write rejected')
        else:
            raise AssertionError('instance accepted world settings')
        for bad in ({'spill': -0.1}, {'spill': 1.1}, {'spill': float('nan')}, {'freq_hz': 0}, {'gain': 2}, {'squash': [1.1, 2]}, {'gravity': float('nan')}):
            try:
                config_admin.save_layer('world', {'extension_motion': {'groups': {'sample_group': bad}}})
            except config_admin.LayerSaveError:
                pass
            else:
                raise AssertionError('accepted invalid override')
        check(True, 'override ranges')
        before = motion()
        registry.get_package('sample').body_slots[0].rig.params['version'] = 2
        check(motion()['rev'] != before['rev'], 'package declaration changes revision')
        for connection in db._connections.values():
            connection.close()
        db._connections.clear()
        paths.init(root / 'b')
        db.init_schema()
        config.load(paths.get_config_path(), instance_path=root / 'instance/config.json')
        check(gain(bare) == 1, 'second world isolated')
        check(gain(profile) == 1, 'world switch drops item snapshot')
        for connection in db._connections.values():
            connection.close()
        db._connections.clear()
        paths.init(root / 'a')
        config.load(paths.get_config_path(), instance_path=root / 'instance/config.json')
        check(gain(bare) == .6, 'first world override persists')
        print('P3 smoke passed')


if __name__ == '__main__':
    main()
