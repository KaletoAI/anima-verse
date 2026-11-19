"""Open the mouth of a rigged humanoid body: a slit along the measured lip line with a closed channel behind it.

World metres, front -Y, up +Z, side +X (the glTF importer's frame of a normalised model).

The mesher delivers a face whose mouth is drawn, not open. This op (Ruling A203, part 1)

1. MEASURES the lip line. A grid of rays from the front around the head joint gives the face's depth and its base
   colour. The nose tip is the front-most point of the window above the head joint, the chin edge the first row
   below it that lies ``chin_drop`` behind the tip. Between them the lip line is the row with the strongest LINE
   CONTRAST (the mean luminance ``line.span`` above and below minus its own, over a band around the midline),
   weighted by a wide prior around ``line.prior`` of the chin-to-nose span and by the rows' REDNESS (red minus
   green against the window's median: a lip line lies between lips, a moustache edge or the shadow under the lower
   lip does not). From there the line is tracked sideways
   (the darkest of the rows next to the last one) until its contrast falls under ``line.corner`` of the central
   contrast: the mouth corners. A parabola through the tracked rows is the lip line v(s).
2. CUTS the skin along it between the corners: the skin faces around the line are subdivided (seam copies alike, so
   no T-junction), every edge the line crosses is split on the line, the faces are split along it and the path is
   ripped. Upper and lower lip keep their texture, UVs and weights (all interpolated by the split) and still meet.
3. BUILDS the channel: a pouch whose rim is the ripped path, running ``depth`` along the axis from the opening
   toward the top of the throat (the midpoint of the head and neck joints, the A193 axis), its width going from the
   mouth's to 2 x ``radius``. Upper and lower wall coincide at rest (the mouth is closed) and share their side and
   back vertices, so the pouch is closed. It has its own material without a texture: the colour of the darkest
   lip-line texel, darkened (``inside.shade``) and fully rough.
4. CLEARS the space the open channel takes: meshers leave walls and lumps inside the head (an inner shell a few
   millimetres under the skin, a modelled oral cavity). A face that is neither the cut skin nor the pouch, has a
   vertex inside the channel's core (from ``clear.start`` behind the opening, ``clear.margin`` inside its width,
   within the upper wall's rise) and is inner geometry (not reached from the cut through the mesh) is removed.
   Inner geometry under the pouch is not removed: it goes down with the lower wall (5). A second pass removes what
   would stand between the two walls with the mouth fully open, from ``clear.behind`` behind the lip line (a lump
   joined to the skin somewhere, which keeps its solved share).
5. OPENS it (part 2): the shape key ``mouth_open`` (0..1, a glTF morph target). Every vertex turns about the jaw's
   hinge (side axis) by its JAW SHARE w x ``jaw.open_deg``; the upper lip lifts by ``lift``. The share is computed,
   not painted: 1 on the lower rim of the cut and on the chin's front (``share.chin``), 0 on the upper rim (both
   rims meet at 1/2 within ``share.corner`` of the mouth corners), 0 above the upper lip and on the border of the
   lower face (``share.reach``); between them the harmonic interpolation
   (inverse-edge-length Laplace) on the skin with its seam copies joined — the cut is a border of that domain, so
   the share jumps across the lips and runs smoothly around the corners. Skin the cut does not reach through the
   mesh (an inner shell, lumps) takes the share of the nearest solved vertex; a face of it that the open mouth
   would tear (shares more than ``share.tear`` apart) is removed. The pouch's lower wall follows the jaw by
   ``lower_follow`` (1 at the lips, 0 at the back), the upper wall stays, their shared sides lie between.

6. THE JAW BONE (part 3): when the group declares a bone (``chains``: Jaw, child of Head), it is created at the
   hinge and the jaw share becomes its WEIGHT (taken from each vertex's other weights in proportion). Turning the
   bone about the body's side axis by ``jaw.open_deg`` (written on the bone as ``mouth_open_deg``) opens the mouth;
   the shape key then holds only what a bone cannot do — the upper lip's lift, the dome and the lips' rounded
   edge (``lip.radius``: open, the cut corner between skin and wall is a fillet, not a blade).

The op reports its ``opening`` (centre, inward axis, depth, radius, half width; glTF axes, bind space) for the
mouth channel of the collision record. The per-character override (``override``: offset_mm [side, up, front],
radius_scale, depth_scale, tilt_deg) moves the measured line, scales the pouch and tilts its axis; the opening
reports what was built. Without an override the axis is tilted by ``DEFAULTS.override.tilt_deg`` = -20 degrees
(``app/core/mouth_channel.TILT_DEFAULT_DEG``, owner decision 2026-11-19): turned 20 degrees about the side axis away
from the throat, toward the top of the head. A stored override's tilt is absolute (0 = the measured axis).
"""
import copy
import math
import sys
from pathlib import Path

_SCRIPT_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPT_DIR)
import _common
from attached_part import base_color_source, resolve_bone
from inset_part import harmonic_fill
import mouth_teeth
from mouth_math import (_smooth, _sstep, corners, jaw_hinge, lip_fillet, lip_row, lower_follow, ring_depths,
                        track_line, turned)
import mouth_math
sys.path.remove(_SCRIPT_DIR)
import bpy
import bmesh
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

DEFAULTS = {
    'head_bone': 'Head', 'neck_bone': 'Neck',
    # The ray grid around the head joint: half width, reach below and above it, steps.
    'grid': {'half_width': .06, 'below': .13, 'above': .10, 'step_s': .001, 'step_v': .0005},
    'nose_window': [-.05, .08], 'chin_drop': .05,
    'line': {'prior': .54, 'prior_sigma': .2, 'red_gain': 1., 'band': .008, 'span': .004, 'min_contrast': .03,
             'corner': .3, 'half_min': .015, 'half_max': .03},
    # The skin subdivided around the line: margin past the corners, height above and below, edge lengths.
    'patch': {'margin': .006, 'height': .012, 'behind': .012, 'near': .004, 'edge_near': .002, 'edge_far': .003},
    'depth': .08, 'radius': .02,
    # Ring spacing of the pouch (first step, growth), where its width and the lip curve have blended out.
    'rings': {'first': .003, 'growth': 1.15, 'taper': .03, 'flatten': .02, 'column': .003},
    # The jaw's hinge behind / above the opening (for a body whose Hips-to-Head distance is ``reference``; scaled
    # with it within ``scale``) and its full opening angle.
    'jaw': {'back': .085, 'up': .03, 'open_deg': 30., 'reference': .6, 'scale': [.8, 1.25]},
    # The jaw share's fixed regions (module docstring 5) and the upper lip's lift with the mouth fully open.
    'share': {'chin': .010, 'chin_reach': .045, 'chin_back': .03, 'chin_width': .6, 'corner': .008, 'above': .012,
              'reach': .075, 'below': .09, 'behind': .09, 'tear': .5},
    'lift': {'height': .0025, 'band': .008, 'depth': .015},
    'dome': {'height': .008, 'blend': .012},
    'clear': {'start': .004, 'margin': .002, 'above': .003, 'below': .003, 'behind': .006, 'inside': .001},
    # The lip's rounded edge with the mouth open: the fillet's radius at the cut.
    'lip': {'radius': .0045},
    'inside': {'shade': .6},
    'override': {'offset_mm': [0., 0., 0.], 'radius_scale': 1., 'depth_scale': 1., 'tilt_deg': -20.},
}
SHAPE_KEY = 'mouth_open'


