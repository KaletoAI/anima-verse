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
     It holds a backend glob (app/core/expression_regen.py reads
     ``outfit_imagegen["workflow"]``) — only a ``workflow:`` prefix in the
     VALUE is legacy. Checked against the consumer's source line AND on the
     migrated profile, whose key must still be ``workflow``.
  4. The config half of the migration (``config._rewrite_legacy_workflow_specs``)
     against a temp config.json: messaging_frame.target and the imagegen
     defaults are rewritten, living neighbours stay, second run writes nothing.
  5. The per-character half (``migrate_legacy_workflow_specs_once``) against a
     THROWAWAY world: the legacy profile is rewritten, an already-canonical one
     is left alone, the file-backed skill configs
     (characters/<name>/skills/*.json, field ``imagegen_workflow``) are swept
     by FIELD NAME across all skill files, the world_kv marker is set, and a
     second run is a no-op.
  6. ``unknown_backend_error``: a glob that names no enabled backend is caught
     BEFORE the render. The ComfyUI era left workflow NAMES here ("Z-Image"),
     which look canonical after the prefix strip but match no backend — the
     render used to die deep in the service with a German message about a
     timeout that never happened.
  7. The import hole: a character ZIP carries skills/*.json verbatim, so an old
     export (or a marketplace pack built from one) would smuggle legacy specs
     back into the world long AFTER the boot migration ran. The import runs the
     same rewriter.

Usage:  ./.venv/bin/python scripts/smoke_workflow_specs.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Point the storage root at a throwaway directory BEFORE any app import — the
# config load path writes to the world's config.json (dead-field strip, spec
# rewrite), and paths.init() falls back to ./worlds/demo when STORAGE_DIR is
# unset. Same reflex as scripts/smoke_dead_config_fields.py.
_TMP_STORAGE = tempfile.TemporaryDirectory(prefix="smoke_workflow_specs_")
os.environ.setdefault("STORAGE_DIR", _TMP_STORAGE.name)

from app.core import paths  # noqa: E402

paths.init(Path(_TMP_STORAGE.name))

from app.core import db  # noqa: E402

db.init_schema()

from app.core import config as cfgmod  # noqa: E402
from app.core.messaging_frame import (  # noqa: E402
    parse_target, unknown_backend_error)
from app.core.workflow_spec_migration import (  # noqa: E402
    PROFILE_SPEC_FIELDS, SKILL_SPEC_FIELD, migrate_legacy_workflow_specs_once,
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
    consumer = (REPO / "app/core/expression_regen.py").read_text(encoding="utf-8")
    check('_char_override.get("workflow")' in consumer,
          "expression_regen still reads outfit_imagegen['workflow'] (field name kept)")
    eq("the migration targets exactly that field",
       PROFILE_SPEC_FIELDS, (("outfit_imagegen", "workflow"),))

    print("4) the config half against a temp config.json")
    check("messaging_frame.target" in cfgmod.LEGACY_SPEC_FIELDS,
          "messaging_frame.target is covered")
    fixture = {
        "image_generation": {
            "outfit_imagegen_default": "workflow:Flux*",
            "expression_imagegen_default": "backend:Krea2",   # stays
            "location_imagegen_default": "Together*",         # stays
            "backends": [{"name": "Krea2", "enabled": True}],  # living neighbour
        },
        "random_events": {"event_imagegen_default": "workflow:", "enabled": True},
        "story_engine": {"imagegen_default": "workflow:Z-Image"},
        "skills": {"instagram": {"imagegen_default": "Flux2*"}},
        "messaging_frame": {"target": "workflow:Z-Image",
                            "prompt": "modern smartphone, pure green screen"},
        "log_level": "INFO",
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        cfg = copy.deepcopy(fixture)
        path.write_text(json.dumps(cfg), encoding="utf-8")
        changed = cfgmod._rewrite_legacy_workflow_specs(cfg, path)
        check(changed is True, "the rewrite reports a change")
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        for label, dotted, expected in [
            ("messaging_frame.target", ("messaging_frame", "target"), "Z-Image"),
            ("outfit default", ("image_generation", "outfit_imagegen_default"), "Flux*"),
            ("story engine default", ("story_engine", "imagegen_default"), "Z-Image"),
            ("bare workflow: -> auto", ("random_events", "event_imagegen_default"), ""),
            ("backend: prefix kept", ("image_generation", "expression_imagegen_default"),
             "backend:Krea2"),
            ("bare glob kept", ("image_generation", "location_imagegen_default"), "Together*"),
            ("nested plugin field kept", ("skills", "instagram", "imagegen_default"), "Flux2*"),
        ]:
            node = on_disk
            for part in dotted:
                node = node.get(part, {}) if isinstance(node, dict) else {}
            eq(f"{label} on disk", node, expected)
        eq("living neighbour untouched",
           on_disk["image_generation"]["backends"], fixture["image_generation"]["backends"])
        eq("living top-level key untouched", on_disk.get("log_level"), "INFO")
        eq("the prompt sibling of target is untouched",
           on_disk["messaging_frame"]["prompt"], "modern smartphone, pure green screen")
        eq("no section lost", sorted(on_disk.keys()), sorted(fixture.keys()))

        mtime = path.stat().st_mtime_ns
        check(cfgmod._rewrite_legacy_workflow_specs(cfg, path) is False,
              "second run reports no change")
        eq("second run wrote nothing", path.stat().st_mtime_ns, mtime)

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

    # The file-backed skill configs: the sweep goes by FIELD NAME, so a second
    # skill file with the same field must be caught without naming any skill.
    def skill_file(character, skill, payload):
        d = get_character_dir(character, create=True) / "skills"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{skill}.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    insta = skill_file("Legacy", "instagram", {
        SKILL_SPEC_FIELD: "workflow:Qwen*", "imagegen_backend": "",
        "hashtags": ["#demo"]})
    video = skill_file("Legacy", "video_generation", {
        SKILL_SPEC_FIELD: "workflow:Z-Image*", "animate_service": "Together*"})
    canon = skill_file("Canonical", "instagram", {SKILL_SPEC_FIELD: "Krea2"})
    other = skill_file("Canonical", "video_generation", {"animate_service": "X*"})
    other_before = other.read_text(encoding="utf-8")
    # A broken file must not abort the sweep around it — otherwise the guard
    # stays unset and the whole migration repeats silently on every boot.
    # 0xff is not valid UTF-8: that is a UnicodeDecodeError, NOT a
    # JSONDecodeError (both are ValueError, which is what the sweep catches).
    binary = get_character_dir("Legacy", create=True) / "skills" / "broken.json"
    binary.write_bytes(b"\xff\xfe not json at all")

    result = migrate_legacy_workflow_specs_once()
    eq("one character touched", result.get("characters"), 1)
    eq("one field rewritten", result.get("fields"), 1)
    eq("two skill files rewritten", result.get("skill_files"), 2)

    ins = json.loads(insta.read_text(encoding="utf-8"))
    eq("the instagram skill config lost its prefix", ins[SKILL_SPEC_FIELD], "Qwen*")
    eq("its siblings survived", ins.get("hashtags"), ["#demo"])
    eq("a second skill file with the same field is swept too",
       json.loads(video.read_text(encoding="utf-8"))[SKILL_SPEC_FIELD], "Z-Image*")
    eq("an already-canonical skill config is untouched",
       json.loads(canon.read_text(encoding="utf-8"))[SKILL_SPEC_FIELD], "Krea2")
    eq("a skill file without the field is not even rewritten",
       other.read_text(encoding="utf-8"), other_before)
    eq("the unreadable file is skipped, not repaired",
       binary.read_bytes(), b"\xff\xfe not json at all")

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
          "the world_kv marker is set (the broken file did not abort the sweep)")

    # Idempotency: values planted AFTER the marker must survive, otherwise the
    # guard is not doing its job (and the second run is not really a no-op).
    prof = get_character_profile("Canonical") or {}
    prof["outfit_imagegen"] = {"workflow": "workflow:Planted", "loras": []}
    save_character_profile("Canonical", prof)
    skill_file("Canonical", "instagram", {SKILL_SPEC_FIELD: "workflow:Planted"})
    second = migrate_legacy_workflow_specs_once()
    eq("second run touches nothing", second,
       {"characters": 0, "fields": 0, "skill_files": 0})
    eq("the planted profile value proves the guard held",
       ((get_character_profile("Canonical") or {}).get("outfit_imagegen") or {}
        ).get("workflow"), "workflow:Planted")
    eq("the planted skill-config value proves it too",
       json.loads(canon.read_text(encoding="utf-8"))[SKILL_SPEC_FIELD],
       "workflow:Planted")

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

    print("7) the import hole: an old ZIP must not smuggle the legacy spec back")
    # "Canonical" still carries the value planted after the marker — a genuine
    # legacy spec inside the export. The boot migration is long done here
    # (guard set), so only the import-side rewrite can clean this up.
    from app.core.character_io import (export_character_to_zip,
                                       import_character_from_zip)
    blob = export_character_to_zip("Canonical")
    import io as _io
    import zipfile as _zip
    with _zip.ZipFile(_io.BytesIO(blob)) as zf:
        in_zip = json.loads(zf.read("files/skills/instagram.json"))
    eq("the export really carries the legacy spec (else the test is empty)",
       in_zip.get(SKILL_SPEC_FIELD), "workflow:Planted")
    res = import_character_from_zip(blob, overwrite=True)
    eq("the import succeeded", res.get("status"), "success")
    eq("the re-imported skill config is canonical",
       json.loads(canon.read_text(encoding="utf-8"))[SKILL_SPEC_FIELD], "Planted")

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
