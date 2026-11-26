#!/usr/bin/env python3
"""World Dev free mode — phase-3 scenario: preview = undo across every new op,
and the hold-checks of phase-1 gaps 22 and 25 (plan
docs/superpowers/plans/2026-11-25-world-dev-free-p3-world-systems.md, Task 10).

Usage: ./.venv/bin/python scripts/smoke_world_dev_world_systems.py
Runs in a temp world (STORAGE_DIR / INSTANCE_DIR / ANIMATION_CLIPS_DIR temp,
paths.init before any world-DB import), no server, no LLM. Tool calls go
through world_dev_tools.run_tool exactly as the agent loop calls them; one
run, two turns.

WHAT IS CHECKED, and where every expected value comes from:

World config: game.discovery_range_m 0 (no place becomes known by sight).
The temp instance has no package list: packages.enabled is patched to
"movement" while the skill manager loads (the smoke_world_dev_skills way),
so the skill "setlocation" (plugins/movement/plugin.yaml, default ON —
SetLocationSkill has no ALWAYS_LOAD) is loaded.

Fixture: an EMPTY world. The counted tables (locations, rooms, characters,
character_state, rules, events, quest_templates, relationships, secrets)
are read before the run; all are expected to stay as read after the full
undo (d).

(a) turn 1:
    set_build_bounds{-200, -200, 200, 200}            -> ok (read row)
    create_location Demo Forge at (0, 0), Demo Gate at (100, 0) -> ok
    create_character Demo Smith, Demo Lad, both home "Demo Forge" -> ok
    set_address Demo Lad -> Demo Smith "calls him Master"   (pair row created)
    set_address Demo Smith -> Demo Lad "calls him lad"      (same row, 2nd key)
    add_secret{Demo Lad, "He broke the anvil.", known_by [Demo Smith],
               related_location <forge>}                    -> ok
    add_block_rule{"Forge closed at night", location <forge>, condition night}
    add_event{"The forge fire roars.", location <forge>, ttl_hours 6}
    create_quest_template{title "The lost mill"}            -> ok
    turn 2:
    place_character{Demo Lad, <gate>}                       -> ok
    set_skill{Demo Lad, setlocation, false}                 -> ok
(b) discard_preview(run) == the list below, derived from
    world_dev_undo.discard_preview: the creating entries oldest first (journal
    order), then the address lines (_address_preview_lines, appended after),
    then the skill lines (none: the switch is put back, no line):
      location <forge> "Demo Forge"
      location <gate> "Demo Gate"
      character "Demo Smith" — 0 chat messages, 0 memory rows of other characters name it
      character "Demo Lad" — 0 chat messages, 0 memory rows of other characters name it
      secret <S> of "Demo Lad" (personal)       (personal = the default category
                                                 of secrets.add_secret, the tool's default)
      rule <R> "Forge closed at night"
      event <E> "The forge fire roars."
      quest template <Q> "The lost mill"
      form of address Demo Lad|Demo Smith (created by the run)
    NO occupant line: Demo Lad stands in the created gate, but the discard
    deletes him itself (deleted_names). The plan's hand list named the
    created rows only; the pair row the first set_address created IS
    removed by the undo (restore_address, row_created) — so the preview
    names it (preview = undo), one line for both directions (the newer
    step only clears its key in the simulation). The relationship pair key
    is relationship.pair_key (sorted names joined by "|").
    The ids <forge>, <gate>, <S>, <R>, <E>, <Q> are read from the journal's
    write rows (the inverse's id) — the one runtime source.
(c) undo(run, turn=2) -> complete; Demo Lad's read_placement equals the read
    taken after turn 1 (his home placement), and his skill file
    characters/Demo Lad/skills/setlocation.json holds the bytes it held
    before set_skill. Deviation from the plan's "skill file absent": a NEW
    character is seeded by character_ops.seed_default_skills, which writes
    {"enabled": true} for every default skill (setlocation is one), so the
    file exists after create_character — (a) checks it parses as
    {"enabled": true}; the undo puts those exact bytes back.
(d) undo(run) -> complete; each counted table has the row count read
    before the run (all 0 here — an empty world), and the run's ids are gone.
    The bounds set in (a) are run metadata (world_dev_runs.set_bounds:
    "the undo and the discard never touch it"): after (a) the run row's
    bounds equal the box sent, as floats; after (d) they are unchanged.
    After (d) discard_preview(run) is [] (every write row undone).
(h) the preview = ONE undo claim: (c)+(d) undo in two steps, so a second
    run (run 1 closed as "rolled_back" first — one open run at a time)
    repeats (a) in the then-empty world, checks discard_preview against the
    same hand list (b) with its own ids, and calls undo(run) ONCE while
    Demo Lad still stands in the created gate with movement off -> complete,
    counts as in the empty fixture, characters and locations gone,
    discard_preview [] afterwards, bounds kept as run state. Exactness by
    CONTENTS, not counts alone: the sorted rows of every world.db table outside
    the journal (world_dev_*, sqlite_*) and the bytes of every storage file
    (outside world.db* and the run's safety backup under
    .cache/world_dev_backups/, which is run state) are snapshotted right after
    run 2 is opened and must be identical after the one undo — an inverse that
    restores the right row count with wrong contents (say a pair row left with
    a stale address key) fails here.
(e) hold-check gap 22 (turn 2, before the undo): update_character{Demo Smith,
    {animation_set: "dancer"}} -> refused, the line lists
    '"", "animal", "female", "male"' (animation_sets.BASE_SETS sorted, the
    clips dir is empty; "" first) — the assertion of
    smoke_world_dev_select_sources (a).
(f) hold-check gap 25: update_character{Demo Smith, {outfits: [{name Work,
    pieces [{name Demo Gloves, slots ["nope"]}]}]}} -> refused, the line says
    "'slots' must name at least one of" followed by the slots of
    body_slots.piece_slots_for_character("Demo Smith") joined by ", "
    (RUNTIME source: no species package in the temp world, so that is
    inventory.VALID_PIECE_SLOTS — checked equal too).
    (e) and (f) leave refused rows only (no write row added).
(g) frontend: git grep -n -e world_prop -e terrain_type -e target_kind
    frontend/src/tabs/world-dev -> no output (no per-kind label map that
    would need the new kinds).
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
REPO = Path(__file__).resolve().parents[1]

ROOT = Path(tempfile.mkdtemp(prefix="smoke_wd_world_systems_"))
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
from app.core.body_slots import piece_slots_for_character  # noqa: E402
from app.core.db import get_connection  # noqa: E402
from app.core.dependencies import get_skill_manager  # noqa: E402
from app.models import character as ch  # noqa: E402
from app.models.inventory import VALID_PIECE_SLOTS  # noqa: E402
from app.models.relationship import pair_key  # noqa: E402
from app.models.world import list_locations  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


_real_get = config.get
with patch("app.core.config.get", side_effect=lambda key, default=None:
           "movement" if key == "packages.enabled" else _real_get(key, default)):
    loaded = {s.SKILL_ID for s in get_skill_manager().skills if s.SKILL_ID}
SKILL = "setlocation"
check("fixture: setlocation is loaded", SKILL in loaded, sorted(loaded))

TABLES = ("locations", "rooms", "characters", "character_state", "rules", "events",
          "quest_templates", "relationships", "secrets")


def counts():
    conn = get_connection()
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}


def contents():
    """Sorted row contents of every world table outside the run journal
    (world_dev_*) and SQLite's own sqlite_* tables."""
    conn = get_connection()
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    return {t: sorted(repr(tuple(row)) for row in conn.execute(f'SELECT * FROM "{t}"'))
            for t in names if not t.startswith(("world_dev_", "sqlite_"))}


