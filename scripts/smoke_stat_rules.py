#!/usr/bin/env python3
"""Verify stat rules and condition atoms in temporary storage.

Usage: ./.venv/bin/python scripts/smoke_stat_rules.py

Hand-derived cases:
[a] Field energy: hourly -2, baseline 50, pull .1; absent lists become [].
[b] Whole-entry override -5 discards baseline 50; deletion restores -2.
[c] Own danger 4: 4>3 true, 4>4 false, including state expressions;
    the missing stat location_danger must never supply a default 100.
[d] Home loc_a matches only loc_a, empty home never matches. Offmap requires
    both no location and no position; (3,4) is on-map. A journey means travelling.
[e] Energy 20<30 activates s1; loop -> loop must return false.
[f] Character baseline 70 and hourly -4 replace the corresponding rule values.
[g] Nearest integer, ties away from zero: .5=1, -.5=-1, 1.49=1,
    -2.5=-3, .4=0.
[h] Shared chat cap 15 becomes world 8; deletion restores shared 15.
    An unknown setting name is rejected.
"""
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
        from app.core import stat_rules as rules
        from app.core.db import init_schema
        from app.core.activity_engine import evaluate_condition
        from app.core import prompt_filters
        init_schema()
        field = dict(key='energy', store='status_effects', bar_hourly=-2,
                     bar_baseline=50, bar_pull=.1)
        template = {'sections': [{'fields': [field]}]}
        assert rules.field_rule(field) == dict(key='energy', per_hour=-2,
                baseline=50, pull=.1, rates=[], thresholds=[])
        print('PASS [a]')
        assert rules.save_stat_override('energy', {'per_hour': -5})
        overridden = rules.rules_for_template(template)['energy']
        assert overridden['per_hour'] == -5 and overridden['baseline'] is None
        assert rules.delete_stat_override('energy')
        assert rules.rules_for_template(template)['energy']['per_hour'] == -2
        print('PASS [b]')
        profile = {'template': 'demo', 'status_effects': {'energy': 80}}
        with patch('app.models.character.get_character_profile', return_value=profile), \
             patch('app.models.character.get_character_current_location', return_value='loc_a') as location, \
             patch('app.models.character.get_character_pos', return_value=None) as pos, \
             patch('app.models.character.get_character_config', return_value={'home_location': 'loc_a'}) as config, \
             patch('app.models.world.get_location_by_id', return_value={'danger_level': 4}), \
             patch('app.core.travel_engine.get_journey', return_value={'target': 'loc_b'}), \
             patch.object(prompt_filters, 'load_filters', return_value=[
                 {'id': 'danger', 'condition': 'location_danger>3'},
                 {'id': 'safe', 'condition': 'location_danger>4'}]) as filters:
            from app.core.stat_boosts import effective_stat
            def checked_stat(p, key):
                assert key != 'location_danger', 'danger treated as a stat'
                return effective_stat(p, key)
            with patch('app.core.stat_boosts.effective_stat', side_effect=checked_stat):
                assert evaluate_condition('location_danger>3', 'demo', 'target')[0]
                assert not evaluate_condition('location_danger>4', 'demo', 'target')[0]
                assert [s['id'] for s in prompt_filters._triggered_filters('demo', profile=profile)] == ['danger']
            print('PASS [c]')
            assert evaluate_condition('at_home', 'demo', 'target')[0]
            location.return_value = 'loc_b'
            assert not evaluate_condition('at_home', 'demo')[0]
            config.return_value = {'home_location': ''}
            assert not evaluate_condition('at_home', 'demo')[0]
            location.return_value = ''
            assert evaluate_condition('offmap', 'demo')[0]
            pos.return_value = {'x': 3, 'z': 4}
            assert not evaluate_condition('offmap', 'demo')[0]
            assert evaluate_condition('travelling', 'demo')[0]
            print('PASS [d]')
            profile['status_effects']['energy'] = 20
            filters.return_value = [{'id': 's1', 'condition': 'energy<30'},
                                    {'id': 'loop', 'condition': 'state:loop'}]
            assert evaluate_condition('state:s1', 'demo')[0]
            assert not evaluate_condition('state:loop', 'demo')[0]
            print('PASS [e]')
            with patch('app.models.character_template.get_template', return_value=template):
                rule = rules.rules_for_character('demo', profile=profile,
                         config={'energy_baseline': 70, 'energy_hourly': -4})['energy']
                assert rule['baseline'] == 70 and rule['per_hour'] == -4
            print('PASS [f]')
        assert [rules.round_half_away(x) for x in (.5, -.5, 1.49, -2.5, .4)] == [1, -1, 1, -3, 0]
        print('PASS [g]')
        assert rules.get_setting('chat_cap_per_hour') == 15
        assert rules.save_setting('chat_cap_per_hour', 8)
        assert rules.get_setting('chat_cap_per_hour') == 8
        assert rules.settings_with_source()['chat_cap_per_hour']['source'] == 'world'
        assert rules.delete_setting('chat_cap_per_hour')
        assert rules.get_setting('chat_cap_per_hour') == 15
        assert rules.settings_with_source()['chat_cap_per_hour']['source'] == 'shared'
        try:
            rules.save_setting('nope', 1)
        except ValueError:
            pass
        else:
            raise AssertionError('unknown setting accepted')
        print('PASS [h]')
        print('All stat rules checks passed (8/8).')


if __name__ == '__main__':
    main()
