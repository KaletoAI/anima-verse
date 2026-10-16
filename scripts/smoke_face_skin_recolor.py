#!/usr/bin/env python3
"""Hand-derived: a 16² blue atlas becomes green outside the triangular face
(4,4),(8,4),(4,8), red inside (15 raster texels). Body has two triangles,
face one, regardless of primitive order. Recolour changes all 256 base texels.
Equal largest partitions and a face using the body atlas are ambiguous.
The v1.2 bake must remain byte-identical to the pre-change implementation.
Usage: .venv/bin/python scripts/smoke_face_skin_recolor.py
"""
import io
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from smoke_face_retexture_bake import fixture, glb, png
from app.core.face_retexture import bake_face_texture, _primitive_basecolor, face_texture_preserved
from app.core.model_validate import parse_glb
from app.core.face_photo_adjust import validated_params, NEUTRAL
from app.imagegen.backends.openai_mesh import OpenAIMeshBackend


def recolored_fixture(size=16):
    doc, binary = fixture(True)
    binary += b'\0' * (-len(binary) % 4)
    raw = png((40, 120, 60, 123), size)
    doc['bufferViews'].append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': len(raw)})
    binary += raw
    doc['images'].append({'bufferView': len(doc['bufferViews'])-1, 'mimeType': 'image/png'})
    doc['textures'].append({'source': 2})
    doc['materials'].append({'pbrMetallicRoughness': {'baseColorTexture': {'index': 2}}})
    doc['meshes'][0]['primitives'][1]['material'] = 2
    doc['meshes'][0]['primitives'].reverse()
    doc['buffers'][0]['byteLength'] = len(binary)
    return doc, binary


def main():
    assert validated_params({})['skin_recolor'] == 1
    assert NEUTRAL['skin_recolor'] == 0
    for value in (False, float('nan'), -.01, 1.01):
        try:
            validated_params({'skin_recolor': value})
        except ValueError:
            pass
        else:
            raise AssertionError(value)
    backend = OpenAIMeshBackend('face', 'http://gateway.invalid', 0, 'SMOKE_SKIN_')
    backend.category = 'face_retexture'
    controls = {'light_balance': .4, 'tone_match': .65, 'brightness': .85, 'skin_recolor': .35}
    for supported in (False, True):
        backend._face_schema = (True, (), '', frozenset(set(controls) - (set() if supported else {'skin_recolor'})))
        assert backend.skin_recolor_supported() is supported
        assert backend.build_alias_params(controls) == {k: v for k, v in controls.items() if supported or k != 'skin_recolor'}
    source = glb(*fixture())
    for size in (16, 8):
        masks = []
        baked, meta = bake_face_texture(source, glb(*recolored_fixture(size)), dilate_px=0, replacement_masks=masks)
        parsed = parse_glb(baked)
        pixels = np.array(Image.open(io.BytesIO(_primitive_basecolor(parsed, parsed['gltf']['meshes'][0]['primitives'][0])[1])))
        expected = np.full((16,16,4), (40 if size == 16 else 39,120,60,123), dtype=np.uint8)
        mask = np.zeros((16,16), dtype=bool)
        for y in range(4,9):
            mask[y,4:13-y] = True
        expected[mask,:3] = (240,10,20)
        assert np.array_equal(pixels, expected)
        assert np.array_equal(masks[0], mask) and mask.sum() == 15
        assert meta['body_recolored'] and meta['body_texels_recolored'] == 256
        assert face_texture_preserved(baked, baked, original_glb=source, bake_meta=meta)
        # A later rig may alter only the body: face preservation still passes.
        # Reverting the face itself must fail even with a recoloured body.
        import copy
        for lose_face in (False, True):
            doc = copy.deepcopy(parsed['gltf'])
            changed = pixels.copy()
            changed[mask if lose_face else ~mask, :3] = (10,20,200)
            stream = io.BytesIO()
            Image.fromarray(changed).save(stream, 'PNG')
            view = doc['bufferViews'][doc['images'][0]['bufferView']]
            binary = parsed['bin'][:view['byteOffset']] + stream.getvalue()
            view['byteLength'] = len(stream.getvalue())
            doc['buffers'][0]['byteLength'] = len(binary)
            assert face_texture_preserved(baked, glb(doc, binary), original_glb=source, bake_meta=meta) is (not lose_face)
    # Frozen pre-change bake hashes prove byte identity; pixel expectations
    # above are derived independently from the triangular coverage.
    import hashlib
    legacy_hashes = {
        (0, False): '47c7f46b56b70a078182424c8d9f1b92505ced6be834c4bfdad6e5b65b9548f5',
        (0, True): '4acdfb85c793578f6abb43d7c6c5e5e7b0366591479b2de2beca37f9cd69796c',
        (1, False): '36d4cfdcc78e7fd0267366990147ae8abaa2db3ac671759167e74ba57bb4730b',
        (1, True): 'a6f43c306006023b92c62b697ff01d6600cb2c41a0ce69788596021a8c6c0755',
        (4, False): '9b5690ec1c5f538827bb886e39817fc20bdc1fc72c43b10e8aa3f5e721e2cfd7',
        (4, True): 'f38a687a547fa515cde127ac911e9e6c01a4bd5bec3f7fb2f7a05920401b48e7',
    }
    for (dilation, transparent), digest in legacy_hashes.items():
        legacy = glb(*fixture(True, transparent=transparent))
        assert hashlib.sha256(bake_face_texture(source, legacy, dilate_px=dilation)[0]).hexdigest() == digest
    # Equal largest primitives cannot identify a unique body.
    doc, binary = fixture(True)
    doc['accessors'][3]['count'] = 3
    sd, sb = fixture()
    sd['accessors'][0]['count'] = 6
    try:
        bake_face_texture(glb(sd, sb), glb(doc, binary))
    except ValueError as exc:
        assert 'exactly one body' in str(exc)
    else:
        raise AssertionError('Ambiguous body accepted')
    doc, binary = recolored_fixture()
    doc['meshes'][0]['primitives'][1]['material'] = 2
    try:
        bake_face_texture(source, glb(doc,binary))
    except ValueError as exc:
        assert 'face texture' in str(exc)
    else:
        raise AssertionError('Identical body/face atlas accepted')
    print('PASS: skin defaults/validation/capability, body selection, recoloured bake, face-only mask and rerig')


if __name__ == '__main__':
    main()
