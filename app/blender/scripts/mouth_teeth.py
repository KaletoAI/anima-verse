"""The teeth, gums and tongue of a built mouth channel (Ruling A206; step 7 of ``mouth_part.build``).

World metres, the frame of ``mouth_part``: O = the opening's centre on the lip line, ``axis`` into the head along
the channel, ``lateral`` the body's side axis, ``up`` = lateral x axis (the channel's normal, upward). Heights are
taken against the pouch's MIDDLE SURFACE (where both walls lie at rest), ``mid(x, d)``.

1. THE ARCHES (``mouth_math.arch_curve``): the labial line of each arch follows the channel's cross-section with
   ``margin`` to each side; its front is a parabola reaching ``front_w`` at ``front_l`` behind the midline. The
   upper arch starts ``front`` behind the opening, the lower one ``lower_back`` further back.
2. THE TEETH: per arch and side the five teeth of ``mouth_math.UPPER_TEETH`` / ``LOWER_TEETH`` side by side along
   the arch, then a molar block, all scaled by ``mouth_math.teeth_scale`` (mouth width x the character's ``size``).
   A tooth is a rounded wedge: rings (superellipses across its width and thickness) from the incisal tip to its
   neck, profile per kind (incisor = edge, canine = point, premolar / molar = rounded block), closed at the tip by
   a fan, the neck end open inside the gum. The upper incisal edges lie ``upper_tip`` under the middle surface,
   the lower ones ``lower_tip`` over it (the overbite).
3. THE GUMS: per arch one closed band along the whole arch over the teeth's necks, ``gum.cover`` of the crown down
   and ``gum.root`` past the neck.
4. THE TONGUE (option): a cushion on the lower wall, behind the lower incisors, inside the lower arch;
   ``tongue.length`` x ``tongue.width`` x ``tongue.height`` (scaled), its tip thinner. Only its top is built
   (the lower wall carries it).
5. BINDING: upper teeth and gum weight exactly 1.0 on Head, lower ones exactly 1.0 on the jaw bone (rigid, both
   turn about the same hinge as the lower wall); the tongue copies the weights of the nearest lower-wall vertex.
6. MATERIALS: ``mouth_teeth`` (teeth and gums, colours as vertex colours ``Color``, slightly glossy) and
   ``mouth_tongue`` (flat colour). Two materials so the renderers' opening pass can leave the rigid teeth alone
   and still push the tongue (``channelOpening.ts``). Every vertex of the body gets the colour attribute; the skin's
   is white (no change where an exporter writes it).
7. CLEARANCE: at rest every new vertex must lie inside the outer skin (the faces seen from the front, from 45
   degrees to each side and from 30 degrees below) by at least ``clearance``. A vertex too close is pushed back
   along the axis until it is (at most ``push_max``); then every face's centre and edge midpoints are held to half
   the clearance the same way (a flat face spans the concave fold under the lower lip although its corners keep it);
   what still fails is reported, not hidden.

``build_teeth`` returns the metrics; it raises on failure, before anything was added to the body, so the caller
publishes the mouth without teeth.
"""
import math

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

from mouth_math import (LOWER_MOLAR, LOWER_TEETH, UPPER_MOLAR, UPPER_TEETH, _sstep, arch_curve, channel_half_width,
                        teeth_gap, teeth_scale, tooth_spans, turned)

TEETH_MATERIAL = 'mouth_teeth'
TONGUE_MATERIAL = 'mouth_tongue'
COLOR_ATTRIBUTE = 'Color'

DEFAULTS = {
    'enabled': True, 'tongue': True, 'shade': 1, 'size': 1.,
    'front': .0045, 'lower_back': .002, 'upper_tip': .0015, 'lower_tip': .0005, 'margin': .003,
    'front_w': .018, 'front_l': .011,
    'gum': {'cover': .22, 'root': .0015, 'out': .0006},
    'tongue_size': {'length': .045, 'width': .030, 'height': .006, 'tip': .0025, 'behind': .002, 'inset': .004},
    'clearance': .0015, 'push_max': .01, 'front_max': .004,
}
#: Linear tooth colours of the three shades (bright, natural, ivory), the gum's and the tongue's.
SHADES = ((.75, .74, .68), (.62, .58, .48), (.55, .47, .33))
GUM_RGB = (.38, .08, .09)
TONGUE_RGB = (.33, .07, .08)

