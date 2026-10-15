"""Smoke: the per-scope views of the config schema (plan I4–I7, Task 1).

Usage:
    ./.venv/bin/python scripts/smoke_config_scope_views.py

Runs without a server and without a world DB (no storage is touched). The
skill packages' subsections come from the manifests (no discovery runs here).

Expected values, derived by hand from config_schema.py and the spec § 5:

Part A — schema_for("instance")
  sections kept whole (declared instance): server, providers, llm_retry,
  llm_routing, lanes, embedding, decision, tts, knowledge, ui,
  content_marketplace; plus the virtual llm_simple.
  image_generation (declared instance, sub_array use_cases is world): kept,
  WITHOUT sub_arrays.use_cases and WITHOUT the page "use_cases"; the custom
  pages "routing" and "routing_overview" stay (declared scope = instance).
  memory (declared world, field chat_retention_days instance): kept with
  exactly one data field, chat_retention_days. Its only group_header
  (_grp_situational) sits AFTER chat_retention_days and is followed by
  situational_* (world) only, so the instance view drops it (Part A2).
  skills (mixed): kept with the subsection "searx" holding only "url"
  (plugins/searx/plugin.yaml declares url scope: instance); "outfit_change"
  (world) is gone.
  NOT present: chat, relationships, social_reactions, thoughts, intents,
  random_events, npc, story_engine, game, messaging_frame, game_calendar,
  game_seasons.

Part A2 — memory in the instance view: the set of field names whose type is
  not group_header/note is exactly {"chat_retention_days"}.

Part B — schema_for("world")
  present: chat, memory, relationships, social_reactions, thoughts, intents,
  random_events, npc, story_engine, game, messaging_frame, game_calendar,
  game_seasons, skills, image_generation.
  memory: has every data field of SECTIONS["memory"] except
  chat_retention_days.
  image_generation: only sub_arrays.use_cases; no data fields; pages = the
  single page "use_cases"; no custom page.
  messaging_frame: all five fields incl. the two buttons and the preview
  (declared world, so the pseudo fields inherit world).
  skills: subsection outfit_change present; subsection searx present
  WITHOUT "url".
  llm_simple absent. Every section has a "world_group" that is one of the
  WORLD_GROUPS ids.

Part C — shipped_tree (the four list defaults include E11 providers)
  shipped_tree("instance")["server"]["timezone"] == ""            (E10)
  shipped_tree("instance")["memory"] == {"chat_retention_days": 90}
  shipped_tree("instance")["content_marketplace"]["catalogs"]
      == config._DEFAULT_MARKETPLACE_CATALOGS
  shipped_tree("instance")["image_generation"]["backends"]
      == config._default_mesh_backend_entries()
  shipped_tree("instance")["providers"] == config._DEFAULT_PROVIDERS   (E11)
  "llm_routing" not in shipped_tree("instance")   (no shipped default list)
  shipped_tree("world")["game_seasons"] == game_time.default_seasons_config()
  shipped_tree("world")["chat"]["top_p"] == 0                      (I0)
  set(shipped_tree("world")["image_generation"]["use_cases"])
      == set(config._DEFAULT_IMAGE_USE_CASES)
  "chat_retention_days" not in shipped_tree("world")["memory"]

Part E — example providers (E11), through config.load on temp dirs (paths.init
  BEFORE any world-DB import; no file of the real worlds is read):
  instance config.json = {}              -> config.get("providers") == _DEFAULT_PROVIDERS
  instance config.json = {"providers": []} -> config.get("providers") == []
  instance config.json = {"providers": [{"name": "mine", "type": "openai",
      "api_base": "http://x/v1"}]}       -> exactly that one entry
  config_scope.prune({"providers": _DEFAULT_PROVIDERS}) == {}

Part F — hand-built schema, independent of the shipped schema:
  root declares instance; local field/array inherit instance, remote
  field/array declare world. The instance custom page keeps only local
  references; an empty custom page stays. The world view drops both custom
  pages even though remote references survive. Ordinary pages retain only
  surviving references and disappear when both lists become empty.
  Each nested subsection/sub_array declares instance but has only a world
  field, making it MIXED. In the instance view that field disappears, so
  only its custom page (with empty lists) survives; both nested nodes stay.

Part D — override_paths (input already pruned):
  {"server": {"timezone": "Europe/Berlin"},
   "providers": [{"name": "a"}],
   "image_generation": {"routing": {"chat_scene": ["x*"]}}}
  -> ["image_generation.routing.chat_scene", "providers", "server.timezone"]
  {} -> []
"""
import os
import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import paths  # noqa: E402

