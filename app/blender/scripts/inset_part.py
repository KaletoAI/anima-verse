"""Replace body skin with a welded, textured recessed part.

World metres, front -Y and up +Z. Source weights and corner UVs are interpolated
before the displaced patch is baked and joined back into the body.
"""
import copy
import math
import sys
from pathlib import Path

_SCRIPT_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPT_DIR)
import _common
from attached_part import resolve_bone
sys.path.remove(_SCRIPT_DIR)
import bpy
import bmesh
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

DEFAULTS = {
    'anchor_bone': 'Hips',
    'center_drop': .08,          # chart centre below the anchor head
    'theta': [-70, 170],         # profile angles (0 front, 90 down, 180 back)
    'anchor_drop': .105,         # s=0 reference: front midline point this far below the Hips head
    'shift': .046,               # the whole shape moves this far along the surface toward the back
    'region': {'s0': -.045, 's1': .13, 'u': .032, 'fall': .012},
    'eps': 0.0, 'sink': 0.0,
    'mound': {'s': -.02, 'amp': .003, 'ss': .022, 'su': .03},
    'ridges': {'s0': -.006, 's1': .108, 'ramp': .02, 'amp': .0055, 'w0': .007, 'w1': .013, 'sig': .007},
    'cleft': {'s0': 0., 's1': .10, 'ramp': .008, 'depth': .009, 'hw0': .0014, 'hw1': .006, 'shape': .7, 'pow': 1.0},
    'inner': {'s0': .018, 's1': .094, 'ramp': .014, 'w': .45, 'sig': .0013, 'rise': .55},
    'inner_scale': 0.0,          # 0 = inner folds inside the cleft, 1 = wider and protruding past the outer ridges
    'hood': {'s': .004, 'ss': .0045, 'su': .0035, 'fill': .75},
    'nub': {'s': .013, 'ss': .0034, 'su': .003, 'fill': .95},
    'nub_scale': .5,             # 0 = just below the rim, 1 = 1.5x larger and standing out past the ridges
    'pocket': {'s0': .048, 's1': .094, 'hw': .0022, 'depth': .02, 'pow': .5},
    'tone': {'ridge': [.97, .9, .88], 'inner': [.82, .56, .6], 'folds': [.9, .66, .7], 'nub': [.92, .62, .66], 'pocket': [.45, .22, .26], 'centre': [.96, .9, .9]},
    'edge': [.0007, .0022, .005], 'bake': 512,
}


def parameters(raw):
    """Merge nested overrides, rejecting unknown keys and degenerate profiles."""
    def merge(default, value, name):
        if isinstance(default, dict):
            if not isinstance(value, dict) or set(value) - set(default):
                raise ValueError('Unknown or malformed parameter: ' + name)
            return {k: merge(v, value[k], name + '.' + k) if k in value else copy.deepcopy(v)
                    for k, v in default.items()}
        if isinstance(default, list):
            if not isinstance(value, list) or len(value) != len(default):
                raise ValueError('Invalid vector length: ' + name)
            return [merge(d, v, name + '[]') for d, v in zip(default, value)]
        if isinstance(default, str):
            if not isinstance(value, str) or not value.strip():
                raise ValueError('Expected bone name: ' + name)
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Expected finite number: ' + name)
        return value
    p = merge(DEFAULTS, raw, 'params')
    if not all(0 <= p[k] <= 1 for k in ('inner_scale', 'nub_scale')):
        raise ValueError('Scales must be between zero and one')
    if not isinstance(p['bake'], int) or p['bake'] <= 0:
        raise ValueError('Bake size must be a positive integer')
    if not -180 <= p['theta'][0] < p['theta'][1] <= 180:
        raise ValueError('Invalid theta interval')
    for section in ('region', 'ridges', 'cleft', 'inner', 'pocket'):
        if p[section]['s0'] >= p[section]['s1']:
            raise ValueError('Invalid interval: ' + section)
    positive = {'region': ('u', 'fall'), 'mound': ('ss', 'su'),
                'ridges': ('ramp', 'w0', 'w1', 'sig'),
                'cleft': ('ramp', 'depth', 'hw0', 'hw1', 'shape', 'pow'),
                'inner': ('ramp', 'w', 'sig'), 'hood': ('ss', 'su'),
                'nub': ('ss', 'su'), 'pocket': ('hw', 'depth', 'pow')}
    for section, keys in positive.items():
        if any(p[section][k] <= 0 for k in keys):
            raise ValueError('Expected positive length or profile exponent: ' + section)
    if min(p['edge']) <= 0 or min(p['center_drop'], p['anchor_drop']) <= 0:
        raise ValueError('Expected positive chart lengths')
    if min(p['eps'], p['sink'], p['mound']['amp'], p['ridges']['amp'], p['inner']['rise'],
           p['hood']['fill'], p['nub']['fill']) < 0:
        raise ValueError('Expected nonnegative profile height')
    if min(p['tone']['inner']) <= 0:
        raise ValueError('Inner tint channels must be positive')
    if any(v < 0 for tone in p['tone'].values() for v in tone):
        raise ValueError('Expected nonnegative tint multiplier')
    return p


