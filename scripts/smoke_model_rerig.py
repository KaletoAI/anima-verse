#!/usr/bin/env python3
"""P3 re-rig contract, no hub or Blender required.

Hand-derived expectations: one rig job and zero mesh jobs replace raw,
normalized prerig and served bytes; source GLB/PNG/JSON remain byte-identical.
An explicit failing rigger cannot call the routed backup. The backend's
configured no_fingers reaches input_no_fingers unchanged. Missing sources
submit nothing. Failure at
rig, normalization, extensions, low rebuild or publication preserves every
byte of the served/source pair. Default signature selects the served model;
character finger settings are ignored; stale snapshots never overwrite a writer.
Generic source is red on top, blue below; its served PNG must be blue on top
(the hub FBX V correction). A pre-existing low tier is rebuilt at its old ratio.
A player POST returns 403, an admin starts a tracked background task.
Usage: ./.venv/bin/python scripts/smoke_model_rerig.py
"""
import os
import sys
import inspect
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_tmp = tempfile.TemporaryDirectory()
os.environ['STORAGE_DIR'] = _tmp.name + '/world'
os.environ['INSTANCE_DIR'] = _tmp.name + '/instance'
from app.core import paths
paths.init(os.environ['STORAGE_DIR'])
paths.init_instance(Path(_tmp.name)/'instance')
import base64
import io
import json
import struct
import threading
from contextlib import ExitStack
from unittest.mock import patch
from PIL import Image
from app.core.rig_contract import BASE_JOINT_NAMES
from app.imagegen.base import ImageBackend, BackendFailedError
from app.imagegen.selection import BackendPool
from app.imagegen.service import ImageService
from app.imagegen.backends.openai_mesh import OpenAIMeshBackend
from app.imagegen import routing
from app.core import model3d, db
db.init_schema()
assert hasattr(model3d, 'rerig_model'), 'P3 core re-rig action missing'
def color_png():
    image = Image.new('RGB', (16, 16), 'red')
    for y in range(8, 16):
        for x in range(16):
            image.putpixel((x, y), (0, 0, 255))
    out = io.BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


def fixture_glb(rig=False):
    color = color_png()
    doc = {'asset': {'version': '2.0'}, 'meshes': [{'primitives': [{'material': 0}]}],
           'buffers': [{'byteLength': len(color)}],
           'bufferViews': [{'byteOffset': 0, 'byteLength': len(color)}],
           'images': [{'bufferView': 0, 'mimeType': 'image/png'}],
           'textures': [{'source': 0}],
           'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}]}
    if rig:
        doc['nodes'] = [{'name': n} for n in BASE_JOINT_NAMES]
        doc['skins'] = [{'joints': list(range(52))}]
    raw = json.dumps(doc).encode()
    raw += b' ' * (-len(raw) % 4)
    color += b'\0' * (-len(color) % 4)
    body = struct.pack('<II', len(raw), 0x4e4f534a) + raw + struct.pack('<II', len(color), 0x004e4942) + color
    return b'glTF' + struct.pack('<II', 2, len(body) + 12) + body


class Fake(ImageBackend):
    def __init__(self, name, category, rig, cost=0, failure=None):
        super().__init__(name, 'http://fake', cost, 'fake', 'RIG_SPLIT_FAKE_')
        self.MEDIA_TYPE = 'mesh'
        self.category, self.mesh_rig = category, rig
        self.instance_enabled = True
        self._available = True
        self.calls = []
        self.failure = failure
        self._meta = threading.local()

    def check_availability(self):
        return self.available

    @property
    def last_result_files(self):
        return self._meta.files

    def generate(self, prompt, negative, params, log_meta=None):
        self.calls.append(dict(params))
        if self.failure:
            raise self.failure
        if self.category == 'mesh2rig':
            uploaded = Path(params['source_model_path'])
            assert (root/'unrigged'/uploaded.name).is_file(), 'source must be durable before rig submission'
            payload = OpenAIMeshBackend.build_input_files(self, params)
            assert set(payload) == {'input_mesh_path'}
            assert base64.b64decode(payload['input_mesh_path'].split(',', 1)[1]) == fixture_glb()
            assert OpenAIMeshBackend.build_alias_params(self, params) == {'input_no_fingers': self.no_fingers}
            assert 'no_fingers' not in params
            if self.mesh_rig == 'generic':
                self._meta.files = [{'name': 'test_articulationxl.fbx', 'kind': 'file', 'mime': 'application/octet-stream'}]
                return [b'Kaydara FBX Binary\x00' + b'fixture']
            self._meta.files = [{'name': 'test_rigged.glb', 'kind': 'file', 'mime': 'application/octet-stream'}]
            return [fixture_glb(True)]
        self._meta.files = [{'name': 'test_00001_.glb', 'kind': 'file', 'mime': 'application/octet-stream'}]
        assert 'no_fingers' not in params
        return [fixture_glb()]

    _generate = lambda self, prompt, negative, params: []
    _file_slot = ''
    no_fingers = True
    _remember_input = lambda self, raw: ''


def service(*backends):
    svc = object.__new__(ImageService)
    svc._pool = BackendPool(list(backends), agent_instances_provider=lambda name: {})
    return svc



root = Path(_tmp.name)/'models'
(root/'unrigged').mkdir(parents=True)
mesh = Fake('mesh', 'img2mesh', 'none')
rigger = Fake('rigger', 'mesh2rig', 'mixamo')
backup = Fake('backup', 'mesh2rig', 'mixamo')
creature = Fake('creature', 'mesh2rig', 'generic')
svc = service(mesh, rigger, backup, creature)
routing._rules = lambda occasion: ['rigger', 'backup'] if occasion == 'rig_humanoid' else ['creature']
routing._character_switches = lambda character: {}

def seed(sig, ext='.glb'):
    (root/'unrigged'/f'{sig}.glb').write_bytes(fixture_glb())
    (root/'unrigged'/f'{sig}.json').write_text(json.dumps({'mesh_backend': 'mesh-original', 'mesh_route_meta': {'original': True}}))
    (root/f'{sig}{ext}').write_bytes(b'old served')
    (root/f'{sig}.json').write_text(json.dumps({'rig': 'mixamo' if ext == '.glb' else 'generic', 'mesh_backend': 'mesh-original', 'mesh_route_meta': {'original': True}}))
    for folder in ('raw', 'prerig', 'low'):
        (root/folder).mkdir(exist_ok=True)
        (root/folder/f'{sig}{ext}').write_bytes(b'old '+folder.encode())
    (root/'low'/f'{sig}.json').write_text(json.dumps({'lod_ratio': 0.4}))

def snapshot(sig):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob(f'{sig}.*') if p.is_file() and not any(s.startswith('.process-') for s in p.parts)}

