#!/usr/bin/env python3
"""Smoke: World Dev free mode — placement checks and a readable map (gaps 18, 20; E9).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p2-buildings-terrain.md, Task 2.
A temp world (paths.init BEFORE any world-DB import), an EMPTY ANIMATION_CLIPS_DIR;
no server, no LLM. Every tool call goes through ``world_dev_tools.run_tool`` exactly
as the agent loop calls it.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_placement.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Terrain kinds: the shipped catalog (shared/terrain/types.json, no world rows in
a temp world). IMP = the FIRST kind of ``effective_catalog()`` with
``passable: false`` — read once at runtime; with today's types.json that is
"deep_water" (name "Deep water", passable false, meta.water true, speed 0.4).
"grass" (name "Grass") is passable, no water flag, speed_factor 1 — every flag
at its default. The default ground (config game.default_terrain_kind) is
"grass", so a point no area covers is walkable.

Fixtures written through the terrain core BEFORE the run (so the undo never
touches them):
  F_IMP  kind IMP, polygon [[0,0],[40,0],[40,40],[0,40]], z_order 1.
  F_GRW  kind "grass", polygon [[150,150],[160,150],[160,160],[150,160]],
         meta.label "Demo Grove" (an area with NPC slots needs one), meta.scatter =
         one entry, meta.npc_slots = one slot (role "Demo Guard").

Seed outline: create_location without a boundary stores the 10 m square
(map_layout_apply.SEED_BOUNDARY_M = 10) centred on its pin, so a pin at
(100,100) spans x 95…105, z 95…105 (third run: the stored square, and a place
without a stored outline is its pin only).

Pure helpers (map_layout_apply), entries {name, pos_x, pos_z, yaw_deg,
boundary = seed square}: A at (0,0) spans -5…5, B at (5,0) spans 0…10 (shares
x 0…5 with A), C at (50,0) spans 45…55 (touches neither).
  (p1) overlap_warnings([C], others=[A, B]) == [] — the A/B pair lies inside
       others and is never reported; C overlaps nobody.
  (p2) overlap_warnings([B], others=[A]) == [{code footprint_overlap, ref
       locations[0], message "'A' and 'B' overlap — their outlines share
       ground."}] (the text sanitize_map_layout has always used).
  (p3) impassable_warning(X at (20,20), "locations[0]", areas [F_IMP]) ->
       {code on_impassable, message "'X' stands on '<IMP>', which nobody can
       walk on — the place would be unreachable."}; X at (100,100) -> None.
  (p4) placement_warnings([X2 at (2,2)], others=[A], areas [F_IMP]): X2 lies
       inside F_IMP (0…40) and spans -3…7, sharing -3…5 with A, so the codes
       are [on_impassable, footprint_overlap] in that order (impassable per
       entry first, as in the per-location loop; overlaps at the end).

Tool cases, one run:
  (a) create_location Demo Hut at (20,20) -> refused, line has "which nobody
      can walk on"; no place named Demo Hut; every journal row so far is
      "refused".
  (b) create_location Demo Hut at (100,100) -> ok, no "; warnings:" in the line.
  (c) create_location Demo Barn at (105,100): spans 100…110 x 95…105, shares
      x 100…105 with the hut -> ok, the line has
      "'Demo Barn' overlaps place <hut id> \"Demo Hut\"" (the free tools name
      the stored place by id; the sanitizer's text stays as in (p2)).
  (d) place_location{hut, 20, 20} -> refused ("which nobody can walk on"); the
      hut stays at (100,100).
  (e) add_terrain_area kind IMP polygon [[90,90],[110,90],[110,110],[90,110]]
      (covers both pins (100,100) and (105,100), z_order 0, above the default
      grass) -> ok; the line has 'place <hut> "Demo Hut" now stands on <IMP>'
      and 'place <barn> "Demo Barn" now stands on <IMP>'.
  (f) map_region{-10,-10,200,200} -> the hut line has "outline
      (95,95)-(105,105)" (the corner format of _fmt_box) and "on <IMP>"; the
      F_GRW line has " · scatter 1" and " · slots 1"; the F_IMP line has none
      of them.
  (g) world_overview -> the terrain line has '<IMP> "<IMP name>" (impassable'
      and 'grass "Grass"' NOT followed by " (" (no flag at default).
  (h) discard_preview names the hut, the barn and the (e) area; undo(run) ->
      complete, no place Demo Hut / Demo Barn, the (e) area is gone, the two
      fixtures remain.

Second run (all far from the fixtures, which cover 0…40 and 150…160):
  (i) create_location Demo Stall at (600,300), then a SECOND Demo Stall at
      (700,300) -> both ok, no overlap (seed squares 595…605 and 695…705); the
      second carries only the same-name warning.
      place_location{second stall, 605, 300}: it spans 600…610, sharing
      600…605 with the first -> ok, the line has
      "overlaps place <first stall id> \"Demo Stall\"" — the id tells the two
      same-named places apart.
  (j) create_location Demo Well at (500,500) -> ok. add_terrain_area kind grass
      polygon [[490,490],[510,490],[510,510],[490,510]] label "Demo Meadow": the
      pin was on the default grass and is on grass -> no "now stands on".
      update_terrain_area{area, label "Demo Lawn"} -> no "now stands on" (kind
      unchanged). update_terrain_area{area, kind IMP} -> 'place <well> "Demo
      Well" now stands on <IMP>'. update_terrain_area{area, label "Demo Pool"}
      -> no "now stands on": the pin was on IMP and stays on IMP (silent
      same-kind case).
  (k) create_location Demo Tower at (300,300) yaw 45 with boundary
      [[-20,-20],[20,-20],[20,20],[-20,20]] (a 40 m square). Turned 45° its
      corners lie on the axes at 20·√2 = 28.2843 m from the pin, so the world
      bbox is 300 ± 28.2843 -> map_region shows
      "outline (271.716,271.716)-(328.284,328.284)" (_g = 6 significant
      digits). The turned square is the diamond |dx| + |dz| <= 28.2843:
      Demo Shed at (325,300) spans x 320…330, z 295…305 and contains the point
      (320,300) with |dx|+|dz| = 20 -> its line has
      "overlaps place <tower id> \"Demo Tower\"". Demo Kiosk at (330,320)
      spans 325…335 x 315…325; its nearest corner (325,315) has
      |dx|+|dz| = 25 + 15 = 40 > 28.28, so it shares no ground although its
      square lies inside the tower's bbox -> no "; warnings:" (the exact
      polygon test, not the box).
  (l) fixture F_ALONG written through the terrain core: kind "path", polygon
      [[800,795],[860,795],[860,805],[800,805]], meta.stroke {points
      [[800,800],[860,800]], width_m 10, along [one row, spacing_m 20]} ->
      map_region{790,790,870,810} shows its line with " · along 1" and no
      " · scatter" / " · slots".
  (n) acceptance follow-ups (same run 2):
      (n1) the well stands on IMP since (j). place_location{well, 500, 500,
           yaw 90} (same x/z, a turn in place) -> ok, yaw_deg 90 stored, no
           "which nobody can walk on" (the pin keeps its ground).
           place_location{well, 501, 500} (still inside the 490…510 meadow,
           a real move) -> refused with "which nobody can walk on".
      (n2) create_location Demo Hall at (400,300): seed square 395…405 x
           295…305, far from the tower diamond (|dx| = 100 - 5 > 28.28) and
           the shed (320…330) -> no "; warnings:". update_location{hall,
           patch {description}} -> no "overlaps" (the outline is unchanged).
           update_location{hall, patch {map3d {boundary [[-80,-5],[-60,-5],
           [-60,5],[-80,5]]}}}: yaw 0, so it spans x 320…340, z 295…305. It
           contains (320,300), |dx|+|dz| = 20 <= 28.28 from the tower pin,
           and shares x 320…330 with the shed -> the line has
           'overlaps place <tower> "Demo Tower"' and
           'overlaps place <shed> "Demo Shed"'.
      (n3) add_terrain_area grass z_order 5 polygon [[495,495],[505,495],
           [505,505],[495,505]] (an island over the IMP meadow, under the
           well's pin) -> ok, no "now stands on" (grass is walkable).
           delete_created{terrain, island} in the SAME turn -> the line has
           'place <well> "Demo Well" now stands on <IMP>'. The same island
           added in turn 6 and deleted in turn 7 (the earlier-turn path) ->
           the same warning.
      (n4) a ring whose points lie on one line encloses no area:
           create_location with boundary [[0,0],[5,0],[10,0]] and
           add_terrain_area with polygon [[0,0],[5,0],[10,0]] -> both
           refused with "encloses no area".
  (m) undo(run 2) -> complete, no place of run 2 left, the run-2 area gone.

Third run — F9 (plan docs/superpowers/plans/2026-11-25-world-dev-free-fixes.md,
Task 11): create_location STORES the seed square when no boundary is given, and
a place without a stored boundary (made elsewhere) is judged as its pin only —
it has no area on the map (world_geometry.effective_boundary). Everything lies
far east of the fixtures (x >= 1000, default grass ground). Seed square =
SEED_BOUNDARY_M (10) centred on the pin, ±5 m.
  (o1) create_location Demo Barn at (1100,100), no boundary -> ok; the stored
       map3d.boundary == mla.seed_boundary(), map3d.plan_width_m == 10; the
       line has "outline: 10 m square (no boundary given)".
  (o2) Demo Pin upserted directly at (1000,0) WITHOUT map3d (no outline).
       create_location Demo Cart at (1008,0), no boundary: it spans x
       1003…1013, z -5…5. The pin (1000,0) lies outside that and has no area
       -> no "; warnings:" (before: the pin's assumed seed 995…1005 shared
       x 1003…1005 with the cart and warned).
       map_region{990,-10,1020,10}: the Demo Pin line has no "outline" and
       " · on grass"; the cart line has "outline (1003,-5)-(1013,5)".
  (o3) Demo Post upserted at (2000,0) without map3d. create_location Demo
       Gate at (2008,0) WITH boundary [[-10,-1],[10,-1],[10,1],[-10,1]]: it
       spans x 1998…2018, z -1…1 and contains the post's pin -> still no
       "; warnings:" (a pin has no area to share).
  (o4) Demo Shop at (1300,0) and Demo Inn at (1308,0), both without boundary:
       stored squares 1295…1305 and 1303…1313 share x 1303…1305 -> the inn's
       line has 'overlaps place <shop id> "Demo Shop"'.
  (o5) undo(run 3) -> complete; Barn, Cart, Gate, Shop, Inn gone; Demo Pin
       and Demo Post (not the run's) stay unchanged.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_place_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_place_"))
paths.init(STORAGE)
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)

from app.core import config, db  # noqa: E402

config.load(paths.get_config_path())
db.init_schema()

from app.core import map_layout_apply as mla  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core.terrain_types import effective_catalog  # noqa: E402
from app.models import terrain  # noqa: E402
from app.models.world import get_location_by_id, list_locations  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


CATALOG = effective_catalog()
IMP = next((k for k, e in CATALOG.items() if not e.get("passable", True)), "")
check("fixture: the shipped catalog has an impassable kind", bool(IMP), CATALOG)
IMP_NAME = str((CATALOG.get(IMP) or {}).get("name") or IMP)
check("fixture: grass is a default-flag kind",
      CATALOG.get("grass", {}).get("passable") is True
      and float(CATALOG.get("grass", {}).get("speed_factor", 1)) == 1.0
      and not (CATALOG.get("grass", {}).get("meta") or {}).get("water"),
      CATALOG.get("grass"))

F_IMP = terrain.save_area({"id": "ta_fix_imp", "kind": IMP, "z_order": 1,
                           "polygon": [[0, 0], [40, 0], [40, 40], [0, 40]]})["id"]
F_GRW = terrain.save_area({
    "id": "ta_fix_grove", "kind": "grass",
    "polygon": [[150, 150], [160, 150], [160, 160], [150, 160]],
    "meta": {"label": "Demo Grove", "scatter": [{"model": "/assets/props/demo_tree/model", "density": 0.01}],
             "npc_slots": [{"role": "Demo Guard"}]}})["id"]
grove = terrain.get_area(F_GRW) or {}
check("fixture: grove keeps 1 scatter entry and 1 slot",
      len((grove.get("meta") or {}).get("scatter") or []) == 1
      and len((grove.get("meta") or {}).get("npc_slots") or []) == 1, grove)

# ── Pure helpers ─────────────────────────────────────────────────────────
SEED = mla.seed_boundary()


def ent(name, x, z):
    return {"name": name, "pos_x": x, "pos_z": z, "yaw_deg": 0.0, "boundary": SEED}


A, B, C = ent("A", 0, 0), ent("B", 5, 0), ent("C", 50, 0)
check("(p1) pairs inside others are never reported",
      mla.overlap_warnings([C], others=[A, B]) == [],
      mla.overlap_warnings([C], others=[A, B]))
check("(p2) a new entry against a stored one",
      mla.overlap_warnings([B], others=[A]) == [{
          "code": "footprint_overlap", "ref": "locations[0]",
          "message": "'A' and 'B' overlap — their outlines share ground."}],
      mla.overlap_warnings([B], others=[A]))
imp_areas = [terrain.get_area(F_IMP)]
w = mla.impassable_warning(ent("X", 20, 20), "locations[0]", catalog=CATALOG,
                           areas=imp_areas, default_kind="grass")
check("(p3) on impassable ground", w == {
    "code": "on_impassable", "ref": "locations[0]",
    "message": f"'X' stands on {IMP!r}, which nobody can walk on — the place "
               f"would be unreachable."}, w)
check("(p3) walkable ground -> None",
      mla.impassable_warning(ent("X", 100, 100), "locations[0]", catalog=CATALOG,
                             areas=imp_areas, default_kind="grass") is None)
ws = mla.placement_warnings([ent("X2", 2, 2)], catalog=CATALOG, areas=imp_areas,
                            default_kind="grass", others=[A])
check("(p4) impassable first, overlaps at the end",
      [x["code"] for x in ws] == ["on_impassable", "footprint_overlap"], ws)

# ── Tool cases ───────────────────────────────────────────────────────────
run = wr.create_run("placement", "m", "p", "u", 40, 300000)


def call(turn, tool, args):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


def named(name):
    return [l for l in list_locations() if l.get("name") == name]


# (a)
res = call(1, "create_location", {"data": {"name": "Demo Hut", "rooms": [{"name": "Room"}]},
                                  "x": 20, "z": 20})
check("(a) refused", not res.ok and not res.wrote, res)
check("(a) line names the impassable ground", "which nobody can walk on" in res.line, res.line)
check("(a) no place Demo Hut", not named("Demo Hut"))
check("(a) only refused journal rows",
      [s["kind"] for s in wr.steps(run)] == ["refused"], wr.steps(run))

# (b)
res = call(1, "create_location", {"data": {"name": "Demo Hut", "rooms": [{"name": "Room"}]},
                                  "x": 100, "z": 100})
check("(b) ok", res.ok and res.wrote, res)
check("(b) no warning", "; warnings:" not in res.line, res.line)
HUT = (named("Demo Hut") or [{}])[0].get("id") or ""

# (c)
res = call(1, "create_location", {"data": {"name": "Demo Barn", "rooms": [{"name": "Stall"}]},
                                  "x": 105, "z": 100})
check("(c) ok", res.ok and res.wrote, res)
BARN = (named("Demo Barn") or [{}])[0].get("id") or ""
check("(c) overlap warned with the stored place's id",
      f"'Demo Barn' overlaps place {HUT} \"Demo Hut\"" in res.line, res.line)

# (d)
before = get_location_by_id(HUT)
n_before = len(wr.steps(run))
res = call(2, "place_location", {"id": HUT, "x": 20, "z": 20})
check("(d) refused", not res.ok and not res.wrote, res)
check("(d) line names the impassable ground", "which nobody can walk on" in res.line, res.line)
check("(d) journal row refused",
      len(wr.steps(run)) == n_before + 1 and wr.steps(run)[-1]["kind"] == "refused")
hut = get_location_by_id(HUT) or {}
check("(d) hut still at (100,100)",
      (hut.get("pos_x"), hut.get("pos_z")) == (100, 100) and hut == before,
      (hut.get("pos_x"), hut.get("pos_z")))

# (e)
res = call(3, "add_terrain_area", {"kind": IMP,
                                   "polygon": [[90, 90], [110, 90], [110, 110], [90, 110]]})
check("(e) ok", res.ok and res.wrote, res)
check("(e) hut named", f'place {HUT} "Demo Hut" now stands on {IMP}' in res.line, res.line)
check("(e) barn named", f'place {BARN} "Demo Barn" now stands on {IMP}' in res.line, res.line)
check("(e) which nobody can walk on", "which nobody can walk on" in res.line, res.line)
AREA = next((a["id"] for a in terrain.list_areas()
             if a["id"] not in (F_IMP, F_GRW)), "")

# (f)
res = call(4, "map_region", {"min_x": -10, "min_z": -10, "max_x": 200, "max_z": 200})
lines = res.line.split("\n")
hut_line = next((l for l in lines if l.startswith(f"place {HUT} ")), "")
check("(f) hut outline", "outline (95,95)-(105,105)" in hut_line, hut_line)
check("(f) hut ground", f"on {IMP}" in hut_line, hut_line)
grw_line = next((l for l in lines if l.startswith(f"terrain {F_GRW} ")), "")
check("(f) grove scatter + slots", " · scatter 1" in grw_line and " · slots 1" in grw_line,
      grw_line)
imp_line = next((l for l in lines if l.startswith(f"terrain {F_IMP} ")), "")
check("(f) plain area has no extras",
      bool(imp_line) and not any(t in imp_line for t in (" · scatter", " · along", " · slots")),
      imp_line)

# (g)
res = call(4, "world_overview", {})
kinds_line = next((l for l in res.line.split("\n") if l.startswith("terrain kinds:")), "")
check("(g) impassable flag", f'{IMP} "{IMP_NAME}" (impassable' in kinds_line, kinds_line)
check("(g) default kind without flags",
      'grass "Grass"' in kinds_line and 'grass "Grass" (' not in kinds_line, kinds_line)

# (h)
prev = wu.discard_preview(run)
check("(h) preview names hut, barn and the area",
      sum("Demo Hut" in ln for ln in prev) == 1 and sum("Demo Barn" in ln for ln in prev) == 1
      and sum(AREA in ln for ln in prev) == 1 and len(prev) == 3, prev)
rep = wu.undo(run)
check("(h) undo complete", rep["complete"], rep)
check("(h) no places left", not named("Demo Hut") and not named("Demo Barn"))
ids = {a["id"] for a in terrain.list_areas()}
check("(h) run area gone, fixtures kept", ids == {F_IMP, F_GRW}, ids)

# ── Second run ───────────────────────────────────────────────────────────
wr.set_status(run, "rolled_back")  # one open run at a time
run = wr.create_run("placement2", "m", "p", "u", 40, 300000)

# (i)
res = call(1, "create_location", {"data": {"name": "Demo Stall", "rooms": [{"name": "Room"}]},
                                  "x": 600, "z": 300})
check("(i) first stall ok, no warning", res.ok and "; warnings:" not in res.line, res)
STALL1 = (named("Demo Stall") or [{}])[0].get("id") or ""
res = call(1, "create_location", {"data": {"name": "Demo Stall", "rooms": [{"name": "Room"}]},
                                  "x": 700, "z": 300})
check("(i) second stall ok, no overlap, a same-name warning",
      res.ok and "overlap" not in res.line and "already exists" in res.line, res)
STALL2 = next((l["id"] for l in named("Demo Stall") if l["id"] != STALL1), "")
check("(i) two stalls", bool(STALL1) and bool(STALL2) and len(named("Demo Stall")) == 2)
res = call(2, "place_location", {"id": STALL2, "x": 605, "z": 300})
check("(i) place_location ok", res.ok and res.wrote, res)
check("(i) overlap names the first stall by id",
      f'overlaps place {STALL1} "Demo Stall"' in res.line, res.line)

# (j)
res = call(3, "create_location", {"data": {"name": "Demo Well", "rooms": [{"name": "Room"}]},
                                  "x": 500, "z": 500})
check("(j) well ok", res.ok, res)
WELL = (named("Demo Well") or [{}])[0].get("id") or ""
res = call(3, "add_terrain_area", {"kind": "grass", "label": "Demo Meadow",
                                   "polygon": [[490, 490], [510, 490], [510, 510], [490, 510]]})
check("(j) grass area ok, no ground warning", res.ok and "now stands on" not in res.line, res)
MEADOW = next((a["id"] for a in terrain.list_areas()
               if (a.get("meta") or {}).get("label") == "Demo Meadow"), "")
res = call(3, "update_terrain_area", {"id": MEADOW, "label": "Demo Lawn"})
check("(j) relabel ok, no ground warning", res.ok and "now stands on" not in res.line, res)
res = call(3, "update_terrain_area", {"id": MEADOW, "kind": IMP})
check("(j) kind change warns",
      res.ok and f'place {WELL} "Demo Well" now stands on {IMP}' in res.line, res)
res = call(3, "update_terrain_area", {"id": MEADOW, "label": "Demo Pool"})
check("(j) same impassable kind stays silent", res.ok and "now stands on" not in res.line, res)

# (k)
res = call(4, "create_location", {"data": {"name": "Demo Tower", "rooms": [{"name": "Room"}]},
                                  "x": 300, "z": 300, "yaw": 45,
                                  "boundary": [[-20, -20], [20, -20], [20, 20], [-20, 20]]})
check("(k) tower ok", res.ok, res)
TOWER = (named("Demo Tower") or [{}])[0].get("id") or ""
res = call(4, "map_region", {"min_x": 290, "min_z": 290, "max_x": 310, "max_z": 310})
tower_line = next((l for l in res.line.split("\n") if l.startswith(f"place {TOWER} ")), "")
check("(k) turned outline box", "outline (271.716,271.716)-(328.284,328.284)" in tower_line,
      tower_line)
res = call(4, "create_location", {"data": {"name": "Demo Shed", "rooms": [{"name": "Room"}]},
                                  "x": 325, "z": 300})
check("(k) shed overlaps the turned tower",
      res.ok and f'overlaps place {TOWER} "Demo Tower"' in res.line, res)
res = call(4, "create_location", {"data": {"name": "Demo Kiosk", "rooms": [{"name": "Room"}]},
                                  "x": 330, "z": 320})
check("(k) kiosk inside the bbox but off the diamond: no warning",
      res.ok and "; warnings:" not in res.line, res)

# (l)
F_ALONG = terrain.save_area({
    "id": "ta_fix_along", "kind": "path",
    "polygon": [[800, 795], [860, 795], [860, 805], [800, 805]],
    "meta": {"stroke": {"points": [[800, 800], [860, 800]], "width_m": 10,
                        "along": [{"spacing_m": 20}]}}})["id"]
res = call(5, "map_region", {"min_x": 790, "min_z": 790, "max_x": 870, "max_z": 810})
al_line = next((l for l in res.line.split("\n") if l.startswith(f"terrain {F_ALONG} ")), "")
check("(l) along row counted",
      " · along 1" in al_line and " · scatter" not in al_line and " · slots" not in al_line,
      al_line)

# (n1)
res = call(5, "place_location", {"id": WELL, "x": 500, "z": 500, "yaw": 90})
check("(n1) a turn in place on impassable ground is ok",
      res.ok and res.wrote and "which nobody can walk on" not in res.line, res)
check("(n1) yaw stored", float((get_location_by_id(WELL) or {}).get("yaw_deg") or 0) == 90.0,
      get_location_by_id(WELL))
res = call(5, "place_location", {"id": WELL, "x": 501, "z": 500})
check("(n1) a real move onto impassable ground is refused",
      not res.ok and "which nobody can walk on" in res.line, res)

# (n2)
res = call(5, "create_location", {"data": {"name": "Demo Hall", "rooms": [{"name": "Room"}]},
                                  "x": 400, "z": 300})
check("(n2) hall ok, no warning", res.ok and "; warnings:" not in res.line, res)
HALL = (named("Demo Hall") or [{}])[0].get("id") or ""
SHED = (named("Demo Shed") or [{}])[0].get("id") or ""
res = call(5, "update_location", {"id": HALL, "patch": {"description": "A demo hall."}})
check("(n2) no outline change, no overlap check", res.ok and "overlaps" not in res.line, res)
res = call(5, "update_location", {"id": HALL, "patch": {"map3d": {
    "boundary": [[-80, -5], [-60, -5], [-60, 5], [-80, 5]]}}})
check("(n2) new outline overlaps the tower",
      res.ok and f'overlaps place {TOWER} "Demo Tower"' in res.line, res)
check("(n2) new outline overlaps the shed",
      res.ok and f'overlaps place {SHED} "Demo Shed"' in res.line, res)

# (n3)
ISLAND = [[495, 495], [505, 495], [505, 505], [495, 505]]


def island(turn):
    known = {a["id"] for a in terrain.list_areas()}
    r = call(turn, "add_terrain_area", {"kind": "grass", "z_order": 5, "polygon": ISLAND})
    return r, next((a["id"] for a in terrain.list_areas() if a["id"] not in known), "")


res, ISL = island(5)
check("(n3) island ok, no ground warning", res.ok and "now stands on" not in res.line, res)
res = call(5, "delete_created", {"kind": "terrain", "id": ISL})
check("(n3) same-turn delete warns about the bared pin",
      res.ok and f'place {WELL} "Demo Well" now stands on {IMP}' in res.line, res)
res, ISL = island(6)
check("(n3) second island ok", res.ok and bool(ISL), res)
res = call(7, "delete_created", {"kind": "terrain", "id": ISL})
check("(n3) earlier-turn delete warns about the bared pin",
      res.ok and f'place {WELL} "Demo Well" now stands on {IMP}' in res.line, res)

# (n4)
res = call(7, "create_location", {"data": {"name": "Demo Line", "rooms": [{"name": "Room"}]},
                                  "x": 900, "z": 900,
                                  "boundary": [[0, 0], [5, 0], [10, 0]]})
check("(n4) collinear boundary refused",
      not res.ok and "encloses no area" in res.line and not named("Demo Line"), res)
res = call(7, "add_terrain_area", {"kind": "grass", "polygon": [[0, 0], [5, 0], [10, 0]]})
check("(n4) collinear polygon refused", not res.ok and "encloses no area" in res.line, res)

# (m)
rep = wu.undo(run)
check("(m) undo complete", rep["complete"], rep)
check("(m) no run-2 place left",
      not any(named(n) for n in ("Demo Stall", "Demo Well", "Demo Tower", "Demo Shed",
                                 "Demo Kiosk", "Demo Hall")))
ids = {a["id"] for a in terrain.list_areas()}
check("(m) run-2 area gone, fixtures kept", ids == {F_IMP, F_GRW, F_ALONG}, ids)

# ── Third run: F9 — the seed square is stored, outline-less places are pins ──
wr.set_status(run, "rolled_back")
run = wr.create_run("placement3", "m", "p", "u", 40, 300000)
from app.models.world import upsert_location  # noqa: E402

# (o1)
res = call(1, "create_location", {"data": {"name": "Demo Barn", "rooms": [{"name": "Room"}]},
                                  "x": 1100, "z": 100})
check("(o1) ok", res.ok and res.wrote, res)
barn = (named("Demo Barn") or [{}])[0]
check("(o1) seed square stored", (barn.get("map3d") or {}).get("boundary") == SEED,
      barn.get("map3d"))
check("(o1) plan width 10", float((barn.get("map3d") or {}).get("plan_width_m") or 0) == 10.0,
      barn.get("map3d"))
check("(o1) line names the seed outline",
      "outline: 10 m square (no boundary given)" in res.line, res.line)

# (o2)
upsert_location({"id": "loc_demo_pin", "name": "Demo Pin", "pos_x": 1000.0, "pos_z": 0.0,
                 "yaw_deg": 0.0}, sync_world=False)
PIN_BEFORE = get_location_by_id("loc_demo_pin")
check("(o2) fixture pin has no outline",
      not ((PIN_BEFORE or {}).get("map3d") or {}).get("boundary"), PIN_BEFORE)
res = call(1, "create_location", {"data": {"name": "Demo Cart", "rooms": [{"name": "Room"}]},
                                  "x": 1008, "z": 0})
check("(o2) cart ok, no warning (a pin has no area)",
      res.ok and "; warnings:" not in res.line, res)
CART = (named("Demo Cart") or [{}])[0].get("id") or ""
res = call(1, "map_region", {"min_x": 990, "min_z": -10, "max_x": 1020, "max_z": 10})
lines = res.line.split("\n")
pin_line = next((l for l in lines if l.startswith("place loc_demo_pin ")), "")
check("(o2) pin line without outline",
      bool(pin_line) and "outline" not in pin_line and " · on grass" in pin_line, pin_line)
cart_line = next((l for l in lines if l.startswith(f"place {CART} ")), "")
check("(o2) cart outline box", "outline (1003,-5)-(1013,5)" in cart_line, cart_line)

# (o3)
upsert_location({"id": "loc_demo_post", "name": "Demo Post", "pos_x": 2000.0, "pos_z": 0.0,
                 "yaw_deg": 0.0}, sync_world=False)
POST_BEFORE = get_location_by_id("loc_demo_post")
res = call(1, "create_location", {"data": {"name": "Demo Gate", "rooms": [{"name": "Room"}]},
                                  "x": 2008, "z": 0,
                                  "boundary": [[-10, -1], [10, -1], [10, 1], [-10, 1]]})
check("(o3) drawn outline over a pin: no warning",
      res.ok and "; warnings:" not in res.line, res)

# (o4)
res = call(1, "create_location", {"data": {"name": "Demo Shop", "rooms": [{"name": "Room"}]},
                                  "x": 1300, "z": 0})
check("(o4) shop ok", res.ok, res)
SHOP = (named("Demo Shop") or [{}])[0].get("id") or ""
res = call(1, "create_location", {"data": {"name": "Demo Inn", "rooms": [{"name": "Room"}]},
                                  "x": 1308, "z": 0})
check("(o4) inn overlaps the stored shop square",
      res.ok and f'overlaps place {SHOP} "Demo Shop"' in res.line, res)

# (o5)
rep = wu.undo(run)
check("(o5) undo complete", rep["complete"], rep)
check("(o5) no run-3 place left",
      not any(named(n) for n in ("Demo Barn", "Demo Cart", "Demo Gate", "Demo Shop",
                                 "Demo Inn")))
check("(o5) pin and post unchanged",
      get_location_by_id("loc_demo_pin") == PIN_BEFORE
      and get_location_by_id("loc_demo_post") == POST_BEFORE)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("all checks passed")
