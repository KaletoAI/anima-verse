#!/usr/bin/env python3
"""Smoke: the image routing config migration (config._migrate_image_routing).

Usage:  ./.venv/bin/python scripts/smoke_image_routing_migration.py

Spec: development_instructions/plan-image-routing.md § 2 + review notes
("Konfiguration + Migration"): the chains come from the old per-occasion
default fields, empty/duplicate entries dropped, a pattern that matches no
backend is kept (the overview marks it), the mesh default goes to the mesh
occasion(s) of the rig its backend has. Pure dict work — no server, no world.

PART A — SEED
Mapping (§ 2, with the review's frame/photo correction):
  profile     <- [profile]
  expression  <- [expression, outfit]      tpose <- [expression, outfit]
  location    <- [location]                timevariant <- [timevariant]
  prop        <- [prop]
  scene_view  <- [scene, location]
  event       <- [random_events.event, scene, location]
  photo       <- [story_engine.imagegen_default]
  frame       <- [messaging_frame.target]
  instagram   <- [skills.instagram.imagegen_default]
  mesh        -> rig of the matched img2mesh backend: mixamo -> mesh_humanoid,
                 generic -> mesh_creature, none -> mesh_object AND mesh_building;
                 matches no img2mesh backend -> dropped (warning)
  empty chains are not written; `routing` itself is always written (marker).

A1 fixture A = the demo world's values (worlds/demo/config.json, 2026-09-29):
   outfit/expression/location = "LocalAI-Flux", nothing else set ->
   {"expression": ["LocalAI-Flux"], "tpose": ["LocalAI-Flux"],
    "location": ["LocalAI-Flux"], "scene_view": ["LocalAI-Flux"],
    "event": ["LocalAI-Flux"]}   (dedup: expression+outfit are one entry)
A2 fixture B = a real world's values (2026-09-29, world name withheld):
   profile/outfit/expression "Qwen2.1*T*", location "Flux2*",
   prop "Flux2*Normal", scene "Qwen BL", timevariant "Qwen 2511" (matches
   NO backend — kept), mesh "Trellis2-Object-Low" (img2mesh rig none),
   event "Flux*", messaging_frame.target "Flux2*" ->
   {"profile": ["Qwen2.1*T*"], "expression": ["Qwen2.1*T*"],
    "tpose": ["Qwen2.1*T*"], "location": ["Flux2*"],
    "timevariant": ["Qwen 2511"], "prop": ["Flux2*Normal"],
    "scene_view": ["Qwen BL", "Flux2*"], "event": ["Flux*", "Qwen BL", "Flux2*"],
    "frame": ["Flux2*"], "mesh_object": ["Trellis2-Object-Low"],
    "mesh_building": ["Trellis2-Object-Low"]}
A3 fixture C = legacy prefixes (the migration normalises them itself):
   outfit/expression/location "workflow:Z-Image*", event "workflow:",
   story "backend:CivitAI-General", instagram "workflow:Qwen*",
   frame "workflow:Z-Image" ->
   {"expression": ["Z-Image*"], "tpose": ["Z-Image*"], "location": ["Z-Image*"],
    "scene_view": ["Z-Image*"], "event": ["Z-Image*"],
    "photo": ["CivitAI-General"], "instagram": ["Qwen*"], "frame": ["Z-Image"]}
A4 mesh "Nope*" matches no img2mesh backend -> no mesh key at all.
A5 mesh "Mesh*" over {Mesh-Humanoid mixamo, Mesh-Creature generic,
   Mesh-Shrink mesh2mesh none} -> mesh_humanoid AND mesh_creature
   ["Mesh*"]; the mesh2mesh alias does not make it an object chain.
A6 returns True on the first run, False on the second, dict unchanged.
A7 an existing routing (even {}) is never touched (still {}); it returns
   True only because the old field next to it is removed (Part B).
A9 _apply_file_migrations runs it FIRST: its first `if` calls
   _migrate_image_routing (AST), and a full run over fixture C gives the
   routing of A3 (not the post-rewrite values of other steps).

PART B — MIGRATION (phase R2b: the old fields are removed by the same step)
B1 fixture A: after the migration none of the old keys is left:
   image_generation.{profile,outfit,expression,location,prop,scene,mesh,
   timevariant}_imagegen_default, random_events.event_imagegen_default,
   story_engine.imagegen_default, skills.instagram.imagegen_default,
   messaging_frame.target — the chains are those of A1; the sections'
   OTHER keys stay (messaging_frame.prompt).
B2 an ALREADY seeded config (routing {"photo": ["X"]} + outfit default "Y" +
   story_engine {imagegen_default "Z", enabled true}) -> True, routing
   unchanged, both old keys gone, story_engine.enabled still true; a second
   run -> False.
B3 the env bridge (`_flatten_to_env`, AST) sets none of PROFILE_, OUTFIT_,
   EXPRESSION_, LOCATION_, TIMEVARIANT_, PROP_IMAGEGEN_DEFAULT,
   EVENT_IMAGEGEN_DEFAULT, STORY_ENGINE_IMAGEGEN_DEFAULT.
B4 LEGACY_SPEC_FIELDS and _rewrite_legacy_workflow_specs are gone (every
   field they covered is removed).
B5 the TRACKED demo config (worlds/demo/config.json) holds the A1 chains
   and none of the old keys.
B6 the admin schema declares none of the removed fields, and the
   instagram plugin.yaml has no imagegen_default.

PART C — one kind source for config entries (Task 18a, from the Task 17
review): `routing.describe_config_backend` trims + lower-cases `category`
and `mesh_rig` like the live backend does (`ImageBackend.category`,
`OpenAIMeshBackend.mesh_rig` = strip().lower(), blank = "mixamo").
C1 {"api_type": "openai_mesh", "mesh_rig": "None ", "category": " IMG2MESH "}
   -> rig "none", category "img2mesh"; mesh_rig "  " -> rig "mixamo".
C2 mesh default "Obj*" over {Obj-A: rig "none ", img2mesh} -> routing
   {"mesh_object": ["Obj*"], "mesh_building": ["Obj*"]} (before: rig
   "none " is no rig the catalog knows -> the default was dropped).
   Mesh default "Obj*" over {Obj-H: rig "mixamo", Obj-Shrink: rig "none",
   category "mesh2mesh "} -> {"mesh_humanoid": ["Obj*"]} only (before: the
   shrink alias with a trailing space counted as img2mesh and added the
   object + building chains).
C3 `_seed_default_mesh_backends` recognises a mesh backend by
   describe_config_backend(...)["media"] == "mesh": a config whose only
   backend has api_type " OpenAI_Mesh " (resolves to the mesh class) ->
   False, nothing appended; a config with only an image backend -> True,
   the default catalog appended.
C4 (fix round 1) the live mesh backend reads its rig like C1: an
   OpenAIMeshBackend with MESH_RIG "  " has mesh_rig "mixamo" (was "" —
   blank after the strip), MESH_RIG " None " -> "none".
Fails on commit 4eb1856e (before Task 18a): C1 (untrimmed), both C2 cases
and the first C3 case (the api_type comparison seeds a second catalog).
Fails on commit d0452bc6 (before fix round 1): C4 (mesh_rig "" for "  ").
"""
import ast
import copy
import inspect
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ANIMATION_CLIPS_DIR", tempfile.mkdtemp(prefix="routing-mig-clips-"))
from app.core import paths  # noqa: E402
paths.init(tempfile.mkdtemp(prefix="routing-mig-storage-"))
from app.core import config as cfgmod  # noqa: E402

