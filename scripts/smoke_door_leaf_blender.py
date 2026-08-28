#!/usr/bin/env python3
"""Blender integration run for the DOOR LEAF split (spec-picture-props.md § 6,
decision D7, plan task 6): the leaf of a door mesh becomes its own glTF node
``leaf``, the rest the node ``frame``, the model FILE's sidecar carries
``leaf_bbox`` (spec-bild-props-v2.md E1), and a delete joins the leaf back.

Usage:  ./.venv/bin/python scripts/smoke_door_leaf_blender.py

Needs Blender (``refine.unavailable_reason()`` empty); otherwise prints
"skipped: Blender unavailable (<reason>)" and exits 0. Throw-away storage in
/tmp, no world, no DB, no server. Every expected number below is derived BY
HAND from the fixture and the spec, never recorded from a run.

THE FIXTURE (glTF y-up, written with the stdlib), ``door_glb()`` — the very
door of ``scripts/smoke_picture_areas.py`` fixture F, as ONE mesh with one
grey-atlas material: five closed boxes, 8 shared vertices and 12 outward
triangles each, the four frame bars first, the plate last:

    left bar    x 0.0..0.1   y 0.0..2.2   z -0.05..0.02    faces  0..11
    right bar   x 0.9..1.0   y 0.0..2.2   z -0.05..0.02    faces 12..23
    bottom bar  x 0.1..0.9   y 0.0..0.1   z -0.05..0.02    faces 24..35
    top bar     x 0.1..0.9   y 2.1..2.2   z -0.05..0.02    faces 36..47
    plate       x 0.1..0.9   y 0.1..2.1   z -0.02..0.00    faces 48..59

40 vertices, 60 triangles, one node "door". The atlas is a flat grey
64x64 PNG, so no COLOUR area is ever found — the run is about geometry.
Positions are float32 in the file; the script rounds to 5 decimals, so
0.1 reads back as 0.1.

[A] THE LANDING HOOK ON A DOOR PROP — ``create_prop(category="door")``
  (no key_areas at all) + ``save_uploaded_glb(door_glb())``: a door prop
  gets its leaf cut out on every landing (``props.is_door_prop``), so
  WITHOUT calling detect_areas the active model is a second gallery file
  whose glTF has exactly the nodes "frame" and "leaf" (sorted: frame first);
  the frame mesh has 48 triangles, the leaf 12 (fixture F4: the plate);
  both nodes carry NO translation/rotation/scale (the transform is baked,
  so ``leaf_bbox`` is the node's own box). Sidecar ``areas`` = ONE entry
  {id "leaf", kind "leaf", source "auto", faces 12, size_m [0.8, 2.0]
  (the plate's plane fit: normal along its 2 cm axis, u = x, v = y),
  normal [0, 0, 1]}; sidecar ``leaf_bbox`` = {min [0.1, 0.1, -0.02],
  max [0.9, 2.1, 0]} (fixture F5); ``.areas.json`` has mesh_layout
  [{frame, 48}, {leaf, 12}], the leaf's 12 box edges and the same
  leaf_bbox; the full record and ``areas_info`` carry leaf_bbox;
  ``areas_error`` absent; the leaf vertices in the file span exactly that
  box; slots stay [] (a node is not a material).

[B] DELETE — ``delete_area(pid, "leaf")``: the result GLB has ONE node
  "frame" with 60 triangles, no node "leaf"; sidecar areas [] and no
  ``leaf_bbox``; areas_info says None; the record has no key.

[C] MANUAL — the plate's faces of the CURRENT mesh (R1 = file order of the
  one node; a face is picked when ALL its vertices lie in the plate's box
  widened by 1 cm: x 0.09..0.91, y 0.09..2.11, z -0.03..0.01 — every bar
  face has a vertex at z = -0.05 or z = 0.02, or at x <= 0.1 / >= 0.9
  together with y = 0 / 2.2; a centroid test would not do, float32 puts
  the bars' inner faces at x = 0.10000000149; 12 faces) as kind "leaf":
  nodes frame (48) + leaf (12) again, source "manual", the same leaf_bbox.

[D] NOT A DOOR — ``create_prop(category="decor")`` + the same upload: no
  key_areas and no door tag, so the landing only reconciles: ONE gallery
  file, one node, no leaf_bbox, areas [].

[F] A PANE INSIDE THE LEAF SWINGS WITH IT (spec § 6: "Glas-Flächen, die im
  Blatt liegen, bleiben Material-Slots im leaf-Knoten") — ``door_glb(glass=
  True)``: the plate's four FRONT vertices (the only ones at z = 0.0) map to
  the UV square u, v in [0.6, 0.9] (corner (0.1, 0.1) -> (0.6, 0.6),
  (0.9, 2.1) -> (0.9, 0.9)); every other vertex maps to (0.1, 0.1). The
  atlas is magenta (255, 0, 255) over png columns/rows 36..60 (u, v in
  [0.5625, 0.953)) and grey elsewhere. So the plate's two front triangles
  sample magenta (centroid of (0.6,0.6),(0.9,0.6),(0.9,0.9) = (0.8, 0.7);
  the two median samples (0.733, 0.667) and (0.833, 0.667) — all inside);
  an edge face (two front vertices + one back vertex at (0.1, 0.1)) has its
  centroid at u = (0.6 + 0.9 + 0.1) / 3 = 0.533 and its nearest median
  sample at 0.533 + (0.6 - 0.533) / 3 = 0.556 < 0.5625 — grey, so at most
  ONE of three samples is magenta and the face stays atlas; the frame's
  faces sit at (0.1, 0.1) — grey. => exactly 2 magenta faces.
  ``create_prop(category="door", key_areas=["glass"])`` + upload: the
  landing run asks for kinds [glass, leaf]; the 2 magenta faces are below
  the production 12-face filter, so only the leaf is cut (areas = [leaf]).
  Then ``detect_areas(gp, mode="auto", min_faces=2)`` (the same lowering
  Task 3's smoke uses — the fixture quad has 2 faces): the leaf is joined
  back, glass_1 is split off (planar UVs: u = (x - 0.1) / 0.8, glTF
  v = 1 - (y - 0.1) / 2.0, size_m [0.8, 2.0], normal [0, 0, 1], 4 outline
  edges), then the leaf is cut again with the glass faces INSIDE it:
    nodes frame + leaf; the LEAF's primitives carry slot_glass_1 (2 tris)
    and atlas (10); the frame: atlas 48, no slot_glass_1;
    TEXCOORD_1 (the atlas backup layer) on the leaf's primitives;
    sidecar areas [glass_1 (auto, 2 faces), leaf (12)], leaf_bbox as [A];
    slots [{glass_1, material}]; .areas.json: glass_1 has 4 edges.
  ``delete_area(gp, "leaf")``: one node "frame", 60 tris, slot_glass_1
  still 2 tris with its planar UVs, TEXCOORD_1 still present (the join
  keeps the backup layer), areas [glass_1], no leaf_bbox, slots unchanged.

[G] NO LEAF FOUND — a door prop (category "door", no key_areas) with the
  BARS ONLY (``door_glb(plate=False)``, fixture F7 of the maths smoke):
  the landing run asks for kinds ["leaf"] ONLY (no unrequested chroma
  detection: the door tag alone never adds a colour kind), finds no seed ->
  ONE gallery file (nothing changed, no split file), areas [], no
  leaf_bbox, and the file's ``areas_warning`` carries props.NO_LEAF_NOTE ("no door leaf
  found — draw it with the polygon tool"). The run WORKED, so areas_info
  reports it as `warning`, not as `error` (which stays "").

[E] AUTO RE-RUN ON A SPLIT MESH — ``detect_areas(pid, mode="auto")`` on the
  prop of [C]: the previous leaf is joined back first and found again —
  still frame 48 / leaf 12, the same box. The source STAYS "manual": an
  area that existed before a run keeps its source (`_sidecar_areas_from_
  script`, the rule every colour area follows). This is also the round-trip
  proof: the file went through Blender's exporter once, which splits a
  flat-shaded box's corners into one vertex per normal — the script welds
  by position for the leaf geometry, or the heuristic would find only the
  plate's front (2 faces) with nothing edge-connected to it.
"""
import json
import os
import struct
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="door-leaf-smoke-"))
os.environ["STORAGE_DIR"] = str(WORLD)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.blender import refine  # noqa: E402
from app.core import props as store  # noqa: E402

