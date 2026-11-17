#!/usr/bin/env python3
"""Smoke: ``runner.run`` answers ``{"ok": False, …}`` on every host-side failure instead of raising,
and a timeout leaves the tail of Blender's output in the log (review 02#5).

Usage:
    ./.venv/bin/python scripts/smoke_blender_run_failures.py

No Blender, no server, no world, no instance. The "Blender" is a Python script in a temp folder: it answers
``--version`` with ``Blender 5.2.0``; as a run it does what ``FAKE_MODE`` says (the runner copies the
environment into the child). It is configured through a stubbed ``runner._config``
(``image_generation.blender_executable``) and found by the real discovery; the slot folder is pinned
into the temp folder. Script name ``meshopt`` (only its path reaches the fake).

Expected, derived by hand from the contract "``ok`` False covers everything" (runner.run docstring):
[1] The input vanishes between the ``is_file`` check and the copy (``shutil.copy2`` stubbed to raise
    FileNotFoundError) → ok False, error starts "input 'model' unreadable". The old runner let the
    FileNotFoundError escape.
[2] The binary is gone after discovery (``status`` stubbed to name a missing path) → ok False, error starts
    "blender could not be started". Old: FileNotFoundError escaped from subprocess.run.
[3] The binary lost +x (mode 0644) → same as [2] (PermissionError). Old: escaped.
[4] Output not valid UTF-8 (bytes ff fe on stdout and stderr), no result, exit 1 → ok False,
    error "script wrote no result (exit 1)". Old: UnicodeDecodeError escaped from the decoding.
[5] Same garbage output, but the result file says ok → ok True (output is never parsed).
[6] Timeout: the fake writes "TAIL-MARKER-6" to stderr, then sleeps 30 s; timeout_s = 1 → ok False,
    error "timeout after 1s", and the ERROR record of the timeout contains "TAIL-MARKER-6" (the old
    runner logged only "timeout after 1s").
"""
import json
import logging
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.blender import runner  # noqa: E402

FAILS = []

FAKE = """#!{python}
import json, os, sys
if sys.argv[1:2] == ["--version"]:
    print("Blender 5.2.0")
    sys.exit(0)
args = json.loads(open(sys.argv[-1], encoding="utf-8").read())
mode = os.environ.get("FAKE_MODE", "")
if mode in ("garbage", "garbage_ok"):
    sys.stdout.buffer.write(b"\\xff\\xfe imported \\xff\\n")
    sys.stderr.buffer.write(b"\\xfe\\xff error \\xff\\n")
    sys.stdout.flush(); sys.stderr.flush()
    if mode == "garbage_ok":
        open(args["result"], "w").write(json.dumps({{"ok": True, "data": {{}}, "outputs": {{}}}}))
    sys.exit(1)
if mode == "hang":
    sys.stderr.write("TAIL-MARKER-6\\n"); sys.stderr.flush()
    os.execvp("sleep", ["sleep", "30"])
open(args["result"], "w").write(json.dumps({{"ok": True, "data": {{}}, "outputs": {{}}}}))
"""


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


def safe_run(**kw):
    """runner.run, with an escaping exception turned into a FAIL marker."""
    try:
        return runner.run("meshopt", **kw)
    except Exception as e:  # noqa: BLE001 — exactly what the smoke looks for
        return {"ok": None, "error": f"RAISED {type(e).__name__}: {e}"}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke-blender-run-"))
    cap = Capture()
    runner.logger.addHandler(cap)
    try:
        exe = tmp / "blender"
        exe.write_text(FAKE.format(python=sys.executable), encoding="utf-8")
        exe.chmod(0o755)
        model = tmp / "model.glb"
        model.write_bytes(b"glTF-stub")
        runner.pin_slots(str(tmp / "slots"), 2)
        runner._version_cache.clear()

        def config(key, default):
            return str(exe) if key == "image_generation.blender_executable" else default

        with patch.object(runner, "_config", config):
            st = runner.status()
            check(st["usable"] and st["executable"] == str(exe), f"fake is discovered ({st['error']!r})")
            res = safe_run(inputs={"model": model}, timeout_s=30)
            check(res["ok"] is True, f"baseline run ok ({res['error']!r})")

            # [1]
            def vanished(src, dst, *a, **kw):
                raise FileNotFoundError(2, "No such file or directory", str(src))
            fake_shutil = types.SimpleNamespace(copy2=vanished, rmtree=shutil.rmtree, move=shutil.move,
                                                which=shutil.which)
            with patch.object(runner, "shutil", fake_shutil):
                res = safe_run(inputs={"model": model}, timeout_s=30)
            check(res["ok"] is False and res["error"].startswith("input 'model' unreadable"),
                  f"[1] vanished input -> ok False ({res['error']!r})")

            # [2]
            gone = dict(st, executable=str(tmp / "gone" / "blender"))
            with patch.object(runner, "status", lambda: gone):
                res = safe_run(inputs={"model": model}, timeout_s=30)
            check(res["ok"] is False and res["error"].startswith("blender could not be started"),
                  f"[2] vanished binary -> ok False ({res['error']!r})")

            # [3]
            noexec = tmp / "noexec-blender"
            shutil.copy2(exe, noexec)
            noexec.chmod(0o644)
            with patch.object(runner, "status", lambda: dict(st, executable=str(noexec))):
                res = safe_run(inputs={"model": model}, timeout_s=30)
            check(res["ok"] is False and res["error"].startswith("blender could not be started"),
                  f"[3] binary without +x -> ok False ({res['error']!r})")

            # [4]
            with patch.dict(os.environ, {"FAKE_MODE": "garbage"}):
                res = safe_run(inputs={"model": model}, timeout_s=30)
            check(res["ok"] is False and res["error"] == "script wrote no result (exit 1)",
                  f"[4] undecodable output, no result -> ok False ({res['error']!r})")

            # [5]
            with patch.dict(os.environ, {"FAKE_MODE": "garbage_ok"}):
                res = safe_run(inputs={"model": model}, timeout_s=30)
            check(res["ok"] is True, f"[5] undecodable output, result ok -> ok True ({res['error']!r})")

            # [6]
            cap.records.clear()
            with patch.dict(os.environ, {"FAKE_MODE": "hang"}):
                res = safe_run(inputs={"model": model}, timeout_s=1)
            check(res["ok"] is False and res["error"] == "timeout after 1s",
                  f"[6] timeout -> ok False ({res['error']!r})")
            rec = next((r for r in cap.records if "timeout after 1s" in r), "")
            check("TAIL-MARKER-6" in rec, f"[6] timeout log carries the stderr tail ({rec!r})")
    finally:
        runner.logger.removeHandler(cap)
        runner.pin_slots(None, None)
        runner._version_cache.clear()
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'FAILED: ' + str(len(FAILS)) if FAILS else 'all passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
