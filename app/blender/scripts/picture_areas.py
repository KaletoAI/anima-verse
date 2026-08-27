"""Picture areas of a prop mesh — find the key-coloured panels, split them off
as slot materials with planar UVs, or do the same for a hand-picked face list
(spec-picture-props.md § 2; the maths lives in ``app/core/picture_areas.py``,
this file is I/O + bpy only).

A frame prop from img2mesh arrives with ONE anonymous atlas material. The
render it was baked from was asked for a chroma-key panel (green = picture,
magenta = glass), so the panel's colour sits in the atlas texture — and that is
the only marker there is. This script reads the atlas through the faces' UVs,
groups the key-coloured triangles into patches, fits a plane to each, writes
planar 0..1 UVs onto exactly those faces and moves them into a material
``slot_<kind>_<k>`` whose base colour is the SAME atlas image — so an empty
panel still shows its key colour ("a picture is missing here").

Params (``args["params"]``)::

    mode        "auto"   — dissolve every existing slot_<kind>_<k> area (faces
                           back to their origin material, atlas UVs restored)
                           and detect anew for every kind in ``kinds``
                "manual" — ``faces`` (flat triangle indices, R1) become ONE new
                           area of ``kind``; every other area stays; a listed
                           face that belonged to another area moves
                "delete" — the area ``area`` is dissolved, nothing else changes
    kinds       ["picture", "glass"] — the kinds to detect in mode auto
    faces       [int] — mode manual
    kind        "picture" | "glass" — mode manual
    area        "<area id>" — mode delete
    min_area_m2 float, min_faces int — the size filter of mode auto
    origins     {"<area id>": "<material name>"} — where dissolved faces go
                (the server keeps it from the run that created the area);
                without an entry the mesh's FIRST non-slot material takes them

R1 — FACE INDEX CONVENTION (mirrored by the admin client): the flat triangle
index runs over the mesh objects sorted by object NAME, triangles per mesh in
stored polygon order after ``calc_loop_triangles()``. An imported GLB is
already triangulated; a mesh that is not is triangulated first (bmesh), so
polygon order and triangle order are the same thing. ``mesh_layout`` in the
result names that order: ``[{name, tri_count}, …]``.

R2 — COORDINATES: the maths module works in glTF y-up model space (three.js
in both renderers). Blender is z-up and its importer converts, so every
vertex handed to the module and every normal/centroid/edge reported goes
through ``(x, y, z)_gltf = (x, z, -y)_blender`` after ``matrix_world``.
Planar UVs are written per LOOP of the area faces only; the glTF exporter
flips V as for every other UV — nothing is pre-flipped here.

THE ATLAS BACKUP LAYER: overwriting a face's UVs loses its atlas UVs, and a
deleted area (or a re-run) has to put them back. So the first split copies
the atlas UV layer into a second UV layer (exported as TEXCOORD_1, ignored by
the renderers) — ALWAYS the LAST layer of the mesh. glTF carries no UV-layer
names, so on re-import the marker is the presence of slot_<kind>_<k>
materials: a mesh that has them and two or more layers keeps its backup in
the last one. When the last area is dissolved the backup is removed again
(layer 0 is the atlas once more), so a mesh does not grow a layer per cycle.

Result ``data``::

    {"areas": [{id, kind, faces: n, size_m: [w, h], normal, centroid,
                edges: [[[x,y,z],[x,y,z]], …], origin: "<material>"}, …],
     "mesh_layout": [{name, tri_count}, …],
     "changed": bool}

Output ``model`` (a GLB, textures embedded) only when the mesh changed.
Blender-side Python only: bpy, bmesh, mathutils, the bundled numpy, stdlib —
plus the stdlib-only ``app.core.picture_areas`` via ``_common``.
"""
import math
import re
import sys
from pathlib import Path

# The scripts directory is on the search path for the sibling import ONLY, and
# comes straight back off it (same reason as in measure.py).
_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
sys.path.remove(_SCRIPTS_DIR)
_common.app_root_on_path()
from app.core import picture_areas as pa                      # noqa: E402

import bmesh                                                  # noqa: E402
import bpy                                                    # noqa: E402
import numpy as np                                            # noqa: E402

