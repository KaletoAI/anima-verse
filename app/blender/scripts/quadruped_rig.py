"""Fit the CC0 fox skeleton, skin and bake embedded quadruped takes.

All measurements use world-space metres, Z up and the head facing -Y.
Only Blender's bundled numpy and the shared script boilerplate are used.
"""
import json
from fnmatch import fnmatchcase
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
from mathutils import Matrix, Vector, Quaternion

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


def skin_weights(p, segs, edges, length):
    """Compute welded, capped and re-smoothed weights using only NumPy."""
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
    edges = np.asarray(edges, dtype=np.int64).reshape(-1, 2)
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
    welded[welded < .01] = 0
    # Smoothing spreads influences; FBXLoader and glTF keep at most four.
    smallest = np.argsort(welded, axis=1)[:, :-4]
    np.put_along_axis(welded, smallest, 0, axis=1)
    mask = welded > 0
    welded /= welded.sum(1, keepdims=True)
    # Cat 7 walk/sit/run p99.9: capping raised 4.5/3.9/7.6 to 5.4/5.3/9.2.
    # Re-smoothing within the kept bones (60 iterations) reduced it to 4.2/4.3/7.25.
    for _ in range(60):
        acc = np.zeros_like(welded)
        np.add.at(acc, start, welded[end])
        average = np.divide(acc, degree, out=welded.copy(), where=degree > 0)
        previous = welded
        welded = np.where(mask, .5 * welded + .5 * average, 0)
        total = welded.sum(1, keepdims=True)
        welded = np.divide(welded, total, out=previous.copy(), where=total > 0)
    weights = welded[weld]
    assert np.all(np.count_nonzero(weights, axis=1) <= 4)
    return weights


def skin(body, arm, length):
    p = vertices([body])
    segs = [(b.name, np.array(arm.matrix_world @ b.head_local), np.array(arm.matrix_world @ b.tail_local))
            for b in arm.data.bones if b.use_deform]
    edges = [tuple(e.vertices) for e in body.data.edges]
    weights = skin_weights(p, segs, edges, length)
    body.vertex_groups.clear()
    for j, (name, _, _) in enumerate(segs):
        group = body.vertex_groups.new(name=name)
        for i in np.flatnonzero(weights[:, j]):
            group.add([int(i)], float(weights[i, j]), 'REPLACE')
    body.parent = arm
    body.matrix_parent_inverse = arm.matrix_world.inverted()
    modifier = body.modifiers.new('Armature', 'ARMATURE')
    modifier.object = arm


def assign_action(arm, action):
    arm.animation_data_create()
    arm.animation_data.action = action
    if action and action.slots:
        arm.animation_data.action_slot = action.slots[0]


def pose_order(arm):
    order = []
    def visit(bone):
        order.append(bone.name)
        for child in bone.children:
            visit(child)
    for bone in arm.data.bones:
        if bone.parent is None:
            visit(bone)
    return order


def apply_pose(arm, pose, rest, order):
    """Convert the explicit world pose to parent-relative basis matrices."""
    for name in order:
        pb = arm.pose.bones[name]
        parent = pb.parent.name if pb.parent else None
        relative = rest[parent].inverted() @ rest[name] if parent else rest[name]
        parent_pose = pose[parent] if parent else Matrix.Identity(4)
        pb.rotation_mode = 'QUATERNION'
        pb.matrix_basis = relative.inverted() @ parent_pose.inverted() @ pose[name]
    bpy.context.view_layer.update()