FAILURES = []



def file_meta(pid: str) -> dict:
    """The ACTIVE full mesh's own sidecar — where the areas, the leaf box, the
    run stamp and the note of a run live since spec-bild-props-v2.md E1."""
    return store.read_model_sidecar(store.model_gallery(pid).find(store.DEFAULT_TIER, fallback=False))

def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def near(a, b, eps=1e-4) -> bool:
    return abs(float(a) - float(b)) <= eps


def vnear(a, b, eps=1e-4) -> bool:
    return len(a) == len(b) and all(near(x, y, eps) for x, y in zip(a, b))


# ── fixture ───────────────────────────────────────────────────────────────

def png_rgb(width: int, height: int, pixel) -> bytes:
    def chunk(tag: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))
    raw = b"".join(
        b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width))
        for y in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def box(x0, x1, y0, y1, z0, z1, verts, faces):
    b = len(verts)
    verts += [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
              (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    for tri in ((4, 5, 6), (4, 6, 7), (0, 2, 1), (0, 3, 2), (0, 4, 7), (0, 7, 3),
                (1, 2, 6), (1, 6, 5), (0, 1, 5), (0, 5, 4), (3, 7, 6), (3, 6, 2)):
        faces.append(tuple(b + i for i in tri))


def door_geometry(plate: bool = True):
    verts, faces = [], []
    box(0.0, 0.1, 0.0, 2.2, -0.05, 0.02, verts, faces)
    box(0.9, 1.0, 0.0, 2.2, -0.05, 0.02, verts, faces)
    box(0.1, 0.9, 0.0, 0.1, -0.05, 0.02, verts, faces)
    box(0.1, 0.9, 2.1, 2.2, -0.05, 0.02, verts, faces)
    if plate:
        box(0.1, 0.9, 0.1, 2.1, -0.02, 0.00, verts, faces)
    return verts, faces


def door_glb(glass: bool = False, plate: bool = True) -> bytes:
    positions, faces = door_geometry(plate)
    if glass:
        # Only the plate's FRONT vertices sit at z == 0.0 exactly.
        uvs = [((0.6 + (x - 0.1) / 0.8 * 0.3, 0.6 + (y - 0.1) / 2.0 * 0.3)
                if z == 0.0 else (0.1, 0.1)) for x, y, z in positions]
    else:
        uvs = [(x, y / 2.2) for x, y, _z in positions]
    indices = [i for f in faces for i in f]
    pos = b"".join(struct.pack("<fff", *p) for p in positions)
    tex = b"".join(struct.pack("<ff", *t) for t in uvs)
    idx = b"".join(struct.pack("<H", i) for i in indices)
    idx += b"\0" * ((4 - len(idx) % 4) % 4)
    png = png_rgb(64, 64, (lambda x, y: (255, 0, 255) if 36 <= x < 61 and 36 <= y < 61
                           else (128, 128, 128)) if glass
                  else (lambda x, y: (128, 128, 128)))
    png_len = len(png)
    png += b"\0" * ((4 - len(png) % 4) % 4)
    blob = pos + tex + idx + png
    views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": len(pos), "target": 34962},
        {"buffer": 0, "byteOffset": len(pos), "byteLength": len(tex), "target": 34962},
        {"buffer": 0, "byteOffset": len(pos) + len(tex), "byteLength": len(indices) * 2,
         "target": 34963},
        {"buffer": 0, "byteOffset": len(pos) + len(tex) + len(idx), "byteLength": png_len},
    ]
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    zs = [p[2] for p in positions]
    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "door"}],
        "meshes": [{"name": "door", "primitives": [{
            "attributes": {"POSITION": 0, "TEXCOORD_0": 1},
            "indices": 2, "material": 0}]}],
        "materials": [{"name": "atlas", "pbrMetallicRoughness": {
            "baseColorTexture": {"index": 0}, "metallicFactor": 0.0}}],
        "textures": [{"source": 0, "sampler": 0}],
        "samplers": [{"magFilter": 9728, "minFilter": 9728,
                      "wrapS": 10497, "wrapT": 10497}],
        "images": [{"mimeType": "image/png", "bufferView": 3, "name": "atlas"}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": views,
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(positions),
             "type": "VEC3", "min": [min(xs), min(ys), min(zs)],
             "max": [max(xs), max(ys), max(zs)]},
            {"bufferView": 1, "componentType": 5126, "count": len(positions),
             "type": "VEC2"},
            {"bufferView": 2, "componentType": 5123, "count": len(indices),
             "type": "SCALAR"},
        ],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    return (struct.pack("<III", 0x46546C67, 2, total)
            + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(blob), 0x004E4942) + blob)


