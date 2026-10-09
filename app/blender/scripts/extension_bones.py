"""Generic optional rig operations in the runner JSON protocol.

Geometry is in metres, front -Y and up +Z. All detection, falloff, weld,
segmentation, reference-frame checks and test poses are required group params. Placement is planned before any bone or weight changes.
A failed group returns no output for the entire request.
"""
import math
import sys
from pathlib import Path

_SCRIPT_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPT_DIR)
import _common
sys.path.remove(_SCRIPT_DIR)
import bpy
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree

PARAMETERS = {'pair_protrusion': {'band_lower_bone': 'bone',
                     'band_upper_bone': 'bone',
                     'band_lower_offset': 'number',
                     'band_upper_offset': 'number',
                     'lateral_min': 'number',
                     'lateral_max': 'number',
                     'wall_drop': 'number',
                     'wall_z_tolerance': 'number',
                     'wall_x_tolerance': 'number',
                     'wall_fallback_depth': 'number',
                     'head_x_scale': 'number',
                     'head_wall_depth': 'number',
                     'head_z_offset': 'number',
                     'radius_min': 'number',
                     'radius_max': 'number',
                     'radius_gain': 'number',
                     'radius_offset': 'number',
                     'radius_z_scale': 'number',
                     'radius_plateau': 'number',
                     'radius_scale': 'number',
                     'side_margin': 'number',
                     'front_margin': 'number',
                     'depth_ramp': 'number',
                     'weight_min': 'number',
                     'test_rotation_deg': 'vector3',
                     'test_scale': 'vector3',
                     'up_from_bone': 'bone',
                     'up_to_bone': 'bone',
                     'up_distance_min': 'number',
                     'up_distance_max': 'number',
                     'lateral_positive_bone': 'bone',
                     'lateral_negative_bone': 'bone',
                     'front_from_bone': 'bone',
                     'front_to_bone': 'bone',
                     'front_distance_min': 'number'},
 'appendage_chain': {'anchor_bone': 'bone',
                     'anchor_offset': 'vector3',
                     'search_z_min': 'number',
                     'search_z_max': 'number',
                     'reference_lateral_min': 'number',
                     'reference_lateral_max': 'number',
                     'slice_size': 'number',
                     'candidate_lateral_max': 'number',
                     'part_half_width': 'number',
                     'protrusion_threshold': 'number',
                     'axis_initial': 'vector3',
                     'axis_iterations': 'number',
                     'root_depth': 'number',
                     'root_wall_margin': 'number',
                     'chain_split': 'fractions',
                     'cut': 'number',
                     'weld_distance': 'number',
                     'window_length_factor': 'number',
                     'window_margin': 'number',
                     'leak_t_limit': 'number',
                     'leak_radius_limit': 'number',
                     'segment_radius_factor': 'number',
                     'segment_min_vertices': 'number',
                     'contact_ramp': 'number',
                     'ring_radius_percentile': 'number',
                     'ring_radius_scale': 'number',
                     'near_slice_margin': 'number',
                     'far_slice_fraction': 'number',
                     'attachment_inset': 'number',
                     'weight_ramp': 'number',
                     'fallback_half_width': 'number',
                     'fallback_z_margin': 'number',
                     'fallback_front_fraction': 'number',
                     'fallback_front_ramp': 'number',
                     'fallback_side_ramp': 'number',
                     'fallback_top_margin': 'number',
                     'fallback_top_ramp': 'number',
                     'blend_start': 'number',
                     'blend_width': 'number',
                     'reweight_factor': 'number',
                     'reweight_from': 'bones',
                     'weight_min': 'number',
                     'test_rotation_deg': 'vector3',
                     'test_rotation_decay': 'number',
                     'test_scale': 'vector3',
                     'up_from_bone': 'bone',
                     'up_to_bone': 'bone',
                     'up_distance_min': 'number',
                     'up_distance_max': 'number',
                     'lateral_positive_bone': 'bone',
                     'lateral_negative_bone': 'bone',
                     'front_from_bone': 'bone',
                     'front_to_bone': 'bone',
                     'front_distance_min': 'number'}}


def smooth(t):
    t = max(0., min(1., t))
    return t * t * (3. - 2. * t)


def bone_key(name):
    return name.lower().removeprefix('mixamorig:').removeprefix('mixamorig').replace(':', '')


