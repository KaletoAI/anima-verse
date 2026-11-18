#!/usr/bin/env python3
"""Blender round trip for the ATLAS BACKUP MARKER of the picture-area split
(``app/blender/scripts/picture_areas.py``, review 03 — ``_backup_layer``).

Before: the script took the LAST UV layer of any mesh that wore a
``slot_<kind>_<k>`` material as its own atlas backup. A file that merely has
two UV sets (a lightmap, or a split some other tool made) was misread: a
delete copied the foreign layer into layer 0 and then removed it. Now the
backup is the layer a glTF MESH EXTRA ``av_atlas_uv = <index>`` names (glTF
keeps no UV-layer names — Blender re-imports TEXCOORD_n as "UVMap",
"UVMap.001", … — but it keeps the layer ORDER and, with ``export_extras``,
mesh extras as mesh custom properties). No valid marker = no backup.

Usage:  ./.venv/bin/python scripts/smoke_picture_areas_backup_mark_blender.py

Needs Blender (``refine.unavailable_reason()`` empty); otherwise prints
"skipped: Blender unavailable (<reason>)" and exits 0. The script is run
through ``app.blender.runner.run`` exactly as ``props._areas_run`` does —
throw-away files in /tmp, no world, no DB, no server. Every expected value
below is derived BY HAND from the fixture, never recorded from a run.

THE FIXTURE (glTF y-up, stdlib), ``plate_glb(materials, uv1, extras)``:
  the 1 m x 1 m plate of ``smoke_picture_areas_blender.py`` with n = 2: 3x3
  vertices at x, y = -0.5 + i/2, z = 0, facing +z; four quads q(i, j) (i along
  x, j along y), two CCW triangles each. TEXCOORD_0 (glTF, v top-down) is the
  atlas: u = x + 0.5, v = 0.5 - y. ``materials`` maps a material name to its
  quads, one primitive each in that order; no textures (manual and delete
  need none). ``uv1`` given = a TEXCOORD_1 that is that constant everywhere
  (a second NATIVE UV set); ``extras`` = the mesh's glTF extras.
  Quads: q(0,1) = top-left (x < 0, y > 0), q(1,0) = bottom-right (x > 0,
  y < 0).

[A] TWO NATIVE UV SETS, A SLOT MATERIAL, NO MARKER — the review's case.
  materials {atlas: q(0,0) q(1,0) q(1,1), slot_picture_1: q(0,1)}, uv1 =
  (0.25, 0.75), no extras. ``delete`` picture_1 (origin atlas):
    materials -> ["atlas"] with all 8 triangles;
    TEXCOORD_0 -> every vertex still (x + 0.5, 0.5 - y): there is NO backup,
      so nothing is "restored" (the old code wrote (0.25, 0.75) onto the two
      top-left triangles — the lightmap);
    TEXCOORD_1 -> still present, every value (0.25, 0.75) (the old code
      removed it as an "unused backup");
    mesh extras -> no ``av_atlas_uv`` (no backup layer exists).
[A2] the same file with a STALE marker ``{"av_atlas_uv": 5}`` (a 2-layer
  mesh has no layer 5): a marker out of range counts as absent -> exactly
  the [A] result.

[B] A PLAIN FILE IS SPLIT, THE MARKER COMES BACK FROM ITS OWN ROUND TRIP.
  materials {atlas: all four quads}, one UV set, no extras.
  B1 ``manual`` kind picture on flat faces [4, 5] (R1: q(0,1) is the third
     quad in the fixture order q(0,0) q(1,0) q(0,1) q(1,1) -> triangles 4, 5):
       slot_picture_1 2 triangles, atlas 6;
       mesh extras ``av_atlas_uv == 1`` (layer 0 + the one appended backup);
       every primitive has TEXCOORD_1 and no TEXCOORD_2;
       TEXCOORD_1 everywhere = the atlas (x + 0.5, 0.5 - y) (copy of layer 0
         taken before the first write);
       slot_picture_1 TEXCOORD_0 = planar: normal (0,0,1), frame u = (1,0,0),
         v = (0,1,0) over the quad's box x in [-0.5, 0], y in [0, 0.5]:
         u = (x + 0.5)/0.5 = 2x + 1, v_blender = y/0.5, glTF v = 1 - 2y;
       atlas TEXCOORD_0 unchanged (x + 0.5, 0.5 - y).
  B2 ``delete`` picture_1 on B1's file: the marked layer (TEXCOORD_1 after
     an export + import) is the backup -> every vertex TEXCOORD_0 =
     (x + 0.5, 0.5 - y) again; no area left -> the backup goes: no
     TEXCOORD_1, no marker; materials ["atlas"], 8 triangles.
  B3 ``manual`` kind glass on B1's file, on the two triangles whose centroid
     has x > 0 and y < 0 (q(1,0); flat indices read off B1's file order):
       still exactly TEXCOORD_0 + TEXCOORD_1 (the marked layer is REUSED, no
         third layer), marker 1, TEXCOORD_1 everywhere the atlas;
       slot_glass_1 TEXCOORD_0 = box x in [0, 0.5], y in [-0.5, 0]:
         u = x/0.5 = 2x, glTF v = 1 - (y + 0.5)/0.5 = -2y;
       slot_picture_1 keeps (2x + 1, 1 - 2y).
  B4 ``delete`` picture_1 on B3's file (two round trips after the backup
     was taken): the picture faces get (x + 0.5, 0.5 - y) back from the
     marked layer, glass_1 keeps (2x, -2y), marker still 1, TEXCOORD_1
     everywhere the atlas.

[C] A SPLIT FROM BEFORE THE MARKER — the host's param
  ``unmarked_backup_is_last_layer`` (set by ``props._areas_run`` only when
  its records prove the file is its own old split; the proof itself is
  ``scripts/smoke_picture_areas_legacy_proof.py``).
  ``layered_glb``: the same plate, but every quad with its OWN four
  vertices (a split file stores planar and atlas UVs per primitive), quads
  q(0,0) q(1,1) on atlas, q(0,1) on slot_picture_1, q(1,0) on slot_glass_1.
  The old script's output, exactly: TEXCOORD_0 = atlas (x + 0.5, 0.5 - y)
  on atlas faces, planar (2x + 1, 1 - 2y) on picture_1, planar (2x, -2y)
  on glass_1 (the [B] derivations); TEXCOORD_1 = the atlas everywhere (the
  backup, LAST layer); NO extras.
  C1 ``delete`` picture_1 WITH the param: the last layer is claimed ->
     the four former picture faces read (x + 0.5, 0.5 - y) again, atlas 6
     triangles, glass_1 2 with (2x, -2y); glass_1 is left, so the backup
     stays: TEXCOORD_1 everywhere the atlas, and the file now carries
     ``av_atlas_uv == 1`` (migrated).
  C2 the same file and delete WITHOUT the param: the strict rule — no
     backup, so the former picture faces keep (2x + 1, 1 - 2y) under the
     atlas material; TEXCOORD_1 stays an ordinary layer (atlas everywhere);
     no marker (no backup layer exists to name).
  C3 A MARKED FILE IGNORES THE PARAM: three sets — TEXCOORD_0 as above,
     TEXCOORD_1 the atlas, TEXCOORD_2 the constant (0.25, 0.75) (a native
     extra set) — and ``av_atlas_uv: 1``. ``delete`` picture_1 WITH the
     param: the marker names layer 1, so the picture faces read
     (x + 0.5, 0.5 - y) — NOT (0.25, 0.75), which the last-layer rule
     would have given; marker still 1, TEXCOORD_2 still (0.25, 0.75).
"""
import json
import os
import shutil
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="picture-areas-mark-smoke-"))
os.environ["STORAGE_DIR"] = str(WORLD)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.blender import refine, runner  # noqa: E402

