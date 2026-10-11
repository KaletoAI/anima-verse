#!/usr/bin/env python3
"""Portrait overrides persist and take precedence only for portrait routing.

Usage: ./.venv/bin/python scripts/smoke_portrait_routing.py

Derived from the UI contract: profile_workflow replaces workflow at character
position 0 for profile only; empty inherits workflow; clearing all overrides
removes position 0. Photo/expression and T-pose keep their own selections.
Round-trip through real profile persistence and a real BackendPool; no HTTP,
server or generation. Every path is isolated in temporary storage.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="portrait-routing-") as tmp:
        os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
        from app.core import paths
        paths.init(Path(tmp) / "world")
        paths.init_instance(Path(tmp) / "instance")
        from app.core import config, db, character_ops
        config.load(paths.get_config_path(), paths.get_instance_config_path())
        db.init_schema()
        from app.models.character import get_character_profile, save_character_profile
        from app.imagegen.base import ImageBackend
        from app.imagegen.selection import BackendPool
        from app.imagegen.routing import resolve_image_route

        class Backend(ImageBackend):
            def __init__(self, *args):
                super().__init__(*args)
                self._available = True

            def check_availability(self):
                return True

            def _generate(self, prompt, negative_prompt, params):
                raise AssertionError("This check must not generate images")

        pool = BackendPool([Backend(name, "", cost, "smoke", "PORTRAIT_SMOKE_") for name, cost in
                            (("Normal", 0), ("Portrait", 1), ("TPose", 2))],
                           agent_instances_provider=lambda name: {})
        assert save_character_profile("demo", {"name": "demo"}, create_new=True)
        values = {"workflow": "Normal", "profile_workflow": "Portrait*",
                  "tpose_workflow": "TPose", "loras": [], "tpose_loras": []}
        character_ops.apply_outfit_imagegen("demo", values)
        stored = get_character_profile("demo")["outfit_imagegen"]
        assert stored.get("profile_workflow") == "Portrait*", stored
        for occasion, expected in (("profile", "Portrait"), ("photo", "Normal"),
                                   ("expression", "Normal"), ("tpose", "TPose")):
            route = resolve_image_route(occasion, character="demo", pool=pool)
            assert (route.backend.name, route.position) == (expected, 0), route
        values["profile_workflow"] = ""
        character_ops.apply_outfit_imagegen("demo", values)
        assert resolve_image_route("profile", character="demo", pool=pool).backend.name == "Normal"
        character_ops.apply_outfit_imagegen("demo", {"profile_workflow": "Portrait"})
        assert resolve_image_route("profile", character="demo", pool=pool).backend.name == "Portrait"
        character_ops.apply_outfit_imagegen("demo", {})
        assert get_character_profile("demo")["outfit_imagegen"] == {}
        assert resolve_image_route("profile", character="demo", pool=pool).position is None
        print("PASS: portrait override persistence, precedence, inheritance and clearing")


if __name__ == "__main__":
    main()
