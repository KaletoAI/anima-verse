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

Since the instance-config layers (2026-10-03) tests 8-10 run on a PAIR of
files — ``<tmp>/w/config.json`` (world) and ``<tmp>/i/config.json``
(instance) — and every dead field sits in the file of its scope (the
``image_generation`` and ``server`` ones are instance, ``chat`` and the use
cases world). Two expectation changes, both by design of the layers:
  * the fixture has no root ``log_level`` and no ``inventory`` — neither is a
    schema section, so both are unknown roots and dropped at load (with a
    warning); they would prove nothing about the strip;
  * the SEEDED blocks (use-case structure, marketplace catalog) are checked
    IN MEMORY (``config.get``) only: on disk each layer is pruned to what
    differs from what ships, and a seed equals its shipped default — so after
    ``migrate_file`` it is ABSENT from the file, which test 9 checks too.

The fixture is the table of the 20 section fields — the 13 of the finding
plus ``server.jwt_secret`` (2026-09-21: sessions are opaque random tokens,
nothing signs a JWT), plus the seven of the instance-config cleanup
(2026-10-03, I0b): six ``image_generation`` leftovers that only sat in world
files and ``rebuild_llm_system_template`` (schema field + env bridge, read by
nobody), plus ``server.storage_dir`` (the world is chosen by ``paths.init`` /
``STORAGE_DIR`` BEFORE any config is read; the bridged value selected
nothing). Written out by hand here, so the constant in app/core/config.py
cannot quietly grow or shrink without this file disagreeing:

    image_generation : comfy_default_workflow, comfyui_workflows,
                       mapfit_backend, mapfit_workflow_file,
                       mapfit_imagegen_default, map_image_prompt_suffix,
                       map_tile_vision_analysis, unet_weight_dtype,
                       scene_prompt_collage,
                       context_render_grid, context_render_figure,
                       scene_asset_rembg, tpose_view_back, tpose_view_left,
                       tpose_view_right, rebuild_llm_system_template
    chat             : auto_wake_stamina
    random_events    : event_image_denoise_strength
    server           : jwt_secret, storage_dir

The ``inventory`` entry (item_image_width/height) is gone from that table:
``inventory`` is no schema section at all, so from the instance layer on it
is dropped as an unknown root. The two names stay known at the TOP LEVEL
only (``DEAD_TOPLEVEL_ONLY_FIELDS``) — worlds/hotopia still carries them
there — and test 5 is their hand case.

Test 1b is the "no reader" half for every name of the table: no string
literal ``"<name>"`` / ``"<dotted.path>.<name>"`` and no attribute access
``.<name>`` anywhere in app/, plugins/ (the symlinked private packs
FOLLOWED; marketplace installs under plugins/installed are user-local and not
scanned — the corpus is ``git ls-files`` plus the symlinked packs),
frontend/src, packages, client3d/src or static/ (the built bundle under
static/game_admin/assets excluded — it is generated from frontend/src). In app/core/config.py only the two constant blocks are
blanked out, so a bridge line like ``server.get("storage_dir", …)`` is still
seen. f-string readers (``f"tpose_view_{v}"``) are out of reach of that scan;
they were checked by hand (task report).

Test 11 pins two bridge cuts of the same cleanup: ``_flatten_to_env`` no
longer writes ``STORAGE_DIR`` from ``server.storage_dir``, and the legacy
``proactive`` section no longer stands in for ``thoughts`` — a world with only
``proactive.min_turn_gap_seconds = 99`` bridges the schema default 30 (by hand
from config_schema ``thoughts.min_turn_gap_seconds``), not 99. Its counter-check
writes the same 99 under ``thoughts`` and sees it arrive.

Beside the flat table there is a NESTED strip: ``image_generation.use_cases``
entries whose render occasion is gone — ``map`` and ``mapfit``, removed with
the map-icon teardown. They sit one level deeper than the table above, so the
flat sweep walks past them; test 4c is their hand case, and the world fixture
of tests 8/9 carries both so the end-to-end path proves it too.

