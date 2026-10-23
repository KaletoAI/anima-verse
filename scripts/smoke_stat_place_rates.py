"""Verify Task 11 place rates in temporary storage.

Usage: ./.venv/bin/python scripts/smoke_stat_place_rates.py
Hand-derived: awake at home 50-2+4+2=54; travelling 50-2-6=42;
danger 3: stamina 50-2-2=46, courage 25-3+1 (pull)=23.
Sanitizing clamps 80 to 50 and -80 to -50, drops empty stats,
keeps at most ten valid entries, and supports clearing and omission.
Good company: courage 50+1=51; strength 60 or a distant friend adds nothing (51 stays 51).
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['STORAGE_DIR'] = tmp
        os.environ['INSTANCE_DIR'] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core.db import init_schema, transaction, get_connection
        init_schema()
        from app.core import world_ops, activity_engine as engine
        from app.models.world import get_location_by_id, get_room_by_id
        from app.models.character import get_character_profile
        from app.core.game_time import GameTime, GameDuration
        from app.core.timeutils import set_game_time, set_game_factor
        set_game_factor(0)
        start = GameTime.parse('Y0001-D002T12:00:00')
        raw = [{'stat': ' stamina ', 'per_hour': 80}, {'stat': '', 'per_hour': 3},
               {'stat': 'courage', 'per_hour': -80}, None,
               {'stat': 'bad', 'per_hour': 'invalid'}]
        home = world_ops.create_location_with_extras({'name': 'Home', 'stat_rates': raw,
            'rooms': [{'id': 'study', 'name': 'Study', 'stat_rates': raw}]})['location']
        expected = [{'stat': 'stamina', 'per_hour': 50}, {'stat': 'courage', 'per_hour': -50}]
        assert home.get('stat_rates') == expected, home.get('stat_rates')
        assert get_room_by_id(home, 'study')['stat_rates'] == expected
        world_ops.update_location_with_extras(home['id'], {'stat_rates': [{'stat': str(i), 'per_hour': 1} for i in range(15)]})
        assert len(get_location_by_id(home['id'])['stat_rates']) == 10
        world_ops.update_location_with_extras(home['id'], {'description': 'Kept'})
        assert len(get_location_by_id(home['id'])['stat_rates']) == 10
        world_ops.update_location_with_extras(home['id'], {'stat_rates': [], 'rooms': [
            {'id': 'study', 'name': 'Study', 'stat_rates': []}]})
        assert get_location_by_id(home['id']).get('stat_rates', []) == []
        world_ops.update_location_with_extras(home['id'], {'stat_rates': [{'stat': 'stamina', 'per_hour': 4}],
            'rooms': [{'id': 'study', 'name': 'Study', 'stat_rates': [{'stat': 'stamina', 'per_hour': 2}]}]})
        world_ops.update_location_with_extras(home['id'], {'rooms': [
            {'id': 'study', 'name': 'Study', 'stat_rates': raw}]})
        assert get_room_by_id(get_location_by_id(home['id']), 'study')['stat_rates'] == expected
        world_ops.update_location_with_extras(home['id'], {'rooms': [
            {'id': 'study', 'name': 'Study', 'stat_rates': [{'stat': 'stamina', 'per_hour': 2}]}]})
        plain = world_ops.create_location_with_extras({'name': 'Road'})['location']
        danger = world_ops.create_location_with_extras({'name': 'Danger', 'danger_level': 3})['location']
        template = json.loads((ROOT / 'plugins/rp/templates/character/rp.json').read_text())
        with patch('app.models.character_template.get_template', return_value=template), patch(
                'app.models.character_template.is_feature_enabled', return_value=True):
            for name, location, room, values, expected, journey in [
                ('home', home['id'], 'study', {'stamina': 50}, {'stamina': 54}, None),
                ('travel', plain['id'], '', {'stamina': 50}, {'stamina': 42}, {'active': True}),
                ('danger', danger['id'], '', {'stamina': 50, 'courage': 25}, {'stamina': 46, 'courage': 23}, None)]:
                with transaction() as conn:
                    conn.execute('INSERT INTO characters (name, template, profile_json, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
                        (name, 'place-test', json.dumps({'status_effects': values}), json.dumps({'home_location': home['id']}), '', ''))
                    conn.execute('INSERT INTO character_state (character_name, current_location, current_room) VALUES (?, ?, ?)', (name, location, room))
                with patch('app.core.travel_engine.get_journey', return_value=journey):
                    set_game_time(start)
                    engine.apply_hourly_status_tick(name)
                    set_game_time(start + GameDuration.of(hours=1))
                    engine.apply_hourly_status_tick(name)
                assert get_character_profile(name)['status_effects'] == expected, name
            from app.models.relationship import update_relationship_manual
            update_relationship_manual('home', 'travel', strength=61)
            with transaction() as conn:
                conn.execute("UPDATE character_state SET current_location=? WHERE character_name='travel'", (home['id'],))
            from app.core.keyed_lock import keyed_lock
            from app.models.character import save_character_profile
            with keyed_lock('character_profile', 'home'):
                profile = get_character_profile('home')
                profile['status_effects']['courage'] = 50
                assert save_character_profile('home', profile)
            for hour, strength, location, expected_courage in [
                (2, 61, home['id'], 51), (3, 60, home['id'], 51), (4, 61, plain['id'], 51)]:
                update_relationship_manual('home', 'travel', strength=strength)
                with transaction() as conn:
                    conn.execute("UPDATE character_state SET current_location=? WHERE character_name='travel'", (location,))
                set_game_time(start + GameDuration.of(hours=hour))
                engine.apply_hourly_status_tick('home')
                assert get_character_profile('home')['status_effects']['courage'] == expected_courage
            rows = [json.loads(row[0]) for row in get_connection().execute(
                "SELECT state_json FROM state_history WHERE character_name='home'")]
            parts = [r for r in rows if r['type'] == 'effects'][0]['metadata']['parts']['stamina']
            assert {'label': 'Place: Home', 'delta': 4} in parts, parts
            assert {'label': 'Room: Study', 'delta': 2} in parts, parts
        print('PASS place/room sanitizing, persistence, hourly parts, travel and danger rates')


if __name__ == '__main__':
    main()