_TMP = tempfile.TemporaryDirectory(prefix="scope-views-")
os.environ["STORAGE_DIR"] = _TMP.name
paths.init(_TMP.name)

from app.core import config, config_scope  # noqa: E402
from app.core.config_schema import SECTIONS  # noqa: E402
from app.core.game_time import default_seasons_config  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def data_fields(node):
    return {k for k, f in (node.get("fields") or {}).items()
            if isinstance(f, dict) and f.get("type") not in ("group_header", "note")
            and not k.startswith("_")}


# Part F — scope resolution uses this small schema; restore globals on exit.
page_only = {
    "scope": "instance",
    "fields": {"remote": {"type": "string", "scope": "world"}},
    "pages": [{"id": "custom", "custom": True, "fields": ["remote"],
               "sub_arrays": []}],
}
fixture = {
    "scope": "instance",
    "fields": {"local": {"type": "string"},
               "remote": {"type": "string", "scope": "world"}},
    "subsections": {"page_only": page_only},
    "sub_arrays": {
        "local": {"scope": "instance", "fields": {"value": {"type": "string"}}},
        "remote": {"scope": "world", "fields": {"value": {"type": "string"}}},
        "page_only": page_only,
    },
    "pages": [
        {"id": "custom", "custom": True, "fields": ["local", "remote"],
         "sub_arrays": ["local", "remote"]},
        {"id": "empty_custom", "custom": True},
        {"id": "ordinary", "fields": ["local", "remote"],
         "sub_arrays": ["local", "remote"]},
        {"id": "remote_only", "fields": ["remote"], "sub_arrays": ["remote"]},
        {"id": "empty"},
    ],
}
original_schema_view = config_scope._schema_view
try:
    config_scope._schema_view = lambda: {"fixture": fixture}
    config_scope._view_cache = (None, None)
    filtered = config_scope.schema_for("instance")["fixture"]
    for kind in ("subsections", "sub_arrays"):
        nested = (filtered.get(kind) or {}).get("page_only", {})
        check(nested.get("pages") == [
            {"id": "custom", "custom": True, "fields": [], "sub_arrays": []}],
            f"F: nested {kind} keeps custom-only node with trimmed references")
    check(filtered.get("pages") == [
        {"id": "custom", "custom": True, "fields": ["local"], "sub_arrays": ["local"]},
        {"id": "empty_custom", "custom": True, "fields": [], "sub_arrays": []},
        {"id": "ordinary", "fields": ["local"], "sub_arrays": ["local"]},
    ], "F: every instance page is trimmed before retention")
    filtered_world = config_scope.schema_for("world")["fixture"]
    check(filtered_world.get("pages") == [
        {"id": "ordinary", "fields": ["remote"], "sub_arrays": ["remote"]},
        {"id": "remote_only", "fields": ["remote"], "sub_arrays": ["remote"]},
    ], "F: world pages drop custom pages and empty ordinary pages")
finally:
    config_scope._schema_view = original_schema_view
    config_scope._view_cache = (None, None)

# Part A
inst = config_scope.schema_for("instance")
for k in ("server", "providers", "llm_retry", "llm_routing", "lanes", "embedding",
          "decision", "tts", "knowledge", "ui", "content_marketplace", "llm_simple"):
    check(k in inst, f"A: instance view has {k}")
for k in ("chat", "relationships", "social_reactions", "thoughts", "intents",
          "random_events", "npc", "story_engine", "game", "messaging_frame",
          "game_calendar", "game_seasons"):
    check(k not in inst, f"A: instance view drops {k}")
ig = inst["image_generation"]
check("use_cases" not in (ig.get("sub_arrays") or {}), "A: no use_cases sub_array")
page_ids = [p["id"] for p in ig.get("pages") or []]
check("use_cases" not in page_ids, "A: no use_cases page")
check("routing" in page_ids and "routing_overview" in page_ids, "A: custom routing pages kept")
check(data_fields(inst["memory"]) == {"chat_retention_days"}, "A2: memory = chat_retention_days only")
subs = inst["skills"].get("subsections") or {}
check("outfit_change" not in subs, "A: skills.outfit_change dropped")
check(data_fields(subs.get("searx", {})) == {"url"}, "A: skills.searx = url only")

