#!/usr/bin/env python3
"""OFFLINE end-to-end proof of the figure Build pipeline on a COPY of a world
(plan ``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md`` Task 15).

Usage:
    ./.venv/bin/python scripts/e2e_figure_pipeline.py --world <copy of a world dir> \
        [--plugins <plugins dir>] [--shared-items <shared/items dir>] [--u2net-home <rembg models>] \
        [--only "1,7,6;2;3;4,5"] [--plan-only] [--no-migrate] [--workdir <dir>] [--log-dir <dir>] [--keep]

``--world`` is a COPY (``cp`` of ``world.db`` + the characters' directories, never the live one — a
directory directly under a repository's ``worlds/`` is refused). It is only READ: each scenario group runs
in its own process on its own fresh ``cp -a`` of it (``--workdir``, deleted afterwards unless ``--keep``),
and every stub answer is read from it, so a file a Build replaces on the working copy is still answered
from its stored state. ``--shared-items`` is copied into a private shared directory (the Build never
writes the repository's ``shared/``).

Zero outbound requests: the temp instance names stub backends only (never the real ``instance/``; no LLM
provider), every ``socket`` connect / DNS lookup and every ``requests`` send raises and is COUNTED, and
the result is FAIL when the count is > 0. The stubs answer from what is stored (block "The responder").

Scenario groups (characters Kai and Ylva Nordwind of the copy): ``1,7,6`` Kai's manual Build, the Base body
tab's Run all (current; then a face-value change), the automatic Build after that base refresh; ``2``
Ylva's bald shape; ``3`` a hairstyle change during Kai's shape step (Ruling A18); ``4,5`` the base-body
routes during a Build (A20) and an injected LOD failure (A19). Exit 0 = every check passed.
"""
import argparse
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# --- Network block (installed before anything else is imported) ------------------------------------------------

OUTBOUND: List[str] = []
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_getaddrinfo = socket.getaddrinfo


class OutboundBlocked(OSError):
    pass


def _blocked(what: str):
    OUTBOUND.append(what)
    raise OutboundBlocked(f"e2e harness: outbound request blocked ({what})")


def _connect(self, address):
    if self.family == getattr(socket, "AF_UNIX", None):
        return _real_connect(self, address)
    _blocked(f"connect {address!r}")


def _connect_ex(self, address):
    if self.family == getattr(socket, "AF_UNIX", None):
        return _real_connect_ex(self, address)
    _blocked(f"connect_ex {address!r}")


def _getaddrinfo(host, *a, **k):
    _blocked(f"getaddrinfo {host!r}")


def _create_connection(address, *a, **k):
    _blocked(f"create_connection {address!r}")


socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.getaddrinfo = _getaddrinfo
socket.create_connection = _create_connection
try:
    import requests  # noqa: E402

    def _send(self, request, **kwargs):
        _blocked(f"requests {request.method} {request.url}")
    requests.Session.send = _send
except ImportError:  # pragma: no cover
    pass


# --- Stub backends ---------------------------------------------------------------------------------------------------
#
# One class per media kind; each instance answers through ``RESPONDER`` (set by the scenarios). They are real
# ``ImageBackend``s in the pool: the real routing resolves them, the real ``run_on_backend_channel`` runs them on
# their own queue channel, the real ``generate()`` logs the prompt. Every call is recorded in ``CALLS``.

CALLS: List[Dict[str, Any]] = []
_calls_lock = threading.Lock()
#: (backend, params, log_meta) -> List[bytes]; also sets the backend's thread-local result metadata.
RESPONDER: Dict[str, Any] = {"fn": None}


def _make_stub_classes():
    from app.imagegen.base import ImageBackend

    class _Stub(ImageBackend):
        REQUIRES_URL = False

        def __init__(self, name, api_url, cost, env_prefix, **_kw):
            super().__init__(name, api_url or "stub://", cost, self.API_TYPE, env_prefix)
            self._tls = threading.local()
            self.upscale_scale = 2.0
            self.max_side = 4096
            self.color_fix = True
            self.model = name
            # A manual prompt limit: the hub schema probe (``prompt_limit.hub_prompt_limit``) is never asked.
            self.prompt_char_limit = 100000

        # thread-local result metadata the service reads on the channel thread
        last_result_files = property(lambda self: getattr(self._tls, "files", []))
        last_result_rig = property(lambda self: getattr(self._tls, "rig", None))
        last_result_meta = property(lambda self: getattr(self._tls, "meta", {}))
        last_single_view = property(lambda self: False)
        last_job_id = property(lambda self: getattr(self._tls, "job_id", ""))
        last_photo_application = property(lambda self: {})

        def set_result(self, files=None, rig=None, meta=None, job_id=""):
            self._tls.files, self._tls.rig, self._tls.meta, self._tls.job_id = list(files or []), rig, \
                dict(meta or {}), job_id

        def check_availability(self) -> bool:
            self._mark_available("e2e stub")
            return True

        def photo_controls_supported(self):
            return True

        def skin_recolor_supported(self):
            return True

        def _generate(self, prompt, negative_prompt, params):
            fn = RESPONDER["fn"]
            if fn is None:
                raise RuntimeError(f"e2e stub {self.name}: no responder")
            return fn(self, prompt, params)

    out = {}
    for api_type, media in (("e2e_stub_image", "image"), ("e2e_stub_mesh", "mesh"),
                            ("e2e_stub_upscale", "image")):
        out[api_type] = type(f"Stub_{api_type}", (_Stub,), {"API_TYPE": api_type, "MEDIA_TYPE": media})
    return out


#: The stub backends of the temp instance and the occasions they serve (``routing``).
STUB_BACKENDS = [
    {"name": "stub-image", "api_type": "e2e_stub_image", "api_url": "stub://image", "category": "img2img",
     "image_family": "natural", "ref_slot_count": 4, "enabled": True},
    {"name": "stub-mesh", "api_type": "e2e_stub_mesh", "api_url": "stub://mesh", "category": "img2mesh",
     "enabled": True},
    {"name": "stub-rig", "api_type": "e2e_stub_mesh", "api_url": "stub://rig", "category": "mesh2rig",
     "enabled": True},
    {"name": "stub-face", "api_type": "e2e_stub_mesh", "api_url": "stub://face", "category": "face_retexture",
     "enabled": True},
    {"name": "stub-hair", "api_type": "e2e_stub_mesh", "api_url": "stub://hair", "category": "img2hair",
     "enabled": True},
    {"name": "stub-upscale", "api_type": "e2e_stub_upscale", "api_url": "stub://upscale", "category": "upscale",
     "enabled": True},
]
STUB_ROUTING = {
    **{occ: ["stub-image"] for occ in ("tpose", "tpose_view", "garment_view", "base_front", "base_view",
                                        "outfit_front", "outfit_back_draft", "outfit_side_draft", "footwear_empty",
                                        "expression", "profile", "regenerate", "item")},
    **{occ: ["stub-mesh"] for occ in ("mesh_humanoid", "mesh_creature", "mesh_garment", "mesh_footwear",
                                       "mesh_object")},
    "rig_humanoid": ["stub-rig"], "rig_creature": ["stub-rig"], "face_retexture": ["stub-face"],
    "hair_mesh": ["stub-hair"], "upscale": ["stub-upscale"],
}


def register_stub_types() -> None:
    from app.imagegen.registry import BACKEND_REGISTRY
    BACKEND_REGISTRY.update(_make_stub_classes())


