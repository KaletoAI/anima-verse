"""Basecolor transfer from an unrigged GLB to a standalone generic rig."""
import base64
import io
from pathlib import Path

from PIL import Image

from app.core.model_validate import parse_glb


def png_basecolor(raw: bytes) -> bytes:
    """Keep the source orientation and encode the selected color map as PNG."""
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
        if max(image.size) < 8:
            raise ValueError("source basecolor is an empty texture")
        out = io.BytesIO()
        image.save(out, format="PNG")
        return out.getvalue()
    except (OSError, ValueError) as exc:
        raise ValueError(f"source basecolor is unusable: {exc}") from exc


def source_basecolor(mesh: Path, separate: str = "") -> bytes:
    """Select the material's basecolor, never the first arbitrary GLB image.

    A generic FBX has one external map. Multiple distinct color maps cannot
    be represented by that contract and require an atlas before rigging.
    """
    if separate:
        return png_basecolor(Path(separate).read_bytes())
    parsed = parse_glb(mesh.read_bytes())
    gltf = parsed['gltf']
    textures = gltf.get('textures') or []
    indices = set()
    for material in gltf.get('materials') or []:
        ref = (material.get('pbrMetallicRoughness') or {}).get('baseColorTexture')
        if isinstance(ref, dict):
            try:
                indices.add(textures[ref['index']]['source'])
            except (KeyError, IndexError, TypeError) as exc:
                raise ValueError('source basecolor texture reference is invalid') from exc
    if len(indices) != 1:
        raise ValueError('generic rig requires one source basecolor texture; missing map or multiple maps need an atlas')
    image = (gltf.get('images') or [])[indices.pop()]
    if 'bufferView' in image:
        view = gltf['bufferViews'][image['bufferView']]
        start = int(view.get('byteOffset', 0))
        raw = parsed['bin'][start:start + int(view['byteLength'])]
    elif str(image.get('uri', '')).startswith('data:'):
        raw = base64.b64decode(image['uri'].split(',', 1)[1])
    else:
        raise ValueError('source basecolor must be embedded in the GLB or supplied by the mesh job')
    return png_basecolor(raw)


def fbx_basecolor(raw: bytes) -> bytes:
    """Apply the generic hub contract's V correction to an Object color map."""
    image = Image.open(io.BytesIO(raw))
    out = io.BytesIO()
    image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).save(out, format="PNG")
    return out.getvalue()


def validate_source(raw: bytes) -> dict:
    """Apply contract none and reject skins on the reproducible source."""
    from app.core.model_validate import validate_static_glb
    verdict = validate_static_glb(raw)
    try:
        skinned = bool(parse_glb(raw)["gltf"].get("skins"))
    except (ValueError, KeyError, IndexError, TypeError):
        return verdict
    if skinned:
        verdict["ok"] = False
        verdict["errors"].append("source mesh must be unrigged (no skins); combined mesh+rig aliases are not supported")
    return verdict
