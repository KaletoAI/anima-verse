"""Build a swept, skinned attached part using root-local smooth SDF unions.

World coordinates are metres, front is -Y and up is +Z. The body is finalized
before sampling the field. The open shell blends into its texture and weights.
"""
import copy
import math
import sys
from pathlib import Path

_SCRIPT_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPT_DIR)
import _common
sys.path.remove(_SCRIPT_DIR)
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

DEFAULTS = {
    'size_factor': 1.0, 'anchor_bone': 'Hips', 'anchor_drop': .09,
    'root_sink': .006, 'length': .095, 'radius': .0165,
    'bend': [[.85, .5, .38], [.25, .97, .7]], 'inner_extension': .015,
    'base_fraction': .15, 'girth_max': 1.2, 'tip_start': 1 - .32 * .85,
    'tip_scale': .85, 'first_link_start': .1,
    'relief': {'amplitude': .00035, 'terms': [[.6, 3.1, 2, 0], [.4, 7.3, -3, 1.3]],
               'start': .1, 'rise': .06, 'end_offset': .02, 'fall': .05},
    'ridges': [
        {'t0': .12, 'tip_offset': .04, 'phase': .45, 'wobble': .25, 'freq': 1.4, 'offset': .5, 'r0': .0015, 'r1': .0008},
        {'t0': .2, 'tip_offset': .08, 'phase': -.6, 'wobble': .2, 'freq': 1.1, 'offset': 2.1, 'r0': .0012, 'r1': .0007},
        {'t0': .1, 'tip_offset': .02, 'phase': math.pi, 'wobble': .03, 'freq': 1., 'offset': 0., 'r0': .0007, 'r1': .0005}],
    'ridge_blend': .0018, 'pod_scale': 1.2,
    'pods': {'down': .046, 'back': .018, 'blend': .008, 'ellipsoids': [
        {'lateral': .012, 'down': .006, 'back': 0., 'radii': [.014, .013, .024]},
        {'lateral': -.012, 'down': .002, 'back': 0., 'radii': [.014, .013, .024]},
        {'lateral': 0., 'down': .012, 'back': 0., 'radii': [.016, .011, .013]},
        {'lateral': 0., 'down': -.008, 'back': .006, 'radii': [.013, .010, .012]}]},
    'pod_link': .7, 'pod_link_distance': .03, 'k_tip_pods': .004, 'k_body': .016,
    'body_window': {'radius': .03, 'fall': .02}, 'skin_sink': .003,
    'hidden_band': {'lateral': .025, 'above': -.02, 'radius': .045, 'depth': .006},
    'flatten': {'lateral': .055, 'down': .035, 'below': .065, 'above': .01,
                'front': .03, 'normal_front': .2, 'iterations': 150},
    'reweight': {'from': .045, 'to': .095},
    'tone': {'shaft': [.9, .83, .8], 'tip': [1.04, .84, .82]}, 'border_lift': .010,
    'texture': {'bake': 1024, 'patch_max': 256, 'flood': .07, 'blur': 9},
    'voxel': .0014, 'smooth': {'iterations': 2, 'factor': .5}, 'decimate': .3,
    'protrusion_warn_mm': 12.,
}


def resolve_bone(bones, name):
    """Resolve the same optional Mixamo prefix as the rig declarations."""
    key = lambda value: value.lower().removeprefix('mixamorig').replace(':', '')
    matches = [bone for bone in bones if key(bone.name) == key(name)]
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous bone: ' + name)
    return matches[0]


def parameters(raw):
    """Merge partial nested settings; reject unknown keys and invalid numbers."""
    def merge(default, value, name):
        if isinstance(default, dict):
            if not isinstance(value, dict) or set(value) - set(default):
                raise ValueError('Unknown or malformed parameter: ' + name)
            return {k: merge(v, value[k], name + '.' + k) if k in value else copy.deepcopy(v)
                    for k, v in default.items()}
        if isinstance(default, list):
            if not isinstance(value, list) or (not value and name not in ('params.ridges', 'params.pods.ellipsoids')):
                raise ValueError('Expected list: ' + name)
            if isinstance(default[0], dict):
                return [merge(default[0], v, name + '[]') for v in value]
            if len(value) != len(default):
                raise ValueError('Invalid vector length: ' + name)
            return [merge(d, v, name + '[]') for d, v in zip(default, value)]
        if isinstance(default, str):
            if not isinstance(value, str) or not value.strip():
                raise ValueError('Expected bone name: ' + name)
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Expected finite number: ' + name)
        elif name in ('params.flatten.iterations', 'params.smooth.iterations', 'params.texture.bake', 'params.texture.patch_max', 'params.texture.blur') and (not isinstance(value, int) or value < 0):
            raise ValueError('Expected nonnegative integer: ' + name)
        return value
    settings = merge(DEFAULTS, raw, 'params')
    for key in ('size_factor', 'length', 'radius', 'voxel', 'tip_scale', 'inner_extension',
                'border_lift', 'k_body', 'k_tip_pods', 'pod_scale', 'pod_link_distance'):
        if settings[key] <= 0:
            raise ValueError(key + ' must be positive')
    if not 0 < settings['decimate'] <= 1 or not 0 <= settings['pod_link'] <= 1:
        raise ValueError('Invalid decimate or pod_link')
    if not 0 < settings['base_fraction'] < settings['tip_start'] < 1 - .09 * settings['tip_scale']:
        raise ValueError('Invalid base / tip profile')
    if not 0 <= settings['first_link_start'] < settings['tip_start']:
        raise ValueError('Invalid first_link_start')
    if settings['reweight']['from'] < 0 or settings['reweight']['to'] <= settings['reweight']['from']:
        raise ValueError('Invalid radial reweight interval')
    for section, keys in (('body_window', ['radius', 'fall']), ('relief', ['rise', 'fall']),
                           ('texture', ['bake', 'patch_max', 'flood', 'blur'])):
        if any(settings[section][key] <= 0 for key in keys):
            raise ValueError('Invalid ' + section)
    if settings['texture']['blur'] % 2 != 1:
        raise ValueError('Texture blur must be odd')
    for e in settings['pods']['ellipsoids']:
        if min(e['radii']) <= 0:
            raise ValueError('Pod radii must be positive')
    for ridge in settings['ridges']:
        if not 0 <= ridge['t0'] < settings['tip_start'] - ridge['tip_offset'] or min(ridge['r0'], ridge['r1']) <= 0:
            raise ValueError('Invalid ridge interval or radius')
    for section, keys in (('flatten', ['lateral', 'down', 'below', 'above', 'front']),
                           ('hidden_band', ['lateral', 'radius', 'depth'])):
        if any(settings[section][key] < 0 for key in keys):
            raise ValueError('Invalid ' + section + ' length')
    if settings['anchor_drop'] < 0 or settings['root_sink'] < 0 or settings['skin_sink'] < 0 or settings['girth_max'] < 1:
        raise ValueError('Invalid root offset or base flare')
    if not 0 <= settings['smooth']['factor'] <= 1 or not 0 <= settings['flatten']['normal_front'] <= 1:
        raise ValueError('Invalid smoothing or front-normal fraction')
    if settings['ridge_blend'] < 0 or settings['pods']['blend'] <= 0 or settings['relief']['amplitude'] < 0:
        raise ValueError('Invalid relief or blend radius')
    if any(min(leg) < 0 or leg[2] <= 0 or leg[0] + leg[1] == 0 for leg in settings['bend']):
        raise ValueError('Invalid bend leg')
    if any(v < 0 for values in settings['tone'].values() for v in values):
        raise ValueError('Invalid tone multiplier')
    if settings['protrusion_warn_mm'] < 0:
        raise ValueError('Invalid protrusion warning threshold')
    return settings


