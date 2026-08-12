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
