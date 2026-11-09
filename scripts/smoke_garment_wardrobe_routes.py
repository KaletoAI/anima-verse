#!/usr/bin/env python3
"""Own-mesh outfit pieces, task 5: the Wardrobe's garment routes
(app/routes/characters.py, plan 2026-11-09-base-body-phase5-mesh-items).

Usage:
    ./.venv/bin/python scripts/smoke_garment_wardrobe_routes.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no GPU, no server process.
The characters router is mounted on a bare FastAPI app with real sessions
(pattern of smoke_garment_routes.py). Nothing runs a chain: the files a
chain would leave are planted.

Fixture (expected values derived by hand):
  Demo    human, pipeline on. Holds and wears ``dress`` (slots top+bottom,
          own mesh) and ``coat`` (slot outer, covers [top], own mesh); holds
          ``cape`` (outer, own mesh, not worn — the coat sits in outer) and
          ``shirt`` (underwear_top, NO flag); owns the hair item ``hair_demo``.
  Offline human, pipeline OFF, holds and wears ``dress``.
  Other   human, pipeline on, holds nothing of the above.

[1] Player session: GET /garments and GET /garments/dress are 403.
[2] GET /characters/Demo/garments/dress: kind clothing, own_mesh True, worn
    True, pipeline True. Limits come from the gate constants of the
    CLOTHING kind (garment_gates.limits("clothing"), garment_mesh,
    garment_fit.CLOTHING_GATES): steps [fit, ghost, mesh, worn] — no
    "haired", no "hairdeck_fit"; worn.garment_share {ge 0.01}; ghost.top_dy
    {abs_le 0.0055} (no per_height: clothing records are fractions of Hb);
    mesh.largest_component_share {ge 0.98}; fit.max_push_m {le 0.10},
    fit.rigged_inside_share {le 0.01}, fit.largest_component_share {ge 0.98}.
    No base model is stored -> status {missing, step None, painted True,
    reason base_body.BASE_MODEL_MISSING}. preview_url None ->
    preview_freshness {missing, "No provenance recorded"}. ``steps`` (the
    ModelSteps rows) = the clothing chain in order, all "missing", the ghost
    row labelled "Piece-only views".
    404: shirt (no flag), a flagged piece Other does not hold
    (Other/garments/dress), an unknown item; 404 for an unknown character.
[3] A planted base model -> reason base_body.NO_MESH_FIT. A planted ACCEPTED
    worn/front final (record {"accepted": true}) with attempt 1 -> the tile
    and its attempt carry freshness "current"; status state "images",
    still painted (no fit).
[4] A persisted chain failure (garment_store.record_failure, step ghost,
    error "gate refused") is reported after a "restart" (empty in-memory
    status): garment.failed {step ghost, error "gate refused", gates None},
    status reason "ghost — gate refused"; the ghost row is "failed" with the
    error as detail, the worn row stays "missing" (only the front is
    accepted).
[5] GET /characters/Demo/garments: pipeline True, items = the flagged pieces
    Demo holds [cape, coat, dress] (not shirt, not the hair); dress painted
    with reason "ghost — gate refused"; cape not worn -> painted False,
    reason None; overlaps: the coat covers top, the dress is worn on top
    -> [{items [coat, dress], slots [top]}]. Offline: pipeline False, dress
    painted False, overlaps []. Other: items {}.
[6] garment_set.piece_status, pure: running wins ({running, step "mesh"});
    an accepted fit of the current fsig -> {fitted, painted False, reason
    None}; an accepted mesh -> "mesh"; an accepted fit without fsig is not
    fitted.
[7] Hair keeps its own limits: GET /characters/Demo/garments/hair_demo ->
    kind hair, own_mesh False, steps [fit, ghost, haired, mesh] with
    fit.bib_cm2 {le 50.0}; worn hair without a fit is NOT painted (hair is
    simply absent). (The Hair tab's own limits, incl. hairdeck_fit, stay
    pinned by smoke_garment_routes.py [2]; its route probes the image
    backends, so it is not called here.)
"""
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
    with tempfile.TemporaryDirectory(prefix="garment-wardrobe-") as tmp:
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

        from app.core import base_body, garment_assembly, garment_set, model_refs, sessions, users
        from app.core import garment_store as gs
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile

        model_refs.schedule_outfit_render = lambda *a, **k: None
        garment_assembly.schedule = lambda name, signature=None: True

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        for name in ("Demo", "Offline", "Other"):
            check(f"create {name}", save_character_profile(name, json.loads(json.dumps(human)), create_new=True),
                  True)
        for name in ("Demo", "Other"):
            check(f"pipeline {name}", base_body.set_pipeline(name, True), True)

        def piece(item_id, slots, own_mesh, covers=()):
            op = {"slots": slots, "outfit_types": ["casual"], "own_mesh": own_mesh, "covers": list(covers)}
            return inventory.add_item(name=item_id.title(), category="outfit_piece", item_id=item_id,
                                      prompt_fragment=f"a plain {item_id}", outfit_piece=op)["id"]

        dress = piece("dress", ["top", "bottom"], True)
        coat = piece("coat", ["outer"], True, covers=["top"])
        cape = piece("cape", ["outer"], True)
        shirt = piece("shirt", ["underwear_top"], False)
        check("ids", [dress, coat, cape, shirt], ["dress", "coat", "cape", "shirt"])
        for item in (cape, dress, coat, shirt):
            check(f"give {item}", inventory.add_to_inventory("Demo", item), True)
        for item in (cape, dress, coat):  # the coat displaces the cape from outer
            check(f"equip {item}", inventory.equip_piece("Demo", item, source="smoke")["status"], "ok")
        check("Demo pieces", sorted(inventory.get_equipped_pieces("Demo").items()),
              [("bottom", dress), ("outer", coat), ("top", dress)])
        check("give Offline dress", inventory.add_to_inventory("Offline", dress), True)
        check("equip Offline dress", inventory.equip_piece("Offline", dress, source="smoke")["status"], "ok")
        hair_spec = {"kind": "hair", "slot": "hair", "body_slot": "hair"}
        inventory.add_item(name="Hair", category="garment", owner="Demo", prompt_fragment="medium blonde hair",
                           garment=hair_spec, item_id="hair_demo", transferable=False, portable=False)
        check("wear hair", inventory.equip_mesh_piece("Demo", "hair_demo"), True)

        tokens = {}
        for role in (users.ROLE_ADMIN, users.ROLE_USER):
            uid = users.create_user("demo-" + role, "temporary-smoke-password", role,
                                    allowed_characters=["Demo", "Offline", "Other"])
            tokens[role] = sessions.create_session(uid)

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routes.characters import router
        app = FastAPI()
        app.include_router(router)

        with TestClient(app, raise_server_exceptions=False) as client:
            print("[1] player session")
            client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_USER])
            for url in ("/characters/Demo/garments", "/characters/Demo/garments/dress"):
                check(f"player GET {url}", client.get(url).status_code, 403)
            client.cookies.set(sessions.SESSION_COOKIE_NAME, tokens[users.ROLE_ADMIN])

            print("[2] GET one own-mesh piece")
            url = "/characters/Demo/garments/dress"
            r = client.get(url)
            body = r.json() if r.status_code == 200 else {}
            check("200", r.status_code, 200)
            check("head", {k: body.get(k) for k in ("pipeline", "item_id", "name", "kind", "own_mesh", "worn")},
                  {"pipeline": True, "item_id": "dress", "name": "Dress", "kind": "clothing", "own_mesh": True,
                   "worn": True})
            limits = body.get("limits") or {}
            check("clothing limits", (sorted(limits), limits.get("worn", {}).get("garment_share"),
                                      limits.get("ghost", {}).get("top_dy"),
                                      limits.get("mesh", {}).get("largest_component_share"),
                                      limits.get("fit", {}).get("max_push_m"),
                                      limits.get("fit", {}).get("rigged_inside_share"),
                                      limits.get("fit", {}).get("largest_component_share")),
                  (["fit", "ghost", "mesh", "worn"], {"op": "ge", "value": 0.01},
                   {"op": "abs_le", "value": 0.0055}, {"op": "ge", "value": 0.98},
                   {"op": "le", "value": 0.10}, {"op": "le", "value": 0.01}, {"op": "ge", "value": 0.98}))
            check("status, no base model", body.get("status"),
                  {"state": "missing", "step": None, "painted": True, "reason": base_body.BASE_MODEL_MISSING})
            g = body.get("garment") or {}
            check("garment kind + fsig", (g.get("kind"), bool(g.get("fsig"))), ("clothing", True))
            check("preview freshness", g.get("preview_freshness"),
                  {"state": "missing", "reason": "No provenance recorded"})
            check("step rows", [(r.get("id"), r.get("label"), r.get("status")) for r in body.get("steps") or []],
                  [("worn", "Worn views", "missing"), ("ghost", "Piece-only views", "missing"),
                   ("cutout", "Cut-outs", "missing"), ("mesh", "Mesh", "missing"), ("fit", "Fit", "missing")])
            for label, u in (("unflagged shirt", "/characters/Demo/garments/shirt"),
                             ("not held", "/characters/Other/garments/dress"),
                             ("unknown item", "/characters/Demo/garments/no_such_item"),
                             ("unknown character", "/characters/Nobody/garments/dress")):
                check(f"404 {label}", client.get(u).status_code, 404)

            print("[3] base model + an accepted worn image")
            bsig = base_body.base_signature("Demo")
            model = get_character_dir("Demo") / "model3d" / f"{bsig}.glb"
            model.parent.mkdir(parents=True, exist_ok=True)
            model.write_bytes(b"glTF-base")
            fsig = gs.garment_fsig("Demo", dress)
            final = gs.garment_path("Demo", dress, fsig, "image", step="worn", view="front")
            try1 = gs.garment_path("Demo", dress, fsig, "image", step="worn", view="front", attempt=1)
            final.parent.mkdir(parents=True, exist_ok=True)
            final.write_bytes(b"\x89PNG-final")
            try1.write_bytes(b"\x89PNG-try1")
            final.with_suffix(".json").write_text(json.dumps({"accepted": True}))
            body = client.get(url).json()
            tile = ((body.get("garment") or {}).get("steps") or {}).get("worn", {}).get("front") or {}
            check("tile freshness", ((tile.get("freshness") or {}).get("state"),
                                     [(a.get("attempt"), (a.get("freshness") or {}).get("state"))
                                      for a in tile.get("attempts") or []]),
                  ("current", [(1, "current")]))
            check("status images", body.get("status"),
                  {"state": "images", "step": None, "painted": True, "reason": base_body.NO_MESH_FIT})

            print("[4] persisted failure")
            gs.record_failure("Demo", dress, fsig, step="ghost", error="gate refused")
            body = client.get(url).json()
            failed = (body.get("garment") or {}).get("failed") or {}
            check("failed", {k: failed.get(k) for k in ("step", "error", "gates")},
                  {"step": "ghost", "error": "gate refused", "gates": None})
            check("status reason", (body.get("status") or {}).get("reason"), "ghost — gate refused")
            rows = {r.get("id"): (r.get("status"), r.get("detail")) for r in body.get("steps") or []}
            check("failed step row", (rows.get("worn"), rows.get("ghost")),
                  (("missing", ""), ("failed", "gate refused")))

            print("[5] the overview")
            r = client.get("/characters/Demo/garments")
            body = r.json() if r.status_code == 200 else {}
            items = body.get("items") or {}
            check("overview", (r.status_code, body.get("pipeline"), sorted(items)),
                  (200, True, ["cape", "coat", "dress"]))
            check("dress row", items.get("dress"),
                  {"state": "images", "step": None, "painted": True, "reason": "ghost — gate refused"})
            check("cape row", items.get("cape"),
                  {"state": "missing", "step": None, "painted": False, "reason": None})
            check("overlaps", body.get("overlaps"), [{"items": ["coat", "dress"], "slots": ["top"]}])
            body = client.get("/characters/Offline/garments").json()
            check("offline", (body.get("pipeline"), (body.get("items") or {}).get("dress", {}).get("painted"),
                              body.get("overlaps")), (False, False, []))
            check("other", client.get("/characters/Other/garments").json().get("items"), {})
            check("unknown character", client.get("/characters/Nobody/garments").status_code, 404)

            print("[6] piece_status")
            ps = garment_set.piece_status
            check("running", ps({"running_step": "mesh", "fsig": "f"}, worn=True, base_model_ready=True),
                  {"state": "running", "step": "mesh", "painted": True, "reason": base_body.NO_MESH_FIT})
            check("fitted", ps({"fsig": "f", "steps": {"fit": {"status": "accepted"}}}, worn=True,
                               base_model_ready=True),
                  {"state": "fitted", "step": None, "painted": False, "reason": None})
            check("mesh", ps({"fsig": "f", "steps": {"mesh": {"status": "accepted"}, "fit": {"status": "missing"}}},
                             worn=False, base_model_ready=True)["state"], "mesh")
            check("fit without fsig", ps({"fsig": None, "steps": {"fit": {"status": "accepted"}}}, worn=True,
                                         base_model_ready=True)["state"], "missing")

            print("[7] hair keeps its own limits")
            body = client.get("/characters/Demo/garments/hair_demo").json()
            limits = body.get("limits") or {}
            check("hair item", (body.get("kind"), body.get("own_mesh"), sorted(limits),
                                limits.get("fit", {}).get("bib_cm2"), (body.get("status") or {}).get("painted")),
                  ("hair", False, ["fit", "ghost", "haired", "mesh"], {"op": "le", "value": 50.0}, False))

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
