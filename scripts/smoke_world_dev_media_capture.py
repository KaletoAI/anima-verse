#!/usr/bin/env python3
"""Smoke: World Dev free mode — the media producers and the exact capture and
removal of what they produce (plan
docs/superpowers/plans/2026-11-25-world-dev-free-media.md, Task 7).

A temp world and instance (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM, no render: ``get_image_service`` raises.
The REAL producer adapters of ``world_dev_media.PRODUCERS`` run; only the ENTRY
POINT each one wraps is replaced by a fake that writes real files into the
element's real roots (``world_ops.generate_gallery_image_core``,
``subjects.generate_building_model``, ``npc_assets.render_profile_image`` /
``render_mesh``, ``figure_build.request`` / ``state``, ``make_hairstyle``).

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_media_capture.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Paths are relative to the storage dir. A location's media root is its model
dir ``locations/<id>/model3d``; gallery images are recorded by the name the
gallery core returns (``world_gallery/<id>/<image>``). A character's roots are
``characters/<name>/{model3d, model_refs, images, garments, jewellery,
template_front}`` (``world_dev_media.media_roots``).

  (a) gallery: the fake core writes world_gallery/<keep>/img_1.png and types
      it "building-front" through the real gallery meta writer; the adapter
      passed {"prompt_type": "building-front", "room_id": ""} and records ONE
      artefact {"type": "gallery_image", location_id, image "img_1.png", path,
      size 4 (b"png1"), mtime_ns of the file}. The day step of room r1 passes
      {"prompt_type": "day", "room_id": r1}. preview removes exactly both
      paths; remove -> both files gone, list_gallery_images no longer lists
      them, the type entry of img_1.png is gone and prompts.json (written by
      the fake through save_gallery_prompt) holds neither image any more.
      The fake also writes {"backend": "stub"} through set_gallery_image_meta
      (as generate_gallery_image_core does); after removal image_metas holds
      neither image, while a foreign entry "other.png" written before the
      step stays exactly {"backend": "keep"}.
  (b) location_mesh: model dir pre-filled with model_a.json = '{"v": 1}'. The
      fake (called with backend "") writes model_a.glb (5 bytes), lod/a.glb and
      rewrites model_a.json = '{"v": 2}' -> artefacts, in path order: dir
      lod, file lod/a.glb, file model_a.glb, sidecar model_a.json (sha256 of
      '{"v": 2}'). Removal -> both glbs gone, lod gone (empty after its file),
      model_a.json reads '{"v": 1}' byte for byte.
  (c) a second mesh run writes model_b.glb; the glb is then touched (mtime +1
      s) -> preview AND remove both keep it "changed since"; the file stays.
  (d) portrait of "Demo A" (profile_image absent before): the fake writes
      images/portrait_1.png + its meta images/portrait_1.json and sets
      profile_image = "portrait_1.png" under the profile lock -> artefacts
      character_image (companion images/portrait_1.json) and profile_keys
      {before {profile_image: ABSENT}, after {profile_image: "portrait_1.png"}}
      (+ the dir "images", which did not exist before). Removal -> the key is
      absent again, both files gone. (d2) a second portrait, then the admin
      sets profile_image = "other.png" -> the key is kept "changed since" and
      stays "other.png"; the unchanged image file is removed.
  (e) mesh of "Demo B" (model3d pre-filled with old.png = b"old"): the fake
      rewrites old.png = b"new!" and writes sig.glb -> artefacts file sig.glb +
      modified old.png; removal deletes sig.glb, keeps old.png ("modified, not
      restored") with b"new!".
  (f) the soul dir lies under none of the character's media roots; every root
      lies directly inside the character dir; the six root names.
  (g) every case: set(removed of preview) == set(removed of remove), and the
      kept records agree.
  (h) "Demo Ruin" (marked created by the run): two gallery images; one is
      deleted by hand -> its record "already gone", no exception. Then the row
      goes (delete_location_row, which leaves the files) -> the remaining image
      is unlinked by its recorded path. sweep_orphan_dirs -> its gallery dir
      (only gallery_meta.json / prompts.json left) and locations/<ruin> are
      gone. "Demo Fort" (created, a foreign notes.txt in its gallery) -> the
      dir is kept, reason "not the run's".
  (i) mesh with a producer note ("mesh: smoke failure") -> StepError status
      "failed", note carried, the written glb is in its artefacts (capture
      survives the failure).
  (j) build: request is called with (name, "world_dev"); the fake state says
      running twice, then idle -> 3 polls, note "", the file written during
      the Build is an artefact. A Build whose state lists a failed step ->
      StepError "failed" naming it, artefacts kept. request False ->
      StepError "skipped".
  (k) hairstyle: make_hairstyle ("done", "") -> ("", []); ("skipped", "no
      hairstyle needed") -> StepError "skipped" with that note.
  (l) MEDIA_PROFILE_KEYS == ("profile_image",) and no tool writes it (the
      tools module never names it).
  (m) merge: a step creates model3d/new.json, a later step rewrites it -> the
      later diff alone says "sidecar"; merge_artefacts keeps ONE file record
      with the newest size/mtime, and removal deletes the file.
  (n) gallery core raising MediaGenerationDisabled -> StepError "skipped" with
      the disabled note; HTTPException(503, "no backend") -> "failed", note
      "no backend".
  (o) concurrent writer: the Build fake ALSO writes images/hand.png and sets
      profile_image = "hand.png" (an admin's hand-rendered portrait during
      the Build); the mesh fake likewise writes images/hand2.png. The
      artefacts are exactly [file model3d/o.glb] / [file model3d/o2.glb] —
      images/ is not a Build/mesh root and no profile key is captured; after
      removal both hand images and profile_image "hand.png" are untouched.
  (p) sidecar backups across steps (same row): model3d/side.json = '{"s": 0}'
      before; step 1 writes '{"s": 1}', step 2 '{"s": 2}' -> two sidecar
      records with DIFFERENT backup files (step 2 must not overwrite step 1's
      pre-run backup); merge keeps step 1's backup (bytes '{"s": 0}'), the
      sha256 and stat of '{"s": 2}' (size 8, the file's mtime_ns now), and
      unlinks step 2's backup; removal restores
      '{"s": 0}' and deletes the kept backup. (m) likewise: the dropped
      sidecar's backup file is gone after the merge.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TMP = Path(tempfile.mkdtemp(prefix="smoke_wd_media_capture_"))
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

from fastapi import HTTPException  # noqa: E402

from app.core import figure_build, npc_assets, world_ops  # noqa: E402
from app.core import world_dev_media as wdm  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core.improvements.types import subjects  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.core.world_dev_undo import ABSENT  # noqa: E402
from app.imagegen.base import MediaGenerationDisabled  # noqa: E402
from app.models.character import (get_character_dir, get_character_profile,  # noqa: E402
                                  save_character_profile)
from app.models.world import (add_location, delete_location_row, get_gallery_dir,  # noqa: E402
                              get_gallery_image_types, list_gallery_images,
                              get_all_gallery_prompts, get_gallery_image_metas,
                              save_gallery_prompt, set_gallery_image_meta,
                              set_gallery_image_type)

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


STORAGE = paths.get_storage_dir()


def rel(p):
    return Path(p).relative_to(STORAGE).as_posix()


def stat_of(p):
    st = os.stat(p)
    return st.st_size, st.st_mtime_ns


def removal(arts, label):
    """(g): preview first, then remove; the two must agree."""
    p_removed, p_kept = wdm.preview_artefacts(arts)
    r_removed, r_kept = wdm.remove_artefacts(arts)
    check(f"{label}: preview removed == remove removed", set(p_removed) == set(r_removed),
          (p_removed, r_removed))
    check(f"{label}: preview kept == remove kept",
          sorted(json.dumps(k, sort_keys=True) for k in p_kept)
          == sorted(json.dumps(k, sort_keys=True) for k in r_kept), (p_kept, r_kept))
    return r_removed, r_kept


def step_of(kind, ident, step_id):
    return next(s for s in wdm.element_steps(kind, ident) if s.id == step_id)


def expect_error(fn, label):
    try:
        fn()
    except wdm.StepError as e:
        return e
    except Exception as e:  # noqa: BLE001
        check(f"{label}: StepError raised", False, repr(e))
        return None
    check(f"{label}: StepError raised", False, "no exception")
    return None


def mesh_step(step_id="mesh"):
    return wdm.StepSpec(step_id, step_id, (), "", step_id)


keep = add_location("Demo Keep", "a keep", rooms=[{"name": "Hall"}])
lid = keep["id"]
r1 = next(str(r["id"]) for r in keep["rooms"] if r["name"] == "Hall")
for n in ("Demo A", "Demo B", "Demo C"):
    check(f"fixture {n}", save_character_profile(n, {"name": n, "template": "human-roleplay",
                                                     "gender": "female", "age": 30}, create_new=True))
    get_character_dir(n, create=True)

run = wr.create_run("build", "m", "p", "u", 80, 300000)
ctx = wdm.ProduceCtx(run_id=run, row_id=1)

# ── (a) gallery ──────────────────────────────────────────────────────────
print("(a) gallery")
GALLERY_CALLS = []


async def fake_gallery(location, data):
    GALLERY_CALLS.append((location, dict(data)))
    name = f"img_{len(GALLERY_CALLS)}.png"
    d = get_gallery_dir(location)
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(f"png{len(GALLERY_CALLS)}".encode())
    save_gallery_prompt(location, name, "a prompt")
    set_gallery_image_type(location, name, data.get("prompt_type") or "")
    set_gallery_image_meta(location, name, {"backend": "stub"})
    return {"status": "success", "location_id": location, "image": name}


world_ops.generate_gallery_image_core = fake_gallery
set_gallery_image_meta(lid, "other.png", {"backend": "keep"})
note, arts_front = wdm.PRODUCERS["gallery"](ctx, "location", lid, step_of("location", lid, "building-front"))
gdir = get_gallery_dir(lid)
size, mtime = stat_of(gdir / "img_1.png")
check("(a) core called with building-front", GALLERY_CALLS[0] == (lid, {"prompt_type": "building-front",
                                                                        "room_id": ""}), GALLERY_CALLS)
check("(a) one gallery artefact", arts_front == [{
    "type": "gallery_image", "location_id": lid, "image": "img_1.png",
    "path": f"world_gallery/{lid}/img_1.png", "size": 4, "mtime_ns": mtime}] and note == "",
    (note, arts_front))
note, arts_day = wdm.PRODUCERS["gallery"](ctx, "location", lid, step_of("location", lid, f"day:{r1}"))
check("(a) day step passes the room", GALLERY_CALLS[1] == (lid, {"prompt_type": "day", "room_id": r1}),
      GALLERY_CALLS)
check("(a) image_metas written by the fake", {"img_1.png", "img_2.png"} <= set(get_gallery_image_metas(lid)),
      get_gallery_image_metas(lid))
removed, kept = removal(arts_front + arts_day, "(a)")
check("(a) both removed", sorted(removed) == sorted([f"world_gallery/{lid}/img_1.png",
                                                     f"world_gallery/{lid}/img_2.png"]) and kept == [],
      (removed, kept))
check("(a) files gone", not (gdir / "img_1.png").exists() and not (gdir / "img_2.png").exists())
check("(a) gallery lists neither", "img_1.png" not in list_gallery_images(lid)
      and "img_2.png" not in list_gallery_images(lid), list_gallery_images(lid))
check("(a) type entry gone", "img_1.png" not in get_gallery_image_types(lid), get_gallery_image_types(lid))
check("(a) image_metas entries gone", not ({"img_1.png", "img_2.png"} & set(get_gallery_image_metas(lid))),
      get_gallery_image_metas(lid))
check("(a) foreign image_metas entry kept", get_gallery_image_metas(lid).get("other.png") == {"backend": "keep"},
      get_gallery_image_metas(lid))
check("(a) prompts.json entries gone", not ({"img_1.png", "img_2.png"} & set(get_all_gallery_prompts(lid))),
      get_all_gallery_prompts(lid))

# ── (b) location mesh ────────────────────────────────────────────────────
print("(b) location mesh")
mdir = wdm.media_roots("location", lid)[0]
check("(b) the location root is its model dir", rel(mdir) == f"locations/{lid}/model3d", rel(mdir))
mdir.mkdir(parents=True, exist_ok=True)
(mdir / "model_a.json").write_text('{"v": 1}', encoding="utf-8")
MESH_CALLS = []


def fake_building(location_id, backend):
    MESH_CALLS.append((location_id, backend))
    (mdir / "model_a.glb").write_bytes(b"glb-a")
    (mdir / "lod").mkdir(exist_ok=True)
    (mdir / "lod" / "a.glb").write_bytes(b"lod")
    (mdir / "model_a.json").write_text('{"v": 2}', encoding="utf-8")


subjects.generate_building_model = fake_building
note, arts_b = wdm.PRODUCERS["location_mesh"](ctx, "location", lid, step_of("location", lid, "mesh"))
check("(b) called with backend ''", MESH_CALLS == [(lid, "")], MESH_CALLS)
base = f"locations/{lid}/model3d"
check("(b) artefact types in path order",
      [(a["type"], a["path"]) for a in arts_b] == [("dir", f"{base}/lod"), ("file", f"{base}/lod/a.glb"),
                                                   ("file", f"{base}/model_a.glb"),
                                                   ("sidecar", f"{base}/model_a.json")],
      [(a["type"], a["path"]) for a in arts_b])
side = next((a for a in arts_b if a["type"] == "sidecar"), {})
check("(b) sidecar sha256 = post-step text", side.get("sha256") == hashlib.sha256(b'{"v": 2}').hexdigest(), side)
removed, kept = removal(arts_b, "(b)")
check("(b) glbs and lod gone", not (mdir / "model_a.glb").exists() and not (mdir / "lod").exists(),
      sorted(p.name for p in mdir.iterdir()))
check("(b) sidecar restored byte for byte", (mdir / "model_a.json").read_bytes() == b'{"v": 1}',
      (mdir / "model_a.json").read_bytes())
check("(b) nothing kept", kept == [], kept)

# ── (c) changed since ────────────────────────────────────────────────────
print("(c) changed since")


def fake_building_b(location_id, backend):
    (mdir / "model_b.glb").write_bytes(b"glb-b")


subjects.generate_building_model = fake_building_b
_, arts_c = wdm.PRODUCERS["location_mesh"](ctx, "location", lid, step_of("location", lid, "mesh"))
st = os.stat(mdir / "model_b.glb")
os.utime(mdir / "model_b.glb", ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
removed, kept = removal(arts_c, "(c)")
check("(c) kept changed since", removed == [] and kept == [{"path": f"{base}/model_b.glb",
                                                            "reason": "changed since"}], (removed, kept))
check("(c) file stays", (mdir / "model_b.glb").exists())

# ── (d) portrait ─────────────────────────────────────────────────────────
print("(d) portrait")
images = get_character_dir("Demo A") / "images"
images_existed = images.is_dir()


def make_fake_portrait(fname):
    def fake(name):
        d = get_character_dir(name) / "images"
        d.mkdir(parents=True, exist_ok=True)
        (d / fname).write_bytes(b"portrait")
        (d / (Path(fname).stem + ".json")).write_text("{}", encoding="utf-8")
        with keyed_lock("character_profile", name):
            prof = get_character_profile(name) or {}
            prof["profile_image"] = fname
            save_character_profile(name, prof)
        return ""
    return fake


check("(d) profile_image empty before", not (get_character_profile("Demo A") or {}).get("profile_image"),
      get_character_profile("Demo A"))
before_value = (get_character_profile("Demo A") or {}).get("profile_image", ABSENT)
npc_assets.render_profile_image = make_fake_portrait("portrait_1.png")
note, arts_d = wdm.PRODUCERS["portrait"](ctx, "character", "Demo A", step_of("character", "Demo A", "portrait"))
ci = [a for a in arts_d if a["type"] == "character_image"]
pk = [a for a in arts_d if a["type"] == "profile_keys"]
dirs = [a for a in arts_d if a["type"] == "dir"]
check("(d) one character image with its meta companion",
      len(ci) == 1 and ci[0]["file"] == "portrait_1.png" and ci[0]["name"] == "Demo A"
      and ci[0]["companions"] == [rel(images / "portrait_1.json")], arts_d)
check("(d) profile_keys before/after",
      len(pk) == 1 and pk[0]["before"] == {"profile_image": before_value}
      and pk[0]["after"] == {"profile_image": "portrait_1.png"}, pk)
check("(d) the images dir is an artefact iff it is new",
      [a["path"] for a in dirs] == ([] if images_existed else [rel(images)]), (images_existed, dirs))
check("(d) nothing else", len(arts_d) == 2 + len(dirs), arts_d)
removed, kept = removal(arts_d, "(d)")
check("(d) key back to its before value",
      (get_character_profile("Demo A") or {}).get("profile_image", ABSENT) == before_value,
      get_character_profile("Demo A"))
check("(d) image and meta gone", not (images / "portrait_1.png").exists()
      and not (images / "portrait_1.json").exists())
check("(d) nothing kept", kept == [], kept)

print("(d2) admin changed the key")
npc_assets.render_profile_image = make_fake_portrait("portrait_2.png")
_, arts_d2 = wdm.PRODUCERS["portrait"](ctx, "character", "Demo A", step_of("character", "Demo A", "portrait"))
with keyed_lock("character_profile", "Demo A"):
    prof = get_character_profile("Demo A")
    prof["profile_image"] = "other.png"
    save_character_profile("Demo A", prof)
removed, kept = removal(arts_d2, "(d2)")
check("(d2) key kept changed since",
      {"item": "profile Demo A.profile_image", "reason": "changed since"} in kept, kept)
check("(d2) value untouched", (get_character_profile("Demo A") or {}).get("profile_image") == "other.png",
      get_character_profile("Demo A"))
check("(d2) unchanged image removed", not (images / "portrait_2.png").exists()
      and rel(images / "portrait_2.png") in removed, removed)

# ── (e) modified binary ──────────────────────────────────────────────────
print("(e) modified binary")
b3d = get_character_dir("Demo B") / "model3d"
b3d.mkdir(parents=True, exist_ok=True)
(b3d / "old.png").write_bytes(b"old")


def fake_mesh_e(name):
    d = get_character_dir(name) / "model3d"
    (d / "old.png").write_bytes(b"new!")
    (d / "sig.glb").write_bytes(b"sig")
    return ""


npc_assets.render_mesh = fake_mesh_e
note, arts_e = wdm.PRODUCERS["mesh"](ctx, "character", "Demo B", mesh_step())
check("(e) file + modified", sorted((a["type"], a["path"]) for a in arts_e)
      == [("file", rel(b3d / "sig.glb")), ("modified", rel(b3d / "old.png"))], arts_e)
removed, kept = removal(arts_e, "(e)")
check("(e) glb removed", removed == [rel(b3d / "sig.glb")] and not (b3d / "sig.glb").exists(), removed)
check("(e) png kept, never touched",
      kept == [{"path": rel(b3d / "old.png"), "reason": "modified, not restored"}]
      and (b3d / "old.png").read_bytes() == b"new!", kept)

# ── (f) soul never a root ────────────────────────────────────────────────
print("(f) roots")
roots = [Path(r) for r in wdm.media_roots("character", "Demo A")]
char_dir = get_character_dir("Demo A")
soul = char_dir / "soul"
check("(f) the soul lies under no root", not any(soul.is_relative_to(r) or r == char_dir for r in roots),
      roots)
check("(f) every root directly inside the character dir", all(r.parent == char_dir for r in roots), roots)
check("(f) the roots", sorted(r.name for r in roots)
      == sorted(["model3d", "model_refs", "images", "garments", "jewellery", "template_front"]), roots)
from app.core import accessory_build, garment_preview_front  # noqa: E402

check("(f) the module dir names are roots", {accessory_build.DIR_NAME, garment_preview_front.DIR_NAME}
      <= {r.name for r in roots}, (accessory_build.DIR_NAME, garment_preview_front.DIR_NAME))

# ── (h) already gone, orphan dirs ────────────────────────────────────────
print("(h) already gone + sweep")
ruin = add_location("Demo Ruin", "a ruin")["id"]
fort = add_location("Demo Fort", "a fort")["id"]
wr.mark_created(run, "location", ruin)
wr.mark_created(run, "location", fort)
world_ops.generate_gallery_image_core = fake_gallery
_, ra = wdm.PRODUCERS["gallery"](ctx, "location", ruin, step_of("location", ruin, "day:"))
_, rb = wdm.PRODUCERS["gallery"](ctx, "location", ruin, step_of("location", ruin, "night:"))
rdir = get_gallery_dir(ruin)
(rdir / ra[0]["image"]).unlink()
(STORAGE / "locations" / ruin / "model3d").mkdir(parents=True, exist_ok=True)
check("(h) row deleted", delete_location_row(ruin))
check("(h) the gallery dir is still there (row delete leaves files)", rdir.is_dir())
removed, kept = removal(ra + rb, "(h)")
check("(h) first already gone", {"path": ra[0]["path"], "reason": "already gone"} in kept, kept)
check("(h) second unlinked by path", removed == [rb[0]["path"]] and not (STORAGE / rb[0]["path"]).exists(),
      removed)
_, fa = wdm.PRODUCERS["gallery"](ctx, "location", fort, step_of("location", fort, "day:"))
fdir = get_gallery_dir(fort)
(fdir / "notes.txt").write_text("someone else's", encoding="utf-8")
wdm.remove_artefacts(fa)
check("(h) fort row deleted", delete_location_row(fort))
sweep = wdm.sweep_orphan_dirs(run)
check("(h) ruin gallery dir gone", not rdir.exists(),
      sorted(p.name for p in rdir.iterdir()) if rdir.exists() else None)
check("(h) ruin model dir gone", not (STORAGE / "locations" / ruin).exists())
check("(h) sweep reports the ruin dirs", f"world_gallery/{ruin}" in sweep["removed"]
      and f"locations/{ruin}" in sweep["removed"], sweep)
check("(h) fort dir kept, not the run's", fdir.is_dir()
      and {"path": f"world_gallery/{fort}", "reason": "not the run's"} in sweep["kept"], sweep)
check("(h) the live keep is never swept", gdir.is_dir() and mdir.is_dir())

# ── (i) failure keeps the capture ────────────────────────────────────────
print("(i) failed mesh")


def fake_mesh_i(name):
    d = get_character_dir(name) / "model3d"
    d.mkdir(parents=True, exist_ok=True)
    (d / "half.glb").write_bytes(b"half")
    return "mesh: smoke failure"


npc_assets.render_mesh = fake_mesh_i
err = expect_error(lambda: wdm.PRODUCERS["mesh"](ctx, "character", "Demo C", mesh_step()), "(i)")
if err is not None:
    check("(i) failed with the note", err.status == "failed" and "mesh: smoke failure" in err.note, err.note)
    c3d = get_character_dir("Demo C") / "model3d"
    check("(i) the glb is captured", rel(c3d / "half.glb") in [a["path"] for a in err.artefacts],
          err.artefacts)
    wdm.remove_artefacts(err.artefacts)
    check("(i) removed", not (c3d / "half.glb").exists())

# ── (j) build ────────────────────────────────────────────────────────────
print("(j) build")
wdm.BUILD_POLL_S = 0.01
REQ = []
STATE = {"polls": 0, "failed": {}}


def fake_request(name, trigger):
    REQ.append((name, trigger))
    d = get_character_dir(name) / "model3d"
    d.mkdir(parents=True, exist_ok=True)
    (d / "built.glb").write_bytes(b"built")
    STATE["polls"] = 0
    return True


def fake_state(name):
    STATE["polls"] += 1
    busy = STATE["polls"] <= 2
    return {"running": busy, "queued": 0, "deferred": None, "failed": dict(STATE["failed"]),
            "skipped": [], "paused": None, "superseded": None}


figure_build.request = fake_request
figure_build.state = fake_state
note, arts_j = wdm.PRODUCERS["build"](ctx, "character", "Demo C", mesh_step("build"))
check("(j) request(name, 'world_dev')", REQ == [("Demo C", "world_dev")], REQ)
check("(j) polled until idle", STATE["polls"] == 3, STATE)
check("(j) done, file captured", note == "" and [a["path"] for a in arts_j if a["type"] == "file"]
      == [rel(get_character_dir("Demo C") / "model3d" / "built.glb")], (note, arts_j))
wdm.remove_artefacts(arts_j)
STATE["failed"] = {"shape": "no backend"}
err = expect_error(lambda: wdm.PRODUCERS["build"](ctx, "character", "Demo C", mesh_step("build")), "(j) failed")
if err is not None:
    check("(j) failed names the step", err.status == "failed" and "shape" in err.note, err.note)
    check("(j) failed keeps the capture", len([a for a in err.artefacts if a["type"] == "file"]) == 1,
          err.artefacts)
    wdm.remove_artefacts(err.artefacts)
figure_build.request = lambda name, trigger: False
err = expect_error(lambda: wdm.PRODUCERS["build"](ctx, "character", "Demo C", mesh_step("build")),
                   "(j) not started")
if err is not None:
    check("(j) not started = skipped", err.status == "skipped", (err.status, err.note))

# ── (k) hairstyle ────────────────────────────────────────────────────────
print("(k) hairstyle")
HS = []
wdm.make_hairstyle = lambda run_id, name: HS.append((run_id, name)) or ("done", "")
out = wdm.PRODUCERS["hairstyle"](ctx, "character", "Demo C", mesh_step("hairstyle"))
check("(k) done", out == ("", []) and HS == [(run, "Demo C")], (out, HS))
wdm.make_hairstyle = lambda run_id, name: ("skipped", "no hairstyle needed")
err = expect_error(lambda: wdm.PRODUCERS["hairstyle"](ctx, "character", "Demo C", mesh_step("hairstyle")), "(k)")
if err is not None:
    check("(k) skipped with the note", (err.status, err.note) == ("skipped", "no hairstyle needed"),
          (err.status, err.note))

# ── (l) profile keys ─────────────────────────────────────────────────────
print("(l) profile keys")
check("(l) MEDIA_PROFILE_KEYS", wdm.MEDIA_PROFILE_KEYS == ("profile_image",), wdm.MEDIA_PROFILE_KEYS)
tools_src = (Path(__file__).resolve().parent.parent / "app/core/world_dev_tools.py").read_text(encoding="utf-8")
check("(l) no tool names a media profile key", all(k not in tools_src for k in wdm.MEDIA_PROFILE_KEYS))

# ── (m) merge ────────────────────────────────────────────────────────────
print("(m) merge")


def write_new(text):
    def fake(name):
        (get_character_dir(name) / "model3d" / "new.json").write_text(text, encoding="utf-8")
        return ""
    return fake


npc_assets.render_mesh = write_new('{"n": 1}')
_, m1 = wdm.PRODUCERS["mesh"](ctx, "character", "Demo B", mesh_step())
npc_assets.render_mesh = write_new('{"n": 22}')
_, m2 = wdm.PRODUCERS["mesh"](ctx, "character", "Demo B", mesh_step())
newp = rel(b3d / "new.json")
check("(m) the later diff alone says sidecar", [(a["type"], a["path"]) for a in m2] == [("sidecar", newp)], m2)
m2_backup = STORAGE / m2[0]["backup"]
check("(m) the dropped sidecar has a backup before the merge", m2_backup.is_file(), m2)
merged = wdm.merge_artefacts(m1, m2)
check("(m) the dropped sidecar's backup is unlinked", not m2_backup.exists())
size, mtime = stat_of(b3d / "new.json")
check("(m) one file record, newest stat", merged == [{"type": "file", "path": newp, "size": size,
                                                      "mtime_ns": mtime}], merged)
removed, kept = removal(merged, "(m)")
check("(m) removed", removed == [newp] and not (b3d / "new.json").exists(), removed)

# ── (n) gallery errors ───────────────────────────────────────────────────
print("(n) gallery errors")


async def disabled(location, data):
    raise MediaGenerationDisabled("off")


async def http503(location, data):
    raise HTTPException(status_code=503, detail="no backend")


world_ops.generate_gallery_image_core = disabled
err = expect_error(lambda: wdm.PRODUCERS["gallery"](ctx, "location", lid, step_of("location", lid, "day:")),
                   "(n) disabled")
if err is not None:
    check("(n) disabled = skipped", (err.status, err.note) == ("skipped", wdm.GATE_DISABLED),
          (err.status, err.note))
world_ops.generate_gallery_image_core = http503
err = expect_error(lambda: wdm.PRODUCERS["gallery"](ctx, "location", lid, step_of("location", lid, "day:")),
                   "(n) 503")
if err is not None:
    check("(n) 503 = failed", (err.status, err.note) == ("failed", "no backend"), (err.status, err.note))

# ── (o) concurrent writer into images/ ───────────────────────────────────
print("(o) concurrent writer")
cimg = get_character_dir("Demo C") / "images"


def fake_request_o(name, trigger):
    d = get_character_dir(name)
    (d / "model3d").mkdir(parents=True, exist_ok=True)
    (d / "model3d" / "o.glb").write_bytes(b"o")
    cimg.mkdir(parents=True, exist_ok=True)
    (cimg / "hand.png").write_bytes(b"hand")
    with keyed_lock("character_profile", name):
        prof = get_character_profile(name) or {}
        prof["profile_image"] = "hand.png"
        save_character_profile(name, prof)
    STATE["polls"] = 0
    return True


STATE["failed"] = {}
(get_character_dir("Demo C") / "model3d").mkdir(parents=True, exist_ok=True)  # (j)'s removal took it
figure_build.request = fake_request_o
_, arts_o = wdm.PRODUCERS["build"](ctx, "character", "Demo C", mesh_step("build"))
o_glb = rel(get_character_dir("Demo C") / "model3d" / "o.glb")
check("(o) build: only its own glb", [(a["type"], a["path"]) for a in arts_o] == [("file", o_glb)], arts_o)


def fake_mesh_o(name):
    (get_character_dir(name) / "model3d" / "o2.glb").write_bytes(b"o2")
    (cimg / "hand2.png").write_bytes(b"hand2")
    return ""


npc_assets.render_mesh = fake_mesh_o
_, arts_o2 = wdm.PRODUCERS["mesh"](ctx, "character", "Demo C", mesh_step())
o2_glb = rel(get_character_dir("Demo C") / "model3d" / "o2.glb")
check("(o) mesh: only its own glb", [(a["type"], a["path"]) for a in arts_o2] == [("file", o2_glb)], arts_o2)
removed, kept = removal(arts_o + arts_o2, "(o)")
check("(o) own glbs removed", sorted(removed) == sorted([o_glb, o2_glb]) and kept == [], (removed, kept))
check("(o) the hand images stay", (cimg / "hand.png").read_bytes() == b"hand"
      and (cimg / "hand2.png").read_bytes() == b"hand2")
check("(o) profile_image untouched", (get_character_profile("Demo C") or {}).get("profile_image") == "hand.png",
      (get_character_profile("Demo C") or {}).get("profile_image"))

# ── (p) sidecar backups across steps ─────────────────────────────────────
print("(p) sidecar backups across steps")
side = b3d / "side.json"
side.write_text('{"s": 0}', encoding="utf-8")


def write_side(text):
    def fake(name):
        side.write_text(text, encoding="utf-8")
        return ""
    return fake


ctx_p = wdm.ProduceCtx(run_id=run, row_id=7)
npc_assets.render_mesh = write_side('{"s": 1}')
_, p1 = wdm.PRODUCERS["mesh"](ctx_p, "character", "Demo B", mesh_step())
npc_assets.render_mesh = write_side('{"s": 2}')
_, p2 = wdm.PRODUCERS["mesh"](ctx_p, "character", "Demo B", mesh_step())
sidep = rel(side)
check("(p) both steps say sidecar", [(a["type"], a["path"]) for a in p1 + p2]
      == [("sidecar", sidep), ("sidecar", sidep)], p1 + p2)
b1, b2 = STORAGE / p1[0]["backup"], STORAGE / p2[0]["backup"]
check("(p) distinct backup files", b1 != b2 and b1.is_file() and b2.is_file(), (b1, b2))
check("(p) step 1's backup still holds the pre-run bytes", b1.read_bytes() == b'{"s": 0}')
merged_p = wdm.merge_artefacts(p1, p2)
check("(p) merged: first backup, newest sha", merged_p == [{
    "type": "sidecar", "path": sidep, "backup": p1[0]["backup"],
    "sha256": hashlib.sha256(b'{"s": 2}').hexdigest(),
    "size": len(b'{"s": 2}'), "mtime_ns": stat_of(side)[1]}], merged_p)
check("(p) step 2's backup unlinked", not b2.exists() and b1.is_file())
removed, kept = removal(merged_p, "(p)")
check("(p) restored to the pre-run bytes", removed == [sidep] and side.read_bytes() == b'{"s": 0}',
      (removed, kept, side.read_bytes()))
check("(p) the used backup is gone", not b1.exists())

print()
if failures:
    print(f"FAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK — media capture and removal")
