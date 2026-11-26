#!/usr/bin/env python3
"""Smoke: World Dev free mode — location field values refused, entry_room
resolved (gap 17, review finding 5).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p1-characters.md, Task 8.
A temp world (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM. Tool calls go through
``world_dev_tools.run_tool`` exactly as the agent loop calls them.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_location_values.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Allowed values (by hand from the code that reads them):
  danger_level 0..5 whole numbers (models.world.add_location clamps to 0-5);
  decency "", public, private, nude_ok (world_ops keeps exactly these three,
  "" = inherit/public); door styles = the stems of shared/door_styles/*.json
  (castle, glass, glazed, interior, panel, plank — door_styles.load_door_styles);
  window styles = the stems of shared/window_styles/*.json (metal, plain, stone,
  timber); terrain kinds = terrain_types.effective_catalog() of the temp world
  (a runtime read: the shared catalog, the temp world adds no rows) — "lava"
  is asserted NOT to be one of them before it is used as the bad value.
  outfit_type: no reader outside the location writers/loaders (D10) — an
  unknown key now.

Fixture, turn 1: create_location{data: {name "Demo Inn", rooms [Hall,
  Kitchen], entry_room "Kitchen"}} -> ok; stored entry_room == the id the
  writer gave the Kitchen room (read back by name). Before this task the name
  went to valid_entry_room unresolved and "" was stored.
Turn 2, refusals — each: not ok, nothing written, journal kind "refused", the
  stored Inn record equal to the record before the call (dict equality):
  (a) update danger_level 7 -> "'danger_level' must be one of: 0, 1, 2, 3,
      4, 5"; danger_level 2.5 -> "whole number"; create with danger_level 7
      -> refused, no place "Demo Bad".
  (b) update decency "secret" -> line lists '"", public, private, nude_ok';
      the same in a room (rooms[0] = Hall with its id) -> the line starts with
      "rooms[0]:" and lists the four values.
  (c) default_door_style "nope" -> lists "castle, glass, glazed, interior,
      panel, plank"; default_window_style "nope" -> lists "metal, plain,
      stone, timber".
  (d) terrain "lava" -> the line lists every effective catalog kind.
  (e) outfit_type "casual" -> "unknown patch key(s) outfit_type".
  (f) update entry_room "Attic" -> "'entry_room' must name a room of this
      place: Hall, Kitchen ("" = arrive on the ground)" (the ground room is
      not offered: "" already means "arrive on the ground").
  (i) indoor "yes" -> "'indoor' must be one of: \"\", indoor, outdoor" (the
      readers know only those, models.world.resolve_indoor_flag; the writer
      blanked anything else); the same in a room -> "rooms[0]:".
  (k) rooms [Hall (id)] alone — the patch drops Kitchen, the current entry
      room, without sending entry_room -> "removes the entry room "Kitchen"".
  (m) danger_level 10**400 (a JSON integer float() cannot hold) -> "'danger_level'
      must be a number" — a refusal, not an OverflowError out of run_tool.
Turn 3, accepted values: update {danger_level 3, decency "private", indoor "outdoor",
  default_door_style "plank", default_window_style "stone", terrain <first
  catalog kind>, entry_room "Hall"} -> ok; stored exactly those, entry_room ==
  Hall's id (an EXISTING room resolved before the write). undo(run, 3) ->
  complete; record equal to the record before turn 3.
Turn 4, finding 5: update {rooms: [Hall (id), Kitchen (id), {name "Attic"}],
  entry_room "Attic"} -> ok; stored entry_room == the new Attic room's id;
  undo(run, 4) -> complete, the room names (reserved "__" rooms left out) are
  [Hall, Kitchen] again and entry_room == Kitchen's id; record equal to the one
  before turn 4.
Turn 5, a new room name with surrounding whitespace: rooms [Hall, Kitchen,
  {name " Attic "}], entry_room "Attic" -> ok; entry_room == the id of the new
  room whose stripped name is "Attic"; undo(run, 5) -> complete, record equal
  to the one before turn 5.
Turn 6, the ground-floor corridor: fixture "Demo Tower" written OUTSIDE the
  run by world_ops.create_location_with_extras with one layout room "Lobby"
  (layout {level 0, x 0, y 0, w 6, d 6} — world_ops._sanitize_room_layout keeps a
  layout only with x/y/w/d) — the tools cannot give a room a layout. No corridor yet
  (models.world.floor_levels drops level 0 unless map3d.ground_corridor).
  update {map3d {ground_corridor true}, entry_room "__floor__0"} -> ok; the
  room ids now include "__floor__0" and entry_room == "__floor__0" (an id
  resolved before the write: the writer syncs the corridor in the map3d block
  and validates entry_room after it). undo(run, 6) -> complete, record equal
  to the one before turn 6 (no corridor, entry_room as before).
Turn 7/8, the corridor as entry room taken away by map3d: turn 7 repeats turn 6
  (ground_corridor true, entry_room "__floor__0") and keeps it. Turn 8:
  map3d {ground_corridor false} alone -> refused, "removes the entry room" and
  "(__floor__0)" in the line (models.world.floor_levels drops level 0 without
  the opt-in, so the sync removes the corridor), record unchanged. The same
  patch with entry_room "" -> ok, no "__floor__0" room, entry_room ""; undo(run,
  8) -> complete, record equal to the one before turn 8 (corridor + entry back).
Turns 9/10, dropping the entry room WITH entry_room: rooms [Hall (id)] +
  entry_room "" -> ok, room names [Hall], entry_room ""; undo -> record as
  before. rooms [Hall (id)] + entry_room "Hall" -> ok, entry_room == Hall's id;
  undo -> record as before (Kitchen and its entry back).
Turns 11/12, the by-name entry write fails AFTER the main write
  (wt._write_entry_room_by_name monkeypatched to raise RuntimeError "boom"):
  update rooms [Hall, Kitchen, {name "Attic"}] + entry_room "Attic" -> run_tool
  re-raises the RuntimeError (a failure, not a refusal: run_tool raises it on),
  the newest journal row is a "write" (step.writing reconciles: the rooms were
  stored), Attic is stored; undo(run, 11) -> complete, record as before turn 11.
  create_location {name "Demo Fail", rooms [Cellar], entry_room "Cellar"} -> the
  RuntimeError again, the newest row is a "write" whose inverse deletes the new place, the place
  exists; undo(run, 12) -> complete, no place "Demo Fail".
Turn 2 (q), one rate per stat (F8d; world_ops._sanitize_stat_rates keeps a
  second entry of the same stat, and the hourly tick would apply both — one
  entry per stat is the editor's meaning): the character templates are read
  from a temp directory with ONE template whose one field has store
  "status_effects" (stat_hints.get_all_stat_keys collects exactly those), so
  S = wt._stat_keys()[0] — the stat key is read, never named here.
  update stat_rates [{S, 2}, {S, -1}] -> refused "'stat_rates[1].stat' 'S' is
  already rated in stat_rates[0] — one entry per stat", record unchanged; the
  same in a room (rooms [Hall (id) with those rates, Kitchen (id)]) -> "'rooms[0]
  .stat_rates[1].stat' 'S' is already rated in rooms[0].stat_rates[0]"
  (_check_room_extras names a room "rooms[<i>]"). Before the fixture, a FRESH
  run (closed again: one open run at a time) whose first call is
  create_location "Demo Spa" with the doubled place rates, then a second one
  with the doubled room rates -> both refused, the location count is unchanged
  and the run has no backup_path (the check runs before the safety backup,
  which is taken lazily before the first write).
End: discard_preview(run) names "Demo Inn" in exactly one line (the only
  element the run created, the Tower is no element of the run); undo(run) ->
  complete and no place "Demo Inn" — preview and undo agree.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_lv_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_lv_"))
paths.init(STORAGE)
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)

from app.core import config, db  # noqa: E402

config.load(paths.get_config_path())
db.init_schema()

import json  # noqa: E402

from app.models import character_template  # noqa: E402

TEMPLATES = Path(tempfile.mkdtemp(prefix="smoke_wd_lv_tpl_"))
atexit.register(shutil.rmtree, TEMPLATES, ignore_errors=True)
(TEMPLATES / "demo-stats.json").write_text(json.dumps({
    "name": "demo-stats", "template_type": "character",
    "sections": [{"id": "stats", "fields": [
        {"key": "demo_stat", "label": "Demo stat", "type": "number",
         "store": "status_effects"}]}]}), encoding="utf-8")
character_template.get_templates_dir = lambda: TEMPLATES  # type: ignore[assignment]
character_template.clear_template_cache()

from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core.terrain_types import effective_catalog  # noqa: E402
from app.models.world import get_location_by_id, list_locations  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


# ── (q) a fresh run: the doubled stat is refused before the first write ──
STATS = wt._stat_keys()
check("(q) fixture: the temp world has a stat key", bool(STATS), STATS)
S = STATS[0] if STATS else "?"
TWICE = [{"stat": S, "per_hour": 2}, {"stat": S, "per_hour": -1}]
run_q = wr.create_run("stat twice", "m", "p", "u", 40, 300000)
n_locs = len(list_locations())
for tag, data in (("place", {"name": "Demo Spa", "stat_rates": TWICE,
                             "rooms": [{"name": "Hall"}]}),
                  ("room", {"name": "Demo Spa",
                            "rooms": [{"name": "Hall", "stat_rates": TWICE}]})):
    res = wt.run_tool(wt.ToolCtx(run_id=run_q, turn=1), "create_location", {"data": data})
    check(f"(q) create, {tag} stat twice: refused", not res.ok and not res.wrote, res)
    check(f"(q) create, {tag} stat twice: line", "is already rated in" in res.line
          and "one entry per stat" in res.line, res.line)
check("(q) create: location count unchanged", len(list_locations()) == n_locs,
      (n_locs, len(list_locations())))
check("(q) create: no backup taken", not (wr.get_run(run_q) or {}).get("backup_path"),
      (wr.get_run(run_q) or {}).get("backup_path"))
wr.set_status(run_q, "rolled_back")  # one open run at a time

run = wr.create_run("location values", "m", "p", "u", 40, 300000)


def call(turn, tool, args):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


def newest():
    return wr.steps(run)[-1]


def room_id(loc, name):
    return next((str(r.get("id")) for r in loc.get("rooms") or []
                 if r.get("name") == name), "")


def room_names(loc):
    return [r.get("name") for r in loc.get("rooms") or []
            if not str(r.get("id") or "").startswith("__")]


# ── Fixture (turn 1) ─────────────────────────────────────────────────────
res = call(1, "create_location", {"data": {
    "name": "Demo Inn", "rooms": [{"name": "Hall"}, {"name": "Kitchen"}],
    "entry_room": "Kitchen"}})
check("fixture create ok", res.ok and res.wrote, res)
INN = next((l["id"] for l in list_locations() if l.get("name") == "Demo Inn"), "")
inn = get_location_by_id(INN) or {}
HALL, KITCHEN = room_id(inn, "Hall"), room_id(inn, "Kitchen")
check("fixture rooms Hall, Kitchen", room_names(inn) == ["Hall", "Kitchen"],
      room_names(inn))
check("create: entry_room 'Kitchen' stored as Kitchen's id",
      bool(KITCHEN) and inn.get("entry_room") == KITCHEN, inn.get("entry_room"))

KINDS = sorted(effective_catalog())
check("fixture terrain catalog not empty", bool(KINDS), KINDS)
check("fixture 'lava' is no catalog kind", "lava" not in KINDS, KINDS)


def refused(label, args, *needles, tool="update_location"):
    before = get_location_by_id(INN)
    n_before = len(wr.steps(run))
    res = call(2, tool, args)
    check(f"{label}: refused", not res.ok and not res.wrote, res)
    for nd in needles:
        check(f"{label}: line has {nd!r}", nd in res.line, res.line)
    check(f"{label}: journal kind refused",
          len(wr.steps(run)) == n_before + 1 and newest()["kind"] == "refused",
          newest())
    check(f"{label}: record unchanged", get_location_by_id(INN) == before)


refused("(a) danger 7", {"id": INN, "patch": {"danger_level": 7}},
        "'danger_level' must be one of: 0, 1, 2, 3, 4, 5")
refused("(a) danger 2.5", {"id": INN, "patch": {"danger_level": 2.5}}, "whole number")
refused("(a) create danger 7", {"data": {"name": "Demo Bad", "danger_level": 7,
                                         "rooms": [{"name": "Hall"}]}},
        "'danger_level' must be one of", tool="create_location")
check("(a) no place Demo Bad",
      not any(l.get("name") == "Demo Bad" for l in list_locations()))
DEC = '"", public, private, nude_ok'
refused("(b) decency", {"id": INN, "patch": {"decency": "secret"}},
        "'decency' must be one of", DEC)
refused("(b) room decency", {"id": INN, "patch": {"rooms": [
    {"id": HALL, "decency": "secret"}, {"id": KITCHEN}]}}, "rooms[0]:", DEC)
refused("(c) door style", {"id": INN, "patch": {"default_door_style": "nope"}},
        "'default_door_style' must be one of",
        "castle, glass, glazed, interior, panel, plank")
refused("(c) window style", {"id": INN, "patch": {"default_window_style": "nope"}},
        "'default_window_style' must be one of", "metal, plain, stone, timber")
refused("(d) terrain", {"id": INN, "patch": {"terrain": "lava"}},
        "'terrain' must be one of", ", ".join(KINDS))
refused("(e) outfit_type", {"id": INN, "patch": {"outfit_type": "casual"}},
        "unknown patch key(s) outfit_type")
refused("(f) entry_room Attic", {"id": INN, "patch": {"entry_room": "Attic"}},
        "'entry_room' must name a room of this place: Hall, Kitchen",
        '("" = arrive on the ground)')
IND = '"", indoor, outdoor'
refused("(i) indoor", {"id": INN, "patch": {"indoor": "yes"}},
        "'indoor' must be one of", IND)
refused("(i) room indoor", {"id": INN, "patch": {"rooms": [
    {"id": HALL, "indoor": "yes"}, {"id": KITCHEN}]}}, "rooms[0]:", IND)
refused("(k) drop the entry room", {"id": INN, "patch": {"rooms": [{"id": HALL}]}},
        'removes the entry room "Kitchen"', "send entry_room too")
refused("(m) danger 10**400", {"id": INN, "patch": {"danger_level": 10 ** 400}},
        "'danger_level' must be a number")

# ── Turn 2 (q): one rate per stat ───────────────────────────────────────
refused("(q) place stat twice", {"id": INN, "patch": {"stat_rates": TWICE}},
        f"'stat_rates[1].stat' {S!r} is already rated in stat_rates[0] — one entry per stat")
refused("(q) room stat twice", {"id": INN, "patch": {"rooms": [
    {"id": HALL, "stat_rates": TWICE}, {"id": KITCHEN}]}},
        f"'rooms[0].stat_rates[1].stat' {S!r} is already rated in "
        "rooms[0].stat_rates[0] — one entry per stat")

# ── Turn 3: accepted values ──────────────────────────────────────────────
before3 = get_location_by_id(INN)
res = call(3, "update_location", {"id": INN, "patch": {
    "danger_level": 3, "decency": "private", "default_door_style": "plank",
    "default_window_style": "stone", "terrain": KINDS[0], "entry_room": "Hall",
    "indoor": "outdoor"}})
check("(g) accepted update ok", res.ok and res.wrote, res)
inn = get_location_by_id(INN) or {}
got = {k: inn.get(k) for k in ("danger_level", "decency", "default_door_style",
                               "default_window_style", "terrain", "entry_room",
                               "indoor")}
want = {"danger_level": 3, "decency": "private", "default_door_style": "plank",
        "default_window_style": "stone", "terrain": KINDS[0], "entry_room": HALL,
        "indoor": "outdoor"}
check("(g) stored values", got == want, got)
rep = wu.undo(run, turn=3)
check("(g) undo complete", rep["complete"], rep)
check("(g) record as before turn 3", get_location_by_id(INN) == before3,
      wu.diff_keys(before3, get_location_by_id(INN)))

# ── Turn 4: a room added in the same update is the entry room ────────────
before4 = get_location_by_id(INN)
res = call(4, "update_location", {"id": INN, "patch": {
    "rooms": [{"id": HALL}, {"id": KITCHEN}, {"name": "Attic"}],
    "entry_room": "Attic"}})
check("(h) add Attic + entry_room Attic ok", res.ok and res.wrote, res)
inn = get_location_by_id(INN) or {}
ATTIC = room_id(inn, "Attic")
check("(h) rooms Hall, Kitchen, Attic", room_names(inn) == ["Hall", "Kitchen", "Attic"],
      room_names(inn))
check("(h) entry_room == Attic's id", bool(ATTIC) and inn.get("entry_room") == ATTIC,
      (inn.get("entry_room"), ATTIC))
rep = wu.undo(run, turn=4)
check("(h) undo complete", rep["complete"], rep)
inn = get_location_by_id(INN) or {}
check("(h) rooms Hall, Kitchen again", room_names(inn) == ["Hall", "Kitchen"],
      room_names(inn))
check("(h) entry_room Kitchen's id again", inn.get("entry_room") == KITCHEN,
      inn.get("entry_room"))
check("(h) record as before turn 4", inn == before4, wu.diff_keys(before4, inn))

# ── Turn 5: a new room name with surrounding whitespace ──────────────────
before5 = get_location_by_id(INN)
res = call(5, "update_location", {"id": INN, "patch": {
    "rooms": [{"id": HALL}, {"id": KITCHEN}, {"name": " Attic "}],
    "entry_room": "Attic"}})
check("(j) add ' Attic ' + entry_room Attic ok", res.ok and res.wrote, res)
inn = get_location_by_id(INN) or {}
ATTIC5 = next((str(r.get("id")) for r in inn.get("rooms") or []
               if str(r.get("name") or "").strip() == "Attic"), "")
check("(j) entry_room == the new room's id",
      bool(ATTIC5) and inn.get("entry_room") == ATTIC5, (inn.get("entry_room"), ATTIC5))
rep = wu.undo(run, turn=5)
check("(j) undo complete", rep["complete"], rep)
inn = get_location_by_id(INN) or {}
check("(j) record as before turn 5", inn == before5, wu.diff_keys(before5, inn))

# ── Turn 6: the ground-floor corridor as entry room ──────────────────────
from app.core.world_ops import create_location_with_extras  # noqa: E402

tres = create_location_with_extras({"name": "Demo Tower", "create_new": True, "rooms": [
    {"name": "Lobby", "layout": {"level": 0, "x": 0, "y": 0, "w": 6, "d": 6}}]})
TOWER = str(((tres or {}).get("location") or {}).get("id") or "")
tower = get_location_by_id(TOWER) or {}
check("(l) fixture Tower without corridor",
      bool(TOWER) and "__floor__0" not in [r.get("id") for r in tower.get("rooms") or []]
      and isinstance(((tower.get("rooms") or [{}])[0]).get("layout"), dict),
      tower.get("rooms"))
before6 = tower
res = call(6, "update_location", {"id": TOWER, "patch": {
    "map3d": {"ground_corridor": True}, "entry_room": "__floor__0"}})
check("(l) ground_corridor + entry_room __floor__0 ok", res.ok and res.wrote, res)
tower = get_location_by_id(TOWER) or {}
check("(l) corridor __floor__0 exists",
      "__floor__0" in [r.get("id") for r in tower.get("rooms") or []], tower.get("rooms"))
check("(l) entry_room == __floor__0", tower.get("entry_room") == "__floor__0",
      tower.get("entry_room"))
rep = wu.undo(run, turn=6)
check("(l) undo complete", rep["complete"], rep)
tower = get_location_by_id(TOWER) or {}
check("(l) record as before turn 6", tower == before6, wu.diff_keys(before6, tower))

# ── Turns 7/8: map3d takes the corridor entry room away ─────────────────
res = call(7, "update_location", {"id": TOWER, "patch": {
    "map3d": {"ground_corridor": True}, "entry_room": "__floor__0"}})
check("(n) setup corridor entry ok", res.ok and res.wrote, res)
before8 = get_location_by_id(TOWER)
n_before = len(wr.steps(run))
res = call(8, "update_location", {"id": TOWER, "patch": {
    "map3d": {"ground_corridor": False}}})
check("(n) corridor removal without entry_room refused", not res.ok and not res.wrote, res)
check("(n) line names the entry room",
      "removes the entry room" in res.line and "(__floor__0)" in res.line, res.line)
check("(n) journal kind refused",
      len(wr.steps(run)) == n_before + 1 and newest()["kind"] == "refused", newest())
check("(n) record unchanged", get_location_by_id(TOWER) == before8)
res = call(8, "update_location", {"id": TOWER, "patch": {
    "map3d": {"ground_corridor": False}, "entry_room": ""}})
check("(n) corridor removal + entry_room '' ok", res.ok and res.wrote, res)
tower = get_location_by_id(TOWER) or {}
check("(n) corridor gone",
      "__floor__0" not in [r.get("id") for r in tower.get("rooms") or []], tower.get("rooms"))
check("(n) entry_room ''", (tower.get("entry_room") or "") == "", tower.get("entry_room"))
rep = wu.undo(run, turn=8)
check("(n) undo complete", rep["complete"], rep)
tower = get_location_by_id(TOWER) or {}
check("(n) record as before turn 8", tower == before8, wu.diff_keys(before8, tower))

# ── Turns 9/10: dropping the entry room together with entry_room ─────────
for turn, entry, want_entry in ((9, "", ""), (10, "Hall", HALL)):
    tag = f"(o) turn {turn} entry_room {entry!r}"
    before = get_location_by_id(INN)
    res = call(turn, "update_location", {"id": INN, "patch": {
        "rooms": [{"id": HALL}], "entry_room": entry}})
    check(f"{tag}: ok", res.ok and res.wrote, res)
    inn = get_location_by_id(INN) or {}
    check(f"{tag}: rooms [Hall]", room_names(inn) == ["Hall"], room_names(inn))
    check(f"{tag}: entry_room stored", (inn.get("entry_room") or "") == want_entry,
          inn.get("entry_room"))
    rep = wu.undo(run, turn=turn)
    check(f"{tag}: undo complete", rep["complete"], rep)
    inn = get_location_by_id(INN) or {}
    check(f"{tag}: record as before", inn == before, wu.diff_keys(before, inn))

# ── Turns 11/12: the by-name entry write fails after the main write ──────
_real_by_name = wt._write_entry_room_by_name


def _boom(*_a, **_k):
    raise RuntimeError("boom")


wt._write_entry_room_by_name = _boom
try:
    before11 = get_location_by_id(INN)
    raised = None
    try:
        call(11, "update_location", {"id": INN, "patch": {
            "rooms": [{"id": HALL}, {"id": KITCHEN}, {"name": "Attic"}],
            "entry_room": "Attic"}})
    except RuntimeError as exc:
        raised = str(exc)
    check("(p) update: failed by-name write raises", raised == "boom", raised)
    check("(p) update: journalled as a write", newest()["kind"] == "write", newest())
    inn = get_location_by_id(INN) or {}
    check("(p) update: Attic stored by the main write",
          room_names(inn) == ["Hall", "Kitchen", "Attic"], room_names(inn))
    rep = wu.undo(run, turn=11)
    check("(p) update: undo complete", rep["complete"], rep)
    inn = get_location_by_id(INN) or {}
    check("(p) update: record as before turn 11", inn == before11,
          wu.diff_keys(before11, inn))

    raised = None
    try:
        call(12, "create_location", {"data": {
            "name": "Demo Fail", "rooms": [{"name": "Cellar"}], "entry_room": "Cellar"}})
    except RuntimeError as exc:
        raised = str(exc)
    check("(p) create: failed by-name write raises", raised == "boom", raised)
    row = newest()
    check("(p) create: journalled as a write deleting the place",
          row["kind"] == "write" and "delete_location" in str(row), row)
    check("(p) create: place exists after the failure",
          any(l.get("name") == "Demo Fail" for l in list_locations()))
    rep = wu.undo(run, turn=12)
    check("(p) create: undo complete", rep["complete"], rep)
    check("(p) create: no place Demo Fail",
          not any(l.get("name") == "Demo Fail" for l in list_locations()))
finally:
    wt._write_entry_room_by_name = _real_by_name

# ── Discard preview agrees with undo ─────────────────────────────────────
prev = wu.discard_preview(run)
check("discard_preview names Demo Inn once",
      sum("Demo Inn" in ln for ln in prev) == 1, prev)
rep = wu.undo(run)
check("final undo complete", rep["complete"], rep)
check("Demo Inn gone", get_location_by_id(INN) is None)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("all checks passed")
