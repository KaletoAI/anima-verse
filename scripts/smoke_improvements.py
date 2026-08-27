#!/usr/bin/env python3
"""Smoke check for the improvements data layer (plan-improvements-queue, task 1).

What it proves — every expectation below is derived BY HAND from the task
contract, never recorded from a run:

  1. Ordering is the queue's own, not SQLite's insertion accident.
     ``create`` sets ``position = max(position) + 1``, so the first row is 1
     and the second 2; ``list_all`` orders by position, hence [A, B].
     ``set_order([B, A])`` writes position = index (0, 1) → [B, A].

  2. A scan is a DIFF, not a rewrite.  Scanning A with the candidates
     ("k1", "Zeta") and ("k2", "Alpha") inserts both as pending →
     {"added": 2, "closed": 0}.  ``next_pending`` orders by LABEL first, so
     "Alpha" (k2) is next even though it was inserted second.  A second scan
     that lists only k1 must CLOSE k2 — the subject vanished from the
     candidate list, which can only mean it is done → {"added": 0, "closed": 1}
     and k2.status == "done".  Counters afterwards: pending 1 (k1), done 1
     (k2), everything else 0 — and ``get`` reports the same counters as
     ``list_all``.

  3. Attempts count attempts, not results.  ``mark_running`` puts k1 into
     'running' — which ``list_steps`` sorts to the front, ahead of the
     label order ("Zeta" before "Alpha").  A busy retry
     (status="pending", count_attempt=True) leaves the step runnable but
     raises attempts to 1; a give-up (status="skipped", count_attempt=True)
     makes it 2 and stamps finished_at + duration_s (from started_at, so a
     real, non-negative number).

  3b. ``retry_step`` is the user's undo of a skip: status back to 'pending',
     attempts back to 0, error cleared, finished_at/duration_s gone.

  3c. A crashed server leaves 'running' rows behind:
     ``reset_running_to_pending`` returns the number it rescued (1) and the
     step is runnable again.  With k1 pending and B stepless,
     ``pending_count_by_type`` is {"fake": 1}.

  3d. After a real completion (running → done) A holds two done steps, the
     ONLY one with a duration is k1, so ``avg_duration_by_type`` has exactly
     the key "fake", and ``recent_done`` lists both closed steps (k1, k2).
     Both finish inside the same wall-clock second, so only the SET of keys
     is asserted, never their order.

  4. Settings live in world_kv as text.  Untouched they read
     {"enabled": False, "idle_minutes": 15}; ``set_settings(True, 0)`` clamps
     to the lower bound 1.

  5. The idle stamp is monotonic and suppressible.  After
     ``_set_for_test(100)`` the stamp is 100 s old (and under a second of
     test runtime, so < 101).  A ``touch()`` inside ``suppressed()`` — what an
     improvement step's own generation does — must NOT reset it; a touch
     outside must.

  6. The registry is a plain name→type map, and the base ``validate`` refuses
     a missing required parameter with a ValueError naming the field.

  7. ``update`` re-encodes params to JSON on write and decodes on read;
     ``delete`` takes the steps with it.

PART 2 — the idle engine (task 2).  Settings for the whole part:
enabled = True, idle_minutes = 15, so the idle threshold is 15 * 60 = 900 s.
Every task row below is read back out of ``STORAGE/task_queue.db``, never
taken from the ``submit`` call.

  8. The idle gate is the threshold, not a mood.  840 s < 900 s → the tick
     submits nothing and marks nothing running; 960 s > 900 s → exactly ONE
     task row exists, of type ``improvement_step``, priority 90, queue
     "improvements", ``max_retries`` 0.  Which step?  ``list_steps`` orders by
     LABEL, and A's candidates are ("k1", "Zeta") + ("k2", "Alpha") — so the
     payload names k2, and k2 alone is 'running'.

  9. ONE step at a time.  The row from 8 is still pending, so
     ``has_pending_task`` is True and the next tick returns "" (reason
     "busy") without adding a second row.

 10. A finished step is done, counted and timed.  ``handle_step`` runs the
     type's ``apply`` (recorded in ``FakeType.applied`` with the task id),
     marks k2 done with a real duration (started_at was stamped in 8) and
     raises ``done_count`` to 1.  A ``touch()`` right after — the user came
     back — closes the window again: the next tick submits nothing.

 11. A one_shot closes itself.  C has both candidates; after two
     ``handle_step`` calls nothing is pending or running any more, so its
     status is 'done' and it drops out of ``ordered_queue`` (which shows only
     'open' entries) — leaving A, whose k1 is still pending.

 12. A standing entry rescans on the clock.  B is scanned once with the single
     candidate k7; with ``last_scan_at`` set 700 s back (>= SCAN_INTERVAL_S =
     600) the next tick rescans it — ``scanned`` 1 — and the newly listed k9
     lands as pending beside k7.  With the stamp 100 s back (< 600) the tick
     rescans nothing: ``scanned`` 0.

 13. A defect costs an attempt.  MAX_ATTEMPTS = 2: the first raise leaves the
     step runnable with attempts 1, the second gives up — status 'skipped',
     attempts 2 — and raises the improvement's ``failed_count`` to 1.

 14. Busy is load, not a defect.  A ``BackendBusyError`` leaves the step
     pending with attempts still 0, so a busy backend can never burn a
     candidate's two attempts.

 15. ``ordered_queue`` is the ENTRY order, positions numbered from 1.
     ``set_order([B, A])`` puts B first, so the queue reads
     [(1, B/k9), (2, A/k1)] — k7 is skipped and k2 done, neither shows.
     Pausing B removes its rows, and A becomes position 1.

 16. The three gates and the one-shot override.  Disabled →
     (False, "disabled"); enabled but frozen → (False, "frozen"); thawed but
     the user active 60 s ago → (False, "active").  ``request_run_now(A)``
     makes the NEXT tick submit A's k1 anyway; while that row is owed the
     status reason is "busy" and ``running_step`` is k1.  After the step is
     handled the flag is spent: with the user still 60 s active the next tick
     submits "" again, and A — its last step done — has closed itself.
     ``next_allowed_in_s`` is 900 - 60 = 840, minus the test's own runtime,
     hence the 830..840 window.

 17. A restart leaves 'running' rows behind.  With B's k9 marked running and
     every ``improvement_step`` row deleted from the queue DB (what a restart
     that never finished looks like), the next tick makes k9 pending again —
     and, the user still being active, queues nothing in the same breath.

 18. A run-now flag can never get stuck.  C is 'done' and has no pending step,
     so the tick it overrides finds nothing: reason "empty".  The flag is
     spent there and then, so the tick after it reads the ordinary idle gate
     again — reason "active", not a second futile walk of the queue.

 19. A one_shot whose scan finds NOTHING is done on the spot.  D is created
     and scanned against an empty candidate list: 0 added, 0 closed, no steps
     at all — so the "0 pending and 0 running" rule closes it right there.
     Without the close in ``scan`` it would sit 'open' 0/0 forever: the only
     other close happens after a step finishes, and D has no step to finish.

 20. A step whose TYPE is gone clears the head of the queue.  E's k5 is marked
     running (what the worker sees), then the registry is emptied — a package
     that went away.  ``handle_step`` must not leave the step 'running': the
     next tick would rescue it (17), resubmit it, and since only ONE
     improvement_step may be owed, every other entry would queue behind a step
     that can never run.  So the step goes 'skipped' with the type id in its
     error, E's failed_count is 1, and the next tick — user idle 960 s, so the
     gate is wide open — submits nothing and has never queued a row for E.

Usage:  ./.venv/bin/python scripts/smoke_improvements.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="improvements-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="improvements-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import user_activity  # noqa: E402
from app.core.improvements import registry, store  # noqa: E402
from app.core.improvements.base import (Candidate, ImprovementType,  # noqa: E402
                                        ParamField)
from app.core.task_queue import get_task_queue  # noqa: E402

# No worker threads in a smoke: this run only inspects rows.
get_task_queue()._started = True

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


def raises(label, exc_type, fn, contains=""):
    """``fn`` must raise ``exc_type``; with ``contains`` the message must also
    carry that text — the field name is what the admin UI shows the user."""
    global CHECKED
    CHECKED += 1
    try:
        fn()
    except exc_type as e:
        if contains and contains not in str(e):
            print(f"  FAIL {label}: {str(e)[:160]!r} does not carry "
                  f"{contains!r}")
            FAILURES.append(label)
            return
        print(f"  OK  {label}: {exc_type.__name__}({str(e)[:120]!r})")
        return
    except Exception as e:  # noqa: BLE001 — anything else is the defect
        print(f"  FAIL {label}: {type(e).__name__}({e})")
        FAILURES.append(label)
        return
    print(f"  FAIL {label}: no exception")
    FAILURES.append(label)


def counters(row):
    return {k: row[k] for k in
            ("pending", "running", "done", "failed", "skipped")}


# ── 1. create / order ────────────────────────────────────────────────────────
print("\n1. create + ordering")
a = store.create("fake", "A", {}, "one_shot")
b = store.create("fake", "B", {}, "continuous")
A, B = a["id"], b["id"]
check("first improvement gets position 1", a["position"], 1)
check("second improvement gets position 2", b["position"], 2)
check("list_all orders by position", [r["label"] for r in store.list_all()],
      ["A", "B"])
store.set_order([B, A])
check("set_order rewrites the order", [r["label"] for r in store.list_all()],
      ["B", "A"])
check("a fresh improvement has no steps", counters(store.get(A)),
      {"pending": 0, "running": 0, "done": 0, "failed": 0, "skipped": 0})

# ── 2. scan = diff ───────────────────────────────────────────────────────────
print("\n2. replace_steps_scan is a diff")
check("first scan adds both candidates",
      store.replace_steps_scan(A, [("k1", "Zeta"), ("k2", "Alpha")]),
      {"added": 2, "closed": 0})
check("next_pending follows the label order",
      store.next_pending(A)["candidate_key"], "k2")
check("re-scanning the same list changes nothing",
      store.replace_steps_scan(A, [("k1", "Zeta"), ("k2", "Alpha")]),
      {"added": 0, "closed": 0})
check("a vanished candidate is closed",
      store.replace_steps_scan(A, [("k1", "Zeta")]),
      {"added": 0, "closed": 1})
check("…as done", {s["candidate_key"]: s["status"]
                   for s in store.list_steps(A)},
      {"k1": "pending", "k2": "done"})
check("get() counts the steps", counters(store.get(A)),
      {"pending": 1, "running": 0, "done": 1, "failed": 0, "skipped": 0})
check("…and list_all() counts them the same way",
      counters([r for r in store.list_all() if r["id"] == A][0]),
      counters(store.get(A)))

# ── 3. attempts + result stamps ──────────────────────────────────────────────
print("\n3. mark_running / mark_result")
store.mark_running(A, "k1")
check("a running step sorts ahead of the labels",
      [s["candidate_key"] for s in store.list_steps(A)], ["k1", "k2"])
check("running_steps sees it",
      [s["candidate_key"] for s in store.running_steps()], ["k1"])
check("counters follow", counters(store.get(A)),
      {"pending": 0, "running": 1, "done": 1, "failed": 0, "skipped": 0})

store.mark_result(A, "k1", status="pending", error="x", count_attempt=True)
step = [s for s in store.list_steps(A) if s["candidate_key"] == "k1"][0]
check("a busy retry stays runnable",
      (step["status"], step["attempts"], step["error"], step["finished_at"]),
      ("pending", 1, "x", None))

store.mark_result(A, "k1", status="skipped", error="gave up",
                  count_attempt=True)
step = [s for s in store.list_steps(A) if s["candidate_key"] == "k1"][0]
check("giving up counts a second attempt",
      (step["status"], step["attempts"]), ("skipped", 2))
check("…and stamps a finish", step["finished_at"] is not None, True)
check("…with a duration", isinstance(step["duration_s"], float)
      and step["duration_s"] >= 0.0, True)

print("\n3b. retry_step undoes a skip")
store.retry_step(A, "k1")
step = [s for s in store.list_steps(A) if s["candidate_key"] == "k1"][0]
check("the skipped step is runnable again",
      (step["status"], step["attempts"], step["error"],
       step["finished_at"], step["duration_s"]),
      ("pending", 0, "", None, None))

print("\n3c. reset_running_to_pending rescues a crash")
store.mark_running(A, "k1")
check("it reports what it rescued", store.reset_running_to_pending(), 1)
check("…and the step is pending again", store.next_pending(A)["candidate_key"],
      "k1")
check("pending_count_by_type", store.pending_count_by_type(), {"fake": 1})

print("\n3d. a real completion")
store.mark_running(A, "k1")
store.mark_result(A, "k1", status="done", count_attempt=True)
check("both steps are done now", counters(store.get(A)),
      {"pending": 0, "running": 0, "done": 2, "failed": 0, "skipped": 0})
check("only the worked step carries a duration",
      sorted(store.avg_duration_by_type().keys()), ["fake"])
check("recent_done lists both closed steps",
      sorted(s["candidate_key"] for s in store.recent_done()), ["k1", "k2"])
check("…with the improvement it belongs to",
      sorted({(s["label"], s["type_id"]) for s in store.recent_done()}),
      [("A", "fake")])
check("nothing is pending any more", store.next_pending(A), None)

# ── 4. settings ──────────────────────────────────────────────────────────────
print("\n4. settings")
check("defaults", store.get_settings(), {"enabled": False, "idle_minutes": 15})
store.set_settings(True, 0)
check("idle_minutes is clamped up", store.get_settings(),
      {"enabled": True, "idle_minutes": 1})
store.set_settings(False, 99999)
check("…and down", store.get_settings(),
      {"enabled": False, "idle_minutes": 1440})

# ── 5. user activity ─────────────────────────────────────────────────────────
print("\n5. user activity stamp")
user_activity._set_for_test(100)
check("the stamp ages", 100.0 <= user_activity.seconds_since() < 101.0, True)
check("nothing is suppressed by default", user_activity.is_suppressed(), False)
with user_activity.suppressed():
    check("inside suppressed()", user_activity.is_suppressed(), True)
    user_activity.touch()
check("a suppressed touch does not reset the idle window",
      100.0 <= user_activity.seconds_since() < 101.0, True)
check("suppression ends with the block", user_activity.is_suppressed(), False)
user_activity.touch()
check("a real touch does", user_activity.seconds_since() < 1.0, True)

# ── 6. registry + validate ───────────────────────────────────────────────────
print("\n6. registry + type contract")


class FakeType(ImprovementType):
    id = "fake"
    label = "Fake improvement"
    params_schema = [
        ParamField("backend", "Backend", "text"),
        ParamField("kind", "Kind", "enum",
                   options=[{"value": "a", "label": "A"}], required=False),
    ]

    def find_candidates(self, params):
        return [Candidate("k1", "Zeta")]

    def is_done(self, candidate, params):
        return False


registry.clear()
registry.register(FakeType())
check("register + get", registry.get("fake").label, "Fake improvement")
check("list_types", [t.id for t in registry.list_types()], ["fake"])
check("an unknown id is None", registry.get("nope"), None)
raises("register refuses a type without an id", ValueError,
       lambda: registry.register(ImprovementType()), "id")

t = registry.get("fake")
check("validate normalises", t.validate({"backend": "  x  "}),
      {"backend": "x", "kind": ""})
raises("validate refuses a missing required parameter", ValueError,
       lambda: t.validate({}), "backend")
raises("validate refuses a value outside the options", ValueError,
       lambda: t.validate({"backend": "x", "kind": "z"}), "kind")
raises("find_candidates is abstract", NotImplementedError,
       lambda: ImprovementType().find_candidates({}))

# ── 7. update + delete ───────────────────────────────────────────────────────
print("\n7. update + delete")
store.update(A, label="A2", params={"backend": "x"}, status="paused")
row = store.get(A)
check("update writes through", (row["label"], row["params"], row["status"]),
      ("A2", {"backend": "x"}, "paused"))
store.delete(A)
check("delete removes the improvement",
      [r["label"] for r in store.list_all()], ["B"])
check("…and its steps", store.list_steps(A), [])

# ═══════════════════════════════════════════════════════════════════════════
# PART 2 — the idle engine
# ═══════════════════════════════════════════════════════════════════════════
import json  # noqa: E402
import sqlite3  # noqa: E402
from datetime import timedelta  # noqa: E402

from app.core.improvements import engine  # noqa: E402
from app.core.timeutils import utc_now  # noqa: E402
from app.imagegen.base import BackendBusyError  # noqa: E402
from app.models.world import set_world_frozen  # noqa: E402

QUEUE_DB = STORAGE / "task_queue.db"


def step_tasks():
    """The improvement_step rows the queue really stored — asked at the
    consumer (the queue DB), never taken from the ``submit`` return value."""
    conn = sqlite3.connect(f"file:{QUEUE_DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT task_id, priority, queue_name, max_retries, status, payload"
            " FROM tasks WHERE task_type=? ORDER BY created_at, rowid",
            (engine.TASK_TYPE,)).fetchall()
    finally:
        conn.close()
    return [{"task_id": r[0], "priority": r[1], "queue_name": r[2],
             "max_retries": r[3], "status": r[4], "payload": json.loads(r[5])}
            for r in rows]


def worker_done(task_id):
    """What the queue worker does once the handler returned — this smoke runs
    without worker threads, so the row is closed by hand."""
    conn = sqlite3.connect(QUEUE_DB)
    try:
        conn.execute("UPDATE tasks SET status='completed' WHERE task_id=?",
                     (task_id,))
        conn.commit()
    finally:
        conn.close()


def drop_step_tasks():
    """A restart: the queue rows are gone, the 'running' step rows are not."""
    conn = sqlite3.connect(QUEUE_DB)
    try:
        conn.execute("DELETE FROM tasks WHERE task_type=?", (engine.TASK_TYPE,))
        conn.commit()
    finally:
        conn.close()


def step_of(improvement_id, key):
    return [s for s in store.list_steps(improvement_id)
            if s["candidate_key"] == key][0]


def ago(seconds):
    return (utc_now() - timedelta(seconds=seconds)).isoformat(timespec="seconds")


class FakeType(ImprovementType):  # noqa: F811 — part 2's own, drivable stand-in
    """Candidate list and failure mode are class state the cases drive."""

    id = "fake"
    label = "Fake improvement"
    params_schema = []
    candidates = [("k1", "Zeta"), ("k2", "Alpha")]
    behaviour = "ok"          # "ok" | "fail" | "busy"
    applied = []              # [(candidate_key, task_id)] in call order

    def find_candidates(self, params):
        return [Candidate(key, label) for key, label in FakeType.candidates]

    def is_done(self, candidate, params):
        return False

    def apply(self, candidate, params, task_id):
        FakeType.applied.append((candidate.key, task_id))
        if FakeType.behaviour == "fail":
            raise RuntimeError("boom")
        if FakeType.behaviour == "busy":
            raise BackendBusyError("gpu busy")


registry.clear()
registry.register(FakeType())
store.delete(B)                       # part 1's leftover — start from empty
store.set_settings(True, 15)
set_world_frozen(False)

# ── 8. the idle gate ─────────────────────────────────────────────────────────
print("\n8. tick submits one step, and only once the user is idle")
A = store.create("fake", "A", {}, "one_shot")["id"]
check("a fresh one_shot is scanned on demand", engine.scan(A),
      {"added": 2, "closed": 0})

user_activity._set_for_test(840)
result = engine.tick()
check("840 s is short of the 900 s window",
      (result["submitted"], result["reason"]), ("", "active"))
check("…and nothing was marked running", store.get(A)["running"], 0)

user_activity._set_for_test(960)
result = engine.tick()
tasks = step_tasks()
check("960 s submits exactly one step", len(tasks), 1)
check("…the label order picks Alpha (k2)", tasks[0]["payload"],
      {"improvement_id": A, "candidate_key": "k2"})
check("…priority 90, queue 'improvements', no retries",
      (tasks[0]["priority"], tasks[0]["queue_name"], tasks[0]["max_retries"]),
      (90, "improvements", 0))
check("…and tick returns that task id", result["submitted"], tasks[0]["task_id"])
check("…only that step is running",
      {s["candidate_key"]: s["status"] for s in store.list_steps(A)},
      {"k2": "running", "k1": "pending"})

# ── 9. one step at a time ────────────────────────────────────────────────────
print("\n9. one step at a time")
result2 = engine.tick()
check("a second tick waits for the owed row",
      (result2["submitted"], result2["reason"]), ("", "busy"))
check("…and adds no row", len(step_tasks()), 1)

# ── 10. a finished step ──────────────────────────────────────────────────────
print("\n10. handle_step finishes the step")
TID = result["submitted"]
worker_done(TID)
check("the handler reports success",
      engine.handle_step({"improvement_id": A, "candidate_key": "k2",
                          "_task_id": TID}), {"ok": True})
step = step_of(A, "k2")
check("the step is done", step["status"], "done")
check("…with a real duration",
      isinstance(step["duration_s"], float) and step["duration_s"] >= 0.0, True)
check("…counted on the improvement", store.get(A)["done_count"], 1)
check("…and the type really ran, with the task id", FakeType.applied[-1],
      ("k2", TID))
user_activity.touch()
check("a user action closes the window again", engine.tick()["submitted"], "")

# ── 11. a one_shot closes itself ─────────────────────────────────────────────
print("\n11. a one_shot with every step done closes itself")
C = store.create("fake", "C", {}, "one_shot")["id"]
engine.scan(C)
for candidate_key in ("k2", "k1"):
    engine.handle_step({"improvement_id": C, "candidate_key": candidate_key,
                        "_task_id": ""})
check("its status is done", store.get(C)["status"], "done")
check("…and it leaves the queue view",
      [r["improvement_id"] for r in engine.ordered_queue()], [A])

# ── 12. a standing entry rescans ─────────────────────────────────────────────
print("\n12. a standing entry rescans on the clock")
FakeType.candidates = [("k7", "Beta")]
B = store.create("fake", "B", {}, "standing")["id"]
engine.scan(B)
store.update(B, last_scan_at=ago(700))
FakeType.candidates = [("k7", "Beta"), ("k9", "Alpha")]
user_activity.touch()                 # keep this tick to its scan
check("a stamp older than SCAN_INTERVAL_S rescans", engine.tick()["scanned"], 1)
check("…and the new candidate lands as pending",
      {s["candidate_key"]: s["status"] for s in store.list_steps(B)},
      {"k7": "pending", "k9": "pending"})
store.update(B, last_scan_at=ago(100))
check("a fresh stamp is left alone", engine.tick()["scanned"], 0)

# ── 13. a defect costs an attempt ────────────────────────────────────────────
print("\n13. a defect costs an attempt, twice is a skip")
FakeType.behaviour = "fail"
result = engine.handle_step({"improvement_id": B, "candidate_key": "k7",
                             "_task_id": ""})
check("the error is reported", "boom" in (result.get("error") or ""), True)
step = step_of(B, "k7")
check("the first attempt stays runnable", (step["status"], step["attempts"]),
      ("pending", 1))
engine.handle_step({"improvement_id": B, "candidate_key": "k7", "_task_id": ""})
step = step_of(B, "k7")
check("the second gives up", (step["status"], step["attempts"]),
      ("skipped", 2))
check("…counted as a failure on the improvement",
      store.get(B)["failed_count"], 1)

# ── 14. busy is not a defect ─────────────────────────────────────────────────
print("\n14. busy is load, not a defect")
FakeType.behaviour = "busy"
engine.handle_step({"improvement_id": B, "candidate_key": "k9", "_task_id": ""})
step = step_of(B, "k9")
check("a busy backend spends no attempt", (step["status"], step["attempts"]),
      ("pending", 0))
FakeType.behaviour = "ok"

# ── 15. ordered_queue ────────────────────────────────────────────────────────
print("\n15. ordered_queue follows the entry order")
store.set_order([B, A])
queue = engine.ordered_queue()
check("B first, A second, positions from 1",
      [(r["pos"], r["improvement_id"], r["candidate_key"]) for r in queue],
      [(1, B, "k9"), (2, A, "k1")])
check("…each row carries its entry's label, type and mode",
      (queue[0]["label"], queue[0]["type_id"], queue[0]["mode"]),
      ("B", "fake", "standing"))
store.update(B, status="paused")
check("a paused entry leaves the queue",
      [(r["pos"], r["improvement_id"]) for r in engine.ordered_queue()],
      [(1, A)])

# ── 16. gates + run-now ──────────────────────────────────────────────────────
print("\n16. the gates, and the one-shot override")
store.set_settings(False, 15)
check("disabled", engine.submit_allowed(), (False, "disabled"))
store.set_settings(True, 15)
set_world_frozen(True)
check("frozen", engine.submit_allowed(), (False, "frozen"))
set_world_frozen(False)
user_activity._set_for_test(60)
check("active", engine.submit_allowed(), (False, "active"))

engine.request_run_now(A)
result = engine.tick()
check("run-now overrides the idle rule",
      (result["submitted"] != "", step_tasks()[-1]["payload"]),
      (True, {"improvement_id": A, "candidate_key": "k1"}))
state = engine.status()
check("status names the step in flight",
      (state["reason"], state["running_step"]["candidate_key"]),
      ("busy", "k1"))

worker_done(result["submitted"])
engine.handle_step({"improvement_id": A, "candidate_key": "k1",
                    "_task_id": result["submitted"]})
user_activity._set_for_test(60)
check("the flag is spent after one step", engine.tick()["submitted"], "")
check("…and A's last step closed it", store.get(A)["status"], "done")
state = engine.status()
check("status reports the settings and the gate",
      (state["enabled"], state["idle_minutes"], state["frozen"],
       state["reason"]), (True, 15, False, "active"))
check("…and counts the window down",
      830 <= state["next_allowed_in_s"] <= 840, True)

# ── 17. restart recovery ─────────────────────────────────────────────────────
print("\n17. a restart's orphaned running step")
store.mark_running(B, "k9")
drop_step_tasks()
result = engine.tick()
check("the step is runnable again", step_of(B, "k9")["status"], "pending")
check("…and nothing was queued in the same breath", result["submitted"], "")

# ── 18. a run-now flag that can never fire ───────────────────────────────────
print("\n18. a run-now flag on a stepless entry is spent, not stuck")
engine.request_run_now(C)             # C is done — it has no pending step
check("the tick finds nothing to run", engine.tick()["reason"], "empty")
check("…and the flag is gone, so the idle rule reads normally again",
      engine.tick()["reason"], "active")

# ── 19. a one_shot with nothing to do ────────────────────────────────────────
print("\n19. a one_shot whose scan finds nothing is done on the spot")
FakeType.candidates = []
D = store.create("fake", "D", {}, "one_shot")["id"]
check("the scan adds nothing", engine.scan(D), {"added": 0, "closed": 0})
check("…and it has no steps at all", counters(store.get(D)),
      {"pending": 0, "running": 0, "done": 0, "failed": 0, "skipped": 0})
check("…so it closed itself", store.get(D)["status"], "done")

# ── 20. the type is gone ─────────────────────────────────────────────────────
print("\n20. a step whose type is gone clears the head of the queue")
FakeType.candidates = [("k5", "Solo")]
E = store.create("fake", "E", {}, "one_shot")["id"]
engine.scan(E)
store.mark_running(E, "k5")           # the state the worker really sees
registry.clear()                      # the package went away
result = engine.handle_step({"improvement_id": E, "candidate_key": "k5",
                             "_task_id": ""})
check("the handler names the missing type", "fake" in (result.get("skipped") or ""),
      True)
step = step_of(E, "k5")
check("the step does NOT stay running", step["status"], "skipped")
check("…and carries the type id as its error", "fake" in step["error"], True)
check("…counted as a failure, not as an attempt",
      (store.get(E)["failed_count"], step["attempts"]), (1, 0))
user_activity._set_for_test(960)      # the gate is wide open now
result = engine.tick()
check("the next tick does not resubmit it",
      (result["submitted"], result["reason"]), ("", "empty"))
check("…and no task row for E was ever queued",
      [t for t in step_tasks() if t["payload"]["improvement_id"] == E], [])

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
