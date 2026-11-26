#!/usr/bin/env python3
"""World Dev free mode — read errors in delete_created become refusals, and
discard_preview turns a failed rule/event read into a line, and a failed
rule/secret undo holds the place/character it names (plan
docs/superpowers/plans/2026-11-25-world-dev-free-media.md, Task 1).

Usage: ./.venv/bin/python scripts/smoke_world_dev_read_errors.py
Runs in a temp world (STORAGE_DIR / INSTANCE_DIR / ANIMATION_CLIPS_DIR temp,
paths.init before any world-DB import), no server, no LLM. Tool calls go
through world_dev_tools.run_tool exactly as the agent loop calls them.

The patches replace the MODULE attribute the code imports at call time
(`from app.models.rules import rules_naming` inside the function body reads
app.models.rules.rules_naming on every call), so patching the module is what
the tool sees.

WHAT IS CHECKED, and where every expected value comes from:

The refusal text is world_dev_tools._naming_refs:
  "the <label> could not be read (<str(exc)>) — nothing was deleted"
with label "world rules" for rules.rules_naming and "secrets" for
secrets.secrets_naming. str(RuleWriteError("broken")) == "broken",
str(sqlite3.OperationalError("locked")) == "locked".
A refusal raised before step.begin leaves exactly ONE journal row for the
call, of kind "refused" (run_tool: step.seq is None -> wr.begin("refused")).

(a) create_location "Demo Hut" in turn 1; rules.rules_naming raises
    RuleWriteError("broken"):
    delete_created{location, <hut>} in turn 1 (the same-turn path) -> ok False,
    line contains "the world rules could not be read (broken)", the call's
    journal kinds == ["refused"], the location still exists.
    The same call in turn 2 (the earlier-turn path, _delete_earlier) -> the
    same refusal, kinds ["refused"], the location still exists.
(b) create_character "Demo Keeper" (home Demo Hut) in turn 1;
    secrets.secrets_naming raises sqlite3.OperationalError("locked"):
    delete_created{character, "Demo Keeper"} in turn 1 and in turn 2 -> each
    ok False, line contains "the secrets could not be read (locked)", kinds
    ["refused"], the character still exists. Same with rules_naming raising
    (secrets unpatched) in turn 1 and in turn 2 -> each "the world rules could
    not be read (broken)", kinds ["refused"], the character still exists.
(c) create_item "Demo Lamp" in turn 2; rules_naming raises -> delete_created
    {item, <lamp>} in turn 2 -> ok False, "the world rules could not be read
    (broken)", kinds ["refused"], the item still exists (inventory.get_item).
(d) patches restored. add_block_rule{"Demo Hut closed", location <hut>} and
    add_event{"Demo smoke rises.", location <hut>} in turn 2.
    Unpatched discard_preview contains 'rule <R> "Demo Hut closed"' and
    'event <E> "Demo smoke rises."' (the ordinary lines, regression).
    rules.world_rule raising -> discard_preview does not raise and contains
    "rule <R> — the world rules cannot be read; the discard will report it"
    and no 'rule <R> "' line; world_dev_undo._event_row_strict raising ->
    "event <E> — the events cannot be read; the discard will report it".
    <R>, <E> come from the journal's write rows (inverse ids).
(e) a failed rule/secret undo holds what it names (world_dev_undo
    _HOLDING_OPS / held_names / REASON_HELD). Turn 2 adds rule R2
    {"Demo Keeper barred", location <hut>, character "Demo Keeper"} and secret
    S {owner "Demo Keeper", related_location <hut>}. Newest-first the undo
    walks S, R2, E, R, ... so the holder labels of the hut are
    "secret S, rule R2, rule R" (R2 alone names the keeper; S's owner is
    the keeper and never counts — secrets_naming without the owner).
    rules.world_rule and world_dev_undo.secret_row raising:
    discard_preview has
      'location <hut> "Demo Hut" is still named by secret S, rule R2, rule R,
       which cannot be read — the discard leaves it'
      'character "Demo Keeper" is still named by rule R2, which cannot be read
       — the discard leaves it'
    and no plain 'location <hut> "Demo Hut"' line. undo(run) then: complete
    False; the hut's skip reason is "still named by a step whose undo failed
    (secret S, rule R2, rule R) — kept for a later discard" with held_by
    [secret S, rule R2, rule R]; the keeper's names (rule R2); the hut, the
    keeper, R, R2 and S still exist; the not-undone writes are exactly
    {delete_secret S, delete_rule R2, delete_rule R, delete_location <hut>,
    delete_character "Demo Keeper"} (E and the lamp were undone).
    Unpatched, the next discard_preview lists them again: 'secret S of
    "Demo Keeper" (personal)', 'rule R2 "Demo Keeper barred"',
    'rule R "Demo Hut closed"', 'location <hut> "Demo Hut"' and a line
    starting 'character "Demo Keeper" — '. A second undo(run) unpatched:
    complete True, nothing left — discard_preview == [], the hut and the
    keeper gone.
    Since F6 the keeper (home and standing place: the hut, create_character
    puts it at its home) holds the hut too: the undo reaches the keeper's
    held delete_character (seq 2) before the hut's delete_location (seq 1)
    and adds the hut with the label 'character "Demo Keeper"'. So the hut's
    held_by is [secret S, rule R2, rule R, character "Demo Keeper"], the
    reason "still named by a step whose undo failed (secret S, rule R2,
    rule R), and character "Demo Keeper" stands or lives there and stays —
    kept for a later discard" (a character is not a failed step), and the
    preview line names the unreadable steps and the character apart:
      'location <hut> "Demo Hut" is still named by secret S, rule R2, rule R,
       which cannot be read, and character "Demo Keeper" stands or lives
       there and is kept — the discard leaves it'
(f) F6 (plan 2026-11-25-world-dev-free-fixes Task 6): a held character keeps
    the run-created place it stands in / lives in. A fixture run creates
    "Demo Square" Q (x 40) — foreign to the runs below, never undone. A rule
    whose condition is "present:<name>" names the character (held_names:
    condition_references family "present"); its location_id is Q, so the
    rule itself names no run-created place. rules.world_rule raising makes
    the rule's undo fail ("undo failed: disk I/O error") and the preview
    line "rule <R> — the world rules cannot be read; ...".
    Run A, turn 1: create_location "Demo Plaza" P (x 80) -> create_character
    "Demo Cara" home "Demo Plaza" (stands in P, home P) -> add_block_rule R
    {location Q, condition "present:Demo Cara"}. Patched:
    (f1) discard_preview contains
         'location <P> "Demo Plaza" stays: character "Demo Cara" stands or
          lives there and is kept — the discard leaves it'
         'character "Demo Cara" is still named by rule <R>, which cannot be
          read — the discard leaves it'
         and no 'location <P> "Demo Plaza"' line.
    (f2) undo(run A), newest-first R (fails, holds Cara), Cara (held by
         rule R; her live place P and home P are added with the label
         'character "Demo Cara"'), P (held): complete False; R's skip starts
         "undo failed: "; Cara's held_by == ["rule <R>"]; P's held_by ==
         ['character "Demo Cara"'], reason 'character "Demo Cara" stands or
         lives there and stays — kept for a later discard'; P
         exists; the not-undone writes are exactly {delete_rule R,
         delete_character Cara, delete_location P}.
    (f3) unpatched undo(run A): complete True, P and Cara gone, preview [].
    Run B — the run's own moves are reversed first: P2 "Demo Market" (x
    120), "Demo Dana" home P2, rule RB {Q, present:Demo Dana} in turn 1;
    turn 2 place_character Dana -> Q and update_character Dana {home: Q}.
    Live: Dana stands in Q, home Q. The undo reaches the home restore and
    the placement restore (newer) first: Dana back in P2, home P2, so P2 is
    held via place and home. Patched:
    (f4) preview: 'location <P2> "Demo Market" stays: character "Demo Dana"
         stands or lives there and is kept — the discard leaves it' (the
         preview simulates the placement and the home back,
         simulated_places / simulated_home), no plain P2 line;
         undo: P2 held_by ['character "Demo Dana"'], Dana in P2 with home
         P2; unpatched second undo complete True, P2 and Dana gone.
    Run C — moves somebody else made stay: P3 "Demo Yard" (x 160), "Demo
    Eve" home P3, rule RC {Q, present:Demo Eve}; then OUTSIDE the run Eve is
    placed in Q (character.write_placement). Patched:
    (f5) preview: P3 still "stays: character "Demo Eve" stands or lives
         there ..." (home P3); undo: P3 held_by ['character "Demo Eve"'].
    (f6) then OUTSIDE the run Eve's home becomes Q (save_character_config):
         patched preview has the plain 'location <P3> "Demo Yard"' line and
         no "stays" line for P3 (and no stranded-occupant line: Eve stands in
         Q); patched undo deletes P3 (its seq is reversed), Eve still exists
         and stands in Q, held_by ["rule <RC>"]. Unpatched third undo:
         complete True, Eve gone.
    Run D — the held character's place cannot be read: "Demo Shed" S4 (x
    200), then "Demo Lane" P4 (x 240), "Demo Finn" home P4, rule RD {Q,
    present:Demo Finn}. With rules.world_rule AND world_dev_undo.
    home_schedule_state raising, neither undo (live read) nor the preview
    (simulated_home) knows Finn's places, so both hold EVERY run-created
    place older than Finn — S4 and P4 — with the label 'character "Demo
    Finn"' (conservative, the two agree):
    (f7) preview contains stays lines for S4 "Demo Shed" and P4 "Demo Lane"
         and no plain line of either; undo: S4 and P4 each held_by
         ['character "Demo Finn"'], both still exist, Finn still exists.
         Unpatched second undo: complete True, S4, P4 and Finn gone.
    Run E — the held character's place was deleted OUTSIDE the run: "Demo
    Pier" P5 (x 280), "Demo Gus" home P5 (stands in P5, home P5), rule RE
    {Q, present:Demo Gus}; then world.delete_location(P5) outside the run.
    A character holds only a place that exists, and the preview lists only
    what still exists. Patched (rules.world_rule raising):
    (f8) preview has no line naming P5; undo walks RE (fails, holds Gus),
         Gus (held by RE; live place/home P5 get the character label), P5:
         P5 no longer exists, so the label is dropped and its
         delete_location runs apply_inverse -&gt; one skip with reason
         "already gone" (world_dev_undo.REASON_GONE) and no held_by, the
         entry marked undone; no skip carries held_by ['character "Demo
         Gus"']. Journal left exactly {delete_rule RE, delete_character Gus}.
         Unpatched second undo: complete True, Gus gone, preview [].
    Run F — the existence check itself fails: "Demo Dock" P6 (x 320), "Demo
    Hal" home P6, rule RF {Q, present:Demo Hal}. With rules.world_rule,
    world_dev_undo.home_schedule_state AND models.world.get_location_by_id
    raising, undo() must not raise: Hal is an unread holder, the check of P6
    fails and counts as existing, so P6 is held: one skip with held_by
    ['character "Demo Hal"'], P6 still exists (read unpatched).
    (f9) unpatched second undo: complete True, P6 and Hal gone.
"""
import atexit
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="smoke_wd_read_errors_"))
atexit.register(shutil.rmtree, ROOT, True)
STORAGE = ROOT / "world"
STORAGE.mkdir()
(ROOT / "clips").mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")
(STORAGE / "config.json").write_text(json.dumps({"game": {"discovery_range_m": 0}}),
                                     encoding="utf-8")

