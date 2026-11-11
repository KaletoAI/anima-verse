#!/usr/bin/env python3
"""Smoke check for the improvements engine contract of the figure-pipeline
types (spec docs/superpowers/specs/2026-11-11-improvements-figure-pipeline-design.md
§ 5): hub cost per candidate, a terminal refusal, ``needs_media`` per type and
the media switch as load.

Every expectation below is derived BY HAND from the contract, never recorded
from a run.  Throwaway storage, ``db.init_schema()``, one drivable ``FakeType``
per needs_media flavour, the queue handler called directly (no worker threads,
as ``smoke_improvements.py`` does).

  [C1] ``Candidate("k", "l")`` keeps the existing types untouched: hub_jobs 0,
       note "".  ``Candidate("k", "l", hub_jobs=3, note="n")`` round-trips.

  [C2] The store keeps the estimate per step and sums it per entry.  FakeType
       lists A(2), B(0), C(None); after ``engine.scan`` ``list_steps`` reads
       hub_jobs [2, 0, None] in LABEL order (A, B, C), and the entry's
       ``pending_hub_jobs`` is None — C is pending and unknown, and an unknown
       step makes the whole estimate unknown, never a silent 2.  A rescan that
       lists only A(2), B(0) closes the vanished PENDING C as done, so the sum
       is 2 + 0 = 2.  A re-listed with hub_jobs 5 updates the pending row to 5
       (the estimate changes as the chain's steps get cached) → 5 + 0 = 5.
       ``mark_result(A, "done")`` leaves B alone → 0.

  [C3] ``POST /improvements/preview`` (the route function called directly)
       with A(2), B(0), C(None): count 3, hub_jobs = 2 + 0 = 2 (the known
       ones), unknown 1 (C), and sample[0] is A as an object
       {"label": "A", "hub_jobs": 2, "note": ""}.

  [C4] A refusal is terminal.  ``apply`` raises ``CandidateRefused("gate")``
       → ``handle_step`` answers {"refused": "gate"}; the step is skipped
       after this ONE attempt (attempts 1), refused 1, error "gate"; the
       entry's failed_count is 1; ``store.retry_step`` is False and the retry
       route raises HTTPException 409 — the engine must never re-spend a
       refused source, and neither may the tab's Retry.  The one-shot whose
       only step was refused is 'done' (not deleted: skipped > 0).

  [C5] A skipped step stays skipped.  FakeType now lists only B; a pending D
       was listed before.  Rescan: A (skipped, refused) stays "skipped" — a
       refused candidate drops off the list because the type excludes it, and
       "done" would claim an asset that does not exist; D (pending, vanished)
       becomes "done"; closed == 1 (D only).

  [C6] ``needs_media``.  ``media_generation_enabled`` patched False; entry1
       (type needs_media True, position 1) and entry2 (needs_media False) each
       with one pending step; engine enabled, idle 960 s > 15 min.  The tick
       passes entry1 over and submits entry2's step: the submitted task's
       payload names entry2.  ``submit_allowed()`` still says media_off (the
       panel's reason).  After entry2's step is done the tick finds only
       entry1's step, which the switch holds: submitted "", reason "media_off".
       ``run_now(entry1)`` → {"ok": False, "reason": "media_off"};
       ``run_now(entry2)`` → started.

  [C7] The switch flipped mid-run is load.  ``apply`` raises
       ``MediaGenerationDisabled`` → {"busy": …}, the step stays pending,
       attempts 0, and it is deferred (``_deferred`` True).

  [C8] ``engine.status()["pending_hub_jobs"]`` sums the OPEN entries' pending
       steps only: entry1 pending 2 + 3 open, entry3 paused with 7 → 5.

Fails on 193321cf: ImportError at the top (``CandidateRefused`` is not in
``base``); with that import dropped, [C1] TypeError — Candidate() got an
unexpected keyword argument 'hub_jobs'.

Usage:  ./.venv/bin/python scripts/smoke_improvements_contract.py
"""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="improvements-contract-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="improvements-contract-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from fastapi import HTTPException  # noqa: E402

