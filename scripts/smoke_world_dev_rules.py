#!/usr/bin/env python3
"""World Dev free mode — add_block_rule / delete_rule and the rules-layer lock
(plan docs/superpowers/plans/2026-11-25-world-dev-free-p3-world-systems.md,
Task 5).

Usage: ./.venv/bin/python scripts/smoke_world_dev_rules.py
Runs in a temp world (STORAGE_DIR / INSTANCE_DIR temp), no server.

WHAT IS CHECKED, and where every expected value comes from:

Fixture: the place Demo Tavern (id "demo_tavern", rooms Taproom
"demo_taproom" and Cellar "demo_cellar", written with
app.models.world.upsert_location, no run); characters Demo Guest (no home)
and Demo Resident, template human-roleplay, save_character_profile
create_new=True. Demo Resident's home is "demo_tavern", written where every
home writer puts it: the character CONFIG (save_character_config — the admin
route routes/characters.py and the World Dev home writes both store
config["home_location"]), never the profile. Two world rules
written by rules.add_rule BEFORE any run: "fixture_keep" (block, scope
location "demo_other", condition "day") and "fixture_other" (the same shape,
used by the lock case). The clock is frozen (set_game_factor(0.0)).
A rule id of the tool is "wdrule_" + 8 hex digits (the plan) — read at
runtime from the result line, which names it. Night is sunset..sunrise of the
default calendar, 18:00..06:00 (activity_engine time atom, its comment
"night — sunset (18:00) until sunrise (06:00)"), so 23:00 is night and 12:00
is day.

Run 1:
  (a) turn 1: add_block_rule{name "Closed at night", message "The tavern is
      closed.", location_id demo_tavern, condition "night"} -> ok, line
      'added rule <A> "Closed at night": blocks enter of "Demo Tavern"
      (demo_tavern) when night'; rules.world_rule(A) == {"id": A, "name":
      "Closed at night", "type": "block", "target": {"scope": "location",
      "location": "demo_tavern", "action": "enter"}, "condition": "night",
      "message": "The tavern is closed."} (the RulesTab shape, plan E8); one
      write journal row, target ("rule", A), inverse {"op": "delete_rule",
      "id": A}. Clock 23:00 -> check_access(Demo Guest, demo_tavern)[0] is
      False; 12:00 -> True. get_location{demo_tavern} has a line starting
      "rules:" that names A.
  (b) rooms ["Cellar"] -> ok, world_rule(B)["target"]["rooms"] ==
      ["demo_cellar"], line ends '(demo_tavern) / Cellar when night';
      rooms ["Attic"] -> refused, the line names "Taproom" and "Cellar".
  (c) refusals (each adds no write row): condition "" ; condition "flying"
      (validate_condition_expression: "Unknown condition atom: flying");
      condition "present:Nobody" (validate_condition_references: "Character
      'Nobody' does not exist"); condition "  night  " (stored as sent,
      surrounding blanks refuse: "blanks"); action "both" (only
      enter|leave); location_id "nowhere"; character "Nobody".
  (d) discard_preview(run) == ['rule <A> "Closed at night"',
      'rule <B> "Cellar at night"'] (creation order). A third rule C made in
      turn 1 and delete_created{rule, C} in turn 1 -> ok, gone; a fourth D
      made in turn 1, delete_created in turn 2 -> refused "created in an
      earlier turn" (E2, same-turn only); D stays.
  (e) lock: while the main thread holds rules.layer_lock(), a thread running
      rules.update_rule("fixture_other", {"name": "Renamed"}) is still alive
      after join(0.2); after the release it ends (join(5)) and the rename is
      stored.
  (f) undo(run) -> complete; no row with an id "wdrule_%" in the rules table;
      the raw (id, text, category, meta) row of "fixture_keep" is byte-equal
      to the one read before run 1.
Run 2 (changed since):
  (f2) add_block_rule E; rules.update_rule(E, {"message": "Closed today."})
      directly -> discard_preview == ['rule <E> was changed since — the
      discard leaves it alone']; undo -> not complete, one "changed since"
      skip with keys ["message"]; E stays with the new message. Removed by
      hand.
Run 3 (residents only — the MEASUREMENT of the plan):
  (g) The field atom "<field>!=<value>" (activity_engine
      _ATOM_PATTERNS["field"]) reads a top-level key of the PROFILE
      (_condition_profile). The home is not one: get_character_profile(Demo
      Resident) has no "home_location" key (the fixture wrote it to the
      config). So add_block_rule{…, condition "home_location!=demo_tavern"}
      is accepted (grammar and references are fine) but INEFFECTIVE as a
      residents-only rule: check_access(Demo Guest, demo_tavern)[0] is False
      ("" != "demo_tavern" -> passes -> blocked) AND
      check_access(Demo Resident, demo_tavern)[0] is False too (its profile
      reads "" as well — the resident is blocked like everyone). The
      documented outcome: the system prompt (_render_system) lists "access
      for residents only" under what cannot be built, and read_manual{systems}
      says so ("residents only" + "cannot"). undo -> complete.
Run 3b (every room named):
  (i) add_block_rule{…, rooms ["Taproom", "Cellar"]} -> ok; the line ends
      with the note "omit 'rooms' to block the whole place" (the branch
      len(rooms) == len(_real_rooms(loc)) — both real rooms named). Before
      the run the tavern gets the reserved ground room "__ground__" the way
      the location writers add it (world.ensure_ground_room, then
      upsert_location; the bare fixture upsert carries none), which
      _real_rooms skips and the rule does not name, so rules._names_every_room is False: at 23:00 (night)
      check_access(Demo Guest, demo_tavern) with no room is True (the place
      stays open), check_access(Demo Guest, demo_tavern, demo_cellar) is
      False (the named room bites). undo -> complete.
Run 4 / 5 (references, same turn and earlier-turn path):
  (h) create_location Demo Shed + create_character Demo Stranger (turn
      create_turn), then (turn rule_turn) add_block_rule on the shed and
      add_block_rule on demo_tavern with character "Demo Stranger" ->
      delete_created{location, shed} refused "still named by" + 'rule <R1>
      "Shed closed"'; delete_created{character, Demo Stranger} refused
      naming 'rule <R2> "Stranger barred"'; delete_created of both rules ->
      ok; then both deletes -> ok; undo -> complete, nothing left.
Run 6 (references inside the condition):
  (j) create_item{name "Demo Key", category "tool"} (id "item_" + 8 hex,
      read from the line) and create_character Demo Visitor in turn 1, then
      add_block_rule{…, condition "has_item:Demo Key"} (the item by NAME —
      activity_engine.condition_references yields ("item", "Demo Key"),
      inventory.resolve_item_id maps it to the id) and add_block_rule{…,
      condition "night AND NOT present:Demo Visitor"} (the character in a
      condition atom; add_block_rule checks the name exactly, the
      rules_naming match is casefolded). Then
      rules.rules_naming(item=<id>) names exactly the key rule and
      rules_naming(character="demo VISITOR") exactly the visitor rule;
      delete_created{item} refused "still named by" + 'rule <K> "Key
      needed"'; delete_created{character} refused naming 'rule <P>
      "Visitor watch"'; both rules deleted -> both deletes ok; undo ->
      complete.
"""
import atexit
import os
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="smoke_wd_rules_"))
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