from app.core import paths  # noqa: E402

paths.init(STORAGE)
paths.init_instance(ROOT / "instance")

from app.core import config, db  # noqa: E402

config.load(STORAGE / "config.json")
db.init_schema()

from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.models import character as ch  # noqa: E402
from app.models import rules, secrets  # noqa: E402
from app.models.inventory import get_item  # noqa: E402
from app.models.world import get_location_by_id, list_locations  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


run = wr.create_run("read errors", "m", "p", "u", 200, 300000)


def call(tool, args, turn):
    """run_tool plus the journal kinds of the rows this call added. A read
    error that escapes as an exception (the old behaviour) is returned as
    (None, kinds, repr) so the check fails instead of the script."""
    before = {e["seq"] for e in wr.entries(run, writes_only=False, include_undone=True)}
    try:
        res = wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)
        err = None
    except Exception as e:  # noqa: BLE001 — reported by the checks
        res, err = None, repr(e)
    kinds = [e.get("kind") for e in sorted(wr.entries(run, writes_only=False,
                                                      include_undone=True),
                                           key=lambda e: e["seq"])
             if e["seq"] not in before]
    return res, kinds, err


def refused_with(label, res, kinds, err, text):
    check(f"{label}: ok False", res is not None and not res.ok, err or (res and res.line))
    check(f"{label}: line names the read error", res is not None and text in res.line,
          err or (res and res.line))
    check(f"{label}: one refused row", kinds == ["refused"], kinds)


