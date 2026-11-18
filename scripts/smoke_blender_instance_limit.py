#!/usr/bin/env python3
"""Smoke: the animation studio and the Blender CLI scripts run under the SERVER's Blender limit, binary and
switches (review 02#4, ``runner.use_instance_config``; callers ``animstudio.bootstrap`` and
``scripts/{backfill_clip_turn,clip_import_cmu,cmu_convert_all,make_reference_rig,make_rig_rest,
repair_clip_loop,repair_clip_roll,repair_clip_spikes}.py``).

Usage:
    ./.venv/bin/python scripts/smoke_blender_instance_limit.py

No Blender, no server, no real world, no real instance. A temp instance holds
``{"server": {"blender_max_concurrent": 1}, "image_generation": {"blender_executable": <fake>}}``; this
script writes ``INSTANCE_DIR`` = that folder, which its children inherit (as ``start.sh --instance`` hands
it to a tool). The fake "blender" is a Python script: ``--version`` → "Blender 5.2.0"; as a run it notes
``start``/``end`` (time.time) in a shared log, sleeps ``FAKE_HOLD`` s in between and writes the ``{"ok":
true}`` result. Every child calls the REAL ``runner.run("meshopt", …)`` — no stubs in the runner.

Children: STUDIO = ``animstudio.bootstrap()`` (throwaway world + instance), CLI = what every listed script
does in ``main()``: ``runner.use_instance_config(<repo>/instance)`` (no world at all). OLD = the studio's
bootstrap body before this fix (``paths.init(<throwaway world>)`` only), inline.

Expected, derived by hand:
[1] STUDIO and CLI started together, hold 1.0 s each, limit 1 from the instance → the two runs never
    overlap (max overlap 1) and first start to last end >= 2 × 1.0 = 2.0 s; both end ok. Without the binding
    each process would take the schema default 2 in its own private slot folder → both would overlap.
[2] Both resolve the instance's values: ``runner.status()["executable"]`` = the fake (from
    ``image_generation.blender_executable``, ``configured`` True), ``max_concurrent()`` = 1, and
    ``slot_dir()`` = <instance>/.blender-slots — the folder the server computes from the same instance.
[3] No world DB is opened: the studio's throwaway world holds neither world.db nor task_queue.db after the
    run; the CLI child has no storage at all (``paths.get_storage_dir()`` raises StorageNotInitialised).
[4] Fails on the old code: OLD resolves ``configured`` False, ``max_concurrent()`` 2 (schema default) and the
    per-user temp folder ``<tmp>/anima-blender-slots-<uid>`` — the server's limit and binary never apply.
[5] A missing instance folder is not created: ``use_instance_config(<tmp>/absent)`` with INSTANCE_DIR unset
    returns None and the folder still does not exist.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


FAKE = """#!{python}
import json, os, sys, time
if sys.argv[1:2] == ["--version"]:
    print("Blender 5.2.0")
    sys.exit(0)
def note(ev):
    with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as f:
        f.write(json.dumps({{"tag": os.environ["FAKE_TAG"], "ev": ev, "t": time.time()}}) + "\\n")
