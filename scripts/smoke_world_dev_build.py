#!/usr/bin/env python3
"""Smoke: World Dev free mode — building contour on set_room_layout, default
floor kind in the shipped surface library, build_hull + media lane, and the
per-run ``building_models`` option ("hull" default | "mesh").

A temp world (STORAGE_DIR / INSTANCE_DIR temp dirs, paths.init BEFORE any
world-DB import), an EMPTY ANIMATION_CLIPS_DIR; no server, no LLM, no Blender
(``app.blender.runner.is_available`` and ``hull_model.generate_hull`` are
monkeypatched where needed). Every tool call goes through
``world_dev_tools.run_tool`` with a real run.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_build.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

  (1) Place "Demo House" with boundary [[-10,-8],[10,-8],[10,8],[-10,8]] and
      two closed rooms Taproom, Kitchen.
      set_room_layout places Taproom (x -8, y -6, w 8, d 6 -> [-8,0] x [-6,0])
      and Kitchen (x 0, y -6, w 4, d 6 -> [0,4] x [-6,0]) on level 0.
      Their union is ONE connected 12 x 6 rectangle [-8, 4] x [-6, 0].
      ``layout_contour._ring`` traces exterior edges clockwise in y-down space
      (top edge first, positive shoelace area), drops collinear mid-vertices
      (0,-6) and (0,0), and rotates to start at the lexicographically smallest
      (x, y) corner (-8, -6):
          map3d.outline == [[-8.0, -6.0], [4.0, -6.0], [4.0, 0.0], [-8.0, 0.0]]
      Only level 0 is occupied -> level_outlines == {}.
      All coordinates are already on exact 0.05 m ticks and aligned -> no room
      moved -> result line does NOT contain "aligned".

  (1b) Same plan with Kitchen at x 0.2, y -6, w 4, d 6 (gap 0.2 m < 0.3 m):
      ``layout_contour._clusters`` converts coordinates to 0.05 m ticks:
      Taproom x-ticks {-160, 0}, Kitchen x-ticks {4, 84}. Distinct room votes:
      -160:1, 0:1, 4:1, 84:1. Gap 4 - 0 = 4 ticks (< 6 ticks = 0.3 m), so
      [0, 4] forms one cluster; [-160] and [84] are singletons.
      Tie-break rule: ``min(run, key=lambda v: (-votes[v], v))`` -> smaller
      tick 0 (0.0 m) wins. So Kitchen's left edge snaps from 0.2 to 0.0 while
      its right edge stays at 4.2 (tick 84):
          Taproom stays x -8.0, y -6.0, w 8.0, d 6.0;
          Kitchen becomes x 0.0, y -6.0, w 4.2, d 6.0 (max delta 0.20 m).
      Result line contains "aligned" and "Kitchen"; outline is the one
      rectangle [[-8.0, -6.0], [4.2, -6.0], [4.2, 0.0], [-8.0, 0.0]].

  (1c) Kitchen at x 6, y -6, w 4, d 6 (6 m gap >= 0.3 m):
      Two disconnected components on level 0 -> ``contour_split``.
      Refused (ok False, wrote False), line contains "contour_split" and
      "own place"; stored location row is completely unchanged.

  (1d) Second place "Demo Square" with only one open room Courtyard
      (open: true, x -4, y -4, w 8, d 8):
      Open rooms (no_walls: true) are excluded from the building contour ->
      ok True, map3d.outline is empty/absent, and result line does NOT say
      "cleared" (the place never had a contour).

  (1e) Contour clearing + hull_description drop on "Demo Clear" & media gate:
      - First set_room_layout (turn 3) stores two closed rooms (RoomA, RoomB)
        -> map3d.outline is stored (non-empty).
      - build_hull (turn 3) with first sorted style id -> ok, map3d.hull_description
        stored, and ``element_steps("location", CLR_LID, "hull")`` ends with "hull".
      - Turning all rooms open (turn 10) -> ok True; stored map3d.outline,
        level_outlines AND hull_description are all absent/empty; result line
        contains "building contour cleared (no closed room left); hull request
        dropped"; ``element_steps("location", CLR_LID, "hull")`` has no "hull".
      - Undo turn 10 -> complete True; stored map3d.outline AND
        hull_description are restored by restore_location.
      - Re-clearing (turn 11): turn open (drops contour+hull), re-close
        (contour stored, NO build_hull), then turn open again -> outline
        cleared, line contains "building contour cleared (no closed room left)"
        and does NOT contain "hull request dropped".
      - Media gate on open-only place OPEN_LID (from (1d), no outline):
        write a valid map3d.hull_description directly via
        ``world_ops.update_location_with_extras`` -> ``hull_facts`` returns
        ``ok=False, error="no_outline"``, and ``element_steps("location",
        OPEN_LID, "hull")`` contains NO "hull" step (then restore OPEN_LID's
        map3d without hull_description).

  (2) Default floor kind:
      ``terrain_layers.FLOOR_KIND_DEFAULT == scene_recipe.DEFAULT_FLOOR_KIND
      == "wooden_floor"``, and ``"wooden_floor"`` is in
      ``surface_textures.library_kinds()`` (the shipped shared library).
      ``terrain_layers.floor_kind_of({}, True) == "wooden_floor"`` and
      ``terrain_layers.floor_kind_of({}, False) == ""``.
      Composing "Demo House" (from (1)) with
      ``scene_recipe.compose_scene(loc, surface_kinds=library_kinds())`` gives
      ``floor_kind == "wooden_floor"`` for every ``floor_plan`` entry of a
      closed room without surfaces.

  (3) ``build_hull`` tool + ``list_catalog hull_styles`` + ``check_run`` + undo:
      - In the default "hull" run, Demo House (closed rooms, no hull yet) has
        gap "no building hull (build_hull)" in ``check_run_lines(run)``.
      - style "nope" -> refused, line lists every style id of ``load_styles()``
        and "list_catalog hull_styles".
      - open-only place ("Demo Square") -> refused, line has
        "no building contour".
      - roof_form "dome" -> refused.
      - valid style (first sorted id of ``load_styles()``) on "Demo House"
        with ``runner.is_available`` patched True -> ok, wrote True.
        Deterministic seed = ``int(hashlib.sha256(lid.encode()).hexdigest()[:8],
        16) % 2**31``. Stored ``map3d.hull_description`` equals
        ``hull_styles.validate_description({"style": style, "seed": seed,
        "overrides": {}}, styles)``.
        After build_hull, "no building hull (build_hull)" is gone from
        ``check_run_lines(run)``.
        The journal row of the call has inverse op "restore_location".
        ``list_catalog{name: "hull_styles"}`` lists every style id.
        Repeating the same build_hull says "no change".
      - Media plan per mode on Demo House (place + 2 real rooms = 3 subjects,
        each day + night = 6 day/night steps):
        * "hull" WITH hull_description -> 7 steps (6 day/night + 1 "hull"
          with producer "location_hull"), no "building-front", no "mesh".
        * "mesh" WITH hull_description still stored -> 8 steps
          ("building-front" + 6 day/night + "mesh"), no "hull".
        * Undo turn 4 removes hull_description -> "hull" WITHOUT
          hull_description -> 6 steps (only the 6 day/night steps), no
          "building-front", no "mesh", no "hull".

  (3b) Media producer ``_produce_location_hull`` and ``step_gate``:
      Re-requesting the hull, pre-creating ``existing.glb`` in ``model_dir``,
      and monkeypatching ``hull_model.generate_hull`` to write ``hull_test.glb``
      into ``model_dir`` and return ``{"ok": True}``:
      - ``_produce_location_hull`` returns artefacts containing a "file" whose
        path ends with ``hull_test.glb``; ``existing.glb`` was passed in
        ``keep``.
      - patched ``generate_hull`` returning ``{"ok": False, "error": "x"}`` ->
        ``StepError`` with status "failed" and note containing "x".
      - ``location_model3d.claim_job(lid, kind="hull")`` held -> ``StepError``
        with status "skipped".
      - ``step_gate`` with ``runner.is_available`` patched False (and run media
        on) -> ``GATE_BLENDER_UNAVAILABLE``.
      - ``step_gate`` with ``image_generation.enabled``
        (``media_generation_enabled``) patched False, ``runner.is_available``
        patched True, and run media on -> ``None`` for the hull step.

  (4) ``building_models`` run option + system prompt:
      - Default ``create_run`` -> ``get_run(...)["building_models"] == "hull"``.
      - Closing the run, then ``create_run(..., building_models="x")`` raises
        ``ValueError``.
      - ``create_run(..., building_models="mesh")`` stores ``"mesh"``.
      - ``build_hull`` in the "mesh" run -> refused (ok False, wrote False)
        with exact text "this run builds 3D-model buildings (img2mesh); start
        a run with Buildings = Blender to build hulls".
      - Creating + laying out "Demo Mesh House" with a closed room in the
        "mesh" run -> ``check_run_lines(mesh_run)`` never reports
        "no building hull (build_hull)".
      - ``world_dev_agent._render_system("hull")`` !=
        ``world_dev_agent._render_system("mesh")`` and the "mesh" variant
        contains "img2mesh".
"""
from __future__ import annotations

