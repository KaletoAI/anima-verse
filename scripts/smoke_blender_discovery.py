#!/usr/bin/env python3
"""Smoke: Blender discovery picks the newest usable version.

Usage:
    ./.venv/bin/python scripts/smoke_blender_discovery.py

Rules (spec plan-pose-animation-unimate-umsetzung.md Task 1):
  usable = MIN_VERSION (4,2) <= version < MAX_VERSION_EXCL (5,0)
  candidates = which("blender") + /opt/blender*/blender + /usr/local/blender*/blender
               + ~/tools/blender*/blender
  pick = newest usable candidate; configured path wins but must be usable.
Cases (expected executable):
  A  PATH=4.0.2, ~/tools 4.2.23              -> ~/tools 4.2.23   (the 2026-10-10 regression)
  B  PATH=4.0.2, ~/tools 4.2.23 + 5.2.2      -> ~/tools 4.2.23   (5.x excluded)
  C  ~/tools 4.2.5 + 4.5.3                   -> 4.5.3            (newest usable)
  D  only 4.0.2                              -> ""  and status()["error"] names "4.0.2" and "4.2"
  E  configured = 4.0.2 path, ~/tools 4.2.23 -> ""  (configured wins, but is rejected: no silent switch)
  F  configured = 4.2.23 path                -> that path
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.blender import runner


def fake_blender(path, ver):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\necho 'Blender {ver}'\n", encoding="utf-8")
    path.chmod(0o755)
    return str(path)


def main():
    original_glob = Path.glob

    def isolated_glob(path, pattern):
        if str(path) == "/" and pattern.startswith(("opt/", "usr/local/")):
            return iter(())
        return original_glob(path, pattern)

    cases = [
        ("A", "4.0.2", ["4.2.23"], "", "4.2.23"),
        ("B", "4.0.2", ["4.2.23", "5.2.2"], "", "4.2.23"),
        ("C", "", ["4.2.5", "4.5.3"], "", "4.5.3"),
        ("D", "4.0.2", [], "", ""),
        ("E", "4.0.2", ["4.2.23"], "4.0.2", ""),
        ("F", "", ["4.2.23"], "4.2.23", "4.2.23"),
    ]
    for label, path_ver, tool_versions, configured_ver, selected_ver in cases:
        with tempfile.TemporaryDirectory(prefix="av-discovery-") as tmp:
            home = Path(tmp)
            binaries = {}
            if path_ver:
                binaries[path_ver] = fake_blender(home / "bin" / "blender", path_ver)
            for ver in tool_versions:
                binaries[ver] = fake_blender(home / "tools" / f"blender-{ver}" / "blender", ver)
            configured = binaries.get(configured_ver, "")
            expected = binaries.get(selected_ver, "")
            def config(key, default):
                return configured if key == "image_generation.blender_executable" else default
            with patch.dict(os.environ, {"PATH": str(home / "bin"), "HOME": tmp}), \
                    patch.object(runner, "_config", config), \
                    patch.object(Path, "glob", isolated_glob):
                runner._version_cache.clear()
                actual = runner.find_executable()
                assert actual == expected, f"{label}: expected {expected!r}, got {actual!r}"
                st = runner.status()
                if label in ("D", "E"):
                    assert "4.2" in st["error"], st
                    assert "4.0.2" in st["error"], st
                    assert st["usable"] is False, st
                    assert st["rejected"][0]["executable"] == binaries["4.0.2"], st
                    assert runner.run("missing")["error"] == st["error"]
                else:
                    assert st["usable"] is True and st["error"] == "", st
                if label == "B":
                    assert {item["version"] for item in st["rejected"]} == {"4.0.2", "5.2.2"}, st
            print(f"{label}: passed")
    runner._version_cache.clear()
    print("all checks passed")


if __name__ == "__main__":
    main()
