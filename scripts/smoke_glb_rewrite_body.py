#!/usr/bin/env python3
"""Smoke: ``glb_mesh.rewrite_body_primitives`` keeps a sparse accessor's bufferViews, drops a primitive (and a mesh)
left without faces, and never stores the primitive-restart value in an index buffer (review 06#3, #5, #6).

Usage:  ./.venv/bin/python scripts/smoke_glb_rewrite_body.py

No storage, no world DB, no server: numpy on one hand-built GLB.

FIXTURE (every accessor in its own bufferView, in this order; POSITION float32 VEC3, indices UNSIGNED_SHORT):
  view/accessor  0 A.POSITION (0,0,0) (1,0,0) (0,1,0)      1 A.indices [0, 1, 2]
                 2 B.POSITION = A + (2,0,0)                  3 B.indices [0, 1, 2]
                 4 C.POSITION = A + (4,0,0)                  5 C.indices [0, 1, 2]     6 C target 0 POSITION (zeros)
                 7 Part.POSITION = A + (6,0,0)               8 Part.indices [0, 1, 2]
  sparse views   9 Part target indices  UNSIGNED_SHORT [1]   10 Part target values float32 [5, 0, 0]
                 (accessor 9 = the Part's morph target: SPARSE, no bufferView, count 3, one entry)
                11 time [0, 1] (accessor 10)   12 morph weights [0, 1] (accessor 11)
                13 translation 2 x VEC3 (accessor 12)
  meshes: 0 = [A, B] (node 0 "Body"), 1 = [C] (node 1 "BodyExtra", weights [0]), 2 = [Part] (node 2, extras
  ``attached_part`` -> not a body primitive). Node 3 "Root" has no mesh. Animations: "Morph" = one channel on node 1
  ``weights``; "Move" = one channel on node 3 ``translation``. Body primitive order: A = 0, B = 1, C = 2.

Expected, by hand:
[S] rewrite {0: A with positions x 2}: A's views 0 and 1 are dropped (only A used them), so every later view moves
    down by 2 and A's two new views go last. The Part's sparse target must name the views that hold ITS bytes: the
    indices view's bytes are ``01 00`` and the values view's bytes are float32 (5, 0, 0); decoded densely (zeros base,
    entry 1 replaced) the target is [[0,0,0], [5,0,0], [0,0,0]]. The old code left the sparse refs at 9 / 10, i.e. on
    the time view [0, 1] (read as index 0) and the 8-byte weights view (too short for one VEC3 float32 = 12 bytes):
    it raised "Sparse geometry accessor is truncated or invalid" (or decoded foreign bytes).
[E1] rewrite {1: B with no face}: B is removed from mesh 0, which keeps A alone; no accessor has ``count`` 0;
    ``body_primitive_arrays`` reads 2 primitives (A then C: positions A, A + (4,0,0)) and ``body_arrays`` 6 vertices
    / 2 faces. Accessors 13 - 2 (B's POSITION + indices) = 11, views 14 - 2 = 12. The old code wrote an index
    accessor with ``count`` 0, which ``accessor_array`` refuses: ``body_arrays`` raised.
[E2] rewrite {2: C with no face}: mesh 1 is left without a primitive and goes: 2 meshes; node 1 keeps its name but
    has no ``mesh`` / ``weights``; node 2 (the part) now names mesh 1; animation "Morph" (its only channel drove node
    1's weights) is gone, "Move" stays with its channel on node 3. Body primitives A, B (positions A, A + (2,0,0)); the
    part's sparse target still decodes [[0,0,0], [5,0,0], [0,0,0]]. Accessors 13 - 3 (C's POSITION, indices,
    target) = 10.
[E3] rewrite {0, 1, 2: no face}: ValueError "The rewrite leaves the body without a face" (nothing a reader takes).
[R] restart value: ``_int_component(v, original, indices=True)`` must stay BELOW the type's maximum: [65535] with
    5123 -> 5125, [65534] with 5123 -> 5123, [255] with 5121 -> 5123, [254] with 5121 -> 5121; a vertex attribute
    (JOINTS_0, ``indices`` False) may use the maximum: [65535] with 5123 -> 5123, [255] with 5121 -> 5121. Through the
    rewrite: A replaced by 65536 vertices (x = i) with the face [0, 1, 65535] stores UNSIGNED_INT indices read back as
    [0, 1, 65535]; with 65535 vertices and [0, 1, 65534] the UNSIGNED_SHORT stays. The old code kept 5123 for 65535.
"""
from __future__ import annotations

import struct
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import glb_mesh  # noqa: E402
from app.core.model_validate import parse_glb  # noqa: E402

FAILED: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILED.append(label)