from app.core import world_dev_agent as wa  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core.db import get_connection  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models import character as ch  # noqa: E402
from app.models import rules  # noqa: E402
from app.models.world import (ensure_ground_room, get_location_by_id,  # noqa: E402
                              list_locations, upsert_location)

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


set_game_factor(0.0)
TAVERN, TAPROOM, CELLAR = "demo_tavern", "demo_taproom", "demo_cellar"
GUEST, RESIDENT = "Demo Guest", "Demo Resident"
upsert_location({"id": TAVERN, "name": "Demo Tavern",
                 "rooms": [{"id": TAPROOM, "name": "Taproom"},
                           {"id": CELLAR, "name": "Cellar"}]}, sync_world=False)
upsert_location({"id": "demo_other", "name": "Demo Other", "rooms": []}, sync_world=False)
assert ch.save_character_profile(GUEST, {"character_name": GUEST,
                                         "template": "human-roleplay"}, create_new=True)
assert ch.save_character_profile(RESIDENT, {"character_name": RESIDENT,
                                            "template": "human-roleplay"}, create_new=True)
assert ch.save_character_config(RESIDENT, {**ch.get_character_config(RESIDENT),
                                           "home_location": TAVERN})
for fid in ("fixture_keep", "fixture_other"):
    rules.add_rule({"id": fid, "name": fid, "type": "block",
                    "target": {"scope": "location", "location": "demo_other",
                               "action": "enter"},
                    "condition": "day", "message": "Fixture."}, target_dir="world")


