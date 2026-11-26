#!/usr/bin/env python3
"""Smoke: World Dev free mode — soul sections are journaled and restored
byte-exact (plan docs/superpowers/plans/2026-11-25-world-dev-free-fixes.md,
Task 9, F8c).

A temp world (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM. Tool calls go through
``world_dev_tools.run_tool`` exactly as the agent loop calls them.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_soul_raw.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------
Fixture: "Demo Ada" (human-roleplay, created through apply_character). Its
template field character_personality has source_file "soul/personality.md"
(shared/templates/character/*.json, read by hand), so REL =
"soul/personality.md" and the patch key is "soul:character_personality".
The file is then overwritten with the raw bytes b"Line one\r\nLine two\r\n"
(a hand-edited file saved with Windows line ends).

  (a) update_character{Demo Ada, {"soul:character_personality":
      "Line one\nLine three"}} -> ok; the file bytes are
      b"Line one\nLine three\n" (the tool stores text.rstrip() + "\n",
      encoded as is); exactly one restore_soul journal row whose
      before_text is "Line one\r\nLine two\r\n" (the RAW text, CRLF kept —
      read_text's universal newlines would have given "Line one\nLine two\n");
      the result line names "soul soul/personality.md".
  (b) wu.undo(run) -> complete; the file bytes are exactly
      b"Line one\r\nLine two\r\n" again.
  (c) on that restored file a new run sends
      {"soul:character_personality": "Line one\nLine two"} -> after newline
      normalisation (CRLF/CR -> LF) the old text "Line one\nLine two\n" equals
      the new "Line one\nLine two\n", so nothing is written: the line says
      "soul soul/personality.md unchanged", the bytes are still the CRLF
      bytes, and the run has 0 restore_soul rows (the count before the call
      was 0 too).
  (d) the file is set to b"Solo" (no trailing newline); update to
      "Solo two" -> bytes b"Solo two\n"; undo -> bytes b"Solo" exactly
      (write_text would have stored b"Solo\n").
  (e) the file is b"Solo" again; update to "Solo  " -> stored form would be
      "Solo\n"; both sides LF-normalised and right-stripped are "Solo", so
      nothing is written: line "soul soul/personality.md unchanged", bytes
      still b"Solo", 0 journal rows, res.wrote False.
  (f) discard_preview agrees with the undo on a foreign rewrite: on the CRLF
      file a run updates to "Line one\nLine three" (as in (a)). Before any
      foreign change discard_preview has NO line starting with "soul " (the
      undo puts the section back — nothing goes). Then the file is rewritten
      to b"Line one\r\nLine three\r\n" (same text, CRLF ends — a Windows
      editor's save). The raw text now differs from the written
      "Line one\nLine three\n", so discard_preview has exactly the line
      'soul soul/personality.md of "Demo Ada" was changed since — the discard
      leaves it alone', and the undo skips seq 1 (complete False) leaving the
      CRLF-three bytes untouched.
"""
import os
import shutil
import sys
import tempfile
import atexit
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_soulraw_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_soulraw_"))
paths.init(STORAGE)
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import soul_writer  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core.world_dev_apply import apply_character  # noqa: E402
from app.models.character import character_row_exists  # noqa: E402
from app.models.character_template import invalidate_source_file  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


NAME, REL, KEY = "Demo Ada", "soul/personality.md", "soul:character_personality"
CRLF = b"Line one\r\nLine two\r\n"

apply_character({"character_name": NAME, "template": "human-roleplay",
                 "character_personality": "calm"})
check("fixture Demo Ada", character_row_exists(NAME))
PATH = soul_writer.soul_text_path(NAME, REL)


def set_bytes(data):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_bytes(data)
    invalidate_source_file(PATH)


def soul_rows(run_id):
    return [e for e in wr.entries(run_id)
            if (e.get("inverse") or {}).get("op") == "restore_soul"]


set_bytes(CRLF)

# (a)
print("(a) update a CRLF section")
run_a = wr.create_run("soul", "m", "p", "u", 40, 300000)
res = wt.run_tool(wt.ToolCtx(run_id=run_a, turn=1), "update_character",
                  {"name": NAME, "patch": {KEY: "Line one\nLine three"}})
check("(a) ok", res.ok and res.wrote, res)
check("(a) bytes written as sent + one newline",
      PATH.read_bytes() == b"Line one\nLine three\n", PATH.read_bytes())