def solve_leg(pose, rest, order, arm, pattern, front, pole):
    """Analytic two-link IK; distal world rotations remain the retarget's."""
    names = [pattern % p for p in (('Upper', 'Lower', 'Ankle') if front else ('Lower', 'Ankle', 'Foot'))]
    a, b, c = names
    tip = pattern % 'Tip'
    tip_tail = pose[tip] @ (rest[tip].inverted() @ (arm.matrix_world @ arm.data.bones[tip].tail_local))
    start, mid, end = [pose[n].translation.copy() for n in names]
    rest_height = (arm.matrix_world @ arm.data.bones[tip].tail_local).z
    goal = end - Vector((0, 0, tip_tail.z - rest_height))
    l1 = (rest[b].translation - rest[a].translation).length
    l2 = (rest[c].translation - rest[b].translation).length
    delta = goal - start
    distance = delta.length
    axis = delta.normalized() if distance > 1e-10 else Vector((0, 0, -1))
    unreachable = distance > l1 + l2 or distance < abs(l1 - l2)
    reach = l1 + l2 if unreachable else max(distance, 1e-10)
    bend = pole - axis * pole.dot(axis)
    if bend.length < 1e-9:
        bend = (mid - start) - axis * (mid - start).dot(axis)
    if bend.length < 1e-9:
        basis = min((Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))),
                    key=lambda candidate: abs(axis.dot(candidate)))
        bend = axis.cross(basis)
    bend.normalize()
    along = (l1*l1 + reach*reach - l2*l2) / (2*max(reach, 1e-10))
    new_mid = start + axis * along + bend * math.sqrt(max(0, l1*l1 - along*along))
    new_end = start + axis * reach
    old = {n: m.copy() for n, m in pose.items()}
    for name, origin, old_vec, new_vec in (
            (a, start, mid-start, new_mid-start), (b, new_mid, end-mid, new_end-new_mid)):
        rotation = old_vec.normalized().rotation_difference(new_vec.normalized())
        pose[name] = Matrix.Translation(origin) @ rotation.to_matrix().to_4x4() @ old[name].to_quaternion().to_matrix().to_4x4()
    # Move the end joint and every distal bone as a rigid offset, preserving
    # their world rotations. Other branches follow their parent joint.
    for name in order:
        if name in (a, b):
            continue
        parent = arm.data.bones[name].parent
        if parent and (parent.name in (a, b) or pose[parent.name] != old[parent.name]):
            pose[name].translation = (pose[parent.name] @ (rest[parent.name].inverted() @ rest[name])).translation
    pose[c].translation = new_end
    for name in order:
        parent = arm.data.bones[name].parent
        if parent and (parent.name == c or arm.data.bones[name] in arm.data.bones[c].children_recursive):
            pose[name].translation = (pose[parent.name] @ (rest[parent.name].inverted() @ rest[name])).translation
    return unreachable


def evaluated_vertices(body):
    ev = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = ev.to_mesh()
    result = np.array([tuple(body.matrix_world @ v.co) for v in mesh.vertices])
    ev.to_mesh_clear()
    return result


