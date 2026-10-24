#!/usr/bin/env python3
"""Verify passive item bonuses in a temporary world.

Usage: ./.venv/bin/python scripts/smoke_stat_item_boosts.py

Hand-derived expectations: base resolve 50 + equipped charm 10 = 60;
unequipped = 50. A carried charm grants 10 once regardless of stack size
or duplicate equipped slots. State 7 + item 10 yields 67. Negative 100
floors 50-100 at zero; positive 100 yields 150 without an upper clamp.
Fifty equipped-only reads require at most one definition load and zero
inventory/profile reads. Carried mode requires one inventory query without
profile or definition rereads per active_boosts call. Shared +10 yields 60, editing to +12 yields 62. An empty world yields 50;
returning to the original world restores 60. Edits/deletes invalidate bonuses.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['STORAGE_DIR'] = os.environ['INSTANCE_DIR'] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core.db import init_schema, transaction
        init_schema()
        from app.models import inventory as inv
        from app.core.stat_boosts import active_boosts, effective_stat, effective_stats
        from app.core.motion_item_cache import invalidate
        from app.core.game_time import GameTime
        with transaction() as conn:
            conn.execute("INSERT INTO characters (name, template, profile_json, config_json, created_at, updated_at) VALUES ('demo', 'demo', '{}', '{}', '', '')")
        profile = {'template': 'demo', 'character_name': 'demo', 'status_effects': {'resolve': 50},
                   'equipped_items': ['item_charm'], 'equipped_pieces': {}}
        item = inv.add_item('Bright charm', item_id='item_charm',
                            properties={'stat_bonuses': {'resolve': 10}})
        assert effective_stat(profile, 'resolve') == 60
        expected = dict(condition=item['id'], label='Bright charm', amount=10,
                        remaining_hours=0.0, source='item')
        assert effective_stats(profile)['resolve']['boosts'] == [expected]
        assert profile['status_effects']['resolve'] == 50
        inv.add_item('Empty carried charm', properties={'stat_bonuses': {}, 'bonus_when': 'carried'})
        invalidate()
        with patch.object(inv, '_load_items', wraps=inv._load_items) as loader, \
             patch.object(inv, 'get_character_inventory', wraps=inv.get_character_inventory) as reads, \
             patch.object(inv, 'get_item', wraps=inv.get_item) as item_reads, \
             patch.object(inv, 'get_connection', wraps=inv.get_connection) as db_reads, \
             patch('app.models.character.get_character_profile', side_effect=AssertionError('profile reread')):
            for _ in range(50):
                assert effective_stat(profile, 'resolve') == 60
            assert loader.call_count <= 1, loader.call_count
            assert reads.call_count == 0, reads.call_count
            assert item_reads.call_count <= 1, item_reads.call_count
            assert db_reads.call_count <= 1, db_reads.call_count
        from app.core.keyed_lock import keyed_lock
        from app.models.character import save_character_profile
        from app.models.character_template import clear_template_cache
        from app.routes.play import play_self, _state_block
        from app.routes.characters import get_status_effects_route
        template_dir = Path(tmp) / 'templates'
        template_dir.mkdir()
        (template_dir / 'demo.json').write_text(json.dumps({'sections': [{'fields': [
            {'key': 'resolve', 'store': 'status_effects', 'default': 50}]}]}))
        with patch('app.models.character_template.get_templates_dir', return_value=template_dir):
            clear_template_cache()
            with keyed_lock('character_profile', 'demo'):
                assert save_character_profile('demo', profile)
            with patch('app.models.account.get_active_character', return_value='demo'):
                for payload in (play_self(), _state_block('demo'), get_status_effects_route('demo')):
                    assert payload['stat_boosts']['resolve']['boosts'] == [expected], payload
            clear_template_cache()
        print('PASS equipped bonus, player/admin payload label, and 50-call read budget')
        profile['equipped_items'] = []
        assert effective_stat(profile, 'resolve') == 50
        profile['equipped_pieces'] = {'top': item['id'], 'outer': item['id']}
        profile['equipped_items'] = [item['id']]
        assert effective_stat(profile, 'resolve') == 60
        state = {'id': 'steady', 'label': 'Steady', 'stat_boosts': {'resolve': 7}}
        profile['active_conditions'] = [{'name': 'steady'}]
        with patch('app.core.prompt_filters.load_filters', return_value=[state]):
            assert effective_stat(profile, 'resolve') == 67
            assert active_boosts(profile, now=GameTime.parse('Y0001-D001T12:00:00'))['resolve'] == [expected, dict(
                condition='steady', label='Steady', amount=7, remaining_hours=0.0)]
        profile['active_conditions'] = []
        for amount, total in [(-100, 0), (100, 150)]:
            inv.update_item(item['id'], {'properties': {'stat_bonuses': {'resolve': amount}}})
            assert effective_stat(profile, 'resolve') == total
        inv.update_item(item['id'], {'properties': {'stat_bonuses': {'resolve': 10}, 'bonus_when': 'carried'}})
        profile['equipped_items'] = []
        profile['equipped_pieces'] = {}
        inv.add_to_inventory('demo', item['id'], quantity=3)
        from app.core.motion_item_cache import item_snapshot
        item_snapshot()
        with patch.object(inv, 'get_character_inventory', wraps=inv.get_character_inventory) as reads, \
             patch.object(inv, 'get_item', side_effect=AssertionError('uncached definition read')), \
             patch.object(inv, 'get_connection', wraps=inv.get_connection) as db_reads, \
             patch('app.models.character.get_character_profile', side_effect=AssertionError('carried profile reread')):
            assert effective_stat(profile, 'resolve') == 60
            assert reads.call_count <= 1
            assert db_reads.call_count == 1, db_reads.call_count
        profile['equipped_items'] = [item['id']]
        assert effective_stat(profile, 'resolve') == 60
        assert effective_stat({'status_effects': {'resolve': 50}}, 'resolve') == 50
        inv.remove_from_inventory('demo', item['id'], quantity=3)
        assert effective_stat(profile, 'resolve') == 50
        inv.delete_item(item['id'])
        assert effective_stat(profile, 'resolve') == 50
        print('PASS unequipped, deduplication, state stacking, bounds, carried and invalidation')
        for properties in ({'stat_bonuses': []}, {'stat_bonuses': {'': 1}},
                           {'stat_bonuses': {'  ': 1}}, {'stat_bonuses': {'resolve': True}},
                           {'stat_bonuses': {'resolve': 1.5}}, {'stat_bonuses': {'resolve': 101}},
                           {'stat_bonuses': {'resolve': -101}}, {'bonus_when': 'nearby'}):
            valid = inv.add_item('Validation target')
            for save in (lambda: inv.add_item('Invalid', properties=properties),
                         lambda: inv.update_item(valid['id'], {'properties': properties})):
                try:
                    save()
                except ValueError:
                    pass
                else:
                    raise AssertionError(f'accepted invalid properties: {properties}')
        print('PASS create/update validation')
        shared_file = Path(tmp) / 'shared-items.json'
        shared_item = dict(id='item_shared_charm', name='Shared charm',
                           properties={'stat_bonuses': {'resolve': 10}})
        profile['equipped_items'] = [shared_item['id']]
        with patch.object(inv, '_get_shared_items_file', return_value=shared_file):
            inv._save_shared_items([shared_item])
            assert effective_stat(profile, 'resolve') == 60
            inv.update_item(shared_item['id'], {'name': 'Renamed charm'})
            assert active_boosts(profile)['resolve'][0]['label'] == 'Renamed charm'
            # External shared-file edits also invalidate the versioned snapshot.
            shared_item['properties']['stat_bonuses']['resolve'] = 12
            shared_file.write_text(json.dumps({'items': [shared_item]}))
            assert effective_stat(profile, 'resolve') == 62
            inv._save_shared_items([])
            assert effective_stat(profile, 'resolve') == 50
        print('PASS shared writes and external shared-file invalidation')
        inv.add_item('World charm', item_id='item_world_charm',
                     properties={'stat_bonuses': {'resolve': 10}})
        profile['equipped_items'] = ['item_world_charm']
        assert effective_stat(profile, 'resolve') == 60
        from app.core import db
        with tempfile.TemporaryDirectory() as other, patch.dict(db._connections, {}, clear=True):
            paths.init(other)
            init_schema()
            assert effective_stat(profile, 'resolve') == 50
            for connection in db._connections.values():
                connection.close()
        paths.init(tmp)
        assert effective_stat(profile, 'resolve') == 60
        print('PASS world isolation')


if __name__ == '__main__':
    main()
