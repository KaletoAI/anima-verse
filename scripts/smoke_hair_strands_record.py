#!/usr/bin/env python3
"""The strand record of a hair fit (``app/core/hair_strands.py``) — strand-hair plan 2026-11-13, Task 4 (spec
§ 6.2.3). Expectations derived by hand below.

Usage: ./.venv/bin/python scripts/smoke_hair_strands_record.py

No server, no world DB of a real world, no hub: a throwaway storage dir (``paths.init``) holds the garment files of
the character ``demo``. Outbound connections are refused (``socket.connect``).

Fixture body (built here; joints as ``smoke_hair_alpha_assembly.py::body_fixture``: every base joint of
``shared/models/rig/joints.json`` as ``mixamorig:<name>``, children of Hips at the origin): Spine2 at (0, 1.30, 0),
Neck at (0, 1.50, 0), Head at (0, 1.60, 0). Three closed meshes in ONE primitive: a head sphere of radius 0.09 m at
(0, 1.60, 0) (64 x 32 lat-long), a neck cylinder of radius 0.05 m from y 1.40 to 1.52 (48 sides, capped), a torso
box x ±0.15, y 1.00 .. 1.40, z ±0.08. Weights by height: y >= 1.52 Head, 1.40 < y < 1.52 Neck, else Spine2
(the shoulder top, ``shoulder_top_height`` = the highest Spine2 vertex, is 1.40; the ear line 1.52 + 0.25 * 0.17).

Hair (HairDeck's layout: square tubes, 4 vertices per row, rows root first, hair first, the cap after it):
  Card A: root (0, 1.62, -0.092), straight down; 35 true rows 0.01 m apart (length 0.34), square side 4 mm.
  Card B: root (0, 1.62, 0.092), pointing +z, the same tube.
  A 4-vertex cap quad at y 1.695. u around a tube 0 / 0.5 / 1 / 0.5, v = 1 at the root .. 0 at the tip; every row
  closed by its cross-section quad (``hair_cards.card_faces`` removes those: the strand UVs run along the card).
  Grafted with Task 2's path: ``refit_pool.graft_file(body, texture_garment(g, hairdeck_cards(F, 280, 284)), …,
  material_overrides=alpha_overrides())``; fit record ``{method: hairdeck, report.vertices: {hair: 280, cap: 4}}``.

Expected (by hand):
  rows: 0.34 / 16 = 0.02125 m apart.
  [1] pins (head centre (0, 1.60, 0), r 0.09):
      A = 2: row 1 = (0, 1.59875, -0.092), sdf = sqrt(0.00125^2 + 0.092^2) - 0.09 = 0.0020 <= 0.006 and
             arc 0.02125 <= 0.04 -> pinned; row 2 arc 0.0425 > 0.04 -> free (sdf irrelevant)
      B = 1: row 1 = (0, 1.62, 0.11325), sdf = sqrt(0.02^2 + 0.11325^2) - 0.09 = 0.0250 > 0.006 and
             arc 0.02125 > 0.02 -> free
      First the sampled sdf of A row 1 within 0.002 of 0.0020 (tessellated sphere), so the 4 mm margin to 0.006
      holds before the pin counts are asserted.
  [2] rest[A][8] == (0, 1.62 - 8*0.02125, -0.092) == (0, 1.45, -0.092) within 1e-5
  [3] free_frac: B row 8 == 8/16 == 0.5; A row 8 == (8-1)/(16-1) == 0.46667; pinned rows 0
      free_arc: B row 16 == 0.34; A row 16 == 0.34 - 0.02125 == 0.31875
  [4] u: the vertices of A's true row 17 (arc 0.17) have u == 0.17/0.34*16 == 8.0; cap vertices card 0 in the npz;
      the npz has one entry per vertex of the fit's hair node (284), the record 2 cards — after ``card_faces``
      dropped the 2 x 35 cross-section quads (140 faces) of the served primitive
  [5] follow: every row sums to 1 within 1e-6; pinned rows are {Head: 1}; bones Head / Neck / Spine2
  [6] sdf: decoded at (0, 1.60, 0.05) == 0.05 - 0.09 = -40 mm within +-4; at (0, 1.60, 0.12) == +30 mm within
      +-4; outside the grid reads +127 mm. At the sphere centre the true value is -90 mm, but the centre is the
      APEX of the distance cone: trilinear interpolation between nodes of the 6.8 mm grid up to 3.4 * sqrt(3) =
      5.9 mm away reads shallower by up to 5.9 mm (and the voxel EDT inside by about one 3.4 mm voxel), so
      -90 - 4 <= decoded <= -90 + 4 + 5.9.
  [7] face_box == [cx-0.06, cx+0.06, chin, brow+0.01, cz+0.25*head_d] with the landmarks the smoke computes
      through head_landmarks (a sphere has no face: brow = top - 0.09); params == PARAMS["hairdeck"];
      PARAMS["haar"] == the same with root_deg 0; head_bone mixamorig:Head; frame head_bind; rows 17
  [8] cache: a second record_for_fit leaves the sidecar mtime unchanged; rewriting the fit (one cap vertex moved
      by 1 mm) changes fit_sha256 and the record; the stored JSON bytes == encode(record) and current_sha ==
      their sha256; a fit of another method gets None
  [9]  Ruling H-R3: ``<item>_<fsig>.strands.json`` / ``.npz`` parse to the fit's (item, fsig), sit in its
       ``stored_groups`` group and in its artefact-graph garment node (deleted with the fit), never ``unknown``
  [10] Ruling H-R4: extension capsules of the fit body (derivation at the check)
  [11] Ruling H-R5: the preview GLB carries the binding (derivation at the check)
"""
import base64
import hashlib
import json
import math
import shutil
import socket
import struct
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

