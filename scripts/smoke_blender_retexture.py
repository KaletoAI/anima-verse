#!/usr/bin/env python3
"""Numeric check of the texture re-encode and its safety gates.

Usage:
    ./.venv/bin/python scripts/smoke_blender_retexture.py

Needs Blender, no server and no world DB. Works in a temp directory only.

What is asserted, and why these and not others:

  Fixture D — a cube with an OPAQUE 512x512 colour-grid texture.
    The PNG of a colour grid is large; JPEG at quality 85 is a fraction of it,
    and texture is nearly all of a small GLB's bytes. So:
        result exists, is SMALLER, and every image mime is image/jpeg
    No exact byte count is asserted — that would test libjpeg, not us.

  Fixture E — the same cube with an ALPHA texture and alphaMode BLEND.
    This is the one assumption the whole step rests on: JPEG has no alpha
    channel, so an image that needs one MUST come back out as PNG or the
    model silently loses its transparency. Asserted:
        at least one image stays image/png
    The bestand this was built against is 181/181 OPAQUE materials, so this
    fixture is the only place the rule is exercised at all — which is exactly
    why it is here.

  Gate F — apply_script must refuse a result that fails validation.
    A stub validator that always fails must leave the file byte-identical,
    and must NOT leave a raw/ backup behind (nothing was replaced, so there
    is nothing to back up).

  Gate G — the raw backup is written on the FIRST apply only. A second run
    must not overwrite the true original with an already-refined file.
"""
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.blender import refine, runner                        # noqa: E402
from app.core.model_validate import parse_glb                 # noqa: E402

FIXTURE_SCRIPT = r'''
import bpy, sys
out = sys.argv[sys.argv.index("--") + 1]

def cube_with_texture(path, alpha):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(size=2)
    obj = bpy.context.object
    size = 64 if alpha else 512
    img = bpy.data.images.new("Tex", width=size, height=size)
    img.generated_type = "COLOR_GRID"
    if alpha:
        # A real, used alpha channel — half transparent across the board.
        px = list(img.pixels)
        for i in range(3, len(px), 4):
            px[i] = 0.5
        img.pixels = px
    mat = bpy.data.materials.new("M")
    mat.use_nodes = True
    nt = mat.node_tree
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    bsdf = nt.nodes["Principled BSDF"]
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if alpha:
        nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
        mat.blend_method = "BLEND"
    obj.data.materials.append(mat)
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB")

cube_with_texture(out + "/d.glb", alpha=False)
cube_with_texture(out + "/e.glb", alpha=True)
# f and g are built FRESH rather than copied from d: d is re-encoded by the
# time they are used, and a second pass over an already-JPEG file correctly
# does nothing — which would make the gates below pass for the wrong reason.
cube_with_texture(out + "/f.glb", alpha=False)
cube_with_texture(out + "/g.glb", alpha=False)
print("FIXTURES_OK")
'''

failures = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(': ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def mimes(path):
    g = parse_glb(Path(path).read_bytes())["gltf"]
    return [(i.get("mimeType") or "?") for i in (g.get("images") or [])]


def main():
    st = runner.status()
    print(f"Blender: {st['executable'] or '(none found)'} {st['version']}")
    if not st["executable"]:
        print("FAIL: no Blender executable")
        return 1

    with tempfile.TemporaryDirectory(prefix="smoke-retex-") as tmp:
        script = Path(tmp) / "fixtures.py"
        script.write_text(FIXTURE_SCRIPT, encoding="utf-8")
        proc = subprocess.run(
            [st["executable"], "--background", "--factory-startup",
             "--python", str(script), "--", tmp],
            capture_output=True, text=True, timeout=300)
        if "FIXTURES_OK" not in proc.stdout:
            print("FAIL: fixtures could not be built")
            print(proc.stdout[-2000:], proc.stderr[-2000:])
            return 1

        print("\nFixture D — opaque texture becomes JPEG and shrinks")
        d = Path(tmp) / "d.glb"
        before = d.stat().st_size
        res = refine.apply_script(d, "retexture", {"jpeg_quality": 85})
        check("script ran", res["ok"], res.get("error", ""))
        check("applied", res["applied"], res.get("error", ""))
        after = d.stat().st_size
        check("smaller", after < before, f"{before} -> {after} bytes")
        got = mimes(d)
        check("all images jpeg", all(m == "image/jpeg" for m in got), str(got))

        print("\nFixture E — an alpha texture must stay PNG")
        e = Path(tmp) / "e.glb"
        refine.apply_script(e, "retexture", {"jpeg_quality": 85},
                            require_smaller=False)
        got = mimes(e)
        check("a png survives", any(m == "image/png" for m in got), str(got))

        print("\nGate F — a failing validator must not replace the file")
        f = Path(tmp) / "f.glb"
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
        res = refine.apply_script(
            f, "retexture", {"jpeg_quality": 40}, require_smaller=False,
            validator=lambda _b: {"ok": False, "errors": ["stub says no"]})
        check("not applied", not res["applied"])
        check("file untouched",
              hashlib.sha256(f.read_bytes()).hexdigest() == digest)
        check("no raw backup written", not refine.raw_backup_path(f).exists())

        print("\nGate G — the raw backup keeps the FIRST original")
        g = Path(tmp) / "g.glb"
        original = hashlib.sha256(g.read_bytes()).hexdigest()
        refine.apply_script(g, "retexture", {"jpeg_quality": 85},
                            require_smaller=False)
        backup = refine.raw_backup_path(g)
        check("backup exists", backup.exists())
        refine.apply_script(g, "retexture", {"jpeg_quality": 60},
                            require_smaller=False)
        check("backup still the original",
              backup.exists()
              and hashlib.sha256(backup.read_bytes()).hexdigest() == original)
        # The backup must not answer the stores' "<stem>.*" glob.
        check("backup is not a sibling",
              backup.parent.name == "raw" and not list(g.parent.glob("g.raw.*")))

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
