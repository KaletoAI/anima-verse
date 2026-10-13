#!/usr/bin/env python3
"""Smoke run for the multi-view mesh input: view detection + slot mapping.

No server or gateway: pure mappings plus payload/service checks with mocked
submission and temporary storage for character sidecar checks.

What is being checked, derived by hand from the agreed design (not from what
the code currently prints):

  1. A multi-view ComfyUI workflow declares FOUR image slots in the alias
     schema: ``input_image_front``, ``input_image_back``, ``input_image_left``,
     ``input_image_right``. A classic alias declares exactly one:
     ``input_image``.
  2. The view a slot asks for is read from the TOKEN in its name, checked in
     the order back → left → right; nothing matching means front. So
     ``input_image_back`` is back, ``INPUT_IMAGE_RIGHT`` is right (the check is
     case-insensitive), and the classic ``input_image`` — carrying no token at
     all — is the FRONT view. That is what lets one rule serve both the alias'
     slot names and our own reference keys.
  3. Our side hands the run its images as ``params["reference_images"]``, keyed
     by view. The legacy key ``input_image`` therefore lands on front by rule
     2, so an old-style params dict needs no special case.
     ``params["source_image_path"]`` is the front view too, but only fills in
     when the refs carry no front of their own — an explicit front ref wins.
  4. Slot mapping keeps only slots we actually hold an image for: with front
     and back rendered, a four-slot alias is sent TWO images (front + back),
     left and right are simply absent from the request. A single-slot alias is
     sent the front view alone, no matter how many views exist — the alias
     decides how many images it can take, never the caller.
  5. An empty slot list (schema unreadable) falls back to the classic single
     slot ``input_image`` → the front view.
  6. Two slots of the SAME view would upload one image twice; the first slot
     of a view wins and the later one is dropped.

Expected results, worked out by hand from those rules:

  (a) slots = [front, back, left, right], views = {front: f.png, back: b.png}
      -> {"input_image_front": "f.png", "input_image_back": "b.png"}
  (b) slots = ["input_image"], all four views held
      -> {"input_image": "f.png"}                       (front only)
  (c) slots = [], views = {front: f.png}
      -> {"input_image": "f.png"}                       (fallback slot)
  (d) reference_images = {"input_image": "x.png"}
      -> {"front": "x.png"}                             (legacy key)
  (e) reference_images = {front: f.png, back: b.png} + source_image_path s.png
      -> {"front": "f.png", "back": "b.png"}            (refs beat the source)
  (f) _slot_view: input_image_back -> back, INPUT_IMAGE_RIGHT -> right,
      input_image -> front
  (g) slots = ["input_image_front", "input_image"] , views = {front: f.png}
      -> {"input_image_front": "f.png"}                 (first slot per view)

Usage:  ./.venv/bin/python scripts/smoke_mesh_multiview.py

P2 expectations derived from spec §4.4: with four slots an animal sends
head-on as front, main as left, plus back/right. Without head-on, main fills
both front and left. One slot sends main only and records single_view=True.
Humanoids keep main as front plus back/left/right; single_view is absent.
"""
import sys
import threading
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.imagegen.backends.openai_mesh import OpenAIMeshBackend  # noqa: E402

FAILURES = []

# The slot names of the real multi-view workflow, in declaration order.
MV_SLOTS = ["input_image_front", "input_image_back",
            "input_image_left", "input_image_right"]


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}"
          f"{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


# --- (a) multi-view alias, only two views rendered --------------------------
print("\n(a) four declared slots, front+back held")
got = OpenAIMeshBackend.select_slot_images(
    MV_SLOTS, {"front": "f.png", "back": "b.png"})
check("front and back are slotted by name",
      got == {"input_image_front": "f.png", "input_image_back": "b.png"},
      str(got))
check("left/right are left out entirely (no empty slots)",
      "input_image_left" not in got and "input_image_right" not in got,
      str(sorted(got)))

# --- (b) classic single-slot alias ------------------------------------------
print("\n(b) one declared slot, all four views held")
got = OpenAIMeshBackend.select_slot_images(
    ["input_image"],
    {"front": "f.png", "back": "b.png", "left": "l.png", "right": "r.png"})
check("the single slot gets the FRONT view only",
      got == {"input_image": "f.png"}, str(got))

# --- (c) unreadable schema --------------------------------------------------
print("\n(c) no declared slots (schema unreadable)")
got = OpenAIMeshBackend.select_slot_images([], {"front": "f.png",
                                                "back": "b.png"})
check("falls back to the classic slot with the front view",
      got == {"input_image": "f.png"}, str(got))

# --- (d) legacy reference key ------------------------------------------------
print("\n(d) legacy params: reference_images = {'input_image': ...}")
got = OpenAIMeshBackend._input_images(
    {"reference_images": {"input_image": "x.png"}})
