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
import extension_bones
sys.path.remove(_SCRIPT_DIR)
import bpy
import bmesh
from mathutils.kdtree import KDTree
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

DEFAULTS = {
    'anchor_bone': 'Hips',
    'center_drop': .08,          # chart centre below the anchor head
    'theta': [-70, 170],         # profile angles (0 front, 90 down, 180 back)
    'centre_height': .07,       # chart centre above the lowest outer midline point
    'under': [50, 105],          # outward normal angles bounding the underside
    'under_ref': .138, 'scale_min': .75, 'centre_offset': -.013,
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
    'edge': [.0007, .0022, .005], 'bake': 512, 'fill_iterations': 1500,
    'level': {'enabled': 1, 'sigma': .015, 'tukey': .004, 'wall_rise': .015, 'depth': [.06, .03], 'relax': 500,
              'min_half_width': .006, 'under': .012},
    # The pelvis rule (Ruling A117): ``bone`` carries at least ``share`` of a vertex's weight in the part, blended
    # over a band around the part's welded border — ``ring`` of the part's deepest border distance inwards, ``spread``
    # of it outwards over the surrounding skin (measured along the skin) — so the opening region stays on the pelvis
    # when the legs flex. ``share`` 0 leaves the interpolated skin weights.
    'pelvis': {'bone': 'Hips', 'share': 0.0, 'ring': .5, 'spread': .5},
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
    if not isinstance(p['fill_iterations'], int) or p['fill_iterations'] <= 0:
        raise ValueError('Fill iterations must be a positive integer')
    pv = p['pelvis']
    if not 0 <= pv['share'] <= 1 or not 0 < pv['ring'] <= 1 or not 0 <= pv['spread'] <= 4:
        raise ValueError('Pelvis: share 0..1, ring above 0 up to 1, spread 0..4')
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
    if min(p['edge']) <= 0 or min(p['center_drop'], p['centre_height'], p['under_ref']) <= 0:
        raise ValueError('Expected positive chart lengths')
    level = p['level']
    if level['enabled'] not in (0, 1) or not isinstance(level['relax'], int) or level['relax'] < 0:
        raise ValueError('Level: enabled is 0 or 1, relax a nonnegative integer')
    if min(level['sigma'], level['tukey'], level['wall_rise'], *level['depth']) <= 0 or min(level['min_half_width'], level['under']) < 0:
        raise ValueError('Level: expected positive lengths')
    if p['under'][0] >= p['under'][1]:
        raise ValueError('Invalid underside interval')
    if not 0 < p['scale_min'] <= 1:
        raise ValueError('Expected scale_min between zero and one')
    if min(p['eps'], p['sink'], p['mound']['amp'], p['ridges']['amp'], p['inner']['rise'],
           p['hood']['fill'], p['nub']['fill']) < 0:
        raise ValueError('Expected nonnegative profile height')
    if min(p['tone']['inner']) <= 0:
        raise ValueError('Inner tint channels must be positive')
    if any(v < 0 for tone in p['tone'].values() for v in tone):
        raise ValueError('Expected nonnegative tint multiplier')
    return p


def surface_chart(body, arm, P):
    """The op's chart of the body as it is now: the outer midline profile
    around the centre below the anchor bone, its arc length ``S`` (scaled)
    and ``chart(Q)`` -> (s, u, radial offset) of world points."""
    M = body.matrix_world.copy(); Mi = M.inverted(); N3 = M.to_3x3(); Ni3 = Mi.to_3x3()
    hips = arm.matrix_world @ resolve_bone(arm.pose.bones, P['anchor_bone']).head
    xm = hips.x
    c = Vector((xm, hips.y, hips.z - P['center_drop']))
    dg = bpy.context.evaluated_depsgraph_get()
    bvh = BVHTree.FromObject(body, dg)

    def outer_hit(centre, direction):
        """Cast from inside, continuing through nearby walls to the outer skin."""
        local_direction = Ni3 @ direction
        local_length = local_direction.length
        local_direction.normalize()
        hit = bvh.ray_cast(Mi @ centre, local_direction)
        if hit[0] is None:
            return None, None
        point = M @ hit[0]
        normal = (N3 @ hit[1]).normalized()
        for _ in range(3):
            hit = bvh.ray_cast(Mi @ (point + direction * 1e-4),
                               local_direction, .015 * local_length)
            if hit[0] is None:
                break
            point = M @ hit[0]
            normal = (N3 @ hit[1]).normalized()
        return point, normal if normal.dot(direction) > 0 else -normal

    # First locate the lowest outer midline point from the original centre.
    low_points = [outer_hit(c, Vector((0, -math.cos(t), -math.sin(t))))[0]
                  for t in np.radians(np.arange(40, 141, 2))]
    if any(point is None for point in low_points):
        raise ValueError('Lowest outer profile ray missed')
    c = Vector((xm, hips.y, min(point.z for point in low_points) + P['centre_height']))
    th = np.radians(np.arange(P['theta'][0], P['theta'][1] + .01, .5))
    prof, pn = [], []
    for t in th:
        point, normal = outer_hit(c, Vector((0, -math.cos(t), -math.sin(t))))
        if point is None:
            raise ValueError('Profile ray missed at %.1f' % math.degrees(t))
        prof.append(tuple(point)); pn.append(tuple(normal))
    prof, pn = np.array(prof), np.array(pn)
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(prof[:, 1:], axis=0), axis=1))])
    phi = np.degrees(np.arctan2(-pn[:, 2], -pn[:, 1]))
    phi = np.convolve(np.pad(phi, 6, mode='edge'), np.ones(13) / 13, mode='valid')
    front = np.flatnonzero(phi >= P['under'][0])
    if not len(front):
        raise ValueError('No front corner in outer profile')
    i0 = int(front[0])
    back = np.flatnonzero(phi[i0 + 1:] >= P['under'][1])
    i1 = i0 + 1 + int(back[0]) if len(back) else None
    underside = float(arc[i1] - arc[i0]) if i1 is not None else P['under_ref']
    scale = float(np.clip(underside / P['under_ref'], P['scale_min'], 1.))
    centre = arc[i0] + underside / 2 + P['centre_offset']
    s_start = centre - .05 * scale
    S = (arc - s_start) / scale
    print('underside', underside, 'scale', scale, 'front corner', prof[i0].tolist())


    def chart(Q):
        """(s, u, radial offset) of world points Q (n,3)."""
        dy, dz = Q[:, 1] - c.y, Q[:, 2] - c.z
        t = np.arctan2(-dz, -dy)
        t = np.where(t < np.radians(P['theta'][0]) - .5, t + 2 * np.pi, t)
        s = np.interp(t, th, S)
        r = np.hypot(dy, dz) - np.interp(t, th, np.hypot(prof[:, 1] - c.y, prof[:, 2] - c.z))
        return s, Q[:, 0] - xm, r
    return {'M': M, 'Mi': Mi, 'N3': N3, 'Ni3': Ni3, 'bvh': bvh, 'c': c, 'xm': xm, 'th': th, 'S': S, 'prof': prof,
            'pn': pn, 'i0': i0, 'arc': arc, 's_start': s_start, 'underside': underside, 'scale': scale, 'chart': chart}


# The opening (cross-person collision, stage 2): a channel region declared with ``from_rig`` takes its placement from
# the op that built the recess. The op reports the pocket's opening: the centre on the undisplaced chart midline (the
# levelled skin, before the part's displacement) and the unit inward surface normal there, in glTF bind space (the
# body's POSITION space). The interval is the pocket AS BUILT: where the levelling cut the part short (A77b), the
# pocket's depth fades out over ``region.fall`` before ``s_end`` (smoothstep, half depth at s_end - fall/2), and the
# levelled skin past that point is not part of it.
def _gltf(v):
    """Blender (x, y, z) -> glTF Y-up (x, z, -y), as plain floats."""
    return [float(v[0]), float(v[2]), float(-v[1])]


def opening_s(pocket, s_end, fall):
    """The chart s of the opening's centre: the midpoint of the built pocket interval, None when none is built."""
    s1 = pocket['s1'] if s_end is None else min(pocket['s1'], s_end - fall / 2)
    return (pocket['s0'] + s1) / 2 if s1 > pocket['s0'] else None


def opening_metric(prof, pn, S, s_mid, xm, Mi, Ni3):
    """``{"centre", "axis"}`` at chart s = ``s_mid``: the midline point (x = ``xm``) and the unit inward normal
    (-``pn`` interpolated over ``S``), through the inverse world matrix ``Mi`` / ``Ni3`` into glTF bind space."""
    point = np.array([xm, np.interp(s_mid, S, prof[:, 1]), np.interp(s_mid, S, prof[:, 2]), 1.])
    inward = -np.array([np.interp(s_mid, S, pn[:, k]) for k in range(3)])
    centre = (np.array(Mi, float) @ point)[:3]
    axis = np.array(Ni3, float) @ inward
    return {'centre': _gltf(centre), 'axis': _gltf(axis / np.linalg.norm(axis))}


