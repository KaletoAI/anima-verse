#!/usr/bin/env python3
"""Edit-prompt C25: world images with a reference say what the picture is for (role sentence, sent prompt only).

Usage: ./.venv/bin/python scripts/smoke_world_ref_roles.py

Runs without the server, on a temp storage (paths.init before any world-DB import), with fake backends that capture
what they are sent (the prompt BEFORE the normaliser, so the canonical ``<ref N>``). Design: docs/edit-prompts.md §8
C25. Expected values, derived by hand from the rules:

[A] ``edit_prompt.with_role_sentence(prompt, sentence)`` appends the sentence as the LAST sentence, once:
    A1 "a, b" + "X <ref 1>." -> "a, b. X <ref 1>." (a prompt without a terminator gets ". ")
    A2 "a." + "X." -> "a. X." (no second dot)
    A3 "a. X." + "X." -> unchanged (already its last sentence)
    A4 "" + "X." -> "X."
[B] the three texts, and what the normaliser makes of them with ONE slot (docs §1: picture_edit / picture_subject
    "<Picture 1>", image_tag and ordinal "the image", capitalised at a sentence start):
    B1 view_reference_sentence("object") = "<ref 1> shows the same object from the front: keep its shape,
       proportions, materials and colours."
       Flux2-9B (ordinal): "a, b. The image shows the same object from the front: …"
       P-H3 (picture_edit): "Edit <Picture 1>. a, b. <Picture 1> shows the same object from the front: …"
       Qwen2.1 (image_tag): "a, b. The image shows the same object …"
    B2 TIME_VARIANT_KEEP on P-H3: "… and the camera angle of <Picture 1> exactly as they are; change only the time
       of day and the light."; on Qwen2.1 "… of the image exactly as they are …"
    B3 EVENT_PLACE_SENTENCE on Flux2-9B: "a, b. It happens in the place shown in the image: keep its layout and
       architecture."
    B4 no slot sent: the role sentence is dropped whole (docs §3 step 4 — another sentence remains), "a, b." stays.
    B5 ``world_ops._view_noun``: building_back -> "building", building_outdoor_side -> "outdoor scene",
       room_model_back -> "set piece", room_model_outdoor_back -> "open-air area", location -> "subject".
[C] event image (``event_images._do_generate``), the location background as reference:
    C1 a 1-slot backend: sent = the composed prompt + ". " + EVENT_PLACE_SENTENCE; reference_roles =
       {input_reference_image_1: room "the place"}.
    C2 a 0-slot backend: sent = the composed prompt, no reference_roles.
[D] day/night variant (``world_ops.generate_time_variant_core``, source = slot 1): sent = the composed prompt + ". " +
    TIME_VARIANT_KEEP, reference_roles {1: canvas "the place"}; the STORED gallery prompt (save_gallery_prompt) is the
    composed prompt alone — no sentence, no token.
[E] prop source render (``props._render_source``), routed, front_reference=True:
    E1 view "back" with its own front slotted on a 1-slot backend: sent = stored + ". " +
       view_reference_sentence("object"), roles {1: view_source "the front"}; the stored prompt (save_source_image)
       has no "<ref".
    E2 view "front" from ANOTHER variant's picture (a new version of the object): the picture is slotted, no
       sentence, no reference_roles (that prompt says what changes itself).
    E3 view "back" on a 0-slot backend: nothing slotted, sent == stored.
[F] the main T-pose render slots the profile image only when one exists (and a 0-slot backend sends nothing), so its
    style must survive WITHOUT a slot. The tpose style (both families) therefore stays prose ("of the reference
    image"), like the profile style: no ``<ref``. Docs §3 step 1: no slot and no token -> byte-identical. With a token
    the no-slot path drops the whole sentence holding it once another remains, and the style, the A-pose clause and
    the start of the character block are ONE comma sentence — an appearance text with ". " would lose all three.
    F1 no ``<ref`` in tpose natural/keywords nor in profile natural/keywords (clothed and unclothed).
    F2 joined = join_style_prompt(tpose natural style, get_tpose_prompt() + ", Mia, slender, long red hair. She wears
       a blue summer dress and white sneakers, neutral relaxed facial expression"); normalise with NO slot on Qwen2.1
       and Flux2-9B returns ``joined`` unchanged, and it holds "A-pose" and "both feet entirely inside the frame".
"""
import asyncio
import os
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TEMP = tempfile.TemporaryDirectory(prefix="smoke-world-ref-roles-")
os.environ["STORAGE_DIR"] = TEMP.name
os.environ["INSTANCE_DIR"] = TEMP.name
from app.core import paths  # noqa: E402

