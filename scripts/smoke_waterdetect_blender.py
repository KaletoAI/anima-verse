#!/usr/bin/env python3
"""Controller-only Blender integration smoke. Do not run in the Codex sandbox.

Hand-derived world units (export preserves metres): blue pool interior 2x1,
bed .2, spill 1.2 -> D=1, L=1.2-min(.08,.2)=1.12, area 2 m².
White tub .5x.5, bed .2, rim .7 -> L=.7-min(.08,.1)=.62,
area .25 m², candidate/bath disabled. Blue flat patch 1x1 at .2 ->
painted film .21, candidate/lake disabled. Levels allow one .02 m step,
areas allow 10% (boundary sampling). Grey room enclosed by 2.5 m walls,
measure=xz: no colour evidence, so no regions even though it is a depression.
Roofed diorama: the same blue 2x1 pool, bed .2 and rim 1.2, under a
flat grey slab whose underside is .2+2.5=2.7 (2.5 m above the floor).
Air over bed = 2.5 m and over rim = 1.5 m, both >= 1.2 m clearance.
With measure=xz and target 2.2, s=1: chosen bed/rim remain .2/1.2,
so colour basin area = 2 m² (±10%) and level = 1.12 (±.021 m).
A topmost-hit raster sees only grey and fails this regression.
Mottled patch: a flat 1x1 m blue square at .2 crossed by two white
.02 m wide lines. Raw blue area = 1 - (2*.02 - .02**2) = .9604 m².
Closing radius round(.04/.02)=2 nodes joins the four quadrants; any
residual crack holes are below .05 m². Expect ONE painted region, NO
holes, area 1 m² (±10% boundary sampling), film level .21.
Usage: ./.venv/bin/python scripts/smoke_waterdetect_blender.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.blender import runner
from app.core.model_water import detect_water

BUILD = r'''
import bpy, sys
from pathlib import Path
out = Path(sys.argv[sys.argv.index('--')+1])
def mat(name, rgb):
    m = bpy.data.materials.new(name); m.use_nodes = True
    m.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value = (*rgb, 1)
    return m
blue = mat('blue', (.02,.25,.6)); white = mat('white', (.8,.8,.8)); grey = mat('grey', (.3,.3,.3))
def box(center, size, material):
    bpy.ops.mesh.primitive_cube_add(size=1, location=center)
    o = bpy.context.object; o.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    o.data.materials.append(material)
def basin(x, w, d, rim, material):
    box((x,0,.1), (w+.2,d+.2,.2), material)
    for sign in (-1,1):
        box((x+sign*(w/2+.05),0,rim/2), (.1,d+.2,rim), white)
        box((x,sign*(d/2+.05),rim/2), (w,.1,rim), white)
def reset():
    bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
reset()
basin(0,2,1,1.2,blue); basin(3,.5,.5,.7,white)
box((5,0,.1),(1,1,.2),blue)
bpy.ops.export_scene.gltf(filepath=str(out/'pools.glb'), export_format='GLB')
reset()
box((0,0,.1),(4,4,.2),grey)
for s in (-1,1):
    box((s*2,0,1.25),(.1,4.1,2.5),grey)
    box((0,s*2,1.25),(4,.1,2.5),grey)
bpy.ops.export_scene.gltf(filepath=str(out/'room.glb'), export_format='GLB')
reset()
basin(0,2,1,1.2,blue)
box((0,0,2.75),(2.2,1.2,.1),grey)
bpy.ops.export_scene.gltf(filepath=str(out/'roofed-pool.glb'), export_format='GLB')
reset()
box((0,0,.1),(1,1,.2),blue)
box((0,0,.2005),(1,.02,.001),white)
box((0,0,.2005),(.02,1,.001),white)
bpy.ops.export_scene.gltf(filepath=str(out/'mottled-patch.glb'), export_format='GLB')
'''


def main():
    exe = runner.find_executable()
    assert exe, 'Blender >=5.2 required'
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build = root/'build.py'
        build.write_text(BUILD)
        subprocess.run([exe, '--background', '--factory-startup', '--python-exit-code', '1',
                        '--python', str(build), '--', tmp], check=True, timeout=120)
        # Mesh x extent: -1.1..5.5 = 6.6, target 6.6 gives s=1.
        data, reason = detect_water(root/'pools.glb', {}, target_m=6.6, measure='xyz',
                                    wait_s=300, preview=root/'preview.png')
        assert reason == 'ok', reason
        regions = data['regions']
        assert len(regions) == 3, regions
        for kind, look, area, level, enabled in [('basin','pool',2,1.12,True),
                                                ('basin','bath',.25,.62,False),
                                                ('painted','lake',1,.21,False)]:
            r = next(r for r in regions if r['kind'] == kind and r['look']['preset'] == look)
            assert r['enabled'] == enabled
            assert r['confidence'] == ('sure' if enabled else 'candidate')
            assert abs(r['level']-level) <= .021, r
            assert abs(r['area_m2']-area) <= area*.1, r
        assert (root/'preview.png').is_file()
        room, reason = detect_water(root/'room.glb', {}, target_m=4.1, measure='xz', wait_s=300)
        assert reason == 'ok' and room['regions'] == [], room
        roofed, reason = detect_water(root/'roofed-pool.glb', {}, target_m=2.2,
                                      measure='xz', wait_s=300, preview=root/'roofed-preview.png')
        assert reason == 'ok', reason
        assert len(roofed['regions']) == 1, roofed
        pool = roofed['regions'][0]
        assert pool['kind'] == 'basin' and pool['look']['preset'] == 'pool', pool
        assert pool['confidence'] == 'sure' and pool['enabled'], pool
        assert abs(pool['area_m2'] - 2) <= .2, pool
        assert abs(pool['level'] - 1.12) <= .021, pool
        assert (root/'roofed-preview.png').is_file()
        mottled, reason = detect_water(root/'mottled-patch.glb', {}, target_m=1,
                                       measure='xz', wait_s=300)
        assert reason == 'ok', reason
        assert len(mottled['regions']) == 1, mottled
        patch = mottled['regions'][0]
        assert patch['kind'] == 'painted', patch
        assert patch['holes'] == [], patch
        assert abs(patch['area_m2'] - 1) <= .1, patch
        assert abs(patch['level'] - .21) <= .021, patch
    print('smoke_waterdetect_blender: PASS')


if __name__ == '__main__':
    main()