SLOT_PREFIX = "slot_"
ATLAS_LAYER_NAME = "atlas_uv"
_AREA_RE = re.compile(r"^slot_(" + "|".join(pa.KINDS) + r")_(\d+)$")
ROUND = 5


def _gltf(v):
    """Blender world (Z up) -> glTF axes (Y up): the importer's own conversion, undone."""
    return (float(v.x), float(v.z), float(-v.y))


def _r(seq):
    return [round(float(c), ROUND) + 0.0 for c in seq]


def _area_name(name):
    """``slot_picture_3`` -> ("picture", 3); anything else -> None."""
    m = _AREA_RE.match(str(name or ""))
    return (m.group(1), int(m.group(2))) if m else None


def _mesh_objects():
    return sorted((o for o in bpy.context.scene.objects if o.type == "MESH"),
                  key=lambda o: o.name)


def _triangulate(obj):
    """R1: polygon order == triangle order. Only touches a mesh that needs it."""
    me = obj.data
    if all(len(p.vertices) == 3 for p in me.polygons):
        return
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    me.update()


# ---------------------------------------------------------------------------
# the model as the maths module sees it
# ---------------------------------------------------------------------------
class Model:
    """Global vertex/face lists in glTF space over all mesh objects (R1 order),
    plus the map from a flat face index to its (object, polygon)."""

    def __init__(self, objects):
        self.objects = objects
        self.vertices = []          # global, glTF space
        self.faces = []             # global vertex indices
        self.poly = []              # flat index -> (obj index, polygon index)
        self.base = []              # vertex offset per object
        self.layout = []
        self.had_areas = []         # per object: slot materials present on import
        for oi, obj in enumerate(objects):
            _triangulate(obj)
            me = obj.data
            me.calc_loop_triangles()
            base = len(self.vertices)
            self.base.append(base)
            mw = obj.matrix_world
            for v in me.vertices:
                self.vertices.append(_gltf(mw @ v.co))
            for t in me.loop_triangles:
                self.faces.append(tuple(base + i for i in t.vertices))
                self.poly.append((oi, t.polygon_index))
            self.layout.append({"name": obj.name, "tri_count": len(me.loop_triangles)})
            self.had_areas.append(any(_area_name(m.name) for m in me.materials if m))

    def atlas_uvs(self):
        """Per-vertex atlas UVs (Blender convention, v bottom-up — the same
        orientation as ``image.pixels``), read off the backup layer where one
        exists, else off layer 0. Imported glTF vertices are split wherever
        loops disagree, so one UV per vertex is exact for them."""
        uvs = [(0.0, 0.0)] * len(self.vertices)
        for oi, obj in enumerate(self.objects):
            me = obj.data
            layer = self._backup_layer(oi) or (me.uv_layers[0] if me.uv_layers else None)
            if layer is None:
                continue
            base = self.base[oi]
            for loop in me.loops:
                uv = layer.data[loop.index].uv
                uvs[base + loop.vertex_index] = (float(uv[0]), float(uv[1]))
        return uvs

    def _backup_layer(self, oi):
        me = self.objects[oi].data
        if self.had_areas[oi] and len(me.uv_layers) >= 2:
            return me.uv_layers[len(me.uv_layers) - 1]
        return None

    def ensure_backup(self, oi):
        """The atlas backup layer of one mesh, created (as the LAST layer, a
        copy of layer 0) on the first split of that mesh."""
        layer = self._backup_layer(oi)
        if layer is not None:
            return layer
        me = self.objects[oi].data
        if not me.uv_layers:
            raise ValueError(f"mesh {self.objects[oi].name!r} has no UV layer")
        me.uv_layers.active_index = 0
        buf = np.empty(len(me.loops) * 2, dtype=np.float32)
        me.uv_layers[0].data.foreach_get("uv", buf)
        me.uv_layers.new(name=ATLAS_LAYER_NAME, do_init=False)
        me.uv_layers[len(me.uv_layers) - 1].data.foreach_set("uv", buf)
        self.had_areas[oi] = True
        return me.uv_layers[len(me.uv_layers) - 1]

    def drop_backup_if_unused(self, oi):
        """No area left on this mesh -> layer 0 IS the atlas again, the copy
        goes (or the mesh would grow a layer per split/delete cycle)."""
        me = self.objects[oi].data
        if any(_area_name(m.name) for m in me.materials if m):
            return
        layer = self._backup_layer(oi)
        if layer is not None and len(me.uv_layers) >= 2:
            me.uv_layers.remove(layer)
        self.had_areas[oi] = False