FAILS = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILS.append(label)


def mesh(name, rig, category="img2mesh"):
    return {"name": name, "api_type": "openai_mesh", "category": category,
            "mesh_rig": rig, "enabled": True}


def img(name, category="img2img"):
    return {"name": name, "api_type": "openai_diffusion", "category": category,
            "enabled": True}


FIXTURE_A = {"image_generation": {
    "outfit_imagegen_default": "LocalAI-Flux",
    "expression_imagegen_default": "LocalAI-Flux",
    "location_imagegen_default": "LocalAI-Flux",
    "backends": [{"name": "LocalAI-Flux", "api_type": "localai", "enabled": True},
                 {"name": "LocalAI-ZImage", "api_type": "localai", "enabled": True}]},
    "random_events": {"enabled": True}, "story_engine": {"enabled": True},
    "skills": {"instagram": {"enabled": True}},
    "messaging_frame": {"prompt": "a phone"}}

FIXTURE_B = {"image_generation": {
    "profile_imagegen_default": "Qwen2.1*T*",
    "outfit_imagegen_default": "Qwen2.1*T*",
    "expression_imagegen_default": "Qwen2.1*T*",
    "location_imagegen_default": "Flux2*",
    "prop_imagegen_default": "Flux2*Normal",
    "scene_imagegen_default": "Qwen BL",
    "mesh_imagegen_default": "Trellis2-Object-Low",
    "timevariant_imagegen_default": "Qwen 2511",
    "backends": [mesh("Trellis2-Humanoid-Low", "mixamo"),
                 mesh("Trellis2-Object-Low", "none"),
                 mesh("mesh-shrink", "none", "mesh2mesh"),
                 img("Qwen2.1 Turbo"), img("Qwen BL"), img("Flux2-9B Normal"),
                 img("Flux1-Dev Inpaint", "inpaint")]},
    "random_events": {"event_imagegen_default": "Flux*"},
    "messaging_frame": {"target": "Flux2*"}}

