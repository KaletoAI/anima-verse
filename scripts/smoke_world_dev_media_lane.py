#!/usr/bin/env python3
"""Smoke: World Dev free mode — the ONE global media lane: schedule (review
only), one lane task + one global media lock, the fingerprint re-read before
each producer, cancel / remove / pending, the boot reset (plan
docs/superpowers/plans/2026-11-25-world-dev-free-media.md, Task 8).

A temp world and instance (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM, no render: ``get_image_service`` raises,
and every producer the lane reaches is a fake in ``world_dev_media.PRODUCERS``
(except the hairstyle of (j), whose real adapter calls make_hairstyle — no
render, garment_assembly.schedule / figure_build.request are no-ops). The
REAL TaskQueue of the temp world is used with its workers NOT started
(``_started`` set, so submit never auto-starts them): a lane task stays
pending and the handler ``run_lane`` is called directly.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_media_lane.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

A created location with rooms Hall, Yard has 8 steps (Task 4 (a)):
building-front, day:, night:, day:<hall>, night:<hall>, day:<yard>,
night:<yard>, mesh. The gallery fake writes ONE image per gallery step (7)
into world_gallery/<loc>/ and records it as a gallery_image; the mesh fake
writes model3d/model.glb and model3d/lod/a.glb through the real capture
(``_captured``), so it records 2 files (+ the created dirs, which the
preview line does not count).

  (a) run R1 creates "Demo Keep"; in review ``schedule`` -> [1] (the first row
      of a fresh world), ONE pending task of type world_dev_media; again ->
      [] (every step held by the queued row).
  (b) run_lane with route_check -> None: row done, its 8 steps done, 7
      gallery_image artefacts + 2 file artefacts; media_preview_lines ==
      ['media of location <id> "Demo Keep": 7 images, 2 model files —
      removed'].
  (c) run R2 "Demo Moor" with the REAL gate (empty temp instance): every
      step skipped with the Task 5 note of its occasion (gallery steps:
      route_check("location"), the mesh: route_check("mesh_building") — the
      values smoke_world_dev_media_routes.py pins by hand), row skipped, no
      artefact, no producer call.
  (d) run R3 "Demo Dale": cancel_queued(R3, "turn 2 started") -> 1, the row
      cancelled with that note; run_lane processes nothing, no producer call.
  (e) run R4 "Demo Edge": the gallery fake calls remove_rows(R4, [row]) during
      the "day:" step (the 2nd) -> pending names the row; after that step the
      lane removes both images it wrote, the row is removed, the later 6 steps
      never ran (2 producer calls).
  (f) remove_run_media(R1) after (b): every file gone; the returned removed
      equals the removed set of preview_run_media taken BEFORE; pending [].
  (g) run R5 "Demo Gale": a scheduled row is put "running" with its first two
      steps done (as a crash mid-row leaves it); reset_on_boot -> requeued 1,
      a lane task submitted; the row queued, no step "running"; run_lane runs
      only the 6 other steps (5 gallery + 1 mesh calls).
  (h) set_media_state(R6, "closed") -> schedule [] ; media state open but
      status "running" -> schedule [] (M15).
  (i) stranding (finding 1): run A ("Demo Aone", "Demo Atwo") scheduled -> 2
      rows, 1 pending task. Run A is accepted with its first row "running"
      (the lane mid-row). Run B in review schedules "Demo Bee" -> no second
      task (the pending one runs the lane), B's row queued. run_lane({})
      processes A's 2nd row and then B's row (B done, its producer calls
      recorded). The task ends (cancelled = the worker finished it); with no
      queued row left, a new schedule of B ("Demo Bee2") submits a NEW task.
      (i2) the race the plain dedup has: the lane task is still "running"
      in the queue (its handler past the exit check) -> a new schedule
      ("Demo Bee3") still submits a task (only a PENDING task counts). With
      a lane active in this process, schedule ("Demo Bee4") submits nothing
      — that lane's next pick takes the row.
  (j) fp re-read (finding 3): created humanoid "Demo Hair" on the pipeline
      with hair text -> steps hairstyle, portrait, build; the real hairstyle
      adapter (make_hairstyle) mints and wears a hairstyle, so the Build's
      input (figure.wanted_figure) changes WITHIN the row: the build step's
      stored fp == the fp the build fake saw (_figure_fp of the post-hairstyle
      profile) and != the planned one; a second schedule -> [].
  (k) pending (finding 6): "Demo Block"'s build fake blocks on an event (the
      lane in a thread); remove_run_media with DISCARD_WAIT_S 0.1 -> pending
      == [{row, kind "character", id "Demo Block", step "build"}] and the
      preview line "a render is running (build)"; released -> the lane
      removes the Build's file, the row is removed.
  (l) a row cancelled mid-row (cancel_queued during its "day:" step) keeps
      its 2 done steps held: the row ends cancelled, and the next schedule
      queues only the 6 steps it left open.
  (m) exact inverse over two rows of ONE pre-existing element (acceptance
      finding: rows were removed one by one). Before the run the element dir
      holds meta.json = {"v":0} and nothing else. Row 1 rewrites meta.json to
      {"v":1} and creates m.glb = "one"; row 2 (a later turn) rewrites them to
      {"v":22} and "two!" (both captured by the real snapshot/diff). The
      exact inverse is the pre-run state, by hand: meta.json == {"v":0}
      (row 1's backup, row 2's sha256), m.glb absent (row 1 created it, so it
      is the run's file whatever row 2 did). So preview_run_media removed ==
      remove_run_media removed == ["<el>/m.glb", "<el>/meta.json"], kept ==
      [] both times, both rows removed, and no backup file of either row left
      under .world_dev_media/<run>/.
  (m2) the same two rows, row 2 "running" (the lane mid-row): the removal
      reports row 2 pending and removes nothing (row 1 waits: removed alone
      it would keep meta.json and m.glb as "changed since"); the preview
      lists nothing removed either. When the lane
      ends row 2 (_stop_flagged_locked) both rows go in one fold: meta.json
      {"v":0}, m.glb absent, both rows removed.
  (n) an unexpected error OUTSIDE a producer (merge_artefacts raises once,
      after the gallery fake wrote its image) while a removal flagged the row
      (remove_rows from inside the "building-front" step): the lane's handler
      still removes the image of the step in progress and the row ends
      removed (not failed with the image left behind).
  Every producer the lane reaches is a fake: the kinds planned for a
  location (gallery, location_mesh) and a character (portrait, build) map to
  the fakes in PRODUCERS; only the hairstyle is the real adapter (no render).
  The portrait / build fakes leave no profile image and no base body, so the
  two output checks of plan() (world_dev_media._portrait_present /
  _base_body_present, plan 2026-11-25-world-dev-free-complete-characters-
  budget Task 6) are patched to True: a finished step holds as it does after
  a real render (the missing-output rule is
  scripts/smoke_world_dev_media_lost_portrait.py).
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TMP = Path(tempfile.mkdtemp(prefix="smoke_wd_media_lane_"))
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

from app.core import figure_build, garment_assembly, garment_hair  # noqa: E402
from app.core import world_dev_media as wdm  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core.task_queue import get_task_queue  # noqa: E402
from app.models.character import get_character_profile  # noqa: E402
from app.models.character_template import clear_template_cache  # noqa: E402
from app.models.world import get_gallery_dir, get_location_by_id  # noqa: E402
from app.plugins import registry  # noqa: E402
from app.plugins.registry import BodySlotSpec, Package  # noqa: E402

garment_assembly.schedule = lambda *a, **k: None
figure_build.request = lambda *a, **k: False

TQ = get_task_queue()
TQ._started = True  # never auto-start workers: the lane task stays pending

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


# The skill manager loads (and re-registers) the packages on its first use;
# the completeness line of a character write asks it for the skill groups
# (plan 2026-11-25-world-dev-free-complete-characters-budget, Task 5), so it
# is loaded before the fake package is registered.
from app.core.dependencies import get_skill_manager  # noqa: E402

get_skill_manager()
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

# ── fakes ────────────────────────────────────────────────────────────────
CALLS = []
HOOKS = {}  # (target, step id) -> callable(ctx) run inside the fake


def fake_gallery(ctx, kind, ident, step):
    CALLS.append((ident, step.id))
    hook = HOOKS.get((ident, step.id))
    if hook:
        hook(ctx)
    gdir = get_gallery_dir(ident)
    gdir.mkdir(parents=True, exist_ok=True)
    name = f"{(step.id.replace(':', '_') or 'x')}_{ctx.row_id}.png"
    path = gdir / name
    path.write_bytes(b"png:" + step.id.encode())
    st = path.stat()
    return "", [{"type": "gallery_image", "location_id": ident, "image": name,
                 "path": wdm._rel(path), "size": st.st_size, "mtime_ns": st.st_mtime_ns}]


def fake_location_mesh(ctx, kind, ident, step):
    CALLS.append((ident, step.id))
    root = wdm.media_roots("location", ident)[0]

    def run():
        (root / "lod").mkdir(parents=True, exist_ok=True)
        (root / "model.glb").write_bytes(b"glb01")
        (root / "lod" / "a.glb").write_bytes(b"lod01")
        return ""
    return wdm._captured(ctx, kind, ident, run)


def fake_portrait(ctx, kind, ident, step):
    CALLS.append((ident, step.id))
    return "", []


BUILD_SEEN = {}
BLOCK = {}


def fake_build(ctx, kind, ident, step):
    CALLS.append((ident, step.id))
    BUILD_SEEN[ident] = wdm._figure_fp(ident, get_character_profile(ident) or {})
    ev = BLOCK.get(ident)

    def run():
        if ev is not None:
            ev["started"].set()
            ev["go"].wait(10)
        root = wdm.producer_roots(ident)[0]
        root.mkdir(parents=True, exist_ok=True)
        (root / "k.glb").write_bytes(b"built")
        return ""
    return wdm._captured(ctx, kind, ident, run, roots=wdm.producer_roots(ident))


wdm.PRODUCERS.update({"gallery": fake_gallery, "location_mesh": fake_location_mesh,
                      "portrait": fake_portrait, "build": fake_build})
# The fakes' outputs count as present (docstring).
wdm._portrait_present = lambda name, profile: True
wdm._base_body_present = lambda name, profile: True
_FAKES = {fake_gallery, fake_location_mesh, fake_portrait, fake_build}
check("every render producer the lane reaches is a fake",
      {k for k, v in wdm.PRODUCERS.items() if v not in _FAKES} == {"mesh", "hairstyle"},
      {k: v.__name__ for k, v in wdm.PRODUCERS.items()})
_real_route_check = wdm.route_check
_real_step_gate = wdm.step_gate


def open_gate():
    wdm.route_check = lambda *a, **k: None
    wdm.step_gate = lambda *a, **k: None


def real_gate():
    wdm.route_check = _real_route_check
    wdm.step_gate = _real_step_gate


def lane_tasks(status=None):
    return [t for t in TQ.list_tasks_of_type(wdm.TASK_TYPE) if status is None or t["status"] == status]


def clear_tasks():
    for t in lane_tasks():
        TQ.cancel_task(t["task_id"])


def new_run():
    """One open run at a time: the previous case's run is closed first."""
    prev = wr.open_run()
    if prev:
        wr.set_status(prev["id"], "accepted")
    run = wr.create_run("build", "m", "p", "u", 80, 300000)
    wr.next_turn(run)
    return run, wt.ToolCtx(run_id=run, turn=1)


