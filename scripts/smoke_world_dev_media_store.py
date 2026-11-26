#!/usr/bin/env python3
"""Smoke: World Dev free mode — media storage (world_dev_runs, media lane rows).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-media.md, Task 3. Temp
worlds only (paths.init BEFORE any world-DB import); no server, no LLM, no
render.

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

  (a) RUN SWITCH + MEDIA STATE. The new columns default to
      ``media_enabled = 1`` and ``media_state = 'open'`` and ``create_run``
      defaults ``media_enabled=True`` → ``get_run`` reports ``True`` (a bool,
      mapped by ``_run_dict``) and ``"open"``. ``create_run(...,
      media_enabled=False)`` in a SECOND world dir (the first holds the one
      open run) → ``False``. ``set_media_enabled(r, False/True)`` flips it;
      ``set_media_state`` accepts open · accepted · closed and raises
      ValueError for anything else (state unchanged).

  (b) BASELINES. ``note_baseline`` is INSERT OR IGNORE: the first call for
      (r, location, loc_a) stores {"day:": "x"} and returns True; a second
      call with {"day:": "y"} returns False and the stored value stays
      {"day:": "x"}. A ``None`` baseline is stored as ``None`` (created by
      the run). ``mark_created`` UPSERTs NULL, so loc_a's {"day:": "x"}
      becomes ``None``; on an element without a row it inserts ``None``.
      Baselines are per run: r2 sees none of r's.

  (c) MEDIA ROWS. Fresh world → AUTOINCREMENT ids start at 1: two rows for
      r, one for r2 → ids 1, 2, 3. ``oldest_queued_row`` spans ALL runs and
      takes the lowest id → 1. ``media_rows(r, statuses=("queued",))`` →
      [1, 2]. ``update_media_row(1, status="running")`` → r's queued rows
      [2] and the oldest queued row across runs is 2. Steps/produced are
      JSON-decoded (produced of a new row = []); ``scheduled_turn`` is
      stored as given; ``kind`` / ``target_id`` filters narrow the list
      (r, character → [2]); ``media_rows(r, statuses=("queud",))`` →
      ValueError (a misspelled filter is not "no rows");
      ``status="bogus"`` → ValueError and the row is
      unchanged; an unknown row id → KeyError. With every row non-queued →
      None.

  (d) OLD WORLD. A world.db whose ``world_dev_runs`` is the pre-task CREATE
      (no media columns) with one row, opened through ``_Db`` (any reader):
      both columns exist and the old row reads ``media_enabled True`` /
      ``media_state "open"`` (the ALTER defaults 1 / 'open'); the two new
      tables exist.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_media_store.py
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="smoke_wd_mstore_clips_")

from app.core import paths  # noqa: E402

W1 = tempfile.mkdtemp(prefix="smoke_wd_mstore_w1_")
W2 = tempfile.mkdtemp(prefix="smoke_wd_mstore_w2_")
W3 = tempfile.mkdtemp(prefix="smoke_wd_mstore_w3_")
os.environ["STORAGE_DIR"] = W1
os.environ["INSTANCE_DIR"] = tempfile.mkdtemp(prefix="smoke_wd_mstore_inst_")
paths.init(W1)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import world_dev_runs as wr  # noqa: E402

failures = []


def check(label, cond):
    print(("  ok   " if cond else "  FAIL ") + label)
    if not cond:
        failures.append(label)


def raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc:
        return True
    except Exception as other:  # noqa: BLE001
        print(f"       (raised {type(other).__name__}: {other})")
        return False
    return False


# (a) run switch + media state
r = wr.create_run("build", "m1", "p1", "u1", 40, 300000)
run = wr.get_run(r)
check("(a) media_enabled defaults to True (bool)", run.get("media_enabled") is True)
check("(a) media_state defaults to open", run.get("media_state") == "open")
paths.init(W2)
db.init_schema()
r_off = wr.create_run("build", "m1", "p1", "u1", 40, 300000, media_enabled=False)
check("(a) create_run(media_enabled=False) -> False",
      wr.get_run(r_off)["media_enabled"] is False)
wr.set_media_enabled(r_off, True)
check("(a) set_media_enabled(True)", wr.get_run(r_off)["media_enabled"] is True)
wr.set_media_enabled(r_off, False)
check("(a) set_media_enabled(False)", wr.get_run(r_off)["media_enabled"] is False)
paths.init(W1)
for state in ("accepted", "closed", "open"):
    wr.set_media_state(r, state)
    check(f"(a) set_media_state({state})", wr.get_run(r)["media_state"] == state)
check("(a) set_media_state(paused) -> ValueError",
      raises(ValueError, wr.set_media_state, r, "paused"))
check("(a) state unchanged after the refusal", wr.get_run(r)["media_state"] == "open")

# (b) baselines
check("(b) first note_baseline -> True",
      wr.note_baseline(r, "location", "loc_a", {"day:": "x"}) is True)
check("(b) second note_baseline -> False",
      wr.note_baseline(r, "location", "loc_a", {"day:": "y"}) is False)
check("(b) first baseline kept", wr.baselines(r)[("location", "loc_a")] == {"day:": "x"})
check("(b) None baseline -> True",
      wr.note_baseline(r, "character", "Demo A", None) is True)
b = wr.baselines(r)
check("(b) None stored as None",
      ("character", "Demo A") in b and b[("character", "Demo A")] is None)
wr.mark_created(r, "location", "loc_a")
check("(b) mark_created overrides to None", wr.baselines(r)[("location", "loc_a")] is None)
wr.mark_created(r, "location", "loc_new")
b = wr.baselines(r)
check("(b) mark_created inserts None",
      ("location", "loc_new") in b and b[("location", "loc_new")] is None)
check("(b) three baselines for r", len(b) == 3)

# (c) media rows across runs
wr.set_status(r, "accepted")
r2 = wr.create_run("second", "m1", "p1", "u1", 40, 300000)
check("(b) baselines are per run", wr.baselines(r2) == {})
steps_a = [{"id": "building-front", "label": "Building front", "status": "queued",
            "note": "", "fp": "f1"}]
id1 = wr.add_media_row(r, "location", "loc_a", steps_a, scheduled_turn=1)
id2 = wr.add_media_row(r, "character", "Demo A", [{"id": "portrait"}])
id3 = wr.add_media_row(r2, "location", "loc_b", [])
check("(c) ids 1, 2, 3", [id1, id2, id3] == [1, 2, 3])
check("(c) oldest_queued_row across runs = 1", (wr.oldest_queued_row() or {}).get("id") == 1)
rows = wr.media_rows(r, statuses=("queued",))
check("(c) r's queued rows [1, 2]", [x["id"] for x in rows] == [1, 2])
check("(c) steps decoded", rows[0]["steps"] == steps_a)
check("(c) produced decoded (empty list)", rows[0]["produced"] == [])
check("(c) scheduled_turn stored",
      rows[0]["scheduled_turn"] == 1 and rows[1]["scheduled_turn"] is None)
check("(c) status queued, run/kind/target",
      (rows[0]["status"], rows[0]["run_id"], rows[0]["kind"], rows[0]["target_id"])
      == ("queued", r, "location", "loc_a"))
check("(c) kind filter", [x["id"] for x in wr.media_rows(r, kind="character")] == [2])
check("(c) target filter",
      [x["id"] for x in wr.media_rows(r, kind="location", target_id="loc_a")] == [1])
wr.update_media_row(1, status="running")
check("(c) after running: r's queued [2]",
      [x["id"] for x in wr.media_rows(r, statuses=("queued",))] == [2])
check("(c) oldest queued across runs = 2", wr.oldest_queued_row()["id"] == 2)
before = wr.media_rows(r, kind="location")[0]
check("(c) misspelled status filter -> ValueError",
      raises(ValueError, wr.media_rows, r, statuses=("queud",)))
check("(c) bogus status -> ValueError",
      raises(ValueError, wr.update_media_row, 1, status="bogus"))
check("(c) row unchanged after the refusal", wr.media_rows(r, kind="location")[0] == before)
check("(c) unknown row -> KeyError", raises(KeyError, wr.update_media_row, 99, status="done"))
wr.update_media_row(1, status="done", steps=[{"id": "building-front", "status": "done"}],
                    produced=[{"path": "a.png"}], note="ok")
row1 = wr.media_rows(r, kind="location")[0]
check("(c) update steps/produced/note",
      (row1["status"], row1["steps"], row1["produced"], row1["note"])
      == ("done", [{"id": "building-front", "status": "done"}], [{"path": "a.png"}], "ok"))
check("(c) updated_at/created_at stamped", bool(row1["updated_at"]) and bool(row1["created_at"]))
wr.update_media_row(2, status="cancelled")
wr.update_media_row(3, status="removed")
check("(c) no queued row -> None", wr.oldest_queued_row() is None)

# (d) an old world without the media columns (pre-task CREATE + the bounds ALTER)
OLD_RUNS = """CREATE TABLE world_dev_runs (
    id               TEXT PRIMARY KEY,
    task             TEXT NOT NULL DEFAULT '',
    model            TEXT NOT NULL DEFAULT '',
    provider         TEXT NOT NULL DEFAULT '',
    user_id          TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL DEFAULT 'running',
    was_frozen       INTEGER NOT NULL DEFAULT 0,
    turn             INTEGER NOT NULL DEFAULT 0,
    steps            INTEGER NOT NULL DEFAULT 0,
    max_steps        INTEGER NOT NULL DEFAULT 0,
    max_tokens_total INTEGER NOT NULL DEFAULT 0,
    max_tokens       INTEGER,
    effort           TEXT NOT NULL DEFAULT '',
    tokens_in        INTEGER NOT NULL DEFAULT 0,
    tokens_out       INTEGER NOT NULL DEFAULT 0,
    cost_total       REAL NOT NULL DEFAULT 0,
    backup_path      TEXT NOT NULL DEFAULT '',
    note             TEXT NOT NULL DEFAULT '',
    skipped_json     TEXT NOT NULL DEFAULT '[]',
    created_at       TEXT NOT NULL,
    ended_at         TEXT,
    bounds           TEXT
)"""
old = sqlite3.connect(str(Path(W3) / "world.db"))
old.execute(OLD_RUNS)
old.execute("INSERT INTO world_dev_runs (id, status, created_at) "
            "VALUES ('wdr_old', 'accepted', '2026-01-01T00:00:00Z')")
old.commit()
old.close()
paths.init(W3)
old_run = wr.get_run("wdr_old")
check("(d) old row media_enabled True", (old_run or {}).get("media_enabled") is True)
check("(d) old row media_state open", (old_run or {}).get("media_state") == "open")
conn = sqlite3.connect(str(Path(W3) / "world.db"))
cols = {c[1] for c in conn.execute("PRAGMA table_info(world_dev_runs)")}
tables = {t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
conn.close()
check("(d) both columns exist", {"media_enabled", "media_state"} <= cols)
check("(d) media tables exist", {"world_dev_media", "world_dev_media_baseline"} <= tables)

if failures:
    print(f"\nFAILED: {len(failures)}")
    sys.exit(1)
print("\nall ok")