def parameters(group):
    op = group['op']
    if op not in PARAMETERS:
        raise ValueError('unsupported operation: ' + str(op))
    supplied = group.get('params') or {}
    unknown = set(supplied) - set(PARAMETERS[op])
    if unknown:
        raise ValueError('unknown params: ' + ', '.join(sorted(unknown)))
    missing = set(PARAMETERS[op]) - set(supplied)
    if missing:
        raise ValueError('missing required params: ' + ', '.join(sorted(missing)))
    p = dict(supplied)
    for key, kind in PARAMETERS[op].items():
        value = p[key]
        if kind == 'number':
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(key + ' must be finite numeric')
            if key in ('axis_iterations', 'segment_min_vertices') and int(value) != value:
                raise ValueError(key + ' must be an integer')
        elif kind == 'bone':
            if not isinstance(value, str) or not value:
                raise ValueError(key + ' must be a bone name')
        else:
            if not isinstance(value, list):
                raise ValueError(key + ' must be a list')
            if kind == 'bones':
                if any(not isinstance(v, str) or not v for v in value):
                    raise ValueError(key + ' must contain bone names')
            else:
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
                    raise ValueError(key + ' must contain finite numbers')
                if kind == 'vector3' and len(value) != 3:
                    raise ValueError(key + ' must have three components')
    positive = ('radius_scale', 'radius_min', 'radius_max', 'radius_z_scale', 'wall_z_tolerance',
                'wall_x_tolerance', 'depth_ramp', 'slice_size', 'part_half_width',
                'candidate_lateral_max', 'protrusion_threshold', 'weld_distance',
                'weight_ramp', 'leak_radius_limit', 'segment_radius_factor', 'segment_min_vertices', 'contact_ramp', 'fallback_half_width',
                'fallback_front_ramp', 'fallback_side_ramp', 'fallback_top_ramp',
                'blend_width', 'window_length_factor', 'ring_radius_scale')
    for key in positive:
        if key in p and p[key] <= 0:
            raise ValueError(key + ' must be positive')
    nonnegative = ('wall_drop', 'wall_fallback_depth', 'head_x_scale',
                   'head_wall_depth', 'radius_gain', 'radius_offset',
                   'side_margin', 'front_margin', 'root_depth',
                   'root_wall_margin', 'window_margin', 'near_slice_margin',
                   'attachment_inset', 'fallback_z_margin',
                   'fallback_front_fraction', 'fallback_top_margin',
                   'reweight_factor', 'test_rotation_decay')
    for key in nonnegative:
        if key in p and p[key] < 0:
            raise ValueError(key + ' must be nonnegative')
    if 'leak_t_limit' in p and p['leak_t_limit'] <= 1:
        raise ValueError('leak_t_limit must exceed 1')
    if not 0 <= p['up_distance_min'] < p['up_distance_max'] or p['front_distance_min'] < 0:
        raise ValueError('invalid declared reference ranges')
    if any(v <= 0 for v in p['test_scale']):
        raise ValueError('test_scale must be positive')
    if not 0 <= p['weight_min'] < 1:
        raise ValueError('weight_min must be in [0,1)')
    if op == 'pair_protrusion':
        if not 0 <= p['radius_plateau'] < 1:
            raise ValueError('radius_plateau must be in [0,1)')
        if not 0 <= p['lateral_min'] < p['lateral_max'] or p['radius_min'] > p['radius_max']:
            raise ValueError('invalid lateral or radius range')
    else:
        if p['search_z_min'] >= p['search_z_max'] or not 0 <= p['reference_lateral_min'] < p['reference_lateral_max']:
            raise ValueError('invalid search or reference range')
        for key in ('cut', 'ring_radius_percentile', 'far_slice_fraction', 'blend_start'):
            if not 0 < p[key] < 1:
                raise ValueError(key + ' must be in (0,1)')
        if not 1 <= p['axis_iterations'] <= 1000 or Vector(p['axis_initial']).length < 1e-8:
            raise ValueError('invalid principal axis parameters')
        splits = p['chain_split']
        if splits != sorted(set(splits)) or any(not 0 < v < 1 for v in splits):
            raise ValueError('chain_split must be strictly increasing inside (0,1)')
    return p


def lookup(bones, name):
    key = bone_key(name)
    if key not in bones:
        raise ValueError('base bone not found: ' + name)
    return bones[key]


