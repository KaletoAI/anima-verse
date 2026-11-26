#!/usr/bin/env python3
"""Smoke: World Dev free mode — custom terrain kinds (gap 20 kinds part, E12).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p2-buildings-terrain.md, Task 9.
A temp world (paths.init BEFORE any world-DB import), an EMPTY ANIMATION_CLIPS_DIR;
no server, no LLM. Every tool call goes through world_dev_tools.run_tool
exactly as the agent loop calls it.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_terrain_types.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

The shipped catalog (shared/terrain/types.json) holds grass, forest, sand,
path, water, river, deep_water, rock; "water" carries meta.water true. A kind
the run adds is a WORLD row (terrain_types.save_world_type); the effective
catalog is shared overlaid by world rows (terrain_types.effective_catalog).
'surface' is checked against the surface-texture library
(surface_textures.library_kinds()) when that library is non-empty; a temp
world sees the SHARED library (non-empty), so the check is live here (s).

Format and ranges are the SANITIZER's (terrain_types.sanitize_type): a kind
must match _KIND_RE (lower-case letters, digits, "_" and "-", 1..40 chars,
starting with a letter or digit), so "Demo Cobble" raises
"invalid terrain kind: 'Demo Cobble'" — that message is the refusal (h).
speed_factor is clamped to SPEED_MIN..SPEED_MAX (0.0..2.0, read from the
module at runtime) and rounded to 2 decimals: 3 -> "would be stored as 2.0"
(c); 1.234 -> 1.23 -> "would be stored as 1.23" (c). An invalid colour
("red") is a ValueError of the sanitizer ("invalid color") (c).

world_overview lists a kind via world_dev_tools._kind_text: '<kind> "<name>"'
plus the flags differing from plain ground; speed 1.2 -> "(speed ×1.2)" (a).

Cases (run 1):
  (a) t1 add_terrain_type{kind "demo_cobble", name "Cobblestone", color
      "#888888", speed_factor 1.2} -> ok, the journal row's target is
      ("terrain_type", "demo_cobble") with inverse
      {"op": "delete_terrain_type", "kind": "demo_cobble"};
      effective_catalog()["demo_cobble"]["speed_factor"] == 1.2;
      world_overview contains 'demo_cobble "Cobblestone" (speed ×1.2)'.
  (b) the same kind again -> refused "already exists (world)"; kind "grass"
      (shipped) -> refused "already exists (shared)". Nothing stored.
  (c) speed_factor 3 / 1.234 -> refused "would be stored as 2.0" / "1.23";
      color "red" -> refused "invalid color"; an unknown key -> refused.
      Every refusal leaves a "refused" journal row and no world row.
  (h) kind "Demo Cobble" -> refused with the sanitizer's message
      "invalid terrain kind: 'Demo Cobble'".
  (s) surface "whatever" (not a library kind) -> refused "'surface' must be a
      kind of the surface library", nothing stored; kind "demo_paved" with
      surface = sorted(library_kinds())[0] -> ok, and the catalog row of
      demo_paved carries exactly that surface. (Undone with the run in (e).)
  (w) add_terrain_type{kind "demo_pond", name "Demo Pond", color "#3366aa",
      water {water_depth_m 2}} -> ok; is_water_kind("demo_pond") True and
      the catalog meta.water_depth_m == 2.0 (stored as sent).
      water {water_depth_m 99} -> refused "would be stored as" (the
      sanitizer clamps to heightfield.WATER_DEPTH_MAX_M).
  (d) t1 add_terrain_area{kind "demo_cobble", polygon} -> ok (usable in the
      same turn).
  discard_preview -> contains 'terrain kind demo_cobble "Cobblestone"' and
      'terrain kind demo_pond "Demo Pond"'.
  (e) undo(run) -> complete: the area is deleted first (newest-first), then
      the kinds; get_type("demo_cobble") is None, no world row left.
Case (x), run 18 (phase review): a foreign edit between two run edits of one
area stops the restore chain there — derived by hand next to the block below;
the kind stays in use and the preview says so.
Cases (run 2):
  (f) t1 add_terrain_type demo_cobble again; then a FOREIGN area of that kind
      saved directly with terrain.save_area. discard_preview names the kind
      ('terrain kind demo_cobble "Cobblestone"', the line also says the
      discard leaves it, as the undo does). undo(run) -> not complete, the
      kind is skipped "changed since" with keys ["in use"]; the foreign area
      is untouched and the kind still exists.
Cases (run 3):
  (g) t1 add_terrain_type demo_gravel; a FOREIGN water area of the shipped
      kind "water" with meta.bed_kind "demo_gravel" saved directly ->
      undo(run) skips the kind "changed since" (in use); it still exists.
Cases (run 4):
  (i) t1 add_terrain_type demo_moss, add_terrain_area of it; same-turn
      delete_created{kind "terrain_type", id "demo_moss"} -> refused (in use,
      names the area); delete_created of the area, then of the kind -> ok,
      the kind is gone, undo(run) complete, nothing left.
Cases (run 5):
  (j) t1 add_terrain_type demo_clay; t2 delete_created -> ok "an earlier
      turn", the kind is gone; discard_preview has no line for it (net
      absent); undo(run, turn 2) -> complete, the kind is back and equal to
      the entry read after t1; undo(run) -> complete, the kind gone.
  (k) t3 add_terrain_type demo_loam; a FOREIGN location with terrain
      "demo_loam" (upsert_location); t4 delete_created -> refused, names the
      location. undo(run) -> skipped "changed since" (in use).
Cases (run 7):
  (l) the run's OWN change of a pre-existing area: fixture area ta_pre of
      "grass" saved before the run; t1 add_terrain_type demo_peat, t1
      update_terrain_area{id ta_pre, kind demo_peat}. discard_preview -> the
      plain line 'terrain kind demo_peat "Demo Peat"' (no "still used": the
      undo restores ta_pre to grass before it reaches the kind);
      undo(run) -> complete, ta_pre is grass again, demo_peat gone.
Cases (run 8):
  (n) the run repaints a pre-existing area and somebody else edits it after:
      fixture ta_pre2 of "grass"; t1 add_terrain_type demo_sod, t1
      update_terrain_area{id ta_pre2, kind demo_sod}; then a FOREIGN
      save_area of ta_pre2 with another polygon (kind still demo_sod). The
      area's restore will be skipped (its row is no longer what the run
      wrote), so the use stays: discard_preview -> the kind's line says
      'is still used by terrain area ta_pre2' and 'the discard leaves it';
      undo(run) -> not complete, the area skipped "changed since" and the
      kind skipped "changed since" with keys ["in use"]; ta_pre2 is still
      demo_sod with the foreign polygon, demo_sod still exists.
Cases (runs 9 and 10):
  (o) the run changes a pre-existing place's terrain: fixture location
      loc_demo_field_o with terrain "grass", description "before"; t1
      add_terrain_type demo_turf_o, t1 update_location{id loc_demo_field_o,
      patch {terrain demo_turf_o}}.
      discard_preview -> the plain line 'terrain kind demo_turf_o "Demo Turf"'
      (no "still used": the restore puts grass back before the kind goes);
      undo(run) -> complete, terrain "grass" again, demo_turf gone.
  (o2) the same (loc_demo_field_o2 / demo_turf_o2), plus a FOREIGN edit of another field (description) after
      the run's write: the stored terrain is still what the run wrote, so the
      same plain line and a complete undo; terrain "grass" again, the
      foreign description kept.
Cases (run 11):
  (m) the world default ground names a run-created kind: t1 add_terrain_type
      demo_meadow, then the setting game.default_terrain_kind set to
      demo_meadow (in memory, the temp config). Same-turn delete_created of
      the kind -> refused, names "default ground"; discard_preview -> the
      kind's line says it stays ("the discard leaves it"); undo(run) -> not
      complete, the kind skipped ["in use"], demo_meadow still exists.
Cases (run 12):
  (p) an area the run created BEFORE the kind, repainted to it, then edited
      by somebody else: t1 add_terrain_area{kind grass} -> area P; t1
      add_terrain_type demo_pa; t1 update_terrain_area{id P, kind demo_pa};
      a FOREIGN save_area of P with another polygon. The undo walks
      newest-first: the repaint's restore is skipped (P is no longer what the
      run wrote), so when it reaches demo_pa P still exists and is demo_pa
      -> the kind skipped ["in use"]; only after that does the oldest entry
      delete P. So discard_preview -> the kind's line says 'is still used by
      terrain area P' and 'the discard leaves it', plus the line
      'terrain area P (demo_pa)'; undo(run) -> not complete, P gone,
      demo_pa still exists (an unused world row, as the preview said).
Cases (run 13):
  (q) a water area the run creates AFTER the kind, with water.bed_kind =
      that kind: t1 add_terrain_type demo_bed, t1 add_terrain_area{kind
      water, water {bed_kind demo_bed}}. The area's deletion is newer than
      the kind's -> discard_preview has the plain line
      'terrain kind demo_bed "Demo Bed"'; undo(run) complete, the area and
      the kind gone, the world kinds equal to before the run.
Cases (run 14):
  (r) a PRE-EXISTING water area given bed_kind by the run: fixture ta_lake_r
      (kind water) snapshot S taken after its save; t1 add_terrain_type
      demo_bed_r, t1 update_terrain_area{id ta_lake_r, water {bed_kind
      demo_bed_r}}. The restore (newer than the kind) puts S back first, S
      names no demo_bed_r -> plain preview line; undo(run) complete, the
      area row == S exactly, demo_bed_r gone.
Cases (run 15):
  (t) a kind edited by somebody else: t1 add_terrain_type demo_edit "Demo
      Edit"; a FOREIGN save_world_type of the same row with name "Foreign
      Edit". delete_created in t1 and in t2 -> refused "changed since";
      discard_preview -> 'terrain kind demo_edit was changed since — the
      discard leaves it alone'; undo(run) -> not complete, skipped
      "changed since" with keys ["name"]; the row keeps "Foreign Edit".
Cases (run 16):
  (u) deleted cross-turn, re-created by somebody else: t1 add_terrain_type
      demo_back, t2 delete_created -> ok; a FOREIGN save_world_type of
      demo_back (name "Foreign Back"). discard_preview -> one line
      'terrain kind demo_back was deleted by this run and exists again — the
      discard leaves it alone' and nothing else naming demo_back;
      undo(run) -> not complete, both entries skipped (the re-creation
      finds the row present, the older creation is then left alone), the
      foreign row kept with "Foreign Back".
Cases (run 17):
  (v) create, cross-turn delete, create again: t1 add_terrain_type
      demo_twice, t2 delete_created, t3 add_terrain_type demo_twice.
      discard_preview -> exactly one line naming demo_twice, the plain
      'terrain kind demo_twice "Demo Twice"'; undo(run) complete, the kind
      gone, the world kinds equal to before the run.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_ttypes_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_ttypes_"))
paths.init(STORAGE)
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)

from app.core import config, db  # noqa: E402

config.load(paths.get_config_path())
db.init_schema()

from app.core import terrain_types as tt  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.models import terrain  # noqa: E402
from app.models.world import get_location_by_id, upsert_location  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


def call(rid, turn, tool, args):
    return wt.run_tool(wt.ToolCtx(run_id=rid, turn=turn), tool, args)


def last_entry(rid):
    return wr.steps(rid)[-1]


def world_kinds():
    return {k for k, src in tt.sources().items() if src == "world"}


SQUARE = [[0, 0], [20, 0], [20, 20], [0, 20]]
COBBLE = {"kind": "demo_cobble", "name": "Cobblestone", "color": "#888888",
          "speed_factor": 1.2}

run = wr.create_run("ttypes", "m", "p", "u", 60, 300000)

print("(a) add_terrain_type")
res = call(run, 1, "add_terrain_type", dict(COBBLE))
check("(a) ok", res.ok and res.wrote, res.line)
ent = last_entry(run)
check("(a) journal target", (ent.get("target_kind"), ent.get("target_id"))
      == ("terrain_type", "demo_cobble"), ent)
check("(a) journal inverse", ent.get("inverse")
      == {"op": "delete_terrain_type", "kind": "demo_cobble"}, ent.get("inverse"))
check("(a) speed 1.2 in the catalog",
      (tt.effective_catalog().get("demo_cobble") or {}).get("speed_factor") == 1.2,
      tt.effective_catalog().get("demo_cobble"))
ov = call(run, 1, "world_overview", {})
check("(a) overview line", 'demo_cobble "Cobblestone" (speed ×1.2)' in ov.line, ov.line)

print("(b) existing kinds")
res = call(run, 1, "add_terrain_type", dict(COBBLE))
check("(b) again -> already exists (world)",
      not res.ok and "already exists (world)" in res.line, res.line)
res = call(run, 1, "add_terrain_type", {"kind": "grass", "name": "G", "color": "#00aa00"})
check("(b) shipped -> already exists (shared)",
      not res.ok and "already exists (shared)" in res.line, res.line)
check("(b) world rows unchanged", world_kinds() == {"demo_cobble"}, world_kinds())

print("(c) refusals")
for args, want in (
        (dict(COBBLE, kind="demo_fast", speed_factor=3), f"would be stored as {tt.SPEED_MAX}"),
        (dict(COBBLE, kind="demo_fast", speed_factor=1.234), "would be stored as 1.23"),
        (dict(COBBLE, kind="demo_fast", color="red"), "invalid color"),
        (dict(COBBLE, kind="demo_fast", movement="swim"), "movement"),
        ({"kind": "demo_fast", "color": "#888888"}, "name")):
    res = call(run, 1, "add_terrain_type", args)
    check(f"(c) {args} refused ({want})", not res.ok and want in res.line
          and not res.wrote, res.line)
    check(f"(c) {args} journal refused", last_entry(run).get("kind") == "refused",
          last_entry(run))
check("(c) no world row added", world_kinds() == {"demo_cobble"}, world_kinds())

print("(h) bad kind format")
res = call(run, 1, "add_terrain_type", dict(COBBLE, kind="Demo Cobble"))
check("(h) refused with the sanitizer's message",
      not res.ok and "invalid terrain kind: 'Demo Cobble'" in res.line, res.line)
check("(h) nothing stored", world_kinds() == {"demo_cobble"}, world_kinds())

print("(s) surface")
from app.core.surface_textures import library_kinds  # noqa: E402
LIB = sorted(library_kinds())
check("(s) the shared surface library is non-empty", bool(LIB), LIB)
res = call(run, 1, "add_terrain_type", dict(COBBLE, kind="demo_paved", surface="whatever"))
check("(s) unknown surface refused",
      not res.ok and "'surface' must be a kind of the surface library" in res.line, res.line)
check("(s) nothing stored", world_kinds() == {"demo_cobble"}, world_kinds())
if LIB:
    res = call(run, 1, "add_terrain_type", dict(COBBLE, kind="demo_paved", surface=LIB[0]))
    check("(s) library surface ok", res.ok, res.line)
    check("(s) catalog row carries the surface",
          (tt.effective_catalog().get("demo_paved") or {}).get("surface") == LIB[0],
          tt.effective_catalog().get("demo_paved"))

print("(w) water kind")
res = call(run, 1, "add_terrain_type", {"kind": "demo_pond", "name": "Demo Pond",
                                        "color": "#3366aa", "water": {"water_depth_m": 99}})
check("(w) depth 99 refused", not res.ok and "would be stored as" in res.line, res.line)
res = call(run, 1, "add_terrain_type", {"kind": "demo_pond", "name": "Demo Pond",
                                        "color": "#3366aa", "water": {"water_depth_m": 2}})
check("(w) ok", res.ok, res.line)
check("(w) is water", tt.is_water_kind("demo_pond"), tt.get_type("demo_pond"))
check("(w) depth stored", ((tt.get_type("demo_pond") or {}).get("meta") or {})
      .get("water_depth_m") == 2.0, tt.get_type("demo_pond"))

print("(d) the new kind is usable")
res = call(run, 1, "add_terrain_area", {"kind": "demo_cobble", "polygon": SQUARE})
check("(d) area ok", res.ok, res.line)
AREA = last_entry(run).get("target_id")

prev = wu.discard_preview(run)
check("(d) preview names the kinds",
      'terrain kind demo_cobble "Cobblestone"' in prev
      and 'terrain kind demo_pond "Demo Pond"' in prev, prev)

print("(e) undo")
u = wu.undo(run)
check("(e) complete", u["complete"], u)
check("(e) area gone", terrain.get_area(AREA) is None, AREA)
check("(e) kinds gone", tt.get_type("demo_cobble") is None and tt.get_type("demo_pond") is None
      and world_kinds() == set(), world_kinds())

print("(f) foreign area of the kind")
wr.set_status(run, "accepted")
run2 = wr.create_run("ttypes-2", "m", "p", "u", 60, 300000)
res = call(run2, 1, "add_terrain_type", dict(COBBLE))
check("(f) added", res.ok, res.line)
foreign = terrain.save_area({"id": "ta_foreign", "kind": "demo_cobble",
                             "polygon": [[50, 50], [60, 50], [60, 60], [50, 60]]})
prev = wu.discard_preview(run2)
check("(f) preview lists the kind",
      any(line.startswith('terrain kind demo_cobble "Cobblestone"') for line in prev), prev)
check("(f) preview says it stays",
      any("demo_cobble" in line and "leaves it" in line for line in prev), prev)
u = wu.undo(run2)
check("(f) not complete", not u["complete"], u)
check("(f) skipped in use",
      any(s.get("reason") == wu.REASON_CHANGED and s.get("keys") == ["in use"]
          for s in u["skipped"]), u)
check("(f) foreign area untouched", terrain.get_area("ta_foreign") is not None)
check("(f) kind still there", tt.get_type("demo_cobble") is not None)

print("(g) foreign use through bed_kind")
wr.set_status(run2, "accepted")
run3 = wr.create_run("ttypes-3", "m", "p", "u", 60, 300000)
res = call(run3, 1, "add_terrain_type", {"kind": "demo_gravel", "name": "Demo Gravel",
                                         "color": "#777777"})
check("(g) added", res.ok, res.line)
terrain.save_area({"id": "ta_lake", "kind": "water",
                   "polygon": [[100, 100], [120, 100], [120, 120], [100, 120]],
                   "meta": {"bed_kind": "demo_gravel"}})
check("(g) fixture keeps bed_kind",
      ((terrain.get_area("ta_lake") or {}).get("meta") or {}).get("bed_kind") == "demo_gravel",
      terrain.get_area("ta_lake"))
u = wu.undo(run3)
check("(g) skipped in use",
      not u["complete"] and any(s.get("reason") == wu.REASON_CHANGED
                                and s.get("keys") == ["in use"] for s in u["skipped"]), u)
check("(g) kind still there", tt.get_type("demo_gravel") is not None)

print("(i) same-turn delete_created")
wr.set_status(run3, "accepted")
run4 = wr.create_run("ttypes-4", "m", "p", "u", 60, 300000)
res = call(run4, 1, "add_terrain_type", {"kind": "demo_moss", "name": "Demo Moss",
                                         "color": "#226622"})
check("(i) added", res.ok, res.line)
res = call(run4, 1, "add_terrain_area", {"kind": "demo_moss", "polygon": SQUARE})
MOSS_AREA = last_entry(run4).get("target_id")
check("(i) area", res.ok and bool(MOSS_AREA), res.line)
res = call(run4, 1, "delete_created", {"kind": "terrain_type", "id": "demo_moss"})
check("(i) refused while in use", not res.ok and MOSS_AREA in res.line, res.line)
check("(i) kind still there", tt.get_type("demo_moss") is not None)
res = call(run4, 1, "delete_created", {"kind": "terrain", "id": MOSS_AREA})
check("(i) area deleted", res.ok, res.line)
res = call(run4, 1, "delete_created", {"kind": "terrain_type", "id": "demo_moss"})
check("(i) kind deleted", res.ok and tt.get_type("demo_moss") is None, res.line)
check("(i) preview empty", wu.discard_preview(run4) == [], wu.discard_preview(run4))
u = wu.undo(run4)
check("(i) undo complete, nothing back", u["complete"] and tt.get_type("demo_moss") is None, u)

print("(j) earlier-turn delete_created")
wr.set_status(run4, "accepted")
run5 = wr.create_run("ttypes-5", "m", "p", "u", 60, 300000)
res = call(run5, 1, "add_terrain_type", {"kind": "demo_clay", "name": "Demo Clay",
                                         "color": "#aa6633", "passable": False})
check("(j) added", res.ok, res.line)
CLAY = tt.get_type("demo_clay")
res = call(run5, 2, "delete_created", {"kind": "terrain_type", "id": "demo_clay"})
check("(j) ok, earlier turn", res.ok and "earlier turn" in res.line, res.line)
check("(j) gone", tt.get_type("demo_clay") is None)
prev = wu.discard_preview(run5)
check("(j) no preview line (net absent)", not any("demo_clay" in x for x in prev), prev)
u = wu.undo(run5, turn=2)
check("(j) undo turn 2 complete", u["complete"], u)
check("(j) re-created exactly", tt.get_type("demo_clay") == CLAY, (tt.get_type("demo_clay"), CLAY))
u = wu.undo(run5)
check("(j) undo run complete, gone", u["complete"] and tt.get_type("demo_clay") is None, u)

print("(k) foreign location of the kind")
wr.set_status(run5, "accepted")
run6 = wr.create_run("ttypes-6", "m", "p", "u", 60, 300000)
res = call(run6, 3, "add_terrain_type", {"kind": "demo_loam", "name": "Demo Loam",
                                         "color": "#664422"})
check("(k) added", res.ok, res.line)
upsert_location({"id": "loc_demo_farm", "name": "Demo Farm", "terrain": "demo_loam"},
                sync_world=False)
check("(k) fixture terrain stored",
      (get_location_by_id("loc_demo_farm") or {}).get("terrain") == "demo_loam",
      get_location_by_id("loc_demo_farm"))
res = call(run6, 4, "delete_created", {"kind": "terrain_type", "id": "demo_loam"})
check("(k) refused, names the location", not res.ok and "loc_demo_farm" in res.line, res.line)
u = wu.undo(run6)
check("(k) undo skipped in use",
      not u["complete"] and any(s.get("keys") == ["in use"] for s in u["skipped"]), u)
check("(k) kind still there", tt.get_type("demo_loam") is not None)

print("(l) the run's own change of a pre-existing area")
wr.set_status(run6, "accepted")
terrain.save_area({"id": "ta_pre", "kind": "grass",
                   "polygon": [[300, 300], [320, 300], [320, 320], [300, 320]]})
run7 = wr.create_run("ttypes-7", "m", "p", "u", 60, 300000)
res = call(run7, 1, "add_terrain_type", {"kind": "demo_peat", "name": "Demo Peat",
                                         "color": "#443322"})
check("(l) added", res.ok, res.line)
res = call(run7, 1, "update_terrain_area", {"id": "ta_pre", "kind": "demo_peat"})
check("(l) area repainted", res.ok and terrain.get_area("ta_pre")["kind"] == "demo_peat", res.line)
prev = wu.discard_preview(run7)
check("(l) preview: the plain line", 'terrain kind demo_peat "Demo Peat"' in prev, prev)
u = wu.undo(run7)
check("(l) undo complete", u["complete"], u)
check("(l) ta_pre grass again, kind gone",
      terrain.get_area("ta_pre")["kind"] == "grass" and tt.get_type("demo_peat") is None,
      terrain.get_area("ta_pre"))

print("(n) a repainted pre-existing area edited by somebody else")
wr.set_status(run7, "accepted")
terrain.save_area({"id": "ta_pre2", "kind": "grass",
                   "polygon": [[400, 400], [420, 400], [420, 420], [400, 420]]})
run8 = wr.create_run("ttypes-8", "m", "p", "u", 60, 300000)
res = call(run8, 1, "add_terrain_type", {"kind": "demo_sod", "name": "Demo Sod",
                                         "color": "#335522"})
check("(n) added", res.ok, res.line)
res = call(run8, 1, "update_terrain_area", {"id": "ta_pre2", "kind": "demo_sod"})
check("(n) area repainted", res.ok, res.line)
FOREIGN_POLY = [[400, 400], [430, 400], [430, 430], [400, 430]]
terrain.save_area(dict(terrain.get_area("ta_pre2"), polygon=FOREIGN_POLY))
prev = wu.discard_preview(run8)
check("(n) preview: still used by ta_pre2, the discard leaves it",
      any(x.startswith('terrain kind demo_sod "Demo Sod"') and "is still used by terrain area ta_pre2"
          in x and "the discard leaves it" in x for x in prev), prev)
u = wu.undo(run8)
check("(n) not complete", not u["complete"], u)
check("(n) kind skipped in use",
      any(s.get("reason") == wu.REASON_CHANGED and s.get("keys") == ["in use"]
          for s in u["skipped"]), u)
check("(n) area skipped changed since",
      any(s.get("reason") == wu.REASON_CHANGED and s.get("keys") != ["in use"]
          for s in u["skipped"]), u)
cur = terrain.get_area("ta_pre2") or {}
check("(n) area still demo_sod with the foreign polygon",
      cur.get("kind") == "demo_sod" and cur.get("polygon") == FOREIGN_POLY, cur)
check("(n) kind still there", tt.get_type("demo_sod") is not None)

print("(o) the run changes a pre-existing place's terrain")
wr.set_status(run8, "accepted")
for tag, foreign_edit in (("o", False), ("o2", True)):
    lid = f"loc_demo_field_{tag}"
    upsert_location({"id": lid, "name": "Demo Field", "terrain": "grass",
                     "description": "before"}, sync_world=False)
    rid = wr.create_run(f"ttypes-9{tag}", "m", "p", "u", 60, 300000)
    kind = f"demo_turf_{tag}"
    res = call(rid, 1, "add_terrain_type", {"kind": kind, "name": "Demo Turf",
                                            "color": "#447733"})
    check(f"({tag}) added", res.ok, res.line)
    res = call(rid, 1, "update_location", {"id": lid, "patch": {"terrain": kind}})
    check(f"({tag}) terrain changed",
          res.ok and (get_location_by_id(lid) or {}).get("terrain") == kind, res.line)
    if foreign_edit:
        upsert_location(dict(get_location_by_id(lid), description="foreign"),
                        sync_world=False)
    prev = wu.discard_preview(rid)
    check(f"({tag}) preview: the plain line", f'terrain kind {kind} "Demo Turf"' in prev, prev)
    u = wu.undo(rid)
    check(f"({tag}) undo complete", u["complete"], u)
    loc = get_location_by_id(lid) or {}
    check(f"({tag}) terrain grass again, kind gone",
          loc.get("terrain") == "grass" and tt.get_type(kind) is None, loc)
    check(f"({tag}) description", loc.get("description")
          == ("foreign" if foreign_edit else "before"), loc.get("description"))
    wr.set_status(rid, "accepted")

print("(m) the world default ground names the kind")
run11 = wr.create_run("ttypes-11", "m", "p", "u", 60, 300000)
res = call(run11, 1, "add_terrain_type", {"kind": "demo_meadow", "name": "Demo Meadow",
                                          "color": "#55aa44"})
check("(m) added", res.ok, res.line)
config._CONFIG.setdefault("game", {})["default_terrain_kind"] = "demo_meadow"
check("(m) setting read back", config.get("game.default_terrain_kind") == "demo_meadow")
res = call(run11, 1, "delete_created", {"kind": "terrain_type", "id": "demo_meadow"})
check("(m) delete_created refused, names the default ground",
      not res.ok and "default ground" in res.line, res.line)
prev = wu.discard_preview(run11)
check("(m) preview: the kind stays",
      any(x.startswith('terrain kind demo_meadow "Demo Meadow"') and "default ground" in x
          and "the discard leaves it" in x for x in prev), prev)
u = wu.undo(run11)
check("(m) undo skipped in use",
      not u["complete"] and any(s.get("keys") == ["in use"] for s in u["skipped"]), u)
check("(m) kind still there", tt.get_type("demo_meadow") is not None)
config._CONFIG["game"].pop("default_terrain_kind", None)

print("(p) a run-created area repainted to a later kind, edited by somebody else")
wr.set_status(run11, "accepted")
run12 = wr.create_run("ttypes-12", "m", "p", "u", 60, 300000)
res = call(run12, 1, "add_terrain_area",
           {"kind": "grass", "polygon": [[500, 500], [520, 500], [520, 520], [500, 520]]})
P_AREA = last_entry(run12).get("target_id")
check("(p) area added", res.ok and bool(P_AREA), res.line)
res = call(run12, 1, "add_terrain_type", {"kind": "demo_pa", "name": "Demo Pa",
                                          "color": "#556677"})
check("(p) kind added", res.ok, res.line)
res = call(run12, 1, "update_terrain_area", {"id": P_AREA, "kind": "demo_pa"})
check("(p) area repainted", res.ok and terrain.get_area(P_AREA)["kind"] == "demo_pa", res.line)
terrain.save_area(dict(terrain.get_area(P_AREA),
                       polygon=[[500, 500], [530, 500], [530, 530], [500, 530]]))
prev = wu.discard_preview(run12)
check("(p) preview: the kind is still used by the area and stays",
      any(x.startswith('terrain kind demo_pa "Demo Pa"')
          and f"is still used by terrain area {P_AREA}" in x
          and "the discard leaves it" in x for x in prev), prev)
check("(p) preview: the area goes", f"terrain area {P_AREA} (demo_pa)" in prev, prev)
u = wu.undo(run12)
check("(p) not complete, the kind skipped in use",
      not u["complete"] and any(s.get("keys") == ["in use"] for s in u["skipped"]), u)
check("(p) area gone", terrain.get_area(P_AREA) is None, terrain.get_area(P_AREA))
check("(p) kind stays (as the preview said)", tt.get_type("demo_pa") is not None)

print("(q) a run-created water area with bed_kind of a run kind")
wr.set_status(run12, "accepted")
KINDS_BEFORE = world_kinds()
run13 = wr.create_run("ttypes-13", "m", "p", "u", 60, 300000)
res = call(run13, 1, "add_terrain_type", {"kind": "demo_bed", "name": "Demo Bed",
                                          "color": "#776655"})
check("(q) kind added", res.ok, res.line)
res = call(run13, 1, "add_terrain_area",
           {"kind": "water", "polygon": [[600, 600], [620, 600], [620, 620], [600, 620]],
            "water": {"bed_kind": "demo_bed"}})
Q_AREA = last_entry(run13).get("target_id")
check("(q) area with bed_kind",
      res.ok and ((terrain.get_area(Q_AREA) or {}).get("meta") or {}).get("bed_kind")
      == "demo_bed", (res.line, terrain.get_area(Q_AREA)))
prev = wu.discard_preview(run13)
check("(q) preview: the plain line", 'terrain kind demo_bed "Demo Bed"' in prev, prev)
u = wu.undo(run13)
check("(q) undo complete", u["complete"], u)
check("(q) area and kind gone, world kinds as before",
      terrain.get_area(Q_AREA) is None and tt.get_type("demo_bed") is None
      and world_kinds() == KINDS_BEFORE, world_kinds())

print("(r) a pre-existing water area given bed_kind by the run")
wr.set_status(run13, "accepted")
terrain.save_area({"id": "ta_lake_r", "kind": "water",
                   "polygon": [[700, 700], [720, 700], [720, 720], [700, 720]]})
LAKE_R = terrain.get_area("ta_lake_r")
run14 = wr.create_run("ttypes-14", "m", "p", "u", 60, 300000)
res = call(run14, 1, "add_terrain_type", {"kind": "demo_bed_r", "name": "Demo Bed R",
                                          "color": "#665544"})
check("(r) kind added", res.ok, res.line)
res = call(run14, 1, "update_terrain_area",
           {"id": "ta_lake_r", "water": {"bed_kind": "demo_bed_r"}})
check("(r) bed_kind set",
      res.ok and ((terrain.get_area("ta_lake_r") or {}).get("meta") or {}).get("bed_kind")
      == "demo_bed_r", (res.line, terrain.get_area("ta_lake_r")))
prev = wu.discard_preview(run14)
check("(r) preview: the plain line", 'terrain kind demo_bed_r "Demo Bed R"' in prev, prev)
u = wu.undo(run14)
check("(r) undo complete", u["complete"], u)
check("(r) area row exactly as before", terrain.get_area("ta_lake_r") == LAKE_R,
      (terrain.get_area("ta_lake_r"), LAKE_R))
check("(r) kind gone", tt.get_type("demo_bed_r") is None)

print("(t) a kind edited by somebody else")
wr.set_status(run14, "accepted")
run15 = wr.create_run("ttypes-15", "m", "p", "u", 60, 300000)
res = call(run15, 1, "add_terrain_type", {"kind": "demo_edit", "name": "Demo Edit",
                                          "color": "#445566"})
check("(t) kind added", res.ok, res.line)
tt.save_world_type(dict(tt.get_type("demo_edit"), name="Foreign Edit"))
for turn in (1, 2):
    res = call(run15, turn, "delete_created", {"kind": "terrain_type", "id": "demo_edit"})
    check(f"(t) delete_created t{turn} refused, changed since",
          not res.ok and "changed since" in res.line, res.line)
prev = wu.discard_preview(run15)
check("(t) preview: changed since, left alone",
      "terrain kind demo_edit was changed since — the discard leaves it alone" in prev, prev)
u = wu.undo(run15)
check("(t) undo skipped changed since, keys ['name']",
      not u["complete"] and any(s.get("reason") == wu.REASON_CHANGED
                                and s.get("keys") == ["name"] for s in u["skipped"]), u)
check("(t) foreign name kept",
      (tt.get_type("demo_edit") or {}).get("name") == "Foreign Edit", tt.get_type("demo_edit"))

print("(u) deleted cross-turn, re-created by somebody else")
wr.set_status(run15, "accepted")
run16 = wr.create_run("ttypes-16", "m", "p", "u", 60, 300000)
res = call(run16, 1, "add_terrain_type", {"kind": "demo_back", "name": "Demo Back",
                                          "color": "#334455"})
check("(u) kind added", res.ok, res.line)
res = call(run16, 2, "delete_created", {"kind": "terrain_type", "id": "demo_back"})
check("(u) deleted in t2", res.ok and tt.get_type("demo_back") is None, res.line)
tt.save_world_type({"kind": "demo_back", "name": "Foreign Back", "color": "#334455"})
prev = wu.discard_preview(run16)
back = [x for x in prev if "demo_back" in x]
check("(u) preview: one 'exists again' line",
      len(back) == 1 and back[0].endswith(
          "demo_back was deleted by this run and exists again — the discard leaves it alone"),
      prev)
u = wu.undo(run16)
check("(u) undo not complete, both entries skipped",
      not u["complete"] and len(u["skipped"]) == 2, u)
check("(u) foreign row kept",
      (tt.get_type("demo_back") or {}).get("name") == "Foreign Back", tt.get_type("demo_back"))

print("(v) create, cross-turn delete, create again")
wr.set_status(run16, "accepted")
KINDS_BEFORE = world_kinds()
run17 = wr.create_run("ttypes-17", "m", "p", "u", 60, 300000)
TWICE = {"kind": "demo_twice", "name": "Demo Twice", "color": "#223344"}
res = call(run17, 1, "add_terrain_type", dict(TWICE))
check("(v) t1 added", res.ok, res.line)
res = call(run17, 2, "delete_created", {"kind": "terrain_type", "id": "demo_twice"})
check("(v) t2 deleted", res.ok and tt.get_type("demo_twice") is None, res.line)
res = call(run17, 3, "add_terrain_type", dict(TWICE))
check("(v) t3 added again", res.ok, res.line)
prev = wu.discard_preview(run17)
check("(v) preview: one plain line",
      [x for x in prev if "demo_twice" in x] == ['terrain kind demo_twice "Demo Twice"'], prev)
u = wu.undo(run17)
check("(v) undo complete", u["complete"], u)
check("(v) kind gone, world kinds as before",
      tt.get_type("demo_twice") is None and world_kinds() == KINDS_BEFORE, world_kinds())

print("(x) a foreign edit between two run edits of one area (the restore chain stops there)")
wr.set_status(run17, "accepted")
# ta_chain (grass) exists before the run. t1 add_terrain_type demo_chain; t1
# update_terrain_area{ta_chain, kind demo_chain} (edit 1: before = grass row);
# somebody relabels ta_chain "Foreign" (terrain.save_area); t2 update_terrain_area
# {ta_chain, label "Run Label"} (edit 2: before = the demo_chain row labelled
# "Foreign"). The undo walks newest-first: edit 2 still finds what it wrote and
# puts back demo_chain + "Foreign"; edit 1 then finds "Foreign", not what it wrote:
# changed since, skipped — ta_chain keeps demo_chain, so the kind is in use and
# stays. The preview must say so (the old chain assumption took edit 1's grass).
terrain.save_area({"id": "ta_chain", "kind": "grass",
                   "polygon": [[800, 800], [820, 800], [820, 820], [800, 820]]})
run18 = wr.create_run("ttypes-18", "m", "p", "u", 60, 300000)
res = call(run18, 1, "add_terrain_type", {"kind": "demo_chain", "name": "Demo Chain",
                                          "color": "#556677"})
check("(x) kind added", res.ok, res.line)
res = call(run18, 1, "update_terrain_area", {"id": "ta_chain", "kind": "demo_chain"})
check("(x) edit 1", res.ok, res.line)
row = terrain.get_area("ta_chain")
terrain.save_area(dict(row, meta=dict(row.get("meta") or {}, label="Foreign")))
res = call(run18, 2, "update_terrain_area", {"id": "ta_chain", "label": "Run Label"})
check("(x) edit 2", res.ok, res.line)
prev = wu.discard_preview(run18)
line = next((x for x in prev if x.startswith('terrain kind demo_chain "Demo Chain"')), "")
check("(x) preview: the kind stays, used by ta_chain",
      "is still used by" in line and "ta_chain" in line and "leaves it" in line, prev)
u = wu.undo(run18)
check("(x) undo not complete", not u["complete"], u)
check("(x) ta_chain keeps demo_chain, label Foreign",
      (terrain.get_area("ta_chain") or {}).get("kind") == "demo_chain"
      and ((terrain.get_area("ta_chain") or {}).get("meta") or {}).get("label") == "Foreign",
      terrain.get_area("ta_chain"))
check("(x) kind still exists", tt.get_type("demo_chain") is not None)

if failures:
    print(f"\nFAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("\nall ok")
