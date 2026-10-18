#!/usr/bin/env python3
"""Smoke: routing seeds are defaults, while custom routes remain overrides.

Usage: ./.venv/bin/python scripts/smoke_config_routing_seed.py

Hand-derived expectations from the configuration deviation-only contract:
A: DEBUG is the sole stored override; the required creature chain stays in
memory. Fails on old code at commit b3bfabb3: unchanged save stores routing.
B: the migration prepends quadruped-local, then scans backend declaration
order: mesh-rig-unirig precedes the appended generic rig-x. All three persist.
C: only an explicit tpose source (including []) produces tpose_view.
D: the shipped two-member chain prunes, a one-member override survives, and
reset restores the two-member default in memory while removing it from disk.
E: a loaded world-only config contains no instance deviations, so save works.
All storage is temporary; paths are initialized before any world-DB import.
"""
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        from app.core import paths
        root = Path(tmp)
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import config, config_admin, config_scope
        # Persistence is under test; provider/TTS reloads have separate smokes.
        config_admin.apply_section_reloads = lambda changed, scope: []
        world = root / "world" / "config.json"
        instance = root / "instance" / "config.json"
        world.write_text("{}", encoding="utf-8")

        def load(data):
            instance.write_text(json.dumps(data), encoding="utf-8")
            config.load(world, instance)

        def save():
            config_admin.save_layer("instance", config_admin.layer_view("instance"))
            return json.loads(instance.read_text(encoding="utf-8"))

        default = ["quadruped-local", "mesh-rig-unirig"]
        load({"server": {"log_level": "DEBUG"}})
        assert config.get("image_generation.routing.rig_creature") == default
        assert save() == {"server": {"log_level": "DEBUG"}}, "A: unchanged save persisted routing seeds"
        print("PASS A: unchanged fresh instance save")

        backends = config._default_mesh_backend_entries() + [
            {"name": "rig-x", "api_type": "openai_mesh", "category": "mesh2rig", "mesh_rig": "generic"}]
        load({"image_generation": {"backends": backends}})
        assert save()["image_generation"]["routing"]["rig_creature"] == [
            "quadruped-local", "mesh-rig-unirig", "rig-x"]
        print("PASS B: custom generic rigger persists in declaration order")

        for source, expected in (({"tpose": ["q*"]}, ["q*"]), ({"profile": ["q"]}, None),
                                 ({"tpose": []}, [])):
            load({"image_generation": {"routing": source}})
            routing = config.get("image_generation.routing")
            if expected is None:
                assert "tpose_view" not in routing
            else:
                assert routing["tpose_view"] == expected
        print("PASS C: T-pose view copies only explicit sources")

        assert config_scope.shipped_default("image_generation.routing.rig_creature") == (True, default)
        assert config_scope.shipped_tree("instance")["image_generation"]["routing"]["rig_creature"] == default
        load({"image_generation": {"routing": {"rig_creature": ["mesh-rig-unirig"]}}})
        assert save() == {"image_generation": {"routing": {"rig_creature": ["mesh-rig-unirig"]}}}
        config_admin.save_layer("instance", config_admin.layer_view("instance"),
                               resets=["image_generation.routing.rig_creature"])
        assert "rig_creature" not in json.loads(instance.read_text()).get("image_generation", {}).get("routing", {})
        assert config.get("image_generation.routing.rig_creature") == default
        print("PASS D: shipped default, override and reset")

        # Match smoke_config_scope part_3: no initialized instance path.
        paths._instance_dir = None
        config.load(world)
        config.save(config.get_all())
        assert json.loads(world.read_text()) == {}
        print("PASS E: world-only save")
    print("OK — routing seed cases A–E passed")


if __name__ == "__main__":
    main()
