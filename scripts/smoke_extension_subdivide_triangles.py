"""Smoke: the subdivision under an extension tip leaves only triangles (A199, review 03#8).

Usage:
    ./.venv/bin/python scripts/smoke_extension_subdivide_triangles.py            # the working tree's script
    ./.venv/bin/python scripts/smoke_extension_subdivide_triangles.py --at 26977eda5   # pre-fix proof

Needs a Blender (``app.blender.runner.find_executable``); no server, no world DB, no instance config.

``extension_bones.subdivide_where`` cuts every edge whose midpoint a predicate accepts (``subdivide_edges``,
cuts=1, grid fill, flat). Derived by hand from that operator on a triangulated grid: a triangle INSIDE the region has
all three edges cut and becomes four triangles; a triangle on the RIM with exactly one cut edge A-B becomes the
quad (A, M, B, C) with M the midpoint of A-B — three corners on one line. Before A199 the follow-up triangulate took
only faces with MORE THAN 4 corners, so that quad survived; its fan triangle (A, M, B) has zero area. So, on a 20x20
grid (each square split into two triangles) and two passes (radius 0.30, then 0.15, around the centre):

  [1] faces with more than 3 corners after the passes: 0 (every face with > 3 corners is triangulated);
  [2] loop triangles with area below 1e-12: 0;
  [3] deform weights of the new vertices still sum to one (the function's own guard raises otherwise).

Pre-fix proof: at 26977eda5 [1] reads > 0 (the rim quads) — run with ``--at 26977eda5``.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROBE = r'''
import sys, json
sys.path.insert(0, SCRIPTS)
import bpy, bmesh
import extension_bones as eb
from mathutils import Vector
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_grid_add(x_subdivisions=20, y_subdivisions=20, size=2.0)
obj = bpy.context.active_object
bm = bmesh.new(); bm.from_mesh(obj.data)
bmesh.ops.triangulate(bm, faces=bm.faces[:]); bm.to_mesh(obj.data); bm.free()
arm = bpy.data.armatures.new("A"); rig = bpy.data.objects.new("R", arm)
bpy.context.scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode="EDIT")
b = arm.edit_bones.new("Root"); b.head = (0, 0, 0); b.tail = (0, 0, 1)
bpy.ops.object.mode_set(mode="OBJECT")
g = obj.vertex_groups.new(name="Root"); g.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
m = obj.modifiers.new("Armature", "ARMATURE"); m.object = rig
c = Vector((0.0, 0.0, 0.0))
eb.subdivide_where(obj, [lambda p: (p - c).length <= 0.30, lambda p: (p - c).length <= 0.15])
me = obj.data
me.calc_loop_triangles()
over3 = sum(1 for f in me.polygons if len(f.vertices) > 3)
flat = sum(1 for t in me.loop_triangles if t.area < 1e-12)
print("RESULT " + json.dumps({"over3": over3, "flat": flat, "faces": len(me.polygons)}))
'''

FAILED = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILED.append(label)


def main() -> int:
    from app.blender import runner
    exe = runner.find_executable()
    if not exe:
        print("SKIP no Blender found")
        return 0
    at = sys.argv[sys.argv.index("--at") + 1] if "--at" in sys.argv else None
    with tempfile.TemporaryDirectory(prefix="smoke-ext-subdiv-") as tmp:
        scripts = ROOT / "app" / "blender" / "scripts"
        if at:
            scripts = Path(tmp)
            data = subprocess.run(["git", "-C", str(ROOT), "show", f"{at}:app/blender/scripts/extension_bones.py"],
                                  check=True, capture_output=True).stdout
            (scripts / "extension_bones.py").write_bytes(data)
            # _common finds the app root from its own resolved path: link the working tree's
            (scripts / "_common.py").symlink_to(ROOT / "app" / "blender" / "scripts" / "_common.py")
        probe = Path(tmp) / "probe.py"
        probe.write_text(f"SCRIPTS = {str(scripts)!r}\n" + PROBE)
        out = subprocess.run([exe, "--background", "--factory-startup", "--python-exit-code", "1",
                              "--python", str(probe)], capture_output=True, text=True, timeout=300)
    line = next((ln for ln in out.stdout.splitlines() if ln.startswith("RESULT ")), None)
    check("probe ran", line is not None, (out.stdout + out.stderr)[-2000:])
    if line is None:
        return 1
    res = json.loads(line[7:])
    print(f"     {res}" + (f" (at {at})" if at else ""))
    check("[1] no face with more than 3 corners", res["over3"] == 0, res["over3"])
    check("[2] no zero-area loop triangle", res["flat"] == 0, res["flat"])
    print("[3] deform weights: subdivide_where's own guard did not raise")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
