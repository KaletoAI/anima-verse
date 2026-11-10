"""The body's base colour of a GLB that carries a procedural part.

Usage: .venv/bin/python scripts/smoke_base_color_parts.py

A part built by the ``inset_part`` / ``attached_part`` Blender scripts brings
its own material with its own baked base-colour texture, marked by the extra
``attached_part`` (on the material for an inset part, on the node for an
attached part). ``base_body.base_color_image`` / ``replace_base_color`` read and
replace the BODY's base colour: before the fix both raised "Expected exactly
one base-colour image, found 2" on such a model — an outfit model whose
extension rig built a part failed when its outfit colour was put back, and so
would a tip colour disc painted onto it.

Fixtures (hand-built GLBs, one 4x4 PNG per image, colours chosen by hand):
  body image (200,100,50), part image (10,20,30), new image (1,2,3).
[1] Inset part: material 0 body, material 1 extras {attached_part: g} with the
    part image; one mesh, two primitives. base_color_image = the body PNG
    bytes; replace_base_color with the new PNG: base_color_image = the new
    bytes, the part image's bytes are unchanged.
[2] Attached part: a second mesh on a node with extras {attached_part: g},
    its material unmarked: the same two results.
[3] A material used by the body AND a part node stays a body material, so two
    unmarked body materials on different images still raise ValueError.
[4] Fails on the old code: the same checks against ``_base_color_targets`` of
    app/core/base_body.py at commit 746206f545 (before the fix) raise on [1]
    and [2].
"""
import ast
import io
import json
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OLD_COMMIT = "746206f545"
FAILS = []


def check(label, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + label + ("" if ok else f" — {detail}"))
    if not ok:
        FAILS.append(label)


def png(colour):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (4, 4), colour).save(out, format="PNG")
    return out.getvalue()


BODY, PART, NEW = png((200, 100, 50)), png((10, 20, 30)), png((1, 2, 3))


def glb(images, materials, meshes, nodes):
    binary, views = b"", []
    for image in images:
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(image)})
        binary += image + b"\0" * (-len(image) % 4)
    doc = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(binary)}], "bufferViews": views,
           "images": [{"bufferView": i, "mimeType": "image/png"} for i in range(len(images))],
           "textures": [{"source": i} for i in range(len(images))],
           "materials": materials, "meshes": meshes, "nodes": nodes}
    raw = json.dumps(doc).encode()
    raw += b" " * (-len(raw) % 4)
    body = struct.pack("<II", len(raw), 0x4E4F534A) + raw + struct.pack("<II", len(binary), 0x004E4942) + binary
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def material(texture, extras=None):
    out = {"pbrMetallicRoughness": {"baseColorTexture": {"index": texture}}}
    if extras:
        out["extras"] = extras
    return out


INSET = glb([BODY, PART], [material(0), material(1, {"attached_part": "g"})],
            [{"primitives": [{"material": 0}, {"material": 1}]}], [{"mesh": 0}])
ATTACHED = glb([BODY, PART], [material(0), material(1)],
               [{"primitives": [{"material": 0}]}, {"primitives": [{"material": 1}]}],
               [{"mesh": 0}, {"mesh": 1, "extras": {"attached_part": "g"}}])
SHARED = glb([BODY, PART], [material(0), material(1)],
             [{"primitives": [{"material": 0}, {"material": 1}]}, {"primitives": [{"material": 1}]}],
             [{"mesh": 0}, {"mesh": 1, "extras": {"attached_part": "g"}}])


def image_bytes(data, index):
    from app.core.model_validate import parse_glb
    parsed = parse_glb(data)
    view = parsed["gltf"]["bufferViews"][parsed["gltf"]["images"][index]["bufferView"]]
    start = view.get("byteOffset", 0)
    return bytes(parsed["bin"][start:start + view["byteLength"]])


def old_targets():
    """``_base_color_targets`` as it was at OLD_COMMIT."""
    source = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_COMMIT}:app/core/base_body.py"],
                            capture_output=True, text=True, check=True).stdout
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_base_color_targets")
    scope: Dict[str, Any] = {"Dict": Dict, "Tuple": Tuple, "Any": Any}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "old_base_body", "exec"), scope)
    return scope["_base_color_targets"]


def main():
    from app.core import base_body
    from app.core.model_validate import parse_glb
    for label, data in (("[1] inset part", INSET), ("[2] attached part", ATTACHED)):
        check(f"{label}: base_color_image is the body's", base_color_image_ok(base_body, data))
        replaced = base_body.replace_base_color(data, NEW, "image/png")
        check(f"{label}: replaced body colour", base_body.base_color_image(replaced)[0] == NEW)
        part_index = 1
        check(f"{label}: the part's texture is untouched", image_bytes(replaced, part_index) == PART)
    try:
        base_body.base_color_image(SHARED)
        check("[3] a shared material stays body: two body images raise", False, "no ValueError")
    except ValueError:
        check("[3] a shared material stays body: two body images raise", True)
    old = old_targets()
    for label, data in (("[4] old code raised on the inset part", INSET),
                        ("[4] old code raised on the attached part", ATTACHED)):
        try:
            old(parse_glb(data)["gltf"])
            check(label, False, "did not raise")
        except ValueError as exc:
            check(label, "found 2" in str(exc), exc)
    print("FAIL" if FAILS else "PASS", f"({len(FAILS)} failed)" if FAILS else "")
    return 1 if FAILS else 0


def base_color_image_ok(base_body, data):
    image, mime = base_body.base_color_image(data)
    return image == BODY and mime == "image/png"


if __name__ == "__main__":
    sys.exit(main())
