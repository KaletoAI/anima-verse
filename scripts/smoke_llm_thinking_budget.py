"""Usage: ./.venv/bin/python scripts/smoke_llm_thinking_budget.py

Hand expectations: an under-budget answer costs one call; a length cutoff costs
 two, with a 40-token thought and 900-token answer. Usage 10+20=30 prompt,
40+5=45 completion, 2+3=5 cached, 40 reasoning (absent second key stays absent).
Content, parser reasoning and echoed tags all yield exactly {"a":1}. A partial
{"a" plus :1} must concatenate once. Unsupported continuation costs three calls
initially and one on the next invocation, both fallback answers thinking off.
A continuation that writes on to the length limit is kept: content as sent,
finish "length", budget_overrun, NOT unenforceable, nothing remembered, so the
next call (one cut thought + one clean answer) is budgeted again. Gemma
prefill is exactly <|channel>thought\nR<channel|>; echoed tags extract the answer.

Cool-off (review 11#3; NO_CONTINUE_COOLOFF_S 600, SYSTEM clock patched): an
empty continuation, a 400 'unsupported continuation' and a 422 without the
field names each switch thinking off until T0+600. At T0+599 the next call is
one plain call; at T0+601 the entry is dropped and the call is budgeted again
(cut thought + clean answer = 2 calls, content "fine", not unenforceable,
nothing remembered). A 400/422 naming continue_final_message is the proof the
server cannot continue: thinking stays off for good (None), so at T0+601 and
at T0+100000 each call is still one plain call, and the warning is logged once.
"""
import copy
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import llm_client as llm

def response(content='', reasoning=None, finish='stop', usage=None):
    return NS(usage=usage, choices=[NS(finish_reason=finish,
              message=NS(content=content, reasoning_content=reasoning))])

class Rejected(Exception):
    status_code = 400

def client_for(responses, **kw):
    client = llm.LLMClient('budget-model', 'k', 'http://fake/v1', max_tokens=900,
                           thinking=kw.pop('thinking', True), thinking_budget=kw.pop('thinking_budget', 40), **kw)
    calls = []
    def create(**kwargs):
        calls.append(copy.deepcopy(kwargs))
        value = responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value
    client._sync = NS(chat=NS(completions=NS(create=create)))
    return client, calls

