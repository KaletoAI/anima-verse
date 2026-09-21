#!/usr/bin/env python3
"""Smoke run: the task-queue management operations, the pause scope and the
worker wakeup.

Usage:
    ./.venv/bin/python scripts/smoke_task_queue_ops.py

Runs WITHOUT the server and against a THROWAWAY task_queue.db: the storage
root is a temp dir set through ``paths.init`` BEFORE the first import of an
app module, so ``TaskQueue._db_path`` (= ``<storage>/task_queue.db``) can
never be the real one. No world DB is touched, nothing sleeps for a rule.

The findings under test (review 2026-09-20, logic_llm.md)
---------------------------------------------------------------------------
LLM-3  ``retry_task`` bound ``(task_id)`` and ``clear_completed`` ``(cutoff)``
       — a STRING, not a 1-tuple. sqlite3 then counts the characters as
       bindings, so ``POST /queue/tasks/item/{id}/retry`` and
       ``DELETE /queue/tasks/clear`` (without ``queue_name``) raised
       ProgrammingError -> HTTP 500. The retry path and the only server-side
       way to shrink the DB were both dead. Additionally the route's
       ``status`` parameter had no counterpart in ``clear_completed``.
LLM-4  ``_dequeue`` fetched the single head row and returned None when THAT
       row's queue was paused. One pending task of a paused queue therefore
       stopped every other queue: pausing "default" (what the AgentLoop pause
       switch pauses) froze background, improvements and instagram jobs too.
LLM-14 The worker cleared its wake event AFTER a successful ``wait()``. A
       ``submit()`` landing between the two lines lost its notification and
       the task started up to 10 s late.

Expected values, derived by hand from app/core/task_queue.py — never recorded
from a run:

  * A task inserted by ``submit`` has status 'pending'. Forcing it to
    'failed' and calling ``retry_task`` must return True and leave status
    'pending' again — 11 characters in a task id must not become 11
    bindings.
  * ``clear_completed(older_than_hours=0)`` deletes exactly the rows whose
    status is one of completed/failed/cancelled/interrupted AND whose
    completed_at is older than now. Two finished rows in, two deleted, the
    pending row untouched.
  * ``clear_completed(status="failed")`` deletes only the failed row;
    ``status="pending"`` is not a clearable status and must delete NOTHING
    (a cleanup may never remove live work).
  * With queue "default" paused and two pending tasks — default at priority
    1 (the better priority) and background at priority 20 — ``_dequeue``
    must return the BACKGROUND one. Priority ordering stays intact: with
    the pause lifted, the same two rows must yield the default one first.
  * ``_worker_loop`` must clear the wake event BEFORE it looks for work and
    must not clear it after a wait: checked on the source (AST), because the
    lost wakeup is a race that a timing test can only miss, plus a live run
    that proves a freshly submitted task starts in well under the 10-s
    fallback timeout.
"""
from __future__ import annotations