import atexit
import copy
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TMP = Path(tempfile.mkdtemp(prefix="smoke_wd_build_"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
os.environ["STORAGE_DIR"] = str(TMP / "world")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")

from app.core import paths  # noqa: E402

paths.init(TMP / "world")

from app.core import db  # noqa: E402

db.init_schema()

from app.blender import runner  # noqa: E402
from app.core import hull_model, hull_styles, location_model3d  # noqa: E402
from app.core.hull_facts import hull_facts  # noqa: E402
from app.core import scene_recipe, surface_textures, terrain_layers  # noqa: E402
from app.core import world_dev_agent as wa  # noqa: E402
from app.core import world_dev_completeness as wc  # noqa: E402
from app.core import world_dev_media as wdm  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core.world_ops import update_location_with_extras  # noqa: E402
from app.imagegen import base as imagegen_base  # noqa: E402
from app.models.world import get_location_by_id, list_locations  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail=None) -> None:
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


def named(name: str):
    return next((l for l in list_locations() if l.get("name") == name), None)


def room_of(lid: str, *, name: str):
    loc = get_location_by_id(lid) or {}
    return next((r for r in loc.get("rooms") or [] if r.get("name") == name), None)


run = wr.create_run("build smoke", "m", "p", "u", 60, 600000)
check("(4) default create_run has building_models == 'hull'",
      (wr.get_run(run) or {}).get("building_models") == "hull",
      wr.get_run(run))


def call(tool: str, args: dict, turn: int, run_id: str = None):
    return wt.run_tool(wt.ToolCtx(run_id=run_id or run, turn=turn), tool, args)


# ── (1) Two closed rooms -> building contour ─────────────────────────────
print("(1) set_room_layout contour")
BOUNDARY = [[-10, -8], [10, -8], [10, 8], [-10, 8]]
res = call("create_location", {
    "data": {"name": "Demo House",
             "rooms": [{"name": "Taproom"}, {"name": "Kitchen"}],
             "map3d": {"boundary": BOUNDARY}},
    "x": 0, "z": 0,
}, turn=1)
check("(1) create Demo House ok", res.ok and res.wrote, res.line)
house = named("Demo House")
LID = house["id"]
TAP = room_of(LID, name="Taproom")["id"]
KIT = room_of(LID, name="Kitchen")["id"]

res = call("set_room_layout", {
    "location_id": LID,
    "layout": {
        "rooms": [
            {"id": TAP, "x": -8, "y": -6, "w": 8, "d": 6},
            {"id": KIT, "x": 0, "y": -6, "w": 4, "d": 6},
        ],
        "entry_room": TAP,
    },
}, turn=2)
check("(1) set_room_layout ok", res.ok and res.wrote, res.line)
loc1 = get_location_by_id(LID) or {}
m3_1 = loc1.get("map3d") or {}
check("(1) map3d.outline is 12x6 rectangle starting at (-8,-6)",
      m3_1.get("outline") == [[-8.0, -6.0], [4.0, -6.0], [4.0, 0.0], [-8.0, 0.0]],
      m3_1.get("outline"))
check("(1) map3d.level_outlines is empty",
      (m3_1.get("level_outlines") or {}) == {},
      m3_1.get("level_outlines"))
check("(1) result line has no 'aligned'", "aligned" not in res.line, res.line)

# ── (1b) Gap 0.2 m (< 0.3 m) -> aligned ─────────────────────────────────
print("(1b) alignment within 0.3 m")
res = call("set_room_layout", {
    "location_id": LID,
    "layout": {
        "rooms": [
            {"id": TAP, "x": -8, "y": -6, "w": 8, "d": 6},
            {"id": KIT, "x": 0.2, "y": -6, "w": 4, "d": 6},
        ],
    },
}, turn=3)
check("(1b) aligned layout ok", res.ok and res.wrote, res.line)
check("(1b) line mentions aligned and Kitchen",
      "aligned" in res.line and "Kitchen" in res.line, res.line)
tap_lay = (room_of(LID, name="Taproom") or {}).get("layout") or {}
kit_lay = (room_of(LID, name="Kitchen") or {}).get("layout") or {}
check("(1b) Taproom unchanged at (-8,-6,8,6)",
      (tap_lay.get("x"), tap_lay.get("y"), tap_lay.get("w"), tap_lay.get("d"))
      == (-8.0, -6.0, 8.0, 6.0), tap_lay)
check("(1b) Kitchen aligned to (0,-6,4.2,6)",
      (kit_lay.get("x"), kit_lay.get("y"), kit_lay.get("w"), kit_lay.get("d"))
      == (0.0, -6.0, 4.2, 6.0), kit_lay)
m3_1b = (get_location_by_id(LID) or {}).get("map3d") or {}
check("(1b) outline is one rectangle [-8,4.2]x[-6,0]",
      m3_1b.get("outline") == [[-8.0, -6.0], [4.2, -6.0], [4.2, 0.0], [-8.0, 0.0]],
      m3_1b.get("outline"))

# ── (1c) Gap 6 m (>= 0.3 m) -> refused ──────────────────────────────────
print("(1c) disconnected rooms refused")
before_1c = copy.deepcopy(get_location_by_id(LID))
res = call("set_room_layout", {
    "location_id": LID,
    "layout": {
        "rooms": [
            {"id": TAP, "x": -8, "y": -6, "w": 8, "d": 6},
            {"id": KIT, "x": 6, "y": -6, "w": 4, "d": 6},
        ],
    },
}, turn=3)
check("(1c) disconnected refused", (not res.ok) and (not res.wrote), res.line)
check("(1c) line names contour_split and own place",
      "contour_split" in res.line and "own place" in res.line, res.line)
check("(1c) location row unchanged", get_location_by_id(LID) == before_1c)

# ── (1d) Open-only place -> no outline, no "cleared" note ────────────────
print("(1d) open-only place has no outline")
res = call("create_location", {
    "data": {"name": "Demo Square",
             "rooms": [{"name": "Courtyard"}],
             "map3d": {"boundary": BOUNDARY}},
    "x": 40, "z": 0,
}, turn=3)
check("(1d) create Demo Square ok", res.ok and res.wrote, res.line)
OPEN_LID = named("Demo Square")["id"]
YARD = room_of(OPEN_LID, name="Courtyard")["id"]
res = call("set_room_layout", {
    "location_id": OPEN_LID,
    "layout": {"rooms": [{"id": YARD, "x": -4, "y": -4, "w": 8, "d": 8, "open": True}]},
}, turn=3)
check("(1d) open layout ok", res.ok and res.wrote, res.line)
m3_open = (get_location_by_id(OPEN_LID) or {}).get("map3d") or {}
check("(1d) open-only place has no map3d.outline", not m3_open.get("outline"), m3_open)
check("(1d) line does not say 'cleared'", "cleared" not in res.line, res.line)

# ── (1e) Turning all closed rooms open clears stored contour & hull ──────
print("(1e) clearing stored contour and hull_description + media gate")
res = call("create_location", {
    "data": {"name": "Demo Clear",
             "rooms": [{"name": "RoomA"}, {"name": "RoomB"}],
             "map3d": {"boundary": BOUNDARY}},
    "x": 80, "z": 0,
}, turn=3)
check("(1e) create Demo Clear ok", res.ok and res.wrote, res.line)
CLR_LID = named("Demo Clear")["id"]
RA = room_of(CLR_LID, name="RoomA")["id"]
RB = room_of(CLR_LID, name="RoomB")["id"]
res = call("set_room_layout", {
    "location_id": CLR_LID,
    "layout": {"rooms": [
        {"id": RA, "x": -4, "y": -4, "w": 4, "d": 4},
        {"id": RB, "x": 0, "y": -4, "w": 4, "d": 4},
    ]},
}, turn=3)
check("(1e) initial closed layout stores outline",
      res.ok and bool(((get_location_by_id(CLR_LID) or {}).get("map3d") or {}).get("outline")),
      res.line)

_clear_styles = hull_styles.load_styles()
_clear_style = sorted(_clear_styles)[0]
res = call("build_hull", {"location_id": CLR_LID, "style": _clear_style}, turn=3)
clr_m3_before = (get_location_by_id(CLR_LID) or {}).get("map3d") or {}
check("(1e) build_hull on Demo Clear ok and stores hull_description",
      res.ok and res.wrote and isinstance(clr_m3_before.get("hull_description"), dict),
      (res.line, clr_m3_before))
clr_steps_before = [s.id for s in wdm.element_steps("location", CLR_LID, "hull")]
check("(1e) element_steps ends with 'hull' before clearing",
      bool(clr_steps_before) and clr_steps_before[-1] == "hull", clr_steps_before)

res = call("set_room_layout", {
    "location_id": CLR_LID,
    "layout": {"rooms": [
        {"id": RA, "x": -4, "y": -4, "w": 4, "d": 4, "open": True},
        {"id": RB, "x": 0, "y": -4, "w": 4, "d": 4, "open": True},
    ]},
}, turn=10)
m3_clr = (get_location_by_id(CLR_LID) or {}).get("map3d") or {}
check("(1e) turning all rooms open ok", res.ok and res.wrote, res.line)
check("(1e) stored outline, level_outlines and hull_description cleared",
      not m3_clr.get("outline") and not m3_clr.get("level_outlines")
      and "hull_description" not in m3_clr, m3_clr)
check("(1e) line says building contour cleared and hull request dropped",
      "building contour cleared (no closed room left); hull request dropped" in res.line,
      res.line)
clr_steps_after = [s.id for s in wdm.element_steps("location", CLR_LID, "hull")]
check("(1e) element_steps has no 'hull' after clearing",
      "hull" not in clr_steps_after, clr_steps_after)

rep_1e = wu.undo(run, 10)
m3_clr_undone = (get_location_by_id(CLR_LID) or {}).get("map3d") or {}
check("(1e) undo turn 10 complete and restores outline + hull_description",
      rep_1e.get("complete") and bool(m3_clr_undone.get("outline"))
      and m3_clr_undone.get("hull_description") == clr_m3_before.get("hull_description"),
      (rep_1e, m3_clr_undone))

# Clear without hull: drop hull, re-close without build_hull, then reopen -> no "hull request dropped"
call("set_room_layout", {
    "location_id": CLR_LID,
    "layout": {"rooms": [
        {"id": RA, "x": -4, "y": -4, "w": 4, "d": 4, "open": True},
        {"id": RB, "x": 0, "y": -4, "w": 4, "d": 4, "open": True},
    ]},
}, turn=11)
call("set_room_layout", {
    "location_id": CLR_LID,
    "layout": {"rooms": [
        {"id": RA, "x": -4, "y": -4, "w": 4, "d": 4},
        {"id": RB, "x": 0, "y": -4, "w": 4, "d": 4},
    ]},
}, turn=11)
res = call("set_room_layout", {
    "location_id": CLR_LID,
    "layout": {"rooms": [
        {"id": RA, "x": -4, "y": -4, "w": 4, "d": 4, "open": True},
        {"id": RB, "x": 0, "y": -4, "w": 4, "d": 4, "open": True},
    ]},
}, turn=11)
check("(1e) contour clear without hull says only contour cleared",
      res.ok and "building contour cleared (no closed room left)" in res.line
      and "hull request dropped" not in res.line, res.line)

# Media gate: hull_description without outline must NOT plan a "hull" step
open_loc_before = get_location_by_id(OPEN_LID) or {}
open_m3_before = copy.deepcopy(open_loc_before.get("map3d") or {})
open_desc = hull_styles.validate_description(
    {"style": _clear_style, "seed": 1, "overrides": {}}, _clear_styles
)
update_location_with_extras(OPEN_LID, {"map3d": {**open_m3_before, "hull_description": open_desc}})
open_loc_with_hd = get_location_by_id(OPEN_LID) or {}
open_facts = hull_facts(open_loc_with_hd, OPEN_LID, description=open_desc)
check("(1e) hull_facts on open-only place with hull_description is not ok (no_outline)",
      open_facts.get("ok") is False and open_facts.get("error") == "no_outline", open_facts)
open_steps = [s.id for s in wdm.element_steps("location", OPEN_LID, "hull")]
check("(1e) element_steps skips 'hull' when hull_facts is not ok",
      "hull" not in open_steps, open_steps)
update_location_with_extras(OPEN_LID, {"map3d": open_m3_before})

# ── (2) Default floor kind ───────────────────────────────────────────────
print("(2) default floor kind")
lib_kinds = surface_textures.library_kinds()
check("(2) FLOOR_KIND_DEFAULT == DEFAULT_FLOOR_KIND == 'wooden_floor'",
      terrain_layers.FLOOR_KIND_DEFAULT == scene_recipe.DEFAULT_FLOOR_KIND == "wooden_floor",
      (terrain_layers.FLOOR_KIND_DEFAULT, scene_recipe.DEFAULT_FLOOR_KIND))
check("(2) 'wooden_floor' is in shared surface library",
      "wooden_floor" in lib_kinds, sorted(lib_kinds)[:10])
check("(2) floor_kind_of({}, True) == 'wooden_floor'",
      terrain_layers.floor_kind_of({}, True) == "wooden_floor",
      terrain_layers.floor_kind_of({}, True))
check("(2) floor_kind_of({}, False) == ''",
      terrain_layers.floor_kind_of({}, False) == "",
      terrain_layers.floor_kind_of({}, False))

composed = scene_recipe.compose_scene(loc1, surface_kinds=lib_kinds)
fp_entries = [f for f in composed.get("floor_plan") or [] if f.get("closed")]
check("(2) composed floor_plan has both closed rooms", len(fp_entries) == 2, fp_entries)
check("(2) every closed room without surfaces gets 'wooden_floor'",
      all(f.get("floor_kind") == "wooden_floor" for f in fp_entries), fp_entries)

# ── (3) build_hull tool + catalog + check_run + media plan + undo ────────
print("(3) build_hull tool, check_run, media plan per mode")
lines_before, _, _ = wc.check_run_lines(run)
house_lines_before = [l for l in lines_before if LID in l]
check("(3) check_run reports 'no building hull (build_hull)' before build_hull",
      bool(house_lines_before) and "no building hull (build_hull)" in house_lines_before[0],
      lines_before)

# Media plan in "hull" mode without hull_description: 6 day/night steps only
expected_dn = ["day:", "night:", f"day:{TAP}", f"night:{TAP}", f"day:{KIT}", f"night:{KIT}"]
steps_hull_no_desc = wdm.element_steps("location", LID, "hull")
ids_hull_no_desc = [s.id for s in steps_hull_no_desc]
check("(3) hull mode without hull_description: 6 day/night steps, no front/mesh/hull",
      ids_hull_no_desc == expected_dn, ids_hull_no_desc)

styles = hull_styles.load_styles()
style_ids = sorted(styles)
first_style = style_ids[0]

res = call("build_hull", {"location_id": LID, "style": "nope"}, turn=4)
check("(3) unknown style refused", (not res.ok) and (not res.wrote), res.line)
check("(3) unknown style lists real styles and catalog hint",
      all(sid in res.line for sid in style_ids) and "list_catalog hull_styles" in res.line,
      res.line)

res = call("build_hull", {"location_id": OPEN_LID, "style": first_style}, turn=4)
check("(3) open-only place refused (no contour)",
      (not res.ok) and "no building contour" in res.line, res.line)

res = call("build_hull", {"location_id": LID, "style": first_style, "roof_form": "dome"}, turn=4)
check("(3) invalid roof_form refused", (not res.ok) and (not res.wrote), res.line)

orig_is_available = runner.is_available
runner.is_available = lambda: True
try:
    res = call("build_hull", {"location_id": LID, "style": first_style}, turn=4)
    check("(3) valid build_hull ok", res.ok and res.wrote, res.line)
    expected_seed = int(hashlib.sha256(LID.encode()).hexdigest()[:8], 16) % 2**31
    expected_desc = hull_styles.validate_description(
        {"style": first_style, "seed": expected_seed, "overrides": {}}, styles
    )
    stored_desc = ((get_location_by_id(LID) or {}).get("map3d") or {}).get("hull_description")
    check("(3) stored map3d.hull_description matches expected",
          stored_desc == expected_desc, (stored_desc, expected_desc))

    lines_after, _, _ = wc.check_run_lines(run)
    check("(3) check_run no longer reports 'no building hull (build_hull)' for Demo House",
          not any(LID in l and "no building hull (build_hull)" in l for l in lines_after),
          lines_after)

    steps_rows = wr.steps(run)
    hull_rows = [s for s in steps_rows if s.get("tool") == "build_hull" and s.get("kind") == "write"]
    check("(3) journal row has inverse op restore_location",
          bool(hull_rows) and (hull_rows[-1].get("inverse") or {}).get("op") == "restore_location",
          hull_rows[-1] if hull_rows else None)

    media_steps_hull = wdm.element_steps("location", LID, "hull")
    step_by_id = {s.id: s for s in media_steps_hull}
    check("(3) hull mode with hull_description: 6 day/night + 1 hull (location_hull), no front/mesh",
          [s.id for s in media_steps_hull] == expected_dn + ["hull"]
          and step_by_id["hull"].producer == "location_hull",
          [(s.id, s.producer) for s in media_steps_hull])

    media_steps_mesh = wdm.element_steps("location", LID, "mesh")
    check("(3) mesh mode (even with hull_description): building-front + 6 day/night + mesh, no hull",
          [s.id for s in media_steps_mesh] == ["building-front"] + expected_dn + ["mesh"],
          [s.id for s in media_steps_mesh])

    cat_res = call("list_catalog", {"name": "hull_styles"}, turn=4)
    check("(3) list_catalog hull_styles lists every style id",
          cat_res.ok and all(sid in cat_res.line for sid in style_ids), cat_res.line)

    res_again = call("build_hull", {"location_id": LID, "style": first_style}, turn=4)
    check("(3) repeating same build_hull says 'no change'",
          res_again.ok and "no change" in res_again.line, res_again.line)

    rep = wu.undo(run, 4)
    check("(3) undo turn 4 complete", rep.get("complete"), rep)
    m3_after_undo = (get_location_by_id(LID) or {}).get("map3d") or {}
    check("(3) undo removed hull_description", "hull_description" not in m3_after_undo, m3_after_undo)
    ids_after_undo = [s.id for s in wdm.element_steps("location", LID, "hull")]
    check("(3) after undo hull mode has no hull/mesh/front",
          ids_after_undo == expected_dn, ids_after_undo)

    # ── (3b) Producer _produce_location_hull + step_gate ─────────────────
    print("(3b) producer and step_gate")
    res = call("build_hull", {"location_id": LID, "style": first_style}, turn=5)
    check("(3b) re-request build_hull ok", res.ok and res.wrote, res.line)
    hull_step = next(s for s in wdm.element_steps("location", LID, "hull") if s.id == "hull")

    mdir = location_model3d.model_dir(LID)
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "existing.glb").write_bytes(b"old-model")

    seen_keep = []
    orig_gen = hull_model.generate_hull

    def fake_gen_ok(location_id, description, *, keep=()):
        seen_keep.append(tuple(keep))
        (mdir / "hull_test.glb").write_bytes(b"new-hull")
        return {"ok": True, "error": ""}

    hull_model.generate_hull = fake_gen_ok
    try:
        ctx = wdm.ProduceCtx(run_id=run, row_id=1)
        note, arts = wdm._produce_location_hull(ctx, "location", LID, hull_step)
        check("(3b) producer returns file artefact ending with hull_test.glb",
              any(a.get("type") == "file" and str(a.get("path") or "").endswith("hull_test.glb")
                  for a in arts), arts)
        check("(3b) pre-existing file passed in keep",
              bool(seen_keep) and "existing.glb" in seen_keep[0], seen_keep)

        hull_model.generate_hull = lambda location_id, description, *, keep=(): {"ok": False, "error": "x"}
        err_failed = None
        try:
            wdm._produce_location_hull(ctx, "location", LID, hull_step)
        except wdm.StepError as exc:
            err_failed = exc
        check("(3b) generate_hull ok=False -> StepError failed",
              err_failed is not None and err_failed.status == "failed" and "x" in err_failed.note,
              err_failed)

        claimed = location_model3d.claim_job(LID, kind="hull")
        check("(3b) claim_job acquired", claimed)
        err_skipped = None
        try:
            wdm._produce_location_hull(ctx, "location", LID, hull_step)
        except wdm.StepError as exc:
            err_skipped = exc
        finally:
            location_model3d.release_job(LID, kind="hull")
        check("(3b) claim_job held -> StepError skipped",
              err_skipped is not None and err_skipped.status == "skipped", err_skipped)
    finally:
        hull_model.generate_hull = orig_gen

    wr.set_media_enabled(run, True)
    runner.is_available = lambda: False
    gate_no_blender = wdm.step_gate(run, "location", LID, hull_step)
    check("(3b) step_gate without Blender returns GATE_BLENDER_UNAVAILABLE",
          gate_no_blender == wdm.GATE_BLENDER_UNAVAILABLE, gate_no_blender)

    runner.is_available = lambda: True
    orig_media_enabled = imagegen_base.media_generation_enabled
    imagegen_base.media_generation_enabled = lambda: False
    try:
        gate_ok = wdm.step_gate(run, "location", LID, hull_step)
        check("(3b) step_gate ignores image_generation.enabled when Blender available",
              gate_ok is None, gate_ok)
    finally:
        imagegen_base.media_generation_enabled = orig_media_enabled

    # ── (4) building_models = "mesh" run + validation + system prompt ────
    print("(4) building_models option and system prompt")
    wr.set_status(run, "accepted")
    bad_err = None
    try:
        wr.create_run("bad bm", "m", "p", "u", 60, 600000, building_models="x")
    except ValueError as exc:
        bad_err = exc
    check("(4) create_run with invalid building_models raises ValueError",
          bad_err is not None, bad_err)

    mesh_run = wr.create_run("mesh smoke", "m", "p", "u", 60, 600000, building_models="mesh")
    check("(4) create_run(..., building_models='mesh') stores 'mesh'",
          (wr.get_run(mesh_run) or {}).get("building_models") == "mesh",
          wr.get_run(mesh_run))

    res_mesh_hull = call("build_hull", {"location_id": LID, "style": first_style},
                         turn=1, run_id=mesh_run)
    expected_refusal = (
        "this run builds 3D-model buildings (img2mesh); start a run with "
        "Buildings = Blender to build hulls"
    )
    check("(4) build_hull in mesh run refused with exact message",
          (not res_mesh_hull.ok) and (not res_mesh_hull.wrote)
          and expected_refusal in res_mesh_hull.line,
          res_mesh_hull.line)

    res = call("create_location", {
        "data": {"name": "Demo Mesh House",
                 "rooms": [{"name": "Hall"}],
                 "map3d": {"boundary": BOUNDARY}},
        "x": 120, "z": 0,
    }, turn=1, run_id=mesh_run)
    check("(4) create Demo Mesh House ok", res.ok and res.wrote, res.line)
    MLID = named("Demo Mesh House")["id"]
    MHALL = room_of(MLID, name="Hall")["id"]
    res = call("set_room_layout", {
        "location_id": MLID,
        "layout": {"rooms": [{"id": MHALL, "x": -4, "y": -4, "w": 8, "d": 8}]},
    }, turn=1, run_id=mesh_run)
    check("(4) set_room_layout in mesh run ok", res.ok and res.wrote, res.line)
    mesh_lines, _, _ = wc.check_run_lines(mesh_run)
    check("(4) check_run in mesh run never reports 'no building hull (build_hull)'",
          not any("no building hull (build_hull)" in l for l in mesh_lines),
          mesh_lines)

    sys_hull = wa._render_system("hull")
    sys_mesh = wa._render_system("mesh")
    check("(4) _render_system('hull') != _render_system('mesh')",
          sys_hull != sys_mesh)
    check("(4) _render_system('mesh') mentions img2mesh",
          "img2mesh" in sys_mesh)
finally:
    runner.is_available = orig_is_available

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {failures}")
    sys.exit(1)
print("all checks passed")