# The levelling (Ruling A77): before the part is built, the skin the mesher modelled in the region (a groove, folds,
# raised bumps — drawn although the mesh input asked for plain skin) is levelled onto the surface around it, as a tip
# part levels its source bump (``extension_bones.level_heights``: k = 1 over the region, fading over NEUTRAL_BLEND x
# full; the inner wall of a double-walled body kept NEUTRAL_GAP_M under the skin; rows further than ``level.depth``
# from the surface are other parts of the body). What differs from the tip is the region and the surface, both
# measured on a mesher-built base model (2026-11-15) whose region detail stood 30 mm above and 40-48 mm below it:
# * the region is this op's own: the chart interval [region.s0, region.s1] and |u| <= region.u — but between the
#   legs the skin is a channel 10-40 mm wide whose walls rise 40-100 mm, so each side ends where the OUTER ENVELOPE
#   (rays from outside along the chart's radial direction) rises more than ``level.wall_rise`` above the lowest point
#   between it and the midline: a wall, not part of the region (a fold stays under 15 mm, the legs rise 40 mm within
#   4 mm). The fade is the region's own ``fall`` (full = fall / NEUTRAL_BLEND), measured along the skin: beside the
#   region a vertex's height above the surface counts as distance too — measured across, the fade pulled the foot
#   of the walls down onto the surface and left them sheared into stripes.
# * the surface: a disc's ring of skin around it does not exist in the channel (beyond its sides are the walls), so
#   it is fitted over the region itself — a quadratic around every node of a LEVEL_GRID_M grid with Gaussian weights
#   of ``level.sigma`` (moving least squares) on the outer envelope inside the region, samples standing off it by more
#   than ``level.tukey`` dropped (Tukey weights, LEVEL_FIT_ITERATIONS refits): the modelled detail is the outlier, the
#   skin it sits on is the fit. On the envelope because the vertices include the inner wall and the groove's walls.
#   Heights are radial distances from the chart axis — not from the profile, which dips into a groove and made the
#   levelled surface jump by 26 mm where it did.
# * the groove's walls are levelled too: ``level.depth[0]`` = 60 mm — at 40 mm the deepest rows stayed and the
#   levelled rim pulled a fin down to them that the op's own profile then followed (its underside fell from 62 to
#   22 mm). A curled fold faces inward like an inner wall, so inner rows FOLLOW the levelled skin, NEUTRAL_GAP_M under
#   it (``inner_follows``) — left in place they stood as spikes across the levelled skin.
# * a levelled fold lies folded over itself on the surface: the levelled rows are spread over the surface again, each
#   at the mean of its neighbours inside the fixed rest (``spread_evenly``, at most ``level.relax`` conjugate-gradient
#   steps, in the chart; the height is the surface's; seam copies as one point); then the moved skin gets the
#   surface's own normals (``extension_bones.refresh_normals``); a face the spread turned over against its source
#   face (at the region's border a node slid past one that stayed) gets its spread nodes at their neighbours' mean.
# * the back end (A77b, measured on the same model): where the legs close, the channel narrows to 1-5 mm half width
#   and its skin runs on 25 mm below the surface, beneath the envelope. Levelled, that skin was lifted 26-28 mm
#   within the fade — the faces between it and the skin around became 8,826 slivers (aspect over SLIVER_ASPECT) and
#   168 folded faces, a spiky strip into the leg gap. So (1) the region ends ``fall`` before the first envelope row
#   whose narrower half width is under ``level.min_half_width`` (``region_ends``), and the part ends there with it;
#   (2) skin more than ``level.under`` below the surface fades out by that excess, as if it lay that far beyond the
#   region, and is not spread; (3) the faces the subdivision cut on one or two edges get the shorter diagonals
#   (``beautify_fill``).
# * past the part's end (A77c, same model): left as modelled, the lower third of the channel kept the mesher's lumps
#   (|residual| p95 4.8 mm against the robust fit, 70.7-84 degrees). So the part still ends at ``region_ends``, but
#   the levelling runs on down the channel to where the legs close over its midline (``channel_close``: the midline's
#   envelope jumps by more than ``wall_rise`` — 84.1 degrees here; never past the region's own end): p95 0.57 mm.
#   Deep skin keeps rule (2). A lower ``min_half_width`` lengthens the part, not the levelling: 4 and 3 mm end it at
#   72.7 instead of 70.7 degrees and put 26 more slivers and 2 folded faces into its narrow end, so 6 mm stays.
#   Levelled between steep walls, the fade folds faces too: the mend takes every moved node and every face turned
#   against its source face, against the faces around it, or (an outer face) newly toward the axis; then the levelled
#   skin's slivers are flipped (``flip_slivers`` without collapses, which would renumber the body), and the displaced
#   patch is mended and placed MEND_ROUNDS times.
SLIVER_ASPECT = 20.          # longest edge over its height: a face past it is a sliver (A77b)
MEND_ROUNDS = 3               # mend-and-place rounds of the displaced patch (A77c)
LEVEL_GRID_M = .0015
# The fit at the border (A169), measured on a mesher-built base model (2026-11-17) with thighs flexed 0/60/90/120
# degrees: (1) the inward-facing skin under the region is no longer removed — removing it opened 330 border edges on
# the outer skin (a gap when the thighs part) and cut a 290-vertex strip of skin loose, which kept its leg weights
# while everything around it rode the pelvis and stood out as a flap; a piece the region's replacement still cuts
# loose is deleted; (2) the part is one-sided like the body (double-sided, it showed its dark back wherever the skin
# folded over it) and carries the body's roughness instead of a constant .55; (3) inside the
# pelvis band the weights are the harmonic blend (inverse-edge-length Laplace, conjugate gradients) between the core
# and the untouched skin around it, solved on the welded mesh so the border has no kink: the band's smoothstep in
# skin distance folded 3.4 % of the region's area at 60 degrees where the source folded none.
HARMONIC_ITERATIONS = 4000
HARMONIC_TOLERANCE = 1e-7
BAND_ATTRIBUTE = '_inset_band'
LEVEL_FIT_ITERATIONS = 6


def robust_local_surface(a, u, h, sigma, tukey, step, extent):
    """The surface the samples (a, u, h) lie on, as a sampler ``f(a, u) -> h``: a quadratic fitted around every
    node of a ``step`` grid over ``extent`` (a0, a1, u0, u1) with Gaussian weights of ``sigma`` (moving least
    squares), samples that stand off it by more than ``tukey`` dropped by Tukey weights over
    LEVEL_FIT_ITERATIONS refits; bilinear between the nodes."""
    ga = np.arange(extent[0] - step, extent[1] + 2 * step, step)
    gu = np.arange(extent[2] - step, extent[3] + 2 * step, step)
    GA, GU = np.meshgrid(ga, gu, indexing='ij')
    nodes = np.stack([GA.ravel(), GU.ravel()], 1)
    robust = np.ones(len(a))
    order = np.argsort(a)
    sorted_a = a[order]
    reach = 3 * sigma

    def solve():
        out = np.full(len(nodes), np.nan)
        for start in range(0, len(nodes), 256):
            block = nodes[start:start + 256]
            lo, hi = np.searchsorted(sorted_a, [block[:, 0].min() - reach, block[:, 0].max() + reach])
            idx = order[lo:hi]
            if not len(idx):
                continue
            da = a[idx][None, :] - block[:, :1]
            du = u[idx][None, :] - block[:, 1:]
            w = np.exp(-(da * da + du * du) / sigma ** 2) * robust[idx][None, :]
            X = np.stack([np.ones_like(da), da, du, da * da, da * du, du * du], -1)
            G = np.einsum('nk,nki,nkj->nij', w, X, X) + np.eye(6) * 1e-12
            rhs = np.einsum('nk,nki,k->ni', w, X, h[idx])
            ok = w.sum(1) > 1e-3
            out[start:start + 256][ok] = np.linalg.solve(G[ok], rhs[ok][..., None])[:, 0, 0]
        grid = out.reshape(GA.shape)
        # A node without samples near it takes its row's nearest value (never read inside the region).
        for row in grid:
            known = np.isfinite(row)
            if known.any() and not known.all():
                row[~known] = np.interp(np.flatnonzero(~known), np.flatnonzero(known), row[known])
        return np.where(np.isfinite(grid), grid, np.nanmean(grid) if np.isfinite(grid).any() else 0.)

    def sample(grid, pa, pu):
        fa = np.clip((pa - ga[0]) / step, 0, len(ga) - 1.001)
        fu = np.clip((pu - gu[0]) / step, 0, len(gu) - 1.001)
        i, j = fa.astype(int), fu.astype(int)
        x, y = fa - i, fu - j
        return (grid[i, j] * (1 - x) * (1 - y) + grid[i + 1, j] * x * (1 - y)
                + grid[i, j + 1] * (1 - x) * y + grid[i + 1, j + 1] * x * y)
    for _ in range(LEVEL_FIT_ITERATIONS):
        grid = solve()
        res = h - sample(grid, a, u)
        robust = np.clip(1 - (res / tukey) ** 2, 0, None) ** 2
    grid = solve()
    return lambda pa, pu: sample(grid, np.asarray(pa, float), np.asarray(pu, float))


