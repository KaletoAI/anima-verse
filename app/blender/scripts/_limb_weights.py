"""Removes impossible limb influences from the pelvis of a humanoid rig.

The humanoid rigger sometimes gives pelvis vertices weights of hands, fingers,
feet or toes (one model: 283 vertices with nothing else, the hand bone a metre
away). Walking then drags those faces along with the swinging arms and legs.
In the Mixamo bind pose (arms out, palms down) no shoulder, arm, hand, foot,
toe, neck or head bone comes near the pelvis, so any such weight inside the
window below the Hips joint is a rigger defect. Knee (``*Leg``), spine, hips
and thigh weights stay: many models carry legitimate knee weights there.

The removed share is filled harmonically from the neighbours (mesh edges plus
coincident seam copies): assigning the nearest bone instead tears the midline,
where left and right thigh vertices meet.

Runs on a normalised model only (metres, grounded), so the window is metric.
"""
from collections import Counter

import bpy
from mathutils.kdtree import KDTree

from app.core.head_twist import bone_name
from app.core.rig_contract import BASE_JOINT_KEYS

HALF_WIDTH_M = 0.12  # Lateral reach from the Hips joint: crotch and inner thighs, never the hands.
DEPTH_M = 0.30  # Down from the Hips joint to mid-thigh, where the defect was measured.
COINCIDENT_EPSILON_M = 1e-5  # Reconnect UV seams and crease copies in metres.
TOLERANCE = 1e-7  # Stop once influence changes are below export precision.
MAX_ITERATIONS = 500  # Bound work even on poorly connected meshes.
MIN_WEIGHT = 1e-4  # Discard negligible influences before export.
FORBIDDEN = ('shoulder', 'arm', 'hand', 'foot', 'toe', 'neck', 'head')


def _report():
    return {'vertices': 0, 'fully_foreign': 0, 'unresolved': 0,
            'removed_weight': 0, 'bones': {}, 'iterations': 0,
            'window': {'half_width': HALF_WIDTH_M, 'depth': DEPTH_M},
            'error': '', 'skipped': ''}


