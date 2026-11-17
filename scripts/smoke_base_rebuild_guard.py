#!/usr/bin/env python3
"""The base mesh repair ("Repair again") and the extension tip rebuild never run beside each other or beside a
Build's model step, and a Build waits for them (review unit 08 #2); a Build whose plan raises records a failure
(review unit 08, LOW "an error in plan() leaves a Build with no failure state").

Usage:
    ./.venv/bin/python scripts/smoke_base_rebuild_guard.py

Runs against a THROWAWAY storage + instance directory (``paths.init`` before any world-DB import) — no real world,
no Blender, no hub, no server. ``model3d.find_model3d`` answers a path, ``model3d.rebuild_extension_rig`` is a
stand-in that takes 0.5 s and records how many rebuilds run at once and what ``figure_build.base_step_in_flight``
says while it runs; the task queue's display row is off (``get_task_queue`` raises — "tracking is display only").
``model3d.generation_slot`` polls every 1 s, so a waiting run starts at most ~1 s after the slot is free.

The old-code proofs run the modules of commit OLD = 3f2ce338 (before the fix) loaded from git, with the same
stand-ins.

EXPECTED, BY HAND
[1] start_repair(A, base1) and start_tip_rebuild(A, base1) right after each other: both run (2 rebuilds), never at
    once (at most 1 in flight) — both hold the character's 3D generation slot.
    OLD: their ``_apply`` called the rebuild without the slot -> 2 at once.
[2] A repair alone (character A2): while its rebuild runs, base_step_in_flight(A2) == "Base mesh repair" (a Build
    does not start beside it: ``start`` answers base_busy / deferred). (In [1] the answer may name the tip rebuild
    instead — it is checked first and waits for the slot meanwhile — so [2] runs the repair on its own.) OLD figure_build.base_step_in_flight asked no repair registry ->
    "" while the same repair runs.
[3] A Build's model step holds the slot (``generation_slot(B)`` in this thread): start_repair(B, base1) -> True,
    but its rebuild has not started 0.6 s later; released -> it runs (1 rebuild within 3 s).
[4] ``_run_planned(C, …)`` with ``plan`` raising KeyError("step_due") returns normally and records
    ``_last[C]["failed"]["build"]["error"]`` = PLAN_FAILED with the error "'step_due'" (str of a KeyError):
    "The Build could not be planned — nothing was built: 'step_due'"; skipped [], reason "outfit_change".
    OLD: ``_run_planned`` let the KeyError out and recorded nothing.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OLD = "3f2ce338"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def old_module(rel: str, name: str) -> types.ModuleType:
    source = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:{rel}"], check=True, capture_output=True,
                            text=True).stdout
    module = types.ModuleType(name)
    exec(compile(source, f"{OLD}:{rel}", "exec"), module.__dict__)
    return module


def wait_until(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="base-rebuild-guard-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({}))
        from app.core import config, db
        config.load(paths.get_config_path(), instance_path=root / "instance" / "config.json")
        db.init_schema()

        from app.core import base_mesh_repair, extension_tip, figure, figure_build, model3d, task_queue

        def no_queue():
            raise RuntimeError("no task queue in this smoke")
        task_queue.get_task_queue = no_queue
        model3d.find_model3d = lambda name, signature=None, *a, **k: root / f"{signature}.glb"
        state = {"now": 0, "max": 0, "runs": [], "busy": []}
        lock = threading.Lock()
        busy_of = {"fn": figure_build.base_step_in_flight}

        def rebuild(character_name, signature=None, *, tier="full", force=False, repair=False):
            with lock:
                state["now"] += 1
                state["max"] = max(state["max"], state["now"])
                state["runs"].append((character_name, "repair" if repair else "tip"))
            if repair:
                state["busy"].append(busy_of["fn"](character_name))
            time.sleep(0.5)
            with lock:
                state["now"] -= 1
            return {"ok": True}
        model3d.rebuild_extension_rig = rebuild

        def idle(name, *modules):
            return all(not m.run_state(name)["running"] if hasattr(m, "run_state") else not m.rebuild_running(name)
                       for m in modules)

        print("[1] repair and tip rebuild never at once")
        check("repair started", base_mesh_repair.start_repair("A", "base1"), True)
        check("tip rebuild started", extension_tip.start_tip_rebuild("A", "base1"), True)
        check("both done", wait_until(lambda: idle("A", base_mesh_repair, extension_tip)), True)
        check("2 rebuilds", sorted(kind for _, kind in state["runs"]), ["repair", "tip"])
        check("at most 1 at once", state["max"], 1)
        print("[2] a Build sees the repair")
        state.update(now=0, max=0, runs=[], busy=[])
        check("repair A2 started", base_mesh_repair.start_repair("A2", "base1"), True)
        check("repair A2 done", wait_until(lambda: idle("A2", base_mesh_repair)), True)
        check("base_step_in_flight during the repair", state["busy"], ["Base mesh repair"])

        print("[3] the repair waits for a Build's model step")
        state.update(now=0, max=0, runs=[], busy=[])
        with model3d.generation_slot("B"):
            check("repair B started", base_mesh_repair.start_repair("B", "base1"), True)
            time.sleep(0.6)
            check("not run while the slot is held", state["runs"], [])
        check("runs once released", wait_until(lambda: len(state["runs"]) == 1, timeout=3.0), True)
        check("repair B done", wait_until(lambda: idle("B", base_mesh_repair)), True)

        print("[4] a plan that raises is the Build's failure")
        real_plan, real_delivered = figure_build.plan, figure._delivered

        def broken_plan(*a, **k):
            raise KeyError("step_due")
        figure_build.plan = broken_plan
        figure._delivered = lambda *a, **k: (None, None)
        try:
            figure_build._run_planned("C", "outfit_change", {}, automatic=False)
            check("returns normally", True, True)
        except Exception as e:  # noqa: BLE001 — reported as the failure
            check("returns normally", f"{type(e).__name__}: {e}", True)
        finally:
            figure_build.plan = real_plan
        last = figure_build._last.get("C") or {}
        check("failure recorded", ((last.get("failed") or {}).get("build") or {}).get("error"),
              "The Build could not be planned — nothing was built: 'step_due'")
        check("skipped / reason", (last.get("skipped"), last.get("reason")), ([], "outfit_change"))

        print(f"[old] code of {OLD}")
        try:
            old_repair = old_module("app/core/base_mesh_repair.py", "base_mesh_repair_old")
            old_tip = old_module("app/core/extension_tip.py", "extension_tip_old")
            old_fb = old_module("app/core/figure_build.py", "figure_build_old")
        except (subprocess.CalledProcessError, OSError) as e:
            check(f"old modules (git show {OLD})", str(e), "loaded")
            old_repair = old_tip = old_fb = None
        if old_fb is not None:
            state.update(now=0, max=0, runs=[], busy=[])
            busy_of["fn"] = old_fb.base_step_in_flight
            check("old repair started", old_repair.start_repair("D", "base1"), True)
            check("old tip rebuild started", old_tip.start_tip_rebuild("D", "base1"), True)
            check("old both done", wait_until(lambda: idle("D", old_repair, old_tip)), True)
            check("old: 2 rebuilds at once (the finding)", state["max"], 2)
            state.update(busy=[])
            busy_of["fn"] = old_fb.base_step_in_flight
            check("current repair started", base_mesh_repair.start_repair("E", "base1"), True)
            check("current repair done", wait_until(lambda: idle("E", base_mesh_repair)), True)
            check("old base_step_in_flight blind to a running repair", state["busy"], [""])
            old_fb.plan = broken_plan
            try:
                old_fb._run_planned("F", "outfit_change", {}, automatic=False)
                check("old: plan error escapes", "returned", "KeyError")
            except KeyError:
                check("old: plan error escapes", "KeyError", "KeyError")
            check("old: nothing recorded", "F" in old_fb._last, False)
        figure._delivered = real_delivered

    print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
