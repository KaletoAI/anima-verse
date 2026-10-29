#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_image_overflow_queue.py

Hand-derived EXPECTED, one permit unless stated:
Q1 A holds the permit: B overflows to T after 0.3 <= waited < 1.6 seconds,
   never runs, leaves pending empty and appears in recent as overflow.
Q2 No target: B returns B after A; pick called at least once.
Q3 Different backend: B returns B; pick called zero times.
Q4 Running A cannot withdraw and stays running.
Q5 C starts within 0.5 seconds after A releases; free slots return to 1.
   A withdrawn worker waiting on a serialize gate also releases both resources.
Q6 Limit 2 minus one running minus one pending = 0; no pending = 1.
Q7 Overflow propagates through BackendPool; cooldown stays false.
Q8 200 zero-threshold claim/withdraw races: executions + withdrawals = 1.
   A zero watch is disabled by contract, so directly race atomic withdrawal;
   also run 20 races with an armed positive threshold. Jitter is 0..2 ms.
Q9 Panel cancel while watched yields GpuTaskCancelled, never overflow.
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_TEMP = tempfile.TemporaryDirectory(prefix="overflow-queue-")
os.environ["ANIMATION_CLIPS_DIR"] = str(Path(_TEMP.name) / "clips")
from app.core import paths
paths.init(_TEMP.name)
from app.core.provider import Provider
from app.core.provider_queue import ProviderQueue, inflight_jobs_snapshot
from app.imagegen.base import ChannelOverflow, OverflowWatch, OVERFLOW_WATCH, GpuTaskCancelled, ImageBackend
from app.imagegen.selection import BackendPool


def until(predicate):
    end = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < end, "condition timed out"
        time.sleep(.001)


def build(limit=1):
    p = Provider(name="local", type="image", api_base="", api_key="",
                 max_concurrent=limit, timeout=5)
    p.available = True
    return ProviderQueue(p, queue_name="backend:local", max_concurrent=limit,
                         chat_pause_enabled=False)


def submit(q, fn, watch=None):
    out = []
    def run():
        token = OVERFLOW_WATCH.set(watch)
        try:
            out.append(q.submit_gpu_task("smoke", 10, fn))
        except BaseException as exc:
            out.append(exc)
        finally:
            OVERFLOW_WATCH.reset(token)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, out


def finish(handle):
    t, out = handle
    t.join(3)
    assert not t.is_alive(), "submission hung"
    assert len(out) == 1
    return out[0]


def blocker(q):
    entered, release = threading.Event(), threading.Event()
    def call():
        entered.set()
        assert release.wait(4)
        return "A"
    h = submit(q, call)
    assert entered.wait(2)
    return release, h


def pending(q):
    with q._lock:
        return next((t for t in q._pending_tasks if t.status == "pending"), None)


