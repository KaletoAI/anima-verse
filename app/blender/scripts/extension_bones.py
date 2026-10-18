"""Generic optional rig operations in the runner JSON protocol.

Geometry is in metres, front -Y and up +Z. All detection, falloff, weld,
segmentation, reference-frame checks and test poses are required group params. Placement is planned before any bone or weight changes.
A failed group returns no output for the entire request.
"""
import math
import heapq
import statistics
import sys
from pathlib import Path
from types import SimpleNamespace

_SCRIPT_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPT_DIR)
import _common
sys.path.remove(_SCRIPT_DIR)
import bpy
import bmesh
import numpy as np
from mathutils.geometry import barycentric_transform
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree
from mathutils.bvhtree import BVHTree

# Metres: positional copies at UV seams and creases must deform together.
# This is independent of the normal-aware segmentation weld and pack params.
COINCIDENT_EPSILON_M = 1e-5

PARAMETERS = {'pair_protrusion': {'band_lower_bone': 'bone',
                     'band_upper_bone': 'bone',
                     'band_lower_offset': 'number',
                     'band_upper_offset': 'number',
                     'lateral_min': 'number',
                     'lateral_max': 'number',
                     'marker_search_radius': 'number',
                     'marker_grid_step': 'number',
                     'marker_score_min': 'number',
                     'marker_yellow_weight': 'number',
                     'marker_dark_min': 'number',
                     'marker_light_max': 'number',
                     'marker_area_min': 'number',
                     'marker_area_max': 'number',
                     'marker_spread_max': 'number',
                     'marker_pair_dz': 'number',
                     'marker_pair_dx': 'number',
                     'boundary_directions': 'number',
                     'boundary_s_min': 'number',
                     'boundary_s_max': 'number',
                     'boundary_step': 'number',
                     'exclude_weight': 'number',
                     'exclude_bones': 'bones',
                     'head_wall_depth': 'number',
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
                     'segment_radius_percentile': 'number',
                     'segment_radius_margin': 'number',
                     'segment_radius_growth_max': 'number',
                     'segment_passes': 'number',
                     'segment_min_vertices': 'number',
                     'contact_ramp': 'number',
                     'contact_follow_distance': 'number',
                     'contact_inside_distance': 'number',
                     'contact_follow_weight': 'number',
                     'base_slice_size': 'number',
                     'base_radius_margin': 'number',
                     'base_growth_max': 'number',
                     'base_extension_max': 'number',
                     'base_history_slices': 'number',
                     'attachment_ring_max': 'number',
                     'weld_normal_min': 'number',
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
                     'centerline_slab': 'number',
                     'link_blend': 'number',
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

PARAMETERS['pair_tip'] = {key:kind for key,kind in PARAMETERS['pair_protrusion'].items()
                          if key.startswith(('up_', 'lateral_positive_', 'lateral_negative_', 'front_from_', 'front_to_', 'front_distance_', 'test_')) or key=='weight_min'}
PARAMETERS['pair_tip'].update({key:'number' for key in ('normal_radius','fill_radius','fill_ring','fill_blend',
    'fill_depth','fill_tolerance','fill_rms_max','tip_diameter','tip_length','tip_round',
    'tip_wall','tip_band','tip_subdivide','weight_depth')})
PARAMETERS['pair_tip']['subdivide_radii'] = 'fractions'


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
            if key in ('boundary_directions', 'axis_iterations', 'segment_min_vertices', 'segment_passes', 'base_history_slices') and int(value) != value:
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
    positive = ('radius_scale', 'marker_search_radius', 'marker_grid_step', 'marker_area_min',
                'marker_area_max', 'marker_spread_max', 'marker_pair_dz', 'marker_pair_dx',
                'boundary_s_min', 'boundary_s_max', 'boundary_step', 'exclude_weight', 'depth_ramp', 'slice_size', 'part_half_width',
                'candidate_lateral_max', 'protrusion_threshold', 'weld_distance',
                'weight_ramp', 'leak_radius_limit', 'segment_radius_factor', 'segment_min_vertices', 'segment_passes', 'segment_radius_margin', 'segment_radius_growth_max', 'contact_ramp', 'fallback_half_width',
                'fallback_front_ramp', 'fallback_side_ramp', 'fallback_top_ramp',
                'base_slice_size', 'base_radius_margin', 'base_growth_max', 'base_extension_max', 'base_history_slices', 'attachment_ring_max',
                'contact_follow_distance', 'link_blend', 'centerline_slab', 'window_length_factor', 'ring_radius_scale')
    for key in positive:
        if key in p and p[key] <= 0:
            raise ValueError(key + ' must be positive')
    nonnegative = ('marker_yellow_weight', 'marker_light_max', 'head_wall_depth',
                   'side_margin', 'front_margin', 'root_depth',
                   'root_wall_margin', 'window_margin', 'near_slice_margin',
                   'attachment_inset', 'fallback_z_margin',
                   'fallback_front_fraction', 'fallback_top_margin',
                   'reweight_factor', 'test_rotation_decay', 'contact_inside_distance')
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
        if not 0 <= p['lateral_min'] < p['lateral_max']:
            raise ValueError('invalid lateral range')
        if not 0 < p['marker_dark_min'] < 1:
            raise ValueError('marker_dark_min must be in (0,1)')
        if p['marker_area_max'] <= p['marker_area_min']:
            raise ValueError('marker_area_max must exceed marker_area_min')
        if p['boundary_s_max'] <= p['boundary_s_min']:
            raise ValueError('boundary_s_max must exceed boundary_s_min')
        if p['boundary_directions'] < 4 or p['boundary_directions'] % 4:
            raise ValueError('boundary_directions must be an integer multiple of four')
    elif op == 'pair_tip':
        radii = p['subdivide_radii']
        if not 1 <= len(radii) <= 4 or any(v <= 0 for v in radii) or radii != sorted(radii,reverse=True):
            raise ValueError('subdivide_radii requires up to four positive non-increasing values')
        for key in ('normal_radius','fill_radius','fill_ring','fill_blend','fill_tolerance','fill_rms_max','tip_diameter','tip_length','tip_wall','tip_band'):
            if p[key] <= 0:
                raise ValueError(key+' must be positive')
        if p['fill_blend'] >= p['fill_radius'] or min(p['fill_depth'],p['weight_depth'],p['tip_subdivide']) < 0 or not 0 < p['tip_round'] <= 1:
            raise ValueError('invalid pair_tip fill or weight range')
    else:
        if not 0 <= p['contact_follow_weight'] < 1:
            raise ValueError('contact_follow_weight must be in [0,1)')
        if p['search_z_min'] >= p['search_z_max'] or not 0 <= p['reference_lateral_min'] < p['reference_lateral_max']:
            raise ValueError('invalid search or reference range')
        if p['base_radius_margin'] < 1 or p['base_growth_max'] <= 1:
            raise ValueError('base_radius_margin must be at least 1 and base_growth_max must exceed 1')
        if not -1 <= p['weld_normal_min'] <= 1:
            raise ValueError('weld_normal_min must be in [-1,1]')
        for key in ('cut', 'segment_radius_percentile', 'ring_radius_percentile', 'far_slice_fraction', 'centerline_slab', 'link_blend'):
            if not 0 < p[key] < 1:
                raise ValueError(key + ' must be in (0,1)')
        if not 1 <= p['axis_iterations'] <= 1000 or Vector(p['axis_initial']).length < 1e-8:
            raise ValueError('invalid principal axis parameters')
        splits = p['chain_split']
        if splits != sorted(set(splits)) or any(not 0 < v < 1 for v in splits):
            raise ValueError('chain_split must be strictly increasing inside (0,1)')
        if p['weight_ramp'] + p['link_blend'] >= (splits[0] if splits else 1):
            raise ValueError('weight_ramp + link_blend must be less than first split')
        if any(b-a <= 2*p['link_blend'] for a,b in zip(splits,splits[1:])):
            raise ValueError('link_blend zones must not overlap')
    return p


def lookup(bones, name):
    key = bone_key(name)
    if key not in bones:
        raise ValueError('base bone not found: ' + name)
    return bones[key]


def validate_references(p, bones):
    rise = lookup(bones,p['up_to_bone']).head_local.z - lookup(bones,p['up_from_bone']).head_local.z
    if not p['up_distance_min'] < rise < p['up_distance_max']:
        raise ValueError('Declared up/size reference check failed')
    if lookup(bones,p['lateral_positive_bone']).head_local.x <= lookup(bones,p['lateral_negative_bone']).head_local.x:
        raise ValueError('Declared lateral reference check failed')
    front = lookup(bones,p['front_from_bone']).head_local.y - lookup(bones,p['front_to_bone']).head_local.y
    if front <= p['front_distance_min']:
        raise ValueError('Declared front reference check failed')

def pair_surface(meshes):
    """Cache world triangles and image pixels once for all pair groups."""
    triangles,uvs,images,pixels = [],[],[],{}
    for mesh in meshes:
        data = mesh.data
        data.calc_loop_triangles()
        uv = data.uv_layers.active
        for tri in data.loop_triangles:
            triangles.append(tuple(mesh.matrix_world@data.vertices[i].co for i in tri.vertices))
            uvs.append(tuple(Vector((*uv.data[i].uv,0)) for i in tri.loops) if uv else None)
            image = None
            mat = data.materials[tri.material_index] if tri.material_index < len(data.materials) else None
            if mat and mat.use_nodes:
                for node in mat.node_tree.nodes:
                    if node.type == 'BSDF_PRINCIPLED' and node.inputs['Base Color'].links:
                        src = node.inputs['Base Color'].links[0].from_node
                        if src.type == 'TEX_IMAGE' and src.image:
                            image = src.image
                            break
            key = image.as_pointer() if image else None
            if image and key not in pixels:
                w,h = image.size
                if w and h:
                    array = np.empty(w*h*4,np.float32)
                    image.pixels.foreach_get(array)
                    pixels[key] = array.reshape(h,w,4)
            images.append(key)
    bvh = BVHTree.FromPolygons([v for tri in triangles for v in tri],
                              [(3*i,3*i+1,3*i+2) for i in range(len(triangles))],all_triangles=True)
    def front(x,z,colour=False):
        point,_,index,_ = bvh.ray_cast(Vector((x,-10.,z)),Vector((0,1,0)),20.)
        if point is None:
            return None
        rgb = None
        if colour and uvs[index] is not None and images[index] in pixels:
            uv = barycentric_transform(point,*triangles[index],*uvs[index])
            array = pixels[images[index]]
            h,w,_ = array.shape
            rgb = array[int(uv.y%1*h)%h,int(uv.x%1*w)%w,:3]
        return point,rgb
    return front


def pair_plan(group, p, co, bones, front, owners, pinned=None):
    chains = group['chains']
    if len(chains) != 2 or any(len(c) != 1 for c in chains):
        raise ValueError('pair_protrusion requires two one-link chains')
    lo = lookup(bones,p['band_lower_bone']).head_local.z+p['band_lower_offset']
    hi = lookup(bones,p['band_upper_bone']).head_local.z+p['band_upper_offset']
    if lo >= hi:
        raise ValueError('empty height band')
    candidates,initial = [],[]
    for sign in (1,-1):
        side = [v for v in co if lo < v.z < hi and p['lateral_min'] < sign*v.x < p['lateral_max']]
        if not side:
            raise ValueError('no protrusion candidates on side '+str(sign))
        candidates.append(side)
        initial.append(min(side,key=lambda v:v.y).copy())
    marker_areas = [None,None]
    def marker(apex,sign):
        step,radius = p['marker_grid_step'],p['marker_search_radius']
        cells = {}
        count = int(radius/step)
        for j in range(-count,count+1):
            for i in range(-count,count+1):
                x,z = apex.x+i*step,apex.z+j*step
                if math.hypot(i*step,j*step) > radius or sign*x <= p['side_margin']:
                    continue
                hit = front(x,z,True)
                if hit and hit[1] is not None:
                    cells[i,j] = (x,z,hit[1])
        if len(cells) < 10:
            return None,'no texture'
        keys = sorted(cells)
        rgb = np.array([cells[k][2] for k in keys])
        linear = np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
        xyz = linear@np.array([[.4124,.2126,.0193],[.3576,.7152,.1192],[.1805,.0722,.9505]])
        xyz /= np.array([.9505,1.,1.089])
        f = np.where(xyz>.008856,np.cbrt(xyz),7.787*xyz+16/116)
        lab = np.stack((116*f[:,1]-16,500*(f[:,0]-f[:,1]),200*(f[:,1]-f[:,2])),axis=1)
        med = np.median(lab,axis=0)
        score = lab[:,1]-med[1]-p['marker_yellow_weight']*(lab[:,2]-med[2])
        ok = (score>p['marker_score_min'])&(lab[:,0]>p['marker_dark_min']*med[0])&(lab[:,0]<med[0]+p['marker_light_max'])
        pending = {k for k,accepted in zip(keys,ok) if accepted}
        best = []
        while pending:
            seed = min(pending)
            pending.remove(seed)
            component,stack = [seed],[seed]
            while stack:
                i,j = stack.pop()
                for neighbour in ((i+1,j),(i-1,j),(i,j+1),(i,j-1)):
                    if neighbour in pending:
                        pending.remove(neighbour)
                        component.append(neighbour)
                        stack.append(neighbour)
            if len(component) > len(best):
                best = component
        if not best:
            return None,'no marker'
        points = np.array([cells[k][:2] for k in best])
        centre = points.mean(axis=0)
        area = len(best)*step*step
        note = 'area %.1f cm2'%(area*1e4)
        if not p['marker_area_min'] <= area <= p['marker_area_max']:
            return None,note
        if math.sqrt(((points-centre)**2).sum(axis=1).mean()) > p['marker_spread_max']:
            return None,'marker spread'
        marker_areas[0 if sign==1 else 1] = area
        hit = front(*centre)
        return (Vector((centre[0],hit[0].y,centre[1])),note) if hit else (None,'centroid miss')
    if pinned is not None:
        markers = []
        for row in pinned:
            x,z = row['tip'][0],row['tip'][2]
            hit = front(x,z)
            if not hit:
                raise ValueError('pinned marker missed modified surface')
            markers.append((Vector((x,hit[0].y,z)),row['marker_note']))
        marker_areas = [row['marker_area'] for row in pinned]
        colour = True
    else:
        markers = [marker(v,sign) for v,sign in zip(initial,(1,-1))]
        colour = all(v is not None for v,_ in markers)
        if colour:
            a,b = [v for v,_ in markers]
            colour = abs(a.z-b.z)<p['marker_pair_dz'] and abs(a.x+b.x)<p['marker_pair_dx']
            if not colour:
                markers = [(v,'pair mismatch; '+note) for v,note in markers]
    K = int(p['boundary_directions'])
    directions = [(math.sin(2*math.pi*k/K),math.cos(2*math.pi*k/K)) for k in range(K)]
    def walls(apexes):
        side_reach = []
        for apex,sign in zip(apexes,(1,-1)):
            reach = [None]*K
            for k,(dx,dz) in enumerate(directions):
                if dx > 1e-6:
                    continue
                best = None
                steps = int(math.floor((p['boundary_s_max']-p['boundary_s_min'])/p['boundary_step']+1e-8))
                for j in range(steps+1):
                    distance = p['boundary_s_min']+j*p['boundary_step']
                    x,z = apex.x+sign*dx*distance,apex.z+dz*distance
                    if sign*x <= p['side_margin']:
                        break
                    hit = front(x,z)
                    if hit:
                        slope = (hit[0].y-apex.y)/distance
                        if best is None or slope > best[0]:
                            best = slope,distance
                reach[k] = best[1] if best else None
            for k,(dx,_) in enumerate(directions):
                if dx > 1e-6:
                    reach[k] = reach[(-k)%K]
            side_reach.append(reach)
        reach = [min((v for v in values if v is not None),default=None) for values in zip(*side_reach)]
        offsets = []
        for k,(dx,dz) in enumerate(directions):
            values = []
            if dx <= 1e-6 and reach[k] is not None:
                for apex,sign in zip(apexes,(1,-1)):
                    hit = front(apex.x+sign*dx*reach[k],apex.z+dz*reach[k])
                    if hit:
                        values.append(hit[0].y-apex.y)
            offsets.append(max(values,default=None))
        fitted = []
        for apex,sign in zip(apexes,(1,-1)):
            points = [Vector((apex.x+sign*dx*r,apex.y+dy,apex.z+dz*r))
                      for (dx,dz),r,dy in zip(directions,reach,offsets) if dy is not None]
            if len(points) < 3:
                raise ValueError('fewer than three wall points')
            array = np.array([list(v) for v in points])
            centre = array.mean(axis=0)
            _,_,vt = np.linalg.svd(array-centre)
            normal = vt[-1]
            if normal[1] > 0:
                normal = -normal
            c,n = Vector(centre),Vector(normal)
            if (apex-c).dot(n) <= 0:
                raise ValueError('apex does not protrude from wall')
            fitted.append((c,n,points))
        return reach,fitted
    apexes = [v.copy() for v,_ in markers] if colour else initial
    reach,fitted = walls(apexes)
    if not colour:
        apexes = [max((v for v in side if math.hypot(v.x-start.x,v.z-start.z)<=p['marker_search_radius']),
                      key=lambda v:(v-c).dot(n)).copy()
                  for side,start,(c,n,_) in zip(candidates,initial,fitted)]
        reach,fitted = walls(apexes)
    excluded = set()
    for name in p['exclude_bones']:
        bone = lookup(bones,name)
        excluded.add(bone.name)
        excluded.update(b.name for b in bone.children_recursive)
    exclusion = [sum(ge.weight for ge in mesh.data.vertices[vi].groups if mesh.vertex_groups[ge.group].name in excluded)
                 for mesh,vi in owners]
    links,weights,placements = [],{},[]
    for chain,sign,apex,(c,n,points),(_,note) in zip(chains,(1,-1),apexes,fitted,markers):
        depth = (apex-c).dot(n)
        base = sum(points,Vector())/len(points)
        foot = base-n*((base-c).dot(n))
        head = foot-n*p['head_wall_depth']
        link = chain[0]
        lookup(bones,link['parent'])
        links.append((link['bone'],head,apex.copy(),link['parent']))
        w = {}
        for i,v in enumerate(co):
            dist = (v-c).dot(n)
            if sign*v.x < p['side_margin'] or dist < -p['front_margin']:
                continue
            rx,rz = (v.x-apex.x)*sign,v.z-apex.z
            t = (math.atan2(rx,rz)%(2*math.pi))/(2*math.pi)*K
            k = int(t)%K
            f = t-int(t)
            radius = (reach[k] if reach[k] is not None else p['boundary_s_min'])*(1-f)+(reach[(k+1)%K] if reach[(k+1)%K] is not None else p['boundary_s_min'])*f
            value = smooth((1-math.hypot(rx,rz)/(radius*p['radius_scale']))/(1-p['radius_plateau']))*smooth((dist+p['front_margin'])/p['depth_ramp'])*max(0.,1-exclusion[i]/p['exclude_weight'])
            if value > p['weight_min']:
                w[i] = value
        if not w:
            raise ValueError('empty pair weight region')
        weights[link['bone']] = w
        placements.append({'head':list(head),'tip':list(apex),'apex_source':'colour' if colour else 'geometry',
                           'marker_area':marker_areas[len(placements)] if colour else None,'marker_note':note,'reach':reach.copy(),'wall_centre':list(c),'wall_normal':list(n),'depth':depth})
    return links,weights,{'placement':placements,'leak':False},set(),[]


def mesh_arrays(meshes):
    co,edges,owners,normals,faces = [],[],[],[],[]
    for mesh in meshes:
        offset = len(co)
        co.extend(mesh.matrix_world@v.co for v in mesh.data.vertices)
        normal_matrix = mesh.matrix_world.to_3x3().inverted().transposed()
        normals.extend((normal_matrix@v.normal).normalized() for v in mesh.data.vertices)
        owners.extend((mesh,v.index) for v in mesh.data.vertices)
        edges.extend((e.vertices[0]+offset,e.vertices[1]+offset) for e in mesh.data.edges)
        faces.extend(tuple(i+offset for i in face.vertices) for face in mesh.data.polygons)
    return co,edges,owners,normals,faces


def tip_mesh(meshes, p, placement):
    tips = [Vector(row['tip']) for row in placement]
    radius = math.sqrt(sum(row['marker_area'] for row in placement)/(2*math.pi))
    before = sum(len(mesh.data.vertices) for mesh in meshes)
    def subdivide(mesh, centres, radii):
        bm = bmesh.new()
        bm.from_mesh(mesh.data)
        original = set(bm.verts)
        for radius_limit in radii:
            selected = [e for e in bm.edges if any((mesh.matrix_world@((e.verts[0].co+e.verts[1].co)/2)-t).length <= radius_limit for t in centres)]
            if selected:
                bmesh.ops.subdivide_edges(bm,edges=selected,cuts=1,use_grid_fill=True,smooth=0.)
                bmesh.ops.triangulate(bm,faces=[f for f in bm.faces if len(f.verts)>4])
        deform = bm.verts.layers.deform.active
        deform_names = {bone.name for modifier in mesh.modifiers if modifier.type=='ARMATURE' and modifier.object
                        for bone in modifier.object.data.bones if bone.use_deform}
        deform_indices = {group.index for group in mesh.vertex_groups if group.name in deform_names}
        if deform is None or any(abs(sum(weight for index,weight in v[deform].items() if index in deform_indices)-1)>1e-4 for v in bm.verts if v not in original):
            bm.free()
            raise ValueError('subdivision deform weights must sum to one')
        bm.to_mesh(mesh.data)
        bm.free()
        mesh.data.update()
    for mesh in meshes:
        subdivide(mesh,tips,[level*radius for level in p['subdivide_radii']])
    rows = []
    for tip in tips:
        normal = Vector()
        for mesh in meshes:
            for face in mesh.data.polygons:
                points = [mesh.matrix_world@mesh.data.vertices[i].co for i in face.vertices]
                centre = sum(points,Vector())/len(points)
                if (centre-tip).length <= p['normal_radius']*radius:
                    for j in range(1,len(points)-1):
                        normal += (points[j]-points[0]).cross(points[j+1]-points[0])/2
        if normal.length < 1e-12:
            raise ValueError('tip surface normal is empty')
        normal.normalize()
        if normal.y >= 0:
            normal.negate()
        a = normal.orthogonal().normalized()
        b = normal.cross(a)
        def coords(point):
            d = point-tip
            u,w,h = d.dot(a),d.dot(b),d.dot(normal)
            return u,w,h,math.hypot(u,w)
        unique = {}
        for mesh in meshes:
            for vertex in mesh.data.vertices:
                point = mesh.matrix_world@vertex.co
                unique.setdefault(tuple(round(v,8) for v in point),point)
        ring = [coords(point) for point in unique.values()]
        ring = [(u,w,h) for u,w,h,r in ring if p['fill_radius']*radius <= r <= (p['fill_radius']+p['fill_ring'])*radius and h >= -p['fill_depth']]
        coef,rms = None,None
        reason = 'fewer than 12 ring points'
        if len(ring) >= 12:
            design = np.array([[1,u,w,u*u,u*w,w*w] for u,w,_ in ring])
            heights = np.array([h for _,_,h in ring])
            candidate,_,rank,_ = np.linalg.lstsq(design,heights,rcond=None)
            rms = float(np.sqrt(np.mean((design@candidate-heights)**2)))
            reason = 'rank deficient fit' if rank < 6 else 'RMS exceeds fill_rms_max'
            if rank == 6 and rms <= p['fill_rms_max']:
                coef = candidate
        moved,kept = 0,0
        if coef is not None:
            for mesh in meshes:
                inverse = mesh.matrix_world.inverted()
                for vertex in mesh.data.vertices:
                    u,w,h,r = coords(mesh.matrix_world@vertex.co)
                    if r >= p['fill_radius']*radius or h < -p['fill_depth']:
                        continue
                    fitted = float(np.dot(coef,[1,u,w,u*u,u*w,w*w]))
                    if abs(h-fitted) > p['fill_tolerance']:
                        kept += 1
                        continue
                    factor = smooth((p['fill_radius']*radius-r)/(p['fill_blend']*radius))
                    vertex.co = inverse@(tip+a*u+b*w+normal*(h*(1-factor)+fitted*factor))
                    moved += 1
                mesh.data.update()
        filled = tip+normal*float(coef[0]) if coef is not None else tip.copy()
        axis = (normal-a*float(coef[1])-b*float(coef[2])).normalized() if coef is not None else normal
        rows.append({'tip':list(filled),'axis':list(axis),'radius':radius,'fill':'applied' if coef is not None else 'skipped: '+reason,
                     'fill_rms':rms,'fill_moved':moved,'fill_kept_by_tolerance':kept})
    if p['tip_subdivide'] > 0:
        for mesh in meshes:
            subdivide(mesh,[Vector(row['tip']) for row in rows],[p['tip_subdivide']])
    return rows, before


def tip_height(r, p):
    rc = p['tip_diameter']/2
    cap = min(p['tip_round']*rc,p['tip_length'])
    lw = p['tip_length']-cap
    return lw+cap*math.sqrt(max(0.,1-(r/rc)**2)) if r <= rc else lw*smooth((rc+p['tip_wall']-r)/p['tip_wall'])


def tip_plan(group, p, co, source, rows, before, meshes):
    rc,wall,band = p['tip_diameter']/2,p['tip_wall'],p['tip_band']
    minimum = min(1-3*x*x+2*x*x*x-6*((rc+wall)/band+x)*x*(1-x) for x in np.linspace(0.,1.,10001))
    for row in rows:
        tip,axis = Vector(row['tip']),Vector(row['axis'])
        heights = []
        for i,point in enumerate(co):
            delta = point-tip
            axial = delta.dot(axis)
            if axial < -p['weight_depth']:
                continue
            r = (delta-axis*axial).length
            height = tip_height(r,p)
            if height > 0:
                co[i] = point+axis*height
                heights.append(axial+height)
        row.update(stub_height=max(heights,default=0.),girth_fold_free_max=float(1+1/-minimum) if minimum < 0 else None)
    offset = 0
    for mesh in meshes:
        inverse = mesh.matrix_world.inverted()
        for vertex in mesh.data.vertices:
            vertex.co = inverse@co[offset+vertex.index]
        offset += len(mesh.data.vertices)
        mesh.data.update()
    links,weights,transfers = [],{},[]
    for chain,source_chain,row in zip(group['chains'],source[0]['chains'],rows):
        link = chain[0]
        tip,axis = Vector(row['tip']),Vector(row['axis'])
        head,tail = tip,tip+axis*p['tip_length']
        source_weights = source[2][1][source_chain[0]['bone']]
        values,factors = {},{}
        for i,value in source_weights.items():
            delta = co[i]-tip
            if delta.dot(axis) < -p['weight_depth']:
                continue
            r = (delta-axis*delta.dot(axis)).length
            factor = 1. if r <= rc+wall else smooth((rc+wall+band-r)/band)
            if factor*value > p['weight_min']:
                values[i],factors[i] = factor*value,factor
        if not values:
            return None
        transfers.append((source_weights,factors))
        weights[link['bone']] = values
        links.append((link['bone'],head,tail,link['parent']))
        row.update(head=list(head),tail=list(tail),verts_within_5mm=sum((point-tip).length<.005 for point in co))
    for source_weights,factors in transfers:
        for i,factor in factors.items():
            source_weights[i] *= 1-factor
    return links,weights,{'placement':rows,'vertices_before':before,'vertices_after':len(co)},set(),[]


def unique_positions(indices, co):
    """Deduplicate geometry statistics without merging contact connectivity."""
    return list({tuple(co[i]):i for i in sorted(indices)}.values())


def surface_weld_allowed(i, j, distance, co, normals, adjacency, p):
    dot = normals[i].dot(normals[j])
    if dot >= p['weld_normal_min']:
        return True
    if distance > 1e-6 or dot < -1e-6:
        return False
    # A sharp seam has a coincident boundary edge, not just a contact point.
    return any((co[a]-co[b]).length <= 1e-6
               for a in adjacency.get(i,()) for b in adjacency.get(j,()))


def section_ring(triangles, centre, direction, station, radius):
    """Find a closed cut enclosing the axis and fitting the fixed tube.

    A complete contour, rather than clipped angular support, distinguishes a
    separate ring from a larger connected surface. Its centre is weighted by
    arc length, so subdivision of the same surface does not move the tube.
    """
    basis = min((Vector((1,0,0)), Vector((0,1,0)), Vector((0,0,1))),
                key=lambda v:abs(v.dot(direction)))
    u,v = direction.cross(basis).normalized(),None
    v = direction.cross(u)
    points,adjacency,sources = {},{},{}
    for vertices,heights,ids in triangles:
        if not min(heights) < station <= max(heights):
            continue
        cuts = []
        for k,j in ((0,1),(1,2),(2,0)):
            if (heights[k] < station <= heights[j]) or (heights[j] < station <= heights[k]):
                c = vertices[k]+(vertices[j]-vertices[k])*((station-heights[k])/(heights[j]-heights[k]))
                # Ten-micrometre contour keys close export seam roundtrips.
                # Branches at coincident contacts remain non-ring components.
                key = tuple(round(value,5) for value in c)
                points[key] = c
                cuts.append(key)
        if len(cuts) != 2 or cuts[0] == cuts[1]:
            continue
        a,b = cuts
        adjacency.setdefault(a,set()).add(b)
        adjacency.setdefault(b,set()).add(a)
        sources.setdefault(a,set()).update(ids)
        sources.setdefault(b,set()).update(ids)
    pending = set(adjacency)
    rings = []
    while pending:
        seed = min(pending)
        component,stack = {seed},[seed]
        pending.remove(seed)
        while stack:
            for j in adjacency[stack.pop()]:
                if j not in component:
                    component.add(j); pending.discard(j); stack.append(j)
        if len(component) < 3 or any(len(adjacency[k]) != 2 for k in component):
            continue
        ordered,previous,current = [],None,seed
        while current not in ordered:
            ordered.append(current)
            following = min(adjacency[current]-{previous})
            previous,current = current,following
        if current != seed or len(ordered) != len(component):
            continue
        contour = [points[k] for k in ordered]
        pairs = list(zip(contour,contour[1:]+contour[:1]))
        winding = 0.
        for a,b in pairs:
            a,b = a-centre,b-centre
            winding += math.atan2(a.dot(u)*b.dot(v)-a.dot(v)*b.dot(u),
                                  a.dot(u)*b.dot(u)+a.dot(v)*b.dot(v))
        if abs(winding) < math.pi:
            continue
        perimeter = sum((b-a).length for a,b in pairs)
        measured = sum(((a+b)*(.5*(b-a).length) for a,b in pairs),Vector())/perimeter
        maximum = max((c-measured-direction*(c-measured).dot(direction)).length for c in contour)
        if maximum <= radius:
            support = set().union(*(sources[k] for k in component))
            rings.append((perimeter,measured,maximum,support))
    return min(rings,key=lambda r:r[0]) if rings else None


def grow_attachment(co, edges, part, base, direction, length, p, normals, faces, reference=None):
    """Follow connected surface slices until their cross-section widens into a wall.

    Measure one position per seam. The acceptance radius stays tied to measured
    part slices, so successive growth cannot inflate the tube into a wall.
    """
    step = p['base_slice_size']/length
    axial = [(c-base).dot(direction)/length for c in co]
    kd = KDTree(len(co))
    for i,c in enumerate(co):
        kd.insert(c,i)
    kd.balance()
    ids = list(range(len(co)))
    source_adjacency = {}
    for a,b in edges:
        source_adjacency.setdefault(a,set()).add(b)
        source_adjacency.setdefault(b,set()).add(a)
    def find(i):
        while ids[i] != i:
            ids[i] = ids[ids[i]]
            i = ids[i]
        return i
    for i in range(len(co)):
        for _,j,distance in kd.find_range(co[i],p['weld_distance']):
            if not surface_weld_allowed(i,j,distance,co,normals,source_adjacency,p):
                continue
            a,b = find(i),find(j)
            ids[max(a,b)] = min(a,b)
    welded = [find(i) for i in range(len(co))]
    adj = {}
    for a,b in edges:
        a,b = welded[a],welded[b]
        adj.setdefault(a,set()).add(b)
        adj.setdefault(b,set()).add(a)
    accepted = {welded[i] for i in part}
    connected,stack = set(accepted),list(accepted)
    while stack:
        for j in adj.get(stack.pop(),()):
            if j not in connected:
                connected.add(j); stack.append(j)
    triangles = []
    for face in faces:
        if all(welded[i] in connected for i in face):
            for k in range(1,len(face)-1):
                ids = (face[0],face[k],face[k+1])
                heights = tuple(axial[i]*length for i in ids)
                if max(heights) >= -p['base_extension_max']*length and min(heights) <= 0:
                    triangles.append((tuple(co[i] for i in ids),heights,tuple(welded[i] for i in ids)))
    def section(samples):
        samples = unique_positions(samples,co)
        centre = sum((co[i] for i in samples),Vector())/len(samples)
        radii = sorted((co[i]-centre-direction*(co[i]-centre).dot(direction)).length for i in samples)
        return centre, radii[int(.95*(len(radii)-1))]
    reference_radii = []
    reference = accepted if reference is None else {welded[i] for i in reference} & accepted
    for k in range(max(1,int(1./step))):
        samples = [i for i in reference if k*step <= axial[i] < (k+1)*step]
        if len(samples) >= 3:
            _,r = section(samples)
            reference_radii.append(r)
    if not reference_radii:
        return part, None, [], 0., 'no reference slices', []
    reference_radius = statistics.median(reference_radii)
    seed = [i for i in accepted if p['cut'] <= axial[i] < p['cut']+step]
    centre,_ = section(seed or list(accepted))
    centres, table = [], []
    extension = 0.
    reason = 'base_extension_max reached'
    representatives = set(welded)
    first_slice = -int(math.ceil(p['cut']/step))
    for k in range(first_slice, int(math.ceil(p['base_extension_max']/step))):
        low = max(-p['base_extension_max'], -(k+1)*step)
        high = -k*step
        tube = reference_radius*p['base_radius_margin']
        predicted = centre+direction*((low+high)/2*length-(centre-base).dot(direction))
        candidates = {i for i in representatives if low <= axial[i] < high
                      and (co[i]-predicted-direction*(co[i]-predicted).dot(direction)).length <= tube}
        reached = set()
        stack = list(accepted)
        while stack:
            for j in adj.get(stack.pop(),()):
                if j in candidates and j not in reached:
                    reached.add(j); stack.append(j)
        if not reached:
            table.append({'t':low, 'count':0, 'p95_radius':None,
                          'tube_radius':tube, 'tube_centre':None, 'accepted':False})
            reason = 'no connected slice'
            break
        measured,r95 = section(reached)
        row = {'t':low, 'count':len(reached), 'p95_radius':r95,
               'tube_radius':tube, 'tube_centre':list(measured), 'accepted':False}
        table.append(row)
        stopped = False
        support = set()
        if low < 0:
            steps = max(1,int(math.ceil((high-low)*length/.001)))
            samples = []
            for j in range(1,steps+1):
                station = (high+(low-high)*j/steps)*length
                ring = section_ring(triangles,predicted,direction,station,tube)
                samples.append({'depth_mm':-station*1000,
                                'closed_ring':ring is not None,
                                'radius_mm':ring[2]*1000 if ring else None})
                if ring is None:
                    low = high+(low-high)*(j-1)/steps
                    row['t'] = low
                    reason = 'closed section leaves tube band'
                    stopped = True
                    break
                _,measured,r95,vertices = ring
                support.update(vertices)
            row['section_samples'] = samples
            row['stop_depth_mm'] = -low*length*1000
            row['tube_centre'] = list(measured)
            # Include the connected strip between validated cuts. Fine axial
            # subdivisions can lie wholly between one-millimetre sample planes.
            slab = {i for i in representatives if low <= axial[i] < high
                    and (co[i]-measured-direction*(co[i]-measured).dot(direction)).length <= tube}
            strip = slab & support
            stack = list(strip)
            while stack:
                for j in adj.get(stack.pop(),()):
                    if j in slab and j not in strip:
                        strip.add(j); stack.append(j)
            row['_surface'] = sorted(strip)
            reached = strip
        inside = {i for i in reached if (co[i]-measured-direction*(co[i]-measured).dot(direction)).length <= tube}
        kept = set(); stack = list(accepted)
        while stack:
            for j in adj.get(stack.pop(),()):
                if j in inside and j not in kept:
                    kept.add(j); stack.append(j)
        if not kept:
            if stopped and centres:
                # The stop is geometric even when this last partial slab
                # contains no vertices. Do not quantize it back to a vertex row.
                extension = low
                if support:
                    centres.append(measured)
                else:
                    measured = centres[-1]
                row.update(accepted=True,accepted_count=0,count=0,p95_radius=None,
                           centre=list(measured),tube_centre=list(measured))
                break
            reason = 'no connected tube slice'
            break
        # This measured centre defines filtering, completion and containment.
        centre = measured
        row['count'] = len(kept)
        kept_radii = sorted((co[i]-centre-direction*(co[i]-centre).dot(direction)).length
                            for i in unique_positions(kept,co))
        row['p95_radius'] = kept_radii[int(.95*(len(kept_radii)-1))]
        row.update(accepted=True, accepted_count=len(kept), centre=list(centre))
        accepted.update(kept)
        if low < 0:
            centres.append(centre)
            extension = low
        if stopped:
            break
    if not centres:
        return part, None, centres, extension, reason, table
    return accepted, welded, centres, extension, reason, table


def polyline_station(c, joints, boundaries):
    """Return declared fraction, physical distance from root, and line distance."""
    nearest = None
    distance_from_root = 0.
    for j,(head,tail) in enumerate(zip(joints,joints[1:])):
        delta = tail-head
        if delta.length_squared < 1e-12:
            raise ValueError('centerline segment has zero length')
        local = max(0.,min(1.,(c-head).dot(delta)/delta.length_squared))
        distance = (c-head-delta*local).length_squared
        if nearest is None or distance < nearest[0]:
            nearest = (distance,boundaries[j]+local*(boundaries[j+1]-boundaries[j]),
                       distance_from_root+local*delta.length)
        distance_from_root += delta.length
    return nearest[1], nearest[2], math.sqrt(nearest[0])


def sagittal_segments(co, faces, base, face_segments=None):
    """Intersect faces with x=base.x, retaining endpoint mesh-edge identities."""
    segments = []
    for face_index,face in enumerate(faces):
        vertices = [co[i] for i in face]
        if len(vertices) < 3 or not min(c.x for c in vertices) <= base.x <= max(c.x for c in vertices):
            continue
        normal = sum(((vertices[i]-vertices[0]).cross(vertices[i+1]-vertices[0])
                      for i in range(1,len(vertices)-1)), Vector())
        if math.hypot(normal.y,normal.z) < 1e-15:
            continue
        hits = []
        for ia,ib in zip(face,face[1:]+face[:1]):
            a,b = co[ia],co[ib]
            if a.x == base.x:
                hits.append((a,(ia,ia)))
            if (a.x-base.x)*(b.x-base.x) < 0:
                hits.append((a.lerp(b,(base.x-a.x)/(b.x-a.x)),tuple(sorted((ia,ib)))))
        unique = []
        for hit,edge in hits:
            matching = next((row for row in unique if (hit-row[0]).length < 1e-9),None)
            if matching is None:
                unique.append((hit,{edge}))
            else:
                matching[1].add(edge)
        # Concave faces can yield several segments on the same section line.
        unique.sort(key=lambda row: -normal.z*row[0].y+normal.y*row[0].z)
        for segment in zip(unique[::2],unique[1::2]):
            if face_segments is not None:
                face_segments.setdefault(face_index,[]).append(len(segments))
            segments.append(segment)
    return segments


def gap_ceiling(co, faces, base, joints, segments, start_index=1, face_segments=None):
    """Locate the local contour peak above a +Y exit followed by a +Z ray."""
    gap = {'gap_exit':None, 'gap_ceiling':None, 'joint_index':None,
           'entry_walked':False, 'attempts':[], 'gap_reason':''}
    bvh = BVHTree.FromPolygons(co,faces)
    if face_segments is None:
        face_segments = {}
        sagittal_segments(co,faces,base,face_segments)
    ceiling = None
    start_segment = None
    forward = Vector((0,1,0))
    epsilon = 1e-6
    for index in range(start_index,len(joints)-1):
        origin = joints[index].copy()
        origin.x = base.x
        attempt = {'joint_index':index, 'entry_walked':False, 'reason':'no +Y exit'}
        gap['attempts'].append(attempt)
        exit_point = None
        # A negative normal is an entry: continue through the part to an exit.
        # Bound the walk by face count, including degenerate/tangential hits.
        for _ in range(len(faces)+1):
            hit,normal,_,_ = bvh.ray_cast(origin,forward)
            if hit is None:
                break
            if normal.dot(forward) > 0:
                exit_point = hit
                break
            if normal.dot(forward) < 0:
                attempt['entry_walked'] = True
            origin = hit+forward*epsilon
        if exit_point is None:
            continue
        # With an outward exit, no intervening +Y surface proves that the
        # entire E..Q interval stays in air, rather than only testing Q.
        next_hit,_,_,distance = bvh.ray_cast(exit_point+forward*epsilon,forward)
        if next_hit is not None and distance <= .002-epsilon:
            attempt['reason'] = 'gap clearance below 2 mm'
            continue
        hit,_,face_index,_ = bvh.ray_cast(exit_point+forward*.002,Vector((0,0,1)))
        if hit is None:
            attempt['reason'] = 'gap ceiling not found'
            continue
        # BVH polygon indices refer to the input faces, not section-list order.
        candidates = []
        for segment_index in face_segments.get(face_index,()):
            (a,_),(b,_) = segments[segment_index]
            delta = b-a
            t = max(0.,min(1.,(hit-a).dot(delta)/delta.length_squared)) if delta.length_squared else 0.
            candidates.append(((a+delta*t-hit).length,segment_index))
        if not candidates or min(candidates)[0] > 1e-6:
            attempt['reason'] = 'hit face section missing'
            continue
        start_segment = min(candidates)[1]
        ceiling = hit
        attempt['reason'] = ''
        gap.update(gap_exit=list(exit_point),gap_ceiling=list(ceiling),joint_index=index,
                   entry_walked=attempt['entry_walked'])
        break
    if ceiling is None or not segments:
        gap['gap_reason'] = gap['attempts'][-1]['reason'] if gap['attempts'] else 'gap ceiling not found'
        return None,gap

    endpoints = [endpoint for segment in segments for endpoint in segment]
    parents = list(range(len(endpoints)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def join(a,b):
        a,b = root(a),root(b)
        parents[max(a,b)] = min(a,b)

    tree = KDTree(len(endpoints))
    edge_nodes = {}
    for index,(point,keys) in enumerate(endpoints):
        tree.insert(point,index)
        for key in keys:
            if key in edge_nodes:
                join(index,edge_nodes[key])
            else:
                edge_nodes[key] = index
    tree.balance()
    for index,(point,_) in enumerate(endpoints):
        for _,other,_ in tree.find_range(point,1e-6):
            join(index,other)
    neighbours = {}
    for index in range(0,len(endpoints),2):
        a,b = root(index),root(index+1)
        neighbours.setdefault(a,set()).add(b)
        neighbours.setdefault(b,set()).add(a)
    # Split only the hit face's section segment at H. A closer endpoint on
    # another contour must never determine which connected contour we climb.
    a,b = root(start_segment*2),root(start_segment*2+1)
    current = len(endpoints)
    endpoints.append((ceiling,set()))
    neighbours[a].discard(b)
    neighbours[b].discard(a)
    neighbours.setdefault(a,set()).add(current)
    neighbours.setdefault(b,set()).add(current)
    neighbours[current] = {a,b}
    visited = set()
    while True:
        plateau = {current}; stack = [current]; higher = set()
        visited.add(current)
        while stack:
            node = stack.pop()
            for other in neighbours[node]:
                if other in visited:
                    continue
                dz = endpoints[other][0].z-endpoints[node][0].z
                if abs(dz) <= 1e-7:
                    visited.add(other); plateau.add(other); stack.append(other)
                elif dz > 1e-7:
                    higher.add(other)
        higher.difference_update(visited)
        if not higher:
            peak = max(plateau,key=lambda i: (endpoints[i][0].z,-i))
            return endpoints[peak][0],gap
        current = max(higher,key=lambda i: (endpoints[i][0].z,-i))


def torso_chord(co, faces, base, joints, start_index=1):
    """Find F in the existing z band and K by rays and a local contour walk."""
    front_points = []

    def clipped(a, b, bounds):
        low, high = 0., 1.
        for axis, minimum, maximum in bounds:
            delta = b[axis]-a[axis]
            if abs(delta) < 1e-15:
                if not minimum <= a[axis] <= maximum:
                    return ()
            else:
                t0, t1 = (minimum-a[axis])/delta, (maximum-a[axis])/delta
                low, high = max(low,min(t0,t1)), min(high,max(t0,t1))
                if low > high:
                    return ()
        return tuple(Vector((base.x, a[1]+t*(b[1]-a[1]),
                             a[2]+t*(b[2]-a[2]))) for t in (low,high))

    face_segments = {}
    segments = sagittal_segments(co,faces,base,face_segments)
    for (a,_),(b,_) in segments:
        front_points.extend(clipped(a,b,((2,base.z+.02,base.z+.05),)))
    ceiling,gap = gap_ceiling(co,faces,base,joints,segments,start_index,face_segments)
    return (min(front_points,key=lambda c:c.y) if front_points else None,ceiling,gap)


def solve_pivot(base, front, ceiling, anchor, target, p):
    """Solve the linear signed chord distance along the fixed +Y/+Z bisector."""
    depth, reason, capped = p['root_depth'], '', False
    distance = slope = None
    if front is None or ceiling is None:
        reason = 'gap ceiling not found' if ceiling is None else 'front point missing'
    else:
        dy, dz = ceiling.y-front.y, ceiling.z-front.z
        chord_length = math.hypot(dy,dz)
        if chord_length < 1e-15:
            reason = 'degenerate chord'
        else:
            ny, nz = -dz/chord_length, dy/chord_length
            if ny*(anchor.y-front.y)+nz*(anchor.z-front.z) < 0:
                ny, nz = -ny, -nz
            distance = ny*(base.y-front.y)+nz*(base.z-front.z)
            slope = (ny+nz)/math.sqrt(2)
            if abs(slope) < 1e-9:
                reason = 'pivot direction parallel to chord'
            else:
                if distance+depth*slope < p['root_wall_margin']:
                    if slope > 0:
                        depth = max(depth,(p['root_wall_margin']-distance)/slope)
                    else:
                        depth = float('inf')
                        reason = 'inward margin unreachable'
    maximum = (target-base).length
    if depth > maximum:
        depth, capped = maximum, True
    head = base+Vector((0,1,1)).normalized()*depth
    margin = None if distance is None else distance+depth*slope
    return head, {'front':list(front) if front is not None else None,
                  'gap_apex':list(ceiling) if ceiling is not None else None,
                  'depth':depth, 'margin':margin, 'capped':capped, 'reason':reason}


def appendage_plan(group, p, co, edges, bones, normals, faces):
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
    kd = KDTree(len(co))
    for i,c in enumerate(co):
        kd.insert(c,i)
    kd.balance()

    source_adjacency = {}
    for a,b in edges:
        source_adjacency.setdefault(a,set()).add(b)
        source_adjacency.setdefault(b,set()).add(a)

    def flood():
        eligible = {i for i,c in enumerate(co)
                    if abs(t_of(c)-.5) < axial_window and radial(c) <= segment_radius}
        ids = list(range(len(co)))
        # Rebuild bounded seam welding for each axis; an excluded seam cannot bridge.
        def find(i):
            while ids[i] != i:
                ids[i] = ids[ids[i]]
                i = ids[i]
            return i
        for i in eligible:
            for _,j,distance in kd.find_range(co[i],p['weld_distance']):
                if j in eligible and surface_weld_allowed(i,j,distance,co,normals,source_adjacency,p):
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
        support = {welded[i] for i in cand if i in eligible and welded[i] in keep
                   and abs(co[i].x-cx) < p['part_half_width']}
        if not support:
            raise ValueError('axis candidates are outside segmented window')
        # A sharp end face can be disconnected by the contact-normal guard.
        # Choose the component supported by the detected surface, rather than
        # an arbitrary UV copy of the closest end position.
        pending = set(support)
        choices = []
        while pending:
            seed = min(pending)
            component,stack = {seed},[seed]
            while stack:
                for j in adj.get(stack.pop(),()):
                    if j in keep and j not in component:
                        component.add(j); stack.append(j)
            pending.difference_update(component)
            choices.append((len(component & support),
                            -min((co[i]-detected_tip).length for i in component),component))
        comp = max(choices,key=lambda row:row[:2])[2]
        captured = {i for i in eligible if welded[i] in comp}
        return eligible,welded,win,comp,captured

    eligible,welded,win,comp,captured = flood()
    initial_base = base.copy()
    history = [{'pass':0, 'radius':segment_radius, 'vertices':len(captured),
                'axis_base':list(base), 'axis_tip':list(detected_tip), 'axis_shift':0.}]
    refinement_reason = 'segment_passes reached'
    for iteration in range(1, int(p['segment_passes'])+1):
        if len(comp) < p['segment_min_vertices'] or max(t_of(co[i]) for i in captured) > p['leak_t_limit']:
            refinement_reason = 'initial component rejected'
            break
        previous = (base.copy(), direction.copy(), detected_tip.copy(), segment_radius,
                    eligible,welded,win,comp,captured)
        # One sample per welded position avoids UV seam multiplicity bias.
        samples = [co[i] for i in unique_positions(comp,co)]
        centre = sum(samples,Vector())/len(samples)
        covariance = [[sum((v[a]-centre[a])*(v[b]-centre[b]) for v in samples)/len(samples)
                       for b in range(3)] for a in range(3)]
        new_direction = direction.copy()
        for _ in range(int(p['axis_iterations'])):
            v = Vector([sum(covariance[a][b]*new_direction[b] for b in range(3)) for a in range(3)])
            if v.length < 1e-10:
                raise ValueError('degenerate refined principal axis')
            new_direction = v.normalized()
        if new_direction.dot(direction) < 0:
            new_direction.negate()
        # Keep the attachment station and length; only project onto the new axis.
        # Re-fitting truncated axial endpoints would move the cut on every pass.
        base = centre+new_direction*(previous[0]-centre).dot(new_direction)
        direction = new_direction
        detected_tip = base+direction*length
        radii = sorted(radial(v) for v in samples)
        rank = p['segment_radius_percentile']*(len(radii)-1)
        lower = int(rank)
        measured = radii[lower]+(radii[min(lower+1,len(radii)-1)]-radii[lower])*(rank-lower)
        segment_radius = measured*p['segment_radius_margin']
        reason = ''
        if segment_radius > previous[3]*p['segment_radius_growth_max']:
            reason = 'segment_radius_growth_max exceeded'
        else:
            try:
                eligible,welded,win,comp,captured = flood()
            except ValueError as exc:
                reason = str(exc)
            if not reason:
                if max(t_of(co[i]) for i in captured) > p['leak_t_limit']:
                    reason = 'refined component exceeds leak_t_limit'
                elif len(comp) < p['segment_min_vertices']:
                    reason = 'refined component has too few vertices'
        if reason:
            base,direction,detected_tip,segment_radius,eligible,welded,win,comp,captured = previous
            refinement_reason = reason+'; previous pass retained'
            break
        change = len(captured ^ previous[8])/max(1,len(previous[8]))
        shift = (base-initial_base).length
        history.append({'pass':iteration, 'radius':segment_radius, 'vertices':len(captured),
                        'axis_base':list(base), 'axis_tip':list(detected_tip),
                        'axis_shift':shift, 'vertex_change_fraction':change})
        if change < .01:
            refinement_reason = 'vertex set changed less than 1%'
            break
    tmax = max(t_of(co[i]) for i in captured)
    rmax = max(radial(co[i]) for i in captured)
    leak_reasons = []
    if len(comp) < p['segment_min_vertices']:
        leak_reasons.append('bounded component has too few vertices')
    if tmax > p['leak_t_limit']:
        leak_reasons.append('bounded component exceeds leak_t_limit')
    leak = bool(leak_reasons)
    root = Vector((base.x,max(base.y+p['root_depth'],front(base.z)+p['root_wall_margin']),base.z))
    part = set()
    extension_t, growth_reason, slice_table = 0., 'component rejected', []
    growth_centres = []
    attachment_station = base.copy()
    if not leak:
        radii = sorted(radial(co[i]) for i in comp)
        r = radii[min(len(radii)-1,int(p['ring_radius_percentile']*len(radii)))]
        # Metre-scale float roundtrips may put the attachment plane just below zero.
        ring = {i for i in win if -1e-6 <= t_of(co[i]) < p['cut'] and radial(co[i]) <= r*p['ring_radius_scale']}
        part = comp|ring
        part, grown_welded, growth_centres, extension_t, growth_reason, slice_table = grow_attachment(
            co, edges, part, base, direction, length, p, normals, faces,
            {i for i in cand if abs(co[i].x-cx) < p['part_half_width']})
        if growth_centres:
            welded = grown_welded
            eligible.update(i for i in range(len(co)) if welded[i] in part)
        geometry = unique_positions(part,co)
        near = [co[i] for i in geometry if t_of(co[i]) < p['cut']+p['near_slice_margin']] or [co[i] for i in geometry]
        far = [co[i] for i in geometry if t_of(co[i]) > p['far_slice_fraction']*tmax] or [co[i] for i in geometry]
        base_c,tip_c = sum(near,Vector())/len(near),sum(far,Vector())/len(far)
        if growth_centres:
            base_c = growth_centres[-1]
        if (base_c-tip_c).length < 1e-6:
            raise ValueError('segmented centre line is degenerate')
        root_station = base_c+(base_c-tip_c).normalized()*p['attachment_inset']
        if growth_centres:
            attachment_station = base_c+direction*(extension_t*length-(base_c-base).dot(direction))
            # Build internal joints and axis length from the measured stop
            # plane. Only after building joints, move the root along +Y/+Z
            # until the pivot reaches the inward torso-chord margin;
            # the physical weight ramp stays on this measured stop plane.
            root_station = attachment_station.copy()
        root = root_station
        tip = tip_c
    axis_length = (tip-root).length if leak else (tip-root).dot(direction)
    if axis_length < 1e-6:
        raise ValueError('chain length is zero')
    splits = p['chain_split']
    if len(splits) != len(chain)-1:
        raise ValueError('chain_split must have one entry per internal chain joint')
    boundaries = [0]+splits+[1]
    joints = [root]
    for fraction in splits:
        station = root.lerp(tip,fraction) if leak else root+direction*(fraction*axis_length)
        if not leak:
            samples = [co[i] for i in geometry
                       if abs((co[i]-station).dot(direction)) <= p['centerline_slab']*axis_length/2]
            if not samples:
                raise ValueError('empty centerline slab at joint '+str(fraction))
            centre = sum(samples,Vector())/len(samples)
            station += centre-station-direction*(centre-station).dot(direction)
        joints.append(station)
    joints.append(tip)
    weight_joints = joints
    pivot = {'front':None, 'gap_apex':None, 'depth':0., 'margin':None,
             'capped':False, 'reason':'leak path unchanged',
             'gap_exit':None, 'gap_ceiling':None, 'joint_index':None}
    if not leak:
        # Preserve the attachment polyline for weights and contact followers.
        # The pivot starts at the unmoved root: the stop station after growth,
        # otherwise the inset root. attachment_station keeps its meaning for
        # the contact-follow distance.
        weight_joints = joints.copy()
        front_point, ceiling_point, gap = torso_chord(co,faces,root,joints)
        joints[0], pivot = solve_pivot(root,front_point,ceiling_point,
                                       anchor,target,p)
        if ceiling_point is None:
            pivot['reason'] = gap['gap_reason']
        pivot.update(gap)
    links = [(link['bone'],joints[i],joints[i+1],link['parent']) for i,link in enumerate(chain)]
    tube_radius = None
    tube_centres = []
    if not leak:
        if not slice_table:
            raise ValueError('no measured tube cross-section')
        tube_radius = slice_table[0]['tube_radius']
        step = p['base_slice_size']/length
        for k in range(math.floor(extension_t/step), math.ceil(tmax/step)):
            samples = [co[i] for i in geometry if k*step <= t_of(co[i]) < (k+1)*step]
            if samples:
                tube_centres.append(sum(samples,Vector())/len(samples))
        if len(tube_centres) < 2:
            raise ValueError('insufficient tube centreline slices')
        endpoint = tube_centres[0]+direction*(extension_t*length-(tube_centres[0]-base).dot(direction))
        if (endpoint-tube_centres[0]).length > 1e-6:
            tube_centres.insert(0,endpoint)
        endpoint = tube_centres[-1]+direction*(tmax*length-(tube_centres[-1]-base).dot(direction))
        if (endpoint-tube_centres[-1]).length > 1e-6:
            tube_centres.append(endpoint)
        tube_boundaries = [i/(len(tube_centres)-1) for i in range(len(tube_centres))]
        def inside_growth_slice(i):
            c = co[i]
            t = t_of(c)
            if t >= 0:
                return True
            high = math.ceil(p['cut']/step)*step
            for row in slice_table:
                if row['accepted'] and row['t'] <= t < high:
                    if welded[i] not in row['_surface']:
                        return False
                    delta = c-Vector(row['tube_centre'])
                    return (delta-direction*delta.dot(direction)).length <= tube_radius
                high = row['t']
            return False
        # Complete the connected surface, including the contact side omitted by
        # protrusion candidates. Axial bounds preserve the attachment stop.
        inside = {welded[i] for i in range(len(co))
                  if extension_t-1e-6 <= t_of(co[i]) <= tmax+1e-6
                  and inside_growth_slice(i)
                  and polyline_station(co[i],tube_centres,tube_boundaries)[2] <= tube_radius}
        adjacency = {}
        for a,b in edges:
            a,b = welded[a],welded[b]
            adjacency.setdefault(a,set()).add(b)
            adjacency.setdefault(b,set()).add(a)
        seeds = inside & part
        seed = min(seeds,key=lambda i:(co[i]-tip).length) if seeds else None
        part,stack = ({seed},[seed]) if seed is not None else (set(),[])
        while stack:
            for j in adjacency.get(stack.pop(),()):
                if j in inside and j not in part:
                    part.add(j); stack.append(j)
        eligible.update(i for i in range(len(co)) if welded[i] in part)
    weights = {link['bone']: {} for link in chain}
    top,bottom = max(v.z for v in points),min(v.z for v in points)
    affected = set()
    for i,c in enumerate(co):
        t,station,distance = polyline_station(c,weight_joints,boundaries)
        if not leak:
            if (i not in eligible or welded[i] not in part
                    or not inside_growth_slice(i)
                    or polyline_station(c,tube_centres,tube_boundaries)[2] > tube_radius):
                continue
            affected.add(i)
            # Membership separates neighbouring surfaces. Every surface point
            # outside the physical attachment ring has full total chain weight.
            if growth_centres:
                # The stop is an axial surface plane, not a nearest-link
                # projection: a bent first link projects opposite sides of
                # one ring to different stations and creates a weight step.
                station = max(0., (c-attachment_station).dot(direction))
                value = smooth(station/min(p['weight_ramp']*axis_length,
                                           p['attachment_ring_max']))
            else:
                value = smooth(max(t/p['weight_ramp'],station/p['attachment_ring_max']))
        else:
            if abs(c.x-cx)>p['fallback_half_width'] or not bottom-p['fallback_z_margin'] < c.z < top+p['fallback_z_margin']:
                continue
            value = smooth((front(c.z)-p['protrusion_threshold']*p['fallback_front_fraction']-c.y)/p['fallback_front_ramp'])*smooth((p['fallback_half_width']-abs(c.x-cx))/p['fallback_side_ramp'])*smooth((top+p['fallback_top_margin']-c.z)/p['fallback_top_ramp'])
        if value <= p['weight_min']:
            continue
        affected.add(i)
        shares = [0.]*len(chain)
        index = sum(t >= split for split in splits)
        shares[index] = 1.
        for j,split in enumerate(splits):
            if abs(t-split) <= p['link_blend']:
                blend = (t-split+p['link_blend'])/(2*p['link_blend'])
                shares = [0.]*len(chain)
                shares[j],shares[j+1] = 1-blend,blend
                break
        for link,share in zip(chain,shares):
            if share*value > 0:
                weights[link['bone']][i] = share*value
    if any(not any(value > .9 for value in w.values()) for w in weights.values()):
        raise ValueError('chain link has no core vertices (weight > 0.9)')
    for row in slice_table:
        row.pop('_surface',None)
    metrics = {
        'base_extension_t':extension_t, 'base_stop_reason':growth_reason,
        'base_stop_depth_mm':-extension_t*length*1000,
        'base_slice_table':slice_table,
        'stem_vertices_captured':sum(t_of(co[i]) < 0 for i in affected),
        'tube_radius':tube_radius, 'tube_centerline':[list(c) for c in tube_centres],
        'attachment_ring_max':p['attachment_ring_max'],
        'placement': [{'head':list(h),'tip':list(t)} for _,h,t,_ in links],
        'weight_joints':[list(c) for c in weight_joints],
        'attachment':list(attachment_station), 'axis_length':axis_length,
        'root_offset':list(joints[0]-weight_joints[0]), 'pivot':pivot,
        'leak':leak, 'leak_reason':'; '.join(leak_reasons),
        'segment_radius':segment_radius, 'measured_half_width':half_width,
        'segment_pass_history':history, 'segment_passes':len(history)-1,
        'segment_stop_reason':refinement_reason, 'segment_axis_shift':(base-initial_base).length,
        'segment_cut_t':p['cut'], 'segment_axis_length':length,
        'segment_axis_base':list(base), 'segment_axis_tip':list(detected_tip),
        'part_vertex_count':len(affected), 'segment_t_max':tmax,
        'segment_radius_max':rmax,
    }
    return links,weights,metrics,affected,p['reweight_from']


def contact_follow_weights(p, co, edges, faces, plan):
    """Shared-face and coincident-copy seeds are d=0; follow eligible edges.

    The nearest-tube distance guard applies to every follower, including points
    dominated by declared source joints. Such points qualify only within the
    edge-path contact zone; distant source-joint surfaces cannot receive weight.
    Tube weights and transfer membership are never changed.
    """
    weights, m, tube = plan[1], plan[2], plan[3]
    follow = {name:{} for name in weights}
    if m['leak'] or not tube:
        return follow, 0
    weight_joints = [Vector(c) for c in m.get('weight_joints',
                    [m['placement'][0]['head']]+[row['tip'] for row in m['placement']])]
    boundaries = [0]+p['chain_split']+[1]
    base = Vector(m['segment_axis_base'])
    axis = (Vector(m['segment_axis_tip'])-base).normalized()
    def attachment_distance(i):
        if m['base_extension_t'] < 0:
            return max(0.,(co[i]-Vector(m['attachment'])).dot(axis))
        return polyline_station(co[i],weight_joints,boundaries)[1]
    full = {i for i in tube if sum(w.get(i,0.) for w in weights.values()) >= .9}
    outside = {i for i in full if attachment_distance(i) > p['attachment_ring_max']}
    contacts = [face for face in faces if any(i in outside for i in face) and any(i not in tube for i in face)]
    if not p['contact_follow_weight'] or not outside:
        return follow, len(contacts)
    kd = KDTree(len(full))
    for i in sorted(full):
        kd.insert(co[i],i)
    kd.balance()
    limit = p['contact_follow_distance']
    nearest = {}
    def eligible(i):
        if i in tube:
            return False
        if i not in nearest:
            _,source,distance = kd.find(co[i])
            station = attachment_distance(i)
            axial = (co[i]-base).dot(axis)/m['segment_axis_length']
            nearest[i] = source if (distance <= limit and station > p['attachment_ring_max']
                                    and axial >= m['base_extension_t']-1e-6) else None
        return nearest[i] is not None
    adjacency = {}
    for a,b in edges:
        adjacency.setdefault(a,[]).append(b)
        adjacency.setdefault(b,[]).append(a)
    distances = {i:0. for face in contacts for i in face if eligible(i)}
    # A crease can have separate tube/body copies without any shared face.
    # Only outside full tube vertices seed, with the same eligibility guards.
    copies = KDTree(len(co))
    for i,c in enumerate(co):
        copies.insert(c,i)
    copies.balance()
    for i in sorted(outside):
        for j in sorted(j for _,j,_ in copies.find_range(co[i],COINCIDENT_EPSILON_M)):
            if eligible(j):
                distances[j] = 0.
    queue = [(0.,i) for i in distances]
    heapq.heapify(queue)
    while queue:
        d,i = heapq.heappop(queue)
        if d != distances[i]:
            continue
        for j in adjacency.get(i,()):
            if not eligible(j):
                continue
            candidate = d+(co[i]-co[j]).length
            if candidate < limit and candidate < distances.get(j,float('inf')):
                distances[j] = candidate
                heapq.heappush(queue,(candidate,j))
    for i,d in sorted(distances.items()):
        value = p['contact_follow_weight']*smooth(1-d/limit)
        source = nearest[i]
        total = sum(w.get(source,0.) for w in weights.values())
        for name,w in weights.items():
            share = w.get(source,0.)/total
            if share*value > 0:
                follow[name][i] = share*value
    return follow, len(contacts)


def unify_coincident_weights(co, owners, joint_index, final_weights):
    """Unify differing exported copies after all transfer and influence limits.

    Positional connected components ignore normals. Agreeing groups receive no
    writes. Return the global changed-group count, including body-only groups.
    """
    copies = KDTree(len(co))
    for i,c in enumerate(co):
        copies.insert(c,i)
    copies.balance()
    parent = list(range(len(co)))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i,c in enumerate(co):
        for j in sorted(j for _,j,_ in copies.find_range(c,COINCIDENT_EPSILON_M) if j > i):
            a,b = root(i),root(j)
            parent[max(a,b)] = min(a,b)
    groups = {}
    for i in range(len(co)):
        groups.setdefault(root(i),[]).append(i)
    changed = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        weights = []
        for i in group:
            mesh,vi = owners[i]
            weights.append({mesh.vertex_groups[ge.group].name:ge.weight
                            for ge in mesh.data.vertices[vi].groups
                            if mesh.vertex_groups[ge.group].name in joint_index and ge.weight > 0})
        if all(w == weights[0] for w in weights[1:]):
            continue
        # Rank exactly rounded sums: dividing per copy, or summing in copy
        # order, lets rounding break ties that the lower joint index decides.
        # Normalising the kept sums gives the same shares as averaging.
        names = {name for w in weights for name in w}
        average = {name:math.fsum(w.get(name,0.) for w in weights) for name in names}
        kept = sorted(average.items(),key=lambda entry:(-entry[1],joint_index[entry[0]]))[:4]
        total = sum(value for _,value in kept)
        for i in group:
            mesh,vi = owners[i]
            for ge in list(mesh.data.vertices[vi].groups):
                vg = mesh.vertex_groups[ge.group]
                if vg.name in joint_index:
                    vg.remove([vi])
            for name,value in kept:
                vg = mesh.vertex_groups.get(name) or mesh.vertex_groups.new(name=name)
                vg.add([vi],value/total,'REPLACE')
            for values in final_weights.values():
                values.pop(i,None)
            # Blender stores float weights; metrics use the values actually written.
            for ge in mesh.data.vertices[vi].groups:
                name = mesh.vertex_groups[ge.group].name
                if name in final_weights and ge.weight > 0:
                    final_weights[name][i] = ge.weight
        changed += 1
    return changed


def contact_inside_weights(p, co, edges, faces, plan, follow):
    """Ramp full tube weights inward, preserving follower values and link shares.

    Coincident full vertices share a graph node, distance and boundary value.
    Equal shortest paths prefer the lowest seed index. Seeds stay outside the
    attachment ring; propagation includes every full tube vertex (total >= .9).
    """
    limit = p['contact_inside_distance']
    weights, m, tube = plan[1], plan[2], plan[3]
    if not limit or m['leak'] or not tube:
        return set()
    joints = [Vector(c) for c in m['weight_joints']]
    boundaries = [0]+p['chain_split']+[1]
    axis = (Vector(m['segment_axis_tip'])-Vector(m['segment_axis_base'])).normalized()
    def outside_ring(i):
        station = (max(0., (co[i]-Vector(m['attachment'])).dot(axis))
                   if m['base_extension_t'] < 0 else polyline_station(co[i],joints,boundaries)[1])
        return station > p['attachment_ring_max']
    full = {i for i in tube if sum(w.get(i,0.) for w in weights.values()) >= .9}
    seeds = {i for i in full if outside_ring(i)}
    contacts = [face for face in faces if any(i in seeds for i in face)
                and any(i not in tube for i in face)]
    if not contacts:
        return set()
    # Collapse position copies without a normal guard: UV seams share weights.
    parent = {i:i for i in full}
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    kd = KDTree(len(full))
    for i in sorted(full):
        kd.insert(co[i],i)
    kd.balance()
    for i in sorted(full):
        for _,j,_ in sorted(kd.find_range(co[i],p['weld_distance']),key=lambda row:row[1]):
            a,b = root(i),root(j)
            parent[max(a,b)] = min(a,b)
    welded = {i:root(i) for i in sorted(full)}
    adjacency = {}
    for a,b in sorted(edges):
        if a not in full or b not in full:
            continue
        u,v = welded[a],welded[b]
        if u == v:
            continue
        distance = (co[a]-co[b]).length
        for x,y in ((u,v),(v,u)):
            row = adjacency.setdefault(x,{})
            row[y] = min(distance,row.get(y,float('inf')))
    boundary, seed_indices = {}, {}
    for face in sorted(contacts):
        value = max((sum(w.get(i,0.) for w in follow.values())
                     for i in face if i not in tube),default=0.)
        for i in sorted(seeds.intersection(face)):
            seed = welded[i]
            boundary[seed] = max(value,boundary.get(seed,0.))
            seed_indices[seed] = min(i,seed_indices.get(seed,i))
    # A welded representative can be a non-contact copy, not an actual seed.
    seed_boundary = {seed_indices[i]:boundary[i] for i in sorted(boundary)}
    distances = {i:(0.,seed_indices[i]) for i in sorted(boundary)}
    queue = [(0.,seed_indices[i],i) for i in sorted(boundary)]
    heapq.heapify(queue)
    while queue:
        d,seed,i = heapq.heappop(queue)
        if (d,seed) != distances[i]:
            continue
        for j,length in sorted(adjacency.get(i,{}).items()):
            candidate = (d+length,seed)
            if candidate[0] < limit and candidate < distances.get(j,(float('inf'),float('inf'))):
                distances[j] = candidate
                heapq.heappush(queue,(candidate[0],seed,j))
    ramped = set()
    for i,node in welded.items():
        if node not in distances:
            continue
        distance,seed = distances[node]
        b = seed_boundary[seed]
        factor = b+(1-b)*smooth(distance/limit)
        if factor < 1:
            ramped.add(i)
            for w in weights.values():
                if i in w:
                    w[i] *= factor
    if any(not any(value > .9 for value in w.values()) for w in weights.values()):
        raise ValueError('chain link has no core vertices (weight > 0.9)')
    return ramped


def contact_follow_entries(entries, extension_names):
    """Fit overlapping extension shares plus the original remainder into four slots."""
    extension = [(vg,w) for vg,w in entries if vg.name in extension_names]
    original = [(vg,w) for vg,w in entries if vg.name not in extension_names]
    chain_total = min(1.,sum(w for _,w in extension))
    if not original and chain_total >= 1-1e-6:
        chain_total = 1.
    extension = extension[:3 if chain_total < 1 else 4]
    retained_total = sum(w for _,w in extension)
    kept = [(vg,w/retained_total*chain_total) for vg,w in extension]
    if chain_total < 1:
        original = original[:4-len(extension)]
        original_total = sum(w for _,w in original)
        if not original_total:
            raise ValueError('contact follower requires original bone weights')
        kept.extend((vg,w/original_total*(1-chain_total)) for vg,w in original)
    return kept


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
            captured = plan[3] if plan[2] else weighted
            ramped = plan[6] if len(plan)>6 else set()
            plan[2]['contact_inside_ramped'] = len(ramped)
            plan[2]['contact_inside_weight_min'] = min(
                (sum(w.get(i,0.) for w in plan[1].values()) for i in ramped),default=1.)
            plan[2]['core_verts_per_link'] = {name:sum(v > .9 for v in w.values()) for name,w in plan[1].items()}
            directions = [(tail-head).normalized() for _,head,tail,_ in plan[0]]
            plan[2]['bind_bend_deg'] = [math.degrees(a.angle(b)) for a,b in zip(directions,directions[1:])]
            sources = {bone_key(n) for n in p['reweight_from']}
            offset = 0
            remaining = 0
            for mesh in meshes:
                for vertex in mesh.data.vertices:
                    if offset+vertex.index in captured:
                        remaining += sum(ge.weight for ge in vertex.groups
                                         if bone_key(mesh.vertex_groups[ge.group].name) in sources) > .1
                offset += len(mesh.data.vertices)
            plan[2]['thigh_weight_in_part'] = remaining
            if 'segment_axis_base' in plan[2]:
                m = plan[2]
                base = Vector(m['segment_axis_base'])
                axis = (Vector(m['segment_axis_tip'])-base).normalized()
                offset = 0
                uncaptured = beyond = outside_base = 0
                for mesh in meshes:
                    for vertex in mesh.data.vertices:
                        delta = mesh.matrix_world@vertex.co-base
                        axial = delta.dot(axis)
                        radial = (delta-axis*axial).length
                        t = axial/m['segment_axis_length']
                        index = offset+vertex.index
                        uncaptured += (m['segment_cut_t'] <= t <= m['segment_t_max']
                                       and radial <= .9*m['segment_radius'] and index not in weighted)
                        beyond += index in captured and t >= m['segment_cut_t'] and radial > 1.05*m['segment_radius']
                        if index in captured and t < -1e-6:
                            rows = m.get('base_slice_table', [])
                            high = math.ceil(p['cut']*m['segment_axis_length']/p['base_slice_size'])*p['base_slice_size']/m['segment_axis_length']
                            inside = False
                            for row in rows:
                                if row['accepted'] and row['t'] <= t < high:
                                    delta_tube = mesh.matrix_world@vertex.co-Vector(row['tube_centre'])
                                    inside = (delta_tube-axis*delta_tube.dot(axis)).length <= row['tube_radius']+1e-6
                                    break
                                high = row['t']
                            outside_base += not inside
                    offset += len(mesh.data.vertices)
                m['uncaptured_in_part'] = uncaptured
                m['captured_beyond_radius'] = beyond
                m['captured_outside_base_tube'] = outside_base
                weight_joints = [Vector(c) for c in m['weight_joints']]
                boundaries = [0]+p['chain_split']+[1]
                tube_centres = [Vector(c) for c in m['tube_centerline']]
                tube_boundaries = [i/(len(tube_centres)-1) for i in range(len(tube_centres))] if tube_centres else []
                offset = 0
                partial = outside_ring = beyond_tube = missing = outside_weighted = 0
                maximum_distance = 0.
                for mesh in meshes:
                    for vertex in mesh.data.vertices:
                        index = offset+vertex.index
                        _,station,distance = polyline_station(mesh.matrix_world@vertex.co,weight_joints,boundaries)
                        if m['base_extension_t'] < 0:
                            station = max(0., (mesh.matrix_world@vertex.co-Vector(m['attachment'])).dot(axis))
                        if tube_centres:
                            distance = polyline_station(mesh.matrix_world@vertex.co,tube_centres,tube_boundaries)[2]
                        value = sum(w.get(index,0.) for w in plan[1].values())
                        is_partial = .1 < value < .9
                        partial += is_partial and index in captured
                        outside_ring += index in captured and index not in ramped and is_partial and station > p['attachment_ring_max']+1e-6
                        outside_weighted += index not in captured and index not in (plan[5] if len(plan)>5 else set()) and value > .1
                        if index in captured:
                            maximum_distance = max(maximum_distance,distance)
                            if m['tube_radius'] is not None:
                                beyond_tube += distance > m['tube_radius']+1e-6
                            missing += index not in ramped and station > p['attachment_ring_max']+1e-6 and value < .9
                    offset += len(mesh.data.vertices)
                m.update(partial_weight_vertices=partial, partial_outside_attachment_ring=outside_ring,
                         captured_beyond_tube_radius=beyond_tube, captured_tube_distance_max=maximum_distance,
                         weighted_outside_part=outside_weighted, uncaptured_in_part=missing)

        if g['op']=='pair_tip' and plan[2].get('placement'):
            lift = []
            for row in plan[2]['placement']:
                tip,axis = Vector(row['tip']),Vector(row['axis'])
                nearest = min(range(len(rest)),key=lambda i:(rest[i]-(tip+axis*p['tip_length'])).length_squared)
                rc = p['tip_diameter']/2
                lw = p['tip_length']-min(p['tip_round']*rc,p['tip_length'])
                ring = []
                for i,point in enumerate(rest):
                    delta = point-tip
                    axial = delta.dot(axis)
                    r = (delta-axis*axial).length
                    if axial >= -p['weight_depth'] and abs(r-rc) < p['tip_wall']/2 and tip_height(r,p) > lw/2:
                        moved = posed[i]-tip
                        ring.append((moved-axis*moved.dot(axis)).length)
                row['diameter'] = 2*statistics.mean(ring) if ring else None
                value = float((posed[nearest]-rest[nearest]).dot(Vector(row['axis'])))
                row['lift'] = value
                lift.append(value)
            plan[2]['lift'] = lift
        if len(plan)>5:
            values = [sum(w.get(i,0.) for w in plan[1].values()) for i in plan[5]]
            plan[2].update(contact_tissue_vertices_weighted=sum(v>0 for v in values),
                           contact_follow_weight_max=max(values,default=0.),
                           contact_follow_weight_mean=statistics.mean(values) if values else 0.)
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
    co,edges,owners,normals,faces = mesh_arrays(meshes)
    if args['params'].get('metrics_only',False):
        plans=[]
        absent={}
        for g in enabled:
            try:
                p=parameters(g)
                names = [link['bone'] for chain in g['chains'] for link in chain]
                if all(bone_key(name) not in bones for name in names):
                    absent[g['id']] = {'status':'not_found','reason':'Group bones absent from model'}
                    continue
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
        metrics.update(absent)
        return {'status':'applied','reason':'','groups':metrics,'metrics':metrics},{}
    try:
        if len({g['id'] for g in enabled})!=len(enabled):
            raise ValueError('duplicate group id')
        declared = {}
        for g in enabled:
            for chain in g['chains']:
                for link in chain:
                    name = link['bone']
                    if name in declared or bone_key(name) in bones or any(bone_key(name)==bone_key(other) for other in declared):
                        raise ValueError('bone already exists: '+name)
                    declared[name] = g['id']
        dependencies = {}
        for g in enabled:
            parents = set()
            for chain in g['chains']:
                earlier = set()
                for link in chain:
                    parent = link['parent']
                    if bone_key(parent) not in bones and parent not in earlier:
                        if earlier or parent not in declared or declared[parent]==g['id']:
                            raise ValueError('missing enabled chain parent: '+parent)
                        parents.add(declared[parent])
                    earlier.add(link['bone'])
            if g.get('depends_on'):
                parents.add(g['depends_on'])
            dependencies[g['id']] = parents
        remaining = list(enabled)
        enabled = []
        while remaining:
            ready = sorted([g for g in remaining if dependencies[g['id']] <= {v['id'] for v in enabled}],key=lambda g:g['id'])
            if not ready:
                raise ValueError('missing enabled dependency or dependency cycle')
            enabled.extend(ready)
            remaining = [g for g in remaining if g not in ready]
        for g in enabled:
            p = parameters(g)
            validate_references(p,bones)
            if g['op']=='pair_protrusion' and (len(g['chains'])!=2 or any(len(c)!=1 for c in g['chains'])):
                raise ValueError('pair_protrusion requires two one-link chains')
            if g['op']=='appendage_chain' and (len(g['chains'])!=1 or not g['chains'][0]):
                raise ValueError('appendage_chain requires one nonempty chain')
            if g['op']=='pair_tip':
                source = next((v for v in enabled if v['id']==g.get('depends_on')),None)
                if source is None or source['op']!='pair_protrusion' or len(g['chains'])!=2 or any(len(c)!=1 for c in g['chains']):
                    raise ValueError('pair_tip requires a pair_protrusion dependency and two one-link chains')
                if [c[0]['parent'] for c in g['chains']] != [c[0]['bone'] for c in source['chains']]:
                    raise ValueError('pair_tip parents must match source sides')
    except (ValueError,KeyError,TypeError,IndexError) as e:
        return skip(str(e),status='failed')
    def plan_sources(pinned):
        surface = pair_surface(meshes) if any(g['op']=='pair_protrusion' for g in enabled) else None
        plans,failed,names = [],{},set()
        planning_bones = dict(bones)
        # Parent identity is available before tip placement; source geometry is independent.
        for g in enabled:
            if g['op']=='pair_tip':
                for chain in g['chains']:
                    name = chain[0]['bone']
                    planning_bones[bone_key(name)] = SimpleNamespace(name=name,children_recursive=[])
        malformed = False
        for g in enabled:
            if g['op']=='pair_tip':
                continue
            try:
                try:
                    p = parameters(g)
                    validate_references(p,planning_bones)
                    chains = g['chains']
                    if g['op']=='pair_protrusion' and (len(chains)!=2 or any(len(c)!=1 for c in chains)):
                        raise ValueError('pair_protrusion requires two one-link chains')
                    if g['op']=='appendage_chain' and (len(chains)!=1 or not chains[0]):
                        raise ValueError('appendage_chain requires one nonempty chain')
                except (ValueError, KeyError, TypeError) as e:
                    malformed = True
                    raise ValueError(str(e)) from e
                plan = pair_plan(g,p,co,planning_bones,surface,owners,pinned=pinned.get(g['id'])) if g['op']=='pair_protrusion' else appendage_plan(g,p,co,edges,planning_bones,normals,faces)
                if g['op']=='appendage_chain':
                    follow,count = contact_follow_weights(p,co,edges,faces,plan)
                    followers = {i for w in follow.values() for i in w}
                    ramped = contact_inside_weights(p,co,edges,faces,plan,follow)
                    plan = (*plan,followers,ramped)
                    plan[2]['contact_faces_outside_ring'] = count
                    for name,w in follow.items():
                        plan[1][name].update(w)
                for name,h,t,parent in plan[0]:
                    if name in names or bone_key(name) in bones:
                        raise ValueError('bone already exists: '+name)
                    if (t-h).length < 1e-6:
                        raise ValueError('bone has zero length: '+name)
                    names.add(name)
                    planning_bones[bone_key(name)] = SimpleNamespace(name=name,head_local=h,tail_local=t,children_recursive=[])
                plans.append((g,p,plan))
            except (ValueError,KeyError,TypeError,IndexError) as e:
                failed[g['id']] = str(e)
        return plans,failed,malformed
    plans,failed,malformed = plan_sources({})
    if failed:
        return skip('; '.join(k+': '+v for k,v in failed.items()),failed,'failed' if malformed else 'not_found')
    soft,prepared = {},{}
    pinned = {g['id']:plan[2]['placement'] for g,p,plan in plans
              if g['op']=='pair_protrusion' and all(row['apex_source']=='colour' for row in plan[2]['placement'])}
    try:
        for g in enabled:
            if dependencies[g['id']].intersection(soft):
                soft[g['id']] = {'status':'not_found','reason':'Source group was not found'}
                continue
            if g['op']!='pair_tip':
                continue
            if g['depends_on'] not in pinned:
                soft[g['id']] = {'status':'not_found','reason':'Source placement is not colour'}
                continue
            p = parameters(g)
            prepared[g['id']] = tip_mesh(meshes,p,pinned[g['depends_on']])
        if prepared:
            co,edges,owners,normals,faces = mesh_arrays(meshes)
            plans,failed,malformed = plan_sources(pinned)
            if failed:
                return skip('; '.join(k+': '+v for k,v in failed.items()),failed,'failed')
            for g in enabled:
                if g['id'] not in prepared:
                    continue
                source = next(row for row in plans if row[0]['id']==g['depends_on'])
                p = parameters(g)
                rows,before = prepared[g['id']]
                plan = tip_plan(g,p,co,source,rows,before,meshes)
                if plan is None:
                    soft[g['id']] = {'status':'not_found','reason':'Empty tip weights; mesh remains modified'}
                else:
                    if any(bone_key(name) in bones or any(name==other for _,_,previous in plans for other,_,_,_ in previous[0]) for name,_,_,_ in plan[0]):
                        raise ValueError('tip bone already exists')
                    plans.append((g,p,plan))
    except (ValueError,KeyError,TypeError,IndexError) as e:
        return skip(str(e),status='failed')
    for g in enabled:
        if not any(row[0]['id']==g['id'] for row in plans) and g['id'] not in soft:
            soft[g['id']] = {'status':'not_found','reason':'Source group was not found'}
    for g in enabled:
        if dependencies[g['id']].intersection(soft):
            soft[g['id']] = {'status':'not_found','reason':'Source group was not found'}
    plans = [row for row in plans if row[0]['id'] not in soft]
    order = {g['id']:i for i,g in enumerate(enabled)}
    plans.sort(key=lambda row:order[row[0]['id']])
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
    # Edit mode rebuilds the bone data; references cached before it are stale.
    bones = {bone_key(b.name):b for b in arm.data.bones}
    totals,allweights={},{}
    followers = set().union(*(plan[5] for g,p,plan in plans if len(plan)>5))
    ramped = set().union(*(plan[6] for g,p,plan in plans if len(plan)>6))
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
        if i in followers or i in ramped:
            kept = contact_follow_entries(entries,allweights)
            kept_names = {vg.name for vg,_ in kept}
            for vg,_ in entries:
                if vg.name not in kept_names:
                    vg.remove([vi])
        else:
            kept=entries[:4]
            for vg,_ in entries[4:]:
                vg.remove([vi])
        total=sum(w for _,w in kept)
        for vg,w in kept:
            vg.add([vi],w/total,'REPLACE')
            if vg.name in final_weights:
                final_weights[vg.name][i]=w/total
    coincident_groups_unified = unify_coincident_weights(co,owners,joint_index,final_weights)
    # Counts and posed geometry must describe the representation we export.
    for g,_,plan in plans:
        if g['op'] == 'appendage_chain':
            plan[2]['coincident_groups_unified'] = coincident_groups_unified
        for name in plan[1]:
            plan[1][name]=final_weights[name]
        if g['op'] == 'appendage_chain' and any(not any(v > .9 for v in w.values()) for w in plan[1].values()):
            return skip('chain link has no exported core vertices (weight > 0.9)',status='failed')
    metrics=measure(arm,meshes,edges,plans)
    metrics.update(soft)
    output=Path(args['out_dir'])/'model.glb'
    bpy.ops.export_scene.gltf(filepath=str(output),export_format='GLB',export_apply=False,export_yup=True,export_skins=True,export_animations=True,export_morph=True,export_all_influences=False)
    return {'status':'applied','reason':'','groups':metrics,'metrics':metrics},{'model':str(output)}


_common.main(extension_bones)