# ---------------------------------------------------------------------------
# materials + images
# ---------------------------------------------------------------------------
def _base_image(mat):
    """The image feeding the Principled base colour (through a Mix node if the
    importer added one), else the first image texture, else None."""
    if mat is None or not mat.use_nodes or mat.node_tree is None:
        return None
    nodes = mat.node_tree.nodes
    for n in nodes:
        if n.type != "BSDF_PRINCIPLED":
            continue
        inp = n.inputs.get("Base Color")
        if not inp or not inp.is_linked:
            continue
        src, seen = inp.links[0].from_node, set()
        while src is not None and src.type != "TEX_IMAGE" and src.name not in seen:
            seen.add(src.name)
            links = [ln for i in src.inputs for ln in i.links]
            src = links[0].from_node if links else None
        if src is not None and src.type == "TEX_IMAGE" and src.image is not None:
            return src.image
    for n in nodes:
        if n.type == "TEX_IMAGE" and n.image is not None:
            return n.image
    return None


def _sampler(image):
    """``sample(u, v) -> (r, g, b)`` floats 0..1, nearest texel, wrapping —
    exactly the 3-tuple ``picture_areas.classify_faces`` unpacks. ``pixels``
    are the stored values (no colour transform), rows bottom-up like Blender
    UVs, so a Blender (u, v) indexes the buffer directly."""
    w, h = int(image.size[0]), int(image.size[1])
    n = int(image.channels)
    if w <= 0 or h <= 0 or n <= 0:
        return None
    buf = np.empty(w * h * n, dtype=np.float32)
    image.pixels.foreach_get(buf)
    px = buf.reshape(h, w, n)

    def sample(u, v):
        if not (math.isfinite(u) and math.isfinite(v)):
            return (0.0, 0.0, 0.0)
        x = int(math.floor(u * w)) % w
        y = int(math.floor(v * h)) % h
        p = px[y, x]
        if n >= 3:
            return (float(p[0]), float(p[1]), float(p[2]))
        return (float(p[0]), float(p[0]), float(p[0]))
    return sample