check("the tokenless legacy key is the front view",
      got == {"front": "x.png"}, str(got))

# --- (e) view-keyed refs beside a source path -------------------------------
print("\n(e) view-keyed refs plus source_image_path")
got = OpenAIMeshBackend._input_images(
    {"reference_images": {"front": "f.png", "back": "b.png"},
     "source_image_path": "s.png"})
check("the explicit front ref wins over source_image_path",
      got.get("front") == "f.png", str(got))
check("the back view is carried through", got.get("back") == "b.png", str(got))
check("no extra views are invented", set(got) == {"front", "back"},
      str(sorted(got)))
got = OpenAIMeshBackend._input_images({"source_image_path": "s.png"})
check("without any ref the source path IS the front view",
      got == {"front": "s.png"}, str(got))

# --- (f) the token rule itself ----------------------------------------------
print("\n(f) slot name -> view")
check("input_image_back -> back",
      OpenAIMeshBackend._slot_view("input_image_back") == "back")
check("INPUT_IMAGE_RIGHT -> right (case-insensitive)",
      OpenAIMeshBackend._slot_view("INPUT_IMAGE_RIGHT") == "right")
check("input_image -> front (no token = front)",
      OpenAIMeshBackend._slot_view("input_image") == "front")
check("input_image_front -> front",
      OpenAIMeshBackend._slot_view("input_image_front") == "front")
check("input_image_left -> left",
      OpenAIMeshBackend._slot_view("input_image_left") == "left")

# --- (g) two slots of the same view -----------------------------------------
print("\n(g) two slots asking for the same view")
got = OpenAIMeshBackend.select_slot_images(
    ["input_image_front", "input_image"], {"front": "f.png"})
check("the first slot of a view wins, the image is not uploaded twice",
      got == {"input_image_front": "f.png"}, str(got))


print("\n(h) body-dependent mapping for the chosen alias")
mapper = getattr(OpenAIMeshBackend, "mesh_slot_views", None)
check("public mesh_slot_views exists", callable(mapper))
if callable(mapper):
    for label, body, views, slots, expected in (
        ("animal four slots", "animal", {"front": "h.png", "back": "b.png", "right": "r.png"}, MV_SLOTS,
         {"input_image_front": "h.png", "input_image_back": "b.png", "input_image_left": "m.png", "input_image_right": "r.png"}),
        ("animal without head-on", "animal", {"back": "b.png", "right": "r.png"}, MV_SLOTS,
         {"input_image_front": "m.png", "input_image_back": "b.png", "input_image_left": "m.png", "input_image_right": "r.png"}),
        ("animal single slot", "animal", {"front": "h.png", "back": "b.png"}, ["input_image"], {"input_image": "m.png"}),
        ("animal unreadable schema", "animal", {"front": "h.png"}, [], {"input_image": "m.png"}),
        ("humanoid unchanged", "humanoid", {"back": "b.png", "left": "l.png", "right": "r.png"}, MV_SLOTS,
         {"input_image_front": "m.png", "input_image_back": "b.png", "input_image_left": "l.png", "input_image_right": "r.png"}),
    ):
        before = dict(views)
        got = OpenAIMeshBackend.select_slot_images(slots, mapper(body, "m.png", views, slots))
        check(label, got == expected, str(got))
        check(label + " leaves raw views intact", views == before)

# Check the real payload builder without a gateway submission.
backend = object.__new__(OpenAIMeshBackend)
backend._tls = threading.local()
backend._face_schema = (False, (), "", frozenset())
backend.category = "img2mesh"
backend.name = backend.model = "smoke"
backend.api_url = "https://unused.invalid"
backend.mesh_endpoint = "/meshes"
main = "https://unused.invalid/main.png"
head = "https://unused.invalid/head.png"
for body, slots, expected, single in (
    ("animal", ["input_image"], {"input_image": main}, True),
    ("animal", MV_SLOTS, {"input_image_front": head, "input_image_left": main}, False),
    ("humanoid", ["input_image"], {"input_image": main}, False),
):
    backend._image_slots = slots
    with patch.object(backend, "build_alias_params", return_value={}), \
            patch("app.imagegen.backends.openai_mesh.submit_job", return_value="") as submit:
        backend._generate("", "", {"source_image_path": main, "view_body": body,
                                   "reference_images": {"front": head} if body == "animal" else {}})
    check(body + " payload " + str(len(slots)), submit.call_args.args[2]["images"] == expected)
    check(body + " single_view " + str(len(slots)), getattr(backend, "last_single_view", None) is single)

