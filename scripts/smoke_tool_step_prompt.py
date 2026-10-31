#!/usr/bin/env python3
"""Check the small tool-step prompt without a server or a real world.

Usage: ./.venv/bin/python scripts/smoke_tool_step_prompt.py

Hand-derived expectations from Task 3: [1] changing prose, people and plans
changes no system bytes, even with twelve 200-character briefs. [2] Subtract
prose, twelve '- Name: brief' lines, menu and plans: scaffold <=1500 chars;
system <=2500. [3] No pose/mood/event or legacy prompt sections. [4] Only an
offered outfit verb supplies Red Mieder. [5] Exact supplied full names or
'Nobody else is here.' [6] Only an empty travel refusal permits the place
marker. [7] Constrained renders contain neither plan grammar nor plan data.
[8] A world override replaces the turn template. [9] rp_first discards tool
mood/pose markers and sends the supplied system/user prompt unchanged.
Movement menus include all
known place names but rooms only at the current place. All storage is temporary.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix='tool-step-') as tmp:
        from app.core import paths
        paths.init(Path(tmp))
        from app.core import db, streaming, template_overrides
        db.init_schema()
        from app.skills.base import TurnFacts
        from app.core.tool_step_prompt import build_tool_step_prompt
        from plugins.movement.skill_set_location import SetLocationSkill

        class Skill:
            POSE_SETTER = False

            def __init__(self, name):
                self.name = name
                self.brief = 'b' * 200

            def available_now(self, facts):
                return 'unavailable' if self.name == 'Hidden' else None

            def decision_menu(self, character):
                return ['Red Mieder (top)'] if self.name == 'ChangeOutfit' else []

        tools = [Skill('ChangeOutfit')] + [Skill(f'Tool{i}') for i in range(11)]
        skills = {s.name: s for s in tools}
        manager = Mock(get_skill_by_name=lambda n: skills.get(n),
                       tool_names_with_flag=lambda flag: frozenset())
        plans = 'p1 | Buy bread'
        prose = 'Ich ziehe mein rotes Mieder an.'
        with patch('app.core.dependencies.get_skill_manager', return_value=manager), \
             patch('app.core.flag_lifecycle.inactive_clearing_tools', return_value=set()), \
             patch('app.routes.chat._marker_travel_refusal', return_value='has_movement_verb') as refusal, \
             patch('app.models.intents.build_open_intents_brief', return_value=plans) as plan_mock:
            def build(present=(), text=prose, constrained=False, offered=None, mode='thought', fmt='tag'):
                return build_tool_step_prompt('Ada Example', mode=mode, rp_response=text,
                    user_input='', tools=tools if offered is None else offered,
                    facts=TurnFacts('Ada Example', mode, present), constrained=constrained,
                    tool_format=fmt)

            first = build()
            plan_mock.return_value = 'p2 | Visit the park'
            second = build(('Ylva Nordwind',), 'Anderer Text')
            assert first.system == second.system
            assert prose not in first.system and 'Tool0' not in first.system
            assert first.offered == [s.name for s in tools] and first.hidden == {}
            print('[1] PASS stable system')
            plan_mock.return_value = plans
            menu = streaming.decision_menu_note('Ada Example', skills, indent='')
            tool_lines = [f'- {s.name}: {s.brief}' for s in tools]
            scaffold = len(first.user) - len(prose) - sum(map(len, tool_lines)) - len(menu) - len(plans)
            assert scaffold <= 1500, scaffold
            assert len(first.system) <= 2500, len(first.system)
            print(f'[2] PASS budget (system={len(first.system)}, scaffold={scaffold})')
            for banned in ('**I feel', '**I do', 'EVENT_RESOLVED', 'Persoenlichkeit',
                           'Available tools:', '[input]', 'WHEN NOT TO USE'):
                assert banned not in first.system + first.user, banned
            print('[3] PASS excluded sections')
            assert 'Red Mieder' in first.user
            assert 'Red Mieder' not in build(offered=tools[1:]).user
            hidden = build(offered=[Skill('Hidden')])
            assert hidden.offered == [] and hidden.hidden == {'Hidden': 'unavailable'}
            print('[4] PASS offered menus and filtering')
            assert 'Ylva Nordwind' in second.user and 'Nobody else is here.' in first.user
            print('[5] PASS exact presence')
            assert '**I am at' not in first.user
            refusal.return_value = ''
            with patch('app.models.world.list_locations_for_character',
                       return_value=[{'name': 'Cafe'}, {'name': 'Mondscheinsee'}]):
                marker_user = build().user
            assert '**I am at' in marker_user
            assert '- Cafe\n- Mondscheinsee' in marker_user, marker_user
            print('[6] PASS place marker gate')
            constrained = build(constrained=True)
            assert '[INTENT' not in constrained.system + constrained.user
            assert plans not in constrained.user
            print('[7] PASS constrained plans')
            for fmt in ('natural_en', 'natural_de'):
                assert '<tool name=' not in build(fmt=fmt).system
            refusal.return_value = 'has_movement_verb'
            template_overrides.set_override('chat/tool_step_turn.md', 'OVERRIDE {{ rp_response }}', '')
            assert build().user == 'OVERRIDE ' + prose
            template_overrides.delete_override('chat/tool_step_turn.md')
            print('[8] PASS world override')
            markers = '**I feel froh**\n**I do sitting**'
            assert streaming._extract_markers(markers, '', rp_first=True) == ''
            assert streaming._extract_markers(markers, '', rp_first=False) == markers
            import asyncio

            async def verify_stream():
                agent = streaming.StreamingAgent(
                    llm=None, tool_format='tag', tools_dict={}, mode='rp_first',
                    tool_step=first)

                async def narrate(state, *args, **kwargs):
                    state.response = prose
                    if False:
                        yield

                async def decide(state, system, user):
                    assert (system, user) == (first.system, first.user)
                    state.response = markers + '\n[INTENT_DONE: p1]'
                    if False:
                        yield

                agent._stream_llm_response = narrate
                agent._invoke_tool_decision = decide
                events = [event async for event in agent._stream_rp_first('RP system', [], '')]
                extracted = [event.markers for event in events
                             if isinstance(event, streaming.ExtractionEvent)]
                assert extracted == ['[INTENT_DONE: p1]'], extracted

            asyncio.run(verify_stream())
            names = [f'Person {i} Example' for i in range(18)]
            locations = dict.fromkeys(names + ['Ada Example', 'Avatar Example', 'Elsewhere Example'], 'home')
            rooms = dict.fromkeys(locations, 'kitchen')
            rooms['Elsewhere Example'] = 'cellar'
            with patch('app.models.character.get_character_current_location',
                       side_effect=lambda name: locations.get(name, '')), \
                 patch('app.models.character.get_character_current_room',
                       side_effect=lambda name: rooms.get(name, '')), \
                 patch('app.models.character.list_available_characters',
                       return_value=names + ['Ada Example', 'Avatar Example', 'Elsewhere Example']), \
                 patch('app.models.account.get_active_character', return_value='Avatar Example'):
                assert streaming.tool_step_presence('Ada Example') == tuple(['Avatar Example'] + names)
                locations['Ada Example'] = ''
                with patch('app.models.character.get_character_pos', return_value={'x': 1, 'y': 2}), \
                     patch('app.core.perception.nearby_in_the_open',
                           return_value=['Earshot Example']) as nearby:
                    assert streaming.tool_step_presence('Ada Example') == ('Earshot Example',)
                    nearby.assert_called_once_with('Ada Example', {'x': 1, 'y': 2})
            print('[9] PASS rp_first markers, supplied prompt and room/earshot names')
            sample_tools = [Skill('ChangeOutfit'), Skill('Sleep'), Skill('SetLocation')]
            for skill, brief in zip(sample_tools, (
                'Change clothing; JSON: {"add": ["exact item name"], "remove": ["exact item name"]}.',
                'Go to sleep; input: {}.',
                'Move to a known place or current-place room; input: place, room (optional).',
            )):
                skill.brief = brief
                skills[skill.name] = skill
            sample = build(offered=sample_tools)
            print('SAMPLE SYSTEM\n' + sample.system + '\nSAMPLE USER\n' + sample.user)

        locations = [{'id': 'home', 'name': 'Home'}, {'id': 'park', 'name': 'Park'}]
        with patch('app.models.world.list_locations_for_character', return_value=locations), \
             patch('plugins.movement.skill_set_location.get_character_current_location', return_value='home'), \
             patch('plugins.movement.skill_set_location.get_location_by_id', return_value=locations[0]), \
             patch('plugins.movement.skill_set_location.get_location_rooms', return_value=[{'name': 'Kitchen'}]) as rooms:
            menu = SetLocationSkill.decision_menu(object(), 'Ada Example')
            assert menu == ['Home', 'Park', 'Home, Kitchen'], menu
            rooms.assert_called_once_with(locations[0])
        print('movement menu PASS')
    print('ALL OK')


if __name__ == '__main__':
    main()
