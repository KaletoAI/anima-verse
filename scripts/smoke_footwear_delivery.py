#!/usr/bin/env python3
"""Footwear, task 16: the delivery rule — footwear is never painted, missing
without a fit, in BOTH outfit body modes (plan
``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md`` Task 16; spec
``docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md`` § 9.1,
§ 12; the Task 10 carry: R11 for an older footwear fit version).

Usage:
    ./.venv/bin/python scripts/smoke_footwear_delivery.py

Runs against a THROWAWAY storage directory with a copy of the repo's ``human``
package — no real world, no hub, no GPU, no server. Synthetic bytes only.
Stubs: ``garments.run_queued`` (records its item ids; answers per item what
the test sets, default ok), ``garment_assembly.schedule`` and
``model_refs.trigger_now`` (recorders), ``model_refs.schedule_outfit_render``
(no-op). Every expectation is derived by hand below from the spec.

Fixture: ``Kira`` (human-roleplay, female, 168 cm, on the base-body pipeline,
retexture mode by default). Items: ``heels`` (slots [feet], own_mesh true,
prompt "plain heels", item image = 64 fixed bytes), ``dress`` ([top], own_mesh
true, "plain dress"), ``skirt`` ([bottom], no flag, "plain skirt"). Kira holds
and wears all three. Base model model3d/<bsig>.glb = b"model-2", SHA = its
sha256. Fits are written by hand: an accepted record of the item's CURRENT
fsig on SHA (dress: kind clothing, fit_version FIT_VERSION["clothing"]; heels:
kind footwear, method shoe, fit_version 4).
R(x) = base_body.MESH_ITEM_NOT_READY.format(item=x's name, reason=...),
P(x) = MESH_ITEM_PAINTED.format(...), NMF = NO_MESH_FIT.

[D1] Retexture, footwear without a fit (no fits at all yet).
     pieces {feet: heels, bottom: skirt}: resolve_mesh_items == {intended
     [heels], effective [], warnings [] (no MESH_ITEM_PAINTED), mode
     "retexture", unpainted [heels], missing {heels: NMF}}; run_queued was
     asked for [heels] (the shoe chain is part of the outfit build, spec
     § 12). dress_text(front, mesh_items=unpainted) names the skirt and not
     the heels ("plain skirt" in, "plain heels" out).
     Without a base model (model file removed): missing {heels:
     BASE_MODEL_MISSING}. A failed shoe chain (run_queued answers {ok False,
     step "fit", error "fit refused — x"}): missing {heels:
     MESH_ITEM_CHAIN_FAILED.format(step="fit", error="fit refused — x")},
     warnings [] still.
[D2] Off-rule (spec § 12: one rebuild, once). An OLD retexture record that
     painted the heels ({intended [heels], effective [], warnings [P(heels)]},
     no unpainted/mode): mesh_items_mode == "retexture",
     mesh_items_unpainted == [], mesh_items_off_rule == [heels]. The NEW
     record of [D1]: off_rule == [] (stable: no rebuild loop),
     mesh_items_missing == [(heels, NMF)], _mesh_warnings == [R(heels, NMF)],
     mesh_items_unpainted == [heels]. mesh_items_mode: {unpainted: []}
     without mode -> "mesh" (only mesh-mode records carried the key),
     {} -> "retexture", explicit mode wins over the key.
[D3] Retexture record with a clothing piece painted AND footwear missing.
     pieces {top: dress, feet: heels, bottom: skirt}, no fits: resolve ==
     {intended [dress, heels], effective [], warnings [P(dress, NMF)], mode
     retexture, unpainted [heels], missing {heels: NMF}}. Of that record:
     off_rule == [] in retexture mode; _mesh_warnings == [P(dress, NMF),
     R(heels, NMF)] (1 painted + 1 not-ready); mesh_items_ready == [] (no
     dress fit). Switched to mesh mode the same record is off-rule [dress]
     (painted belongs unpainted there), never [heels].
[D4] Mesh mode (profile outfit_body_mode "mesh"), dress fitted, heels not:
     resolve == {intended [dress, heels], effective [dress], warnings
     [R(heels, NMF)], mode "mesh", unpainted [dress, heels], missing {heels:
     NMF}} — unchanged from the ruling of 2026-11-10 (smoke_garment_outfit.py
     covers the rest). mesh_items_missing of it == [(heels, NMF)]. Back in
     retexture mode: resolve == {…, effective [dress], warnings [], mode
     retexture, unpainted [dress, heels], missing {heels: NMF}}; the [D3]
     record is now mesh_items_ready == [dress] (MESH_ITEM_READY) and
     off_rule == [] (the dress has its fit; the heels are not painted in it).
[D5] Flag off (Review Focus 4): heels own_mesh False -> garment_kind_of None,
     resolve_mesh_items({feet: heels, bottom: skirt}) == {} (not intended),
     mesh_items_token == "" and dress_text names the heels ("plain heels" in:
     an ordinary painted piece). Flag back on afterwards.
[D6] after_mesh_item_ready for footwear in retexture mode. The current
     outfit model model3d/<sig>.glb (sig = current_outfit_state(Kira)[2])
     with a sidecar whose mesh_items left the heels out ({intended [dress,
     heels], effective [dress], unpainted [dress, heels], missing {heels:
     NMF}, mode retexture}, outfit_body_mode retexture) -> True, schedule
     called once with (Kira, sig), trigger_now NOT called. For the dress
     (clothing, left out in that record too): neither (False, nothing called —
     retexture mode, nothing painted). A sidecar that painted the dress
     ({intended [dress, heels], effective [], unpainted [heels], …}) ->
     after_mesh_item_ready(dress) == True with trigger_now called (tpose) and
     schedule not called (the existing rebuild path).
[D7] R11 carry (Task 10): the heels' current fsig has no fit; an accepted
     footwear record under another fsig "0123456789ab" (kind footwear, method
     shoe, SHA, fit_version 3) -> accepted_fit(Kira, heels, SHA) is None and
     newest_accepted_fits(..., base_model_sha=SHA) has no "shoe" entry; a
     record of fit_version 4 under that fsig -> served (the fallback itself
     stays). The dress's fallback is untouched: its current-fsig fit removed,
     an accepted clothing record under "0123456789cd" (fit_version
     FIT_VERSION["clothing"], SHA) is served. resolve with the version-2 heels
     record only: heels missing NMF (never effective).
[D8] Wardrobe status (piece_status via the route and garment_set.wardrobe).
     Heels worn without a fit, retexture mode: status {state "missing",
     painted False, missing True, reason NMF}; mesh mode: the same.
     piece_status of a footwear info with an accepted fit (hand-made: the
     route's fit status needs the shoe source on disk): {state "fitted",
     painted False, missing False, reason None}; with the current-fsig fit
     written, resolve puts the heels into effective and unpainted, missing
     {}. The route's limits.fit has the five fit gates AND
     the three cut gates: deep_outside {le 0.02}, visible_poke {le 0.005},
     throat_ledge_p95_mm {le 4.0}, toe_conform_m {le 0.025}.
[D9] run_garment asks after_mesh_item_ready for footwear (GRAFTED_PIECE_KINDS
     == ("clothing", "footwear")): garment_footwear.run_chain stubbed to
     {ok True, fsig F, ran ["fit"], fit "accepted"} -> after_mesh_item_ready
     (recorder) called with (Kira, heels); with ran [] -> not called.
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


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="footwear-delivery-") as tmp:
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

        from app.core import base_body, garment_assembly, garment_fit, garment_set, garments, model_refs
        from app.core import garment_store as gs
        from app.models import inventory
        from app.models.character import get_character_dir, get_character_profile, save_character_profile

        model_refs.schedule_outfit_render = lambda *a, **k: None
        SCHEDULED, TRIGGERED, QUEUED = [], [], []
        garment_assembly.schedule = lambda name, signature=None: SCHEDULED.append((name, signature)) or True
        model_refs.trigger_now = lambda name, **k: TRIGGERED.append((name, k.get("kinds")))
        ANSWERS = {}

        def run_queued(character_name, item_ids):
            ids = list(item_ids)
            QUEUED.append(ids)
            return {i: dict(ANSWERS.get(i) or {"ok": True, "ran": []}) for i in ids}
        garments.run_queued = run_queued

        check("create Kira", save_character_profile("Kira", {
            "template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
            "body_slots": {"hair": {"length": "medium", "color": "blonde"}}}, create_new=True), True)
        check("pipeline Kira", base_body.set_pipeline("Kira", True), True)

        def piece(name, slots, own_mesh=None):
            op = {"slots": slots, "outfit_types": ["casual"]}
            if own_mesh is not None:
                op["own_mesh"] = own_mesh
            return inventory.add_item(name=name, category="outfit_piece", prompt_fragment=f"plain {name.lower()}",
                                      outfit_piece=op)["id"]

        heels = piece("Heels", ["feet"], True)
        dress = piece("Dress", ["top"], True)
        skirt = piece("Skirt", ["bottom"])
        item_dir = inventory._get_item_dir(heels, create=True)
        (item_dir / "image.png").write_bytes(bytes(range(64)))
        check("item image set", inventory.set_item_image(heels, "image.png"), True)
        for item in (heels, dress, skirt):
            check(f"Kira holds {item}", inventory.add_to_inventory("Kira", item), True)
            check(f"Kira wears {item}", inventory.equip_piece("Kira", item, source="smoke")["status"], "ok")

        def set_mode(mode):
            profile = get_character_profile("Kira")
            profile["outfit_body_mode"] = mode
            check(f"mode {mode}", save_character_profile("Kira", profile), True)

        def flag(item_id, on):
            item = inventory.get_item(item_id)
            op = dict(item.get("outfit_piece") or {})
            op["own_mesh"] = on
            inventory.update_item(item_id, {"outfit_piece": op})

        bsig = base_body.base_signature("Kira")
        refs = get_character_dir("Kira") / "model_refs"
        refs.mkdir(parents=True, exist_ok=True)
        (refs / f"tpose_{bsig}.png").write_bytes(b"front view of Kira")
        (refs / f"tpose_back_{bsig}.png").write_bytes(b"back view of Kira")
        model_dir = get_character_dir("Kira") / "model3d"
        model_dir.mkdir(parents=True, exist_ok=True)
        model = model_dir / f"{bsig}.glb"
        model.write_bytes(b"model-2")
        sha = hashlib.sha256(b"model-2").hexdigest()
        check("base sha", base_body.base_model_sha256("Kira", bsig), sha)

        def write_fit(item_id, kind, fsig=None, version=None, method=None):
            f = fsig or gs.garment_fsig("Kira", item_id)
            fit = gs.garment_path("Kira", item_id, f, "fit")
            fit.parent.mkdir(parents=True, exist_ok=True)
            fit.write_bytes(b"fit " + item_id.encode() + f.encode())
            record = {"accepted": True, "kind": kind, "item_id": item_id, "fsig": f, "base_signature": bsig,
                      "base_model_sha256": sha,
                      "fit_version": garment_fit.FIT_VERSION[kind] if version is None else version}
            if method or kind == "footwear":
                record["method"] = method or "shoe"
            gs.write_record(fit.with_suffix(".json"), record)
            return fit

        def drop_fit(item_id, fsig=None):
            f = fsig or gs.garment_fsig("Kira", item_id)
            fit = gs.garment_path("Kira", item_id, f, "fit")
            fit.unlink(missing_ok=True)
            fit.with_suffix(".json").unlink(missing_ok=True)

        NMF = base_body.NO_MESH_FIT
        BMM = base_body.BASE_MODEL_MISSING
        RET, MESH = base_body.RETEXTURE_MODE, base_body.MESH_MODE

        def R(name, reason):
            return base_body.MESH_ITEM_NOT_READY.format(item=name, reason=reason)

        def P(name, reason):
            return base_body.MESH_ITEM_PAINTED.format(item=name, reason=reason)

        print("[D1] retexture: footwear without a fit is missing, never painted")
        check("GRAFTED_PIECE_KINDS", garment_set.GRAFTED_PIECE_KINDS, ("clothing", "footwear"))
        check("no FOOTWEAR_PREVIEW_ONLY", hasattr(base_body, "FOOTWEAR_PREVIEW_ONLY"), False)
        feet = {"feet": heels, "bottom": skirt}
        QUEUED.clear()
        d1 = base_body.resolve_mesh_items("Kira", feet)
        check("D1 record", d1, {"intended": [heels], "effective": [], "warnings": [], "mode": RET,
                                "unpainted": [heels], "missing": {heels: NMF}})
        check("D1 run_queued asked for the shoe chain", QUEUED, [[heels]])
        text = base_body.dress_text("Kira", "front", pieces=feet, items=[],
                                    mesh_items=base_body.mesh_items_unpainted({"mesh_items": d1}))
        check("D1 dress text", ("plain skirt" in text, "plain heels" in text), (True, False))
        model.unlink()
        check("D1 no base model", base_body.resolve_mesh_items("Kira", feet).get("missing"), {heels: BMM})
        model.write_bytes(b"model-2")
        ANSWERS[heels] = {"ok": False, "fsig": "x", "step": "fit", "error": "fit refused — x"}
        failed = base_body.resolve_mesh_items("Kira", feet)
        check("D1 failed chain", (failed.get("missing"), failed.get("warnings")),
              ({heels: base_body.MESH_ITEM_CHAIN_FAILED.format(step="fit", error="fit refused — x")}, []))
        ANSWERS.clear()

        print("[D2] an old record that painted the heels is off-rule once; the new one is stable")
        old = {"mesh_items": {"intended": [heels], "effective": [], "warnings": [P("Heels", NMF)]},
               "base_signature": bsig}
        check("D2 old mode", base_body.mesh_items_mode(old), RET)
        check("D2 old unpainted", base_body.mesh_items_unpainted(old), [])
        check("D2 old off-rule", base_body.mesh_items_off_rule("Kira", old, base_sha=sha), [heels])
        new = {"mesh_items": d1, "base_signature": bsig}
        check("D2 new off-rule", base_body.mesh_items_off_rule("Kira", new, base_sha=sha), [])
        check("D2 new missing", base_body.mesh_items_missing("Kira", new, base_sha=sha), [(heels, NMF)])
        check("D2 new warnings", base_body._mesh_warnings("Kira", new, sha), [R("Heels", NMF)])
        check("D2 new unpainted", base_body.mesh_items_unpainted(new), [heels])
        check("D2 mode: unpainted key alone", base_body.mesh_items_mode({"mesh_items": {"unpainted": []}}), MESH)
        check("D2 mode: no record", base_body.mesh_items_mode({}), RET)
        check("D2 mode: explicit wins",
              base_body.mesh_items_mode({"mesh_items": {"unpainted": [], "mode": RET}}), RET)

        print("[D3] a clothing piece painted and the footwear missing in one retexture record")
        full = {"top": dress, "feet": heels, "bottom": skirt}
        d3 = base_body.resolve_mesh_items("Kira", full)
        check("D3 record", d3, {"intended": sorted([dress, heels]), "effective": [], "warnings": [P("Dress", NMF)],
                                "mode": RET, "unpainted": [heels], "missing": {heels: NMF}})
        rec3 = {"mesh_items": d3, "base_signature": bsig}
        check("D3 off-rule (retexture)", base_body.mesh_items_off_rule("Kira", rec3, base_sha=sha), [])
        check("D3 warnings", base_body._mesh_warnings("Kira", rec3, sha), [P("Dress", NMF), R("Heels", NMF)])
        check("D3 ready", base_body.mesh_items_ready("Kira", rec3, base_sha=sha), [])
        set_mode(MESH)
        check("D3 off-rule (mesh mode)", base_body.mesh_items_off_rule("Kira", rec3, base_sha=sha), [dress])
        set_mode(RET)

        print("[D4] mesh mode unchanged; the dress fitted")
        write_fit(dress, "clothing")
        set_mode(MESH)
        d4 = base_body.resolve_mesh_items("Kira", full)
        check("D4 mesh record", d4, {"intended": sorted([dress, heels]), "effective": [dress],
                                     "warnings": [R("Heels", NMF)], "mode": MESH,
                                     "unpainted": sorted([dress, heels]), "missing": {heels: NMF}})
        check("D4 mesh missing", base_body.mesh_items_missing("Kira", {"mesh_items": d4, "base_signature": bsig},
                                                              base_sha=sha), [(heels, NMF)])
        set_mode(RET)
        d4r = base_body.resolve_mesh_items("Kira", full)
        check("D4 retexture record", d4r, {"intended": sorted([dress, heels]), "effective": [dress],
                                           "warnings": [], "mode": RET, "unpainted": sorted([dress, heels]),
                                           "missing": {heels: NMF}})
        check("D4 D3 record ready now", base_body.mesh_items_ready("Kira", rec3, base_sha=sha), [dress])
        check("D4 D3 record off-rule", base_body.mesh_items_off_rule("Kira", rec3, base_sha=sha), [])

        print("[D5] flag off: an ordinary painted piece")
        flag(heels, False)
        check("D5 kind", garment_set.garment_kind_of(inventory.get_item(heels)), None)
        check("D5 not intended", base_body.resolve_mesh_items("Kira", feet), {})
        check("D5 token", model_refs.mesh_items_token("Kira", pieces=feet), "")
        check("D5 painted", "plain heels" in base_body.dress_text("Kira", "front", pieces=feet, items=[]), True)
        flag(heels, True)
        check("D5 flag back on", garment_set.garment_kind_of(inventory.get_item(heels)), "footwear")

        print("[D6] after_mesh_item_ready: footwear is only assembled, in retexture mode too")
        sig = model_refs.current_outfit_state("Kira")[2]
        outfit_model = model_dir / f"{sig}.glb"
        outfit_model.write_bytes(b"outfit model")

        def sidecar(mesh_items):
            outfit_model.with_suffix(".json").write_text(json.dumps({
                "character": "Kira", "base_signature": bsig, "base_model_sha256": sha,
                "outfit_body_mode": RET, "mesh_items": mesh_items}))
        sidecar({"intended": sorted([dress, heels]), "effective": [dress], "unpainted": sorted([dress, heels]),
                 "missing": {heels: NMF}, "mode": RET, "warnings": []})
        SCHEDULED.clear()
        TRIGGERED.clear()
        check("D6 footwear -> True", base_body.after_mesh_item_ready("Kira", heels), True)
        check("D6 schedule called", SCHEDULED, [("Kira", sig)])
        check("D6 trigger_now not called", TRIGGERED, [])
        SCHEDULED.clear()
        check("D6 dress left out -> False", base_body.after_mesh_item_ready("Kira", dress), False)
        check("D6 dress: nothing called", (SCHEDULED, TRIGGERED), ([], []))
        sidecar({"intended": sorted([dress, heels]), "effective": [], "unpainted": [heels],
                 "missing": {heels: NMF}, "mode": RET, "warnings": [P("Dress", NMF)]})
        check("D6 painted dress -> True", base_body.after_mesh_item_ready("Kira", dress), True)
        check("D6 painted dress: rebuild", (SCHEDULED, TRIGGERED), ([], [("Kira", ("tpose",))]))
        TRIGGERED.clear()
        outfit_model.unlink()
        outfit_model.with_suffix(".json").unlink()

        print("[D7] R11: an older footwear fit version is never served")
        old_fsig = "0123456789ab"
        write_fit(heels, "footwear", fsig=old_fsig, version=3)
        check("D7 FIT_VERSION footwear", garment_fit.FIT_VERSION["footwear"], 4)
        check("D7 version 3 not served", gs.accepted_fit("Kira", heels, base_model_sha=sha), None)
        check("D7 newest: no shoe", "shoe" in gs.newest_accepted_fits("Kira", heels, base_model_sha=sha), False)
        d7 = base_body.resolve_mesh_items("Kira", full)
        check("D7 heels missing", (d7.get("effective"), d7.get("missing")), ([dress], {heels: NMF}))
        write_fit(heels, "footwear", fsig=old_fsig, version=4)
        served = gs.accepted_fit("Kira", heels, base_model_sha=sha)
        check("D7 version 4 served (fallback)", served and gs.parse_name(served[0])[1], old_fsig)
        drop_fit(heels, old_fsig)
        drop_fit(dress)
        write_fit(dress, "clothing", fsig="0123456789cd")
        served = gs.accepted_fit("Kira", dress, base_model_sha=sha)
        check("D7 clothing fallback untouched", served and gs.parse_name(served[0])[1], "0123456789cd")
        drop_fit(dress, "0123456789cd")
        write_fit(dress, "clothing")

        print("[D8] Wardrobe status: missing in either mode, never painted; the cut gates have limits")
        from app.routes.characters import get_character_garment

        def status():
            body = get_character_garment("Kira", heels, {})
            st = body["status"]
            return ({k: st.get(k) for k in ("state", "painted", "missing", "reason")}, body["limits"])
        st, limits = status()
        check("D8 retexture unfitted", st, {"state": "missing", "painted": False, "missing": True, "reason": NMF})
        check("D8 wardrobe unfitted", {k: garment_set.wardrobe("Kira")["items"][heels].get(k)
                                       for k in ("painted", "missing")}, {"painted": False, "missing": True})
        set_mode(MESH)
        check("D8 mesh unfitted", status()[0], {"state": "missing", "painted": False, "missing": True,
                                                "reason": NMF})
        set_mode(RET)
        check("D8 cut gate limits", {k: limits["fit"].get(k)
                                     for k in ("deep_outside", "visible_poke", "throat_ledge_p95_mm", "toe_conform_m")},
              {"deep_outside": {"op": "le", "value": 0.02}, "visible_poke": {"op": "le", "value": 0.005},
               "throat_ledge_p95_mm": {"op": "le", "value": 4.0}, "toe_conform_m": {"op": "le", "value": 0.025}})
        check("D8 fit gate limits kept", sorted(limits["fit"]),
              sorted(["ball_placement_mm", "lift_asymmetry_mm", "slim_needed", "stand_floor_mm", "boot",
                      "deep_outside", "visible_poke", "throat_ledge_p95_mm", "toe_conform_m"]))
        fitted = {k: v for k, v in garment_set.piece_status(
            {"kind": "footwear", "fsig": "f", "steps": {"fit": {"status": "accepted"}}}, worn=True,
            base_model_ready=True).items() if k in ("state", "painted", "missing", "reason")}
        check("D8 fitted", fitted, {"state": "fitted", "painted": False, "missing": False, "reason": None})
        write_fit(heels, "footwear")
        d8 = base_body.resolve_mesh_items("Kira", full)
        check("D8 fitted record", (d8.get("effective"), d8.get("unpainted"), d8.get("missing")),
              (sorted([dress, heels]), sorted([dress, heels]), {}))
        drop_fit(heels)

        print("[D9] run_garment asks after_mesh_item_ready for footwear")
        from app.core import garment_footwear
        F = gs.garment_fsig("Kira", heels)
        HOOK = []
        real_chain, real_hook = garment_footwear.run_chain, base_body.after_mesh_item_ready
        base_body.after_mesh_item_ready = lambda name, item_id: HOOK.append((name, item_id)) or True
        try:
            garment_footwear.run_chain = lambda n, item, w, f: {"ok": True, "fsig": F, "ran": ["fit"],
                                                                "fit": "accepted"}
            check("D9 run ok", garments.run_garment("Kira", heels).get("ok"), True)
            check("D9 hook called", HOOK, [("Kira", heels)])
            garment_footwear.run_chain = lambda n, item, w, f: {"ok": True, "fsig": F, "ran": [],
                                                                "fit": "accepted"}
            garments.run_garment("Kira", heels)
            check("D9 hook not called without a fit run", HOOK, [("Kira", heels)])
        finally:
            garment_footwear.run_chain, base_body.after_mesh_item_ready = real_chain, real_hook
        check("wait idle", garments.wait_idle(10.0), True)

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