def main():
    llm._NO_CONTINUE.clear()
    client, calls = client_for([response('answer')])
    assert client.invoke('ping').budget_hit is False and len(calls) == 1
    for first, second in [('', '{"a":1}'), ('', '\n\n{"a":1}'),
                          ('', '<think>\nR\n</think>\n\n{"a":1}'),
                          ('{"a"', ':1}'), ('{"a"', '<think>\nR\n</think>\n\n{"a":1}')]:
        usage1 = dict(prompt_tokens=10, completion_tokens=40,
                      prompt_tokens_details=dict(cached_tokens=2), completion_tokens_details=dict(reasoning_tokens=40))
        usage2 = dict(prompt_tokens=20, completion_tokens=5, prompt_tokens_details=dict(cached_tokens=3))
        vllm = second.startswith('\n\n')
        client, calls = client_for([response(first, 'R', 'length', usage1),
                                   response('' if vllm else second, second if vllm else None, usage=usage2)])
        result = client.invoke('ping')
        assert result.content == '{"a":1}', result
        assert result.budget_hit and result.reasoning == 'R' and result.finish_reason == 'stop'
        assert result.usage == dict(prompt_tokens=30, completion_tokens=45, cached_tokens=5, reasoning_tokens=40)
        assert calls[0]['max_tokens'] == 40 and calls[1]['max_tokens'] == 900
        assert calls[1]['messages'][-1] == dict(role='assistant', content='<think>\nR\n</think>\n\n' + first)
        assert calls[1]['extra_body']['continue_final_message'] is True
        assert calls[1]['extra_body']['add_generation_prompt'] is False
    client, calls = client_for([response('<think>\nR', finish='length'), response('{"a":1}')])
    assert client.invoke('ping').content == '{"a":1}'
    assert calls[1]['messages'][-1]['content'] == '<think>\nR\n</think>\n\n'
    client, calls = client_for([response('', 'R', 'length'), response('ok')])
    result = client.invoke('ping')
    assert result.usage is None and result.budget_hit
    client, calls = client_for([response('', 'R', 'length', dict(prompt_tokens=2)),
                               response('ok', usage=dict(completion_tokens=3))])
    assert client.invoke('ping').usage == dict(prompt_tokens=2, completion_tokens=3)
    rejected422 = Rejected('unsupported continuation')
    rejected422.status_code = 422
    llm._NO_CONTINUE.clear()
    client, calls = client_for([response('', 'R', 'length'), response('<tool/>\nWait, more', finish='length'),
                                response('', 'R', 'length'), response('<tool/>')])
    overrun, clean = client.invoke('ping'), client.invoke('ping')
    assert overrun.content == '<tool/>\nWait, more' and overrun.finish_reason == 'length'
    assert overrun.budget_overrun and not overrun.budget_unenforceable
    assert clean.content == '<tool/>' and clean.finish_reason == 'stop' and not clean.budget_overrun
    assert len(calls) == 4 and not llm._NO_CONTINUE
    for failure in (Rejected('unsupported continuation'), rejected422, response('')):
        llm._NO_CONTINUE.clear()
        client, calls = client_for([response('', 'R', 'length'), failure, response('ok'), response('next')])
        with patch.object(llm.logger, 'warning') as warning:
            first = client.invoke('ping')
            second = client.invoke('ping')
            assert first.content == 'ok' and first.budget_unenforceable
            assert second.content == 'next' and second.budget_unenforceable
            assert warning.call_count == 1
        assert len(calls) == 4 and (client.base_url, client.model) in llm._NO_CONTINUE
        assert all(c['extra_body']['chat_template_kwargs']['enable_thinking'] is False for c in calls[2:])
    llm._NO_CONTINUE.clear()
    client, calls = client_for([response('{"a"', 'R', 'length'), response(''), response('{"a":1}')])
    assert client.invoke('ping').content == '{"a":1}' and len(calls) == 3
    assert (client.base_url, client.model) in llm._NO_CONTINUE
    llm._NO_CONTINUE.clear()
    for kw in (dict(thinking=False), dict(thinking_budget=None)):
        client, calls = client_for([response('ok')], **kw)
        assert client.invoke('ping').content == 'ok' and len(calls) == 1 and calls[0]['max_tokens'] == 900
    for raw, echoed in ((False, False), (False, True), (True, False), (True, True)):
        llm._NO_CONTINUE.clear()
        client, calls = client_for([response('<|channel>thought\nR' if raw else '',
                                            None if raw else 'R', 'length'),
                                   response('<|channel>thought\nR<channel|>{"a":1}' if echoed else '{"a":1}')])
        client.model = 'Gemma-4-26B'
        assert client.invoke('ping').content == '{"a":1}'
        assert calls[1]['messages'][-1]['content'] == '<|channel>thought\nR<channel|>'
    from app.core.llm_router import _instance_for
    from app.core.provider import Provider
    provider = Provider('demo', 'openai', 'http://fake/v1', 'k', timeout=60)
    for mode, expected in [('on', True), ('off', False), ('task', False)]:
        inst = _instance_for('extraction', dict(provider='P', model='M', thinking=mode, thinking_budget=200), provider)
        with patch('app.core.llm_tasks.task_thinks', return_value=False):
            client = inst.create_llm()
        assert client.thinking is expected and client.thinking_budget == (200 if expected else None)
        assert inst.create_llm(thinking=True, thinking_budget=50).thinking_budget == 50
        assert inst.create_llm(thinking=False).thinking_budget is None
        if mode == 'task':
            with patch('app.core.llm_tasks.task_thinks', return_value=True):
                assert inst.create_llm().thinking is True and inst.create_llm().thinking_budget == 200
    from app.core.config_schema import SECTIONS
    routing = SECTIONS['llm_routing']
    assert routing['fields']['thinking']['choices'] == ['task', 'off', 'on']
    assert routing['fields']['thinking']['default'] == 'task'
    assert routing['fields']['thinking_budget']['min'] == 1
    assert routing['fields']['thinking_budget']['max'] == 32000
    assert all(k in next(p for p in routing['pages'] if p['id'] == 'llms')['fields']
               for k in ('thinking', 'thinking_budget'))
    cooloff_checks()
    print('Thinking budget: under-budget, continuation, parser/echo, partial answer, fallback, cool-off, routing OK')


def cooloff_checks():
    from datetime import timedelta
    from app.core import timeutils
    t0 = timeutils.utc_now()
    clock = [t0]
    key = ('http://fake/v1', 'budget-model')
    unnamed422 = Rejected('context length briefly exceeded')
    unnamed422.status_code = 422
    with patch.object(timeutils, 'utc_now', side_effect=lambda: clock[0]):
        for failure in (response(''), Rejected('unsupported continuation'), unnamed422):
            llm._NO_CONTINUE.clear()
            clock[0] = t0
            client, calls = client_for([response('', 'R', 'length'), failure, response('ok'),
                                        response('plain'),
                                        response('', 'R', 'length'), response('fine')])
            assert client.invoke('ping').content == 'ok' and len(calls) == 3
            assert llm._NO_CONTINUE[key] == t0 + timedelta(seconds=600), llm._NO_CONTINUE
            clock[0] = t0 + timedelta(seconds=599)
            result = client.invoke('ping')
            assert result.content == 'plain' and result.budget_unenforceable and len(calls) == 4
            clock[0] = t0 + timedelta(seconds=601)
            result = client.invoke('ping')
            assert result.content == 'fine' and not result.budget_unenforceable and len(calls) == 6
            assert key not in llm._NO_CONTINUE
        for status in (400, 422):
            llm._NO_CONTINUE.clear()
            clock[0] = t0
            named = Rejected('Unrecognized request argument supplied: continue_final_message')
            named.status_code = status
            client, calls = client_for([response('', 'R', 'length'), named, response('ok'),
                                        response('plain'), response('still plain')])
            with patch.object(llm.logger, 'warning') as warning:
                assert client.invoke('ping').content == 'ok' and len(calls) == 3
                assert llm._NO_CONTINUE[key] is None
                clock[0] = t0 + timedelta(seconds=601)
                assert client.invoke('ping').content == 'plain' and len(calls) == 4
                clock[0] = t0 + timedelta(seconds=100000)
                assert client.invoke('ping').content == 'still plain' and len(calls) == 5
                assert warning.call_count == 1
    llm._NO_CONTINUE.clear()

if __name__ == '__main__':
    main()