FAILURES = []
EPS = 1e-4


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


# ── fixture ───────────────────────────────────────────────────────────────

QUAD_ORDER = [(0, 0), (1, 0), (0, 1), (1, 1)]


def plate_glb(materials, uv1=None, extras=None) -> bytes:
    n = 2
    positions, uvs = [], []
    for j in range(n + 1):
        for i in range(n + 1):
            x, y = -0.5 + i / n, -0.5 + j / n
            positions.append((x, y, 0.0))
            uvs.append((x + 0.5, 0.5 - y))
    quads = {}
    for j in range(n):
        for i in range(n):
            a, b = j * (n + 1) + i, j * (n + 1) + i + 1
            c, d = (j + 1) * (n + 1) + i + 1, (j + 1) * (n + 1) + i
            quads[(i, j)] = [a, b, c, a, c, d]
    chunks = [b"".join(struct.pack("<fff", *p) for p in positions),
              b"".join(struct.pack("<ff", *t) for t in uvs)]
    if uv1 is not None:
        chunks.append(b"".join(struct.pack("<ff", *uv1) for _ in positions))
    index_lists = []
    for _name, qs in materials:
        idx = [k for q in qs for k in quads[q]]
        index_lists.append(idx)
        raw = b"".join(struct.pack("<H", k) for k in idx)
        chunks.append(raw + b"\0" * ((4 - len(raw) % 4) % 4))
    views, accessors, off = [], [], 0
    for ci, ch in enumerate(chunks):
        is_index = ci >= (3 if uv1 is not None else 2)
        views.append({"buffer": 0, "byteOffset": off, "byteLength": len(ch),
                      "target": 34963 if is_index else 34962})
        off += len(ch)
    accessors.append({"bufferView": 0, "componentType": 5126, "count": len(positions),
                      "type": "VEC3", "min": [-0.5, -0.5, 0.0], "max": [0.5, 0.5, 0.0]})
    accessors.append({"bufferView": 1, "componentType": 5126, "count": len(positions),
                      "type": "VEC2"})
    attrs = {"POSITION": 0, "TEXCOORD_0": 1}
    if uv1 is not None:
        accessors.append({"bufferView": 2, "componentType": 5126,
                          "count": len(positions), "type": "VEC2"})
        attrs["TEXCOORD_1"] = 2
    prims = []
    first = len(accessors)
    for k, (idx, (name, _qs)) in enumerate(zip(index_lists, materials)):
        accessors.append({"bufferView": first + k, "componentType": 5123,
                          "count": len(idx), "type": "SCALAR"})
        prims.append({"attributes": dict(attrs), "indices": first + k, "material": k})
    mesh = {"name": "plate", "primitives": prims}
    if extras is not None:
        mesh["extras"] = extras
    blob = b"".join(chunks)
    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "plate"}],
        "meshes": [mesh],
        "materials": [{"name": name, "pbrMetallicRoughness": {
            "baseColorFactor": [0.5, 0.5, 0.5, 1.0], "metallicFactor": 0.0}}
            for name, _qs in materials],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": views,
        "accessors": accessors,
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    return (struct.pack("<III", 0x46546C67, 2, total)
            + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(blob), 0x004E4942) + blob)


