"""Reverse a finished library FBX without retargeting or stripping its root."""
import json
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common
from _clip_scene import sample, write_root
from _action import curves
import cmu_clip
import clip_orient
import clip_root_motion
import proc_clip
sys.path.remove(_SCRIPTS_DIR)

import bpy
from mathutils import Matrix


FLOOR_TARGET = 0.0  # cm, in the client's rendered space


def lift_rendered_floor(arm, frames, hips, support):
    """Smooth measured-head deficits; re-sample because lift also changes p."""
    applied = [0.0] * len(frames)
    rest = arm.data.bones[hips].matrix_local.copy()

    def measure():
        mats, joints = sample(arm, frames)
        h0 = joints[frames[0]][hips][0].y
        span = joints[frames[-1]][hips][0].y - h0
        lows = []
        for f in frames:
            p = max(0.0, min(1.0, (joints[f][hips][0].y - h0) / span)) if span else 0.0
            lows.append(min(joints[f][cmu_clip.PREFIX + name][0].y
                            for name in proc_clip.MEASURED) + support * p)
        return mats, lows

    mats, lows = measure()
    for attempt in range(3):
        deficit = [max(0.0, FLOOR_TARGET - low) for low in lows]
        # FBX float noise is sub-millimetre; endpoints must never be moved.
        if max(deficit[0], deficit[-1]) > 1e-3:
            raise ValueError('Rendered floor deficit at an immutable endpoint')
        deficit[0] = deficit[-1] = 0.0
        if not any(deficit):
            break
        radius = 6
        envelope = [max(deficit[max(0, i-radius):i+radius+1])
                    for i in range(len(frames))]
        smooth = [sum(envelope[max(0, i-radius):i+radius+1]) /
                  len(envelope[max(0, i-radius):i+radius+1])
                  for i in range(len(frames))]
        smooth[0] = smooth[-1] = 0.0
        # Raising on retries compensates for the client's changed hips ratio.
        smooth = [v * (attempt + 1) for v in smooth]
        moved = {f: Matrix.Translation((0.0, smooth[i], 0.0)) @ mats[f][hips]
                 for i, f in enumerate(frames)}
        write_root(arm, hips, moved, rest)
        applied = [a + d for a, d in zip(applied, smooth)]
        mats, lows = measure()
        if min(lows) >= -0.5:
            break
    if min(lows) < -0.5:
        raise ValueError('Rendered floor remains below -0.5 cm after three lifts')
    assert applied[0] == applied[-1] == 0.0
    return max(applied)


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
    frames = list(range(f0, f1 + 1))
    mats, joints = sample(arm, frames)
    hips = cmu_clip.PREFIX + 'Hips'
    # Match proc_clip._measure: measured joint HEADS, armature +Y, cm.
    support = -min(joints[f0][cmu_clip.PREFIX + name][0].y
                   for name in proc_clip.MEASURED)
    if support > 1.0:
        first_y = mats[f0][hips].translation.y
        last_y = mats[f1][hips].translation.y
        span = first_y - last_y
        if abs(span) < 1e-4:
            raise ValueError('Cannot unbake support height: reversed hips start/end '
                             'heights are equal (within 0.0001 cm)')
        moved = {}
        for f in frames:
            ratio = max(0.0, min(1.0, (mats[f][hips].translation.y - last_y) / span))
            moved[f] = Matrix.Translation((0.0, support * ratio, 0.0)) @ mats[f][hips]
        # Convert armature +Y through the rest matrix into bone-local location.
        write_root(arm, hips, moved, arm.data.bones[hips].matrix_local.copy())
    else:
        support = 0.0
    floor_lift = lift_rendered_floor(arm, frames, hips, support)
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
    # Keep the uniform floor shift/orientation history. The time-varying
    # support correction is separate; contacts and travel are re-measured.
    meta.update(kind=kind, loop=False, pair=False)
    geometry = meta.setdefault('geometry', {})
    geometry['root_motion'] = motion
    geometry['support_unbaked_cm'] = round(support, 3)
    geometry['floor_lift_max_cm'] = round(floor_lift, 3)
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
