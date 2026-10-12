#!/usr/bin/env python3
"""Hand-derived bake expectations (plan section 15), without external assets.

The source has two triangles, using seven interleaved POSITION/UV vertices; the body is at (12,12).
The face triangle's UV pixel corners on a 16x16 atlas are (4,4),(8,4),(4,8).
Its interior (5,5) and dilation ring (3,5) become red; (0,0) stays blue.
Transparent face texel (4,4) stays blue, and every base alpha stays 123.
An 8x8 solid red atlas must resize to 16x16 with the same inside/outside
colors. Changed positions, UVs, triangles and identical basecolor must fail.
The bake retains source mesh/accessor layout and all geometry bytes, and
passes validate_source. Texture comparison accepts differences <=2, rejects
larger differences, resizes rig textures and rejects undecodable textures.
Unshared basecolor replaces its image without an orphan; trailing views move
with aligned offsets and unchanged payloads. Unsafe extensions reject repacking.
Shared metallicRoughness stays on texture 0 and unchanged source BIN bytes;
basecolor moves to texture 1 with sampler 0. texCoord=1, transforms, negative
UVs (face or body, e.g. a body island shifted
by +1 U) and fully transparent faces fail. Winding reversal and replacing a second
012 with a second 000 fail despite identical unordered triangle sets. With
body corners (10,4),(12,4),(10,6), the four-pixel ring leaves (10,4) blue and
(9,4) red: body coverage takes precedence only outside the face triangles.
"""
import copy
import io
import json
import struct
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from app.core.model_validate import parse_glb
from app.core.mesh_source import validate_source


def png(color, size=16, transparent=False):
    image = Image.new('RGBA', (size, size), color)
    if transparent:
        image.putpixel((4, 4), (240, 10, 20, 0))
    out = io.BytesIO()
    image.save(out, 'PNG')
    return out.getvalue()


def glb(doc, binary):
    raw = json.dumps(doc).encode()
    raw += b' ' * (-len(raw) % 4)
    binary += b'\0' * (-len(binary) % 4)
    return (struct.pack('<III', 0x46546c67, 2, 28 + len(raw) + len(binary))
            + struct.pack('<I4s', len(raw), b'JSON') + raw
            + struct.pack('<I4s', len(binary), b'BIN\0') + binary)


def fixture(hub=False, size=16, transparent=False):
    binary = bytearray()
    views = []
    def add(raw, **extra):
        binary.extend(b'\0' * (-len(binary) % 4))
        views.append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': len(raw), **extra})
        binary.extend(raw)
        return len(views) - 1
    add(struct.pack('<6H', 0, 1, 2, 4, 5, 6))
    add(b''.join(struct.pack('<5f', *row) for row in
                [(0,0,0,.25,.25), (1,0,0,.5,.25), (0,1,0,.25,.5), (1,1,0,.75,.75), (2,0,0,.75,.75), (3,0,0,.875,.75), (2,1,0,.75,.875)]), byteStride=20)
    add(png((10, 20, 200, 123)))
    doc = {'asset': {'version': '2.0'}, 'bufferViews': views,
           'accessors': [{'bufferView': 0, 'componentType': 5123, 'type': 'SCALAR', 'count': 6},
                         {'bufferView': 1, 'componentType': 5126, 'type': 'VEC3', 'count': 7},
                         {'bufferView': 1, 'byteOffset': 12, 'componentType': 5126, 'type': 'VEC2', 'count': 7}],
           'meshes': [{'primitives': [{'indices': 0, 'attributes': {'POSITION': 1, 'TEXCOORD_0': 2}, 'material': 0}]}],
           'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}],
           'textures': [{'source': 0}], 'images': [{'bufferView': 2, 'mimeType': 'image/png'}]}
    if hub:
        image_view = add(png((240,10,20,255), size, transparent))
        doc['images'].append({'bufferView': image_view, 'mimeType': 'image/png'})
        doc['textures'].append({'source': 1})
        doc['materials'].append({'pbrMetallicRoughness': {'baseColorTexture': {'index': 1}}})
        doc['accessors'][0]['count'] = 3
        doc['accessors'].append({'bufferView': 0, 'byteOffset': 6, 'componentType': 5123, 'type': 'SCALAR', 'count': 3})
        face = doc['meshes'][0]['primitives'][0]
        body = copy.deepcopy(face)
        face['material'] = 1
        body['indices'] = 3
        doc['meshes'][0]['primitives'].append(body)
    doc['buffers'] = [{'byteLength': len(binary)}]
    return doc, bytes(binary)