# ── result reader (stdlib) ────────────────────────────────────────────────

_CTYPE = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2),
          5125: ("I", 4), 5126: ("f", 4)}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def read_glb(data: bytes):
    gltf, blob = {}, b""
    off = 12
    while off + 8 <= len(data):
        ln, typ = struct.unpack("<II", data[off:off + 8])
        body = data[off + 8:off + 8 + ln]
        if typ == 0x4E4F534A:
            gltf = json.loads(body.decode("utf-8"))
        elif typ == 0x004E4942:
            blob = body
        off += 8 + ln + ((4 - ln % 4) % 4)
    return gltf, blob


def accessor(gltf, blob, index):
    acc = gltf["accessors"][index]
    view = gltf["bufferViews"][acc["bufferView"]]
    fmt, size = _CTYPE[acc["componentType"]]
    n = _NCOMP[acc["type"]]
    start = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
    stride = int(view.get("byteStride", 0)) or size * n
    out = []
    for k in range(acc["count"]):
        at = start + k * stride
        out.append(struct.unpack("<" + fmt * n, blob[at:at + size * n]))
    return out


def nodes(path: Path):
    """``{node name: {"tris": [(p, p, p), …], "prims": [{material, tris, uvs,
    has_uv1}], "trs": bool}}`` for every node with a mesh, in node order;
    ``trs`` = the node carries a transform."""
    gltf, blob = read_glb(path.read_bytes())
    mats = [m.get("name", "") for m in gltf.get("materials", [])]
    out = {}
    for node in gltf.get("nodes", []):
        if "mesh" not in node:
            continue
        mesh = gltf["meshes"][node["mesh"]]
        tris, prims = [], []
        for prim in mesh.get("primitives", []):
            attrs = prim["attributes"]
            pos = accessor(gltf, blob, attrs["POSITION"])
            uv = accessor(gltf, blob, attrs["TEXCOORD_0"]) if "TEXCOORD_0" in attrs else []
            idx = [i[0] for i in accessor(gltf, blob, prim["indices"])] if "indices" in prim \
                else list(range(len(pos)))
            ptris = [tuple(pos[i] for i in idx[k:k + 3]) for k in range(0, len(idx), 3)]
            puvs = [tuple(uv[i] for i in idx[k:k + 3]) for k in range(0, len(idx), 3)] if uv else []
            tris += ptris
            prims.append({"material": mats[prim["material"]] if "material" in prim else "",
                          "tris": ptris, "uvs": puvs, "has_uv1": "TEXCOORD_1" in attrs})
        out[node.get("name", "")] = {
            "tris": tris, "prims": prims,
            "trs": any(k in node for k in ("translation", "rotation", "scale", "matrix")),
        }
    return out


