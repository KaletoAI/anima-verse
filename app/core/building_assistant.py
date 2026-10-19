"""Propose building plans, run guarded build chains and restore snapshots."""
import copy
import json
import re
import secrets
import threading
from typing import Any

from app.core.furniture_kits import kit_for_location, load_room_types
from app.core.furnish_kit_building import furnish_location
from app.core.hull_model import generate_hull, propose_hull
from app.core.hull_styles import load_styles, validate_description
from app.core.layout_apply import (
    _read_snapshot, apply_layout, layout_counts, layout_snapshot,
    restore_layout_snapshot, sanitize_layout,
)
from app.core.layout_prompt import (
    extract_json_block, format_layout_location, format_layout_rooms,
    format_surface_kinds, layout_target, load_schema, world_setup_block,
)
from app.core.llm_router import llm_call
from app.core.location_model3d import (
    claim_job, find_building_model, release_job, select_model,
)
from app.core.log import get_logger
from app.core.prompt_templates import render_task
from app.core.surface_textures import library_kinds

logger = get_logger(__name__)
_status_lock = threading.RLock()
_statuses: dict[str, dict] = {}


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


def status(location_id: str) -> dict:
    """Return an isolated view of the process-local chain state."""
    with _status_lock:
        return copy.deepcopy(_statuses.get(location_id, {
            'state': 'idle', 'steps': [], 'snapshot_id': '', 'previous_model': '',
        }))


def _step(location_id: str, step_id: str, state: str, message: str = '',
          counts: dict | None = None) -> None:
    with _status_lock:
        step = next(s for s in _statuses[location_id]['steps'] if s['id'] == step_id)
        step.update(state=state, message=message, counts=counts or {})


def _run_chain(location_id: str, description: dict | None) -> None:
    task_id, error, step_id = '', '', 'hull'
    try:
        from app.core.task_queue import get_task_queue
        try:
            task_id = get_task_queue().track_start(
                'model3d_generation', f'Building: {location_id}', start_running=True)
        except Exception:
            logger.exception('Could not track building chain for %s', location_id)
        _step(location_id, 'hull', 'running')
        if description is None:
            description = propose_hull(location_id)['description_json']
        result = generate_hull(location_id, description)
        if not result.get('ok'):
            raise RuntimeError(result.get('error') or 'Hull build failed')
        _step(location_id, 'hull', 'done')
        step_id = 'furnish'
        _step(location_id, 'furnish', 'running')
        kit = kit_for_location(location_id)
        if kit is None:
            _step(location_id, 'furnish', 'skipped', 'no kit for this style')
        else:
            result = furnish_location(location_id, kit, dry_run=False)
            reasons: dict[str, int] = {}
            for room in result.get('skipped', []):
                reason = room.get('reason') or 'unknown'
                reasons[reason] = reasons.get(reason, 0) + 1
            _step(location_id, 'furnish', 'done', counts={
                'rooms': len(result.get('rooms', [])),
                'skipped': len(result.get('skipped', [])), 'reasons': reasons,
            })
    except Exception as exc:
        error = str(exc) or type(exc).__name__
        logger.exception('Building %s step %s failed', location_id, step_id)
        _step(location_id, step_id, 'failed', error)
        if step_id == 'hull':
            _step(location_id, 'furnish', 'skipped', 'Hull build failed')
    finally:
        if task_id:
            try:
                get_task_queue().track_finish(task_id, error=error)
            except Exception:
                logger.exception('Could not finish building task %s', task_id)
        with _status_lock:
            release_job(location_id, kind='hull')
            _statuses[location_id]['state'] = 'failed' if error else 'done'


def apply(location_id: str, draft: dict, hull: dict | None = None) -> dict:
    """Apply a fresh normalized plan and launch one guarded daemon chain."""
    with _status_lock:
        if not claim_job(location_id, kind='hull'):
            return {'ok': False, 'error': 'busy'}
        started = False
        try:
            loc = layout_target(location_id)
            if not loc:
                return {'ok': False, 'error': 'not_found'}
            try:
                normalized, _ = sanitize_layout(
                    draft, location=loc, surface_kinds=library_kinds(), derive_contour=True)
            except ValueError as exc:
                return {'ok': False, 'error': 'contour', 'errors': [str(exc)]}
            if normalized.get('errors'):
                return {'ok': False, 'error': 'contour', 'errors': normalized['errors']}
            description = None
            if (isinstance(hull, dict) and isinstance(hull.get('style'), str)
                    and hull['style'] in load_styles()):
                description = validate_description(hull, load_styles())
            elif normalized.get('hull_valid'):
                description = normalized['hull']
            previous = find_building_model(location_id)
            snapshot_id = layout_snapshot(location_id)
            applied = apply_layout(normalized)
            _statuses[location_id] = {
                'state': 'running', 'snapshot_id': snapshot_id,
                'previous_model': previous.name if previous else '',
                'steps': [dict(id=key, state='done' if key == 'floorplan' else 'pending',
                               message='', counts=layout_counts(normalized) if key == 'floorplan' else {})
                          for key in ('floorplan', 'hull', 'furnish')],
            }
            try:
                threading.Thread(target=_run_chain, args=(location_id, description),
                                 daemon=True).start()
            except Exception as exc:
                _statuses[location_id]['state'] = 'failed'
                _step(location_id, 'hull', 'failed', str(exc))
                _step(location_id, 'furnish', 'skipped', 'Hull build failed')
                raise
            started = True
            return {'ok': True, 'snapshot_id': snapshot_id, 'applied': applied}
        finally:
            if not started:
                release_job(location_id, kind='hull')


def undo(location_id: str, snapshot_id: str) -> dict:
    """Restore a plan and its remembered selection, serialized with Apply."""
    with _status_lock:
        if status(location_id)['state'] == 'running':
            return {'ok': False, 'error': 'busy'}
        if not claim_job(location_id, kind='hull'):
            return {'ok': False, 'error': 'busy'}
        try:
            try:
                payload = _read_snapshot(snapshot_id)
                if payload.get('location_id') != location_id:
                    return {'ok': False, 'error': 'not_found'}
                restored = restore_layout_snapshot(snapshot_id)
            except ValueError:
                return {'ok': False, 'error': 'not_found'}
            previous = status(location_id)['previous_model']
            if previous:
                select_model(location_id, previous)
            _statuses[location_id] = {
                'state': 'idle', 'steps': [], 'snapshot_id': '',
                'previous_model': '', 'message': 'Layout restored',
            }
            return {'ok': True, 'restored': restored, 'reselected': previous}
        finally:
            release_job(location_id, kind='hull')
