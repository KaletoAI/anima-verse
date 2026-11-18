"""Smoke: the Blender log (``logs/blender.log``, ``app/blender/runner.py`` ``_write_log``) — one whole block per
run, never interleaved between processes, and the rename rotation of ``start.sh`` loses and tears none.

Usage:
    ./.venv/bin/python scripts/smoke_blender_log.py

No Blender, no server, no world. Writers are child Pythons that call ``runner._write_log`` with ``LOG_FILE``
pointed into a temp folder; the rotation is the ``rotate_log_by_rename`` function cut out of ``start.sh`` and run
by bash, so the check runs the shipped code.

Expected, derived by hand:
[1] ``LOG_FILE`` is ``<repo>/logs/blender.log`` from any working directory (a child started in a temp folder
    prints the same path) — the studio and the server write one file.
[2] A block: the header ``=== <stamp> script=<s> outcome=<o> seconds=<x.xx> pid=<p> job=<job folder> exit=<c|-> ===``,
    then the body, ending in a newline even when the output did not. ``seconds`` 1.5 prints "1.50", exit None
    prints "-". An ok run's body is cut to its last LOG_OK_BYTES (2048) behind "[… cut]\\n"; a failed run keeps
    up to LOG_FAILED_BYTES (65536) — a 60000-byte body whole.
[3] An unwritable log (its directory is a regular file) warns once for two failing writes and raises nothing.
[4] 8 writers × 150 blocks at the same time (bodies of 100..60000 bytes, each body one repeated letter of its
    writer): exactly 1200 blocks, each header names (writer, index) once, each body is only its own letter and
    exactly as long as written — no block torn, none interleaved.
[5] The same 8 × 150 (4 ms apart) while ``rotate_log_by_rename`` runs 80 times 10 ms apart (each into its own archive folder, so the
    second-resolution file name never collides): the live log plus every archived file hold exactly the 1200
    blocks, each once and whole; at least two archives received blocks (the rotation really ran under load).
    The same run with ``rotate_log`` (copy, then truncate) put in its place lost 15, 33 and 28 of the 1200
    blocks in three runs (2026-11-18): a block appended between the copy and the truncation is gone.
"""
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.blender import runner  # noqa: E402

FAILS = []

HEAD = re.compile(r"^=== (?P<stamp>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\S*) script=(?P<script>\S+) "
                  r"outcome=(?P<outcome>\S+) seconds=(?P<seconds>\d+\.\d\d) pid=(?P<pid>\d+) "
                  r"job=(?P<job>\S+) exit=(?P<exit>-?\d+|-) ===$")

WRITERS, BLOCKS = 8, 150

WRITER = r"""
import sys
import time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from app.blender import runner
runner.LOG_FILE = Path(sys.argv[2])
w = int(sys.argv[3])
letter = chr(ord("a") + w)
for i in range(int(sys.argv[4])):
    size = 100 + (i * 7919 + w * 104729) % 59901          # 100 .. 60000 bytes
    line = letter * 79 + "\n"
    body = (line * (size // 80 + 1))[:size - 1] + "\n"
    runner._write_log(f"w{w}-i{i}", "crashed", 0.1, Path("av-blender-smoke"), 1, body)
    time.sleep(float(sys.argv[5]))
"""


def check(cond, label):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def size_of(w, i):
    return 100 + (i * 7919 + w * 104729) % 59901


def parse(text):
    """``[(header match or None, body)]`` — a body line that looks like no header stays in its block."""
    out = []
    for line in text.splitlines(keepends=True):
        m = HEAD.match(line.rstrip("\n")) if line.startswith("=== ") else None
        if m:
            out.append([m, ""])
        elif out:
            out[-1][1] += line
        else:
            out.append([None, line])
    return out


def judge(blocks, label):
    """[4]/[5]: every (writer, index) once, every body whole and only its writer's letter."""
    seen, bad = {}, []
    for m, body in blocks:
        if m is None:
            bad.append("text before the first header")
            continue
        w, i = (int(x) for x in re.match(r"w(\d+)-i(\d+)$", m.group("script")).groups())
        seen[(w, i)] = seen.get((w, i), 0) + 1
        letter = chr(ord("a") + w)
        if len(body.encode()) != size_of(w, i) or set(body) - {letter, "\n"}:
            bad.append(f"w{w}-i{i}: {len(body.encode())} bytes, letters {sorted(set(body) - {chr(10)})[:4]}")
    want = {(w, i) for w in range(WRITERS) for i in range(BLOCKS)}
    check(len(blocks) == WRITERS * BLOCKS and set(seen) == want and all(v == 1 for v in seen.values()),
          f"{label} {len(blocks)} blocks, {len(set(seen))} distinct, {sum(v > 1 for v in seen.values())} twice")
    check(not bad, f"{label} no torn or interleaved block ({bad[:3]})")


