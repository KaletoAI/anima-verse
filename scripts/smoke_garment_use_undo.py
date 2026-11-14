#!/usr/bin/env python3
"""Ruling A79 — Undo of a "Use this" on a stored image attempt (app/core/garment_use_undo.py,
``garments.use_attempt`` / ``use_undo_state`` / ``undo_use``, the routes
POST …/garments/{item}/images/{step}/{view}/attempts/{n}/use and POST …/garments/{item}/images/undo-use, the
GET panel's ``use_undo``, ``artefact_graph.scan``).

Usage:
    ./.venv/bin/python scripts/smoke_garment_use_undo.py

A throwaway storage + instance directory with a copy of the repo's ``human`` package; no world, no hub, no
server. Every outbound socket connect is refused and counted (must stay 0).

Fixture (the frame of smoke_attempt_pick_and_use.py): Demo with an own-mesh Blouse on the pipeline. Ylva's state
of 2026-11-15: worn front + back, ghost back accepted, the cut-out back made; the ghost FRONT has no final and two
stored attempts, both refused for the hem; the chain failure of step ghost is recorded; a prepared + raw mesh of
an earlier run and one kept mesh attempt are on disk (bytes "old-prepared", "old-raw", "old-kept").

THE CASES, DERIVED BY HAND (module docstring of garment_use_undo)
[1] Use attempt 1 of the ghost front (refused -> accepted by the user). Before the click the snapshot holds the
    files the click replaces or drops: the ghost and cut-out FRONT images (+ records) — none there, so they are
    recorded absent —, the raw + prepared mesh (+ records) and the failure record — there, copied —, and the
    kept mesh attempt. The ghost is no drafted step, so no back is touched.
    After the click: the ghost front is attempt 1's bytes, the mesh and the kept attempt are gone, the failure is
    cleared (Ruling A37); ``use_undo_state``: step ghost, view front, attempt 1, passing False, available True,
    why_not "", images {ghost front: before False, cutout front: before False}, mesh_before True,
    refusal_before True. The panel (GET) carries the same block.
[2] Made since (as a Build would): a cut-out front and a new prepared mesh ("new-prepared").
[3] Undo: the ghost front image + record removed (not there before), the cut-out front removed (made since),
    the prepared mesh back to "old-prepared", the raw back, the kept attempt back ("old-kept"), the failure record
    back (step ghost); the ghost back and the cut-out back untouched; the snapshot gone -> state None. The
    attempts are still on disk: "Use this" on attempt 1 is offered again (in_use False, block "").
    Undo again -> UndoUnavailable "Nothing to undo"; the route answers 409.
[4] Replaced since: use attempt 1, then a run rewrites the ghost front (other bytes) -> available False,
    why_not REPLACED_SINCE; undo -> UndoUnavailable with that reason, nothing restored (the mesh stays absent).
[5] The last click is what Undo takes back: use attempt 1, then attempt 2 -> the snapshot is attempt 2's
    (attempt 2, its "before" = attempt 1's final); undo -> the ghost front is attempt 1's bytes again.
[6] A click that publishes nothing keeps the snapshot: attempt 1 again while it is in use -> changed False, the
    state still attempt 1's; an unusable attempt (3, none stored) -> AttemptUnusable, no ``….pending`` folder
    left, the state unchanged.
[7] A run holds the piece's lock -> ``UseBusy`` for undo; the route 409.
[8] The artefact GC sees the snapshot as files of the garment group (``scan``: none of them unknown).
"""
import json
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
OUTBOUND = []


def check(label, got, want):
    ok = got == want
    tail = "" if ok else f" — expected {want!r}"[:400]
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + tail)
    if not ok:
        FAILS.append(label)


def _refuse_connect(self, address, *a, **k):
    OUTBOUND.append(address)
    raise OSError("smoke: no outbound connections")