paths.init(TEMP.name)
paths.init_instance(TEMP.name)
from app.core import db  # noqa: E402

db.init_schema()
from PIL import Image  # noqa: E402

from app.core import event_images, props, world_ops  # noqa: E402
from app.core.view_prompts import view_reference_sentence  # noqa: E402
from app.imagegen import edit_prompt as ep  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f"\n         expected {want!r}"))
    if not ok:
        FAILS.append(label)


class FakeBackend:
    def __init__(self, name, model, slots):
        self.name, self.model, self.ref_slot_count = name, model, slots
        self.prompt_dialect_setting = ""
        self.image_family = "natural"
        self.api_type = "fake"
        self.calls = []

    def generate(self, prompt, negative, params, log_meta=None, **kw):
        self.calls.append({"prompt": prompt, "negative": negative, "params": dict(params)})
        return [_png()]


def _png() -> bytes:
    import io
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "grey").save(buf, "PNG")
    return buf.getvalue()


class FakeService:
    enabled = True

    def __init__(self, backend):
        self.pool = SimpleNamespace(backends=[backend])

    def run_on_backend_channel(self, b, fn, **kw):
        return fn()

    def run_on_backend(self, b, op, **kw):
        return op(b), b


def routed_to(backend):
    return lambda occasion, render, **kw: (render(backend), None)


FLUX = ("Flux2-9B Normal", "Flux2-9B")
PH3 = ("P-H3-Image", "P-H3-Image")
QWEN = ("Qwen2.1", "Qwen2.1")
ONE = {"reference_images": {"input_reference_image_1": "x.png"}}

# ------------------------------------------------------------------------------------------------ [A]
print("[A] with_role_sentence")
check("A1", ep.with_role_sentence("a, b", "X <ref 1>."), "a, b. X <ref 1>.")
check("A2", ep.with_role_sentence("a.", "X."), "a. X.")
check("A3", ep.with_role_sentence("a. X.", "X."), "a. X.")
check("A4", ep.with_role_sentence("", "X."), "X.")

# ------------------------------------------------------------------------------------------------ [B]
print("[B] texts and dialects")
VIEW = view_reference_sentence("object")
check("B1 text", VIEW, "<ref 1> shows the same object from the front: keep its shape, proportions, materials and "
                       "colours.")
TAIL = "shows the same object from the front: keep its shape, proportions, materials and colours."
check("B1 Flux", ep.normalise(ep.with_role_sentence("a, b", VIEW), ONE, FakeBackend(*FLUX, 1))[0],
      "a, b. The image " + TAIL)
check("B1 P-H3", ep.normalise(ep.with_role_sentence("a, b", VIEW), ONE, FakeBackend(*PH3, 4))[0],
      "Edit <Picture 1>. a, b. <Picture 1> " + TAIL)
check("B1 Qwen", ep.normalise(ep.with_role_sentence("a, b", VIEW), ONE, FakeBackend(*QWEN, 10))[0],
      "a, b. The image " + TAIL)
KEEP = world_ops.TIME_VARIANT_KEEP
check("B2 P-H3", ep.normalise(ep.with_role_sentence("a, b", KEEP), ONE, FakeBackend(*PH3, 4))[0],
      "Edit <Picture 1>. a, b. Keep the layout, every building and object, and the camera angle of <Picture 1> "
      "exactly as they are; change only the time of day and the light.")
