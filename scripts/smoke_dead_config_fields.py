#!/usr/bin/env python3
"""Smoke run for the dead-config-field strip (Config-Altlasten, part A).

No world, no DB: a hand-built config dict goes into
``config._strip_dead_config_fields`` against a temp file, and the admin
schema prefill runs on an empty dict.

The fixture is the table of the 17 fields from the finding — written out by
hand here, so the constant in app/core/config.py cannot quietly grow or
shrink without this file disagreeing:

    image_generation : comfy_default_workflow, comfyui_workflows,
                       mapfit_backend, mapfit_workflow_file,
                       mapfit_imagegen_default, map_image_prompt_suffix,
                       map_tile_vision_analysis, unet_weight_dtype,
                       scene_prompt_collage
    chat             : auto_wake_stamina
    inventory        : item_image_width, item_image_height
    random_events    : event_image_denoise_strength
    game             : backdrop_enabled, backdrop_arc, backdrop_height_m,
                       backdrop_seed

The four ``game.backdrop_*`` entries joined on 2026-08-16, when the far
backdrop was removed after crashing at runtime. They are the first dead
fields the strip has to catch that were LIVE settings a moment ago, so test 6
carries real weight for them: the schema entries have to be gone too, or
every admin save would seed them straight back in.

The fields live at TWO depths: normally inside their section, but worlds older
than the sectioning (worlds/demo, worlds/hotopia) carry
``item_image_width``/``item_image_height`` at the top level and have no
``inventory`` section at all — test 5 is the hand case for that.

The point of the file is the pair of counter-checks:
  * the LIVING neighbours of the dead fields survive — most sharply
    ``scene_prompt_collage`` falls while ``scene_prompt_multi_ref`` and
    ``scene_prompt_only_background`` (read in app/core/scene_render.py) stay,
    and a living TOP-LEVEL key (``log_level``) is not caught by the flat sweep;
  * the seeding source is really gone — the two fields that used to reappear
    in freshly created worlds (``mapfit_imagegen_default`` /
    ``map_tile_vision_analysis``) came from schema entries in
    app/core/config_schema.py that ``_apply_schema_defaults``
    (app/routes/admin_settings.py) materializes into config.json on every
    admin save round-trip. Test 6 shows today's schema produces neither;
    test 7 puts the two removed schema entries back and shows the SAME call
    then does produce them — without that red run, test 6 would pass on any
    broken assertion.

Usage:  ./.venv/bin/python scripts/smoke_dead_config_fields.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Point the storage root at a throwaway directory BEFORE any app import.
# paths.init() falls back to ./worlds/demo when STORAGE_DIR is unset (see
# app/core/paths.py) and get_storage_dir() auto-initializes on first call —
# so an import that touches config/paths at module level would write into the
# tracked demo world. Same reflex as ANIMATION_CLIPS_DIR in the 3D smokes.
_TMP_STORAGE = tempfile.TemporaryDirectory(prefix="smoke_dead_config_")
os.environ.setdefault("STORAGE_DIR", _TMP_STORAGE.name)

from app.core import config as cfgmod  # noqa: E402

FAILURES = []

# The finding's table, by hand.
EXPECTED_DEAD = {
    "image_generation": {
        "comfy_default_workflow",
        "comfyui_workflows",
        "mapfit_backend",
        "mapfit_workflow_file",
        "mapfit_imagegen_default",
        "map_image_prompt_suffix",
        "map_tile_vision_analysis",
        "unet_weight_dtype",
        "scene_prompt_collage",
    },
    "chat": {"auto_wake_stamina"},
    "inventory": {"item_image_width", "item_image_height"},
    "random_events": {"event_image_denoise_strength"},
    "game": {"backdrop_enabled", "backdrop_arc", "backdrop_height_m",
             "backdrop_seed"},
}

# Living neighbours that must survive the strip untouched.
LIVING = {
    "image_generation": {
        "scene_prompt_multi_ref": "multi ref prompt",       # scene_render.py
        "scene_prompt_only_background": "bg only prompt",   # scene_render.py
        "backends": [{"name": "gpu-a", "enabled": True}],
        "lora_triggers": [],
    },
    "chat": {"context_messages": 20},
    "inventory": {"max_items": 50},
    "random_events": {"enabled": True},
    "ui": {"downscale_item_max_dim": 768},                  # image_postprocess.py
    # The two walk limits are the sharpest neighbours of the dead backdrop
    # keys: same section, and they DO still travel in the worldmap payload.
    "game": {"max_step_height_m": 0.4, "max_slope_deg": 40.0},
}


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILURES.append(msg)


def build_fixture() -> dict:
    """A world config carrying all 17 dead fields plus living neighbours."""
    cfg = copy.deepcopy(LIVING)
    dead_values = {
        "comfy_default_workflow": "flux.json",
        "comfyui_workflows": ["a.json", "b.json"],
        "mapfit_backend": "comfy-1",
        "mapfit_workflow_file": "mapfit.json",
        "mapfit_imagegen_default": "",
        "map_image_prompt_suffix": ", seamless tile",
        "map_tile_vision_analysis": False,
        "unet_weight_dtype": "fp8_e4m3fn",
        "scene_prompt_collage": "collage prompt",
        "auto_wake_stamina": 40,
        "item_image_width": 512,
        "item_image_height": 512,
        "event_image_denoise_strength": 0.6,
        "backdrop_enabled": True,
        "backdrop_arc": "N,NE",
        "backdrop_height_m": 120.0,
        "backdrop_seed": 1,
    }
    for section, keys in EXPECTED_DEAD.items():
        for key in keys:
            cfg[section][key] = dead_values[key]
    return cfg


def main():
    print("1) the constant matches the finding's table")
    actual = {s: set(k) for s, k in cfgmod.DEAD_CONFIG_FIELDS.items()}
    check(actual == EXPECTED_DEAD,
          f"DEAD_CONFIG_FIELDS == 17 fields of the table (got {actual})")
    check(sum(len(v) for v in actual.values()) == 17,
          "17 fields in total")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"

        print("2) the strip removes exactly the 17 and persists")
        cfg = build_fixture()
        changed = cfgmod._strip_dead_config_fields(cfg, path)
        check(changed is True, "returns True on the first run")
        check(path.exists(), "config.json written")
        left = {s: sorted(k for k in EXPECTED_DEAD[s] if k in cfg.get(s, {}))
                for s in EXPECTED_DEAD}
        check(all(not v for v in left.values()),
              f"no dead field left in the dict (leftovers: {left})")
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        left_disk = [k for s, keys in EXPECTED_DEAD.items()
                     for k in keys if k in on_disk.get(s, {})]
        check(not left_disk, f"no dead field on disk (leftovers: {left_disk})")

        print("3) living neighbours survive (counter-check)")
        for section, fields in LIVING.items():
            for key, value in fields.items():
                check(cfg.get(section, {}).get(key) == value,
                      f"{section}.{key} unchanged")
        check("scene_prompt_collage" not in cfg["image_generation"]
              and "scene_prompt_multi_ref" in cfg["image_generation"],
              "collage falls, multi_ref stays")
        check(set(cfg) == set(LIVING), "no section added or dropped")

        print("4) idempotent")
        before = path.stat().st_mtime_ns
        again = cfgmod._strip_dead_config_fields(cfg, path)
        check(again is False, "returns False on the second run")
        check(path.stat().st_mtime_ns == before, "no second write")

        print("4b) a config without any of the fields is left alone")
        clean = copy.deepcopy(LIVING)
        check(cfgmod._strip_dead_config_fields(clean, path) is False,
              "clean config -> no write")
        check(clean == LIVING, "clean config untouched")

        print("5) top-level strays (worlds older than the sectioning)")
        check(set(cfgmod.DEAD_TOPLEVEL_FIELDS)
              == {k for keys in EXPECTED_DEAD.values() for k in keys},
              "DEAD_TOPLEVEL_FIELDS == the same 17 names, flat")
        # worlds/demo and worlds/hotopia look exactly like this: the two item
        # sizes sit at the top level and there is NO inventory section.
        old = {
            "item_image_width": 256,
            "item_image_height": 256,
            "log_level": "INFO",
            "storage_dir": "./storage",
            "image_generation": {"mapfit_backend": "comfy-1",
                                 "scene_prompt_multi_ref": "keep me"},
            "inventory": {"item_image_width": 128, "max_items": 50},
        }
        check(cfgmod._strip_dead_config_fields(old, path) is True,
              "returns True — the top-level strays count as a change")
        check("item_image_width" not in old and "item_image_height" not in old,
              "both top-level item sizes are gone")
        check("item_image_width" not in old["inventory"],
              "the section variant falls too")
        check("mapfit_backend" not in old["image_generation"],
              "the section sweep still works alongside")
        check(old["log_level"] == "INFO" and old["storage_dir"] == "./storage",
              "living TOP-LEVEL fields stay")
        check(old["image_generation"].get("scene_prompt_multi_ref") == "keep me"
              and old["inventory"].get("max_items") == 50,
              "living section fields stay")

    print("6) today's schema prefill seeds neither reappearing field")
    from app.routes import admin_settings  # noqa: E402
    data = {}
    admin_settings._apply_schema_defaults(data)
    ig = data.get("image_generation", {})
    for key in ("mapfit_imagegen_default", "map_tile_vision_analysis"):
        check(key not in ig, f"{key} not materialized by _apply_schema_defaults")
    seeded_dead = [k for s, keys in EXPECTED_DEAD.items()
                   for k in keys if k in data.get(s, {})]
    check(not seeded_dead,
          f"no dead field materialized at all (got {seeded_dead})")

    print("7) red counter-check: the old schema entries WOULD seed them")
    from app.core.config_schema import SECTIONS
    legacy = copy.deepcopy(SECTIONS)
    legacy["image_generation"]["fields"]["mapfit_imagegen_default"] = {
        "type": "imagegen_select", "label": "Map Fit/Match-edges target",
        "default": "",
    }
    legacy["image_generation"]["fields"]["map_tile_vision_analysis"] = {
        "type": "bool", "label": "Analyze neighbor tiles for map prompts",
        "default": False,
    }
    original = admin_settings.get_schema
    try:
        admin_settings.get_schema = lambda: legacy
        red = {}
        admin_settings._apply_schema_defaults(red)
    finally:
        admin_settings.get_schema = original
    red_ig = red.get("image_generation", {})
    check(red_ig.get("mapfit_imagegen_default") == ""
          and red_ig.get("map_tile_vision_analysis") is False,
          "with the removed schema entries back, both fields DO appear")

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
