#!/usr/bin/env python3
"""Smoke: the figure-poll measuring points (plan 2026-11-24-figure-poll-caches, Task 0) —
``read_scope.measure``/``tally`` and the ``figure_memo`` / ``figure_compute`` statistics of
``figure_build.figure_info``.

Usage:
    ./.venv/bin/python scripts/smoke_figure_poll_stats.py

Runs without a server, LLM or HTTP on a throwaway world (``STORAGE_DIR`` / ``INSTANCE_DIR`` set to temp dirs and
``paths.init(<tmp>)`` BEFORE any world-DB module is imported). Expected values, by hand:

[M1] Inside ``with measure() as c``: tally("a") three times and tally("b") once -> c == {"a": 3, "b": 1}
     (one increment per call, per name).
[M2] tally("a") with no measure open is a no-op and does not raise; a measure opened afterwards starts with {}
     (nothing leaked from the call outside).
[M3] Nested: outer tally("a") once, then inner measure with tally("a") twice. The inner dict only sees its own two
     calls -> {"a": 2}; the outer counts its own one plus the inner two -> {"a": 3}.
[M4] A threading.Thread started inside a measure calls tally("a"). A new thread does not inherit the creating
     thread's context variables, so the measure's dict stays {} .
[M5] Character "demo" (no pipeline parts), hot_path_stats.count/record patched to recorders. figure_info("demo")
     twice: the first call finds no memo -> count("figure_memo", "info_miss") once and computes _figure_info
     once -> exactly one record("figure_compute", d); the second call has the same key within MEMO_TTL_S ->
     "info_hit" once, no further record. d has exactly the seven keys info_ms, drape_state, cut_key,
     read_record, garment_fsig, get_item, profile, all >= 0. One warm-up figure_info runs before (stats not yet
     patched, memo emptied after it): the first computation for a fresh character creates its model_refs /
     model3d directories and moves the figure generation, which changes the key (the directories' stat is part
     of it) — without it the second call would rightly be a miss as well.
[M6] As [M5] but on an emptied memo, with _figure_info patched to call figure.invalidate() first and then the
     original: the generation moved during the computation -> the answer is not stored -> "info_unstored" once
     (and the cold computation still records one figure_compute). The next call finds no memo -> "info_miss"
     again (the counts of that call: info_miss 1, no info_hit).
"""
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="smoke_figure_poll_stats_"))
os.environ["STORAGE_DIR"] = str(TMP / "world")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(TMP / "reference.fbx")
for d in ("world", "instance", "clips"):
    (TMP / d).mkdir()

from app.core import paths  # noqa: E402
paths.init(str(TMP / "world"))
paths.init_instance(str(TMP / "instance"))

failures = []


def check(name, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        failures.append(name)


def main() -> int:
    from app.core import read_scope
    from app.core.read_scope import measure, tally

    print("[M1] counts per name")
    with measure() as c:
        tally("a"); tally("a"); tally("a"); tally("b")
    check("M1 counts", dict(c), {"a": 3, "b": 1})

    print("[M2] outside a measure")
    try:
        tally("a")
        raised = False
    except Exception:  # noqa: BLE001
        raised = True
    check("M2 no raise", raised, False)
    with measure() as c:
        pass
    check("M2 fresh measure", dict(c), {})

    print("[M3] nested")
    with measure() as outer:
        tally("a")
        with measure() as inner:
            tally("a"); tally("a")
    check("M3 inner", dict(inner), {"a": 2})
    check("M3 outer", dict(outer), {"a": 3})

    print("[M4] no context inheritance into a thread")
    with measure() as c:
        t = threading.Thread(target=tally, args=("a",))
        t.start(); t.join()
    check("M4 thread", dict(c), {})

    from app.core import config, db
    config.load(paths.get_config_path(), instance_path=TMP / "instance" / "config.json")
    db.init_schema()
    from app.core import figure, figure_build, hot_path_stats
    from app.models.character import save_character_profile
    check("create demo", save_character_profile("demo", {"gender": "female", "age": 30}, create_new=True), True)

    counts, records = [], []
    hot_path_stats.count = lambda name, key: counts.append((name, key))
    hot_path_stats.record = lambda name, values: records.append((name, dict(values)))

    print("[M5] miss then hit")
    figure_build.figure_info("demo")  # warm-up: creates the character's directories (see docstring)
    counts.clear(); records.clear()
    figure_build._info_memo.clear()
    figure_build.figure_info("demo")
    figure_build.figure_info("demo")
    memo = [k for n, k in counts if n == "figure_memo"]
    check("M5 info_miss", memo.count("info_miss"), 1)
    check("M5 info_hit", memo.count("info_hit"), 1)
    comp = [v for n, v in records if n == "figure_compute"]
    check("M5 one record", len(comp), 1)
    keys = {"info_ms", "drape_state", "cut_key", "read_record", "garment_fsig", "get_item", "profile"}
    check("M5 keys", set(comp[0]) if comp else set(), keys)
    check("M5 all >= 0", all(v >= 0 for v in comp[0].values()) if comp else False, True)

    print("[M6] a write during the computation")
    figure_build._info_memo.clear()
    counts.clear(); records.clear()
    real = figure_build._figure_info

    def racing(*a, **kw):
        figure.invalidate()
        return real(*a, **kw)
    figure_build._figure_info = racing
    try:
        figure_build.figure_info("demo")
    finally:
        figure_build._figure_info = real
    memo = [k for n, k in counts if n == "figure_memo"]
    check("M6 info_unstored", memo.count("info_unstored"), 1)
    check("M6 one record", len([1 for n, _ in records if n == "figure_compute"]), 1)
    counts.clear()
    figure_build.figure_info("demo")
    memo = [k for n, k in counts if n == "figure_memo"]
    check("M6 next info_miss", memo.count("info_miss"), 1)
    check("M6 next info_hit", memo.count("info_hit"), 0)

    print("\nFAILED: " + ", ".join(failures) if failures else "\nall checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