def broken_rules(**_kw):
    raise rules.RuleWriteError("broken")


def locked_secrets(*_a, **_kw):
    raise sqlite3.OperationalError("locked")


RULES_TEXT = "the world rules could not be read (broken)"
SECRETS_TEXT = "the secrets could not be read (locked)"

print("fixture")
r = wt.run_tool(wt.ToolCtx(run_id=run, turn=1), "create_location",
                {"data": {"name": "Demo Hut"}, "x": 0, "z": 0})
check("Demo Hut created", r.ok and r.wrote, r.line)
HUT = next((l["id"] for l in list_locations() if l.get("name") == "Demo Hut"), "")
r = wt.run_tool(wt.ToolCtx(run_id=run, turn=1), "create_character",
                {"data": {"name": "Demo Keeper"}, "home": "Demo Hut"})
check("Demo Keeper created", r.ok and r.wrote, r.line)
KEEPER = "Demo Keeper"


def keeper_exists():
    return KEEPER in ch.list_available_characters(include_pooled=True)


print("(a) location, rules_naming broken")
with patch.object(rules, "rules_naming", broken_rules):
    for turn in (1, 2):
        res, kinds, err = call("delete_created", {"kind": "location", "id": HUT}, turn)
        refused_with(f"(a) turn {turn}", res, kinds, err, RULES_TEXT)
        check(f"(a) turn {turn}: the location still exists",
              get_location_by_id(HUT) is not None)