def raw_rule(rid):
    return get_connection().execute(
        "SELECT id, text, category, meta FROM rules WHERE id=?", (rid,)).fetchone()


KEEP_RAW = tuple(raw_rule("fixture_keep"))

RID = re.compile(r"rule (wdrule_[0-9a-f]{8})")


def new_run(label):
    open_ = wr.open_run()
    if open_:
        wr.set_status(open_["id"], "accepted")
    return wr.create_run(label, "m", "p", "u", 80, 300000)


run = new_run("rules")


def call(tool, args, turn=1):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


def writes():
    return [e for e in wr.entries(run, include_undone=True) if e.get("kind") == "write"]


def rid_of(res):
    m = RID.search(res.line or "")
    return m.group(1) if m else ""


def at(hour):
    set_game_time(GameTime.from_parts(1, 1, hour, 0, 0))


BASE = {"name": "Closed at night", "message": "The tavern is closed.",
        "location_id": TAVERN, "condition": "night"}

# ── (a) ──────────────────────────────────────────────────────────────────
print("(a) add_block_rule")
r = call("add_block_rule", dict(BASE))
check("(a) ok", r.ok and r.wrote, r)
A = rid_of(r)
check("(a) line", r.line == (f'added rule {A} "Closed at night": blocks enter of '
                             f'"Demo Tavern" (demo_tavern) when night'), r.line)
row = rules.world_rule(A) if hasattr(rules, "world_rule") else None
check("(a) stored shape", row == {"id": A, "name": "Closed at night", "type": "block",
                                  "target": {"scope": "location", "location": TAVERN,
                                             "action": "enter"},
                                  "condition": "night", "message": "The tavern is closed."},
      row)
w = writes()
check("(a) one write row", len(w) == 1, w)
if w:
    check("(a) target", (w[0].get("target_kind"), w[0].get("target_id")) == ("rule", A), w[0])
    check("(a) inverse", w[0].get("inverse") == {"op": "delete_rule", "id": A},
          w[0].get("inverse"))
at(23)
check("(a) 23:00 blocked", rules.check_access(GUEST, TAVERN)[0] is False)
at(12)
check("(a) 12:00 allowed", rules.check_access(GUEST, TAVERN)[0] is True)
g = call("get_location", {"id": TAVERN})
rline = next((ln for ln in (g.line or "").splitlines() if ln.startswith("rules:")), "")
check("(a) get_location rules line", A in rline, g.line)

