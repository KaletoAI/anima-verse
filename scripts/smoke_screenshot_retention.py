#!/usr/bin/env python3
"""Task 101: screenshot lifetime, with a temporary DB and fake image generation.

Usage: ./.venv/bin/python scripts/smoke_screenshot_retention.py

Hand oracle: only screenshot-purpose uploads are disposable. A successful
photo removes its input and owner row; a failed render keeps both for retry.
Exactly seven SYSTEM days is retained; seven days plus one second expires.
Chat attachments, fresh screenshots and paths outside chat_uploads survive.
"""
import asyncio
import io
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_tmp = tempfile.TemporaryDirectory(prefix="task101-uploads-")
os.environ["STORAGE_DIR"] = _tmp.name
os.environ["INSTANCE_DIR"] = _tmp.name
from app.core import paths
paths.init(_tmp.name)
paths.init_instance(_tmp.name)
from app.core import db, chat_ops, scene_photo
from app.core.auth_dependency import current_user_ctx
from app.core.timeutils import utc_now
from app.models.character import save_character_profile
from starlette.requests import Request
from PIL import Image

db.init_schema()
db.init_schema()  # Additive migrations must be idempotent.
save_character_profile("Ann", {"name": "Ann", "language": "en"}, create_new=True)
image = io.BytesIO()
Image.new("RGB", (2, 2)).save(image, "JPEG")


def upload(purpose="scene_photo"):
    boundary = "task101"
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="shot.jpg"\r\n'
            'Content-Type: image/jpeg\r\n\r\n').encode() + image.getvalue() + f'\r\n--{boundary}--\r\n'.encode()
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    request = Request({"type": "http", "method": "POST", "path": "/chat/me/upload-image",
                       "query_string": f"purpose={purpose}".encode(), "headers": [
                           (b"content-type", f"multipart/form-data; boundary={boundary}".encode())]}, receive)
    token = current_user_ctx.set({"id": "uploader"})
    try:
        return asyncio.run(chat_ops.save_chat_upload(request))["image_id"]
    finally:
        current_user_ctx.reset(token)


def owner(image_id):
    return db.get_connection().execute("SELECT * FROM chat_upload_owners WHERE image_id=?", (image_id,)).fetchone()


def path(image_id):
    return Path(_tmp.name) / "chat_uploads" / image_id


def take(image_id, outcome=True, secret=False):
    gallery = Path(_tmp.name) / "characters" / "Ann" / "images" / "result.png"
    gallery.parent.mkdir(parents=True, exist_ok=True)
    def generate(**kw):
        assert Path(kw["source_image_path"]).is_file(), "input must exist during generation"
        if isinstance(outcome, Exception):
            raise outcome
        if outcome:
            gallery.write_bytes(image.getvalue())
        return outcome, "fixture prompt", str(gallery)
    with patch.object(scene_photo, "prepare_scene_photo", return_value={"ok": True, "location": "house",
            "room": "room", "subjects": ["Ann"], "prompt": "fixture"}), \
         patch("app.core.room_entry.characters_in_room", return_value=["Ann"]), \
         patch("app.skills.image_regenerate.regenerate_image", side_effect=generate), \
         patch("app.core.perception.announce_action"):
        return scene_photo.take_scene_photo("Ann", reference_image_id=image_id, user_id="uploader", secret=secret)


shot = upload()
assert owner(shot)["purpose"] == "scene_photo", "screenshots must be marked before a dialog can be abandoned"
assert owner(shot)["created_at"], "retention needs a system timestamp"
for outcome in (False, RuntimeError("backend unavailable")):
    assert not take(shot, outcome)["ok"]
    assert path(shot).is_file() and owner(shot), "failure must preserve retry input and owner"
for secret in (False, True):
    shot = upload()
    result = take(shot, secret=secret)
    assert result["ok"]
    assert not path(shot).exists() and owner(shot) is None, "success must remove input and owner"
    assert (Path(_tmp.name) / "characters/Ann/images/result.png").is_file(), "gallery image survives"
chat = upload("chat")
assert take(chat)["ok"] and path(chat).is_file() and owner(chat), "ordinary uploads are never consumed"
attached = upload()
from app.routes.chat import resolve_chat_image
assert resolve_chat_image(image_id=attached)[0]
assert owner(attached)["purpose"] == "chat", "attaching a screenshot protects its message reference"
assert take(attached)["ok"] and path(attached).exists()
print("PASS marked upload, failure/retry, public/secret success, gallery and chat protection")

now = utc_now()
old, boundary, fresh, missing = upload(), upload(), upload(), upload()
outside = Path(_tmp.name) / "outside.jpg"
outside.write_bytes(b"keep")
escape = upload()
path(escape).unlink()
path(escape).symlink_to(outside)
with db.transaction() as conn:
    for image_id in (old, chat, attached, missing, escape):
        conn.execute("UPDATE chat_upload_owners SET created_at=? WHERE image_id=?",
                     ((now - timedelta(days=7, seconds=1)).isoformat(), image_id))
    conn.execute("UPDATE chat_upload_owners SET created_at=? WHERE image_id=?",
                 ((now - timedelta(days=7)).isoformat(), boundary))
    conn.execute("INSERT INTO chat_upload_owners (image_id,user_id,purpose,created_at) VALUES (?,?,?,?)",
                 ("../outside.jpg", "uploader", "scene_photo", (now - timedelta(days=8)).isoformat()))
path(missing).unlink()
from app.core import periodic_jobs
job, interval, _ = next(row for row in periodic_jobs._SUB_TASKS if row[2] == "screenshot_uploads")
assert interval == 86400, "cleanup runs daily"
with patch("app.core.timeutils.utc_now", return_value=now):
    job()
for image_id in (old, missing):
    assert not path(image_id).exists() and owner(image_id) is None, "expired screenshot/owner must go together"
for image_id in (chat, attached, boundary, fresh, escape):
    assert path(image_id).exists() and owner(image_id), f"protected input removed: {image_id}"
assert outside.read_bytes() == b"keep" and owner("../outside.jpg"), "resolved containment must block deletion"
print("PASS daily sweep, seven-day boundary, missing file, chat owners and path/symlink safety")
