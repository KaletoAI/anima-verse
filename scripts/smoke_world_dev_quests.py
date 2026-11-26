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
  (g) list_catalog{quest_types} has the line 'spoke_with (condition) — Has
      spoken with: params character:role'; list_catalog{quest_roles} lines
      == ['character', 'location', 'room', 'item'] (ROLE_KINDS).
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
r = call("list_catalog", {"name": "quest_types"})
check("(g) quest_types", r.ok and "spoke_with (condition) — Has spoken with: params character:role"
      in r.line.split("\n"), r.line)
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

print()
if failures:
    print(f"FAILED ({len(failures)}):")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("all checks passed")