# --- The responder: what each stub call answers ---------------------------------------------------------------------
#
# Images answer from what is STORED on the copy (the goal: the real gates pass on good inputs):
# * base views (``base_front`` / ``base_view``) — the stored base view of the requested signature;
# * a dressed front (``outfit_front``) / a back draft (``outfit_back_draft``) — the stored dressed view /
#   back draft on the same plain body whose worn pieces overlap the request most (exact shape first);
# * a garment chain edit (``garment_view``) — the stored accepted image of that item / fsig / step / view
#   (else its newest try); a GHOST BACK is derived from the stored WORN back (its garment pixels — worn vs
#   base back — on the neutral grey), because the stored ghost backs are the very ones Ruling A17 refuses;
# * an upscale — the input scaled ×2 (Lanczos).
# Meshes: the shape's / plain body's stored unrigged source (else the plain body's), the matching stored rig
# output (``model3d/raw``), the face retexture hands its input back unchanged, a garment mesh is the stored raw
# mesh of that item. Every answer names where it came from (``CALLS[i]['source']``).

_ctx_lock = threading.Lock()
_render_ctx: Dict[int, Dict[str, Any]] = {}   # caller thread id -> the render_character_image arguments


def _install_render_context() -> None:
    from app.core import expression_regen
    real = expression_regen.render_character_image
    if getattr(real, "_e2e", False):
        return

    def wrapped(character_name, **kw):
        ctx = {"character": character_name, **{k: kw.get(k) for k in (
            "output_stem", "occasion", "sidecar_extra", "equipped_pieces", "override_width", "override_height",
            "crop_back_to", "reference_image", "back_view", "image_use_case")}}
        tid = threading.get_ident()
        with _ctx_lock:
            _render_ctx[tid] = ctx
        try:
            return real(character_name, **kw)
        finally:
            with _ctx_lock:
                _render_ctx.pop(tid, None)
    wrapped._e2e = True
    expression_regen.render_character_image = wrapped


def _one_render_ctx() -> Dict[str, Any]:
    with _ctx_lock:
        live = list(_render_ctx.values())
    if len(live) != 1:
        raise RuntimeError(f"e2e harness: {len(live)} renders in flight — cannot tell which one this call is")
    return live[0]


def _png(path: Path) -> bytes:
    from PIL import Image
    import io
    with Image.open(path) as im:
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()