def layered_glb(prims, layers, extras=None) -> bytes:
    """``prims`` [(material, [quad, …])], ``layers`` [f(material, x, y) ->
    (u, v)] = TEXCOORD_0..n; every quad has its own four vertices."""
    n = 2
    vchunks, ichunks, accessors, prim_json = [], [], [], []
    for k, (name, qs) in enumerate(prims):
        pos, uvs, idx = [], [[] for _ in layers], []
        for (i, j) in qs:
            base = len(pos)
            for (di, dj) in ((0, 0), (1, 0), (1, 1), (0, 1)):
                x, y = -0.5 + (i + di) / n, -0.5 + (j + dj) / n
                pos.append((x, y, 0.0))
                for li, f in enumerate(layers):
                    uvs[li].append(f(name, x, y))
            idx += [base, base + 1, base + 2, base, base + 2, base + 3]
        attrs = {"POSITION": len(accessors)}
        vchunks.append(b"".join(struct.pack("<fff", *p) for p in pos))
        accessors.append({"count": len(pos), "type": "VEC3", "componentType": 5126,
                          "min": [min(p[c] for p in pos) for c in range(3)],
                          "max": [max(p[c] for p in pos) for c in range(3)]})
        for li in range(len(layers)):
            attrs[f"TEXCOORD_{li}"] = len(accessors)
            vchunks.append(b"".join(struct.pack("<ff", *t) for t in uvs[li]))
            accessors.append({"count": len(pos), "type": "VEC2", "componentType": 5126})
        raw = b"".join(struct.pack("<H", q) for q in idx)
        ichunks.append((len(accessors), raw + b"\0" * ((4 - len(raw) % 4) % 4), len(idx)))
        accessors.append({"count": len(idx), "type": "SCALAR", "componentType": 5123})
        prim_json.append({"attributes": attrs, "indices": ichunks[-1][0], "material": k})
    # bufferViews in accessor order: vertex chunks and index chunks interleave per primitive
    chunks, views, off, vi = [], [], 0, 0
    index_at = {a: (raw, cnt) for a, raw, cnt in ichunks}
    for a in range(len(accessors)):
        if a in index_at:
            ch, target = index_at[a][0], 34963
        else:
            ch, target = vchunks[vi], 34962
            vi += 1
        views.append({"buffer": 0, "byteOffset": off, "byteLength": len(ch), "target": target})
        accessors[a]["bufferView"] = a
        chunks.append(ch)
        off += len(ch)
    mesh = {"name": "plate", "primitives": prim_json}
    if extras is not None:
        mesh["extras"] = extras
    blob = b"".join(chunks)
    gltf = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "plate"}], "meshes": [mesh],
        "materials": [{"name": name, "pbrMetallicRoughness": {
            "baseColorFactor": [0.5, 0.5, 0.5, 1.0], "metallicFactor": 0.0}}
            for name, _qs in prims],
        "buffers": [{"byteLength": len(blob)}], "bufferViews": views, "accessors": accessors,
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    return (struct.pack("<III", 0x46546C67, 2, total)
            + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(blob), 0x004E4942) + blob)


