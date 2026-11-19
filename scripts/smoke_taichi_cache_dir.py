#!/usr/bin/env python3
"""The Taichi offline kernel cache folder (app/core/gpu_compute.py ``_cache_dir``) is per instance / per user,
never a fixed folder in the shared temp directory (review finding 06C#5).

Usage:
    ./.venv/bin/python scripts/smoke_taichi_cache_dir.py

No world, no server, no Taichi start: only the path function is called, with throwaway dirs.

EXPECTED, from the rule in the ``_cache_dir`` docstring:
[T1] instance chosen (``paths.init_instance(<tmp>/inst)``) -> ``<tmp>/inst/.taichi-cache/vulkan`` and
     ``.../cpu``; both exist, mode 0o700 on the arch folder.
[T2] no instance, ``XDG_CACHE_HOME=<tmp>/xdg`` -> ``<tmp>/xdg/anima-verse/taichi-cache/cpu``.
[T3] no instance, no XDG_CACHE_HOME, ``HOME=<tmp>/home`` -> ``<tmp>/home/.cache/anima-verse/taichi-cache/cpu``.
[T4] no case lands under ``tempfile.gettempdir()/anima-taichi-cache`` (the old fixed path).
     FAILS on the old code (commit 8fa2d763f): every call returned ``<gettempdir>/anima-taichi-cache/<arch>``.
"""
import os
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="smoke_taichi_cache_")).resolve()
os.environ["XDG_CACHE_HOME"] = str(TMP / "xdg")

from app.core import paths  # noqa: E402
from app.core import gpu_compute as gc  # noqa: E402

fails = []


def check(tag, ok, msg=""):
    print(f"[{tag}] {'PASS' if ok else 'FAIL'} {msg}")
    if not ok:
        fails.append(tag)


old = os.path.join(tempfile.gettempdir(), "anima-taichi-cache")
seen = []

# T2 / T3 first, before an instance is chosen
d = gc._cache_dir("cpu"); seen.append(d)
check("T2", d == str(TMP / "xdg" / "anima-verse" / "taichi-cache" / "cpu") and os.path.isdir(d), d)
del os.environ["XDG_CACHE_HOME"]
os.environ["HOME"] = str(TMP / "home")
d = gc._cache_dir("cpu"); seen.append(d)
check("T3", d == str(TMP / "home" / ".cache" / "anima-verse" / "taichi-cache" / "cpu"), d)

paths.init_instance(str(TMP / "inst"))
inst = paths.get_instance_dir()
v, c = gc._cache_dir("vulkan"), gc._cache_dir("cpu"); seen += [v, c]
check("T1", v == str(inst / ".taichi-cache" / "vulkan") and c == str(inst / ".taichi-cache" / "cpu")
      and os.path.isdir(v) and stat.S_IMODE(os.stat(v).st_mode) == 0o700, f"{v} {c}")
check("T4", not any(s.startswith(old) for s in seen), str(seen))

print("FAIL" if fails else "ALL PASS", fails)
sys.exit(1 if fails else 0)
