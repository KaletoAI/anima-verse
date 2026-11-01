"""Usage: ./.venv/bin/python scripts/smoke_llm_thinking_off.py

Hand expectations: off sends false for all three families; only Gemma adds
thinking.disabled. A rejected field costs two calls initially, then one call.
Three checks times three runs = nine runs; one wholly truncated check = three
cutoffs and one failed_by_truncation id. Positive counts 216,216,216 median 216.
"""
import asyncio
import copy
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
from app.core import llm_client as llm

class Rejected(Exception):
    status_code = 400

def main():
    for model in ('sensenova-loop-9b', 'nanbeige4.3-33b', 'gemma-4-26b'):
        client = llm.LLMClient(model, 'key', 'https://fake.test/v1')
        body = client._build_kwargs()['extra_body']
        assert body['chat_template_kwargs'] == {'enable_thinking': False}
        assert body.get('thinking') == ({'type': 'disabled'} if 'gemma' in model else None)
        assert 'chat_template_kwargs' not in client._build_kwargs(thinking=True).get('extra_body', {})
    assert llm.usage_from_openai({'completion_tokens_details': {'reasoning_tokens': 216}})['reasoning_tokens'] == 216
    assert 'reasoning_tokens' not in llm.usage_from_openai({})
    client.extra_params = {'chat_template_kwargs': {'enable_thinking': True}}
    assert client._build_kwargs()['extra_body']['chat_template_kwargs']['enable_thinking'] is True
    response = NS(usage=None, choices=[NS(finish_reason='stop', message=NS(content='ok', reasoning_content='hidden'))])
    for streaming in (False, True):
        llm._NO_CHAT_TEMPLATE_KWARGS.clear()
        calls = []
        def create(**kw):
            calls.append(copy.deepcopy(kw))
            if 'chat_template_kwargs' in kw.get('extra_body', {}):
                raise Rejected('unknown chat_template_kwargs')
            return response
        async def chunks():
            if False:
                yield
        async def acreate(**kw):
            create(**kw)
            return chunks()
        client._sync = NS(chat=NS(completions=NS(create=create)))
        client._async = NS(chat=NS(completions=NS(create=acreate)))
        async def consume():
            async for _ in client.astream('ping'):
                pass
        for _ in range(2):
            if streaming:
                asyncio.run(consume())
            else:
                assert client.invoke('ping').reasoning == 'hidden'
        assert len(calls) == 3
        assert (client.base_url, client.model) in llm._NO_CHAT_TEMPLATE_KWARGS
        assert all('chat_template_kwargs' not in c.get('extra_body', {}) for c in calls[1:])
    with tempfile.TemporaryDirectory() as tmp:
        paths.init(tmp)
        from app.core import model_suitability as suit
        records = []
        for i in range(3):
            records.append({'id': str(i), 'category': 'helper', 'ok': i != 0, 'hallucinated': False,
                'runs': [{'finish_reason': 'length' if i == 0 else 'stop',
                          'reasoning': 'hidden' if i == 0 else None,
                          'usage': {'reasoning_tokens': 216} if i == 0 else {}} for _ in range(3)],
                'run_checks': [{'ok': i != 0, 'truncated': i == 0} for _ in range(3)]})
        summary = suit._summarize('fake', records)
        assert summary['total_runs'] == 9 and summary['truncated_runs'] == 3
        assert summary['failed_by_truncation'] == ['0']
        assert summary['thinking_runs'] == 3 and summary['reasoning_tokens_median'] == 216
        from app.core import model_capabilities as caps
        for record in records:
            record['truncated_runs'] = sum(r['finish_reason'] == 'length' for r in record['runs'])
            record['reasoning_tokens'] = [r['usage'].get('reasoning_tokens') for r in record['runs']]
        with patch.object(caps, 'save_raw_outputs') as raw, patch.object(caps, 'save_suitability') as save:
            assert suit._persist('fake', summary, records)
            stored = save.call_args.args[1]['tested_suitability']
            assert stored['truncated_runs'] == 3 and stored['total_runs'] == 9
            assert stored['failed_by_truncation'] == ['0']
            assert stored['checks'][0]['reasoning_tokens'] == [216, 216, 216]
            assert 'hidden' not in str(stored)
            assert 'hidden' in str(raw.call_args)
    print('Thinking off, strict-server sync/stream retry, reasoning and nine-run summary OK')

if __name__ == '__main__':
    main()