# ── (b) ──────────────────────────────────────────────────────────────────
print("(b) rooms")
r = call("add_block_rule", {**BASE, "name": "Cellar at night", "rooms": ["Cellar"]})
B = rid_of(r)
check("(b) ok", r.ok and B, r.line)
check("(b) line", (r.line or "").endswith("(demo_tavern) / Cellar when night"), r.line)
row = rules.world_rule(B) if hasattr(rules, "world_rule") and B else None
check("(b) rooms stored as ids", (row or {}).get("target", {}).get("rooms") == [CELLAR], row)
r = call("add_block_rule", {**BASE, "name": "Attic", "rooms": ["Attic"]})
check("(b) unknown room refused", not r.ok and "Taproom" in r.line and "Cellar" in r.line,
      r.line)

# ── (c) ──────────────────────────────────────────────────────────────────
print("(c) refusals")
n_writes = len(writes())
for label, patch, needle in (
        ("empty condition", {"condition": ""}, "condition"),
        ("unknown atom", {"condition": "flying"}, "flying"),
        ("unknown reference", {"condition": "present:Nobody"}, "Nobody"),
        ("blanks around the condition", {"condition": "  night  "}, "blanks"),
        ("action both", {"action": "both"}, "enter"),
        ("unknown location", {"location_id": "nowhere"}, "nowhere"),
        ("unknown character", {"character": "Nobody"}, "Nobody")):
    res = call("add_block_rule", {**BASE, **patch})
    check(f"(c) {label} refused", not res.ok and not res.wrote and needle in res.line, res.line)
check("(c) no new write rows", len(writes()) == n_writes, len(writes()))

# ── (d) ──────────────────────────────────────────────────────────────────
print("(d) discard_preview, delete_created")
pv = wu.discard_preview(run)
check("(d) preview", pv == [f'rule {A} "Closed at night"', f'rule {B} "Cellar at night"'], pv)
r = call("add_block_rule", {**BASE, "name": "Third"})
C = rid_of(r)
r = call("delete_created", {"kind": "rule", "id": C})
check("(d) same-turn delete ok", r.ok, r.line)
check("(d) C gone", C and rules.world_rule(C) is None)
r = call("add_block_rule", {**BASE, "name": "Fourth"})
D = rid_of(r)
r = call("delete_created", {"kind": "rule", "id": D}, turn=2)
check("(d) earlier turn refused", not r.ok and "created in an earlier turn" in r.line, r.line)
check("(d) D stays", D and rules.world_rule(D) is not None)

# ── (e) ──────────────────────────────────────────────────────────────────
print("(e) layer lock")
if hasattr(rules, "layer_lock"):
    t = threading.Thread(target=rules.update_rule, args=("fixture_other", {"name": "Renamed"}))
    with rules.layer_lock():
        t.start()
        t.join(0.2)
        check("(e) writer waits for the lock", t.is_alive())
    t.join(5)
    check("(e) writer ran after the release", not t.is_alive())
    check("(e) rename stored", (rules.world_rule("fixture_other") or {}).get("name") == "Renamed")
else:
    check("(e) rules.layer_lock exists", False)

# ── (f) ──────────────────────────────────────────────────────────────────
print("(f) undo")
u = wu.undo(run)
check("(f) complete", u["complete"], u)
left = get_connection().execute("SELECT id FROM rules WHERE id LIKE 'wdrule_%'").fetchall()
check("(f) no wdrule rows", left == [], left)
check("(f) fixture_keep byte-equal", tuple(raw_rule("fixture_keep")) == KEEP_RAW,
      (raw_rule("fixture_keep"), KEEP_RAW))

# ── (f2) ─────────────────────────────────────────────────────────────────
print("(f2) changed since")
run = new_run("rules 2")
r = call("add_block_rule", {**BASE, "name": "Changed"})
E = rid_of(r)
check("(f2) ok", r.ok and E, r.line)
if E:
    rules.update_rule(E, {"message": "Closed today."})
pv = wu.discard_preview(run)
check("(f2) preview", pv == [f"rule {E} was changed since — the discard leaves it alone"], pv)
u = wu.undo(run)
check("(f2) not complete", not u["complete"], u)
sk = [s for s in u["skipped"] if s.get("reason") == wu.REASON_CHANGED]
check("(f2) changed since, keys [message]", len(sk) == 1 and sk[0].get("keys") == ["message"],
      u["skipped"])
