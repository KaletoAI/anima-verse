#!/usr/bin/env python3
"""Outfit body mode switch — the worn outfit's body is always listed and marked current in BOTH modes, a mode
switch spends nothing (Build current outfit builds the model of the new mode), bodies survive the switch, and the
3D tab says when it serves a stand-in (app/core/outfit_bodies.py ``worn_texture`` / ``textures`` / ``paint_worn`` /
``body_info``'s ``current``, app/core/model3d_pipeline.py ``build_current_outfit`` / ``fallback_state``,
app/core/artefact_graph.py body rule).

Since Task 6 of plan 2026-11-12-unified-worn-pieces there is no body mode: each worn piece's item mode decides, and
the outfit model is built as the figure DELIVERED now (``figure.delivered_figure``, the interim rule: a wanted shape
not built yet leaves its pieces painted on the plain body meanwhile). "Switch to in_body" below = top and skirt set
to ``in_body``, "switch to painted" = both ``painted``; a mode change is never an automatic trigger (plan Global
Constraints), so every build below is explicit. Until Task 8 Build current outfit answers in two steps after a
switch: "views" (the T-pose pass makes the outfit's views for the figure delivered now — copies of the shape's or
the texture store's, no job here) and then "generating". Replaced cases are named "(was …)".

Since Task 5 of that plan the artefact GC predicts each live outfit under its pieces' CURRENT modes only
(``figure.predicted_keys``): a body whose pieces were all switched to painted, and whose outfit model was rebuilt
painted, is unreachable — but Ruling 5a keeps switching free: an outfit body of the current base built for a live
outfit is ``STORED_NOT_NEEDED``, and an AUTOMATIC walk (``artefact_graph.collect_quietly``) never deletes it
(protected "stored", listed by ``figure.stored_unneeded``); only an explicit collect would ([3]'s dry run).

Usage:
    ./.venv/bin/python scripts/smoke_outfit_body_mode_switch.py

Throwaway storage + instance directory with a copy of the repo's ``human`` package; the outfit_bodies router on a
bare FastAPI app with a TestClient, session lookup stubbed (header ``x-role``: admin / user). No hub, no GPU, no
Blender:
* ``app.imagegen.service.get_image_service`` raises (nothing may reach it);
* ``expression_regen.render_character_image`` = recorder writing PNG + sidecar (one call = the front edit, ONE image
  job), ``base_body._dress_view`` = recorder writing the dressed back (one call = draft + fit, TWO image jobs);
* ``base_body._guard_dressed_views`` passes every view; ``outfit_body_posture.is_stale`` False;
* ``base_body._dress_view`` writes the back as the real two-step view does: a draft naming the front's sha, the fit
  naming the draft's (so the texture store's back follows its front);
* ``model3d.generate_for_current_outfit`` = the build, by hand from the real decisions: with ``outfit_body`` it is
  ONE HUB JOB (mesh + rig of that shape) and writes the rigged and unrigged shape; an outfit build first runs the
  REAL ``base_body.prepare_outfit_figure`` (the wanted shape: a current stored one is reused, else that hub job;
  then the outfit's views for the figure delivered), then ``build_outfit_model`` by hand: the delivered figure's
  shape, its texture painted — reused when the REAL ``base_body.stored_texture_body`` accepts it (unless forced),
  else ONE WORKER RUN (CPU paint) that stores it; nothing painted on a shape = the shape copied; the outfit model
  records ``figure``, ``texture_signature`` and on a shape ``body_id`` / ``body_sha256``;
* ``model3d.trigger_generation`` = recorder that runs that build synchronously (one entry = one queued build);
* ``model_refs.trigger_now`` = the T-pose pass, synchronous (``generate_model_ref_images``; one entry = one pass).
The outfit-change trigger, the auto hook, the GC walk, the stale rules and ``apply_profile_update`` are REAL.

Fixture (Demo: humanoid, pipeline on, side views off -> dressed views front + back, no own-mesh piece). Items top
{top} and skirt {bottom}, both painted (retexture mode). O1 = {top, skirt} worn, O2 = {top}, O3 = {skirt}. Base views front/back, base model
(rigged + unrigged). T1 = the tsig of O1 by the hand rule (no own-mesh piece: unpainted [], variant
outfit_variant = "rigged"); B1 = O1's shape key once top + skirt are in the body (figure.predicted_keys, taken in
[2]). O2 has a retexture model on T2 = what O2's pieces paint now (figure.predicted_keys' texture key — a made-up
tsig is outdated and goes with the first walk) with its painted body, but no dressed views. B2 = shape_key_of of
made-up shape inputs (another outfit's body, [4]).

Expected, by hand:
[1] retexture, nothing built for O1: textures = [pending entry (key O1, current, pending, worn_outfit {O1,
    "Skirt + Top", views_missing [front, back], image_jobs 1 + 2 = 3, model False}, blocked {generate "",
    regenerate PENDING_NO_BODY, delete PENDING_NO_BODY}), T2 (current False, used by O2 with a model, generate
    NOT_WORN_TEXTURE, regenerate NO_SOURCE — O2 has no dressed front —, delete PAINTED_KEPT: O2 would paint it
    now)]. bodies []. Routes: user 403; paint on T2 404; repaint on
    T2 409 NO_SOURCE. POST paint O1 -> 202; the run: 1 front edit + 1 back = 3 image jobs, ONE build (O1, not
    forced), 1 worker run (no painted body of T1 yet), 0 hub jobs, image service never called. Then: textures[0]
    key T1 (== the hand tsig), current, not pending, painted, worn_outfit.model True, generate WORN_MODEL_PRESENT,
    regenerate "" (O1 stands on it), delete PAINTED_KEPT; paint again 409 WORN_MODEL_PRESENT; T2 still not
    current.
[2] painted -> in_body (no shape B1 yet): the switch spends nothing (0 builds, 0 jobs). The delivered figure is
    the plain body with top + skirt painted meanwhile — texture T1, exactly O1's model (was: stale "body_mode");
    pending_changes names top and skirt {wanted in_body, delivered painted}; build-current -> {status "current"},
    nothing spent (was: one build meshing B1 — the shape is Task 7's Build). The worn body's Regenerate (POST
    outfit-bodies/<B1>/regenerate) renders the shape's views (front edit tpose_<B1> + back = 3 image jobs) and
    meshes B1: ONE hub job; O1 is stale "figure" now (delivered: B1, nothing painted). build-current -> "views":
    the T-pose pass once, O1's views copies of B1's (0 image jobs); again -> "generating": ONE build, 0 jobs; O1
    stands on B1 with texture "". in_body -> painted: the switch spends nothing; O1 stale "figure"; build-current
    -> "views" (T1's views back from the texture store: 0 image jobs), then "generating": ONE build, 0 hub
    jobs, 0 worker runs — T1's painted body reused; O1 has no body_id and names T1. B1 still stored after an
    automatic GC walk (artefact_graph.collect_quietly): no live outfit has a piece in the body, but B1 was built
    for O1, which is live -> STORED_NOT_NEEDED, protected "stored"; figure.stored_unneeded(Demo) lists exactly B1
    (kind "shape", built_for O1, bytes = its file sizes, last_used an ISO stamp).
[3] painted -> in_body -> painted again, build-current twice after each switch ("views", then "generating"): ONE
    build each, 2 view passes; in total 0 hub jobs (B1 is current: cached), 0 worker runs (T1 reused), 0 image
    jobs. B1 and T1's painted body still stored after an automatic walk (Ruling 5a). An EXPLICIT collect would
    delete B1: dry run (explicit=True) lists B1 as an orphan with reason STORED_NOT_NEEDED, not protected.
    build-current once more -> {status "current"}, no build.
[4] other outfits' bodies are never current. in_body (build-current twice: ONE build, 0 jobs — B1 is stored), a
    body B2 with O2's model on it AND O1's model
    rewritten to name B2 (an outdated model of the worn outfit on another body): bodies: B1 current True
    (listed first, the worn outfit's views stand for it), B2 current False although O1 (worn) is listed on it.
    painted, not built: the worn outfit's pending entry (key O1) leads as current, T1 not current (O1's views are
    B1's copies until the views pass; was "T1 current"), T2 not.
[5] 3D tab, O3 worn (no model, no views: its name from the worn pieces). fallback_state: {model None,
    signature O3} -> {current O3 "Skirt", served ""}; {model nearest O1} ->
    served O1 "Skirt + Top"; an exact model -> None. POST build-current -> 200 {status
    "views"} and the outfit-change T-pose pass is asked once (trigger_now(("tpose",), force=False)); user 403;
    base model missing -> 409 BASE_MODEL_FIRST. Wear O1 again (painted since [4], its model still on B1 -> stale
    "figure", was "body_mode"): build-current twice -> "views", then "generating": ONE build, 0 jobs (T1 reused);
    T1 current, T2 not (the check moved here from [4]); again -> {status "current"}, no build.
[6] painted body preview. T1: url /characters/Demo/outfit-bodies/T1/model?v=<first 16 hex of sha256(GLB)>,
    freshness current (record names the base model's sha and O1's view shas), outfit_url /characters/Demo/
    model3d/file (worn, built). T2: url set, stale "Made from an older base body" (its record names no base
    model sha), outfit_url None. GET -> the GLB, ETag "<v>", immutable; If-None-Match -> 304; another v ->
    no-cache; user 403; tex999999999999 / B1 -> 404. New GLB bytes -> new v; O1's back re-rendered -> stale
    "Dressed views re-rendered since this model". Wearing O3: the pending entry has no url, no badge.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
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


def png(path: Path, colour) -> Path:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 16), colour).save(path)
    return path


def write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="outfit-body-mode-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "inst")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "inst")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "inst/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.core import (artefact_graph, auth_dependency, base_body, expression_regen, model3d,
                              model3d_pipeline, model_refs, outfit_bodies, outfit_body_posture)
        from app.core.model_refs import mesh_items_token, mesh_signature, mesh_variant
        from app.imagegen import service as image_service
        from app.models import inventory
        from app.models.character import get_character_dir, get_character_images_dir, get_character_profile, \
            save_character_profile
        from app.routes import outfit_bodies as outfit_bodies_routes

        image_calls = []

        def no_image_service(*a, **kw):
            image_calls.append(1)
            raise RuntimeError("no image service in this smoke")
        image_service.get_image_service = no_image_service

        users = {"admin": {"id": "a", "username": "admin", "role": "admin"},
                 "user": {"id": "u", "username": "player", "role": "user", "allowed_characters": ["Demo"]}}
        auth_dependency._get_session_user = lambda request: users.get(request.headers.get("x-role", ""))
        app = FastAPI()
        app.include_router(outfit_bodies_routes.router)
        client = TestClient(app)
        ADMIN, USER = {"x-role": "admin"}, {"x-role": "user"}

        char = "Demo"
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender"}
        assert save_character_profile(char, human, create_new=True)
        png(get_character_images_dir(char) / f"{char}_1.png", (200, 180, 160))
        prof = get_character_profile(char)
        prof["profile_image"] = f"{char}_1.png"
        assert save_character_profile(char, prof)
        assert base_body.set_pipeline(char, True)
        for key, slots in (("top", ["top"]), ("skirt", ["bottom"])):
            op = {"slots": slots, "covers": [], "outfit_types": ["casual"], "mesh_mode": "painted"}
            inventory.add_item(name=key.title(), category="outfit_piece", item_id=key,
                               prompt_fragment=f"a plain {key}", outfit_piece=op)
            inventory.add_to_inventory(char, key)

        def wear(pieces):
            p = get_character_profile(char)
            p["equipped_pieces"] = dict(pieces)
            assert save_character_profile(char, p)

        def sig_of(pieces):
            return mesh_signature(pieces, [], char, mesh_variant(char, pieces), mesh_items_token(char, pieces))

        P1, P2, P3 = {"top": "top", "bottom": "skirt"}, {"top": "top"}, {"bottom": "skirt"}
        wear(P1)
        prof = get_character_profile(char)
        O1, O2, O3 = sig_of(P1), sig_of(P2), sig_of(P3)

        cdir = get_character_dir(char)
        M, R = cdir / "model3d", cdir / "model_refs"
        bsig = base_body.base_signature(char)
        sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()  # noqa: E731
        base_views = {"front": png(R / f"tpose_{bsig}.png", (10, 10, 10)),
                      "back": png(R / f"tpose_back_{bsig}.png", (20, 20, 20))}
        for p in base_views.values():
            write_json(p.with_suffix(".json"), {"base_signature": bsig})
        M.mkdir(parents=True, exist_ok=True)
        (M / f"{bsig}.glb").write_bytes(b"BASE-GLB")
        write_json(M / f"{bsig}.json", {"base": True, "rig": "mixamo"})
        (M / "unrigged").mkdir(parents=True, exist_ok=True)
        (M / "unrigged" / f"{bsig}.glb").write_bytes(b"BASE-UNRIGGED")
        base_sha = sha(M / f"{bsig}.glb")
        outfit_bodies.stale_posture = lambda c, meta: ""
        outfit_body_posture.is_stale = lambda c, b: False
        base_body._guard_dressed_views = lambda *a, **k: ({}, [])

        T1 = base_body.texture_signature(base_body.texture_inputs(
            char, pieces=P1, items=[], variant=base_body.outfit_variant(char, P1, profile=prof),
            mesh_effective=[], bsig=bsig, profile={**prof, "equipped_pieces": P1, "equipped_items": []}))
        from app.core import figure
        B1 = None   # O1's shape key: computable once its pieces are in the body ([2])
        # What O2's pieces would paint now (a made-up tsig no outfit paints is outdated and goes with the
        # first walk — artefact_graph._current_textures).
        T2 = figure.predicted_keys(char, P2, [], bsig=bsig, profile=prof)[1]
        B2_INPUTS = {"version": figure.SHAPE_VERSION, "base_signature": bsig, "dress_text": {"front": "O2 elsewhere"}}
        B2 = figure.shape_key_of(B2_INPUTS)

        def manifest(pieces):
            return {"pieces": dict(pieces), "items": [], "mesh_variant": mesh_variant(char, pieces),
                    "mesh_token": mesh_items_token(char, pieces)}

        # O2: a retexture model on T2 with its painted body, no dressed views.
        (M / f"{O2}.glb").write_bytes(b"MODEL-O2")
        write_json(M / f"{O2}.json", {"character": char, **manifest(P2), "base_signature": bsig,
                                      "base_model_sha256": base_sha, "texture_signature": T2, "dressed": True,
                                      "created_at": "2026-11-10T10:00:00+00:00", "rig": "mixamo"})
        (M / "texture").mkdir(parents=True, exist_ok=True)
        (M / "texture" / f"{T2}.glb").write_bytes(b"PAINTED-T2")
        write_json(M / "texture" / f"{T2}.json", {"texture_signature": T2, "base_signature": bsig,
                                                  "created_at": "2026-11-10T10:00:00+00:00"})

        renders, backs, builds, hub_jobs, workers, triggers = [], [], [], [], [], []

        def fake_render(character_name, *, output_stem, sidecar_extra=None, equipped_pieces=None,
                        equipped_items=None, **kw):
            renders.append((Path(output_stem).name, kw.get("occasion")))
            out = png(Path(f"{output_stem}.png"), (100, 50 + len(renders), 0))
            write_json(out.with_suffix(".json"), {"equipped_pieces": equipped_pieces or {},
                                                  "equipped_items": equipped_items or [],
                                                  "created_at": "2026-11-10T12:00:00+00:00",
                                                  **(sidecar_extra or {})})
            return out
        expression_regen.render_character_image = fake_render

        def fake_dress_view(character_name, view, *, signature, bsig, pieces, items, profile, front, base_views,
                            refs_dir, size, mesh_items=None, texture=None):
            backs.append((view, signature))
            # As the real two-step view: the draft from the front (sidecar front_sha256), the fit naming the draft.
            draft = png(refs_dir / base_body.DRAFT_DIR / f"{base_body._kind(view)}_{signature}.png", (0, 0, 60))
            write_json(draft.with_suffix(".json"), {"front_sha256": sha(front)})
            out = png(refs_dir / f"{base_body._kind(view)}_{signature}.png", (0, 0, 120))
            write_json(out.with_suffix(".json"), {"equipped_pieces": dict(pieces or {}),
                                                  "equipped_items": list(items or []), "base_signature": bsig,
                                                  "dressed": True, "base_image_sha256": sha(base_views[view]),
                                                  f"{view}_draft_sha256": sha(draft), **(texture or {})})
            return out, None
        base_body._dress_view = fake_dress_view

        def fake_generate(character_name, *, force=False, signature=None, outfit_body=None, **kw):
            if outfit_body is not None:
                # ONE hub job: the shape meshed and rigged from its views.
                hub_jobs.append(signature)
                body = base_body.outfit_body_path(character_name, signature)
                body.write_bytes(b"BODY-" + signature.encode())
                (body.parent / "unrigged").mkdir(parents=True, exist_ok=True)
                (body.parent / "unrigged" / body.name).write_bytes(b"BODY-UNRIGGED-" + signature.encode())
                write_json(body.with_suffix(".json"), {"rig": "mixamo", **outfit_body,
                                                       "created_at": "2026-11-10T13:00:00+00:00"})
                return {"ok": True}
            signature = signature or model_refs.current_outfit_state(character_name)[2]
            builds.append((signature, force))
            if not force and model3d.find_model3d(character_name, signature):
                return {"ok": True, "cached": True}
            # The REAL preparation (model3d.generate_for_current_outfit): the wanted shape, then the views of
            # the figure delivered then.
            prepared = base_body.prepare_outfit_figure(character_name, signature, force=force)
            if prepared is not None and not prepared.get("ok"):
                return prepared
            # base_body.build_outfit_model by hand: the delivered figure's shape, its texture painted or reused.
            front = base_body.dressed_image(character_name, "front", signature, bsig)
            if front is None:
                return {"ok": False, "error": base_body.DRESSED_IMAGES_MISSING}
            first = model3d._ref_manifest(front)
            fig = figure.delivered_figure(character_name, pieces=dict(first.get("pieces") or {}),
                                          items=list(first.get("items") or []))
            tsig = fig.texture
            meta = {"character": character_name, **manifest(first.get("pieces") or {}), "base_signature": bsig,
                    "base_model_sha256": base_sha, "texture_signature": tsig, "dressed": True, "rig": "mixamo",
                    "base_variant": "rigged", "source": "base_body", "figure": fig.as_dict(),
                    "created_at": "2026-11-10T14:00:00+00:00"}
            meshed = not figure.is_plain(fig.shape)
            if meshed:
                meta.update(body_id=fig.shape,
                            body_sha256=sha(base_body.outfit_body_path(character_name, fig.shape)))
            if tsig:
                source = (base_body._snapshot_shape(character_name, fig.shape, bsig) if meshed
                          else base_body._snapshot_base_model(character_name, bsig))
                shas = base_body.texture_view_shas(character_name, signature, bsig, fig=fig)
                stored = None if force else base_body.stored_texture_body(character_name, tsig, base=source,
                                                                          view_shas=shas)
                if stored is None:
                    workers.append(tsig)   # ONE worker run: the texture painted
                    data = b"PAINTED-" + tsig.encode()
                    path = base_body.texture_body_path(character_name, tsig)
                    path.write_bytes(data)
                    rigged = hashlib.sha256(source["rigged"]).hexdigest()
                    write_json(path.with_suffix(".json"), {
                        "texture_signature": tsig, "base_signature": bsig, "base_model_sha256": rigged,
                        "source_model_sha256": rigged, "base_variant": "rigged", "covered_missing": False,
                        "views": shas, "body_sha256": hashlib.sha256(data).hexdigest(),
                        "created_at": "2026-11-10T14:00:00+00:00"})
            (M / f"{signature}.glb").write_bytes(b"MODEL-" + signature.encode())
            write_json(M / f"{signature}.json", meta)
            return {"ok": True}
        model3d.generate_for_current_outfit = fake_generate

        def fake_trigger(character_name, *, force=False, followup=False, **kw):
            triggers.append((character_name, force))
            fake_generate(character_name, force=force)
            return True
        model3d.trigger_generation = fake_trigger

        passes = []

        def fake_pass(name, kinds=None, **kw):
            # The outfit-change T-pose pass, synchronous: the worn outfit's views (images counted as above).
            passes.append((name, kinds, kw.get("force")))
            model_refs.generate_model_ref_images(name, kinds=("tpose",))
        model_refs.trigger_now = fake_pass

        def tab():
            return client.get(f"/characters/{char}/outfit-bodies", headers=ADMIN).json()

        def counts():
            return {"images": len(renders) + 2 * len(backs), "hub": len(hub_jobs), "workers": len(workers),
                    "builds": len(triggers)}

        def reset():
            for lst in (renders, backs, builds, hub_jobs, workers, triggers):
                lst.clear()

        def set_mode(mode):
            for key in ("top", "skirt"):
                op = dict(inventory.get_item(key)["outfit_piece"])
                op["mesh_mode"] = "in_body" if mode == "mesh" else "painted"
                assert inventory.update_item(key, {"outfit_piece": op})
            return sorted(figure.wanted_figure(char).in_body)

        build = f"/characters/{char}/model3d/build-current"

        def build_current():
            r = client.post(build, headers=ADMIN)
            return r.status_code, r.json()

        def build_twice():
            """Build current outfit as it answers until Task 8: the outfit's views for the figure delivered now
            first (the T-pose pass; a view the texture store holds or a copy of the shape's is no job), then the
            model."""
            return build_current(), build_current()

        # --- [1] ---------------------------------------------------------------------------------------------
        print("[1] retexture: the worn outfit's pending entry, Generate")
        info = tab()
        texs = info["textures"]
        check("[1] keys", [t["key"] for t in texs], [O1, T2])
        p = texs[0]
        check("[1] pending entry", (p["current"], p["pending"], p["texture_signature"]), (True, True, None))
        check("[1] worn_outfit", p["worn_outfit"], {"signature": O1, "name": "Skirt + Top",
                                                   "views_missing": ["front", "back"], "image_jobs": 3,
                                                   "model": False})
        check("[1] pending blocked", p["blocked"], {"generate": "", "regenerate": outfit_bodies.PENDING_NO_BODY,
                                                    "delete": outfit_bodies.PENDING_NO_BODY})
        o = texs[1]
        check("[1] other body not current", (o["current"], [(x["signature"], x["has_model"]) for x in o["outfits"]]),
              (False, [(O2, True)]))
        check("[1] other blocked", o["blocked"], {"generate": outfit_bodies.NOT_WORN_TEXTURE,
                                                  "regenerate": outfit_bodies.NO_SOURCE,
                                                  "delete": outfit_bodies.PAINTED_KEPT})
        check("[1] no outfit bodies", info["bodies"], [])
        url = f"/characters/{char}/outfit-bodies"
        check("[1] user -> 403", client.post(f"{url}/{O1}/paint", headers=USER).status_code, 403)
        r = client.post(f"{url}/{T2}/paint", headers=ADMIN)
        check("[1] paint other -> 404", (r.status_code, r.json().get("detail")), (404, outfit_bodies.NOT_WORN_TEXTURE))
        r = client.post(f"{url}/{T2}/repaint", headers=ADMIN)
        check("[1] repaint without source -> 409", (r.status_code, r.json().get("detail")),
              (409, outfit_bodies.NO_SOURCE))
        r = client.post(f"{url}/{O1}/paint", headers=ADMIN)
        check("[1] paint -> 202", (r.status_code, r.json().get("kind")), (202, "paint"))
        check("[1] run ended", wait_for(lambda: not outfit_bodies._active), True)
        check("[1] front edit + back", (renders, backs), ([(f"tpose_{O1}", "outfit_front")], [("back", O1)]))
        check("[1] one build, not forced", builds, [(O1, False)])
        check("[1] jobs", (len(renders) + 2 * len(backs), len(hub_jobs), workers, image_calls), (3, 0, [T1], []))
        texs = tab()["textures"]
        c = texs[0]
        check("[1] current entry is T1", (c["key"], c["current"], c["pending"], c["painted"]), (T1, True, False, True))
        check("[1] model built", c["worn_outfit"]["model"], True)
        check("[1] blocked after", c["blocked"], {"generate": outfit_bodies.WORN_MODEL_PRESENT, "regenerate": "",
                                                  "delete": outfit_bodies.PAINTED_KEPT})
        check("[1] regenerate source", c["regenerate_from"], O1)
        r = client.post(f"{url}/{T1}/paint", headers=ADMIN)
        check("[1] paint again -> 409", (r.status_code, r.json().get("detail")),
              (409, outfit_bodies.WORN_MODEL_PRESENT))
        check("[1] T2 still not current", [(t["key"], t["current"]) for t in texs], [(T1, True), (T2, False)])

        # --- [2] ---------------------------------------------------------------------------------------------
        print("[2] painted -> in the body -> painted")
        reset()
        check("[2] switch to in_body", set_mode("mesh"), ["skirt", "top"])
        B1 = figure.predicted_keys(char, P1, [], bsig=bsig)[0]
        check("[2] B1 = O1's shape key", base_body.is_outfit_body_signature(B1), True)
        check("[2] the switch spends nothing", counts(), {"images": 0, "hub": 0, "workers": 0, "builds": 0})
        check("[2] interim: delivered on the plain body as T1", (figure.delivered_figure(char).shape,
                                                                figure.delivered_figure(char).texture), (bsig, T1))
        check("[2] pending changes (pieces)", sorted((c["key"], c["wanted"], c["delivered"])
                                                     for c in figure.pending_changes(char) if c["key"] in P1.values()),
              [("skirt", "in_body", "painted"), ("top", "in_body", "painted")])
        check("[2] build-current: O1's model is the delivered figure", build_current(), (200, {"status": "current"}))
        check("[2] nothing spent", counts(), {"images": 0, "hub": 0, "workers": 0, "builds": 0})
        r = client.post(f"{url}/{B1}/regenerate", headers=ADMIN)
        check("[2] Regenerate the worn body -> 202", r.status_code, 202)
        check("[2] run ended", wait_for(lambda: not outfit_bodies._active), True)
        check("[2] the shape's views, then ONE hub job", (counts(), renders, backs, hub_jobs),
              ({"images": 3, "hub": 1, "workers": 0, "builds": 0}, [(f"tpose_{B1}", "outfit_front")],
               [("back", B1)], [B1]))
        check("[2] O1 stale (figure)", base_body.outfit_info(char).get("stale_reason"), "figure")
        reset()
        check("[2] build-current: the views first", build_current(), (200, {"status": "views"}))
        check("[2] the T-pose pass once, its views copies of B1's", (passes, counts()),
              ([(char, ("tpose",), False)], {"images": 0, "hub": 0, "workers": 0, "builds": 0}))
        check("[2] build-current again", build_current(), (200, {"status": "generating"}))
        check("[2] in the body: one build, no job", counts(), {"images": 0, "hub": 0, "workers": 0, "builds": 1})
        o1 = json.loads((M / f"{O1}.json").read_text())
        check("[2] O1 stands on B1, nothing painted", (o1.get("body_id"), (o1.get("figure") or {}).get("texture")),
              (B1, ""))
        reset()
        passes.clear()
        check("[2] switch to painted", set_mode("retexture"), [])
        check("[2] the switch spends nothing", counts(), {"images": 0, "hub": 0, "workers": 0, "builds": 0})
        check("[2] O1 stale (figure)", base_body.outfit_info(char).get("stale_reason"), "figure")
        check("[2] painted: build-current twice -> views, then generating", build_twice(),
              ((200, {"status": "views"}), (200, {"status": "generating"})))
        check("[2] painted: T1's views from the store, T1's painted body reused", (counts(), len(passes)),
              ({"images": 0, "hub": 0, "workers": 0, "builds": 1}, 1))
        o1 = json.loads((M / f"{O1}.json").read_text())
        check("[2] O1 painted on the plain body again", ("body_id" in o1, o1.get("texture_signature")), (False, T1))
        report = artefact_graph.collect_quietly(char, "smoke")
        check("[2] B1 kept by the automatic walk (stored, not needed now)",
              (base_body.outfit_body_path(char, B1).is_file(),
               sorted({s["why"] for s in (report or {}).get("skipped", []) if s["key"] == B1})),
              (True, [artefact_graph.STORED]))
        unneeded = figure.stored_unneeded(char)
        check("[2] stored_unneeded lists B1",
              [(e["key"], e["kind"], e["built_for"], e["bytes"] > 0, bool(e["last_used"])) for e in unneeded],
              [(B1, "shape", O1, True, True)])

        # --- [3] ---------------------------------------------------------------------------------------------
        print("[3] back and forth: no job for shapes and textures that exist")
        reset()
        passes.clear()
        set_mode("mesh")
        check("[3] in the body again", build_twice(), ((200, {"status": "views"}), (200, {"status": "generating"})))
        check("[3] in the body again: one build, 0 jobs", counts(), {"images": 0, "hub": 0, "workers": 0, "builds": 1})
        set_mode("retexture")
        check("[3] painted again", build_twice(), ((200, {"status": "views"}), (200, {"status": "generating"})))
        check("[3] painted again: 2 builds in total, 2 view passes, 0 jobs", (counts(), len(passes)),
              ({"images": 0, "hub": 0, "workers": 0, "builds": 2}, 2))
        artefact_graph.collect_quietly(char, "smoke")
        check("[3] B1 + painted T1 stored", (base_body.outfit_body_path(char, B1).is_file(),
                                             base_body.texture_body_path(char, T1).is_file()), (True, True))
        dry = artefact_graph.collect(char, dry_run=True, explicit=True, reason="smoke")
        check("[3] an explicit collect would delete B1",
              sorted({(e["reason"], e["protected"]) for e in dry["orphans"] if e["key"] == B1}),
              [(artefact_graph.STORED_NOT_NEEDED, "")])
        reset()
        check("[3] built: current", build_current(), (200, {"status": "current"}))
        check("[3] no further build", counts(), {"images": 0, "hub": 0, "workers": 0, "builds": 0})

        # --- [4] ---------------------------------------------------------------------------------------------
        print("[4] other outfits' bodies are never current")
        set_mode("mesh")
        reset()
        check("[4] in the body: build-current", build_twice(),
              ((200, {"status": "views"}), (200, {"status": "generating"})))
        check("[4] mesh: one build on the stored B1", counts(), {"images": 0, "hub": 0, "workers": 0, "builds": 1})
        rec = {"body_id": B2, "shape_key": B2, "version": figure.SHAPE_VERSION, "shape_inputs": B2_INPUTS,
               "base_signature": bsig, "built_for": O2, "views": {}, "used_views": ["front"]}
        base_body.outfit_body_path(char, B2).write_bytes(b"BODY-B2")
        write_json(M / f"{B2}.json", {"rig": "mixamo", "outfit_body": rec, "created_at": "2026-11-10T09:00:00+00:00"})
        o2 = json.loads((M / f"{O2}.json").read_text())
        o2.update(outfit_body_mode="mesh", body_id=B2, body_sha256=sha(M / f"{B2}.glb"))
        write_json(M / f"{O2}.json", o2)
        o1 = json.loads((M / f"{O1}.json").read_text())
        o1.update(body_id=B2, body_sha256=sha(M / f"{B2}.glb"))
        write_json(M / f"{O1}.json", o1)
        bodies = tab()["bodies"]
        check("[4] mesh: B1 current first", [(b["body_id"], b["current"]) for b in bodies], [(B1, True), (B2, False)])
        b2 = bodies[1]
        check("[4] B2 lists the worn O1 (outdated) and O2, still not current",
              (sorted((x["signature"], x["worn"]) for x in b2["outfits"]), b2["current"]),
              (sorted([(O1, True), (O2, False)]), False))
        o1["body_id"] = B1
        o1["body_sha256"] = sha(base_body.outfit_body_path(char, B1))
        write_json(M / f"{O1}.json", o1)
        set_mode("retexture")
        check("[4] painted, not built yet: the worn outfit's pending entry leads, T1 and T2 not current",
              [(t["key"], t["current"]) for t in tab()["textures"]], [(O1, True), (T1, False), (T2, False)])

        # --- [5] ---------------------------------------------------------------------------------------------
        print("[5] 3D tab: stand-in banner, Build current outfit")
        wear(P3)
        fb = model3d_pipeline.fallback_state
        check("[5] no model", fb(char, {"signature": O3, "model": None}),
              {"current_signature": O3, "current_name": "Skirt", "served_signature": "", "served_name": ""})
        check("[5] nearest", fb(char, {"signature": O3, "model": {"signature": O1, "match": "nearest"}}),
              {"current_signature": O3, "current_name": "Skirt", "served_signature": O1,
               "served_name": "Skirt + Top"})
        check("[5] exact -> none", fb(char, {"signature": O1, "model": {"signature": O1, "match": "exact"}}), None)
        model_refs.trigger_now = lambda name, kinds=None, **kw: passes.append((name, kinds, kw.get("force")))
        passes.clear()
        reset()
        check("[5] user -> 403", client.post(build, headers=USER).status_code, 403)
        r = client.post(build, headers=ADMIN)
        check("[5] build-current: views first", (r.status_code, r.json()), (200, {"status": "views"}))
        check("[5] the outfit-change T-pose pass, once", passes, [(char, ("tpose",), False)])
        base_glb = M / f"{bsig}.glb"
        base_glb.rename(M / "base.bak")
        r = client.post(build, headers=ADMIN)
        check("[5] no base model -> 409", (r.status_code, r.json().get("detail")),
              (409, model3d_pipeline.BASE_MODEL_FIRST))
        (M / "base.bak").rename(base_glb)
        model_refs.trigger_now = fake_pass
        wear(P1)
        check("[5] O1 worn, its model on B1: views, then rebuilt", build_twice(),
              ((200, {"status": "views"}), (200, {"status": "generating"})))
        check("[5] one build, T1 reused", counts(), {"images": 0, "hub": 0, "workers": 0, "builds": 1})
        check("[5] painted: T1 current, T2 not", [(t["key"], t["current"]) for t in tab()["textures"]],
              [(T1, True), (T2, False)])
        r = client.post(build, headers=ADMIN)
        check("[5] again: current", (r.status_code, r.json()), (200, {"status": "current"}))
        check("[5] no further build", counts()["builds"], 1)

        # --- [6] ---------------------------------------------------------------------------------------------
        print("[6] painted body preview: url, freshness, the model route")
        from app.core.model_overview import DRESSED_VIEWS_CHANGED, OLDER_BASE_BODY
        texs = {t["key"]: t for t in tab()["textures"]}
        t1_path = base_body.texture_body_path(char, T1)
        v1 = hashlib.sha256(t1_path.read_bytes()).hexdigest()[:16]
        model_url = f"/characters/{char}/outfit-bodies/{T1}/model"
        check("[6] T1 url", texs[T1]["url"], f"{model_url}?v={v1}")
        check("[6] T1 current", texs[T1]["freshness"], {"state": "current", "reason": ""})
        check("[6] T1 outfit_url (worn, built)", texs[T1]["outfit_url"], f"/characters/{char}/model3d/file")
        check("[6] T2 painted, older base, not worn", (bool(texs[T2]["url"]), texs[T2]["freshness"],
                                                       texs[T2]["outfit_url"]),
              (True, {"state": "stale", "reason": OLDER_BASE_BODY}, None))
        r = client.get(texs[T1]["url"], headers=ADMIN)
        check("[6] GET -> the painted GLB, immutable", (r.status_code, r.content, r.headers.get("etag"),
                                                        r.headers.get("cache-control")),
              (200, t1_path.read_bytes(), f'"{v1}"', "public, max-age=31536000, immutable"))
        r = client.get(model_url, headers={**ADMIN, "if-none-match": f'"{v1}"'})
        check("[6] If-None-Match -> 304", r.status_code, 304)
        check("[6] other v -> no-cache", client.get(f"{model_url}?v=0", headers=ADMIN).headers.get("cache-control"),
              "no-cache")
        check("[6] user -> 403", client.get(model_url, headers=USER).status_code, 403)
        check("[6] unknown tsig -> 404", client.get(f"/characters/{char}/outfit-bodies/tex999999999999/model",
                                                    headers=ADMIN).status_code, 404)
        check("[6] not a tsig -> 404", client.get(f"/characters/{char}/outfit-bodies/{B1}/model",
                                                  headers=ADMIN).status_code, 404)
        t1_path.write_bytes(b"PAINTED-AGAIN")
        url2 = next(t for t in tab()["textures"] if t["key"] == T1)["url"]
        check("[6] content changed -> new version", url2,
              f"{model_url}?v={hashlib.sha256(b'PAINTED-AGAIN').hexdigest()[:16]}")
        png(R / f"tpose_back_{O1}.png", (1, 2, 3))   # O1's dressed back re-rendered
        check("[6] views re-rendered -> stale", next(t for t in tab()["textures"] if t["key"] == T1)["freshness"],
              {"state": "stale", "reason": DRESSED_VIEWS_CHANGED})
        wear(P3)
        p = next(t for t in tab()["textures"] if t["current"])
        check("[6] pending entry: no url, no badge", (p["pending"], p["url"], p["freshness"], p["outfit_url"]),
              (True, None, None, None))

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): {', '.join(FAILS)}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
