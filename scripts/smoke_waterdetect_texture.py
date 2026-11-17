#!/usr/bin/env python3
"""waterdetect reads texture texels as STORED sRGB and follows the importer's Mix chain.

Part A (pure, no Blender): the colour helpers of app/blender/scripts/waterdetect.py
are loaded by AST. ``image.pixels`` of a byte sRGB texture returns the stored,
already encoded values; the old ``_colour`` encoded them a second time.
Hand-derived (x^(1/2.4) via e^(ln x/2.4)):
  * texel (.50, .65, .75), real water blue: h = 240 + 60*(.50-.65)/.25 = 204°,
    s = .25/.75 = .333, v = .75 -> blue. Encoded again: _srgb(.5) = .7354,
    _srgb(.75) = .8808 -> s = .1453/.8808 = .165 < .2 -> NOT blue (old bug).
  * texel (.05, .12, .18), dark slate: v = .18 < .2 -> not blue, not pale.
    Encoded again: _srgb(.05) = .2478, _srgb(.12) = .3811, _srgb(.18) = .4613
    -> h = 240 + 60*(.2478-.3811)/.2135 = 202.5°, s = .463, v = .461 -> blue (old bug).
  * grey (.5, .5, .5): s = 0 -> neither, either way.
  * a float (linear) texel (.02, .25, .6) still gets ONE encoding:
    (.1517, .5371, .7978) -> h = 204°, s = .81, v = .80 -> blue.
  * the importer's Multiply Mix: white sRGB texel (1, 1, 1) decodes to linear
    1, times the linear baseColorFactor (.02, .25, .6) = (.02, .25, .6) -> the
    same (.1517, .5371, .7978) -> blue. The old code read the unlinked Base
    Color default (.8 grey) -> s = 0 -> not blue.

Part B (Blender >= 5.2, skipped with a note when none is found): four 1x1 m
boxes, top at .2, each in its own GLB, run through the real script in a temp
job dir (args.json contract of app/blender/runner.py, without the server's
slot folder), measure=xz, target 1 m (s = 1):
  * byte sRGB texture stored (128, 166, 191)/255 = (.502, .651, .749) ->
    h = 205°, s = .33, v = .75 -> blue -> ONE painted region, area 1 m² (±10%).
  * byte sRGB texture stored (13, 31, 46)/255 = (.051, .122, .180) -> v < .2 ->
    NO region.
  * white texture times baseColorFactor (.02, .25, .6) (exported Mix) -> blue
    -> ONE painted region, area 1 m² (±10%).
  * no texture, COLOR_0 linear (.02, .25, .6) times a white base colour -> the
    same blue -> ONE painted region, area 1 m² (±10%).
Old code: case 1 -> no region (s .165), case 2 -> a painted region, cases 3
and 4 -> no region (the grey default of the linked Base Color socket).

Usage: ./.venv/bin/python scripts/smoke_waterdetect_texture.py
"""
import ast
import colorsys
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "app/blender/scripts/waterdetect.py"
HELPERS = ("_srgb", "_linear", "_texel_linear", "_shade", "_blue", "_pale")


def _helpers():
    module = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    body = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name in HELPERS]
    assert {n.name for n in body} == set(HELPERS), [n.name for n in body]
    scope = {"colorsys": colorsys}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(SCRIPT), "exec"), scope)
    return scope


def part_a():
    h = _helpers()
    srgb, texel_linear, shade, blue, pale = (h["_srgb"], h["_texel_linear"], h["_shade"],
                                              h["_blue"], h["_pale"])

    def texture(stored, stored_srgb=True):
        return shade([texel_linear(stored, stored_srgb)])

    def old(stored):  # the old _colour body for a texel: encode the stored value again
        return tuple(srgb(c) for c in stored)

    water = texture((.50, .65, .75))
    assert all(abs(a - b) < 1e-6 for a, b in zip(water, (.50, .65, .75))), water
    assert blue(water)
    assert not blue(old((.50, .65, .75))), "old double encoding should miss the water"
    hh, s, v = colorsys.rgb_to_hsv(*old((.50, .65, .75)))
    assert abs(s - .165) < .002, s

    slate = texture((.05, .12, .18))
    assert not blue(slate) and not pale(slate), slate
    assert blue(old((.05, .12, .18))), "old double encoding flags dark slate as water"
    hh, s, v = colorsys.rgb_to_hsv(*old((.05, .12, .18)))
    assert abs(s - .463) < .002 and abs(v - .461) < .002 and abs(hh * 360 - 202.5) < .5, (hh, s, v)

    grey = texture((.5, .5, .5))
    assert not blue(grey) and not pale(grey)

    lin = texture((.02, .25, .6), stored_srgb=False)
    for got, want in zip(lin, (.1517, .5371, .7978)):
        assert abs(got - want) < 5e-4, lin
    assert blue(lin)

    mixed = shade([texel_linear((1.0, 1.0, 1.0), True), (.02, .25, .6)])
    assert all(abs(a - b) < 1e-9 for a, b in zip(mixed, lin)), mixed
    assert blue(mixed)
    assert not blue(tuple(srgb(c) for c in (.8, .8, .8))), "old path read the grey default"
    assert shade([]) is None
    print("part A: texel decoding + Mix product PASS (5 colours)")


