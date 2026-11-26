#!/usr/bin/env python3
"""World Dev free mode — create_quest_template / delete_quest_template, the
quest list_catalog entries, and the template field check moved to
quest_engine.check_template_fields (plan
docs/superpowers/plans/2026-11-25-world-dev-free-p3-world-systems.md, Task 7).

Usage: ./.venv/bin/python scripts/smoke_world_dev_quests.py
Runs in a temp world (STORAGE_DIR / INSTANCE_DIR temp), no server.

WHAT IS CHECKED, and where every expected value comes from:

The condition type used is the core type "spoke_with" of
app/core/quest_types.py: kind "condition", label "Has spoken with", ONE
param "character" of type "role" (role kinds ["character"]). A step is
{"id", "text", "condition"} (quest_engine.validate_template: id and text
required, condition checked by quest_catalog.check_expression). So the
template of (a) — role {key "miller", kind "character"}, step {id "s1",
text "Speak with {miller}.", condition {type spoke_with, params {character:
"miller"}}} — has no authoring issue. A template id is "qt_" + 12 hex digits
(quests.create_template) — read at runtime from the result line.

Run 1:
  (a) create_quest_template{title "The lost mill", summary, gm_notes, roles,
      steps as above} -> ok, line exactly
      'created draft quest template <A> "The lost mill" (1 role, 1 step)'
      (no "issues:"; singular for 1, like add_event's "1 game hour").
      quests.get_template(A): state "draft", origin "admin", revision 1
      (create_template inserts at revision 1), title / summary / gm_notes /
      roles / steps exactly as sent. One write journal row, target
      ("quest_template", A), inverse {"op": "delete_quest_template", "id": A}.
  (b) roles [{key "x", kind "dragon"}] -> ok WITH "issues:" and the issue
      "roles.0.kind: A role kind is one of character, location, room, item"
      (validate_template, bad_kind; the kinds are quest_catalog.ROLE_KINDS).
      Its template B is stored as a draft anyway (E9: issues are warnings).
  (c) refusals (each adds no write row and no template): title 5 -> "title
      must be text" (check_template_fields, the route's 400 message);
      time_limit_s -1 -> "time_limit_s is a whole number of seconds, 0 or more";
      no title -> "title"; title "  " -> "title"; roles "x" (not a list) ->
      "roles"; steps {} -> "steps"; start_condition [] -> "start_condition";
      prerequisites "x" -> "prerequisites"; unknown key "state" -> "state";
      gm_notes of 300 000 characters -> "256 KiB" (the route's body cap
      256 * 1024 bytes); roles nested 5000 lists deep -> "nested too deeply"
      (a refusal, not a RecursionError); roles nested so the args reach depth
      65 (the roles list at depth 2, wrapped in 63 more lists) -> "nested too deeply"
      (wt.MAX_ARG_DEPTH 64), while start_condition at depth 64 (a list,
      62 wraps) is refused only as "start_condition" (not an object), NOT
      for its depth.
  (d) quests.update_template(A, {"summary": "x"}, base_revision=1) directly
      (revision 2) -> discard_preview == ['quest template <A> was changed
      since — the discard leaves it alone', 'quest template <B> "<B title>"']
      (creation order A, B); undo -> not complete, exactly one "changed since"
      skip with keys ["revision"]; A stays, B gone. A removed by hand.
Run 2 (clean):
  (e) two templates E1, E2 -> discard_preview == ['quest template <E1>
      "Demo One"', 'quest template <E2> "Demo Two"']; delete_created
      {quest_template, E3} in the turn that made E3 -> ok, gone; E4 made in
      turn 1, delete_created in turn 2 -> refused "created in an earlier turn"
      (E2 same-turn only), E4 stays and joins the preview; undo -> complete;
      quests.list_templates() == [].
Run 3 (a run of the template):
  (f) template R; quests.create_run(template=R, bindings={}, state="hidden")
      directly -> discard_preview == ['quest template <R> was changed since —
      the discard leaves it alone'] (revision still 1, but a run exists);
      undo -> not complete, one skip keys ["runs"]; R stays.
Catalogs:
  (g) list_catalog{quest_types} returns the two header lines declared in
      world_dev_tools._QUEST_TYPES_HEADER followed by one line per registered
      type, never cut (no line starts with "… ", budget MAX_QUEST_TYPES_CHARS):
      - header 1: 'Conditions go into steps[].condition and start_condition,
        prerequisite types into prerequisites.condition; an effect is an entry
        {"key", "type", "params", "permanent"?} of setup_effects,
        steps[].on_done or rewards.'
      - header 2: '* = required. role[k] takes a role key of kind k.
        target[...] takes a role key of the listed kind or the key of an
        EARLIER effect that makes the listed object kind: a step condition
        reaches setup_effects and the on_done of earlier steps; an on_done
        entry also the earlier entries of its own list; a reward every effect
        key; a setup entry the earlier setup entries; start_condition and
        prerequisites setup keys only.'
      - spoke_with (app/core/quest_types.py::_builtin_types: kind "condition",
        label "Has spoken with", object_kind "", one required role param
        "character" with role_kinds ["character"]):
        'spoke_with (condition) — Has spoken with: params character*:role[character]'
      - place_item (app/core/quest_effects.py::builtin_effect_types: kind
        "effect", label "Place an item", object_kind "room_item", params:
        required target item [role_kinds item, object_kinds item], required
        role room [role_kinds room], int quantity, bool hidden, int difficulty,
        str note):
        'place_item (effect, makes room_item) — Place an item: params item*:target[item role or item effect key], room*:role[room], quantity:int, hidden:bool, difficulty:int, note:str'
      - give_item (app/core/quest_effects.py::builtin_effect_types: kind
        "effect", label "Give an item", object_kind "grant", params: required
        target item [role_kinds item, object_kinds item], role to [role_kinds
        character, avatar_default True], int quantity):
        'give_item (effect, makes grant) — Give an item: params item*:target[item role or item effect key], to:role[character; empty = the avatar], quantity:int'
      - every id of quest_catalog.types() starts exactly one line.
      list_catalog{quest_roles} lines == ['character', 'location', 'room',
      'item'] (ROLE_KINDS).
Route:
  (h) routes.quests._create_template_sync({"title": "x", "summary": 5})
      raises HTTPException 400 with detail {"code": "bad_request", "message":
      "summary must be text"} — the same body as before the move (a title
      that is not text answers "title is required" first, the route's own
      order); _update_template_sync(<id>, {"base_revision": 1, "title": 5})
      -> 400 "title must be text" (checked before the template is read, so
      any id); quest_engine
      .check_template_fields({"time_limit_s": True}) == "time_limit_s is a
      whole number of seconds, 0 or more" (a bool is not a number) and
      check_template_fields({"title": "x", "time_limit_s": 0}) is None.
Run 4 (stage-2 template & blocking errors):
  (i) create_quest_template with TPL_I ("The big rock": giver_role "giver",
      3 roles giver/wood/glade, 4 setup_effects rock/box/box_spot/hint, 4
      steps s1..s4 with s2.on_done [told], 2 rewards charm/charm_given) -> ok
      and wrote, line exactly
      'created draft quest template <I> "The big rock" (3 roles, 4 steps)'
      (no "issues:"); stored as state "draft" with every sent key verbatim;
      quest_engine.validate_template(row) == []; one new write row with target
      ("quest_template", I) and inverse {"op": "delete_quest_template", "id": I};
      no run created; wu.undo(run) -> complete and template gone.
  (j) stage-2 errors refused (not ok, not wrote, line starts with "error:",
      no write row and no template added), each expected message derived from
      source:
      - j1 setup_effects "x" -> "'setup_effects' must be a list (leave it out
        for none)" (quest_engine.check_template_fields);
      - j2 rewards {} -> "'rewards' must be a list" (quest_engine.check_template_fields:
        "'rewards' must be a list (leave it out for none)");
      - j3 TPL_I with box_spot moved before box (index 1) ->
        "setup_effects.1.params.item: Item: 'box' is created only later"
        (quest_catalog._check_param: f"{label}: '{value}' is created only later",
        place_item.item label "Item");
      - j4 TPL_I with s3 condition params {placement: "box"} ->
        "steps.2.condition.params.placement: Placement: 'box' is item, expected room_item"
        (quest_catalog._check_param: f"{label}: '{value}' is {actual}, expected {expected}",
        found_item.placement label "Placement", object_kinds ["room_item"]);
      - j5 TPL_I with rewards[0].permanent False ->
        "rewards.0.permanent: A reward is always permanent"
        (quest_catalog.check_effects: _issue(f"{p}.permanent", "not_allowed_here",
        "A reward is always permanent"));
      - j6 TPL_I with giver_role "glade" ->
        "giver_role: The giver role 'glade' is not a character role of this quest"
        (quest_engine.validate_template: _issue("giver_role", "unknown_role",
        f"The giver role '{giver}' is not a character role of this quest"));
      - j7 step 0 condition {type: "create_item", params: {name: "x"}} ->
        "steps.0.condition.type: 'Create an item' is an effect, not allowed here (allowed: condition)"
        (quest_catalog._check_leaf: f"'{t.label}' is {article} {t.kind}, not allowed here (allowed: {', '.join(allowed_kinds)})",
        create_item label "Create an item", kind "effect");
      - j8 setup_effects [{key: "x1", type: "summon_dragon", params: {}}] ->
        "setup_effects.0.type: Unknown effect type 'summon_dragon'"
        (quest_catalog._check_leaf: f"Unknown {allowed_kinds[0]} type '{leaf['type']}'",
        check_effects passes allowed_kinds=("effect",)).
"""
import atexit
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="smoke_wd_quests_"))
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

