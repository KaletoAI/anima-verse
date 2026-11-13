#!/usr/bin/env python3
"""The base mesh repair (``app/core/base_mesh_repair.py``, Ruling A34): holes filled on the CPU, a rebuilt chest tip
smoothed first over the part's footprint.

Usage:
    ./.venv/bin/python scripts/smoke_base_mesh_repair.py
    RUN_BASE_MESH_REPAIR_REAL=1 A34_STAGES=<dir> ./.venv/bin/python scripts/smoke_base_mesh_repair.py

Synthetic meshes only (no world, no server, no Blender); the optional real-data section reads COPIES of a base
model's stages from ``A34_STAGES`` (``s0_mesher.glb``: the mesher output, closed; ``s4_prerig_normalized.glb``:
the rigged clean source with the rigger's three dropped faces). Storage is a temp dir (``paths.init`` before any
world module) for the model3d section.

Fixture: an icosphere (icosahedron subdivided 3 times: 642 vertices, 1280 triangles) of radius r = 4 cm, as a real
skinned GLB (POSITION, NORMAL, TEXCOORD_0 = (x, y)/r, JOINTS_0 = (0, 1, 0, 0), WEIGHTS_0 = (w, 1 - w, 0, 0) with
w = (z + r) / 2r — joint 0 carries the top). Expected, derived by hand:

[1] Closed sphere: ``repair_glb`` returns THE SAME bytes object (byte for byte), record holes 0, filled 0,
    status applied; the summary "Closed — no hole".
[2] Hole: every triangle whose centroid lies within 20 degrees of +z removed. The rim then sits at the polar angle
    theta_rim of its vertices (measured, mean). A fair fill spans at least the flat disc of the rim,
    pi (r sin theta_rim)^2, and at most the spherical cap 2 pi r^2 (1 - cos theta_rim); with the icosphere's facets
    a little flatter than the sphere the patch area must lie in [disc, 1.05 cap]. Closed afterwards: 0 open edges
    (``open_edge_count``), record holes 1, filled 1, largest_cm = the rim's largest vertex-to-vertex distance (the
    size rule of ``_loop_size``; about 2 r sin theta_rim = 2 x 4 x sin 20 = 2.7 cm, a jagged rim reaches farther),
    open_edges_after 0. That is under the default largest hole 4 cm (checked on the run's own number; with r = 5 cm
    the jagged rim measured 4.08 cm and was — correctly — left open).
    The patch is FAIRED, not flat: its centre vertex lies at least half the cap's sagitta r (1 - cos theta_rim)
    above the rim's plane.
[3] The fill's attributes: every new vertex's weights sum to 1 (+-1e-6), use only joints 0/1 (the rim's), and
    w0 lies within the rim's [min, max] (harmonic interpolation: maximum principle); its UV within the rim's UV
    box; its NORMAL unit length and pointing outwards (dot with the position > 0).
[4] One dropped triangle (the rigger's case on Kira's base: 3-vertex holes of 0.5-1.8 mm): exactly one triangle
    added, no vertex, 0 open edges after.
[5] The largest hole setting at 0.5 cm and the 20-degree hole (~3 cm across): not filled, record unfilled
    [{size_cm, reason "larger than the largest hole to fill"}], the bytes returned unchanged, the summary
    "1 hole left open (… cm — larger than the largest hole to fill)". Switched off: status skipped, same bytes.
[6] Tip smoothing radius = the part's footprint: ``tip_smooth_radius(fill_radius, tip_radius)`` =
    fill_radius x tip_radius: 2.1 x 8.92 mm = 18.732 mm (Kira's measured marker radius and the pack's
    fill_radius); a marker twice as large -> 37.464 mm; fill_radius 3 -> 26.76 mm.
    ``smooth_region`` on a 1 mm grid plane (60 x 60 mm, z = 0) with two 3 mm bumps (Gaussian, sigma 1.5 mm):
    one at the centre (inside the 18.73 mm footprint) and one 25 mm out (outside it, beyond the 2.68 mm blend):
    the inner bump drops below 20 % of its height, every vertex farther than R from the centre keeps its exact
    coordinates, and N = ceil((R / edge)^2) passes are run (edge = the mean edge of the region, here 1.17 mm with
    the grid's diagonals -> ceil((18.732 / edge)^2), compared with the run's own edge). A fixed vertex never moves;
    a fixed patch of 4 vertices with ``min_wall`` 100 counts as a fold (released, ``folds_released`` 4) and moves.
[7] Settings: defaults {enabled True, max_hole_cm 4.0}; 0.4 and 21 cm, a string, an unknown key -> ValueError;
    the fingerprint changes with max_hole_cm and with VERSION.
[8] model3d: a base body's staged bytes are repaired (``_repaired_base``: record in meta, version VERSION, the
    settings fingerprint of the defaults); an outfit model's (meta without ``base``) come back untouched with no
    record; ``_mesh_repair_due``: no record -> True, the record just written -> False, saved settings
    max_hole_cm 6 -> True.
[9] Real data (RUN_BASE_MESH_REPAIR_REAL=1): s0_mesher closed -> same bytes; s4_prerig_normalized: holes 3,
    filled 3, largest <= 0.2 cm (measured 2026-11-14: 0.18), faces_added 3, vertices_added 0, open edges 7 -> 0.
"""
import json
import math
import os
import struct
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + label + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)


