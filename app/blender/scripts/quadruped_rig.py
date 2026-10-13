"""Fit the CC0 fox skeleton and distance weights; P3 exports no takes.

All measurements use world-space metres, Z up and the head facing -Y.
Only Blender's bundled numpy and the shared script boilerplate are used.
"""
import json
import math
import shutil
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common
sys.path.remove(_SCRIPTS_DIR)

import bpy
import numpy as np
from mathutils import Matrix, Vector

LEGS = {'front_L': 'Front_Leg_%s_L', 'front_R': 'Front_Leg_%s_R',
        'hind_L': 'Back_Leg_%s_L', 'hind_R': 'Back_Leg_%s_R'}


class NotApplicable(ValueError):
    pass


def import_objects(path):
    before = set(bpy.data.objects)
    _common.import_model(path)
    return [o for o in bpy.data.objects if o not in before]


def vertices(objects):
    return np.array([tuple(o.matrix_world @ v.co) for o in objects
                     if o.type == 'MESH' for v in o.data.vertices])


def alignment(points):
    """PCA only rotates the horizontal plane; preserve original size."""
    xy = points[:, :2] - points[:, :2].mean(0)
    _, basis = np.linalg.eigh(np.cov(xy.T))
    axis = basis[:, -1]
    rotation = Matrix.Rotation(math.pi / 2 - math.atan2(axis[1], axis[0]), 4, 'Z')
    rotated = np.array([tuple(rotation @ Vector(p)) for p in points])
    length = np.ptp(rotated[:, 1])
    if length <= 1e-9:
        raise NotApplicable('degenerate mesh: acceptance cannot be measured')
    lo = rotated[rotated[:, 1] < rotated[:, 1].min() + .15 * length, 2].max()
    hi = rotated[rotated[:, 1] > rotated[:, 1].max() - .15 * length, 2].max()
    if hi > lo:
        rotation = Matrix.Rotation(math.pi, 4, 'Z') @ rotation
        rotated = np.array([tuple(rotation @ Vector(p)) for p in points])
    offset = Vector((-(rotated[:, 0].max() + rotated[:, 0].min()) / 2,
                     -(rotated[:, 1].max() + rotated[:, 1].min()) / 2,
                     -rotated[:, 2].min()))
    return Matrix.Translation(offset) @ rotation


def landmarks(v):
    length, width, height = np.ptp(v[:, 1]), np.ptp(v[:, 0]), np.ptp(v[:, 2])
    low = v[v[:, 2] < v[:, 2].min() + .06 * height, :2]
    if min(length, width, height) <= 1e-9 or len(low) < 4:
        raise NotApplicable('acceptance: degenerate dimensions or fewer than four ground points')
    ymin = v[:, 1].min()
    centres = np.array([[s * width / 4, ymin + f * length]
                        for f in (.3, .7) for s in (1, -1)])
    for _ in range(40):
        labels = np.argmin(((low[:, None] - centres[None]) ** 2).sum(-1), 1)
        updated = np.array([low[labels == k].mean(0) if (labels == k).any()
                            else centres[k] for k in range(4)])
        if np.allclose(updated, centres, atol=1e-9 * length):
            centres = updated
            break
        centres = updated
    labels = np.argmin(((low[:, None] - centres[None]) ** 2).sum(-1), 1)
    counts = np.bincount(labels, minlength=4)
    order = np.argsort(centres[:, 1])
    front, hind = centres[order[:2]], centres[order[2:]]
    acceptance = {
        'cluster_min_fraction': float(counts.min() / len(low)),
        'pair_length_fraction': float((hind[:, 1].mean() - front[:, 1].mean()) / length),
        'pair_width_fraction': float(min(np.ptp(front[:, 0]), np.ptp(hind[:, 0])) / width),
        'outlier_fraction': float(np.mean(np.linalg.norm(low - centres[labels], axis=1) > .1 * length)),
    }
    if (acceptance['cluster_min_fraction'] < .05 or acceptance['pair_length_fraction'] < .30
            or acceptance['pair_width_fraction'] < .25 or acceptance['outlier_fraction'] > .15):
        raise NotApplicable('quadruped acceptance failed: ' + json.dumps(acceptance, sort_keys=True))
    paws = {}
    for kind, pair in (('front', front), ('hind', hind)):
        pair = pair[np.argsort(-pair[:, 0])]
        paws[kind + '_L'], paws[kind + '_R'] = pair
    fy, hy = front[:, 1].mean(), hind[:, 1].mean()
    middle = slice_at(v, length, (fy + hy) / 2, .03)
    return {'L': length, 'W': width, 'H': height, 'nose': ymin, 'tail': v[:, 1].max(),
            'fy': fy, 'hy': hy, 'paws': paws, 'thick': max(np.ptp(middle[:, 2]), 1e-9),
            'back': middle[:, 2].max(), 'belly': middle[:, 2].min(), 'acceptance': acceptance}


