#!/usr/bin/env python3
"""Footwear, task 1: kind ``footwear``, method ``shoe``, the own-mesh piece kinds
(plan ``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md`` Task 1; spec
``docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md`` § 5.1, § 5.6, § 9.1).

Usage:
    ./.venv/bin/python scripts/smoke_footwear_kind.py

Runs against a THROWAWAY storage directory with a copy of the repo's ``human``
package — no real world, no hub, no GPU, no server. Synthetic bytes only.
``garments.run_queued`` is stubbed (records its item ids, answers ok). Every
expectation is derived by hand below from the Global Constraints and Task 1.

Fixture: ``Kira`` (human-roleplay, female, 168 cm, on the base-body pipeline)
and ``Mira`` (human-roleplay, male, 190 cm, on the pipeline — another base
signature). Items, inserted through ``app.models.inventory``:
``heels`` (slots [feet], own_mesh true, item image = 64 fixed bytes),
``dress`` (slots [top], own_mesh true), ``boots`` (slots [feet], own_mesh
absent = false), ``tights`` (slots [feet, legs], own_mesh true). Kira holds
and wears heels + dress; Mira holds heels.

[K1] Kind and steps.
     garment_kind_of: heels -> "footwear" (own_mesh, slots exactly [feet]);
     dress -> "clothing" (own_mesh, no feet); boots -> None (no own_mesh);
     tights -> "clothing" (own_mesh, feet among other slots — controller
     ruling 2026-11-10: footwear is a piece worn in feet ALONE).
     OWN_MESH_PIECE_KINDS == ("clothing", "footwear") == GRAFTED_PIECE_KINDS
     (footwear is grafted since Task 16).
     steps_for("footwear", "shoe") == FOOTWEAR_STEPS == ("source", "empty",
     "cutout", "mesh", "insole", "fit"); steps_for("footwear", "edit_chain") ->
     ValueError; steps_for("clothing", "shoe") -> ValueError (no method choice
     either way). kind_method("footwear", Kira, profile) == "shoe".
     _garment_kind(heels) == "footwear"; garments._item(Kira, heels) ->
     (heels, "footwear"); garments._item(Mira, dress) -> ValueError (not held);
     garment_mesh._kind(heels) -> ValueError (its mesh is footwear_source's).
     Own-mesh set membership: worn_garments(Kira) == sorted([dress, heels]),
     held_clothing(Kira) == sorted([dress, heels]), held_clothing(Mira) ==
     [heels]; layer_order([dress, heels])["order"] == [dress] (footwear takes no
     part in layering). garment_fit.FIT_VERSION["footwear"] == 5 (7b298358: placed on the skinned ball; Task 15:
     the cut applied and gated; T21 round 4: the toe conform; boots Task 1: the foot measured below the ankle).
[K2] Footwear fsig — no base in it.
     IMG = sha256 of the heels image bytes.
     ssig = md5(json.dumps({"image": IMG, "version": 2, "seed": 0},
     sort_keys=True))[:12] (FOOTWEAR_SOURCE_VERSION 2 since the Task 21 fix
     round — a pre-fix skipped ``empty`` is unreachable; seed 0 = never
     regenerated) == footwear_source.current_ssig(heels).
     fsig = md5(json.dumps({"kind": "footwear", "ssig": ssig,
     "insole_version": 5, "width_cap": 1.1, "fit_version": 7},
     sort_keys=True))[:12] — the width cap without an override is 1.10.
     base_signature(Kira) != base_signature(Mira) (precondition); Kira gets
     base front/back view files (Mira none) -> garment_fsig(Kira, heels) ==
     garment_fsig(Mira, heels) == fsig.
     Kira's profile footwear_width_cap {heels: 1.05} -> width_cap 1.05 and
     fsig' = the same md5 with "width_cap": 1.05 != fsig; an override 1.2 is
     clamped to 1.10 -> fsig again; 0.9 clamps to 1.00.
     Kira's base model model3d/<bsig>.glb b"model-1" -> b"model-2": fsig
     unchanged (the base model is never an fsig input).
[K3] mesh_items_token(Kira, pieces={"feet": heels}) ==
     "|meshitems:" + heels + "|worn:feet=" + heels — the string the clothing
     kind produced before footwear existed (the feet piece was flagged as
     clothing then), so no outfit signature moves in P1.
     mesh_items_token(Kira, pieces={"feet": boots}) == "" (not own-mesh).
[K4] Delivery rule (Task 16, spec § 9.1: footwear is grafted like clothing,
     never painted; smoke_footwear_delivery.py has the unfitted cases).
     Kira's base model b"model-2", SHA = its sha256. Both heels and dress get
     an accepted fit record on SHA under their current fsig (dress: kind
     clothing; heels: kind footwear, method shoe, fit_version 6).
     Retexture mode, pieces {top: dress, feet: heels}:
       resolve_mesh_items -> {intended sorted([dress, heels]), effective
       sorted([dress, heels]) (the heels' fit is grafted), warnings [], mode
       "retexture", unpainted sorted([dress, heels]), missing {}};
       run_queued was asked for sorted([dress, heels]) (the shoe chain is
       part of the outfit build, spec § 12).
     Mesh mode (profile outfit_body_mode "mesh"): the same but mode "mesh".
     A retexture-mode record that painted heels (intended [dress, heels],
     effective [dress], no unpainted): mesh_items_ready(Kira, record,
     base_sha=SHA) == [heels] (its fit landed: the rebuild drops it from the
     texture) and, in retexture mode, mesh_items_off_rule == [heels] too
     (footwear is never painted). A mesh-mode record that left both out
     (unpainted [dress, heels], missing {heels: "other"}):
     mesh_items_missing(Kira, record, base_sha=SHA) == [] (both have their
     fit — judged now, whatever the record says) and mesh_items_off_rule in
     retexture mode == [] (nothing of it belongs painted on).
[K5] Every entry point runs the SHOE chain for footwear, never the clothing
     chain (Task 6 replaced the temporary skip; the REAL queue functions,
     run_queued restored). ``garment_footwear.run_chain`` is a recorder
     answering R = {ok: True, fsig: F, ran: [], fit: "pending"} (F = the
     current footwear fsig, [K2]); ``garments._fit``,
     ``garment_images.run_edit_step`` / ``cut_out`` and
     ``garment_mesh.generate`` record any call.
       run_garment(Kira, heels) == R, recorder (Kira, heels, None, False);
       run_garment(…, steps="mesh", force=True) == R, recorder (["mesh"],
       True);
       start_garment(Kira, heels) == {started True, queued False, position
       0, behind None} (idle character) -> recorder (None, False);
       start_garment(…, steps="empty", force=True) -> recorder (["empty"],
       True); start_garment(…, view="front") -> ValueError (no views);
       enqueue_garment(Kira, heels): job.done after the worker, job.result
       == R; run_queued(Kira, [heels]) == {heels: R};
       the Wardrobe run route run_character_garment(Kira, heels, {}) answers
       {started True, …} and the recorder gets (None, False);
       the clothing-chain recorders saw no call for heels at all;
       after_base_model(Kira) (hair creation stubbed off, enqueue_garment
       wrapped to record its ids and answer a done job): the ids == [dress, heels]
       (dress has no prepared mesh -> its fit is "outdated"; heels have no fit
       — since Task 25 the trigger queues the worn shoe too: fit-only, its item
       steps cached under the ssig, a refused source never);
       refit sweep: an old clothing-era fit of heels under fsig
       "0123456789ab" (kind clothing, fit_version 6 < 7, accepted on SHA) and
       a too-small "fit" failure under "0123456789cd" (scale_retry absent,
       base SHA) -> outdated_fits / refused_fits name no heels group (its
       current fsig is the footwear one, its method "shoe"), and
       refit_character(Kira) calls garments._fit 0 times for heels.
     After all of it: the character's queue is idle and empty
     (queue_running None, queue []), status(Kira, heels) has no running
     step, cached_failure(Kira, heels) is None and no file
     garments/failed/<heels>_<current fsig>.json exists.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def raises(label, fn, exc, contains=""):
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        ok = isinstance(e, exc) and contains in str(e)
        check(label, "raised" if ok else f"{type(e).__name__}: {e}", "raised")
        return
    check(label, "no error", "raised")


def md5_12(payload) -> str:
    return hashlib.md5(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="footwear-kind-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import (base_body, garment_assembly, garment_fit, garment_mesh, garment_set, garments,
                              model_refs)
        from app.core import garment_store as gs
        from app.models import inventory
        from app.models.character import get_character_dir, get_character_profile, save_character_profile

        model_refs.schedule_outfit_render = lambda *a, **k: None
        garment_assembly.schedule = lambda name, signature=None: True
        QUEUED = []
        real_run_queued = garments.run_queued

        def run_queued(character_name, item_ids):
            ids = list(item_ids)
            QUEUED.append(ids)
            return {i: {"ok": True, "ran": []} for i in ids}
        garments.run_queued = run_queued

        for name, gender, height in (("Kira", "female", 168), ("Mira", "male", 190)):
            check(f"create {name}", save_character_profile(name, {
                "template": "human-roleplay", "gender": gender, "age": 30, "height": height,
                "body_slots": {"hair": {"length": "medium", "color": "blonde"}}}, create_new=True), True)
            check(f"pipeline {name}", base_body.set_pipeline(name, True), True)

        def piece(name, slots, own_mesh=None):
            op = {"slots": slots, "outfit_types": ["casual"]}
            if own_mesh is not None:
                op["own_mesh"] = own_mesh
            return inventory.add_item(name=name, category="outfit_piece", prompt_fragment=f"plain {name.lower()}",
                                      outfit_piece=op)["id"]

        heels = piece("Heels", ["feet"], True)
        dress = piece("Dress", ["top"], True)
        boots = piece("Boots", ["feet"])
        tights = piece("Tights", ["feet", "legs"], True)
        image_bytes = bytes(range(64))
        item_dir = inventory._get_item_dir(heels, create=True)
        (item_dir / "image.png").write_bytes(image_bytes)
        check("item image set", inventory.set_item_image(heels, "image.png"), True)
        for item in (heels, dress):
            check(f"Kira holds {item}", inventory.add_to_inventory("Kira", item), True)
            check(f"Kira wears {item}", inventory.equip_piece("Kira", item, source="smoke")["status"], "ok")
        check("Mira holds heels", inventory.add_to_inventory("Mira", heels), True)

        print("[K1] kind and steps")
        get = inventory.get_item
        check("kind heels", garment_set.garment_kind_of(get(heels)), "footwear")
        check("kind dress", garment_set.garment_kind_of(get(dress)), "clothing")
        check("kind boots", garment_set.garment_kind_of(get(boots)), None)
        check("kind tights (feet + legs)", garment_set.garment_kind_of(get(tights)), "clothing")
        check("FOOTWEAR", garment_set.FOOTWEAR, "footwear")
        check("OWN_MESH_PIECE_KINDS", garment_set.OWN_MESH_PIECE_KINDS, ("clothing", "footwear"))
        check("GRAFTED_PIECE_KINDS", garment_set.GRAFTED_PIECE_KINDS, ("clothing", "footwear"))
        check("SHOE", gs.SHOE, "shoe")
        check("FOOTWEAR_STEPS", gs.FOOTWEAR_STEPS, ("source", "empty", "cutout", "mesh", "insole", "fit"))
        check("steps_for footwear shoe", gs.steps_for("footwear", "shoe"), gs.FOOTWEAR_STEPS)
        raises("steps_for footwear edit_chain", lambda: gs.steps_for("footwear", "edit_chain"), ValueError)
        raises("steps_for clothing shoe", lambda: gs.steps_for("clothing", "shoe"), ValueError)
        check("kind_method footwear", gs.kind_method("footwear", "Kira", get_character_profile("Kira")), "shoe")
        check("_garment_kind heels", gs._garment_kind(heels), "footwear")
        check("garment_method heels", gs.garment_method("Kira", heels), "shoe")
        got = garments._item("Kira", heels)
        check("_item Kira heels", (got[0]["id"], got[1]), (heels, "footwear"))
        raises("_item Mira dress (not held)", lambda: garments._item("Mira", dress), ValueError,
               "not a garment of Mira")
        raises("garment_mesh._kind heels", lambda: garment_mesh._kind(heels), ValueError)
        check("garment_mesh._kind dress", garment_mesh._kind(dress), "clothing")
        check("worn_garments Kira", garment_set.worn_garments("Kira"), sorted([dress, heels]))
        check("held_clothing Kira", garment_set.held_clothing("Kira"), sorted([dress, heels]))
        check("held_clothing Mira", garment_set.held_clothing("Mira"), [heels])
        check("layer_order skips footwear", garment_set.layer_order([dress, heels])["order"], [dress])
        check("FIT_VERSION footwear", garment_fit.FIT_VERSION.get("footwear"), 7)

        print("[K2] footwear fsig")
        from app.core import footwear_source, garment_footwear
        img = hashlib.sha256(image_bytes).hexdigest()
        ssig = md5_12({"image": img, "version": 2, "seed": 0})
        check("current_ssig", footwear_source.current_ssig(heels), ssig)

        def fsig_by_hand(cap):
            return md5_12({"kind": "footwear", "ssig": ssig, "insole_version": 5, "width_cap": cap,
                           "fit_version": 7})
        fsig = fsig_by_hand(1.1)
        kira_bsig = base_body.base_signature("Kira")
        check("base signatures differ", kira_bsig != base_body.base_signature("Mira"), True)
        refs = get_character_dir("Kira") / "model_refs"
        refs.mkdir(parents=True, exist_ok=True)
        (refs / f"tpose_{kira_bsig}.png").write_bytes(b"front view of Kira")
        (refs / f"tpose_back_{kira_bsig}.png").write_bytes(b"back view of Kira")
        check("fsig Kira by hand", gs.garment_fsig("Kira", heels), fsig)
        check("fsig Mira == Kira", gs.garment_fsig("Mira", heels), fsig)

        def set_cap(value):
            profile = get_character_profile("Kira")
            if value is None:
                profile.pop("footwear_width_cap", None)
            else:
                profile["footwear_width_cap"] = {heels: value}
            check(f"save cap {value}", save_character_profile("Kira", profile), True)
        set_cap(1.05)
        check("width_cap 1.05", garment_footwear.width_cap(get_character_profile("Kira"), heels), 1.05)
        check("fsig cap 1.05 by hand", gs.garment_fsig("Kira", heels), fsig_by_hand(1.05))
        check("fsig cap 1.05 differs", gs.garment_fsig("Kira", heels) != fsig, True)
        set_cap(1.2)
        check("width_cap 1.2 clamps", garment_footwear.width_cap(get_character_profile("Kira"), heels), 1.1)
        check("fsig cap clamped", gs.garment_fsig("Kira", heels), fsig)
        set_cap(0.9)
        check("width_cap 0.9 clamps", garment_footwear.width_cap(get_character_profile("Kira"), heels), 1.0)
        set_cap(None)
        model_dir = get_character_dir("Kira") / "model3d"
        model_dir.mkdir(parents=True, exist_ok=True)
        model = model_dir / f"{kira_bsig}.glb"
        model.write_bytes(b"model-1")
        f1 = gs.garment_fsig("Kira", heels)
        model.write_bytes(b"model-2")
        os.utime(model, (model.stat().st_atime + 2, model.stat().st_mtime + 2))
        check("base model bytes: same fsig", (f1, gs.garment_fsig("Kira", heels)), (fsig, fsig))

        print("[K3] mesh items token")
        check("token feet piece", model_refs.mesh_items_token("Kira", pieces={"feet": heels}),
              "|meshitems:" + heels + "|worn:feet=" + heels)
        check("token unflagged feet piece", model_refs.mesh_items_token("Kira", pieces={"feet": boots}), "")

        print("[K4] delivery rule: a fitted shoe is grafted like clothing")
        sha = hashlib.sha256(b"model-2").hexdigest()
        check("base sha", base_body.base_model_sha256("Kira", kira_bsig), sha)
        for item_id, kind, method in ((dress, "clothing", "edit_chain"), (heels, "footwear", "shoe")):
            f = gs.garment_fsig("Kira", item_id)
            fit = gs.garment_path("Kira", item_id, f, "fit")
            fit.parent.mkdir(parents=True, exist_ok=True)
            fit.write_bytes(b"fit " + item_id.encode())
            gs.write_record(fit.with_suffix(".json"), {
                "accepted": True, "kind": kind, "method": method, "item_id": item_id, "fsig": f,
                "base_signature": kira_bsig, "base_model_sha256": sha,
                "fit_version": garment_fit.FIT_VERSION.get(kind)})
            check(f"accepted fit {item_id}", gs.accepted_fit("Kira", item_id, base_model_sha=sha) is not None, True)
        pieces = {"top": dress, "feet": heels}
        check("no FOOTWEAR_PREVIEW_ONLY", hasattr(base_body, "FOOTWEAR_PREVIEW_ONLY"), False)
        both = sorted([dress, heels])
        QUEUED.clear()
        out = base_body.resolve_mesh_items("Kira", pieces)
        check("retexture record", out, {"intended": both, "effective": both, "warnings": [],
                                        "mode": base_body.RETEXTURE_MODE, "unpainted": both, "missing": {}})
        check("run_queued: both grafted kinds", QUEUED, [both])
        profile = get_character_profile("Kira")
        profile["outfit_body_mode"] = base_body.MESH_MODE
        check("mesh mode on", save_character_profile("Kira", profile), True)
        out = base_body.resolve_mesh_items("Kira", pieces)
        check("mesh record", out, {"intended": both, "effective": both, "warnings": [],
                                   "mode": base_body.MESH_MODE, "unpainted": both, "missing": {}})
        painted = {"mesh_items": {"intended": both, "effective": [dress]}, "base_signature": kira_bsig}
        check("mesh_items_ready painted heels", base_body.mesh_items_ready("Kira", painted, base_sha=sha), [heels])
        left_out = {"mesh_items": {"intended": both, "effective": [dress], "unpainted": both,
                                   "missing": {heels: "other"}}, "base_signature": kira_bsig}
        check("mesh_items_missing", base_body.mesh_items_missing("Kira", left_out, base_sha=sha), [])
        profile = get_character_profile("Kira")
        profile["outfit_body_mode"] = base_body.RETEXTURE_MODE
        check("retexture mode on", save_character_profile("Kira", profile), True)
        check("off rule: painted heels", base_body.mesh_items_off_rule("Kira", painted, base_sha=sha), [heels])
        check("off rule: left out", base_body.mesh_items_off_rule("Kira", left_out, base_sha=sha), [])

        print("[K5] footwear runs the shoe chain, never the clothing chain")
        from app.core import garment_footwear, garment_images, garment_refit
        garments.run_queued = real_run_queued
        F = gs.garment_fsig("Kira", heels)
        R = {"ok": True, "fsig": F, "ran": [], "fit": "pending"}
        CHAIN, CLOTHING = [], []

        def chain_recorder(character_name, item, wanted, force):
            CHAIN.append((character_name, item["id"], wanted, force))
            return dict(R)
        real_chain = garment_footwear.run_chain
        garment_footwear.run_chain = chain_recorder
        saved = (garments._fit, garment_images.run_edit_step, garment_images.cut_out, garment_mesh.generate)
        garments._fit = lambda name, item_id, *a, **k: CLOTHING.append(("fit", item_id))
        garment_images.run_edit_step = lambda name, item_id, *a, **k: CLOTHING.append(("edit", item_id))
        garment_images.cut_out = lambda name, item_id, *a, **k: CLOTHING.append(("cutout", item_id))
        garment_mesh.generate = lambda name, item_id, *a, **k: CLOTHING.append(("mesh", item_id))
        try:
            started = {"started": True, "queued": False, "position": 0, "behind": None}
            check("run_garment", garments.run_garment("Kira", heels), R)
            check("run_garment forced mesh", garments.run_garment("Kira", heels, steps="mesh", force=True), R)
            check("chain calls", CHAIN, [("Kira", heels, None, False), ("Kira", heels, ["mesh"], True)])
            CHAIN.clear()
            check("start_garment", garments.start_garment("Kira", heels), started)
            check("idle 1", garments.wait_idle(10), True)
            check("start_garment forced empty", garments.start_garment("Kira", heels, steps="empty", force=True),
                  started)
            check("idle 2", garments.wait_idle(10), True)
            check("start chain calls", CHAIN, [("Kira", heels, None, False), ("Kira", heels, ["empty"], True)])
            raises("start_garment with a view", lambda: garments.start_garment("Kira", heels, view="front"),
                   ValueError, "no views")
            CHAIN.clear()
            job = garments.enqueue_garment("Kira", heels)
            check("enqueue_garment done", (job.done.wait(10), job.result), (True, R))
            check("run_queued", garments.run_queued("Kira", [heels]), {heels: R})
            from app.routes.characters import GarmentRunRequest, run_character_garment
            check("run route", run_character_garment("Kira", heels, GarmentRunRequest(), {}), started)
            check("idle 3", garments.wait_idle(10), True)
            check("queue chain calls", CHAIN, [("Kira", heels, None, False)] * 3)
            check("no clothing chain for heels", [c for c in CLOTHING if c[1] == heels], [])
        finally:
            garment_footwear.run_chain = real_chain
            garments._fit, garment_images.run_edit_step, garment_images.cut_out, garment_mesh.generate = saved
        ENQUEUED = []
        real_enqueue = garments.enqueue_garment
        real_ensure_hair = garments._ensure_hair

        def recording_enqueue(character_name, item_id):
            ENQUEUED.append(item_id)
            done = garments._Job(item_id, None, None, False)
            done.result = {"ok": True, "ran": []}
            done.done.set()
            return done
        garments.enqueue_garment = recording_enqueue
        garments._ensure_hair = lambda name, profile: False
        try:
            garments.after_base_model("Kira")
        finally:
            garments.enqueue_garment = real_enqueue
            garments._ensure_hair = real_ensure_hair
        check("after_base_model enqueues (footwear too since Task 25: fit-only, its item steps cached)", ENQUEUED, [dress, heels])
        old_fit = gs.garment_path("Kira", heels, "0123456789ab", "fit")
        old_fit.write_bytes(b"clothing-era fit of the heels")
        gs.write_record(old_fit.with_suffix(".json"), {
            "accepted": True, "kind": "clothing", "item_id": heels, "fsig": "0123456789ab",
            "base_signature": kira_bsig, "base_model_sha256": sha, "fit_version": 6})
        old_failed = gs.garment_path("Kira", heels, "0123456789cd", "failed")
        old_failed.parent.mkdir(parents=True, exist_ok=True)
        gs.write_record(old_failed, {"step": "fit", "error": "fit — the garment is too small; x",
                                     "base_model_sha256": sha, "fsig": "0123456789cd"})
        check("outdated_fits: no heels", [g for g in garment_refit.outdated_fits("Kira") if g[0] == heels], [])
        check("refused_fits: no heels", [g for g in garment_refit.refused_fits("Kira") if g[0] == heels], [])
        FITS = []
        real_fit = garments._fit
        garments._fit = lambda name, item_id, *a, **k: FITS.append(item_id)
        try:
            garment_refit.refit_character("Kira")
        finally:
            garments._fit = real_fit
        check("refit sweep fits no heels", [i for i in FITS if i == heels], [])
        check("wait idle", garments.wait_idle(10.0), True)
        check("queue empty", garments.queue_state("Kira"), {"queue_running": None, "queue": []})
        check("no running step", gs.status("Kira", heels).get("running_step"), None)
        check("no cached failure", garments.cached_failure("Kira", heels), None)
        current = gs.garment_fsig("Kira", heels)
        check("no failed record", gs.garment_path("Kira", heels, current, "failed").exists(), False)

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