def _sidecar(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.with_suffix(".json").read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


#: The world copy the harness was given (never written): every stub answer is read from here, so a file the Build
#: deletes or replaces on its working copy is still answered from its stored state.
STOCK: Dict[str, Path] = {}


def _stock(path: Path) -> Path:
    from app.core import paths
    return STOCK["world"] / Path(path).resolve().relative_to(paths.get_storage_dir().resolve())


def _op_of(path: Path):
    from app.core import hub_ops
    for part in Path(path).parts:
        if part.startswith("hop_"):
            return hub_ops.get(part)
    return None


class Responder:
    def __init__(self) -> None:
        self.last_mesh: Dict[str, Path] = {}   # character -> the unrigged mesh handed out last
        self.overrides: List[Any] = []         # callables (backend, params, ctx) -> Optional[(bytes list, source)]

    def __call__(self, backend, prompt, params):
        category = backend.category
        rec: Dict[str, Any] = {"backend": backend.name, "category": category, "t": time.time()}
        try:
            if category == "upscale":
                blobs, source = self.upscale(params), "the input ×2"
                rec.update(occasion="upscale")
            elif backend.MEDIA_TYPE == "image":
                ctx = _one_render_ctx()
                rec.update(occasion=ctx.get("occasion"), character=ctx["character"],
                           stem=str(ctx.get("output_stem") or ""), garment=(ctx.get("sidecar_extra") or {}).get("garment"))
                blobs, source = self.image(ctx, params)
            elif category == "img2mesh":
                blobs, source = self.mesh(backend, params, rec)
            elif category == "mesh2rig":
                blobs, source = self.rig(backend, params, rec)
            elif category == "face_retexture":
                blobs, source = self.face(backend, params, rec)
            else:
                raise RuntimeError(f"e2e stub: no answer for category {category!r}")
            rec["source"] = source
            return blobs
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
            raise
        finally:
            with _calls_lock:
                CALLS.append(rec)

    # -- images -------------------------------------------------------------------------------------------------------
    @staticmethod
    def _refs(character: str) -> Path:
        from app.core.model_refs import get_model_refs_dir
        return _stock(get_model_refs_dir(character))

    def image(self, ctx: Dict[str, Any], params: Dict[str, Any]):
        for override in self.overrides:
            hit = override(ctx, params)
            if hit is not None:
                return hit
        occasion = ctx.get("occasion") or ""
        character = ctx["character"]
        stem = Path(str(ctx.get("output_stem") or ""))
        extra = ctx.get("sidecar_extra") or {}
        if occasion in ("base_front", "base_view"):
            bsig = str(extra.get("base_signature") or "")
            view = "front" if occasion == "base_front" else ("back" if ctx.get("back_view") else
                                                             stem.name.split("_")[1])
            name = f"tpose_{bsig}.png" if view == "front" else f"tpose_{view}_{bsig}.png"
            path = self._refs(character) / name
            if not path.is_file():
                raise RuntimeError(f"no stored base view {name}")
            return [_png(path)], f"stored base view {name}"
        if occasion in ("outfit_front", "outfit_back_draft"):
            return self._dressed(character, occasion, stem, ctx, extra)
        if occasion == "garment_view":
            return self._garment(character, extra.get("garment") or {})
        raise RuntimeError(f"e2e stub: no image answer for occasion {occasion!r} ({stem.name})")

    def _dressed(self, character: str, occasion: str, stem: Path, ctx: Dict[str, Any], extra: Dict[str, Any]):
        bsig = str(extra.get("base_signature") or "")
        refs = self._refs(character)
        key = stem.name.rsplit("_", 1)[-1]          # tpose_<key> / tpose_back_<key>
        want = set((ctx.get("equipped_pieces") or {}).values())
        draft = occasion == "outfit_back_draft"
        pool = (sorted((refs / "drafts").glob("tpose_back_*.png")) + sorted(refs.glob("tpose_back_ob*.png"))
                if draft else sorted(refs.glob("tpose_*.png")) + sorted((refs / "texture").glob("tpose_tex*.png")))
        best = None
        for path in pool:
            if path.name.endswith(".raw.png") or (not draft and path.name.startswith(("tpose_back_", "tpose_left_",
                                                                                      "tpose_right_", "tpose_neutral_"))):
                continue
            meta = _sidecar(path)
            if not meta.get("dressed") or (bsig and meta.get("base_signature") != bsig):
                continue
            pieces = set((meta.get("equipped_pieces") or {}).values())
            exact = path.stem.rsplit("_", 1)[-1] == key
            score = (exact, len(want & pieces) - len(pieces - want), path.parent.name == "drafts", path.name)
            if best is None or score > best[0]:
                best = (score, path)
        if best is None:
            raise RuntimeError(f"no stored dressed view on {bsig} for {stem.name}")
        path = best[1]
        return [_png(path)], f"stored {path.relative_to(refs)}"

    def _garment(self, character: str, g: Dict[str, Any]):
        from app.core import garment_store
        item, fsig, step, view = g.get("item_id"), g.get("fsig"), g.get("step"), g.get("view")
        images = _stock(garment_store.garments_dir(character)) / "images"
        base = f"{item}_{fsig}_{step}_{view}"
        if step == "ghost" and view == "back":
            return [self._ghost_from_worn(images, f"{item}_{fsig}")], f"derived from {item}_{fsig}_worn_back.png"
        accepted = images / f"{base}.png"
        if accepted.is_file():
            return [_png(accepted)], f"stored {accepted.name}"
        tries = sorted(images.glob(f"{base}.try*.png"))
        tries = [t for t in tries if not t.name.endswith((".raw.png", ".support.png"))]
        if tries:
            return [_png(tries[-1])], f"stored {tries[-1].name}"
        # another fsig of the same item (a chain on a changed outfit / base): its accepted image of that step+view
        other = sorted(images.glob(f"{item}_*_{step}_{view}.png"), key=lambda p: p.stat().st_mtime)
        if other:
            return [_png(other[-1])], f"stored {other[-1].name} (another fsig)"
        raise RuntimeError(f"no stored garment image {base}")

    @staticmethod
    def _ghost_from_worn(images: Path, prefix: str) -> bytes:
        """The worn back's garment pixels (worn vs the chain's base back, ``garment_gates.garment_region`` — the
        region the ghost gate measures against) on the neutral grey, in the worn back's frame."""
        import io
        import numpy as np
        from PIL import Image
        from app.core import garment_gates
        from app.core.garment_images import _mask, _rgb
        from app.core.model_refs import VIEW_REFERENCE_BACKGROUND
        base, worn = images / f"{prefix}_base_back.png", images / f"{prefix}_worn_back.png"
        with Image.open(base) as im:
            size = im.size
        b_rgb, w_rgb = _rgb(base, size), _rgb(worn, size)
        region = garment_gates.garment_region(b_rgb, _mask(base, size), w_rgb, _mask(worn, size))
        out = np.empty_like(w_rgb)
        out[...] = np.asarray(VIEW_REFERENCE_BACKGROUND, dtype=np.uint8)
        out[region] = w_rgb[region]
        buf = io.BytesIO()
        Image.fromarray(out).save(buf, format="PNG")
        return buf.getvalue()

    # -- meshes -------------------------------------------------------------------------------------------------------
    def mesh(self, backend, params, rec):
        from app.core.model3d import get_model3d_dir
        src = Path(str(params.get("source_image_path") or ""))
        rec["source_image"] = src.name
        character = self._character_of(src)
        rec["character"] = character
        if "/garments/" in str(src) or src.name.startswith("item_"):
            return self._garment_mesh(backend, src, rec)
        op = _op_of(src)
        key = str((op.inputs or {}).get("signature") or "") if op is not None else src.stem.rsplit("_", 1)[-1]
        rec["key"] = key
        unrigged = _stock(get_model3d_dir(character)) / "unrigged"
        bsig = self._bsig(character)
        path = unrigged / f"{key}.glb"
        if not path.is_file() or not self._on_base(path, bsig):
            path = unrigged / f"{bsig}.glb"
        rec["answered_as"] = path.stem
        backend.set_result([{"name": f"{key}_00001_.glb", "mime": "model/gltf-binary", "kind": "model"}])
        return [path.read_bytes()], f"stored unrigged/{path.name}"

    def _garment_mesh(self, backend, src: Path, rec):
        character = rec["character"]
        from app.core import garment_store
        root = _stock(garment_store.garments_dir(character))
        stem = src.name.split("_cutout")[0] if "_cutout" in src.name else src.stem
        item = "_".join(stem.split("_")[:2])
        rec["key"] = stem
        for cand in [root / "raw" / f"{stem}.glb", *sorted((root / "raw").glob(f"{item}_*.glb"))]:
            if cand.is_file():
                backend.set_result([{"name": f"{stem}_00001_.glb", "mime": "model/gltf-binary", "kind": "model"}])
                return [cand.read_bytes()], f"stored garments/raw/{cand.name}"
        raise RuntimeError(f"no stored raw garment mesh for {stem}")

    def rig(self, backend, params, rec):
        """The stored rig output of the mesh the op is for (``model3d/raw/<signature>.glb``); the op names it."""
        from app.core.model3d import get_model3d_dir
        src = Path(str(params.get("source_model_path") or ""))
        character = self._character_of(src)
        rec["character"] = character
        op = _op_of(src) or _op_of(Path(str(getattr(params.get("hub_stage"), "op", None) and
                                            params["hub_stage"].op.dir or "")))
        key = str((op.inputs or {}).get("signature") or "") if op is not None else ""
        rec["key"] = key
        raw = _stock(get_model3d_dir(character)) / "raw"
        path = raw / f"{key}.glb"
        if not key or not path.is_file():
            path = raw / f"{self._bsig(character)}.glb"
        rec["answered_as"] = path.stem
        backend.set_result([{"name": f"{path.stem}_rigged.glb", "mime": "model/gltf-binary", "kind": "model"}],
                           rig="mixamo")
        return [path.read_bytes()], f"stored raw/{path.name}"

    def face(self, backend, params, rec):
        """A hub-shaped face result: the input mesh split into a body and a face primitive (the head's top
        triangles) that share its POSITION / TEXCOORD_0, the face with a tinted copy of the base colour."""
        src = Path(str(params.get("source_model_path") or ""))
        rec["character"] = self._character_of(src)
        op = _op_of(src)
        rec["key"] = str((op.inputs or {}).get("signature") or "") if op is not None else src.stem
        backend.set_result([{"name": "corrected_00001_.glb", "mime": "model/gltf-binary", "kind": "model"}],
                           job_id="e2e-face")
        return [_face_hub_glb(src.read_bytes())], "the input mesh split into body + tinted face"

    @staticmethod
    def upscale(params):
        import io
        from PIL import Image
        with Image.open(io.BytesIO(params["image_bytes"])) as im:
            out = im.convert("RGB").resize((im.width * 2, im.height * 2), Image.LANCZOS)
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return [buf.getvalue()]

    # -- helpers ------------------------------------------------------------------------------------------------------
    @staticmethod
    def _character_of(path: Path) -> str:
        from app.core import paths
        chars = paths.get_storage_dir() / "characters"
        try:
            return path.resolve().relative_to(chars.resolve()).parts[0]
        except ValueError:
            pass
        # a hub-op input copy: worlds/<w>/hub_ops/<op>/… — the op's character from its record
        op = _op_of(path)
        if op is not None and (op.inputs or {}).get("character"):
            return str(op.inputs["character"])
        return CURRENT.get("character", "")

    @staticmethod
    def _bsig(character: str) -> str:
        from app.core import base_body
        return base_body.base_signature(character)

    @staticmethod
    def _on_base(path: Path, bsig: str) -> bool:
        meta = _sidecar(path)
        return meta.get("signature") == bsig or meta.get("base_signature") in (None, bsig)


def _face_hub_glb(raw: bytes) -> bytes:
    import io
    import struct
    import numpy as np
    from PIL import Image
    from app.core.glb_mesh import accessor_array
    from app.core.model_validate import parse_glb
    parsed = parse_glb(raw)
    gltf, binary = json.loads(json.dumps(parsed["gltf"])), bytearray(parsed["bin"])
    prim = gltf["meshes"][0]["primitives"][0]
    pos = accessor_array(parsed, prim["attributes"]["POSITION"])
    tris = accessor_array(parsed, prim["indices"]).reshape(-1, 3).astype(np.uint32)
    # The face: front-facing triangles of the band below the crown (hair above it stays body), so the
    # projected texels are skin, not dark hair — what a real projection replaces.
    top, height = pos[:, 1].max(), pos[:, 1].max() - pos[:, 1].min()
    corners = pos[tris]
    ys = corners[:, :, 1]
    normal_z = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])[:, 2]
    face_mask = ((ys < top - 0.035 * height).all(axis=1) & (ys > top - 0.10 * height).all(axis=1)
                 & (normal_z > 0))
    if not face_mask.any() or face_mask.all():
        raise RuntimeError("e2e face stub: no head triangles to split")

    def append(blob: bytes) -> int:
        while len(binary) % 4:
            binary.append(0)
        start = len(binary)
        binary.extend(blob)
        gltf["bufferViews"].append({"buffer": 0, "byteOffset": start, "byteLength": len(blob)})
        return len(gltf["bufferViews"]) - 1

    def indices(sel) -> int:
        view = append(np.ascontiguousarray(sel, dtype=np.uint32).tobytes())
        gltf["bufferViews"][view]["target"] = 34963
        gltf["accessors"].append({"bufferView": view, "componentType": 5125, "count": int(sel.size),
                                  "type": "SCALAR"})
        return len(gltf["accessors"]) - 1

    material = gltf["materials"][prim["material"]]
    texture = gltf["textures"][material["pbrMetallicRoughness"]["baseColorTexture"]["index"]]
    from app.core.model_validate import texture_image_index
    image = gltf["images"][texture_image_index(gltf, texture)]
    iv = gltf["bufferViews"][image["bufferView"]]
    base = Image.open(io.BytesIO(bytes(parsed["bin"][iv.get("byteOffset", 0):iv.get("byteOffset", 0) + iv["byteLength"]])))
    tinted = Image.blend(base.convert("RGB"), Image.new("RGB", base.size, (205, 160, 140)), 0.6)
    buf = io.BytesIO()
    tinted.save(buf, format="PNG")
    gltf["images"].append({"bufferView": append(buf.getvalue()), "mimeType": "image/png"})
    gltf["textures"].append({k: v for k, v in texture.items() if k not in ("source", "extensions")}
                            | {"source": len(gltf["images"]) - 1})
    face_material = json.loads(json.dumps(material))
    face_material["name"] = "face"
    face_material["pbrMetallicRoughness"]["baseColorTexture"] = {"index": len(gltf["textures"]) - 1}
    gltf["materials"].append(face_material)
    body = dict(prim, indices=indices(tris[~face_mask].ravel()))
    face_prim = dict(prim, indices=indices(tris[face_mask].ravel()), material=len(gltf["materials"]) - 1)
    gltf["meshes"][0]["primitives"] = [body, face_prim]
    while len(binary) % 4:
        binary.append(0)
    gltf["buffers"] = [{"byteLength": len(binary)}]
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(binary))
    out += struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(binary), 0x004E4942) + bytes(binary)
    return out


