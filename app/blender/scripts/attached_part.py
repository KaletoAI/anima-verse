"""Build a swept, skinned attached part using root-local smooth SDF unions.

World coordinates are metres, front is -Y and up is +Z. The body is finalized
before sampling the field. The open shell blends into its texture and weights.
"""
import copy
import heapq
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
    'base_fraction': .15, 'girth_max': 1.0, 'tip_start': 1 - .32 * .85,
    'tip_rim': .012, 'tip_girth': 1.05, 'first_link_start': .1,
    'relief': {'amplitude': .00035, 'terms': [[.6, 3.1, 2, 0], [.4, 7.3, -3, 1.3]],
               'start': .1, 'rise': .06, 'end_offset': .02, 'fall': .05},
    'ridges': [
        {'t0': .12, 'tip_offset': .04, 'phase': .45, 'wobble': .25, 'freq': 1.4, 'offset': .5, 'r0': .0015, 'r1': .0008},
        {'t0': .2, 'tip_offset': .08, 'phase': -.6, 'wobble': .2, 'freq': 1.1, 'offset': 2.1, 'r0': .0012, 'r1': .0007},
        # The underside ridge (phase pi) faces the pouch. From .1 it ran into the
        # junction with the pouch, which a lifted chain turns to the front: the
        # union's crest there turned the normal by up to .85 rad across 8 mm of
        # the midline and shaded as a dark vertical band (Ruling A88). From .5 on
        # it stays on the free part of the sweep.
        {'t0': .5, 'tip_offset': .02, 'phase': math.pi, 'wobble': .03, 'freq': 1., 'offset': 0., 'r0': .0007, 'r1': .0005}],
    'ridge_blend': .0018, 'pod_scale': 1.2,
    # The pods hang from the root: the union's top (the last ellipsoid, .008 up
    # and .016 tall, both x pod scale) sits at the root's height, the pod centre
    # .024 x pod scale below it and 10 mm behind, so the part leaves the body at
    # the pods' upper front (Ruling A65; .046 / .018 along the skin normal left
    # a gap of skin between them).
    'pods': {'down': .024, 'back': .010, 'blend': .008, 'ellipsoids': [
        {'lateral': .012, 'down': .006, 'back': 0., 'radii': [.014, .011, .024]},
        {'lateral': -.012, 'down': .002, 'back': 0., 'radii': [.014, .011, .024]},
        {'lateral': 0., 'down': .012, 'back': 0., 'radii': [.016, .0095, .013]},
        {'lateral': 0., 'down': -.008, 'back': .006, 'radii': [.016, .012, .016]}],
        # Rugae: wavy transverse folds pressed INTO the skin (a loose, slightly
        # sunken sack, not a taut one), a crossing set for irregularity and the
        # midline seam. Lengths scale with the pods; free of folds near the root.
        'folds': {'depth': .0007, 'wavelength': .0075, 'width': .3, 'wobble': .003, 'wobble_wavelength': .021,
                  # The raphe's flanks rise at most .86 raphe/raphe_width (4.9 degrees):
                  # at 1.8 mm (13 degrees) it shaded as a thin dark line (Ruling A65d).
                  'raphe': .0005, 'raphe_width': .005, 'root_clear': .016, 'root_fall': .012, 'shade': .3}},
    # The shaft-pods union widens near the root into a web of skin; along the
    # free shaft it stays tight so a lifted shaft does not drag the sack along.
    # Until .4 the web ended where the hanging sweep lies on the pouch's front:
    # the tight fillet there became a narrow crest on the midline once the
    # chain lifted (Ruling A88); until .55 the junction stays a broad roll.
    'pod_web': {'blend': .016, 'until': .55},
    'pod_link': .7, 'pod_link_distance': .03, 'k_tip_pods': .004, 'k_body': .016,
    # Beyond radius + fall the body field recedes `recede` metres per metre into
    # the body: there the part only touches skin and keeps its own closed
    # surface, which a pose can pull off the skin without opening it (Ruling A65c).
    'body_window': {'radius': .03, 'fall': .02, 'recede': 2.},
    # The fillet settles on the skin sunk this deep: at 3 mm it rose steeply
    # out of the skin and drew a rim around the root (Ruling A65b).
    'skin_sink': .0008,
    'hidden_band': {'lateral': .025, 'above': -.02, 'radius': .045, 'depth': .006},
    # wall_reach: how far around the window the flattening blends out, and how
    # deep under its skin an inner wall moves with it; blend: smoothing passes
    # over the displacement there (Ruling A65e).
    'flatten': {'lateral': .055, 'down': .035, 'below': .065, 'above': .01,
                'front': .03, 'normal_front': .2, 'iterations': 150, 'wall_reach': .03, 'blend': 10},
    'reweight': {'from': .045, 'to': .095},
    'tone': {'shaft': [.9, .83, .8], 'tip': [1.04, .84, .82]}, 'border_lift': .010,
    # The attachment seam: the fillet lands `tuck` under the skin, its height
    # falls off over `band` and its normals turn to the body's over
    # `normal_band`, so the part grows out of the body instead of sitting on it.
    # An open border standing on the skin showed as a dark serrated line.
    'seam': {'tuck': .0004, 'band': .006, 'normal_band': .012},
    'texture': {'bake': 1024, 'patch_max': 256, 'flood': .07, 'blur': 9, 'tone_tolerance': .15},
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
        elif name in ('params.flatten.iterations', 'params.flatten.blend', 'params.smooth.iterations', 'params.texture.bake', 'params.texture.patch_max', 'params.texture.blur') and (not isinstance(value, int) or value < 0):
            raise ValueError('Expected nonnegative integer: ' + name)
        return value
    settings = merge(DEFAULTS, raw, 'params')
    for key in ('size_factor', 'length', 'radius', 'voxel', 'tip_rim', 'tip_girth', 'inner_extension',
                'border_lift', 'k_body', 'k_tip_pods', 'pod_scale', 'pod_link_distance'):
        if settings[key] <= 0:
            raise ValueError(key + ' must be positive')
    if not 0 < settings['decimate'] <= 1 or not 0 <= settings['pod_link'] <= 1:
        raise ValueError('Invalid decimate or pod_link')
    if not 0 < settings['base_fraction'] < settings['tip_start'] < 1 - 2 * settings['tip_rim']:
        raise ValueError('Invalid base / tip profile')
    if not 0 <= settings['first_link_start'] < settings['tip_start']:
        raise ValueError('Invalid first_link_start')
    if settings['reweight']['from'] < 0 or settings['reweight']['to'] <= settings['reweight']['from']:
        raise ValueError('Invalid radial reweight interval')
    for section, keys in (('body_window', ['radius', 'fall', 'recede']), ('relief', ['rise', 'fall']),
                           ('texture', ['bake', 'patch_max', 'flood', 'blur', 'tone_tolerance']),
                           ('pods.folds', ['wavelength', 'width', 'wobble_wavelength', 'raphe_width', 'root_fall']),
                           ('pod_web', ['until']), ('seam', ['band', 'normal_band'])):
        values = settings
        for part_ in section.split('.'):
            values = values[part_]
        if any(values[key] <= 0 for key in keys):
            raise ValueError('Invalid ' + section)
    folds = settings['pods']['folds']
    if any(folds[key] < 0 for key in ('depth', 'wobble', 'raphe', 'root_clear', 'shade')) or folds['shade'] > 1 or settings['pod_web']['blend'] < 0:
        raise ValueError('Invalid pod folds or web')
    if settings['texture']['blur'] % 2 != 1:
        raise ValueError('Texture blur must be odd')
    for e in settings['pods']['ellipsoids']:
        if min(e['radii']) <= 0:
            raise ValueError('Pod radii must be positive')
    for ridge in settings['ridges']:
        if not 0 <= ridge['t0'] < settings['tip_start'] - ridge['tip_offset'] or min(ridge['r0'], ridge['r1']) <= 0:
            raise ValueError('Invalid ridge interval or radius')
    for section, keys in (('flatten', ['lateral', 'down', 'below', 'above', 'front', 'wall_reach']),
                           ('hidden_band', ['lateral', 'radius', 'depth'])):
        if any(settings[section][key] < 0 for key in keys):
            raise ValueError('Invalid ' + section + ' length')
    if settings['seam']['tuck'] < 0:
        raise ValueError('Invalid seam tuck')
    if settings['anchor_drop'] < 0 or settings['root_sink'] < 0 or settings['skin_sink'] < 0 or settings['girth_max'] < 1 or settings['tip_girth'] < 1:
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


