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

THE FIXTURE (glTF y-up, written with the stdlib), `plate_glb(n)`:
  A 1 m x 1 m plate in the xy plane at z = 0, facing +z: (n+1)x(n+1) vertices
  at x, y = -0.5 + i/n; n*n quads of (1/n) m, each two CCW triangles -> 2n²
  triangles, one mesh, one material "atlas" with a 64x64 PNG.
  UVs (glTF, v top-down): u = x + 0.5, v = 0.5 - y.
  The PNG is grey (128,128,128) except a pure green (0,255,0) block over
  columns 0..31 and rows 0..31 (the top-left quarter) -> u < 0.5, v < 0.5
  -> x < 0 and y > 0 -> exactly the TOP-LEFT QUARTER of the plate.
  n = 2 (parts A–C): four quads, the green quarter is ONE quad = 2 triangles,
    fixture order q(0,0)=0,1  q(1,0)=2,3  q(0,1)=4,5  q(1,1)=6,7
    (q(i,j): i along x, j along y; quad (0,1) is the top-left one).
  n = 8 (parts D–F, the production filter): 64 quads = 128 triangles; the
    green quarter is 4x4 quads = 32 triangles, 0.25 m² (both above the
    12-face / 0.02 m² filter); its outline is 4 quad edges per side = 16
    boundary edges; size_m [0.5, 0.5], normal [0, 0, 1].

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
  FILE sidecar `areas` (spec-bild-props-v2.md E1): one entry, id "picture_1", kind "picture",
    size_m [0.5, 0.5], normal [0,0,1], source "auto", faces 2.
  `<model>.areas.json`: picture_1 has 4 boundary edges (the quad's outline;
    the diagonal is shared by both triangles and drops out); mesh_layout has
    ONE mesh with tri_count 8.
  Slots: `_autofill_slots` -> [{"name": "picture_1", "kind": "image"}].
  Gallery: the result is a NEW file, selected; the original stays stored as
    history and NO raw/ copy is made (ruling R6 — that rule is for in-place
    refinements).

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

[D] THE LANDING HOOK — upload on a prop created with key_areas=["picture"]
  `save_uploaded_glb(plate_glb(8))` WITHOUT calling detect_areas: the active
  model is a second gallery file (the upload + the split) carrying
  "slot_picture_1" with 32 triangles, "atlas" 96; sidecar areas = one entry
  (picture_1, auto, faces 32, size_m [0.5, 0.5]), `areas_error` absent,
  `areas_run_at` set; `.areas.json` has 16 edges, mesh_layout tri_count 128.
  NOT a landing: `select_model(<the uploaded original>)` re-points the
  selection and does NOT split again (file count stays 2, the active file is
  the original) — the sidecar areas RECONCILE to [] (the original names no
  slot material); selecting the split file back brings the list back from
  its own `.areas.json` (one entry, picture_1).

[E] THE HOOK NEVER FAILS A LANDING — `runner.run` patched to raise for the
  `picture_areas` script only: `save_uploaded_glb` still returns True, the
  uploaded file is the active one, sidecar `areas == []` and `areas_error`
  carries the message.

[F] THE GENERATION CHAIN — `_generate(mesh_only=True)` with the img2mesh
  service faked to write plate_glb(8) into the output path (the pattern of
  smoke_props_slots [3b]; no image backend is needed for a re-mesh): the
  active model carries "slot_picture_1" with 32 triangles, sidecar areas one
  entry, slots [{picture_1, image}].

[G] AN AUTOMATIC RUN KEEPS WHAT THE ADMIN DREW (ruling R14)
  On plate_glb(8), the BOTTOM-RIGHT quarter (x > 0, y < 0 — grey, so the
  detector would never find it) is drawn by hand as kind "glass": 4x4 quads =
  32 triangles, `source "manual"`. An `auto` run afterwards therefore has one
  auto area to find (the green quarter) and one manual area to leave alone:

    areas -> [(picture_1, auto, 32), (glass_1, manual, 32)]   (kind order)
    mesh  -> slot_picture_1 32 tris, slot_glass_1 32 tris, atlas 128-64 = 64

  glass_1 keeps its id (so `_next_k` stepped over the number), its faces and
  its planar UVs. Its frame is the same as [A]'s — n = (0,0,1), u = (1,0,0),
  v = (0,1,0) — over the bbox x in [0, 0.5], y in [-0.5, 0]: u = (x-0)/0.5 =
  2x, v_blender = (y+0.5)/0.5, glTF v = 1 - v_blender = -2y.