def skin_texel_fallback(pixels):
    return np.median(pixels[..., :3].reshape(-1, 3), axis=0)


def build_part(group, companions, output):
    """Run the accepted field, surface-net, skin-transfer and bake sequence."""
    settings = parameters(group.get('params', {}))
    chain = group['chains'][0]
    link_count = len(chain)
    if len(group['chains']) != 1 or link_count < 2:
        raise ValueError('Attached part requires one chain with at least two links')
    if len(companions) > 1 or any(len(g['chains']) != 1 or len(g['chains'][0]) != 1 or g.get('params') for g in companions):
        raise ValueError('Attached part supports one single-link companion')
    voxel, pod_blend, body_blend = settings['voxel'], settings['k_tip_pods'], settings['k_body']
    pod_bone = companions[0]['chains'][0][0]['bone'] if companions else None
    # Anchor on the textured body surface.
    body = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and o.vertex_groups and not o.get('attached_part'))
    arms = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
    if len(arms) != 1 or abs(bpy.context.scene.unit_settings.scale_length - 1) > 1e-6:
        raise ValueError('Requires one armature and metre scene units')
    armature = arms[0]
    declared = [link for g in [group, *companions] for c in g['chains'] for link in c]
    names = [link['bone'] for link in declared]
    if len(set(names)) != len(names) or any(armature.data.bones.get(name) for name in names):
        raise ValueError('Duplicate or existing part bone')
    known = {bone.name.rsplit(':', 1)[-1].lower() for bone in armature.data.bones}
    for link in declared:
        if link['parent'].rsplit(':', 1)[-1].lower() not in known:
            raise ValueError('Missing declared parent: ' + link['parent'])
        known.add(link['bone'].rsplit(':', 1)[-1].lower())
    if not body.data.uv_layers.active:
        raise ValueError('Body requires a UV map')
    img = [nd.inputs['Base Color'].links[0].from_node.image for nd in body.active_material.node_tree.nodes
           if nd.type == 'BSDF_PRINCIPLED'][0]
    texture_width, texture_height = img.size
    pixels = np.empty(texture_width * texture_height * 4, np.float32)
    img.pixels.foreach_get(pixels)
    pixels = pixels.reshape(texture_height, texture_width, 4)
    body_matrix = body.matrix_world.copy()
    body_inverse = body_matrix.inverted()
    normal_matrix, inverse_normal_matrix = body_matrix.to_3x3(), body_inverse.to_3x3()
    anchor_name = resolve_bone(armature.data.bones, settings['anchor_bone']).name
    pod_bone = pod_bone or anchor_name
    hips = armature.matrix_world @ armature.pose.bones[anchor_name].head
    att = Vector((hips.x, hips.y, hips.z - settings['anchor_drop']))
    dg = bpy.context.evaluated_depsgraph_get()
    bvh = BVHTree.FromObject(body, dg)
    hit = bvh.ray_cast(body_inverse @ (att + Vector((0, -.15, -.01))), inverse_normal_matrix @ Vector((0, 1, 0)))
    if hit[0] is None:
        raise ValueError('Anchor ray missed the body')
    surface_point, surface_normal = body_matrix @ hit[0], (normal_matrix @ hit[1]).normalized()
    surface_normal = Vector((0, surface_normal.y, surface_normal.z)).normalized()
    print('surface', [round(x, 3) for x in surface_point], 'normal', [round(x, 2) for x in surface_normal])
    # Does the generated body still carry a part? Anything on the midline below the
    # anchor that reaches in front of the belly line (6-12 cm above the anchor) is one;
    # a flat or softly rounded body stays behind that line (measured: drawn part
    # +40 mm, part-less body -15 mm). Measured before any flattening.
    body_points = [body_matrix @ v.co for v in body.data.vertices]
    belly = [p.y for p in body_points if abs(p.x - hips.x) < .02 and att.z + .06 < p.z < att.z + .12]
    below = [p.y for p in body_points if abs(p.x - hips.x) < .04 and att.z - .16 < p.z < att.z - .02]
    protrusion = max(0.0, (min(belly) - min(below)) * 1000) if belly and below else 0.0


    down, lat, upv = Vector((0, 0, -1)), Vector((1, 0, 0)), Vector((0, 0, 1))
    size_factor = settings['size_factor']
    sweep_length, shaft_radius = settings['length'] * size_factor, settings['radius'] * size_factor
    root = surface_point - surface_normal * settings['root_sink']
    curve_root = root
    curve_control = root + (surface_normal * settings['bend'][0][0] + down * settings['bend'][0][1]).normalized() * sweep_length * settings['bend'][0][2]
    curve_end = curve_control + (down * settings['bend'][1][1] + surface_normal * settings['bend'][1][0]).normalized() * sweep_length * settings['bend'][1][2]
    # Sample the two-leg quadratic sweep and its inner extension.
    sweep_samples = 240
    cl = [curve_root * (1 - t) ** 2 + curve_control * 2 * t * (1 - t) + curve_end * t * t for t in np.linspace(0, 1, sweep_samples)]
    arc = np.concatenate([[0], np.cumsum([(cl[i] - cl[i - 1]).length for i in range(1, sweep_samples)])])
    tparam = arc / arc[-1]
    inner = [root - surface_normal * settings['inner_extension'] * f for f in np.linspace(1, 0, 12, endpoint=False)]
    centerline = np.array([tuple(point) for point in inner] + [tuple(point) for point in cl])
    stations = np.concatenate([np.linspace(-.15, 0, 12, endpoint=False), tparam])
    tip_start = settings['tip_start']
    tip_scale = settings['tip_scale']


    base_fraction, girth_max = settings['base_fraction'], settings['girth_max']


    # Shaft flare, fixed tip profile, and geometric surface relief.
    def radius(t):
        t = np.asarray(t, float)
        r = np.where(t < tip_start, 1 - .05 * np.clip(t, 0, 1) / tip_start, 0)

        w_ = np.clip(t / base_fraction, 0, 1)
        r = r * np.where(t < base_fraction, girth_max / (1 + w_ * (girth_max - 1)), 1)
        r = np.where((t >= tip_start) & (t < tip_start + .03 * tip_scale), .95 - .06 * (t - tip_start) / (.03 * tip_scale), r)
        r = np.where((t >= tip_start + .03 * tip_scale) & (t < tip_start + .09 * tip_scale), .89 + .09 * np.sin((t - tip_start - .03 * tip_scale) / (.06 * tip_scale) * np.pi / 2), r)
        u = np.clip((t - tip_start - .09 * tip_scale) / (1 - tip_start - .09 * tip_scale), 0, 1)
        r = np.where(t >= tip_start + .09 * tip_scale, .98 * np.maximum(0, 1 - u ** 2.4) ** .55, r)
        return shaft_radius * r


    TAN = np.gradient(centerline, axis=0)
    TAN /= np.linalg.norm(TAN, axis=1)[:, None]
    SNv = np.array(tuple(surface_normal))
    DOR = SNv[None, :] - TAN * (TAN @ SNv)[:, None]
    DOR /= np.linalg.norm(DOR, axis=1)[:, None]
    SIDE = np.cross(TAN, DOR)


    def relief(t, ph):

        fade = np.clip((t - settings['relief']['start']) / settings['relief']['rise'], 0, 1) * np.clip((tip_start - settings['relief']['end_offset'] - t) / settings['relief']['fall'], 0, 1)
        return settings['relief']['amplitude'] * size_factor * fade * sum(a * np.sin(2 * np.pi * freq * t + phase * ph + offset) for a, freq, phase, offset in settings['relief']['terms'])


    def shaft_tube(P):
        best = np.full(len(P), 1e9)
        bt = np.zeros(len(P))
        bph = np.zeros(len(P))
        for i in range(len(centerline) - 1):
            A, B = centerline[i], centerline[i + 1]
            AB = B - A
            h = np.clip(((P - A) @ AB) / (AB @ AB), 0, 1)
            D = P - (A + h[:, None] * AB)
            d = np.linalg.norm(D, axis=1)
            t = stations[i] + h * (stations[i + 1] - stations[i])
            ph = np.arctan2(D @ SIDE[i], D @ DOR[i])
            sd = d - radius(t) - relief(t, ph)
            sel = sd < best
            best[sel], bt[sel], bph[sel] = sd[sel], t[sel], ph[sel]
        return best, bt


    def cl_at(t):
        j = np.clip(np.searchsorted(stations, t), 1, len(stations) - 1)
        return j


    def ridge_line(t0, t1, phase, wob, freq, off, r0, r1, n=70):
        pts, rad = [], []
        for t in np.linspace(t0, t1, n):
            j = cl_at(t)
            ph = phase + wob * np.sin(2 * np.pi * freq * t + off)
            r = float(radius(t))
            rv = (r0 + (r1 - r0) * (t - t0) / (t1 - t0)) * size_factor
            pts.append(centerline[j] + (DOR[j] * np.cos(ph) + SIDE[j] * np.sin(ph)) * (r + .25 * rv))
            rad.append(rv)
        return np.array(pts), np.array(rad)


    RIDGES = [ridge_line(r['t0'], tip_start - r['tip_offset'], r['phase'], r['wobble'], r['freq'], r['offset'], r['r0'], r['r1']) for r in settings['ridges']]


    def ridge_sdf(P):
        best = np.full(len(P), 1e9)
        for pts, rad in RIDGES:
            for i in range(len(pts) - 1):
                A, B = pts[i], pts[i + 1]
                AB = B - A
                h = np.clip(((P - A) @ AB) / (AB @ AB), 0, 1)
                d = np.linalg.norm(P - (A + h[:, None] * AB), axis=1) - (rad[i] + h * (rad[i + 1] - rad[i]))
                best = np.minimum(best, d)
        return best


    def shaft_sdf(P):
        d, t = shaft_tube(P)
        return smin(d, ridge_sdf(P), settings['ridge_blend'] * size_factor), t



    pod_factor = (1 + .55 * (size_factor - 1)) * settings['pod_scale']
    pod_center = root + down * settings['pods']['down'] * pod_factor - surface_normal * settings['pods']['back']
    pod_ellipsoids = [(pod_center + lat * e['lateral'] * pod_factor + down * e['down'] * pod_factor - surface_normal * e['back'], np.array(e['radii']) * pod_factor) for e in settings['pods']['ellipsoids']]
    FR = np.array([tuple(lat), tuple(surface_normal), tuple(upv)])


    def smin(a_, b_, k):
        k = np.maximum(k, 1e-9)
        h = np.maximum(k - np.abs(a_ - b_), 0) / k
        return np.minimum(a_, b_) - h * h * k / 4


    def k_body(P):

        d = np.linalg.norm(P - np.array(tuple(root)), axis=1)
        return body_blend * np.clip(1 - (d - settings['body_window']['radius'] * size_factor) / (settings['body_window']['fall'] * size_factor), 0, 1)


    def ellip(P, c, r):
        q = (P - np.array(tuple(c))) @ FR.T / r
        return (np.linalg.norm(q, axis=1) - 1) * r.min()


    def pods_sdf(P):
        if not pod_ellipsoids:
            return np.full(len(P), 1e9)
        d = ellip(P, *pod_ellipsoids[0])
        for c, r in pod_ellipsoids[1:]:
            d = smin(d, ellip(P, c, r), settings['pods']['blend'] * pod_factor)
        return d



    # Flatten the front window: one inward displacement per seam group.
    import bmesh as _bm
    bmb = _bm.new(); bmb.from_mesh(body.data); bmb.verts.ensure_lookup_table()
    cen = root + down * settings['flatten']['down']
    window = settings['flatten']
    def in_window(v):
        point = body_matrix @ v.co
        n = (normal_matrix @ v.normal).normalized()
        return abs(point.x - cen.x) < window['lateral'] and cen.z - window['below'] < point.z < root.z + window['above'] and point.y < cen.y + window['front'] and n.y < -window['normal_front']

    keyv = {}
    for v in bmb.verts:
        keyv.setdefault(tuple(round(c / 1e-5) for c in v.co), []).append(v)
    mask = {v for v in bmb.verts if in_window(v)}
    nbrs = {}
    for v in mask:
        ns = set()
        for c in keyv[tuple(round(x / 1e-5) for x in v.co)]:
            for e in c.link_edges:
                ns.add(e.other_vert(c))
        nbrs[v] = list(ns)
    orig = {v: v.co.copy() for v in mask}
    pos = {v: v.co.copy() for v in mask}
    for _ in range(settings['flatten']['iterations']):
        newp = {}
        for v in mask:
            acc_ = Vector()
            for u_ in nbrs[v]:
                acc_ += pos.get(u_, u_.co)
            newp[v] = acc_ / len(nbrs[v]) if nbrs[v] else pos[v]
        pos = newp
    flat = 0
    flatten_outward = 0.0
    done_ = set()
    for v in mask:
        grp = keyv[tuple(round(x / 1e-5) for x in orig[v])]
        if id(grp) in done_:
            continue
        done_.add(id(grp))

        inm = [c for c in grp if c in mask]
        n = sum((c.normal for c in grp), Vector()).normalized()
        target = sum((pos[c] for c in inm), Vector()) / len(inm)
        d = (orig[v] - target).dot(n)
        if d > 0:
            for c in grp:
                c.co = orig[v] - n * d
            flatten_outward = max(flatten_outward, (grp[0].co - orig[v]).dot(n))
            flat += len(grp)
    seam_cracks = sum(max((c.co - grp[0].co).length for c in grp) > 1e-6 for grp in keyv.values() if len(grp) > 1)
    bmb.to_mesh(body.data); bmb.free(); body.data.update()
    print('window verts flattened', flat, 'of', len(mask))
    # Transfer only radial upper-leg influences to the anchor.
    hips_g = body.vertex_groups[anchor_name]
    legs = [g for g in body.vertex_groups if g.name.endswith('UpLeg')]
    moved = 0
    for v in body.data.vertices:
        d = (body_matrix @ v.co - root).length
        f = float(np.clip(1 - (d - settings['reweight']['from']) / (settings['reweight']['to'] - settings['reweight']['from']), 0, 1))
        if f <= 0:
            continue
        f = f * f * (3 - 2 * f)
        take = 0.0
        for g in v.groups:
            if body.vertex_groups[g.group] in legs and g.weight > 0:
                x = g.weight * f
                take += x
                body.vertex_groups[g.group].add([v.index], g.weight - x, 'REPLACE')
        if take > 0:
            cur = next((g.weight for g in v.groups if g.group == hips_g.index), 0.0)
            hips_g.add([v.index], cur + take, 'REPLACE')
            moved += 1
    print('root verts moved to hips', moved)
    dg = bpy.context.evaluated_depsgraph_get()
    bvh = BVHTree.FromObject(body, dg)


    # Sample root-local unions of sweep, ridges, pods and body skin.
    pts = np.vstack([centerline, *[np.array(tuple(c)) + np.diag(r) for c, r in pod_ellipsoids], *[np.array(tuple(c)) - np.diag(r) for c, r in pod_ellipsoids]])
    lo, hi = pts.min(0) - .02, pts.max(0) + .02
    nx, ny, nz = (np.ceil((hi - lo) / voxel)).astype(int) + 1
    if int(nx) * int(ny) * int(nz) > 8_000_000:
        raise ValueError('Part voxel grid exceeds 8 million samples')
    gx, gy, gz = (lo[0] + np.arange(nx) * voxel, lo[1] + np.arange(ny) * voxel, lo[2] + np.arange(nz) * voxel)
    grid_points = np.stack(np.meshgrid(gx, gy, gz, indexing='ij'), -1).reshape(-1, 3)
    print('grid', nx, ny, nz, len(grid_points))
    ds, dt = shaft_sdf(grid_points)
    dc = pods_sdf(grid_points)
    part = smin(ds, dc, pod_blend)
    db = np.full(len(grid_points), 1.0)
    band = np.where(part < 2.5 * body_blend)[0]
    for i in band:
        point = Vector(grid_points[i])
        q, n, _, _ = bvh.find_nearest(body_inverse @ point)
        q, n = body_matrix @ q, (normal_matrix @ n).normalized()
        v = point - q
        db[i] = v.length * (1 if v.dot(n) >= 0 else -1)
    U = smin(part, db + settings['skin_sink'], k_body(grid_points))
    field = U.reshape(nx, ny, nz)
    print('field done, band', len(band))


    # Surface nets: one average crossing vertex per active cell.
    inside = field < 0
    cell_any = np.zeros((nx - 1, ny - 1, nz - 1), int)
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                cell_any += inside[dx:nx - 1 + dx, dy:ny - 1 + dy, dz:nz - 1 + dz]
    active = (cell_any > 0) & (cell_any < 8)
    cid = -np.ones(active.shape, int)
    cells = np.argwhere(active)
    cid[active] = np.arange(len(cells))
    corner = np.array([[i, j, k] for i in (0, 1) for j in (0, 1) for k in (0, 1)])
    edges = [(a_, b_) for a_ in range(8) for b_ in range(a_ + 1, 8) if np.abs(corner[a_] - corner[b_]).sum() == 1]
    vacc = np.zeros((len(cells), 3))
    vcnt = np.zeros(len(cells))
    for a_, b_ in edges:
        ia, ib = cells + corner[a_], cells + corner[b_]
        fa, fb = field[tuple(ia.T)], field[tuple(ib.T)]
        cr = (fa < 0) != (fb < 0)
        tt = np.where(cr, fa / np.where(fa - fb == 0, 1e-12, fa - fb), 0)
        crossings = lo + (ia + (ib - ia) * tt[:, None]) * voxel
        vacc[cr] += crossings[cr]
        vcnt[cr] += 1
    positions = vacc / np.maximum(vcnt, 1)[:, None]
    quads = []
    for axis in range(3):
        o1, o2 = [ax for ax in range(3) if ax != axis]
        sl = [slice(0, nx), slice(0, ny), slice(0, nz)]
        sl[axis] = slice(0, field.shape[axis] - 1)
        A_ = inside[tuple(sl)]
        sl2 = list(sl)
        sl2[axis] = slice(1, field.shape[axis])
        B_ = inside[tuple(sl2)]
        for idx in np.argwhere(A_ != B_):
            if idx[o1] == 0 or idx[o2] == 0:
                continue
            c = []
            for d1, d2 in ((0, 0), (1, 0), (1, 1), (0, 1)):
                q = idx.copy()
                q[o1] -= d1
                q[o2] -= d2
                if q[o1] >= cid.shape[o1] or q[o2] >= cid.shape[o2] or q[axis] >= cid.shape[axis]:
                    c = None
                    break
                c.append(cid[tuple(q)])
            if not c or min(c) < 0:
                continue
            flip = A_[tuple(idx)] ^ (axis == 1)
            quads.append(c[::-1] if flip else c)
    quads = np.array(quads)
    print('verts', len(positions), 'quads', len(quads))


    # Keep the shell, including a short hidden band at the root.
    shaft_distance, part_station = shaft_sdf(positions)
    pod_distance = pods_sdf(positions)
    part_distance = smin(shaft_distance, pod_distance, pod_blend)
    skin_distance = np.empty(len(positions))
    skin_nearest = []
    for i, point in enumerate(positions):
        q, n, fi, _ = bvh.find_nearest(body_inverse @ Vector(point))
        q, n = body_matrix @ q, (normal_matrix @ n).normalized()
        skin_distance[i] = (Vector(point) - q).dot(n)
        skin_nearest.append((q, fi))
    near_root = (np.abs(positions[:, 0] - root.x) < settings['hidden_band']['lateral'] * size_factor) & (positions[:, 2] > root.z + settings['hidden_band']['above'] * size_factor) & (np.linalg.norm(positions - np.array(tuple(root)), axis=1) < settings['hidden_band']['radius'] * size_factor)
    keepv = (part_distance < 1.15 * body_blend) & np.where(near_root, skin_distance > -settings['hidden_band']['depth'], skin_distance > .0006)
    quads = quads[keepv[quads].all(1)]
    used = np.unique(quads)
    remap = -np.ones(len(positions), int)
    remap[used] = np.arange(len(used))
    if not len(used):
        raise ValueError('Part field produced no visible faces')
    positions, quads = positions[used], remap[quads]
    shaft_distance, part_station, pod_distance, part_distance = shaft_distance[used], part_station[used], pod_distance[used], part_distance[used]
    skin_nearest = [skin_nearest[i] for i in used]
    skin_distance = skin_distance[used]
    print('kept verts', len(positions), 'quads', len(quads))


    # Blend skin texels by fillet share and lift above the body.
    fillet_weight = np.clip(part_distance / body_blend, 0, 1)
    fillet_weight = fillet_weight * fillet_weight * (3 - 2 * fillet_weight)
    tip_weight = np.clip((part_station - tip_start) / .06, 0, 1) * (shaft_distance < pod_distance)
    tone_p = (.5 + .5 * tip_weight) * (1 - fillet_weight)

    wl = np.clip(1 - skin_distance / settings['border_lift'], 0, 1)
    wl = wl * wl * (3 - 2 * wl)
    skin_weight = np.maximum(fillet_weight, wl)
    cols = []
    for l in body.data.loops:
        point = body_matrix @ body.data.vertices[l.vertex_index].co
        if abs(point.x - att.x) < .05 and att.z + .05 < point.z < att.z + .15 and point.y < att.y + .02:
            q = body.data.uv_layers.active.data[l.index].uv
            cols.append(pixels[int(q.y % 1 * texture_height) % texture_height, int(q.x % 1 * texture_width) % texture_width, :3])
    skin_tone = np.median(np.array(cols), 0) if cols else skin_texel_fallback(pixels)
    dark = skin_tone * np.array(settings['tone']['shaft'])
    tip = dark * np.array(settings['tone']['tip'])
    from mathutils.geometry import barycentric_transform
    body.data.calc_loop_triangles()
    uvd = body.data.uv_layers.active.data
    polys = body.data.polygons


    def skin_texel(q, fi):
        poly = polys[fi]
        vs = [body_matrix @ body.data.vertices[v].co for v in poly.vertices]
        uvs = [Vector((*uvd[li].uv, 0)) for li in poly.loop_indices]
        uvp = barycentric_transform(q, vs[0], vs[1], vs[2], uvs[0], uvs[1], uvs[2])
        return pixels[int(uvp.y % 1 * texture_height) % texture_height, int(uvp.x % 1 * texture_width) % texture_width, :3]


    vertex_colors = np.zeros((len(positions), 4))
    for i in range(len(positions)):
        tone = dark * (1 - tip_weight[i]) + tip * tip_weight[i]
        under = skin_texel(*skin_nearest[i]) if skin_weight[i] > 0 else skin_tone
        vertex_colors[i, :3] = under * skin_weight[i] + tone * (1 - skin_weight[i])
        vertex_colors[i, 3] = 1
    # Transfer skin weights at the border; known part weights elsewhere.
    kd = KDTree(len(body.data.vertices))
    for v in body.data.vertices:
        kd.insert(body_matrix @ v.co, v.index)
    kd.balance()
    gname = {g.index: g.name for g in body.vertex_groups}


    link_edges = [settings['first_link_start'] + (tip_start - settings['first_link_start']) * k / (link_count - 1) for k in range(link_count)] + [1.0]
    link_centers = [(link_edges[k] + link_edges[k + 1]) / 2 for k in range(link_count)]


    def shaft_weights(t):
        if t < 0:
            return {anchor_name: 1.0}
        if t >= tip_start:
            f = min(1, (t - tip_start) / .03 + .5) if t < tip_start + .015 else 1
            w = {chain[-1]['bone']: f}
            if f < 1:
                w[chain[-2]['bone']] = 1 - f
            return w
        if t <= link_centers[0]:
            w = {chain[0]['bone']: 1.0}
        else:
            k = max(j for j in range(link_count - 1) if link_centers[j] <= t)
            hi = tip_start if k == link_count - 2 else link_centers[k + 1]
            f = min(1, (t - link_centers[k]) / (hi - link_centers[k]))
            w = {chain[k]['bone']: 1 - f * (.5 if k == link_count - 2 else 1),
                 chain[k + 1]['bone']: f * (.5 if k == link_count - 2 else 1)}
        if t < base_fraction:
            h = (base_fraction - t) / base_fraction
            w = {k: v * (1 - h) for k, v in w.items()}
            w[anchor_name] = h
        return w


    boundary_edges = {}
    for face in quads:
        for a, b in zip(face, np.roll(face, -1)):
            edge = tuple(sorted((int(a), int(b))))
            boundary_edges[edge] = boundary_edges.get(edge, 0) + 1
    border = {vi for edge, count in boundary_edges.items() if count == 1 for vi in edge}
    vertex_weights = []
    for i, point in enumerate(positions):
        ws_ = shaft_weights(max(part_station[i], 0))

        near_sh = float(np.clip(1 - max(shaft_distance[i], 0) / settings['pod_link_distance'], 0, 1)) ** 1.5 * settings['pod_link']
        wc_ = {pod_bone: 1 - near_sh, chain[0]['bone']: near_sh}
        mix = np.clip((pod_distance[i] - shaft_distance[i]) / .04, 0, 1)
        w = {}
        for d_, f_ in ((ws_, mix), (wc_, 1 - mix)):
            for k_, x_ in d_.items():
                w[k_] = w.get(k_, 0) + x_ * f_
        # Only the skin fillet at the root takes the skin's weights; a border where the
        # part merely touches other skin (pods against the thighs) keeps part weights.
        # Keep the continuous reference share even at open borders: forcing
        # a fillet share above .5 to 1 creates a weight step under chain lift.
        wroot = fillet_weight[i]
        if wroot > 0:
            _, bi, _ = kd.find(Vector(skin_nearest[i][0]))
            bw = {gname[g.group]: g.weight for g in body.data.vertices[bi].groups}
            tot_ = sum(bw.values()) or 1
            w = {k_: x_ * (1 - wroot) for k_, x_ in w.items()}
            for k_, x_ in bw.items():
                w[k_] = w.get(k_, 0) + wroot * x_ / tot_
        vertex_weights.append(w)


    # Create the skinned object, declared links and companion.
    me = bpy.data.meshes.new('Part')
    me.from_pydata([tuple(body_inverse @ Vector(point)) for point in positions], [], [tuple(q) for q in quads])
    me.update()
    uv = me.uv_layers.new(name='UVMap')
    for poly in me.polygons:
        poly.use_smooth = True
        for li in poly.loop_indices:
            vi = me.loops[li].vertex_index
            point = positions[vi]
            uv.data[li].uv = (((point[0] + point[2]) * 9) % 1, min(.998, max(.002, tone_p[vi])))
    ca = me.color_attributes.new('Col', 'FLOAT_COLOR', 'POINT')
    for i in range(len(positions)):
        c_ = vertex_colors[i, :3]
        lin_ = np.where(c_ <= .04045, c_ / 12.92, ((c_ + .055) / 1.055) ** 2.4)
        ca.data[i].color = (*lin_, 1.0)
    me.color_attributes.active_color = ca
    gat = me.attributes.new('tip', 'FLOAT', 'POINT')
    sat = me.attributes.new('skin', 'FLOAT', 'POINT')
    for i in range(len(positions)):
        gat.data[i].value = float(tip_weight[i])
        sat.data[i].value = float(skin_weight[i])
    partobj = bpy.data.objects.new('Part', me)
    bpy.context.scene.collection.objects.link(partobj)
    partobj.matrix_world = body_matrix
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode='EDIT')
    eb = armature.data.edit_bones
    ami = armature.matrix_world.inverted()
    idx_t = lambda t: Vector(centerline[12 + int(round(t * (sweep_samples - 1)))])
    for b in range(link_count):
        t0, t1 = link_edges[b], link_edges[b + 1]
        bone = eb.new(chain[b]['bone'])
        bone.head, bone.tail = ami @ idx_t(t0), ami @ idx_t(t1)
        bone.parent = resolve_bone(eb, chain[b]['parent'])
        bone.use_connect = b > 0 and bone.parent.name == chain[b - 1]['bone']
    for companion in companions:
        link = companion['chains'][0][0]
        bone = eb.new(link['bone'])
        bone.head, bone.tail = ami @ pod_center, ami @ (pod_center + down * .02)
        bone.parent = resolve_bone(eb, link['parent'])
    bpy.ops.object.mode_set(mode='OBJECT')
    groups = {}
    for i, w in enumerate(vertex_weights):
        for name, x in w.items():
            if x > 1e-4:
                g = groups.get(name) or partobj.vertex_groups.new(name=name)
                groups[name] = g
                g.add([i], x, 'REPLACE')
    partobj['attached_part'] = group['id']
    partobj.parent = armature
    partobj.matrix_world = body_matrix
    mod = partobj.modifiers.new('Armature', 'ARMATURE')
    mod.object = armature

    bpy.context.view_layer.objects.active = partobj
    sm = partobj.modifiers.new('Smooth', 'SMOOTH')
    sm.factor, sm.iterations = settings['smooth']['factor'], settings['smooth']['iterations']
    bpy.ops.object.modifier_move_to_index(modifier='Smooth', index=0)
    bpy.ops.object.modifier_apply(modifier='Smooth')
    dec = partobj.modifiers.new('Decimate', 'DECIMATE')
    dec.ratio = settings['decimate']
    bpy.ops.object.modifier_move_to_index(modifier='Decimate', index=0)
    bpy.ops.object.modifier_apply(modifier='Decimate')
    final_positions = np.array([tuple(body_matrix @ v.co) for v in partobj.data.vertices])
    final_ds, final_t = shaft_sdf(final_positions)
    final_dc = pods_sdf(final_positions)
    edge_counts = {}
    for poly in partobj.data.polygons:
        for edge in poly.edge_keys:
            edge_counts[edge] = edge_counts.get(edge, 0) + 1
    final_border = {vi for edge, count in edge_counts.items() if count == 1 for vi in edge}
    # Preserve the reference's interpolated weights after both modifiers.
    # Reclassifying a smoothed vertex by its new station creates hard seams.
    tip_count = int(np.count_nonzero((final_t >= tip_start + .015) & (final_ds < final_dc)))
    for vertex in partobj.data.vertices:
        i = vertex.index
        # Incidental skin contacts must not give the free shell thigh motion.
        # The root's skin transfer remains intact within the 35 mm root ball.
        if (Vector(final_positions[i]) - root).length > .035:
            take = 0.
            for entry in list(vertex.groups):
                vg = partobj.vertex_groups[entry.group]
                if vg.name.endswith('UpLeg'):
                    take += entry.weight
                    vg.remove([i])
            if take:
                vg = partobj.vertex_groups.get(anchor_name) or partobj.vertex_groups.new(name=anchor_name)
                current = next((entry.weight for entry in vertex.groups if entry.group == vg.index), 0.)
                vg.add([i], current + take, 'REPLACE')
    print('part tris', sum(len(poly.vertices) - 2 for poly in partobj.data.polygons))

    # Extract a clean skin square from the nearby UV island.
    hb = bvh.ray_cast(body_inverse @ (root + upv * .08 + Vector((0, -.25, 0))), inverse_normal_matrix @ Vector((0, 1, 0)))
    face0 = hb[2]
    if face0 is None:
        raise ValueError('Skin patch ray missed the body')
    ek = {}
    for poly in body.data.polygons:
        for e_ in poly.edge_keys:
            ek.setdefault(e_, []).append(poly.index)
    isl, st_ = {face0}, [face0]
    c0 = body_matrix @ body.data.polygons[face0].center
    while st_:
        f_ = st_.pop()
        for e_ in body.data.polygons[f_].edge_keys:
            for g_ in ek[e_]:
                if g_ not in isl and (body_matrix @ body.data.polygons[g_].center - c0).length < settings['texture']['flood']:
                    isl.add(g_)
                    st_.append(g_)
    mask = np.zeros((texture_height, texture_width), bool)
    a3 = auv = 0.0
    for t_ in body.data.loop_triangles:
        if t_.polygon_index not in isl:
            continue
        q_ = np.array([[uvd[l].uv.x * texture_width, uvd[l].uv.y * texture_height] for l in t_.loops])
        P3 = [body_matrix @ body.data.vertices[v].co for v in t_.vertices]
        a3 += (P3[1] - P3[0]).cross(P3[2] - P3[0]).length / 2
        auv += abs(np.cross(q_[1] - q_[0], q_[2] - q_[0])) / 2
        x0_, y0_ = np.floor(q_.min(0)).astype(int)
        x1_, y1_ = np.ceil(q_.max(0)).astype(int)
        xs, ys = np.meshgrid(np.arange(x0_, x1_ + 1) + .5, np.arange(y0_, y1_ + 1) + .5)
        d_ = (q_[1, 1] - q_[2, 1]) * (q_[0, 0] - q_[2, 0]) + (q_[2, 0] - q_[1, 0]) * (q_[0, 1] - q_[2, 1])
        if abs(d_) < 1e-12:
            continue
        l1 = ((q_[1, 1] - q_[2, 1]) * (xs - q_[2, 0]) + (q_[2, 0] - q_[1, 0]) * (ys - q_[2, 1])) / d_
        l2 = ((q_[2, 1] - q_[0, 1]) * (xs - q_[2, 0]) + (q_[0, 0] - q_[2, 0]) * (ys - q_[2, 1])) / d_
        ins = (l1 >= 0) & (l2 >= 0) & (1 - l1 - l2 >= 0)
        yy_, xx_ = (ys[ins] - .5).astype(int) % texture_height, (xs[ins] - .5).astype(int) % texture_width
        mask[yy_, xx_] = True
    mpp = math.sqrt(a3 / max(auv, 1e-12))
    ys_, xs_ = np.nonzero(mask)
    y0b, x0b = ys_.min(), xs_.min()
    sub = mask[y0b:ys_.max() + 1, x0b:xs_.max() + 1]
    dp = np.zeros(sub.shape, int)
    for i_ in range(sub.shape[0]):
        for j_ in range(sub.shape[1]):
            if sub[i_, j_]:
                dp[i_, j_] = 1 + (min(dp[i_ - 1, j_], dp[i_, j_ - 1], dp[i_ - 1, j_ - 1]) if i_ and j_ else 0)
    i_, j_ = np.unravel_index(dp.argmax(), dp.shape)
    S_ = min(int(dp[i_, j_]) - 2, settings['texture']['patch_max'])
    if S_ < 1:
        raise ValueError('No clean skin patch in the UV island')
    y0p, x0p = y0b + i_ - S_ + 1, x0b + j_ - S_ + 1
    P_ = pixels[y0p:y0p + S_, x0p:x0p + S_, :3].copy()
    print('skin patch', S_, 'px =', round(S_ * mpp * 100, 1), 'cm, island faces', len(isl))
    curve_end = np.concatenate([np.concatenate([P_, P_[:, ::-1]], 1), np.concatenate([P_[::-1], P_[::-1, ::-1]], 1)], 0)
    blur = curve_end.copy()
    for ax in (0, 1):
        blur = sum(np.roll(blur, k_, ax) for k_ in range(-settings['texture']['blur'] // 2 + 1, settings['texture']['blur'] // 2 + 1)) / settings['texture']['blur']
    lin = lambda c: np.where(c <= .04045, c / 12.92, ((c + .055) / 1.055) ** 2.4)
    mean_lin = lin(P_).reshape(-1, 3).mean(0)


    def mkimg(name, arr):
        im = bpy.data.images.new(name, arr.shape[1], arr.shape[0], alpha=False)
        rgba = np.ones((*arr.shape[:2], 4), np.float32)
        rgba[..., :3] = arr
        im.pixels.foreach_set(rgba.ravel())
        im.pack()
        return im


    im_shaft, im_tip = mkimg('skin_patch', curve_end), mkimg('skin_patch_soft', blur)

    # Bake real skin detail at body texel scale with a softer tip patch.
    for o in bpy.context.scene.objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = partobj
    partobj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=1.15192, island_margin=0.004)
    bpy.ops.object.mode_set(mode='OBJECT')
    BS = settings['texture']['bake']
    bimg = bpy.data.images.new('part_baked', BS, BS, alpha=False)
    bm_ = bpy.data.materials.new('part_bake')
    bm_.use_nodes = True
    nt = bm_.node_tree
    nt.nodes.clear()
    N_ = nt.nodes.new
    out = N_('ShaderNodeOutputMaterial')
    emit = N_('ShaderNodeEmission')
    col = N_('ShaderNodeAttribute'); col.attribute_name = 'Col'
    gla = N_('ShaderNodeAttribute'); gla.attribute_name = 'tip'
    tc = N_('ShaderNodeTexCoord')
    mp = N_('ShaderNodeMapping')
    sc_m = 1 / (2 * S_ * mpp)
    mp.inputs['Scale'].default_value = (sc_m, sc_m, sc_m)
    nt.links.new(tc.outputs['Object'], mp.inputs['Vector'])
    ts = N_('ShaderNodeTexImage'); ts.image = im_shaft
    tg_ = N_('ShaderNodeTexImage'); tg_.image = im_tip
    for t_n in (ts, tg_):
        t_n.projection, t_n.projection_blend, t_n.extension = 'BOX', .3, 'REPEAT'
        nt.links.new(mp.outputs['Vector'], t_n.inputs['Vector'])
    mxs = N_('ShaderNodeMix'); mxs.data_type = 'RGBA'
    nt.links.new(gla.outputs['Fac'], mxs.inputs['Factor'])
    nt.links.new(ts.outputs['Color'], mxs.inputs[6]); nt.links.new(tg_.outputs['Color'], mxs.inputs[7])
    inv = N_('ShaderNodeRGB'); inv.outputs[0].default_value = (*(1 / mean_lin), 1)
    m1 = N_('ShaderNodeMix'); m1.data_type = 'RGBA'; m1.blend_type = 'MULTIPLY'; m1.inputs['Factor'].default_value = 1
    nt.links.new(mxs.outputs[2], m1.inputs[6]); nt.links.new(inv.outputs[0], m1.inputs[7])
    ska = N_('ShaderNodeAttribute'); ska.attribute_name = 'skin'
    fade = N_('ShaderNodeMix'); fade.data_type = 'RGBA'
    nt.links.new(ska.outputs['Fac'], fade.inputs['Factor'])
    nt.links.new(m1.outputs[2], fade.inputs[6]); fade.inputs[7].default_value = (1, 1, 1, 1)
    m2 = N_('ShaderNodeMix'); m2.data_type = 'RGBA'; m2.blend_type = 'MULTIPLY'; m2.inputs['Factor'].default_value = 1
    nt.links.new(fade.outputs[2], m2.inputs[6]); nt.links.new(col.outputs['Color'], m2.inputs[7])
    nt.links.new(m2.outputs[2], emit.inputs['Color'])
    nt.links.new(emit.outputs['Emission'], out.inputs['Surface'])
    tex_ = N_('ShaderNodeTexImage'); tex_.image = bimg; nt.nodes.active = tex_
    partobj.data.materials.clear(); partobj.data.materials.append(bm_)
    sc_ = bpy.context.scene
    sc_.render.engine = 'CYCLES'; sc_.cycles.device = 'CPU'; sc_.cycles.samples = 1
    sc_.render.bake.margin = 8
    bpy.ops.object.bake(type='EMIT')
    bimg.pack()
    nt.nodes.clear()
    out = N_('ShaderNodeOutputMaterial'); bsdf = N_('ShaderNodeBsdfPrincipled'); tex_ = N_('ShaderNodeTexImage'); tex_.image = bimg
    nt.links.new(tex_.outputs['Color'], bsdf.inputs['Base Color']); nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    bsdf.inputs['Roughness'].default_value = .55
    me_ = partobj.data
    while me_.color_attributes:
        me_.color_attributes.remove(me_.color_attributes[0])
    me_.attributes.remove(me_.attributes['tip'])
    me_.attributes.remove(me_.attributes['skin'])
    for im in (im_shaft, im_tip):
        bpy.data.images.remove(im)
    print('baked', BS)
    bpy.ops.export_scene.gltf(filepath=str(output), export_format='GLB', export_apply=False, export_yup=True, export_skins=True, export_animations=True, export_morph=True, export_all_influences=False, export_extras=True)
    _common.body_meshes_first(output)
    return {
        'status': 'applied', 'reason': '', 'size_factor': size_factor,
        'protrusion_mm': protrusion, 'flattened_vertices': flat,
        'reweighted_vertices': moved, 'part_tris': sum(len(poly.vertices) - 2 for poly in partobj.data.polygons),
        'skin_patch_px': S_, 'skin_patch_cm': S_ * mpp * 100,
        'tip_vertices': tip_count,
        'border_vertices': len(final_border),
        'cracked_seam_groups': int(seam_cracks), 'flatten_outward_m': flatten_outward,
    }


def attached_part(args):
    """Runner entry. A failed build has no output, so the staged body survives."""
    groups = [g for g in args['params'].get('groups', []) if g.get('enabled', True)]
    parts = [g for g in groups if g['op'] == 'attached_part']
    companions = [g for g in groups if g['op'] == 'attached_part_bone']
    if len(parts) != 1:
        raise ValueError('Exactly one attached part group is required')
    _common.reset_scene()
    _common.import_model(args['inputs']['model'])
    output = Path(args['out_dir']) / 'model.glb'
    metrics = build_part(parts[0], companions, output)
    per_group = {parts[0]['id']: metrics}
    for companion in companions:
        per_group[companion['id']] = {'status': 'applied', 'reason': ''}
    return {'status': 'applied', 'reason': '', 'metrics': per_group, 'groups': per_group}, {'model': str(output)}


if __name__ == '__main__':
    _common.main(attached_part)