def mat_tris(n, node: str, material: str) -> int:
    return sum(len(p["tris"]) for p in n.get(node, {}).get("prims", []) if p["material"] == material)


def uv_rule_holds(n, node: str, material: str, rule) -> bool:
    """Every vertex of every triangle of ``material`` on ``node`` has uv == rule(x, y)."""
    ok = False
    for p in n.get(node, {}).get("prims", []):
        if p["material"] != material:
            continue
        ok = True
        for t, tu in zip(p["tris"], p["uvs"]):
            for (x, y, _z), (u, v) in zip(t, tu):
                eu, ev = rule(x, y)
                if not (near(u, eu) and near(v, ev)):
                    return False
    return ok


def span(tris):
    pts = [p for t in tris for p in t]
    return ([min(p[i] for p in pts) for i in range(3)],
            [max(p[i] for p in pts) for i in range(3)])


def flat_faces_where(path: Path, pred):
    """R1 flat indices over the nodes sorted by NAME (the script's order) of
    the faces whose EVERY vertex satisfies ``pred(x, y, z)``."""
    out, flat = [], 0
    n = nodes(path)
    for name in sorted(n):
        for t in n[name]["tris"]:
            if all(pred(*v) for v in t):
                out.append(flat)
            flat += 1
    return out


LEAF_MIN = [0.1, 0.1, -0.02]
LEAF_MAX = [0.9, 2.1, 0.0]


