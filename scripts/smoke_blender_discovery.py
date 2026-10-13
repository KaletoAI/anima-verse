#!/usr/bin/env python3
"""Smoke: Blender discovery picks the newest usable version.

Usage:
    ./.venv/bin/python scripts/smoke_blender_discovery.py

Rules (spec plan-pose-animation-unimate-umsetzung.md Task 1):
  usable = MIN_VERSION (5,2) <= version < MAX_VERSION_EXCL (6,0)
  candidates = which("blender") + /opt/blender*/blender + /usr/local/blender*/blender
               + ~/tools/blender*/blender
  pick = newest usable candidate; configured path wins but must be usable.
Cases (expected executable, derived by hand from 5.2 <= version < 6.0):
  A  PATH=4.0.2, ~/tools 4.2.23 + 5.2.2      -> 5.2.2; both 4.x are below 5.2
  B  PATH=4.0.2, ~/tools 4.2.23              -> ""; both below 5.2, error names 4.2.23 and 5.2
  C  ~/tools 5.0.1 + 5.2.2                  -> 5.2.2; 5.0.1 is below 5.2 and rejected
  D  ~/tools 5.2.2 + 6.0.0                  -> 5.2.2; 6.0.0 reaches the exclusive ceiling
  E  configured=4.2.23, ~/tools 5.2.2        -> ""; configured is below 5.2, no silent switch
  F  configured=5.2.2                       -> that path; it meets the inclusive floor
  G  ~/tools 5.1.9                          -> ""; below 5.2, error names 5.1.9 and 5.2
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
        ("A", "4.0.2", ["4.2.23", "5.2.2"], "", "5.2.2"),   # newest usable; 4.x rejected
        ("B", "4.0.2", ["4.2.23"], "", ""),                 # nothing usable: error names 4.2.23 and 5.2
        ("C", "", ["5.0.1", "5.2.2"], "", "5.2.2"),         # 5.0.1 rejected
        ("D", "", ["5.2.2", "6.0.0"], "", "5.2.2"),         # 6.x excluded
        ("E", "", ["4.2.23", "5.2.2"], "4.2.23", ""),       # configured wins but is rejected: no silent switch
        ("F", "", ["5.2.2"], "5.2.2", "5.2.2"),
        ("G", "", ["5.1.9"], "", ""),
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
                if label in ("B", "E", "G"):
                    assert "5.2" in st["error"], st
                    assert ("5.1.9" if label == "G" else "4.2.23") in st["error"], st
                    assert st["usable"] is False, st
                    if label == "E":
                        assert st["rejected"][0]["executable"] == configured, st
                    assert runner.run("missing")["error"] == st["error"]
                else:
                    assert st["usable"] is True and st["error"] == "", st
                if label in ("A", "B"):
                    assert {item["version"] for item in st["rejected"]} == {"4.0.2", "4.2.23"}, st
                if label == "C":
                    assert {item["version"] for item in st["rejected"]} == {"5.0.1"}, st
                if label == "D":
                    assert {item["version"] for item in st["rejected"]} == {"6.0.0"}, st
                if label == "G":
                    assert {item["version"] for item in st["rejected"]} == {"5.1.9"}, st
            print(f"{label}: passed")
    runner._version_cache.clear()
    print("all checks passed")


if __name__ == "__main__":
    main()
