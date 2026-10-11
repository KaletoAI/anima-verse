#!/usr/bin/env python3
"""Smoke: per-task progress, recent history, and cancellation preservation.

Usage:
    ./.venv/bin/python scripts/smoke_task_queue_progress.py

Uses paths.init before importing TaskQueue, as the queue operations smoke does.
No workers start and no real database is touched. Expectations are hand-derived:
progress starts empty and is replaced; history includes pending and completed
tasks; cancelled rows survive both finish paths unchanged; seven rows yield the
five newest, with later insertions first when creation timestamps tie.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
_TMP = Path(tempfile.mkdtemp(prefix="smoke_task_queue_progress_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(_TMP / "clips")
from app.core import paths  # noqa: E402

paths.init(_TMP)
assert paths.get_storage_dir() == _TMP.resolve()
from app.core.task_queue import TaskQueue  # noqa: E402


def check(label: str, condition: bool) -> None:
    assert condition, label
    print(f"  ok   {label}")


def task_row(tq: TaskQueue, task_id: str) -> dict:
    with tq._connect() as conn:
        return dict(conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone())


def main() -> int:
    print("smoke_task_queue_progress")
    try:
        tq = TaskQueue()
        check("database isolated", tq._db_path == _TMP / "task_queue.db")
        tq.start = lambda: None
        tid = tq.submit("t", {})
        check("initial progress empty", tq.get_task_progress(tid) == {})
        tq.update_task_progress(tid, {"phase": "llm"})
        check("progress round trip", tq.get_task_progress(tid) == {"phase": "llm"})
        recent = tq.list_recent_tasks("t", 5)
        check("pending history and exact keys", len(recent) == 1 and recent[0] == {
            "task_id": tid, "status": "pending", "payload": {},
            "progress": {"phase": "llm"}, "error": "",
            "created_at": task_row(tq, tid)["created_at"], "completed_at": None,
        })
        id2 = tq.submit("t", {})
        check("new and unknown progress empty", tq.get_task_progress(id2) == {}
              and tq.get_task_progress("unknown") == {})
        tq.update_task_progress(tid, {"phase": "render", "label": "Tänzer"})
        check("progress replaces rather than merges", tq.get_task_progress(tid)
              == {"phase": "render", "label": "Tänzer"})
        tq.update_task_progress(tid, {})
        check("empty replacement", tq.get_task_progress(tid) == {})
        tq.update_task_progress("unknown", {"phase": "llm"})
        check("unknown update creates no task", tq.get_task_progress("unknown") == {})
        tq._finish_task(id2, "completed", result={"ok": True})
        completed = next(row for row in tq.list_recent_tasks("t") if row["task_id"] == id2)
        check("completed history", completed["status"] == "completed"
              and bool(completed["completed_at"]))
        id3 = tq.submit("t", {})
        check("cancel succeeds", tq.cancel_task(id3))
        cancelled = task_row(tq, id3)
        for status, retry in (("failed", False), ("failed", True), ("completed", False)):
            tq._finish_task(id3, status, error="x", retry=retry)
            check(f"cancelled row preserved ({status}, retry={retry})",
                  task_row(tq, id3) == cancelled)
        retry_id = tq.submit("retry", {}, max_retries=1)
        tq._finish_task(retry_id, "failed", error="x", retry=True)
        retried = task_row(tq, retry_id)
        check("ordinary retry still works", retried["status"] == "pending"
              and retried["retry_count"] == 1 and retried["error"] == "x")
        ids = [tq.submit("history", {"n": n}) for n in range(7)]
        with tq._connect() as conn:
            conn.execute("UPDATE tasks SET created_at='2000-01-01T00:00:00' WHERE task_type='history'")
            conn.execute("UPDATE tasks SET created_at='2001-01-01T00:00:00' WHERE task_id=?", (ids[0],))
            conn.commit()
        check("limit and timestamp/rowid ordering", [row["task_id"] for row in
              tq.list_recent_tasks("history", 5)] == [ids[0], ids[6], ids[5], ids[4], ids[3]])
        check("type filter and zero limit", tq.list_recent_tasks("absent") == []
              and tq.list_recent_tasks("history", 0) == [])
        for raw in ("", "broken", "[]", "null", '"text"'):
            with tq._connect() as conn:
                conn.execute("UPDATE tasks SET payload=?, progress=? WHERE task_id=?", (raw, raw, tid))
                conn.commit()
            row = next(row for row in tq.list_recent_tasks("t") if row["task_id"] == tid)
            check(f"defensive JSON decoding {raw!r}", tq.get_task_progress(tid) == {}
                  and row["payload"] == {} and row["progress"] == {})
        tq.update_task_progress(id2, {"phase": "llm", "path": Path("clip")})
        tq._init_db()
        check("migration can run again without losing progress", tq.get_task_progress(id2)
              == {"phase": "llm", "path": "clip"})
        with tq._connect() as conn:
            conn.execute("ALTER TABLE tasks DROP COLUMN progress")
            conn.commit()
        tq._init_db()
        check("old database gains empty progress without losing tasks",
              tq.get_task_progress(id2) == {} and task_row(tq, id2)["status"] == "completed")
        check("workers never started", tq._started is False and tq._workers == [])
        print("ALL CHECKS PASSED")
        return 0
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