FAILS = []
CHAR = "demo"
ITEM = "hair_h2"
FSIG = "0123456789ab"
NAME = f"garment_hair_{ITEM}"
STEP = 0.34 / 16


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def _no_net(*_a, **_k):
    raise OSError("smoke: outbound connections are refused")


def pack(doc, blob):
    blob = bytes(blob) + b"\0" * (-len(blob) % 4)
    doc["buffers"] = [{"byteLength": len(blob)}]
    raw = json.dumps(doc).encode()
    raw += b" " * (-len(raw) % 4)
    body = struct.pack("<II", len(raw), 0x4E4F534A) + raw + struct.pack("<II", len(blob), 0x004E4942) + blob
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def sphere(c, r, nu=64, nv=32):
    P = [[c[0], c[1] + r, c[2]]]
    for i in range(1, nv):
        th = math.pi * i / nv
        for j in range(nu):
            ph = 2 * math.pi * j / nu
            P.append([c[0] + r * math.sin(th) * math.cos(ph), c[1] + r * math.cos(th), c[2] + r * math.sin(th) * math.sin(ph)])
    P.append([c[0], c[1] - r, c[2]])
    F = []
    for j in range(nu):
        F.append([0, 1 + (j + 1) % nu, 1 + j])
    for i in range(nv - 2):
        a, b = 1 + i * nu, 1 + (i + 1) * nu
        for j in range(nu):
            j1 = (j + 1) % nu
            F += [[a + j, a + j1, b + j1], [a + j, b + j1, b + j]]
    last = len(P) - 1
    base = 1 + (nv - 2) * nu
    for j in range(nu):
        F.append([base + j, base + (j + 1) % nu, last])
    return np.asarray(P), np.asarray(F)


def cylinder(r, y0, y1, n=48):
    ring = [[r * math.cos(2 * math.pi * j / n), r * math.sin(2 * math.pi * j / n)] for j in range(n)]
    P = [[x, y0, z] for x, z in ring] + [[x, y1, z] for x, z in ring] + [[0, y0, 0], [0, y1, 0]]
    F = []
    for j in range(n):
        j1 = (j + 1) % n
        F += [[j, j1, n + j1], [j, n + j1, n + j], [2 * n, j1, j], [2 * n + 1, n + j, n + j1]]
    return np.asarray(P, float), np.asarray(F)


