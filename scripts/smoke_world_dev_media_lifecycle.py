#!/usr/bin/env python3
"""Smoke: World Dev free mode — the run lifecycle of the media lane (plan
docs/superpowers/plans/2026-11-25-world-dev-free-media.md, Task 9): turn
start cancels queued rows, turn end schedules, a rolled-back later turn
re-plans (no row removal), Discard removes the run's media (bounded wait,
pending, orphan sweep) before the journal undo and replays the triggers the
undo suppressed, Accept keeps the lane going, a cross-turn delete_created
removes the element's media before its snapshot.

A temp world and instance (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no real LLM, no render: ``get_image_service``
raises, every render producer in ``world_dev_media.PRODUCERS`` is a fake
(only the hairstyle adapter is real: make_hairstyle renders nothing), the
gate is open (``route_check`` / ``step_gate`` -> None) and the lane task is
run synchronously: the task queue's ``submit`` calls ``run_lane`` inline
(LANE["inline"]) or records the submit and runs nothing.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_media_lifecycle.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

The plugin registry holds one species with a hair body slot (as
smoke_world_dev_media_lane (j)), so a humanoid with hair text gets the steps
hairstyle, portrait, build; one without hair text portrait, build. A place
with one room "Hall" has 6 steps: building-front, day:, night:, day:<hall>,
night:<hall>, mesh — the gallery fake writes 1 image per gallery step (5),
the mesh fake 1 model file (model.glb).

  (a) turn 1 [create_location "Demo Keep" (room Hall), "Built."], lane inline
      -> awaiting_review; exactly one media row, status done, 6 steps done;
      the 5 images and model.glb exist.
  (c2) inside turn 2 of that run (a callable reply = while the run is
      "running") schedule(run) -> [] and the row count stays 1.
  (c) turn 2 [update_location rooms Hall image_prompt_day "a new prompt",
      3 bad bodies] -> turn 2 fails and is rolled back -> awaiting_review,
      the room's day prompt is back (absent); hand-derived: no row was
      scheduled during turn 2 and turn 1's row was done at turn-2 start
      (nothing cancelled), so plan(run) == [], schedule(run) == [], still
      exactly 1 media row (done) and all 6 files exist.
  (d) discard of that run: discard_preview BEFORE holds the line
      'media of location <id> "Demo Keep": 5 images, 1 model file — removed';
      the report's media.removed equals preview_run_media's removed set
      taken before (non-empty), media.pending == []; afterwards the files and
      the created location's gallery dir are gone (sweep_orphan_dirs),
      status rolled_back, media_state closed.
  (b) lane NOT inline: turn 1 [create_location "Demo Dale", "Built."] -> one
      row queued; follow-up turn 2 starts -> that row cancelled with note
      "turn 2 started"; turn 2 ends final -> one NEW queued row for the same
      location with all 6 steps (re-planned: the cancelled row held no done
      step) -> 2 rows.
  (e) accept of that run with the queued row -> the row is still queued,
      status accepted, media_state "accepted".
  (c3) like (b) but turn 2 fails (3 bad bodies): the rollback re-plans too
      -> the turn-1 row cancelled "turn 2 started", one new queued row.
  (f)/(g) turn 1 [create_character "Demo Gone" (no hair text), "Made."], lane
      inline -> is_deferred("Demo Gone") is False after the turn (g); its row
      done; the build fake wrote 600 KiB (more than MAX_SNAPSHOT_FILE_BYTES,
      512 KiB) into the character's model3d dir, so without the media
      removal the cross-turn delete would be refused. Turn 2 [delete_created
      character "Demo Gone", "Removed."] -> the step's line contains "its
      media removed"; the journal's recreate_character snapshot has
      file_bytes < MAX_SNAPSHOT_FILE_BYTES; the 600 KiB file is gone; the
      character is gone.
  (f2) the location branch of (f): turn 1 [create_location "Demo Fell"
      (room Hall), "Built."], lane inline -> one row done, 6 files (as (a)).
      Turn 2 [delete_created location, then 3 bad bodies] -> the step's line
      contains "its media removed (6 files)" (5 images + model.glb), the turn
      fails and is rolled back: the location row equals the one before turn 2
      (JSON), turn 1's row stays "removed" (its files were removed, the
      rollback re-creates world data only; turn 1's 5 images stay gone, the
      mesh fake writes model.glb at the same path again) and exactly one new
      row is planned and runs to done (re-plan of a re-created element: its
      6 steps).
      Turn 3 [delete_created location, "Removed."] -> line contains "its media
      removed (6 files)" (the new row's 6 files), the gallery and model dirs
      are gone, the location is gone, the recreate_location inverse holds
      only {op, row} (no media bytes). Discard -> no "media of" preview line,
      complete True, the gallery / model dirs stay gone, the run's backup dir
      <storage>/.world_dev_media/<run>/ does not exist.
  (h) Task 6 deviation 1. "Demo Pre" exists before the run (hair slot red /
      long, no hairstyle). Turn 1 [update_character "Demo Pre" hair black / long
      (a change of the hair text: its hairstyle / portrait fingerprints move),
      create_character "Demo Made" (hair black / short), "Done."], lane
      inline -> both rows done, Demo Pre wears a server hairstyle
      (make_hairstyle). The counters are reset; discard -> during the undo
      Demo Pre IS deferred: the hairstyle undo's garment_assembly.schedule
      and figure_build.request are swallowed by the guard (SUPP); after the
      close they run exactly once each for Demo Pre (counted past the guard:
      the garment_assembly.schedule recorder and the figure_build.start
      recorder); for Demo Made (deleted by the same discard) nothing runs.
      Demo Pre has no hairstyle any more, status rolled_back.
"""
from __future__ import annotations

