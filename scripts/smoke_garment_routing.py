#!/usr/bin/env python3
"""Smoke: the garment and footwear occasions, their use cases and their routing seeds — one table per kind.

Usage:  ./.venv/bin/python scripts/smoke_garment_routing.py

No server, no world DB: the catalog and the migrations are pure functions; the use cases are read with an empty
in-memory config (temp world + temp instance). Two sections share one set-up and one parameterised migration /
use-case check; a failing section does not stop the next, the run exits non-zero and names every failed section.

[G] GARMENT (plan docs/superpowers/plans/2026-11-09-base-body-phase4-hair.md, ruling R4 + Task 2).
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
   routing dict is exactly {"photo": ["P"]}. A missing routing dict -> False, no image_generation -> False.
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

[F] FOOTWEAR (plan docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md, Task 2 + the Global Constraints
("Routing: mesh_footwear (world-scoped, img2mesh, seeded once from mesh_garment) and footwear_empty (world-scoped
image edit, needs_ref_slot=True, use case footwear_source) ... No per-character override for either")).
Expected values, derived by hand from the plan:
R1. Catalog.
    1. `mesh_footwear` and `footwear_empty` are catalog ids, in that order, in
       the garment group after `mesh_garment` (the brief: "two entries after
       mesh_garment"; `hair_views_mesh`, which stood between them, went with
       the hair edit chain — hair-from-body spec 2026-11-11, Task 2):
         mesh_garment, mesh_footwear, footwear_empty.
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

THE SHARED MIGRATION TABLE (both kinds, steps 4-6 / R2.4-R2.8): first run on the sources -> True and every
target a copy of its source; appending to the first target leaves its source unchanged; a second run -> False and
the routing unchanged; an existing first target is kept while the second is still seeded -> True; no source ->
False, routing exactly {photo: [P]}; no routing dict / no image_generation -> False; _apply_file_migrations on the
first input seeds every target.
"""
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILED = []          # (section, label)
_SECTION = ["-"]


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILED.append((_SECTION[0], label))


def section(name, fn, *args):
    """Run one section; a crash is recorded and the next section still runs."""
    _SECTION[0] = name
    print(f"\n=== {name}")
    try:
        fn(*args)
    except Exception:  # noqa: BLE001 — a crashed section is a failed section, the others still run
        traceback.print_exc()
        FAILED.append((name, "crashed"))


SPIKE_NEG = ("illustration, anime, cgi, painting, cartoon, drawing, sketch, watermark, "
             "signature, text, logo, deformed, blurry, low quality, overexposed, glossy, "
             "dramatic lighting")
SHOE_STYLE = "product photo, single shoe, plain white background, even studio light"
SHOE_NEG = "foot, leg, skin, person, pair of shoes, second shoe, shadow clutter"


def k(media, cat, ref=1):
    return {"media": media, "category": cat, "ref_slot_count": ref}


def check_migration(config, tag, migrate_name, seeds, own):
    """The shared migration table. ``seeds`` = [(target, source, source chain)], ``own`` = the chain an admin set
    on the FIRST target before the run."""
    migrate = getattr(config, migrate_name, None)
    check(f"{tag} migration exists", callable(migrate), True)
    if not callable(migrate):
        return

    def first_input():
        return {"image_generation": {"routing": {src: list(chain) for _t, src, chain in seeds}}}

    cfg = first_input()
    check(f"{tag} first run", migrate(cfg), True)
    routing = cfg["image_generation"]["routing"]
    for target, _src, chain in seeds:
        check(f"{tag} {target} copied", routing.get(target), chain)
    first_target, first_source, first_chain = seeds[0]
    routing[first_target].append("Z")
    check(f"{tag} copy is independent", routing[first_source], first_chain)
    routing[first_target].pop()
    before = {key: list(v) for key, v in routing.items()}
    check(f"{tag} second run", migrate(cfg), False)
    check(f"{tag} routing unchanged", routing, before)

    cfg = first_input()
    cfg["image_generation"]["routing"][first_target] = list(own)
    check(f"{tag} existing target run", migrate(cfg), True)
    check(f"{tag} existing {first_target} kept", cfg["image_generation"]["routing"][first_target], own)
    for target, _src, chain in seeds[1:]:
        check(f"{tag} {target} seeded beside it", cfg["image_generation"]["routing"][target], chain)

    cfg = {"image_generation": {"routing": {"photo": ["P"]}}}
    check(f"{tag} no source run", migrate(cfg), False)
    check(f"{tag} no source untouched", cfg["image_generation"]["routing"], {"photo": ["P"]})
    check(f"{tag} no routing dict", migrate({"image_generation": {}}), False)
    check(f"{tag} no image_generation", migrate({}), False)

    cfg = first_input()
    config._apply_file_migrations(cfg)
    for target, _src, chain in seeds:
        check(f"{tag} {target} via file migrations", cfg["image_generation"]["routing"].get(target), chain)


