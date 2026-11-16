#!/usr/bin/env python3
"""Outward winding + vertex normals of a base body (``base_mesh_repair.orient`` / ``orient_glb``, Ruling A137).

Usage:
    ./.venv/bin/python scripts/smoke_base_mesh_orient.py

Synthetic meshes only (no world, no server, no Blender). Fixture: the icosphere of ``smoke_base_mesh_repair``
(``icosphere(r, 3)``: 642 vertices, 1280 triangles; ``icosphere(r, 2)``: 162 / 320), wound outward, NORMAL = the
unit position (outward). Expected, derived by hand:

[1] Closed, outward sphere: ``orient_glb`` returns THE SAME bytes object; components 1, closed 1, voids 0,
    faces_flipped 0, normals_fixed 0.
[2] Every 100th face reversed (faces 0, 100, ..., 1200: ceil(1280 / 100) = 13, a minority): exactly those 13 reversed back, the face
    list equals the original one; normals_fixed 0 (the stored normals never disagreed with the outward faces).
[3] All 1280 faces reversed (an inside-out shell, closed, alone): the component is closed, encloses -V and lies in
    nothing else -> all 1280 reversed, the result equals the original; voids 0.
[4] A cavity: the r = 4 cm sphere outward plus an r = 1 cm sphere (level 2) wound INWARD at its centre. The small
    shell is closed with negative volume but lies inside the big one (6 rays, each crossing the big sphere once)
    -> voids 1, faces_flipped 0. Its stored normals point outward (the unit position) — against its inward faces —
    so all 162 of its vertices get the face normal: normals_fixed 162, each now pointing to the centre
    (dot(N, P) < 0).
[5] An open piece: the faces of the sphere with centroid z > 0 (a hemisphere, open at the equator, so never
    reversed as a whole) with 3 faces reversed -> faces_flipped 3, closed 0, the face list equals the original.
    The same hemisphere reversed ENTIRELY stays as it is (faces_flipped 0): an open piece keeps its own majority; its stored normals (outward) now
    disagree with every face, so every vertex of the hemisphere gets the face normal (normals_fixed = its vertex count).
[6] Normals: 5 vertices of the outward sphere get NORMAL = -outward -> normals_fixed 5, each repaired normal has
    dot > 0.99 with the outward unit position (the area-weighted face normal of a fine icosphere); every other
    normal byte-identical.
[7] ``repair_glb`` carries the record (``record["orient"]``, status applied) and VERSION >= 3.
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from smoke_base_mesh_repair import build_glb, icosphere  # noqa: E402
from app.core import base_mesh_repair as r, glb_mesh  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + label + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)


def faces_of(glb):
    return glb_mesh.body_primitive_arrays(glb)[0]


def main() -> int:
    R = 0.04
    P, F = icosphere(R, 3)
    P, F = np.asarray(P, np.float64), np.asarray(F, np.int64)
    print("[1] closed outward sphere")
    glb = build_glb(P, F, R)
    out, rec = r.orient_glb(glb)
    check("same bytes object", out is glb)
    check("record", (rec["components"], rec["closed"], rec["voids"], rec["faces_flipped"], rec["normals_fixed"])
          == (1, 1, 0, 0, 0), str(rec))

    print("[2] every 100th face reversed")
    G = F.copy()
    G[::100] = G[::100][:, [0, 2, 1]]
    out, rec = r.orient_glb(build_glb(P, G, R))
    check("13 flipped", rec["faces_flipped"] == 13 == len(F[::100]), str(rec))
    check("faces restored", np.array_equal(faces_of(out).faces, F))
    check("no normal touched", rec["normals_fixed"] == 0)

    print("[3] inside-out sphere")
    out, rec = r.orient_glb(build_glb(P, F[:, [0, 2, 1]], R))
    check("all 1280 flipped", rec["faces_flipped"] == 1280 and rec["voids"] == 0, str(rec))
    check("faces restored", np.array_equal(faces_of(out).faces, F))

    print("[4] cavity")
    p2, f2 = icosphere(0.01, 2)
    p2, f2 = np.asarray(p2, np.float64), np.asarray(f2, np.int64)
    PP = np.concatenate([P, p2])
    FF = np.concatenate([F, f2[:, [0, 2, 1]] + len(P)])
    out, rec = r.orient_glb(build_glb(PP, FF, R))
    check("void kept", rec["voids"] == 1 and rec["faces_flipped"] == 0 and rec["closed"] == 2, str(rec))
    N = faces_of(out).attributes["NORMAL"]
    check("162 normals fixed, inward", rec["normals_fixed"] == 162 == len(p2)
          and bool((np.einsum("ij,ij->i", N[len(P):], PP[len(P):]) < 0).all()))

    print("[5] open piece")
    c = P[F].mean(1)
    H = F[c[:, 2] > 0]
    used = np.unique(H)
    remap = -np.ones(len(P), np.int64)
    remap[used] = np.arange(len(used))
    PH, H = P[used], remap[H]
    G = H.copy()
    G[[5, 50, 150]] = G[[5, 50, 150]][:, [0, 2, 1]]
    out, rec = r.orient_glb(build_glb(PH, G, R))
    check("3 flipped, open", rec["faces_flipped"] == 3 and rec["closed"] == 0, str(rec))
    check("faces restored", np.array_equal(faces_of(out).faces, H))
    _, rec = r.orient_glb(build_glb(PH, H[:, [0, 2, 1]], R))
    check("reversed open piece kept", rec["faces_flipped"] == 0 and rec["normals_fixed"] == len(PH), str(rec))

    print("[6] normals")
    glb = build_glb(P, F, R)
    prim = faces_of(glb)
    bad = [3, 77, 200, 401, 640]
    prim.attributes["NORMAL"][bad] *= -1
    glb2 = glb_mesh.rewrite_body_primitives(glb, {0: prim})
    out, rec = r.orient_glb(glb2)
    N = faces_of(out).attributes["NORMAL"]
    U = P / np.linalg.norm(P, axis=1, keepdims=True)
    check("5 fixed", rec["normals_fixed"] == 5, str(rec))
    check("outward again", bool((np.einsum("ij,ij->i", N[bad], U[bad]) > 0.99).all()))
    keep = np.setdiff1d(np.arange(len(P)), bad)
    check("others identical", np.array_equal(N[keep], faces_of(glb2).attributes["NORMAL"][keep]))

    print("[7] repair record")
    _, rec = r.repair_glb(build_glb(P, F, R))
    check("orient in record", (rec.get("orient") or {}).get("status") == "applied", str(rec.get("orient")))
    check("VERSION >= 3", r.VERSION >= 3)

    print()
    if FAILS:
        print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