check("B2 Qwen", ep.normalise(ep.with_role_sentence("a, b", KEEP), ONE, FakeBackend(*QWEN, 10))[0],
      "a, b. Keep the layout, every building and object, and the camera angle of the image exactly as they are; "
      "change only the time of day and the light.")
check("B3 Flux", ep.normalise(ep.with_role_sentence("a, b", event_images.EVENT_PLACE_SENTENCE), ONE,
                              FakeBackend(*FLUX, 1))[0],
      "a, b. It happens in the place shown in the image: keep its layout and architecture.")
check("B4 no slot", ep.normalise(ep.with_role_sentence("a, b", VIEW), {}, FakeBackend(*FLUX, 1))[0], "a, b.")
check("B5", [world_ops._view_noun(u) for u in ("building_back", "building_outdoor_side", "room_model_back",
                                              "room_model_outdoor_back", "location")],
      ["building", "outdoor scene", "set piece", "open-air area", "subject"])

# ------------------------------------------------------------------------------------------------ [C]
print("[C] event image")
bg = Path(TEMP.name) / "bg.png"
Image.new("RGB", (640, 360), "blue").save(bg)


def run_event(backend):
    with ExitStack() as st:
        st.enter_context(patch("app.models.world.get_background_path", lambda *a, **k: bg))
        st.enter_context(patch("app.models.world.get_location_by_id", lambda *a, **k: {"id": "L1"}))
        st.enter_context(patch("app.models.world.resolve_indoor_flag", lambda *a, **k: "indoor"))
        st.enter_context(patch("app.imagegen.service.get_image_service", lambda: FakeService(backend)))
        st.enter_context(patch("app.imagegen.routing.run_routed", routed_to(backend)))
        st.enter_context(patch("app.imagegen.pose_check.apply", lambda occ, p: (p, False)))
        st.enter_context(patch("app.models.events.update_event_fields", lambda *a, **k: {"ok": True}))
        st.enter_context(patch.object(event_images, "publish_image_ready", lambda *a, **k: None))
        event_images._do_generate("e1", "L1", "a street musician plays the violin", False)
    return backend.calls[-1]


c1 = run_event(FakeBackend(*FLUX, 1))
check("C1 sentence last", c1["prompt"].endswith(". " + event_images.EVENT_PLACE_SENTENCE), True)
check("C1 roles", c1["params"].get("reference_roles"),
      {"input_reference_image_1": {"role": "room", "label": "the place"}})
c2 = run_event(FakeBackend("Flux1-Dev", "flux1", 0))
check("C2 no slot: no sentence", ("<ref" in c2["prompt"], "reference_roles" in c2["params"],
                                  "reference_images" in c2["params"]), (False, False, False))

# ------------------------------------------------------------------------------------------------ [D]
print("[D] day/night variant")
gal = Path(TEMP.name) / "gallery"
gal.mkdir()
Image.new("RGB", (64, 64), "white").save(gal / "day.png")
stored = {}
ph3 = FakeBackend(*PH3, 4)
with ExitStack() as st:
    st.enter_context(patch.object(world_ops, "resolve_location",
                                  lambda *a, **k: {"id": "L1", "name": "Market", "description": "a market square"}))
    st.enter_context(patch.object(world_ops, "get_gallery_dir", lambda *a, **k: gal))
    st.enter_context(patch.object(world_ops, "get_gallery_image_rooms", lambda *a, **k: {}))
    st.enter_context(patch.object(world_ops, "is_outdoor_room", lambda *a, **k: False))
    st.enter_context(patch.object(world_ops, "save_gallery_prompt",
                                  lambda loc, name, prompt: stored.update(prompt=prompt)))
    for name in ("toggle_background_image", "set_gallery_image_type", "set_gallery_image_room",
                 "set_gallery_image_meta"):
        st.enter_context(patch.object(world_ops, name, lambda *a, **k: None))
    st.enter_context(patch("app.core.task_queue.get_task_queue",
                           lambda: SimpleNamespace(track_start=lambda *a, **k: "t", track_activate=lambda *a, **k: None,
                                                   track_finish=lambda *a, **k: None)))
    st.enter_context(patch("app.imagegen.service.get_image_service", lambda: FakeService(ph3)))
    st.enter_context(patch("app.imagegen.routing.run_routed", routed_to(ph3)))
    asyncio.run(world_ops.generate_time_variant_core("Market", "day.png", "night", "", ""))
