#!/usr/bin/env python3
"""Retired backend flags cannot override global enable or character matches.

Usage: ./.venv/bin/python scripts/smoke_retired_backend_flags.py

Hand-derived expectations: backend enabled is installation-owned. Historical
instances[backend].enabled booleans must not enter the render config. Width and
height overrides and unrelated skill fields survive cleanup. Cleanup is
idempotent and does not alter profile.outfit_imagegen or other skill files.
Image config reads must not create a persisted snapshot of backend defaults.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="retired-backend-flags-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import config, db
        config.load(root / "world/config.json", paths.get_instance_config_path())
        db.init_schema()
        from app.models.character import (get_character_dir, get_character_profile,
                                          save_character_profile,
                                          save_character_skill_config)
        from app.imagegen.service import ImageService
        profile = {"name": "demo", "outfit_imagegen": {"workflow": "demo-image"}}
        save_character_profile("demo", profile, create_new=True)
        save_character_profile("demo_fresh", {"name": "demo_fresh"}, create_new=True)
        legacy = {"enabled": True, "custom": "keep", "instances": {
            "demo-image": {"enabled": False, "width": 768},
            "demo-off": {"enabled": True}, "demo-empty": {}}}
        save_character_skill_config("demo", "image_generation", legacy)
        backend = SimpleNamespace(name="demo-image", instance_enabled=True,
                                  width=1024, height=1024)
        svc = object.__new__(ImageService)
        svc._pool = SimpleNamespace(backends=[backend])
        cfg = svc._get_instance_config("demo", backend)
        assert cfg == {"width": 768, "height": 1024}, cfg
        print("OK: render configuration retains sizing, not historical enable flags")
        fresh_path = get_character_dir("demo_fresh") / "skills/image_generation.json"
        svc._get_instance_config("demo_fresh", backend)
        assert not fresh_path.exists()
        print("OK: reading defaults creates no character backend snapshots")

        from app.core.image_backend_flags_migration import remove_character_backend_flags
        skill_path = get_character_dir("demo") / "skills/image_generation.json"
        other_path = skill_path.with_name("demo_other.json")
        other_path.write_text('{"enabled": false}')
        expected = {"enabled": True, "custom": "keep", "instances": {
            "demo-image": {"width": 768}}}
        assert remove_character_backend_flags() == 2
        assert json.loads(skill_path.read_text()) == expected
        assert get_character_profile("demo")["outfit_imagegen"] == {"workflow": "demo-image"}
        assert other_path.read_text() == '{"enabled": false}'
        before = skill_path.read_bytes()
        assert remove_character_backend_flags() == 0
        assert skill_path.read_bytes() == before
        assert not fresh_path.exists()
        print("OK: cleanup removes both true/false flags, preserves overrides and is idempotent")
        # Imported archives may reintroduce obsolete flags after the first boot.
        save_character_skill_config("demo", "image_generation", {"instances": {
            "demo-image": {"enabled": False}}})
        assert remove_character_backend_flags() == 1
        assert json.loads(skill_path.read_text()) == {}
        print("OK: a later import is cleaned without retaining empty backend entries")
        print("Retired backend flag smoke passed")


if __name__ == "__main__":
    main()
