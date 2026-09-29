#!/usr/bin/env python3
"""Smoke: the image routing config migration (config._migrate_image_routing).

Usage:  ./.venv/bin/python scripts/smoke_image_routing_migration.py

Spec: development_instructions/plan-image-routing.md § 2 + review notes
("Konfiguration + Migration"): the chains come from the old per-occasion
default fields, empty/duplicate entries dropped, a pattern that matches no
backend is kept (the overview marks it), the mesh default goes to the mesh
occasion(s) of the rig its backend has. Pure dict work — no server, no world.

PART A — SEED (phase R1: the old fields stay)
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
A3 fixture C = legacy prefixes (the migration runs BEFORE
   _rewrite_legacy_workflow_specs, so it normalises itself):
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
A7 an existing routing (even {}) is never touched: returns False.
A8 R1: the old fields are STILL THERE after the seed (fixture A keeps
   outfit_imagegen_default == "LocalAI-Flux").
A9 _apply_file_migrations runs it FIRST: its first `if` calls
   _migrate_image_routing (AST), and a full run over fixture C gives the
   routing of A3 (not the post-rewrite values of other steps).
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
    check("A8 R1 keeps the old field", cfg["image_generation"].get("outfit_imagegen_default"),
          "LocalAI-Flux")

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
    check("A7 existing routing untouched", cfgmod._migrate_image_routing(f), False)
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


if __name__ == "__main__":
    part_a()
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) failed: {FAILS}")
        sys.exit(1)
    print("all checks passed")
