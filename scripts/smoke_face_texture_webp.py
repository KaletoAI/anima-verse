#!/usr/bin/env python3
"""Hand-derived WebP contract expectations, without a world or external assets.

Usage: ./.venv/bin/python scripts/smoke_face_texture_webp.py

Nine indices give three triangles: one face and two repeated body triangles.
Seven interleaved POSITION/UV vertices put face pixel corners at
(4,4),(8,4),(4,8) on a 16x16 atlas; body starts at (12,12).
One-pixel dilation turns (5,5) and (3,5) red (240,10,20), while (15,15)
stays blue (10,20,200). All 256 source alpha values stay 123 except
(5,5), whose alpha stays 200. MR is RGB (0,128,255) and byte-identical.
WebP textures 0/1 resolve to images 0/1; bake adds plain PNG texture 2,
copying sampler 0. Both hub materials retain MR texture index 1.
Geometry arrays and both original WebP images remain unchanged.
For VP8, VP8L and VP8X headers a 13x7 image must report (13,7).
Every malformed case must return ok=False and a nonempty error list.
"""
import copy
import io
import os
import json
import struct
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from app.core import model_validate as mv
from app.core.mesh_source import source_basecolor, validate_source, validate_face_source


def png(color):
    out = io.BytesIO()
    Image.new('RGBA', (16,16), color).save(out, 'PNG')
    return out.getvalue()


def webp(color):
    image = Image.new('RGBA' if len(color) == 4 else 'RGB', (16,16), color)
    if len(color) == 4:
        image.putpixel((5,5), (10,20,200,200))
    out = io.BytesIO()
    image.save(out, format='WEBP', lossless=True, exact=True)
    return out.getvalue()


def glb(doc, binary):
    raw = json.dumps(doc).encode()
    raw += b' ' * (-len(raw) % 4)
    binary += b'\0' * (-len(binary) % 4)
    return (struct.pack('<III', 0x46546c67, 2, 28 + len(raw) + len(binary))
            + struct.pack('<I4s', len(raw), b'JSON') + raw
            + struct.pack('<I4s', len(binary), b'BIN\0') + binary)


def fixture(hub=False):
    binary = bytearray()
    views = []
    def add(raw, **extra):
        binary.extend(b'\0' * (-len(binary) % 4))
        views.append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': len(raw), **extra})
        binary.extend(raw)
        return len(views) - 1
    add(struct.pack('<9H', 0, 1, 2, 4, 5, 6, 4, 5, 6))
    add(b''.join(struct.pack('<5f', *row) for row in
                [(0,0,0,.25,.25), (1,0,0,.5,.25), (0,1,0,.25,.5), (1,1,0,.75,.75), (2,0,0,.75,.75), (3,0,0,.875,.75), (2,1,0,.75,.875)]), byteStride=20)
    add(webp((10, 20, 200, 123)))
    add(webp((0, 128, 255)))
    doc = {'asset': {'version': '2.0'}, 'bufferViews': views,
           'accessors': [{'bufferView': 0, 'componentType': 5123, 'type': 'SCALAR', 'count': 9},
                         {'bufferView': 1, 'componentType': 5126, 'type': 'VEC3', 'count': 7},
                         {'bufferView': 1, 'byteOffset': 12, 'componentType': 5126, 'type': 'VEC2', 'count': 7}],
           'meshes': [{'primitives': [{'indices': 0, 'attributes': {'POSITION': 1, 'TEXCOORD_0': 2}, 'material': 0}]}],
           'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}],
           'extensionsUsed': ['EXT_texture_webp'], 'extensionsRequired': ['EXT_texture_webp'],
           'samplers': [{}],
           'textures': [{'sampler': 0, 'extensions': {'EXT_texture_webp': {'source': 0}}},
                        {'extensions': {'EXT_texture_webp': {'source': 1}}}],
           'images': [{'bufferView': 2, 'mimeType': 'image/webp'}, {'bufferView': 3, 'mimeType': 'image/webp'}]}
    doc['materials'][0]['alphaMode'] = 'OPAQUE'
    doc['materials'][0]['pbrMetallicRoughness']['metallicRoughnessTexture'] = {'index': 1}
    if hub:
        image_view = add(png((240,10,20,255)))
        doc['images'].append({'bufferView': image_view, 'mimeType': 'image/png'})
        doc['textures'].append({'source': 2})
        doc['materials'].append({'pbrMetallicRoughness': {'baseColorTexture': {'index': 2}, 'metallicRoughnessTexture': {'index': 1}}})
        doc['accessors'][0]['count'] = 3
        doc['accessors'].append({'bufferView': 0, 'byteOffset': 6, 'componentType': 5123, 'type': 'SCALAR', 'count': 6})
        face = doc['meshes'][0]['primitives'][0]
        body = copy.deepcopy(face)
        face['material'] = 1
        body['indices'] = 3
        doc['meshes'][0]['primitives'] = [body, face]
    doc['buffers'] = [{'byteLength': len(binary)}]
    return doc, bytes(binary)


