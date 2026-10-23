#!/usr/bin/env python3
"""Verify player feedback in an isolated world.

Usage: ./.venv/bin/python scripts/smoke_stat_player_feedback.py

Hand-derived: 50→30 then 30→20 yields two rows, newest first, with
Tea then Chat labels. At 20, max 25 selects Low. No stats means no bands
or history; an activity row does not count toward effects history. Ten
additional effects rows replace both older rows in the ten-row window.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="stat-player-") as tmp:
        os.environ['STORAGE_DIR'] = tmp
        os.environ['INSTANCE_DIR'] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.server import app
        from app.core.db import init_schema, transaction
        from app.models.character import record_state_change
        from app.models.character_template import save_template
        from app.routes.play import play_self
        assert app
        init_schema()
        with patch('app.models.character_template.get_templates_dir', return_value=Path(tmp) / 'templates'):
            save_template('feedback', {'sections': [{'fields': [
                {'key': 'energy', 'label': 'Energy', 'store': 'status_effects',
                 'hint_thresholds': [{'max': 25, 'label': 'Low'}]}]}]})
            with transaction() as conn:
                for name, stats in [('demo', {'energy': 20}), ('empty', {})]:
                    conn.execute("INSERT INTO characters(name, template, profile_json, config_json, created_at, updated_at) VALUES (?, ?, ?, '{}', '', '')",
                                 (name, 'feedback', json.dumps({'status_effects': stats})))
                    conn.execute("INSERT INTO character_state(character_name) VALUES (?)", (name,))
            for source, old, new in [('chat', 50, 30), ('item:Tea', 30, 20)]:
                assert record_state_change('demo', 'effects', source, metadata={
                    'source': source, 'changes': {'energy': {'old': old, 'new': new}}})
            assert record_state_change('demo', 'activity', 'Reading')
            with patch('app.models.account.get_active_character', return_value='demo'):
                payload = play_self()
            rows = payload['stat_changes']
            assert len(rows) == 2 and [r['label'] for r in rows] == ['Tea', 'Chat'], rows
            assert rows[0]['id'] > rows[1]['id'] and all(r['game_ts'] for r in rows)
            assert set(rows[0]) == {'id', 'game_ts', 'label', 'changes'}
            assert rows[0]['changes'] == {'energy': {'old': 30, 'new': 20}}
            assert payload['stat_bands'] == {'energy': 'Low'}, payload['stat_bands']
            for _ in range(10):
                assert record_state_change('demo', 'effects', 'chat', metadata={
                    'source': 'chat', 'changes': {'energy': {'old': 20, 'new': 20}}})
            with patch('app.models.account.get_active_character', return_value='demo'):
                latest = play_self()['stat_changes']
            assert len(latest) == 10 and all(row['id'] > rows[0]['id'] for row in latest)
            assert [row['id'] for row in latest] == sorted((row['id'] for row in latest), reverse=True)
            for avatar in ('empty', ''):
                with patch('app.models.account.get_active_character', return_value=avatar):
                    payload = play_self()
                assert payload['stat_changes'] == [] and payload['stat_bands'] == {}, payload
        print('PASS player feedback: newest-first labels, changes, bands, empty avatars')


if __name__ == '__main__':
    main()