rows = soul_rows(run_a)
check("(a) one restore_soul row with the RAW before text",
      len(rows) == 1 and rows[0]["inverse"].get("before_text") == "Line one\r\nLine two\r\n",
      [r.get("inverse") for r in rows])
check("(a) line names the section", f"soul {REL}" in res.line
      and f"soul {REL} unchanged" not in res.line, res.line)

# (b)
print("(b) undo restores the bytes")
rep = wu.undo(run_a)
check("(b) undo complete", rep.get("complete"), rep)
check("(b) CRLF bytes back exactly", PATH.read_bytes() == CRLF, PATH.read_bytes())
wr.set_status(run_a, "rolled_back")

# (c)
print("(c) a line-end-only difference writes nothing")
run_c = wr.create_run("soul", "m", "p", "u", 40, 300000)
n0 = len(soul_rows(run_c))
res = wt.run_tool(wt.ToolCtx(run_id=run_c, turn=1), "update_character",
                  {"name": NAME, "patch": {KEY: "Line one\nLine two"}})
check("(c) ok", res.ok, res)
check("(c) line says unchanged", f"soul {REL} unchanged" in res.line, res.line)
check("(c) bytes still CRLF", PATH.read_bytes() == CRLF, PATH.read_bytes())
check("(c) no restore_soul row", n0 == 0 and len(soul_rows(run_c)) == 0,
      soul_rows(run_c))
check("(c) nothing written", not res.wrote, res)
check("(c) no journal row at all", len(wr.entries(run_c)) == 0, wr.entries(run_c))
wr.set_status(run_c, "rolled_back")

# (d)
print("(d) no trailing newline survives the undo")
set_bytes(b"Solo")
run_d = wr.create_run("soul", "m", "p", "u", 40, 300000)
res = wt.run_tool(wt.ToolCtx(run_id=run_d, turn=1), "update_character",
                  {"name": NAME, "patch": {KEY: "Solo two"}})
check("(d) ok", res.ok and res.wrote, res)
check("(d) bytes b'Solo two\\n'", PATH.read_bytes() == b"Solo two\n", PATH.read_bytes())
rep = wu.undo(run_d)
check("(d) undo complete", rep.get("complete"), rep)
check("(d) bytes b'Solo' exactly", PATH.read_bytes() == b"Solo", PATH.read_bytes())
wr.set_status(run_d, "rolled_back")

# (e)
print("(e) a final-newline / trailing-space-only difference writes nothing")
set_bytes(b"Solo")
run_e = wr.create_run("soul", "m", "p", "u", 40, 300000)
res = wt.run_tool(wt.ToolCtx(run_id=run_e, turn=1), "update_character",
                  {"name": NAME, "patch": {KEY: "Solo  "}})
check("(e) ok, nothing written", res.ok and not res.wrote, res)
check("(e) line says unchanged", f"soul {REL} unchanged" in res.line, res.line)
check("(e) bytes still b'Solo'", PATH.read_bytes() == b"Solo", PATH.read_bytes())
check("(e) no journal row", len(wr.entries(run_e)) == 0, wr.entries(run_e))
wr.set_status(run_e, "rolled_back")

# (f)
print("(f) discard_preview announces the soul skip")
set_bytes(CRLF)
run_f = wr.create_run("soul", "m", "p", "u", 40, 300000)
res = wt.run_tool(wt.ToolCtx(run_id=run_f, turn=1), "update_character",
                  {"name": NAME, "patch": {KEY: "Line one\nLine three"}})
check("(f) ok", res.ok and res.wrote, res)
soul_lines = [ln for ln in wu.discard_preview(run_f) if ln.startswith("soul ")]
check("(f) no soul line before a foreign change", soul_lines == [], soul_lines)
FOREIGN = b"Line one\r\nLine three\r\n"
set_bytes(FOREIGN)
SKIP_LINE = (f'soul {REL} of "{NAME}" was changed since — the discard '
             "leaves it alone")
soul_lines = [ln for ln in wu.discard_preview(run_f) if ln.startswith("soul ")]
check("(f) preview announces the skip", soul_lines == [SKIP_LINE], soul_lines)
rep = wu.undo(run_f)
check("(f) undo incomplete (skip)", not rep.get("complete"), rep)
check("(f) foreign bytes untouched", PATH.read_bytes() == FOREIGN, PATH.read_bytes())
wr.set_status(run_f, "rolled_back")

if failures:
    print(f"FAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("all ok")