check("_grp_situational" not in inst["memory"]["fields"], "A2: no situational header")

# Part B
world = config_scope.schema_for("world")
for k in ("chat", "memory", "relationships", "social_reactions", "thoughts", "intents",
          "random_events", "npc", "story_engine", "game", "messaging_frame",
          "game_calendar", "game_seasons", "skills", "image_generation"):
    check(k in world, f"B: world view has {k}")
check("llm_simple" not in world, "B: llm_simple absent")
check(data_fields(world["memory"]) == data_fields(SECTIONS["memory"]) - {"chat_retention_days"},
      "B: memory without chat_retention_days")
check("_grp_situational" in world["memory"]["fields"], "B: situational header stays")
wig = world["image_generation"]
check(not data_fields(wig), "B: image_generation has no data field")
check(list((wig.get("sub_arrays") or {})) == ["use_cases"], "B: only use_cases")
check([p["id"] for p in wig.get("pages") or []] == ["use_cases"], "B: only the use_cases page")
check(set(world["messaging_frame"]["fields"]) == set(SECTIONS["messaging_frame"]["fields"]),
      "B: messaging_frame keeps buttons and preview")
wsubs = world["skills"].get("subsections") or {}
check("outfit_change" in wsubs, "B: outfit_change present")
check("url" not in (wsubs.get("searx", {}).get("fields") or {}), "B: searx without url")
from app.core.config_schema import WORLD_GROUPS  # noqa: E402

group_ids = {g["id"] for g in WORLD_GROUPS}
for k, sec in world.items():
    check(sec.get("world_group") in group_ids, f"B: {k} has a known world_group")

# Part C
ti = config_scope.shipped_tree("instance")
tw = config_scope.shipped_tree("world")
check(ti["server"]["timezone"] == "", "C: timezone default empty")
check(ti["memory"] == {"chat_retention_days": 90}, "C: instance memory part")
check(ti["content_marketplace"]["catalogs"] == config._DEFAULT_MARKETPLACE_CATALOGS, "C: catalogs seed")
check(ti["image_generation"]["backends"] == config._default_mesh_backend_entries(), "C: mesh seed")
check(ti["providers"] == config._DEFAULT_PROVIDERS, "C: example providers seed (E11)")
check("llm_routing" not in ti, "C: no llm_routing default")
check(tw["game_seasons"] == default_seasons_config(), "C: seasons default")
check(tw["chat"]["top_p"] == 0, "C: top_p default 0")
check(set(tw["image_generation"]["use_cases"]) == set(config._DEFAULT_IMAGE_USE_CASES), "C: use cases")
check("chat_retention_days" not in tw["memory"], "C: world memory without retention")
check("packages" not in ti, "C: package activation has no instance default")
check(config_scope.split_by_scope({"packages": {"enabled": "absent_pack"}}) ==
      ({}, {"packages": {"enabled": "absent_pack"}}, []),
      "C: absent package IDs remain world-only during scope split")

# Part D
got = config_scope.override_paths({
    "server": {"timezone": "Europe/Berlin"},
    "providers": [{"name": "a"}],
    "image_generation": {"routing": {"chat_scene": ["x*"]}},
})
check(got == ["image_generation.routing.chat_scene", "providers", "server.timezone"],
      f"D: override paths {got}")
check(config_scope.override_paths({}) == [], "D: empty part")

# Part E — all load cases use temporary world and instance files.
world_file = Path(_TMP.name) / "world" / "config.json"
instance_file = Path(_TMP.name) / "inst" / "config.json"
world_file.parent.mkdir()
instance_file.parent.mkdir()
world_file.write_text("{}", encoding="utf-8")
mine = [{"name": "mine", "type": "openai", "api_base": "http://x/v1"}]
for raw, expected, label in (
    ({}, config._DEFAULT_PROVIDERS, "missing providers seeds examples"),
    ({"providers": []}, [], "empty providers stay empty"),
    ({"providers": mine}, mine, "custom providers stay exact"),
):
    instance_file.write_text(json.dumps(raw), encoding="utf-8")
    config.load(world_file, instance_file)
    check(config.get("providers") == expected, f"E: {label}")
check(config_scope.prune({"providers": config._DEFAULT_PROVIDERS}) == {}, "E: seed is pruned")