BACKUPS = STORAGE / ".cache" / "world_dev_backups"


def file_tree():
    """Every storage file with its bytes, outside the world DB (and its WAL/SHM)
    and the per-run safety backups (world_dev_backup: run state, like the bounds)."""
    return {str(p.relative_to(STORAGE)): p.read_bytes() for p in sorted(STORAGE.rglob("*"))
            if p.is_file() and not p.name.startswith("world.db")
            and BACKUPS not in p.parents}


def diff_tables(a, b):
    return {t: (len(a.get(t, [])), len(b.get(t, []))) for t in set(a) | set(b)
            if a.get(t) != b.get(t)}


COUNTS0 = counts()
check("fixture: an empty world", all(v == 0 for v in COUNTS0.values()), COUNTS0)

SMITH, LAD = "Demo Smith", "Demo Lad"
run = wr.create_run("world systems", "m", "p", "u", 200, 300000)


def call(tool, args, turn=1):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


def writes():
    return [e for e in wr.entries(run, include_undone=True) if e.get("kind") == "write"]


def loc_id(name):
    return next((l["id"] for l in list_locations() if l.get("name") == name), "")


def inverse_ids(op):
    """The ids the run's write rows of one creating op name, oldest first."""
    rows = sorted(writes(), key=lambda e: e.get("seq") or 0)
    return [str((e.get("inverse") or {}).get("id") or "") for e in rows
            if (e.get("inverse") or {}).get("op") == op]


