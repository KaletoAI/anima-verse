#!/usr/bin/env python3
"""Smoke: the image routing occasion catalog (app/imagegen/occasions.py).

Usage:  ./.venv/bin/python scripts/smoke_image_routing_catalog.py

Spec: development_instructions/plan-image-routing.md § 1 + the binding review
notes ("Katalog (§1)"). No server, no world, no DB — it imports the catalog
module only (Part A). Parts B and C (added later) scan the callers by AST.

PART A — THE CATALOG, DERIVED BY HAND FROM THE SPEC
---------------------------------------------------
A1. Exactly these 19 occasions (§ 1 table, minus `mesh_low` which the review
    DROPS, plus `frame` which the review ADDS):
      photo instagram profile expression tpose scene_view location
      timevariant event prop surface_texture item regenerate frame video
      mesh_humanoid mesh_creature mesh_object mesh_building
A2. `mesh_low` is unknown: get_occasion("mesh_low") raises
    UnknownOccasionError, which is a ValueError.
A3. media: video -> "video"; the four mesh_* -> "mesh"; all others "image".
A4. rig: mesh_humanoid "mixamo", mesh_creature "generic", mesh_object and
    mesh_building "none"; category of every mesh occasion "img2mesh", of every
    other "render".
A5. character_scoped exactly: photo, instagram, profile, expression, tpose,
    regenerate (§ 1 column "figurbez." = ja; frame is a product shot without
    a figure — review note).
A6. tpose reads char_spec_field "tpose_workflow" with fallback "workflow"
    (review note); every other character-scoped one reads "workflow" with no
    fallback.
A7. needs_ref_slot only on timevariant (§ 1 "nur Backends mit >= 1 Ref-Slot").
A8. backend_fits, one line each (kind = media/category/rig/ref_slot_count):
      photo    + image/img2img/ref 1          -> True
      photo    + image/inpaint                -> False  (render = all but inpaint)
      photo    + video/txt2img                -> False  (media differs)
      video    + video/txt2img                -> True
      timevariant + image/img2img/ref 0       -> False  (needs a ref slot)
      timevariant + image/img2img/ref 1       -> True
      mesh_object + mesh/img2mesh/rig none    -> True
      mesh_object + mesh/mesh2mesh/rig none   -> False  (a reduction alias)
      mesh_object + mesh/img2mesh/rig mixamo  -> False  (wrong rig)
      mesh_humanoid + mesh/img2mesh/rig ""    -> True   (missing rig = mixamo,
                                                         the backend default)
      mesh_creature + mesh/img2mesh/rig generic -> True
A9. mesh_occasion_for_rig: mixamo -> mesh_humanoid, generic -> mesh_creature,
    none -> mesh_object, none + building=True -> mesh_building.
    MESH_OCCASIONS_BY_RIG["none"] == ("mesh_object", "mesh_building").
A10. catalog_payload() has 19 rows in catalog order, each with the keys
    id, label, media, category, rig, character_scoped, needs_ref_slot, covers;
    every label is a non-empty English string.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILS = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILS.append(label)


def part_a():
    print("A) catalog")
    from app.imagegen import occasions as occ

    expected_ids = ["photo", "instagram", "profile", "expression", "tpose",
                    "scene_view", "location", "timevariant", "event", "prop",
                    "surface_texture", "item", "regenerate", "frame", "video",
                    "mesh_humanoid", "mesh_creature", "mesh_object",
                    "mesh_building"]
    check("A1 the 19 occasions in catalog order", occ.occasion_ids(), expected_ids)

    try:
        occ.get_occasion("mesh_low")
        check("A2 mesh_low raises", "no exception", "UnknownOccasionError")
    except occ.UnknownOccasionError as e:
        check("A2 mesh_low raises a ValueError", isinstance(e, ValueError), True)

    media = {i: occ.get_occasion(i)["media"] for i in expected_ids}
    check("A3 video media", media["video"], "video")
    check("A3 mesh media", sorted(i for i, m in media.items() if m == "mesh"),
          ["mesh_building", "mesh_creature", "mesh_humanoid", "mesh_object"])
    check("A3 image media count", sum(1 for m in media.values() if m == "image"), 14)

    check("A4 rigs", {i: occ.get_occasion(i).get("rig") for i in
                      ("mesh_humanoid", "mesh_creature", "mesh_object", "mesh_building")},
          {"mesh_humanoid": "mixamo", "mesh_creature": "generic",
           "mesh_object": "none", "mesh_building": "none"})
    check("A4 categories",
          sorted({occ.get_occasion(i)["category"] for i in expected_ids}),
          ["img2mesh", "render"])
    check("A4 mesh category",
          {occ.get_occasion(i)["category"] for i in expected_ids if media[i] == "mesh"},
          {"img2mesh"})

    check("A5 character scoped",
          [i for i in expected_ids if occ.get_occasion(i)["character_scoped"]],
          ["photo", "instagram", "profile", "expression", "tpose", "regenerate"])

    tp = occ.get_occasion("tpose")
    check("A6 tpose field", (tp["char_spec_field"], tp["char_spec_fallback"]),
          ("tpose_workflow", "workflow"))
    check("A6 others read workflow",
          {(occ.get_occasion(i)["char_spec_field"], occ.get_occasion(i)["char_spec_fallback"])
           for i in ("photo", "instagram", "profile", "expression", "regenerate")},
          {("workflow", "")})

    check("A7 needs_ref_slot",
          [i for i in expected_ids if occ.get_occasion(i).get("needs_ref_slot")],
          ["timevariant"])

    def k(media_, cat, rig="", ref=1):
        return {"media": media_, "category": cat, "rig": rig, "ref_slot_count": ref}

    fits = occ.backend_fits
    check("A8 photo img2img", fits("photo", k("image", "img2img")), True)
    check("A8 photo inpaint", fits("photo", k("image", "inpaint")), False)
    check("A8 photo video", fits("photo", k("video", "txt2img")), False)
    check("A8 video video", fits("video", k("video", "txt2img")), True)
    check("A8 timevariant ref 0", fits("timevariant", k("image", "img2img", ref=0)), False)
    check("A8 timevariant ref 1", fits("timevariant", k("image", "img2img", ref=1)), True)
    check("A8 mesh_object none", fits("mesh_object", k("mesh", "img2mesh", "none")), True)
    check("A8 mesh_object mesh2mesh", fits("mesh_object", k("mesh", "mesh2mesh", "none")), False)
    check("A8 mesh_object mixamo", fits("mesh_object", k("mesh", "img2mesh", "mixamo")), False)
    check("A8 mesh_humanoid empty rig", fits("mesh_humanoid", k("mesh", "img2mesh", "")), True)
    check("A8 mesh_creature generic", fits("mesh_creature", k("mesh", "img2mesh", "generic")), True)

    check("A9 mixamo", occ.mesh_occasion_for_rig("mixamo"), "mesh_humanoid")
    check("A9 generic", occ.mesh_occasion_for_rig("generic"), "mesh_creature")
    check("A9 none", occ.mesh_occasion_for_rig("none"), "mesh_object")
    check("A9 none building", occ.mesh_occasion_for_rig("none", building=True), "mesh_building")
    check("A9 table", occ.MESH_OCCASIONS_BY_RIG["none"], ("mesh_object", "mesh_building"))

    rows = occ.catalog_payload()
    check("A10 payload order", [r["id"] for r in rows], expected_ids)
    check("A10 payload keys", {tuple(sorted(r)) for r in rows},
          {tuple(sorted(["id", "label", "media", "category", "rig",
                         "character_scoped", "needs_ref_slot", "covers"]))})
    check("A10 labels non-empty", all(isinstance(r["label"], str) and r["label"].strip()
                                      for r in rows), True)


if __name__ == "__main__":
    part_a()
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) failed: {FAILS}")
        sys.exit(1)
    print("all checks passed")
