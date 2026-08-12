#!/usr/bin/env python3
"""Smoke run for the mesh gateway client: param mapping + result splitting.

No world, no DB, no server, no gateway: the backend object is built from env
vars (the config bridge), fed a hand-written alias schema, and asked what it
would SEND; the service's result splitter is fed hand-written job-view results
and asked what it would STORE.

Every expectation below is derived by hand from the client spec
(llm-gateway/docs/mesh-client-spec.md, 2026-08-03), not from what the code
currently prints:

  § 1  — every public param name is ``input_*``; unknown names are silently
         ignored, so an UNREADABLE schema may send the input_* names blind.
  § 3.2 — the img2mesh families take input_name (always set — it decides the
         delivered file names), input_remove_background, input_face_num,
         input_texture_resolution, input_no_fingers.
  § 3.1 — input_no_fingers is accepted by ALL families (not just humanoid).
  § 3.3 — Triposplat declares NO input_face_num: the same detail value goes
         out as input_num_gaussians, and with no value configured nothing is
         sent at all (the alias default 10000 stands).
  § 3.2 warning — Hunyuan3D freezes above face_num 40000: face_num_max caps
         the effective value (config data, no family name in the code).
  § 2 rule 1 — artifacts are matched by TOKEN substring in the delivered name
         (_basecolor / _metallic / _articulationxl) plus kind/mime, never by
         position or extension.
  § 3.2 LOD — Hunyuan3D-Object bakes extra stages in the SAME job:
         ``input_lod_faces`` is a comma-separated list of target triangle
         counts sent as a STRING, each stage comes back self-contained. The
         MAIN result ends on ``_00001_.glb``, a stage on ``_<digits>.glb``
         (digits directly before the extension, the REQUESTED value). The
         response order is ALPHABETICAL by file name, never the requested
         order — so the main mesh must be found by NAME; a positional pick
         takes a stage. ``input_name`` must be unique per job: the stages live
         under that name on the backend and a repeat run with fewer stages
         hands the older ones out again.
  § 2 rule 2 + § 3.1 — rig mixamo/none store ONLY the GLB (texture embedded);
         rig generic stores the FBX AND its *_basecolor* as an inseparable
         pair, dropping *_metallic*. Extensions come per FILE from the
         response (a basecolor may be .png while the metallic map of the SAME
         job is .jpg).
  § 3.4 — mesh-shrink takes the source mesh as a FILE IN THE REQUEST
         (``files.input_mesh_path``: base64 / data-URI / http-URL), never in
         ``params`` — there the name would mean a path on the gateway's own
         backend. Params: input_name, input_face_num (default 5000),
         input_texture_resolution (default 1024); no image slot at all.
         Delivery is ``<name>_00001_.glb`` + ``*_basecolor*.png`` +
         ``*_metallic*.png`` (always PNG here), and the GLB may be reported
         with ``kind: "file"`` — § 1 says every mesh is ``"file"``, so a
         filter on ``kind == "model"`` finds nothing.
  § 1  — ``files`` is STRICT: over 64 MB the gateway answers 413. The client
         refuses that size itself instead of uploading it first.
  § 3.3 — a Triposplat GLB carries its colour in the VERTICES (``COLOR_0``,
         ``KHR_materials_unlit``): no UVs, no texture images. § 3.4 — the
         reduction re-bakes the texture onto the new topology, so it NEEDS UVs
         plus an embedded texture; on such a mesh the job dies with
         ``node 21 …: expected np.ndarray (got NoneType)``, permanently.
         Hence: probe the FILE (never the alias name), block the action, and
         classify that job error as an INPUT problem — no backend cooldown.
  gateway note (2026-08-03) — the job view gains ``input_images[]`` with
         ``sha256`` (like ``results[]``) after the input-mix-up fix: compare it
         against what we uploaded; absent field = old gateway = no check.

Usage:  ./.venv/bin/python scripts/smoke_mesh_gateway.py
"""
import hashlib
import json
import os
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.model_validate import (glb_capabilities_at,  # noqa: E402
                                     shrink_capability)
from app.imagegen.backends._gateway_job import (  # noqa: E402
    _TERMINAL_JOB_ERROR)
from app.imagegen.backends.openai_mesh import (  # noqa: E402
    LOD_FACES_PARAM, MESH_UPLOAD_MAX_BYTES, OpenAIMeshBackend,
    normalize_lod_faces)
