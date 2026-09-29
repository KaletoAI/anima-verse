#!/usr/bin/env python3
"""Smoke: the image routing occasion catalog (app/imagegen/occasions.py).

Usage:  ./.venv/bin/python scripts/smoke_image_routing_catalog.py

Spec: development_instructions/plan-image-routing.md § 1 + the binding review
notes ("Katalog (§1)"). No server, no world, no DB — it imports the catalog
module only (Part A); Part B (and C, added later) scan the callers by AST.

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

PART B — THE STRING-PATH CALLERS NAME THEIR OCCASION (AST, no import)
---------------------------------------------------------------------
The caller set is derived from the code itself: every tracked .py file under
app/ and plugins/ (`git ls-files`; the symlinked private packs are not
scanned — known limit) is parsed, and a file is a caller when its AST
references the attribute `.generate_from_input` (a call, or the bound method
handed on, e.g. to `asyncio.to_thread`). A mention in a comment or a
docstring does not count. app/imagegen/service.py DEFINES the façade and is
not a caller of it.
B1. Every function of those files whose own body references
    `.generate_from_input` sets an "occasion" payload key (dict literal key
    or `x["occasion"] = …`); a CONSTANT value must be a catalog occasion.
B2. None of those functions writes a "workflow" payload key any more (the
    soft glob is gone, plan-image-routing.md review "Service-Teilung").
B3. The caller files are exactly EXPECTED_STRING_CALLERS (a new caller must
    be added here consciously, with its occasion):
      plugins/take_photo/skill.py         photo      (TakePhoto)
      plugins/instagram/skill_post.py     instagram  (Instagram post)
      app/core/messaging_frame.py         frame      (no explicit target)
      app/core/story_engine.py            photo      (story beat image)
      app/routes/story.py                 photo      (visualised scene)
      app/skills/video_generation_skill.py photo     (the video's still)
      app/core/character_ops.py           profile    (portrait, editor route)
      app/core/npc_assets.py              profile    (temporary-NPC portrait)
      app/core/expression_regen.py        expression / tpose (variants, model refs)
"""
import os
import subprocess
import sys
from pathlib import Path

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


EXPECTED_STRING_CALLERS = {
    "plugins/take_photo/skill.py",
    "plugins/instagram/skill_post.py",
    "app/core/messaging_frame.py",
    "app/core/story_engine.py",
    "app/routes/story.py",
    "app/skills/video_generation_skill.py",
    "app/core/character_ops.py",
    "app/core/npc_assets.py",
    "app/core/expression_regen.py",
}

ROOT = Path(__file__).resolve().parent.parent
FACADE = "generate_from_input"


def _tracked_py(*paths):
    """Tracked .py files under *paths* (repo-relative), via git ls-files."""
    out = subprocess.run(["git", "ls-files", "--", *paths], cwd=ROOT,
                         capture_output=True, text=True, check=False).stdout
    return [f for f in out.split() if f.endswith(".py")]


def _own_nodes(fn):
    """Nodes of a function body without the bodies of nested defs."""
    import ast
    stack = list(fn.body)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _references_facade(nodes):
    import ast
    return any(isinstance(n, ast.Attribute) and n.attr == FACADE for n in nodes)


def _payload_keys(fn, key):
    """Values written to payload key `key` inside fn: dict-literal entries
    and `x[key] = value` assignments. Returns the value nodes."""
    import ast
    vals = []
    for node in _own_nodes(fn):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == key:
                    vals.append(v)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                        and t.slice.value == key):
                    vals.append(node.value)
    return vals


def part_b():
    import ast
    from app.imagegen.occasions import occasion_ids
    print("B) string-path callers")
    ids = set(occasion_ids())
    trees = {}
    for f in _tracked_py("app", "plugins"):
        if f == "app/imagegen/service.py":
            continue
        tree = ast.parse((ROOT / f).read_text(encoding="utf-8"), filename=f)
        if _references_facade(ast.walk(tree)):
            trees[f] = tree
    files = set(trees)
    check("B3 the caller files", files, EXPECTED_STRING_CALLERS)
    for f in sorted(files):
        for fn in ast.walk(trees[f]):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not _references_facade(_own_nodes(fn)):
                continue
            occ = _payload_keys(fn, "occasion")
            check(f"B1 {f}:{fn.name} sets an occasion", bool(occ), True)
            bad = [v.value for v in occ if isinstance(v, ast.Constant) and v.value not in ids]
            check(f"B1 {f}:{fn.name} occasions are in the catalog", bad, [])
            check(f"B2 {f}:{fn.name} writes no workflow key",
                  len(_payload_keys(fn, "workflow")), 0)


if __name__ == "__main__":
    part_a()
    part_b()
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) failed: {FAILS}")
        sys.exit(1)
    print("all checks passed")