FIXTURE_C = {"image_generation": {
    "outfit_imagegen_default": "workflow:Z-Image*",
    "expression_imagegen_default": "workflow:Z-Image*",
    "location_imagegen_default": "workflow:Z-Image*",
    "backends": []},
    "random_events": {"event_imagegen_default": "workflow:"},
    "story_engine": {"imagegen_default": "backend:CivitAI-General"},
    "skills": {"instagram": {"imagegen_default": "workflow:Qwen*"}},
    "messaging_frame": {"target": "workflow:Z-Image"}}


def seeded(fixture):
    cfg = copy.deepcopy(fixture)
    changed = cfgmod._migrate_image_routing(cfg)
    return changed, cfg


def part_a():
    print("A) seed")
    ch, cfg = seeded(FIXTURE_A)
    check("A1 demo values", cfg["image_generation"]["routing"],
          {"expression": ["LocalAI-Flux"], "tpose": ["LocalAI-Flux"],
           "location": ["LocalAI-Flux"], "scene_view": ["LocalAI-Flux"],
           "event": ["LocalAI-Flux"]})
    check("A6 first run changed", ch, True)
    again = copy.deepcopy(cfg)
    check("A6 second run no change", cfgmod._migrate_image_routing(again), False)
    check("A6 second run leaves the dict", again, cfg)

    _ch, cfg = seeded(FIXTURE_B)
    check("A2 real-world values", cfg["image_generation"]["routing"],
          {"profile": ["Qwen2.1*T*"], "expression": ["Qwen2.1*T*"],
           "tpose": ["Qwen2.1*T*"], "location": ["Flux2*"],
           "timevariant": ["Qwen 2511"], "prop": ["Flux2*Normal"],
           "scene_view": ["Qwen BL", "Flux2*"],
           "event": ["Flux*", "Qwen BL", "Flux2*"], "frame": ["Flux2*"],
           "mesh_object": ["Trellis2-Object-Low"],
           "mesh_building": ["Trellis2-Object-Low"]})

    _ch, cfg = seeded(FIXTURE_C)
    check("A3 legacy prefixes", cfg["image_generation"]["routing"],
          {"expression": ["Z-Image*"], "tpose": ["Z-Image*"], "location": ["Z-Image*"],
           "scene_view": ["Z-Image*"], "event": ["Z-Image*"],
           "photo": ["CivitAI-General"], "instagram": ["Qwen*"], "frame": ["Z-Image"]})

    d = copy.deepcopy(FIXTURE_B)
    d["image_generation"]["mesh_imagegen_default"] = "Nope*"
    cfgmod._migrate_image_routing(d)
    check("A4 unmatched mesh default dropped",
          sorted(k for k in d["image_generation"]["routing"] if k.startswith("mesh_")), [])

    e = {"image_generation": {"mesh_imagegen_default": "Mesh*", "backends": [
        mesh("Mesh-Humanoid", "mixamo"), mesh("Mesh-Creature", "generic"),
        mesh("Mesh-Shrink", "none", "mesh2mesh")]}}
    cfgmod._migrate_image_routing(e)
    check("A5 mesh rigs", e["image_generation"]["routing"],
          {"mesh_humanoid": ["Mesh*"], "mesh_creature": ["Mesh*"]})

    f = {"image_generation": {"routing": {}, "outfit_imagegen_default": "X"}}
    check("A7 existing routing: only the old field removed", cfgmod._migrate_image_routing(f), True)
    check("A7 still empty", f["image_generation"]["routing"], {})

    src = inspect.getsource(cfgmod._apply_file_migrations)
    fn = ast.parse(src).body[0]
    first_if = next(n for n in fn.body if isinstance(n, ast.If))
    call = first_if.test
    check("A9 first step", isinstance(call, ast.Call) and getattr(call.func, "id", ""),
          "_migrate_image_routing")
    full = copy.deepcopy(FIXTURE_C)
    cfgmod._apply_file_migrations(full, False)
    check("A9 full run keeps the seeded chains",
          full["image_generation"]["routing"]["photo"], ["CivitAI-General"])


