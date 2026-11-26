#!/usr/bin/env python3
"""Smoke: World Dev free mode — source-backed selects are validated (gap 22).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p1-characters.md, Task 1.
A temp world (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM. Every call goes through
``world_dev_tools.run_tool`` exactly as the agent loop calls it.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_select_sources.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Fixture: character "Demo Rider", template human-roleplay, saved with
save_character_profile(..., create_new=True) and NO animation_set /
expression_set key. The fields come from shared/templates/character/
base-character.json: animation_set is a select with source "animation_sets"
(and allow_custom, which the source overrides), expression_set a select with
source "expression_sets", tts_voice a select with neither options nor source.

Run 1, turn 1 (update_character{name: "Demo Rider", patch: ...}):

  (a) {animation_set: "dancer"} -> ok False; the line lists
      `"", "animal", "female", "male"` — animation_sets.BASE_SETS
      ("female", "male", "animal") sorted, the clips dir is empty so no
      discovered set is added; "" (= derived automatically) comes first.
  (b) {animation_set: "male"} -> ok; profile animation_set == "male".
  (c) {animation_set: ""} -> ok; profile animation_set == "".
  (d) {expression_set: "nope"} -> refused; the line names every key of
      expression_sets.sets_payload() — RUNTIME source: the shipped expression
      catalog (shared + this temp world's empty overrides), read here because
      the catalog is data, not code. At least one key must exist.
  (e) {expression_set: <first catalog key, sorted>} -> ok, stored.
  (f) {tts_voice: "x"} -> refused, the line contains "character editor"
      (its values come from live TTS backends the tool cannot check);
      the character config is unchanged.
  (h) {animation_set: ["male"]} and {animation_set: 5} -> refused (a source
      select takes a string only); the line lists the same values as (a).
  (i) a clip file <clips>/dancer/idle.fbx is created (the set is the ONE
      subdirectory level, CLAUDE.md "Shared animation clips") and the clip
      caches are reloaded (the library writer's contract), then
      {animation_set: "dancer"} -> ok, stored — the value refused in (a) is
      now a discovered set; a following refused call lists
      `"", "animal", "dancer", "female", "male"`.
  Refused calls (a), (d), (f), (h) leave journal rows of kind "refused" only.
  Second fixture "Demo Pilot", saved BEFORE the run with animation_set
  "female"; in turn 1 it is set to "dancer" -> ok.
  (g) discard_preview(run) == [] before the undo — every write of this run
      is an update of an existing character, nothing was created, so nothing
      is listed as going (discard_preview must agree with undo).
      undo(run, turn=1) -> complete; "Demo Rider" has neither animation_set
      nor expression_set again (they were never set before the run), and
      "Demo Pilot" has animation_set == "female" again (the stored old value).
      Whole-state check: the full profile AND config of BOTH characters equal
      the snapshots taken right before create_run.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_sel_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_sel_"))
paths.init(STORAGE)
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core.expression_sets import sets_payload  # noqa: E402
from app.models.character import (get_character_config,  # noqa: E402
                                  get_character_profile, save_character_profile)

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


NAME = "Demo Rider"
save_character_profile(NAME, {"name": NAME, "template": "human-roleplay"},
                       create_new=True)
prof0 = get_character_profile(NAME) or {}
check("fixture: no animation_set / expression_set",
      "animation_set" not in prof0 and "expression_set" not in prof0, prof0)
cfg0 = get_character_config(NAME) or {}

PILOT = "Demo Pilot"
save_character_profile(PILOT, {"name": PILOT, "template": "human-roleplay",
                               "animation_set": "female"}, create_new=True)
check("fixture: Demo Pilot animation_set female",
      (get_character_profile(PILOT) or {}).get("animation_set") == "female")

snap0 = {n: (get_character_profile(n), get_character_config(n)) for n in (NAME, PILOT)}

run = wr.create_run("selects", "m", "p", "u", 40, 300000)
ctx = wt.ToolCtx(run_id=run, turn=1)


def update(patch):
    return wt.run_tool(ctx, "update_character", {"name": NAME, "patch": patch})


def newest_kind():
    return wr.steps(run)[-1]["kind"]


# (a)
res = update({"animation_set": "dancer"})
check("(a) unknown animation set refused", not res.ok and not res.wrote, res)
check("(a) line lists \"\", BASE_SETS sorted",
      '"", "animal", "female", "male"' in res.line, res.line)
check("(a) journal kind refused", newest_kind() == "refused")

# (b)
res = update({"animation_set": "male"})
check("(b) male ok", res.ok and res.wrote, res)
check("(b) stored", (get_character_profile(NAME) or {}).get("animation_set") == "male")

# (c)
res = update({"animation_set": ""})
check("(c) empty ok", res.ok, res)
check("(c) stored \"\"", (get_character_profile(NAME) or {}).get("animation_set") == "")

# (d)
keys = sorted(sets_payload())
check("(d) the catalog has at least one set", len(keys) >= 1, keys)
res = update({"expression_set": "nope"})
check("(d) unknown expression set refused", not res.ok and not res.wrote, res)
check("(d) line names every catalog key",
      all(f'"{k}"' in res.line for k in keys), (keys, res.line))
check("(d) journal kind refused", newest_kind() == "refused")

# (e)
first = keys[0] if keys else "?"
res = update({"expression_set": first})
check("(e) catalog key ok", res.ok and res.wrote, res)
check("(e) stored", (get_character_profile(NAME) or {}).get("expression_set") == first)

# (f)
res = update({"tts_voice": "x"})
check("(f) tts_voice refused", not res.ok and not res.wrote, res)
check("(f) line points to the character editor", "character editor" in res.line, res.line)
check("(f) config unchanged", (get_character_config(NAME) or {}) == cfg0)
check("(f) journal kind refused", newest_kind() == "refused")

# (h)
for bad in (["male"], 5):
    res = update({"animation_set": bad})
    check(f"(h) non-string {bad!r} refused", not res.ok and not res.wrote, res)
    check(f"(h) {bad!r}: line lists the values",
          '"", "animal", "female", "male"' in res.line, res.line)
    check(f"(h) {bad!r}: journal kind refused", newest_kind() == "refused")

# (i)
(CLIPS / "dancer").mkdir()
(CLIPS / "dancer" / "idle.fbx").write_bytes(b"")
# The clip library's fingerprint is memoised for 5 s (animation_clips
# _FINGERPRINT_TTL_S); an in-process library writer drops it — without this
# a slow run (several smokes in parallel) still saw the empty library.
from app.core.animation_clips import reload_clip_caches  # noqa: E402

reload_clip_caches()
res = update({"animation_set": "dancer"})
check("(i) discovered set accepted", res.ok and res.wrote, res)
check("(i) stored", (get_character_profile(NAME) or {}).get("animation_set") == "dancer")
res = update({"animation_set": "nope"})
check("(i) refusal lists the discovered set",
      '"", "animal", "dancer", "female", "male"' in res.line, res.line)

res = wt.run_tool(ctx, "update_character",
                  {"name": PILOT, "patch": {"animation_set": "dancer"}})
check("Demo Pilot -> dancer ok", res.ok and res.wrote, res)
check("Demo Pilot stored dancer",
      (get_character_profile(PILOT) or {}).get("animation_set") == "dancer")

# (g)
prev = wu.discard_preview(run)
check("(g) discard_preview lists nothing (updates only)", prev == [], prev)
rep = wu.undo(run, turn=1)
check("(g) undo complete", rep["complete"], rep)
prof = get_character_profile(NAME) or {}
check("(g) animation_set / expression_set absent again",
      "animation_set" not in prof and "expression_set" not in prof, prof)
check("(g) Demo Pilot animation_set back to \"female\"",
      (get_character_profile(PILOT) or {}).get("animation_set") == "female",
      get_character_profile(PILOT))
for n in (NAME, PILOT):
    now = (get_character_profile(n), get_character_config(n))
    check(f"(g) {n}: whole profile + config equal the pre-run snapshot",
          now == snap0[n], (snap0[n], now))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("all ok")
