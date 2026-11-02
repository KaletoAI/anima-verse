"""Resumable MotionBricks transition jobs, staging and explicit publication."""
import json
import math
from pathlib import Path
import re
import shutil

from app.core import animation_clips as clips, paths, pose_catalog, hub_ops
from app.core.clip_bvh_export import export_clip_bvh
from app.core.fbx_import import import_source
from app.core.keyed_lock import keyed_lock
from app.core.pose_animation import ChoiceError, _age_s, _read_candidates
from app.core.task_queue import get_task_queue
from app.core.timeutils import utc_now_iso
from app.imagegen.service import get_image_service

TASK_TYPE = 'pose_transition'
STAGING_DIRNAME = '.pose_transition'
MAX_VARIANTS = 4
DEFAULT_VARIANTS = 3
CANDIDATE_MAX_AGE_DAYS = 7
WARN = {'hop_cm': 2.0, 'foot_slide_cm': 3.0,
        'final_root_error_cm': 5.0, 'final_yaw_error_deg': 5.0}


def _staging_root():
    return paths.get_clips_inbox_dir() / STAGING_DIRNAME


def _staging(task_id):
    if not re.fullmatch(r'task_[0-9a-f]+', str(task_id)):
        raise ChoiceError(404, 'unknown job')
    root = _staging_root().resolve()
    folder = (root / task_id).resolve()
    if folder.parent != root:
        raise ChoiceError(404, 'unknown job')
    return folder


def pose_clip(pose, cset):
    entry = pose_catalog.get_catalog('pose').get('standing' if pose == 'walking' else pose)
    if not entry or not entry.get('solo', True):
        raise ValueError('unknown or non-solo pose')
    kind = entry.get('animation')
    if not kind:
        raise ValueError('pose has no animation')
    for wanted in dict.fromkeys((cset, '')):
        if any(e['kind'] == kind and e['set'] == wanted and e['path'].suffix.lower() == '.fbx'
               for e in clips.clip_entries()):
            return kind, wanted
    raise ValueError('pose animation missing from library')


def affected_rule(start_pose, target_pose):
    rule = clips.resolve_pose_transition(start_pose, target_pose)
    return {'from': rule['from'] if rule else start_pose,
            'to': rule['to'] if rule else target_pose,
            'store': rule.get('store', 'shared') if rule else 'shared',
            'old_kind': rule['kind'] if rule else None}


def suggested_kind(start_pose, target_pose):
    def clean(value):
        return re.sub('[^a-z0-9-]+', '-', value.replace('@', '').replace('*', 'any')).strip('-')
    base = clips.validate_kind(f'mb-{clean(start_pose)}-to-{clean(target_pose)}')
    taken = {e['kind'] for e in clips.clip_entries()}
    kind, n = base, 2
    while kind in taken:
        kind, n = f'{base}-{n}', n + 1
    return kind


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'invalid {name}')
    return value


def _placement(data):
    return {key: _number(data.get(key), key, low, high) for key, low, high in (
        ('forward_m', -2, 2), ('left_m', -2, 2), ('yaw_deg', -180, 180))}


def variant_params(t0, count, duration, loop):
    def time(k):
        t = t0 + k * .5
        return t % duration if loop else min(max(t, min(.2, duration / 2)), max(duration - .2, duration / 2))
    return [{'start_time_s': time(k), 'max_tokens': 16} for k in range(count)]


def report_warnings(report):
    report = report.get('metrics', report)
    def maximum(value):
        if isinstance(value, dict):
            return max((maximum(v) for v in value.values()), default=0)
        if isinstance(value, list):
            return max((maximum(v) for v in value), default=0)
        return abs(value) if isinstance(value, (int, float)) else 0
    return [name for field, name in (('hop_cm', 'hop'), ('foot_slide_cm', 'slide'),
            ('final_root_error_cm', 'root_error'), ('final_yaw_error_deg', 'yaw_error'))
            if maximum(report.get(field)) > WARN[field]]