def box(lo, hi):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    P = [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]]
    F = [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [3, 7, 6], [3, 6, 2], [0, 4, 7], [0, 7, 3],
         [1, 2, 6], [1, 6, 5]]
    return np.asarray(P, float), np.asarray(F)


def body_fixture():
    from app.core.rig_contract import BASE_JOINT_NAMES
    names = ["mixamorig:" + n for n in BASE_JOINT_NAMES]
    jidx = {n: 2 + i for i, n in enumerate(names)}
    nodes = [{"name": "Armature", "children": [1, 2]}, {"name": "Body", "mesh": 0, "skin": 0}]
    joints = [{"name": n} for n in names]
    joints[0]["children"] = [jidx[n] for n in names[1:]]
    at = {"mixamorig:Spine2": 1.30, "mixamorig:Neck": 1.50, "mixamorig:Head": 1.60}
    for n, y in at.items():
        joints[names.index(n)]["translation"] = [0, y, 0]
    nodes += joints
    sk = {n: i for i, n in enumerate(names)}
    ibm = np.tile(np.eye(4), (len(names), 1, 1))
    for n, y in at.items():
        ibm[sk[n], 1, 3] = -y
    parts = [sphere((0, 1.60, 0), 0.09), cylinder(0.05, 1.40, 1.52), box((-0.15, 1.00, -0.08), (0.15, 1.40, 0.08))]
    P, F, base = [], [], 0
    for p, f in parts:
        P.append(p)
        F.append(f + base)
        base += len(p)
    P = np.vstack(P).astype("<f4")
    F = np.vstack(F).astype("<u4")
    y = P[:, 1]
    # (the cylinder's bottom ring and the box top at y 1.40 are Spine2, so the shoulder top is 1.40)
    bone = np.where(y >= 1.52, sk["mixamorig:Head"], np.where(y > 1.405, sk["mixamorig:Neck"], sk["mixamorig:Spine2"]))
    J = np.zeros((len(P), 4), "<u2")
    J[:, 0] = bone
    W = np.zeros((len(P), 4), "<f4")
    W[:, 0] = 1
    blob = bytearray()
    views, accs = [], []

    def add(arr, ctype, typ, target=None, minmax=False):
        raw = arr.tobytes()
        blob.extend(b"\0" * (-len(blob) % 4))
        view = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(raw)}
        if target:
            view["target"] = target
        views.append(view)
        blob.extend(raw)
        count = {"MAT4": len(arr) // 16, "SCALAR": arr.size}.get(typ, len(arr))
        a = {"bufferView": len(views) - 1, "componentType": ctype, "count": count, "type": typ}
        if minmax:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(a)
        return len(accs) - 1
    attrs = {"POSITION": add(P, 5126, "VEC3", 34962, True), "JOINTS_0": add(J, 5123, "VEC4", 34962),
             "WEIGHTS_0": add(W, 5126, "VEC4", 34962)}
    ind = add(F.reshape(-1), 5125, "SCALAR", 34963)
    ibm_acc = add(np.ascontiguousarray(ibm.transpose(0, 2, 1).reshape(-1), "<f4"), 5126, "MAT4")
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes,
           "meshes": [{"name": "Body", "primitives": [{"attributes": attrs, "indices": ind, "material": 0}]}],
           "skins": [{"joints": [jidx[n] for n in names], "inverseBindMatrices": ibm_acc}],
           "accessors": accs, "bufferViews": views, "materials": [{"name": "Skin"}]}
    return pack(doc, blob)


def tube(root, direction, side_a, side_b, rows=35, step=0.01, half=0.002):
    """A square tube: ``rows`` rings of 4 vertices (``root + i * step * direction``), side quads between rings
    and the cross-section quad of every ring."""
    root, d = np.asarray(root, float), np.asarray(direction, float)
    a, b = np.asarray(side_a, float) * half, np.asarray(side_b, float) * half
    ring = [-a - b, a - b, a + b, -a + b]
    P = [root + i * step * d + o for i in range(rows) for o in ring]
    U = [[u, 1 - i / (rows - 1)] for i in range(rows) for u in (0, 0.5, 1, 0.5)]
    F = []
    for r in range(rows - 1):
        for k in range(4):
            p, q = 4 * r + k, 4 * r + (k + 1) % 4
            F += [[p, q, q + 4], [p, q + 4, p + 4]]
    for r in range(rows):
        F += [[4 * r, 4 * r + 1, 4 * r + 2], [4 * r, 4 * r + 2, 4 * r + 3]]
    return np.asarray(P), np.asarray(U, float), np.asarray(F)


