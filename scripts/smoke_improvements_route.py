#!/usr/bin/env python3
"""Smoke check for the improvements ADMIN ROUTE (plan-improvements-queue, task 5).

The route is a thin HTTP adapter over engine + store, so what is checked here
is exactly the adapter's own job: parsing, status codes and the shape the tab
consumes.  Every expectation is derived BY HAND from the task contract, never
recorded from a run.  A mini FastAPI app carries only this router, and
``require_admin`` is overridden — the auth itself is not this check's subject.

  1. ``GET /improvements/types`` lists the registered types with their param
     schema as ``ParamField.to_dict()`` gives it: the fake type has exactly one
     field, key "backend", required.

  2. ``POST /improvements`` creates AND scans in one go.  FakeType names two
     candidates, so the created row comes back with pending 2 and
     ``GET /improvements/{id}/steps`` lists both keys — without the immediate
     scan a fresh entry would show 0/0 until the next tick.

  2b. A missing required parameter is the USER's error, not a crash: the
     ``ValueError`` from ``validate`` becomes 400 with the field name in
     ``detail`` — that string is what the tab shows.

  3. ``POST /improvements/preview`` answers without creating anything:
     count 2, the two labels as sample, and ``GET /improvements`` still holds
     exactly the one entry from 2.

  4. ``GET /improvements/queue`` numbers the queue from 1 and carries the
     entry's label/type beside the candidate.  Two entries, A first (created
     first, so position 1), so the first row is A's.  ``recent`` is empty:
     nothing has finished.

  5. ``PATCH /improvements/order`` is the drag-and-drop.  Swapping to [B, A]
     must swap the head of the queue — that is the whole point of the entry
     order.

  6. ``PATCH /improvements/{id}`` renames, and new params re-validate and
     RE-SCAN: with the fake type reduced to one candidate, the patched entry
     has one pending step left, the vanished one closed as done.

  7. ``POST /{id}/pause`` takes an entry out of the queue view (status
     'paused'), ``resume`` puts it back ('open').  Paused, B contributes
     nothing to the queue, so only A's rows remain.

  8. ``POST /{id}/rescan`` reports the diff, ``POST /{id}/run-now`` sets the
     override flag the next tick reads (``engine._run_now``), and
     ``POST /{id}/steps/{key}/retry`` un-skips a step: pending with attempts 0.

  9. ``GET /improvements/status`` is the panel head: the settings, the gate
     reason and the pending total.  With the engine off the reason is
     "disabled".  ``PUT /improvements/settings`` writes both values and answers
     with what was STORED, so idle_minutes 0 comes back clamped to 1.

 10. Unknown ids are 404 on every id-addressed endpoint, and an unknown type is
     400 on create — the tab must never see a 500 for either.

 11. ``DELETE`` removes the entry and its steps; the running task of a step in
     flight is cancelled first, so no worker keeps working for an entry that is
     gone.  The queue row goes 'cancelled' and the last entry leaves the list.

     Two things the cancel must get right, and both are set up here.  First,
     OWNERSHIP: with A's step owed, deleting B may cancel nothing — the task is
     not B's.  Second, VISIBILITY under load: improvement steps run at priority
     90, behind everything a player waits for, and the admin panel's pending
     window is ``ORDER BY priority, created_at LIMIT 50``.  So 51 unrelated
     priority-20 tasks are queued in front of it — enough to push A's task out
     of that window entirely.  It is still cancelled, and none of the 51 is
     touched: the cancel asks for tasks BY TYPE and picks by payload, it does
     not sample a panel view.

 11b. A RUNNING task is not cancelled.  Its worker is inside ``apply()`` and
     keeps generating whatever the row says; flipping the row to 'cancelled'
     would only make ``has_pending_task`` report False, and the next tick would
     start a second generation on the same backend.  So with one running and
     one queued task of the same entry, DELETE cancels the queued one and
     leaves the running one alone — the deleted step row makes its later
     ``mark_result`` a no-op anyway (store: no row, no write).

 12. The user-activity stamp comes from ONE middleware, not from routes.  The
     mini app carries the same hook (``user_activity.activity_middleware_hook``)
     that ``app/server.py`` applies.  A POST to a non-improvements path is a
     player action → the stamp resets to 0; a GET is a poll → the stamp keeps
     its age; and a write to the improvements admin API itself is not player
     activity → the stamp keeps its age too, so watching the queue panel cannot
     push away the idle window the panel is waiting for.

Usage:  ./.venv/bin/python scripts/smoke_improvements_route.py
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="improvements-route-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="improvements-route-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import user_activity  # noqa: E402
from app.core.auth_dependency import require_admin  # noqa: E402
from app.core.improvements import engine, registry, store  # noqa: E402
from app.core.improvements.base import (Candidate, ImprovementType,  # noqa: E402
                                        ParamField)
from app.core.task_queue import get_task_queue  # noqa: E402
from app.routes import improvements as improvements_route  # noqa: E402

# No worker threads in a smoke: this run only inspects rows.
get_task_queue()._started = True

QUEUE_DB = STORAGE / "task_queue.db"

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


class FakeType(ImprovementType):
    """A drivable stand-in: the cases set ``candidates`` and read ``applied``."""

    id = "fake"
    label = "Fake improvement"
    params_schema = [ParamField("backend", "Backend", "text")]
    candidates = [("k1", "Zeta"), ("k2", "Alpha")]

    def find_candidates(self, params):
        return [Candidate(key, label) for key, label in FakeType.candidates]

    def is_done(self, candidate, params):
        return False

    def apply(self, candidate, params, task_id):
        return None


registry.clear()
registry.register(FakeType())

app = FastAPI()
app.include_router(improvements_route.router)
app.dependency_overrides[require_admin] = lambda: {"username": "demo",
                                                   "role": "admin"}


@app.middleware("http")
async def _activity_middleware(request, call_next):
    """The same two lines ``app/server.py`` runs — the rule itself lives in
    ``user_activity``, which is why this smoke can carry it without booting the
    real app."""
    user_activity.activity_middleware_hook(request.method, request.url.path)
    return await call_next(request)


@app.post("/play/say")
def _play_say():
    """A stand-in for any player write — the middleware never looks at the
    route, only at method and path."""
    return {"ok": True}


client = TestClient(app)


def set_task_status(task_id, status):
    """What the queue worker does when it picks a task up — this smoke runs
    without worker threads, so the row is moved by hand."""
    conn = sqlite3.connect(QUEUE_DB)
    try:
        conn.execute("UPDATE tasks SET status=? WHERE task_id=?",
                     (status, task_id))
        conn.commit()
    finally:
        conn.close()


def status_of(task_id):
    conn = sqlite3.connect(f"file:{QUEUE_DB}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT status FROM tasks WHERE task_id=?",
                           (task_id,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def task_rows(task_type=None):
    """The rows the queue really stored — read at the consumer (the queue DB),
    never taken from a submit return value."""
    conn = sqlite3.connect(f"file:{QUEUE_DB}?mode=ro", uri=True)
    try:
        return [dict(zip(("task_id", "status"), r)) for r in conn.execute(
            "SELECT task_id, status FROM tasks WHERE task_type=? "
            "ORDER BY created_at, rowid",
            (task_type or engine.TASK_TYPE,)).fetchall()]
    finally:
        conn.close()


# ── 1. the type catalogue ────────────────────────────────────────────────────
print("\n1. GET /improvements/types")
r = client.get("/improvements/types")
check("200", r.status_code, 200)
check("the fake type is listed with its label",
      [(t["id"], t["label"]) for t in r.json()], [("fake", "Fake improvement")])
check("…and its param schema comes as ParamField.to_dict()",
      r.json()[0]["params_schema"],
      [{"key": "backend", "label": "Backend", "kind": "text", "options": [],
        "required": True}])

# ── 2. create + immediate scan ───────────────────────────────────────────────
print("\n2. POST /improvements creates and scans")
r = client.post("/improvements", json={"type_id": "fake", "label": "A",
                                       "mode": "one_shot",
                                       "params": {"backend": "x"}})
check("200", r.status_code, 200)
A = r.json()["id"]
check("the row carries the normalised params", r.json()["params"],
      {"backend": "x"})
check("…and the scan already counted both candidates", r.json()["pending"], 2)
steps = client.get(f"/improvements/{A}/steps").json()
check("GET /{id}/steps lists them",
      sorted(s["candidate_key"] for s in steps), ["k1", "k2"])

print("\n2b. a missing parameter is a 400, not a crash")
r = client.post("/improvements", json={"type_id": "fake", "label": "bad",
                                       "mode": "one_shot", "params": {}})
check("400", r.status_code, 400)
check("…naming the field", "backend" in r.json()["detail"], True)
check("…and nothing was created",
      [i["label"] for i in client.get("/improvements").json()], ["A"])

# ── 3. preview ───────────────────────────────────────────────────────────────
print("\n3. POST /improvements/preview asks without creating")
r = client.post("/improvements/preview",
                json={"type_id": "fake", "params": {"backend": "x"}})
check("count + sample", r.json(), {"count": 2, "sample": ["Zeta", "Alpha"]})
check("…and still exactly one entry", len(client.get("/improvements").json()), 1)

# ── 4. the queue view ────────────────────────────────────────────────────────
print("\n4. GET /improvements/queue")
B = client.post("/improvements", json={"type_id": "fake", "label": "B",
                                       "mode": "standing",
                                       "params": {"backend": "y"}}).json()["id"]
q = client.get("/improvements/queue").json()
check("positions start at 1", [row["pos"] for row in q["queue"]], [1, 2, 3, 4])
check("…and the creation order leads",
      [row["improvement_id"] for row in q["queue"]], [A, A, B, B])
check("…each row carries its entry's label and type",
      (q["queue"][0]["label"], q["queue"][0]["type_id"]), ("A", "fake"))
check("nothing has finished yet", q["recent"], [])

# ── 5. reordering ────────────────────────────────────────────────────────────
print("\n5. PATCH /improvements/order")
check("200", client.patch("/improvements/order",
                          json={"ids": [B, A]}).status_code, 200)
q = client.get("/improvements/queue").json()
check("the swap moves the head of the queue",
      q["queue"][0]["improvement_id"], B)
check("…and the entry list follows",
      [i["label"] for i in client.get("/improvements").json()], ["B", "A"])

# ── 6. patching an entry ─────────────────────────────────────────────────────
print("\n6. PATCH /improvements/{id} renames, re-validates and re-scans")
FakeType.candidates = [("k1", "Zeta")]
r = client.patch(f"/improvements/{A}",
                 json={"label": "A2", "params": {"backend": "  z  "}})
check("200", r.status_code, 200)
check("the label and the trimmed params are stored",
      (r.json()["label"], r.json()["params"]), ("A2", {"backend": "z"}))
check("…and the rescan closed the candidate that vanished",
      {s["candidate_key"]: s["status"]
       for s in client.get(f"/improvements/{A}/steps").json()},
      {"k1": "pending", "k2": "done"})
r = client.patch(f"/improvements/{A}", json={"params": {}})
check("bad params are a 400", r.status_code, 400)

# ── 7. pause / resume ────────────────────────────────────────────────────────
print("\n7. POST /{id}/pause and /{id}/resume")
check("pause answers with the stored status",
      client.post(f"/improvements/{B}/pause").json()["status"], "paused")
check("…and B's steps leave the queue",
      {row["improvement_id"] for row in
       client.get("/improvements/queue").json()["queue"]}, {A})
check("resume puts it back",
      client.post(f"/improvements/{B}/resume").json()["status"], "open")
check("…with its steps", len(client.get("/improvements/queue").json()["queue"]), 3)

# ── 8. rescan / run-now / retry ──────────────────────────────────────────────
print("\n8. rescan, run-now, retry")
FakeType.candidates = [("k1", "Zeta"), ("k3", "Beta")]
check("rescan reports the diff",
      client.post(f"/improvements/{A}/rescan").json(),
      {"added": 1, "closed": 0})
engine._run_now.clear()
check("run-now arms the next tick",
      (client.post(f"/improvements/{A}/run-now").status_code,
       sorted(engine._run_now)), (200, [A]))
engine._run_now.clear()
store.mark_result(A, "k3", status="skipped", error="boom", count_attempt=True)
r = client.post(f"/improvements/{A}/steps/k3/retry")
check("retry un-skips the step", r.status_code, 200)
step = [s for s in client.get(f"/improvements/{A}/steps").json()
        if s["candidate_key"] == "k3"][0]
check("…with a clean slate",
      (step["status"], step["attempts"], step["error"]), ("pending", 0, ""))

# ── 9. status + settings ─────────────────────────────────────────────────────
print("\n9. GET /improvements/status and PUT /improvements/settings")
s = client.get("/improvements/status").json()
check("the engine is off by default",
      (s["enabled"], s["idle_minutes"], s["reason"]), (False, 15, "disabled"))
check("…and the pending total counts the open entries' steps",
      s["pending_total"], 4)
r = client.put("/improvements/settings",
               json={"enabled": True, "idle_minutes": 0})
check("settings answer with what was STORED, so 0 is clamped up",
      r.json(), {"enabled": True, "idle_minutes": 1})
check("…and status agrees",
      client.get("/improvements/status").json()["idle_minutes"], 1)

# ── 10. unknown ids and types ────────────────────────────────────────────────
print("\n10. unknown id → 404, unknown type → 400")
check("PATCH", client.patch("/improvements/nope", json={"label": "x"}).status_code, 404)
check("DELETE", client.delete("/improvements/nope").status_code, 404)
check("pause", client.post("/improvements/nope/pause").status_code, 404)
check("run-now", client.post("/improvements/nope/run-now").status_code, 404)
check("rescan", client.post("/improvements/nope/rescan").status_code, 404)
check("steps", client.get("/improvements/nope/steps").status_code, 404)
check("retry", client.post("/improvements/nope/steps/k1/retry").status_code, 404)
check("an unknown type on create",
      client.post("/improvements", json={"type_id": "ghost", "label": "x",
                                         "mode": "one_shot",
                                         "params": {}}).status_code, 400)
check("…and on preview",
      client.post("/improvements/preview",
                  json={"type_id": "ghost", "params": {}}).status_code, 400)

# ── 11. delete cancels what is in flight ─────────────────────────────────────
print("\n11. DELETE cancels the running task and takes the steps with it")
store.set_settings(True, 15)
client.patch("/improvements/order", json={"ids": [A, B]})   # A owes the step
user_activity._set_for_test(960)
submitted = engine.tick()["submitted"]
check("a step is owed", (submitted != "", len(task_rows())), (True, 1))
running = store.running_steps()[0]
check("…for A", running["improvement_id"], A)

# 51 unrelated tasks in front of it: one more than the admin panel's pending
# window holds, and all of them at the default priority 20, so A's priority-90
# task is the first thing that window drops.
for i in range(51):
    get_task_queue().submit("noise", {"i": i}, priority=20, deduplicate=False)
check("the panel's window no longer shows the owed step",
      [r for r in get_task_queue().get_status()["pending"]
       if r["task_type"] == engine.TASK_TYPE], [])

check("deleting the OTHER entry answers ok",
      client.delete(f"/improvements/{B}").status_code, 200)
check("…and cancels nothing — the task is not B's",
      [row["status"] for row in task_rows()], ["pending"])

check("DELETE answers ok", client.delete(f"/improvements/{A}").status_code, 200)
check("…the owed task is cancelled, window or no window",
      [row["status"] for row in task_rows()], ["cancelled"])
check("…and no unrelated task was touched",
      sorted({row["status"] for row in task_rows("noise")}), ["pending"])
check("…the steps are gone", client.get(f"/improvements/{A}/steps").status_code, 404)
check("…and the list is empty", client.get("/improvements").json(), [])

# ── 11b. a running task finishes, a queued one does not ──────────────────────
print("\n11b. DELETE cancels the QUEUED task and lets the running one finish")
FakeType.candidates = [("k1", "Solo")]
F = client.post("/improvements", json={"type_id": "fake", "label": "F",
                                       "mode": "one_shot",
                                       "params": {"backend": "x"}}).json()["id"]
user_activity._set_for_test(960)
running_task = engine.tick()["submitted"]
check("a step is owed", running_task != "", True)
set_task_status(running_task, "running")      # a worker picked it up
queued_task = get_task_queue().submit(
    engine.TASK_TYPE, {"improvement_id": F, "candidate_key": "k1"},
    queue_name=engine.QUEUE_NAME, priority=90, max_retries=0,
    deduplicate=False)
check("DELETE answers ok", client.delete(f"/improvements/{F}").status_code, 200)
check("the running step is left to finish", status_of(running_task), "running")
check("…and only the queued one is cancelled", status_of(queued_task),
      "cancelled")

# ── 12. the activity stamp ───────────────────────────────────────────────────
print("\n12. one middleware stamps the user's activity — no route does")
user_activity._set_for_test(300)
check("a GET is a poll, not activity",
      (client.get("/improvements").status_code,
       user_activity.seconds_since() >= 300.0), (200, True))
check("…and neither is a write to the improvements admin API",
      (client.post("/improvements/preview",
                   json={"type_id": "fake", "params": {"backend": "x"}}
                   ).status_code,
       user_activity.seconds_since() >= 300.0), (200, True))
check("a player's write resets the window",
      (client.post("/play/say").status_code,
       user_activity.seconds_since() < 1.0), (200, True))

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