The fields live at TWO depths: normally inside their section, but worlds older
than the sectioning (worlds/hotopia) carry ``item_image_width`` /
``item_image_height`` at the top level — test 5 is the hand case for that.

The point of the file is the pair of counter-checks:
  * the LIVING neighbours of the dead fields survive — most sharply
    ``scene_prompt_collage`` falls while ``scene_prompt_multi_ref`` and
    ``scene_prompt_only_background`` (read in app/core/scene_render.py) stay,
    and a living TOP-LEVEL key (``llm_task_state``, the one root outside the
    schema sections that has a reader) is not caught by the flat sweep;
  * the seeding source is really gone — the two fields that used to reappear
    in freshly created worlds (``mapfit_imagegen_default`` /
    ``map_tile_vision_analysis``) came from schema entries in
    app/core/config_schema.py that ``apply_schema_defaults``
    (app/core/config_admin.py) materializes into config.json on every
    admin save round-trip. Test 6 shows today's schema produces neither;
    test 7 puts the two removed schema entries back and shows the SAME call
    then does produce them — without that red run, test 6 would pass on any
    broken assertion.

FAILS BEFORE: against commit e7363832 (the code before the I0b cleanup) test 1
fails (14 fields, an inventory entry), 1b names the readers it still had —
the bridge lines ``server.get("storage_dir", …)`` /
``ig.get("rebuild_llm_system_template", …)`` and their schema entries — test 2
finds the seven new names left in the dict, and the run stops at test 5 with
an AttributeError (no ``DEAD_TOPLEVEL_ONLY_FIELDS``).