def review(run):
    wr.set_status(run, "awaiting_review")


def create_location(ctx, name, rooms=("Hall", "Yard")):
    res = wt.run_tool(ctx, "create_location", {"data": {
        "name": name, "rooms": [{"name": r} for r in rooms]}})
    check(f"create {name} ok", res.ok and res.wrote, res)
    for e in wr.entries(ctx.run_id):
        loc = get_location_by_id(e["target_id"]) if e.get("tool") == "create_location" else None
        if loc and loc.get("name") == name:
            return str(loc["id"])
    return ""


def calls_for(ident):
    return [s for i, s in CALLS if i == ident]


def files_exist(rels):
    return [r for r in rels if (wdm._storage() / r).exists()]


# (a)
print("(a) schedule")
open_gate()
r1, c1 = new_run()
keep = create_location(c1, "Demo Keep")
review(r1)
rows = wdm.schedule(r1)
check("(a) [1]", rows == [1], rows)
check("(a) one pending lane task", len(lane_tasks("pending")) == 1, lane_tasks())
check("(a) again -> [] (held)", wdm.schedule(r1) == [])
check("(a) still one task", len(lane_tasks()) == 1, lane_tasks())

# (b)
print("(b) run_lane")
out = wdm.run_lane({})
row = wr.media_row(1)
check("(b) lane processed row 1", out.get("rows") == [1], out)
check("(b) row done", row["status"] == "done", row)
check("(b) 8 steps done", [s["status"] for s in row["steps"]] == ["done"] * 8, row["steps"])
gal = [a for a in row["produced"] if a["type"] == "gallery_image"]
files = [a for a in row["produced"] if a["type"] == "file"]
check("(b) 7 gallery images", len(gal) == 7, gal)
check("(b) 2 model files", sorted(a["path"].rsplit("/", 1)[-1] for a in files) == ["a.glb", "model.glb"], files)
lines = wdm.media_preview_lines(r1)
check("(b) preview line", lines == [f'media of location {keep} "Demo Keep": 7 images, 2 model files — removed'],
      lines)

