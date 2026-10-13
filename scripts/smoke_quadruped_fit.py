#!/usr/bin/env python3
"""Check P3 quadruped fit against the CC0 fox rest skeleton.

Hand-derived limits from spec §4.2/P3: self-fit joint error <= .02*body
length; sum(Upper..Tip lengths)/|Tip.tail-Upper.head| differs by <= .05
from the reference on EACH leg. Mirroring changes symmetry by <1% of the
body diagonal. A 37-degree yaw and 1.8 uniform scale must leave canonical
joints identical after dividing by 1.8 (<=2% reference length). A cube
and a missing front paw cannot satisfy the four-ground-cluster inequalities:
min share >=.05, length gap >=.30, lateral gap >=.25, outliers <=.15.
Spec §4.2 step 1 centres the mesh bounding box in x/y and sets min z
on the ground. Thus expected rest joints must receive the translation
(-bbox_center_x, -bbox_center_y, -mesh_min_z), derived from the fox mesh
vertices, before comparison with the fitted output. The reference skeleton is
the armature in fox-animations.glb in rest pose (§4.1). The authored fox already
faces -Y, so no rotation is needed. The turned mesh returns to this canonical
frame at 1.8 times the size; dividing its joints by 1.8 removes that scale.
Expected values are tolerances from the spec, never snapshots of the fitter.
Usage: ./.venv/bin/python scripts/smoke_quadruped_fit.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.blender import runner
from app.core.paths import get_quadruped_dir

# This helper only prepares inputs and reads outputs; it does not call the
# fitter's measurement functions when deriving the expected rest skeleton.
HELPER = r'''
import bpy, json, sys, math
import numpy as np
from pathlib import Path
from mathutils import Matrix, Vector
folder, assets, stage = map(str, sys.argv[sys.argv.index('--')+1:])
folder, assets = Path(folder), Path(assets)
bpy.ops.wm.read_factory_settings(use_empty=True)
def load(path):
    bpy.ops.import_scene.gltf(filepath=str(path))
    shapes = {pb.custom_shape for o in bpy.data.objects if o.type=='ARMATURE' for pb in o.pose.bones if pb.custom_shape}
    for o in shapes:
        bpy.data.objects.remove(o, do_unlink=True)
def joints(arm):
    return {b.name:[list(arm.matrix_world@b.head_local),list(arm.matrix_world@b.tail_local)] for b in arm.data.bones}
def rest_pose(arm):
    arm.animation_data_clear()
    for pb in arm.pose.bones:
        pb.matrix_basis=Matrix.Identity(4)
    bpy.context.view_layer.update()
if stage=='prepare':
    load(assets/'fox-animations.glb')
    arm=next(o for o in bpy.data.objects if o.type=='ARMATURE')
    rest_pose(arm)
    reference_joints=joints(arm)
    meshes=[o for o in bpy.data.objects if o.type=='MESH']
    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes:
        w=o.matrix_world.copy();o.parent=None;o.matrix_world=w
        o.modifiers.clear();o.vertex_groups.clear();o.animation_data_clear();o.select_set(True)
    bpy.context.view_layer.objects.active=meshes[0]
    if len(meshes)>1:bpy.ops.object.join()
    body=bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    original=body.data.copy()
    v=np.array([tuple(p.co) for p in original.vertices])
    # The authored fox faces -Y. Its centre and ground are independently
    # computed here, before fitting, for the expected canonical skeleton.
    off=Vector((-(v[:,0].min()+v[:,0].max())/2,-(v[:,1].min()+v[:,1].max())/2,-v[:,2].min()))
    reference_transform=Matrix.Translation(off)
    expected={name:[list(reference_transform@Vector(p)) for p in pair]
              for name,pair in reference_joints.items()}
    (folder/'reference.json').write_text(json.dumps({'joints':expected,'length':float(np.ptp(v[:,1]))}))
    def export(name):
        bpy.ops.object.select_all(action='DESELECT');body.select_set(True)
        bpy.ops.export_scene.gltf(filepath=str(folder/(name+'.glb')),use_selection=True,export_animations=False,export_skins=False)
    export('fox')
    body.data=original.copy();body.data.transform(Matrix.Diagonal((-1,1,1,1)));export('mirror')
    body.data=original.copy();body.data.transform(Matrix.Rotation(math.radians(37),4,'Z')@Matrix.Diagonal((1.8,1.8,1.8,1)));export('turned')
    # Remove the complete ground support of the positive-X front leg;
    # preserve the torso so this specifically tests missing-paw rejection.
    body.data=original.copy()
    import bmesh
    bm=bmesh.new();bm.from_mesh(body.data)
    cut=[p for p in bm.verts if p.co.x>0 and p.co.y<-.05 and p.co.z<.4*float(v[:,2].max())]
    bmesh.ops.delete(bm,geom=cut,context='VERTS');bm.to_mesh(body.data);bm.free();export('missing')
    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.mesh.primitive_cube_add(size=1)
    # A tessellated cube samples the continuous bottom face. Four corners
    # alone would resemble four isolated ground supports to vertex k-means.
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.subdivide(number_cuts=8)
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.export_scene.gltf(filepath=str(folder/'cube.glb'),use_selection=True,export_animations=False)
else:
    bpy.ops.import_scene.fbx(filepath=str(folder/stage/'quadruped_rigged.fbx'))
    arm=next(o for o in bpy.data.objects if o.type=='ARMATURE')
    (folder/stage/'joints.json').write_text(json.dumps(joints(arm)))
'''


def main():
    if not runner.is_available():
        print('SKIP quadruped fit: supported Blender unavailable:', runner.status()['error'])
        return
    assets = get_quadruped_dir()
    with tempfile.TemporaryDirectory(prefix='av-smoke-quadruped-') as tmp:
        root = Path(tmp)
        helper = root/'helper.py'
        helper.write_text(HELPER)
        def helper_run(stage):
            try:
                proc = subprocess.run([runner.find_executable(), '--background', '--factory-startup',
                '--python-exit-code', '1', '--python', str(helper), '--', str(root), str(assets), stage],
                    capture_output=True, text=True, timeout=300)
            except subprocess.TimeoutExpired as exc:
                print('FAIL Blender helper timed out in stage:', stage, flush=True)
                print((exc.stdout or b'')[-4000:], (exc.stderr or b'')[-4000:], flush=True)
                raise
            assert proc.returncode == 0, (proc.stdout+proc.stderr)[-5000:]
        helper_run('prepare')
        # A separate valid PNG, whose bytes the exporter must leave unchanged.
        from PIL import Image
        Image.new('RGB',(16,16),'red').save(root/'texture.png')
        reference = json.loads((root/'reference.json').read_text())
        results = {}
        for kind in ('fox','mirror','turned','cube','missing'):
            out=root/kind
            res=runner.run('quadruped_rig',inputs={'mesh':root/(kind+'.glb'),'texture':root/'texture.png',
                'ref':assets/'fox-animations.glb'},
                params={'clips':[],'tail_motion':'calm'},out_dir=out,timeout_s=300)
            if kind in ('cube','missing'):
                assert not res['ok'] and res['data'].get('not_applicable'), res
                assert all(key in res['error'] for key in ('cluster_min_fraction','pair_length_fraction','pair_width_fraction','outlier_fraction')),res
                print('PASS',kind,'not applicable:',res['error'])
                continue
            assert res['ok'],res
            helper_run(kind)
            results[kind]={'metrics':res['data'],'joints':json.loads((out/'joints.json').read_text())}
            assert (out/'quadruped_basecolor.png').read_bytes()==(root/'texture.png').read_bytes()
        import numpy as np
        expected=reference['joints']
        def joint_errors(actual,scale=1):
            # Blender FBX is Z-up again on import. Compare world metres.
            # Joints only (bone HEADS): FBX stores no bone tails, the importer
            # derives them from child heads, so a tail that does not touch its
            # child (Hips, Nose, Spine_2) moves on re-import by design.
            return {n: float(np.linalg.norm(np.array(actual[n][0])/scale-np.array(pair[0])))
                    /reference['length']*100 for n,pair in expected.items()}
        def max_error(actual,scale=1):
            return max(joint_errors(actual,scale).values())
        def fold(joints):
            values={}
            for k,prefix in (('front_L','Front'),('front_R','Front'),('hind_L','Back'),('hind_R','Back')):
                names=[f'{prefix}_Leg_{part}_{k[-1]}' for part in ('Upper','Lower','Ankle','Foot','Foot_1','Tip')
                       if f'{prefix}_Leg_{part}_{k[-1]}' in joints]
                total=sum(np.linalg.norm(np.array(joints[n][1])-joints[n][0]) for n in names)
                straight=np.linalg.norm(np.array(joints[names[-1]][1])-joints[names[0]][0])
                values[k]=float(total/straight)
            return values
        error=max_error(results['fox']['joints'])
        rotated_error=max_error(results['turned']['joints'],1.8)
        ref_fold=fold(expected)
        fit_fold=results['fox']['metrics']['fold']
        sym=results['mirror']['metrics']['sym_max_pct']
        print(json.dumps({'max_joint_error_pct':error,'turned_joint_error_pct':rotated_error,
            'fold_reference':ref_fold,'fold_fit':fit_fold,'sym_max_pct':sym},indent=2))
        for kind, scale, measured in (('fox', 1, error), ('turned', 1.8, rotated_error)):
            if measured > 2:
                worst = sorted(joint_errors(results[kind]['joints'], scale).items(),
                               key=lambda item: item[1], reverse=True)[:5]
                print('FAIL', kind, 'top 5 per-joint errors (% body length):',
                      json.dumps(dict(worst)), flush=True)
        assert error<=2,error
        assert rotated_error<=2,rotated_error
        assert sym<1,sym
        assert all(abs(fit_fold[k]-ref_fold[k])<=.05 for k in ref_fold),(fit_fold,ref_fold)
        assert results['fox']['metrics']['takes']==[]
        print('PASS fox self-fit, mirrored symmetry, transformed fit, acceptance and unchanged PNG')


if __name__=='__main__':
    main()