def region_walls(env, ug, cap, rise):
    """Per envelope row (one chart angle) the region's half width on each side ``[left, right]`` (metres): out from
    the midline, the last sample before the envelope ``env`` (radial distances, NaN = no skin) rises more than
    ``rise`` above the lowest point between it and the midline, or misses; at most ``cap``."""
    mid = int(np.argmin(np.abs(ug)))
    walls = np.full((len(env), 2), float(cap))
    for i, row in enumerate(env):
        for side, sign in enumerate((-1, 1)):
            low = row[mid]
            for j in range(mid, len(ug) if sign > 0 else -1, sign):
                if not np.isfinite(row[j]) or row[j] - low > rise:
                    walls[i, side] = min(cap, max(0., abs(ug[j]) - abs(ug[1] - ug[0])))
                    break
                low = min(low, row[j])
    return walls


def region_ends(tg, walls, t0, t1, minimum, margin):
    """The levelled region's ends (angles) inside [t0, t1] (A77b). From the region's widest envelope row outward, the
    first row whose narrower half width (``walls``, per row of ``tg``) falls below ``minimum`` is where the legs close
    over the channel: the skin left between them is too narrow to level or to build on. The region ends ``margin``
    (an angle: the fade beyond the region) before that row, so its fade, too, stays out of the narrow channel; the
    same toward the start. Nothing narrow, all narrow, or nothing left between the ends: [t0, t1] unchanged."""
    rows = np.flatnonzero((tg >= t0) & (tg <= t1))
    if not len(rows) or minimum <= 0:
        return t0, t1
    half = walls[rows].min(1)
    if (half < minimum).all():
        return t0, t1
    widest = int(np.argmax(half))
    after = np.flatnonzero(half[widest:] < minimum)
    before = np.flatnonzero(half[:widest] < minimum)
    end = min(t1, float(tg[rows[widest + after[0]]]) - margin) if len(after) else t1
    start = max(t0, float(tg[rows[before[-1]]]) + margin) if len(before) else t0
    return (start, end) if start < end else (t0, t1)


def channel_close(tg, env, ug, start, limit, rise):
    """Where the leg walls meet over the channel's midline (an angle in [start, limit]): the last envelope row before
    the midline's envelope (the lowest sample within 1 mm of it) jumps more than ``rise`` above the previous row's, or
    misses — past it the ray from outside hits a leg lying over the channel (A77c)."""
    mid = np.abs(ug) <= .001 + 1e-9
    close, previous = start, None
    for i in np.flatnonzero((tg >= start) & (tg <= limit)):
        values = env[i, mid]
        here = float(np.nanmin(values)) if np.isfinite(values).any() else math.nan
        if not math.isfinite(here) or (previous is not None and here - previous > rise):
            break
        close, previous = float(tg[i]), here
    return close


