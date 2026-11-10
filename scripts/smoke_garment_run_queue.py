#!/usr/bin/env python3
"""An explicit garment run click is QUEUED behind the character's running
garment run, never refused (user decision 2026-11-10): ``garments.start_garment``
and the queue view ``garments.queue_state`` (app/core/garments.py).

Usage:
    ./.venv/bin/python scripts/smoke_garment_run_queue.py

Runs against a THROWAWAY storage directory (``paths.init`` before any world
module) — no world, no hub, no GPU, no server. Stubs: ``garments.check_run``
(every item valid) and ``garments.run_garment`` (a recorder that blocks the
first run of A on an event, raises for B, and notes A's run status while B
runs). Everything else is real: the FIFO, the worker thread, the in-memory
run status (``garment_store.start`` / ``end`` / ``status``).

Expected values (derived by hand from the rules in ``start_garment``):
[1] Idle character, start A -> {started True, queued False, position 0,
    behind None}; the recorder holds A's run; queue_state(Demo, A) ->
    {queue_running "A", queue [], queue_position None}.
[2] start B (another item) while A runs -> {started False, queued True,
    position 1, behind "A"}; B's status running_step "queued";
    queue_state(Demo, B) -> {queue_running "A", queue ["B"], queue_position 1}.
[3] The same click again (B, same steps/view/force) -> the same payload,
    queue still ["B"] (no second job).
[4] Explicit over a waiting default run: enqueue_garment(Demo, C) (the
    trigger path) -> queue ["B", "C"]; start_garment(C, steps "fit",
    force True) -> {started False, queued True, position 2, behind "A"}, queue
    still ["B", "C"], and the waiting job IS the trigger's job, now explicit
    (steps "fit", view None, force True) — the trigger's waiter gets the
    explicit run's result.
[5] An explicit run of the item IN FLIGHT (A, steps "mesh", force True) is
    appended, not merged: position 3, queue ["B", "C", "A"].
[6] Released: the runs go A (None, None, False), B (raises "boom"), C ("fit",
    None, True), A ("mesh", None, True) — B's failure does not hold the queue;
    at most one run at a time; while B runs, A's status is "queued" again
    (A waits for its second run). B's status: running_step None, failed error
    "boom". The trigger's job C is done with {ok True, item "C"}.
[7] Idle afterwards: queue_state(Demo) -> {queue_running None, queue []},
    no worker left (``_active`` empty), A's status running_step None.
"""
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="garment-run-queue-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import garments
        from app.core import garment_store as gs

        RUNS = []
        live = {"now": 0, "max": 0, "a_status_during_b": None}
        live_lock = threading.Lock()
        gate_a = threading.Event()

        def recorder(character_name, item_id, *, steps=None, view=None, force=False):
            with live_lock:
                live["now"] += 1
                live["max"] = max(live["max"], live["now"])
            try:
                first_a = item_id == "A" and not any(r[1] == "A" for r in RUNS)
                RUNS.append((character_name, item_id, steps, view, force))
                if first_a:
                    gate_a.wait(30)
                if item_id == "B":
                    live["a_status_during_b"] = gs.status(character_name, "A")["running_step"]
                    raise RuntimeError("boom")
                return {"ok": True, "item": item_id}
            finally:
                with live_lock:
                    live["now"] -= 1

        garments.check_run = lambda character_name, item_id, steps=None, view=None: None
        garments.run_garment = recorder

        def wait_for(pred, timeout=10.0):
            done = threading.Event()
            for _ in range(int(timeout / 0.02)):
                if pred():
                    return True
                done.wait(0.02)
            return False

        print("[1] idle: the click starts at once")
        check("start A", garments.start_garment("Demo", "A"),
              {"started": True, "queued": False, "position": 0, "behind": None})
        check("A runs", wait_for(lambda: bool(RUNS)), True)
        check("queue A", garments.queue_state("Demo", "A"),
              {"queue_running": "A", "queue": [], "queue_position": None})

        print("[2] another item while A runs: queued behind it")
        queued_b = {"started": False, "queued": True, "position": 1, "behind": "A"}
        check("start B", garments.start_garment("Demo", "B"), queued_b)
        check("B status", gs.status("Demo", "B")["running_step"], "queued")
        check("queue B", garments.queue_state("Demo", "B"),
              {"queue_running": "A", "queue": ["B"], "queue_position": 1})

        print("[3] the same click again: no second job")
        check("start B again", garments.start_garment("Demo", "B"), queued_b)
        check("queue still [B]", garments.queue_state("Demo")["queue"], ["B"])

        print("[4] explicit over a waiting default run")
        trigger_job = garments.enqueue_garment("Demo", "C")
        check("queue [B, C]", garments.queue_state("Demo")["queue"], ["B", "C"])
        check("explicit C", garments.start_garment("Demo", "C", steps="fit", force=True),
              {"started": False, "queued": True, "position": 2, "behind": "A"})
        check("queue still [B, C]", garments.queue_state("Demo")["queue"], ["B", "C"])
        with garments._lock:
            waiting = list(garments._queues.get("Demo") or [])
        check("the trigger's job, now explicit",
              (waiting[1] is trigger_job, trigger_job.steps, trigger_job.view, trigger_job.force),
              (True, "fit", None, True))

        print("[5] explicit run of the item in flight: appended")
        check("explicit A", garments.start_garment("Demo", "A", steps="mesh", force=True),
              {"started": False, "queued": True, "position": 3, "behind": "A"})
        check("queue [B, C, A]", garments.queue_state("Demo")["queue"], ["B", "C", "A"])

        print("[6] released: FIFO order, B's failure does not hold the queue")
        gate_a.set()
        check("idle", garments.wait_idle(30), True)
        check("runs", RUNS, [("Demo", "A", None, None, False), ("Demo", "B", None, None, False),
                             ("Demo", "C", "fit", None, True), ("Demo", "A", "mesh", None, True)])
        check("serial", live["max"], 1)
        check("A waits again while B runs", live["a_status_during_b"], "queued")
        st_b = gs.status("Demo", "B")
        check("B failed", (st_b["running_step"], (st_b["failed"] or {}).get("error")), (None, "boom"))
        check("trigger job done", (trigger_job.done.is_set(), trigger_job.result), (True, {"ok": True, "item": "C"}))

        print("[7] idle afterwards")
        check("queue empty", garments.queue_state("Demo"), {"queue_running": None, "queue": []})
        with garments._lock:
            check("no worker", (set(garments._active), dict(garments._current)), (set(), {}))
        check("A idle", gs.status("Demo", "A")["running_step"], None)

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
