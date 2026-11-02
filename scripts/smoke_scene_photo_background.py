#!/usr/bin/env python3
"""Nonblocking photo acceptance and private completion, with a held renderer.

Usage: ./.venv/bin/python scripts/smoke_scene_photo_background.py

Hand oracle: a held renderer cannot finish, yet POST must return 202 with an
ID and discovery already applied. Before release: zero charge, zero completion.
After release: one gallery file, one charge, one owner notice; another avatar
at the SAME location receives no completion topic. Failure keeps the uploaded
screenshot and charges zero. Invalid input must be a synchronous 4xx.
Fixtures initialise temporary world/instance paths before all DB imports.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TEMP = tempfile.TemporaryDirectory(prefix="photo-background-")
os.environ["STORAGE_DIR"] = TEMP.name
os.environ["INSTANCE_DIR"] = TEMP.name
from app.core import paths
paths.init(TEMP.name)
paths.init_instance(TEMP.name)

from smoke_scene_photo_secret import SecretPhotos, character, scene_photo, secrets, request, LOC
from fastapi import FastAPI, HTTPException
import httpx
from app.core import sync_topics, db
from app.core import scene_photo_jobs
from app.models.notifications import get_notifications
from app.routes import play


async def wait_for_photo(photo_id):
    for _ in range(500):
        with scene_photo_jobs._lock:
            running = photo_id in scene_photo_jobs._workers
        if not running:
            break
        await asyncio.sleep(.01)
    assert not running, "photo worker did not finish"
    return next(n for n in get_notifications(limit=200, character_whitelist=["Ann"])
                if n["metadata"].get("photo_id") == photo_id)


class BackgroundPhotos(SecretPhotos):
    # Reuse the safe fixture, not the legacy synchronous test methods.
    def test_accept_before_render_and_private_completion(self):
        async def exercise():
            entered, release = threading.Event(), threading.Event()
            api = FastAPI()
            api.add_api_route("/play/scene-photo", play.play_scene_photo, methods=["POST"])
            api.dependency_overrides[play.get_current_user] = lambda: {"id": "u1"}
            client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://smoke")
            generate = self.generate
            def held(**kwargs):
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('test renderer was never released')
                return generate(**kwargs)
            conns = [sync_topics.register(uid, uid, avatar, LOC)
                     for uid, avatar in [('u1', 'Ann'), ('u2', 'Bob')]]
            for c in conns:
                c.take(); c.delivered()
            try:
                with patch('app.imagegen.service.get_image_service', return_value=SimpleNamespace(enabled=True)), \
                     patch('app.imagegen.routing.resolve_image_route'), \
                     patch.object(play, '_player_action_gate', return_value=SimpleNamespace(SKILL_ID='camera')), \
                     patch('app.skills.image_regenerate.regenerate_image', side_effect=held), \
                     patch('app.core.scene_photo_jobs.random.random', return_value=0), \
                     patch('app.core.skill_gate.charge') as charge:
                    posting = asyncio.create_task(client.post("/play/scene-photo", json={
                        'prompt': 'Bob by the window', 'secret': True}))
                    done, _ = await asyncio.wait([posting], timeout=.5)
                    if not done:
                        release.set()
                        await posting
                    self.assertTrue(done, 'POST waited for the held render')
                    response = posting.result()
                    self.assertEqual(response.status_code, 202)
                    accepted = response.json()
                    self.assertEqual(accepted['status'], 'accepted')
                    self.assertEqual(set(accepted['discovered_by']), {'Bob', 'Cid', 'Dee'})
                    self.assertTrue(self.loop.bump_respond.called, 'discovery consequences happen at acceptance')
                    charge.assert_not_called()
                    for c in conns:
                        c.take(); c.delivered()  # discard legitimate discovery consequences
                    release.set()
                    for _ in range(400):
                        notices = [n for n in get_notifications(character_whitelist=['Ann'])
                                   if n['type'] == 'scene_photo' and n['metadata'].get('photo_id') == accepted['photo_id']]
                        if notices:
                            break
                        await asyncio.sleep(.01)
                    self.assertEqual(len(notices), 1)
                    meta = notices[0]['metadata']
                    self.assertEqual(meta['status'], 'ready')
                    payload = play.play_notices(user={"id": "u1"})
                    fetched = next(n for n in payload["notifications"] if n["id"] == notices[0]["id"])
                    self.assertEqual(fetched["photo"], meta)
                    with patch("app.models.account.get_active_character", return_value="Bob"):
                        self.assertFalse(any(n.get("photo", {}).get("photo_id") == accepted["photo_id"]
                                             for n in play.play_notices(user={"id": "u2"})["notifications"]))
                    self.assertTrue((character.get_character_images_dir('Ann') / meta['filename']).is_file())
                    charge.assert_called_once_with('Ann', 'camera')
                    self.assertIn('notices', conns[0].take()[0])
                    self.assertNotIn('notices', conns[1].take()[0])
                    self.assertFalse(any(n['type'] == 'scene_photo' for n in get_notifications(character_whitelist=['Bob'])))
                    known = next(s for s in secrets.list_secrets('Ann')
                                 if s['source_ref'] == 'secret_photo:' + accepted['photo_id'])
                    self.assertIn('Bob', known['known_by'])
            finally:
                release.set()
                for c in conns:
                    sync_topics.unregister(c)
                await client.aclose()
        asyncio.run(exercise())

    def test_failure_retention_charge_and_retry(self):
        async def exercise():
            image_id = "aabbccddeeff.jpg"
            source = paths.get_storage_dir() / "chat_uploads" / image_id
            source.parent.mkdir(parents=True, exist_ok=True)
            from PIL import Image
            Image.new("RGB", (2, 2)).save(source)
            with db.transaction() as conn:
                conn.execute("INSERT OR REPLACE INTO chat_upload_owners (image_id, user_id, purpose, created_at) "
                             "VALUES (?, 'u1', 'scene_photo', '2026-11-02T00:00:00+00:00')", (image_id,))
            def retained():
                self.assertTrue(source.is_file())
                self.assertIsNotNone(db.get_connection().execute(
                    "SELECT 1 FROM chat_upload_owners WHERE image_id=?", (image_id,)).fetchone())
            with patch("app.imagegen.service.get_image_service", return_value=SimpleNamespace(enabled=True)), \
                 patch("app.imagegen.routing.resolve_image_route"), \
                 patch.object(play, "_player_action_gate", return_value=SimpleNamespace(SKILL_ID="camera")), \
                 patch("app.core.skill_gate.charge") as charge, \
                 patch("app.core.perception.announce_action") as announce:
                for outcome in [(False, "", ""), RuntimeError("Backend failed")]:
                    with patch("app.skills.image_regenerate.regenerate_image", **(
                            {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome})):
                        response = await play.play_scene_photo(request({"prompt": "Bob", "secret": True,
                            "reference_image_id": image_id}), user={"id": "u1"})
                        accepted = json.loads(response.body)
                        self.assertEqual(response.status_code, 202)
                        notice = await wait_for_photo(accepted["photo_id"])
                        self.assertEqual(notice["metadata"]["status"], "failed")
                        self.assertIn("failed", notice["content"].lower())
                        charge.assert_not_called()
                        retained()
                with patch("app.skills.image_regenerate.regenerate_image", side_effect=self.generate):
                    response = await play.play_scene_photo(request({"prompt": "Bob", "secret": False,
                        "reference_image_id": image_id}), user={"id": "u1"})
                    notice = await wait_for_photo(json.loads(response.body)["photo_id"])
                    self.assertEqual(notice["metadata"]["status"], "ready")
                charge.assert_called_once_with("Ann", "camera")
                self.assertFalse(source.exists())
                self.assertIsNone(db.get_connection().execute(
                    "SELECT 1 FROM chat_upload_owners WHERE image_id=?", (image_id,)).fetchone())
                announce.assert_called_once()
        asyncio.run(exercise())

    def test_validation_is_synchronous_and_never_rolls_or_renders(self):
        async def exercise():
            from app.core.lora_library import LoraNotAllowedError
            async def refused(body, status):
                with self.assertRaises(HTTPException) as err:
                    await play.play_scene_photo(request(body), user={"id": "u1"})
                self.assertEqual(err.exception.status_code, status)
            with patch.object(play, "_player_action_gate", return_value=None), \
                 patch("app.core.scene_photo_jobs.random.random") as roll, \
                 patch("app.skills.image_regenerate.regenerate_image") as render, \
                 patch("app.core.skill_gate.charge") as charge, \
                 patch("app.imagegen.service.get_image_service", return_value=SimpleNamespace(enabled=True)):
                for body in [[], None, {"secret": "true"}, {"secret": 1}, {"secret": None},
                             {"prompt": {}}, {"backend": []}, {"character_names": "Bob"},
                             {"use_room": 1}, {"pose_check": "false"}, {"loras": {}},
                             {"loras": [{"name": "test", "strength": float("nan")}]},
                             {"reference_image_id": 1}]:
                    await refused(body, 422)
                await refused({"reference_image_id": "missing.jpg"}, 404)
                with patch("app.core.chat_ops.resolve_owned_chat_upload_path", side_effect=HTTPException(403, "Not yours")):
                    await refused({"reference_image_id": "aabbccddeeff.jpg"}, 403)
                with patch("app.imagegen.base.media_generation_enabled", return_value=False):
                    await refused({}, 409)
                with patch("app.core.explicit_backend.require_explicit_backend", side_effect=HTTPException(503, "Selected backend unavailable")):
                    await refused({"backend": "Missing"}, 503)
                with patch("app.core.explicit_backend.require_explicit_backend", return_value=SimpleNamespace(name="Fake")), \
                     patch("app.core.lora_library.assert_loras_allowed", side_effect=LoraNotAllowedError("Fake", ["bad"])):
                    await refused({"backend": "Fake", "loras": [{"name": "bad"}]}, 400)
                from app.imagegen.routing import NoRouteError
                with patch("app.imagegen.routing.resolve_image_route", side_effect=NoRouteError("photo", [])):
                    await refused({}, 503)
                with patch.object(play, "_player_action_gate", side_effect=HTTPException(409, "Blocked")):
                    await refused({}, 409)
                roll.assert_not_called()
                render.assert_not_called()
                charge.assert_not_called()
        asyncio.run(exercise())

    def test_multiple_submits_and_no_duplicate_discovery_on_show(self):
        async def exercise():
            release = threading.Event()
            calls = []
            def held(**kwargs):
                calls.append(kwargs)
                if not release.wait(5):
                    raise RuntimeError("renderer not released")
                return self.generate(**kwargs)
            try:
                with patch("app.imagegen.service.get_image_service", return_value=SimpleNamespace(enabled=True)), \
                     patch("app.imagegen.routing.resolve_image_route"), \
                     patch.object(play, "_player_action_gate", return_value=None), \
                     patch("app.skills.image_regenerate.regenerate_image", side_effect=held), \
                     patch("app.core.scene_photo_jobs.random.random", return_value=0):
                    first = json.loads((await play.play_scene_photo(request({"prompt": "Bob", "secret": True}), user={"id": "u1"})).body)
                    second = json.loads((await play.play_scene_photo(request({"prompt": "Bob"}), user={"id": "u1"})).body)
                    self.assertNotEqual(first["photo_id"], second["photo_id"])
                    self.assertEqual(set(first["discovered_by"]), {"Bob", "Cid", "Dee"})
                    self.assertFalse(release.is_set())
                    release.set()
                    notice = await wait_for_photo(first["photo_id"])
                    await wait_for_photo(second["photo_id"])
                    from app.core.scene_photo_watch import reveal_photo
                    with patch("app.core.scene_photo_watch.discover_photo", wraps=__import__(
                            "app.core.scene_photo_watch", fromlist=["discover_photo"]).discover_photo):
                        self.assertEqual(reveal_photo("Ann", notice["metadata"]["filename"]), [])
                    self.assertEqual(calls[0]["location_id"], LOC)
                    self.assertEqual(calls[0]["room_id"], "salon")
            finally:
                release.set()
        asyncio.run(exercise())

    def test_public_announcement_keeps_shutter_room_after_player_moves(self):
        async def exercise():
            release = threading.Event()
            def held(**kwargs):
                if not release.wait(5):
                    raise RuntimeError("renderer not released")
                return self.generate(**kwargs)
            try:
                with patch("app.imagegen.service.get_image_service", return_value=SimpleNamespace(enabled=True)), \
                     patch("app.imagegen.routing.resolve_image_route"), \
                     patch.object(play, "_player_action_gate", return_value=None), \
                     patch("app.skills.image_regenerate.regenerate_image", side_effect=held), \
                     patch("app.core.perception.record_utterance") as utterance:
                    response = await play.play_scene_photo(request({"prompt": "Bob"}), user={"id": "u1"})
                    with patch("app.models.character.get_character_current_location", return_value="elsewhere"), \
                         patch("app.models.character.get_character_current_room", return_value="another-room"):
                        release.set()
                        notice = await wait_for_photo(json.loads(response.body)["photo_id"])
                    self.assertEqual(notice["metadata"]["status"], "ready")
                    self.assertEqual(utterance.call_args.kwargs["location_id"], LOC)
                    self.assertEqual(utterance.call_args.kwargs["room_id"], "salon")
            finally:
                release.set()
        asyncio.run(exercise())


if __name__ == '__main__':
    # Only this class's new methods; inherited regressions run in their own smoke.
    suite = unittest.TestSuite(BackgroundPhotos(n) for n in BackgroundPhotos.__dict__ if n.startswith('test_'))
    raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
