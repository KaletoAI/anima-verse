#!/usr/bin/env python3
"""Smoke: World Dev free mode — the media phase end to end (plan
docs/superpowers/plans/2026-11-25-world-dev-free-media.md, Task 12): one
scripted turn builds a place with one room and a humanoid character, the
server renders their media at the turn end, Discard removes every file the
run produced, and the system prompt tells the model what the server renders.

A temp world and instance (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no real LLM, no render: ``get_image_service``
raises, every render producer in ``world_dev_media.PRODUCERS`` is a fake
(only the hairstyle adapter is real: make_hairstyle renders nothing). The
REAL step_gate runs; only ``route_check`` is replaced: None for every
occasion except ``mesh_building``, which answers the empty-chain note
``ROUTE_NO_CHAIN`` ("no routing chain for mesh_building — ..."). The lane
task runs synchronously: the task queue's ``submit`` calls ``run_lane``
inline.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_media_scenario.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

The plugin registry holds one species with a hair body slot (as
smoke_world_dev_media_lifecycle), so a humanoid with hair in its body slot
is on the base-body pipeline with hair text. ``figure_build.planned_work``
is pinned to one runnable "shape" step (a fresh world has no plain body, so
the real explicit plan — the lane's Build is a manual one, BUILD_EXPLICIT —
would be the plain body, whose base_front/base_view occasions this smoke
does not need to route).

  (a) turn 1 [create_location "Demo Mill" (room "Loft"), create_character
      "Demo Mira" (female, hair black / long), "Built."] -&gt; awaiting_review,
      2 elements (one media row each).
      Location row, hand count: gallery steps building-front, day:, night:
      (the place itself, room id ""), day:&lt;loft&gt;, night:&lt;loft&gt; (the one
      non-corridor room) = 5, plus mesh = 6 steps. The 5 gallery steps are
      done (the gallery fake writes one image each = 5 images), mesh is
      skipped with exactly ROUTE_NO_CHAIN for mesh_building, the row is done.
      Character row: steps hairstyle, portrait, build (hair text present,
      base-body pipeline), all done. The hairstyle is a real item worn by
      Demo Mira (make_hairstyle).
  (b) discard_preview holds: a line naming the location and one naming the
      character (both created by the run), the media line of the location
      'media of location &lt;id&gt; "Demo Mill": 5 images — removed' (the mesh was
      skipped, so no model file) and a media line of the character
      ('media of character ... 1 model file — removed': the build fake's
      k.glb; the portrait fake writes nothing). Discard -&gt; report complete
      True, media.kept == [], media.pending == [] (the lane ran inline,
      nothing runs); no file the run produced is left (the 5 images,
      k.glb), the gallery dir of the place and the character dir hold no
      file; the hairstyle item is gone from the inventory.
  (c) _render_system() contains the section "## Images and 3D models" and
      the "What you cannot build" list no longer names "images, 3D models".
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

TMP = Path(tempfile.mkdtemp(prefix="smoke_wd_media_scen_"))
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
from app.models import inventory  # noqa: E402
from app.models.character import get_character_dir  # noqa: E402
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
ROUTE_CALLS = []


def fake_route_check(occasion, character="", *, chain_only=False):
    """Every occasion is routable except the building mesh, whose chain is
    empty (the note the real route_check gives for an empty chain)."""
    ROUTE_CALLS.append(occasion)
    if occasion == "mesh_building":
        return wdm.ROUTE_NO_CHAIN.format(occasion=occasion)
    return None


wdm.route_check = fake_route_check
# A fresh temp world has no plain body, so the REAL explicit plan would be the
# plain body step. The plan the gate reads is pinned to one runnable step
# ("shape", as on a stored plain body); the Build itself is the fake producer below.
_SHAPE = figure_build.Step(name="shape", label="Shape", jobs=1)
figure_build.planned_work = lambda *_a, **_k: ([_SHAPE], [_SHAPE])

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



def files_under(root):
    root = Path(root)
    return sorted(str(p) for p in root.rglob("*") if p.is_file()) if root.exists() else []


async def main():
    print("(a) one turn builds a place and a character -&gt; media rendered")
    LANE["inline"] = True
    rm, fake = manager()
    fake.replies = [create_loc("Demo Mill", rooms=("Loft",)),
                    call("create_character", {"data": {
                        "name": "Demo Mira", "gender": "female",
                        "body_slots": {"hair": {"color": "black", "length": "long"}}}}),
                    "Built."]
    run = await rm.start("build", "fake-model", "fake", "u1")
    st = await settle(rm, run)
    mill = loc_id("Demo Mill")
    loft = next((str(r["id"]) for r in (get_location_by_id(mill) or {}).get("rooms") or []
                 if r.get("name") == "Loft"), "")
    check("(a) awaiting_review", st["status"] == "awaiting_review", st)
    rows = wr.media_rows(run)
    by_kind = {r["kind"]: r for r in rows}
    check("(a) two elements, one row each",
          sorted((r["kind"], r["target_id"]) for r in rows)
          == [("character", "Demo Mira"), ("location", mill)],
          [(r["kind"], r["target_id"], r["status"]) for r in rows])
    lrow = by_kind.get("location") or {"steps": []}
    lsteps = {s["id"]: s for s in lrow["steps"]}
    gallery_ids = ["building-front", "day:", "night:", f"day:{loft}", f"night:{loft}"]
    check("(a) location: 6 steps (5 gallery + mesh)",
          sorted(lsteps) == sorted(gallery_ids + ["mesh"]), sorted(lsteps))
    check("(a) the 5 gallery steps done",
          [lsteps.get(i, {}).get("status") for i in gallery_ids] == ["done"] * 5,
          [(i, lsteps.get(i, {}).get("status")) for i in gallery_ids])
    mesh = lsteps.get("mesh") or {}
    check("(a) mesh skipped with the no-chain note",
          (mesh.get("status"), mesh.get("note"))
          == ("skipped", wdm.ROUTE_NO_CHAIN.format(occasion="mesh_building")), mesh)
    check("(a) location row done", lrow.get("status") == "done", lrow.get("status"))
    crow = by_kind.get("character") or {"steps": []}
    check("(a) character: hairstyle, portrait, build done",
          [(s["id"], s["status"]) for s in crow["steps"]]
          == [("hairstyle", "done"), ("portrait", "done"), ("build", "done")],
          [(s["id"], s["status"], s.get("note")) for s in crow["steps"]])
    check("(a) character row done", crow.get("status") == "done", crow.get("status"))
    hs = garment_hair.hairstyles("Demo Mira")
    check("(a) Demo Mira owns one hairstyle", len(hs) == 1, hs)
    hs_ids = [str(h.get("id")) for h in hs]
    files = [f for r in rows for f in row_files(r)]
    check("(a) 6 files exist (5 images + k.glb)", len(files) == 6 and exist(files) == files, files)

    print("(b) discard removes the media")
    preview = wu.discard_preview(run)
    loc_lines = [l for l in preview if mill in l and "Demo Mill" in l and not l.startswith("media of")]
    chr_lines = [l for l in preview if "Demo Mira" in l and not l.startswith("media of")]
    check("(b) preview: the location", bool(loc_lines), preview)
    check("(b) preview: the character", bool(chr_lines), preview)
    want = f'media of location {mill} "Demo Mill": 5 images — removed'
    check("(b) preview: the location's media line", want in preview, preview)
    cmedia = [l for l in preview if l.startswith("media of character") and "Demo Mira" in l]
    check("(b) preview: the character's media line",
          len(cmedia) == 1 and cmedia[0].endswith("1 model file — removed"), cmedia)
    rep = await rm.discard(run)
    media = rep.get("media") or {}
    check("(b) complete", rep.get("complete") is True, rep)
    check("(b) media.kept == []", media.get("kept") == [], media)
    check("(b) media.pending == []", media.get("pending") == [], media)
    check("(b) no produced file left", exist(files) == [], exist(files))
    gleft = files_under(get_gallery_dir(mill))
    check("(b) the gallery dir holds no file", gleft == [], gleft)
    cleft = files_under(get_character_dir("Demo Mira"))
    check("(b) the character dir holds no file", cleft == [], cleft)
    rleft = [f for root in wdm.producer_roots("Demo Mira") for f in files_under(root)]
    check("(b) the media roots hold no file", rleft == [], rleft)
    check("(b) the hairstyle item is gone",
          bool(hs_ids) and all(inventory.get_item(i) is None for i in hs_ids), hs_ids)
    check("(b) rolled_back", wr.get_run(run)["status"] == "rolled_back", wr.get_run(run)["status"])

    print("(c) the system prompt names the server's renders")
    system = wa._render_system()
    check("(c) section '## Images and 3D models'", "## Images and 3D models" in system)
    cannot = system.split("## What you cannot build", 1)[-1].split("\n## ", 1)[0]
    check("(c) the cannot-build list no longer names images / 3D models",
          "images, 3D models" not in cannot and "images, 3D models" not in system, cannot)


asyncio.run(main())

print()
if failures:
    print(f"FAILED ({len(failures)}):")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ALL OK")