from app.imagegen.base import (BackendBusyError,  # noqa: E402
                               GatewayInputMismatchError, GatewayRejectedError)
from app.imagegen.selection import BackendPool  # noqa: E402
from app.imagegen.service import (_mesh_file_suffix,  # noqa: E402
                                  _split_mesh_files, _unique_mesh_name,
                                  mesh_lod_stage_faces)

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def backend(alias: str, *, rig: str = "mixamo", face_num: str = "",
            face_num_max: str = "", declared=None) -> OpenAIMeshBackend:
    """A backend as the config bridge would build it, with a hand-written
    alias schema. ``declared=None`` = schema unreadable."""
    prefix = "SMOKE_MESH_"
    for k in list(os.environ):
        if k.startswith(prefix):
            del os.environ[k]
    os.environ[f"{prefix}MESH_RIG"] = rig
    os.environ[f"{prefix}FACE_NUM"] = face_num
    os.environ[f"{prefix}FACE_NUM_MAX"] = face_num_max
    os.environ[f"{prefix}NO_FINGERS"] = "true"
    b = OpenAIMeshBackend(name=alias, api_url="http://gateway.invalid",
                          cost=1, env_prefix=prefix, model=alias)
    b._alias_param_names = set(declared or [])
    return b


# --- (a) a full img2mesh schema ------------------------------------------
print("\n(a) alias declaring input_face_num / input_texture_resolution / "
      "input_no_fingers")
FULL = ["input_name", "input_remove_background", "input_face_num",
        "input_texture_resolution", "input_no_fingers"]
b = backend("Trellis2-Humanoid-Low", face_num="20000", declared=FULL)
p = b.build_alias_params({"mesh_name": "Held", "texture_size": 1024})
check("input_name = the mesh name", p.get("input_name") == "Held", str(p))
check("input_remove_background sent", p.get("input_remove_background") is True)
check("input_face_num = 20000", p.get("input_face_num") == 20000)
check("input_texture_resolution = 1024",
      p.get("input_texture_resolution") == 1024)
check("input_no_fingers sent", p.get("input_no_fingers") is True)
check("no legacy space-names", not any(" " in k for k in p), str(sorted(p)))
check("no input_num_gaussians on a face alias", "input_num_gaussians" not in p)

# input_name must never go out empty (§ 3.2: empty inherits workflow leftovers)
p2 = b.build_alias_params({})
check("empty mesh_name falls back to the alias",
      p2.get("input_name") == "Trellis2-Humanoid-Low", str(p2.get("input_name")))

# § 3.1: no_fingers is NOT humanoid-only any more
b_gen = backend("Trellis2-Generic-Low", rig="generic", face_num="20000",
                declared=FULL)
p3 = b_gen.build_alias_params({"mesh_name": "Wolf"})
check("input_no_fingers also on a generic alias (§ 3.1)",
      p3.get("input_no_fingers") is True, str(p3))

# --- (b) Triposplat: input_num_gaussians only ----------------------------
print("\n(b) Triposplat-style schema (input_num_gaussians, no face param)")
SPLAT = ["input_name", "input_remove_background", "input_num_gaussians",
         "input_texture_resolution"]
b = backend("Triposplat-Object", rig="none", face_num="", declared=SPLAT)
p = b.build_alias_params({"mesh_name": "Vase", "texture_size": 512})
check("nothing configured -> NO detail param (alias default 10000 stands)",
      "input_num_gaussians" not in p and "input_face_num" not in p, str(p))
check("input_no_fingers dropped (not declared)", "input_no_fingers" not in p)
check("input_texture_resolution = 512", p.get("input_texture_resolution") == 512)
p = b.build_alias_params({"mesh_name": "Vase", "face_num": 30000})
check("per-run face value goes out as input_num_gaussians",
      p.get("input_num_gaussians") == 30000 and "input_face_num" not in p, str(p))

# --- (c) unreadable schema ------------------------------------------------
print("\n(c) no schema (GET /schema unreachable)")
b = backend("Hunyuan3D-Object", rig="none", face_num="40000", declared=None)
p = b.build_alias_params({"mesh_name": "Fass", "texture_size": 1024})
check("input_face_num sent blind", p.get("input_face_num") == 40000, str(p))
check("input_no_fingers sent blind", p.get("input_no_fingers") is True)
check("input_texture_resolution sent blind",
      p.get("input_texture_resolution") == 1024)