# Per kind: ring parameters t (0 tip .. 1 neck .. past it into the gum), width and thickness fractions per ring,
# the fan centre's drop past the tip (m), the superellipse exponent and the crown's tilt (degrees, neck inward).
PROFILES = {
    'incisor': {'t': (0., .08, .4, 1., 1.15), 'w': (.92, 1., .97, .72, .65), 'b': (.18, .32, .7, 1., .95),
                'tip': .0002, 'e': 2.2, 'tilt': 15.},
    'canine': {'t': (0., .08, .4, 1., 1.15), 'w': (.25, .55, .95, .72, .65), 'b': (.3, .5, .85, 1., .95),
               'tip': .0006, 'e': 2.2, 'tilt': 8.},
    'premolar': {'t': (0., .1, .6, 1.15), 'w': (.7, .95, 1., .8), 'b': (.65, .92, 1., .85),
                 'tip': .0004, 'e': 2.4, 'tilt': 4.},
    'molar': {'t': (0., .1, .6, 1.15), 'w': (.75, .97, 1., .85), 'b': (.7, .95, 1., .85),
              'tip': .0003, 'e': 2.5, 'tilt': 2.},
}
#: Ring points per tooth: the upper front teeth get the most (they are what an open mouth shows).
RING_POINTS = {('upper', 'front'): 10, ('lower', 'front'): 8, ('upper', 'back'): 8, ('lower', 'back'): 8}
GUM_SAMPLES = 13            # per half arch
TONGUE_GRID = (8, 7)        # along x across


def options(raw):
    """The character's teeth options merged over ``DEFAULTS``: ``enabled`` / ``tongue`` booleans, ``shade`` 0..2,
    ``size`` within [0.8, 1.2]. ValueError otherwise."""
    out = {k: v for k, v in DEFAULTS.items()}
    for key, value in (raw or {}).items():
        if key in ('enabled', 'tongue'):
            if type(value) is not bool:
                raise ValueError('Teeth: %s must be a boolean' % key)
        elif key == 'shade':
            if type(value) is not int or not 0 <= value <= 2:
                raise ValueError('Teeth: shade must be 0, 1 or 2')
        elif key == 'size':
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not .8 <= value <= 1.2:
                raise ValueError('Teeth: size must be within [0.8, 1.2]')
            value = float(value)
        else:
            raise ValueError('Teeth: unknown option ' + key)
        out[key] = value
    return out


def _superellipse(n, e):
    a = np.linspace(0, 2 * math.pi, n, endpoint=False) + math.pi / n
    c, s = np.cos(a), np.sin(a)
    return np.sign(c) * np.abs(c) ** (2 / e), np.sign(s) * np.abs(s) ** (2 / e)


class _Mesh:
    """Positions (world), triangles, per-vertex part ('upper' / 'lower' / 'tongue') and colour."""

    def __init__(self):
        self.P, self.F, self.part, self.rgb, self.kind, self.front = [], [], [], [], [], []

    def vert(self, p, part, rgb, kind, front=False):
        self.front.append(front)
        self.P.append(np.asarray(p, float))
        self.part.append(part)
        self.rgb.append(rgb)
        self.kind.append(kind)
        return len(self.P) - 1

    def tri(self, a, b, c, flip=False):
        # Base winding (a, c, b): the loops below run so that this faces outward.
        self.F.append((a, b, c) if flip else (a, c, b))