check("(f2) E stays", E and (rules.world_rule(E) or {}).get("message") == "Closed today.")
if E:
    rules.delete_rule(E, target_dir="world")

# ── (g) ──────────────────────────────────────────────────────────────────
print("(g) residents only (measured)")
run = new_run("rules 3")
check("(g) fixture: the home is in the config",
      ch.get_character_config(RESIDENT).get("home_location") == TAVERN)
check("(g) measured: the home is no profile key",
      "home_location" not in ch.get_character_profile(RESIDENT))
r = call("add_block_rule", {**BASE, "name": "Residents only",
                            "message": "Only residents may enter.",
                            "condition": f"home_location!={TAVERN}"})
check("(g) ok", r.ok, r.line)
at(12)
check("(g) guest without a home blocked", rules.check_access(GUEST, TAVERN)[0] is False)
check("(g) the resident is blocked too (ineffective)",
      rules.check_access(RESIDENT, TAVERN)[0] is False)
m = call("read_manual", {"section": "systems"})
check("(g) manual says it cannot be built",
      m.ok and "residents only" in m.line and "cannot" in m.line, m.line[:200])
check("(g) system prompt lists it as unbuildable",
      "access for residents only" in wa._render_system())
u = wu.undo(run)
check("(g) undo complete", u["complete"], u)


# ── (i) ──────────────────────────────────────────────────────────────────
print("(i) every room named")
run = new_run("rules 3b")
# Fixture step, no run: give the tavern the reserved ground room the way the
# location writers do (world.ensure_ground_room); the bare upsert above has none.
_tavern = get_location_by_id(TAVERN)
ensure_ground_room(_tavern["rooms"])
upsert_location(_tavern, sync_world=False)
check("(i) fixture: the ground room is stored",
      any(rm.get("id") == "__ground__" for rm in (get_location_by_id(TAVERN) or {}).get("rooms", [])),
      get_location_by_id(TAVERN))
r = call("add_block_rule", {**BASE, "name": "All rooms", "rooms": ["Taproom", "Cellar"]})
check("(i) ok", r.ok and rid_of(r), r.line)
check("(i) note on the line",
      (r.line or "").endswith("omit 'rooms' to block the whole place"), r.line)
at(23)
check("(i) place without a room stays open", rules.check_access(GUEST, TAVERN)[0] is True)
check("(i) the named room is blocked",
      rules.check_access(GUEST, TAVERN, CELLAR)[0] is False)
u = wu.undo(run)
check("(i) undo complete", u["complete"], u)


# ── (h) ──────────────────────────────────────────────────────────────────
def loc_id(name):
    return next((l["id"] for l in list_locations() if l.get("name") == name), "")


