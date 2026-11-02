"""Verify versioned diagnosis, history and offline safety without providers.

Hand-derived from the binding spec: three repeats must retain three complete
answers (including >600 characters), reasoning, usage, duration and stop reason.
Nineteen reasoning characters estimate round(19/3.5) = 5 tokens.
Shared JSON must contain none of those answers. One missing-image case causes
zero invokes and adds zero to the score denominator. A subsequent infrastructure
failure must still save local evidence, but must not replace a quality result.
Two quality saves preserve the previous record. Legacy raw strings never become
full rescored verdicts. Captures exclude old rows and require explicit review before structural scoring.
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
from app.core.suitability_scoring import curated_cases, fixture_version, score_case
from scripts.smoke_suitability_semantics import ANSWERS
from scripts.suitability_offline_rescore import rescore


def main():
    with tempfile.TemporaryDirectory() as tmp:
        paths.init(tmp)
        paths.init_instance(Path(tmp) / "instance")
        from app.core import model_suitability as suit, model_capabilities as caps
        root = Path(tmp)
        cases = curated_cases()
        case = copy.deepcopy(cases[0])
        case['repeats'] = 3
        answer = ANSWERS[case['id']][0]
        long_answer = answer + '\n' + (' ' * 900)
        fake_client = SimpleNamespace(invoke=lambda messages: SimpleNamespace(
            content=long_answer, reasoning='synthetic reasoning', finish_reason='stop',
            usage={'completion_tokens': 5}))
        fake = SimpleNamespace(available=True, provider_name='fake', create_llm=lambda **kw: fake_client)
        caps_path = root / 'caps.json'
        outs_path = root / 'outputs.json'
        data = {'cases': [case, {'id': 'image', 'label': 'image', 'category': 'helper', 'fmt': 'text', 'task': 'image_analysis', 'repeats': 1}]}
        with patch.object(caps, '_caps_path', return_value=caps_path), patch.object(caps, '_outputs_path', return_value=outs_path), patch.object(suit, 'load_cases', return_value=data), patch('app.core.llm_router.create_llm_instance', return_value=fake):
            with patch.object(fake_client, 'invoke', wraps=fake_client.invoke) as invoke:
                events = list(suit.iter_suitability_results('fake::demo', settings={}))
                assert invoke.call_count == 3
            done = events[-1]['summary']
            assert done['saved'] and done['score'] == '1/1' and done['helper'] == '0/0'
            shared = json.loads(caps_path.read_text())
            stored = shared['suitability']['fake::demo']['tested_suitability']
            # The Speed column reads these from the saved record.
            assert stored['total_runs'] == 4 and stored['truncated_runs'] == 0
            assert stored['thinking_runs'] == 3 and stored['reasoning_tokens_median'] == 5
            assert stored['reasoning_tokens_estimated'] is True
            assert stored['checks'][0]['reasoning_tokens'] == [5, 5, 5]
            assert stored['checks'][0]['truncated_runs'] == 0
            assert 'speed_ok' in stored and 'max_turn_seconds' in stored, sorted(stored)
            assert long_answer not in caps_path.read_text() and 'synthetic reasoning' not in caps_path.read_text()
            raw = json.loads(outs_path.read_text())['outputs']['fake::demo']
            saved = raw['cases'][case['id']]
            assert len(saved) == 3
            assert all(r['content'] == long_answer and r['reasoning'] == 'synthetic reasoning' and r['finish_reason'] == 'stop' and r['usage']['completion_tokens'] == 5 and r['duration_s'] >= 0 for r in saved)
            list(suit.iter_suitability_results('fake::demo', settings={}))
            assert len(json.loads(caps_path.read_text())['suitability_history']['fake::demo']) == 1
            before = caps_path.read_bytes()
            def fail(messages):
                raise RuntimeError('synthetic outage')
            with patch.object(fake_client, 'invoke', side_effect=fail):
                done = list(suit.iter_suitability_results('fake::demo', settings={}))[-1]['summary']
                assert done['saved'] is False
            assert caps_path.read_bytes() == before
            raw = json.loads(outs_path.read_text())['outputs']['fake::demo']
            assert all(r['error'] == 'synthetic outage' for r in raw['cases'][case['id']])
        legacy = {'outputs': {'fake::demo': {case['id']: answer}}}
        result = rescore({'cases': [case]}, shared, legacy, 'fake::demo')
        assert result['kind'] == 'offline_rescore'
        assert all(r['verdict'] == 'undecidable' for r in result['checks'])
        # Future normal fixture input includes logs; the scorer adds synthetic cases.
        full = curated_cases()
        hashes = fixture_version(full)
        payload = {'outputs': {'fake::demo': {'fixture_version': hashes, 'cases': {
            c['id']: [{'content': ANSWERS[c['id']][0], 'finish_reason': 'stop'} for _ in range(3)] for c in full}}}}
        current = {'suitability': {'fake::demo': {'tested_suitability': {'checks': [{'id': c['id']} for c in full]}}}}
        scored = rescore({'cases': []}, current, payload, 'fake::demo')
        assert all(c['verdict'] == 'rescored' for c in scored['checks'])
        partial = {'outputs': {'fake::demo': {case['id']: '<tool name="Act">{"text":"'}}}
        uncertain = rescore({'cases': [case]}, shared, partial, 'fake::demo')
        assert uncertain['checks'][0].get('classification') == 'undecidable'
        payload['outputs']['fake::demo']['cases'][full[0]['id']][0]['finish_reason'] = None
        uncertain = rescore({'cases': []}, current, payload, 'fake::demo')
        assert uncertain['checks'][0]['verdict'] == 'undecidable'
        # Builder must not infer the catalog or semantic truth from goldens.
        logged = root / 'calls.jsonl'
        long_golden = 'synthetic preamble ' + 'x' * 700 + answer
        logged.write_text(json.dumps({'task': 'thought', 'prompt': {'system': case['system'], 'user': case['user']}, 'response': long_golden}) + '\n')
        suit.build_cases_from_log(logged)
        built = json.loads((root / 'suitability_cases.json').read_text())
        assert built['cases'][0]['golden'] == long_golden
        assert 'ChangeOutfit' in built['cases'][0]['allowed_tools']
        assert built['cases'][0]['reviewed'] is False
        base = {'task': 'thought', 'prompt': {'system': case['system'], 'user': case['user']},
                'response': answer}
        logged.write_text('\n'.join(json.dumps(row) for row in [
            {**base, 'starttime': '2026-10-30T23:59:59Z'},
            {**base, 'starttime': '2026-10-31T00:00:00Z', 'reviewed': True,
             'expect': case['expect'], 'sets': case['sets']},
            {**base, 'starttime': '2026-10-31T01:00:00Z',
             'prompt': {'system': case['system'], 'user': case['user'] + '\nAnother turn'}},
            {**base, 'timestamp': 'bad'},
        ]) + '\n')
        summary = suit.build_cases_from_log(logged, since='2026-10-31T00:00:00Z')
        assert summary['total'] == 2
        captured = json.loads((root / 'suitability_cases.json').read_text())['cases']
        assert [c['reviewed'] for c in captured] == [True, False]
        assert captured[0]['expect'] == case['expect']
        assert score_case(captured[1], ANSWERS[case['id']][1])['ok'] is True
        try:
            suit.build_cases_from_log(logged, since='not-an-iso-date')
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid cutoff accepted')
        loaded = suit.load_cases()
        assert len(loaded['cases']) == 2 + len(curated_cases())
        assert loaded['fixture_version'] == fixture_version(loaded['cases'])

        # Exercise capture and explicit review through the real CLI, in temp storage.
        command = [sys.executable, 'scripts/suitability_capture_cases.py']
        env = {**os.environ, 'STORAGE_DIR': tmp}
        captured_cli = subprocess.run(
            command + ['--since', '2026-10-31T00:00:00Z', '--log', str(logged)],
            env=env, text=True, capture_output=True, timeout=20, check=True)
        assert 'log_thought_2' in captured_cli.stdout and '"reviewed": false' in captured_cli.stdout
        subprocess.run(command + ['--review', 'log_thought_2'], env=env,
                       text=True, capture_output=True, timeout=20, check=True)
        reviewed_cli = json.loads((root / 'suitability_cases.json').read_text())
        assert all(c['reviewed'] for c in reviewed_cli['cases'])
        (root / 'suitability_cases.json').unlink()
        curated_only = suit.load_cases(auto_build=False)
        curated_file = json.loads((Path(__file__).resolve().parents[1] / 'shared/config/suitability_curated_cases.json').read_text(encoding='utf-8'))
        assert curated_only['curated_only'] and len(curated_only['cases']) == len(curated_file['cases'])

        # Mixed checked semantics are evidence, not an untested run.
        r = {'category': 'tool', 'ok': False, 'hallucinated': False, 'dimensions': {'decision_correct': 'mixed'}, 'run_checks': [{'decision_correct': True}, {'decision_correct': False}]}
        assert suit._summarize('fake', [r])['verdict'] == 'no — tools'
        assert score_case(case, answer + answer)['forbidden_extra_action'] is True
    print('Suitability storage/offline: all expectations hold.')

if __name__ == '__main__':
    main()