d = ph3.calls[-1]
check("D sent = stored + sentence", d["prompt"], stored.get("prompt", "") + ". " + KEEP)
check("D stored without token", "<ref" in stored.get("prompt", "<ref"), False)
check("D roles", d["params"].get("reference_roles"),
      {"input_reference_image_1": {"role": "canvas", "label": "the place"}})

# ------------------------------------------------------------------------------------------------ [E]
print("[E] prop source render")
front = Path(TEMP.name) / "front.png"
Image.new("RGB", (64, 64), "white").save(front)


def run_prop(backend, view, reference_variant=None):
    saved = {}
    with ExitStack() as st:
        st.enter_context(patch.object(props, "read_sidecar", lambda *a, **k: {"name": "armchair",
                                                                            "description": "a fabric armchair"}))
        st.enter_context(patch.object(props, "reference_front", lambda *a, **k: front))
        st.enter_context(patch.object(props, "save_source_image",
                                      lambda *a, **k: saved.update(prompt=k.get("prompt")) or True))
        st.enter_context(patch("app.imagegen.service.get_image_service", lambda: FakeService(backend)))
        st.enter_context(patch("app.imagegen.routing.run_routed", routed_to(backend)))
        ok = props._render_source("armchair-1", "", "", "", view=view, front_reference=True,
                                  reference_variant=reference_variant)
    return ok, backend.calls[-1], saved.get("prompt", "")


ok, e1, e1_stored = run_prop(FakeBackend(*FLUX, 1), "back")
check("E1 rendered", ok, True)
check("E1 sent = stored + sentence", e1["prompt"], e1_stored + ". " + VIEW)
check("E1 stored without token", "<ref" in e1_stored, False)
check("E1 roles", e1["params"].get("reference_roles"),
      {"input_reference_image_1": {"role": "view_source", "label": "the front"}})
ok, e2, e2_stored = run_prop(FakeBackend(*FLUX, 1), "front", reference_variant=0)
check("E2 front from another variant: slotted, no sentence",
      ("reference_images" in e2["params"], e2["prompt"] == e2_stored, "reference_roles" in e2["params"]),
      (True, True, False))
ok, e3, e3_stored = run_prop(FakeBackend("Flux1-Dev", "flux1", 0), "back")
check("E3 no slot: no sentence", (e3["prompt"] == e3_stored, "reference_images" in e3["params"]), (True, False))

# ------------------------------------------------------------------------------------------------ [F]
print("[F] tpose without a reference")
from app.core import config, model_refs  # noqa: E402

carrying = [(uc, fam, clothed) for uc in ("tpose", "profile") for fam in ("natural", "keywords")
            for clothed in (True, False)
            if "<ref" in config.get_use_case_prompts(uc, fam, clothed=clothed)["prompt_style"]]
check("F1 slot-optional styles carry no <ref", carrying, [])
tpose_style = config.get_use_case_prompts("tpose", "natural", clothed=True)["prompt_style"]
joined = config.join_style_prompt(
    tpose_style, model_refs.get_tpose_prompt() + ", Mia, slender, long red hair. She wears a blue summer dress and "
    "white sneakers, neutral relaxed facial expression", None)
for label, be in (("Qwen2.1", FakeBackend(*QWEN, 10)), ("Flux2-9B", FakeBackend(*FLUX, 1))):
    sent = ep.normalise(joined, {}, be)[0]
    check(f"F2 {label} no slot: byte-identical, A-pose and framing kept",
          (sent == joined, "A-pose" in sent, "both feet entirely inside the frame" in sent), (True, True, True))

print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