# (f)
print("(f) remove_run_media")
before = wdm.preview_run_media(r1)
paths_all = [a["path"] for a in row["produced"] if a["type"] in ("gallery_image", "file")]
check("(f) files exist before", len(files_exist(paths_all)) == 9, files_exist(paths_all))
rep = wdm.remove_run_media(r1)
check("(f) removed == preview", set(rep["removed"]) == set(before["removed"]) and rep["removed"],
      (rep, before))
check("(f) nothing pending", rep["pending"] == [], rep)
check("(f) files gone", files_exist(paths_all) == [], files_exist(paths_all))
check("(f) row removed", wr.media_row(1)["status"] == "removed")
check("(f) no preview lines left", wdm.media_preview_lines(r1) == [], wdm.media_preview_lines(r1))
clear_tasks()

# (c)
print("(c) real gate, empty instance")
real_gate()
r2, c2 = new_run()
moor = create_location(c2, "Demo Moor")
review(r2)
(rid,) = wdm.schedule(r2)
n_calls = len(CALLS)
wdm.run_lane({})
row = wr.media_row(rid)
check("(c) row skipped", row["status"] == "skipped", row["status"])
want = [_real_route_check("location")] * 7 + [_real_route_check("mesh_building")]
check("(c) notes = the Task 5 route notes", [s["note"] for s in row["steps"]] == want,
      ([s["note"] for s in row["steps"]], want))