def slice_at(v, length, y, fraction=.015):
    band = v[np.abs(v[:, 1] - y) < fraction * length]
    return band if len(band) else v[np.argsort(np.abs(v[:, 1] - y))[:min(50, len(v))]]


def top_at(v, lm, y):
    return float(slice_at(v, lm['L'], y)[:, 2].max())


def tail_centroid(v, lm, y):
    band = slice_at(v, lm['L'], y)
    z = np.sort(band[:, 2])[::-1]
    cut = z[-1]
    for i in range(1, len(z)):
        if z[i - 1] - z[i] > .03 * lm['H']:
            cut = z[i - 1]
            break
    return band[band[:, 2] >= cut].mean(0)


def trace_leg(v, lm, key, heights):
    """Walk from this paw upwards, within 22% of body width."""
    cx, cy = lm['paws'][key]
    traced = {}
    for z in sorted(set(heights)):
        band = v[np.abs(v[:, 2] - z) < .02 * lm['H']]
        if len(band):
            near = band[np.hypot(band[:, 0] - cx, band[:, 1] - cy) < .22 * lm['W']]
            if len(near):
                cx, cy = near[:, :2].mean(0)
        traced[z] = np.array((cx, cy))
    return traced


def joint_profile(v, lm, key, leg_height):
    """Profile extrema qualify only with 0.15 local-width prominence."""
    zs = np.linspace(.1 * leg_height, .8 * leg_height, 71)
    centres = trace_leg(v, lm, key, zs)
    profile = []
    for z in zs:
        cx, cy = centres[z]
        band = v[(np.abs(v[:, 2] - z) < .02 * lm['H'])
                 & (np.hypot(v[:, 0] - cx, v[:, 1] - cy) < .22 * lm['W'])]
        if len(band):
            profile.append((z, band[:, 1].min(), band[:, 1].max(), np.ptp(band[:, 0])))
    result = {}
    kinds = [('hock', .15, .45, 2), ('knee', .45, .75, 1)]
    if key.startswith('front'):
        kinds = [('elbow', .50, .75, 2)]
    for name, low, high, column in kinds:
        rows = np.array([r for r in profile if low * leg_height <= r[0] <= high * leg_height])
        if len(rows) < 3:
            result[name] = None
            continue
        # The neighbouring range boundaries define the straight profile.
        baseline = np.interp(rows[:, 0], [rows[0, 0], rows[-1, 0]], [rows[0, column], rows[-1, column]])
        prominence = (rows[:, column] - baseline) * (1 if column == 2 else -1)
        index = int(np.argmax(prominence))
        result[name] = float(rows[index, 0]) if prominence[index] >= .15 * max(rows[index, 3], 1e-9) else None
    return result


