#!/usr/bin/env python3
"""Smoke: the figure-poll measurement points (plan 2026-11-24-figure-poll-caches, Task 0) —
``read_scope.measure`` / ``read_scope.tally`` and the ``hot_path_stats`` counters "figure_memo" and the
record "figure_compute" of ``figure_build.figure_info``.

Usage: ./.venv/bin/python scripts/smoke_figure_poll_stats.py

Runs on a throw-away world: ``paths.init(<tmp>)`` / ``paths.init_instance(<tmp>)`` before any world-DB
module is imported. No server, no LLM, no HTTP. ``hot_path_stats.count`` / ``record`` are replaced by
recorders, so nothing is logged and the calls are counted exactly.

Expected, by hand:

[M1] In ``with measure() as c``: tally("a") x3, tally("b") x1 -> c == {"a": 3, "b": 1}.
[M2] tally("a") outside any scope does not raise; a scope opened afterwards starts with {} (nothing
     was stored for it).
[M3] Nested: outer tally("a") once, then inside the inner scope tally("a") x2 -> inner {"a": 2},
     outer {"a": 1 + 2} = {"a": 3} (the outer scope counts the inner calls too).
[M4] A threading.Thread started inside a scope calls tally("a") -> the scope stays {} (a new thread
     starts with an empty context, it inherits no scope).
[M5] Character "demo" (no pipeline parts: no base body, nothing worn; its model_refs/ and model3d/
     directories already exist — the very first figure read creates them, and their stat is part of
     _info_key, so without them the second call would miss once more). figure_info("demo") twice,
     nothing written in between -> the first call misses (cold computation), the second hits the
     memo (same _info_key, within MEMO_TTL_S = 30 s): count("figure_memo", ...) calls
     == [info_miss, info_hit], and exactly ONE record("figure_compute", d) (only the cold call is
     measured) whose keys are the seven {info_ms, drape_state, cut_key, read_record, garment_fsig,
     get_item, profile}, every value >= 0.
[M6] Memo emptied, _figure_info patched to call figure.invalidate() first and then the original:
     the key was taken at generation g, the computation moves it to g + 1, so the answer is not
     stored -> counts [info_miss, info_unstored] (info_miss counts every cold computation,
     info_unstored the ones whose result could not be stored) and one record. Patch removed, the
     next call takes its key at g + 1, finds no memo entry -> [info_miss] again and a second
     record; a third call then hits -> [info_hit] (the second answer was stored).
     Totals: info_miss 2, info_unstored 1, info_hit 1, records 2.
"""
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
KEYS = {"info_ms", "drape_state", "cut_key", "read_record", "garment_fsig", "get_item", "profile"}


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def scope_cases() -> None:
    from app.core.read_scope import measure, tally
    with measure() as c:
        tally("a")
        tally("a")
        tally("a")
        tally("b")
    check("[M1] three a, one b", c, {"a": 3, "b": 1})

    raised = None
    try:
        tally("a")
    except Exception as e:  # noqa: BLE001
        raised = e
    check("[M2] tally outside a scope raises nothing", raised, None)
    with measure() as c2:
        pass
    check("[M2] a later scope starts empty", c2, {})

    with measure() as outer:
        tally("a")
        with measure() as inner:
            tally("a")
            tally("a")
    check("[M3] inner scope", inner, {"a": 2})
    check("[M3] outer scope counts the inner calls too", outer, {"a": 3})

    with measure() as c4:
        t = threading.Thread(target=tally, args=("a",))
        t.start()
        t.join()
    check("[M4] a thread inherits no scope", c4, {})


def figure_cases(tmp: Path) -> None:
    os.environ["STORAGE_DIR"] = str(tmp / "world")
    os.environ["INSTANCE_DIR"] = str(tmp / "instance")
    os.environ["ANIMATION_CLIPS_DIR"] = str(tmp / "clips")
    os.environ["ANIMATION_RIG_FILE"] = str(tmp / "reference.fbx")
    from app.core import paths
    paths.init(tmp / "world")
    paths.init_instance(tmp / "instance")
    paths.get_config_path().write_text(json.dumps({}))
    from app.core import config
    config.load(paths.get_config_path(), instance_path=tmp / "instance/config.json")
    from app.core import db
    db.init_schema()

    from app.core import figure, figure_build, hot_path_stats
    from app.models.character import get_character_dir, save_character_profile
    check("create demo", save_character_profile("demo", {"template": "human-roleplay", "gender": "female"},
                                                create_new=True), True)
    # The first figure read creates these two directories, and their stat is part of _info_key — made
    # here, so the fixture is a character whose figure was already looked at once (see [M5]).
    for sub in ("model_refs", "model3d"):
        (get_character_dir("demo") / sub).mkdir(parents=True, exist_ok=True)

    counts, records = [], []
    hot_path_stats.count = lambda name, key: counts.append((name, key))
    hot_path_stats.record = lambda name, values: records.append((name, dict(values)))

    figure_build.figure_info("demo")
    figure_build.figure_info("demo")
    check("[M5] memo counts", counts, [("figure_memo", "info_miss"), ("figure_memo", "info_hit")])
    check("[M5] one figure_compute record", [n for n, _ in records], ["figure_compute"])
    d = records[0][1] if records else {}
    check("[M5] its seven keys", set(d), KEYS)
    check("[M5] all values >= 0", bool(d) and all(isinstance(v, (int, float)) and v >= 0 for v in d.values()), True)

    counts.clear()
    records.clear()
    with figure_build._info_lock:
        figure_build._info_memo.clear()
    real = figure_build._figure_info

    def moving(character_name, **kw):
        figure.invalidate()
        return real(character_name, **kw)

    figure_build._figure_info = moving
    try:
        figure_build.figure_info("demo")
    finally:
        figure_build._figure_info = real
    check("[M6] a write during the computation", counts,
          [("figure_memo", "info_miss"), ("figure_memo", "info_unstored")])
    check("[M6] nothing stored", "demo" in figure_build._info_memo, False)
    counts.clear()
    figure_build.figure_info("demo")
    check("[M6] the next call misses again", counts, [("figure_memo", "info_miss")])
    counts.clear()
    figure_build.figure_info("demo")
    check("[M6] then it is stored and hits", counts, [("figure_memo", "info_hit")])
    check("[M6] one record per cold computation", len(records), 2)


def main() -> int:
    scope_cases()
    with tempfile.TemporaryDirectory(prefix="figure-poll-stats-") as tmp:
        figure_cases(Path(tmp))
    print("\nALL OK" if not FAILS else f"\nFAILED: {FAILS}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
