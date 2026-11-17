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
# Metres: when the largest colour blobs do not make a mirrored pair, a smaller
# blob still counts as the tip if it sits this close (front view) to the
# front-most vertex of its side. Measured: tips half hidden by hair 8 mm,
# hair or fabric blobs 48 mm and more; accepted primary tips reach 34 mm,
# which is why this is only the fallback and not a filter on the primary pair.
MARKER_APEX_REACH_M = .02
# Metres: the fallback fill when the wide ring does not fit levels only the tip,
# out to the inner edge of the ring its own surface is fitted on (8 mm).
LOCAL_FILL_RADIUS_M = .008
# A body counts as double-walled from this many enclosed vertices around the
# tips (measured: UniForge 474-5563; creases and seams of single-walled bodies
# a handful).
DOUBLE_WALL_MIN_VERTICES = 100
LOCAL_FILL_BLEND_M = .003

PARAMETERS = {'pair_protrusion': {'band_lower_bone': 'bone',
                     'band_upper_bone': 'bone',
                     'band_lower_offset': 'number',
                     'band_upper_offset': 'number',
                     'lateral_min': 'number',
                     'lateral_max': 'number',
                     'marker_search_radius': 'number',
                     'apex_smooth_radius': 'number',
                     'apex_plateau_depth': 'number',
                     'apex_context_radius': 'number',
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
                     'fade_down': 'number',
                     'fade_up': 'number',
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
    positive = ('marker_search_radius', 'apex_smooth_radius', 'apex_plateau_depth', 'apex_context_radius', 'marker_grid_step', 'marker_area_min',
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
        if not 0 < p['fade_down'] <= p['fade_up']:
            raise ValueError('fade_down must be positive and fade_up at least fade_down')
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


def marker_accept(lab, p):
    """Which colour-window cells (rows of CIE Lab) belong to a tip marker.

    A marker cell is redder and less yellow than the reference skin tone by
    more than marker_score_min, neither much darker nor much lighter. The
    reference comes from the cells that pass the darkness gate: a dark strand
    of hair across the window (Tilda: about 40 % of the cells, L 37 / a 10)
    otherwise drags the median toward its own red and a faint tip next to it
    drops below marker_score_min (Ruling A120). Without such cells the gated
    median is the plain one."""
    med = np.median(lab,axis=0)
    skin = lab[:,0] > p['marker_dark_min']*med[0]
    if skin.sum() >= 10:
        med = np.median(lab[skin],axis=0)
    score = lab[:,1]-med[1]-p['marker_yellow_weight']*(lab[:,2]-med[2])
    return (score>p['marker_score_min'])&(lab[:,0]>p['marker_dark_min']*med[0])&(lab[:,0]<med[0]+p['marker_light_max'])


# Marker-free outline of a chest pair (Ruling A160), used when no colour marker
# is found (a reference post-process removed the tips before the texture was
# made). Measured on two such models and one with a marker: the underside
# crease of each half-round is a jump of the front depth along a ray from the
# bump (slope 4-38 m/m below and at the side, under 1.6 above and toward the
# midline), so it is read where it is sharp; the shadow under it (luminance
# 3-12 % below the half-round) admits a softer jump. The top has no crease:
# the half-round fades into the upper chest, which runs as a straight line in
# the side profile; the top is where the surface leaves that line.
OUTLINE_ANGLES_DEG = tuple(range(0,166,15))   # from straight down (0) over the side (90) to the lower midline side
OUTLINE_RAY_MAX_M = .11
OUTLINE_CREASE_SLOPE = 3.                     # depth jump per metre along the ray: a crease on its own
OUTLINE_SHADED_SLOPE = 1.5                    # a softer jump counts with a shadow at it
OUTLINE_SHADOW = .97                          # boundary luminance below this share of the half-round's
OUTLINE_POINTS_MIN = 5                        # crease points per side
OUTLINE_RMS_MAX_M = .008                      # circle fit residual
OUTLINE_ARC_TOLERANCE_M = .01
OUTLINE_LINE_SPAN_M = (.02,.03)               # upper chest line: below / above the band top
OUTLINE_LINE_LEAVE_M = .002                   # the surface stands this far in front of the line
OUTLINE_BUMP_SIGMAS_M = (.006,.04)
# The top line never lies below this share of the crease circle's radius above
# its centre (Vallerie: the upper chest line runs on into the half-round's
# upper slope and leaves it 1 cm above the centre; the shading fades 3 cm above).
OUTLINE_TOP_MIN = .75
UPPER_CHEST_SLOPE = .7
UNDERSIDE_SLOPE = 1.5
# Metres: the strip at the sternum over which the pair's weight fades to zero.
MIDLINE_STRIP_M = .01
OUTER_SIDE_SLOPE = .35


def outline_locate(p, front, mid, lo, hi):
    """Locate both half-rounds of a chest pair without a colour marker.

    Returns ``(outline, note)``: ``outline`` is None when the shape is not
    found, otherwise ``{'centre': [d, z], 'radius', 'top', 'bottom', 'outer',
    'seed': [d, z], 'points': [n+, n-], 'rms', 'shaded'}`` in side coordinates
    (``d`` = distance from the midline, one outline mirrored onto both
    sides). Steps: a seed per side at the mirrored best bump of the front depth
    (small blur minus wide blur), rays from it downward and sideways whose
    steepest depth jump is the crease (with its shadow), one circle fitted to
    the crease points of both sides, and the top where the surface leaves the
    straight upper chest line."""
    step = p['marker_grid_step']
    margin = math.ceil(3*OUTLINE_BUMP_SIGMAS_M[1]/step)
    zs = lo-.06+step*np.arange(int((hi-lo+.06)/step)+1)
    ds = step*np.arange(int((p['lateral_max']+.02)/step)+1)
    zs_m = np.concatenate((zs[0]-step*np.arange(margin,0,-1),zs,zs[-1]+step*np.arange(1,margin+1)))
    ds_m = np.concatenate((ds,ds[-1]+step*np.arange(1,margin+1)))
    def blur(a,sigma):
        reach = math.ceil(3*sigma/step)
        kernel = np.exp(-.5*(np.arange(-reach,reach+1)*step/sigma)**2)
        a = np.apply_along_axis(lambda r:np.convolve(r,kernel,'same'),0,a)
        return np.apply_along_axis(lambda r:np.convolve(r,kernel,'same'),1,a)
    bumps = []
    for sign in (1,-1):
        depth = np.full((len(zs_m),len(ds_m)),np.nan)
        for j,z in enumerate(zs_m):
            for i,d in enumerate(ds_m):
                hit = front(float(mid+sign*d),float(z))
                if hit:
                    depth[j,i] = hit[0].y
        known = ~np.isnan(depth)
        sm = [blur(np.where(known,depth,0.),s)/np.maximum(blur(known.astype(float),s),1e-9) for s in OUTLINE_BUMP_SIGMAS_M]
        bumps.append(np.where(known,sm[1]-sm[0],np.nan)[margin:margin+len(zs),:len(ds)])
    score = bumps[0]+bumps[1]
    band = (zs[:,None] > lo-.03)&(zs[:,None] < hi)&(ds[None,:] > p['lateral_min'])&(ds[None,:] < p['lateral_max']-.01)
    score = np.where(band&~np.isnan(score),score,-np.inf)
    if not np.isfinite(score.max()):
        return None,'outline: no surface'
    j,i = np.unravel_index(int(np.argmax(score)),score.shape)
    sd,sz = float(ds[i]),float(zs[j])
    def luminance(rgb):
        return float(.2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2])
    points,counts,shaded = [],[],0
    ts = np.arange(.005,OUTLINE_RAY_MAX_M,step/2)
    for sign in (1,-1):
        n = 0
        for a in OUTLINE_ANGLES_DEG:
            u = (math.sin(math.radians(a)),-math.cos(math.radians(a)))
            ys,lum = np.full(len(ts),np.nan),np.full(len(ts),np.nan)
            for k,t in enumerate(ts):
                d,z = sd+u[0]*t,sz+u[1]*t
                if d <= p['side_margin']:
                    break
                hit = front(float(mid+sign*d),float(z),True)
                if hit:
                    ys[k] = hit[0].y
                    if hit[1] is not None:
                        lum[k] = luminance(hit[1])
            if np.isnan(ys).sum() > len(ts)-3:
                continue
            g = np.gradient(np.where(np.isnan(ys),np.nanmax(ys),ys),ts)
            k = int(np.nanargmax(g))
            ok = g[k] > OUTLINE_CREASE_SLOPE
            if not ok and g[k] > OUTLINE_SHADED_SLOPE and np.isfinite(lum[k]):
                inside = np.nanmedian(lum[:max(k-2,1)])
                ring = lum[max(k-2,0):k+3]
                ok = bool(np.isfinite(inside) and np.nanmin(ring) < OUTLINE_SHADOW*inside)
                shaded += ok
            if ok:
                points.append((sd+u[0]*ts[k],sz+u[1]*ts[k]))
                n += 1
        counts.append(n)
    if min(counts) < OUTLINE_POINTS_MIN:
        return None,'outline: %d/%d crease points'%tuple(counts)
    P = np.array(points)
    A = np.c_[2*P,np.ones(len(P))]
    c = np.linalg.lstsq(A,(P**2).sum(axis=1),rcond=None)[0]
    cd,cz = float(c[0]),float(c[1])
    radius = math.sqrt(max(c[2]+cd*cd+cz*cz,0.))
    rms = float(np.sqrt(((np.hypot(P[:,0]-cd,P[:,1]-cz)-radius)**2).mean()))
    # The circle may reach past the midline (a wide pair, Gelina: centre 4.8 cm,
    # radius 7.4 cm): the outline's inner edge is measured on its own below.
    if rms > OUTLINE_RMS_MAX_M or not p['boundary_s_min'] <= radius <= p['boundary_s_max']:
        return None,'outline: circle d %.3f r %.3f rms %.4f'%(cd,radius,rms)
    # Top: per column near the centre, the upper chest line fitted above the
    # band top, extended down; the highest point standing in front of it.
    below,above = OUTLINE_LINE_SPAN_M
    tops = []
    for sign in (1,-1):
        for d in cd+step*np.arange(-4,5):
            line = [(z,front(float(mid+sign*d),float(z))) for z in np.arange(hi-below,hi+above+1e-9,step)]
            line = [(z,h[0].y) for z,h in line if h]
            if len(line) < 5:
                continue
            fit = np.polyfit([z for z,_ in line],[y for _,y in line],1)
            for z in np.arange(hi-below,cz,-step):
                h = front(float(mid+sign*d),float(z))
                if h and np.polyval(fit,z)-h[0].y > OUTLINE_LINE_LEAVE_M:
                    tops.append(float(z))
                    break
    line_top = float(np.median(tops)) if tops else cz+radius
    top = max(line_top,cz+OUTLINE_TOP_MIN*radius)
    # Inner edge: the cleavage wall, the steepest backward step of the depth on
    # rows from the seed toward the midline around the circle's centre height.
    inner = []
    for z in cz+step*np.arange(-4,5):
        for sign in (1,-1):
            row = [(d,front(float(mid+sign*d),float(z))) for d in np.arange(sd,p['side_margin'],-step)]
            row = [(d,h[0].y) for d,h in row if h]
            if len(row) < 3:
                continue
            g = np.gradient([y for _,y in row],[-d for d,_ in row])
            inner.append(row[int(np.argmax(g))][0])
    inner = max(float(np.median(inner)) if inner else cd-radius,p['side_margin'])
    bottom,outer = float(P[:,1].min()),float(P[:,0].max())
    # The crease points must lie on the circle's lower half: its bottom and
    # outer side where the crease is (measured 2-3 mm off on both models; a
    # cap without an undercut, whose steepest steps scatter, 5 cm).
    if abs(cz-radius-bottom) > OUTLINE_ARC_TOLERANCE_M or abs(cd+radius-outer) > OUTLINE_ARC_TOLERANCE_M:
        return None,'outline: crease off its circle (bottom %.3f/%.3f, outer %.3f/%.3f)'%(bottom,cz-radius,outer,cd+radius)
    if outer-inner < 2*p['boundary_s_min'] or top-bottom < 2*p['boundary_s_min']:
        return None,'outline: extent %.3f x %.3f'%(outer-inner,top-bottom)
    return ({'centre':[.5*(inner+outer),.5*(bottom+top)],'half':[.5*(outer-inner),.5*(top-bottom)],
             'inner':inner,'outer':outer,'bottom':bottom,'top':top,'line_top':line_top,
             'circle':[cd,cz,radius],'seed':[sd,sz],'points':counts,'rms':rms,'shaded':shaded},
            'outline %.1f x %.1f cm, %d+%d crease points'%((outer-inner)*100,(top-bottom)*100,*counts))


def outline_reach(outline, apex_d, apex_z, directions):
    """Distance from an apex (side coordinates) to the outline along each
    boundary direction ``(lateral, up)``: the axis-aligned ellipse spanned by
    the measured inner edge, outer side, crease bottom and top."""
    (cd,cz),(a,b) = outline['centre'],outline['half']
    out = []
    for dx,dz in directions:
        fx,fz = (apex_d-cd)/a,(apex_z-cz)/b
        ux,uz = dx/a,dz/b
        qa,qb,qc = ux*ux+uz*uz,2*(fx*ux+fz*uz),fx*fx+fz*fz-1
        disc = qb*qb-4*qa*qc
        out.append(max((-qb+math.sqrt(disc))/(2*qa) if disc > 0 else min(a,b),1e-3))
    return out


def pair_plan(group, p, co, bones, front, owners, pinned=None):
    chains = group['chains']
    if len(chains) != 2 or any(len(c) != 1 for c in chains):
        raise ValueError('pair_protrusion requires two one-link chains')
    lo = lookup(bones,p['band_lower_bone']).head_local.z+p['band_lower_offset']
    hi = lookup(bones,p['band_upper_bone']).head_local.z+p['band_upper_offset']
    if lo >= hi:
        raise ValueError('empty height band')
    # The tip search runs on a smoothed front depth map, not on single vertices:
    # under clothing the front is a flat plateau whose front-most vertex is a
    # fold, seam or bow rather than the shape's crest. The crest is where the
    # map (blurred by apex_smooth_radius) stands furthest in front of its
    # surroundings (blurred by apex_context_radius), so torso tilt and rib cage
    # curvature drop out. Both sides are scored together on cells mirrored
    # about the body midline.
    step = p['marker_grid_step']
    mid = .5*(lookup(bones,p['lateral_positive_bone']).head_local.x+lookup(bones,p['lateral_negative_bone']).head_local.x)
    # The map extends 3 sigma beyond the candidate cells (across the midline
    # too), so the blur near the candidate edge does not average one-sidedly.
    margin = math.ceil(3*p['apex_context_radius']/step)
    zs = lo+step*np.arange(-margin,int(math.floor((hi-lo)/step+1e-9))+1+margin)
    ds = p['lateral_min']+step*np.arange(-margin,int(math.floor((p['lateral_max']-p['lateral_min'])/step+1e-9))+1+margin)
    def crest_search():
        # Built only in geometry mode: about 60k front rays.
        def blur(a,sigma):
            reach = math.ceil(3*sigma/step)
            kernel = np.exp(-.5*(np.arange(-reach,reach+1)*step/sigma)**2)
            a = np.apply_along_axis(lambda r:np.convolve(r,kernel,'same'),0,a)
            return np.apply_along_axis(lambda r:np.convolve(r,kernel,'same'),1,a)
        def normalised(depth,known,sigma):
            return blur(np.where(known,depth,0.),sigma)/np.maximum(blur(known.astype(float),sigma),1e-9)
        grids = []
        for sign in (1,-1):
            depth = np.full((len(zs),len(ds)),np.nan)
            for j,z in enumerate(zs):
                for i,d in enumerate(ds):
                    hit = front(float(mid+sign*d),float(z))
                    if hit:
                        depth[j,i] = hit[0].y
            known = ~np.isnan(depth)
            smoothed = np.where(known,normalised(depth,known,p['apex_smooth_radius']),np.nan)
            grids.append((depth,smoothed,normalised(depth,known,p['apex_context_radius'])-smoothed))
        paired = [(j,i) for j,i in zip(*np.nonzero(~np.isnan(grids[0][0])&~np.isnan(grids[1][0])))
                  if margin <= j < len(zs)-margin and margin <= i < len(ds)-margin]
        if not paired:
            raise ValueError('no protrusion candidates on both sides')
        def cell(j,i,sign):
            return Vector((mid+sign*ds[i],grids[0 if sign==1 else 1][1][j,i],zs[j]))
        def pick(score):
            # Centre of the crest: a flat plateau has no single best cell, so the
            # connected cells within apex_plateau_depth per side are averaged.
            values = {c:score(c) for c in paired}
            seed = max(values,key=values.get)
            level = values[seed]-2*p['apex_plateau_depth']
            crest,stack = {seed},[seed]
            while stack:
                j,i = stack.pop()
                for c in ((j+1,i),(j-1,i),(j,i+1),(j,i-1)):
                    if c not in crest and values.get(c,-math.inf) >= level:
                        crest.add(c)
                        stack.append(c)
            d = sum(ds[i] for _,i in crest)/len(crest)
            z = sum(zs[j] for j,_ in crest)/len(crest)
            out = []
            for sign in (1,-1):
                hit = front(float(mid+sign*d),float(z))
                if hit is None:
                    raise ValueError('crest centre missed surface')
                out.append(Vector((mid+sign*d,hit[0].y,z)))
            return out
        return cell,pick,pick(lambda c:grids[0][2][c]+grids[1][2][c])
    # The colour search still starts at each side's front-most vertex.
    frontmost = []
    for sign in (1,-1):
        side = [v for v in co if lo < v.z < hi and p['lateral_min'] < sign*v.x < p['lateral_max']]
        if not side:
            raise ValueError('no protrusion candidates on side '+str(sign))
        frontmost.append(min(side,key=lambda v:v.y))
    marker_areas = [None,None]
    def marker(apex,sign):
        step,radius = p['marker_grid_step'],p['marker_search_radius']
        cells = {}
        count = int(radius/step)
        for j in range(-count,count+1):
            for i in range(-count,count+1):
                x,z = apex.x+i*step,apex.z+j*step
                if math.hypot(i*step,j*step) > radius or sign*(x-mid) <= p['side_margin']:
                    continue
                hit = front(x,z,True)
                if hit and hit[1] is not None:
                    cells[i,j] = (x,z,hit[1])
        if len(cells) < 10:
            return [],'no texture'
        keys = sorted(cells)
        rgb = np.array([cells[k][2] for k in keys])
        linear = np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
        xyz = linear@np.array([[.4124,.2126,.0193],[.3576,.7152,.1192],[.1805,.0722,.9505]])
        xyz /= np.array([.9505,1.,1.089])
        f = np.where(xyz>.008856,np.cbrt(xyz),7.787*xyz+16/116)
        lab = np.stack((116*f[:,1]-16,500*(f[:,0]-f[:,1]),200*(f[:,1]-f[:,2])),axis=1)
        ok = marker_accept(lab,p)
        pending = {k for k,accepted in zip(keys,ok) if accepted}
        components = []
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
            components.append(component)
        if not components:
            return [],'no marker'
        # Every plausible blob is a candidate: hair of a similar tone over the
        # chest can form a blob larger than the tip itself (Lirien: 4.7 cm2
        # strand edge vs 2.5 cm2 tip). The largest blob stays the primary
        # choice; the rest only feed the fallback below.
        candidates,note = [],''
        components.sort(key=len,reverse=True)
        for component in components:
            points = np.array([cells[k][:2] for k in component])
            centre = points.mean(axis=0)
            area = len(component)*step*step
            reason = 'area %.1f cm2'%(area*1e4)
            hit = None
            if not p['marker_area_min'] <= area <= p['marker_area_max']:
                failure = reason
            elif math.sqrt(((points-centre)**2).sum(axis=1).mean()) > p['marker_spread_max']:
                failure = 'marker spread'
            else:
                hit = front(*centre)
                failure = '' if hit else 'centroid miss'
            # The note is always the largest blob's, as the primary choice reports.
            note = note or failure or reason
            if hit:
                candidates.append((Vector((centre[0],hit[0].y,centre[1])),area,reason,component is components[0]))
        return candidates,note
    if pinned is not None:
        markers = []
        for row in pinned:
            x,z = row['tip'][0],row['tip'][2]
            hit = front(x,z)
            if not hit:
                raise ValueError('pinned marker missed modified surface')
            markers.append((Vector((x,hit[0].y,z)),row['marker_note']))
        marker_areas = [row['marker_area'] for row in pinned]
        # A geometry placement is pinned only for a dependent tip group: it
        # keeps its crest apex and its round outline, no new crest search;
        # an outline placement keeps its apex and its measured outline.
        colour = all(row['apex_source']=='colour' for row in pinned)
        extent = {'pinned':[row['reach'] for row in pinned]} if colour and all(row.get('outline') for row in pinned) else None
        outline = {'pinned':[row['reach'] for row in pinned]} if all(row['apex_source']=='outline' for row in pinned) else None
    else:
        found = [marker(v,sign) for v,sign in zip(frontmost,(1,-1))]
        mirrored = lambda a,b: abs(a[0].z-b[0].z)<p['marker_pair_dz'] and abs((a[0].x-mid)+(b[0].x-mid))<p['marker_pair_dx']
        # Primary: the largest blob of each side, as long as it is plausible
        # (an oversized largest blob, e.g. patterned fabric, rules colour out).
        primary = [cands[0] if cands and cands[0][3] else None for cands,_ in found]
        pairs = [tuple(primary)] if all(primary) and mirrored(*primary) else []
        if not pairs and all(c for c,_ in found):
            # Fallback for a tip partly hidden by hair: a mirrored pair of
            # blobs at the crest, the front-most one.
            near = [[c for c in cands if math.hypot(c[0].x-start.x,c[0].z-start.z) <= MARKER_APEX_REACH_M]
                    for (cands,_),start in zip(found,frontmost)]
            pairs = sorted(((a,b) for a in near[0] for b in near[1] if mirrored(a,b)),
                           key=lambda pair:pair[0][0].y+pair[1][0].y)[:1]
        colour = bool(pairs)
        outline = None
        outline,outline_note = outline_locate(p,front,mid,lo,hi)
        # With a marker the outline still sets the region (Ruling A164): the
        # tangent reach mirrors the medial side onto the lateral one and
        # stops short of the outer side and the top on a full pair.
        extent = outline if colour else None
        if colour:
            outline = None
        if colour:
            markers = [(c[0],c[2] if c[3] else c[2]+'; at crest') for c in pairs[0]]
            marker_areas = [c[1] for c in pairs[0]]
        else:
            markers = [((c[0] if c else None),(('pair mismatch; '+note) if all(primary) else note)+'; '+outline_note)
                       for c,(_,note) in zip(primary,found)]
    K = int(p['boundary_directions'])
    directions = [(math.sin(2*math.pi*k/K),math.cos(2*math.pi*k/K)) for k in range(K)]
    def walls(apexes, fixed=None):
        side_reach = [list(r) for r in fixed] if fixed else []
        for apex,sign in zip(apexes,() if fixed else (1,-1)):
            reach = [None]*K
            for k,(dx,dz) in enumerate(directions):
                if dx > 1e-6:
                    continue
                best = None
                steps = int(math.floor((p['boundary_s_max']-p['boundary_s_min'])/p['boundary_step']+1e-8))
                for j in range(steps+1):
                    distance = p['boundary_s_min']+j*p['boundary_step']
                    x,z = apex.x+sign*dx*distance,apex.z+dz*distance
                    if sign*(x-mid) <= p['side_margin']:
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
    def outline_plan():
        # The apex is the middle of the half-round, the outline's centre on
        # the surface, mirrored over both sides: the tip suggestion of a
        # dependent tip group (pair_tip build 1). The front-most point is not
        # used: on both measured models it sits 2.5-3 cm toward the midline
        # of the middle, where the half-rounds lean in.
        cd,cz = outline['centre']
        apexes = []
        for sign in (1,-1):
            hit = front(float(mid+sign*cd),float(cz))
            if hit is None:
                raise ValueError('outline centre missed surface')
            apexes.append(Vector((mid+sign*cd,hit[0].y,cz)))
        outline['apex'] = [cd,cz]
        reach,fitted = walls(apexes,[outline_reach(outline,cd,cz,directions)]*2)
        return apexes,reach,fitted
    if outline and pinned is None:
        try:
            apexes,reach,fitted = outline_plan()
        except ValueError as e:
            # A wall that does not close falls back to the crest search.
            outline = None
            markers = [(v,note+' ('+str(e)+')') for v,note in markers]
    if outline and 'pinned' not in outline:
        pass
    elif colour or pinned is not None:
        apexes = [v.copy() for v,_ in markers]
    else:
        cell,pick,initial = crest_search()
        apexes = initial
    if colour and extent:
        reach,fitted = walls(apexes,extent['pinned'] if 'pinned' in extent else
                             [outline_reach(extent,sign*(a.x-mid),a.z,directions) for a,sign in zip(apexes,(1,-1))])
    elif not outline:
        reach,fitted = walls(apexes)
    elif 'pinned' in outline:
        reach,fitted = walls(apexes,outline['pinned'])
    if not colour and not outline:
        if pinned is None:
            near = lambda c:all(math.hypot(mid+sign*ds[c[1]]-start.x,zs[c[0]]-start.z)<=p['marker_search_radius'] for sign,start in zip((1,-1),initial))
            # Only the sagittal tilt of the wall moves the tip (a torso leaning back);
            # its lateral tilt follows the rib cage and would drag the tip to the midline.
            sagittal = [Vector((0,n.y,n.z)).normalized() for _,n,_ in fitted]
            apexes = pick(lambda c:sum((cell(*c,sign)-w[0]).dot(s) for sign,w,s in zip((1,-1),fitted,sagittal)) if near(c) else -math.inf)
            reach,fitted = walls(apexes)
        # Without a marked tip (clothing) the tangent search rarely finds a real
        # boundary; a round outline of the median reach avoids angular jumps.
        reach = [statistics.median(v for v in reach if v is not None)]*K
    excluded = set()
    for name in p['exclude_bones']:
        bone = lookup(bones,name)
        excluded.add(bone.name)
        excluded.update(b.name for b in bone.children_recursive)
    exclusion = [sum(ge.weight for ge in mesh.data.vertices[vi].groups if mesh.vertex_groups[ge.group].name in excluded)
                 for mesh,vi in owners]
    links,weights,placements = [],{},[]
    # The measured outline (an ellipse in side coordinates) the region is
    # built on: fresh from the locator, or kept with a pinned placement.
    if outline and 'pinned' not in outline:
        shapes = [outline]*2
    elif colour and extent and 'pinned' not in extent:
        shapes = [extent]*2
    elif pinned is not None:
        shapes = [row.get('outline') for row in pinned]
    else:
        shapes = [None,None]
    for chain,sign,apex,(c,n,points),(_,note),shape in zip(chains,(1,-1),apexes,fitted,markers,shapes):
        depth = (apex-c).dot(n)
        base = sum(points,Vector())/len(points)
        foot = base-n*((base-c).dot(n))
        head = foot-n*p['head_wall_depth']
        link = chain[0]
        lookup(bones,link['parent'])
        links.append((link['bone'],head,apex.copy(),link['parent']))
        w = {}
        sagittal = Vector((0,n.y,n.z)).normalized()
        if shape:
            (cd,cz),(ha,hb) = shape['centre'],shape['half']
            z_lo,z_hi = shape['bottom'],shape['top']
            d_hi = cd+ha
        else:
            z_lo,z_hi = apex.z-(reach[K//2] or p['boundary_s_min']),apex.z+(reach[0] or p['boundary_s_min'])
            d_hi = sign*(apex.x-mid)+(reach[K//4] or p['boundary_s_min'])
        for i,v in enumerate(co):
            rx,rz = (v.x-apex.x)*sign,v.z-apex.z
            d = sign*(v.x-mid)
            # Above the apex the region follows the upper chest back: it leans
            # back about .4-.7 m per metre of height (side profiles of the
            # measured models), so the depth gate moves back with it there;
            # toward the outer side the half-round's own side face curves back
            # the same way (Kira, Rosi), at half the slope, so the flank of
            # the torso 9-10 cm behind stays out; below the apex the underside
            # folds back onto the torso down to the crease (Rosi: 9 cm deep
            # over 2 cm of height), so the gate follows it steeply there, but
            # only inside the outline's outer side: beyond it the torso's
            # flank at that height stays out (Gelina).
            # The gate takes the wall's sagittal tilt only: with its lateral
            # tilt the torso's flank, which faces sideways, counted as in
            # front of the wall once the falloff reached past the outline.
            dist = ((v-c).dot(sagittal)+UPPER_CHEST_SLOPE*max(rz,0.)+OUTER_SIDE_SLOPE*max(rx,0.)
                    +(UNDERSIDE_SLOPE*max(-rz,0.) if d <= d_hi else 0.))
            if d < p['side_margin'] or dist < -p['front_margin']:
                continue
            if shape:
                # Full weight inside the measured outline itself (Ruling A173:
                # an apex near the outline's edge, Rosi's low marker 2 cm above
                # the crease, left the star reach a few millimetres there),
                # then the falloff by the direction's height from its centre.
                ex,ez = (d-cd)/ha,(v.z-cz)/hb
                rho = math.hypot(ex,ez)
                share = p['fade_down']+(p['fade_up']-p['fade_down'])*(1+ez/max(rho,1e-9))/2
                value = smooth((1+share-rho)/share)
                inward = d < cd
            else:
                t = (math.atan2(rx,rz)%(2*math.pi))/(2*math.pi)*K
                k = int(t)%K
                f = t-int(t)
                radius = (reach[k] if reach[k] is not None else p['boundary_s_min'])*(1-f)+(reach[(k+1)%K] if reach[(k+1)%K] is not None else p['boundary_s_min'])*f
                r = math.hypot(rx,rz)
                # Full weight over the whole outline, then a falloff into the
                # torso (Ruling A164): long upward, short downward, in between
                # by the direction's height.
                fade = radius*(p['fade_down']+(p['fade_up']-p['fade_down'])*(1+rz/max(r,1e-9))/2)
                value = smooth((radius+fade-r)/fade)
                inward = rx < 0
            # Toward the midline the half-round is weighted fully up to the
            # cleavage over its whole height (Ruling A173); only a narrow
            # strip at the sternum fades, also where clothing bridges the gap.
            if inward and z_lo <= v.z <= z_hi:
                value = 1.
            value *= smooth((d-p['side_margin'])/MIDLINE_STRIP_M)
            # Never above the band top (the armpit level): on a full pair the
            # upward falloff would otherwise reach the collarbone.
            value *= smooth((hi-v.z)/p['depth_ramp'])
            value *= smooth((dist+p['front_margin'])/p['depth_ramp'])*max(0.,1-exclusion[i]/p['exclude_weight'])
            if value > p['weight_min']:
                w[i] = value
        if not w:
            raise ValueError('empty pair weight region')
        weights[link['bone']] = w
        placements.append({'head':list(head),'tip':list(apex),'apex_source':'colour' if colour else 'outline' if outline else 'geometry',
                           **({'outline':shape} if shape else {}),
                           'marker_area':marker_areas[len(placements)] if colour else None,'marker_note':note,'reach':reach.copy(),'wall_centre':list(c),'wall_normal':list(n),'depth':depth,
                           'anchor_blend':anchor_blend(w,owners,bones)})
    return links,weights,{'placement':placements,'leak':False},set(),[]


# Bones below this share of the tissue a new bone takes over leave its anchor.
ANCHOR_BLEND_MIN_SHARE = .02


def anchor_blend(weights, owners, bones):
    """Which bones the tissue a new bone takes over followed BEFORE, by share.

    Each vertex's original deform weights, normalised, count with the weight the
    new bone takes from it. The renderers anchor the bone at this blend instead
    of its one parent: the rigger spread the tissue over several bones (breast
    tissue 22-63 % Spine1, the rest Spine2), and a bone that followed Spine2
    alone sagged with the upper chest in clips that bend it against Spine1."""
    names = {bone.name for bone in bones.values() if not isinstance(bone, SimpleNamespace)}
    share = {}
    for i,value in weights.items():
        mesh,vi = owners[i]
        groups = [(mesh.vertex_groups[g.group].name,g.weight) for g in mesh.data.vertices[vi].groups
                  if g.weight > 0 and mesh.vertex_groups[g.group].name in names]
        total = sum(weight for _,weight in groups)
        for name,weight in groups:
            share[name] = share.get(name,0.)+value*weight/total
    total = sum(share.values())
    kept = {name:x/total for name,x in share.items() if total and x/total >= ANCHOR_BLEND_MIN_SHARE}
    rest = sum(kept.values())
    return {name:round(x/rest,4) for name,x in sorted(kept.items())} if rest else {}


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


def tip_radius(p, placement):
    """The part's scale R: colour — the marked area's equal-area radius;
    geometry (no marker) — the declared stub radius."""
    return (math.sqrt(sum(row['marker_area'] for row in placement)/(2*math.pi))
            if all(row.get('marker_area') for row in placement) else p['tip_diameter']/2)


def inner_walls(meshes, tips, radius, p, tree):
    """The inner-wall vertices ``(mesh index, vertex index)`` around ``tips``
    of a double-walled body; an empty set for a single-walled one. Inner walls
    of a double-walled body neither define the surface nor move: their points
    sit a few mm below the skin and used to spoil the ring fit (UniForge: RMS
    2-4 mm, fill skipped) and follow the fill and the stub."""
    region = max(p['normal_radius'],p['fill_radius']+p['fill_ring'])*radius
    inner = set()
    for index,mesh in enumerate(meshes):
        normal_matrix = mesh.matrix_world.to_3x3().inverted().transposed()
        for vertex in mesh.data.vertices:
            point = mesh.matrix_world@vertex.co
            if any((point-t).length <= region for t in tips) and _common.enclosed(tree,point,normal_matrix@vertex.normal):
                inner.add((index,vertex.index))
    if len(inner) < DOUBLE_WALL_MIN_VERTICES:
        inner = set()   # a crease or seam, not a wall: single-walled body, unchanged
    return inner


def tip_frame(meshes, tip, p, radius, inner, tree):
    """``(tip, normal, a, b, existing_tip)``: the area-weighted outer surface
    normal within ``normal_radius`` x R of ``tip`` (inner walls left out,
    pointing to the front), a tangent pair, and the tip the mesh carries there."""
    normal = Vector()
    for index,mesh in enumerate(meshes):
        for face in mesh.data.polygons:
            if any((index,i) in inner for i in face.vertices):
                continue
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
    return (tip,normal,a,b,existing_tip(tree,tip,normal,a,b))


def subdivide_around(mesh, centres, radii):
    """One flat subdivision pass per radius (metres, in order): every edge
    whose midpoint lies within that radius of a centre is cut once; new
    vertices take interpolated deform weights, which must sum to one."""
    subdivide_where(mesh,[lambda point,limit=limit: any((point-t).length <= limit for t in centres)
                          for limit in radii])


def subdivide_where(mesh, passes, vectorised=False):
    """One flat subdivision pass per predicate (in order): every edge whose
    world midpoint the predicate accepts is cut once; new vertices take
    interpolated deform weights, which must sum to one (``subdivide_around``
    with a region of any shape — the inset part's levelling). ``vectorised``:
    each predicate takes all midpoints at once (n x 3 array) and returns a
    bool mask."""
    bm = bmesh.new()
    bm.from_mesh(mesh.data)
    original = set(bm.verts)
    for accept in passes:
        if vectorised:
            edges = list(bm.edges)
            matrix = np.array(mesh.matrix_world)
            local = np.array([tuple((e.verts[0].co+e.verts[1].co)/2) for e in edges]).reshape(-1,3)
            mask = accept(local@matrix[:3,:3].T+matrix[:3,3])
            selected = [e for e,keep in zip(edges,mask) if keep]
        else:
            selected = [e for e in bm.edges if accept(mesh.matrix_world@((e.verts[0].co+e.verts[1].co)/2))]
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


def tip_mesh(meshes, p, placement, sources):
    """Prepare the skin for the stubs at ``placement`` (the placed tips) and
    return ``(rows, vertices before)``. The stub REPLACES whatever the mesher
    modelled for the part (Ruling A53): first every side's source bump — at
    ``sources``, where the source group located it (its colour marker or
    crest), before any offset — is levelled onto the surface around it, the
    same fitted-surface levelling a switched-off part gets (``level_sides``).
    Only then are the frames taken and the stub's fill made. Each row carries
    the levelling's numbers (``source_smooth``, the record's shape) and per
    side ``source_level``: the source bump's height above the fitted surface
    before and after (mm), the mesh's own tip height there before and after
    (``existing_tip``, mm) and the placed tip's distance from the source
    apex (mm)."""
    tips = [Vector(row['tip']) for row in placement]
    radius = tip_radius(p,placement)
    before = sum(len(mesh.data.vertices) for mesh in meshes)
    for mesh in meshes:
        subdivide_around(mesh,tips,[level*radius for level in p['subdivide_radii']])
    levelled,smoothing,inner,normals = level_sides(meshes,p,radius,sources,placement)
    tree = world_tree(meshes)
    # A tip placed on its source apex sits where the levelling just lowered
    # the skin by the bump's height. When that leaves no skin within its
    # frame window (normal_radius x R) the tip settles back onto the outer
    # skin along the source's normal (the first hit from in front, as
    # ``existing_tip`` reads it) — Ruling A109: a 12.9 mm bump under a 9 mm
    # window failed the build. Any other tip stays exactly where it is.
    settled = []
    for tip,side,normal in zip(tips,levelled,normals):
        hit = None
        try:
            tip_frame(meshes,tip,p,radius,inner,tree)
        except ValueError:
            hit = tree.ray_cast(tip+normal*.08,-normal,.2)[0]
        side['tip_settled_mm'] = round(float((hit-tip).dot(normal))*1000,3) if hit is not None else 0.
        settled.append(hit.copy() if hit is not None else tip)
    tips = settled
    frames = [tip_frame(meshes,tip,p,radius,inner,tree) for tip in tips]
    rows = []
    for (tip,normal,a,b,existing),side in zip(frames,levelled):
        def coords(point):
            d = point-tip
            u,w,h = d.dot(a),d.dot(b),d.dot(normal)
            return u,w,h,math.hypot(u,w)
        unique = {}
        for index,mesh in enumerate(meshes):
            for vertex in mesh.data.vertices:
                if (index,vertex.index) in inner:
                    continue
                point = mesh.matrix_world@vertex.co
                unique.setdefault(tuple(round(v,8) for v in point),point)
        ring = [coords(point) for point in unique.values()]
        ring = [(u,w,h) for u,w,h,r in ring if p['fill_radius']*radius <= r <= (p['fill_radius']+p['fill_ring'])*radius and h >= -p['fill_depth']]
        coef,rms = None,None
        reason = 'fewer than 12 ring points'
        if inner:
            # Double-walled: the wide fill may move the skin by up to
            # fill_tolerance, through the inner wall a few mm below it.
            reason = 'double-walled body'
        elif len(ring) >= 12:
            design = np.array([[1,u,w,u*u,u*w,w*w] for u,w,_ in ring])
            heights = np.array([h for _,_,h in ring])
            candidate,_,rank,_ = np.linalg.lstsq(design,heights,rcond=None)
            rms = float(np.sqrt(np.mean((design@candidate-heights)**2)))
            reason = 'rank deficient fit' if rank < 6 else 'RMS exceeds fill_rms_max'
            if rank == 6 and rms <= p['fill_rms_max']:
                coef = candidate
        fill_outer,fill_blend,fill = p['fill_radius']*radius,p['fill_blend']*radius,'applied'
        if coef is None and existing['coef'] is not None and existing['rms'] <= p['fill_rms_max']:
            # The wide ring over a coarse or strongly curved breast does not fit,
            # the tip's own 8-15 mm ring does: level just the tip.
            coef,fill_outer,fill_blend,fill = existing['coef'],LOCAL_FILL_RADIUS_M,LOCAL_FILL_BLEND_M,'applied locally ('+reason+')'
        moved,kept = 0,0
        if coef is not None:
            for index,mesh in enumerate(meshes):
                inverse = mesh.matrix_world.inverted()
                for vertex in mesh.data.vertices:
                    if (index,vertex.index) in inner:
                        continue
                    u,w,h,r = coords(mesh.matrix_world@vertex.co)
                    if r >= fill_outer or h < -p['fill_depth']:
                        continue
                    fitted = float(np.dot(coef,[1,u,w,u*u,u*w,w*w]))
                    if abs(h-fitted) > p['fill_tolerance']:
                        kept += 1
                        continue
                    factor = smooth((fill_outer-r)/fill_blend)
                    vertex.co = inverse@(tip+a*u+b*w+normal*(h*(1-factor)+fitted*factor))
                    moved += 1
                mesh.data.update()
        filled = tip+normal*float(coef[0]) if coef is not None else tip.copy()
        axis = (normal-a*float(coef[1])-b*float(coef[2])).normalized() if coef is not None else normal
        rows.append({'tip':list(filled),'axis':list(axis),'radius':radius,'fill':fill if coef is not None else 'skipped: '+reason,
                     'fill_rms':rms,'fill_moved':moved,'fill_kept_by_tolerance':kept,
                     'tip_source':'stub','tip_length_m':p['tip_length'],'tip_radius_m':p['tip_diameter']/2,
                     'existing_tip_m':existing['protrusion'],'inner_wall_vertices':len(inner),
                     'source_smooth':smoothing,'source_level':side})
    stubs = [Vector(row['tip']) for row in rows]
    if p['tip_subdivide'] > 0 and stubs:
        for mesh in meshes:
            subdivide_around(mesh,stubs,[p['tip_subdivide']])
    return rows, before


# The levelled surface where a tip part sits or would sit (Ruling A44 for a
# part that is switched off, the op's ``when_off: neutralise``; Ruling A53 for
# one that is on: the stub replaces the mesher's own). The mesher models the
# part where the colour marker is (a raised disc, a tip, a crater, often as a
# second sheet over the skin), so the region to level is the marker's: full
# strength out to max(NEUTRAL_SCALE x R, NEUTRAL_MIN_M, the stub's footprint +
# LEVEL_MARGIN_M) (R = the part's scale, ``tip_radius``; ``level_full``),
# fading over NEUTRAL_BLEND x that; the surface it is levelled to is a quadratic
# fitted to the outer skin on the ring NEUTRAL_FIT beyond the fade (in
# multiples of the full radius) — so the curve the part sits on stays. Measured
# on a body whose mesher drew a raised disc with a crater (Ylva, edges ~6 mm):
# Laplacian smoothing over a fixed rim left a funnel and pushed the sheet under
# the disc through the skin; levelling does neither. A narrower fade (0.3) or a
# fit ring nearer the disc (1.3-1.8) left a visible step at the rim, where the
# disc's skirt meets the fitted surface. The region is flat-subdivided first
# (NEUTRAL_SUBDIVIDE, x the full radius) so the fade has vertices to bend on. A
# vertex under another sheet (an inner wall, ``inner_walls``) is never raised
# and ends NEUTRAL_GAP_M below the levelled skin, so nothing pokes through.
# Vertices further than NEUTRAL_DEPTH_M from the fitted surface are other parts
# of the body. Only the mesh changes: the texture stays as it is (Ruling A53).
NEUTRAL_SCALE = 1.2
NEUTRAL_MIN_M = .012
NEUTRAL_BLEND = .8
NEUTRAL_FIT = (1.8, 2.5)
NEUTRAL_SUBDIVIDE = (1.9, 1.5)
NEUTRAL_GAP_M = .001
NEUTRAL_DEPTH_M = (.015, .03)
# Metres beyond the stub's own footprint (its radius plus its wall) that the
# levelling always reaches at full strength.
LEVEL_MARGIN_M = .003


def _quadratic(u, w):
    return np.stack([np.ones_like(u),u,w,u*u,u*w,w*w],1)


def level_surface(meshes, tip, normal, full, inner):
    """Level the skin around ``tip`` onto the surface around it (module
    notes above): ``h' = Q + (1 - k) (h - Q)`` along ``normal`` with ``Q``
    the quadratic fitted on the ring, ``k`` = 1 within ``full`` metres and
    fading to 0 over the blend; an ``inner`` vertex only goes down and keeps
    ``NEUTRAL_GAP_M`` x k below (``level_heights``). Returns
    ``{bump_before_mm, bump_after_mm, moved, max_shift_mm, fit_rms_mm,
    full_radius_mm, blend_mm}`` (bump = the highest outer-skin point within
    ``full`` above the fitted surface)."""
    a = normal.orthogonal().normalized()
    b = normal.cross(a)
    rows = []
    for index,mesh in enumerate(meshes):
        for vertex in mesh.data.vertices:
            d = mesh.matrix_world@vertex.co-tip
            u,w,h = d.dot(a),d.dot(b),d.dot(normal)
            if math.hypot(u,w) <= NEUTRAL_FIT[1]*full and -.05 < h < .05:
                rows.append((index,vertex.index,u,w,h,(index,vertex.index) in inner))
    if not rows:
        raise ValueError('no surface around the part to level')
    R = np.array([row[2:5] for row in rows])
    inside = np.array([row[5] for row in rows])
    r = np.hypot(R[:,0],R[:,1])

    def quadratic(ring):
        coef = np.linalg.lstsq(_quadratic(R[ring,0],R[ring,1]),R[ring,2],rcond=None)[0]
        return _quadratic(R[:,0],R[:,1])@coef
    shift,level = level_heights(R[:,2],r-full,inside,full,quadratic)
    moved = 0
    for row,dh in zip(rows,shift):
        if abs(dh) > 1e-9:
            mesh = meshes[row[0]]
            vertex = mesh.data.vertices[row[1]]
            vertex.co = mesh.matrix_world.inverted()@(mesh.matrix_world@vertex.co+normal*float(dh))
            moved += 1
    for mesh in meshes:
        mesh.data.update()
    return {'bump_before_mm':level['bump_before_mm'],'bump_after_mm':level['bump_after_mm'],'moved':moved,
            'max_shift_mm':level['max_shift_mm'],'fit_rms_mm':level['fit_rms_mm'],
            'full_radius_mm':round(full*1000,2),'blend_mm':round(NEUTRAL_BLEND*full*1000,2)}


def level_heights(h, outside, inner, full, fit, depth=NEUTRAL_DEPTH_M, inner_follows=False, ring=None):
    """The levelling itself, for a region of any shape (``level_surface``
    around a tip, ``inset_part`` along its chart): per row its height ``h``
    along the direction it moves in (metres), ``outside`` its distance beyond
    the full-strength region (0 or less within it) and ``inner`` whether it
    is an inner-wall vertex; ``full`` the region's scale (the fade is
    NEUTRAL_BLEND x it, the fit ring NEUTRAL_FIT - 1 x it beyond the region
    on the outer skin within ``depth[1]`` of the height 0); ``fit(ring)``
    returns the fitted surface Q at every row from the ring rows (bool mask;
    ``ring`` replaces it where the surface is fitted on other rows — the inset
    part's fit over its region — and is what ``fit_rms_mm`` measures).
    ``inner_follows``: an inner row follows the levelled skin both ways
    instead of only going down. Returns ``(shift per row, {bump_before_mm, bump_after_mm, bump_p95_mm:
    [before, after], max_shift_mm, fit_rms_mm})`` — a row that is further
    than ``depth`` (below, above) from Q is another part of the body and
    stays; bump = the outer skin within the region above Q."""
    blend = NEUTRAL_BLEND*full
    if ring is None:
        ring = ~inner&(outside >= (NEUTRAL_FIT[0]-1)*full)&(np.abs(h) < depth[1])
    if ring.sum() < 12:
        raise ValueError('no surface around the part to level')
    Q = fit(ring)
    off = h-Q
    near = (off > -depth[0])&(off < depth[1])
    k = np.where(near,np.clip((blend-outside)/blend,0.,1.),0.)
    k = k*k*(3-2*k)
    target = Q+(1-k)*off
    target = np.where(inner,(target if inner_follows else np.minimum(h,target))-NEUTRAL_GAP_M*k,target)
    shift = target-h
    within = ~inner&near&(outside <= 0)
    bump = lambda values: round(float(values[within].max())*1000,3) if within.any() else 0.
    p95 = lambda values: round(float(np.percentile(values[within],95))*1000,3) if within.any() else 0.
    return shift,{'bump_before_mm':bump(off),'bump_after_mm':bump(target-Q),
                  'bump_p95_mm':[p95(off),p95(target-Q)],
                  'max_shift_mm':round(float(np.abs(shift).max())*1000,3),
                  'fit_rms_mm':round(float(np.sqrt(np.mean((h[ring]-Q[ring])**2)))*1000,3)}


def level_full(p, radius):
    """The full-strength radius of the levelling (metres; module notes above)."""
    return max(NEUTRAL_SCALE*radius,NEUTRAL_MIN_M,p['tip_diameter']/2+p['tip_wall']+LEVEL_MARGIN_M)


def level_sides(meshes, p, radius, sources, placed=None):
    """Level each side's source bump onto the surface around it
    (``level_surface``) at ``sources`` — the apex the source group located
    (its colour marker or crest), before any offset: where the mesher modelled
    the part. ``placed``: the tips of a part that is on, after their offset;
    their own region is never levelled — no source bump sits there, and a
    quadratic fitted around a tip moved onto the curve's flank flattens the
    curve (measured on Ylva, 30 mm down and in: a 15-27 mm deep dish). Each
    source region is flat-subdivided first, as far as the stub's subdivision
    (``tip_mesh``, around the placed tips) has not done so. Returns ``(sides,
    smoothing, inner)``: per side ``{bump_mm: [before, after], height_mm:
    [before, after], tip_from_source_mm, level}`` — the bump's highest point
    above the fitted surface, the mesh's own tip above its surroundings
    (``existing_tip``) at the source, the placed tip's distance from the
    source apex (None without ``placed``), the levelling's numbers — then the
    numbers of the side that moved most in the record's shape, and the
    inner-wall vertices. A source with no surface around it raises ValueError
    for a part that is off; for one that is on, the side records ``error``
    and the stub is built on the skin as it is."""
    origins = [Vector(row['tip']) for row in sources]
    targets = [Vector(row['tip']) for row in placed] if placed else [None]*len(origins)
    full = level_full(p,radius)
    # A source the stub's subdivision already reached takes only the passes
    # it still lacks, so the region is never cut finer than either would cut
    # it alone.
    for o in origins:
        done = sum(1 for level in p['subdivide_radii']
                   if placed and any((o-t).length <= level*radius for t in targets))
        passes = [level*full for level in NEUTRAL_SUBDIVIDE][done:]
        if passes:
            for mesh in meshes:
                subdivide_around(mesh,[o],passes)
    tree = world_tree(meshes)
    inner = inner_walls(meshes,origins+[t for t in targets if t is not None],radius,p,tree)
    frames = [tip_frame(meshes,o,p,radius,inner,tree) for o in origins]
    levels,errors = [],[]
    for o,(_,normal,_,_,_) in zip(origins,frames):
        try:
            levels.append(level_surface(meshes,o,normal,full,inner))
            errors.append('')
        except ValueError as e:
            # A part that is on is still built on the unlevelled skin; one that
            # is off has nothing else to do and fails.
            if not placed:
                raise
            levels.append(None)
            errors.append(str(e))
    tree = world_tree(meshes)
    sides = []
    for o,t,(_,normal,a,b,existing),level,error in zip(origins,targets,frames,levels,errors):
        # Measured in the frame taken before the levelling: the levelling
        # lowers the skin under the source apex by the bump's height, so a
        # fresh frame around ``o`` can find no skin within its window
        # (normal_radius x R) at all — a 13 mm bump under a 9 mm window
        # failed the whole build (Ruling A109). The rays come from in front
        # along the same normal, so before and after compare like for like.
        after = existing_tip(tree,o,normal,a,b)
        sides.append({'bump_mm':[level['bump_before_mm'],level['bump_after_mm']] if level else None,
                      'height_mm':[round(existing['protrusion']*1000,3),round(after['protrusion']*1000,3)],
                      'tip_from_source_mm':round((t-o).length*1000,2) if t is not None else None,
                      'level':level,**({'error':error} if error else {})})
    done = [level for level in levels if level]
    top = max(done,key=lambda level:level['max_shift_mm']) if done else None
    smoothing = {'radius_m':full,'blend_m':NEUTRAL_BLEND*full,'iterations':None,
                 'moved':sum(level['moved'] for level in done),'max_shift_mm':top['max_shift_mm'] if top else 0.,
                 'inner_wall_vertices':len(inner)}
    if any(errors):
        smoothing['error'] = next(error for error in errors if error)
    return sides,smoothing,inner,[frame[1] for frame in frames]


def neutralise_mesh(meshes, p, sources):
    """The neutral surface where a switched-off tip part would sit (Ruling
    A44): each side's source bump at ``sources`` (the source group's apex) is
    levelled onto the surface around it (``level_sides``); no stub, no bone,
    and the texture stays as it is (Ruling A53). Returns one row per side —
    ``{tip, axis, radius, tip_source: neutral, height_before_mm,
    height_after_mm, bump_mm, level}`` — and the numbers of the side that
    moved most, in the shape of the stub's ``source_smooth``."""
    radius = tip_radius(p,sources)
    sides,smoothing,inner,normals = level_sides(meshes,p,radius,sources)
    rows = []
    for row,side,normal in zip(sources,sides,normals):
        # The surface normal at the source before the levelling: the levelled
        # skin may lie below the window around the apex (Ruling A109).
        tip = Vector(row['tip'])
        rows.append({'tip':list(tip),'axis':list(normal),'radius':radius,'tip_source':'neutral',
                     'height_before_mm':side['height_mm'][0],'height_after_mm':side['height_mm'][1],
                     'bump_mm':side['bump_mm'],'level':side['level']})
    return rows,smoothing


def position_snapshot(meshes):
    """Every vertex position of ``meshes`` before the tip ops (``refresh_normals``)."""
    return [{tuple(round(c,7) for c in v.co) for v in mesh.data.vertices} for mesh in meshes]


def refresh_normals(meshes, snapshot):
    """Give the vertices the tip ops moved or created — and their one ring,
    whose faces changed with them — the surface's own smooth normal (Ruling
    A34). An imported GLB carries its normals as custom normals: a vertex the
    fill, the smoothing or the stub moved kept the normal of where it was, and
    a vertex the subdivision made got one interpolated between neighbours —
    across a fold of the source, a normal pointing into the body, which shades
    as a black hole in the skin. Copies at one position share the normal.
    Every other vertex keeps its custom normal. Returns the count refreshed."""
    refreshed = 0
    for index,mesh in enumerate(meshes):
        data = mesh.data
        if not data.has_custom_normals:
            continue
        changed = {v.index for v in data.vertices if tuple(round(c,7) for c in v.co) not in snapshot[index]}
        if not changed:
            continue
        ring = set(changed)
        for poly in data.polygons:
            if any(i in changed for i in poly.vertices):
                ring.update(poly.vertices)
        key = lambda v: tuple(round(c/COINCIDENT_EPSILON_M) for c in v.co)
        wanted = {key(data.vertices[i]) for i in ring}
        sums = {}
        for v in data.vertices:
            k = key(v)
            if k in wanted:
                sums[k] = sums.get(k,Vector())+v.normal
        corner = [Vector(c.vector) for c in data.corner_normals]
        for loop in data.loops:
            if loop.vertex_index in ring:
                n = sums[key(data.vertices[loop.vertex_index])]
                if n.length > 1e-8:
                    corner[loop.index] = n.normalized()
        data.normals_split_custom_set([tuple(n) for n in corner])
        data.update()
        refreshed += len(ring)
    return refreshed


# Metres: the region around each tip whose normals the tip smoothing record
# counts (Ruling A43; the radius the A34 diagnosis measured in).
TIP_NORMAL_REGION_M = .04
# A normal more than this far off its surface counts as "off" (cos 60 deg).
TIP_NORMAL_OFF_COS = .5


def normal_census(meshes, centres):
    """How the shading normals near ``centres`` (world points) stand to the
    surface (Ruling A43): ``{vertices, inverted, off_60}`` — the vertices
    within ``TIP_NORMAL_REGION_M`` of a centre, those of them with a corner
    normal pointing against the surface's own smooth normal (into the body:
    a dark hole in the skin) and those more than 60 deg off it. The surface
    normal of a vertex sums ``vertex.normal`` over its coincident copies, as
    ``refresh_normals`` does."""
    vertices = inverted = off = 0
    for mesh in meshes:
        data = mesh.data
        world = mesh.matrix_world
        near = {v.index for v in data.vertices if any(((world@v.co)-c).length <= TIP_NORMAL_REGION_M for c in centres)}
        if not near:
            continue
        key = lambda v: tuple(round(c/COINCIDENT_EPSILON_M) for c in v.co)
        keys = {i:key(data.vertices[i]) for i in near}
        wanted = set(keys.values())
        sums = {}
        for v in data.vertices:
            k = key(v)
            if k in wanted:
                sums[k] = sums.get(k,Vector())+v.normal
        corners = data.corner_normals
        worst = {}
        for loop in data.loops:
            i = loop.vertex_index
            if i not in near:
                continue
            surface = sums[keys[i]]
            if surface.length < 1e-12:
                continue
            d = Vector(corners[loop.index].vector).dot(surface.normalized())
            worst[i] = min(worst.get(i,1.),d)
        vertices += len(near)
        inverted += sum(d < 0 for d in worst.values())
        off += sum(d < TIP_NORMAL_OFF_COS for d in worst.values())
    return {'vertices':vertices,'inverted':inverted,'off_60':off}


# Metres per step of the tip offset walk along the surface.
TIP_WALK_STEP_M = .0005
# Millimetres: the tip offset range per direction (the server clamps the
# stored override to the same range).
TIP_OFFSET_MAX_MM = 50.
# Millimetres: the colour disc diameter range and its soft edge width range.
DISC_DIAMETER_MM = (10., 50.)
DISC_SOFT_MAX_MM = 10.
# Texels painted beyond a triangle's UV edge (the island gutter).
DISC_GUTTER_TEXELS = 1.5


def _finite(value, default=0.):
    return float(value) if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) else default


def tip_offsets(override):
    """``[(up, out), (up, out)]`` in metres, one per chain (side +1 first),
    each value clamped to +-TIP_OFFSET_MAX_MM; absent values are zero."""
    rows = (override or {}).get('offsets') or []
    offsets = []
    for i in range(2):
        row = rows[i] if i < len(rows) and isinstance(rows[i],dict) else {}
        offsets.append(tuple(max(-TIP_OFFSET_MAX_MM,min(TIP_OFFSET_MAX_MM,_finite(row.get(key))))/1000
                             for key in ('up','out')))
    return offsets


def surface_frame(normal, side):
    """The two tangent directions at a surface point of normal ``normal``:
    up (world +Z) and out (away from the midline, ``side`` * X), each
    projected into the tangent plane and normalised."""
    up,out = Vector((0,0,1)),Vector((side,0,0))
    return (up-normal*normal.dot(up)).normalized(),(out-normal*normal.dot(out)).normalized()


def surface_nearest(meshes):
    """``nearest(point) -> (surface point, front normal)`` over all meshes."""
    tree = world_tree(meshes)
    def nearest(point):
        location,normal,_,_ = tree.find_nearest(point)
        if location is None:
            raise ValueError('tip offset found no surface')
        normal = normal.normalized()
        return location,(-normal if normal.y > 0 else normal)
    return nearest


def surface_walk(nearest, start, side, up, out, step=TIP_WALK_STEP_M):
    """Move ``start`` ``up``/``out`` metres along the surface: equal steps of
    at most ``step`` in the direction up*e_up + out*e_out of the local
    tangent frame (``surface_frame``), each projected back onto the mesh
    (``nearest``). The path length is hypot(up, out); on a plane the result is
    start + up*Z + out*side*X exactly. Returns (point, normal)."""
    point,normal = nearest(start)
    length = math.hypot(up,out)
    if length < 1e-9:
        return point,normal
    count = max(1,math.ceil(length/step))
    for _ in range(count):
        e_up,e_out = surface_frame(normal,side)
        direction = e_up*up+e_out*out
        direction -= normal*normal.dot(direction)
        point,normal = nearest(point+direction.normalized()*(length/count))
    return point,normal


def tip_positions(meshes, source_rows, override):
    """The tip rows ``tip_mesh`` builds on, and what the metrics record.

    The suggestion is each source side's apex: its colour marker, or without
    one its geometry crest (``tip_source``). A side with an offset moves its
    tip along the surface (``surface_walk``); a side without one keeps the
    source row as it is. Per side the metrics get the suggestion, its front
    normal, the tangent frame there, the applied offset in mm and the placed
    position (before the fill)."""
    offsets = tip_offsets(override)
    nearest = surface_nearest(meshes)
    rows,sides = [],[]
    for row,(up,out),side in zip(source_rows,offsets,(1,-1)):
        suggested = Vector(row['tip'])
        normal = nearest(suggested)[1]
        placed = dict(row)
        if up or out:
            placed['tip'] = list(surface_walk(nearest,suggested,side,up,out)[0])
        rows.append(placed)
        e_up,e_out = surface_frame(normal,side)
        sides.append({'suggested':list(suggested),'suggested_normal':list(normal),
                      'tangent_up':list(e_up),'tangent_out':list(e_out),
                      'offset_mm':[round(up*1000,3),round(out*1000,3)],'placed':list(placed['tip'])})
    colour = all(row['apex_source']=='colour' for row in source_rows)
    return rows,{'tip_source':'colour' if colour else 'geometry','sides':sides}


def base_colour_image(material):
    """The image node feeding a material's Principled base colour, or None."""
    if material and material.use_nodes:
        for node in material.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED' and node.inputs['Base Color'].links:
                source = node.inputs['Base Color'].links[0].from_node
                if source.type == 'TEX_IMAGE' and source.image:
                    return source.image
    return None


def disc_alpha(r, radius, soft):
    """Disc coverage at distance ``r`` from the tip axis: 1 inside, 0 outside;
    a soft edge of width ``soft`` is centred on the rim (0.5 at r = radius)."""
    if soft <= 0:
        return np.where(r <= radius,1.,0.)
    x = np.clip((radius+soft/2-r)/soft,0.,1.)
    return x*x*(3-2*x)


def disc_mask(meshes, rows, disc):
    """Texels of the base-colour image a colour disc around each tip covers.

    The disc lies in the plane across each tip's axis: a texel counts by the
    distance of its surface point from the axis (so the raised stub keeps the
    colour of the skin it was raised from). Triangles are rasterised in UV
    space (texel centres, image rows top-down as stored in the file); only
    triangles within 3 cm along the axis and not facing away from it count, so
    the far side of the body and an inner wall stay untouched. A texel up to
    DISC_GUTTER_TEXELS outside a triangle's UV edge counts too (extrapolated)
    unless another triangle owns it, so texture filtering at an island border
    never blends the unpainted gutter in. Overlapping texels keep the larger
    coverage. Returns ``{size: [w, h], image, texels: [x, y, alpha 1..255,
    ...], pixels}``; ValueError when the region has no single base-colour
    image."""
    radius = max(DISC_DIAMETER_MM[0],min(DISC_DIAMETER_MM[1],_finite(disc.get('diameter_mm'),28.)))/2000
    soft = max(0.,min(DISC_SOFT_MAX_MM,_finite(disc.get('soft_mm'))))/1000
    return disc_texels(meshes,rows,radius,soft)


def disc_texels(meshes, rows, radius, soft, with_at=False):
    """``disc_mask`` for a disc of ``radius`` metres with a soft edge of
    ``soft`` metres, unclamped (the neutral paint of Ruling A44 sizes its disc
    and its sample ring from the part's footprint). ``with_at``: also ``at``,
    per texel where it lies on the surface — ``[u, w, ...]`` in mm in the tip's
    tangent frame — so colours can be carried across UV seams."""
    reach = radius+soft/2
    pad = DISC_GUTTER_TEXELS
    surfaces = []
    for mesh in meshes:
        data = mesh.data
        uv = data.uv_layers.active
        if uv is None:
            continue
        data.calc_loop_triangles()
        local = np.empty(len(data.vertices)*3,np.float64)
        data.vertices.foreach_get('co',local)
        matrix = np.array(mesh.matrix_world)
        world = local.reshape(-1,3)@matrix[:3,:3].T+matrix[:3,3]
        count = len(data.loop_triangles)
        tris,loops,materials = np.empty(count*3,np.int64),np.empty(count*3,np.int64),np.empty(count,np.int64)
        data.loop_triangles.foreach_get('vertices',tris)
        data.loop_triangles.foreach_get('loops',loops)
        data.loop_triangles.foreach_get('material_index',materials)
        uvs = np.empty(len(data.loops)*2,np.float64)
        uv.data.foreach_get('uv',uvs)
        surfaces.append((data,world,tris.reshape(-1,3),loops.reshape(-1,3),materials,uvs.reshape(-1,2)))
    covered,image,owners,at = {},None,[],{}
    def owned(x, y):
        """Whether a texel centre lies inside any triangle's UV footprint."""
        if not owners:
            verts,polys = [],[]
            for _,_,_,loops,_,uvs in surfaces:
                corners = uvs[loops.reshape(-1)]
                offset = len(verts)
                verts.extend(Vector((u*width,(1-v)*height,0.)) for u,v in corners.tolist())
                polys.extend((offset+3*i,offset+3*i+1,offset+3*i+2) for i in range(len(loops)))
            owners.append(BVHTree.FromPolygons(verts,polys,all_triangles=True))
        hit = owners[0].find_nearest(Vector((x,y,0.)))
        return hit[0] is not None and hit[3] < 1e-6
    for data,world,tris,loops,materials,uvs in surfaces:
        for row in rows:
            tip,axis = np.array(row['tip']),Vector(row['axis']).normalized()
            b1 = axis.orthogonal().normalized()
            b2 = axis.cross(b1)
            delta = world-tip
            axial = delta@np.array(axis)
            u,w = delta@np.array(b1),delta@np.array(b2)
            tu,tw,ta = u[tris],w[tris],axial[tris]
            p = world[tris]
            cross = np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0])
            near = ((tu.min(1) <= reach)&(tu.max(1) >= -reach)&(tw.min(1) <= reach)&(tw.max(1) >= -reach)
                    &(np.abs(ta).max(1) < .03)&(cross@np.array(axis) > -.25*np.linalg.norm(cross,axis=1)))
            for t in np.nonzero(near)[0]:
                index = int(materials[t])
                found = base_colour_image(data.materials[index] if index < len(data.materials) else None)
                if found is None:
                    continue
                if image is None:
                    image = found
                elif found != image:
                    raise ValueError('disc region has several base-colour images')
                width,height = image.size
                if not width or not height:
                    raise ValueError('base-colour image has no pixels')
                corners = uvs[loops[t]]
                px,py = corners[:,0]*width,(1-corners[:,1])*height
                x0,x1 = int(math.floor(px.min()-pad)),int(math.ceil(px.max()+pad))
                y0,y1 = int(math.floor(py.min()-pad)),int(math.ceil(py.max()+pad))
                gx,gy = np.meshgrid(np.arange(x0,x1+1)+.5,np.arange(y0,y1+1)+.5)
                d1x,d1y,d2x,d2y = px[1]-px[0],py[1]-py[0],px[2]-px[0],py[2]-py[0]
                det = d1x*d2y-d1y*d2x
                if abs(det) < 1e-12:
                    continue
                qx,qy = gx-px[0],gy-py[0]
                s1 = (qx*d2y-qy*d2x)/det
                s2 = (d1x*qy-d1y*qx)/det
                # Barycentric l_i = distance to the opposite edge / altitude,
                # the altitude being |det| / that edge's length.
                edges = (math.hypot(px[2]-px[1],py[2]-py[1]),math.hypot(d2x,d2y),math.hypot(d1x,d1y))
                slack = [pad*e/abs(det) for e in edges]
                inside = (s1 >= -slack[1])&(s2 >= -slack[2])&(1-s1-s2 >= -slack[0])
                strict = (s1 >= -1e-9)&(s2 >= -1e-9)&(1-s1-s2 >= -1e-9)
                if not inside.any():
                    continue
                ru = tu[t,0]+s1*(tu[t,1]-tu[t,0])+s2*(tu[t,2]-tu[t,0])
                rw = tw[t,0]+s1*(tw[t,1]-tw[t,0])+s2*(tw[t,2]-tw[t,0])
                alpha = np.rint(disc_alpha(np.hypot(ru,rw),radius,soft)*255).astype(int)
                for cx,cy,a,own,su,sw in zip(gx[inside].tolist(),gy[inside].tolist(),alpha[inside].tolist(),strict[inside].tolist(),
                                             ru[inside].tolist(),rw[inside].tolist()):
                    if a <= 0 or (not own and owned(cx,cy)):
                        continue
                    key = (int(math.floor(cx))%width,int(math.floor(cy))%height)
                    if a > covered.get(key,0):
                        covered[key] = a
                        at[key] = (round(su*1000,3),round(sw*1000,3))
    if image is None:
        raise ValueError('no base-colour texture around the tips')
    texels,where = [],[]
    for (x,y),a in sorted(covered.items()):
        texels.extend((x,y,a))
        where.extend(at[(x,y)])
    return {'size':list(image.size),'image':image.name,'texels':texels,'pixels':len(covered),
            **({'at':where} if with_at else {})}


def world_tree(meshes):
    """One BVH over all meshes in world space."""
    verts,polys = [],[]
    for mesh in meshes:
        offset = len(verts)
        verts.extend(mesh.matrix_world@v.co for v in mesh.data.vertices)
        polys.extend([offset+i for i in face.vertices] for face in mesh.data.polygons)
    return BVHTree.FromPolygons(verts,polys)


def existing_tip(tree, tip, normal, a, b):
    """Height of a tip the mesh already carries, from the OUTER skin.

    A depth map by rays from in front (the first hit is the outer skin, never an
    inner wall) on a 0.5 mm grid; the surrounding surface is a quadratic fit to
    the ring 8-15 mm out, the tip is the highest residual within 7 mm.
    Returns protrusion (m), apex (world) and the equal-area radius of the part
    above half the protrusion."""
    grid = np.arange(-.015,.0151,.0005)
    samples = []
    for u in grid:
        for w in grid:
            hit = tree.ray_cast(tip+a*float(u)+b*float(w)+normal*.08,-normal,.2)
            if hit[0] is not None:
                samples.append((float(u),float(w),(hit[0]-tip).dot(normal)))
    if len(samples) < 50:
        return {'protrusion':0.,'apex':list(tip),'radius':0.,'coef':None,'rms':None}
    S = np.array(samples)
    r = np.hypot(S[:,0],S[:,1])
    design = lambda rows:np.stack([np.ones(len(rows)),rows[:,0],rows[:,1],rows[:,0]**2,rows[:,0]*rows[:,1],rows[:,1]**2],1)
    ring = (r > .008)&(r < .015)
    inner = r < .007
    if ring.sum() < 12 or not inner.any():
        return {'protrusion':0.,'apex':list(tip),'radius':0.,'coef':None,'rms':None}
    coef = np.linalg.lstsq(design(S[ring]),S[ring,2],rcond=None)[0]
    residual = S[:,2]-design(S)@coef
    k = int(np.argmax(np.where(inner,residual,-np.inf)))
    protrusion = float(residual[k])
    raised = (r < .009)&(residual > protrusion/2)
    u,w,h = S[k]
    return {'protrusion':max(protrusion,0.),'apex':list(tip+a*u+b*w+normal*h),
            'radius':math.sqrt(raised.sum()*.0005**2/math.pi),
            'coef':coef,'rms':float(np.sqrt(np.mean(residual[ring]**2)))}


def tip_height(r, p):
    rc = p['tip_diameter']/2
    cap = min(p['tip_round']*rc,p['tip_length'])
    lw = p['tip_length']-cap
    return lw+cap*math.sqrt(max(0.,1-(r/rc)**2)) if r <= rc else lw*smooth((rc+p['tip_wall']-r)/p['tip_wall'])


def tip_plan(group, p, co, source, rows, before, meshes):
    wall,band = p['tip_wall'],p['tip_band']
    # The inner-wall test needs the meshes behind ``co``; without them there is
    # no wall to tell apart.
    tree = world_tree(meshes) if meshes else None
    normals = mesh_arrays(meshes)[3] if meshes else []
    for row in rows:
        row.setdefault('tip_source','stub')
        row.setdefault('tip_length_m',p['tip_length'])
        row.setdefault('tip_radius_m',p['tip_diameter']/2)
        rc = row['tip_radius_m']
        minimum = min(1-3*x*x+2*x*x*x-6*((rc+wall)/band+x)*x*(1-x) for x in np.linspace(0.,1.,10001))
        row['girth_fold_free_max'] = float(1+1/-minimum) if minimum < 0 else None
        tip,axis = Vector(row['tip']),Vector(row['axis'])
        walled = tree is not None and row.get('inner_wall_vertices',0) > 0
        heights = []
        for i,point in enumerate(co):
            delta = point-tip
            axial = delta.dot(axis)
            if axial < -p['weight_depth']:
                continue
            r = (delta-axis*axial).length
            height = tip_height(r,p)
            # An inner wall under the tip stays where it is (double-walled body).
            if height > 0 and not (walled and _common.enclosed(tree,point,normals[i])):
                co[i] = point+axis*height
                heights.append(axial+height)
        row['stub_height'] = max(heights,default=0.)
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
        rc = row['tip_radius_m']
        head,tail = tip,tip+axis*row['tip_length_m']
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
                length = row.get('tip_length_m',p['tip_length'])
                nearest = min(range(len(rest)),key=lambda i:(rest[i]-(tip+axis*length)).length_squared)
                rc = row.get('tip_radius_m',p['tip_diameter']/2)
                lw = p['tip_length']-min(p['tip_round']*rc,p['tip_length'])
                ring = []
                for i,point in enumerate(rest):
                    delta = point-tip
                    axial = delta.dot(axis)
                    r = (delta-axis*axial).length
                    side = axial >= -p['weight_depth'] and tip_height(r,p) > lw/2
                    if abs(r-rc) < p['tip_wall']/2 and side:
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
    _common.progress('bones', 0, len(enabled))
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
    soft,prepared,tip_info = {},{},{}
    snapshot = None   # vertex positions before the first tip op (refresh_normals)
    census = {}       # group -> (tip centres, normal census before its tip op) — Ruling A43
    # Switched-off tip parts that leave a neutral surface (Ruling A44): never
    # bones, only the levelling of where they would sit — the mesh only, the
    # texture stays as it is (Ruling A53).
    neutral_groups = [g for g in args['params'].get('neutralise') or [] if g.get('op')=='pair_tip']
    neutral = {}      # group -> (rows, smoothing)
    # A colour placement always pins the re-plan; a geometry placement only
    # when a tip group stands on it (its crest apex is the tip suggestion).
    tip_sources = {g.get('depends_on') for g in enabled+neutral_groups if g['op']=='pair_tip'}
    pinned = {g['id']:plan[2]['placement'] for g,p,plan in plans
              if g['op']=='pair_protrusion' and (all(row['apex_source']=='colour' for row in plan[2]['placement'])
                                                 or g['id'] in tip_sources)}
    try:
        for g in enabled:
            if dependencies[g['id']].intersection(soft):
                soft[g['id']] = {'status':'not_found','reason':'Source group was not found'}
                continue
            if g['op']!='pair_tip':
                continue
            if g['depends_on'] not in pinned:
                soft[g['id']] = {'status':'not_found','reason':'Source placement is missing'}
                continue
            p = parameters(g)
            # A tip that cannot be built fails alone (Ruling A109): the mesh
            # goes back to how it was before this group touched it, and the
            # source pair group is still built.
            saved = [mesh.data.copy() for mesh in meshes]
            fresh = snapshot is None
            try:
                rows,tip_info[g['id']] = tip_positions(meshes,pinned[g['depends_on']],g.get('tip_override'))
                if fresh:
                    snapshot = position_snapshot(meshes)
                centres = [Vector(row['tip']) for row in rows]
                census[g['id']] = (centres,normal_census(meshes,centres))
                prepared[g['id']] = tip_mesh(meshes,p,rows,pinned[g['depends_on']])
            except (ValueError,KeyError,TypeError,IndexError) as e:
                for mesh,data in zip(meshes,saved):
                    changed = mesh.data
                    mesh.data = data
                    bpy.data.meshes.remove(changed)
                for store in (tip_info,census,prepared):
                    store.pop(g['id'],None)
                if fresh:
                    snapshot = None
                soft[g['id']] = {'status':'failed','reason':str(e)}
                continue
            for data in saved:
                bpy.data.meshes.remove(data)
        for g in neutral_groups:
            # Where the part would sit: the same placement it uses when on.
            if g.get('depends_on') not in pinned or g.get('depends_on') in soft:
                soft[g['id']] = {'status':'not_found','mode':'neutralised',
                                 'reason':'Nothing located where the part would sit — nothing changed'}
                continue
            # The source bump is levelled where the source group found it — an
            # offset moves only a part that is on (Ruling A53).
            p = parameters(g)
            sources = pinned[g['depends_on']]
            if snapshot is None:
                snapshot = position_snapshot(meshes)
            centres = [Vector(row['tip']) for row in sources]
            census[g['id']] = (centres,normal_census(meshes,centres))
            neutral[g['id']] = neutralise_mesh(meshes,p,sources)
        if prepared or neutral:
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
                    info = tip_info[g['id']]
                    plan[2]['tip_source'] = info['tip_source']
                    for row,side in zip(plan[2]['placement'],info['sides']):
                        row.update(side)
                    if any(bone_key(name) in bones or any(name==other for _,_,previous in plans for other,_,_,_ in previous[0]) for name,_,_,_ in plan[0]):
                        raise ValueError('tip bone already exists')
                    plans.append((g,p,plan))
            # The surface around the tips changed (subdivision, smoothing, fill,
            # stub): its normals follow it (refresh_normals).
            refreshed = refresh_normals(meshes,snapshot)
            for g,_,plan in plans:
                if g['id'] in prepared:
                    plan[2]['normals_refreshed'] = refreshed
                    # The tip smoothing record (Ruling A43): the normals near
                    # the tips before the tip op and now.
                    centres,before_census = census[g['id']]
                    after_census = normal_census(meshes,centres)
                    plan[2]['tip_normals'] = {'region_mm':TIP_NORMAL_REGION_M*1000,
                                              'vertices':[before_census['vertices'],after_census['vertices']],
                                              'inverted':[before_census['inverted'],after_census['inverted']],
                                              'off_60':[before_census['off_60'],after_census['off_60']]}
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
    # The anchor blend travels as glTF node extras of the joint (Bone data
    # custom properties survive import/export round trips; pose bones do not).
    for g,p,plan in plans:
        if g['op'] == 'pair_protrusion':
            for (name,_,_,_),row in zip(plan[0],plan[2]['placement']):
                if row.get('anchor_blend'):
                    arm.data.bones[name]['anchor_blend'] = row['anchor_blend']
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
    for g,p,plan in plans:
        disc = (g.get('tip_override') or {}).get('disc') or {}
        if g['op']=='pair_tip' and disc.get('enabled'):
            # Texels only: the caller paints them into a copy of the clean
            # source's base colour (never compounding on a re-run).
            try:
                metrics[g['id']]['disc_mask'] = disc_mask(meshes,plan[2]['placement'],disc)
            except ValueError as e:
                metrics[g['id']]['disc_mask'] = {'error':str(e)}
    for gid,(rows,smoothing) in neutral.items():
        centres,before_census = census[gid]
        after_census = normal_census(meshes,centres)
        metrics[gid] = {'status':'neutralised','mode':'neutralised','reason':'','placement':rows,
                        'source_smooth':smoothing,
                        'tip_normals':{'region_mm':TIP_NORMAL_REGION_M*1000,
                                       'vertices':[before_census['vertices'],after_census['vertices']],
                                       'inverted':[before_census['inverted'],after_census['inverted']],
                                       'off_60':[before_census['off_60'],after_census['off_60']]}}
    metrics.update(soft)
    output=Path(args['out_dir'])/'model.glb'
    _common.progress('exporting')
    bpy.ops.export_scene.gltf(filepath=str(output),export_format='GLB',export_apply=False,export_yup=True,export_skins=True,export_animations=True,export_morph=True,export_all_influences=False,export_extras=True)
    _common.body_meshes_first(output)
    return {'status':'applied','reason':'','groups':metrics,'metrics':metrics},{'model':str(output)}


# Runs only as the job's own script: imported (inset_part levels with it) or exec'd by a probe, nothing runs.
(_common.main if __name__ == '__main__' else lambda job: None)(extension_bones)