def normalize(name, path, meta, **kw):
    path.write_bytes(path.read_bytes()+b'normalized')

def extensions(name, path, meta, **kw):
    target=path.parent/'prerig'/path.name
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(path.read_bytes())
    path.write_bytes(path.read_bytes()+b'extended')
    return {'ok': True}

def lod(name, signature=None, ratio=0.25):
    assert ratio == 0.4
    target=model3d.get_model3d_dir(name)
    (target/'low').mkdir(exist_ok=True)
    (target/'low'/f'{signature}.glb').write_bytes((target/f'{signature}.glb').read_bytes()+b'low')
    return {'ok': True}

with patch('app.models.character.get_character_profile', return_value={'model3d_opts': {'no_fingers': True, 'auto_generate': True}}):
    assert model3d.get_model3d_options('demo') == {'auto_generate': True, 'extension_rig': {}, 'extension_motion': {}}

real_normalize=model3d._auto_normalize
with ExitStack() as stack:
    stack.enter_context(patch('app.imagegen.service.get_image_service', return_value=svc))
    stack.enter_context(patch.object(svc, 'run_on_backend_channel', side_effect=lambda b, fn, **kw: fn()))
    stack.enter_context(patch.object(model3d, 'get_model3d_dir', side_effect=lambda n: getattr(model3d._staging, 'directories', {}).get(n) or root))
    stack.enter_context(patch.object(model3d, 'get_model3d_options', return_value={'no_fingers': False}))
    stack.enter_context(patch.object(model3d, 'required_rig', return_value='mixamo'))
    stack.enter_context(patch.object(model3d, '_auto_retexture', return_value=None))
    stack.enter_context(patch.object(model3d, '_auto_normalize', side_effect=normalize))
    stack.enter_context(patch.object(model3d, '_auto_extension_rig', side_effect=extensions))
    stack.enter_context(patch.object(model3d, '_attach_measurement', return_value=None))
    stack.enter_context(patch.object(model3d, 'build_lod', side_effect=lod))
    seed('mixamo')
    before=snapshot('mixamo')
    result=model3d.rerig_model('demo', signature='mixamo', backend_glob='rigger')
    assert result['ok'], result
    assert (root/'raw/mixamo.glb').read_bytes() == fixture_glb(True)
    assert (root/'prerig/mixamo.glb').read_bytes() == fixture_glb(True)+b'normalized'
    assert (root/'mixamo.glb').read_bytes() == fixture_glb(True)+b'normalizedextended'
    assert (root/'low/mixamo.glb').read_bytes() == fixture_glb(True)+b'normalizedextendedlow'
    for p, value in before.items():
        if p.parts[0] == 'unrigged': assert (root/p).read_bytes() == value
    meta=json.loads((root/'mixamo.json').read_text())
    assert meta['mesh_backend'] == 'mesh-original' and meta['mesh_route_meta'] == {'original': True}
    assert meta['rig_backend'] == 'rigger' and 'no_fingers' not in meta
    assert not mesh.calls
    for failure in ('rig', 'normalize', 'extension', 'low', 'publication'):
        if failure == 'publication': seed('mixamo')
        before=snapshot('mixamo')
        with ExitStack() as failures:
            if failure == 'rig': rigger.failure=RuntimeError('broken rigger')
            elif failure == 'normalize':
                failures.enter_context(patch.object(model3d, '_auto_normalize', side_effect=real_normalize))
                failures.enter_context(patch('app.blender.refine.auto_normalize_enabled', return_value=True))
                failures.enter_context(patch('app.blender.refine.normalize', return_value={'applied': False, 'error': 'normalize failed'}))
                failures.enter_context(patch.object(model3d, '_auto_extension_rig', return_value={'ok': True}))
            elif failure == 'extension': failures.enter_context(patch.object(model3d, '_auto_extension_rig', return_value={'ok': False, 'error': 'extension failed'}))
            elif failure == 'publication':
                original_replace=os.replace
                def fail_publication(src, dst):
                    if Path(dst) == root/'mixamo.json':
                        raise OSError('publication failed')
                    return original_replace(src, dst)
                failures.enter_context(patch('os.replace', side_effect=fail_publication))
            else: failures.enter_context(patch.object(model3d, 'build_lod', return_value={'ok': False, 'error': 'low failed'}))
            try:
                result=model3d.rerig_model('demo', signature='mixamo', backend_glob='rigger')
                assert not result['ok']
            except BackendFailedError:
                assert failure == 'rig'
            except OSError as exc:
                assert failure == 'publication' and 'publication failed' in str(exc)
            except RuntimeError as exc:
                assert failure == 'normalize' and 'normalize failed' in str(exc)
        rigger.failure=None
        rigger._cooldown_until=0
        rigger._available=True
        assert snapshot('mixamo') == before, failure
    assert len(rigger.calls) == 6, 'extension and low failure must actually run the rig'
    assert not backup.calls and not mesh.calls
    rigger.no_fingers = False
    with patch.object(model3d, '_auto_normalize'), patch.object(model3d, '_auto_extension_rig', return_value={'ok': True}), patch.object(model3d, 'build_lod', side_effect=lod):
        assert model3d.rerig_model('demo', signature='mixamo')['ok']
    assert 'no_fingers' not in rigger.calls[-1]
    # Default means SERVED signature, which can differ from current outfit;
    # absent no_fingers preserves the backend default instead of forcing false.
    with patch.object(model3d, 'get_model3d_options', return_value={'no_fingers': False}), patch.object(model3d, 'find_model3d_serving', return_value=(root/'mixamo.glb', 'nearest')), patch.object(model3d, 'current_outfit_state', return_value=({}, {}, 'missing')):
        result=model3d.rerig_model('demo')
        assert result['ok'] and result['filename'] == 'mixamo.glb'
        assert 'no_fingers' not in rigger.calls[-1]
    with patch.object(model3d, 'find_model3d_serving', return_value=(root/'mixamo.glb', 'exact')), patch.object(model3d, 'current_outfit_state', return_value=({}, {}, 'mixamo')):
        info=model3d.get_model3d_info('demo')
        assert info['model']['has_unrigged_source'] is True
        assert info['model']['mesh_backend'] == 'mesh-original'
        assert info['model']['rig_backend'] == 'rigger'
        assert {b['name'] for b in info['rig_backends']} == {'rigger', 'backup'}
        (root/'unrigged/mixamo.glb').unlink()
        info=model3d.get_model3d_info('demo')
        assert info['model']['has_unrigged_source'] is False
        assert info['model']['unrigged_source_reason']
        (root/'unrigged/mixamo.glb').write_bytes(fixture_glb())
    # A concurrent writer wins; the private re-rig must be discarded.
    def concurrent_write(b, fn, **kw):
        value=fn()
        (root/'mixamo.glb').write_bytes(b'concurrent served model')
        return value
    with patch.object(svc, 'run_on_backend_channel', side_effect=concurrent_write):
        result=model3d.rerig_model('demo', signature='mixamo')
    assert result['status'] == 'stale' and not result['ok']
    assert (root/'mixamo.glb').read_bytes() == b'concurrent served model'
    before_calls=len(rigger.calls)
    assert not model3d.rerig_model('demo', signature='missing')['ok']
    assert len(rigger.calls) == before_calls
    seed('generic', '.fbx')
    (root/'low/generic.fbx').unlink()
    (root/'unrigged/generic.png').write_bytes(color_png())
    with patch.object(model3d, 'required_rig', return_value='generic'), patch.object(model3d, '_auto_normalize'), patch.object(model3d, '_auto_extension_rig', return_value={'ok': True}):
        result=model3d.rerig_model('demo', signature='generic')
    assert result['ok'], result
    assert Image.open(root/'generic.png').getpixel((0,0)) == (0,0,255)
    assert Image.open(root/'unrigged/generic.png').getpixel((0,0)) == (255,0,0)
