#!/usr/bin/env python3
"""Deleting a character deletes its hairstyles (``delete_character`` step 2b → ``hairstyle_delete.delete_owned_items``),
an orphan left by an older deletion goes through the public ``hairstyle_delete.delete_orphan``, and World Dev refuses
to delete (in a later turn) a character that owns hairstyles, because its snapshot holds no items.

Usage:
    ./.venv/bin/python scripts/smoke_character_delete_hairstyles.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real world,
no hub, no GPU, no server. Stubs (as in ``smoke_hairstyle_items_hidden.py``): ``figure_build.request`` and
``garment_assembly.schedule`` are recorders, ``figure.stored`` answers []; the session lookup of the auth gate reads
the role from a header.

FIXTURE (S = a 12-hex signature)
  Demo, Mira, Lena (human, created in this order).
  create_hairstyle(Demo, "medium blonde hair", "hairdeck") -> hair_demo (Demo's first: worn), then
  create_hairstyle(Demo, "long braided hair", "body") -> hair_demo_2; files garments/hair_demo_S1.glb and the media
  folder items/hair_demo/image.png.
  create_hairstyle(Mira, "short red hair", "body") -> hair_mira (worn).
  create_hairstyle(Lena, "black bob", "body") -> hair_lena.
  Shirt = add_item(outfit_piece, owner Demo) -> shirt_demo (owned by Demo, no hair item).
  O1 = add_item(hair garment, owner "Old") -> hair_old; "Old" is no stored character, but its folder
  characters/Old/garments/ still holds hair_old_S2.glb (O1's) and hair_old_2_S3.glb (an id that starts with
  "hair_old_" — no file of O1).

EXPECTED, BY HAND
[1] World Dev: _character_delete_blockers(Mira) names "owns 1 hairstyles" (hair_mira) — a later-turn delete would
    remove an item the character snapshot cannot bring back. For Demo "owns 2 hairstyles".
[2] delete_character(Demo) -> True. Afterwards: get_item(hair_demo) and get_item(hair_demo_2) are None, the folder
    items/hair_demo/ is gone, characters/Demo/ is gone; shirt_demo is still stored (only hair items go); hair_mira,
    hair_lena and hair_old are still stored. unneeded() lists no hairstyle with owner Demo.
[3] DELETE /characters/Lena (admin, real router) -> 200; hair_lena gone, hair_mira still there.
[4] Orphans: unneeded() = exactly [hair_old] (reason orphan) — the hairstyles of Demo and Lena did not become
    orphans. delete_orphan("Ghost", "hair_mira") -> ValueError (not Ghost's hairstyle), hair_mira stays.
    POST /characters/hairstyle-cleanup -> removed [(hair_old, orphan, deleted_files 1)]; hair_old_S2.glb gone,
    hair_old_2_S3.glb still there.
[5] hairstyle_sweep reaches hairstyle_delete only through public names: its source names no
    ``hairstyle_delete._…``.
"""
import json
import os
import re
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