def submit(*, start_pose, target_pose, cset='', start_time_s, target_time_s,
           forward_m, left_m, yaw_deg, guide=None, variants=DEFAULT_VARIANTS, backend=''):
    if not isinstance(start_pose, str) or not isinstance(target_pose, str) or start_pose == target_pose:
        raise ValueError('start and target must be different poses')
    cset = clips._validate_set(cset)
    if isinstance(variants, bool) or not isinstance(variants, int) or not 1 <= variants <= MAX_VARIANTS:
        raise ValueError('variants must be 1..4')
    for pose in (start_pose, target_pose):
        pose_clip(pose, cset)
    _number(start_time_s, 'start_time_s', 0, 86400)
    _number(target_time_s, 'target_time_s', 0, 86400)
    placement = _placement(locals())
    if yaw_deg == -180:
        raise ValueError('yaw_deg must be greater than -180')
    if guide is not None:
        if not isinstance(guide, dict):
            raise ValueError('guide must be an object')
        guide = dict(guide)
        guide['kind'] = clips.validate_kind(guide.get('kind'))
        guide['set'] = clips._validate_set(guide.get('set', ''))
        _number(guide.get('time_s'), 'guide.time_s', 0, 86400)
        _placement(guide)
        if guide['yaw_deg'] == -180:
            raise ValueError('guide yaw_deg must be greater than -180')
        if not any(e['kind'] == guide['kind'] and e['set'] in (guide['set'], '') for e in clips.clip_entries()):
            raise ValueError('guide clip missing')
    if not isinstance(backend, str):
        raise ValueError('backend must be a string')
    route = get_image_service().resolve_transition_backend(backend)
    if variants > route.backend.max_variants:
        raise ValueError('backend variant limit exceeded')
    payload = dict(start_pose=start_pose, target_pose=target_pose, cset=cset,
                   start_time_s=start_time_s, target_time_s=target_time_s,
                   **placement, guide=guide, variants=variants, backend=route.backend.name)
    tid = get_task_queue().submit(TASK_TYPE, payload, max_retries=0, queue_name=TASK_TYPE)
    return {'task_id': tid}


def _prepare(payload, folder):
    files, exports = {}, {}
    for side in ('start', 'target'):
        kind, used = pose_clip(payload[side + '_pose'], payload['cset'])
        path = folder / f'{side}.bvh'
        exports[side] = dict(export_clip_bvh(kind, used, path), kind=kind, set=used)
        files['input_' + side + '_bvh'] = str(path)
    duration = exports['start']['duration_s']
    meta = clips.clip_meta(exports['start']['kind'], exports['start']['set']) or {}
    loop = bool(meta.get('loop'))
    if payload['start_time_s'] > duration or payload['target_time_s'] > exports['target']['duration_s']:
        raise ValueError('time outside clip')
    group = (pose_catalog.get_catalog('pose').get(payload['target_pose']) or {}).get('group', 'stand')
    constrained = group in ('seat', 'ground', 'lie')
    target = dict(time_s=payload['target_time_s'], rig='mixamo',
                  num_poses=1 if constrained else 4, hips_constrained=constrained, early_frames=0,
                  **{k: payload[k] for k in ('forward_m', 'left_m', 'yaw_deg')})
    guide = payload.get('guide')
    if guide:
        path = folder / 'guide.bvh'
        exports['guide'] = export_clip_bvh(guide['kind'], guide['set'], path)
        if guide['time_s'] > exports['guide']['duration_s']:
            raise ValueError('guide time outside clip')
        files['input_guide_bvh'] = str(path)
        guide = dict(time_s=guide['time_s'], rig='mixamo', num_poses=4,
                     hips_constrained=False, early_frames=10, **_placement(guide))
    spec = {'start': {'time_s': payload['start_time_s'], 'rig': 'mixamo'}, 'target': target,
            'guide': guide, 'variants': variant_params(payload['start_time_s'], payload['variants'], duration, loop)}
    return files, exports, spec


def _handle(payload):
    tid = payload['_task_id']
    tq = get_task_queue()
    progress = tq.get_task_progress(tid)
    op = hub_ops.find_open(TASK_TYPE, lambda inputs: inputs.get('task_id') == tid)
    if progress.get('state') in ('awaiting_choice', 'published', 'discarded', 'expired'):
        if op:
            hub_ops.delete(op)
        return progress
    route = None
    if op is None:
        if progress:
            raise RuntimeError('interrupted before hub job was recorded')
        folder = _staging(tid)
        folder.mkdir(parents=True, exist_ok=True)
        with keyed_lock('clip_library', 'write'):
            files, exports, spec = _prepare(payload, folder)
        route = get_image_service().resolve_transition_backend(payload['backend'])
        meta = route.backend.motion_meta
        op = hub_ops.create(TASK_TYPE, f'{TASK_TYPE}:{tid}',
            {'task_id': tid, 'request': payload, 'files': files, 'exports': exports,
             'spec': spec, 'meta': meta}, label=f'Transition: {payload["start_pose"]} to {payload["target_pose"]}')
    if op.status == hub_ops.FAILED:
        hub_ops.raise_failed(op)
    return hub_ops.execute(op, lambda: _build(tid, op, progress, route))


