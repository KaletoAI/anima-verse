#!/usr/bin/env python3
"""Ruling A140 — the garment piece dialog always offers the next step (button + cost) or a visible reason.

Usage:
    ./.venv/bin/python scripts/smoke_garment_dialog_a140.py

Case behind it: a piece with mesh shape "Shell from the body" (chain worn -> ghost -> fit, ``garments.shell_order``)
whose views were all accepted; the fit button was disabled because it waited for ``mesh.status == 'accepted'``,
which a shell piece never gets, and the Figure-tab dialog has no Run all. Throwaway storage, no world DB, no server.

Expected, by hand from the ruling:

[1] ``model_overview.garment_steps`` of a shell piece (``fit_settings.mesh_shape.resolved == "shell"``) with
    worn + ghost accepted, cut-outs/mesh/fit empty: worn done, ghost done, cutout SKIPPED and mesh SKIPPED with
    detail "From the body — made in the fit step", fit DUE. The same garment with resolved "as_generated":
    cutout/mesh/fit all "missing" (unchanged behaviour).
[2] ``fitRowGate`` (garmentStyle.ts, node via esbuild), args (shell, meshAccepted, viewsReady, fitMade,
    refitBlock, buildRunning):
    a (T,F,T,F,"",F) -> enabled, "Fit now (CPU, 0 hub jobs)", primary   <- the user's case
    b (T,F,F,F,"",F) -> disabled, reason "Needs both piece-only views accepted first"
    c (F,F,T,F,"",F) -> disabled, reason "Needs an accepted mesh first"
    d (F,T,T,T,"",F) -> enabled, "Re-fit (CPU, 0 hub jobs)", not primary
    e (T,F,T,F,"",T) -> disabled, reason "Waits for the running Build — it fits this piece too"
    f (T,F,T,F,"X",F) -> disabled, reason "X"
    Every disabled result has a non-empty reason.
[3] ``nextStepLine``: null -> null; {steps:[],hub_jobs:0} -> nothing true; {steps:["fit"],hub_jobs:0} ->
    nothing false, steps ["fit"], hubJobs 0.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="a140_")
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
    from app.core import model_overview as mo
    acc = {"front": {"accepted": True}, "back": {"accepted": True}}
    empty = {"front": {"accepted": False}, "back": {"accepted": False}}

    def garment(shape):
        return {"kind": "clothing", "steps": {"worn": acc, "ghost": acc, "cutout": empty,
                                              "mesh": {"status": "missing"}, "fit": {"status": "missing"}},
                "fit_settings": {"mesh_shape": {"resolved": shape}}}
    rows = {r["id"]: r for r in mo.garment_steps(garment("shell"))}
    got = {k: rows[k]["status"] for k in rows}
    check(got == {"worn": "done", "ghost": "done", "cutout": "skipped", "mesh": "skipped", "fit": "due"},
          f"shell rows {got}")
    check(rows["mesh"]["detail"] == "From the body — made in the fit step", "mesh detail names the fit step")
    check(rows["cutout"]["detail"] == "Not needed: the shell is made from the piece-only views", "cutout detail")
    rows = {r["id"]: r["status"] for r in mo.garment_steps(garment("as_generated"))}
    check([rows[k] for k in ("cutout", "mesh", "fit")] == ["missing"] * 3, f"generated rows unchanged {rows}")


JS = r"""
import { fitRowGate, nextStepLine } from %s
const g = (shell, meshAccepted, viewsReady, fitMade, refitBlock, buildRunning) =>
  fitRowGate({ shell, meshAccepted, viewsReady, fitMade, refitBlock, buildRunning })
console.log(JSON.stringify({
  a: g(true, false, true, false, '', false), b: g(true, false, false, false, '', false),
  c: g(false, false, true, false, '', false), d: g(false, true, true, true, '', false),
  e: g(true, false, true, false, '', true), f: g(true, false, true, false, 'X', false),
  n0: nextStepLine(null), n1: nextStepLine({ steps: [], hub_jobs: 0 }), n2: nextStepLine({ steps: ['fit'], hub_jobs: 0 }),
}))
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
        r = json.loads(subprocess.run(["node", str(bundle)], capture_output=True, text=True).stdout.strip()
                       .splitlines()[-1])
    check(r["a"] == {"disabled": False, "label": "Fit now (CPU, 0 hub jobs)", "reason": "", "primary": True},
          f"a shell piece with its views: Fit now {r['a']}")
    check(r["b"]["disabled"] and r["b"]["reason"] == "Needs both piece-only views accepted first", "b")
    check(r["c"]["disabled"] and r["c"]["reason"] == "Needs an accepted mesh first", "c")
    check(r["d"] == {"disabled": False, "label": "Re-fit (CPU, 0 hub jobs)", "reason": "", "primary": False}, "d")
    check(r["e"]["disabled"] and r["e"]["reason"] == "Waits for the running Build — it fits this piece too", "e")
    check(r["f"]["disabled"] and r["f"]["reason"] == "X", "f")
    check(all(r[k]["reason"] for k in "abcdef" if r[k]["disabled"]), "every disabled gate has a reason")
    check(r["n0"] is None and r["n1"]["nothing"] is True
          and r["n2"] == {"nothing": False, "steps": ["fit"], "hubJobs": 0}, "nextStepLine")


try:
    section1()
    section2()
finally:
    shutil.rmtree(TMP, ignore_errors=True)
print("FAILED: %d" % len(FAILS) if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