def review_cases():
    from app.core.face_retexture import bake_face_texture
    doc, binary = fixture()
    doc['materials'][0]['pbrMetallicRoughness']['metallicRoughnessTexture'] = {'index': 0}
    doc['textures'][0]['sampler'] = 0
    doc['samplers'] = [{}]
    source = glb(doc, binary)
    parsed = parse_glb(bake_face_texture(source, glb(*fixture(True)))[0])
    original = parse_glb(source)
    assert parsed['bin'][:len(original['bin'])] == original['bin'], 'Source BIN must be untouched'
    assert parsed['gltf']['bufferViews'][:-1] == original['gltf']['bufferViews']
    assert parsed['gltf']['images'][:-1] == original['gltf']['images']
    assert parsed['gltf']['textures'][-1]['sampler'] == 0
    pbr = parsed['gltf']['materials'][0]['pbrMetallicRoughness']
    assert pbr['metallicRoughnessTexture']['index'] == 0 and pbr['baseColorTexture']['index'] == 1
    assert len(parsed['gltf']['images']) == 2
    assert parsed['gltf']['textures'][0] == original['gltf']['textures'][0]
    # A view after the image must move, retain its payload and remain aligned.
    doc, binary = fixture()
    binary += b'\0' * (-len(binary) % 4)
    doc['bufferViews'].append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': 5})
    binary += b'trail'
    doc['buffers'][0]['byteLength'] = len(binary)
    doc['materials'][0]['extensions'] = {'KHR_materials_unlit': {}}
    doc['extensionsUsed'] = ['KHR_materials_unlit']
    parsed = parse_glb(bake_face_texture(glb(doc, binary), glb(*fixture(True)))[0])
    view = parsed['gltf']['bufferViews'][-1]
    assert view['byteOffset'] % 4 == 0
    assert parsed['bin'][view['byteOffset']:view['byteOffset'] + 5] == b'trail'
    assert view['byteOffset'] != doc['bufferViews'][-1]['byteOffset']
    for name, extension in [('EXT_custom_buffer_layout', {'buffer': 0, 'byteOffset': 0}),
                            ('KHR_materials_unlit', {'bufferView': 0})]:
        doc, binary = fixture()
        doc['extensions'] = {name: extension}
        rejected(glb(doc, binary), glb(*fixture(True)), 'Cannot repack')
    # Another image sharing the view also requires append, even with no material slot.
    doc, binary = fixture()
    doc['images'].append(dict(doc['images'][0]))
    parsed = parse_glb(bake_face_texture(glb(doc, binary), glb(*fixture(True)))[0])
    assert len(parsed['gltf']['images']) == 3
    assert parsed['gltf']['images'][:2] == doc['images']
    for target in ('source', 'hub'):
        for field, value, message in [('texCoord', 1, 'texCoord'),
                                      ('extensions', {'KHR_texture_transform': {}}, 'KHR_texture_transform')]:
            sd, sb = fixture()
            hd, hb = fixture(True)
            material = sd['materials'][0] if target == 'source' else hd['materials'][1]
            material['pbrMetallicRoughness']['baseColorTexture'][field] = value
            rejected(glb(sd, sb), glb(hd, hb), message)
    sd, sb = fixture()
    hd, hb = fixture(True)
    for doc, data in ((sd, sb), (hd, hb)):
        mutable = bytearray(data)
        struct.pack_into('<f', mutable, doc['bufferViews'][1]['byteOffset'] + 12, -0.01)
        if doc is sd: sb = bytes(mutable)
        else: hb = bytes(mutable)
    rejected(glb(sd, sb), glb(hd, hb), 'outside [0, 1]')
    # A body island shifted by +1 in U (vertex 4: u .75 -> 1.75, byte offset
    # 4*20+12 in the interleaved view) would sample the same texels under
    # REPEAT but rasterize off the atlas, leaving them unprotected: rejected.
    sd, sb = fixture()
    hd, hb = fixture(True)
    for doc, data in ((sd, sb), (hd, hb)):
        mutable = bytearray(data)
        struct.pack_into('<f', mutable, doc['bufferViews'][1]['byteOffset'] + 4 * 20 + 12, 1.75)
        if doc is sd: sb = bytes(mutable)
        else: hb = bytes(mutable)
    rejected(glb(sd, sb), glb(hd, hb), 'Body triangle UVs are outside [0, 1]')
    hd, hb = fixture(True)
    view = hd['bufferViews'][-1]
    raw = png((240,10,20,0))
    hb = hb[:view['byteOffset']] + raw
    view['byteLength'] = len(raw)
    hd['buffers'][0]['byteLength'] = len(hb)
    rejected(glb(*fixture()), glb(hd, hb), 'no usable face texture')
    hd, hb = fixture(True)
    hb = bytearray(hb)
    struct.pack_into('<3H', hb, 0, 0, 2, 1)
    rejected(glb(*fixture()), glb(hd, bytes(hb)), 'triangle')
    # Same unordered set {012, 456, 000}, different multiplicities.
    sd, sb = fixture()
    hd, hb = fixture(True)
    for doc, data, indices in ((sd, sb, (0,1,2,4,5,6,0,1,2,0,0,0)),
                                (hd, hb, (0,1,2,4,5,6,0,0,0,0,0,0))):
        data = bytearray(data)
        data.extend(b'\0' * (-len(data) % 4))
        offset = len(data)
        data.extend(struct.pack('<12H', *indices))
        doc['bufferViews'].append({'buffer': 0, 'byteOffset': offset, 'byteLength': 24})
        doc['accessors'][0].update(bufferView=len(doc['bufferViews'])-1, count=12)
        if doc is hd:
            doc['meshes'][0]['primitives'] = [doc['meshes'][0]['primitives'][0]]
        doc['buffers'][0]['byteLength'] = len(data)
        if doc is sd: sb = bytes(data)
        else: hb = bytes(data)
    rejected(glb(sd, sb), glb(hd, hb), 'triangle')
    # Body begins at x=10, two pixels beyond face corner x=8.
    sd, sb = fixture()
    hd, hb = fixture(True)
    for doc, data in ((sd, sb), (hd, hb)):
        data = bytearray(data)
        start = doc['bufferViews'][1]['byteOffset']
        for i, uv in zip((4,5,6), ((10/16,4/16),(12/16,4/16),(10/16,6/16))):
            struct.pack_into('<2f', data, start+i*20+12, *uv)
        if doc is sd: sb = bytes(data)
        else: hb = bytes(data)
    baked, _ = bake_face_texture(glb(sd, sb), glb(hd, hb))
    from app.core.face_retexture import _primitive_basecolor
    parsed = parse_glb(baked)
    image = Image.open(io.BytesIO(_primitive_basecolor(parsed, parsed['gltf']['meshes'][0]['primitives'][0])[1]))
    assert image.getpixel((10,4)) == (10,20,200,123)
    assert image.getpixel((9,4)) == (240,10,20,123)


