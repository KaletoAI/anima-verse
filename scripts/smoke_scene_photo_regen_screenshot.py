#!/usr/bin/env python3
"""Task 109: screenshot composition survives gallery regeneration.

Usage: ./.venv/bin/python scripts/smoke_scene_photo_regen_screenshot.py

Hand oracle: a successful screenshot photo owns one byte-identical companion
and consumes its disposable upload/owner. With three slots, regeneration uses
the companion first, then Ann/Bob's original outfit references, never room or
generated photo; the composition instruction occurs once and CGI negatives
survive a dialog override. Unchecked, missing and legacy sources use normal
references. New variants own independent copies even when unchecked; overwrite
keeps ownership. Both gallery delete routes and media cleanup remove the
companion. Exports, gallery listings and media scans exclude the private file.
All DB access follows temporary paths.init; only generation/LLM inputs are faked.
"""
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TEMP = tempfile.TemporaryDirectory(prefix="photo-regen-screenshot-")
os.environ["STORAGE_DIR"] = TEMP.name
os.environ["INSTANCE_DIR"] = TEMP.name
from app.core import paths
paths.init(TEMP.name)
paths.init_instance(TEMP.name)
from app.core import db, scene_photo
db.init_schema()
from app.core import prompt_builder as pb
from app.imagegen import service
from app.models import character
from app.skills import image_regenerate as ir
from PIL import Image

buffer = io.BytesIO()
Image.new("RGB", (4, 4), "blue").save(buffer, "JPEG")
SCREENSHOT = buffer.getvalue()
Image.new("RGB", (4, 4), "red").save(buffer := io.BytesIO(), "PNG")
GENERATED = buffer.getvalue()


class Backend:
    name, api_type, ref_slot_count, model, image_family = "Fake", "fake", 3, "", "natural"
    supports_negative_prompt = True

    def generate(self, prompt, negative, params, **kwargs):
        self.captured = prompt, negative, dict(params.get("reference_images") or {})
        return [GENERATED]


BACKEND = Backend()


class Service:
    enabled = True

    def _wait_for_explicit_backend(self, name): return BACKEND
    def _get_instance_config(self, *args): return {}
    def run_on_backend_channel(self, backend, fn, **kwargs): return fn()
    def run_on_backend(self, backend, op, **kwargs): return op(backend), backend
    def _generate_image_analysis(self, *args): return ""


REFS = {}
ROOM = Path(TEMP.name) / "world_gallery" / "loc1" / "room.png"
ROOM.parent.mkdir(parents=True)
ROOM.write_bytes(GENERATED)
for name in ("Ann", "Bob"):
    character.save_character_profile(name, {"name": name, "language": "en"}, create_new=True)
    ref = character.get_character_outfits_dir(name) / f"{name}_original.png"
    ref.write_bytes(GENERATED)
    REFS[name] = str(ref)


class Builder(pb.PromptBuilder):
    def __init__(self, name): self.character_name = name
    def detect_persons(self, prompt, character_names=None):
        return [pb.Person(n, "brown hair", "", is_agent=n == "Ann")
                for n in (character_names if character_names is not None else ["Ann", "Bob"])]
    def _resolve_person_ref_image(self, person): return REFS[person.name]
    def _collect_location(self, variables): variables.ref_image_room = str(ROOM)


