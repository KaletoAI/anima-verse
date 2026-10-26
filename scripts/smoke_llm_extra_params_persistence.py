#!/usr/bin/env python3
"""Check that per-LLM request-body fields survive an instance save and reload.

Usage: ./.venv/bin/python scripts/smoke_llm_extra_params_persistence.py

The expected values are literal: two entries on one provider retain distinct
body fields despite using the same model, and a third entry has none. Storage
is temporary; no real world configuration is read or modified.
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
        from app.core import config, config_admin
        config_admin.apply_section_reloads = lambda changed, scope: []
        world = root / "world" / "config.json"
        instance = root / "instance" / "config.json"
        world.write_text("{}", encoding="utf-8")
        entries = [
            {"name": "one", "provider": "demo", "model": "model", "tasks": [
                {"task": "chat_stream", "order": 1}, {"task": "intent", "order": 1}],
             "extra_params": {"venice_parameters": {"disable_thinking": True}}},
            {"name": "two", "provider": "demo", "model": "model", "tasks": [
                {"task": "intent", "order": 2}], "extra_params": {"seed": [1, 2]}},
            {"name": "three", "provider": "demo", "model": "other", "tasks": []},
        ]
        instance.write_text(json.dumps({"llm_routing": entries}), encoding="utf-8")
        config.load(world, instance)
        config_admin.save_layer("instance", config_admin.layer_view("instance"))
        stored = json.loads(instance.read_text(encoding="utf-8"))["llm_routing"]
        assert stored[0]["extra_params"] == {"venice_parameters": {"disable_thinking": True}}
        assert stored[1]["extra_params"] == {"seed": [1, 2]}
        assert not stored[2].get("extra_params")
        config.load(world, instance)
        reloaded = config.get("llm_routing")
        assert reloaded[0]["extra_params"] == {"venice_parameters": {"disable_thinking": True}}
        assert reloaded[1]["extra_params"] == {"seed": [1, 2]}
        assert not reloaded[2].get("extra_params")
        # A literal stop sequence is request data, not a masked API key.
        edited = config_admin.layer_view("instance")
        edited["llm_routing"][0]["extra_params"]["stop"] = ["***"]
        edited["llm_routing"][1]["extra_params"]["stop"] = ["***end"]
        config_admin.save_layer("instance", edited)
        config.load(world, instance)
        reloaded = config.get("llm_routing")
        assert reloaded[0]["extra_params"]["stop"] == ["***"]
        assert reloaded[1]["extra_params"]["stop"] == ["***end"]
        # A stale editor rebases over an unrelated settings change.
        revision = config_admin.layer_revision("instance")
        stale = config_admin.layer_view("instance")
        stale["llm_routing"][0]["extra_params"]["stop"] = ["***fresh"]
        other = config_admin.layer_view("instance")
        other["server"] = {"log_level": "DEBUG"}
        config_admin.save_layer("instance", other)
        config_admin.save_layer("instance", stale, base_revision=revision)
        config.load(world, instance)
        assert config.get("llm_routing")[0]["extra_params"]["stop"] == ["***fresh"]
        assert config.get("server.log_level") == "DEBUG"
    print("LLM extra_params: per-entry save and reload OK")


if __name__ == "__main__":
    main()