from app.core import user_activity  # noqa: E402
from app.core.improvements import engine, registry, store  # noqa: E402
from app.core.improvements.base import (Candidate, CandidateRefused,  # noqa: E402
                                        ImprovementType)
from app.core.task_queue import get_task_queue  # noqa: E402
from app.imagegen.base import MediaGenerationDisabled  # noqa: E402
from app.models.world import set_world_frozen  # noqa: E402
from app.routes import improvements as improvements_route  # noqa: E402

get_task_queue()._started = True          # no worker threads: rows only
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


def step_of(improvement_id, key):
    return [s for s in store.list_steps(improvement_id) if s["candidate_key"] == key][0]


def step_tasks():
    conn = sqlite3.connect(f"file:{QUEUE_DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT task_id, status, payload FROM tasks WHERE task_type=? "
            "ORDER BY created_at, rowid", (engine.TASK_TYPE,)).fetchall()
    finally:
        conn.close()
    return [{"task_id": r[0], "status": r[1], "payload": json.loads(r[2])} for r in rows]


def worker_done(task_id):
    conn = sqlite3.connect(QUEUE_DB)
    try:
        conn.execute("UPDATE tasks SET status='completed' WHERE task_id=?", (task_id,))
        conn.commit()
    finally:
        conn.close()


class FakeType(ImprovementType):
    """Candidate list and apply behaviour are class state the cases drive."""

    id = "fake"
    label = "Fake improvement"
    params_schema = []
    candidates = []            # [(key, label, hub_jobs, note)]
    behaviour = "ok"           # "ok" | "refuse" | "media_off"

    def find_candidates(self, params):
        return [Candidate(key, label, hub_jobs=hub, note=note)
                for key, label, hub, note in type(self).candidates]

    def is_done(self, candidate, params):
        return False

    def apply(self, candidate, params, task_id):
        if type(self).behaviour == "refuse":
            raise CandidateRefused("gate")
        if type(self).behaviour == "media_off":
            raise MediaGenerationDisabled("media generation is switched off")


class CpuType(FakeType):
    """The CPU-only flavour: runs with the media switch off."""

    id = "cpu"
    label = "CPU-only improvement"
    needs_media = False
    candidates = []
    behaviour = "ok"


registry.clear()
registry.register(FakeType())
registry.register(CpuType())
store.set_settings(True, 15)
set_world_frozen(False)

# ── C1 ───────────────────────────────────────────────────────────────────────
print("\nC1. Candidate defaults and round-trip")
c = Candidate("k", "l")
check("defaults: hub_jobs 0, note ''", (c.hub_jobs, c.note), (0, ""))
c = Candidate("k", "l", hub_jobs=3, note="n")
check("explicit values round-trip", (c.key, c.label, c.hub_jobs, c.note),
      ("k", "l", 3, "n"))
check("needs_media defaults True", ImprovementType.needs_media, True)
check("…and the CPU type says False", CpuType.needs_media, False)

# ── C2 ───────────────────────────────────────────────────────────────────────
print("\nC2. the estimate per step and per entry")
FakeType.candidates = [("a", "A", 2, ""), ("b", "B", 0, ""), ("c", "C", None, "")]
E = store.create("fake", "E", {}, "standing")["id"]
check("scan adds the three", engine.scan(E), {"added": 3, "closed": 0})
check("list_steps carries hub_jobs in label order",
      [s["hub_jobs"] for s in store.list_steps(E)], [2, 0, None])
check("…and the note column", [s["note"] for s in store.list_steps(E)], ["", "", ""])
check("an unknown pending step makes the entry unknown",
      store.get(E)["pending_hub_jobs"], None)
check("…in list_all too",
      [r["pending_hub_jobs"] for r in store.list_all() if r["id"] == E], [None])