[H] A SPLIT FILE CAN BE DETECTED AGAIN AFTER ITS OWN ROUND TRIP
  `plate_glb(8, 0.002)`: every second grid vertex sits 2 mm proud, so all
  POSITIONS stay shared between the quads that meet at them while every
  triangle gets its own normal — an ordinary img2mesh surface. glTF stores one
  vertex per (position, normal, uv) triple, so Blender's export duplicates
  every vertex of the panel per adjoining face and the re-imported file shares
  no index between two faces of it. Raw indices would break the green quarter
  into 32 one-face components, every one of them below the 12-face filter, and
  the second run would report NO area. With the (position, uv) weld the quarter
  is one patch again:

    run 1 (the landing hook splits the upload)  -> picture_1, 32 faces
    run 2 (`auto` on the file run 1 exported)   -> picture_1, 32 faces
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



def file_meta(pid: str) -> dict:
    """The ACTIVE full mesh's own sidecar — where the areas, the run stamp and
    the error of a run live since spec-bild-props-v2.md E1."""
    return store.read_model_sidecar(store.model_gallery(pid).find(store.DEFAULT_TIER, fallback=False))

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


def plate_glb(n: int = 2, bump: float = 0.0) -> bytes:
    """The plate. ``bump`` lifts every second grid vertex by that many metres
    (a checkerboard), which leaves every POSITION shared between the quads
    that meet at it but gives every triangle its OWN normal — the shape of an
    img2mesh surface, and the reason a round trip needs a weld (part [H])."""
    positions, uvs = [], []
    for j in range(n + 1):
        for i in range(n + 1):
            x, y = -0.5 + i / n, -0.5 + j / n
            positions.append((x, y, bump if (i + j) % 2 else -bump))
            uvs.append((x + 0.5, 0.5 - y))
    indices = []
    for j in range(n):
        for i in range(n):
            a, b = j * (n + 1) + i, j * (n + 1) + i + 1
            c, d = (j + 1) * (n + 1) + i + 1, (j + 1) * (n + 1) + i
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
            {"bufferView": 0, "componentType": 5126, "count": len(positions),
             "type": "VEC3", "min": [-0.5, -0.5, -bump], "max": [0.5, 0.5, bump]},
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