def part(root: Path):
    from fastapi import HTTPException
    from app.core import artefact_graph, base_body, garment_images as gi, garment_source, garment_use_undo as gu
    from app.core import garments
    from app.core import garment_store as gs
    from app.models import inventory
    from app.models.character import save_character_profile
    from app.routes import characters as routes
    human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
             "character_appearance": "slender",
             "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"}, "build": {"type": "athletic"},
                            "hair": {"length": "medium", "color": "blonde"}}}
    check("create Demo", save_character_profile("Demo", human, create_new=True), True)
    bid = inventory.add_item(name="Blouse", category="outfit_piece", prompt_fragment="a white blouse",
                             outfit_piece={"slots": ["top"], "outfit_types": ["casual"], "mesh_mode": "own_mesh"})["id"]
    check("inventory", inventory.add_to_inventory("Demo", bid), True)
    check("equip", inventory.equip_piece("Demo", bid, source="smoke")["status"], "ok")
    fsig = gs.garment_fsig("Demo", bid)
    ghost_v = gi._kind_module(bid).GATE_VERSIONS["ghost"]
    ok_ghost = {"ok": True, "hem_c": 0.45, "worn_hem_c": 0.45, "gate_version": ghost_v}

    def path(step, view, attempt=0):
        return gs.garment_path("Demo", bid, fsig, "image", step=step, view=view, attempt=attempt)

    def put(step, view, record=None, extra=None):
        p = path(step, view)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(f"fixture-{step}-{view}".encode())
        rec = dict(record or (ok_ghost if step == "ghost" else {"ok": True, "gate_version": 4}), attempt=1)
        gs.write_record(p.with_suffix(".json"), {"accepted": True, "attempt": 1, "gates": {"first": rec},
                                                 "created_at": "2026-11-13T22:00:00+00:00", **(extra or {})})

    def attempt(n):
        p = path("ghost", "front", n)
        p.write_bytes(f"ghost-front-try{n}".encode())
        gs.write_record(p.with_suffix(".json"), {
            "garment": {"step": "ghost", "view": "front", "attempt": n}, "created_at": "2026-11-14T23:18:07+00:00",
            "gate": {"view": "front", "ok": False, "gate_version": ghost_v, "attempt": n, "hem_c": 0.46146,
                     "worn_hem_c": 0.32788,
                     "reasons": ["garment ends at another height than the worn piece: |Δ| 0.1336 Hb > 0.02 Hb"]}})

    mesh = {part: gs.garment_path("Demo", bid, fsig, part) for part in ("raw", "prepared")}
    kept = gs.garment_path("Demo", bid, fsig, "mesh_attempt", attempt=1)

    def old_mesh():
        for part, p in mesh.items():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(f"old-{part}".encode())
            gs.write_record(p.with_suffix(".json"), {"accepted": True, "which": f"old-{part}"})
        kept.parent.mkdir(parents=True, exist_ok=True)
        kept.write_bytes(b"old-kept")

    put("worn", "front")
    put("worn", "back", extra={"fit": "composite", "front_sha256": base_body.file_sha256(path("worn", "front"))})
    put("ghost", "back")
    put("cutout", "back", record={"ok": True})
    attempt(1)
    attempt(2)
    old_mesh()
    gs.record_failure("Demo", bid, fsig, step="ghost", error="ghost front refused — ends at another height")
    untouched = {p: p.read_bytes() for p in (path("ghost", "back"), path("cutout", "back"), path("worn", "front"))}
    folder = gu.undo_dir("Demo", bid, fsig)

    with patch.object(garment_source, "find_source", lambda *a, **k: None):
        print("[1] use attempt 1 (refused)")
        check("no snapshot yet", garments.use_undo_state("Demo", bid), None)
        res = garments.use_attempt("Demo", bid, "ghost", "front", 1)
        check("result", (res["changed"], res["passing"], res["user_accepted"]), (True, False, True))
        check("ghost front = attempt 1", path("ghost", "front").read_bytes(), b"ghost-front-try1")
        check("mesh + kept attempt dropped, failure cleared",
              (mesh["prepared"].is_file(), mesh["raw"].is_file(), kept.is_file(),
               gs.chain_failure("Demo", bid, fsig)), (False, False, False, None))
        state = garments.use_undo_state("Demo", bid)
        check("state", {k: state[k] for k in ("step", "view", "attempt", "passing", "available", "why_not",
                                              "mesh_before", "refusal_before")},
              {"step": "ghost", "view": "front", "attempt": 1, "passing": False, "available": True, "why_not": "",
               "mesh_before": True, "refusal_before": True})
        check("state images", sorted((i["step"], i["view"], i["before"]) for i in state["images"]),
              [("cutout", "front", False), ("ghost", "front", False)])
        panel = routes.get_character_garment("Demo", bid, {})
        check("panel use_undo", panel.get("use_undo"), state)
        check("no pending folder", folder.with_name(folder.name + ".pending").exists(), False)

        print("[2] made since")
        put("cutout", "front", record={"ok": True})
        mesh["prepared"].write_bytes(b"new-prepared")

        print("[3] undo")
        res = routes.undo_character_garment_attempt_use("Demo", bid, {})
        check("result", (res["step"], res["view"], res["attempt"]), ("ghost", "front", 1))
        check("ghost front + record removed", (path("ghost", "front").exists(),
                                               path("ghost", "front").with_suffix(".json").exists()), (False, False))
        check("cut-out front made since removed", path("cutout", "front").exists(), False)
        check("mesh back", (mesh["prepared"].read_bytes(), mesh["raw"].read_bytes(), kept.read_bytes(),
                            gs.read_record(mesh["prepared"].with_suffix(".json")).get("which")),
              (b"old-prepared", b"old-raw", b"old-kept", "old-prepared"))
        check("failure back", (gs.chain_failure("Demo", bid, fsig) or {}).get("step"), "ghost")
        check("other views untouched", all(p.read_bytes() == b for p, b in untouched.items()), True)
        check("snapshot gone", (garments.use_undo_state("Demo", bid), folder.exists()), (None, False))
        plan = garments.use_plans("Demo", bid)["ghost"]["front"]["1"]
        check("attempt 1 offered again", (plan["in_use"], plan["block"], plan["passing"]), (False, "", False))
        try:
            garments.undo_use("Demo", bid)
            check("undo again raises", "undone", "UndoUnavailable")
        except gu.UndoUnavailable as e:
            check("undo again raises", str(e), gu.NOTHING_TO_UNDO)
        try:
            routes.undo_character_garment_attempt_use("Demo", bid, {})
            check("route 409", "ok", 409)
        except HTTPException as e:
            check("route 409", (e.status_code, e.detail), (409, gu.NOTHING_TO_UNDO))

        print("[4] replaced since")
        garments.use_attempt("Demo", bid, "ghost", "front", 1)
        path("ghost", "front").write_bytes(b"a later render")
        state = garments.use_undo_state("Demo", bid)
        check("not available", (state["available"], state["why_not"]), (False, gu.REPLACED_SINCE))
        try:
            garments.undo_use("Demo", bid)
            check("undo raises", "undone", "UndoUnavailable")
        except gu.UndoUnavailable as e:
            check("undo raises", str(e), gu.REPLACED_SINCE)
        check("nothing restored", mesh["prepared"].is_file(), False)

        print("[5] the last click")
        old_mesh()
        garments.use_attempt("Demo", bid, "ghost", "front", 1)
        garments.use_attempt("Demo", bid, "ghost", "front", 2)
        state = garments.use_undo_state("Demo", bid)
        check("snapshot of attempt 2", (state["attempt"], state["available"],
                                        sorted((i["step"], i["view"], i["before"]) for i in state["images"])),
              (2, True, [("cutout", "front", False), ("ghost", "front", True)]))
        garments.undo_use("Demo", bid)
        check("back to attempt 1", (path("ghost", "front").read_bytes(),
                                    gs.read_record(path("ghost", "front").with_suffix(".json")).get("attempt")),
              (b"ghost-front-try1", 1))

        print("[6] a click that publishes nothing")
        garments.use_attempt("Demo", bid, "ghost", "front", 2)
        before = garments.use_undo_state("Demo", bid)
        check("again: changed False", garments.use_attempt("Demo", bid, "ghost", "front", 2)["changed"], False)
        check("snapshot kept", garments.use_undo_state("Demo", bid), before)
        try:
            garments.use_attempt("Demo", bid, "ghost", "front", 3)
            check("unusable raises", "used", "AttemptUnusable")
        except gi.AttemptUnusable:
            check("unusable raises", True, True)
        check("no pending folder, state unchanged",
              (folder.with_name(folder.name + ".pending").exists(), garments.use_undo_state("Demo", bid)),
              (False, before))

        print("[7] a run holds the lock")
        lock = gs.run_item_lock("Demo", bid)
        lock.acquire()
        try:
            try:
                garments.undo_use("Demo", bid)
                check("UseBusy", "undone", "UseBusy")
            except garments.UseBusy:
                check("UseBusy", True, True)
            try:
                routes.undo_character_garment_attempt_use("Demo", bid, {})
                check("route 409 busy", "ok", 409)
            except HTTPException as e:
                check("route 409 busy", e.status_code, 409)
        finally:
            lock.release()

        print("[8] the artefact GC")
        nodes, unknown = artefact_graph.scan("Demo")
        snap = sorted(p for p in folder.rglob("*") if p.is_file())
        group = [n for n in nodes if n.kind == "garment" and n.parents.get("fsig") == fsig]
        check("snapshot files in the garment group", bool(snap) and all(p in group[0].files for p in snap), True)
        check("none unknown", [p for p in unknown if folder in p.parents], [])


def main() -> int:
    socket.socket.connect = _refuse_connect
    with tempfile.TemporaryDirectory(prefix="garment-use-undo-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)
        from app.core import garment_assembly
        garment_assembly.schedule = lambda *a, **k: False
        part(root)
    check("outbound connects", len(OUTBOUND), 0)
    print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall ok")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
