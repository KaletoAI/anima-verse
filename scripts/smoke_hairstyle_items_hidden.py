#!/usr/bin/env python3
"""Hairstyles are no world items in the item displays, unneeded ones are removed with their files on a confirmed
"Clean up" (never on their own), and "New hairstyle" always mints a new item, also for a text and mode that exist
(``app/core/hairstyle_sweep.py``, ``garment_hair.create_hairstyle`` / ``is_hair_item``, ``app/routes/inventory.py``,
the world clean-up in ``app/routes/characters.py``).

Usage:
    ./.venv/bin/python scripts/smoke_hairstyle_items_hidden.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real world,
no hub, no GPU, no server. Stubs (as in ``smoke_hairstyle_delete.py``): ``figure_build.request`` and
``garment_assembly.schedule`` are recorders, ``figure.stored`` answers [] and ``figure.delete_stored`` is a
recorder; the session lookup of the auth gate reads the role from a header.

FIXTURE (S = a 12-hex signature; every hair item's ``created_at`` is set 30 days back unless named otherwise)
  Demo (human). H1 = create_hairstyle(Demo, "medium blonde hair", "hairdeck") -> hair_demo (the first: worn and
  the plain body's); files garments/hair_demo_S1.glb.
  H2 = create_hairstyle(Demo, "long braided hair", "body") -> hair_demo_2 — no files.
  H3 = create_hairstyle(Demo, "long braided hair", "haar") -> hair_demo_3 — files raw/hair_demo_3_S3/record.json,
       hair_demo_3_S4.glb, hair_demo_3_S4.json.
  H4 = _mint_hairstyle(Demo, "long braided hair", "haar") -> hair_demo_4 — the same mode and settings as H3; files raw/hair_demo_4_S5/record.json, hair_demo_4_S6.glb.
  H5 = _mint_hairstyle(Demo, "long braided hair", "haar", {hair_colour "#112233"}) -> hair_demo_5 — other
       settings; file hair_demo_5_S7.glb.
  H6 = _mint_hairstyle(Demo, "medium blonde hair", "body") -> hair_demo_6 — named by the outfit set "Party".
  H7 = _mint_hairstyle(Demo, "medium blonde hair", "body") -> hair_demo_7 — created NOW (inside the grace).
  H8 = _mint_hairstyle(Demo, "long braided hair", "body") -> hair_demo_8 — the same mode and settings as H2; no
       files (neither has any).
  O1 = add_item(hair garment, owner "Ghost") -> hair_ghost — no such character.
  O2 = add_item(hair garment, owner "Ghost") -> hair_ghost_2 — one inventory_items row (Demo) names it.
  Shirt = add_item(outfit_piece) -> shirt_demo.

EXPECTED, BY HAND
[1] No reuse: 10 hair items. create_hairstyle(Demo, "Long  Braided HAIR", "haar") — the text of H3 with other
    case and spacing, H3's mode — mints the next id "hair_demo_9" (text "Long Braided HAIR", whitespace folded,
    mode haar, settings {}), never "hair_demo_3": an alternative of the same text and mode differs only in its
    settings, which are set after creation (review 2026-11-27). The count is 11. H9 is then removed with
    inventory.delete_item (no files, referenced nowhere) so [2]-[6] see the 10 of the fixture again.
[2] unneeded(Demo) — groups by text + mode + settings (files never decide what goes, only which copy stays):
    ("long braided hair", haar, {}) = H3, H4: neither referenced, both with files, same stamp, id -> H3 kept, H4
    DUPLICATE of H3. ("long braided hair", haar, {hair_colour}) = H5 alone -> kept. ("long braided hair", body, {})
    = H2, H8: no files, same stamp, id -> H2 kept, H8 DUPLICATE of H2. So H2 — the same text as H3 in another
    mode, no files of its own — is an alternative and stays (the 95398e7c5 rule of this branch removed it).
    ("medium blonde hair", hairdeck) = H1 alone. ("medium blonde hair", body, {}) = H6, H7: H6 referenced (outfit
    set) -> first, kept; H7 inside the grace -> no candidate, kept.
    => {hair_demo_4: (duplicate, hair_demo_3), hair_demo_8: (duplicate, hair_demo_2)}.
    unneeded(None) adds hair_ghost (orphan, kept ""); hair_ghost_2 is referenced (inventory row) -> not listed.
[3] Routes (real router, admin header): GET /inventory/items (world items) lists exactly {shirt_demo} — none of
    the 10 hair items; with include_shared=1 still no item ``is_hair_item`` (the repo's shared library adds its own); GET /characters/Demo/hairstyles carries ``unneeded`` with the ids of [2];
    POST /inventory/items {category garment, garment {kind hair, slot hair}} -> 409; PUT /inventory/items/hair_demo
    -> 409; PUT /inventory/items/shirt_demo {category garment, garment {kind hair, slot hair}} -> 409; DELETE
    /inventory/items/hair_demo_5 -> 409 and hair_demo_5 still there; ``add_to_inventory(Demo, hair_demo_5)`` False.
    OLD CODE, pinned to main 9af31aef78dcffb30a44deeb077bbe0fb519d644: that commit's ``list_items_route`` (its
    source from git, run against this store) lists all 11 world items (8 + 2 + the shirt), the 10 hair
    items among them.
    GET /characters/hairstyle-cleanup (admin) -> the ids of unneeded(None); without a session -> 401, and
    POST without a session -> 401 (nothing removed); "hairstyle-cleanup" is a reserved route segment (no character
    can shadow the URL). The Items tab has no clean-up: no source under frontend/src/tabs/items/ names
    "hairstyle-cleanup", "/inventory/hairstyles" or HairstyleCleanup, and the router has no /inventory/hairstyles
    route; the character list (CharacterListPanel.tsx) mounts HairstyleCleanupButton.
    Import and store moves refuse hairstyles: POST /inventory/items/import with an item pack whose row is a hair
    item -> 409, the same with overwrite=true -> 409; an item pack of a plain garment under the id hair_demo_5
    (a stored hairstyle) with overwrite=true -> 409 and hair_demo_5 unchanged (equal to its row read before); a bundle pack holding the shirt and a hair row -> 409, nothing imported (no item "hair_new");
    POST /inventory/items/hair_demo_5/move-to-shared -> 409 and move-to-world -> 409, hair_demo_5 still a world
    item.
[4] POST /characters/Demo/hairstyles/cleanup -> removed {hair_demo_4, hair_demo_8}, skipped []; files: H4's 2
    gone, H3's 3 and H5's 1 and H1's 1 byte-identical; deleted_files of hair_demo_4 = 2, of hair_demo_8 = 0.
    Afterwards hair_ghost still there (orphans are the world clean-up's).
[5] POST /characters/hairstyle-cleanup (the character list's "Clean up hairstyles") -> removed [hair_ghost] (orphan,
    deleted_files 0); hair items left: hair_demo, hair_demo_2, hair_demo_3, hair_demo_5, hair_demo_6, hair_demo_7,
    hair_ghost_2. A second POST removes nothing. H1 still worn and the plain body's.
[6] Nothing removes on its own: periodic_jobs._SUB_TASKS has no label "hairstyle_sweep" and no job whose source
    names hairstyle_sweep.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OLD = "9af31aef78dcffb30a44deeb077bbe0fb519d644"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def write(path: Path, data: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data or path.name)
    return path


def sha(paths):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hairstyle-items-") as tmp:
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

        from app.core import figure, figure_build, garment_assembly, garment_hair, hairstyle_sweep
        from app.models import inventory
        from app.models.character import (add_character_outfit, get_character_dir, get_character_profile,
                                          save_character_profile)
        requests = []
        figure_build.request = lambda name, trigger: requests.append((name, trigger)) or True
        garment_assembly.schedule = lambda name, signature=None: True
        figure.stored = lambda name: []
        figure.delete_stored = lambda name, key: {}
        from app.imagegen import service
        service.get_image_service = lambda *a, **k: types.SimpleNamespace()

        check("create Demo", save_character_profile("Demo", {
            "template": "human-roleplay", "age": 30, "gender": "female", "height": 170,
            "character_appearance": "slim", "body_slots": {"hair": {"length": "medium", "color": "blonde"}}},
            create_new=True), True)
        slot = garment_hair._check_hairstyle_owner("Demo", get_character_profile("Demo"))
        h1 = garment_hair.create_hairstyle("Demo", "medium blonde hair", "hairdeck")
        h2 = garment_hair.create_hairstyle("Demo", "long braided hair", "body")
        h3 = garment_hair.create_hairstyle("Demo", "long braided hair", "haar")
        h4 = garment_hair._mint_hairstyle("Demo", slot.id, "long braided hair", "haar")["id"]
        h5 = garment_hair._mint_hairstyle("Demo", slot.id, "long braided hair", "haar",
                                          {"hair_colour": "#112233"})["id"]
        h6 = garment_hair._mint_hairstyle("Demo", slot.id, "medium blonde hair", "body")["id"]
        h7 = garment_hair._mint_hairstyle("Demo", slot.id, "medium blonde hair", "body")["id"]
        h8 = garment_hair._mint_hairstyle("Demo", slot.id, "long braided hair", "body")["id"]
        check("ids", (h1, h2, h3, h4, h5, h6, h7, h8),
              ("hair_demo", "hair_demo_2", "hair_demo_3", "hair_demo_4", "hair_demo_5", "hair_demo_6", "hair_demo_7",
               "hair_demo_8"))
        ghost = {"kind": "hair", "slot": "hair", "body_slot": slot.id, "mesh_mode": "body", "description": "grey hair"}
        inventory.add_item(name="Grey hair", category="garment", owner="Ghost", garment=ghost, item_id="hair_ghost",
                           transferable=False, portable=False)
        inventory.add_item(name="Grey hair 2", category="garment", owner="Ghost", garment=ghost,
                           item_id="hair_ghost_2", transferable=False, portable=False)
        inventory.add_item(name="Shirt", category="outfit_piece", item_id="shirt_demo", prompt_fragment="a shirt",
                           outfit_piece={"slots": ["top"]})
        add_character_outfit("Demo", {"name": "Party", "hairstyle": h6})
        with db.transaction() as conn:
            conn.execute("INSERT INTO inventory_items (character_name, item_id, quantity, acquired_at) "
                         "VALUES ('Demo', 'hair_ghost_2', 1, '2026-01-01T00:00:00+00:00')")
            conn.execute("UPDATE items SET created_at='2026-01-01T00:00:00+00:00' WHERE id LIKE 'hair_%' AND id<>?",
                         (h7,))
        g = get_character_dir("Demo") / "garments"
        s = "a0000000000{}"
        h1_files = [write(g / f"hair_demo_{s.format(1)}.glb")]
        h3_files = [write(g / f"raw/hair_demo_3_{s.format(3)}/record.json"),
                    write(g / f"hair_demo_3_{s.format(4)}.glb"), write(g / f"hair_demo_3_{s.format(4)}.json")]
        h4_files = [write(g / f"raw/hair_demo_4_{s.format(5)}/record.json"), write(g / f"hair_demo_4_{s.format(6)}.glb")]
        h5_files = [write(g / f"hair_demo_5_{s.format(7)}.glb")]
        kept_hashes = sha(h1_files + h3_files + h5_files)

        print("[1] no reuse")
        n_hair = lambda: len([i for i in inventory.list_items() if garment_hair.is_hair_item(i)])  # noqa: E731
        check("hair items", n_hair(), 10)
        h9 = garment_hair.create_hairstyle("Demo", "Long  Braided HAIR", "haar")
        check("same text + mode mints a new item", h9, "hair_demo_9")
        i9 = inventory.get_item(h9) or {}
        check("its text, mode, settings",
              (garment_hair.hairstyle_description(i9), garment_hair.hairstyle_mode(i9),
               garment_hair.hairstyle_settings(i9)), ("Long Braided HAIR", "haar", {}))
        check("hair items after create", n_hair(), 11)
        check("H9 removed again", inventory.delete_item(h9), True)
        check("hair items again", n_hair(), 10)

        print("[2] unneeded")
        demo = {e["item_id"]: (e["reason"], e["kept"]) for e in hairstyle_sweep.unneeded("Demo")}
        check("unneeded(Demo)", demo, {h4: ("duplicate", h3), h8: ("duplicate", h2)})
        world = {e["item_id"]: (e["reason"], e["kept"]) for e in hairstyle_sweep.unneeded()}
        check("unneeded(world)", world, {h4: ("duplicate", h3), h8: ("duplicate", h2), "hair_ghost": ("orphan", "")})

        print("[3] routes")
        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient
        from app.core import auth_dependency
        from app.routes import characters as characters_route
        from app.routes import inventory as inventory_route
        admin_user = {"id": "u_admin", "username": "demo", "role": "admin", "allowed_characters": []}

        def session_user(request: Request):
            return admin_user if request.headers.get("x-test-user") == "admin" else None
        auth_dependency._get_session_user = session_user
        app = FastAPI()
        app.middleware("http")(auth_dependency.auth_gate_middleware)
        app.middleware("http")(auth_dependency.user_context_middleware)
        app.include_router(characters_route.router)
        app.include_router(inventory_route.router)
        client = TestClient(app)
        admin = {"x-test-user": "admin"}
        r = client.get("/inventory/items", headers=admin)
        check("GET /inventory/items ids", sorted(i["id"] for i in r.json()["items"]), ["shirt_demo"])
        r = client.get("/inventory/items?include_shared=1", headers=admin)
        check("with the library: no hair item", [i["id"] for i in r.json()["items"] if garment_hair.is_hair_item(i)], [])
        r = client.get("/characters/Demo/hairstyles", headers=admin)
        check("GET hairstyles unneeded", sorted(e["item_id"] for e in r.json().get("unneeded", [])), sorted([h4, h8]))
        r = client.get("/characters/hairstyle-cleanup", headers=admin)
        check("GET world cleanup", sorted(e["item_id"] for e in r.json().get("unneeded", [])),
              sorted([h4, h8, "hair_ghost"]))
        check("GET world cleanup, no session", client.get("/characters/hairstyle-cleanup").status_code, 401)
        check("POST world cleanup, no session", client.post("/characters/hairstyle-cleanup").status_code, 401)
        from app.core.character_name import RESERVED_ROUTE_SEGMENTS
        check("hairstyle-cleanup reserved", "hairstyle-cleanup" in RESERVED_ROUTE_SEGMENTS, True)
        items_src = "".join(p.read_text() for p in sorted((ROOT / "frontend/src/tabs/items").rglob("*.ts*")))
        check("Items tab has no clean-up", [w for w in ("hairstyle-cleanup", "/inventory/hairstyles",
                                                        "HairstyleCleanup") if w in items_src], [])
        check("no /inventory/hairstyles route", [r.path for r in inventory_route.router.routes
                                                 if "/hairstyles" in getattr(r, "path", "")], [])
        check("character list mounts it", "<HairstyleCleanupButton" in (
            ROOT / "frontend/src/tabs/characters/CharacterListPanel.tsx").read_text(), True)
        check("nothing removed by it", inventory.get_item("hair_ghost") is not None, True)
        hair_body = {"name": "x", "category": "garment", "garment": {"kind": "hair", "slot": "hair"}}
        check("POST hair item", client.post("/inventory/items", json=hair_body, headers=admin).status_code, 409)
        check("PUT hairstyle", client.put(f"/inventory/items/{h1}", json={"name": "y"}, headers=admin).status_code, 409)
        check("PUT shirt into hair", client.put("/inventory/items/shirt_demo", json={
            "category": "garment", "garment": {"kind": "hair", "slot": "hair"}}, headers=admin).status_code, 409)
        check("DELETE hairstyle", client.delete(f"/inventory/items/{h5}", headers=admin).status_code, 409)
        check("hairstyle kept", inventory.get_item(h5) is not None, True)
        check("add_to_inventory hairstyle", inventory.add_to_inventory("Demo", h5), False)
        import io
        import zipfile

        def pack(kind, rows):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                manifest = {"version": 1, "type": kind}
                if kind == "item":
                    manifest["item_id"] = rows[0]["id"]
                zf.writestr("manifest.json", json.dumps(manifest))
                zf.writestr("db/items.json", json.dumps(rows))
            return buf.getvalue()

        def post_pack(data, overwrite=False):
            return client.post(f"/inventory/items/import?overwrite={'true' if overwrite else 'false'}",
                               files={"file": ("p.zip", data, "application/zip")}, headers=admin).status_code
        hair_row = {"id": "hair_new", "name": "New hair", "category": "garment", "owner": "Demo",
                    "garment": {"kind": "hair", "slot": "hair"}}
        check("import hair item", post_pack(pack("item", [hair_row])), 409)
        check("import hair item, overwrite", post_pack(pack("item", [hair_row]), True), 409)
        h5_before = inventory.get_item(h5)
        plain = {"id": h5, "name": "Scarf", "category": "garment", "garment": {"kind": "scarf", "slot": "neck"}}
        check("import over a hairstyle, overwrite", post_pack(pack("item", [plain]), True), 409)
        check("hairstyle unchanged", inventory.get_item(h5) == h5_before and h5_before is not None, True)
        shirt_row = {**(inventory.get_item("shirt_demo") or {}), "id": "shirt_demo"}
        check("import bundle with a hair row", post_pack(pack("item_bundle", [shirt_row, hair_row]), True), 409)
        check("nothing imported", inventory.get_item("hair_new"), None)
        check("move-to-shared hairstyle", client.post(f"/inventory/items/{h5}/move-to-shared", json={},
                                                      headers=admin).status_code, 409)
        check("move-to-world hairstyle", client.post(f"/inventory/items/{h5}/move-to-world", json={},
                                                     headers=admin).status_code, 409)
        check("still a world item", inventory.is_shared_item(h5), False)
        old = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:app/routes/inventory.py"],
                             capture_output=True, text=True)
        if old.returncode != 0:
            check("old source readable", old.stderr.strip(), "")
        else:
            namespace = {"__name__": "old_inventory_routes"}
            exec(compile(old.stdout, "old_inventory_routes.py", "exec"), namespace)
            old_ids = sorted(i["id"] for i in namespace["list_items_route"](include_shared=0)["items"])
            check(f"OLD {OLD[:9]} list holds the hair items", (len(old_ids), len([i for i in old_ids
                                                                                    if i.startswith("hair_")])), (11, 10))

        print("[4] Clean up (one character)")
        r = client.post("/characters/Demo/hairstyles/cleanup", headers=admin)
        check("cleanup status", r.status_code, 200)
        body = r.json()
        check("cleanup removed", {e["item_id"]: e["deleted_files"] for e in body["removed"]}, {h4: 2, h8: 0})
        check("cleanup skipped", body["skipped"], [])
        check("H4 files gone", [p.exists() for p in h4_files], [False, False])
        check("kept files byte-identical", sha(h1_files + h3_files + h5_files), kept_hashes)
        check("orphan still there", inventory.get_item("hair_ghost") is not None, True)

        print("[5] Clean up hairstyles (world, character list)")
        r = client.post("/characters/hairstyle-cleanup", headers=admin)
        check("world cleanup status", r.status_code, 200)
        report = r.json()
        check("world cleanup removed", [(e["item_id"], e["reason"], e["deleted_files"]) for e in report["removed"]],
              [("hair_ghost", "orphan", 0)])
        left = sorted(i["id"] for i in inventory.list_items() if garment_hair.is_hair_item(i))
        check("hair items left", left, [h1, h2, h3, h5, h6, h7, "hair_ghost_2"])
        check("second world cleanup", client.post("/characters/hairstyle-cleanup", headers=admin).json(),
              {"removed": [], "skipped": []})
        profile = get_character_profile("Demo")
        check("H1 still worn + plain", (garment_hair.worn_hair_id("Demo", profile),
                                        profile.get(garment_hair.BASE_HAIRSTYLE_KEY)), (h1, h1))
        check("no Build requested", requests, [])

        print("[6] nothing runs on its own")
        import inspect
        from app.core import periodic_jobs
        check("no periodic hairstyle job", [lab for f, iv, lab in periodic_jobs._SUB_TASKS
                                            if lab == "hairstyle_sweep" or "hairstyle_sweep" in inspect.getsource(f)],
              [])
    print("PASS" if not FAILS else f"FAIL: {len(FAILS)} — {', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