from app.core import quest_types  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.models import quests  # noqa: E402

quest_types.register()

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


QID = re.compile(r"quest template (qt_[0-9a-f]{12})")


def new_run(label):
    open_ = wr.open_run()
    if open_:
        wr.set_status(open_["id"], "accepted")
    return wr.create_run(label, "m", "p", "u", 80, 300000)


run = new_run("quests")


def call(tool, args, turn=1):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


def writes():
    return [e for e in wr.entries(run, include_undone=True) if e.get("kind") == "write"]


def qid_of(res):
    m = QID.search(res.line or "")
    return m.group(1) if m else ""


ROLES = [{"key": "miller", "kind": "character"}]
STEPS = [{"id": "s1", "text": "Speak with {miller}.",
          "condition": {"type": "spoke_with", "params": {"character": "miller"}}}]
BASE = {"title": "The lost mill", "summary": "The mill wheel is gone.",
        "gm_notes": "The apprentice took it.", "roles": ROLES, "steps": STEPS}
CHANGED = "was changed since — the discard leaves it alone"

# ── (a) ──────────────────────────────────────────────────────────────────
print("(a) create_quest_template")
r = call("create_quest_template", dict(BASE))
check("(a) ok", r.ok and r.wrote, r)
A = qid_of(r)
check("(a) line", r.line == f'created draft quest template {A} "The lost mill" (1 role, 1 step)',
      r.line)
