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

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
