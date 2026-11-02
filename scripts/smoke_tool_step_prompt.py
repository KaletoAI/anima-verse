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
[11] The stable system carries the character language and explicitly permits
consent calls and shared-trip proposals.
[10] Respond queue submission equals the builder, partner words are context only,
TalkTo needs a third person, and tool mood/pose markers are ignored.
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
             patch('app.models.character.get_character_language_instruction', return_value='Always respond in German.'), \
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
            assert '<tool name="ToolName">{"key": "value"}</tool>' in first.system
            assert 'The example shows syntax only.' in first.system
            assert 'Kommst du mit?' not in first.system and 'TalkTo' not in first.system
            assert 'Always respond in German.' in first.system
            assert 'Every message, caption or free-text tool argument' in first.system
            assert 'Agreement needs no tool unless an open question' in first.system
            assert 'an offered verb answers exactly that proposal' in first.system
            assert 'Proposing to go somewhere together is an action.' in first.system
            print('[1] PASS stable system, language, consent rule and syntax-only example')
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
                natural = build(fmt=fmt).system
                assert '<tool name=' not in natural
                prefix = 'Use ToolName for:' if fmt == 'natural_en' else 'Ich nutze ToolName für:'
                assert prefix + ' {"key": "value"}' in natural
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
            from app.core import chat_engine
            from types import SimpleNamespace
            from plugins.talk_to.skill import TalkToSkill
            talk = object.__new__(TalkToSkill)
            talk.name, talk.brief = 'TalkTo', 'Speak to a third person; input: full name, words.'
            pose = Skill('SetActivity')
            pose.POSE_SETTER = True
            skills.update(TalkTo=talk, SetActivity=pose)
            manager.tool_names_with_flag = lambda flag: (
                frozenset({"TalkTo"}) if flag == "DELIVERS_SPEECH" else frozenset())
            words, reply = 'Please change your clothes.', 'Ada smiles. **I feel froh**'
            for present in [('Ylva Nordwind',), ('Ylva Nordwind', 'Ben Example')]:
                expected = build_tool_step_prompt('Ada Example', mode='respond',
                    rp_response=chat_engine.clean_response(reply), user_input=words, tools=[talk, pose],
                    facts=TurnFacts('Ada Example', 'respond', present, 'Ylva Nordwind'), tool_format='tag')
                assert 'SetActivity' not in expected.offered
                assert ('TalkTo' in expected.offered) == (len(present) == 2)
                assert words not in expected.system and expected.user.count(words) == 1
                assert 'Other person’s words (context only):\n' + words in expected.user
                ctx = dict(llm=object(), system_content='RP', moment_content='', messages=[], room_mode=True,
                    mode='rp_first', tool_format='tag', tools_dict={'TalkTo': lambda raw: ''},
                    tool_llm=object(), agent_tools=[talk, pose], agent_config={},
                    speaker='Ylva Nordwind', medium='in_person', full_chat_history=[])
                calls, processed = [], []
                def submit(**kw):
                    calls.append(kw)
                    return SimpleNamespace(content=reply if len(calls) == 1 else
                        '**I feel tired**\n**I do sitting**\n[INTENT_DONE: p1]\n'
                        '**I am at Cafe**\n[EVENT_RESOLVED: e1]')
                class InlineThread:
                    def __init__(self, target, **kw): self.target = target
                    def start(self): self.target()
                with patch.object(chat_engine, 'build_chat_context', return_value=ctx), \
                     patch('app.core.streaming.tool_step_presence', return_value=present), \
                     patch('app.core.llm_queue.get_llm_queue', return_value=SimpleNamespace(submit=submit)), \
                     patch('app.core.memory_situational.build_situational_block', return_value=''), \
                     patch('threading.Thread', InlineThread), \
                     patch.object(chat_engine, 'post_process_response', side_effect=lambda *a, **k: processed.append((a, k))):
                    chat_engine.run_chat_turn('demo', 'Ada Example', 'Ylva Nordwind', words, post_process=True)
                assert len(calls) == 2, calls
                assert calls[1]['task_type'] == 'intent'
                assert calls[1]['messages_or_prompt'] == [dict(role='system', content=expected.system), dict(role='user', content=expected.user)]
                assert processed and 'tired' not in str(processed) and '**I do sitting**' not in str(processed)
                assert all(marker in str(processed) for marker in (
                    '[INTENT_DONE: p1]', '**I am at Cafe**', '[EVENT_RESOLVED: e1]'))
            print('[10] PASS respond queue, partner context, availability and markers')
            print('RESPOND SAMPLE SYSTEM\n' + expected.system + '\nRESPOND SAMPLE USER\n' + expected.user)
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