# An inactive installed package still owns its dormant endpoint settings.
# Losing manifest metadata after discovery would move that URL to world scope.
from app.plugins import loader, registry
synthetic_root = Path(_TMP.name) / "synthetic_plugins"
synthetic_pack = synthetic_root / "installed" / "scope_dormant"
synthetic_pack.mkdir(parents=True)
(synthetic_pack / "plugin.yaml").write_text(json.dumps({
    "name": "Dormant scope probe",
    "on_load": "must_not_import.py",
    "config_schema": {"scope_dormant": {"label": "Dormant probe", "fields": {
        "url": {"type": "str", "scope": "instance", "default": ""},
        "mood": {"type": "str", "default": ""},
    }}},
}), encoding="utf-8")
marker = Path(_TMP.name) / "unexpected_package_import"
(synthetic_pack / "must_not_import.py").write_text(
    f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\n",
    encoding="utf-8")
loader.PLUGIN_DIR = synthetic_root
loader._manifest_schemas = None
config_scope._view_cache = (None, None)
world_file.write_text(json.dumps({
    "packages": {"enabled": ""},
    "skills": {"scope_dormant": {"mood": "quiet"}},
}), encoding="utf-8")
instance_file.write_text(json.dumps({
    "skills": {"scope_dormant": {"url": "https://private.invalid"}},
}), encoding="utf-8")
for phase in ("before discovery", "after discovery"):
    if phase == "after discovery":
        loader.discover_packages()
        check("scope_dormant" not in {p.id for p in registry.packages()},
              "G: installed package without opt-in is not activated")
    check(config_scope.scope_of("skills.scope_dormant.url") == "instance",
          f"G: dormant endpoint stays instance {phase}")
    check(config_scope.scope_of("skills.scope_dormant.mood") == "world",
          f"G: dormant simulation setting stays world {phase}")
    check(not marker.exists(), f"G: scope inventory imports no package code {phase}")
    config.load(world_file, instance_file)
    config.save(config.get_all())
    check(json.loads(instance_file.read_text()).get("skills", {}).get("scope_dormant") ==
          {"url": "https://private.invalid"}, f"G: dormant endpoint persisted only instance {phase}")
    check(json.loads(world_file.read_text()).get("skills", {}).get("scope_dormant") ==
          {"mood": "quiet"}, f"G: dormant simulation value persisted only world {phase}")

# Marketplace installation/removal followed by normal rediscovery refreshes
# dormant metadata without importing or activating either unlisted package.
manifest = json.loads((synthetic_pack / "plugin.yaml").read_text())
later_pack = synthetic_root / "installed" / "scope_later"
later_pack.mkdir()
manifest["config_schema"]["scope_later"] = manifest["config_schema"].pop("scope_dormant")
(later_pack / "plugin.yaml").write_text(json.dumps(manifest), encoding="utf-8")
(later_pack / "must_not_import.py").write_text(
    f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\n",
    encoding="utf-8")
check("scope_later" not in loader.manifest_config_schemas(),
      "H: inventory remains cached until normal rediscovery")
check("scope_later" not in
      config_scope.schema_for("instance")["skills"].get("subsections", {}),
      "H: cached scope view does not invent unscanned ownership")
loader.discover_packages(force=True)
check(config_scope.scope_of("skills.scope_later.url") == "instance",
      "H: newly installed unlisted package endpoint gains instance ownership")
check("scope_later" in config_scope.schema_for("world")["skills"]["subsections"],
      "H: newly installed unlisted package world settings join inventory")
check("scope_later" not in {p.id for p in registry.packages()} and not marker.exists(),
      "H: newly installed unlisted package remains inactive")
(synthetic_pack / "plugin.yaml").unlink()
(synthetic_pack / "must_not_import.py").unlink()
synthetic_pack.rmdir()
check("scope_dormant" in loader.manifest_config_schemas(),
      "H: removal does not mutate cached inventory before rediscovery")
loader.discover_packages(force=True)
check("scope_dormant" not in
      config_scope.schema_for("instance")["skills"].get("subsections", {}),
      "H: removed inactive package loses stale instance schema")
check("scope_dormant" not in
      config_scope.schema_for("world")["skills"].get("subsections", {}),
      "H: removed inactive package loses stale world schema")
check(config_scope.scope_of("skills.scope_later.url") == "instance" and not marker.exists(),
      "H: remaining inactive package scope survives removal without imports")

print()
print("FAILED: %d" % len(FAILS) if FAILS else "ALL OK")
_TMP.cleanup()
sys.exit(1 if FAILS else 0)
