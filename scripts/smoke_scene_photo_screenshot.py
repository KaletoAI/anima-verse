#!/usr/bin/env python3
"""Screenshot photo contract, using only temporary storage and a fake backend.

Usage: ./.venv/bin/python scripts/smoke_scene_photo_screenshot.py

Hand-derived expectations: x=.1/.5/.9 is left/centre/right; depths 2/5/8
put the nearest person in front and farthest in back. Pitch -21 is above,
-20 and +15 are eye level, +16 is below. Unknown/absent people never enter
the frame. Empty visible means scenery, not an implicit selfie. An upload
belongs to the authenticated uploader, never to the avatar or URL segment.
Three slots with a screenshot, room and two people must contain exactly the
screenshot and the two outfit references, in that order. A third person's
reference is dropped, with a log naming that person. Zero slots is text-only.
Both style families use the character-photo style. Anti-CGI negatives are
added once only when the backend supports them. Refusals fall back to state
poses; free-camera photos never become selfies. All storage is temporary.
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
from app.utils import image_prompt_logger

# ImageBackend.generate logs centrally even for a fake engine.
image_prompt_logger.LOG_DIR = Path(_tmp.name) / "logs"
image_prompt_logger.LOG_FILE = image_prompt_logger.LOG_DIR / "image_prompts.jsonl"

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
                   "query_string": b"",
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
    supports_negative_prompt = True
    def generate(self, prompt, negative, params, log_meta=None):
        calls.append((prompt, negative, params))
        return [buf.getvalue()]
backend = Backend()
class Service:
    enabled = True
    pool = None
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
    assert params["reference_images"]["input_reference_image_1"] == str(source)
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

# Task 97: keep the actual detector, outfit cache and slot assignment in play.
import json
import unittest
from contextlib import ExitStack
from app.core import expression_regen as er, prompt_builder as pb
from app.models.character import get_character_images_dir, get_character_profile
from app.models.inventory import add_item

class PhotoRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.outfits = {}
        coat = add_item("Demo coat", category="outfit_piece", prompt_fragment="a linen coat",
                        outfit_piece={"slots": ["top"]})
        cls.other_coat = add_item("Other coat", category="outfit_piece", prompt_fragment="a wool coat",
                                 outfit_piece={"slots": ["top"]})
        def render(character, *, output_stem, **kw):
            image = output_stem.with_suffix(".png")
            image.write_bytes(buf.getvalue())
            image.with_suffix(".json").write_text(json.dumps({"prompt": "Neutral outfit reference"}))
            return image
        for name in ("Ann", "Bob", "Cid"):
            profile = get_character_profile(name)
            profile.update(template="human-default", character_appearance="a person with brown hair",
                           equipped_pieces={"top": coat["id"]}, profile_image="profile.png")
            assert save_character_profile(name, profile)
            (get_character_images_dir(name) / "profile.png").write_bytes(buf.getvalue())
            with patch.object(er, "render_character_image", side_effect=render):
                cls.outfits[name] = str(er.generate_expression_image(er.expression_snapshot(name, "neutral")))
            assert Path(cls.outfits[name]).is_file()
        cls.room = Path(_tmp.name) / "room.png"
        cls.room.write_bytes(buf.getvalue())

    def render_photo(self, names, *, screenshot=True, slots=3, occasion="photo", extra=None, image_service=None):
        # The same live resolver must see the active avatar and NPCs. No
        # PromptBuilder/ref resolver mock can hide the old profile-image path.
        with ExitStack() as stack:
            stack.enter_context(patch.object(backend, "ref_slot_count", slots))
            stack.enter_context(patch.object(pb, "get_active_character", return_value="Ann"))
            stack.enter_context(patch("app.models.account.get_active_character", return_value="Ann"))
            stack.enter_context(patch.object(pb, "get_character_current_feeling", return_value="neutral"))
            stack.enter_context(patch.object(pb.PromptBuilder, "_collect_location",
                                         side_effect=lambda variables: setattr(variables, "ref_image_room", str(self.room))))
            stack.enter_context(patch("app.models.world.get_background_path", return_value=self.room))
            stack.enter_context(patch.object(service, "get_image_service", return_value=image_service or Service()))
            stack.enter_context(patch.object(config, "resolve_use_case_style", return_value={}))
            kw = dict(character_name="Ann", output_path=str(get_character_images_dir("Ann") / "photo.png"),
                      original_prompt="Ann and friends smiling at the window.", backend_name="Fake",
                      character_names=names, occasion=occasion, pose_check=False,
                      use_source_as_reference=screenshot, source_image_path=str(source) if screenshot else "")
            if extra:
                kw.update(extra)
            result = real_regenerate(**kw)
            self.assertTrue(result[0], result)
            return calls[-1]

    def test_screenshot_precedes_people_and_excludes_room(self):
        _, _, params = self.render_photo(["Ann", "Bob"])
        self.assertEqual(params["reference_images"], {
            "input_reference_image_1": str(source),
            "input_reference_image_2": self.outfits["Ann"],
            "input_reference_image_3": self.outfits["Bob"]})

    def test_last_person_dropped_with_log(self):
        with self.assertLogs("image_regen", level="INFO") as logs:
            _, _, params = self.render_photo(["Bob", "Ann", "Cid"])
        self.assertEqual(list(params["reference_images"].values()),
                         [str(source), self.outfits["Bob"], self.outfits["Ann"]])
        dropped = [line for line in logs.output if "drop" in line.lower()]
        self.assertEqual(len(dropped), 1, logs.output)
        self.assertIn("Cid", dropped[0])

    def test_avatar_outfit_in_normal_photo(self):
        _, _, params = self.render_photo(["Ann", "Bob"], screenshot=False)
        # Normal priority remains room, then explicit subjects: the avatar is
        # marked is_user rather than is_agent by the existing detector.
        self.assertEqual(list(params["reference_images"].values()),
                         [str(self.room), self.outfits["Ann"], self.outfits["Bob"]])

    def test_other_regenerate_keeps_profile_and_slot_priority(self):
        _, _, params = self.render_photo(["Ann", "Bob"], screenshot=False, occasion="regenerate")
        self.assertEqual(list(params["reference_images"].values()),
                         [str(self.room), str(get_character_images_dir("Ann") / "profile.png"), self.outfits["Bob"]])

    def test_zero_slots_logs_text_only(self):
        with self.assertLogs("image_regen", level="INFO") as logs:
            _, _, params = self.render_photo(["Ann", "Bob"], slots=0)
        self.assertEqual(params["reference_images"], {})
        self.assertTrue(any("text-only" in line.lower() for line in logs.output), logs.output)

    def test_screenshot_survives_person_reference_error(self):
        with patch.object(PromptBuilder, "_resolve_person_ref_image", side_effect=RuntimeError("bad cache")):
            _, _, params = self.render_photo(["Ann", "Bob"])
        self.assertEqual(params["reference_images"], {"input_reference_image_1": str(source)})

    def test_non_photo_source_keeps_first_free_slot(self):
        _, _, params = self.render_photo(["Ann", "Bob"], occasion="regenerate", slots=4)
        self.assertEqual(list(params["reference_images"].values()),
                         [str(self.room), str(get_character_images_dir("Ann") / "profile.png"),
                          self.outfits["Bob"], str(source)])

    def test_current_outfit_signature_still_required(self):
        profile = get_character_profile("Ann")
        try:
            assert save_character_profile("Ann", {**profile, "equipped_pieces": {"top": self.other_coat["id"]}})
            _, _, params = self.render_photo(["Ann"])
            self.assertEqual(list(params["reference_images"].values()),
                             [str(source), str(get_character_images_dir("Ann") / "profile.png")])
        finally:
            assert save_character_profile("Ann", profile)

    def test_backend_without_negative_support(self):
        from app.imagegen.base import ImageBackend
        class StrictBackend(ImageBackend):
            def __init__(self):
                super().__init__("Fake", "", 0, "fake", "TASK97_FAKE_")
                self.image_family = "natural"
                self.negative_prompt_setting = "no"
                self.ref_slot_count = 3
                self.model = ""
            def check_availability(self): return True
            def _generate(self, prompt, negative, params):
                if negative:
                    raise RuntimeError("HTTP 400: unsupported Venice model control: negative_prompt")
                calls.append((prompt, negative, params))
                return [buf.getvalue()]
        strict = StrictBackend()
        with patch.dict(globals(), backend=strict):
            prompt, negative, _ = self.render_photo(["Ann"], extra={"negative_prompt_extra": scene_photo._SCREENSHOT_NEGATIVE})
        self.assertEqual(negative, "")
        self.assertNotIn("no 3d render", prompt.lower(), "unsupported screenshot negatives must not be folded either")

    def test_routed_retry_rebuilds_slots_and_negative_capability(self):
        from app.imagegen.base import ImageBackend
        from app.imagegen.selection import BackendPool
        class RoutedBackend(ImageBackend):
            def __init__(self, name, slots, negative_setting, fail=False):
                super().__init__(name, "", 0, "fake", "TASK97_ROUTE_")
                self.category, self.image_family = "img2img", "natural"
                self.ref_slot_count, self.negative_prompt_setting = slots, negative_setting
                self.instance_enabled, self._available = True, True
                self.model, self.fail = "", fail
            def check_availability(self): return self.available
            def _generate(self, prompt, negative, params):
                calls.append((prompt, negative, params))
                if self.fail:
                    raise RuntimeError("fixture backend outage")
                if negative:
                    raise RuntimeError("HTTP 400: unsupported Venice model control: negative_prompt")
                return [buf.getvalue()]
        first = RoutedBackend("First", 3, "yes", fail=True)
        second = RoutedBackend("Second", 1, "no")
        svc = Service()
        svc.pool = BackendPool([first, second])
        svc.run_on_backend = svc.pool.run_on_backend
        with patch.dict(config._CONFIG.setdefault("image_generation", {}),
                        {"routing": {"photo": ["First", "Second"]}}):
            self.render_photo(["Ann", "Bob"], image_service=svc,
                              extra={"backend_name": "", "negative_prompt_extra": scene_photo._SCREENSHOT_NEGATIVE})
        self.assertEqual(list(calls[-2][2]["reference_images"].values()),
                         [str(source), self.outfits["Ann"], self.outfits["Bob"]])
        self.assertIn("3d render", calls[-2][1])
        self.assertEqual(calls[-1][2]["reference_images"], {"input_reference_image_1": str(source)})
        self.assertEqual(calls[-1][1], "")
        self.assertNotIn("no 3d render", calls[-1][0].lower())

    def test_refusals_fall_back_in_both_photo_modes(self):
        refusal = "I'm not able to help with this request. The conversation describes explicit content. " * 5
        for v in (None, {**view, "visible": [{**view["visible"][0], "name": "Ann"}]}):
            for answer in (refusal, "I cannot assist with that request.", "Sorry, I can't generate that image.",
                           "I’m sorry, but I can’t help with this request. " * 5,
                           "I apologize, but I cannot generate that content. " * 5, "No.", ""):
                with self.subTest(view=v, answer=answer), \
                     patch("app.core.llm_router.llm_call", return_value=SimpleNamespace(content=answer)), \
                     patch("app.core.scene_render._pose_hint", return_value="smiling"):
                    with self.assertLogs("scene_photo", level="WARNING") as logs:
                        prepared = prepare(v, transcript="Bob: We smile and wave to the camera. " * 8)
                    self.assertTrue(prepared["prompt"].startswith("Candid photograph"), prepared)
                    self.assertIn("smiling", prepared["prompt"])
                    if answer:
                        self.assertNotIn(answer, prepared["prompt"])
                    self.assertEqual(len(logs.output), 1)

    def test_concise_valid_distillation_of_long_transcript(self):
        answer = "Bob smiles and waves at the camera beside the window."
        with patch("app.core.llm_router.llm_call", return_value=SimpleNamespace(content=answer)):
            prepared = prepare(view, transcript="Bob: Let's smile and wave. " * 100)
        self.assertTrue(prepared["prompt"].startswith(answer), prepared)

    def test_free_camera_is_never_a_selfie(self):
        v = {**view, "visible": [{**view["visible"][0], "name": "Ann"}]}
        system_prompts = []
        def from_template(**kw):
            # A model obeying the template exposes contradictory camera rules.
            text = kw["system_prompt"]
            system_prompts.append(text)
            if "selfie" in text.lower() or "Ann is taking the photo" in text:
                return SimpleNamespace(content="A close-up selfie taken by Ann.")
            return SimpleNamespace(content="Ann smiles at the camera from the given angle.")
        with patch("app.core.llm_router.llm_call", side_effect=from_template):
            for transcript in ("", "Bob: Let's take a selfie."):
                with self.subTest(transcript=transcript):
                    prepared = prepare(v, transcript=transcript)
                    text = prepared["prompt"].lower()
                    self.assertNotIn("selfie", text)
                    self.assertNotIn("taken by", text)
                    self.assertIn("unseen photographer", text)
                    self.assertEqual(prepared["subjects"], ["Ann"])
        self.assertNotIn("selfie", system_prompts[-1].lower())
        self.assertNotIn("Ann is taking the photo", system_prompts[-1])
        self.assertIn("unseen photographer outside the frame", system_prompts[-1])
        # A model that ignores the framing rules must not leak selfie prose.
        with patch("app.core.llm_router.llm_call", return_value=SimpleNamespace(content="A selfie taken by Ann.")):
            text = prepare(v, transcript="Ann: Smile for the camera.")["prompt"].lower()
            self.assertNotIn("selfie", text)
            self.assertNotIn("taken by", text)

unittest.main(argv=[sys.argv[0]], verbosity=2)
