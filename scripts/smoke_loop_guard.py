#!/usr/bin/env python3
"""Loop guard: a world-DB access on the server's event loop is counted, never one from a thread.

Usage: ./.venv/bin/python scripts/smoke_loop_guard.py
Storage is a temp dir, initialised before any world-DB module is imported.

Expected numbers, derived by hand:
  [G1] no loop registered: 3 x get_connection -> flush() == []
  [G2] loop registered, 2 x get_connection ON the loop, 5 x inside asyncio.to_thread
       -> one line, n=2 (the thread's five never count)
  [G3] the line is "loop_sync n=2 <key>=2" and the key names this script's coroutine
       as the entry: it has no "/app/" frame, so the key is "(no app frame)"
  [G4] strict mode: get_connection on the loop raises LoopBlockingCall, to_thread does not
  [G5] allowed(): inside the block nothing is counted and strict does not raise
  [G6] 17 different keys with counts 17..1 -> 15 named, other = 2 + 1 = 3, n = 153
  [G7] after unregister(): counts nothing again
  [G8] strict mode records the violation BEFORE raising: a caller that swallows the
       exception (as the agent loop's predicates do) still leaves violations == 1 entry
       that starts with "db:"
  [G9] note_lag(frame of this script): no "/app/" frame -> key "lag:(no app frame)>smoke_loop_guard:<function>",
       counted once -> line "loop_sync n=1 lag:(no app frame)>smoke_loop_guard:scenario=1"
  [G10] the task queue's own connection is a choke point too: TaskQueue._connect on the
        loop in strict mode appends a violation that starts with "tq:"
"""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths

failed = 0


def ok(label, cond, detail=""):
    global failed
    print(("  OK  " if cond else "  FAIL ") + label + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failed += 1


with tempfile.TemporaryDirectory() as tmp:
    paths.init(Path(tmp))
    from app.core import db, loop_guard

    for _ in range(3):
        db.get_connection()
    ok("[G1] nothing counted without a registered loop", loop_guard.flush() == [])

    async def scenario():
        loop_guard.register_server_loop()
        db.get_connection()
        db.get_connection()

        def in_thread():
            for _ in range(5):
                db.get_connection()
        await asyncio.to_thread(in_thread)
        lines = loop_guard.flush()
        ok("[G2] one line, n=2", len(lines) == 1 and lines[0].startswith("loop_sync n=2 "), str(lines))
        ok("[G3] line format", lines == ["loop_sync n=2 (no app frame)=2"], str(lines))

        loop_guard.strict(True)
        try:
            db.get_connection()
            raised = False
        except loop_guard.LoopBlockingCall:
            raised = True
        ok("[G4] strict raises on the loop", raised)
        try:
            await asyncio.to_thread(db.get_connection)
            thread_ok = True
        except loop_guard.LoopBlockingCall:
            thread_ok = False
        ok("[G4] strict does not raise in a thread", thread_ok)
        with loop_guard.allowed():
            try:
                db.get_connection()
                allowed_ok = True
            except loop_guard.LoopBlockingCall:
                allowed_ok = False
        ok("[G5] allowed() passes in strict mode", allowed_ok)
        loop_guard.strict(False)
        with loop_guard.allowed():
            db.get_connection()
        ok("[G5] allowed() counts nothing", loop_guard.flush() == [])

        for i in range(17):
            loop_guard._counts[f"k{i:02d}"] = 17 - i
        line = loop_guard.flush()[0]
        ok("[G6] n = 153", line.startswith("loop_sync n=153 "), line)
        ok("[G6] 15 named, other=3", line.endswith(" k14=3 other=3") and line.count("=") == 17, line)

        loop_guard.strict(True)
        loop_guard.clear_violations()
        try:
            db.get_connection()
        except Exception:
            pass   # what a swallowing caller does
        ok("[G8] a swallowed raise still leaves one violation",
           len(loop_guard.violations) == 1 and loop_guard.violations[0].startswith("db:"),
           str(loop_guard.violations))
        from app.core.task_queue import TaskQueue
        loop_guard.clear_violations()
        try:
            TaskQueue._connect(TaskQueue.__new__(TaskQueue))
        except Exception:
            pass
        ok("[G10] task-queue connect is watched",
           len(loop_guard.violations) == 1 and loop_guard.violations[0].startswith("tq:"),
           str(loop_guard.violations))
        loop_guard.clear_violations()
        loop_guard.strict(False)

        loop_guard.flush()
        loop_guard.note_lag(sys._getframe(), 250.0)
        lines = loop_guard.flush()
        ok("[G9] lag note", lines == ["loop_sync n=1 lag:(no app frame)>smoke_loop_guard:scenario=1"], str(lines))

        loop_guard.unregister()
        db.get_connection()
        ok("[G7] nothing counted after unregister", loop_guard.flush() == [])

    asyncio.run(scenario())

print("FAILED" if failed else "Loop guard checks passed")
sys.exit(1 if failed else 0)
