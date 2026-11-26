#!/usr/bin/env python3
"""Smoke: World Dev free mode — the media lane's element steps, fingerprints,
baselines at the first touch and the plan (plan
docs/superpowers/plans/2026-11-25-world-dev-free-media.md, Task 4).

A temp world and instance (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM, no render: ``plan`` and
``element_steps`` only READ (fingerprints of render inputs), and
``get_image_service`` is replaced by a function that raises, so a path that
reached a render would fail loudly. Every tool runs through
``world_dev_tools.run_tool`` (the real journal + the real _Step hooks).

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_media_plan.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

The plugin registry is cleared and one fake species is registered for
"human-roleplay": piece slots ["top"] and ONE body slot "hair" that declares
``mesh_item: hair`` with the always-fragment "{length} {color} hair" (the shape
of plugins/human's hair slot). So a character with
body_slots.hair = {color: red, length: long} has the appearance hair text
"long red hair" (garment_hair.appearance_hair_text: the slot fragment) and
owns no hairstyle — exactly ensure_hairstyle's "make the first one" case.

Step order of an element (world_dev_media.element_steps):
  location : building-front, day:, night:, day:<room>, night:<room> per real
             room in stored order (the ground __ground__ and the corridors
             __floor__<n> excluded), mesh.
  character: hairstyle (only on the pipeline, humanoid, hair slot, no
             hairstyle owned or worn, non-empty hair text), portrait, then
             build (on the base-body pipeline) or mesh (off it).

  (a) create_location "Demo Keep" with rooms Hall, Yard -> the stored real
      rooms are those two (ids r1, r2 read back from the location); plan of
      the run in review lists for it exactly
      ["building-front", "day:", "night:", "day:<r1>", "night:<r1>",
       "day:<r2>", "night:<r2>", "mesh"] (2 + 2*2 + 2 = 8; the writer's
      reserved rooms are not in it). Its baseline is None although
      _Step.attach ran AFTER create_location_with_extras had written the place:
      the attach carries the delete_location inverse = a create-inverse (M13).
  (b) pre-existing "Demo Mill" (add_location before the run, rooms Hall with
      image_prompt_day "a calm hall", Shed) changed by update_location on the
      Hall's image_prompt_day only ("a busy hall") -> due ["day:<hall>"]: the
      gallery fingerprint is sha256 of [type, room, subject, use case] and only
      the Hall day subject changed (resolve_gallery_subject: a room day render
      takes the room's image_prompt_day; the night render falls back to the
      room's image_prompt_day only when image_prompt_night is empty — so the
      Hall NIGHT subject changes too unless the room has a night prompt; the
      fixture therefore gives the Hall image_prompt_night "a dark hall" and the
      expected due list is ["day:<hall>"] alone). A second update that puts
      "a calm hall" back -> due [] (back at the baseline; the element is then
      not in the plan at all).
  (c) pre-existing "Demo Plain" (saved directly, template human-roleplay, no
      hair values) touched by update_character schedule = [{hour 8, sleep}]
      -> due [] (the schedule is no render input: hair text "", face prompt,
      wanted figure all unchanged).
  (d) create_character "Demo Hair" with body_slots.hair {red, long}: a
      humanoid of human-roleplay is on the base-body pipeline
      (base_body.is_base_pipeline: every humanoid that is no temporary NPC),
      no hairstyle owned, hair text "long red hair" ->
      ["hairstyle", "portrait", "build"]; the hairstyle step's fp is that text.
      create_character "Demo Lean" with figure_build.on_pipeline patched to
      False (the off-pipeline branch — a humanoid cannot be put off it in a
      temp world) -> ["portrait", "mesh"].
  (e) set_media_enabled(run, False) -> plan(run) == []; on again -> back.
  (f) element_steps patched to raise during the first touch of a
      pre-existing location ("Demo Barn", update_location description) -> the
      tool call is still ok and wrote; the stored baseline is {} (every step
      due) -> due = every step of a roomless place,
      ["building-front", "day:", "night:", "mesh"] (4 ids).
  (g) create_character "Demo Made": the begin carries the name and the
      unclaimed delete_character inverse (no touch), the claimed attach marks
      it created -> baseline None; a later update_character (schedule) in the
      same run leaves it None.
  (h) "already held": a queued media row of the run holding "day:<hall>"
      with the CURRENT fp hides that step from the plan; a row holding a
      different fp ("stale") does not.
  (i) plan is [] while the run is "running" (M15) and lists again in
      "interrupted".
  (j) the baseline read writes nothing: "Demo Quiet" saved directly has the
      raw config_json '{}' (save_character_profile stores no config); the
      default config reader would SAVE the defaults on its first read
      (get_character_config's auto-create). note_touch of a second run on it
      -> a dict baseline is stored and the raw config_json is still '{}'
      (element_steps reads under character.no_config_auto_create).
  (k) the create race: "Demo Foreign" exists (created by someone else after
      the tool's re-check). note_touch with the UNCLAIMED delete_character
      inverse of create_character's begin records nothing (key absent, so
      plan() never lists it); the claimed inverse ({"claimed": True}) marks
      it created -> baseline None.
  (l) an item step touches the item's wearers: "Demo Wearer" saved with
      equipped_pieces {top: item_demo_coat}, "Demo Hairdo" with
      equipped_mesh_pieces {hair: item_demo_coat} (a worn mesh piece counts
      the same), "Demo Bare" with none. note_item_touch of a third run with a
      non-create inverse ({"op": "restore_item"}) -> baselines exist (dicts)
      for exactly Wearer and Hairdo, none for Bare; item_wearers sorts them
      ["Demo Hairdo", "Demo Wearer"]. With the create-inverse delete_items in
      a fourth run -> no character baseline at all (a new item has no wearer).
  (m) the gate of the ("shape", "outfit_side_draft") occasion is
      _side_views_on, which reads base_body.side_views_dressed(): the world
      setting base_body.dressed_side_views, shipped default False
      (config_schema). Unset -> False, False -> False, True -> True, and none
      of the three raises (the call named a function base_body never had).
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TMP = Path(tempfile.mkdtemp(prefix="smoke_wd_media_plan_"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
os.environ["STORAGE_DIR"] = str(TMP / "world")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")

from app.core import paths  # noqa: E402

paths.init(TMP / "world")

from app.core import db  # noqa: E402

db.init_schema()

import app.imagegen.service as image_service  # noqa: E402


def _no_render(*_a, **_k):
    raise AssertionError("render reached")


image_service.get_image_service = _no_render

from app.core import figure_build  # noqa: E402
from app.core import world_dev_media as wdm  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402
from app.models.character_template import clear_template_cache  # noqa: E402
from app.models.world import add_location, get_location_by_id  # noqa: E402
from app.plugins import registry  # noqa: E402
from app.plugins.registry import BodySlotSpec, Package  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


registry.clear_registry()
registry.register_package(Package(
    id="smoke_species", dir=TMP, manifest={}, apply_to=["human-roleplay"],
    piece_slots=["top"],
    body_slots=[BodySlotSpec(
        id="hair", package_id="smoke_species", face=True, mesh_item="hair",
        attributes={"color": {"type": "select", "options": ["red", "black"]},
                    "length": {"type": "select", "options": ["short", "long"]}},
        prompt={"always": "{length} {color} hair"})]))
clear_template_cache()


def due(run_id, kind, ident):
    for k, i, steps in wdm.plan(run_id):
        if (k, i) == (kind, str(ident)):
            return [s.id for s in steps]
    return []


def review(run_id, status="awaiting_review"):
    wr.set_status(run_id, status)


def running(run_id):
    wr.set_status(run_id, "running")


def real_room_ids(loc):
    return [str(r["id"]) for r in loc.get("rooms") or []
            if not str(r.get("id") or "").startswith("__")]


# ── Fixtures before the run ──────────────────────────────────────────────
mill = add_location("Demo Mill", "an old mill", rooms=[
    {"name": "Hall", "image_prompt_day": "a calm hall", "image_prompt_night": "a dark hall"},
    {"name": "Shed", "image_prompt_day": "a shed"}])
mill_id = mill["id"]
hall = next(str(r["id"]) for r in mill["rooms"] if r["name"] == "Hall")
shed = next(str(r["id"]) for r in mill["rooms"] if r["name"] == "Shed")
barn = add_location("Demo Barn", "a barn")
save_character_profile("Demo Plain", {"name": "Demo Plain", "template": "human-roleplay",
                                      "gender": "female", "age": 30}, create_new=True)

run = wr.create_run("build", "m", "p", "u", 80, 300000)
ctx = wt.ToolCtx(run_id=run, turn=1)

# (a)
print("(a) created location")
res = wt.run_tool(ctx, "create_location", {"data": {
    "name": "Demo Keep", "rooms": [{"name": "Hall"}, {"name": "Yard"}]}})
check("(a) create ok", res.ok and res.wrote, res)
keep = next((l for l in [get_location_by_id(e["target_id"]) for e in wr.entries(run)
                         if e.get("tool") == "create_location"] if l), {})
kid = str(keep.get("id") or "")
r1, r2 = (real_room_ids(keep) + ["?", "?"])[:2]
check("(a) two real rooms", len(real_room_ids(keep)) == 2, keep.get("rooms"))
check("(a) baseline None (create-inverse)", wr.baselines(run).get(("location", kid), "missing") is None,
      wr.baselines(run))
review(run)
check("(a) 8 steps, corridor/ground excluded",
      due(run, "location", kid) == ["building-front", "day:", "night:", f"day:{r1}", f"night:{r1}",
                                    f"day:{r2}", f"night:{r2}", "mesh"], due(run, "location", kid))
running(run)

# (b)
print("(b) room-only edit")
res = wt.run_tool(ctx, "update_location", {"id": mill_id, "patch": {"rooms": [
    {"id": hall, "image_prompt_day": "a busy hall"}, {"id": shed}]}})
check("(b) update ok", res.ok and res.wrote, res)
check("(b) baseline is a dict", isinstance(wr.baselines(run).get(("location", mill_id)), dict),
      wr.baselines(run).get(("location", mill_id)))
review(run)
check("(b) due day:<hall> only", due(run, "location", mill_id) == [f"day:{hall}"],
      due(run, "location", mill_id))

# (h) already held
print("(h) already held")
fp_now = {s.id: s.fp for s in wdm.element_steps("location", mill_id)}[f"day:{hall}"]
row = wr.add_media_row(run, "location", mill_id,
                       [{"id": f"day:{hall}", "label": "x", "status": "queued", "note": "", "fp": fp_now}])
check("(h) held step hidden", due(run, "location", mill_id) == [], due(run, "location", mill_id))
wr.update_media_row(row, status="cancelled")
check("(h) a cancelled row holds nothing", due(run, "location", mill_id) == [f"day:{hall}"],
      due(run, "location", mill_id))
wr.add_media_row(run, "location", mill_id,
                 [{"id": f"day:{hall}", "label": "x", "status": "queued", "note": "", "fp": "stale"}])
check("(h) a stale fp holds nothing", due(run, "location", mill_id) == [f"day:{hall}"],
      due(run, "location", mill_id))
running(run)

res = wt.run_tool(ctx, "update_location", {"id": mill_id, "patch": {"rooms": [
    {"id": hall, "image_prompt_day": "a calm hall"}, {"id": shed}]}})
check("(b) revert ok", res.ok and res.wrote, res)
review(run)
check("(b) back at the baseline -> nothing due", due(run, "location", mill_id) == [],
      due(run, "location", mill_id))
running(run)

# (c)
print("(c) invisible change")
res = wt.run_tool(ctx, "update_character", {"name": "Demo Plain",
                                            "patch": {"schedule": [{"hour": 8, "sleep": True}]}})
check("(c) update ok", res.ok and res.wrote, res)
check("(c) baseline is a dict", isinstance(wr.baselines(run).get(("character", "Demo Plain")), dict),
      wr.baselines(run).get(("character", "Demo Plain")))
review(run)
check("(c) nothing due", due(run, "character", "Demo Plain") == [], due(run, "character", "Demo Plain"))
running(run)

# (d)
print("(d) created characters")
res = wt.run_tool(ctx, "create_character", {"data": {
    "name": "Demo Hair", "gender": "female", "body_slots": {"hair": {"color": "red", "length": "long"}}}})
check("(d) create Demo Hair ok", res.ok and res.wrote, res)
steps = wdm.element_steps("character", "Demo Hair") or []
check("(d) hairstyle fp = the hair text",
      next((s.fp for s in steps if s.id == "hairstyle"), None) == "long red hair",
      [(s.id, s.fp) for s in steps])
_orig_on = figure_build.on_pipeline
figure_build.on_pipeline = lambda name, **kw: False if name == "Demo Lean" else _orig_on(name, **kw)
try:
    res = wt.run_tool(ctx, "create_character", {"data": {"name": "Demo Lean", "gender": "male"}})
    check("(d) create Demo Lean ok", res.ok and res.wrote, res)
    review(run)
    check("(d) on the pipeline", due(run, "character", "Demo Hair") == ["hairstyle", "portrait", "build"],
          due(run, "character", "Demo Hair"))
    check("(d) off the pipeline", due(run, "character", "Demo Lean") == ["portrait", "mesh"],
          due(run, "character", "Demo Lean"))

    # (e)
    print("(e) run switch")
    wr.set_media_enabled(run, False)
    check("(e) switch off -> []", wdm.plan(run) == [], wdm.plan(run))
    wr.set_media_enabled(run, True)
    check("(e) switch on -> listed again", due(run, "character", "Demo Lean") == ["portrait", "mesh"],
          due(run, "character", "Demo Lean"))

    # (i)
    print("(i) status gate")
    running(run)
    check("(i) running -> []", wdm.plan(run) == [], wdm.plan(run))
    review(run, "interrupted")
    check("(i) interrupted -> listed", due(run, "character", "Demo Lean") == ["portrait", "mesh"],
          due(run, "character", "Demo Lean"))
    running(run)
finally:
    figure_build.on_pipeline = _orig_on

# (f)
print("(f) fingerprint error")
_orig_steps = wdm.element_steps


def _boom(*_a, **_k):
    raise RuntimeError("fp boom")


wdm.element_steps = _boom
try:
    res = wt.run_tool(ctx, "update_location", {"id": barn["id"], "patch": {"description": "a red barn"}})
finally:
    wdm.element_steps = _orig_steps
check("(f) tool still ok", res.ok and res.wrote, res)
check("(f) baseline {}", wr.baselines(run).get(("location", barn["id"]), "missing") == {},
      wr.baselines(run).get(("location", barn["id"]), "missing"))
review(run)
check("(f) every step due", due(run, "location", barn["id"]) == ["building-front", "day:", "night:", "mesh"],
      due(run, "location", barn["id"]))
running(run)

# (g)
print("(g) create then update")
res = wt.run_tool(ctx, "create_character", {"data": {"name": "Demo Made", "gender": "female"}})
check("(g) create ok", res.ok and res.wrote, res)
check("(g) baseline None", wr.baselines(run).get(("character", "Demo Made"), "missing") is None,
      wr.baselines(run).get(("character", "Demo Made"), "missing"))
res = wt.run_tool(ctx, "update_character", {"name": "Demo Made",
                                            "patch": {"schedule": [{"hour": 9, "sleep": True}]}})
check("(g) update ok", res.ok and res.wrote, res)
check("(g) baseline still None", wr.baselines(run).get(("character", "Demo Made"), "missing") is None,
      wr.baselines(run).get(("character", "Demo Made"), "missing"))

# (j)
print("(j) the baseline read writes nothing")
save_character_profile("Demo Quiet", {"name": "Demo Quiet", "template": "human-roleplay",
                                      "gender": "male", "age": 40}, create_new=True)


def raw_config(name):
    return db.get_connection().execute(
        "SELECT config_json FROM characters WHERE name=?", (name,)).fetchone()[0]


check("(j) fixture: raw config '{}'", raw_config("Demo Quiet") == "{}", raw_config("Demo Quiet"))
wr.set_status(run, "accepted")  # one open run at a time
run_j = wr.create_run("build", "m", "p", "u", 80, 300000)
wdm.note_touch(run_j, "character", "Demo Quiet", {"op": "restore_character", "name": "Demo Quiet"})
check("(j) a dict baseline", isinstance(wr.baselines(run_j).get(("character", "Demo Quiet")), dict),
      wr.baselines(run_j))
check("(j) raw config still '{}'", raw_config("Demo Quiet") == "{}", raw_config("Demo Quiet"))

# (k)
print("(k) the unclaimed create inverse is no touch")
save_character_profile("Demo Foreign", {"name": "Demo Foreign", "template": "human-roleplay",
                                        "gender": "male", "age": 30}, create_new=True)
wdm.note_touch(run_j, "character", "Demo Foreign",
               {"op": "delete_character", "name": "Demo Foreign", "items": []})
check("(k) unclaimed -> no baseline", ("character", "Demo Foreign") not in wr.baselines(run_j),
      wr.baselines(run_j))
wdm.note_touch(run_j, "character", "Demo Foreign",
               {"op": "delete_character", "name": "Demo Foreign", "items": [], "claimed": True})
check("(k) claimed -> baseline None",
      wr.baselines(run_j).get(("character", "Demo Foreign"), "missing") is None,
      wr.baselines(run_j).get(("character", "Demo Foreign"), "missing"))

# (l)
print("(l) an item step touches its wearers")
for _nm, _extra in (("Demo Wearer", {"equipped_pieces": {"top": "item_demo_coat"}}),
                    ("Demo Hairdo", {"equipped_mesh_pieces": {"hair": "item_demo_coat"}}),
                    ("Demo Bare", {})):
    save_character_profile(_nm, {"name": _nm, "template": "human-roleplay", "gender": "male",
                                 "age": 30, **_extra}, create_new=True)
check("(l) wearers", wdm.item_wearers("item_demo_coat") == ["Demo Hairdo", "Demo Wearer"],
      wdm.item_wearers("item_demo_coat"))
wr.set_status(run_j, "accepted")
run_l = wr.create_run("build", "m", "p", "u", 80, 300000)
wdm.note_item_touch(run_l, "item_demo_coat", {"op": "restore_item", "id": "item_demo_coat"})
_bl = wr.baselines(run_l)
check("(l) wearers touched", isinstance(_bl.get(("character", "Demo Wearer")), dict)
      and isinstance(_bl.get(("character", "Demo Hairdo")), dict), _bl)
check("(l) non-wearer untouched", ("character", "Demo Bare") not in _bl, _bl)
wr.set_status(run_l, "accepted")
run_l2 = wr.create_run("build", "m", "p", "u", 80, 300000)
wdm.note_item_touch(run_l2, "item_demo_coat", {"op": "delete_items", "ids": ["item_demo_coat"]})
check("(l) create-inverse touches nobody", wr.baselines(run_l2) == {}, wr.baselines(run_l2))

# (m)
print("(m) the dressed-side-views gate reads the real setting")
from app.core import config as _config  # noqa: E402
from app.core.config_schema import field_default  # noqa: E402

_gate = wdm.CONDITIONAL_OCCASIONS[("shape", "outfit_side_draft")]
check("(m) the gate is _side_views_on", _gate is wdm._side_views_on, _gate)
check("(m) shipped default is off", field_default("base_body", "dressed_side_views") is False,
      field_default("base_body", "dressed_side_views"))
_bb = _config._CONFIG.setdefault("base_body", {})
_had, _old = "dressed_side_views" in _bb, _bb.get("dressed_side_views")
try:
    _bb.pop("dressed_side_views", None)
    check("(m) unset -> False (no raise)", wdm._side_views_on("x") is False)
    _bb["dressed_side_views"] = False
    check("(m) off -> False", wdm._side_views_on("x") is False)
    _bb["dressed_side_views"] = True
    check("(m) on -> True", wdm._side_views_on("x") is True)
finally:
    if _had:
        _bb["dressed_side_views"] = _old
    else:
        _bb.pop("dressed_side_views", None)

print("FAIL: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