#: The character the scenario runs (fallback of ``Responder._character_of``).
CURRENT: Dict[str, str] = {}


# --- Setup ---------------------------------------------------------------------------------------------------------

#: The instance settings the harness writes (temp instance; never the real one): the render sizes the live
#: instance uses (plain numbers, no secret) and the stub backends — nothing else, no LLM provider.
RENDER_SIZES = {"tpose_image_width": 1536, "tpose_image_height": 1536, "outfit_image_width": 640,
                "outfit_image_height": 960, "expression_image_width": 768, "expression_image_height": 768}


def _refuse_live_world(world: Path) -> None:
    """A world directory directly under a repository's ``worlds/`` (beside ``app/server.py``) is a live world."""
    resolved = world.resolve()
    if resolved.parent.name == "worlds" and (resolved.parent.parent / "app" / "server.py").is_file():
        raise SystemExit(f"refused: {world} is a live world — pass a COPY")


def setup(world: Path, tmp: Path, *, plugins: Path, shared_items: Path, u2net_home: Path) -> None:
    """Paths, the temp instance with the stub backends, config, schema, packages (``plugins``) and a private
    shared directory whose ``items`` is a COPY of ``shared_items`` (the Build may write items; never the repo)."""
    _refuse_live_world(world)
    instance = tmp / "instance"
    instance.mkdir(parents=True, exist_ok=True)
    register_stub_types()
    (instance / "config.json").write_text(json.dumps({
        "providers": [], "llm_routing": [],
        "image_generation": {**RENDER_SIZES, "u2net_home": str(u2net_home),
                             "backends": [dict(b) for b in STUB_BACKENDS],
                             "routing": STUB_ROUTING},
        "embedding": {"backend": "internal"}}, indent=1))
    os.environ["STORAGE_DIR"] = str(world)
    os.environ["INSTANCE_DIR"] = str(instance)
    (tmp / "clips").mkdir(exist_ok=True)
    os.environ["ANIMATION_CLIPS_DIR"] = str(tmp / "clips")
    from app.core import paths
    paths.init(world)
    paths.init_instance(instance)
    # A private shared dir: items copied, everything else read through symlinks.
    shared = tmp / "shared"
    if not shared.exists():
        shared.mkdir()
        for entry in (ROOT / "shared").iterdir():
            if entry.name != "items":
                (shared / entry.name).symlink_to(entry)
        shutil.copytree(shared_items, shared / "items")
    paths.get_shared_dir = lambda: shared
    from app.models import inventory
    inventory._get_shared_dir = lambda: shared
    from app.core import config
    config.load(paths.get_config_path(), instance_path=instance / "config.json")
    from app.core import db
    db.init_schema()
    import plugins as _plugins_pkg   # the symlinked packs import as plugins.<name>
    if str(plugins) not in list(_plugins_pkg.__path__):
        _plugins_pkg.__path__.append(str(plugins))
    from app.plugins.loader import discover_packages
    discover_packages(plugins, force=True)
    from app.core.provider_manager import initialize_provider_manager
    initialize_provider_manager()
    _install_render_context()
    RESPONDER["fn"] = Responder()


def boot_migrations() -> Dict[str, Any]:
    """The figure migrations the server runs at boot, in ``app/server.py`` order (each idempotent,
    world_kv-marked); the model-fit re-make synchronously (the server starts it in a thread)."""
    out: Dict[str, Any] = {}
    from app.core import figure_migration, hair_migration, model_fit_remake
    for name, fn in (("hair_migration.delete_all_hair_once", hair_migration.delete_all_hair_once),
                     ("migrate_modes_once", figure_migration.migrate_modes_once),
                     ("rekey_bodies_once", figure_migration.rekey_bodies_once),
                     ("stamp_figures_once", figure_migration.stamp_figures_once),
                     ("redefault_modes_once", figure_migration.redefault_modes_once),
                     ("drop_pipeline_key_once", figure_migration.drop_pipeline_key_once),
                     ("drop_fit_globs_once", figure_migration.drop_fit_globs_once),
                     ("migrate_hairstyles_once", figure_migration.migrate_hairstyles_once),
                     ("model_fit_remake.remake_once", model_fit_remake.remake_once)):
        try:
            out[name] = fn()
        except Exception as e:  # noqa: BLE001 — reported
            out[name] = f"FAILED: {e}"
    return out


def describe(character: str) -> Dict[str, Any]:
    from app.core import figure, figure_build
    from app.models.character import get_character_profile
    wanted, delivered = figure._delivered(character, profile=get_character_profile(character))
    steps = figure_build.plan(character)
    return {"wanted": wanted.as_dict(), "delivered": delivered.as_dict(),
            "plan": [s.as_dict() for s in steps], "cost": figure_build.cost(character, steps)}


# --- Running a Build -------------------------------------------------------------------------------------------------

STEP_LOG: List[Dict[str, Any]] = []
LOGS: List[Dict[str, Any]] = []


class _Capture:
    """Every log record of the run (level, logger, message) for the checks."""
    level = 0

    def handle(self, record) -> None:
        try:
            LOGS.append({"level": record.levelname, "name": record.name, "msg": record.getMessage(),
                         "t": record.created})
        except Exception:  # noqa: BLE001 — a bad format string is not the harness's failure
            pass


def _install_capture() -> None:
    import logging
    handler = logging.Handler()
    handler.emit = _Capture().handle
    logging.getLogger().addHandler(handler)
    if logging.getLogger().level > logging.INFO:
        logging.getLogger().setLevel(logging.INFO)


RUNS: List[Dict[str, Any]] = []


def _install_run_log() -> None:
    """Every Build run (the first and each follow-up the worker takes): character, reason, automatic."""
    from app.core import figure_build
    real = figure_build._run
    if getattr(real, "_e2e", False):
        return

    def wrapped(character_name, reason, *a, **k):
        RUNS.append({"character": character_name, "reason": reason, "automatic": k.get("automatic"),
                     "steps_from": len(STEP_LOG)})
        return real(character_name, reason, *a, **k)
    wrapped._e2e = True
    figure_build._run = wrapped


