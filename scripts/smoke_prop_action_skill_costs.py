"""PropAction admission costs are once per request; replay and cancel stay free.

Usage: /home/dev/projekte/anima-verse/.venv/bin/python scripts/smoke_prop_action_skill_costs.py
Hand-derived: 10 fuel - 5 for one new execution = 5, even after replay.
At zero fuel the same execution can still be replayed and cancelled.
Engine admission is mocked; this checks the real plugin through both gate adapters.
"""
import json
import tempfile
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
from smoke_stat_skill_gate import setup


def main():
    with tempfile.TemporaryDirectory() as tmp:
        from app.core import paths
        paths.init(tmp)
        sm = setup(tmp)  # Also initializes the private instance before DB imports.
        from app.core import skill_gate, stat_rules, prop_action_engine as engine
        from app.models import character
        from plugins.set_pose.skill_prop_action import PropActionSkill
        skill = PropActionSkill({}, SimpleNamespace())
        skill.name = 'PropAction'
        sm.skills.append(skill)
        stat_rules.save_setting('skill_costs', {'prop_action': {'fuel': 5}})
        request = dict(operation='request', action_id='sit', revision='v1',
                       target={}, request_id='nonce')
        result = dict(status='approaching', execution_id='execution', reason='')
        admitted = []
        def admit(*args, **kwargs):
            created = not admitted
            admitted.append(True)
            return dict(result), created
        with patch('app.core.dependencies.get_skill_manager', return_value=sm), patch(
                'app.models.rules.load_rules', return_value=[]), patch.object(
                engine, 'request_with_creation', side_effect=admit), patch.object(
                engine.store, 'by_request', side_effect=lambda actor, nonce: result if admitted and nonce == 'nonce' else None), patch.object(
                engine.store, 'get', side_effect=lambda eid: dict(result)), patch.object(
                engine, '_result', side_effect=lambda run: dict(run)), patch.object(
                engine, 'cancel', return_value=dict(status='cancelled', execution_id='execution', reason='')):
            tool = skill.as_tool('Tester')
            def call(payload, adapter='tool'):
                if adapter == 'tool':
                    return skill_gate.run_tool('Tester', 'PropAction', lambda: tool.func(json.dumps(payload)))
                return skill_gate.run_gated('Tester', 'prop_action', lambda: tool.func(json.dumps(payload)))
            assert json.loads(call(request)) == result
            assert character.get_character_profile('Tester')['status_effects']['fuel'] == 5
            assert json.loads(call(request, 'gated')) == result
            assert character.get_character_profile('Tester')['status_effects']['fuel'] == 5, 'replay charged twice'
            character.adjust_status_effects('Tester', {'fuel': -5})
            assert json.loads(call(request)) == result, 'exhaustion blocked replay'
            refused = json.loads(call(dict(request, request_id='new')))
            assert refused['status'] == 'refused', 'new request bypassed exhaustion'
            assert len(admitted) == 3, 'exhausted new request reached admission'
            assert json.loads(call(dict(operation='cancel', execution_id='execution')))['status'] == 'cancelled'
            assert character.get_character_profile('Tester')['status_effects']['fuel'] == 0
            # Admission can insert a run whose immediate start then fails.
            for status in ('failed', 'cancelled'):
                character.adjust_status_effects('Tester', {'fuel': 10})
                admitted.clear()
                result['status'] = status
                assert json.loads(call(request))['status'] == status
                assert character.get_character_profile('Tester')['status_effects']['fuel'] == 10, status
                character.adjust_status_effects('Tester', {'fuel': -10})
            # Invitation listeners execute when the outer nonce guard exits.
            @contextmanager
            def deferred_guard(*args):
                yield
                result['status'] = 'running'
            character.adjust_status_effects('Tester', {'fuel': 10})
            admitted.clear()
            result['status'] = 'awaiting_consent'
            with patch.object(engine, 'request_guard', side_effect=deferred_guard):
                assert json.loads(call(request))['status'] == 'running', 'stale deferred invitation result'
            assert character.get_character_profile('Tester')['status_effects']['fuel'] == 5
            # Simultaneous callers share the real nonce guard across admission
            # and charging; mock only DB/stat work to keep thread storage local.
            admitted.clear()
            result['status'] = 'approaching'
            start = Barrier(2)
            charges = []
            def concurrent_call(_):
                start.wait(timeout=5)
                return json.loads(call(request))
            with patch.object(skill_gate, 'blocked_reason', return_value=''), patch.object(
                    skill_gate, 'charge', side_effect=lambda *args: charges.append(args)):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    answers = list(pool.map(concurrent_call, range(2)))
            assert answers == [result, result]
            assert len(charges) == 1, 'concurrent replay charged twice'
        print('PASS PropAction gate: once-only request cost, exhausted replay and cancellation')


if __name__ == '__main__':
    main()
