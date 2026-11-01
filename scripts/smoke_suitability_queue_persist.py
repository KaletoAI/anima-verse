#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_suitability_queue_persist.py

Hand-derived expectations: A1/A2 share one FIFO worker, B1 has its own.
Blocking A1 and B1 leaves three records in enqueue order: running/queued/running.
Restart restores exactly three interrupted jobs without starting workers; an
identical request adds zero. Resume runs A1 before A2 and completion removes
all three disk records. Discard removes three; cancel removes one interrupted
record. Corrupt JSON restores zero; one invalid settings entry beside a valid
entry restores exactly one and logs a warning. Write failures at start/finish
release the provider registration and leave one recoverable interrupted job.
Recovery POSTs deny anonymous/player with 401/403 and allow admin with 200;
both HTTP adapters also declare require_admin. All storage is temporary.
"""
import json
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while not predicate():
        assert time.monotonic() < deadline, 'Timed out'
        time.sleep(.005)


with tempfile.TemporaryDirectory() as directory:
    paths.init(directory)
    paths.init_instance(Path(directory) / 'instance')
    from app.core import model_suitability as suit
    target = paths.get_instance_dir() / 'suitability_queue.json'
    gate = threading.Event()
    started = []
    gates = {}

    def runner(model, **kwargs):
        started.append(model)
        assert gates.get(model, gate).wait(5)
        yield {'type': 'done', 'summary': {}}

    def stored():
        return json.loads(target.read_text())['jobs']

    def restart(content):
        target.write_text(content)
        suit._reset_for_tests()
        with patch.object(suit.threading, 'Thread') as thread:
            jobs = suit.list_jobs()
            thread.assert_not_called()
        return jobs

    with patch.object(suit, 'iter_suitability_results', runner):
        jobs = [suit.enqueue_test(model, settings={}, concurrency=2)
                for model in ('A::one', 'A::two', 'B::one')]
        wait_for(lambda: len(started) == 2)
        rows = stored()
        assert [j['model'] for j in rows] == ['A::one', 'A::two', 'B::one']
        assert [j['status'] for j in rows] == ['running', 'queued', 'running']
        original = target.read_text()
        gate.set()
        wait_for(lambda: not suit._ACTIVE_PROVIDERS)
        assert stored() == []
        restored = restart(original)
        assert len(restored) == 3 and all(j['status'] == 'interrupted' for j in restored)
        assert target.read_text() == original
        assert len(suit.interrupted_jobs()) == 3
        same = suit.enqueue_test('A::one', settings={}, concurrency=2)
        assert same['job_id'] == jobs[0]['job_id'] and len(suit.list_jobs()) == 3
        started.clear()
        gate.clear()
        gates.update({model: threading.Event() for model in ('A::one', 'A::two', 'B::one')})
        assert suit.resume_interrupted() == 3
        wait_for(lambda: len(started) == 2)
        assert len(stored()) == 3
        gates['A::one'].set()
        wait_for(lambda: 'A::two' in started)
        assert [j['model'] for j in stored()] == ['A::two', 'B::one']
        gates['B::one'].set()
        wait_for(lambda: len(stored()) == 1)
        assert stored()[0]['model'] == 'A::two'
        gates['A::two'].set()
        wait_for(lambda: not suit._ACTIVE_PROVIDERS)
        assert [m for m in started if m.startswith('A::')] == ['A::one', 'A::two']
        assert stored() == []
        restart(original)
        # Hand-derived: jobs HTTP adapter must retain all three interrupted rows.
        from app.routes import admin_settings as routes
        from app.core.auth_dependency import require_admin
        for endpoint in (routes.llm_suitability_resume, routes.llm_suitability_discard_interrupted):
            import inspect
            assert inspect.signature(endpoint).parameters['user'].default.dependency is require_admin
        assert len(routes.llm_suitability_test_jobs(user={})['jobs']) == 3
        with patch.object(suit, 'resume_interrupted', return_value=3):
            assert routes.llm_suitability_resume(user={}) == {'resumed': 3}
        assert routes.llm_suitability_discard_interrupted(user={}) == {'discarded': 3}
        assert suit.list_jobs() == [] and stored() == []
        restart(original)
        assert suit.cancel_test(jobs[0]['job_id'])
        assert len(stored()) == 2 and suit.get_job(jobs[0]['job_id']) is None
        with patch.object(suit.logger, 'warning') as warning:
            assert restart('{broken') == []
            assert warning.called
        invalid = dict(rows[0], job_id='invalid', settings={'max_tokens': -1})
        with patch.object(suit.logger, 'warning') as warning:
            restored = restart(json.dumps({'jobs': [invalid, rows[1]]}))
            assert len(restored) == 1 and restored[0]['job_id'] == rows[1]['job_id']
            assert warning.called
        # Malformed entries of different shapes cannot hide a subsequent valid job.
        invalid_entries = [None, {}, dict(rows[0], concurrency=True),
                           dict(rows[0], status='done'), dict(rows[0], enqueued_at='bad')]
        with patch.object(suit.logger, 'warning') as warning:
            restored = restart(json.dumps({'jobs': invalid_entries + [rows[1]]}))
            assert len(restored) == 1 and warning.call_count == len(invalid_entries)
        snapshot = suit.interrupted_jobs()[0]
        snapshot['settings']['max_tokens'] = -1
        assert suit.get_job(snapshot['job_id'])['settings']['max_tokens'] == 900
    # Exercise the real gate and dependency without TestClient's thread portal.
    import asyncio
    from fastapi import HTTPException, Request
    from fastapi.responses import JSONResponse
    from app.core import auth_dependency as auth
    async def check_recovery_auth():
        async def reached(request):
            return JSONResponse({'reached': True})
        for action in ('resume', 'discard-interrupted'):
            request = Request({'type': 'http', 'method': 'POST', 'scheme': 'http',
                               'path': '/admin/settings/llm-suitability-test/' + action,
                               'headers': [], 'query_string': b'', 'server': ('test', 80)})
            for user, expected in ((None, 401), ({'role': 'user'}, 403), ({'role': 'admin'}, 200)):
                token = auth.current_user_ctx.set(user)
                try:
                    response = await auth.auth_gate_middleware(request, reached)
                    assert response.status_code == expected
                finally:
                    auth.current_user_ctx.reset(token)
                with patch.object(auth, '_get_session_user', return_value=user):
                    try:
                        require_admin(request)
                    except HTTPException as exc:
                        assert exc.status_code == expected
                    else:
                        assert expected == 200
    asyncio.run(check_recovery_auth())
    # Hand-derived: a failed disk write must release the worker registration.
    # Both a start failure and a finish failure leave one recoverable job;
    # a later same-provider job can run, then explicit resume clears the old one.
    suit.discard_interrupted()
    for failure_status in ('running', 'done'):
        actual_persist = suit._persist_queue
        def fail_write():
            if any(j['model'] == 'IO::old' and j['status'] in ((failure_status,) if failure_status == 'running' else ('done', 'error'))
                   for j in suit._JOBS.values()):
                raise OSError('fake disk failure')
            actual_persist()
        def instant_runner(model, **kwargs):
            yield {'type': 'done', 'summary': {}}
        with patch.object(suit, 'iter_suitability_results', instant_runner):
            with patch.object(suit, '_persist_queue', side_effect=fail_write), patch.object(suit.logger, 'error'):
                old = suit.enqueue_test('IO::old', settings={})
                wait_for(lambda: not suit._ACTIVE_PROVIDERS)
                assert suit.get_job(old['job_id'])['status'] == 'interrupted'
            new = suit.enqueue_test('IO::new', settings={})
            wait_for(lambda: not suit._ACTIVE_PROVIDERS)
            assert suit.get_job(new['job_id'])['status'] == 'done'
            assert suit.resume_interrupted() == 1
            wait_for(lambda: not suit._ACTIVE_PROVIDERS)
            assert stored() == []
        suit._reset_for_tests()
print('PASS: suitability queue persistence, restart, FIFO, resume, discard, validation and cancel')
