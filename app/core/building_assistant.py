"""Read-only, one-call building proposals using the shared layout normalizer."""
import json
import re
import secrets
from typing import Any

from app.core.furniture_kits import load_room_types
from app.core.hull_styles import load_styles
from app.core.layout_apply import sanitize_layout
from app.core.layout_prompt import (
    extract_json_block, format_layout_location, format_layout_rooms,
    format_surface_kinds, layout_target, load_schema, world_setup_block,
)
from app.core.llm_router import llm_call
from app.core.prompt_templates import render_task
from app.core.surface_textures import library_kinds


def propose(location_id: str, text: str, *, style: str = '',
            previous: dict | None = None, revision: str = '') -> dict:
    """Return a normalized preview; never apply layouts or start build jobs."""
    seed = secrets.randbelow(2**31)
    result: dict[str, Any] = {
        'ok': False, 'error': '', 'draft': {}, 'normalized': {},
        'warnings': [], 'errors': [], 'seed': seed, 'hull': None,
    }
    loc = layout_target(location_id)
    if not loc:
        return {**result, 'error': 'not_found'}
    schema = load_schema(
        'layout', layout_location=format_layout_location(loc),
        layout_rooms=format_layout_rooms(loc), surface_kinds=format_surface_kinds(),
        world_setup_block=world_setup_block())
    styles = [{'id': key, 'name': value['name'], 'description': value['description']}
              for key, value in load_styles().items()]
    types = [{'id': key, 'label': value['name']} for key, value in load_room_types().items()]
    system_prompt, user_prompt = render_task(
        'building_layout', text=text, forced_style=style, layout_schema=schema,
        room_types=types, hull_styles=styles,
        previous=json.dumps(previous, ensure_ascii=False) if previous is not None else '',
        revision=revision)
    name = str(loc.get('name') or location_id)
    try:
        response = llm_call(task='building_layout', system_prompt=system_prompt,
                            user_prompt=user_prompt, agent_name='system',
                            label=f'Building design: {name}')
    except Exception as exc:
        return {**result, 'error': 'llm_failed', 'message': str(exc)}
    answer = str(getattr(response, 'content', '') or '')
    try:
        draft = extract_json_block(answer, 'layout')
    except TypeError as exc:
        # The legacy extractor logs len(parsed), which scalar JSON lacks.
        return {**result, 'error': 'bad_layout', 'message': str(exc)}
    if draft is None:
        # The shared extractor returns None for both absent and broken blocks.
        error = 'bad_json' if re.search(r'```json:layout\s*\n', answer) else 'no_layout'
        return {**result, 'error': error}
    if isinstance(draft, dict):
        hull = draft.get('hull')
        if style or isinstance(hull, dict):
            draft['hull'] = {**(hull if isinstance(hull, dict) else {}), 'seed': seed}
            if style:
                draft['hull']['style'] = style
    result['draft'] = draft
    try:
        normalized, warnings = sanitize_layout(
            draft, location=loc, surface_kinds=library_kinds(), derive_contour=True)
    except ValueError as exc:
        return {**result, 'error': 'bad_layout', 'message': str(exc)}
    return {**result, 'ok': True, 'normalized': normalized,
            'warnings': warnings, 'errors': normalized.get('errors', []),
            'hull': normalized.get('hull')}
