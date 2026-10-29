"""Verify versioned diagnosis, history and offline safety without providers.

Hand-derived from the binding spec: three repeats must retain three complete
answers (including >600 characters), reasoning, usage, duration and stop reason.
Shared JSON must contain none of those answers. One missing-image case causes
zero invokes and adds zero to the score denominator. A subsequent infrastructure
failure must still save local evidence, but must not replace a quality result.
Two quality saves preserve the previous record. Legacy raw strings never become
full rescored verdicts. Migration is non-destructive and refuses in-place writes.
"""
import copy
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
from app.core.suitability_scoring import semantic_cases, fixture_version, score_case
from scripts.suitability_migrate_fixtures import migrate
from scripts.suitability_offline_rescore import rescore


def main():
    with tempfile.TemporaryDirectory() as tmp:
        paths.init(tmp)
        from app.core import model_suitability as suit, model_capabilities as caps
        root = Path(tmp)
        source = root / 'fixtures.json'
        cases = semantic_cases()
        source.write_text(json.dumps({'cases': cases}))
        original = source.read_bytes()
        migrated = migrate(source)
        assert source.read_bytes() == original and migrated != source
        for output in (source, migrated):
            try:
                migrate(source, output)
            except (ValueError, FileExistsError):
                pass
            else:
                raise AssertionError('Migration overwrote existing data')
        case = copy.deepcopy(cases[-1])
        case['repeats'] = 3
        answer = case['test_good']
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
                events = list(suit.iter_suitability_results('fake::demo'))
                assert invoke.call_count == 3
            done = events[-1]['summary']
            assert done['saved'] and done['score'] == '1/1' and done['helper'] == '0/0'
            shared = json.loads(caps_path.read_text())
            assert long_answer not in caps_path.read_text() and 'synthetic reasoning' not in caps_path.read_text()
            raw = json.loads(outs_path.read_text())['outputs']['fake::demo']
            saved = raw['cases'][case['id']]
            assert len(saved) == 3
            assert all(r['content'] == long_answer and r['reasoning'] == 'synthetic reasoning' and r['finish_reason'] == 'stop' and r['usage']['completion_tokens'] == 5 and r['duration_s'] >= 0 for r in saved)
            list(suit.iter_suitability_results('fake::demo'))
            assert len(json.loads(caps_path.read_text())['suitability_history']['fake::demo']) == 1
            before = caps_path.read_bytes()
            def fail(messages):
                raise RuntimeError('synthetic outage')
            with patch.object(fake_client, 'invoke', side_effect=fail):
                done = list(suit.iter_suitability_results('fake::demo'))[-1]['summary']
                assert done['saved'] is False
            assert caps_path.read_bytes() == before
            raw = json.loads(outs_path.read_text())['outputs']['fake::demo']
            assert all(r['error'] == 'synthetic outage' for r in raw['cases'][case['id']])
        legacy = {'outputs': {'fake::demo': {case['id']: answer}}}
        result = rescore({'cases': [case]}, shared, legacy, 'fake::demo')
        assert result['kind'] == 'offline_rescore'
        assert all(r['verdict'] == 'undecidable' for r in result['checks'])
        # Future normal fixture input includes logs; the scorer adds synthetic cases.
        full = semantic_cases()
        hashes = fixture_version(full)
        payload = {'outputs': {'fake::demo': {'fixture_version': hashes, 'cases': {
            c['id']: [{'content': c['test_good'], 'finish_reason': 'stop'} for _ in range(3)] for c in full}}}}
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
        logged.write_text(json.dumps({'task': 'thought', 'prompt': {'system': case['system'], 'user': 'demo action'}, 'response': long_golden}) + '\n')
        suit.build_cases_from_log(logged)
        built = json.loads((root / 'suitability_cases.json').read_text())
        assert built['cases'][0]['golden'] == long_golden
        assert 'GoToCharacter' in built['cases'][0]['allowed_tools']
        assert 'semantic' not in built['cases'][0]['expect']
        loaded = suit.load_cases()
        assert len(loaded['cases']) == 1 + len(semantic_cases())
        assert loaded['fixture_version'] == fixture_version(loaded['cases'])

        # Mixed checked semantics are evidence, not an untested run.
        r = {'category': 'tool', 'ok': False, 'hallucinated': False, 'dimensions': {'decision_correct': 'mixed'}, 'run_checks': [{'decision_correct': True}, {'decision_correct': False}]}
        assert suit._summarize('fake', [r])['verdict']['tool'] is False
        assert score_case(case, answer + answer)['forbidden_extra_action'] is True
    print('Suitability storage/offline: all expectations hold.')

if __name__ == '__main__':
    main()