import ast
import inspect
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Throwaway storage BEFORE any app module that could open a DB is imported.
_TMP = Path(tempfile.mkdtemp(prefix="smoke_task_queue_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(_TMP / "clips")
from app.core import paths  # noqa: E402

paths.init(_TMP)
assert paths.get_storage_dir() == _TMP.resolve(), paths.get_storage_dir()

from app.core.task_queue import TaskQueue  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{(' — ' + detail) if detail else ''}")
        failures.append(label)


def _status_of(tq: TaskQueue, task_id: str) -> str:
    conn = tq._connect()
    try:
        row = conn.execute("SELECT status FROM tasks WHERE task_id=?",
                           (task_id,)).fetchone()
        return row["status"] if row else ""
    finally:
        conn.close()


def _set(tq: TaskQueue, task_id: str, **cols) -> None:
    sets = ", ".join(f"{k}=?" for k in cols)
    conn = tq._connect()
    try:
        conn.execute(f"UPDATE tasks SET {sets} WHERE task_id=?",
                     (*cols.values(), task_id))
        conn.commit()
    finally:
        conn.close()


def _count(tq: TaskQueue) -> int:
    conn = tq._connect()
    try:
        return int(conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"])
    finally:
        conn.close()


def _new_queue() -> TaskQueue:
    """A queue WITHOUT worker threads: `_started = True` keeps `submit` from
    auto-starting the pool, so the rows stay pending and `_dequeue` can be
    driven by hand."""
    tq = TaskQueue()
    tq._started = True
    return tq


def part_llm3() -> None:
    print("\nLLM-3 — retry / clear bind 1-tuples, and clear honours `status`")
    tq = _new_queue()
    tid = tq.submit("smoke_type", {"n": 1}, queue_name="background")
    check("submit returns a task id", bool(tid), repr(tid))
    _set(tq, tid, status="failed", error="boom")

    try:
        ok = tq.retry_task(tid)
        check("retry_task(failed) -> True", ok is True, repr(ok))
        check("retry_task puts the row back to 'pending'",
              _status_of(tq, tid) == "pending", _status_of(tq, tid))
    except Exception as exc:  # the old code raised sqlite3.ProgrammingError
        check("retry_task does not raise", False, f"{type(exc).__name__}: {exc}")

    # Two finished rows + one pending row.
    done = tq.submit("smoke_type", {"n": 2}, queue_name="background")
    bad = tq.submit("smoke_type", {"n": 3}, queue_name="background")
    _set(tq, done, status="completed", completed_at="2000-01-01T00:00:00")
    _set(tq, bad, status="failed", completed_at="2000-01-01T00:00:00")
    before = _count(tq)
    check("3 rows before the cleanup", before == 3, str(before))

    try:
        deleted = tq.clear_completed(older_than_hours=0, status="pending")
        check("clear_completed(status='pending') deletes nothing",
              deleted == 0 and _count(tq) == 3, f"deleted={deleted} left={_count(tq)}")
        deleted = tq.clear_completed(older_than_hours=0, status="failed")
        check("clear_completed(status='failed') deletes exactly the failed row",
              deleted == 1 and _status_of(tq, bad) == "", f"deleted={deleted}")
        deleted = tq.clear_completed(older_than_hours=0)
        check("clear_completed() without a queue deletes the remaining finished row",
              deleted == 1 and _count(tq) == 1, f"deleted={deleted} left={_count(tq)}")
        check("the pending row survives every cleanup",
              _status_of(tq, tid) == "pending", _status_of(tq, tid))
    except Exception as exc:  # the old code raised sqlite3.ProgrammingError
        check("clear_completed does not raise", False, f"{type(exc).__name__}: {exc}")


def part_llm4() -> None:
    print("\nLLM-4 — a paused queue holds back only its own tasks")
    tq = _new_queue()
    conn = tq._connect()
    try:
        conn.execute("DELETE FROM tasks")
        conn.commit()
    finally:
        conn.close()

    hi = tq.submit("smoke_type", {"q": "default"}, queue_name="default", priority=1)
    lo = tq.submit("smoke_type", {"q": "background"}, queue_name="background",
                   priority=20)
    tq.pause_queue("default")

    row = tq._dequeue()
    check("_dequeue skips the paused head row and takes the background task",
          bool(row) and row["task_id"] == lo,
          "None" if not row else f"{row['queue_name']}/{row['task_id']}")
    if row:
        _set(tq, lo, status="pending", started_at=None)

    row = tq._dequeue()
    check("the paused task is still not handed out",
          bool(row) and row["task_id"] == lo,
          "None" if not row else row["queue_name"])
    if row:
        _set(tq, lo, status="pending", started_at=None)

    tq.resume_queue("default")
    row = tq._dequeue()
    check("with the pause lifted, priority ordering wins again (default first)",
          bool(row) and row["task_id"] == hi,
          "None" if not row else f"{row['queue_name']}/{row['task_id']}")

    # Only paused queues are excluded — a queue that was paused and resumed
    # carries paused=0 and must not be filtered out.
    tq.pause_queue("background")
    _set(tq, hi, status="pending", started_at=None)
    row = tq._dequeue()
    check("pausing the OTHER queue now yields the default task",
          bool(row) and row["task_id"] == hi,
          "None" if not row else row["queue_name"])


def part_llm14() -> None:
    print("\nLLM-14 — the worker clears its wakeup BEFORE it looks for work")
    src = inspect.getsource(TaskQueue._worker_loop)
    tree = ast.parse(src.lstrip().replace("\n    ", "\n"))  # de-indent the method
    events: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Attribute) and \
                    node.func.value.attr == "_wake_event":
                events.append(node.func.attr)
    check("_worker_loop touches the wake event exactly twice (clear, wait)",
          events == ["clear", "wait"], repr(events))

    # Live proof that a submitted task really starts at once. The 10-s
    # fallback timeout is the bound the lost wakeup used to hit; 3 s is far
    # below it and far above a healthy dispatch.
    tq = TaskQueue()
    # Fresh table and no pause left over from the parts above — the workers
    # below must see exactly one task, in a queue of its own.
    conn = tq._connect()
    try:
        conn.execute("DELETE FROM tasks")
        conn.execute("DELETE FROM queue_paused")
        conn.commit()
    finally:
        conn.close()
    started = threading.Event()

    def _handler(payload):
        started.set()
        return {"ok": True}

    tq.register_handler("smoke_wake", _handler)
    tq.start()
    t0 = time.monotonic()
    tq.submit("smoke_wake", {}, queue_name="smoke_wake_q")
    ran = started.wait(timeout=3.0)
    dt = time.monotonic() - t0
    tq._stopped = True
    tq._wake_event.set()
    check(f"a fresh task starts immediately ({dt * 1000:.0f} ms < 3000 ms)", ran,
          f"not started after {dt:.1f}s")


def main() -> int:
    print("smoke_task_queue_ops")
    print(f"  storage (throwaway): {_TMP}")
    try:
        part_llm3()
        part_llm4()
        part_llm14()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)

    print()
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print(f"  {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
