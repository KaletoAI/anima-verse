#!/usr/bin/env python3
"""Smoke: ``runner.version()`` caches only completed probes, keyed on the binary's identity
(review 02#6).

Usage:
    ./.venv/bin/python scripts/smoke_blender_version_cache.py

No Blender, no server, no world: the "Blender" is a shell script in a temp folder that answers
``--version`` with ``Blender <v>`` (exit 0), appends one line per call to a counter file, and exits 1
without output while a ``fail_next`` marker exists (the marker is consumed by that call).

Expected, derived by hand from the rule "cache only an exit-0 probe, key = (path, st_mtime_ns, st_ino)":
[1] fail_next set → first version() = "" (exit 1, not cached); the second call probes again and returns
    "5.2.0". The old runner stored "" under the path on the first failure and returned it forever.
[2] A probe that times out (subprocess.TimeoutExpired, stubbed once) → "" and not cached; the next call
    probes the real script → "5.2.0".
[3] Two calls on an unchanged binary → the script ran exactly once (counter = 1): a success IS cached.
[4] Upgrade in place, new inode: a new file "Blender 5.3.1" os.replace'd over the path → "5.3.1" (the old
    runner kept the cached "5.2.0"). Rewrite of the SAME inode to "Blender 5.2.4" with the mtime moved
    one second ahead → "5.2.4".
[5] Discovery: the fake configured as ``image_generation.blender_executable``; with fail_next set the
    first find_executable() = "" and the second = the fake's path (the old runner kept rejecting it).
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.blender import runner  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def write_fake(path: Path, ver: str, state: Path) -> None:
    path.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then\n'
        f'  echo x >> "{state}/count"\n'
        f'  if [ -f "{state}/fail_next" ]; then rm -f "{state}/fail_next"; exit 1; fi\n'
        f'  echo "Blender {ver}"; exit 0\n'
        "fi\n"
        "exit 2\n", encoding="utf-8")
    path.chmod(0o755)


def probes(state: Path) -> int:
    f = state / "count"
    return len(f.read_text().splitlines()) if f.is_file() else 0


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="smoke-blender-version-") as tmp:
        tmp = Path(tmp)
        state = tmp / "state"
        state.mkdir()
        exe = tmp / "blender"
        write_fake(exe, "5.2.0", state)

        # [1]
        runner._version_cache.clear()
        (state / "fail_next").touch()
        check(runner.version(str(exe)) == "", "[1] failing probe -> ''")
        got = runner.version(str(exe))
        check(got == "5.2.0", f"[1] next call probes again -> '5.2.0' (got {got!r})")

        # [2]
        runner._version_cache.clear()
        real_run = subprocess.run
        calls = {"n": 0}

        def once_timeout(cmd, *a, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise subprocess.TimeoutExpired(cmd, 30)
            return real_run(cmd, *a, **kw)

        with patch.object(runner.subprocess, "run", once_timeout):
            first = runner.version(str(exe))
            second = runner.version(str(exe))
        check(first == "" and second == "5.2.0",
              f"[2] timeout not cached ({first!r}, then {second!r})")

        # [3]
        runner._version_cache.clear()
        before = probes(state)
        runner.version(str(exe))
        runner.version(str(exe))
        check(probes(state) - before == 1, f"[3] success cached: 1 probe (got {probes(state) - before})")

        # [4]
        new = tmp / "blender.new"
        write_fake(new, "5.3.1", state)
        os.replace(new, exe)
        got = runner.version(str(exe))
        check(got == "5.3.1", f"[4] new inode at the same path -> '5.3.1' (got {got!r})")
        st = exe.stat()
        write_fake(exe, "5.2.4", state)  # same inode, rewritten
        os.utime(exe, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        check(exe.stat().st_ino == st.st_ino, "[4] rewrite kept the inode")
        got = runner.version(str(exe))
        check(got == "5.2.4", f"[4] same inode, new mtime -> '5.2.4' (got {got!r})")

        # [5]
        write_fake(exe, "5.2.0", state)
        os.utime(exe, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
        runner._version_cache.clear()
        (state / "fail_next").touch()

        def config(key, default):
            return str(exe) if key == "image_generation.blender_executable" else default

        with patch.object(runner, "_config", config):
            first = runner.find_executable()
            second = runner.find_executable()
        check(first == "" and second == str(exe),
              f"[5] discovery recovers ({first!r}, then {second!r})")
    runner._version_cache.clear()
    print(f"\n{'FAILED: ' + str(len(FAILS)) if FAILS else 'all passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
