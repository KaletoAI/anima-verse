#!/usr/bin/env python3
"""Ruling A25 (T15-F1 of plan ``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md``): the Build's estimate
counts what its own-mesh chains spend (cut-out upscales included; a cached-failed chain's retry in a manual Build),
a Build's own chain queues no "piece_ready" follow-up, and ``model3d.face_settings_fingerprint`` is defined once.

Usage:
    ./.venv/bin/python scripts/smoke_figure_build_a25.py

Runs against a THROWAWAY storage + instance directory — no world, no hub, no server. The numbers of the estimate
itself are checked where their fixtures live (``smoke_garment_run_estimate`` E1/E6: 7 = worn 2 + ghost 2 +
cutout 2 + mesh 1; ``smoke_figure_f13``: the open state 5, its worn front kept 6; ``smoke_figure_a11`` [4] /
``smoke_figure_auto_build`` [7]: the failed chain's retry cost); ``smoke_garment_outfit`` [1] runs a real chain
inside the Build's pieces step and sees no follow-up. This smoke pins the pieces in isolation:

[1] ``garments.HUB_JOBS["clothing:edit_chain"]`` == {worn 2, ghost 2, cutout 2, mesh 1, fit 0} (the cut-out =
    one routed upscale per view, front + back, below ``garment_images.CUTOUT_MIN_SIDE`` 1024).
[2] ``base_body.after_mesh_item_ready(Demo, jacket)`` (on the pipeline, the jacket worn; ``figure_build.request``
    recorded): outside a Build's chain -> True, one request "piece_ready"; while ``figure_build._chain`` runs
    the jacket's chain (``garments.run_queued`` stubbed to call the hook from inside, as the garment FIFO does)
    -> the hook answers False and nothing is requested; after the chain ``runs_chain`` is False again (also
    when the chain raises).
[3] ``app/core/model3d.py`` defines ``face_settings_fingerprint`` exactly once (AST).
[4] Fails on the old code (explicit hash 21ca534b, the base of T15-F1): cutout 0 in ``HUB_JOBS`` and two
    definitions of ``face_settings_fingerprint``.
"""
import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASELINE = "21ca534b"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


def defs(source: str, name: str) -> int:
    return sum(1 for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef) and node.name == name)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="figure-build-a25-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import base_body, figure_build, garment_images, garments, model_refs

        print("[1] the clothing chain's first-attempt jobs")
        check("HUB_JOBS clothing", garments.HUB_JOBS["clothing:edit_chain"],
              {"worn": 2, "ghost": 2, "cutout": 2, "mesh": 1, "fit": 0})
        check("CUTOUT_MIN_SIDE", garment_images.CUTOUT_MIN_SIDE, 1024)

        print("[2] no piece_ready follow-up from the Build's own chain")
        requests, hooks = [], []
        base_body._profile_of = lambda *_a, **_kw: {"model_pipeline": "base_body"}
        base_body.is_base_pipeline = lambda *_a, **_kw: True
        model_refs.current_outfit_state = lambda _c: ({"outer": "jacket"}, [], "sig")
        figure_build.request = lambda c, reason: requests.append((c, reason)) or True
        check("outside a Build: requested", (base_body.after_mesh_item_ready("Demo", "jacket"), requests),
              (True, [("Demo", "piece_ready")]))
        requests.clear()

        def run_queued(c, ids, explicit=False):
            hooks.append((base_body.after_mesh_item_ready(c, ids[0]), figure_build.runs_chain(c, ids[0])))
            return {i: {"ok": True} for i in ids}

        garments.run_queued = run_queued
        check("the Build's chain", figure_build._chain("Demo", "jacket", False), "")
        check("inside: no request, runs_chain True", (hooks, requests), ([(False, True)], []))
        check("after: runs_chain False", figure_build.runs_chain("Demo", "jacket"), False)

        def failing(c, ids, explicit=False):
            raise RuntimeError("chain broke — smoke")

        garments.run_queued = failing
        try:
            figure_build._chain("Demo", "jacket", True)
        except RuntimeError:
            pass
        check("after a raising chain: runs_chain False", figure_build.runs_chain("Demo", "jacket"), False)

    print("[3] face_settings_fingerprint once")
    now = (ROOT / "app/core/model3d.py").read_text(encoding="utf-8")
    check("one definition", defs(now, "face_settings_fingerprint"), 1)

    print(f"[4] fails on the old code ({BASELINE})")
    old_m3d = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASELINE}:app/core/model3d.py"],
                             capture_output=True, text=True).stdout
    old_garments = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASELINE}:app/core/garments.py"],
                                  capture_output=True, text=True).stdout
    check(f"{BASELINE}: two definitions", defs(old_m3d, "face_settings_fingerprint"), 2)
    check(f"{BASELINE}: cutout 0", '"clothing:edit_chain": {"worn": 2, "ghost": 2, "cutout": 0' in old_garments, True)

    print(f"\n{len(FAILS)} failure(s)")
    for label in FAILS:
        print("  -", label)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
