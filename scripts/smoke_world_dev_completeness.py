#!/usr/bin/env python3
"""Smoke: World Dev free mode — completeness feedback and check_run (gap 8).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p1-characters.md, Task 9,
widened by plan docs/superpowers/plans/2026-11-25-world-dev-free-complete-characters-budget.md,
Task 5 (C1: secrets, skill groups, media gaps, check_character — section
"TASK 5" at the end of this docstring). A temp world (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM. Every tool call goes through
``world_dev_tools.run_tool`` exactly as the agent loop calls it.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_completeness.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

The plugin registry is CLEARED and the FAKE species package of Task 3's smoke
is registered (scripts/smoke_world_dev_describe_template.py):

    id smoke_species, apply_to ["human-roleplay"], body_slots:
      hair         color  select [blonde, red], allow_custom
                   length select [short, long]
      facial_hair  applies_to gender=male; style select [short beard]

FAKE SKILLS (the Task 4 list of scripts/smoke_world_dev_skills.py): the skill
manager's list is replaced by five fake skills, in this loader order:
    demo_on      default on,  no capability
    demo_always  default off, no capability
    demo_off2    default off, no capability
    demo_pair_a  default off, capability demo_pair
    demo_pair_b  default off, capability demo_pair
(the capability comes from a patched registry.package_of_skill). A fresh
character therefore has the open skill groups demo_always, demo_off2 and
demo_pair (demo_on is on = decided), and the gap text is
    SKILLS = "skills not decided (set_skill on or off): demo_always, demo_off2,
              demo_pair (demo_pair_a+demo_pair_b)"
(one entry per group, a multi-member group as "id (m1+m2)"). A character
without a secret has the gap "no secret (add_secret)". Both come AFTER the
existing gaps (secret first, then skills) and only in full scope (a created
character, or check_character): secrets are journaled under target kind
"secret" and never widen a character's scope; set_skill (restore_skill_config)
widens it to "skills".

MEDIA in cases (a)-(r): world_dev_completeness.media_gaps is patched to []
there (the original runs predate media gaps); the TASK 5 cases use the real one.

No character below is male, so the unset body attributes of an empty
character are exactly "hair.color, hair.length" (declaration order).
The package declares no clothing slots, so outfits use the core slots
(top, bottom, feet).

Locations stored directly before the runs (not by a run):
    H "Demo House" placed at (0, 0), P "Demo Park" placed at (50, 0),
    U "Demo Shed" without x/z.

The soul fields of human-roleplay (shared/templates/character/base-character.json
merged into human-roleplay.json, template field order): character_personality,
character_presence, character_task, character_soul, character_beliefs,
character_lessons, character_goals. Their default texts (the scaffold a new
character gets) hold only headings, except presence, whose two sections carry
an HTML comment as a writing hint — a comment is no content, so all seven
count as "without content". SOUL below = that list joined with ", ".

Run 1 (turn 1):
  (a) create_character{data: {name: "Demo Bare"}} -> the line ends with
        "; missing: no home — not in the world; no outfits; wears nothing;
        no daily schedule; soul sections without content: SOUL;
        body slots unset: hair.color, hair.length; no secret (add_secret);
        SKILLS"
      (human-roleplay has a wardrobe, so "no outfits" and "wears nothing").
  (a') no "knows only its home": Demo Bare has no home, the precondition of
      that gap fails ("no home" already says it); "not placed" is absent for
      the same reason (it needs a home too).
  (b) Demo Full: home H, schedule [{0, sleep}, {10, P, role "walk"}], all
      seven soul fields with text, body_slots hair {color red, length long},
      2 outfits (Daily: top, bottom, feet; Night: a gown on top+bottom) ->
      "; missing: no secret (add_secret); SKILLS" (Task 5: a new character
      has neither). Then add_secret{Demo Full, …}, set_skill demo_always
      false, set_skill demo_off2 true, set_skill demo_pair true (the group:
      2 rows) -> character_suffix(run, Demo Full) == "; complete". Placed at H (a NEW character is placed at its home,
      world_dev_apply._apply_home_and_schedule is_new), wears Daily (the
      first outfit), known places [H, P] (home + schedule place) — so not
      "knows only its home".
  (c) Demo Shedder with home U -> placed at U, known [U], so the line ends
        "; missing: home <U> is unplaced (no x/z); no outfits; wears nothing;
        no daily schedule; soul sections without content: SOUL;
        body slots unset: hair.color, hair.length; knows only its home;
        no secret (add_secret); SKILLS"
  (d) create_location{data: {name: "Demo Mill"}} (no x/z, seeded 10 m square
      outline, only ground room, no props) -> the line ends
      "; missing: unplaced (no x/z) — not a travel target; no props on the open
      ground (place_world_prop, or place_room_prop in an open room)" (unplaced:
      neither the path gap nor the spacing gap applies); place_location of it
      at (100, 20) (no path area within 10 m)
      -> "; missing: no props on the open ground (place_world_prop, or
      place_room_prop in an open room); entrance without a path within 10 m
      (add_terrain_area kind path)".
  (e) check_run{} -> exactly: the Demo Bare line, the Demo Shedder line
      ('character "<n>": missing: …' with the suffix lists of (a) and (c)),
      the Demo Mill line ('location <id> "Demo Mill": missing: no props on the
      open ground (place_world_prop, or place_room_prop in an open room);
      entrance without a path within 10 m (add_terrain_area kind path)'),
      then "1 of 4 elements complete" (created: Demo Bare, Demo Full,
      Demo Shedder, Demo Mill; only Demo Full is complete; H, P, U pre-exist
      and were not touched).
      The secret add_secret journaled (target kind "secret") does not exist
      as a check_run element kind, so n stays 4.
      Its journal row is kind "read". check_run{x: 1} -> refused.

Run 2 (pre-existing hand-made Demo Hand, saved directly: human-roleplay,
no home, no schedule, no current location, one outfit "Daily" that is NOT
worn, scaffold soul sections, no body slots):
  (f) update_character{Demo Hand, {importance: 2}} -> "; complete": a config
      field is restore_character, which touches no gap group.
      update_character{Demo Hand, {home: H}} -> only the home group:
      _apply_home_and_schedule with is_new False never places anybody (only
      "if is_new and home") -> "not placed"; known_locations gains the home
      through add_known_location -> [H] -> "knows only its home"; no
      schedule -> "no daily schedule". So the line ends
        "; missing: not placed; no daily schedule; knows only its home"
      Never "wears nothing" (only for created characters), "no outfits",
      "soul sections" or "body slots" (groups the run did not touch).
      A later update_character{importance: 3} keeps the home group of the
      earlier call -> the same suffix.
  (g) update_location{U, {description}} -> "; complete": U was only updated
      and the run wrote no x/z for it (no restore_position).
  (h) check_run{} -> exactly
        'character "Demo Hand": missing: not placed; no daily schedule; knows only its home
         (only what this run changed — check_character lists all)'  (one line; an
         UPDATED character's check_run line names its narrowed scope, Task 5)
        "1 of 2 elements complete"   (Demo Hand and U; U complete under its scope)

Run 3 (hand-made Demo Loner: no home; Demo Homebody: config home_location H
saved directly, no known_locations; Demo Hand from run 2 knows [H]):
  (i) update_character{Demo Hand, {known_places: [H]}} -> H is already known,
      "known places unchanged"; the row's inverse names no id, so it widens
      no group -> "; complete" (before the fix: the home group's
      "not placed; no daily schedule; knows only its home"). It changed
      nothing, so Demo Hand is no element of run 3 at all.
  (j) update_character{Demo Loner, {known_places: [P]}} -> the "known" group
      only, which reports nothing but "knows only its home" and needs a home
      -> "; complete" (before: "no home — not in the world; no daily schedule").
  (k) update_character{Demo Homebody, {known_places: [H]}} -> H added, known
      [H] = only the home -> "; missing: knows only its home" (no "not placed",
      no "no daily schedule": the home group is not in scope).
  (l) turn 1 create_character{Demo Gone}; turn 2 delete_created{character,
      Demo Gone} (cross-turn: a done recreate_character row); then a
      hand-made "Demo Gone" saved directly. It is somebody else's (as
      discard_preview decides), its older rows widen nothing and the run
      changed nothing of it -> not listed, not counted.
  (m) check_run{} -> exactly
        'character "Demo Homebody": missing: knows only its home (only what this
         run changed — check_character lists all)'
        "1 of 2 elements complete"   (Demo Loner — known places added, no
                                      home, so complete — and Demo Homebody;
                                      Demo Hand (i) and Demo Gone (l) are
                                      no elements)

Run 4 (same-turn delete and a no-op update):
  (n) turn 1 create_character{Demo Tmp}; update_character{Demo Tmp,
      {"soul:character_soul": "..."}} (a restore_soul row, which always counts);
      delete_created{character, Demo Tmp} in the SAME turn (the creating row
      is marked undone, the delete row has no inverse, the soul row stays
      live); then a hand-made "Demo Tmp" saved directly (scaffold soul).
      Before the fix the live soul row widened the scope to {soul} ->
      'character "Demo Tmp": missing: soul sections without content: SOUL'.
      Now the inverse-less done delete row resets it like a recreate_* row:
      Demo Tmp is no element.
  (o) update_character{Demo Full, {body_slots: {hair: {color: "red"}}}} —
      the value it already has -> the row's inverse names nothing changed
      ("before" empty) -> not an element; "; complete".
  (p) update_character{Demo Loner, {importance: 2}} -> a restore_character
      row (a real change, no gap group) -> counted, complete.
  (q) check_run{} -> exactly ["1 of 1 elements complete"] (only Demo Loner).

Run 5 (a no-op update alone):
  (r) update_character{Demo Loner, {importance: 2}} — the value (p) stored ->
      the restore_character row attaches empty profile/config maps (nothing
      changed) -> not an element; check_run{} -> exactly
      ["0 of 0 elements complete"].

TASK 5 ((k), (k'), (m) run on run 1 right after (e); the rest after (r);
real media_gaps in these cases; temp storage has no profile image and no
stored base front, and every character is a humanoid human-roleplay
character on the base-body pipeline, so media_gaps == ["no portrait",
"no base body"] for each — "no portrait": profile_image empty; "no base
body": is_base_pipeline True and base_refresh_plan(missing=True).reason
"missing" because no front is stored):
  (k) run 1 (media on, create_run's default) check_character{Demo Full} ->
      exactly ['character "Demo Full": complete',
               "media pending (rendered after the turn): no portrait; no base body"].
      Demo Full was created by run 1: its baseline is NULL (created) before
      and after (note_touch is a no-op when a baseline exists).
  (m) check_run{} of run 1 again -> still "1 of 4 elements complete" (media
      gaps never lower complete), the Demo Bare line now ends with
      " · media pending: no portrait; no base body", and complete Demo Full
      (created by run 1, NULL baseline -> every step due) now has a line
      too: 'character "Demo Full": complete · media pending: no portrait; no
      base body' — still counted complete.
  (b') run 6 (media on): create_character{Demo Half}; set_skill demo_always
      false; set_skill demo_off2 false; the smoke writes ONLY
      skills/demo_pair_a.json = {"enabled": true} -> character_suffix(run 6,
      Demo Half) contains "skills not decided (set_skill on or off): demo_pair
      (demo_pair_a+demo_pair_b)" and not "demo_always" (one member set
      leaves the group open — the Skills tab shows it off).
  (n) "Demo Plain" saved directly (outside any run), no profile image: before
      check_character ("character", "Demo Plain") is not in wr.baselines(run 6);
      after check_character{Demo Plain} it is, and the second line is
      "media pending (rendered after the turn): no portrait; no base body";
      a second check_character leaves the baseline row unchanged (same value).
      The recorded baseline marks both missing outputs due: base_n["portrait"]
      == base_n["build"] == world_dev_media.MISSING_OUTPUT_FP (Demo Plain is on
      the base-body pipeline, so its steps are portrait + build).
  (n') "Demo Seen" saved directly, then run 6 takes its baseline the way a
      write step's begin does (world_dev_media.note_touch, no inverse: the
      CURRENT fingerprints). Nothing changes its portrait/build inputs, but
      both OUTPUTS are missing (no profile image, no base front), and since
      Task 6 (C4) a missing output makes its step due whatever its
      fingerprint -> check_character{Demo Seen}'s last line is "media
      pending (rendered after the turn): no portrait; no base body" (no "not
      due" line), and the baseline is unchanged (the check records only a
      first one). Then a QUEUED row of run 6 holds both steps with their
      current fps (in flight — it always holds) -> plan() counts neither
      due: no "pending" line, the last line is "media missing (not due in
      this run's media plan — not rendered): no portrait; no base body". The
      row is put "removed" afterwards.
      Run 7 (media OFF, create_run(media_enabled=False)): check_character{Demo
      Plain} -> second line "media missing (Generate media is off for this run
      — not rendered): no portrait; no base body", and no baseline in run 7.
  (l) run 8 (media OFF): "Demo Handmade" saved directly (config home H, no
      known places, no secret, no body slots); update_character{known_places:
      [H]} -> scope {"known"} -> check_run{} == [
        'character "Demo Handmade": missing: knows only its home (only what this
         run changed — check_character lists all) · media missing (Generate media
         is off): no portrait; no base body',
        "0 of 1 elements complete"],
      while check_character{Demo Handmade} lists the full set, incl.
      "no secret (add_secret)" and "body slots unset: hair.color, hair.length".
  (k') check_character{x: 1} -> refused; check_character of an unknown name ->
      refused; its row is kind "read".
  (t) check_run's suffixes are the module constants RUN_MEDIA_PENDING /
      RUN_MEDIA_NOT_DUE / RUN_MEDIA_OFF == " · media pending: ", " · media
      missing (not due — not rendered): ", " · media missing (Generate media is
      off): " (the literals cases (m) and (l) compare against).
  (u) run 9 (media on): "Demo Rolled" saved directly; in turn 1
      check_character records its baseline with portrait/build ==
      MISSING_OUTPUT_FP (as in (n)), then update_character{importance: 3}.
      world_dev_undo.undo(run 9, turn=1) -> complete, importance back to its
      value before; the check baseline is NO journal row, so it stays unchanged
      and due_step_ids == {"portrait", "build"} — on purpose (media_split
      docstring): the lane renders what the check found missing anyway.
  (v) run 10 (media off): secrets.list_secrets and
      world_dev_tools._open_skill_decisions patched to raise RuntimeError ->
      create_character{Demo Faulty} and update_character{importance: 2} are ok,
      character_gaps("Demo Faulty") holds neither "no secret (add_secret)" nor
      a "skills not decided" gap but still "body slots unset: hair.color,
      hair.length", and the world_dev_completeness logger got the warnings
      "... secrets not readable ..." and "... skill decisions not readable ...".
  (w) Pure reads (phase review of complete-characters-budget). "Demo Bare"
      saved directly, its characters.config_json set to "{}" (a hand-made
      character without a stored config) and its empty model_refs dir removed.
      Run 11 (media on): check_character{Demo Bare} -> ok, last line
      PENDING + MEDIA (no portrait, no base body, as in (u)); config_json is
      still exactly "{}" (get_character_config would otherwise save the
      defaults — no_config_auto_create) and the file tree under the storage
      dir (db files aside) is unchanged — no characters/Demo Bare/model_refs
      (base_body._stored_base_for and world_dev_media._base_body_present must
      not create it). set_skill demo_off2 on puts Demo Bare into check_run
      (restore_skill_config widens group skills); check_run -> a "Demo Bare"
      line, config_json still "{}", file tree unchanged by the check. On the
      code before this fix config_json held the ten default keys after either
      check and characters/Demo Bare/model_refs appeared after check_character.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_compl_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_compl_"))
INSTANCE = Path(tempfile.mkdtemp(prefix="smoke_wd_compl_inst_"))
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(INSTANCE)
paths.init(STORAGE)
paths.init_instance(INSTANCE)
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)
atexit.register(shutil.rmtree, INSTANCE, ignore_errors=True)
(STORAGE / "config.json").write_text("{}", encoding="utf-8")

from app.core import config, db  # noqa: E402

config.load(STORAGE / "config.json")
db.init_schema()

from app.core import world_dev_completeness as completeness  # noqa: E402
from app.core import world_dev_media  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core.dependencies import get_skill_manager  # noqa: E402
from app.core.world_dev_apply import _apply_one_outfit  # noqa: E402
from app.core.world_ops import create_location_with_extras  # noqa: E402
from app.models.character import (get_character_outfits,  # noqa: E402
                                  save_character_profile)
from app.models.character_template import clear_template_cache  # noqa: E402
from app.models.inventory import get_equipped_pieces  # noqa: E402
from app.models.world import update_location_position  # noqa: E402
from app.plugins import registry  # noqa: E402
from app.plugins.registry import BodySlotSpec, Package  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


# ── fake skills (Task 4 list), loaded BEFORE the registry is cleared ──
FAKE_SKILLS = [("demo_on", True, ""), ("demo_always", False, ""), ("demo_off2", False, ""),
               ("demo_pair_a", False, "demo_pair"), ("demo_pair_b", False, "demo_pair")]


class _FakeSkill:
    ALWAYS_LOAD = False

    def __init__(self, sid, default):
        self.SKILL_ID = sid
        self.name = sid
        self.description = ""
        self._default = default

    def default_enabled_for(self, _name):
        return self._default

    def get_config_fields(self):
        return {}


class _FakeCapability:
    def __init__(self, pid):
        self.id = pid
        self.capability_label = "Demo pair"
        self.requires = []
        self.conflicts = []


get_skill_manager().skills[:] = [_FakeSkill(sid, d) for sid, d, _c in FAKE_SKILLS]
_FAKE_CAP = {sid: c for sid, _d, c in FAKE_SKILLS if c}
_real_package_of_skill = registry.package_of_skill
registry.package_of_skill = (
    lambda sid: _FakeCapability(_FAKE_CAP[sid]) if sid in _FAKE_CAP
    else _real_package_of_skill(sid))
SKILLS = ("skills not decided (set_skill on or off): demo_always, demo_off2, "
          "demo_pair (demo_pair_a+demo_pair_b)")
SECRET = "no secret (add_secret)"
NEW = f"{SECRET}; {SKILLS}"

MEDIA = "no portrait; no base body"
PENDING = "media pending (rendered after the turn): "
OFF = "media missing (Generate media is off for this run — not rendered): "
NOT_DUE = "media missing (not due in this run's media plan — not rendered): "

# Cases (a)-(r) predate media gaps (see the docstring).
_real_media_gaps = completeness.media_gaps
completeness.media_gaps = lambda name: []

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


def new_place(name, x=None, z=None):
    res = create_location_with_extras({"name": name, "rooms": [], "create_new": True})
    lid = str(res["location"]["id"])
    if x is not None:
        update_location_position(lid, x, z, None)
    return lid


H = new_place("Demo House", 0, 0)
P = new_place("Demo Park", 50, 0)
U = new_place("Demo Shed")

SOUL_KEYS = ["character_personality", "character_presence", "character_task",
             "character_soul", "character_beliefs", "character_lessons",
             "character_goals"]
SOUL = ", ".join(SOUL_KEYS)
BODY = "body slots unset: hair.color, hair.length"

run1 = wr.create_run("completeness 1", "m", "p", "u", 40, 300000)
ctx1 = wt.ToolCtx(run_id=run1, turn=1)


def call(ctx, name, args):
    return wt.run_tool(ctx, name, args)


# (a)
BARE = ("no home — not in the world; no outfits; wears nothing; no daily schedule; "
        f"soul sections without content: {SOUL}; {BODY}; {NEW}")
res = call(ctx1, "create_character", {"data": {"name": "Demo Bare"}})
check("(a) Demo Bare: full gap list", res.ok and res.line.endswith("; missing: " + BARE),
      res.line)
check("(a') no 'knows only its home' / 'not placed' without a home",
      "knows only its home" not in res.line and "not placed" not in res.line, res.line)

# (b)
OUTFITS = [
    {"name": "Daily", "pieces": [
        {"slots": ["top"], "name": "Demo Shirt", "prompt_fragment": "plain linen shirt"},
        {"slots": ["bottom"], "name": "Demo Trousers", "prompt_fragment": "brown trousers"},
        {"slots": ["feet"], "name": "Demo Boots", "prompt_fragment": "leather boots"}]},
    {"name": "Night", "pieces": [
        {"slots": ["top", "bottom"], "name": "Demo Gown", "prompt_fragment": "long gown"}]},
]
full_data = {"name": "Demo Full", "outfits": OUTFITS,
             "body_slots": {"hair": {"color": "red", "length": "long"}}}
for key in SOUL_KEYS:
    full_data[key] = f"Demo text of {key}."
res = call(ctx1, "create_character", {
    "data": full_data, "home": H,
    "schedule": [{"hour": 0, "sleep": True}, {"hour": 10, "location": P, "role": "walk"}]})
check("(b) Demo Full: only secret and skills missing",
      res.ok and res.line.endswith("; missing: " + NEW), res.line)
res = call(ctx1, "add_secret", {"name": "Demo Full", "content": "Demo secret text."})
check("(b) add_secret ok", res.ok, res.line)
for sid, on in (("demo_always", False), ("demo_off2", True), ("demo_pair", True)):
    res = call(ctx1, "set_skill", {"name": "Demo Full", "skill": sid, "enabled": on})
    check(f"(b) set_skill {sid} {on}", res.ok, res.line)
check("(b) Demo Full: complete", completeness.character_suffix(run1, "Demo Full") == "; complete",
      completeness.character_suffix(run1, "Demo Full"))
check("(b) Demo Full wears its first outfit", bool(get_equipped_pieces("Demo Full")))

# (c)
SHEDDER = (f"home {U} is unplaced (no x/z); no outfits; wears nothing; no daily schedule; "
           f"soul sections without content: {SOUL}; {BODY}; knows only its home; {NEW}")
res = call(ctx1, "create_character", {"data": {"name": "Demo Shedder"}, "home": U})
check("(c) Demo Shedder: unplaced home", res.ok and f"home {U} is unplaced (no x/z)" in res.line,
      res.line)
check("(c) Demo Shedder: exact suffix", res.ok and res.line.endswith("; missing: " + SHEDDER),
      res.line)

# (d)
MILL_OPEN = "no props on the open ground (place_world_prop, or place_room_prop in an open room)"
MILL_PATH = "entrance without a path within 10 m (add_terrain_area kind path)"
res = call(ctx1, "create_location", {"data": {"name": "Demo Mill"}})
check("(d) unplaced new location",
      res.ok
      and res.line.endswith(f"; missing: unplaced (no x/z) — not a travel target; {MILL_OPEN}")
      and "without a path" not in res.line
      and "from the nearest place" not in res.line,
      res.line)
mill = wr.entries(run1)[0]["target_id"]
res = call(ctx1, "place_location", {"id": mill, "x": 100, "z": 20})
check("(d) placed -> open-ground and path gaps only",
      res.ok and res.line.endswith(f"; missing: {MILL_OPEN}; {MILL_PATH}"), res.line)

# (e)
res = call(ctx1, "check_run", {})
check("(e) check_run lines", res.ok and res.line.splitlines() == [
    f'character "Demo Bare": missing: {BARE}',
    f'character "Demo Shedder": missing: {SHEDDER}',
    f'location {mill} "Demo Mill": missing: {MILL_OPEN}; {MILL_PATH}',
    "1 of 4 elements complete"], res.line)
check("(e) check_run is a read row", wr.steps(run1)[-1]["kind"] == "read",
      wr.steps(run1)[-1]["kind"])
res = call(ctx1, "check_run", {"x": 1})
check("(e) unknown argument refused", not res.ok and "x" in res.line, res.line)

# (k) — Task 5 cases on run 1 (real media gaps for this block)
completeness.media_gaps = _real_media_gaps
check("(k) Demo Full baseline is 'created' before",
      ("character", "Demo Full") in wr.baselines(run1)
      and wr.baselines(run1)[("character", "Demo Full")] is None,
      wr.baselines(run1).get(("character", "Demo Full")))
res = call(ctx1, "check_character", {"name": "Demo Full"})
check("(k) check_character Demo Full", res.ok and res.line.splitlines() == [
    'character "Demo Full": complete', PENDING + MEDIA], res.line)
check("(k) baseline still 'created'", wr.baselines(run1).get(("character", "Demo Full"), 1) is None,
      wr.baselines(run1).get(("character", "Demo Full")))
check("(k) check_character is a read row", wr.steps(run1)[-1]["kind"] == "read",
      wr.steps(run1)[-1]["kind"])
# (k')
res = call(ctx1, "check_character", {"name": "Demo Full", "x": 1})
check("(k') unknown argument refused", not res.ok, res.line)
res = call(ctx1, "check_character", {"name": "Demo Nobody"})
check("(k') unknown character refused", not res.ok, res.line)

# (m)
res = call(ctx1, "check_run", {})
lines = res.line.splitlines()
check("(m) media gaps never lower complete", res.ok and lines[-1] == "1 of 4 elements complete",
      res.line)
check("(m) the Demo Bare line names its pending media",
      bool(lines) and lines[0] == f'character "Demo Bare": missing: {BARE} · media pending: {MEDIA}',
      lines[:1])
check("(m) complete Demo Full shows its pending media",
      f'character "Demo Full": complete · media pending: {MEDIA}' in lines, lines)

completeness.media_gaps = lambda name: []


# Run 2: a hand-made character and a pre-existing unplaced location.
check("setup: Demo Hand saved", save_character_profile(
    "Demo Hand", {"name": "Demo Hand", "template": "human-roleplay"}, create_new=True))
_apply_one_outfit("Demo Hand", {"name": "Daily", "pieces": [
    {"slots": ["top"], "name": "Demo Tunic", "prompt_fragment": "grey tunic"}]})
check("setup: Demo Hand has an outfit, wears nothing",
      len(get_character_outfits("Demo Hand")) == 1 and not get_equipped_pieces("Demo Hand"))

wr.set_status(run1, "accepted")
run2 = wr.create_run("completeness 2", "m", "p", "u", 40, 300000)
ctx2 = wt.ToolCtx(run_id=run2, turn=1)

# (f)
HAND = "not placed; no daily schedule; knows only its home"
SCOPED = " (only what this run changed — check_character lists all)"
res = call(ctx2, "update_character", {"name": "Demo Hand", "patch": {"importance": 2}})
check("(f) config-only update -> complete", res.ok and res.line.endswith("; complete"), res.line)
res = call(ctx2, "update_character", {"name": "Demo Hand", "patch": {"home": H}})
check("(f) home update -> home group only",
      res.ok and res.line.endswith("; missing: " + HAND), res.line)
for word in ("wears nothing", "no outfits", "soul sections", "body slots"):
    check(f"(f) never {word!r} for Demo Hand", word not in res.line, res.line)
res = call(ctx2, "update_character", {"name": "Demo Hand", "patch": {"importance": 3}})
check("(f) later update keeps the earlier call's group",
      res.ok and res.line.endswith("; missing: " + HAND), res.line)

# (g)
res = call(ctx2, "update_location", {"id": U, "patch": {"description": "A small shed."}})
check("(g) updated unplaced location -> complete",
      res.ok and res.line.endswith("; complete"), res.line)

# (h)
res = call(ctx2, "check_run", {})
check("(h) check_run of run 2", res.ok and res.line.splitlines() == [
    f'character "Demo Hand": missing: {HAND}{SCOPED}', "1 of 2 elements complete"], res.line)

# Run 3
from app.models.character import get_character_config, save_character_config  # noqa: E402

check("setup: Demo Loner saved", save_character_profile(
    "Demo Loner", {"name": "Demo Loner", "template": "human-roleplay"}, create_new=True))
check("setup: Demo Homebody saved", save_character_profile(
    "Demo Homebody", {"name": "Demo Homebody", "template": "human-roleplay"}, create_new=True))
hb_cfg = dict(get_character_config("Demo Homebody") or {})
hb_cfg["home_location"] = H
hb_cfg.pop("known_locations", None)
check("setup: Demo Homebody home H, knows nothing",
      save_character_config("Demo Homebody", hb_cfg)
      and not (get_character_config("Demo Homebody") or {}).get("known_locations"))

wr.set_status(run2, "accepted")
run3 = wr.create_run("completeness 3", "m", "p", "u", 40, 300000)
ctx3 = wt.ToolCtx(run_id=run3, turn=1)

# (i)
res = call(ctx3, "update_character", {"name": "Demo Hand", "patch": {"known_places": [H]}})
check("(i) no-op known places -> complete",
      res.ok and "known places unchanged" in res.line and res.line.endswith("; complete"),
      res.line)

# (j)
res = call(ctx3, "update_character", {"name": "Demo Loner", "patch": {"known_places": [P]}})
check("(j) known places without a home -> complete",
      res.ok and res.line.endswith("; complete"), res.line)

# (k)
res = call(ctx3, "update_character", {"name": "Demo Homebody", "patch": {"known_places": [H]}})
check("(k) only the home known -> only that gap",
      res.ok and res.line.endswith("; missing: knows only its home"), res.line)

# (l)
res = call(ctx3, "create_character", {"data": {"name": "Demo Gone"}})
check("(l) Demo Gone created", res.ok, res.line)
res = call(wt.ToolCtx(run_id=run3, turn=2), "delete_created",
           {"kind": "character", "id": "Demo Gone"})
check("(l) Demo Gone deleted in turn 2", res.ok, res.line)
check("(l) hand-made Demo Gone saved", save_character_profile(
    "Demo Gone", {"name": "Demo Gone", "template": "human-roleplay"}, create_new=True))

# (m)
res = call(wt.ToolCtx(run_id=run3, turn=2), "check_run", {})
check("(m) check_run of run 3", res.ok and res.line.splitlines() == [
    'character "Demo Homebody": missing: knows only its home' + SCOPED,
    "1 of 2 elements complete"], res.line)

# Run 4
wr.set_status(run3, "accepted")
run4 = wr.create_run("completeness 4", "m", "p", "u", 40, 300000)
ctx4 = wt.ToolCtx(run_id=run4, turn=1)

# (n)
res = call(ctx4, "create_character", {"data": {"name": "Demo Tmp"}})
check("(n) Demo Tmp created", res.ok, res.line)
res = call(ctx4, "update_character", {"name": "Demo Tmp",
                                      "patch": {"soul:character_soul": "Demo soul text."}})
check("(n) Demo Tmp soul written", res.ok, res.line)
check("(n) the soul row is restore_soul",
      (wr.entries(run4)[0].get("inverse") or {}).get("op") == "restore_soul",
      wr.entries(run4)[0].get("inverse"))
res = call(ctx4, "delete_created", {"kind": "character", "id": "Demo Tmp"})
check("(n) Demo Tmp deleted in the same turn", res.ok, res.line)
check("(n) hand-made Demo Tmp saved", save_character_profile(
    "Demo Tmp", {"name": "Demo Tmp", "template": "human-roleplay"}, create_new=True))

# (o)
res = call(ctx4, "update_character", {"name": "Demo Full",
                                      "patch": {"body_slots": {"hair": {"color": "red"}}}})
check("(o) unchanged body slot -> complete", res.ok and res.line.endswith("; complete"),
      res.line)

# (p)
res = call(ctx4, "update_character", {"name": "Demo Loner", "patch": {"importance": 2}})
check("(p) config update -> complete", res.ok and res.line.endswith("; complete"), res.line)

# (q)
res = call(ctx4, "check_run", {})
check("(q) check_run of run 4", res.ok and res.line.splitlines() == [
    "1 of 1 elements complete"], res.line)

# (r)
wr.set_status(run4, "accepted")
run5 = wr.create_run("completeness 5", "m", "p", "u", 40, 300000)
ctx5 = wt.ToolCtx(run_id=run5, turn=1)
res = call(ctx5, "update_character", {"name": "Demo Loner", "patch": {"importance": 2}})
check("(r) same importance -> ok, nothing changed",
      res.ok and "fields unchanged" in res.line, res.line)
check("(r) the row is restore_character with empty maps",
      (wr.entries(run5)[0].get("inverse") or {}) == {
          "op": "restore_character", "name": "Demo Loner", "profile": {}, "config": {}},
      wr.entries(run5)[0].get("inverse"))
res = call(ctx5, "check_run", {})
check("(r) check_run of run 5: no element", res.ok and res.line.splitlines() == [
    "0 of 0 elements complete"], res.line)

# ── TASK 5: real media gaps from here ──
completeness.media_gaps = _real_media_gaps

# (b')
wr.set_status(run5, "accepted")
run6 = wr.create_run("completeness 6", "m", "p", "u", 40, 300000)
ctx6 = wt.ToolCtx(run_id=run6, turn=1)
res = call(ctx6, "create_character", {"data": {"name": "Demo Half"}})
check("(b') Demo Half created", res.ok, res.line)
for sid in ("demo_always", "demo_off2"):
    res = call(ctx6, "set_skill", {"name": "Demo Half", "skill": sid, "enabled": False})
    check(f"(b') set_skill {sid} off", res.ok, res.line)
from app.models.character import get_character_dir  # noqa: E402

(get_character_dir("Demo Half") / "skills").mkdir(parents=True, exist_ok=True)
(get_character_dir("Demo Half") / "skills" / "demo_pair_a.json").write_text(
    '{"enabled": true}', encoding="utf-8")
suf = completeness.character_suffix(run6, "Demo Half")
check("(b') one member set leaves the group open",
      "skills not decided (set_skill on or off): demo_pair (demo_pair_a+demo_pair_b)" in suf
      and "demo_always" not in suf, suf)

# (n)
check("setup: Demo Plain saved", save_character_profile(
    "Demo Plain", {"name": "Demo Plain", "template": "human-roleplay"}, create_new=True))
check("(n) no baseline before", ("character", "Demo Plain") not in wr.baselines(run6))
res = call(ctx6, "check_character", {"name": "Demo Plain"})
check("(n) media pending line", res.ok and res.line.splitlines()[-1:] == [PENDING + MEDIA],
      res.line)
base_n = wr.baselines(run6).get(("character", "Demo Plain"), "absent")
check("(n) baseline recorded", ("character", "Demo Plain") in wr.baselines(run6)
      and isinstance(base_n, dict) and bool(base_n), base_n)
check("(n) the missing outputs are marked due",
      isinstance(base_n, dict)
      and base_n.get("portrait") == base_n.get("build") == world_dev_media.MISSING_OUTPUT_FP,
      base_n)
call(ctx6, "check_character", {"name": "Demo Plain"})
check("(n) second check leaves the baseline unchanged",
      wr.baselines(run6).get(("character", "Demo Plain")) == base_n)
# (n')
check("setup: Demo Seen saved", save_character_profile(
    "Demo Seen", {"name": "Demo Seen", "template": "human-roleplay"}, create_new=True))
world_dev_media.note_touch(run6, "character", "Demo Seen", None)
base_s = wr.baselines(run6).get(("character", "Demo Seen"), "absent")
res = call(ctx6, "check_character", {"name": "Demo Seen"})
check("(n') unchanged inputs, outputs missing: pending",
      res.ok and res.line.splitlines()[-1:] == [PENDING + MEDIA]
      and not any(l.startswith(NOT_DUE) for l in res.line.splitlines()), res.line)
check("(n') baseline unchanged", wr.baselines(run6).get(("character", "Demo Seen")) == base_s)
_fps = {s.id: s.fp for s in world_dev_media.element_steps("character", "Demo Seen")}
_flight = wr.add_media_row(run6, "character", "Demo Seen", [
    {"id": sid, "label": sid, "status": "queued", "note": "", "fp": _fps[sid]}
    for sid in ("portrait", "build")])
res = call(ctx6, "check_character", {"name": "Demo Seen"})
check("(n') a queued row holds both steps: not due, no pending promise",
      res.ok and not any(l.startswith(PENDING) for l in res.line.splitlines())
      and res.line.splitlines()[-1:] == [NOT_DUE + MEDIA], res.line)
wr.update_media_row(_flight, status="removed")
wr.set_status(run6, "accepted")
run7 = wr.create_run("completeness 7", "m", "p", "u", 40, 300000, media_enabled=False)
ctx7 = wt.ToolCtx(run_id=run7, turn=1)
res = call(ctx7, "check_character", {"name": "Demo Plain"})
check("(n) media off: 'media missing' line", res.ok and res.line.splitlines()[-1:] == [
    OFF + MEDIA], res.line)
check("(n) media off: no baseline", ("character", "Demo Plain") not in wr.baselines(run7))

# (l)
wr.set_status(run7, "accepted")
check("setup: Demo Handmade saved", save_character_profile(
    "Demo Handmade", {"name": "Demo Handmade", "template": "human-roleplay"}, create_new=True))
hm_cfg = dict(get_character_config("Demo Handmade") or {})
hm_cfg["home_location"] = H
hm_cfg.pop("known_locations", None)
check("setup: Demo Handmade home H", save_character_config("Demo Handmade", hm_cfg))
run8 = wr.create_run("completeness 8", "m", "p", "u", 40, 300000, media_enabled=False)
ctx8 = wt.ToolCtx(run_id=run8, turn=1)
res = call(ctx8, "update_character", {"name": "Demo Handmade", "patch": {"known_places": [H]}})
check("(l) known place added", res.ok, res.line)
res = call(ctx8, "check_run", {})
check("(l) check_run: scoped line + media off", res.ok and res.line.splitlines() == [
    'character "Demo Handmade": missing: knows only its home' + SCOPED
    + " · media missing (Generate media is off): " + MEDIA,
    "0 of 1 elements complete"], res.line)
res = call(ctx8, "check_character", {"name": "Demo Handmade"})
first = res.line.splitlines()[0] if res.ok else res.line
check("(l) check_character lists the full set",
      res.ok and first.startswith('character "Demo Handmade": missing: ')
      and SECRET in first and BODY in first and SKILLS in first
      and "no daily schedule" in first, res.line)

# (t) check_run's media suffixes are module constants (one source)
check("(t) check_run suffix constants", (completeness.RUN_MEDIA_PENDING,
                                         completeness.RUN_MEDIA_NOT_DUE,
                                         completeness.RUN_MEDIA_OFF) == (
    " · media pending: ", " · media missing (not due — not rendered): ",
    " · media missing (Generate media is off): "))

# (u) a check baseline outlives a per-turn rollback (on purpose)
from app.core import world_dev_undo  # noqa: E402

wr.set_status(run8, "accepted")
check("setup: Demo Rolled saved", save_character_profile(
    "Demo Rolled", {"name": "Demo Rolled", "template": "human-roleplay"}, create_new=True))
imp_before = (get_character_config("Demo Rolled") or {}).get("importance")
run9 = wr.create_run("completeness 9", "m", "p", "u", 40, 300000)
ctx9 = wt.ToolCtx(run_id=run9, turn=1)
res = call(ctx9, "check_character", {"name": "Demo Rolled"})
check("(u) media pending line", res.ok and res.line.splitlines()[-1:] == [PENDING + MEDIA],
      res.line)
base_u = wr.baselines(run9).get(("character", "Demo Rolled"), "absent")
res = call(ctx9, "update_character", {"name": "Demo Rolled", "patch": {"importance": 3}})
check("(u) importance written", res.ok
      and (get_character_config("Demo Rolled") or {}).get("importance") == 3, res.line)
undo_u = world_dev_undo.undo(run9, turn=1)
check("(u) turn rolled back", undo_u.get("complete") and bool(undo_u.get("reversed"))
      and (get_character_config("Demo Rolled") or {}).get("importance") == imp_before, undo_u)
check("(u) the check baseline stays",
      isinstance(base_u, dict) and base_u.get("portrait") == world_dev_media.MISSING_OUTPUT_FP
      and wr.baselines(run9).get(("character", "Demo Rolled")) == base_u, base_u)
check("(u) both missing outputs still due",
      world_dev_media.due_step_ids(run9, "character", "Demo Rolled") == {"portrait", "build"},
      world_dev_media.due_step_ids(run9, "character", "Demo Rolled"))

# (v) a failing secrets / skills reader is no gap, logged, never a tool error
import logging  # noqa: E402

import app.models.secrets as secrets_mod  # noqa: E402


class _Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.msgs = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


def _boom(*_a, **_k):
    raise RuntimeError("reader down")


wr.set_status(run9, "accepted")
run10 = wr.create_run("completeness 10", "m", "p", "u", 40, 300000, media_enabled=False)
ctx10 = wt.ToolCtx(run_id=run10, turn=1)
grab = _Grab()
clog = logging.getLogger("world_dev_completeness")
clog.addHandler(grab)
real_list_secrets, real_open = secrets_mod.list_secrets, wt._open_skill_decisions
secrets_mod.list_secrets = _boom
wt._open_skill_decisions = _boom
try:
    res_c = call(ctx10, "create_character", {"data": {"name": "Demo Faulty"}})
    res_u = call(ctx10, "update_character", {"name": "Demo Faulty", "patch": {"importance": 2}})
    gaps_v = completeness.character_gaps("Demo Faulty")
finally:
    secrets_mod.list_secrets, wt._open_skill_decisions = real_list_secrets, real_open
    clog.removeHandler(grab)
check("(v) create_character ok", res_c.ok, res_c.line)
check("(v) update_character ok", res_u.ok, res_u.line)
check("(v) no secret/skills gap, the rest still reported",
      SECRET not in gaps_v and not any(g.startswith("skills not decided") for g in gaps_v)
      and BODY in gaps_v, gaps_v)
check("(v) both reader failures logged",
      any("secrets not readable" in m for m in grab.msgs)
      and any("skill decisions not readable" in m for m in grab.msgs), grab.msgs)

# (w) check_character / check_run are pure reads on a hand-made character
# whose stored config is "{}" (review finding: the config reader saved the
# defaults and the base-body plan created model_refs — writes outside the
# journal that Discard could not take back)
from app.core.db import get_connection  # noqa: E402


def _tree():
    return sorted(str(p.relative_to(STORAGE)) for p in STORAGE.rglob("*")
                  if not p.name.endswith((".db", ".db-wal", ".db-shm", ".db-journal")))


def _raw_cfg(name):
    row = get_connection().execute(
        "SELECT config_json FROM characters WHERE name=?", (name,)).fetchone()
    return row[0] if row else None


wr.set_status(run10, "accepted")
check("setup: Demo Bare saved", save_character_profile(
    "Demo Bare", {"name": "Demo Bare", "template": "human-roleplay"}, create_new=True))
with get_connection() as _conn:
    _conn.execute("UPDATE characters SET config_json='{}' WHERE name=?", ("Demo Bare",))
# save_character_profile(create_new) lays out an empty model_refs dir; a
# hand-made character may have none — the read must not create it.
from app.models.character import get_character_dir  # noqa: E402

_refs_w = get_character_dir("Demo Bare") / "model_refs"
if _refs_w.is_dir() and not any(_refs_w.iterdir()):
    _refs_w.rmdir()
check("setup: Demo Bare has no model_refs", not _refs_w.exists())
check("setup: Demo Bare config is '{}'", _raw_cfg("Demo Bare") == "{}", _raw_cfg("Demo Bare"))
run11 = wr.create_run("completeness 11", "m", "p", "u", 40, 300000)
ctx11 = wt.ToolCtx(run_id=run11, turn=1)
tree_w = _tree()  # after create_run (its safety backup is files too)
res = call(ctx11, "check_character", {"name": "Demo Bare"})
check("(w) check_character ok, media pending", res.ok
      and res.line.splitlines()[-1:] == [PENDING + MEDIA], res.line)
check("(w) check_character: config still '{}'", _raw_cfg("Demo Bare") == "{}",
      _raw_cfg("Demo Bare"))
check("(w) check_character: no new files", _tree() == tree_w,
      sorted(set(_tree()) - set(tree_w)))
res = call(ctx11, "set_skill", {"name": "Demo Bare", "skill": "demo_off2", "enabled": True})
check("(w) set_skill ok (puts Demo Bare into check_run)", res.ok, res.line)
cfg_w, tree_w2 = _raw_cfg("Demo Bare"), _tree()
res = call(ctx11, "check_run", {})
check("(w) check_run lists Demo Bare", res.ok and any(
    ln.startswith('character "Demo Bare"') for ln in res.line.splitlines()), res.line)
check("(w) check_run: config unchanged", _raw_cfg("Demo Bare") == cfg_w == "{}",
      (cfg_w, _raw_cfg("Demo Bare")))
check("(w) check_run: no new files", _tree() == tree_w2,
      sorted(set(_tree()) - set(tree_w2)))

if failures:
    print(f"FAILED ({len(failures)}): " + "; ".join(failures))
    sys.exit(1)
print("smoke_world_dev_completeness: all checks passed")
