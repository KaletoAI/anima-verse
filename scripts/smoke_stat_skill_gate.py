"""Verify skill rules and execution backstops in an isolated world.

Usage: ./.venv/bin/python scripts/smoke_stat_skill_gate.py
Hand-derived: fuel 10 < 15 blocks FakeMove; 20 does not. A matching
state blocks independently. Disabled buttons retain their capability ID.
A refused execution increments no counter, including intent dispatch.
"""
import asyncio
import ast
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def setup(tmp):
    os.environ['STORAGE_DIR'] = os.environ['INSTANCE_DIR'] = tmp
    from app.core import paths
    paths.init(tmp)
    paths.init_instance(tmp)
    from app.core.db import init_schema, transaction
    init_schema()
    from app.skills.base import BaseSkill
    from app.skills.skill_manager import SkillManager
    class FakeSkill(BaseSkill):
        PLAYER_ACTION = 'travel'
        INTENT_TYPES = ('fake_move',)
        def __init__(self, sid, name):
            super().__init__({})
            self.SKILL_ID, self.name = sid, name
            self.calls = 0
        def execute(self, raw=''):
            self.calls += 1
            return 'Done'
        def handle_intent(self, kind, payload):
            self.calls += 1
            return {'success': True}
    sm = SkillManager()
    sm.skills = [FakeSkill('fake_move', 'FakeMove'), FakeSkill('fake_photo', 'FakePhoto')]
    sm.skills[1].PLAYER_ACTION = 'scene_photo'
    with transaction() as conn:
        conn.execute('INSERT INTO characters (name, template, profile_json, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
                     ('Tester', 'test', json.dumps({'status_effects': {'fuel': 10}}), '{}', '', ''))
    return sm