def build_part(group, output):
    """Build the accepted midline field, bake its texture and weld its border."""
    P = parameters(group.get('params', {}))
    arms = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
    if len(arms) != 1 or abs(bpy.context.scene.unit_settings.scale_length - 1) > 1e-6:
        raise ValueError('Requires one armature and metre scene units')
    arm = arms[0]
    body = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and o.vertex_groups and not o.get('attached_part'))
    if not body.data.uv_layers.active:
        raise ValueError('Body requires a UV map')
    M = body.matrix_world.copy(); Mi = M.inverted(); N3 = M.to_3x3(); Ni3 = Mi.to_3x3()
    hips = arm.matrix_world @ resolve_bone(arm.pose.bones, P['anchor_bone']).head
    xm = hips.x
    c = Vector((xm, hips.y, hips.z - P['center_drop']))
    dg = bpy.context.evaluated_depsgraph_get()
    bvh = BVHTree.FromObject(body, dg)

    # Midline profile from rays in the yz plane through the chart centre.
    th = np.radians(np.arange(P['theta'][0], P['theta'][1] + .01, .5))
    prof = []
    for t in th:
        d = Vector((0, -math.cos(t), -math.sin(t)))
        h = bvh.ray_cast(Mi @ c, Ni3 @ d)
        if h[0] is None:
            raise ValueError('Profile ray missed at %.1f' % math.degrees(t))
        prof.append(M @ h[0])
    prof = np.array([tuple(p) for p in prof])
    S = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(prof[:, 1:], axis=0), axis=1))])
    low = int(np.argmin(prof[:, 2]))
    anc = int(np.argmax(prof[:, 2] <= hips.z - P['anchor_drop']))
    S = S - S[anc] - P['shift']
    print('anchor', [round(x, 3) for x in prof[anc]], 'theta', round(math.degrees(th[anc]), 1), 'low at s', round(float(S[low]), 3))
    print('profile low', [round(x, 3) for x in prof[low]], 'theta', round(math.degrees(th[low]), 1), 'hips', [round(x, 3) for x in hips])
    for s_ in (-.04, -.019, 0, .03, .068, .09):
        i = int(np.argmin(np.abs(S - s_)))
        print('  s %+.3f -> y %.3f z %.3f theta %.0f' % (s_, prof[i, 1], prof[i, 2], math.degrees(th[i])))


    def chart(Q):
        """(s, u, radial offset) of world points Q (n,3)."""
        dy, dz = Q[:, 1] - c.y, Q[:, 2] - c.z
        t = np.arctan2(-dz, -dy)
        t = np.where(t < np.radians(P['theta'][0]) - .5, t + 2 * np.pi, t)
        s = np.interp(t, th, S)
        r = np.hypot(dy, dz) - np.interp(t, th, np.hypot(prof[:, 1] - c.y, prof[:, 2] - c.z))
        return s, Q[:, 0] - xm, r


    sstep = lambda x: (lambda y: y * y * (3 - 2 * y))(np.clip(x, 0, 1))


    def window(s, s0, s1, ramp):
        return sstep((s - s0) / ramp) * sstep((s1 - s) / ramp)


    def fields(s, u, facing, r):
        R = P['region']
        W = np.minimum(R['u'], np.interp(s, WS, WA))
        m = window(s, R['s0'], R['s1'], R['fall']) * sstep((W - np.abs(u)) / (.45 * W)) * sstep((.03 - np.abs(r)) / .01)
        mo = P['mound']
        mound = mo['amp'] * np.exp(-((s - mo['s']) / mo['ss']) ** 2 - (u / mo['su']) ** 2)
        rg = P['ridges']
        k = np.clip((s - rg['s0']) / (rg['s1'] - rg['s0']), 0, 1)
        w = rg['w0'] + (rg['w1'] - rg['w0']) * np.sin(np.pi * k)
        ridge_n = window(s, rg['s0'], rg['s1'], rg['ramp']) * np.exp(-((np.abs(u) - w) / rg['sig']) ** 2)
        ridge = rg['amp'] * ridge_n
        cl = P['cleft']
        k = np.clip((s - cl['s0']) / (cl['s1'] - cl['s0']), 0, 1)
        hw = cl['hw0'] + (cl['hw1'] - cl['hw0']) * np.sin(np.pi * k) ** cl['shape']
        gn = window(s, cl['s0'], cl['s1'], cl['ramp']) * np.clip(1 - (u / hw) ** 2, 0, 1) ** cl['pow']
        ip, isc = P['inner'], P['inner_scale']
        inner_n = window(s, ip['s0'], ip['s1'], ip['ramp']) * np.exp(-((np.abs(u) - ip['w'] * hw * (1 + .3 * isc)) / (ip['sig'] * (1 + 1.2 * isc))) ** 2)
        rise = ip['rise'] + .95 * isc
        hd = P['hood']
        hood_n = np.exp(-((s - hd['s']) / hd['ss']) ** 2 - (u / hd['su']) ** 2)
        env = P['eps'] + mound + ridge
        h_env = -P['sink'] + (P['sink'] + env) * m
        nb = P['nub']
        nsc = P['nub_scale']
        nub_n = np.exp(-((s - nb['s']) / (nb['ss'] * (1 + .5 * nsc))) ** 2 - (u / (nb['su'] * (1 + .5 * nsc))) ** 2)
        pk = P['pocket']
        ks = np.clip((s - pk['s0']) / (pk['s1'] - pk['s0']), 0, 1)
        phw = pk['hw'] * np.sqrt(np.clip(1 - (2 * ks - 1) ** 2, 0, 1))
        pocket_n = np.clip(1 - (u / np.maximum(phw, 1e-6)) ** 2, 0, 1) ** pk['pow'] * (phw > 1e-5)
        fill = np.maximum(hd['fill'] * hood_n, (nb['fill'] + .4 * nsc) * nub_n)
        h = h_env - cl['depth'] * gn * (1 - rise * inner_n) * (1 - fill) - pk['depth'] * pocket_n * gn
        return dict(m=m, h_env=h_env, h=h, groove=gn, ridge=ridge_n, folds=gn * np.maximum(inner_n, hood_n),
                    nub=gn * nub_n, pocket=pocket_n * gn,
                    centre=window(s, cl['s0'] - .01, cl['s1'] + .005, .01) * np.exp(-(u / .012) ** 2))


    # Body positions, normals, seam groups.
    body.data.calc_loop_triangles()
    V = np.array([tuple(M @ v.co) for v in body.data.vertices])
    Nn = np.array([tuple((N3 @ v.normal).normalized()) for v in body.data.vertices])
    key = {}
    for i, p in enumerate(V):
        key.setdefault(tuple(np.round(p / 1e-5).astype(int)), []).append(i)
    # Split seam copies carry one-sided normals; use the group's mean.
    for grp in key.values():
        if len(grp) > 1:
            n = Nn[grp].sum(0)
            Nn[grp] = n / (np.linalg.norm(n) + 1e-12)
    s_b, u_b, r_b = chart(V)
    rad = np.stack([np.zeros(len(V)), V[:, 1] - c.y, V[:, 2] - c.z], 1)
    rad /= np.linalg.norm(rad, axis=1)[:, None] + 1e-12
    fac_b = np.einsum('ij,ij->i', Nn, rad)
    # Usable half width per s: distance from the midline to where the skin turns sideways at the legs.
    WS = np.arange(P['region']['s0'] - .03, P['region']['s1'] + .03, .004)
    WA = []
    for s_ in WS:
        sel = (np.abs(s_b - s_) < .004) & (np.abs(r_b) < .03) & (np.abs(u_b) < .06)
        side = []
        for sg in (1, -1):
            turn = sel & (sg * u_b > 0) & (fac_b < .5)
            side.append(np.min(sg * u_b[turn]) if turn.any() else .06)
        WA.append(min(side))
    WA = np.convolve(np.pad(WA, 2, mode='edge'), np.ones(5) / 5, mode='valid')
    print('usable half width mm', [(round(a_, 3), round(w_ * 1000, 1)) for a_, w_ in zip(WS[::3], WA[::3])])
    F = fields(s_b, u_b, fac_b, r_b)
    R = P['region']
    near = (s_b > R['s0'] - R['fall'] - .01) & (s_b < R['s1'] + R['fall'] + .01) & (np.abs(u_b) < R['u'] + R['fall'] + .01) & (np.abs(r_b) < .04)
    near &= np.abs(u_b) < np.interp(s_b, WS, WA) + .01
    print('patch body verts', int(near.sum()))

    # Patch copy: body faces whose vertices are all near; welded, interior edges subdivided.
    bm = bmesh.new()
    uvname = body.data.uv_layers.active.name
    uvsrc = body.data.uv_layers.active.data
    fidx = [t for t in body.data.loop_triangles if all(near[v] for v in t.vertices)]
    sel_polys = {t.polygon_index for t in fidx}
    if not fidx:
        raise ValueError('No body triangles in inset region')
    vmap = {}
    for t in fidx:
        for v in t.vertices:
            if v not in vmap:
                vmap[v] = bm.verts.new(V[v])
    for t in fidx:
        try:
            bm.faces.new([vmap[v] for v in t.vertices])
        except ValueError:
            pass
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5)
    _bv = [v for v in bm.verts if v.is_boundary]
    from mathutils.kdtree import KDTree
    _kd = KDTree(len(V))
    for _i, _p in enumerate(V):
        _kd.insert(Vector(_p), _i)
    _kd.balance()
    _bi = [_kd.find(v.co)[1] for v in _bv]
    _bf = fields(s_b[_bi], u_b[_bi], fac_b[_bi], r_b[_bi])
    print('patch border verts', len(_bv), 'max m', round(float(_bf['m'].max()), 3), 'max |h| mm', round(float(np.abs(_bf['h']).max()) * 1000, 2))


    def target_edge(p):
        s_, u_, _ = chart(np.array([tuple(p)]))
        cl = P['cleft']
        if cl['s0'] - .01 < s_[0] < cl['s1'] + .01 and abs(u_[0]) < cl['hw1'] + .004:
            return P['edge'][0]
        if abs(u_[0]) < P['ridges']['w1'] + 2 * P['ridges']['sig']:
            return P['edge'][1]
        return P['edge'][2]


    for _ in range(5):
        long_ = [e for e in bm.edges if not e.is_boundary and e.calc_length() > target_edge((e.verts[0].co + e.verts[1].co) / 2)]
        if not long_:
            break
        # Split marked triangle edges explicitly. Selective grid subdivision can
        # produce duplicate thin faces in Blender; these templates stay conforming.
        midpoints = {frozenset(e.verts): bm.verts.new((e.verts[0].co + e.verts[1].co) / 2) for e in long_}
        triangles = []
        for face in list(bm.faces):
            vertices = list(face.verts)
            splits = [midpoints.get(frozenset((vertices[i], vertices[(i + 1) % 3]))) for i in range(3)]
            count = sum(v is not None for v in splits)
            if not count:
                continue
            # Rotate until the first edge is split, and for two splits the next
            # edge is split too. This gives one template per edge count.
            index = next(i for i in range(3) if splits[i] is not None and
                         (count != 2 or splits[(i + 1) % 3] is not None))
            a, b, d = vertices[index:] + vertices[:index]
            m, n, q = splits[index:] + splits[:index]
            if count == 1:
                triangles.extend(((a, m, d), (m, b, d)))
            elif count == 2:
                triangles.extend(((b, n, m), (a, m, d), (m, n, d)))
            else:
                triangles.extend(((a, m, q), (m, b, n), (q, n, d), (m, n, q)))
            bm.faces.remove(face)
        for triangle in triangles:
            bm.faces.new(triangle)
        for edge in list(bm.edges):
            if not edge.link_faces:
                bm.edges.remove(edge)
        print('  subdiv', len(long_), 'edges ->', len(bm.faces), 'tris')
    patch_tris = len(bm.faces)
    print('patch tris', patch_tris)
    bm.verts.ensure_lookup_table()
    bm.verts.index_update()
    Q = np.array([tuple(v.co) for v in bm.verts])
    border = np.array([v.is_boundary for v in bm.verts])
    gname = {g.index: g.name for g in body.vertex_groups}
    VW = [{gname[g.group]: g.weight for g in v.groups} for v in body.data.vertices]
    qn, qw = [], []
    for p in Q:
        loc, _, fi, _ = bvh.find_nearest(Mi @ Vector(p))
        vs = list(body.data.polygons[fi].vertices)
        A, B, C_ = (Vector(V[v]) for v in vs[:3])
        bc = barycentric_transform(M @ loc, A, B, C_, Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
        bc = np.clip(np.array(bc), 0, None); bc /= bc.sum() or 1
        n = sum((Vector(Nn[v]) * bc[k] for k, v in enumerate(vs[:3])), Vector()).normalized()
        w = {}
        for k, v in enumerate(vs[:3]):
            for g, x in VW[v].items():
                w[g] = w.get(g, 0) + x * bc[k]
        qn.append(tuple(n)); qw.append(w)
    qn = np.array(qn)
    s_q, u_q, r_q = chart(Q)
    rq = np.stack([np.zeros(len(Q)), Q[:, 1] - c.y, Q[:, 2] - c.z], 1)
    rq /= np.linalg.norm(rq, axis=1)[:, None] + 1e-12
    FQ = fields(s_q, u_q, np.einsum('ij,ij->i', qn, rq), r_q)
    hq = np.where(border, 0.0, FQ['h'])
    for v, p in zip(bm.verts, Q + qn * hq[:, None]):
        v.co = Vector(p)
    # Source UVs per corner from the corner's own source face plane (seams keep their sides).
    uvl = bm.loops.layers.uv.new('body')
    for f in bm.faces:
        cen = sum((Vector(Q[l.vert.index]) for l in f.loops), Vector()) / 3
        _, _, fi, _ = bvh.find_nearest(Mi @ cen)
        poly = body.data.polygons[fi]
        vs = [Vector(V[v]) for v in poly.vertices[:3]]
        uvs = [Vector((*uvsrc[li].uv, 0)) for li in poly.loop_indices[:3]]
        for l in f.loops:
            uv = barycentric_transform(Vector(Q[l.vert.index]), *vs, *uvs)
            l[uvl].uv = (uv.x, uv.y)
    me = bpy.data.meshes.new('Part')
    bm.to_mesh(me); bm.free()
    part = bpy.data.objects.new('Part', me)
    bpy.context.scene.collection.objects.link(part)
    part.matrix_world = M
    for vtx in me.vertices:
        vtx.co = Mi @ vtx.co
    T = P['tone']
    lin = lambda k: np.array(k) ** 2.2
    tint = (1 - FQ['centre'][:, None] * (1 - lin(T['centre']))) * (1 - FQ['ridge'][:, None] * (1 - lin(T['ridge']))) * (1 - np.clip(FQ['groove'] * 1.4, 0, 1)[:, None] * (1 - lin(T['inner']))) * (1 - np.clip(FQ['folds'], 0, 1)[:, None] * (1 - lin(T['folds']) / lin(T['inner'])).clip(-1, 1))
    tint *= (1 - np.clip(FQ['nub'], 0, 1)[:, None] * (1 - lin(T['nub']) / lin(T['inner'])).clip(-1, 1))
    tint *= (1 - np.clip(FQ['pocket'] * 1.5, 0, 1)[:, None] * (1 - lin(T['pocket'])))
    tint[border] = 1
    ca = me.color_attributes.new('Tint', 'FLOAT_COLOR', 'POINT')
    for i, t in enumerate(tint):
        ca.data[i].color = (*t, 1)
    for i, w in enumerate(qw):
        for g, x in w.items():
            if x > 0:
                vg = part.vertex_groups.get(g) or part.vertex_groups.new(name=g)
                vg.add([i], x, 'REPLACE')
    for poly in me.polygons:
        poly.use_smooth = True

    # Bake body texture x tint onto an own UV map, on the separate patch object.
    bpy.context.view_layer.objects.active = part
    for o in bpy.context.scene.objects:
        o.select_set(o is part)
    bake_uv = me.uv_layers.new(name='bake')
    me.uv_layers.active = bake_uv
    bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=1.4, island_margin=.01)
    bpy.ops.object.mode_set(mode='OBJECT')
    img = next(nd.inputs['Base Color'].links[0].from_node.image for nd in body.active_material.node_tree.nodes if nd.type == 'BSDF_PRINCIPLED')
    bimg = bpy.data.images.new('part_baked', P['bake'], P['bake'], alpha=False)
    bimg.generated_color = (.8, .65, .6, 1)
    mat = bpy.data.materials.new('part_bake')
    mat.use_nodes = True
    mat['attached_part'] = group['id']
    nt = mat.node_tree; nt.nodes.clear(); Nd = nt.nodes.new
    out = Nd('ShaderNodeOutputMaterial'); emit = Nd('ShaderNodeEmission')
    uvn = Nd('ShaderNodeUVMap'); uvn.uv_map = 'body'
    tex = Nd('ShaderNodeTexImage'); tex.image = img
    att = Nd('ShaderNodeAttribute'); att.attribute_name = 'Tint'
    mul = Nd('ShaderNodeMix'); mul.data_type = 'RGBA'; mul.blend_type = 'MULTIPLY'; mul.inputs['Factor'].default_value = 1
    nt.links.new(uvn.outputs['UV'], tex.inputs['Vector'])
    nt.links.new(tex.outputs['Color'], mul.inputs[6]); nt.links.new(att.outputs['Color'], mul.inputs[7])
    nt.links.new(mul.outputs[2], emit.inputs['Color']); nt.links.new(emit.outputs['Emission'], out.inputs['Surface'])
    tb = Nd('ShaderNodeTexImage'); tb.image = bimg; nt.nodes.active = tb
    me.materials.append(mat)
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'; sc.cycles.device = 'CPU'; sc.cycles.samples = 1; sc.render.bake.margin = 24
    bpy.ops.object.bake(type='EMIT')
    bimg.pack()
    nt.nodes.clear()
    out = Nd('ShaderNodeOutputMaterial'); bsdf = Nd('ShaderNodeBsdfPrincipled'); tb = Nd('ShaderNodeTexImage'); tb.image = bimg
    nt.links.new(tb.outputs['Color'], bsdf.inputs['Base Color']); nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    bsdf.inputs['Roughness'].default_value = .55
    me.uv_layers.remove(me.uv_layers['body'])
    me.uv_layers['bake'].name = uvname
    while me.color_attributes:
        me.color_attributes.remove(me.color_attributes[0])

    # Replace the region faces of the body and weld the patch in.
    _bmp = bmesh.new(); _bmp.from_mesh(me)
    part_border_local = [v.co.copy() for v in _bmp.verts if v.is_boundary]
    _bmp.free()
    bmb = bmesh.new(); bmb.from_mesh(body.data); bmb.faces.ensure_lookup_table()
    bmesh.ops.delete(bmb, geom=[bmb.faces[i] for i in sel_polys], context='FACES')
    bmb.to_mesh(body.data); bmb.free()
    for o in bpy.context.scene.objects:
        o.select_set(o in (body, part))
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    bmb = bmesh.new(); bmb.from_mesh(body.data)
    pkeys = {tuple(np.round(np.array(v) / 1e-5).astype(int)) for v in part_border_local}
    edge_verts = [v for v in bmb.verts if v.is_boundary and tuple(np.round(np.array(v.co) / 1e-5).astype(int)) in pkeys]
    n0 = len(bmb.verts)
    bmesh.ops.remove_doubles(bmb, verts=edge_verts, dist=2e-6)
    print('welded', n0 - len(bmb.verts), 'border verts')
    bmb.to_mesh(body.data); bmb.free()
    open_left = 0
    bmb = bmesh.new(); bmb.from_mesh(body.data)
    mi_part = len(body.data.materials) - 1
    for e in bmb.edges:
        if e.is_boundary and any(f.material_index == mi_part for f in e.link_faces):
            open_left += 1
    bmb.free()
    print('open patch border edges after weld', open_left, 'part material', body.data.materials[mi_part].name, 'body tris', len(body.data.polygons))

    bpy.ops.export_scene.gltf(filepath=str(output), export_format='GLB', export_apply=False,
                              export_yup=True, export_skins=True, export_animations=True,
                              export_morph=True, export_extras=True, export_all_influences=False)
    _common.body_meshes_first(output)
    return {'status': 'applied', 'reason': '', 'anchor': prof[anc].tolist(),
            'patch_tris': patch_tris,
            'border_vertices': int(border.sum()), 'open_border_edges': open_left,
            'border_max_abs_h': float(np.abs(hq[border]).max()) if border.any() else 0.,
            'usable_half_width': float(np.interp((P['cleft']['s0'] + P['cleft']['s1']) / 2, WS, WA)),
            'inner_scale': P['inner_scale'], 'nub_scale': P['nub_scale']}


def inset_part(args):
    """Runner entry; failures leave the caller's staged body untouched."""
    groups = [g for g in args['params'].get('groups', []) if g.get('enabled', True) and g['op'] == 'inset_part']
    if len(groups) != 1:
        raise ValueError('Exactly one inset part group is required')
    _common.reset_scene()
    _common.import_model(args['inputs']['model'])
    output = Path(args['out_dir']) / 'model.glb'
    metrics = build_part(groups[0], output)
    per_group = {groups[0]['id']: metrics}
    return {'status': 'applied', 'reason': '', 'metrics': per_group, 'groups': per_group}, {'model': str(output)}


if __name__ == '__main__':
    _common.main(inset_part)