class NoMouth(ValueError):
    """The face shows no mouth to open (no lip line, no texture, ...): a finding about this body, not a failure."""

INSIDE_MATERIAL = 'mouth_channel'
SNAP_M = .00004               # a vertex closer to the line than this is moved off it before the cut


def parameters(raw):
    """Merge nested overrides, rejecting unknown keys and values out of range."""
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
    p = merge(DEFAULTS, raw or {}, 'params')
    if min(p['depth'], p['radius'], p['chin_drop'], *p['grid'].values()) <= 0:
        raise ValueError('Expected positive lengths')
    if min(v for k, v in p['patch'].items()) <= 0 or min(p['rings'].values()) <= 0 or p['rings']['growth'] < 1:
        raise ValueError('Expected positive patch and ring lengths, ring growth at least 1')
    jaw = p['jaw']
    if min(jaw['back'], jaw['reference'], jaw['scale'][0]) <= 0 or jaw['scale'][0] > jaw['scale'][1] \
            or not 0 < jaw['open_deg'] <= 45 or min(p['clear'].values()) < 0 or p['lip']['radius'] < 0:
        raise ValueError('Jaw: positive lengths, open_deg within (0, 45]; clear: nonnegative lengths')
    line = p['line']
    if not 0 < p['inside']['shade'] <= 1:
        raise ValueError('Inside: shade within (0, 1]')
    if min(p['dome'].values()) <= 0 or min(p['share'].values()) <= 0 \
            or min(p['lift']['band'], p['lift']['depth']) <= 0 or p['lift']['height'] < 0:
        raise ValueError('Share and lift: positive lengths')
    if not 0 < line['prior'] < 1 or min(line['prior_sigma'], line['band'], line['span'], line['corner']) <= 0 \
            or not 0 < line['half_min'] <= line['half_max']:
        raise ValueError('Line: prior within (0, 1), positive lengths, half_min up to half_max')
    if p['nose_window'][0] >= p['nose_window'][1]:
        raise ValueError('Invalid nose window')
    o = p['override']
    if max(abs(v) for v in o['offset_mm']) > 50 or not .5 <= o['radius_scale'] <= 2 \
            or not .5 <= o['depth_scale'] <= 2 or abs(o['tilt_deg']) > 45:
        raise ValueError('Override: offsets within 50 mm, scales within [0.5, 2], tilt within 45 degrees')
    return p


def _gltf(v):
    """Blender (x, y, z) -> glTF Y-up (x, z, -y), as plain floats."""
    return [float(v[0]), float(v[2]), float(-v[1])]


def measure(body, arm, P):
    """The lip line of ``body``: a dict with the midline ``s0``, the half width ``hw``, the line's parabola
    ``coef`` (v = c0 + c1 (s - s0) + c2 (s - s0)^2, world z over world x), the surface depth along it and the
    landmarks. ValueError with the reason when the face does not show one."""
    me = body.data
    M = body.matrix_world
    me.calc_loop_triangles()
    V = np.array([tuple(M @ v.co) for v in me.vertices])
    tris = np.array([tuple(t.vertices) for t in me.loop_triangles])
    bvh = BVHTree.FromPolygons([Vector(p) for p in V], [tuple(int(i) for i in t) for t in tris])
    head = arm.matrix_world @ resolve_bone(arm.pose.bones, P['head_bone']).head
    neck = arm.matrix_world @ resolve_bone(arm.pose.bones, P['neck_bone']).head
    g = P['grid']
    S = head.x + np.arange(-g['half_width'], g['half_width'] + 1e-9, g['step_s'])
    Z = head.z + np.arange(-g['below'], g['above'] + 1e-9, g['step_v'])
    depth = np.full((len(Z), len(S)), np.nan)
    face = -np.ones((len(Z), len(S)), int)
    front = float(V[:, 1].min()) - .05
    toward = Vector((0, 1, 0))
    for i, z in enumerate(Z):
        for j, s in enumerate(S):
            hit = bvh.ray_cast(Vector((s, front, z)), toward)
            if hit[0] is not None:
                depth[i, j] = hit[0].y
                face[i, j] = hit[2]
    # Base colour at the hits (barycentric in the hit triangle's corner UVs), read from the HIT FACE's material:
    # a body may carry more than one (a built part has its own texture). A hit on a material without a base
    # colour texture counts as not seen.
    if not me.uv_layers.active:
        raise NoMouth('Body requires a UV map')
    uv = np.empty(len(me.loops) * 2)
    me.uv_layers.active.data.foreach_get('uv', uv)
    uv = uv.reshape(-1, 2)
    tri_loops = np.array([tuple(t.loops) for t in me.loop_triangles])
    tri_material = np.array([t.material_index for t in me.loop_triangles])
    ok = face >= 0
    fi = face[ok]
    A, B, C = (V[tris[fi, k]] for k in range(3))
    Pn = np.stack([np.broadcast_to(S, depth.shape)[ok], depth[ok], np.broadcast_to(Z[:, None], depth.shape)[ok]], 1)
    v0, v1, v2 = B - A, C - A, Pn - A
    d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
    d20, d21 = (v2 * v0).sum(1), (v2 * v1).sum(1)
    den = np.where(np.abs(d00 * d11 - d01 * d01) < 1e-18, 1e-18, d00 * d11 - d01 * d01)
    b1 = (d11 * d20 - d01 * d21) / den
    b2 = (d00 * d21 - d01 * d20) / den
    hit_uv = (uv[tri_loops[fi, 0]] * (1 - b1 - b2)[:, None] + uv[tri_loops[fi, 1]] * b1[:, None]
              + uv[tri_loops[fi, 2]] * b2[:, None])
    colour = np.full((len(fi), 3), np.nan)
    hit_material = tri_material[fi]
    for slot in np.unique(hit_material):
        material = me.materials[int(slot)] if int(slot) < len(me.materials) else None
        tree = material.node_tree if material is not None and material.use_nodes else None
        shader = next((nd for nd in tree.nodes if nd.type == 'BSDF_PRINCIPLED'), None) if tree else None
        image = base_color_source(shader.inputs['Base Color'])[0] if shader is not None else None
        if image is None:
            continue
        W, H = image.size
        px = np.empty(W * H * 4, np.float32)
        image.pixels.foreach_get(px)
        px = px.reshape(H, W, 4)
        of = hit_material == slot
        colour[of] = px[(np.floor(hit_uv[of, 1] % 1 * H).astype(int)) % H,
                        (np.floor(hit_uv[of, 0] % 1 * W).astype(int)) % W, :3]
    if not np.isfinite(colour).any():
        raise NoMouth('The face has no base colour texture')
    rgb = np.full(depth.shape + (3,), np.nan)
    rgb[ok] = colour
    lum = np.full(depth.shape, np.nan)
    lum[ok] = colour @ np.array([.3, .6, .1])
    red = np.full(depth.shape, np.nan)
    red[ok] = colour[:, 0] - colour[:, 1]
    uv_grid = np.full(depth.shape + (2,), np.nan)
    uv_grid[ok] = hit_uv

    # Nose tip: the front-most point of the window, on the depth smoothed over 3 mm.
    blur = np.stack([_smooth(depth[:, j], max(1, int(round(.003 / g['step_v'])))) for j in range(len(S))], 1)
    blur = np.stack([_smooth(blur[i], max(1, int(round(.003 / g['step_s'])))) for i in range(len(Z))], 0)
    window = (Z[:, None] >= head.z + P['nose_window'][0]) & (Z[:, None] <= head.z + P['nose_window'][1]) \
        & (np.abs(S[None, :] - head.x) <= .045) & np.isfinite(blur)
    if not window.any():
        raise NoMouth('No face in front of the head joint')
    nose_i, nose_j = np.unravel_index(int(np.argmin(np.where(window, blur, np.inf))), blur.shape)
    nose_y = float(blur[nose_i, nose_j])
    band = max(1, int(round(.003 / g['step_s'])))
    column = np.nanmin(depth[:, max(0, nose_j - band):nose_j + band + 1], axis=1)
    chin_i = next((i for i in range(nose_i, -1, -1)
                   if not np.isfinite(column[i]) or column[i] > nose_y + P['chin_drop']), None)
    if chin_i is None:
        raise NoMouth('No chin edge below the nose')
    line = P['line']
    wide = max(1, int(round(line['band'] / g['step_s'])))
    band_lum = np.nanmean(lum[:, max(0, nose_j - wide):nose_j + wide + 1], axis=1)
    band_red = np.nanmean(red[:, max(0, nose_j - wide):nose_j + wide + 1], axis=1)
    found = lip_row(band_lum, band_red, Z, float(Z[nose_i]), float(Z[chin_i]), line)
    if isinstance(found, str):
        raise NoMouth(found)
    row, contrast = found
    cols, rows, contrasts = track_line(lum, row, nose_j, line, g['step_s'], g['step_v'])
    left, right = corners(cols, contrasts, nose_j, line, g['step_s'])
    half = (S[right] - S[left]) / 2
    s0 = (S[right] + S[left]) / 2
    hw = float(np.clip(half, line['half_min'], line['half_max']))
    if half < line['half_min']:
        # The contrast faded early (a pale line): the mouth is centred on the nose instead of on a short piece.
        s0 = float(S[nose_j])
    inside = (S[cols] >= s0 - hw) & (S[cols] <= s0 + hw)
    coef = np.polyfit(S[cols][inside] - s0, Z[rows][inside], 2)[::-1]
    o = P['override']
    s0 += o['offset_mm'][0] / 1000
    coef = coef.copy()
    coef[0] += o['offset_mm'][1] / 1000
    return {'V': V, 'tris': tris, 'bvh': bvh, 'S': S, 'Z': Z, 'depth': depth, 'lum': lum, 'uv': uv_grid, 'rgb': rgb,
            'head': head, 'neck': neck, 's0': float(s0), 'hw': hw, 'coef': [float(c) for c in coef],
            'nose': [float(S[nose_j]), nose_y, float(Z[nose_i])], 'chin_z': float(Z[chin_i]),
            'contrast': contrast, 'tracked_half_width': float(half)}