def refs_case(tag, create_turn, rule_turn):
    global run
    run = new_run(f"rules {tag}")
    r = call("create_location", {"data": {"name": "Demo Shed"}, "x": 60, "z": 0},
             turn=create_turn)
    check(f"({tag}) shed", r.ok, r.line)
    shed = loc_id("Demo Shed")
    r = call("create_character", {"data": {"name": "Demo Stranger"}}, turn=create_turn)
    check(f"({tag}) stranger", r.ok, r.line)
    r = call("add_block_rule", {**BASE, "name": "Shed closed", "location_id": shed},
             turn=rule_turn)
    r1 = rid_of(r)
    check(f"({tag}) shed rule ok", r.ok and r1, r.line)
    r = call("add_block_rule", {**BASE, "name": "Stranger barred", "character": "Demo Stranger"},
             turn=rule_turn)
    r2 = rid_of(r)
    check(f"({tag}) character rule ok", r.ok and r2, r.line)
    r = call("delete_created", {"kind": "location", "id": shed}, turn=rule_turn)
    check(f"({tag}) location delete refused",
          not r.ok and "still named by" in r.line and f'rule {r1} "Shed closed"' in r.line,
          r.line)
    check(f"({tag}) shed still there", get_location_by_id(shed) is not None)
    r = call("delete_created", {"kind": "character", "id": "Demo Stranger"}, turn=rule_turn)
    check(f"({tag}) character delete refused",
          not r.ok and f'rule {r2} "Stranger barred"' in r.line, r.line)
    check(f"({tag}) stranger still there", ch.character_row_exists("Demo Stranger"))
    for rid in (r1, r2):
        r = call("delete_created", {"kind": "rule", "id": rid}, turn=rule_turn)
        check(f"({tag}) rule {rid} delete ok", r.ok, r.line)
    r = call("delete_created", {"kind": "location", "id": shed}, turn=rule_turn)
    check(f"({tag}) location delete ok", r.ok, r.line)
    r = call("delete_created", {"kind": "character", "id": "Demo Stranger"}, turn=rule_turn)
    check(f"({tag}) character delete ok", r.ok, r.line)
    u = wu.undo(run)
    check(f"({tag}) undo complete", u["complete"], u)
    check(f"({tag}) nothing left", loc_id("Demo Shed") == ""
          and not ch.character_row_exists("Demo Stranger")
          and rules.world_rule(r1 or "x") is None and rules.world_rule(r2 or "x") is None)


# ── (j) ──────────────────────────────────────────────────────────────────
print("(j) references inside the condition")
run = new_run("rules j")
r = call("create_item", {"name": "Demo Key", "category": "tool"})
m = re.search(r"item_[0-9a-f]{8}", r.line or "")
KEY = m.group(0) if m else ""
check("(j) key created", r.ok and KEY, r.line)
r = call("create_character", {"data": {"name": "Demo Visitor"}})
check("(j) visitor created", r.ok, r.line)
r = call("add_block_rule", {**BASE, "name": "Key needed", "condition": "has_item:Demo Key"})
RK = rid_of(r)
check("(j) key rule ok", r.ok and RK, r.line)
r = call("add_block_rule", {**BASE, "name": "Visitor watch",
                            "condition": "night AND NOT present:Demo Visitor"})
RP = rid_of(r)
check("(j) visitor rule ok", r.ok and RP, r.line)
check("(j) rules_naming(item)", [x.get("id") for x in rules.rules_naming(item=KEY)] == [RK],
      rules.rules_naming(item=KEY))
check("(j) rules_naming(character) via condition, casefolded",
      [x.get("id") for x in rules.rules_naming(character="demo VISITOR")] == [RP],
      rules.rules_naming(character="demo VISITOR"))
r = call("delete_created", {"kind": "item", "id": KEY})
check("(j) item delete refused",
      not r.ok and "still named by" in r.line and f'rule {RK} "Key needed"' in r.line, r.line)
r = call("delete_created", {"kind": "character", "id": "Demo Visitor"})
check("(j) character delete refused",
      not r.ok and f'rule {RP} "Visitor watch"' in r.line, r.line)
for rid in (RK, RP):
    r = call("delete_created", {"kind": "rule", "id": rid})
    check(f"(j) rule {rid} delete ok", r.ok, r.line)
r = call("delete_created", {"kind": "item", "id": KEY})
check("(j) item delete ok", r.ok, r.line)
r = call("delete_created", {"kind": "character", "id": "Demo Visitor"})
check("(j) character delete ok", r.ok, r.line)
u = wu.undo(run)
check("(j) undo complete", u["complete"], u)

if hasattr(rules, "world_rule"):
    print("(h) references, same turn")
    refs_case("h", 1, 1)
    print("(h2) references, earlier turn")
    refs_case("h2", 1, 2)
else:
    check("(h) rules.world_rule exists", False)

print()
if failures:
    print(f"FAILED ({len(failures)}):")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("all checks passed")
