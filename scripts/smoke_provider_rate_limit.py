#!/usr/bin/env python3
"""Provider quota contract, using a fake SYSTEM clock and no network.

Usage: ./.venv/bin/python scripts/smoke_provider_rate_limit.py

Hand-derived expectations: nine sends at seconds 0..8 fill a 9/60 window.
At 60.5 only the send at 0 expired, leaving eight. A reservation occupies
one slot until consumed (one send, not two), released, or age 60. A 7-second
Retry-After blocks through second 6.999 and frees at 7; absent that header,
an unconfigured provider blocks for 60 seconds. Two budget stages are two
HTTP sends. Quiet availability polls must occupy zero slots.
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from contextlib import ExitStack
import asyncio
import threading
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_tmp = tempfile.TemporaryDirectory()
os.environ['STORAGE_DIR'] = _tmp.name
os.environ['INSTANCE_DIR'] = _tmp.name
from app.core import paths
paths.init(_tmp.name)
from app.core.provider import Provider


def main():
    assert 'rate_limit_requests' in Provider.__dataclass_fields__, 'provider quota fields missing'
    from app.core.provider_quota import ProviderQuota, is_rate_limit_error
    now = [0.0]
    q = ProviderQuota(9, 60, clock=lambda: now[0])
    for t in range(9):
        now[0] = t
        q.send()
    assert q.wait_seconds() == 52
    assert q.reason() == "rate limit 9/9, frees in 52 s"
    now[0] = 60.5
    assert q.wait_seconds() == 0 and q.used == 8
    q = ProviderQuota(1, 60, clock=lambda: now[0])
    r = q.reserve()
    assert r is not None and q.used == 1 and q.reserve() is None
    q.send(r)
    assert q.used == 1
    now[0] += 60
    assert q.used == 0
    r = q.reserve()
    now[0] += 60
    assert q.used == 0
    q.send(r)
    assert q.used == 1
    print('PASS: sliding window, reservations and expiry')
    routing_checks()
    client_checks()
    config_checks()
    streaming_check()


class Limited(Exception):
    status_code = 429

    def __init__(self, retry=None):
        super().__init__('Too Many Requests')
        self.response = NS(headers={} if retry is None else {'Retry-After': str(retry)})


def provider(name, now, capacity=1):
    from app.core.provider_quota import ProviderQuota
    return Provider(name, 'openai', 'http://fake/v1', 'demo', available=True,
                    rate_limit_requests=capacity,
                    quota=ProviderQuota(capacity, 60, clock=lambda: now[0]))


def routing_checks():
    from app.core import llm_router as router
    from app.core import llm_lanes as lanes
    from app.core.provider_quota import is_rate_limit_error
    now = [0.0]
    providers = {n: provider(n, now) for n in ('A', 'B')}
    routing = [{'provider': n, 'model': 'demo', 'tasks': [{'task': t, 'order': i}
               for t in ('intent', 'thought', 'chat_stream')]} for i, n in enumerate(providers, 1)]
    with ExitStack() as stack:
        stack.enter_context(patch.object(router, '_load_routing', return_value=routing))
        stack.enter_context(patch.object(router, '_resolve_character_override', return_value=None))
        stack.enter_context(patch.object(router, 'get_provider_manager', return_value=NS(get_provider=providers.get)))
        stack.enter_context(patch.object(router, 'disabled_providers', return_value=set()))
        stack.enter_context(patch.object(router, '_model_cooled_down', return_value=False))
        stack.enter_context(patch('app.core.llm_task_state.is_enabled', return_value=True))
        stack.enter_context(patch.object(lanes, '_manager', lanes.LaneManager(lane_count=lambda _: 1)))
        for _ in range(5):
            assert router._usable(routing[0], quiet=True) is providers['A']
            assert router.resolve_llm('intent', reserve=False).provider_name == 'A'
        assert providers['A'].quota.used == 0
        for _ in range(5):
            assert router.overflow_target('thought', reserve=False).provider_name == 'A'
        assert providers['A'].quota.used == 0
        chosen = router.overflow_target('thought')
        assert providers['A'].quota.used == 1
        providers['A'].quota.release(chosen._quota_reservation)
        a = router.resolve_llm('intent')
        assert a.provider_name == 'A' and providers['A'].quota.used == 1
        a.create_llm().provider_quota.send(a._quota_reservation)
        assert providers['A'].quota.used == 1
        with patch.object(router.logger, 'info') as log:
            for _ in range(4):
                assert router._usable(routing[0]) is None
            assert log.call_count == 1
            assert router._usable(routing[0], quiet=True) is None
            assert log.call_count == 1
            now[0] = 60
            assert router._usable(routing[0]) is providers['A']
            providers['A'].quota.send()
            assert router._usable(routing[0]) is None
            assert log.call_count == 2
        for task in ('intent', 'thought', 'chat_stream'):
            inst = router.resolve_llm(task)
            assert inst.provider_name == 'B'
            providers['B'].quota.release(inst._quota_reservation)
        result = router.explain_routing({'llm_routing': routing, 'providers': [{'name': n} for n in providers]}, provider_lookup=providers.get,
                    cooled_down=lambda *a: None, disabled=set(), runtime_disabled=set())
        intent = next(t for t in result['tasks'] if t['task'] == 'intent')
        assert intent['chain'][0]['skipped'] == 'rate limit 1/1, frees in 60 s'
        assert router.quota_wait_seconds('intent') == 0
        providers['B'].quota.send()
        assert router.quota_wait_seconds('intent') == 60
        providers['B'].available = False
        assert router.quota_wait_seconds('intent') == 0
        providers['B'].available = True
        # Worker-thread llm_call waits, then the next resolve succeeds.
        def advance(seconds):
            now[0] += seconds
        sent = []
        def submit(**kw):
            client = kw['llm']
            sent.append(client.provider_name)
            client.provider_quota.send(client.quota_reservation)
            return NS(content='ok')
        with patch.object(router.time, 'sleep', side_effect=advance), patch.object(router, 'get_llm_queue', return_value=NS(submit=submit)):
            assert router.llm_call('intent', 'system', 'user').content == 'ok'
        assert sent == ['A'] and now[0] == 120
        now[0] = 180
        assert router.resolve_llm('intent', reserve=False).provider_name == 'A'
        # Async wait yields to another coroutine; it never uses time.sleep.
        providers['A'].quota.send()
        providers['B'].quota.send()
        original_sleep = asyncio.sleep
        progress = []
        async def async_advance(seconds):
            await original_sleep(0)
            progress.append('yielded')
            now[0] += seconds
        async def check_async():
            with patch('asyncio.sleep', side_effect=async_advance):
                inst = await router.resolve_llm_async('intent')
                assert inst.provider_name == 'A'
                providers['A'].quota.release(inst._quota_reservation)
        asyncio.run(check_async())
        assert progress == ['yielded']
        # A 429 retries the same call on B; availability and health stay intact.
        now[0] += 60
        sent.clear()
        from app.core.provider_quota import ProviderQuota
        providers["A"].quota = ProviderQuota(9, 60, clock=lambda: now[0])
        error = Limited(7)
        def limited_submit(**kw):
            client = kw['llm']
            sent.append(client.provider_name)
            client.provider_quota.send(client.quota_reservation)
            if client.provider_name == 'A':
                wrapped = RuntimeError('queue wrapper')
                wrapped.__cause__ = error
                raise wrapped
            return NS(content='fallback')
        with patch.object(router, 'get_llm_queue', return_value=NS(submit=limited_submit)):
            assert router.llm_call('intent', 'system', 'user').content == 'fallback'
        assert sent == ['A', 'B']
        assert providers['A'].available and providers['A']._cooldown_until == 0
        assert providers["A"].quota.wait_seconds() == 7
        assert is_rate_limit_error(error)
        q = provider('C', now, capacity=0).quota
        q.exhaust(error)
        assert q.wait_seconds() == 7
        now[0] += 6.999
        assert 0 < q.wait_seconds() < .002
        now[0] += .001
        assert q.wait_seconds() < .000001
        q.exhaust(Limited())
        assert q.wait_seconds() == 60
        now[0] += 60
        assert q.wait_seconds() == 0
        # Queue callers (including chat aliases) and direct tool decisions must
        # receive the same 429 fallback as llm_call, preserving their payload.
        from app.core import provider_manager as pm_mod
        from app.core.llm_queue import LLMQueue
        from app.core.streaming import StreamingAgent
        calls = []
        payload = [{'role': 'user', 'content': 'same question'}]
        def invoke(client):
            calls.append(client.provider_name)
            client.provider_quota.send(client.quota_reservation)
            if client.provider_name == 'A':
                raise Limited(7)
            return NS(content='fallback')
        def queued(*args, **kwargs):
            assert args[3] is payload
            return invoke(args[2])
        pm = NS(get_provider=providers.get,
                provider_name_for=lambda client: client.provider_name,
                get_queue_for_provider=lambda name: NS(submit=queued),
                get_first_queue=lambda: None)
        for kind in ('queue', 'tool'):
            for p in providers.values():
                p.quota = ProviderQuota(9, 60, clock=lambda: now[0])
            calls.clear()
            initial = router.resolve_llm('intent').create_llm()
            if kind == 'queue':
                with patch.object(pm_mod, 'get_provider_manager', return_value=pm):
                    result = LLMQueue().submit('send_message', 1, initial, payload,
                                               routing_task='intent')
            else:
                agent = StreamingAgent(initial, 'none', {}, tool_llm=initial)
                with patch.object(agent, '_invoke_tool_client_laned', side_effect=lambda c, messages: invoke(c)):
                    result = agent._invoke_tool_llm_laned(payload)
            assert result.content == 'fallback' and calls == ['A', 'B'], (kind, calls)
            assert providers['A'].available and providers['A']._cooldown_until == 0
    print('PASS: routing, quiet polling, full-phase logs, explanation, sync/async waits and 429 fallback for llm_call, queued chat and direct tools')


def client_checks():
    from app.core.llm_client import LLMClient, LLMChunk, AnthropicLLMClient
    from app.core.provider_quota import ProviderQuota
    now = [0.0]
    q = ProviderQuota(9, 60, clock=lambda: now[0])
    def response(content='', reasoning=None, finish='stop'):
        return NS(usage=None, choices=[NS(finish_reason=finish,
                  message=NS(content=content, reasoning_content=reasoning))])
    client = LLMClient('demo', 'demo', 'http://fake/v1', thinking=True,
                       thinking_budget=4, max_tokens=8)
    client.provider_quota = q
    client.quota_reservation = q.reserve()
    with patch.object(client._sync.chat.completions, 'create', side_effect=[
            response('', 'think', 'length'), response('answer')]) as create:
        assert client.invoke('question').content == 'answer'
        assert create.call_count == 2 and q.used == 2
    error = Limited(7)
    with patch.object(client._sync.chat.completions, 'create', side_effect=error) as create:
        try:
            client.invoke('question')
        except Limited:
            pass
        else:
            raise AssertionError('429 swallowed')
        assert create.call_count == 1 and q.used == 3
    assert q.wait_seconds() == 7
    # Streaming setup is also one send, with no same-provider 429 retries.
    now[0] = 60
    async def check_stream():
        with patch.object(client._async.chat.completions, 'create', side_effect=Limited()) as create:
            try:
                async for _ in client.astream('question'):
                    pass
            except Limited:
                pass
            else:
                raise AssertionError('stream 429 swallowed')
            assert create.call_count == 1 and q.used == 1
    asyncio.run(check_stream())
    # A rate-limit event after content starts cannot replay the response, but
    # must still gate this key for subsequent calls.
    client.provider_quota = ProviderQuota(0, 60, clock=lambda: now[0])
    async def interrupted():
        yield NS(choices=[NS(delta=NS(content='partial'), finish_reason=None)], usage=None)
        raise Limited(7)
    async def interrupted_create(**kwargs):
        return interrupted()
    async def midstream():
        received = []
        with patch.object(client._async.chat.completions, 'create', side_effect=interrupted_create) as create:
            try:
                async for chunk in client.astream('question'):
                    received.append(chunk.content)
            except Limited:
                pass
            else:
                raise AssertionError('midstream 429 swallowed')
            assert received == ['partial'] and create.call_count == 1
            assert client.provider_quota.wait_seconds() == 7
    asyncio.run(midstream())
    # Concurrent reservations cannot all claim the last slot.
    q = ProviderQuota(1, 60)
    results = []
    threads = [threading.Thread(target=lambda: results.append(q.reserve())) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(r is not None for r in results) == 1
    # A transient 503 retains its retry, and both HTTP attempts count.
    from app.core import llm_client as client_module
    busy = RuntimeError('503 Service Unavailable')
    client.provider_quota = ProviderQuota(9, 60, clock=lambda: now[0])
    client.thinking = False
    with patch.object(client._sync.chat.completions, 'create', side_effect=[busy, response('ok')]) as create, \
            patch.object(client_module.time, 'sleep'):
        assert client.invoke('question').content == 'ok'
        assert create.call_count == 2 and client.provider_quota.used == 2
    print('PASS: continuation and 503 retry each count two HTTP sends; sync/stream 429 has no local retry; atomic reservations')


def config_checks():
    from app.core import config
    from app.core.config_schema import SECTIONS
    from app.core.provider_manager import ProviderManager
    fields = SECTIONS['providers']['fields']
    assert SECTIONS['providers']['scope'] == 'instance'
    assert [(fields[n]['default'], fields[n]['min']) for n in
            ('rate_limit_requests', 'rate_limit_window_seconds', 'max_parallel_llm')] == [(0, 0), (60, 1), (0, 0)]
    cfg = [{'name': 'demo', 'type': 'openai', 'api_base': 'http://fake/v1',
            'api_key': 'demo', 'rate_limit_requests': 9,
            'rate_limit_window_seconds': 60, 'max_parallel_llm': 1}]
    pm = ProviderManager()
    with patch.object(config, 'get', return_value=cfg), patch.object(Provider, 'check_availability', return_value=True):
        first = pm.provider_for_test('demo')
        second = pm.provider_for_test('demo')
        assert first.quota is second.quota
        first.quota.send()
        assert second.quota.used == 1
        assert second.max_parallel_llm == 1
    # Config-based provider construction and reload retain sends for this key.
    env = {'PROVIDER_1_NAME': 'demo', 'PROVIDER_1_TYPE': 'openai',
           'PROVIDER_1_API_BASE': 'http://fake/v1', 'PROVIDER_1_API_KEY': 'demo'}
    with patch.dict(os.environ, env, clear=True), patch.object(config, 'get', return_value=cfg), \
            patch.object(pm, '_channel'), patch.object(pm, '_load_backend_channels', return_value=({}, set())):
        pm.load_providers()
        loaded = pm.get_provider('demo')
        assert loaded.quota is first.quota and loaded.quota.used == 1
        assert (loaded.rate_limit_requests, loaded.rate_limit_window_seconds, loaded.max_parallel_llm) == (9, 60, 1)
        pm.load_providers()
        assert pm.get_provider('demo').quota is loaded.quota
    print('PASS: instance schema, config-based loading, suitability quota sharing and reload preservation')


def streaming_check():
    """A stream's 429 moves to B before emitting text and occupies B's lane."""
    from app.core import provider_manager as pm_mod, provider_queue as pq_mod
    from app.core import llm_router as router, llm_lanes as lanes
    from app.core.llm_client import LLMClient
    from app.core.streaming import StreamingAgent, ContentEvent
    now = [0.0]
    providers = {n: provider(n, now, 9) for n in ('A', 'B')}
    manager = pm_mod.ProviderManager()
    for name, p in providers.items():
        queue = pq_mod.ProviderQueue(p, queue_name=name, max_concurrent=1,
                                     chat_pause_enabled=False, serialize_group='')
        manager.providers[name] = p
        manager.channels[name] = queue
        manager._queues[name] = queue
    lm = lanes.LaneManager(lane_count=lambda _: 1, provider_cap=lambda _: 1)
    routing = [{'provider': n, 'model': 'demo', 'tasks': [{'task': 'chat_stream', 'order': i}]}
               for i, n in enumerate(providers, 1)]
    clients = {n: LLMClient('demo', 'demo', 'http://fake/v1') for n in providers}
    sends = []
    async def fail(**kwargs):
        sends.append('A')
        raise Limited(7)
    async def chunks():
        yield NS(choices=[NS(delta=NS(content='fallback'), finish_reason='stop')], usage=None)
    async def success(**kwargs):
        assert lm.free_lanes('B/demo') == 0, 'fallback stream bypassed B lane'
        sends.append('B')
        return chunks()
    def create(instance, **kwargs):
        client = clients[instance.provider_name]
        client.provider_name = instance.provider_name
        client.provider_quota = instance._provider.quota
        client.quota_reservation = instance._quota_reservation
        return client
    async def inline_thread(fn, *args, **kwargs):
        # These uncontended fake lanes need no worker; production uses to_thread.
        return fn(*args, **kwargs)
    with ExitStack() as stack:
        stack.enter_context(patch.object(pm_mod, '_provider_manager', manager))
        stack.enter_context(patch.object(lanes, '_manager', lm))
        stack.enter_context(patch.object(pq_mod, '_attach_duration_estimate', return_value=None))
        stack.enter_context(patch.object(router, '_load_routing', return_value=routing))
        stack.enter_context(patch.object(router, '_resolve_character_override', return_value=None))
        stack.enter_context(patch.object(router, 'disabled_providers', return_value=set()))
        stack.enter_context(patch('app.core.llm_task_state.is_enabled', return_value=True))
        stack.enter_context(patch.object(router.LLMInstance, 'create_llm', create))
        stack.enter_context(patch.object(clients['A']._async.chat.completions, 'create', side_effect=fail))
        stack.enter_context(patch.object(clients['B']._async.chat.completions, 'create', side_effect=success))
        first = router.resolve_llm('chat_stream')
        agent = StreamingAgent(first.create_llm(), 'none', {}, agent_name='demo', log_task='chat_stream')
        stack.enter_context(patch.object(agent, '_log_llm_call'))
        tid = manager.channels['A'].register_chat_active('demo', model='demo')
        agent.chat_task_id = tid
        async def check():
            with patch('asyncio.to_thread', side_effect=inline_thread):
                for _ in range(2):
                    text = ''.join([event.content async for event in agent.stream('system', [], 'question')
                                   if isinstance(event, ContentEvent)])
                    assert text == 'fallback'
                    assert lm.free_lanes('B/demo') == 1
                    assert agent.chat_task_id == tid
        try:
            asyncio.run(check())
        finally:
            manager.register_chat_done(tid)
        assert sends == ['A', 'B', 'B'], sends
        assert providers['A'].available and providers['A']._cooldown_until == 0
        assert providers['A'].quota.wait_seconds() == 7
        assert providers['B'].quota.used == 2
    print('PASS: streaming 429 fallback counts sends, takes the target lane, and releases it before tools')


if __name__ == '__main__':
    main()