def level_region(body, arm, P):
    """Level the skin of the region onto the surface around it before the part is built (module notes above).
    Returns the metrics ``{source_smooth: {radius_m, blend_m, iterations, moved, max_shift_mm,
    inner_wall_vertices}, source_level: {bump_mm: [before, after], bump_p95_mm: [before, after], fit_rms_mm,
    angle_deg, half_width_mm: [min, max], folded_faces: [before, after], normals_refreshed}}`` (bump: the outer skin
    of the region above the fitted surface, mm — the tip's ``bump_mm``), and ``end_point``: the world point where the
    part is cut short (``region_ends``; the levelling runs on to ``channel_close``), None where it is not —
    ``build_part`` ends the part there."""
    L, R = P['level'], P['region']
    ch = surface_chart(body, arm, P)
    M, Mi, Ni3, bvh, c, xm, th, S, prof = (ch[k] for k in ('M', 'Mi', 'Ni3', 'bvh', 'c', 'xm', 'th', 'S', 'prof'))
    t0, t1 = (float(v) for v in np.interp([R['s0'], R['s1']], S, th))
    rho_prof = np.hypot(prof[:, 1] - c.y, prof[:, 2] - c.z)
    rho_nom = float(np.median(rho_prof[(th >= t0) & (th <= t1)]))
    span = (t1 - t0) * rho_nom
    full = R['fall'] / extension_bones.NEUTRAL_BLEND
    reach = (extension_bones.NEUTRAL_FIT[1] - 1) * full
    # The outer envelope over the region and its surroundings: 1 degree x 1 mm, rays from outside.
    tg = np.arange(t0 - reach / rho_nom, t1 + reach / rho_nom + 1e-9, math.radians(1))
    ug = np.round(np.arange(-R['u'] - reach, R['u'] + reach + 1e-9, .001), 6)
    env = np.full((len(tg), len(ug)), np.nan)
    for i, t in enumerate(tg):
        d = Vector((0, -math.cos(t), -math.sin(t)))
        for j, x in enumerate(ug):
            hit = bvh.ray_cast(Mi @ (Vector((xm + x, c.y, c.z)) + d * .5), Ni3 @ (-d))
            if hit[0] is not None:
                q = M @ hit[0]
                env[i, j] = math.hypot(q.y - c.y, q.z - c.z)
    walls = region_walls(env, ug, R['u'], L['wall_rise'])
    nominal_end = t1
    t0, t_part = region_ends(tg, walls, t0, t1, L['min_half_width'], R['fall'] / rho_nom)
    # Cut short, the part ends there; the levelling runs on down the channel to where the legs close over it (A77c).
    t1 = channel_close(tg, env, ug, t_part, t1, L['wall_rise']) if t_part < t1 else t1
    span = (t1 - t0) * rho_nom

    def chart(points):
        """(a along the region, u, height above rho_nom, distance outside the region, valid, radial unit)."""
        dy, dz = points[:, 1] - c.y, points[:, 2] - c.z
        t = np.arctan2(-dz, -dy)
        t = np.where(t < np.radians(P['theta'][0]) - .5, t + 2 * np.pi, t)
        rho = np.hypot(dy, dz)
        u = points[:, 0] - xm
        a = (t - t0) * rho_nom
        width = np.where(u < 0, np.interp(t, tg, walls[:, 0]), np.interp(t, tg, walls[:, 1]))
        outside = np.hypot(np.maximum(0, np.maximum(-a, a - span)), np.maximum(0, np.abs(u) - width))
        valid = (t > th[0]) & (t < th[-1]) & (np.abs(rho - rho_nom) < .05)
        return a, u, rho - rho_nom, outside, valid, np.stack([np.zeros(len(points)), dy, dz], 1) / np.maximum(rho, 1e-9)[:, None]
    # The fit, before any vertex moves: the envelope inside the region.
    TG, UG = np.meshgrid(tg, ug, indexing='ij')
    ea = (TG - t0) * rho_nom
    width = np.where(UG < 0, np.interp(TG, tg, walls[:, 0]), np.interp(TG, tg, walls[:, 1]))
    inside = (np.isfinite(env) & (ea >= 0) & (ea <= span) & (np.abs(UG) <= width)
              & (np.abs(np.nan_to_num(env, nan=0.) - rho_nom) < .05))
    if inside.sum() < 12:
        raise ValueError('No skin in the inset region to level')
    surface = robust_local_surface(ea[inside], UG[inside], env[inside] - rho_nom, L['sigma'], L['tukey'],
                                   LEVEL_GRID_M, (-reach, span + reach, ug[0], ug[-1]))
    meshes = [body]
    snapshot = extension_bones.position_snapshot(meshes)

    def window(limit):
        def accept(points):
            _, _, _, outside, valid, _ = chart(points)
            return valid & (outside <= limit)
        return accept
    source_count = len(body.data.vertices)
    extension_bones.subdivide_where(body, [window((f - 1) * full) for f in extension_bones.NEUTRAL_SUBDIVIDE],
                                    vectorised=True)
    # The grid fill leaves quads; the patch is cut from triangles, and a quad half in it opens the border.
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.verts.ensure_lookup_table()
    quads = [f for f in bm.faces if len(f.verts) > 3 and any(v.index >= source_count for v in f.verts)]
    if quads:
        bmesh.ops.triangulate(bm, faces=quads)
    # A face the subdivision cut on one or two edges only (the window's border) is a bisected sliver where the mesher's
    # faces are long and thin already — the channel past the region's end (A77b): the new faces get the shorter
    # diagonals. Flat subdivision, so the flips keep the surface.
    cut = [f for f in bm.faces if any(v.index >= source_count for v in f.verts)]
    cut_set = set(cut)
    bmesh.ops.beautify_fill(bm, faces=cut, edges=[e for e in {e for f in cut for e in f.edges}
                                                  if len(e.link_faces) == 2 and all(f in cut_set for f in e.link_faces)])
    bm.to_mesh(body.data)
    bm.free()
    V = np.array([tuple(M @ v.co) for v in body.data.vertices])
    Nn = np.array([tuple((M.to_3x3() @ v.normal).normalized()) for v in body.data.vertices])
    # Coincident copies (UV seams) are one point: one normal, one move.
    groups = {}
    for i, q in enumerate(np.round(V / 1e-5).astype(np.int64)):
        groups.setdefault(tuple(q), []).append(i)
    group_of = np.empty(len(V), np.int64)
    for g, members in enumerate(groups.values()):
        group_of[members] = g
        if len(members) > 1:
            n = Nn[members].sum(0)
            Nn[members] = n / (np.linalg.norm(n) + 1e-12)
    a, u, h, outside, valid, radial = chart(V)
    rows = np.flatnonzero(valid & (outside <= reach))
    # This op's inner wall: facing the chart axis (``build_part``'s ``inner_wall``).
    inner = np.einsum('ij,ij->i', Nn[rows], radial[rows]) < -.2
    folded_before = folded_faces(body, rows[outside[rows] <= 0], c)
    Q = surface(a[rows], u[rows])
    support = ~inner & (outside[rows] <= 0) & (np.abs(h[rows] - Q) < L['tukey'])
    # Beyond the region the fade runs along the skin: a wall rising off the surface is that far away too.
    beyond = np.where(outside[rows] > 0, np.hypot(outside[rows], np.maximum(0, h[rows] - Q)), outside[rows])
    # Skin lying further than ``under`` below the surface is the mesher's skin beneath the region (A77b: where the legs
    # close it runs on, 25 mm down, under the envelope): it fades out by that excess as if it lay that far beyond the
    # region — lifting it whole stretched the faces between it and the skin around into slivers. Continuous at the
    # border (excess 0 = within the region).
    under = np.maximum(0, Q - h[rows] - L['under'])
    beyond = np.where(beyond > 0, np.hypot(beyond, under), np.where(under > 0, under, beyond))
    shift, stats = extension_bones.level_heights(h[rows], beyond, inner, full, lambda ring: Q,
                                                 tuple(L['depth']), inner_follows=True, ring=support)
    moved = 0
    for i, dh, n in zip(rows, shift, radial[rows]):
        if abs(dh) > 1e-9:
            vertex = body.data.vertices[int(i)]
            vertex.co = Mi @ (M @ vertex.co + Vector(n) * float(dh))
            moved += 1
    # Spread the levelled folds over the surface again (tangential; seam copies as one point).
    off = h[rows] - Q
    level = np.zeros(len(V), bool)
    level[rows[(beyond <= 0) & (off > -L['depth'][0]) & (off < L['depth'][1])]] = True    # levelled whole
    count = group_of.max() + 1
    free = np.zeros(count, bool)
    free[group_of[level]] = True
    free[group_of[~level]] = False
    ga, gu = np.zeros(count), np.zeros(count)
    ga[group_of], gu[group_of] = a, u
    edges = group_of[np.array([tuple(e.vertices) for e in body.data.edges], np.int64).reshape(-1, 2)]
    edges = edges[(edges[:, 0] != edges[:, 1]) & (free[edges[:, 0]] | free[edges[:, 1]])]
    ga[free], gu[free] = spread_evenly(edges, free, ga, gu, L['relax'])
    is_inner = np.zeros(len(V), bool)
    is_inner[rows[inner]] = True
    # A node the spread put onto another one of its sheet (a sliver between the same fixed neighbours) keeps its
    # levelled place instead: two vertices in one spot leave a face of no area, which the patch drops (an open edge).
    sheet = np.zeros(count)
    sheet[group_of[is_inner]] = 1.
    tree = KDTree(count)
    for g in range(count):
        tree.insert((ga[g], gu[g], sheet[g]), g)
    tree.balance()
    for g in np.flatnonzero(free):
        if len(tree.find_range((ga[g], gu[g], sheet[g]), 2e-5)) > 1:
            free[g] = False
    spread = np.flatnonzero(level & free[group_of])
    na, nu = ga[group_of[spread]], gu[group_of[spread]]
    nt = na / rho_nom + t0
    nr = rho_nom + surface(na, nu) - np.where(is_inner[spread], extension_bones.NEUTRAL_GAP_M, 0.)
    levelled = {int(i): body.data.vertices[int(i)].co.copy() for i in spread}
    for i, x, y, z in zip(spread, xm + nu, c.y - nr * np.cos(nt), c.z - nr * np.sin(nt)):
        body.data.vertices[int(i)].co = Mi @ Vector((x, y, z))
    # A face the spread turned over (a node slid past a neighbour that stayed — the region's border, A77b) is mended
    # by moving its moved nodes to the mean of their neighbours (seam copies together). Turned over: against its own
    # face before the levelling, against the faces around it, or an outer face now facing the axis that did not
    # before — the levelled channel past the part's end lies between steep walls, where the fade folds faces too (A77c).
    mendable = set(levelled) | {int(i) for i, dh in zip(rows, shift) if abs(dh) > 1e-9}
    members = {}
    for i in mendable:
        members.setdefault(int(group_of[i]), []).append(i)
    faces = [tuple(f.vertices) for f in body.data.polygons if any(v in mendable for v in f.vertices)]
    def normal(points):
        return (points[1] - points[0]).cross(points[2] - points[0])
    source = {f: normal([Mi @ Vector(V[v]) for v in f]) for f in faces}
    ring = {}
    for e in body.data.edges:
        i, j = e.vertices
        ring.setdefault(int(group_of[i]), set()).add(j)
        ring.setdefault(int(group_of[j]), set()).add(i)
    adjacent = {}
    for f in faces:
        for k in range(len(f)):
            adjacent.setdefault(frozenset((f[k], f[(k + 1) % len(f)])), []).append(f)
    def turned_over(f):
        local = [body.data.vertices[v].co for v in f]
        n = normal(local)
        if n.dot(source[f]) <= 0:
            return True
        around = sum((normal([body.data.vertices[v].co for v in g]) for k in range(len(f))
                      for g in adjacent[frozenset((f[k], f[(k + 1) % len(f)]))] if g != f), Vector())
        if around.length > 0 and n.normalized().dot(around.normalized()) < -.2:
            return True
        if is_inner[list(f)].any():
            return False
        world = [M @ p for p in local]
        centre = sum(world, Vector()) / len(world)
        out = Vector((0, centre.y - c.y, centre.z - c.z))
        return normal(world).dot(out) <= 0 < (M.to_3x3() @ source[f]).dot(out)
    for _ in range(20):
        turned = {int(group_of[v]) for f in faces if turned_over(f) for v in f if v in mendable}
        if not turned:
            break
        mean = {g: sum((body.data.vertices[j].co for j in ring[g]), Vector()) / len(ring[g]) for g in turned}
        for g, m in mean.items():
            for i in members[g]:
                body.data.vertices[i].co = m
    body.data.update()
    # The levelled skin's slivers are mended like the patch's (``flip_slivers``), by flips only: a collapse would
    # renumber the body's vertices (A77c).
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.verts.ensure_lookup_table()
    allowed = {bm.verts[int(i)] for i in rows}
    flip_slivers(bm, {v: v.co.copy() for v in bm.verts}, only=allowed, collapse=False)
    bm.to_mesh(body.data)
    bm.free()
    body.data.update()
    refreshed = extension_bones.refresh_normals(meshes, snapshot)
    after = rows[outside[rows] <= 0]
    folded_after = folded_faces(body, after, c)
    return {'source_smooth': {'radius_m': full, 'blend_m': extension_bones.NEUTRAL_BLEND * full,
                              'iterations': L['relax'], 'moved': moved, 'max_shift_mm': stats['max_shift_mm'],
                              'inner_wall_vertices': int(inner.sum())},
            'end_point': [xm, c.y - rho_nom * math.cos(t_part), c.z - rho_nom * math.sin(t_part)] if t_part < nominal_end else None,
            'source_level': {'bump_mm': [stats['bump_before_mm'], stats['bump_after_mm']],
                             'bump_p95_mm': stats['bump_p95_mm'], 'fit_rms_mm': stats['fit_rms_mm'],
                             'angle_deg': [round(math.degrees(t0), 2), round(math.degrees(t1), 2)],
                             'half_width_mm': [round(float(walls.min()) * 1000, 1), round(float(walls.max()) * 1000, 1)],
                             'folded_faces': [folded_before, folded_after], 'normals_refreshed': refreshed}}


