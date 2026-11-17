#!/usr/bin/env python3
"""Route lookups that never send must not book a provider quota slot.

Usage: ./.venv/bin/python scripts/smoke_resolve_only_quota.py

Runs without the server, on a temp storage dir, with fake providers whose
quota uses a fake SYSTEM clock frozen at 0 (nothing ever expires here).

Hand-derived expectations (review 11#1):

1. Embeddings. Provider A has a 9-requests/60-s window and serves
   ``pose_embedding``. ``current_model_id()`` resolves once,
   ``effective_backend()`` once, ``embed("x")`` (backend auto) twice — once
   in ``effective_backend`` and once in ``_embed_external``; its vector goes
   out over ``httpx.post`` (stubbed here), which never consumes a slot.
   Twenty rounds of those three calls are 20 × (1 + 1 + 2) = 80 lookups.
   Free slots before: 9 − 0 = 9; after: must still be 9 (``used == 0``), and
   every ``current_model_id()`` must stay ``external:demo``. The old code
   booked one slot per lookup: the window was full after the 9th lookup
   (inside round 3: lookups 1..4, 5..8, 9 = current_model_id of round 3), and
   from round 3 on the id fell back to ``internal:<model>`` — the re-embed
   storm of the finding.
2. ``release_reservation``: one reserving ``resolve_llm('intent')`` on A
   books 1 (used 1); releasing it gives 0; a second release and a release of
   ``None`` change nothing (0).
3. The stream fallback: the failed stream ran on A (429 → A blocked by the
   Retry-After of 30 s), the chain resolves B, but B is already in ``tried``.
   The instance is not used, so B's window must be back at 0 afterwards
   (old code: 1, held for the whole window).
4. The tool LLM lookups of chat_engine, act_engine and thoughts (the
   single-mode tool instance that is often never sent) pass ``reserve=``
   explicitly — an AST check, because driving a whole chat turn needs a
   world. thoughts passes ``reserve=bool(fast)``: in fast mode the tool
   instance narrates for sure, and the unused thought instance is released
   through ``release_reservation`` (checked as a call in the same function).
"""
import ast
import os
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_tmp = tempfile.TemporaryDirectory()
os.environ['STORAGE_DIR'] = _tmp.name
os.environ['INSTANCE_DIR'] = _tmp.name
from app.core import paths
paths.init(_tmp.name)
from app.core.provider import Provider  # noqa: E402

FAILS = []


def check(cond, msg):
    print(('PASS: ' if cond else 'FAIL: ') + msg)
    if not cond:
        FAILS.append(msg)


class Limited(Exception):
    status_code = 429

    def __init__(self):
        super().__init__('Too Many Requests')
        self.response = NS(headers={'Retry-After': '30'})


def provider(name, now, capacity):
    from app.core.provider_quota import ProviderQuota
    return Provider(name, 'openai', 'http://fake/v1', 'demo', available=True,
                    rate_limit_requests=capacity,
                    quota=ProviderQuota(capacity, 60, clock=lambda: now[0]))


def router_patches(stack, router, routing, providers):
    stack.enter_context(patch.object(router, '_load_routing', return_value=routing))
    stack.enter_context(patch.object(router, '_resolve_character_override', return_value=None))
    pm = NS(get_provider=providers.get,
            provider_name_for=lambda llm: getattr(llm, 'provider_name', ''))
    stack.enter_context(patch.object(router, 'get_provider_manager', return_value=pm))
    stack.enter_context(patch('app.core.provider_manager.get_provider_manager', return_value=pm))
    stack.enter_context(patch.object(router, 'disabled_providers', return_value=set()))
    stack.enter_context(patch.object(router, '_model_cooled_down', return_value=False))
    stack.enter_context(patch('app.core.llm_task_state.is_enabled', return_value=True))