def _line_z(coef, s0, x):
    d = np.asarray(x) - s0
    return coef[0] + coef[1] * d + coef[2] * d * d


def _grid_at(grid, S, Z, x, z):
    """Nearest finite grid value around (x, z) (within 2 cells), NaN without one."""
    j = int(round((x - S[0]) / (S[1] - S[0])))
    i = int(round((z - Z[0]) / (Z[1] - Z[0])))
    best, value = None, np.nan
    for di in range(-2, 3):
        for dj in range(-2, 3):
            a, b = i + di, j + dj
            if 0 <= a < grid.shape[0] and 0 <= b < grid.shape[1] and np.all(np.isfinite(grid[a, b])):
                d = di * di + dj * dj
                if best is None or d < best:
                    best, value = d, grid[a, b]
    return value


def _key(p):
    return tuple(int(round(c / 1e-5)) for c in p)


def _split_faces(bm, faces, made, tag):
    """Triangulate the faces whose edges got new vertices ``made`` (BMVert set), fan-free: one template per count
    of split edges, as the inset part's subdivision. New faces inherit ``tag`` values of their source."""
    for face in faces:
        if not face.is_valid:
            continue
        value = face[tag]
        loop_verts = [l.vert for l in face.loops]
        corner = [v for v in loop_verts if v not in made]
        if len(corner) != 3 or len(loop_verts) == 3:
            continue
        # Rotate so the walk starts at a corner; mids[i] is the new vertex after corner i (or None).
        start = next(i for i, v in enumerate(loop_verts) if v not in made)
        walk = loop_verts[start:] + loop_verts[:start]
        mids, i = [], 0
        while i < len(walk):
            nxt = walk[i + 1] if i + 1 < len(walk) else None
            if nxt is not None and nxt in made:
                mids.append(nxt)
                i += 2
            else:
                mids.append(None)
                i += 1
        corners_ = [v for v in walk if v not in made]
        count = sum(m is not None for m in mids)
        index = next(i for i in range(3) if mids[i] is not None and (count != 2 or mids[(i + 1) % 3] is not None))
        a, b, d = corners_[index:] + corners_[:index]
        m, n, q = mids[index:] + mids[:index]
        cuts = [(m, d)] if count == 1 else [(m, n), (m, d)] if count == 2 else [(m, n), (n, q), (q, m)]
        pieces = [face]
        for x, y in cuts:
            for piece in list(pieces):
                if x in piece.verts and y in piece.verts and not any(
                        x in e.verts and y in e.verts for e in piece.edges):
                    new, _loop = bmesh.utils.face_split(piece, x, y)
                    if new is not None:
                        new[tag] = value
                        pieces.append(new)
                    break


