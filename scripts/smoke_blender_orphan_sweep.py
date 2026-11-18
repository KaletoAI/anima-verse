#!/usr/bin/env python3
"""Smoke: Blender job folders left behind by a killed host process are swept, live ones never
(review finding on ``runner.run``'s ``tempfile.mkdtemp(prefix="av-blender-")``: nothing removed a job
folder whose process died mid-run; ``runner.sweep_orphan_job_dirs`` + the owner marker ``owner.json``).

Usage:
    ./.venv/bin/python scripts/smoke_blender_orphan_sweep.py

No Blender, no server, no world, no instance. Linux only (``/proc``). The temp folder of this process is
a scratch folder (``tempfile.tempdir``), so the sweep only ever sees the fixtures below. ME = this
process: pid ``os.getpid()``, start = field 22 of ``/proc/self/stat``, boot = ``/proc/sys/kernel/random/
boot_id``, pidns = ``readlink /proc/self/ns/pid``. A marker is ``{"pid", "start", "boot", "pidns"}``.

Fixtures in the scratch temp folder T, expected outcome derived by hand from the rule "a marked folder
goes only when its owner is provably gone; an unmarked one only past UNMARKED_MAX_AGE_S (7 days)":
 [1] av-blender-dead     marker of a child that was started, read, killed and REAPED → its /proc entry
                         is gone (FileNotFoundError) → REMOVED.
 [2] av-blender-live     marker = ME → the start matches, state not Z → KEPT (age is never asked).
 [2b] av-blender-other   marker of ANOTHER process that still runs (a sleeping child, as another host
                         process of the machine would be) → KEPT.
 [3] av-blender-recycled marker = my pid, start = mine − 1 → the pid belongs to another process → REMOVED.
 [4] av-blender-zombie   marker of a child that exited but is NOT reaped yet (state Z) → REMOVED.
 [5] av-blender-reboot   marker = ME with another boot id → every process of that boot is gone → REMOVED.
 [6] av-blender-ns       marker = ME with another pid namespace → owner cannot be checked → KEPT.
 [7] other-dead          a dead-owner marker but a foreign prefix → UNTOUCHED.
 [8] av-blender-link     a SYMLINK (to a folder OUTSIDE T holding a dead-owner marker + a file) → the
                         link and its target both stay.
 [9] av-blender-young    no marker, mtime now → KEPT.
[10] av-blender-old      no marker, the folder and its entries 8 days old → REMOVED.
[11] av-blender-oldprog  no marker, folder 8 days old but ``progress.json`` in it rewritten now (a run of
                         older code still reporting) → newest mtime = now → KEPT.
[12] av-blender-badmark  a marker that is not JSON, folder young → counts as unmarked young → KEPT.
[13] inside [1] a symlink ``escape`` → a file OUTSIDE T: the file survives the removal of [1].
[14] av-blender-file     a regular FILE with the prefix → UNTOUCHED.
The sweep returns exactly {[1], [3], [4], [5], [10]}.

Then ``runner.run("meshopt", …)`` with a fake Blender (a Python script; ``runner.status`` stubbed to it,
the slot folder pinned into T2 — a fresh scratch temp folder):
[15] The fake reads ``owner.json`` beside its ``args.json`` BEFORE doing anything and returns it as its
     data → marker = ME (pid, start, boot, pidns); i.e. the marker is written before Blender starts.
[16] After ``run`` the job folder is gone from T2 (the normal path's rmtree is unchanged).
[17] ``sweep_orphan_job_dirs`` replaced by a function that raises → the next run is still ok True (the sweep
     runs once per process on a daemon thread; a failure is logged, never raised). The flag stays: a
     second run does not start a second sweep (the raising function is called exactly once).

Fails on the old code for the right reason: it had no sweep and no marker — [1] [3] [4] [5] [10] stay
in T, and [15]'s fake finds no ``owner.json`` (data ``{"marker": null}``).
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


FAKE = """#!{python}
import json, os, sys
if sys.argv[1:2] == ["--version"]:
    print("Blender 5.2.0")
    sys.exit(0)
