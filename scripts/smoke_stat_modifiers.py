"""Rule modifiers affect baked game-time travel and generic consumers.

Usage: ./.venv/bin/python scripts/smoke_stat_modifiers.py
Hand-derived: no rule = 1; 20<30 gives .7; .7*.5=.35. The identical
100-metre route takes base/.7 game seconds, including for a leader whose
follower has .7. Discovery 50*.6=30; a 35m boundary lies outside 50*.6.
Spell 80*1.3=104 clamps to 100. Ten equal agents get 100/1000 picks each;
one at .5 gets .5/9.5*1000 ~=53 (within 10% of half its previous share).
Fractional tickets are deterministic across rounds, including weights .1.
"""
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from collections import Counter
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix='modifiers-') as tmp:
        os.environ['STORAGE_DIR'] = os.environ['INSTANCE_DIR'] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core import config, db
        config_path = Path(tmp) / 'config.json'
        config_path.write_text('{}')
        config.load(config_path)
        db.init_schema()
        config._CONFIG.setdefault('game', {}).update(travel_speed_m_s=1, discovery_range_m=50)
        config._CONFIG.setdefault('inventory', {})['discovery_stat'] = 'sight' 
        from app.core import modifiers, travel_engine, party_engine, agent_loop, discovery, spell_engine
        from app.models import rules, character as ch, inventory
        from app.models.world import add_location, update_location_position, _load_world_data, _save_world_data
        from app.core.timeutils import set_game_factor, set_game_time
        from app.core.game_time import GameTime
        set_game_factor(0)
        set_game_time(GameTime.parse('Y0001-D001T12:00:00'))
        shipped = {r['id']: r for r in rules.load_rules()}
        assert shipped['default_tired_legs']['modify'] == {'quantity': 'travel_speed', 'factor': .7}
        assert shipped['default_distracted_eyes']['modify'] == {'quantity': 'discovery', 'factor': .6}
        assert shipped['default_alert_eyes']['modify'] == {'quantity': 'discovery', 'factor': 1.3}
        disabled = [{'id': rid, 'type': 'info'} for rid in shipped]
        def save(entries):
            rules.save_rules(disabled + entries)
        def modify(qid, value, condition='', character='', rid='test'):
            return {'id': rid, 'name': 'Test', 'type': 'modify', 'condition': condition,
                    'character': character, 'modify': {'quantity': qid, 'factor': value}}
        a = add_location(name='Origin', description='fixture')['id']
        b = add_location(name='Goal', description='fixture')['id']
        update_location_position(a, 0, 0)
        update_location_position(b, 100, 0)
        data = _load_world_data()
        for loc in data['locations']:
            loc['map3d'] = {'boundary': [[-5,-5],[-5,5],[5,5],[5,-5]],
                            'boundary_openings': [{'edge': i, 'at': .5, 'width_m': 4,
                                                   'type': 'passage'} for i in range(4)]}
        _save_world_data(data)
        for name in ('Walker', 'Leader', 'Follower'):
            ch.save_character_profile(name, {'status_effects': {'stamina': 20, 'attention': 20, 'sight': 50}}, create_new=True)
            ch.save_character_current_location(name, a)
            ch.set_character_pos(name, 0, 0)
            ch.set_known_locations(name, [a, b])
        save([])
        assert modifiers.factor('Walker', 'travel_speed') == 1
        assert {q['id'] for q in modifiers.quantities()} == {'travel_speed', 'discovery', 'spell_success', 'thought_frequency'}
        from app.routes.rules import quantities_route
        assert quantities_route() == modifiers.quantities()
        modifiers.register_quantity('fixture', 'Fixture', 'Package quantity')
        assert modifiers.quantities()[-1] == {'id': 'fixture', 'label': 'Fixture', 'description': 'Package quantity'}
        base, reason = travel_engine.start_journey('Walker', b)
        assert base, reason
        seconds = base['waypoints'][-1][2]
        travel_engine.cancel_journey('Walker')
        tired = modify('travel_speed', .7, 'stamina<30')
        save([tired])
        with patch('app.models.rules.load_rules', wraps=rules.load_rules) as loaded:
            assert modifiers.factor('Walker', 'travel_speed') == .7
            assert loaded.call_count == 1
        slowed, reason = travel_engine.start_journey('Walker', b)
        assert slowed, reason
        assert math.isclose(slowed['waypoints'][-1][2], seconds / .7)
        assert slowed['speed_m_s'] == .7
        assert [p[:2] for p in base['waypoints']] == [p[:2] for p in slowed['waypoints']]
        travel_engine.cancel_journey('Walker')
        point, reason = travel_engine.start_journey_to_point('Walker', 100, 0)
        assert point and point['speed_m_s'] == .7, reason
        save([tired, modify('travel_speed', .5, rid='second')])
        assert math.isclose(modifiers.factor('Walker', 'travel_speed'), .35)
        save([modify('travel_speed', .7, character='Follower')])
        assert party_engine.add_to_party('Leader', 'Follower')
        grouped, reason = travel_engine.start_journey('Leader', b)
        assert grouped and math.isclose(grouped['waypoints'][-1][2], seconds / .7), reason
        assert travel_engine.get_journey('Follower') is None
        for base_speed, expected in ((.1, .1), (20, 20)):
            config._CONFIG['game']['travel_speed_m_s'] = base_speed
            save([modify('travel_speed', .1 if base_speed == .1 else 5)])
            _, speed = travel_engine._bake_route((0, 0), (100, 0), None, character_name='Walker')
            assert speed == expected
        config._CONFIG['game']['travel_speed_m_s'] = 1
        save([modify('discovery', .6, 'attention<25')])
        assert inventory.discovery_value('Walker') == 30
        with patch('app.core.discovery.locations_within', return_value=[]) as within:
            rules.check_discover_rules('Walker')
            assert within.call_args.args[2] == 30
        ch.set_known_locations('Walker', [])
        assert b not in discovery.discover_in_range('Walker', 60, 0)
        assert b in discovery.discover_in_range('Walker', 70, 0)
        save([modify('spell_success', 1.3)])
        with patch('random.randint', return_value=100), patch('app.models.character.set_pose_intent'):
            result = spell_engine.execute_cast('Walker', 'Leader', {'name': 'Fixture', 'success_chance': 80})
        assert result['chance'] == 100 and result['success'], result
        for raw, expected in ((0, .1), (10, 5), ('bad', 1), (float('nan'), 1)):
            save([modify('fixture', raw)])
            assert modifiers.factor('Walker', 'fixture') == expected
            assert rules.get_rule('test')['modify']['factor'] == expected
        created = rules.add_rule(modify('fixture', 9))
        assert created['modify']['factor'] == 5
        assert rules.update_rule('test', {'modify': {'quantity': 'fixture', 'factor': 0}})['modify']['factor'] == .1
        save([modify('fixture', .2, character='Other')])
        assert modifiers.factor('Walker', 'fixture') == 1
        save([modify('fixture', .2, condition='stamina>30')])
        assert modifiers.factor('Walker', 'fixture') == 1
        # A value the character does not have never fires a modifier (a rule
        # condition would read the missing value as 100 and pass).
        save([modify('fixture', 1.3, condition='value_walker_lacks>10')])
        assert modifiers.factor('Walker', 'fixture') == 1
        names = ['Agent' + str(i) for i in range(10)]
        def picks():
            agent_loop._ticket_credit.clear()
            counts = Counter()
            loop = agent_loop.AgentLoop()
            for _ in range(1000):
                name = loop._pick_next_agent()
                assert name is not None
                counts[name] += 1
            return counts
        with patch('app.models.character.list_available_characters', return_value=names), \
             patch('app.models.character.get_character_config', return_value={'importance': 1}), \
             patch('app.core.agent_loop._is_agent_eligible', return_value=True), \
             patch('random.shuffle', side_effect=lambda values: None), \
             patch('app.core.agent_loop._has_hot_lane', return_value=False), \
             patch.object(agent_loop.AgentLoop, '_on_rut_rest', return_value=False):
            save([])
            baseline = picks()[names[0]]
            save([modify('thought_frequency', .5, character=names[0])])
            count = picks()[names[0]]
            assert abs(count - baseline * .5) <= baseline * .5 * .1, (baseline, count)
            save([modify('thought_frequency', .1)])
            agent_loop._ticket_credit.clear()
            rounds = [agent_loop._build_round_tickets() for _ in range(10)]
            assert Counter(n for row in rounds for n in row) == Counter({n: 1 for n in names})
        print('PASS stat modifiers: registry, rules, travel, party, discovery, spell, fractional tickets')


if __name__ == '__main__':
    main()
