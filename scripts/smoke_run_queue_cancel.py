#!/usr/bin/env python3
"""Cancel a QUEUED explicit run (user decision 2026-11-10): the garment queue
(``garments.cancel_garment``, ``POST /characters/{c}/garments/{item}/cancel``;
hair and own-mesh pieces share it). (The per-body run queue of the removed
outfit-body tab and its cancel — formerly [7]–[10] — went with that tab in plan
2026-11-12-unified-worn-pieces Task 11; the Build has no per-body queue.)

Usage:
    ./.venv/bin/python scripts/smoke_run_queue_cancel.py

Runs against a THROWAWAY storage + instance directory (``paths.init`` before
any world module) — no world, no hub, no GPU, no server. The characters router
is mounted on a bare FastAPI app with a TestClient; the session lookup is stubbed
(header ``x-role``: admin / user / none). Stubs: ``garments.check_run``
(everything valid), ``garments.run_garment`` (a recorder; the first run blocks
on an event). Real: the FIFO and its worker thread, the in-memory garment run
status (``garment_store.start`` / ``end`` / ``status``), the generation guard.

Expected values (derived by hand from the rules in ``cancel_garment``: a
waiting entry goes, the one in flight never does):

GARMENTS (character Demo; items A, B, C)
[1] start_garment(A) -> started (the recorder holds A). B through the trigger
    path (enqueue_garment, handle kept), then the explicit click on B
    (steps "fit", force) merges into that job; start_garment(C) -> position 2.
    queue_state(Demo) = {queue_running "A", queue ["B", "C"]}.
[2] POST …/garments/B/cancel (admin) -> 200 {item_id "B", cancelled 1,
    queue_running "A", queue ["C"]}. Afterwards queue_state(Demo, "C") ->
    queue_position 1 (it moved up); B's status running_step None (its
    "queued" mark ended, so no tile says "will be redone"); A's status still
    "queued" (start_garment marked it, the stub never reaches a step) and
    A still in flight (queue_running "A"); the trigger's job of B is done with
    {ok False, cancelled True, error CANCELLED, ran []}.
[3] POST …/garments/A/cancel -> 409 (A runs, nothing of A waits), detail
    ALREADY_RUNNING; the queue unchanged (["C"]).
[4] POST …/garments/Z/cancel (no run at all) -> 404; POST …/garments/B/cancel
    again -> 404 (already gone).
[5] Auth: user -> 403 on C's cancel, anonymous -> 401; C still queued.
[6] Released: the runs are exactly A then C (B never ran), idle afterwards.

"""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def wait_for(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="run-queue-cancel-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "inst")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "inst")
        paths.get_config_path().write_text(json.dumps({}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "inst/config.json")
        from app.core import db
        db.init_schema()

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.core import auth_dependency, garments
        from app.core import garment_store as gs
        from app.models.character import save_character_profile
        from app.routes import characters as characters_routes

        users = {"admin": {"id": "a", "username": "admin", "role": "admin"},
                 "user": {"id": "u", "username": "player", "role": "user", "allowed_characters": ["Demo"]}}
        auth_dependency._get_session_user = lambda request: users.get(request.headers.get("x-role", ""))
        app = FastAPI()
        app.include_router(characters_routes.router)
        client = TestClient(app)
        ADMIN, USER = {"x-role": "admin"}, {"x-role": "user"}
        check("character saved", save_character_profile("Demo", {"gender": "female"}, create_new=True), True)

        # --- garments ---------------------------------------------------------
        runs = []
        gate_a = threading.Event()

        def recorder(character_name, item_id, *, steps=None, view=None, force=False, state=None):
            runs.append((item_id, steps, force))
            if item_id == "A":
                gate_a.wait(30)
            return {"ok": True, "item": item_id}

        garments.check_run = lambda character_name, item_id, steps=None, view=None, state=None: None
        garments.run_garment = recorder

        print("[1] A runs, B and C wait")
        check("start A", garments.start_garment("Demo", "A")["started"], True)
        check("A in flight", wait_for(lambda: bool(runs)), True)
        trigger_b = garments.enqueue_garment("Demo", "B")
        check("explicit B merges", garments.start_garment("Demo", "B", steps="fit", force=True)["position"], 1)
        check("start C", garments.start_garment("Demo", "C")["position"], 2)
        check("queue", garments.queue_state("Demo"), {"queue_running": "A", "queue": ["B", "C"]})

        print("[2] cancel B: C moves up, A untouched")
        r = client.post("/characters/Demo/garments/B/cancel", headers=ADMIN)
        check("cancel B", (r.status_code, r.json()),
              (200, {"item_id": "B", "cancelled": 1, "queue_running": "A", "queue": ["C"]}))
        check("C position 1", garments.queue_state("Demo", "C")["queue_position"], 1)
        check("B mark gone", gs.status("Demo", "B")["running_step"], None)
        check("A status", gs.status("Demo", "A")["running_step"], "queued")
        check("A in flight", garments.queue_state("Demo")["queue_running"], "A")
        check("trigger waiter of B", (trigger_b.done.is_set(), trigger_b.result),
              (True, {"ok": False, "cancelled": True, "error": garments.CANCELLED, "ran": []}))

        print("[3] cancel A (running) -> 409")
        r = client.post("/characters/Demo/garments/A/cancel", headers=ADMIN)
        check("cancel A", (r.status_code, r.json().get("detail")), (409, garments.ALREADY_RUNNING))
        check("queue unchanged", garments.queue_state("Demo")["queue"], ["C"])

        print("[4] cancel unknown / gone -> 404")
        check("cancel Z", client.post("/characters/Demo/garments/Z/cancel", headers=ADMIN).status_code, 404)
        check("cancel B again", client.post("/characters/Demo/garments/B/cancel", headers=ADMIN).status_code, 404)

        print("[5] auth")
        check("user", client.post("/characters/Demo/garments/C/cancel", headers=USER).status_code, 403)
        check("anonymous", client.post("/characters/Demo/garments/C/cancel").status_code, 401)
        check("C still queued", garments.queue_state("Demo", "C")["queue_position"], 1)

        print("[6] released")
        gate_a.set()
        check("idle", garments.wait_idle(30), True)
        check("runs", runs, [("A", None, False), ("C", None, False)])
        check("queue empty", garments.queue_state("Demo"), {"queue_running": None, "queue": []})

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