def split_uv0(name, x, y):
    """TEXCOORD_0 of a split file: planar on the areas, atlas elsewhere."""
    if name == "slot_picture_1":
        return (2 * x + 1, 1 - 2 * y)
    if name == "slot_glass_1":
        return (2 * x, -2 * y)
    return (x + 0.5, 0.5 - y)


SPLIT_PRIMS = [("atlas", [(0, 0), (1, 1)]), ("slot_picture_1", [(0, 1)]),
               ("slot_glass_1", [(1, 0)])]


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
    return [struct.unpack("<" + fmt * n, blob[start + k * stride:start + k * stride + size * n])
            for k in range(acc["count"])]


def read_model(path: Path):
    """{"extras": <mesh 0 extras>, "texcoords": set of TEXCOORD_n names,
    "prims": [{material, verts: [(pos, uv0, uv1|None)] per triangle corner,
    tris}]} in file order."""
    gltf, blob = read_glb(path.read_bytes())
    mats = [m.get("name", "") for m in gltf.get("materials", [])]
    meshes = gltf.get("meshes", [])
    out = {"extras": (meshes[0].get("extras") or {}) if meshes else {},
           "texcoords": set(), "prims": []}
    for mesh in meshes:
        for prim in mesh.get("primitives", []):
            attrs = prim["attributes"]
            out["texcoords"] |= {k for k in attrs if k.startswith("TEXCOORD_")}
            pos = accessor(gltf, blob, attrs["POSITION"])
            uv0 = accessor(gltf, blob, attrs["TEXCOORD_0"])
            uv1 = accessor(gltf, blob, attrs["TEXCOORD_1"]) if "TEXCOORD_1" in attrs else None
            uv2 = accessor(gltf, blob, attrs["TEXCOORD_2"]) if "TEXCOORD_2" in attrs else None
            idx = [i[0] for i in accessor(gltf, blob, prim["indices"])]
            tris = [idx[k:k + 3] for k in range(0, len(idx), 3)]
            out["prims"].append({
                "material": mats[prim["material"]] if "material" in prim else "",
                "tris": [[(pos[i], uv0[i], uv1[i] if uv1 else None, uv2[i] if uv2 else None)
                          for i in t] for t in tris],
                "has_uv1": uv1 is not None})
    return out


