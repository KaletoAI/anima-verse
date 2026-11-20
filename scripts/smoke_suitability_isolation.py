"""Usage: ./.venv/bin/python scripts/smoke_suitability_isolation.py

Every model test runs under the same conditions (2026-11-20: one refused
continuation kept thinking off for every later test of that model name until
the restart, and three such runs were saved as 8/16).

Real LLMClient objects on a fake server, real _persist into a temp capability
file. One helper case, one repeat, thinking up to 300. The fake server answers
an off request with nothing (the case fails without thinking), a budgeted
request with a thought cut at the budget, and the continuation per run:

Run A (continuation refused with a 400 naming continue_final_message), started
with the PROCESS memory already saying "thinking off" for this model:
  requests = 1 off + 1 at 300 = 2; server calls = 1 warm-up (thinking off,
  unscored) + 1 + 2 (cut + refused) = 4 — no further "plain" call, so the
  mode never changed. The check fails with
  "continuation_failed" and the server's body; the run is not saved: no
  capability file entry, saved False, reason names continuation_failed and
  the body. The body is in a WARNING. The process memory is untouched.
Run B right after, same process, continuation answers: 4 server calls again,
  the case passes at 300, thinking_runs 1, recommended thinking on / 300,
  saved as 1/1, no history entry (A never became a record).
Run C = A again: B's record 1/1 stays, still no history entry.
"""
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths

BODY = '{"error": {"message": "continue_final_message is not supported with this template"}}'


class Refused(Exception):
    status_code = 400
    response = NS(text=BODY)


def response(content='', reasoning=None, finish='stop'):
    return NS(usage=None, choices=[NS(finish_reason=finish,
              message=NS(content=content, reasoning_content=reasoning))])


with tempfile.TemporaryDirectory() as tmp:
    paths.init(tmp)
    paths.init_instance(Path(tmp) / 'instance')
    from datetime import timedelta
    from app.core import llm_client as llm, model_capabilities as caps, model_suitability as suit
    from app.core.timeutils import utc_now
    server = dict(refuse=True, calls=[])

    def create(**kwargs):
        body = kwargs.get('extra_body') or {}
        if body.get('continue_final_message'):
            server['calls'].append('continue')
            if server['refuse']:
                raise Refused('Error code: 400')
            return response('answer')
        if (body.get('chat_template_kwargs') or {}).get('enable_thinking') is False:
            server['calls'].append('off')
            return response('')
        server['calls'].append('budget')
        assert kwargs['max_tokens'] == 300, kwargs['max_tokens']
        return response('', 'R', 'length')

    def factory(**kw):
        client = llm.LLMClient('m', 'k', 'http://fake/v1', temperature=kw['temperature'],
                               max_tokens=kw.get('max_tokens') or 900, thinking=kw['thinking'],
                               thinking_budget=kw['thinking_budget'])
        client._sync = NS(chat=NS(completions=NS(create=create)))
        return client

    instance = NS(available=True, provider_name='fake', model='m', create_llm=factory)
    case = dict(id='X', group='helpers', task='extraction', system='X', user='test', fmt='text',
                expect={'min': 1}, repeats=1)
    caps_path = Path(tmp) / 'caps.json'

    def run(refuse):
        server.update(refuse=refuse, calls=[])
        with patch.object(suit, 'runnable_cases', return_value=[case]), \
             patch.object(suit, 'load_cases', return_value={}), \
             patch.object(caps, '_caps_path', return_value=caps_path), \
             patch.object(caps, '_outputs_path', return_value=Path(tmp) / 'outputs.json'), \
             patch('app.core.llm_router.create_llm_instance', return_value=instance), \
             patch('app.core.agent_loop.get_agent_loop', return_value=NS(status=lambda: {'running': False})), \
             patch('app.models.world.is_world_frozen', return_value=True), \
             patch.object(llm.logger, 'warning') as warning:
            events = list(suit.iter_suitability_results('fake::m', settings={
                'thinking_max': dict(tools=0, helpers=300, vision=0)}))
        run.warnings = [call.args[0] % call.args[1:] for call in warning.call_args_list]
        assert events[-1]['type'] == 'done', events[-1]
        return events[-1]['summary']

    def stored():
        caps.invalidate_cache()
        data = json.loads(caps_path.read_text()) if caps_path.is_file() else {}
        return data.get('suitability', {}).get('fake::m'), data.get('suitability_history', {}).get('fake::m')

    key = ('http://fake/v1', 'm')
    poison = utc_now() + timedelta(seconds=10 ** 6)
    llm._NO_CONTINUE.clear()
    llm._NO_CONTINUE_STRIKES.clear()
    llm._NO_CONTINUE[key] = poison
    llm._NO_CHAT_TEMPLATE_KWARGS.discard(key)

    a = run(refuse=True)
    assert server['calls'] == ['off', 'off', 'budget', 'continue'], server['calls']
    assert a['requests'] == 2 and a['continuation_refused_runs'] == 1
    assert a['invalid_reason'] == 'continuation_failed' and a['saved'] is False
    assert 'continuation_failed' in a['not_saved_reason'] and BODY in a['not_saved_reason']
    check = a['checks'][0]
    assert check['ok'] is False and check['detail'] == 'continuation_failed: HTTP 400: ' + BODY, check['detail']
    assert check['runs'][0]['continuation_error'] == 'HTTP 400: ' + BODY
    assert any(BODY in line for line in run.warnings), run.warnings
    assert stored() == (None, None)
    assert llm._NO_CONTINUE == {key: poison} and not llm._NO_CONTINUE_STRIKES

    b = run(refuse=False)
    assert server['calls'] == ['off', 'off', 'budget', 'continue'], server['calls']
    assert b['saved'] is True and b['warmup_s'] >= 0 and b['score'] == '1/1' and 'invalid_reason' not in b
    assert b['thinking_runs'] == 1 and b['budget_hits'] == 1 and b['continuation_failures'] == 0
    assert b['thinking']['helpers']['recommended'] == dict(thinking=True, thinking_budget=300)
    assert b['thinking']['helpers']['stopped'] is None
    record, history = stored()
    assert record['tested_score'] == '1/1' and not history

    c = run(refuse=True)
    assert c['saved'] is False and c['invalid_reason'] == 'continuation_failed'
    record, history = stored()
    assert record['tested_score'] == '1/1' and not history
    llm._NO_CONTINUE.clear()
print('Suitability isolation: refused continuation fails one check, run unsaved, next run thinks again OK')