def fit(body, arm, reference_v, target_v):
    f, t = landmarks(reference_v), landmarks(target_v)
    matrix = arm.matrix_world.copy()
    bones = {b.name: (matrix @ b.head_local, matrix @ b.tail_local) for b in arm.data.bones}
    roll_axes = {b.name: (matrix.to_3x3() @ b.matrix_local.to_3x3().col[2]).normalized()
                 for b in arm.data.bones}
    fknots, tknots = [f[k] for k in ('nose', 'fy', 'hy', 'tail')], [t[k] for k in ('nose', 'fy', 'hy', 'tail')]
    def map_y(y):
        i = 0 if y <= fknots[1] else 1 if y <= fknots[2] else 2
        return tknots[i] + (y - fknots[i]) * (tknots[i + 1] - tknots[i]) / (fknots[i + 1] - fknots[i])
    thickness, width = t['thick'] / f['thick'], t['W'] / f['W']
    length_scale = (t['hy'] - t['fy']) / (f['hy'] - f['fy'])
    def map_body(p):
        y = map_y(p.y)
        depth = top_at(reference_v, f, p.y) - p.z
        return Vector((p.x * width, y, top_at(target_v, t, y) - depth * thickness))
    new, fallbacks = {}, []
    for key, pattern in LEGS.items():
        front = key.startswith('front')
        top = pattern % ('Shoulder' if front else 'Pelvis')
        upper, ankle = pattern % 'Upper', pattern % 'Ankle'
        chain = [n for n in bones if n.startswith(pattern.split('%s')[0]) and n.endswith(pattern.split('%s')[1])]
        source_height = bones[upper][0].z
        target_height = map_body(bones[upper][0]).z
        fp = joint_profile(reference_v, f, key, source_height)
        tp = joint_profile(target_v, t, key, target_height)
        # Ratios from the fox's rest joints are used for unprominent profiles.
        joint_bones = ({'elbow': pattern % 'Lower'} if front else
                       {'hock': ankle, 'knee': pattern % 'Lower'})
        height_knots = [(0., 0.), (source_height, target_height)]
        if front:
            wrist_z = bones[ankle][0].z
            height_knots.append((wrist_z, wrist_z / source_height * target_height))
        for joint, name in joint_bones.items():
            source_z = bones[name][0].z
            if tp[joint] is None:
                fallbacks.append(key + ':' + joint)
                target_z = source_z / source_height * target_height
            else:
                # Measured on both meshes: preserve the rig's anatomical
                # offset from the surface landmark, including fox-on-fox.
                reference_z = fp[joint] if fp[joint] is not None else source_z
                target_z = tp[joint] + (source_z - reference_z) * target_height / source_height
            height_knots.append((source_z, target_z))
        height_knots.sort()
        def map_z(z):
            return float(np.interp(z, [x[0] for x in height_knots], [x[1] for x in height_knots]))
        points = {(n, i): bones[n][i] for n in chain for i in (0, 1)}
        source_trace = trace_leg(reference_v, f, key, [p.z for p in points.values()])
        target_trace = trace_leg(target_v, t, key, [map_z(p.z) for p in points.values()])
        for (n, i), p in points.items():
            if n == top or (n == upper and i == 0):
                q = map_body(p)
            else:
                z = map_z(p.z)
                xy = target_trace[z] + (np.array((p.x, p.y)) - source_trace[p.z]) * np.array((width, length_scale))
                if 'Foot' in n or 'Tip' in n or p.y < bones[ankle][0].y - 1e-6:
                    a = bones[ankle][0]
                    anchor = target_trace[map_z(a.z)] + (np.array((a.x, a.y)) - source_trace[a.z]) * np.array((width, length_scale))
                    xy = anchor + np.array((p.x - a.x, p.y - a.y)) * np.array((width, length_scale))
                q = Vector((xy[0], xy[1], z))
            new[n, i] = q
    for n, pair in bones.items():
        for i, p in enumerate(pair):
            if (n, i) in new:
                continue
            if n == 'root':
                q = Vector((p.x * width, map_y(p.y), p.z * t['H'] / f['H']))
            elif n.startswith('Tail'):
                y = map_y(p.y)
                fc, tc = tail_centroid(reference_v, f, p.y), tail_centroid(target_v, t, y)
                q = Vector((tc[0] + (p.x - fc[0]) * width, y,
                            tc[2] + (p.z - fc[2]) * thickness))
            else:
                q = map_body(p)
            new[n, i] = q
    bpy.ops.object.select_all(action='DESELECT')
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    inv = matrix.inverted()
    for b in arm.data.edit_bones:
        b.use_connect = False
    for b in arm.data.edit_bones:
        b.head, b.tail = inv @ new[b.name, 0], inv @ new[b.name, 1]
        if b.length < 1e-9:
            b.tail = b.head + Vector((0, 0, 1e-6 * t['L']))
        b.align_roll(matrix.to_3x3().inverted() @ roll_axes[b.name])
    bpy.ops.object.mode_set(mode='OBJECT')
    arm.data.bones['root'].use_deform = False
    fold = fold_metric(arm)
    sym = []
    for n in bones:
        if n.endswith('_L') and n[:-2] + '_R' in bones:
            for i in (0, 1):
                p, q = new[n, i], new[n[:-2] + '_R', i]
                sym.append((Vector((-p.x, p.y, p.z)) - q).length)
    return {'fold': fold, 'fold_mean': sum(fold.values()) / 4,
            'sym_max_pct': 100 * max(sym, default=0) / math.sqrt(t['L']**2 + t['W']**2 + t['H']**2),
            'landmark_fallback': fallbacks, 'takes': [], 'acceptance': t['acceptance'],
            'dims_m': [float(t[k]) for k in ('W', 'L', 'H')]}


