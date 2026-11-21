"""Smoke: a point beyond an OPEN edge of the drape's collider is outside (``gd.signed_out`` with ``gd.collider_tree``).

Usage:
    ./.venv/bin/python scripts/smoke_collider_rim.py

No server, no world DB, no LLM, no hub job. The checks need ``mathutils`` and ``bpy`` and therefore run this same file
inside Blender (``runner.find_executable``, after ``paths.init`` into a temp dir); without a usable Blender the
script fails, because nothing was checked. Every collider below is made of boxes by hand, so every expected number is
arithmetic, not a recording.

Why (bug round 2026-11-21, Tilda's blouse refused with stretch_max 2.298): ``drop_outer_shells`` (A236) cuts the
hair lying on the shoulders out of the voxel collider and leaves an OPEN edge there. A pinned yoke vertex stood
7.95 mm outside, beside that edge, 0.47 mm under the plane of the one face at it. ``signed_out`` decided "inside" by
that face's side alone, and which of the faces meeting there the BVH returned differed between the clearance pass's
tree and ``drape``'s cropped one: the clearance read it 7.95 mm out, the pre-inflate in ``drape`` read it 0.66 mm IN
and moved the PINNED vertex 11.1 mm after the rest lengths were taken — its 7.26 mm edge to the next pinned vertex
became 16.68 mm = 2.298.

Collider O ("open box") = the box x, y in [0, 1], z in [-1, 0], wound outward, WITHOUT its +x side face (the cut);
its 4 boundary edges are that face's edges. Collider C = the same box closed.

[R1] ``rim_segments``: C -> {} (closed). O -> the faces with a vertex on the open edge: top, bottom, the y = 0 and the
     y = 1 side = 4 faces; the -x side has no such vertex. The top face's corners (1, 0, 0) and (1, 1, 0) each touch 2
     boundary edges -> 4 segments (the edge between them twice).
[R2] p = (1.008, 0.5, -0.0005) — 8 mm beyond the cut edge, 0.5 mm under the top face's plane (Tilda's case). Nearest
     point (1, 0.5, 0) on the open edge, distance sqrt(8^2 + 0.5^2) = sqrt(64.25) = 8.0156 mm.
     * the raw BVH of O (what ``signed_out`` got before: no rim) -> offset . top normal = -0.5 mm ("inside");
     * ``collider_tree(O)`` -> +8.0156 mm, outside, direction = the offset (0.998, 0, -0.0624).
[R3] p = (0.5, 0.5, -0.005) — 5 mm under the top face's MIDDLE of O (the top is a rim face, but its nearest point is
     no rim point) -> -5.0 mm, inside as before.
[R4] p = (1.02, 0.5, 0.01) on C (A178's case, ``smoke_a179_bodice_geometry`` [B1]) -> +22.36 mm, unchanged; and
     p = (1.008, 0.5, -0.0005) on C: the +x side face is there, 8 mm in front of it (x 1.008 > 1) -> the nearest
     point is (1, 0.5, -0.0005) on that face's middle, +8.0 mm. The rim rule changes nothing on a closed collider.
[R5] the same as R2 on O with its faces in REVERSED order (as ``drape``'s crop rebuilds the collider) -> +8.0156 mm:
     the answer no longer depends on which face the BVH returns.
[R6] ``signed_depth`` over ``collider_tree(O)`` for the points of R2 and R3 -> [+8.0156, -5.0] mm.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILS = []


def check(label, ok, got=None):
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else f"  (got {got!r})"))
    if not ok:
        FAILS.append(label)


def near(a, b, tol):
    return a is not None and abs(a - b) <= tol


def in_blender():
    import bpy
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    sys.path.insert(0, str(ROOT / "app" / "blender" / "scripts"))
    import garment_template_drape as gd

    bpy.ops.wm.read_factory_settings(use_empty=True)
    verts = [(0, 0, -1), (1, 0, -1), (1, 1, -1), (0, 1, -1), (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    faces = {"bottom": (0, 3, 2, 1), "top": (4, 5, 6, 7), "y0": (0, 1, 5, 4), "x1": (1, 2, 6, 5),
             "y1": (2, 3, 7, 6), "x0": (3, 0, 4, 7)}

    def obj(name, keys):
        me = bpy.data.meshes.new(name)
        me.from_pydata([Vector(v) for v in verts], [], [faces[k] for k in keys])
        me.update()
        ob = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(ob)
        return ob, keys

    open_keys = ["bottom", "top", "y0", "y1", "x0"]
    o, okeys = obj("open", open_keys)
    c, _ckeys = obj("closed", list(faces))
    r, _rkeys = obj("open_reversed", list(reversed(open_keys)))
    bpy.context.view_layer.update()

    # [R1]
    check("[R1] a closed collider has no rim", gd.rim_segments(c) == {}, gd.rim_segments(c))
    rim = gd.rim_segments(o)
    named = sorted(okeys[i] for i in rim)
    check("[R1] the faces at the open edge: bottom, top, y0, y1", named == ["bottom", "top", "y0", "y1"], named)
    check("[R1] the top face carries 4 segments", len(rim.get(okeys.index("top"), ())) == 4,
          len(rim.get(okeys.index("top"), ())))

    def depth(tree, p):
        p = Vector(p)
        loc, out = gd.signed_out(tree, p, 0.1)
        return None if loc is None else (p - loc).dot(out) * 1000, out

    # [R2]
    p2 = (1.008, 0.5, -0.0005)
    raw = BVHTree.FromObject(o, bpy.context.evaluated_depsgraph_get())
    d, _o = depth(raw, p2)
    check("[R2] without the rim the face's side reads -0.5 mm (the old answer)", near(d, -0.5, 1e-3), d)
    d, out = depth(gd.collider_tree(o), p2)
    check("[R2] beyond the open edge: +8.0156 mm", near(d, 8.0156, 1e-3), d)
    check("[R2] pushed along the offset (0.998, 0, -0.0624)",
          near(out.x, 0.998, 1e-3) and near(out.y, 0.0, 1e-6) and near(out.z, -0.0624, 1e-3), tuple(out))
    # [R3]
    d, _o = depth(gd.collider_tree(o), (0.5, 0.5, -0.005))
    check("[R3] under the top face's middle: -5.0 mm", near(d, -5.0, 1e-3), d)
    # [R4]
    d, _o = depth(gd.collider_tree(c), (1.02, 0.5, 0.01))
    check("[R4] closed, off its edge: +22.36 mm", near(d, 22.36, 0.01), d)
    d, _o = depth(gd.collider_tree(c), p2)
    check("[R4] closed, in front of the +x side: +8.0 mm", near(d, 8.0, 1e-3), d)
    # [R5]
    d, _o = depth(gd.collider_tree(r), p2)
    check("[R5] faces in reversed order: +8.0156 mm", near(d, 8.0156, 1e-3), d)
    # [R6]
    sd = gd.signed_depth(gd.collider_tree(o), [p2, (0.5, 0.5, -0.005)])
    check("[R6] signed_depth [+8.0156, -5.0] mm", near(sd[0] * 1000, 8.0156, 1e-3) and near(sd[1] * 1000, -5.0, 1e-3),
          list(sd))


def main():
    try:
        import bpy  # noqa: F401
    except ImportError:
        bpy = None
    if bpy is not None:
        in_blender()
        print("FAILED: " + ", ".join(FAILS) if FAILS else "blender part passed")
        sys.exit(1 if FAILS else 0)
    sys.path.insert(0, str(ROOT))
    from app.core import paths
    paths.init(tempfile.mkdtemp(prefix="smoke-rim-"))
    from app.blender import runner
    exe = runner.find_executable()
    if not exe:
        check("a usable Blender to run the checks", False, "none found")
    else:
        res = subprocess.run([exe, "--background", "--factory-startup", "--python-exit-code", "1", "--python",
                              str(Path(__file__).resolve())], capture_output=True, text=True, timeout=300)
        lines = [ln for ln in res.stdout.splitlines() if ln.startswith(("ok   ", "FAIL ", "blender part", "FAILED"))]
        print("\n".join(lines))
        seen = sum(1 for ln in lines if ln.startswith("ok   "))
        check(f"the checks ran in Blender and passed ({seen} checks)", res.returncode == 0 and seen >= 11,
              (res.returncode, seen, res.stderr[-400:]))
    print()
    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL CHECKS PASSED")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
