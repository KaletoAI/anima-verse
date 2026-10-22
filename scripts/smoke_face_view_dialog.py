#!/usr/bin/env python3
"""Face view through the image dialog: its picks reach the render, once.

Contract, derived by hand from the request (2026-10-22: "the face view's
Generate button uses the image generation dialog, so LoRAs can be passed";
the picks apply to that one run only):

1. Dialog run with prompt "DIALOG_PROMPT", backend "pick-b", LoRA
   {"name": "lora-ok", "strength": 0.7}, negative "DIALOG_NEG":
   the service payload carries exactly prompt == "DIALOG_PROMPT",
   backend == "pick-b", loras == [{"name": "lora-ok", "strength": 0.7}],
   loras_explicit is True, negative_prompt == "DIALOG_NEG"; the stored
   character LoRA ("STORED_LORA") and the stored model ("stored-model",
   which belongs to the character's own backend, not "pick-b") are absent.
2. Dialog run with no LoRA picked (loras == []): no "loras" key at all.
3. The automatic run afterwards (no dialog): no backend, no loras, no
   negative_prompt key, prompt == the default face prompt — nothing of the
   dialog run was stored.
4. Route: dialog keys without view "face" -> 422; malformed loras -> 422;
   a dead explicit pick -> 503 (the explicit-backend guard's own answer);
   a LoRA the library does not associate with the pick -> 400; a valid
   body hands {prompt, backend, loras, negative_prompt} to trigger_now.

All storage is temporary and initialised before world modules are imported.
Usage: ./.venv/bin/python scripts/smoke_face_view_dialog.py
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths


def request(body):
    from starlette.requests import Request
    raw = json.dumps(body).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    return Request({"type": "http", "method": "POST", "headers": []}, receive)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        paths.init(Path(tmp))
        paths.init_instance(Path(tmp) / 'instance')
        from app.core import db, model_refs as mr
        from app.models.character import save_character_profile, get_character_dir
        from smoke_face_retexture_rollback import photo
        db.init_schema()
        (Path(tmp) / 'characters' / 'demo').mkdir(parents=True)
        assert save_character_profile('demo', {
            'profile_image': 'profile.png',
            'outfit_imagegen': {'model': 'stored-model', 'loras': [{'name': 'STORED_LORA'}]}})
        images = get_character_dir('demo') / 'images'
        images.mkdir(exist_ok=True)
        (images / 'profile.png').write_bytes(photo())
        (get_character_dir('demo') / 'model_refs').mkdir(exist_ok=True)

        seen = []

        class Service:
            enabled = True
            last_image_meta = {'created_at': '2026-10-22T12:00:00Z'}

            def generate_from_input(self, raw):
                seen.append(json.loads(raw))
                out = images / 'render.png'
                out.write_bytes(photo())
                return '/images/' + out.name

        with (patch('app.imagegen.service.get_image_service', return_value=Service()),
              patch('app.models.character.postprocess_outfit_image', side_effect=lambda p: p),
              patch('app.imagegen.routing.is_character_match', return_value=False)):
            mr.generate_face_view('demo', True, {
                'prompt': 'DIALOG_PROMPT', 'backend': 'pick-b',
                'loras': [{'name': 'lora-ok', 'strength': 0.7}], 'negative_prompt': 'DIALOG_NEG'})
            p = seen[-1]
            assert p['prompt'] == 'DIALOG_PROMPT', p['prompt']
            assert p['backend'] == 'pick-b'
            assert p['loras'] == [{'name': 'lora-ok', 'strength': 0.7}]
            assert p['loras_explicit'] is True
            assert p['negative_prompt'] == 'DIALOG_NEG'
            assert 'STORED_LORA' not in json.dumps(p) and 'model_override' not in p

            mr.generate_face_view('demo', True, {'prompt': '', 'backend': '', 'loras': [],
                                                 'negative_prompt': ''})
            p = seen[-1]
            assert 'loras' not in p and 'loras_explicit' not in p and 'backend' not in p
            assert p['prompt'] == mr.FACE_VIEW_PROMPT_DEFAULT

            mr.generate_face_view('demo', True)
            p = seen[-1]
            assert 'backend' not in p and 'loras' not in p and 'negative_prompt' not in p
            assert p['prompt'] == mr.FACE_VIEW_PROMPT_DEFAULT
        print('PASS: dialog picks reach the face render once; the automatic run stays routed without LoRAs')

        from fastapi import HTTPException
        from app.routes import characters as routes

        def status(body):
            try:
                asyncio.run(routes.generate_character_model_refs('demo', request(body)))
            except HTTPException as e:
                return e.status_code
            return 200

        class Backend:
            name = 'pick-b'
            lora_filter = ''

        async def alive(name, media='image', *, has_input_image=False):
            assert name == 'pick-b' and has_input_image
            return Backend()

        async def dead(name, media='image', *, has_input_image=False):
            raise HTTPException(status_code=503, detail='not available')

        calls = []
        with (patch.object(mr, 'trigger_now', side_effect=lambda *a, **k: calls.append(k)),
              patch('app.core.config.get_lora_options',
                    side_effect=lambda name, lora_filter='': [{'name': 'lora-ok'}] if name == 'pick-b' else []),
              patch('app.core.explicit_backend.require_explicit_backend_async', side_effect=alive)):
            assert status({'kinds': ['tpose'], 'view': 'main', 'backend': 'pick-b'}) == 422
            assert status({'kinds': ['tpose'], 'view': 'face', 'loras': 'lora-ok'}) == 422
            assert status({'kinds': ['tpose'], 'view': 'face', 'loras': [{'strength': 1}]}) == 422
            assert status({'kinds': ['tpose'], 'view': 'face', 'backend': 'pick-b',
                           'loras': [{'name': 'lora-other', 'strength': 1}]}) == 400
            with patch('app.core.explicit_backend.require_explicit_backend_async', side_effect=dead):
                assert status({'kinds': ['tpose'], 'view': 'face', 'backend': 'pick-b'}) == 503
            assert not calls
            assert status({'kinds': ['tpose'], 'view': 'face', 'prompt': ' P ', 'backend': 'pick-b',
                           'loras': [{'name': 'lora-ok', 'strength': 0.7}], 'negative_prompt': 'N'}) == 200
            assert calls[-1]['tpose_view'] == 'face'
            assert calls[-1]['face_render'] == {'prompt': 'P', 'backend': 'pick-b',
                                                'loras': [{'name': 'lora-ok', 'strength': 0.7}],
                                                'negative_prompt': 'N'}
            assert status({'kinds': ['tpose'], 'view': 'face'}) == 200
            assert calls[-1]['face_render'] is None
        print('PASS: route answers 422/400/503 before the thread starts and hands the dialog picks on')


if __name__ == '__main__':
    main()
