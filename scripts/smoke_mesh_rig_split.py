#!/usr/bin/env python3
"""Check the two-stage mesh contract without a hub.

Hand-derived expectations from plan-mesh-rig-trennung P1/P2: two character
occasions accept any img2mesh; rig occasions accept any mesh2rig but require
a configured chain. Migration seeds both rig chains in cost order, drops old
declarations and preserves enabled flags; a second pass changes nothing.
A validated source and its served static GLB must be durable before rigging.
A failed replacement retains the NEW source/static pair, never the old rig.
Two busy rig runs produce failed task records, no fallback and no cooldown.
A 64 MiB + 1 byte source is refused before submission. The shared single-slot
channel must record exactly
mesh start/end, rig start/end twice, never an overlapping or nested submit.
The 16x16 source is red on its upper half, blue on its lower half: generic
FBX needs a V-corrected PNG (top blue), while the retained source stays top
red. Both actual character ZIP import and model_store export retain GLB,
sidecar and creature PNG; GC/purge removes the combination's source too.
Two boot migrations put copied API keys in secrets.json only, and the second
boot writes nothing. Rig requests contain only the backend's configured input_no_fingers in params
and a data-URI GLB in files.input_mesh_path, including with no alias schema.
Recovery accepts valid unrigged gateway deliveries without force or automatic
rigging, retaining their provenance; invalid deliveries leave the pair unchanged.
A concurrent real upload before the source checkpoint wins without rig submission.
Usage: ./.venv/bin/python scripts/smoke_mesh_rig_split.py
"""
import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_tmp = tempfile.TemporaryDirectory()
os.environ['STORAGE_DIR'] = _tmp.name + '/world'
os.environ['INSTANCE_DIR'] = _tmp.name + '/instance'
from app.core import paths
paths.init(os.environ['STORAGE_DIR'])
paths.init_instance(Path(_tmp.name) / 'instance')
from app.imagegen.occasions import backend_fits
for occasion in ('mesh_humanoid', 'mesh_creature', 'mesh_object', 'mesh_building'):
    assert backend_fits(occasion, {'media': 'mesh', 'category': 'img2mesh'})
    assert not backend_fits(occasion, {'media': 'mesh', 'category': 'mesh2rig'})
for occasion in ('rig_humanoid', 'rig_creature'):
    assert backend_fits(occasion, {'media': 'mesh', 'category': 'mesh2rig'})
    assert not backend_fits(occasion, {'media': 'mesh', 'category': 'img2mesh'})
from app.core.config import _migrate_mesh_rig_split
cfg = {'image_generation': {'backends': [
    {'name': 'disabled', 'api_type': 'openai_mesh', 'category': 'img2mesh', 'mesh_rig': 'mixamo', 'enabled': False},
    {'name': 'Trellis2-Low', 'api_type': 'openai_mesh', 'category': 'img2mesh', 'enabled': True},
    {'name': 'mia-high', 'api_type': 'openai_mesh', 'category': 'mesh2rig', 'mesh_rig': 'mixamo', 'cost': 2},
    {'name': 'mia-low', 'api_type': 'openai_mesh', 'category': 'mesh2rig', 'mesh_rig': 'mixamo', 'cost': 1},
    {'name': 'unirig', 'api_type': 'openai_mesh', 'category': 'mesh2rig', 'mesh_rig': 'generic'},
    {'name': 'off', 'api_type': 'openai_mesh', 'category': 'mesh2rig', 'mesh_rig': 'generic', 'enabled': False},
]}}
assert _migrate_mesh_rig_split(cfg)
entries = cfg['image_generation']['backends']
assert len(entries) == 6 and entries[0]['enabled'] is False and entries[1]['enabled'] is True
assert all('mesh_rig' not in b for b in entries)
assert cfg['image_generation']['routing'] == {'rig_humanoid': ['mia-low', 'mia-high'], 'rig_creature': ['unirig']}
assert not _migrate_mesh_rig_split(cfg)
fresh = {'image_generation': {'backends': [{'name': 'Trellis2-Low', 'api_type': 'openai_mesh', 'category': 'img2mesh', 'enabled': True}]}}
assert not _migrate_mesh_rig_split(fresh)
assert fresh['image_generation']['backends'][0]['enabled'] is True
existing = {'image_generation': {'routing': {'rig_humanoid': ['custom']}, 'backends': [{'name': 'mia', 'category': 'mesh2rig', 'api_type': 'openai_mesh', 'mesh_rig': 'mixamo'}]}}
assert _migrate_mesh_rig_split(existing)
assert existing['image_generation']['routing']['rig_humanoid'] == ['custom']
# Malformed stored roots remain visible for admin repair, never crash load.
for raw in (['old'], 'old', '', False):
    malformed = {'image_generation': {'routing': raw, 'backends': [{'name': 'mia', 'api_type': 'openai_mesh', 'category': 'mesh2rig', 'mesh_rig': 'mixamo'}]}}
    assert _migrate_mesh_rig_split(malformed)
    assert malformed['image_generation']['routing'] == raw
    assert not _migrate_mesh_rig_split(malformed)
