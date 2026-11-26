#!/usr/bin/env python3
"""Smoke: World Dev free mode — editor fields of places and rooms, list_catalog,
place NPC slots (gaps 16, 5 place part).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p2-buildings-terrain.md, Task 3.
A temp world (paths.init BEFORE any world-DB import), an EMPTY ANIMATION_CLIPS_DIR;
no server, no LLM. Every tool call goes through ``world_dev_tools.run_tool`` exactly
as the agent loop calls it.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_editor_fields.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Fixtures:
  * The character templates are read from a temp directory
    (``character_template.get_templates_dir`` patched) holding ONE template
    "demo-stats" with one field {key "stamina", store "status_effects"} — so
    ``stat_hints.get_all_stat_keys()`` returns ["stamina"] (it collects the
    status_effects fields of every template; asserted once).
  * A door prop created through ``props.create_prop(name "Demo Door",
    category "door")`` — ``props.is_door_prop`` reads category "door" as a
    door. Its id is the slug + hash the core mints (read from the return).
  * A place "Demo Inn" with one room "Taproom" written OUTSIDE the run by
    ``world_ops.create_location_with_extras`` (so the undo restores, never
    deletes it); TAP = the id the writer gave the room (read back by name).
  * An item "Demo Note" (category "document") through ``inventory.add_item``.
  * Demo Inn then gets, still OUTSIDE the run, one
    ``update_location_with_extras(INN, {description "A demo inn.",
    event_settings {event_probability 0.3, stat_effects {ambient {stamina 5}}}})``
    — an admin-authored event setting, and the write canonicalises the raw row
    (a tool write would otherwise add image_prompt_night "" / yaw_deg 0.0 that
    the undo does not take back — reader-equal, see world_dev_undo). RAW_BEFORE
    = every column of its ``locations`` row except updated_at plus every
    column of its ``rooms`` rows, read straight from SQLite.

Allowed values, by hand from the code that stores them:
  stat_rates: world_ops._sanitize_stat_rates keeps {stat, per_hour} with
    per_hour = int clamped to -50…50, at most ten entries.
  event categories: random_events.CATEGORIES = ambient, social, disruption,
    danger (four keys).
  npc_slots: npc_spawn.normalize_slots de-duplicates by lower-cased role
    (so a second "barkeeper" after "Barkeeper" is dropped) and normalize_slot
    adds the defaults template "", briefing "", room "", when "", radius_m 0,
    character "" (count_min 1, count_max max(1, count_min) when not sent).
    "18:00-02:00" is already canonical for npc_windows.normalize_when.
  ambience: world_ops.sanitize_ambience clamps daylight to 0…1 and returns
    None (= the key is dropped) for daylight 1.0 without a tint — so
    {daylight: 1.5} would be stored as nothing at all.
  room_types: shared/furniture/room_types.json — "tavern" is one of them
    (living, bedroom, kitchen, dining, bathroom, study, hall, storage,
    workshop, tavern).
  list_catalog names (9): stats, event_categories, event_settings, room_types,
    furniture_kits, surface_kinds, door_props, terrain_kinds, item_categories.

One run, every write in turn 1:
  (a) create_location Demo Tavern {stat_rates [{stamina, 5}], chattiness 0.4,
      rooms [{name Taproom, room_type tavern, stat_rates [{stamina, 2}]}]}
      -> ok; stored stat_rates == [{"stat": "stamina", "per_hour": 5}],
      chattiness == 0.4 (the create writer does not store chattiness — the
      tool writes it in the same step through the update writer), room
      room_type "tavern" and stat_rates [{"stat": "stamina", "per_hour": 2}].
  (b) stat_rates [{mana, 5}] -> refused, line lists "stamina"; no write.
  (c) per_hour 80 -> refused, "whole number -50…50".
  (d) event_settings {allowed_categories [ambient, heist]} -> refused, the line
      lists "ambient, danger, disruption, social" (sorted).
  (e) npc_slots [{Barkeeper 1/1}, {barkeeper}] -> refused, "would be stored as"
      and "dropped".
  (f) update_location Demo Inn {npc_slots [{Barkeeper, 1, 2, "18:00-02:00",
      room TAP}]} -> ok; stored npc_slots == [sent + defaults template "",
      briefing "", radius_m 0, character ""].
  (f2) update Demo Inn npc_slots room "Cellar" (no such room id) -> refused,
      names the room ids; character "Nobody" -> refused ("temporary NPC").
  (g) update Demo Inn rooms [{id TAP, ambience {daylight 1.5}}] -> refused,
      "would be stored as"; {daylight 0.5} -> ok, stored {"daylight": 0.5,
      "tint": None}.
  (h) update Demo Inn default_door_prop_id <door id> -> ok, stored; "nope" ->
      refused. knowledge_item_id "nope" -> refused; the Demo Note id -> ok.
      chattiness 1.5 -> refused. room_type "dungeon" -> refused, the line has
      "tavern".
  (i) list_catalog{stats} -> a line "stamina"; list_catalog{x} -> refused, the
      line lists all 9 names. list_catalog{room_types} has 'tavern';
      list_catalog{door_props} has the door id; list_catalog{item_categories}
      has "document" and not "outfit_piece"; list_catalog{event_categories}
      has "ambient".
  (i2) create_location {npc_slots [{Barkeeper, room Taproom}]} -> refused
      "add the slot's room with update_location"; no place Demo Bar.
  (i3) get_location{inn, fields [npc_slots, chattiness]} -> npc_slots shown,
      chattiness "(not set)" (a known field, not "no such field").
  (k) event_settings is a PATCH: update {event_settings {allowed_categories
      [ambient]}} -> ok; stored == the fixture object plus allowed_categories
      [ambient] (event_probability 0.3 and stat_effects stay).
  (k2) max_concurrent_events 0 -> refused "1…10"; event_cooldown_hours
      10**400 -> refused "0…48", and the line is short (< 300 chars — it does
      not print the number back). Bounds = RandomEventsEditor.tsx inputs.
  (k3) values the place editor cannot produce (RandomEventsEditor.tsx:
      parseInt inputs, a category checkbox list, blacklist words):
      max_concurrent_events 2.0 -> ok and stored as the int 2 (type int,
      not 2.0); event_cooldown_hours 1.5 -> refused "whole number";
      allowed_categories [ambient, ambient] -> refused "twice";
      event_blacklist [""] and [" rain"] -> refused "leading or trailing".
  (f3) _slot_room_ids skips every reserved room (ids "__…"): for
      [{id __ground__}, {id __floor__1}, {id r1, name A}] it is {"r1": "A"}.
  (l) a rooms patch that drops the Taproom while the Barkeeper slot names
      TAP -> refused, line has TAP, "Barkeeper" and "send npc_slots".
  (m) slot template "no-such-template" -> refused, the line lists
      "demo-stats" (the only template of the fixture dir); template
      "demo-stats" -> ok, stored.
  (n) rooms [{id TAP, ambience {}}] after (g) -> ok; the stored room has no
      "ambience" key (sanitize_ambience({}) is None = dropped by the writer).
  (o) rooms [{id TAP, image_prompt_building "a timbered taproom, no people"}]
      -> ok, stored on the room.
  (p) clearing: stat_rates [{stamina 3}] then [] -> stored [] (the writer
      stores _sanitize_stat_rates([]) == []); chattiness 0.6 then "" -> key
      absent (the writer pops it); after (l2) npc_slots [] -> key absent
      (normalize_slots([]) is empty, the writer pops it).
  (l2) rooms [{name Attic}] + npc_slots [] in ONE patch -> ok (the slot is
      gone with the room): Taproom gone, Attic there.
  (q) create_location Demo Hall {chattiness 0.2, npc_slots [{role Guard}],
      rooms [{name Hall, room_type hall, image_prompt_building "a stone hall",
      ambience {daylight 0.3, tint "#aabbcc"}}]} -> ok, all stored (slot =
      role Guard + the normalize_slot defaults, count_min 1, count_max 1).
  (j) discard_preview lists exactly the two created places (two lines,
      "Demo Tavern" and "Demo Hall"); undo(run, 1) -> complete; both gone;
      Demo Inn back to the record before the run (npc_slots ABSENT again),
      and its RAW locations/rooms rows equal RAW_BEFORE column by column.

A second run (run2), after (j):
  (r) its FIRST call is update_location Demo Inn with a slot room "Cellar"
      -> refused, and the run has no backup_path (the slot check runs before
      step.prepare, so a refused first write copies nothing).
  (s) an admin writes npc_slots [{Cook, room TAP}] OUTSIDE the run; run2's
      rooms patch [{name Attic}] (drops the Taproom) -> refused, line has
      "Cook" and "send npc_slots" — STORED slots guard the room too. The
      admin then clears the slots (npc_slots [] -> key absent).
  (t) turn 1: event_settings {max_concurrent_events 3} -> ok, S1 = the inn
      now; turn 2: event_settings {max_concurrent_events 5} + chattiness 0.7
      -> ok; undo(run2, 2) -> complete and the inn == S1 exactly.
  (u) turn 3: event_settings {event_cooldown_hours 4} -> ok; an admin then
      writes the stored event_settings with event_cooldown_hours 9 (outside
      the run); undo(run2, 3) -> NOT complete, one skip "changed since" with
      keys ["event_settings"]; the stored cooldown stays 9.
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_edf_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_edf_"))
TEMPLATES = Path(tempfile.mkdtemp(prefix="smoke_wd_edf_tpl_"))
paths.init(STORAGE)
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)
atexit.register(shutil.rmtree, TEMPLATES, ignore_errors=True)

from app.core import config, db  # noqa: E402

config.load(paths.get_config_path())
db.init_schema()

from app.models import character_template  # noqa: E402

(TEMPLATES / "demo-stats.json").write_text(json.dumps({
    "name": "demo-stats", "template_type": "character",
    "sections": [{"id": "stats", "fields": [
        {"key": "stamina", "label": "Stamina", "type": "number",
         "store": "status_effects"}]}]}), encoding="utf-8")
character_template.get_templates_dir = lambda: TEMPLATES  # type: ignore[assignment]
character_template.clear_template_cache()

from app.core import props  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core.stat_hints import get_all_stat_keys  # noqa: E402
from app.core.world_ops import create_location_with_extras  # noqa: E402
from app.models import inventory  # noqa: E402
from app.models.world import get_location_by_id, list_locations  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


check("fixture: stat keys == ['stamina']", get_all_stat_keys() == ["stamina"],
      get_all_stat_keys())
DOOR = props.create_prop(name="Demo Door", category="door")["id"]
check("fixture: door prop in temp storage",
      (STORAGE / "props" / DOOR).is_dir() and props.is_door_prop(props.read_sidecar(DOOR)),
      DOOR)
INN = create_location_with_extras({"name": "Demo Inn", "create_new": True,
                                   "rooms": [{"name": "Taproom"}]})["location"]["id"]
TAP = next((r["id"] for r in (get_location_by_id(INN) or {}).get("rooms") or []
            if r.get("name") == "Taproom"), "")
check("fixture: inn with a Taproom", bool(INN) and bool(TAP))
NOTE = inventory.add_item("Demo Note", category="document").get("id") or ""
check("fixture: item", bool(inventory.get_item(NOTE)), NOTE)
from app.core.db import get_connection  # noqa: E402
from app.core.world_ops import update_location_with_extras  # noqa: E402

update_location_with_extras(INN, {"description": "A demo inn.", "event_settings": {
    "event_probability": 0.3, "stat_effects": {"ambient": {"stamina": 5}}}})
ES_FIXTURE = {"event_probability": 0.3, "stat_effects": {"ambient": {"stamina": 5}}}
check("fixture: inn event_settings",
      (get_location_by_id(INN) or {}).get("event_settings") == ES_FIXTURE,
      (get_location_by_id(INN) or {}).get("event_settings"))


def raw_rows(lid):
    conn = get_connection()
    conn.row_factory = None
    cur = conn.execute("SELECT * FROM locations WHERE id=?", (lid,))
    cols = [d[0] for d in cur.description]
    loc = [dict(zip(cols, row)) for row in cur.fetchall()]
    for row in loc:
        row.pop("updated_at", None)
    cur = conn.execute("SELECT * FROM rooms WHERE location_id=? ORDER BY id", (lid,))
    cols = [d[0] for d in cur.description]
    return loc, [dict(zip(cols, row)) for row in cur.fetchall()]


INN_BEFORE = get_location_by_id(INN)
RAW_BEFORE = raw_rows(INN)

run = wr.create_run("editor_fields", "m", "p", "u", 60, 600000)


def call(tool, args, turn=1):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


def named(name):
    return [l for l in list_locations() if l.get("name") == name]


def refused(label, tool, args, *needles):
    n = len(wr.steps(run))
    inn = get_location_by_id(INN)
    res = call(tool, args)
    check(f"{label}: refused", not res.ok and not res.wrote, res)
    for nd in needles:
        check(f"{label}: line has {nd!r}", nd in res.line, res.line)
    check(f"{label}: journal row refused",
          len(wr.steps(run)) == n + 1 and wr.steps(run)[-1]["kind"] == "refused")
    check(f"{label}: inn unchanged", get_location_by_id(INN) == inn)
    return res


# (a)
res = call("create_location", {"data": {
    "name": "Demo Tavern", "stat_rates": [{"stat": "stamina", "per_hour": 5}],
    "chattiness": 0.4,
    "rooms": [{"name": "Taproom", "room_type": "tavern",
               "stat_rates": [{"stat": "stamina", "per_hour": 2}]}]}})
check("(a) ok", res.ok and res.wrote, res)
TAV = (named("Demo Tavern") or [{}])[0]
check("(a) stat_rates", TAV.get("stat_rates") == [{"stat": "stamina", "per_hour": 5}],
      TAV.get("stat_rates"))
check("(a) chattiness", TAV.get("chattiness") == 0.4, TAV.get("chattiness"))
troom = next((r for r in TAV.get("rooms") or [] if r.get("name") == "Taproom"), {})
check("(a) room_type", troom.get("room_type") == "tavern", troom)
check("(a) room stat_rates", troom.get("stat_rates") == [{"stat": "stamina", "per_hour": 2}],
      troom)

# (b) (c) (d) (e)
refused("(b) unknown stat", "update_location",
        {"id": INN, "patch": {"stat_rates": [{"stat": "mana", "per_hour": 5}]}}, "stamina")
refused("(c) per_hour 80", "update_location",
        {"id": INN, "patch": {"stat_rates": [{"stat": "stamina", "per_hour": 80}]}},
        "whole number -50…50")
refused("(d) unknown category", "update_location",
        {"id": INN, "patch": {"event_settings": {"allowed_categories": ["ambient", "heist"]}}},
        "ambient, danger, disruption, social")
refused("(e) duplicate role", "update_location",
        {"id": INN, "patch": {"npc_slots": [
            {"role": "Barkeeper", "count_min": 1, "count_max": 1}, {"role": "barkeeper"}]}},
        "would be stored as", "dropped")

# (f)
SLOT = {"role": "Barkeeper", "count_min": 1, "count_max": 2, "when": "18:00-02:00",
        "room": TAP}
res = call("update_location", {"id": INN, "patch": {"npc_slots": [SLOT]}})
check("(f) ok", res.ok and res.wrote, res)
check("(f) stored slot = sent + defaults",
      (get_location_by_id(INN) or {}).get("npc_slots") == [{
          **SLOT, "template": "", "briefing": "", "radius_m": 0, "character": ""}],
      (get_location_by_id(INN) or {}).get("npc_slots"))
refused("(f2) slot room unknown", "update_location",
        {"id": INN, "patch": {"npc_slots": [{"role": "Cook", "room": "Cellar"}]}}, TAP)
refused("(f2) slot character unknown", "update_location",
        {"id": INN, "patch": {"npc_slots": [{"role": "Cook", "character": "Nobody"}]}},
        "temporary NPC")

# (g)
refused("(g) ambience clamp", "update_location",
        {"id": INN, "patch": {"rooms": [{"id": TAP, "ambience": {"daylight": 1.5}}]}},
        "would be stored as")
res = call("update_location", {"id": INN, "patch": {"rooms": [
    {"id": TAP, "ambience": {"daylight": 0.5}}]}})
check("(g) ambience 0.5 ok", res.ok, res)
room = next((r for r in (get_location_by_id(INN) or {}).get("rooms") or []
             if r.get("id") == TAP), {})
check("(g) ambience stored", room.get("ambience") == {"daylight": 0.5, "tint": None}, room)

# (h)
res = call("update_location", {"id": INN, "patch": {"default_door_prop_id": DOOR}})
check("(h) door prop ok", res.ok and (get_location_by_id(INN) or {}).get(
    "default_door_prop_id") == DOOR, res)
refused("(h) door prop nope", "update_location",
        {"id": INN, "patch": {"default_door_prop_id": "nope"}}, DOOR)
refused("(h) knowledge item nope", "update_location",
        {"id": INN, "patch": {"knowledge_item_id": "nope"}}, "no item")
res = call("update_location", {"id": INN, "patch": {"knowledge_item_id": NOTE}})
check("(h) knowledge item ok",
      res.ok and (get_location_by_id(INN) or {}).get("knowledge_item_id") == NOTE, res)
refused("(h) chattiness 1.5", "update_location",
        {"id": INN, "patch": {"chattiness": 1.5}}, "'chattiness'")
refused("(h) room_type dungeon", "update_location",
        {"id": INN, "patch": {"rooms": [{"id": TAP, "room_type": "dungeon"}]}},
        "tavern", "list_catalog")

# (i)
res = call("list_catalog", {"name": "stats"})
check("(i) stats", res.ok and "stamina" in res.line.split("\n"), res)
res = call("list_catalog", {"name": "x"})
NAMES = ["stats", "event_categories", "event_settings", "room_types", "furniture_kits",
         "surface_kinds", "door_props", "terrain_kinds", "item_categories"]
check("(i) unknown name refused listing 9 names",
      not res.ok and all(n in res.line for n in NAMES), res)
res = call("list_catalog", {"name": "room_types"})
check("(i) room_types", res.ok and "tavern" in res.line, res)
res = call("list_catalog", {"name": "door_props"})
check("(i) door_props", res.ok and DOOR in res.line, res)
res = call("list_catalog", {"name": "item_categories"})
check("(i) item_categories", res.ok and "document" in res.line
      and "outfit_piece" not in res.line, res)
res = call("list_catalog", {"name": "event_categories"})
check("(i) event_categories", res.ok and "ambient" in res.line, res)
for n in NAMES:
    res = call("list_catalog", {"name": n})
    check(f"(i) list_catalog {n} answers", res.ok and res.line.strip(), res)

# (i2)
n_places = len(list_locations())
refused("(i2) slot room on create", "create_location",
        {"data": {"name": "Demo Bar", "rooms": [{"name": "Taproom"}],
                  "npc_slots": [{"role": "Barkeeper", "room": "Taproom"}]}},
        "add the slot's room with update_location")
check("(i2) no place Demo Bar", not named("Demo Bar") and len(list_locations()) == n_places)

# (i3)
res = call("get_location", {"id": INN, "fields": ["npc_slots", "chattiness"]})
check("(i3) npc_slots shown", res.ok and "Barkeeper" in res.line, res)
check("(i3) chattiness is a known field",
      "chattiness: (not set)" in res.line and "no such field" not in res.line, res.line)

def inn_room(rid):
    return next((r for r in (get_location_by_id(INN) or {}).get("rooms") or []
                 if r.get("id") == rid), {})


# (k)
res = call("update_location", {"id": INN, "patch": {
    "event_settings": {"allowed_categories": ["ambient"]}}})
check("(k) ok", res.ok and res.wrote, res)
check("(k) stored keys kept, sent key added",
      (get_location_by_id(INN) or {}).get("event_settings")
      == {**ES_FIXTURE, "allowed_categories": ["ambient"]},
      (get_location_by_id(INN) or {}).get("event_settings"))

# (k2)
refused("(k2) max_concurrent 0", "update_location",
        {"id": INN, "patch": {"event_settings": {"max_concurrent_events": 0}}}, "1…10")
res = refused("(k2) cooldown 10**400", "update_location",
              {"id": INN, "patch": {"event_settings": {"event_cooldown_hours": 10 ** 400}}},
              "0…48")
check("(k2) refusal line is short", len(res.line) < 300, len(res.line))

# (k3)
res = call("update_location", {"id": INN, "patch": {
    "event_settings": {"max_concurrent_events": 2.0}}})
mce = ((get_location_by_id(INN) or {}).get("event_settings") or {}).get(
    "max_concurrent_events")
check("(k3) max_concurrent 2.0 ok", res.ok and res.wrote, res)
check("(k3) stored as int 2", mce == 2 and type(mce) is int, mce)
refused("(k3) cooldown 1.5", "update_location",
        {"id": INN, "patch": {"event_settings": {"event_cooldown_hours": 1.5}}},
        "whole number")
refused("(k3) duplicate category", "update_location",
        {"id": INN, "patch": {"event_settings": {"allowed_categories": ["ambient", "ambient"]}}},
        "twice")
refused("(k3) empty blacklist word", "update_location",
        {"id": INN, "patch": {"event_settings": {"event_blacklist": [""]}}},
        "leading or trailing")
refused("(k3) unstripped blacklist word", "update_location",
        {"id": INN, "patch": {"event_settings": {"event_blacklist": [" rain"]}}},
        "leading or trailing")

# (f3)
check("(f3) reserved rooms are no slot rooms",
      wt._slot_room_ids([{"id": "__ground__"}, {"id": "__floor__1"},
                         {"id": "r1", "name": "A"}]) == {"r1": "A"})

# (l)
refused("(l) slot room removed", "update_location",
        {"id": INN, "patch": {"rooms": [{"name": "Attic"}]}},
        TAP, "Barkeeper", "send npc_slots")

# (m)
refused("(m) unknown template", "update_location",
        {"id": INN, "patch": {"npc_slots": [{**SLOT, "template": "no-such-template"}]}},
        "demo-stats")
res = call("update_location", {"id": INN, "patch": {
    "npc_slots": [{**SLOT, "template": "demo-stats"}]}})
check("(m) template ok", res.ok and ((get_location_by_id(INN) or {}).get("npc_slots")
                                     or [{}])[0].get("template") == "demo-stats", res)

# (n)
res = call("update_location", {"id": INN, "patch": {"rooms": [{"id": TAP, "ambience": {}}]}})
check("(n) ambience {} ok", res.ok and res.wrote, res)
check("(n) ambience cleared", "ambience" not in inn_room(TAP), inn_room(TAP))

# (o)
res = call("update_location", {"id": INN, "patch": {"rooms": [
    {"id": TAP, "image_prompt_building": "a timbered taproom, no people"}]}})
check("(o) ok", res.ok and res.wrote, res)
check("(o) room image_prompt_building stored",
      inn_room(TAP).get("image_prompt_building") == "a timbered taproom, no people",
      inn_room(TAP))

# (p)
res = call("update_location", {"id": INN, "patch": {
    "stat_rates": [{"stat": "stamina", "per_hour": 3}], "chattiness": 0.6}})
check("(p) set ok", res.ok and (get_location_by_id(INN) or {}).get("chattiness") == 0.6, res)
res = call("update_location", {"id": INN, "patch": {"stat_rates": [], "chattiness": ""}})
inn = get_location_by_id(INN) or {}
check("(p) clear ok", res.ok and res.wrote, res)
check("(p) stat_rates []", inn.get("stat_rates") == [], inn.get("stat_rates"))
check("(p) chattiness absent", "chattiness" not in inn, inn.get("chattiness"))

# (l2)
res = call("update_location", {"id": INN, "patch": {
    "rooms": [{"name": "Attic"}], "npc_slots": []}})
inn = get_location_by_id(INN) or {}
check("(l2) ok", res.ok and res.wrote, res)
check("(l2) Taproom gone, Attic there",
      not inn_room(TAP) and any(r.get("name") == "Attic" for r in inn.get("rooms") or []),
      [r.get("name") for r in inn.get("rooms") or []])
check("(p) npc_slots [] -> absent", "npc_slots" not in inn, inn.get("npc_slots"))

# (q)
res = call("create_location", {"data": {
    "name": "Demo Hall", "chattiness": 0.2, "npc_slots": [{"role": "Guard"}],
    "rooms": [{"name": "Hall", "room_type": "hall", "image_prompt_building": "a stone hall",
               "ambience": {"daylight": 0.3, "tint": "#aabbcc"}}]}})
check("(q) ok", res.ok and res.wrote, res)
HALL = (named("Demo Hall") or [{}])[0]
hroom = next((r for r in HALL.get("rooms") or [] if r.get("name") == "Hall"), {})
check("(q) chattiness", HALL.get("chattiness") == 0.2, HALL.get("chattiness"))
check("(q) npc_slots", HALL.get("npc_slots") == [{
    "role": "Guard", "count_min": 1, "count_max": 1, "template": "", "briefing": "",
    "room": "", "when": "", "radius_m": 0, "character": ""}], HALL.get("npc_slots"))
check("(q) room extras", hroom.get("room_type") == "hall"
      and hroom.get("image_prompt_building") == "a stone hall"
      and hroom.get("ambience") == {"daylight": 0.3, "tint": "#aabbcc"}, hroom)

# (j)
prev = wu.discard_preview(run)
check("(j) preview lists exactly the two created places",
      len(prev) == 2 and any("Demo Tavern" in p for p in prev)
      and any("Demo Hall" in p for p in prev), prev)
rep = wu.undo(run, 1)
check("(j) undo complete", rep.get("complete"), rep)
check("(j) tavern gone", not named("Demo Tavern"))
check("(j) hall gone", not named("Demo Hall"))
inn = get_location_by_id(INN) or {}
check("(j) inn restored", inn == INN_BEFORE and "npc_slots" not in inn,
      wu.diff_keys(INN_BEFORE, inn))
raw_after = raw_rows(INN)
check("(j) raw locations row equal", raw_after[0] == RAW_BEFORE[0],
      [(k, RAW_BEFORE[0][0].get(k), v) for k, v in (raw_after[0] or [{}])[0].items()
       if RAW_BEFORE[0] and RAW_BEFORE[0][0].get(k) != v])
check("(j) raw rooms rows equal", raw_after[1] == RAW_BEFORE[1],
      (RAW_BEFORE[1], raw_after[1]))

# ---- run2 ----
wr.set_status(run, "rolled_back")  # one open run at a time (undone in (j))
run2 = wr.create_run("editor_fields_2", "m", "p", "u", 60, 600000)


def call2(tool, args, turn=1):
    return wt.run_tool(wt.ToolCtx(run_id=run2, turn=turn), tool, args)


# (r)
res = call2("update_location", {"id": INN, "patch": {
    "npc_slots": [{"role": "Cook", "room": "Cellar"}]}})
check("(r) refused", not res.ok and not res.wrote, res)
check("(r) no backup taken", not (wr.get_run(run2) or {}).get("backup_path"),
      (wr.get_run(run2) or {}).get("backup_path"))

# (s)
update_location_with_extras(INN, {"npc_slots": [{"role": "Cook", "room": TAP}]})
check("(s) admin slot stored", ((get_location_by_id(INN) or {}).get("npc_slots")
                                or [{}])[0].get("room") == TAP)
inn = get_location_by_id(INN)
res = call2("update_location", {"id": INN, "patch": {"rooms": [{"name": "Attic"}]}})
check("(s) room drop refused", not res.ok and not res.wrote
      and "Cook" in res.line and "send npc_slots" in res.line, res)
check("(s) inn unchanged", get_location_by_id(INN) == inn)
update_location_with_extras(INN, {"npc_slots": []})
check("(s) admin slots cleared", "npc_slots" not in (get_location_by_id(INN) or {}))

# (t)
res = call2("update_location", {"id": INN, "patch": {
    "event_settings": {"max_concurrent_events": 3}}}, turn=1)
check("(t) turn 1 ok", res.ok and res.wrote, res)
S1 = get_location_by_id(INN)
res = call2("update_location", {"id": INN, "patch": {
    "event_settings": {"max_concurrent_events": 5}, "chattiness": 0.7}}, turn=2)
check("(t) turn 2 ok", res.ok and res.wrote, res)
rep = wu.undo(run2, 2)
check("(t) undo turn 2 complete", rep.get("complete"), rep)
check("(t) inn == turn-1 state", get_location_by_id(INN) == S1,
      wu.diff_keys(S1, get_location_by_id(INN) or {}))

# (u)
res = call2("update_location", {"id": INN, "patch": {
    "event_settings": {"event_cooldown_hours": 4}}}, turn=3)
check("(u) turn 3 ok", res.ok and res.wrote, res)
es = dict((get_location_by_id(INN) or {}).get("event_settings") or {})
update_location_with_extras(INN, {"event_settings": {**es, "event_cooldown_hours": 9}})
rep = wu.undo(run2, 3)
check("(u) undo not complete", not rep.get("complete"), rep)
check("(u) one skip changed since, keys ['event_settings']",
      [(s.get("reason"), s.get("keys")) for s in rep.get("skipped") or []]
      == [("changed since", ["event_settings"])], rep.get("skipped"))
check("(u) foreign cooldown kept",
      ((get_location_by_id(INN) or {}).get("event_settings") or {}).get(
          "event_cooldown_hours") == 9)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("all checks passed")
