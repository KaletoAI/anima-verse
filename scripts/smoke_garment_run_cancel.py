"""A191 — a garment run in flight is cancellable, and so is a render from the queue panel.

Usage: ./.venv/bin/python scripts/smoke_garment_run_cancel.py   (no server, no world DB; a temp storage)

Cause (A191, Glut's Glutstulpen): ``garments.cancel_garment`` took only WAITING runs out of the queue and answered
409 "a running run cannot be cancelled"; the piece dialog showed Cancel only while the run waited. The queue panel's
Cancel of the render ("Bild generieren", a tracked row) only marked the row cancelled (``track_cancel``) — the render
went on and the garment run continued with its next attempt / step. Nothing tied either cancel to the GPU task or to
the hub job behind it.

Expected values derived by hand:
[C1] ``CancelScope``: a child of a cancelled parent reads set; a set child leaves its parent unset.
[C2] a scope set before the submit: ``submit_gpu_task`` raises ``GpuTaskCancelled`` and the callable never runs.
[C3] a running task under a scope: the callable sees the same scope (``CANCEL_SCOPE`` in the channel worker) and
     ``stage_cancel({})`` returns its check (False, then True after the cancel); cancelling the scope 0.3 s in ends
     the submit with ``GpuTaskCancelled`` within 4 s (the 1 s scope poll + the 2 s cancel poll of the worker),
     although the callable itself blocks for 10 s.
[C4] a PENDING task (the single slot held by another task) under a scope: cancelled -> ``GpuTaskCancelled``, its
     callable never runs.
[C5] ``stage_cancel`` with neither a scope nor a hub operation -> None (a normal run polls as before).
[C6] ``TaskQueue.track_cancel`` runs the row's ``on_track_cancel`` hook once; a dropped hook does not run.
[C7] ``cancel_garment`` on the item's run in flight: ``stopping`` True, 0 waiting runs, the job's scope is set (no
     409). Only a CPU refit beside the queue -> ``RunStarted``; no run -> ``LookupError``.
[C8] ``_is_cancel``: a RuntimeError raised from a ``GpuTaskCancelled`` -> True; a plain RuntimeError -> False.
     ``_cancelled_run`` -> ok False, cancelled True, retry_later True (``_note_outcome`` persists nothing).
"""
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="smoke_a191_cancel_"))
from app.core.provider import Provider  # noqa: E402
from app.core.provider_queue import ProviderQueue  # noqa: E402
from app.imagegen.backends._gateway_job import stage_cancel  # noqa: E402
from app.imagegen.base import CANCEL_SCOPE, CancelScope, GpuTaskCancelled  # noqa: E402

failed = []


def check(name, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + f"{name}: got {got!r} want {want!r}")
    if not ok:
        failed.append(name)


# [C1]
parent = CancelScope()
child = CancelScope(parent=parent)
child2 = CancelScope(parent=parent)
child2.cancel()
check("C1 set child leaves parent", parent.is_set(), False)
parent.cancel()
check("C1 parent cancels child", child.is_set(), True)

provider = Provider(name="b", type="image", api_base="", api_key="", max_concurrent=1, timeout=60)
provider.available = True
pq = ProviderQueue(provider, queue_name="backend:b", max_concurrent=1, chat_pause_enabled=False)


def submit(fn):
    return pq.submit_gpu_task("image_generation", 5, fn, agent_name="", label="b")


# [C2]
ran = []
scope = CancelScope()
scope.cancel()
token = CANCEL_SCOPE.set(scope)
try:
    submit(lambda: ran.append(1))
    check("C2 raises", "no exception", "GpuTaskCancelled")
except GpuTaskCancelled:
    check("C2 raises", "GpuTaskCancelled", "GpuTaskCancelled")
finally:
    CANCEL_SCOPE.reset(token)
check("C2 callable never ran", ran, [])

# [C3]
seen = {}
release = threading.Event()


def slow():
    seen["scope"] = CANCEL_SCOPE.get()
    seen["check"] = stage_cancel({})
    seen["before"] = seen["check"]() if seen["check"] else None
    release.wait(10)
    return [b"x"]


