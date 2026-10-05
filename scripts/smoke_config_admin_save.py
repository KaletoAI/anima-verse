"""Smoke: saving ONE config layer through config_admin (plan I4–I7, Task 2).

Usage:
    ./.venv/bin/python scripts/smoke_config_admin_save.py

Works on temp dirs only: a world dir and an instance dir under one tempfile
root; paths.init / init_instance point there BEFORE any world-DB import.
Both layers start SETTLED: config.json files exist (written by the smoke)
and one save has run before any "unchanged" assertion — a missing layer
file is written as {} by the first save (config._write_if_changed treats a
missing file as changed), which is intended and not what E measures.

Hand-derived expectations (spec § 4 "Speichern", § 6 I4, Review Focus):

A  Instance save writes the instance file only.
   Start: instance {"server": {"log_level": "INFO"}} ... (log_level default is
   whatever SECTIONS["server"]["fields"]["log_level"]["default"] says — the
   smoke reads it and picks a DIFFERENT choice X).
   save_layer("instance", view with server.log_level = X)
   -> instance/config.json == {"server": {"log_level": X}}
   -> world config.json unchanged (bytes equal)

B  World-scope path in an instance body -> LayerSaveError mentioning "chat".
   Instance-scope path in a world body -> LayerSaveError mentioning "providers".

C  Stale page (Review Focus 1): world part saved with chat.top_p = 0.9; then
   an instance save built from a view read BEFORE that world save.
   -> world config.json still holds {"chat": {"top_p": 0.9}}.

D  Duplicate names (Review Focus 2): providers [{"name":"local"},{"name":"local"}]
   -> LayerSaveError whose text contains "providers" and "duplicate name 'local'".

E  Unchanged save writes nothing (Review Focus 4): with one backend entry
   {"name": "b1", "api_type": "<first api_type choice>"} on disk, the view
   from layer_view("instance") (which materializes bool/select item
   defaults) is saved back unchanged -> mtime_ns of instance/config.json and
   of the world config.json are unchanged; the stored backend entry has no
   new keys.

F  Masked secret survives: providers [{"name": "p", "api_key": "sk-1"}] on
   disk; body with api_key "***" -> instance/secrets.json still holds sk-1
   for entry "p".

G  Unreadable instance file -> config.ConfigWriteRefused (subclass of
   RuntimeError) and the world file is not touched.

H  Reset of a list without shipped default (Review Focus 3): llm_routing
   [{"name": "e", "provider": "p", "model": "m"}] on disk;
   save_layer("instance", view, resets=["llm_routing"])
   -> "llm_routing" not in instance/config.json (not [] — prune keeps []).
H2 Reset of the providers list (E11 seed): providers [{"name": "mine",
   "type": "openai", "api_base": "http://x/v1"}] on disk; resets=["providers"]
   -> layer_part("instance")["providers"] == config._DEFAULT_PROVIDERS and
      "providers" not in instance/config.json (equal to the seed, pruned).

I  Reset of a CUSTOMIZED backend list to the seed (Review Focus 3): backends
   on disk = the mesh seed with entry 0 renamed to "old" and given
   "lora_filter": "x"; the body carries that list (as the page would) and
   resets=["image_generation.backends"]
   -> after the save, config_admin.layer_part("instance")["image_generation"]
      ["backends"] == config._default_mesh_backend_entries()  (exact: no
      lora_filter, every seed key present)
   -> "backends" not in instance/config.json's image_generation (pruned)
   -> "image_generation.backends" not in origin("instance")["overrides"]

J  Reset of the image routing (Review Focus 3): image_generation.routing
   {"photo": ["x*"]} on disk; the body's image_generation has NO routing key
   (the page deleted it) and resets=["image_generation.routing"]
   -> "routing" absent from instance/config.json; without the reset entry
      (same body, resets=[]) the stored chains survive
      (_preserve_unsent_image_routing), which is the old protection.

K  resets entry with an index ("providers.0.name") or of the other scope
   ("chat.top_p" in an instance save) -> LayerSaveError.

M  Stale provider env blocks are purged (Codex re-review finding 5): flatten
   a config with providers [a, b, c], then one with providers [a] ->
   "PROVIDER_2_NAME" and "PROVIDER_3_NAME" not in os.environ,
   os.environ["PROVIDER_1_NAME"] == "a". After a reset to the E11 seed (2
   entries) from a 3-entry list -> no PROVIDER_3_* key left.

N  API guards and recursive lists: non-object bodies, malformed resets,
   and unknown roots are rejected before writes. In a named array with a
   nested named array, a bool/select default absent from an existing
   counterpart is removed; a non-default value and a new entry retain their
   values. Duplicate names in a nested list report that list's dotted path.

O  memory=null in a world save is rejected mentioning memory, with instance
   bytes unchanged. Direct cross-layer save_part candidates raise ValueError
   before either config or secret file is written. commit_layer maps it to LayerSaveError.

L  Env bridge follows the newest union: an instance save setting tts.backend
   to a non-default choice, then a world save -> os.environ value of the
   tts.backend bridge key (read the key name from config._flatten_to_env)
   still holds the instance choice.
"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
root = Path(tempfile.mkdtemp(prefix="config-admin-save-"))
world = root / "world"
inst = root / "instance"
world.mkdir()
inst.mkdir()
os.environ["STORAGE_DIR"] = str(world)
os.environ["INSTANCE_DIR"] = str(inst)
from app.core import paths
paths.init(world)
paths.init_instance(inst)
from app.core import config, config_scope
import app.core.config_admin as adm
from app.core.config_schema import SECTIONS

failures = []
def check(cond, msg):
    print(("OK " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)

def read(path):
    return json.loads(path.read_text())

def setup(instance=None, world_data=None):
    for folder in (inst, world):
        (folder / "secrets.json").unlink(missing_ok=True)
    (inst / "config.json").write_text(json.dumps(instance or {}))
    (world / "config.json").write_text(json.dumps(world_data or {}))
    config.load(world / "config.json", inst / "config.json")
    config.save(config.get_all())

# Reload side effects are tested by existing route smokes; this smoke isolates persistence.
adm.apply_section_reloads = lambda changed, scope: []
f = SECTIONS["server"]["fields"]["log_level"]
x = next(v for v in f["choices"] if v != f["default"])
setup({"server": {"log_level": "INFO"}})
wbytes = (world / "config.json").read_bytes()
stale = adm.layer_view("instance")
stale["server"]["log_level"] = x
adm.save_layer("instance", stale)
check(read(inst / "config.json") == {"server": {"log_level": x}} and
      (world / "config.json").read_bytes() == wbytes, "A instance only")

for scope, body, text in [("instance", {"chat": {"top_p": 0.9}}, "chat"),
                          ("world", {"providers": [{"name": "x"}]}, "providers"),
                          ("instance", {"providers": [{"name": "local"}, {"name": "local"}]}, "duplicate name 'local'")]:
    try:
        adm.save_layer(scope, body)
    except adm.LayerSaveError as e:
        check(text in str(e), "B/D refusal " + text)
    else:
        check(False, "B/D refusal " + text)
adm.save_layer("world", {"chat": {"top_p": 0.9}})
adm.save_layer("instance", stale)
check(read(world / "config.json") == {"chat": {"top_p": 0.9}}, "C stale page")

api = SECTIONS["image_generation"]["sub_arrays"]["backends"]["fields"]["api_type"]["choices"][0]
setup({"image_generation": {"backends": [{"name": "b1", "api_type": api}]}})
before = [(p.stat().st_mtime_ns, p.read_bytes()) for p in (inst / "config.json", world / "config.json")]
adm.save_layer("instance", adm.layer_view("instance"))
check(before == [(p.stat().st_mtime_ns, p.read_bytes()) for p in (inst / "config.json", world / "config.json")]
      and read(inst / "config.json")["image_generation"]["backends"] == [{"name": "b1", "api_type": api}], "E unchanged files and entry")
setup({"providers": [{"name": "p", "api_key": "sk-1"}]})
body = adm.layer_view("instance")
body["providers"][0]["api_key"] = "***"
adm.save_layer("instance", body)
check(read(inst / "secrets.json")["providers"]["p"]["api_key"] == "sk-1", "F masked secret")
wbytes = (world / "config.json").read_bytes()
(inst / "config.json").write_text("{broken")
try:
    adm.save_layer("instance", body)
except config.ConfigWriteRefused as e:
    check(isinstance(e, RuntimeError) and (world / "config.json").read_bytes() == wbytes, "G unreadable refusal")
else:
    check(False, "G unreadable refusal")

setup({"llm_routing": [{"name": "e", "provider": "p", "model": "m"}]})
adm.save_layer("instance", adm.layer_view("instance"), resets=["llm_routing"])
check("llm_routing" not in read(inst / "config.json"), "H routing deleted")
setup({"providers": [{"name": "mine", "type": "openai", "api_base": "http://x/v1"}]})
adm.save_layer("instance", adm.layer_view("instance"), resets=["providers"])
check(adm.layer_part("instance")["providers"] == config._DEFAULT_PROVIDERS and "providers" not in read(inst / "config.json"), "H2 provider seed")
seed = config._default_mesh_backend_entries()
custom = copy.deepcopy(seed)
custom[0].update(name="old", lora_filter="x")
setup({"image_generation": {"backends": custom}})
adm.save_layer("instance", adm.layer_view("instance"), resets=["image_generation.backends"])
check(adm.layer_part("instance")["image_generation"]["backends"] == seed and
      "backends" not in read(inst / "config.json").get("image_generation", {}) and
      "image_generation.backends" not in adm.origin("instance")["overrides"], "I exact backend seed")
setup({"image_generation": {"routing": {"photo": ["x*"]}}})
body = adm.layer_view("instance")
body["image_generation"].pop("routing", None)
adm.save_layer("instance", body)
check(read(inst / "config.json")["image_generation"]["routing"] == {"photo": ["x*"]}, "J missing routing preserved")
adm.save_layer("instance", body, resets=["image_generation.routing"])
check("routing" not in read(inst / "config.json").get("image_generation", {}), "J reset wins")
for reset in ("providers.0.name", "chat.top_p"):
    try:
        adm.save_layer("instance", {}, resets=[reset])
    except adm.LayerSaveError:
        check(True, "K " + reset)
    else:
        check(False, "K " + reset)
config._flatten_to_env({"providers": [{"name": n} for n in "abc"]})
config._flatten_to_env({"providers": [{"name": "a"}]})
check(os.environ.get("PROVIDER_1_NAME") == "a" and "PROVIDER_2_NAME" not in os.environ and "PROVIDER_3_NAME" not in os.environ, "M shortened providers")
setup({"providers": [{"name": n} for n in "abc"]})
config._flatten_to_env(config.get_all())
adm.save_layer("instance", adm.layer_view("instance"), resets=["providers"])
check(not any(k.startswith("PROVIDER_3_") for k in os.environ), "M provider reset purges block")
f = SECTIONS["tts"]["fields"]["backend"]
x = next(v for v in f["choices"] if v != f["default"])
body = adm.layer_view("instance")
body.setdefault("tts", {})["backend"] = x
adm.save_layer("instance", body)
adm.save_layer("world", {"chat": {"top_p": 0.9}})
check(os.environ.get("TTS_BACKEND") == x, "L newest union env")
for body, resets, message in [([], [], "body must be a JSON object"),
                              ({}, "server.log_level", "resets must be a list of paths"),
                              ({}, [1], "resets must be a list of paths"),
                              ({"unknown_root": 1}, [], "unknown_root")]:
    before = (inst / "config.json").read_bytes()
    try:
        adm.prepare_layer("instance", body, resets)
    except adm.LayerSaveError as e:
        check(message in str(e) and (inst / "config.json").read_bytes() == before,
              "N input guard " + message)
    else:
        check(False, "N input guard " + message)
fields = {"enabled": {"type": "bool", "default": True},
          "mode": {"type": "select", "default": "auto"}}
schema = {"entries": {"is_array": True, "fields": {
    **fields, "children": {"is_array": True, "item_fields": fields}}}}
current = {"entries": [{"name": "one", "children": [{"name": "child"}]}]}
merged = {"entries": [{"name": "one", "enabled": True, "mode": "custom",
                       "children": [{"name": "child", "enabled": True, "mode": "auto"},
                                    {"name": "new", "enabled": True, "mode": "auto"}]},
                      {"name": "new", "enabled": True}]}
adm.strip_materialized_item_defaults(merged, current, schema)
check(merged == {"entries": [{"name": "one", "mode": "custom", "children": [
    {"name": "child"}, {"name": "new", "enabled": True, "mode": "auto"}]},
    {"name": "new", "enabled": True}]}, "N nested strip keeps new and custom values")
check(adm.duplicate_names({"a": {"b": [{"name": "dup"}, {"name": "dup"}]}})
      == ["a.b: duplicate name 'dup'"], "N nested duplicate path")
setup({"memory": {"chat_retention_days": 42}})
before = [(p, p.read_bytes()) for folder in (inst, world)
          for p in folder.glob("*.json")]
try:
    adm.save_layer("world", {"memory": None})
except adm.LayerSaveError as e:
    check("memory" in str(e), "O mixed object rejected")
else:
    check(False, "O mixed object rejected")
check(all(p.read_bytes() == data for p, data in before), "O malformed save writes nothing")
setup({"memory": {"chat_retention_days": 42}})
for scope, candidate in (("world", {"memory": None}),
                         ("instance", {"chat": {"injected_world_value": 1}})):
    before = [(p, p.read_bytes()) for folder in (inst, world)
              for p in folder.glob("*.json")]
    try:
        config.save_part(scope, candidate)
    except ValueError as e:
        check("save_part would change the" in str(e), "O direct guard " + scope)
    else:
        check(False, "O direct guard " + scope)
    check(all(p.read_bytes() == data for p, data in before), "O guard writes nothing " + scope)
try:
    adm.commit_layer("world", {"memory": None}, adm.layer_part("world"))
except adm.LayerSaveError:
    check(True, "O commit maps guard")
else:
    check(False, "O commit maps guard")
print(f"{len(failures)} failure(s)")
sys.exit(bool(failures))
