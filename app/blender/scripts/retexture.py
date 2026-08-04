"""Re-encodes a model's textures, leaving the geometry untouched.

70–93 % of a generated GLB is texture, stored as uncompressed PNG. This is
the one step that makes a real difference to what a client downloads, and it
costs no geometry at all: the mesh, its UVs and its rig go through unchanged.

    jpeg_quality        0-100, the JPEG quality of re-encoded maps
    max_texture_size    downscale maps larger than this (0 = keep resolution)

Alpha is the whole subtlety, and it is not ours to get wrong: Blender's glTF
exporter keeps any image that NEEDS an alpha channel as PNG when the format is
set to JPEG. That is the same rule the gateway already applies to its own
deliveries, so a basecolor with real transparency survives.

JPEG is deliberate over WebP. WebP is smaller again, but inside a GLB it needs
the EXT_texture_webp extension and therefore a loader plugin in every renderer
that opens the file. JPEG is glTF core — nothing anywhere has to learn a thing.

Reported under ``data``: ``before``/``after`` file bytes, ``ratio``, and per
image its name, size and whether it was downscaled. The caller decides whether
to keep the result; this script only ever writes into its job directory.
"""
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bpy                                                    # noqa: E402

# Only these containers can be re-exported without touching the rig contract.
# An FBX carries its rig through a different exporter with its own quirks —
# out of scope here, and the FBX deliveries keep their textures separately
# anyway.
SUPPORTED = (".glb", ".gltf")

# Blender's own name for "decide per image, keep PNG where alpha is needed".
JPEG_FORMAT = "JPEG"


def _images():
    return [i for i in bpy.data.images
            if i.name not in ("Render Result", "Viewer Node") and i.size[0]]


def retexture(args):
    src = args["inputs"].get("model")
    if not src:
        raise ValueError("no input 'model'")
    if Path(src).suffix.lower() not in SUPPORTED:
        raise ValueError(f"retexture handles {'/'.join(SUPPORTED)}, "
                         f"not {Path(src).suffix}")
    p = args["params"]
    quality = max(0, min(100, int(p.get("jpeg_quality") or 85)))
    max_size = int(p.get("max_texture_size") or 0)

    _common.reset_scene()
    _common.import_model(src)

    images = []
    for img in _images():
        w, h = int(img.size[0]), int(img.size[1])
        scaled = False
        if max_size and max(w, h) > max_size:
            factor = max_size / float(max(w, h))
            nw, nh = max(1, int(w * factor)), max(1, int(h * factor))
            img.scale(nw, nh)
            w, h, scaled = nw, nh, True
        images.append({"name": img.name, "size": [w, h], "scaled": scaled})

    out = Path(args["out_dir"]) / Path(src).name
    bpy.ops.export_scene.gltf(
        filepath=str(out), export_format="GLB",
        export_image_format=JPEG_FORMAT, export_jpeg_quality=quality,
        # Everything below keeps the model itself identical — this step is
        # about bytes in the images, nothing else.
        export_apply=False, export_yup=True, export_skins=True,
        export_animations=True, export_morph=True)

    before = Path(src).stat().st_size
    after = out.stat().st_size
    data = {
        "before": {"file_bytes": before},
        "after": {"file_bytes": after},
        "ratio": round(after / before, 4) if before else 1.0,
        "bytes_saved": before - after,
        "jpeg_quality": quality,
        "max_texture_size": max_size,
        "images": images,
    }
    # A result that is not smaller is not a result — the caller would keep the
    # original anyway, and handing one back invites it to be stored by mistake.
    return data, ({"model": str(out)} if after < before else {})


_common.main(retexture)