def pair_plan(group, p, co, bones):
    chains = group['chains']
    if len(chains) != 2 or any(len(c) != 1 for c in chains):
        raise ValueError('pair_protrusion requires two one-link chains')
    lo = lookup(bones, p['band_lower_bone']).head_local.z + p['band_lower_offset']
    hi = lookup(bones, p['band_upper_bone']).head_local.z + p['band_upper_offset']
    if lo >= hi:
        raise ValueError('empty height band')
    links, weights, placements = [], {}, []
    for chain, sign in zip(chains, (1, -1)):
        candidates = [i for i, c in enumerate(co) if lo < c.z < hi and p['lateral_min'] < sign * c.x < p['lateral_max']]
        if not candidates:
            raise ValueError('no protrusion candidates on side ' + str(sign))
        apex = co[min(candidates, key=lambda i: co[i].y)]
        under = [c.y for c in co if abs(c.z - apex.z + p['wall_drop']) < p['wall_z_tolerance'] and abs(c.x - apex.x) < p['wall_x_tolerance']]
        wall = min(under) if under else apex.y + p['wall_fallback_depth']
        depth = wall - apex.y
        if depth <= 0:
            raise ValueError('apex does not protrude from wall')
        radius = max(p['radius_min'], min(p['radius_max'], depth * p['radius_gain'] + p['radius_offset']))
        head = Vector((apex.x * p['head_x_scale'], wall + p['head_wall_depth'], apex.z + p['head_z_offset']))
        link = chain[0]
        lookup(bones, link['parent'])
        links.append((link['bone'], head, apex.copy(), link['parent']))
        w = {}
        for i, c in enumerate(co):
            if sign * c.x < p['side_margin'] or c.y > wall + p['front_margin']:
                continue
            d = math.sqrt(((c.x-apex.x)/radius)**2 + ((c.z-apex.z)/(radius*p['radius_z_scale']))**2)
            value = smooth((1-d/p['radius_scale'])/(1-p['radius_plateau'])) * smooth((wall+p['front_margin']-c.y)/p['depth_ramp'])
            if value > p['weight_min']:
                w[i] = value
        if not w:
            raise ValueError('empty pair weight region')
        weights[link['bone']] = w
        placements.append({'head': list(head), 'tip': list(apex), 'wall_y': wall})
    return links, weights, {'placement': placements, 'leak': False}, set(), []