check("(c) all skipped", [s["status"] for s in row["steps"]] == ["skipped"] * 8, row["steps"])
check("(c) no artefact, no call", row["produced"] == [] and len(CALLS) == n_calls)
clear_tasks()
open_gate()

# (d)
print("(d) cancel_queued")
r3, c3 = new_run()
dale = create_location(c3, "Demo Dale")
review(r3)
(rid,) = wdm.schedule(r3)
check("(d) one cancelled", wdm.cancel_queued(r3, "turn 2 started") == 1)
row = wr.media_row(rid)
check("(d) row cancelled with note", (row["status"], row["note"]) == ("cancelled", "turn 2 started"), row)
out = wdm.run_lane({})
check("(d) lane processed nothing", out.get("rows") == [] and calls_for(dale) == [], (out, calls_for(dale)))
clear_tasks()

# (e)
print("(e) removal flag mid-row")
r4, c4 = new_run()
edge = create_location(c4, "Demo Edge")
review(r4)
(rid,) = wdm.schedule(r4)
PENDING = {}
HOOKS[(edge, "day:")] = lambda ctx: PENDING.update(wdm.remove_rows(r4, [ctx.row_id]))
wdm.run_lane({})
row = wr.media_row(rid)
check("(e) pending named the row", [p["row"] for p in PENDING.get("pending", [])] == [rid], PENDING)
check("(e) row removed", row["status"] == "removed", row)
check("(e) only 2 producer calls", calls_for(edge) == ["building-front", "day:"], calls_for(edge))
written = [a["path"] for a in row["produced"] if a["type"] == "gallery_image"]
check("(e) both images recorded and gone", len(written) == 2 and files_exist(written) == [], written)
clear_tasks()