args_file = sys.argv[-1]
marker = os.path.join(os.path.dirname(args_file), "owner.json")
data = json.load(open(marker)) if os.path.isfile(marker) else None
args = json.load(open(args_file))
open(args["result"], "w").write(json.dumps({{"ok": True, "data": {{"marker": data}}, "outputs": {{}}}}))
"""


def proc_start(pid):
    raw = open(f"/proc/{pid}/stat").read()
    return int(raw[raw.rindex(")") + 2:].split()[19])


def me():
    return {"pid": os.getpid(), "start": proc_start(os.getpid()),
            "boot": open("/proc/sys/kernel/random/boot_id").read().strip(),
            "pidns": os.readlink("/proc/self/ns/pid")}


def job(root, name, marker=None, raw=None):
    d = root / name
    d.mkdir()
    (d / "in").mkdir()
    if marker is not None:
        (d / "owner.json").write_text(json.dumps(marker), encoding="utf-8")
    if raw is not None:
        (d / "owner.json").write_text(raw, encoding="utf-8")
    return d


def age(path, seconds):
    t = time.time() - seconds
    for p in [*path.iterdir(), path]:
        os.utime(p, (t, t), follow_symlinks=False)


def main():
    if not sys.platform.startswith("linux"):
        print("skip: Linux only (/proc)")
        return 0
    scratch = Path(tempfile.mkdtemp(prefix="smoke-blender-sweep-"))
    T = scratch / "tmp"
    T.mkdir()
    outside = scratch / "outside"
    outside.mkdir()
    tempfile.tempdir = str(T)
    from app.blender import runner
    try:
        mine = me()
        # [1] a dead, reaped owner
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        dead = {**mine, "pid": child.pid, "start": proc_start(child.pid)}
        child.kill()
        child.wait()
        d_dead = job(T, "av-blender-dead", dead)
        (outside / "keep.txt").write_text("x")
        os.symlink(outside / "keep.txt", d_dead / "escape")  # [13]
        # [4] a zombie owner (exited, not reaped)
        zomb = subprocess.Popen([sys.executable, "-c", "pass"])
        zmark = {**mine, "pid": zomb.pid, "start": proc_start(zomb.pid)}
        for _ in range(100):
            if open(f"/proc/{zomb.pid}/stat").read().rsplit(")", 1)[1].split()[0] == "Z":
                break
            time.sleep(0.05)
        d_zomb = job(T, "av-blender-zombie", zmark)
        d_live = job(T, "av-blender-live", mine)                                   # [2]
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        d_other = job(T, "av-blender-other", {**mine, "pid": other.pid, "start": proc_start(other.pid)})  # [2b]
        d_recy = job(T, "av-blender-recycled", {**mine, "start": mine["start"] - 1})  # [3]
        d_boot = job(T, "av-blender-reboot", {**mine, "boot": "00000000-0000-0000-0000-000000000000"})  # [5]
        d_ns = job(T, "av-blender-ns", {**mine, "pidns": "pid:[1]"})              # [6]
        d_foreign = job(T, "other-dead", dead)                                     # [7]
        target = outside / "linked"
        target.mkdir()
        (target / "owner.json").write_text(json.dumps(dead))
        (target / "data.bin").write_text("x")
        os.symlink(target, T / "av-blender-link")                                  # [8]
        d_young = job(T, "av-blender-young")                                       # [9]
        d_old = job(T, "av-blender-old")                                           # [10]
        age(d_old, 8 * 24 * 3600)
        d_prog = job(T, "av-blender-oldprog")                                      # [11]
        (d_prog / "progress.json").write_text("{}")
        age(d_prog, 8 * 24 * 3600)
        os.utime(d_prog / "progress.json")
        d_bad = job(T, "av-blender-badmark", raw="{not json")                      # [12]
        f_file = T / "av-blender-file"
        f_file.write_text("x")                                                     # [14]

        removed = set(runner.sweep_orphan_job_dirs())
        other.kill()
        other.wait()
        want = {str(Path(os.path.realpath(p))) for p in (d_dead, d_recy, d_zomb, d_boot, d_old)}
        check(removed == want, f"sweep removed exactly dead/recycled/zombie/reboot/old "
                               f"(got {sorted(Path(p).name for p in removed)})")
        for d, tag in ((d_dead, "[1] dead owner"), (d_recy, "[3] recycled pid"), (d_zomb, "[4] zombie owner"),
                       (d_boot, "[5] other boot"), (d_old, "[10] unmarked old")):
            check(not d.exists(), f"{tag}: removed")
        for d, tag in ((d_live, "[2] live owner (me)"), (d_other, "[2b] live owner (another process)"),
                       (d_ns, "[6] other pid namespace"),
                       (d_foreign, "[7] foreign prefix"), (d_young, "[9] unmarked young"),
                       (d_prog, "[11] unmarked, progress rewritten now"), (d_bad, "[12] malformed marker, young")):
            check(d.is_dir(), f"{tag}: kept")
        check((T / "av-blender-link").is_symlink() and (target / "data.bin").is_file(),
              "[8] symlinked prefix entry: link and target untouched")
        check((outside / "keep.txt").is_file(), "[13] symlink inside a removed folder not followed")
        check(f_file.is_file(), "[14] regular file with the prefix untouched")
        zomb.wait()

        # [15]..[17] the real run() path
        T2 = scratch / "tmp2"
        T2.mkdir()
        tempfile.tempdir = str(T2)
        exe = scratch / "blender"
        exe.write_text(FAKE.format(python=sys.executable), encoding="utf-8")
        exe.chmod(0o755)
        runner.pin_slots(str(scratch / "slots"), 2)
        runner.status = lambda: {"enabled": True, "executable": str(exe), "error": ""}
        calls = []

        def boom():
            calls.append(1)
            raise RuntimeError("sweep exploded")
        runner.sweep_orphan_job_dirs = boom
        model = scratch / "model.glb"
        model.write_bytes(b"glTF-stub")
        res = runner.run("meshopt", inputs={"model": model}, timeout_s=60)
        for t in threading.enumerate():
            if t.name == "blender-job-sweep":
                t.join(5)
        got = (res.get("data") or {}).get("marker")
        check(res["ok"] is True, f"[17] run ok although the sweep raised ({res['error']!r})")
        check(got == mine, f"[15] marker written before Blender started = this process ({got} vs {mine})")
        left = [p.name for p in T2.iterdir() if p.name.startswith("av-blender-")]
        check(left == [], f"[16] job folder removed after the run (left {left})")
        res2 = runner.run("meshopt", inputs={"model": model}, timeout_s=60)
        check(res2["ok"] is True and len(calls) == 1, f"[17] one sweep per process (calls {len(calls)})")
    finally:
        import shutil
        shutil.rmtree(scratch, ignore_errors=True)
    print(f"\n{'FAILED: ' + str(len(FAILS)) if FAILS else 'all passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
