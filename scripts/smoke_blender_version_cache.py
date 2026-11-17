#!/usr/bin/env python3
"""Smoke: ``runner.version()`` caches completed probes for good and failed probes for ``NEG_TTL_S``
only, both keyed on the binary's identity (review 02#6 + follow-up).

Usage:
    ./.venv/bin/python scripts/smoke_blender_version_cache.py

No Blender, no server, no world: the "Blender" is a shell script in a temp folder that answers
``--version`` with ``Blender <v>`` (exit 0), appends one line per call to a counter file (= spawns), and
exits 1 without output while a ``fail_next`` marker exists (the marker is consumed by that call) or always
while an ``always_fail`` marker exists. The clock is a fake ``time.monotonic`` (``runner.time.monotonic``
patched to a settable value; ``subprocess`` keeps its own bound alias) — no real sleeping.

Expected, derived by hand from the rules "an exit-0 probe is cached for good; a failed one (non-zero exit,
timeout, failed start) is remembered for NEG_TTL_S = 60 s of the monotonic clock, then probed again
(re-probe when now - failed_at >= 60); key = (path, st_mtime_ns, st_ino)":
[1] fail_next set, clock 1000 → version() = "" (1 spawn). At 1000 and 1059.9 → "" with NO spawn
    (0.0 and 59.9 < 60). At 1060.0 (60.0 is not < 60) → probes again (1 spawn) → "5.2.0". The original
    runner stored "" under the path on the first failure and returned it forever.
[2] A probe that times out (subprocess.TimeoutExpired, stubbed for every call): first → "" (stub called
    once); 10 more calls within the TTL → stub still called once — a hanging binary costs its 30 s at most
    once per 60 s. After +60 s with the stub removed → real probe → "5.2.0".
[3] always_fail: 10 calls inside one TTL window → exactly 1 spawn; each answers "".
[4] A success IS cached: two calls on an unchanged binary → 1 spawn.
[5] Identity change ends the negative entry at once: after a failed probe (always_fail, clock 3000) the
    binary is replaced (new inode, "Blender 5.3.1", marker removed) at the SAME clock → probed at once →
    "5.3.1". Rewrite of the SAME inode to "Blender 5.2.4" with the mtime one second ahead → "5.2.4" (the
    original runner kept the cached "5.2.0").
[6] Discovery: the fake configured as ``image_generation.blender_executable``, fail_next set, clock 5000 →
    find_executable() = ""; at 5030 still "" (within the TTL, no spawn); at 5060 → the fake's path.
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
CLOCK = {"t": 0.0}


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def write_fake(path: Path, ver: str, state: Path) -> None:
    path.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then\n'
        f'  echo x >> "{state}/count"\n'
        f'  if [ -f "{state}/always_fail" ]; then exit 1; fi\n'
        f'  if [ -f "{state}/fail_next" ]; then rm -f "{state}/fail_next"; exit 1; fi\n'
        f'  echo "Blender {ver}"; exit 0\n'
        "fi\n"
        "exit 2\n", encoding="utf-8")
    path.chmod(0o755)


def spawns(state: Path) -> int:
    f = state / "count"
    return len(f.read_text().splitlines()) if f.is_file() else 0


def reset():
    runner._version_cache.clear()
    runner._version_failed.clear()


def main() -> int:
    check(runner.NEG_TTL_S == 60.0, f"NEG_TTL_S is 60 s (got {runner.NEG_TTL_S})")
    with tempfile.TemporaryDirectory(prefix="smoke-blender-version-") as tmp, \
            patch.object(runner.time, "monotonic", lambda: CLOCK["t"]):
        tmp = Path(tmp)
        state = tmp / "state"
        state.mkdir()
        exe = tmp / "blender"
        write_fake(exe, "5.2.0", state)

        # [1]
        reset()
        CLOCK["t"] = 1000.0
        (state / "fail_next").touch()
        n0 = spawns(state)
        check(runner.version(str(exe)) == "" and spawns(state) - n0 == 1, "[1] failing probe -> '' (1 spawn)")
        got = runner.version(str(exe))
        CLOCK["t"] = 1059.9
        got2 = runner.version(str(exe))
        check(got == "" and got2 == "" and spawns(state) - n0 == 1,
              f"[1] within the TTL: '' without spawning (spawns {spawns(state) - n0})")
        CLOCK["t"] = 1060.0
        got = runner.version(str(exe))
        check(got == "5.2.0" and spawns(state) - n0 == 2,
              f"[1] after the TTL: probes again -> '5.2.0' (got {got!r}, spawns {spawns(state) - n0})")

        # [2]
        reset()
        CLOCK["t"] = 2000.0
        calls = {"n": 0}

        def always_timeout(cmd, *a, **kw):
            calls["n"] += 1
            raise subprocess.TimeoutExpired(cmd, 30)

        with patch.object(runner.subprocess, "run", always_timeout):
            first = runner.version(str(exe))
            rest = []
            for i in range(10):
                CLOCK["t"] = 2000.0 + i * 5.0
                rest.append(runner.version(str(exe)))
        check(first == "" and set(rest) == {""} and calls["n"] == 1,
              f"[2] timeout remembered: 11 calls, 1 probe (got {calls['n']})")
        CLOCK["t"] = 2060.0
        got = runner.version(str(exe))
        check(got == "5.2.0", f"[2] after the TTL the real probe -> '5.2.0' (got {got!r})")

        # [3]
        reset()
        CLOCK["t"] = 2500.0
        (state / "always_fail").touch()
        n0 = spawns(state)
        answers = []
        for i in range(10):
            CLOCK["t"] = 2500.0 + i * 6.0  # 2500 .. 2554, all < 2560
            answers.append(runner.version(str(exe)))
        check(set(answers) == {""} and spawns(state) - n0 == 1,
              f"[3] always failing: 10 calls in one window, 1 spawn (got {spawns(state) - n0})")
        (state / "always_fail").unlink()

        # [4]
        reset()
        n0 = spawns(state)
        runner.version(str(exe))
        runner.version(str(exe))
        check(spawns(state) - n0 == 1, f"[4] success cached: 1 spawn (got {spawns(state) - n0})")

        # [5]
        reset()
        CLOCK["t"] = 3000.0
        (state / "always_fail").touch()
        check(runner.version(str(exe)) == "", "[5] failing probe on the old binary")
        (state / "always_fail").unlink()
        new = tmp / "blender.new"
        write_fake(new, "5.3.1", state)
        os.replace(new, exe)
        got = runner.version(str(exe))
        check(got == "5.3.1", f"[5] new inode at the same path, same clock -> '5.3.1' (got {got!r})")
        st = exe.stat()
        write_fake(exe, "5.2.4", state)  # same inode, rewritten
        os.utime(exe, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        check(exe.stat().st_ino == st.st_ino, "[5] rewrite kept the inode")
        got = runner.version(str(exe))
        check(got == "5.2.4", f"[5] same inode, new mtime -> '5.2.4' (got {got!r})")

        # [6]
        write_fake(exe, "5.2.0", state)
        os.utime(exe, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
        reset()
        (state / "fail_next").touch()

        def config(key, default):
            return str(exe) if key == "image_generation.blender_executable" else default

        with patch.object(runner, "_config", config):
            CLOCK["t"] = 5000.0
            first = runner.find_executable()
            n0 = spawns(state)
            CLOCK["t"] = 5030.0
            second = runner.find_executable()
            no_spawn = spawns(state) == n0
            CLOCK["t"] = 5060.0
            third = runner.find_executable()
        check(first == "" and second == "" and no_spawn and third == str(exe),
              f"[6] discovery recovers after the TTL ({first!r}, {second!r}, spawned={not no_spawn}, {third!r})")
    reset()
    print(f"\n{'FAILED: ' + str(len(FAILS)) if FAILS else 'all passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