TRI = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32)
SPARSE_TARGET = [[0.0, 0.0, 0.0], [5.0, 0.0, 0.0], [0.0, 0.0, 0.0]]


def fixture() -> bytes:
    binary = bytearray()
    views: list = []
    accessors: list = []

    def view(raw: bytes) -> int:
        binary.extend(b"\0" * (-len(binary) % 4))
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(raw)})
        binary.extend(raw)
        return len(views) - 1

    def acc(arr: np.ndarray, component: int, kind: str, minmax: bool = False) -> int:
        entry = {"bufferView": view(arr.tobytes()), "componentType": component, "count": len(arr), "type": kind}
        if minmax:
            entry["min"], entry["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accessors.append(entry)
        return len(accessors) - 1

    idx = np.array([0, 1, 2], "<u2")
    prims = {}
    for name, dx in (("A", 0), ("B", 2), ("C", 4)):
        prims[name] = {"attributes": {"POSITION": acc(TRI + np.float32([dx, 0, 0]), 5126, "VEC3", True)},
                       "indices": acc(idx, 5123, "SCALAR")}
        if name == "C":
            prims[name]["targets"] = [{"POSITION": acc(np.zeros((3, 3), np.float32), 5126, "VEC3", True)}]
    part = {"attributes": {"POSITION": acc(TRI + np.float32([6, 0, 0]), 5126, "VEC3", True)},
            "indices": acc(idx, 5123, "SCALAR")}
    si = view(np.array([1], "<u2").tobytes())
    sv = view(np.array([[5, 0, 0]], "<f4").tobytes())
    accessors.append({"componentType": 5126, "count": 3, "type": "VEC3", "min": [0, 0, 0], "max": [5, 0, 0],
                      "sparse": {"count": 1, "indices": {"bufferView": si, "componentType": 5123},
                                 "values": {"bufferView": sv}}})
    part["targets"] = [{"POSITION": len(accessors) - 1}]
    t = acc(np.array([[0.0], [1.0]], "<f4"), 5126, "SCALAR", True)
    w = acc(np.array([[0.0], [1.0]], "<f4"), 5126, "SCALAR")
    move = acc(np.zeros((2, 3), "<f4"), 5126, "VEC3")
    gltf = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0, 1, 2, 3]}],
            "nodes": [{"name": "Body", "mesh": 0}, {"name": "BodyExtra", "mesh": 1, "weights": [0.0]},
                      {"name": "Part", "mesh": 2, "extras": {"attached_part": {}}}, {"name": "Root"}],
            "meshes": [{"primitives": [prims["A"], prims["B"]]}, {"primitives": [prims["C"]], "weights": [0.0]},
                       {"primitives": [part]}],
            "animations": [{"name": "Morph", "samplers": [{"input": t, "output": w}],
                            "channels": [{"sampler": 0, "target": {"node": 1, "path": "weights"}}]},
                           {"name": "Move", "samplers": [{"input": t, "output": move}],
                            "channels": [{"sampler": 0, "target": {"node": 3, "path": "translation"}}]}],
            "bufferViews": views, "accessors": accessors, "buffers": [{"byteLength": len(binary)}]}
    return glb_mesh.pack_glb(gltf, bytes(binary))


def part_target(glb: bytes):
    parsed = parse_glb(glb)
    gltf = parsed["gltf"]
    node = next(n for n in gltf["nodes"] if n.get("name") == "Part")
    index = gltf["meshes"][node["mesh"]]["primitives"][0]["targets"][0]["POSITION"]
    return parsed, gltf["accessors"][index]["sparse"], glb_mesh.accessor_array(parsed, index).tolist()


def view_bytes(parsed: dict, index: int) -> bytes:
    view = parsed["gltf"]["bufferViews"][index]
    start = int(view.get("byteOffset", 0))
    return bytes(parsed["bin"][start:start + int(view["byteLength"])])


