"""Caster spell cost checks.

Usage: ./.venv/bin/python scripts/smoke_stat_spell_cost.py
Hand-derived: 15 minus 10 = 5 on success and failure; 8 < 10 refuses.
The target remains at 10; absent stats are ignored. Effective 11 covers cost
10 with stored 8, so payment clamps to 0. Both anchor outcomes pay 15-10=5.
Two ordinary attempts + one boosted + two anchor attempts = five history rows.
"""
import asyncio
import json
import os
import tempfile
from unittest.mock import patch
from smoke_stat_skill_gate import setup


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['STORAGE_DIR'] = os.environ['INSTANCE_DIR'] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        setup(tmp)
        from app.models import character, inventory
        from app.core import spell_engine
        from app.core.db import transaction, get_connection
        from app.routes.inventory import _create_item_route_sync
        with transaction() as conn:
            conn.execute("INSERT INTO characters (name, template, profile_json, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)", ('Target', 'test', json.dumps({'status_effects': {'fuel': 10}}), '{}', '', ''))
        item = _create_item_route_sync({'name': 'Spark', 'category': 'spell', 'incantation': 'spark', 'cost': {'fuel': 10, 'absent': 20, 'bad': 0, 'bool': True, 'large': 101, 'text': '5'}})['item']
        assert item.get('cost') == {'fuel': 10, 'absent': 20}, item
        inventory.add_to_inventory('Tester', item['id'])
        spell = spell_engine.build_spell_catalog('Tester')[0]
        assert spell['cost'] == item['cost']
        spell.update(success_chance=50, copy_on_give=True)
        for roll in (1, 100):
            character.adjust_status_effects('Tester', {'fuel': 15 - character.get_character_profile('Tester')['status_effects']['fuel']})
            with patch('random.randint', return_value=roll), patch('app.models.character.set_pose_intent'):
                result = spell_engine.execute_cast('Tester', 'Target', spell)
            assert result['success'] == (roll == 1)
            assert character.get_character_profile('Tester')['status_effects']['fuel'] == 5
            assert character.get_character_profile('Target')['status_effects']['fuel'] == 10
        character.adjust_status_effects('Tester', {'fuel': 3})
        spell['copy_on_give'] = False
        with patch('random.randint', side_effect=AssertionError('refusal must not roll')):
            refused = spell_engine.execute_cast('Tester', 'Target', spell)
        assert refused['reason'] == 'cost' and refused['hint'] == 'Too exhausted to cast Spark.'
        assert set(result) <= set(refused)
        assert character.get_character_profile('Tester')['status_effects']['fuel'] == 8
        assert refused['roll'] is None
        held = inventory.get_character_inventory('Tester')['inventory']
        assert len(held) == 1 and held[0]['item_id'] == item['id'] and held[0]['quantity'] == 1
        from app.routes.play import build_belongings
        assert build_belongings('Tester')['items'][0]['cast_blocked'] == refused['hint']
        with patch('app.models.account.get_active_character', return_value='Tester'):
            from app.routes.play import play_item_detail
            assert play_item_detail(item['id'], user={})['cast_blocked'] == refused['hint']
        from app.routes.play import _cast_from_inventory
        async def inline_thread(func, *args, **kwargs):
            return func(*args, **kwargs)
        with patch('random.randint', side_effect=AssertionError('no roll')), patch('app.core.perception.record_utterance'), patch('asyncio.to_thread', side_effect=inline_thread):
            response = asyncio.run(_cast_from_inventory('Tester', 'Target', item['id']))
        assert response['success'] is False and response['hint'] == refused['hint']
        assert response['reason'] == 'cost'
        with patch('app.core.spell_engine.detect_cast', return_value=spell), patch('random.randint', side_effect=AssertionError('no roll')):
            assert spell_engine.detect_and_cast('Tester', 'Target', 'spark')['reason'] == 'cost'
        # Effective boosts permit payment from the stored value, clamped at zero.
        with patch('app.core.stat_boosts.effective_stat', side_effect=lambda profile, key: 11 if key == 'fuel' else None), patch('random.randint', return_value=100):
            assert 'reason' not in spell_engine.execute_cast('Tester', 'Target', spell)
        assert character.get_character_profile('Tester')['status_effects']['fuel'] == 0
        # Anchor failure and success each pay once, independently of delivery.
        spell.update(cost={'fuel': 10}, anchor_item_id='anchor', copy_on_give=True)
        for anchor in (None, {'kind': 'room', 'location_id': 'there', 'room_id': ''}):
            character.adjust_status_effects('Tester', {'fuel': 15})
            with patch('random.randint', return_value=1), patch('app.models.inventory.find_item_location', return_value=anchor), patch('app.models.character.save_character_current_location'), patch('app.models.character.set_pose_intent'):
                anchored = spell_engine.execute_cast('Tester', 'Target', spell)
            assert anchored['success'] == bool(anchor)
            assert character.get_character_profile('Tester')['status_effects']['fuel'] == 5
            character.adjust_status_effects('Tester', {'fuel': -5})
        spell['cost'] = {'absent': 10}
        with patch('random.randint', return_value=100):
            assert 'reason' not in spell_engine.execute_cast('Tester', 'Target', spell)
        rows = [json.loads(r[0]) for r in get_connection().execute('SELECT state_json FROM state_history')]
        assert sum(r.get('metadata', {}).get('source') == 'spell:Spark' for r in rows) == 5
        assert inventory.update_item(item['id'], {'cost': []})['cost'] == {}
        assert 'cost' not in inventory.update_item(item['id'], {'category': 'tool'})
        print('PASS spell costs')


if __name__ == '__main__':
    main()
