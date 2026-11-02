#!/usr/bin/env python3
"""Task 12 contract checks with disposable storage.

A four-second loop at 1 s with half-second spacing gives 1, 1.5, 2.
A seat constrains hips and uses one pose. Hop 2.5 exceeds 2; 1.9 does not.
Flight 5 with hop .3 is seated foot elevation, not a hop. Missing hop is safe.
Hub kind/mime are deliberately misleading: extensions and order pair results.
Every file hash and content must pass; a bad pair must preserve later indices.
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


def main():
    with tempfile.TemporaryDirectory() as tmp:
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(Path(tmp) / 'instance')
        for key in ('ANIMATION_CLIPS_DIR', 'ANIMATION_CLIPS_LICENSED_DIR',
                    'ANIMATION_CLIPS_INBOX_DIR', 'ANIMATION_RIG_FILE', 'ANIMATION_PUPPET_FILE'):
            os.environ[key] = str(Path(tmp) / key)
        from app.core import pose_transition as pt
        assert pt.variant_params(1, 3, 4, True) == [
            {'start_time_s': t, 'max_tokens': 16} for t in (1, 1.5, 2)]
        assert pt.variant_params(3.8, 3, 4, True)[1]['start_time_s'] == .3 or abs(pt.variant_params(3.8, 3, 4, True)[1]['start_time_s'] - .3) < 1e-9
        for report, expected in (({'hop_cm': 2.5}, ['hop']), ({'hop_cm': 1.9}, []),
                                 ({'flight_cm': 5, 'hop_cm': .3}, []), ({'flight_cm': 5}, [])):
            assert pt.report_warnings(report) == expected
        # Raw slide (16.47 / 9.95 cm on the first hub job) is pre-foot_lock: no warning.
        assert pt.report_warnings({'foot_slide_cm': {'left': 16.47, 'right': 9.95},
            'final_root_error_cm': [0, 5.1], 'final_yaw_error_deg': [0, -5.1]}) == ['root_error', 'yaw_error']
        print('PASS [params] [warnings]')
        from app.imagegen.backends.openai_motion_transition import OpenAIMotionTransitionBackend
        backend = OpenAIMotionTransitionBackend('fixture', 'http://fixture', 0, 'TASK12_')
        blobs = [b'HIERARCHY fixture', b'{"hop_cm":0.3}', b'HIERARCHY second', b'{}']
        results = [{'n': i, 'name': f'transition_{i//2}.' + ('json' if i % 2 else 'bvh'),
                    'sha256': hashlib.sha256(b).hexdigest(), 'kind': 'image',
                    'mime': 'application/octet-stream'} for i, b in enumerate(blobs)]
        def get(url, **kw):
            return SimpleNamespace(status_code=200, content=blobs[int(url.rsplit('/', 1)[1])])
        with patch('app.imagegen.backends.openai_motion_transition.requests.get', side_effect=get):
            pairs = backend._download({'results': results}, 'job', 2)
            assert len(pairs) == 2 and all(p['ok'] for p in backend.last_result_meta)
            assert json.loads(pairs[0])['report']['hop_cm'] == .3
            results[0]['sha256'] = '0' * 64
            pairs = backend._download({'results': results}, 'job', 2)
            assert 'sha256' in json.loads(pairs[0])['error'] and 'bvh' in json.loads(pairs[1])
        spec = {'variants': [{'start_time_s': 1, 'max_tokens': 16}], 'guide': None}
        with patch('app.imagegen.backends.openai_motion_transition.submit_job', return_value='job') as submit, \
             patch.object(backend, '_collect', return_value=[]):
            backend.generate_transition({'input_start_bvh_path': b'HIERARCHY start',
                                         'input_target_bvh_path': b'HIERARCHY target'}, json.dumps(spec))
            payload = submit.call_args.args[2]
            assert payload['prompt'] == 'transition' and set(payload['params']) == {'input_params'}
            assert all(v.startswith('data:text/plain;base64,') for v in payload['files'].values())
            assert 'seed' not in payload['params']
        print('PASS [hub-pairs] hashes, names, content and stable variant indices')
        from app.core.db import init_schema
        init_schema()
        lifecycle(pt, Path(tmp))
        service_checks()
        print('PASS: pose transition checks')


def lifecycle(pt, root):
    from app.core import pose_catalog as pc, animation_clips as clips
    from app.core import hub_ops
    catalog = root / 'catalog.json'
    catalog.write_text(json.dumps({'groups': {'stand': {'default': 'standing', 'needs_place': False},
        'seat': {'default': 'sitting', 'needs_place': True}}, 'entries': {
        'standing': {'solo': True, 'group': 'stand', 'animation': 'idle', 'prompt': 'standing'},
        'sitting': {'solo': True, 'group': 'seat', 'animation': 'sit', 'prompt': 'sitting'}}}))
    free, licensed = clips.library_root('free'), clips.library_root('licensed')
    free.mkdir(parents=True)
    licensed.mkdir(parents=True)
    for kind in ('idle', 'sit', 'get-up-chair'):
        (free / (kind + '.fbx')).write_bytes(b'fixture')
        (free / (kind + '.json')).write_text(json.dumps({'kind': kind, 'duration_s': 4,
            'loop': True, 'geometry': {'loop': {'seam_distance': 0}}}))
    transitions = root / 'transitions.json'
    transitions.write_text(json.dumps([{'from': '@seat', 'to': '*', 'kind': 'get-up-chair'}]))
    tq = pt.get_task_queue()
    backend = SimpleNamespace(name='fixture', max_variants=4,
        motion_meta={'license': 'Fixture licence', 'credit': 'Fixture', 'model_revision': 'v1'})
    service = SimpleNamespace(resolve_transition_backend=lambda name='': SimpleNamespace(backend=backend))
    from smoke_bvh_soma_import import write_fixture
    fixture_path = root / 'generated-soma.bvh'
    write_fixture(fixture_path)
    fixture_bvh = fixture_path.read_text()
    exported = []
    def export(kind, cset, path):
        exported.append((kind, cset))
        path.write_bytes(b'HIERARCHY fixture')
        library = 'licensed' if (licensed / (kind + '.fbx')).exists() else 'free'
        return {'library': library, 'duration_s': 4}
    def imported(kind, src, rest, *, out_dir, **kw):
        assert kw['root_motion'] == 'foot_lock' and kw['loop_s'] is None
        if src.parent.name == 'cand_1':
            raise ValueError('foot_lock left a planted foot moving 1.60 cm')
        out_dir.mkdir(parents=True)
        fbx, sidecar = out_dir / (kind + '.fbx'), out_dir / (kind + '.json')
        fbx.write_bytes(src.read_bytes())
        meta = {'kind': kind, 'duration_s': 1.9, 'source': kw['source_extra'],
                'geometry': {'root_motion': {'max_drift_cm': .7, 'travel_m': [0, -.25], 'turn_deg': 0}}}
        sidecar.write_text(json.dumps(meta))
        return {'fbx': fbx, 'sidecar': sidecar, 'meta': meta}
    count = {'fresh': 0, 'attach': 0}
    def generate(files, params_json, **kw):
        spec = json.loads(params_json)
        assert set(files) == {'input_start_bvh_path', 'input_target_bvh_path'} | ({'input_guide_bvh_path'} if spec['guide'] else set())
        if spec['guide']:
            assert spec['guide']['num_poses'] == 4 and spec['guide']['early_frames'] == 10
            assert spec['guide']['hips_constrained'] is False
        assert spec['target']['hips_constrained'] is True and spec['target']['num_poses'] == 1
        assert [v['start_time_s'] for v in spec['variants']] == [1, 1.5, 2]
        stage = kw['hub_stage']
        if stage.job.get('job_id'):
            count['attach'] += 1
            assert kw['route'] is None
        else:
            count['fresh'] += 1
        kw['on_job_id']('fixture-job', 'fixture')
        return {'backend': 'fixture', 'job_id': 'fixture-job', 'variants': [
            {'bvh': fixture_bvh, 'report': {'metrics': {'hop_cm': .3, 'flight_cm': 5},
             'duration_s': 1.9}} for _ in spec['variants']]}
    service.generate_motion_transition = generate
    request = dict(start_pose='walking', target_pose='sitting', cset='female',
        start_time_s=1, target_time_s=0, forward_m=-.25, left_m=0, yaw_deg=0)
    def job():
        with patch.object(tq, 'start'):
            tid = pt.submit(**request)['task_id']
        pt._handle(dict(request, variants=3, backend='fixture', guide=request.get('guide'), _task_id=tid))
        return tid
    original = pc.catalog_path
    with patch.object(pc, 'catalog_path', side_effect=lambda axis: catalog if axis == 'pose' else original(axis)), \
         patch.object(clips, 'clip_transitions_path', return_value=transitions), \
         patch.object(pt, 'get_image_service', return_value=service), \
         patch.object(pt, 'export_clip_bvh', side_effect=export), \
         patch.object(pt, 'import_source', side_effect=imported):
        pc.reload_catalogs()
        clips.reload_clip_caches()
        assert pt.pose_clip('sitting', 'female') == ('sit', '')
        assert pt.affected_rule('sitting', 'walking') == {
            'from': '@seat', 'to': '*', 'store': 'shared', 'old_kind': 'get-up-chair'}
        print('PASS [affected] [set-fallback]')
        tid = job()
        progress = tq.get_task_progress(tid)
        assert progress['state'] == 'awaiting_choice'
        assert [c['ok'] for c in progress['candidates']] == [True, False, True]
        assert progress['candidates'][1]['error'] == 'foot_lock_drift'
        assert progress['candidates'][0]['metrics']['hop_cm'] == .3
        assert progress['candidates'][0]['metrics']['travel_m'] == [0, -.25]
        assert exported[:2] == [('idle', ''), ('sit', '')]
        print('PASS [one-failed]')
        before = transitions.read_bytes()
        try:
            pt.choose(tid, 0, kind='mb-free', expected_old_kind='stale')
        except pt.ChoiceError as exc:
            assert exc.status == 409 and str(exc) == 'rule_changed'
        else:
            raise AssertionError('stale rule accepted')
        assert transitions.read_bytes() == before and not (free / 'female/mb-free.fbx').exists()
        print('PASS [stale-rule]')
        result = pt.choose(tid, 0, kind='mb-free', expected_old_kind=None)
        assert result['library'] == 'free' and (free / 'female/mb-free.fbx').is_file()
        assert any(r['kind'] == 'mb-free' and r['store'] == 'shared' for r in clips.load_transitions())
        assert json.loads((free / 'female/mb-free.json').read_text())['source']['params']['max_tokens'] == 16
        print('PASS [publish-free] into female/')
        tid_recover = job()
        rows_before = clips.load_transitions()
        with patch.object(clips, '_write_transitions', side_effect=RuntimeError('disk fixture')):
            try:
                pt.choose(tid_recover, 0, kind='mb-recover', expected_old_kind='mb-free')
            except RuntimeError as exc:
                assert str(exc) == 'disk fixture'
            else:
                raise AssertionError('failed rule write accepted')
        assert clips.load_transitions() == rows_before
        assert not (free / 'female/mb-recover.fbx').exists()
        class Stopped(BaseException):
            pass
        original_state = pt._state
        def state(task_id, progress, **fields):
            if fields.get('state') == 'published':
                raise Stopped()
            return original_state(task_id, progress, **fields)
        with patch.object(pt, '_state', side_effect=state):
            try:
                pt.choose(tid_recover, 0, kind='mb-recover', expected_old_kind='mb-free')
            except Stopped:
                pass
            else:
                raise AssertionError('stop fixture did not stop')
        recovery_folder = pt._staging(tid_recover)
        recovery_file = recovery_folder / 'candidates.json'
        recovery_data = json.loads(recovery_file.read_text())
        recovery_data['created_at'] = '2000-01-01T00:00:00+00:00'
        recovery_file.write_text(json.dumps(recovery_data))
        try:
            pt.discard(tid_recover)
        except pt.ChoiceError as exc:
            assert exc.status == 409
        else:
            raise AssertionError('interrupted publication discarded')
        assert pt.sweep_candidates() == 0 and recovery_folder.exists()
        pt.choose(tid_recover, 0, kind='mb-recover', expected_old_kind='mb-free')
        assert tq.get_task_progress(tid_recover)['state'] == 'published'
        print('PASS [rollback] [interrupted-choice] preserved and completed after seven days')
        (licensed / 'get-up-chair.fbx').write_bytes(b'licensed guide')
        clips.reload_clip_caches()
        request['guide'] = {'kind': 'get-up-chair', 'set': '', 'time_s': .5,
                            'forward_m': -.1, 'left_m': 0, 'yaw_deg': 0}
        guide_tid = job()
        pt.choose(guide_tid, 0, kind='mb-guide', expected_old_kind='mb-recover')
        assert (licensed / 'female/mb-guide.fbx').exists()
        assert pt.affected_rule('walking', 'sitting')['store'] == 'world'
        request.pop('guide')
        print('PASS [guide-licensed] licensed guide forces licensed library and world rule')
        (licensed / 'idle.fbx').write_bytes(b'licensed')
        clips.reload_clip_caches()
        tid2 = job()
        pt.choose(tid2, 2, kind='mb-licensed', expected_old_kind='mb-guide')
        assert (licensed / 'female/mb-licensed.fbx').is_file()
        assert pt.affected_rule('walking', 'sitting')['store'] == 'world'
        print('PASS [publish-licensed]')
        # Create the record before invoking the handler, as a stopped process does.
        with patch.object(tq, 'start'):
            tid3 = pt.submit(**request)['task_id']
        folder = pt._staging(tid3)
        folder.mkdir(parents=True)
        files, exports, spec = pt._prepare(dict(request, variants=3, guide=None), folder)
        with patch.object(hub_ops, 'current_owner', return_value=tid3):
            op = hub_ops.create(pt.TASK_TYPE, 'resume-fixture', {'task_id': tid3,
            'request': dict(request, backend='fixture', guide=None), 'files': files, 'exports': exports,
            'spec': spec, 'meta': backend.motion_meta})
        op.stage('transition')._set_job(lambda j: j.update(job_id='already-submitted'))
        fresh = count['fresh']
        pt.register()
        with patch.object(hub_ops, 'current_owner', return_value=tid3):
            pt._handle({'_task_id': tid3})
        assert count['attach'] == 1 and count['fresh'] == fresh
        print('PASS [resume] collected without submission')
        data_path = folder / 'candidates.json'
        data = json.loads(data_path.read_text())
        data['created_at'] = '2000-01-01T00:00:00+00:00'
        data_path.write_text(json.dumps(data))
        assert pt.sweep_candidates() == 1 and not folder.exists()
        assert tq.get_task_progress(tid3)['state'] == 'expired'
        print('PASS [sweep]')


def service_checks():
    from app.imagegen.service import ImageService
    from app.imagegen.base import GenerationCancelled
    from app.imagegen import routing, occasions
    service = ImageService.__new__(ImageService)
    backend = SimpleNamespace(name='fixture', last_job_id='job')
    calls = []
    backend.generate = lambda *a, **kw: [json.dumps({'bvh': 'HIERARCHY fixture', 'report': {}}).encode()]
    service.run_on_backend = lambda b, fn: (fn(b), b)
    def channel(b, fn, **kwargs):
        calls.append(kwargs['task_type'])
        return fn()
    service.run_on_backend_channel = channel
    result = service.generate_motion_transition({}, '{}', route=SimpleNamespace(backend=backend))
    assert calls == ['pose_transition'] and result['variants'][0]['bvh'].startswith(b'HIERARCHY')
    stage = SimpleNamespace(prepare=lambda: 'attach', collected=lambda: {
        'blobs': [json.dumps({'bvh': 'HIERARCHY resumed', 'report': {}}).encode()],
        'backend': 'original', 'job_id': 'saved-job'})
    service.run_on_backend = lambda *a: (_ for _ in ()).throw(AssertionError('resume resubmitted'))
    result = service.generate_motion_transition({}, '{}', route=None, hub_stage=stage)
    assert result['backend'] == 'original' and result['job_id'] == 'saved-job'
    assert calls == ['pose_transition']
    assert occasions.requires_chain('pose_transition')
    assert occasions.backend_fits('pose_transition', {'media': 'animation', 'category': 'motion2transition'})
    assert not occasions.backend_fits('pose_transition', {'media': 'animation', 'category': 'mesh2anim'})
    from app.routes.poses import router
    from app.core.auth_dependency import require_admin
    routes = [r for r in router.routes if r.path.startswith('/poses/transition-jobs')]
    assert len(routes) == 8
    assert all(any(d.call is require_admin for d in r.dependant.dependencies) for r in routes)
    from app.core.periodic_jobs import _SUB_TASKS
    assert any(fn.__name__ == '_sub_pose_transition_candidates' and interval == 86400
               for fn, interval, name in _SUB_TASKS if name == 'pose_transition_candidates')
    print('PASS [admin] eight routes require_admin; daily sweep registered')
    print('PASS [service] channel, byte BVHs, resume without channel, occasion isolation')


if __name__ == '__main__':
    main()
