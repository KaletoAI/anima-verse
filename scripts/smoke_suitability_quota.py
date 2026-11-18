"""Usage: ./.venv/bin/python scripts/smoke_suitability_quota.py

The capability test (``model_suitability``) against a provider with request limits and with reported slots — fake
provider, no requests, temporary storage. Two sections; a failed assert ends its section only, the run exits
non-zero and names every failed section.

[Q] QUOTA. Hand expectations for the capability test against a provider with request limits:
Hand expectations for the capability test against a provider with request
limits (fake provider, no requests, temporary storage):
- max_parallel_llm=1 caps a 3-parallel test to concurrency 1 (peak 1);
  max_parallel_llm=0 leaves it at 3.
- A quota of 2 requests per 1 s window and 2 cases x 3 repeats = 6 sends:
  the test waits instead of failing, so every case is ok and none is infra;
  no 1 s span holds more than 2 sends, so the run takes >= 2.0 s
  (sends at ~0, ~1, ~2 s); each recorded duration stays the 0.05 s answer
  time (< 0.5 s), the quota wait is not counted.
- One remote 429 with Retry-After 0.3 on the first request: the case is
  retried after the gate and still ok, not infra.
- _wait_for_quota with a full quota and a set cancel event raises
  _QuotaWaitCancelled instead of sleeping; with an empty quota it returns 0.

[S] SLOTS (formerly smoke_suitability_slots). Hand expectations:
Hand expectations: a llama-swap entry with meta.llamaswap.max_num_seqs=4
reports 4 slots; one with only "quant=q8-0 | slots=1 | context=8192" in its
description reports 1; one with neither reports None, and so does
max_num_seqs=0. A capability test with 3 parallel requests against a model
whose provider reports 1 slot runs with concurrency 1 (never two requests at
once, summary concurrency 1); with 2 slots it runs with 2; without a report,
or when the model list cannot be read, it keeps 3. Fake provider, no requests;
all storage is temporary.
"""
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths

FAILED = []


def section(name, fn):
    """Run one section; a failed assert or a crash is recorded and the next section still runs."""
    print(f"\n=== {name}")
    try:
        fn()
    except Exception:  # noqa: BLE001 — a failed assert ends its section only
        traceback.print_exc()
        print(f"FAIL {name}")
        FAILED.append(name)


def section_quota():
    from app.core import model_suitability as suit
    from app.core.provider_quota import ProviderQuota

    cases = [dict(id=f'c{i}', group='helpers', task='extraction', system=f'c{i}', user='test',
                  fmt='text', expect={'min': 1}, repeats=3) for i in range(2)]

    class RateLimited(Exception):
        status_code = 429

        def __init__(self):
            super().__init__('Error code: 429 - Too Many Requests')
            self.response = NS(headers={'retry-after': '0.3'})

    def run(*, parallel=0, quota=None, fail_first_429=False):
        active, peak, sends, lock = [0], [0], [], threading.Lock()
        failed = [False]

        def invoke(messages):
            if quota is not None:
                quota.send(None)  # what llm_client._quota_attempt does
            with lock:
                sends.append(time.monotonic())
                if fail_first_429 and not failed[0]:
                    failed[0] = True
                    err = RateLimited()
                    quota.exhaust(err)
                    raise err
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.05)
            with lock:
                active[0] -= 1
            return NS(content='answer', usage={}, finish_reason='stop')

        provider = NS(list_models=lambda: [], max_parallel_llm=parallel, quota=quota)
        instance = NS(available=True, provider_name='fake', _provider=provider,
                      create_llm=lambda **kw: NS(invoke=invoke, provider_quota=quota))
        start = time.monotonic()
        with patch.object(suit, 'runnable_cases', return_value=cases), \
             patch.object(suit, 'load_cases', return_value={}), \
             patch.object(suit, '_persist', return_value=True), \
             patch('app.core.llm_router.create_llm_instance', return_value=instance), \
             patch('app.core.agent_loop.get_agent_loop', return_value=NS(status=lambda: {'running': False})), \
             patch('app.models.world.is_world_frozen', return_value=True):
            summary = list(suit.iter_suitability_results('fake::M', settings={}, concurrency=3))[-1]['summary']
        return summary, peak[0], sends, time.monotonic() - start

    summary, peak, _, _ = run(parallel=1)
    assert (summary['concurrency'], peak) == (1, 1), (summary['concurrency'], peak)
    assert run(parallel=0)[0]['concurrency'] == 3

    summary, _, sends, elapsed = run(quota=ProviderQuota(2, 1))
    checks = summary['checks']
    assert len(checks) == 2 and all(c['ok'] is True and not c['infra'] for c in checks), checks
    assert len(sends) == 6, sends
    for s in sends:
        assert sum(s <= t < s + 1.0 for t in sends) <= 2, sends
    assert elapsed >= 2.0, elapsed
    assert all(0 < c['duration_s'] < 0.5 for c in checks), [c['duration_s'] for c in checks]

    summary, _, sends, _ = run(quota=ProviderQuota(0, 60), fail_first_429=True)
    assert len(sends) == 7, sends
    assert all(c['ok'] is True and not c['infra'] for c in summary['checks']), summary['checks']

    full = ProviderQuota(1, 60)
    full.send(None)
    cancel = threading.Event()
    cancel.set()
    try:
        suit._wait_for_quota(full, cancel, sleep=lambda s: (_ for _ in ()).throw(AssertionError('slept')))
        raise AssertionError('no cancel')
    except suit._QuotaWaitCancelled:
        pass
    assert suit._wait_for_quota(ProviderQuota(1, 60), cancel) == 0
    print('Suitability quota: parallel cap, quota wait, remote 429 retry and cancel OK')


