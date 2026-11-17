#!/usr/bin/env python3
"""The Hairstyles tab's backend (plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md Task 14,
Rulings P2/P3, the user's rule R1-R4): the hair GET of a SELECTED hairstyle (``?item_id=``) with its Run-all
estimate, the save-only Swing (R3) and the outfit set's hairstyle (D5).

Usage:
    ./.venv/bin/python scripts/smoke_hairstyles_tab.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real
world, no hub, no GPU, no server. The characters and inventory routers are mounted on a bare FastAPI app with
real sessions (an admin and a player of Kai). ``garments.start_garment`` and ``figure_build.request`` are
recorders (nothing runs, nothing is built); the image service is a stub without a pool.

Fixture: Kai (human-roleplay, male, 180 cm) with a stored base set for his base signature B (four view PNGs +
the base model ``model3d/<B>.glb``, rig mixamo); three hairstyles he owns:
  hair_kai_body  (mode body,     "short black hair")   — worn, the plain body's (``base_hairstyle``);
  hair_kai_deck  (mode hairdeck, "long braided hair")  — not worn, never run;
  hair_kai_bun   (mode body,     "a bun")              — not worn, not the plain body's;
and Ana's hairstyle hair_ana (mode hairdeck). One saved outfit set of Kai, ``set1`` (no hairstyle).

EXPECTED, BY HAND FROM THE BRIEF AND app/core/garments.py (HUB_JOBS "hair:hairdeck" = {hairdeck 1, fit 0})
[1] GET /characters/Kai/hair (no query) — the worn hairstyle as before: item_id hair_kai_body, equipped True,
    hair_in_body True (its mode is body), plain True, body_url the base model's url
    (``model3d.signature_model_url(Kai, B)``); ``run`` = the estimate of a body hairstyle: steps [],
    hub_jobs 0, note "Hair comes from the body mesh" (``garment_hair.HAIR_IN_BODY``), refit False.
[2] GET …/hair?item_id=hair_kai_deck — THAT hairstyle, not the worn one: item_id hair_kai_deck, equipped
    False, plain False, hair_in_body False (its own mode, although the worn one is body), method "hairdeck",
    description "long braided hair", base_prompts None (not in the body); run: nothing made yet, so both
    steps from the first: steps ["hairdeck", "fit"], hub_jobs 1 + 0 = 1, note "hairdeck 1" (the 0-job fit is
    not named), refit False.
[3] GET …/hair?item_id=hair_kai_bun — a body hairstyle that is not the plain body's: hair_in_body True,
    plain False, equipped False.
[4] GET …/hair?item_id=hair_ana (Ana's) -> 404; ?item_id=nothing -> 404; a player of Kai -> 403 (admin route).
[5] POST /characters/Kai/hair/motion {item_id hair_kai_deck, swing true, stiffness 1.5} (rule R3: settings
    saved on their own): 200 {swing true, stiffness 1.5} — no ``refit`` key — stored on hair_kai_deck
    (hair_swing "on", hair_stiffness 1.5) and ``garments.start_garment`` NOT called (the old route started a
    fit-only run when Swing changed). The worn hairstyle hair_kai_body keeps no hair_swing.
[6] POST /inventory/characters/Kai/outfit-sets/set1/hairstyle {hairstyle hair_kai_deck} -> 200
    {outfit_id set1, hairstyle hair_kai_deck}; the preview route (GET …/outfit-sets/set1) names it; nothing
    is worn (equipped_mesh_pieces.hair still hair_kai_body) and no Build is requested. {hairstyle ""} -> 200,
    the set leaves the hair as it is (""). {hairstyle hair_ana} -> 400 (no hairstyle of Kai), set unchanged;
    unknown set -> 404; a player of Kai -> 403.
[7] A set deleted WHILE its hairstyle is set (review 10#3): a second set ``set2``; the route's existence check
    (its first ``get_character_outfits`` call) starts ``delete_character_outfit(Kai, set2)`` in another thread
    and waits 0.3 s for it. The delete takes ``keyed_lock("character_profile", Kai)``, which the route holds
    around check + write, so it is still running after 0.3 s -> True; the route writes the existing set2 ->
    200 {outfit_id set2, hairstyle hair_kai_deck}; then the delete runs. Kai's set ids afterwards: [set1] only —
    no phantom set. (Unlocked, the delete finished inside the 0.3 s, ``add_character_outfit`` found no set2
    and appended a new empty set "Outfit1": two sets.)
"""
import json
import os
import shutil
import sys
import tempfile
import types
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
    with tempfile.TemporaryDirectory(prefix="hairstyles-tab-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        world_cfg = paths.get_config_path()
        world_cfg.write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(world_cfg, instance_path=root / "instance" / "config.json")
        from app.core import db
        db.init_schema()
        shutil.copytree(ROOT / "plugins" / "human", root / "plugins" / "human")
        from app.plugins.loader import discover_packages
        discover_packages(root / "plugins", force=True)

        from app.core import base_body, figure_build, garment_hair, garments, model3d, model_refs, sessions, users
        from app.core.keyed_lock import keyed_lock
        from app.models import inventory
        from app.models.character import (add_character_outfit, get_character_dir, get_character_profile,
                                          save_character_profile)
        requests = []
        figure_build.request = lambda name, trigger: requests.append((name, trigger)) or True
        model_refs.get_auto_kinds = lambda name: {}
        runs = []
        garments.start_garment = lambda name, item_id, **kw: runs.append((name, item_id, kw)) or {"started": True}
        from app.core import glb_delivery
        glb_delivery.delivery_path = lambda path, **kw: path   # no Blender for the stub GLB
        from app.imagegen import service
        service.get_image_service = lambda *a, **k: types.SimpleNamespace()

        human = {"template": "human-roleplay", "age": 30}
        check("create Kai", save_character_profile("Kai", {
            **human, "gender": "male", "height": 180, "character_appearance": "athletic",
            "body_slots": {"hair": {"length": "short", "color": "black"}}}, create_new=True), True)
        check("create Ana", save_character_profile("Ana", {
            **human, "gender": "female", "height": 168, "character_appearance": "slender"}, create_new=True), True)

        def style(item_id, owner, mode, text):
            inventory.add_item(name=text.capitalize(), category="garment", owner=owner, item_id=item_id,
                               prompt_fragment=text,
                               garment={"kind": "hair", "slot": "hair", "body_slot": "hair", "mesh_mode": mode,
                                        "description": text},
                               transferable=False, portable=False)
        style("hair_kai_body", "Kai", "body", "short black hair")
        style("hair_kai_deck", "Kai", "hairdeck", "long braided hair")
        style("hair_kai_bun", "Kai", "body", "a bun")
        style("hair_ana", "Ana", "hairdeck", "long blonde hair")
        with keyed_lock("character_profile", "Kai"):
            kai = get_character_profile("Kai")
            kai.update(equipped_mesh_pieces={"hair": "hair_kai_body"},
                       **{garment_hair.BASE_HAIRSTYLE_KEY: "hair_kai_body"})
            check("Kai wears hair_kai_body", save_character_profile("Kai", kai), True)
        set_id = add_character_outfit("Kai", {"id": "", "name": "Set one", "pieces": [], "remove_slots": []})

        bsig = base_body.base_signature("Kai")
        refs = model_refs.get_model_refs_dir("Kai")
        refs.mkdir(parents=True, exist_ok=True)
        for view in base_body.BASE_VIEWS:
            kind = base_body._kind(view)
            (refs / f"{kind}_{bsig}.png").write_bytes(f"png-{view}".encode())
            (refs / f"{kind}_{bsig}.json").write_text(json.dumps({"base_signature": bsig}))
        mdir = get_character_dir("Kai") / "model3d"
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / f"{bsig}.glb").write_bytes(b"glb-Kai")
        (mdir / f"{bsig}.json").write_text(json.dumps({"base": True, "rig": "mixamo", "signature": bsig,
                                                       "format": "glb", "source": "generated"}))
        check("Kai on the pipeline with a base model", (base_body.is_base_pipeline("Kai"),
                                                        (base_body.base_model_info("Kai") or {}).get("status")),
              (True, "ready"))
        model_url = model3d.signature_model_url("Kai", bsig)

        tokens = {}
        for role in (users.ROLE_ADMIN, users.ROLE_USER):
            uid = users.create_user("demo-" + role, "temporary-smoke-password", role, allowed_characters=["Kai"])
            tokens[role] = sessions.create_session(uid)
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routes.characters import router as characters_router
        from app.routes.inventory import router as inventory_router
        app = FastAPI()
        app.include_router(characters_router)
        app.include_router(inventory_router)
        with TestClient(app, raise_server_exceptions=False) as client:
            client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_ADMIN])

            def hair(query=""):
                r = client.get("/characters/Kai/hair" + query)
                return r.status_code, (r.json() if r.status_code == 200 else {})

            # --- [1] ---------------------------------------------------------------------------------------------
            print("[1] GET /hair — the worn hairstyle")
            code, d = hair()
            check("200", code, 200)
            check("worn body hairstyle", (d.get("item_id"), d.get("equipped"), d.get("hair_in_body"), d.get("plain")),
                  ("hair_kai_body", True, True, True))
            check("body_url = the base model", d.get("body_url"), model_url)
            check("run of a body hairstyle", d.get("run"),
                  {"steps": [], "hub_jobs": 0, "note": garment_hair.HAIR_IN_BODY, "refit": False})

            # --- [2] ---------------------------------------------------------------------------------------------
            print("[2] GET /hair?item_id=hair_kai_deck — the selected hairstyle")
            code, d = hair("?item_id=hair_kai_deck")
            check("200", code, 200)
            check("that hairstyle", (d.get("item_id"), d.get("equipped"), d.get("plain"), d.get("hair_in_body"),
                                     d.get("method"), d.get("description"), d.get("base_prompts")),
                  ("hair_kai_deck", False, False, False, "hairdeck", "long braided hair", None))
            check("its Run all", d.get("run"),
                  {"steps": ["hairdeck", "fit"], "hub_jobs": 1, "note": "hairdeck 1", "refit": False})

            # --- [3] ---------------------------------------------------------------------------------------------
            print("[3] GET /hair?item_id=hair_kai_bun — a body hairstyle that is not the plain body's")
            code, d = hair("?item_id=hair_kai_bun")
            check("bun", (code, d.get("hair_in_body"), d.get("plain"), d.get("equipped")), (200, True, False, False))

            # --- [4] ---------------------------------------------------------------------------------------------
            print("[4] refusals")
            check("Ana's hairstyle -> 404", hair("?item_id=hair_ana")[0], 404)
            check("unknown item -> 404", hair("?item_id=nothing")[0], 404)
            client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_USER])
            check("player -> 403", client.get("/characters/Kai/hair?item_id=hair_kai_deck").status_code, 403)
            client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_ADMIN])

            # --- [5] ---------------------------------------------------------------------------------------------
            print("[5] POST /hair/motion saves only (R3)")
            r = client.post("/characters/Kai/hair/motion",
                            json={"item_id": "hair_kai_deck", "swing": True, "stiffness": 1.5})
            check("200 {swing, stiffness}", (r.status_code, r.json()), (200, {"swing": True, "stiffness": 1.5}))
            deck = garment_hair.hairstyle_settings(inventory.get_item("hair_kai_deck"))
            check("stored on hair_kai_deck", (deck.get("hair_swing"), deck.get("hair_stiffness")), ("on", 1.5))
            check("no run started", runs, [])
            check("worn hairstyle untouched",
                  "hair_swing" in garment_hair.hairstyle_settings(inventory.get_item("hair_kai_body")), False)

            # --- [6] ---------------------------------------------------------------------------------------------
            print("[6] outfit set hairstyle (D5)")
            url = f"/inventory/characters/Kai/outfit-sets/{set_id}/hairstyle"
            r = client.post(url, json={"hairstyle": "hair_kai_deck"})
            check("200", (r.status_code, r.json()), (200, {"outfit_id": set_id, "hairstyle": "hair_kai_deck"}))
            preview = client.get(f"/inventory/characters/Kai/outfit-sets/{set_id}").json()
            check("preview names it", preview.get("hairstyle"), "hair_kai_deck")
            check("nothing worn, no Build", ((get_character_profile("Kai").get("equipped_mesh_pieces") or {}).get("hair"),
                                             requests), ("hair_kai_body", []))
            r = client.post(url, json={"hairstyle": "hair_ana"})
            check("Ana's -> 400", r.status_code, 400)
            check("set unchanged", client.get(f"/inventory/characters/Kai/outfit-sets/{set_id}").json().get("hairstyle"),
                  "hair_kai_deck")
            r = client.post(url, json={"hairstyle": ""})
            check("'' -> 200", (r.status_code, r.json().get("hairstyle")), (200, ""))
            check("set leaves the hair", client.get(f"/inventory/characters/Kai/outfit-sets/{set_id}").json()
                  .get("hairstyle"), "")
            check("unknown set -> 404", client.post("/inventory/characters/Kai/outfit-sets/nope/hairstyle",
                                                    json={"hairstyle": ""}).status_code, 404)

            # --- [7] ---------------------------------------------------------------------------------------------
            print("[7] a set deleted while its hairstyle is set")
            import threading
            from app.models import character as ch_mod
            set2 = add_character_outfit("Kai", {"id": "", "name": "Set two", "pieces": [], "remove_slots": []})
            real_get = ch_mod.get_character_outfits
            race = {}

            def racing_get(name):
                result = real_get(name)
                if "thread" not in race:
                    race["thread"] = threading.Thread(target=ch_mod.delete_character_outfit, args=("Kai", set2))
                    race["thread"].start()
                    race["thread"].join(0.3)
                    race["delete_waited"] = race["thread"].is_alive()
                return result

            ch_mod.get_character_outfits = racing_get
            try:
                r = client.post(f"/inventory/characters/Kai/outfit-sets/{set2}/hairstyle",
                                json={"hairstyle": "hair_kai_deck"})
            finally:
                ch_mod.get_character_outfits = real_get
            race["thread"].join(5)
            check("delete waited for the route's lock", race.get("delete_waited"), True)
            check("route wrote the existing set", (r.status_code, r.json()),
                  (200, {"outfit_id": set2, "hairstyle": "hair_kai_deck"}))
            check("no phantom set", [o.get("id") for o in real_get("Kai")], [set_id])

            client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_USER])
            check("player -> 403", client.post(url, json={"hairstyle": "hair_kai_deck"}).status_code, 403)

    if FAILS:
        print(f"\nFAIL ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