def _install_step_log() -> None:
    _install_run_log()
    from app.core import figure_build
    real = figure_build._run_step
    if getattr(real, "_e2e", False):
        return

    def wrapped(character_name, step, explicit):
        entry = {"character": character_name, "step": step.name, "label": step.label, "item_id": step.item_id,
                 "jobs": step.jobs, "calls_before": len(CALLS), "t0": time.time()}
        STEP_LOG.append(entry)
        try:
            error = real(character_name, step, explicit)
            entry["error"] = error
            return error
        except figure_build.StepSuperseded as e:
            entry["superseded"] = str(e) or "superseded"
            raise
        except Exception as e:
            entry["error"] = f"raised {type(e).__name__}: {e}"
            raise
        finally:
            entry["calls"] = CALLS[entry["calls_before"]:]
            entry["seconds"] = round(time.time() - entry["t0"], 1)
    wrapped._e2e = True
    figure_build._run_step = wrapped


def wait_quiet(character: str, timeout: float = 5400.0, settle: float = 4.0) -> None:
    """Until no Build, no base Run all and no garment assembly of ``character`` has gone for ``settle`` s."""
    from app.core import figure_build, garment_assembly, model3d
    deadline = time.time() + timeout
    quiet_since = None
    while True:
        busy = (figure_build.running(character) or figure_build.base_run_all(character).get("running")
                or model3d.generation_running(character))
        if not busy:
            garment_assembly.wait_idle(timeout=900.0)
            quiet_since = quiet_since or time.time()
            if time.time() - quiet_since >= settle:
                return
        else:
            quiet_since = None
        if time.time() > deadline:
            raise RuntimeError(f"{character} still busy after {timeout} s")
        time.sleep(0.5)


def _builds_started(character: str, since: int) -> int:
    """Build RUNS of ``character`` since ``RUNS[since]`` (the first and every follow-up)."""
    return sum(1 for r in RUNS[since:] if r["character"] == character)


def run_build(character: str, *, automatic: bool = False, reason: str = "e2e") -> Dict[str, Any]:
    from app.core import figure_build
    CURRENT["character"] = character
    planned = figure_build.plan(character, explicit=not automatic)
    runnable = figure_build._runnable(planned, not automatic)
    estimate = figure_build.cost(character, runnable)
    steps_before, calls_before, logs_before, runs_before = len(STEP_LOG), len(CALLS), len(LOGS), len(RUNS)
    started = figure_build.start(character, reason=reason, automatic=automatic)
    wait_quiet(character)
    return {"start": started, "plan": [s.as_dict() for s in planned], "runnable": [s.name for s in runnable],
            "estimate": estimate, "steps": STEP_LOG[steps_before:], "calls": CALLS[calls_before:],
            "state": figure_build.state(character), "builds": _builds_started(character, runs_before),
            "runs": [dict(r) for r in RUNS[runs_before:]], "logs": LOGS[logs_before:]}


def served(character: str) -> Dict[str, Any]:
    """The served model, the figure it was built as and the wanted figure of now."""
    from app.core import figure, model3d
    from app.models.character import get_character_profile
    path, *_rest = model3d.find_model3d_serving(character)
    meta = model3d._read_sidecar(path) if path is not None else {}
    built = figure.built_figure(meta).as_dict() if path is not None else None
    wanted, delivered = figure._delivered(character, profile=get_character_profile(character))
    return {"path": str(path) if path else None, "meta": meta, "built": built, "wanted": wanted.as_dict(),
            "delivered": delivered.as_dict(), "current": built == wanted.as_dict()}


def _what(c: Dict[str, Any]) -> str:
    g = c.get("garment")
    if g:
        return f"{g.get('item_id')} {g.get('step')} {g.get('view')} try{g.get('attempt')}"
    return str(c.get("key") or Path(c.get("stem") or "").name)


def show(result: Dict[str, Any]) -> None:
    print(f"  start: {result['start']}  estimate: {result['estimate']['note']}  builds started: {result['builds']}")
    for st in result["steps"]:
        tail = (f"  ERROR {st['error']}" if st.get("error") else f"  SUPERSEDED {st['superseded']}"
                if st.get("superseded") else "")
        print(f"   step {st['step']:9} calls {len(st['calls']):2} (est {st['jobs']}) {st['seconds']:7.1f}s  "
              f"{st['label']}{tail}"[:400])
        for c in st["calls"]:
            print(f"      - {c.get('backend'):12} {c.get('occasion') or c.get('category'):18} {_what(c):44.44} <- "
                  f"{c.get('source') or c.get('error')}")
    st = result["state"]
    print(f"  state: failed={st.get('failed')} skipped={st.get('skipped')} superseded={st.get('superseded')}")


# --- Checks ----------------------------------------------------------------------------------------------------------

class Scenario:
    def __init__(self, number: int, title: str):
        self.number, self.title, self.checks, self.notes = number, title, [], []
        self.calls: List[Dict[str, Any]] = []
        self.steps: List[Dict[str, Any]] = []
        self.estimate: Any = None

    def check(self, name: str, ok: bool, detail: Any = "") -> bool:
        self.checks.append({"name": name, "ok": bool(ok), "detail": str(detail)[:600]})
        print(f"   [{'PASS' if ok else 'FAIL'}] {name}{'  — ' + str(detail)[:600] if detail != '' else ''}")
        return bool(ok)

    def note(self, text: str) -> None:
        self.notes.append(text)
        print(f"   note: {text}")

    def take(self, result: Dict[str, Any]) -> None:
        self.calls += result["calls"]
        self.steps += [{k: (len(v) if k == "calls" else v) for k, v in s.items() if k != "calls_before"}
                       | {"call_list": [f"{c.get('occasion') or c.get('category')} {_what(c)}" for c in s["calls"]]}
                       for s in result["steps"]]
        self.estimate = result["estimate"]["hub_jobs"] if self.estimate is None else self.estimate

    def as_dict(self) -> Dict[str, Any]:
        return {"number": self.number, "title": self.title, "pass": all(c["ok"] for c in self.checks)
                and bool(self.checks), "checks": self.checks, "notes": self.notes, "steps": self.steps,
                "calls": len(self.calls), "estimate": self.estimate}


def _kind(c: Dict[str, Any]) -> str:
    return str(c.get("occasion") or c.get("category"))


def _problems(logs: List[Dict[str, Any]]) -> List[str]:
    """WARNING/ERROR lines of the pipeline modules (the harness's own and the expected ones aside)."""
    quiet = ("provider_mgr", "provider_queue", "body_slots")
    return [f"{r['name']}: {r['msg'][:300]}" for r in logs if r["level"] in ("WARNING", "ERROR", "CRITICAL")
            and not r["name"].startswith(quiet)]


def _common_checks(sc: Scenario, result: Dict[str, Any], character: str, *, allow_superseded: bool = False,
                   expected_warnings: tuple = ()) -> None:
    errors = [f"{s['step']}: {s['error']}" for s in result["steps"] if s.get("error")]
    sc.check("no step ended in an error", not errors, errors or "")
    if not allow_superseded:
        sup = [s["step"] for s in result["steps"] if s.get("superseded")]
        sc.check("no step superseded", not sup, sup or "")
    failed = result["state"].get("failed") or {}
    sc.check("Build state has no failure", not failed, failed or "")
    stub_errors = [f"{_kind(c)} {_what(c)}: {c['error']}" for c in result["calls"] if c.get("error")]
    sc.check("every stub call answered", not stub_errors, stub_errors or "")
    warnings = [w for w in _problems(result["logs"]) if not any(e in w for e in expected_warnings)]
    sc.check("no unexpected warning/error log line", not warnings, warnings or "")
    now = served(character)
    sc.check("served figure is the wanted figure", now["current"],
             "" if now["current"] else {"built": now["built"], "wanted": now["wanted"]})


