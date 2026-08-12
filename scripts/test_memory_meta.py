#!/usr/bin/env python3
"""Checks that a memory entry no longer loses meta fields silently.

Usage:
    ./.venv/bin/python scripts/test_memory_meta.py

Runs without the server and without a world DB — the meta builder is a pure
function, and the slice fix is checked on a synthetic list.

WHY these expectations (derived by hand from the defect, not recorded from
current output):

1. `delay_minutes` must survive. It is a commitment's due hint. The whitelist did not
   know the key, so `apply_extracted_memories` handed it in and it vanished:
   0 rows with `meta.delay` in all three worlds, while the prompt block kept
   rendering "(when: …)" from a field that was never stored.

2. `summary` / `summary_stale` must survive. Same whitelist, different victim:
   the pairwise relationship summary could never be persisted, so
   `summary_stale` stayed True forever — 32 and 132 memories tagged
   `relationship`, none with a summary.

3. An unknown key still must NOT be stored (the column is a whitelist on
   purpose) but must produce exactly one warning. Silent loss is the defect;
   refusing loudly is fine.

4. Fields that live in their own columns (content, tags, timestamp, …) are not
   meta and must NOT trigger the warning — otherwise every single save would
   log noise and the warning would be worthless.

5. The dedup context takes the NEWEST entries. `load_memories` sorts ts DESC,
   so `[-15:]` handed the model the fifteen OLDEST memories as its "do not
   repeat" list. With 20 synthetic entries newest-first, the first slice entry
   must be the newest one, not the oldest.

Exit code 0 = all checks passed, 1 = at least one failed.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import memory as mem  # noqa: E402

failures = []


def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          f"{'' if ok else f'  — got {got!r}, want {want!r}'}")
    if not ok:
        failures.append(name)


class CountingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


handler = CountingHandler()
mem.logger.addHandler(handler)

print("1) the fields that used to vanish now survive")
entry = {
    "memory_type": "commitment", "content": "x", "timestamp": "2026-08-03",
    "tags": ["a"], "importance": 4, "related_character": "Alpha",
    "delay_minutes": 120, "summary": "kurz", "summary_stale": False,
}
handler.records.clear()
meta = mem._build_meta(entry)
check("delay_minutes kept", meta.get("delay_minutes"), 120)
check("summary kept", meta.get("summary"), "kurz")
check("summary_stale kept", meta.get("summary_stale"), False)
check("importance kept", meta.get("importance"), 4)
check("no warning for known fields", handler.records, [])

print("2) column fields are not meta and stay quiet")
handler.records.clear()
meta = mem._build_meta({"content": "x", "tags": [], "timestamp": "t",
                        "source_ids": [], "id": 7, "tier": "semantic"})
check("nothing lands in meta", meta, {})
check("no warning", handler.records, [])

print("3) an unknown field is refused loudly, not silently")
handler.records.clear()
meta = mem._build_meta({"content": "x", "voellig_neu": 1})
check("not stored", "voellig_neu" in meta, False)
check("exactly one warning", len(handler.records), 1)
check("warning names the field", "voellig_neu" in handler.records[0], True)

print("4) _entry_to_row uses the same builder")
row = mem._entry_to_row({"memory_type": "commitment", "content": "c",
                         "delay_minutes": 1440, "importance": 2})
check("row carries the meta json", '"delay_minutes": 1440' in row["meta"], True)
check("tier from memory_type", row["tier"], "commitment")

print("5) the dedup context takes the newest entries")
# load_memories returns ts DESC → newest first.
newest_first = [{"content": f"mem-{20 - i:02d}"} for i in range(20)]
check("newest first, as load_memories delivers", newest_first[0]["content"], "mem-20")
sliced = newest_first[:15]
check("slice starts at the newest", sliced[0]["content"], "mem-20")
check("slice ends 15 entries later", sliced[-1]["content"], "mem-06")
check("the old [-15:] would have started at", newest_first[-15:][0]["content"], "mem-15")

print("6) the extraction actually hands the delay over")
src = (Path(__file__).resolve().parents[1]
       / "app/core/memory_service.py").read_text()
check("apply_extracted_memories fills extra_meta['delay_minutes']",
      'extra_meta["delay_minutes"] = delay_minutes' in src, True)
check("the dedup slice is fixed", "existing[:15]" in src, True)
check("the commitment slice is fixed", "open_commitments[:10]" in src, True)

print("7) completion accepts the id the prompt actually shows")
# The prompt prints "[ID:123]" where 123 is the integer row id; an LLM returns
# it as a number on one day and as a string on the next. Before the fix the
# comparison was `entry["id"] in commitment_ids`, so "123" matched nothing —
# silently. Result: 998 commitments in the worlds, none ever completed.
from app.core import memory_service as ms  # noqa: E402
from app.models import memory as mem_mod  # noqa: E402


def _run_completion(ids, entry_id=123, mtype="commitment"):
    saved = {}
    entries = [{"id": entry_id, "memory_type": mtype, "tags": [], "content": "c"}]
    orig_load, orig_save = mem_mod.load_memories, mem_mod.save_memories
    mem_mod.load_memories = lambda name: entries
    mem_mod.save_memories = lambda name, e: saved.update({"n": len(e)})
    try:
        ms._mark_commitments_completed("Demo", ids)
    finally:
        mem_mod.load_memories, mem_mod.save_memories = orig_load, orig_save
    return "completed" in entries[0]["tags"]


check("string id matches the integer row id", _run_completion(["123"]), True)
check("integer id matches too", _run_completion([123]), True)
check("a different id does not match", _run_completion(["999"]), False)
check("a non-commitment is never touched",
      _run_completion(["123"], mtype="semantic"), False)

print("8) the due hint reads minutes, not prose")
from datetime import datetime, timezone  # noqa: E402
from app.core import thought_context as tc, timeutils  # noqa: E402

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
orig_now = timeutils.game_now
timeutils.game_now = lambda: NOW
try:
    # promised at 11:30 with 120 minutes → due 13:30 → 90 minutes left → hours
    check("90 minutes out reads as hours",
          tc._due_hint("2026-08-03T11:30:00+00:00", 120), "in 1 h")
    # promised at 11:50 with 30 minutes → due 12:20 → 20 minutes left
    check("20 minutes out reads as minutes",
          tc._due_hint("2026-08-03T11:50:00+00:00", 30), "in 20 min")
    # promised yesterday with 60 minutes → long past
    check("past due says so",
          tc._due_hint("2026-08-02T11:00:00+00:00", 60), "overdue")
    check("an unreadable timestamp yields nothing",
          tc._due_hint("kaputt", 120), "")
finally:
    timeutils.game_now = orig_now


print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