# (l)
print("(l) cancelled mid-row keeps its done steps")
r7, c7 = new_run()
lake = create_location(c7, "Demo Lake")
review(r7)
(rid,) = wdm.schedule(r7)
HOOKS[(lake, "day:")] = lambda ctx: wdm.cancel_queued(r7, "turn 2 started")
wdm.run_lane({})
row = wr.media_row(rid)
check("(l) row cancelled", (row["status"], row["note"]) == ("cancelled", "turn 2 started"), row)
check("(l) 2 done", [s["status"] for s in row["steps"]][:2] == ["done", "done"], row["steps"])
HOOKS.pop((lake, "day:"))
(rid2,) = wdm.schedule(r7)
ids = [s["id"] for s in wr.media_row(rid2)["steps"]]
check("(l) only the 6 open steps re-queued", len(ids) == 6 and "building-front" not in ids and "day:" not in ids,
      ids)
wdm.cancel_queued(r7, "smoke")
clear_tasks()

# (g)
print("(g) reset_on_boot")
r5, c5 = new_run()
gale = create_location(c5, "Demo Gale")
review(r5)
(rid,) = wdm.schedule(r5)
clear_tasks()
row = wr.media_row(rid)
steps = row["steps"]
steps[0]["status"] = "done"
steps[1]["status"] = "done"
steps[2]["status"] = "running"
wr.update_media_row(rid, status="running", steps=steps)
counts = wdm.reset_on_boot()
row = wr.media_row(rid)
check("(g) requeued 1, submitted", counts.get("requeued") == 1 and counts.get("submitted") == 1, counts)
check("(g) row queued, no running step",
      row["status"] == "queued" and not any(s["status"] == "running" for s in row["steps"]), row)
check("(g) one pending task", len(lane_tasks("pending")) == 1, lane_tasks())
wdm.run_lane({})
got = calls_for(gale)
check("(g) only the 6 other steps ran", len(got) == 6 and "building-front" not in got and "day:" not in got
      and got[-1] == "mesh", got)
check("(g) row done", wr.media_row(rid)["status"] == "done")
clear_tasks()

# (h)
print("(h) not schedulable")
r6, c6 = new_run()
create_location(c6, "Demo Hill")
review(r6)
wdm.set_media_state(r6, "closed")
check("(h) closed -> []", wdm.schedule(r6) == [])
wdm.set_media_state(r6, "open")
wr.set_status(r6, "running")
check("(h) running -> []", wdm.schedule(r6) == [])
check("(h) no task", lane_tasks() == [], lane_tasks())

# (i)
print("(i) stranding")
ra, ca = new_run()
aone = create_location(ca, "Demo Aone", rooms=())
atwo = create_location(ca, "Demo Atwo", rooms=())
review(ra)
a_rows = wdm.schedule(ra)
check("(i) two A rows", len(a_rows) == 2, a_rows)
check("(i) one pending task", len(lane_tasks("pending")) == 1, lane_tasks())
task_a = lane_tasks("pending")[0]["task_id"]
wr.update_media_row(a_rows[0], status="running")  # the lane is mid-row
wdm.set_media_state(ra, "accepted")
wr.set_status(ra, "accepted")
rb, cb = new_run()
bee = create_location(cb, "Demo Bee", rooms=())
review(rb)
(b_row,) = wdm.schedule(rb)
check("(i) no second task", [t["task_id"] for t in lane_tasks()] == [task_a], lane_tasks())
check("(i) B queued", wr.media_row(b_row)["status"] == "queued")
out = wdm.run_lane({})
check("(i) lane took A's 2nd row, then B's", out.get("rows") == [a_rows[1], b_row], out)
check("(i) B done + calls recorded", wr.media_row(b_row)["status"] == "done"
      and calls_for(bee) == ["building-front", "day:", "night:", "mesh"], (wr.media_row(b_row), calls_for(bee)))
