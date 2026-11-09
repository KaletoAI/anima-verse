#!/usr/bin/env python3
"""Smoke: the garment occasions, the garment_edit use case and their routing seeds.

Usage:  ./.venv/bin/python scripts/smoke_garment_routing.py

Plan: docs/superpowers/plans/2026-11-09-base-body-phase4-hair.md, ruling R4 + Task 2.
No server, no world DB: the catalog and the migration are pure functions; the use
case is read with an empty in-memory config (temp world + temp instance).

Expected values, derived by hand from R4:
1. `garment_view` and `mesh_garment` are catalog ids (occasion_ids()).
2. `garment_view` is an IMAGE occasion with needs_ref_slot=True, so the rule of
   backend_fits is "render category, not inpaint, ref_slot_count >= 1":
     image/img2img/ref 0 -> False   (no reference slot for the source view)
     image/img2img/ref 1 -> True
   It is character-scoped on the field tpose_view_workflow, no fallback field —
   the same position-0 glob as the dressed edits (tpose_view).
3. `mesh_garment` is a MESH occasion, category img2mesh, rig "none", world-scoped:
     mesh/img2mesh -> True
     mesh/mesh2rig -> False (a rigger never meshes a garment)
4. config._migrate_garment_routing on
     {image_generation: {routing: {tpose_view: ["A", "B"], mesh_humanoid: ["U"]}}}
   copies each source chain once:  garment_view == ["A", "B"], mesh_garment == ["U"],
   returns True. The copies are independent lists (mutating one leaves the other).
   A second run finds both targets present -> returns False, nothing changes.
5. An existing garment_view ["X"] is kept (the admin owns it); mesh_garment is
   still seeded from mesh_humanoid -> True, garment_view stays ["X"].
6. Without a source (routing {"photo": ["P"]}) nothing is added -> False, and the
   routing dict is exactly {"photo": ["P"]}. A missing routing dict -> False.
7. _mesh_routing_occasions: a matching img2mesh backend now serves FIVE mesh
   occasions: mesh_humanoid, mesh_creature, mesh_object, mesh_building, mesh_garment.
8. get_use_case_prompts("garment_edit", family) for both families, with no admin
   override, gives:
     prompt_style       ""
     prompt_instruction ""
     prompt_negative    the spike NEG, literally:
       "illustration, anime, cgi, painting, cartoon, drawing, sketch, watermark,
        signature, text, logo, deformed, blurry, low quality, overexposed, glossy,
        dramatic lighting"
     (one line, ", "-joined, as in hair_edit.py of the spike).
9. The migration is registered in _apply_file_migrations: running that on the
   step-4 input seeds both chains too.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILED = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILED.append(label)


SPIKE_NEG = ("illustration, anime, cgi, painting, cartoon, drawing, sketch, watermark, "
             "signature, text, logo, deformed, blurry, low quality, overexposed, glossy, "
             "dramatic lighting")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        from app.core import paths
        root = Path(tmp)
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import config
        from app.imagegen import occasions as occ

        world = root / "world" / "config.json"
        instance = root / "instance" / "config.json"
        world.write_text("{}", encoding="utf-8")
        instance.write_text("{}", encoding="utf-8")
        config.load(world, instance)

        print("1. catalog ids")
        ids = occ.occasion_ids()
        check("garment_view in catalog", "garment_view" in ids, True)
        check("mesh_garment in catalog", "mesh_garment" in ids, True)

        print("2. garment_view")
        if "garment_view" in ids:
            check("img2img ref 0", occ.backend_fits(
                "garment_view", {"media": "image", "category": "img2img",
                                 "ref_slot_count": 0}), False)
            check("img2img ref 1", occ.backend_fits(
                "garment_view", {"media": "image", "category": "img2img",
                                 "ref_slot_count": 1}), True)
            gv = occ.get_occasion("garment_view")
            check("scope", (gv["media"], gv["category"], gv["character_scoped"],
                            gv["char_spec_field"], gv["char_spec_fallback"],
                            gv["needs_ref_slot"], gv["style_use_cases"]),
                  ("image", "render", True, "tpose_view_workflow", "", True,
                   ["garment_edit"]))

        print("3. mesh_garment")
        if "mesh_garment" in ids:
            check("img2mesh", occ.backend_fits(
                "mesh_garment", {"media": "mesh", "category": "img2mesh"}), True)
            check("mesh2rig", occ.backend_fits(
                "mesh_garment", {"media": "mesh", "category": "mesh2rig"}), False)
            mg = occ.get_occasion("mesh_garment")
            check("scope", (mg["media"], mg["category"], mg["rig"],
                            mg["character_scoped"]),
                  ("mesh", "img2mesh", "none", False))

        print("4-6. migration")
        migrate = getattr(config, "_migrate_garment_routing", None)
        check("migration exists", callable(migrate), True)
        if callable(migrate):
            cfg = {"image_generation": {"routing": {"tpose_view": ["A", "B"],
                                                    "mesh_humanoid": ["U"]}}}
            check("first run", migrate(cfg), True)
            routing = cfg["image_generation"]["routing"]
            check("garment_view copied", routing.get("garment_view"), ["A", "B"])
            check("mesh_garment copied", routing.get("mesh_garment"), ["U"])
            routing["garment_view"].append("Z")
            check("copy is independent", routing["tpose_view"], ["A", "B"])
            check("second run", migrate(cfg), False)

            cfg = {"image_generation": {"routing": {"tpose_view": ["A"],
                                                    "garment_view": ["X"],
                                                    "mesh_humanoid": ["U"]}}}
            check("existing target run", migrate(cfg), True)
            check("existing garment_view kept",
                  cfg["image_generation"]["routing"]["garment_view"], ["X"])
            check("mesh_garment seeded beside it",
                  cfg["image_generation"]["routing"]["mesh_garment"], ["U"])

            cfg = {"image_generation": {"routing": {"photo": ["P"]}}}
            check("no source run", migrate(cfg), False)
            check("no source untouched", cfg["image_generation"]["routing"],
                  {"photo": ["P"]})
            check("no routing dict", migrate({"image_generation": {}}), False)
            check("no image_generation", migrate({}), False)

        print("7. mesh seed occasions")
        backends = [{"name": "Mesh-A", "api_type": "openai_mesh", "category": "img2mesh"}]
        check("five mesh occasions",
              config._mesh_routing_occasions("Mesh-*", backends),
              ["mesh_humanoid", "mesh_creature", "mesh_object", "mesh_building",
               "mesh_garment"])

        print("8. garment_edit use case")
        for family in ("natural", "keywords"):
            p = config.get_use_case_prompts("garment_edit", family)
            check(f"{family} style", p["prompt_style"], "")
            check(f"{family} instruction", p["prompt_instruction"], "")
            check(f"{family} negative", p["prompt_negative"], SPIKE_NEG)

        print("9. registered in _apply_file_migrations")
        cfg = {"image_generation": {"routing": {"tpose_view": ["A", "B"],
                                                "mesh_humanoid": ["U"]}}}
        config._apply_file_migrations(cfg)
        routing = cfg["image_generation"]["routing"]
        check("garment_view via file migrations", routing.get("garment_view"), ["A", "B"])
        check("mesh_garment via file migrations", routing.get("mesh_garment"), ["U"])

    if FAILED:
        print(f"\n{len(FAILED)} check(s) failed: {FAILED}")
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
