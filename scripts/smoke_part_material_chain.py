#!/usr/bin/env python3
"""attached_part / inset_part read the body material through the glTF importer's node chain (review 03#10, #11, #12).

Part A (pure, no Blender): ``attached_part.base_color_source``,
``attached_part.srgb_times_linear`` and ``inset_part.body_roughness`` are loaded by AST
and run on stand-in node objects (the attributes they read: type, inputs, links,
identifier, default_value, is_linked, data_type, blend_type, operation, image).
  base_color_source:
    * Base Color unlinked, default (.2, .3, .4)          -> (None, (.2, .3, .4))
    * Base Color <- Image                                -> (img, (1, 1, 1))
    * Base Color <- Mix MULTIPLY(A <- Image, B = (.5, .25, 1)) -> (img, (.5, .25, 1))
      (the importer's chain for baseColorFactor != 1; the old one-hop read
      ``links[0].from_node.image`` raised AttributeError on the Mix node)
    * Base Color <- Mix MULTIPLY(A <- Image, B <- Color Attribute) -> (img, (1, 1, 1))
  body_roughness: Roughness <- Math MULTIPLY(Value <- Separate Color.Green <- Image,
    Value_001 = .5) -> (img, default, .5): the body renders green x .5; the old
    function returned no factor, so the patch baked raw green (twice as rough).
  srgb_times_linear: sRGB .5 is linear ((.5+.055)/1.055)^2.4 = .21404; x .5 = .10702;
    back to sRGB 1.055 * .10702^(1/2.4) - .055 = .3608. Factor 1 is the identity.

Part B (Blender >= 5.2, skipped with a note when none is found):
  * A plane exported with a texture x baseColorFactor (.5, .25, 1) and a
    metallic-roughness texture with roughnessFactor .5, re-imported: the real
    importer nodes give base_color_source -> (the image, (.5, .25, 1)) and
    body_roughness -> (the image, _, .5).
  * A FLOAT point attribute 'Clean' = .5 baked through Emission into an 8x8 byte
    image the way inset_part's bake_layer does: the default (sRGB) image reads
    back 1.055*.5^(1/2.4)-.055 = .7354 (8 bit: 188/255 = .737), a Non-Color one
    .5 (128/255 = .502). inset_part must bake 'Clean' with data=True.

Usage: ./.venv/bin/python scripts/smoke_part_material_chain.py
"""
import ast
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'app/blender/scripts'


def _load(path, names, scope):
    module = ast.parse(path.read_text(encoding='utf-8'))
    body = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in body} == set(names), [n.name for n in body]
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), 'exec'), scope)
    return scope


class Link:
    def __init__(self, node):
        self.from_node = node


class Socket:
    def __init__(self, identifier, default=None, source=None):
        self.identifier, self.default_value = identifier, default
        self.links = [Link(source)] if source is not None else []
        self.is_linked = bool(self.links)


class Node:
    def __init__(self, name, type, inputs=(), **attrs):
        self.name, self.type, self.inputs = name, type, list(inputs)
        for k, v in attrs.items():
            setattr(self, k, v)