FakeType.candidates = [("a", "A", 2, ""), ("b", "B", 0, "")]
check("rescan closes the vanished pending C", engine.scan(E), {"added": 0, "closed": 1})
check("…as done", step_of(E, "c")["status"], "done")
check("the sum is 2 + 0", store.get(E)["pending_hub_jobs"], 2)
FakeType.candidates = [("a", "A", 5, "cached less"), ("b", "B", 0, "")]
engine.scan(E)
check("a re-listed pending step takes the new estimate",
      (step_of(E, "a")["hub_jobs"], step_of(E, "a")["note"]), (5, "cached less"))
check("…and the sum follows", store.get(E)["pending_hub_jobs"], 5)
store.mark_result(E, "a", status="done", count_attempt=False)
check("a done step no longer counts", store.get(E)["pending_hub_jobs"], 0)
FakeType.candidates = [("a", "A", 2, ""), ("b", "B", 0, "")]
engine.scan(E)
check("a done step keeps its estimate untouched by the scan",
      (step_of(E, "a")["status"], step_of(E, "a")["hub_jobs"]), ("done", 5))

# ── C3 ───────────────────────────────────────────────────────────────────────
print("\nC3. POST /improvements/preview carries the cost")
FakeType.candidates = [("a", "A", 2, ""), ("b", "B", 0, ""), ("c", "C", None, "")]
preview = improvements_route.preview(
    improvements_route.PreviewBody(type_id="fake", params={}))
check("count / hub_jobs / unknown",
      {k: preview[k] for k in ("count", "hub_jobs", "unknown")},
      {"count": 3, "hub_jobs": 2, "unknown": 1})
check("sample rows are objects", preview["sample"][0],
      {"label": "A", "hub_jobs": 2, "note": ""})
check("…the unknown one says None", preview["sample"][2]["hub_jobs"], None)

# ── C4 ───────────────────────────────────────────────────────────────────────
print("\nC4. a refusal is terminal")
FakeType.candidates = [("a", "A", 2, "")]
FakeType.behaviour = "refuse"
R = store.create("fake", "R", {}, "one_shot")["id"]
engine.scan(R)
store.mark_running(R, "a")
result = engine.handle_step({"improvement_id": R, "candidate_key": "a", "_task_id": "t"})
check("handle_step reports the refusal", result, {"refused": "gate"})
step = step_of(R, "a")
check("the step is skipped after ONE attempt, marked refused",
      (step["status"], step["attempts"], step["refused"], step["error"]),
      ("skipped", 1, 1, "gate"))
check("the entry counts the failure", store.get(R)["failed_count"], 1)
check("retry_step refuses it", store.retry_step(R, "a"), False)
try:
    improvements_route.retry_step(R, "a")
    check("the retry route → 409", "no exception", 409)
except HTTPException as e:
    check("the retry route → 409", (e.status_code, e.detail), (409, "refused"))
check("…and the step is still skipped", step_of(R, "a")["status"], "skipped")
check("a one-shot whose only step was refused is done, not deleted",
      store.get(R)["status"], "done")
FakeType.behaviour = "ok"

# ── C5 ───────────────────────────────────────────────────────────────────────
print("\nC5. a skipped step stays skipped on rescan")
FakeType.candidates = [("a", "A", 2, ""), ("d", "D", 1, "")]
S = store.create("fake", "S", {}, "standing")["id"]
engine.scan(S)
store.mark_running(S, "a")
FakeType.behaviour = "refuse"
engine.handle_step({"improvement_id": S, "candidate_key": "a", "_task_id": "t"})
FakeType.behaviour = "ok"
check("A is refused, D pending",
      {s["candidate_key"]: s["status"] for s in store.list_steps(S)},
      {"a": "skipped", "d": "pending"})
FakeType.candidates = [("b", "B", 0, "")]
check("rescan closes only the vanished PENDING step",
      engine.scan(S), {"added": 1, "closed": 1})
check("A stays skipped, D is done",
      {s["candidate_key"]: s["status"] for s in store.list_steps(S)},
      {"a": "skipped", "b": "pending", "d": "done"})
check("…and A is still marked refused", step_of(S, "a")["refused"], 1)