print("(b) character, secrets_naming / rules_naming broken")
with patch.object(secrets, "secrets_naming", locked_secrets):
    for turn in (1, 2):
        res, kinds, err = call("delete_created", {"kind": "character", "id": KEEPER}, turn)
        refused_with(f"(b) turn {turn}", res, kinds, err, SECRETS_TEXT)
        check(f"(b) turn {turn}: the character still exists", keeper_exists())
with patch.object(rules, "rules_naming", broken_rules):
    for turn in (1, 2):
        res, kinds, err = call("delete_created", {"kind": "character", "id": KEEPER}, turn)
        refused_with(f"(b) rules turn {turn}", res, kinds, err, RULES_TEXT)
        check(f"(b) rules turn {turn}: the character still exists", keeper_exists())

print("(c) item, rules_naming broken")
r = wt.run_tool(wt.ToolCtx(run_id=run, turn=2), "create_item",
                {"name": "Demo Lamp", "category": "tool"})
check("(c) Demo Lamp created", r.ok and r.wrote, r.line)
LAMP = next((str(i) for e in wr.entries(run) if (e.get("inverse") or {}).get("op")
             == "delete_items" for i in (e["inverse"].get("ids") or [])), "")
check("(c) lamp id from the journal", bool(LAMP), LAMP)
with patch.object(rules, "rules_naming", broken_rules):
    res, kinds, err = call("delete_created", {"kind": "item", "id": LAMP}, 2)
    refused_with("(c)", res, kinds, err, RULES_TEXT)
    check("(c) the item still exists", get_item(LAMP) is not None)

print("(d) discard_preview")
r = wt.run_tool(wt.ToolCtx(run_id=run, turn=2), "add_block_rule",
                {"name": "Demo Hut closed", "message": "Closed.", "location_id": HUT,
                 "condition": "night"})
check("(d) rule added", r.ok and r.wrote, r.line)
r = wt.run_tool(wt.ToolCtx(run_id=run, turn=2), "add_event",
                {"text": "Demo smoke rises.", "location_id": HUT, "ttl_hours": 6})
check("(d) event added", r.ok and r.wrote, r.line)


def inverse_id(op):
    return next((str((e.get("inverse") or {}).get("id") or "") for e in wr.entries(run)
                 if (e.get("inverse") or {}).get("op") == op), "")


RID, EID = inverse_id("delete_rule"), inverse_id("delete_event")
check("(d) rule and event ids from the journal", bool(RID and EID), (RID, EID))
plain = wu.discard_preview(run)
check("(d) unpatched rule line", f'rule {RID} "Demo Hut closed"' in plain, plain)
check("(d) unpatched event line", f'event {EID} "Demo smoke rises."' in plain, plain)


def boom(*_a, **_kw):
    raise sqlite3.OperationalError("disk I/O error")


for label, target, attr, want, gone in (
        ("rule", rules, "world_rule",
         f"rule {RID} — the world rules cannot be read; the discard will report it",
         f'rule {RID} "'),
        ("event", wu, "_event_row_strict",
         f"event {EID} — the events cannot be read; the discard will report it",
         f'event {EID} "')):
    with patch.object(target, attr, boom):
        try:
            lines, err = wu.discard_preview(run), None
        except Exception as e:  # noqa: BLE001 — reported by the checks
            lines, err = [], repr(e)
    check(f"(d) {label} read error: preview does not raise", err is None, err)
    check(f"(d) {label} read error: the line", want in lines, lines)
    check(f"(d) {label} read error: no ordinary line",
          not any(x.startswith(gone) for x in lines), lines)