def part_a():
    scope = _load(SCRIPTS / 'attached_part.py', ('base_color_source', 'srgb_times_linear'), {'np': np})
    _load(SCRIPTS / 'inset_part.py', ('body_roughness',), scope)
    source, times, roughness = scope['base_color_source'], scope['srgb_times_linear'], scope['body_roughness']
    img = object()

    def tex():
        return Node('Image Texture', 'TEX_IMAGE', image=img)

    assert source(Socket('Base Color', (.2, .3, .4, 1))) == (None, (.2, .3, .4))
    assert source(Socket('Base Color', (.8, .8, .8, 1), tex())) == (img, (1., 1., 1.))
    mix = Node('Mix', 'MIX', [Socket('Factor_Float', 1.), Socket('A_Color', (.5, .5, .5, 1), tex()),
                              Socket('B_Color', (.5, .25, 1., 1))], data_type='RGBA', blend_type='MULTIPLY')
    got = source(Socket('Base Color', (.8, .8, .8, 1), mix))
    assert got[0] is img and np.allclose(got[1], (.5, .25, 1.)), got
    try:  # the old one-hop read
        Socket('Base Color', (.8, .8, .8, 1), mix).links[0].from_node.image
    except AttributeError:
        pass
    else:
        raise AssertionError('old read should fail on the Mix node')
    vcol = Node('Color Attribute', 'VERTEX_COLOR')
    mix_v = Node('Mix', 'MIX', [Socket('Factor_Float', 1.), Socket('A_Color', (.5, .5, .5, 1), tex()),
                                Socket('B_Color', (.5, .5, .5, 1), vcol)], data_type='RGBA', blend_type='MULTIPLY')
    got = source(Socket('Base Color', (.8, .8, .8, 1), mix_v))
    assert got[0] is img and np.allclose(got[1], (1., 1., 1.)), got

    sep = Node('Separate Color', 'SEPARATE_COLOR', [Socket('Color', (.8, .8, .8, 1), tex())])
    math = Node('Math', 'MATH', [Socket('Value', .5, sep), Socket('Value_001', .5), Socket('Value_002', .5)],
                operation='MULTIPLY')
    bsdf = Node('Principled BSDF', 'BSDF_PRINCIPLED')
    bsdf.inputs = {'Roughness': Socket('Roughness', .5, math)}
    image, value, factor = roughness(bsdf)
    assert image is img and value == .5 and abs(factor - .5) < 1e-12, (image, value, factor)
    bsdf.inputs = {'Roughness': Socket('Roughness', .7)}
    assert roughness(bsdf) == (None, .7, 1.)

    assert abs(float(times(.5, (.5,))[0]) - .3608) < 2e-4, times(.5, (.5,))
    assert np.allclose(times([.1, .5, .9], (1., 1., 1.)), [.1, .5, .9])
    print('part A: Base Color / roughness chains through the importer nodes PASS')