# ── C6 ───────────────────────────────────────────────────────────────────────
print("\nC6. needs_media: CPU-only entries keep running with the switch off")
for row in store.list_all():                   # start from an empty queue
    store.delete(row["id"])
FakeType.candidates = [("m", "M", 1, "")]
CpuType.candidates = [("p", "P", 0, "")]
entry1 = store.create("fake", "Entry1", {}, "one_shot")["id"]
entry2 = store.create("cpu", "Entry2", {}, "one_shot")["id"]
engine.scan(entry1)
engine.scan(entry2)
store.set_order([entry1, entry2])
user_activity._set_for_test(960)
with patch("app.core.improvements.engine.media_generation_enabled", return_value=False):
    check("submit_allowed names the switch", engine.submit_allowed(), (False, "media_off"))
    check("…and the gates behind it are open",
          engine.submit_allowed(needs_media=False), (True, "ok"))
    result = engine.tick()
    tasks = step_tasks()
    check("the tick submits the CPU-only entry's step",
          (result["reason"], tasks[-1]["payload"]),
          ("ok", {"improvement_id": entry2, "candidate_key": "p"}))
    check("…entry1's step is untouched", step_of(entry1, "m")["status"], "pending")
    check("status() reports media_off", engine.status()["reason"], "media_off")
    worker_done(result["submitted"])
    engine.handle_step({"improvement_id": entry2, "candidate_key": "p",
                        "_task_id": result["submitted"]})
    check("the CPU-only one-shot worked itself off", store.get(entry2), None)
    result = engine.tick()
    check("only the held step is left: nothing submitted, reason media_off",
          (result["submitted"], result["reason"]), ("", "media_off"))
    check("run_now on a media type is refused by the switch",
          engine.run_now(entry1), {"ok": False, "reason": "media_off"})
    entry2 = store.create("cpu", "Entry2b", {}, "one_shot")["id"]
    engine.scan(entry2)
    result = engine.run_now(entry2)
    check("run_now on a CPU-only type starts",
          (result["ok"], result["reason"]), (True, "started"))
    worker_done(result["task_id"])
    engine.handle_step({"improvement_id": entry2, "candidate_key": "p",
                        "_task_id": result["task_id"]})
check("with the switch on the held step goes out",
      engine.tick()["reason"], "ok")

# ── C7 ───────────────────────────────────────────────────────────────────────
print("\nC7. MediaGenerationDisabled mid-run is load")
FakeType.behaviour = "media_off"
result = engine.handle_step({"improvement_id": entry1, "candidate_key": "m",
                             "_task_id": "t"})
check("handle_step answers busy", list(result.keys()), ["busy"])
step = step_of(entry1, "m")
check("the step stays pending with no attempt",
      (step["status"], step["attempts"], step["refused"]), ("pending", 0, 0))
check("…and is deferred", engine._deferred(entry1, "m", engine.utc_now()), True)
FakeType.behaviour = "ok"
engine._undefer(entry1, "m")
for t in step_tasks():
    worker_done(t["task_id"])

# ── C8 ───────────────────────────────────────────────────────────────────────
print("\nC8. status() sums the open entries' pending hub jobs")
for row in store.list_all():
    store.delete(row["id"])
FakeType.candidates = [("x", "X", 2, ""), ("y", "Y", 3, "")]
entry1 = store.create("fake", "Open", {}, "one_shot")["id"]
engine.scan(entry1)
FakeType.candidates = [("z", "Z", 7, "")]
entry3 = store.create("fake", "Paused", {}, "one_shot")["id"]
engine.scan(entry3)
store.update(entry3, status="paused")
check("open 2 + 3, paused 7 excluded", engine.status()["pending_hub_jobs"], 5)
check("…pending_hub_jobs_total(open_only=False) counts the paused one too",
      store.pending_hub_jobs_total(open_only=False), 12)
FakeType.candidates = [("x", "X", 2, ""), ("y", "Y", None, "")]
engine.scan(entry1)
check("an unknown open step makes the panel total unknown",
      engine.status()["pending_hub_jobs"], None)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
