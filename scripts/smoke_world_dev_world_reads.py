#!/usr/bin/env python3
"""Smoke: World Dev free mode — world reads and the system prompt (P3 Task 1).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p3-world-systems.md, Task 1
(gap 27 part, gap 26 read part). A temp world (STORAGE_DIR / INSTANCE_DIR /
ANIMATION_CLIPS_DIR temp, paths.init BEFORE any world-DB import), an empty
world config; no server, no LLM. Tool calls go through
``world_dev_tools.run_tool`` exactly as the agent loop calls them.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_world_reads.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

The world config is ``{}``: no ``game_calendar`` / ``game_seasons``, so
``game_time.get_calendar()`` is ``Calendar.default()`` — the four seasons of
``_DEFAULT_SEASONS`` in app/core/game_time.py,
    ("spring", "Spring"), ("summer", "Summer"), ("autumn", "Autumn"),
    ("winter", "Winter"),
each ``days=30``, ``week_days=()``.

Fixture: characters "Demo A" (profile language "en"), "Demo B" ("en"),
"Demo C" (no language key — ``get_character_language`` would answer "de" for
it, the raw stored key is empty), "Demo D" (no language key) and "Demo E"
("fr") both linked to Demo A through ``linked_characters.link`` — a newly
linked body becomes dormant (``make_dormant``), Demo A stays in the world
(empty status); "Demo F" ("de", unlinked); "Demo G" (no key) leading
"Demo H" (no key). Demo E is saved BEFORE Demo F, so a count-then-code sort
is not the insertion order.

  (a0) BEFORE the fixture (no character, no location): the content-language
      line is exactly "content language: the language of your task text"
      (no stored key anywhere -> no "characters speak" part) and the counts
      line starts "counts: 0 locations (0 placed), 0 characters, " (nobody
      out of the world -> no "(… out of the world)" part).
  (a) world_overview{} -> one line starting "calendar: 4 seasons — ", which
      contains 'spring "Spring" 30 d' (first season) and " 30 d" exactly four
      times (4 seasons × 30 days), and "week days: none" (no weeks); the
      line also carries "; now " (the current game-time label).
  (b) the content-language line is exactly
      "content language: the language of your task text; characters speak
      en ×2, de ×1, fr ×1" — en: Demo A + Demo B (2, first by count); de
      (Demo F) and fr (Demo E, dormant, still counted) tie at 1 and sort by
      code, de before fr. Demo C, D, G, H have no stored key, so no extra
      "de" from the reader default. The counts line of the same result
      contains "8 characters (3 out of the world), " — 8 rows, the fixture
      links all three bodies first, so Demo D, E and H are dormant — the
      same roster as the language line, which counts dormant Demo E's "fr".
  (c) save_world_setup(250 × "x") -> the "setup:" line ends
      "(full text in your instructions)" (250 > the 200-char cut); a 20-char
      setup -> the line is "setup: " + 20 × "x", no hint.
  (d) get_character{name: "Demo D"} -> a line "linked: body of Demo A
      (dormant)"; get_character{name: "Demo A"} -> exactly
      "linked: leads Demo D, Demo E (Demo D and Demo E stand outside the
      world while this character is in it)" — bodies_of is sorted, the
      outside list is [leader] + bodies filtered to the dormant ones (D, E),
      two names -> "and" + "stand", the present member is the card's own
      character -> "this character". Demo C (unlinked) -> no "linked:" line.
  (d2) swap_presence("Demo A", "Demo D"): Demo A becomes dormant, Demo D
      stands in the world. Demo A's card -> exactly "linked: leads Demo D,
      Demo E (this character and Demo E stand outside the world while
      Demo D is in it)" (outside = A, E in [leader] + bodies order; A is the
      card's own). Demo D -> "linked: body of Demo A (in the world)", Demo E
      -> "linked: body of Demo A (dormant)". swap_presence("Demo G",
      "Demo H"): Demo G's card -> exactly "linked: leads Demo H (this
      character stands outside the world while Demo H is in it)" — one
      name -> "stands".
  (h) out-of-world families, forced through set_character_status (state
      after (d2): A dormant, D in, E dormant, G dormant, H in):
      Demo H -> "dormant": Demo G's card is exactly "linked: leads Demo H
      (all of them stand outside the world)". Demo G -> "pooled" (pooled
      leader + dormant body — present_member() would answer Demo G, which
      the outside list also names): still exactly that line. Demo F ->
      "pooled": the language line is unchanged ("… en ×2, de ×1, fr ×1",
      Demo F's "de" still counted) and the counts line contains
      "8 characters (5 out of the world), " (A, E, F, G, H). Demo E and
      Demo A -> "" (a repaired-by-hand state with all three in the world):
      Demo A's card is exactly "linked: leads Demo D, Demo E (this character
      is in the world)" — outside empty, the present member is the first of
      [leader] + bodies, the card's own character.
  (g) configured calendar: the world config gets
      game_calendar {"week_days": "Mo, Tu", "year_label": "Age {n}"} (no
      game_seasons, so still the four default seasons), config reloaded and
      the calendar cache dropped -> the calendar line contains
      'year label "Age {n}"; week days: Mo, Tu' (the raw label, the comma
      list split and re-joined with ", ").
  (e) world_dev_agent._render_system() contains "## Content language",
      "## What you cannot build", and that section (up to the next "## "
      heading) names each of "scheduler", "intents", "linking",
      "package panels", "calendar", "weekly market", "left open".
  (f) every journal row of the run is kind "read" (all calls above are reads).
"""
import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="smoke_wd_world_reads_"))
# Removed on every exit, a failed assert or an exception included.
atexit.register(shutil.rmtree, ROOT, True)
STORAGE = ROOT / "world"
STORAGE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")
(STORAGE / "config.json").write_text("{}", encoding="utf-8")

