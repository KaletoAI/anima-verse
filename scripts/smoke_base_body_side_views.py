#!/usr/bin/env python3
"""Base body: dressed side views (opt-in) (finding 6) — the setting and the
side draft's occasion and routing. No back refit since Task 11g (Ruling C1:
the model fit, and the refit of it, replaced by the CPU composite —
``smoke_view_composite.py``). A224 removed the painted mode and its worker:
the worker argv ([2]), the side-arm margin and the painted outfit passes
([4]–[6], which rendered and painted the dressed side views on the plain
body) went with it; a shape's own views (side views included) are rendered
by the Build's shape step (``smoke_figure_build_plan.py``,
``smoke_outfit_body_mesh.py``).

Usage:
    ./.venv/bin/python scripts/smoke_base_body_side_views.py

Runs against a THROWAWAY world + instance with a copy of the repo's ``human``
package — no real world, no image backend, no server process.

Expected, derived by hand from the brief (fix 6, user test 2026-11-09):

[1] Settings. Without a ``base_body`` section: dressed_views() = (front,
    back). dressed_side_views true -> (front, back, left, right); the string
    "true" is no bool -> off. Schema: the field in section base_body, scope
    world (config_scope.scope_of), default False; no ``side_arm_margin``
    field any more (A224), and a stored one is stripped on load
    (config._strip_dead_config_fields on {base_body: {side_arm_margin: 0.05,
    dressed_side_views: true}} -> True, {base_body: {dressed_side_views:
    true}} left).
[3] Occasions and routing. outfit_side_draft: fields
    [outfit_side_draft_workflow, outfit_back_draft_workflow,
    tpose_view_workflow], use case outfit_edit (Ruling A125), no ref slot, a
    mesh-input occasion, its hint names "Dressed side views"; outfit_side
    is no occasion any more; the catalog order has the side draft right
    after outfit_back_draft. Seeding (config._apply_file_migrations on
    routing {tpose_view: [b*], outfit_back: [mine], outfit_side: [own]}):
    outfit_back_draft [b*] (the base-body seed), outfit_side_draft [b*],
    outfit_back / outfit_side dropped; a second
    _migrate_outfit_side_routing -> False; an existing outfit_side_draft
    [own] stays. Per character {tpose_view_workflow v,
    outfit_back_draft_workflow od}: outfit_side_draft od; plus
    outfit_side_draft_workflow sd -> sd. BASE_BODY_MATCH_FIELDS ends with
    the two draft fields.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {repr(got)[:200]}"
          + ("" if ok else f" — expected {repr(want)[:400]}"))
    if not ok:
        FAILS.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="base-body-sides-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import base_body, character_ops, config_scope
        from app.core.config_schema import SECTIONS, field_default
        from app.imagegen import occasions, routing
        import app.models.character as character_module

        # --- [1] settings ---------------------------------------------------------
        print("[1] settings")
        config._CONFIG.pop("base_body", None)
        check("default views", base_body.dressed_views(), ("front", "back"))
        config._CONFIG["base_body"] = {"dressed_side_views": True}
        check("on", base_body.dressed_views(), ("front", "back", "left", "right"))
        config._CONFIG["base_body"] = {"dressed_side_views": "true"}
        check("string is not on", base_body.dressed_views(), ("front", "back"))
        config._CONFIG.pop("base_body", None)
        fields = SECTIONS["base_body"]["fields"]
        check("schema default", field_default("base_body", "dressed_side_views"), False)
        check("no side_arm_margin field (A224)", "side_arm_margin" in fields, False)
        check("world scope", config_scope.scope_of("base_body.dressed_side_views"), "world")
        stored = {"base_body": {"side_arm_margin": 0.05, "dressed_side_views": True}}
        check("a stored margin is stripped", (config._strip_dead_config_fields(stored), stored),
              (True, {"base_body": {"dressed_side_views": True}}))

        # --- [3] occasions + routing ---------------------------------------------
        print("[3] occasions")
        sd = occasions.OCCASIONS["outfit_side_draft"]
        check("side draft fields", occasions.spec_fields(sd),
              ["outfit_side_draft_workflow", "outfit_back_draft_workflow", "tpose_view_workflow"])
        check("use case (Ruling A125: an edit of the base view)", sd.get("style_use_cases"), ["outfit_edit"])
        check("ref slot", bool(sd.get("needs_ref_slot")), False)
        check("mesh input", "outfit_side_draft" in occasions.MESH_INPUT_OCCASIONS, True)
        check("hint", "Dressed side views" in sd.get("hint", ""), True)
        check("no side fit occasion", "outfit_side" in occasions.OCCASIONS, False)
        ids = occasions.occasion_ids()
        i = ids.index("outfit_back_draft")
        check("catalog order", ids[i:i + 2], ["outfit_back_draft", "outfit_side_draft"])
        union = {"image_generation": {"routing": {"tpose_view": ["b*"], "outfit_back": ["mine"],
                                                  "outfit_side": ["own"]}}}
        config._apply_file_migrations(union)
        r = union["image_generation"]["routing"]
        check("seeded", [r.get(k) for k in ("outfit_back_draft", "outfit_side_draft")], [["b*"], ["b*"]])
        check("fit chains dropped", ("outfit_back" in r, "outfit_side" in r), (False, False))
        check("second run unchanged", config._migrate_outfit_side_routing(union), False)
        own = {"image_generation": {"routing": {"outfit_back_draft": ["x"], "outfit_side_draft": ["own"]}}}
        config._migrate_outfit_side_routing(own)
        check("own chain kept", own["image_generation"]["routing"]["outfit_side_draft"], ["own"])
        real_profile = character_module.get_character_profile
        record = {"tpose_view_workflow": "v", "outfit_back_draft_workflow": "od"}
        character_module.get_character_profile = lambda name: {"outfit_imagegen": dict(record)}
        try:
            check("fallback", routing._character_spec(sd, "Demo"), "od")
            record["outfit_side_draft_workflow"] = "sd"
            check("own field", routing._character_spec(sd, "Demo"), "sd")
        finally:
            character_module.get_character_profile = real_profile
        check("match fields", character_ops.BASE_BODY_MATCH_FIELDS[-2:],
              ("outfit_back_draft_workflow", "outfit_side_draft_workflow"))

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
