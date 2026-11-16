#!/usr/bin/env python3
"""Ruling A136 — the garment piece dialog reloads when a Build or re-fit of its character starts or ends, and its
Details 3D preview never shows an out-of-date fit as if the piece were worn.

Usage:
    ./.venv/bin/python scripts/smoke_garment_dialog_a136.py

Runs against a THROWAWAY storage + instance directory — no world DB, no hub, no server. The Build steps are
stubbed (``figure_build._run`` / ``_run_refit``); ``sync_topics.notify`` is recorded.

Expected, by hand from the ruling and the code:

[1] ``figure_build._worker("demo")`` with one queued follow-up (reason "outfit_change", automatic False):
    the run is called once, and ``notify`` is called exactly twice — before and after it — each with topic
    "generation" and recipient ``sync_topics.Admins()`` (Build state is admin-only, never the avatar). A run
    that RAISES still ends with the second notify (2 calls again). A queued Re-fit (``_refit_items``) also
    gives 2 calls. ``_active`` no longer holds "demo" afterwards.
[2] ``previewChoice(fitUrl, stale, showOld, bodyUrl)`` (``garmentStyle.ts``, node via esbuild):
    (null, *, *, *) → "none"; ("f", false, false, "b") → "fit" (a current fit is shown as it is);
    ("f", true, false, "b") → "body" (stale: the body without it by default); ("f", true, true, "b") → "old"
    (only on request); ("f", true, false, null) → "none" (no body to show — never the stale fit).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="a136_")
os.environ["STORAGE_DIR"] = TMP
os.environ["INSTANCE_DIR"] = os.path.join(TMP, "instance")
os.makedirs(os.environ["INSTANCE_DIR"], exist_ok=True)

from app.core import paths  # noqa: E402
paths.init(TMP)

FAILS = []


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        FAILS.append(what)


def section1():
    from app.core import figure_build as fb, sync_topics
    calls, runs = [], []
    sync_topics_notify = sync_topics.notify
    sync_topics.notify = lambda topics, *, to: calls.append((topics, to))
    fb._run = lambda c, r, automatic=False: runs.append(("run", c, r))
    fb._run_refit = lambda c, item: runs.append(("refit", c, item))
    try:
        def go(reason="outfit_change", refit=""):
            calls.clear(); runs.clear()
            with fb._lock:
                fb._queues["demo"] = deque([(reason, False)])
                if refit:
                    fb._refit_items["demo"] = refit
                fb._active.add("demo")
            fb._worker("demo")
        go()
        check(runs == [("run", "demo", "outfit_change")], "the Build ran once")
        check(calls == [("generation", sync_topics.Admins())] * 2, f"two admin 'generation' pushes: {calls}")
        check("demo" not in fb._active, "worker ended")

        def boom(c, r, automatic=False):
            raise RuntimeError("x")
        fb._run = boom
        go()
        check(len(calls) == 2, "a failed run still pushes at its end")
        go(reason=fb.REFIT_REASON, refit="item_x")
        check(runs == [("refit", "demo", "item_x")] and len(calls) == 2, "a re-fit pushes twice")
    finally:
        sync_topics.notify = sync_topics_notify


JS = """
import { previewChoice } from %s
console.log(JSON.stringify([
  previewChoice(null, true, true, 'b'), previewChoice('f', false, false, 'b'), previewChoice('f', true, false, 'b'),
  previewChoice('f', true, true, 'b'), previewChoice('f', true, false, null)]))
"""


def section2():
    esbuild = next((ROOT / p for p in ("node_modules/.bin/esbuild", "frontend/node_modules/.bin/esbuild")
                    if (ROOT / p).exists()), None)
    if esbuild is None or shutil.which("node") is None:
        check(False, "esbuild and node available")
        return
    ts = ROOT / "frontend/src/tabs/characters/garmentStyle.ts"
    with tempfile.TemporaryDirectory() as tmp:
        entry, bundle = Path(tmp) / "e.mjs", Path(tmp) / "b.mjs"
        entry.write_text(JS % json.dumps(str(ts)))
        b = subprocess.run([str(esbuild), str(entry), "--bundle", "--platform=node", "--format=esm",
                            "--log-level=error", f"--outfile={bundle}"], cwd=ROOT, capture_output=True, text=True)
        if b.returncode:
            print(b.stderr)
            check(False, "bundle")
            return
        out = subprocess.run(["node", str(bundle)], capture_output=True, text=True).stdout.strip().splitlines()[-1]
    check(json.loads(out) == ["none", "fit", "body", "old", "none"], f"previewChoice table: {out}")


try:
    section1()
    section2()
finally:
    shutil.rmtree(TMP, ignore_errors=True)
print("FAILED: %d" % len(FAILS) if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