def _build(tid, op, progress, route):
    tq, inputs = get_task_queue(), op.inputs
    request, spec = inputs['request'], inputs['spec']
    def cancelled():
        if tq.is_task_cancelled(tid):
            raise RuntimeError('cancelled')
    def update(**fields):
        progress.update(**fields)
        tq.update_task_progress(tid, progress)
    stage = op.stage('transition')
    if route is None and not (stage.job.get('job_id') or stage.job.get('collected')):
        route = get_image_service().resolve_transition_backend(request['backend'])
    cancelled()
    result = get_image_service().generate_motion_transition(
        {k: Path(v).read_bytes() for k, v in inputs['files'].items()}, json.dumps(spec), route=route,
        should_cancel=lambda: tq.is_task_cancelled(tid), hub_stage=stage,
        on_job_id=lambda jid, backend: update(phase='hub', hub_job=jid, backend=backend),
        label=f'Transition: {request["start_pose"]} to {request["target_pose"]}')
    cancelled()
    folder = _staging(tid)
    kind = suggested_kind(request['start_pose'], request['target_pose'])
    source = {'generator': 'motionbricks', **{k: request[k] for k in (
        'start_pose', 'target_pose', 'cset', 'target_time_s', 'forward_m', 'left_m', 'yaw_deg', 'guide')},
        'set': request['cset'], 'start_kind': inputs['exports']['start']['kind'], 'target_kind': inputs['exports']['target']['kind'],
        'hub_job': result.get('job_id', ''), 'backend': result.get('backend', request['backend']),
        'model_revision': inputs['meta']['model_revision']}
    candidates = []
    for index, params in enumerate(spec['variants']):
        cancelled()
        variant = (result.get('variants') or [])[index:index+1]
        variant = variant[0] if variant else {'error': 'missing variant'}
        candidate = dict(index=index, ok=False, error=variant.get('error', ''), metrics={},
                         warnings=[], params=params, fbx='', sidecar='')
        candidates.append(candidate)
        if candidate['error']:
            continue
        try:
            directory = folder / f'cand_{index}'
            directory.mkdir(parents=True, exist_ok=True)
            src = directory / 'result.bvh'
            raw = variant['bvh']
            src.write_bytes(raw if isinstance(raw, bytes) else raw.encode())
            report = variant['report']
            report_metrics = report.get('metrics', report)
            candidate['metrics'] = {k: report_metrics.get(k) for k in (
                'hop_cm', 'flight_cm', 'foot_slide_cm', 'final_root_error_cm', 'final_yaw_error_deg')}
            candidate['warnings'] = report_warnings(report)
            clip = import_source(kind, src, paths.get_rig_file(), out_dir=directory / 'clip',
                                 loop_s=None, root_motion='foot_lock', source_extra=dict(source, params=params))
            meta = clip['meta']
            meta.update(license=inputs['meta']['license'], credit=inputs['meta']['credit'])
            rm = (meta.get('geometry') or {}).get('root_motion') or {}
            candidate['metrics'].update(drift_cm=rm.get('max_drift_cm'), travel_m=rm.get('travel_m'),
                                         turn_deg=rm.get('turn_deg'), duration_s=meta.get('duration_s', report.get('duration_s')))
            if rm.get('max_drift_cm', 0) > 1.5:
                raise ValueError('foot_lock_drift')
            Path(clip['sidecar']).write_text(json.dumps(meta, indent=2), encoding='utf-8')
            candidate.update(ok=True, fbx=str(clip['fbx']), sidecar=str(clip['sidecar']))
        except Exception as exc:
            message = str(exc)
            candidate['error'] = 'foot_lock_drift' if 'foot_lock' in message and ('planted foot' in message or 'drift' in message) else message
    cancelled()
    if not any(c['ok'] for c in candidates):
        raise RuntimeError('no variant passed the check: ' + '; '.join(c['error'] for c in candidates))
    library = 'free' if all(e['library'] == 'free' for e in inputs['exports'].values()) else 'licensed'
    data = {'created_at': utc_now_iso(), 'request': request, 'candidates': candidates,
            'library': library, 'kind': kind, 'affected_rule': affected_rule(request['start_pose'], request['target_pose'])}
    (folder / 'candidates.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    update(phase='choose', state='awaiting_choice', kind=kind, backend=result.get('backend', request['backend']),
           candidates=[_public(c) for c in candidates], affected_rule=data['affected_rule'])
    return {'ok': True, **progress}


