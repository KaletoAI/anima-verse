#!/usr/bin/env python3
"""Check shipped states and lossless moves in a temporary world.

Usage: ./.venv/bin/python scripts/smoke_stat_states.py
Hand-derived: 20 < 30 and not < 10 means tired; 5 < 10 means exhausted
only. Strict bounds exclude 30/75/25/80. A +5 boost must remain +5 on
insert, conflict update, reverse move and subsequent world move.
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
        os.environ.update(STORAGE_DIR=tmp, INSTANCE_DIR=tmp)
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core.db import init_schema, transaction
        init_schema()
        from app.core import prompt_filters as pf
        from app.core.activity_engine import validate_condition_references
        from app.routes.admin_settings import _prompt_filters_move_sync, prompt_filters_data
        shipped = json.loads((ROOT / 'shared/prompt_filters/filters.json').read_text())['filters']
        ids = [f['id'] for f in shipped]
        assert len(ids) == len(set(ids))
        for entry in shipped:
            assert not validate_condition_references(entry.get('condition', '')), entry
        expected = {'tired': 'stamina<30 AND NOT stamina<10', 'alert': 'attention>75',
                    'distracted': 'attention<25', 'scared': 'courage<25', 'bold': 'courage>80'}
        for fid, condition in expected.items():
            entry = next((f for f in shipped if f['id'] == fid), None)
            assert entry is not None, f'missing shipped state {fid}'
            assert entry['condition'] == condition and entry['enabled']
            assert entry['icon'] and entry['prompt_modifier'] and entry['image_modifier']
            assert not entry.get('drop_blocks') and not entry.get('stat_boosts')
        for value, wanted, absent in [(20, 'tired', 'exhausted'), (5, 'exhausted', 'tired')]:
            active = {f['id'] for f in pf._triggered_filters('demo', profile={
                'status_effects': {'stamina': value, 'attention': 50, 'courage': 50}})}
            assert wanted in active and absent not in active, active
        for key, fid, boundary, inside in [('stamina', 'tired', 30, 29),
                                           ('attention', 'alert', 75, 76),
                                           ('attention', 'distracted', 25, 24),
                                           ('courage', 'scared', 25, 24),
                                           ('courage', 'bold', 80, 81)]:
            for value, triggered in [(boundary, False), (inside, True)]:
                stats = {'stamina': 50, 'attention': 50, 'courage': 50, key: value}
                active = {f['id'] for f in pf._triggered_filters('demo', profile={'status_effects': stats})}
                assert (fid in active) == triggered, (fid, value, active)
        print('PASS shipped shape, validation, strict boundaries and exclusive energy bands')
        # A character without these values never shows the band states
        # (a missing stat must not read as 100 in a state condition).
        active = {f['id'] for f in pf._triggered_filters('demo', profile={'status_effects': {}})}
        assert not active & {'tired', 'alert', 'distracted', 'scared', 'bold'}, active
        assert not pf._evaluate('attention>75', 'demo')
        from app.core.activity_engine import evaluate_condition
        assert evaluate_condition('attention>75', 'demo')[0], 'rules keep missing=100'
        print('PASS no band state for a character without the values; rules unchanged')
        shared = Path(tmp) / 'filters.json'
        shared.write_text(json.dumps({'filters': [{'id': 'boosted', 'stat_boosts': {'x': 5}}]}))
        with patch.object(pf, '_SHARED_FILE', shared):
            pf.invalidate_filter_snapshot()
            for target in ['world', 'world', 'shared', 'world']:
                _prompt_filters_move_sync('boosted', None, {'target': target})
                assert next(f for f in pf.load_filters() if f['id'] == 'boosted')['stat_boosts'] == {'x': 5}, target
            with transaction() as conn:
                conn.execute("UPDATE prompt_filters SET meta='{}' WHERE id='boosted'")
            assert 'stat_boosts' in next(f for f in prompt_filters_data()['filters'] if f['id'] == 'boosted')['masked_fields']
        print('PASS insert, conflict, reverse move and masked boosts')


if __name__ == '__main__':
    main()