def _prepare(arm, report):
    names = {bone_name(b.name): b for b in arm.data.bones}
    anchor = arm.matrix_world @ names['hips'].head_local
    objects = [o for o in bpy.context.scene.objects if o.type == 'MESH'
               and any(m.type == 'ARMATURE' and m.object == arm for m in o.modifiers)]
    entries, positions, neighbours, known, sums, foreign = [], [], [], [], [], []
    counts = Counter()
    unknown = []
    original_names = {bone_name(b.name): b.name for b in arm.data.bones}
    for obj in objects:
        offset = len(entries)
        groups = {g.index: bone_name(g.name) for g in obj.vertex_groups}
        # Only base rig joints are subject to the rule; extensions stay allowed.
        forbidden = {i for i, name in groups.items()
                     if name in BASE_JOINT_KEYS and any(s in name for s in FORBIDDEN)}
        for v in obj.data.vertices:
            i = len(entries)
            co = obj.matrix_world @ v.co
            weights = {groups[g.group]: g.weight for g in v.groups
                       if g.group not in forbidden and g.weight > 0}
            f = sum(g.weight for g in v.groups if g.group in forbidden)
            entries.append((obj, v.index))
            positions.append(co)
            neighbours.append(set())
            known.append(weights)
            sums.append(sum(weights.values()))
            foreign.append(f)
            if abs(co.x-anchor.x) < HALF_WIDTH_M and anchor.z-DEPTH_M < co.z < anchor.z and f > 0:
                unknown.append(i)
                for g in v.groups:
                    if g.group in forbidden and g.weight > 0:
                        counts[groups[g.group]] += 1
        for edge in obj.data.edges:
            a, b = (offset+j for j in edge.vertices)
            if a != b:
                neighbours[a].add(b)
                neighbours[b].add(a)
    if not unknown:
        return []
    tree = KDTree(len(entries))
    seeds = [i for i, s in enumerate(sums) if s > 0]
    if not seeds:
        report['unresolved'] += len(unknown)
        return []
    seed_tree = KDTree(len(seeds))
    for i, co in enumerate(positions):
        tree.insert(co, i)
    tree.balance()
    for i in seeds:
        seed_tree.insert(positions[i], i)
    seed_tree.balance()
    values = [{n: w/sums[i] for n, w in weights.items()} if sums[i] else {}
              for i, weights in enumerate(known)]
    for i in unknown:
        for _, j, _ in tree.find_range(positions[i], COINCIDENT_EPSILON_M):
            if i != j:
                neighbours[i].add(j)
                neighbours[j].add(i)
        if not sums[i]:
            _, j, _ = seed_tree.find(positions[i])
            values[i] = dict(values[j])
    for iteration in range(1, MAX_ITERATIONS+1):
        updated = {}
        delta = 0.0
        for i in unknown:
            adjacent = [values[j] for j in sorted(neighbours[i]) if values[j]]
            if not adjacent:
                # An isolated vertex keeps the nearest-vertex initial estimate.
                adjacent = [values[i]]
            mean = Counter()
            for value in adjacent:
                for name, w in value.items():
                    mean[name] += w/len(adjacent)
            total = sums[i]+foreign[i]
            value = {name: (known[i].get(name, 0)+foreign[i]*mean.get(name, 0))/total
                     for name in known[i].keys() | mean.keys()}
            delta = max(delta, max((abs(value.get(n, 0)-values[i].get(n, 0))
                                    for n in value.keys() | values[i].keys()), default=0))
            updated[i] = value
        for i, value in updated.items():
            values[i] = value
        report['iterations'] = max(report['iterations'], iteration)
        if delta < TOLERANCE:
            break
    changes = []
    for i in unknown:
        obj, index = entries[i]
        value = {n: w for n, w in values[i].items() if w >= MIN_WEIGHT}
        total = sum(value.values())
        groups = {bone_name(g.name): g.name for g in obj.vertex_groups}
        changes.append((obj, index, {groups.get(n, original_names.get(n, n)): w/total
                                     for n, w in value.items()}))
    report['vertices'] += len(unknown)
    report['fully_foreign'] += sum(sums[i] == 0 for i in unknown)
    report['removed_weight'] += sum(foreign[i] for i in unknown)
    report['bones'] = dict(Counter(report['bones']) + counts)
    return changes


def repair():
    """Stage all distributions before writing; roll back every edit on error."""
    report = _report()
    backups, created = [], []
    try:
        arms = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
        eligible = [a for a in arms if 'hips' in {bone_name(b.name) for b in a.data.bones}]
        if not eligible:
            report['skipped'] = 'no Hips bone'
            return report
        changes = []
        for arm in eligible:
            names = {bone_name(b.name) for b in arm.data.bones}
            if not {'leftupleg', 'rightupleg'} <= names:
                continue
            changes.extend(_prepare(arm, report))
        if not any({'leftupleg', 'rightupleg'} <= {bone_name(b.name) for b in a.data.bones}
                   for a in eligible):
            report['skipped'] = 'not a humanoid rig'
        for obj, index, distribution in changes:
            backups.append((obj, index, {obj.vertex_groups[g.group].name: g.weight
                                        for g in obj.data.vertices[index].groups}))
            for group in obj.vertex_groups:
                group.remove([index])
            for name, weight in distribution.items():
                group = obj.vertex_groups.get(name)
                if group is None:
                    group = obj.vertex_groups.new(name=name)
                    created.append((obj, group))
                group.add([index], weight, 'REPLACE')
        report['removed_weight'] = round(report['removed_weight'], 3)
        report['bones'] = dict(Counter(report['bones']).most_common(8))
    except Exception as exc:
        for obj, index, distribution in reversed(backups):
            for group in obj.vertex_groups:
                group.remove([index])
            for name, weight in distribution.items():
                obj.vertex_groups[name].add([index], weight, 'REPLACE')
        for obj, group in reversed(created):
            obj.vertex_groups.remove(group)
        report = _report()
        report['error'] = str(exc)
    return report
