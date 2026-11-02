#!/usr/bin/env python3
"""Screenshot photo contract, using only temporary storage and a fake backend.

Usage: ./.venv/bin/python scripts/smoke_scene_photo_screenshot.py

Hand-derived expectations: x=.1/.5/.9 is left/centre/right; depths 2/5/8
put the nearest person in front and farthest in back. Pitch -21 is above,
-20 and +15 are eye level, +16 is below. Unknown/absent people never enter
the frame. Empty visible means scenery, not an implicit selfie. An upload
belongs to the authenticated uploader, never to the avatar or URL segment.
A preoccupied reference slot 1 leaves slot 2 for the screenshot. Both style
families use the existing character-photo use case, preserving its negative
and adding each anti-CGI term once. No world or image/LLM service is used.
"""
import asyncio
import io
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_tmp = tempfile.TemporaryDirectory(prefix="photo-screenshot-")
os.environ["STORAGE_DIR"] = _tmp.name
os.environ["INSTANCE_DIR"] = _tmp.name
from app.core import paths
paths.init(_tmp.name)
paths.init_instance(_tmp.name)
from app.core import db

db.init_schema()
from fastapi import HTTPException
from PIL import Image
from starlette.requests import Request
from app.core import scene_photo, chat_ops, config
from app.core.auth_dependency import current_user_ctx
from app.models.character import save_character_profile
from app.skills import image_regenerate as ir
from app.imagegen import service
from app.core.prompt_builder import PromptBuilder

for name in ("Ann", "Bob", "Cid", "Dee"):
    save_character_profile(name, {"name": name, "language": "en"}, create_new=True)

view = {"visible": [
    {"name": n, "screen_x": x, "screen_y": .5, "depth_m": d}
    for n, x, d in [("Bob", .1, 2), ("Cid", .5, 5), ("Dee", .9, 8),
                    ("Unknown", .2, 1), ("Absent", .3, 1)]],
    "camera": {"pitch_deg": -21, "height_m": 3, "fov_deg": 70}}


def prepare(v=None, transcript=""):
    with patch("app.models.character.get_character_current_location", return_value="room-loc"), \
         patch("app.models.character.get_character_current_room", return_value="salon"), \
         patch("app.core.room_entry.characters_in_room", return_value=["Ann", "Bob", "Cid", "Dee"]), \
         patch.object(scene_photo, "_room_transcript", return_value=transcript), \
         patch("app.core.interaction_engine.get_interaction", return_value=None):
        return scene_photo.prepare_scene_photo("Ann", **({"view": v} if v is not None else {}))

legacy = prepare()
assert legacy["subjects"] == ["Bob", "Cid", "Dee"]
framed = prepare(view)
assert framed["subjects"] == framed["present"] == ["Bob", "Cid", "Dee"]
for wording in ("Bob: left, front", "Cid: centre", "Dee: right, back", "from above", "wide"):
    assert wording in framed["prompt"], framed["prompt"]
assert "Unknown" not in framed["prompt"] and "Absent" not in framed["prompt"]
for pitch, wording in [(-20, "eye level"), (15, "eye level"), (16, "from below")]:
    v = {**view, "camera": {**view["camera"], "pitch_deg": pitch}}
    assert wording in prepare(v)["prompt"]
assert prepare({**view, "visible": []})["subjects"] == []
# Exact screen thirds and FOV boundary; duplicate client names cannot add people.
for x, label in [(1 / 3, "centre"), (2 / 3, "right")]:
    v = {"visible": [{"name": "Bob", "screen_x": x, "screen_y": .5, "depth_m": 2}],
         "camera": {"pitch_deg": 0, "height_m": 1, "fov_deg": 59}}
    result = prepare(v)
    assert f"Bob: {label}." in result["prompt"] and "close view" in result["prompt"]
    assert "front" not in result["prompt"] and "back" not in result["prompt"]
assert prepare({**view, "visible": [view["visible"][0], view["visible"][0]]})["subjects"] == ["Bob"]
assert prepare({**view, "visible": [{**view["visible"][0], "name": "Ann"}]})["subjects"] == ["Ann"]
assert prepare() == legacy, "no-view output stays unchanged"
print("PASS framing, angle boundaries, absent names, empty frame, legacy")

# The real StrictUndefined template receives the filtered subjects and framing.
from types import SimpleNamespace
llm_inputs = []
def fake_llm(**kwargs):
    llm_inputs.append(kwargs)
    return SimpleNamespace(content="Bob smiles by the window.")
