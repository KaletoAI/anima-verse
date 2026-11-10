#!/usr/bin/env python3
"""Cancel a QUEUED explicit run (user decision 2026-11-10): the garment queue
(``garments.cancel_garment``, ``POST /characters/{c}/garments/{item}/cancel``;
hair and own-mesh pieces share it) and the Outfit body tab's queue
(``outfit_bodies.cancel``, ``POST /characters/{c}/outfit-bodies/{body}/cancel``).

Usage:
    ./.venv/bin/python scripts/smoke_run_queue_cancel.py

Runs against a THROWAWAY storage + instance directory (``paths.init`` before
any world module) — no world, no hub, no GPU, no server. The two routers are
mounted on a bare FastAPI app with a TestClient; the session lookup is stubbed
(header ``x-role``: admin / user / none). Stubs: ``garments.check_run`` and
``outfit_bodies.check_run`` (everything valid), ``garments.run_garment`` and
``outfit_bodies._run`` (recorders; the first run of each queue blocks on an
event). Real: both FIFOs and their worker threads, the in-memory garment run
status (``garment_store.start`` / ``end`` / ``status``), the generation guard.

Expected values (derived by hand from the rules in ``cancel_garment`` /
``cancel``: a waiting entry goes, the one in flight never does):

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

OUTFIT BODIES (character Demo; body ids X, Y, Z = ob11111111, ob22222222, ob33333333)
[7] start(regenerate X) -> started; X is in flight (the recorder holds it);
    start(rerig Y), start(refit Z) -> positions 1 and 2.
[8] POST …/outfit-bodies/Y/cancel -> 200 {body_id Y, cancelled 1, queue
    {running {regenerate, X}, waiting [refit Z]}}; _run_state(Z) =
    ("queued", "refit", 1); _run_state(X) = ("running", "regenerate", None);
    Y's job done {ok False, cancelled True, error CANCELLED}; _run_state(Y) =
    ("", None, None).
[9] Cancel X -> 409 (detail ALREADY_RUNNING); cancel ob99999999 -> 404;
    user -> 403, anonymous -> 401.
[10] Released: the runs are X (regenerate) then Z (refit); no last result
    recorded for Y.
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
        from app.core import auth_dependency, garments, outfit_bodies
        from app.core import garment_store as gs
        from app.models.character import save_character_profile
        from app.routes import characters as characters_routes, outfit_bodies as outfit_bodies_routes

        users = {"admin": {"id": "a", "username": "admin", "role": "admin"},
                 "user": {"id": "u", "username": "player", "role": "user", "allowed_characters": ["Demo"]}}
        auth_dependency._get_session_user = lambda request: users.get(request.headers.get("x-role", ""))
        app = FastAPI()
        app.include_router(characters_routes.router)
        app.include_router(outfit_bodies_routes.router)
        client = TestClient(app)
        ADMIN, USER = {"x-role": "admin"}, {"x-role": "user"}
        check("character saved", save_character_profile("Demo", {"gender": "female"}, create_new=True), True)

        # --- garments ---------------------------------------------------------
        runs = []
        gate_a = threading.Event()

        def recorder(character_name, item_id, *, steps=None, view=None, force=False):
            runs.append((item_id, steps, force))
            if item_id == "A":
                gate_a.wait(30)
            return {"ok": True, "item": item_id}

        garments.check_run = lambda character_name, item_id, steps=None, view=None: None
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

        # --- outfit bodies ------------------------------------------------------
        X, Y, Z = "ob11111111", "ob22222222", "ob33333333"
        body_runs = []
        gate_x = threading.Event()

        def body_recorder(character_name, job):
            body_runs.append((job.kind, job.body_id))
            if job.body_id == X:
                gate_x.wait(30)
            return {"ok": True}

        outfit_bodies.check_run = lambda character_name, kind, body_id, item_id="", view="": None
        outfit_bodies._run = body_recorder

        print("[7] X runs, Y and Z wait")
        check("start X", outfit_bodies.start("Demo", "regenerate", X)["started"], True)
        check("X in flight", wait_for(lambda: bool(body_runs)), True)
        check("start Y", outfit_bodies.start("Demo", "rerig", Y)["position"], 1)
        check("start Z", outfit_bodies.start("Demo", "refit", Z)["position"], 2)
        with outfit_bodies._lock:
            job_y = next(j for j in outfit_bodies._queues["Demo"] if j.body_id == Y)

        print("[8] cancel Y: Z moves up, X untouched")
        r = client.post(f"/characters/Demo/outfit-bodies/{Y}/cancel", headers=ADMIN)
        check("cancel Y", (r.status_code, r.json()),
              (200, {"body_id": Y, "cancelled": 1, "queue": {
                  "running": {"kind": "regenerate", "body_id": X, "item_id": None},
                  "waiting": [{"kind": "refit", "body_id": Z, "item_id": None}]}}))
        check("Z state", outfit_bodies._run_state("Demo", Z), ("queued", "refit", 1))
        check("X state", outfit_bodies._run_state("Demo", X), ("running", "regenerate", None))
        check("Y state", outfit_bodies._run_state("Demo", Y), ("", None, None))
        check("Y waiter", (job_y.done.is_set(), job_y.result),
              (True, {"ok": False, "cancelled": True, "error": outfit_bodies.CANCELLED}))

        print("[9] 409 / 404 / auth")
        r = client.post(f"/characters/Demo/outfit-bodies/{X}/cancel", headers=ADMIN)
        check("cancel X", (r.status_code, r.json().get("detail")), (409, outfit_bodies.ALREADY_RUNNING))
        check("cancel unknown",
              client.post("/characters/Demo/outfit-bodies/ob99999999/cancel", headers=ADMIN).status_code, 404)
        check("user", client.post(f"/characters/Demo/outfit-bodies/{Z}/cancel", headers=USER).status_code, 403)
        check("anonymous", client.post(f"/characters/Demo/outfit-bodies/{Z}/cancel").status_code, 401)

        print("[10] released")
        gate_x.set()
        check("idle", wait_for(lambda: not outfit_bodies._active, 30), True)
        check("runs", body_runs, [("regenerate", X), ("refit", Z)])
        check("no result for Y", ("Demo", Y) in outfit_bodies._results, False)

    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