row = quests.get_template(A) if A else None
check("(a) draft / admin / revision 1",
      row is not None and (row["state"], row["origin"], row["revision"]) == ("draft", "admin", 1),
      row)
check("(a) stored as sent", row is not None and all(row.get(k) == v for k, v in BASE.items()), row)
w = writes()
check("(a) one write row", len(w) == 1, w)
if w:
    check("(a) target", (w[0].get("target_kind"), w[0].get("target_id")) == ("quest_template", A),
          w[0])
    check("(a) inverse", w[0].get("inverse") == {"op": "delete_quest_template", "id": A},
          w[0].get("inverse"))

# ── (b) ──────────────────────────────────────────────────────────────────
print("(b) issues are warnings")
r = call("create_quest_template", {**BASE, "title": "Demo Dragon", "roles": [{"key": "x", "kind": "dragon"}]})
B = qid_of(r)
check("(b) ok", r.ok and r.wrote and B, r.line)
check("(b) issue named", "issues:" in r.line
      and "roles.0.kind: A role kind is one of character, location, room, item" in r.line, r.line)
check("(b) stored as draft", B and (quests.get_template(B) or {}).get("state") == "draft")

# ── (c) ──────────────────────────────────────────────────────────────────
print("(c) refusals")


def nested(k):
    """A list wrapped k times inside the roles list: depth 2 + k."""
    value = []          # the roles list itself: depth 2
    for _ in range(k):
        value = [value]
    return value