# --- Scenarios -------------------------------------------------------------------------------------------------------

KAI, YLVA = "Kai", "Ylva Nordwind"
KAI_JACKET = "item_555a7a01"


def scenario_1() -> Scenario:
    """Kai as cloned: a manual Build (shape, the failed jacket chain, CPU refits, assembly)."""
    sc = Scenario(1, "Kai manual Build as cloned")
    before = served(KAI)
    result = run_build(KAI)
    show(result)
    sc.take(result)
    plan = [s["name"] for s in result["plan"]]
    sc.check("plan: shape, pieces, fits, assemble (no interim, no plain body)",
             plan == ["shape", "pieces", "fits", "assemble"], plan)
    ran = [s["step"] for s in result["steps"]]
    sc.check("steps ran once each, in plan order", ran == plan, ran)
    sc.check("exactly one Build run (a Build's own piece completion queues no follow-up)", result["builds"] == 1,
             [(r["reason"], r["automatic"]) for r in result["runs"]])
    sc.check("all stub calls == the Build's estimate (A25)", len(result["calls"]) == result["estimate"]["hub_jobs"],
             f"{len(result['calls'])} vs {result['estimate']['hub_jobs']}")
    _common_checks(sc, result, KAI)
    by = {s["step"]: s for s in result["steps"]}
    shape_key = str(before["wanted"].get("shape") or "")
    if "shape" in by:
        kinds = [_kind(c) for c in by["shape"]["calls"]]
        sc.check("shape: front, back draft, mesh, face, rig", kinds == ["outfit_front", "outfit_back_draft",
                                                                        "img2mesh", "face_retexture", "mesh2rig"],
                 kinds)
        keys = {c.get("key") for c in by["shape"]["calls"] if c.get("category") != "img2img"}
        sc.check(f"shape: mesh/face/rig all for {shape_key}", keys == {shape_key}, keys)
        sc.check("shape: calls == estimate", len(by["shape"]["calls"]) == by["shape"]["jobs"],
                 f"{len(by['shape']['calls'])} vs {by['shape']['jobs']}")
    if "pieces" in by:
        calls = by["pieces"]["calls"]
        renders = [c.get("garment") or {} for c in calls if _kind(c) == "garment_view"]
        sc.check("jacket: only the stale ghost back is rendered (A17d), the ghost front try2 is reused",
                 [(g.get("step"), g.get("view")) for g in renders] == [("ghost", "back")], renders)
        sc.check("jacket: one garment mesh", sum(_kind(c) == "img2mesh" for c in calls) == 1,
                 [_kind(c) for c in calls])
        sc.check("jacket chain 'failed — Retry': calls == its retry estimate (A25)",
                 len(calls) == by["pieces"]["jobs"],
                 f"{len(calls)} vs {by['pieces']['jobs']}: " + ", ".join(_kind(c) for c in calls))
    for step in ("fits", "assemble"):
        if step in by:
            sc.check(f"{step}: no hub job", not by[step]["calls"], [_kind(c) for c in by[step]["calls"]])
    fit_fail = [r["msg"] for r in result["logs"] if "Garment fit" in r["msg"] and "failed" in r["msg"]]
    sc.check("every garment fit accepted", not fit_fail, fit_fail)
    from app.core import figure_build
    sc.check("no Build running or queued afterwards", not figure_build.running(KAI))
    return sc


def scenario_7() -> Scenario:
    """Base body tab Run all on the current Kai: "current"; after a face-value change only the face steps."""
    from app.core import figure_build, model3d
    from app.core.face_photo_adjust import DEFAULTS
    sc = Scenario(7, "Base body Run all")
    CURRENT["character"] = KAI
    plan = figure_build.base_run_all(KAI)
    sc.check("Run all plan of the current base: nothing", plan["kind"] == "" and plan["hub_jobs"] == 0,
             {k: plan[k] for k in ("kind", "hub_jobs", "note", "face_due")})
    calls_before = len(CALLS)
    started = figure_build.start_base_run_all(KAI)
    sc.check("Run all answers 'current'", started.get("status") == "current", started)
    sc.check("Run all on current spends 0 calls", len(CALLS) == calls_before, len(CALLS) - calls_before)
    opts = model3d.get_model3d_options(KAI)
    sc.check("Kai has face before rig", bool(opts.get("face_before_rig")), opts.get("face_before_rig"))
    # Setup: the cloned base's face record predates Task UI2 (no ``settings`` fingerprint) and counts as current
    # by design whatever the values are; it gets the fingerprint of the values in force — what a face
    # retexture made since UI2 records — so a change of the values is what makes the face step due.
    from app.core import base_body
    base_path = model3d.find_model3d(KAI, base_body.base_signature(KAI))
    meta = model3d._read_sidecar(base_path)
    if isinstance(meta.get("face_retexture"), dict) and not meta["face_retexture"].get("settings"):
        meta["face_retexture"]["settings"] = model3d.face_settings_fingerprint(KAI)
        model3d._publish_sidecar(base_path, meta)
        sc.note("setup: stamped the face settings fingerprint of the values in force into the cloned base's "
                "pre-UI2 face record")
        sc.check("Run all still 'current' with the stamped record", figure_build.base_run_all(KAI)["kind"] == "")
    photo = dict(opts.get("face_photo") or DEFAULTS)
    key = next(k for k in DEFAULTS if k not in ("balance", "tone_match", "skin_recolor"))
    photo[key] = 1.25 if float(photo.get(key, 1.0)) != 1.25 else 1.1
    model3d.set_model3d_options(KAI, {"face_photo": photo})
    plan = figure_build.base_run_all(KAI)
    names = [s["name"] for s in plan["steps"]]
    sc.check(f"after a face-value change ({key} -> {photo[key]}): only face steps planned",
             plan["kind"] != "" and names and not ({"view front", "skin front", "mesh"} & set(names)),
             {"kind": plan["kind"], "steps": plan["steps"], "face_due": plan["face_due"], "note": plan["note"]})
    sc.estimate = plan["hub_jobs"]
    calls_before, steps_before, logs_before = len(CALLS), len(STEP_LOG), len(LOGS)
    started = figure_build.start_base_run_all(KAI)
    sc.check("Run all starts", started.get("status") == "started", started)
    wait_quiet(KAI)
    calls = CALLS[calls_before:]
    base_calls = [c for c in calls if c["t"] and not any(c in s["calls"] for s in STEP_LOG[steps_before:])]
    sc.calls = base_calls
    kinds = [_kind(c) for c in base_calls]
    print("   run-all calls:", kinds)
    sc.check("Run all spent no image render and no mesh", not ({"img2mesh"} & set(kinds))
             and not any(c.get("category") == "img2img" for c in base_calls), kinds)
    sc.check("Run all calls == its estimate", len(base_calls) == (plan["hub_jobs"] or 0),
             f"{len(base_calls)} vs {plan['hub_jobs']}")
    last = figure_build.base_run_all(KAI)
    sc.check("Run all ended without error", not (last.get("last") or {}).get("error"), last.get("last"))
    sc.check("base is current again", last["kind"] == "", {k: last[k] for k in ("kind", "note", "face_due")})
    rec = model3d._read_sidecar(model3d.find_model3d(KAI, __import__("app.core.base_body", fromlist=["x"])
                                                      .base_signature(KAI))).get("face_retexture") or {}
    sc.check("base model face record applied with the new settings",
             rec.get("status") == "applied" and rec.get("settings") == model3d.face_settings_fingerprint(KAI),
             {k: rec.get(k) for k in ("status", "settings", "error")})
    warnings = _problems(LOGS[logs_before:])
    sc.check("no unexpected warning/error log line", not warnings, warnings)
    # What the automatic path did with the refreshed base (scenario 6 reads it).
    STATE["after_run_all"] = {"steps": STEP_LOG[steps_before:], "logs_from": logs_before,
                              "builds": sum(1 for r in RUNS if r["steps_from"] >= steps_before)}
    return sc