def spread_evenly(edges, free, xa, xb, iterations):
    """The free nodes' coordinates (two arrays over all nodes) once every free node sits at the mean of its
    neighbours, the others fixed — the even spread of the graph inside its fixed border (uniform Laplacian,
    conjugate gradients, at most ``iterations`` steps), which leaves no face folded over another where the border
    is convex. Returns the free nodes' (a, b)."""
    count = len(free)
    degree = np.bincount(edges.ravel(), minlength=count).astype(float)
    solvable = free & (degree > 0)

    def laplace(x):
        neighbours = np.bincount(edges[:, 0], x[edges[:, 1]], count) + np.bincount(edges[:, 1], x[edges[:, 0]], count)
        return degree * x - neighbours
    out = []
    for x in (xa.copy(), xb.copy()):
        fixed = np.where(solvable, 0., x)
        rhs = -laplace(fixed)
        y = np.where(solvable, x, 0.)
        r = np.where(solvable, rhs - laplace(y), 0.)
        d = r.copy()
        rr = r @ r
        for _ in range(iterations):
            if rr < 1e-24:
                break
            q = np.where(solvable, laplace(d), 0.)
            alpha = rr / (d @ q)
            y += alpha * d
            r -= alpha * q
            new = r @ r
            d = r + new / rr * d
            rr = new
        out.append(np.where(solvable, y, x)[free])
    return out


def folded_faces(body, vertices, c):
    """Outer-skin faces among those with every vertex in ``vertices`` whose winding faces the chart axis while
    their vertices' own normals face away from it: skin folded over itself."""
    chosen = np.zeros(len(body.data.vertices), bool)
    chosen[vertices] = True
    M = body.matrix_world
    count = 0
    for poly in body.data.polygons:
        if not chosen[list(poly.vertices)].all():
            continue
        points = [M @ body.data.vertices[i].co for i in poly.vertices]
        centre = sum(points, Vector()) / len(points)
        radial = Vector((0, centre.y - c.y, centre.z - c.z))
        normal = (points[1] - points[0]).cross(points[2] - points[0])
        if normal.dot(radial) < 0 and sum((M.to_3x3() @ body.data.vertices[i].normal for i in poly.vertices), Vector()).dot(radial) > 0:
            count += 1
    return count


def aspect(points):
    """A triangle's longest edge over its height on that edge (1/2 sqrt 3 for an equilateral one; inf degenerate)."""
    a, b, c = points
    longest = max((b - a).length, (c - b).length, (a - c).length)
    area = (b - a).cross(c - a).length / 2
    return longest * longest / (2 * area) if area > 1e-16 else math.inf


def flip_slivers(bm, flat, limit=SLIVER_ASPECT, passes=6, bend=.9, only=None, collapse=True):
    """Mend the slivers (aspect over ``limit``) of the displaced patch ``bm`` (A77b) — the walls of the cleft and pocket
    rise steeply over a few millimetres, and the flat subdivision's diagonals run across them. First the shared edge
    of a sliver and a neighbour is flipped where the other diagonal gives both triangles a lower worst aspect and each
    new face stays within ``bend`` (cosine) of the old faces' mean normal; then a needle's shortest edge is collapsed
    onto its midpoint where no face around it turns or becomes a sliver. ``flat`` maps every vertex to its position
    before the displacement; a collapse keeps it current (the merged vertex gets the flat midpoint), so the caller
    places the mended patch again from it. ``only`` (a vertex set) limits the mend to faces of those vertices;
    ``collapse`` False keeps every vertex (flips only — the levelled body skin, A77c)."""
    for _ in range(passes):
        flips = []
        seen = set()
        for f in bm.faces:
            if len(f.verts) != 3 or f in seen or aspect([v.co for v in f.verts]) <= limit:
                continue
            if only is not None and not all(v in only for v in f.verts):
                continue
            best = None
            for e in f.edges:
                if e.is_boundary or len(e.link_faces) != 2 or e.seam:
                    continue
                g = e.link_faces[1] if e.link_faces[0] is f else e.link_faces[0]
                if g in seen or len(g.verts) != 3 or (only is not None and not all(v in only for v in g.verts)):
                    continue
                p = next(v for v in f.verts if v not in e.verts)
                q = next(v for v in g.verts if v not in e.verts)
                a, b = e.verts
                old = max(aspect([v.co for v in f.verts]), aspect([v.co for v in g.verts]))
                t1, t2 = (p.co, q.co, a.co), (q.co, p.co, b.co)
                new = max(aspect(t1), aspect(t2))
                if new >= old:
                    continue
                normals = [(t[1] - t[0]).cross(t[2] - t[0]) for t in (t1, t2)]
                if min(n.length for n in normals) < 1e-14:
                    continue
                ref = (f.normal + g.normal).normalized()
                if any(abs(n.normalized().dot(ref)) < bend for n in normals):
                    continue
                if best is None or new < best[0]:
                    best = (new, e, g)
            if best:
                flips.append(best[1])
                seen.update((f, best[2]))
        if not flips:
            break
        bmesh.ops.rotate_edges(bm, edges=flips, use_ccw=False)
        bm.normal_update()
    # What no flip mends is a needle: its shortest edge is collapsed onto its midpoint where that folds no face
    # around it (inner vertices only — the border stays welded to the body).
    for _ in range(passes if collapse else 0):
        done = False
        for f in list(bm.faces):
            if not f.is_valid or len(f.verts) != 3 or aspect([v.co for v in f.verts]) <= limit:
                continue
            e = min(f.edges, key=lambda e: e.calc_length())
            a, b = e.verts
            if a.is_boundary or b.is_boundary or e.is_boundary or e.seam:
                continue
            if only is not None and not all(v in only for g in set(a.link_faces) | set(b.link_faces) for v in g.verts):
                continue
            m = (a.co + b.co) / 2
            ok = True
            for g in set(a.link_faces) | set(b.link_faces):
                if e in g.edges:
                    continue
                pts = [m if v in (a, b) else v.co for v in g.verts]
                n = (pts[1] - pts[0]).cross(pts[2] - pts[0])
                if n.length < 1e-14 or n.normalized().dot(g.normal) < bend or aspect(pts) > max(limit, aspect([v.co for v in g.verts])):
                    ok = False
                    break
            if ok:
                mid = (flat.pop(a) + flat.pop(b)) / 2
                bmesh.ops.pointmerge(bm, verts=[a, b], merge_co=m)
                flat[a if a.is_valid else b] = mid
                done = True
        bm.normal_update()
        if not done:
            break


def pelvis_level(x, inner, outer):
    """The pelvis rule's blend (Ruling A117) at signed border distance ``x`` — depth into the part positive, distance
    out over the surrounding skin negative: 0 at ``-outer`` and beyond, 1 at ``inner`` and deeper, a smoothstep
    between (monotone in ``x``, no kink at either end)."""
    t = np.clip((np.asarray(x, float) + outer) / (inner + outer), 0, 1)
    return t * t * (3 - 2 * t)


def pelvis_weights(weights, floors, bone):
    """``weights`` (one ``{group: weight}`` per vertex) with ``bone``'s share of each vertex's total raised to at
    least its ``floors`` entry; the other groups shrink in proportion, so the total and their ratios stay. A vertex
    whose share already reaches its floor (every one with floor 0) keeps its weights exactly."""
    out = []
    for w, floor in zip(weights, floors):
        total = sum(w.values())
        own = w.get(bone, 0.)
        rest = total - own
        if total <= 0 or own >= floor * total or rest <= 0:
            out.append(dict(w))
            continue
        k = (1 - floor) * total / rest
        new = {g: x * k for g, x in w.items() if g != bone}
        new[bone] = floor * total
        out.append(new)
    return out


