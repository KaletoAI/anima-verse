#!/usr/bin/env python3
"""Smoke run for the AWARE system stamps on memories (plan-log-befunde-2026-09-11,
findings B1 and B2).

Runs WITHOUT a server and WITHOUT a real world: a throwaway SQLite world is
created in a temp directory (``paths.init`` + ``db.init_schema``). ``worlds/``
is never touched.

WHY THIS EXISTS

Every memory row carries a SYSTEM stamp written by ``utc_now_iso()`` — an
AWARE ISO string ending in ``+00:00`` (app/models/memory.py). Two readers had
built their own naive clock value instead of using ``app.core.timeutils``:

  B1  ``memory_service.apply_extracted_memories`` compared a naive
      ``datetime.now() - timedelta(days=14)`` against the aware stamp of the
      newest row. ``load_memories`` orders ``ts DESC``, so the very FIRST
      iteration raised ``TypeError: can't compare offset-naive and
      offset-aware`` — outside the ``try`` that only wrapped the parse. The
      caller (chat_engine) logs "Memory extraction error" and moves on, so
      NOTHING extracted from a thought was ever stored.

  B2  ``character_ops._score_memory_no_mutate`` made the same comparison, but
      INSIDE its ``try`` — the TypeError was swallowed and ``age_days`` fell
      back to its 30.0 default on every single entry, which pins
      ``_recency_boost`` to 1.0 forever.

THE HAND VALUES

  [1] ``add_memory`` writes an aware stamp: ``entry["timestamp"]`` ends in
      "+00:00". That is the precondition of everything below — if this ever
      changes, the comparisons in [2]–[4] are asking the wrong question.

  [2] ``apply_extracted_memories(CHAR, [one semantic item], {...})`` → **1**.
      Derivation: one item; the 14-day dedup pool holds only the unrelated
      memory from [1], so ``_keyword_overlap("older text …", "sunlight on the
      harbour wall") = 0.0`` (no shared non-stop word) which is below the
      0.5 skip threshold in ``apply_extracted_memories``; memory_type
      "semantic" with delay_minutes 0 takes neither the intent nor the
      commitment path, so ``add_memory`` runs once and the counter is 1.
      Before the fix this raised TypeError before the loop even started.

  [3] The SAME item a second time → **0**. Derivation: the pool now contains
      the identical content, ``_keyword_overlap(c, c) = 1.0 > 0.5`` → skip,
      no ``add_memory``, counter stays 0.

  [4] A LEGACY row with a NAIVE stamp ('2026-01-01T00:00:00', written by a
      direct UPDATE on the throwaway DB) does not break the run: ``parse_iso``
      reads a naive string as UTC (documented convention, not a shim), the row
      simply falls out of the 14-day window, and a fresh distinct item still
      returns **1**. Before the fix this was the same TypeError.

  [5] ``_score_memory_no_mutate`` on a FRESH aware stamp → **6.0** (±0.01 for
      the sub-second drift between building the stamp and scoring it).
      Derivation from the formula ``importance · decay · recency ·
      (1 + 2·relevance + type_bonus)``:
        importance 3
        decay      = min(1.0, max(0.05, exp(-0.023 · 0) + 0·0.05)) = 1.0
        recency    = _recency_boost(0.0) = 2.0        (age ≤ 1 day)
        relevance  = 0.0   (no current_message)
        type_bonus = 0.0   (no memory_type → neither commitment nor episodic)
        → 3 · 1.0 · 2.0 · 1.0 = 6.0
      Before the fix: age_days fell back to 30.0 → recency 1.0 → 3.0.

  [6] The same entry stamped 10 days ago → **2.38** (±0.01).
        decay      = exp(-0.023 · 10) = exp(-0.23) = 0.79453
        recency    = _recency_boost(10.0) = 1.0      (3+ days → no boost)
        → 3 · 0.79453 · 1.0 · 1.0 = 2.38360 → 2.38
      Note that ``_compute_decay`` was ALWAYS correct (it already used
      ``parse_iso``/``utc_now``), which is why B2 stayed invisible: only the
      recency factor was wrong, so the number moved but never looked absurd.

  [7] The same 10-day-old stamp written NAIVELY (no "+00:00") scores the same
      **2.38**: ``parse_iso`` carries the legacy row. Before the fix [5]/[6]/[7]
      all collapsed onto the 30.0 fallback.

Usage:  ./.venv/bin/python scripts/smoke_memory_aware_stamps.py

Exit code 0 = all checks passed; any failure prints FAIL and exits 1.
"""
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="memory-aware-stamps-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(
    prefix="memory-aware-stamps-smoke-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core.db import get_connection, transaction  # noqa: E402