check("still no input_num_gaussians (classic name is the blind default)",
      "input_num_gaussians" not in p)

# --- (d) face_num_max clamp ----------------------------------------------
print("\n(d) face_num_max (Hunyuan3D freezes above 40000, § 3.2)")
b = backend("Hunyuan3D-Humanoid", face_num="40000", face_num_max="40000",
            declared=FULL)
check("configured value passes unchanged",
      b.build_alias_params({}).get("input_face_num") == 40000)
check("per-run 100000 is clamped to 40000",
      b.build_alias_params({"face_num": 100000}).get("input_face_num") == 40000)
check("per-run 12000 stays 12000",
      b.build_alias_params({"face_num": 12000}).get("input_face_num") == 12000)
b_free = backend("Trellis2-Object-Low", rig="none", face_num="20000",
                 declared=FULL)
check("no cap configured -> no clamp",
      b_free.build_alias_params({"face_num": 100000}).get("input_face_num")
      == 100000)

# --- (e) result splitting -------------------------------------------------
print("\n(e) result splitting (§ 2 + § 3.1)")


def f(name: str, mime: str, kind: str) -> dict:
    return {"name": name, "mime": mime, "kind": kind, "blob": name.encode()}


# -Generic: FBX (token _articulationxl) + basecolor .png + metallic .jpg
generic = [f("Wolf_articulationxl_00001_.fbx", "model/fbx", "model"),
           f("Wolf_basecolor_00001_.png", "image/png", "image"),
           f("Wolf_metallic_00001_.jpg", "image/jpeg", "image")]
model, tex, stages = _split_mesh_files(generic, "generic")
check("generic: the FBX is the model",
      model is not None and model["name"].endswith(".fbx"), str(model))
check("generic: the *_basecolor* image is the texture",
      tex is not None and "_basecolor" in tex["name"], str(tex))
check("generic: *_metallic* is dropped",
      tex is not None and "_metallic" not in tex["name"])
check("generic: the basecolor keeps ITS delivered extension (.png)",
      _mesh_file_suffix(tex) == ".png", _mesh_file_suffix(tex))
check("per-file re-encode: the metallic map of the SAME job is .jpg",
      _mesh_file_suffix(generic[2]) == ".jpg")
check("model extension from the delivered name (.fbx)",
      _mesh_file_suffix(model) == ".fbx")

# -Humanoid: ONE glb (texture embedded) + an optional metallic map
humanoid = [f("Held.glb", "model/gltf-binary", "model"),
            f("Held_metallic_00001_.png", "image/png", "image")]
model, tex, stages = _split_mesh_files(humanoid, "mixamo")
check("mixamo: the GLB is the model", model["name"] == "Held.glb")
check("mixamo: no texture is stored (embedded)", tex is None, str(tex))
check("mixamo: .glb extension from the delivered name",
      _mesh_file_suffix(model) == ".glb")

# -Object (rig none): same rule, and the maps are dropped too
obj = [f("Fass.glb", "model/gltf-binary", "model"),
       f("Fass_basecolor_00001_.jpg", "image/jpeg", "image"),
       f("Fass_metallic_00001_.jpg", "image/jpeg", "image")]
model, tex, stages = _split_mesh_files(obj, "none")
check("none: only the GLB is stored",
      model["name"] == "Fass.glb" and tex is None)

# Order must not matter — assignment is by token, not by position (§ 2 rule 1)
shuffled = [generic[2], generic[1], generic[0]]
model, tex, stages = _split_mesh_files(shuffled, "generic")
check("generic: reversed delivery order changes nothing",
      model["name"].endswith(".fbx") and "_basecolor" in tex["name"])

# A generic job without its basecolor: the pair is mandatory — the splitter
# reports "no texture", and generate_mesh turns that into a hard error.
model, tex, stages = _split_mesh_files([generic[0], generic[2]], "generic")
check("generic without *_basecolor*: no texture (-> hard error upstream)",
      model is not None and tex is None)
check("no model file at all -> (None, None, [])",
      _split_mesh_files([generic[1]], "generic") == (None, None, []))

# --- (f) mesh-shrink: params + the file-in-request payload (§ 3.4) --------
print("\n(f) mesh-shrink (mesh->mesh): params and the files payload")
SHRINK = ["input_mesh_path", "input_name", "input_face_num",
          "input_texture_resolution", "input_no_fingers"]