def hair_garment(cap_shift=0.0):
    from app.core.glb_mesh import GarmentMesh
    PA, UA, FA = tube((0, 1.62, -0.092), (0, -1, 0), (1, 0, 0), (0, 0, 1))
    PB, UB, FB = tube((0, 1.62, 0.092), (0, 0, 1), (1, 0, 0), (0, 1, 0))
    cap = np.array([[-0.02, 1.695, -0.02], [0.02, 1.695, -0.02], [0.02, 1.695, 0.02], [-0.02, 1.695, 0.02]])
    cap[0, 1] += cap_shift
    P = np.vstack([PA, PB, cap])
    U = np.vstack([UA, UB, np.zeros((4, 2))])
    F = np.vstack([FA, FB + len(PA), np.array([[0, 2, 1], [0, 3, 2]]) + 2 * len(PA)])
    n = len(P)
    g = GarmentMesh(positions=P, normals=None, uvs=U, indices=F, joints=np.zeros((n, 4), np.int64),
                    weights=np.tile([1.0, 0, 0, 0], (n, 1)), joint_names=["mixamorig:Head"],
                    material={"name": "hair", "doubleSided": True}, colors=np.tile([0.4, 0.3, 0.2, 1.0], (n, 1)))
    return g, F


def write_fit(target, cap_shift=0.0):
    from app.core import garment_store as gs, hair_cards, refit_pool
    g, F = hair_garment(cap_shift)
    textured = hair_cards.texture_garment(g, hair_cards.hairdeck_cards(F, 280, 284))
    fit = gs.garment_path(CHAR, ITEM, FSIG, "fit")
    fit.parent.mkdir(parents=True, exist_ok=True)
    refit_pool.graft_file(target, textured, NAME, {"kind": "hair", "item_id": ITEM, "fsig": FSIG}, str(fit),
                          material_overrides=hair_cards.alpha_overrides())
    gs.write_record(fit.with_suffix(".json"), {"accepted": True, "kind": "hair", "item_id": ITEM, "fsig": FSIG,
                                               "method": "hairdeck", "report": {"vertices": {"hair": 280, "cap": 4}}})
    return fit, len(F), len(textured.indices)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="smoke_hair_strands_record_"))
    try:
        return run_checks(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_checks(tmp):
    socket.socket.connect = _no_net
    socket.create_connection = _no_net
    from app.core import paths
    paths.init(tmp / "world")
    paths.init_instance(tmp / "instance")
    from app.core import db
    db.init_schema()
    from app.core import garment_fit as gf, garment_hairdeck as gh, glb_mesh, hair_strands as hs
    from app.models.character import get_character_dir
    get_character_dir(CHAR, create=True)
    target = body_fixture()
    fit, faces_before, faces_served = write_fit(target)
    blob = fit.read_bytes()

    t0 = time.time()
    record = hs.record_for_fit(CHAR, fit)
    print(f"     record built in {time.time() - t0:.1f} s")
    check(record is not None, "[0] record_for_fit builds a record")
    if record is None:
        print(f"FAIL ({len(FAILS)})")
        return 1
    rest = np.asarray(record["rest"]).reshape(-1, 17, 3)
    free_arc = np.asarray(record["free_arc"]).reshape(-1, 17)
    free_frac = np.asarray(record["free_frac"]).reshape(-1, 17)

    # [1] pins
    body = glb_mesh.body_arrays(blob)
    frame = hs.head_frame(body)
    sdf = hs.head_sdf(body, frame)
    d1 = float(sdf.sample(np.array([[0, 1.62 - STEP, -0.092]]))[0])
    expect = math.sqrt(0.00125 ** 2 + 0.092 ** 2) - 0.09
    check(abs(d1 - expect) <= 0.002, f"[1] sdf at A row 1 = {d1:.4f} within 0.002 of {expect:.4f}")
    check(record["cards"] == 2, f"[1] two cards (got {record['cards']})")
    check(record["pins"] == [2, 1], f"[1] pins A 2, B 1 (got {record['pins']})")

    # [2] rest
    check(np.allclose(rest[0, 8], [0, 1.45, -0.092], atol=1e-5), f"[2] rest[A][8] == (0, 1.45, -0.092) (got {rest[0, 8]})")

    # [3] free arc / fraction
    check(abs(free_frac[1, 8] - 0.5) < 1e-5, f"[3] free_frac B row 8 == 0.5 (got {free_frac[1, 8]})")
    check(abs(free_frac[0, 8] - 7 / 15) < 1e-5, f"[3] free_frac A row 8 == 0.46667 (got {free_frac[0, 8]})")
    check(free_frac[0, :2].tolist() == [0, 0] and free_frac[1, 0] == 0 and free_arc[0, :2].tolist() == [0, 0]
          and free_arc[1, 0] == 0, "[3] pinned rows 0")
    check(abs(free_arc[1, 16] - 0.34) < 1e-5, f"[3] free_arc B row 16 == 0.34 (got {free_arc[1, 16]})")
    check(abs(free_arc[0, 16] - 0.31875) < 1e-5, f"[3] free_arc A row 16 == 0.31875 (got {free_arc[0, 16]})")

    # [4] per-vertex binding
    arrays = hs.vertex_arrays(fit)
    check(arrays is not None, "[4] vertex_arrays of the current record")
    hair_node = glb_mesh.garment_arrays(blob, node_prefix=NAME, exact=True)
    check(len(arrays["card"]) == len(arrays["u"]) == len(hair_node.positions) == 284,
          f"[4] one entry per vertex of the hair node ({len(arrays['card'])} / {len(hair_node.positions)})")
    check(faces_served == faces_before - 140 and len(hair_node.indices) == faces_served,
          f"[4] the served primitive lost the 140 cross-section faces ({faces_before} -> {len(hair_node.indices)})")
    row17 = np.arange(17 * 4, 18 * 4)
    check(np.allclose(arrays["u"][row17], 8.0, atol=1e-5), f"[4] u of A's true row 17 == 8.0 (got {arrays['u'][row17]})")
    check(arrays["card"].dtype == np.uint16 and arrays["u"].dtype == np.float32, "[4] uint16 / float32")
    check(arrays["card"][:140].tolist() == [1] * 140 and arrays["card"][140:280].tolist() == [2] * 140
          and arrays["card"][280:].tolist() == [0] * 4, "[4] card + 1: A 1, B 2, cap 0")
    check(float(arrays["u"][:140].max()) == 16.0 and float(arrays["u"][:140].min()) == 0.0, "[4] u spans 0 .. 16")

    # [5] follow
    w = np.asarray(record["follow"]["w"]).reshape(2, 17, -1)
    check(record["follow"]["bones"] == ["mixamorig:Head", "mixamorig:Neck", "mixamorig:Spine2"],
          f"[5] bones Head / Neck / Spine2 (got {record['follow']['bones']})")
    check(np.abs(w.sum(2) - 1).max() <= 1e-6, f"[5] rows sum to 1 (max err {np.abs(w.sum(2) - 1).max():.2e})")
    check(w[0, :2].tolist() == [[1, 0, 0]] * 2 and w[1, 0].tolist() == [1, 0, 0], "[5] pinned rows {Head: 1}")
    check(w[0, 16, 2] > 0.99, f"[5] A's tip (y 1.28, below the shoulder top 1.40) rides Spine2 (got {w[0, 16]})")

    # [6] the SDF payload
    s = record["sdf"]
    q = base64.b64decode(s["data"])
    check(len(q) == s["dims"][0] * s["dims"][1] * s["dims"][2] and s["order"] == "x_fastest"
          and s["unit"] == "mm_int8" and abs(s["vox"] - 2 * gf.VOX_M) < 1e-9,
          f"[6] payload dims {s['dims']}, vox {s['vox']}, x fastest, int8 mm")
    centre = hs.decode_sdf(s, [[0, 1.60, 0]])[0] * 1000
    inner = hs.decode_sdf(s, [[0, 1.60, 0.05]])[0] * 1000
    front = hs.decode_sdf(s, [[0, 1.60, 0.12]])[0] * 1000
    far = hs.decode_sdf(s, [[0, 2.5, 0]])[0] * 1000
    check(-94 <= centre <= -90 + 4 + 5.9, f"[6] decoded at the centre (cone apex) {centre:.1f} mm in [-94, -80.1]")
    check(abs(inner + 40) <= 4, f"[6] decoded at (0, 1.60, 0.05) {inner:.1f} mm == -40 +- 4")
    check(abs(front - 30) <= 4, f"[6] decoded at (0, 1.60, 0.12) {front:.1f} mm == +30 +- 4")
    check(abs(far - 127) < 1e-9, f"[6] outside the grid +127 mm (got {far})")
    # x fastest: the byte at (ix, iy, iz) is data[ix + nx * (iy + ny * iz)]
    nx, ny, nz = s["dims"]
    qa = np.frombuffer(q, np.int8)
    ix, iy, iz = nx // 2, ny // 2, nz // 2
    check(int(qa[ix + nx * (iy + ny * iz)]) == int(np.clip(round(sdf.field[2 * ix, 2 * iy, 2 * iz] * 1000), -127, 127)),
          "[6] byte (ix, iy, iz) == the field at (2ix, 2iy, 2iz)")

    # [7] boxes and parameters
    P = body.positions
    head_v = gf.dense_weights(body)[:, gf.joint_index(body, "head")] > 0.5
    chin = gf.chin_height(body)
    top = float(P[head_v, 1].max())
    cx, cz, _w, head_d = gh._head_box(P, head_v)
    lm = gh.head_landmarks(P, head_v, chin, top)
    brow = lm["brow_y"] if lm else top - 0.09
    want = [cx - 0.06, cx + 0.06, chin, brow + 0.01, cz + 0.25 * head_d]
    check(lm is None, "[7] a sphere shows no face (brow = top - 0.09)")
    check(np.allclose(record["face_box"], want, atol=1e-6), f"[7] face_box {record['face_box']} == {np.round(want, 5).tolist()}")
    check(record["params"] == hs.PARAMS["hairdeck"], "[7] params == PARAMS['hairdeck']")
    check(hs.PARAMS["haar"] == {**hs.PARAMS["hairdeck"], "root_deg": 0}, "[7] PARAMS['haar'] = root_deg 0")
    check(hs.PARAMS["hairdeck"]["root_deg"] == 10 and hs.PARAMS["hairdeck"]["iterations"] == 6
          and hs.PARAMS["hairdeck"]["tether_head"] == 0.012, "[7] the spec § 6.2.1 table")
    check(record["head_bone"] == "mixamorig:Head" and record["frame"] == "head_bind" and record["rows"] == 17
          and record["version"] == hs.RECORD_VERSION == 1, "[7] head_bone / frame / rows / version")
    check(record["vertex_attributes"] == {"card": "_STRAND_CARD", "u": "_STRAND_U"}, "[7] vertex_attributes")
    check(abs(record["ear_y"] - gf.ear_line_height(body)) < 1e-6, f"[7] ear_y {record['ear_y']}")
    check(record["capsules"]["version"] == 4 and isinstance(record["capsules"]["capsules"], list),
          f"[7] capsules v4 ({len(record['capsules']['capsules'])} capsules)")

    # [8] the cache
    json_path, npz_path = hs.sidecar_paths(fit)
    check(json_path.name == f"{ITEM}_{FSIG}.strands.json" and npz_path.name == f"{ITEM}_{FSIG}.strands.npz",
          f"[8] sidecars {json_path.name} / {npz_path.name}")
    data = json_path.read_bytes()
    check(data == hs.encode(record), "[8] the stored JSON is encode(record)")
    check(hs.current_sha(fit) == hashlib.sha256(data).hexdigest(), "[8] current_sha == sha256 of the stored bytes")
    m0 = (json_path.stat().st_mtime_ns, npz_path.stat().st_mtime_ns)
    again = hs.record_for_fit(CHAR, fit)
    check(again == record and (json_path.stat().st_mtime_ns, npz_path.stat().st_mtime_ns) == m0,
          "[8] a second record_for_fit reads the sidecars (mtimes unchanged)")
    old_sha = record["fit_sha256"]
    write_fit(target, cap_shift=0.001)
    check(hs.current_sha(fit) == "" and hs.vertex_arrays(fit) is None, "[8] a rewritten fit: the record is stale")
    new = hs.record_for_fit(CHAR, fit)
    check(new is not None and new["fit_sha256"] != old_sha
          and new["fit_sha256"] == hashlib.sha256(fit.read_bytes()).hexdigest() and new != record,
          "[8] a rewritten fit: a new record with the new fit_sha256")
    from app.core import garment_store as gs
    rec = gs.read_record(fit.with_suffix(".json"))
    gs.write_record(fit.with_suffix(".json"), {**rec, "method": "edit_chain"})
    check(hs.record_for_fit(CHAR, fit) is None, "[8] a fit of another method gets None")
    print(f"     record {len(data)} bytes, sdf dims {s['dims']}")
    gs.write_record(fit.with_suffix(".json"), rec)
    record = hs.record_for_fit(CHAR, fit)
    json_path, npz_path = hs.sidecar_paths(fit)

    # [9] Ruling H-R3: the sidecars belong to their fit
    check(gs.parse_name(json_path) == (ITEM, FSIG) and gs.parse_name(npz_path) == (ITEM, FSIG)
          and gs.parse_name(fit) == (ITEM, FSIG), "[9] parse_name: both sidecars name (item, fsig) like the fit")
    check(gs.is_strands_sidecar(json_path) and gs.is_strands_sidecar(npz_path) and not gs.is_strands_sidecar(fit)
          and not gs.is_strands_sidecar(fit.with_suffix(".json")), "[9] is_strands_sidecar: the two sidecars only")
    group = gs.stored_groups(CHAR).get((ITEM, FSIG), [])
    check({json_path, npz_path, fit, fit.with_suffix(".json")} <= set(group),
          f"[9] stored_groups: the fit's group holds both sidecars ({sorted(p.name for p in group)})")
    from app.core import artefact_graph
    nodes, unknown = artefact_graph.scan(CHAR)
    owner = [n for n in nodes if json_path in n.files and npz_path in n.files]
    check(len(owner) == 1 and owner[0].kind == "garment" and fit in owner[0].files
          and json_path not in unknown and npz_path not in unknown,
          "[9] artefact_graph.scan: the sidecars are files of the fit's garment node (deleted with it), not unknown")

    # [10] Ruling H-R4: the extension capsules of the body the fit was made on. A fake package declares the
    #      group "bump" with the one-link chain [mixamorig:Head]; the body's sidecar model3d/base0000abcd.json lists
    #      it as applied with op pair_protrusion. EXTENSION_CAPSULES["pair_protrusion"] has two entries (chest,
    #      chest_hair), so the record gains exactly two capsules, after the table's, with the ids "<group>:<bone>"
    #      and "<group>:<bone>:<region>" (bone = norm_bone_name("mixamorig:Head") = "head"):
    #      "bump:head", "bump:head:chest_hair". Without the sidecar (or with an outside op) none.
    from types import SimpleNamespace
    from app.plugins import loader
    base_ids = [c["id"] for c in record["capsules"]["capsules"]]
    check(not any(":" in i for i in base_ids), f"[10] a fit record without body_id: no extension capsule ({len(base_ids)})")
    fake = [SimpleNamespace(body_slots=[SimpleNamespace(rigs=[
        SimpleNamespace(id="bump", chains=[[{"bone": "mixamorig:Head", "parent": "Neck"}]])])])]
    real_declared = loader.declared_packages
    loader.declared_packages = lambda: fake
    try:
        model_dir = get_character_dir(CHAR) / "model3d"
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "base0000abcd.json").write_text(json.dumps({"extension_rig": {
            "status": "applied", "groups": ["bump"], "group_ops": {"bump": "pair_protrusion"}}}))
        gs.write_record(fit.with_suffix(".json"), {**rec, "body_id": "base0000abcd"})
        json_path.unlink()
        ext = hs.record_for_fit(CHAR, fit)
        ids = [c["id"] for c in ext["capsules"]["capsules"]] if ext else []
        check(ids == base_ids + ["bump:head", "bump:head:chest_hair"],
              f"[10] body_id with an applied pair_protrusion group: + bump:head, bump:head:chest_hair (got {ids[len(base_ids):]})")
        gs.write_record(fit.with_suffix(".json"), {**rec, "body_id": "base0000ffff"})
        json_path.unlink()
        none = hs.record_for_fit(CHAR, fit)
        check(none is not None and [c["id"] for c in none["capsules"]["capsules"]] == base_ids,
              "[10] a body_id without a model sidecar: the table's capsules only")
    finally:
        loader.declared_packages = real_declared
        gs.write_record(fit.with_suffix(".json"), rec)

    # [11] Ruling H-R5: the Hairstyles preview GLB carries the full tier's binding. preview_glb(fit) = the fit with
    #      _STRAND_CARD / _STRAND_U on the hair primitive, equal to the npz ([4]: 284 values, A 1, B 2, cap 0); the
    #      body and the hair's own attributes unchanged; version = sha256(fit)[:16] + ".s1" == preview_version(fit).
    #      A fit of another method: the stored bytes, version = content_version (no suffix).
    from app.core.http_files import content_version
    json_path.unlink()
    record = hs.record_for_fit(CHAR, fit)
    built = hs.preview_glb(CHAR, fit)
    fit_bytes = fit.read_bytes()
    want_version = hashlib.sha256(fit_bytes).hexdigest()[:16] + ".s1"
    check(built is not None and built[1] == want_version == hs.preview_version(fit),
          f"[11] preview version {built[1] if built else None} == sha16 + '.s1' == preview_version")
    arrays = hs.vertex_arrays(fit)
    served = glb_mesh.garment_arrays(built[0], node_prefix=NAME, exact=True)
    plain = glb_mesh.garment_arrays(fit_bytes, node_prefix=NAME, exact=True)
    extra = served.extra_attributes
    check(sorted(extra) == ["_STRAND_CARD", "_STRAND_U"] and extra["_STRAND_CARD"].dtype == np.uint16
          and np.array_equal(extra["_STRAND_CARD"], arrays["card"]) and np.array_equal(extra["_STRAND_U"], arrays["u"]),
          "[11] the preview's hair primitive carries _STRAND_CARD / _STRAND_U == the npz")
    check(np.array_equal(served.positions, plain.positions) and np.array_equal(served.indices, plain.indices)
          and np.array_equal(glb_mesh.body_arrays(built[0]).positions, glb_mesh.body_arrays(fit_bytes).positions)
          and not plain.extra_attributes, "[11] positions / faces / body unchanged; the stored fit has no binding")
    try:
        glb_mesh.add_vertex_attributes(built[0], {"_STRAND_U": arrays["u"]}, node_prefix=NAME)
        twice = False
    except ValueError:
        twice = True
    try:
        glb_mesh.add_vertex_attributes(fit_bytes, {"_STRAND_U": arrays["u"][:-1]}, node_prefix=NAME)
        short = False
    except ValueError:
        short = True
    check(twice and short, "[11] add_vertex_attributes refuses an attribute already there and a wrong length")
    gs.write_record(fit.with_suffix(".json"), {**rec, "method": "edit_chain"})
    other = hs.preview_glb(CHAR, fit)
    check(other == (fit_bytes, content_version(fit)) and hs.preview_version(fit) == content_version(fit),
          "[11] a fit of another method: the stored bytes, the plain content version")
    gs.write_record(fit.with_suffix(".json"), rec)

    print("PASS" if not FAILS else f"FAIL ({len(FAILS)})")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