OLD_KEYS = ["image_generation.profile_imagegen_default", "image_generation.outfit_imagegen_default",
            "image_generation.expression_imagegen_default", "image_generation.location_imagegen_default",
            "image_generation.prop_imagegen_default", "image_generation.scene_imagegen_default",
            "image_generation.mesh_imagegen_default", "image_generation.timevariant_imagegen_default",
            "random_events.event_imagegen_default", "story_engine.imagegen_default",
            "skills.instagram.imagegen_default", "messaging_frame.target"]


def _has(cfg, dotted):
    node = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def part_b():
    import json as _json
    print("B) migration")
    cfg = copy.deepcopy(FIXTURE_A)
    cfg["messaging_frame"]["target"] = "LocalAI-Flux"
    cfgmod._migrate_image_routing(cfg)
    check("B1 old keys gone", [k for k in OLD_KEYS if _has(cfg, k)], [])
    check("B1 other keys stay", cfg["messaging_frame"].get("prompt"), "a phone")

    seeded_cfg = {"image_generation": {"routing": {"photo": ["X"]},
                                       "outfit_imagegen_default": "Y"},
                  "story_engine": {"imagegen_default": "Z", "enabled": True}}
    check("B2 changed", cfgmod._migrate_image_routing(seeded_cfg), True)
    check("B2 routing kept", seeded_cfg["image_generation"]["routing"], {"photo": ["X"]})
    check("B2 old keys gone", [k for k in OLD_KEYS if _has(seeded_cfg, k)], [])
    check("B2 enabled kept", seeded_cfg["story_engine"].get("enabled"), True)
    check("B2 second run", cfgmod._migrate_image_routing(seeded_cfg), False)

    src = inspect.getsource(cfgmod._flatten_to_env)
    bridged = [n for n in ("PROFILE_IMAGEGEN_DEFAULT", "OUTFIT_IMAGEGEN_DEFAULT",
                           "EXPRESSION_IMAGEGEN_DEFAULT", "LOCATION_IMAGEGEN_DEFAULT",
                           "TIMEVARIANT_IMAGEGEN_DEFAULT", "PROP_IMAGEGEN_DEFAULT",
                           "EVENT_IMAGEGEN_DEFAULT", "STORY_ENGINE_IMAGEGEN_DEFAULT")
               if n in src]
    check("B3 no default bridge", bridged, [])
    check("B4 legacy rewrite gone", (hasattr(cfgmod, "LEGACY_SPEC_FIELDS"),
                                     hasattr(cfgmod, "_rewrite_legacy_workflow_specs")),
          (False, False))

    demo = _json.loads((Path(__file__).resolve().parent.parent / "worlds" / "demo"
                        / "config.json").read_text(encoding="utf-8"))
    check("B5 demo chains", demo["image_generation"].get("routing"),
          {"expression": ["LocalAI-Flux"], "tpose": ["LocalAI-Flux"],
           "location": ["LocalAI-Flux"], "scene_view": ["LocalAI-Flux"],
           "event": ["LocalAI-Flux"]})
    check("B5 demo old keys", [k for k in OLD_KEYS if _has(demo, k)], [])

    from app.core.config_schema import get_schema
    sch = get_schema()
    ig_fields = set((sch.get("image_generation") or {}).get("fields", {}))
    check("B6 image_generation fields", sorted(ig_fields & {k.split(".")[1] for k in OLD_KEYS[:8]}), [])
    check("B6 event field", "event_imagegen_default" in
          (sch.get("random_events") or {}).get("fields", {}), False)
    check("B6 story field", "imagegen_default" in (sch.get("story_engine") or {}).get("fields", {}), False)
    check("B6 frame target", "target" in (sch.get("messaging_frame") or {}).get("fields", {}), False)
    yml = (Path(__file__).resolve().parent.parent / "plugins" / "instagram" / "plugin.yaml").read_text(
        encoding="utf-8")
    check("B6 instagram yaml", "imagegen_default" in yml, False)


