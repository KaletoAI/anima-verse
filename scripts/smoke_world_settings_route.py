#!/usr/bin/env python3
"""Smoke the world settings functions directly, without HTTP or app.server.

Usage: ./.venv/bin/python scripts/smoke_world_settings_route.py

Hand-derived expectations from I5 and Task 3:
A: An empty world has no overrides; groups follow WORLD_GROUPS and include
   gameplay/calendar. Providers are instance settings, absent from schema.
Setup: Both existing layer files contain exactly {}.
B: Saving chat.top_p=0.9 writes exactly that world override; the instance
   file stays byte-identical to {}. The response exposes save metadata.
C: Providers are refused with 400 naming providers; [], "x", and null are
   non-object bodies and receive 400.
D: Reposting GET values changes neither file's mtime_ns; materialized shipped
   seasons remain in memory but are pruned from the file (Review Focus 4).
E: Resetting chat.top_p restores the shipped value, leaving {} and no overrides.
F: An unreadable existing world file is protected with 409 and left intact.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="world-settings-smoke-") as tmp:
        root = Path(tmp)
        world = root / "world"
        instance = root / "instance"
        world.mkdir()
        instance.mkdir()
        os.environ["STORAGE_DIR"] = str(world)
        os.environ["INSTANCE_DIR"] = str(instance)
        from app.core import paths
        paths.init(world)
        paths.init_instance(instance)
        from app.core import config
        from app.core.config_schema import WORLD_GROUPS
        from app.core.game_time import default_seasons_config
        from app.routes.world_settings import get_world_settings, _put_sync
        from fastapi import HTTPException

        world_file = world / "config.json"
        instance_file = instance / "config.json"
        world_file.write_text("{}", encoding="utf-8")
        instance_file.write_text("{}", encoding="utf-8")
        config.load(world_file, instance_path=instance_file)
        initial_instance = instance_file.read_bytes()
        payload = get_world_settings()
        assert payload["world"] == "world"
        assert payload["overrides"] == []
        ids = [g["id"] for g in payload["groups"]]
        assert ids == [g["id"] for g in WORLD_GROUPS if g["id"] in ids]
        assert {"gameplay", "calendar"} <= set(ids)
        assert "providers" not in payload["schema"]
        for group in payload["groups"]:
            assert group["sections"] == [key for key, section in payload["schema"].items()
                                         if section.get("world_group") == group["id"]]
        assert set(payload["use_case_defaults"]) == {"use_cases", "families", "defaults"}
        assert payload["values"]["game_seasons"] == default_seasons_config()
        print("A: empty-world payload passed")

        def put(body):
            if isinstance(body, dict):
                body = {**body, "base_revision": get_world_settings()["revision"]}
            return _put_sync(body)

        saved = put({"values": {"chat": {"top_p": 0.9}}})
        assert json.loads(world_file.read_text()) == {"chat": {"top_p": 0.9}}
        assert saved["overrides"] == ["chat.top_p"]
        assert instance_file.read_bytes() == initial_instance
        assert {"changed_sections", "reloaded", "warnings"} <= saved.keys()
        print("B: world-only save passed")

        def refused(body, code, detail=""):
            try:
                put(body)
            except HTTPException as exc:
                assert exc.status_code == code
                assert detail in exc.detail
            else:
                raise AssertionError(f"Expected HTTP {code}")

        refused({"values": {"providers": []}}, 400, "providers")
        for body in ([], "x", None):
            refused(body, 400)
        print("C: invalid bodies passed")
        config.reload()
        values = get_world_settings()["values"]
        assert values["game_seasons"] == default_seasons_config()
        mtimes = (world_file.stat().st_mtime_ns, instance_file.stat().st_mtime_ns)
        put({"values": values})
        assert (world_file.stat().st_mtime_ns, instance_file.stat().st_mtime_ns) == mtimes
        assert json.loads(world_file.read_text()) == {"chat": {"top_p": 0.9}}
        assert instance_file.read_bytes() == initial_instance
        print("D: unchanged save and seasons pruning passed")
        reset = put({"values": get_world_settings()["values"],
                           "resets": ["chat.top_p"]})
        assert json.loads(world_file.read_text()) == {}
        assert reset["overrides"] == []
        print("E: reset passed")
        world_file.write_text("broken JSON", encoding="utf-8")
        refused({"values": {}}, 409)
        assert world_file.read_text() == "broken JSON"
        print("F: write refusal passed")
    print("OK — world settings route")


if __name__ == "__main__":
    main()