from app.core import paths  # noqa: E402

paths.init(STORAGE)
paths.init_instance(ROOT / "instance")

from app.core import config, db  # noqa: E402

config.load(STORAGE / "config.json")
db.init_schema()

from app.core import linked_characters as lc  # noqa: E402
from app.core import world_dev_agent as wa  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.models import character as ch  # noqa: E402
from app.models.world_setup import save_world_setup  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


run = wr.create_run("world reads", "m", "p", "u", 40, 300000)


def call(tool, args):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=1), tool, args)


def line_of(text, prefix):
    return next((ln for ln in text.splitlines() if ln.startswith(prefix)), None)


# ── (a0) empty world ─────────────────────────────────────────────────────
print("(a0) empty world")
r = call("world_overview", {})
check("(a0) bare language line", line_of(r.line, "content language: ")
      == "content language: the language of your task text", r.line)
counts = line_of(r.line, "counts: ") or ""
check("(a0) zero counts", counts.startswith("counts: 0 locations (0 placed), 0 characters, "),
      counts)

# ── Fixture ──────────────────────────────────────────────────────────────
for name, lang in (("Demo A", "en"), ("Demo B", "en"), ("Demo C", None), ("Demo D", None),
                   ("Demo E", "fr"), ("Demo F", "de"), ("Demo G", None), ("Demo H", None)):
    prof = {"character_name": name, "template": "human-roleplay"}
    if lang:
        prof["language"] = lang
    assert ch.save_character_profile(name, prof, create_new=True), name
for body, leader in (("Demo D", "Demo A"), ("Demo E", "Demo A"), ("Demo H", "Demo G")):
    res = lc.link(body, leader)
    check(f"fixture: link {body} -> {leader}", res.get("ok"), res)
check("fixture: Demo D dormant", ch.get_character_status("Demo D") == "dormant",
      ch.get_character_status("Demo D"))
check("fixture: Demo C raw language unset",
      not (ch.get_character_profile("Demo C") or {}).get("language"))

# ── (a) calendar ─────────────────────────────────────────────────────────
print("(a) calendar")
r = call("world_overview", {})
check("(a) ok", r.ok, r.line)
cal = line_of(r.line, "calendar: ")
check("(a) calendar line present", cal is not None, r.line)
cal = cal or ""
check("(a) 4 seasons", cal.startswith("calendar: 4 seasons — "), cal)
check("(a) first season", 'spring "Spring" 30 d' in cal, cal)
check("(a) ' 30 d' four times", cal.count(" 30 d") == 4, cal)
check("(a) no week days", "week days: none" in cal, cal)
check("(a) now label", "; now " in cal, cal)

# ── (b) content language ─────────────────────────────────────────────────
print("(b) content language")
lang_line = line_of(r.line, "content language: ")
check("(b) exact line", lang_line ==
      "content language: the language of your task text; characters speak "
      "en ×2, de ×1, fr ×1",
      lang_line)
counts = line_of(r.line, "counts: ") or ""
check("(b) counts name the dormant ones", "8 characters (3 out of the world), " in counts,
      counts)

# ── (c) setup cut ────────────────────────────────────────────────────────
print("(c) setup cut")
save_world_setup("x" * 250)
r = call("world_overview", {})
setup = line_of(r.line, "setup: ") or ""
check("(c) long setup hint", setup.endswith("(full text in your instructions)"), setup)
save_world_setup("x" * 20)
r = call("world_overview", {})
setup = line_of(r.line, "setup: ") or ""
check("(c) short setup whole", setup == "setup: " + "x" * 20, setup)

