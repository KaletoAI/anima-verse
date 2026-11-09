#!/usr/bin/env python3
"""Hair as its own mesh, task 9: the admin routes of the hair garment
(app/routes/characters.py, plan 2026-11-09-base-body-phase4-hair).

Usage:
    ./.venv/bin/python scripts/smoke_garment_routes.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no GPU, no
server process. The characters router is mounted on a bare FastAPI app with
real sessions (pattern of smoke_base_body_model.py [5]).

Stubs: ``garments.run_garment`` (recorder that BLOCKS on an event, so a run
can be held "in flight"), ``garment_assembly.schedule`` (recorder; equipping
asks for an assembly). Everything else is real: ``ensure_hair_item``,
``start_garment`` (its worker thread calls the recorder), ``garment_info``,
``preview_path``, ``garment_store.garment_path`` and the file responses.

Fixture (expected values derived by hand):
  Demo    human, pipeline on, hair slot {medium, blonde}, appearance
          "slender" -> description = the slot's always fragment
          "{length} {color} hair" = "medium blonde hair"; medium has a
          mesh-input line -> behind_shoulders True. Item id = "hair_" + slug
          "demo" = "hair_demo".
  Pet     animal template + model_pipeline base_body -> not humanoid -> 400.
  Offline human, pipeline OFF -> 400 naming the "base-body pipeline"; it also
          owns a garment item "hair_offline" (added directly) -> a run is 400.
  Bald    human, pipeline on, no hair slot value, no hair clause -> "" ->
          POST /hair 400 "No hair set"; no item -> /hair/equipped 404.
  Other   human, pipeline on, owns "hair_other" -> foreign for Demo.

[1] Player session: every route answers 403 (require_admin), and the
    recorder sees no call.
[2] GET /characters/Demo/hair before any item: {pipeline True, humanoid
    True, description "medium blonde hair", behind_shoulders True, item_id
    None, equipped False, garment None, collision False}; Pet: humanoid
    False, description "", garment None; Nobody: 404.
[3] POST /hair: Pet 400, Offline 400 ("base-body pipeline"), Bald 400
    ("No hair set"); none of them gets an item or a run.
[4] POST /characters/Demo/hair -> 202 {item_id "hair_demo", started True};
    the recorder runs (Demo, hair_demo, steps None, view None, force False);
    while it blocks: a run -> 409, a second POST /hair -> 202 started False;
    GET /hair -> item_id hair_demo, equipped True, garment.item_id hair_demo,
    garment.running_step "queued" (the worker is still before its first
    step — the recorder never calls garment_store.start). Released -> idle.
[5] Run validation: step "nope" 400, view "side" 400, Other's item 400, an
    unknown item 400, Offline's own item 400 ("base-body pipeline"); then
    {step fit, force true} -> 202 {started True} and the recorder gets
    (steps "fit", view None, force True); {step haired, view back} ->
    (steps "haired", view "back", force False).
[6] /hair/equipped: false -> 200 {equipped False}, worn map {}; GET /hair
    still names hair_demo with equipped False; true -> {equipped True},
    worn {hair: hair_demo}; Bald (no item) -> 404.
[7] Image route for the CURRENT fsig F: the planted final haired/front
    bytes come back (200, image/png); ?attempt=1 -> the planted try1 bytes;
    ?attempt=2 (absent) -> 404; ghost/back (absent) -> 404; step "mesh" ->
    400; view "side" -> 400; attempt 7 -> 400; Other's item -> 404;
    traversal (step "..", step "..%2F..%2Fsecret", item "..%2Fsecret") ->
    400 or 404 and never the planted characters/Demo/secret.png bytes.
[8] Model route: no fit -> 404; the planted fit garments/hair_demo_F.glb
    -> 200 model/gltf-binary with those bytes and ETag "<content_version>";
    If-None-Match with that ETag -> 304; ?v=<content_version> -> immutable
    Cache-Control. garment.preview_url of GET /hair names that version.
"""
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


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="garment-routes-") as tmp:
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

        from app.core import base_body, garment_assembly, sessions, users
        from app.core import garment_store as gs
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile
        try:
            from app.core import garments
        except ImportError as e:
            check("garments importable", str(e), "importable")
            return 1

        # --- stubs ---------------------------------------------------------------
        RUNS = []
        gate = threading.Event()
        gate.set()

        def recorder(character_name, item_id, *, steps=None, view=None, force=False):
            RUNS.append((character_name, item_id, steps, view, force))
            gate.wait(30)
            return {"ok": True, "fsig": "", "ran": []}

        garments.run_garment = recorder
        garment_assembly.schedule = lambda name, signature=None: True

        # --- fixture -------------------------------------------------------------
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        for name in ("Demo", "Offline", "Other"):
            check(f"create {name}", save_character_profile(name, json.loads(json.dumps(human)), create_new=True),
                  True)
        bald = json.loads(json.dumps(human))
        bald["body_slots"].pop("hair")
        check("create Bald", save_character_profile("Bald", bald, create_new=True), True)
        check("create Pet", save_character_profile("Pet", {"template": "animal-default", "gender": "female",
                                                           "model_pipeline": "base_body"}, create_new=True), True)
        for name in ("Demo", "Other", "Bald"):
            check(f"pipeline {name}", base_body.set_pipeline(name, True), True)
        garment = {"kind": "hair", "slot": "hair", "body_slot": "hair"}
        inventory.add_item(name="Hair", category="garment", owner="Offline", prompt_fragment="medium blonde hair",
                           garment=garment, item_id="hair_offline", transferable=False, portable=False)
        inventory.add_item(name="Hair", category="garment", owner="Other", prompt_fragment="medium blonde hair",
                           garment=garment, item_id="hair_other", transferable=False, portable=False)
        secret = get_character_dir("Demo") / "secret.png"
        secret.write_bytes(b"SECRET-BYTES")

        tokens = {}
        for role in (users.ROLE_ADMIN, users.ROLE_USER):
            uid = users.create_user("demo-" + role, "temporary-smoke-password", role,
                                    allowed_characters=["Demo", "Pet", "Offline", "Bald", "Other"])
            tokens[role] = sessions.create_session(uid)

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routes.characters import router
        app = FastAPI()
        app.include_router(router)

        def wait_idle():
            check("worker idle", garments.wait_idle(30), True)

        with TestClient(app, raise_server_exceptions=False) as client:
            # --- [1] player --------------------------------------------------------
            print("[1] player session: every route 403")
            client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_USER])
            calls = [
                ("GET", "/characters/Demo/hair", None),
                ("POST", "/characters/Demo/hair", {}),
                ("POST", "/characters/Demo/hair/equipped", {"equipped": True}),
                ("POST", "/characters/Demo/garments/hair_demo/run", {}),
                ("GET", "/characters/Demo/garments/hair_demo/images/haired/front", None),
                ("GET", "/characters/Demo/garments/hair_demo/model", None),
            ]
            for method, url, body in calls:
                r = client.request(method, url, json=body) if body is not None else client.request(method, url)
                check(f"player {method} {url}", r.status_code, 403)
            check("player started nothing", (RUNS, inventory.get_item("hair_demo")), ([], None))

            client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_ADMIN])

            # --- [2] GET before the item ---------------------------------------------
            print("[2] GET /hair before the item")
            r = client.get("/characters/Demo/hair")
            body = r.json() if r.status_code == 200 else {}
            limits = body.pop("limits", None) or {}
            check("demo hair", (r.status_code, body if r.status_code == 200 else r.text),
                  (200, {"pipeline": True, "humanoid": True, "description": "medium blonde hair",
                         "behind_shoulders": True, "item_id": None, "equipped": False, "garment": None,
                         "collision": False}))
            # The chip limits come from the gate constants (R7): haired XOR < 0.015,
            # ghost |top_dy| <= 0.0052 H, mesh component share >= 0.98, fit bib <= 50 cm².
            check("hair limits", (sorted(limits), limits.get("haired", {}).get("body_xor"),
                                  limits.get("ghost", {}).get("top_dy"),
                                  limits.get("mesh", {}).get("largest_component_share"),
                                  limits.get("fit", {}).get("bib_cm2"),
                                  limits.get("fit", {}).get("largest_component_share")),
                  (["fit", "ghost", "haired", "mesh"], {"op": "lt", "value": 0.015},
                   {"op": "abs_le", "value": 0.0052, "per_height": True},
                   {"op": "ge", "value": 0.98}, {"op": "le", "value": 50.0},
                   {"op": "ge", "value": 0.98}))
            r = client.get("/characters/Pet/hair")
            body = r.json() if r.status_code == 200 else {}
            check("pet hair", (r.status_code, body.get("humanoid"), body.get("description"), body.get("garment")),
                  (200, False, "", None))
            check("unknown character", client.get("/characters/Nobody/hair").status_code, 404)

            # --- [3] refusals ----------------------------------------------------------
            print("[3] POST /hair refusals")
            for name, needle in (("Pet", "humanoid"), ("Offline", "base-body pipeline"), ("Bald", "No hair set")):
                r = client.post(f"/characters/{name}/hair", json={})
                detail = (r.json() or {}).get("detail", "") if r.status_code == 400 else r.text
                check(f"{name} 400", (r.status_code, needle in str(detail)), (400, True))
            check("no items, no runs", (inventory.get_equipped_mesh_pieces("Bald"), RUNS), ({}, []))

            # --- [4] create + start ------------------------------------------------------
            print("[4] POST /hair creates, wears and starts")
            gate.clear()
            r = client.post("/characters/Demo/hair", json={})
            check("202", (r.status_code, r.json()), (202, {"item_id": "hair_demo", "started": True}))
            deadline = time.monotonic() + 10
            while not RUNS and time.monotonic() < deadline:
                time.sleep(0.02)
            check("recorder call", RUNS, [("Demo", "hair_demo", None, None, False)])
            check("worn", inventory.get_equipped_mesh_pieces("Demo"), {"hair": "hair_demo"})
            r = client.post("/characters/Demo/garments/hair_demo/run", json={})
            check("run while running -> 409", r.status_code, 409)
            r = client.post("/characters/Demo/hair", json={})
            check("second POST /hair", (r.status_code, r.json()), (202, {"item_id": "hair_demo", "started": False}))
            r = client.get("/characters/Demo/hair")
            body = r.json() if r.status_code == 200 else {}
            g = body.get("garment") or {}
            check("GET with item", (body.get("item_id"), body.get("equipped"), g.get("item_id"),
                                    g.get("running_step"), body.get("collision")),
                  ("hair_demo", True, "hair_demo", "queued", False))
            gate.set()
            wait_idle()
            check("one run only", len(RUNS), 1)

            # --- [5] run validation --------------------------------------------------------
            print("[5] run validation")
            RUNS.clear()
            for label, item, payload in (("unknown step", "hair_demo", {"step": "nope"}),
                                         ("unknown view", "hair_demo", {"view": "side"}),
                                         ("foreign item", "hair_other", {}),
                                         ("unknown item", "no_such_item", {})):
                r = client.post(f"/characters/Demo/garments/{item}/run", json=payload)
                check(f"{label} 400", r.status_code, 400)
            r = client.post("/characters/Offline/garments/hair_offline/run", json={})
            detail = (r.json() or {}).get("detail", "") if r.status_code == 400 else r.text
            check("off pipeline run 400", (r.status_code, "base-body pipeline" in str(detail)), (400, True))
            check("nothing ran", RUNS, [])
            r = client.post("/characters/Demo/garments/hair_demo/run", json={"step": "fit", "force": True})
            check("forced fit 202", (r.status_code, r.json()), (202, {"started": True}))
            wait_idle()
            r = client.post("/characters/Demo/garments/hair_demo/run", json={"step": "haired", "view": "back"})
            check("haired back 202", r.status_code, 202)
            wait_idle()
            check("recorder args", RUNS, [("Demo", "hair_demo", "fit", None, True),
                                          ("Demo", "hair_demo", "haired", "back", False)])

            # --- [6] equipped -----------------------------------------------------------------
            print("[6] equip / unequip")
            r = client.post("/characters/Demo/hair/equipped", json={"equipped": False})
            check("unequip", (r.status_code, r.json()), (200, {"equipped": False}))
            check("worn map empty", inventory.get_equipped_mesh_pieces("Demo"), {})
            body = client.get("/characters/Demo/hair").json()
            check("GET after unequip", (body.get("item_id"), body.get("equipped")), ("hair_demo", False))
            r = client.post("/characters/Demo/hair/equipped", json={"equipped": True})
            check("equip", (r.status_code, r.json()), (200, {"equipped": True}))
            check("worn again", inventory.get_equipped_mesh_pieces("Demo"), {"hair": "hair_demo"})
            check("Bald 404", client.post("/characters/Bald/hair/equipped", json={"equipped": True}).status_code,
                  404)

            # --- [7] images ----------------------------------------------------------------------
            print("[7] image route")
            fsig = gs.garment_fsig("Demo", "hair_demo")
            final = gs.garment_path("Demo", "hair_demo", fsig, "image", step="haired", view="front")
            try1 = gs.garment_path("Demo", "hair_demo", fsig, "image", step="haired", view="front", attempt=1)
            final.parent.mkdir(parents=True, exist_ok=True)
            final.write_bytes(b"\x89PNG-final")
            try1.write_bytes(b"\x89PNG-try1")
            base = "/characters/Demo/garments/hair_demo/images"
            r = client.get(f"{base}/haired/front")
            check("final", (r.status_code, r.content, r.headers.get("content-type")),
                  (200, b"\x89PNG-final", "image/png"))
            r = client.get(f"{base}/haired/front?attempt=1")
            check("attempt 1", (r.status_code, r.content), (200, b"\x89PNG-try1"))
            check("attempt 2 absent", client.get(f"{base}/haired/front?attempt=2").status_code, 404)
            check("ghost back absent", client.get(f"{base}/ghost/back").status_code, 404)
            check("step mesh", client.get(f"{base}/mesh/front").status_code, 400)
            check("view side", client.get(f"{base}/haired/side").status_code, 400)
            check("attempt 7", client.get(f"{base}/haired/front?attempt=7").status_code, 400)
            check("foreign item", client.get("/characters/Demo/garments/hair_other/images/haired/front").status_code,
                  404)
            for url in (f"{base}/../front", f"{base}/..%2F..%2Fsecret/front",
                        "/characters/Demo/garments/..%2Fsecret/images/haired/front",
                        "/characters/Demo/garments/..%2F..%2FDemo%2Fsecret.png/model"):
                r = client.get(url)
                check(f"traversal {url}", (r.status_code in (400, 404), b"SECRET" in r.content), (True, False))

            # --- [8] model -----------------------------------------------------------------------
            print("[8] model route")
            murl = "/characters/Demo/garments/hair_demo/model"
            check("no fit 404", client.get(murl).status_code, 404)
            fit = gs.garment_path("Demo", "hair_demo", fsig, "fit")
            fit.write_bytes(b"glTF-fixture-bytes")
            from app.core.http_files import content_version
            ver = content_version(fit)
            r = client.get(murl)
            check("fit served", (r.status_code, r.content, r.headers.get("content-type"), r.headers.get("etag")),
                  (200, b"glTF-fixture-bytes", "model/gltf-binary", f'"{ver}"'))
            r = client.get(murl, headers={"If-None-Match": f'"{ver}"'})
            check("304", r.status_code, 304)
            r = client.get(f"{murl}?v={ver}")
            check("immutable", "immutable" in (r.headers.get("cache-control") or ""), True)
            g = client.get("/characters/Demo/hair").json().get("garment") or {}
            check("preview url", g.get("preview_url"), f"{murl}?v={ver}")

        gate.set()
        garments.wait_idle(30)

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