def bake_clips(body, arm, sources, catalog, reference_v, target_v, mode):
    """24fps world-delta retarget, contact IK, tail clearance and NLA takes."""
    if mode not in ('full', 'calm', 'still'):
        raise ValueError('unknown tail_motion: ' + str(mode))
    order = pose_order(arm)
    rest = {b.name: arm.matrix_world @ b.matrix_local for b in arm.data.bones}
    contact_rest_z = {key: (arm.matrix_world @ arm.data.bones[pattern % 'Tip'].tail_local).z
                      for key, pattern in LEGS.items()}
    target_lm = landmarks(target_v)
    tail_indices = [v.index for v in body.data.vertices if sum(g.weight for g in v.groups
                    if body.vertex_groups[g.group].name.startswith('Tail')) > .5]
    # Tail vertices and paws of legs currently controlled by contact IK are exempt.
    paw_weights = {}
    for key, pattern in LEGS.items():
        groups = {g.index for g in body.vertex_groups
                  if any(fnmatchcase(g.name, pattern % part) for part in ('Ankle', 'Foot*', 'Tip'))}
        paw_weights[key] = np.array([sum(g.weight for g in v.groups if g.group in groups)
                                    for v in body.data.vertices])
    edges = np.array([tuple(e.vertices) for e in body.data.edges], dtype=int).reshape(-1, 2)
    lengths = np.linalg.norm(target_v[edges[:, 0]] - target_v[edges[:, 1]], axis=1)
    valid = lengths > 1e-8 * target_lm['L']
    metrics, actions, idle_offset = {}, [], None
    for take, declaration in catalog.items():
        src, source_actions, source_v = sources[declaration['src']]
        action = source_actions.get(declaration['action'])
        if action is None:
            raise ValueError('missing source action: ' + declaration['action'])
        effective_mode = declaration.get('tail', {}).get(mode, mode)
        mapping = {n: n for n in order}
        if any(n not in src.data.bones for n in mapping.values()):
            raise ValueError('fox source is missing a target bone')
        source_rest = {b.name: src.matrix_world @ b.matrix_local for b in src.data.bones}
        source_lm = landmarks(source_v)
        ratio = target_lm['back'] / source_lm['back']
        assign_action(src, action)
        f0, f1 = action.frame_range
        count = int(math.ceil(f1 - f0)) + 1
        samples, contacts = [], {k: [] for k in LEGS}
        for i in range(count):
            t = min(f1, f0+i)
            bpy.context.scene.frame_set(int(math.floor(t)), subframe=t-math.floor(t))
            world = {b.name: src.matrix_world @ b.matrix for b in src.pose.bones}
            samples.append(world)
            for key, pattern in LEGS.items():
                name = mapping.get(pattern % 'Tip')
                if name is None:
                    raise ValueError('missing contact bone mapping: ' + pattern % 'Tip')
                contacts[key].append(src.matrix_world @ src.pose.bones[name].tail)
        masks = {}
        for key, points in contacts.items():
            source_rest_z = (src.matrix_world @ src.data.bones[mapping[LEGS[key] % 'Tip']].tail_local).z
            masks[key] = [p.z - source_rest_z <= .02*source_lm['H']
                and (p-points[max(0,i-1)]).length < .01*source_lm['L']
                and (p-points[min(count-1,i+1)]).length < .01*source_lm['L']
                for i,p in enumerate(points)]
        poses, errors = [], []
        for i, world in enumerate(samples):
            pose = {}
            for name in order:
                bone = arm.data.bones[name]
                parent = bone.parent.name if bone.parent else None
                inherited = pose[parent] @ (rest[parent].inverted() @ rest[name]) if parent else rest[name].copy()
                source_name = mapping.get(name)
                if source_name is None:
                    pose[name] = inherited
                    continue
                sw = world[source_name]
                delta = sw.to_quaternion() @ source_rest[source_name].to_quaternion().inverted()
                if name.startswith('Tail'):
                    if effective_mode == 'still':
                        pose[name] = inherited
                        continue
                    if effective_mode == 'calm':
                        # Swing/twist about WORLD up: preserve pitch and roll.
                        twist = Quaternion((delta.w, 0, 0, delta.z)).normalized()
                        swing = delta @ twist.inverted()
                        angle = 2*math.atan2(twist.z, twist.w)
                        angle = (angle+math.pi) % (2*math.pi)-math.pi
                        delta = swing @ Quaternion(Vector((0,0,1)), .2*angle)
                translation = inherited.translation
                if parent is None or name == 'Hips':
                    translation = rest[name].translation + (sw.translation-source_rest[source_name].translation)*ratio
                pose[name] = Matrix.Translation(translation) @ (delta @ rest[name].to_quaternion()).to_matrix().to_4x4()
            poses.append(pose)
            for key, pattern in LEGS.items():
                if masks[key][i]:
                    name = pattern % 'Tip'
                    tail = pose[name] @ (rest[name].inverted() @ (arm.matrix_world @ arm.data.bones[name].tail_local))
                    errors.append(tail.z - contact_rest_z[key])
        if errors:
            offset = -float(np.median(errors))
        elif idle_offset is not None:
            offset = idle_offset
        else:
            raise ValueError('idle must precede contactless clips')
        if take == 'idle':
            idle_offset = offset
        assign_action(arm, None)
        baked = bpy.data.actions.new(take)
        assign_action(arm, baked)
        max_error, minimum_tail, unreachable, stretches = 0., math.inf, 0, []
        tail_clearance_unreached = 0
        ground_lift_max = 0.
        tail_floor = -.002 * target_lm['H']
        for i, pose in enumerate(poses):
            # The offset is constant for the WHOLE clip, including flight.
            for matrix in pose.values():
                matrix.translation.z += offset
            failed = False
            for key, pattern in LEGS.items():
                if not masks[key][i]:
                    continue
                front = key.startswith('front')
                source_names = [mapping[pattern % p] for p in (('Upper','Lower','Ankle') if front else ('Lower','Ankle','Foot'))]
                a,b,c = [samples[i][n].translation for n in source_names]
                axis = (c-a).normalized()
                pole = (b-a)-axis*(b-a).dot(axis)
                failed |= solve_leg(pose, rest, order, arm, pattern, front, pole)
            unreachable += int(failed)
            apply_pose(arm, pose, rest, order)
            def tail_min():
                co = evaluated_vertices(body)
                return float(co[tail_indices, 2].min()) if tail_indices else 0.
            low = tail_min()
            if effective_mode != 'still' and low < tail_floor:
                original = {n: pose[n].copy() for n in order if n.startswith('Tail')}
                pivot = pose['Tail_Base'].translation.copy()
                def lift(angle):
                    transform = Matrix.Translation(pivot) @ Matrix.Rotation(angle,4,'X') @ Matrix.Translation(-pivot)
                    for n, matrix in original.items():
                        pose[n] = transform @ matrix
                    apply_pose(arm, pose, rest, order)
                    return tail_min()
                # Positive X raises a tail extending towards +Y; cap at 30 degrees.
                lo, hi = 0., math.pi/6
                raised = lift(hi)
                if raised < tail_floor:
                    # Keep the better pose even when clearance is unreachable.
                    low = lift(hi if raised >= low else 0.)
                    tail_clearance_unreached += 1
                else:
                    for _ in range(8):
                        mid = (lo+hi)/2
                        if lift(mid) >= tail_floor:
                            hi = mid
                        else:
                            lo = mid
                    low = lift(hi)
            # Explicit poses are world matrices: translating every matrix
            # changes only ROOT's relative location, preserving the child pose.
            # Do this after IK and tail clearance, and never pull a frame down.
            co = evaluated_vertices(body)
            excluded = np.zeros(len(co), dtype=bool)
            excluded[tail_indices] = True
            for key, weights in paw_weights.items():
                if masks[key][i]:
                    excluded |= weights > .5
            mesh_min = float(co[~excluded, 2].min()) if (~excluded).any() else 0.
            # Leave 0.001% H for float roundoff during the FBX roundtrip.
            ground_lift = (tail_floor - mesh_min + 1e-5*target_lm['H']
                           if mesh_min < tail_floor else 0.)
            if ground_lift > 0.:
                for matrix in pose.values():
                    matrix.translation.z += ground_lift
                apply_pose(arm, pose, rest, order)
                co = evaluated_vertices(body)
                low = float(co[tail_indices, 2].min()) if tail_indices else 0.
            ground_lift_max = max(ground_lift_max, ground_lift)
            minimum_tail = min(minimum_tail, low)
            for key, pattern in LEGS.items():
                if masks[key][i]:
                    max_error = max(max_error, abs(
                        (arm.matrix_world @ arm.pose.bones[pattern % 'Tip'].tail).z - contact_rest_z[key]))
            co = evaluated_vertices(body)
            stretch = np.linalg.norm(co[edges[:,0]]-co[edges[:,1]],axis=1)[valid]/lengths[valid]
            stretches.append(float(np.percentile(stretch,99.9)))
            for name in order:
                pb = arm.pose.bones[name]
                pb.keyframe_insert('location', frame=i+1)
                pb.keyframe_insert('rotation_quaternion', frame=i+1)
                pb.keyframe_insert('scale', frame=i+1)
        metrics[take] = {'stretch_p999': max(stretches),
            'contact_err_max': 100*max_error/target_lm['H'], 'tail_min_z': minimum_tail,
            'ik_unreachable': unreachable, 'tail_clearance_unreached': tail_clearance_unreached,
            'ground_lift_max': 100*ground_lift_max/target_lm['H'],
            'loop': declaration['loop']}
        actions.append((take,baked,count))
    for src, _, _ in sources.values():
        bpy.data.objects.remove(src, do_unlink=True)
    assign_action(arm, None)
    keep = {action for _,action,_ in actions}
    for action in list(bpy.data.actions):
        if action not in keep:
            bpy.data.actions.remove(action)
    for take, action, count in actions:
        track = arm.animation_data.nla_tracks.new()
        track.name = take
        strip = track.strips.new(take, 1, action)
        strip.name = take
        strip.action_frame_start, strip.action_frame_end = 1, count
        strip.blend_type = 'REPLACE'
        strip.extrapolation = 'NOTHING'
    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = max((n for _,_,n in actions), default=1)
    return metrics


