#!/usr/bin/env python3
"""P1 gateway payload and credentials, expectations derived by hand.

The hub contract declares one GLB file and one RGB PNG image: both must be
Data-URIs in the same request. Only four schema-declared controls are sent;
authenticated schema failure disables the backend. Input hashes reported in
separate image/file lists are united. Zero/two GLBs fail selection; one GLB
plus a PNG passes. Category isolation excludes projection from mesh/shrink.
A foreign result origin, including redirects, receives zero authenticated
requests. cancelled/410/three 404s are terminal without cooldown or fallback.
Usage: ./.venv/bin/python scripts/smoke_face_retexture_payload.py
"""
import hashlib
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths


def main():
    with tempfile.TemporaryDirectory() as tmp:
        paths.init(tmp)
        from app.imagegen.backends.openai_mesh import OpenAIMeshBackend
        from app.imagegen.backends import _gateway_job
        from app.imagegen.base import GatewayRejectedError, GenerationCancelled
        from app.imagegen.service import ImageService
        from smoke_face_retexture_check import glb, photo
        backend = OpenAIMeshBackend('face', 'https://gateway.invalid', 1, 'FACE_SMOKE_', api_key='fake-key', model='face-alias')
        backend.category = 'face_retexture'
        source = Path(tmp) / 'original.glb'
        source.write_bytes(glb())
        image = photo()
        schema = {'files': [{'name': 'input_mesh_path'}], 'images': [{'name': 'reference_image'}],
                  'params': [{'name': k} for k in ('strength', 'feather', 'render_resolution', 'yaw')]}
        def response(status=200, data=None, headers=None):
            return SimpleNamespace(status_code=status, content=b'present', json=lambda: data or {}, headers=headers or {})
        with patch('app.imagegen.backends.openai_mesh.requests.get', side_effect=[response(), response(403)]):
            assert not backend.check_availability()
        with patch('app.imagegen.backends.openai_mesh.requests.get', side_effect=[response(), response(data=schema)]):
            assert backend.check_availability()
        with patch('app.imagegen.backends.openai_mesh.requests.get', side_effect=[response(), response(data={'params': schema['params']})]):
            assert not backend.check_availability(), 'schema without upload slots must disable projection'
        with patch('app.imagegen.backends.openai_mesh.requests.get', side_effect=[response(), response(data=schema)]):
            assert backend.check_availability()
        submitted = []
        def submit(b, url, payload, kind):
            submitted.append(payload)
            return 'fake-job'
        with patch('app.imagegen.backends.openai_mesh.submit_job', side_effect=submit), patch('app.imagegen.backends.openai_mesh.poll_job', return_value=[b'result']):
            backend._generate('', '', {'source_model_path': str(source), 'reference_image_bytes': image, 'face_num': 99, 'input_name': 'ignored'})
        # Hand-derived: a pending health check preserves the verified payload.
        import threading
        started, release = threading.Event(), threading.Event()
        def pending_schema(url, **kwargs):
            if url.endswith('/schema'):
                started.set()
                assert release.wait(5)
                return response(data=schema)
            return response()
        with patch('app.imagegen.backends.openai_mesh.requests.get', side_effect=pending_schema), patch('app.imagegen.backends.openai_mesh.submit_job', side_effect=submit), patch('app.imagegen.backends.openai_mesh.poll_job', return_value=[b'result']):
            worker = threading.Thread(target=backend.check_availability)
            worker.start()
            try:
                assert started.wait(5)
                backend._generate('', '', {'source_model_path': str(source), 'reference_image_bytes': image})
                assert list(submitted[-1]['images']) == ['reference_image'] and submitted[-1]['params'] == {'strength': 1, 'feather': 0.18, 'render_resolution': 768, 'yaw': 0}
            finally:
                release.set()
                worker.join(5)
            assert not worker.is_alive()
        # A completed invalidation while reading the GLB must not split slots
        # and controls within a payload already using the verified snapshot.
        remember = backend._remember_input
        def refresh_during_read(raw):
            with patch('app.imagegen.backends.openai_mesh.requests.get', return_value=response(403)):
                backend._fetch_alias_schema()
            return remember(raw)
        with patch.object(backend, '_remember_input', side_effect=refresh_during_read), patch('app.imagegen.backends.openai_mesh.submit_job', side_effect=submit), patch('app.imagegen.backends.openai_mesh.poll_job', return_value=[b'result']):
            backend._generate('', '', {'source_model_path': str(source), 'reference_image_bytes': image})
            assert list(submitted[-1]['files']) == ['input_mesh_path']
            assert list(submitted[-1]['images']) == ['reference_image']
            assert submitted[-1]['params'] == {'strength': 1, 'feather': 0.18, 'render_resolution': 768, 'yaw': 0}
        payload = submitted[0]
        assert payload['files']['input_mesh_path'].startswith('data:model/gltf-binary;base64,')
        assert payload['images']['reference_image'].startswith('data:image/png;base64,')
        assert payload['params'] == {'strength': 1, 'feather': 0.18, 'render_resolution': 768, 'yaw': 0}
        assert backend.last_job_id == 'fake-job'
        backend._check_input_identity({'input_files': [{'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}],
                                       'input_images': [{'sha256': hashlib.sha256(image).hexdigest()}]}, 'fake-job')
        # The live hub (2026-10-13) reports only the reference image with a
        # digest; the mesh upload appears as "<upload:…>" without one. Ours
        # being partly unreported is no mismatch ...
        backend._check_input_identity({'input_images': [{'sha256': hashlib.sha256(image).hexdigest()}]}, 'fake-job')
        # ... but a reported digest that is not ours still fails the job.
        from app.imagegen.base import GatewayInputMismatchError
        try:
            backend._check_input_identity({'input_images': [{'sha256': 'e' * 64}]}, 'fake-job')
        except GatewayInputMismatchError:
            pass
        else:
            raise AssertionError('a foreign reported input hash was accepted')
        backend._face_schema = (True, ('reference_image',), 'input_mesh_path', frozenset({'strength'}))
        assert backend.build_alias_params({'yaw': 20}) == {'strength': 1}
        backend._face_schema = (False, (), '', frozenset())
        assert backend.build_alias_params({}) == {}
        svc = object.__new__(ImageService)
        svc.list_available_backends = lambda **kw: [backend]
        assert svc.list_mesh_backends() == [] and svc.list_shrink_backends() == []
        assert svc.list_face_retexture_backends() == [backend]
        model = {'name': 'corrected.glb', 'mime': 'model/gltf-binary'}
        for files in ([], [model, model]):
            try:
                svc._select_face_retexture_results(files)
            except ValueError:
                pass
            else:
                raise AssertionError('ambiguous GLB selection accepted')
        assert svc._select_face_retexture_results([model, {'mime': 'image/png'}])[0] is model
        with patch('app.imagegen.backends.openai_mesh.requests.get') as get:
            try:
                backend._download_same_origin('https://foreign.invalid/result.glb')
            except GatewayRejectedError:
                pass
            else:
                raise AssertionError('foreign origin accepted')
            get.assert_not_called()
        with patch('app.imagegen.backends.openai_mesh.requests.get', return_value=response(302, headers={'Location': 'https://foreign.invalid/file'})) as get:
            try:
                backend._download_same_origin('https://gateway.invalid/result.glb')
            except GatewayRejectedError:
                pass
            else:
                raise AssertionError('foreign redirect accepted')
            assert get.call_count == 1
        for replies in ([response(data={'status': 'cancelled'})], [response(410)], [response(404)] * 3):
            with patch.object(_gateway_job.requests, 'get', side_effect=replies), patch.object(_gateway_job.time, 'sleep'):
                try:
                    _gateway_job.poll_job(backend, 'fake-job', max_wait=1, max_queue_wait=1, poll_interval=0,
                                          on_done=lambda sd, elapsed: [])
                except (GenerationCancelled if replies[0].json().get('status') == 'cancelled' else GatewayRejectedError):
                    pass
                else:
                    raise AssertionError('terminal job was retried')
        # Shared mesh callers keep cancellation terminal: one submission,
        # failed result, no fallback/cooldown, and no output file.
        from app.imagegen.selection import BackendPool
        from app.imagegen import routing
        mesh = OpenAIMeshBackend('mesh-cancel', 'https://gateway.invalid', 1, 'FACE_SMOKE_', model='mesh-alias')
        mesh.category = 'img2mesh'
        mesh._available = True
        fallback = OpenAIMeshBackend('mesh-next', 'https://gateway.invalid', 1, 'FACE_SMOKE_', model='mesh-next')
        fallback.category = 'img2mesh'
        fallback._available = True
        service = object.__new__(ImageService)
        service.enabled = True
        service._pool = BackendPool([mesh, fallback])
        service.run_on_backend_channel = lambda b, fn, **kwargs: fn()
        input_path, output_path = Path(tmp) / 'input.png', Path(tmp) / 'output.glb'
        input_path.write_bytes(image)
        attempts = []
        def mesh_submit(b, url, payload, kind):
            attempts.append(b.name)
            return 'mesh-cancelled-job'
        with patch.object(mesh, 'check_availability', return_value=True), patch.object(routing, '_rules', return_value=['mesh-cancel', 'mesh-next']), patch('app.imagegen.backends.openai_mesh.submit_job', side_effect=mesh_submit), patch.object(_gateway_job.requests, 'get', return_value=response(data={'status': 'cancelled'})):
            mesh.poll_interval = 0
            result = service.generate_mesh(str(input_path), str(output_path))
        assert not result['ok'] and result['error'] == 'mesh-cancelled-job'
        assert attempts == ['mesh-cancel'] and not mesh.in_cooldown()
        assert not output_path.exists()
    print('PASS: face retexture payload, schema gate, identity union, result selection, category isolation, origin and terminal jobs')


if __name__ == '__main__':
    main()