print("(e) a failed rule/secret undo holds the place and character it names")
r = wt.run_tool(wt.ToolCtx(run_id=run, turn=2), "add_block_rule",
                {"name": "Demo Keeper barred", "message": "Not you.", "location_id": HUT,
                 "condition": "night", "character": KEEPER})
check("(e) rule R2 added", r.ok and r.wrote, r.line)
R2 = next((str((e.get("inverse") or {}).get("id") or "") for e in wr.entries(run)
           if (e.get("inverse") or {}).get("op") == "delete_rule"), "")
r = wt.run_tool(wt.ToolCtx(run_id=run, turn=2), "add_secret",
                {"name": KEEPER, "content": "Demo keeper hides a key.",
                 "related_location": HUT})
check("(e) secret S added", r.ok and r.wrote, r.line)
SID = inverse_id("delete_secret")
check("(e) R2 and S from the journal", bool(R2 and SID) and R2 != RID, (R2, SID, RID))
HOLDERS = f"secret {SID}, rule {R2}, rule {RID}"
KEEPER_LABEL = f'character "{KEEPER}"'
HUT_HELD = (f'location {HUT} "Demo Hut" is still named by {HOLDERS}, which cannot be '
            f"read, and {KEEPER_LABEL} stands or lives there and is kept — the discard "
            "leaves it")
KEEPER_HELD = (f'character "{KEEPER}" is still named by rule {R2}, which cannot be read '
               "— the discard leaves it")
with patch.object(rules, "world_rule", boom), patch.object(wu, "secret_row", boom):
    lines = wu.discard_preview(run)
    check("(e) preview: the hut is held", HUT_HELD in lines, lines)
    check("(e) preview: the keeper is held", KEEPER_HELD in lines, lines)
    check("(e) preview: no plain hut line", f'location {HUT} "Demo Hut"' not in lines, lines)
    rep = wu.undo(run)
check("(e) undo incomplete", rep["complete"] is False, rep)
hut_skip = next((s for s in rep["skipped"] if s.get("held_by") == [f"secret {SID}",
                f"rule {R2}", f"rule {RID}", KEEPER_LABEL]), None)
check("(e) hut skip reason", hut_skip is not None and hut_skip["reason"]
      == (f"still named by a step whose undo failed ({HOLDERS}), and {KEEPER_LABEL} "
          "stands or lives there and stays — kept for a later discard"), rep["skipped"])
check("(e) keeper skip", any(s.get("held_by") == [f"rule {R2}"] for s in rep["skipped"]),
      rep["skipped"])
check("(e) hut, keeper, rules, secret still exist",
      get_location_by_id(HUT) is not None and keeper_exists()
      and rules.world_rule(RID) is not None and rules.world_rule(R2) is not None
      and wu.secret_row(KEEPER, SID) is not None)
left = sorted((e["inverse"]["op"], str(e["inverse"].get("id") or e["inverse"].get("name")))
              for e in wr.entries(run))
want = sorted([("delete_secret", SID), ("delete_rule", R2), ("delete_rule", RID),
               ("delete_location", HUT), ("delete_character", KEEPER)])
check("(e) exactly the held writes stay in the journal", left == want, left)
lines = wu.discard_preview(run)
for want_line in (f'secret {SID} of "{KEEPER}" (personal)', f'rule {R2} "Demo Keeper barred"',
                  f'rule {RID} "Demo Hut closed"', f'location {HUT} "Demo Hut"'):
    check(f"(e) later preview: {want_line}", want_line in lines, lines)
check("(e) later preview: the keeper line",
      any(x.startswith(f'character "{KEEPER}" — ') for x in lines), lines)
rep = wu.undo(run)
check("(e) second undo complete", rep["complete"] is True, rep)
check("(e) nothing left", wu.discard_preview(run) == [], wu.discard_preview(run))
check("(e) hut and keeper gone", get_location_by_id(HUT) is None and not keeper_exists())

print("(f) F6: a held character keeps the run-created place it stands in / lives in")
# One open run at a time (idx_world_dev_runs_one_open): each run below is
# closed before the next one opens.
wr.set_status(run, "rolled_back")
fix = wr.create_run("fixture", "m", "p", "u", 200, 300000)
r = wt.run_tool(wt.ToolCtx(run_id=fix, turn=1), "create_location",
                {"data": {"name": "Demo Square"}, "x": 40, "z": 0})
check("(f) Demo Square created", r.ok and r.wrote, r.line)
Q = next((l["id"] for l in list_locations() if l.get("name") == "Demo Square"), "")
wr.set_status(fix, "accepted")


