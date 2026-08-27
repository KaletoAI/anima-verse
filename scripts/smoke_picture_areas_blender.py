#!/usr/bin/env python3
"""Blender integration run for the picture-area SPLIT (spec-picture-props.md
§ 2, plan task 3): a key-coloured patch on the atlas becomes a slot material
with planar UVs, the manual face list becomes a second one, and a delete puts
the faces back.

Usage:  ./.venv/bin/python scripts/smoke_picture_areas_blender.py

Needs Blender (``refine.unavailable_reason()`` empty); otherwise prints
"skipped: Blender unavailable (<reason>)" and exits 0. Throw-away storage in
/tmp, no world, no DB, no server. Every expected number below is derived BY
HAND from the fixture and the spec, never recorded from a run.

THE FIXTURE (glTF y-up, written with the stdlib):
  A 1 m x 1 m plate in the xy plane at z = 0, facing +z: 3x3 vertices at
  x, y in {-0.5, 0, 0.5}; four quads of 0.5 m x 0.5 m, each two CCW triangles
  -> 8 triangles, one mesh, one material "atlas" with a 64x64 PNG.
  UVs (glTF, v top-down): u = x + 0.5, v = 0.5 - y.
  The PNG is grey (128,128,128) except a pure green (0,255,0) block over
  columns 0..31 and rows 0..31 (the top-left quarter) -> u < 0.5, v < 0.5
  -> x < 0 and y > 0 -> exactly the TOP-LEFT quad (fixture triangles 4, 5).
  Fixture triangle order: q(0,0)=0,1  q(1,0)=2,3  q(0,1)=4,5  q(1,1)=6,7
  (q(i,j): i along x, j along y, quad (0,1) is the top-left one).

[A] AUTO — `detect_areas(pid, mode="auto", min_faces=2)`
  (min_faces lowered from the production 12: the fixture quad has 2 faces;
  min_area_m2 stays 0.02 and the quad's 0.25 m² passes it.)
  Result GLB:
    materials contain "slot_picture_1"; exactly 2 triangles use it; the
    origin material "atlas" keeps 6.
    Planar UVs on the picture faces: frame of n=(0,0,1) is u=(1,0,0),
    v=(0,1,0); u = (x+0.5)/0.5, v_blender = (y-0)/0.5, glTF v = 1 - v_blender
    -> corner (-0.5,0)->(0,1), (0,0)->(1,1), (0,0.5)->(1,0), (-0.5,0.5)->(0,0)
    i.e. every picture vertex has (u, v) = (2x+1, 1-2y).
    TEXCOORD_1 (the atlas backup layer) is present on the split file.
  Sidecar `areas`: one entry, id "picture_1", kind "picture",
    size_m [0.5, 0.5], normal [0,0,1], source "auto", faces 2.
  `<model>.areas.json`: picture_1 has 4 boundary edges (the quad's outline;
    the diagonal is shared by both triangles and drops out); mesh_layout has
    ONE mesh with tri_count 8.
  Slots: `_autofill_slots` -> [{"name": "picture_1", "kind": "image"}].
  Gallery: the result is a NEW file, selected; the original stays stored and
    a copy sits under raw/.

[B] MANUAL — the bottom-right quad (x > 0, y < 0) as kind "glass"
  Its two flat face indices are taken off the [A] result by R1: flat index =
  position in the concatenation of the mesh's primitives (the importer merges
  them in order), and the two triangles are the ones whose centroid has
  x > 0 and y < 0.
  Result: "slot_glass_1" with 2 triangles, "slot_picture_1" keeps its 2,
  "atlas" 4. Sidecar areas: picture_1 (auto) and glass_1 (manual, faces 2,
  size_m [0.5, 0.5]). Slots: picture_1 image, glass_1 material.

[C] DELETE — `delete_area(pid, "glass_1")`
  "slot_glass_1" is gone, "atlas" has 6 triangles again, "slot_picture_1"
  keeps 2; sidecar areas: picture_1 only. The restored faces carry their
  ATLAS UVs again: every vertex of the bottom-right quad has
  (u, v) = (x + 0.5, 0.5 - y) — that is what the backup layer is for.
"""
import json
import os
import struct
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="picture-areas-smoke-"))
os.environ["STORAGE_DIR"] = str(WORLD)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.blender import refine  # noqa: E402
from app.core import props as store  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def near(a, b, eps=1e-4) -> bool:
    return abs(float(a) - float(b)) <= eps