def rejected(source, hub, message):
    from app.core.face_retexture import bake_face_texture
    try:
        bake_face_texture(source, hub)
    except ValueError as exc:
        assert message in str(exc), str(exc)
    else:
        raise AssertionError(f'Expected rejection: {message}')


def main():
    from app.core.face_retexture import bake_face_texture, face_texture_preserved
    source = glb(*fixture())
    review_cases()
    unshared = parse_glb(bake_face_texture(source, glb(*fixture(True)))[0])
    assert len(unshared["gltf"]["images"]) == 1, "Unshared image must be replaced, without an orphan"
    assert {t["source"] for t in unshared["gltf"]["textures"]} == set(range(len(unshared["gltf"]["images"])))
    for size, transparent in [(16, True), (8, False)]:
        baked, info = bake_face_texture(source, glb(*fixture(True, size, transparent)), dilate_px=1)
        assert validate_source(baked)['ok']
        parsed, original = parse_glb(baked), parse_glb(source)
        assert parsed['gltf']['meshes'] == original['gltf']['meshes']
        assert parsed['gltf']['accessors'] == original['gltf']['accessors']
        for i in (0, 1):
            bv, ov = parsed['gltf']['bufferViews'][i], original['gltf']['bufferViews'][i]
            assert parsed['bin'][bv['byteOffset']:bv['byteOffset']+bv['byteLength']] == original['bin'][ov['byteOffset']:ov['byteOffset']+ov['byteLength']]
        view = parsed['gltf']['bufferViews'][-1]
        image = Image.open(io.BytesIO(parsed['bin'][view['byteOffset']:view['byteOffset']+view['byteLength']]))
        assert image.getpixel((5,5)) == (240,10,20,123)
        assert image.getpixel((3,5)) == (240,10,20,123)
        assert image.getpixel((0,0)) == (10,20,200,123)
        if transparent:
            assert image.getpixel((4,4)) == (10,20,200,123)
        assert np.all(np.asarray(image)[...,3] == 123)
        # The one-pixel square dilation has seven rows of lengths 7,7,7,6,5,4,3.
        expected = np.full((16, 16, 4), (10,20,200,123), dtype=np.uint8)
        for y, right in [(3,9), (4,9), (5,9), (6,8), (7,7), (8,6), (9,5)]:
            expected[y, 3:right+1, :3] = (240,10,20)
        if transparent:
            expected[4,4,:3] = (10,20,200)
        assert np.array_equal(np.asarray(image), expected)
        assert info == {'face_primitives': 1, 'face_triangles': 1,
                        'texels_replaced': 38 if transparent else 39, 'dilate_px': 1}
        assert face_texture_preserved(baked, baked)
    baked, info = bake_face_texture(source, glb(*fixture(True)))
    assert info['dilate_px'] == 4
    parsed = parse_glb(baked)
    view = parsed['gltf']['bufferViews'][-1]
    image = Image.open(io.BytesIO(parsed['bin'][view['byteOffset']:view['byteOffset']+view['byteLength']]))
    assert image.getpixel((0,0)) == (240,10,20,123)
    assert image.getpixel((15,15)) == (10,20,200,123)
    for mutation, message in [('positions', 'POSITION'), ('uvs', 'TEXCOORD_0'), ('triangles', 'triangle'), ('image', 'no face texture')]:
        doc, binary = fixture(True)
        binary = bytearray(binary)
        if mutation in ('positions', 'uvs'):
            struct.pack_into('<f', binary, doc['bufferViews'][1]['byteOffset'] + (0 if mutation == 'positions' else 12), .9)
        elif mutation == 'triangles':
            struct.pack_into('<H', binary, 0, 3)
        else:
            doc['textures'][1]['source'] = 0
        try:
            bake_face_texture(source, glb(doc, bytes(binary)))
        except ValueError as exc:
            assert message in str(exc), str(exc)
        else:
            raise AssertionError(f'{mutation} must fail')
    def recolor(color, size=16):
        doc, binary = fixture()
        view = doc['bufferViews'][2]
        raw = png(color, size)
        binary = binary[:view['byteOffset']] + raw
        view['byteLength'] = len(raw)
        doc['buffers'][0]['byteLength'] = len(binary)
        return glb(doc, binary)
    assert face_texture_preserved(source, recolor((12,22,202,125), 8))
    assert not face_texture_preserved(source, recolor((30,40,220,123)))
    assert not face_texture_preserved(source, b'invalid')
    mask = np.zeros((16,16), dtype=bool)
    mask[5,5] = True
    assert face_texture_preserved(source, recolor((12,22,202,0)), replacement_mask=mask)
    assert not face_texture_preserved(source, recolor((13,23,203,123)), replacement_mask=mask)
    # Cyclic rotation preserves the oriented triangle, unlike reversal.
    doc, binary = fixture(True)
    binary = bytearray(binary)
    struct.pack_into('<3H', binary, 0, 1, 2, 0)
    assert bake_face_texture(source, glb(doc, bytes(binary)))[1]['face_triangles'] == 1
    print('PASS: geometry, dilation, alpha, atlas resize, rejection, validation and rig texture comparison')


if __name__ == '__main__':
    main()