def image_bytes(parsed, index):
    view = parsed['gltf']['bufferViews'][parsed['gltf']['images'][index]['bufferView']]
    start = view.get('byteOffset', 0)
    return parsed['bin'][start:start + view['byteLength']]


def pixels(raw):
    with Image.open(io.BytesIO(raw)) as image:
        return np.array(image.convert('RGBA'))


def refused(label, doc, binary):
    verdict = mv.face_texture_geometry(glb(doc, binary), original=True)
    assert not verdict['ok'] and verdict['errors'], (label, verdict)


def main():
    doc, binary = fixture()
    source = glb(doc, binary)
    verdict = mv.face_texture_geometry(source, original=True)
    assert verdict['ok'] and verdict['triangles'] == 3, verdict
    assert validate_face_source(source, original=True)['ok']
    static = mv.validate_static_glb(source)
    assert static['ok'] and not any('size could not be read' in w for w in static['warnings']), static
    assert [mv.texture_image_index(doc, t) for t in doc['textures']] == [0,1]
    parsed = mv.parse_glb(source)
    assert [i['size'] for i in parsed['images']] == [(16,16), (16,16)]
    # Exercise all three header layouts independently of the lossless fixture.
    for mode, lossless, kind in [('RGB', False, b'VP8 '),
                                 ('RGB', True, b'VP8L'), ('RGBA', False, b'VP8X')]:
        out = io.BytesIO()
        Image.new(mode, (13,7), (10,20,200,123) if mode == 'RGBA' else (10,20,200)).save(
            out, 'WEBP', lossless=lossless, exact=True)
        raw = out.getvalue()
        assert raw[12:16] == kind
        assert mv._image_size(raw) == (13,7)
    print('OK: UniForge source, triangle count and VP8/VP8L/VP8X sizes')
    from app.core.face_retexture import bake_face_texture, face_texture_preserved, _accessor_array
    hd, hb = fixture(True)
    hub = glb(hd, hb)
    assert mv.face_texture_geometry(hub)['ok']
    for material in hd['materials']:
        assert material['pbrMetallicRoughness']['metallicRoughnessTexture']['index'] == 1
    baked, info = bake_face_texture(source, hub, dilate_px=1)
    result = mv.parse_glb(baked)
    gd = result['gltf']
    pbr = gd['materials'][0]['pbrMetallicRoughness']
    assert pbr['baseColorTexture']['index'] == 2
    texture = gd['textures'][2]
    assert 'extensions' not in texture and texture['sampler'] == 0
    index = mv.texture_image_index(gd, texture)
    assert gd['images'][index]['mimeType'] == 'image/png'
    actual, expected = pixels(image_bytes(result, index)), pixels(image_bytes(parsed, 0))
    assert tuple(actual[5,5,:3]) == (240,10,20)
    assert tuple(actual[5,3,:3]) == (240,10,20)
    assert np.array_equal(actual[15,15,:3], expected[15,15,:3])
    assert np.array_equal(actual[...,3], expected[...,3])
    assert actual[5,5,3] == 200 and actual[15,15,3] == 123
    assert pbr['metallicRoughnessTexture']['index'] == 1
    assert image_bytes(result, mv.texture_image_index(gd, gd['textures'][1])) == image_bytes(parsed, 1)
    assert np.all(pixels(image_bytes(result, 1))[...,:3] == (0,128,255))
    assert gd['textures'][:2] == doc['textures'] and gd['images'][:2] == doc['images']
    assert image_bytes(result, 0) == image_bytes(parsed, 0)
    for key in ('extensionsUsed', 'extensionsRequired'):
        assert gd[key] == ['EXT_texture_webp']
    for index in (0,1,2):
        assert np.array_equal(_accessor_array(parsed, index), _accessor_array(result, index))
    assert validate_source(baked)['ok']
    assert mv.face_texture_geometry(baked, original=True)['ok']
    assert face_texture_preserved(baked, baked, original_glb=source)
    print('OK: bake references, pixels, alpha, MR bytes and geometry')
    fallback = copy.deepcopy(hd)
    fallback['textures'][0]['source'] = 2
    assert mv.texture_image_index(fallback, fallback['textures'][0]) == 0
    for invalid in (-1, True, 9, 0):
        bad = copy.deepcopy(fallback['textures'][0])
        bad['source'] = invalid
        try:
            mv.texture_image_index(fallback, bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f'Invalid core fallback accepted: {invalid}')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'source.glb'
        path.write_bytes(source)
        assert np.array_equal(pixels(source_basecolor(path)), expected)
    print('OK: fallback preference and generic rig basecolor')
    cases = [
        ('missing used', lambda d: d.update(extensionsUsed=[])),
        ('basis required', lambda d: d.update(extensionsRequired=['KHR_texture_basisu'])),
        ('unknown required', lambda d: d.update(extensionsRequired=['VENDOR_unknown'])),
        ('basis texture', lambda d: d['textures'][0].update(extensions={'KHR_texture_basisu': {'source': 0}})),
        ('draco', lambda d: d['meshes'][0]['primitives'][0].update(extensions={'KHR_draco_mesh_compression': {}})),
        ('meshopt', lambda d: d['bufferViews'][0].update(extensions={'EXT_meshopt_compression': {}})),
        ('uri', lambda d: d['images'][0].update(uri='external.webp')),
        ('core webp', lambda d: d['textures'][0].update(source=0, extensions={})),
        ('ext png mime', lambda d: d['images'][0].update(mimeType='image/png')),
        ('skins', lambda d: d.update(skins=[{'joints': []}])),
        ('unused invalid texture', lambda d: d['textures'].append({'source': 9})),
    ]
    for label, mutate in cases:
        d = copy.deepcopy(doc)
        mutate(d)
        refused(label, d, binary)
        if label in ('basis required', 'unknown required'):
            assert d['extensionsRequired'][0] in ' '.join(mv.face_texture_geometry(glb(d, binary))['errors'])
    for value in (-1, True, 9):
        d = copy.deepcopy(doc)
        d['textures'][0]['extensions']['EXT_texture_webp']['source'] = value
        refused(f'ext source {value}', d, binary)
    d = copy.deepcopy(doc)
    d['textures'][0]['extensions']['EXT_texture_webp'] = []
    refused('non-dict extension', d, binary)
    # The final MR image proves that validation decodes every image.
    out = io.BytesIO()
    Image.new('RGB', (16,16), 'red').save(out, 'WEBP', lossless=True, exact=True,
        save_all=True, append_images=[Image.new('RGB', (16,16), 'blue')], duration=100, loop=0)
    for label, raw in [('mime mismatch', png((0,128,255,255))),
                       ('truncated WebP', image_bytes(parsed, 1)[:20]), ('animated', out.getvalue())]:
        d = copy.deepcopy(doc)
        view = d['bufferViews'][3]
        b = binary[:view['byteOffset']] + raw
        view['byteLength'] = len(raw)
        d['buffers'][0]['byteLength'] = len(b)
        refused(label, d, b)
    with patch.object(mv, 'MAX_TEXTURE_SIDE', 15):
        refused('side limit', doc, binary)
    with patch.object(mv, 'MAX_TEXTURE_PIXELS', 255):
        refused('pixel limit', doc, binary)
    refused('truncated BIN', doc, binary[:-16])
    # Keep the real PNG bytes intact so this isolates reference resolution.
    hd['textures'][0]['extensions']['EXT_texture_webp']['source'] = 2
    hd['meshes'][0]['primitives'] = [hd['meshes'][0]['primitives'][0]]
    refused('extension points to PNG', hd, hb)
    print('OK: malformed references, extensions, images, limits and containers refused')
    real = os.environ.get('ANIMA_UNIFORGE_GLB')
    if real:
        raw = Path(real).read_bytes()
        for verdict in (mv.face_texture_geometry(raw, original=True), validate_face_source(raw, original=True)):
            assert verdict['ok'], verdict
        print('OK: optional real UniForge GLB')
    else:
        print('SKIP: ANIMA_UNIFORGE_GLB is not set')


if __name__ == '__main__':
    main()
