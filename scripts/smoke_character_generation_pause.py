#!/usr/bin/env python3
"""Ruling A42: automatic generation can be paused per character; waiting jobs can be cancelled.

Usage:
    ./.venv/bin/python scripts/smoke_character_generation_pause.py

Runs against a THROWAWAY storage + instance directory — no world of the user, no hub, no server. Every producer is
a stub that records its call; a socket guard counts outbound connects (want 0). Two characters: ``Demo`` (paused)
and ``Demo Two`` (never paused). The expectations are derived by hand from the rules in
``app/core/generation_pause.py``:

[1] An automatic trigger while paused starts nothing and is held:
    a) ``figure_build.request(Demo, "outfit_change")`` (on the pipeline, "Build automatically" on) -> False,
       ``figure_build.start`` never called, the held triggers are exactly [build {reason outfit_change}];
       a second request "body_change" keeps ONE entry (key ``build``) with the newer reason.
    b) the outfit reference timer of kind ``tpose`` firing (``model_refs._fire_kind``) -> no render
       (``_fire_kinds`` not called), held trigger ``model_refs:tpose``.
    c) ``expression_regen.trigger_expression_generation`` -> False, no coalesce timer armed.
    d) an automatic garment run (``garments.enqueue_garment``, automatic) -> no worker, ``run_garment`` not
       called, ``held_items(Demo)`` == [coat].
    e) a queued task submitted with ``character_hold`` for Demo -> not dequeued; the queue view marks it
       ``held`` True.
    f) an Improvements step: ``_held_by_pause`` of a media type on ``character:Demo`` -> "Demo", on
       ``character:Demo Two`` -> "", of a CPU-only type (``needs_media`` False) -> ""; the key parse:
       ``clothing:Demo:item_1`` -> Demo, ``location:loc_1:a.png`` -> "", mesh_from_tpose ``Demo:ab12`` -> Demo.
[2] Held, then released in order on Resume:
    a) three held tasks t1, t2, t3 of one priority, submitted in that order within one second -> nothing
       dequeued while paused; after Resume ``_dequeue`` returns t1, t2, t3 (priority, age, then rowid).
    b) two held garment runs coat, scarf -> after Resume ``run_garment`` ran [coat, scarf].
    c) the held triggers fire again in the order first held: build, then model_refs:tpose; afterwards none is
       left.
[3] An explicit click while paused runs:
    a) ``garments.start_garment(Demo, hat)`` (a click) with coat held -> ``run_garment`` ran [hat] only, coat
       still held.
    b) ``figure_build.start(Demo, reason="manual")`` -> "started", ``_run`` called with automatic False, and the
       held ``build`` trigger is dropped (the manual Build covers it).
    c) a task of Demo submitted WITHOUT ``character_hold`` (a click's) is dequeued while paused.
[4] Cancel removes ONE waiting entry and changes nothing else:
    a) ``generation_pause.cancel(Demo, "garment:coat")`` -> held_items == [], the waiter got ``cancelled``,
       after Resume ``run_garment`` never ran coat.
    b) ``cancel(Demo, "task:<t>")`` -> the row is ``cancelled``, never dequeued after Resume.
    c) ``cancel(Demo, "trigger:build")`` -> after Resume the Build replay is never called.
    d) an unknown id -> LookupError.
[5] Another character is unaffected: Demo Two's ``character_hold`` task is dequeued while Demo is paused, its
    automatic garment run runs, and its ``figure_build.request`` reaches ``start``.
[6] A running job is not interrupted:
    a) Demo's automatic garment run ``boots`` blocks inside ``run_garment``; Demo is paused meanwhile; it
       finishes with ok True and the automatic ``gloves`` queued behind it stays held (never run).
    b) an automatic Build of two steps (fits, assemble) whose first step pauses the character while it runs:
       the first step returns normally, the second never runs, ``state()['paused']['step']`` == "assemble",
       ``failed`` == {} and the held trigger ``build`` names the run's reason.
[7] The push signal reaches admins only: after ``set_paused`` an admin connection holds the topic
    ``generation``, a player's connection holds nothing.
[8] Outbound connects: 0.
"""
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
CONNECTS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def _guard_sockets():
    real = socket.socket.connect

    def connect(self, address):
        if isinstance(address, tuple):
            CONNECTS.append(address)
            raise OSError("outbound connect blocked by the smoke")
        return real(self, address)
    socket.socket.connect = connect