n_writes = len(writes())
n_templates = len(quests.list_templates())
for label, args, needles in (
        ("title 5", {**BASE, "title": 5}, ("title must be text",)),
        ("time limit -1", {**BASE, "time_limit_s": -1},
         ("time_limit_s is a whole number of seconds, 0 or more",)),
        ("no title", {k: v for k, v in BASE.items() if k != "title"}, ("title",)),
        ("blank title", {**BASE, "title": "  "}, ("title",)),
        ("roles not a list", {**BASE, "roles": "x"}, ("roles",)),
        ("steps not a list", {**BASE, "steps": {}}, ("steps",)),
        ("start_condition not an object", {**BASE, "start_condition": []}, ("start_condition",)),
        ("prerequisites not an object", {**BASE, "prerequisites": "x"}, ("prerequisites",)),
        ("unknown key", {**BASE, "state": "ready"}, ("state",)),
        ("too large", {**BASE, "gm_notes": "x" * 300000}, ("256 KiB",)),
        ("nested 5000 deep", {**BASE, "roles": nested(5000)}, ("nested too deeply",)),
        ("nested 65 deep", {**BASE, "roles": nested(63)}, ("nested too deeply",))):
    res = call("create_quest_template", args)
    check(f"(c) {label} refused",
          not res.ok and not res.wrote and all(n in res.line for n in needles), res.line)
res = call("create_quest_template", {**BASE, "start_condition": nested(62)})
check("(c) depth 64 not refused for depth",
      not res.ok and not res.wrote and "start_condition" in res.line
      and "nested too deeply" not in res.line, res.line)
check("(c) no new write rows", len(writes()) == n_writes, len(writes()))
check("(c) no new templates", len(quests.list_templates()) == n_templates)

# ── (d) ──────────────────────────────────────────────────────────────────
print("(d) changed since (revision)")
if A:
    quests.update_template(A, {"summary": "x"}, base_revision=1)
pv = wu.discard_preview(run)
check("(d) preview", pv == [f"quest template {A} {CHANGED}",
                            f'quest template {B} "Demo Dragon"'], pv)
u = wu.undo(run)
check("(d) not complete", not u["complete"], u)
sk = [s for s in u["skipped"] if s.get("reason") == wu.REASON_CHANGED]
check("(d) changed since, keys [revision]",
      len(sk) == 1 and sk[0].get("keys") == ["revision"], u["skipped"])
check("(d) A stays", A and quests.get_template(A) is not None)
check("(d) B gone", quests.get_template(B or "x") is None)
if A:
    quests.delete_template(A)

# ── (e) ──────────────────────────────────────────────────────────────────
print("(e) clean run, delete_created")
run = new_run("quests 2")
E1 = qid_of(call("create_quest_template", {"title": "Demo One"}))
E2 = qid_of(call("create_quest_template", {"title": "Demo Two", "steps": STEPS, "roles": ROLES}))
check("(e) both ok", E1 and E2)
E3 = qid_of(call("create_quest_template", {"title": "Demo Three"}))
r = call("delete_created", {"kind": "quest_template", "id": E3})
check("(e) same-turn delete ok", r.ok, r.line)
check("(e) E3 gone", E3 and quests.get_template(E3) is None)
E4 = qid_of(call("create_quest_template", {"title": "Demo Four"}))
r = call("delete_created", {"kind": "quest_template", "id": E4}, turn=2)
check("(e) earlier turn refused", not r.ok and "created in an earlier turn" in r.line, r.line)
check("(e) E4 stays", E4 and quests.get_template(E4) is not None)
pv = wu.discard_preview(run)
check("(e) preview", pv == [f'quest template {E1} "Demo One"', f'quest template {E2} "Demo Two"',
                            f'quest template {E4} "Demo Four"'], pv)