def embedding_checks():
    from app.core import llm_router as router
    from app.core import embedding
    now = [0.0]
    providers = {'A': provider('A', now, 9)}
    routing = [{'provider': 'A', 'model': 'demo',
                'tasks': [{'task': 'pose_embedding', 'order': 1}, {'task': 'intent', 'order': 1}]}]

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {'data': [{'index': 0, 'embedding': [0.1, 0.2]}]}

    real_get = embedding.config.get

    def cfg_get(key, default=None):
        if key == 'embedding':
            return {'backend': 'auto'}
        return real_get(key, default)

    with ExitStack() as stack:
        router_patches(stack, router, routing, providers)
        stack.enter_context(patch.object(embedding.config, 'get', side_effect=cfg_get))
        stack.enter_context(patch('httpx.post', return_value=Resp()))
        stack.enter_context(patch('app.models.world.get_world_setting', return_value=''))
        quota = providers['A'].quota
        free_before = quota.capacity - quota.used
        ids = set()
        for _ in range(20):
            ids.add(embedding.current_model_id())
            embedding.effective_backend()
            vec = embedding.embed('x')
        free_after = quota.capacity - quota.used
        check(free_before == 9 and free_after == 9,
              f'80 embedding lookups leave the 9 free slots free (before {free_before}, after {free_after})')
        check(ids == {'external:demo'}, f'the embedding model id never flips (ids {sorted(ids)})')
        check(vec == [0.1, 0.2], 'embed() still reaches the external endpoint')

        inst = router.resolve_llm('intent')
        check(quota.used == 1, f'a reserving resolve books one slot (used {quota.used})')
        router.release_reservation(inst)
        check(quota.used == 0 and inst._quota_reservation is None,
              f'release_reservation frees it (used {quota.used})')
        router.release_reservation(inst)
        router.release_reservation(None)
        check(quota.used == 0, 'a second release and release(None) change nothing')


def stream_fallback_check():
    from app.core import llm_router as router
    from app.core.streaming import StreamingAgent
    now = [0.0]
    providers = {n: provider(n, now, 9) for n in ('A', 'B')}
    routing = [{'provider': n, 'model': 'demo', 'tasks': [{'task': 'chat_stream', 'order': i}]}
               for i, n in enumerate(providers, 1)]
    with ExitStack() as stack:
        router_patches(stack, router, routing, providers)
        agent = StreamingAgent.__new__(StreamingAgent)
        agent.log_task = 'chat_stream'
        agent.agent_name = ''
        failed = NS(provider_name='A', model='demo', model_name='demo')
        result = agent._fallback_after_upstream_error(failed, Limited(), {('B', 'demo')})
        check(result is None, 'the chain is exhausted when the next entry was already tried')
        check(providers['B'].quota.used == 0,
              f"the unused fallback instance gives its slot back (B used {providers['B'].quota.used})")


def _calls(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            fname = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, 'id', '')
            if fname == name:
                yield node


def static_checks():
    for rel in ('app/core/chat_engine.py', 'app/core/act_engine.py', 'app/core/thoughts.py'):
        tree = ast.parse((ROOT / rel).read_text(encoding='utf-8'))
        intent_calls = [c for c in _calls(tree, 'resolve_llm')
                        if c.args and isinstance(c.args[0], ast.Constant) and c.args[0].value == 'intent']
        check(bool(intent_calls) and all(any(k.arg == 'reserve' for k in c.keywords) for c in intent_calls),
              f'{rel}: the tool-LLM lookup passes reserve= ({len(intent_calls)} call(s))')
    tree = ast.parse((ROOT / 'app/core/thoughts.py').read_text(encoding='utf-8'))
    released = [c for c in _calls(tree, 'release_reservation')
                if c.args and isinstance(c.args[0], ast.Name) and c.args[0].id == '_thought_inst']
    check(len(released) == 1, 'thoughts: fast mode releases the unused thought instance')


def main():
    embedding_checks()
    stream_fallback_check()
    static_checks()
    if FAILS:
        print(f'FAILED: {len(FAILS)} check(s)')
        return 1
    print('ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