def icosphere(r, levels):
    t = (1 + 5 ** 0.5) / 2
    V = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
         (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    F = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6),
         (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10),
         (8, 6, 7), (9, 8, 1)]
    V = [np.array(v, float) / np.linalg.norm(v) for v in V]
    for _ in range(levels):
        cache, nf = {}, []

        def mid(a, b):
            key = (min(a, b), max(a, b))
            if key not in cache:
                m = V[a] + V[b]
                V.append(m / np.linalg.norm(m))
                cache[key] = len(V) - 1
            return cache[key]
        for a, b, c in F:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            nf += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        F = nf
    return np.array(V) * r, np.array(F, np.int64)


def build_glb(P, F, r):
    """A skinned one-primitive GLB (module docstring)."""
    P = np.asarray(P, np.float32)
    N = (P / np.linalg.norm(P, axis=1, keepdims=True)).astype(np.float32)
    UV = (P[:, :2] / r).astype(np.float32)
    w = ((P[:, 2] + r) / (2 * r)).astype(np.float32)
    J = np.tile(np.array([0, 1, 0, 0], np.uint8), (len(P), 1))
    W = np.stack([w, 1 - w, np.zeros_like(w), np.zeros_like(w)], 1).astype(np.float32)
    I = np.asarray(F, np.uint32).reshape(-1)
    blobs, views, accessors = [], [], []

    def add(arr, comp, typ, target, minmax=False):
        raw = arr.tobytes()
        offset = sum(len(b) for b in blobs)
        blobs.append(raw + b"\0" * (-len(raw) % 4))
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw), "target": target})
        acc = {"bufferView": len(views) - 1, "componentType": comp, "count": int(arr.shape[0]), "type": typ}
        if minmax:
            acc["min"], acc["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accessors.append(acc)
        return len(accessors) - 1
    attrs = {"POSITION": add(P, 5126, "VEC3", 34962, True), "NORMAL": add(N, 5126, "VEC3", 34962),
             "TEXCOORD_0": add(UV, 5126, "VEC2", 34962), "JOINTS_0": add(J, 5121, "VEC4", 34962),
             "WEIGHTS_0": add(W, 5126, "VEC4", 34962)}
    idx = add(I.reshape(-1, 1), 5125, "SCALAR", 34963)
    body = b"".join(blobs)
    gltf = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0, 1]}],
            "nodes": [{"name": "Body", "mesh": 0, "skin": 0}, {"name": "Hips", "children": [2]}, {"name": "Spine"}],
            "skins": [{"joints": [1, 2]}],
            "meshes": [{"primitives": [{"attributes": attrs, "indices": idx}]}],
            "buffers": [{"byteLength": len(body)}], "bufferViews": views, "accessors": accessors}
    js = json.dumps(gltf).encode()
    js += b" " * (-len(js) % 4)
    chunks = struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(body), b"BIN\0") + body
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks


def area(P, F):
    return float(np.linalg.norm(np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]]), axis=1).sum() / 2)


