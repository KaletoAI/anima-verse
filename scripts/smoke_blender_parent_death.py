#!/usr/bin/env python3
"""Smoke: a Blender child dies with the server process that started it (review 02#8,
``runner._spawn`` → ``_die_with_parent``: an exec wrapper sets PR_SET_PDEATHSIG = SIGKILL on Linux and
replaces itself with Blender — no ``preexec_fn``, nothing runs between fork and exec in the server).

Usage:
    ./.venv/bin/python scripts/smoke_blender_parent_death.py

No Blender, no server, no world, no instance. A "server" is a CHILD PROCESS of this script
(``--server <json>``) that calls the REAL ``runner.run("meshopt", …)`` from a worker thread (as the server's
threadpool does) with ``runner._config`` stubbed to configure a fake Blender: a shell script that answers
``--version`` with "Blender 5.2.0" and, as a run, writes ``<pid> <ppid>`` to a file and then either ``exec``s
``sleep 60`` (same pid) or, with ``FAKE_RESULT`` set, writes the ok result and exits. The slot folder is pinned
into a temp folder. Linux only (the death signal is a Linux ``prctl``).

Expected, derived by hand:
[1] SIGKILL the "server" while its Blender sleeps → the kernel delivers SIGKILL to the child when the thread
    that forked it dies → the Blender pid is gone or a zombie within 3.0 s (it would otherwise sleep 60 s).
    The wrapper EXECs, so Blender is the server's direct child (its ppid = the server pid, no wrapper process
    in between) and still runs in its own session (``start_new_session`` kept): sid = its own pid.
[2] Control — the same with ``runner._spawn`` replaced by the body it had before this fix
    (``subprocess.run(cmd, …, start_new_session=True)``): the Blender pid is still running 1.5 s after the
    kill. This is the orphan the finding describes; the smoke kills it afterwards.
[3] A living parent is unaffected: a run whose fake writes the result → ok True, and its ppid is the
    server's pid (pid kept through the exec).
[4] The timeout kill still hits Blender: ``timeout_s`` = 1 on a fake that sleeps 60 s → ok False, error
    "timeout after 1s", and the pid the fake wrote is dead right after ``run`` returned (subprocess.run kills
    the pid it started — the same pid after the exec — and reaps it).
[5] The race guard: the wrapper started with a parent pid that is NOT its parent (pid 1) exits with code 1
    before the exec — ``/bin/echo MARK`` never runs (stdout empty).
[6] Off Linux (``sys.platform`` = "darwin") ``_die_with_parent(cmd)`` is ``cmd`` unchanged.
[7] Start latency added by the wrapper: median of 15 ``_spawn(["/bin/true"])`` with it minus the median of 15
    without it is printed; bound < 0.5 s (one extra ``python -I -S`` start + ctypes import, tens of ms).
"""
import json
import os
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def server(spec):
    sys.path.insert(0, str(ROOT))
    from app.blender import runner
    runner.pin_slots(spec["slots"], 2)
    runner._config = lambda path, default: (spec["exe"] if path == "image_generation.blender_executable"
                                            else default)
    if spec.get("old"):
        def old_spawn(cmd, timeout, env):
            return subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                                  timeout=timeout, env=env, start_new_session=True)
        runner._spawn = old_spawn
    os.environ["FAKE_PIDFILE"] = spec["pidfile"]
    if spec.get("result"):
        os.environ["FAKE_RESULT"] = "1"
    out = {}
    t = threading.Thread(target=lambda: out.update(runner.run(
        "meshopt", inputs={"model": Path(spec["model"])}, timeout_s=int(spec.get("timeout", 120)))))
    t.start()
    t.join()
    print(json.dumps({"ok": out.get("ok"), "error": out.get("error"), "server_pid": os.getpid()}))


