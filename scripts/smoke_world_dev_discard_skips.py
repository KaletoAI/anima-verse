#!/usr/bin/env python3
"""Smoke: World Dev free mode — a final discard clears the skip records it resolved (F7).

Usage:  ./.venv/bin/python scripts/smoke_world_dev_discard_skips.py

Plan docs/superpowers/plans/2026-11-25-world-dev-free-fixes.md, Task 7. A temp
world (STORAGE_DIR / INSTANCE_DIR temp, paths.init BEFORE any world-DB
import); no server, no LLM: the steps are run through `wt.run_tool`, the
discard through `RunManager.discard`.

THE RULE: a run's stored `skipped` keeps the records of earlier undos (a
turn rollback whose undo failed). On the final discard an earlier record
survives only when its seq is 0 (a crashed undo, no step to resolve) or the
final undo neither REVERSED nor RE-SKIPPED its seq; a re-skipped seq is
replaced by the final undo's fresh record (one record per seq). The run ends
`rolled_back` when the final undo is complete and every surviving earlier
record is complete (`wu.is_complete`), else `rollback_incomplete`.

Fixture per case: a fresh run; turn 1 create_location "Demo Plaza <x>" (P,
seq p, kept); turn 2 add_block_rule on P (R2, seq k). The turn-2 rollback
`wu.undo(run, 2)` runs with `rules.world_rule` stubbed to raise
RuntimeError("stub turn 2"), so R2's undo raises -> one skip record
{seq k, reason "undo failed: stub turn 2"}, R2 stays (a rule step whose undo
raised is not marked undone). That record is stored with `wr.set_skipped`
and the run set to `awaiting_review`, as the turn end does.

(a) clean: stub removed, discard -> the final undo reverses R2 (k) and then
    P (p), skips nothing. The earlier k record is resolved -> dropped.
    Expected: report reversed contains k and p; status rolled_back; stored
    skipped == []; P and R2 gone. (Old code: stored kept the stale k record
    and the run ended rollback_incomplete.)
(b) seq-0 control: as (a) but the stored earlier list also carries
    {"seq": 0, "line": "undo", "reason": "undo failed: x"}. Seq 0 always
    stays; it is not complete -> rollback_incomplete; stored skipped ==
    [that seq-0 record] exactly (the k record resolved -> dropped).
(c) stub kept: the discard runs with `rules.world_rule` raising
    RuntimeError("stub final") -> the final undo skips R2 again with reason
    "undo failed: stub final" (and P is held by R2, its own record).
    Expected: status rollback_incomplete; the stored list has EXACTLY ONE
    record for seq k, and its reason is "undo failed: stub final" — equal to
    the report's record for k (the fresh one, not the turn-2 copy).
"""
import asyncio
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="smoke_wd_discard_skips_"))
atexit.register(shutil.rmtree, ROOT, True)
STORAGE = ROOT / "world"
STORAGE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")
(STORAGE / "config.json").write_text("{}", encoding="utf-8")

from app.core import paths  # noqa: E402

paths.init(STORAGE)
paths.init_instance(ROOT / "instance")

from app.core import config, db  # noqa: E402

config.load(STORAGE / "config.json")
db.init_schema()

from app.core import world_dev_agent as wa  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.models import rules  # noqa: E402
from app.models.world import get_location_by_id, list_locations  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


REAL_WORLD_RULE = rules.world_rule


def stub(message):
    def boom(rid):
        raise RuntimeError(message)
    return boom


def by_name(name):
    return [loc for loc in list_locations() if loc.get("name") == name]