def harmonic_fill(n, edges, lengths, free, X, iterations=HARMONIC_ITERATIONS, tolerance=HARMONIC_TOLERANCE):
    """``X`` (n x k) with the rows of ``free`` (bool, n) replaced by the harmonic interpolation of the other rows
    along ``edges`` (m x 2) weighted by inverse length: the solution of the graph Laplace equation, by conjugate
    gradients per column started at ``X``. A free row joined to no fixed row through free rows keeps its start."""
    X = np.array(X, float)
    edges = np.asarray(edges, int).reshape(-1, 2)
    w = 1. / np.maximum(np.asarray(lengths, float), 1e-5)
    free = np.asarray(free, bool)
    a, b = edges[:, 0], edges[:, 1]
    keep = free[a] | free[b]
    a, b, w = a[keep], b[keep], w[keep]
    if not free.any() or not len(a):
        return X
    degree = np.bincount(a, w, n) + np.bincount(b, w, n)

    def spread(Y):
        return np.stack([np.bincount(a, w * Y[b, k], n) + np.bincount(b, w * Y[a, k], n) for k in range(Y.shape[1])], 1)

    def apply(Y):
        out = degree[:, None] * Y - spread(Y)
        out[~free] = 0
        return out

    fixed = X.copy()
    fixed[free] = 0
    rhs = spread(fixed)
    rhs[~free] = 0
    Y = X.copy()
    Y[~free] = 0
    r = rhs - apply(Y)
    d = r.copy()
    rr = (r * r).sum(0)
    limit = tolerance ** 2 * np.maximum((rhs * rhs).sum(0), 1e-30)
    for _ in range(iterations):
        if (rr <= limit).all():
            break
        Ad = apply(d)
        dAd = (d * Ad).sum(0)
        alpha = np.where(dAd > 0, rr / np.where(dAd > 0, dAd, 1), 0)
        Y += alpha * d
        r -= alpha * Ad
        rr_new = (r * r).sum(0)
        d = r + np.where(rr > 0, rr_new / np.where(rr > 0, rr, 1), 0) * d
        rr = rr_new
    return np.where(free[:, None], Y, X)


def position_groups(coordinates, quantum=1e-5):
    """One id per distinct position (``quantum`` grid): the seam copies of a vertex share it."""
    keys = np.round(np.asarray(coordinates, float) / quantum).astype(np.int64)
    _, ids = np.unique(keys, axis=0, return_inverse=True)
    return ids.ravel()


def blend_band_weights(obj, bone):
    """Replace the weights of the vertices flagged in BAND_ATTRIBUTE by the harmonic blend of the others (A169), on
    the welded mesh: seam copies are one node, an edge between two nodes weighs by its inverse length. Groups with
    no weight in or around the band are left alone; the result is normalised to the vertex's former total, weights
    under .001 dropped. Returns the number of band nodes and how many bones the blend covered."""
    me = obj.data
    flag = np.zeros(len(me.vertices))
    me.attributes[BAND_ATTRIBUTE].data.foreach_get('value', flag)
    co = np.zeros(len(me.vertices) * 3)
    me.vertices.foreach_get('co', co)
    co = co.reshape(-1, 3)
    gid = position_groups(co)
    n = int(gid.max()) + 1
    free = np.zeros(n, bool)
    np.logical_or.at(free, gid, flag > .5)
    ev = np.zeros(len(me.edges) * 2, int)
    me.edges.foreach_get('vertices', ev)
    ev = gid[ev.reshape(-1, 2)]
    ev = ev[ev[:, 0] != ev[:, 1]]
    ev = np.unique(np.sort(ev, 1), axis=0)
    pos = np.zeros((n, 3))
    pos[gid] = co
    lengths = np.linalg.norm(pos[ev[:, 0]] - pos[ev[:, 1]], axis=1)
    near = free.copy()
    near[ev[free[ev[:, 0]], 1]] = True
    near[ev[free[ev[:, 1]], 0]] = True
    names = [g.name for g in obj.vertex_groups]
    W = np.zeros((len(me.vertices), len(names)))
    for v in me.vertices:
        if near[gid[v.index]]:
            for g in v.groups:
                W[v.index, g.group] = g.weight
    total = W.sum(1)
    Wn = W / np.where(total > 0, total, 1)[:, None]
    G = np.zeros((n, len(names)))
    G[gid] = Wn
    cols = np.nonzero(G[near].max(0) > 0)[0]
    if bone in names:
        cols = np.union1d(cols, [names.index(bone)])
    sub = np.unique(np.concatenate([np.nonzero(near)[0]]))
    index = -np.ones(n, int)
    index[sub] = np.arange(len(sub))
    inside = (index[ev[:, 0]] >= 0) & (index[ev[:, 1]] >= 0)
    H = harmonic_fill(len(sub), index[ev[inside]], lengths[inside], free[sub], G[np.ix_(sub, cols)])
    H = np.clip(H, 0, None)
    H[H < 1e-3] = 0
    H /= np.maximum(H.sum(1, keepdims=True), 1e-12)
    for v in me.vertices:
        node = gid[v.index]
        if not free[node]:
            continue
        row = H[index[node]] * (total[v.index] if total[v.index] > 0 else 1.)
        for k in cols:
            group = obj.vertex_groups[int(k)]
            if row[list(cols).index(k)] > 0:
                group.add([v.index], float(row[list(cols).index(k)]), 'REPLACE')
            else:
                group.remove([v.index])
    return int(free.sum()), len(cols)


def body_roughness(bsdf):
    """``(image, value)``: the image whose green channel feeds the body's roughness (glTF metallic-roughness), or
    None and the input's own value when it is not textured that way."""
    node = bsdf.inputs['Roughness'].links[0].from_node if bsdf.inputs['Roughness'].links else None
    while node is not None and node.type != 'TEX_IMAGE':
        linked = [i for i in node.inputs if i.links]
        node = linked[0].links[0].from_node if linked else None
    return (node.image if node is not None else None), float(bsdf.inputs['Roughness'].default_value)


def pieces(bm):
    """Per vertex of ``bm`` the id of its connected piece, seam copies joined by position."""
    bm.verts.ensure_lookup_table()
    bm.verts.index_update()
    gid = position_groups([tuple(v.co) for v in bm.verts])
    parent = list(range(int(gid.max()) + 1))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for e in bm.edges:
        a, b = find(gid[e.verts[0].index]), find(gid[e.verts[1].index])
        if a != b:
            parent[a] = b
    return np.array([find(g) for g in gid])


def cut_loose(bm, before):
    """The vertices of ``bm`` cut loose by a face removal: ``before`` (an int vertex layer) holds each vertex's piece
    from ``pieces`` before the removal; of the pieces one former piece fell into, all but the largest go."""
    after = pieces(bm)
    former = np.array([v[before] for v in bm.verts])
    sizes = {}
    for f, a in zip(former, after):
        sizes[(f, a)] = sizes.get((f, a), 0) + 1
    keep = {}
    for (f, a), n in sizes.items():
        if n > keep.get(f, (None, -1))[1]:
            keep[f] = (a, n)
    return [v for v, f, a in zip(bm.verts, former, after) if keep[f][0] != a]