with patch("app.core.llm_router.llm_call", side_effect=fake_llm):
    distilled = prepare({**view, "visible": [view["visible"][0]]}, transcript="Cid: Hello, Bob.")
assert distilled["subjects"] == distilled["present"] == ["Bob"]
assert "Bob: left" in distilled["prompt"] and "Cid" not in distilled["prompt"]
assert "Exactly these people are in the frame: Bob" in llm_inputs[0]["system_prompt"]
assert "Camera from above" in llm_inputs[0]["system_prompt"]
print("PASS actual LLM template receives filtered people and framing")

# Real upload boundary: multipart parsing, capped read and magic-byte check.
buf = io.BytesIO()
Image.new("RGB", (2, 2)).save(buf, "JPEG")
boundary = "photo-smoke"
body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="shot.jpg"\r\n'
        'Content-Type: image/jpeg\r\n\r\n').encode() + buf.getvalue() + f'\r\n--{boundary}--\r\n'.encode()
async def receive():
    return {"type": "http.request", "body": body, "more_body": False}
request = Request({"type": "http", "method": "POST", "path": "/chat/me/upload-image",
                   "headers": [(b"content-type", f"multipart/form-data; boundary={boundary}".encode())]}, receive)
token = current_user_ctx.set({"id": "uploader"})
try:
    image_id = asyncio.run(chat_ops.save_chat_upload(request))["image_id"]
finally:
    current_user_ctx.reset(token)
source = chat_ops.resolve_owned_chat_upload_path(image_id, "uploader")
for bad, owner, code in [(image_id, "other", 403), ("000000000000.jpg", "uploader", 404),
                          ("../world.db", "uploader", 404)]:
    try:
        chat_ops.resolve_owned_chat_upload_path(bad, owner)
        raise AssertionError("unowned image accepted")
    except HTTPException as exc:
        assert exc.status_code == code
print("PASS real upload records ownership; foreign/unknown/path ids refused")

calls = []
class Backend:
    name, api_type, ref_slot_count, model = "Fake", "fake", 3, ""
    image_family = "natural"
    def generate(self, prompt, negative, params, log_meta=None):
        calls.append((prompt, negative, params))
        return [buf.getvalue()]
backend = Backend()
class Service:
    enabled = True
    def _wait_for_explicit_backend(self, name): return backend
    def _get_instance_config(self, character, b): return {}
    def run_on_backend_channel(self, b, fn, **kw): return fn()
    def run_on_backend(self, b, op, **kw): return op(b), b
    def _generate_image_analysis(self, *args): return ""

real_regenerate = ir.regenerate_image
handoffs = []
def regenerate(**kw):
    handoffs.append(kw)
    return real_regenerate(**kw)

for family, style in [("natural", "A documentary photograph"), ("keywords", "documentary, photo")]:
    backend.image_family = family
    original_get = config.get
    def configured(key, default=None):
        if key == f"image_generation.use_cases.character.styles.{family}.prompt_style":
            return style
        if key == f"image_generation.use_cases.character.styles.{family}.prompt_negative":
            return "grain, cgi"
        return original_get(key, default)
    with patch.object(scene_photo, "prepare_scene_photo", return_value=framed), \
         patch.object(ir, "regenerate_image", side_effect=regenerate), \
         patch.object(service, "get_image_service", return_value=Service()), \
         patch.object(config, "get", side_effect=configured), \
         patch.object(PromptBuilder, "resolve_reference_slots", return_value={
             "reference_images": {"input_reference_image_1": str(source)}, "has_reference_slots": True}), \
         patch("app.core.perception.announce_action"):
        result = scene_photo.take_scene_photo("Ann", prompt="Friends by the window", backend_name="Fake",
            character_names=["Bob"], use_room=False, pose_check=False,
            reference_image_id=image_id, user_id="uploader")
    assert result["ok"], result
    kw = handoffs[-1]
    assert kw["occasion"] == "photo" and kw["create_new"] and kw["use_source_as_reference"]
    assert kw["source_image_path"] == str(source)
    p, neg, params = calls[-1]
    assert p.startswith(style), p
    assert "composition, camera angle and poses" in p and "must not be copied" in p
    assert params["reference_images"]["input_reference_image_2"] == str(source)
    terms = [v.strip().lower() for v in neg.split(",")]
    for term in ["grain", "3d render", "cgi", "video game screenshot", "low poly", "plastic skin", "game engine"]:
        assert terms.count(term) == 1, (term, neg)
    assert "strength" not in params and "denoise" not in params