def fixture(tag):
    """Turn 1 P kept, turn 2 R2 whose turn rollback failed. Returns
    (run, p, k, rule id, the turn-2 skip records)."""
    run = wr.create_run(f"discard skips {tag}", "m", "p", "u", 80, 300000)
    r1 = wt.run_tool(wt.ToolCtx(run_id=run, turn=1), "create_location",
                     {"data": {"name": f"Demo Plaza {tag}", "rooms": [{"name": "Main"}]}})
    assert r1.ok and r1.wrote, r1
    pid = by_name(f"Demo Plaza {tag}")[0]["id"]
    r2 = wt.run_tool(wt.ToolCtx(run_id=run, turn=2), "add_block_rule",
                     {"name": "Closed at night", "message": "Closed.",
                      "location_id": pid, "condition": "night"})
    assert r2.ok and r2.wrote, r2
    writes = [e for e in wr.entries(run, include_undone=True) if e.get("kind") == "write"]
    p = next(e["seq"] for e in writes if e.get("target_kind") == "location")
    rule_row = next(e for e in writes if e.get("target_kind") == "rule")
    k, rid = rule_row["seq"], rule_row["target_id"]
    rules.world_rule = stub("stub turn 2")
    try:
        rep2 = wu.undo(run, 2)
    finally:
        rules.world_rule = REAL_WORLD_RULE
    sk2 = list(rep2.get("skipped") or [])
    check(f"({tag}) turn-2 rollback skipped R2 once",
          [(s.get("seq"), s.get("reason")) for s in sk2]
          == [(k, "undo failed: stub turn 2")], sk2)
    check(f"({tag}) R2 still stands", REAL_WORLD_RULE(rid) is not None)
    return run, pid, p, k, rid, sk2


async def main():
    rm = wa.RunManager()

    print("(a) clean final discard")
    run, pid, p, k, rid, sk2 = fixture("a")
    wr.set_skipped(run, sk2)
    wr.set_status(run, "awaiting_review")
    report = await rm.discard(run)
    stored = wr.get_run(run)
    check("(a) reversed contains k and p",
          {k, p} <= set(report.get("reversed") or []), report.get("reversed"))
    check("(a) report skipped nothing", report.get("skipped") == [], report.get("skipped"))
    check("(a) rolled_back", stored["status"] == "rolled_back", stored["status"])
    check("(a) stored skipped == []", stored.get("skipped") == [], stored.get("skipped"))
    check("(a) P gone", get_location_by_id(pid) is None)
    check("(a) R2 gone", REAL_WORLD_RULE(rid) is None)

    print("(b) a seq-0 earlier record stays")
    run, pid, p, k, rid, sk2 = fixture("b")
    zero = {"seq": 0, "line": "undo", "reason": "undo failed: x"}
    wr.set_skipped(run, sk2 + [zero])
    wr.set_status(run, "awaiting_review")
    report = await rm.discard(run)
    stored = wr.get_run(run)
    check("(b) reversed contains k and p",
          {k, p} <= set(report.get("reversed") or []), report.get("reversed"))
    check("(b) rollback_incomplete", stored["status"] == "rollback_incomplete",
          stored["status"])
    check("(b) stored skipped == [seq-0 record]", stored.get("skipped") == [zero],
          stored.get("skipped"))

    print("(c) the final undo re-skips seq k")
    run, pid, p, k, rid, sk2 = fixture("c")
    wr.set_skipped(run, sk2)
    wr.set_status(run, "awaiting_review")
    rules.world_rule = stub("stub final")
    try:
        report = await rm.discard(run)
    finally:
        rules.world_rule = REAL_WORLD_RULE
    stored = wr.get_run(run)
    fresh = [s for s in report.get("skipped") or [] if s.get("seq") == k]
    mine = [s for s in stored.get("skipped") or [] if s.get("seq") == k]
    check("(c) rollback_incomplete", stored["status"] == "rollback_incomplete",
          stored["status"])
    check("(c) the report re-skipped k once", len(fresh) == 1, report.get("skipped"))
    check("(c) exactly one stored record for k", len(mine) == 1, stored.get("skipped"))
    check("(c) it is the fresh one",
          len(mine) == 1 and len(fresh) == 1
          and mine[0].get("reason") == fresh[0].get("reason") == "undo failed: stub final",
          (mine, fresh))
    check("(c) stored == the report's records",
          stored.get("skipped") == list(report.get("skipped") or []),
          (stored.get("skipped"), report.get("skipped")))
    check("(c) R2 still stands", REAL_WORLD_RULE(rid) is not None)


asyncio.run(main())
print()
if failures:
    print(f"FAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("all checks passed")