# ── (d) linked characters ────────────────────────────────────────────────
print("(d) linked")
r = call("get_character", {"name": "Demo D"})
check("(d) body line", "linked: body of Demo A (dormant)" in r.line.splitlines(), r.line)
r = call("get_character", {"name": "Demo A"})
lead = line_of(r.line, "linked: ") or ""
check("(d) leader line", lead == "linked: leads Demo D, Demo E (Demo D and Demo E "
      "stand outside the world while this character is in it)", lead)
r = call("get_character", {"name": "Demo C"})
check("(d) unlinked: no line", line_of(r.line, "linked:") is None, r.line)

# ── (d2) swapped families ────────────────────────────────────────────────
print("(d2) swapped")
for src, dst in (("Demo A", "Demo D"), ("Demo G", "Demo H")):
    res = lc.swap_presence(src, dst)
    check(f"(d2) swap {src} -> {dst}", res.get("ok"), res)
r = call("get_character", {"name": "Demo A"})
lead = line_of(r.line, "linked: ") or ""
check("(d2) leader swapped out", lead == "linked: leads Demo D, Demo E (this character "
      "and Demo E stand outside the world while Demo D is in it)", lead)
r = call("get_character", {"name": "Demo D"})
check("(d2) present body", "linked: body of Demo A (in the world)" in r.line.splitlines(),
      r.line)
r = call("get_character", {"name": "Demo E"})
check("(d2) dormant body", "linked: body of Demo A (dormant)" in r.line.splitlines(), r.line)
r = call("get_character", {"name": "Demo G"})
lead = line_of(r.line, "linked: ") or ""
check("(d2) single outside: stands", lead == "linked: leads Demo H (this character "
      "stands outside the world while Demo H is in it)", lead)

# ── (h) out-of-world families ────────────────────────────────────────────
print("(h) out of the world")
ch.set_character_status("Demo H", "dormant")
r = call("get_character", {"name": "Demo G"})
lead = line_of(r.line, "linked: ") or ""
check("(h) all dormant", lead == "linked: leads Demo H (all of them stand outside the world)",
      lead)
ch.set_character_status("Demo G", "pooled")
r = call("get_character", {"name": "Demo G"})
lead = line_of(r.line, "linked: ") or ""
check("(h) pooled leader + dormant body", lead ==
      "linked: leads Demo H (all of them stand outside the world)", lead)
ch.set_character_status("Demo F", "pooled")
r = call("world_overview", {})
check("(h) pooled language still counted", line_of(r.line, "content language: ") ==
      "content language: the language of your task text; characters speak "
      "en ×2, de ×1, fr ×1", r.line)
counts = line_of(r.line, "counts: ") or ""
check("(h) counts 5 out", "8 characters (5 out of the world), " in counts, counts)
ch.set_character_status("Demo E", "")
ch.set_character_status("Demo A", "")
r = call("get_character", {"name": "Demo A"})
lead = line_of(r.line, "linked: ") or ""
check("(h) nobody outside", lead ==
      "linked: leads Demo D, Demo E (this character is in the world)", lead)

# ── (g) configured calendar ──────────────────────────────────────────────
print("(g) configured calendar")
from app.core.game_time import invalidate_calendar_cache  # noqa: E402

(STORAGE / "config.json").write_text(json.dumps(
    {"game_calendar": {"week_days": "Mo, Tu", "year_label": "Age {n}"}}), encoding="utf-8")
config.load(STORAGE / "config.json")
invalidate_calendar_cache()
r = call("world_overview", {})
cal = line_of(r.line, "calendar: ") or ""
check("(g) year label + week days", 'year label "Age {n}"; week days: Mo, Tu' in cal, cal)

# ── (e) system prompt ────────────────────────────────────────────────────
print("(e) system prompt")
system = wa._render_system()
check("(e) content language section", "## Content language" in system)
check("(e) cannot-build section", "## What you cannot build" in system)
# The words are looked up INSIDE the cannot-build section (up to the next
# heading): "calendar" alone would also match the world_overview summary.
cannot = system.split("## What you cannot build", 1)[-1].split("\n## ", 1)[0]
for word in ("scheduler", "intents", "linking", "package panels", "calendar",
             "weekly market", "left open"):
    check(f"(e) cannot-build names {word!r}", word in cannot, cannot[:400])

# ── (f) journal ──────────────────────────────────────────────────────────
print("(f) journal")
kinds = {e.get("kind") for e in wr.entries(run, writes_only=False)}
check("(f) only read rows", kinds == {"read"}, kinds)

if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all ok")