def appendage_plan(group, p, co, edges, bones):
    chains = group['chains']
    if len(chains) != 1 or not chains[0]:
        raise ValueError('appendage_chain requires one nonempty chain')
    chain = chains[0]
    anchor = lookup(bones, p['anchor_bone']).head_local
    parent = lookup(bones, chain[0]['parent'])
    for name in p['reweight_from']:
        lookup(bones, name)
    lo, hi = anchor.z+p['search_z_min'], anchor.z+p['search_z_max']
    lat = {}
    for c in co:
        if p['reference_lateral_min'] < abs(c.x-anchor.x) < p['reference_lateral_max'] and lo < c.z < hi:
            k = round(c.z/p['slice_size'])
            lat[k] = min(lat.get(k, float('inf')), c.y)
    if not lat:
        raise ValueError('no lateral reference surface')
    fallback = sorted(lat.values())[len(lat)//2]
    def front(z):
        return lat.get(round(z/p['slice_size']), fallback)
    cand = [i for i,c in enumerate(co) if abs(c.x-anchor.x) < p['candidate_lateral_max'] and lo < c.z < hi and c.y < front(c.z)-p['protrusion_threshold']]
    if not cand:
        raise ValueError('no protrusion candidates')
    cx = sorted(co[i].x for i in cand)[len(cand)//2]
    points = [co[i] for i in cand if abs(co[i].x-cx) < p['part_half_width']]
    if len(points) < 3:
        raise ValueError('insufficient axis candidates')
    cen = sum(points, Vector())/len(points)
    cov = [[sum((v[a]-cen[a])*(v[b]-cen[b]) for v in points)/len(points) for b in range(3)] for a in range(3)]
    axis = Vector(p['axis_initial']).normalized()
    for _ in range(int(p['axis_iterations'])):
        v = Vector([sum(cov[a][b]*axis[b] for b in range(3)) for a in range(3)])
        if v.length < 1e-10:
            raise ValueError('degenerate principal axis')
        axis = v.normalized()
    ts = [(v-cen).dot(axis) for v in points]
    ends = (cen+axis*min(ts), cen+axis*max(ts))
    target = anchor+Vector(p['anchor_offset'])
    base, tip = sorted(ends, key=lambda e: (e-target).length)
    if group.get('flip', False):
        base, tip = tip, base
    detected_tip = tip.copy()
    length = (tip-base).length
    if length < 1e-6:
        raise ValueError('degenerate part length')
    direction = (tip-base)/length
    def t_of(c):
        return (c-base).dot(direction)/length
    def radial(c):
        delta = c-base
        return (delta-direction*delta.dot(direction)).length
    # Half-width comes from the lateral extent of the axis candidate set.
    half_width = (max(v.x for v in points)-min(v.x for v in points))/2
    segment_radius = p['segment_radius_factor'] * half_width
    if segment_radius <= 0:
        raise ValueError('degenerate measured part half-width')
    axial_window = p['window_length_factor'] + p['window_margin']/length
    eligible = {i for i,c in enumerate(co)
                if abs(t_of(c)-.5) < axial_window and radial(c) <= segment_radius}
    kd = KDTree(len(co))
    for i,c in enumerate(co):
        kd.insert(c,i)
    kd.balance()
    ids = list(range(len(co)))
    # Bound welding too, so out-of-bound seam vertices cannot bridge the flood.
    # Union-find guarantees transitive welding across multiple UV seams.
    def find(i):
        while ids[i] != i:
            ids[i] = ids[ids[i]]
            i = ids[i]
        return i
    for i in eligible:
        for _,j,_ in kd.find_range(co[i],p['weld_distance']):
            if j not in eligible:
                continue
            a,b = find(i),find(j)
            ids[max(a,b)] = min(a,b)
    welded = [find(i) for i in range(len(co))]
    adj = {}
    for a,b in edges:
        a,b = welded[a],welded[b]
        if a != b:
            adj.setdefault(a,set()).add(b)
            adj.setdefault(b,set()).add(a)
    win = {welded[i] for i in eligible}
    keep = {i for i in win if t_of(co[i]) >= p['cut']}
    seed = welded[min(range(len(co)),key=lambda i:(co[i]-tip).length)]
    if seed not in keep:
        raise ValueError('tip is outside segmented window')
    comp, stack = {seed},[seed]
    while stack:
        for j in adj.get(stack.pop(),()):
            if j in keep and j not in comp:
                comp.add(j)
                stack.append(j)
    tmax = max(t_of(co[i]) for i in comp)
    rmax = max(radial(co[i]) for i in comp)
    leak_reasons = []
    if len(comp) < p['segment_min_vertices']:
        leak_reasons.append('bounded component has too few vertices')
    if tmax > p['leak_t_limit']:
        leak_reasons.append('bounded component exceeds leak_t_limit')
    leak = bool(leak_reasons)
    root = Vector((base.x,max(base.y+p['root_depth'],front(base.z)+p['root_wall_margin']),base.z))
    part = set()
    if not leak:
        radii = sorted(radial(co[i]) for i in comp)
        r = radii[min(len(radii)-1,int(p['ring_radius_percentile']*len(radii)))]
        ring = {i for i in win if 0 <= t_of(co[i]) < p['cut'] and radial(co[i]) <= r*p['ring_radius_scale']}
        part = comp|ring
        near = [co[i] for i in part if t_of(co[i]) < p['cut']+p['near_slice_margin']] or [co[i] for i in part]
        far = [co[i] for i in part if t_of(co[i]) > p['far_slice_fraction']*tmax] or [co[i] for i in part]
        base_c,tip_c = sum(near,Vector())/len(near),sum(far,Vector())/len(far)
        if (base_c-tip_c).length < 1e-6:
            raise ValueError('segmented centre line is degenerate')
        root = base_c+(base_c-tip_c).normalized()*p['attachment_inset']
        tip = tip_c
    delta = tip-root
    axis_length = delta.length
    if axis_length < 1e-6:
        raise ValueError('chain length is zero')
    dirv = delta/axis_length
    splits = p['chain_split']
    if len(splits) != len(chain)-1:
        raise ValueError('chain_split must have one entry per internal chain joint')
    boundaries = [0]+splits+[1]
    links = [(link['bone'],root.lerp(tip,boundaries[i]),root.lerp(tip,boundaries[i+1]),link['parent']) for i,link in enumerate(chain)]
    weights = {link['bone']: {} for link in chain}
    top,bottom = max(v.z for v in points),min(v.z for v in points)
    affected = set()
    for i,c in enumerate(co):
        t = (c-root).dot(dirv)/axis_length
        if not leak:
            if i not in eligible or welded[i] not in part:
                continue
            affected.add(i)
            value = smooth(t/p['weight_ramp']) * smooth((segment_radius-radial(c))/p['contact_ramp'])
        else:
            if abs(c.x-cx)>p['fallback_half_width'] or not bottom-p['fallback_z_margin'] < c.z < top+p['fallback_z_margin']:
                continue
            value = smooth((front(c.z)-p['protrusion_threshold']*p['fallback_front_fraction']-c.y)/p['fallback_front_ramp'])*smooth((p['fallback_half_width']-abs(c.x-cx))/p['fallback_side_ramp'])*smooth((top+p['fallback_top_margin']-c.z)/p['fallback_top_ramp'])
        if value <= p['weight_min']:
            continue
        affected.add(i)
        # Two-link crossover uses the declared blend interval.
        if len(chain)==2:
            blend = smooth((t-p['blend_start'])/p['blend_width'])
            shares = [1-blend,blend]
        else:
            position = max(0,min(len(chain)-1,t*len(chain)-.5))
            a = int(position)
            shares = [0.]*len(chain)
            shares[a] = 1-(position-a)
            if a+1 < len(chain):
                shares[a+1] = position-a
        for link,share in zip(chain,shares):
            if share*value > 0:
                weights[link['bone']][i] = share*value
    if any(not w for w in weights.values()):
        raise ValueError('empty chain weight region')
    metrics = {
        'placement': [{'head':list(h),'tip':list(t)} for _,h,t,_ in links],
        'attachment':list(base), 'axis_length':axis_length,
        'leak':leak, 'leak_reason':'; '.join(leak_reasons),
        'segment_radius':segment_radius, 'measured_half_width':half_width,
        'segment_axis_base':list(base), 'segment_axis_tip':list(detected_tip),
        'part_vertex_count':len(affected), 'segment_t_max':tmax,
        'segment_radius_max':rmax,
    }
    return links,weights,metrics,affected,p['reweight_from']


def measure(arm, meshes, edges, plans):
    def evaluated():
        out=[]
        dg=bpy.context.evaluated_depsgraph_get()
        for mesh in meshes:
            ev=mesh.evaluated_get(dg)
            data=ev.to_mesh()
            out.extend(mesh.matrix_world@v.co for v in data.vertices)
            ev.to_mesh_clear()
        return out
    bpy.context.view_layer.update()
    rest=evaluated()
    metrics={}
    for g,p,plan in plans:
        for i,(name,_,_,_) in enumerate(plan[0]):
            pb=arm.pose.bones[name]
            pb.rotation_mode='XYZ'
            decay=p.get('test_rotation_decay',1)**i
            pb.rotation_euler=[math.radians(v)*decay for v in p['test_rotation_deg']]
            pb.scale=p['test_scale']
        bpy.context.view_layer.update()
        posed=evaluated()
        weighted={i for w in plan[1].values() for i in w}
        ratios=sorted((posed[a]-posed[b]).length/(rest[a]-rest[b]).length for a,b in edges if (a in weighted or b in weighted) and (rest[a]-rest[b]).length>1e-6)
        pct=lambda f: ratios[min(len(ratios)-1,int(f*len(ratios)))] if ratios else None
        if g['op'] == 'appendage_chain':
            sources = {bone_key(n) for n in p['reweight_from']}
            captured = plan[3] if plan[2] else weighted
            offset = 0
            remaining = 0
            for mesh in meshes:
                for vertex in mesh.data.vertices:
                    if offset+vertex.index in captured:
                        remaining += sum(ge.weight for ge in vertex.groups
                                         if bone_key(mesh.vertex_groups[ge.group].name) in sources) > .1
                offset += len(mesh.data.vertices)
            plan[2]['thigh_weight_in_part'] = remaining
        metrics[g['id']]={**plan[2], 'verts_per_group':{name:len(w) for name,w in plan[1].items()}, 'weighted_verts':len(weighted),'edge_stretch_p01_p50_p99_max':[pct(.01),pct(.5),pct(.99),pct(1)],'reason':''}
        for name,_,_,_ in plan[0]:
            arm.pose.bones[name].rotation_euler=(0,0,0)
            arm.pose.bones[name].scale=(1,1,1)
        bpy.context.view_layer.update()
    return metrics


def extension_bones(args):
    groups = args['params'].get('groups') or []
    enabled = [g for g in groups if g.get('enabled',True)]
    if not enabled:
        return {'status':'none_applicable','reason':'','groups':{}},{}
    _common.reset_scene()
    _common.import_model(args['inputs']['model'])
    arms = [o for o in bpy.context.scene.objects if o.type=='ARMATURE']
    meshes = [o for o in bpy.context.scene.objects if o.type=='MESH' and any(m.type=='ARMATURE' and m.object in arms for m in o.modifiers)]
    def skip(reason,failed=None,status='not_found'):
        return {'status':status,'reason':reason,'groups':{g['id']:{'reason':failed.get(g['id'],'Request aborted: '+reason) if failed else reason} for g in enabled}},{}
    if abs(bpy.context.scene.unit_settings.scale_length-1)>1e-6:
        return skip('Requires metre scene units')
    if len(arms)!=1 or not meshes:
        return skip('Requires one armature and skinned meshes')
    arm = arms[0]
    if any(abs(arm.matrix_world[i][j]-Matrix.Identity(4)[i][j])>1e-6 for i in range(4) for j in range(4)):
        return skip('Armature must be at identity')
    bones = {bone_key(b.name):b for b in arm.data.bones}
    deform_names={b.name for b in arm.data.bones if b.use_deform}
    for mesh in meshes:
        for v in mesh.data.vertices:
            weight=sum(ge.weight for ge in v.groups if mesh.vertex_groups[ge.group].name in deform_names)
            if weight <= 1e-8:
                return skip('Skinned vertices require nonzero deform weights',status='failed')
    co,edges,owners = [],[],[]
    for mesh in meshes:
        offset = len(co)
        co.extend(mesh.matrix_world@v.co for v in mesh.data.vertices)
        owners.extend((mesh,v.index) for v in mesh.data.vertices)
        edges.extend((e.vertices[0]+offset,e.vertices[1]+offset) for e in mesh.data.edges)
    if args['params'].get('metrics_only',False):
        plans=[]
        for g in enabled:
            try:
                p=parameters(g)
                links=[]
                weights={}
                for chain in g['chains']:
                    for link in chain:
                        bone=lookup(bones,link['bone'])
                        links.append((bone.name,bone.head_local.copy(),bone.tail_local.copy(),link['parent']))
                        weights[bone.name]={}
                for i,(mesh,vi) in enumerate(owners):
                    for ge in mesh.data.vertices[vi].groups:
                        name=mesh.vertex_groups[ge.group].name
                        if name in weights and ge.weight>0:
                            weights[name][i]=ge.weight
                plans.append((g,p,(links,weights,{},set(),[])))
            except (ValueError,KeyError,TypeError) as e:
                return skip(str(e),status='failed')
        metrics=measure(arm,meshes,edges,plans)
        return {'status':'applied','reason':'','groups':metrics,'metrics':metrics},{}
    plans,failed,names = [],{},set()
    malformed = False
    for g in enabled:
        try:
            try:
                p = parameters(g)
                rise = lookup(bones,p['up_to_bone']).head_local.z - lookup(bones,p['up_from_bone']).head_local.z
                if not p['up_distance_min'] < rise < p['up_distance_max']:
                    raise ValueError('Declared up/size reference check failed')
                if lookup(bones,p['lateral_positive_bone']).head_local.x <= lookup(bones,p['lateral_negative_bone']).head_local.x:
                    raise ValueError('Declared lateral reference check failed')
                front = lookup(bones,p['front_from_bone']).head_local.y - lookup(bones,p['front_to_bone']).head_local.y
                if front <= p['front_distance_min']:
                    raise ValueError('Declared front reference check failed')
                chains = g['chains']
                if g['op']=='pair_protrusion' and (len(chains)!=2 or any(len(c)!=1 for c in chains)):
                    raise ValueError('pair_protrusion requires two one-link chains')
                if g['op']=='appendage_chain' and (len(chains)!=1 or not chains[0]):
                    raise ValueError('appendage_chain requires one nonempty chain')
            except (ValueError, KeyError, TypeError) as e:
                malformed = True
                raise ValueError(str(e)) from e
            plan = pair_plan(g,p,co,bones) if g['op']=='pair_protrusion' else appendage_plan(g,p,co,edges,bones)
            for name,h,t,parent in plan[0]:
                if name in names or bone_key(name) in bones:
                    raise ValueError('bone already exists: '+name)
                if (t-h).length < 1e-6:
                    raise ValueError('bone has zero length: '+name)
                names.add(name)
            plans.append((g,p,plan))
        except (ValueError,KeyError,TypeError,IndexError) as e:
            failed[g['id']] = str(e)
    if failed:
        return skip('; '.join(k+': '+v for k,v in failed.items()),failed,'failed' if malformed else 'not_found')
    bpy.context.view_layer.objects.active=arm
    bpy.ops.object.mode_set(mode='EDIT')
    eb=arm.data.edit_bones
    for g,p,plan in plans:
        for name,h,t,parent in plan[0]:
            b=eb.new(name)
            b.head,b.tail=h,t
            b.parent=eb.get(parent) or next((v for v in eb if bone_key(v.name)==bone_key(parent)),None)
            if b.parent is None:
                raise ValueError('parent is absent: '+parent)
            b.use_connect=False
            b.roll=0
    bpy.ops.object.mode_set(mode='OBJECT')
    totals,allweights={},{}
    for g,p,plan in plans:
        for name,w in plan[1].items():
            allweights[name]=w
            for i,v in w.items():
                totals[i]=totals.get(i,0)+v
    # Preserve relative extension shares where two operation envelopes overlap.
    scales={i:1/max(1,total) for i,total in totals.items()}
    for g,p,plan in plans:
        if not plan[4]:
            continue
        parent_name=lookup(bones,g['chains'][0][0]['parent']).name
        sources={bone_key(n) for n in plan[4]}
        for i in plan[3]:
            mesh,vi=owners[i]
            take=0
            for ge in list(mesh.data.vertices[vi].groups):
                vg=mesh.vertex_groups[ge.group]
                if bone_key(vg.name) in sources:
                    amount=ge.weight
                    vg.remove([vi])
                    take+=amount
            if take:
                vg=mesh.vertex_groups.get(parent_name) or mesh.vertex_groups.new(name=parent_name)
                vg.add([vi],take,'ADD')
    for i,total in totals.items():
        mesh,vi=owners[i]
        for ge in list(mesh.data.vertices[vi].groups):
            mesh.vertex_groups[ge.group].add([vi],ge.weight*(1-total*scales[i]),'REPLACE')
    for name,w in allweights.items():
        for i,value in w.items():
            mesh,vi=owners[i]
            vg=mesh.vertex_groups.get(name) or mesh.vertex_groups.new(name=name)
            vg.add([vi],value*scales[i],'REPLACE')
    # The browser consumes exactly four joints per vertex. Joint order is
    # the armature export order; equal weights prefer its lower joint index.
    joint_index={b.name:i for i,b in enumerate(arm.data.bones) if b.use_deform}
    final_weights={name:{} for name in allweights}
    for i,(mesh,vi) in enumerate(owners):
        vertex=mesh.data.vertices[vi]
        entries=[(mesh.vertex_groups[ge.group],ge.weight) for ge in vertex.groups
                 if mesh.vertex_groups[ge.group].name in joint_index and ge.weight>0]
        entries.sort(key=lambda entry:(-entry[1],joint_index[entry[0].name]))
        kept=entries[:4]
        total=sum(w for _,w in kept)
        for vg,_ in entries[4:]:
            vg.remove([vi])
        for vg,w in kept:
            vg.add([vi],w/total,'REPLACE')
            if vg.name in final_weights:
                final_weights[vg.name][i]=w/total
    # Counts and posed geometry must describe the representation we export.
    for _,_,plan in plans:
        for name in plan[1]:
            plan[1][name]=final_weights[name]
    metrics=measure(arm,meshes,edges,plans)
    output=Path(args['out_dir'])/'model.glb'
    bpy.ops.export_scene.gltf(filepath=str(output),export_format='GLB',export_apply=False,export_yup=True,export_skins=True,export_animations=True,export_morph=True,export_all_influences=False)
    return {'status':'applied','reason':'','groups':metrics,'metrics':metrics},{'model':str(output)}


_common.main(extension_bones)