STATE: Dict[str, Any] = {}


def scenario_6() -> Scenario:
    """An automatic Build after a manual base refresh builds on the new base without redoing the base."""
    from app.core import figure_build
    sc = Scenario(6, "Automatic Build after a manual base refresh")
    after = STATE.get("after_run_all") or {}
    if after.get("builds"):
        sc.note(f"the base refresh itself requested {after['builds']} automatic Build(s): "
                + ", ".join(f"{s['step']}({len(s['calls'])})" for s in after["steps"]))
    plan = figure_build.plan(KAI, explicit=False)
    sc.note("automatic plan now: " + (", ".join(f"{s.name}[{s.jobs}]{' manual' if s.manual else ''}"
                                                for s in plan) or "nothing"))
    result = run_build(KAI, automatic=True, reason="e2e automatic after base refresh")
    show(result)
    sc.take(result)
    auto_steps = list(after.get("steps") or []) + result["steps"]
    names = [s["step"] for s in auto_steps]
    sc.check("no plain-body step in the automatic Build(s)", "plain_body" not in names, names)
    base_calls = [c for s in auto_steps for c in s["calls"] if _kind(c) in ("base_front", "base_view")]
    sc.check("no base view rendered", not base_calls, [_what(c) for c in base_calls])
    _common_checks(sc, result, KAI)
    now = served(KAI)
    from app.core import base_body
    sc.check("served figure stands on the current base model",
             now["meta"].get("base_model_sha256") in (None, base_body.current_base(KAI)[1])
             if base_body.current_base(KAI) else False,
             {"figure": now["meta"].get("base_model_sha256"), "base": base_body.current_base(KAI)})
    return sc


def scenario_2() -> Scenario:
    """Ylva (HairDeck): the automatic Build makes the bald shape — back accepted at its first draft, head
    taken over (A16/A21) — and assembles."""
    sc = Scenario(2, "Ylva bald shape")
    before = served(YLVA)
    from app.core import figure_build
    manual = figure_build.plan(YLVA, explicit=True)
    sc.note("a MANUAL Build of Ylva would plan: " + ", ".join(f"{s.name}[{s.jobs}]{' (' + s.manual + ')' if s.manual else ''}"
                                                              for s in manual)
            + f" = {figure_build.cost(YLVA, manual)['note']}")
    result = run_build(YLVA, automatic=True)
    show(result)
    sc.take(result)
    ran = [s["step"] for s in result["steps"]]
    sc.check("automatic Build runs the shape and no plain body", "shape" in ran and "plain_body" not in ran, ran)
    sc.check("all stub calls == the Build's estimate (A24: the outdated back re-composited, no draft)",
             len(result["calls"]) == result["estimate"]["hub_jobs"],
             f"{len(result['calls'])} vs {result['estimate']['hub_jobs']}: " + ", ".join(_kind(c) for c in result["calls"]))
    _common_checks(sc, result, YLVA)
    shape = str(before["wanted"].get("shape") or "")
    from app.core.model_refs import get_model_refs_dir
    meta = _sidecar(get_model_refs_dir(YLVA) / f"tpose_back_{shape}.png")
    fit = meta.get("fit_gate") or meta.get("fit") or {}
    attempts = fit.get("attempts") or []
    sc.check("dressed back accepted at its first draft (A16)", fit.get("chosen") == 1 and fit.get("ok") is True
             and len(attempts) == 1, {k: fit.get(k) for k in ("chosen", "ok", "warning")} | {"attempts": len(attempts)})
    head = ((attempts[0] if attempts else {}).get("composite") or {}).get("head")
    sc.check("the draft's head is taken over (A21)", bool(head), head)
    by = {s["step"]: s for s in result["steps"]}
    if "shape" in by:
        sc.check("shape: calls == estimate", len(by["shape"]["calls"]) == by["shape"]["jobs"],
                 f"{len(by['shape']['calls'])} vs {by['shape']['jobs']}")
    return sc


def scenario_3() -> Scenario:
    """A hairstyle change while Kai's shape renders: that step ends superseded, ONE follow-up builds the new
    figure, nothing stale goes to face/rig (A18)."""
    from app.core import garment_hair
    sc = Scenario(3, "Supersede during the shape step")
    before = served(KAI)
    old_shape = str(before["wanted"].get("shape") or "")
    fired: Dict[str, Any] = {}

    def change_hair(ctx, params):
        if fired or ctx.get("occasion") != "outfit_back_draft" or ctx["character"] != KAI:
            return None
        item = garment_hair.create_hairstyle(KAI, "shoulder-length wavy auburn hair", mode="body")
        fired["item"] = item
        fired["saved"] = garment_hair.wear_hairstyle(KAI, item)
        return None
    RESPONDER["fn"].overrides.append(change_hair)
    try:
        result = run_build(KAI)
    finally:
        RESPONDER["fn"].overrides.remove(change_hair)
    show(result)
    sc.take(result)
    sc.check("the hairstyle change happened during the shape step", fired.get("saved") is True, fired)
    sup = [s for s in result["steps"] if s.get("superseded")]
    sc.check("the shape step ended superseded", [s["step"] for s in sup] == ["shape"],
             [(s["step"], s.get("superseded")) for s in sup])
    sc.check("exactly ONE follow-up for the supersede (A18)",
             sum(r["reason"] == "superseded" for r in result["runs"]) == 1, result["runs"])
    sc.check("no further follow-up run (a Build's own piece completion queues none)", result["builds"] == 2,
             [(r["reason"], r["automatic"]) for r in result["runs"]])
    stale = [f"{_kind(c)} {c.get('key')}" for c in result["calls"]
             if _kind(c) in ("face_retexture", "mesh2rig") and c.get("key") == old_shape]
    sc.check(f"no face/rig of the stale shape {old_shape}", not stale, stale)
    now = served(KAI)
    sc.check("new shape differs from the old", now["wanted"].get("shape") != old_shape, now["wanted"].get("shape"))
    _common_checks(sc, result, KAI, allow_superseded=True)
    return sc