def state(pid):
    """'gone', 'Z' (zombie) or the /proc state letter of a live process."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return "gone"
    return stat.rsplit(")", 1)[1].split()[0]


def dead(pid):
    return state(pid) in ("gone", "Z", "X")


def wait_for(cond, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def start_server(tmp, name, **extra):
    pidfile = tmp / f"{name}.pid"
    spec = {"slots": str(tmp / f"slots-{name}"), "exe": str(tmp / "blender"), "pidfile": str(pidfile),
            "model": str(tmp / "model.glb"), **extra}
    srv = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--server", json.dumps(spec)],
                           cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return srv, pidfile


def read_pids(pidfile):
    pid, ppid = (int(x) for x in pidfile.read_text().split())
    return pid, ppid


def killed_scenario(tmp, name, old):
    srv, pidfile = start_server(tmp, name, old=old)
    if not wait_for(lambda: pidfile.is_file() and len(pidfile.read_text().split()) == 2, 20):
        srv.kill()
        print(srv.communicate()[1][-2000:])
        return None, None, None, None
    pid, ppid = read_pids(pidfile)
    sid = os.getsid(pid)
    os.kill(srv.pid, signal.SIGKILL)
    srv.wait(timeout=10)
    return pid, ppid, sid, srv.pid


def finished_scenario(tmp, name, **extra):
    srv, pidfile = start_server(tmp, name, **extra)
    out, err = srv.communicate(timeout=60)
    lines = out.strip().splitlines()
    res = json.loads(lines[-1]) if lines else {"error": err[-2000:]}
    pids = read_pids(pidfile) if pidfile.is_file() else (None, None)
    return res, pids


def main():
    if not sys.platform.startswith("linux"):
        print("skipped: PR_SET_PDEATHSIG is Linux-only")
        return 0
    sys.path.insert(0, str(ROOT))
    from app.blender import runner
    tmp = Path(tempfile.mkdtemp(prefix="smoke-blender-pdeath-"))
    orphans = []
    try:
        exe = tmp / "blender"
        exe.write_text('#!/bin/sh\n'
                       'if [ "$1" = "--version" ]; then echo "Blender 5.2.0"; exit 0; fi\n'
                       'echo "$$ $PPID" > "$FAKE_PIDFILE"\n'
                       'if [ -n "$FAKE_RESULT" ]; then\n'
                       '  for last; do :; done\n'
                       '  res=$(sed -n \'s/.*"result": "\\([^"]*\\)".*/\\1/p\' "$last")\n'
                       '  echo \'{"ok": true}\' > "$res"; exit 0\n'
                       'fi\n'
                       'exec sleep 60\n', encoding="utf-8")
        exe.chmod(0o755)
        (tmp / "model.glb").write_bytes(b"glTF-stub")

        # [1]
        pid, ppid, sid, srv_pid = killed_scenario(tmp, "new", old=False)
        check(pid is not None, "[1] fake Blender started")
        if pid:
            orphans.append(pid)
            check(ppid == srv_pid, f"[1] Blender is the server's direct child (ppid {ppid}, server {srv_pid})")
            check(sid == pid, f"[1] child runs in its own session (sid {sid}, pid {pid})")
            check(wait_for(lambda: dead(pid), 3.0), f"[1] Blender died with the server (state {state(pid)})")

        # [2]
        pid, _ppid, _sid, _srv = killed_scenario(tmp, "old", old=True)
        check(pid is not None, "[2] control: fake Blender started")
        if pid:
            orphans.append(pid)
            time.sleep(1.5)
            check(not dead(pid), f"[2] control: without the fix the orphan keeps running (state {state(pid)})")

        # [3]
        res, (pid, ppid) = finished_scenario(tmp, "alive", result=True)
        check(res.get("ok") is True, f"[3] living parent: run ok ({res.get('error')!r})")
        check(ppid is not None and ppid == res.get("server_pid"),
              f"[3] Blender's ppid is the server (ppid {ppid}, server {res.get('server_pid')})")

        # [4]
        res, (pid, _ppid) = finished_scenario(tmp, "timeout", timeout=1)
        if pid:
            orphans.append(pid)
        check(res.get("ok") is False and res.get("error") == "timeout after 1s",
              f"[4] timeout -> ok False ({res.get('error')!r})")
        check(pid is not None and dead(pid), f"[4] the timeout killed the Blender pid (state {state(pid)})")

        # [5]
        proc = subprocess.run([sys.executable, "-I", "-S", "-c", runner._PDEATH_EXEC, "1", "/bin/echo", "MARK"],
                              capture_output=True, text=True, timeout=30)
        check(proc.returncode == 1 and proc.stdout == "",
              f"[5] wrong parent -> exit 1 before the exec (rc {proc.returncode}, stdout {proc.stdout!r})")

        # [6]
        saved = runner.sys.platform
        runner.sys.platform = "darwin"
        try:
            check(runner._die_with_parent(["blender", "-b"]) == ["blender", "-b"], "[6] off Linux: cmd unchanged")
        finally:
            runner.sys.platform = saved

        # [7]
        env = dict(os.environ)

        def timed(fn):
            t0 = time.perf_counter()
            fn()
            return time.perf_counter() - t0
        with_w = [timed(lambda: runner._spawn(["/bin/true"], 30, env)) for _ in range(15)]
        without = [timed(lambda: subprocess.run(["/bin/true"], capture_output=True, text=True, errors="replace",
                                                timeout=30, env=env, start_new_session=True))
                   for _ in range(15)]
        extra = statistics.median(with_w) - statistics.median(without)
        print(f"     start latency: with wrapper {statistics.median(with_w) * 1000:.1f} ms, "
              f"without {statistics.median(without) * 1000:.1f} ms, added {extra * 1000:.1f} ms (median of 15)")
        check(extra < 0.5, f"[7] added start latency < 0.5 s ({extra * 1000:.1f} ms)")
    finally:
        for pid in orphans:
            try:
                if not dead(pid):
                    os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'FAILED: ' + str(len(FAILS)) if FAILS else 'all passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--server":
        server(json.loads(sys.argv[2]))
    else:
        sys.exit(main())
