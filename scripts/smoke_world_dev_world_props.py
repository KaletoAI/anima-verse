#!/usr/bin/env python3
"""Smoke: World Dev free mode — prop search and free-standing world props
(gap 6, E10).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p2-buildings-terrain.md, Task 7.
A temp world (paths.init BEFORE any world-DB import), an EMPTY ANIMATION_CLIPS_DIR;
no server, no LLM. Every tool call goes through world_dev_tools.run_tool
exactly as the agent loop calls it.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_world_props.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Props (fixtures, through the props core — props.create_prop; the id is a slug
of the name plus a short hash and is read back at runtime):
  WELL  = create_prop(name="Demo Well", category="outdoor", width_m 2,
          depth_m 2, height_m 1.5, tags ["water", "stone"], mount "floor")
  BENCH = create_prop(name="Demo Bench", category="furniture", width_m 1.8,
          depth_m 0.6, height_m 0.9, tags ["seat"], mount "floor")
  LAMP  = create_prop(name="Demo Lamp", category="light", width_m 0.3,
          tags ["light"], mount "wall")  (depth/height become the largest
          given value, 0.3 — create_prop's "rough cube" rule)
  None of them has a mesh (create_prop writes the sidecar only), so every
  find_props line ends " · no mesh yet".
find_props line (plan Task 7): '<id> "<name>" <category> <w>×<d>×<h> m mount
<mount> tags <t1>, <t2> model /assets/props/<id>/model' — numbers through
world_dev_tools._g (no trailing ".0"): the well is "2×2×1.5 m".

World props: world_props.sanitize_world_prop rounds x/z to 2 decimals, wraps
yaw_deg modulo 360 (1 decimal) and CLAMPS offset_y to ±MAX_OFFSET_Y (50.0, read
from the module at runtime) — the free rule refuses both rewrites
(_refuse_rewritten): yaw 450 -> 450 % 360 = 90 -> "would be stored as 90.0";
offset_y 80 -> "would be stored as 50.0". A row is {id, prop_id, x, z,
yaw_deg, offset_y, variant} (world_props._row): (b) sends x 10, z 5, yaw 90
and no offset/variant -> {x 10.0, z 5.0, yaw_deg 90.0, offset_y 0.0,
variant None}.

Ground: the shipped catalog (shared/terrain/types.json) has "rock" with
passable false. A fixture rock area (200,0)-(220,20) is saved through
terrain.save_area before the run; a prop placed at (210, 10) is stored and the
result warns "rock, which nobody can walk on".
Place: a fixture location "loc_demo_yard" (pin (100, 100), yaw 0, a drawn
10 m square boundary = map_layout_apply.seed_boundary()) stored through
upsert_location before the run; a prop at (101, 101) lies 1 m from the pin,
inside the ±5 m square -> the result warns 'inside the outline of place
loc_demo_yard "Demo Yard"'.

Cases (run 1):
  (a) t1 find_props{query "well"} -> exactly 1 line, starting with WELL, the
      full line as above. find_props{category "furniture"} -> 1 line (BENCH);
      {tag "light"} -> 1 line (LAMP); {mount "wall"} -> LAMP only;
      {mount "sideways"} -> refused naming the mount kinds (props.MOUNT_KINDS);
      {query "nothing-like-this"} -> "no props match".
  (b) t1 place_world_prop{prop_id WELL, x 10, z 5, yaw 90} -> ok; the line
      names the new id and WELL; the stored row (list_world_props) is
      {id, prop_id WELL, x 10.0, z 5.0, yaw_deg 90.0, offset_y 0.0,
      variant None}; the journal row's target is ("world_prop", id).
  (c) yaw 450 -> refused "would be stored as 90.0"; offset_y 80 -> refused
      "would be stored as 50.0"; prop_id "nope" -> refused "unknown prop";
      x 10.123 -> refused "would be stored as 10.12"; variant -1 -> refused;
      an unknown key -> refused. None of them stored a row (count stays 1).
  (b2) t1 place at (210, 10) -> ok, warning "nobody can walk on";
      place at (101, 101) -> ok, warning "inside the outline of place
      loc_demo_yard"; place at (50, 50) — open ground (no fixture area, the
      yard square is (95..105, 95..105)) -> ok, no "warnings" in the line.
      Rows now 4 (the well of (b) + these three).
  (g) t1 map_region{0,0,20,20} lists "prop <id> <WELL> (10,5)"; the rock
      prop at (210,10) is not in that box.
  (d) discard_preview -> contains 'world prop <id> (<WELL>)' and one line
      per created prop (4 "world prop" lines).
  (e) t2 delete_created{kind "world_prop", id} -> ok "an earlier turn"; the
      row is gone and discard_preview has no line for it any more (net
      absent). undo(run, turn 2) -> complete, the row is back and equal to
      the row read after (b). undo(run) -> complete, no world prop left.
  (h) same-turn delete: run 1b, t1 place then delete_created in t1 -> gone;
      the creating entry is undone; undo(run) -> complete, still nothing.
Cases (run 2):
  (f) t1 place WELL at (30, 30) -> ok; a FOREIGN edit moves the row with
      save_world_prop({..., x 11}, must_exist=True); discard_preview BEFORE
      the undo -> exactly one line, 'world prop <id> (<WELL>) was changed
      since — the discard leaves it alone' (the undo below skips it, so it
      is not announced as going); undo(run) -> not complete, the skip
      reason is "changed since", the row stays at x 11.0.
  Only one run may be open at a time (world_dev_runs' unique index), so each
  finished run is set to "accepted" before the next one is created.
  (k) cap: with MAX_WORLD_PROPS patched to the current count the call is
      refused "holds its limit of", nothing stored, journal row "refused".
Cases (run 4):
  (m) t1 place WELL at (40, 40); a FOREIGN edit moves it to x 12; t2
      delete_created{world_prop} -> refused "could not delete world prop
      <id>: changed since" (the undo of the creating step would leave the
      foreign row alone, so a delete here could only be re-created as the
      foreign row) — the row stays at x 12.0, journal row "refused".
      discard_preview -> exactly the one "was changed since" line; undo(run)
      -> not complete ("changed since"), the row still at x 12.0.
Cases (run 5):
  (n) t1 place WELL at x -0.0, z 60 -> ok, the line reads "at (0,60)" (the
      stored x is 0.0; _g of 0.0 is "0"). t2 delete_created -> ok (earlier
      turn), row gone. MAX_WORLD_PROPS patched to the current count (the
      re-creation hits the cap): undo(run) -> the turn-2 re-creation is
      skipped with reason "re-creation refused" and an "error" naming the
      cap ("at most", world_props.save_world_prop's message), NOT "undo
      failed"; the creating entry then finds it "already gone". The creating
      entry of the same target was handled in the same pass, so the world
      ends as before the run (absent): the refused record carries
      net_absent True and complete is True; no row of it exists.
Cases (run 6):
  (n2) the same, but undo(run, turn 2) only: the creating entry (turn 1) is
      not in the pass, the prop should exist after that rollback and does
      not -> the refused record has no net_absent, complete is False. Then
      undo(run) (cap restored; only the turn-1 entry is left) -> the
      creating entry finds it "already gone" -> complete True.
Cases (run 7):
  (p) t1 place WELL at (70, 70), t2 delete_created, then somebody else
      saves a row under the same id (save_world_prop of the read row):
      discard_preview -> exactly 'world prop <id> was deleted by this run
      and exists again — the discard leaves it alone' (the kind label, not
      the raw kind "world_prop").
  (q) delete_created{kind "world_prop", id "wp_nope"} -> refused
      "world prop 'wp_nope' was not created by this run".
  (r) yaw at a full turn (sanitize_world_prop): 359.96 % 360 = 359.96,
      round 1 -> 360.0, which is a full turn -> stored 0.0; -0.04 % 360 =
      359.96 -> 0.0 likewise; 359.94 -> 359.9 stays. The tool: yaw 359.96
      -> refused "would be stored as 0.0" (ONE retry with 0 lands it, not
      the old 360.0 / 0.0 loop); yaw 360 -> refused "would be stored as 0.0".
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_wprops_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_wprops_"))
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
from app.core.map_layout_apply import seed_boundary  # noqa: E402
from app.models import terrain  # noqa: E402
from app.models import world_props as wp  # noqa: E402
from app.models.world import upsert_location  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


WELL = props.create_prop(name="Demo Well", category="outdoor", width_m=2, depth_m=2,
                         height_m=1.5, tags=["water", "stone"], mount="floor")["id"]
BENCH = props.create_prop(name="Demo Bench", category="furniture", width_m=1.8,
                          depth_m=0.6, height_m=0.9, tags=["seat"], mount="floor")["id"]
LAMP = props.create_prop(name="Demo Lamp", category="light", width_m=0.3,
                         tags=["light"], mount="wall")["id"]
terrain.save_area({"id": "ta_rock", "kind": "rock",
                   "polygon": [[200, 0], [220, 0], [220, 20], [200, 20]]})
upsert_location({"id": "loc_demo_yard", "name": "Demo Yard", "pos_x": 100.0,
                 "pos_z": 100.0, "yaw_deg": 0.0,
                 "map3d": {"boundary": seed_boundary()}}, sync_world=False)

run = wr.create_run("wprops", "m", "p", "u", 60, 300000)


def call(turn, tool, args, rid=None):
    return wt.run_tool(wt.ToolCtx(run_id=rid or run, turn=turn), tool, args)


def rows():
    return wp.list_world_props()


def row(pid):
    return next((r for r in rows() if r["id"] == pid), None)


def new_prop(fn):
    known = {r["id"] for r in rows()}
    res = fn()
    added = [r["id"] for r in rows() if r["id"] not in known]
    return res, (added[0] if added else "")


def last_entry(rid=None):
    """The newest journal row of the run, any kind (wr.steps is oldest-first)."""
    return wr.steps(rid or run)[-1]


print("(a) find_props")
res = call(1, "find_props", {"query": "well"})
lines = res.line.splitlines()
check("(a) ok, one line", res.ok and len(lines) == 1, res.line)
check("(a) starts with the well id", lines[0].startswith(WELL + " "), res.line)
check("(a) the full line",
      lines[0] == (f'{WELL} "Demo Well" outdoor 2×2×1.5 m mount floor tags water, stone '
                   f"model /assets/props/{WELL}/model · no mesh yet"), lines[0])
res = call(1, "find_props", {"category": "furniture"})
check("(a) category furniture -> the bench only",
      res.ok and len(res.line.splitlines()) == 1 and res.line.startswith(BENCH), res.line)
res = call(1, "find_props", {"tag": "light"})
check("(a) tag light -> the lamp only",
      res.ok and len(res.line.splitlines()) == 1 and res.line.startswith(LAMP), res.line)
res = call(1, "find_props", {"mount": "wall"})
check("(a) mount wall -> the lamp only",
      res.ok and len(res.line.splitlines()) == 1 and res.line.startswith(LAMP), res.line)
res = call(1, "find_props", {"mount": "sideways"})
check("(a) unknown mount refused, kinds named",
      not res.ok and all(k in res.line for k in props.MOUNT_KINDS), res.line)
res = call(1, "find_props", {"query": "nothing-like-this"})
check("(a) no match", res.ok and res.line == "no props match", res.line)

print("(b) place_world_prop")
res, P1 = new_prop(lambda: call(1, "place_world_prop",
                                {"prop_id": WELL, "x": 10, "z": 5, "yaw": 90}))
check("(b) ok", res.ok and bool(P1) and res.wrote, res.line)
check("(b) line names id and prop", P1 in res.line and WELL in res.line, res.line)
R1 = row(P1)
check("(b) row exact", R1 == {"id": P1, "prop_id": WELL, "x": 10.0, "z": 5.0,
                              "yaw_deg": 90.0, "offset_y": 0.0, "variant": None}, R1)
ent = last_entry()
check("(b) journal target", (ent.get("target_kind"), ent.get("target_id")) == ("world_prop", P1),
      ent)
check("(b) journal inverse", ent.get("inverse") == {"op": "delete_world_prop", "id": P1},
      ent.get("inverse"))

print("(c) refusals")
for args, want in (({"prop_id": WELL, "x": 10, "z": 5, "yaw": 450}, "would be stored as 90.0"),
                   ({"prop_id": WELL, "x": 10, "z": 5, "offset_y": 80},
                    f"would be stored as {wp.MAX_OFFSET_Y}"),
                   ({"prop_id": "nope", "x": 10, "z": 5}, "unknown prop"),
                   ({"prop_id": WELL, "x": 10.123, "z": 5}, "would be stored as 10.12"),
                   ({"prop_id": WELL, "x": 10, "z": 5, "variant": -1}, "variant"),
                   ({"prop_id": WELL, "x": 10, "z": 5, "colour": "red"}, "colour")):
    n0 = len(rows())
    res = call(1, "place_world_prop", args)
    check(f"(c) {args} refused ({want})",
          not res.ok and want in res.line and not res.wrote and len(rows()) == n0, res.line)
    check(f"(c) {args} journal refused", last_entry().get("kind") == "refused", last_entry())

print("(b2) warnings")
res, P_ROCK = new_prop(lambda: call(1, "place_world_prop", {"prop_id": BENCH, "x": 210, "z": 10}))
check("(b2) on rock: ok with a warning",
      res.ok and bool(P_ROCK) and "rock, which nobody can walk on" in res.line, res.line)
res, P_YARD = new_prop(lambda: call(1, "place_world_prop", {"prop_id": BENCH, "x": 101, "z": 101}))
check("(b2) inside a place: ok with a warning",
      res.ok and bool(P_YARD)
      and 'inside the outline of place loc_demo_yard "Demo Yard"' in res.line, res.line)
res, P_FREE = new_prop(lambda: call(1, "place_world_prop", {"prop_id": BENCH, "x": 50, "z": 50}))
check("(b2) open ground: no warning", res.ok and "warnings" not in res.line, res.line)
check("(b2) four rows", len(rows()) == 4, rows())

print("(g) map_region")
res = call(1, "map_region", {"min_x": 0, "min_z": 0, "max_x": 20, "max_z": 20})
check("(g) lists the well", f"prop {P1} {WELL} (10,5)" in res.line, res.line)
check("(g) not the rock prop", P_ROCK not in res.line, res.line)

print("(d) discard_preview")
prev = wu.discard_preview(run)
check("(d) names the well", f"world prop {P1} ({WELL})" in prev, prev)
check("(d) four world prop lines",
      sum(1 for line in prev if line.startswith("world prop ")) == 4, prev)

print("(e) delete_created in a later turn, undo")
res = call(2, "delete_created", {"kind": "world_prop", "id": P1})
check("(e) ok, earlier turn", res.ok and "earlier turn" in res.line, res.line)
check("(e) gone", row(P1) is None, rows())
prev = wu.discard_preview(run)
check("(e) no discard line for it (net absent)",
      not any(P1 in line for line in prev), prev)
u2 = wu.undo(run, turn=2)
check("(e) undo turn 2 complete", u2["complete"], u2)
check("(e) re-created exactly", row(P1) == R1, (row(P1), R1))
u = wu.undo(run)
check("(e) undo run complete", u["complete"], u)
check("(e) nothing left", rows() == [], rows())

print("(h) same-turn delete_created")
wr.set_status(run, "accepted")  # one open run at a time
run_b = wr.create_run("wprops-b", "m", "p", "u", 60, 300000)
res, PB = new_prop(lambda: call(1, "place_world_prop", {"prop_id": WELL, "x": 1, "z": 1}, run_b))
check("(h) placed", res.ok and bool(PB), res.line)
res = call(1, "delete_created", {"kind": "world_prop", "id": PB}, run_b)
check("(h) deleted", res.ok and row(PB) is None, res.line)
check("(h) discard lists nothing", wu.discard_preview(run_b) == [], wu.discard_preview(run_b))
u = wu.undo(run_b)
check("(h) undo complete, still nothing", u["complete"] and rows() == [], (u, rows()))

print("(f) foreign edit")
wr.set_status(run_b, "accepted")
run2 = wr.create_run("wprops-2", "m", "p", "u", 60, 300000)
res, PF = new_prop(lambda: call(1, "place_world_prop", {"prop_id": WELL, "x": 30, "z": 30}, run2))
check("(f) placed", res.ok and bool(PF), res.line)
moved = dict(row(PF), x=11)
wp.save_world_prop(moved, must_exist=True)
prev = wu.discard_preview(run2)
check("(f) preview: changed since, not going",
      prev == [f"world prop {PF} ({WELL}) was changed since — the discard leaves it alone"],
      prev)
u = wu.undo(run2)
check("(f) undo not complete", not u["complete"], u)
check("(f) skipped changed since",
      any(s.get("reason") == wu.REASON_CHANGED for s in u["skipped"]), u)
check("(f) row stays at x 11", (row(PF) or {}).get("x") == 11.0, row(PF))

print("(k) cap")
wr.set_status(run2, "accepted")
run3 = wr.create_run("wprops-3", "m", "p", "u", 60, 300000)
old_cap = wp.MAX_WORLD_PROPS
wp.MAX_WORLD_PROPS = wp.count_world_props()
try:
    n0 = len(rows())
    res = call(1, "place_world_prop", {"prop_id": WELL, "x": 2, "z": 2}, run3)
    check("(k) refused at the cap",
          not res.ok and "holds its limit of" in res.line and len(rows()) == n0,
          res.line)
    check("(k) journal refused", last_entry(run3).get("kind") == "refused", last_entry(run3))
finally:
    wp.MAX_WORLD_PROPS = old_cap

print("(m) earlier-turn delete of a foreign-edited prop")
wr.set_status(run3, "accepted")
run4 = wr.create_run("wprops-4", "m", "p", "u", 60, 300000)
res, PM = new_prop(lambda: call(1, "place_world_prop", {"prop_id": WELL, "x": 40, "z": 40}, run4))
check("(m) placed", res.ok and bool(PM), res.line)
wp.save_world_prop(dict(row(PM), x=12), must_exist=True)
res = call(2, "delete_created", {"kind": "world_prop", "id": PM}, run4)
check("(m) refused, changed since",
      not res.ok and f"could not delete world prop {PM}: changed since" in res.line, res.line)
check("(m) journal refused", last_entry(run4).get("kind") == "refused", last_entry(run4))
check("(m) row stays at x 12", (row(PM) or {}).get("x") == 12.0, row(PM))
prev = wu.discard_preview(run4)
check("(m) preview: changed since",
      prev == [f"world prop {PM} ({WELL}) was changed since — the discard leaves it alone"],
      prev)
u = wu.undo(run4)
check("(m) undo not complete, changed since",
      not u["complete"] and any(s.get("reason") == wu.REASON_CHANGED for s in u["skipped"]), u)
check("(m) row still at x 12", (row(PM) or {}).get("x") == 12.0, row(PM))

print("(n) re-creation refused by the writer")
wr.set_status(run4, "accepted")
run5 = wr.create_run("wprops-5", "m", "p", "u", 60, 300000)
res, PN = new_prop(lambda: call(1, "place_world_prop",
                                {"prop_id": WELL, "x": -0.0, "z": 60}, run5))
check("(n) placed, -0 shown as 0", res.ok and bool(PN) and "at (0,60)" in res.line, res.line)
check("(n) stored x 0.0", (row(PN) or {}).get("x") == 0.0, row(PN))
res = call(2, "delete_created", {"kind": "world_prop", "id": PN}, run5)
check("(n) deleted in an earlier turn", res.ok and row(PN) is None, res.line)
old_cap = wp.MAX_WORLD_PROPS
wp.MAX_WORLD_PROPS = wp.count_world_props()
try:
    u = wu.undo(run5)
finally:
    wp.MAX_WORLD_PROPS = old_cap
reasons = [s.get("reason") for s in u["skipped"]]
check("(n) re-creation refused, not 'undo failed'",
      wu.REASON_RECREATE_REFUSED in reasons
      and not any(str(r).startswith("undo failed") for r in reasons), u)
check("(n) the error names the cap",
      any("at most" in str(s.get("error") or "") for s in u["skipped"]
          if s.get("reason") == wu.REASON_RECREATE_REFUSED), u)
check("(n) creating entry already gone", wu.REASON_GONE in reasons, u)
check("(n) refused record net_absent",
      all(s.get("net_absent") for s in u["skipped"]
          if s.get("reason") == wu.REASON_RECREATE_REFUSED), u)
check("(n) complete, no row", u["complete"] and row(PN) is None, (u, row(PN)))

print("(n2) re-creation refused, turn-scoped undo")
wr.set_status(run5, "accepted")
run6 = wr.create_run("wprops-6", "m", "p", "u", 60, 300000)
res, PN2 = new_prop(lambda: call(1, "place_world_prop",
                                 {"prop_id": WELL, "x": 61, "z": 61}, run6))
check("(n2) placed", res.ok and bool(PN2), res.line)
res = call(2, "delete_created", {"kind": "world_prop", "id": PN2}, run6)
check("(n2) deleted in an earlier turn", res.ok and row(PN2) is None, res.line)
wp.MAX_WORLD_PROPS = wp.count_world_props()
try:
    u = wu.undo(run6, turn=2)
finally:
    wp.MAX_WORLD_PROPS = old_cap
refused = [s for s in u["skipped"] if s.get("reason") == wu.REASON_RECREATE_REFUSED]
check("(n2) turn 2: refused, no net_absent",
      len(refused) == 1 and not refused[0].get("net_absent"), u)
check("(n2) turn 2: not complete", not u["complete"] and row(PN2) is None, u)
u = wu.undo(run6)
check("(n2) rest of the run: complete (already gone)",
      u["complete"] and [s.get("reason") for s in u["skipped"]] == [wu.REASON_GONE], u)

print("(p) exists again, preview label")
wr.set_status(run6, "accepted")
run7 = wr.create_run("wprops-7", "m", "p", "u", 60, 300000)
res, PP = new_prop(lambda: call(1, "place_world_prop",
                                {"prop_id": WELL, "x": 70, "z": 70}, run7))
check("(p) placed", res.ok and bool(PP), res.line)
kept = dict(row(PP))
res = call(2, "delete_created", {"kind": "world_prop", "id": PP}, run7)
check("(p) deleted", res.ok and row(PP) is None, res.line)
wp.save_world_prop(kept)
prev = wu.discard_preview(run7)
check("(p) preview names the kind label",
      prev == [f"world prop {PP} was deleted by this run and exists again — "
               "the discard leaves it alone"], prev)

print("(q) delete_created refusal label")
res = call(3, "delete_created", {"kind": "world_prop", "id": "wp_nope"}, run7)
check("(q) refused with the kind label",
      not res.ok and "world prop 'wp_nope' was not created by this run" in res.line, res.line)

print("(r) yaw at a full turn")
for sent, want in ((359.96, 0.0), (-0.04, 0.0), (359.94, 359.9)):
    got = wp.sanitize_world_prop({"prop_id": WELL, "x": 0, "z": 0, "yaw_deg": sent})["yaw_deg"]
    check(f"(r) sanitize yaw {sent} -> {want}", got == want, got)
for sent in (359.96, 360):
    res = call(3, "place_world_prop", {"prop_id": WELL, "x": 80, "z": 80, "yaw": sent}, run7)
    check(f"(r) tool yaw {sent} refused, stored as 0.0",
          not res.ok and "would be stored as 0.0" in res.line, res.line)

if failures:
    print(f"\nFAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("\nall ok")
