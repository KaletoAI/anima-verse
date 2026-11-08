#!/usr/bin/env python3
"""Smoke: the local GLBBodyRetexture runner (app/core/body_retexture.py).

Usage:  ./.venv/bin/python scripts/smoke_body_retexture_runner.py

No server, no world DB, no real worker. The storage root is a throwaway temp
dir (set before any app import). The instance settings are put straight into
the in-memory config (``config._CONFIG["body_retexture"]``) — the runner reads
them live at call time, so no reload is involved.

THE FAKE WORKERS

Each fake is a directory ``<tmp>/<name>/`` shaped like the real repo:
``.venv/bin/python`` is a symlink to THIS interpreter and ``body_core/`` is a
package whose ``__main__`` does the fake's job. ``python -m body_core`` finds
that package only because the runner starts it with ``cwd=<worker_dir>`` — so
every fake that works at all also proves the cwd.

  echo     writes {"argv": sys.argv[1:], "cwd": os.getcwd()} into the --proof
           path, touches --out, exits 0.
  refuse   writes "loading views" + "front view does not match the
           registration" to stderr, exits 3.
  noproof  touches --out, writes no proof, exits 0.
  sleep    starts a CHILD python that sleeps 60 s, records both pids in
           <tmp>/sleep_pids.json, then sleeps 60 s itself.

WHAT IS CHECKED, and where every expected value comes from

 1. worker_dir "" (the schema default) -> RetextureUnavailable whose message
    contains "not configured" (spec review focus 2: the visible error text).
 2. worker_dir = a dir without .venv/bin/python -> RetextureUnavailable whose
    message contains "not installed".
 3. echo, views passed in the order right, front, left (back absent). The
    argv is BASE_VIEWS order ("front","back","left","right") with back
    skipped, every path absolute, so by hand:
        --glb <tmp>/in.glb
        --view front=<tmp>/d.png,<tmp>/r.png
        --view left=<tmp>/dl.png,<tmp>/rl.png
        --view right=<tmp>/dr.png,<tmp>/rr.png
        --out <tmp>/out.glb --proof <tmp>/proof.json --atlas <tmp>/atlas.png
    and the returned dict IS the proof the fake wrote (argv + cwd), with cwd
    = the (resolved) echo worker dir.
 4. worker_dir given as "~/echo" with HOME=<tmp> -> the same call works
    (the ``~`` is expanded).
 5. A stale proof.json left from an earlier run with the noproof fake ->
    RetextureFailed mentioning "proof" (the runner removes the old proof
    before the run, so the stale one cannot pass as this run's result).
 6. refuse -> RetextureFailed whose message contains "does not match".
 7. views without "front" -> ValueError before anything runs; an unknown
    view name ("top") -> ValueError.
 8. sleep with timeout_seconds = 1 -> RetextureFailed mentioning "timed out"
    within 15 s wall time, and afterwards NEITHER recorded pid is a live
    process (absent, or a zombie awaiting its reaper): the whole process
    group was killed, not only the worker.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="smoke_body_retex_"))

from app.core import paths  # noqa: E402

paths.init(str(_TMP / "storage"))

from app.core import config  # noqa: E402

FAILS = []


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILS.append(msg)


FAKES = {
    "echo": """
import json, os, sys
a = sys.argv[1:]
proof = a[a.index("--proof") + 1]
out = a[a.index("--out") + 1]
open(out, "wb").write(b"glb")
json.dump({"argv": a, "cwd": os.getcwd()}, open(proof, "w"))
""",
    "refuse": """
import sys
sys.stderr.write("loading views\\nfront view does not match the registration\\n")
sys.exit(3)
""",
    "noproof": """
import sys
a = sys.argv[1:]
open(a[a.index("--out") + 1], "wb").write(b"glb")
""",
    "sleep": """
