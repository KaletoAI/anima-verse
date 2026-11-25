"""Smoke: the one-time part migration (plan-anhaenger Task 5, ruling D1 "migrate",
``app/core/accessory_parts_migration.py``).

Usage: ./.venv/bin/python scripts/smoke_accessory_parts_migration.py   (no server; a temp world, a temp shared library)

Fixtures are written RAW (``_save_items`` / ``_save_shared_items``) in the format stored before part items:
necklace ``item_neck`` ``pendant: {from_image: true, size_mm: 22}`` with an image and an accepted pendant mesh under
``jewellery/item_neck/<psig of its image>/`` (``record.json {accepted: true, hub_jobs: 1}``); belt ``item_belt``
``buckle: {from_image: true, size_mm: 65}``; necklace ``item_bare`` with a pendant but no image; a shared necklace
``item_lib`` with a pendant and an image in the shared library.

Expected, by hand:

[1] ``item_neck_pendant`` exists (a part, no slot), its image byte-equal to the host's → the same psig →
    ``pendant_state == ready`` with the record moved as it was (``hub_jobs`` 1 from the copy — no new job);
    ``jewellery/item_neck/`` holds no psig folder any more; the host links ``{item: item_neck_pendant, size_mm: 22.0}``.
[2] the belt's ``buckle`` is None (stored and normalized).
[3] a second run → ``{necklaces: 0, belts: 0, meshes_moved: 0}``; the first run counted necklaces 2 (world: item_neck,
    item_bare) + 1 (shared: item_lib) = 3, belts 1, meshes_moved 1.
[4] ``item_bare_pendant`` has no image → the host's ``part_states`` says ``no_image``.
[5] "demo" owns and wears item_neck: after the migration the inventory still holds item_neck and NOT
    item_neck_pendant, and ``equipped_pieces`` is unchanged.
[6] the shared necklace's part ``item_lib_pendant`` is a shared item too (never a shared host with a world-only link).
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="smoke_parts_migration_")
SHARED = Path(tempfile.mkdtemp(prefix="smoke_parts_migration_shared_"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="smoke_parts_migration_clips_")
from app.core import paths  # noqa: E402

paths.init(TMP)
from app.core import db  # noqa: E402

db.init_schema()
import app.models.inventory as inv  # noqa: E402

inv._get_shared_dir = lambda: SHARED
from app.core import accessory_parts as parts, accessory_parts_migration as mig, accessory_pendant as ap  # noqa: E402
from app.core import accessory_spec  # noqa: E402
from app.models.character import get_character_profile, save_character_profile  # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (expected {want!r})"))
    if not ok:
        FAIL.append(name)


def raw_item(item_id, name, slots, jewellery, image=None):
    item = {"id": item_id, "name": name, "category": "outfit_piece", "prompt_fragment": name.lower(),
            "image": "image.png" if image else None,
            "outfit_piece": {"slots": slots, "mesh_mode": "accessory", "jewellery": jewellery}}
    if image:
        d = Path(TMP) / "items" / item_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "image.png").write_bytes(image)
    return item


inv._save_items([
    raw_item("item_neck", "Bone Amulet", ["neck"], {"kind": "necklace", "pendant": {"from_image": True, "size_mm": 22}},
             b"amulet-image"),
    raw_item("item_belt", "Copper Belt", ["outer"], {"kind": "belt", "buckle": {"from_image": True, "size_mm": 65}},
             b"belt-image"),
    raw_item("item_bare", "Plain Chain", ["neck"], {"kind": "necklace", "pendant": {"from_image": True, "size_mm": 18}}),
])
lib = raw_item("item_lib", "Library Chain", ["neck"], {"kind": "necklace", "pendant": {"from_image": True,
                                                                                       "size_mm": 20}})
(SHARED / "items" / "item_lib").mkdir(parents=True)
(SHARED / "items" / "item_lib" / "image.png").write_bytes(b"library-image")
inv._save_shared_items([lib])
psig = ap.current_psig("item_neck")
d = ap.pendant_dir("item_neck", psig)
d.mkdir(parents=True)
(d / "raw.glb").write_bytes(b"glb")
(d / "record.json").write_text(json.dumps({"accepted": True, "psig": psig, "hub_jobs": 1}))
save_character_profile("demo", {"name": "demo", "equipped_pieces": {"neck": "item_neck"}}, create_new=True)
inv._save_inventory("demo", {"inventory": [{"item_id": "item_neck", "quantity": 1}]})
worn_before = dict(get_character_profile("demo").get("equipped_pieces") or {})

first = mig.migrate_parts_once()
check("[3] first run", first, {"necklaces": 3, "belts": 1, "meshes_moved": 1})
part = inv.get_item("item_neck_pendant")
check("[1] part exists", (parts.is_part(part), part["outfit_piece"]["slots"]), (True, []))
check("[1] same psig", ap.current_psig("item_neck_pendant"), psig)
st = ap.pendant_state("item_neck_pendant")
check("[1] ready, no new job", (st["state"], (st["record"] or {}).get("hub_jobs")), ("ready", 1))
check("[1] host store emptied", [p.name for p in ap.item_dir("item_neck").glob("*") if p.is_dir()], [])
check("[1] host links it", accessory_spec.of_item(inv.get_item("item_neck"))["pendant"],
      {"item": "item_neck_pendant", "size_mm": 22.0})
check("[2] belt buckle gone (raw)", inv.get_item("item_belt")["outfit_piece"]["jewellery"]["buckle"], None)
check("[2] belt buckle gone (normalized)", accessory_spec.of_item(inv.get_item("item_belt"))["buckle"], None)
check("[3] second run", mig.migrate_parts_once(), {"necklaces": 0, "belts": 0, "meshes_moved": 0})
check("[4] no image", [p["state"] for p in parts.part_states(accessory_spec.of_item(inv.get_item("item_bare")))],
      ["no_image"])
check("[5] inventory", [e["item_id"] for e in inv._load_inventory("demo")["inventory"]], ["item_neck"])
check("[5] worn unchanged", dict(get_character_profile("demo").get("equipped_pieces") or {}), worn_before)
check("[6] library part shared", (inv.is_shared_item("item_lib_pendant"),
                                  accessory_spec.of_item(inv.get_item("item_lib"))["pendant"]),
      (True, {"item": "item_lib_pendant", "size_mm": 20.0}))

if FAIL:
    print(f"\n{len(FAIL)} check(s) failed: {FAIL}")
    sys.exit(1)
print("\nall checks passed")