scope = CancelScope()
threading.Timer(0.3, scope.cancel).start()
token = CANCEL_SCOPE.set(scope)
t0 = time.monotonic()
try:
    submit(slow)
    outcome = "returned"
except GpuTaskCancelled:
    outcome = "GpuTaskCancelled"
finally:
    CANCEL_SCOPE.reset(token)
took = time.monotonic() - t0
check("C3 cancelled", outcome, "GpuTaskCancelled")
check("C3 within 4 s", took < 4.0, True)
check("C3 scope in the worker", seen.get("scope") is scope, True)
check("C3 stage_cancel before", seen.get("before"), False)
check("C3 stage_cancel after", bool(seen["check"]()) if seen.get("check") else None, True)
release.set()
time.sleep(0.3)

# [C4]
hold = threading.Event()
started = threading.Event()


def blocker():
    started.set()
    hold.wait(10)
    return [b"y"]


bt = threading.Thread(target=lambda: submit(blocker))
bt.start()
started.wait(5)
ran = []
scope = CancelScope()
threading.Timer(0.3, scope.cancel).start()
token = CANCEL_SCOPE.set(scope)
try:
    submit(lambda: ran.append(1))
    outcome = "returned"
except GpuTaskCancelled:
    outcome = "GpuTaskCancelled"
finally:
    CANCEL_SCOPE.reset(token)
hold.set()
bt.join(10)
check("C4 pending cancelled", outcome, "GpuTaskCancelled")
check("C4 callable never ran", ran, [])

# [C5]
check("C5 no scope, no op", stage_cancel({}), None)

# [C6]
from app.core.task_queue import get_task_queue  # noqa: E402
tq = get_task_queue()
calls = []
tid = tq.track_start("image_generation", "Bild generieren", agent_name="demo", provider="b")
tq.on_track_cancel(tid, lambda: calls.append(tid))
check("C6 cancelled", tq.track_cancel(tid), True)
check("C6 hook ran once", calls, [tid])
tid2 = tq.track_start("image_generation", "Bild generieren", agent_name="demo", provider="b")
tq.on_track_cancel(tid2, lambda: calls.append(tid2))
tq.drop_track_cancel(tid2)
tq.track_cancel(tid2)
check("C6 dropped hook", calls, [tid])

# [C7]
from app.core import garment_store as gs  # noqa: E402
from app.core import garments  # noqa: E402
gs.end = lambda *a, **k: None
gs.start = lambda *a, **k: None
job = garments._Job("item_x", None, None, False)
with garments._lock:
    garments._current["demo"] = job
res = garments.cancel_garment("demo", "item_x")
check("C7 stopping", (res["stopping"], res["cancelled"]), (True, 0))
check("C7 scope set", job.cancel_scope.is_set(), True)
with garments._lock:
    garments._current.pop("demo", None)
    side = garments._Job("item_x", "fit", None, False)
    garments._side["demo"] = {"item_x": side}
try:
    garments.cancel_garment("demo", "item_x")
    check("C7 beside refit", "no exception", "RunStarted")
except garments.RunStarted:
    check("C7 beside refit", "RunStarted", "RunStarted")
with garments._lock:
    garments._side.pop("demo", None)
try:
    garments.cancel_garment("demo", "item_x")
    check("C7 no run", "no exception", "LookupError")
except LookupError:
    check("C7 no run", "LookupError", "LookupError")

# [C8]
try:
    try:
        raise GpuTaskCancelled("x")
    except GpuTaskCancelled as inner:
        raise RuntimeError("wrapped") from inner
except RuntimeError as e:
    check("C8 chained cancel", garments._is_cancel(e), True)
check("C8 plain error", garments._is_cancel(RuntimeError("boom")), False)
r = garments._cancelled_run("demo", "item_x", "f", "ghost", [])
check("C8 result", (r["ok"], r["cancelled"], r["retry_later"]), (False, True, True))

print("FAILED: " + ", ".join(failed) if failed else "all passed")
sys.exit(1 if failed else 0)