def _public(candidate):
    return {k: candidate[k] for k in ('index', 'ok', 'error', 'metrics', 'warnings', 'params')}


def candidate_clip(task_id, index):
    folder = _staging(task_id)
    data = _read_candidates(folder)
    if not data:
        raise ChoiceError(410, 'the candidates are gone')
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(data['candidates']):
        raise ChoiceError(404, 'no such candidate')
    candidate = data['candidates'][index]
    path = Path(candidate.get('fbx') or '').resolve()
    if not candidate['ok'] or folder not in path.parents or not path.is_file():
        raise ChoiceError(410, 'the candidate is unavailable')
    return path


def _state(task_id, progress, **fields):
    progress.update(**fields)
    get_task_queue().update_task_progress(task_id, progress)


def choose(task_id, index, *, kind, expected_old_kind):
    folder = _staging(task_id)
    kind = clips.validate_kind(kind)
    with keyed_lock('pose_transition_choice', task_id), keyed_lock('clip_library', 'write'):
        progress = get_task_queue().get_task_progress(task_id)
        if not progress:
            raise ChoiceError(404, 'unknown job')
        if progress.get('state') == 'expired':
            raise ChoiceError(410, 'the candidates expired')
        if progress.get('state') not in ('awaiting_choice', 'publishing'):
            raise ChoiceError(409, 'the job is not waiting for a choice')
        resuming = progress.get('state') == 'publishing'
        if resuming and (progress.get('chosen') != index or progress.get('kind') != kind):
            raise ChoiceError(409, 'finish the interrupted choice first')
        data = _read_candidates(folder)
        if not data or (not resuming and _age_s(data, folder) >= CANDIDATE_MAX_AGE_DAYS * 86400):
            raise ChoiceError(410, 'the candidates expired')
        request = data['request']
        rule = affected_rule(request['start_pose'], request['target_pose'])
        frozen = progress.get('publication_rule') if resuming else None
        # A stop after saving the rule needs only to finish the local state.
        already_saved = bool(frozen and rule['old_kind'] == kind and
                             all(rule[k] == frozen[k] for k in ('from', 'to', 'store')))
        if not resuming and rule != data['affected_rule']:
            raise ChoiceError(409, 'rule_changed')
        if not already_saved and (rule['old_kind'] != expected_old_kind or
                (resuming and progress.get('expected_old_kind') != expected_old_kind)):
            raise ChoiceError(409, 'rule_changed')
        path = candidate_clip(task_id, index)
        candidate = data['candidates'][index]
        root = clips.library_root(data['library']).resolve()
        destination = (root / request['cset']).resolve()
        if destination != root and root not in destination.parents:
            raise ChoiceError(400, 'invalid set')
        targets = [destination / f'{kind}.{ext}' for ext in ('fbx', 'json')]
        sidecar = Path(candidate['sidecar']).resolve()
        if folder not in sidecar.parents or not sidecar.is_file():
            raise ChoiceError(410, 'the sidecar is gone')
        meta = json.loads(sidecar.read_text())
        meta['kind'] = kind
        meta['redistributable'] = data['library'] == 'free'
        meta.setdefault('source', {})['transition_task_id'] = task_id
        current_rule = clips.resolve_pose_transition(request['start_pose'], request['target_pose']) or {}
        replacement = frozen or {'accel': current_rule.get('accel', 0), 'from': rule['from'], 'to': rule['to'], 'kind': kind,
            'store': 'world' if data['library'] == 'licensed' else rule['store']}
        if not resuming and (any(e['kind'] == kind for e in clips.clip_entries()) or any(t.exists() for t in targets)):
            raise ChoiceError(409, 'kind already exists')
        if resuming:
            # Only this task's reserved destination may be completed.
            if targets[1].exists() and json.loads(targets[1].read_text()).get('source', {}).get('transition_task_id') != task_id:
                raise ChoiceError(409, 'kind already exists')
            if targets[0].exists() and targets[0].read_bytes() != path.read_bytes():
                raise ChoiceError(409, 'kind already exists')
        destination.mkdir(parents=True, exist_ok=True)
        rows = clips.load_transitions()
        new_rows = [r for r in rows if (r['from'], r['to']) != (replacement['from'], replacement['to'])] + [replacement]
        seed = clips.clip_transitions_path()
        seed_before = seed.read_bytes() if seed.exists() else None
        world_before = clips.world_transitions()
        _state(task_id, progress, phase='publishing', state='publishing', chosen=index, kind=kind,
               publication_rule=replacement, expected_old_kind=expected_old_kind)
        try:
            if not already_saved:
                _atomic_bytes(targets[1], json.dumps(meta, indent=2).encode())
                _atomic_bytes(targets[0], path.read_bytes())
                # Scans use filesystem identity; avoid notifying until the rule is saved.
                clips.save_transitions(new_rows)
        except Exception:
            clips._write_world_transitions(world_before)
            if seed_before is None:
                seed.unlink(missing_ok=True)
            else:
                _atomic_bytes(seed, seed_before)
            for target in targets:
                target.unlink(missing_ok=True)
            clips.reload_clip_caches()
            _state(task_id, progress, state='awaiting_choice', phase='choose')
            raise
        clips.reload_clip_caches()
        _state(task_id, progress, state='published', phase='published')
        shutil.rmtree(folder, ignore_errors=True)
        return {'task_id': task_id, 'kind': kind, 'index': index, 'library': data['library'], 'rule': replacement}


