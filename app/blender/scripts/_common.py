"""Shared boilerplate for the bpy scripts: read the job, write the result.

These scripts run inside Blender's OWN Python — the application's venv is not
importable here, so this module may only use the standard library and bpy.
Blender's BUNDLED numpy is allowed too (ruling 2026-08-27, spec-picture-props
§ 2): pixel access over ``image.pixels`` is hopeless in pure Python, and the
bundle ships numpy with every Blender release.

``app_root_on_path()`` puts the repository root on ``sys.path`` so a script
can import a module of the application — ONLY modules that are stdlib-only
by contract (``app.core.picture_areas`` is the one such module today). Any
other ``app.*`` import would drag the venv's dependencies in and fail on the
first ``import numpy``-style line that resolves against the wrong interpreter.
"""
import json
import sys
import traceback
from pathlib import Path

# <repo>/app/blender/scripts/_common.py -> <repo>
_APP_ROOT = Path(__file__).resolve().parents[3]


def app_root_on_path():
    """Makes ``app.core.<stdlib-only module>`` importable; idempotent.

    The root goes to the END of the path, not the front: nothing of the
    repository may shadow a stdlib module Blender's add-ons import while they
    load (the same reason the scripts directory itself is only on the path
    for the sibling import and comes straight back off it).
    """
    root = str(_APP_ROOT)
    if root not in sys.path:
        sys.path.append(root)
    return _APP_ROOT

# Blender's importers are addons; their operators live under bpy.ops.
IMPORTERS = {
    ".glb": "gltf", ".gltf": "gltf", ".fbx": "fbx", ".obj": "obj",
    ".ply": "ply", ".stl": "stl",
}


def read_args():
    """The job description the runner wrote (everything after ``--``)."""
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        raise SystemExit("no args file given")
    return json.loads(Path(argv[0]).read_text(encoding="utf-8"))


def write_result(args, ok, data=None, outputs=None, error=""):
    Path(args["result"]).write_text(json.dumps({
        "ok": bool(ok), "error": str(error),
        "data": data or {}, "outputs": outputs or {},
    }, ensure_ascii=False, indent=1), encoding="utf-8")


#: A194: the run's progress file (``args["progress"]``, set by ``main``) and the stage clock.
_PROGRESS = {"file": None, "stage": None, "t0": None, "last": 0.0}


def progress(stage, i=None, n=None, label=None):
    """Report what the run does now — ``stage`` (a short key the server labels, e.g. ``"bones"``), optionally
    ``i`` of ``n`` — into the progress file the server shows live (A194). Throttled inside a stage; a write that
    fails is ignored: progress is never worth a failed run. No-op without a progress file."""
    import time
    path = _PROGRESS["file"]
    if not path:
        return
    now = time.time()
    if _PROGRESS["stage"] != stage:
        _PROGRESS["stage"], _PROGRESS["t0"] = stage, now
    elif i is not None and n is not None and 0 < i < n and now - _PROGRESS["last"] < 0.25:
        return
    _PROGRESS["last"] = now
    try:
        tmp = Path(str(path) + ".tmp")
        tmp.write_text(json.dumps({"stage": stage, "label": label, "i": i, "n": n,
                                   "t0": _PROGRESS["t0"], "t": now}), encoding="utf-8")
        tmp.replace(path)
    except Exception:  # noqa: BLE001
        pass


def main(fn):
    """Runs ``fn(args)`` and turns anything it raises into a failed result.

    A crashing script that wrote no result is indistinguishable from a
    Blender crash on the runner side; writing the traceback here makes the
    cause visible in the caller's log instead of only in Blender's stdout.
    """
    args = None
    try:
        args = read_args()
        _PROGRESS["file"] = args.get("progress") or None
        data, outputs = fn(args)
        write_result(args, True, data=data, outputs=outputs)
    except BaseException as e:                    # noqa: BLE001 - last resort
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        if args:
            write_result(args, False, error=f"{type(e).__name__}: {e}")
        raise SystemExit(1)


