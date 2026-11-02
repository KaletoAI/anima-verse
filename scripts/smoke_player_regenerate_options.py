#!/usr/bin/env python3
"""Player regenerate routes must preserve backend and LoRAs before rendering.

Usage: ./.venv/bin/python scripts/smoke_player_regenerate_options.py
Hand oracle: explicit model A and [{name: style, strength: .65}] reach the
render worker unchanged for BOTH gallery and Instagram. Auto reaches it with
backend '' / loras None. A refused explicit backend must start zero threads
and zero queue tracks. Routes run under a player context, with temp storage
initialised before imports; renderers, metadata and thread launch are stubbed.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import MagicMock, patch
from contextlib import ExitStack
from starlette.requests import Request
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TEMP = tempfile.TemporaryDirectory(prefix='player-regen-options-')
os.environ['STORAGE_DIR'] = TEMP.name
os.environ['INSTANCE_DIR'] = TEMP.name
from app.core import paths
paths.init(TEMP.name)
paths.init_instance(TEMP.name)
from app.core.auth_dependency import current_user_ctx
from app.routes import characters, instagram


def request(body):
    async def receive():
        return {'type': 'http.request', 'body': json.dumps(body).encode()}
    return Request({'type': 'http', 'method': 'POST', 'path': '/', 'headers': []}, receive)


class InlineThread:
    def __init__(self, target, args=(), **kwargs):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


async def direct_thread(fn, *args):
    return fn(*args)


async def main():
    image = Path(TEMP.name) / 'photo.png'
    image.write_bytes(b'fixture')
    loras = [{'name': 'style', 'strength': .65}]
    token = current_user_ctx.set({'id': 'player', 'role': 'user'})
    try:
        with ExitStack() as stack:
            stack.enter_context(patch('asyncio.to_thread', side_effect=direct_thread))
            queue = MagicMock()
            queue.track_start.return_value = 'track1'
            stack.enter_context(patch('app.core.task_queue.get_task_queue', return_value=queue))
            stack.enter_context(patch('app.core.task_router.resolve_queue', return_value='image'))
            stack.enter_context(patch('app.models.character.get_character_config', return_value={}))
            stack.enter_context(patch.object(characters, 'get_character_config', return_value={}))
            stack.enter_context(patch.object(characters, 'get_character_images_dir', return_value=Path(TEMP.name)))
            stack.enter_context(patch.object(characters, 'get_character_image_prompts', return_value={image.name: 'Source prompt'}))
            stack.enter_context(patch('app.models.character.get_single_image_meta', return_value={}))
            stack.enter_context(patch.object(instagram, 'get_post', return_value={
                'agent_name': 'Ann', 'image_filename': image.name, 'image_prompt': 'Source prompt'}))
            stack.enter_context(patch.object(instagram, 'get_instagram_dir', return_value=Path(TEMP.name)))
            stack.enter_context(patch.object(instagram, 'load_image_meta', return_value={}))
            render = stack.enter_context(patch('app.skills.image_regenerate.regenerate_image',
                return_value=(True, 'Source prompt', str(image))))
            for module, call in (
                (characters, lambda body: characters.regenerate_character_image('Ann', image.name, request(body))),
                (instagram, lambda body: instagram.regenerate_post_image('p1', request(body))),
            ):
                with patch.object(module, 'require_explicit_backend') as require, \
                     patch('threading.Thread', side_effect=InlineThread) as thread:
                    for body in ({'backend': 'A', 'loras': loras}, {}):
                        render.reset_mock(); require.reset_mock()
                        assert (await call(body))['status'] == 'started'
                        render.assert_called_once()
                        assert render.call_args.kwargs['backend_name'] == body.get('backend', '')
                        assert render.call_args.kwargs['loras'] == body.get('loras')
                        if body:
                            require.assert_called_once_with('A')
                        else:
                            require.assert_not_called()
                    queue.reset_mock(); thread.reset_mock()
                    require.side_effect = HTTPException(503, 'Unavailable explicit pick')
                    try:
                        await call({'backend': 'A', 'loras': loras})
                    except HTTPException as error:
                        assert error.status_code == 503
                    else:
                        raise AssertionError('explicit refusal was swallowed')
                    thread.assert_not_called()
                    queue.track_start.assert_not_called()
                print(f'{module.__name__}: PASS (player explicit/Auto forwarding, preflight before thread)')
    finally:
        current_user_ctx.reset(token)


asyncio.run(main())
TEMP.cleanup()