import asyncio
import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TMP = Path(tempfile.mkdtemp(prefix="smoke_wd_media_life_"))
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
from app.core import world_dev_agent as wa  # noqa: E402
from app.core import world_dev_media as wdm  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core.llm_client import LLMChunk  # noqa: E402
from app.core.task_queue import get_task_queue  # noqa: E402
from app.models.character import character_row_exists, save_character_profile  # noqa: E402
from app.models.character_template import clear_template_cache  # noqa: E402
from app.models.world import get_gallery_dir, get_location_by_id, list_locations  # noqa: E402
from app.plugins import registry  # noqa: E402
from app.plugins.registry import BodySlotSpec, Package  # noqa: E402

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

# ── the lane: synchronous, or not at all ────────────────────────────────
TQ = get_task_queue()
TQ._started = True
LANE = {"inline": True, "submits": 0}


def fake_submit(task_type, payload=None, *a, **k):
    LANE["submits"] += 1
    if task_type == wdm.TASK_TYPE and LANE["inline"]:
        wdm.run_lane(payload or {})
    return f"fake-{LANE['submits']}"


TQ.submit = fake_submit
wdm.route_check = lambda *a, **k: None
wdm.step_gate = lambda *a, **k: None

# ── the automatic triggers, counted past their guard ────────────────────
EXEC = []   # (trigger, name) that really ran past the World Dev guard
SUPP = []   # (trigger, name) swallowed by the guard


def rec_assembly(character_name, signature=None, *, retry=False):
    if wdm.suppress_if_deferred(character_name, "garment_assembly.schedule", (None,),
                                {"retry": retry}):
        SUPP.append(("garment_assembly.schedule", character_name))
        return False
    EXEC.append(("garment_assembly.schedule", character_name))
    return True


_real_request = figure_build.request


def rec_request(character_name, trigger):
    if wdm.is_deferred(character_name):
        SUPP.append(("figure_build.request", character_name))
    return _real_request(character_name, trigger)


def rec_start(name, *, reason, automatic=False):
    EXEC.append(("figure_build.start", name))
    return {"status": "started"}


garment_assembly.schedule = rec_assembly
figure_build.request = rec_request
figure_build.start = rec_start

# ── producer fakes ───────────────────────────────────────────────────────
BIG = {}  # character name -> the bytes the build fake writes


def fake_gallery(ctx, kind, ident, step):
    gdir = get_gallery_dir(ident)
    gdir.mkdir(parents=True, exist_ok=True)
    name = f"{(step.id.replace(':', '_') or 'x')}_{ctx.row_id}.png"
    path = gdir / name
    path.write_bytes(b"png:" + step.id.encode())
    st = path.stat()
    return "", [{"type": "gallery_image", "location_id": ident, "image": name,
                 "path": wdm._rel(path), "size": st.st_size, "mtime_ns": st.st_mtime_ns}]