class FakeMeshService:
    """Just enough of the image service for `props._generate`: `generate_mesh`
    writes the GLB it is given a path for and reports the run."""

    def __init__(self, blob: bytes) -> None:
        self.blob = blob

    def generate_mesh(self, *, output_path: str, **_kw) -> dict:
        Path(output_path).write_bytes(self.blob)
        return {"ok": True, "path": output_path, "format": "glb",
                "rig": "none", "backend": "fake-mesh"}


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
    check("no raw/ copy (R6)", not (original.parent / "raw").exists())
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
    meta = file_meta(pid)
    check("FILE sidecar areas == the returned list", meta.get("areas") == areas)
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

    print("\n[D] the landing hook: an upload on a key_areas prop splits itself")
    kp = store.create_prop(name="Keyed frame", key_areas=["picture"])["id"]
    check("upload lands", store.save_uploaded_glb(kp, plate_glb(8)))
    kg = store.model_gallery(kp)
    files = kg.files()
    active = store.model_path(kp)
    uploaded = next((f for f in files if f != active), None)
    check("two gallery files: the upload and the split", len(files) == 2, str([f.name for f in files]))
    prims = primitives(active)
    check("the ACTIVE model carries slot_picture_1 with 32 triangles",
          tri_count(prims, "slot_picture_1") == 32, str(tri_count(prims, "slot_picture_1")))
    check("atlas 96", tri_count(prims, "atlas") == 96, str(tri_count(prims, "atlas")))
    meta = file_meta(kp)
    ka = meta.get("areas") or []
    check("sidecar: one area picture_1/auto/32 faces",
          len(ka) == 1 and (ka[0]["id"], ka[0]["source"], ka[0]["faces"]) == ("picture_1", "auto", 32),
          str(ka))
    check("size_m [0.5, 0.5]", ka and near(ka[0]["size_m"][0], 0.5) and near(ka[0]["size_m"][1], 0.5))
    check("areas_error absent", "areas_error" not in meta, str(meta.get("areas_error")))
    check("areas_run_at set", bool(meta.get("areas_run_at")))
    extra = json.loads(store.areas_sidecar_path(active).read_text(encoding="utf-8"))
    check("16 boundary edges", len(extra["areas"][0]["edges"]) == 16, str(len(extra["areas"][0]["edges"])))
    check("mesh_layout tri_count 128", extra["mesh_layout"][0]["tri_count"] == 128, str(extra["mesh_layout"]))
    check("select_model of the original does NOT split again",
          uploaded is not None and store.select_model(kp, uploaded.name)
          and store.model_path(kp) == uploaded and len(store.model_gallery(kp).files()) == 2,
          str([f.name for f in store.model_gallery(kp).files()]))
    check("…and the areas reconcile to [] (the original names no slot material)",
          file_meta(kp).get("areas") == [], str(file_meta(kp).get("areas")))
    store.select_model(kp, active.name)
    back = file_meta(kp).get("areas") or []
    check("selecting the split file back brings its area list back",
          [a["id"] for a in back] == ["picture_1"] and len(store.model_gallery(kp).files()) == 2, str(back))

    print("\n[E] the hook never fails a landing")
    from app.blender import runner
    real_run = runner.run

    def failing_run(script, **kw):
        if script == "picture_areas":
            raise RuntimeError("boom: simulated blender failure")
        return real_run(script, **kw)

    runner.run = failing_run
    try:
        ep = store.create_prop(name="Doomed frame", key_areas=["picture"])["id"]
        ok = store.save_uploaded_glb(ep, plate_glb(8))
    finally:
        runner.run = real_run
    check("save_uploaded_glb still returns True", ok is True, str(ok))
    check("the uploaded file is the active model", len(store.model_gallery(ep).files()) == 1)
    emeta = file_meta(ep)
    check("sidecar areas == []", emeta.get("areas") == [], str(emeta.get("areas")))
    check("areas_error carries the message", "boom" in str(emeta.get("areas_error")), str(emeta.get("areas_error")))
    check("areas_info reports it", "boom" in store.areas_info(ep)["error"])

    print("\n[F] the generation chain hooks the split as well")
    import app.imagegen.service as image_service
    real_service = image_service.get_image_service
    image_service.get_image_service = lambda: FakeMeshService(plate_glb(8))
    try:
        gp = store.create_prop(name="Generated frame", key_areas=["picture"])["id"]
        (store.prop_dir(gp, create=True) / store.SOURCE_NAME).write_bytes(b"\x89PNG fake")
        out = store._generate(gp, "", "", "", "fake-mesh", mesh_only=True, variant=0)
    finally:
        image_service.get_image_service = real_service
    check("the chain succeeded", out.get("ok") is True, str(out))
    prims = primitives(store.model_path(gp))
    check("the active model carries slot_picture_1 with 32 triangles",
          tri_count(prims, "slot_picture_1") == 32, str(tri_count(prims, "slot_picture_1")))
    gmeta = file_meta(gp)
    check("sidecar: one area", [a["id"] for a in gmeta.get("areas") or []] == ["picture_1"], str(gmeta.get("areas")))
    check("slots: picture_1 image", store.get_prop(gp)["slots"] == [{"name": "picture_1", "kind": "image"}])

    print("\n[G] an automatic run keeps what the ADMIN drew (R14)")
    gp = store.create_prop(name="Drawn frame", category="decor")["id"]
    store.save_uploaded_glb(gp, plate_glb(8))
    up = store.model_path(gp)
    drawn = flat_faces_where(primitives(up), lambda cx, cy: cx > 0 and cy < 0)
    check("the bottom-right quarter is 32 flat faces", len(drawn) == 32, str(len(drawn)))
    areas = store.detect_areas(gp, mode="manual", faces=drawn, kind="glass")
    check("the drawn area is glass_1, source manual, 32 faces",
          [(a["id"], a["source"], a["faces"]) for a in areas]
          == [("glass_1", "manual", 32)], str(areas))
    areas = store.detect_areas(gp, mode="auto")
    ids = [(a["id"], a["source"], a["faces"]) for a in areas]
    check("auto adds the green panel and LEAVES the drawn one standing",
          ids == [("picture_1", "auto", 32), ("glass_1", "manual", 32)], str(ids))
    prims = primitives(store.model_path(gp))
    check("the mesh carries both materials, 32 triangles each",
          tri_count(prims, "slot_picture_1") == 32
          and tri_count(prims, "slot_glass_1") == 32,
          str((tri_count(prims, "slot_picture_1"), tri_count(prims, "slot_glass_1"))))
    check("…and the drawn area kept its planar UVs (u = 2x, v = -2y)",
          uv_rule_holds(prims, "slot_glass_1", lambda x, y: (2 * x, -2 * y)))
    check("atlas 64", tri_count(prims, "atlas") == 64, str(tri_count(prims, "atlas")))

    print("\n[H] a split file can be detected again after its own round trip")
    hp = store.create_prop(name="Bumpy frame", key_areas=["picture"])["id"]
    check("the landing splits the bumpy plate", store.save_uploaded_glb(hp, plate_glb(8, 0.002)))
    first = file_meta(hp).get("areas") or []
    check("run 1: picture_1 with 32 faces",
          [(a["id"], a["faces"]) for a in first] == [("picture_1", 32)], str(first))
    areas = store.detect_areas(hp, mode="auto")
    check("run 2 on the EXPORTED file: still one area of 32 faces",
          [(a["id"], a["faces"]) for a in areas] == [("picture_1", 32)], str(areas))
    prims = primitives(store.model_path(hp))
    check("…and the mesh really carries them", tri_count(prims, "slot_picture_1") == 32,
          str(tri_count(prims, "slot_picture_1")))

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