def check_use_case(config, use_case, style, instruction, negative):
    for family in ("natural", "keywords"):
        p = config.get_use_case_prompts(use_case, family)
        check(f"{use_case} {family} style", p.get("prompt_style"), style)
        check(f"{use_case} {family} instruction", p.get("prompt_instruction"), instruction)
        check(f"{use_case} {family} negative", p.get("prompt_negative"), negative)


def section_garment(config, occ):
    print("1. catalog ids")
    ids = occ.occasion_ids()
    check("garment_view in catalog", "garment_view" in ids, True)
    check("mesh_garment in catalog", "mesh_garment" in ids, True)

    print("2. garment_view")
    if "garment_view" in ids:
        check("img2img ref 0", occ.backend_fits("garment_view", k("image", "img2img", 0)), False)
        check("img2img ref 1", occ.backend_fits("garment_view", k("image", "img2img", 1)), True)
        gv = occ.get_occasion("garment_view")
        check("scope", (gv["media"], gv["category"], gv["character_scoped"],
                        gv["char_spec_field"], gv["char_spec_fallback"],
                        gv["needs_ref_slot"], gv["style_use_cases"]),
              ("image", "render", True, "tpose_view_workflow", "", True,
               ["garment_edit"]))

    print("3. mesh_garment")
    if "mesh_garment" in ids:
        check("img2mesh", occ.backend_fits("mesh_garment", {"media": "mesh", "category": "img2mesh"}), True)
        check("mesh2rig", occ.backend_fits("mesh_garment", {"media": "mesh", "category": "mesh2rig"}), False)
        mg = occ.get_occasion("mesh_garment")
        check("scope", (mg["media"], mg["category"], mg["rig"], mg["character_scoped"]),
              ("mesh", "img2mesh", "none", False))

    print("4-6, 9. migration")
    check_migration(config, "garment", "_migrate_garment_routing",
                    [("garment_view", "tpose_view", ["A", "B"]), ("mesh_garment", "mesh_humanoid", ["U"])],
                    own=["X"])

    print("7. mesh seed occasions")
    backends = [{"name": "Mesh-A", "api_type": "openai_mesh", "category": "img2mesh"}]
    check("five mesh occasions",
          config._mesh_routing_occasions("Mesh-*", backends),
          ["mesh_humanoid", "mesh_creature", "mesh_object", "mesh_building",
           "mesh_garment"])

    print("8. garment_edit use case")
    check_use_case(config, "garment_edit", "", "", SPIKE_NEG)


def section_footwear(config, occ):
    print("R1.1 catalog ids")
    ids = occ.occasion_ids()
    check("mesh_footwear in catalog", "mesh_footwear" in ids, True)
    check("footwear_empty in catalog", "footwear_empty" in ids, True)
    if "mesh_garment" in ids and "mesh_footwear" in ids and "footwear_empty" in ids:
        i = ids.index("mesh_garment")
        check("order after mesh_garment", ids[i:i + 3], ["mesh_garment", "mesh_footwear", "footwear_empty"])

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
    check("seed table", getattr(config, "_FOOTWEAR_ROUTING_SEEDS", None),
          (("mesh_footwear", "mesh_garment"), ("footwear_empty", "garment_view")))
    check_migration(config, "footwear", "_migrate_footwear_routing",
                    [("mesh_footwear", "mesh_garment", ["UniForge*"]), ("footwear_empty", "garment_view", ["Qwen*"])],
                    own=["Own*"])
    migrate = getattr(config, "_migrate_footwear_routing", None)
    if callable(migrate):
        cfg = {"image_generation": {"routing": {"garment_view": ["Qwen*"]}}}
        check("7 one source run", migrate(cfg), True)
        check("7 one source: footwear_empty",
              cfg["image_generation"]["routing"].get("footwear_empty"), ["Qwen*"])
        check("7 one source: no mesh_footwear",
              "mesh_footwear" in cfg["image_generation"]["routing"], False)

    print("R3 footwear_source use case")
    check_use_case(config, "footwear_source", SHOE_STYLE, "", SHOE_NEG)


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

        section("[G] garment", section_garment, config, occ)
        section("[F] footwear", section_footwear, config, occ)

    if FAILED:
        names = list(dict.fromkeys(s for s, _ in FAILED))
        print(f"\n{len(FAILED)} check(s) failed in section(s) {', '.join(names)}: {[label for _s, label in FAILED]}")
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
