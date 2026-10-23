"""Verify Task 13 effects in temporary storage without LLM calls.

Usage: ./.venv/bin/python scripts/smoke_stat_event_effects.py
Hand-derived: danger costs 15 from 50 => 35 for all six occupants, even
though only five are prompt names. A later entrant loses 15 exactly once.
Empty category overrides suppress effects; omitted categories inherit.
Escalation costs another 15: 35=>20; a social secret hint adds 4: 20=>24.
Sanitizing clamps +/-150 to +/-100, drops unknown categories/invalid values.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['STORAGE_DIR'] = os.environ['INSTANCE_DIR'] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core.db import init_schema, transaction, get_connection
        init_schema()
        from app.core.timeutils import set_game_factor, set_game_time
        from app.core.game_time import GameTime
        set_game_factor(0)
        set_game_time(GameTime.parse('Y0001-D002T12:00:00'))
        from app.core import random_events, stat_rules, world_ops
        from app.models import character, events
        from app.models.world import get_location_by_id
        stat_rules.save_setting('event_effects', {'danger': {'courage': -15}, 'social': {'courage': 4}})
        location = world_ops.create_location_with_extras({'name': 'Square', 'event_settings': {
            'stat_effects': {'danger': {'courage': -150, '': 5, 'bad': 'oops'},
                             'social': {'courage': 150}, 'ambient': {}, 'unknown': {'courage': 2}}}})['location']
        assert location['event_settings']['stat_effects'] == {
            'danger': {'courage': -100}, 'social': {'courage': 100}, 'ambient': {}}
        world_ops.update_location_with_extras(location['id'], {'event_settings': {'stat_effects': {'ambient': {}}}})
        location = get_location_by_id(location['id'])
        for name in ('A', 'B', 'D', 'E', 'F', 'G', 'C', 'Away'):
            with transaction() as conn:
                conn.execute('INSERT INTO characters (name, template, profile_json, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
                    (name, 'test', json.dumps({'status_effects': {'courage': 50}}), '{}', '', ''))
                conn.execute('INSERT INTO character_state (character_name, current_location) VALUES (?, ?)',
                    (name, location['id'] if name not in ('C', 'Away') else 'elsewhere'))
        with patch('app.core.llm_router.llm_call', return_value=SimpleNamespace(content='A dangerous storm arrives.')) as llm:
            random_events._generate_event(location['id'], location, 'danger', ['A', 'B', 'D', 'E', 'F'], [], {})
            llm.assert_called_once()
        event = events.list_events(location['id'])[0]
        assert set(event['metadata']['stat_hit']) == {'A', 'B', 'D', 'E', 'F', 'G'}, event
        for name in ('A', 'B', 'D', 'E', 'F', 'G'):
            assert character.get_character_profile(name)['status_effects']['courage'] == 35, name
        assert character.get_character_profile('Away')['status_effects']['courage'] == 50
        with transaction() as conn:
            conn.execute("UPDATE character_state SET current_location=? WHERE character_name='C'", (location['id'],))
        # Existing effects apply even when generation is disabled or entry rolls are on cooldown.
        with patch.dict(os.environ, {'EVENT_ENTRY_ROLL_ENABLED': '0', 'EVENT_GENERATION_ENABLED': '0'}):
            random_events.try_roll_on_entry('C', location['id'], location)
            random_events.try_roll_on_entry('C', location['id'], location)
        assert character.get_character_profile('C')['status_effects']['courage'] == 35
        assert events.get_event(event['id'])['metadata']['stat_hit'].count('C') == 1
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(pool.map(lambda _: events.add_stat_hit(event['id'], 'Concurrent'), range(8)))
        assert claims.count(True) == 1, claims
        assert events.add_stat_hit('missing', 'C') is False
        # A writer holding an old event snapshot cannot erase persisted claims.
        assert events._update_event(event)
        assert events.get_event(event['id'])['metadata']['stat_hit'].count('C') == 1
        # Explicit empty danger override prevents any hit and any loss.
        location['event_settings']['stat_effects']['danger'] = {}
        other = events.add_event('Another storm', location_id=location['id'], category='danger')
        with patch.dict(os.environ, {'EVENT_ENTRY_ROLL_ENABLED': '0'}):
            random_events.try_roll_on_entry('C', location['id'], location)
        assert character.get_character_profile('C')['status_effects']['courage'] == 35
        assert 'C' not in events.get_event(other['id']).get('metadata', {}).get('stat_hit', [])
        # Resolved, expired and other-location events have no entry effect.
        events.update_event_fields(other['id'], resolved=True)
        expired = events.add_event('Old storm', location_id=location['id'], category='danger')
        events.update_event_fields(expired['id'], expires_at='Y0001-D001T00:00:00')
        events.add_event('Distant storm', location_id='elsewhere', category='danger')
        location['event_settings']['stat_effects'].pop('danger')
        with patch.dict(os.environ, {'EVENT_ENTRY_ROLL_ENABLED': '0'}):
            random_events.try_roll_on_entry('C', location['id'], location)
        assert character.get_character_profile('C')['status_effects']['courage'] == 35
        # Real NPC/follower movement uses the room-entry hook, without avatar rolls.
        from app.core import stat_rewards
        stat_rewards.register_hooks()
        character.save_character_current_location('Away', location['id'], _party_drag=True)
        assert character.get_character_profile('Away')['status_effects']['courage'] == 35
        # Alternate creation paths use the same category effects.
        # Escalation: 35-15=20; a social secret hint: 20+4=24.
        with patch('app.core.llm_router.llm_call', return_value=SimpleNamespace(content='The storm grows stronger.')):
            random_events._escalate_event(event)
        assert character.get_character_profile('A')['status_effects']['courage'] == 20
        with patch('app.core.llm_router.llm_call', return_value=SimpleNamespace(content='A subtle reminder of a hidden promise.')), patch(
                'app.models.secrets.list_secrets', return_value=[{'id': 'hint', 'content': 'A hidden promise', 'severity': 1}]):
            assert random_events._try_generate_secret_hint_event(location['id'], location, ['A', 'B'], {})
        assert character.get_character_profile('A')['status_effects']['courage'] == 24
        rows = [json.loads(row[0]) for row in get_connection().execute(
            "SELECT state_json FROM state_history WHERE character_name='A'")]
        assert [r['metadata']['source'] for r in rows if r['type'] == 'effects'] == [
            'event:danger', 'event:danger', 'event:social']
        print('PASS event effects: sanitize, all occupants, entry once, persistent claims, empty override, inactive exclusion')


if __name__ == '__main__':
    main()