class ScreenshotRegen(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target, kwargs in [
            ("app.imagegen.service.get_image_service", {"return_value": Service()}),
            ("app.core.prompt_builder.PromptBuilder", {"new": Builder}),
            ("app.core.config.resolve_use_case_style", {"return_value": {}}),
            ("app.models.world.get_background_path", {"return_value": ROOM}),
            ("app.core.perception.announce_action", {}),
            ("app.core.room_entry.characters_in_room", {"return_value": ["Ann", "Bob"]}),
            ("app.core.scene_photo.prepare_scene_photo", {"return_value": {
                "ok": True, "location": "loc1", "room": "r1", "subjects": ["Ann", "Bob"],
                "prompt": "Ann and Bob by the window"}}),
        ]:
            self.stack.enter_context(patch(target, **kwargs))
        self.gallery = character.get_character_images_dir("Ann")
        self.upload = Path(TEMP.name) / "chat_uploads" / "aabbccddeeff.jpg"
        self.upload.parent.mkdir(exist_ok=True)
        self.upload.write_bytes(SCREENSHOT)
        with db.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO chat_upload_owners "
                         "(image_id,user_id,purpose,created_at) VALUES (?, 'u1', 'scene_photo', '2026-11-03')",
                         (self.upload.name,))

    def photo(self, screenshot=True):
        result = scene_photo.take_scene_photo(
            "Ann", backend_name="Fake", pose_check=False,
            reference_image_id=self.upload.name if screenshot else "", user_id="u1")
        self.assertTrue(result["ok"], result)
        self.image = self.gallery / result["filename"]
        self.meta = character._load_single_image_meta("Ann", self.image.name)
        return result

    def companion(self, image=None):
        image = image or self.image
        meta = character._load_single_image_meta("Ann", image.name)
        name = meta.get("screenshot_source")
        self.assertTrue(name, "successful screenshot photo must remember its screenshot")
        # Metadata is relative to images/, so a private subdirectory is allowed.
        matches = [f for f in self.gallery.rglob("*") if f.is_file()
                   and (f.name == name or f.relative_to(self.gallery).as_posix() == name)]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].read_bytes(), SCREENSHOT)
        return matches[0]

    def regen(self, **kwargs):
        ok, prompt, output = ir.regenerate_image(
            "Ann", str(self.image), self.meta["prompt"], backend_name="Fake",
            character_names=["Ann", "Bob"], location_id="loc1", source_room_id="r1",
            use_source_as_reference=kwargs.pop("use_source_as_reference", True),
            source_image_path=str(self.image), keep_source_references=True,
            pose_check=False, **kwargs)
        self.assertTrue(ok)
        return Path(output), BACKEND.captured

    def test_photo_keeps_source_and_consumes_upload(self):
        self.photo()
        companion = self.companion()
        self.assertFalse(self.upload.exists())
        self.assertIsNone(db.get_connection().execute(
            "SELECT 1 FROM chat_upload_owners WHERE image_id=?", (self.upload.name,)).fetchone())
        self.assertNotIn(companion.name, character.get_character_images("Ann"))
        self.assertNotIn(companion.name, character.get_character_image_metadata("Ann"))
        from app.core.improvements.types.subjects import character_gallery_images
        self.assertNotIn(str(companion), [g["path"] for g in character_gallery_images("Ann")])

    def test_regenerate_composition_people_negative_and_prompt(self):
        self.photo()
        companion = self.companion()
        self.meta["prompt"] += "\n" + scene_photo._SCREENSHOT_SENTENCE
        output, (prompt, negative, refs) = self.regen(negative_prompt_override="soft focus, CGI")
        self.assertEqual(output, self.image)
        self.assertEqual(list(refs.values()), [str(companion), REFS["Ann"], REFS["Bob"]])
        self.assertEqual(prompt.count(scene_photo._SCREENSHOT_SENTENCE), 1)
        terms = [t.strip().casefold() for t in negative.split(",")]
        for term in ("soft focus", "cgi", "3d render", "game engine"):
            self.assertEqual(terms.count(term), 1)
        self.assertEqual(self.companion(), companion)

    def test_unchecked_and_new_variants_own_copies(self):
        self.photo()
        original = self.companion()
        for enabled in (False, True):
            output, (_, _, refs) = self.regen(create_new=True, use_source_as_reference=enabled)
            copy = self.companion(output)
            self.assertNotEqual(copy, original)
            self.assertNotEqual(copy.stat().st_ino, original.stat().st_ino)
            self.assertEqual(str(original) in refs.values(), enabled)
            self.assertEqual(str(ROOM) in refs.values(), not enabled)
            # A variant must still regenerate from its own copy after its
            # parent's companion is no longer available.
            parent_image, parent_meta = self.image, self.meta
            self.image, self.meta = output, character._load_single_image_meta("Ann", output.name)
            held = original.with_suffix(".held")
            original.rename(held)
            try:
                _, (_, _, variant_refs) = self.regen()
            finally:
                held.rename(original)
            self.assertEqual(list(variant_refs.values()), [str(copy), REFS["Ann"], REFS["Bob"]])
            self.image, self.meta = parent_image, parent_meta
            self.assertTrue(character.delete_character_image("Ann", output.name))
            self.assertFalse(copy.exists())
            self.assertTrue(original.exists())

    def test_legacy_and_missing_companion_keep_normal_behavior(self):
        self.photo(screenshot=False)
        self.assertNotIn("screenshot_source", self.meta)
        _, (_, negative, refs) = self.regen()
        self.assertIn(str(ROOM), refs.values())
        self.assertNotIn("3d render", negative)
        self.photo()
        self.companion().unlink()
        _, (_, _, refs) = self.regen()
        self.assertIn(str(ROOM), refs.values())

    def test_new_photo_does_not_inherit_a_placeholder_companion(self):
        from app.core.screenshot_sources import store_screenshot_source
        placeholder = self.gallery / "Ann_photo.png"
        placeholder.write_bytes(GENERATED)
        old_upload = Path(TEMP.name) / "old-shot.jpg"
        old_upload.write_bytes(GENERATED)
        source_name = store_screenshot_source("Ann", placeholder.name, old_upload)
        character.add_character_image_metadata("Ann", placeholder.name, {"screenshot_source": source_name})
        try:
            self.photo(screenshot=False)
            self.assertNotIn("screenshot_source", self.meta)
            self.photo()
            self.assertEqual(BACKEND.captured[2]["input_reference_image_1"], str(self.upload))
            self.companion()
        finally:
            character.delete_character_image("Ann", placeholder.name)

    def test_exports_and_gallery_delete_route(self):
        self.photo()
        companion = self.companion()
        from app.core.character_io import export_character_to_zip
        from app.core.content_io import export_zip_for
        for payload in (export_character_to_zip("Ann"), export_zip_for("character", "Ann")):
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                self.assertFalse(any(companion.name in n for n in archive.namelist()))
        from app.routes import play
        with patch("app.models.account.get_active_character", return_value="Ann"):
            self.assertEqual(play.play_gallery_delete_image("Ann", self.image.name, user={"id": "u1"}), {"ok": True})
        self.assertFalse(companion.exists())

    def test_text_only_variant_does_not_record_unused_reference(self):
        self.photo()
        with patch.object(BACKEND, "ref_slot_count", 0):
            output, (_, _, refs) = self.regen(create_new=True)
        self.assertEqual(refs, {})
        meta = character._load_single_image_meta("Ann", output.name)
        self.assertEqual(meta["reference_paths"], {})
        self.companion(output)

    def test_hostile_metadata_cannot_use_or_delete_another_source(self):
        self.photo()
        first_image = self.image
        first_source = self.companion()
        self.upload.write_bytes(SCREENSHOT)
        with db.transaction() as conn:
            conn.execute("INSERT INTO chat_upload_owners (image_id,user_id,purpose,created_at) "
                         "VALUES (?, 'u1', 'scene_photo', '2026-11-03')", (self.upload.name,))
        self.photo()
        second_source = self.companion()
        for hostile in ("../outside.jpg", str(first_source), first_source.name, "x\\source.jpg", 123):
            self.meta["screenshot_source"] = hostile
            character.add_character_image_metadata("Ann", self.image.name, self.meta)
            _, (_, _, refs) = self.regen()
            self.assertNotIn(str(first_source), refs.values())
        self.assertTrue(character.delete_character_image("Ann", self.image.name))
        self.assertTrue(first_source.exists())
        self.assertTrue(second_source.exists(), "unsafe metadata must not name files to unlink")
        self.assertTrue(first_image.exists())

    def test_source_symlinks_cannot_escape_read_write_or_delete(self):
        self.photo()
        companion = self.companion()
        outside = Path(TEMP.name) / "outside.jpg"
        outside.write_bytes(b"must survive")
        companion.unlink()
        companion.symlink_to(outside)
        _, (_, _, refs) = self.regen()
        self.assertNotIn(str(outside), refs.values())
        from app.core.screenshot_sources import store_screenshot_source
        with self.assertRaises(ValueError):
            store_screenshot_source("Ann", self.image.name, self.upload)
        self.assertTrue(character.delete_character_image("Ann", self.image.name))
        self.assertEqual(outside.read_bytes(), b"must survive")

    def test_source_directory_and_gallery_name_cannot_redirect_writes(self):
        self.photo()
        companion = self.companion()
        from app.core.screenshot_sources import store_screenshot_source
        outside = Path(TEMP.name) / "outside-sources"
        outside.mkdir(exist_ok=True)
        directory = companion.parent
        held = directory.with_name("held-sources")
        directory.rename(held)
        directory.symlink_to(outside, target_is_directory=True)
        try:
            with self.assertRaises(ValueError):
                store_screenshot_source("Ann", self.image.name, self.upload)
            self.assertEqual(list(outside.iterdir()), [])
        finally:
            directory.unlink()
            held.rename(directory)
        with self.assertRaises(ValueError):
            store_screenshot_source("Ann", "../escape.png", self.upload)

    def test_character_delete_removes_companions(self):
        from app.core.screenshot_sources import store_screenshot_source
        character.save_character_profile("Disposable", {"name": "Disposable"}, create_new=True)
        gallery = character.get_character_images_dir("Disposable")
        (gallery / "photo.png").write_bytes(GENERATED)
        name = store_screenshot_source("Disposable", "photo.png", self.upload)
        companion = gallery / ".screenshot-sources" / name
        self.assertTrue(companion.exists())
        self.assertTrue(character.delete_character("Disposable"))
        self.assertFalse(companion.exists())

    def test_delete_gallery_symlink_keeps_target_image(self):
        target = self.gallery / "target.png"
        target.write_bytes(GENERATED)
        alias = self.gallery / "alias.png"
        alias.symlink_to(target)
        self.assertTrue(character.delete_character_image("Ann", alias.name))
        self.assertTrue(target.exists(), "deleting a gallery alias must not unlink its target")
        self.assertFalse(alias.is_symlink())


if __name__ == "__main__":
    unittest.main()