import json, os, subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
json.dump({"worker": os.getpid(), "child": child.pid}, open(PIDFILE, "w"))
time.sleep(60)
""",
}


def make_fake(name: str) -> Path:
    d = _TMP / name
    (d / ".venv" / "bin").mkdir(parents=True)
    (d / ".venv" / "bin" / "python").symlink_to(Path(sys.executable).resolve())
    (d / "body_core").mkdir()
    (d / "body_core" / "__init__.py").write_text("")
    body = FAKES[name].replace("PIDFILE", repr(str(_TMP / "sleep_pids.json")))
    (d / "body_core" / "__main__.py").write_text(body)
    return d


def set_cfg(worker_dir: str, timeout: int = 1800):
    config._CONFIG["body_retexture"] = {"worker_dir": worker_dir, "timeout_seconds": timeout}


def alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return False
    return state != "Z"


def main():
    from app.core import body_retexture as br

    for name in FAKES:
        make_fake(name)
    t = str(_TMP)
    glb, out = _TMP / "in.glb", _TMP / "out.glb"
    proof, atlas = _TMP / "proof.json", _TMP / "atlas.png"
    glb.write_bytes(b"glb")
    views = {
        "right": (_TMP / "dr.png", _TMP / "rr.png"),
        "front": (_TMP / "d.png", _TMP / "r.png"),
        "left": (_TMP / "dl.png", _TMP / "rl.png"),
    }

    def run(v=views):
        return br.retexture(glb, v, out, proof=proof, atlas=atlas)

    print("[1] not configured")
    set_cfg("")
    try:
        run()
        check(False, "empty worker_dir raises RetextureUnavailable")
    except br.RetextureUnavailable as exc:
        check("not configured" in str(exc), f"message names 'not configured' ({exc})")

    print("[2] not installed")
    (_TMP / "empty").mkdir()
    set_cfg(str(_TMP / "empty"))
    try:
        run()
        check(False, "dir without .venv raises RetextureUnavailable")
    except br.RetextureUnavailable as exc:
        check("not installed" in str(exc), f"message names 'not installed' ({exc})")

    print("[3] echo: argv in BASE_VIEWS order, proof returned")
    set_cfg(str(_TMP / "echo"))
    result = run()
    expected = [
        "--glb", f"{t}/in.glb",
        "--view", f"front={t}/d.png,{t}/r.png",
        "--view", f"left={t}/dl.png,{t}/rl.png",
        "--view", f"right={t}/dr.png,{t}/rr.png",
        "--out", f"{t}/out.glb", "--proof", f"{t}/proof.json", "--atlas", f"{t}/atlas.png",
    ]
    check(result.get("argv") == expected, f"argv == hand-derived list (got {result.get('argv')})")
    check(Path(result.get("cwd", "")).resolve() == (_TMP / "echo").resolve(),
          f"cwd = worker dir (got {result.get('cwd')})")
    check(result == json.loads(proof.read_text()), "result dict is the proof file")

    print("[4] ~ in worker_dir is expanded")
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = t
    try:
        set_cfg("~/echo")
        result = run()
        check(result.get("argv") == expected, "~/echo runs the echo worker")
    finally:
        if old_home is not None:
            os.environ["HOME"] = old_home

    print("[5] exit 0 without a proof -> RetextureFailed (stale proof removed)")
    check(proof.exists(), "stale proof.json from [4] is present before the run")
    set_cfg(str(_TMP / "noproof"))
    try:
        run()
        check(False, "missing proof raises RetextureFailed")
    except br.RetextureFailed as exc:
        check("proof" in str(exc), f"message mentions the proof ({exc})")

    print("[6] refusal -> RetextureFailed with the stderr reason")
    set_cfg(str(_TMP / "refuse"))
    try:
        run()
        check(False, "exit 3 raises RetextureFailed")
    except br.RetextureFailed as exc:
        check("does not match" in str(exc), f"message carries stderr ({exc})")

    print("[7] view validation")
    set_cfg(str(_TMP / "echo"))
    for bad, label in (({"left": views["left"]}, "no front"),
                       ({**views, "top": views["left"]}, "unknown view 'top'")):
        try:
            run(bad)
            check(False, f"{label} raises ValueError")
        except ValueError:
            check(True, f"{label} raises ValueError")

    print("[8] timeout kills the whole process group")
    set_cfg(str(_TMP / "sleep"), timeout=1)
    t0 = time.monotonic()
    try:
        run()
        check(False, "sleeping worker raises RetextureFailed")
    except br.RetextureFailed as exc:
        check("timed out" in str(exc), f"message mentions the timeout ({exc})")
    check(time.monotonic() - t0 < 15, f"returned within 15 s ({time.monotonic() - t0:.1f} s)")
    pids = json.loads((_TMP / "sleep_pids.json").read_text())
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and any(alive(p) for p in pids.values()):
        time.sleep(0.05)
    for role, pid in pids.items():
        check(not alive(pid), f"{role} process {pid} is gone")


if __name__ == "__main__":
    try:
        main()
    except ImportError as exc:
        FAILS.append(f"import: {exc}")
        print(f"  FAIL import: {exc}")
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s)")
        sys.exit(1)
    print("all checks passed")