def import_model(path, *, gltf_merge_vertices=False):
    """Loads a model into the EMPTY current scene, by extension.

    ``gltf_merge_vertices`` (glTF only): weld the per-UV vertex split glTF
    stores (every UV seam is a cut in the file) back into one surface. A
    static mesh that is decimated afterwards needs it — split at its seams,
    each UV island shrinks on its own and the surface tears apart; skinned
    character imports keep the default.

    glTF: the importer keeps its DEFAULT bone heuristic (BLENDER) on purpose —
    it is the one that PRESERVES the source's joint orientations through an
    import/export round trip. TEMPERANCE looked attractive because it creates
    no display objects, but it RE-DERIVES every bone frame from the child
    positions: positions and bind stay consistent (rest pose looks right),
    while the exported joint rotations land in a different convention — and
    the clients apply the shared Mixamo clips INTO those local frames, so a
    rig whose source frames do not match the heuristic animates broken
    (2026-08-06 incident: 57 of 83 store files, hips pitched ~90-180°).
    The one real problem of the BLENDER heuristic — the Icosphere display
    object that falsified measurements — is solved by DELETING the bone
    custom shapes after import instead.
    """
    progress("loading")
    import bpy
    ext = Path(path).suffix.lower()
    kind = IMPORTERS.get(ext)
    if not kind:
        raise ValueError(f"unsupported model format: {ext}")
    if kind == "gltf":
        if gltf_merge_vertices:
            bpy.ops.import_scene.gltf(filepath=str(path), merge_vertices=True)
        else:
            bpy.ops.import_scene.gltf(filepath=str(path))
        _drop_bone_shape_objects(bpy)
    elif kind == "fbx":
        # global_scale stays 1.0 on purpose: many rigs (Mixamo among them) are
        # authored in centimetres, and silently rescaling on import would hide
        # exactly the discrepancy this pipeline exists to measure.
        bpy.ops.import_scene.fbx(filepath=str(path), global_scale=1.0)
    elif kind == "obj":
        bpy.ops.wm.obj_import(filepath=str(path))
    elif kind == "ply":
        bpy.ops.wm.ply_import(filepath=str(path))
    elif kind == "stl":
        bpy.ops.wm.stl_import(filepath=str(path))


def _drop_bone_shape_objects(bpy):
    """Removes objects that exist only as bone display shapes.

    They are visual aids for a human in the viewport; in a headless pipeline
    they only falsify counts and bounds."""
    shapes = set()
    for obj in list(bpy.context.scene.objects):
        if obj.type != "ARMATURE" or obj.pose is None:
            continue
        for pb in obj.pose.bones:
            if pb.custom_shape is not None:
                shapes.add(pb.custom_shape.name)
    for obj in list(bpy.context.scene.objects):
        if obj.name in shapes:
            bpy.data.objects.remove(obj, do_unlink=True)


def reset_scene():
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)


def enclosed(tree, point, normal):
    """Whether a surface point is an INNER wall: every ray of a fan around its
    normal hits the mesh again (``tree`` a mathutils BVHTree in the point's space).

    Some meshers (UniForge) deliver double-walled bodies: the outer skin plus a
    wall a few mm below it whose normals face the hollow interior. Measured on
    such a body: inner wall 9 of 9 rays hit, outer skin at the groin 0-4 of 9.
    A deep crease of outer skin can pass as enclosed too."""
    import math
    from mathutils import Vector
    n = normal.normalized()
    a = Vector((1, 0, 0)) if abs(n.x) < .9 else Vector((0, 1, 0))
    u = n.cross(a).normalized()
    w = n.cross(u)
    origin = point + n * 1e-5
    if tree.ray_cast(origin, n)[0] is None:
        return False
    for angle in (45, 70):
        c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        for t in (u, -u, w, -w):
            if tree.ray_cast(origin, (n * c + t * s).normalized())[0] is None:
                return False
    return True


def body_meshes_first(path):
    """Keep the body mesh first without changing accessors or binary buffers."""
    import json
    import struct
    blob = path.read_bytes()
    size = struct.unpack_from('<I', blob, 12)[0]
    doc = json.loads(blob[20:20 + size])
    marked = {n['mesh'] for n in doc.get('nodes', [])
              if 'mesh' in n and 'attached_part' in n.get('extras', {})}
    materials = doc.get('materials', [])
    for index, mesh in enumerate(doc.get('meshes', [])):
        primitives = mesh.get('primitives', [])
        if primitives and all('material' in primitive and 'attached_part' in
                              (materials[primitive['material']].get('extras') or {})
                              for primitive in primitives):
            marked.add(index)
    if not marked:
        return
    order = sorted(range(len(doc.get('meshes', []))), key=lambda i: i in marked)
    remap = {old: new for new, old in enumerate(order)}
    doc['meshes'] = [doc['meshes'][i] for i in order]
    for node in doc.get('nodes', []):
        if 'mesh' in node:
            node['mesh'] = remap[node['mesh']]
    raw = json.dumps(doc, separators=(',', ':')).encode()
    raw += b' ' * (-len(raw) % 4)
    rest = blob[20 + size:]
    path.write_bytes(struct.pack('<4sII', b'glTF', 2, 20 + len(raw) + len(rest))
                     + struct.pack('<II', len(raw), 0x4E4F534A) + raw + rest)


MOUTH_TEETH_MATERIAL = 'mouth_teeth'


