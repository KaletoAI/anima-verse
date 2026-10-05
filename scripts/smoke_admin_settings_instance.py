"""Smoke instance admin routes using temporary, existing {} layer files.

Usage: ./.venv/bin/python scripts/smoke_admin_settings_instance.py

Hand-derived expectations from spec I4 and Review Focus 2/4:
A raw has server but no chat; schema has no game_calendar.
B unchanged {values: raw, resets: []} preserves bytes and mtime_ns of both files.
C world chat values are HTTP 400.
D server.timezone Europe/Berlin stores exactly that override and its origin.
E resetting server.timezone stores {} and clears origin.
F duplicate providers named local are HTTP 400 mentioning duplicate name 'local'.
G [], "x", null bodies and malformed values/resets are HTTP 400 before merging.
H origin and shipped-default routes expose only instance data.
I resetting backends validates final capabilities; an invalid final chain is 400.
J resetting invalid LLM routing succeeds; unreadable instance storage is 409.
K clearing discovered LoRAs preserves manual entries and the world file.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

class Request:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return copy.deepcopy(self.body)

with tempfile.TemporaryDirectory(prefix="admin-settings-instance-") as root:
    world = Path(root) / "world"
    instance = Path(root) / "instance"
    for folder in (world, instance):
        folder.mkdir()
        (folder / "config.json").write_text("{}")
    os.environ.update(STORAGE_DIR=str(world), INSTANCE_DIR=str(instance))
    from app.core import paths
    paths.init(world)
    paths.init_instance(instance)
    from app.core import config, config_admin, config_scope
    from app.routes import admin_settings as adm
    from fastapi import HTTPException
    config.load(world / "config.json", instance / "config.json")
    config_admin.apply_section_reloads = lambda keys, scope: []

    def snapshot():
        return [(p.read_bytes(), p.stat().st_mtime_ns)
                for p in (world / "config.json", instance / "config.json")]

    def save(values, resets=None):
        return asyncio.run(adm.settings_save(Request({"values": values, "resets": resets or []}), user=None))

    def refused(body, status=400, detail=""):
        before = snapshot()
        try:
            asyncio.run(adm.settings_save(Request(body), user=None))
        except HTTPException as exc:
            assert exc.status_code == status and detail in str(exc.detail), exc
        else:
            raise AssertionError("Expected HTTP refusal")
        assert snapshot() == before

    raw = adm.settings_raw(user=None)
    assert "chat" not in raw and "server" in raw, "A raw must be instance-only"
    assert "game_calendar" not in adm.settings_schema(user=None)
    before = snapshot()
    result = save(raw)
    assert result["status"] == "success" and snapshot() == before, "B unchanged files"
    refused({"values": {"chat": {}}, "resets": []})
    values = copy.deepcopy(raw)
    values["server"]["timezone"] = "Europe/Berlin"
    result = save(values)
    assert json.loads((instance / "config.json").read_text()) == {"server": {"timezone": "Europe/Berlin"}}
    assert result["overrides"] == ["server.timezone"]
    assert adm.settings_origin(user=None) == {"overrides": ["server.timezone"]}
    result = save(values, ["server.timezone"])
    assert json.loads((instance / "config.json").read_text()) == {} and result["overrides"] == []
    refused({"values": {"providers": [{"name": "local"}, {"name": "local"}]}, "resets": []}, detail="duplicate name 'local'")
    for body in ([], "x", None, {}, {"values": [], "resets": []}, {"values": {}, "resets": None}):
        with patch.object(config_admin, "prepare_layer", side_effect=AssertionError("type check must run first")):
            refused(body)
    assert adm.settings_shipped_defaults(user=None) == config_scope.shipped_tree("instance")
    assert "chat" not in adm.settings_shipped_defaults(user=None)
    # A custom photo backend becomes a mesh-only shipped list after reset.
    custom = {"image_generation": {"backends": [{"name": "photo-only", "api_type": "openai_diffusion"}], "routing": {"photo": ["*"]}}}
    refused({"values": custom, "resets": ["image_generation.backends"]})
    save({"llm_routing": [{"name": "a", "tasks": [{"task": "chat", "order": 1}]}, {"name": "b", "tasks": [{"task": "chat", "order": 1}]}]}, ["llm_routing"])
    (instance / "config.json").write_text("{broken")
    refused({"values": {}, "resets": []}, status=409)
    (instance / "config.json").write_text("{}")
    config.load(world / "config.json", instance / "config.json")
    save({"image_generation": {"lora_triggers": [{"name": "manual"}, {"name": "found", "source": "discovered"}]}})
    world_before = (world / "config.json").read_bytes()
    result = adm.lora_library_clear_discovered(user=None)
    assert result == {"removed": 1, "lora_triggers": [{"name": "manual"}]}
    assert (world / "config.json").read_bytes() == world_before
    print("PASS A–K instance admin routes")