b = backend("mesh-shrink", rig="none", face_num="5000", declared=SHRINK)
p = b.build_alias_params({"mesh_name": "prop_lo", "texture_size": 1024})
check("input_name = the mesh name", p.get("input_name") == "prop_lo", str(p))
check("input_face_num = the alias default 5000", p.get("input_face_num") == 5000)
check("input_texture_resolution = 1024",
      p.get("input_texture_resolution") == 1024)
check("input_no_fingers passed through (declared, without effect)",
      p.get("input_no_fingers") is True)
check("NO input_remove_background (not declared — an image step)",
      "input_remove_background" not in p, str(sorted(p)))
check("input_mesh_path is NOT a param (it travels in files)",
      "input_mesh_path" not in p, str(sorted(p)))
check("per-run face count overrides the default",
      b.build_alias_params({"face_num": 2000}).get("input_face_num") == 2000)

with tempfile.TemporaryDirectory() as tmp:
    mesh = Path(tmp) / "model_1754000000.glb"
    mesh.write_bytes(b"glTF\x02\x00\x00\x00" + b"\x00" * 120)
    files = b.build_input_files({"source_model_path": str(mesh)})
    check("exactly one files entry, keyed input_mesh_path",
          list(files) == ["input_mesh_path"], str(list(files)))
    val = files["input_mesh_path"]
    check("value is a data-URI with the GLB mime",
          val.startswith("data:model/gltf-binary;base64,"), val[:40])
    import base64 as _b64
    check("the payload decodes back to the file bytes",
          _b64.b64decode(val.split(",", 1)[1]) == mesh.read_bytes())
    # An img2mesh run carries no source mesh — nothing must be built for it.
    check("no source mesh -> no files block (img2mesh stays image-only)",
          b.build_input_files({"source_image_path": "/x.png"}) == {})
    # An http(s) URL is passed through: the gateway fetches it itself (§ 3.4).
    check("an http URL goes out unchanged",
          b.build_input_files({"source_model_path": "http://h/m.glb"})
          == {"input_mesh_path": "http://h/m.glb"})
    missing = str(Path(tmp) / "nope.glb")
    try:
        b.build_input_files({"source_model_path": missing})
        check("a missing source mesh raises", False, "no exception")
    except FileNotFoundError:
        check("a missing source mesh raises FileNotFoundError", True)

    # § 1: over 64 MB the gateway answers 413 — refuse before uploading. The
    # sparse file costs no disk space but reports the real size.
    big = Path(tmp) / "model_1754000001.glb"
    with open(big, "wb") as fh:
        fh.truncate(MESH_UPLOAD_MAX_BYTES + 1)
    check("the limit is 64 MB", MESH_UPLOAD_MAX_BYTES == 64 * 1024 * 1024,
          str(MESH_UPLOAD_MAX_BYTES))
    try:
        b.build_input_files({"source_model_path": str(big)})
        check("64 MB + 1 byte is refused", False, "no exception")
    except ValueError as e:
        check("64 MB + 1 byte is refused before submitting",
              "413" in str(e), str(e))
    # Exactly at the limit it must still go out.
    ok_size = Path(tmp) / "model_1754000002.glb"
    with open(ok_size, "wb") as fh:
        fh.truncate(MESH_UPLOAD_MAX_BYTES)
    check("exactly 64 MB still goes out",
          "input_mesh_path" in b.build_input_files(
              {"source_model_path": str(ok_size)}))

# § 3.4 delivery: GLB + two PNG maps, the GLB reported as kind "file".
shrink_result = [f("prop_lo_00001_.glb", "model/gltf-binary", "file"),
                 f("prop_lo_basecolor_00001_.png", "image/png", "image"),
                 f("prop_lo_metallic_00001_.png", "image/png", "image")]
model, tex, stages = _split_mesh_files(shrink_result, "none")
check("shrink: the kind-'file' GLB is recognised as the model",
      model is not None and model["name"].endswith(".glb"), str(model))
check("shrink: both maps are dropped (texture is embedded)", tex is None)
check("shrink: a reduction has no LOD stages of its own", stages == [], str(stages))
check("shrink: .glb extension from the delivered name",
      _mesh_file_suffix(model) == ".glb")
