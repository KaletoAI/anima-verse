#!/usr/bin/env python3
"""The Hair tab chooses the hair method (plan
docs/superpowers/plans/2026-11-09-hairdeck-hair.md, Task 5): the routes
POST /characters/{n}/hair/method, POST /characters/{n}/hair/colour,
GET /characters/{n}/garments/{item}/hairdeck/{image}, the ``method`` query of
the garment model route and the new keys of GET /characters/{n}/hair
(method, method_source, world_method, hairdeck, other, limits.hairdeck_fit).

Usage:
    ./.venv/bin/python scripts/smoke_hair_tab_method.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no GPU, no Blender, no
server process. The characters router is mounted on a bare FastAPI app with
real sessions (pattern of smoke_garment_routes.py). The fixture body, base
views and base model are those of scripts/smoke_garment_chain.py (imported).
Stubs (as in smoke_garment_hairdeck_chain.py): the image service
(``generate_hair`` = recorder writing the seven files of a HairDeck job, its
``info.json`` with hair_color [0.4980392156862745, 0.3843137254901961,
0.2823529411764706] — the spike job's value; ``pool`` = one img2hair backend
"HairDeck"), ``garment_hairdeck.fit_hairdeck`` (recorder, always accepted),
``refine.decimate_to`` (copies) and ``garment_assembly.schedule`` (recorder).
The chain (``start_garment`` -> ``run_garment``), the fingerprints, the fit
records and the serving are REAL.

EXPECTED VALUES, DERIVED BY HAND FROM THE TASK BRIEF AND THE RULINGS
[1] Player session: POST /hair/method, POST /hair/colour, the HairDeck image
    route and the model route with ?method= answer 403; nothing is stored.
[2] GET /hair before any item: method "edit_chain", method_source "world",
    world_method "edit_chain" (schema default), hairdeck None, other None;
    limits.hairdeck_fit = the HairDeck gate constants as "le" chips:
    max_push_m 0.12, moved_share 0.90, icp_resid_p95_m 0.012.
[3] Method: "bogus" -> 400, profile key absent; "hairdeck" -> 200 {method
    "hairdeck", method_source "character"}, profile hair_method "hairdeck",
    one assembly schedule (the served hair follows the method); GET says
    the same. "" -> {edit_chain, world} (falls back to the world), profile
    "". The world set to "hairdeck": "" -> {hairdeck, world}, GET
    world_method "hairdeck". World back to absent, character "hairdeck".
[4] Colour: "#12345", "red", "#GGGGGG", "ff8000" -> 400 each; the profile
    key hair_colour stays absent.
[5] POST /hair (creates + wears "hair_demo", starts the REAL chain): ran
    hairdeck + fit -> generate_hair 1 call (seed 42), fit 1 call with
    colour_target None. GET: garment.method "hairdeck", served_fsig = the
    current fsig F1, garment.fit accepted; hairdeck.status "accepted",
    attempt 1, seed 42, notes ["input_alpha"], attempts []; images input /
    prep / model_input all with a url, prep.model "HairDeck"; colour
    {target None, source "hairdeck", auto "#7f6248"} (0.49804·255 = 127.0 ->
    7f, 0.38431·255 = 98.0 -> 62, 0.28235·255 = 72.0 -> 48). Image route:
    prep -> the job's prep.png bytes "prep.png-call1", input -> the profile
    picture's bytes, "bogus" -> 400, a traversal name -> 400/404 without the
    planted secret. other None (no edit-chain fit).
[6] Colour "#FF8000" -> 200 {target "#ff8000", source "override"}, profile
    "#ff8000". GET: fsig F2 != F1, hairdeck.hsig unchanged, garment.fit
    "missing", stale_reasons ["colour_changed"], served_fsig still F1.
    POST run {} -> re-fits WITHOUT a HairDeck call: generate_hair still 1,
    fit 2 with colour_target (1.0, 128/255, 0.0); GET: fit accepted, fit
    colour {target "#ff8000", source "override"}, stale_reasons [],
    served_fsig F2. Colour "" -> {target None, source "hairdeck"}; fsig = F1
    again, fit accepted (nothing to run: counts stay (1, 2)).
[7] Method "edit_chain" (no edit-chain fit exists): GET garment.method
    "edit_chain", the five edit-chain steps, served_fsig None, preview_url
    None (the tab says "No hair from this method yet"); other.method
    "hairdeck", on_current_base True, other.preview_url ends in
    "&method=hairdeck" and names the F1 fit (what HairDeck would serve with
    colour "", not the newer F2); the model route ?method=hairdeck returns
    the F1 bytes, the plain model route and ?method=edit_chain are 404,
    ?method=bogus is 400. Counts stay (1, 2): the switch generated nothing.
    Back to "hairdeck": served_fsig F1, other None.
[8] Fix round 1 — a forced regenerate gives a NEW result: two POST run
    {step "hairdeck", force true} send seeds 43 and 44 (the next seed after
    the highest the job record has seen: 42 -> 43 -> 44) to generate_hair;
    each re-fits (the job's hair changed): counts (1, 2) -> (2, 3) -> (3, 4).
    The hsig stays the same (it does not depend on the seed), the job
    record says seed 44, seeds [42, 43, 44]; the fsig stays F1 and the
    served fit is the F1 fit whose record has inputs.seed 44 and
    inputs.nohead_sha256 = sha256 of the job's hair_seed44_nohead.glb (the
    stub wrote "hair_seed44_nohead.glb-call3"); garment fit "accepted",
    hairdeck panel seed 44.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

FAILS = []
JOB_FILES = ("hair_seed{s}_nohead.glb", "hair_seed{s}.glb", "chains_seed{s}.json", "cards_seed{s}.json",
             "info.json", "prep.png", "model_input.png")
HAIR_COLOR = [0.4980392156862745, 0.3843137254901961, 0.2823529411764706]


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hair-tab-method-") as tmp:
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

        import smoke_garment_chain as cx
        from app.blender import refine
        from app.core import (base_body, garment_assembly, garment_fit, garment_hairdeck, glb_mesh, sessions,
                              sync_topics, users)
        from app.core import garment_store as gs
        from app.core import garments
        from app.core.http_files import content_version
        from app.core.keyed_lock import keyed_lock
        from app.imagegen import service
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)

        # --- stubs -------------------------------------------------------------
        HAIR_CALLS, FIT_CALLS, SCHEDULED = [], [], []
        backend = SimpleNamespace(name="HairDeck", MEDIA_TYPE="mesh", category="img2hair", instance_enabled=True,
                                  effective_cost=0, extra_params={"input_steps": 30})

        class FakeService:
            pool = SimpleNamespace(backends=[backend])

            def generate_hair(self, image_path, output_dir, *, backend_glob="", character_name="", params=None,
                              hub_stage=None):
                n = len(HAIR_CALLS) + 1
                seed = int((params or {}).get("seed"))
                HAIR_CALLS.append({"image": image_path, "seed": seed})
                files = []
                for pattern in JOB_FILES:
                    name = pattern.format(s=seed)
                    path = Path(output_dir) / name
                    if name == "info.json":
                        path.write_text(json.dumps({"ok": True, "notes": ["input_alpha"], "box": [1, 2, 3, 4],
                                                    "hair_color": HAIR_COLOR}))
                    else:
                        path.write_bytes(f"{name}-call{n}".encode())
                    files.append({"name": name, "mime": "application/octet-stream", "path": str(path)})
                return {"files": files, "backend": "HairDeck", "route": {"routing": {"occasion": "hair_mesh"}},
                        "job_id": f"job-{n}"}

        service.get_image_service = lambda: FakeService()

        def fit_stub(nohead_glb, proxy_glb, rigged_base_glb, *, colour_target):
            import smoke_garment_fit as fx
            FIT_CALLS.append({"colour_target": colour_target})
            body = glb_mesh.body_arrays(rigged_base_glb)
            P, F = fx.cap(0.19, np.array([0.0, 1.58, 0.0]), n_el=9, nlon=24)
            names, J, W = garment_fit.hair_weights(P, body)
            garment = glb_mesh.GarmentMesh(
                positions=P, normals=garment_fit.vertex_normals(P, F), uvs=np.zeros((len(P), 2)),
                indices=np.asarray(F, np.int64).reshape(-1, 3), joints=J, weights=W, joint_names=names,
                material={"doubleSided": True}, colors=np.tile([0.3, 0.2, 0.1, 1.0], (len(P), 1)))
            m = {"max_push_m": 0.01, "moved_share": 0.3, "icp_resid_p95_m": 0.004}
            ok, reasons = garment_hairdeck.gate(m)
            return garment_fit.FitResult(garment=garment, metrics=m, ok=ok, reasons=reasons, report={})

        garment_hairdeck.fit_hairdeck = fit_stub

        def decimate_to(path_in, target_tris, out, merge_vertices=False):
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(Path(path_in).read_bytes())
            return {"ok": True, "path": str(out), "tris": target_tris, "ratio": 0.5, "error": ""}

        refine.decimate_to = decimate_to
        garment_assembly.schedule = lambda name, signature=None: SCHEDULED.append((name, signature)) or True
        sync_topics.changed_at = lambda *a, **k: None

        # --- fixture -----------------------------------------------------------
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        images = get_character_images_dir("Demo")
        images.mkdir(parents=True, exist_ok=True)
        profile_png = cx.solid_png((50, 60, 70), 8)
        (images / "Demo_1.png").write_bytes(profile_png)
        with keyed_lock("character_profile", "Demo"):
            stored = get_character_profile("Demo")
            stored["profile_image"] = "Demo_1.png"
            check("profile image", save_character_profile("Demo", stored), True)
        check("pipeline", base_body.set_pipeline("Demo", True), True)
        cdir = get_character_dir("Demo")
        (cdir / "secret.png").write_bytes(b"SECRET-BYTES")
        refs, mdir = cdir / "model_refs", cdir / "model3d"
        b1 = base_body.base_signature("Demo")
        refs.mkdir(parents=True, exist_ok=True)
        for v in base_body.BASE_VIEWS:
            stem = f"tpose_{b1}" if v == "front" else f"tpose_{v}_{b1}"
            (refs / f"{stem}.png").write_bytes(cx.png(cx.BASE))
            (refs / f"{stem}.json").write_text(json.dumps({"base_signature": b1}))
        unrigged, rigged = cx.base_bodies((200, 160, 140))
        (mdir / "unrigged").mkdir(parents=True, exist_ok=True)
        (mdir / "unrigged" / f"{b1}.glb").write_bytes(unrigged)
        (mdir / f"{b1}.glb").write_bytes(rigged)
        (mdir / f"{b1}.json").write_text(json.dumps({
            "base": True, "rig": "mixamo", "signature": b1, "format": "glb", "source": "generated"}))

        tokens = {}
        for role in (users.ROLE_ADMIN, users.ROLE_USER):
            uid = users.create_user("demo-" + role, "temporary-smoke-password", role,
                                    allowed_characters=["Demo"])
            tokens[role] = sessions.create_session(uid)

        def profile():
            return get_character_profile("Demo") or {}

        def counts():
            return len(HAIR_CALLS), len(FIT_CALLS)

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routes.characters import router
        app = FastAPI()
        app.include_router(router)

        with TestClient(app, raise_server_exceptions=False) as client:
            def hair():
                r = client.get("/characters/Demo/hair")
                return r.json() if r.status_code == 200 else {"status": r.status_code, "text": r.text}

            def wait_idle():
                check("worker idle", garments.wait_idle(30), True)

            # --- [1] player --------------------------------------------------------
            print("[1] player session: the new routes answer 403")
            client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_USER])
            for method, url, body in (("POST", "/characters/Demo/hair/method", {"method": "hairdeck"}),
                                      ("POST", "/characters/Demo/hair/colour", {"hex": "#ff8000"}),
                                      ("GET", "/characters/Demo/garments/hair_demo/hairdeck/prep", None),
                                      ("GET", "/characters/Demo/garments/hair_demo/model?method=hairdeck", None)):
                r = client.request(method, url, json=body) if body is not None else client.request(method, url)
                check(f"player {method} {url}", r.status_code, 403)
            check("player stored nothing", ("hair_method" in profile(), "hair_colour" in profile()), (False, False))
            client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_ADMIN])

            # --- [2] GET before the item -----------------------------------------
            print("[2] GET /hair before the item")
            h = hair()
            check("method keys", (h.get("method"), h.get("method_source"), h.get("world_method"),
                                  h.get("hairdeck"), h.get("other"), h.get("item_id")),
                  ("edit_chain", "world", "edit_chain", None, None, None))
            check("hairdeck limits", (h.get("limits") or {}).get("hairdeck_fit"),
                  {"max_push_m": {"op": "le", "value": 0.12}, "moved_share": {"op": "le", "value": 0.90},
                   "icp_resid_p95_m": {"op": "le", "value": 0.012}})

            # --- [3] method --------------------------------------------------------
            print("[3] POST /hair/method")
            r = client.post("/characters/Demo/hair/method", json={"method": "bogus"})
            check("bogus 400", (r.status_code, "hair_method" in profile()), (400, False))
            r = client.post("/characters/Demo/hair/method", json={"method": "hairdeck"})
            check("hairdeck", (r.status_code, r.json()), (200, {"method": "hairdeck", "method_source": "character"}))
            check("stored hairdeck", (profile().get("hair_method"), len(SCHEDULED)), ("hairdeck", 1))
            h = hair()
            check("GET hairdeck", (h.get("method"), h.get("method_source")), ("hairdeck", "character"))
            r = client.post("/characters/Demo/hair/method", json={"method": ""})
            check("'' -> world", (r.status_code, r.json()), (200, {"method": "edit_chain", "method_source": "world"}))
            check("stored ''", profile().get("hair_method"), "")
            config._CONFIG["base_body"] = {"hair_method": "hairdeck"}
            r = client.post("/characters/Demo/hair/method", json={"method": ""})
            check("'' -> world hairdeck", r.json(), {"method": "hairdeck", "method_source": "world"})
            check("GET world_method", hair().get("world_method"), "hairdeck")
            config._CONFIG.pop("base_body", None)
            r = client.post("/characters/Demo/hair/method", json={"method": "hairdeck"})
            check("character hairdeck again", r.json(), {"method": "hairdeck", "method_source": "character"})

            # --- [4] colour validation ---------------------------------------------
            print("[4] POST /hair/colour validation")
            for bad in ("#12345", "red", "#GGGGGG", "ff8000"):
                r = client.post("/characters/Demo/hair/colour", json={"hex": bad})
                check(f"colour {bad!r} 400", r.status_code, 400)
            check("hair_colour absent", "hair_colour" in profile(), False)

            # --- [5] first HairDeck run ---------------------------------------------
            print("[5] POST /hair runs hairdeck + fit")
            r = client.post("/characters/Demo/hair", json={})
            check("create 202", (r.status_code, r.json()), (202, {"item_id": "hair_demo", "started": True}))
            wait_idle()
            check("counts", counts(), (1, 1))
            check("first call", (HAIR_CALLS[0]["seed"], FIT_CALLS[0]["colour_target"]), (42, None))
            f1 = gs.garment_fsig("Demo", "hair_demo")
            h = hair()
            g = h.get("garment") or {}
            check("garment", (g.get("method"), g.get("served_fsig"), (g.get("steps") or {}).get("fit", {}).get("status"),
                              g.get("failed")), ("hairdeck", f1, "accepted", None))
            hd = h.get("hairdeck") or {}
            check("hairdeck panel", (hd.get("status"), hd.get("attempt"), hd.get("seed"), hd.get("notes"),
                                     hd.get("attempts")), ("accepted", 1, 42, ["input_alpha"], []))
            imgs = hd.get("images") or {}
            check("image urls", {k: bool((v or {}).get("url")) for k, v in imgs.items()},
                  {"input": True, "prep": True, "model_input": True})
            check("prep tile meta", ((imgs.get("prep") or {}).get("model"), bool((imgs.get("prep") or {}).get("created_at"))),
                  ("HairDeck", True))
            check("colour auto", hd.get("colour"), {"target": None, "source": "hairdeck", "auto": "#7f6248"})
            check("other none", h.get("other"), None)
            r = client.get((imgs.get("prep") or {}).get("url") or "/none")
            check("prep bytes", (r.status_code, r.content), (200, b"prep.png-call1"))
            r = client.get("/characters/Demo/garments/hair_demo/hairdeck/input")
            check("input bytes", (r.status_code, r.content == profile_png), (200, True))
            check("bogus image 400", client.get("/characters/Demo/garments/hair_demo/hairdeck/bogus").status_code, 400)
            for url in ("/characters/Demo/garments/hair_demo/hairdeck/..%2F..%2Fsecret",
                        "/characters/Demo/garments/..%2Fsecret/hairdeck/prep"):
                r = client.get(url)
                check(f"traversal {url}", (r.status_code in (400, 404), b"SECRET" in r.content), (True, False))

            # --- [6] colour change re-fits without HairDeck --------------------------
            print("[6] colour override re-fits from the cached job")
            hsig1 = hd.get("hsig")
            r = client.post("/characters/Demo/hair/colour", json={"hex": "#FF8000"})
            check("colour 200", (r.status_code, r.json()), (200, {"target": "#ff8000", "source": "override"}))
            check("stored colour", profile().get("hair_colour"), "#ff8000")
            h = hair()
            g = h.get("garment") or {}
            f2 = g.get("fsig")
            check("fsig changed, hsig same", (f2 != f1, (h.get("hairdeck") or {}).get("hsig") == hsig1), (True, True))
            check("before re-fit", ((g.get("steps") or {}).get("fit", {}).get("status"), g.get("stale_reasons"),
                                    g.get("served_fsig")), ("missing", ["colour_changed"], f1))
            r = client.post("/characters/Demo/garments/hair_demo/run", json={})
            check("run 202", r.status_code, 202)
            wait_idle()
            check("no HairDeck call", counts(), (1, 2))
            check("colour target", FIT_CALLS[1]["colour_target"], (1.0, 128 / 255, 0.0))
            h = hair()
            g = h.get("garment") or {}
            fit = (g.get("steps") or {}).get("fit") or {}
            check("after re-fit", (fit.get("status"), fit.get("colour"), g.get("stale_reasons"), g.get("served_fsig")),
                  ("accepted", {"target": "#ff8000", "source": "override"}, [], f2))
            r = client.post("/characters/Demo/hair/colour", json={"hex": ""})
            check("reset", (r.status_code, r.json()), (200, {"target": None, "source": "hairdeck"}))
            g = hair().get("garment") or {}
            check("back to F1", (g.get("fsig"), (g.get("steps") or {}).get("fit", {}).get("status"), counts()),
                  (f1, "accepted", (1, 2)))

            # --- [7] the other method -----------------------------------------------
            print("[7] switch to edit_chain: HairDeck becomes the other method")
            SCHEDULED.clear()
            r = client.post("/characters/Demo/hair/method", json={"method": "edit_chain"})
            check("edit_chain", (r.status_code, r.json(), len(SCHEDULED)),
                  (200, {"method": "edit_chain", "method_source": "character"}, 1))
            h = hair()
            g = h.get("garment") or {}
            check("edit garment", (g.get("method"), sorted(g.get("steps") or {}), g.get("served_fsig"),
                                   g.get("preview_url")),
                  ("edit_chain", sorted(["haired", "ghost", "cutout", "mesh", "fit"]), None, None))
            other = h.get("other") or {}
            f1_fit = gs.garment_path("Demo", "hair_demo", f1, "fit")
            murl = "/characters/Demo/garments/hair_demo/model"
            check("other", (other.get("method"), other.get("on_current_base"), other.get("preview_url")),
                  ("hairdeck", True, f"{murl}?v={content_version(f1_fit)}&method=hairdeck"))
            r = client.get(f"{murl}?method=hairdeck")
            check("other model = F1", (r.status_code, hashlib.sha256(r.content).hexdigest()),
                  (200, hashlib.sha256(f1_fit.read_bytes()).hexdigest()))
            check("plain model 404", client.get(murl).status_code, 404)
            check("edit_chain model 404", client.get(f"{murl}?method=edit_chain").status_code, 404)
            check("bogus method 400", client.get(f"{murl}?method=bogus").status_code, 400)
            check("switch generated nothing", counts(), (1, 2))
            client.post("/characters/Demo/hair/method", json={"method": "hairdeck"})
            h = hair()
            check("back to hairdeck", ((h.get("garment") or {}).get("served_fsig"), h.get("other")), (f1, None))

            # --- [8] forced regenerate: next seed ----------------------------------
            print("[8] forced HairDeck regenerate takes the next seed")
            hsig_before = (h.get("hairdeck") or {}).get("hsig")
            for n, want in ((1, (2, 3)), (2, (3, 4))):
                r = client.post("/characters/Demo/garments/hair_demo/run", json={"step": "hairdeck", "force": True})
                check(f"forced {n} 202", r.status_code, 202)
                wait_idle()
                check(f"forced {n} counts", counts(), want)
            check("seeds sent", [c["seed"] for c in HAIR_CALLS], [42, 43, 44])
            folder = gs.hairdeck_dir("Demo", "hair_demo", hsig_before)
            job = gs.read_record(folder / gs.HAIRDECK_RECORD)
            check("job record", (job.get("accepted"), job.get("seed"), job.get("seeds"), job.get("attempt")),
                  (True, 44, [42, 43, 44], 1))
            check("nohead bytes", (folder / "hair_seed44_nohead.glb").read_bytes(), b"hair_seed44_nohead.glb-call3")
            h = hair()
            g = h.get("garment") or {}
            served = gs.accepted_fit("Demo", "hair_demo", base_model_sha=base_body.current_base("Demo")[1])
            rec = served[1] if served else {}
            check("served after regenerate",
                  ((h.get("hairdeck") or {}).get("hsig"), g.get("fsig"), g.get("served_fsig"),
                   (g.get("steps") or {}).get("fit", {}).get("status"), (h.get("hairdeck") or {}).get("seed"),
                   served[0].name if served else None, (rec.get("inputs") or {}).get("seed"),
                   (rec.get("inputs") or {}).get("nohead_sha256")),
                  (hsig_before, f1, f1, "accepted", 44, f"hair_demo_{f1}.glb", 44,
                   hashlib.sha256(b"hair_seed44_nohead.glb-call3").hexdigest()))

        garments.wait_idle(30)

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