def _slot_material(name, image):
    """``slot_<kind>_<k>`` with the atlas as base colour — an empty panel
    keeps showing its key colour. Rebuilt from scratch even when a material
    of that name survived the import, so it never carries stale nodes."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.name = name
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    if image is not None:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = image
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def _material_index(obj, mat):
    for i, m in enumerate(obj.data.materials):
        if m is not None and m.name == mat.name:
            return i
    obj.data.materials.append(mat)
    return len(obj.data.materials) - 1


def _origin_index(obj, origin_name):
    """Where dissolved faces go: the named origin material when the mesh has
    it, else the first material that is not a slot area."""
    mats = obj.data.materials
    if origin_name:
        for i, m in enumerate(mats):
            if m is not None and m.name == origin_name:
                return i
    for i, m in enumerate(mats):
        if m is None or not _area_name(m.name):
            return i
    return 0


def _drop_empty_area_materials(obj):
    """Removes slot-area material slots no polygon uses any more and remaps
    the polygon indices — the exporter must not see a phantom material."""
    me = obj.data
    used = {p.material_index for p in me.polygons}
    mats = list(me.materials)
    keep = [i for i, m in enumerate(mats)
            if i in used or m is None or not _area_name(m.name)]
    if len(keep) == len(mats):
        return
    remap = {old: new for new, old in enumerate(keep)}
    idx = [remap.get(p.material_index, 0) for p in me.polygons]
    me.materials.clear()
    for i in keep:
        me.materials.append(mats[i])
    for p, i in zip(me.polygons, idx):
        p.material_index = i


# ---------------------------------------------------------------------------
# areas on the mesh
# ---------------------------------------------------------------------------
def _existing_areas(model):
    """``{area_id: {kind, k, faces: [flat …]}}`` read off the material names
    and the polygon assignment."""
    out = {}
    for flat, (oi, pi) in enumerate(model.poly):
        me = model.objects[oi].data
        mi = me.polygons[pi].material_index
        mat = me.materials[mi] if 0 <= mi < len(me.materials) else None
        parsed = _area_name(mat.name) if mat is not None else None
        if not parsed:
            continue
        kind, k = parsed
        entry = out.setdefault(f"{kind}_{k}", {"kind": kind, "k": k, "faces": []})
        entry["faces"].append(flat)
    return out


def _dissolve(model, area, origin_name):
    """Faces of ``area`` back to the origin material, atlas UVs restored."""
    for flat in area["faces"]:
        oi, pi = model.poly[flat]
        obj = model.objects[oi]
        me = obj.data
        poly = me.polygons[pi]
        poly.material_index = _origin_index(obj, origin_name)
        backup = model._backup_layer(oi)
        if backup is not None and me.uv_layers:
            layer = me.uv_layers[0]
            for li in poly.loop_indices:
                layer.data[li].uv = backup.data[li].uv


def _assign(model, area_id, kind, faces, uvs, image):
    """Faces -> the area's material, planar UVs onto their loops only.
    Returns the origin material name the faces had (majority)."""
    counts = {}
    for flat in faces:
        oi, pi = model.poly[flat]
        me = model.objects[oi].data
        mi = me.polygons[pi].material_index
        mat = me.materials[mi] if 0 <= mi < len(me.materials) else None
        if mat is not None and not _area_name(mat.name):
            counts[mat.name] = counts.get(mat.name, 0) + 1
    origin = max(counts, key=counts.get) if counts else ""
    mat = _slot_material(f"{SLOT_PREFIX}{area_id}", image)
    for flat in faces:
        oi, pi = model.poly[flat]
        obj = model.objects[oi]
        me = obj.data
        model.ensure_backup(oi)
        layer = me.uv_layers[0]
        poly = me.polygons[pi]
        poly.material_index = _material_index(obj, mat)
        base = model.base[oi]
        for li in poly.loop_indices:
            uv = uvs.get(base + me.loops[li].vertex_index)
            if uv is not None:
                layer.data[li].uv = (float(uv[0]), float(uv[1]))
    return origin


def _next_k(kind, existing):
    used = {e["k"] for e in existing.values() if e["kind"] == kind}
    k = 1
    while k in used:
        k += 1
    return k


def _fit(model, faces):
    """Plane, frame, planar UVs and size of one face set (any mode)."""
    verts = sorted({v for n in faces for v in model.faces[n]})
    points = [model.vertices[v] for v in verts]
    centroid, normal = pa.fit_plane(points)
    frame = pa.planar_frame(normal)
    flat, size_m = pa.planar_uvs(points, centroid, frame)
    return {"centroid": centroid, "normal": normal, "size_m": size_m,
            "uvs": {v: flat[i] for i, v in enumerate(verts)}}


def _material_groups(model):
    """(object index, material index, image) for every non-area material
    that carries a base-colour image — the atlases the detection reads."""
    out = []
    for oi, obj in enumerate(model.objects):
        for mi, mat in enumerate(obj.data.materials):
            if mat is None or _area_name(mat.name):
                continue
            image = _base_image(mat)
            if image is not None:
                out.append((oi, mi, image))
    return out


def _report(model, existing, origins):
    areas = []
    for area_id, entry in existing.items():
        faces = entry["faces"]
        fit = _fit(model, faces)
        edges = pa.area_edges(model.vertices, model.faces, faces)
        areas.append({
            "id": area_id,
            "kind": entry["kind"],
            "faces": len(faces),
            "size_m": _r(fit["size_m"]),
            "normal": _r(fit["normal"]),
            "centroid": _r(fit["centroid"]),
            "edges": [[_r(a), _r(b)] for a, b in edges],
            "origin": str(origins.get(area_id) or ""),
        })
    areas.sort(key=lambda a: (pa.KINDS.index(a["kind"]), int(a["id"].rsplit("_", 1)[1])))
    return areas


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------
def picture_areas(args):
    params = args.get("params") or {}
    mode = str(params.get("mode") or "auto")
    kinds = [k for k in (params.get("kinds") or list(pa.KINDS)) if k in pa.KINDS]
    min_area = float(params.get("min_area_m2") or 0.02)
    min_faces = int(params.get("min_faces") or 12)
    origins = {str(k): str(v) for k, v in (params.get("origins") or {}).items()}

    _common.reset_scene()
    _common.import_model(args["inputs"]["model"])
    objects = _mesh_objects()
    if not objects:
        raise RuntimeError("no mesh objects")
    model = Model(objects)
    existing = _existing_areas(model)
    changed = False

    if mode == "auto":
        for area_id, entry in existing.items():
            _dissolve(model, entry, origins.get(area_id, ""))
            changed = True
        existing = {}
        atlas_uvs = model.atlas_uvs()
        for oi, mi, image in _material_groups(model):
            sample = _sampler(image)
            if sample is None:
                continue
            me = model.objects[oi].data
            group = [flat for flat, (o, pi) in enumerate(model.poly)
                     if o == oi and me.polygons[pi].material_index == mi]
            sub_faces = [model.faces[n] for n in group]
            for kind in kinds:
                found = pa.detect_areas(model.vertices, sub_faces, atlas_uvs, sample,
                                        kind, min_area_m2=min_area, min_faces=min_faces)
                for area in found:
                    faces = [group[i] for i in area["faces"]]
                    k = _next_k(kind, existing)
                    area_id = f"{kind}_{k}"
                    origin = _assign(model, area_id, kind, faces, area["uvs"], image)
                    existing[area_id] = {"kind": kind, "k": k, "faces": faces}
                    origins[area_id] = origin
                    changed = True

    elif mode == "manual":
        kind = str(params.get("kind") or "picture")
        if kind not in pa.KINDS:
            raise ValueError(f"unknown area kind {kind!r}")
        faces = sorted({int(f) for f in (params.get("faces") or [])})
        bad = [f for f in faces if f < 0 or f >= len(model.faces)]
        if not faces or bad:
            raise ValueError(f"faces must be flat triangle indices below "
                             f"{len(model.faces)} (got {len(faces)}, bad: {bad[:5]})")
        listed = set(faces)
        # A listed face leaves the area it was in; an area left empty goes.
        for area_id, entry in list(existing.items()):
            taken = [f for f in entry["faces"] if f in listed]
            if taken:
                _dissolve(model, {"faces": taken}, origins.get(area_id, ""))
                entry["faces"] = [f for f in entry["faces"] if f not in listed]
                if not entry["faces"]:
                    existing.pop(area_id)
        fit = _fit(model, faces)
        k = _next_k(kind, existing)
        area_id = f"{kind}_{k}"
        # The atlas of the faces' current material — the MAJORITY material
        # among those that carry an image, so a pick that grazes a second
        # material at its edge still gets the panel's own atlas.
        votes = {}
        images = {}
        for flat in faces:
            oi, pi = model.poly[flat]
            me = model.objects[oi].data
            mi = me.polygons[pi].material_index
            mat = me.materials[mi] if 0 <= mi < len(me.materials) else None
            if mat is None or mat.name in images and images[mat.name] is None:
                continue
            if mat.name not in images:
                images[mat.name] = _base_image(mat)
            if images[mat.name] is not None:
                votes[mat.name] = votes.get(mat.name, 0) + 1
        image = images[max(votes, key=votes.get)] if votes else None
        origin = _assign(model, area_id, kind, faces, fit["uvs"], image)
        existing[area_id] = {"kind": kind, "k": k, "faces": faces}
        origins[area_id] = origin
        changed = True

    elif mode == "delete":
        area_id = str(params.get("area") or "")
        entry = existing.pop(area_id, None)
        if entry is None:
            raise ValueError(f"no area {area_id!r} on the mesh "
                             f"(has: {', '.join(existing) or 'none'})")
        _dissolve(model, entry, origins.get(area_id, ""))
        changed = True

    else:
        raise ValueError(f"unknown mode {mode!r} (auto | manual | delete)")

    for oi, obj in enumerate(model.objects):
        _drop_empty_area_materials(obj)
        model.drop_backup_if_unused(oi)
        obj.data.update()

    data = {"areas": _report(model, existing, origins),
            "mesh_layout": model.layout, "changed": changed}
    if not changed:
        return data, {}
    out = Path(args["out_dir"]) / "model.glb"
    bpy.ops.export_scene.gltf(filepath=str(out), export_format="GLB")
    if not out.is_file():
        raise RuntimeError(f"export wrote no file: {out}")
    return data, {"model": str(out)}


_common.main(picture_areas)