print("PASS real regenerate: source slot, photo style in both families, merged negative")

# The route must parse the additive fields and use the authenticated user,
# preserving charging on success and refusing unowned uploads before rendering.
from app.routes import play

async def json_request(payload):
    import json
    raw = json.dumps(payload).encode()
    async def receive_json():
        return {"type": "http.request", "body": raw, "more_body": False}
    return Request({"type": "http", "method": "POST", "path": "/play/scene-photo", "headers": []}, receive_json)

# A resolved character would consume slot 1. An empty screenshot must leave
# that slot for the source itself, rather than silently adding the photographer.
face_ref = source.parent / "face.png"
face_ref.write_bytes(buf.getvalue())
def character_slots(builder, variables, max_slots=0):
    refs = {"input_reference_image_1": str(face_ref)} if variables.persons else {}
    return {"reference_images": refs, "has_reference_slots": bool(refs)}

async def route_checks():
    with patch("app.models.account.get_active_character", return_value="Ann"), \
         patch.object(play, "_player_action_gate", return_value=SimpleNamespace(SKILL_ID="camera")), \
         patch("app.models.character.get_character_current_location", return_value="room-loc"), \
         patch("app.models.character.get_character_current_room", return_value="salon"), \
         patch("app.core.room_entry.characters_in_room", return_value=["Ann", "Bob", "Cid", "Dee"]), \
         patch.object(scene_photo, "_room_transcript", return_value=""), \
         patch("app.core.interaction_engine.get_interaction", return_value=None):
        response = await play.play_scene_photo_prepare(await json_request({"view": view}), user={"id": "uploader"})
        assert response["subjects"] == ["Bob", "Cid", "Dee"]
        assert "from above" in response["prompt"]
        response = await play.play_scene_photo_prepare(await json_request({}), user={"id": "uploader"})
        assert response == legacy
        try:
            await play.play_scene_photo_prepare(await json_request({"view": {"visible": [], "camera": {}}}), user={"id": "uploader"})
            raise AssertionError("malformed view accepted")
        except HTTPException as exc:
            assert exc.status_code == 422

    with patch("app.models.account.get_active_character", return_value="Ann"), \
         patch.object(play, "_player_action_gate", return_value=SimpleNamespace(SKILL_ID="camera")), \
         patch.object(scene_photo, "prepare_scene_photo", return_value=framed), \
         patch.object(service, "get_image_service", return_value=Service()), \
         patch.object(PromptBuilder, "resolve_reference_slots", autospec=True, side_effect=character_slots), \
         patch("app.core.perception.announce_action") as announce, \
         patch("app.core.skill_gate.charge") as charge:
        payload = {"prompt": "The reference image gives only composition, camera angle and poses; its 3D/CGI look must not be copied.\nThe reference image gives only composition, camera angle and poses; its 3D/CGI look must not be copied.",
                   "reference_image_id": image_id, "backend": "Fake", "pose_check": False,
                   "negative_prompt": "CGI, cgi, soft focus, 3d render, CGI", "character_names": [], "use_room": False}
        response = await play.play_scene_photo(await json_request(payload), user={"id": "uploader"})
        assert response["ok"]
        charge.assert_called_once_with("Ann", "camera")
        prompt, negative, params = calls[-1]
        assert prompt.count("composition, camera angle and poses") == 1
        assert params["reference_images"] == {"input_reference_image_1": str(source)}
        terms = [term.strip().lower() for term in negative.split(",")]
        assert terms.count("cgi") == terms.count("3d render") == terms.count("soft focus") == 1
        count_before = len(calls)
        for uid, ref, expected in [("other", image_id, 403), ("uploader", "missing.jpg", 404)]:
            try:
                await play.play_scene_photo(await json_request({**payload, "reference_image_id": ref}), user={"id": uid})
                raise AssertionError("unowned reference reached generation")
            except HTTPException as exc:
                assert exc.status_code == expected
        assert len(calls) == count_before
        charge.assert_called_once()
        announce.assert_called_once()
        assert "selfie" not in announce.call_args.args[1].lower(), "scenery is not a selfie"

asyncio.run(route_checks())
print("PASS routes: view parsing/422, authenticated ownership, submit, exclusions once, success-only charge")
