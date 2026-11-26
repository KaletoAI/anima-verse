#!/usr/bin/env python3
"""Smoke: World Dev free mode — area scatter, rows along strokes, area NPC
slots, water and relief (gaps 5 area part, 6, 20 water/relief; E10, E11).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p2-buildings-terrain.md, Task 6.
A temp world (paths.init BEFORE any world-DB import), an EMPTY ANIMATION_CLIPS_DIR;
no server, no LLM. Every tool call goes through world_dev_tools.run_tool
exactly as the agent loop calls it.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_area_extras.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Kinds: the shipped catalog (shared/terrain/types.json, no world rows in a temp
world). "grass" is passable and no water. WATER = the FIRST kind of
effective_catalog() for which terrain_types.is_water_kind answers True — read
once at runtime; with today's types.json that is "water" (passable,
meta.water true).

Prop: TREE = props.create_prop(name="Demo Tree")["id"] (a slug of the name
plus a short hash, e.g. "demo-tree-1a2b3c" — read back at runtime);
URL = "/assets/props/<TREE>/model", the shape props.prop_id_from_model_url
resolves (strict: no host, no query).

Constants quoted from app/models/terrain.py:
  MIN_SPACING_MAX_M = 100.0 (a scatter min_spacing_m is clamped to it — read
  from the module at runtime, as the plan allows; json.dumps(100.0) = "100.0");
  RELIEF_AMPLITUDE 0.05 … 2.0 (so 5 is clamped to 2.0), RELIEF_WAVE 4.0 … 200.0
  (so 0.5 / 20 pass unchanged); ALONG_SPACING 1.0 … 500.0 (15 passes).
Keys the sanitizers ADD (defaults, not a rewrite):
  _sanitize_scatter_entry: always "density_per_100m2" (we send it); nothing
  else for an entry with only model / density / min_spacing_m.
  _sanitize_along_entry: always "spacing_m" (default 20) and "offset_m"
  (default 0.0) — so a row sent as {model, spacing_m 15} is stored
  {spacing_m 15.0, offset_m 0.0, model URL}.
  _sanitize_npc_slots: forces room "" and radius_m 0 on every area slot;
  npc_spawn.normalize_slot adds its own defaults (counts, …).
E11: a stroke area of a water kind that sends neither water.flow_along nor
water.flow_dir_deg is stored with flow_along "forward" and the result line
says "flows forward"; water.flow_along "" means still water (the key stays
absent; the sanitizer drops "" which is exactly the meaning sent).

Cases, one run:
  (a) t1 add_terrain_area{grass, square (0,0)-(40,40), label "Demo Wood",
      scatter [{model URL, density_per_100m2 2, min_spacing_m 3}]} -> ok;
      stored meta.scatter == [{"density_per_100m2": 2.0, "min_spacing_m": 3.0,
      "model": URL}] (exactly — no other key is added).
  (b) t1 same with min_spacing_m 9999 -> refused, the line has
      "would be stored as 100.0"; no new area.
  (c) t1 scatter model "/assets/props/nope/model" (no such prop) and
      "https://x/y" (not the prop URL shape) -> both refused, line names
      "model"; no new area.
  (d) t1 add_terrain_area{WATER, stroke {points [[0,100],[0,200]], width_m 10}}
      -> ok; stored meta.flow_along == "forward"; the line has "flows forward".
  (e) t1 the same at x 50 with water {flow_along ""} -> ok; stored meta has
      NO "flow_along"; no "flows forward" in the line.
      water {flow_along "sideways"} -> refused with
      'water.flow_along' would be stored as "dropped" (the sanitizer drops a
      value outside heightfield.FLOW_ALONG_VALUES = forward/reverse).
      water {bed_kind "nosuch"} on a WATER polygon -> refused, "bed_kind".
      water {water_depth_m 2} on a grass area -> refused, "water kind".
  (f) t1 add_terrain_area{grass, square (100,0)-(120,20), npc_slots
      [{role "Demo Hunter"}]} without a label -> refused, "needs a label"
      (terrain._sanitize_npc_slots' ValueError); a slot with room "r1" ->
      refused, "room"; with label "Demo Hunting Ground" -> ok, the stored slot
      has role "Demo Hunter", room "" and radius_m 0.
  (g) t1 add_terrain_area{grass, square (200,0)-(240,40), relief_amplitude_m
      0.5, relief_wave_m 20} -> ok, stored 0.5 / 20.0; relief_amplitude_m 5 on
      another square -> refused, "would be stored as 2.0".
  (h) t1 add_terrain_area{grass, stroke {points [[300,0],[300,100]], width_m 6,
      along [{model URL, spacing_m 15}]}} -> ok; stored meta.stroke.along ==
      [{"spacing_m": 15.0, "offset_m": 0.0, "model": URL}]. An along row without
      a model (it would place nothing) -> refused, "model".
  (m) t1 scatter [{model URL}] (no density) -> refused, the line names
      "density_per_100m2" (the sanitizer would store 0.0 = nothing scattered);
      density_per_100m2 0 -> refused the same way; [{model URL, place
      "center"}] -> ok (a centre instance ignores the density, scene-render
      scatter.ts), stored [{"density_per_100m2": 0.0, "model": URL, "place":
      "center"}] — the sanitizer's own keys, nothing else.
      [{model URL, place "edge"}] (no min_spacing_m) -> refused, the line names
      "min_spacing_m" (the renderer walks an edge row at min_spacing_m;
      scatterAxis.ts ringStations returns [] for a spacing that is not above
      0); min_spacing_m 0 -> refused the same way; [{model URL, place "edge",
      min_spacing_m 4}] -> ok (area m2).
  (t) t1 add_terrain_area{WATER polygon, water {flow_along "forward"}} ->
      refused, the line names "flow_dir_deg" (heightfield.is_flowing needs a
      stroke's line; on a polygon the key acts on nothing).
  (n) t1 add_terrain_area{grass, relief_wave_m 20} alone -> refused, the line
      names "relief_amplitude_m" (heightfield reads amp 0 = no relief).
  (o) t1 add_terrain_area{WATER, square (400,0)-(420,20), water
      {water_depth_m 2}} -> ok (2 is inside WATER_DEPTH 0.2 … 20, stored 2.0).
  (l) the refused calls of (b), (c), (e), (f), (g), (h), (m), (n), (t) left
      no area: the stored ids are exactly a, d, e, f, g, h, m, m2, o plus the
      two fixtures.
  (u) t2 update_terrain_area{a, water {}} -> refused "nothing to change"
      (an empty water object changes nothing), wrote False, a unchanged.
  (i) t2 update_terrain_area{a, label "Old Wood"} -> meta.scatter unchanged,
      label "Old Wood". t2 update_terrain_area{h, stroke {points
      [[300,0],[300,120]], width_m 6}} (no along sent) -> the along rows are
      kept. t2 update_terrain_area{g, scatter [{model URL,
      density_per_100m2 1}]} -> meta.scatter == [{"density_per_100m2": 1.0,
      "model": URL}], relief_amplitude_m still 0.5.
  (i2) t2 refusals on update come before any write (the row is built and
      checked on the pre-read): update{g, relief_amplitude_m 5} -> refused
      "would be stored as 2.0"; update{f, label ""} -> refused "needs a label"
      (slots stay, the label would go); both leave g / f JSON-equal and add
      one "refused" journal row each. update{a, scatter []} -> ok, meta has no
      "scatter" any more ([] removes the list); update{g, relief_amplitude_m 0}
      -> ok, no "relief_amplitude_m" (0 removes it), relief_wave_m 20.0 kept.
  (k) t2 get_area{a} has the line "scatter: 1 entries (<TREE> d=2 s=3)"
      (density 2.0 and spacing 3.0 printed through _g, which drops ".0");
      get_area{h} has "along: 1 rows (<TREE> spacing=15 offset=0)" (the
      stored row of (h): spacing 15.0, offset 0.0, no side);
      get_area{f} has "slots: Demo Hunter"; get_area{d} has a "water: " line
      containing "flow_along=forward". The second fixture ta_fixture_rows (a
      stroke saved through the core whose along row carries yaw_mode "random",
      start_m 3, spacing_jitter_m 2, variant 1, reshuffle_min 60 beside
      spacing 25 / offset 6 / side both) prints EVERY stored key:
      "along: 1 rows (<TREE> spacing=25 offset=6 side=both reshuffle_min=60
      spacing_jitter_m=2 start_m=3 variant=1 yaw_mode=random)" — the short
      names first, the rest sorted by name; the agent resends what it keeps
      from this line, so a key left out would be lost.
  (p) after (k): t2 update_terrain_area{d, polygon square (0,100)-(10,110)}
      -> ok, the stroke is gone and so is flow_along (no water sent), the line
      has "flow_along dropped with the stroke". d was settled at (d) with
      water_level_up / water_level_down (asserted present before): both go
      with it (no flow_dir_deg remains, so the polygon is a still lake on
      water_level) and the line names them.
      The phase review added (p2), run 2 below: the same with water {flow_along
      ""} in the call — the end levels are decided AFTER the merge (whoever
      cleared the flow), and an along row of the dropped stroke is named.
  (v) run 2: SHRUBS = 8 props "Demo Shrub 0..7"; add_terrain_area{grass, square,
      scatter: one edge entry per shrub, {place edge, min_spacing_m 4, offset_m
      1.5, sides opposite, yaw_mode aligned, yaw_deg 90, variant 1,
      reshuffle_min 60, spacing_jitter_m 1}} -> get_area has the WHOLE line
      "scatter: 8 entries (<shrub> d=0 s=4 place=edge offset=1.5 sides=opposite
      yaw=aligned yaw_deg=90 reshuffle_min=60 spacing_jitter_m=1 variant=1; …)"
      (d=0: an edge row stores density 0.0, _g prints "0"; the short names in
      their fixed order, the rest sorted) — longer than 300 characters, never
      cut, every shrub id on it. (v2) the same for 8 along rows on a stroke:
      "along: 8 rows (<shrub> spacing=25 offset=6 side=both reshuffle_min=60
      spacing_jitter_m=2 start_m=3 variant=1 yaw_mode=random; …)".
  (q) t2 update_terrain_area{o, kind "grass"} -> ok, water_depth_m 2.0 stays
      (the sanitizer keeps a flat water key on any kind). water
      {water_depth_m 3} on it -> refused "water kind"; water {water_depth_m
      ""} -> ok, the key is gone (a removal is let through on any kind).
  (r) the fixture: before the run it gets, through the core, scatter
      [{model URL, density 1}], npc_slots [{role "Demo Herder"}], relief
      0.3 / 12 and a foreign meta key "demo_note"; F_ROW is read after that.
      t2 update_terrain_area{ta_fixture, label "Demo Meadow", scatter
      [{model URL, density 4, min_spacing_m 2}], relief_amplitude_m 0.6,
      npc_slots []} -> ok and changed; (j) then proves undo RESTORES it.
  (j) discard_preview names each created area exactly once (a, d, e, f, g, h,
      m, m2, o = 9 lines) and not the fixtures (it lists only what the run CREATED,
      world_dev_undo.discard_preview's docstring); undo(run) -> complete, no area
      of the run is left, the fixture area equals its pre-run row (F_ROW,
      JSON-equal: scatter, slots, relief, label and the foreign key back).
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

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_extras_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_extras_"))
paths.init(STORAGE)
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)

from app.core import config, db  # noqa: E402

config.load(paths.get_config_path())
db.init_schema()

from app.core import props  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core.terrain_types import effective_catalog, is_water_kind  # noqa: E402
from app.models import terrain  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


CATALOG = effective_catalog()
WATER = next((k for k in CATALOG if is_water_kind(k, CATALOG)), "")
check("fixture: a water kind exists", bool(WATER), list(CATALOG))
TREE = props.create_prop(name="Demo Tree")["id"]
URL = f"/assets/props/{TREE}/model"
check("fixture: the URL resolves to the prop", props.prop_id_from_model_url(URL) == TREE, URL)

terrain.save_area({"id": "ta_fixture", "kind": "grass",
                   "polygon": [[900, 900], [910, 900], [910, 910], [900, 910]],
                   "meta": {"label": "Demo Field", "demo_note": "kept",
                            "scatter": [{"model": URL, "density_per_100m2": 1}],
                            "npc_slots": [{"role": "Demo Herder"}],
                            "relief_amplitude_m": 0.3, "relief_wave_m": 12}})
F_ROW = terrain.get_area("ta_fixture")
terrain.save_area({"id": "ta_fixture_rows", "kind": "grass",
                   "polygon": [[950, 900], [960, 900], [960, 910]],
                   "meta": {"stroke": {"points": [[950, 0], [950, 100]], "width_m": 6,
                                       "along": [{"model": URL, "spacing_m": 25,
                                                  "offset_m": 6, "side": "both",
                                                  "yaw_mode": "random", "start_m": 3,
                                                  "spacing_jitter_m": 2, "variant": 1,
                                                  "reshuffle_min": 60}]}}})

run = wr.create_run("extras", "m", "p", "u", 60, 300000)


def call(turn, tool, args):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


def new_area(fn):
    known = {a["id"] for a in terrain.list_areas()}
    res = fn()
    added = [a["id"] for a in terrain.list_areas() if a["id"] not in known]
    return res, (added[0] if added else "")


def meta(aid):
    return (terrain.get_area(aid) or {}).get("meta") or {}


def sq(x0, z0, x1, z1):
    return [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]


def add(args):
    return new_area(lambda: call(1, "add_terrain_area", args))


# (a)
res, A = add({"kind": "grass", "polygon": sq(0, 0, 40, 40), "label": "Demo Wood",
              "scatter": [{"model": URL, "density_per_100m2": 2, "min_spacing_m": 3}]})
check("(a) ok", res.ok and bool(A), res.line)
check("(a) scatter stored exactly",
      meta(A).get("scatter") == [{"density_per_100m2": 2.0, "min_spacing_m": 3.0,
                                  "model": URL}], meta(A).get("scatter"))

# (b)
res, B = add({"kind": "grass", "polygon": sq(50, 0, 60, 10),
              "scatter": [{"model": URL, "density_per_100m2": 2, "min_spacing_m": 9999}]})
check("(b) refused", not res.ok and not B, res.line)
check("(b) names the clamp",
      f"would be stored as {terrain.MIN_SPACING_MAX_M}" in res.line, res.line)

# (c)
for bad in ("/assets/props/nope/model", "https://x/y"):
    res, C = add({"kind": "grass", "polygon": sq(50, 0, 60, 10),
                  "scatter": [{"model": bad, "density_per_100m2": 1}]})
    check(f"(c) model {bad} refused", not res.ok and not C and "model" in res.line, res.line)

# (d)
res, D = add({"kind": WATER, "stroke": {"points": [[0, 100], [0, 200]], "width_m": 10}})
check("(d) ok", res.ok and bool(D), res.line)
check("(d) flows forward by default", meta(D).get("flow_along") == "forward", meta(D))
check("(d) line says so", "flows forward" in res.line, res.line)

# (e)
res, E = add({"kind": WATER, "stroke": {"points": [[50, 100], [50, 200]], "width_m": 10},
              "water": {"flow_along": ""}})
check("(e) ok", res.ok and bool(E), res.line)
check("(e) still water: no flow_along", "flow_along" not in meta(E), meta(E))
check("(e) no default line", "flows forward" not in res.line, res.line)
res, E2 = add({"kind": WATER, "stroke": {"points": [[80, 100], [80, 200]], "width_m": 10},
               "water": {"flow_along": "sideways"}})
check("(e) unknown flow_along refused",
      not res.ok and not E2
      and "'water.flow_along' would be stored as \"dropped\"" in res.line, res.line)
res, E3 = add({"kind": WATER, "polygon": sq(80, 300, 90, 310),
               "water": {"bed_kind": "nosuch"}})
check("(e) unknown bed_kind refused", not res.ok and not E3 and "bed_kind" in res.line,
      res.line)
res, E4 = add({"kind": "grass", "polygon": sq(80, 300, 90, 310),
               "water": {"water_depth_m": 2}})
check("(e) water on a dry kind refused", not res.ok and not E4 and "water kind" in res.line,
      res.line)

# (f)
res, F0 = add({"kind": "grass", "polygon": sq(100, 0, 120, 20),
               "npc_slots": [{"role": "Demo Hunter"}]})
check("(f) without label refused", not res.ok and not F0 and "needs a label" in res.line,
      res.line)
res, F1 = add({"kind": "grass", "polygon": sq(100, 0, 120, 20),
               "label": "Demo Hunting Ground",
               "npc_slots": [{"role": "Demo Hunter", "room": "r1"}]})
check("(f) slot with room refused", not res.ok and not F1 and "room" in res.line, res.line)
res, FA = add({"kind": "grass", "polygon": sq(100, 0, 120, 20),
               "label": "Demo Hunting Ground", "npc_slots": [{"role": "Demo Hunter"}]})
slots = meta(FA).get("npc_slots") or [{}]
check("(f) with label ok", res.ok and bool(FA), res.line)
check("(f) slot stored with room '' and radius 0",
      len(slots) == 1 and slots[0].get("role") == "Demo Hunter"
      and slots[0].get("room") == "" and slots[0].get("radius_m") == 0, slots)

# (g)
res, G = add({"kind": "grass", "polygon": sq(200, 0, 240, 40),
              "relief_amplitude_m": 0.5, "relief_wave_m": 20})
check("(g) ok", res.ok and bool(G), res.line)
check("(g) relief stored",
      (meta(G).get("relief_amplitude_m"), meta(G).get("relief_wave_m")) == (0.5, 20.0),
      meta(G))
res, G2 = add({"kind": "grass", "polygon": sq(250, 0, 260, 10), "relief_amplitude_m": 5})
check("(g) clamped amplitude refused",
      not res.ok and not G2 and "would be stored as 2.0" in res.line, res.line)

# (h)
res, H = add({"kind": "grass", "stroke": {"points": [[300, 0], [300, 100]], "width_m": 6,
                                          "along": [{"model": URL, "spacing_m": 15}]}})
check("(h) ok", res.ok and bool(H), res.line)
check("(h) along stored with defaults",
      (meta(H).get("stroke") or {}).get("along")
      == [{"spacing_m": 15.0, "offset_m": 0.0, "model": URL}], meta(H).get("stroke"))
res, H2 = add({"kind": "grass", "stroke": {"points": [[350, 0], [350, 100]], "width_m": 6,
                                           "along": [{"spacing_m": 15}]}})
check("(h) row without a model refused", not res.ok and not H2 and "model" in res.line,
      res.line)

# (m)
res, M0 = add({"kind": "grass", "polygon": sq(500, 0, 510, 10), "scatter": [{"model": URL}]})
check("(m) scatter without density refused",
      not res.ok and not M0 and "density_per_100m2" in res.line, res.line)
res, M1 = add({"kind": "grass", "polygon": sq(500, 0, 510, 10),
               "scatter": [{"model": URL, "density_per_100m2": 0}]})
check("(m) scatter density 0 refused",
      not res.ok and not M1 and "density_per_100m2" in res.line, res.line)
res, M = add({"kind": "grass", "polygon": sq(500, 0, 510, 10),
              "scatter": [{"model": URL, "place": "center"}]})
check("(m) centre entry without density ok", res.ok and bool(M), res.line)
check("(m) centre entry stored exactly",
      meta(M).get("scatter") == [{"density_per_100m2": 0.0, "model": URL,
                                  "place": "center"}], meta(M).get("scatter"))
res, ME = add({"kind": "grass", "polygon": sq(540, 0, 560, 20),
               "scatter": [{"model": URL, "place": "edge"}]})
check("(m) edge row without min_spacing_m refused",
      not res.ok and not ME and "min_spacing_m" in res.line, res.line)
res, ME = add({"kind": "grass", "polygon": sq(540, 0, 560, 20),
               "scatter": [{"model": URL, "place": "edge", "min_spacing_m": 0}]})
check("(m) edge row with min_spacing_m 0 refused",
      not res.ok and not ME and "min_spacing_m" in res.line, res.line)
res, M2 = add({"kind": "grass", "polygon": sq(540, 0, 560, 20),
               "scatter": [{"model": URL, "place": "edge", "min_spacing_m": 4}]})
check("(m) edge row with a spacing ok", res.ok and bool(M2), res.line)

# (t)
res, T0 = add({"kind": WATER, "polygon": sq(600, 0, 620, 20),
               "water": {"flow_along": "forward"}})
check("(t) flow_along on a polygon refused",
      not res.ok and not T0 and "flow_dir_deg" in res.line, res.line)

# (n)
res, N = add({"kind": "grass", "polygon": sq(520, 0, 530, 10), "relief_wave_m": 20})
check("(n) lone relief_wave_m refused",
      not res.ok and not N and "relief_amplitude_m" in res.line, res.line)

# (o)
res, O = add({"kind": WATER, "polygon": sq(400, 0, 420, 20), "water": {"water_depth_m": 2}})
check("(o) water polygon with depth ok",
      res.ok and bool(O) and meta(O).get("water_depth_m") == 2.0, (res.line, meta(O)))

# (l)
created = {A, D, E, FA, G, H, M, M2, O}
FIXTURES = {"ta_fixture", "ta_fixture_rows"}
ids = {a["id"] for a in terrain.list_areas()}
check("(l) refused calls left no area", ids == created | FIXTURES, ids)

# (u)
a_row = terrain.get_area(A)
res = call(2, "update_terrain_area", {"id": A, "water": {}})
check("(u) empty water refused up front",
      not res.ok and not res.wrote and "nothing to change" in res.line, res.line)
check("(u) a unchanged", terrain.get_area(A) == a_row)

# (i)
a_before = meta(A)
res = call(2, "update_terrain_area", {"id": A, "label": "Old Wood"})
check("(i) relabel ok", res.ok, res.line)
check("(i) scatter unchanged", meta(A).get("scatter") == a_before.get("scatter")
      and meta(A).get("label") == "Old Wood", meta(A))
res = call(2, "update_terrain_area", {"id": H, "stroke": {"points": [[300, 0], [300, 120]],
                                                          "width_m": 6}})
check("(i) reshaped stroke keeps along",
      res.ok and (meta(H).get("stroke") or {}).get("along")
      == [{"spacing_m": 15.0, "offset_m": 0.0, "model": URL}], (res.line, meta(H)))
res = call(2, "update_terrain_area", {"id": G, "scatter": [{"model": URL,
                                                             "density_per_100m2": 1}]})
check("(i) scatter set on update", res.ok and meta(G).get("scatter")
      == [{"density_per_100m2": 1.0, "model": URL}], (res.line, meta(G)))
check("(i) relief untouched", meta(G).get("relief_amplitude_m") == 0.5, meta(G))

# (i2)
g_row, f_row = terrain.get_area(G), terrain.get_area(FA)
n_steps = len(wr.steps(run))
res = call(2, "update_terrain_area", {"id": G, "relief_amplitude_m": 5})
check("(i2) clamped relief refused on update",
      not res.ok and not res.wrote and "would be stored as 2.0" in res.line, res.line)
res = call(2, "update_terrain_area", {"id": FA, "label": ""})
check("(i2) dropping the label of a slotted area refused",
      not res.ok and not res.wrote and "needs a label" in res.line, res.line)
check("(i2) both areas unchanged",
      terrain.get_area(G) == g_row and terrain.get_area(FA) == f_row)
check("(i2) one refused row each",
      [s["kind"] for s in wr.steps(run)[n_steps:]] == ["refused", "refused"],
      wr.steps(run)[n_steps:])

# (k)
out = call(2, "get_area", {"id": FA}).line.split("\n")
check("(k) slots line", "slots: Demo Hunter" in out, out)
out = call(2, "get_area", {"id": D}).line.split("\n")
wl = next((ln for ln in out if ln.startswith("water: ")), "")
check("(k) water line", "flow_along=forward" in wl, out)
out = call(2, "get_area", {"id": A}).line.split("\n")
check("(k) scatter entries spelled out", f"scatter: 1 entries ({TREE} d=2 s=3)" in out, out)
out = call(2, "get_area", {"id": H}).line.split("\n")
check("(k) along rows spelled out", f"along: 1 rows ({TREE} spacing=15 offset=0)" in out, out)
out = call(2, "get_area", {"id": "ta_fixture_rows"}).line.split("\n")
check("(k) every stored along key printed",
      f"along: 1 rows ({TREE} spacing=25 offset=6 side=both reshuffle_min=60 "
      f"spacing_jitter_m=2 start_m=3 variant=1 yaw_mode=random)" in out, out)

# (p)
check("(p) d carries the end levels before",
      "water_level_up" in meta(D) and "water_level_down" in meta(D), meta(D))
res = call(2, "update_terrain_area", {"id": D, "polygon": sq(0, 100, 10, 110)})
check("(p) stroke to polygon ok", res.ok and "stroke" not in meta(D), (res.line, meta(D)))
check("(p) flow_along dropped with the stroke",
      "flow_along" not in meta(D) and "flow_along dropped with the stroke" in res.line,
      (res.line, meta(D)))
check("(p) end levels dropped with it",
      "water_level_up" not in meta(D) and "water_level_down" not in meta(D)
      and "water_level_up, water_level_down" in res.line, (res.line, meta(D)))

# (q)
res = call(2, "update_terrain_area", {"id": O, "kind": "grass"})
check("(q) water area turned dry, depth kept",
      res.ok and meta(O).get("water_depth_m") == 2.0, (res.line, meta(O)))
res = call(2, "update_terrain_area", {"id": O, "water": {"water_depth_m": 3}})
check("(q) water value on a dry kind refused", not res.ok and "water kind" in res.line,
      res.line)
res = call(2, "update_terrain_area", {"id": O, "water": {"water_depth_m": ""}})
check("(q) water removal on a dry kind ok", res.ok and "water_depth_m" not in meta(O),
      (res.line, meta(O)))

# (r)
res = call(2, "update_terrain_area", {"id": "ta_fixture", "label": "Demo Meadow",
                                      "scatter": [{"model": URL, "density_per_100m2": 4,
                                                   "min_spacing_m": 2}],
                                      "relief_amplitude_m": 0.6, "npc_slots": []})
fm = meta("ta_fixture")
check("(r) fixture updated", res.ok and fm.get("label") == "Demo Meadow"
      and "npc_slots" not in fm and fm.get("relief_amplitude_m") == 0.6
      and fm.get("demo_note") == "kept", (res.line, fm))

# (i2) removals (after the get_area reads of (k))
res = call(2, "update_terrain_area", {"id": A, "scatter": []})
check("(i2) scatter [] removes the list", res.ok and "scatter" not in meta(A), meta(A))
res = call(2, "update_terrain_area", {"id": G, "relief_amplitude_m": 0})
check("(i2) relief 0 removes the amplitude",
      res.ok and "relief_amplitude_m" not in meta(G) and meta(G).get("relief_wave_m") == 20.0,
      meta(G))

# (j)
prev = wu.discard_preview(run)
check("(j) preview names each created area once, the restored fixture not",
      len(prev) == 9 and all(sum(aid in ln for ln in prev) == 1 for aid in created)
      and not any("ta_fixture" in ln for ln in prev), prev)
rep = wu.undo(run)
check("(j) undo complete", rep["complete"], rep)
ids = {a["id"] for a in terrain.list_areas()}
check("(j) every run area gone", ids == FIXTURES, ids)
check("(j) fixture restored to its pre-run row",
      json.dumps(terrain.get_area("ta_fixture"), sort_keys=True)
      == json.dumps(F_ROW, sort_keys=True), terrain.get_area("ta_fixture"))
check("(j) fixture extras present before the run (the restore had work to do)",
      bool((F_ROW.get("meta") or {}).get("scatter"))
      and bool((F_ROW.get("meta") or {}).get("npc_slots")), F_ROW)

# ── second run: long extras lines and the flow cleanup (phase review) ──────
try:
    wr.set_status(run, "accepted")
except Exception:  # noqa: BLE001 — the undo may have closed it already
    pass
run = wr.create_run("extras2", "m", "p", "u", 60, 300000)
SHRUBS = [props.create_prop(name=f"Demo Shrub {i}")["id"] for i in range(8)]

# (v) scatter: 8 edge entries, one per shrub prop
res, V = add({"kind": "grass", "polygon": sq(1000, 0, 1040, 40),
              "scatter": [{"model": f"/assets/props/{p}/model", "place": "edge",
                           "min_spacing_m": 4, "offset_m": 1.5, "sides": "opposite",
                           "yaw_mode": "aligned", "yaw_deg": 90, "variant": 1,
                           "reshuffle_min": 60, "spacing_jitter_m": 1} for p in SHRUBS]})
check("(v) 8 rich scatter entries ok", res.ok and bool(V), res.line)
want = ("scatter: 8 entries ("
        + "; ".join(f"{p} d=0 s=4 place=edge offset=1.5 sides=opposite yaw=aligned "
                    "yaw_deg=90 reshuffle_min=60 spacing_jitter_m=1 variant=1"
                    for p in SHRUBS) + ")")
out = call(1, "get_area", {"id": V}).line.split("\n")
check("(v) scatter line whole, longer than the old 300 cut", want in out and len(want) > 300,
      out)
check("(v) every prop id on the scatter line",
      all(p in next((ln for ln in out if ln.startswith("scatter: ")), "") for p in SHRUBS), out)

# (v2) along: 8 rows on a stroke
res, V2 = add({"kind": "grass", "stroke": {"points": [[1100, 0], [1100, 200]], "width_m": 6,
                                          "along": [{"model": f"/assets/props/{p}/model",
                                                     "spacing_m": 25, "offset_m": 6,
                                                     "side": "both", "yaw_mode": "random",
                                                     "start_m": 3, "spacing_jitter_m": 2,
                                                     "variant": 1, "reshuffle_min": 60}
                                                    for p in SHRUBS]}})
check("(v2) 8 rich along rows ok", res.ok and bool(V2), res.line)
want = ("along: 8 rows ("
        + "; ".join(f"{p} spacing=25 offset=6 side=both reshuffle_min=60 "
                    "spacing_jitter_m=2 start_m=3 variant=1 yaw_mode=random"
                    for p in SHRUBS) + ")")
out = call(1, "get_area", {"id": V2}).line.split("\n")
check("(v2) along line whole, longer than the old 300 cut", want in out and len(want) > 300,
      out)

# (p2) a flowing water stroke with one along row, redrawn as a polygon while the
#     SAME call sends water {flow_along ""}: the call clears the flow itself, so
#     no "flow_along dropped" note; the end levels are decided on the merged meta
#     (no flow_along, no flow_dir_deg) and go: "water_level_up, water_level_down
#     dropped with the stroke (still water)"; the along row goes with the stroke
#     and is named: "1 along row (<TREE>) dropped with the stroke".
res, P2 = add({"kind": WATER, "stroke": {"points": [[1200, 0], [1200, 100]], "width_m": 10,
                                         "along": [{"model": URL, "spacing_m": 15}]}})
check("(p2) flowing water stroke with a row",
      res.ok and meta(P2).get("flow_along") == "forward"
      and "water_level_up" in meta(P2) and "water_level_down" in meta(P2), (res.line, meta(P2)))
res = call(2, "update_terrain_area", {"id": P2, "polygon": sq(1200, 0, 1210, 10),
                                      "water": {"flow_along": ""}})
m2 = meta(P2)
check("(p2) polygon, no flow, no end levels",
      res.ok and "stroke" not in m2 and "flow_along" not in m2
      and "water_level_up" not in m2 and "water_level_down" not in m2, (res.line, m2))
check("(p2) the line names the end levels and the row",
      "water_level_up, water_level_down dropped with the stroke (still water)" in res.line
      and f"1 along row ({TREE}) dropped with the stroke" in res.line
      and "flow_along dropped" not in res.line, res.line)
rep = wu.undo(run)
check("(v/p2) undo complete", rep["complete"], rep)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("all checks passed")
