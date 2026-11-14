#!/usr/bin/env python3
"""Ruling A33 — a per-view button of the Wardrobe's step grid runs ONLY its
view of its step; a view it needs that is not accepted is named BEFORE
anything is spent (app/core/garments.py: ``view_plan`` / ``view_plans``,
``check_run``'s ``PrerequisiteMissing``, ``run_garment(view=…)``, the route
``POST /characters/{c}/garments/{item}/run`` with ``prerequisites``).

Usage:
    ./.venv/bin/python scripts/smoke_view_button_scope.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no world, no hub, no GPU, no server. Every
outbound socket connect is refused and counted (must stay 0).

Stubs (the orchestration is REAL, the renders are not):
``garment_images.run_edit_step`` = a recorder that answers each (step, view)
from a script — "ok" publishes attempt 1 through the REAL
``garment_images._publish`` (so the drops of a new image are the real ones:
the later image steps of the view, and a new drafted front drops its back),
"refuse" writes two refused attempts and raises ``GateRefused`` (2 hub jobs,
as the real step's two attempts); ``garment_images.cut_out`` = a recorder
that needs the accepted ghost of its view like the real one;
``garment_mesh.generate`` / ``garments._fit`` = recorders;
``garment_source.ensure_current`` no-op, ``garment_source.find_source`` None.
Each recorded render is one hub job (a refused one two).

The clothing cost table (``garments.HUB_JOBS["clothing:edit_chain"]``): worn
2, ghost 2, cutout 2, mesh 1, fit 0; ``BACK_JOBS`` worn 1, ghost 1. So every
view costs 1 job on its first attempt: worn front 2-1 = 1, worn back 1, ghost
front 2-1 = 1, ghost back 1, cutout front 2-1 = 1 and back 2//2 = 1.
Dependencies (``view_needs``, clothing ``EDIT_STEPS``: worn {source base,
front first, back drafted}, ghost {source worn}, ``PAIR_STEP`` ghost):
worn back <- worn front (draft); ghost v <- worn v (source); ghost front <-
ghost back (pair); cutout v <- ghost v (source).

Ghost gate records carry ``hem_c`` / ``worn_hem_c`` (``garment_gates``
``HEM_AGREE`` 0.02): 0.65 / 0.65 everywhere agrees; a back at 0.70 / 0.65
disagrees with a front at 0.65 (|Δ| 0.05 > 0.02), and ``pair_redo`` names
the back (its hem 0.05 from its worn back, the front's 0).

[S1] The incident (Ylva's blouse, hub job aa57982f): worn front + back
     accepted, the ghost back refused twice (two refused attempts, no final),
     no ghost front. ``view_plan(ghost, front)``: jobs 1, missing [ghost back
     (why pair, for ghost front, jobs 1)], prerequisite_jobs 1, follow_up [].
     ``start_garment(ghost, front, force)`` raises ``PrerequisiteMissing``
     "Needs the piece-only back first — the piece-only front is matched to
     the piece-only back's length. Nothing was rendered", nothing queued; the
     route answers 409 with that text. ``run_garment`` of the same (a queued
     run that finds it at its start): ok False, ``prerequisite`` set, 0
     renders, no failure persisted (``chain_failure`` None).
[S2] The explicit "Render back first" (``prerequisites=True``) on S1:
     renders ghost back (not forced, no pair check), then ghost front
     (forced, with the pair check) = 2 jobs = prerequisite_jobs 1 + jobs 1;
     ran [ghost]; no cut-out, no mesh, no fit.
[S3] A front click with the back accepted (S2's end state, the front
     refused-then-reset: the ghost front removed): plan jobs 1, missing [];
     renders only ghost front (forced, pair check); the cut-out back (its
     ghost accepted, the cut-out missing) is NOT made; no mesh, no fit.
[S4] A back click of the pair step whose new back disagrees with the kept
     front: renders only ghost back (forced); the front is not rendered
     again; the result says ``pair`` {agree False, redo "back", error
     PAIR_REFUSED}; ``garment_info["pair"]`` the same with step "ghost".
[S5] A drafted front (worn front) with everything accepted: plan jobs 1,
     follow_up [worn back (draft, jobs 1)] = 2 jobs; the run renders worn
     front (forced) then worn back (not forced); the ghost front + back
     (dropped by the real publish: the later steps of the front, and the
     back with everything after it) stay dropped — no ghost, no cut-out.
[S6] Nothing rendered yet, a ghost back click: missing [worn front (draft,
     for worn back, jobs 1), worn back (source, for ghost back, jobs 1)] in
     that order, prerequisite_jobs 2, jobs 1; 409 "Needs 2 views (worn
     front, worn back) first — the piece-only back is made from the worn
     back image. Nothing was rendered"; with ``prerequisites`` (through
     ``start_garment`` and the worker): worn front, worn back, ghost back =
     3 jobs = 2 + 1; ran [worn, ghost].
[S7] A cut-out front click (both ghosts accepted, no cut-outs): plan jobs 1,
     missing []; renders only cutout front (forced); no cut-out back, no mesh.
[S8] An empty drafted back (worn back accepted as an EMPTY composite): the
     ghost back is not made (``skipped_view``) — ``check_run`` ValueError
     "…is not made…", the plan says ``skipped`` with jobs 0.
[S9] Run all unchanged on S1's state: ``run_estimate`` steps [ghost, cutout,
     mesh, fit], hub_jobs 2 + 2 + 1 = 5; the run renders ghost back, ghost
     front (pair check), cutout front, cutout back, mesh (forced: an earlier
     step produced output, ``dirty``), fit — the chain, skipping accepted
     views (no worn render).
[S10] A view with more than one step / with the fit step / without a step:
     ValueError "A view runs one image step".

Fails on 9ca64d390 (the commit before A33): S1's front click renders the
ghost back twice and never the front; ``view_plan`` does not exist.
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


def main() -> int:
    socket.socket.connect = _refuse_connect
    with tempfile.TemporaryDirectory(prefix="view-button-scope-") as tmp:
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

        from fastapi import HTTPException
        from app.core import base_body, garment_assembly, garment_images as gi, garment_mesh, garment_source, garments
        from app.core import garment_clothing
        from app.core import garment_store as gs
        from app.models import inventory
        from app.models.character import save_character_profile
        from app.routes import characters as routes
        garment_assembly.schedule = lambda *a, **k: False

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)

        def piece(name):
            iid = inventory.add_item(name=name, category="outfit_piece", prompt_fragment=f"a white {name.lower()}",
                                     outfit_piece={"slots": ["top"], "outfit_types": ["casual"],
                                                   "mesh_mode": "own_mesh"})["id"]
            check(f"inventory {name}", inventory.add_to_inventory("Demo", iid), True)
            check(f"equip {name}", inventory.equip_piece("Demo", iid, source="smoke")["status"], "ok")
            return iid

        bid = piece("Blouse")
        fsig = gs.garment_fsig("Demo", bid)
        check("on the pipeline", base_body.current_base("Demo") is not None, True)

        renders = []
        script = {}  # (step, view) -> "ok" | "refuse" | gate record (accepted with that record)
        OK_GHOST = {"ok": True, "hem_c": 0.65, "worn_hem_c": 0.65, "gate_version": 5}

        def final(step, view, item=None):
            return gs.garment_path("Demo", item or bid, gs.garment_fsig("Demo", item) if item else fsig, "image",
                                   step=step, view=view)

        def gate_for(step, view):
            entry = script.get((step, view), "ok")
            if isinstance(entry, dict):
                return dict(entry)
            if step == "ghost":
                return dict(OK_GHOST)
            return {"ok": True, "gate_version": 4}

        def run_edit_step(character_name, item_id, fsig_, step, view, *, force=False, pair_check=None,
                          prompt_hints=None, state=None, before_composite=None):
            target_final = gs.garment_path(character_name, item_id, fsig_, "image", step=step, view=view)
            if not force and gi._accepted(target_final):
                return target_final
            renders.append((step, view, "forced" if force else "", "pair" if pair_check else ""))
            kind = gi._kind_module(item_id)
            if script.get((step, view)) == "refuse":
                records = []
                for n in (1, 2):
                    path = gs.garment_path(character_name, item_id, fsig_, "image", step=step, view=view, attempt=n)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"refused")
                    record = {"view": view, "ok": False, "reasons": ["hem"], "attempt": n,
                              "gate_version": 5 if step == "ghost" else 4}
                    gs.write_record(path.with_suffix(".json"), {"gate": record})
                    records.append(record)
                renders.append((step, view, "attempt 2", ""))
                raise gi.GateRefused(step, view, records)
            record = gate_for(step, view)
            if pair_check is not None:
                reason = pair_check(record)
                check(f"pair check of {step} {view} passes", reason, None)
            record["attempt"] = 1
            target = gs.garment_path(character_name, item_id, fsig_, "image", step=step, view=view, attempt=1)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f"{step}-{view}-{len(renders)}".encode())
            gs.write_record(target.with_suffix(".json"), {"gate": record})
            extra = None
            if view == "back" and gi._drafted(kind, step):
                extra = {"fit": "composite",
                         "front_sha256": base_body.file_sha256(
                             gs.garment_path(character_name, item_id, fsig_, "image", step=step, view="front"))}
            return gi._publish(character_name, item_id, fsig_, step, view, kind, target, target_final, [record], 1,
                               extra)

        def cut_out(character_name, item_id, fsig_, view, *, force=False):
            target = gs.garment_path(character_name, item_id, fsig_, "image", step="cutout", view=view)
            if not force and gi._accepted(target):
                return target
            if not gi._accepted(gs.garment_path(character_name, item_id, fsig_, "image", step="ghost", view=view)):
                raise base_body.MissingInput(f"The ghost {view} image is missing — run that step first")
            renders.append(("cutout", view, "forced" if force else "", ""))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f"cutout-{view}".encode())
            gs.write_record(target.with_suffix(".json"), {"accepted": True, "side": 1024})
            return target

        def mesh_generate(character_name, item_id, fsig_, force=False, outcome=None):  # outcome: Ruling A58
            renders.append(("mesh", "", "forced" if force else "", ""))
            prepared = gs.garment_path(character_name, item_id, fsig_, "prepared")
            prepared.parent.mkdir(parents=True, exist_ok=True)
            prepared.write_bytes(b"glb")
            gs.write_record(prepared.with_suffix(".json"), {"accepted": True})

        def fit(character_name, item_id, kind, fsig_, bsig, profile):
            renders.append(("fit", "", "", ""))

        def put(step, view, record=None, extra=None, item=None):
            """An accepted final written by hand (a fixture, not a render)."""
            path = final(step, view, item)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"fixture-{step}-{view}".encode())
            rec = record or (dict(OK_GHOST) if step == "ghost" else {"ok": True, "gate_version": 4})
            rec["attempt"] = 1
            gs.write_record(path.with_suffix(".json"), {"accepted": True, "attempt": 1, "gates": {"first": rec},
                                                       **(extra or {})})

        def put_worn(item=None, empty=False):
            put("worn", "front", item=item)
            extra = {"fit": "composite", "front_sha256": base_body.file_sha256(final("worn", "front", item))}
            if empty:
                extra["composite"] = "empty"
            put("worn", "back", extra=extra, item=item)

        def refused_attempts(step, view):
            for n in (1, 2):
                path = gs.garment_path("Demo", bid, fsig, "image", step=step, view=view, attempt=n)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"refused")
                gs.write_record(path.with_suffix(".json"),
                                {"gate": {"view": view, "ok": False, "reasons": ["hem"], "attempt": n,
                                          "gate_version": 5}})

        def plan_brief(p):
            return (p["jobs"], [(m["step"], m["view"], m["why"], tuple(m["for"]), m["jobs"]) for m in p["missing"]],
                    p["prerequisite_jobs"], [(f["step"], f["view"], f["why"], f["jobs"]) for f in p["follow_up"]],
                    p["follow_up_jobs"], p["skipped"])

        stubs = [patch.object(gi, "run_edit_step", run_edit_step), patch.object(gi, "cut_out", cut_out),
                 patch.object(garment_mesh, "generate", mesh_generate), patch.object(garments, "_fit", fit),
                 patch.object(garment_source, "ensure_current", lambda *a, **k: False),
                 patch.object(garment_source, "find_source", lambda *a, **k: None)]
        for s in stubs:
            s.start()
        try:
            print("[S1] the incident: front click, the ghost back refused")
            put_worn()
            refused_attempts("ghost", "back")
            plan = garments.view_plan("Demo", bid, "ghost", "front")
            check("S1 plan", plan_brief(plan), (1, [("ghost", "back", "pair", ("ghost", "front"), 1)], 1, [], 0, None))
            want_error = ("Needs the piece-only back first — the piece-only front is matched to the piece-only "
                          "back's length. Nothing was rendered")
            try:
                garments.start_garment("Demo", bid, steps="ghost", view="front", force=True)
                check("S1 start refused", "started", "PrerequisiteMissing")
            except garments.PrerequisiteMissing as e:
                check("S1 start refused", str(e), want_error)
            check("S1 nothing queued", (garments.queue_state("Demo", bid)["queue_position"],
                                        garments.queue_state("Demo", bid)["queue_running"]), (None, None))
            try:
                routes.run_character_garment("Demo", bid, routes.GarmentRunRequest(step="ghost", view="front",
                                                                                    force=True), {})
                check("S1 route 409", "accepted", 409)
            except HTTPException as e:
                check("S1 route 409", (e.status_code, e.detail), (409, want_error))
            res = garments.run_garment("Demo", bid, steps="ghost", view="front", force=True)
            check("S1 run refused, nothing rendered",
                  (res["ok"], res["step"], res["error"], [m["view"] for m in res["prerequisite"]], renders),
                  (False, "ghost", want_error, ["back"], []))
            check("S1 no failure persisted", gs.chain_failure("Demo", bid, fsig, base_model_sha=""), None)

            print("[S2] explicit 'Render back first'")
            res = garments.run_garment("Demo", bid, steps="ghost", view="front", force=True, prerequisites=True)
            check("S2 back then front, nothing later",
                  (res["ok"], res["ran"], renders),
                  (True, ["ghost"], [("ghost", "back", "", ""), ("ghost", "front", "forced", "pair")]))
            check("S2 jobs = prerequisite 1 + view 1", len(renders), plan["prerequisite_jobs"] + plan["jobs"])
            check("S2 no cut-out made", (gi._accepted(final("cutout", "front")), gi._accepted(final("cutout", "back"))),
                  (False, False))

            print("[S3] front click with the back accepted")
            for suffix in (".png", ".json"):
                final("ghost", "front").with_suffix(suffix).unlink(missing_ok=True)
            del renders[:]
            plan = garments.view_plan("Demo", bid, "ghost", "front")
            check("S3 plan", plan_brief(plan), (1, [], 0, [], 0, None))
            res = garments.run_garment("Demo", bid, steps="ghost", view="front", force=True)
            check("S3 the front alone", (res["ok"], res["ran"], renders, res.get("pair")),
                  (True, ["ghost"], [("ghost", "front", "forced", "pair")], None))
            check("S3 cut-out back not made", gi._accepted(final("cutout", "back")), False)

            print("[S4] back click, the new back disagrees with the kept front")
            del renders[:]
            script[("ghost", "back")] = {"ok": True, "hem_c": 0.70, "worn_hem_c": 0.65, "gate_version": 5}
            plan = garments.view_plan("Demo", bid, "ghost", "back")
            check("S4 plan", plan_brief(plan), (1, [], 0, [], 0, None))
            res = garments.run_garment("Demo", bid, steps="ghost", view="back", force=True)
            pair = {"agree": False, "redo": "back", "error": garment_clothing.PAIR_REFUSED}
            check("S4 the back alone, the pair named", (res["ok"], renders, res.get("pair")),
                  (True, [("ghost", "back", "forced", "")], pair))
            check("S4 garment_info pair", garments.garment_info("Demo", bid)["pair"], {"step": "ghost", **pair})
            del script[("ghost", "back")]

            print("[S5] a drafted front re-drafts its back")
            put("ghost", "back")
            put("ghost", "front")
            del renders[:]
            plan = garments.view_plan("Demo", bid, "worn", "front")
            check("S5 plan", plan_brief(plan), (1, [], 0, [("worn", "back", "draft", 1)], 1, None))
            res = garments.run_garment("Demo", bid, steps="worn", view="front", force=True)
            check("S5 front then its back", (res["ok"], res["ran"], renders),
                  (True, ["worn"], [("worn", "front", "forced", ""), ("worn", "back", "", "")]))
            check("S5 jobs = view 1 + follow-up 1", len(renders), plan["jobs"] + plan["follow_up_jobs"])
            check("S5 the ghosts stay dropped", (final("ghost", "front").exists(), final("ghost", "back").exists()),
                  (False, False))
            check("S5 garment_info pair gone", garments.garment_info("Demo", bid)["pair"], None)

            print("[S6] nothing rendered yet: a ghost back click")
            cid = piece("Cardigan")
            cfsig = gs.garment_fsig("Demo", cid)
            del renders[:]
            plan = garments.view_plan("Demo", cid, "ghost", "back")
            check("S6 plan", plan_brief(plan),
                  (1, [("worn", "front", "draft", ("worn", "back"), 1),
                       ("worn", "back", "source", ("ghost", "back"), 1)], 2, [], 0, None))
            try:
                garments.check_run("Demo", cid, steps="ghost", view="back")
                check("S6 refused", "ok", "PrerequisiteMissing")
            except garments.PrerequisiteMissing as e:
                check("S6 refused", str(e), "Needs 2 views (worn front, worn back) first — the piece-only back is "
                                            "made from the worn back image. Nothing was rendered")
            started = garments.start_garment("Demo", cid, steps="ghost", view="back", force=True,
                                             prerequisites=True)
            check("S6 started", started.get("started"), True)
            check("S6 idle", garments.wait_idle(60), True)
            check("S6 worn front, worn back, ghost back", renders,
                  [("worn", "front", "", ""), ("worn", "back", "", ""), ("ghost", "back", "forced", "")])
            check("S6 jobs = prerequisites 2 + view 1", len(renders), plan["prerequisite_jobs"] + plan["jobs"])
            check("S6 the ghost front not made", gi._accepted(gs.garment_path("Demo", cid, cfsig, "image",
                                                                               step="ghost", view="front")), False)

            print("[S7] a cut-out front click")
            put_worn()
            put("ghost", "back")
            put("ghost", "front")
            del renders[:]
            plan = garments.view_plan("Demo", bid, "cutout", "front")
            check("S7 plan", plan_brief(plan), (1, [], 0, [], 0, None))
            res = garments.run_garment("Demo", bid, steps="cutout", view="front", force=True)
            check("S7 the cut-out front alone", (res["ok"], res["ran"], renders),
                  (True, ["cutout"], [("cutout", "front", "forced", "")]))
            check("S7 no cut-out back", gi._accepted(final("cutout", "back")), False)

            print("[S8] an empty drafted back")
            eid = piece("Necklace")
            put_worn(item=eid, empty=True)
            plan = garments.view_plan("Demo", eid, "ghost", "back")
            check("S8 plan skipped", (plan["jobs"], bool(plan["skipped"]), plan["missing"]), (0, True, []))
            try:
                garments.check_run("Demo", eid, steps="ghost", view="back")
                check("S8 refused", "ok", "ValueError")
            except garments.PrerequisiteMissing:
                check("S8 refused", "PrerequisiteMissing", "ValueError")
            except ValueError as e:
                check("S8 refused", "is not made" in str(e), True)

            print("[S9] Run all unchanged")
            for step in ("ghost", "cutout"):
                for view in gs.GARMENT_VIEWS:
                    for suffix in (".png", ".json"):
                        final(step, view).with_suffix(suffix).unlink(missing_ok=True)
            refused_attempts("ghost", "back")
            del renders[:]
            est = garments.run_estimate("Demo", bid)
            check("S9 estimate", (est["steps"], est["hub_jobs"], est["note"]),
                  (["ghost", "cutout", "mesh", "fit"], 5, "ghost 2 + cutout 2 + mesh 1"))
            res = garments.run_garment("Demo", bid)
            check("S9 the chain", (res["ok"], res["ran"], renders),
                  (True, ["ghost", "cutout", "mesh", "fit"],
                   [("ghost", "back", "", ""), ("ghost", "front", "", "pair"), ("cutout", "front", "", ""),
                    ("cutout", "back", "", ""), ("mesh", "", "forced", ""), ("fit", "", "", "")]))
            check("S9 jobs = the estimate", len([r for r in renders if r[0] != "fit"]), est["hub_jobs"])

            print("[S10] a view names one image step")
            for steps in (["worn", "ghost"], "fit", None):
                try:
                    garments.check_run("Demo", bid, steps=steps, view="front")
                    check(f"S10 {steps}", "accepted", "ValueError")
                except ValueError as e:
                    check(f"S10 {steps}", str(e), "A view runs one image step")
        finally:
            for s in stubs:
                s.stop()

    check("no outbound connection", OUTBOUND, [])
    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
