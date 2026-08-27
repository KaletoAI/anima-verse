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

from app.core import model3d, model_refs, props  # noqa: E402
from app.core.improvements import registry  # noqa: E402
from app.core.improvements.base import CandidateBusy  # noqa: E402
from app.core.improvements.types import subjects  # noqa: E402
from app.core.timeutils import utc_now_iso  # noqa: E402
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


model3d.generate_for_current_outfit = fake_mesh
props._generate = fake_prop_generate
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
FILL_MISSING.apply(CAND_P, FILL_MISSING.validate(FILL_PROP), "task-5")
check("apply re-meshes the existing image with the default backend", PROP_CALLS,
      [{"prop_id": PROP, "mesh_backend_glob": "tr", "mesh_only": True}])
check("the stored mesh records the backend that made it",
      (subjects.prop_model(PROP) or {}).get("backend"), "tr")
check("and the prop is no longer missing a model",
      candidates(FILL_MISSING, FILL_PROP), [])

print()
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}: " + ", ".join(FAILURES))
    sys.exit(1)
print(f"All {CHECKED} checks OK")