def keep_mouth_teeth_colours(path):
    """The post-export step of every script that re-exports a rigged body (Ruling A206): Blender writes the body's
    colour attribute — which only the built teeth use — into every primitive of the body mesh again, so the skin and
    the tongue would start to carry vertex colours. A no-op for a file without teeth."""
    vertex_colors_only_on(path, {MOUTH_TEETH_MATERIAL})


def vertex_colors_only_on(path, material_names):
    """Keep ``COLOR_0`` only on the primitives whose material is one of ``material_names``, within the meshes that
    have such a primitive (another mesh's own vertex colours are left alone): Blender writes a mesh's colour
    attribute into every primitive of it, and a body skin must not start to carry vertex colours because one built
    part uses them. The accessors and buffer views nothing uses any more are dropped and the binary chunk is
    repacked (8-byte aligned views)."""
    import json
    import struct
    blob = path.read_bytes()
    size = struct.unpack_from('<I', blob, 12)[0]
    doc = json.loads(blob[20:20 + size])
    rest = blob[20 + size:]
    bin_len = struct.unpack_from('<I', rest, 0)[0]
    binary = rest[8:8 + bin_len]
    materials = doc.get('materials', [])
    changed = False
    def name_of(prim):
        return materials[prim['material']].get('name') if 'material' in prim else None

    for mesh in doc.get('meshes', []):
        if not any(name_of(prim) in material_names for prim in mesh.get('primitives', [])):
            continue
        for prim in mesh.get('primitives', []):
            name = name_of(prim)
            if 'COLOR_0' in prim.get('attributes', {}) and name not in material_names:
                del prim['attributes']['COLOR_0']
                changed = True
    if not changed:
        return
    used = set()
    for mesh in doc.get('meshes', []):
        for prim in mesh.get('primitives', []):
            used.update(prim.get('attributes', {}).values())
            if 'indices' in prim:
                used.add(prim['indices'])
            for target in prim.get('targets') or []:
                used.update(target.values())
    for skin in doc.get('skins', []):
        if 'inverseBindMatrices' in skin:
            used.add(skin['inverseBindMatrices'])
    for anim in doc.get('animations', []):
        for sampler in anim.get('samplers', []):
            used.update((sampler['input'], sampler['output']))
    order = sorted(used)
    acc_map = {old: new for new, old in enumerate(order)}
    accessors = [doc['accessors'][i] for i in order]
    for mesh in doc.get('meshes', []):
        for prim in mesh.get('primitives', []):
            prim['attributes'] = {k: acc_map[v] for k, v in prim['attributes'].items()}
            if 'indices' in prim:
                prim['indices'] = acc_map[prim['indices']]
            if prim.get('targets'):
                prim['targets'] = [{k: acc_map[v] for k, v in t.items()} for t in prim['targets']]
    for skin in doc.get('skins', []):
        if 'inverseBindMatrices' in skin:
            skin['inverseBindMatrices'] = acc_map[skin['inverseBindMatrices']]
    for anim in doc.get('animations', []):
        for sampler in anim.get('samplers', []):
            sampler['input'], sampler['output'] = acc_map[sampler['input']], acc_map[sampler['output']]
    doc['accessors'] = accessors
    views = set()
    for acc in accessors:
        if 'bufferView' in acc:
            views.add(acc['bufferView'])
        sparse = acc.get('sparse')
        if sparse:
            views.update((sparse['indices']['bufferView'], sparse['values']['bufferView']))
    for image in doc.get('images', []):
        if 'bufferView' in image:
            views.add(image['bufferView'])
    view_order = sorted(views)
    view_map = {old: new for new, old in enumerate(view_order)}
    out = bytearray()
    new_views = []
    for old in view_order:
        view = dict(doc['bufferViews'][old])
        start = view.get('byteOffset', 0)
        chunk = binary[start:start + view['byteLength']]
        out += b'\0' * (-len(out) % 8)
        view['byteOffset'] = len(out)
        out += chunk
        new_views.append(view)
    doc['bufferViews'] = new_views
    for acc in accessors:
        if 'bufferView' in acc:
            acc['bufferView'] = view_map[acc['bufferView']]
        sparse = acc.get('sparse')
        if sparse:
            sparse['indices']['bufferView'] = view_map[sparse['indices']['bufferView']]
            sparse['values']['bufferView'] = view_map[sparse['values']['bufferView']]
    for image in doc.get('images', []):
        if 'bufferView' in image:
            image['bufferView'] = view_map[image['bufferView']]
    out += b'\0' * (-len(out) % 4)
    doc['buffers'][0]['byteLength'] = len(out)
    raw = json.dumps(doc, separators=(',', ':')).encode()
    raw += b' ' * (-len(raw) % 4)
    body = struct.pack('<II', len(raw), 0x4E4F534A) + raw + struct.pack('<II', len(out), 0x004E4942) + bytes(out)
    path.write_bytes(struct.pack('<4sII', b'glTF', 2, 12 + len(body)) + body)
