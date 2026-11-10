#!/usr/bin/env python3
"""Outfit body tab routes (app/routes/outfit_bodies.py, app/core/outfit_bodies.py; plan
docs/superpowers/plans/2026-11-10-outfit-body-mesh-mode.md, Task 4).

Usage:
    ./.venv/bin/python scripts/smoke_outfit_body_routes.py

Throwaway storage + instance directory with a copy of the repo's ``human`` package; the routers
(outfit_bodies + characters, for the model file route) are mounted on a bare FastAPI app with a TestClient and
the session lookup stubbed (header ``x-role``: admin / user / none). No hub, no GPU: ``prepare_outfit_body``,
``rerig_model`` and ``garments.fit_on_body`` are stubs that record their calls; the tsig computation
(``base_body.outfit_body_of_outfit``) is stubbed to the fixture's mapping (Task 1's smokes test the real one).

Fixture (character Demo: humanoid, base-body pipeline on, outfit_body_mode mesh, profile picture; items top {top}
and skirt {bottom} painted, dress {outer} own mesh, all held). bsig = base_signature; T1/T2 = tex111…/tex222…;
B1/B2 = outfit_body_id(T1/T2). Outfits: O1 {top, skirt} WORN on B1, O2 {top, dress} on B2 (model sidecars name
body_id; O2's carries mesh_items.effective [dress]). Body files per Bn: refs tpose[_back]_<Bn> (+.json with the
parent record {body_id, texture_signature Tn, base_signature bsig, version OUTFIT_BODY_VERSION, built_for On,
views = texture_view_shas(On)}), model3d <Bn>.glb/.json (rig mixamo, collision with one capsule), unrigged/ (B1
only), prerig/, rollback/<Bn>/. Base fit Gd of dress (accepted on sha(base glb)); body fits Bd1/Bd2 of dress on
B1/B2 (record accepted, body_sha256 = sha(Bn glb), base_fit_sha256 = sha(Gd fit), fit_version current) + Bd1
layers/ + Bd2 failed/. Texture stores T1/T2 (front view sidecar dress_text "a top and a skirt" / "a top").
O2 also has assembled/ and low/ model files.

Expected, by hand:
[1] GET /characters/Demo/outfit-bodies (admin) -> 200: mode "mesh", pipeline True; body ids {B1, B2}, B1 first (the
    worn outfit stands on it); B1 outfits = [O1, worn True], B2 outfits = [O2, worn False]; O1's name = its piece
    names in alphabetical order "Skirt + Top" (no saved outfit has exactly those pieces); B1 dress_text
    "a top and a skirt"; both freshness "current" (record base = bsig, version current, views = shas of the
    source outfit's dressed views, a current posture record — outfit_body_posture.py); B1 without its posture
    record: freshness "stale", reason POSTURE_NOT_MATCHED; both status "ready"; url names signature=<Bn>; steps non-empty (first row
    = the parent record, id "outfit_body", model_overview.outfit_body_steps); collision capsules 1; B1 can_rerig
    True, B2 False; regenerate_from On; B1 fits = [dress: accepted]; B2 fits = [dress: accepted] (its failure
    record is of another fit version, so it does not hold — garment_store.body_failure).
    View route views/front of B1 -> 200 with the planted bytes; views/front of "nonsense" -> 404.
[2] Auth: user -> 403 on GET list, POST regenerate, POST delete, GET view; anonymous -> 401.
    The model file route serves B1 to an admin (200, bytes of B1's glb), 403 to a user, 404 for an id with no
    model ("ob00000000").
[3] Queue: model3d's generation guard held by another run -> POST regenerate B1 = 202 {started True, queued
    False, position 0}; the stub is NOT called while the guard is held (0.4 s); GET shows B1 status "running"
    (the worker took it) and generation_running True. POST regenerate B2 = 202 {started False, queued True,
    position 1, behind {kind regenerate, body_id B1}}; posting it again does not add it twice (position 1,
    waiting length 1). POST delete B1 -> 409 (a run on it). Guard released, stub released -> prepare_outfit_body
    called (Demo, O1, rebuild=True) then (Demo, O2, rebuild=True); last_run ok.
[4] Re-rig: B2 (no unrigged mesh) -> 409; B1 -> 202, rerig_model called with (Demo, B1).
[5] Refit: POST refit B1 -> fit_on_body called once for (dress, body_id B1); POST refit B1 {item_id: "nope"} ->
    400; {item_id: dress} -> one more call.
[6] Delete B2 -> 200; filesystem walk of model3d/ model_refs/ garments/: every file whose path names B2 is gone
    (0 left), O2's model files (model3d/<O2>.glb/.json, low/, assembled/, assembled/low/) are gone, everything
    else stays exactly (B1, Bd1, Gd, O1, O1/O2 refs, T1, T2, base).
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


def touch(path: Path, data=b"x" * 16) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())
    return path


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="outfit-body-routes-") as tmp:
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
        from app.core import auth_dependency, base_body, garment_fit, garment_store as gs, garments, model3d
        from app.core import outfit_bodies
        from app.core.outfit_body_posture import POSTURE_MATCH_VERSION
        from app.core.model_refs import mesh_items_token, mesh_signature, mesh_variant
        from app.models import inventory
        from app.models.character import get_character_dir, get_character_images_dir, get_character_profile, \
            save_character_profile
        from app.routes import characters as characters_routes, outfit_bodies as outfit_bodies_routes
        from app.core import glb_delivery
        glb_delivery.delivery_path = lambda path, **kw: path   # no Blender meshopt copy of the fake GLBs

        users = {"admin": {"id": "a", "username": "admin", "role": "admin"},
                 "user": {"id": "u", "username": "player", "role": "user", "allowed_characters": ["Demo"]}}
        auth_dependency._get_session_user = lambda request: users.get(request.headers.get("x-role", ""))
        app = FastAPI()
        app.include_router(characters_routes.router)
        app.include_router(outfit_bodies_routes.router)
        client = TestClient(app)
        ADMIN, USER = {"x-role": "admin"}, {"x-role": "user"}

        char = "Demo"
        T1, T2 = "tex111111111111", "tex222222222222"
        B1, B2 = base_body.outfit_body_id(T1), base_body.outfit_body_id(T2)
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender", "outfit_body_mode": "mesh"}
        assert save_character_profile(char, human, create_new=True)
        touch(get_character_images_dir(char) / f"{char}_1.png", b"\x89PNG" + b"demo" * 8)
        prof = get_character_profile(char)
        prof["profile_image"] = f"{char}_1.png"
        assert save_character_profile(char, prof)
        assert base_body.set_pipeline(char, True)
        ids = {}
        for key, slots, own in (("top", ["top"], False), ("skirt", ["bottom"], False), ("dress", ["outer"], True)):
            op = {"slots": slots, "covers": [], "outfit_types": ["casual"], "own_mesh": own}
            ids[key] = inventory.add_item(name=f"{key.title()}", category="outfit_piece", item_id=key,
                                          prompt_fragment=f"a {key}", outfit_piece=op)["id"]
            inventory.add_to_inventory(char, ids[key])
        outfits = {"O1": {"top": "top", "bottom": "skirt"}, "O2": {"top": "top", "outer": "dress"}}
        prof = get_character_profile(char)
        prof["equipped_pieces"] = dict(outfits["O1"])
        assert save_character_profile(char, prof)
        cdir = get_character_dir(char)
        M, R = cdir / "model3d", cdir / "model_refs"
        bsig = base_body.base_signature(char)
        base_glb = b"BASE-GLB-demo"
        base_front = touch(R / f"tpose_{bsig}.png", b"base-front")
        touch(R / f"tpose_{bsig}.json", {"base_signature": bsig})
        base_back = touch(R / f"tpose_back_{bsig}.png", b"base-back")
        touch(R / f"tpose_back_{bsig}.json", {"base_signature": bsig})
        touch(M / f"{bsig}.glb", base_glb)
        touch(M / f"{bsig}.json", {"base": True, "rig": "mixamo"})
        base_sha = hashlib.sha256(base_glb).hexdigest()
        sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()  # noqa: E731
        sigs, tex_of, body_of = {}, {"O1": T1, "O2": T2}, {"O1": B1, "O2": B2}
        for name, pieces in outfits.items():
            variant, token = mesh_variant(char, pieces), mesh_items_token(char, pieces)
            sig = mesh_signature(pieces, [], char, variant, token)
            sigs[name] = sig
            for kind, base_view in (("tpose", base_front), ("tpose_back", base_back)):
                touch(R / f"{kind}_{sig}.png", f"{name}-{kind}".encode())
                touch(R / f"{kind}_{sig}.json", {"equipped_pieces": pieces, "equipped_items": [],
                                                 "mesh_variant": variant, "mesh_token": token,
                                                 "base_signature": bsig, "base_image_sha256": sha(base_view),
                                                 "texture_signature": tex_of[name]})
        O1, O2 = sigs["O1"], sigs["O2"]
        dress = "dress"
        fd = gs.garment_fsig(char, dress)
        gd_fit = touch(gs.garment_path(char, dress, fd, "fit"), b"GD-FIT")
        touch(gd_fit.with_suffix(".json"), {"accepted": True, "kind": "clothing", "base_model_sha256": base_sha,
                                            "body_id": bsig, "base_signature": bsig, "item_id": dress, "fsig": fd})
        touch(gs.garment_path(char, dress, fd, "prepared"))
        for t, text in ((T1, "a top and a skirt"), (T2, "a top")):
            tm = {"base_signature": bsig, "texture_signature": t}
            touch(R / "texture" / f"tpose_{t}.png", f"tex-{t}".encode())
            touch(R / "texture" / f"tpose_{t}.json", {**tm, "dress_text": text})
            touch(M / "texture" / f"{t}.glb")
            touch(M / "texture" / f"{t}.json", tm)
        capsule = {"version": 1, "capsules": [{"bone": "Spine", "radius": 0.1}], "skipped": [], "scales": {}}
        for name in ("O1", "O2"):
            b, t = body_of[name], tex_of[name]
            rec = {"body_id": b, "mode": "mesh", "version": base_body.OUTFIT_BODY_VERSION, "texture_signature": t,
                   "base_signature": bsig, "built_for": sigs[name], "used_views": ["front", "back"],
                   "views": base_body.texture_view_shas(char, sigs[name], bsig)}
            touch(R / f"tpose_{b}.png", f"{b}-front".encode())
            touch(R / f"tpose_{b}.json", {"outfit_body": rec})
            touch(R / f"tpose_back_{b}.png", f"{b}-back".encode())
            touch(R / f"tpose_back_{b}.json", {"outfit_body": rec})
            body_glb = touch(M / f"{b}.glb", f"BODY-{b}".encode())
            touch(M / f"{b}.json", {"outfit_body": rec, "rig": "mixamo", "created_at": "2026-11-10T10:00:00+00:00",
                                    "collision": capsule,
                                    # matched to the stored base (outfit_body_posture.py): no posture run here
                                    "blender": {"posture_match": {"version": POSTURE_MATCH_VERSION,
                                                                  "base_signature": bsig, "base_sha256": base_sha,
                                                                  "status": "applied", "error": ""}}})
            if name == "O1":
                touch(M / "unrigged" / f"{b}.glb")
                touch(M / "unrigged" / f"{b}.json", {"outfit_body": rec})
            touch(M / "prerig" / f"{b}.glb")
            touch(M / "prerig" / f"{b}.json", {"outfit_body": rec})
            touch(M / "rollback" / b / f"{b}.glb")
            mmeta = {"pieces": outfits[name], "items": [], "base_signature": bsig, "base_model_sha256": base_sha,
                     "texture_signature": t, "outfit_body_mode": "mesh", "body_id": b, "body_sha256": sha(body_glb),
                     "rig": "mixamo", "source": "base_body", "dressed": True,
                     "mesh_items": {"effective": [dress]} if name == "O2" else {}}
            touch(M / f"{sigs[name]}.glb", f"OUTFIT-{name}".encode())
            touch(M / f"{sigs[name]}.json", mmeta)
            if name == "O2":
                for sub in ("low", "assembled", "assembled/low"):
                    touch(M / sub / f"{sigs[name]}.glb")
                    touch(M / sub / f"{sigs[name]}.json", {})
            frec = {"accepted": True, "kind": "clothing", "item_id": dress, "fsig": fd, "body_id": b,
                    "body_sha256": sha(body_glb), "base_signature": bsig, "base_fit_sha256": sha(gd_fit),
                    "fit_version": garment_fit.FIT_VERSION.get("clothing"), "created_at": "2026-11-10T11:00:00+00:00"}
            fit = touch(gs.garment_path(char, dress, fd, "fit", body=b))
            touch(fit.with_suffix(".json"), frec)
            touch(gs.garment_path(char, dress, fd, "low", body=b))
        touch(gs.garment_path(char, dress, fd, "layer", lsig="abcdefabcdef", body=B1))
        touch(gs.garment_path(char, dress, fd, "failed", body=B2), {"error": "too tight", "fit_version": -1})

        def walk():
            return {p.relative_to(cdir).as_posix() for d in ("model3d", "model_refs", "garments")
                    if (cdir / d).is_dir() for p in (cdir / d).rglob("*") if p.is_file()}

        # The tsig computation of an outfit -> its body (Task 1's smokes test the real one).
        base_body.outfit_body_of_outfit = lambda c, s, profile=None: {O1: B1, O2: B2}.get(s, "")

        # --- [1] list ---------------------------------------------------------------------------------
        print("[1] list")
        r = client.get(f"/characters/{char}/outfit-bodies", headers=ADMIN)
        check("[1] status", r.status_code, 200)
        data = r.json()
        check("[1] mode / pipeline", (data["mode"], data["pipeline"]), ("mesh", True))
        bodies = {b["body_id"]: b for b in data["bodies"]}
        check("[1] body ids, worn body first", [b["body_id"] for b in data["bodies"]], [B1, B2])
        check("[1] B1 outfits", [(o["signature"], o["worn"]) for o in bodies[B1]["outfits"]], [(O1, True)])
        check("[1] B2 outfits", [(o["signature"], o["worn"]) for o in bodies[B2]["outfits"]], [(O2, False)])
        check("[1] outfit name from the pieces", bodies[B1]["outfits"][0]["name"], "Skirt + Top")
        check("[1] B1 dress text", bodies[B1]["dress_text"], "a top and a skirt")
        check("[1] freshness", [bodies[b]["freshness"]["state"] for b in (B1, B2)], ["current", "current"])
        b1_meta = M / f"{B1}.json"
        kept = b1_meta.read_text()
        b1_meta.write_text(json.dumps({k: v for k, v in json.loads(kept).items() if k != "blender"}))
        unmatched = next(b for b in client.get(f"/characters/{char}/outfit-bodies", headers=ADMIN).json()["bodies"]
                         if b["body_id"] == B1)
        check("[1] no posture record -> stale, named", (unmatched["freshness"]["state"],
                                                        unmatched["freshness"]["reason"]),
              ("stale", outfit_bodies.POSTURE_NOT_MATCHED))
        b1_meta.write_text(kept)
        check("[1] status", [bodies[b]["status"] for b in (B1, B2)], ["ready", "ready"])
        check("[1] url names the body", f"signature={B1}" in (bodies[B1]["url"] or ""), True)
        check("[1] steps start with the parent", (bodies[B1]["steps"] or [{}])[0].get("id"), "outfit_body")
        check("[1] collision capsules", len((bodies[B1]["collision"] or {}).get("capsules") or []), 1)
        check("[1] can_rerig", (bodies[B1]["can_rerig"], bodies[B2]["can_rerig"]), (True, False))
        check("[1] can_regenerate", (bodies[B1]["regenerate_from"], bodies[B2]["regenerate_from"]), (O1, O2))
        check("[1] B1 fits", [(f["item_id"], f["status"]) for f in bodies[B1]["fits"]], [(dress, "accepted")])
        check("[1] B2 fits", [(f["item_id"], f["status"]) for f in bodies[B2]["fits"]], [(dress, "accepted")])
        check("[1] views: front + back, no sides", {v: bool(u) for v, u in bodies[B1]["views"].items()},
              {"front": True, "back": True, "left": False, "right": False})
        r = client.get(bodies[B1]["views"]["front"], headers=ADMIN)
        check("[1] view route", (r.status_code, r.content), (200, f"{B1}-front".encode()))
        check("[1] view of a nonsense key", client.get(f"/characters/{char}/outfit-bodies/nonsense/views/front",
                                                         headers=ADMIN).status_code, 404)

        # --- [2] auth ---------------------------------------------------------------------------------
        print("[2] auth")
        for method, url in (("get", f"/characters/{char}/outfit-bodies"),
                            ("post", f"/characters/{char}/outfit-bodies/{B1}/regenerate"),
                            ("post", f"/characters/{char}/outfit-bodies/{B1}/delete"),
                            ("get", f"/characters/{char}/outfit-bodies/{B1}/views/front")):
            check(f"[2] user {method.upper()} {url.rsplit('/', 1)[-1]}", getattr(client, method)(url, headers=USER)
                  .status_code, 403)
            check(f"[2] anonymous {method.upper()} {url.rsplit('/', 1)[-1]}", getattr(client, method)(url)
                  .status_code, 401)
        r = client.get(f"/characters/{char}/model3d/file?signature={B1}", headers=ADMIN)
        check("[2] model file of the body (admin)", (r.status_code, r.content), (200, f"BODY-{B1}".encode()))
        check("[2] model file of the body (user)", client.get(f"/characters/{char}/model3d/file?signature={B1}",
                                                              headers=USER).status_code, 403)
        check("[2] model file of an absent body", client.get(f"/characters/{char}/model3d/file?signature=ob00000000",
                                                             headers=ADMIN).status_code, 404)

        # --- [3] queue ----------------------------------------------------------------------------------
        print("[3] queue")
        calls, gate = [], threading.Event()
        entered = threading.Event()

        def fake_prepare(c, signature=None, *, force=False, rebuild=False):
            calls.append((c, signature, rebuild))
            entered.set()
            gate.wait(10)
            return {"ok": True, "cached": False, "body_id": {O1: B1, O2: B2}[signature]}
        base_body.prepare_outfit_body = fake_prepare
        with model3d._lock:
            model3d._generating.add(char)   # another 3D run of the character holds the guard
        r = client.post(f"/characters/{char}/outfit-bodies/{B1}/regenerate", headers=ADMIN)
        check("[3] regenerate B1 answer", (r.status_code, {k: r.json().get(k) for k in ("started", "queued", "position")}),
              (202, {"started": True, "queued": False, "position": 0}))
        time.sleep(0.4)
        check("[3] waits for the guard", calls, [])
        info = client.get(f"/characters/{char}/outfit-bodies", headers=ADMIN).json()
        check("[3] B1 running, guard reported", (next(b for b in info["bodies"] if b["body_id"] == B1)["status"],
                                                 info["generation_running"]), ("running", True))
        r = client.post(f"/characters/{char}/outfit-bodies/{B2}/regenerate", headers=ADMIN)
        check("[3] regenerate B2 queued", (r.status_code, {k: r.json().get(k) for k in
                                                           ("started", "queued", "position", "behind")}),
              (202, {"started": False, "queued": True, "position": 1,
                     "behind": {"kind": "regenerate", "body_id": B1}}))
        r = client.post(f"/characters/{char}/outfit-bodies/{B2}/regenerate", headers=ADMIN)
        check("[3] not added twice", (r.json().get("position"), len(outfit_bodies.queue_state(char)["waiting"])),
              (1, 1))
        info = client.get(f"/characters/{char}/outfit-bodies", headers=ADMIN).json()
        b2 = next(b for b in info["bodies"] if b["body_id"] == B2)
        check("[3] B2 queued", (b2["status"], b2["queue_position"]), ("queued", 1))
        check("[3] delete of a body with a run -> 409",
              client.post(f"/characters/{char}/outfit-bodies/{B1}/delete", headers=ADMIN).status_code, 409)
        with model3d._lock:
            model3d._generating.discard(char)
        check("[3] stub entered after the guard", entered.wait(5), True)
        gate.set()
        check("[3] both ran", wait_for(lambda: len(calls) == 2 and not outfit_bodies.queue_state(char)["running"]),
              True)
        check("[3] calls", calls, [(char, O1, True), (char, O2, True)])
        info = client.get(f"/characters/{char}/outfit-bodies", headers=ADMIN).json()
        check("[3] last run ok", next(b for b in info["bodies"] if b["body_id"] == B1)["last_run"]["ok"], True)
        check("[3] guard free again", model3d.generation_running(char), False)

        # --- [4] re-rig ---------------------------------------------------------------------------------
        print("[4] re-rig")
        rerigs = []
        model3d.rerig_model = lambda c, s=None, **kw: rerigs.append((c, s)) or {"ok": True}
        check("[4] B2 without unrigged -> 409",
              client.post(f"/characters/{char}/outfit-bodies/{B2}/rerig", headers=ADMIN).status_code, 409)
        check("[4] B1 -> 202", client.post(f"/characters/{char}/outfit-bodies/{B1}/rerig", headers=ADMIN)
              .status_code, 202)
        check("[4] rerig called", wait_for(lambda: rerigs == [(char, B1)]), True)

        # --- [5] refit ----------------------------------------------------------------------------------
        print("[5] refit")
        fits = []
        garments.fit_on_body = lambda c, item, *, body_id, base_fit, profile=None, schedule=True: (
            fits.append((item, body_id, Path(base_fit[0]).name)) or Path(base_fit[0]))
        wait_for(lambda: not outfit_bodies.queue_state(char)["running"])
        check("[5] refit all -> 202", client.post(f"/characters/{char}/outfit-bodies/{B1}/refit", headers=ADMIN)
              .status_code, 202)
        check("[5] fit_on_body (dress on B1, from the base fit)", wait_for(lambda: len(fits) == 1) and fits,
              [(dress, B1, gd_fit.name)])
        check("[5] unknown item -> 400", client.post(f"/characters/{char}/outfit-bodies/{B1}/refit",
                                                     json={"item_id": "nope"}, headers=ADMIN).status_code, 400)
        wait_for(lambda: not outfit_bodies.queue_state(char)["running"])
        check("[5] one item -> 202", client.post(f"/characters/{char}/outfit-bodies/{B1}/refit",
                                                 json={"item_id": dress}, headers=ADMIN).status_code, 202)
        check("[5] one more call", wait_for(lambda: len(fits) == 2), True)
        wait_for(lambda: not outfit_bodies.queue_state(char)["running"])

        # --- [6] delete ---------------------------------------------------------------------------------
        print("[6] delete")
        before = walk()
        o2_models = {f"model3d/{O2}.glb", f"model3d/{O2}.json"} | {
            f"model3d/{sub}/{O2}.{e}" for sub in ("low", "assembled", "assembled/low") for e in ("glb", "json")}
        names_b2 = {p for p in before if B2 in p}
        check("[6] fixture has B2 files", len(names_b2) > 10, True)
        r = client.post(f"/characters/{char}/outfit-bodies/{B2}/delete", headers=ADMIN)
        check("[6] delete -> 200", r.status_code, 200)
        after = walk()
        check("[6] nothing of B2 left", sorted(p for p in after if B2 in p), [])
        check("[6] O2 outfit models gone", sorted(after & o2_models), [])
        check("[6] everything else kept", sorted((before - names_b2 - o2_models) ^ after), [])
        check("[6] B1 and its fit kept", (f"model3d/{B1}.glb" in after,
                                          f"garments/bodies/{B1}/{dress}_{fd}.glb" in after), (True, True))
        check("[6] report lists the chain", sorted({e["kind"] for e in r.json()["deleted"]}),
              ["body", "body_fit", "outfit"])
        info = client.get(f"/characters/{char}/outfit-bodies", headers=ADMIN).json()
        check("[6] list without B2", [b["body_id"] for b in info["bodies"]], [B1])

    print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nOK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
