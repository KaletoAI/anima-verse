"""Smoke: A198 — the garment template's texture projection, bake pose and lower-layer collider (review 03 #1, #3, #4).

Usage:
    ./.venv/bin/python scripts/smoke_template_bake_a198.py

No server, no world DB, no hub job. Runs this same file inside Blender (``runner.find_executable``; without a usable
Blender the checks are reported as SKIPPED and the script fails). Every mesh is built by hand, so every expectation
is arithmetic, not a recording.

[1] project_bake after a Solidify. A unit quad x, z in [0, 1] at y = 0, wound (0,0,0) (1,0,0) (1,0,1) (0,0,1):
    normal (1,0,0) x (1,0,1) = (0, -1, 0) — it faces the front camera (-Y). UV = (x, z). Solidify 1.5 mm, offset 1
    (as the build): F = 1 face before, the copy layer shares the UVs and faces +Y. Front view all red, back view
    all blue (alpha 1). The texel at UV (0.5, 0.5) must be RED with ``polys=F`` (only layer 0 projected). Without
    ``polys`` the last write wins: the copy (faces +Y -> "back", blue) — the mirrored-print bug (pre-fix e846d7d02
    always projected every face).
[2] set_pose("_bake") with POSES["_bake"] = LeftArm Y 0 deg: every pose bone stays at rest (matrix_basis identity).
    Pre-fix ARMS_DOWN was appended (LeftArm Y 30 deg, LeftForeArm X -20 deg), so a "0 deg" try was 30 deg.
[3] _join_extra with a closed two-layer lower: body = closed cylinder r 0.15 (64 sides, z 0..1), lower = open tube
    r 0.20 (64 sides, z 0.2..0.8) solidified 1.5 mm offset 1 -> a closed shell between r 0.2000 and 0.2015 (the
    outer layer pushed out along the outward normal). After _join_extra (EXTRA_SOLID_M 8 mm, offset -1) every
    collider vertex farther than 0.17 from the axis must lie within [0.2015 - 0.008, 0.2015] (+-0.5 mm; a facet's
    middle is 0.2015 * cos(pi/64) = 0.20126 at least): the outer layer thickened INWARD. Pre-fix the inner layer
    (facing the body) grew outward: max r = 0.2000 + 0.008 = 0.208.
"""
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILS = []


def check(label, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILS.append(label)


def part_b():
    import bpy
    import numpy as np
    sys.path.insert(0, str(ROOT / "app" / "blender" / "scripts"))
    import garment_template_drape as gd

    tmp = Path(tempfile.mkdtemp(prefix="a198-bake-"))
    # [1]
    for name, rgb in (("front", (1, 0, 0, 1)), ("back", (0, 0, 1, 1))):
        im = bpy.data.images.new(name, 8, 8, alpha=True)
        im.pixels[:] = list(rgb) * 64
        im.filepath_raw = str(tmp / f"{name}.png")
        im.file_format = "PNG"
        im.save()
    views = {"view_front": str(tmp / "front.png"), "view_back": str(tmp / "back.png")}

    def quad():
        me = bpy.data.meshes.new("q")
        me.from_pydata([(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)], [], [(0, 1, 2, 3)])
        uvl = me.uv_layers.new(name="UVMap")
        for lp in me.loops:
            co = me.vertices[lp.vertex_index].co
            uvl.data[lp.index].uv = (co.x, co.z)
        obj = bpy.data.objects.new("q", me)
        bpy.context.scene.collection.objects.link(obj)
        n_single = len(me.polygons)
        sol = obj.modifiers.new("sol", "SOLIDIFY")
        sol.thickness = 0.0015
        sol.offset = 1
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=sol.name)
        return obj, n_single

    def centre_texel(path):
        im = bpy.data.images.load(str(path))
        px = np.array(im.pixels[:]).reshape(im.size[1], im.size[0], 4)
        return px[im.size[1] // 2, im.size[0] // 2, :3]

    obj, f_single = quad()
    check("[1] one face before the Solidify", f_single == 1, f_single)
    gd.project_bake(obj, views, tmp / "layer0.png", size=64, polys=f_single)
    c = centre_texel(tmp / "layer0.png")
    check("[1] layer 0 only: the front texel is red", c[0] > 0.9 and c[2] < 0.1, c)
    obj2, _ = quad()
    gd.project_bake(obj2, views, tmp / "all.png", size=64)
    c = centre_texel(tmp / "all.png")
    check("[1] every face (the old call): the copy paints it blue", c[2] > 0.9 and c[0] < 0.1, c)

    # [2]
    arm_data = bpy.data.armatures.new("arm")
    arm = bpy.data.objects.new("arm", arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for name, head, tail, parent in (("LeftArm", (0.2, 0, 1.4), (0.45, 0, 1.4), None),
                                     ("LeftForeArm", (0.45, 0, 1.4), (0.7, 0, 1.4), "LeftArm")):
        eb = arm_data.edit_bones.new(gd.P + name)
        eb.head, eb.tail = head, tail
        if parent:
            eb.parent = arm_data.edit_bones[gd.P + parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    gd.POSES["_bake"] = [("LeftArm", "Y", 0), ("RightArm", "Y", 0)]
    gd.set_pose(arm, "_bake")
    dev = max(float(np.abs(np.array(pb.matrix_basis) - np.eye(4)).max()) for pb in arm.pose.bones)
    check("[2] a 0 deg bake try leaves the arms at rest", dev < 1e-6, dev)

    # [3]
    def cylinder(name, r, z0, z1, closed):
        n = 64
        verts = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n), z)
                 for z in (z0, z1) for i in range(n)]
        faces = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
        if closed:
            faces += [tuple(reversed(range(n))), tuple(range(n, 2 * n))]
        me = bpy.data.meshes.new(name)
        me.from_pydata(verts, [], faces)
        me.update()
        obj = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(obj)
        return obj

    body = cylinder("body", 0.15, 0.0, 1.0, True)
    lower = cylinder("lower", 0.20, 0.2, 0.8, False)
    rad = [math.hypot(*np.array(lower.data.vertices[0].co)[:2])]
    sol = lower.modifiers.new("sol", "SOLIDIFY")
    sol.thickness = 0.0015
    sol.offset = 1
    bpy.context.view_layer.objects.active = lower
    bpy.ops.object.modifier_apply(modifier=sol.name)
    r = np.hypot(*np.array([v.co[:2] for v in lower.data.vertices]).T)
    check("[3] the lower is a shell 0.2000 .. 0.2015",
          abs(r.min() - 0.2) < 1e-4 and abs(r.max() - 0.2015) < 1e-4, (rad, r.min(), r.max()))
    dg = bpy.context.evaluated_depsgraph_get()
    col = bpy.data.objects.new("collider", bpy.data.meshes.new_from_object(body.evaluated_get(dg)))
    bpy.context.scene.collection.objects.link(col)
    gd._join_extra(col, lower, dg)
    rc = np.hypot(*np.array([v.co[:2] for v in col.data.vertices]).T)
    ext = rc[rc > 0.17]
    check("[3] the collider of the lower lies within 0.1935 .. 0.2015",
          len(ext) and ext.max() <= 0.2015 + 5e-4 and ext.min() >= 0.2015 - 0.008 - 5e-4,
          (len(ext), float(ext.min()) if len(ext) else None, float(ext.max()) if len(ext) else None))


def main():
    try:
        import bpy  # noqa: F401
        inside = True
    except ImportError:
        inside = False
    if inside:
        part_b()
        print("FAILED: " + ", ".join(FAILS) if FAILS else "part B passed")
        sys.exit(1 if FAILS else 0)
    sys.path.insert(0, str(ROOT))
    from app.blender import runner
    exe = runner.find_executable()
    if not exe:
        check("a usable Blender (SKIPPED)", False, "none found")
    else:
        res = subprocess.run([exe, "--background", "--factory-startup", "--python-exit-code", "1",
                              "--python", str(Path(__file__).resolve())], capture_output=True, text=True, timeout=300)
        lines = [ln for ln in res.stdout.splitlines() if ln.startswith(("ok   ", "FAIL ", "part B", "FAILED"))]
        print("\n".join(lines))
        seen = sum(1 for ln in lines if ln.startswith("ok   "))
        check(f"part B ran in Blender and passed ({seen} checks)", res.returncode == 0 and seen >= 6,
              (res.returncode, seen, res.stderr[-600:]))
    print()
    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL CHECKS PASSED")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
