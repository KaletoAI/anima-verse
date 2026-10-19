#!/usr/bin/env python3
"""One-call proposals on a temporary world; no live LLM or writes by propose.

Two rooms span x=0..6 and 6.2..10, y=0..4. The 0.2 m gap aligns
at x=6, yielding the 10 by 4 rectangle. The digest pins the pre-move
World-Dev layout prompt, including literal JSON braces and plot context.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['ANIMATION_CLIPS_DIR'] = tempfile.mkdtemp(prefix='building-clips-')
from app.core import paths
paths.init(Path(tempfile.mkdtemp(prefix='building-propose-')))
from app.core import db
db.init_schema()
from app.models import world
from app.core.world_ops import update_location_with_extras

FIXTURE = {'id': 'fixture-building', 'name': 'Bakery', 'description': 'Stone bakery.',
           'rooms': [{'id': 'shop', 'name': 'Shop', 'description': 'Bread.'}],
           'map3d': {'boundary': [[0, 0], [12, 0], [12, 10], [0, 10]], 'storey_height_m': 3}}
# BASE 2a6be06a: rendered before moving helpers out of world_dev.py.
PROMPT_SHA256 = '3dbf182e2e913582ba0ba9551a0da971e18660efe1a5453a49935dfc54eca04c'


def main():
    try:
        from app.core import building_assistant as ba, layout_prompt as lp
    except ImportError as exc:
        print(f'FAIL proposal module missing: {exc}')
        return 1
    from app.core.llm_router import fallback_parent
    from app.core.prompt_templates import render_task
    with patch('app.core.surface_textures.library_kinds', return_value={'plaster', 'wood_planks'}):
        prompt = lp.load_schema('layout', layout_location=lp.format_layout_location(FIXTURE),
                                layout_rooms=lp.format_layout_rooms(FIXTURE),
                                surface_kinds=lp.format_surface_kinds(),
                                world_setup_block=lp.world_setup_block())
    assert hashlib.sha256(prompt.encode()).hexdigest() == PROMPT_SHA256
    assert fallback_parent('building_layout') == 'intent'
    loc = world.add_location('Bakery', 'Stone bakery.', rooms=[])
    update_location_with_extras(loc['id'], {'map3d': FIXTURE['map3d']})
    before = world.get_location_by_id(loc['id'])
    draft = {'summary': 'Shop and kitchen.', 'storey_height_m': 3.2,
             'rooms': [{'name': 'Shop', 'room_type': 'workshop', 'x': 0, 'y': 0, 'w': 6, 'd': 4},
                       {'name': 'Kitchen', 'room_type': 'kitchen', 'x': 6.2, 'y': 0, 'w': 3.8, 'd': 4}],
             'hull': {'style': 'steinhaus', 'overrides': {}}}
    def call(answer=None, **kwargs):
        with patch.object(ba, 'llm_call', return_value=SimpleNamespace(content=answer)) as llm:
            result = ba.propose(loc['id'], 'A bakery', **kwargs)
            assert llm.call_count == 1
            assert llm.call_args.kwargs['task'] == 'building_layout'
            return result, llm.call_args.kwargs
    def fence(data):
        return '```json:layout\n' + json.dumps(data) + '\n```'
    result, _ = call(fence(draft))
    assert result['ok'], result
    norm = result['normalized']
    assert norm['outline'] == [[0., 0.], [10., 0.], [10., 4.], [0., 4.]], norm
    assert norm['rooms'][1]['layout']['x'] == 6
    assert result['hull']['seed'] == result['seed']
    assert 0 <= result['seed'] < 2**31
    assert norm['storey_height_m'] == 3.2
    assert [r['room_type'] for r in norm['rooms']] == ['workshop', 'kitchen']
    for answer, error in [('Nothing here', 'no_layout'), ('```json:layout\n{"rooms": [}\n```', 'bad_json'),
                          ('```json:layout\n{"rooms": [', 'bad_json'), (fence({'rooms': []}), 'bad_layout'), (fence(42), 'bad_layout')]:
        got, _ = call(answer)
        assert not got['ok'] and got['error'] == error, got
    unknown = {**draft, 'hull': {'style': 'unknown'}}
    got, _ = call(fence(unknown))
    assert got['hull'] is None and any(w['code'] == 'hull_style_unknown' for w in got['warnings'])
    got, _ = call(fence(unknown), style='steinhaus')
    assert got['hull']['style'] == 'steinhaus'
    _, args = call(fence(draft), previous=norm, revision='Move the kitchen east')
    assert json.dumps(norm, ensure_ascii=False) in args['user_prompt']
    assert 'Move the kitchen east' in args['user_prompt']
    with patch.object(ba, 'llm_call', side_effect=RuntimeError('offline')):
        got = ba.propose(loc['id'], 'Bakery')
    assert got['error'] == 'llm_failed' and 'offline' in str(got)
    inputs = dict(text='Bakery', forced_style='', layout_schema=prompt, room_types=[], hull_styles=[])
    for extra in ({}, {'previous': '', 'revision': ''}, {'previous': json.dumps(norm), 'revision': 'Move kitchen'}):
        system, user = render_task('building_layout', **inputs, **extra)
        assert 'ONE-SHOT' in system and 'Bakery' in user
    from app.core.auth_dependency import is_admin_only_path
    assert is_admin_only_path(f"/world/locations/{loc['id']}/building-assistant/propose", 'POST')
    assert world.get_location_by_id(loc['id']) == before
    print('PASS proposal, failures, style, seed, revision, template, fallback, prompt digest, auth, no writes')
    return 0


if __name__ == '__main__':
    sys.exit(main())