BUILD = r'''
import bpy, sys
from pathlib import Path
out = Path(sys.argv[sys.argv.index('--')+1])
def reset():
    for o in list(bpy.data.objects): bpy.data.objects.remove(o)
def textured(name, stored, factor=None):
    reset()
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, .1))
    o = bpy.context.object; o.dimensions = (1, 1, .2)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    img = bpy.data.images.new(name, 4, 4)
    img.pixels[:] = [c / 255 for c in stored] * 16 if len(stored) == 4 else [*[c / 255 for c in stored], 1.0] * 16
    img.filepath_raw = str(out / (name + '.png')); img.file_format = 'PNG'; img.save()
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; b = nt.nodes['Principled BSDF']
    t = nt.nodes.new('ShaderNodeTexImage'); t.image = img
    if factor:
        mx = nt.nodes.new('ShaderNodeMix'); mx.data_type = 'RGBA'; mx.blend_type = 'MULTIPLY'
        mx.inputs[0].default_value = 1
        nt.links.new(t.outputs[0], mx.inputs[6]); mx.inputs[7].default_value = (*factor, 1)
        nt.links.new(mx.outputs[2], b.inputs['Base Color'])
    else:
        nt.links.new(t.outputs[0], b.inputs['Base Color'])
    o.data.materials.append(m)
    bpy.ops.export_scene.gltf(filepath=str(out / (name + '.glb')), export_format='GLB')
textured('water', (128, 166, 191))
textured('slate', (13, 31, 46))
textured('mixed', (255, 255, 255), factor=(.02, .25, .6))
reset()
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, .1))
o = bpy.context.object; o.dimensions = (1, 1, .2)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
m = bpy.data.materials.new('vcol'); m.use_nodes = True
m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (1, 1, 1, 1)
o.data.materials.append(m)
a = o.data.color_attributes.new('Col', 'FLOAT_COLOR', 'CORNER')
for d in a.data: d.color = (.02, .25, .6, 1)
bpy.ops.export_scene.gltf(filepath=str(out / 'vcol.glb'), export_format='GLB',
                          export_vertex_color='ACTIVE')
'''


def _run(exe, root, name):
    job = root / ("job-" + name)
    (job / "out").mkdir(parents=True)
    args = {"inputs": {"model": str(root / (name + ".glb"))},
            "params": {"rotation": {}, "target_m": 1, "measure": "xz", "step": .02,
                       "clearance": 1.2, "max_cells": 250000, "preview": False},
            "out_dir": str(job / "out"), "result": str(job / "result.json")}
    (job / "args.json").write_text(json.dumps(args))
    subprocess.run([exe, "--background", "--factory-startup", "--python-exit-code", "1",
                    "--python", str(SCRIPT), "--", str(job / "args.json")],
                   capture_output=True, timeout=300)
    res = json.loads((job / "result.json").read_text())
    assert res["ok"], res["error"]
    return res["data"]["regions"]


def part_b():
    sys.path.insert(0, str(ROOT))
    from app.blender import runner
    exe = runner.find_executable()
    if not exe:
        print("part B: SKIPPED — no Blender >= 5.2 found")
        return
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "build.py").write_text(BUILD)
        subprocess.run([exe, "--background", "--factory-startup", "--python-exit-code", "1",
                        "--python", str(root / "build.py"), "--", tmp],
                       check=True, capture_output=True, timeout=120)
        for name, want in (("water", 1), ("slate", 0), ("mixed", 1), ("vcol", 1)):
            regions = _run(exe, root, name)
            assert len(regions) == want, (name, regions)
            for r in regions:
                assert r["kind"] == "painted", (name, r)
                assert abs(r["area_m2"] - 1) <= .1, (name, r)
    print("part B: textured water / dark slate / Mix factor / vertex colour through Blender PASS")


def main():
    part_a()
    part_b()
    print("smoke_waterdetect_texture: PASS")


if __name__ == "__main__":
    main()