check("shrink: the maps stay PNG here (no JPEG re-encode)",
      _mesh_file_suffix(shrink_result[1]) == ".png"
      and _mesh_file_suffix(shrink_result[2]) == ".png")

# --- (g) capability probe on the two GLB shapes (§ 3.3) -------------------
print("\n(g) capability probe: textured mesh vs. vertex-coloured mesh")


def glb(gltf: dict, *, fake_bin_len: int = 0) -> bytes:
    """A minimal GLB: 12-byte header + JSON chunk, optionally followed by the
    HEADER of a BIN chunk that claims a length the file does not have. Anything
    that tries to read the binary payload trips over that; the probe must not."""
    body = json.dumps(gltf).encode("utf-8")
    body += b" " * ((4 - len(body) % 4) % 4)
    chunk = struct.pack("<II", len(body), 0x4E4F534A) + body
    tail = struct.pack("<II", fake_bin_len, 0x004E4942) if fake_bin_len else b""
    return (struct.pack("<III", 0x46546C67, 2, 12 + len(chunk) + len(tail))
            + chunk + tail)


# The two shapes as measured on stored files: Trellis2 = images 2 + TEXCOORD_0,
# Triposplat = images 0 + COLOR_0 + KHR_materials_unlit.
TEXTURED = {
    "asset": {"version": "2.0"},
    "images": [{"mimeType": "image/png", "bufferView": 0},
               {"mimeType": "image/png", "bufferView": 1}],
    "meshes": [{"primitives": [{"attributes": {"NORMAL": 0, "POSITION": 1,
                                               "TEXCOORD_0": 2}}]}],
}
VERTEX_COLOURED = {
    "asset": {"version": "2.0"},
    "extensionsUsed": ["KHR_materials_unlit"],
    "meshes": [{"primitives": [{"attributes": {"COLOR_0": 0, "POSITION": 1}}]}],
}
# A mesh with UVs but no image at all — neither of the two field shapes, but
# the reduction has nothing to bake either. The rule is the FILE's content.
UV_NO_TEXTURE = {
    "asset": {"version": "2.0"},
    "meshes": [{"primitives": [{"attributes": {"POSITION": 0,
                                               "TEXCOORD_0": 1}}]}],
}

with tempfile.TemporaryDirectory() as tmp:
    # ~4 GB of BIN the file does not contain (the chunk length is a uint32, so
    # this is nearly its maximum): reading it is impossible, and a successful
    # probe therefore proves it stopped after the JSON chunk.
    FAKE_BIN = 0xFFFFFFF0
    tex_p = Path(tmp) / "textured.glb"
    vc_p = Path(tmp) / "vertex_coloured.glb"
    uv_p = Path(tmp) / "uv_only.glb"
    tex_p.write_bytes(glb(TEXTURED, fake_bin_len=FAKE_BIN))
    vc_p.write_bytes(glb(VERTEX_COLOURED, fake_bin_len=FAKE_BIN))
    uv_p.write_bytes(glb(UV_NO_TEXTURE))
    check("the test files are far smaller than the BIN length they declare",
          tex_p.stat().st_size < 1024 and vc_p.stat().st_size < 1024,
          f"{tex_p.stat().st_size} / {vc_p.stat().st_size} bytes")

    caps = glb_capabilities_at(tex_p)
    check("textured: 2 images", caps["images"] == 2, str(caps))
    check("textured: TEXCOORD_0 found", caps["uv"] is True)
    check("textured: no vertex colours", caps["vertex_colors"] is False)
    check("textured: not unlit", caps["unlit"] is False)

    caps = glb_capabilities_at(vc_p)
    check("vertex-coloured: 0 images", caps["images"] == 0, str(caps))
    check("vertex-coloured: no UVs", caps["uv"] is False)
    check("vertex-coloured: COLOR_0 found", caps["vertex_colors"] is True)
    check("vertex-coloured: KHR_materials_unlit reported", caps["unlit"] is True)

    # --- (h) the shrinkable decision + its reason -------------------------
    print("\n(h) shrinkable decision (§ 3.4: UVs AND a texture are required)")
    d = shrink_capability(tex_p)
    check("textured mesh is shrinkable", d["shrinkable"] is True and not d["reason"],
          str(d["reason"]))
    d = shrink_capability(vc_p)
    check("vertex-coloured mesh is NOT shrinkable", d["shrinkable"] is False)
    check("the reason names the vertex colours and the missing UVs",
          "vertex-coloured" in d["reason"] and "UV" in d["reason"], d["reason"])
    d = shrink_capability(uv_p)
    check("UVs but no texture image -> not shrinkable either",
          d["shrinkable"] is False, str(d))
    check("that reason names the missing texture", "texture" in d["reason"],
          d["reason"])
    # Only a POSITIVE finding blocks: something we cannot read keeps its action
    # (an FBX, a future container — the gateway stays the authority there).
    junk = Path(tmp) / "not_a_glb.glb"
    junk.write_bytes(b"Kaydara FBX Binary  \x00" + b"\x00" * 64)
    d = shrink_capability(junk)
    check("an unreadable file is NOT blocked", d["shrinkable"] is True
          and d["reason"] == "", str(d))

