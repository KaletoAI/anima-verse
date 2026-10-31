"""Tool logging smoke. Usage: ./.venv/bin/python scripts/smoke_tool_call_log.py

Hand-derived: TalkTo has 2 ok + 1 error: total 3, fail rate .333.
Move has blocked + exception: total 2, fail rate 1. Filtering status
leaves these summaries intact. Nested execution writes exactly one row.
Input/result limits are 2000/1000 characters respectively.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory() as directory:
        os.environ['STORAGE_DIR'] = directory
        os.environ['INSTANCE_DIR'] = directory
        from app.core import paths
        paths.init(directory)
        from app.core import tool_call_log as log, skill_gate as gate
        from app.core.turn_trace import begin_trace, set_trace
        log.LOG_FILE = Path(directory) / 'tools.jsonl'
        def rows():
            return [json.loads(line) for line in log.LOG_FILE.read_text().splitlines()]
        for value in ('Error: x', 'Fehler: y', '{"success": false}',
                      {'ok': False}, {'status': 'refused'}):
            assert log.classify(value) == 'error', value
        for value in ('Moved to kitchen', "Character 'Zed' not found"):
            # Known gap: is_error_result does not recognize missing characters.
            assert log.classify(value) == 'ok'
        log.record(character='demo', tool='demo', status='ok',
                   tool_input='x' * 2500, result='y' * 1500)
        assert len(rows()[-1]['input']) == 2000
        assert len(rows()[-1]['result']) == 1000
        log.record(character='demo', tool='demo', status='ok', tool_input={'a': 'é'})
        assert json.loads(rows()[-1]['input']) == {'a': 'é'}
        valid = log.LOG_FILE
        log.LOG_FILE = valid / 'invalid'
        log.record(character='demo', tool='demo', status='ok')
        log.LOG_FILE = valid
        class Unprintable:
            def __str__(self):
                raise ValueError('demo')
        log.record(character='demo', tool='demo', status='ok', tool_input=Unprintable())
        circular = []
        circular.append(circular)
        log.record(character='demo', tool='demo', status='ok', tool_input=circular)
        assert log.classify(Unprintable()) == 'ok'
        manager = SimpleNamespace(get_skill=lambda _: SimpleNamespace(name='Demo'),
                                  get_skill_by_name=lambda _: None)
        with patch('app.core.dependencies.get_skill_manager', return_value=manager), \
             patch.object(gate, 'blocked_reason', return_value=''), \
             patch.object(gate, 'charge'):
            for value, expected in (('done', 'ok'), ('Error: no', 'error')):
                before = len(rows())
                assert gate.run_gated('demo', 'demo', lambda: value) == value
                assert len(rows()) == before + 1 and rows()[-1]['status'] == expected
            with patch.object(gate, 'blocked_reason', return_value='no'):
                before = len(rows())
                def forbidden():
                    raise AssertionError('blocked call executed')
                assert gate.run_gated('demo', 'demo', forbidden) == 'Error: no'
                assert len(rows()) == before + 1 and rows()[-1]['status'] == 'blocked'
            before = len(rows())
            def raising():
                raise ValueError('demo')
            try:
                gate.run_gated('demo', 'demo', raising)
            except ValueError:
                pass
            else:
                raise AssertionError('exception swallowed')
            assert len(rows()) == before + 1 and rows()[-1]['status'] == 'exception'
            before = len(rows())
            gate.run_gated('demo', 'demo', lambda: gate.run_gated('demo', 'demo', lambda: 'ok'))
            assert len(rows()) == before + 1
            before = len(rows())
            gate.run_tool('demo', 'Unknown', lambda: gate.run_tool('demo', 'Unknown', lambda: 'ok'))
            assert len(rows()) == before + 1
            before = len(rows())
            gate.run_gated('demo', 'prop_action', lambda: gate.run_gated(
                'demo', 'prop_action', lambda: {'status': 'refused'}),
                tool_input={'demo': True}, source='npc_action', tool_name='PropAction')
            row = rows()[-1]
            assert len(rows()) == before + 1 and row['status'] == 'error'
            assert row['tool'] == 'PropAction' and row['source'] == 'npc_action'
            assert json.loads(row['input']) == {'demo': True}
            assert isinstance(row['duration_ms'], int)
        trace = begin_trace('thought', 'demo')
        log.record(character='demo', tool='demo', status='ok')
        assert rows()[-1]['trace_id'] == trace['id'] and rows()[-1]['source'] == 'thought'
        log.record(character='demo', tool='demo', status='ok', source='intent')
        assert rows()[-1]['source'] == 'intent'
        set_trace(None)
        from app.routes import logs
        data = [{'tool': tool, 'status': status, 'character': 'Alex', 'source': 'thought'}
                for tool, status in (('TalkTo', 'ok'), ('TalkTo', 'ok'), ('TalkTo', 'error'),
                                     ('Move', 'blocked'), ('Move', 'exception'))]
        valid.write_text('\n'.join(json.dumps(row) for row in data) + '\ninvalid\n[]\n')
        def query(**kwargs):
            args = dict(limit=100, offset=0, character='', tool='', status='', source='', search='')
            args.update(kwargs)
            return logs.tool_log_data(**args)
        result = query()
        assert result['total'] == 5 and result['entries'][0]['status'] == 'exception'
        assert result['summary'] == [
            {'tool': 'Move', 'total': 2, 'by_status': {'blocked': 1, 'exception': 1}, 'fail_rate': 1.0},
            {'tool': 'TalkTo', 'total': 3, 'by_status': {'ok': 2, 'error': 1}, 'fail_rate': .333}]
        assert query(status='error')['total'] == 1
        assert query(tool='TalkTo', status='error')['summary'] == result['summary']
        assert query(character='Zed')['total'] == 0
        assert query(source='intent')['summary'] == []
        assert query(search='blocked')['summary'][0]['total'] == 1
        assert query(offset=1, limit=2)['entries'] == list(reversed(data))[1:3]
        from app.core import npc_actions
        from contextlib import ExitStack
        # No pre-LLM rejection is a turn; every post-LLM discard is one row.
        with ExitStack() as stack:
            available = stack.enter_context(patch.object(npc_actions, 'action_available', return_value=True))
            stack.enter_context(patch.object(npc_actions, 'prompt_vars', return_value={
                'home': True, 'current_room_id': 'demo'}))
            stack.enter_context(patch.object(npc_actions, 'game_time', return_value=None))
            stack.enter_context(patch('app.models.character.get_character_profile', return_value={}))
            stack.enter_context(patch('app.core.prompt_templates.render_task', return_value=('', '')))
            answer = stack.enter_context(patch.object(npc_actions, '_ask', return_value=None))
            home = stack.enter_context(patch.object(npc_actions, '_apply_home_answer', return_value=None))
            # The query fixture included intentionally malformed lines; start a clean writer file.
            valid.write_text('')
            assert npc_actions.run_action_for('demo', llm=lambda: None) is None
            assert len(rows()) == 1 and rows()[-1]['result'] == 'no usable answer'
            answer.return_value = {}
            assert npc_actions.run_action_for('demo', llm=lambda: None) is None
            assert len(rows()) == 2 and rows()[-1]['result'] == 'home answer unusable'
            home.return_value = {'name': 'demo', 'moved': False}
            assert npc_actions.run_action_for('demo', llm=lambda: None) == home.return_value
            assert len(rows()) == 3 and rows()[-1]['status'] == 'ok'
            available.return_value = False
            assert npc_actions.run_action_for('demo', llm=lambda: None) is None
            assert len(rows()) == 3
        assert 'prune_jsonl_log(LOG_DIR / "tool_calls.jsonl", days)' in Path('app/utils/llm_logger.py').read_text()
    print('PASS: tool call logging, gates, trace, viewer, retention')


if __name__ == '__main__':
    main()
