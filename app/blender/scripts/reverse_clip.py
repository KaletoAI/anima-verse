"""Reverse a finished library FBX without retargeting or stripping its root."""
import json
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common
from _action import curves
import cmu_clip
import clip_orient
import clip_root_motion
import proc_clip
sys.path.remove(_SCRIPTS_DIR)

import bpy


def run(job):
    inputs, params = job['inputs'], job['params']
    meta = json.loads(Path(inputs['sidecar']).read_text(encoding='utf-8'))
    if meta.get('loop') or meta.get('pair'):
        raise ValueError('Reversed requires a non-looping solo clip')
    fps = int(meta['fps'])
    _common.reset_scene()
    arm = clip_orient._import_armature(inputs['src'], fps)
    f0, f1 = (int(round(f)) for f in arm.animation_data.action.frame_range)
    if f1 - f0 + 1 != meta['frames']:
        raise ValueError('source sidecar frame count disagrees with FBX')
    # FBX imports are sampled at scene fps. Bake every animated channel at
    # those same samples in reverse; linear keys avoid Bezier overshoot.
    for owner in list(bpy.data.objects):
        if not owner.animation_data or not owner.animation_data.action:
            continue
        for fc in curves(owner):
            values = [fc.evaluate(f1 - i) for i in range(f1 - f0 + 1)]
            fc.keyframe_points.clear()
            fc.keyframe_points.add(len(values))
            for i, value in enumerate(values):
                key = fc.keyframe_points[i]
                key.co = (f0 + i, value)
                key.interpolation = 'LINEAR'
            fc.update()
    cmu_clip.DRIVEN.clear()
    cmu_clip.DRIVEN.update(fc.data_path.split('"')[1][len(cmu_clip.PREFIX):]
                          for fc in curves(arm)
                          if fc.data_path.startswith('pose.bones["' + cmu_clip.PREFIX)
                          and fc.data_path.endswith('rotation_quaternion'))
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = f0, f1
    out = Path(job['out_dir'])
    kind = params['kind']
    dst = out / f'{kind}.fbx'
    cmu_clip._export(arm, dst)
    measure_path = proc_clip._measure(str(dst), out, fps)
    # Use the reference rig's contacts and heights, exactly as the existing
    # measure-only job does; measure the exported file, not the working action.
    root, _ = clip_root_motion.run({'inputs': {'src': str(dst), 'rig': inputs['rig']},
                                  'params': {'fps': fps, 'measure_only': True}})
    a, b = root['hips_xz'][0], root['hips_xz'][-1]
    motion = {'mode': 'keep', 'travel_m': [round((y-x)/100, 3) for x, y in zip(a, b)],
              'ref_height_m': root['ref_height_m'], 'contact_s': root['contact_s'],
              'max_drift_cm': root['max_drift_cm']}
    # Reversal visits the identical poses: floor shifts, lift, scales and
    # orientation stay valid. Contacts and travel depend on time and are new.
    meta.update(kind=kind, loop=False, pair=False)
    geometry = meta.setdefault('geometry', {})
    geometry['root_motion'] = motion
    if 'despiked' in geometry:
        geometry['despiked'] = {role: {bone: sorted(meta['frames'] - 1 - f for f in fixed)
                                     for bone, fixed in bones.items()}
                                for role, bones in geometry['despiked'].items()}
    meta['source'] = {**meta.get('source', {}), 'reversed_from': params['source'],
                      'studio': 'animation-studio',
                      'studio_spec': f'animation-studio/anims/{kind}.py',
                      'studio_spec_sha': params['spec_sha']}
    side = out / f'{kind}.json'
    side.write_text(json.dumps(meta, indent=1), encoding='utf-8')
    return meta, {kind: str(dst), 'sidecar': str(side), 'measure': measure_path}


if __name__ == '__main__':
    _common.main(run)