# ── fixture ───────────────────────────────────────────────────────────────

def png_rgb(width: int, height: int, pixel) -> bytes:
    """A stdlib PNG: ``pixel(x, y)`` -> (r, g, b), row 0 = TOP."""
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


def atlas_png() -> bytes:
    def pixel(x, y):
        return (0, 255, 0) if x < 32 and y < 32 else (128, 128, 128)
    return png_rgb(64, 64, pixel)


def plate_glb() -> bytes:
    positions, uvs = [], []
    for j in range(3):
        for i in range(3):
            x, y = -0.5 + 0.5 * i, -0.5 + 0.5 * j
            positions.append((x, y, 0.0))
            uvs.append((x + 0.5, 0.5 - y))
    indices = []
    for j in range(2):
        for i in range(2):
            a, b = j * 3 + i, j * 3 + i + 1
            c, d = (j + 1) * 3 + i + 1, (j + 1) * 3 + i
            indices += [a, b, c, a, c, d]
    pos = b"".join(struct.pack("<fff", *p) for p in positions)
    tex = b"".join(struct.pack("<ff", *t) for t in uvs)
    idx = b"".join(struct.pack("<H", i) for i in indices)
    idx += b"\0" * ((4 - len(idx) % 4) % 4)
    png = atlas_png()
    png += b"\0" * ((4 - len(png) % 4) % 4)
    blob = pos + tex + idx + png
    views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": len(pos), "target": 34962},
        {"buffer": 0, "byteOffset": len(pos), "byteLength": len(tex), "target": 34962},
        {"buffer": 0, "byteOffset": len(pos) + len(tex), "byteLength": len(indices) * 2,
         "target": 34963},
        {"buffer": 0, "byteOffset": len(pos) + len(tex) + len(idx),
         "byteLength": len(atlas_png())},
    ]
    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "plate"}],
        "meshes": [{"name": "plate", "primitives": [{
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
            {"bufferView": 0, "componentType": 5126, "count": 9, "type": "VEC3",
             "min": [-0.5, -0.5, 0.0], "max": [0.5, 0.5, 0.0]},
            {"bufferView": 1, "componentType": 5126, "count": 9, "type": "VEC2"},
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


def primitives(path: Path):
    """[{material, tris: [((x,y,z)*3)], uvs: [((u,v)*3)], has_uv1}] in file
    order over every mesh of the scene (R1's flat order for one mesh)."""
    gltf, blob = read_glb(path.read_bytes())
    mats = [m.get("name", "") for m in gltf.get("materials", [])]
    out = []
    for mesh in gltf.get("meshes", []):
        for prim in mesh.get("primitives", []):
            attrs = prim["attributes"]
            pos = accessor(gltf, blob, attrs["POSITION"])
            uv = accessor(gltf, blob, attrs["TEXCOORD_0"]) if "TEXCOORD_0" in attrs else []
            idx = [i[0] for i in accessor(gltf, blob, prim["indices"])] if "indices" in prim \
                else list(range(len(pos)))
            tris = [tuple(pos[i] for i in idx[k:k + 3]) for k in range(0, len(idx), 3)]
            tuvs = [tuple(uv[i] for i in idx[k:k + 3]) for k in range(0, len(idx), 3)] if uv else []
            mat = mats[prim["material"]] if "material" in prim else ""
            out.append({"material": mat, "tris": tris, "uvs": tuvs,
                        "has_uv1": "TEXCOORD_1" in attrs})
    return out


def tri_count(prims, material):
    return sum(len(p["tris"]) for p in prims if p["material"] == material)


def material_names(path: Path):
    gltf, _ = read_glb(path.read_bytes())
    return [m.get("name", "") for m in gltf.get("materials", [])]


def flat_faces_where(prims, pred):
    """R1: flat triangle index over the primitives in file order."""
    out, flat = [], 0
    for p in prims:
        for t in p["tris"]:
            cx = sum(v[0] for v in t) / 3
            cy = sum(v[1] for v in t) / 3
            if pred(cx, cy):
                out.append(flat)
            flat += 1
    return out


def uv_rule_holds(prims, material, rule):
    """Every vertex of every triangle of ``material`` satisfies uv == rule(x, y)."""
    ok = True
    for p in prims:
        if p["material"] != material:
            continue
        for t, tu in zip(p["tris"], p["uvs"]):
            for (x, y, _z), (u, v) in zip(t, tu):
                eu, ev = rule(x, y)
                if not (near(u, eu) and near(v, ev)):
                    ok = False
    return ok


def main() -> int:
    reason = refine.unavailable_reason()
    if reason:
        print(f"skipped: Blender unavailable ({reason})")
        return 0

    pid = store.create_prop(name="Frame plate", category="decor")["id"]
    fixture = plate_glb()
    store.save_uploaded_glb(pid, fixture)
    original = store.model_path(pid)
    check("fixture stored", original is not None and original.exists())

    print("[A] auto detection splits the green quad")
    areas = store.detect_areas(pid, mode="auto", min_faces=2)
    check("one area detected", len(areas) == 1, str(areas))
    a = areas[0] if areas else {}
    check("id picture_1, kind picture, source auto",
          (a.get("id"), a.get("kind"), a.get("source")) == ("picture_1", "picture", "auto"),
          str(a))
    check("faces 2", a.get("faces") == 2, str(a.get("faces")))
    check("size_m [0.5, 0.5]",
          len(a.get("size_m") or []) == 2 and near(a["size_m"][0], 0.5) and near(a["size_m"][1], 0.5),
          str(a.get("size_m")))
    check("normal [0, 0, 1]",
          all(near(x, y) for x, y in zip(a.get("normal") or [9, 9, 9], [0, 0, 1])),
          str(a.get("normal")))
    result = store.model_path(pid)
    check("the result is a NEW gallery file, selected",
          result is not None and result != original, f"{original} -> {result}")
    check("the original stays stored", original.exists())
    check("a copy of the original sits under raw/",
          (original.parent / "raw" / original.name).exists())
    prims = primitives(result)
    check("materials: atlas + slot_picture_1",
          set(material_names(result)) == {"atlas", "slot_picture_1"},
          str(material_names(result)))
    check("exactly 2 triangles use slot_picture_1",
          tri_count(prims, "slot_picture_1") == 2, str(tri_count(prims, "slot_picture_1")))
    check("atlas keeps 6", tri_count(prims, "atlas") == 6, str(tri_count(prims, "atlas")))
    check("picture faces carry planar UVs (2x+1, 1-2y)",
          uv_rule_holds(prims, "slot_picture_1", lambda x, y: (2 * x + 1, 1 - 2 * y)))
    check("atlas faces keep their atlas UVs (x+0.5, 0.5-y)",
          uv_rule_holds(prims, "atlas", lambda x, y: (x + 0.5, 0.5 - y)))
    check("the atlas backup layer TEXCOORD_1 is present",
          all(p["has_uv1"] for p in prims))
    meta = store.read_sidecar(pid)
    check("sidecar areas == the returned list", meta.get("areas") == areas)
    check("sidecar areas_error empty", not meta.get("areas_error"), str(meta.get("areas_error")))
    side = store.areas_sidecar_path(result)
    check("<model>.areas.json exists", side is not None and side.exists(), str(side))
    extra = json.loads(side.read_text(encoding="utf-8")) if side and side.exists() else {}
    edges = {e["id"]: e.get("edges") for e in extra.get("areas", [])}
    check("picture_1 has 4 boundary edges", len(edges.get("picture_1") or []) == 4,
          str(len(edges.get("picture_1") or [])))
    layout = extra.get("mesh_layout") or []
    check("mesh_layout: one mesh of 8 triangles",
          len(layout) == 1 and layout[0].get("tri_count") == 8, str(layout))
    rec = store.get_prop(pid)
    check("slots: picture_1 image (autofill)",
          rec["slots"] == [{"name": "picture_1", "kind": "image"}], str(rec["slots"]))
    info = store.areas_info(pid)
    check("areas_info: edges + mesh_layout + blender + last_run",
          set(info) >= {"areas", "mesh_layout", "blender", "last_run"}
          and info["blender"].get("available") is True
          and len(info["areas"][0].get("edges") or []) == 4 and info["last_run"],
          str({k: (v if k != "areas" else "…") for k, v in info.items()}))

    print("\n[B] a manual face list becomes a glass area")
    faces = flat_faces_where(prims, lambda cx, cy: cx > 0 and cy < 0)
    check("the bottom-right quad is two flat faces", len(faces) == 2, str(faces))
    areas = store.detect_areas(pid, mode="manual", faces=faces, kind="glass")
    ids = [(x["id"], x["source"], x["faces"]) for x in areas]
    check("areas: picture_1 kept, glass_1 added",
          ids == [("picture_1", "auto", 2), ("glass_1", "manual", 2)], str(ids))
    g = next((x for x in areas if x["id"] == "glass_1"), {})
    check("glass_1 size_m [0.5, 0.5]",
          len(g.get("size_m") or []) == 2 and near(g["size_m"][0], 0.5) and near(g["size_m"][1], 0.5),
          str(g.get("size_m")))
    result2 = store.model_path(pid)
    check("another NEW gallery file", result2 != result)
    prims = primitives(result2)
    check("slot_glass_1 has 2 triangles", tri_count(prims, "slot_glass_1") == 2,
          str(tri_count(prims, "slot_glass_1")))
    check("slot_picture_1 still 2", tri_count(prims, "slot_picture_1") == 2)
    check("atlas 4", tri_count(prims, "atlas") == 4, str(tri_count(prims, "atlas")))
    check("picture faces keep their planar UVs",
          uv_rule_holds(prims, "slot_picture_1", lambda x, y: (2 * x + 1, 1 - 2 * y)))
    rec = store.get_prop(pid)
    check("slots: picture_1 image, glass_1 material",
          rec["slots"] == [{"name": "picture_1", "kind": "image"},
                           {"name": "glass_1", "kind": "material"}], str(rec["slots"]))

    print("\n[C] deleting the glass area puts its faces back")
    areas = store.delete_area(pid, "glass_1")
    check("areas: picture_1 only", [x["id"] for x in areas] == ["picture_1"], str(areas))
    result3 = store.model_path(pid)
    prims = primitives(result3)
    check("slot_glass_1 is gone", "slot_glass_1" not in material_names(result3),
          str(material_names(result3)))
    check("atlas has 6 again", tri_count(prims, "atlas") == 6, str(tri_count(prims, "atlas")))
    check("slot_picture_1 keeps 2", tri_count(prims, "slot_picture_1") == 2)
    check("restored faces carry their ATLAS UVs again",
          uv_rule_holds(prims, "atlas", lambda x, y: (x + 0.5, 0.5 - y)))
    rec = store.get_prop(pid)
    check("slots: picture_1 only",
          rec["slots"] == [{"name": "picture_1", "kind": "image"}], str(rec["slots"]))

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