def preview_list(forge, gate, s, r_, e, q):
    """The hand list of docstring (b) for one run's ids."""
    return [
        f'location {forge} "Demo Forge"',
        f'location {gate} "Demo Gate"',
        f'character "{SMITH}" — 0 chat messages, 0 memory rows of other characters name it',
        f'character "{LAD}" — 0 chat messages, 0 memory rows of other characters name it',
        f'secret {s} of "{LAD}" (personal)',
        f'rule {r_} "Forge closed at night"',
        f'event {e} "The forge fire roars."',
        f'quest template {q} "The lost mill"',
        f"form of address {pair_key(LAD, SMITH)} (created by the run)",
    ]


def run_ids():
    """<S>, <R>, <E>, <Q> of the current run, read from its write rows."""
    ids = [inverse_ids(op) for op in ("delete_secret", "delete_rule", "delete_event",
                                      "delete_quest_template")]
    return ids, [x[0] if x else "?" for x in ids]


BOX = {"min_x": -200.0, "min_z": -200.0, "max_x": 200.0, "max_z": 200.0}


def build(tag):
    """Turns 1 and 2 of the scenario in the current `run` (docstring (a))."""
    print(f"{tag} turn 1")
    r = call("set_build_bounds", dict(BOX))
    check(f"{tag} bounds", r.ok and not r.wrote, r.line)
    check(f"{tag} bounds stored on the run row", wr.get_run(run)["bounds"] == BOX,
          wr.get_run(run)["bounds"])
    r = call("create_location", {"data": {"name": "Demo Forge"}, "x": 0, "z": 0})
    check(f"{tag} forge", r.ok and r.wrote, r.line)
    r = call("create_location", {"data": {"name": "Demo Gate"}, "x": 100, "z": 0})
    check(f"{tag} gate", r.ok and r.wrote, r.line)
    FORGE, GATE = loc_id("Demo Forge"), loc_id("Demo Gate")
    check(f"{tag} both ids", bool(FORGE and GATE), (FORGE, GATE))
    for nm in (SMITH, LAD):
        r = call("create_character", {"data": {"name": nm}, "home": "Demo Forge"})
        check(f"{tag} {nm} created", r.ok and r.wrote, r.line)
    r = call("set_address", {"speaker": LAD, "addressee": SMITH, "text": "calls him Master"})
    check(f"{tag} address lad -> smith", r.ok and r.wrote, r.line)
    r = call("set_address", {"speaker": SMITH, "addressee": LAD, "text": "calls him lad"})
    check(f"{tag} address smith -> lad", r.ok and r.wrote, r.line)
    r = call("add_secret", {"name": LAD, "content": "He broke the anvil.",
                            "known_by": [SMITH], "related_location": FORGE})
    check(f"{tag} secret", r.ok and r.wrote, r.line)
    r = call("add_block_rule", {"name": "Forge closed at night", "message": "The forge is closed.",
                                "location_id": FORGE, "condition": "night"})
    check(f"{tag} rule", r.ok and r.wrote, r.line)
    r = call("add_event", {"text": "The forge fire roars.", "location_id": FORGE, "ttl_hours": 6})
    check(f"{tag} event", r.ok and r.wrote, r.line)
    r = call("create_quest_template", {"title": "The lost mill"})
    check(f"{tag} quest template", r.ok and r.wrote, r.line)
    LAD_HOME = ch.read_placement(LAD)
    check(f"{tag} Demo Lad stands at the forge",
          LAD_HOME["profile"].get("current_location") == FORGE, LAD_HOME)
    skill_file = ch.get_character_dir(LAD) / "skills" / f"{SKILL}.json"
    SKILL_BYTES = skill_file.read_bytes() if skill_file.is_file() else None
    check(f"{tag} seeded skill file", SKILL_BYTES is not None
          and json.loads(SKILL_BYTES) == {"enabled": True}, SKILL_BYTES)

    print(f"{tag} turn 2")
    r = call("place_character", {"name": LAD, "location_id": GATE}, turn=2)
    check(f"{tag} Demo Lad placed at the gate", r.ok and r.wrote, r.line)
    r = call("set_skill", {"name": LAD, "skill": SKILL, "enabled": False}, turn=2)
    check(f"{tag} movement off", r.ok and r.wrote, r.line)
    check(f"{tag} skill file written", skill_file.is_file())
    return FORGE, GATE, LAD_HOME, skill_file, SKILL_BYTES