def section_slots():
    from app.core.provider import _reported_capabilities
    from app.core import model_suitability as suit

    assert _reported_capabilities({'meta': {'llamaswap': {'max_num_seqs': 4}}})['slots'] == 4
    assert _reported_capabilities({'description': 'quant=q8-0 | slots=1 | context=8192'})['slots'] == 1
    assert _reported_capabilities({'description': 'quant=q8-0'})['slots'] is None
    assert _reported_capabilities({'meta': {'llamaswap': {'max_num_seqs': 0}}})['slots'] is None

    cases = [dict(id=f'c{i}', group='helpers', task='extraction', system=f'c{i}', user='test',
                  fmt='text', expect={'min': 1}, repeats=3) for i in range(2)]

    def run(models):
        active, peak, lock = [0], [0], threading.Lock()

        def invoke(messages):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.05)
            with lock:
                active[0] -= 1
            return NS(content='answer', usage={}, finish_reason='stop')

        def list_models():
            if models is None:
                raise OSError('unreachable')
            return models
        instance = NS(available=True, provider_name='fake', _provider=NS(list_models=list_models),
                      create_llm=lambda **kw: NS(invoke=invoke))
        with patch.object(suit, 'runnable_cases', return_value=cases), \
             patch.object(suit, 'load_cases', return_value={}), \
             patch.object(suit, '_persist', return_value=True), \
             patch('app.core.llm_router.create_llm_instance', return_value=instance), \
             patch('app.core.agent_loop.get_agent_loop', return_value=NS(status=lambda: {'running': False})), \
             patch('app.models.world.is_world_frozen', return_value=True):
            summary = list(suit.iter_suitability_results('fake::M', settings={}, concurrency=3))[-1]['summary']
        return summary['concurrency'], peak[0]

    assert run([{'name': 'M', 'slots': 1}]) == (1, 1)
    assert run([{'name': 'M', 'slots': 2}]) == (2, 2)
    assert run([{'name': 'M', 'slots': None}])[0] == 3
    assert run([{'name': 'other', 'slots': 1}])[0] == 3
    assert run(None)[0] == 3
    print('Suitability slots: reported slots cap parallel test requests OK')


with tempfile.TemporaryDirectory() as tmp:
    paths.init(tmp)
    paths.init_instance(Path(tmp) / 'instance')
    section("[Q] quota", section_quota)
    section("[S] slots", section_slots)
if FAILED:
    print(f"\nFAILED {len(FAILED)} section(s): " + ", ".join(FAILED))
    sys.exit(1)