def fake_location_mesh(ctx, kind, ident, step):
    root = wdm.media_roots("location", ident)[0]

    def run():
        root.mkdir(parents=True, exist_ok=True)
        (root / "model.glb").write_bytes(b"glb01")
        return ""
    return wdm._captured(ctx, kind, ident, run)


def fake_portrait(ctx, kind, ident, step):
    return "", []


def fake_build(ctx, kind, ident, step):
    def run():
        root = wdm.producer_roots(ident)[0]
        root.mkdir(parents=True, exist_ok=True)
        (root / "k.glb").write_bytes(BIG.get(ident, b"built"))
        return ""
    return wdm._captured(ctx, kind, ident, run, roots=wdm.producer_roots(ident))


wdm.PRODUCERS.update({"gallery": fake_gallery, "location_mesh": fake_location_mesh,
                      "portrait": fake_portrait, "build": fake_build, "mesh": fake_build})


# ── LLM fakes ────────────────────────────────────────────────────────────
async def _no_active(_llm_instance):
    return None


wa._chat_active = _no_active
wa._chat_done = lambda _task_id: None


class FakeLLM:
    def __init__(self):
        self.replies = []

    async def astream(self, messages):
        reply = self.replies.pop(0) if self.replies else "Done."
        if callable(reply):
            reply = reply()
        if isinstance(reply, BaseException):
            raise reply
        yield LLMChunk(content=reply)


def call(tool, body):
    return f'<tool name="{tool}">{json.dumps(body)}</tool>'


BAD = '<tool name="world_overview">{oops</tool>'


def create_loc(name, rooms=("Hall",)):
    return call("create_location", {"data": {"name": name, "rooms": [{"name": r} for r in rooms]}})


def manager():
    rm = wa.RunManager()
    fake = FakeLLM()
    rm.llm_factory = lambda model, provider, max_tokens: (fake, None)
    return rm, fake


async def settle(rm, run_id):
    for _ in range(1500):
        run = wr.get_run(run_id)
        if run["status"] != "running" and not rm.is_busy(run_id):
            return run
        await asyncio.sleep(0.02)
    raise AssertionError(f"run {run_id} still running")


def loc_id(name):
    for loc in list_locations() or []:
        if loc.get("name") == name:
            return str(loc["id"])
    return ""


def row_files(row):
    return [a["path"] for a in row.get("produced") or [] if a.get("type") in ("gallery_image", "file")]


def exist(rels):
    return [r for r in rels if (wdm._storage() / r).exists()]


def statuses(run_id):
    return [(r["status"], r["note"]) for r in wr.media_rows(run_id)]