# ── (a) turn 1 ───────────────────────────────────────────────────────────
FORGE, GATE, LAD_HOME, skill_file, SKILL_BYTES = build("(a)")

# ── (e) / (f) hold-checks (turn 2, refused only) ─────────────────────────
print("(e)/(f) hold-checks of gaps 22 and 25")
n_writes = len(writes())
r = call("update_character", {"name": SMITH, "patch": {"animation_set": "dancer"}}, turn=2)
check("(e) source-backed select refused with the source values",
      not r.ok and not r.wrote and '"", "animal", "female", "male"' in r.line, r.line)
slots = tuple(piece_slots_for_character(SMITH))
check("(f) slot source is the core default", slots == tuple(VALID_PIECE_SLOTS), slots)
r = call("update_character", {"name": SMITH, "patch": {"outfits": [
    {"name": "Work", "pieces": [{"name": "Demo Gloves", "slots": ["nope"],
                                 "prompt_fragment": "gloves"}]}]}}, turn=2)
check("(f) unknown slot refused naming the slot list",
      not r.ok and not r.wrote
      and ("'slots' must name at least one of " + ", ".join(slots)) in r.line, r.line)
check("(e)/(f) no write row added", len(writes()) == n_writes, len(writes()))

# ── (b) ──────────────────────────────────────────────────────────────────
print("(b) discard_preview")
ID_LISTS, (S, R_, E, Q) = run_ids()
check("(b) one id each", [len(x) for x in ID_LISTS] == [1, 1, 1, 1], ID_LISTS)
expected = preview_list(FORGE, GATE, S, R_, E, Q)
check("(b) pair key", pair_key(LAD, SMITH) == "Demo Lad|Demo Smith", pair_key(LAD, SMITH))
pv = wu.discard_preview(run)
check("(b) preview == hand list", pv == expected, pv)
check("(b) no occupant line", not any("stands in" in ln for ln in pv), pv)