u = wu.undo(run)
check("(e) complete", u["complete"], u)
check("(e) no templates left", quests.list_templates() == [], quests.list_templates())

# ── (f) ──────────────────────────────────────────────────────────────────
print("(f) changed since (a run exists)")
run = new_run("quests 3")
RT = qid_of(call("create_quest_template", dict(BASE)))
check("(f) ok", RT)
if RT:
    quests.create_run(template=quests.get_template(RT), bindings={}, state="hidden")
pv = wu.discard_preview(run)
check("(f) preview", pv == [f"quest template {RT} {CHANGED}"], pv)
u = wu.undo(run)
sk = [s for s in u["skipped"] if s.get("reason") == wu.REASON_CHANGED]
check("(f) not complete, keys [runs]", not u["complete"] and len(sk) == 1
      and sk[0].get("keys") == ["runs"], u)
check("(f) R stays", RT and quests.get_template(RT) is not None)

# ── (g) ──────────────────────────────────────────────────────────────────
print("(g) catalogs")
from app.core import quest_catalog  # noqa: E402

HEADER_1 = (
    'Conditions go into steps[].condition and start_condition, prerequisite '
    'types into prerequisites.condition; an effect is an entry '
    '{"key", "type", "params", "permanent"?} of setup_effects, '
    'steps[].on_done or rewards.'
)
HEADER_2 = (
    "* = required. role[k] takes a role key of kind k. target[...] takes a "
    "role key of the listed kind or the key of an EARLIER effect that makes "
    "the listed object kind: a step condition reaches setup_effects and the "
    "on_done of earlier steps; an on_done entry also the earlier entries of "
    "its own list; a reward every effect key; a setup entry the earlier setup "
    "entries; start_condition and prerequisites setup keys only."
)
SPOKE_WITH_LINE = "spoke_with (condition) — Has spoken with: params character*:role[character]"
PLACE_ITEM_LINE = (
    "place_item (effect, makes room_item) — Place an item: params "
    "item*:target[item role or item effect key], room*:role[room], "
    "quantity:int, hidden:bool, difficulty:int, note:str"
)
GIVE_ITEM_LINE = (
    "give_item (effect, makes grant) — Give an item: params "
    "item*:target[item role or item effect key], "
    "to:role[character; empty = the avatar], quantity:int"
)

r = call("list_catalog", {"name": "quest_types"})
qt_lines = r.line.split("\n") if r.ok else []
check("(g) quest_types headers",
      r.ok and len(qt_lines) >= 2 and qt_lines[0] == HEADER_1 and qt_lines[1] == HEADER_2,
      qt_lines[:2])
check("(g) quest_types spoke_with", r.ok and SPOKE_WITH_LINE in qt_lines, r.line)
check("(g) quest_types place_item", r.ok and PLACE_ITEM_LINE in qt_lines, r.line)
check("(g) quest_types give_item", r.ok and GIVE_ITEM_LINE in qt_lines, r.line)
check("(g) quest_types not cut",
      r.ok and not any(ln.startswith("… ") for ln in qt_lines), qt_lines[-1] if qt_lines else "")
registered_ids = list(quest_catalog.types())
check("(g) quest_types complete",
      r.ok and all(sum(1 for ln in qt_lines[2:] if ln.startswith(f"{tid} ")) == 1
                   for tid in registered_ids),
      (len(registered_ids), len(qt_lines) - 2))
r = call("list_catalog", {"name": "quest_roles"})
check("(g) quest_roles", r.ok and r.line.split("\n") == ["character", "location", "room", "item"],
      r.line)

# ── (h) ──────────────────────────────────────────────────────────────────
print("(h) route + core field check")
from fastapi import HTTPException  # noqa: E402

