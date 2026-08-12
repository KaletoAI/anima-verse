#!/usr/bin/env python3
"""Numeric check of the `normalize` script (plan-blender-veredelung.md § 2.6).

Usage:
    ./.venv/bin/python scripts/smoke_blender_normalize.py

Needs Blender (auto-discovered, or image_generation.blender_executable), no
server and no world DB. Works entirely in a temp directory — no store is read
or written. The result is verified BY RE-MEASURING the produced file with the
independent `measure` script, not by trusting what `normalize` reports.

The expected numbers are DERIVED BY HAND here, not recorded from a run:

  Fixture A — crown basis (the Mixamo case).
    A cube of 0.6 x 0.3 x 2.2 m with its centre at (0.4, -0.2, 1.4), so the
    box spans z 0.3..2.5 — it hovers 0.3 m above the ground and sits off
    centre. One bone named `mixamorig:HeadTop_End` with its head at world
    z 2.3; every vertex is skinned to it (glTF only round-trips bones that
    skin something). The 0.2 m of box above the crown play the hair.

    normalize(target_height_m=1.70) must measure at the CROWN, not the box:
        height_now = crown 2.3 - box bottom 0.3          = 2.0 m
        scale      = 1.70 / 2.0                          = 0.85
        dims_m     = [0.6, 0.3, 2.2] * 0.85              = [0.51, 0.255, 1.87]
        min_z      = 0            (grounded — was 0.3)
        center_xy  = [0, 0]       (centred — was [0.4, -0.2])
        tris       = 12           (a cube, untouched by normalising)
        joints     = 1
    The bounding-box height 1.87 m is ON PURPOSE taller than the target: the
    figure's BODY is 1.70 m, the rest is hair. A bounding-box scale would have
    shrunk the body to 1.70 * (2.0/2.2) = 1.545 m — the defect this basis
    exists to end.

  Fixture B — bounding-box basis (no rig).
    The cylinder from smoke_blender_measure: r=0.35, depth=1.75, at the
    origin. No armature, so the box is the only basis:
        height_now = 1.75
        scale      = 2.0 / 1.75                          = 1.142857
        dims_m     = [0.70, 0.70, 1.75] * scale          = [0.8, 0.8, 2.0]
        min_z      = 0            (was -0.875)
        center_xy  = [0, 0]

  Fixture C — crown ESTIMATE (the gateway case: `Head` exists, no
  `HeadTop_End`). A box 0.5 x 0.5 x 2.0 m standing on the origin, one bone
  `mixamorig:Head` with its head at z 1.4 — head ratio 1.4 / 2.0 = 0.7,
  below the 0.80 trust band, so the box counts as inflated by headwear:
        height_now = 1.4 / 0.875                         = 1.6
        scale      = 1.6 / 1.6                           = 1.0   (target 1.6)
        dims_m     = [0.5, 0.5, 2.0]  (unchanged — the point of the basis:
                     the BODY is already 1.6 m, the 0.4 m above the crown
                     stay above it instead of shrinking everything)
        min_z      = 0, center_xy = [0, 0]

Tolerance 1e-3 m: the measurement rounds to four decimals and a glTF
round-trip stores float32; exact equality would test the float format.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.blender import runner                                # noqa: E402

TOL = 1e-3

# Builds the two fixtures as GLB files. Runs in Blender, so it may only use
# bpy and the standard library.
FIXTURE_SCRIPT = r'''
import bpy, sys
out = sys.argv[sys.argv.index("--") + 1]

def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)

# A: skinned cube, crown joint 0.2 m below the top of the box.
fresh()
bpy.ops.mesh.primitive_cube_add(size=1, location=(0.4, -0.2, 1.4))
obj = bpy.context.object
obj.scale = (0.6, 0.3, 2.2)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
arm = bpy.data.armatures.new("rig")
armo = bpy.data.objects.new("Armature", arm)
bpy.context.scene.collection.objects.link(armo)
bpy.context.view_layer.objects.active = armo
bpy.ops.object.mode_set(mode="EDIT")
b = arm.edit_bones.new("mixamorig:HeadTop_End")
b.head = (0, 0, 2.3)
b.tail = (0, 0, 2.5)
bpy.ops.object.mode_set(mode="OBJECT")
vg = obj.vertex_groups.new(name="mixamorig:HeadTop_End")
vg.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
mod = obj.modifiers.new("Armature", "ARMATURE")
mod.object = armo
obj.parent = armo
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=out + "/a.glb", export_format="GLB")

# B: the known cylinder, no rig.
fresh()
bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.35, depth=1.75)
bpy.ops.export_scene.gltf(filepath=out + "/b.glb", export_format="GLB")

# C: skinned box with a Head joint at 0.7 of the box height, no HeadTop_End.
fresh()
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 1.0))
obj = bpy.context.object
obj.scale = (0.5, 0.5, 2.0)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
arm = bpy.data.armatures.new("rig")
armo = bpy.data.objects.new("Armature", arm)
bpy.context.scene.collection.objects.link(armo)
bpy.context.view_layer.objects.active = armo
bpy.ops.object.mode_set(mode="EDIT")
b = arm.edit_bones.new("mixamorig:Head")
b.head = (0, 0, 1.4)
b.tail = (0, 0, 1.55)
bpy.ops.object.mode_set(mode="OBJECT")
vg = obj.vertex_groups.new(name="mixamorig:Head")
vg.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
mod = obj.modifiers.new("Armature", "ARMATURE")
mod.object = armo
obj.parent = armo
bpy.ops.object.select_all(action="SELECT")
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


def run_and_measure(tmp, name, target):
    """Runs normalize and re-measures the produced file independently."""
    out_dir = Path(tmp) / f"out-{name}"
    out_dir.mkdir()
    res = runner.run("normalize", inputs={"model": Path(tmp) / f"{name}.glb"},
                     params={"target_height_m": target}, out_dir=out_dir)
    if not res["ok"]:
        print(f"FAIL: normalize {name}: {res['error']}")
        return None, None
    produced = res.get("outputs", {}).get("model")
    if not produced:
        print(f"FAIL: normalize {name} produced no model")
        return None, None
    measured = runner.run("measure", inputs={"model": Path(produced)})
    if not measured["ok"]:
        print(f"FAIL: re-measure {name}: {measured['error']}")
        return None, None
    return res["data"], measured["data"]


def main():
    st = runner.status()
    print(f"Blender: {st['executable'] or '(none found)'} {st['version']}")
    if not st["executable"]:
        print("FAIL: no Blender executable — set image_generation.blender_executable")
        return 1

    import subprocess
    with tempfile.TemporaryDirectory(prefix="smoke-normalize-") as tmp:
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

        print("\nFixture A — crown basis: body 2.0 m + 0.2 m hair -> 1.70 m")
        data, m = run_and_measure(tmp, "a", 1.70)
        if data is None:
            return 1
        check("height_basis", data["height_basis"], "crown")
        check("scale", data["scale"], 0.85, 1e-4)
        check("joints (reported)", data["after"]["joints"], 1)
        # The independent measurement of the produced file is the verdict.
        check_vec("dims_m (re-measured)", m["dims_m"], [0.51, 0.255, 1.87])
        check_vec("center_xy (re-measured)", m["center_xy"], [0.0, 0.0])
        check("min_z (re-measured)", m["min_z"], 0.0, TOL)
        check("tris (re-measured)", m["tris"], 12)
        check("bones (re-measured)", m["bones"], 1)

        print("\nFixture B — bbox basis: cylinder 1.75 m -> 2.0 m")
        data, m = run_and_measure(tmp, "b", 2.0)
        if data is None:
            return 1
        check("height_basis", data["height_basis"], "bbox")
        check("scale", data["scale"], 2.0 / 1.75, 1e-4)
        check_vec("dims_m (re-measured)", m["dims_m"], [0.8, 0.8, 2.0])
        check_vec("center_xy (re-measured)", m["center_xy"], [0.0, 0.0])
        check("min_z (re-measured)", m["min_z"], 0.0, TOL)

        print("\nFixture C — crown estimate: Head at 0.7 of the box -> body 1.6 m")
        data, m = run_and_measure(tmp, "c", 1.6)
        if data is None:
            return 1
        check("height_basis", data["height_basis"], "head-est")
        check("scale", data["scale"], 1.0, 1e-4)
        check_vec("dims_m (re-measured)", m["dims_m"], [0.5, 0.5, 2.0])
        check("min_z (re-measured)", m["min_z"], 0.0, TOL)

        print("\nRunner contract")
        bad = runner.run("normalize", inputs={"model": Path(tmp) / "b.glb"},
                         params={}, out_dir=Path(tmp))
        check("missing target -> ok False", bad["ok"], False)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