# Refs-only humanoid calls must retain the front without a source path.
backend._image_slots = MV_SLOTS
back = "https://unused.invalid/back.png"
with patch.object(backend, "build_alias_params", return_value={}), \
        patch("app.imagegen.backends.openai_mesh.submit_job", return_value="") as submit:
    backend._generate("", "", {"view_body": "humanoid",
                               "reference_images": {"front": main, "back": back}})
images = submit.call_args.args[2]["images"] if submit.call_args else None
check("humanoid refs-only payload retains front and back",
      images == {
          "input_image_front": main, "input_image_back": back},
      str(images))

# The service must copy worker-local metadata before leaving the channel.
from app.imagegen.service import ImageService

service = object.__new__(ImageService)
service._pool = object()
raw = {"front": "h.png", "back": "b.png", "right": "r.png"}
for body, single in (("animal", True), ("animal", False), ("humanoid", False)):
    backend._tls.single_view = single
    backend._tls.result_files = [{"name": "mesh.glb", "mime": "model/gltf-binary"}]
    with patch.object(backend, "generate", return_value=[b"mesh"]) as generate, \
            patch.object(service, "run_on_backend_channel", create=True,
                         side_effect=lambda bb, op, **kw: op()) as channel, \
            patch.object(service, "run_on_backend", create=True,
                         side_effect=lambda bb, op, **kw: (op(bb), bb)), \
            patch("app.imagegen.routing.run_routed",
                  side_effect=lambda occasion, render, **kw: (render(backend), None)), \
            patch.object(service, "_store_mesh_files", return_value={"ok": True, "path": "unused.glb"}):
        result = service.generate_mesh("m.png", "unused.glb", view_images=raw, view_body=body)
    check(body + " raw views reach chosen backend", generate.call_args.args[2]["reference_images"] == raw)
    check(body + " main and body reach chosen backend",
          generate.call_args.args[2]["source_image_path"] == "m.png"
          and generate.call_args.args[2]["view_body"] == body)
    check("generation uses backend channel", channel.call_count == 1)
    check(body + " result flag " + str(single),
          result.get("single_view") is True if single else "single_view" not in result)

# Initialise isolated storage before importing character model modules.
from app.core import paths
import json

with tempfile.TemporaryDirectory(prefix="smoke-mesh-multiview-") as tmp:
    paths.init(tmp)
    from app.core import model3d

    directory = Path(tmp) / "models"
    directory.mkdir()
    source = Path(tmp) / "source.glb"
    source.write_bytes(b"mesh")
    for single in (True, False):
        result = {"path": str(source), "backend": "smoke"}
        if single:
            result["single_view"] = True
        with patch.object(model3d, "get_model3d_dir", return_value=directory), \
                patch.object(model3d, "_purge_combination"), \
                patch("app.core.mesh_source.validate_source", return_value={"ok": True}):
            stored = model3d._store_unrigged_model("smoke", "signature", result, "mixamo", {})
        for relative in ("signature.json", "unrigged/signature.json"):
            meta = json.loads((directory / relative).read_text())
            check(relative + " single_view " + str(single),
                  meta.get("single_view") is True if single else "single_view" not in meta)

        # Re-rig the retained source through the real publication path. Only
        # the rig service, validation and optional processing are stubbed.
        def generate_rig(*, mesh_path, output_path, **kwargs):
            check("re-rig consumes retained source",
                  Path(mesh_path) == directory / "unrigged/signature.glb")
            Path(output_path).write_bytes(b"rigged mesh")
            return {"ok": True, "path": output_path, "backend": "smoke-rigger"}

        with patch.object(model3d, "get_model3d_dir", return_value=directory), \
                patch.object(model3d, "find_model3d", return_value=directory / "signature.glb"), \
                patch.object(model3d, "required_rig", return_value="mixamo"), \
                patch("app.imagegen.service.get_image_service", return_value=service), \
                patch.object(service, "generate_rig", side_effect=generate_rig), \
                patch("app.core.model_validate.validate_glb", return_value={"ok": True}), \
                patch.object(model3d, "_auto_retexture"), \
                patch.object(model3d, "_auto_normalize"), \
                patch.object(model3d, "_auto_extension_rig", return_value={"ok": True}), \
                patch.object(model3d, "_attach_measurement"), \
                patch.object(model3d, "request_lod", return_value=False):
            rerigged = model3d._rig_from_source(
                "smoke", "signature", directory / "unrigged/signature.glb")
        check("re-rig succeeds " + str(single), rerigged.get("ok") is True, str(rerigged))
        meta = json.loads((directory / "signature.json").read_text())
        check("re-rig published single_view " + str(single),
              meta.get("single_view") is True if single else "single_view" not in meta)

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
    sys.exit(1)
print("all mesh-multiview checks passed")