def main() -> int:
    _guard_sockets()
    with tempfile.TemporaryDirectory(prefix="generation-pause-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import db
        db.init_schema()
        from app.core import (expression_regen, figure_build, garment_store, garments, generation_pause, model_refs,
                              sync_topics)
        from app.core.improvements import engine, registry
        from app.core.improvements.base import ImprovementType
        from app.core.improvements.types.mesh_from_tpose import MeshFromTpose
        from app.core.task_queue import get_task_queue

        A, B = "Demo", "Demo Two"
        tq = get_task_queue()
        tq._started = True   # no worker threads: the smoke dequeues by hand

        # --- stubs: the garment FIFO's producers and store marks ---
        ran = []
        block = {"boots": threading.Event()}
        entered = threading.Event()

        def run_garment(c, item_id, **_kw):
            if item_id in block:
                entered.set()
                block[item_id].wait(10)
            ran.append((c, item_id))
            return {"ok": True, "ran": ["fit"]}
        garments.run_garment = run_garment
        garments.check_run = lambda *_a, **_kw: None
        garments.cached_failure = lambda *_a, **_kw: None
        garment_store.status = lambda *_a, **_kw: {}
        garment_store.start = lambda *_a, **_kw: None
        garment_store.end = lambda *_a, **_kw: None

        # --- stubs: the Build's view of the characters ---
        starts = []
        real_start = figure_build.start
        figure_build._read_profile = lambda _c: {}
        figure_build.on_pipeline = lambda *_a, **_kw: True
        figure_build.auto_build_on = lambda *_a, **_kw: True
        figure_build.start = lambda c, **kw: starts.append((c, kw)) or {"status": "started"}

        def held_keys(c):
            return [(e["key"], e["payload"]) for e in tq.held_triggers(c)]

        print("[1] an automatic trigger while paused starts nothing")
        generation_pause.set_paused(A, True)
        check("1a request -> False", figure_build.request(A, "outfit_change"), False)
        check("1a start not called", starts, [])
        check("1a held", held_keys(A), [("build", {"reason": "outfit_change"})])
        figure_build.request(A, "body_change")
        check("1a one entry, newest reason", held_keys(A), [("build", {"reason": "body_change"})])

        fired = []
        real_fire_kinds = model_refs._fire_kinds
        model_refs._fire_kinds = lambda c, kinds, *a, **kw: fired.append((c, kinds))
        model_refs.get_auto_kinds = lambda _c: {"tpose": True, "pose": False}
        model_refs._pending_timers[(A, "tpose")] = SimpleNamespace(timer=threading.current_thread())
        model_refs._fire_kind(A, "tpose")
        check("1b no render", fired, [])
        check("1b held", [k for k, _p in held_keys(A)], ["build", "model_refs:tpose"])

        request = SimpleNamespace(character=A)
        check("1c expression -> False", expression_regen.trigger_expression_generation(request), False)
        check("1c no timer armed", A in expression_regen._pending, False)

        job_coat = garments.enqueue_garment(A, "coat")
        check("1d no worker", A in garments._active, False)
        check("1d run_garment not called", ran, [])
        check("1d held_items", garments.held_items(A), ["coat"])

        t_held = tq.submit("npc_assets", {}, agent_name=A, character_hold=True)
        check("1e not dequeued", tq._dequeue(), None)
        pending = {r["task_id"]: r for r in tq.get_status()["pending"]}
        check("1e marked held", pending[t_held]["held"], True)

        class Media(ImprovementType):
            id, needs_media = "smoke_media", True

        class Cpu(ImprovementType):
            id, needs_media = "smoke_cpu", False
        registry.register(Media())
        registry.register(Cpu())
        check("1f media on Demo", engine._held_by_pause({"type_id": "smoke_media", "candidate_key": f"character:{A}"}),
              A)
        check("1f media on Demo Two",
              engine._held_by_pause({"type_id": "smoke_media", "candidate_key": f"character:{B}"}), "")
        check("1f cpu type", engine._held_by_pause({"type_id": "smoke_cpu", "candidate_key": f"character:{A}"}), "")
        check("1f keys", (Media().subject_character(f"clothing:{A}:item_1"), Media().subject_character(
            "location:loc_1:a.png"), MeshFromTpose().subject_character(f"{A}:ab12")), (A, "", A))

        print("[3] an explicit click while paused runs")
        garments.start_garment(A, "hat")
        garments.wait_idle(10)
        check("3a only the click ran", ran, [(A, "hat")])
        check("3a coat still held", garments.held_items(A), ["coat"])
        runs = []
        figure_build.start = real_start
        figure_build.base_step_in_flight = lambda _c: ""
        figure_build.plan = lambda *_a, **_kw: [figure_build.Step("fits", "CPU refits", 0)]
        real_run = figure_build._run
        figure_build._run = lambda c, reason, *, automatic=False: runs.append((c, reason, automatic))
        check("3b manual Build", real_start(A, reason="manual"), {"status": "started"})
        deadline = time.monotonic() + 5
        while figure_build.running(A) and time.monotonic() < deadline:
            time.sleep(0.02)
        check("3b ran manual", runs, [(A, "manual", False)])
        check("3b held build dropped", [k for k, _p in held_keys(A)], ["model_refs:tpose"])
        tq.hold_trigger(A, "build", "Build (automatic) · outfit change", {"reason": "outfit_change"})
        t_click = tq.submit("outfit_combos", {}, agent_name=A)
        check("3c click task dequeued", (tq._dequeue() or {}).get("task_id"), t_click)
        tq._finish_task(t_click, "completed")

        print("[5] another character is unaffected")
        t_other = tq.submit("npc_assets", {}, agent_name=B, character_hold=True)
        check("5 other's task dequeued", (tq._dequeue() or {}).get("task_id"), t_other)
        tq._finish_task(t_other, "completed")
        ran.clear()
        garments.enqueue_garment(B, "cape")
        garments.wait_idle(10)
        check("5 other's garment ran", ran, [(B, "cape")])
        starts.clear()
        figure_build.start = lambda c, **kw: starts.append((c, kw)) or {"status": "started"}
        check("5 other's request", figure_build.request(B, "outfit_change"), True)
        check("5 start reached", [c for c, _kw in starts], [B])

        print("[4] Cancel removes one waiting entry, nothing else")
        waiting = [e["id"] for e in generation_pause.state(A)["waiting"]]
        check("4 waiting list", waiting, ["trigger:model_refs:tpose", "trigger:build", "garment:coat",
                                          f"task:{t_held}"])
        generation_pause.cancel(A, "garment:coat")
        check("4a coat gone", garments.held_items(A), [])
        check("4a waiter told", (job_coat.done.is_set(), job_coat.result.get("cancelled")), (True, True))
        generation_pause.cancel(A, f"task:{t_held}")
        check("4b task cancelled", tq.task_status(t_held), "cancelled")
        replays = []
        generation_pause._REPLAY["build"] = lambda c, p: replays.append(("build", c, p.get("reason")))
        generation_pause._REPLAY["model_refs"] = lambda c, p: replays.append(("model_refs", c, p.get("kind")))
        generation_pause.cancel(A, "trigger:build")
        try:
            generation_pause.cancel(A, "garment:nothing")
            check("4d unknown id", "no error", "LookupError")
        except LookupError:
            check("4d unknown id", "LookupError", "LookupError")

        print("[2] held, then released in order on Resume")
        ran.clear()
        tq.hold_trigger(A, "build", "Build (automatic) · new body", {"reason": "body_change"})
        # model_refs:tpose is held since [1b], so it was first held BEFORE this build entry
        ids = [tq.submit("npc_assets", {"n": i}, agent_name=A, character_hold=True) for i in (1, 2, 3)]
        check("2a nothing dequeued while paused", tq._dequeue(), None)
        garments.enqueue_garment(A, "coat")
        garments.enqueue_garment(A, "scarf")
        check("2b held", garments.held_items(A), ["coat", "scarf"])
        generation_pause.set_paused(A, False)
        garments.wait_idle(10)
        check("2b ran in order", ran, [(A, "coat"), (A, "scarf")])
        got = []
        for _ in range(4):
            row = tq._dequeue()
            if row:
                got.append(row["task_id"])
                tq._finish_task(row["task_id"], "completed")
        check("2a dequeued in order (the cancelled one never)", got, ids)
        check("2c replayed in held order", replays, [("model_refs", A, "tpose"), ("build", A, "body_change")])
        check("2c none left", held_keys(A), [])
        check("4c the cancelled build (outfit_change) never replayed",
              [r for r in replays if r[0] == "build" and r[2] == "outfit_change"], [])

        print("[6] a running job is not interrupted")
        ran.clear()
        boots = garments.enqueue_garment(A, "boots")
        entered.wait(5)
        gloves = garments.enqueue_garment(A, "gloves")
        generation_pause.set_paused(A, True)
        block["boots"].set()
        boots.done.wait(5)
        time.sleep(0.3)
        check("6a running run finished", (boots.result.get("ok"), ran), (True, [(A, "boots")]))
        check("6a the one behind it is held", (garments.held_items(A), gloves.done.is_set()), (["gloves"], False))
        generation_pause.cancel(A, "garment:gloves")

        steps_run = []

        def fits(c, step, explicit):
            steps_run.append(step.name)
            generation_pause.set_paused(c, True)   # the pause comes while the step runs
            return ""
        figure_build._RUNNERS = {**figure_build._RUNNERS, "fits": fits,
                                 "assemble": lambda c, s, e: steps_run.append(s.name) or ""}
        figure_build._run = real_run
        figure_build.plan = lambda *_a, **_kw: [figure_build.Step("fits", "CPU refits", 0),
                                                 figure_build.Step("assemble", "Assemble", 0)]
        from app.core import figure
        figure._delivered = lambda *_a, **_kw: (None, None)
        figure_build._base_snapshot = lambda _c: None
        generation_pause.set_paused(A, False)
        tq.drop_trigger(A, "build")
        figure_build._run_planned(A, "piece_ready", {}, automatic=True)
        build = figure_build.state(A)
        check("6b first step ran, second not", steps_run, ["fits"])
        check("6b paused before", (build["paused"] or {}).get("step"), "assemble")
        check("6b no failure", build["failed"], {})
        check("6b held with its reason", held_keys(A), [("build", {"reason": "piece_ready"})])

        print("[7] the push signal reaches admins only")
        admin = sync_topics.register("u-admin", "t1", "", "", admin=True)
        player = sync_topics.register("u-player", "t2", "", "", admin=False)
        for conn in (admin, player):
            conn.take()   # the opening resync
        generation_pause.set_paused(A, False)
        check("7 admin got the topic", admin.take(), (["generation"], False))
        check("7 player got nothing", player.take(), ([], False))
        sync_topics.unregister(admin)
        sync_topics.unregister(player)
        model_refs._fire_kinds = real_fire_kinds

    print("[8] outbound connects")
    check("8 connects", CONNECTS, [])
    print("PASS" if not FAILS else f"FAIL ({len(FAILS)})")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
