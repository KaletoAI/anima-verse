"""Usage: ./.venv/bin/python scripts/smoke_llm_thinking_budget.py

Hand expectations: an under-budget answer costs one call; a length cutoff costs
 two, with a 40-token thought and 900-token answer. Usage 10+20=30 prompt,
40+5=45 completion, 2+3=5 cached, 40 reasoning (absent second key stays absent).
Content, parser reasoning and echoed tags all yield exactly {"a":1}. A partial
{"a" plus :1} must concatenate once. Unsupported continuation costs three calls
initially and one on the next invocation, both fallback answers thinking off.
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
    for failure in (Rejected('unsupported continuation'), rejected422, response('')):
        llm._NO_CONTINUE.clear()
        client, calls = client_for([response('', 'R', 'length'), failure, response('ok'), response('next')])
        with patch.object(llm.logger, 'warning') as warning:
            assert client.invoke('ping').content == 'ok'
            assert client.invoke('ping').content == 'next'
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
    from app.core.llm_router import _instance_for
    provider = NS(type='openai', api_base='http://fake/v1', api_key='k', timeout=60)
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
    print('Thinking budget: under-budget, continuation, parser/echo, partial answer, fallback, routing OK')

if __name__ == '__main__':
    main()