def write(path: Path, data: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data or path.name)
    return path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="character-delete-hair-") as tmp:
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

        from app.core import figure, figure_build, garment_assembly, garment_hair, hairstyle_delete, hairstyle_sweep
        from app.models import inventory
        from app.models.character import (delete_character, get_character_dir, get_character_profile,
                                          save_character_profile)
        figure_build.request = lambda name, trigger: True
        garment_assembly.schedule = lambda name, signature=None: True
        figure.stored = lambda name: []
        figure.delete_stored = lambda name, key: {}
        from app.imagegen import service
        service.get_image_service = lambda *a, **k: types.SimpleNamespace()

        for name in ("Demo", "Mira", "Lena"):
            check(f"create {name}", save_character_profile(name, {
                "template": "human-roleplay", "age": 30, "gender": "female", "height": 170,
                "character_appearance": "slim", "body_slots": {"hair": {"length": "medium", "color": "blonde"}}},
                create_new=True), True)
        h1 = garment_hair.create_hairstyle("Demo", "medium blonde hair", "hairdeck")
        h2 = garment_hair.create_hairstyle("Demo", "long braided hair", "body")
        hm = garment_hair.create_hairstyle("Mira", "short red hair", "body")
        hl = garment_hair.create_hairstyle("Lena", "black bob", "body")
        check("ids", (h1, h2, hm, hl), ("hair_demo", "hair_demo_2", "hair_mira", "hair_lena"))
        inventory.add_item(name="Shirt", category="outfit_piece", owner="Demo", item_id="shirt_demo",
                           prompt_fragment="a shirt", outfit_piece={"slots": ["top"]})
        slot = garment_hair._check_hairstyle_owner("Mira", get_character_profile("Mira"))
        inventory.add_item(name="Old hair", category="garment", owner="Old", item_id="hair_old",
                           garment={"kind": "hair", "slot": "hair", "body_slot": slot.id, "mesh_mode": "body",
                                    "description": "grey hair"}, transferable=False, portable=False)
        with db.transaction() as conn:
            conn.execute("UPDATE items SET created_at='2026-01-01T00:00:00+00:00' WHERE id='hair_old'")
        s = "a0000000000{}"
        write(get_character_dir("Demo") / "garments" / f"hair_demo_{s.format(1)}.glb")
        media = write(paths.get_storage_dir() / "items" / h1 / "image.png")
        old_root = paths.get_storage_dir() / "characters" / "Old" / "garments"
        old_own = write(old_root / f"hair_old_{s.format(2)}.glb")
        old_other = write(old_root / f"hair_old_2_{s.format(3)}.glb")

        print("[1] World Dev blocker")
        from app.core import world_dev_tools
        check("Mira blocked", "owns 1 hairstyles" in world_dev_tools._character_delete_blockers("Mira"), True)
        check("Demo blocked", "owns 2 hairstyles" in world_dev_tools._character_delete_blockers("Demo"), True)

        print("[2] delete_character(Demo)")
        check("deleted", delete_character("Demo"), True)
        check("Demo's hairstyles gone", (inventory.get_item(h1), inventory.get_item(h2)), (None, None))
        check("media folder gone", media.parent.exists(), False)
        check("character folder gone", get_character_dir("Demo").exists(), False)
        check("shirt stays", inventory.get_item("shirt_demo") is not None, True)
        check("others stay", [inventory.get_item(i) is not None for i in (hm, hl, "hair_old")], [True, True, True])
        check("no orphan of Demo", [e["item_id"] for e in hairstyle_sweep.unneeded() if e["owner"] == "Demo"], [])

        print("[3] DELETE /characters/Lena")
        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient
        from app.core import auth_dependency
        from app.routes import characters as characters_route
        admin_user = {"id": "u_admin", "username": "demo", "role": "admin", "allowed_characters": []}

        def session_user(request: Request):
            return admin_user if request.headers.get("x-test-user") == "admin" else None
        auth_dependency._get_session_user = session_user
        app = FastAPI()
        app.middleware("http")(auth_dependency.auth_gate_middleware)
        app.middleware("http")(auth_dependency.user_context_middleware)
        app.include_router(characters_route.router)
        client = TestClient(app)
        admin = {"x-test-user": "admin"}
        check("DELETE status", client.delete("/characters/Lena", headers=admin).status_code, 200)
        check("Lena's hairstyle gone", inventory.get_item(hl), None)
        check("Mira's stays", inventory.get_item(hm) is not None, True)

        print("[4] orphans")
        check("unneeded", [(e["item_id"], e["reason"]) for e in hairstyle_sweep.unneeded()], [("hair_old", "orphan")])
        try:
            hairstyle_delete.delete_orphan("Ghost", hm)
            refused = False
        except ValueError:
            refused = True
        check("delete_orphan refuses another owner's", (refused, inventory.get_item(hm) is not None), (True, True))
        r = client.post("/characters/hairstyle-cleanup", headers=admin)
        check("cleanup status", r.status_code, 200)
        check("cleanup removed", [(e["item_id"], e["reason"], e["deleted_files"]) for e in r.json()["removed"]],
              [("hair_old", "orphan", 1)])
        check("O1's file gone, the other kept", (old_own.exists(), old_other.exists()), (False, True))

        print("[5] public names only")
        src = (ROOT / "app/core/hairstyle_sweep.py").read_text()
        check("no private hairstyle_delete name", re.findall(r"hairstyle_delete\._\w+", src), [])
    print("PASS" if not FAILS else f"FAIL: {len(FAILS)} — {', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