def writers(log, pause=0.0):
    return [subprocess.Popen([sys.executable, "-c", WRITER, str(ROOT), str(log), str(w), str(BLOCKS), str(pause)])
            for w in range(WRITERS)]


def main():
    tmp = Path(tempfile.mkdtemp(prefix="smoke-blender-log-"))

    # [1]
    out = subprocess.run([sys.executable, "-c", "from app.blender import runner; print(runner.LOG_FILE)"],
                         cwd=tmp, env={**os.environ, "PYTHONPATH": str(ROOT)}, capture_output=True, text=True)
    check(out.stdout.strip() == str(ROOT / "logs" / "blender.log") == str(runner.LOG_FILE),
          f"[1] LOG_FILE from a foreign cwd is the repo's logs/blender.log ({out.stdout.strip() or out.stderr})")

    # [2]
    saved = runner.LOG_FILE
    try:
        runner.LOG_FILE = tmp / "fmt" / "blender.log"
        runner._write_log("meshopt", "ok", 1.5, Path("/x/av-blender-abc"), None, "no newline")
        runner._write_log("meshopt", "ok", 0.0, Path("/x/av-blender-abc"), 0, "y" * 5000)
        runner._write_log("lod", "crashed", 2.0, Path("/x/av-blender-abc"), -11, "z" * 59999 + "\n")
        blocks = parse(runner.LOG_FILE.read_text(encoding="utf-8"))
        heads = [m for m, _b in blocks]
        check(len(blocks) == 3 and all(heads), f"[2] three blocks with headers ({len(blocks)})")
        if len(blocks) == 3 and all(heads):
            m = heads[0]
            check((m.group("script"), m.group("outcome"), m.group("seconds"), m.group("pid"), m.group("job"),
                   m.group("exit")) == ("meshopt", "ok", "1.50", str(os.getpid()), "av-blender-abc", "-"),
                  f"[2] header fields ({m.group(0)!r})")
            check(blocks[0][1] == "no newline\n", "[2] a body without a final newline gets one")
            check(blocks[1][1] == "[… cut]\n" + "y" * 2048 + "\n",
                  f"[2] an ok body is cut to the last 2048 bytes ({len(blocks[1][1])} chars)")
            check(heads[2].group("exit") == "-11" and blocks[2][1] == "z" * 59999 + "\n",
                  "[2] a failed run's 60000-byte body stays whole")

        # [3]
        (tmp / "afile").write_text("x")
        runner.LOG_FILE = tmp / "afile" / "blender.log"
        warned = []
        saved_warning = runner.logger.warning
        runner.logger.warning = lambda *a, **k: warned.append(a)
        try:
            runner._log_warned = False
            runner._write_log("meshopt", "ok", 0.0, Path("av-blender-x"), 0, "x")
            runner._write_log("meshopt", "ok", 0.0, Path("av-blender-x"), 0, "x")
        finally:
            runner.logger.warning = saved_warning
        check(len(warned) == 1, f"[3] an unwritable log warns once, raises nothing ({len(warned)} warnings)")
    finally:
        runner.LOG_FILE = saved

    # [4]
    log = tmp / "conc" / "blender.log"
    for p in writers(log):
        p.wait()
    judge(parse(log.read_text(encoding="utf-8")), "[4]")

    # [5]
    text = (ROOT / "start.sh").read_text(encoding="utf-8")
    fn = re.search(r"^rotate_log_by_rename\(\) \{\n.*?^\}\n", text, re.S | re.M)
    check(fn is not None, "[5] rotate_log_by_rename found in start.sh")
    if fn is None:
        return
    log = tmp / "rot" / "blender.log"
    log.parent.mkdir()
    procs = writers(log, pause=0.004)       # ~0.6 s of writing per writer
    archives = []
    for k in range(80):
        time.sleep(0.01)
        arch = tmp / "rot" / f"archive_{k}"
        arch.mkdir()
        archives.append(arch)
        subprocess.run(["bash", "-c", fn.group(0) + 'rotate_log_by_rename "$1"', "_", str(log)],
                       env={**os.environ, "ARCHIVE_DIR": str(arch)}, check=True, capture_output=True)
    for p in procs:
        p.wait()
    files = [f for a in archives for f in sorted(a.iterdir())] + ([log] if log.exists() else [])
    check(sum(1 for a in archives if any(a.iterdir())) >= 2,
          f"[5] the rotation ran under load ({sum(1 for a in archives if any(a.iterdir()))} archives filled)")
    blocks = []
    for f in files:
        blocks += parse(f.read_text(encoding="utf-8"))
    judge(blocks, "[5]")

    print("all passed" if not FAILS else f"{len(FAILS)} FAILED")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