def run(job):
    inputs, params = job['inputs'], job.get('params') or {}
    catalog = params.get('clips') or {}
    mode = params.get('tail_motion', 'calm')
    if mode not in ('full', 'calm', 'still'):
        raise ValueError('unknown tail_motion: ' + str(mode))
    for take, declaration in catalog.items():
        unknown = set(declaration) - {'src', 'action', 'loop', 'tail'}
        if unknown:
            raise ValueError('unknown take declaration keys: ' + ', '.join(sorted(unknown)))
        if declaration['src'] != 'fox':
            raise ValueError('unknown take source: ' + str(declaration['src']))
        overrides = declaration.get('tail', {})
        if not isinstance(overrides, dict) or any(
                key not in ('full', 'calm', 'still') or value not in ('full', 'calm', 'still')
                for key, value in overrides.items()):
            raise ValueError('unknown tail override: ' + str(overrides))
    _common.reset_scene()
    bpy.context.scene.render.fps = 24
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
    sources = {}
    if catalog:
        fox = arm.copy()
        fox.data = arm.data.copy()
        bpy.context.collection.objects.link(fox)
        fox.animation_data_clear()
        sources['fox'] = (fox, {a.name: a for a in bpy.data.actions}, reference_v)
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
    bpy.context.scene.render.fps = 24
    if catalog:
        metrics['clips'] = bake_clips(body, arm, sources, catalog, reference_v, target_v, mode)
        metrics['takes'] = list(catalog)
    else:
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
        object_types={'ARMATURE', 'MESH'}, add_leaf_bones=False, bake_anim=bool(catalog),
        bake_anim_use_nla_strips=True, bake_anim_use_all_actions=False,
        bake_anim_force_startend_keying=True, bake_anim_step=1.0,
        bake_anim_simplify_factor=0.0, axis_forward='-Z', axis_up='Y',
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