# --- (i) the terminal job error is an INPUT problem -----------------------
print("\n(i) terminal job error: input, not backend defect")
REAL = ("node 21 Trellis2RenderMultiViewNvdiffrast: expected np.ndarray "
        "(got NoneType)")
check("the real gateway message is recognised",
      bool(_TERMINAL_JOB_ERROR.search(REAL)))
check("a different node number/name still matches (only the meaningful part)",
      bool(_TERMINAL_JOB_ERROR.search(
          "node 7 SomeOtherBake: expected np.ndarray (got NoneType)")))
for other in ("no basecolor PNG delivered",
              "embedded texture is a 2x2 dummy",
              "CUDA out of memory"):
    check(f"unrelated failure not misread: {other!r}",
          not _TERMINAL_JOB_ERROR.search(other))


class _StubBackend:
    """Just enough backend for the pool's runner: a name, a cost and a
    recording ``mark_unhealthy`` (the cooldown we are asserting about)."""

    def __init__(self) -> None:
        self.name = "mesh-shrink"
        self.cost = 0
        self.cooldowns: list = []

    def mark_unhealthy(self, reason: str, seconds: float) -> None:
        self.cooldowns.append((reason, seconds))


pool = BackendPool([], lambda _n: {})


def _run(exc):
    b = _StubBackend()
    def _op(_backend):
        raise exc
    try:
        pool.run_on_backend(b, _op)
    except Exception as e:      # noqa: BLE001 - the raise is what we assert on
        return b, e
    return b, None


b_stub, err = _run(GatewayRejectedError("mesh-shrink: the input mesh has no "
                                        "UVs/texture …"))
check("a rejected input is re-raised", isinstance(err, GatewayRejectedError))
check("a rejected input does NOT put the backend on cooldown",
      b_stub.cooldowns == [], str(b_stub.cooldowns))
b_stub, err = _run(RuntimeError("connection refused"))
check("a real defect still cools the backend down",
      len(b_stub.cooldowns) == 1, str(b_stub.cooldowns))
b_stub, err = _run(BackendBusyError("timeout"))
check("busy stays busy (no cooldown, re-raised)",
      isinstance(err, BackendBusyError) and b_stub.cooldowns == [])

# --- (j) input-hash guard --------------------------------------------------
print("\n(j) input sha256 guard (gateway input_images[])")
b = backend("mesh-shrink", rig="none", face_num="5000",
            declared=["input_mesh_path", "input_name", "input_face_num"])
with tempfile.TemporaryDirectory() as tmp:
    mesh = Path(tmp) / "model_1754000003.glb"
    mesh.write_bytes(b"glTF\x02\x00\x00\x00" + b"\x01" * 120)
    b.build_input_files({"source_model_path": str(mesh)})
    ours = hashlib.sha256(mesh.read_bytes()).hexdigest()
    check("the uploaded bytes are hashed",
          getattr(b._tls, "input_sha256", "") == ours,
          getattr(b._tls, "input_sha256", "")[:12])

    def guard(view: dict):
        try:
            b._check_input_identity(view, "job-1")
            return None
        except GatewayInputMismatchError as e:
            return e

    check("old gateway (no input list) -> no check",
          guard({"status": "done", "results": []}) is None)
    check("our own hash reported -> passes",
          guard({"input_images": [{"sha256": ours}]}) is None)
    check("a list without any sha256 -> nothing to compare, no complaint",
          guard({"input_images": [{"name": "upload.glb"}]}) is None)
    mism = guard({"input_images": [{"sha256": "d" * 64}]})
    check("a FOREIGN hash fails the job", isinstance(mism, GatewayInputMismatchError))
    check("the message says the gateway ran a different input",
          "DIFFERENT input" in str(mism), str(mism)[:90])
    # An http(s) URL is fetched by the gateway — we hold no bytes, so there is
    # nothing to compare and nothing to warn about.
    b._tls.input_sha256 = ""
    check("no local bytes (URL input) -> no check",
          guard({"input_images": [{"sha256": "d" * 64}]}) is None)