def fold_metric(arm):
    matrix = arm.matrix_world
    result = {}
    for key, pat in LEGS.items():
        # Include every segment, including the fox's extra hind Foot_1.
        chain = []
        bone = arm.data.bones[pat % 'Tip']
        while bone is not None:
            chain.append(bone)
            if bone.name == pat % 'Upper':
                break
            bone = bone.parent
        chain.reverse()
        length = sum((matrix @ b.tail_local - matrix @ b.head_local).length for b in chain)
        straight = (matrix @ chain[-1].tail_local - matrix @ chain[0].head_local).length
        result[key] = length / max(straight, 1e-12)
    return result


def skin(body, arm, length):
    p = vertices([body])
    segs = [(b.name, np.array(arm.matrix_world @ b.head_local), np.array(arm.matrix_world @ b.tail_local))
            for b in arm.data.bones if b.use_deform]
    distances = np.empty((len(p), len(segs)))
    for j, (_, head, tail) in enumerate(segs):
        d = tail - head
        u = np.clip(((p - head) @ d) / max(float(d @ d), 1e-12), 0, 1)
        distances[:, j] = np.linalg.norm(p - head - u[:, None] * d, axis=1)
    nearest = np.argsort(distances, axis=1)[:, :4]
    weights = np.zeros_like(distances)
    ds = np.maximum(np.take_along_axis(distances, nearest, axis=1), 1e-9 * length)
    np.put_along_axis(weights, nearest, ds ** -4, axis=1)
    weights /= weights.sum(1, keepdims=True)
    _, weld = np.unique(np.round(p / (1e-5 * length)).astype(np.int64), axis=0, return_inverse=True)
    weld = weld.ravel()
    edges = np.array([tuple(e.vertices) for e in body.data.edges], dtype=np.int64).reshape(-1, 2)
    # Unique welded edges prevent UV seam duplication from changing smoothing.
    edges = np.unique(np.sort(weld[edges], axis=1), axis=0)
    edges = edges[edges[:, 0] != edges[:, 1]]
    start = np.concatenate((edges[:, 0], edges[:, 1]))
    end = np.concatenate((edges[:, 1], edges[:, 0]))
    count = int(weld.max()) + 1
    welded = np.zeros((count, len(segs)))
    np.add.at(welded, weld, weights)
    welded /= np.bincount(weld, minlength=count)[:, None]
    degree = np.bincount(start, minlength=count)[:, None]
    for _ in range(20):
        acc = np.zeros_like(welded)
        np.add.at(acc, start, welded[end])
        average = np.divide(acc, degree, out=welded.copy(), where=degree > 0)
        welded = .5 * welded + .5 * average
    weights = welded[weld]
    weights[weights < .01] = 0
    weights /= weights.sum(1, keepdims=True)
    body.vertex_groups.clear()
    for j, (name, _, _) in enumerate(segs):
        group = body.vertex_groups.new(name=name)
        for i in np.flatnonzero(weights[:, j]):
            group.add([int(i)], float(weights[i, j]), 'REPLACE')
    body.parent = arm
    body.matrix_parent_inverse = arm.matrix_world.inverted()
    modifier = body.modifiers.new('Armature', 'ARMATURE')
    modifier.object = arm