print('PASS re-rig stages, immutable source, explicit no fallback, atomic failures, generic basecolor and low rebuild')

# Mount the actual router and actual auth dependency; only session lookup is
# faked. An Event holds the expensive rig worker so the HTTP response can be
# checked while its tracked task is still running.
from fastapi import FastAPI
import asyncio
from httpx import AsyncClient, ASGITransport
from app.routes import characters
from app.core import auth_dependency
from app.models.character import save_character_profile, get_character_dir
assert save_character_profile('demo', {'name': 'demo', 'template': 'human'}, create_new=True)
char_root=get_character_dir('demo')/'model3d'
(char_root/'unrigged').mkdir(parents=True, exist_ok=True)
(char_root/'unrigged/mixamo.glb').write_bytes(fixture_glb())
char_root.joinpath('mixamo.glb').write_bytes(fixture_glb(True))
app=FastAPI()
app.include_router(characters.router)
app.middleware('http')(auth_dependency.auth_gate_middleware)
app.middleware('http')(auth_dependency.user_context_middleware)
started=threading.Event()
release=threading.Event()
finished=threading.Event()

def worker(*args, **kwargs):
    started.set()
    assert release.wait(10)
    return {'ok': True}

from app.core.task_queue import get_task_queue
queue=get_task_queue()
original_finish=queue.track_finish