# --- (k) LOD stages of ONE job (§ 3.2) ------------------------------------
print("\n(k) LOD stages: params, name-based splitting, unique input_name")

# The Hunyuan3D-Object schema — the ONLY family that declares the stage param
# today. Which alias that is comes from the schema, never from its name.
HUNYUAN_OBJECT = ["input_name", "input_remove_background", "input_face_num",
                  "input_texture_resolution", "input_no_fingers",
                  LOD_FACES_PARAM]
b = backend("Hunyuan3D-Object", rig="none", face_num="40000",
            face_num_max="40000", declared=HUNYUAN_OBJECT)
p = b.build_alias_params({"mesh_name": "chair-rab12cd", "lod_faces": 5000})
check("input_lod_faces goes out as a STRING (contract type)",
      p.get(LOD_FACES_PARAM) == "5000", repr(p.get(LOD_FACES_PARAM)))
check("the alias is reported as LOD-capable", b.supports_lod_stages is True)
p = b.build_alias_params({"mesh_name": "chair", "lod_faces": [8000, 4000, 2000]})
check("several stages become ONE comma list, order kept",
      p.get(LOD_FACES_PARAM) == "8000,4000,2000", repr(p.get(LOD_FACES_PARAM)))
check("no stage requested -> the param is absent (alias default stands)",
      LOD_FACES_PARAM not in b.build_alias_params({"mesh_name": "chair"}))
check("a comma string is accepted as-is",
      normalize_lod_faces(" 8000, 4000 ") == [8000, 4000])
check("junk and duplicates are dropped",
      normalize_lod_faces("2000,2000,x,-5,0") == [2000], str(normalize_lod_faces("2000,2000,x,-5,0")))

# An alias whose schema does NOT declare the param must never be asked for
# stages — it would silently ignore them and we would wait for files that
# never come.
b_plain = backend("Trellis2-Object-Low", rig="none", face_num="20000",
                  declared=FULL)
check("an alias without the param never receives it",
      LOD_FACES_PARAM not in b_plain.build_alias_params(
          {"mesh_name": "chair", "lod_faces": 5000}))
check("and it is NOT offered as LOD-capable",
      b_plain.supports_lod_stages is False)
# § 1: with an UNREADABLE schema the input_* names go out blind (the gateway
# ignores unknown ones) — but a backend whose capability is unknown is never
# ADVERTISED as capable, or the admin gets a control that reaches nothing.
b_blind = backend("Hunyuan3D-Object", rig="none", declared=None)
check("unreadable schema: the param may go out blind",
      b_blind.build_alias_params({"mesh_name": "c", "lod_faces": 5000})
      .get(LOD_FACES_PARAM) == "5000")
check("unreadable schema: the alias is NOT advertised as LOD-capable",
      b_blind.supports_lod_stages is False)


def glb_file(name: str) -> dict:
    """One delivered mesh — § 1: every mesh is reported as kind 'file'."""
    return f(name, "model/gltf-binary", "file")


# A realistic Hunyuan3D-Object delivery for "8000,4000,2000": the main result
# plus one self-contained GLB per stage, plus the two maps. § 3.2: the response
# is sorted ALPHABETICALLY by file name, never by the requested order.
NAME = "chair_9f21-rab12cd"
delivery = sorted(
    [glb_file(f"{NAME}_00001_.glb"), glb_file(f"{NAME}_2000.glb"),
     glb_file(f"{NAME}_4000.glb"), glb_file(f"{NAME}_8000.glb"),
     f(f"{NAME}_basecolor_00001_.png", "image/png", "image"),
     f(f"{NAME}_metallic_00001_.png", "image/png", "image")],
    key=lambda x: x["name"])
model, tex, stages = _split_mesh_files(delivery, "none")
check("the _00001_ file is the main mesh",
      model is not None and model["name"] == f"{NAME}_00001_.glb", str(model))