class OuterSkin:
    """BVH over the body's OUTER skin, answering with body polygon indices.

    Some meshers (UniForge) deliver a double-walled body: the outer skin plus an
    inner wall a few mm below it whose normals face the hollow interior. The
    skin field takes its sign from the nearest face's normal, so the inner wall
    turned the body's inside into "outside" and the surface net sprouted
    fragments inside the body. An inner-wall face is ``_common.enclosed``. A
    deep crease of outer skin can pass as enclosed too; losing it from the field
    only coarsens the distance there, while a missed inner-wall face breaks the
    field's sign.
    """

    def __init__(self, body, centre, radius):
        me = body.data
        verts = [v.co.copy() for v in me.vertices]
        full = BVHTree.FromPolygons(verts, [p.vertices[:] for p in me.polygons])
        centre_local = body.matrix_world.inverted() @ centre
        radius_local = radius / max(body.matrix_world.to_scale())
        self.body = body
        self.index = []
        self.inner_wall_faces = 0
        for poly in me.polygons:
            if (poly.center - centre_local).length < radius_local and self._enclosed(full, poly):
                self.inner_wall_faces += 1
                continue
            self.index.append(poly.index)
        self.refit()

    def refit(self):
        """Rebuild the tree on the body's current vertex positions, keeping
        the classification. Which face is skin and which is inner wall is
        decided once, before the window is flattened: a flattened skin that
        passes a wall it was meant to push along (13 faces under the root on a
        UniForge body) reads as enclosed afterwards, and the wall in front of
        it as skin. That wall faces the hollow, upward under the body: every
        point of a sweep hanging below it lay "behind" it, the skin field
        took the sweep's middle for the inside of the body and cut a gash
        across it (Ruling A98)."""
        me = self.body.data
        self.tree = BVHTree.FromPolygons([v.co.copy() for v in me.vertices],
                                         [me.polygons[i].vertices[:] for i in self.index])

    @staticmethod
    def _enclosed(tree, poly):
        return _common.enclosed(tree, poly.center, poly.normal)

    def _mapped(self, hit):
        location, normal, index, distance = hit
        return location, normal, None if index is None else self.index[index], distance

    def find_nearest(self, co):
        return self._mapped(self.tree.find_nearest(co))

    def inside_beside(self, co, hit):
        """For a point beside its nearest skin face rather than over it: whether
        it lies inside the skin; None for a point over the face.

        Over a face (the offset to the nearest point within 60 degrees of the
        face normal) the offset along the normal is the point's height. Beside
        it the nearest point lies on the rim that a left-out inner wall or crease
        leaves in the outer skin, often centimetres away, and the offset along
        that face's normal says nothing: a border vertex deep in the body read as
        standing on the skin, and landing it along that normal walked it 9 mm
        through the body (Ruling A65e). There six axis rays vote by their
        crossings of the outer skin. ``co`` and ``hit`` are in the body's local
        space, ``hit`` from ``find_nearest``."""
        location, normal, _, distance = hit
        if location is None or distance < 1e-9 or abs((co - location).dot(normal)) >= .5 * distance:
            return None
        votes = 0
        for axis in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            direction, origin, crossings = Vector(axis), co.copy(), 0
            while True:
                found = self.tree.ray_cast(origin, direction)[0]
                if found is None:
                    break
                crossings += 1
                origin = found + direction * 1e-6
            votes += crossings % 2
        return votes > 3

    def ray_cast(self, origin, direction):
        return self._mapped(self.tree.ray_cast(origin, direction))


def border_strip(points, edge_counts, border, band):
    """Smoothstep share falling from 1 on an open border to 0 at ``band`` metres
    from it, the distance measured along the mesh edges (``edge_counts`` maps
    each edge, a vertex index pair, to its face count)."""
    along = np.full(len(points), np.inf)
    neighbours = [[] for _ in range(len(points))]
    for a, b in edge_counts:
        length = float(np.linalg.norm(np.asarray(points[a]) - np.asarray(points[b])))
        neighbours[a].append((b, length))
        neighbours[b].append((a, length))
    heap = [(0., i) for i in border]
    for _, i in heap:
        along[i] = 0.
    heapq.heapify(heap)
    while heap:
        d, i = heapq.heappop(heap)
        if d > along[i] or d > band:
            continue
        for j, length in neighbours[i]:
            if d + length < along[j]:
                along[j] = d + length
                heapq.heappush(heap, (d + length, j))
    share = np.clip(1 - along / band, 0, 1)
    return share * share * (3 - 2 * share)


def skin_texel_fallback(pixels):
    return np.median(pixels[..., :3].reshape(-1, 3), axis=0)