def scenario_4_5() -> List[Scenario]:
    """Base-body routes answer 409 during a Build (A20); an LOD failure is a warning, the figure is delivered
    (A19)."""
    from fastapi import HTTPException
    from app.core import figure_build, model3d
    from app.routes import characters as routes
    s4, s5 = Scenario(4, "Base routes during a Build"), Scenario(5, "LOD failure")
    answers: Dict[str, Any] = {}

    def probe(ctx, params):
        if answers or ctx["character"] != KAI:
            return None
        for name, call in (
                ("images", lambda: routes.generate_character_base_body_images(
                    KAI, routes.BaseBodyImagesRequest(), {})),
                ("model", lambda: routes.generate_character_base_body_model(KAI, routes.BaseBodyModelRequest(), {})),
                ("skin-step", lambda: routes.rerun_character_base_body_skin_step(KAI, {}))):
            try:
                answers[name] = ("answered", call())
            except HTTPException as e:
                answers[name] = (e.status_code, e.detail)
        answers["run-all"] = figure_build.start_base_run_all(KAI)
        return None
    real_lod = model3d.build_lod
    lod_calls: List[str] = []

    def failing_lod(character_name, signature, *a, **k):
        lod_calls.append(f"{character_name}/{signature}")
        if character_name == KAI:
            raise RuntimeError("injected LOD failure (e2e)")
        return real_lod(character_name, signature, *a, **k)
    RESPONDER["fn"].overrides.append(probe)
    model3d.build_lod = failing_lod
    try:
        result = run_build(KAI)
    finally:
        RESPONDER["fn"].overrides.remove(probe)
        model3d.build_lod = real_lod
    show(result)
    s4.take(result)
    s5.take(result)
    for name in ("images", "model", "skin-step"):
        got = answers.get(name)
        s4.check(f"POST base-body/{name} during the Build: 409 BASE_BUILD_RUNNING",
                 bool(got) and got[0] == 409 and got[1] == figure_build.BASE_BUILD_RUNNING, got)
    s4.check("base Run all during the Build: 'building'", (answers.get("run-all") or {}).get("status") == "building",
             answers.get("run-all"))
    s4.check("the Build itself was not disturbed",
             not any(s.get("error") for s in result["steps"]) and not (result["state"].get("failed") or {}),
             result["state"].get("failed"))
    s5.check("the LOD build was attempted (and failed by injection)", bool(lod_calls), lod_calls)
    _common_checks(s5, result, KAI, expected_warnings=("injected LOD failure",))
    now = served(KAI)
    s5.check("the delivered model records the LOD failure as a warning (lod_error)",
             "injected LOD failure" in str(now["meta"].get("lod_error") or ""), now["meta"].get("lod_error"))
    return [s4, s5]


#: Each group runs in its own process on its own fresh copy of the stock world.
GROUPS: Dict[str, Callable[[], List[Scenario]]] = {
    "1,7,6": lambda: [scenario_1(), scenario_7(), scenario_6()],
    "2": lambda: [scenario_2()],
    "3": lambda: [scenario_3()],
    "4,5": scenario_4_5,
    "1": lambda: [scenario_1()],
}


# --- Main ------------------------------------------------------------------------------------------------------------

def _child(args) -> int:
    tmp = Path(tempfile.mkdtemp(prefix="e2e_figure_"))
    out: Dict[str, Any] = {"scenarios": [], "outbound": None, "crash": None}
    try:
        STOCK["world"] = args.stock.resolve()
        setup(args.world, tmp, plugins=args.plugins, shared_items=args.shared_items, u2net_home=args.u2net_home)
        _install_capture()
        if args.log:
            import logging
            handler = logging.FileHandler(args.log)
            handler.setFormatter(logging.Formatter("%(asctime)s %(threadName)s [%(name)s] %(levelname)s %(message)s"))
            logging.getLogger().addHandler(handler)
        _install_step_log()
        if not args.no_migrate:
            print("boot migrations:", json.dumps(boot_migrations(), default=str)[:1500])
        if args.plan_only:
            for c in (KAI, YLVA):
                d = describe(c)
                print(f"== {c}\n wanted    {json.dumps(d['wanted'], default=str)}\n delivered "
                      f"{json.dumps(d['delivered'], default=str)}")
                for s in d["plan"]:
                    print(f"  - {s['name']:10} {s['jobs']!s:>4}  {s['label']}"
                          f"{'  [manual: ' + s['manual'] + ']' if s['manual'] else ''}"
                          f"{'  [failed: ' + s['failed'][:200] + ']' if s['failed'] else ''}")
                print("  cost:", d["cost"]["note"])
            return 0
        for sc in GROUPS[args.group]():
            out["scenarios"].append(sc.as_dict())
    except Exception:  # noqa: BLE001 — reported as the group's crash
        import traceback
        out["crash"] = traceback.format_exc()
        print(out["crash"])
    finally:
        out["outbound"] = list(OUTBOUND)
        if args.result:
            args.result.write_text(json.dumps(out, default=str, indent=1))
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--world", required=True, type=Path, help="a COPY of a world (read only; never written)")
    ap.add_argument("--plugins", type=Path, default=ROOT / "plugins")
    ap.add_argument("--shared-items", type=Path, default=ROOT / "shared" / "items")
    ap.add_argument("--u2net-home", type=Path, default=ROOT / "models" / "u2net")
    ap.add_argument("--only", default="", help="scenario groups, e.g. '1,7,6;2'")
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--no-migrate", action="store_true")
    ap.add_argument("--workdir", type=Path, default=None, help="where the working copies go (default: a temp dir)")
    ap.add_argument("--log-dir", type=Path, default=None)
    ap.add_argument("--keep", action="store_true", help="keep the working copies (diagnosis)")
    # child mode (one group on one working copy)
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--stock", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--group", default="", help=argparse.SUPPRESS)
    ap.add_argument("--result", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--log", type=Path, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.child:
        return _child(args)
    _refuse_live_world(args.world)
    import subprocess
    work = Path(tempfile.mkdtemp(prefix="e2e_figure_work_", dir=args.workdir))
    groups = [g for g in (args.only.split(";") if args.only else GROUPS) if g]
    if args.plan_only:
        groups = groups[:1]
    results, failed = [], False
    try:
        for group in groups:
            if group not in GROUPS and not args.plan_only:
                raise SystemExit(f"unknown group {group!r} (known: {'; '.join(GROUPS)})")
            copy = work / "world"
            print(f"\n##### group {group}: copying the world …", flush=True)
            subprocess.run(["cp", "-a", str(args.world), str(copy)], check=True)
            res = work / f"result_{group.replace(',', '_')}.json"
            log = (args.log_dir / f"group_{group.replace(',', '_')}.log") if args.log_dir else None
            cmd = [sys.executable, str(Path(__file__).resolve()), "--child", "--stock", str(args.world),
                   "--world", str(copy), "--group", group, "--result", str(res),
                   "--plugins", str(args.plugins), "--shared-items", str(args.shared_items),
                   "--u2net-home", str(args.u2net_home)]
            cmd += ["--log", str(log)] if log else []
            cmd += ["--no-migrate"] if args.no_migrate else []
            cmd += ["--plan-only"] if args.plan_only else []
            subprocess.run(cmd, check=False)
            if args.keep:
                kept = work.parent / f"kept_{group.replace(',', '_')}"
                shutil.rmtree(kept, ignore_errors=True)
                copy.rename(kept)
                print(f"kept the working copy at {kept}")
            shutil.rmtree(copy, ignore_errors=True)
            if args.plan_only:
                return 0
            data = json.loads(res.read_text()) if res.is_file() else {"crash": "no result file", "scenarios": [],
                                                                       "outbound": ["unknown"]}
            results.append((group, data))
        print("\n##### SUMMARY")
        total_out = 0
        for group, data in results:
            total_out += len(data.get("outbound") or [])
            if data.get("crash"):
                failed = True
                print(f"group {group}: CRASH\n{data['crash'][-1500:]}")
            for sc in data["scenarios"]:
                failed |= not sc["pass"]
                print(f"Scenario {sc['number']}: {'PASS' if sc['pass'] else 'FAIL'} — {sc['title']} "
                      f"(stub calls {sc['calls']}, estimate {sc['estimate']})")
                for st in sc["steps"]:
                    print(f"    {st['step']:9} {st['calls']:2} call(s) est {st['jobs']}"
                          f"{'  ERROR ' + str(st['error']) if st.get('error') else ''}"
                          f"{'  SUPERSEDED' if st.get('superseded') else ''}  {st['label']}")
                for c in sc["checks"]:
                    if not c["ok"]:
                        print(f"    FAIL {c['name']}: {c['detail']}")
                for n in sc["notes"]:
                    print(f"    note: {n}")
            for o in data.get("outbound") or []:
                print(f"    OUTBOUND {o}")
        print(f"outbound requests: {total_out}")
        failed |= total_out > 0
        print("RESULT:", "FAIL" if failed else "PASS")
        return 1 if failed else 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