def check_split(label: str, pid: str, source: str, extra_areas: int = 0) -> None:
    active = store.model_path(pid)
    n = nodes(active)
    check(f"{label}: nodes are exactly frame + leaf", set(n) == {"frame", "leaf"}, str(sorted(n)))
    check(f"{label}: frame has 48 triangles", len(n.get("frame", {}).get("tris", [])) == 48,
          str(len(n.get("frame", {}).get("tris", []))))
    check(f"{label}: leaf has 12 triangles", len(n.get("leaf", {}).get("tris", [])) == 12,
          str(len(n.get("leaf", {}).get("tris", []))))
    check(f"{label}: neither node carries a transform (baked)",
          not n.get("frame", {}).get("trs") and not n.get("leaf", {}).get("trs"))
    if n.get("leaf", {}).get("tris"):
        lo, hi = span(n["leaf"]["tris"])
        check(f"{label}: the leaf's vertices span the derived box",
              vnear(lo, LEAF_MIN) and vnear(hi, LEAF_MAX), f"{lo} .. {hi}")
    meta = file_meta(pid)
    areas = meta.get("areas") or []
    check(f"{label}: sidecar areas = {extra_areas} colour + one leaf entry, leaf LAST",
          len(areas) == extra_areas + 1 and areas[-1]["id"] == "leaf"
          and areas[-1]["kind"] == "leaf"
          and areas[-1]["faces"] == 12 and areas[-1]["source"] == source, str(areas))
    a = areas[-1] if areas else {}
    check(f"{label}: size_m [0.8, 2.0], normal [0, 0, 1]",
          vnear(a.get("size_m") or [0, 0], [0.8, 2.0])
          and vnear(a.get("normal") or [9, 9, 9], [0, 0, 1]), str(a))
    bb = meta.get("leaf_bbox") or {}
    check(f"{label}: sidecar leaf_bbox min [0.1, 0.1, -0.02] max [0.9, 2.1, 0]",
          vnear(bb.get("min") or [], LEAF_MIN) and vnear(bb.get("max") or [], LEAF_MAX), str(bb))
    check(f"{label}: areas_error absent", "areas_error" not in meta, str(meta.get("areas_error")))
    sp = store.areas_sidecar_path(active)
    extra = json.loads(sp.read_text(encoding="utf-8")) if sp and sp.exists() else {}
    check(f"{label}: .areas.json mesh_layout [frame 48, leaf 12]",
          extra.get("mesh_layout") == [{"name": "frame", "tri_count": 48},
                                       {"name": "leaf", "tri_count": 12}],
          str(extra.get("mesh_layout")))
    rec_edges = next((x.get("edges") for x in extra.get("areas", []) if x.get("id") == "leaf"), None)
    check(f"{label}: the leaf's outline is its box — 12 edges", len(rec_edges or []) == 12,
          str(len(rec_edges or [])))
    check(f"{label}: .areas.json carries the same leaf_bbox",
          vnear((extra.get("leaf_bbox") or {}).get("min") or [], LEAF_MIN)
          and vnear((extra.get("leaf_bbox") or {}).get("max") or [], LEAF_MAX))
    rec = store.get_prop(pid)
    check(f"{label}: the full record carries leaf_bbox",
          vnear((rec["variant_tiers"][0].get("leaf_bbox") or {}).get("min") or [], LEAF_MIN),
          str(rec["variant_tiers"][0].get("leaf_bbox")))
    check(f"{label}: areas_info carries leaf_bbox",
          vnear((store.areas_info(pid).get("leaf_bbox") or {}).get("max") or [], LEAF_MAX))
    if not extra_areas:
        check(f"{label}: slots stay [] — a node is not a material", rec["slots"] == [], str(rec["slots"]))


