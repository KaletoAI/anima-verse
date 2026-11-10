#!/usr/bin/env python3
"""Outfit body tab — the worn outfit's body before its dressed views exist, Generate views, the visible
reasons of disabled actions and the orphaned bodies (app/core/outfit_bodies.py ``worn_body`` /
``render_worn_views`` / ``body_info``'s ``blocked`` / ``orphaned``,
``POST /characters/{c}/outfit-bodies/{body}/generate-views``, ``POST …/{body}/cancel``).

Usage:
    ./.venv/bin/python scripts/smoke_outfit_body_worn_views.py

Throwaway storage + instance directory with a copy of the repo's ``human`` package; the outfit_bodies router on a
bare FastAPI app with a TestClient, session lookup stubbed (header ``x-role``: admin / user / none). No hub, no
GPU: ``app.imagegen.service.get_image_service`` raises (nothing may reach it), ``expression_regen.
render_character_image`` is a recorder that writes a PNG + sidecar (one call = the front edit, one image job),
``base_body._dress_view`` a recorder that writes the dressed back (one call = draft + fit, two image jobs),
``base_body.prepare_outfit_body`` a recorder (one call = one mesh run).

Fixture (character Demo: humanoid, pipeline on, outfit_body_mode mesh, side views off = the default). Items top
{top} and skirt {bottom}, painted (no own-mesh flag), both WORN = outfit O1. Base views front/back of bsig, base
model. NO dressed view of O1, no outfit model, no outfit body.

Expected, by hand:
[1] GET: exactly one body, the worn outfit's PENDING entry P. P is the body the views will stand on: no own-mesh
    piece, so the unpainted set is empty and the tsig is ``texture_signature(texture_inputs(pieces, items,
    variant=outfit_variant(pieces), mesh_effective=[], bsig))`` — P = outfit_body_id(that), computed here through
    the public functions. status "missing", orphaned False, worn_outfit = {signature O1, predicted True,
    views_missing [front, back], image_jobs 3} (side views off: the front is ONE edit, the back a draft plus a
    fit = 2 → 1 + 2 = 3). blocked: regenerate WORN_VIEWS_MISSING (no outfit stands on P's views), rerig
    NO_UNRIGGED, refit NO_MODEL (no glb), delete NOTHING_STORED (no file of P at all), views "" (it can run).
    view_info: front + back listed (dressed views), url None, blocked WORN_VIEWS_MISSING (not NO_SOURCE).
[2] Routes: user -> 403, anonymous -> 401; generate-views on another body id -> 404 NOT_WORN_BODY. Another 3D run
    holds the generation guard: POST generate-views -> 202 started True (the worker took it and waits);
    a second POST -> 202 queued position 1 (the running one is not in the waiting list). GET: P status "running",
    run_kind "views"; EVERY action blocked with LOCKED_RUNNING (the lock comes before the static reasons).
    cancel {} -> 200 cancelled 1 (the waiting one); cancel {} again -> 409 (only the running one is left).
    Nothing rendered while the guard is held.
[3] Guard released -> the run ends: exactly ONE front edit (output_stem tpose_<O1>, occasion outfit_front) and
    ONE back (``_dress_view`` view back, signature O1) — 3 image jobs as predicted; ZERO mesh runs (no
    auto-chain), get_image_service never called. last_run {kind views, ok True}. GET: P is now O1's real body
    (``base_body.outfit_body_of_outfit(O1) == P`` — the prediction held), still one body, worn_outfit.predicted
    False, views_missing [], blocked.views WORN_VIEWS_PRESENT, blocked.regenerate "" (O1 stands on it), front +
    back urls set. POST generate-views again -> 409 WORN_VIEWS_PRESENT. POST regenerate -> 202 and the mesh
    recorder gets (Demo, O1, rebuild=True) — the mesh step is the body's own run.
[4] A 3D model job builds P (``model3d.active_stages`` names (Demo, P)): GET -> status "running", run_kind
    "build", every action blocked with LOCKED_BUILD.
[5] Orphan: refs of a body Q = outfit_body_id("tex0123456789ab") whose record names another texture and an outfit
    that does not exist (built_for "0000deadbeef"), never built. GET: Q listed AFTER P, orphaned True, status
    "missing", worn_outfit None, blocked.regenerate NO_SOURCE, blocked.delete "" (its refs are stored),
    view front blocked NO_SOURCE. P: orphaned False. POST generate-views on Q -> 404.
[6] Nothing worn (undressed): no worn entry any more. P drops out of the list — nothing of P itself is stored (the
    mesh recorder wrote no body file; O1's dressed views live in the outfit's refs and the texture store, not
    under P's id) and no worn outfit names it; Q stays, orphaned.
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
    with tempfile.TemporaryDirectory(prefix="outfit-body-worn-") as tmp:
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
        from app.core import auth_dependency, base_body, expression_regen, model3d, outfit_bodies
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
                 "character_appearance": "slender", "outfit_body_mode": "mesh"}
        assert save_character_profile(char, human, create_new=True)
        png(get_character_images_dir(char) / f"{char}_1.png", (200, 180, 160))
        prof = get_character_profile(char)
        prof["profile_image"] = f"{char}_1.png"
        assert save_character_profile(char, prof)
        assert base_body.set_pipeline(char, True)
        for key, slots in (("top", ["top"]), ("skirt", ["bottom"])):
            op = {"slots": slots, "covers": [], "outfit_types": ["casual"]}
            inventory.add_item(name=key.title(), category="outfit_piece", item_id=key,
                               prompt_fragment=f"a plain {key}", outfit_piece=op)
            inventory.add_to_inventory(char, key)
        pieces = {"top": "top", "bottom": "skirt"}
        prof = get_character_profile(char)
        prof["equipped_pieces"] = dict(pieces)
        assert save_character_profile(char, prof)
        prof = get_character_profile(char)

        cdir = get_character_dir(char)
        M, R = cdir / "model3d", cdir / "model_refs"
        bsig = base_body.base_signature(char)
        sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()  # noqa: E731
        base_views = {"front": png(R / f"tpose_{bsig}.png", (10, 10, 10)),
                      "back": png(R / f"tpose_back_{bsig}.png", (20, 20, 20))}
        for p in base_views.values():
            write_json(p.with_suffix(".json"), {"base_signature": bsig})
        (M / f"{bsig}.glb").parent.mkdir(parents=True, exist_ok=True)
        (M / f"{bsig}.glb").write_bytes(b"BASE-GLB")
        write_json(M / f"{bsig}.json", {"base": True, "rig": "mixamo"})
        outfit_bodies.stale_posture = lambda c, meta: ""

        O1 = mesh_signature(pieces, [], char, mesh_variant(char, pieces), mesh_items_token(char, pieces))
        # The hand rule of [1]: no own-mesh piece -> nothing unpainted, variant = outfit_variant(pieces).
        T = base_body.texture_signature(base_body.texture_inputs(
            char, pieces=pieces, items=[], variant=base_body.outfit_variant(char, pieces, profile=prof),
            mesh_effective=[], bsig=bsig, profile={**prof, "equipped_pieces": pieces, "equipped_items": []}))
        P = base_body.outfit_body_id(T)

        renders, backs, meshes = [], [], []

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
            out = png(refs_dir / f"{base_body._kind(view)}_{signature}.png", (0, 0, 120))
            write_json(out.with_suffix(".json"), {"equipped_pieces": dict(pieces or {}),
                                                  "equipped_items": list(items or []), "base_signature": bsig,
                                                  "dressed": True, "base_image_sha256": sha(base_views[view]),
                                                  **(texture or {})})
            return out, None
        base_body._dress_view = fake_dress_view

        def fake_prepare(c, signature=None, *, force=False, rebuild=False):
            meshes.append((c, signature, rebuild))
            return {"ok": True, "cached": False, "body_id": P}
        base_body.prepare_outfit_body = fake_prepare

        def bodies():
            return client.get(f"/characters/{char}/outfit-bodies", headers=ADMIN).json()["bodies"]

        def body(bid):
            return next((b for b in bodies() if b["body_id"] == bid), None)

        url = f"/characters/{char}/outfit-bodies/{P}/generate-views"
        actions = ["regenerate", "rerig", "refit", "delete", "views"]

        # --- [1] ---------------------------------------------------------------------------------------------
        print("[1] the worn outfit's pending entry")
        listed = bodies()
        check("[1] one body: P", [b["body_id"] for b in listed], [P])
        b = listed[0]
        check("[1] status / orphaned", (b["status"], b["orphaned"]), ("missing", False))
        check("[1] worn_outfit", b["worn_outfit"], {"signature": O1, "name": "Skirt + Top", "predicted": True,
                                                   "views_missing": ["front", "back"], "image_jobs": 3})
        check("[1] blocked", b["blocked"], {"regenerate": outfit_bodies.WORN_VIEWS_MISSING,
                                            "rerig": outfit_bodies.NO_UNRIGGED, "refit": outfit_bodies.NO_MODEL,
                                            "delete": outfit_bodies.NOTHING_STORED, "views": ""})
        check("[1] view tiles", {v: (e["url"], e["blocked"]) for v, e in b["view_info"].items()},
              {"front": (None, outfit_bodies.WORN_VIEWS_MISSING), "back": (None, outfit_bodies.WORN_VIEWS_MISSING)})

        # --- [2] ---------------------------------------------------------------------------------------------
        print("[2] routes, queue, lock reasons, cancel")
        check("[2] user -> 403", client.post(url, headers=USER).status_code, 403)
        check("[2] anonymous -> 401", client.post(url).status_code, 401)
        r = client.post(f"/characters/{char}/outfit-bodies/ob00000000/generate-views", headers=ADMIN)
        check("[2] other body -> 404", (r.status_code, r.json().get("detail")), (404, outfit_bodies.NOT_WORN_BODY))
        with model3d._lock:
            model3d._generating.add(char)   # another 3D run of the character holds the guard
        r = client.post(url, headers=ADMIN)
        check("[2] first answer", (r.status_code, r.json().get("kind"), r.json().get("started")), (202, "views", True))
        r = client.post(url, headers=ADMIN)
        check("[2] second queued", (r.status_code, r.json().get("queued"), r.json().get("position")), (202, True, 1))
        b = body(P)
        check("[2] running views", (b["status"], b["run_kind"]), ("running", "views"))
        check("[2] every action locked", b["blocked"], {a: outfit_bodies.LOCKED_RUNNING for a in actions})
        cancel = f"/characters/{char}/outfit-bodies/{P}/cancel"
        r = client.post(cancel, json={}, headers=ADMIN)
        check("[2] cancel the waiting one", (r.status_code, r.json().get("cancelled")), (200, 1))
        check("[2] cancel the running one -> 409", client.post(cancel, json={}, headers=ADMIN).status_code, 409)
        time.sleep(0.3)
        check("[2] nothing rendered under the guard", (renders, backs), ([], []))
        with model3d._lock:
            model3d._generating.discard(char)
        check("[2] run ended", wait_for(lambda: not outfit_bodies._active), True)

        # --- [3] ---------------------------------------------------------------------------------------------
        print("[3] the views exist: P is O1's real body")
        check("[3] one front edit", renders, [(f"tpose_{O1}", "outfit_front")])
        check("[3] one back (draft + fit)", backs, [("back", O1)])
        check("[3] no mesh run, no image service", (meshes, image_calls), ([], []))
        check("[3] prediction held", base_body.outfit_body_of_outfit(char, O1), P)
        listed = bodies()
        check("[3] still one body: P", [x["body_id"] for x in listed], [P])
        b = listed[0]
        check("[3] last run", {k: (b["last_run"] or {}).get(k) for k in ("kind", "ok")}, {"kind": "views", "ok": True})
        check("[3] worn_outfit", {k: b["worn_outfit"][k] for k in ("predicted", "views_missing", "image_jobs")},
              {"predicted": False, "views_missing": [], "image_jobs": 0})
        check("[3] blocked views / regenerate", (b["blocked"]["views"], b["blocked"]["regenerate"]),
              (outfit_bodies.WORN_VIEWS_PRESENT, ""))
        check("[3] urls set", [bool(b["view_info"][v]["url"]) for v in ("front", "back")], [True, True])
        r = client.post(url, headers=ADMIN)
        check("[3] again -> 409", (r.status_code, r.json().get("detail")), (409, outfit_bodies.WORN_VIEWS_PRESENT))
        check("[3] regenerate -> 202", client.post(f"/characters/{char}/outfit-bodies/{P}/regenerate",
                                                   headers=ADMIN).status_code, 202)
        check("[3] the mesh run", wait_for(lambda: meshes == [(char, O1, True)]), True)
        wait_for(lambda: not outfit_bodies._active)

        # --- [4] ---------------------------------------------------------------------------------------------
        print("[4] a 3D model job builds P")
        real_stages = model3d.active_stages
        model3d.active_stages = lambda: {"job": (char, P)}
        b = body(P)
        check("[4] running build", (b["status"], b["run_kind"]), ("running", "build"))
        check("[4] every action locked", b["blocked"], {a: outfit_bodies.LOCKED_BUILD for a in actions})
        model3d.active_stages = real_stages

        # --- [5] ---------------------------------------------------------------------------------------------
        print("[5] an orphaned body")
        Q = base_body.outfit_body_id("tex0123456789ab")
        rec = {"body_id": Q, "mode": "mesh", "version": base_body.OUTFIT_BODY_VERSION,
               "texture_signature": "tex0123456789ab", "base_signature": bsig, "built_for": "0000deadbeef",
               "used_views": ["front"], "views": {}}
        png(R / f"tpose_{Q}.png", (5, 5, 5))
        write_json(R / f"tpose_{Q}.json", {"outfit_body": rec})
        listed = bodies()
        check("[5] Q listed after P", [x["body_id"] for x in listed], [P, Q])
        q = listed[1]
        check("[5] Q orphaned", (q["orphaned"], q["status"], q["worn_outfit"]), (True, "missing", None))
        check("[5] Q reasons", (q["blocked"]["regenerate"], q["blocked"]["delete"], q["view_info"]["front"]["blocked"]),
              (outfit_bodies.NO_SOURCE, "", outfit_bodies.NO_SOURCE))
        check("[5] P not orphaned", listed[0]["orphaned"], False)
        check("[5] generate-views on Q -> 404", client.post(f"/characters/{char}/outfit-bodies/{Q}/generate-views",
                                                            headers=ADMIN).status_code, 404)

        # --- [6] ---------------------------------------------------------------------------------------------
        print("[6] nothing worn")
        prof = get_character_profile(char)
        prof["equipped_pieces"] = {}
        assert save_character_profile(char, prof)
        listed = bodies()
        check("[6] only Q, orphaned, no worn entry", [(x["body_id"], x["orphaned"], x["worn_outfit"]) for x in listed],
              [(Q, True, None)])

    print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nOK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