def corners(model, material=None):
    return [c for p in model["prims"] if material is None or p["material"] == material
            for t in p["tris"] for c in t]


def tri_count(model, material):
    return sum(len(p["tris"]) for p in model["prims"] if p["material"] == material)


def uv_is(corner_list, which, fn):
    """Every corner's TEXCOORD_<which> equals ``fn(x, y)`` (glTF y-up)."""
    for corner in corner_list:
        pos, uv = corner[0], corner[1 + which]
        want = fn(pos[0], pos[1])
        if uv is None or abs(uv[0] - want[0]) > EPS or abs(uv[1] - want[1]) > EPS:
            return False
    return bool(corner_list)


def atlas(x, y):
    return (x + 0.5, 0.5 - y)


def flat_faces_where(model, pred):
    out, flat = [], 0
    for p in model["prims"]:
        for t in p["tris"]:
            cx = sum(c[0][0] for c in t) / 3
            cy = sum(c[0][1] for c in t) / 3
            if pred(cx, cy):
                out.append(flat)
            flat += 1
    return out


def run(src: Path, params: dict, tag: str) -> Path:
    out_dir = WORLD / f"out-{tag}"
    out_dir.mkdir()
    res = runner.run("picture_areas", inputs={"model": src}, params=params,
                     out_dir=out_dir, timeout_s=300)
    if not res.get("ok"):
        raise RuntimeError(f"{tag}: picture_areas failed: {res.get('error')}")
    produced = (res.get("outputs") or {}).get("model")
    if not produced:
        raise RuntimeError(f"{tag}: the run reported no change")
    return Path(produced)


def write(name: str, data: bytes) -> Path:
    p = WORLD / name
    p.write_bytes(data)
    return p


# ── the run ───────────────────────────────────────────────────────────────

def part_a(label: str, extras) -> None:
    src = write(f"{label}.glb", plate_glb(
        [("atlas", [(0, 0), (1, 0), (1, 1)]), ("slot_picture_1", [(0, 1)])],
        uv1=(0.25, 0.75), extras=extras))
    m = read_model(run(src, {"mode": "delete", "area": "picture_1",
                             "origins": {"picture_1": "atlas"}}, label))
    check(f"{label}: materials -> atlas with all 8 triangles",
          [p["material"] for p in m["prims"]] == ["atlas"] and tri_count(m, "atlas") == 8,
          str([(p["material"], len(p["tris"])) for p in m["prims"]]))
    check(f"{label}: TEXCOORD_0 untouched everywhere (no backup -> nothing restored)",
          uv_is(corners(m), 0, atlas))
    check(f"{label}: TEXCOORD_1 (the native second set) kept, every value (0.25, 0.75)",
          "TEXCOORD_1" in m["texcoords"]
          and uv_is(corners(m), 1, lambda x, y: (0.25, 0.75)), str(sorted(m["texcoords"])))
    check(f"{label}: no av_atlas_uv marker", "av_atlas_uv" not in m["extras"], str(m["extras"]))