def main() -> int:
    glb = fixture()
    prims = glb_mesh.body_primitive_arrays(glb)
    check("fixture: 3 body primitives A, B, C", len(prims) == 3
          and [float(p.positions[0, 0]) for p in prims] == [0.0, 2.0, 4.0])
    check("fixture: the part's sparse target decodes", part_target(glb)[2] == SPARSE_TARGET)

    print("[S] sparse accessor bufferViews follow the repack")
    try:
        out = glb_mesh.rewrite_body_primitives(glb, {0: replace(prims[0], positions=prims[0].positions * 2)})
        parsed, sparse, target = part_target(out)
        check("target decodes [[0,0,0],[5,0,0],[0,0,0]]", target == SPARSE_TARGET, str(target))
        check("sparse indices view holds 01 00", view_bytes(parsed, sparse["indices"]["bufferView"]) == b"\x01\x00")
        check("sparse values view holds (5, 0, 0)",
              view_bytes(parsed, sparse["values"]["bufferView"]) == struct.pack("<3f", 5, 0, 0))
        check("A rewritten (x 2)", glb_mesh.body_primitive_arrays(out)[0].positions[1].tolist() == [2.0, 0.0, 0.0])
    except ValueError as exc:
        check("rewrite + read of the sparse target", False, str(exc))

    print("[E1] a primitive emptied in a two-primitive mesh")
    try:
        out = glb_mesh.rewrite_body_primitives(glb, {1: replace(prims[1], faces=np.zeros((0, 3), np.int64))})
        gltf = parse_glb(out)["gltf"]
        check("mesh 0 keeps one primitive", len(gltf["meshes"][0]["primitives"]) == 1)
        check("no accessor with count 0", all(int(a["count"]) > 0 for a in gltf["accessors"]))
        check("11 accessors, 12 views", (len(gltf["accessors"]), len(gltf["bufferViews"])) == (11, 12),
              str((len(gltf["accessors"]), len(gltf["bufferViews"]))))
        back = glb_mesh.body_primitive_arrays(out)
        check("body primitives A, C", [float(p.positions[0, 0]) for p in back] == [0.0, 4.0])
        body = glb_mesh.body_arrays(out)
        check("body_arrays: 6 vertices, 2 faces", (len(body.positions), len(body.faces)) == (6, 2))
    except ValueError as exc:
        check("rewrite + read with an emptied primitive", False, str(exc))

    print("[E2] a mesh left without primitives")
    try:
        out = glb_mesh.rewrite_body_primitives(glb, {2: replace(prims[2], faces=np.zeros((0, 3), np.int64))})
        gltf = parse_glb(out)["gltf"]
        nodes = {n["name"]: n for n in gltf["nodes"]}
        check("2 meshes", len(gltf["meshes"]) == 2)
        check("node BodyExtra kept without mesh / weights",
              "BodyExtra" in nodes and not {"mesh", "skin", "weights"} & set(nodes["BodyExtra"]))
        check("the part names mesh 1", nodes["Part"].get("mesh") == 1)
        check("animation Morph gone, Move kept on node 3",
              [(a["name"], [c["target"] for c in a["channels"]]) for a in gltf.get("animations") or []]
              == [("Move", [{"node": 3, "path": "translation"}])])
        check("10 accessors", len(gltf["accessors"]) == 10, str(len(gltf["accessors"])))
        back = glb_mesh.body_primitive_arrays(out)
        check("body primitives A, B", [float(p.positions[0, 0]) for p in back] == [0.0, 2.0])
        check("the part's sparse target still decodes", part_target(out)[2] == SPARSE_TARGET)
    except ValueError as exc:
        check("rewrite + read with an emptied mesh", False, str(exc))

    print("[E3] every body face removed")
    empty = {i: replace(p, faces=np.zeros((0, 3), np.int64)) for i, p in enumerate(prims)}
    try:
        glb_mesh.rewrite_body_primitives(glb, empty)
        check("ValueError", False, "no error")
    except ValueError as exc:
        check("ValueError 'without a face'", "without a face" in str(exc), str(exc))

    print("[R] the primitive-restart value never lands in an index buffer")
    ic = glb_mesh._int_component
    for values, original, indices, expected in (([65535], 5123, True, 5125), ([65534], 5123, True, 5123),
                                                ([255], 5121, True, 5123), ([254], 5121, True, 5121),
                                                ([65535], 5123, False, 5123), ([255], 5121, False, 5121)):
        got = ic(np.array(values), original, indices=indices)
        check(f"_int_component({values}, {original}, indices={indices}) == {expected}", got == expected, str(got))
    for n, top, component in ((65536, 65535, 5125), (65535, 65534, 5123)):
        P = np.zeros((n, 3))
        P[:, 0] = np.arange(n)
        out = glb_mesh.rewrite_body_primitives(glb, {0: replace(prims[0], positions=P,
                                                                faces=np.array([[0, 1, top]], np.int64))})
        parsed = parse_glb(out)
        index = parsed["gltf"]["meshes"][0]["primitives"][0]["indices"]
        got = parsed["gltf"]["accessors"][index]["componentType"]
        flat = glb_mesh.accessor_array(parsed, index).reshape(-1).tolist()
        check(f"{n} vertices, face [0, 1, {top}] -> component {component}, read back",
              got == component and flat == [0, 1, top], f"{got} {flat}")

    print("PASS" if not FAILED else f"FAILED: {len(FAILED)} — {FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
