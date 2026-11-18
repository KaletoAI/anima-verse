#!/usr/bin/env python3
"""Smoke (Blender): a vertex moved by the extension rig survives export on a body with shape keys (review 03, below
the cut-off: the ``vertex.co`` writes of ``extension_bones``; ``set_co``).

Usage:  ./.venv/bin/python scripts/smoke_extension_shape_key_writes.py

Headless Blender (``app.blender.runner``, CPU), no world: a probe execs extension_bones.py on a default plane
(corners at x, y = +-1, z = 0).

By hand: the plane gets shape keys Basis and Smile (Smile lifts vertex 0 by +.5 in z). ``set_co`` moves vertex 0 to
z = 1. Exported as glTF (+Y up, so Blender z is glTF y): POSITION max y = 1 (the Basis followed; on 69aeeba75 the
plain ``vertex.co`` write leaves it 0 — the exporter reads the Basis key), and the Smile target's y max = .5 (the
morph keeps its offset). A plane without shape keys: ``set_co`` is a plain write, max y = 1.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROBE = r'''
import bpy, json, struct, sys
from pathlib import Path
from mathutils import Vector
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
source=Path(job['params']['source']); scope={'__file__':str(source)}
exec(compile(source.read_text(),str(source),'exec'),scope)
fails=[]
def case(keys):
 bpy.ops.wm.read_factory_settings(use_empty=True)
 bpy.ops.mesh.primitive_plane_add()
 o=bpy.context.object
 if keys:
  o.shape_key_add(name='Basis'); k=o.shape_key_add(name='Smile'); k.data[0].co.z+=.5
 v=o.data.vertices[0]
 scope['set_co'](o,v,v.co+Vector((0,0,1)))
 out=str(Path(job['result']).parent/('k.glb' if keys else 'n.glb'))
 bpy.ops.export_scene.gltf(filepath=out,export_format='GLB',export_morph=True)
 raw=Path(out).read_bytes(); n=struct.unpack_from('<I',raw,12)[0]; doc=json.loads(raw[20:20+n])
 prim=doc['meshes'][0]['primitives'][0]
 top=doc['accessors'][prim['attributes']['POSITION']]['max'][1]
 morph=doc['accessors'][prim['targets'][0]['POSITION']]['max'][1] if keys else None
 return top,morph
top,morph=case(True)
if abs(top-1)>1e-6 or abs(morph-.5)>1e-6: fails.append(('keys',top,morph))
top,_=case(False)
if abs(top-1)>1e-6: fails.append(('plain',top))
Path(job['result']).write_text(json.dumps({'ok':not fails,'error':repr(fails),'data':{},'outputs':{}}))
'''


def main():
    from app.blender import runner
    if not runner.status()['executable']:
        raise RuntimeError('Blender executable unavailable; no checks ran')
    with tempfile.TemporaryDirectory(prefix='shape-key-writes-') as tmp:
        root = Path(tmp)
        (root/'probe.py').write_text(PROBE)
        source = runner.SCRIPTS_DIR/'extension_bones.py'
        with patch.object(runner, 'SCRIPTS_DIR', root):
            result = runner.run('probe', params={'source': str(source)}, out_dir=root/'out', timeout_s=120)
    print('all passed' if result['ok'] else f"FAILED {result.get('error')}")
    sys.exit(0 if result['ok'] else 1)


if __name__ == '__main__':
    main()
