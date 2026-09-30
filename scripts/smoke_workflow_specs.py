#!/usr/bin/env python3
"""Smoke run for the canonical render-target specs (Config-Altlasten, part B).

A render target is a BACKEND GLOB ("Flux2*", or an exact backend name); the
prefix ``backend:`` is tolerated legacy. The ComfyUI-era ``workflow:<glob>``
is dead — ``BackendPool.resolve_spec`` resolves it to None, so whoever
configured it silently rendered on some other backend.

What is checked here, all hand-derived, no snapshots:

  1. ``messaging_frame.parse_target`` — the sharpest case of the finding: the
     CANONICAL glob used to be REJECTED ("Ungueltiges Target-Format") while the
     dead ``workflow:`` form was accepted. Now the glob passes and
     ``workflow:`` is refused with a message that names the replacement.
  2. The pure rewriter ``strip_legacy_workflow_prefix`` by hand:
     ``workflow:Flux`` -> ``Flux``, a bare ``workflow:`` -> empty (= auto),
     and everything else — bare glob, ``backend:`` spec, empty, non-string —
     comes back untouched, including surrounding whitespace.
  3. RED COUNTER-CHECK: the FIELD NAME ``workflow`` is alive and must survive.
     It holds a backend glob — only a ``workflow:`` prefix in the VALUE is
     legacy. Its consumer is the image routing since R2a
     (development_instructions/plan-image-routing.md, Task 11 moved it out
     of app/core/expression_regen.py): ``routing._character_spec`` reads
     ``outfit_imagegen[<char_spec_field>]`` of the occasion catalog, and the
     catalog names ``workflow`` for the character occasions (``expression``,
     ``profile``) and as the fallback of ``tpose``. Checked against the
     catalog, the reader's source line AND the migrated profile, whose key
     must still be ``workflow``.
  (4. The config half is gone: the per-occasion default fields it rewrote
     are migrated into image_generation.routing and removed —
     scripts/smoke_image_routing_migration.py.)
  5. The per-character half (``migrate_legacy_workflow_specs_once``) against a
     THROWAWAY world: the legacy profile is rewritten, an already-canonical one
     is left alone, the world_kv marker is set, and a second run is a no-op.
     The file-backed skill configs (characters/<name>/skills/*.json, field
     ``imagegen_workflow``) are NOT touched any more — the field has no
     reader, so a legacy value there is left as it is.
  6. ``unknown_backend_error``: a glob that names no enabled backend is caught
     BEFORE the render. The ComfyUI era left workflow NAMES here ("Z-Image"),
     which look canonical after the prefix strip but match no backend — the
     render used to die deep in the service with a German message about a
     timeout that never happened.
  (7. The import-side rewrite of skills/*.json is gone with the field.)

Usage:  ./.venv/bin/python scripts/smoke_workflow_specs.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Point the storage root at a throwaway directory BEFORE any app import — the
# config load path writes to the world's config.json (dead-field strip, image
# routing migration), and without STORAGE_DIR there is no world at all: paths.init()
# raises StorageNotInitialised, so the tracked worlds/demo cannot be reached.
# Same reflex as scripts/smoke_dead_config_fields.py.
_TMP_STORAGE = tempfile.TemporaryDirectory(prefix="smoke_workflow_specs_")
os.environ.setdefault("STORAGE_DIR", _TMP_STORAGE.name)

from app.core import paths  # noqa: E402

paths.init(Path(_TMP_STORAGE.name))

from app.core import db  # noqa: E402

db.init_schema()

from app.core.messaging_frame import (  # noqa: E402
    parse_target, unknown_backend_error)
from app.core.workflow_spec_migration import (  # noqa: E402
    PROFILE_SPEC_FIELDS, migrate_legacy_workflow_specs_once,
    strip_legacy_workflow_prefix)

FAILURES = []
CHECKED = 0


def check(ok, label, detail=""):
    global CHECKED
    CHECKED += 1
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def eq(label, actual, expected):
    check(actual == expected, label, f"got {actual!r}, expected {expected!r}")


def main():
    print("1) parse_target: the canonical form is accepted, the dead one is not")
    for spec, expected in [
        ("Flux2*", "Flux2*"),            # canonical glob — used to be REJECTED
        ("Together-Fast", "Together-Fast"),
        ("  Krea2  ", "Krea2"),
        ("backend:Together-Fast", "Together-Fast"),
        ("BACKEND:Krea2", "Krea2"),      # prefix match is case-insensitive
        ("", ""),                        # empty = auto selection
    ]:
        glob, err = parse_target(spec)
        eq(f"parse_target({spec!r}) -> glob", glob, expected)
        eq(f"parse_target({spec!r}) -> no error", err, "")

    glob, err = parse_target("workflow:Z-Image")
    eq("parse_target('workflow:Z-Image') -> no glob", glob, "")
    check(bool(err) and "workflow:Z-Image" in err and "backend-name glob" in err,
          "workflow: spec rejected with a message naming the replacement",
          repr(err))
    check("ComfyUI" in err, "the message says why (ComfyUI removed)", repr(err))

    glob, err = parse_target("WORKFLOW:Z-Image")
    check(not glob and bool(err), "the rejection is case-insensitive too", repr(err))

    glob, err = parse_target("nonsense:x")
    check(not glob and bool(err) and "Invalid target format" in err,
          "an unknown prefix is rejected as well", repr(err))

    print("2) the rewriter by hand")
    for value, expected in [
        ("workflow:Flux", "Flux"),
        ("workflow:", ""),
        ("workflow: Flux2*  ", "Flux2*"),
        ("WORKFLOW:Flux", "Flux"),
        ("Flux", "Flux"),                 # bare glob: untouched
        ("backend:Flux", "backend:Flux"),  # tolerated prefix: untouched
        (" Flux ", " Flux "),             # no destructive trimming
        ("", ""),
        (None, None),                     # non-string: untouched
        (0, 0),
    ]:
        eq(f"strip_legacy_workflow_prefix({value!r})",
           strip_legacy_workflow_prefix(value), expected)
    eq("running it twice changes nothing more",
       strip_legacy_workflow_prefix(strip_legacy_workflow_prefix("workflow:Flux")),
       "Flux")

    print("3) red counter-check: the FIELD NAME 'workflow' stays alive")
    eq("the bare field name is not a legacy spec",
       strip_legacy_workflow_prefix("workflow"), "workflow")
    from app.imagegen.occasions import get_occasion
    for occ in ("expression", "profile"):
        eq(f"the {occ} occasion reads outfit_imagegen['workflow'] (field name kept)",
           get_occasion(occ).get("char_spec_field"), "workflow")
    eq("the tpose occasion falls back to outfit_imagegen['workflow']",
       get_occasion("tpose").get("char_spec_fallback"), "workflow")
    consumer = (REPO / "app/imagegen/routing.py").read_text(encoding="utf-8")
    check('.get("outfit_imagegen")' in consumer,
          "the image routing reads the outfit_imagegen override")
    eq("the migration targets exactly that field",
       PROFILE_SPEC_FIELDS, (("outfit_imagegen", "workflow"),))

    print("5) the per-character half against a throwaway world")
    from app.models.character import (get_character_dir, get_character_profile,
                                      save_character_profile)
    from app.models.world import get_world_setting

    save_character_profile("Legacy", {
        "name": "Legacy", "description": "carries a ComfyUI-era spec",
        "outfit_imagegen": {"workflow": "workflow:Flux*",
                            "loras": [{"name": "detail", "strength": 0.7}]},
    }, create_new=True)
    save_character_profile("Canonical", {
        "name": "Canonical", "description": "already canonical",
        "outfit_imagegen": {"workflow": "Krea2", "loras": []},
    }, create_new=True)
    save_character_profile("NoOverride", {
        "name": "NoOverride", "description": "no render override at all",
    }, create_new=True)

    # A skill config that still carries the dead field: left alone now.
    skills_dir = get_character_dir("Legacy", create=True) / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    dead = skills_dir / "instagram.json"
    dead.write_text(json.dumps({"imagegen_workflow": "workflow:Qwen*"}),
                    encoding="utf-8")
    dead_before = dead.read_text(encoding="utf-8")

    result = migrate_legacy_workflow_specs_once()
    eq("one character touched", result.get("characters"), 1)
    eq("one field rewritten", result.get("fields"), 1)
    eq("no skill-file count any more", "skill_files" in result, False)
    eq("the dead skill-config field is not rewritten",
       dead.read_text(encoding="utf-8"), dead_before)

    legacy = (get_character_profile("Legacy") or {}).get("outfit_imagegen") or {}
    eq("the legacy value lost its prefix", legacy.get("workflow"), "Flux*")
    check("workflow" in legacy, "the KEY is still 'workflow' (field name kept)")
    eq("the LoRA sibling survived", legacy.get("loras"),
       [{"name": "detail", "strength": 0.7}])
    canonical = (get_character_profile("Canonical") or {}).get("outfit_imagegen") or {}
    eq("the canonical character is untouched", canonical.get("workflow"), "Krea2")
    eq("a character without an override stays without one",
       (get_character_profile("NoOverride") or {}).get("outfit_imagegen"), None)

    check(bool(get_world_setting("migrated_legacy_workflow_specs_v2")),
          "the world_kv marker is set")

    # Idempotency: values planted AFTER the marker must survive, otherwise the
    # guard is not doing its job (and the second run is not really a no-op).
    prof = get_character_profile("Canonical") or {}
    prof["outfit_imagegen"] = {"workflow": "workflow:Planted", "loras": []}
    save_character_profile("Canonical", prof)
    second = migrate_legacy_workflow_specs_once()
    eq("second run touches nothing", second,
       {"characters": 0, "fields": 0})
    eq("the planted profile value proves the guard held",
       ((get_character_profile("Canonical") or {}).get("outfit_imagegen") or {}
        ).get("workflow"), "workflow:Planted")

    print("6) unknown backend: caught before the render, not inside it")
    pool = ["CivitAI-Z-Image", "Flux2-9B Normal", "Together-Fast"]
    eq("an exact name passes", unknown_backend_error("Together-Fast", pool), "")
    eq("a matching glob passes", unknown_backend_error("Flux2*", pool), "")
    eq("a case-different glob passes", unknown_backend_error("civitai-*", pool), "")
    eq("an empty glob passes (auto)", unknown_backend_error("", pool), "")
    err = unknown_backend_error("Z-Image", pool)
    check(bool(err) and "Z-Image" in err and "Messaging frame" in err,
          "the ComfyUI workflow name is refused with an actionable hint", repr(err))
    check(all(n in err for n in pool),
          "the message lists the backends that ARE offered", repr(err))
    check("Timeout" not in err and "verfuegbar" not in err,
          "and it is English, without the bogus timeout claim", repr(err))
    check(bool(unknown_backend_error("Flux", pool)),
          "'Flux' does not match 'Flux2-9B Normal' either (no substring magic)")
    eq("an empty pool refuses everything",
       bool(unknown_backend_error("Anything", [])), True)

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)} of {CHECKED}):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print(f"ALL OK ({CHECKED} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
