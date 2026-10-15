#!/usr/bin/env python3
"""Generation-time face correction, expectations derived from the brief.

A two-triangle mesh must keep two triangles after baking. Frozen controls are
strength=1, feather=.18, resolution=768, yaw=0; both face/upscale picks are
empty (routing), even with an explicit mesh backend. Off: zero face,
upscale or bake stages and exactly one rig of original bytes. On: one face
and upscale, one rig of baked (not projected) bytes, applied metadata and
original mesh provenance. Failure/no route: one plain rig and failed/skipped
metadata. DB reloads after mesh done, upscale/face submitted, bake done and
rig submitted must submit each job once and publish one final model, even
after option/photo changes. Collected face errors fall back to plain rig;
collected upscale errors use the original photo, preserving live-run policy.
Cancellation, disabled media, lost jobs and standalone face failures stay terminal. Revert submits one plain rig, no mesh,
removes facefix and applied metadata. All storage is temporary.
Usage: ./.venv/bin/python scripts/smoke_face_before_rig.py
"""
import hashlib
import os
import pickle
from collections import Counter
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
from smoke_face_retexture_rollback import fixture, photo


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['STORAGE_DIR'] = str(Path(tmp) / 'world')
        os.environ['INSTANCE_DIR'] = str(Path(tmp) / 'instance')
        paths.init(Path(tmp) / 'world')
        paths.init_instance(Path(tmp) / 'instance')
        from app.core import model3d, db, face_retexture, hub_ops
        from app.imagegen.base import GenerationCancelled, MediaGenerationDisabled, HubJobLost
        from app.models.character import save_character_profile
        db.init_schema()
        root = paths.get_storage_dir() / 'characters' / 'demo' / 'model3d'
        root.mkdir(parents=True)
        refs = root.parent / 'model_refs'
        refs.mkdir()
        sig = '0123456789ab'
        image = refs / f'tpose_{sig}.png'
        image.write_bytes(photo())
        rig_inputs, operations = [], []
        class Service:
            face_calls = 0
            upscale_calls = 0
            mesh_calls = 0
            failure = None
            upscale_failure = None
            face_raw = None
            compare_raw = None
            def generate_mesh(self, **kw):
                self.mesh_calls += 1
                assert kw['backend_glob'] == 'mesh-fixture'
                Path(kw['output_path']).write_bytes(fixture())
                return dict(ok=True, path=kw['output_path'], backend='mesh-fixture', single_view=True,
                            routing={'mesh': True}, format='glb')
            def upscale_image(self, raw, **kw):
                self.upscale_calls += 1
                assert kw['backend_glob'] == ''
                if self.upscale_failure:
                    raise self.upscale_failure
                return dict(bytes=raw, status='applied', backend='up-fixture', **{'in': [16, 16], 'out': [16, 16]})
            def generate_face_retexture(self, source, raw, target, *args, **kw):
                self.face_calls += 1
                assert args[1] == ''
                assert Path(source).read_bytes() == fixture()
                if self.failure:
                    raise self.failure
                out = Path(target) / 'corrected.glb'
                out.write_bytes(self.face_raw if self.face_raw is not None else fixture(corrected=True))
                compare = out.with_suffix('.png')
                compare.write_bytes(self.compare_raw if self.compare_raw is not None else photo())
                return dict(ok=True, path=str(out), compare_path=str(compare), backend='face-fixture')
            def generate_rig(self, **kw):
                raw = Path(kw['mesh_path']).read_bytes()
                rig_inputs.append(raw)
                from app.core.model_validate import parse_glb
                from app.core.rig_contract import BASE_JOINT_NAMES
                from smoke_face_retexture_check import glb
                parsed = parse_glb(raw)
                doc = parsed['gltf']
                doc['nodes'] = [{'name': n} for n in BASE_JOINT_NAMES]
                doc['skins'] = [{'joints': list(range(52))}]
                Path(kw['output_path']).write_bytes(glb(doc, parsed['bin']))
                return dict(ok=True, path=kw['output_path'], rig='mixamo', backend='rig-fixture')
        svc = Service()
        create = hub_ops.create
        def capture(*args, **kw):
            op = create(*args, **kw)
            operations.append(op)
            return op
        with ExitStack() as stack:
            stack.enter_context(patch('app.imagegen.service.get_image_service', return_value=svc))
            stack.enter_context(patch.object(hub_ops, 'create', side_effect=capture))
            stack.enter_context(patch.object(model3d, 'required_rig', return_value='mixamo'))
            stack.enter_context(patch.object(model3d, 'find_ref_image', return_value=image))
            stack.enter_context(patch('app.core.model_refs.enabled_tpose_views', return_value=[]))
            stack.enter_context(patch.object(model3d, '_ref_manifest', return_value={'pieces': {}, 'items': []}))
            for name in ('_auto_retexture', '_auto_normalize', '_attach_measurement', 'request_lod'):
                stack.enter_context(patch.object(model3d, name))
            stack.enter_context(patch.object(model3d, '_auto_extension_rig', return_value={'ok': True}))
            stack.enter_context(patch.object(model3d, '_auto_lod_enabled', return_value=False))
            ready = stack.enter_context(patch.object(face_retexture, 'runnable', return_value={'ok': True, 'problems': []}))
            assert save_character_profile('demo', {})
            assert model3d.get_model3d_options('demo')['face_before_rig'] is False
            from app.routes.characters import _set_character_model3d_options_sync
            from fastapi import HTTPException
            assert _set_character_model3d_options_sync('demo', {'face_before_rig': True})['options']['face_before_rig']
            assert not model3d.get_model3d_options('demo')['auto_generate']
            assert not _set_character_model3d_options_sync('demo', {'face_before_rig': False})['options']['face_before_rig']
            for invalid in (None, 'false', 1, []):
                try:
                    _set_character_model3d_options_sync('demo', {'face_before_rig': invalid})
                except HTTPException as exc:
                    assert exc.status_code == 400
                else:
                    raise AssertionError('Option must accept booleans only')
            def run(enabled, failure=None, routable=True):
                svc.failure = failure
                ready.return_value = {'ok': routable, 'problems': [] if routable else [{'message': 'No face backend'}]}
                model3d.set_model3d_options('demo', {'face_before_rig': enabled})
                before = len(rig_inputs)
                result = model3d.generate_for_current_outfit('demo', signature=sig, force=True, backend_glob='mesh-fixture')
                assert result['ok'], result
                assert len(rig_inputs) == before + 1
                return model3d._read_sidecar(root / f'{sig}.glb')
            meta = run(False)
            assert rig_inputs[-1] == fixture() and svc.face_calls == svc.upscale_calls == 0
            assert not any(operations[-1].done(s) for s in ('upscale', 'face', 'bake'))
            meta = run(True)
            assert svc.face_calls == svc.upscale_calls == 1
            assert operations[-1].inputs['controls'] == {'strength': 1, 'feather': .18, 'render_resolution': 768, 'yaw': 0}
            assert operations[-1].inputs['upscale'] is True
            assert (root / 'facefix' / f'{sig}.png').read_bytes() == photo()
            baked = (root / 'facefix' / f'{sig}.glb').read_bytes()
            assert rig_inputs[-1] == baked and baked != fixture(corrected=True) and baked != fixture()
            assert meta['face_retexture']['status'] == 'applied'
            assert meta['face_retexture']['upscale']['backend'] == 'up-fixture'
            assert not meta['face_retexture']['face_texture_lost']
            assert meta['mesh_backend'] == 'mesh-fixture' and meta['single_view']
            assert meta['mesh_route_meta'] == {'routing': {'mesh': True}}
            assert meta['source_image_sha256'] == hashlib.sha256(photo()).hexdigest()
            assert meta['pieces'] == {} and meta['items'] == []
            assert not face_retexture.snapshot_info(root, sig)['ok']
            # The same payload the React revert button consumes advertises rerig.
            with ExitStack() as info_stack:
                info_stack.enter_context(patch.object(model3d, 'current_outfit_state', return_value=({}, {}, sig)))
                info_stack.enter_context(patch.object(model3d, 'list_mesh_backends', return_value={}))
                info_stack.enter_context(patch.object(model3d, 'list_rig_backends', return_value=[]))
                info_stack.enter_context(patch.object(Service, 'list_upscale_backends', return_value=[], create=True))
                info_stack.enter_context(patch.object(Service, 'list_face_retexture_backends', return_value=[], create=True))
                info_stack.enter_context(patch('app.imagegen.routing.explain_occasion', return_value={}))
                info_stack.enter_context(patch.object(model3d, '_finish_model_urls', return_value={}))
                info = model3d.get_model3d_info('demo')
                assert info['rig'] == 'mixamo' and info['options']['face_before_rig']
                assert info['model']['face_retexture_revert'] == 'rerig'
            count = svc.mesh_calls
            assert model3d.revert_face_retexture('demo', sig)['ok']
            assert svc.mesh_calls == count and rig_inputs[-1] == fixture()
            assert not (root / 'facefix' / f'{sig}.glb').exists()
            assert model3d._read_sidecar(root / f'{sig}.glb').get('face_retexture', {}).get('status') != 'applied'
            run(True)
            with patch.object(svc, 'generate_rig', side_effect=SystemExit('revert crash')):
                try:
                    model3d.revert_face_retexture('demo', sig)
                except SystemExit:
                    pass
                else:
                    raise AssertionError('Revert crash not reached')
            assert (root / 'facefix' / f'{sig}.glb').exists()
            revert_op = operations[-1]
            assert hub_ops.resume(revert_op, lambda: model3d._rerig_model(
                'demo', sig, _op_ctx={'op': revert_op}), agent_name='demo')['ok']
            assert rig_inputs[-1] == fixture()
            assert not (root / 'facefix' / f'{sig}.glb').exists()
            assert model3d._read_sidecar(root / f'{sig}.glb').get('face_retexture', {}).get('status') != 'applied'
            meta = run(True, RuntimeError('face fixture failure'))
            assert rig_inputs[-1] == fixture() and meta['face_retexture']['status'] == 'failed'
            assert 'face fixture failure' in meta['face_retexture']['error']
            for failure in (ValueError('bake fixture failure'),):
                with patch.object(face_retexture, 'bake_face_texture', side_effect=failure):
                    meta = run(True)
                    assert rig_inputs[-1] == fixture() and meta['face_retexture']['status'] == 'failed'
            with patch.object(face_retexture, 'MAX_BYTES', 1):
                meta = run(True)
                assert rig_inputs[-1] == fixture() and meta['face_retexture']['status'] == 'failed'
            for attribute in ('face_raw', 'compare_raw'):
                setattr(svc, attribute, b'invalid backend output')
                meta = run(True)
                assert rig_inputs[-1] == fixture() and meta['face_retexture']['status'] == 'failed'
                setattr(svc, attribute, None)
            svc.upscale_failure = RuntimeError('upscale fixture failure')
            meta = run(True)
            assert meta['face_retexture']['status'] == 'applied'
            assert meta['face_retexture']['upscale']['status'] == 'failed'
            svc.upscale_failure = None
            with patch.object(model3d, '_auto_normalize', side_effect=RuntimeError('normalize fixture failure')):
                meta = run(True)
                assert meta['face_retexture']['status'] == 'applied'
                assert meta['normalization_error'] == 'normalize fixture failure'
            meta = run(True, routable=False)
            assert rig_inputs[-1] == fixture() and meta['face_retexture'] == {'status': 'skipped', 'reason': 'No face backend'}
            for exc in (GenerationCancelled('fixture'), MediaGenerationDisabled('fixture'), HubJobLost('fixture')):
                try:
                    run(True, exc)
                except type(exc):
                    pass
                else:
                    raise AssertionError('Terminal exception swallowed')
            # Real persisted job handles: dropping a hub_stage or submitting
            # again after reload must fail the submission-count assertions.
            from app.imagegen.backends._gateway_job import GatewayOutputError
            submissions, attachments = Counter(), Counter()
            jobs = {}
            crash = {'boundary': None, 'error': None}
            class Died(BaseException):
                pass
            class Backend:
                name = 'restart-fixture'
                api_url = 'http://fixture'
                def attach(self, job_id, params, **kw):
                    attachments[params['stage']] += 1
                    if crash['error'] is not None:
                        raise crash['error']
                    return [jobs[job_id]]
            backend = Backend()
            def staged(method):
                def call(*args, **kw):
                    stage = kw['hub_stage']
                    name = stage.name
                    if stage.prepare() == 'attach':
                        return pickle.loads(stage.collect()['blobs'][0])
                    submissions[name] += 1
                    result = method(*args, **kw)
                    job_id = f'{name}-{submissions[name]}'
                    jobs[job_id] = pickle.dumps(result)
                    stage.posting(backend)
                    stage.submitted(backend, job_id, {'stage': name})
                    if crash['boundary'] == (name, 'submitted'):
                        raise Died()
                    return result
                return call
            complete = hub_ops.Op.complete
            def complete_then_die(op, name, *args, **kw):
                result = complete(op, name, *args, **kw)
                if crash['boundary'] == (name, 'done'):
                    raise Died()
                return result
            boundaries = [('mesh', 'done'), ('upscale', 'submitted'),
                          ('face', 'submitted'), ('bake', 'done'), ('rig', 'submitted')]
            # Recoverable collection errors must reach the pipeline; terminal
            # errors and standalone face operations must still fail the op.
            cases = [(boundary, None) for boundary in boundaries]
            cases += [((stage, 'submitted'), GatewayOutputError('bad MIME/checksum'))
                      for stage in ('face', 'upscale')]
            svc.failure = None
            ready.return_value = {'ok': True, 'problems': []}
            with ExitStack() as restart_stack:
                for method in ('generate_mesh', 'upscale_image', 'generate_face_retexture', 'generate_rig'):
                    restart_stack.enter_context(patch.object(svc, method, staged(getattr(svc, method))))
                restart_stack.enter_context(patch.object(hub_ops.Op, 'complete', complete_then_die))
                restart_stack.enter_context(patch.object(hub_ops, 'find_backend', return_value=backend))
                restart_stack.enter_context(patch.object(hub_ops, 'current_owner', return_value='restart-task'))
                from app.core.task_queue import get_task_queue
                restart_stack.enter_context(patch.object(get_task_queue(), 'task_status', return_value='pending'))
                for boundary, error in cases:
                    submissions.clear()
                    attachments.clear()
                    model3d.set_model3d_options('demo', {'face_before_rig': True})
                    crash.update(boundary=boundary, error=None)
                    with patch.object(model3d, '_publish_signature', wraps=model3d._publish_signature) as publish:
                        try:
                            model3d.generate_for_current_outfit('demo', signature=sig, force=True,
                                                              backend_glob='mesh-fixture')
                        except Died:
                            pass
                        else:
                            raise AssertionError(f'Crash not reached: {boundary}')
                        op_id = operations[-1].op_id
                        # No in-memory Op survives the simulated process death.
                        op = hub_ops.get(op_id)
                        assert op is not operations[-1]
                        crash.update(boundary=None, error=error)
                        model3d.set_model3d_options('demo', {'face_before_rig': False})
                        image.write_bytes(b'changed after crash')
                        with patch.object(hub_ops, '_PROCESS_ID', 'restarted-process'):
                            hub_ops._collect_ahead(op)
                            crash['error'] = None
                            # A second startup must neither re-collect a failed
                            # optional job nor forget its durable verdict.
                            hub_ops._collect_ahead(hub_ops.get(op_id))
                            # Public task entry finds the DB record and uses
                            # _resume_entry, including its failed-record check.
                            result = model3d.generate_for_current_outfit('demo', signature=sig, force=True)
                        image.write_bytes(photo())
                        assert result['ok'], result
                        assert sum(not call.kwargs.get('retain_stage') for call in publish.call_args_list) == 1
                    assert hub_ops.get(op_id) is None
                    assert submissions == {'mesh': 1, 'upscale': 1, 'face': 1, 'rig': 1}, submissions
                    if boundary[1] == 'submitted':
                        assert attachments[boundary[0]] == 1, attachments
                    meta = model3d._read_sidecar(root / f'{sig}.glb')
                    if error is not None and boundary[0] == 'face':
                        assert rig_inputs[-1] == fixture()
                        assert meta['face_retexture']['status'] == 'failed'
                        assert 'bad MIME/checksum' in meta['face_retexture']['error']
                    else:
                        assert meta['face_retexture']['status'] == 'applied'
                        assert rig_inputs[-1] == (root / 'facefix' / f'{sig}.glb').read_bytes()
                        if error is not None:
                            assert meta['face_retexture']['upscale']['status'] == 'failed'
                for kind, enabled, stage_name, error in (
                        ('character_mesh', True, 'face', GenerationCancelled('cancelled')),
                        ('character_mesh', True, 'upscale', MediaGenerationDisabled('disabled')),
                        ('character_mesh', True, 'face', HubJobLost('lost')),
                        ('character_mesh', False, 'face', GatewayOutputError('required')),
                        ('face_retexture', True, 'face', GatewayOutputError('standalone'))):
                    op = hub_ops.create(kind, 'terminal-fixture', {'face_before_rig': enabled})
                    stage = op.stage(stage_name)
                    stage.prepare()
                    stage.posting(backend)
                    stage.submitted(backend, 'terminal-job', {'stage': stage_name})
                    crash['error'] = error
                    hub_ops._collect_ahead(hub_ops.get(op.op_id))
                    fresh = hub_ops.get(op.op_id)
                    assert fresh.status == hub_ops.FAILED
                    assert not fresh.jobs()[stage_name].get('collection_error')
                    try:
                        model3d._resume_entry(fresh, lambda: (_ for _ in ()).throw(
                            AssertionError('Terminal operation resumed')), 'demo')
                    except (RuntimeError, HubJobLost):
                        pass
                    else:
                        raise AssertionError('Terminal verdict was swallowed')
                    hub_ops.delete(fresh)
                crash['error'] = None
            image.write_bytes(photo())
            model3d.set_model3d_options('demo', {'face_before_rig': True})
            ready.reset_mock()
            with patch.object(model3d, 'required_rig', return_value='generic'), patch.object(
                    svc, 'generate_mesh', side_effect=SystemExit('stop after op creation')):
                try:
                    model3d.generate_for_current_outfit('demo', signature=sig, force=True, backend_glob='mesh-fixture')
                except SystemExit:
                    pass
                else:
                    raise AssertionError('Non-humanoid op not created')
            ready.assert_not_called()
            assert not operations[-1].inputs['face_before_rig']
            assert not operations[-1].abs('inputs/photo.png').exists()
            hub_ops.delete(operations[-1])
    print('PASS: face-before-rig off/on, baked rig once, provenance, failure, skipped, terminal errors, five persisted restart boundaries, collection fallbacks, unrigged revert (including restart), validation, non-humanoid gating')


if __name__ == '__main__':
    main()
