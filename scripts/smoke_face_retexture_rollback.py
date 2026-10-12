#!/usr/bin/env python3
"""P1 publication and first-snapshot rollback, derived by hand from sections 5–6.

Two source triangles split into two textured primitives preserve the triangle
count. Projection and rig run once each through separate channels; original
mesh provenance stays in the full sidecar. A second run keeps the first
snapshot byte-for-byte. Re-rig retains facefix and snapshot. Revert restores
all original files exactly, except full sidecar's reverted status, and removes
facefix/snapshot. Hub, rig, normalization, publication and stale failures
publish no bytes and no snapshot. Material loss, texture re-encode,
extension and low failures publish the valid rig with visible failure metadata
and retain the rollback snapshot (updated plan section 5.7). A corrupt or
incomplete manifest refuses revert. Source replacement removes both correction
and snapshot; export carries corrected GLB/JSON but excludes diagnostic/snapshot.
After a mesh checkpoint, a failed final publication keeps the new static mesh
and permanently removes the previous rollback snapshot; Revert must refuse.
P2: 16x16 reference -> 32x32 output (scale 2). Upscale off submits original;
failed/busy submits original with a nested warning, without a busy cooldown.
Cancel and media-off propagate and publish nothing. Cache survives face/rig
failure and revert, rerig preserves the nested status, source purge/GC remove
it, and snapshot/export/publication never contain it. Parameter or corrupted
cache changes must cause a backend call. Explicit unavailable picks refuse start.
All fixtures are constructed here; fake backends never use a network or Blender.
Usage: ./.venv/bin/python scripts/smoke_face_retexture_rollback.py
"""
import copy
import hashlib
import json
import os
import struct
import sys
import tempfile
import threading
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
from smoke_face_retexture_check import fixture_doc, glb, photo