from app.core.timeutils import utc_now, utc_now_iso  # noqa: E402
from app.core.character_ops import _score_memory_no_mutate  # noqa: E402
from app.core.memory_service import apply_extracted_memories  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402
from app.models.memory import add_memory, load_memories  # noqa: E402

FAILURES = []
CHECKED = 0

CHAR = "Demo"
LEGACY_NAIVE_TS = "2026-01-01T00:00:00"
CTX = {"source": "thought", "is_background": True}


def item(content):
    """One extraction item in the shape the extraction template produces."""
    return {"content": content, "memory_type": "semantic",
            "importance": 3, "tags": ["t"]}


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_close(label, actual, expected, tol=0.01):
    global CHECKED
    CHECKED += 1
    ok = abs(actual - expected) <= tol
    print(f"  {'OK' if ok else 'FAIL'} {label}: {actual:.5f}"
          + ("" if ok else f" — expected {expected} ±{tol}"))
    if not ok:
        FAILURES.append(label)


def check_true(label, cond, detail=""):
    global CHECKED
    CHECKED += 1
    ok = bool(cond)
    print(f"  {'OK' if ok else 'FAIL'} {label}" + (f": {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def main() -> int:
    save_character_profile(CHAR, {"name": CHAR, "language": "en"},
                           create_new=True)

    # ---------------------------------------------------------------- [1]
    print("\n[1] add_memory writes an AWARE system stamp")
    entry = add_memory(CHAR, "older text about nothing in particular",
                       memory_type="semantic", tags=["seed"])
    ts = entry.get("timestamp", "")
    check_true("returned timestamp ends in +00:00", ts.endswith("+00:00"), ts)
    check_true("load_memories carries the same stamp",
               load_memories(CHAR)[0].get("timestamp", "").endswith("+00:00"))

    # ---------------------------------------------------------------- [2]
    print("\n[2] apply_extracted_memories stores a new item")
    check("one new semantic item",
          apply_extracted_memories(CHAR, [item("sunlight on the harbour wall")],
                                   CTX), 1)

    # ---------------------------------------------------------------- [3]
    print("\n[3] the same item again is deduped")
    check("identical content is skipped",
          apply_extracted_memories(CHAR, [item("sunlight on the harbour wall")],
                                   CTX), 0)

    # ---------------------------------------------------------------- [4]
    print("\n[4] a naive LEGACY stamp does not break the run")
    with transaction() as conn:
        conn.execute("UPDATE memories SET ts=? WHERE character_name=?",
                     (LEGACY_NAIVE_TS, CHAR))
    check_true("every row is naive now",
               all(not r[0].endswith("+00:00") for r in get_connection().execute(
                   "SELECT ts FROM memories WHERE character_name=?",
                   (CHAR,)).fetchall()))
    check("a fresh item still stores",
          apply_extracted_memories(CHAR, [item("rain against the workshop shutters")],
                                   CTX), 1)

    # ---------------------------------------------------------------- [5..7]
    print("\n[5] _score_memory_no_mutate on a fresh aware stamp")
    check_close("score of a brand-new memory",
                _score_memory_no_mutate({"timestamp": utc_now_iso(),
                                         "importance": 3, "content": "x",
                                         "tags": []}), 6.0)

    print("\n[6] the same entry ten days old")
    ten_days_aware = (utc_now() - timedelta(days=10)).isoformat()
    check_close("score at ten days",
                _score_memory_no_mutate({"timestamp": ten_days_aware,
                                         "importance": 3, "content": "x",
                                         "tags": []}), 2.38)

    print("\n[7] the same ten-day-old stamp written naively")
    ten_days_naive = ten_days_aware.replace("+00:00", "")
    check_true("the legacy stamp really is naive",
               not ten_days_naive.endswith("+00:00"), ten_days_naive)
    check_close("score at ten days, legacy row",
                _score_memory_no_mutate({"timestamp": ten_days_naive,
                                         "importance": 3, "content": "x",
                                         "tags": []}), 2.38)

    print(f"\n{CHECKED} checks, {len(FAILURES)} failure(s)")
    if FAILURES:
        for f in FAILURES:
            print(f"  FAIL {f}")
        return 1
    print("all green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
