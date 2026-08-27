#!/usr/bin/env python3
"""Smoke check for the improvement types `model_replace`, `fill_missing`,
`image_rerender` (plan-improvements-queue, tasks 3 + 4) and `surface_bake`
(spec-surface-height § 5 no. 3).

Every expectation below is derived BY HAND from the task contract and from the
generator anchors it builds on — nothing here records what a run happened to
produce.

The world is a throwaway storage dir. The two BLOCKING generators are replaced
by fakes that persist exactly what the real ones persist (a mesh file plus its
sidecar carrying `backend`), so the READERS stay real: `get_model3d_info` and
`props.list_models` are the production functions, and every "is the asset there
/ which backend made it" assertion goes through them.

  1. The parameter contract is the base class's.  All three types are
     registered by importing the package.  `model_replace` declares
     three required fields (subject, source_backend, target_backend), so a
     complete set validates to itself and a set without `target_backend`
     raises ValueError naming that field.  `subject` carries options, so
     "character" passes the membership check.

  2. A candidate is a subject whose CURRENT model was made by
     `source_backend`.  With no model at all there is no candidate.  After
     demo_a's sidecar records backend "hy", scanning for source "hy" yields
     exactly one candidate, key "character:demo_a" (the `<kind>:<ident>`
     format) and label "demo_a"; scanning for source "tr" yields none —
     nothing was made by "tr" yet.

  3. `apply` is the generation, synchronously.  It must call the mesh
     producer with `backend_glob` = the TARGET backend ("tr"), and once that
     producer has persisted its sidecar, `is_done` — which re-reads the
     sidecar through `get_model3d_info` — must be True.

  4. The producer NEVER raises; it answers {"ok": False, "error": …}.  A
     truthful `apply` therefore has to turn that into an exception, or the
     engine would count a failure as a finished step:
     {"ok": False, "error": "no_tpose_input"} → RuntimeError("no_tpose_input").

  5. A subject already being generated elsewhere is BUSY, not broken.  With
     "demo_b" inside `model3d._generating`, `apply` raises `CandidateBusy`
     (the engine leaves the step pending, no attempt counted) and the
     producer is not called at all — call count stays where it was.

  6. `fill_missing` asks the opposite question: subjects WITHOUT the asset.
     demo_a has a mesh (case 3) and the temporary NPC is not a subject at all
     (case 7), so demo_b is the only candidate.  Its `apply` has no backend
     parameter — it must use the admin default, which the patched backend
     inventory reports as "tr".  Afterwards demo_b has a model, so the
     candidate list is empty.

  7. `subjects.characters()` is the ROSTER minus the temporary NPCs: demo_a
     and demo_b are in it, the character whose template is `npc-temporary`
     is not (`is_temporary_npc` reads the template feature).

  8. A prop can only be re-meshed from a source image it HAS.  A prop
     without `source.png` is therefore not a `fill_missing prop_model`
     candidate at all; after the file appears it is, and `apply` calls
     `props._generate` with `mesh_only=True` (re-mesh the existing product
     shot, never burn a new image render) and `mesh_backend_glob` = the
     admin default "tr".

  9. Replacing a backend BY ITSELF is not an improvement, it is a treadmill:
     every candidate would already be `is_done`, the engine would apply
     anyway and a standing entry would regenerate the same models forever.
     `validate` refuses source == target, and `find_candidates` drops any
     subject that is already done — the contract says it returns only the
     unfinished ones, whatever an already-stored parameter set says.

 10. `_generate` does NOT take its module's in-flight slot — only the
     `trigger_*` wrappers do — so calling it directly has to hold the slot,
     or a parallel admin run meshes the same subject twice.  Pre-holding the
     prop's own job key (`props._gen_key(pid, None, "tr")`, the very key
     `props.trigger_generation` uses) makes `apply` raise `CandidateBusy`
     without calling the producer; after a successful apply the key is gone
     again, so a second apply runs instead of reporting busy.

 11. `building_source_image` resolves in three steps, and all three are
     reachable: (d) a location with no building-typed gallery image at all
     answers "" — such a location is not a `fill_missing building_model`
     candidate, because there would be nothing to generate FROM; (a) with two
     building-typed images and no model it answers the NEWEST of them
     ("new.png", mtime-ordered — "map.png" is typed `map_2d` and never
     counts); (b) once a model exists whose sidecar names an EXISTING gallery
     file, that file wins ("old.png" — a regeneration re-meshes the picture
     the model was made from); (c) a sidecar naming a file that is gone falls
     back to (a) again.

 12. The building handler runs end to end: with a source image and no model
     the location is the only candidate, `apply` calls
     `location_model3d._generate` with ("new.png", "tr"), the stored sidecar
     then names backend "tr" — so the location drops out of `fill_missing`
     and becomes a `model_replace` candidate for source "tr".  Its slot is
     claimed for the duration: a pre-claimed job makes `apply` busy without
     calling the producer, and after a successful apply `is_pending` is False.

 13. The expression handler asks the NPC gate's question.  With
     `peek_cached_expression` answering None both characters are candidates;
     with it answering a path, neither is.  `generate_expression_image` does
     not register in the module's in-flight set, so the busy question goes to
     `expression_regen.is_generating` — True makes `apply` raise
     `CandidateBusy` without rendering.

 14. `image_rerender character_images` works on the PROFILE image: a
     character whose profile image's meta names backend "flux" is a candidate
     for source "flux" and for no other source.  A portrait without a stored
     prompt is not a candidate at all — there would be nothing to render it
     from (the same rule as the missing source image in case 8).

 15. Its `apply` re-renders that profile image with `backend_name` = the
     TARGET backend, `create_new=True` (decision E5: the old portrait stays
     in the gallery) and `use_room=False` (a portrait is not a scene).  The
     new file becomes the profile — `get_character_profile_image` says so —
     and the expression cache is cleared, because every cached variant was
     derived from the old portrait.  `is_done` then reads the NEW profile
     image's meta backend and answers True.

 16. `regenerate_image` reports its failures in the return value
     (`(False, "", "")`) instead of raising, so `apply` has to turn that into
     an exception: RuntimeError("profile regenerate failed").

 17. `location_gallery` candidates are single gallery FILES, keyed
     `location:<id>:<file>`: a gallery image whose meta names the source
     backend AND that has a stored prompt is a candidate; the image without a
     prompt is not, and neither is anything under a source backend nothing
     was made by.  A picture that was DELETED is not a candidate either —
     `delete_gallery_image` keeps both the meta and the stored prompt, so only
     the file's existence tells the two apart.

 18. The stored gallery prompt IS the finished prompt: the core saves the fully
     composed one (`save_gallery_prompt(loc_id, image_name, full_prompt)`), so
     handing it back without `settings_applied` would compose it a second time
     and store a prompt that grows with every pass.  `apply` therefore sends
     `settings_applied: True`, and the image's `prompt_type` with it (an
     untyped re-render of a map tile would be flagged as a room background).

 19. A gallery re-render is a NEW file, so "done" cannot be a property of the
     candidate file: after `apply` the new image carries `backend` = the target
     AND `source_file` = the candidate — the meta the core wrote survives, the
     source is only merged in — and `is_done` answers True through that pair,
     so the candidate disappears from the list.  The background flag follows
     the picture: the core flags the new file, the old one is unflagged, or the
     location would keep showing the image that was just superseded.

 20. The core reports a saturated/unavailable backend as `HTTPException(503)`,
     not as a return value.  Letting that through would count an attempt and
     skip the step for good after two of them, so `apply` translates it into
     `CandidateBusy`.

 21. `surface_bake room_model` works on LAID-OUT rooms that have a model: a
     room whose floor plan is missing is placed in no scene, so its diorama's
     lattice would never be read and it is no subject at all — the same rule
     that keeps a prop without its product shot out of `fill_missing`.  The
     candidate is keyed `room:<location>/<room>` and labelled
     "<location> / <room>".

 22. Candidacy is `read_surface is None`, and validity is part of that
     (spec § 4): after `apply` has baked, the room drops out and `is_done`
     answers True; turning the orientation dial afterwards makes the stored
     lattice read as stale — the very same "no surface" — and the room is a
     candidate again.  `apply` waits the landing paths' 300 s for a Blender
     slot and bakes with the sidecar's fix.

 23. `bake_surface` NEVER raises: it answers None for a missing Blender, for a
     slot that never came free and for a failed script alike.  The engine
     records a failure only from an exception, so `apply` has to raise, or the
     step would be closed as finished and the model would stay without a
     floor.

 24. A bake invalidates the walk gate's cached lattices.  A room knows its
     location and drops only that one; a prop stands in many locations and
     does not know in which, so its cache goes wholesale (`forget_surfaces()`
     with no argument) — the same rule `props.bake_surfaces` follows.

 25. `surface_bake prop_model` works per ACTIVE VARIANT, keyed
     `prop:<id>/<index>` on the STORE index: the prop with one variant is one
     candidate labelled by its plain name, and a second active variant adds a
     second candidate labelled "(variant 1)".

The printed sections follow execution order, so expectations 9 and 10 are
checked inside the sections whose fixtures they belong to.

Usage:  ./.venv/bin/python scripts/smoke_improvement_types.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="improvtypes-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="improvtypes-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from fastapi import HTTPException  # noqa: E402

from app.core import (expression_regen, location_model3d, model3d,  # noqa: E402
                      model_refs, model_surface, props, world_ops)
from app.core.improvements import registry  # noqa: E402
from app.core.improvements.base import CandidateBusy  # noqa: E402
from app.core.improvements.types import subjects  # noqa: E402
from app.core.model_store import write_sidecar  # noqa: E402
from app.core.timeutils import utc_now_iso  # noqa: E402
from app.models import world  # noqa: E402
from app.models.character import (add_character_image_metadata,  # noqa: E402
                                  add_character_image_prompt,
                                  get_character_dir,
                                  get_character_images_dir,
                                  get_character_profile_image,
                                  save_character_profile,
                                  set_character_profile_image)
from app.skills import image_regenerate  # noqa: E402

import app.core.improvements.types  # noqa: E402,F401  (registers the types)

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_raises(label, exc_type, fn, message=None):
    global CHECKED
    CHECKED += 1
    try:
        fn()
    except exc_type as e:
        ok = message is None or str(e) == message
        print(f"  {'OK ' if ok else 'FAIL'} {label}: {exc_type.__name__}({str(e)!r})"
              + ("" if ok else f" — expected message {message!r}"))
        if not ok:
            FAILURES.append(label)
        return
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL {label}: raised {type(e).__name__}({e!r})"
              f" — expected {exc_type.__name__}")
        FAILURES.append(label)
        return
    print(f"  FAIL {label}: nothing raised — expected {exc_type.__name__}")
    FAILURES.append(label)


# ── fixtures ────────────────────────────────────────────────────────────────

def make_character(name, template=""):
    profile = {"name": name, "appearance": "a weathered farmhand"}
    if template:
        profile["template"] = template
    save_character_profile(name, profile, create_new=True)
    return name


def write_mesh_sidecar(name, backend):
    """What the real mesh producer leaves behind: the model file plus its
    sidecar (`model3d.get_model3d_info` reads `backend` from there)."""
    sig = model_refs.current_outfit_state(name)[2]
    d = get_character_dir(name) / "model3d"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sig}.glb").write_bytes(b"glTF fake")
    (d / f"{sig}.json").write_text(json.dumps({
        "created_at": utc_now_iso(), "source": "generated",
        "backend": backend, "rig": "mixamo"}), encoding="utf-8")


# ── the producer fakes ──────────────────────────────────────────────────────

MESH_CALLS = []
MESH_RESULT = {"value": None}       # None = persist and succeed
PROP_CALLS = []
BUILDING_CALLS = []
EXPRESSION_CALLS = []
EXPRESSION_CACHED = {"value": None}   # what peek_cached_expression answers


def fake_mesh(character_name, *, force=False, backend_glob="", **kwargs):
    MESH_CALLS.append({"name": character_name, "force": force,
                       "backend_glob": backend_glob})
    if MESH_RESULT["value"] is not None:
        return MESH_RESULT["value"]
    write_mesh_sidecar(character_name, backend_glob)
    return {"ok": True}


def fake_prop_generate(prop_id, prompt, negative, image_backend_glob,
                       mesh_backend_glob, **kwargs):
    PROP_CALLS.append({"prop_id": prop_id,
                       "mesh_backend_glob": mesh_backend_glob,
                       "mesh_only": bool(kwargs.get("mesh_only"))})
    gallery = props.model_gallery(prop_id)
    path = gallery.new_path()
    path.write_bytes(b"glTF fake")
    props.write_model_sidecar(path, {
        "created_at": utc_now_iso(), "source": "generated", "format": "glb",
        "rig": "none", "tier": props.DEFAULT_TIER,
        "backend": mesh_backend_glob})
    gallery.select(path.name, props.DEFAULT_TIER)
    return {"ok": True}


def fake_building_generate(location_id, source_image, backend_glob,
                           room_id="", **kwargs):
    BUILDING_CALLS.append({"location_id": location_id,
                           "source_image": source_image,
                           "backend_glob": backend_glob})
    owner = location_model3d._owner_id(location_id)
    gallery = location_model3d._gallery(owner, room_id)
    path = gallery.new_path()
    path.write_bytes(b"glTF fake")
    write_sidecar(path, {"created_at": utc_now_iso(), "source": "generated",
                         "format": "glb", "rig": "none",
                         "tier": location_model3d.DEFAULT_TIER,
                         "backend": backend_glob,
                         "source_image": source_image})
    gallery.select(path.name, location_model3d.DEFAULT_TIER)
    return {"ok": True}


REGEN_CALLS = []
REGEN_OK = {"value": True}          # False = the producer reports a failure


def fake_regenerate_image(character_name, output_path, original_prompt,
                          improvement_request="", workflow_name="",
                          backend_name="", **kwargs):
    """What `image_regenerate.regenerate_image` does to the WORLD on a
    `create_new` run: it writes a new file next to the old one and records the
    backend that made it in that file's image meta (`_regen_meta["backend"]`).
    The readers stay real — `get_character_image_metadata` answers from here."""
    REGEN_CALLS.append({"name": character_name,
                        "output_path": Path(output_path).name,
                        "prompt": original_prompt,
                        "backend_name": backend_name,
                        "create_new": bool(kwargs.get("create_new")),
                        "use_room": bool(kwargs.get("use_room"))})
    if not REGEN_OK["value"]:
        return (False, "", "")
    new_name = Path(output_path).stem + "_v1" + Path(output_path).suffix
    new_path = Path(output_path).parent / new_name
    new_path.write_bytes(b"\x89PNG fake")
    add_character_image_metadata(character_name, new_name,
                                 {"backend": backend_name})
    add_character_image_prompt(character_name, new_name, original_prompt)
    return (True, original_prompt, str(new_path))


GALLERY_CALLS = []
GALLERY_BUSY = {"value": False}     # True = the backend reports load (503)
GALLERY_SEQ = {"n": 0}


async def fake_gallery_generate(location_name, data):
    """What `generate_gallery_image_core` does to the WORLD: it writes a NEW
    gallery file, stores that file's prompt and its generation meta (backend,
    backend_type, model, LoRAs), flags an untyped image as a background — and
    reports the new file name under "image".  Failures never come back as a
    return value; the core raises, and load raises an HTTPException(503)."""
    GALLERY_CALLS.append(dict(data))
    if GALLERY_BUSY["value"]:
        raise HTTPException(status_code=503, detail="zimg ist ausgelastet")
    GALLERY_SEQ["n"] += 1
    new_name = f"{2000 + GALLERY_SEQ['n']}.png"
    (world.get_gallery_dir(location_name) / new_name).write_bytes(b"\x89PNG fake")
    world.save_gallery_prompt(location_name, new_name, data["prompt"])
    world.set_gallery_image_meta(location_name, new_name, {
        "backend": data["backend"], "backend_type": "http", "model": "",
        "loras": []})
    if data.get("prompt_type") not in ("map_2d", "building"):
        world.toggle_background_image(location_name, new_name)
    return {"status": "success", "location": location_name,
            "location_id": location_name, "image": new_name, "warnings": []}


EXPR_CLEARED = []


def fake_clear_expression_cache(character_name):
    EXPR_CLEARED.append(character_name)
    return 0


def fake_peek_expression(name, mood, pose_key, **kwargs):
    return EXPRESSION_CACHED["value"]


def fake_expression_image(name, mood, pose_key, **kwargs):
    EXPRESSION_CALLS.append(name)
    return Path("/tmp/fake-expression.png")


model3d.generate_for_current_outfit = fake_mesh
props._generate = fake_prop_generate
location_model3d._generate = fake_building_generate
expression_regen.peek_cached_expression = fake_peek_expression
expression_regen.generate_expression_image = fake_expression_image
expression_regen.clear_expression_cache = fake_clear_expression_cache
image_regenerate.regenerate_image = fake_regenerate_image
world_ops.generate_gallery_image_core = fake_gallery_generate
# The backend INVENTORY, not an asset reader: without configured mesh
# backends `list_mesh_backends` answers {"backends": [], "default": ""} and
# every "which backend is the default" expectation would be vacuous.
model3d.list_mesh_backends = lambda rig="": {
    "backends": [{"name": "hy"}, {"name": "tr"}], "default": "tr"}

BAKE_CALLS = []
BAKE_FAILS = {"value": False}      # True = Blender missing / no slot / script failed
FORGET_CALLS = []


def fake_bake_surface(model_path, rotation, *, wait_s=0.0):
    """What `model_surface.bake_surface` leaves behind on success: the lattice
    file next to the model, naming the format version, the FILE it was baked
    from and the FIX it was baked under. `read_surface` stays the real one, so
    every "is there a surface" answer below goes through the production
    validity check."""
    BAKE_CALLS.append({"model": Path(model_path).name,
                       "rotation": model_surface._norm_rotation(rotation),
                       "wait_s": wait_s})
    if BAKE_FAILS["value"]:
        return None
    surface = {"version": model_surface.SURFACE_VERSION,
               "source": model_surface._source_of(Path(model_path)),
               "rotation": model_surface._norm_rotation(rotation),
               "baked_at": utc_now_iso(), "blender": "fake", "hits": 1,
               "step": model_surface.SURFACE_STEP_M, "origin": [0.0, 0.0],
               "cols": 1, "rows": 1, "values": [0.0],
               "box_min": [0.0, 0.0, 0.0], "box_max": [1.0, 1.0, 1.0],
               "extent_snapped": [1.0, 1.0, 1.0]}
    model_surface.surface_path(Path(model_path)).write_text(
        json.dumps(surface), encoding="utf-8")
    return surface


def fake_forget_surfaces(location_id=""):
    FORGET_CALLS.append(location_id)


model_surface.bake_surface = fake_bake_surface
model_surface.forget_surfaces = fake_forget_surfaces

MODEL_REPLACE = registry.get("model_replace")
FILL_MISSING = registry.get("fill_missing")
IMAGE_RERENDER = registry.get("image_rerender")
SURFACE_BAKE = registry.get("surface_bake")

A = make_character("demo_a")
B = make_character("demo_b")
TEMP = make_character("demo_temp", template="npc-temporary")


def candidates(improvement_type, params):
    return [(c.key, c.label)
            for c in improvement_type.find_candidates(improvement_type.validate(params))]


# ── [1] the parameter contract ──────────────────────────────────────────────
print("[1] model_replace parameters")
check("all four types are registered",
      sorted(t.id for t in registry.list_types()),
      ["fill_missing", "image_rerender", "model_replace", "surface_bake"])
check("a complete set validates to itself",
      MODEL_REPLACE.validate({"subject": "character", "source_backend": "hy",
                              "target_backend": "tr"}),
      {"subject": "character", "source_backend": "hy", "target_backend": "tr"})
check_raises("a missing target backend is refused", ValueError,
             lambda: MODEL_REPLACE.validate({"subject": "character",
                                             "source_backend": "hy"}),
             "missing parameter 'target_backend'")
check_raises("replacing a backend by itself is refused", ValueError,
             lambda: MODEL_REPLACE.validate({"subject": "character",
                                             "source_backend": "hy",
                                             "target_backend": "hy"}),
             "source and target backend must differ")

# ── [2] candidates are keyed on the CURRENT backend ─────────────────────────
print("[2] model_replace candidates")
REPLACE_HY = {"subject": "character", "source_backend": "hy",
              "target_backend": "tr"}
check("without any model nothing is a candidate",
      candidates(MODEL_REPLACE, REPLACE_HY), [])
write_mesh_sidecar(A, "hy")
check("a model made by 'hy' is one candidate, keyed character:<name>",
      candidates(MODEL_REPLACE, REPLACE_HY), [("character:demo_a", "demo_a")])
check("scanning for a backend nothing was made by finds nothing",
      candidates(MODEL_REPLACE, {"subject": "character",
                                 "source_backend": "tr",
                                 "target_backend": "hy"}), [])
check("a STORED equal-backend set yields no work either (is_done filter)",
      [(c.key, c.label) for c in MODEL_REPLACE.find_candidates(
          {"subject": "character", "source_backend": "hy",
           "target_backend": "hy"})], [])

# ── [3] apply generates with the TARGET backend ─────────────────────────────
print("[3] model_replace apply")
MESH_CALLS.clear()
CAND_A = MODEL_REPLACE.find_candidates(MODEL_REPLACE.validate(REPLACE_HY))[0]
MODEL_REPLACE.apply(CAND_A, MODEL_REPLACE.validate(REPLACE_HY), "task-1")
check("the producer ran once, forced, with the target backend", MESH_CALLS,
      [{"name": "demo_a", "force": True, "backend_glob": "tr"}])
check("is_done reads the fresh sidecar back",
      MODEL_REPLACE.is_done(CAND_A, MODEL_REPLACE.validate(REPLACE_HY)), True)
check("and the subject has dropped out of the candidate list",
      candidates(MODEL_REPLACE, REPLACE_HY), [])

# ── [4] a failing producer must raise ───────────────────────────────────────
print("[4] a producer failure is an exception, not a finished step")
MESH_CALLS.clear()
MESH_RESULT["value"] = {"ok": False, "error": "no_tpose_input"}
check_raises("the error string becomes the RuntimeError", RuntimeError,
             lambda: MODEL_REPLACE.apply(CAND_A,
                                         MODEL_REPLACE.validate(REPLACE_HY),
                                         "task-2"),
             "no_tpose_input")
MESH_RESULT["value"] = None

# ── [5] a subject generated elsewhere is busy ───────────────────────────────
print("[5] the double-start guard is a CandidateBusy")
MESH_CALLS.clear()
with model3d._lock:
    model3d._generating.add("demo_b")
BUSY = type(CAND_A)("character:demo_b", "demo_b")
check_raises("apply refuses while another run holds the subject", CandidateBusy,
             lambda: MODEL_REPLACE.apply(BUSY,
                                         MODEL_REPLACE.validate(REPLACE_HY),
                                         "task-3"))
check("the producer was never called", MESH_CALLS, [])
check("subjects.character_model_pending sees the same guard",
      subjects.character_model_pending("demo_b"), True)
with model3d._lock:
    model3d._generating.discard("demo_b")
check("and the guard is released again",
      subjects.character_model_pending("demo_b"), False)

# ── [6] fill_missing over character models ──────────────────────────────────
print("[6] fill_missing character_model")
FILL_CHAR = {"subject": "character_model"}
check("the admin default is what the inventory reports",
      subjects.default_mesh_backend(), "tr")
check("only the character without a mesh is a candidate",
      candidates(FILL_MISSING, FILL_CHAR), [("character:demo_b", "demo_b")])
MESH_CALLS.clear()
CAND_B = FILL_MISSING.find_candidates(FILL_MISSING.validate(FILL_CHAR))[0]
FILL_MISSING.apply(CAND_B, FILL_MISSING.validate(FILL_CHAR), "task-4")
check("apply generates with the admin default backend", MESH_CALLS,
      [{"name": "demo_b", "force": True, "backend_glob": "tr"}])
check("is_done is simply 'the asset exists now'",
      FILL_MISSING.is_done(CAND_B, FILL_MISSING.validate(FILL_CHAR)), True)
check("nothing is missing any more", candidates(FILL_MISSING, FILL_CHAR), [])

# ── [7] the roster excludes temporary NPCs ──────────────────────────────────
print("[7] subjects.characters()")
check("demo_a and demo_b are subjects, the temporary NPC is not",
      subjects.characters(), ["demo_a", "demo_b"])

# ── [8] props need a source image before they can be meshed ─────────────────
print("[8] fill_missing prop_model")
FILL_PROP = {"subject": "prop_model"}
PROP = props.create_prop(name="Oak Chair")["id"]
check("a prop without source.png is NOT a candidate",
      candidates(FILL_MISSING, FILL_PROP), [])
check("subjects.prop_has_source agrees", subjects.prop_has_source(PROP), False)
(props.prop_dir(PROP, create=True) / props.SOURCE_NAME).write_bytes(b"\x89PNG fake")
check("with the product shot on disk it becomes a candidate",
      candidates(FILL_MISSING, FILL_PROP), [(f"prop:{PROP}", "Oak Chair")])
PROP_CALLS.clear()
CAND_P = FILL_MISSING.find_candidates(FILL_MISSING.validate(FILL_PROP))[0]
PROP_KEY = props._gen_key(PROP, None, "tr")
with props._lock:
    props._generating.add(PROP_KEY)
check_raises("a held job key makes apply busy", CandidateBusy,
             lambda: FILL_MISSING.apply(CAND_P,
                                        FILL_MISSING.validate(FILL_PROP),
                                        "task-5"))
check("the producer was never called", PROP_CALLS, [])
with props._lock:
    props._generating.discard(PROP_KEY)
FILL_MISSING.apply(CAND_P, FILL_MISSING.validate(FILL_PROP), "task-6")
check("apply re-meshes the existing image with the default backend", PROP_CALLS,
      [{"prop_id": PROP, "mesh_backend_glob": "tr", "mesh_only": True}])
check("the job slot is released again", props._generating, set())
check("the stored mesh records the backend that made it",
      (subjects.prop_model(PROP) or {}).get("backend"), "tr")
check("and the prop is no longer missing a model",
      candidates(FILL_MISSING, FILL_PROP), [])

# ── [9] building_source_image resolves in three steps ───────────────────────
print("[9] subjects.building_source_image")
LOC_ID = world.add_location("Crossroads Inn", "A stone house at the fork.")["id"]
BARE_ID = world.add_location("Empty Field", "Grass, nothing else.")["id"]
GALLERY = world.get_gallery_dir(LOC_ID)
GALLERY.mkdir(parents=True, exist_ok=True)
for _name in ("old.png", "new.png", "map.png"):
    (GALLERY / _name).write_bytes(b"\x89PNG fake")
# Deterministic age instead of write order: old.png is a minute older.
_NOW = (GALLERY / "new.png").stat().st_mtime
os.utime(GALLERY / "old.png", (_NOW - 60, _NOW - 60))
check("(d) no building-typed image at all → no source",
      subjects.building_source_image(LOC_ID), "")
world.set_gallery_image_type(LOC_ID, "old.png", "building")
world.set_gallery_image_type(LOC_ID, "new.png", "building")
world.set_gallery_image_type(LOC_ID, "map.png", "map_2d")
check("(a) without a model the NEWEST building-typed image wins",
      subjects.building_source_image(LOC_ID), "new.png")
check("(d) a location without any gallery image has none either",
      subjects.building_source_image(BARE_ID), "")
check("and neither location has a building model yet",
      [subjects.building_model(LOC_ID), subjects.building_model(BARE_ID)],
      [None, None])

# ── [10] the building handler, end to end ───────────────────────────────────
print("[10] fill_missing building_model")
FILL_BUILDING = {"subject": "building_model"}
check("only the location with a source image is a candidate",
      candidates(FILL_MISSING, FILL_BUILDING),
      [(f"location:{LOC_ID}", "Crossroads Inn")])
CAND_L = FILL_MISSING.find_candidates(FILL_MISSING.validate(FILL_BUILDING))[0]
check("the job slot can be claimed", location_model3d.claim_job(
    LOC_ID, kind=subjects._BUILDING_JOB_KIND), True)
check_raises("a claimed slot makes apply busy", CandidateBusy,
             lambda: FILL_MISSING.apply(CAND_L,
                                        FILL_MISSING.validate(FILL_BUILDING),
                                        "task-7"))
check("the producer was never called", BUILDING_CALLS, [])
location_model3d.release_job(LOC_ID, kind=subjects._BUILDING_JOB_KIND)
FILL_MISSING.apply(CAND_L, FILL_MISSING.validate(FILL_BUILDING), "task-8")
check("apply meshes the newest building image with the default backend",
      BUILDING_CALLS, [{"location_id": LOC_ID, "source_image": "new.png",
                        "backend_glob": "tr"}])
check("the slot is released again", location_model3d.is_pending(LOC_ID), False)
check("the stored sidecar names the backend that made it",
      (subjects.building_model(LOC_ID) or {}).get("backend"), "tr")
check("nothing is missing any more", candidates(FILL_MISSING, FILL_BUILDING), [])
check("and the location is now a model_replace candidate for 'tr'",
      candidates(MODEL_REPLACE, {"subject": "location", "source_backend": "tr",
                                 "target_backend": "hy"}),
      [(f"location:{LOC_ID}", "Crossroads Inn")])
MODEL_PATH = location_model3d.find_building_model(LOC_ID)
SIDECAR = json.loads(MODEL_PATH.with_suffix(".json").read_text(encoding="utf-8"))
SIDECAR["source_image"] = "old.png"
MODEL_PATH.with_suffix(".json").write_text(json.dumps(SIDECAR), encoding="utf-8")
check("(b) the active model's own source image wins over the newest",
      subjects.building_source_image(LOC_ID), "old.png")
SIDECAR["source_image"] = "gone.png"
MODEL_PATH.with_suffix(".json").write_text(json.dumps(SIDECAR), encoding="utf-8")
check("(c) a source image that is gone falls back to the newest",
      subjects.building_source_image(LOC_ID), "new.png")

# ── [11] the expression handler ─────────────────────────────────────────────
print("[11] fill_missing character_expressions")
FILL_EXPR = {"subject": "character_expressions"}
EXPRESSION_CACHED["value"] = None
check("no cached variant → every character is a candidate",
      candidates(FILL_MISSING, FILL_EXPR),
      [("character:demo_a", "demo_a"), ("character:demo_b", "demo_b")])
CAND_E = FILL_MISSING.find_candidates(FILL_MISSING.validate(FILL_EXPR))[0]
expression_regen.is_generating = lambda *a, **kw: True
check_raises("a render already running makes apply busy", CandidateBusy,
             lambda: FILL_MISSING.apply(CAND_E,
                                        FILL_MISSING.validate(FILL_EXPR),
                                        "task-9"))
check("the renderer was never called", EXPRESSION_CALLS, [])
expression_regen.is_generating = lambda *a, **kw: False
FILL_MISSING.apply(CAND_E, FILL_MISSING.validate(FILL_EXPR), "task-10")
check("otherwise the renderer runs for that character", EXPRESSION_CALLS,
      ["demo_a"])
EXPRESSION_CACHED["value"] = Path("/tmp/fake-expression.png")
check("a cached variant → nobody is a candidate",
      candidates(FILL_MISSING, FILL_EXPR), [])
check("and is_done says so", FILL_MISSING.is_done(
    CAND_E, FILL_MISSING.validate(FILL_EXPR)), True)

# ── [12] image_rerender over character portraits ────────────────────────────
print("[12] image_rerender character_images")
RERENDER = {"subject": "character_images", "source_backend": "flux",
            "target_backend": "zimg"}
check_raises("re-rendering into the same backend is refused", ValueError,
             lambda: IMAGE_RERENDER.validate({"subject": "character_images",
                                              "source_backend": "flux",
                                              "target_backend": "flux"}),
             "source and target backend must differ")
PORTRAIT_DIR = get_character_images_dir(A)
PORTRAIT_DIR.mkdir(parents=True, exist_ok=True)
(PORTRAIT_DIR / "portrait.png").write_bytes(b"\x89PNG fake")
add_character_image_metadata(A, "portrait.png", {"backend": "flux"})
set_character_profile_image(A, "portrait.png")
check("a portrait without a stored prompt is NOT a candidate",
      candidates(IMAGE_RERENDER, RERENDER), [])
add_character_image_prompt(A, "portrait.png", "a weathered farmhand, portrait")
check("with a prompt the 'flux' portrait is one candidate",
      candidates(IMAGE_RERENDER, RERENDER), [("character:demo_a", "demo_a")])
check("scanning for a backend nothing was made by finds nothing",
      candidates(IMAGE_RERENDER, {"subject": "character_images",
                                  "source_backend": "sdxl",
                                  "target_backend": "zimg"}), [])
REGEN_CALLS.clear()
EXPR_CLEARED.clear()
CAND_I = IMAGE_RERENDER.find_candidates(IMAGE_RERENDER.validate(RERENDER))[0]
IMAGE_RERENDER.apply(CAND_I, IMAGE_RERENDER.validate(RERENDER), "task-11")
check("apply re-renders the profile image on the TARGET backend, as a new "
      "file, without the room reference", REGEN_CALLS,
      [{"name": "demo_a", "output_path": "portrait.png",
        "prompt": "a weathered farmhand, portrait", "backend_name": "zimg",
        "create_new": True, "use_room": False}])
check("the new file is the profile image now",
      get_character_profile_image(A), "portrait_v1.png")
check("and the expression cache was dropped", EXPR_CLEARED, ["demo_a"])
check("is_done reads the new profile image's meta backend",
      IMAGE_RERENDER.is_done(CAND_I, IMAGE_RERENDER.validate(RERENDER)), True)
check("the character has dropped out of the candidate list",
      candidates(IMAGE_RERENDER, RERENDER), [])
REGEN_OK["value"] = False
check_raises("a producer failure becomes an exception", RuntimeError,
             lambda: IMAGE_RERENDER.apply(
                 type(CAND_I)("character:demo_a", "demo_a"),
                 IMAGE_RERENDER.validate({"subject": "character_images",
                                          "source_backend": "zimg",
                                          "target_backend": "flux"}),
                 "task-12"),
             "profile regenerate failed")
REGEN_OK["value"] = True

# ── [13] image_rerender over a location gallery ─────────────────────────────
print("[13] image_rerender location_gallery")
GALLERY_RERENDER = {"subject": "location_gallery", "source_backend": "flux",
                    "target_backend": "zimg"}
world.set_gallery_image_meta(LOC_ID, "old.png", {"backend": "flux"})
world.set_gallery_image_meta(LOC_ID, "new.png", {"backend": "flux"})
world.save_gallery_prompt(LOC_ID, "new.png", "a stone house at the fork")
check("only the image with a stored prompt can be re-rendered",
      [g["filename"] for g in subjects.gallery_images(LOC_ID)], ["new.png"])
check("it is one candidate, keyed location:<id>:<file>",
      candidates(IMAGE_RERENDER, GALLERY_RERENDER),
      [(f"location:{LOC_ID}:new.png", "Crossroads Inn / new.png")])
check("scanning for a backend nothing was made by finds nothing",
      candidates(IMAGE_RERENDER, {"subject": "location_gallery",
                                  "source_backend": "zimg",
                                  "target_backend": "flux"}), [])

# A second location whose image is untyped (so the core flags it as a
# background) — plus a picture that was DELETED while its meta and prompt
# stayed behind, which is what delete_gallery_image leaves.
MILL_ID = world.add_location("Riverside Mill", "A mill by the river.")["id"]
MILL_GALLERY = world.get_gallery_dir(MILL_ID)
MILL_GALLERY.mkdir(parents=True, exist_ok=True)
(MILL_GALLERY / "shot.png").write_bytes(b"\x89PNG fake")
world.set_gallery_image_meta(MILL_ID, "shot.png", {"backend": "flux"})
world.save_gallery_prompt(MILL_ID, "shot.png", "a mill by the river, daylight")
world.toggle_background_image(MILL_ID, "shot.png")
world.set_gallery_image_meta(MILL_ID, "gone.png", {"backend": "flux"})
world.save_gallery_prompt(MILL_ID, "gone.png", "a mill by the river, at night")
check("a deleted picture is no subject, meta and prompt notwithstanding",
      [g["filename"] for g in subjects.gallery_images(MILL_ID)], ["shot.png"])
check("both locations' 'flux' images are candidates",
      candidates(IMAGE_RERENDER, GALLERY_RERENDER),
      [(f"location:{LOC_ID}:new.png", "Crossroads Inn / new.png"),
       (f"location:{MILL_ID}:shot.png", "Riverside Mill / shot.png")])
CAND_G = IMAGE_RERENDER.find_candidates(
    IMAGE_RERENDER.validate(GALLERY_RERENDER))[1]
GALLERY_CALLS.clear()
IMAGE_RERENDER.apply(CAND_G, IMAGE_RERENDER.validate(GALLERY_RERENDER),
                     "task-13")
check("apply renders the STORED (already composed) prompt on the target "
      "backend, with the image's type", GALLERY_CALLS,
      [{"prompt": "a mill by the river, daylight", "settings_applied": True,
        "room_id": "", "prompt_type": "", "backend": "zimg"}])
check("the new image names its source — and the core's own meta survives it",
      world.get_gallery_image_metas(MILL_ID).get("2001.png"),
      {"backend": "zimg", "backend_type": "http", "model": "", "loras": [],
       "source_file": "shot.png"})
check("the background flag moved to the new picture",
      world.get_background_images(MILL_ID), ["2001.png"])
check("is_done finds the replacement, not the candidate file",
      IMAGE_RERENDER.is_done(CAND_G, IMAGE_RERENDER.validate(GALLERY_RERENDER)),
      True)
check("so the re-rendered image has dropped out of the candidate list",
      candidates(IMAGE_RERENDER, GALLERY_RERENDER),
      [(f"location:{LOC_ID}:new.png", "Crossroads Inn / new.png")])
GALLERY_CALLS.clear()
GALLERY_BUSY["value"] = True
CAND_G2 = IMAGE_RERENDER.find_candidates(
    IMAGE_RERENDER.validate(GALLERY_RERENDER))[0]
check_raises("a 503 from the core is load, not a defect", CandidateBusy,
             lambda: IMAGE_RERENDER.apply(
                 CAND_G2, IMAGE_RERENDER.validate(GALLERY_RERENDER), "task-14"),
             "zimg ist ausgelastet")
check("and the candidate stayed exactly as it was",
      candidates(IMAGE_RERENDER, GALLERY_RERENDER),
      [(f"location:{LOC_ID}:new.png", "Crossroads Inn / new.png")])
GALLERY_BUSY["value"] = False

# ── [14] surface_bake over room models ──────────────────────────────────────
print("[14] surface_bake room_model")
BAKE_ROOM = {"subject": "room_model"}


def set_room_layout(location_id, room_id, layout):
    """Only the PRESENCE of a floor plan is the gate here, so a minimal one is
    stored directly rather than through the layout sanitizer."""
    data = world._load_world_data()
    for _loc in data.get("locations", []):
        if _loc.get("id") != location_id:
            continue
        for _room in _loc.get("rooms", []):
            if _room.get("id") == room_id:
                _room["layout"] = layout
    world._save_world_data(data)


TAPROOM = world.add_room(LOC_ID, "Taproom")["id"]
CELLAR = world.add_room(LOC_ID, "Cellar")["id"]
fake_building_generate(LOC_ID, "new.png", "tr", room_id=TAPROOM)
fake_building_generate(LOC_ID, "new.png", "tr", room_id=CELLAR)
check("both rooms have a model", [
    bool(location_model3d.find_building_model(LOC_ID, TAPROOM)),
    bool(location_model3d.find_building_model(LOC_ID, CELLAR))], [True, True])
set_room_layout(LOC_ID, TAPROOM, {"w": 6.0, "h": 4.0})
check("only the LAID-OUT room is a subject",
      candidates(SURFACE_BAKE, BAKE_ROOM),
      [(f"room:{LOC_ID}/{TAPROOM}", "Crossroads Inn / Taproom")])
BAKE_CALLS.clear()
FORGET_CALLS.clear()
CAND_R = SURFACE_BAKE.find_candidates(SURFACE_BAKE.validate(BAKE_ROOM))[0]
ROOM_MODEL = location_model3d.find_building_model(LOC_ID, TAPROOM)
SURFACE_BAKE.apply(CAND_R, SURFACE_BAKE.validate(BAKE_ROOM), "task-15")
check("apply bakes that model under its sidecar fix, waiting for a slot",
      BAKE_CALLS, [{"model": ROOM_MODEL.name,
                    "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "wait_s": 300.0}])
check("and drops the walk gate's cache for THIS location", FORGET_CALLS,
      [LOC_ID])
check("is_done reads the fresh lattice back",
      SURFACE_BAKE.is_done(CAND_R, SURFACE_BAKE.validate(BAKE_ROOM)), True)
check("so the room has dropped out of the candidate list",
      candidates(SURFACE_BAKE, BAKE_ROOM), [])
ROOM_META = location_model3d.read_sidecar(ROOM_MODEL)
ROOM_META["rotation"] = {"x": 0, "y": 90, "z": 0}
write_sidecar(ROOM_MODEL, ROOM_META)
check("turning the orientation dial makes the stored lattice stale — which "
      "reads as no surface, so the room is a candidate again",
      candidates(SURFACE_BAKE, BAKE_ROOM),
      [(f"room:{LOC_ID}/{TAPROOM}", "Crossroads Inn / Taproom")])
BAKE_CALLS.clear()
FORGET_CALLS.clear()
BAKE_FAILS["value"] = True
check_raises("a bake that answers None is an exception, not a finished step",
             RuntimeError,
             lambda: SURFACE_BAKE.apply(CAND_R, SURFACE_BAKE.validate(BAKE_ROOM),
                                        "task-16"),
             f"room:{LOC_ID}/{TAPROOM}: surface bake failed")
check("and nothing was invalidated", FORGET_CALLS, [])
BAKE_FAILS["value"] = False

# ── [15] surface_bake over prop variants ────────────────────────────────────
print("[15] surface_bake prop_model")
BAKE_PROP = {"subject": "prop_model"}
check("the prop's one variant is one candidate, keyed on the STORE index",
      candidates(SURFACE_BAKE, BAKE_PROP), [(f"prop:{PROP}/0", "Oak Chair")])
VARIANT = props.add_variant(PROP)
VAR_GALLERY = props.model_gallery(PROP, VARIANT)
VAR_MODEL = VAR_GALLERY.new_path()
VAR_MODEL.write_bytes(b"glTF fake")
props.write_model_sidecar(VAR_MODEL, {
    "created_at": utc_now_iso(), "source": "generated", "format": "glb",
    "rig": "none", "tier": props.DEFAULT_TIER, "backend": "tr"})
VAR_GALLERY.select(VAR_MODEL.name, props.DEFAULT_TIER)
check("a second active variant is a second candidate",
      candidates(SURFACE_BAKE, BAKE_PROP),
      [(f"prop:{PROP}/0", "Oak Chair"),
       (f"prop:{PROP}/1", "Oak Chair (variant 1)")])
BAKE_CALLS.clear()
FORGET_CALLS.clear()
CAND_V = SURFACE_BAKE.find_candidates(SURFACE_BAKE.validate(BAKE_PROP))[1]
SURFACE_BAKE.apply(CAND_V, SURFACE_BAKE.validate(BAKE_PROP), "task-17")
check("apply bakes that VARIANT's mesh", BAKE_CALLS,
      [{"model": VAR_MODEL.name, "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
        "wait_s": 300.0}])
check("a prop does not know where it stands, so the whole cache goes",
      FORGET_CALLS, [""])
check("only the other variant is left to bake",
      candidates(SURFACE_BAKE, BAKE_PROP), [(f"prop:{PROP}/0", "Oak Chair")])

print()
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}: " + ", ".join(FAILURES))
    sys.exit(1)
print(f"All {CHECKED} checks OK")