def fixture(corrected=False, rigged=False, lost=False):
    doc, binary = fixture_doc()
    binary = struct.pack('<6H', 0, 1, 2, 0, 1, 2) + binary[8:]
    doc['buffers'][0]['byteLength'] = len(binary)
    doc['bufferViews'][0]['byteLength'] = 12
    doc['bufferViews'][1]['byteOffset'] = 12
    doc['bufferViews'][2]['byteOffset'] = 36
    doc['accessors'][0]['count'] = 6
    if corrected and lost is not True:
        doc['accessors'][0]['count'] = 3
        doc['materials'].append(copy.deepcopy(doc['materials'][0]))
        second = copy.deepcopy(doc['meshes'][0]['primitives'][0])
        second['material'] = 1
        doc['meshes'][0]['primitives'].append(second)
    if lost == 'merged' and corrected:
        doc['meshes'][0]['primitives'][1]['material'] = 0
    if rigged:
        from app.core.rig_contract import BASE_JOINT_NAMES
        doc['nodes'] = [{'name': n} for n in BASE_JOINT_NAMES]
        doc['skins'] = [{'joints': list(range(52))}]
    return glb(doc, binary)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['STORAGE_DIR'] = str(Path(tmp) / 'world')
        os.environ['INSTANCE_DIR'] = str(Path(tmp) / 'instance')
        paths.init(os.environ['STORAGE_DIR'])
        paths.init_instance(Path(os.environ['INSTANCE_DIR']))
        from app.core import model3d, face_retexture, db
        from app.core.model_store import export_files
        from app.imagegen import routing
        from app.imagegen.service import ImageService
        from app.imagegen.selection import BackendPool
        from app.imagegen.base import ImageBackend, GatewayRejectedError
        db.init_schema()
        root = Path(os.environ['STORAGE_DIR']) / 'characters' / 'demo' / 'model3d'
        root.mkdir(parents=True)
        refs = root.parent / 'model_refs'
        refs.mkdir()
        sig = '0123456789ab'

        class Fake(ImageBackend):
            MEDIA_TYPE = 'mesh'
            def __init__(self, name, category):
                super().__init__(name, 'https://fake.invalid', 0, 'fake', 'FACE_SMOKE_')
                self.category = category
                self.instance_enabled = True
                self._available = True
                self.calls = []
                self.failure = None
                self.lost = False
                self._tls = threading.local()
                self.model = name
            def check_availability(self):
                return self.available
            @property
            def last_result_files(self):
                return self._tls.files
            @property
            def last_job_id(self):
                return 'fake-face-job'
            @property
            def last_result_rig(self):
                return 'mixamo' if self.category == 'mesh2rig' else 'none'
            def _generate(self, prompt, negative, params):
                self.calls.append(params)
                if self.failure:
                    raise self.failure
                if self.category == 'face_retexture':
                    assert Path(params['source_model_path']).parent.name == 'unrigged'
                    assert Path(params['source_model_path']).read_bytes() == fixture()
                    raw = fixture(corrected=True)
                    self._tls.files = [{'name': 'corrected.glb', 'mime': 'model/gltf-binary', 'kind': 'model',
                                        'sha256': hashlib.sha256(raw).hexdigest(), 'url': 'https://fake.invalid/corrected'},
                                       {'name': 'comparison.png', 'mime': 'image/png', 'kind': 'image'}]
                    return [raw, photo()]
                assert Path(params['source_model_path']).parent.name == 'facefix'
                raw = fixture(corrected=True, rigged=True, lost=self.lost)
                self._tls.files = [{'name': 'rigged.glb', 'mime': 'model/gltf-binary', 'kind': 'model'}]
                return [raw]

        face = Fake('face', 'face_retexture')
        rig = Fake('rigger', 'mesh2rig')
        svc = object.__new__(ImageService)
        svc._pool = BackendPool([face, rig], agent_instances_provider=lambda name: {})
        channels = []
        def channel(backend, fn, **kwargs):
            channels.append(backend.name)
            return fn()
        svc.run_on_backend_channel = channel

        def seed():
            import shutil
            for child in root.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            image = refs / f'tpose_{sig}.png'
            image.write_bytes(photo())
            meta = {'mesh_backend': 'original-mesh', 'mesh_route_meta': {'original': True}, 'job_id': 'original-job',
                    'source_image': image.name, 'source_image_sha256': hashlib.sha256(photo()).hexdigest(),
                    'pieces': {}, 'items': [], 'view_images': {'front': image.name}}
            for folder in ('', 'unrigged', 'raw', 'prerig', 'low', 'low/raw', 'low/prerig'):
                directory = root / folder
                directory.mkdir(parents=True, exist_ok=True)
                (directory / f'{sig}.glb').write_bytes(fixture() if folder == 'unrigged' else fixture(rigged=True))
                (directory / f'{sig}.json').write_text(json.dumps({**meta, 'rig': 'mixamo', 'lod_ratio': 0.4}))
            face.failure = rig.failure = None
            rig.lost = False
            face._available = rig._available = True
            face._cooldown_until = rig._cooldown_until = 0

        def files():
            return {r: p.read_bytes() for r, p in model3d._signature_files(root, sig).items()}
        def low(name, signature=None, ratio=0.25):
            assert ratio == 0.4
            (model3d.get_model3d_dir(name) / 'low').mkdir(exist_ok=True)
            (model3d.get_model3d_dir(name) / 'low' / f'{sig}.glb').write_bytes(fixture(corrected=True, rigged=True))
            return {'ok': True}

        real_build_lod = model3d.build_lod
        with ExitStack() as stack:
            stack.enter_context(patch('app.imagegen.service.get_image_service', return_value=svc))
            stack.enter_context(patch.object(routing, '_rules', side_effect=lambda occasion: ['rigger'] if occasion == 'rig_humanoid' else []))
            stack.enter_context(patch.object(model3d, 'required_rig', return_value='mixamo'))
            stack.enter_context(patch.object(model3d, '_auto_retexture'))
            stack.enter_context(patch.object(model3d, '_auto_normalize'))
            stack.enter_context(patch.object(model3d, '_auto_extension_rig', return_value={'ok': True}))
            stack.enter_context(patch.object(model3d, '_attach_measurement'))
            stack.enter_context(patch.object(model3d, 'build_lod', side_effect=low))
            stack.enter_context(patch.object(model3d, 'request_lod'))
            seed()
            before = files()
            result = model3d.face_retexture_model('demo', sig)
            assert result['ok'], result
            assert channels == ['face', 'rigger'], channels
            snap = root / 'rollback' / sig
            manifest = (snap / 'manifest.json').read_bytes()
            assert face_retexture.snapshot_info(root, sig)['ok']
            meta = model3d._read_sidecar(root / f'{sig}.glb')
            assert meta['mesh_backend'] == 'original-mesh' and meta['job_id'] == 'original-job'
            assert meta['face_retexture']['job_id'] == 'fake-face-job' and meta['face_retexture']['status'] == 'applied'
            exported = [p.relative_to(root).as_posix() for p in export_files(root, [sig])]
            assert f'facefix/{sig}.glb' in exported and f'facefix/{sig}.json' in exported
            assert f'facefix/{sig}.png' not in exported and not any(p.startswith('rollback/') for p in exported)
            assert model3d.face_retexture_model('demo', sig)['ok']
            assert (snap / 'manifest.json').read_bytes() == manifest
            assert model3d.rerig_model('demo', sig)['ok']
            assert (root / 'facefix' / f'{sig}.glb').is_file() and (snap / 'manifest.json').read_bytes() == manifest
            assert model3d._read_sidecar(root / f'{sig}.glb')['face_retexture']['status'] == 'applied'
            assert model3d.revert_face_retexture('demo', sig)['ok']
            after = files()
            for path, raw in before.items():
                if path == Path(f'{sig}.json'):
                    restored = json.loads(after[path])
                    assert restored.pop('face_retexture')['status'] == 'reverted'
                    assert restored == json.loads(raw)
                else:
                    assert after[path] == raw, path
            assert set(after) == set(before)
            assert not snap.exists() and not (root / 'facefix' / f'{sig}.glb').exists()

            for failure in ('hub', 'rig', 'normalize', 'publication', 'stale'):
                seed()
                before = files()
                with ExitStack() as fault:
                    if failure == 'hub': face.failure = GatewayRejectedError('fake hub failure')
                    if failure == 'rig': rig.failure = GatewayRejectedError('fake rig failure')
                    if failure == 'materials': rig.lost = True
                    if failure == 'normalize': fault.enter_context(patch.object(model3d, '_auto_normalize', side_effect=RuntimeError('fake normalize failure')))
                    if failure == 'extensions': fault.enter_context(patch.object(model3d, '_auto_extension_rig', return_value={'ok': False, 'error': 'fake extensions failure'}))
                    if failure == 'low': fault.enter_context(patch.object(model3d, 'build_lod', return_value={'ok': False, 'error': 'fake low failure'}))
                    if failure == 'stale': fault.enter_context(patch.object(model3d, '_publish_signature', return_value=None))
                    if failure == 'publication':
                        replace = os.replace
                        calls = []
                        def fail_once(source, target):
                            calls.append(str(target))
                            if len(calls) == 2:
                                raise OSError('fake publication failure')
                            return replace(source, target)
                        fault.enter_context(patch.object(os, 'replace', side_effect=fail_once))
                    try:
                        result = model3d.face_retexture_model('demo', sig)
                    except (RuntimeError, OSError):
                        pass
                    else:
                        assert not result['ok'], (failure, result)
                assert files() == before, failure
                assert not snap.exists(), failure
            for failure in ('materials', 'merged', 'retexture', 'extensions', 'low'):
                seed()
                original_files = files()
                with ExitStack() as fault:
                    if failure == 'materials': rig.lost = True
                    if failure == 'merged': rig.lost = 'merged'
                    if failure == 'retexture': fault.enter_context(patch.object(model3d, '_auto_retexture', side_effect=OSError('fake retexture failure')))
                    if failure == 'extensions': fault.enter_context(patch.object(model3d, '_auto_extension_rig', return_value={'ok': False, 'error': 'fake extensions failure'}))
                    if failure == 'low': fault.enter_context(patch.object(model3d, 'build_lod', return_value={'ok': False, 'error': 'fake low failure'}))
                    result = model3d.face_retexture_model('demo', sig)
                    assert result['ok'], (failure, result)
                assert face_retexture.snapshot_info(root, sig)['ok'], failure
                meta = model3d._read_sidecar(root / f'{sig}.glb')
                if failure in ('materials', 'merged'): assert meta['face_retexture']['material_lost']
                if failure == 'retexture':
                    assert not meta['refined']['retexture'] and meta['refined']['reason'] == 'fake retexture failure'
                    assert result['warnings']['refined'] == meta['refined']
                    assert model3d.get_model3d_info('demo')['model']['refined'] == meta['refined']
                    with patch.object(model3d, '_auto_retexture', side_effect=OSError('fake retexture failure')):
                        assert model3d.rerig_model('demo', sig)['warnings']['refined']['reason'] == 'fake retexture failure'
                if failure == 'extensions': assert meta['extension_rig']['status'] == 'failed'
                if failure == 'low':
                    assert meta['lod_error'] == 'fake low failure'
                    assert not (root / 'low' / f'{sig}.glb').exists()
                assert model3d.revert_face_retexture('demo', sig)['ok']
                for relative, raw in original_files.items():
                    if relative != Path(f'{sig}.json'):
                        assert (root / relative).read_bytes() == raw, (failure, relative)
            seed()
            assert model3d.face_retexture_model('demo', sig)['ok']
            before = files()
            (snap / f'{sig}.glb').write_bytes(b'corrupt')
            assert not model3d.revert_face_retexture('demo', sig)['ok']
            assert files() == before
            seed()
            assert model3d.face_retexture_model('demo', sig)['ok']
            (snap / 'manifest.json').write_text(json.dumps({'created_at': 'fake', 'files': []}))
            assert not model3d.revert_face_retexture('demo', sig)['ok']
            seed()
            assert model3d.face_retexture_model('demo', sig)['ok']
            replacement = root / '.new.glb'
            replacement.write_bytes(fixture())
            @model3d._serial_model
            def replace_source(name, signature):
                return model3d._store_unrigged_model(name, signature, {'path': str(replacement), 'backend': 'new-mesh'}, 'mixamo', {'source_image': f'tpose_{sig}.png', 'source_image_sha256': hashlib.sha256(photo()).hexdigest()})
            assert replace_source('demo', sig)['ok']
            assert not snap.exists() and not (root / 'facefix' / f'{sig}.glb').exists()
            assert model3d._read_sidecar(root / 'unrigged' / f'{sig}.glb')['source_image_sha256'] == hashlib.sha256(photo()).hexdigest()
            seed()
            assert model3d.face_retexture_model('demo', sig)['ok']
            with tempfile.TemporaryDirectory(dir=root) as tmp_stage:
                stage = Path(tmp_stage)
                token = model3d._publication_token(root, sig)
                (stage / '.replace-source').touch()
                (stage / f'{sig}.glb').write_bytes(fixture())
                token = model3d._publish_signature('demo', root, stage, sig, token,
                                                   retain_stage=True, rollback_on_error=True)
                assert token is not None and not snap.exists()
                (stage / f'{sig}.glb').write_bytes(fixture(rigged=True))
                replace = os.replace
                def fail_final(source, target):
                    if Path(source) == stage / f'{sig}.glb':
                        raise OSError('fake final publication failure')
                    return replace(source, target)
                with patch.object(os, 'replace', side_effect=fail_final):
                    try:
                        model3d._publish_signature('demo', root, stage, sig, token, rollback_on_error=True)
                    except OSError:
                        pass
                    else:
                        raise AssertionError('Final publication must fail')
                assert (root / f'{sig}.glb').read_bytes() == fixture()
                assert not snap.exists(), 'Old snapshot must stay removed after checkpoint'
                assert not model3d.revert_face_retexture('demo', sig)['ok']
            # A successful later distance rebuild clears its prior failure.
            seed()
            served = root / f'{sig}.glb'
            metadata = model3d._read_sidecar(served)
            metadata['lod_error'] = 'earlier low failure'
            model3d._publish_sidecar(served, metadata)
            from app.blender import runner
            def fake_lod_run(operation, *, out_dir, **kwargs):
                target = out_dir / 'reduced.glb'
                target.write_bytes(fixture(rigged=True))
                return {'ok': True, 'outputs': {'model': str(target)},
                        'data': {'stages': [{'tris': 2, 'tris_before': 2}]}}
            with patch.object(runner, 'run', side_effect=fake_lod_run):
                assert real_build_lod('demo', sig)['ok']
            assert 'lod_error' not in model3d._read_sidecar(served)
            # Exercise the actual HTTP adapters without importing the server.
            from fastapi import FastAPI, HTTPException, Request
            import asyncio
            from httpx import AsyncClient, ASGITransport
            from app.core.auth_dependency import require_admin
            from app.routes import characters
            # The response owns the image bytes even if publication deletes the path.
            seed()
            assert model3d.face_retexture_model('demo', sig)['ok']
            compare_path = root / 'facefix' / f'{sig}.png'
            request = Request({'type': 'http', 'headers': []})
            response = characters.compare_character_face_retexture('demo', request, sig)
            expected_image = compare_path.read_bytes()
            etag = response.headers['etag']
            cached = characters.compare_character_face_retexture('demo', Request({
                'type': 'http', 'headers': [(b'if-none-match', etag.encode())]}), sig)
            assert cached.status_code == 304 and cached.headers['etag'] == etag
            compare_path.unlink()
            assert response.body == expected_image
            app = FastAPI()
            app.include_router(characters.router)
            def admin(request: Request):
                if request.headers.get('x-role') != 'admin':
                    raise HTTPException(403, 'Admin required')
                return {'role': 'admin'}
            app.dependency_overrides[require_admin] = admin
            url = f'/characters/demo/model3d/face-retexture'
            headers = {'x-role': 'admin'}
            seed()
            async def route_checks():
                async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
                    assert (await client.get(url + '/check', params={'signature': sig})).status_code == 403
                    assert (await client.post(url, params={'signature': sig})).status_code == 403
                    assert (await client.post(url + '/revert', params={'signature': sig})).status_code == 403
                    assert (await client.get(url + '/compare', params={'signature': sig})).status_code == 403
                    response = await client.get(url + '/check', headers=headers, params={'signature': sig, 'lang': 'de'})
                    assert response.status_code == 200 and response.json()['ok'] and response.json()['runnable']
                    missing = await client.get(url + '/check', headers=headers, params={'signature': sig, 'backend': 'missing'})
                    assert not missing.json()['runnable'] and missing.json()['runnable_problems'][0]['code'] == 'no_backend'
                    with patch.object(routing, '_rules', return_value=[]):
                        ready = face_retexture.runnable('demo')
                        assert 'no_rigger' in [p['code'] for p in ready['problems']]
                    assert (await client.get(url + '/check', headers=headers, params={'signature': '../escape'})).status_code == 400
                    assert (await client.post(url, headers=headers, params={'signature': sig, 'strength': 2})).status_code == 422
                    assert (await client.get(url + '/compare', headers=headers, params={'signature': sig})).status_code == 404
                    from app.core.task_queue import get_task_queue
                    queue = get_task_queue()
                    finished = threading.Event()
                    real_finish = queue.track_finish
                    def track_finish(*args, **kwargs):
                        try:
                            return real_finish(*args, **kwargs)
                        finally:
                            finished.set()
                    with patch.object(queue, 'track_finish', side_effect=track_finish):
                        response = await client.post(url, headers=headers, params={'signature': sig})
                        assert response.status_code == 200 and response.json()['task_id']
                        for _ in range(500):
                            with model3d._lock:
                                complete = finished.is_set() and 'demo' not in model3d._generating
                            if complete:
                                break
                            await asyncio.sleep(0.01)
                        assert complete, 'background correction did not finish'
                    assert model3d._face_retexture_results['demo']['ok']
                    comparison = await client.get(url + '/compare', headers=headers, params={'signature': sig})
                    assert comparison.status_code == 200 and comparison.content == photo()
                    assert comparison.headers['content-type'] == 'image/png'
                    assert (await client.get(url + '/compare', headers={**headers, 'if-none-match': comparison.headers['etag']}, params={'signature': sig})).status_code == 304
                    assert (await client.post(url + '/revert', headers=headers, params={'signature': sig})).json()['ok']
                    assert (await client.get(url + '/compare', headers=headers, params={'signature': sig})).status_code == 404
            async def run_routes():
                # Keep the selector awake when the sandbox drops self-pipe signals.
                async def heartbeat():
                    while True:
                        await asyncio.sleep(0.01)
                ticker = asyncio.create_task(heartbeat())
                try:
                    await asyncio.wait_for(route_checks(), timeout=10)
                finally:
                    ticker.cancel()
            asyncio.run(run_routes())
            # P2 integration uses the real service, publication and face/rig orchestration.
            from app.imagegen.base import BackendBusyError, GenerationCancelled, MediaGenerationDisabled
            from PIL import Image
            import io
            class Upscale(ImageBackend):
                def __init__(self):
                    super().__init__('upscale-fixture', '', 0, 'fake_upscale', 'FACE_UPSCALE_SMOKE_')
                    self.category = 'upscale'
                    self._available = True
                    self.instance_enabled = True
                    self.model = 'fixture-v1'
                    self.upscale_scale = 2
                    self.max_side = 512
                    self.color_fix = True
                    self.calls = 0
                    self.failure = None
                def check_availability(self): return self.available
                def _generate(self, prompt, negative, params):
                    self.calls += 1
                    if self.failure: raise self.failure
                    decoded = Image.open(io.BytesIO(params['image_bytes']))
                    out = io.BytesIO()
                    decoded.resize((decoded.width*2, decoded.height*2)).save(out, format='PNG')
                    return [out.getvalue()]
            up = Upscale()
            svc._pool.backends.append(up)
            with patch.object(routing, '_rules', side_effect=lambda occasion: ['rigger'] if occasion == 'rig_humanoid' else ['upscale-fixture'] if occasion == 'upscale' else []):
                seed()
                original_photo = face_retexture.flatten_photo(photo())
                calls = up.calls
                assert model3d.face_retexture_model('demo', sig, upscale=False)['ok']
                assert up.calls == calls and face.calls[-1]['reference_image_bytes'] == original_photo
                assert model3d._read_sidecar(root / f'{sig}.glb')['face_retexture']['upscale']['status'] == 'off'
                seed()
                assert model3d.face_retexture_model('demo', sig)['ok']
                sent = face.calls[-1]['reference_image_bytes']
                assert Image.open(io.BytesIO(sent)).size == (32, 32) and sent != original_photo
                status = model3d._read_sidecar(root / f'{sig}.glb')['face_retexture']['upscale']
                assert status['in'] == [16, 16] and status['out'] == [32, 32] and not status['cached']
                cache = root / 'facefix-ref' / f'{sig}.png'
                assert cache.read_bytes() == sent
                assert not any(r.parts[0] == 'facefix-ref' for r in model3d._signature_files(root, sig))
                manifest = json.loads((snap / 'manifest.json').read_text())
                assert not any(entry['path'].startswith('facefix-ref/') for entry in manifest['files'])
                assert not any('facefix-ref' in p.parts for p in export_files(root, [sig]))
                calls = up.calls
                assert model3d.face_retexture_model('demo', sig)['ok'] and up.calls == calls
                assert model3d._read_sidecar(root / f'{sig}.glb')['face_retexture']['upscale']['cached']
                assert model3d.rerig_model('demo', sig)['ok'] and cache.exists()
                assert model3d._read_sidecar(root / f'{sig}.glb')['face_retexture']['upscale']['cached']
                assert model3d.get_model3d_info('demo')['upscale_backends'][0]['name'] == up.name
                assert model3d.revert_face_retexture('demo', sig)['ok'] and cache.exists()
                assert model3d.face_retexture_model('demo', sig)['ok'] and up.calls == calls
                up.color_fix = False
                assert model3d.face_retexture_model('demo', sig)['ok'] and up.calls == calls+1
                calls = up.calls
                cache.write_bytes(b'broken')
                assert model3d.face_retexture_model('demo', sig)['ok'] and up.calls == calls+1
                # Failed projection and failed rig retain the useful cache.
                for target in (face, rig):
                    calls = up.calls
                    target.failure = GatewayRejectedError('fixture failure after upscale')
                    try: model3d.face_retexture_model('demo', sig)
                    except GatewayRejectedError: pass
                    else: raise AssertionError('Face/rig fixture should fail')
                    target.failure = None
                    assert cache.exists() and up.calls == calls
                for failure in (RuntimeError('upscale fixture failed'), BackendBusyError('upscale fixture busy')):
                    seed()
                    up._available = True
                    up._cooldown_until = 0
                    up.failure = failure
                    assert model3d.face_retexture_model('demo', sig)['ok']
                    assert face.calls[-1]['reference_image_bytes'] == original_photo
                    status = model3d._read_sidecar(root / f'{sig}.glb')['face_retexture']['upscale']
                    assert status['status'] == 'failed' and status['error']
                    if isinstance(failure, BackendBusyError):
                        assert status['busy'] and not up.in_cooldown()
                for failure in (GenerationCancelled('upscale-fixture-job'), MediaGenerationDisabled('fixture disabled')):
                    seed()
                    up._available = True
                    up._cooldown_until = 0
                    up.failure = failure
                    before = files()
                    face_count = len(face.calls)
                    try: model3d.face_retexture_model('demo', sig)
                    except type(failure): pass
                    else: raise AssertionError('Cancel/master switch must propagate')
                    assert files() == before and len(face.calls) == face_count and not snap.exists()
                    assert not up.in_cooldown()
                # Real Hub polling cancellation: zero face calls/publications,
                # no CPU fallback and no cooldown (expected by hand from 13a.7).
                from app.imagegen.backends.openai_upscale import OpenAIUpscaleBackend
                from app.imagegen.backends import _gateway_job
                from types import SimpleNamespace
                hub = OpenAIUpscaleBackend('hub-cancel', 'https://gateway.invalid', 1, 'FACE_UPSCALE_SMOKE_')
                hub._schema = (True, 'reference', frozenset({'scale'}))
                hub._available = True
                hub.instance_enabled = True
                hub.poll_interval = 0
                svc._pool.backends.append(hub)
                seed()
                before = files()
                face_count, cpu_count = len(face.calls), up.calls
                reply = SimpleNamespace(status_code=200, content=b'present', json=lambda: {'status': 'cancelled'})
                schema_reply = SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                    json=lambda: {'images': [{'name': 'reference', 'required': True}], 'params': ['scale']})
                def hub_response(url, **kwargs):
                    return schema_reply if url.endswith('/schema') else reply
                with patch.object(routing, '_rules', side_effect=lambda occasion: ['hub-cancel', 'upscale-fixture'] if occasion == 'upscale' else ['rigger'] if occasion == 'rig_humanoid' else []), patch('app.imagegen.backends.openai_upscale.submit_job', return_value='cancelled-job'), patch.object(_gateway_job.requests, 'get', side_effect=hub_response):
                    try:
                        model3d.face_retexture_model('demo', sig)
                    except GenerationCancelled:
                        pass
                    else:
                        raise AssertionError('Gateway cancellation must abort the face run')
                assert files() == before and not snap.exists()
                assert len(face.calls) == face_count and up.calls == cpu_count
                assert not hub.in_cooldown()
                svc._pool.backends.remove(hub)
                seed()
                up.failure = None
                up._available = True
                up._cooldown_until = 0
                assert model3d.face_retexture_model('demo', sig)['ok'] and cache.exists()
                from app.core.outfit_cache_gc import _mesh_files
                assert cache in _mesh_files('demo')[sig]
                model3d._purge_combination(root, sig, preserve_sources=True)
                assert cache.exists()
                model3d._purge_combination(root, sig)
                assert not cache.exists() and not cache.with_suffix('.json').exists()
                # Real source publication also purges the cache outside its stage.
                seed()
                assert model3d.face_retexture_model('demo', sig)['ok'] and cache.exists()
                with tempfile.TemporaryDirectory(dir=root) as replacement_stage:
                    stage = Path(replacement_stage)
                    (stage / '.replace-source').touch()
                    (stage / f'{sig}.glb').write_bytes(fixture())
                    assert model3d._publish_signature('demo', root, stage, sig,
                        model3d._publication_token(root, sig), rollback_on_error=True) is not None
                assert not cache.exists() and not cache.with_suffix('.json').exists()
                # The real GC purger removes PNG and metadata together.
                seed()
                assert model3d.face_retexture_model('demo', sig)['ok'] and cache.exists()
                from app.core import outfit_cache_gc
                with patch.object(outfit_cache_gc, 'verify_cache', return_value={'stale_signatures': [sig]}):
                    assert outfit_cache_gc.purge_stale('demo', [sig])['deleted_files'] > 0
                assert not cache.exists() and not cache.with_suffix('.json').exists()
                seed()
                up._available = False
                async def explicit_upscale_route():
                    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
                        response = await client.post(url, headers=headers, params={'signature': sig, 'upscale_backend': up.name})
                        assert response.status_code == 503
                async def explicit_with_heartbeat():
                    async def heartbeat():
                        while True: await asyncio.sleep(0.01)
                    ticker = asyncio.create_task(heartbeat())
                    try: await asyncio.wait_for(explicit_upscale_route(), 10)
                    finally: ticker.cancel()
                asyncio.run(explicit_with_heartbeat())
            svc._pool.backends.remove(up)

    print('PASS: face retexture stages, provenance, first snapshot, byte-exact revert, rerig, source replacement, export, 5 fatal/5 nonfatal failures, damaged snapshots, four admin HTTP routes and P2 upscale integration')


if __name__ == '__main__':
    main()
