#!/usr/bin/env python3
"""Numeric check of the `bake_vc` script (Triposplat rescue, plan § 3.3).

Usage:
    ./.venv/bin/python scripts/smoke_blender_bake_vc.py

Needs Blender (auto-discovered), no server and no world DB. Works entirely in
a temp directory. The result is verified by RE-MEASURING the produced file
with the independent `measure` script, plus one pixel probe of the baked
texture in a separate Blender run.

The expected numbers are DERIVED BY HAND here, not recorded from a run:

  Fixture A — the Triposplat signature: a cube (size=2 -> 12 tris, dims
  2 x 2 x 2 m), UV map removed, one CORNER colour attribute painted uniform
  RED (1, 0, 0, 1). After bake_vc(texture_size=256):
        uv_layers     = 1     (Smart UV Project added exactly one set)
        vertex_colors = 0     (removed — the texture replaces them)
        images        = one 256 x 256, packed
        tris          = 12, dims unchanged (geometry untouched)
    The centre pixel of the baked image must be red. 1 and 0 are fixed
    points of every sRGB/linear conversion, so the probe is transfer-proof.

  Fixture B — hole filling: the same cube with ONE face deleted.
    5 quads = 10 tris, and the missing face leaves 4 boundary edges.
    fill_holes closes the 4-edge loop with one quad: 12 tris, 0 boundary
    edges. (`boundary_before`/`after` come from the script's own report;
    the re-measured triangle count confirms the fill really landed in the
    file.)

  Fixture C — an already-textured model (cube WITH its UV map, no colour
  attribute) must come back untouched: the script declares "nothing to do"
  and produces NO output file; `baked` = 0.

Tolerance: colours 0.02 (8-bit quantisation), geometry exact.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.blender import runner                                # noqa: E402

FIXTURE_SCRIPT = r'''
import bpy, sys
out = sys.argv[sys.argv.index("--") + 1]

def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)

def paint_red(me):
    while me.uv_layers:
        me.uv_layers.remove(me.uv_layers[0])
    col = me.color_attributes.new(name="Col", type="BYTE_COLOR", domain="CORNER")
    for d in col.data:
        d.color = (1.0, 0.0, 0.0, 1.0)

# A: closed cube, no UVs, red vertex colours.
fresh()
bpy.ops.mesh.primitive_cube_add(size=2)
paint_red(bpy.context.object.data)
bpy.ops.export_scene.gltf(filepath=out + "/a.glb", export_format="GLB")

# B: same, one face deleted (4 boundary edges). A fresh primitive comes fully
# selected, so deselect FIRST — otherwise the delete takes the whole cube.
fresh()
bpy.ops.mesh.primitive_cube_add(size=2)
obj = bpy.context.object
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="DESELECT")
bpy.ops.object.mode_set(mode="OBJECT")
obj.data.polygons[0].select = True
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.delete(type="FACE")
bpy.ops.object.mode_set(mode="OBJECT")
paint_red(obj.data)
bpy.ops.export_scene.gltf(filepath=out + "/b.glb", export_format="GLB")

# C: normal textured-style cube — UVs kept, no colour attribute.
fresh()
bpy.ops.mesh.primitive_cube_add(size=2)
bpy.ops.export_scene.gltf(filepath=out + "/c.glb", export_format="GLB")
print("FIXTURES_OK")
'''

PROBE_SCRIPT = r'''
import bpy, sys
src = sys.argv[sys.argv.index("--") + 1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
for img in bpy.data.images:
    if img.name in ("Render Result", "Viewer Node") or not img.size[0]:
        continue
    w, h = img.size
    px = list(img.pixels)
    i = ((h // 2) * w + w // 2) * 4
    print("PIXEL", round(px[i], 3), round(px[i + 1], 3), round(px[i + 2], 3))
    break
'''

failures = []


def check(label, got, want, tol=0.0):
    ok = (abs(got - want) <= tol) if tol else (got == want)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got}, want {want}")
    if not ok:
        failures.append(label)


def main():
    st = runner.status()
    print(f"Blender: {st['executable'] or '(none found)'} {st['version']}")
    if not st["executable"]:
        print("FAIL: no Blender executable")
        return 1

    with tempfile.TemporaryDirectory(prefix="smoke-bakevc-") as tmp:
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

        print("\nFixture A — red vertex-colour cube -> textured cube")
        out_a = Path(tmp) / "out-a"
        out_a.mkdir()
        res = runner.run("bake_vc", inputs={"model": Path(tmp) / "a.glb"},
                         params={"texture_size": 256}, out_dir=out_a)
        if not res["ok"] or not res.get("outputs"):
            print(f"FAIL: {res.get('error') or 'no output'}")
            return 1
        check("baked objects", res["data"]["baked"], 1)
        produced = res["outputs"]["model"]
        m = runner.run("measure", inputs={"model": Path(produced)})
        if not m["ok"]:
            print(f"FAIL: re-measure: {m['error']}")
            return 1
        d = m["data"]
        check("uv_layers (re-measured)", d["uv_layers"], 1)
        check("vertex_colors (re-measured)", d["vertex_colors"], 0)
        check("tris (re-measured)", d["tris"], 12)
        img = (d.get("images") or [{}])[0]
        check("texture edge", (img.get("size") or [0])[0], 256)
        check("texture packed", int(bool(img.get("packed"))), 1)
        probe = Path(tmp) / "probe.py"
        probe.write_text(PROBE_SCRIPT, encoding="utf-8")
        pr = subprocess.run(
            [st["executable"], "--background", "--factory-startup",
             "--python", str(probe), "--", str(produced)],
            capture_output=True, text=True, timeout=120)
        pix = [line for line in pr.stdout.splitlines() if line.startswith("PIXEL")]
        if not pix:
            print("FAIL: no pixel probe")
            failures.append("pixel probe")
        else:
            r, g, b = (float(x) for x in pix[0].split()[1:4])
            check("baked pixel R", r, 1.0, 0.02)
            check("baked pixel G", g, 0.0, 0.02)
            check("baked pixel B", b, 0.0, 0.02)

        print("\nFixture B — open cube: 4 boundary edges -> filled")
        out_b = Path(tmp) / "out-b"
        out_b.mkdir()
        res = runner.run("bake_vc", inputs={"model": Path(tmp) / "b.glb"},
                         params={"texture_size": 64}, out_dir=out_b)
        if not res["ok"] or not res.get("outputs"):
            print(f"FAIL: {res.get('error') or 'no output'}")
            return 1
        check("boundary_before", res["data"]["boundary_before"], 4)
        check("boundary_after", res["data"]["boundary_after"], 0)
        m = runner.run("measure", inputs={"model": res["outputs"]["model"]})
        check("tris after fill (re-measured)", m["data"]["tris"], 12)

        print("\nFixture C — already textured: untouched")
        out_c = Path(tmp) / "out-c"
        out_c.mkdir()
        res = runner.run("bake_vc", inputs={"model": Path(tmp) / "c.glb"},
                         params={}, out_dir=out_c)
        check("ok", int(res["ok"]), 1)
        check("baked objects", res["data"]["baked"], 0)
        check("no output produced", len(res.get("outputs") or {}), 0)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
