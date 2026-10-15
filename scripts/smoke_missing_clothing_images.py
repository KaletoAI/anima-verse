#!/usr/bin/env python3
"""Smoke: fill missing clothing images without replacing existing images.

Usage: ./.venv/bin/python scripts/smoke_missing_clothing_images.py

Hand-derived contract: only world items in category outfit_piece whose selected
image file is absent are candidates. A dangling image name is still missing;
a present selected image is not. Items deleted or recategorized after a scan
need no render. A completed image appearing while queued must not be replaced.

Run the real improvement engine, routing, item producer and DB/file publication
against temporary storage. Only the external GPU backend and rembg are replaced.
Backend load must leave attempts at zero; a real failure consumes one attempt.
"""
import io
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="missing-clothing-") as tmp:
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
        from app.imagegen.base import BackendBusyError, ImageBackend
        from app.imagegen.selection import BackendPool
        from app.models import inventory
        from PIL import Image

        improvement_type = registry.get("fill_missing")
        params = improvement_type.validate({"subject": "clothing_images"})

        def piece(name):
            return inventory.add_item(name, category="outfit_piece",
                                      outfit_piece={"slots": ["top"]})["id"]

        def keys():
            return [c.key for c in improvement_type.find_candidates(params)]

        missing = piece("Demo shirt")
        dangling = piece("Demo boots")
        present = piece("Demo coat")
        inventory.add_item("Demo tool", category="tool")
        inventory.update_item(dangling, {"image": "gone.png"})
        inventory.update_item(present, {"image": "kept.png"})
        present_dir = paths.get_storage_dir() / "items" / present
        present_dir.mkdir(parents=True)
        kept = present_dir / "kept.png"
        kept.write_bytes(b"keep this image")
        assert keys() == [f"item:{dangling}", f"item:{missing}"], keys()
        print("OK: missing and dangling clothing images only; stable label order")

        candidates = {c.key: c for c in improvement_type.find_candidates(params)}
        deleted = piece("Demo deleted")
        changed = piece("Demo recategorized")
        stale = {c.key: c for c in improvement_type.find_candidates(params)}
        inventory.delete_item(deleted)
        inventory.update_item(changed, {"category": "tool"})
        for item_id in (deleted, changed):
            candidate = stale[f"item:{item_id}"]
            assert improvement_type.is_done(candidate, params)
            improvement_type.apply(candidate, params, "")
        assert not (paths.get_storage_dir() / "items" / deleted).exists()
        print("OK: deleted and recategorized candidates need no render")

        blob = io.BytesIO()
        Image.new("RGB", (16, 16), (70, 80, 90)).save(blob, "PNG")

        class Backend(ImageBackend):
            def __init__(self):
                super().__init__("demo-image", "http://localhost", 0, "fake", "SMOKE_")
                self.category = "txt2img"
                self.instance_enabled = True
                self._available = True
                self.error = None

            def check_availability(self):
                self.available = True
                return True

            def _generate(self, prompt, negative_prompt, render_params):
                if self.error:
                    raise self.error
                return [blob.getvalue()]

        backend = Backend()
        cfg = config.get_all()
        cfg["image_generation"]["routing"] = {"item": ["demo-image"]}
        config.save(cfg)
        with patch.object(service.ImageService, "_load_instances", return_value=[]):
            svc = service.ImageService()
        svc.enabled = True
        svc._pool = BackendPool([backend])
        with patch.object(service, "get_image_service", return_value=svc), \
                patch.object(service.ImageService, "run_on_backend_channel",
                             side_effect=lambda b, generate, **kw: generate()), \
                patch("app.models.character.postprocess_outfit_image", side_effect=lambda p: p):
            entry = store.create("fill_missing", "Demo clothing", params, "one_shot")
            engine.scan(entry["id"])
            payload = {"improvement_id": entry["id"],
                       "candidate_key": f"item:{missing}"}
            svc._pool = BackendPool([])
            assert "busy" in engine.handle_step(payload)
            step = next(s for s in store.list_steps(entry["id"])
                        if s["candidate_key"] == f"item:{missing}")
            assert (step["status"], step["attempts"]) == ("pending", 0), step
            svc._pool = BackendPool([backend])
            print("OK: an unavailable routing chain waits without consuming an attempt")

            backend.error = BackendBusyError("demo GPU busy")
            assert "busy" in engine.handle_step(payload)
            step = next(s for s in store.list_steps(entry["id"])
                        if s["candidate_key"] == f"item:{missing}")
            assert (step["status"], step["attempts"]) == ("pending", 0), step
            print("OK: backend load leaves the step pending without an attempt")

            backend.error = RuntimeError("demo render failed")
            assert "error" in engine.handle_step(payload)
            step = next(s for s in store.list_steps(entry["id"])
                        if s["candidate_key"] == f"item:{missing}")
            assert (step["status"], step["attempts"]) == ("pending", 1), step
            print("OK: real generation failure is not reported as success")

            backend.error = None
            backend.clear_cooldown()
            assert engine.handle_step(payload) == {"ok": True}
            image_path = Path(inventory.get_item_image_path(missing))
            assert image_path.read_bytes() == blob.getvalue()
            meta = inventory.get_item(missing)["image_meta"]
            assert meta["routing"] == {"occasion": "item", "position": 1,
                                       "spec": "demo-image"}, meta
            assert improvement_type.is_done(candidates[f"item:{missing}"], params)
            assert keys() == [f"item:{dangling}"]
            print("OK: engine publishes the image and routing metadata; candidate disappears")

            backend.error = AssertionError("an existing image must not be rendered again")
            improvement_type.apply(candidates[f"item:{missing}"], params, "")
            assert image_path.read_bytes() == blob.getvalue()
            assert kept.read_bytes() == b"keep this image"
            print("OK: queued candidates cannot replace an image filled in the meantime")
        print("Missing clothing image smoke passed")


if __name__ == "__main__":
    main()