def loc_id(name):
    return next((l["id"] for l in list_locations() if l.get("name") == name), "")


def char_exists(name):
    return name in ch.list_available_characters(include_pooled=True)


def stands_in(name):
    return str((ch.read_placement(name).get("profile") or {}).get("current_location") or "")


def setup_run(label, place, x, who):
    rid = wr.create_run(label, "m", "p", "u", 200, 300000)
    res = wt.run_tool(wt.ToolCtx(run_id=rid, turn=1), "create_location",
                      {"data": {"name": place}, "x": x, "z": 0})
    check(f"({label}) {place} created", res.ok and res.wrote, res.line)
    res = wt.run_tool(wt.ToolCtx(run_id=rid, turn=1), "create_character",
                      {"data": {"name": who}, "home": place})
    check(f"({label}) {who} created", res.ok and res.wrote, res.line)
    res = wt.run_tool(wt.ToolCtx(run_id=rid, turn=1), "add_block_rule",
                      {"name": f"{who} barred", "message": "No.", "location_id": Q,
                       "condition": f"present:{who}"})
    check(f"({label}) rule added", res.ok and res.wrote, res.line)
    rule_id = next((str((e.get("inverse") or {}).get("id") or "") for e in wr.entries(rid)
                    if (e.get("inverse") or {}).get("op") == "delete_rule"), "")
    return rid, loc_id(place), rule_id


def stays_line(lid, place, who):
    return (f'location {lid} "{place}" stays: character "{who}" stands or lives there '
            "and is kept — the discard leaves it")


def skip_of(rep, label):
    return next((s for s in rep["skipped"] if s.get("held_by") == [label]), None)


RUN_A, P, RA = setup_run("f-A", "Demo Plaza", 80, "Demo Cara")
check("(f) Cara stands in P with home P", stands_in("Demo Cara") == P
      and wu.home_schedule_state("Demo Cara").get("home_location") == P,
      (stands_in("Demo Cara"), wu.home_schedule_state("Demo Cara")))
CARA = 'character "Demo Cara"'
with patch.object(rules, "world_rule", boom):
    lines = wu.discard_preview(RUN_A)
    check("(f1) preview: P stays", stays_line(P, "Demo Plaza", "Demo Cara") in lines, lines)
    check("(f1) preview: Cara held", f'character "Demo Cara" is still named by rule {RA}, '
          "which cannot be read — the discard leaves it" in lines, lines)
    check("(f1) preview: no plain P line", f'location {P} "Demo Plaza"' not in lines, lines)
    rep = wu.undo(RUN_A)
check("(f2) undo incomplete", rep["complete"] is False, rep)
check("(f2) R failed", any(str(s.get("reason") or "").startswith("undo failed: ")
                           for s in rep["skipped"]), rep["skipped"])
check("(f2) Cara held by R", skip_of(rep, f"rule {RA}") is not None, rep["skipped"])
p_skip = skip_of(rep, CARA)
check("(f2) P held by Cara", p_skip is not None and p_skip["reason"]
      == f"{CARA} stands or lives there and stays — kept for a later discard",
      rep["skipped"])
check("(f2) P exists", get_location_by_id(P) is not None)
left = sorted((e["inverse"]["op"], str(e["inverse"].get("id") or e["inverse"].get("name")))
              for e in wr.entries(RUN_A))
check("(f2) exactly R, Cara, P stay in the journal", left == sorted(
    [("delete_rule", RA), ("delete_character", "Demo Cara"), ("delete_location", P)]), left)
rep = wu.undo(RUN_A)
check("(f3) unpatched undo complete", rep["complete"] is True, rep)
check("(f3) P and Cara gone", get_location_by_id(P) is None and not char_exists("Demo Cara"))
check("(f3) nothing left", wu.discard_preview(RUN_A) == [], wu.discard_preview(RUN_A))
wr.set_status(RUN_A, "rolled_back")

RUN_B, P2, RB = setup_run("f-B", "Demo Market", 120, "Demo Dana")
r = wt.run_tool(wt.ToolCtx(run_id=RUN_B, turn=2), "place_character",
                {"name": "Demo Dana", "location_id": Q})
check("(f4) Dana placed in Q", r.ok and r.wrote and stands_in("Demo Dana") == Q, r.line)
r = wt.run_tool(wt.ToolCtx(run_id=RUN_B, turn=2), "update_character",
                {"name": "Demo Dana", "patch": {"home": Q}})
check("(f4) Dana's home is Q", r.ok and r.wrote
      and wu.home_schedule_state("Demo Dana").get("home_location") == Q, r.line)