from app.core import quest_engine  # noqa: E402
from app.routes import quests as quest_routes  # noqa: E402

try:
    quest_routes._create_template_sync({"title": "x", "summary": 5})
    detail = None
except HTTPException as e:
    detail = (e.status_code, e.detail)
check("(h) create 400 body", detail == (400, {"code": "bad_request",
                                              "message": "summary must be text"}), detail)
try:
    quest_routes._update_template_sync("qt_000000000000", {"base_revision": 1, "title": 5})
    detail = None
except HTTPException as e:
    detail = (e.status_code, e.detail)
check("(h) update 400 body", detail == (400, {"code": "bad_request",
                                              "message": "title must be text"}), detail)
check("(h) bool time limit", getattr(quest_engine, "check_template_fields", lambda b: "missing")(
    {"time_limit_s": True}) == "time_limit_s is a whole number of seconds, 0 or more")
check("(h) clean body", getattr(quest_engine, "check_template_fields", lambda b: "missing")(
    {"title": "x", "time_limit_s": 0}) is None)

# ── (i) ──────────────────────────────────────────────────────────────────
print("(i) stage-2 template through the tool")
import copy  # noqa: E402

TPL_I = {
    "title": "The big rock",
    "summary": "{giver} lost something near {wood}.",
    "gm_notes": "GM ONLY",
    "giver_role": "giver",
    "roles": [
        {"key": "giver", "kind": "character", "description": "who asks"},
        {"key": "wood", "kind": "location", "description": "the wood"},
        {"key": "glade", "kind": "room", "description": "where the box lies"},
    ],
    "setup_effects": [
        {"key": "rock", "type": "create_prop", "params": {
            "name": "Big rock", "prompt": "a large mossy boulder",
            "height_m": 2.0, "near": "wood", "offset_x": 12, "offset_z": -4}},
        {"key": "box", "type": "create_item", "params": {
            "name": "Old tin box", "category": "tool"}},
        {"key": "box_spot", "type": "place_item", "params": {
            "item": "box", "room": "glade", "hidden": True, "difficulty": 3}},
        {"key": "hint", "type": "give_hint", "params": {
            "holder": "giver", "text": "The box lies hidden in {glade}."}},
    ],
    "steps": [
        {"id": "s1", "text": "Find the big rock near {wood}.", "hint": "",
         "condition": {"type": "near_object", "params": {"object": "rock", "radius_m": 15}}},
        {"id": "s2", "text": "Find out where the box is.", "hint": "",
         "condition": {"type": "knows_secret", "params": {"secret": "hint"}},
         "on_done": [{"key": "told", "type": "narrate",
                      "params": {"text": "You remember the hollow under the roots."}}]},
        {"id": "s3", "text": "Find the tin box in {glade}.", "hint": "",
         "condition": {"type": "found_item", "params": {"placement": "box_spot"}}},
        {"id": "s4", "text": "Bring the tin box.", "hint": "",
         "condition": {"type": "holds_item", "params": {"item": "box", "count": 1}}},
    ],
    "rewards": [
        {"key": "charm", "type": "create_item", "permanent": True,
         "params": {"name": "Lucky charm", "category": "tool"}},
        {"key": "charm_given", "type": "give_item", "permanent": True,
         "params": {"item": "charm"}},
    ],
    "start_condition": {},
    "prerequisites": {},
    "time_limit_s": 0,
}

run = new_run("quests 4")
runs_before = len(quests.list_runs())
r = call("create_quest_template", copy.deepcopy(TPL_I))
check("(i) ok", r.ok and r.wrote, r)
TI = qid_of(r)
check("(i) line", r.line == f'created draft quest template {TI} "The big rock" (3 roles, 4 steps)',
      r.line)
row = quests.get_template(TI) if TI else None
check("(i) draft", row is not None and row.get("state") == "draft", row)
check("(i) stored verbatim",
      row is not None and all(row.get(k) == v for k, v in TPL_I.items()), row)
