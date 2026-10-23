#!/usr/bin/env python3
"""Verify effective stats using a temporary world only.

Usage: ./.venv/bin/python scripts/smoke_stat_boosts.py

Hand-derived expectations (T is fixed at Y0001-D002T12:00:00):
[a] No condition: base attention 50, no boosts, effective 50.
[b] Focused +40, started T-1h for 2h: 50+40=90, 2-1=1h left.
[c] Focused started T-3h for 2h: 3>2, so expired, effective 50.
[d] Focused + dazed: max(0,50+40-70)=20; dazed alone: max(0,-20)=0.
[e] Focused makes attention>80 true (90>80), triggering alert; alert's
    expression alone contributes no +25, so effective remains 90.
[f] Missing courage has no effective value (None).
[g] Base 95 +40=135; adjusting base by +10 clamps 105 to 100.
[h] Prompt reads effective 90; base zero renders 0, ignoring stale top-level 77.
[i] Save rejects +300 and unknown keys; +40 survives save/load.
[j] Player/admin payloads: base 50 + focused 40 = 90; only attention is
    boosted, with 2-1=1.0h left. No conditions yields an empty boost map.
    Condition chips carry attention +40 and 1.0h remaining. Expired boosts
    and net-zero sums are omitted; dazed alone yields max(0,50-70)=0.
    Editing a shared +40 state into a world override preserves +40.
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
        os.environ['STORAGE_DIR'] = tmp
        os.environ['INSTANCE_DIR'] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core.stat_boosts import active_boosts, effective_stat, effective_stats
        from app.core.db import init_schema, transaction
        from app.core.game_time import GameTime, GameDuration
        from app.core.timeutils import set_game_time, set_game_factor
        from app.core.keyed_lock import keyed_lock
        from app.models.character import save_character_profile, get_character_profile, adjust_status_effects
        from app.models.character_template import build_prompt_section
        from app.core.prompt_filters import load_filters, _triggered_filters
        from app.core.activity_engine import evaluate_condition
        from app.routes.admin_settings import _prompt_filters_save_sync
        from fastapi import HTTPException
        init_schema()
        with transaction() as conn:
            conn.execute("INSERT INTO characters (name, template, profile_json, config_json, created_at, updated_at) VALUES (?, ?, '{}', '{}', '', '')", ('demo', 'demo'))
        set_game_factor(0)
        t = GameTime.parse('Y0001-D002T12:00:00')
        set_game_time(t)
        template = {'sections': [{'fields': [
            {'key': 'attention', 'label': 'Attention', 'store': 'status_effects',
             'default': 50, 'in_prompt': True},
            {'key': 'stamina', 'store': 'status_effects', 'default': 5}]}]}
        # Keep template fixtures in temporary storage, away from the shared catalog.
        template_dir = Path(tmp) / 'templates'
        template_dir.mkdir()
        (template_dir / 'demo.json').write_text(json.dumps(template))
        with patch('app.models.character_template.get_templates_dir', return_value=template_dir):
            from app.models.character_template import clear_template_cache
            clear_template_cache()
            for fid, boosts, condition in [('focused', {'attention': 40}, ''),
                                          ('dazed', {'attention': -70}, ''),
                                          ('alert', {'attention': 25}, 'attention>80')]:
                _prompt_filters_save_sync(None, {'id': fid, 'label': fid.title(),
                                                'condition': condition, 'stat_boosts': boosts})
            profile = {'template': 'demo', 'status_effects': {'attention': 50, 'stamina': 5}}
            def store():
                with keyed_lock('character_profile', 'demo'):
                    assert save_character_profile('demo', profile)
            def cond(name, hours=1):
                return {'name': name, 'started_at': (t-GameDuration.of(hours=hours)).canonical(),
                        'duration_hours': 2}
            assert effective_stat(profile, 'attention') == 50 and active_boosts(profile) == {}
            print('PASS [a]')
            profile['active_conditions'] = [cond('focused')]
            assert effective_stat(profile, 'attention') == 90
            assert active_boosts(profile)['attention'] == [dict(condition='focused', label='Focused', amount=40, remaining_hours=1.0)]
            assert effective_stats(profile)['attention']['boost'] == 40
            print('PASS [b]')
            profile['active_conditions'] = [cond('focused', 3)]
            assert effective_stat(profile, 'attention') == 50
            print('PASS [c]')
            profile['active_conditions'] = [cond('focused'), cond('dazed')]
            assert effective_stat(profile, 'attention') == 20
            profile['active_conditions'] = [cond('dazed')]
            assert effective_stat(profile, 'attention') == 0
            print('PASS [d]')
            profile['active_conditions'] = [cond('focused')]
            store()
            assert evaluate_condition('attention>80', 'demo')[0]
            assert 'alert' in [f['id'] for f in _triggered_filters('demo', profile=profile)]
            assert effective_stat(profile, 'attention') == 90
            print('PASS [e]')
            assert effective_stat(profile, 'courage') is None
            print('PASS [f]')
            profile['status_effects']['attention'] = 95
            assert effective_stat(profile, 'attention') == 135
            store()
            adjust_status_effects('demo', {'attention': 10})
            assert get_character_profile('demo')['status_effects']['attention'] == 100
            print('PASS [g]')
            profile['status_effects']['attention'] = 50
            assert build_prompt_section(template, profile, volatile=True) == ['Attention: 90/100']
            profile['active_conditions'] = []
            profile['status_effects']['attention'] = 0
            profile['attention'] = 77
            assert build_prompt_section(template, profile, volatile=True) == ['Attention: 0/100']
            print('PASS [h]')
            for boosts in ({'attention': 300}, {'nonexistent': 5}):
                try:
                    _prompt_filters_save_sync(None, {'id': 'validation', 'stat_boosts': boosts})
                except HTTPException as exc:
                    assert exc.status_code == 400
                else:
                    raise AssertionError('invalid boosts accepted')
            _prompt_filters_save_sync(None, {'id': 'validation', 'stat_boosts': {'attention': 40}})
            assert next(f for f in load_filters() if f['id'] == 'validation')['stat_boosts'] == {'attention': 40}
            print('PASS [i]')
            from app.routes.play import play_self, _state_block
            from app.routes.characters import get_status_effects_route
            profile['status_effects']['attention'] = 50
            profile['active_conditions'] = [cond('focused')]
            store()
            expected = {'attention': dict(base=50, boost=40, value=90, boosts=[
                dict(condition='focused', label='Focused', amount=40, remaining_hours=1.0)])}
            with patch('app.models.account.get_active_character', return_value='demo'):
                payload = play_self()
                assert payload.get('stat_boosts') == expected, payload.get('stat_boosts')
                chip = next(c for c in payload['conditions'] if c['name'] == 'focused')
                assert chip['remaining_hours'] == 1.0
                assert chip['boosts'] == [{'stat': 'attention', 'amount': 40}]
                assert _state_block('demo')['stat_boosts'] == expected
                assert get_status_effects_route('demo')['stat_boosts'] == expected
                profile['active_conditions'] = []
                store()
                assert play_self()['stat_boosts'] == {}
                assert _state_block('demo')['stat_boosts'] == {}
                assert get_status_effects_route('demo')['stat_boosts'] == {}
                profile['active_conditions'] = [cond('focused', 3)]
                store()
                assert play_self()['stat_boosts'] == {}
                profile['active_conditions'] = [cond('dazed')]
                store()
                negative = get_status_effects_route('demo')['stat_boosts']['attention']
                assert (negative['base'], negative['boost'], negative['value']) == (50, -70, 0)
                _prompt_filters_save_sync(None, {'id': 'balanced', 'stat_boosts': {'attention': -40}})
                profile['active_conditions'] = [cond('focused'), cond('balanced')]
                store()
                assert play_self()['stat_boosts'] == {}
            from app.routes.admin_settings import prompt_filters_data
            shared_file = Path(tmp) / 'filters.json'
            shared_file.write_text(json.dumps({'filters': [{'id': 'shared_focus', 'label': 'Focus',
                                                'stat_boosts': {'attention': 40}}]}))
            with patch('app.core.prompt_filters._SHARED_FILE', shared_file):
                data = prompt_filters_data()
                assert 'attention' in data['stat_keys']
                shared = next(f for f in data['filters'] if f['id'] == 'shared_focus')
                assert shared['stat_boosts'] == {'attention': 40}
                _prompt_filters_save_sync(None, shared)
                override = next(f for f in prompt_filters_data()['filters'] if f['id'] == 'shared_focus')
                assert override['source'] == 'world override'
                assert override['stat_boosts'] == {'attention': 40}
            print('PASS [j]')
        print('All stat boost checks passed (10/10).')


if __name__ == '__main__':
    main()