def _atomic_bytes(target, content):
    from app.core.http_files import sibling_stage, atomic_replace
    with sibling_stage(target) as stage:
        stage.write_bytes(content)
        atomic_replace(stage, target)


def discard(task_id):
    with keyed_lock('pose_transition_choice', task_id):
        folder = _staging(task_id)
        progress = get_task_queue().get_task_progress(task_id)
        if not progress:
            raise ChoiceError(404, 'unknown job')
        if progress.get('state') != 'awaiting_choice':
            raise ChoiceError(409, 'finish an interrupted choice before discarding')
        shutil.rmtree(folder, ignore_errors=True)
        _state(task_id, progress, state='discarded', phase='discarded')
        return {'task_id': task_id, 'state': 'discarded'}


def dismiss(task_id):
    with keyed_lock('pose_transition_choice', task_id):
        folder = _staging(task_id)
        deleted = get_task_queue().delete_finished_task(task_id)
        if deleted is None:
            raise ChoiceError(404, 'unknown job')
        if not deleted:
            raise ChoiceError(409, 'the job is still running or waiting for a choice')
        shutil.rmtree(folder, ignore_errors=True)
        return {'task_id': task_id, 'dismissed': True}


def recent_jobs(limit=20):
    tasks = get_task_queue().list_recent_tasks(TASK_TYPE, limit=max(limit, 500))
    selected = tasks[:limit] + [t for t in tasks[limit:] if (t.get('progress') or {}).get('state') in ('awaiting_choice', 'publishing')]
    return [{**{k: t.get(k) for k in ('task_id', 'status', 'error', 'created_at', 'completed_at')},
             **(t.get('progress') or {}), 'request': t.get('payload') or {}} for t in selected]


def sweep_candidates(max_age_days=CANDIDATE_MAX_AGE_DAYS):
    count = 0
    root = _staging_root()
    for folder in list(root.iterdir()) if root.is_dir() else []:
        if folder.is_symlink() or not folder.is_dir() or not re.fullmatch(r'task_[0-9a-f]+', folder.name):
            continue
        with keyed_lock('pose_transition_choice', folder.name):
            if _age_s(_read_candidates(folder), folder) < max_age_days * 86400:
                continue
            progress = get_task_queue().get_task_progress(folder.name)
            if progress and progress.get('state') not in ('awaiting_choice', 'published', 'discarded', 'expired'):
                continue
            shutil.rmtree(folder)
            if progress.get('state') in ('awaiting_choice', 'publishing'):
                _state(folder.name, progress, state='expired', phase='expired')
            count += 1
    return count


def register():
    get_task_queue().register_handler(TASK_TYPE, _handle)


def _orphan_resume(op):
    hub_ops.drop(op, 'the pose-transition task is gone')
    return {'ok': False, 'error': 'the pose-transition task is gone'}


hub_ops.register_kind(TASK_TYPE, resume=_orphan_resume, track_type=TASK_TYPE)
