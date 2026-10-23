"""Verify success-only skill costs with synthetic stats and tools.

Usage: ./.venv/bin/python scripts/smoke_stat_skill_costs.py
Hand-derived: 12 fuel minus 5 = 7; 4 < 5 refuses. Error leaves 7.
Missing stats and unconfigured comment verbs cost zero. Boosts affect
eligibility; deductions affect the stored stat and record skill provenance.
"""
import asyncio
import json
import os
import tempfile
from unittest.mock import patch
from smoke_stat_skill_gate import setup


async def inline_thread(func, *args, **kwargs):
    """Execute mocked route services directly; no real blocking work is present."""
    return func(*args, **kwargs)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['STORAGE_DIR'] = os.environ['INSTANCE_DIR'] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        sm = setup(tmp)
        from app.core import skill_gate, stat_rules
        from app.models import character
        from app.core.db import get_connection
        stat_rules.save_setting('skill_costs', {'fake_photo': {'fuel': 5, 'absent': 30}})
        with patch('app.core.dependencies.get_skill_manager', return_value=sm), patch(
                'app.models.rules.load_rules', return_value=[]), patch(
                'asyncio.to_thread', side_effect=inline_thread):
            character.adjust_status_effects('Tester', {'fuel': 2})
            assert not skill_gate.blocked_reason('Tester', 'fake_photo')
            assert skill_gate.run_gated('Tester', 'fake_photo', lambda: 'Done') == 'Done'
            assert character.get_character_profile('Tester')['status_effects']['fuel'] == 7
            # Streaming fallback may invoke an already gated context wrapper.
            character.adjust_status_effects('Tester', {'fuel': 5})
            skill_gate.run_tool('Tester', 'FakePhoto', lambda: skill_gate.run_gated(
                'Tester', 'fake_photo', lambda: 'Done'))
            assert character.get_character_profile('Tester')['status_effects']['fuel'] == 7
            assert skill_gate.run_gated('Tester', 'fake_photo', lambda: 'Error: failed') == 'Error: failed'
            assert character.get_character_profile('Tester')['status_effects']['fuel'] == 7
            character.adjust_status_effects('Tester', {'fuel': -3})
            assert skill_gate.blocked_reason('Tester', 'fake_photo') == 'Too exhausted for FakePhoto (needs 5 fuel)'
            assert skill_gate.run_gated('Tester', 'fake_photo', lambda: 'Done').startswith('Error: ')
            # Effective boosts and the first declaring template label are used.
            profile = character.get_character_profile('Tester')
            profile['active_conditions'] = [{'name': 'boost'}]
            with patch('app.models.character.get_character_profile', return_value=profile), patch(
                    'app.core.prompt_filters.load_filters', return_value=[{
                        'id': 'boost', 'enabled': True, 'stat_boosts': {'fuel': 2}}]):
                assert not skill_gate.blocked_reason('Tester', 'fake_photo')
            with patch('app.models.character_template.list_templates', return_value=[{'name': 'z'}, {'name': 'a'}]), patch(
                    'app.models.character_template.get_template', side_effect=lambda name: {'sections': [{'fields': [{
                        'key': 'fuel', 'store': 'status_effects', 'label': 'Fuel reserve' if name == 'a' else 'Other label'}]}]}):
                assert skill_gate.blocked_reason('Tester', 'fake_photo') == 'Too exhausted for FakePhoto (needs 5 Fuel reserve)'
            # The player prepare call is free; only successful photo submission pays.
            character.adjust_status_effects('Tester', {'fuel': 8})
            from app.routes import play
            class Request:
                async def json(self):
                    return {}
            with patch('app.models.character.get_character_skill_config', return_value={'enabled': True}), patch(
                    'app.models.account.get_active_character', return_value='Tester'), patch(
                    'app.core.scene_photo.prepare_scene_photo', return_value={'ok': True}), patch(
                    'app.core.scene_photo.take_scene_photo', return_value={'ok': True}):
                assert asyncio.run(play.play_scene_photo_prepare(user={}))['ok']
                assert character.get_character_profile('Tester')['status_effects']['fuel'] == 12
                assert asyncio.run(play.play_scene_photo(Request(), user={}))['ok']
                assert character.get_character_profile('Tester')['status_effects']['fuel'] == 7
            stat_rules.save_setting('skill_costs', {'fake_photo': {'fuel': 5}, 'fake_move': {'fuel': 5}})
            character.adjust_status_effects('Tester', {'fuel': 5})
            class TravelRequest:
                async def json(self):
                    return {'target_id': 'destination'}
            with patch('app.models.character.get_character_skill_config', return_value={'enabled': True}), patch(
                    'app.models.account.get_active_character', return_value='Tester'), patch(
                    'app.models.world.get_location_by_id', return_value={'id': 'destination'}), patch(
                    'app.core.party_engine.is_party_follower', return_value=False), patch(
                    'app.models.rules.check_leave', return_value=(True, '')), patch(
                    'app.core.world_ops.conditions_pass', return_value=True), patch(
                    'app.core.danger_system.check_location_access', return_value=(True, '')), patch(
                    'app.models.character.is_character_sleeping', return_value=False), patch(
                    'app.routes.play._travel_block', return_value={'target_id': 'destination'}), patch(
                    'app.core.travel_engine.start_journey', return_value=({'id': 'journey'}, '')):
                asyncio.run(play.play_travel(TravelRequest(), user={}))
                assert character.get_character_profile('Tester')['status_effects']['fuel'] == 7
                with patch('app.core.travel_engine.start_journey', return_value=(None, 'no route')):
                    asyncio.run(play.play_travel(TravelRequest(), user={}))
                assert character.get_character_profile('Tester')['status_effects']['fuel'] == 7
            skill_gate.run_gated('Tester', 'fake_photo', lambda: {'success': False, 'error': 'failed'})
            assert character.get_character_profile('Tester')['status_effects']['fuel'] == 7
            assert not skill_gate.blocked_reason('Tester', 'fake_comment')
            assert skill_gate.charge('Tester', 'fake_comment') == {}
            with patch('app.models.character.get_character_profile', return_value={'status_effects': {}}):
                assert not skill_gate.blocked_reason('Tester', 'fake_photo')
                assert skill_gate.charge('Tester', 'fake_photo') == {}
            history = [json.loads(row[0]) for row in get_connection().execute('SELECT state_json FROM state_history')]
            assert sum(r.get('metadata', {}).get('source') == 'skill:fake_photo' for r in history) == 3
        print('PASS skill costs: success, shortfall, errors, absent stats, free verbs, history')


if __name__ == '__main__':
    main()