def run(job):
    inputs, params = job['inputs'], job.get('params') or {}
    if params.get('clips'):
        raise ValueError('P3 requires clips: []')
    _common.reset_scene()
    objects = import_objects(inputs['mesh'])
    meshes = [o for o in objects if o.type == 'MESH']
    if not meshes:
        raise NotApplicable('no mesh to measure; quadruped acceptance unavailable')
    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes:
        # Keep world geometry when removing any imported parent.
        world = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = world
        o.modifiers.clear()
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    body = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    transform = alignment(vertices([body]))
    body.data.transform(transform)
    target_v = vertices([body])
    landmarks(target_v)  # Reject before importing reference assets.
    ref_objects = import_objects(inputs['ref'])
    arm = next(o for o in ref_objects if o.type == 'ARMATURE')
    # The animation asset's rest skeleton matches its mesh and source clips.
    arm.animation_data_clear()
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    reference_v = vertices(ref_objects)
    ref_transform = alignment(reference_v)
    reference_v = np.array([tuple(ref_transform @ Vector(p)) for p in reference_v])
    arm.matrix_world = ref_transform @ arm.matrix_world
    for o in ref_objects:
        if o != arm:
            bpy.data.objects.remove(o, do_unlink=True)
    bpy.context.view_layer.update()
    metrics = fit(body, arm, reference_v, target_v)
    skin(body, arm, metrics['dims_m'][1])
    # Preserve the separate, unchanged PNG and bind it to the mesh material.
    image = bpy.data.images.load(inputs['texture'], check_existing=True)
    material = bpy.data.materials.new('Quadruped basecolor')
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get('Principled BSDF')
    tex = material.node_tree.nodes.new('ShaderNodeTexImage')
    tex.image = image
    material.node_tree.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    body.data.materials.clear()
    body.data.materials.append(material)
    for polygon in body.data.polygons:
        polygon.material_index = 0
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action)
    bpy.context.scene.unit_settings.system = 'METRIC'
    bpy.context.scene.unit_settings.scale_length = 1.0
    bpy.context.scene.render.fps = 24
    out = Path(job['out_dir'])
    fbx, png, metric_file = out / 'quadruped_rigged.fbx', out / 'quadruped_basecolor.png', out / 'metrics.json'
    shutil.copyfile(inputs['texture'], png)
    image.filepath = str(png)
    bpy.ops.object.select_all(action='DESELECT')
    body.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.fbx(filepath=str(fbx), use_selection=True,
        object_types={'ARMATURE', 'MESH'}, add_leaf_bones=False, bake_anim=False,
        bake_anim_use_nla_strips=True, bake_anim_use_all_actions=False,
        bake_anim_force_startend_keying=True, axis_forward='-Z', axis_up='Y',
        path_mode='STRIP', embed_textures=False)
    metric_file.write_text(json.dumps(metrics, indent=2))
    return metrics, {'mesh': str(fbx), 'texture': str(png), 'metrics': str(metric_file)}


if __name__ == '__main__':
    job = _common.read_args()
    try:
        data, outputs = run(job)
        _common.write_result(job, True, data=data, outputs=outputs)
    except NotApplicable as exc:
        reason = str(exc)
        failure = {'ok': False, 'not_applicable': True, 'reason': reason}
        Path(job['result']).write_text(json.dumps({**failure, 'error': reason,
            'data': failure, 'outputs': {}}))
    except Exception:
        import traceback
        _common.write_result(job, False, error=traceback.format_exc())
        raise SystemExit(1)
