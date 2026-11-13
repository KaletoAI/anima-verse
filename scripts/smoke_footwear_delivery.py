#!/usr/bin/env python3
"""Footwear, task 16: the delivery rule — footwear is never painted, missing
without a fit, whether a piece is in the body or not (plan
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
retexture mode by default). Items: ``heels`` (slots [feet], mode own_mesh,
prompt "plain heels", item image = 64 fixed bytes), ``dress`` ([top], own_mesh,
"plain dress"), ``skirt`` ([bottom], painted, "plain skirt"). Kira holds
and wears all three. The outfit body mode follows the worn pieces (interim
rule of plan 2026-11-12-unified-worn-pieces Task 2): "mesh mode" below = the
skirt switched to mode in_body, "retexture mode" = the skirt painted. Base model model3d/<bsig>.glb = b"model-2", SHA = its
sha256. Fits are written by hand: an accepted record of the item's CURRENT
fsig on SHA (dress: kind clothing, fit_version FIT_VERSION["clothing"]; heels:
kind footwear, method shoe, fit_version 9).
Task 6 of plan 2026-11-12-unified-worn-pieces: ``resolve_figure`` replaced
``resolve_mesh_items`` (its record compared without ``figure``, which
replaced ``mode``); "mesh mode" / "retexture mode" are the skirt's item mode
in_body / painted, checked on the wanted figure; no shape is built here, so
the delivered figure stays on the plain body with the skirt painted
meanwhile. off(record) = what the figure delivered now leaves unpainted
(own + left out) that the record painted — replaces ``mesh_items_off_rule``;
``mesh_items_mode`` is gone with the mode.
R(x) = base_body.MESH_ITEM_NOT_READY.format(item=x's name, reason=...),
IB(x) = MESH_ITEM_IN_BODY.format(...), NMF = NO_MESH_FIT.

Task 11c-2 of plan 2026-11-12-unified-worn-pieces (rulings A11 / A14): an
own-mesh piece without its mesh — footwear included — is IN THE BODY shape
meanwhile (record ``in_body``, a warning IB naming why it has no mesh),
never painted and never left out; ``resolve_figure`` runs no garment chain
(was: run_queued asked for the shoe chain; footwear left out with
``missing``; clothing painted with ``MESH_ITEM_PAINTED``).

[D1] Retexture, footwear without a fit (no fits at all yet).
     pieces {feet: heels, bottom: skirt}: resolve == {intended [],
     effective [], warnings [IB(heels, NMF)], unpainted [], missing {},
     in_body [heels]}; run_queued NOT asked. The delivered figure's dress
     text (``figure_texts``) names the skirt AND the heels (in the body).
     Without a base model (model file removed): warnings [IB(heels,
     BASE_MODEL_MISSING)]. A refused shoe chain (``garments.cached_failure``
     {step "fit", error "fit refused — x"}): warnings [IB(heels,
     MESH_ITEM_CHAIN_FAILED.format(step="fit", error="fit refused — x"))],
     still in_body [heels], missing {}.
[D2] Off-rule (spec § 12: one rebuild, once). An OLD retexture record that
     painted the heels ({intended [heels], effective [], warnings ["Heels
     stays painted on: …"]}, no unpainted): mesh_items_unpainted == [], off
     == [] (the heels are in the body now, nothing is unpainted). The NEW
     record of [D1]: off == [] (stable: no rebuild loop),
     mesh_items_missing == [], _mesh_warnings == [IB(heels, NMF)],
     mesh_items_unpainted == [], mesh_items_in_body == [heels].
     mesh_items_unpainted of {unpainted: []} and of {} == [] (the three
     mesh_items_mode cases went with the mode).
[D3] Pieces {top: dress, feet: heels, bottom: skirt}, no fits: resolve ==
     {intended [], effective [], warnings [IB(dress, NMF), IB(heels, NMF)],
     unpainted [], missing {}, in_body [dress, heels]}. Of that record: off
     == []; _mesh_warnings == the two IB; mesh_items_ready == []. The skirt
     in the body: off == [] still.
[D4] The skirt in the body, dress fitted, heels not: resolve ==
     {intended [dress], effective [dress], warnings [IB(heels, NMF)],
     unpainted [dress], missing {}, in_body [heels]} (the dress grafted on
     the interim shape of {heels, skirt} — not stored yet, its base fit
     counts); mesh_items_missing of it == []. The skirt painted again: the
     same record (interim shape of {heels}); the [D3] record: mesh_items_ready
     == [] (it painted nothing) and off == [dress] (the dress has its fit: a
     view that kept it in the text is stale).
[D5] Own mesh off (Review Focus 4): heels painted -> garment_kind_of None,
     resolve({feet: heels, bottom: skirt}) == {} (not intended),
     mesh_items_token == "" and dress_text names the heels ("plain heels" in:
     an ordinary painted piece). Own mesh again afterwards.
[D6] after_mesh_item_ready for footwear, the skirt painted. The current
     outfit model model3d/<sig>.glb (sig = current_outfit_state(Kira)[2])
     with a sidecar that left the heels out ({intended [dress, heels],
     effective [dress], unpainted [dress, heels], missing {heels: NMF}}) and
     records the figure delivered then (dress grafted, heels in the body:
     ruling A11 — that model's shape is stored, ``figure.stored_shape`` is
     stubbed to answer for the shape a model sidecar names, and
     ``garments.body_fit`` to carry every base fit onto it); the heels' fit
     written (the one the hook reports) -> True: the hook asks the Build
     ("piece_ready", ``figure_build.request`` recorded — Task 8 of plan
     2026-11-12-unified-worn-pieces; was: it scheduled the assembly itself)
     and calls neither schedule nor trigger_now; the Build's plan needs no
     new texture: the delivered figure KEEPS the model's shape (ruling A11:
     out of the shape only on the next manual Build) with the same texture.
     For the dress (grafted on that model already): True, the Build asked,
     nothing called. A sidecar built while neither had a fit (both in the
     body), the dress fit back -> after_mesh_item_ready(dress) == True, the
     Build asked, and again the same shape and texture (was: the dress
     painted meanwhile, another texture — the Build's ``texture`` step
     rendered its views).
[D7] The heels' current fsig has no fit; an accepted footwear record under
     another fsig "0123456789ab" (kind footwear, method shoe, SHA, fit_version
     3, no body cut, no foot pose: from before both — the assembly could not
     graft it) -> accepted_fit(Kira, heels, SHA) is None and
     newest_accepted_fits(..., base_model_sha=SHA) has no "shoe" entry; a
     record of fit_version 17 (the current FOOTWEAR_FIT_VERSION) under that
     fsig -> served (the fallback itself stays).
     Ruling R7b (plan 2026-11-12 fit-sdf-speed-drape, replaces the R11 carry
     "an older version is never served"): the same fsig with fit_version 16
     and its cut (``cut.sides`` non-empty) and ``foot_pose`` -> served
     (``garment_store.footwear_servable``), "shoe" in newest_accepted_fits,
     and resolve(full) makes the heels effective beside the dress (as D8's
     fitted record: effective [dress, heels], missing {}); a refusal recorded
     for the CURRENT fsig (the refit of version 17 refused) leaves it served.
     footwear_servable: ``cut.sides`` empty -> False; no ``foot_pose`` -> False. The dress's fallback is untouched: its current-fsig fit removed,
     an accepted clothing record under "0123456789cd" (fit_version
     FIT_VERSION["clothing"], SHA) is served. resolve with the version-3 heels
     record only: the heels never effective — in the body (ruling A11; was:
     missing NMF).
[D8] Wardrobe status (piece_status via the route and garment_set.wardrobe).
     Heels worn without a fit, the skirt painted: status {state "missing",
     painted False, in_body True, reason NMF} and no "missing" key (ruling
     A11: in the body until its mesh is ready; was missing True); the skirt
     in the body: the same.
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
        from app.core import figure
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile

        model_refs.schedule_outfit_render = lambda *a, **k: None
        SCHEDULED, TRIGGERED, QUEUED = [], [], []
        garment_assembly.schedule = lambda name, signature=None: SCHEDULED.append((name, signature)) or True
        model_refs.trigger_now = lambda name, **k: TRIGGERED.append((name, k.get("kinds")))
        # Task 8 (plan 2026-11-12-unified-worn-pieces): every hook is a Build request now — recorded.
        from _figure_build_fixtures import record_requests
        REQUESTS = record_requests()
        ANSWERS = {}

        def run_queued(character_name, item_ids):
            ids = list(item_ids)
            QUEUED.append(ids)
            return {i: dict(ANSWERS.get(i) or {"ok": True, "ran": []}) for i in ids}
        garments.run_queued = run_queued

        check("create Kira", save_character_profile("Kira", {
            "template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
            "body_slots": {"hair": {"length": "medium", "color": "blonde"}}}, create_new=True), True)

        def piece(name, slots, own_mesh=None):
            op = {"slots": slots, "outfit_types": ["casual"]}
            op["mesh_mode"] = "own_mesh" if own_mesh else "painted"
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
            """The skirt's item mode (Task 6 of plan 2026-11-12-unified-worn-pieces: the per-character outfit
            body mode is gone — the old "mesh mode" is the skirt in the body, "retexture" the skirt painted);
            checked on the wanted figure."""
            op = dict(inventory.get_item(skirt)["outfit_piece"])
            op["mesh_mode"] = mode
            inventory.update_item(skirt, {"outfit_piece": op})
            check(f"skirt {mode}", list(figure.wanted_figure("Kira").in_body), [skirt] if mode == MESH else [])

        def resolve(pieces):
            """``resolve_figure``'s record without its ``figure`` (Task 6 replaced the record's ``mode``)."""
            return {k: v for k, v in base_body.resolve_figure("Kira", pieces)[1].items() if k != "figure"}

        def off(meta, pieces):
            """What a record painted that the figure delivered NOW leaves unpainted — the pieces that make a
            view of it stale (``dressed_image``; replaces ``mesh_items_off_rule``)."""
            fig = figure.delivered_figure("Kira", pieces=dict(pieces), items=[])
            return sorted({*fig.own, *fig.left_out} - set(base_body.mesh_items_unpainted(meta)))

        def flag(item_id, on):
            item = inventory.get_item(item_id)
            op = dict(item.get("outfit_piece") or {})
            op["mesh_mode"] = "own_mesh" if on else "painted"
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

        def write_fit(item_id, kind, fsig=None, version=None, method=None, extra=None):
            f = fsig or gs.garment_fsig("Kira", item_id)
            fit = gs.garment_path("Kira", item_id, f, "fit")
            fit.parent.mkdir(parents=True, exist_ok=True)
            fit.write_bytes(b"fit " + item_id.encode() + f.encode())
            record = {"accepted": True, "kind": kind, "item_id": item_id, "fsig": f, "base_signature": bsig,
                      "base_model_sha256": sha,
                      "fit_version": garment_fit.FIT_VERSION[kind] if version is None else version}
            if method or kind == "footwear":
                record["method"] = method or "shoe"
            record.update(extra or {})
            gs.write_record(fit.with_suffix(".json"), record)
            return fit

        def drop_fit(item_id, fsig=None):
            f = fsig or gs.garment_fsig("Kira", item_id)
            fit = gs.garment_path("Kira", item_id, f, "fit")
            fit.unlink(missing_ok=True)
            fit.with_suffix(".json").unlink(missing_ok=True)

        NMF = base_body.NO_MESH_FIT
        BMM = base_body.BASE_MODEL_MISSING
        RET, MESH = "painted", "in_body"   # the skirt's item mode

        def R(name, reason):
            return base_body.MESH_ITEM_NOT_READY.format(item=name, reason=reason)

        def IB(name, reason):
            return base_body.MESH_ITEM_IN_BODY.format(item=name, reason=reason)

        print("[D1] retexture: footwear without a fit is in the body (ruling A11), never painted, no chain run")
        check("GRAFTED_PIECE_KINDS", garment_set.GRAFTED_PIECE_KINDS, ("clothing", "footwear"))
        check("no FOOTWEAR_PREVIEW_ONLY", hasattr(base_body, "FOOTWEAR_PREVIEW_ONLY"), False)
        feet = {"feet": heels, "bottom": skirt}
        QUEUED.clear()
        d1 = resolve(feet)
        check("D1 record", d1, {"intended": [], "effective": [], "warnings": [IB("Heels", NMF)],
                                "unpainted": [], "missing": {}, "in_body": [heels]})
        check("D1 run_queued not asked (ruling A14)", QUEUED, [])
        text = base_body.figure_texts("Kira", figure.delivered_figure("Kira", pieces=feet, items=[]), [])["front"]
        check("D1 dress text", ("plain skirt" in text, "plain heels" in text), (True, True))
        model.unlink()
        check("D1 no base model", resolve(feet).get("warnings"), [IB("Heels", BMM)])
        model.write_bytes(b"model-2")
        real_failure = garments.cached_failure
        garments.cached_failure = lambda _c, item_id, **_kw: ({"step": "fit", "error": "fit refused — x"}
                                                              if item_id == heels else None)
        failed = resolve(feet)
        garments.cached_failure = real_failure
        check("D1 refused chain", (failed.get("in_body"), failed.get("missing"), failed.get("warnings")),
              ([heels], {}, [IB("Heels", base_body.MESH_ITEM_CHAIN_FAILED.format(step="fit",
                                                                              error="fit refused — x"))]))

        print("[D2] an old record that painted the heels; the new one is stable")
        old = {"mesh_items": {"intended": [heels], "effective": [], "warnings": [f"Heels stays painted on: {NMF}"]},
               "base_signature": bsig}
        check("D2 old unpainted", base_body.mesh_items_unpainted(old), [])
        check("D2 old off-rule", off(old, feet), [])
        new = {"mesh_items": d1, "base_signature": bsig}
        check("D2 new off-rule", off(new, feet), [])
        check("D2 new missing", base_body.mesh_items_missing("Kira", new, base_sha=sha), [])
        check("D2 new warnings", base_body._mesh_warnings("Kira", new, sha), [IB("Heels", NMF)])
        check("D2 new unpainted / in body", (base_body.mesh_items_unpainted(new), base_body.mesh_items_in_body(new)),
              ([], [heels]))
        check("D2 unpainted: the key alone", base_body.mesh_items_unpainted({"mesh_items": {"unpainted": []}}), [])
        check("D2 unpainted: no record", base_body.mesh_items_unpainted({}), [])

        print("[D3] a clothing piece painted and the footwear missing in one retexture record")
        full = {"top": dress, "feet": heels, "bottom": skirt}
        d3 = resolve(full)
        both_ib = [IB(n, NMF) for _i, n in sorted([(dress, "Dress"), (heels, "Heels")])]
        check("D3 record", d3, {"intended": [], "effective": [], "warnings": both_ib, "unpainted": [], "missing": {},
                                "in_body": sorted([dress, heels])})
        rec3 = {"mesh_items": d3, "base_signature": bsig}
        check("D3 off-rule (skirt painted)", off(rec3, full), [])
        check("D3 warnings", base_body._mesh_warnings("Kira", rec3, sha), both_ib)
        check("D3 ready", base_body.mesh_items_ready("Kira", rec3, base_sha=sha), [])
        set_mode(MESH)
        check("D3 off-rule (skirt in the body, no shape built)", off(rec3, full), [])
        set_mode(RET)

        print("[D4] mesh mode unchanged; the dress fitted")
        write_fit(dress, "clothing")
        set_mode(MESH)
        d4 = resolve(full)
        d4_want = {"intended": [dress], "effective": [dress], "warnings": [IB("Heels", NMF)], "unpainted": [dress],
                   "missing": {}, "in_body": [heels]}
        check("D4 skirt-in-body record", d4, d4_want)
        check("D4 mesh missing", base_body.mesh_items_missing("Kira", {"mesh_items": d4, "base_signature": bsig},
                                                              base_sha=sha), [])
        set_mode(RET)
        d4r = resolve(full)
        check("D4 skirt-painted record", d4r, d4_want)
        check("D4 D3 record ready now: it painted nothing", base_body.mesh_items_ready("Kira", rec3, base_sha=sha),
              [])
        check("D4 D3 record off-rule: the dress", off(rec3, full), [dress])

        print("[D5] flag off: an ordinary painted piece")
        flag(heels, False)
        check("D5 kind", garment_set.garment_kind_of(inventory.get_item(heels)), None)
        check("D5 not intended", resolve(feet), {})
        check("D5 token", model_refs.mesh_items_token("Kira", pieces=feet), "")
        check("D5 painted", "plain heels" in base_body.dress_text("Kira", "front", pieces=feet, items=[]), True)
        flag(heels, True)
        check("D5 flag back on", garment_set.garment_kind_of(inventory.get_item(heels)), "footwear")

        print("[D6] after_mesh_item_ready: footwear is only assembled, in retexture mode too")
        sig = model_refs.current_outfit_state("Kira")[2]
        outfit_model = model_dir / f"{sig}.glb"
        outfit_model.write_bytes(b"outfit model")

        def sidecar(mesh_items):
            """The model as built NOW (its recorded figure = the one delivered at this moment)."""
            outfit_model.with_suffix(".json").write_text(json.dumps({
                "character": "Kira", "base_signature": bsig, "base_model_sha256": sha, "mesh_items": mesh_items,
                "figure": figure.delivered_figure("Kira").as_dict()}))
        real_stored_shape = figure.stored_shape

        def stored_shape(_c, key, **_kw):
            """The shape the current outfit model was built on is stored (the fixture writes no GLB of it)."""
            side = outfit_model.with_suffix(".json")
            built = figure.built_figure(json.loads(side.read_text())) if side.is_file() else None
            return {"outfit_body": {"body_id": key}} if built is not None and built.shape == key else None
        figure.stored_shape = stored_shape
        real_body_fit = garments.body_fit
        garments.body_fit = lambda _c, item_id, *, base_fit, **_kw: {"fit": base_fit[0], "pending": False, "error": ""}
        sidecar({"intended": [dress], "effective": [dress], "unpainted": [dress], "missing": {},
                 "in_body": [heels], "warnings": [IB("Heels", NMF)]})
        check("D6 the model's figure: heels in the body",
              figure.built_figure(json.loads(outfit_model.with_suffix(".json").read_text())).in_body_own, (heels,))
        write_fit(heels, "footwear")   # the fit the hook reports
        SCHEDULED.clear()
        TRIGGERED.clear()
        REQUESTS.clear()

        def same_shape_and_texture():
            """What the Build's ``texture`` step turns on besides missing views (``figure_build.plan``): the
            stored model built on the shape and texture the figure delivered now has (the fixture stores no
            views, so the plan itself would ask for them in every case)."""
            built = figure.built_figure(json.loads(outfit_model.with_suffix(".json").read_text()))
            now = figure.delivered_figure("Kira")
            return (built.shape, built.texture) == (now.shape, now.texture)
        check("D6 footwear -> True (the Build asked)", (base_body.after_mesh_item_ready("Kira", heels), REQUESTS),
              (True, [("Kira", "piece_ready")]))
        check("D6 the hook itself schedules nothing, no trigger_now", (SCHEDULED, TRIGGERED), ([], []))
        check("D6 same shape and texture: the Build only assembles", same_shape_and_texture(), True)
        REQUESTS.clear()
        check("D6 dress grafted on the model -> the Build asked",
              (base_body.after_mesh_item_ready("Kira", dress), REQUESTS), (True, [("Kira", "piece_ready")]))
        check("D6 dress: nothing called by the hook", (SCHEDULED, TRIGGERED), ([], []))
        REQUESTS.clear()
        drop_fit(heels)
        drop_fit(dress)
        sidecar({"intended": [], "effective": [], "unpainted": [], "missing": {}, "in_body": sorted([dress, heels]),
                 "warnings": []})
        write_fit(dress, "clothing")
        check("D6 in-body dress -> True (the Build asked)",
              (base_body.after_mesh_item_ready("Kira", dress), REQUESTS), (True, [("Kira", "piece_ready")]))
        check("D6 in-body dress: nothing called by the hook", (SCHEDULED, TRIGGERED), ([], []))
        check("D6 in-body dress: the shape kept, no view to render", same_shape_and_texture(), True)
        figure.stored_shape = real_stored_shape
        garments.body_fit = real_body_fit
        TRIGGERED.clear()
        outfit_model.unlink()
        outfit_model.with_suffix(".json").unlink()

        print("[D7] an older footwear fit without its cut is never served")
        old_fsig = "0123456789ab"
        write_fit(heels, "footwear", fsig=old_fsig, version=3)
        check("D7 FIT_VERSION footwear", garment_fit.FIT_VERSION["footwear"], 17)
        check("D7 version 3 not served", gs.accepted_fit("Kira", heels, base_model_sha=sha), None)
        check("D7 newest: no shoe", "shoe" in gs.newest_accepted_fits("Kira", heels, base_model_sha=sha), False)
        d7 = resolve(full)
        check("D7 heels in the body", (d7.get("effective"), d7.get("missing"), d7.get("in_body")),
              ([dress], {}, [heels]))
        write_fit(heels, "footwear", fsig=old_fsig, version=17)
        served = gs.accepted_fit("Kira", heels, base_model_sha=sha)
        check("D7 version 17 served (fallback)", served and gs.parse_name(served[0])[1], old_fsig)
        print("[D7b] R7b: an older footwear version with its cut stays served until its refit is accepted")
        graftable = {"cut": {"version": 7, "sides": {"left": {"cap": []}}}, "foot_pose": {"version": 1}}
        write_fit(heels, "footwear", fsig=old_fsig, version=16, extra=graftable)
        served = gs.accepted_fit("Kira", heels, base_model_sha=sha)
        check("D7b version 16 served", served and gs.parse_name(served[0])[1], old_fsig)
        check("D7b newest: the shoe", "shoe" in gs.newest_accepted_fits("Kira", heels, base_model_sha=sha), True)
        d7b = resolve(full)
        check("D7b heels effective", (d7b.get("effective"), d7b.get("missing")), (sorted([dress, heels]), {}))
        gs.record_failure("Kira", heels, gs.garment_fsig("Kira", heels), step="fit",
                          error="fit refused — visible_poke 0.02 > 0.005", base_model_sha=sha)
        served = gs.accepted_fit("Kira", heels, base_model_sha=sha)
        check("D7b refit refused: still served", served and gs.parse_name(served[0])[1], old_fsig)
        gs.clear_failure("Kira", heels, gs.garment_fsig("Kira", heels))
        check("D7b servable: no sides / no foot pose",
              (gs.footwear_servable({"accepted": True, "cut": {"sides": {}}, "foot_pose": {}}),
               gs.footwear_servable({"accepted": True, "cut": {"sides": {"left": {}}}})), (False, False))
        drop_fit(heels, old_fsig)
        drop_fit(dress)
        write_fit(dress, "clothing", fsig="0123456789cd")
        served = gs.accepted_fit("Kira", dress, base_model_sha=sha)
        check("D7 clothing fallback untouched", served and gs.parse_name(served[0])[1], "0123456789cd")
        drop_fit(dress, "0123456789cd")
        write_fit(dress, "clothing")

        print("[D8] Wardrobe status: in the body in either mode, never painted; the cut gates have limits")
        from app.routes.characters import get_character_garment

        def status():
            body = get_character_garment("Kira", heels, {})
            st = body["status"]
            return ({k: st.get(k) for k in ("state", "painted", "missing", "in_body", "reason")}, body["limits"])
        st, limits = status()
        unfitted = {"state": "missing", "painted": False, "missing": None, "in_body": True, "reason": NMF}
        check("D8 retexture unfitted", st, unfitted)
        check("D8 wardrobe unfitted", {k: garment_set.wardrobe("Kira")["items"][heels].get(k)
                                       for k in ("painted", "missing", "in_body")},
              {"painted": False, "missing": None, "in_body": True})
        set_mode(MESH)
        check("D8 mesh unfitted", status()[0], unfitted)
        set_mode(RET)
        check("D8 cut gate limits", {k: limits["fit"].get(k)
                                     for k in ("deep_outside", "visible_poke", "throat_ledge_p95_mm", "toe_conform_m")},
              {"deep_outside": {"op": "le", "value": 0.02}, "visible_poke": {"op": "le", "value": 0.005},
               "throat_ledge_p95_mm": {"op": "le", "value": 4.0}, "toe_conform_m": {"op": "le", "value": 0.025}})
        check("D8 fit gate limits kept", sorted(limits["fit"]),
              sorted(["ball_placement_mm", "lift_asymmetry_mm", "slim_needed", "stand_floor_mm",
                      "shaft_push_p95_m", "shaft_push_max_m", "shaft_inside_share", "seam_gap_p95_mm",
                      "seam_stretch_max", "shaft_leg_follow_deg", "shaft_clip_m", "knee_margin_m",
                      "deep_outside", "visible_poke", "throat_ledge_p95_mm", "toe_conform_m", "shaft_poke",
                      "collar_conform_m", "collar_flex_poke"]))
        check("D8 knee gate limits (Task 14)", (limits["fit"].get("shaft_clip_m"), limits["fit"].get("knee_margin_m")),
              ({"op": "le", "value": 0.05}, {"op": "ge", "value": 0.04}))
        check("D8 shaft_poke / collar_conform_m / collar_flex_poke limits (CUT_VERSION 6)",
              (limits["fit"].get("shaft_poke"), limits["fit"].get("collar_conform_m"), limits["fit"].get("collar_flex_poke")),
              ({"op": "le", "value": 0.005}, {"op": "le", "value": 0.025}, {"op": "le", "value": 0.005}))
        fitted = {k: v for k, v in garment_set.piece_status(
            {"kind": "footwear", "fsig": "f", "steps": {"fit": {"status": "accepted"}}}, worn=True,
            base_model_ready=True).items() if k in ("state", "painted", "missing", "reason")}
        check("D8 fitted", fitted, {"state": "fitted", "painted": False, "missing": False, "reason": None})
        write_fit(heels, "footwear")
        d8 = resolve(full)
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