def build_teeth(ctx, raw_options):
    """Add teeth, gums and (optionally) the tongue to ``ctx['body']`` (module docstring). Returns the metrics with
    ``teeth_gap``; raises before touching the body when anything fails."""
    opt = options(raw_options)
    O, axis, lateral, up = (np.asarray(ctx[k], float) for k in ('O', 'axis', 'lateral', 'up'))
    widest, R, D = ctx['widest'], ctx['R'], ctx['D']
    taper, flatten = ctx['taper'], ctx['flatten']
    across_sorted, rest_up = ctx['across_sorted'], ctx['rest_up']
    f = teeth_scale(widest, opt['size'])

    def mid(x, d):
        widen = 1 + (R / widest - 1) * float(_sstep(d / taper))
        return float(np.interp(x / widen, across_sorted, rest_up)) * (1 - float(_sstep(d / flatten)))

    # The occlusal plane is LEVEL (the body's horizontal), not the channel's axis, which runs down toward the
    # throat: teeth placed along the axis stack below each other seen from the front. Teeth and gums rise by
    # ``level`` per metre of depth behind the upper arch's front; the tongue lies on the wall.
    level = max(0., -float(axis[2])) / max(1e-6, math.hypot(float(axis[0]), float(axis[1])))

    def world(x, d, h, from_d=None):
        rise = 0. if from_d is None else (d - from_d) * level
        return O + lateral * x + axis * d + up * (h + rise + mid(x, d))

    def limit(d):
        return channel_half_width(d, widest, R, taper) - opt['margin']

    shade = SHADES[opt['shade']]

    def generate(front):
        """The teeth, gums and tongue with the upper arch ``front`` behind the opening."""
        mesh = _Mesh()
        report = {'scale': round(f, 4), 'arches': {}}
        tips = {}
        for part, table, molar, d0, tip_h, sign in (
                ('upper', UPPER_TEETH, UPPER_MOLAR, front, -opt['upper_tip'], 1.),
                ('lower', LOWER_TEETH, LOWER_MOLAR, front + opt['lower_back'] * f, opt['lower_tip'], -1.)):
            widths = [w * f / 1000 for _k, w, _h, _t in table] + [molar[0] * f / 1000]
            heights = [h * f / 1000 for _k, _w, h, _t in table] + [molar[1] * f / 1000]
            thick = [t * f / 1000 for _k, _w, _h, t in table] + [molar[2] * f / 1000]
            kinds = [k for k, _w, _h, _t in table] + ['molar']
            x, d, s = arch_curve(d0, opt['front_w'] * f, opt['front_l'] * f, limit, D * .75)
            spans = tooth_spans(widths, float(s[-1]))
            if len(spans) < len(widths):
                raise ValueError('The %s arch is too short for its teeth (%.1f mm)' % (part, s[-1] * 1000))
            end = spans[-1][1]

            def at(sv):
                """Labial point (x, d) and the tangent / outward unit vectors in (lateral, axis) at arc length sv."""
                xv, dv = float(np.interp(sv, s, x)), float(np.interp(sv, s, d))
                e = .0005
                tx = float(np.interp(sv + e, s, x) - np.interp(max(sv - e, 0.), s, x))
                td = float(np.interp(sv + e, s, d) - np.interp(max(sv - e, 0.), s, d))
                n_ = math.hypot(tx, td) or 1.
                tx, td = tx / n_, td / n_
                return xv, dv, (tx, td), (td, -tx)

            tooth_count = 0
            for side in (1., -1.):
                for k, (a_, b_) in enumerate(spans):
                    prof = PROFILES[kinds[k]]
                    group = 'front' if k < 3 else 'back'
                    n_pts = RING_POINTS[(part, group)]
                    cu, cv = _superellipse(n_pts, prof['e'])
                    xc, dc, (tx, td), (ox, od) = at((a_ + b_) / 2)
                    half_w = (b_ - a_) * .97 / 2
                    H, T = heights[k], thick[k]
                    tilt = math.tan(math.radians(prof['tilt']))
                    rings = []
                    for t, wf, bf in zip(prof['t'], prof['w'], prof['b']):
                        bt = T / 2 * bf
                        back = tilt * H * t          # the labial face on the line at the tip, the neck inward
                        h = tip_h + sign * H * t
                        ring = []
                        for u_, v_ in zip(cu, cv):
                            inward = back + bt * (1 - v_)
                            lx = xc + tx * half_w * wf * u_ - ox * inward
                            ld = dc + td * half_w * wf * u_ - od * inward
                            ring.append(mesh.vert(world(side * lx, ld, h, front), part, shade, 'tooth', k < 3))
                        rings.append(ring)
                    # Tip fan: the centre of the first ring, a little past the tip.
                    centre = np.mean([mesh.P[i] for i in rings[0]], 0) - up * sign * prof['tip']
                    c_ = mesh.vert(centre, part, shade, 'tooth')
                    flip = (side < 0) != (sign < 0)
                    for j in range(n_pts):
                        mesh.tri(c_, rings[0][(j + 1) % n_pts], rings[0][j], flip)
                    for r0, r1 in zip(rings[:-1], rings[1:]):
                        for j in range(n_pts):
                            j1 = (j + 1) % n_pts
                            mesh.tri(r0[j], r0[j1], r1[j1], flip)
                            mesh.tri(r0[j], r1[j1], r1[j], flip)
                    tooth_count += 1
            # The gum: one closed band along the whole arch (both halves), over the necks.
            g = opt['gum']
            centres = [(a_ + b_) / 2 for a_, b_ in spans]

            def per_tooth(values, sv):
                return float(np.interp(sv, centres, values))

            samples = np.linspace(0., end, GUM_SAMPLES)
            loops = []
            for sv in list(-samples[::-1]) + list(samples[1:]):
                side = 1. if sv >= 0 else -1.
                xv, dv, _t, (ox, od) = at(abs(sv))
                H, T = per_tooth(heights, abs(sv)), per_tooth(thick, abs(sv))
                low = tip_h + sign * H * (1 - g['cover'])
                top = tip_h + sign * (H * 1.15 + g['root'])
                midh = (low + top) / 2
                lab, ling = g['out'], -(T + g['out'])
                bulge = g['out'] * .8
                profile = ((lab, low), (lab + bulge, midh), (lab, top), (ling, top), (ling - bulge * .5, midh), (ling, low))
                loops.append([mesh.vert(world(side * (xv + ox * o_), dv + od * o_, h, front), part, GUM_RGB, 'gum')
                              for o_, h in profile])
            flip = sign < 0
            for l0, l1 in zip(loops[:-1], loops[1:]):
                for j in range(6):
                    j1 = (j + 1) % 6
                    mesh.tri(l0[j], l0[j1], l1[j1], flip)
                    mesh.tri(l0[j], l1[j1], l1[j], flip)
            for loop, fl in ((loops[0], not flip), (loops[-1], flip)):
                for j in range(1, 5):
                    mesh.tri(loop[0], loop[j], loop[j + 1], fl)
            upper_tip_point = world(0., d0, tip_h, front)
            tips[part] = upper_tip_point
            report['arches'][part] = {'teeth': tooth_count, 'front_mm': round(d0 * 1000, 2),
                                      'half_width_back_mm': round(float(x[np.searchsorted(s, end) - 1]) * 1000, 2),
                                      'depth_back_mm': round(float(np.interp(end, s, d)) * 1000, 2),
                                      'arc_mm': round(end * 1000, 2)}
            if part == 'lower':
                report['lower_inner'] = (x, d, s, end, thick)

        # The tongue: on the lower wall's middle surface behind the lower incisors, inside the lower arch.
        if opt['tongue']:
            ts = opt['tongue_size']
            lx_, ld_, ls_, lend, lthick = report.pop('lower_inner')
            start = front + opt['lower_back'] * f + LOWER_TEETH[0][3] * f / 1000 + ts['behind']
            length = min(ts['length'] * f, D * .8 - start)
            nu, nv = TONGUE_GRID
            grid = []
            for i in range(nu):
                u = i / (nu - 1)
                dv = start + length * u
                inner = float(np.interp(dv, ld_, lx_)) - ts['inset']
                half = min(ts['width'] * f / 2, inner) * (.75 + .25 * math.sin(min(u / .25, 1.) * math.pi / 2))
                height = (ts['tip'] + (ts['height'] - ts['tip']) * float(_sstep(u / .5))) * f
                row = []
                for j in range(nv):
                    v = -1 + 2 * j / (nv - 1)
                    h = -.0005 + (height + .0005) * math.sqrt(max(0., 1 - v * v)) * (1 if 0 < i else .4)
                    row.append(mesh.vert(world(v * half, dv, h), 'tongue', TONGUE_RGB, 'tongue'))
                grid.append(row)
            for i in range(nu - 1):
                for j in range(nv - 1):
                    mesh.tri(grid[i][j], grid[i + 1][j], grid[i + 1][j + 1])
                    mesh.tri(grid[i][j], grid[i + 1][j + 1], grid[i][j + 1])
            report['tongue_mm'] = [round(length * 1000, 1), round(ts['width'] * f * 1000, 1), round(ts['height'] * f * 1000, 1)]
        else:
            report.pop('lower_inner')


        return mesh, report, tips, np.array(mesh.P), np.array(mesh.F), np.array(mesh.part), np.array(mesh.kind)

    # The front (module docstring 7): from ``front`` back in half millimetres until the incisors' and canines'
    # crowns keep the clearance (a lower lip set back from the lip line moves the arches back with it).
    skin = ctx['outer_skin']
    front = opt['front']
    while True:
        mesh, report, tips, P, F, part, kind = generate(front)
        crowns = [i for i in range(len(P)) if mesh.front[i]]
        if all(skin.inside(P[i], opt['clearance'])[0] for i in crowns) or front >= opt['front'] + opt['front_max']:
            break
        front += .0005
    report['front_moved_mm'] = round((front - opt['front']) * 1000, 2)

    # Clearance (module docstring 7) against the outer skin.
    pushed = 0
    pushed_at = []
    dist = np.empty(len(P))
    for i, p in enumerate(P):
        ok, d_ = skin.inside(p, opt['clearance'])
        if not ok:
            # Toward the middle surface first (a gum or a neck under the lip's fold gets shorter), then back.
            toward = up * (1. if part[i] != 'upper' else -1.)
            h0 = float((p - O) @ up)
            for step in np.arange(.0005, opt['push_max'] + 1e-9, .0005):
                for q in ((p + toward * min(step, abs(h0)), p + axis * step) if abs(h0) > 1e-4 else (p + axis * step,)):
                    ok, d_ = skin.inside(q, opt['clearance'])
                    if ok:
                        break
                if ok:
                    break
            if ok:
                pushed += 1
                pushed_at.append([kind[i], part[i]] + [round(float((P[i] - O) @ e) * 1000, 1) for e in (lateral, axis, up)]
                                 + [round(float(np.linalg.norm(q - P[i])) * 1000, 1), skin.why(P[i])])
                P[i] = q
        dist[i] = d_
    # A face spans between its vertices: where the skin is concave (the fold under the lower lip) a flat face can
    # cut through it although every vertex keeps the clearance. Its centre and edge midpoints are held to half the
    # clearance; a failing face moves as a whole, the same way as a vertex.
    def samples(f):
        c = P[list(f)]
        return [c.mean(0)] + [(c[k] + c[(k + 1) % len(c)]) / 2 for k in range(len(c))]

    face_pushed = 0
    for _round in range(3):
        moved = False
        for f in F:
            if all(skin.inside(q, opt['clearance'] / 2)[0] for q in samples(f)):
                continue
            i0 = int(f[0])
            toward = up * (1. if part[i0] != 'upper' else -1.)
            base = P[list(f)].copy()
            for step in np.arange(.0005, opt['push_max'] + 1e-9, .0005):
                for shift in (toward * step, axis * step):
                    P[list(f)] = base + shift
                    if all(skin.inside(q, opt['clearance'] / 2)[0] for q in samples(f)):
                        break
                else:
                    continue
                break
            else:
                P[list(f)] = base
                continue
            face_pushed += 1
            moved = True
        if not moved:
            break
    face_bad = sum(1 for f in F if not all(skin.inside(q, 0.)[0] for q in samples(f)))
    dist = np.array([skin.inside(p, opt['clearance'])[1] for p in P])
    covered = np.array([skin.inside(p, 0.)[0] for p in P])
    bad = np.nonzero((dist < opt['clearance'] - 1e-6) | ~covered)[0]
    report['pushed_at'] = pushed_at
    report['failing'] = [[kind[i], part[i]] + [round(float((P[i] - O) @ e) * 1000, 1) for e in (lateral, axis, up)]
                         + [round(float(dist[i]) * 1000, 2)] for i in bad[:20]]
    report['clearance'] = {'min_mm': round(float(dist.min()) * 1000, 2), 'pushed_vertices': pushed,
                           'below_clearance': int((dist < opt['clearance'] - 1e-6).sum()),
                           'uncovered': int((~covered).sum()), 'pushed_faces': face_pushed,
                           'faces_uncovered': face_bad}

    # The free height between the incisal edges with the mouth fully open.
    # From the incisal tips (the hand formula) and from the built crowns within 4 mm of the midline (the lowest upper
    # point against the highest lower point turned open): the smaller is reported — a crown's corner below its tip
    # line must not let a part through that touches it.
    gap_tips = teeth_gap(tips['upper'], tips['lower'], ctx['hinge'], ctx['theta'], up)
    mid_x = float(tips['upper'] @ lateral)
    near = (kind == 'tooth') & (np.abs((P - O) @ lateral - (mid_x - float(O @ lateral))) < .004)
    upper_pts, lower_pts = P[near & (part == 'upper')], P[near & (part != 'upper')]
    gap = gap_tips
    if len(upper_pts) and len(lower_pts):
        gap = min(gap_tips, float((upper_pts @ up).min() - (turned(lower_pts, ctx['hinge'], ctx['theta']) @ up).max()))
    report['teeth_gap'] = round(gap, 4)
    report['teeth_gap_tips'] = round(gap_tips, 4)
    # The points it is computed from (Blender world metres), for the hand check 2 R sin(theta / 2).
    report['incisal'] = {'upper': [round(float(c), 5) for c in tips['upper']],
                         'lower': [round(float(c), 5) for c in tips['lower']],
                         'hinge': [round(float(c), 5) for c in ctx['hinge']], 'up': [round(float(c), 6) for c in up],
                         'theta_deg': round(math.degrees(ctx['theta']), 3)}
    report['tris'] = {'teeth': int((kind[F[:, 0]] == 'tooth').sum()), 'gum': int((kind[F[:, 0]] == 'gum').sum()),
                      'tongue': int((kind[F[:, 0]] == 'tongue').sum())}

    # Build the object, bind it, join it into the body.
    body = ctx['body']
    Mi = body.matrix_world.inverted()
    me = bpy.data.meshes.new('mouth_teeth')
    me.from_pydata([tuple(Mi @ Vector(p)) for p in P], [], [tuple(int(i) for i in t) for t in F])
    me.update()
    for poly in me.polygons:
        poly.use_smooth = True
    obj = bpy.data.objects.new('mouth_teeth', me)
    bpy.context.scene.collection.objects.link(obj)
    obj.matrix_world = body.matrix_world.copy()
    try:
        teeth_mat = bpy.data.materials.new(TEETH_MATERIAL)
        teeth_mat.use_nodes = True
        teeth_mat['attached_part'] = ctx['group_id']
        teeth_mat.use_backface_culling = True
        tree = teeth_mat.node_tree
        shader = next(nd for nd in tree.nodes if nd.type == 'BSDF_PRINCIPLED')
        attr = tree.nodes.new('ShaderNodeVertexColor')
        attr.layer_name = COLOR_ATTRIBUTE
        tree.links.new(attr.outputs['Color'], shader.inputs['Base Color'])
        shader.inputs['Roughness'].default_value = .35
        shader.inputs['Metallic'].default_value = 0.
        tongue_mat = bpy.data.materials.new(TONGUE_MATERIAL)
        tongue_mat.use_nodes = True
        tongue_mat['attached_part'] = ctx['group_id']
        tongue_mat.use_backface_culling = True
        tshader = next(nd for nd in tongue_mat.node_tree.nodes if nd.type == 'BSDF_PRINCIPLED')
        tshader.inputs['Base Color'].default_value = (*TONGUE_RGB, 1.)
        tshader.inputs['Roughness'].default_value = .55
        tshader.inputs['Metallic'].default_value = 0.
        obj.data.materials.append(teeth_mat)
        obj.data.materials.append(tongue_mat)
        for poly in me.polygons:
            poly.material_index = 1 if kind[F[poly.index, 0]] == 'tongue' else 0
        colors = me.color_attributes.new(COLOR_ATTRIBUTE, 'BYTE_COLOR', 'POINT')
        for i, c in enumerate(mesh.rgb):
            colors.data[i].color = (*c, 1.)
        # Weights: rigid upper / lower, the tongue from the lower wall under it.
        head = ctx['head_bone']
        jaw = ctx['jaw_bone']
        g_head = obj.vertex_groups.new(name=head)
        g_jaw = obj.vertex_groups.new(name=jaw)
        g_head.add([int(i) for i in np.nonzero(part == 'upper')[0]], 1., 'REPLACE')
        g_jaw.add([int(i) for i in np.nonzero(part == 'lower')[0]], 1., 'REPLACE')
        tongue_idx = np.nonzero(part == 'tongue')[0]
        if len(tongue_idx):
            wall = ctx['lower_wall']        # [(world position, {group name: weight})]
            tree_ = KDTree(len(wall))
            for i, (p, _w) in enumerate(wall):
                tree_.insert(Vector(p), i)
            tree_.balance()
            groups = {}
            for i in tongue_idx:
                weights = wall[tree_.find(Vector(P[i]))[1]][1]
                total = sum(weights.values()) or 1.
                for name, w in weights.items():
                    if name not in groups:
                        groups[name] = obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
                    groups[name].add([int(i)], w / total, 'REPLACE')
        # The skin's colour: white, so nothing changes where an exporter writes the attribute for it.
        if COLOR_ATTRIBUTE not in body.data.color_attributes:
            skin_colors = body.data.color_attributes.new(COLOR_ATTRIBUTE, 'BYTE_COLOR', 'POINT')
            for item in skin_colors.data:
                item.color = (1., 1., 1., 1.)
        bpy.ops.object.mode_set(mode='OBJECT') if bpy.context.object and bpy.context.object.mode != 'OBJECT' else None
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        obj.select_set(True)
        body.select_set(True)
        bpy.context.view_layer.objects.active = body
        bpy.ops.object.join()
    except Exception:
        if obj.name in bpy.data.objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        raise
    report['status'] = 'applied'
    return report


