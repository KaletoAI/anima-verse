#!/usr/bin/env python3
"""The Blender ``diagnose`` and ``lod`` scripts on joined meshes that carry a marked inset patch — one Blender run,
two sections; a failing section does not stop the next, the run exits non-zero and names every failed section.

Usage: ./.venv/bin/python scripts/smoke_inset_part_lod.py

No model or world fixtures are read (a throwaway storage root, synthetic meshes built inside Blender).

[D] DIAGNOSE (formerly smoke_inset_part_diagnose): a closed tetrahedron has one body triangle and three marked patch
faces. Body corners (0,0,0), (1,0,0), (0,1,0) give exactly three measured edges:
1, 1, sqrt(2); median 1, max sqrt(2), no needles, one component. The patch
apex at (0,0,100) must not affect shape numbers. All six physical edges have
two faces, so boundary_edges remains 0 despite excluding patch shape data.
A separate marked-node triangle 1000 units wide must contribute no metrics.

[L] LOD: a synthetic joined sphere has two textured materials before and after LOD.
Half its faces use body material 0 and half marked patch material 1. A 0.5
ratio must reduce triangles while retaining both primitives, both embedded
textures and the patch material marker.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
BLENDER = '/home/dev/tools/blender-5.2.2-linux-x64/blender'


def _load(name):
    """Import one of the Blender scripts without running its ``_common.main`` entry."""
    import _common
    entry = _common.main
    _common.main = lambda fn: None
    module = __import__(name)
    _common.main = entry
    return module


def blender_diagnose(directory):
    import bpy
    import _common
    _common.reset_scene()
    mesh = bpy.data.meshes.new('joined')
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 100)], [],
                     [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)])
    obj = bpy.data.objects.new('body', mesh)
    bpy.context.collection.objects.link(obj)
    for index in range(2):
        material = bpy.data.materials.new('surface' + str(index))
        if index:
            material['attached_part'] = 'inset'
        mesh.materials.append(material)
    for face in mesh.polygons:
        face.material_index = int(face.index > 0)
    separate = bpy.data.meshes.new('separate')
    separate.from_pydata([(0, 0, 0), (1000, 0, 0), (0, 1000, 0)], [], [(0, 1, 2)])
    part = bpy.data.objects.new('part', separate)
    part['attached_part'] = 'attached'
    bpy.context.collection.objects.link(part)
    source = Path(directory) / 'diagnose_source.glb'
    bpy.ops.export_scene.gltf(filepath=str(source), export_format='GLB', export_extras=True)
    diagnose = _load('diagnose')
    data, _ = diagnose.diagnose({'inputs': {'model': str(source)}, 'params': {}})
    assert data['edges'] == 3, data
    assert data['edge_median'] == 1 and abs(data['edge_max'] - 2 ** .5) < 1e-5, data
    assert data['boundary_edges'] == 0 and data['loose_parts'] == 1, data
    assert data['needles'] == 0 and data['spikes'] == 0, data
    body = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and 'attached_part' not in o)
    # Imported UV/normal splits may duplicate corners; only the patch apex is omitted.
    measured = diagnose._body_vertex_indices(body)
    assert measured and all(body.data.vertices[i].co.length < 2 for i in measured)
    print('PASS inset_part diagnose: 3 body edges, median 1, max sqrt(2), zero false borders, one component', flush=True)


def blender_lod(directory):
    import bpy
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
    lod = _load('lod')
    data, outputs = lod.lod({'inputs': {'model': str(source)}, 'params': {'ratios': [.5]}, 'out_dir': directory})
    assert data['stages'][0]['tris'] < data['source_tris'], data
    Path(directory, 'output.json').write_text(json.dumps(outputs))
    print('BLENDER-OK lod', flush=True)


def blender_smoke(directory):
    sys.path.insert(0, str(ROOT / 'app/blender/scripts'))
    failed = []
    for name, fn in (('[D] diagnose', blender_diagnose), ('[L] lod', blender_lod)):
        try:
            fn(directory)
        except BaseException:
            traceback.print_exc()
            print(f'FAIL {name} (inside Blender)', flush=True)
            failed.append(name)
    return failed


def main():
    sys.path.insert(0, str(ROOT))
    from app.core import paths
    from app.core.model_validate import parse_glb
    failed = []
    with tempfile.TemporaryDirectory(prefix='inset-diagnose-lod-') as tmp:
        paths.init(Path(tmp) / 'world')
        result = subprocess.run([BLENDER, '-b', '-noaudio', '--factory-startup', '--python-exit-code', '1',
                                 '--python', str(Path(__file__).resolve()), '--', '--blender', tmp],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180)
        lines = result.stdout.splitlines()

        print('\n=== [D] diagnose')
        try:
            assert not any(line.startswith('FAIL [D]') for line in lines), result.stdout
            print(next(line for line in lines if line.startswith('PASS inset_part diagnose')))
        except (AssertionError, StopIteration):
            print(result.stdout)
            print('FAIL [D] diagnose')
            failed.append('[D] diagnose')

        print('\n=== [L] lod')
        try:
            assert not any(line.startswith('FAIL [L]') for line in lines), result.stdout
            output = next(iter(json.loads(Path(tmp, 'output.json').read_text()).values()))
            for filename in (Path(tmp, 'source.glb'), Path(output)):
                doc = parse_glb(filename.read_bytes())['gltf']
                assert len(doc['meshes']) == 1
                assert len(doc['meshes'][0]['primitives']) == 2
                assert sum('attached_part' in m.get('extras', {}) for m in doc['materials']) == 1
                assert len(doc['images']) == 2 and all('bufferView' in im for im in doc['images'])
            print('PASS inset_part LOD reduces joined mesh and preserves two materials, embedded textures and marker')
        except Exception:  # noqa: BLE001 — a failed assert ends its section only
            traceback.print_exc()
            print('FAIL [L] lod')
            failed.append('[L] lod')

        if result.returncode != 0 and not failed:
            print(result.stdout)
            failed.append(f'Blender exit code {result.returncode}')
    if failed:
        print(f'\nFAILED {len(failed)} section(s): ' + ', '.join(failed))
        sys.exit(1)


if __name__ == '__main__':
    if '--blender' in sys.argv:
        try:
            failed = blender_smoke(sys.argv[-1])
        except BaseException:
            traceback.print_exc()
            sys.stdout.flush()
            os._exit(1)
        sys.stdout.flush()
        os._exit(1 if failed else 0)
    main()
