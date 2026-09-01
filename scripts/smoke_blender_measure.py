#!/usr/bin/env python3
"""Numeric check of the Blender runner and the `measure` script.

Usage:
    ./.venv/bin/python scripts/smoke_blender_measure.py

Needs Blender (auto-discovered, or image_generation.blender_executable), no
server and no world DB. Works entirely in a temp directory — no store is read
or written.

The expected numbers are DERIVED BY HAND here, not recorded from a run:

  Fixture A — a cube from `primitive_cube_add(size=2)` moved to (0.5, -1.5, 3).
    size=2 means edge length 2 m, so the box is 2 x 2 x 2 m.
    A cube has 6 quad faces; a quad is 2 triangles -> 12 tris.
    Vertices are NOT 8. glTF stores one attribute set per vertex, so a corner
    can only be shared by faces that agree on every attribute — and the three
    faces meeting at a cube corner each have their own normal. Every corner is
    therefore stored once per adjacent face: 8 * 3 = 24. (This is why `tris`
    is the count worth comparing across formats and `verts` is not.)
    Moving it does not change its size, so:
        dims_m    = [2, 2, 2]
        center_xy = [0.5, -1.5]        (the move, unchanged)
        min_z     = 3 - (2 / 2) = 2    (centre minus half the height)
        verts     = 24, tris = 12,  bones = 0,  vertex_colors = 0

  Fixture B — a cylinder, `primitive_cylinder_add(vertices=24, radius=0.35,
  depth=1.75)`, left at the origin.
    radius 0.35 m -> the bounding box spans the full diameter 0.70 m in x and y.
    depth is the full height, so 1.75 m in z, centred on the origin:
        dims_m    = [0.70, 0.70, 1.75]
        center_xy = [0, 0]
        min_z     = -1.75 / 2 = -0.875
    Triangle count is NOT asserted: the two end caps are 24-gons, and how many
    triangles those become is the triangulator's business, not the spec's.

  Fixture C — a cube with its UV map removed and a colour attribute added.
    This is the Triposplat signature the pipeline has to recognise:
        uv_layers = 0  AND  vertex_colors >= 1

  Fixture D — a "no fingers" hand: an armature of THREE bones named the Mixamo
  way (LeftHand, LeftHandThumb1, LeftHandIndex1) skinning a cube of size 0.2,
  every corner weighted 1.0 to the HAND bone only.
    Two bone names carry a finger token (Thumb, Index), so finger_bones = 2 —
    yet no finger bone owns a vertex, which is exactly what a "No fingers"
    bake looks like: the bones are there, the hand moves as one block.
        bones = 3, mixamo_bones = 3
        finger_bones = 2, finger_bones_weighted = 0, finger_verts = 0

  Fixture E — the same hand with four of the eight corners re-weighted 1.0 to
  the THUMB bone instead.
    One finger bone now drives mesh -> finger_bones_weighted = 1 (the index
    bone still owns nothing). The driven vertices are counted AS STORED, and
    glTF splits every cube corner into 3 (see fixture A), so the four thumb
    corners read 4 * 3 = 12:
        finger_bones = 2, finger_bones_weighted = 1, finger_verts = 12

Tolerance is 1e-4 m — the measurement rounds to four decimals, and a glTF
round-trip stores floats, so exact equality would be a test of float32.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.blender import runner                                # noqa: E402

TOL = 1e-4

# Builds the three fixtures as GLB files. Runs in Blender, so it may only use
# bpy and the standard library.
FIXTURE_SCRIPT = r'''
import bpy, sys
out = sys.argv[sys.argv.index("--") + 1]

def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)

fresh()
bpy.ops.mesh.primitive_cube_add(size=2, location=(0.5, -1.5, 3))
bpy.ops.export_scene.gltf(filepath=out + "/a.glb", export_format="GLB")

fresh()
bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.35, depth=1.75)
bpy.ops.export_scene.gltf(filepath=out + "/b.glb", export_format="GLB")

fresh()
bpy.ops.mesh.primitive_cube_add(size=2)
me = bpy.context.object.data
while me.uv_layers:
    me.uv_layers.remove(me.uv_layers[0])
me.color_attributes.new(name="Col", type="BYTE_COLOR", domain="CORNER")
bpy.ops.export_scene.gltf(filepath=out + "/c.glb", export_format="GLB")

# A three-bone "hand" skinning a small cube. thumb_corners: which of the 8
# cube corners belong to the thumb bone; the rest belong to the hand bone.
def hand(path, thumb_corners):
    fresh()
    arm = bpy.data.armatures.new("Armature")
    arm_obj = bpy.data.objects.new("Armature", arm)
    bpy.context.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="EDIT")
    hand_b = arm.edit_bones.new("mixamorig:LeftHand")
    hand_b.head, hand_b.tail = (0, 0, 0), (0, 0, 0.1)
    for name, tip in (("mixamorig:LeftHandThumb1", 0.15),
                      ("mixamorig:LeftHandIndex1", 0.16)):
        b = arm.edit_bones.new(name)
        b.head, b.tail = (0, 0, 0.1), (0, 0, tip)
        b.parent = hand_b
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.mesh.primitive_cube_add(size=0.2)
    cube = bpy.context.object
    cube.parent = arm_obj
    cube.modifiers.new("Armature", "ARMATURE").object = arm_obj
    hand_vg = cube.vertex_groups.new(name="mixamorig:LeftHand")
    hand_vg.add([i for i in range(8) if i not in thumb_corners], 1.0, "REPLACE")
    if thumb_corners:
        thumb_vg = cube.vertex_groups.new(name="mixamorig:LeftHandThumb1")
        thumb_vg.add(list(thumb_corners), 1.0, "REPLACE")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB")

hand(out + "/d.glb", [])
hand(out + "/e.glb", [0, 1, 2, 3])
print("FIXTURES_OK")
'''

failures = []


def check(label, got, want, tol=0.0):
    ok = (abs(got - want) <= tol) if tol else (got == want)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got}, want {want}")
    if not ok:
        failures.append(label)


def check_vec(label, got, want, tol=TOL):
    ok = len(got) == len(want) and all(abs(g - w) <= tol for g, w in zip(got, want))
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got}, want {want}")
    if not ok:
        failures.append(label)


def main():
    st = runner.status()
    print(f"Blender: {st['executable'] or '(none found)'} {st['version']}")
    if not st["executable"]:
        print("FAIL: no Blender executable — set image_generation.blender_executable")
        return 1

    with tempfile.TemporaryDirectory(prefix="smoke-blender-") as tmp:
        script = Path(tmp) / "fixtures.py"
        script.write_text(FIXTURE_SCRIPT, encoding="utf-8")
        proc = subprocess.run(
            [st["executable"], "--background", "--factory-startup",
             "--python", str(script), "--", tmp],
            capture_output=True, text=True, timeout=180)
        if "FIXTURES_OK" not in proc.stdout:
            print("FAIL: fixtures could not be built")
            print(proc.stdout[-2000:], proc.stderr[-2000:])
            return 1

        print("\nFixture A — cube 2x2x2 m at (0.5, -1.5, 3)")
        a = runner.run("measure", inputs={"model": Path(tmp) / "a.glb"})
        if not a["ok"]:
            print(f"FAIL: {a['error']}")
            return 1
        d = a["data"]
        check_vec("dims_m", d["dims_m"], [2.0, 2.0, 2.0])
        check_vec("center_xy", d["center_xy"], [0.5, -1.5])
        check("min_z", d["min_z"], 2.0, TOL)
        check("verts", d["verts"], 24)
        check("tris", d["tris"], 12)
        check("bones", d["bones"], 0)
        check("vertex_colors", d["vertex_colors"], 0)

        print("\nFixture B — cylinder r=0.35 m, h=1.75 m at the origin")
        b = runner.run("measure", inputs={"model": Path(tmp) / "b.glb"})
        if not b["ok"]:
            print(f"FAIL: {b['error']}")
            return 1
        d = b["data"]
        check_vec("dims_m", d["dims_m"], [0.70, 0.70, 1.75])
        check_vec("center_xy", d["center_xy"], [0.0, 0.0])
        check("min_z", d["min_z"], -0.875, TOL)

        print("\nFixture C — Triposplat signature (no UVs, colour in vertices)")
        c = runner.run("measure", inputs={"model": Path(tmp) / "c.glb"})
        if not c["ok"]:
            print(f"FAIL: {c['error']}")
            return 1
        d = c["data"]
        check("uv_layers", d["uv_layers"], 0)
        print(f"  {'ok  ' if d['vertex_colors'] >= 1 else 'FAIL'} "
              f"vertex_colors: got {d['vertex_colors']}, want >= 1")
        if d["vertex_colors"] < 1:
            failures.append("vertex_colors")

        print("\nFixture D — 'no fingers' hand: finger bones present, none drives mesh")
        dd = runner.run("measure", inputs={"model": Path(tmp) / "d.glb"})
        if not dd["ok"]:
            print(f"FAIL: {dd['error']}")
            return 1
        d = dd["data"]
        check("bones", d["bones"], 3)
        check("mixamo_bones", d["mixamo_bones"], 3)
        check("finger_bones", d["finger_bones"], 2)
        check("finger_bones_weighted", d["finger_bones_weighted"], 0)
        check("finger_verts", d["finger_verts"], 0)

        print("\nFixture E — rigged thumb: 4 corners on the thumb bone")
        e = runner.run("measure", inputs={"model": Path(tmp) / "e.glb"})
        if not e["ok"]:
            print(f"FAIL: {e['error']}")
            return 1
        d = e["data"]
        check("finger_bones", d["finger_bones"], 2)
        check("finger_bones_weighted", d["finger_bones_weighted"], 1)
        check("finger_verts", d["finger_verts"], 12)

        print("\nRunner contract")
        miss = runner.run("measure", inputs={"model": Path(tmp) / "nope.glb"})
        check("missing input -> ok False", miss["ok"], False)
        unknown = runner.run("no_such_script", inputs={"model": Path(tmp) / "a.glb"})
        check("unknown script -> ok False", unknown["ok"], False)
        # A script that produces files must be given somewhere to put them;
        # measure declares none, so this must NOT trip.
        check("measure declares no outputs", len(a["outputs"]), 0)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
