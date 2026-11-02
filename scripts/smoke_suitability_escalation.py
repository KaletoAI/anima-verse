"""Usage: ./.venv/bin/python scripts/smoke_suitability_escalation.py

Hand expectations: X first passes at 600, Y passes off but fails on, Z always
fails. Off and verified 600 each score 1/3, so off wins. X stages 0/300/600,
Z 0/300/600/900; verification must call Y three more times at 600. Seven
reasoning characters estimate two tokens. No reasoning stops after 300;
an unenforceable budget also stops there. Three image request rejections
make vision unsupported, excluded from the score and verdict. A winning
600-token candidate coexists with an excluded fixture without a crash. A model
that thinks for X but not for Z stops only Z (stages 0/300, no group stop, since
models such as Nanbeige decide per case) and keeps X's earned 600 candidate:
1/2 beats off 0/2; Z has no fabricated latency sample at an untried setting. Progress: the off pass reports
done 1, 2, 3 before the first check event, then one phase per escalation stage. Fake clients,
no provider requests; all storage is temporary.
"""
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths

with tempfile.TemporaryDirectory() as tmp:
    paths.init(tmp)
    paths.init_instance(Path(tmp) / 'instance')
    from app.core import model_suitability as suit
    calls = []
    cases = [dict(id=x, group='helpers', task='extraction', system=x, user='test', fmt='text',
                  expect={'min': 1}, repeats=3) for x in ('X', 'Y', 'Z')]
    mode = 'normal'
    class ImageError(Exception):
        status_code = 500
    def factory(**kw):
        budget = kw['thinking_budget'] or 0
        def invoke(messages):
            name = messages[0]['content']
            calls.append((name, budget))
            if name == 'V':
                raise ImageError('image input is not supported - provide mmproj')
            if name == 'T':
                return NS(content='NONE', usage={}, finish_reason='stop')
            ok = name == 'X' and budget >= 600 or name in ('Y', 'Y2') and budget == 0
            return NS(content='answer' if ok else '', reasoning='1234567' if budget and mode != 'ineffective' and not (mode == 'partial_ineffective' and name == 'Z') else '',
                      usage={}, finish_reason='stop', budget_hit=bool(budget),
                      budget_unenforceable=bool(budget and mode == 'unenforceable'))
        return NS(invoke=invoke)
    instance = NS(available=True, provider_name='fake', create_llm=factory)
    def run(selected):
        calls.clear()
        with patch.object(suit, 'runnable_cases', return_value=selected), \
             patch.object(suit, 'load_cases', return_value={}), \
             patch.object(suit, '_persist', return_value=True), \
             patch('app.core.llm_router.create_llm_instance', return_value=instance), \
             patch('app.core.agent_loop.get_agent_loop', return_value=NS(status=lambda: {'running': False})), \
             patch('app.models.world.is_world_frozen', return_value=True):
            events = list(suit.iter_suitability_results('fake::M', settings={
                'thinking_max': dict(tools=0, helpers=900, vision=900)}))
            run.events = events
            return events[-1]['summary']
    summary = run(cases)
    kinds = [(e['type'], e.get('done'), e.get('phase')) for e in run.events]
    first_check = next(i for i, k in enumerate(kinds) if k[0] == 'check')
    assert [k[1] for k in kinds[:first_check] if k[2] == 'without thinking'] == [1, 2, 3]
    assert ('progress', None, 'helpers: X with thinking up to 600') in kinds
    assert ('progress', None, 'helpers: verifying Y at 600') in kinds
    checks = {c['id']: c for c in summary['checks']}
    t = summary['thinking']['helpers']
    assert checks['X']['stage'] == 600 and checks['Y']['stage'] == 0 and checks['Z']['stage'] is None
    assert [s['budget'] for s in checks['X']['stages']] == [0, 300, 600]
    assert [s['budget'] for s in checks['Z']['stages']] == [0, 300, 600, 900]
    assert t['score_off'] == t['score_at_budget'] == '1/3' and t['candidate_budget'] == 600
    assert t['recommended'] == dict(thinking=False, thinking_budget=None)
    assert calls.count(('Y', 600)) == 3
    assert checks['X']['runs'][0]['usage']['reasoning_tokens'] == 2
    assert checks['X']['runs'][0]['reasoning_tokens_estimated'] is True
    assert summary['score'] == '1/3'
    summary = run([cases[0], cases[2]])
    assert summary['thinking']['helpers']['recommended'] == dict(thinking=True, thinking_budget=600)
    assert summary['thinking']['helpers']['score_at_budget'] == '1/2'
    assert summary['thinking_leak_runs'] == 0
    assert summary['reasoning_tokens_median'] == 2 and summary['reasoning_tokens_estimated'] is True
    assert summary['speed']['helpers']['reasoning_tokens_estimated'] is True
    assert calls.count(('Z', 600)) == 3, 'failed case at candidate is reused, never retried'
    missing = dict(cases[2], id='missing', fixture_error='missing catalog')
    summary = run([cases[0], missing])
    assert summary['score'] == '1/1' and summary['checks'][1]['recommended_ok'] is None
    for mode, reason in [('ineffective', 'thinking_ineffective'), ('unenforceable', 'budget_unenforceable')]:
        summary = run(cases)
        assert summary['thinking']['helpers']['stopped'] == reason
        assert max(b for _, b in calls) == 300
    mode = 'partial_ineffective'
    summary = run([cases[0], cases[2]])
    assert summary['thinking']['helpers']['stopped'] is None
    assert [s['budget'] for s in summary['checks'][1]['stages']] == [0, 300]
    assert summary['thinking']['helpers']['score_at_budget'] == '1/2'
    assert summary['thinking']['helpers']['recommended']['thinking_budget'] == 600
    assert summary['checks'][1]['recommended_runs'] == [], 'no speed invented for an untried setting'
    image = Path(tmp) / 'image.png' 
    image.write_bytes(b'fake')
    v = dict(id='V', group='vision', task='image_analysis', system='V', user='test', image=str(image), repeats=3)
    mode = 'normal'
    summary = run(cases + [v])
    assert summary['vision'] == 'not_supported' and not summary['infra']
    assert summary['score'] == '1/3' and 'vision' not in summary['verdict']
    assert not any(n == 'V' and b for n, b in calls)
    tool = dict(id='T', group='tools', task='thought', system='T', user='test',
                allowed_tools=[], expect={'none': True}, repeats=3)
    good_helpers = [dict(cases[1], task='extraction_chat_state'),
                    dict(cases[1], id='Y2', system='Y2', task='extraction')]
    summary = run([tool] + good_helpers + [v])
    assert summary['vision'] == 'not_supported' and summary['verdict'] == 'yes'
    assert summary['score'] == '3/3' and summary['thinking']['tools']['candidate_budget'] == 0
print('Escalation, verification tie, group stops, estimates and unsupported vision OK')
