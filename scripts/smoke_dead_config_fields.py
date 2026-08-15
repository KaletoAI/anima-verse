#!/usr/bin/env python3
"""Smoke run for the dead-config-field strip (Config-Altlasten, part A).

No world, no DB: a hand-built config dict goes into
``config._strip_dead_config_fields`` against a temp file, and the admin
schema prefill runs on an empty dict.

The fixture is the table of the 13 fields from the finding — written out by
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

The point of the file is the pair of counter-checks:
  * the LIVING neighbours of the dead fields survive — most sharply
    ``scene_prompt_collage`` falls while ``scene_prompt_multi_ref`` and
    ``scene_prompt_only_background`` (read in app/core/scene_render.py) stay;
  * the seeding source is really gone — the two fields that used to reappear
    in freshly created worlds (``mapfit_imagegen_default`` /
    ``map_tile_vision_analysis``) came from schema entries in
    app/core/config_schema.py that ``_apply_schema_defaults``
    (app/routes/admin_settings.py) materializes into config.json on every
    admin save round-trip. Test 5 shows today's schema produces neither;
    test 6 puts the two removed schema entries back and shows the SAME call
    then does produce them — without that red run, test 5 would pass on any
    broken assertion.

Usage:  ./.venv/bin/python scripts/smoke_dead_config_fields.py
"""
import copy
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
}


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILURES.append(msg)


def build_fixture() -> dict:
    """A world config carrying all 13 dead fields plus living neighbours."""
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
    }
    for section, keys in EXPECTED_DEAD.items():
        for key in keys:
            cfg[section][key] = dead_values[key]
    return cfg


def main():
    print("1) the constant matches the finding's table")
    actual = {s: set(k) for s, k in cfgmod.DEAD_CONFIG_FIELDS.items()}
    check(actual == EXPECTED_DEAD,
          f"DEAD_CONFIG_FIELDS == 13 fields of the table (got {actual})")
    check(sum(len(v) for v in actual.values()) == 13,
          "13 fields in total")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"

        print("2) the strip removes exactly the 13 and persists")
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

    print("5) today's schema prefill seeds neither reappearing field")
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

    print("6) red counter-check: the old schema entries WOULD seed them")
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