wr.update_media_row(a_rows[0], status="done")
TQ.cancel_task(task_a)  # the worker finished the task
wr.set_status(rb, "running")
create_location(cb, "Demo Bee2", rooms=())
review(rb)
check("(i) B schedules again", len(wdm.schedule(rb)) == 1)
pend = lane_tasks("pending")
check("(i) a NEW pending task", len(pend) == 1 and pend[0]["task_id"] != task_a, pend)
wdm.run_lane({})
# (i2) the task of an exited lane still shows "running" in the queue
task_b = pend[0]["task_id"]
with TQ._connect() as conn:
    conn.execute("UPDATE tasks SET status='running' WHERE task_id=?", (task_b,))
    conn.commit()
wr.set_status(rb, "running")
create_location(cb, "Demo Bee3", rooms=())
review(rb)
check("(i2) schedule", len(wdm.schedule(rb)) == 1)
pend = lane_tasks("pending")
check("(i2) a running task does not count: new pending task", len(pend) == 1 and pend[0]["task_id"] != task_b,
      lane_tasks())
wdm.run_lane({})
clear_tasks()
wdm._lane["active"] = True
try:
    wr.set_status(rb, "running")
    create_location(cb, "Demo Bee4", rooms=())
    review(rb)
    check("(i2) active lane: schedule", len(wdm.schedule(rb)) == 1)
    check("(i2) active lane: no task", lane_tasks() == [], lane_tasks())
finally:
    wdm._lane["active"] = False
check("(i2) the lane takes it", len(wdm.run_lane({}).get("rows") or []) == 1)

# (j)
print("(j) fp re-read")
open_gate()
rj, cj = new_run()
res = wt.run_tool(cj, "create_character", {"data": {
    "name": "Demo Hair", "gender": "female", "body_slots": {"hair": {"color": "red", "length": "long"}}}})
check("(j) create ok", res.ok and res.wrote, res)
review(rj)
(rid,) = wdm.schedule(rj)
planned = {s["id"]: s["fp"] for s in wr.media_row(rid)["steps"]}
check("(j) planned steps", list(planned) == ["hairstyle", "portrait", "build"], list(planned))
wdm.run_lane({})
row = wr.media_row(rid)
stored = {s["id"]: s["fp"] for s in row["steps"]}
check("(j) row done", row["status"] == "done" and all(s["status"] == "done" for s in row["steps"]), row)
check("(j) a hairstyle is worn", bool(garment_hair.hairstyles("Demo Hair")))
check("(j) build fp == what the Build saw", stored["build"] == BUILD_SEEN.get("Demo Hair"),
      (stored["build"], BUILD_SEEN))
check("(j) build fp != the planned one", stored["build"] != planned["build"])
check("(j) second schedule -> []", wdm.schedule(rj) == [])
clear_tasks()

# (k)
print("(k) pending")
rk, ck = new_run()
res = wt.run_tool(ck, "create_character", {"data": {"name": "Demo Block", "gender": "male"}})
check("(k) create ok", res.ok and res.wrote, res)
review(rk)
(rid,) = wdm.schedule(rk)
BLOCK["Demo Block"] = {"started": threading.Event(), "go": threading.Event()}
lane = threading.Thread(target=wdm.run_lane, args=({},), daemon=True)
lane.start()
check("(k) build started", BLOCK["Demo Block"]["started"].wait(10))
wdm.DISCARD_WAIT_S = 0.1
rep = wdm.remove_run_media(rk)
check("(k) pending", rep["pending"] == [{"row": rid, "kind": "character", "id": "Demo Block", "step": "build"}],
      rep)
lines = wdm.media_preview_lines(rk)
check("(k) preview: a render is running (build)", any("a render is running (build)" in l for l in lines), lines)
BLOCK["Demo Block"]["go"].set()
lane.join(10)
row = wr.media_row(rid)
check("(k) row removed", row["status"] == "removed", row)
built = [a["path"] for a in row["produced"] if a["type"] == "file"]
check("(k) the Build's file recorded and gone", len(built) == 1 and files_exist(built) == [], built)
check("(k) lane idle", not wdm._lane["active"])
clear_tasks()