check("(i) validate clean",
      row is not None and quest_engine.validate_template(row) == [],
      quest_engine.validate_template(row) if row else None)
w = writes()
check("(i) one write row", len(w) == 1, w)
if w:
    check("(i) target", (w[0].get("target_kind"), w[0].get("target_id")) == ("quest_template", TI),
          w[0])
    check("(i) inverse", w[0].get("inverse") == {"op": "delete_quest_template", "id": TI},
          w[0].get("inverse"))
check("(i) no run created", len(quests.list_runs()) == runs_before)
u = wu.undo(run)
check("(i) undo complete", u["complete"], u)
check("(i) template gone", TI and quests.get_template(TI) is None)

# ── (j) ──────────────────────────────────────────────────────────────────
print("(j) stage-2 errors are refused")
run = new_run("quests 5")
n_writes = len(writes())
n_templates = len(quests.list_templates())

j3 = copy.deepcopy(TPL_I)
j3["setup_effects"][1], j3["setup_effects"][2] = j3["setup_effects"][2], j3["setup_effects"][1]

j4 = copy.deepcopy(TPL_I)
j4["steps"][2]["condition"]["params"] = {"placement": "box"}

j5 = copy.deepcopy(TPL_I)
j5["rewards"][0]["permanent"] = False

j6 = copy.deepcopy(TPL_I)
j6["giver_role"] = "glade"

j7 = copy.deepcopy(BASE)
j7["steps"][0]["condition"] = {"type": "create_item", "params": {"name": "x"}}

j8 = copy.deepcopy(BASE)
j8["setup_effects"] = [{"key": "x1", "type": "summon_dragon", "params": {}}]

for label, args, needle in (
        ("j1 setup_effects not a list", {**BASE, "setup_effects": "x"},
         "'setup_effects' must be a list (leave it out for none)"),
        ("j2 rewards not a list", {**BASE, "rewards": {}},
         "'rewards' must be a list"),
        ("j3 box_spot before box", j3,
         "setup_effects.1.params.item: Item: 'box' is created only later"),
        ("j4 wrong_kind placement", j4,
         "steps.2.condition.params.placement: Placement: 'box' is item, expected room_item"),
        ("j5 reward permanent false", j5,
         "rewards.0.permanent: A reward is always permanent"),
        ("j6 giver_role not character", j6,
         "giver_role: The giver role 'glade' is not a character role of this quest"),
        ("j7 effect in step condition", j7,
         "steps.0.condition.type: 'Create an item' is an effect, not allowed here (allowed: condition)"),
        ("j8 unknown effect type", j8,
         "setup_effects.0.type: Unknown effect type 'summon_dragon'")):
    res = call("create_quest_template", args)
    check(f"(j) {label}",
          not res.ok and not res.wrote and res.line.startswith("error:") and needle in res.line,
          res.line)
check("(j) no new write rows", len(writes()) == n_writes, len(writes()))
check("(j) no new templates", len(quests.list_templates()) == n_templates,
      len(quests.list_templates()))

# ── (k) ──────────────────────────────────────────────────────────────────
# Fails on d026dc0fb: validate_template does not reject a reward targeting a
# non-permanent setup effect key, so create_quest_template stores it.
print("(k) reward targeting non-permanent setup item is refused")
n_writes_k = len(writes())
n_templates_k = len(quests.list_templates())
k_tpl = {
    **BASE,
    "setup_effects": [{"key": "box", "type": "create_item", "params": {"name": "Box", "category": "tool"}}],
    "rewards": [{"key": "gift", "type": "give_item", "permanent": True, "params": {"item": "box"}}],
}
res_k = call("create_quest_template", k_tpl)
check("(k) refused with rewards.0.params.item",
      not res_k.ok and not res_k.wrote and "rewards.0.params.item" in res_k.line, res_k.line)
check("(k) no new write rows", len(writes()) == n_writes_k, len(writes()))
check("(k) no new templates", len(quests.list_templates()) == n_templates_k,
      len(quests.list_templates()))

print()
if failures:
    print(f"FAILED ({len(failures)}):")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("all checks passed")
