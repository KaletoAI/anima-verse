#!/usr/bin/env python3
"""Smoke: World Dev free mode — a rolled-back create gives the element its
first media baseline back (plan
docs/superpowers/plans/2026-11-25-world-dev-free-fixes.md, Task 5, F4).

A temp world and instance (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM, no render. Journal rows are built
with the ``world_dev_runs`` step API (begin -> complete); the undo handlers of
``delete_character`` / ``delete_location`` are replaced in
``world_dev_undo._HANDLERS`` by stubs returning ``[]`` (a smoke seam — the
handlers' own behaviour is covered by smoke_world_dev_undo.py). Every case
uses its own run (one open run at a time: the previous one is set
``accepted`` first).

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_media_baseline.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

The rule (world_dev_runs.mark_created / restore_prior_baseline,
world_dev_media.note_create_undone): ``mark_created`` keeps the FIRST dict
baseline it overrides in ``prior_json`` (COALESCE: a later override keeps the
first) and sets ``fps_json`` NULL. When the undo marks a creating entry
(inverse ``delete_location`` or a CLAIMED ``delete_character``) undone and no
not-undone creating entry of that target is left, ``fps_json`` gets
``prior_json`` back — only when ``fps_json`` is NULL and a prior exists.

  (a) note_baseline(run, character, "Demo Ada", {portrait: p1, mesh: m1});
      note_touch with the claimed delete_character inverse -> mark_created
      -> baselines()[("character", "Demo Ada")] is None.
  (b) a done turn-2 entry (seq 2, a turn-1 filler entry is seq 1) carrying
      that inverse; undo(run, 2) -> reversed [2] (the stub returns no skip);
      no creating entry left -> baseline == {portrait: p1, mesh: m1}.
  (c) two creating entries of "Demo Ada" (turn 1 seq 1, turn 2 seq 2, both
      claimed), prior dict present: undo(run, 2) -> seq 1 still stands ->
      baseline stays None; undo(run, 1) -> none left -> baseline == the dict.
  (d) "Demo Fresh": mark_created on a key without a row (insert, prior NULL)
      -> undo of its create -> baseline stays None, and
      restore_prior_baseline returns False (no prior to copy).
  (e) first prior wins: dict A {portrait: a} noted, mark_created, note_baseline
      with dict B {portrait: b} (ignored: the row exists, INSERT OR IGNORE),
      mark_created again (COALESCE keeps A) -> after undo of both create rows
      (turn 1 seq 1, turn 2 seq 2; undo of the whole run, newest first ->
      reversed [2, 1]) baseline == A.
  (f) location: as (b) with {op: delete_location, id: L1} and the prior
      {building-front: f1} -> baseline == {building-front: f1}.
  (g) an UNCLAIMED delete_character entry undone -> note_create_undone not
      called (a counting wrapper around it stays at 0): the unclaimed inverse
      never marked anything created.
  (h) GONE path: as (b), but the delete_character stub raises
      _Skip(REASON_GONE) (the character is already gone — e.g. the turn
      deleted its own create via delete_created) -> undo(run, 2) reports seq 2
      skipped with reason "already gone", reversed []; the entry is marked
      undone (no not-undone entry of turn 2 left); no not-undone creating
      entry left -> baseline == {portrait: p1, mesh: m1}.
  (j) the real handlers (no stub): note_baseline(run, character, "Demo Ada",
      {portrait: p1, mesh: m1}); turn 2 run_tool create_character "Demo Ada"
      (claimed inverse -> mark_created -> None), then run_tool delete_created
      of it in the SAME turn: _delete_created applies the creating inverse
      itself and marks that entry undone, so it calls the same hook ->
      baseline == {portrait: p1, mesh: m1} right after it; undo(run, 2) then
      finds the create entry already undone and the delete_created step has
      no inverse -> reversed [], skipped [] and the baseline stays the dict.
  (i) the column: after a second init_schema (the ALTER is idempotent)
      PRAGMA table_info(world_dev_media_baseline) lists ``prior_json``.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TMP = Path(tempfile.mkdtemp(prefix="smoke_wd_media_baseline_"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
os.environ["STORAGE_DIR"] = str(TMP / "world")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")
(TMP / "clips").mkdir(parents=True, exist_ok=True)

from app.core import paths  # noqa: E402

paths.init(TMP / "world")

from app.core import db  # noqa: E402

db.init_schema()

from app.core import world_dev_media as wm  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402

failures = []


def check(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label
          + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(label)


def _ok_stub(entry, inv):
    return []


def _gone_stub(entry, inv):
    raise wu._Skip(wu.REASON_GONE)


_REAL_DELETE_CHARACTER = wu._HANDLERS["delete_character"]
wu._HANDLERS["delete_character"] = _ok_stub
wu._HANDLERS["delete_location"] = _ok_stub

_prev = []


def new_run(task):
    for r in _prev:
        wr.set_status(r, "accepted")
    r = wr.create_run(task, "m", "p", "u", 40, 300000)
    _prev.append(r)
    return r


def entry(run, turn, inverse, target_kind, target_id):
    seq = wr.begin(run, turn, "write", "create_x", {}, target_kind, target_id, inverse)
    wr.complete(run, seq, {"ok": True}, "created")
    return seq


def filler(run, turn):
    """A turn-1 non-create write the turn-2 undo never reaches."""
    return entry(run, turn, {"op": "restore_soul", "name": "Demo Other"}, "character",
                 "Demo Other")


ADA = {"portrait": "p1", "mesh": "m1"}
CLAIMED = {"op": "delete_character", "name": "Demo Ada", "claimed": True}
KEY = ("character", "Demo Ada")

# (a) + (b)
r = new_run("b")
wr.note_baseline(r, "character", "Demo Ada", dict(ADA))
wm.note_touch(r, "character", "Demo Ada", dict(CLAIMED))
check("(a) the claimed create marks it created -> None", wr.baselines(r).get(KEY, "x") is None)
s1 = filler(r, 1)
s2 = entry(r, 2, dict(CLAIMED), "character", "Demo Ada")
check("(b) seqs 1, 2", (s1, s2) == (1, 2))
res = wu.undo(r, 2)
check("(b) undo(turn 2) reversed [2]", res["reversed"] == [2], res)
check("(b) baseline back to the prior dict", wr.baselines(r).get(KEY) == ADA, wr.baselines(r))

# (c) two creating entries
r = new_run("c")
wr.note_baseline(r, "character", "Demo Ada", dict(ADA))
wm.note_touch(r, "character", "Demo Ada", dict(CLAIMED))
entry(r, 1, dict(CLAIMED), "character", "Demo Ada")
entry(r, 2, dict(CLAIMED), "character", "Demo Ada")
res = wu.undo(r, 2)
check("(c) undo(turn 2) reversed [2]", res["reversed"] == [2], res)
check("(c) seq 1 still stands -> baseline stays None", wr.baselines(r).get(KEY, "x") is None)
res = wu.undo(r, 1)
check("(c) undo(turn 1) reversed [1]", res["reversed"] == [1], res)
check("(c) none left -> the prior dict", wr.baselines(r).get(KEY) == ADA, wr.baselines(r))

# (d) created fresh, no prior
r = new_run("d")
FRESH = {"op": "delete_character", "name": "Demo Fresh", "claimed": True}
wm.note_touch(r, "character", "Demo Fresh", dict(FRESH))
entry(r, 1, dict(FRESH), "character", "Demo Fresh")
res = wu.undo(r)
check("(d) reversed [1]", res["reversed"] == [1], res)
check("(d) baseline stays None",
      wr.baselines(r).get(("character", "Demo Fresh"), "x") is None)
check("(d) restore_prior_baseline -> False",
      wr.restore_prior_baseline(r, "character", "Demo Fresh") is False)

# (e) first prior wins
r = new_run("e")
wr.note_baseline(r, "character", "Demo Ada", {"portrait": "a"})
wr.mark_created(r, "character", "Demo Ada")
check("(e) note_baseline B ignored (row exists)",
      wr.note_baseline(r, "character", "Demo Ada", {"portrait": "b"}) is False)
wr.mark_created(r, "character", "Demo Ada")
entry(r, 1, dict(CLAIMED), "character", "Demo Ada")
entry(r, 2, dict(CLAIMED), "character", "Demo Ada")
res = wu.undo(r)
check("(e) reversed [2, 1]", res["reversed"] == [2, 1], res)
check("(e) baseline == A", wr.baselines(r).get(KEY) == {"portrait": "a"}, wr.baselines(r))

# (f) location
r = new_run("f")
LOC = {"op": "delete_location", "id": "L1"}
wr.note_baseline(r, "location", "L1", {"building-front": "f1"})
wm.note_touch(r, "location", "L1", dict(LOC))
check("(f) create marks the place created",
      wr.baselines(r).get(("location", "L1"), "x") is None)
filler(r, 1)
entry(r, 2, dict(LOC), "location", "L1")
res = wu.undo(r, 2)
check("(f) reversed [2]", res["reversed"] == [2], res)
check("(f) baseline back",
      wr.baselines(r).get(("location", "L1")) == {"building-front": "f1"}, wr.baselines(r))

# (g) unclaimed delete_character -> no call
r = new_run("g")
calls = []
_real = getattr(wm, "note_create_undone", None)


def _counting(*a, **kw):
    calls.append(a)
    return _real(*a, **kw) if _real else None


wm.note_create_undone = _counting
entry(r, 1, {"op": "delete_character", "name": "Demo Una"}, "character", "Demo Una")
res = wu.undo(r)
if _real is not None:
    wm.note_create_undone = _real
check("(g) reversed [1]", res["reversed"] == [1], res)
check("(g) note_create_undone not called", calls == [], calls)

# (h) GONE path
wu._HANDLERS["delete_character"] = _gone_stub
r = new_run("h")
wr.note_baseline(r, "character", "Demo Ada", dict(ADA))
wm.note_touch(r, "character", "Demo Ada", dict(CLAIMED))
filler(r, 1)
entry(r, 2, dict(CLAIMED), "character", "Demo Ada")
res = wu.undo(r, 2)
wu._HANDLERS["delete_character"] = _ok_stub
check("(h) reversed []", res["reversed"] == [], res)
check("(h) seq 2 skipped as already gone",
      [(s["seq"], s["reason"]) for s in res["skipped"]] == [(2, "already gone")], res)
check("(h) entry marked undone", [e["seq"] for e in wr.entries(r, turn=2)] == [])
check("(h) baseline back to the prior dict", wr.baselines(r).get(KEY) == ADA, wr.baselines(r))

# (j) real handlers: same-turn create_character + delete_created
from app.core import world_dev_tools as wt  # noqa: E402
from app.models.character import character_row_exists  # noqa: E402

wu._HANDLERS["delete_character"] = _REAL_DELETE_CHARACTER
r = new_run("j")
wr.note_baseline(r, "character", "Demo Ada", dict(ADA))
ctx = wt.ToolCtx(run_id=r, turn=2)
res = wt.run_tool(ctx, "create_character",
                  {"data": {"character_name": "Demo Ada", "template": "human-roleplay"}})
check("(j) create_character ok", res.ok and character_row_exists("Demo Ada"), res)
check("(j) the create marks it created -> None", wr.baselines(r).get(KEY, "x") is None,
      wr.baselines(r))
res = wt.run_tool(ctx, "delete_created", {"kind": "character", "id": "Demo Ada"})
check("(j) delete_created ok", res.ok and not character_row_exists("Demo Ada"), res)
check("(j) baseline back to the prior dict right after delete_created",
      wr.baselines(r).get(KEY) == ADA, wr.baselines(r))
res = wu.undo(r, 2)
check("(j) undo(turn 2) reverses / skips nothing",
      res["reversed"] == [] and res["skipped"] == [], res)
check("(j) baseline still the prior dict after the undo",
      wr.baselines(r).get(KEY) == ADA, wr.baselines(r))
wu._HANDLERS["delete_character"] = _ok_stub

# (i) the column exists after the migration (idempotent)
db.init_schema()
from app.core.db import get_connection  # noqa: E402

cols = [row[1] for row in get_connection().execute(
    "PRAGMA table_info(world_dev_media_baseline)").fetchall()]
check("(i) prior_json column present", "prior_json" in cols, cols)

if failures:
    print(f"\n{len(failures)} FAILED")
    sys.exit(1)
print("\nall ok")
