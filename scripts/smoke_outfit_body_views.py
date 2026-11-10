#!/usr/bin/env python3
"""Outfit body tab — per-view freshness and the per-view Regenerate run
(app/core/outfit_bodies.py ``view_infos`` / ``view_blocked`` / ``render_view``,
app/core/model_overview.py ``outfit_body_view_freshness``,
``POST /characters/{c}/outfit-bodies/{body}/views/{view}/regenerate``,
``POST …/{body}/cancel {view}``).

Usage:
    ./.venv/bin/python scripts/smoke_outfit_body_views.py

Throwaway storage + instance directory with a copy of the repo's ``human`` package; the outfit_bodies router on a
bare FastAPI app with a TestClient, session lookup stubbed (header ``x-role``: admin / user / none). No hub, no
GPU: ``expression_regen.render_character_image`` is a recorder that writes a PNG + sidecar (one call = one image
job), ``base_body.prepare_outfit_body`` a recorder (one call = one mesh run). The tsig and body id are the real
ones (``base_body._outfit_texture`` of the outfit's dressed front), so ``source_outfit`` is not stubbed.

Fixture (character Demo: humanoid, pipeline on, outfit_body_mode mesh, side views off = the default). Items top
{top} and skirt {bottom}, painted. Base views front/back (PNG) of bsig, base model. Outfit O1 {top, skirt} WORN:
dressed front + back made from the current base views (sidecar base_signature = bsig, base_image_sha256 = sha of
the base view, dress_text = TEXTS[view]), the back's draft (front_sha256 = sha of O1's front) — TEXTS = the dress
texts ``_outfit_texture`` computes for O1 at fixture time ("the render"). T = its tsig, B = outfit_body_id(T). The
texture store holds exact copies of O1's views and draft under T (what ``_store_texture_views`` publishes). Body
B: refs tpose[_back]_<B> + model3d/<B>.glb with the parent record {views = texture_view_shas(O1)}.

Expected, by hand:
[1] GET (admin) -> B's view_info has front + back (side views off, no side image) and no left/right; both
    urls serve the STORE copies (key T); front and back freshness "current" (base provenance matches, recorded
    text = text now, back's draft follows the store front); blocked "" for both; status "".
    Body freshness "current".
[2] Base back re-rendered (bytes changed): back -> stale "Made from an older base view"; front stays current;
    blocked still "" (the back's base view exists, O1's front is current). Restored afterwards.
[3] Blocked / bad requests: POST views/left/regenerate -> 409 with base_body.SIDE_VIEW_NOT_DRESSED (side views
    off); views/bogus -> 400; user -> 403, anonymous -> 401 (regenerate and cancel).
[4] Queue + cancel: another 3D run holds the generation guard. POST views/front -> 202 started True (the worker
    took it, waits for the guard; recorder not called after 0.4 s); POST views/back -> 202 queued position 1;
    GET: back status "queued" queue_position 1, front "running". cancel {view: back} -> 200 cancelled 1; again ->
    404; cancel {view: front} -> 409 (running). Guard released -> the front run ends.
[5] Exactly ONE image job (render recorder called once: output_stem tpose_<O1>, occasion outfit_front), ZERO mesh
    runs; last_run {kind view, view front, ok True}. GET: front url changed and freshness "current" (the render
    recorded the current base front and the dress text); back stale "Made from an older dressed front" (its
    draft names the old front — no cascade, the back was not rendered); body freshness stale with reason
    "Dressed views changed" (its record names the old view shas).
[6] The mesh step is its own explicit run: POST regenerate -> prepare_outfit_body called once (Demo, O1,
    rebuild=True), still no further image job.
[7] Dress text changed: the skirt's prompt fragment is edited -> O1 now stands on another texture, so B has no
    source: front and back freshness carry "Dress text changed", both blocked = outfit_bodies.NO_SOURCE, POST
    views/front -> 409 NO_SOURCE.
"""
import hashlib
import json
import os
import shutil
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
    with tempfile.TemporaryDirectory(prefix="outfit-body-views-") as tmp:
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
        from app.core.model_overview import DRESS_TEXT_CHANGED, OLDER_BASE_VIEW, OLDER_DRESSED_FRONT
        from app.core.model_refs import mesh_items_token, mesh_signature, mesh_variant
        from app.models import inventory
        from app.models.character import get_character_dir, get_character_images_dir, get_character_profile, \
            save_character_profile
        from app.routes import outfit_bodies as outfit_bodies_routes
        from app.core import glb_delivery
        glb_delivery.delivery_path = lambda path, **kw: path   # no Blender meshopt copy of the fake GLBs

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

        variant, token = mesh_variant(char, pieces), mesh_items_token(char, pieces)
        O1 = mesh_signature(pieces, [], char, variant, token)
        manifest = {"equipped_pieces": pieces, "equipped_items": [], "mesh_variant": variant,
                    "base_signature": bsig, "dressed": True}
        o1_front = png(R / f"tpose_{O1}.png", (100, 0, 0))
        write_json(o1_front.with_suffix(".json"), {**manifest, "base_image_sha256": sha(base_views["front"])})
        texture = base_body._outfit_texture(char, o1_front, bsig=bsig, profile=prof)
        T, TEXTS = texture["tsig"], texture["inputs"]["dress_text"]
        B = base_body.outfit_body_id(T)
        write_json(o1_front.with_suffix(".json"), {**manifest, "base_image_sha256": sha(base_views["front"]),
                                                   "texture_signature": T, "dress_text": TEXTS["front"]})
        o1_draft = png(R / "drafts" / f"tpose_back_{O1}.png", (0, 100, 0))
        write_json(o1_draft.with_suffix(".json"), {**manifest, "back_draft": True, "front_sha256": sha(o1_front),
                                                   "texture_signature": T})
        o1_back = png(R / f"tpose_back_{O1}.png", (0, 0, 100))
        write_json(o1_back.with_suffix(".json"), {**manifest, "base_image_sha256": sha(base_views["back"]),
                                                  "back_draft": o1_draft.name, "back_draft_sha256": sha(o1_draft),
                                                  "texture_signature": T, "dress_text": TEXTS.get("back", "")})
        # The texture store: exact copies, the outfit's own keys dropped (base_body._store_texture_views).
        base_body._store_texture_views(char, O1, T, ["front", "back"], TEXTS)
        check("fixture: O1 stands on B", base_body.outfit_body_of_outfit(char, O1), B)
        rec = {"body_id": B, "mode": "mesh", "version": base_body.OUTFIT_BODY_VERSION, "texture_signature": T,
               "base_signature": bsig, "built_for": O1, "used_views": ["front", "back"],
               "views": base_body.texture_view_shas(char, O1, bsig)}
        for kind, colour in (("tpose", (1, 1, 1)), ("tpose_back", (2, 2, 2))):
            png(R / f"{kind}_{B}.png", colour)
            write_json(R / f"{kind}_{B}.json", {"outfit_body": rec})
        (M / f"{B}.glb").write_bytes(b"BODY-GLB")
        write_json(M / f"{B}.json", {"outfit_body": rec, "rig": "mixamo", "created_at": "2026-11-10T10:00:00+00:00"})
        write_json(M / f"{O1}.json", {"pieces": pieces, "items": [], "base_signature": bsig,
                                      "texture_signature": T, "outfit_body_mode": "mesh", "body_id": B,
                                      "body_sha256": sha(M / f"{B}.glb"), "rig": "mixamo",
                                      "source": "base_body", "dressed": True})
        (M / f"{O1}.glb").write_bytes(b"OUTFIT")
        # No posture record: the body would be stale for POSTURE_NOT_MATCHED, which is not this smoke's topic.
        outfit_bodies.stale_posture = lambda c, meta: ""

        renders, meshes = [], []

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

        def fake_prepare(c, signature=None, *, force=False, rebuild=False):
            meshes.append((c, signature, rebuild))
            return {"ok": True, "cached": False, "body_id": B}
        base_body.prepare_outfit_body = fake_prepare

        def body():
            data = client.get(f"/characters/{char}/outfit-bodies", headers=ADMIN).json()
            return next(b for b in data["bodies"] if b["body_id"] == B)

        def fresh(b, v):
            f = ((b["view_info"][v] or {}).get("meta") or {}).get("freshness") or {}
            return f.get("state"), f.get("reason") or ""

        # --- [1] ---------------------------------------------------------------------------------------------
        print("[1] views of the body")
        b = body()
        check("[1] views listed", sorted(b["view_info"]), ["back", "front"])
        check("[1] urls name the texture store", [f"/outfit-bodies/{T}/views/{v}?" in (b["view_info"][v]["url"] or "")
                                                  for v in ("front", "back")], [True, True])
        r = client.get(b["view_info"]["front"]["url"], headers=ADMIN)
        check("[1] front url serves the store copy", (r.status_code, r.content),
              (200, base_body._texture_view(char, "front", T).read_bytes()))
        check("[1] front fresh", fresh(b, "front"), ("current", ""))
        check("[1] back fresh", fresh(b, "back"), ("current", ""))
        check("[1] blocked", [b["view_info"][v]["blocked"] for v in ("front", "back")], ["", ""])
        check("[1] status", [b["view_info"][v]["status"] for v in ("front", "back")], ["", ""])
        check("[1] body fresh", b["freshness"]["state"], "current")

        # --- [2] ---------------------------------------------------------------------------------------------
        print("[2] base back re-rendered")
        kept = base_views["back"].read_bytes()
        png(base_views["back"], (30, 30, 30))
        b = body()
        check("[2] back stale: older base view", fresh(b, "back"), ("stale", OLDER_BASE_VIEW))
        check("[2] front current", fresh(b, "front"), ("current", ""))
        check("[2] back still renderable", b["view_info"]["back"]["blocked"], "")
        base_views["back"].write_bytes(kept)

        # --- [3] ---------------------------------------------------------------------------------------------
        print("[3] blocked / bad requests / auth")
        r = client.post(f"/characters/{char}/outfit-bodies/{B}/views/left/regenerate", headers=ADMIN)
        check("[3] side view off -> 409", (r.status_code, r.json().get("detail")),
              (409, base_body.SIDE_VIEW_NOT_DRESSED))
        check("[3] unknown view -> 400", client.post(f"/characters/{char}/outfit-bodies/{B}/views/bogus/regenerate",
                                                     headers=ADMIN).status_code, 400)
        for url, payload in ((f"/characters/{char}/outfit-bodies/{B}/views/front/regenerate", None),
                             (f"/characters/{char}/outfit-bodies/{B}/cancel", {"view": "front"})):
            check(f"[3] user {url.rsplit('/', 2)[-2:]}", client.post(url, json=payload, headers=USER).status_code, 403)
            check(f"[3] anonymous {url.rsplit('/', 2)[-2:]}", client.post(url, json=payload).status_code, 401)
        check("[3] nothing rendered", renders, [])

        # --- [4] ---------------------------------------------------------------------------------------------
        print("[4] queue + cancel")
        with model3d._lock:
            model3d._generating.add(char)   # another 3D run of the character holds the guard
        r = client.post(f"/characters/{char}/outfit-bodies/{B}/views/front/regenerate", headers=ADMIN)
        check("[4] front answer", (r.status_code, {k: r.json().get(k) for k in ("kind", "view", "started", "queued")}),
              (202, {"kind": "view", "view": "front", "started": True, "queued": False}))
        time.sleep(0.4)
        check("[4] waits for the guard", renders, [])
        r = client.post(f"/characters/{char}/outfit-bodies/{B}/views/back/regenerate", headers=ADMIN)
        check("[4] back queued", (r.status_code, r.json().get("queued"), r.json().get("position")), (202, True, 1))
        b = body()
        check("[4] view states", ((b["view_info"]["front"]["status"]), b["view_info"]["back"]["status"],
                                  b["view_info"]["back"]["queue_position"]), ("running", "queued", 1))
        r = client.post(f"/characters/{char}/outfit-bodies/{B}/cancel", json={"view": "back"}, headers=ADMIN)
        check("[4] cancel back", (r.status_code, r.json().get("cancelled")), (200, 1))
        check("[4] cancel back again -> 404", client.post(f"/characters/{char}/outfit-bodies/{B}/cancel",
                                                          json={"view": "back"}, headers=ADMIN).status_code, 404)
        check("[4] cancel the running front -> 409", client.post(f"/characters/{char}/outfit-bodies/{B}/cancel",
                                                                 json={"view": "front"}, headers=ADMIN).status_code,
              409)
        old_front_url = b["view_info"]["front"]["url"]
        with model3d._lock:
            model3d._generating.discard(char)
        check("[4] run ended", wait_for(lambda: not outfit_bodies._active), True)

        # --- [5] ---------------------------------------------------------------------------------------------
        print("[5] one image job, back and body stale, no cascade")
        check("[5] exactly one image job", renders, [(f"tpose_{O1}", "outfit_front")])
        check("[5] no mesh run", meshes, [])
        b = body()
        check("[5] last run", {k: (b["last_run"] or {}).get(k) for k in ("kind", "view", "ok")},
              {"kind": "view", "view": "front", "ok": True})
        check("[5] front url changed", b["view_info"]["front"]["url"] != old_front_url, True)
        check("[5] front fresh", fresh(b, "front"), ("current", ""))
        check("[5] back stale: older dressed front", fresh(b, "back"), ("stale", OLDER_DRESSED_FRONT))
        check("[5] body stale: dressed views changed", (b["freshness"]["state"], b["freshness"]["reason"]),
              ("stale", outfit_bodies.DRESSED_VIEWS_CHANGED))

        # --- [6] ---------------------------------------------------------------------------------------------
        print("[6] the mesh is its own run")
        check("[6] regenerate -> 202", client.post(f"/characters/{char}/outfit-bodies/{B}/regenerate",
                                                   headers=ADMIN).status_code, 202)
        check("[6] mesh run", wait_for(lambda: meshes == [(char, O1, True)]), True)
        wait_for(lambda: not outfit_bodies._active)
        check("[6] no further image job", len(renders), 1)

        # --- [7] ---------------------------------------------------------------------------------------------
        print("[7] dress text changed")
        # The edit's render purge is not this smoke's topic (it would drop O1's views and the body files).
        inventory._invalidate_renders_for_item = lambda item_id: None
        inventory.update_item("skirt", {"prompt_fragment": "a long pleated skirt in dark green"})
        b = body()
        check("[7] front: dress text changed", DRESS_TEXT_CHANGED in fresh(b, "front")[1], True)
        check("[7] back: dress text changed", DRESS_TEXT_CHANGED in fresh(b, "back")[1], True)
        check("[7] blocked: no source", [b["view_info"][v]["blocked"] for v in ("front", "back")],
              [outfit_bodies.NO_SOURCE] * 2)
        r = client.post(f"/characters/{char}/outfit-bodies/{B}/views/front/regenerate", headers=ADMIN)
        check("[7] regenerate -> 409", (r.status_code, r.json().get("detail")), (409, outfit_bodies.NO_SOURCE))

    print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nOK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
