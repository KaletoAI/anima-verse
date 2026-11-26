#!/usr/bin/env python3
"""Smoke: World Dev free mode — describe_template, the schema before creation (gap 3).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p1-characters.md, Task 3.
A temp world (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM. Every call goes through
``world_dev_tools.run_tool`` exactly as the agent loop calls it.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_describe_template.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

The plugin registry is CLEARED and one FAKE species package is registered
(same shape as scripts/smoke_world_dev_body_slots.py, cut to what this check
needs; the rp stats are therefore absent — status lines are Task 2's smoke):

    id smoke_species, apply_to ["human-roleplay"], body_slots:
      hair         color  select [blonde, red], allow_custom
                   length select [short, long]
      facial_hair  applies_to gender=male; style select [short beard]

The template fields come from shared/templates/character/base-character.json
merged into human-roleplay.json (label "Human (Roleplay)", outfit system on).

  (a) describe_template{template: "human-roleplay", gender: "female"} -> ok.
      Line 1, by the output contract:
        template human-roleplay (Human (Roleplay)) — outfits; keys work in
        create_character data and in update_character patch (soul fields
        there as "soul:<key>")
      The body block (_body_schema of {template, gender: female}): header
      "body slots for gender=female:", then
        hair: color=- [blonde|red|other]; length=- [short|long]
      ("-" = unset, allow_custom adds "|other"); facial_hair applies only to
      gender=male -> no facial_hair line.
  (b) gender "male" -> also "facial_hair: style=- [short beard]".
      No gender -> header "body slots (gender not given — slots that depend
      on it are left out):", the hair line, no facial_hair line.
  (c) field lines, "- <key> [<store>]: <takes>" + " — default <json>":
        importance: store config, options 1/2/3 (numbers), default 1
          -> "- importance [config]: one of 1 | 2 | 3 — default 1"
        chat_mode: store config, options "" / "rp_first", default "rp_first"
          -> '- chat_mode [config]: one of "" | "rp_first" — default "rp_first"'
        age: number, profile -> "- age [profile]: number"
        birthday: season_day -> '- birthday [profile]: "<season>:<day>"'
        character_personality: source_file -> "- character_personality [soul]: soul text"
          (no default shown for a soul field)
        tts_voice: select with neither options nor source (D1)
          -> "- tts_voice [config]: editor only"
        animation_set: source animation_sets, clips dir empty -> BASE_SETS
          sorted -> '- animation_set [profile]: one of "" | "animal" | "female" | "male"'
        away_note: text, visible_when {field: avatar_only_presence, values: ["true"]}
          -> "- away_note [config]: text (only when avatar_only_presence=true)"
      Never listed: current_location (readonly), character_name, template.
  (d) the journal row of (a) is kind "read"; the line is at most 8000
      characters (MAX_TEMPLATE_SCHEMA_CHARS) and is NOT cut ("more —" absent):
      the template has ~50 settable fields, more than the 30-line list cap
      of other read tools — the schema has its own budget.
  (e) template "npc-temporary" -> refused; the line lists the offered
      templates with "human-roleplay (outfits)" and "human-default (no outfits)".
      gender "robot" -> refused (gender is a fixed select female/male).
      An unknown argument key -> refused.
  (f) create_character{data: {name: "Demo X", wingspan: 3}} -> refused,
      the line names 'wingspan' and 'describe_template{"template":
      "human-roleplay"}'; no row "Demo X". update_character of an existing
      human-roleplay character with {wingspan: 3} -> refused with the same
      pointer.
  (g) template "human-default" -> line 1 ends the label with "— no outfits";
      the fake package does not apply to it -> "body slots: none".
  (h) order + hints: line 2 is the body header (the body block comes right
      after the header so a budget cut never takes it), then "fields:".
      A field with an editor hint gets its FIRST SENTENCE on the next line,
      indented 4: birthday's hint (base-character.json) is "Season and day
      of the world calendar, no year. Leave empty for no birthday." ->
      "    Season and day of the world calendar, no year."
      A dot after an abbreviation is no sentence end: roles' hint
      (human-roleplay.json) is "Comma-separated role tags (e.g.
      'photographer, model'). Activities with required_roles ..." -> the
      ". " after "e.g" is skipped, the next one closes the parenthesis ->
      "    Comma-separated role tags (e.g. 'photographer, model')."
      A first sentence under 12 characters runs on: social_dialog_probability's
      hint is "0-100%. Probability of conversations with other characters at
      the same location" -> "0-100%." is 7 characters, no further ". ",
      so the whole 79-character hint (under the 90 cap) is shown.
  (i) the cut path: MAX_TEMPLATE_SCHEMA_CHARS patched to 1500 -> the output
      is at most 1500 characters, still holds the hair line, and its last
      line is "… N more — the rest is cut — …" where N + the "- " field
      lines shown == the "- " field lines of the uncut output (every field
      is either shown or counted, none dropped silently).
  (j) allow_custom wording: animal-default's species is a select with
      allow_custom and options dog, cat, … (animal-default.json, first two
      "dog", "cat"), no package needed -> the line starts
      '- species [profile]: one of "dog" | "cat"' and ends
      " or another string".
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_desc_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_desc_"))
paths.init(STORAGE)
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.models.character import (character_row_exists,  # noqa: E402
                                  save_character_profile)
from app.models.character_template import clear_template_cache  # noqa: E402
from app.plugins import registry  # noqa: E402
from app.plugins.registry import BodySlotSpec, Package  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


registry.clear_registry()
registry.register_package(Package(
    id="smoke_species", dir=STORAGE, manifest={}, apply_to=["human-roleplay"],
    body_slots=[
        BodySlotSpec(id="hair", package_id="smoke_species", attributes={
            "color": {"type": "select", "options": ["blonde", "red"], "allow_custom": True},
            "length": {"type": "select", "options": ["short", "long"]},
        }),
        BodySlotSpec(id="facial_hair", package_id="smoke_species",
                     applies_to={"gender": ["male"]}, attributes={
                         "style": {"type": "select", "options": ["short beard"]},
                     }),
    ]))
clear_template_cache()

run = wr.create_run("describe", "m", "p", "u", 40, 300000)
ctx = wt.ToolCtx(run_id=run, turn=1)


def call(name, args):
    return wt.run_tool(ctx, name, args)


HAIR = "hair: color=- [blonde|red|other]; length=- [short|long]"
BEARD = "facial_hair: style=- [short beard]"

# (a)
res = call("describe_template", {"template": "human-roleplay", "gender": "female"})
lines = res.line.splitlines() if res.ok else []
check("(a) ok", res.ok, res.line[:300])
check("(a) line 1", lines[:1] == [
    'template human-roleplay (Human (Roleplay)) — outfits; keys work in create_character '
    'data and in update_character patch (soul fields there as "soul:<key>")'], lines[:1])
check("(a) body header", "body slots for gender=female:" in lines, lines[-4:])
check("(a) hair line", HAIR in lines, lines[-4:])
check("(a) no facial_hair line", not any(ln.startswith("facial_hair") for ln in lines))
check("(d) journal row kind read", wr.steps(run)[-1]["kind"] == "read", wr.steps(run)[-1]["kind"])
check("(d) at most 8000 chars", len(res.line) <= 8000, len(res.line))
check("(d) not cut", "more —" not in res.line, res.line[-300:])

# (c)
for want in (
        "- importance [config]: one of 1 | 2 | 3 — default 1",
        '- chat_mode [config]: one of "" | "rp_first" — default "rp_first"',
        "- age [profile]: number",
        '- birthday [profile]: "<season>:<day>"',
        "- character_personality [soul]: soul text",
        "- tts_voice [config]: editor only",
        '- animation_set [profile]: one of "" | "animal" | "female" | "male"',
        "- away_note [config]: text (only when avatar_only_presence=true)"):
    check(f"(c) line {want!r}", want in lines, [ln for ln in lines if ln.startswith(want[:12])])
for key in ("current_location", "character_name", "template"):
    check(f"(c) no {key} line", not any(ln.startswith(f"- {key} ") for ln in lines))

# (b)
res = call("describe_template", {"template": "human-roleplay", "gender": "male"})
check("(b) male: hair + facial_hair", res.ok and HAIR in res.line.splitlines()
      and BEARD in res.line.splitlines(), res.line[-300:])
res = call("describe_template", {})
lines = res.line.splitlines() if res.ok else []
check("(b) default template is human-roleplay",
      lines[:1] and lines[0].startswith("template human-roleplay "), lines[:1])
check("(b) no gender: header",
      "body slots (gender not given — slots that depend on it are left out):" in lines,
      lines[-4:])
check("(b) no gender: hair, no facial_hair",
      HAIR in lines and not any(ln.startswith("facial_hair") for ln in lines), lines[-4:])

# (e)
res = call("describe_template", {"template": "npc-temporary"})
check("(e) npc-temporary refused with the template list",
      not res.ok and "human-roleplay (outfits)" in res.line
      and "human-default (no outfits)" in res.line, res.line)
check("(e) refused row", wr.steps(run)[-1]["kind"] == "refused")
res = call("describe_template", {"template": "human-roleplay", "gender": "robot"})
check("(e) unknown gender refused", not res.ok and '"female"' in res.line, res.line)
res = call("describe_template", {"template": "human-roleplay", "species": "x"})
check("(e) unknown argument refused", not res.ok and "species" in res.line, res.line)

# (f)
POINTER = 'describe_template{"template": "human-roleplay"} lists the fields'
res = call("create_character", {"data": {"name": "Demo X", "wingspan": 3}})
check("(f) create unknown field refused with pointer",
      not res.ok and "'wingspan'" in res.line and POINTER in res.line, res.line)
check("(f) no Demo X", not character_row_exists("Demo X"))
save_character_profile("Demo Y", {"name": "Demo Y", "template": "human-roleplay"},
                       create_new=True)
res = call("update_character", {"name": "Demo Y", "patch": {"wingspan": 3}})
check("(f) update unknown field refused with pointer",
      not res.ok and "'wingspan'" in res.line and POINTER in res.line, res.line)

# (g)
res = call("describe_template", {"template": "human-default"})
lines = res.line.splitlines() if res.ok else []
check("(g) human-default: no outfits",
      lines[:1] and lines[0].startswith("template human-default (") and "— no outfits;" in lines[0],
      lines[:1])
check("(g) human-default: body slots none", "body slots: none" in lines, lines[-3:])

# (h)
res = call("describe_template", {"template": "human-roleplay", "gender": "female"})
full = res.line.splitlines() if res.ok else []
check("(h) line 2 is the body header", full[1:2] == ["body slots for gender=female:"], full[:3])
check("(h) fields: follows the body block",
      "fields:" in full and full.index("fields:") > full.index(HAIR), full[:6])
i_b = full.index('- birthday [profile]: "<season>:<day>"') if \
    '- birthday [profile]: "<season>:<day>"' in full else -1
check("(h) birthday hint on the next line",
      i_b >= 0 and full[i_b + 1:i_b + 2] == ["    Season and day of the world calendar, no year."],
      full[i_b:i_b + 2])
n_fields = sum(1 for ln in full if ln.startswith("- "))


def _hint_after(prefix):
    idx = [i for i, ln in enumerate(full) if ln.startswith(prefix)]
    return full[idx[0] + 1:idx[0] + 2] if idx else None


check("(h) roles hint keeps the e.g. sentence whole",
      _hint_after("- roles [") == ["    Comma-separated role tags (e.g. 'photographer, model')."],
      _hint_after("- roles ["))
check("(h) a bare range runs on to the next sentence",
      _hint_after("- social_dialog_probability [") == [
          "    0-100%. Probability of conversations with other characters at the same location"],
      _hint_after("- social_dialog_probability ["))

# (i)
_saved = wt.MAX_TEMPLATE_SCHEMA_CHARS
wt.MAX_TEMPLATE_SCHEMA_CHARS = 1500
try:
    res = call("describe_template", {"template": "human-roleplay", "gender": "female"})
finally:
    wt.MAX_TEMPLATE_SCHEMA_CHARS = _saved
cut = res.line.splitlines() if res.ok else []
check("(i) cut: at most 1500 chars", res.ok and len(res.line) <= 1500, len(res.line))
check("(i) cut: hair line kept", HAIR in cut, cut[:5])
import re  # noqa: E402
m = re.fullmatch(r"… (\d+) more — the rest is cut — .+", cut[-1]) if cut else None
check("(i) cut: tail line", m is not None, cut[-1:])
shown = sum(1 for ln in cut if ln.startswith("- "))
check("(i) cut: shown + N == all fields",
      m is not None and shown > 0 and shown + int(m.group(1)) == n_fields,
      (shown, m and m.group(1), n_fields))

# (j)
res = call("describe_template", {"template": "animal-default"})
sp = [ln for ln in res.line.splitlines() if ln.startswith("- species ")] if res.ok else []
check("(j) species allow_custom wording",
      len(sp) == 1 and sp[0].startswith('- species [profile]: one of "dog" | "cat"')
      and sp[0].endswith(" or another string"), sp or res.line[:300])

print()
if failures:
    print(f"FAILED ({len(failures)}): " + "; ".join(failures))
    sys.exit(1)
print("all describe_template checks passed")
