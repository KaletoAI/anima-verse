#!/usr/bin/env python3
"""Smoke: the image routing occasion catalog (app/imagegen/occasions.py).

Usage:  ./.venv/bin/python scripts/smoke_image_routing_catalog.py

Spec: development_instructions/plan-image-routing.md § 1 + the binding review
notes ("Katalog (§1)"). No server, no world, no DB — it imports the catalog
module only (Part A); Parts B and C scan the callers by AST / text.

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
    An empty rig is "mixamo" (the backend default) -> mesh_humanoid; a rig
    the catalog does not know ("bogus") raises UnknownOccasionError (Task 1
    review carry-over: guessing mesh_humanoid for it would mesh with a
    skeleton nobody asked for). Fails on commit 4893221f, which answered
    "mesh_humanoid" for "bogus".
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
B3. The caller files are exactly the keys of EXPECTED_STRING_CALLERS (a new
    caller must be added here consciously, with its occasion):
      plugins/take_photo/skill.py         photo      (TakePhoto)
      plugins/instagram/skill_post.py     instagram  (Instagram post)
      app/core/messaging_frame.py         frame      (set only in the branch
                                                      without an explicit target;
                                                      a target is an explicit pick)
      app/core/story_engine.py            photo      (story beat image)
      app/routes/story.py                 photo      (visualised scene)
      app/skills/video_generation_skill.py photo     (the video's still)
      app/core/character_ops.py           profile    (portrait, editor route)
      app/core/npc_assets.py              profile    (temporary-NPC portrait)
      app/core/expression_regen.py        COMPUTED   (expression, or tpose for the
                                                      T-pose use cases / model refs)
B4. Per file, the constant occasions its facade callers write are exactly
    {its occasion} from the table; a COMPUTED file writes no constant and at
    least one computed value (a later constant there would bypass the
    use-case split).

PART C — every direct caller + every meta writer (AST / git grep, no import)
------------------------------------------------------------------------
C1. Every `run_routed(` / `resolve_image_route(` call in app/ + plugins/
    (also `asyncio.to_thread(run_routed, "<occasion>", …)`) names a CATALOG
    occasion as a constant first argument — except the functions that take
    the occasion as a parameter and hand it through (DYNAMIC_OK below).
C2. Nothing in app/, plugins/, frontend/src, static/admin reads a removed key
    any more: "_IMAGEGEN_DEFAULT", "imagegen_default", "messaging_frame.target",
    "imagegen_backend", "imagegen_model", "animate_service" (the migration
    table in app/core/config.py names the old dotted fields as its SOURCES
    and is exempt). The quoted forms are searched where the bare word also
    names something that stays (`imagegen_backend_models`,
    `list_animate_services`); `"type": "imagegen_model"` in
    app/core/config_schema.py is the widget type of a backend's model field,
    not the removed per-character skill field, and is exempt.
C2b. (binding review C1) The four request handlers that used to pass a
    request-body "workflow" on as an image soft glob no longer do:
    app/routes/world.py, app/core/world_ops.py, app/routes/instagram.py,
    app/routes/characters.py contain no `<data|body|payload>.get("workflow")`,
    no `<data|body|payload>["workflow"]` (read or write), no name
    `workflow_name` and no `resolve_imagegen_target(` call. The character's
    OWN stored glob (`outfit_imagegen.workflow`, edited via
    `override.get("workflow")` in characters.py) is position 0 of the chain
    and stays. Proof the check bites: run on app/routes/world.py of commit
    860a57de^ (before the gallery was routed) it finds
    `data.get("workflow")` and `body["workflow"]` (>= 2 hits).
C3. Every meta writer of the spec's review list either calls route_meta( or
    copies the routing fields (the string literal "fallback_from" in its
    code) — by AST, so a comment or docstring does not count:
    service.py, expression_regen.py, world_ops.py, image_regenerate.py,
    describe_room_skill.py, routes/inventory.py, surface_textures.py,
    props.py, model3d.py, location_model3d.py, video_generation_skill.py,
    routes/instagram.py, scene_render.py, event_images.py.
    DOCUMENTED EXCEPTION: app/core/surface_textures.py is NOT routed yet —
    another session holds an uncommitted change in that file, so its routing
    (plan Task 13) is deferred rather than merged into foreign work. It is
    reported as DEFERRED, not skipped silently, and the check FAILS once the
    file writes the routing record, so the exception is removed with it.
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
    check("A9 empty rig = mixamo", occ.mesh_occasion_for_rig(""), "mesh_humanoid")
    try:
        got = occ.mesh_occasion_for_rig("bogus")
        check("A9 unknown rig raises", got, "UnknownOccasionError")
    except occ.UnknownOccasionError:
        check("A9 unknown rig raises", "UnknownOccasionError", "UnknownOccasionError")

    rows = occ.catalog_payload()
    check("A10 payload order", [r["id"] for r in rows], expected_ids)
    check("A10 payload keys", {tuple(sorted(r)) for r in rows},
          {tuple(sorted(["id", "label", "media", "category", "rig",
                         "character_scoped", "needs_ref_slot", "covers"]))})
    check("A10 labels non-empty", all(isinstance(r["label"], str) and r["label"].strip()
                                      for r in rows), True)


# file -> its constant occasion; None = computed at run time (see B4).
EXPECTED_STRING_CALLERS = {
    "plugins/take_photo/skill.py": "photo",
    "plugins/instagram/skill_post.py": "instagram",
    "app/core/messaging_frame.py": "frame",
    "app/core/story_engine.py": "photo",
    "app/routes/story.py": "photo",
    "app/skills/video_generation_skill.py": "photo",
    "app/core/character_ops.py": "profile",
    "app/core/npc_assets.py": "profile",
    "app/core/expression_regen.py": None,
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
    check("B3 the caller files", files, set(EXPECTED_STRING_CALLERS))
    for f in sorted(files):
        consts, computed = set(), 0
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
            for v in occ:
                if isinstance(v, ast.Constant):
                    consts.add(v.value)
                else:
                    computed += 1
        want = EXPECTED_STRING_CALLERS.get(f, "")
        if want is None:
            check(f"B4 {f} computes its occasion", (consts, computed > 0), (set(), True))
        else:
            check(f"B4 {f} occasion", consts, {want})


DYNAMIC_OK = {
    ("app/imagegen/service.py", "generate_from_input"),
    ("app/imagegen/service.py", "generate_video"),
    ("app/imagegen/service.py", "generate_mesh"),
    ("app/skills/image_regenerate.py", "regenerate_image"),
    ("app/imagegen/routing.py", "run_routed"),
}
META_WRITERS = [
    "app/imagegen/service.py", "app/core/expression_regen.py", "app/core/world_ops.py",
    "app/skills/image_regenerate.py", "app/skills/describe_room_skill.py",
    "app/routes/inventory.py", "app/core/surface_textures.py", "app/core/props.py",
    "app/core/model3d.py", "app/core/location_model3d.py",
    "app/skills/video_generation_skill.py", "app/routes/instagram.py",
    "app/core/scene_render.py", "app/core/event_images.py",
]
# Meta writers whose routing is deferred, with the reason (C3).
DEFERRED_META_WRITERS = {
    "app/core/surface_textures.py":
        "not routed yet: another session holds an uncommitted change in the "
        "file, so plan Task 13 waits instead of merging into foreign work",
}
# Quoted where the bare word also names something that stays
# (`imagegen_backend_models`, `list_animate_services`).
REMOVED = ["_IMAGEGEN_DEFAULT", "imagegen_default", "messaging_frame.target",
           '"imagegen_backend"', '"imagegen_model"', '"animate_service"']
# (file, line text) pairs that match REMOVED but name something that stays.
REMOVED_EXEMPT = [
    ("app/core/config_schema.py", '"type": "imagegen_model"'),
]
SOFT_GLOB_FILES = ["app/routes/world.py", "app/core/world_ops.py",
                   "app/routes/instagram.py", "app/routes/characters.py"]
_BODY_NAMES = {"data", "body", "payload"}


def _soft_glob_reads(source):
    """C2b: request-body "workflow" reads/writes and the old resolver in
    *source*. Returns a list of short descriptions (empty = clean)."""
    import ast
    hits = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and isinstance(node.func.value, ast.Name)
                and node.func.value.id in _BODY_NAMES and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "workflow"):
            hits.append(f'{node.func.value.id}.get("workflow") line {node.lineno}')
        elif (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
              and node.value.id in _BODY_NAMES and isinstance(node.slice, ast.Constant)
              and node.slice.value == "workflow"):
            hits.append(f'{node.value.id}["workflow"] line {node.lineno}')
        elif isinstance(node, ast.Name) and node.id == "workflow_name":
            hits.append(f"workflow_name line {node.lineno}")
        elif isinstance(node, ast.arg) and node.arg == "workflow_name":
            hits.append(f"workflow_name parameter line {node.lineno}")
        elif (isinstance(node, ast.Call)
              and getattr(node.func, "attr", getattr(node.func, "id", ""))
              == "resolve_imagegen_target"):
            hits.append(f"resolve_imagegen_target( line {node.lineno}")
    return hits


def _writes_routing_record(tree):
    """C3 by AST: a call of `route_meta(...)` or the string literal
    "fallback_from" in code (a comment never counts, and a docstring is never
    exactly that string)."""
    import ast
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "id", getattr(node.func, "attr", "")) == "route_meta"):
            return True
        if isinstance(node, ast.Constant) and node.value == "fallback_from":
            return True
    return False


def part_c():
    import ast
    from app.imagegen.occasions import occasion_ids
    print("C) direct callers + meta writers")
    ids = set(occasion_ids())
    n_calls = 0
    for f in _tracked_py("app", "plugins"):
        text = (ROOT / f).read_text(encoding="utf-8")
        if "run_routed" not in text and "resolve_image_route(" not in text:
            continue
        tree = ast.parse(text, filename=f)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in _own_nodes(fn):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "id", getattr(node.func, "attr", ""))
                if name in ("run_routed", "resolve_image_route"):
                    arg = node.args[0] if node.args else None
                elif (node.args and isinstance(node.args[0], ast.Name)
                      and node.args[0].id == "run_routed"):
                    # asyncio.to_thread(run_routed, "<occasion>", render, …)
                    arg = node.args[1] if len(node.args) > 1 else None
                else:
                    continue
                n_calls += 1
                if isinstance(arg, ast.Constant):
                    check(f"C1 {f}:{fn.name} -> {arg.value}", arg.value in ids, True)
                else:
                    check(f"C1 {f}:{fn.name} passes a variable occasion",
                          (f, fn.name) in DYNAMIC_OK, True)
    # Counted by hand at Task 19: 8 constant call sites (event, prop,
    # scene_view, 3x world_ops, item, describe_room) plus 6 dynamic
    # hand-throughs — the scan must not quietly come back (nearly) empty.
    check("C1 the scan found the routed callers (>= 10)", n_calls >= 10, True)

    cmd = ["git", "grep", "-n", "-F"]
    for r in REMOVED:
        cmd += ["-e", r]
    cmd += ["--", "app", "plugins", "frontend/src", "static/admin",
            ":!app/core/config.py"]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True).stdout
    left = [ln for ln in out.splitlines()
            if not any(ln.startswith(f + ":") and frag in ln
                       for f, frag in REMOVED_EXEMPT)]
    check("C2 no reader of a removed key", left, [])

    for f in SOFT_GLOB_FILES:
        check(f"C2b {f} reads no request-body workflow glob",
              _soft_glob_reads((ROOT / f).read_text(encoding="utf-8")), [])
    old = subprocess.run(["git", "show", "860a57de^:app/routes/world.py"], cwd=ROOT,
                         capture_output=True, text=True).stdout
    check("C2b proof: the check finds the old gallery soft glob (>= 2)",
          len(_soft_glob_reads(old)) >= 2, True)

    for f in META_WRITERS:
        writes = _writes_routing_record(
            ast.parse((ROOT / f).read_text(encoding="utf-8"), filename=f))
        if f in DEFERRED_META_WRITERS:
            print(f"  DEFERRED {f}: {DEFERRED_META_WRITERS[f]}")
            check(f"C3 {f} still deferred (drop the exception once routed)",
                  writes, False)
            continue
        check(f"C3 {f} writes the routing record", writes, True)


if __name__ == "__main__":
    part_a()
    part_b()
    part_c()
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) failed: {FAILS}")
        sys.exit(1)
    print("all checks passed")
