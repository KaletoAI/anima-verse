#!/usr/bin/env python3
"""Smoke: World Dev free mode — run store and two-phase journal (world_dev_runs).

Plan docs/superpowers/plans/2026-11-22-world-dev-free-mode.md, Task 2. A temp
world (paths.init BEFORE any world-DB import); no server, no LLM.

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

  (a) ONE OPEN RUN. ``create_run`` stores status ``running`` (an open status),
      so ``open_run()["id"]`` is the new id. A second ``create_run`` hits the
      partial unique index over the open statuses and raises ``RunOpenError``
      whose ``run_id`` is the FIRST id; no second row is written
      (``list_runs()`` still has 1 row).

  (b) SEQS AND ORDER. Steps in this order:
          seq 1  turn 1  write  create_location   inverse delete_location{id: L1}
          seq 2  turn 1  read   get_location      (no inverse)
          seq 3  turn 1  write  add_terrain_area  pending, no inverse yet
          seq 4  turn 2  write  update_location   inverse restore_location
      seqs count up per run from 1. ``begin`` writes the journal row only
      (plan 2026-11-25 complete-characters-budget, B1): ``steps`` stays 0.
      ``steps`` counts model tool calls through ``count_call``: two calls
      return 1, then 2, ``steps`` → 2; ``count_call("wdr_nope")`` raises
      KeyError. The journal seqs stay [1, 2, 3, 4].
      ``entries(run, turn=1)`` = writes of turn 1 newest-first = [3, 1].
      ``entries(run)`` = every write newest-first = [4, 3, 1].
      ``steps(run)`` = all 4 rows oldest-first = [1, 2, 3, 4], kinds
      [write, read, write, write].

  (c) TWO PHASES. seq 1 is ``pending`` after ``begin``; ``complete(written,
      line)`` makes it ``done`` with that written dict and line. ``attach``
      on seq 3 sets target_id "A1", the inverse delete_terrain_area{id: A1}
      and before {}; seq 3 stays ``pending`` (never completed) and is still
      in ``entries`` WITH its inverse. ``complete(..., kind="refused")``
      on a fifth step changes its kind so it drops out of the writes.

  (d) UNDONE. ``mark_undone(run, 3)`` hides seq 3 from ``entries`` →
      turn 1 = [1]; ``include_undone=True`` shows it again → [3, 1].

  (e) RUN FIELDS. next_turn twice → 1, 2. add_usage(100, 20, 0.5) twice →
      tokens_in 200, tokens_out 40, cost_total 1.0. set_budgets(10, 5000),
      set_was_frozen(True) → was_frozen True, set_skipped([{"seq": 3}]) →
      skipped [{"seq": 3}], set_backup("/x") → backup_path "/x".

  (f) TERMINAL FREES THE SLOT. set_status(run, "rollback_incomplete") →
      open_run() is None, ended_at set, and a new create_run succeeds and is
      the open run. An unknown status raises ValueError.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_runs.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="smoke_wd_runs_"))

from app.core import db  # noqa: E402

db.init_schema()

from app.core import world_dev_runs as wr  # noqa: E402

failures = []


def check(label, cond):
    print(("  ok   " if cond else "  FAIL ") + label)
    if not cond:
        failures.append(label)


# (a) one open run
run = wr.create_run("build a lake", "m1", "p1", "u1", 40, 300000)
check("(a) open_run is the new run", (wr.open_run() or {}).get("id") == run)
check("(a) status running", wr.get_run(run)["status"] == "running")
try:
    wr.create_run("second", "m1", "p1", "u1", 40, 300000)
    check("(a) second create_run raises RunOpenError", False)
except wr.RunOpenError as e:
    check("(a) second create_run raises RunOpenError", True)
    check("(a) RunOpenError carries the first id", e.run_id == run)
check("(a) still one run row", len(wr.list_runs()) == 1)

# (b) seqs and order
s1 = wr.begin(run, 1, "write", "create_location", {"data": {"name": "L"}},
              target_kind="location", target_id="L1",
              inverse={"op": "delete_location", "id": "L1"})
s2 = wr.begin(run, 1, "read", "get_location", {"id": "L1"})
s3 = wr.begin(run, 1, "write", "add_terrain_area", {"kind": "water"},
              target_kind="terrain")
s4 = wr.begin(run, 2, "write", "update_location", {"id": "M"},
              target_kind="location", target_id="M",
              inverse={"op": "restore_location", "id": "M", "before": {"description": "old"}})
check("(b) seqs 1..4", [s1, s2, s3, s4] == [1, 2, 3, 4])
check("(b) begin does not count: run.steps == 0", wr.get_run(run)["steps"] == 0)
check("(b) count_call -> 1, 2", [wr.count_call(run), wr.count_call(run)] == [1, 2])
check("(b) run.steps == 2", wr.get_run(run)["steps"] == 2)
try:
    wr.count_call("wdr_nope")
    _kerr = False
except KeyError:
    _kerr = True
check("(b) count_call of an unknown run raises KeyError", _kerr)
check("(b) entries(turn=1) newest-first [3, 1]",
      [e["seq"] for e in wr.entries(run, turn=1)] == [3, 1])
check("(b) entries() [4, 3, 1]", [e["seq"] for e in wr.entries(run)] == [4, 3, 1])
st = wr.steps(run)
check("(b) steps() oldest-first [1..4]", [e["seq"] for e in st] == [1, 2, 3, 4])
check("(b) steps() kinds", [e["kind"] for e in st] == ["write", "read", "write", "write"])

# (c) two phases
check("(c) seq 1 pending after begin", wr.steps(run)[0]["state"] == "pending")
wr.complete(run, s1, {"name": "L"}, 'created location L1 "L"')
e1 = wr.steps(run)[0]
check("(c) seq 1 done", e1["state"] == "done")
check("(c) seq 1 written", e1["written"] == {"name": "L"})
check("(c) seq 1 line", e1["line"] == 'created location L1 "L"')
check("(c) seq 1 inverse", e1["inverse"] == {"op": "delete_location", "id": "L1"})
wr.attach(run, s3, "A1", {"op": "delete_terrain_area", "id": "A1"}, before={})
e3 = [e for e in wr.entries(run, turn=1) if e["seq"] == 3]
check("(c) pending seq 3 listed", len(e3) == 1)
check("(c) seq 3 still pending", e3 and e3[0]["state"] == "pending")
check("(c) seq 3 target A1", e3 and e3[0]["target_id"] == "A1")
check("(c) seq 3 inverse", e3 and e3[0]["inverse"] == {"op": "delete_terrain_area", "id": "A1"})
check("(c) seq 3 before {}", e3 and e3[0]["before"] == {})
s5 = wr.begin(run, 2, "write", "update_location", {"id": "Z"})
wr.complete(run, s5, None, "refused: no such location", kind="refused")
check("(c) refused step leaves the writes", [e["seq"] for e in wr.entries(run)] == [4, 3, 1])
check("(c) refused step kept in steps()", wr.steps(run)[-1]["kind"] == "refused")

# (d) undone
wr.mark_undone(run, s3)
check("(d) mark_undone hides seq 3", [e["seq"] for e in wr.entries(run, turn=1)] == [1])
check("(d) include_undone shows it",
      [e["seq"] for e in wr.entries(run, turn=1, include_undone=True)] == [3, 1])
check("(d) writes_only=False adds the read",
      [e["seq"] for e in wr.entries(run, turn=1, writes_only=False)] == [2, 1])

# (e) run fields
check("(e) next_turn 1", wr.next_turn(run) == 1)
check("(e) next_turn 2", wr.next_turn(run) == 2)
wr.add_usage(run, 100, 20, 0.5)
wr.add_usage(run, 100, 20, 0.5)
wr.set_budgets(run, 10, 5000)
wr.set_was_frozen(run, True)
wr.set_skipped(run, [{"seq": 3}])
wr.set_backup(run, "/x")
r = wr.get_run(run)
check("(e) tokens", (r["tokens_in"], r["tokens_out"]) == (200, 40))
check("(e) cost", abs(r["cost_total"] - 1.0) < 1e-9)
check("(e) budgets", (r["max_steps"], r["max_tokens_total"]) == (10, 5000))
check("(e) was_frozen", r["was_frozen"] is True)
check("(e) skipped", r["skipped"] == [{"seq": 3}])
check("(e) backup", r["backup_path"] == "/x")

# (f) terminal frees the slot
wr.set_status(run, "rollback_incomplete", note="1 step skipped")
check("(f) open_run None", wr.open_run() is None)
r = wr.get_run(run)
check("(f) ended_at set", bool(r["ended_at"]))
check("(f) note", r["note"] == "1 step skipped")
run2 = wr.create_run("again", "m1", "p1", "u1", 40, 300000)
check("(f) new run can start", (wr.open_run() or {}).get("id") == run2 and run2 != run)
check("(f) list_runs newest first", [x["id"] for x in wr.list_runs()] == [run2, run])
try:
    wr.set_status(run2, "bogus")
    check("(f) unknown status raises ValueError", False)
except ValueError:
    check("(f) unknown status raises ValueError", True)

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all ok")
