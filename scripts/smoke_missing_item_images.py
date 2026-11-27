#!/usr/bin/env python3
"""Smoke: the ``item_images`` improvement fills the image of every item kind that has none.

Usage: ./.venv/bin/python scripts/smoke_missing_item_images.py

Hand-derived contract (``app/core/improvements/types/item_images.py``):

* A candidate is a WORLD item, or a SHARED-library item this world reaches (held in an inventory, worn, placed in a
  room, or a part such an item links), whose selected image file is absent — no image name, or a dangling one.
* Not a candidate: a hairstyle (garment kind hair), any other ``garment`` item (mesh-only), a WORLD outfit piece
  (the clothing images of ``fill_missing`` cover it — part items are outfit pieces, so a world part too), a shared
  item no inventory or room of this world reaches, and an item whose image is present.
* A shared outfit piece the world reaches IS a candidate: the clothing images take world pieces only.
* Key ``item:<id>:<t>``, <t> = first 12 hex of sha256 over the JSON [image_prompt, prompt_fragment, name]
  (``ikey``); the label is the item name; order by (label lower-case, key).
* ``invalid_reason``: "" for a live subject; "item deleted" once deleted; the exclusion reason once the item turned
  into a world outfit piece; it RAISES when the item table cannot be read.
* The create dialog's reads (``GET /improvements/types``, ``POST /improvements/preview``) list the type with its
  description and preview the same 9 candidates.
* The engine's validity pass drops the stored step of an item deleted after the scan.
* ``is_done`` (fulfilled) once the item has an image; an image that appears while the step waits is never replaced.

The world is a temp dir; the shared library is a temp dir too (``inventory._get_shared_dir`` patched), so the
repo's ``shared/items`` is never read or written. The real engine, routing, item producer and DB/file publication
run; only the GPU backend, the backend channel and rembg are stubbed.

Expected set, by hand from the fixture below (labels sorted case-insensitively):
  Demo bread (consumable, dangling image) · Demo compass (shared tool, in demo's inventory) ·
  Demo hat (shared outfit piece, worn by demo — equipped_pieces) ·
  Demo lantern (tool) · Demo letter (document, image_prompt set) · Demo map (shared tool, in a room) ·
  Demo pendant (shared part of the shared necklace) · Demo scarf (shared outfit piece, in demo's inventory) ·
  Demo spark (spell)
Excluded: Demo shirt + Demo charm (world outfit pieces, the charm a part) · Demo braid (hairstyle) ·
  Demo tail (garment) · Demo coat (tool with its image) · Demo coin (shared, not reached) ·
  Demo necklace (shared, reached, but has its image).
"""
import hashlib
import io
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="missing-items-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import config, db
        config.load(paths.get_storage_dir() / "config.json",
                    paths.get_instance_config_path())
        db.init_schema()
        from app.core.improvements import engine, registry, store
        import app.core.improvements.types  # noqa: F401
        from app.imagegen import service
        from app.imagegen.base import ImageBackend
        from app.imagegen.selection import BackendPool
        from app.models import inventory
        from app.models.world import upsert_location
        from PIL import Image

        shared_root = root / "shared"
        shared_patch = patch.object(inventory, "_get_shared_dir", return_value=shared_root)
        shared_patch.start()

        improvement_type = registry.get("item_images")
        params = improvement_type.validate({})
        assert params == {"image_backend": ""}, params
        assert improvement_type.description, "the create dialog shows a description"

        texts = {}

        def item(name, category="tool", image_prompt="", **kw):
            item_id = inventory.add_item(name, category=category, image_prompt=image_prompt, **kw)["id"]
            texts[item_id] = [image_prompt, "", name]
            return item_id

        def ikey(item_id):
            token = hashlib.sha256(json.dumps(texts[item_id]).encode("utf-8")).hexdigest()[:12]
            return f"item:{item_id}:{token}"

        def keys():
            return [c.key for c in improvement_type.find_candidates(params)]

        # --- world items ---------------------------------------------------------------------------------------
        lantern = item("Demo lantern")
        bread = item("Demo bread", "consumable")
        inventory.update_item(bread, {"image": "gone.png"})
        letter = item("Demo letter", "document", image_prompt="a folded letter with a wax seal")
        spark = item("Demo spark", "spell")
        coat = item("Demo coat")
        inventory.update_item(coat, {"image": "kept.png"})
        (paths.get_storage_dir() / "items" / coat).mkdir(parents=True)
        kept = paths.get_storage_dir() / "items" / coat / "kept.png"
        kept.write_bytes(b"keep this image")
        item("Demo shirt", "outfit_piece", outfit_piece={"slots": ["top"]})
        item("Demo charm", "outfit_piece",
             outfit_piece={"slots": [], "mesh_mode": "accessory", "jewellery": {"kind": "charm"}})
        item("Demo braid", "garment", garment={"kind": "hair", "slot": "hair"})
        item("Demo tail", "garment", garment={"kind": "tail", "slot": "tail"})

        # --- shared library ------------------------------------------------------------------------------------
        def shared(item_id, name, category="tool", **kw):
            texts[item_id] = ["", "", name]
            return {"id": item_id, "name": name, "category": category, **kw}

        inventory._save_shared_items([
            shared("item_democompass", "Demo compass"),
            shared("item_demomap", "Demo map"),
            shared("item_democoin", "Demo coin"),
            shared("item_demohat", "Demo hat", "outfit_piece", outfit_piece={"slots": ["head"]}),
            shared("item_demoscarf", "Demo scarf", "outfit_piece", outfit_piece={"slots": ["neck"]}),
            shared("item_demonecklace", "Demo necklace", "outfit_piece", image="n.png",
                   outfit_piece={"slots": ["neck"],
                                 "jewellery": {"kind": "necklace", "pendant": {"item": "item_demopendant"}}}),
            shared("item_demopendant", "Demo pendant", "outfit_piece",
                   outfit_piece={"slots": [], "mesh_mode": "accessory", "jewellery": {"kind": "charm"}}),
        ])
        (shared_root / "items" / "item_demonecklace").mkdir(parents=True)
        (shared_root / "items" / "item_demonecklace" / "n.png").write_bytes(b"necklace")
        assert inventory.get_item("item_demonecklace")["_shared"]
        from app.core.accessory_parts import part_ids_of
        assert part_ids_of(inventory.get_item("item_demonecklace")) == ["item_demopendant"]
        from app.models.character import save_character_profile
        assert save_character_profile("demo", {"name": "demo", "equipped_pieces": {"head": "item_demohat"}},
                                      create_new=True)
        for item_id in ("item_democompass", "item_demoscarf", "item_demonecklace"):
            assert inventory.add_to_inventory("demo", item_id), item_id
        upsert_location({"id": "loc_demo", "name": "Demo square",
                         "rooms": [{"id": "hall", "name": "Hall", "items": []}]}, sync_world=False)
        assert inventory.add_item_to_room("loc_demo", "hall", "item_demomap")

        expected = [ikey(bread), ikey("item_democompass"), ikey("item_demohat"), ikey(lantern), ikey(letter),
                    ikey("item_demomap"),
                    ikey("item_demopendant"), ikey("item_demoscarf"), ikey(spark)]
        assert keys() == expected, keys()
        labels = [c.label for c in improvement_type.find_candidates(params)]
        assert labels == ["Demo bread", "Demo compass", "Demo hat", "Demo lantern", "Demo letter", "Demo map",
                          "Demo pendant", "Demo scarf", "Demo spark"], labels
        print("OK: every item kind without an image, shared items only in scope, exclusions hold")

        # What the create dialog reads: the type with its description and its one optional field, and the preview.
        from app.routes import improvements as improvements_route
        listed = next(t for t in improvements_route.list_types() if t["id"] == "item_images")
        assert listed["description"] == improvement_type.description
        assert [(f["key"], f["kind"], f["required"]) for f in listed["params_schema"]] == \
            [("image_backend", "image_backend", False)], listed["params_schema"]
        shown = improvements_route.preview(improvements_route.PreviewBody(type_id="item_images", params={}))
        assert shown["count"] == 9 and [x["label"] for x in shown["sample"]] == labels, shown
        print("OK: the create dialog lists the type with its description; the preview shows the 9 candidates")

        # The clothing subject keeps its own set: the two world pieces, never the general items.
        clothing = registry.get("fill_missing")
        cparams = clothing.validate({"subject": "clothing_images"})
        clothing_ids = {c.key.split(":")[1] for c in clothing.find_candidates(cparams)}
        assert not clothing_ids & {k.split(":")[1] for k in expected}, clothing_ids
        print("OK: no candidate is shared with the clothing images")

        # --- invalid / fulfilled -------------------------------------------------------------------------------
        stale = {c.key: c for c in improvement_type.find_candidates(params)}
        assert improvement_type.invalid_reason(ikey(spark), params) == ""
        assert improvement_type.invalid_reason("prop:x:y", params) == "not an item key"
        inventory.delete_item(bread)
        assert improvement_type.invalid_reason(ikey(bread), params) == "item deleted"
        assert improvement_type.is_done(stale[ikey(bread)], params)
        improvement_type.apply(stale[ikey(bread)], params, "")
        assert not (paths.get_storage_dir() / "items" / bread).exists()
        inventory.update_item(spark, {"category": "outfit_piece", "outfit_piece": {"slots": ["top"]}})
        assert improvement_type.invalid_reason(ikey(spark), params) == \
            "world clothing (covered by the clothing images)"
        with patch.object(inventory, "get_connection", side_effect=sqlite3.OperationalError("locked")):
            try:
                improvement_type.invalid_reason(ikey(lantern), params)
            except sqlite3.OperationalError:
                pass
            else:
                raise AssertionError("an unreadable item table must raise, not judge")
            try:
                improvement_type.find_candidates(params)
            except sqlite3.OperationalError:
                pass
            else:
                raise AssertionError("an unreadable item table must not read as 'no items'")
        print("OK: deleted / excluded items are invalid; an unreadable table raises")

        # --- the engine renders one step through the routed item producer -----------------------------------------
        blob = io.BytesIO()
        Image.new("RGB", (16, 16), (70, 80, 90)).save(blob, "PNG")

        class Backend(ImageBackend):
            def __init__(self):
                super().__init__("demo-image", "http://localhost", 0, "fake", "SMOKE_")
                self.category = "txt2img"
                self.instance_enabled = True
                self._available = True
                self.prompts = []

            def check_availability(self):
                self.available = True
                return True

            def _generate(self, prompt, negative_prompt, render_params):
                self.prompts.append(prompt)
                return [blob.getvalue()]

        backend = Backend()
        cfg = config.get_all()
        cfg["image_generation"]["routing"] = {"item": ["demo-image"]}
        config.save(cfg)
        with patch.object(service.ImageService, "_load_instances", return_value=[]):
            svc = service.ImageService()
        svc.enabled = True
        svc._pool = BackendPool([backend])
        channel_calls = []

        def channel(b, generate, **kw):
            channel_calls.append((b.name, kw.get("task_type")))
            return generate()

        with patch.object(service, "get_image_service", return_value=svc), \
                patch.object(service.ImageService, "run_on_backend_channel", side_effect=channel), \
                patch("app.models.character.postprocess_outfit_image", side_effect=lambda p: p):
            door_key = item("Demo key", "key")
            entry = store.create("item_images", "Demo items", params, "one_shot")
            engine.scan(entry["id"])
            assert ikey(door_key) in {s["candidate_key"] for s in store.list_steps(entry["id"])}
            assert engine.remove_invalid(entry["id"], explicit=True)["removed"] == 0
            inventory.delete_item(door_key)
            removed = engine.remove_invalid(entry["id"], explicit=True)
            assert removed["removed"] == 1, removed
            assert ikey(door_key) not in {s["candidate_key"] for s in store.list_steps(entry["id"])}
            print("OK: the engine drops the pending step of a deleted item")
            assert engine.handle_step({"improvement_id": entry["id"],
                                       "candidate_key": ikey(letter)}) == {"ok": True}
            assert channel_calls == [("demo-image", "item_image")], channel_calls
            assert "a folded letter with a wax seal" in backend.prompts[0], backend.prompts
            path = Path(inventory.get_item_image_path(letter))
            assert path.read_bytes() == blob.getvalue()
            meta = inventory.get_item(letter)["image_meta"]
            assert meta["routing"] == {"occasion": "item", "position": 1, "spec": "demo-image"}, meta
            assert improvement_type.is_done(stale[ikey(letter)], params)
            assert ikey(letter) not in keys()
            print("OK: a step renders on the item occasion's backend channel and publishes the image")

            # An image that arrived while the step waited is never replaced.
            inventory.update_item(lantern, {"image": "manual.png"})
            (paths.get_storage_dir() / "items" / lantern).mkdir(parents=True)
            manual = paths.get_storage_dir() / "items" / lantern / "manual.png"
            manual.write_bytes(b"manual")
            improvement_type.apply(stale[ikey(lantern)], params, "")
            assert manual.read_bytes() == b"manual" and len(channel_calls) == 1
            assert kept.read_bytes() == b"keep this image"
            print("OK: an image filled meanwhile is kept, the step only reads as fulfilled")

        assert keys() == [ikey("item_democompass"), ikey("item_demohat"), ikey("item_demomap"),
                          ikey("item_demopendant"), ikey("item_demoscarf")], keys()
        shared_patch.stop()
        print("Missing item image smoke passed")


if __name__ == "__main__":
    main()
