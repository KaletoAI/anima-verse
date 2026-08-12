"""Standalone check: scene consolidation idle threshold follows the config.

Run: ./.venv/bin/python scripts/test_scene_idle_config.py
No server, no world DB — stubs config.get and checks the resolution rules:
memory.scene_idle_minutes when set, otherwise the 30-minute default,
clamped to >= 1 and never crashing on garbage values.
"""
import sys

sys.path.insert(0, ".")

from app.core import config
from app.core import scene_manager


def check(name: str, cond: bool):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        sys.exit(1)


def with_cfg(value):
    orig = config.get
    config.get = lambda key, default=None: value if key == "memory.scene_idle_minutes" else orig(key, default)
    try:
        return scene_manager.scene_idle_minutes()
    finally:
        config.get = orig


check("default is 30 min", with_cfg(None) == 30.0)
check("empty string falls back to default", with_cfg("") == 30.0)
check("configured value wins", with_cfg(45) == 45.0)
check("string value is coerced", with_cfg("90") == 90.0)
check("clamped to at least 1 min", with_cfg(0) == 1.0)
check("garbage falls back to default", with_cfg("abc") == 30.0)
print("OK")
