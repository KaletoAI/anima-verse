#!/usr/bin/env python3
"""Smoke: the cut skin's corner normals come from the source triangle that holds the face (Ruling A218).

Usage:
    ./.venv/bin/python scripts/smoke_mouth_normals.py

No server, no world, no Blender. Every expected number is derived by hand here. The pre-fix proof reads the pinned
commit baac1102c (``git show``).

The source: a = (0,0,0), b = (1,0,0), c = (0,1,0), d = (1,1,0); triangle 0 = (a, b, c) with corner normals all
(0,0,1), triangle 1 = (b, d, c) with corner normals b (1,0,0), d (1,0,0), c (0,1,0). The two triangles share the edge
b c, and their corner normals at b and c differ (split normals, as on the meshed faces). ``nearest`` is the first
triangle that contains the point (barycentric weights all >= 0), so a point ON the shared edge goes to triangle 0 —
a tie, as for the BVH in Blender, where the answer depends on the tree and changes from vertex to vertex.

[1] A face of triangle 1 (centre (2/3, 2/3, 0)) with a corner on the edge, p = (0.5, 0.5, 0): asked 0.02 of the way to
    the centre, (0.50333, 0.50333, 0), x + y > 1 -> triangle 1. p over (b, d, c): x = wb + wd = 0.5,
    y = wd + wc = 0.5, wb + wd + wc = 1 -> wd = 0, wb = wc = 0.5 -> 0.5 (1,0,0) + 0.5 (0,1,0) = (0.5, 0.5, 0)
    -> (0.70711, 0.70711, 0).
[2] A face of triangle 0 (centre (1/3, 1/3, 0)), same corner: asked at (0.49667, 0.49667, 0) -> triangle 0 -> (0,0,1).
[3] The rule before (asked at the corner itself): p lies on both triangles, the tie goes to triangle 0 -> (0,0,1) for
    the face of triangle 1 too, 90 degrees off [1]. Along a row of subdivision vertices on a source edge this pick
    flipped from vertex to vertex: the sawtooth band across Lirien's lips (corners more than 20 degrees off the
    source's shading 367 -> 26 of 10497 near the lip line, measured on a copy).
[4] A corner outside its triangle (p = (1.2, 0.5, 0), triangle 1 given): x = wb + wd = 1.2, y = wd + wc = 0.5,
    sum 1 -> wc = -0.2, wd = 0.7, wb = 0.5; clipped (0.5, 0.7, 0) / 1.2 -> all weight on b and d -> (1, 0, 0). Not
    clipped it would be (1.2, -0.2, 0) / |.| = (0.98639, -0.16440, 0).
[5] No triangle -> None.
[6] mouth_part: NORMAL_PROBE = 0.02 and restore_shading calls face_corner_normal with it; extension_rig's
    OP_BUILDS["mouth_part"] >= 9 (new normals = a new build: every humanoid's extension rig is due again).
[7] Pre-fix proof at baac1102c: restore_shading asked ``find_nearest(p)`` at the corner, and mouth_math had no
    face_corner_normal.
"""
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app" / "blender" / "scripts"))
import mouth_math as mm  # noqa: E402

PINNED = "baac1102c"
failed = 0


def check(label, ok, got=""):
    global failed
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else "  got: %r" % (got,)))
    failed += 0 if ok else 1


V = np.array([[0., 0, 0], [1., 0, 0], [0., 1, 0], [1., 1, 0]])
tris = np.array([[0, 1, 2], [1, 3, 2]])
normals = np.array([[[0., 0, 1], [0., 0, 1], [0., 0, 1]],
                    [[1., 0, 0], [1., 0, 0], [0., 1, 0]]])


def nearest(q):
    for i, t in enumerate(tris):
        if (mm.barycentric(np.asarray(q, float), *V[t]) >= -1e-12).all():
            return i
    return None


p = np.array([.5, .5, 0.])
got = mm.face_corner_normal(p, np.array([2 / 3, 2 / 3, 0.]), V, tris, normals, nearest)
check("[1] face of triangle 1 -> (0.70711, 0.70711, 0)", np.allclose(got, [.70711, .70711, 0], atol=1e-5), got)
got = mm.face_corner_normal(p, np.array([1 / 3, 1 / 3, 0.]), V, tris, normals, nearest)
check("[2] face of triangle 0 -> (0, 0, 1)", np.allclose(got, [0, 0, 1], atol=1e-12), got)
old = nearest(p)
w = mm.barycentric(p, *V[tris[old]])
n_old = w @ normals[old]
n_old = n_old / np.linalg.norm(n_old)
check("[3] the corner itself ties to triangle 0 -> (0, 0, 1) for the face of triangle 1", old == 0
      and np.allclose(n_old, [0, 0, 1]), (old, n_old))
got = mm.face_corner_normal(np.array([1.2, .5, 0.]), np.array([.9, .6, 0.]), V, tris, normals, lambda q: 1)
check("[4] clipped to the triangle -> (1, 0, 0)", np.allclose(got, [1, 0, 0], atol=1e-12), got)
raw = mm.barycentric(np.array([1.2, .5, 0.]), *V[tris[1]]) @ normals[1]
check("[4] unclipped it would be (0.98639, -0.16440, 0)",
      np.allclose(raw / np.linalg.norm(raw), [.98639, -.16440, 0], atol=1e-5), raw)
check("[5] no triangle -> None", mm.face_corner_normal(p, p, V, tris, normals, lambda q: None) is None)

part = (ROOT / "app" / "blender" / "scripts" / "mouth_part.py").read_text()
body = part[part.index("def restore_shading("):part.index("def _teeth_context(")]
check("[6] NORMAL_PROBE = .02", re.search(r"^NORMAL_PROBE = \.02\b", part, re.M) is not None)
check("[6] restore_shading uses face_corner_normal with NORMAL_PROBE",
      "face_corner_normal(" in body and "NORMAL_PROBE" in body and "find_nearest(p)" not in body)
rig = (ROOT / "app" / "core" / "extension_rig.py").read_text()
m = re.search(r'"mouth_part": (\d+)\}', rig)
check("[6] OP_BUILDS mouth_part >= 9", m is not None and int(m.group(1)) >= 9, m and m.group(1))


def show(path):
    return subprocess.run(["git", "show", "%s:%s" % (PINNED, path)], cwd=ROOT, capture_output=True,
                          text=True).stdout


old_part, old_math = show("app/blender/scripts/mouth_part.py"), show("app/blender/scripts/mouth_math.py")
old_body = old_part[old_part.index("def restore_shading("):old_part.index("def _teeth_context(")] if old_part else ""
check("[7] at %s restore_shading asked find_nearest(p) at the corner" % PINNED, "find_nearest(p)" in old_body)
check("[7] at %s mouth_math had no face_corner_normal" % PINNED,
      bool(old_math) and "def face_corner_normal" not in old_math)

print("FAILED %d" % failed if failed else "all ok")
sys.exit(1 if failed else 0)