def main() -> int:
    reason = refine.unavailable_reason()
    if reason:
        print(f"skipped: Blender unavailable ({reason})")
        return 0

    print("[A] the landing hook cuts a DOOR prop's leaf out")
    pid = store.create_prop(name="Front door", category="door")["id"]
    check("upload lands", store.save_uploaded_glb(pid, door_glb()))
    files = store.model_gallery(pid).files()
    check("two gallery files: the upload and the split", len(files) == 2, str([f.name for f in files]))
    check_split("A", pid, "auto")

    print("\n[B] delete joins the leaf back into the frame")
    areas = store.delete_area(pid, "leaf")
    check("B: areas == []", areas == [], str(areas))
    n = nodes(store.model_path(pid))
    check("B: one node 'frame' with 60 triangles",
          set(n) == {"frame"} and len(n["frame"]["tris"]) == 60, str({k: len(v["tris"]) for k, v in n.items()}))
    meta = file_meta(pid)
    check("B: sidecar has no leaf_bbox", "leaf_bbox" not in meta, str(meta.get("leaf_bbox")))
    check("B: areas_info leaf_bbox is None, record has no key",
          store.areas_info(pid)["leaf_bbox"] is None
          and "leaf_bbox" not in store.get_prop(pid)["variant_tiers"][0])

    print("\n[C] a manual face list becomes the leaf")
    faces = flat_faces_where(store.model_path(pid),
                             lambda x, y, z: 0.09 < x < 0.91 and 0.09 < y < 2.11
                             and -0.03 < z < 0.01)
    check("C: the plate is 12 flat faces", len(faces) == 12, str(faces))
    areas = store.detect_areas(pid, mode="manual", faces=faces, kind="leaf")
    check("C: returns the leaf entry", [a["id"] for a in areas] == ["leaf"], str(areas))
    check_split("C", pid, "manual")

    print("\n[D] not a door: no split, only a reconcile")
    dp = store.create_prop(name="Grey plate thing", category="decor")["id"]
    check("D: upload lands", store.save_uploaded_glb(dp, door_glb()))
    check("D: ONE gallery file", len(store.model_gallery(dp).files()) == 1)
    check("D: one node, no leaf", set(nodes(store.model_path(dp))) == {"door"})
    check("D: areas [] and no leaf_bbox",
          file_meta(dp).get("areas", []) == [] and "leaf_bbox" not in file_meta(dp))

    print("\n[E] auto on a split mesh: the leaf is joined back and found again")
    areas = store.detect_areas(pid, mode="auto")
    check("E: returns the leaf entry", [a["id"] for a in areas] == ["leaf"], str(areas))
    check_split("E", pid, "manual")

    print("\n[F] a pane inside the leaf stays a slot material of the leaf node")
    gp = store.create_prop(name="Glass door", category="door", key_areas=["glass"])["id"]
    check("F: upload lands", store.save_uploaded_glb(gp, door_glb(glass=True)))
    meta = file_meta(gp)
    check("F: the landing (production filter) cut the leaf only",
          [a["id"] for a in meta.get("areas") or []] == ["leaf"], str(meta.get("areas")))
    areas = store.detect_areas(gp, mode="auto", min_faces=2)
    check("F: areas glass_1 (auto, 2 faces) then leaf (auto, 12)",
          [(a["id"], a["source"], a["faces"]) for a in areas]
          == [("glass_1", "auto", 2), ("leaf", "auto", 12)], str(areas))
    g = next((a for a in areas if a["id"] == "glass_1"), {})
    check("F: glass_1 size_m [0.8, 2.0], normal [0, 0, 1]",
          vnear(g.get("size_m") or [], [0.8, 2.0]) and vnear(g.get("normal") or [], [0, 0, 1]), str(g))
    check_split("F", gp, "auto", extra_areas=1)
    n = nodes(store.model_path(gp))
    check("F: the LEAF carries slot_glass_1 with 2 triangles",
          mat_tris(n, "leaf", "slot_glass_1") == 2, str(mat_tris(n, "leaf", "slot_glass_1")))
    check("F: …and atlas with 10", mat_tris(n, "leaf", "atlas") == 10, str(mat_tris(n, "leaf", "atlas")))
    check("F: the frame has atlas 48 and no slot_glass_1",
          mat_tris(n, "frame", "atlas") == 48 and mat_tris(n, "frame", "slot_glass_1") == 0,
          str([(p["material"], len(p["tris"])) for p in n.get("frame", {}).get("prims", [])]))
    glass_uv = lambda x, y: ((x - 0.1) / 0.8, 1 - (y - 0.1) / 2.0)  # noqa: E731
    check("F: the glass faces carry planar UVs ((x-0.1)/0.8, 1-(y-0.1)/2)",
          uv_rule_holds(n, "leaf", "slot_glass_1", glass_uv))
    check("F: TEXCOORD_1 (the atlas backup layer) on the leaf's primitives",
          all(p["has_uv1"] for p in n.get("leaf", {}).get("prims", [])))
    rec = store.get_prop(gp)
    check("F: slots [{glass_1, material}]",
          rec["slots"] == [{"name": "glass_1", "kind": "material"}], str(rec["slots"]))
    sp = store.areas_sidecar_path(store.model_path(gp))
    extra = json.loads(sp.read_text(encoding="utf-8")) if sp and sp.exists() else {}
    g_edges = next((x.get("edges") for x in extra.get("areas", []) if x.get("id") == "glass_1"), None)
    check("F: .areas.json: glass_1 has 4 outline edges", len(g_edges or []) == 4, str(len(g_edges or [])))
    areas = store.delete_area(gp, "leaf")
    check("F: delete leaf -> areas [glass_1]", [a["id"] for a in areas] == ["glass_1"], str(areas))
    n = nodes(store.model_path(gp))
    check("F: one node 'frame' with 60 triangles",
          set(n) == {"frame"} and len(n["frame"]["tris"]) == 60,
          str({k: len(v["tris"]) for k, v in n.items()}))
    check("F: slot_glass_1 still has its 2 triangles on the frame",
          mat_tris(n, "frame", "slot_glass_1") == 2, str(mat_tris(n, "frame", "slot_glass_1")))
    check("F: …with their planar UVs", uv_rule_holds(n, "frame", "slot_glass_1", glass_uv))
    check("F: TEXCOORD_1 survives the join",
          all(p["has_uv1"] for p in n.get("frame", {}).get("prims", [])))
    meta = file_meta(gp)
    check("F: no leaf_bbox after the delete", "leaf_bbox" not in meta)
    check("F: slots unchanged",
          store.get_prop(gp)["slots"] == [{"name": "glass_1", "kind": "material"}])

    print("\n[G] a door without a leaf: the run says so")
    np_ = store.create_prop(name="Bare frame", category="door")["id"]
    check("G: upload lands", store.save_uploaded_glb(np_, door_glb(plate=False)))
    check("G: ONE gallery file — nothing was split",
          len(store.model_gallery(np_).files()) == 1,
          str([f.name for f in store.model_gallery(np_).files()]))
    meta = file_meta(np_)
    check("G: areas [] and no leaf_bbox",
          meta.get("areas", []) == [] and "leaf_bbox" not in meta, str(meta.get("areas")))
    check("G: areas_warning carries NO_LEAF_NOTE (its own file key since v2)",
          meta.get("areas_warning") == store.NO_LEAF_NOTE and "areas_error" not in meta,
          str((meta.get("areas_warning"), meta.get("areas_error"))))
    # A run that WORKED and found nothing to cut is a NOTE: `areas_info`
    # splits the one sidecar key into `warning` (this) and `error` (a run
    # that broke), so the tab cannot report a failure over a working run.
    check("G: areas_info reports it as a WARNING, with `error` empty",
          store.areas_info(np_)["warning"] == store.NO_LEAF_NOTE
          and store.areas_info(np_)["error"] == "",
          str((store.areas_info(np_)["error"], store.areas_info(np_)["warning"])))

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
