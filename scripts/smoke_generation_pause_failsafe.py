#!/usr/bin/env python3
"""The per-character generation pause fails safe (app/core/generation_pause.py) — review 09#2.

Usage:
    ./.venv/bin/python scripts/smoke_generation_pause_failsafe.py

Runs against a THROWAWAY storage + instance directory (``paths.init`` first) with the real ``TaskQueue`` (no
workers started); the replays (``_REPLAY``) are recorders, the push signal (``_notify``) and the garment
release are stubs — nothing renders, no hub, no server. Character ``Demo``.

Expected, by hand from the rules in the module (MAX_REPLAY_ATTEMPTS = 3):
[1] ``is_paused`` when the queue cannot be opened (``_queue`` raises) -> True (an unknown pause holds; the old
    code answered False and let automatic generation through). Not paused, queue readable -> False.
[2] Paused, ``TaskQueue.hold_trigger`` raising (the record write fails): ``hold(Demo, "auto_mesh", "L",
    {"a": 1})`` -> True (nothing starts); the waiting list shows ``trigger:auto_mesh`` labelled "L"; on Resume
    the ``auto_mesh`` replay runs once with {"a": 1}; afterwards nothing is held (queue or memory).
    (Old code: the trigger was only logged — the replay list after Resume was [].)
[3] Paused, ``hold(Demo, "build", "B", {"reason": "outfit_change"})`` recorded; the ``build`` replay raises:
    Resume 1 -> the replay was tried once and the trigger is held again with ``_replay_attempts`` 1 (the old
    code dropped it before the replay: held list []); pause + Resume 2 -> tried again, attempts 2; pause +
    Resume 3 -> tried a third time and dropped (3 = MAX): held list []. The replay always saw the payload
    WITHOUT the counter: {"reason": "outfit_change"}.
[4] Paused, the write failing again: ``hold(Demo, "mesh_part", "M")`` kept in memory; ``cancel(Demo,
    "trigger:mesh_part")`` removes it (waiting list empty); a second cancel -> LookupError.
Fails on 3f2ce338e in [1], [2], [3] and [4] (unreadable -> False; the failed record lost; the failing replay
dropped after one try; nothing to cancel).
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="generation-pause-failsafe-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import db
        db.init_schema()
        from app.core import garments, generation_pause as gp
        from app.core.task_queue import TaskQueue, get_task_queue

        A = "Demo"
        tq = get_task_queue()
        gp._notify = lambda: None
        garments.release_held = lambda _c: None
        replays = []
        failing = {"build"}

        def recorder(kind):
            def replay(c, payload):
                replays.append((kind, c, dict(payload)))
                if kind in failing:
                    raise RuntimeError(f"{kind} replay failed")
            return replay
        for kind in ("build", "model_refs", "auto_mesh", "mesh_part"):
            gp._REPLAY[kind] = recorder(kind)

        def held():
            return [(e["key"], e["payload"]) for e in tq.held_triggers(A)] + [
                (e["key"], e["payload"]) for e in getattr(gp, "_unrecorded_of", lambda _c: [])(A)]

        real_hold_trigger = TaskQueue.hold_trigger

        def broken_hold_trigger(self, *a, **kw):
            raise OSError("database is locked")

        print("[1] is_paused fails closed")
        real_queue = gp._queue
        gp._queue = lambda: (_ for _ in ()).throw(RuntimeError("queue cannot be opened"))
        check("unreadable -> paused", gp.is_paused(A), True)
        gp._queue = real_queue
        check("readable, not paused", gp.is_paused(A), False)

        print("[2] a failed record is kept and fires on Resume")
        gp.set_paused(A, True)
        TaskQueue.hold_trigger = broken_hold_trigger
        check("hold -> True", gp.hold(A, "auto_mesh", "L", {"a": 1}), True)
        TaskQueue.hold_trigger = real_hold_trigger
        check("waiting list", [(w["id"], w["label"]) for w in gp.waiting(A)], [("trigger:auto_mesh", "L")])
        gp.set_paused(A, False)
        check("replayed once", replays, [("auto_mesh", A, {"a": 1})])
        check("nothing held", held(), [])

        print("[3] a failing replay stays held, at most 3 attempts")
        replays.clear()
        gp.set_paused(A, True)
        check("hold build", gp.hold(A, "build", "B", {"reason": "outfit_change"}), True)
        gp.set_paused(A, False)
        check("resume 1: tried", replays, [("build", A, {"reason": "outfit_change"})])
        check("resume 1: held again", held(), [("build", {"reason": "outfit_change", "_replay_attempts": 1})])
        gp.set_paused(A, True)
        gp.set_paused(A, False)
        check("resume 2: tried twice", len(replays), 2)
        check("resume 2: held again", held(), [("build", {"reason": "outfit_change", "_replay_attempts": 2})])
        gp.set_paused(A, True)
        gp.set_paused(A, False)
        check("resume 3: tried three times", len(replays), 3)
        check("resume 3: dropped", held(), [])
        check("payload never shows the counter", {str(p) for _k, _c, p in replays}, {"{'reason': 'outfit_change'}"})

        print("[4] cancel of an in-memory trigger")
        gp.set_paused(A, True)
        TaskQueue.hold_trigger = broken_hold_trigger
        gp.hold(A, "mesh_part", "M")
        TaskQueue.hold_trigger = real_hold_trigger
        check("in the waiting list", [w["id"] for w in gp.waiting(A)], ["trigger:mesh_part"])
        gp.cancel(A, "trigger:mesh_part")
        check("cancelled", gp.waiting(A), [])
        try:
            gp.cancel(A, "trigger:mesh_part")
            check("second cancel", "no error", "LookupError")
        except LookupError:
            check("second cancel", "LookupError", "LookupError")
        gp.set_paused(A, False)
    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