def close_free_holes(obj, skin, root_local, band, matrix):
    """Fills each open border loop of ``obj`` except the one passing closest to
    ``root_local`` whose median distance to ``skin`` (an object-space BVH-like
    ``find_nearest``), measured in world metres through ``matrix``, exceeds
    ``band``. Returns the number of loops closed."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    seen, loops = set(), []
    for edge in bm.edges:
        if not edge.is_boundary or edge in seen:
            continue
        loop, stack = [], [edge]
        seen.add(edge)
        while stack:
            e = stack.pop()
            loop.append(e)
            for v in e.verts:
                for f in v.link_edges:
                    if f.is_boundary and f not in seen:
                        seen.add(f)
                        stack.append(f)
        loops.append(loop)
    closed = 0
    if len(loops) > 1:
        def verts_of(loop):
            return {v for e in loop for v in e.verts}
        attach = min(range(len(loops)), key=lambda k: min((v.co - root_local).length for v in verts_of(loops[k])))
        for k, loop in enumerate(loops):
            if k == attach:
                continue
            gaps = sorted((matrix @ v.co - matrix @ skin.find_nearest(v.co)[0]).length for v in verts_of(loop))
            if gaps[len(gaps) // 2] > band:
                # A fan around the loop's centroid: it closes a loop that
                # touches itself too (holes_fill leaves such a loop open). The
                # centre takes the mean of the loop's weights.
                ring = verts_of(loop)
                deform = bm.verts.layers.deform.active
                centre = bm.verts.new(sum((v.co for v in ring), Vector()) / len(ring))
                if deform is not None:
                    mean = {}
                    for v in ring:
                        for g, w in v[deform].items():
                            mean[g] = mean.get(g, 0.) + w / len(ring)
                    for g, w in mean.items():
                        centre[deform][g] = w
                for e in loop:
                    face = e.link_faces[0]
                    a, b = e.verts
                    # Opposite winding to the face the edge already has.
                    for corner in face.loops:
                        if corner.vert == a and corner.link_loop_next.vert == b:
                            a, b = b, a
                            break
                    bm.faces.new((a, b, centre))
                closed += 1
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return closed


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
    sweep_samples = 80   # chord error < .02 mm at this curvature; segments dominate the field cost
    cl = [curve_root * (1 - t) ** 2 + curve_control * 2 * t * (1 - t) + curve_end * t * t for t in np.linspace(0, 1, sweep_samples)]
    arc = np.concatenate([[0], np.cumsum([(cl[i] - cl[i - 1]).length for i in range(1, sweep_samples)])])
    tparam = arc / arc[-1]
    inner = [root - surface_normal * settings['inner_extension'] * f for f in np.linspace(1, 0, 12, endpoint=False)]
    centerline = np.array([tuple(point) for point in inner] + [tuple(point) for point in cl])
    stations = np.concatenate([np.linspace(-.15, 0, 12, endpoint=False), tparam])
    tip_start = settings['tip_start']
    tip_rim, tip_girth = settings['tip_rim'], settings['tip_girth']


    base_fraction, girth_max = settings['base_fraction'], settings['girth_max']


    # Straight sweep (optional base flare), a short rim step up to the tip girth,
    # then the rounded tip cap.
    def radius(t):
        t = np.asarray(t, float)
        r = np.ones_like(t)
        w_ = np.clip(t / base_fraction, 0, 1)
        r = r * np.where(t < base_fraction, girth_max / (1 + w_ * (girth_max - 1)), 1)
        k = np.clip((t - tip_start) / tip_rim, 0, 1)
        r = np.where((t >= tip_start) & (t < tip_start + tip_rim), 1 + (tip_girth - 1) * k * k * (3 - 2 * k), r)
        u = np.clip((t - tip_start - tip_rim) / (1 - tip_start - tip_rim), 0, 1)
        r = np.where(t >= tip_start + tip_rim, tip_girth * np.maximum(0, 1 - u ** 2.4) ** .55, r)
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
        # Closest segment by the profiled tube distance; the relief (a sub-mm term)
        # and its phase are evaluated once for the chosen segment, not per segment.
        best = np.full(len(P), 1e9)
        bt = np.zeros(len(P))
        bseg = np.zeros(len(P), int)
        bh = np.zeros(len(P))
        for i in range(len(centerline) - 1):
            A, B = centerline[i], centerline[i + 1]
            AB = B - A
            h = np.clip(((P - A) @ AB) / (AB @ AB), 0, 1)
            d = np.linalg.norm(P - (A + h[:, None] * AB), axis=1)
            t = stations[i] + h * (stations[i + 1] - stations[i])
            sd = d - radius(t)
            sel = sd < best
            best[sel], bt[sel], bseg[sel], bh[sel] = sd[sel], t[sel], i, h[sel]
        A = centerline[bseg]
        D = P - (A + bh[:, None] * (centerline[bseg + 1] - A))
        ph = np.arctan2(np.einsum('ij,ij->i', D, SIDE[bseg]), np.einsum('ij,ij->i', D, DOR[bseg]))
        return best - relief(bt, ph), bt


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
        # Ridges sit on the surface: only points near it can be affected by them.
        near = np.where(d < .008 * size_factor)[0]
        if len(near):
            d = d.copy()
            d[near] = smin(d[near], ridge_sdf(P[near]), settings['ridge_blend'] * size_factor)
        return d, t



    pod_factor = (1 + .55 * (size_factor - 1)) * settings['pod_scale']
    # The pods hang plumb from the root: down is world down and back is world
    # back (+Y), whatever the skin's tilt there, so the union's top stays at the
    # root's height on sloping skin too.
    back = Vector((0, 1, 0))
    pod_center = root + down * settings['pods']['down'] * pod_factor + back * settings['pods']['back']
    pod_ellipsoids = [(pod_center + lat * e['lateral'] * pod_factor + down * e['down'] * pod_factor + back * e['back'], np.array(e['radii']) * pod_factor) for e in settings['pods']['ellipsoids']]
    FR = np.array([tuple(lat), tuple(surface_normal), tuple(upv)])


    def smin(a_, b_, k):
        k = np.maximum(k, 1e-9)
        h = np.maximum(k - np.abs(a_ - b_), 0) / k
        return np.minimum(a_, b_) - h * h * k / 4


    def k_body(P):

        d = np.linalg.norm(P - np.array(tuple(root)), axis=1)
        return body_blend * np.clip(1 - (d - settings['body_window']['radius'] * size_factor) / (settings['body_window']['fall'] * size_factor), 0, 1)

    attach_reach = (settings['body_window']['radius'] + settings['body_window']['fall']) * size_factor


    def recede(P):
        """How far the body field sinks beyond the attachment window: none
        inside it, then steeply, so the part's own surface takes over."""
        d = np.linalg.norm(P - np.array(tuple(root)), axis=1)
        return np.maximum(d - attach_reach, 0) * settings['body_window']['recede']


    def ellip(P, c, r):
        q = (P - np.array(tuple(c))) @ FR.T / r
        return (np.linalg.norm(q, axis=1) - 1) * r.min()


    folds = settings['pods']['folds']


    def pod_folds(P):
        """Crease depth in [0, 1], faded out near the root.

        Narrow creases sit on the zero lines of a warped mix of three
        non-commensurate waves: wrinkles of varying length and direction,
        mostly transverse, with smooth skin between them."""
        q = (P - np.array(tuple(pod_center))) @ FR.T / pod_factor
        x, y, z = q[:, 0], q[:, 1], q[:, 2]
        lam, wl = folds['wavelength'], folds['wobble_wavelength']
        w_ = folds['wobble'] * (np.sin(2 * np.pi * x / wl + 1.7) + .6 * np.sin(2 * np.pi * (x - .7 * y + .4 * z) / (.57 * wl) + .4))
        s_ = z + w_
        n_ = (.6 * np.sin(2 * np.pi * s_ / lam)
              + .45 * np.sin(2 * np.pi * (.38 * x + .92 * s_) / (1.41 * lam) + 2.1)
              + .3 * np.sin(2 * np.pi * (-.52 * x + .85 * s_ + .3 * y) / (.79 * lam) + .7))
        crease = np.exp(-(n_ / folds['width']) ** 2)
        strength = .55 + .45 * np.sin(2 * np.pi * (.8 * x + .6 * z) / (3.1 * lam) + 1.1)
        r_ = np.linalg.norm(P - np.array(tuple(root)), axis=1) / pod_factor
        return crease * strength * np.clip((r_ - folds['root_clear']) / folds['root_fall'], 0, 1)


    def pods_sdf(P):
        if not pod_ellipsoids:
            return np.full(len(P), 1e9)
        d = ellip(P, *pod_ellipsoids[0])
        for c, r in pod_ellipsoids[1:]:
            d = smin(d, ellip(P, c, r), settings['pods']['blend'] * pod_factor)
        # Creases only cut inward (half-wave), the raphe is a low ridge on the midline.
        near = np.where(d < .006 * pod_factor)[0]
        if len(near):
            d = d.copy()
            Pn = P[near]
            x = ((Pn - np.array(tuple(pod_center))) @ np.array(tuple(lat))) / pod_factor
            raphe = folds['raphe'] * np.exp(-(x / folds['raphe_width']) ** 2)
            fade = np.clip((np.linalg.norm(Pn - np.array(tuple(root)), axis=1) / pod_factor - folds['root_clear']) / folds['root_fall'], 0, 1)
            d[near] += (folds['depth'] * pod_folds(Pn) - raphe * fade) * pod_factor
        return d


    def pod_link_k(station):
        """Shaft-pods blend radius: the web near the root, tight along the free shaft."""
        web = np.clip(1 - np.asarray(station, float) / settings['pod_web']['until'], 0, 1)
        return pod_blend + settings['pod_web']['blend'] * size_factor * web * web * (3 - 2 * web)



    # The outer skin is told from an inner wall on the body as delivered (see
    # OuterSkin.refit); its tree follows the flattened positions below.
    bvh = OuterSkin(body, root, .25)
    print('inner wall faces skipped', bvh.inner_wall_faces)
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
    # A double-walled body (see OuterSkin) carries an inner wall a few mm under
    # its skin. Flattening the skin deeper than that pushed it through the wall:
    # the wall then lay in front of the skin, the outer-skin test took the skin
    # for an inner wall, and a client that draws front faces only looked through
    # the window into the hollow body (Ruling A65e). Each inner-wall vertex
    # under the window is paired with the skin point in front of it (a ray
    # against its normal) and moves with that point.
    polys_ = body.data.polygons
    full_ = BVHTree.FromPolygons([v.co.copy() for v in body.data.vertices], [p_.vertices[:] for p_ in polys_])
    reach_ = window['wall_reach']
    def near_window(point):
        return (abs(point.x - cen.x) < window['lateral'] + reach_ and cen.z - window['below'] - reach_ < point.z < root.z + window['above'] + reach_
                and point.y < cen.y + window['front'] + reach_)
    region_ = {p_.index for p_ in polys_ if near_window(body_matrix @ p_.center)}
    enclosed_ = {i for i in region_ if _common.enclosed(full_, polys_[i].center, polys_[i].normal)}
    reach_local = reach_ / max(body_matrix.to_scale())
    wall_pairs = {}
    for grp in keyv.values():
        if not all(f.index in enclosed_ for c in grp for f in c.link_faces):
            continue
        normal_ = sum((body.data.vertices[c.index].normal for c in grp), Vector()).normalized()
        origin_, travelled = grp[0].co - normal_ * 1e-5, 0.
        while travelled < reach_local:
            hit_, _, face_, distance_ = full_.ray_cast(origin_, -normal_, reach_local - travelled)
            if hit_ is None:
                break
            if face_ in region_ and face_ not in enclosed_:
                wall_pairs[id(grp)] = (grp, face_, hit_)
                break
            travelled += distance_ + 1e-5
            origin_ = hit_ - normal_ * 1e-5
    orig_all = [v.co.copy() for v in bmb.verts]
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
    # Each window vertex moved along its own normal, its neighbours outside the
    # window not at all: on a coarse body the window's edge became a serrated
    # line of creases, up to 53 degrees sharper than the body's, lit like a
    # torn edge under the part (Ruling A65e). The displacement is smoothed over
    # the skin around the window, held at zero beyond `wall_reach`; the inner
    # wall (paired above) follows below.
    skin_groups = [g for g in keyv.values() if near_window(body_matrix @ orig_all[g[0].index]) and id(g) not in wall_pairs
                   and not all(f.index in enclosed_ for c in g for f in c.link_faces)]
    slot = {id(g): i for i, g in enumerate(skin_groups)}
    links = []
    for g in skin_groups:
        ring = set()
        for c in g:
            for e in c.link_edges:
                other = keyv[tuple(round(x / 1e-5) for x in orig_all[e.other_vert(c).index])]
                if other is not g:
                    ring.add(slot.get(id(other), -1))
        links.append(list(ring))
    shift_ = [g[0].co - orig_all[g[0].index] for g in skin_groups]
    for _ in range(window['blend']):
        shift_ = [(shift_[i] + sum((shift_[j] if j >= 0 else Vector() for j in links[i]), Vector()) / len(links[i])) / 2 if links[i] else shift_[i]
                  for i in range(len(skin_groups))]
    for g, s_ in zip(skin_groups, shift_):
        for c in g:
            c.co = orig_all[c.index] + s_
    from mathutils.interpolate import poly_3d_calc
    wall_moved = 0
    for grp, face_, hit_ in wall_pairs.values():
        corners = polys_[face_].vertices[:]
        shares = poly_3d_calc([orig_all[j] for j in corners], hit_)
        shift = sum(((bmb.verts[j].co - orig_all[j]) * w_ for j, w_ in zip(corners, shares)), Vector())
        if shift.length > 1e-7:
            for c in grp:
                c.co = orig_all[c.index] + shift
            wall_moved += len(grp)
    print('inner wall verts moved with the window', wall_moved, 'paired', sum(len(g) for g, _, _ in wall_pairs.values()))
    seam_cracks = sum(max((c.co - grp[0].co).length for c in grp) > 1e-6 for grp in keyv.values() if len(grp) > 1)
    bmb.to_mesh(body.data); bmb.free(); body.data.update()
    print('window verts flattened', flat, 'of', len(mask))
    # Transfer only radial upper-leg influences to the anchor. The band grows
    # with the part like its window does: a larger part's attachment border
    # reaches further onto the thigh crease, and skin there on thigh weights
    # pulled that border (and the part with it) toward the legs (A180).
    hips_g = body.vertex_groups[anchor_name]
    legs = [g for g in body.vertex_groups if g.name.endswith('UpLeg')]
    moved = 0
    reweight_from, reweight_to = settings['reweight']['from'] * size_factor, settings['reweight']['to'] * size_factor
    for v in body.data.vertices:
        d = (body_matrix @ v.co - root).length
        f = float(np.clip(1 - (d - reweight_from) / (reweight_to - reweight_from), 0, 1))
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
    bvh.refit()
    # Skin faces near the window that the outer-skin test now takes for an inner
    # wall: the flatten pushed them behind one. A diagnostic only: the skin
    # field keeps them as skin (see OuterSkin.refit).
    flattened_tree = BVHTree.FromPolygons([v.co.copy() for v in body.data.vertices], [p_.vertices[:] for p_ in polys_])
    window_skin_lost = sum(_common.enclosed(flattened_tree, polys_[i].center, polys_[i].normal) for i in region_ - enclosed_)
    print('window skin faces lost to the inner wall', window_skin_lost)


    # Sample root-local unions of sweep, ridges, pods and body skin.
    # The grid also spans the sweep's top above the root plus its body fillet:
    # with only the 20 mm margin a wide root was cut off flat there.
    crown = root + upv * (shaft_radius * girth_max + body_blend)
    pts = np.vstack([centerline, [tuple(crown)], *[np.array(tuple(c)) + np.diag(r) for c, r in pod_ellipsoids], *[np.array(tuple(c)) - np.diag(r) for c, r in pod_ellipsoids]])
    lo, hi = pts.min(0) - .02, pts.max(0) + .02
    nx, ny, nz = (np.ceil((hi - lo) / voxel)).astype(int) + 1
    if int(nx) * int(ny) * int(nz) > 8_000_000:
        raise ValueError('Part voxel grid exceeds 8 million samples')
    gx, gy, gz = (lo[0] + np.arange(nx) * voxel, lo[1] + np.arange(ny) * voxel, lo[2] + np.arange(nz) * voxel)
    grid_points = np.stack(np.meshgrid(gx, gy, gz, indexing='ij'), -1).reshape(-1, 3)
    print('grid', nx, ny, nz, len(grid_points))
    ds, dt = shaft_sdf(grid_points)
    dc = pods_sdf(grid_points)
    part = smin(ds, dc, pod_link_k(dt))
    db = np.full(len(grid_points), 1.0)
    band = np.where(part < 2.5 * body_blend)[0]
    for i in band:
        point = Vector(grid_points[i])
        q, n, _, _ = bvh.find_nearest(body_inverse @ point)
        q, n = body_matrix @ q, (normal_matrix @ n).normalized()
        v = point - q
        db[i] = v.length * (1 if v.dot(n) >= 0 else -1)
    print('field done, band', len(band))


    def opened(P, holes):
        """The body field sinks away within `body_blend` of a hole's border."""
        if holes is None or not len(holes):
            return np.zeros(len(P))
        tree = KDTree(len(holes))
        for j, point in enumerate(holes):
            tree.insert(point, j)
        tree.balance()
        near = np.array([tree.find(Vector(point))[2] for point in P])
        # 10 cm: deeper than any body distance sampled in the band.
        return np.clip(1 - near / body_blend, 0, 1) * .1


    def shell(holes):
        """Surface-net the union and keep the visible shell (with its hidden band at the root)."""
        sink = recede(grid_points)
        sink[band] += opened(grid_points[band], holes)
        U = smin(part, db + settings['skin_sink'] + sink, k_body(grid_points))
        field = U.reshape(nx, ny, nz)


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
                # Counter-clockwise seen from outside: the part's normals face out.
                quads.append(c if flip else c[::-1])
        quads = np.array(quads)
        print('verts', len(positions), 'quads', len(quads))


        # Keep the shell, including a short hidden band at the root.
        shaft_distance, part_station = shaft_sdf(positions)
        pod_distance = pods_sdf(positions)
        part_distance = smin(shaft_distance, pod_distance, pod_link_k(part_station))
        skin_distance = np.empty(len(positions))
        skin_nearest = []
        for i, point in enumerate(positions):
            q, n, fi, _ = bvh.find_nearest(body_inverse @ Vector(point))
            q, n = body_matrix @ q, (normal_matrix @ n).normalized()
            skin_distance[i] = (Vector(point) - q).dot(n)
            skin_nearest.append((q, fi))
        near_root = (np.abs(positions[:, 0] - root.x) < settings['hidden_band']['lateral'] * size_factor) & (positions[:, 2] > root.z + settings['hidden_band']['above'] * size_factor) & (np.linalg.norm(positions - np.array(tuple(root)), axis=1) < settings['hidden_band']['radius'] * size_factor)
        # Beyond the window the part's own surface stays, under the skin too: a pod
        # resting on a thigh or a crease of the body there kept a cut edge that a
        # pose pulled open, or a hole where the body's walls cross (Ruling A65c).
        free_surface = (recede(positions) + opened(positions, holes) > 0) & (np.abs(part_distance) < .5 * voxel)
        keepv = (part_distance < 1.15 * body_blend) & (np.where(near_root, skin_distance > -settings['hidden_band']['depth'], skin_distance > .0006) | free_surface)
        quads = quads[keepv[quads].all(1)]
        # Every visible piece carries part surface (a flat body can split the
        # shaft from the pods). An island that is all skin fillet comes from a
        # folded inner wall where the thighs meet the body: drop it.
        parent_ = np.arange(len(positions))

        def find_(i):
            while parent_[i] != i:
                parent_[i] = parent_[parent_[i]]
                i = parent_[i]
            return i
        for face in quads:
            r0 = find_(face[0])
            for vi in face[1:]:
                r1 = find_(vi)
                if r1 != r0:
                    parent_[r1] = r0
        stray_faces = 0
        if len(quads):
            vertex_roots = np.array([find_(i) for i in range(len(positions))])
            face_vertices = np.unique(quads)
            on_part = np.unique(vertex_roots[face_vertices[np.abs(part_distance[face_vertices]) < voxel]])
            keep_face = np.isin(vertex_roots[quads[:, 0]], on_part)
            stray_faces = int(np.count_nonzero(~keep_face))
            quads = quads[keep_face]
        print('stray faces dropped', stray_faces)
        used = np.unique(quads)
        remap = -np.ones(len(positions), int)
        remap[used] = np.arange(len(used))
        if not len(used):
            raise ValueError('Part field produced no visible faces')
        return (positions[used], remap[quads], shaft_distance[used], part_station[used], pod_distance[used],
                part_distance[used], [skin_nearest[i] for i in used], skin_distance[used], stray_faces)


    def hole_borders(positions, quads, skin_distance):
        """Vertices of the open border loops that are holes: besides the loop
        passing closest to the root, every loop lying mostly in the outer half
        of the window's fall, where the union no longer forms a fillet and only
        cuts, and not deep in the body (where the part's own surface ends
        hidden beyond the window). A pod rising out of the skin nearer the root
        keeps its fillet loop."""
        count = {}
        for face in quads:
            for a, b in zip(face, np.roll(face, -1)):
                edge = (min(int(a), int(b)), max(int(a), int(b)))
                count[edge] = count.get(edge, 0) + 1
        link = {}
        for (a, b), c in count.items():
            if c == 1:
                link.setdefault(a, []).append(b)
                link.setdefault(b, []).append(a)
        loops, seen = [], set()
        for start in link:
            if start in seen:
                continue
            loop, stack = [], [start]
            seen.add(start)
            while stack:
                v = stack.pop()
                loop.append(v)
                for w in link[v]:
                    if w not in seen:
                        seen.add(w)
                        stack.append(w)
            loops.append(loop)
        if len(loops) < 2:
            return []
        distance = np.linalg.norm(positions - np.array(tuple(root)), axis=1)
        attachment = min(range(len(loops)), key=lambda k: distance[loops[k]].min())
        share = k_body(positions) / body_blend
        return [v for k, loop in enumerate(loops)
                if k != attachment and np.median(share[loop]) < .5 and np.median(skin_distance[loop]) > -2 * voxel
                for v in loop]


    (positions, quads, shaft_distance, part_station, pod_distance, part_distance,
     skin_nearest, skin_distance, stray_faces) = shell(None)
    # A loop hole_borders names is a hole: the body field cut the part where it only met skin
    # (a crease whose walls cross, a thigh). The field gives way around it and
    # the part keeps its own surface there (Ruling A65c).
    # Closing one can uncover a smaller one beside it: up to three passes.
    hole_points = []
    for _ in range(3):
        holes = hole_borders(positions, quads, skin_distance)
        if not holes:
            break
        hole_points += [tuple(p) for p in positions[holes]]
        (positions, quads, shaft_distance, part_station, pod_distance, part_distance,
         skin_nearest, skin_distance, stray_faces) = shell(hole_points)
    holes_left = len(hole_borders(positions, quads, skin_distance))
    print('hole border vertices opened', len(hole_points), 'left', holes_left)
    print('kept verts', len(positions), 'quads', len(quads))


    # Blend skin texels by fillet share and lift above the body.
    fillet_weight = np.clip(part_distance / body_blend, 0, 1)
    fillet_weight = fillet_weight * fillet_weight * (3 - 2 * fillet_weight)
    tip_weight = np.clip((part_station - tip_start) / .06, 0, 1) * (shaft_distance < pod_distance)
    tone_p = (.5 + .5 * tip_weight) * (1 - fillet_weight)

    wl = np.clip(1 - skin_distance / settings['border_lift'], 0, 1)
    # Only where the part is attached: the free surface beyond the window keeps its tone.
    wl = wl * wl * (3 - 2 * wl) * (k_body(positions) / body_blend)
    skin_weight = np.maximum(fillet_weight, wl)
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


    def nearest_skin(point):
        q, _, fi, _ = bvh.find_nearest(body_inverse @ Vector(point))
        return body_matrix @ q, fi


    # The part's tone comes from the skin where it attaches: rings around the
    # root, from the shaft's girth out to the edge of the body fillet, projected
    # onto the outer skin. The belly 5-15 cm higher is often paler than the groin.
    ring_u = surface_normal.cross(lat).normalized()
    cols = []
    for ring_radius in np.linspace(shaft_radius, shaft_radius + body_blend, 4):
        for angle in np.linspace(0, 2 * math.pi, 32, endpoint=False):
            probe = root + (lat * math.cos(angle) + ring_u * math.sin(angle)) * ring_radius
            q, _, fi, _ = bvh.find_nearest(body_inverse @ probe)
            if fi is not None:
                cols.append(skin_texel(body_matrix @ q, fi))
    skin_tone = np.median(np.array(cols), 0) if cols else skin_texel_fallback(pixels)
    print('root skin tone', [round(float(c), 3) for c in skin_tone], 'samples', len(cols))
    dark = skin_tone * np.array(settings['tone']['shaft'])
    tip = dark * np.array(settings['tone']['tip'])

    # Smoothing and decimation soften the creases; the bake keeps them readable.
    pod_share = np.clip(.5 + (shaft_distance - pod_distance) / .01, 0, 1)
    crease_shade = folds['shade'] * pod_folds(positions) * pod_share
    vertex_colors = np.zeros((len(positions), 4))
    for i in range(len(positions)):
        tone = (dark * (1 - tip_weight[i]) + tip * tip_weight[i]) * (1 - crease_shade[i])
        under = skin_texel(*skin_nearest[i]) if skin_weight[i] > 0 else skin_tone
        vertex_colors[i, :3] = under * skin_weight[i] + tone * (1 - skin_weight[i])
        vertex_colors[i, 3] = 1
    # Transfer skin weights at the border; known part weights elsewhere.
    gname = {g.index: g.name for g in body.vertex_groups}


    def skin_share(q, fi):
        """Inverse-distance shares of the corners of body polygon ``fi`` at world point ``q``."""
        poly = body.data.polygons[fi]
        share = []
        for li in poly.loop_indices:
            vi = body.data.loops[li].vertex_index
            share.append((li, vi, 1 / ((body_matrix @ body.data.vertices[vi].co - q).length + 1e-5)))
        total = sum(w for _, _, w in share)
        return [(li, vi, w / total) for li, vi, w in share]


    def skin_weights_at(q, fi):
        """Body weights interpolated across the nearest polygon: the nearest
        vertex alone steps from one vertex's weights to the next along the seam."""
        out_ = {}
        for _, vi, share in skin_share(q, fi):
            groups_ = body.data.vertices[vi].groups
            tot_ = sum(g.weight for g in groups_) or 1
            for g in groups_:
                out_[gname[g.group]] = out_.get(gname[g.group], 0) + share * g.weight / tot_
        return out_


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
    glue = border_strip(positions, boundary_edges, border, settings['seam']['band'])
    vertex_weights = []
    for i, point in enumerate(positions):
        ws_ = shaft_weights(max(part_station[i], 0))

        near_sh = float(np.clip(1 - max(shaft_distance[i], 0) / settings['pod_link_distance'], 0, 1)) ** 1.5 * settings['pod_link']
        wc_ = {pod_bone: 1 - near_sh, chain[0]['bone']: near_sh}
        # Shaft vs pods weights blend only across the junction (about 15 mm to each
        # side of the equal-distance surface); a wide one-sided ramp left the
        # shaft's underside on the pods bone, which shears it when the chain lifts.
        mix = np.clip(.5 + (pod_distance[i] - shaft_distance[i]) / .03, 0, 1)
        w = {}
        for d_, f_ in ((ws_, mix), (wc_, 1 - mix)):
            for k_, x_ in d_.items():
                w[k_] = w.get(k_, 0) + x_ * f_
        # The skin fillet takes the skin's weights, and so does every open border
        # with its strip (`seam.band` along the mesh): a border on part weights
        # rose off the skin when the chain lifted (4 mm, Ruling A65c). Beyond the
        # window the part is closed and has no border. Both shares are continuous.
        wroot = max(fillet_weight[i], glue[i])
        if wroot > 0:
            bw = skin_weights_at(*skin_nearest[i])
            w = {k_: x_ * (1 - wroot) for k_, x_ in w.items()}
            for k_, x_ in bw.items():
                w[k_] = w.get(k_, 0) + wroot * x_
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
    # The decimation can leave a face twice; the glTF export validates the mesh
    # and drops the copy, which opened a pinhole no border pass had seen.
    # Validate now, so every border is final from here on.
    partobj.data.validate()
    # A hole loop that ends away from the skin is a gap in the part's own
    # closed surface (the cut left it where the part only rested on a thigh);
    # landing it on the nearest skin drew faces across to the thigh (A180).
    # It is closed with the vertices it has; the attachment loop (closest to
    # the root) and a hole lying on the skin stay open and land below.
    holes_closed = close_free_holes(partobj, bvh, body_inverse @ root, settings['seam']['band'], body_matrix)
    final_positions = np.array([tuple(body_matrix @ v.co) for v in partobj.data.vertices])
    final_ds, final_t = shaft_sdf(final_positions)
    final_dc = pods_sdf(final_positions)
    edge_counts = {}
    for poly in partobj.data.polygons:
        for edge in poly.edge_keys:
            edge_counts[edge] = edge_counts.get(edge, 0) + 1
    final_border = {vi for edge, count in edge_counts.items() if count == 1 for vi in edge}
    seam = settings['seam']
    strip = border_strip(final_positions, edge_counts, final_border, seam['band'])
    # Only the attachment loop (the border loop passing closest to the root)
    # moves with the skin it grows from. A hole loop left where the part only
    # rests on a thigh took that thigh's weights at full share, so a pose that
    # parted the legs pulled strands from the part to the thigh (A180): such a
    # loop and its strip stay on the part's side of the weights.
    border_links = {}
    for (a, b), count in edge_counts.items():
        if count == 1:
            border_links.setdefault(a, []).append(b)
            border_links.setdefault(b, []).append(a)
    border_loops, seen_ = [], set()
    for start in border_links:
        if start in seen_:
            continue
        loop_, stack_ = [], [start]
        seen_.add(start)
        while stack_:
            v_ = stack_.pop()
            loop_.append(v_)
            for w_ in border_links[v_]:
                if w_ not in seen_:
                    seen_.add(w_)
                    stack_.append(w_)
        border_loops.append(loop_)
    root_xyz = np.array(tuple(root))
    attach_border = set(min(border_loops, key=lambda loop_: np.linalg.norm(final_positions[loop_] - root_xyz, axis=1).min())) if border_loops else set()
    hole_border = final_border - attach_border
    attach_strip = border_strip(final_positions, edge_counts, attach_border, seam['band'])
    # Preserve the reference's interpolated weights after both modifiers.
    # Reclassifying a smoothed vertex by its new station creates hard seams.
    tip_count = int(np.count_nonzero((final_t >= tip_start + .015) & (final_ds < final_dc)))
    for vertex in partobj.data.vertices:
        i = vertex.index
        # Incidental skin contacts must not give the free shell thigh motion.
        # The root's skin transfer remains intact within the 35 mm root ball,
        # and a border strip keeps the skin's weights: it moves with the skin.
        if (Vector(final_positions[i]) - root).length > .035 and attach_strip[i] < 1:
            take = 0.
            for group_, weight_ in [(e.group, e.weight) for e in vertex.groups]:
                vg = partobj.vertex_groups[group_]
                if vg.name.endswith('UpLeg'):
                    moved_ = weight_ * (1 - attach_strip[i])
                    take += moved_
                    if weight_ - moved_ > 1e-4:
                        vg.add([i], weight_ - moved_, 'REPLACE')
                    else:
                        vg.remove([i])
            if take:
                vg = partobj.vertex_groups.get(anchor_name) or partobj.vertex_groups.new(name=anchor_name)
                current = next((entry.weight for entry in vertex.groups if entry.group == vg.index), 0.)
                vg.add([i], current + take, 'REPLACE')
    print('part tris', sum(len(poly.vertices) - 2 for poly in partobj.data.polygons))

    # The attachment seam (Ruling A65b). Smoothing an open border curls it off
    # the skin, and the fillet's own normals shade it apart from the body: the
    # part looked set onto the body. The fillet share above the skin now falls
    # onto it with a cubic profile (tangent at the skin, its edge `tuck` under
    # it: Ruling A65c), and its normals turn to the body's corner normals. Away
    # from the fillet and an open border nothing moves.
    final_pd = smin(final_ds, final_dc, pod_link_k(final_t))
    fillet_share = np.clip(final_pd / body_blend, 0, 1)
    fillet_share = fillet_share * fillet_share * (3 - 2 * fillet_share)
    # An open border lands under the skin whatever its height, wherever it is;
    # the strip within `band` of it, measured along the mesh, follows it down.
    seam_share = np.maximum(fillet_share, strip)
    corner_normals = body.data.corner_normals
    pme = partobj.data
    body_normal, skin_height = [], np.zeros(len(final_positions))
    seam_moved = 0
    for i, point in enumerate(final_positions):
        point = Vector(point)
        hit_ = bvh.find_nearest(body_inverse @ point)
        q, fi = body_matrix @ hit_[0], hit_[2]
        nb = sum((corner_normals[li].vector * share for li, _, share in skin_share(q, fi)), Vector())
        nb = (normal_matrix @ nb).normalized()
        body_normal.append(nb)
        # Height over the landing level `tuck` under the skin.
        height = (point - q).dot(nb) + seam['tuck']
        if bvh.inside_beside(body_inverse @ point, hit_):
            # Deep in the body, beside a far skin: hidden, nothing to land.
            height = -(point - q).length
        skin_height[i] = height
        if height <= 0 or seam_share[i] <= 0:
            continue
        g = float(np.clip(1 - height / seam['band'], 0, 1))
        # Whatever its height only the attachment loop lands: a hole loop
        # landed on the nearest skin, a thigh 10 cm away beside the tip, and
        # its faces spanned the gap (A180). It lands within `band` only.
        move = height * max(g * g * (3 - 2 * g), attach_strip[i]) * seam_share[i]
        if move > 1e-7:
            pme.vertices[i].co = body_inverse @ (point - nb * move)
            skin_height[i] -= move
            seam_moved += 1
    # In a fold the move can bring an edge over the opposite skin: land it again.
    # Beside its skin (see OuterSkin.inside_beside) an edge inside the body stays,
    # one outside lands on the nearest skin point.
    for _ in range(2):
        for i in final_border:
            point = body_matrix @ pme.vertices[i].co
            hit_ = bvh.find_nearest(body_inverse @ point)
            q, normal_ = body_matrix @ hit_[0], (normal_matrix @ hit_[1]).normalized()
            if i in hole_border and (point - q).length > seam['band']:
                continue
            beside = bvh.inside_beside(body_inverse @ point, hit_)
            if beside is None:
                height = (point - q).dot(normal_) + seam['tuck']
                if height > 1e-6:
                    pme.vertices[i].co = body_inverse @ (point - normal_ * height)
            elif not beside:
                pme.vertices[i].co = body_inverse @ (q - normal_ * seam['tuck'])
    # Decimation blended a trace of the part's bones back into the border; on
    # the skin's weights alone it stays where the skin is in every pose.
    hole_leg_moved = 0
    for i in final_border:
        point = body_matrix @ pme.vertices[i].co
        q, _, fi, _ = bvh.find_nearest(body_inverse @ point)
        for entry in list(pme.vertices[i].groups):
            partobj.vertex_groups[entry.group].remove([i])
        skin_ = skin_weights_at(body_matrix @ q, fi)
        if i in hole_border and (Vector(final_positions[i]) - root).length > .035:
            leg_ = sum(w_ for n_, w_ in skin_.items() if n_.endswith('UpLeg'))
            skin_ = {n_: w_ for n_, w_ in skin_.items() if not n_.endswith('UpLeg')}
            skin_[anchor_name] = skin_.get(anchor_name, 0.) + leg_
            hole_leg_moved += leg_ > 1e-4
        for name_, weight_ in skin_.items():
            if weight_ > 1e-4:
                vg = partobj.vertex_groups.get(name_) or partobj.vertex_groups.new(name=name_)
                vg.add([i], weight_, 'REPLACE')
    pme.update()
    custom = []
    # The same share later wears the body's own texture (see the bake).
    seam_attribute = pme.attributes.new('seam', 'FLOAT', 'POINT')
    opposed = 0
    for v in pme.vertices:
        i = v.index
        g = float(np.clip(1 - max(skin_height[i], 0) / seam['normal_band'], 0, 1))
        c = max(g * g * (3 - 2 * g), strip[i]) * seam_share[i]
        own = (normal_matrix @ v.normal).normalized()
        # Only skin the part grows out of lends its normal. In a fold the
        # nearest skin is the opposite wall, facing the part: its normal turned
        # the pouch's underside inside out, a bright or black band from below
        # (Ruling A65d). Full share from 60 degrees apart, none from 90.
        a = float(np.clip(own.dot(body_normal[i]) / .5, 0, 1))
        agree = a * a * (3 - 2 * a)
        if c > 0 and agree < 1:
            opposed += 1
        c *= agree
        custom.append(tuple((inverse_normal_matrix @ own.lerp(body_normal[i], c)).normalized()))
        seam_attribute.data[i].value = c
    pme.normals_split_custom_set_from_vertices(custom)
    print('seam vertices moved', seam_moved, 'opposed normals', opposed)

    # Extract a clean skin square from the UV island at the root. Only texels
    # near the root's skin tone count: clothing painted onto the body (a top
    # above the groin) must not lend its weave to the part.
    hb = bvh.ray_cast(body_inverse @ (root + Vector((0, -.25, 0))), inverse_normal_matrix @ Vector((0, 1, 0)))
    face0 = hb[2]
    if face0 is None:
        raise ValueError('Skin patch ray missed the body')
    # Edges are keyed by position: a flat-shaded or seamed import splits the
    # vertices of neighbouring faces, and the flood must still cross them.
    vkey = [tuple(round(c / 1e-5) for c in v.co) for v in body.data.vertices]
    ek = {}
    for poly in body.data.polygons:
        for e_ in poly.edge_keys:
            ek.setdefault(frozenset((vkey[e_[0]], vkey[e_[1]])), []).append(poly.index)
    isl, st_ = {face0}, [face0]
    c0 = body_matrix @ body.data.polygons[face0].center
    while st_:
        f_ = st_.pop()
        for e_ in body.data.polygons[f_].edge_keys:
            for g_ in ek[frozenset((vkey[e_[0]], vkey[e_[1]]))]:
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

    def largest_square(m):
        ys_, xs_ = np.nonzero(m)
        if not len(ys_):
            return 0, 0, 0
        y0b, x0b = ys_.min(), xs_.min()
        sub = m[y0b:ys_.max() + 1, x0b:xs_.max() + 1]
        dp = np.zeros(sub.shape, int)
        for i_ in range(sub.shape[0]):
            for j_ in range(sub.shape[1]):
                if sub[i_, j_]:
                    dp[i_, j_] = 1 + (min(dp[i_ - 1, j_], dp[i_, j_ - 1], dp[i_ - 1, j_ - 1]) if i_ and j_ else 0)
        i_, j_ = np.unravel_index(dp.argmax(), dp.shape)
        size = min(int(dp[i_, j_]) - 2, settings['texture']['patch_max'])
        return size, y0b + i_ - size + 1, x0b + j_ - size + 1
    skin_like = np.abs(pixels[..., :3] - skin_tone).max(-1) < settings['texture']['tone_tolerance']
    S_, y0p, x0p = largest_square(mask & skin_like)
    if S_ < 8:
        # Too little root-coloured skin in the island: any clean square beats none.
        S_, y0p, x0p = largest_square(mask)
    if S_ < 1:
        raise ValueError('No clean skin patch in the UV island')
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
    seam_texels = project_body_texture(partobj, bimg, nt, lambda P: np.array([skin_texel(*nearest_skin(p)) for p in P]), root)
    print('seam texels from the body texture', seam_texels)
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
    me_.attributes.remove(me_.attributes['seam'])
    for im in (im_shaft, im_tip):
        bpy.data.images.remove(im)
    print('baked', BS)
    _common.progress('exporting')
    bpy.ops.export_scene.gltf(filepath=str(output), export_format='GLB', export_apply=False, export_yup=True, export_skins=True, export_animations=True, export_morph=True, export_all_influences=False, export_extras=True)
    _common.body_meshes_first(output)
    return {
        'status': 'applied', 'reason': '', 'size_factor': size_factor,
        'protrusion_mm': protrusion, 'flattened_vertices': flat,
        'reweighted_vertices': moved, 'part_tris': sum(len(poly.vertices) - 2 for poly in partobj.data.polygons),
        'skin_patch_px': S_, 'skin_patch_cm': S_ * mpp * 100,
        'tip_vertices': tip_count,
        'border_vertices': len(final_border), 'hole_border_leg_moved': hole_leg_moved, 'free_holes_closed': holes_closed,
        'seam_vertices': seam_moved, 'seam_opposed_normals': opposed,
        'hole_border_vertices': len(hole_points), 'hole_border_vertices_left': holes_left,
        'cracked_seam_groups': int(seam_cracks), 'flatten_outward_m': flatten_outward,
        'inner_wall_moved': wall_moved, 'window_skin_lost': window_skin_lost,
        'inner_wall_faces': bvh.inner_wall_faces, 'stray_faces': stray_faces,
    }


