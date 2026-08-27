"""Height grid of a model — the walkable surface, baked (spec-surface-height § 3).

Reports, in the model's glTF axes (x right, y UP, z towards the viewer) AFTER
the sidecar orientation fix (Euler 'YXZ' in degrees, exactly the order
``placeModelSpec`` in packages/scene-render uses):

  box_min, box_max   the hull under the EXACT fix, measured the way three.js'
                     ``Box3.setFromObject`` measures (8 corners of every mesh
                     object's local box through its world matrix, united)
  extent_snapped     [sx, sy, sz] of the same hull under the fix rounded to 90°
                     — the number the client divides ``max_m`` by
  step, origin, cols, rows, values
                     a lattice over the box's XZ extent; ``values[j*cols+i]``
                     is the walkable height of node (i, j) in whole centimetres
                     above ``box_min[1]``, or null where no surface answers
  hits               number of non-null nodes

Cell rule (user decision 2026-08-27): the LOWEST upward-facing hit that has at
least ``clearance`` metres of air above it (to the next hit of any facing) —
under a high overhang the ground below wins, under a low ledge the ledge does,
a solid rock answers its top (its underside faces down and never counts). The
topmost hit has infinite air, so any node with an upward-facing hit answers.

Rays are cast at the node's lattice position clamped 1 mm INSIDE the box, so
the boundary ring answers the model's edge instead of grazing it; the lattice
itself stays uniform.

Params: rotation {x,y,z} (deg), step (m), clearance (m), max_cells (int).
Blender-side Python only (bpy, mathutils, stdlib).
"""
import math
import sys
from pathlib import Path

# The scripts directory is on the search path for the sibling import ONLY, and
# comes straight back off it (same reason as in measure.py).
_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bpy                                                    # noqa: E402
from mathutils import Matrix, Vector                          # noqa: E402
from mathutils.bvhtree import BVHTree                         # noqa: E402

EDGE_NUDGE = 0.001
RAY_EPS = 1e-5


def _gltf(v):
    """Blender world (Z up) -> glTF axes (Y up): the importer's own conversion, undone."""
    return Vector((v.x, v.z, -v.y))


def _fix_matrix(rot, snap):
    """three.js Euler 'YXZ' as a 3x3 matrix: R = Ry * Rx * Rz (applied to column vectors)."""
    def deg(axis):
        v = float(rot.get(axis, 0) or 0)
        if snap:
            v = round(v / 90.0) * 90.0
        return math.radians(v)
    return (Matrix.Rotation(deg("y"), 3, "Y")
            @ Matrix.Rotation(deg("x"), 3, "X")
            @ Matrix.Rotation(deg("z"), 3, "Z"))


def _mesh_objects():
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def _three_box(objects, fix):
    """Box3.setFromObject(precise=false): every object's LOCAL bound box, its 8
    corners through the world matrix (then into glTF axes and through the fix),
    united. Deliberately NOT the vertex hull — this is what the client measures."""
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for obj in objects:
        for corner in obj.bound_box:
            p = fix @ _gltf(obj.matrix_world @ Vector(corner))
            for k in range(3):
                lo[k] = min(lo[k], p[k])
                hi[k] = max(hi[k], p[k])
    return lo, hi


def _triangles(objects, fix):
    """All evaluated triangles in the fixed glTF frame, as (verts, tris)."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    verts = []
    tris = []
    for obj in objects:
        ev = obj.evaluated_get(depsgraph)
        mesh = ev.to_mesh()
        try:
            mesh.calc_loop_triangles()
            base = len(verts)
            mw = ev.matrix_world
            for v in mesh.vertices:
                verts.append(fix @ _gltf(mw @ v.co))
            for t in mesh.loop_triangles:
                tris.append([base + i for i in t.vertices])
        finally:
            ev.to_mesh_clear()
    return verts, tris


def _hits_below(bvh, x, z, top):
    """Every hit of a downward ray from (x, top, z): [(y, faces_up)], ascending y."""
    out = []
    origin = Vector((x, top, z))
    direction = Vector((0.0, -1.0, 0.0))
    while True:
        loc, normal, _index, _dist = bvh.ray_cast(origin, direction)
        if loc is None:
            break
        out.append((loc.y, normal.y > 0.0))
        origin = Vector((x, loc.y - RAY_EPS, z))
    out.sort(key=lambda h: h[0])
    return out


def _walk_height(hits, clearance):
    """The cell rule of the docstring. None when nothing faces up."""
    for idx, (y, up) in enumerate(hits):
        if not up:
            continue
        above = hits[idx + 1][0] if idx + 1 < len(hits) else math.inf
        if above - y >= clearance:
            return y
    return None


def heightgrid(args):
    params = args.get("params") or {}
    rot = params.get("rotation") or {}
    step = float(params.get("step") or 0.25)
    clearance = float(params.get("clearance") or 1.2)
    max_cells = int(params.get("max_cells") or 40000)

    _common.reset_scene()
    _common.import_model(args["inputs"]["model"])
    objects = _mesh_objects()
    if not objects:
        raise RuntimeError("no mesh objects")

    fix = _fix_matrix(rot, snap=False)
    lo, hi = _three_box(objects, fix)
    slo, shi = _three_box(objects, _fix_matrix(rot, snap=True))
    verts, tris = _triangles(objects, fix)
    bvh = BVHTree.FromPolygons(verts, tris)

    width = hi[0] - lo[0]
    depth = hi[2] - lo[2]
    while True:
        cols = int(math.ceil(width / step)) + 1
        rows = int(math.ceil(depth / step)) + 1
        if cols * rows <= max_cells:
            break
        step *= 2.0

    top = hi[1] + 1.0
    values = []
    hits = 0
    for j in range(rows):
        z = min(max(lo[2] + j * step, lo[2] + EDGE_NUDGE), hi[2] - EDGE_NUDGE)
        for i in range(cols):
            x = min(max(lo[0] + i * step, lo[0] + EDGE_NUDGE), hi[0] - EDGE_NUDGE)
            y = _walk_height(_hits_below(bvh, x, z, top), clearance)
            if y is None:
                values.append(None)
            else:
                values.append(int(round((y - lo[1]) * 100.0)))
                hits += 1

    data = {
        "step": step,
        "origin": [round(lo[0], 5), round(lo[2], 5)],
        "cols": cols,
        "rows": rows,
        "values": values,
        "box_min": [round(v, 5) for v in lo],
        "box_max": [round(v, 5) for v in hi],
        "extent_snapped": [round(shi[k] - slo[k], 5) for k in range(3)],
        "hits": hits,
    }
    return data, {}


_common.main(heightgrid)
