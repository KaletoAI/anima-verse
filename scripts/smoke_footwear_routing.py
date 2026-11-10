#!/usr/bin/env python3
"""Smoke: the footwear occasions, the footwear_source use case and their routing seeds.

Usage:  ./.venv/bin/python scripts/smoke_footwear_routing.py

Plan: docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md, Task 2 + the
Global Constraints ("Routing: mesh_footwear (world-scoped, img2mesh, seeded once
from mesh_garment) and footwear_empty (world-scoped image edit,
needs_ref_slot=True, use case footwear_source) ... No per-character override for
either"). No server, no world DB: the catalog and the migration are pure
functions; the use case is read with an empty in-memory config (temp world +
temp instance).

Expected values, derived by hand from the plan:
R1. Catalog.
    1. `mesh_footwear` and `footwear_empty` are catalog ids, in that order, in
       the garment group after `mesh_garment` (the brief: "two entries after
       mesh_garment"). `hair_views_mesh` is pinned RIGHT after mesh_garment by
       smoke_hair_views_mesh_route, so the pair follows it:
         mesh_garment, hair_views_mesh, mesh_footwear, footwear_empty.
    2. `mesh_footwear` = _mesh(..., "none") world scope:
         (media, category, rig, character_scoped, char_spec_field,
          needs_ref_slot, style_use_cases)
         == ("mesh", "img2mesh", "none", False, "", False, [])
       backend_fits: mesh/img2mesh -> True, mesh/mesh2rig -> False,
       mesh/img2hair -> False (only img2mesh meshes a shoe).
    3. `footwear_empty` = _image(..., ["footwear_source"], _WORLD,
       needs_ref_slot=True):
         (media, category, character_scoped, char_spec_field,
          needs_ref_slot, style_use_cases)
         == ("image", "render", False, "", True, ["footwear_source"])
       backend_fits follows "render category, not inpaint, ref_slot_count >= 1":
         image/img2img/ref 0 -> False   (no slot for the item image)
         image/img2img/ref 1 -> True
         image/inpaint/ref 1 -> False
       Labels, verbatim from the brief: "3D mesh — footwear" and
       "Footwear — empty shoe edit".
R2. Migration config._migrate_footwear_routing (seeds
    (("mesh_footwear", "mesh_garment"), ("footwear_empty", "garment_view"))).
    4. On {image_generation: {routing: {mesh_garment: ["UniForge*"],
       garment_view: ["Qwen*"]}}} -> returns True,
       mesh_footwear == ["UniForge*"], footwear_empty == ["Qwen*"]; the copies
       are independent lists (appending to one leaves the source unchanged).
    5. A second run finds both targets present -> False, routing unchanged.
    6. An existing mesh_footwear ["Own*"] is never overwritten: run on
       {mesh_garment: ["UniForge*"], garment_view: ["Qwen*"],
        mesh_footwear: ["Own*"]} -> True (footwear_empty is still seeded),
       mesh_footwear stays ["Own*"], footwear_empty == ["Qwen*"].
    7. A missing source seeds nothing: {photo: ["P"]} -> False, routing exactly
       {photo: ["P"]}; only garment_view present -> True, footwear_empty seeded,
       "mesh_footwear" not in routing. No routing dict / no image_generation
       -> False.
    8. Registered in _apply_file_migrations: running that on the step-4 input
       seeds both chains too.
R3. Use case footwear_source, both families, no admin override, verbatim:
       prompt_style       "product photo, single shoe, plain white background,
                           even studio light"
       prompt_negative    "foot, leg, skin, person, pair of shoes, second shoe,
                           shadow clutter"
       prompt_instruction ""
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


STYLE = "product photo, single shoe, plain white background, even studio light"
NEG = "foot, leg, skin, person, pair of shoes, second shoe, shadow clutter"


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

        print("R1.1 catalog ids")
        ids = occ.occasion_ids()
        check("mesh_footwear in catalog", "mesh_footwear" in ids, True)
        check("footwear_empty in catalog", "footwear_empty" in ids, True)
        if "mesh_garment" in ids and "mesh_footwear" in ids and "footwear_empty" in ids:
            i = ids.index("mesh_garment")
            check("order after mesh_garment", ids[i:i + 4],
                  ["mesh_garment", "hair_views_mesh", "mesh_footwear", "footwear_empty"])

        def k(media, cat, ref=1):
            return {"media": media, "category": cat, "ref_slot_count": ref}

        print("R1.2 mesh_footwear")
        if "mesh_footwear" in ids:
            mf = occ.get_occasion("mesh_footwear")
            check("scope", (mf["media"], mf["category"], mf["rig"], mf["character_scoped"],
                            mf["char_spec_field"], mf["needs_ref_slot"],
                            mf["style_use_cases"]),
                  ("mesh", "img2mesh", "none", False, "", False, []))
            check("label", mf["label"], "3D mesh — footwear")
            check("img2mesh fits", occ.backend_fits("mesh_footwear", k("mesh", "img2mesh")), True)
            check("mesh2rig no", occ.backend_fits("mesh_footwear", k("mesh", "mesh2rig")), False)
            check("img2hair no", occ.backend_fits("mesh_footwear", k("mesh", "img2hair")), False)

        print("R1.3 footwear_empty")
        if "footwear_empty" in ids:
            fe = occ.get_occasion("footwear_empty")
            check("scope", (fe["media"], fe["category"], fe["character_scoped"],
                            fe["char_spec_field"], fe["needs_ref_slot"],
                            fe["style_use_cases"]),
                  ("image", "render", False, "", True, ["footwear_source"]))
            check("needs_ref_slot is True", fe["needs_ref_slot"] is True, True)
            check("label", fe["label"], "Footwear — empty shoe edit")
            check("img2img ref 0", occ.backend_fits("footwear_empty", k("image", "img2img", 0)), False)
            check("img2img ref 1", occ.backend_fits("footwear_empty", k("image", "img2img", 1)), True)
            check("inpaint", occ.backend_fits("footwear_empty", k("image", "inpaint", 1)), False)

        print("R2 migration")
        migrate = getattr(config, "_migrate_footwear_routing", None)
        check("migration exists", callable(migrate), True)
        check("seed table", getattr(config, "_FOOTWEAR_ROUTING_SEEDS", None),
              (("mesh_footwear", "mesh_garment"), ("footwear_empty", "garment_view")))
        if callable(migrate):
            cfg = {"image_generation": {"routing": {"mesh_garment": ["UniForge*"],
                                                    "garment_view": ["Qwen*"]}}}
            check("4 first run", migrate(cfg), True)
            routing = cfg["image_generation"]["routing"]
            check("4 mesh_footwear copied", routing.get("mesh_footwear"), ["UniForge*"])
            check("4 footwear_empty copied", routing.get("footwear_empty"), ["Qwen*"])
            routing["mesh_footwear"].append("Z")
            check("4 copy is independent", routing["mesh_garment"], ["UniForge*"])
            routing["mesh_footwear"].pop()
            before = {k_: list(v) for k_, v in routing.items()}
            check("5 second run", migrate(cfg), False)
            check("5 routing unchanged", routing, before)

            cfg = {"image_generation": {"routing": {"mesh_garment": ["UniForge*"],
                                                    "garment_view": ["Qwen*"],
                                                    "mesh_footwear": ["Own*"]}}}
            check("6 existing target run", migrate(cfg), True)
            check("6 existing mesh_footwear kept",
                  cfg["image_generation"]["routing"]["mesh_footwear"], ["Own*"])
            check("6 footwear_empty seeded beside it",
                  cfg["image_generation"]["routing"]["footwear_empty"], ["Qwen*"])

            cfg = {"image_generation": {"routing": {"photo": ["P"]}}}
            check("7 no source run", migrate(cfg), False)
            check("7 no source untouched", cfg["image_generation"]["routing"],
                  {"photo": ["P"]})
            cfg = {"image_generation": {"routing": {"garment_view": ["Qwen*"]}}}
            check("7 one source run", migrate(cfg), True)
            check("7 one source: footwear_empty",
                  cfg["image_generation"]["routing"].get("footwear_empty"), ["Qwen*"])
            check("7 one source: no mesh_footwear",
                  "mesh_footwear" in cfg["image_generation"]["routing"], False)
            check("7 no routing dict", migrate({"image_generation": {}}), False)
            check("7 no image_generation", migrate({}), False)

        print("R2.8 registered in _apply_file_migrations")
        cfg = {"image_generation": {"routing": {"mesh_garment": ["UniForge*"],
                                                "garment_view": ["Qwen*"]}}}
        config._apply_file_migrations(cfg)
        routing = cfg["image_generation"]["routing"]
        check("mesh_footwear via file migrations", routing.get("mesh_footwear"), ["UniForge*"])
        check("footwear_empty via file migrations", routing.get("footwear_empty"), ["Qwen*"])

        print("R3 footwear_source use case")
        for family in ("natural", "keywords"):
            p = config.get_use_case_prompts("footwear_source", family)
            check(f"{family} style", p.get("prompt_style"), STYLE)
            check(f"{family} negative", p.get("prompt_negative"), NEG)
            check(f"{family} instruction", p.get("prompt_instruction"), "")

    if FAILED:
        print(f"\n{len(FAILED)} check(s) failed: {FAILED}")
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