def main() -> int:
    tmp = tempfile.TemporaryDirectory(prefix="base-mesh-repair-")
    root = Path(tmp.name)
    os.environ["STORAGE_DIR"] = str(root / "world")
    os.environ["INSTANCE_DIR"] = str(root / "instance")
    from app.core import paths
    paths.init(root / "world")
    paths.init_instance(root / "instance")
    from app.core import base_mesh_repair as R, glb_mesh

    r = 0.04
    P, F = icosphere(r, 3)
    check("fixture 642 vertices, 1280 triangles", (len(P), len(F)) == (642, 1280), f"{len(P)}, {len(F)}")

    print("[1] closed sphere")
    closed = build_glb(P, F, r)
    out, rec = R.repair_glb(closed)
    check("same bytes object", out is closed and out == closed)
    check("record", (rec["status"], rec["holes"], rec["filled"]) == ("applied", 0, 0), str(rec))
    check("summary", R.summary(rec) == "Closed — no hole", R.summary(rec))

    print("[2] a 20-degree hole")
    cen = P[F].mean(1)
    polar = np.degrees(np.arccos(np.clip(cen[:, 2] / np.linalg.norm(cen, axis=1), -1, 1)))
    keep = polar > 20.0
    holed = build_glb(P, F[keep], r)
    prims = glb_mesh.body_primitive_arrays(holed)
    loops, _ = R.boundary_loops(prims[0].positions, prims[0].faces)
    rim = prims[0].positions[[raw for _, raw, _ in loops[0]]]
    theta = float(np.mean(np.arccos(np.clip(rim[:, 2] / np.linalg.norm(rim, axis=1), -1, 1))))
    disc, cap = math.pi * (r * math.sin(theta)) ** 2, 2 * math.pi * r * r * (1 - math.cos(theta))
    print(f"       theta_rim {math.degrees(theta):.2f} deg, disc {disc * 1e4:.3f} cm2, cap {cap * 1e4:.3f} cm2")
    d = rim[:, None, :] - rim[None, :, :]
    across = float(np.sqrt((d * d).sum(-1)).max())
    check("rim under the default largest hole", across < 0.04, f"{across * 100:.2f} cm")
    out, rec = R.repair_glb(holed)
    after = glb_mesh.body_primitive_arrays(out)[0]
    check("closed afterwards", R.open_edge_count(after.positions, after.faces) == 0 and rec["open_edges_after"] == 0)
    check("record holes 1 filled 1", (rec["holes"], rec["filled"], rec["unfilled"]) == (1, 1, []), str(rec))
    check("largest_cm = the rim's largest distance", abs(rec["largest_cm"] - across * 100) <= 0.005,
          f"{rec['largest_cm']} vs {across * 100:.3f}")
    new_faces = after.faces[len(prims[0].faces):]
    patch = area(after.positions, new_faces)
    check("patch area in [disc, 1.05 cap]", disc <= patch <= 1.05 * cap,
          f"{patch * 1e4:.3f} cm2 in [{disc * 1e4:.3f}, {1.05 * cap * 1e4:.3f}]")
    n0 = len(prims[0].positions)
    new = after.positions[n0:]
    plane_z = float(rim[:, 2].mean())
    sagitta = r * (1 - math.cos(theta))
    top = float(new[:, 2].max() - plane_z) if len(new) else 0.0
    check("faired: centre above the rim plane by >= half the sagitta", top >= 0.5 * sagitta,
          f"{top * 1000:.2f} mm vs sagitta {sagitta * 1000:.2f} mm")

    print("[3] attributes of the fill")
    rim_raw = [raw for _, raw, _ in loops[0]]
    Wn, Jn = after.weights[n0:], after.joints[n0:]
    check("new vertices exist", len(new) > 0, str(len(new)))
    check("weights sum to 1", bool(np.all(np.abs(Wn.sum(1) - 1) < 1e-6)), f"{np.abs(Wn.sum(1) - 1).max():.2e}")
    used = {int(j) for j, w in zip(Jn.ravel(), Wn.ravel()) if w > 0}
    check("only the rim's joints", used <= {0, 1}, str(used))
    w0 = np.array([sum(w for j, w in zip(js, ws) if j == 0) for js, ws in zip(Jn, Wn)])
    rim_w0 = prims[0].weights[rim_raw, 0]
    check("w0 within the rim's range", bool(np.all((w0 >= rim_w0.min() - 1e-6) & (w0 <= rim_w0.max() + 1e-6))),
          f"[{w0.min():.4f}, {w0.max():.4f}] in [{rim_w0.min():.4f}, {rim_w0.max():.4f}]")
    uv, rim_uv = after.attributes["TEXCOORD_0"][n0:], prims[0].attributes["TEXCOORD_0"][rim_raw]
    check("UV within the rim's box", bool(np.all((uv >= rim_uv.min(0) - 1e-9) & (uv <= rim_uv.max(0) + 1e-9))))
    nn = after.attributes["NORMAL"][n0:]
    check("normals unit and outward", bool(np.all(np.abs(np.linalg.norm(nn, axis=1) - 1) < 1e-5)
                                          and np.all((nn * new).sum(1) > 0)))

    print("[4] one dropped triangle")
    one = build_glb(P, np.delete(F, 100, axis=0), r)
    out, rec = R.repair_glb(one)
    after1 = glb_mesh.body_primitive_arrays(out)[0]
    check("one triangle, no vertex", (rec["filled"], rec["faces_added"], rec["vertices_added"]) == (1, 1, 0), str(rec))
    check("closed", R.open_edge_count(after1.positions, after1.faces) == 0)

    print("[5] too large / switched off")
    out, rec = R.repair_glb(holed, {"max_hole_cm": 0.5})   # the hole is ~3 cm across
    check("not filled, bytes unchanged", out is holed and rec["filled"] == 0
          and [u["reason"] for u in rec["unfilled"]] == ["larger than the largest hole to fill"], str(rec))
    check("summary names it", R.summary(rec).startswith("1 hole left open (")
          and R.summary(rec).endswith("cm — larger than the largest hole to fill)"), R.summary(rec))
    out, rec = R.repair_glb(holed, {"enabled": False})
    check("switched off", out is holed and rec["status"] == "skipped" and R.summary(rec) == "Switched off")

    print("[6] tip smoothing follows the part's footprint")
    check("2.1 x 8.92 mm", abs(R.tip_smooth_radius(2.1, 0.00892) - 0.018732) < 1e-9)
    check("marker twice as large", abs(R.tip_smooth_radius(2.1, 0.01784) - 0.037464) < 1e-9)
    check("fill_radius 3", abs(R.tip_smooth_radius(3.0, 0.00892) - 0.02676) < 1e-9)
    n = 61
    xs = (np.arange(n) - 30) * 0.001
    X, Y = np.meshgrid(xs, xs, indexing="ij")
    Z = (0.003 * np.exp(-(X ** 2 + Y ** 2) / (2 * 0.0015 ** 2))
         + 0.003 * np.exp(-((X - 0.025) ** 2 + Y ** 2) / (2 * 0.0015 ** 2)))
    grid = np.stack([X.ravel(), Y.ravel(), Z.ravel()], 1)
    idx = np.arange(n * n).reshape(n, n)
    edges = np.concatenate([np.stack([idx[:-1, :].ravel(), idx[1:, :].ravel()], 1),
                            np.stack([idx[:, :-1].ravel(), idx[:, 1:].ravel()], 1),
                            np.stack([idx[:-1, :-1].ravel(), idx[1:, 1:].ravel()], 1)])
    radius, blend = R.tip_smooth_radius(2.1, 0.00892), 0.3 * 0.00892
    fixed = np.zeros(len(grid), bool)
    fixed_one = int(idx[30, 40])           # 10 mm out, inside the footprint
    fixed[fixed_one] = True
    smoothed, info = R.smooth_region(grid, edges, [(0, 0, 0)], radius, blend, fixed=fixed)
    centre = int(idx[30, 30])
    check("inner bump below 20 %", smoothed[centre, 2] < 0.2 * grid[centre, 2],
          f"{smoothed[centre, 2] * 1000:.3f} of {grid[centre, 2] * 1000:.3f} mm")
    far = np.linalg.norm(grid[:, :2], axis=1) > radius
    check("outside the footprint untouched", bool(np.array_equal(smoothed[far], grid[far])))
    check("the outer bump untouched", smoothed[int(idx[55, 30]), 2] == grid[int(idx[55, 30]), 2])
    check("passes = ceil((R / edge)^2)", info["iterations"] == math.ceil((radius / info["edge_m"]) ** 2),
          f"{info['iterations']} with edge {info['edge_m'] * 1000:.3f} mm")
    check("fixed vertex unmoved", bool(np.array_equal(smoothed[fixed_one], grid[fixed_one])))
    patch = np.zeros(len(grid), bool)
    patch[[int(idx[30, 31]), int(idx[30, 32]), int(idx[31, 31]), int(idx[31, 32])]] = True
    smoothed2, info2 = R.smooth_region(grid, edges, [(0, 0, 0)], radius, blend, fixed=patch, min_wall=100)
    check("a small fixed patch is a fold: released and smoothed",
          info2["folds_released"] == 4 and not np.array_equal(smoothed2[patch], grid[patch]), str(info2))

    print("[7] settings")
    check("defaults", R.validated_settings(None) == {"enabled": True, "max_hole_cm": 4.0})
    for bad in ({"max_hole_cm": 0.4}, {"max_hole_cm": 21}, {"max_hole_cm": "3"}, {"other": 1}, {"enabled": 1}):
        try:
            R.validated_settings(bad)
            check(f"refuses {bad}", False)
        except ValueError:
            check(f"refuses {bad}", True)
    a = R.settings_fingerprint({})
    check("fingerprint follows max_hole_cm", a != R.settings_fingerprint({"max_hole_cm": 6}))
    R.VERSION += 1
    check("fingerprint follows VERSION", a != R.settings_fingerprint({}))
    R.VERSION -= 1

    print("[8] model3d")
    from app.core import model3d
    options = {"mesh_repair": R.validated_settings(None)}
    model3d.get_model3d_options = lambda name: options
    meta = {"base": True, "rig": "mixamo"}
    repaired = model3d._repaired_base("Demo", one, meta)
    record = meta.get("mesh_repair") or {}
    check("base repaired", repaired != one and record.get("filled") == 1
          and record.get("version") == R.VERSION and record.get("settings") == R.settings_fingerprint({}), str(record))
    outfit = {"rig": "mixamo"}
    check("outfit untouched", model3d._repaired_base("Demo", one, outfit) is one and "mesh_repair" not in outfit)
    path = root / "base.glb"
    check("due without a record", model3d._mesh_repair_due("Demo", path, {"base": True, "rig": "mixamo"}))
    check("not due with it", not model3d._mesh_repair_due("Demo", path, meta))
    options["mesh_repair"] = R.validated_settings({"max_hole_cm": 6})
    check("due after a saved setting", model3d._mesh_repair_due("Demo", path, meta))

    if os.environ.get("RUN_BASE_MESH_REPAIR_REAL") == "1":
        print("[9] real data (copies)")
        stages = Path(os.environ.get("A34_STAGES", ""))
        s0, s4 = stages / "s0_mesher.glb", stages / "s4_prerig_normalized.glb"
        if not s0.is_file() or not s4.is_file():
            check("stage copies present", False, str(stages))
        else:
            blob = s0.read_bytes()
            out, rec = R.repair_glb(blob)
            check("mesher output closed: same bytes", out is blob and rec["holes"] == 0, str(rec))
            blob = s4.read_bytes()
            before = R.open_edge_count(*R._concat(glb_mesh.body_primitive_arrays(blob)))
            out, rec = R.repair_glb(blob)
            check("rigged source: 3 holes filled", (rec["holes"], rec["filled"], rec["faces_added"],
                                                    rec["vertices_added"]) == (3, 3, 3, 0), str(rec))
            check("largest <= 0.2 cm", rec["largest_cm"] <= 0.2, str(rec["largest_cm"]))
            check("open edges 7 -> 0", (before, rec["open_edges_after"]) == (7, 0), f"{before} -> {rec['open_edges_after']}")
    else:
        print("[9] real data skipped (RUN_BASE_MESH_REPAIR_REAL=1 A34_STAGES=<dir>)")

    tmp.cleanup()
    print()
    if FAILS:
        print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