Usage:  ./.venv/bin/python scripts/smoke_dead_config_fields.py
"""
import ast
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Point the storage root at a throwaway directory BEFORE any app import, the
# same way smoke_worldmap_v2.py does. This matters because the thing under
# test WRITES: config.migrate_file() persists the strip/seed pass into the
# world's config.json. There is no default world any more — paths.init()
# without an argument and without STORAGE_DIR raises StorageNotInitialised,
# and so does get_storage_dir() before anything initialised it — so this
# redirect is what gives a stray migrate_file() from an import chain a
# throwaway world to write into instead of failing the run. Tracked world
# data stays out of reach either way; a check script must never touch it.
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
        "context_render_grid",
        "context_render_figure",
        "scene_asset_rembg",
        "tpose_view_back",
        "tpose_view_left",
        "tpose_view_right",
        "rebuild_llm_system_template",
    },
    "chat": {"auto_wake_stamina"},
    "random_events": {"event_image_denoise_strength"},
    "server": {"jwt_secret", "storage_dir"},
}

# Names that are dead at the TOP LEVEL only (no section owns them any more).
EXPECTED_DEAD_TOPLEVEL_ONLY = {"item_image_width", "item_image_height"}
EXPECTED_TOTAL = 20

# The nested strip's table, by hand: use-case entries with no render occasion.
EXPECTED_DEAD_USE_CASES = {"map", "mapfit"}

# Living neighbours that must survive the strip untouched.
LIVING = {
    "image_generation": {
        "scene_prompt_multi_ref": "multi ref prompt",       # scene_render.py
        "scene_prompt_only_background": "bg only prompt",   # scene_render.py
        "backends": [{"name": "gpu-a", "enabled": True}],
    },
    "chat": {"context_messages": 20},
    "random_events": {"enabled": True},
    "ui": {"downscale_item_max_dim": 768},                  # image_postprocess.py
    "server": {"log_level": "INFO"},
}
# image_analysis_prompt is the living sibling of the dead rebuild template.
LIVING["image_generation"]["image_analysis_prompt"] = "describe it"


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILURES.append(msg)


REPO = Path(__file__).resolve().parents[1]
# Where a reader could live. static/game_admin/assets is the build of
# frontend/src and is skipped; app/core/config.py is scanned with its two
# constant blocks blanked out (they NAME the fields, they do not read them).
READER_ROOTS = ["app", "plugins", "frontend/src", "packages", "client3d/src", "static"]
READER_SUFFIXES = {".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".json", ".yaml",
                   ".yml", ".md", ".html", ".css"}


def _reader_corpus():
    """[(relative path, text)] of every tracked file under READER_ROOTS plus
    every file inside a symlinked package under plugins/ (git does not
    follow those)."""
    out = subprocess.run(["git", "ls-files", "-z", "--"] + READER_ROOTS,
                         cwd=REPO, capture_output=True, text=True, check=True).stdout
    files = [REPO / f for f in out.split("\0") if f]
    for pkg in (REPO / "plugins").iterdir():
        if pkg.is_symlink() and pkg.is_dir():
            for dirpath, dirnames, filenames in os.walk(pkg, followlinks=True):
                dirnames[:] = [d for d in dirnames if d != "__pycache__"]
                files.extend(Path(dirpath) / f for f in filenames)
    corpus = []
    for f in files:
        rel = os.path.relpath(f, REPO)
        if rel.startswith("static/game_admin/assets/") or f.suffix not in READER_SUFFIXES:
            continue
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        if rel == "app/core/config.py":
            text = _blank_constants(text)
        corpus.append((rel, text))
    return corpus


def _blank_constants(text):
    """config.py with the DEAD_* constant assignments replaced by blank lines."""
    lines = text.splitlines()
    for node in ast.parse(text).body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
        if target in ("DEAD_CONFIG_FIELDS", "DEAD_TOPLEVEL_ONLY_FIELDS"):
            for i in range(node.lineno - 1, node.end_lineno):
                lines[i] = ""
    return "\n".join(lines)


def readers_of(name, corpus):
    """Lines that read *name* as a config key: a string literal that IS the
    name or ends a dotted path with it, or an attribute access ``.name``."""
    pat = re.compile(r"([\"'](?:\w+\.)*" + re.escape(name) + r"[\"'])|(\." + re.escape(name) + r"\b)")
    hits = []
    for rel, text in corpus:
        for ln, line in enumerate(text.splitlines(), 1):
            if pat.search(line):
                hits.append(f"{rel}:{ln}")
    return hits


def build_fixture() -> dict:
    """A world config carrying all 20 dead fields plus living neighbours."""
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
        "event_image_denoise_strength": 0.6,
        "jwt_secret": "change-me",
        "storage_dir": "./storage",
        "context_render_grid": True,
        "context_render_figure": True,
        "scene_asset_rembg": False,
        "tpose_view_back": True,
        "tpose_view_left": False,
        "tpose_view_right": False,
        "rebuild_llm_system_template": "You are an image prompt enhancer.",
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
          f"DEAD_CONFIG_FIELDS == {EXPECTED_TOTAL} fields of the table (got {actual})")
    check(sum(len(v) for v in actual.values()) == EXPECTED_TOTAL,
          f"{EXPECTED_TOTAL} fields in total")
    check("inventory" not in cfgmod.DEAD_CONFIG_FIELDS,
          "no inventory entry (no schema section, dropped as unknown root)")
    check(set(cfgmod.DEAD_USE_CASES) == EXPECTED_DEAD_USE_CASES,
          f"DEAD_USE_CASES == map + mapfit (got {set(cfgmod.DEAD_USE_CASES)})")
    check(not (EXPECTED_DEAD_USE_CASES & set(cfgmod._DEFAULT_IMAGE_USE_CASES)),
          "neither dead use case is a built-in default any more")

    print("1b) no reader of any dead name (string key or attribute)")
    corpus = _reader_corpus()
    check(len(corpus) >= 500 and any(r.startswith("frontend/src/") for r, _ in corpus)
          and any(r == "app/core/config.py" for r, _ in corpus),
          f"the corpus is real ({len(corpus)} files, lower bound 500)")
    # Counter-check: the scan sees a living key and its bridge line.
    check(any(h.startswith("app/core/config.py:")
              for h in readers_of("image_analysis_prompt", corpus)),
          "counter-check: the living image_analysis_prompt bridge line IS seen")
    dead_names = sorted({k for keys in EXPECTED_DEAD.values() for k in keys}
                        | EXPECTED_DEAD_TOPLEVEL_ONLY)
    for name in dead_names:
        hits = readers_of(name, corpus)
        check(not hits, f"{name}: no reader (got {hits[:4]})")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"

        print(f"2) the strip removes exactly the {EXPECTED_TOTAL} — in memory, no file")
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

        print("4c) the nested use-case strip removes map + mapfit")
        uc_cfg = {"image_generation": {"use_cases": {
            "map": {"styles": {"keywords": {"prompt_style": "tile"}}},
            "mapfit": {"styles": {}},
            "location": {"styles": {"keywords": {"prompt_style": "keep me"}}},
        }}}
        check(cfgmod._strip_dead_use_cases(uc_cfg) is True,
              "returns True on the first run")
        check(set(uc_cfg["image_generation"]["use_cases"]) == {"location"},
              "map and mapfit are gone, the living use case stays")
        check(cfgmod._strip_dead_use_cases(uc_cfg) is False,
              "idempotent — the second run reports no change")
        check(cfgmod._strip_dead_use_cases({"image_generation": {}}) is False,
              "a config without use_cases is left alone")

        print("5) top-level strays (worlds older than the sectioning)")
        check(set(cfgmod.DEAD_TOPLEVEL_ONLY_FIELDS) == EXPECTED_DEAD_TOPLEVEL_ONLY,
              "DEAD_TOPLEVEL_ONLY_FIELDS == the two item sizes")
        check(set(cfgmod.DEAD_TOPLEVEL_FIELDS)
              == ({k for keys in EXPECTED_DEAD.values() for k in keys}
                  | EXPECTED_DEAD_TOPLEVEL_ONLY),
              f"DEAD_TOPLEVEL_FIELDS == the {EXPECTED_TOTAL} names flat + the two "
              f"item sizes")
        # worlds/hotopia looks exactly like this: the two item sizes sit at
        # the top level. llm_task_state is the one LIVING root key that is no
        # schema section (config_scope.EXTRA_ROOTS, read by llm_task_state.py).
        old = {
            "item_image_width": 256,
            "item_image_height": 256,
            "storage_dir": "./storage",
            "llm_task_state": {"disabled_tasks": ["x"]},
            "server": {"storage_dir": "./storage", "log_level": "DEBUG"},
            "image_generation": {"mapfit_backend": "comfy-1",
                                 "scene_prompt_multi_ref": "keep me"},
        }
        check(cfgmod._strip_dead_config_fields(old) is True,
              "returns True — the top-level strays count as a change")
        check("item_image_width" not in old and "item_image_height" not in old,
              "both top-level item sizes are gone")
        check("storage_dir" not in old and "storage_dir" not in old["server"],
              "storage_dir falls at both depths")
        check("mapfit_backend" not in old["image_generation"],
              "the section sweep still works alongside")
        check(old["llm_task_state"] == {"disabled_tasks": ["x"]},
              "the living TOP-LEVEL key stays (llm_task_state)")
        check(old["image_generation"].get("scene_prompt_multi_ref") == "keep me"
              and old["server"].get("log_level") == "DEBUG",
              "living section fields stay")

    print("6) today's schema prefill seeds neither reappearing field")
    from app.core import config_admin
    from app.core.config_schema import get_schema  # noqa: E402
    data = {}
    config_admin.apply_schema_defaults(data, get_schema())
    ig = data.get("image_generation", {})
    for key in ("mapfit_imagegen_default", "map_tile_vision_analysis"):
        check(key not in ig, f"{key} not materialized by apply_schema_defaults")
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
    red = {}
    config_admin.apply_schema_defaults(red, legacy)
    red_ig = red.get("image_generation", {})
    check(red_ig.get("mapfit_imagegen_default") == ""
          and red_ig.get("map_tile_vision_analysis") is False,
          "with the removed schema entries back, both fields DO appear")

    # ── The read/write split ────────────────────────────────────────────────
    # A world + instance pair carrying dead fields at BOTH depths, a legacy
    # backend category, a legacy prompt field, and none of the seeded blocks.
    # Plus an instance secrets.json, because migrate_file() must not leak it
    # into config.json.
    with tempfile.TemporaryDirectory() as tmp:
        world = Path(tmp) / "w" / "config.json"
        inst = Path(tmp) / "i" / "config.json"
        world.parent.mkdir()
        inst.parent.mkdir()
        world_fixture = {
            "chat": {"auto_wake_stamina": 40, "chattiness": 0.3},
            "image_generation": {
                # Both dead use cases, as an older world's config.json holds
                # them — seeded before the map-icon teardown.
                "use_cases": {"map": {"styles": {}}, "mapfit": {"styles": {}}},
            },
            "item_image_height": 256,
        }
        instance_fixture = {
            "image_generation": {
                "mapfit_backend": "comfy-1",
                "scene_prompt_multi_ref": "keep me",
                "backends": [{"name": "gpu-a", "enabled": True,
                              "category": "generate", "prompt_prefix": "old",
                              "api_key": ""}],
            },
            "server": {"storage_dir": "./storage", "log_level": "DEBUG"},
        }
        world.write_text(json.dumps(world_fixture, indent=2), encoding="utf-8")
        inst.write_text(json.dumps(instance_fixture, indent=2), encoding="utf-8")
        (inst.parent / "secrets.json").write_text(
            json.dumps({"image_generation": {"backends": [{"api_key": "sk-SECRET"}]}}),
            encoding="utf-8")
        before = {f: (f.read_bytes(), f.stat().st_mtime_ns) for f in (world, inst)}

        print("8) a bare config.load() writes NOTHING")
        loaded = cfgmod.load(world, inst)
        for f, (data, mtime) in before.items():
            check(f.read_bytes() == data, f"{f.parent.name}/config.json is byte-identical after load")
            check(f.stat().st_mtime_ns == mtime, f"{f.parent.name}/config.json mtime unchanged after load")
        # …while the RUNNING config looks exactly as it always did.
        check("mapfit_backend" not in loaded["image_generation"],
              "in memory: the dead section field is stripped")
        check("auto_wake_stamina" not in loaded["chat"],
              "in memory: the dead world field is stripped")
        check("item_image_height" not in loaded
              and "storage_dir" not in loaded.get("server", {}),
              "in memory: the dead fields at both depths are stripped")
        check("prompt_prefix" not in loaded["image_generation"]["backends"][0],
              "in memory: the legacy backend prompt field is stripped")
        check(loaded["image_generation"]["backends"][0]["category"] == "txt2img",
              "in memory: the backend category is migrated")
        check(loaded["image_generation"]["backends"][0]["api_key"] == "sk-SECRET",
              "in memory: the instance secret is overlaid")
        check(set(cfgmod.get("image_generation.use_cases", {}))
              == set(cfgmod._DEFAULT_IMAGE_USE_CASES),
              "in memory: every use-case block is seeded (map/mapfit gone)")
        check(bool(cfgmod.get("content_marketplace.catalogs")),
              "in memory: the marketplace catalog is seeded")
        check(loaded["image_generation"]["scene_prompt_multi_ref"] == "keep me"
              and loaded["chat"]["chattiness"] == 0.3
              and loaded["server"]["log_level"] == "DEBUG",
              "in memory: living fields survive")

        print("9) migrate_file() writes exactly that strip+seed diff, pruned")
        check(cfgmod.migrate_file(world, inst) is True, "returns True — it wrote")
        w_after = json.loads(world.read_text(encoding="utf-8"))
        i_after = json.loads(inst.read_text(encoding="utf-8"))
        check(w_after == {"chat": {"chattiness": 0.3}},
              f"on disk (world): only the living field is left ({w_after})")
        check("mapfit_backend" not in i_after["image_generation"]
              and "storage_dir" not in i_after.get("server", {}),
              "on disk (instance): the dead fields are gone")
        check("prompt_prefix" not in i_after["image_generation"]["backends"][0]
              and i_after["image_generation"]["backends"][0]["category"] == "txt2img",
              "on disk: legacy prompt field stripped, category migrated")
        # The seeds equal their shipped defaults, so the pruned files do not
        # carry them — they live in memory only (test 8).
        check("use_cases" not in w_after.get("image_generation", {})
              and "content_marketplace" not in i_after,
              "on disk: the seeded blocks are pruned (equal to what ships)")
        check(i_after["image_generation"]["scene_prompt_multi_ref"] == "keep me"
              and i_after["server"] == {"log_level": "DEBUG"},
              "on disk: living fields survive")
        # The two things that must NOT ride along: the secret stays in the
        # instance's secrets.json, and the in-memory-only calendar defaults
        # are not persisted (they equal what ships).
        check(i_after["image_generation"]["backends"][0]["api_key"] == "",
              "on disk: no secret leaked out of secrets.json")
        check("sk-SECRET" in (inst.parent / "secrets.json").read_text(encoding="utf-8"),
              "on disk: the secret is still in the instance's secrets.json")
        check("game_seasons" not in w_after and "game_calendar" not in w_after,
              "on disk: the in-memory-only calendar defaults are not persisted")

        print("10) migrate_file() is idempotent — the second call writes nothing")
        settled = {f: (f.read_bytes(), f.stat().st_mtime_ns) for f in (world, inst)}
        check(cfgmod.migrate_file(world, inst) is False, "returns False — nothing to do")
        for f, (data, mtime) in settled.items():
            check(f.read_bytes() == data, f"{f.parent.name}/config.json byte-identical")
            check(f.stat().st_mtime_ns == mtime, f"{f.parent.name}/config.json mtime unchanged")

    print("11) the bridge: no STORAGE_DIR, no proactive fallback")
    saved_env = dict(os.environ)
    try:
        before = os.environ.get("STORAGE_DIR")
        cfgmod._flatten_to_env({"server": {"storage_dir": "/x"}})
        check(os.environ.get("STORAGE_DIR") == before,
              f"server.storage_dir does not reach STORAGE_DIR "
              f"(got {os.environ.get('STORAGE_DIR')!r})")
        os.environ.pop("THOUGHT_MIN_TURN_GAP_SECONDS", None)
        cfgmod._flatten_to_env({"proactive": {"min_turn_gap_seconds": 99}})
        got = os.environ.get("THOUGHT_MIN_TURN_GAP_SECONDS")
        check(got == "30",
              f"proactive.min_turn_gap_seconds=99 is ignored -> schema default 30 "
              f"(got {got!r})")
        os.environ.pop("THOUGHT_MIN_TURN_GAP_SECONDS", None)
        cfgmod._flatten_to_env({"thoughts": {"min_turn_gap_seconds": 99}})
        got = os.environ.get("THOUGHT_MIN_TURN_GAP_SECONDS")
        check(got == "99",
              f"counter-check: thoughts.min_turn_gap_seconds=99 arrives (got {got!r})")
    finally:
        os.environ.clear()
        os.environ.update(saved_env)
    check(os.environ.get("STORAGE_DIR") == _TMP_STORAGE.name,
          "env restored: STORAGE_DIR is the throwaway dir again")

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