class OuterSkin:
    """The faces of ``body`` seen from the front, from 45 degrees to each side and from 30 degrees below within
    ``reach`` of ``centre`` — the outer skin (the lips' inner surfaces behind the cut are not: they part from the
    teeth when the mouth opens). ``inside(p, clearance)``: ``(ok, distance)`` — p is covered from all four
    directions (a ray from p toward each camera meets a skin face) and at least ``clearance`` from the outer skin."""

    def __init__(self, V, tris, skip, centre, reach=.06, step=.0005):
        bvh = BVHTree.FromPolygons([Vector(p) for p in V], [tuple(int(i) for i in t) for t in tris])
        self.dirs = []
        seen = set()
        for yaw, pitch in ((0., 0.), (45., 0.), (-45., 0.), (0., -30.)):
            a, b = math.radians(yaw), math.radians(pitch)
            d = Vector((math.sin(a) * math.cos(b), math.cos(a) * math.cos(b), math.sin(b)))   # camera -> head
            if pitch:
                d = Vector((0., math.cos(b), -math.sin(b)))
            self.dirs.append(d)
            u = Vector((0., 0., 1.)).cross(d).normalized()
            v = d.cross(u).normalized()
            c = Vector(centre)
            for i in np.arange(-reach, reach + 1e-9, step):
                for j in np.arange(-reach, reach + 1e-9, step):
                    hit = bvh.ray_cast(c + u * float(i) + v * float(j) - d * .3, d)
                    if hit[0] is not None and int(hit[2]) not in skip:
                        seen.add(int(hit[2]))
        faces = [tuple(int(i) for i in tris[k]) for k in sorted(seen)]
        self.count = len(faces)
        self.bvh = BVHTree.FromPolygons([Vector(p) for p in V], faces)
        # Cover: any skin face (an inner wall in between has the outer skin beyond it).
        self.cover = BVHTree.FromPolygons([Vector(p) for p in V], [tuple(int(i) for i in t) for k, t in
                                                                     enumerate(tris) if k not in skip])

    def why(self, p):
        p = Vector(p)
        near = self.bvh.find_nearest(p)
        return [round(near[3] * 1000, 2), [k for k, d in enumerate(self.dirs) if self.cover.ray_cast(p, -d)[0] is None],
                [round(c * 1000, 1) for c in near[0]]]

    def inside(self, p, clearance):
        p = Vector(p)
        near = self.bvh.find_nearest(p)
        dist = near[3] if near[0] is not None else float('inf')
        for d in self.dirs:
            if self.cover.ray_cast(p, -d)[0] is None:
                return False, dist
        return dist >= clearance, dist