check("all three stages are returned",
      [s["lod_faces"] for s in stages] == [2000, 4000, 8000],
      str([s["lod_faces"] for s in stages]))
check("the stages are the _<digits> files",
      [s["name"] for s in stages]
      == [f"{NAME}_2000.glb", f"{NAME}_4000.glb", f"{NAME}_8000.glb"])
check("the maps are still dropped (texture embedded)", tex is None)
check("the main mesh is never among the stages",
      all(s["name"] != model["name"] for s in stages))
# Alphabetically the main happens to sort FIRST here ('0' < any stage digit),
# so this order alone would not catch a positional pick. The delivery order is
# not ours to rely on though (§ 2 rule 1) — reversed, position picks _8000.
rev = list(reversed(delivery))
model_r, _t, stages_r = _split_mesh_files(rev, "none")
check("reversed delivery: still the _00001_ file (position would pick _8000)",
      model_r["name"] == f"{NAME}_00001_.glb"
      and [x for x in rev if x["name"].endswith(".glb")][0]["name"]
      == f"{NAME}_8000.glb", model_r["name"])
check("reversed delivery: the stages are the same three, still smallest first",
      [s["lod_faces"] for s in stages_r] == [2000, 4000, 8000])

check("the requested value is read off the file NAME",
      mesh_lod_stage_faces({"name": f"{NAME}_2000.glb"}) == 2000)
check("the main token is not a stage (trailing underscore)",
      mesh_lod_stage_faces({"name": f"{NAME}_00001_.glb"}) == 0)
check("a name without a trailing number is not a stage",
      mesh_lod_stage_faces({"name": "building.glb"}) == 0)

# Single model, no counter at all: nothing to distinguish -> that IS the mesh.
only = [glb_file("building.glb")]
model, tex, stages = _split_mesh_files(only, "none")
check("a single delivered model is the main mesh (no name matches)",
      model["name"] == "building.glb" and stages == [])
# A delivery that is nothing BUT a stage: it is promoted to the main mesh and
# must not be stored a second time as its own low variant.
model, tex, stages = _split_mesh_files([glb_file(f"{NAME}_2000.glb")], "none")
check("a lone stage becomes the mesh and is not also listed as a stage",
      model["name"] == f"{NAME}_2000.glb" and stages == [], str(stages))

# Rigged deliveries: a reduced stage would carry no rig, so it is IGNORED
# rather than stored (§ 3.1 pairs stay untouched).
rigged_generic = [f(f"{NAME}_articulationxl.fbx", "model/fbx", "file"),
                  glb_file(f"{NAME}_2000.glb"),
                  f(f"{NAME}_basecolor_00001_.png", "image/png", "image")]
model, tex, stages = _split_mesh_files(rigged_generic, "generic")
check("generic: the FBX stays the model, a stage is ignored",
      model["name"].endswith(".fbx") and stages == [], str(stages))
check("generic: the basecolor pair is unchanged",
      tex is not None and "_basecolor" in tex["name"])
rigged_mixamo = [glb_file(f"{NAME}_2000.glb"),
                 glb_file("gwchain_7c1_mia_rigged.glb")]
model, tex, stages = _split_mesh_files(rigged_mixamo, "mixamo")
check("mixamo: the *_rigged GLB wins over a stage-looking file",
      model["name"] == "gwchain_7c1_mia_rigged.glb" and stages == [], str(model))

# § 3.2: input_name must be UNIQUE per job — else a later run with fewer
# stages gets the older ones handed out with its result.
n1, n2 = _unique_mesh_name("chair_9f21"), _unique_mesh_name("chair_9f21")
check("the same subject yields two DIFFERENT job names", n1 != n2, f"{n1} / {n2}")
check("the bare subject id is never reused as the job name", n1 != "chair_9f21")
check("the subject stays the prefix (attributable in the job view)",
      n1.startswith("chair_9f21"), n1)
# A job name ending in _<digits> would make the MAIN result read as a stage of
# itself — the run token starts with a letter for exactly that reason.
check("a subject id ending in digits still yields a non-stage job name",
      mesh_lod_stage_faces({"name": _unique_mesh_name("prop_2000") + ".glb"}) == 0,
      _unique_mesh_name("prop_2000"))


print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
    sys.exit(1)
print("all mesh-gateway checks passed")