with patch.object(rules, "world_rule", boom):
    lines = wu.discard_preview(RUN_B)
    check("(f4) preview: P2 stays", stays_line(P2, "Demo Market", "Demo Dana") in lines, lines)
    check("(f4) preview: no plain P2 line", f'location {P2} "Demo Market"' not in lines, lines)
    rep = wu.undo(RUN_B)
check("(f4) undo: P2 held by Dana", skip_of(rep, 'character "Demo Dana"') is not None,
      rep["skipped"])
check("(f4) undo: Dana back in P2 with home P2", stands_in("Demo Dana") == P2
      and wu.home_schedule_state("Demo Dana").get("home_location") == P2,
      (stands_in("Demo Dana"), wu.home_schedule_state("Demo Dana")))
rep = wu.undo(RUN_B)
check("(f4) unpatched undo complete", rep["complete"] is True, rep)
check("(f4) P2 and Dana gone", get_location_by_id(P2) is None and not char_exists("Demo Dana"))
wr.set_status(RUN_B, "rolled_back")

RUN_C, P3, RC = setup_run("f-C", "Demo Yard", 160, "Demo Eve")
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.models.world import get_arrival_room_id  # noqa: E402
with keyed_lock("character_profile", "Demo Eve"):
    ch.write_placement("Demo Eve", {"current_location": Q,
                                    "current_room": get_arrival_room_id(get_location_by_id(Q))},
                       {"x": 40.0, "z": 0.0, "yaw": None, "session": None, "seq": None})
check("(f5) Eve stands in Q (outside the run)", stands_in("Demo Eve") == Q, stands_in("Demo Eve"))
with patch.object(rules, "world_rule", boom):
    lines = wu.discard_preview(RUN_C)
    check("(f5) preview: P3 stays (home)", stays_line(P3, "Demo Yard", "Demo Eve") in lines,
          lines)
    rep = wu.undo(RUN_C)
check("(f5) undo: P3 held by Eve", skip_of(rep, 'character "Demo Eve"') is not None,
      rep["skipped"])
check("(f5) P3 exists", get_location_by_id(P3) is not None)
with keyed_lock("character_profile", "Demo Eve"):
    cfg = dict(ch.get_character_config("Demo Eve") or {})
    cfg["home_location"] = Q
    check("(f6) Eve's home is Q (outside the run)", ch.save_character_config("Demo Eve", cfg))
with patch.object(rules, "world_rule", boom):
    lines = wu.discard_preview(RUN_C)
    check("(f6) preview: plain P3 line", f'location {P3} "Demo Yard"' in lines, lines)
    check("(f6) preview: no stays / stranded line for P3",
          not any(P3 in x and x != f'location {P3} "Demo Yard"' for x in lines), lines)
    p3_seq = next((e["seq"] for e in wr.entries(RUN_C)
                   if (e.get("inverse") or {}).get("op") == "delete_location"), None)
    rep = wu.undo(RUN_C)
check("(f6) undo: P3 reversed and gone", p3_seq in rep["reversed"]
      and get_location_by_id(P3) is None, rep)
check("(f6) Eve stays in Q, held by RC", char_exists("Demo Eve") and stands_in("Demo Eve") == Q
      and skip_of(rep, f"rule {RC}") is not None, rep["skipped"])
rep = wu.undo(RUN_C)
check("(f6) unpatched undo complete", rep["complete"] is True, rep)
check("(f6) Eve gone", not char_exists("Demo Eve"))
wr.set_status(RUN_C, "rolled_back")

RUN_D = wr.create_run("f-D", "m", "p", "u", 200, 300000)
r = wt.run_tool(wt.ToolCtx(run_id=RUN_D, turn=1), "create_location",
                {"data": {"name": "Demo Shed"}, "x": 200, "z": 0})
check("(f7) Demo Shed created", r.ok and r.wrote, r.line)
r = wt.run_tool(wt.ToolCtx(run_id=RUN_D, turn=1), "create_location",
                {"data": {"name": "Demo Lane"}, "x": 240, "z": 0})
check("(f7) Demo Lane created", r.ok and r.wrote, r.line)
r = wt.run_tool(wt.ToolCtx(run_id=RUN_D, turn=1), "create_character",
                {"data": {"name": "Demo Finn"}, "home": "Demo Lane"})
check("(f7) Demo Finn created", r.ok and r.wrote, r.line)
r = wt.run_tool(wt.ToolCtx(run_id=RUN_D, turn=1), "add_block_rule",
                {"name": "Demo Finn barred", "message": "No.", "location_id": Q,
                 "condition": "present:Demo Finn"})
