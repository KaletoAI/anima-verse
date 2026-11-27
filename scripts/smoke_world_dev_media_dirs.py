#!/usr/bin/env python3
"""Smoke: World Dev free mode — a media removal leaves no empty dir a media
step created (plan docs/superpowers/plans/2026-11-25-world-dev-free-fixes.md,
Task 2 / F2).

A temp world and instance (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM, no render. The REAL producer adapters run; only the entry point each wraps is a fake that writes real files
(``world_ops.generate_gallery_image_core``, ``subjects.generate_building_model``),
exactly as smoke_world_dev_media_capture.py stubs them (the image-based building
path = building_models 'mesh'; the hull path is covered by smoke_world_dev_build.py).

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_media_dirs.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Fixture: location "Demo Mill" (id L), with neither ``world_gallery/L`` nor
``locations/L`` on disk (add_location creates no media dir). The fake gallery
core makes ``world_gallery/L``, writes img1.png (10 bytes), its prompts.json
entry (save_gallery_prompt) and its gallery_meta.json image_metas entry
(set_gallery_image_meta), and returns {"image": "img1.png", "location_id": L}.

  (a) gallery step on a location WITHOUT a gallery dir: the dir did not exist
      before the core ran and does after -> the step records the image AND the
      dir: types ["gallery_image", "gallery_dir"], paths
      ["world_gallery/L/img1.png", "world_gallery/L"] (image first: it is the
      step's output, the dir is appended after it); the gallery_dir record
      holds only type and path (the removal reads nothing else).
  (b) preview_artefacts == (["world_gallery/L/img1.png", "world_gallery/L"],
      []): removal order is images (type order 1) before dirs (5); the dir
      holds img1.png (removed first, so "gone") and the two gallery meta files
      (allowed at its top). remove_artefacts returns the same, and
      world_gallery/L no longer exists (the meta files went with it).
  (c) the dir existed before (an empty world_gallery/L made by hand) -> only
      ["gallery_image"] is recorded; after the removal the dir still exists
      (it was not the step's).
  (d) dir created by the step, then a foreign file world_gallery/L/foreign.png
      appears -> preview and removal both: removed
      ["world_gallery/L/img1.png"], kept [{"path": "world_gallery/L", "reason":
      "not empty"}]; foreign.png and the dir stay.
  (e) location mesh: the fake building core writes
      locations/L/model3d/model.glb; neither locations/L nor its model3d
      existed -> the artefacts hold dir "locations/L" (the extra record of the
      producer), dir "locations/L/model3d" (the root diff) and file
      "locations/L/model3d/model.glb". Removal order: file (type 2) first,
      then the dirs deepest first (model3d has 2 slashes, locations/L 1) ->
      removed == ["locations/L/model3d/model.glb", "locations/L/model3d",
      "locations/L"]; locations/L is gone.
  (f) failure: the fake core creates the dir and both meta files, then raises
      -> StepError (status "failed") with artefacts == [{"type": "gallery_dir",
      "path": "world_gallery/L"}] (path only, no location field); removing them removes the
      dir (only meta files in it) and leaves no dir behind.
  (g) the fold and the order: merge_artefacts of the (a) list with itself is
      the (a) list (a duplicate gallery_dir record is a duplicate);
      _ordered_artefacts puts gallery_dir "x/a/b" before gallery_dir "x/a"
      (the depth key applies to gallery_dir as to dir).
  (h) media_preview_lines counting: with _preview_elements stubbed to one
      location element whose artefacts are the (a) list and whose removed
      list is [img1, world_gallery/L], the one line is
      'media of location L "Demo Mill": 1 image — removed' — the gallery dir
      is no image, no model file (the phrase set is unchanged).
  (i) the dir is the one of the location the core RESOLVES: a step whose
      target is the NAME "Demo Mill" (the core answers with the resolved id
      L, as the real one does) records gallery_dir "world_gallery/L" (not
      "world_gallery/Demo_Mill"), the image record carries the resolved id L
      and the dir record no location at all; removal takes image and dir. A core that answers
      with another location O (it wrote into world_gallery/O, which did not
      exist before) -> only ["gallery_image"] at "world_gallery/O/img1.png":
      whether O's dir existed before the core ran was never checked, so it is
      not claimed as the step's; world_gallery/L was not created.
  (j) cross-turn delete_created (world_dev_tools._remove_earlier_media) of L
      with one "done" media row holding the (a) artefacts: the removal takes
      img1.png AND the gallery dir, the count of FILES removed is 1 (the dir
      is no file), and world_gallery/L is gone.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TMP = Path(tempfile.mkdtemp(prefix="smoke_wd_media_dirs_"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(TMP / "rig" / "reference.fbx")
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

from app.core import world_ops  # noqa: E402
from app.core import world_dev_media as wdm  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core.improvements.types import subjects  # noqa: E402
from app.models.world import (add_location, get_gallery_dir, save_gallery_prompt,  # noqa: E402
                              set_gallery_image_meta)

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


STORAGE = paths.get_storage_dir()

mill = add_location("Demo Mill", "a mill", rooms=[{"name": "Floor"}])
L = mill["id"]
GDIR = get_gallery_dir(L)
LDIR = STORAGE / "locations" / L
check("fixture: no gallery dir, no locations dir", not GDIR.exists() and not LDIR.exists(),
      (GDIR.exists(), LDIR.exists()))

run = wr.create_run("build", "m", "p", "u", 80, 300000, building_models="mesh")
ctx = wdm.ProduceCtx(run_id=run, row_id=1)
front = next(s for s in wdm.element_steps("location", L, "mesh") if s.id == "building-front")


async def fake_gallery(location, data):
    d = get_gallery_dir(location)
    d.mkdir(parents=True, exist_ok=True)
    (d / "img1.png").write_bytes(b"0123456789")
    save_gallery_prompt(location, "img1.png", "a prompt")
    set_gallery_image_meta(location, "img1.png", {"backend": "stub"})
    return {"status": "success", "location_id": location, "image": "img1.png"}


async def failing_gallery(location, data):
    d = get_gallery_dir(location)
    d.mkdir(parents=True, exist_ok=True)
    save_gallery_prompt(location, "img1.png", "a prompt")
    set_gallery_image_meta(location, "img1.png", {"backend": "stub"})
    raise RuntimeError("smoke: the backend failed")


world_ops.generate_gallery_image_core = fake_gallery


def produce():
    return wdm.PRODUCERS["gallery"](ctx, "location", L, front)


IMG = f"world_gallery/{L}/img1.png"
GREL = f"world_gallery/{L}"

# ── (a) ──────────────────────────────────────────────────────────────────
print("(a) a step that creates the gallery dir records it")
_, arts_a = produce()
check("(a) types", [a.get("type") for a in arts_a] == ["gallery_image", "gallery_dir"], arts_a)
check("(a) paths", [a.get("path") for a in arts_a] == [IMG, GREL], arts_a)
check("(a) gallery_dir is path only", set(arts_a[-1]) == {"type", "path"}, arts_a)
check("(a) meta files written", (GDIR / "gallery_meta.json").is_file() and (GDIR / "prompts.json").is_file(),
      sorted(os.listdir(GDIR)))

# ── (b) ──────────────────────────────────────────────────────────────────
print("(b) preview and removal")
check("(b) preview", wdm.preview_artefacts(arts_a) == ([IMG, GREL], []), wdm.preview_artefacts(arts_a))
res = wdm.remove_artefacts(arts_a)
check("(b) remove", res == ([IMG, GREL], []), res)
check("(b) gallery dir gone", not GDIR.exists())

# ── (c) ──────────────────────────────────────────────────────────────────
print("(c) a pre-existing gallery dir is not recorded")
GDIR.mkdir(parents=True)
_, arts_c = produce()
check("(c) only the image", [a.get("type") for a in arts_c] == ["gallery_image"], arts_c)
res = wdm.remove_artefacts(arts_c)
check("(c) image removed", res == ([IMG], []), res)
check("(c) dir stays", GDIR.is_dir())
shutil.rmtree(GDIR)

# ── (d) ──────────────────────────────────────────────────────────────────
print("(d) a foreign file keeps the dir")
_, arts_d = produce()
(GDIR / "foreign.png").write_bytes(b"foreign")
expected_d = ([IMG], [{"path": GREL, "reason": wdm.KEPT_NOT_EMPTY}])
check("(d) preview", wdm.preview_artefacts(arts_d) == expected_d, wdm.preview_artefacts(arts_d))
res = wdm.remove_artefacts(arts_d)
check("(d) remove", res == expected_d, res)
check("(d) foreign file and dir stay", (GDIR / "foreign.png").is_file())
shutil.rmtree(GDIR)

# ── (e) ──────────────────────────────────────────────────────────────────
print("(e) location mesh records locations/<key>")


def fake_building(location_id, backend):
    d = STORAGE / "locations" / location_id / "model3d"
    d.mkdir(parents=True, exist_ok=True)
    (d / "model.glb").write_bytes(b"glb")


subjects.generate_building_model = fake_building
mesh = wdm.StepSpec("mesh", "mesh", (), "", "mesh")
_, arts_e = wdm.PRODUCERS["location_mesh"](ctx, "location", L, mesh)
pairs = sorted((a.get("type"), a.get("path")) for a in arts_e)
check("(e) artefacts", pairs == sorted([("dir", f"locations/{L}"), ("dir", f"locations/{L}/model3d"),
                                        ("file", f"locations/{L}/model3d/model.glb")]), pairs)
pre = wdm.preview_artefacts(arts_e)
res = wdm.remove_artefacts(arts_e)
order = [f"locations/{L}/model3d/model.glb", f"locations/{L}/model3d", f"locations/{L}"]
check("(e) preview order", pre == (order, []), pre)
check("(e) removal order", res == (order, []), res)
check("(e) locations/<key> gone", not LDIR.exists())

# ── (f) ──────────────────────────────────────────────────────────────────
print("(f) a failing step carries the dir it created")
world_ops.generate_gallery_image_core = failing_gallery
err = None
try:
    produce()
except wdm.StepError as e:
    err = e
check("(f) StepError failed", err is not None and err.status == "failed", err)
check("(f) artefacts", err is not None and err.artefacts == [{"type": "gallery_dir", "path": GREL}],
      err and err.artefacts)
res = wdm.remove_artefacts(err.artefacts if err else [])
check("(f) dir removed", res == ([GREL], []) and not GDIR.exists(), (res, GDIR.exists()))
world_ops.generate_gallery_image_core = fake_gallery

# ── (g) ──────────────────────────────────────────────────────────────────
print("(g) fold and depth order")
check("(g) duplicate gallery_dir folds", wdm.merge_artefacts(arts_a, arts_a) == arts_a,
      wdm.merge_artefacts(arts_a, arts_a))
ordered = wdm._ordered_artefacts([{"type": "gallery_dir", "path": "x/a"},
                                  {"type": "gallery_dir", "path": "x/a/b"}])
check("(g) deepest gallery_dir first", [a["path"] for a in ordered] == ["x/a/b", "x/a"], ordered)

# ── (h) ──────────────────────────────────────────────────────────────────
print("(h) the preview counts no dir as an image or file")
wdm._preview_elements = lambda _run: [{"kind": "location", "id": L, "artefacts": arts_a,
                                       "removed": [IMG, GREL], "kept": [], "running": []}]
lines = wdm.media_preview_lines(run)
check("(h) one line, one image", lines == [f'media of location {L} "Demo Mill": 1 image — removed'], lines)

# ── (i) ──────────────────────────────────────────────────────────────────
print("(i) the gallery dir is the resolved location's")
if GDIR.exists():
    shutil.rmtree(GDIR)


async def resolving_gallery(location, data):
    # The real core answers with the RESOLVED id, whatever it was called with.
    return {**await fake_gallery(location, data), "location_id": L}


world_ops.generate_gallery_image_core = resolving_gallery
_, arts_i = wdm.PRODUCERS["gallery"](ctx, "location", "Demo Mill", front)
check("(i) by name: image + dir of L",
      [(a.get("type"), a.get("path")) for a in arts_i] == [("gallery_image", IMG), ("gallery_dir", GREL)],
      arts_i)
check("(i) by name: the image carries the resolved id, the dir no name",
      arts_i[0].get("location_id") == L and "location_id" not in arts_i[1], arts_i)
check("(i) by name: removal", wdm.remove_artefacts(arts_i) == ([IMG, GREL], []) and not GDIR.exists(),
      GDIR.exists())
other = add_location("Demo Barn", "a barn", rooms=[{"name": "Floor"}])
O = other["id"]
ODIR = get_gallery_dir(O)


async def elsewhere_gallery(location, data):
    return await fake_gallery(O, data)


world_ops.generate_gallery_image_core = elsewhere_gallery
_, arts_o = produce()
check("(i) other location: only the image",
      [(a.get("type"), a.get("path")) for a in arts_o] == [("gallery_image", f"world_gallery/{O}/img1.png")],
      arts_o)
check("(i) other location: L's dir not created", not GDIR.exists() and ODIR.is_dir(),
      (GDIR.exists(), ODIR.exists()))
shutil.rmtree(ODIR)
world_ops.generate_gallery_image_core = fake_gallery

# ── (j) ──────────────────────────────────────────────────────────────────
print("(j) cross-turn delete_created counts files, not the gallery dir")
from types import SimpleNamespace  # noqa: E402

from app.core import world_dev_tools as wdt  # noqa: E402

_, arts_j = produce()
row_j = wr.add_media_row(run, "location", L, [])
wr.update_media_row(row_j, status="done", produced=arts_j)
count = wdt._remove_earlier_media(SimpleNamespace(ctx=SimpleNamespace(run_id=run)), "location", L)
check("(j) one file removed", count == 1, count)
check("(j) gallery dir gone", not GDIR.exists(), sorted(os.listdir(GDIR)) if GDIR.exists() else None)

if failures:
    print(f"\nFAILED: {len(failures)}")
    sys.exit(1)
print("\nOK")
