#!/usr/bin/env python3
"""Smoke run: the duration estimate reads a BOUNDED window, not the whole
retention bucket (LLM-8).

Usage:
    ./.venv/bin/python scripts/smoke_llm_stats_window.py

Runs WITHOUT the server and against a THROWAWAY world DB: the storage root is
a temp dir set through ``paths.init`` BEFORE the first app import, so the
``world.db`` this creates is under /tmp and is deleted at the end. No network,
no LLM.

The finding
---------------------------------------------------------------------------
``_fetch_bucket`` passed ``_BUCKET_LIMIT`` — the RETENTION limit, 5000 — as
its SQL ``LIMIT``, although the constant's own docstring says the estimator
needs only the last ~200. ``estimate_duration`` calls it up to three times
(the (model,task,provider) -> (model,*,provider) -> (model,task,*) fallback
chain) and then runs three medians and a full sort over each result, per LLM
call, before the call itself starts.

Expected values, derived by hand from app/utils/llm_stats.py
---------------------------------------------------------------------------
* ``_READ_WINDOW`` is the read limit and is 200; ``_BUCKET_LIMIT`` (5000)
  must only appear in the DELETE of ``record_call``.
* 700 recorded calls for one (model, task, provider) exceed the window, so
  ``estimate_duration(...)["samples"]`` must be exactly 200 — with the old
  code it was 700 (and up to 5000 in production).
* The numbers are chosen so the WINDOW and the FULL bucket disagree: 500 rows
  of 1.0 s are written first, then 200 rows of 3.0 s, all with
  in_tokens = out_tokens = 100. The window is the 200 most recent rows
  (``ORDER BY ts DESC``), i.e. the 3.0-s ones alone -> median 3.0, and with
  in_tokens = median_in the ratio is 1.0, so ``est_duration_s`` = 3.0. Over
  all 700 rows the median sits among the 500 one-second rows -> 1.0. So 3.0
  proves the window, 1.0 proves the old full read.
* Recency: 200 further rows of 5.0 s written LAST must move the window
  entirely onto them -> est 5.0, while the full bucket of 900 would still say
  1.0.
* ``source`` stays "task" — the first, exact bucket has far more than the
  five samples ``_MIN_TASK_SAMPLES`` asks for.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

_TMP = Path(tempfile.mkdtemp(prefix="smoke_llm_stats_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(_TMP / "clips")
from app.core import paths  # noqa: E402

paths.init(_TMP)
assert paths.get_storage_dir() == _TMP.resolve(), paths.get_storage_dir()

from app.core import db  # noqa: E402
from app.utils import llm_stats  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{(' — ' + detail) if detail else ''}")
        failures.append(label)


def _insert(model: str, task: str, provider: str, n: int, duration: float,
            start_index: int) -> None:
    """Writes n rows directly — record_call would be fine too, but the
    timestamp has to be controlled so "most recent" is unambiguous."""
    with db.transaction() as conn:
        for i in range(n):
            n_ = start_index + i
            ts = (f"2026-01-01T{n_ // 3600:02d}:"
                  f"{(n_ // 60) % 60:02d}:{n_ % 60:02d}")
            conn.execute(
                "INSERT INTO llm_call_stats "
                "(ts, model, task, provider, agent_name, in_tokens, "
                " out_tokens, max_tokens, duration_s) "
                "VALUES (?, ?, ?, ?, '', 100, 100, 0, ?)",
                (ts, model, task, provider, duration))


def main() -> int:
    print("smoke_llm_stats_window")
    print(f"  storage (throwaway): {_TMP}")
    db.init_schema()

    print("\n1. The constants say what they are for")
    window = getattr(llm_stats, "_READ_WINDOW", None)
    check("_READ_WINDOW is 200", window == 200, str(window))
    check("_BUCKET_LIMIT (retention) is still 5000",
          getattr(llm_stats, "_BUCKET_LIMIT", None) == 5000,
          str(getattr(llm_stats, "_BUCKET_LIMIT", None)))
    src = (REPO / "app" / "utils" / "llm_stats.py").read_text(encoding="utf-8")
    fetch_src = src.split("def _fetch_bucket", 1)[1]
    check("_fetch_bucket binds _READ_WINDOW, not _BUCKET_LIMIT",
          "_READ_WINDOW" in fetch_src and "_BUCKET_LIMIT" not in fetch_src)

    print("\n2. The estimate reads at most the window")
    # 500 rows of 1.0 s first, then 200 of 3.0 s. Window (200 newest) -> 3.0,
    # full bucket (700) -> 1.0.
    _insert("m", "chat_stream", "P", 500, 1.0, 0)
    _insert("m", "chat_stream", "P", 200, 3.0, 500)
    est = llm_stats.estimate_duration("m", "chat_stream", "P", in_tokens=100)
    check("an estimate comes back", est is not None)
    if est:
        check(f"samples == 200 (700 rows written), got {est['samples']}",
              est["samples"] == 200)
        check(f"source == 'task', got {est['source']!r}", est["source"] == "task")
        check(f"est_duration_s == 3.0 (window), not 1.0 (full bucket), "
              f"got {est['est_duration_s']}",
              abs(est["est_duration_s"] - 3.0) < 1e-9)

    print("\n3. The window follows the NEWEST rows")
    # 200 further rows of 5.0 s, written last -> the window is those alone.
    _insert("m", "chat_stream", "P", 200, 5.0, 700)
    est = llm_stats.estimate_duration("m", "chat_stream", "P", in_tokens=100)
    if est:
        check(f"est_duration_s == 5.0 (window), not 1.0 (full bucket), "
              f"got {est['est_duration_s']}",
              abs(est["est_duration_s"] - 5.0) < 1e-9)
        check(f"samples still 200, got {est['samples']}", est["samples"] == 200)

    print("\n4. Nothing comparable -> None (unchanged)")
    check("unknown model gives None",
          llm_stats.estimate_duration("nope", "chat_stream", "P", 100) is None)
    check("empty model gives None",
          llm_stats.estimate_duration("", "chat_stream", "P", 100) is None)

    shutil.rmtree(_TMP, ignore_errors=True)
    print()
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print(f"  {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