def main() -> int:
    reason = refine.unavailable_reason()
    if reason:
        print(f"skipped: Blender unavailable ({reason})")
        return 0
    print(f"Blender: {runner.status().get('version')}")

    print("\n[A] two native UV sets + slot material, no marker: delete picture_1")
    part_a("A", None)
    print("\n[A2] the same with a stale marker (index 5 on a 2-layer mesh)")
    part_a("A2", {"av_atlas_uv": 5})

    print("\n[B1] plain file: manual picture on faces [4, 5]")
    src = write("B.glb", plate_glb([("atlas", QUAD_ORDER)]))
    b1_path = run(src, {"mode": "manual", "kind": "picture", "faces": [4, 5]}, "B1")
    b1 = read_model(b1_path)
    check("B1: slot_picture_1 2 triangles, atlas 6",
          tri_count(b1, "slot_picture_1") == 2 and tri_count(b1, "atlas") == 6)
    check("B1: mesh extras av_atlas_uv == 1", b1["extras"].get("av_atlas_uv") == 1,
          str(b1["extras"]))
    check("B1: exactly TEXCOORD_0 + TEXCOORD_1",
          b1["texcoords"] == {"TEXCOORD_0", "TEXCOORD_1"}
          and all(p["has_uv1"] for p in b1["prims"]), str(sorted(b1["texcoords"])))
    check("B1: TEXCOORD_1 everywhere the atlas (x + 0.5, 0.5 - y)",
          uv_is(corners(b1), 1, atlas))
    check("B1: picture faces planar (2x + 1, 1 - 2y)",
          uv_is(corners(b1, "slot_picture_1"), 0, lambda x, y: (2 * x + 1, 1 - 2 * y)))
    check("B1: atlas faces keep (x + 0.5, 0.5 - y)", uv_is(corners(b1, "atlas"), 0, atlas))

    print("\n[B2] delete picture_1 on B1's file: restored from the MARKED layer")
    b2 = read_model(run(b1_path, {"mode": "delete", "area": "picture_1",
                                  "origins": {"picture_1": "atlas"}}, "B2"))
    check("B2: atlas with all 8 triangles",
          [p["material"] for p in b2["prims"]] == ["atlas"] and tri_count(b2, "atlas") == 8)
    check("B2: TEXCOORD_0 everywhere the atlas again", uv_is(corners(b2), 0, atlas))
    check("B2: no area left -> no TEXCOORD_1, no marker",
          b2["texcoords"] == {"TEXCOORD_0"} and "av_atlas_uv" not in b2["extras"],
          f"{sorted(b2['texcoords'])} {b2['extras']}")

    print("\n[B3] manual glass on B1's file (bottom-right quad)")
    glass_faces = flat_faces_where(b1, lambda cx, cy: cx > 0 and cy < 0)
    check("B3: the bottom-right quad is 2 faces of B1's file", len(glass_faces) == 2,
          str(glass_faces))
    b3_path = run(b1_path, {"mode": "manual", "kind": "glass", "faces": glass_faces}, "B3")
    b3 = read_model(b3_path)
    check("B3: still exactly TEXCOORD_0 + TEXCOORD_1, marker 1 (backup reused)",
          b3["texcoords"] == {"TEXCOORD_0", "TEXCOORD_1"}
          and b3["extras"].get("av_atlas_uv") == 1,
          f"{sorted(b3['texcoords'])} {b3['extras']}")
    check("B3: TEXCOORD_1 everywhere the atlas", uv_is(corners(b3), 1, atlas))
    check("B3: glass faces planar (2x, -2y)",
          tri_count(b3, "slot_glass_1") == 2
          and uv_is(corners(b3, "slot_glass_1"), 0, lambda x, y: (2 * x, -2 * y)))
    check("B3: picture faces keep (2x + 1, 1 - 2y)",
          uv_is(corners(b3, "slot_picture_1"), 0, lambda x, y: (2 * x + 1, 1 - 2 * y)))

    print("\n[B4] delete picture_1 on B3's file: two round trips after the backup")
    b4 = read_model(run(b3_path, {"mode": "delete", "area": "picture_1",
                                  "origins": {"picture_1": "atlas"}}, "B4"))
    check("B4: atlas 6 triangles, slot_glass_1 2, no slot_picture_1",
          tri_count(b4, "atlas") == 6 and tri_count(b4, "slot_glass_1") == 2
          and tri_count(b4, "slot_picture_1") == 0)
    check("B4: atlas faces (the former picture ones included) back to (x + 0.5, 0.5 - y)",
          uv_is(corners(b4, "atlas"), 0, atlas))
    check("B4: glass keeps (2x, -2y)",
          uv_is(corners(b4, "slot_glass_1"), 0, lambda x, y: (2 * x, -2 * y)))
    check("B4: marker 1, TEXCOORD_1 everywhere the atlas",
          b4["extras"].get("av_atlas_uv") == 1 and uv_is(corners(b4), 1, atlas),
          str(b4["extras"]))

    print("\n[C] a split from before the marker")
    old = write("C.glb", layered_glb(SPLIT_PRIMS, [split_uv0, lambda n, x, y: atlas(x, y)]))
    delete = {"mode": "delete", "area": "picture_1", "origins": {"picture_1": "atlas"}}
    c1 = read_model(run(old, {**delete, "unmarked_backup_is_last_layer": True}, "C1"))
    check("C1: atlas 6 triangles, slot_glass_1 2, no slot_picture_1",
          tri_count(c1, "atlas") == 6 and tri_count(c1, "slot_glass_1") == 2
          and tri_count(c1, "slot_picture_1") == 0)
    check("C1: atlas faces (the former picture ones included) read (x + 0.5, 0.5 - y)",
          uv_is(corners(c1, "atlas"), 0, atlas))
    check("C1: glass keeps (2x, -2y)",
          uv_is(corners(c1, "slot_glass_1"), 0, lambda x, y: (2 * x, -2 * y)))
    check("C1: migrated — marker 1, TEXCOORD_1 everywhere the atlas",
          c1["extras"].get("av_atlas_uv") == 1 and uv_is(corners(c1), 1, atlas)
          and c1["texcoords"] == {"TEXCOORD_0", "TEXCOORD_1"},
          f"{c1['extras']} {sorted(c1['texcoords'])}")
    c2 = read_model(run(old, delete, "C2"))
    def picture_quad(m):
        """Corners of the atlas triangles whose centroid lies in q(0,1) (x < 0, y > 0)."""
        return [c for p in m["prims"] if p["material"] == "atlas" for t in p["tris"]
                if sum(c[0][0] for c in t) < 0 and sum(c[0][1] for c in t) > 0 for c in t]
    check("C2: without the param the former picture faces keep (2x + 1, 1 - 2y)",
          len(picture_quad(c2)) == 6
          and uv_is(picture_quad(c2), 0, lambda x, y: (2 * x + 1, 1 - 2 * y)),
          str(len(picture_quad(c2))))
    check("C2: TEXCOORD_1 an ordinary layer (atlas everywhere), no marker",
          uv_is(corners(c2), 1, atlas) and "av_atlas_uv" not in c2["extras"], str(c2["extras"]))

    marked = write("C3.glb", layered_glb(
        SPLIT_PRIMS, [split_uv0, lambda n, x, y: atlas(x, y), lambda n, x, y: (0.25, 0.75)],
        extras={"av_atlas_uv": 1}))
    c3 = read_model(run(marked, {**delete, "unmarked_backup_is_last_layer": True}, "C3"))
    check("C3: marked file — picture faces restored from layer 1, not the last layer",
          len(picture_quad(c3)) == 6 and uv_is(picture_quad(c3), 0, atlas), str(len(picture_quad(c3))))
    check("C3: marker still 1, TEXCOORD_2 still (0.25, 0.75)",
          c3["extras"].get("av_atlas_uv") == 1
          and uv_is(corners(c3), 2, lambda x, y: (0.25, 0.75)), str(c3["extras"]))

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(WORLD, ignore_errors=True)
