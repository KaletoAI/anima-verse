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
HUT_HELD = (f'location {HUT} "Demo Hut" is still named by {HOLDERS}, which cannot be '
            "read — the discard leaves it")
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
                f"rule {R2}", f"rule {RID}"]), None)
check("(e) hut skip reason", hut_skip is not None and hut_skip["reason"]
      == f"still named by a step whose undo failed ({HOLDERS}) — kept for a later discard",
      rep["skipped"])
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

print()
if failures:
    print(f"FAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("all checks passed")