def main():
    assert build().free_gpu_slots() == 1
    q = build()
    release, a = blocker(q)
    calls = []
    b = submit(q, lambda: calls.append("B"), OverflowWatch("local", .3, lambda: "T"))
    exc = finish(b)
    assert isinstance(exc, ChannelOverflow), exc
    assert exc.target == "T" and .3 <= exc.waited_s < 1.6
    assert inflight_jobs_snapshot() == {"smoke-user": 1}
    started = threading.Event()
    c = submit(q, lambda: started.set() or "C")
    release.set()
    assert started.wait(.5)
    assert finish(a) == "A" and finish(c) == "C"
    time.sleep(.5)
    assert calls == [] and q.get_status()["pending"] == []
    assert any(t["status"] == "overflow" for t in q.get_status()["recent"])
    until(lambda: q.free_gpu_slots() == 1)
    assert inflight_jobs_snapshot() == {}
    print("Q1/Q5 OK")
    for name, target in [("local", None), ("other", "T")]:
        q = build()
        release, a = blocker(q)
        picks = []
        b = submit(q, lambda: "B", OverflowWatch(name, .3, lambda: picks.append(1) or target))
        if name == "local":
            until(lambda: bool(picks))
        else:
            time.sleep(.35)
        release.set()
        assert finish(a) == "A" and finish(b) == "B"
        assert bool(picks) == (name == "local")
    print("Q2/Q3 OK")
    q = build()
    release, a = blocker(q)
    with q._lock:
        task = q._current_tasks[0]
    assert not q._withdraw_gpu_task(task) and task.status == "running"
    release.set()
    assert finish(a) == "A"
    print("Q4 OK")
    q = build()
    gate = threading.Semaphore(0)
    q._serialize_gate = gate
    calls = []
    b = submit(q, lambda: calls.append("B"), OverflowWatch("local", .3, lambda: "T"))
    until(lambda: q._semaphore.held() == 1)
    assert isinstance(finish(b), ChannelOverflow)
    c = submit(q, lambda: "C")
    gate.release()
    assert finish(c) == "C" and calls == []
    until(lambda: q.free_gpu_slots() == 1)
    assert gate.acquire(blocking=False)
    assert not gate.acquire(blocking=False)
    gate.release()
    print("Q5 serialize gate OK")
    q = build(2)
    q._serialize_gate = threading.Semaphore(1)
    release, a = blocker(q)
    until(lambda: q.free_gpu_slots() == 1)
    b = submit(q, lambda: "B")
    until(lambda: pending(q) is not None)
    assert q.free_gpu_slots() == 0
    release.set()
    assert finish(a) == "A" and finish(b) == "B"
    until(lambda: q.free_gpu_slots() == 2)
    print("Q6 OK")
    class Fake(ImageBackend):
        def check_availability(self):
            return True

        def _generate(self, prompt, negative_prompt, params):
            return [b"img"]

    backend = Fake("fake", "http://localhost", 0, "fake", "FAKE_")
    exc = ChannelOverflow("fake", .3, "T")
    def fail(_):
        raise exc
    try:
        BackendPool([backend]).run_on_backend(backend, fail)
    except ChannelOverflow as caught:
        assert caught is exc
    else:
        raise AssertionError("overflow swallowed")
    assert not backend.in_cooldown()
    print("Q7 OK")
    q = build()
    outcomes = set()
    for i in range(200):
        release, a = blocker(q)
        calls = []
        b = submit(q, lambda: calls.append(1) or "B", OverflowWatch("local", 0, lambda: "T"))
        until(lambda: pending(q) is not None)
        task = pending(q)
        timer = threading.Timer((i % 3) * .001, release.set)
        timer.start()
        if i % 3 == 2:
            time.sleep(.004)
        withdrawn = q._withdraw_gpu_task(task)
        outcomes.add(withdrawn)
        if withdrawn:
            task._done_event.set()
        finish(b)
        assert finish(a) == "A"
        timer.join()
        assert len(calls) + int(withdrawn) == 1, i
    assert outcomes == {False, True}
    for i in range(20):
        release, a = blocker(q)
        calls = []
        b = submit(q, lambda: calls.append(1) or "B", OverflowWatch("local", .003, lambda: "T"))
        timer = threading.Timer(.002 + (i % 3) * .001, release.set)
        timer.start()
        result = finish(b)
        assert finish(a) == "A"
        timer.join()
        assert len(calls) + int(isinstance(result, ChannelOverflow)) == 1
    until(lambda: q.free_gpu_slots() == 1)
    print("Q8 OK (200 atomic + 20 watched races)")
    q = build()
    release, a = blocker(q)
    picks = []
    b = submit(q, lambda: "B", OverflowWatch("local", .3, lambda: picks.append(1)))
    until(lambda: bool(picks))
    assert q.cancel_task(pending(q).task_id)
    assert isinstance(finish(b), GpuTaskCancelled)
    release.set()
    assert finish(a) == "A"
    print("Q9 OK")
    assert inflight_jobs_snapshot() == {}
    print("all checks passed")


if __name__ == "__main__":
    with patch("app.core.provider_queue.limited_user_key", return_value="smoke-user"), \
            patch("app.core.provider_queue.max_inflight_jobs_per_user", return_value=100):
        main()