def project_body_texture(partobj, baked, tree, sample_skin, root):
    """Lay the body's own texture over the seam share of the baked atlas.

    Vertex colours sample the skin only at the vertices, a few mm apart, so
    the part's edge showed a blurred copy of the skin beside the real one
    (Ruling A65b). Two more EMIT bakes on the part's UVs give every atlas texel
    its 'seam' share and its point on the part; each texel with a share takes
    the body's texel at the nearest outer-skin point (``sample_skin``, sRGB like
    the atlas) by that share. Both bakes keep the scene's margin, so texels
    just outside a UV island (sampled by texture filtering) take part too. A
    ray projection would meet the inner wall of a double-walled body in front
    of the flattened skin.
    """
    size = baked.size[0]
    share_image = bpy.data.images.new('part_seam_share', size, size, alpha=False, float_buffer=True)
    point_image = bpy.data.images.new('part_seam_point', size, size, alpha=False, float_buffer=True)
    span = .25   # metres either side of the root the point bake encodes
    tree.nodes.clear()
    out = tree.nodes.new('ShaderNodeOutputMaterial')
    emit = tree.nodes.new('ShaderNodeEmission')
    tree.links.new(emit.outputs['Emission'], out.inputs['Surface'])
    target = tree.nodes.new('ShaderNodeTexImage')
    tree.nodes.active = target
    share = tree.nodes.new('ShaderNodeAttribute')
    share.attribute_name = 'seam'
    tree.links.new(share.outputs['Fac'], emit.inputs['Color'])
    target.image = share_image
    bpy.ops.object.bake(type='EMIT')
    geometry = tree.nodes.new('ShaderNodeNewGeometry')
    offset = tree.nodes.new('ShaderNodeVectorMath')
    offset.operation = 'MULTIPLY_ADD'
    offset.inputs[1].default_value = (.5 / span,) * 3
    offset.inputs[2].default_value = tuple(.5 - c * .5 / span for c in root)
    tree.links.new(geometry.outputs['Position'], offset.inputs[0])
    tree.links.new(offset.outputs['Vector'], emit.inputs['Color'])
    target.image = point_image
    bpy.ops.object.bake(type='EMIT')
    weight = np.empty(size * size * 4, np.float32)
    share_image.pixels.foreach_get(weight)
    weight = np.clip(weight.reshape(size, size, 4)[..., 0], 0, 1)
    points = np.empty(size * size * 4, np.float32)
    point_image.pixels.foreach_get(points)
    points = (points.reshape(size, size, 4)[..., :3] - .5) * 2 * span + np.array(tuple(root))
    base = np.empty(size * size * 4, np.float32)
    baked.pixels.foreach_get(base)
    base = base.reshape(size, size, 4)
    texels = np.argwhere(weight > .01)
    if len(texels):
        colours = sample_skin(points[texels[:, 0], texels[:, 1]])
        w_ = weight[texels[:, 0], texels[:, 1]][:, None]
        base[texels[:, 0], texels[:, 1], :3] = base[texels[:, 0], texels[:, 1], :3] * (1 - w_) + colours * w_
        baked.pixels.foreach_set(base.ravel())
    bpy.data.images.remove(share_image)
    bpy.data.images.remove(point_image)
    return len(texels)


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
    _common.progress('building_part')
    metrics = build_part(parts[0], companions, output)
    per_group = {parts[0]['id']: metrics}
    for companion in companions:
        per_group[companion['id']] = {'status': 'applied', 'reason': ''}
    return {'status': 'applied', 'reason': '', 'metrics': per_group, 'groups': per_group}, {'model': str(output)}


if __name__ == '__main__':
    _common.main(attached_part)