# (m) / (m2)
def two_row_element(label):
    run, _ctx = new_run()
    review(run)
    el = wdm._storage() / "wdm_probe" / label
    el.mkdir(parents=True)
    side, glb = el / "meta.json", el / "m.glb"
    side.write_text('{"v":0}')
    rels = (wdm._rel(glb), wdm._rel(side))
    ids, arts = [], []
    for n, (meta, data) in enumerate((('{"v":1}', b"one"), ('{"v":22}', b"two!")), 1):
        rid = wr.add_media_row(run, "character", label, [{"id": "build", "status": "done", "fp": str(n)}],
                               scheduled_turn=n)
        before = wdm.snapshot([el])
        side.write_text(meta)
        glb.write_bytes(data)
        arts.append(wdm.diff(before, wdm.snapshot([el]), wdm.ProduceCtx(run, rid).backup_dir()))
        wr.update_media_row(rid, status="done", produced=arts[-1])
        ids.append(rid)
    return run, side, glb, rels, ids


def backups_left(run):
    root = wdm._storage() / ".world_dev_media" / run
    return sorted(str(p) for p in root.rglob("*") if p.is_file()) if root.exists() else []


print("(m) two rows, one element: exact inverse")
rm, side, glb, rels, ids = two_row_element("Demo Old")
want = sorted(rels)
pre = wdm.preview_run_media(rm)
rep = wdm.remove_run_media(rm)
check("(m) preview removed == both paths", sorted(pre["removed"]) == want and pre["kept"] == [], pre)
check("(m) report == preview", sorted(rep["removed"]) == want and rep["kept"] == [] and rep["pending"] == [],
      rep)
check("(m) meta.json back to the pre-run bytes", side.read_text() == '{"v":0}', side.read_text())
check("(m) m.glb (created by the run) gone", not glb.exists())
check("(m) both rows removed", [wr.media_row(i)["status"] for i in ids] == ["removed", "removed"])
check("(m) no backup left", backups_left(rm) == [], backups_left(rm))

print("(m2) the later row running")
rm2, side, glb, rels, ids = two_row_element("Demo Older")
wr.update_media_row(ids[1], status="running")
wdm.DISCARD_WAIT_S = 0.05
pre = wdm.preview_run_media(rm2)
rep = wdm.remove_run_media(rm2)
check("(m2) preview: nothing removed now", pre["removed"] == [] and len(pre["pending"]) == 1, pre)
check("(m2) report: row 2 pending, nothing removed", rep["removed"] == []
      and [p["row"] for p in rep["pending"]] == [ids[1]], rep)
check("(m2) bytes untouched meanwhile", side.read_text() == '{"v":22}' and glb.read_bytes() == b"two!")
row2 = wr.media_row(ids[1])
with wdm._media_lock():
    st = wdm._stop_flagged_locked(row2, row2["steps"], row2["produced"])
check("(m2) the lane's end removes", st == "removed", st)
check("(m2) meta.json back to the pre-run bytes", side.read_text() == '{"v":0}', side.read_text())
check("(m2) m.glb gone", not glb.exists())
check("(m2) both rows removed", [wr.media_row(i)["status"] for i in ids] == ["removed", "removed"],
      [wr.media_row(i) for i in ids])
check("(m2) no backup left", backups_left(rm2) == [], backups_left(rm2))

print("(n) error outside a producer while flagged remove")
rn, cn = new_run()
nook = create_location(cn, "Demo Nook", rooms=())
review(rn)
(rid,) = wdm.schedule(rn)
HOOKS[(nook, "building-front")] = lambda ctx: wdm.remove_rows(rn, [ctx.row_id])
_real_merge = wdm.merge_artefacts
_merge_calls = {"n": 0}


def _merge_once_raises(*a, **k):
    _merge_calls["n"] += 1
    if _merge_calls["n"] == 1:
        raise RuntimeError("merge broke")
    return _real_merge(*a, **k)


wdm.merge_artefacts = _merge_once_raises
try:
    wdm.run_lane({})
finally:
    wdm.merge_artefacts = _real_merge
row = wr.media_row(rid)
img = get_gallery_dir(nook) / f"building-front_{rid}.png"
check("(n) row removed (not failed)", row["status"] == "removed", row)
check("(n) the in-flight image gone", not img.exists(), str(img))
check("(n) only the one producer call", calls_for(nook) == ["building-front"], calls_for(nook))
clear_tasks()

print()
if failures:
    print(f"FAILED ({len(failures)}):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ALL OK")
