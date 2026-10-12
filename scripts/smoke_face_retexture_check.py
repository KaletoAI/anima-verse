#!/usr/bin/env python3
"""P1 source eligibility, derived by hand from plan sections 3 and 4.

One indexed triangle with three UVs and an embedded opaque RGB PNG passes.
Two primitives, skin, morph, animation, external image/buffer, required Draco,
BLEND, missing indices and KTX2 each yield bad_source. An absent source yields
no_source; a changed photo yields photo_changed, an old sidecar without a hash
only warns photo_unverified. A reference re-render during generation yields
photo_changed because the uploaded bytes retain their hash. Fetch by job ID
has unknown photo provenance and only warns photo_unverified. No backend or real world is used.
Usage: ./.venv/bin/python scripts/smoke_face_retexture_check.py
"""
import copy
import hashlib
import io
import json
import struct
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from app.core import paths


def photo():
    out = io.BytesIO()
    Image.new('RGBA', (16, 16), (200, 20, 30, 128)).save(out, 'PNG')
    return out.getvalue()


def fixture_doc():
    image = photo()
    binary = struct.pack('<3H', 0, 1, 2) + b'\0\0' + struct.pack('<6f', 0, 0, 1, 0, 0, 1) + image
    doc = {'asset': {'version': '2.0'}, 'buffers': [{'byteLength': len(binary)}],
           'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': 6},
                           {'buffer': 0, 'byteOffset': 8, 'byteLength': 24},
                           {'buffer': 0, 'byteOffset': 32, 'byteLength': len(image)}],
           'accessors': [{'bufferView': 0, 'componentType': 5123, 'type': 'SCALAR', 'count': 3},
                         {'bufferView': 1, 'componentType': 5126, 'type': 'VEC2', 'count': 3}],
           'meshes': [{'primitives': [{'indices': 0, 'attributes': {'TEXCOORD_0': 1}, 'material': 0}]}],
           'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}],
           'textures': [{'source': 0}], 'images': [{'bufferView': 2, 'mimeType': 'image/png'}]}
    return doc, binary


def glb(doc=None, binary=None):
    if doc is None:
        doc, binary = fixture_doc()
    raw = json.dumps(doc).encode()
    raw += b' ' * (-len(raw) % 4)
    binary += b'\0' * (-len(binary) % 4)
    body = struct.pack('<II', len(raw), 0x4e4f534a) + raw + struct.pack('<II', len(binary), 0x004e4942) + binary
    return b'glTF' + struct.pack('<II', 2, len(body) + 12) + body


def main():
    with tempfile.TemporaryDirectory() as tmp:
        paths.init(tmp)
        from app.core import face_retexture, model3d
        root = Path(tmp) / 'characters' / 'demo' / 'model3d'
        root.mkdir(parents=True)
        (root / 'unrigged').mkdir()
        refs = root.parent / 'model_refs'
        refs.mkdir()
        sig = '0123456789ab'
        source = root / 'unrigged' / f'{sig}.glb'
        (root / f'{sig}.glb').write_bytes(glb())
        source.write_bytes(glb())
        image = refs / f'tpose_{sig}.png'
        image.write_bytes(photo())
        with patch.object(model3d, 'required_rig', return_value='mixamo'):
            verdict = face_retexture.check('demo', sig)
            assert verdict['ok'], verdict
            assert [w['code'] for w in verdict['warnings']] == ['photo_unverified']
            source.with_suffix('.json').write_text(json.dumps({'source_image': image.name, 'source_image_sha256': '0' * 64}))
            assert 'photo_changed' in [p['code'] for p in face_retexture.check('demo', sig)['problems']]
            source.with_suffix('.json').write_text(json.dumps({'source_image': image.name, 'source_image_sha256': hashlib.sha256(photo()).hexdigest()}))
            assert face_retexture.check('demo', sig)['ok']
            mutations = {
                'two primitives': lambda d: d['meshes'][0]['primitives'].append(copy.deepcopy(d['meshes'][0]['primitives'][0])),
                'skin': lambda d: d.update(skins=[{'joints': []}]),
                'morph': lambda d: d['meshes'][0]['primitives'][0].update(targets=[{}]),
                'animation': lambda d: d.update(animations=[{}]),
                'external image': lambda d: d['images'][0].update(uri='external.png'),
                'external buffer': lambda d: d['buffers'][0].update(uri='external.bin'),
                'Draco': lambda d: d.update(extensionsRequired=['KHR_draco_mesh_compression']),
                'BLEND': lambda d: d['materials'][0].update(alphaMode='BLEND'),
                'no indices': lambda d: d['meshes'][0]['primitives'][0].pop('indices'),
                'KTX2': lambda d: d['images'][0].update(mimeType='image/ktx2'),
            }
            for label, mutate in mutations.items():
                doc, binary = fixture_doc()
                mutate(doc)
                source.write_bytes(glb(doc, binary))
                verdict = face_retexture.check('demo', sig)
                assert 'bad_source' in [p['code'] for p in verdict['problems']], (label, verdict)
            source.write_bytes(glb())
            delivered = root / '.delivered.glb'
            delivered.write_bytes(glb())
            uploaded = photo()
            def mesh_job(**kwargs):
                assert Path(kwargs['source_image_path']).read_bytes() == uploaded
                image.write_bytes(face_retexture.flatten_photo(uploaded))
                assert Path(kwargs['source_image_path']).read_bytes() == uploaded
                return {'ok': True, 'path': str(delivered), 'backend': 'fake'}
            from unittest.mock import Mock
            service = Mock()
            service.generate_mesh.side_effect = mesh_job
            service.generate_rig.return_value = {'ok': False, 'error': 'fake rig failure'}
            image.write_bytes(uploaded)
            with patch('app.imagegen.service.get_image_service', return_value=service), \
                    patch('app.core.task_queue.get_task_queue', return_value=Mock()), \
                    patch('app.core.model_refs.enabled_tpose_views', return_value=[]):
                assert not model3d.generate_for_current_outfit('demo', signature=sig, force=True)['ok']
                metadata = model3d._read_sidecar(source)
                assert metadata['source_image_sha256'] == hashlib.sha256(uploaded).hexdigest()
                assert 'photo_changed' in [p['code'] for p in face_retexture.check('demo', sig)['problems']]
                service.fetch_mesh_job.return_value = {'status': 'stored', 'rig': 'none',
                                                       'path': str(delivered), 'backend': 'fake'}
                assert model3d.fetch_job_for_current_outfit('demo', 'fake-job', signature=sig)['status'] == 'stored'
                assert not model3d._read_sidecar(source).get('source_image_sha256')
                verdict = face_retexture.check('demo', sig)
                assert verdict['ok'], verdict
                assert 'photo_unverified' in [w['code'] for w in verdict['warnings']]
            source.unlink()
            assert 'no_source' in [p['code'] for p in face_retexture.check('demo', sig)['problems']]
            flattened = Image.open(io.BytesIO(face_retexture.flatten_photo(photo())))
            assert flattened.mode == 'RGB'
            assert flattened.getpixel((0, 0)) == (227, 137, 142)
    print('PASS: face retexture eligibility (10 invalid GLBs, photo provenance, white RGB flatten)')


if __name__ == '__main__':
    main()
