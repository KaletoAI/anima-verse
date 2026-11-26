#!/usr/bin/env python3
"""Smoke: World Dev free mode — clothing slots from the species, dead outfit
keys refused, the starting outfit (gaps 13, 25).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p1-characters.md, Task 4.
A temp world (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM. Every tool call goes through
``world_dev_tools.run_tool`` exactly as the agent loop calls it.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_outfits.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

The plugin registry is CLEARED (no private pack can declare its own clothing
slots for human-roleplay) and one FAKE species package is registered:

    id smoke_species, apply_to ["human-roleplay"],
    piece_slots ["head", "underwear_top", "underwear_bottom", "top", "bottom", "feet"]

The outfits used below (all pieces NEW, so every piece is one catalog item,
created in draft order — on_item order = the create step's inverse items):

    Daily: Demo Undershirt [underwear_top], Demo Underpants [underwear_bottom],
           Demo Blouse [top], Demo Skirt [bottom], Demo Shoes [feet]   (5 items)
    Night: Demo Dress [top, bottom], Demo Slippers [feet]             (2 items)

  (a) create Demo Weaver with [Daily, Night], no `wear` -> ok; the first
      outfit is worn: get_equipped_pieces == {underwear_top: items[0],
      underwear_bottom: items[1], top: items[2], bottom: items[3],
      feet: items[4]}. The line holds ", wearing Daily (underwear_top,
      underwear_bottom, top, bottom, feet)" — the worn slots in the species'
      declared order (head is not worn).
  (b) the same draft as Demo Weaver2 with wear "night" (case-insensitive) ->
      equipped {top: items[5], bottom: items[5], feet: items[6]} (the dress
      occupies both of its slots), line ", wearing Night (top, bottom, feet)"
      (the stored name's spelling).
  (c) a piece with slots ["hands"] (a core slot, but not the species') ->
      refused; the line says "'slots' must name at least one of head,
      underwear_top, underwear_bottom, top, bottom, feet" (declared order);
      no character, the catalog item count unchanged.
  (d) an outfit with "locations": [] -> refused, the line names 'locations'
      and "not bound to places or activities"; same for "activities" and
      "excluded_locations". No character.
  (e) wear "Gala" -> refused, the line names the outfits ("Daily", "Night");
      wear without outfits -> refused; wear 3 (not a string) -> refused.
      Two outfits with the same name (Daily, daily) -> refused "given twice".
      No character in any of these.
  (f) update_character{"Demo Weaver", patch: {wear: "Daily"}} -> refused,
      the line names the "wardrobe".
  (k) update_character on Demo Weaver adding an outfit with a piece in slot
      "hands" -> refused with the same 6-slot list (the stored profile's
      species decides); an added outfit with "activities" -> refused.
  (h) discard_preview of the run lists Demo Weaver and Demo Weaver2, each
      with ", 7 outfit pieces it brought" (5 Daily + 2 Night new items each
      — a character's own inventory is the dedupe scope, so Weaver2 brings
      its own 7). Before the undo each of the two has at least one
      state_history row of type "outfit" (the equip). undo(run) -> complete;
      both gone, all 14 items gone, NO state_history row of either name, and
      EXACT: a dump of every table (journal tables and sqlite_sequence left
      out) taken before (a) equals the one after the undo (refused calls
      write nothing, so (c)-(k) add nothing), and so does the storage file
      tree (SQLite files and .cache/world_dev_backups left out).
  (i) the route refactor, on a fixture Demo Keeper (saved directly) with
      one set "Daily" = [Demo Gown [top, bottom], Demo Boots [feet]]:
      outfit_set_pieces_by_slot(set) == {"top": gown, "feet": boots} (first
      declared slot of each piece), and _apply_outfit_set_route_sync(
      "Demo Keeper", {"name": "Daily"})["applied"] ==
      [{gown, top}, {gown, bottom}, {boots, feet}] — the multi-slot piece
      first, each piece's slots in its declared order (the same list the
      route returned before the refactor: the loop moved, not changed).
  (j) failed save: app.models.character.save_character_profile wrapped so
      that it returns False WITHOUT storing for exactly the write that sets
      Demo Fail's equipped_pieces (the equip; every write before it — the
      apply, the field write — carries no equipped_pieces) ->
      create_character ok False, the result line holds "the starting outfit
      was not stored" and the kept-note "partly written: character Demo
      Fail"; the journal step's line starts "failed: the starting outfit
      was not stored" (as smoke_world_dev_tools (h)); the step is done with inverse delete_character
      carrying the 5 new items. Right after the failed create NO render timer
      of Demo Fail is armed (apply_equipped_pieces notified the outfit change
      although nothing was stored; _wear_starting_outfit disarms it — red on
      the code before this fix: {"pose", "figure_build"} were armed).
      undo(run) -> complete, Demo Fail and its 5 items gone; the table dump
      and the file tree equal the ones taken before the create.
  (l) a set with two NEW pieces whose first slot is the same: Twin =
      [Demo Tee [top], Demo Vest [top], Demo Sock [feet]] on Demo Twin ->
      ok; outfit_set_pieces_by_slot keeps ONE piece per first slot, the
      last one written (dict assignment), so worn == {top: Vest (items[1]),
      feet: Sock (items[2])}; the line holds ", wearing Twin (top, feet)"
      AND the warning "starting outfit Twin: piece <items[0]> not worn
      (another piece of the outfit takes its slot)" — Tee never reached
      apply_equipped_pieces, so it is no "skipped" entry.
  (m) render timers of a created character (model_refs, default config:
      model_ref_renders_enabled missing = on, debounce missing = 60 s, no
      model_ref_auto key = every kind on): right after the create the armed
      kinds of Demo Twin are exactly schedule_outfit_render's set — on the
      base-body pipeline {"pose", "figure_build"} (tpose is a Build step),
      else {"tpose", "pose"}. undo(run) -> complete, Demo Twin gone, and NO
      timer of Demo Twin is armed any more (delete_character ->
      model_refs.cancel_character_timers).
      A timer body that had already started (armed by hand: the entry's
      timer IS the running thread) for the gone Demo Twin, kinds "pose" and
      "figure_build" -> neither model_refs._fire_kinds nor
      figure_build.request is called (both replaced by recorders here, so
      no render is ever started). Positive control: the same for the
      existing Demo Keeper, kind "pose" -> _fire_kinds called once with
      ("Demo Keeper", ("pose",)). The same for Demo Keeper with
      character_row_exists raising sqlite3.OperationalError (a locked DB):
      only a CONFIRMED missing row is "gone", so it fires -> a second
      ("Demo Keeper", ("pose",)) call.
  (g) describe_template{template: "human-roleplay"} WITH the fake package ->
      line "outfit slots: head, underwear_top, underwear_bottom, top,
      bottom, feet"; human-default (no outfits) -> no "outfit slots:" line.
      After registry.clear_registry() + clear_template_cache() -> the line
      is "outfit slots: " + ", ".join(inventory.VALID_PIECE_SLOTS) — the 11
      core slots underwear_top, underwear_bottom, legs, top, bottom, outer,
      feet, hands, neck, face, head (inventory.py, VALID_PIECE_SLOTS).
  (n) a fake species whose ONLY clothing slot is "tail_sock" (not in
      VALID_PIECE_SLOTS, so the catalog could never store it) ->
      describe_template line "outfit slots: none the catalog can store
      (existing pieces by item_id only)"; create_character with a new piece
      in slots ["tail_sock"] -> refused with "this template has no clothing
      slots the catalog can store"; no character.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_outfits_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_outfits_"))
paths.init(STORAGE)
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core.db import get_connection  # noqa: E402
from app.models import character as charmod  # noqa: E402
from app.models import inventory as invmod  # noqa: E402
from app.models.character import (add_character_outfit,  # noqa: E402
                                  character_row_exists, get_character_outfits,
                                  save_character_profile)
from app.models.character_template import clear_template_cache  # noqa: E402
from app.models.inventory import (add_item, add_to_inventory,  # noqa: E402
                                  get_equipped_pieces, get_item)
from app.plugins import registry  # noqa: E402
from app.plugins.registry import Package  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


SPECIES_SLOTS = ["head", "underwear_top", "underwear_bottom", "top", "bottom", "feet"]
registry.clear_registry()
registry.register_package(Package(
    id="smoke_species", dir=STORAGE, manifest={}, apply_to=["human-roleplay"],
    piece_slots=list(SPECIES_SLOTS)))
clear_template_cache()


def piece(name, *slots):
    return {"name": name, "slots": list(slots), "prompt_fragment": name.lower()}


def daily(name="Daily"):
    return {"name": name, "pieces": [
        piece("Demo Undershirt", "underwear_top"), piece("Demo Underpants", "underwear_bottom"),
        piece("Demo Blouse", "top"), piece("Demo Skirt", "bottom"), piece("Demo Shoes", "feet")]}


def night():
    return {"name": "Night", "pieces": [piece("Demo Dress", "top", "bottom"),
                                        piece("Demo Slippers", "feet")]}


def item_count():
    return len(invmod.list_items())


def outfit_rows(name):
    return get_connection().execute(
        "SELECT COUNT(*) FROM state_history WHERE character_name=? "
        "AND json_extract(state_json, '$.type')='outfit'", (name,)).fetchone()[0]


def all_rows(name):
    return get_connection().execute(
        "SELECT COUNT(*) FROM state_history WHERE character_name=?", (name,)).fetchone()[0]


#: The journal itself and SQLite's own counter (as smoke_world_dev_tools).
_DUMP_SKIP = {"world_dev_journal", "world_dev_runs", "sqlite_sequence"}


def db_dump():
    """Every row of every table (journal tables left out), with its rowid."""
    conn = get_connection()
    out = {}
    for (tbl,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                               "ORDER BY name").fetchall():
        if tbl in _DUMP_SKIP:
            continue
        try:
            rows = conn.execute(f'SELECT rowid, * FROM "{tbl}" ORDER BY rowid').fetchall()
        except sqlite3.OperationalError:
            rows = sorted(conn.execute(f'SELECT * FROM "{tbl}"').fetchall(), key=repr)
        out[tbl] = [tuple(r) for r in rows]
    return out


def dump_diff(a, b):
    return [t for t in sorted(set(a) | set(b)) if a.get(t) != b.get(t)]


def file_tree():
    """Every file under the temp storage except the SQLite files themselves
    and the runs' own backups (.cache/world_dev_backups — run machinery, like
    the journal tables)."""
    return {rel: p.read_bytes() for p in sorted(STORAGE.rglob("*"))
            if p.is_file() and ".db" not in p.name
            and not (rel := p.relative_to(STORAGE).as_posix()).startswith(
                ".cache/world_dev_backups/")}


def create_items(run_id, name):
    for e in wr.entries(run_id):
        inv = e.get("inverse") or {}
        if inv.get("op") == "delete_character" and inv.get("name") == name:
            return list(inv.get("items") or [])
    return []


run = wr.create_run("outfits", "m", "p", "u", 40, 300000)
ctx = wt.ToolCtx(run_id=run, turn=1)


def call(name, args, c=None):
    return wt.run_tool(c or ctx, name, args)


# (a)
dump_h, tree_h = db_dump(), file_tree()
res = call("create_character", {"data": {"name": "Demo Weaver", "outfits": [daily(), night()]}})
check("(a) ok", res.ok, res.line)
items_a = create_items(run, "Demo Weaver")
check("(a) 7 new items", len(items_a) == 7, items_a)
if len(items_a) == 7:
    check("(a) first outfit worn", get_equipped_pieces("Demo Weaver") == {
        "underwear_top": items_a[0], "underwear_bottom": items_a[1], "top": items_a[2],
        "bottom": items_a[3], "feet": items_a[4]}, get_equipped_pieces("Demo Weaver"))
check("(a) line names the worn outfit",
      ", wearing Daily (underwear_top, underwear_bottom, top, bottom, feet)" in res.line, res.line)

# (b)
res = call("create_character", {"data": {"name": "Demo Weaver2", "outfits": [daily(), night()],
                                          "wear": "night"}})
check("(b) ok", res.ok, res.line)
items_b = create_items(run, "Demo Weaver2")
if len(items_b) == 7:
    check("(b) Night worn", get_equipped_pieces("Demo Weaver2") == {
        "top": items_b[5], "bottom": items_b[5], "feet": items_b[6]},
        get_equipped_pieces("Demo Weaver2"))
else:
    check("(b) 7 new items", False, items_b)
check("(b) line", ", wearing Night (top, bottom, feet)" in res.line, res.line)

# (c)
n_items = item_count()
bad = daily()
bad["pieces"].append(piece("Demo Gloves", "hands"))
res = call("create_character", {"data": {"name": "Demo Hands", "outfits": [bad]}})
check("(c) hands refused with the species slot list",
      not res.ok and "'slots' must name at least one of head, underwear_top, "
      "underwear_bottom, top, bottom, feet" in res.line, res.line)
check("(c) no character", not character_row_exists("Demo Hands"))
check("(c) no new catalog item", item_count() == n_items, (item_count(), n_items))

# (d)
for key in ("locations", "activities", "excluded_locations"):
    o = daily()
    o[key] = []
    res = call("create_character", {"data": {"name": "Demo Bound", "outfits": [o]}})
    check(f"(d) {key} refused", not res.ok and f"'{key}'" in res.line
          and "not bound to places or activities" in res.line, res.line)
check("(d) no character", not character_row_exists("Demo Bound"))

# (e)
res = call("create_character", {"data": {"name": "Demo Gala", "outfits": [daily(), night()],
                                          "wear": "Gala"}})
check("(e) unknown wear refused, names the outfits",
      not res.ok and '"Daily"' in res.line and '"Night"' in res.line, res.line)
res = call("create_character", {"data": {"name": "Demo Gala", "wear": "Daily"}})
check("(e) wear without outfits refused", not res.ok and "'wear'" in res.line, res.line)
res = call("create_character", {"data": {"name": "Demo Gala", "outfits": [daily()], "wear": 3}})
check("(e) wear not a string refused", not res.ok and "'wear'" in res.line, res.line)
res = call("create_character", {"data": {"name": "Demo Gala", "outfits": [daily(), daily("daily")]}})
check("(e) duplicate outfit names refused", not res.ok and "given twice" in res.line, res.line)
check("(e) no character", not character_row_exists("Demo Gala"))

# (f)
res = call("update_character", {"name": "Demo Weaver", "patch": {"wear": "Daily"}})
check("(f) update wear refused", not res.ok and "wardrobe" in res.line, res.line)

# (k)
res = call("update_character", {"name": "Demo Weaver", "patch": {"outfits": [
    {"name": "Work", "pieces": [piece("Demo Gloves", "hands")]}]}})
check("(k) update: hands refused with the species list",
      not res.ok and "'slots' must name at least one of head, underwear_top, "
      "underwear_bottom, top, bottom, feet" in res.line, res.line)
res = call("update_character", {"name": "Demo Weaver", "patch": {"outfits": [
    {"name": "Work", "activities": ["work"]}]}})
check("(k) update: activities refused",
      not res.ok and "'activities'" in res.line, res.line)

# (h)
prev = wu.discard_preview(run)
for nm in ("Demo Weaver", "Demo Weaver2"):
    check(f"(h) discard_preview lists {nm} with 7 pieces",
          any(ln.startswith(f'character "{nm}" —') and ln.endswith(", 7 outfit pieces it brought")
              for ln in prev), prev)
    check(f"(h) {nm} has an outfit history row", outfit_rows(nm) >= 1, outfit_rows(nm))
rep = wu.undo(run)
check("(h) undo complete", rep.get("complete"), rep)
for nm in ("Demo Weaver", "Demo Weaver2"):
    check(f"(h) {nm} gone", not character_row_exists(nm))
    check(f"(h) no state_history row of {nm}", all_rows(nm) == 0, all_rows(nm))
check("(h) all 14 items gone",
      all(get_item(i) is None for i in items_a + items_b) and len(items_a + items_b) == 14,
      [i for i in items_a + items_b if get_item(i) is not None])
check("(h) undo exact: every table as before the first create",
      dump_diff(dump_h, db_dump()) == [], dump_diff(dump_h, db_dump()))
check("(h) undo exact: the storage file tree as before",
      file_tree() == tree_h, sorted(set(file_tree()) ^ set(tree_h)))
wr.set_status(run, "rolled_back")

# (i)
save_character_profile("Demo Keeper", {"name": "Demo Keeper", "template": "human-roleplay"},
                       create_new=True)
gown = add_item(name="Demo Gown", description="", category="outfit_piece", image_prompt="",
                prompt_fragment="a gown",
                outfit_piece={"slots": ["top", "bottom"], "covers": [], "partially_covers": []})["id"]
boots = add_item(name="Demo Boots", description="", category="outfit_piece", image_prompt="",
                 prompt_fragment="boots",
                 outfit_piece={"slots": ["feet"], "covers": [], "partially_covers": []})["id"]
for iid in (gown, boots):
    add_to_inventory(character_name="Demo Keeper", item_id=iid, obtained_method="manual",
                     obtained_from="smoke")
add_character_outfit("Demo Keeper", {"name": "Daily", "pieces": [gown, boots]})
kset = next(o for o in get_character_outfits("Demo Keeper") if o["name"] == "Daily")
fn = getattr(invmod, "outfit_set_pieces_by_slot", None)
check("(i) outfit_set_pieces_by_slot", fn is not None and fn(kset) == {"top": gown, "feet": boots},
      fn and fn(kset))
from app.routes.inventory import _apply_outfit_set_route_sync  # noqa: E402
out = _apply_outfit_set_route_sync("Demo Keeper", {"name": "Daily"})
check("(i) route applied list", out.get("applied") == [
    {"item_id": gown, "slot": "top"}, {"item_id": gown, "slot": "bottom"},
    {"item_id": boots, "slot": "feet"}], out.get("applied"))

# (j)
from app.core import figure_build, model_refs  # noqa: E402
from app.core.base_body import is_base_pipeline  # noqa: E402


def armed(name):
    with model_refs._lock:
        return {k[1] for k in model_refs._pending_timers if k[0] == name}


run_j = wr.create_run("outfits-fail", "m", "p", "u", 40, 300000)
ctx_j = wt.ToolCtx(run_id=run_j, turn=1)
_orig_save = charmod.save_character_profile


def _failing_save(name, profile, *a, **kw):
    if name == "Demo Fail" and (profile or {}).get("equipped_pieces"):
        return False
    return _orig_save(name, profile, *a, **kw)


dump_j, tree_j = db_dump(), file_tree()
charmod.save_character_profile = _failing_save
try:
    res = call("create_character", {"data": {"name": "Demo Fail", "outfits": [daily()]}}, ctx_j)
finally:
    charmod.save_character_profile = _orig_save
check("(j) not ok, the result names the starting outfit and the kept character",
      not res.ok and "the starting outfit was not stored" in res.line
      and "partly written: character Demo Fail" in res.line, res.line)
step_j = [e for e in wr.entries(run_j) if e.get("tool") == "create_character"]
check("(j) no render timer of Demo Fail armed after the failed create (it wears nothing)",
      armed("Demo Fail") == set(), armed("Demo Fail"))
check("(j) journal line starts 'failed:'",
      len(step_j) == 1 and str(step_j[0].get("line") or "").startswith(
          "failed: the starting outfit was not stored"), step_j)
inv_j = (step_j[0].get("inverse") or {}) if step_j else {}
check("(j) step done with delete_character + 5 items",
      len(step_j) == 1 and step_j[0].get("state") == "done"
      and inv_j.get("op") == "delete_character" and len(inv_j.get("items") or []) == 5,
      step_j)
rep = wu.undo(run_j)
check("(j) undo complete", rep.get("complete"), rep)
check("(j) Demo Fail gone", not character_row_exists("Demo Fail"))
check("(j) its items gone", all(get_item(i) is None for i in inv_j.get("items") or []))
check("(j) undo exact: every table as before the create",
      dump_diff(dump_j, db_dump()) == [], dump_diff(dump_j, db_dump()))
check("(j) undo exact: the storage file tree as before",
      file_tree() == tree_j, sorted(set(file_tree()) ^ set(tree_j)))
wr.set_status(run_j, "rolled_back")

# (l)
run_l = wr.create_run("outfits-twin", "m", "p", "u", 40, 300000)
ctx_l = wt.ToolCtx(run_id=run_l, turn=1)
res = call("create_character", {"data": {"name": "Demo Twin", "outfits": [{"name": "Twin", "pieces": [
    piece("Demo Tee", "top"), piece("Demo Vest", "top"), piece("Demo Sock", "feet")]}]}}, ctx_l)
items_l = create_items(run_l, "Demo Twin")
check("(l) ok, 3 new items", res.ok and len(items_l) == 3, (res.line, items_l))
if len(items_l) == 3:
    check("(l) worn: Vest on top, Sock on feet",
          get_equipped_pieces("Demo Twin") == {"top": items_l[1], "feet": items_l[2]},
          get_equipped_pieces("Demo Twin"))
    check("(l) line: wearing Twin (top, feet) + the Tee warning",
          ", wearing Twin (top, feet)" in res.line
          and f"starting outfit Twin: piece {items_l[0]} not worn (another piece of the "
              "outfit takes its slot)" in res.line, res.line)

# (m)
want_m = {"pose", "figure_build"} if is_base_pipeline("Demo Twin") else {"tpose", "pose"}
check("(m) timers armed after the create", armed("Demo Twin") == want_m,
      (armed("Demo Twin"), want_m))
rep = wu.undo(run_l)
check("(m) undo complete, Demo Twin gone",
      rep.get("complete") and not character_row_exists("Demo Twin"), rep)
check("(m) no timer of Demo Twin armed after the undo", armed("Demo Twin") == set(),
      armed("Demo Twin"))
fired, built = [], []
_orig_fire, _orig_request = model_refs._fire_kinds, figure_build.request
model_refs._fire_kinds = lambda name, kinds, *a, **kw: fired.append((name, kinds))
figure_build.request = lambda name, *a, **kw: built.append(name)


def started_timer(name, kind):
    """Run _fire_kind as a timer body that had already started (the armed
    entry's timer is the running thread)."""
    import threading
    from app.core.timeutils import utc_now
    t = threading.Thread(target=model_refs._fire_kind, args=[name, kind])
    with model_refs._lock:
        model_refs._pending_timers[(name, kind)] = model_refs._Scheduled(
            timer=t, scheduled_at=utc_now(), due_at=utc_now())
    t.start()
    t.join(10)


try:
    started_timer("Demo Twin", "pose")
    started_timer("Demo Twin", "figure_build")
    check("(m) gone character: no render, no Build", fired == [] and built == [], (fired, built))
    started_timer("Demo Keeper", "pose")
    check("(m) positive control: Demo Keeper pose fires once",
          fired == [("Demo Keeper", ("pose",))], fired)
    _orig_exists = charmod.character_row_exists

    def _locked(_name):
        raise sqlite3.OperationalError("database is locked")

    charmod.character_row_exists = _locked
    try:
        started_timer("Demo Keeper", "pose")
    finally:
        charmod.character_row_exists = _orig_exists
    check("(m) a row check that fails (locked DB) fires as before: a second pose call",
          fired == [("Demo Keeper", ("pose",)), ("Demo Keeper", ("pose",))], fired)
finally:
    model_refs._fire_kinds, figure_build.request = _orig_fire, _orig_request
model_refs.cancel_character_timers("Demo Keeper")
wr.set_status(run_l, "rolled_back")

# (g)
res = call("describe_template", {"template": "human-roleplay"})
check("(g) species outfit slots line",
      res.ok and "outfit slots: head, underwear_top, underwear_bottom, top, bottom, feet"
      in res.line.splitlines(), [ln for ln in res.line.splitlines() if "slots" in ln])
res = call("describe_template", {"template": "human-default"})
check("(g) human-default: no outfit slots line",
      res.ok and not any(ln.startswith("outfit slots:") for ln in res.line.splitlines()))
registry.clear_registry()
clear_template_cache()
res = call("describe_template", {"template": "human-roleplay"})
CORE = ("underwear_top, underwear_bottom, legs, top, bottom, outer, feet, hands, neck, "
        "face, head")
check("(g) core list equals VALID_PIECE_SLOTS", ", ".join(invmod.VALID_PIECE_SLOTS) == CORE)
check("(g) core outfit slots line", res.ok and f"outfit slots: {CORE}" in res.line.splitlines(),
      [ln for ln in res.line.splitlines() if "slots" in ln])

# (n)
registry.register_package(Package(
    id="smoke_tailed", dir=STORAGE, manifest={}, apply_to=["human-roleplay"],
    piece_slots=["tail_sock"]))
clear_template_cache()
res = call("describe_template", {"template": "human-roleplay"})
check("(n) describe_template: no storable outfit slots",
      res.ok and "outfit slots: none the catalog can store (existing pieces by item_id only)"
      in res.line.splitlines(), [ln for ln in res.line.splitlines() if "slots" in ln])
res = call("create_character", {"data": {"name": "Demo Tailed", "outfits": [
    {"name": "Tail", "pieces": [piece("Demo Tail Sock", "tail_sock")]}]}})
check("(n) new piece refused: no storable slots",
      not res.ok and "this template has no clothing slots the catalog can store" in res.line,
      res.line)
check("(n) no character", not character_row_exists("Demo Tailed"))

print()
if failures:
    print(f"FAILED ({len(failures)}): " + "; ".join(failures))
    sys.exit(1)
print("all outfit checks passed")
