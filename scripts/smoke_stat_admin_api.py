#!/usr/bin/env python3
"""Exercise values APIs with an isolated world and authenticated roles.

Usage: ./.venv/bin/python scripts/smoke_stat_admin_api.py

Hand-derived expectations: sleeping at home adds 22 and Base subtracts 2,
so 50 becomes 70. Two effects rows (hourly, then item) are returned newest
first; the unrelated activity row is excluded. Cap override 8 replaces the
shared 15; deletion restores 15. Player writes return 403, malformed rules
and settings 400, and history limits outside 1..200 return 422.
"""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix='stat-api-') as tmp:
        os.environ['STORAGE_DIR'] = tmp
        os.environ['INSTANCE_DIR'] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.server import app
        from app.core import auth_dependency
        from app.core.db import init_schema, transaction
        from app.models.character import record_state_change
        from app.models.character_template import save_template
        from fastapi.testclient import TestClient
        init_schema()
        template_patch = patch('app.models.character_template.get_templates_dir', return_value=Path(tmp) / 'templates')
        template_patch.start()
        save_template('demo', {'sections': [{'fields': [
            {'key': 'energy', 'label': 'Energy', 'store': 'status_effects',
             'bar_hourly': -2}]}]})
        users = {
            'admin': {'id': 'a', 'username': 'demo', 'role': 'admin', 'allowed_characters': []},
            'player': {'id': 'p', 'username': 'demo', 'role': 'user', 'allowed_characters': ['demo']},
        }
        with patch.object(auth_dependency, '_get_session_user',
                          side_effect=lambda request: users.get(request.headers.get('x-test-user'))):
            client = TestClient(app)
            def request(method, path, body=None, role='admin'):
                return client.request(method, path, json=body, headers={'x-test-user': role})
            root = '/admin/stat-rules'
            stat = root + '/stat/energy'
            assert request('PUT', stat, {}, 'player').status_code == 403
            assert request('GET', root, role='player').status_code == 403
            assert request('GET', '/characters/other/stat-history', role='player').status_code == 403
            print('PASS auth')
            bad = request('PUT', stat, {'rates': [{'condition': 'foo>>3', 'per_hour': 1}]})
            assert bad.status_code == 400 and isinstance(bad.json()['detail'], list), bad.text
            for condition in ('energy>3 AND', 'OR energy>3', 'energy>nope', 'present:missing_character'):
                assert request('PUT', stat, {'rates': [{'condition': condition, 'per_hour': 1}]}).status_code == 400
            for rule in ({'per_hour': 101}, {'baseline': -1}, {'pull': 1.1},
                         {'per_hour': True}, {'rates': {}}, {'thresholds': [{'min': 'bad'}]},
                         {'rates': [{'condition': 'at_home', 'per_hour': 101}]},
                         {'thresholds': [{'max': 101}]}, {'pull': 10 ** 400}):
                assert request('PUT', stat, rule).status_code == 400, rule
            assert request('PUT', stat, {'per_hour': -4, 'rates': [
                {'condition': 'is_sleeping AND at_home', 'per_hour': 22, 'label': 'Sleep at home'}],
                'baseline': 50, 'pull': 0.1, 'thresholds': [{'max': 20, 'label': 'Low',
                    'text': 'Rest', 'need': {'text': 'Rest', 'urgency': 'felt'}}]}).status_code == 200
            payload = request('GET', root).json()
            row = next(r for r in payload['stats'] if r['key'] == 'energy')
            assert row['source'] == 'world' and row['effective']['per_hour'] == -4 and row['name'] == 'Energy'
            assert payload['categories'] == ['ambient', 'social', 'disruption', 'danger']
            assert payload['occasions'] == ['intent_done', 'gift_received']
            assert isinstance(payload['skills'], list)
            assert request('DELETE', stat).status_code == 200
            row = next(r for r in request('GET', root).json()['stats'] if r['key'] == 'energy')
            assert row['source'] == 'shared' and row['effective']['per_hour'] == -2
            print('PASS rules')
            setting = root + '/setting/chat_cap_per_hour'
            assert request('PUT', setting, {'value': 8}).status_code == 200
            assert request('GET', root).json()['settings']['chat_cap_per_hour']['value'] == 8
            assert request('DELETE', setting).status_code == 200
            assert request('GET', root).json()['settings']['chat_cap_per_hour']['source'] == 'shared'
            for name, value in [('chat_cap_per_hour', True), ('rewards', []),
                                ('skill_costs', {'act': {'energy': -1}}),
                                ('perception_gate', {'enabled': 1, 'stat': 'energy', 'below': 20}),
                                ('event_effects', {'unknown': {}})]:
                assert request('PUT', root + '/setting/' + name, {'value': value}).status_code == 400
            good_settings = {
                'rewards': {'intent_done': {'energy': -100}, 'gift_received': {'energy': 100}},
                'skill_costs': {'act': {'energy': 100}},
                'perception_gate': {'enabled': False, 'stat': 'energy', 'below': 0},
                'event_effects': {'danger': {'energy': -100}, 'ambient': {}},
            }
            for name, value in good_settings.items():
                path = root + '/setting/' + name
                assert request('PUT', path, {'value': value}).status_code == 200
                assert request('GET', root).json()['settings'][name]['value'] == value
                assert request('DELETE', path).status_code == 200
                assert request('GET', root).json()['settings'][name]['source'] == 'shared'
            assert request('PUT', root + '/setting/unknown', {'value': 1}).status_code == 400
            assert request('DELETE', root + '/setting/unknown').status_code == 400
            assert request('GET', root, role='').status_code == 401
            print('PASS settings')
            with transaction() as conn:
                conn.execute("INSERT INTO characters(name, created_at, updated_at) VALUES (?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')", ('demo',))
            assert record_state_change('demo', 'effects', 'hourly', metadata={
                'source': 'hourly', 'changes': {'energy': {'old': 50, 'new': 70}},
                'parts': {'energy': [{'label': 'Base', 'delta': -2}, {'label': 'Sleep at home', 'delta': 22}]}})
            assert record_state_change('demo', 'effects', 'item:Tea', metadata={
                'source': 'item:Tea', 'changes': {'energy': {'old': 70, 'new': 75}}})
            assert record_state_change('demo', 'activity', 'Reading')
            result = request('GET', '/characters/demo/stat-history', role='player')
            assert result.status_code == 200, result.text
            rows = result.json()['rows']
            assert len(rows) == 2 and rows[0]['label'] == 'Tea', rows
            assert rows[1]['label'] == 'Sleep at home +22, Base −2', rows
            assert rows[0]['id'] > rows[1]['id'] and rows[1]['game_ts']
            assert len(request('GET', '/characters/demo/stat-history?limit=1').json()['rows']) == 1
            assert request('GET', '/characters/demo/stat-history?limit=201').status_code == 422
            assert 'energy' in request('GET', '/world/stat-keys', role='player').json()['keys']
            assert request('GET', '/characters/demo/stat-history?limit=0').status_code == 422
            from app.core.stat_rules import describe_source
            for source, label in {
                'chat': 'Chat', 'activity': 'Activity', 'item:Tea': 'Tea',
                'event_resolved': 'Event resolved', 'intent_done': 'Plan done',
                'gift_received': 'Gift', 'skill:act': 'Skill act',
                'spell:Restore': 'Restore', 'event:danger': 'Event',
                'unknown': 'unknown', 'hourly': 'hourly',
            }.items():
                assert describe_source(source, None) == label
            from app.core.dependencies import get_skill_manager
            assert request('GET', root).json()['skills'] == [
                {'id': skill.SKILL_ID, 'name': skill.name}
                for skill in get_skill_manager().skills]
            print('PASS history and stat keys')
        template_patch.stop()
        print('PASS stat admin API')


if __name__ == '__main__':
    main()