null_root = {'image_generation': {'routing': None, 'backends': [{'name': 'mia', 'api_type': 'openai_mesh', 'category': 'mesh2rig', 'mesh_rig': 'mixamo'}]}}
assert _migrate_mesh_rig_split(null_root)
assert null_root['image_generation']['routing'] == {'rig_humanoid': ['mia']}
print('PASS category separation and idempotent migration')

# The fake pool keeps routing and runner behavior real; only GPU submission
# and backend I/O are replaced. One worker is shared by both stages.
import base64
import io
import json
import struct
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from PIL import Image
from app.core.rig_contract import BASE_JOINT_NAMES
from app.imagegen.base import ImageBackend, BackendBusyError, MediaGenerationDisabled
from app.imagegen.selection import BackendPool
from app.imagegen.service import ImageService
from app.imagegen import routing
from app.imagegen.backends.openai_mesh import OpenAIMeshBackend
from app.core import model3d, model_refs, config, db
db.init_schema()
from app.core.model_store import export_files, read_sidecar
from app.core.model_validate import validate_fbx


def color_png():
    image = Image.new('RGB', (16, 16), 'red')
    for y in range(8, 16):
        for x in range(16):
            image.putpixel((x, y), (0, 0, 255))
    out = io.BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


def fixture_glb(rig=False, revision='original'):
    color = color_png()
    doc = {'asset': {'version': '2.0'}, 'meshes': [{'primitives': [{'material': 0}]}],
           'buffers': [{'byteLength': len(color)}],
           'bufferViews': [{'byteOffset': 0, 'byteLength': len(color)}],
           'images': [{'bufferView': 0, 'mimeType': 'image/png'}],
           'textures': [{'source': 0}],
           'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}]}
    doc['asset']['extras'] = {'revision': revision}
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
        self.category, self.delivered_rig = category, rig
        self.instance_enabled = True
        self._available = True
        self.calls = []
        self.failure = failure
        self._meta = threading.local()
        self.source = fixture_glb()
        self.check_submission = None
        self.check_delivery = None

    def check_availability(self):
        return self.available

    @property
    def last_result_files(self):
        return self._meta.files

    def generate(self, prompt, negative, params, log_meta=None):
        self.calls.append(dict(params))
        if self.category != 'mesh2rig' and self.failure:
            raise self.failure
        if self.category == 'mesh2rig':
            uploaded = Path(params['source_model_path'])
            assert (root/'unrigged'/uploaded.name).is_file(), 'source must be durable before rig submission'
            payload = OpenAIMeshBackend.build_input_files(self, params)
            assert set(payload) == {'input_mesh_path'}
            assert uploaded.read_bytes() == mesh.source, 'rig must consume the newest mesh, not a stale source'
            assert base64.b64decode(payload['input_mesh_path'].split(',', 1)[1]) == mesh.source
            if self.check_submission:
                self.check_submission(uploaded.stem)
            if self.failure:
                raise self.failure
            assert OpenAIMeshBackend.build_alias_params(self, params) == {'input_no_fingers': self.no_fingers}
            assert 'no_fingers' not in params
            if self.delivered_rig == 'generic':
                self._meta.files = [{'name': 'test_articulationxl.fbx', 'kind': 'file', 'mime': 'application/octet-stream'}]
                return [b'Kaydara FBX Binary\x00' + b'fixture']
            self._meta.files = [{'name': 'test_rigged.glb', 'kind': 'file', 'mime': 'application/octet-stream'}]
            return [fixture_glb(True)]
        self._meta.files = [{'name': 'test_00001_.glb', 'kind': 'file', 'mime': 'application/octet-stream'}]
        assert 'no_fingers' not in params
        if self.check_delivery:
            self.check_delivery()
        return [self.source]

    def fetch_job(self, job_id):
        return {'status': 'done', 'job_id': job_id, 'rig': 'none', 'model': '',
                'progress': 1, 'elapsed_s': 1, 'error': '',
                'files': [{'name': 'recovered-source.glb', 'kind': 'file', 'mime': 'application/octet-stream'}],
                'blobs': [self.source]}

    _generate = lambda self, prompt, negative, params: []
    _file_slot = ''
    no_fingers = True
    _remember_input = lambda self, raw: ''


def assert_static(signature, *, error=False, routed=True):
    """Missing early publication or stale backups violate the visible contract."""
    public = root/f'{signature}.glb'
    assert public.is_file(), 'validated mesh must be publicly served before rig submission'
    assert public.read_bytes() == mesh.source, 'served mesh must be the newest unrigged delivery'
    assert (root/'unrigged'/public.name).read_bytes() == mesh.source
    metadata = read_sidecar(public)
    assert metadata['rig'] == 'none' and metadata['mesh_backend'] == 'mesh'
    assert metadata['pieces'] == {'body': 'new-piece'} and metadata['items'] == ['new-item']
    assert metadata['source_image'] == src.name
    if routed:
        assert metadata['mesh_route_meta']['routing']['occasion'] in ('mesh_humanoid', 'mesh_creature')
    assert not (root/f'{signature}.fbx').exists(), 'old FBX must not shadow the static GLB'
    for folder in ('low', 'low/raw', 'low/prerig', 'raw', 'prerig'):
        for path in (root/folder).glob(f'{signature}.*'):
            if path.suffix == '.json':
                assert read_sidecar(path)['rig'] == 'none'
            elif path.suffix == '.glb':
                assert path.read_bytes() == mesh.source, f'old rig remains in {folder}'
            else:
                raise AssertionError(f'old rig artifact remains: {path}')
    with patch.object(model3d, 'current_outfit_state', return_value=({'body': 'new-piece'}, ['new-item'], signature)):
        served, match = model3d.find_model3d_serving('demo')
        assert served == public and match == 'exact'
        info = model3d.get_model3d_info('demo')['model']
        assert info['rig'] == 'none' and info['has_unrigged_source']
        assert info['filename'] == public.name and info['tiers'] == ['full']
        if error:
            assert metadata.get('rig_error') and info['rig_error'] == metadata['rig_error']
        else:
            assert not metadata.get('rig_error') and not info.get('rig_error')

def service(*backends):
    svc = object.__new__(ImageService)
    svc._pool = BackendPool(list(backends), agent_instances_provider=lambda name: {})
    return svc


rules = {}
routing._rules = lambda occasion: rules.get(occasion, [])
routing._character_switches = lambda character: {}
mesh = Fake('mesh', 'img2mesh', 'none')
high = Fake('rig-high', 'mesh2rig', 'mixamo', 2)
low = Fake('rig-low', 'mesh2rig', 'mixamo', 1)
creature = Fake('creature', 'mesh2rig', 'generic')
svc = service(mesh, high, low, creature)
for occasion in ('rig_humanoid', 'rig_creature'):
    try:
        routing.resolve_image_route(occasion, pool=svc.pool)
        raise AssertionError('empty rig chain must fail')
    except routing.NoRouteError as exc:
        assert occasion in str(exc) and '/admin/settings → Media Generation → Routing' in str(exc)
    overview = routing.explain_occasion(occasion, pool=svc.pool)
    assert overview['resolved'] is None and overview['via'] == 'none'
rules.update(rig_humanoid=['rig-low'], rig_creature=['creature'])
for occasion, expected in (('rig_humanoid', low), ('rig_creature', creature), ('mesh_humanoid', mesh), ('mesh_creature', mesh), ('mesh_object', mesh), ('mesh_building', mesh)):
    assert routing.resolve_image_route(occasion, pool=svc.pool).backend is expected
rules['rig_humanoid'] = ['mesh']
try:
    routing.resolve_image_route('rig_humanoid', pool=svc.pool)
    raise AssertionError('configured wrong-kind chain must fail')
except routing.NoRouteError:
    pass
rules['rig_humanoid'] = ['rig-high', 'rig-low']
seen = []
from app.imagegen.base import BackendFailedError

def failed_once(b):
    seen.append(b.name)
    if b is high:
        raise BackendFailedError(b.name, RuntimeError('failure'))
    return b.name
value, route = routing.run_routed('rig_humanoid', failed_once, pool=svc.pool)
assert seen == ['rig-high', 'rig-low'] and route.is_fallback
seen.clear()
try:
    routing.run_routed('rig_humanoid', lambda b: (_ for _ in ()).throw(BackendBusyError('busy')), pool=svc.pool)
    raise AssertionError('busy must propagate')
except BackendBusyError:
    pass
print('PASS explicit rig chains, NoRouteError, failed fallback, busy propagation')

root = Path(_tmp.name) / 'models'
root.mkdir()
src = Path(_tmp.name) / 'source.png'
src.write_bytes(color_png())
executor = ThreadPoolExecutor(max_workers=1)
worker = threading.local()
events = []


def channel(backend, gen_fn, **kwargs):
    assert not getattr(worker, 'inside', False), 'nested single-slot submission'
    def run():
        worker.inside = True
        events.append(('start', backend.name))
        try:
            return gen_fn()
        finally:
            events.append(('end', backend.name))
            worker.inside = False
    return executor.submit(run).result(timeout=5)


# Hand-derived delivery checks: the wrong FBX is a healthy response, so it
# skips to the next chain entry without a cooldown or publishing wrong bytes.
(root/'unrigged').mkdir()
delivery_source = root/'unrigged/delivery.glb'
delivery_source.write_bytes(fixture_glb())
high.delivered_rig = 'generic'
with patch.object(svc, 'run_on_backend_channel', side_effect=channel):
    result = svc.generate_rig(str(delivery_source), str(root/'delivery.glb'), 'mixamo')
    assert result['ok'] and result['backend'] == 'rig-low'
    assert result['fallback_from']['intended_spec'] == 'rig-high'
    assert not high.in_cooldown() and high.available
    assert len(high.calls) == len(low.calls) == 1
    result = svc.generate_rig(str(delivery_source), str(root/'wrong.glb'), 'mixamo', backend_glob='rig-high')
    assert not result['ok'] and "delivered rig 'generic'" in result['error']
    assert not (root/'wrong.glb').exists() and not high.in_cooldown()
    assert len(low.calls) == 1, 'explicit mismatch has no fallback'
    # Job rig overrides detectable bytes, including an unknown nonempty value.
    with patch.object(Fake, 'last_result_rig', property(lambda self: 'generic' if self is low else None), create=True):
        result = svc.generate_rig(str(delivery_source), str(root/'declared-wrong.glb'), 'mixamo', backend_glob='rig-low')
        assert not result['ok'] and not low.in_cooldown()
    with patch.object(Fake, 'last_result_rig', property(lambda self: ''), create=True):
        result = svc.generate_rig(str(delivery_source), str(root/'blank-rig.glb'), 'mixamo', backend_glob='rig-low')
        assert not result['ok'] and not low.in_cooldown(), 'a present blank rig must not be inferred'
from app.imagegen.service import _delivered_mesh_rig
assert _delivered_mesh_rig([{'name': 'source.glb', 'blob': fixture_glb()}]) == 'none'
assert _delivered_mesh_rig([{'name': 'source.glb', 'blob': fixture_glb()}, {'name': 'test_rigged.glb', 'blob': fixture_glb(True)}]) == 'mixamo'
assert _delivered_mesh_rig([{'name': 'test_articulationxl_00001_.fbx', 'blob': b'FBX'}]) == 'generic'
assert _delivered_mesh_rig([{'name': 'rigged.glb', 'blob': fixture_glb(True)}]) == 'mixamo'
assert _delivered_mesh_rig([{'name': 'rigged.glb', 'blob': fixture_glb(True)}], '') == ''
assert _delivered_mesh_rig([{'name': 'rigged.glb', 'blob': fixture_glb(True)}], 'generic') == 'generic'
assert _delivered_mesh_rig([{'name': 'source.glb', 'blob': fixture_glb()}], 'unknown-rig') == 'unknown-rig'
from app.core.mesh_source import validate_source
assert 'combined mesh+rig aliases are not supported' in '; '.join(validate_source(fixture_glb(True))['errors'])
# Even when the main artifact is unrigged, a skinned sibling or LOD proves
# this is an unsupported combined delivery; no output is published.
for extra_name in ('extra_rigged.glb', 'source_2000.glb'):
    mixed = [{'name': 'source_00001_.glb', 'kind': 'model', 'blob': fixture_glb()},
             {'name': extra_name, 'kind': 'model', 'blob': fixture_glb(True)}]
    verdict = svc._store_mesh_files(mixed, 'none', str(root/'combined.glb'), 'mesh')
    assert not verdict['ok'] and 'combined mesh+rig aliases are not supported' in verdict['error']
    assert not (root/'combined.glb').exists()
high.delivered_rig = 'mixamo'
high.calls.clear()
low.calls.clear()
events.clear()
print('PASS delivered rig mismatch retries without cooldown, explicit mismatch fails, job rig takes precedence')

# Real orchestration and publication; Blender postprocessing is outside this
# check and is covered by the existing model/LOD smokes.
from contextlib import ExitStack
with ExitStack() as stack:
    stack.enter_context(patch('app.imagegen.service.get_image_service', return_value=svc))
    from app.core import llm_queue
    class Queue:
        def submit_gpu_task(self, provider_name, callable_fn, **kwargs):
            backend = next(b for b in svc.pool.backends if b.name == provider_name)
            return channel(backend, callable_fn, **kwargs)
    stack.enter_context(patch.object(llm_queue, 'get_llm_queue', return_value=Queue()))
    stack.enter_context(patch.object(model3d, 'get_model3d_dir', side_effect=lambda name: getattr(model3d._staging, 'directories', {}).get(name) or root))
    stack.enter_context(patch.object(model3d, 'find_ref_image', return_value=src))
    stack.enter_context(patch.object(model3d, 'get_model3d_options', return_value={'no_fingers': False}))
    stack.enter_context(patch.object(model3d, '_ref_manifest', return_value={'pieces': {'body': 'new-piece'}, 'items': ['new-item']}))
    stack.enter_context(patch.object(model_refs, 'enabled_tpose_views', return_value=[]))
    for fn in ('_auto_retexture', '_auto_normalize', '_auto_extension_rig', '_attach_measurement', 'request_lod'):
        stack.enter_context(patch.object(model3d, fn, return_value=None))
    low.check_submission = creature.check_submission = assert_static
    for rig, rig_name in (('mixamo', 'rig-low'), ('generic', 'creature')):
        rules.clear()
        rules.update({'mesh_humanoid': ['mesh'], 'mesh_creature': ['mesh'], 'rig_humanoid': ['rig-low'], 'rig_creature': ['creature']})
        with patch.object(model3d, 'required_rig', return_value=rig):
            result = model3d.generate_for_current_outfit('demo', signature=rig, force=True)
        assert result['ok'], result
        target = Path(result['path'])
        assert (root / 'unrigged' / f'{rig}.glb').read_bytes() == fixture_glb()
        assert (root / 'raw' / target.name).is_file()
        meta = read_sidecar(target)
        assert meta['mesh_backend'] == 'mesh' and meta['rig_backend'] == rig_name
        assert meta['mesh_route_meta']['routing']['occasion'] == ('mesh_humanoid' if rig == 'mixamo' else 'mesh_creature')
        assert meta['rig_route_meta']['routing']['occasion'] == ('rig_humanoid' if rig == 'mixamo' else 'rig_creature')
        if rig == 'generic':
            tex = target.with_suffix('.png').read_bytes()
            assert validate_fbx(target.read_bytes(), tex)['ok']
            assert Image.open(io.BytesIO(tex)).getpixel((0, 0)) == (0, 0, 255)
            assert Image.open(root / 'unrigged' / f'{rig}.png').getpixel((0, 0)) == (255, 0, 0)
    low.check_submission = creature.check_submission = None
    assert events == [('start', 'mesh'), ('end', 'mesh'), ('start', 'rig-low'), ('end', 'rig-low'), ('start', 'mesh'), ('end', 'mesh'), ('start', 'creature'), ('end', 'creature')]
    before = len(low.calls)
    with patch('app.imagegen.service.media_generation_enabled', return_value=False):
        for fn in (lambda: svc.generate_mesh(str(src), str(root/'disabled.glb')),
                   lambda: svc.generate_rig(str(root/'unrigged/mixamo.glb'), str(root/'disabled-rig.glb'), 'mixamo')):
            try:
                fn()
                raise AssertionError('master switch must refuse generation')
            except MediaGenerationDisabled:
                pass
    assert len(low.calls) == before

    assert not svc.generate_rig(str(root/'unrigged/mixamo.glb'), str(root/'wrong.glb'), 'mixamo', backend_glob='creature')['ok']
    assert len(low.calls) == before
    huge = root/'huge.glb'
    with huge.open('wb') as f:
        f.truncate(64*1024*1024 + 1)
    assert '413' in svc.generate_rig(str(huge), str(root/'huge-rig.glb'), 'mixamo')['error']
    huge.unlink()
    # A distinct valid delivery replaces both an old rig and its old source
    # before a busy rigger runs. First generation follows the same contract.
    old_rig = (root/'mixamo.glb').read_bytes()
    old_source = (root/'unrigged/mixamo.glb').read_bytes()
    for folder in ('raw', 'prerig', 'low', 'low/raw', 'low/prerig'):
        (root/folder).mkdir(parents=True, exist_ok=True)
        (root/folder/'mixamo.glb').write_bytes(old_rig)
        (root/folder/'mixamo.json').write_text(json.dumps({'rig': 'mixamo'}))
    mesh.source = fixture_glb(revision='busy replacement')
    assert mesh.source != old_source and mesh.source != old_rig
    low.failure = BackendBusyError('rig channel busy')
    low.check_submission = assert_static
    before = len(low.calls)
    for signature in ('mixamo', 'failed'):
        try:
            with patch.object(model3d, 'required_rig', return_value='mixamo'):
                model3d.generate_for_current_outfit('demo', signature=signature, force=True)
            raise AssertionError('busy must survive orchestration')
        except BackendBusyError:
            pass
        assert_static(signature, error=True)
    assert len(low.calls) == before + 2 and not low.in_cooldown()
    from app.core.task_queue import get_task_queue
    with get_task_queue()._connect() as conn:
        assert conn.execute("SELECT count(*) FROM tasks WHERE task_type='model3d_generation' AND status='failed'").fetchone()[0] >= 2
    low.failure = None
    # Ordinary backend failure must retain the newest pair too, without a
    # routed backup or resurrection of the previous static/rigged generation.
    mesh.source = fixture_glb(revision='failed replacement')
    low.failure = RuntimeError('rig backend failed')
    before = len(low.calls)
    before_high = len(high.calls)
    for signature in ('mixamo', 'firstfailure'):
        try:
            with patch.object(model3d, 'required_rig', return_value='mixamo'):
                result = model3d.generate_for_current_outfit('demo', signature=signature, force=True)
            assert not result['ok']
        except (BackendFailedError, routing.NoRouteError):
            pass
        assert_static(signature, error=True)
        low._cooldown_until = 0
        low._available = True
    assert len(low.calls) == before + 2 and len(high.calls) == before_high
    low.failure = None
    low.check_submission = creature.check_submission = None
    # The gateway lookup, service artifact storage and character transaction
    # stay real. Only the external job download is supplied by the backend.
    saved_source = mesh.source
    before_rigs = len(low.calls) + len(creature.calls)
    for rig in ('mixamo', 'generic'):
        signature = f'recovery-{rig}'
        old_ext = '.glb' if rig == 'mixamo' else '.fbx'
        (root/f'{signature}{old_ext}').write_bytes(fixture_glb(True) if rig == 'mixamo' else b'old rigged FBX')
        (root/f'{signature}.json').write_text(json.dumps({'rig': rig}))
        for folder in ('raw', 'prerig', 'low', 'low/raw', 'low/prerig'):
            (root/folder).mkdir(parents=True, exist_ok=True)
            (root/folder/f'{signature}{old_ext}').write_bytes(b'old rigged backup')
        mesh.source = fixture_glb(revision=f'recovered {rig} source')
        with patch.object(model3d, 'required_rig', return_value=rig):
            result = model3d.fetch_job_for_current_outfit(
                'demo', 'mesh-recovery-job', backend_glob='mesh', signature=signature)
            assert result['status'] == 'stored', result
            assert_static(signature, routed=False)
        public_meta = read_sidecar(root/f'{signature}.glb')
        source_meta = read_sidecar(root/'unrigged'/f'{signature}.glb')
        for metadata in (public_meta, source_meta):
            assert metadata['job_id'] == 'mesh-recovery-job'
            assert metadata['source_filename'] == 'recovered-source.glb'
        if rig == 'generic':
            assert Image.open(root/'unrigged'/f'{signature}.png').getpixel((0, 0)) == (255, 0, 0)
        previous_public = (root/f'{signature}.glb').read_bytes()
        previous_source = (root/'unrigged'/f'{signature}.glb').read_bytes()
        mesh.source = b'not a valid GLB'
        with patch.object(model3d, 'required_rig', return_value=rig):
            invalid = model3d.fetch_job_for_current_outfit(
                'demo', 'invalid-mesh-job', backend_glob='mesh', signature=signature)
        assert invalid['status'] != 'stored'
        assert (root/f'{signature}.glb').read_bytes() == previous_public
        assert (root/'unrigged'/f'{signature}.glb').read_bytes() == previous_source
    assert len(low.calls) + len(creature.calls) == before_rigs, 'recovery must not start automatic rigging'
    mesh.source = saved_source

    # A real upload on the GPU worker publishes after generation's snapshot
    # but before its checkpoint. The invalidated mesh must never rig/publish.
    winner = fixture_glb(True, revision='concurrent upload wins')
    before_rigs = len(low.calls)
    def concurrent_upload():
        with patch.object(model3d, 'current_outfit_state', return_value=({}, [], 'checkpoint-race')):
            metadata = model3d.save_uploaded_model(
                'demo', 'concurrent.glb', winner, rig='mixamo', signature='checkpoint-race')
        assert metadata['rig'] == 'mixamo'
    mesh.check_delivery = concurrent_upload
    try:
        with patch.object(model3d, 'required_rig', return_value='mixamo'):
            try:
                result = model3d.generate_for_current_outfit('demo', signature='checkpoint-race', force=True)
                assert not result['ok']
            except RuntimeError:
                pass
    finally:
        mesh.check_delivery = None
    assert (root/'checkpoint-race.glb').read_bytes() == winner
    assert read_sidecar(root/'checkpoint-race.glb')['source'] == 'upload'
    assert not (root/'unrigged/checkpoint-race.glb').exists()
    assert len(low.calls) == before_rigs
    high.failure = RuntimeError('rig backend failed')
    before = len(low.calls)
    try:
        svc.generate_rig(str(root/'unrigged/mixamo.glb'), str(root/'explicit.glb'), 'mixamo', backend_glob='rig-high')
        raise AssertionError('explicit failure must propagate without fallback')
    except BackendFailedError:
        pass
    assert len(low.calls) == before
    high.failure = None
    bad_source = root/'already-rigged.glb'
    bad_source.write_bytes(fixture_glb(True))
    assert 'unrigged' in svc.generate_rig(str(bad_source), str(root/'bad-rig.glb'), 'mixamo')['error']
    bad_source.unlink()
executor.shutdown()
print('PASS two stages, sequential single-slot channel, upload payload, route sidecars, generic FBX/PNG and V correction')

# Export resolves sources, while raw/prerig remain private. A ZIP round trip
# must retain the same relative source path and bytes (decision 5.2).
import zipfile
pack = io.BytesIO()
files = export_files(root, ['mixamo', 'generic'])
assert root/'unrigged/generic.glb' in files and root/'unrigged/generic.png' in files
with zipfile.ZipFile(pack, 'w') as zf:
    for p in files:
        zf.writestr(p.relative_to(root).as_posix(), p.read_bytes())
restored = Path(_tmp.name)/'restored'
with zipfile.ZipFile(io.BytesIO(pack.getvalue())) as zf:
    zf.extractall(restored)
assert (restored/'unrigged/generic.glb').read_bytes() == fixture_glb()
model3d._purge_combination(root, 'generic')
assert not list((root/'unrigged').glob('generic.*'))
from app.core.media_cleanup import remove_owned_dir
assert remove_owned_dir(Path(_tmp.name), 'restored')
print('PASS source export round trip and combination/media purge')

# Exercise OpenAIMeshBackend._generate, including its job-start logging (MIA
# deliberately has no input_name), without replacing its request builder.
from app.imagegen.backends import openai_mesh
backend = OpenAIMeshBackend('rig-request', 'http://fake', 0, 'RIG_REQUEST_', model='mesh-mia')
backend.category = 'mesh2rig'
input_path = restored.parent/'fixture.glb'
input_path.write_bytes(fixture_glb())
payloads = []
with patch.object(openai_mesh, 'submit_job', side_effect=lambda b, url, payload, kind: payloads.append(payload) or 'job1'), \
        patch.object(openai_mesh, 'poll_job', return_value=[fixture_glb(True)]):
    backend.no_fingers = False
    assert backend._generate('', '', {'source_model_path': str(input_path)})
assert len(payloads) == 1 and payloads[0]['params'] == {'input_no_fingers': False}
assert 'images' not in payloads[0] and set(payloads[0]['files']) == {'input_mesh_path'}
print('PASS actual rig request builder and job-start path without input_name')

# The real character/Marketplace ZIP boundary copies the unrigged source and
# restores it at the path consumed by the model store, not just a synthetic ZIP.
from app.models.character import save_character_profile, get_character_dir
from app.core.character_io import export_character_to_zip, import_character_from_zip
assert save_character_profile('demo', {'name': 'demo', 'template': 'human'}, create_new=True)
char_models = get_character_dir('demo')/'model3d'
(char_models/'unrigged').mkdir(parents=True)
(char_models/'mixamo.glb').write_bytes(fixture_glb(True))
(char_models/'unrigged/mixamo.glb').write_bytes(fixture_glb())
(char_models/'unrigged/mixamo.json').write_text(json.dumps({'rig': 'none', 'signature': 'mixamo'}))
(char_models/'unrigged/mixamo.png').write_bytes(color_png())
real_pack = export_character_to_zip('demo')
with zipfile.ZipFile(io.BytesIO(real_pack)) as zf:
    assert {'files/model3d/unrigged/mixamo.glb', 'files/model3d/unrigged/mixamo.json', 'files/model3d/unrigged/mixamo.png'} <= set(zf.namelist())
import shutil
shutil.rmtree(char_models)
result = import_character_from_zip(real_pack, overwrite=True)
assert result['character'] == 'demo'
assert (char_models/'unrigged/mixamo.glb').read_bytes() == fixture_glb()
from app.core import outfit_cache_gc
files = outfit_cache_gc._mesh_files('demo')['mixamo']
assert char_models/'unrigged/mixamo.glb' in files
model3d._purge_combination(char_models, 'mixamo')
assert not list((char_models/'unrigged').glob('mixamo.*'))
print('PASS actual character/Marketplace export-import and GC collection/purge')

# Two boot migrations drop the declaration while preserving secret layers.
inst = Path(_tmp.name)/'boot-instance'
world_cfg = Path(_tmp.name)/'boot-world/config.json'
inst.mkdir()
world_cfg.parent.mkdir()
world_cfg.write_text('{}')
(inst/'config.json').write_text(json.dumps({'image_generation': {'backends': [{'name': 'rigger', 'api_type': 'openai_mesh', 'category': 'mesh2rig', 'mesh_rig': 'generic', 'api_url': 'http://fake', 'model': 'mesh-rig-unirig'}]}}))
(inst/'secrets.json').write_text(json.dumps({'image_generation': {'backends': {'rigger': {'api_key': 'test-secret'}}}}))
assert config.migrate_file(world_cfg, instance_path=inst/'config.json')
public = json.loads((inst/'config.json').read_text())
secret_text = (inst/'secrets.json').read_text()
assert 'test-secret' not in (inst/'config.json').read_text()
assert len(public['image_generation']['backends']) == 1
assert 'mesh_rig' not in public['image_generation']['backends'][0]
assert public['image_generation']['routing']['rig_creature'] == ['rigger']
config.load(world_cfg, instance_path=inst/'config.json')
assert all(b['api_key'] == 'test-secret' for b in config.get('image_generation.backends'))
assert not config.migrate_file(world_cfg, instance_path=inst/'config.json')
assert (inst/'secrets.json').read_text() == secret_text
print('PASS two actual boot migrations and separate secret layering')