async def main():
    print("(a) turn 1 creates a place -> one row done")
    LANE["inline"] = True
    rm, fake = manager()
    fake.replies = [create_loc("Demo Keep"), "Built."]
    run = await rm.start("build", "fake-model", "fake", "u1")
    st = await settle(rm, run)
    keep = loc_id("Demo Keep")
    rows = wr.media_rows(run)
    check("(a) awaiting_review", st["status"] == "awaiting_review", st)
    check("(a) one row, done", [r["status"] for r in rows] == ["done"], statuses(run))
    files_a = row_files(rows[0]) if rows else []
    check("(a) 6 steps done", bool(rows) and [s["status"] for s in rows[0]["steps"]] == ["done"] * 6,
          rows and rows[0]["steps"])
    check("(a) 5 images + model.glb exist", len(files_a) == 6 and exist(files_a) == files_a, files_a)

    print("(c2)/(c) turn 2 fails -> rolled back, nothing re-planned")
    hall = next((str(r["id"]) for r in (get_location_by_id(keep) or {}).get("rooms") or []
                 if r.get("name") == "Hall"), "")
    seen = {}

    def probe():
        seen["schedule"] = wdm.schedule(run)
        seen["rows"] = len(wr.media_rows(run))
        seen["status"] = wr.get_run(run)["status"]
        return BAD

    fake.replies = [call("update_location", {"id": keep, "patch": {"rooms": [
        {"id": hall, "name": "Hall", "image_prompt_day": "a new prompt"}]}}), probe, BAD, BAD]
    await rm.message(run, "change the hall")
    st = await settle(rm, run)
    check("(c2) during the turn: status running", seen.get("status") == "running", seen)
    check("(c2) schedule during a turn -> []", seen.get("schedule") == [], seen)
    check("(c2) no row added during the turn", seen.get("rows") == 1, seen)
    check("(c) awaiting_review after the rollback", st["status"] == "awaiting_review", st)
    room = next((r for r in (get_location_by_id(keep) or {}).get("rooms") or []
                 if str(r.get("id")) == hall), {})
    check("(c) the day prompt is undone", not room.get("image_prompt_day"), room)
    check("(c) plan == []", wdm.plan(run) == [], wdm.plan(run))
    check("(c) schedule == []", wdm.schedule(run) == [])
    check("(c) still exactly 1 row, done", [s for s, _ in statuses(run)] == ["done"], statuses(run))
    check("(c) every file still exists", exist(files_a) == files_a, exist(files_a))

    print("(d) discard removes the media")
    preview = wu.discard_preview(run)
    want_line = f'media of location {keep} "Demo Keep": 5 images, 1 model file — removed'
    check("(d) preview holds the media line", want_line in preview, preview)
    before = wdm.preview_run_media(run)
    rep = await rm.discard(run)
    media = rep.get("media") or {}
    check("(d) report media.removed == preview", bool(before["removed"])
          and set(media.get("removed") or []) == set(before["removed"]), (media, before))
    check("(d) nothing pending", media.get("pending") == [], media)
    check("(d) files gone", exist(files_a) == [], exist(files_a))
    check("(d) the gallery dir is gone", not get_gallery_dir(keep).exists(), str(get_gallery_dir(keep)))
    st = wr.get_run(run)
    check("(d) rolled_back, media closed",
          (st["status"], st.get("media_state")) == ("rolled_back", "closed"),
          (st["status"], st.get("media_state")))

    print("(b) turn start cancels, turn end re-plans")
    LANE["inline"] = False
    rm, fake = manager()
    fake.replies = [create_loc("Demo Dale"), "Built."]
    run = await rm.start("build", "fake-model", "fake", "u1")
    await settle(rm, run)
    check("(b) one queued row after turn 1", [s for s, _ in statuses(run)] == ["queued"], statuses(run))
    fake.replies = ["Nothing to change."]
    await rm.message(run, "look again")
    st = await settle(rm, run)
    rows = wr.media_rows(run)
    check("(b) awaiting_review", st["status"] == "awaiting_review", st)
    check("(b) row 1 cancelled 'turn 2 started', a new queued row",
          statuses(run)[:1] == [("cancelled", "turn 2 started")]
          and [s for s, _ in statuses(run)][1:] == ["queued"], statuses(run))
    check("(b) the new row: same element, all 6 steps",
          len(rows) == 2 and rows[1]["target_id"] == loc_id("Demo Dale") and len(rows[1]["steps"]) == 6,
          rows[-1:])

    print("(e) accept keeps the queued row")
    await rm.accept(run)
    st = wr.get_run(run)
    check("(e) accepted, media accepted",
          (st["status"], st.get("media_state")) == ("accepted", "accepted"),
          (st["status"], st.get("media_state")))
    check("(e) the queued row is still queued", [s for s, _ in statuses(run)][-1:] == ["queued"],
          statuses(run))
    wdm.cancel_queued(run, "smoke")

    print("(c3) a rolled-back later turn re-plans")
    rm, fake = manager()
    fake.replies = [create_loc("Demo Moor"), "Built."]
    run = await rm.start("build", "fake-model", "fake", "u1")
    await settle(rm, run)
    fake.replies = [BAD, BAD, BAD]
    await rm.message(run, "go on")
    st = await settle(rm, run)
    check("(c3) awaiting_review", st["status"] == "awaiting_review", st)
    check("(c3) cancelled + one new queued row",
          statuses(run)[:1] == [("cancelled", "turn 2 started")]
          and [s for s, _ in statuses(run)][1:] == ["queued"], statuses(run))
    await rm.discard(run)
    check("(c3) discarded", wr.get_run(run)["status"] == "rolled_back", wr.get_run(run)["status"])

    print("(f)/(g) cross-turn delete_created of a rendered character")
    LANE["inline"] = True
    BIG["Demo Gone"] = b"x" * (600 * 1024)
    rm, fake = manager()
    fake.replies = [call("create_character", {"data": {"name": "Demo Gone", "gender": "female"}}),
                    "Made."]
    run = await rm.start("build", "fake-model", "fake", "u1")
    await settle(rm, run)
    check("(g) released at the turn end", not wdm.is_deferred("Demo Gone"))
    rows = wr.media_rows(run)
    check("(f) row done", [r["status"] for r in rows] == ["done"], statuses(run))
    big = row_files(rows[0]) if rows else []
    check("(f) the 600 KiB file exists", len(big) == 1 and exist(big) == big, big)
    fake.replies = [call("delete_created", {"kind": "character", "id": "Demo Gone"}), "Removed."]
    await rm.message(run, "remove her")
    await settle(rm, run)
    steps = [s for s in wr.steps(run) if s.get("tool") == "delete_created"]
    line = steps[-1]["line"] if steps else ""
    check("(f) the delete line names the media removal", "its media removed" in (line or ""), line)
    snap = next((e["inverse"].get("snapshot") for e in wr.entries(run)
                 if (e.get("inverse") or {}).get("op") == "recreate_character"), None)
    check("(f) snapshot file_bytes < MAX", snap is not None
          and snap["file_bytes"] < wu.MAX_SNAPSHOT_FILE_BYTES, snap and snap["file_bytes"])
    check("(f) the big file is gone", exist(big) == [], exist(big))
    check("(f) the character is gone", not character_row_exists("Demo Gone"))
    await rm.discard(run)
    check("(f) discarded", wr.get_run(run)["status"] == "rolled_back", wr.get_run(run))

    print("(f2) cross-turn delete_created of a rendered location")
    LANE["inline"] = True
    rm, fake = manager()
    fake.replies = [create_loc("Demo Fell"), "Built."]
    run = await rm.start("build", "fake-model", "fake", "u1")
    await settle(rm, run)
    fell = loc_id("Demo Fell")
    rows = wr.media_rows(run)
    files_f = row_files(rows[0]) if rows else []
    check("(f2) turn 1: one row done, 6 files", [r["status"] for r in rows] == ["done"]
          and len(files_f) == 6 and exist(files_f) == files_f, (statuses(run), files_f))
    row_before = json.dumps(get_location_by_id(fell), sort_keys=True, default=str)
    fake.replies = [call("delete_created", {"kind": "location", "id": fell}), BAD, BAD, BAD]
    await rm.message(run, "remove it, then fail")
    st = await settle(rm, run)
    steps = [s for s in wr.steps(run) if s.get("tool") == "delete_created"]
    line = steps[-1]["line"] if steps else ""
    check("(f2) turn 2 line: its media removed (6 files)",
          "its media removed (6 files)" in (line or ""), line)
    check("(f2) turn 2 rolled back -> awaiting_review", st["status"] == "awaiting_review", st)
    check("(f2) the location is rebuilt exactly",
          json.dumps(get_location_by_id(fell), sort_keys=True, default=str) == row_before,
          get_location_by_id(fell))
    rows = wr.media_rows(run)
    check("(f2) turn 1's row stays removed, one new row done",
          [r["status"] for r in rows] == ["removed", "done"], statuses(run))
    check("(f2) the new row: same place, 6 steps",
          len(rows) == 2 and rows[1]["target_id"] == fell and len(rows[1]["steps"]) == 6,
          rows[-1:])
    files_f2 = row_files(rows[1]) if len(rows) == 2 else []
    # The mesh fake writes the same model.glb path again; the images carry
    # the row id, so turn 1's 5 images must stay gone.
    old_only = [f for f in files_f if f not in files_f2]
    check("(f2) turn 1's images stay removed", len(old_only) == 5 and exist(old_only) == [],
          (old_only, exist(old_only)))
    check("(f2) the new row's 6 files exist", len(files_f2) == 6 and exist(files_f2) == files_f2,
          files_f2)
    fake.replies = [call("delete_created", {"kind": "location", "id": fell}), "Removed."]
    await rm.message(run, "remove it")
    st = await settle(rm, run)
    steps = [s for s in wr.steps(run) if s.get("tool") == "delete_created"]
    line = steps[-1]["line"] if steps else ""
    check("(f2) turn 3 line: its media removed (6 files)",
          "its media removed (6 files)" in (line or ""), line)
    check("(f2) the location is gone", get_location_by_id(fell) is None)
    gdir = get_gallery_dir(fell)
    mdir = wdm.media_roots("location", fell)[0]
    check("(f2) the gallery dir is gone", not gdir.exists(), str(gdir))
    check("(f2) the model dir holds no file",
          not mdir.exists() or not any(p.is_file() for p in mdir.rglob("*")), str(mdir))
    check("(f2) the new row's files are gone", exist(files_f2) == [], exist(files_f2))
    invs = [e["inverse"] for e in wr.entries(run)
            if (e.get("inverse") or {}).get("op") == "recreate_location"]
    check("(f2) recreate_location inverses hold only {op, row}",
          bool(invs) and all(set(i) == {"op", "row"} for i in invs),
          [sorted(i) for i in invs])
    preview = wu.discard_preview(run)
    check("(f2) the preview names no media", "media of" not in preview, preview)
    rep = await rm.discard(run)
    check("(f2) discard complete", rep.get("complete") is True, rep)
    check("(f2) rolled_back", wr.get_run(run)["status"] == "rolled_back", wr.get_run(run)["status"])
    check("(f2) the gallery dir stays gone", not gdir.exists(), str(gdir))
    check("(f2) the model dir holds no file",
          not mdir.exists() or not any(p.is_file() for p in mdir.rglob("*")), str(mdir))
    bdir = wdm._storage() / ".world_dev_media" / run
    check("(f2) the run's backup dir is swept", not bdir.exists(), str(bdir))

    print("(h) the discard replays what its undo suppressed")
    save_character_profile("Demo Pre", {"name": "Demo Pre", "template": "human-roleplay",
                                        "gender": "female",
                                        "body_slots": {"hair": {"color": "red", "length": "long"}}},
                           create_new=True)
    rm, fake = manager()
    fake.replies = [call("update_character", {"name": "Demo Pre", "patch": {
                        "body_slots": {"hair": {"color": "black", "length": "long"}}}}),
                    call("create_character", {"data": {"name": "Demo Made", "gender": "female",
                                                       "body_slots": {"hair": {"color": "black",
                                                                               "length": "short"}}}}),
                    "Done."]
    run = await rm.start("build", "fake-model", "fake", "u1")
    st = await settle(rm, run)
    rows = wr.media_rows(run)
    check("(h) awaiting_review", st["status"] == "awaiting_review", st)
    check("(h) two rows done", [r["status"] for r in rows] == ["done", "done"],
          [(r["target_id"], r["status"], r["steps"]) for r in rows])
    hs = garment_hair.hairstyles("Demo Pre")
    check("(h) Demo Pre wears a server hairstyle", bool(hs), hs)
    EXEC.clear()
    SUPP.clear()
    rep = await rm.discard(run)
    st = wr.get_run(run)
    check("(h) rolled_back", st["status"] == "rolled_back", (st["status"], rep.get("skipped")))
    check("(h) the undo's triggers were swallowed for Demo Pre",
          ("garment_assembly.schedule", "Demo Pre") in SUPP
          and ("figure_build.request", "Demo Pre") in SUPP, SUPP)
    check("(h) replayed exactly once each for Demo Pre",
          sorted(t for t, n in EXEC if n == "Demo Pre")
          == ["figure_build.start", "garment_assembly.schedule"], EXEC)
    check("(h) nothing for the deleted Demo Made", [e for e in EXEC if e[1] == "Demo Made"] == [], EXEC)
    check("(h) Demo Made gone", not character_row_exists("Demo Made"))
    check("(h) Demo Pre has no hairstyle any more", garment_hair.hairstyles("Demo Pre") == [],
          garment_hair.hairstyles("Demo Pre"))
    check("(h) Demo Pre not deferred", not wdm.is_deferred("Demo Pre"))


asyncio.run(main())

print()
if failures:
    print(f"FAILED ({len(failures)}):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ALL OK")