def track_finish(*args, **kw):
    try: return original_finish(*args, **kw)
    finally: finished.set()

async def route_checks():
    with patch.object(auth_dependency, '_get_session_user', side_effect=lambda r: {'id':'test', 'username':'demo', 'role':r.headers.get('x-role', 'user'), 'allowed_characters':['demo']}), patch.object(model3d, 'rerig_model', side_effect=worker), patch.object(queue, 'track_finish', side_effect=track_finish), patch.object(model3d, 'find_model3d_serving', return_value=(char_root/'mixamo.glb','exact')):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            from app.routes.characters import rerig_character_model3d
            assert 'no_fingers' not in inspect.signature(rerig_character_model3d).parameters
            assert 'no_fingers' not in inspect.signature(model3d.trigger_rerig).parameters
            url='/characters/demo/model3d/rerig'
            assert (await client.post(url, headers={'x-role':'user'})).status_code == 403
            assert not started.is_set()
            response=await client.post(url, headers={'x-role':'admin'})
            assert response.status_code == 200, response.text
            while not started.is_set():
                await asyncio.sleep(0.01)
            task_id=response.json()['task_id']
            with queue._connect() as conn:
                row=conn.execute('SELECT task_type,status FROM tasks WHERE task_id=?',(task_id,)).fetchone()
                assert tuple(row) == ('model3d_rerig','running'), row
            release.set()
            while not finished.is_set() or 'demo' in model3d._generating:
                await asyncio.sleep(0.01)
            assert (await client.post(url+'?signature=missing', headers={'x-role':'admin'})).status_code == 409
            finished.clear()
            with patch.object(model3d, 'rerig_model', return_value={'ok': False, 'error': 'rig failed'}):
                response=await client.post(url, headers={'x-role': 'admin'})
                assert response.status_code == 200
                while not finished.is_set() or 'demo' in model3d._generating:
                    await asyncio.sleep(0.01)
                with queue._connect() as conn:
                    row=conn.execute('SELECT status,error FROM tasks WHERE task_id=?', (response.json()['task_id'],)).fetchone()
                    assert tuple(row) == ('failed', 'rig failed'), row
                assert model3d._rerig_results['demo']['ok'] is False
                assert model3d._rerig_results['demo']['error'] == 'rig failed'
            with patch('app.imagegen.service.get_image_service', return_value=svc):
                creature._available=True
                assert (await client.post(url+'?backend=creature', headers={'x-role':'admin'})).status_code == 400
                creature._available=False
                assert (await client.post(url+'?backend=creature', headers={'x-role':'admin'})).status_code == 503
    print('PASS real admin-only route, tracked nonblocking task, source and explicit backend preflight')

async def main():
    # A heartbeat also works in sandboxes that drop the loop's self-pipe
    # wakeup from the route threadpool; it does not alter route semantics.
    async def heartbeat():
        while True:
            await asyncio.sleep(0.01)
    ticker=asyncio.create_task(heartbeat())
    try:
        await route_checks()
    finally:
        ticker.cancel()
asyncio.run(main())