def build(group, output):
    """Measure, cut, build the pouch, export. Returns the metrics."""
    raw = dict(group.get('params') or {})
    teeth_options = raw.pop('teeth', None)
    P = parameters(raw)
    arms = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
    if len(arms) != 1:
        raise ValueError('Requires one armature')
    arm = arms[0]
    body = next(o for o in bpy.context.scene.objects
                if o.type == 'MESH' and o.vertex_groups and not o.get('attached_part'))
    m = measure(body, arm, P)
    S, Z, depth, s0, hw, coef = m['S'], m['Z'], m['depth'], m['s0'], m['hw'], m['coef']
    M = body.matrix_world.copy()
    Mi = M.inverted()
    pt, o = P['patch'], P['override']
    f_of = lambda p: p[2] - _line_z(coef, s0, p[0])

    _common.progress('cutting')
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active
    deform = bm.verts.layers.deform.verify()
    tag = bm.faces.layers.int.new('_mouth')
    # Created before any vertex is collected: a new layer reallocates the vertices' data.
    w_layer = bm.verts.layers.float.new('_jaw_share')
    world = lambda v: M @ v.co

    # The skin around the line: flooded from the faces the rays hit on the line, through shared positions, inside
    # the window and no further behind the visible surface than ``patch.behind`` (an inner wall is not connected).
    def in_window(p):
        if abs(p.x - s0) > hw + pt['margin'] or abs(f_of(p)) > pt['height']:
            return False
        d = _grid_at(depth, S, Z, p.x, p.z)
        return np.isfinite(d) and p.y <= d + pt['behind']

    near_faces = [fc for fc in bm.faces
                  if all(abs((M @ v.co).x - s0) < hw + pt['margin'] + .01 and abs((M @ v.co).z - coef[0]) < .05
                         for v in fc.verts)]
    centre = {fc: M @ fc.calc_center_median() for fc in near_faces}
    candidates = [fc for fc in near_faces if in_window(centre[fc])]
    by_key = {}
    for fc in candidates:
        for v in fc.verts:
            by_key.setdefault(_key(world(v)), []).append(fc)
    seeds = []
    for x in np.arange(s0 - hw * .5, s0 + hw * .5 + 1e-9, .002):
        z = float(_line_z(coef, s0, x))
        hit = m['bvh'].ray_cast(Vector((x, float(m['V'][:, 1].min()) - .05, z)), Vector((0, 1, 0)))
        if hit[0] is not None:
            near = min(candidates, key=lambda fc: (centre[fc] - hit[0]).length_squared, default=None)
            if near is not None and (centre[near] - hit[0]).length < .006:
                seeds.append(near)
    if not seeds:
        raise NoMouth('No skin faces on the lip line')
    skin, stack = set(seeds), list(seeds)
    while stack:
        fc = stack.pop()
        for v in fc.verts:
            for other in by_key[_key(world(v))]:
                if other not in skin:
                    skin.add(other)
                    stack.append(other)
    for fc in skin:
        fc[tag] = 1
    print('mouth skin faces', len(skin), 'of', len(candidates), 'candidates')

    # Subdivide: every edge of the skin longer than its target, and every other edge at the same position.
    def target(mid):
        return pt['edge_near'] if abs(f_of(mid)) < pt['near'] else pt['edge_far']

    for _round in range(6):
        wanted = set()
        for fc in bm.faces:
            if fc[tag] != 1:
                continue
            for e in fc.edges:
                a, b = world(e.verts[0]), world(e.verts[1])
                if (a - b).length > target((a + b) / 2):
                    wanted.add(frozenset((_key(a), _key(b))))
        if not wanted:
            break
        edges = [e for e in bm.edges if frozenset((_key(world(e.verts[0])), _key(world(e.verts[1])))) in wanted]
        touched = {fc for e in edges for fc in e.link_faces}
        made = set()
        for e in edges:
            _edge, vert = bmesh.utils.edge_split(e, e.verts[0], .5)
            made.add(vert)
        _split_faces(bm, touched, made, tag)
        print('  subdivided', len(edges), 'edges')

    # Move vertices lying on the line off it (seam copies alike: the move is a function of the position).
    for v in {v for fc in bm.faces if fc[tag] == 1 for v in fc.verts}:
        p = world(v)
        f = f_of(p)
        if abs(f) < SNAP_M:
            p.z += (SNAP_M if f >= 0 else -SNAP_M) - f
            v.co = Mi @ p

    # Cut: split every skin edge the line crosses between the corners, then the faces along the line.
    skin_faces = [fc for fc in bm.faces if fc[tag] == 1]
    crossing = {}
    for fc in skin_faces:
        for e in fc.edges:
            if e in crossing:
                continue
            a, b = world(e.verts[0]), world(e.verts[1])
            fa, fb = f_of(a), f_of(b)
            if (fa > 0) == (fb > 0):
                continue
            t = fa / (fa - fb)
            if abs(a.x + (b.x - a.x) * t - s0) < hw:
                crossing[e] = t
    touched = {fc for e in crossing for fc in e.link_faces}
    made = set()
    for e, t in crossing.items():
        _edge, vert = bmesh.utils.edge_split(e, e.verts[0], t)
        made.add(vert)
    line_keys = {_key(world(v)) for v in made}
    path = []
    for fc in touched:
        if not fc.is_valid:
            continue
        on = [v for v in fc.verts if v in made]
        if len(on) == 2 and fc[tag] == 1:
            new, _loop = bmesh.utils.face_split(fc, on[0], on[1])
            if new is not None:
                new[tag] = 1
                path.append(next(e for e in new.edges if on[0] in e.verts and on[1] in e.verts))
    bmesh.ops.triangulate(bm, faces=[fc for fc in bm.faces if len(fc.verts) > 3])
    if len(path) < 4:
        raise NoMouth('The lip line crosses too few skin faces')
    bmesh.ops.split_edges(bm, edges=path)
    bm.verts.ensure_lookup_table()

    # Rim: the line vertices by side (the faces they still carry lie above or below the line).
    upper, lower, both = {}, {}, {}
    for v in bm.verts:
        k = _key(world(v))
        if k not in line_keys:
            continue
        signs = {f_of(M @ fc.calc_center_median()) > 0 for fc in v.link_faces if fc[tag] == 1}
        (both if len(signs) != 1 else upper if True in signs else lower).setdefault(k, []).append(v)
    # The path's two ends are the outermost line positions; whatever the rip did there (an end on a UV seam is
    # ripped too), their copies count as one unsplit point. Every position between them was ripped.
    every = sorted(set(upper) | set(lower) | set(both), key=lambda k: k[0])
    if len(every) < 8:
        raise NoMouth('The lip line could not be opened (%d rim points)' % len(every))
    ends = [every[0], every[-1]]
    for k in ends:
        both[k] = both.get(k, []) + upper.pop(k, []) + lower.pop(k, [])
    columns = [ends[0]] + [k for k in every[1:-1] if k in upper and k in lower] + [ends[1]]
    for k in every[1:-1]:
        if k not in upper or k not in lower:
            # Not ripped (a piece of the path the split did not separate): both lips keep that point.
            both[k] = both.get(k, []) + upper.pop(k, []) + lower.pop(k, [])
    source = [(both.get(k) or upper.get(k))[0] for k in columns]
    # The rim's own coordinates (not the rounded keys): the pouch's first ring lies exactly on the skin's rim.
    rim_pos = [np.array(world(v)) for v in source]
    source_low = [(both.get(k) or lower.get(k))[0] for k in columns]

    # The pouch.
    _common.progress('building_part')
    mid = np.array([float(_line_z(coef, s0, s0))])
    centre_i = int(np.argmin([abs(p[0] - s0) for p in rim_pos]))
    O = rim_pos[centre_i].copy()
    throat = (np.array(m['head']) + np.array(m['neck'])) / 2
    axis = throat - O
    # In the mouth's own mid-plane: a head joint beside the face's midline must not turn the channel sideways.
    axis[0] = 0.
    reach = float(np.linalg.norm(axis))
    axis /= reach
    tilt = -math.radians(o['tilt_deg'])
    side = np.array([1., 0., 0.])
    axis = (axis * math.cos(tilt) + np.cross(side, axis) * math.sin(tilt)
            + side * float(side @ axis) * (1 - math.cos(tilt)))
    lateral = side - (side @ axis) * axis
    lateral /= np.linalg.norm(lateral)
    D = P['depth'] * o['depth_scale']
    R = P['radius'] * o['radius_scale']
    depths = ring_depths(D, P['rings'])
    rel = np.array(rim_pos) - O
    across = rel @ lateral
    rest = rel - across[:, None] * lateral
    widest = float(np.abs(across).max())
    n, K = len(columns), len(depths)

    def ring(k):
        d = depths[k]
        widen = 1 + (R / widest - 1) * _sstep(d / P['rings']['taper'])
        keep = 1 - _sstep(d / P['rings']['flatten'])
        return O + axis * d + lateral * (across * widen)[:, None] + rest * keep

    # The pouch's material: its own, without a texture — the colour of the darkest lip-line texel near the
    # middle, darkened by ``inside.shade``, fully rough. (One texel of the body's own texture was tried first: lips
    # are glossy on these bodies, roughness .02-.5 and no matt texel of a similar colour anywhere on the face, so
    # the inside of the open mouth shone white in the clients.) It carries the part mark ``attached_part``, so
    # the readers of the body's base colour leave it alone.
    dark_uv, dark, dark_at = None, np.inf, None
    for x in np.arange(s0 - hw * .5, s0 + hw * .5, .001):
        z = float(_line_z(coef, s0, x))
        value = _grid_at(m['lum'], S, Z, x, z)
        if np.isfinite(value) and value < dark:
            dark, dark_uv, dark_at = float(value), _grid_at(m['uv'], S, Z, x, z), (x, z)
    if dark_uv is None:
        raise NoMouth('No texel on the lip line')
    lip_rgb = np.clip(np.asarray(_grid_at(m['rgb'], S, Z, *dark_at), float), 0, 1)
    inside_rgb = np.where(lip_rgb <= .04045, lip_rgb / 12.92, ((lip_rgb + .055) / 1.055) ** 2.4) * P['inside']['shade']
    inside = bpy.data.materials.new(INSIDE_MATERIAL)
    inside.use_nodes = True
    inside['attached_part'] = group['id']
    inside.use_backface_culling = True
    shader = next(nd for nd in inside.node_tree.nodes if nd.type == 'BSDF_PRINCIPLED')
    shader.inputs['Base Color'].default_value = (*[float(c) for c in inside_rgb], 1.)
    shader.inputs['Roughness'].default_value = 1.
    shader.inputs['Metallic'].default_value = 0.
    body.data.materials.append(inside)
    inside_slot = len(body.data.materials) - 1

    def new_vert(p, like):
        v = bm.verts.new(Mi @ Vector(p))
        for g_, w_ in like[deform].items():
            v[deform][g_] = w_
        return v

    # Ring 0 carries every rim point (no T-junction against the skin); from ring 1 on the columns are thinned to
    # ``rings.column`` apart, and a fan joins the two.
    keep_cols = [0]
    for i in range(1, n - 1):
        if abs(across[i] - across[keep_cols[-1]]) >= P['rings']['column'] \
                and abs(across[n - 1] - across[i]) >= P['rings']['column'] / 2:
            keep_cols.append(i)
    keep_cols.append(n - 1)
    rings_pos = [ring(k) for k in range(K)]
    pouch = []

    def face(tri, flip):
        if len(set(tri)) < 3:
            return
        try:
            fc = bm.faces.new(tri[::-1] if flip else tri)
        except ValueError:
            return
        fc.material_index = inside_slot
        fc.smooth = True
        fc[tag] = 2
        for loop in fc.loops:
            loop[uv_layer].uv = (float(dark_uv[0]), float(dark_uv[1]))
        pouch.append(fc)

    walls = []
    role = {}                 # pouch vertex -> (wall 0 upper / 1 lower / 2 shared, ring, column)
    for like, flip in ((source, False), (source_low, True)):
        first = [new_vert(rings_pos[0][i], like[i]) if not walls or i not in (0, n - 1) else walls[0][0][i]
                 for i in range(n)]
        deeper = [[None if i not in keep_cols else
                   walls[0][k][i] if walls and (i in (0, n - 1) or k == K - 1) else new_vert(rings_pos[k][i], like[i])
                   for i in range(n)] for k in range(1, K)]
        wall = [first] + deeper
        for k, row in enumerate(wall):
            for i, v in enumerate(row):
                if v is not None:
                    role[v] = (2 if v in role else len(walls), k, i)
        walls.append(wall)
        for a, b in zip(keep_cols[:-1], keep_cols[1:]):
            middle = (a + b) // 2
            for i in range(a, middle):
                face((wall[0][i], wall[0][i + 1], wall[1][a]), flip)
            for i in range(middle, b):
                face((wall[0][i], wall[0][i + 1], wall[1][b]), flip)
            face((wall[0][middle], wall[1][b], wall[1][a]), flip)
            for k in range(1, K - 1):
                face((wall[k][a], wall[k][b], wall[k + 1][b]), flip)
                face((wall[k][a], wall[k + 1][b], wall[k + 1][a]), flip)
    grid_u = walls[0]
    # The upper wall faces down into the channel, the lower wall up: check one face of the upper wall.
    bm.normal_update()
    probe = keep_cols[len(keep_cols) // 2]
    up_face = next(fc for fc in pouch if grid_u[1][probe] in fc.verts and grid_u[2][probe] in fc.verts)
    if (M.to_3x3() @ up_face.normal).z > 0:
        for fc in pouch:
            fc.normal_flip()
    bm.normal_update()

    hips = arm.matrix_world @ resolve_bone(arm.pose.bones, 'Hips').head
    hinge, jaw_scale = jaw_hinge(O, hips, m['head'], P['jaw'])
    theta = math.radians(P['jaw']['open_deg'])
    cl = P['clear']
    normal = np.cross(lateral, axis)
    if normal[2] < 0:
        normal = -normal
    order = np.argsort(across)
    rest_up = (rest @ normal)[order]

    def in_pouch(p):
        """``(depth, height, within, widening)`` of a world point over the pouch's middle surface (continued past
        its width) when it lies within the pouch's depth range, else None. Height: + above (the upper wall's
        side), - below; ``within`` = inside the pouch's width less ``clear.margin``."""
        rel_p = np.asarray(p, float) - O
        d = float(rel_p @ axis)
        if not 0. <= d <= D:
            return None
        widen = 1 + (R / widest - 1) * float(_sstep(d / P['rings']['taper']))
        a_ = float(rel_p @ lateral)
        bow = float(np.interp(a_ / widen, across[order], rest_up)) * (1 - float(_sstep(d / P['rings']['flatten'])))
        return d, float(rel_p @ normal) - bow, abs(a_) <= widest * widen - cl['margin'], widen

    # The jaw share (module docstring 5).
    _common.progress('skinning')
    sh, lf = P['share'], P['lift']
    upper_rim = {v for k in columns for v in upper.get(k, [])}
    lower_rim = {v for k in columns for v in lower.get(k, [])}
    domain = []
    for v in bm.verts:
        if v in role:
            continue
        p = world(v)
        if abs(p.x - s0) < sh['reach'] and -sh['below'] < p.z - float(_line_z(coef, s0, p.x)) < .03 \
                and p.y < O[1] + sh['behind']:
            domain.append(v)
    index_of = {v: i for i, v in enumerate(domain)}
    Pd = np.array([tuple(world(v)) for v in domain])
    side_of = np.array([1 if v in upper_rim else 2 if v in lower_rim else 0 for v in domain])
    keys = np.concatenate([np.round(Pd / 1e-5).astype(np.int64), side_of[:, None]], 1)
    _uniq, node = np.unique(keys, axis=0, return_inverse=True)
    node = node.ravel()
    count = int(node.max()) + 1
    pos = np.zeros((count, 3))
    pos[node] = Pd
    pairs, border = [], np.zeros(count, bool)
    for v in domain:
        for e in v.link_edges:
            other = e.other_vert(v)
            if other in index_of:
                if index_of[other] > index_of[v]:
                    pairs.append((node[index_of[v]], node[index_of[other]]))
            elif other not in role:
                border[node[index_of[v]]] = True
    pairs = np.array(pairs, int).reshape(-1, 2)
    pairs = pairs[pairs[:, 0] != pairs[:, 1]]
    pairs = np.unique(np.sort(pairs, 1), axis=0)
    f_node = pos[:, 2] - _line_z(coef, s0, pos[:, 0])
    upper_node = np.zeros(count, bool)
    lower_node = np.zeros(count, bool)
    upper_node[node[side_of == 1]] = True
    lower_node[node[side_of == 2]] = True
    surface = np.array([_grid_at(depth, S, Z, q[0], q[2]) for q in pos])
    # The chin's front: below the lower lip, around the midline, on the visible surface and no further behind the
    # opening than ``share.chin_back`` (the throat under the chin lies further back).
    chin = (f_node < -sh['chin']) & (f_node > -sh['chin_reach']) & (np.abs(pos[:, 0] - s0) < sh['chin_width'] * hw) \
        & np.isfinite(surface) & (pos[:, 1] <= np.nan_to_num(surface, nan=-np.inf) + .004) \
        & (pos[:, 1] <= O[1] + sh['chin_back'])
    # Toward a corner both lips come together at half the turn: within ``share.corner`` of the path's end the
    # lower rim falls from 1 to 1/2 and the upper rim rises from 0 to 1/2, so the opening closes like a lens
    # instead of standing open as a slot with torn ends.
    ends_x = (rim_pos[0][0], rim_pos[-1][0])
    rim_x = np.array([p_[0] for p_ in rim_pos])

    def rim_share(x, lower_side):
        return mouth_math.rim_share(x, ends_x, sh['corner'], lower_side)

    end_node = np.zeros(count, bool)
    for k in ends:
        for v in both.get(k, []):
            if v in index_of:
                end_node[node[index_of[v]]] = True
    fixed = lower_node | upper_node | end_node | chin | border | (f_node > sh['above'])
    X = np.zeros((count, 1))
    X[chin, 0] = 1.
    X[lower_node, 0] = rim_share(pos[lower_node, 0], True)
    X[upper_node, 0] = rim_share(pos[upper_node, 0], False)
    X[end_node, 0] = .5
    lengths = np.linalg.norm(pos[pairs[:, 0]] - pos[pairs[:, 1]], axis=1)
    share = np.clip(harmonic_fill(count, pairs, lengths, ~fixed, X)[:, 0], 0., 1.)
    # Reached from the lower rim through the mesh = solved; the rest takes its nearest solved node's share.
    reached = np.zeros(count, bool)
    reached[lower_node | upper_node] = True
    neighbours = [[] for _ in range(count)]
    for a_, b_ in pairs:
        neighbours[a_].append(b_)
        neighbours[b_].append(a_)
    stack = list(np.nonzero(reached)[0])
    while stack:
        a_ = stack.pop()
        for b_ in neighbours[a_]:
            if not reached[b_]:
                reached[b_] = True
                stack.append(b_)
    # Inner geometry = what the cut does not reach through the mesh. A lump JOINED to the skin somewhere is not
    # told apart: two rules for it were tried and dropped — its detour along the mesh took a second skin layer on
    # a chin for a lump, and "hidden from the front" took the fold under a full lower lip for one, which left a
    # gap under the lip. Such a lump keeps its solved share and may cross the open channel (measured: 27 faces
    # on one of three bodies).
    # Everything else takes the share of the nearest skin node first.
    solved = np.nonzero(reached)[0]
    tree = KDTree(len(solved))
    for i_, n_ in enumerate(solved):
        tree.insert(Vector(pos[n_]), i_)
    tree.balance()
    inner = ~reached
    for n_ in np.nonzero(~reached)[0]:
        share[n_] = share[solved[tree.find(Vector(pos[n_]))[1]]]
    for n_ in np.nonzero(~reached)[0]:
        # Over the pouch it stays with the head, under it it goes down at least as far as the lower wall there:
        # nothing passes through a wall.
        where = in_pouch(pos[n_])
        if where is None:
            continue
        inner[n_] = True
        x_rim = float(np.interp((pos[n_] - O) @ lateral / where[3], across[order], rim_x[order]))
        follow = float(lower_follow(where[0], D))
        if where[1] >= 0:
            share[n_] = follow * float(rim_share(x_rim, False))
        elif where[2]:
            share[n_] = max(share[n_], follow * float(rim_share(x_rim, True)))
    for v in domain:
        v[w_layer] = float(share[node[index_of[v]]])
    torn = [fc for fc in bm.faces if fc[tag] == 0 and all(v in index_of for v in fc.verts)
            and all(inner[node[index_of[v]]] for v in fc.verts)
            and max(v[w_layer] for v in fc.verts) - min(v[w_layer] for v in fc.verts) > sh['tear']]
    if torn:
        # Faces only: the vertices stay (unused ones are not exported), so nothing collected above goes stale.
        bmesh.ops.delete(bm, geom=torn, context='FACES_ONLY')
    print('jaw share nodes', count, 'solved', int(reached.sum()), 'torn faces removed', len(torn))
    # Clear the channel's core (module docstring 4): never skin the cut reaches through the mesh.
    inside = set()
    for v in bm.verts:
        if v in role or (v in index_of and not inner[node[index_of[v]]]):
            continue
        p = np.array(world(v))
        if np.abs(p - O).max() > D + widest + .01:
            continue
        where = in_pouch(p)
        if where is None or not where[2] or where[0] < cl['start'] or where[0] > D - cl['margin']:
            continue
        # Under the pouch an inner vertex goes down with the lower wall (its share above), so only what stands
        # over the upper wall within the dome's rise ends up inside the open channel.
        if -cl['below'] <= where[1] <= cl['above'] + P['dome']['height']:
            inside.add(v)
    doomed = [fc for fc in bm.faces if fc[tag] == 0 and any(v in inside for v in fc.verts)
              and not any(v in index_of and not inner[node[index_of[v]]] for v in fc.verts)]
    cleared = len(doomed)
    if doomed:
        # Faces only: the vertices stay (unused ones are not exported), so nothing collected above goes stale.
        bmesh.ops.delete(bm, geom=doomed, context='FACES_ONLY')
    print('cleared faces inside the channel', cleared)
    # The pouch: lower wall by depth, upper wall none, shared sides between (the corners' solved share at the rim).
    # Across its width the open channel is a lens, not a box: past the rim the lower wall's share falls off toward
    # the sides, and the upper wall rises into a dome with the mouth open (``dome``, part of the shape key).
    rim_low, rim_up = rim_share(rim_x, True), rim_share(rim_x, False)
    lens = np.sqrt(np.clip(1 - (across / widest) ** 2, 0, 1))
    dome = {}
    for v, (wall, k, i) in role.items():
        follow = float(lower_follow(depths[k], D))
        shaped = 1 - (1 - lens[i]) * float(_sstep(depths[k] / P['dome']['blend']))
        if k == K - 1:
            v[w_layer] = 0.
        elif i in (0, n - 1):
            v[w_layer] = .5 * follow
        elif wall == 1:
            v[w_layer] = follow * (rim_up[i] + (rim_low[i] - rim_up[i]) * shaped)
        else:
            v[w_layer] = follow * rim_up[i]
        if wall == 0 and i not in (0, n - 1) and 0 < k < K - 1:
            dome[v] = P['dome']['height'] * lens[i] * math.sin(math.pi * depths[k] / D) ** .5
    # What would STAND IN THE OPEN CHANNEL (a lump joined to the skin somewhere is not inner geometry by the
    # rule above and keeps its solved share): a vertex behind the lip line (``clear.behind``) and within the
    # pouch's width that, with the mouth fully open, ends up between the two walls — its own height less its own
    # drop lies above the lower wall's drop and below the upper wall with its dome, each by ``clear.inside``.
    # Chin skin is below the lower wall then (it drops at least as far), so it is never taken.
    def wall_shares(a_, d_, widen_):
        x_rim = float(np.interp(a_ / widen_, across[order], rim_x[order]))
        follow_ = float(lower_follow(d_, D))
        lens_ = math.sqrt(max(0., 1 - (a_ / (widest * widen_)) ** 2))
        shaped_ = 1 - (1 - lens_) * float(_sstep(d_ / P['dome']['blend']))
        up_ = float(rim_share(x_rim, False))
        low_ = float(rim_share(x_rim, True))
        return follow_ * (up_ + (low_ - up_) * shaped_), follow_ * up_, lens_

    standing = set()
    for v in bm.verts:
        if v in role:
            continue
        p = np.array(world(v))
        if np.abs(p - O).max() > D + widest + .01:
            continue
        where = in_pouch(p)
        if where is None or not where[2] or where[0] < cl['behind'] or where[0] > D - cl['margin']:
            continue
        drop = float(np.linalg.norm(turned(p[None], hinge, theta)[0] - p))
        low_, up_, lens_ = wall_shares(float((p - O) @ lateral), where[0], where[3])
        top = -up_ * drop + P['dome']['height'] * lens_ * math.sin(math.pi * where[0] / D) ** .5
        after = where[1] - float(v[w_layer]) * drop
        if -low_ * drop + cl['inside'] < after < top - cl['inside']:
            standing.add(v)
    crossing = [fc for fc in bm.faces if fc[tag] == 0 and any(v in standing for v in fc.verts)]
    if crossing:
        bmesh.ops.delete(bm, geom=crossing, context='FACES_ONLY')
    print('faces standing in the open channel removed', len(crossing))
    bm.verts.ensure_lookup_table()
    bm.verts.index_update()
    rest_co = np.array([tuple(world(v)) for v in bm.verts])
    lower_wall_idx = [v.index for v, (wall, _k, _i) in role.items() if wall == 1]
    jaw_share = np.array([v[w_layer] for v in bm.verts])
    # The upper lip's lift: the skin above the line and the pouch's upper wall (a rim copy counts by its side).
    f_all = rest_co[:, 2] - _line_z(coef, s0, rest_co[:, 0])
    is_upper = f_all > 0
    along = np.zeros(len(rest_co))
    for v in bm.verts:
        if v in upper_rim:
            is_upper[v.index] = True
        elif v in lower_rim:
            is_upper[v.index] = False
        elif v in role:
            wall, k, i = role[v]
            is_upper[v.index] = wall == 0 and i not in (0, n - 1)
            along[v.index] = depths[k]
            f_all[v.index] = 0.
    lift = np.where(is_upper, lf['height'] * np.exp(-(np.clip(f_all, 0, None) / lf['band']) ** 2)
                    * np.cos(np.clip(np.abs(rest_co[:, 0] - s0) / hw, 0, 1) * math.pi / 2) ** 2
                    * (1 - _sstep(along / lf['depth'])), 0.)
    lift[np.linalg.norm(rest_co - O, axis=1) > .08] = 0.
    rise = np.zeros((len(rest_co), 3))
    for v, height in dome.items():
        rise[v.index] = normal * height
    # THE LIP'S EDGE. Cut, a lip ends in a sharp corner between the skin and the channel's wall — open, it looked
    # like a cut flap. With the mouth open the corner is rounded by a fillet of ``lip.radius``: a point at distance
    # t < r from the rim (down the skin, or back along the wall) goes onto the quarter circle that touches the
    # skin and the wall r from the corner — alpha = 45 deg x (1 - t/r) from the skin's side, 90 deg - that from
    # the wall's; the corner itself lands on the arc's middle, (1 - 1/sqrt 2) r back and into the lip. Scaled by
    # how far the rim opens there (nothing at the mouth corners), part of the shape key, so the closed lips meet.
    radius = P['lip']['radius']
    roll = np.zeros((len(rest_co), 3))
    lip_verts = {v for fc in bm.faces if fc[tag] == 1 for v in fc.verts}
    for v in bm.verts:
        on_wall = v in role
        if not on_wall and v not in lip_verts:
            continue
        if on_wall:
            wall, k, i = role[v]
            if wall == 2 or i in (0, n - 1):
                continue
            t, x = depths[k], rim_x[i]
            upper_side = wall == 0
        else:
            t, x = abs(float(f_all[v.index])), float(rest_co[v.index][0])
            upper_side = bool(is_upper[v.index])
        if t >= radius or abs(x - s0) >= hw:
            continue
        back, into = lip_fillet(t, radius, on_wall)
        opens = float(rim_share(x, True) - rim_share(x, False))
        roll[v.index] = (axis * back + (normal if upper_side else -normal) * into) * opens
    bm.verts.layers.float.remove(w_layer)

    # Check: along the rim every open edge of the skin has the pouch's open edge at its place (no seam there).
    rim_set = set(columns)
    open_edges = {}
    for e in bm.edges:
        if e.is_boundary:
            k = frozenset((_key(world(e.verts[0])), _key(world(e.verts[1]))))
            if all(c in rim_set for c in k):
                kinds = open_edges.setdefault(k, [0, 0])
                kinds[0 if e.link_faces[0][tag] == 2 else 1] += 1
    # Per rim segment: one skin edge above, one below, and the pouch's two walls.
    unmatched = sum(1 for kinds in open_edges.values() if kinds != [2, 2])
    pouch_tris = len(pouch)
    skin_tris = sum(1 for fc in bm.faces if fc[tag] == 1)
    bm.faces.layers.int.remove(tag)
    bm.to_mesh(body.data)
    bm.free()
    body.data.update()

    # The jaw (part 3): with a declared bone the turn is the BONE's — the share becomes its weight, taken from the
    # vertex's other weights in proportion — and the shape key keeps what a bone cannot do (the upper lip's lift,
    # the dome). Without one the shape key carries the turn as well.
    chains = group.get('chains') or []
    jaw_name = chains[0][0]['bone'] if chains and chains[0] else None
    if jaw_name:
        parent = resolve_bone(arm.data.bones, chains[0][0]['parent']).name
        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.mode_set(mode='EDIT')
        to_arm = arm.matrix_world.inverted()
        bone = arm.data.edit_bones.new(jaw_name)
        bone.head = to_arm @ Vector(hinge)
        # Toward the chin: from the hinge to a point under the opening.
        bone.tail = to_arm @ Vector(hinge + (O + np.array([0., 0., -.03]) - hinge) * .6)
        bone.parent = arm.data.edit_bones[parent]
        bone.use_connect = False
        bone.use_deform = True
        jaw_name = bone.name
        bpy.ops.object.mode_set(mode='OBJECT')
        arm.data.bones[jaw_name]['mouth_open_deg'] = float(P['jaw']['open_deg'])
        jaw_group = body.vertex_groups.get(jaw_name) or body.vertex_groups.new(name=jaw_name)
        for i_ in np.nonzero(jaw_share > 1e-4)[0]:
            vertex = body.data.vertices[int(i_)]
            share_ = float(min(jaw_share[i_], 1.))
            total = sum(g_.weight for g_ in vertex.groups) or 1.
            for g_ in vertex.groups:
                g_.weight = g_.weight * (1. - share_)
            jaw_group.add([int(i_)], share_ * total, 'REPLACE')
        opened = rest_co.copy()
        moved = (lift > 1e-7) | (np.abs(rise).sum(1) > 1e-7) | (np.abs(roll).sum(1) > 1e-7)
    else:
        opened = turned(rest_co, hinge, jaw_share * theta)
        moved = (jaw_share > 1e-5) | (lift > 1e-7) | (np.abs(rise).sum(1) > 1e-7) \
            | (np.abs(roll).sum(1) > 1e-7)
    opened[:, 2] += lift
    opened += rise + roll
    if body.data.shape_keys is None:
        body.shape_key_add(name='Basis', from_mix=False)
    key = body.data.shape_keys.key_blocks.get(SHAPE_KEY) or body.shape_key_add(name=SHAPE_KEY, from_mix=False)
    key.slider_min, key.slider_max, key.value = 0., 1., 0.
    local = np.array([tuple(Mi @ Vector(p)) for p in opened])
    for i_ in np.nonzero(moved)[0]:
        key.data[int(i_)].co = Vector(local[i_])

    # THE TEETH (step 7, Ruling A206): a failure here publishes the mouth without them.
    teeth = {'status': 'off', 'reason': 'switched off'}
    if (teeth_options or {}).get('enabled', True) is not False:
        _common.progress('teeth')
        try:
            if not jaw_name:
                raise ValueError('No jaw bone to carry the lower teeth')
            teeth = mouth_teeth.build_teeth(_teeth_context(body, arm, group, P, inside_slot, lower_wall_idx, jaw_name, {
                'O': O, 'axis': axis, 'lateral': lateral, 'up': normal, 'widest': widest, 'R': R, 'D': D,
                'taper': P['rings']['taper'], 'flatten': P['rings']['flatten'], 'across_sorted': across[order],
                'rest_up': rest_up, 'hinge': hinge, 'theta': theta}), teeth_options)
        except Exception as exc:  # noqa: BLE001 — the mouth is published without teeth, never discarded
            import traceback
            traceback.print_exc()
            teeth = {'status': 'failed', 'reason': str(exc) or type(exc).__name__}
    print('teeth', teeth.get('status'), teeth.get('reason', ''))

    _common.progress('exporting')
    bpy.ops.export_scene.gltf(filepath=str(output), export_format='GLB', export_apply=False,
                              export_yup=True, export_skins=True, export_animations=True,
                              export_morph=True, export_extras=True, export_all_influences=False)
    _common.body_meshes_first(output)
    _common.keep_mouth_teeth_colours(output)
    front_shift = np.array([0., -o['offset_mm'][2] / 1000, 0.])
    return {'status': 'applied', 'reason': '',
            'opening': {'centre': [round(c, 5) for c in _gltf(O + front_shift)],
                        'axis': [round(c, 6) for c in _gltf(axis)], 'depth': round(D, 4),
                        'radius': round(R, 4), 'half_width': round(widest, 4),
                        'open_height': round(float(np.linalg.norm(turned(O[None], hinge, theta)[0] - O)), 4),
                        **({'teeth_gap': teeth['teeth_gap']} if teeth.get('status') == 'applied' else {}),
                        'teeth_status': teeth.get('status'), 'teeth_reason': teeth.get('reason', ''),
                        'teeth_left_out': sum(a.get('left_out', 0) for a in (teeth.get('arches') or {}).values()),
                        'override': {'offset_mm': list(o['offset_mm']), 'radius_scale': o['radius_scale'],
                                     'depth_scale': o['depth_scale'], 'tilt_deg': o['tilt_deg']}},
            'lip_line': {'s0': round(s0, 4), 'coef': [round(c, 5) for c in coef], 'contrast': round(m['contrast'], 3),
                         'tracked_half_width': round(m['tracked_half_width'], 4), 'half_width': round(hw, 4),
                         'nose': [round(c, 4) for c in m['nose']], 'chin_z': round(m['chin_z'], 4)},
            'throat_reach': round(reach, 4), 'rim_points': n, 'rings': K,
            'jaw': {'hinge': [round(c, 5) for c in _gltf(hinge)], 'open_deg': P['jaw']['open_deg'],
                    'scale': round(jaw_scale, 3)},
            'shape_key': SHAPE_KEY, 'moved_vertices': int(moved.sum()),
            'jaw_bone': jaw_name, 'jaw_vertices': int((jaw_share > 1e-4).sum()) if jaw_name else 0, 'torn_faces_removed': len(torn),
            'cleared_faces': cleared, 'standing_faces_removed': len(crossing), 'pouch_uv': [float(dark_uv[0]), float(dark_uv[1])],
            'inside': {'lip_line_rgb': [round(float(c), 3) for c in lip_rgb],
                       'base_color_linear': [round(float(c), 4) for c in inside_rgb]},
            'pouch_tris': pouch_tris, 'skin_tris': skin_tris, 'rim_segments': len(open_edges),
            'unmatched_open_edges': unmatched, 'teeth': teeth}


def _teeth_context(body, arm, group, P, inside_slot, lower_wall_idx, jaw_name, frame):
    """What ``mouth_teeth.build_teeth`` reads besides the channel's frame: the body, its bones, the outer skin
    (without the pouch) and the lower wall's vertices with their weights."""
    me = body.data
    M = body.matrix_world
    me.calc_loop_triangles()
    V = np.array([tuple(M @ v.co) for v in me.vertices])
    tris = np.array([tuple(t.vertices) for t in me.loop_triangles])
    skip = {i for i, t in enumerate(me.loop_triangles) if t.material_index == inside_slot}
    names = [g.name for g in body.vertex_groups]
    wall = [(V[i], {names[g.group]: g.weight for g in me.vertices[i].groups if g.weight > 0})
            for i in lower_wall_idx]
    return {**frame, 'body': body, 'arm': arm, 'group_id': group['id'],
            'head_bone': resolve_bone(arm.data.bones, P['head_bone']).name,
            'jaw_bone': jaw_name, 'lower_wall': wall,
            'outer_skin': mouth_teeth.OuterSkin(V, tris, skip, frame['O'])}


def mouth_part(args):
    """Runner entry; failures leave the caller's staged body untouched."""
    groups = [g for g in args['params'].get('groups', []) if g.get('enabled', True) and g['op'] == 'mouth_part']
    if len(groups) != 1:
        raise ValueError('Exactly one mouth channel group is required')
    _common.reset_scene()
    _common.import_model(args['inputs']['model'])
    output = Path(args['out_dir']) / 'model.glb'
    _common.progress('measuring')
    try:
        metrics = build(groups[0], output)
    except NoMouth as finding:
        # No output: the caller keeps the body as it is and records why (``not_found``, not ``failed``).
        per_group = {groups[0]['id']: {'status': 'not_found', 'reason': str(finding)}}
        return {'status': 'not_found', 'reason': str(finding), 'metrics': per_group, 'groups': per_group}, {}
    per_group = {groups[0]['id']: metrics}
    return {'status': 'applied', 'reason': '', 'metrics': per_group, 'groups': per_group}, {'model': str(output)}


if __name__ == '__main__':
    _common.main(mouth_part)