args = json.loads(open(sys.argv[-1], encoding="utf-8").read())
note("start")
time.sleep(float(os.environ.get("FAKE_HOLD", "1")))
note("end")
open(args["result"], "w").write(json.dumps({{"ok": True, "data": {{}}, "outputs": {{}}}}))
"""


# --- child side ---------------------------------------------------------------------

def child(spec):
    mode = spec["mode"]
    sys.path.insert(0, str(ROOT))
    if mode == "studio":
        sys.path.insert(0, str(ROOT / "animation-studio"))
        import animstudio
        animstudio.bootstrap()
    elif mode == "cli":
        from app.blender import runner
        runner.use_instance_config(ROOT / "instance")
    elif mode == "old":
        import atexit
        import shutil
        from app.core import paths
        world = tempfile.mkdtemp(prefix="smoke-old-studio-world-")
        atexit.register(shutil.rmtree, world, True)
        paths.init(world)
    elif mode == "absent":
        os.environ.pop("INSTANCE_DIR", None)
        from app.blender import runner
        got = runner.use_instance_config(Path(spec["absent"]))
        print(json.dumps({"got": got and str(got), "exists": Path(spec["absent"]).exists()}))
        return
    from app.blender import runner
    from app.core import paths
    st = runner.status()
    report = {"executable": st["executable"], "configured": st["configured"],
              "limit": runner.max_concurrent(), "slot_dir": str(runner.slot_dir())}
    if spec.get("run"):
        res = runner.run("meshopt", inputs={"model": Path(spec["model"])}, timeout_s=60)
        report.update(ok=res["ok"], error=res["error"])
    try:
        world = paths.get_storage_dir()
        report["world_dbs"] = sorted(p.name for p in world.glob("*.db"))
        report["storage"] = True
    except paths.StorageNotInitialised:
        report["storage"] = False
    print(json.dumps(report))


# --- parent side --------------------------------------------------------------------

def spawn(spec, env):
    return subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child", json.dumps(spec)],
                            cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)


def result(proc):
    out, err = proc.communicate(timeout=120)
    lines = out.strip().splitlines()
    try:
        return json.loads(lines[-1])
    except (IndexError, ValueError):
        print(err[-2000:])
        return {}


def max_overlap(rows):
    events = sorted(((r["t"], 1 if r["ev"] == "start" else -1) for r in rows), key=lambda x: (x[0], x[1]))
    cur = best = 0
    for _t, d in events:
        cur += d
        best = max(best, cur)
    return best


def main():
    tmp = Path(tempfile.mkdtemp(prefix="smoke-blender-instance-"))
    inst = tmp / "instance"
    inst.mkdir()
    exe = tmp / "blender"
    exe.write_text(FAKE.format(python=sys.executable), encoding="utf-8")
    exe.chmod(0o755)
    (inst / "config.json").write_text(json.dumps({
        "server": {"blender_max_concurrent": 1},
        "image_generation": {"blender_executable": str(exe)}}), encoding="utf-8")
    (tmp / "model.glb").write_bytes(b"glTF-stub")
    log = tmp / "runs.log"
    os.environ["INSTANCE_DIR"] = str(tmp / "instance")
    os.environ.pop("STORAGE_DIR", None)
    base = dict(os.environ, FAKE_LOG=str(log), FAKE_HOLD="1.0")
    try:
        # [1] [2] [3]
        procs = {m: spawn({"mode": m, "run": True, "model": str(tmp / "model.glb")}, dict(base, FAKE_TAG=m))
                 for m in ("studio", "cli")}
        reports = {m: result(p) for m, p in procs.items()}
        rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()] \
            if log.is_file() else []
        starts = [r["t"] for r in rows if r["ev"] == "start"]
        ends = [r["t"] for r in rows if r["ev"] == "end"]
        check(len(starts) == 2 and len(ends) == 2, f"[1] two runs logged (starts {len(starts)}, ends {len(ends)})")
        check(max_overlap(rows) == 1, f"[1] limit 1 across studio + CLI: max overlap 1 (got {max_overlap(rows)})")
        span = (max(ends) - min(starts)) if starts and ends else 0.0
        check(span >= 2.0, f"[1] serialised: span >= 2.0 s (got {span:.2f})")
        for m, rep in reports.items():
            check(rep.get("ok") is True, f"[1] {m}: run ok ({rep.get('error')!r})")
            check(rep.get("executable") == str(exe) and rep.get("configured") is True,
                  f"[2] {m}: binary from the instance ({rep.get('executable')!r})")
            check(rep.get("limit") == 1, f"[2] {m}: limit 1 from the instance (got {rep.get('limit')})")
            check(rep.get("slot_dir") == str(inst / ".blender-slots"),
                  f"[2] {m}: slots under the instance (got {rep.get('slot_dir')})")
        check(reports["studio"].get("storage") is True and reports["studio"].get("world_dbs") == [],
              f"[3] studio: throwaway world has no DB file (got {reports['studio'].get('world_dbs')})")
        check(reports["cli"].get("storage") is False, "[3] CLI: no storage initialised at all")

        # [4]
        old = result(spawn({"mode": "old"}, dict(base, FAKE_TAG="old")))
        uid = os.getuid()
        check(old.get("configured") is False and old.get("limit") == 2
              and old.get("slot_dir") == str(Path(tempfile.gettempdir()) / f"anima-blender-slots-{uid}"),
              f"[4] old bootstrap: defaults + private slots ({old})")

        # [5]
        absent = tmp / "absent"
        got = result(spawn({"mode": "absent", "absent": str(absent)}, dict(base, FAKE_TAG="absent")))
        check(got == {"got": None, "exists": False}, f"[5] missing instance stays unbound, not created ({got})")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'FAILED: ' + str(len(FAILS)) if FAILS else 'all passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--child":
        child(json.loads(sys.argv[2]))
    else:
        sys.exit(main())
