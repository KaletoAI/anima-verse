#!/usr/bin/env python3
"""Secret-photo consequences and real room-chat attachment integration.

Usage: ./.venv/bin/python scripts/smoke_scene_photo_secret.py

Hand-derived probabilities: ordinary observer .35; depicted .35*1.7=.595;
distracted .35*.25=.0875; depicted+distracted .14875; sleeping 0.
Rolls strictly below the chance discover; equality does not. A patched base
of 1 clamps a depicted observer to .95; a negative base clamps to 0.
Only the watcher's directed sentiment changes (-.4 depicted, -.3 otherwise).
Showing reveals only to present depicted non-knowers, once per image/watcher.
All persistence uses temporary storage. Generation, vision and agent execution
are stubbed; memories, relationships, secrets and perception fan-out are real.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TEMP = tempfile.TemporaryDirectory(prefix="photo-secret-")
os.environ["STORAGE_DIR"] = TEMP.name
os.environ["INSTANCE_DIR"] = TEMP.name
from app.core import paths
paths.init(TEMP.name)
paths.init_instance(TEMP.name)
from app.core import db, scene_photo, scene_photo_watch as watch, perception
db.init_schema()
from app.models import character, secrets, relationship, memory, perception_store
from app.models.world import add_location, update_location_position
from fastapi import HTTPException
from starlette.requests import Request

LOC = add_location(name="Photo room", description="Smoke fixture", rooms=[{"id": "salon", "name": "Salon"}])["id"]
update_location_position(LOC, 0, 0)
for name in ("Ann", "Bob", "Cid", "Dee"):
    assert character.save_character_profile(name, {"name": name, "language": "en"}, create_new=True)
    character.save_character_current_location(name, LOC)
    character.save_character_current_room(name, "salon")


def request(body):
    async def receive():
        return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}
    return Request({"type": "http", "method": "POST", "path": "/play/say", "headers": []}, receive)


class SecretPhotos(unittest.TestCase):
    serial = 0

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.loop = SimpleNamespace(bump_respond=Mock(), dispatch_room_reactions=Mock(
            return_value={"obligatory": ["Bob"], "chime": []}))
        self.stack.enter_context(patch("app.core.agent_loop.get_agent_loop", return_value=self.loop))
        self.stack.enter_context(patch("app.models.account.is_player_controlled", side_effect=lambda n: n in {"Ann", "Cid"}))
        self.stack.enter_context(patch("app.core.attention.is_distracted", return_value=False))
        self.stack.enter_context(patch("app.models.character.is_character_sleeping", return_value=False))
        self.stack.enter_context(patch.object(scene_photo, "prepare_scene_photo", return_value={
            "ok": True, "location": LOC, "room": "salon", "subjects": ["Bob"], "prompt": "Bob by the window"}))
        self.stack.enter_context(patch("app.skills.image_regenerate.regenerate_image", side_effect=self.generate))
        self.stack.enter_context(patch("app.models.account.get_active_character", return_value="Ann"))
        self.stack.enter_context(patch("app.routes.chat.analyze_chat_image_blocking", return_value="Bob by the window"))
        from app.routes import play
        async def silent(*args, **kwargs):
            pass
        self.stack.enter_context(patch.object(play, "_storyteller_after_silence", silent))
        self.stack.enter_context(patch.object(play, "_storyteller_fallback", silent))

    def generate(self, **kwargs):
        type(self).serial += 1
        path = character.get_character_images_dir("Ann") / f"photo-{self.serial}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        from PIL import Image
        Image.new("RGB", (2, 2)).save(path)
        return True, kwargs["original_prompt"], str(path)

    def take(self, **kwargs):
        return scene_photo.take_scene_photo("Ann", **kwargs)

    def test_ordinary_still_announces(self):
        with patch.object(perception, "announce_action") as announce:
            result = self.take()
        self.assertTrue(result["ok"])
        self.assertEqual(announce.call_count, 1)
        self.assertIn("takes a photo of Bob", announce.call_args.args[1])

    def test_secret_silent_metadata_and_subject_filter(self):
        with patch.object(perception, "announce_action") as announce:
            result = self.take(secret=True, rng=lambda: .99, character_names=["Bob", "Absent", "Bob"])
        self.assertFalse(announce.called)
        self.assertEqual(result["discovered_by"], [])
        meta = character.get_single_image_meta("Ann", result["filename"])
        self.assertIs(meta["secret"], True)
        self.assertEqual(meta["photo_subjects"], ["Bob"])

    def test_probabilities_boundaries_sleep_and_clamp(self):
        for depicted, distracted, chance in [(False, False, .35), (True, False, .595),
                                             (False, True, .0875), (True, True, .14875)]:
            with self.subTest(depicted=depicted, distracted=distracted):
                with patch("app.core.attention.is_distracted", return_value=distracted):
                    self.assertAlmostEqual(watch.discovery_chance("Bob", depicted=depicted), chance)
        with patch("app.models.character.is_character_sleeping", return_value=True):
            self.assertEqual(watch.discovery_chance("Bob", depicted=True), 0)
            result = self.take(secret=True, rng=lambda: 0)
            self.assertEqual(result["discovered_by"], [])
        for base, expected in [(1, .95), (-1, 0)]:
            with patch.object(watch, "DISCOVERY_BASE", base):
                self.assertEqual(watch.discovery_chance("Bob", depicted=True), expected)
        result = self.take(secret=True, rng=lambda: .595)
        self.assertEqual(result["discovered_by"], [])
        result = self.take(secret=True, rng=lambda: .59499)
        self.assertEqual(result["discovered_by"], ["Bob"])

    def test_discovery_persists_effects_and_player_notice(self):
        before = {n: relationship.get_relationship(n, "Ann") for n in ("Bob", "Cid")}
        result = self.take(secret=True, rng=lambda: .1)
        self.assertEqual(result["discovered_by"], ["Bob", "Cid", "Dee"])
        secret = next(s for s in secrets.list_secrets("Ann") if s["source_ref"] == "secret_photo:" + result["filename"])
        self.assertEqual(set(secret["known_by"]), {"Bob", "Cid", "Dee"})
        self.assertEqual(secret["source"], "discovered")
        self.assertEqual(secret["category"], "relationship")
        self.assertEqual(secret["related_characters"], ["Bob"])
        for name in ("Ann", "Bob", "Cid"):
            self.assertTrue(memory.get_memories_by_tag(name, "caught"))
        rows = perception_store.get_character_room_stream("Ann", LOC, "salon", 100)
        self.assertTrue(any("Bob notices Ann secretly" in r["content"] for r in rows))
        hints = self.loop.bump_respond.call_args_list
        self.assertEqual({c.args[0] for c in hints}, {"Bob", "Dee"})
        self.assertTrue(all(c.kwargs["obligatory"] for c in hints))
        for n, delta in [("Bob", -.4), ("Cid", -.3)]:
            old = before[n] or {}
            new = relationship.get_relationship(n, "Ann")
            self.assertIsNotNone(new)
            self.assertAlmostEqual(new["sentiment_b_to_a"], max(-1, old.get("sentiment_b_to_a", 0) + delta))
            self.assertEqual(new["sentiment_a_to_b"], old.get("sentiment_a_to_b", 0))
        from app.models.notifications import get_notifications
        self.assertTrue(get_notifications(character_whitelist=["Cid"]))

    def test_show_reuses_chat_attachment_and_reveals_once(self):
        from app.routes.play import play_say
        result = self.take(secret=True, rng=lambda: .99)
        before = len(memory.get_memories_by_tag("Bob", "caught"))
        shown = asyncio.run(play_say(request({"photo_filename": result["filename"]}), user={"id": "u1"}))
        self.assertTrue(shown["ok"])
        rows = perception_store.get_character_room_stream("Bob", LOC, "salon", 100)
        self.assertTrue(any((r.get("meta") or {}).get("image_url") == result["url"] for r in rows))
        self.assertIn("Bob by the window", self.loop.dispatch_room_reactions.call_args.kwargs["content"])
        self.assertEqual(len(memory.get_memories_by_tag("Bob", "caught")), before + 1)
        self.assertTrue(any("Bob realizes the photo was taken secretly" in r["content"] for r in rows))
        secret = next(s for s in secrets.list_secrets("Ann") if s["source_ref"] == "secret_photo:" + result["filename"])
        self.assertEqual(secret["known_by"], ["Bob"])
        asyncio.run(play_say(request({"photo_filename": result["filename"]}), user={"id": "u1"}))
        self.assertEqual(len(memory.get_memories_by_tag("Bob", "caught")), before + 1)

    def test_existing_gallery_attachment_also_reveals(self):
        from app.routes.play import play_say
        result = self.take(secret=True, rng=lambda: .99)
        before = len(memory.get_memories_by_tag("Bob", "caught"))
        asyncio.run(play_say(request({"image_url": result["url"]}), user={"id": "u1"}))
        self.assertEqual(len(memory.get_memories_by_tag("Bob", "caught")), before + 1)

    def test_show_legacy_own_image_and_no_penalty_for_public_photo(self):
        from app.routes.play import play_say
        _, _, path = self.generate(original_prompt="old photo")
        before = len(memory.get_memories_by_tag("Bob", "caught"))
        shown = asyncio.run(play_say(request({"photo_filename": Path(path).name}), user={"id": "u1"}))
        self.assertTrue(shown["ok"])
        result = self.take()
        shown = asyncio.run(play_say(request({"photo_filename": result["filename"]}), user={"id": "u1"}))
        self.assertTrue(shown["ok"])
        self.assertEqual(len(memory.get_memories_by_tag("Bob", "caught")), before)

    def test_failed_generation_has_no_discovery_effects(self):
        before = len(secrets.list_secrets("Ann"))
        with patch("app.skills.image_regenerate.regenerate_image", return_value=(False, "", "")):
            self.assertFalse(self.take(secret=True, rng=lambda: 0)["ok"])
        self.assertEqual(len(secrets.list_secrets("Ann")), before)
        self.assertFalse(self.loop.bump_respond.called)

    def test_route_secret_validation_and_success_only_charging(self):
        from app.routes import play
        skill = SimpleNamespace(SKILL_ID="test-photo")
        with patch.object(play, "_player_action_gate", return_value=skill) as gate, \
             patch("app.core.skill_gate.charge") as charge:
            result = asyncio.run(play.play_scene_photo(request({"secret": True}), user={"id": "u1"}))
            self.assertTrue(result["ok"])
            self.assertTrue(character.get_single_image_meta("Ann", result["filename"])["secret"])
            charge.assert_called_once_with("Ann", "test-photo")
            gate.assert_called_with("Ann", "scene_photo")
            for value in ("true", 1, None):
                with self.assertRaises(HTTPException) as err:
                    asyncio.run(play.play_scene_photo(request({"secret": value}), user={"id": "u1"}))
                self.assertEqual(err.exception.status_code, 422)
            charge.reset_mock()
            with patch("app.skills.image_regenerate.regenerate_image", return_value=(False, "", "")):
                with self.assertRaises(HTTPException):
                    asyncio.run(play.play_scene_photo(request({"secret": True}), user={"id": "u1"}))
            charge.assert_not_called()
            with patch.object(play, "_player_action_gate", side_effect=AssertionError("show charged a skill")):
                self.assertTrue(asyncio.run(play.play_say(
                    request({"photo_filename": result["filename"]}), user={"id": "u1"}))["ok"])
    def test_unknown_foreign_traversal_refused(self):
        from app.routes.play import play_say
        foreign = character.get_character_images_dir("Bob") / "foreign.png"
        foreign.parent.mkdir(parents=True, exist_ok=True)
        from PIL import Image
        Image.new("RGB", (2, 2)).save(foreign)
        for filename in ("foreign.png", "unknown.png", "../Bob/images/foreign.png", "/tmp/photo.png", "bad\x00.png"):
            with self.subTest(filename=filename):
                with self.assertRaises(HTTPException) as err:
                    asyncio.run(play_say(request({"photo_filename": filename}), user={"id": "u1"}))
                self.assertEqual(err.exception.status_code, 404)

    def test_show_capped_magic_checked_and_symlink_contained(self):
        result = self.take()
        path = character.get_character_images_dir("Ann") / result["filename"]
        with patch("app.core.upload_limits.max_upload_bytes", return_value=10), self.assertRaises(HTTPException) as err:
            scene_photo.resolve_scene_photo("Ann", path.name)
        self.assertEqual(err.exception.status_code, 413)
        path.write_bytes(b"not really an image")
        with self.assertRaises(HTTPException) as err:
            scene_photo.resolve_scene_photo("Ann", path.name)
        self.assertEqual(err.exception.status_code, 415)
        path.unlink()
        outside = Path(TEMP.name) / "outside.png"
        outside.write_bytes(b"outside")
        path.symlink_to(outside)
        with self.assertRaises(HTTPException) as err:
            scene_photo.resolve_scene_photo("Ann", path.name)
        self.assertEqual(err.exception.status_code, 404)

    def test_show_skips_sleeping_absent_and_existing_knowers(self):
        from app.routes.play import play_say
        result = self.take(secret=True, character_names=["Bob", "Cid"], rng=lambda: .99)
        with patch("app.models.character.is_character_sleeping", side_effect=lambda n, **kw: n == "Bob"), \
             patch("app.core.room_entry.characters_in_room", return_value=["Ann", "Bob", "Dee"]):
            asyncio.run(play_say(request({"photo_filename": result["filename"]}), user={"id": "u1"}))
        self.assertFalse(any(s["source_ref"] == "secret_photo:" + result["filename"] for s in secrets.list_secrets("Ann")))
        asyncio.run(play_say(request({"photo_filename": result["filename"]}), user={"id": "u1"}))
        secret = next(s for s in secrets.list_secrets("Ann") if s["source_ref"] == "secret_photo:" + result["filename"])
        self.assertEqual(set(secret["known_by"]), {"Bob", "Cid"})
        before = len(memory.get_memories_by_tag("Ann", "caught"))
        asyncio.run(play_say(request({"photo_filename": result["filename"]}), user={"id": "u1"}))
        self.assertEqual(len(memory.get_memories_by_tag("Ann", "caught")), before)

    def test_concurrent_disclosure_has_one_penalty(self):
        from concurrent.futures import ThreadPoolExecutor
        result = self.take(secret=True, rng=lambda: .99)
        before = len(memory.get_memories_by_tag("Bob", "caught"))
        with ThreadPoolExecutor(max_workers=2) as pool:
            calls = [pool.submit(watch.discover_photo, "Ann", result["filename"], ["Bob"], "Bob", LOC, "salon", shown=True)
                     for _ in range(2)]
            self.assertEqual(sorted(f.result() for f in calls), [False, True])
        self.assertEqual(len(memory.get_memories_by_tag("Bob", "caught")), before + 1)

    def test_missing_room_never_reveals_to_the_whole_location(self):
        result = self.take(secret=True, rng=lambda: .99)
        with patch("app.models.character.get_character_current_room", return_value=""):
            self.assertEqual(watch.reveal_photo("Ann", result["filename"]), [])
        with patch.object(scene_photo, "prepare_scene_photo", return_value={
                "ok": True, "location": LOC, "room": "", "subjects": ["Bob"], "prompt": "Bob"}):
            self.assertEqual(self.take(secret=True, rng=lambda: 0)["discovered_by"], [])


if __name__ == "__main__":
    unittest.main()
