#!/usr/bin/env python3
"""Smoke: World Dev free mode — village-building guard rails (items, spacing,
boundary patch refusal, check_run gaps, world-prop room check).

A temp world (STORAGE_DIR / INSTANCE_DIR temp dirs, paths.init BEFORE any
world-DB import), an EMPTY ANIMATION_CLIPS_DIR; no server, no LLM. Every tool
call goes through ``world_dev_tools.run_tool`` exactly as the agent loop calls
it.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_guide.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

1. Item rule (create_item available without any switch; add_room_item always refused):
   - create_item succeeds without any run switch and stores the item.
   - add_room_item is always refused with ROOM_ITEM_REFUSAL
     ("room decoration is props, not items — furnish with props (find_props, place_room_prop)")
     and the room's items stay unchanged.
   - tool_list() marks add_room_item with "NOT AVAILABLE"; the create_item line
     does NOT contain "NOT AVAILABLE" and contains "never to furnish or decorate".
   - world_dev_agent._render_system() contains the add_room_item NOT AVAILABLE line.

2. Spacing report and warning (10x10 square boundary [[-5,-5],[5,-5],[5,5],[-5,5]]):
   The nearest-place info (" · nearest place <id> \"<name>\": <N> m edge to edge")
   is appended before "; warnings:" and is NOT a warning.
   - Place A at (0, 0) spans x in [-5, 5], z in [-5, 5].
   - Place B at (40, 0) spans x in [35, 45]. Edge gap to A = 35 - 5 = 30 m
     (25 < 30 <= 150) -> info "30 m edge to edge" AND warning with "30 m" and
     "3–10 m apart".
   - Place C at (-16, 0) spans x in [-21, -11]. Edge gap to A = -5 - (-11) = 6 m
     (<= 25) -> info " · nearest place <A> \"Place A\": 6 m edge to edge" and
     NO "; warnings:" at all.
   - place_location of B to (14, 0) spans x in [9, 19]. Edge gap to A = 9 - 5 = 4 m
     (gap to C = 9 - (-11) = 20 m; nearest is A at 4 m <= 25) -> info
     " · nearest place <A> \"Place A\": 4 m edge to edge" and NO "; warnings:" at all.
   - Place D at (400, 0) spans x in [395, 405]. Nearest run place is B at [9, 19],
     edge gap = 395 - 19 = 376 m (> 150) -> info "376 m edge to edge" and
     NO "; warnings:" at all.

3. update_location top-level 'boundary':
   - update_location{id: A, patch: {"boundary": [[-6,-6],[6,-6],[6,6],[-6,6]]}}
     -> refused with "use map3d.boundary"; stored boundary of A is unchanged.

4. check_run gaps:
   - Outdoor place SQ ("Demo Square") at (0, 0), boundary 20x20 [-10..10], one
     open room "Open Plaza" (x -8, y -8, w 16, d 16, open True), no props, no
     path area -> check_run lists both:
       * "no props on the open ground (place_world_prop, or place_room_prop in an open room)"
       * "entrance without a path within 10 m (add_terrain_area kind path)"
   - After place_room_prop of a bench inside "Open Plaza" -> "no props on the
     open ground" is gone.
   - After add_terrain_area kind "path" stroke [[-15, 0], [15, 0]] width_m 3
     (passes directly through SQ, distance 0 m <= 10 m) -> "entrance without a
     path within 10 m" is gone.
   - Gap c (3+ run-created placed places):
       * P1 at (0, 0), boundary 10x10 [-5..5]
       * P2 at (16, 0), boundary 10x10 [11..21] -> gap to P1 = 11 - 5 = 6 m (<= 25)
       * P3 at (66, 0), boundary 10x10 [61..71] -> gap to P2 = 61 - 21 = 40 m
         (25 < 40 <= 150). Because P3 is the 3rd run-created placed place,
         create_location emits NO per-write "houses of a village" warning
         (no double report), while check_run reports "stands 40 m from the
         nearest place of this run — a village's houses stand 3–10 m apart"
         on P3 ONLY (not on P1 or P2).
   - Gap b with an outside door on a rotated house (yaw 90):
       * House at pin (cx=200, cz=300), yaw=90 deg, boundary [[-5,-5],[5,-5],[5,5],[-5,5]]
         (world x in [195, 205], z in [295, 305]).
       * Closed room "Hall" at x=-4, y=-4, w=8, d=8, level=0. Its rect outline in
         location-local metres is [[-4,-4],[4,-4],[4,4],[-4,4]]. Edge 2 (south) runs
         from (4, 4) to (-4, 4); an outside door at at=0.5 sits at local (0, 4).
       * compose_scene(house)["doorways"] returns at_world in the location-local
         frame: [0.0, 4.0].
       * world_geometry.local_to_world(lx, lz, cx, cz, yaw_deg) is:
           wx = cx + lx * cos(yaw) + lz * sin(yaw)
           wz = cz - lx * sin(yaw) + lz * cos(yaw)
         For (lx=0, lz=4), (cx=200, cz=300), yaw=90 deg (cos=0, sin=1):
           wx = 200 + 0*0 + 4*1 = 204
           wz = 300 - 0*1 + 4*0 = 300   -> world door point = (204, 300).
       * Opposite-side path: stroke [[186, 290], [186, 310]] width_m=2 -> ribbon
         x in [185, 187], z in [290, 310]. Distance to west house rim (x=195) is
         195 - 187 = 8 m (<= 10 m), but distance to world door (204, 300) is
         204 - 187 = 17 m (> 10 m) -> gap b IS reported (the door is the entrance,
         not the rim).
       * Door-side path: stroke [[213, 299], [213, 301]] width_m=2 -> ribbon
         x in [212, 214], z in [299, 301]. Distance to world door (204, 300) is
         212 - 204 = 8 m (<= 10 m) -> gap b is GONE.
   - Gap a cleared by a world prop inside the boundary (ground-only outdoor place):
       * "Demo Meadow", indoor "outdoor", no rooms in data (ground only), at
         (500, 500), boundary [[-10,-10],[10,-10],[10,10],[-10,10]] -> world
         x in [490, 510], z in [490, 510].
       * Initial check_run lists "no props on the open ground (place_world_prop,
         or place_room_prop in an open room)" on Demo Meadow's line.
       * place_world_prop of BENCH at (520, 500): x = 520 > 510 (outside the
         [490, 510] boundary) -> gap still present on Demo Meadow's line.
       * place_world_prop of BENCH at (505, 495): 490 <= 505 <= 510 and
         490 <= 495 <= 510 (inside the boundary) -> gap gone on Demo Meadow's line.
   - 4f: a bare pin (only the ground room, no boundary) gets no open-ground gap.

5. _world_prop_warnings:
   - Place H at (100, 100), boundary 20x20 (world 90..110 x 90..110), one level-0
     room "Hall" at x -4, y -4, w 8, d 8 (world 96..104 x 96..104).
   - Point (108, 108) is inside H's outline (90..110) but outside "Hall" (96..104)
     -> warning contains "but in none of its rooms" and NOT "furnish_rooms".
   - Point (100, 100) is inside "Hall" (96..104)
     -> warning mentions "place_room_prop" and "furnish_rooms".
   - Rotated place R at pin (300, 100), yaw 90 deg, boundary 20x20
     [[-10,-10],[10,-10],[10,10],[-10,10]] (world x 290..310, z 90..110), one
     level-0 off-centre room "Hall" at x=2, y=-4, w=6, d=8 (local x 2..8, z -4..4).
     From world_geometry.local_to_world (cos 90 = 0, sin 90 = 1):
       wx = 300 + lx*0 + lz*1 = 300 + lz  -> [296, 304]
       wz = 100 - lx*1 + lz*0 = 100 - lx  -> [92, 98]
     * Point (300, 95) lies inside the rotated room [296..304] x [92..98]
       -> warning mentions "place_room_prop" and "furnish_rooms".
     * Point (306, 100) lies inside the UNROTATED room footprint [302..308] x
       [96..104] and inside R's outline [290..310] x [90..110], but OUTSIDE the
       rotated room [296..304] x [92..98]
       -> warning contains "but in none of its rooms" and NOT "furnish_rooms".
"""
from __future__ import annotations

