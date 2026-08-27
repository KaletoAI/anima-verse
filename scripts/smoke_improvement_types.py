#!/usr/bin/env python3
"""Smoke check for the improvement types `model_replace` + `fill_missing`
(plan-improvements-queue, task 3).

Every expectation below is derived BY HAND from the task contract and from the
generator anchors it builds on — nothing here records what a run happened to
produce.

The world is a throwaway storage dir. The two BLOCKING generators are replaced
by fakes that persist exactly what the real ones persist (a mesh file plus its
sidecar carrying `backend`), so the READERS stay real: `get_model3d_info` and
`props.list_models` are the production functions, and every "is the asset there
/ which backend made it" assertion goes through them.

  1. The parameter contract is the base class's.  `model_replace` declares
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

from app.core import (expression_regen, location_model3d, model3d,  # noqa: E402
                      model_refs, props)
from app.core.improvements import registry  # noqa: E402
from app.core.improvements.base import CandidateBusy  # noqa: E402
from app.core.improvements.types import subjects  # noqa: E402
from app.core.model_store import write_sidecar  # noqa: E402
from app.core.timeutils import utc_now_iso  # noqa: E402
from app.models import world  # noqa: E402
from app.models.character import (get_character_dir,  # noqa: E402
                                  save_character_profile)

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
# The backend INVENTORY, not an asset reader: without configured mesh
# backends `list_mesh_backends` answers {"backends": [], "default": ""} and
# every "which backend is the default" expectation would be vacuous.
model3d.list_mesh_backends = lambda rig="": {
    "backends": [{"name": "hy"}, {"name": "tr"}], "default": "tr"}

MODEL_REPLACE = registry.get("model_replace")
FILL_MISSING = registry.get("fill_missing")

A = make_character("demo_a")
B = make_character("demo_b")
TEMP = make_character("demo_temp", template="npc-temporary")


def candidates(improvement_type, params):
    return [(c.key, c.label)
            for c in improvement_type.find_candidates(improvement_type.validate(params))]


# ── [1] the parameter contract ──────────────────────────────────────────────
print("[1] model_replace parameters")
check("both types are registered", sorted(t.id for t in registry.list_types()),
      ["fill_missing", "model_replace"])
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

print()
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}: " + ", ".join(FAILURES))
    sys.exit(1)
print(f"All {CHECKED} checks OK")