def part_c():
    print("C) one kind source for config entries")
    from app.imagegen.routing import describe_config_backend
    k = describe_config_backend({"name": "M", "api_type": "openai_mesh",
                                 "mesh_rig": "None ", "category": " IMG2MESH "})
    check("C1 trimmed", (k["media"], k["rig"], k["category"]), ("mesh", "none", "img2mesh"))
    k = describe_config_backend({"name": "M", "api_type": "openai_mesh", "mesh_rig": "  "})
    check("C1 blank rig", k["rig"], "mixamo")
    c = {"image_generation": {"mesh_imagegen_default": "Obj*", "backends": [
        mesh("Obj-A", "none ")]}}
    cfgmod._migrate_image_routing(c)
    check("C2 rig with a trailing space migrates", c["image_generation"]["routing"],
          {"mesh_object": ["Obj*"], "mesh_building": ["Obj*"]})
    c = {"image_generation": {"mesh_imagegen_default": "Obj*", "backends": [
        mesh("Obj-H", "mixamo"), mesh("Obj-Shrink", "none", "mesh2mesh ")]}}
    cfgmod._migrate_image_routing(c)
    check("C2 mesh2mesh with a trailing space never counts", c["image_generation"]["routing"],
          {"mesh_humanoid": ["Obj*"]})
    c = {"image_generation": {"backends": [
        {"name": "Mx", "api_type": " OpenAI_Mesh ", "enabled": True}]}}
    check("C3 mesh recognised by kind", (cfgmod._seed_default_mesh_backends(c),
                                         len(c["image_generation"]["backends"])), (False, 1))
    c = {"image_generation": {"backends": [img("Flux")]}}
    check("C3 image-only config seeded", (cfgmod._seed_default_mesh_backends(c),
                                          len(c["image_generation"]["backends"]) > 1),
          (True, True))

    from app.imagegen.backends.openai_mesh import OpenAIMeshBackend
    rigs = []
    for raw in ("  ", " None "):
        os.environ["SMOKE_RIG_MESH_RIG"] = raw
        rigs.append(OpenAIMeshBackend(name="R", api_url="http://mesh.invalid", cost=1,
                                      env_prefix="SMOKE_RIG_", model="R").mesh_rig)
    del os.environ["SMOKE_RIG_MESH_RIG"]
    check("C4 live rig reading", rigs, ["mixamo", "none"])


if __name__ == "__main__":
    part_a()
    part_b()
    part_c()
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) failed: {FAILS}")
        sys.exit(1)
    print("all checks passed")