# ── (c) ──────────────────────────────────────────────────────────────────
print("(c) undo turn 2")
u = wu.undo(run, turn=2)
check("(c) complete", u["complete"], u)
check("(c) Demo Lad back at his home placement",
      wu._norm(ch.read_placement(LAD)) == wu._norm(LAD_HOME), ch.read_placement(LAD))
check("(c) skill file bytes as seeded",
      skill_file.is_file() and skill_file.read_bytes() == SKILL_BYTES,
      skill_file.read_bytes() if skill_file.is_file() else None)

# ── (d) ──────────────────────────────────────────────────────────────────
print("(d) undo the run")
u = wu.undo(run)
check("(d) complete", u["complete"], u)
check("(d) counts as in the empty fixture", counts() == COUNTS0, counts())
check("(d) characters gone",
      not ch.character_row_exists(SMITH) and not ch.character_row_exists(LAD))
check("(d) locations gone", loc_id("Demo Forge") == "" and loc_id("Demo Gate") == "")
check("(d) the build bounds survive the undo as run state",
      wr.get_run(run)["bounds"] == BOX, wr.get_run(run)["bounds"])
check("(d) nothing left to discard", wu.discard_preview(run) == [], wu.discard_preview(run))

# ── (h) ──────────────────────────────────────────────────────────────────
print("(h) second run: preview, then ONE full undo")
wr.set_status(run, "rolled_back")   # close run 1: one open run at a time
run = wr.create_run("world systems 2", "m", "p", "u", 200, 300000)
CONTENTS_H0, FILES_H0 = contents(), file_tree()
FORGE2, GATE2, _home2, _file2, _bytes2 = build("(h)")
check("(h) fresh ids", FORGE2 not in (FORGE, GATE) and GATE2 not in (FORGE, GATE),
      (FORGE2, GATE2))
ID_LISTS2, ids2 = run_ids()
check("(h) one id each", [len(x) for x in ID_LISTS2] == [1, 1, 1, 1], ID_LISTS2)
pv2 = wu.discard_preview(run)
check("(h) preview == hand list", pv2 == preview_list(FORGE2, GATE2, *ids2), pv2)
u = wu.undo(run)
check("(h) complete", u["complete"], u)
check("(h) counts as in the empty fixture", counts() == COUNTS0, counts())
CONTENTS_H1, FILES_H1 = contents(), file_tree()
check("(h) every non-journal table holds the rows it held before run 2",
      CONTENTS_H1 == CONTENTS_H0, diff_tables(CONTENTS_H0, CONTENTS_H1))
check("(h) the storage file tree is as before run 2", FILES_H1 == FILES_H0,
      sorted(set(FILES_H0) ^ set(FILES_H1))
      or [k for k in FILES_H0 if FILES_H0[k] != FILES_H1.get(k)])
check("(h) characters gone",
      not ch.character_row_exists(SMITH) and not ch.character_row_exists(LAD))
check("(h) locations gone", loc_id("Demo Forge") == "" and loc_id("Demo Gate") == "")
check("(h) nothing left to discard", wu.discard_preview(run) == [], wu.discard_preview(run))
check("(h) the build bounds survive the undo as run state",
      wr.get_run(run)["bounds"] == BOX, wr.get_run(run)["bounds"])

# ── (g) ──────────────────────────────────────────────────────────────────
print("(g) frontend has no per-kind label map")
g = subprocess.run(["git", "grep", "-n", "-e", "world_prop", "-e", "terrain_type",
                    "-e", "target_kind", "--", "frontend/src/tabs/world-dev"],
                   cwd=REPO, capture_output=True, text=True)
check("(g) git grep finds nothing", g.returncode == 1 and g.stdout == "",
      (g.returncode, g.stdout))

print()
if failures:
    print(f"FAILED ({len(failures)}):")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("all checks passed")
