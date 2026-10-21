#!/usr/bin/env python3
"""A synthetic joined sphere has two textured materials before and after LOD.

Half its faces use body material 0 and half marked patch material 1. A 0.5
ratio must reduce triangles while retaining both primitives, both embedded
textures and the patch material marker. No model or world fixtures are read.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BLENDER = '/home/dev/tools/blender-5.2.2-linux-x64/blender'


def blender_smoke(directory):
    import bpy
    sys.path.insert(0, str(ROOT / 'app/blender/scripts'))
    import _common
    _common.reset_scene()
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16)
    body = bpy.context.object
    for index in range(2):
        image = bpy.data.images.new('atlas' + str(index), width=8, height=8)
        image.generated_color = (0.6, 0.4 + 0.1 * index, 0.3, 1)
        image.pack()
        material = bpy.data.materials.new('material' + str(index))
        material.use_nodes = True
        texture = material.node_tree.nodes.new('ShaderNodeTexImage')
        texture.image = image
        shader = material.node_tree.nodes.get('Principled BSDF')
        material.node_tree.links.new(texture.outputs['Color'], shader.inputs['Base Color'])
        if index:
            material['attached_part'] = 'inset'
        body.data.materials.append(material)
    for face in body.data.polygons:
        face.material_index = int(face.center.z >= 0)
    source = Path(directory) / 'source.glb'
    bpy.ops.export_scene.gltf(filepath=str(source), export_format='GLB', export_extras=True)
    entry = _common.main
    _common.main = lambda fn: None
    import lod
    _common.main = entry
    data, outputs = lod.lod({'inputs': {'model': str(source)}, 'params': {'ratios': [.5]}, 'out_dir': directory})
    assert data['stages'][0]['tris'] < data['source_tris'], data
    Path(directory, 'output.json').write_text(json.dumps(outputs))


def main():
    sys.path.insert(0, str(ROOT))
    from app.core import paths
    from app.core.model_validate import parse_glb
    with tempfile.TemporaryDirectory(prefix='inset-lod-') as tmp:
        paths.init(Path(tmp) / 'world')
        result = subprocess.run([BLENDER, '-b', '-noaudio', '--factory-startup', '--python-exit-code', '1',
                                 '--python', str(Path(__file__).resolve()), '--', '--blender', tmp],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
        assert result.returncode == 0, result.stdout
        output = next(iter(json.loads(Path(tmp, 'output.json').read_text()).values()))
        for filename in (Path(tmp, 'source.glb'), Path(output)):
            doc = parse_glb(filename.read_bytes())['gltf']
            assert len(doc['meshes']) == 1
            assert len(doc['meshes'][0]['primitives']) == 2
            assert sum('attached_part' in m.get('extras', {}) for m in doc['materials']) == 1
            assert len(doc['images']) == 2 and all('bufferView' in im for im in doc['images'])
        print('PASS inset_part LOD reduces joined mesh and preserves two materials, embedded textures and marker')


if __name__ == '__main__':
    if '--blender' in sys.argv:
        try:
            blender_smoke(sys.argv[-1])
        except BaseException:
            import traceback
            traceback.print_exc()
            sys.stdout.flush()
            os._exit(1)
        sys.stdout.flush()
        os._exit(0)
    main()
