#!/usr/bin/env python3
"""Smoke run for the dead-config-field strip (Config-Altlasten, part A).

No world, no DB, and a THROWAWAY storage root: a hand-built config dict goes
into ``config._strip_dead_config_fields``, and the admin schema prefill runs on
an empty dict. Test 0 pins the storage root before anything else — see the
guard below.

Tests 8-10 pin the READ/WRITE split of the config lifecycle: ``config.load()``
normalises only in memory and NEVER touches a file, while the explicit
``config.migrate_file()`` writes exactly that normalisation to disk and is
idempotent. Before the split, every script that merely opened a world rewrote
its tracked config.json.

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

# Point the storage root at a throwaway directory BEFORE any app import, the
# same way smoke_worldmap_v2.py does. This matters because the thing under
# test WRITES: config.migrate_file() persists the strip/seed pass into the
# world's config.json. paths.init() falls back to ./worlds/demo when
# STORAGE_DIR is unset (app/core/paths.py, resolved against the CURRENT
# WORKING DIRECTORY), and get_storage_dir() auto-initializes on first call —
# so a stray migrate_file() from an import chain would edit tracked world
# data. A check script must never do that.
#
# Two deliberate changes over the previous guard:
#   * assignment, not setdefault — an inherited STORAGE_DIR (a shell that
#     exported one, a parent process pointing at a real world) silently won
#     against setdefault, which is the one case where the guard was needed;
#   * an EXPLICIT paths.init(), so the storage root is pinned by argument and
#     no longer depends on an env var being read at the right moment.
# The assertion below is the check-at-the-consumer: it fails the run rather
# than letting a regression show up as a dirty `git status worlds/`.
_TMP_STORAGE = tempfile.TemporaryDirectory(prefix="smoke_dead_config_")
os.environ["STORAGE_DIR"] = _TMP_STORAGE.name

from app.core import paths  # noqa: E402

paths.init(_TMP_STORAGE.name)

_root = paths.get_storage_dir().resolve()
if _root != Path(_TMP_STORAGE.name).resolve():
    raise SystemExit(f"storage root is {_root}, not the throwaway directory — "
                     f"refusing to run against real world data")

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
    print("0) the run is isolated from every real world")
    tmp_root = Path(_TMP_STORAGE.name).resolve()
    check(paths.get_storage_dir().resolve() == tmp_root,
          f"storage root is the throwaway dir ({paths.get_storage_dir()})")
    check(paths.get_config_path().resolve().parent == tmp_root,
          f"config.json would be written into it ({paths.get_config_path()})")
    repo_demo = (Path(__file__).resolve().parents[1] / "worlds").resolve()
    check(repo_demo not in paths.get_config_path().resolve().parents,
          "no path of this run points into the repo's worlds/")

    print("1) the constant matches the finding's table")
    actual = {s: set(k) for s, k in cfgmod.DEAD_CONFIG_FIELDS.items()}
    check(actual == EXPECTED_DEAD,
          f"DEAD_CONFIG_FIELDS == 13 fields of the table (got {actual})")
    check(sum(len(v) for v in actual.values()) == 13,
          "13 fields in total")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"

        print("2) the strip removes exactly the 13 — in memory, no file")
        cfg = build_fixture()
        changed = cfgmod._strip_dead_config_fields(cfg)
        check(changed is True, "returns True on the first run")
        check(not path.exists(),
              "the strip itself writes NOTHING (config.json still absent)")
        left = {s: sorted(k for k in EXPECTED_DEAD[s] if k in cfg.get(s, {}))
                for s in EXPECTED_DEAD}
        check(all(not v for v in left.values()),
              f"no dead field left in the dict (leftovers: {left})")

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
        again = cfgmod._strip_dead_config_fields(cfg)
        check(again is False, "returns False on the second run")

        print("4b) a config without any of the fields is left alone")
        clean = copy.deepcopy(LIVING)
        check(cfgmod._strip_dead_config_fields(clean) is False,
              "clean config -> no change")
        check(clean == LIVING, "clean config untouched")

        print("5) top-level strays (worlds older than the sectioning)")
        check(set(cfgmod.DEAD_TOPLEVEL_FIELDS)
              == {k for keys in EXPECTED_DEAD.values() for k in keys},
              "DEAD_TOPLEVEL_FIELDS == the same 13 names, flat")
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
        check(cfgmod._strip_dead_config_fields(old) is True,
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

    # ── The read/write split ────────────────────────────────────────────────
    # A world file carrying a dead field at BOTH depths, a legacy backend
    # category, a legacy prompt field, and none of the seeded blocks. Plus a
    # secrets.json, because migrate_file() must not leak it into config.json.
    with tempfile.TemporaryDirectory() as tmp:
        world = Path(tmp) / "config.json"
        fixture = {
            "log_level": "INFO",
            "image_generation": {
                "mapfit_backend": "comfy-1",
                "scene_prompt_multi_ref": "keep me",
                "backends": [{"name": "gpu-a", "enabled": True,
                              "category": "generate", "prompt_prefix": "old",
                              "api_key": ""}],
            },
            "inventory": {"item_image_width": 128, "max_items": 50},
            "item_image_height": 256,
        }
        world.write_text(json.dumps(fixture, indent=2), encoding="utf-8")
        (Path(tmp) / "secrets.json").write_text(
            json.dumps({"image_generation": {"backends": [{"api_key": "sk-SECRET"}]}}),
            encoding="utf-8")
        before_bytes = world.read_bytes()
        before_mtime = world.stat().st_mtime_ns

        print("8) a bare config.load() writes NOTHING")
        loaded = cfgmod.load(world)
        check(world.read_bytes() == before_bytes,
              "config.json is byte-identical after load")
        check(world.stat().st_mtime_ns == before_mtime,
              "config.json mtime unchanged after load")
        # …while the RUNNING config looks exactly as it always did.
        check("mapfit_backend" not in loaded["image_generation"],
              "in memory: the dead section field is stripped")
        check("item_image_height" not in loaded
              and "item_image_width" not in loaded.get("inventory", {}),
              "in memory: the dead fields at both depths are stripped")
        check("prompt_prefix" not in loaded["image_generation"]["backends"][0],
              "in memory: the legacy backend prompt field is stripped")
        check(loaded["image_generation"]["backends"][0]["category"] == "txt2img",
              "in memory: the backend category is migrated")
        check(set(loaded["image_generation"].get("use_cases", {}))
              == set(cfgmod._DEFAULT_IMAGE_USE_CASES),
              "in memory: every use-case block is seeded")
        check(bool(loaded.get("content_marketplace", {}).get("catalogs")),
              "in memory: the marketplace catalog is seeded")
        check(loaded["image_generation"]["scene_prompt_multi_ref"] == "keep me"
              and loaded["log_level"] == "INFO",
              "in memory: living fields survive")

        print("9) migrate_file() writes exactly that strip+seed diff")
        check(cfgmod.migrate_file(world) is True, "returns True — it wrote")
        after = json.loads(world.read_text(encoding="utf-8"))
        check(world.read_bytes() != before_bytes, "the file did change")
        check("mapfit_backend" not in after["image_generation"]
              and "item_image_height" not in after
              and "item_image_width" not in after["inventory"],
              "on disk: the dead fields are gone")
        check("prompt_prefix" not in after["image_generation"]["backends"][0]
              and after["image_generation"]["backends"][0]["category"] == "txt2img",
              "on disk: legacy prompt field stripped, category migrated")
        check(set(after["image_generation"].get("use_cases", {}))
              == set(cfgmod._DEFAULT_IMAGE_USE_CASES),
              "on disk: every use-case block is seeded")
        check(bool(after.get("content_marketplace", {}).get("catalogs")),
              "on disk: the marketplace catalog is seeded")
        check(after["image_generation"]["scene_prompt_multi_ref"] == "keep me"
              and after["log_level"] == "INFO"
              and after["inventory"]["max_items"] == 50,
              "on disk: living fields survive")
        # The two things that must NOT ride along: migrate_file works on a
        # fresh read of the file, not on the in-memory config, which carries
        # the secrets overlay and the materialized game calendar.
        check(after["image_generation"]["backends"][0]["api_key"] == "",
              "on disk: no secret leaked out of secrets.json")
        check("game_seasons" not in after and "game_calendar" not in after,
              "on disk: the in-memory-only calendar defaults are not persisted")

        print("10) migrate_file() is idempotent — the second call writes nothing")
        settled_bytes = world.read_bytes()
        settled_mtime = world.stat().st_mtime_ns
        check(cfgmod.migrate_file(world) is False, "returns False — nothing to do")
        check(world.read_bytes() == settled_bytes, "config.json byte-identical")
        check(world.stat().st_mtime_ns == settled_mtime, "mtime unchanged")

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