def main():
    with tempfile.TemporaryDirectory() as tmp:
        sm = setup(tmp)
        from app.core import skill_gate
        from app.core.stat_sources import bind_stat_sources
        from app.models import character, rules
        from app.routes import play
        rule = {'id': 'fake_block', 'name': 'Test gate', 'type': 'block',
                'target': {'scope': 'skill', 'skills': ['fake_move']},
                'condition': 'fuel<15', 'message': 'Rest first'}
        with patch('app.core.dependencies.get_skill_manager', return_value=sm), patch(
                'app.models.character.get_character_skill_config', return_value={'enabled': True}), patch(
                'app.models.rules.load_rules', return_value=[rule]):
            assert 'FakeMove' not in [t.name for t in sm.get_agent_tools('Tester')]
            assert skill_gate.blocked_reason('Tester', 'fake_move') == 'Rest first'
            assert 'fake_move' in play._player_capabilities('Tester')
            assert skill_gate.blocked_skills('Tester', play._player_capabilities('Tester')) == {'fake_move': 'Rest first'}
            payload = play._player_skill_payload('Tester')
            assert payload['capability_blocks'] == {'fake_move': 'Rest first'}
            assert payload['capability_actions']['travel'] == 'fake_move'
            from app.routes.rules import skill_options_route
            assert {'id': 'fake_move', 'name': 'FakeMove'} in skill_options_route()
            assert '- Unavailable right now: FakeMove — Rest first' in skill_gate.prompt_lines('Tester')
            assert skill_gate.run_gated('Tester', 'fake_move', sm.skills[0].execute) == 'Error: Rest first'
            from app.core.intent_engine import _dispatch_intent
            result = _dispatch_intent({'intent_type': 'fake_move', 'agent_name': 'Tester'})
            assert not result['success'] and 'Rest first' in result['error'], result
            assert sm.skills[0].calls == 0
            # Exercise the real nested context wrappers with synthetic context.
            for filename, factory in (('chat_engine.py', '_make_ctx_wrapper'),
                                      ('thoughts.py', '_make_ctx_wrapper'),
                                      ('act_engine.py', '_make_wrapper')):
                tree = ast.parse((Path(__file__).resolve().parents[1] / 'app/core' / filename).read_text())
                node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == factory)
                context = dict(t=sm.skills[0].as_tool(), character_name='Tester', owner_id='',
                               _tool_initiator='', actor='Tester', sid='fake_move', json=json,
                               _json=json, _coerce_to_dict=lambda raw: {},
                               bind_stat_sources=bind_stat_sources, stat_collector=None)
                exec(compile(ast.Module(body=[node], type_ignores=[]), filename, 'exec'), context)
                wrapper = context[factory](sm.skills[0].execute)
                assert wrapper('{}') == 'Error: Rest first', filename
            # Even a hidden tool that the model names receives the rule reason.
            from app.core.streaming import StreamingAgent
            stream = StreamingAgent(llm=None, tool_format='tag', tools_dict={}, agent_name='Tester')
            async def blocked_stream():
                results = []
                events = [event async for event in stream._execute_tools([('FakeMove', '')], results, [])]
                assert results == [('FakeMove', 'Error: Rest first')]
                assert events[0].result == 'Error: Rest first'
            asyncio.run(blocked_stream())
            async def inline_thread(func, *args, **kwargs):
                return func(*args, **kwargs)
            # The thought queue executor delegates to the same context wrapper.
            thought_tree = ast.parse((Path(__file__).resolve().parents[1] / 'app/core/thoughts.py').read_text())
            queued = next(n for n in ast.walk(thought_tree)
                          if isinstance(n, ast.AsyncFunctionDef) and n.name == '_tool_executor_queued')
            async def register_active(*args, **kwargs):
                return 'registered'
            context = dict(reply_only_to='', _tool_executions=[], _thought_state={'task_id': ''},
                           tools_dict={'FakeMove': wrapper}, _llm_queue=SimpleNamespace(
                               register_chat_active_async=register_active),
                           _set_thought_task=lambda tid: None, character_name='Tester',
                           _llm_inst=None, _thought_label='', asyncio=asyncio)
            exec(compile(ast.Module(body=[queued], type_ignores=[]), 'thoughts.py', 'exec'), context)
            with patch('asyncio.to_thread', side_effect=inline_thread):
                assert asyncio.run(context['_tool_executor_queued']('FakeMove', '{}')) == 'Error: Rest first'
                # A queued deferred tool must recheck a rule that changes later.
                async def delayed_block():
                    character.adjust_status_effects('Tester', {'fuel': 10})
                    stream.tools_dict = {'FakeMove': sm.skills[0].execute}
                    stream.deferred_tools = {'FakeMove'}
                    results, pending = [], []
                    _ = [event async for event in stream._execute_tools([('FakeMove', '')], results, pending)]
                    assert pending == [('FakeMove', '')] and not results
                    character.adjust_status_effects('Tester', {'fuel': -10})
                    with patch('app.core.streaming.report_deferred_failure', return_value=True):
                        events = [event async for event in stream._run_deferred_tools('Narrative', pending)]
                    assert any(getattr(event, 'result', '') == 'Error: Rest first' for event in events)
                asyncio.run(delayed_block())
            assert sm.skills[0].calls == 0
            # The scheduler's direct executor must apply the same backstop.
            from app.scheduler.scheduler_manager import SchedulerManager
            with patch.object(sm, 'get_skill', return_value=sm.skills[0]):
                result = SchedulerManager.__new__(SchedulerManager)._action_extract_files({}, 'Tester')
                assert not result['success'] and result['error'] == 'Error: Rest first'
            assert sm.skills[0].calls == 0
            assert rules.check_access('Tester', '') == (True, '')
            class Request:
                async def json(self):
                    return {'target_id': 'somewhere'}
            from fastapi import HTTPException

            def refusal(call):
                # The player routes refuse like their other 403s: detail
                # carries reason + message (the client reads detail.message).
                try:
                    asyncio.run(call)
                except HTTPException as exc:
                    assert exc.status_code == 403, exc.status_code
                    return exc.detail
                raise AssertionError('route did not refuse')
            with patch('app.models.account.get_active_character', return_value='Tester'):
                assert refusal(play.play_travel(Request(), user={}))['reason'] == 'skill_blocked'
                rule['target']['skills'].append('fake_photo')
                assert refusal(play.play_scene_photo_prepare(user={}))['message'] == 'Rest first'
                assert refusal(play.play_scene_photo(Request(), user={}))['message'] == 'Rest first'
                rule['target']['skills'].remove('fake_photo')
            character.adjust_status_effects('Tester', {'fuel': 10})
            assert 'FakeMove' in [t.name for t in sm.get_agent_tools('Tester')]
            rule['condition'] = 'state:fake_state'
            with patch('app.core.prompt_filters.is_state_active', return_value=True):
                assert skill_gate.blocked_reason('Tester', 'fake_move') == 'Rest first'
        from app.core.skill_drop_migration import migrate_skill_drop_blocks_once
        from app.core.db import transaction, get_connection
        with transaction() as conn:
            conn.execute("INSERT INTO prompt_filters (id, condition, drop_blocks) VALUES (?, '', ?)",
                         ('old_state', json.dumps(['skill:fake_move', 'effects_block'])))
        assert migrate_skill_drop_blocks_once() == 1
        assert migrate_skill_drop_blocks_once() == 0
        assert json.loads(get_connection().execute(
            "SELECT drop_blocks FROM prompt_filters WHERE id='old_state'").fetchone()[0]) == ['effects_block']
        root = Path(__file__).resolve().parents[1]
        for filename in ('app/core/prompt_filters.py', 'app/routes/admin_settings.py', 'app/core/thought_context.py'):
            source = (root / filename).read_text()
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, (ast.Name, ast.FunctionDef)):
                    identifier = node.id if isinstance(node, ast.Name) else node.name
                    assert not identifier.startswith('_skill_block'), identifier
                    assert not (identifier.startswith('skill_') and identifier.endswith('_drops')), identifier
        print('PASS skill gate [a-g]')


if __name__ == '__main__':
    main()
