#!/usr/bin/env python3
"""Check the in-process suitability FIFO without provider calls.

Usage: ./.venv/bin/python scripts/smoke_suitability_queue.py

Hand-derived expectations: [1] one worker means A runs while B/C wait at
positions 1/2. [2] identical waiting B adds zero jobs. [3] removing B makes
C first. [4] releasing A starts only C. [5] cancelling C during its first
case prevents its second case and all persistence, including the last-case
boundary. All storage is temporary; Events control scheduling, not sleeps.
"""
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

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
    entered = {name: threading.Event() for name in ('A', 'C')}
    release = {name: threading.Event() for name in ('A', 'C')}
    calls = []
    persisted = []
    case = {'id': 'one', 'label': 'one', 'category': 'helper', 'fmt': 'text',
            'system': 'system', 'user': 'ping', 'expect': {}}

    def instance(task, model, **kwargs):
        def invoke(messages):
            calls.append(model)
            entered[model].set()
            assert release[model].wait(5), 'Case was not released'
            return SimpleNamespace(content='ok')
        return SimpleNamespace(available=True, create_llm=lambda **kw:
                               SimpleNamespace(invoke=invoke))

    with patch('app.core.llm_router.create_llm_instance', side_effect=instance), \
         patch.object(suit, 'load_cases', return_value={'cases': [case, {**case, 'id': 'two'}]}), \
         patch.object(suit, '_persist', side_effect=lambda model, *args: persisted.append(model) or True):
        try:
            a = suit.enqueue_test('A')
            assert entered['A'].wait(5)
            b = suit.enqueue_test('B', entry_index=1, routing_entry={'name': 'B'})
            c = suit.enqueue_test('C', concurrency=2)
            assert suit.get_job(a['job_id'])['status'] == 'running'
            assert b['position'] == 1 and c['position'] == 2
            assert c['concurrency'] == 2 and a['concurrency'] == 3
            print('[1] FIFO positions OK')
            assert suit.enqueue_test('B', entry_index=1, routing_entry={'name': 'B'})['job_id'] == b['job_id']
            assert suit.enqueue_test('A')['job_id'] == a['job_id']
            assert [j['job_id'] for j in suit.list_jobs()] == [a['job_id'], b['job_id'], c['job_id']]
            print('[2] Active duplicate requests reuse jobs OK')
            assert suit.cancel_test(b['job_id'])
            assert suit.get_job(b['job_id'])['status'] == 'cancelled'
            assert suit.get_job(c['job_id'])['position'] == 1
            print('[3] Queued cancellation updates positions OK')
            release['A'].set()
            assert entered['C'].wait(5)
            assert suit.get_job(a['job_id'])['status'] == 'done'
            assert sum(j['status'] == 'running' for j in suit.list_jobs()) == 1
            print('[4] One worker across models OK')
            assert suit.cancel_test(c['job_id'])
            release['C'].set()
            wait_for(lambda: suit.get_job(c['job_id'])['status'] == 'cancelled')
            # A subsequent job is a barrier proving the cancelled runner exited.
            end = suit.enqueue_test('A')
            wait_for(lambda: suit.get_job(end['job_id'])['status'] == 'done')
            assert calls.count('C') == 1 and 'C' not in persisted
            assert not suit.cancel_test(end['job_id'])
            assert not suit.cancel_test('missing')
            # Also cancel after the final case, before summary persistence.
            cancel = threading.Event()
            before = len(persisted)
            with patch.object(suit, 'load_cases', return_value={'cases': [case]}):
                events = suit.iter_suitability_results('A', cancel_event=cancel)
                assert next(events)['type'] == 'start'
                assert next(events)['type'] == 'check'
                cancel.set()
                assert list(events) == []
            assert len(persisted) == before
            print('[5] Running cancellation persists nothing OK')
        finally:
            for event in release.values():
                event.set()


if __name__ == '__main__':
    main()
