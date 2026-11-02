#!/usr/bin/env python3
"""Provider parallel cap across models; no HTTP or persistent storage.

Usage: ./.venv/bin/python scripts/smoke_provider_parallel_cap.py

Hand-derived: two models each with two lanes allow four concurrent calls
when the provider cap is zero. With cap one, holding model A's lane must
leave zero usable lanes on model B, whose acquisition times out. Releasing
A permits B immediately. A second provider is independent. Threaded calls
under cap one must have a measured peak concurrency of exactly one. A nested tool on model B must temporarily
suspend a capped chat on model A and restore it afterward; otherwise cap
one would make the turn wait for itself.
"""
import os
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_tmp = tempfile.TemporaryDirectory()
os.environ['STORAGE_DIR'] = _tmp.name
os.environ['INSTANCE_DIR'] = _tmp.name
from app.core import paths
paths.init(_tmp.name)
from app.core.llm_lanes import LaneManager, LaneTimeout, Priority


def main():
    import inspect
    assert 'provider_cap' in inspect.signature(LaneManager).parameters, 'provider-wide lane cap missing'
    cap = [1]
    m = LaneManager(lane_count=lambda _: 2, provider_cap=lambda p: cap[0] if p == 'P' else 0)
    a = m.acquire_lane('P/A', 'chat:demo', Priority.CHAT, timeout=0)
    assert m.free_lanes('P/B') == 0
    try:
        m.acquire_lane('P/B', 'chat:other', Priority.CHAT, timeout=0)
    except LaneTimeout:
        pass
    else:
        raise AssertionError('second model bypassed provider cap')
    with m.acquire('Q/A', 'chat:demo', Priority.CHAT, timeout=0):
        pass
    a.release()
    with m.acquire('P/B', 'chat:other', Priority.CHAT, timeout=0):
        pass
    cap[0] = 0
    handles = [m.acquire_lane('P/'+model, 'chat:demo', Priority.CHAT, timeout=0)
               for model in ('A', 'A', 'B', 'B')]
    for h in handles:
        h.release()
    cap[0] = 1
    state = [0, 0]
    lock = threading.Lock()
    errors = []
    def call(model):
        try:
            with m.acquire('P/'+model, 'chat:'+model, Priority.CHAT, timeout=3):
                with lock:
                    state[0] += 1
                    state[1] = max(state)
                time.sleep(.01)
                with lock:
                    state[0] -= 1
        except Exception as exc:
            errors.append(exc)
    threads = [threading.Thread(target=call, args=(model,)) for model in ('A', 'B') * 5]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert state == [0, 1], state
    print('PASS: provider cap serializes different models; cap zero preserves model lanes')
    nested_check()


def nested_check():
    """A chat must give back its whole-key permit for another model's tool."""
    from app.core import llm_lanes as lanes
    from app.core import provider_queue
    from app.core.provider import Provider
    from app.core.provider_manager import ProviderManager
    p = Provider('P', 'openai', 'http://fake/v1', 'demo', max_parallel_llm=1)
    queue = provider_queue.ProviderQueue(p, queue_name='P', max_concurrent=1,
                                        chat_pause_enabled=False, serialize_group='')
    pm = ProviderManager()
    pm.providers['P'] = p
    pm.channels['P'] = queue
    pm._queues['P'] = queue
    manager = lanes.LaneManager(lane_count=lambda _: 1, provider_cap=lambda _: 1)
    with patch.object(lanes, '_manager', manager), \
            patch.object(lanes, 'configured_provider_cap', return_value=1), \
            patch.object(provider_queue, '_attach_duration_estimate', return_value=None):
        tid = queue.register_chat_active('demo', model='A')
        try:
            client = SimpleNamespace(provider_name='P', model='B')
            with pm.nested_call_lane(tid, client, 'tool:demo') as handle:
                assert handle.pool_key == 'P/B'
                assert manager.free_lanes('P/A') == 0
                assert tid not in queue._chat_lanes
            assert tid in queue._chat_lanes
            assert manager.free_lanes('P/B') == 0
        finally:
            queue.register_chat_done(tid)
        assert manager.free_lanes('P/B') == 1
    print('PASS: nested tool on a second model suspends and resumes the capped chat lane')


if __name__ == '__main__':
    main()
