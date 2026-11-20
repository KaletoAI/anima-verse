#!/usr/bin/env python3
"""Smoke: A224 — the worn-piece mode ``painted`` is gone; the boot migration moves every stored piece
(``app/core/painted_mode_migration.py``).

Usage:
    ./.venv/bin/python scripts/smoke_painted_mode_migration.py

Runs in a temp world (``paths.init(<tmp>)`` before any world-DB import) with a temp shared items file
(``inventory._get_shared_items_file`` redirected); the tracked ``shared/items/items.json`` is never read or written.
No server, no hub, no network.

Expected by hand from the explicit table (user decisions 2026-11-19):

  shared file: N = item_936518eb painted, B = item_0b35fb92 painted, A = item_silver_anklets painted,
               C = item_silver_chain_bra painted, X = shared_x painted, K = shared_k own_mesh, note "keep me"
  world items: W1 = world_w1 painted, W2 = world_w2 in_body
  profile T: garment_paint_colours + outfit_references + a kept key ``height``; profile U: neither key.

[1] the first call moves: N -> accessory/necklace, B -> accessory/belt, A, C, X, W1 -> in_body (6 changes);
    K stays own_mesh, W2 stays in_body; N's ``jewellery.kind`` == "necklace", B's == "belt"; no item anywhere is
    still ``painted``; the shared file keeps ``note`` and has the marker; T lost both keys and kept ``height``;
    the result names only T; the world flag is set.
[2] the second call returns None and leaves the shared file's bytes alone (idempotent).
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def piece(item_id, mode):
    return {"id": item_id, "name": item_id, "category": "outfit_piece",
            "outfit_piece": {"slots": ["top"], "mesh_mode": mode}}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="painted-mode-") as tmp:
        root = Path(tmp)
        for k, v in {"STORAGE_DIR": root / "world", "INSTANCE_DIR": root / "instance",
                     "ANIMATION_CLIPS_DIR": root / "clips", "ANIMATION_RIG_FILE": root / "reference.fbx"}.items():
            os.environ[k] = str(v)
        (root / "instance").mkdir()
        from app.core import paths
        paths.init(root / "world")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config, db
        config.load(paths.get_config_path(), instance_path=root / "instance" / "config.json")
        db.init_schema()
        from app.models import inventory
        shared = root / "shared" / "items.json"
        shared.parent.mkdir()
        inventory._get_shared_items_file = lambda: shared
        shared.write_text(json.dumps({"items": [
            piece("item_936518eb", "painted"), piece("item_0b35fb92", "painted"),
            piece("item_silver_anklets", "painted"), piece("item_silver_chain_bra", "painted"),
            piece("shared_x", "painted"), piece("shared_k", "own_mesh")], "note": "keep me"}))
        check("world items saved", bool(inventory._save_items([piece("world_w1", "painted"),
                                                                piece("world_w2", "in_body")])), True)
        from app.models.character import get_character_profile, save_character_profile
        base = {"template": "human-roleplay", "gender": "female", "age": 30}
        check("create T", save_character_profile("T", {**base, "height": 170, "garment_paint_colours": {"x": "#fff"},
                                                       "outfit_references": {"k": {}}}, create_new=True), True)
        check("create U", save_character_profile("U", dict(base), create_new=True), True)
        from app.core import painted_mode_migration as pm
        from app.models.world import get_world_setting

        print("[1] first call")
        result = pm.migrate_painted_mode_once() or {}
        moved = {c["item"]: (c["to"], c["kind"]) for c in result.get("items", [])}
        check("changes", moved, {"item_936518eb": ("accessory", "necklace"), "item_0b35fb92": ("accessory", "belt"),
                                 "item_silver_anklets": ("in_body", ""), "item_silver_chain_bra": ("in_body", ""),
                                 "shared_x": ("in_body", ""), "world_w1": ("in_body", "")})
        data = json.loads(shared.read_text())
        modes = {i["id"]: i["outfit_piece"]["mesh_mode"] for i in data["items"]}
        modes.update({i["id"]: i["outfit_piece"]["mesh_mode"] for i in inventory._load_items(strict=True)})
        check("K kept", modes["shared_k"], "own_mesh")
        check("W2 kept", modes["world_w2"], "in_body")
        check("nothing painted", sorted(k for k, v in modes.items() if v == "painted"), [])
        kinds = {i["id"]: (i["outfit_piece"].get("jewellery") or {}).get("kind") for i in data["items"]}
        check("necklace kind", kinds["item_936518eb"], "necklace")
        check("belt kind", kinds["item_0b35fb92"], "belt")
        check("note kept", data.get("note"), "keep me")
        check("shared marker", bool(data.get(pm.SHARED_KEY)), True)
        t = get_character_profile("T") or {}
        check("T keys gone", [k for k in pm.PROFILE_KEYS if k in t], [])
        check("T height kept", t.get("height"), 170)
        check("profiles", result.get("profiles"), ["T"])
        check("world flag", bool(get_world_setting(pm.FLAG, strict=True)), True)

        print("[2] second call")
        before = shared.read_bytes()
        check("second call", pm.migrate_painted_mode_once(), None)
        check("bytes identical", shared.read_bytes() == before, True)
    print("FAILED: " + ", ".join(FAILS) if FAILS else "all pass")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