import atexit
import copy
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_guide_clips_"))
STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_guide_"))
INSTANCE = Path(tempfile.mkdtemp(prefix="smoke_wd_guide_inst_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(INSTANCE)
for _d in (CLIPS, STORAGE, INSTANCE):
    atexit.register(shutil.rmtree, _d, ignore_errors=True)

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import config, db  # noqa: E402

config.load(paths.get_config_path())
db.init_schema()

from app.core import props  # noqa: E402
from app.core import world_dev_agent as wa  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.models.inventory import add_item, list_items  # noqa: E402
from app.models.world import get_location_by_id, list_locations  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


def call(run_id, tool, args, turn=1):
    return wt.run_tool(wt.ToolCtx(run_id=run_id, turn=turn), tool, args)


def named(name):
    return next((l for l in list_locations() if l.get("name") == name), {})


def room_id(lid, rname):
    return next((r.get("id") for r in (get_location_by_id(lid) or {}).get("rooms") or []
                 if r.get("name") == rname), "")


# ── 1. Item rule ─────────────────────────────────────────────────────────
print("1. Item rule")
PRE_ITEM = add_item(name="Demo Pre Item", category="tool")["id"]
run_items = wr.create_run("item rule", "m", "p", "u", 40, 300000)

res_loc = call(run_items, "create_location", {
    "data": {"name": "Item Guard Room", "rooms": [{"name": "Cellar"}]},
    "x": -500, "z": -500,
    "boundary": [[-5, -5], [5, -5], [5, 5], [-5, 5]]})
check("1a fixture location created", res_loc.ok and res_loc.wrote, res_loc)
IG_LID = named("Item Guard Room").get("id") or ""
IG_RID = room_id(IG_LID, "Cellar")

items_before = len(list_items())
res_ci_ok = call(run_items, "create_item", {"name": "Demo Key", "category": "tool"})
check("1b create_item ok without any switch",
      res_ci_ok.ok and res_ci_ok.wrote and len(list_items()) == items_before + 1,
      res_ci_ok)

loc_before = copy.deepcopy(get_location_by_id(IG_LID))
res_ari = call(run_items, "add_room_item", {
    "location_id": IG_LID, "room_id": IG_RID, "item_id": PRE_ITEM})
check("1c add_room_item always refused with ROOM_ITEM_REFUSAL",
      not res_ari.ok and not res_ari.wrote and wt.ROOM_ITEM_REFUSAL in res_ari.line,
      res_ari)
check("1c room items unchanged", get_location_by_id(IG_LID) == loc_before)

tl = wt.tool_list()
ari_tl = next((l for l in tl if l.startswith("add_room_item{")), "")
ci_tl = next((l for l in tl if l.startswith("create_item{")), "")
check("1d tool_list() marks add_room_item NOT AVAILABLE",
      "NOT AVAILABLE" in ari_tl and wt.ROOM_ITEM_REFUSAL in ari_tl, ari_tl)
check("1d tool_list() create_item available and says never to furnish or decorate",
      bool(ci_tl) and "NOT AVAILABLE" not in ci_tl
      and "never to furnish or decorate" in ci_tl, ci_tl)

sys_prompt = wa._render_system()
ari_sys = next((l for l in sys_prompt.splitlines() if "add_room_item{" in l), "")
check("1e _render_system() contains add_room_item NOT AVAILABLE line",
      "NOT AVAILABLE" in ari_sys and wt.ROOM_ITEM_REFUSAL in ari_sys, ari_sys)

wr.set_status(run_items, "accepted")


# ── 2. Spacing report and warning ────────────────────────────────────────
print("2. Spacing")
SQ10 = [[-5, -5], [5, -5], [5, 5], [-5, 5]]
run_sp = wr.create_run("spacing", "m", "p", "u", 40, 300000)

res_a = call(run_sp, "create_location", {
    "data": {"name": "Place A", "rooms": [{"name": "Room A"}]},
    "x": 0, "z": 0, "boundary": SQ10})
check("2a Place A created", res_a.ok and res_a.wrote, res_a)
A_ID = named("Place A").get("id") or ""

res_b = call(run_sp, "create_location", {
    "data": {"name": "Place B", "rooms": [{"name": "Room B"}]},
    "x": 40, "z": 0, "boundary": SQ10})
check("2b Place B at (40,0) has 30 m info and warns 30 m / 3–10 m apart",
      res_b.ok and f' · nearest place {A_ID} "Place A": 30 m edge to edge' in res_b.line
      and "30 m" in res_b.line and "3–10 m apart" in res_b.line, res_b)
B_ID = named("Place B").get("id") or ""

res_c = call(run_sp, "create_location", {
    "data": {"name": "Place C", "rooms": [{"name": "Room C"}]},
    "x": -16, "z": 0, "boundary": SQ10})
check("2c Place C at (-16,0) has 6 m info and NO '; warnings:'",
      res_c.ok and f' · nearest place {A_ID} "Place A": 6 m edge to edge' in res_c.line
      and "; warnings:" not in res_c.line, res_c)

res_b_mv = call(run_sp, "place_location", {"id": B_ID, "x": 14, "z": 0})
check("2d place_location B to (14,0) has 4 m info and NO '; warnings:'",
      res_b_mv.ok and f' · nearest place {A_ID} "Place A": 4 m edge to edge' in res_b_mv.line
      and "; warnings:" not in res_b_mv.line,
      res_b_mv)

res_d = call(run_sp, "create_location", {
    "data": {"name": "Place D", "rooms": [{"name": "Room D"}]},
    "x": 400, "z": 0, "boundary": SQ10})
check("2e Place D at (400,0) > 150 m has 376 m info and NO '; warnings:'",
      res_d.ok and "376 m edge to edge" in res_d.line
      and "; warnings:" not in res_d.line, res_d)


# ── 3. update_location top-level 'boundary' ──────────────────────────────
print("3. update_location top-level boundary refusal")
a_before = copy.deepcopy(get_location_by_id(A_ID))
res_bad_b = call(run_sp, "update_location", {
    "id": A_ID,
    "patch": {"boundary": [[-6, -6], [6, -6], [6, 6], [-6, 6]]}})
check("3a top-level boundary refused with 'use map3d.boundary'",
      not res_bad_b.ok and not res_bad_b.wrote
      and "use map3d.boundary" in res_bad_b.line, res_bad_b)
check("3b nothing written to Place A", get_location_by_id(A_ID) == a_before)

wr.set_status(run_sp, "accepted")


# ── 4. check_run gaps ────────────────────────────────────────────────────
print("4. check_run gaps")
BENCH = props.create_prop(name="Demo Square Bench", category="furniture",
                          width_m=2.0, depth_m=0.6, height_m=0.9, mount="floor")["id"]

run_cr = wr.create_run("check_run gaps", "m", "p", "u", 40, 300000)
res_sq = call(run_cr, "create_location", {
    "data": {"name": "Demo Square", "indoor": "outdoor",
             "rooms": [{"name": "Open Plaza"}]},
    "x": 0, "z": 200,
    "boundary": [[-10, -10], [10, -10], [10, 10], [-10, 10]]})
check("4a Demo Square created", res_sq.ok and res_sq.wrote, res_sq)
SQ_ID = named("Demo Square").get("id") or ""
PLAZA_ID = room_id(SQ_ID, "Open Plaza")

res_lay = call(run_cr, "set_room_layout", {
    "location_id": SQ_ID,
    "layout": {"rooms": [{"id": PLAZA_ID, "x": -8, "y": -8, "w": 16, "d": 16, "open": True}]}})
check("4a Open Plaza layout set", res_lay.ok and res_lay.wrote, res_lay)

OPEN_GROUND_GAP = (
    "no props on the open ground "
    "(place_world_prop, or place_room_prop in an open room)"
)
cr1 = call(run_cr, "check_run", {})
check("4a gap a (no props on the open ground) present",
      cr1.ok and OPEN_GROUND_GAP in cr1.line, cr1)
check("4b gap b (entrance without a path within 10 m) present",
      cr1.ok and "entrance without a path within 10 m (add_terrain_area kind path)" in cr1.line,
      cr1)

res_prp = call(run_cr, "place_room_prop", {
    "location_id": SQ_ID, "room_id": PLAZA_ID, "prop_id": BENCH, "x": 8, "z": 8})
check("4a bench placed in Open Plaza", res_prp.ok and res_prp.wrote, res_prp)
cr2 = call(run_cr, "check_run", {})
check("4a gap a gone after place_room_prop",
      cr2.ok and "no props on the open ground" not in cr2.line, cr2)

res_path = call(run_cr, "add_terrain_area", {
    "kind": "path", "label": "Square Path",
    "stroke": {"points": [[-15, 200], [15, 200]], "width_m": 3}})
check("4b path added", res_path.ok and res_path.wrote, res_path)
cr3 = call(run_cr, "check_run", {})
check("4b gap b gone after path area",
      cr3.ok and "entrance without a path within 10 m" not in cr3.line, cr3)

wr.set_status(run_cr, "accepted")

# Gap c: three run-created places with one 40 m away
run_c3 = wr.create_run("check_run spacing", "m", "p", "u", 40, 300000)
call(run_c3, "create_location", {
    "data": {"name": "House One", "rooms": [{"name": "R1"}]},
    "x": 0, "z": 400, "boundary": SQ10})
call(run_c3, "create_location", {
    "data": {"name": "House Two", "rooms": [{"name": "R2"}]},
    "x": 16, "z": 400, "boundary": SQ10})
res_p3 = call(run_c3, "create_location", {
    "data": {"name": "House Three", "rooms": [{"name": "R3"}]},
    "x": 66, "z": 400, "boundary": SQ10})
check("4c 3rd run-created place gets NO per-write spacing warning",
      res_p3.ok and "houses of a village" not in res_p3.line, res_p3)
cr_sp = call(run_c3, "check_run", {})
sp_lines = cr_sp.line.splitlines()
p1_line = next((l for l in sp_lines if '"House One"' in l), "")
p2_line = next((l for l in sp_lines if '"House Two"' in l), "")
p3_line = next((l for l in sp_lines if '"House Three"' in l), "")
check("4c gap c present on House Three (40 m)",
      "stands 40 m from the nearest place of this run — a village's houses stand 3–10 m apart"
      in p3_line, p3_line)
check("4c gap c absent on House One and House Two",
      "from the nearest place of this run" not in p1_line
      and "from the nearest place of this run" not in p2_line,
      (p1_line, p2_line))

wr.set_status(run_c3, "accepted")

# Gap b with outside door on a rotated house (yaw 90)
from app.core.scene_recipe import compose_scene  # noqa: E402

run_door = wr.create_run("check_run door yaw90", "m", "p", "u", 40, 300000)
res_dh = call(run_door, "create_location", {
    "data": {"name": "Rotated House", "rooms": [{"name": "Hall"}]},
    "x": 200, "z": 300, "yaw": 90, "boundary": SQ10})
check("4d Rotated House created", res_dh.ok and res_dh.wrote, res_dh)
DH_ID = named("Rotated House").get("id") or ""
DH_HALL = room_id(DH_ID, "Hall")
res_dl = call(run_door, "set_room_layout", {
    "location_id": DH_ID,
    "layout": {"rooms": [{
        "id": DH_HALL, "x": -4, "y": -4, "w": 8, "d": 8, "level": 0,
        "openings": [{"edge": 2, "at": 0.5, "width_m": 1, "type": "door", "to": "outside"}]}]}})
check("4d Rotated House layout with outside door set", res_dl.ok and res_dl.wrote, res_dl)
doorways = [d for d in compose_scene(get_location_by_id(DH_ID))["doorways"]
            if d.get("level") == 0 and d.get("outside")]
check("4d compose_scene doorway at_world is location-local [0, 4]",
      len(doorways) == 1 and doorways[0].get("at_world") == [0.0, 4.0], doorways)

res_opp = call(run_door, "add_terrain_area", {
    "kind": "path", "label": "Opposite Side Path",
    "stroke": {"points": [[186, 290], [186, 310]], "width_m": 2}})
check("4d opposite-side path added", res_opp.ok and res_opp.wrote, res_opp)
cr_opp = call(run_door, "check_run", {})
check("4d gap b STILL reported when path is only on opposite side of door",
      cr_opp.ok and "entrance without a path within 10 m (add_terrain_area kind path)"
      in cr_opp.line, cr_opp)

res_dp = call(run_door, "add_terrain_area", {
    "kind": "path", "label": "Door Side Path",
    "stroke": {"points": [[213, 299], [213, 301]], "width_m": 2}})
check("4d door-side path added", res_dp.ok and res_dp.wrote, res_dp)
cr_dp = call(run_door, "check_run", {})
check("4d gap b GONE when path is 8 m from world door (204, 300)",
      cr_dp.ok and "entrance without a path within 10 m" not in cr_dp.line, cr_dp)

wr.set_status(run_door, "accepted")

# Gap a cleared by a world prop inside the boundary (ground-only outdoor place)
run_meadow = wr.create_run("check_run meadow world prop", "m", "p", "u", 40, 300000)
res_mdw = call(run_meadow, "create_location", {
    "data": {"name": "Demo Meadow", "indoor": "outdoor"},
    "x": 500, "z": 500,
    "boundary": [[-10, -10], [10, -10], [10, 10], [-10, 10]]})
check("4e Demo Meadow created", res_mdw.ok and res_mdw.wrote, res_mdw)


def _meadow_line(cr_res):
    return next((l for l in cr_res.line.splitlines() if '"Demo Meadow"' in l), "")


cr_m1 = call(run_meadow, "check_run", {})
m1_line = _meadow_line(cr_m1)
check("4e gap a present on Demo Meadow initially",
      cr_m1.ok and OPEN_GROUND_GAP in m1_line, m1_line)

res_wp_out = call(run_meadow, "place_world_prop", {
    "prop_id": BENCH, "x": 520, "z": 500})
check("4e outside world prop at (520, 500) placed",
      res_wp_out.ok and res_wp_out.wrote, res_wp_out)
cr_m2 = call(run_meadow, "check_run", {})
m2_line = _meadow_line(cr_m2)
check("4e gap a still present after outside world prop (520, 500)",
      cr_m2.ok and OPEN_GROUND_GAP in m2_line, m2_line)

res_wp_in = call(run_meadow, "place_world_prop", {
    "prop_id": BENCH, "x": 505, "z": 495})
check("4e inside world prop at (505, 495) placed",
      res_wp_in.ok and res_wp_in.wrote, res_wp_in)
cr_m3 = call(run_meadow, "check_run", {})
m3_line = _meadow_line(cr_m3)
check("4e gap a gone on Demo Meadow after inside world prop (505, 495)",
      cr_m3.ok and OPEN_GROUND_GAP not in m3_line
      and "no props on the open ground" not in m3_line, m3_line)

wr.set_status(run_meadow, "accepted")

# 4f: a bare pin (no map3d.boundary, only the ground room) has no open room for
# place_room_prop and no plot for place_world_prop, so the open-ground gap must
# not be raised (it could never close).
from app.core.world_dev_completeness import location_gaps as _gaps
pin_gaps = _gaps({"pos_x": 0, "pos_z": 0, "indoor": "outdoor",
                  "rooms": [{"id": "__ground__"}]})
check("4f bare pin gets no open-ground gap",
      not any("no props on the open ground" in g for g in pin_gaps), pin_gaps)


# ── 5. _world_prop_warnings ──────────────────────────────────────────────
print("5. _world_prop_warnings")
run_wp = wr.create_run("world prop room check", "m", "p", "u", 40, 300000)
res_h = call(run_wp, "create_location", {
    "data": {"name": "Demo Hall", "rooms": [{"name": "Hall"}]},
    "x": 100, "z": 100,
    "boundary": [[-10, -10], [10, -10], [10, 10], [-10, 10]]})
check("5 fixture Demo Hall created", res_h.ok and res_h.wrote, res_h)
H_ID = named("Demo Hall").get("id") or ""
H_RID = room_id(H_ID, "Hall")
res_hl = call(run_wp, "set_room_layout", {
    "location_id": H_ID,
    "layout": {"rooms": [{"id": H_RID, "x": -4, "y": -4, "w": 8, "d": 8}]}})
check("5 fixture Hall laid out", res_hl.ok and res_hl.wrote, res_hl)

w_out = wt._world_prop_warnings(108.0, 108.0)
w_out_text = "; ".join(w_out)
check("5a inside outline, outside rooms: no furnish_rooms, says none of its rooms",
      "but in none of its rooms" in w_out_text and "furnish_rooms" not in w_out_text,
      w_out)

w_in = wt._world_prop_warnings(100.0, 100.0)
w_in_text = "; ".join(w_in)
check("5b inside room: mentions place_room_prop or furnish_rooms",
      "place_room_prop" in w_in_text and "furnish_rooms" in w_in_text,
      w_in)

res_r = call(run_wp, "create_location", {
    "data": {"name": "Rotated Hall", "rooms": [{"name": "Hall"}]},
    "x": 300, "z": 100, "yaw": 90,
    "boundary": [[-10, -10], [10, -10], [10, 10], [-10, 10]]})
check("5c fixture Rotated Hall created", res_r.ok and res_r.wrote, res_r)
R_ID = named("Rotated Hall").get("id") or ""
R_RID = room_id(R_ID, "Hall")
res_rl = call(run_wp, "set_room_layout", {
    "location_id": R_ID,
    "layout": {"rooms": [{"id": R_RID, "x": 2, "y": -4, "w": 6, "d": 8, "level": 0}]}})
check("5c fixture Rotated Hall off-centre room laid out", res_rl.ok and res_rl.wrote, res_rl)

w_rot_in = wt._world_prop_warnings(300.0, 95.0)
w_rot_in_text = "; ".join(w_rot_in)
check("5c (300, 95) inside rotated room: mentions place_room_prop and furnish_rooms",
      "place_room_prop" in w_rot_in_text and "furnish_rooms" in w_rot_in_text,
      w_rot_in)

w_rot_out = wt._world_prop_warnings(306.0, 100.0)
w_rot_out_text = "; ".join(w_rot_out)
check("5d (306, 100) outside rotated room, inside outline: none of its rooms, no furnish_rooms",
      "but in none of its rooms" in w_rot_out_text and "furnish_rooms" not in w_rot_out_text,
      w_rot_out)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("all checks passed")
