"""Check explicit world package activation with temporary packages/processes.

Usage: .venv/bin/python scripts/smoke_world_package_activation.py
No active world, private package, server, or installation config is touched.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PACKAGE_IDS = {
    "base_probe", "content_probe", "dependent_probe", "transitive_probe",
    "unrelated_probe", "base_probe_extra", "gated_probe", "mixed_probe",
}
ALL_ENABLED = ",".join(sorted(PACKAGE_IDS))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def make_package(plugins, package_id, *, installed=False, content=False,
                 requires=(), always=True, enabled_default=False, shared_rig=False):
    package = plugins / ("installed" if installed else "") / package_id
    package.mkdir(parents=True)
    llm = package / "templates/llm"
    llm.mkdir(parents=True)
    (llm / (package_id + ".md")).write_text(package_id + " template", encoding="utf-8")
    write_json(package / "fragment.json", {
        "apply_to": "*", "features": {package_id: True},
    })
    slot = {"id": package_id + "_slot", "prompt": {"always": package_id + " body"}}
    if shared_rig:
        slot["rig"] = {"id": "shared_group", "op": "fixture_operation",
                       "chains": [[{"bone": "FixtureExtension", "parent": "Hips"}]]}
    manifest = {
        "name": package_id,
        "enabled_default": enabled_default,
        "on_load": "on_load.py",
        "requires": list(requires),
        "templates": {"llm": "templates/llm", "character": ["fragment.json"]},
        "state_flags": [{"flag": package_id + "_flag"}],
        "apply_to": "*", "body_slots": [slot],
        "piece_slots": [package_id + "_piece"],
        "config_schema": {package_id: {"label": package_id, "fields": {
            "instance_probe": {"type": "str", "scope": "instance", "default": ""},
            "world_probe": {"type": "str", "scope": "world", "default": ""},
        }}},
    }
    if not content:
        manifest["skills"] = [{"skill_id": package_id + "_verb",
                               "always_load": always, "default_enabled": True}]
        if package_id == "mixed_probe":
            manifest["skills"].append({"skill_id": "mixed_probe_gated", "always_load": False})
    write_json(package / "plugin.yaml", manifest)
    (package / "on_load.py").write_text(
        "from pathlib import Path\n"
        "from app.core.hooks import register, register_provider\n"
        "Path(__file__).with_name('onload-imported').write_text('imported')\n"
        f"register_provider({package_id!r}, lambda: {package_id!r})\n"
        f"register({package_id!r}, lambda: None, tag={package_id!r})\n",
        encoding="utf-8")
    (package / "skill.py").write_text(
        "from pathlib import Path\n"
        "from app.plugins.base import PluginSkill\n"
        "Path(__file__).with_name('skill-imported').write_text('imported')\n"
        "class ProbeSkill(PluginSkill):\n"
        "    def execute(self, *args, **kwargs):\n"
        f"        return {package_id!r}\n", encoding="utf-8")
    return package


def fixture(root, installed):
    plugins = root / "plugins"
    make_package(plugins, "base_probe", installed=installed)
    make_package(plugins, "content_probe", installed=not installed, content=True)
    make_package(plugins, "dependent_probe", installed=not installed, requires=("base_probe",))
    make_package(plugins, "transitive_probe", installed=installed, requires=("dependent_probe",))
    make_package(plugins, "unrelated_probe", always=False,
                 enabled_default=True, shared_rig=True)
    make_package(plugins, "base_probe_extra", installed=True)
    make_package(plugins, "gated_probe", always=False)
    make_package(plugins, "mixed_probe")
    write_json(root / "templates/fixture.json", {"label": "fixture", "features": {}})
    write_json(root / "instance/config.json", {
        "server": {"port": 54321},
        "packages": {"enabled": ALL_ENABLED},  # Wrong layer cannot opt packages in.
        "skills": {"base_probe": {"instance_probe": "retained-instance-value"}},
    })
    for world, enabled in {
        "world": ALL_ENABLED,
        "explicit-empty": "",
        "dependency-missing": "dependent_probe,transitive_probe,content_probe",
        "middle-missing": "base_probe,transitive_probe",
        "dependent-only": "dependent_probe",
        "base-only": "base_probe",
        "exact": " base_probe_extra , BASE_PROBE,base_,missing_probe, ,base_probe_extra ",
        "pre-discovery": "",
    }.items():
        write_json(root / world / "config.json", {"packages": {"enabled": enabled}})
    write_json(root / "other/config.json", {})


def assert_visible(root, skills, expected):
    from app.core import body_slots, hooks, prompt_templates
    from app.core.extension_rig import rig_groups_for
    from app.models import character_template
    from app.plugins import registry

    assert {p.id for p in registry.packages()} == expected, "activation/dependency set differs"
    expected_verbs = {p + "_verb" for p in expected - {"content_probe", "gated_probe"}}
    assert set(skills) == expected_verbs, "always_load/default-enabled/gated verbs differ"
    assert "mixed_probe_gated" not in skills, "non-always_load gate was bypassed"
    for skill_id, skill in skills.items():
        assert skill.execute() == skill_id.removesuffix("_verb")
    assert {s.flag for s in registry.flag_specs()} == {p + "_flag" for p in expected}
    assert set(registry.default_enabled_skill_ids()) == {
        p + "_verb" for p in expected - {"content_probe"}}
    features = character_template.get_template("fixture")["features"]
    assert set(features) == expected, "character-template fragments leaked or disappeared"
    profile = {"template": "fixture"}
    assert {s.id for s in body_slots.slots_for_character("fixture", profile=profile)} == {
        p + "_slot" for p in expected}
    assert set(body_slots.prompt_fragments("fixture", profile=profile)["general"]) == {
        p + " body" for p in expected}, "body prompt contributions differ"
    assert {r["id"] for r in rig_groups_for("fixture", profile)} == (
        {"shared_group"} if "unrelated_probe" in expected else set())
    for package_id in PACKAGE_IDS:
        active = package_id in expected
        assert (registry.get_package(package_id) is not None) == active
        assert prompt_templates.template_exists(package_id + ".md") == active
        if active:
            assert prompt_templates.render(package_id + ".md") == package_id + " template"
        provider = hooks.get_provider(package_id)
        assert (provider is not None) == active, "on_load provider eligibility differs"
        if active:
            assert provider() == package_id
        assert hooks.emit(package_id) == int(active), "on_load hook eligibility differs"
        package = next((root / "plugins").glob("**/" + package_id + "/plugin.yaml")).parent
        assert (package / "onload-imported").exists() == active, "on_load imported inert code"
        imported = active and package_id not in {"content_probe", "gated_probe"}
        assert (package / "skill-imported").exists() == imported, "verb module import differs"
        assert ("plugins." + package_id + ".skill" in sys.modules) == imported


def run_child(root, world, expected, mutate, before_discovery):
    from app.core import paths
    paths.init(root / world)
    paths.init_instance(root / "instance")
    from app.core import config, config_scope, db
    from app.models import character_template
    from app.plugins import loader, registry
    loader.PLUGIN_DIR = root / "plugins"
    db.init_schema()
    # Inventory before config loading must not import code or capture activation.
    schemas = loader.manifest_config_schemas()
    assert set(schemas) == PACKAGE_IDS
    schemas.clear()
    assert set(loader.manifest_config_schemas()) == PACKAGE_IDS, "inventory exposed mutable cache"
    assert registry.packages() == [] and not loader.is_discovered()
    assert not list((root / "plugins").glob("**/*-imported"))
    assert not any(name.startswith("plugins.") for name in sys.modules)
    config.load(root / world / "config.json", instance_path=root / "instance/config.json")
    assert config.get("server.port") == 54321
    if before_discovery:
        data = config.get_all()
        data["packages"] = {"enabled": ALL_ENABLED}
        config.save(data)
    with patch.object(character_template, "get_templates_dir", return_value=root / "templates"):
        assert_visible(root, loader.load_all_plugins(), expected)
        assert set(loader.manifest_config_schemas()) == PACKAGE_IDS, "inventory lost inactive packages"
        assert config_scope.scope_of("skills.base_probe.instance_probe") == "instance"
        assert config.get("skills.base_probe.instance_probe") == "retained-instance-value"
        if mutate:
            enabled = "" if expected else ALL_ENABLED
            data = config.get_all()
            data["packages"] = {"enabled": enabled}
            config.save(data)
            config.reload()
            assert config.get("packages.enabled", "") == enabled
            assert "packages" not in json.loads((root / "instance/config.json").read_text())
            assert_visible(root, loader.load_all_plugins(), expected)
            print("PASS force reload keeps activation after real config save/reload")
        # Late installation must not bypass an empty/explicit startup allowlist.
        make_package(root / "plugins", "future_probe", installed=True)
        assert "future_probe_verb" not in loader.load_all_plugins()
        assert registry.get_package("future_probe") is None
        assert not list((root / "plugins/installed/future_probe").glob("*-imported"))
        assert "future_probe" in loader.manifest_config_schemas()
        # Merely loading another world's settings cannot partially reconfigure
        # the running process; a fresh child below uses that world's selection.
        config.load(root / "other/config.json", instance_path=root / "instance/config.json")
        assert config.get("packages.enabled", "") == ""
        assert_visible(root, loader.load_all_plugins(), expected)
    print("PASS", world, "active:", sorted(expected))


def spawn(root, world, expected=(), *, mutate=False, before_discovery=False):
    # Each child's absence assertions are independent of earlier activation.
    for marker in (root / "plugins").glob("**/*-imported"):
        marker.unlink()
    command = [sys.executable, str(Path(__file__).resolve()), "--child", str(root),
               "--world", world, "--expected", ",".join(sorted(expected))]
    if mutate:
        command.append("--mutate")
    if before_discovery:
        command.append("--before-discovery")
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith("SKILL_") and key.endswith("_ENABLED"):
            environment.pop(key)
    subprocess.run(command, check=True, cwd=ROOT, env=environment)
    future = root / "plugins/installed/future_probe"
    if future.exists():
        import shutil
        shutil.rmtree(future)  # Synthetic package only.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", type=Path)
    parser.add_argument("--world", default="world")
    parser.add_argument("--expected", default="")
    parser.add_argument("--mutate", action="store_true")
    parser.add_argument("--before-discovery", action="store_true")
    args = parser.parse_args()
    if args.child:
        expected = set(filter(None, args.expected.split(",")))
        run_child(args.child, args.world, expected, args.mutate, args.before_discovery)
        return
    with tempfile.TemporaryDirectory(prefix="world-package-activation-") as tmp:
        for installed in (False, True):
            root = Path(tmp) / ("installed-root" if installed else "repo-root")
            fixture(root, installed)
            spawn(root, "world", PACKAGE_IDS, mutate=True)
            # Fresh processes honor both directions of the persisted change.
            spawn(root, "world", mutate=True)
            spawn(root, "world", PACKAGE_IDS)
            spawn(root, "other")
            spawn(root, "explicit-empty")
            spawn(root, "dependency-missing", {"content_probe"})
            spawn(root, "middle-missing", {"base_probe"})
            spawn(root, "dependent-only")
            spawn(root, "base-only", {"base_probe"})
            spawn(root, "exact", {"base_probe_extra"})
            spawn(root, "pre-discovery", PACKAGE_IDS, before_discovery=True)
    print("PASS world package opt-in: repo/installed, contributions, dependencies, restart and scope")


if __name__ == "__main__":
    main()
