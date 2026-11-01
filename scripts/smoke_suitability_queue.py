#!/usr/bin/env python3
"""Provider FIFO. Usage: .venv/bin/python scripts/smoke_suitability_queue.py

Hand-derived: A::one holds A's worker. A::two has position 1, while B::one
starts immediately and A::one is still running. Cancelling A::two removes
it without invocation. A different concurrency/settings is a distinct request;
identical active requests reuse the ID. Running cancellation prevents persistence,
including cancellation at the final-case boundary. Events control scheduling.
No provider requests or persistent storage writes occur.
"""
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
_storage = tempfile.TemporaryDirectory()
paths.init(_storage.name)
from app.core import model_suitability as suit


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(.005)
    raise AssertionError('Worker did not reach expected state')


def main():
    entered = {name: threading.Event() for name in ('A::one', 'B::one')}
    release = {name: threading.Event() for name in entered}
    persisted = []
    calls = []
    case = dict(id='one', group='helpers', task='extraction', system='system',
                user='ping', fmt='text', repeats=1)
    def instance(task, model, **kwargs):
        def invoke(messages):
            calls.append(model)
            entered[model].set()
            assert release[model].wait(5)
            return SimpleNamespace(content='ok')
        return SimpleNamespace(available=True, provider_name=model.split('::')[0],
                               create_llm=lambda **kw: SimpleNamespace(invoke=invoke))
    with patch('app.core.llm_router.create_llm_instance', side_effect=instance), patch.object(
            suit, 'load_cases', return_value={'cases': [case]}), patch.object(
            suit, '_persist', side_effect=lambda model, *args: persisted.append(model) or True):
        try:
            a = suit.enqueue_test('A::one', settings={})
            assert entered['A::one'].wait(5)
            a2 = suit.enqueue_test('A::two', settings={})
            b = suit.enqueue_test('B::one', settings={})
            assert entered['B::one'].wait(5)
            assert suit.get_job(a['job_id'])['status'] == 'running'
            assert suit.get_job(a2['job_id'])['status'] == 'queued'
            assert suit.get_job(a2['job_id'])['position'] == 1
            assert suit.get_job(b['job_id'])['status'] == 'running'
            assert 'A::two' not in calls
            print('[1] Independent provider workers and provider-local position 1 OK')
            assert suit.enqueue_test('A::two', settings={})['job_id'] == a2['job_id']
            changed = suit.enqueue_test('A::two', settings={}, concurrency=2)
            other = suit.enqueue_test('A::two', settings={'thinking': True})
            assert len({changed['job_id'], other['job_id'], a2['job_id']}) == 3
            assert changed['position'] == 2 and other['position'] == 3
            for job in (a2, changed, other):
                assert suit.cancel_test(job['job_id'])
            assert suit.cancel_test(b['job_id'])
            release['B::one'].set()
            wait_for(lambda: suit.get_job(b['job_id'])['status'] == 'cancelled')
            assert 'B::one' not in persisted
            release['A::one'].set()
            wait_for(lambda: suit.get_job(a['job_id'])['status'] == 'done')
            assert persisted == ['A::one']
            assert suit.get_job(a['job_id'])['finished_ago_s'] is not None
            print('[2] Dedup includes settings/concurrency; queued/running cancellation OK')
            # After the final check, cancellation still prevents persistence.
            cancel = threading.Event()
            events = suit.iter_suitability_results('A::one', settings={}, cancel_event=cancel)
            assert next(events)['type'] == 'start'
            assert next(events)['type'] == 'check'
            cancel.set()
            assert list(events) == [] and persisted == ['A::one']
            assert not suit.cancel_test('missing')
            print('[3] Final-case cancellation prevents persistence OK')
        finally:
            for event in release.values():
                event.set()
    # A second queued job actually starts after the first finishes, in FIFO order.
    with patch.object(suit, 'iter_suitability_results') as runner:
        gate = threading.Event()
        started = threading.Event()
        order = []
        def run(model, **kwargs):
            order.append(model)
            if model == 'C::first':
                started.set()
                assert gate.wait(5)
            yield {'type': 'done', 'summary': {}}
        runner.side_effect = run
        try:
            first = suit.enqueue_test('C::first', settings={})
            assert started.wait(5)
            second = suit.enqueue_test('C::second', settings={})
            assert second['position'] == 1 and order == ['C::first']
            gate.set()
            wait_for(lambda: suit.get_job(second['job_id'])['status'] == 'done')
            assert order == ['C::first', 'C::second']
            print('[4] Same-provider FIFO starts second only after first finishes OK')
        finally:
            gate.set()


if __name__ == '__main__':
    main()
