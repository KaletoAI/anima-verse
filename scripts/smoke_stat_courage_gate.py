"""Shipped danger rule checks.

Usage: ./.venv/bin/python scripts/smoke_stat_courage_gate.py
Hand-derived: 30 < 40 blocks danger 3; 45 allows it; danger 2 allows 30.
"""
import json
import os
from pathlib import Path
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
        from app.models import rules
        from app.core.db import transaction
        shipped = json.loads((Path(__file__).resolve().parents[1] / 'shared/rules/rules.json').read_text())['rules']
        rule = next((r for r in shipped if r.get('id') == 'default_courage_danger_gate'), None)
        assert rule == {'id': 'default_courage_danger_gate', 'name': 'Too scared for danger', 'name_de': 'Zu ängstlich für Gefahr', 'type': 'block', 'target': {'scope': 'danger_level', 'min_danger_level': 3, 'action': 'enter'}, 'condition': 'courage<40', 'message': 'Too scared to go there.', 'message_de': 'Zu ängstlich, um dorthin zu gehen.'}, rule
        for value, danger, allowed in ((30, 3, False), (45, 3, True), (30, 2, True)):
            with transaction() as conn:
                conn.execute('UPDATE characters SET profile_json=? WHERE name=?', (json.dumps({'status_effects': {'courage': value}}), 'Tester'))
            with patch('app.models.rules.load_rules', return_value=[rule]), patch('app.models.rules._get_target_danger_level', return_value=danger), patch('app.models.rules._user_lang', return_value='en'):
                assert rules.check_access('Tester', 'forest') == (allowed, '' if allowed else rule['message'])
        print('PASS shipped courage gate')


if __name__ == '__main__':
    main()
