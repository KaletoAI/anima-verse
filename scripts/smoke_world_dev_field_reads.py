#!/usr/bin/env python3
"""Smoke: World Dev free mode — full-length single-field reads (gap 19, part 1).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p1-characters.md, Task 7.
A temp world (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM. Every call goes through
``world_dev_tools.run_tool`` exactly as the agent loop calls it.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_field_reads.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Output contract (plan Task 7, decision D8): each requested field is printed
as "<key>:" + newline + its full text. Text values are shown raw (not JSON
escaped); a soul field (template field with source_file) is the raw file
text as soul_writer.write_text stored it (``text.rstrip() + "\n"``), shown
without the trailing newline — exactly what update_character's
"soul:<key>" takes back. All requested fields share ONE budget,
MAX_FIELD_CHARS = 12000, counted as len("<key>:\n") + len(text) per field.
The field that does not fit is cut at n = (budget left) - len("<key>:\n")
characters and followed, on its own line, by
"[cut at <n> of <total> characters — ask for this field alone]"; a soul field
adds " — do not send it back as soul:<key>" before the "]". Every field after
the cut reads "<key>: (not shown — over budget)".

Key lengths used below: "character_personality" = 9 + 1 + 11 = 21 characters,
so its header "character_personality:\n" is 23; "current_feeling" = 7 + 1 + 7 =
15, header 17. character_personality is a soul field of human-roleplay
(shared/templates/character/human-roleplay.json, source_file
soul/personality.md); current_feeling is a plain profile key.

  (a) soul text TEXT_A = "# Personality\n\n## Core nature\n" + "a" * 3000
      = 13 + 2 + 14 + 1 + 3000 = 3030 characters, written via
      soul_writer.write_text -> get_character{fields: ["character_personality"]}
      contains "character_personality:\n" + TEXT_A (heading lines kept — the
      profile reader strips "# Personality", the raw read must not) and no
      "[cut". 23 + 3030 = 3053 <= 12000. The whole result is longer than the
      1500-character cap of the other read tools, so that cap is not applied.
  (b) soul text "b" * 13000 -> 23 + 13000 > 12000 -> cut at 12000 - 23 = 11977:
      "[cut at 11977 of 13000 characters — ask for this field alone — do not
      send it back as soul:character_personality]"; the shown text is exactly
      11977 "b".
  (c) fields [character_personality, current_feeling, age] with soul text
      "p" * 7000, current_feeling "q" * 7000, age 30:
      first: 23 + 7000 = 7023 <= 12000 -> whole, 12000 - 7023 = 4977 left;
      second: 17 + 7000 > 4977 -> cut at 4977 - 17 = 4960, the note WITHOUT the
      soul clause: "[cut at 4960 of 7000 characters — ask for this field alone]";
      third: "age: (not shown — over budget)".
  (d) a location with description "d" * 2000 -> get_location{fields:
      ["description", "nosuchkey"]} contains "description:\n" + "d" * 2000,
      no "[cut", and "nosuchkey: (no such field — location fields:" (it is
      neither stored nor one of the location keys); "style_hint" is a
      location key the place does not store -> "style_hint: (not set)".
      A non-text value is JSON: fields ["pos_x"] of a place at x = 12.5 ->
      "pos_x:\n12.5". The same key twice (["description", "description"])
      is answered once: "description:\n" occurs exactly 1 time.
  (e) every read call above is journalled as kind "read".
  (f) why the soul read is the RAW file (plan deviation): the text read can
      be sent back unchanged. TEXT_A is written, read, and the read text
      (everything after "character_personality:\n", since it is the only
      field) is sent as update_character{patch: {"soul:character_personality":
      <read text>}} -> the result line names "soul soul/personality.md
      unchanged" and the file bytes equal the bytes before the call. (The
      profile copy drops "# Personality", so sending THAT back would change
      the file.)
  (g) exact-fit boundary: 23 + 11977 = 12000 = the budget -> "x" * 11977 is
      whole, no "[cut"; "x" * 11978 -> 23 + 11978 = 12001 > 12000 -> cut at
      12000 - 23 = 11977: "[cut at 11977 of 11978 characters — ...".
  (h) a key that names no field reads "(no such field", not "(not set)":
      "nosuchfield" is neither a human-roleplay template field nor a stored
      profile/config key -> "nosuchfield: (no such field — describe_template";
      a template field of human-roleplay that is never stored here
      ("birthday") stays "birthday: (not set)". The write
      spelling "soul:character_personality" reads the same text as the bare key
      (answered under the bare key); "soul:nosuch" ->
      "soul:nosuch: (no such soul field in template human-roleplay".
  (i) the placeholder lines are not counted against MAX_FIELD_CHARS, so the
      list is capped: MAX_READ_FIELDS = 30 -> 30 names are answered, 31 are
      refused ("at most 30 fields per read"), 3000 names (the acceptance
      probe that produced 64902 characters) refused; a name longer than
      MAX_FIELD_KEY_CHARS = 80 is refused. Same cap for get_location.
  (j) one spelling for "nothing there": a stored age None and a stored
      current_feeling "" read "age: (not set)" / "current_feeling: (not set)",
      like an absent template field; an empty soul file reads
      "character_personality: (not set)". The same soul field asked for bare
      AND as soul:character_personality with soul text "j" * 7000 is answered
      once: "character_personality:\n" occurs 1 time and nothing is cut
      (23 + 7000 = 7023 <= 12000; twice would be 14046 > 12000 and cut).
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_fields_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_fields_"))
paths.init(STORAGE)
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import soul_writer  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.models.character import (get_character_profile,  # noqa: E402
                                  save_character_profile)
from app.models.world import upsert_location  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


run = wr.create_run("fields", "m", "p", "u", 40, 300000)
ctx = wt.ToolCtx(run_id=run, turn=1)


def call(name, args):
    res = wt.run_tool(ctx, name, args)
    check(f"(e) {name} journalled as read", wr.steps(run)[-1]["kind"] == "read",
          wr.steps(run)[-1]["kind"])
    return res


NAME = "Demo Reader"
SOUL = "soul/personality.md"
check("fixture character", save_character_profile(
    NAME, {"template": "human-roleplay"}, create_new=True))
check("budget constant", getattr(wt, "MAX_FIELD_CHARS", None) == 12000, getattr(wt, "MAX_FIELD_CHARS", None))

# (a)
TEXT_A = "# Personality\n\n## Core nature\n" + "a" * 3000
check("(a) TEXT_A is 3030 characters", len(TEXT_A) == 3030, len(TEXT_A))
soul_writer.write_text(NAME, SOUL, TEXT_A)
res = call("get_character", {"name": NAME, "fields": ["character_personality"]})
check("(a) ok", res.ok, res.line[:300])
check("(a) whole raw text", "character_personality:\n" + TEXT_A in res.line, res.line[:200])
check("(a) not cut", "[cut" not in res.line, res.line[-200:])
check("(a) longer than the 1500 cap", len(res.line) > 1500, len(res.line))

# (b)
soul_writer.write_text(NAME, SOUL, "b" * 13000)
res = call("get_character", {"name": NAME, "fields": ["character_personality"]})
check("(b) cut note", "[cut at 11977 of 13000 characters — ask for this field alone"
      " — do not send it back as soul:character_personality]" in res.line, res.line[-200:])
check("(b) exactly 11977 shown",
      ("character_personality:\n" + "b" * 11977 + "\n[cut") in res.line, res.line[:60])

# (c)
soul_writer.write_text(NAME, SOUL, "p" * 7000)
prof = get_character_profile(NAME) or {}
prof["current_feeling"] = "q" * 7000
prof["age"] = 30
check("(c) fixture saved", save_character_profile(NAME, prof))
res = call("get_character", {"name": NAME,
                             "fields": ["character_personality", "current_feeling", "age"]})
check("(c) first whole", ("character_personality:\n" + "p" * 7000 + "\n") in res.line)
check("(c) second cut at 4960",
      ("current_feeling:\n" + "q" * 4960
       + "\n[cut at 4960 of 7000 characters — ask for this field alone]") in res.line,
      res.line[-200:])
check("(c) no soul clause on a plain field", "soul:current_feeling" not in res.line)
check("(c) third over budget", "age: (not shown — over budget)" in res.line, res.line[-120:])

# (d)
check("(d) fixture location", upsert_location(
    {"id": "loc_r", "name": "Demo Library", "description": "d" * 2000,
     "pos_x": 12.5, "pos_z": 0, "rooms": []}, sync_world=False))
res = call("get_location", {"id": "loc_r", "fields": ["description", "nosuchkey"]})
check("(d) whole description", "description:\n" + "d" * 2000 in res.line, res.line[:120])
check("(d) not cut", "[cut" not in res.line and "… (cut" not in res.line, res.line[-120:])
check("(d) typo is no such field", "nosuchkey: (no such field — location fields:"
      in res.line, res.line[-200:])
res = call("get_location", {"id": "loc_r", "fields": ["style_hint"]})
check("(d) unset location key", "style_hint: (not set)" in res.line, res.line)
res = call("get_location", {"id": "loc_r", "fields": ["description", "description"]})
check("(d) duplicate key answered once", res.line.count("description:\n") == 1,
      res.line.count("description:\n"))
res = call("get_location", {"id": "loc_r", "fields": ["pos_x"]})
check("(d) number as JSON", "pos_x:\n12.5" in res.line, res.line)

# (f)
soul_writer.write_text(NAME, SOUL, TEXT_A)
soul_path = soul_writer.soul_text_path(NAME, SOUL)
bytes_before = soul_path.read_bytes()
res = call("get_character", {"name": NAME, "fields": ["character_personality"]})
head = f'"{NAME}"\ncharacter_personality:\n'
check("(f) read starts with the header", res.line.startswith(head), res.line[:80])
read_back = res.line[len(head):]
check("(f) read text keeps the heading", read_back.startswith("# Personality\n"),
      read_back[:40])
res = wt.run_tool(ctx, "update_character",
                  {"name": NAME, "patch": {"soul:character_personality": read_back}})
check("(f) write-back ok", res.ok, res.line[:300])
check("(f) write-back unchanged", f"soul {SOUL} unchanged" in res.line, res.line[:300])
check("(f) file bytes identical", soul_path.read_bytes() == bytes_before)

# (g)
check("(g) MAX_FIELD_CHARS arithmetic", 23 + 11977 == wt.MAX_FIELD_CHARS)
soul_writer.write_text(NAME, SOUL, "x" * 11977)
res = call("get_character", {"name": NAME, "fields": ["character_personality"]})
check("(g) exact fit whole", ("character_personality:\n" + "x" * 11977) in res.line
      and "[cut" not in res.line, res.line[-120:])
soul_writer.write_text(NAME, SOUL, "x" * 11978)
res = call("get_character", {"name": NAME, "fields": ["character_personality"]})
check("(g) one more cuts at 11977",
      ("character_personality:\n" + "x" * 11977
       + "\n[cut at 11977 of 11978 characters — ask for this field alone") in res.line,
      res.line[-200:])

# (h)
soul_writer.write_text(NAME, SOUL, "h" * 50)
res = call("get_character", {"name": NAME, "fields": [
    "nosuchfield", "birthday", "soul:character_personality", "soul:nosuch"]})
check("(h) typo is no such field",
      "nosuchfield: (no such field — describe_template" in res.line, res.line)
check("(h) typo not 'not set'", "nosuchfield: (not set)" not in res.line)
check("(h) unset template field", "birthday: (not set)" in res.line, res.line[:300])
check("(h) soul: spelling reads the text",
      "\ncharacter_personality:\n" + "h" * 50 in res.line, res.line)
check("(h) unknown soul: spelling",
      "soul:nosuch: (no such soul field in template human-roleplay" in res.line, res.line)

# (i)
check("(i) caps", (wt.MAX_READ_FIELDS, wt.MAX_FIELD_KEY_CHARS) == (30, 80),
      (wt.MAX_READ_FIELDS, wt.MAX_FIELD_KEY_CHARS))
res = call("get_character", {"name": NAME, "fields": [f"k{i}" for i in range(30)]})
check("(i) 30 names answered", res.ok and res.line.count("(no such field") == 30,
      res.line[:200])
for n in (31, 3000):
    res = wt.run_tool(ctx, "get_character",
                      {"name": NAME, "fields": [f"k{i}" for i in range(n)]})
    check(f"(i) {n} names refused", not res.ok and "at most 30 fields per read" in res.line,
          res.line[:200])
    check(f"(i) {n} names: short answer", len(res.line) < 300, len(res.line))
res = wt.run_tool(ctx, "get_character", {"name": NAME, "fields": ["k" * 81]})
check("(i) long name refused", not res.ok and "longer than 80" in res.line, res.line[:200])
res = wt.run_tool(ctx, "get_location", {"id": "loc_r", "fields": [f"k{i}" for i in range(31)]})
check("(i) get_location capped too", not res.ok and "at most 30 fields" in res.line,
      res.line[:200])

# (j)
prof = get_character_profile(NAME) or {}
prof["age"] = None
prof["current_feeling"] = ""
check("(j) fixture saved", save_character_profile(NAME, prof))
res = call("get_character", {"name": NAME, "fields": ["age", "current_feeling"]})
check("(j) stored None reads not set", "age: (not set)" in res.line, res.line)
check("(j) stored empty string reads not set", "current_feeling: (not set)" in res.line,
      res.line)
check("(j) no null", "null" not in res.line, res.line)
soul_writer.soul_text_path(NAME, SOUL).write_text("", encoding="utf-8")
res = call("get_character", {"name": NAME, "fields": ["character_personality"]})
check("(j) empty soul file reads not set", "character_personality: (not set)" in res.line,
      res.line)
soul_writer.write_text(NAME, SOUL, "j" * 7000)
res = call("get_character", {"name": NAME, "fields": [
    "character_personality", "soul:character_personality"]})
check("(j) bare + soul: answered once",
      res.line.count("character_personality:\n") == 1, res.line.count("character_personality:\n"))
check("(j) not cut", "[cut" not in res.line and "over budget" not in res.line,
      res.line[-200:])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("all checks passed")