BLENDER_SIDE = r'''
import bpy, json, sys
from pathlib import Path
argv = sys.argv[sys.argv.index('--') + 1:]
scripts, out = argv[0], Path(argv[1])
sys.path.insert(0, scripts)
import attached_part, inset_part
for o in list(bpy.data.objects): bpy.data.objects.remove(o)
bpy.ops.mesh.primitive_plane_add(size=1)
o = bpy.context.object
m = bpy.data.materials.new('body'); m.use_nodes = True
nt = m.node_tree; b = nt.nodes['Principled BSDF']
def image(name, rgba, non_color=False):
    im = bpy.data.images.new(name, 4, 4); im.pixels[:] = list(rgba) * 16
    if non_color: im.colorspace_settings.name = 'Non-Color'
    im.filepath_raw = str(out / (name + '.png')); im.file_format = 'PNG'; im.save()
    t = nt.nodes.new('ShaderNodeTexImage'); t.image = im
    return t
col = image('albedo', (.6, .5, .4, 1))
mx = nt.nodes.new('ShaderNodeMix'); mx.data_type = 'RGBA'; mx.blend_type = 'MULTIPLY'; mx.inputs[0].default_value = 1
nt.links.new(col.outputs[0], mx.inputs[6]); mx.inputs[7].default_value = (.5, .25, 1, 1)
nt.links.new(mx.outputs[2], b.inputs['Base Color'])
mr = image('mr', (0, .6, 0, 1), non_color=True)
sep = nt.nodes.new('ShaderNodeSeparateColor'); nt.links.new(mr.outputs[0], sep.inputs[0])
mul = nt.nodes.new('ShaderNodeMath'); mul.operation = 'MULTIPLY'; mul.inputs[1].default_value = .5
nt.links.new(sep.outputs['Green'], mul.inputs[0]); nt.links.new(mul.outputs[0], b.inputs['Roughness'])
nt.links.new(sep.outputs['Blue'], b.inputs['Metallic'])
o.data.materials.append(m)
bpy.ops.export_scene.gltf(filepath=str(out / 'body.glb'), export_format='GLB')
for o in list(bpy.data.objects): bpy.data.objects.remove(o)
for mm in list(bpy.data.materials): bpy.data.materials.remove(mm)
bpy.ops.import_scene.gltf(filepath=str(out / 'body.glb'))
body = next(o for o in bpy.data.objects if o.type == 'MESH')
bsdf = next(n for n in body.active_material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
img, factor = attached_part.base_color_source(bsdf.inputs['Base Color'])
rimg, rvalue, rfactor = inset_part.body_roughness(bsdf)
result = {'base_image': img.name if img else None, 'base_factor': list(factor),
          'rough_image': rimg.name if rimg else None, 'rough_factor': rfactor}
# Clean = .5 baked through Emission as inset_part's bake_layer does.
for o in list(bpy.data.objects): bpy.data.objects.remove(o)
bpy.ops.mesh.primitive_plane_add(size=1)
p = bpy.context.object
attr = p.data.attributes.new('Clean', 'FLOAT', 'POINT')
for d in attr.data: d.value = .5
mat = bpy.data.materials.new('bake'); mat.use_nodes = True
nt = mat.node_tree; nt.nodes.clear()
outn = nt.nodes.new('ShaderNodeOutputMaterial'); emit = nt.nodes.new('ShaderNodeEmission')
cla = nt.nodes.new('ShaderNodeAttribute'); cla.attribute_name = 'Clean'
nt.links.new(emit.outputs['Emission'], outn.inputs['Surface']); nt.links.new(cla.outputs['Fac'], emit.inputs['Color'])
p.data.materials.append(mat)
bpy.context.view_layer.objects.active = p; p.select_set(True)
sc = bpy.context.scene; sc.render.engine = 'CYCLES'; sc.cycles.device = 'CPU'; sc.cycles.samples = 1
for data in (False, True):
    im = bpy.data.images.new('layer', 8, 8, alpha=False)
    if data: im.colorspace_settings.name = 'Non-Color'
    node = nt.nodes.new('ShaderNodeTexImage'); node.image = im; nt.nodes.active = node
    bpy.ops.object.bake(type='EMIT')
    result['clean_data' if data else 'clean_srgb'] = im.pixels[4 * 36]
    nt.nodes.remove(node); bpy.data.images.remove(im)
(out / 'result.json').write_text(json.dumps(result))
'''


def part_b():
    sys.path.insert(0, str(ROOT))
    from app.blender import runner
    exe = runner.find_executable()
    if not exe:
        print('part B: SKIPPED — no Blender >= 5.2 found')
        return
    with tempfile.TemporaryDirectory(prefix='part-material-') as tmp:
        root = Path(tmp)
        (root / 'side.py').write_text(BLENDER_SIDE)
        r = subprocess.run([exe, '-b', '-noaudio', '--factory-startup', '--python-exit-code', '1',
                            '--python', str(root / 'side.py'), '--', str(SCRIPTS), tmp],
                           capture_output=True, text=True, timeout=300)
        if r.returncode:
            print(r.stdout[-3000:], r.stderr[-3000:])
            raise SystemExit(r.returncode)
        d = json.loads((root / 'result.json').read_text())
    assert d['base_image'] and np.allclose(d['base_factor'], (.5, .25, 1.), atol=1e-6), d
    assert d['rough_image'] and abs(d['rough_factor'] - .5) < 1e-6, d
    assert abs(d['clean_srgb'] - .737) < .004, d
    assert abs(d['clean_data'] - .502) < .004, d
    src = (SCRIPTS / 'inset_part.py').read_text(encoding='utf-8')
    assert "bake_layer(cla.outputs['Fac'], data=True)" in src, 'inset_part must read Clean unconverted'
    print('part B: importer chain factors and the Clean read-back through Blender PASS', json.dumps(d))


def main():
    part_a()
    part_b()
    print('smoke_part_material_chain: PASS')


if __name__ == '__main__':
    main()