def skin_distance(adjacency, positions, seeds, limit):
    """Shortest distance along mesh edges from ``seeds`` (vertex indices) to every vertex within ``limit``."""
    import heapq
    dist = {i: 0. for i in seeds}
    heap = [(0., i) for i in seeds]
    while heap:
        d, i = heapq.heappop(heap)
        if d > dist.get(i, math.inf):
            continue
        for j in adjacency[i]:
            nd = d + float(np.linalg.norm(positions[i] - positions[j]))
            if nd <= limit and nd < dist.get(j, math.inf):
                dist[j] = nd
                heapq.heappush(heap, (nd, j))
    return dist


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
    level = level_region(body, arm, P) if P['level']['enabled'] else None
    ch = surface_chart(body, arm, P)
    M, Mi, N3, Ni3, bvh = ch['M'], ch['Mi'], ch['N3'], ch['Ni3'], ch['bvh']
    c, xm, th, S, prof, pn, i0 = ch['c'], ch['xm'], ch['th'], ch['S'], ch['prof'], ch['pn'], ch['i0']
    arc, s_start, underside, scale, chart = ch['arc'], ch['s_start'], ch['underside'], ch['scale'], ch['chart']
    sstep = lambda x: (lambda y: y * y * (3 - 2 * y))(np.clip(x, 0, 1))
    # Where the levelling cut its region short, the part ends there too (A77b): it fades out over the region's fall
    # before that point and takes no skin beyond it — past it lies the mesher's skin between the closing legs, not a
    # surface to build on.
    end_point = level.pop('end_point') if level else None
    s_end = float(chart(np.array([end_point]))[0][0]) if end_point is not None else None
    end_fade = (lambda s: sstep((s_end - s) / P['region']['fall'])) if s_end is not None else (lambda s: 1.)


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
        e = end_fade(s)
        return dict(m=m * e, h_env=h_env * e, h=h * e, groove=gn * e, ridge=ridge_n * e,
                    folds=gn * np.maximum(inner_n, hood_n) * e, nub=gn * nub_n * e, pocket=pocket_n * gn * e,
                    centre=window(s, cl['s0'] - .01, cl['s1'] + .005, .01) * np.exp(-(u / .012) ** 2) * e)


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
            turn = sel & (sg * u_b > 0) & (fac_b < .5) & (fac_b > -.3)
            side.append(np.min(sg * u_b[turn]) if turn.any() else .06)
        WA.append(min(side))
    WA = np.convolve(np.pad(WA, 2, mode='edge'), np.ones(5) / 5, mode='valid')
    print('usable half width mm', [(round(a_, 3), round(w_ * 1000, 1)) for a_, w_ in zip(WS[::3], WA[::3])])
    F = fields(s_b, u_b, fac_b, r_b)
    R = P['region']
    near = (s_b > R['s0'] - R['fall'] - .01) & (s_b < R['s1'] + R['fall'] + .01) & (np.abs(u_b) < R['u'] + R['fall'] + .01) & (np.abs(r_b) < .04)
    near &= np.abs(u_b) < np.interp(s_b, WS, WA) + .01
    near &= fac_b > .2
    if s_end is not None:
        near &= s_b < s_end
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
    gname = {g.index: g.name for g in body.vertex_groups}
    VW = [{gname[g.group]: g.weight for g in v.groups} for v in body.data.vertices]
    # The displaced patch is mended (``flip_slivers``) and placed again from the mended flat patch, three times (a
    # mend changes the faces the next placement displaces, A77c), then placed once more.
    for mend in [True] * MEND_ROUNDS + [False]:
        bm.verts.ensure_lookup_table()
        bm.verts.index_update()
        Q = np.array([tuple(v.co) for v in bm.verts])
        border = np.array([v.is_boundary for v in bm.verts])
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
        if not mend:
            break
        flat = {v: Vector(q) for v, q in zip(bm.verts, Q)}
        flip_slivers(bm, flat)
        for v in bm.verts:
            v.co = flat[v]
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
    clean = sstep((FQ['m'] - .35) / .5)
    clean[border] = 0
    clean_attribute = me.attributes.new('Clean', 'FLOAT', 'POINT')
    for i, value in enumerate(clean):
        clean_attribute.data[i].value = float(value)
    ca = me.color_attributes.new('Tint', 'FLOAT_COLOR', 'POINT')
    for i, t in enumerate(tint):
        ca.data[i].color = (*t, 1)
    pv = P['pelvis']
    pelvis = None
    if pv['share'] > 0:
        pelvis_bone = resolve_bone(arm.data.bones, pv['bone']).name
        rim = Q[border]
        kd_rim = KDTree(len(rim))
        for i_, q_ in enumerate(rim):
            kd_rim.insert(Vector(q_), i_)
        kd_rim.balance()
        depth = np.array([0. if border[i_] else kd_rim.find(Vector(q_))[2] for i_, q_ in enumerate(Q)])
        inner_m, outer_m = pv['ring'] * depth.max(), pv['spread'] * depth.max()
        share_of = lambda ws: np.array([w.get(pelvis_bone, 0.) / (sum(w.values()) or 1) for w in ws])
        before = share_of(qw)
        floors = pv['share'] * pelvis_level(depth, inner_m, outer_m)
        qw = pelvis_weights(qw, floors, pelvis_bone)
        after = share_of(qw)
        # The surrounding skin: body vertices off the replaced faces, by their distance along the skin from the
        # part's welded border (the border's own body vertices are the seeds, at distance 0 like the part's border).
        replaced = np.zeros(len(V), int)
        for poly in body.data.polygons:
            for v in poly.vertices:
                replaced[v] += 1
        for pi in sel_polys:
            for v in body.data.polygons[pi].vertices:
                replaced[v] -= 1
        kept = replaced > 0
        adjacency = [[] for _ in range(len(V))]
        for e_ in body.data.edges:
            a_, b_ = e_.vertices
            if kept[a_] and kept[b_]:
                adjacency[a_].append(b_); adjacency[b_].append(a_)
        # Seam copies (one position, several vertices) are joined at distance 0, so they get one weight.
        for grp in key.values():
            for a_ in grp:
                adjacency[a_].extend(b_ for b_ in grp if b_ != a_ and kept[a_] and kept[b_])
        seeds = sorted({j_ for q_ in rim for j_ in key.get(tuple(np.round(q_ / 1e-5).astype(int)), []) if kept[j_]})
        hull = {i_: d_ for i_, d_ in skin_distance(adjacency, V, seeds, outer_m).items()} if outer_m > 0 else {}
        hull_idx = sorted(hull)
        hull_floor = pv['share'] * pelvis_level(-np.array([hull[i_] for i_ in hull_idx]), inner_m, outer_m)
        hull_new = pelvis_weights([VW[i_] for i_ in hull_idx], hull_floor, pelvis_bone)
        hull_raised = 0
        for i_, old, new in zip(hull_idx, (VW[i_] for i_ in hull_idx), hull_new):
            if new == old:
                continue
            hull_raised += 1
            for g, x in new.items():
                vg = body.vertex_groups.get(g) or body.vertex_groups.new(name=g)
                vg.add([i_], x, 'REPLACE')
        band_body = np.zeros(len(V))
        band_body[hull_idx] = 1.
        pelvis = {'bone': pelvis_bone, 'share': pv['share'], 'ring_m': round(float(inner_m), 4),
                  'spread_m': round(float(outer_m), 4), 'depth_max_m': round(float(depth.max()), 4),
                  'raised': int((after > before + 1e-9).sum()), 'core_vertices': int((floors >= pv['share'] - 1e-9).sum()),
                  'skin_raised': hull_raised,
                  'mean_share_before': round(float(before.mean()), 3), 'mean_share_after': round(float(after.mean()), 3)}
        print('pelvis rule', pelvis)
    band_part = np.zeros(len(Q))
    if pelvis is not None:
        band_part = (floors < pv['share'] - 1e-9).astype(float)
    for i, w in enumerate(qw):
        for g, x in w.items():
            if x > 0:
                vg = part.vertex_groups.get(g) or part.vertex_groups.new(name=g)
                vg.add([i], x, 'REPLACE')
    for poly in me.polygons:
        poly.use_smooth = True

    # Bake raw colour, tint, clean factor and coverage on the chart UV map.
    bpy.context.view_layer.objects.active = part
    for o in bpy.context.scene.objects:
        o.select_set(o is part)
    bake_uv = me.uv_layers.new(name='bake')
    me.uv_layers.active = bake_uv
    # Use the undisplaced chart so the height field has no overlapping islands.
    su = np.stack([u_q, s_q], 1)
    lo, hi = su.min(0), su.max(0)
    span = (hi - lo).max() * 1.02
    for loop in me.loops:
        uv = (su[loop.vertex_index] - lo) / span + .01
        bake_uv.data[loop.index].uv = tuple(uv)
    body_bsdf = next(nd for nd in body.active_material.node_tree.nodes if nd.type == 'BSDF_PRINCIPLED')
    img = body_bsdf.inputs['Base Color'].links[0].from_node.image
    rough_image, rough_value = body_roughness(body_bsdf)
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
    nt.links.new(uvn.outputs['UV'], tex.inputs['Vector'])
    nt.links.new(emit.outputs['Emission'], out.inputs['Surface'])
    cla = Nd('ShaderNodeAttribute'); cla.attribute_name = 'Clean'
    white = Nd('ShaderNodeRGB'); white.outputs[0].default_value = (1, 1, 1, 1)
    me.materials.append(mat)
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'; sc.cycles.device = 'CPU'; sc.cycles.samples = 1; sc.render.bake.margin = 24
    BS = P['bake']

    def bake_layer(socket, data=False):
        """Read each emission layer back in the same image space (``data``: unconverted values, no colour space)."""
        image = bpy.data.images.new('layer', BS, BS, alpha=False)
        if data:
            image.colorspace_settings.name = 'Non-Color'
        image.generated_color = (0, 0, 0, 1)
        node = Nd('ShaderNodeTexImage'); node.image = image; nt.nodes.active = node
        nt.links.new(socket, emit.inputs['Color'])
        try:
            bpy.ops.object.bake(type='EMIT')
            pixels = np.empty(BS * BS * 4, np.float32)
            image.pixels.foreach_get(pixels)
            return pixels.reshape(BS, BS, 4)
        finally:
            nt.nodes.remove(node)
            bpy.data.images.remove(image)

    raw = bake_layer(tex.outputs['Color'])
    rough_px = None
    if rough_image is not None:
        # The body's roughness rides along like its colour (A169): a constant on the part stood out at the border.
        rtex = Nd('ShaderNodeTexImage'); rtex.image = rough_image
        rsep = Nd('ShaderNodeSeparateColor')
        nt.links.new(uvn.outputs['UV'], rtex.inputs['Vector'])
        nt.links.new(rtex.outputs['Color'], rsep.inputs['Color'])
        rough_px = bake_layer(rsep.outputs['Green'], data=True)[..., 0]
    tint_px = bake_layer(att.outputs['Color'])
    clean_px = bake_layer(cla.outputs['Fac'])[..., 0]
    cover = bake_layer(white.outputs[0])[..., 0] > .5

    # Average 4x4 blocks; pad only to preserve arbitrary positive bake sizes.
    G = (BS + 3) // 4
    def small(values):
        padding = [(0, G * 4 - BS), (0, G * 4 - BS)] + [(0, 0)] * (values.ndim - 2)
        padded = np.pad(values, padding, mode='edge')
        return padded.reshape(G, 4, G, 4, *values.shape[2:]).mean((1, 3))

    rs, cs = small(raw[..., :3]), small(clean_px)
    vs = small(cover.astype(float)) > .5
    unknown = vs & (cs > .5)
    known = vs & ~unknown
    f = rs.copy()
    if unknown.any():
        f[unknown] = rs[known].mean(0) if known.any() else rs[unknown].mean(0)
    wv = vs.astype(float)[..., None]
    # Jacobi: each unknown uses four covered neighbours from the previous step.
    _common.progress('filling')
    for _ in range(P['fill_iterations']):
        acc = np.zeros_like(f); cnt = np.zeros_like(wv)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            acc += np.roll(np.roll(f * wv, dy, 0), dx, 1)
            cnt += np.roll(np.roll(wv, dy, 0), dx, 1)
        f = np.where(unknown[..., None], acc / np.maximum(cnt, 1e-6), f)
    fill = np.repeat(np.repeat(f, 4, 0), 4, 1)[:BS, :BS]
    cw = clean_px[..., None]
    final = (raw[..., :3] * (1 - cw) + fill * cw) * tint_px[..., :3]
    outpx = np.ones((BS, BS, 4), np.float32)
    outpx[..., :3] = final
    bimg.pixels.foreach_set(outpx.ravel())
    bimg.pack()
    nt.nodes.clear()
    out = Nd('ShaderNodeOutputMaterial'); bsdf = Nd('ShaderNodeBsdfPrincipled'); tb = Nd('ShaderNodeTexImage'); tb.image = bimg
    nt.links.new(tb.outputs['Color'], bsdf.inputs['Base Color']); nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    bsdf.inputs['Roughness'].default_value = rough_value
    if rough_px is not None:
        rimg = bpy.data.images.new('part_rough', BS, BS, alpha=False)
        rimg.colorspace_settings.name = 'Non-Color'
        rpx = np.ones((BS, BS, 4), np.float32)
        rpx[..., 0] = rpx[..., 2] = 0
        rpx[..., 1] = rough_px
        rimg.pixels.foreach_set(rpx.ravel())
        rimg.pack()
        tr = Nd('ShaderNodeTexImage'); tr.image = rimg
        rs = Nd('ShaderNodeSeparateColor')
        nt.links.new(tr.outputs['Color'], rs.inputs['Color'])
        nt.links.new(rs.outputs['Green'], bsdf.inputs['Roughness'])
    # One-sided like the body (A169): a double-sided part showed its dark back wherever the skin folded over it.
    mat.use_backface_culling = True
    me.uv_layers.remove(me.uv_layers['body'])
    me.uv_layers['bake'].name = uvname
    me.attributes.remove(clean_attribute)
    while me.color_attributes:
        me.color_attributes.remove(me.color_attributes[0])

    # Replace the region faces of the body and weld the patch in.
    _bmp = bmesh.new(); _bmp.from_mesh(me)
    part_border_local = [v.co.copy() for v in _bmp.verts if v.is_boundary]
    _bmp.free()
    # The skin facing inward under the region (the inner wall of a double-walled body, a fold's underside) stays
    # (A169): one-sided like the rest of the body it is not seen from outside, and removing it opened the outer skin.
    # In the pelvis band it is blended with the skin around it, so it moves with it.
    inner_wall = {t.polygon_index for t in body.data.loop_triangles if all(
        fac_b[v] < -.2 and -.04 < r_b[v] < 0
        and R['s0'] - R['fall'] < s_b[v] < R['s1'] + R['fall']
        and abs(u_b[v]) < R['u'] + R['fall'] for v in t.vertices)}
    print('inner wall faces kept', len(inner_wall))
    if pelvis is not None:
        for pi in inner_wall:
            band_body[list(body.data.polygons[pi].vertices)] = 1.
        body.data.attributes.new(BAND_ATTRIBUTE, 'FLOAT', 'POINT').data.foreach_set('value', band_body.astype(np.float32))
    bmb = bmesh.new(); bmb.from_mesh(body.data); bmb.faces.ensure_lookup_table()
    piece_layer = bmb.verts.layers.int.new('_piece')
    for v, piece in zip(bmb.verts, pieces(bmb)):
        v[piece_layer] = int(piece)
    bmesh.ops.delete(bmb, geom=[bmb.faces[i] for i in sel_polys], context='FACES')
    loose = cut_loose(bmb, piece_layer)
    if loose:
        bmesh.ops.delete(bmb, geom=loose, context='VERTS')
    print('cut-loose skin vertices removed', len(loose))
    bmb.verts.layers.int.remove(piece_layer)
    bmb.to_mesh(body.data); bmb.free()
    if pelvis is not None:
        part_band = me.attributes.new(BAND_ATTRIBUTE, 'FLOAT', 'POINT')
        part_band.data.foreach_set('value', band_part.astype(np.float32))
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
    if pelvis is not None:
        nodes, bones = blend_band_weights(body, pelvis['bone'])
        pelvis['band_nodes'] = nodes
        print('pelvis band blended harmonically', nodes, 'nodes', bones, 'bones')
        body.data.attributes.remove(body.data.attributes[BAND_ATTRIBUTE])
    print('open patch border edges after weld', open_left, 'part material', body.data.materials[mi_part].name, 'body tris', len(body.data.polygons))

    _common.progress('exporting')
    bpy.ops.export_scene.gltf(filepath=str(output), export_format='GLB', export_apply=False,
                              export_yup=True, export_skins=True, export_animations=True,
                              export_morph=True, export_extras=True, export_all_influences=False)
    _common.body_meshes_first(output)
    s_open = opening_s(P['pocket'], s_end, R['fall'])
    opening = opening_metric(prof, pn, S, s_open, xm, Mi, Ni3) if s_open is not None else None
    return {'status': 'applied', 'reason': '', 'anchor': prof[i0].tolist(),
            'underside_m': underside, 'scale': scale, 'front_corner': prof[i0].tolist(),
            'inner_wall_faces_kept': len(inner_wall), 'cut_loose_vertices_removed': len(loose),
            'patch_tris': patch_tris,
            'border_vertices': int(border.sum()), 'open_border_edges': open_left,
            'border_max_abs_h': float(np.abs(hq[border]).max()) if border.any() else 0.,
            'usable_half_width': float(np.interp((P['cleft']['s0'] + P['cleft']['s1']) / 2, WS, WA)),
            'inner_scale': P['inner_scale'], 'nub_scale': P['nub_scale'],
            **({'part_end_s': round(s_end, 4)} if s_end is not None else {}),
            **({'pelvis': pelvis} if pelvis else {}),
            **({'opening': opening} if opening is not None else {}), **(level or {})}


def inset_part(args):
    """Runner entry; failures leave the caller's staged body untouched."""
    groups = [g for g in args['params'].get('groups', []) if g.get('enabled', True) and g['op'] == 'inset_part']
    if len(groups) != 1:
        raise ValueError('Exactly one inset part group is required')
    _common.reset_scene()
    _common.import_model(args['inputs']['model'])
    output = Path(args['out_dir']) / 'model.glb'
    _common.progress('building_part')
    metrics = build_part(groups[0], output)
    per_group = {groups[0]['id']: metrics}
    return {'status': 'applied', 'reason': '', 'metrics': per_group, 'groups': per_group}, {'model': str(output)}


if __name__ == '__main__':
    _common.main(inset_part)