check("(f7) rule added", r.ok and r.wrote, r.line)
S4, P4 = loc_id("Demo Shed"), loc_id("Demo Lane")
FINN = 'character "Demo Finn"'
with patch.object(rules, "world_rule", boom), patch.object(wu, "home_schedule_state", boom):
    lines = wu.discard_preview(RUN_D)
    check("(f7) preview: S4 stays", stays_line(S4, "Demo Shed", "Demo Finn") in lines, lines)
    check("(f7) preview: P4 stays", stays_line(P4, "Demo Lane", "Demo Finn") in lines, lines)
    check("(f7) preview: no plain S4/P4 line", f'location {S4} "Demo Shed"' not in lines
          and f'location {P4} "Demo Lane"' not in lines, lines)
    rep = wu.undo(RUN_D)
held_d = sorted(str(s.get("location") or s.get("line") or "") for s in rep["skipped"]
                if s.get("held_by") == [FINN])
check("(f7) undo: two places held by Finn", len(held_d) == 2, rep["skipped"])
check("(f7) S4, P4 and Finn still exist", get_location_by_id(S4) is not None
      and get_location_by_id(P4) is not None and char_exists("Demo Finn"))
rep = wu.undo(RUN_D)
check("(f7) unpatched undo complete", rep["complete"] is True, rep)
check("(f7) S4, P4 and Finn gone", get_location_by_id(S4) is None
      and get_location_by_id(P4) is None and not char_exists("Demo Finn"))
wr.set_status(RUN_D, "rolled_back")

from app.models import world as world_models  # noqa: E402

RUN_E, P5, RE = setup_run("f-E", "Demo Pier", 280, "Demo Gus")
check("(f8) Gus stands in P5 with home P5", stands_in("Demo Gus") == P5
      and wu.home_schedule_state("Demo Gus").get("home_location") == P5,
      (stands_in("Demo Gus"), wu.home_schedule_state("Demo Gus")))
check("(f8) P5 deleted outside the run", world_models.delete_location(P5)
      and get_location_by_id(P5) is None)
GUS = 'character "Demo Gus"'
p5_seq = next((e["seq"] for e in wr.entries(RUN_E)
               if (e.get("inverse") or {}).get("op") == "delete_location"), None)
with patch.object(rules, "world_rule", boom):
    lines = wu.discard_preview(RUN_E)
    check("(f8) preview: no line names P5", not any(P5 in x for x in lines), lines)
    rep = wu.undo(RUN_E)
p5_skips = [s for s in rep["skipped"] if s.get("seq") == p5_seq]
check("(f8) undo: P5 already gone, not held", len(p5_skips) == 1
      and p5_skips[0].get("reason") == wu.REASON_GONE and not p5_skips[0].get("held_by"),
      rep["skipped"])
check("(f8) undo: nothing held by Gus", skip_of(rep, GUS) is None, rep["skipped"])
left = sorted((e["inverse"]["op"], str(e["inverse"].get("id") or e["inverse"].get("name")))
              for e in wr.entries(RUN_E))
check("(f8) exactly RE and Gus stay in the journal", left == sorted(
    [("delete_rule", RE), ("delete_character", "Demo Gus")]), left)
rep = wu.undo(RUN_E)
check("(f8) unpatched undo complete", rep["complete"] is True, rep)
check("(f8) Gus gone, nothing left", not char_exists("Demo Gus")
      and wu.discard_preview(RUN_E) == [], wu.discard_preview(RUN_E))
wr.set_status(RUN_E, "rolled_back")

RUN_F, P6, RF = setup_run("f-F", "Demo Dock", 320, "Demo Hal")
HAL = 'character "Demo Hal"'
try:
    with patch.object(rules, "world_rule", boom), \
            patch.object(wu, "home_schedule_state", boom), \
            patch.object(world_models, "get_location_by_id", boom):
        rep = wu.undo(RUN_F)
    raised = None
except Exception as e:  # noqa: BLE001 — the check reports it
    raised, rep = e, {"skipped": []}
check("(f9) undo does not raise on a failed place read", raised is None, raised)
check("(f9) P6 held by Hal", skip_of(rep, HAL) is not None, rep["skipped"])
check("(f9) P6 and Hal still exist", get_location_by_id(P6) is not None
      and char_exists("Demo Hal"))
rep = wu.undo(RUN_F)
check("(f9) unpatched undo complete", rep["complete"] is True, rep)
check("(f9) P6 and Hal gone", get_location_by_id(P6) is None and not char_exists("Demo Hal"))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("all checks passed")
