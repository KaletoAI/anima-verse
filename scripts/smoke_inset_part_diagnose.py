#!/usr/bin/env python3
"""A closed tetrahedron has one body triangle and three marked patch faces.

Body corners (0,0,0), (1,0,0), (0,1,0) give exactly three measured edges:
1, 1, sqrt(2); median 1, max sqrt(2), no needles, one component. The patch
apex at (0,0,100) must not affect shape numbers. All six physical edges have
two faces, so boundary_edges remains 0 despite excluding patch shape data.
A separate marked-node triangle 1000 units wide must contribute no metrics.
"""
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
    source = Path(directory) / 'source.glb'
    bpy.ops.export_scene.gltf(filepath=str(source), export_format='GLB', export_extras=True)
    entry = _common.main
    _common.main = lambda fn: None
    import diagnose
    _common.main = entry
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


def main():
    sys.path.insert(0, str(ROOT))
    from app.core import paths
    with tempfile.TemporaryDirectory(prefix='inset-diagnose-') as tmp:
        paths.init(Path(tmp) / 'world')
        result = subprocess.run([BLENDER, '-b', '-noaudio', '--factory-startup', '--python-exit-code', '1',
                                 '--python', str(Path(__file__).resolve()), '--', '--blender', tmp],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
        assert result.returncode == 0, result.stdout
        print(next(line for line in result.stdout.splitlines() if line.startswith('PASS ')))


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
