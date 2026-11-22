#!/usr/bin/env python3
"""Chat photo, Instagram, story, video still and profile name every slotted picture by its slot (docs/edit-prompts.md
§4, change plan point 1): the slot plan is computed BEFORE the prompt is rendered, the text says ``<ref N>`` where a
person / the room / an item sits, and exactly that plan is sent.

Usage:
    ./.venv/bin/python scripts/smoke_chat_photo_slots.py

No world DB, no server, no network: a throwaway STORAGE_DIR / INSTANCE_DIR (``paths.init`` before any world import),
hand-built ``PromptVariables`` and a capture backend whose ``_generate`` raises before any request.

Fixture: Mia (the creating character, position 1, picture ``mia.png``), Kai (position 2, ``kai.png``), the room
picture ``room.png``, one item "lamp" (``lamp.png``); prompt_persons {1: "Mia, red hair", 2: "Kai, tall man"},
outfits {1: "Mia is wearing a green coat", 2: "Kai is wearing a blue shirt"}, location "a small cafe", style
"photorealistic", scene "Mia and Kai drink tea".

Expected, derived by hand from the plan order (creating character > extra edit pictures > room > other persons >
items, ``plan_reference_slots``):

[1] 4 slots: plan = Mia, room, Kai, lamp -> person_slot {1: 1, 2: 3}, room_slot 2, item_slot_of {"lamp": 4};
    resolve_reference_slots sends mia/room/kai/lamp as input_reference_image_1..4 and the manifest
    {1: identity "Mia", 2: room "the room", 3: identity "Kai", 4: item "lamp"}. A plan stored for another slot count
    is not reused (1 slot -> only mia.png).
[2] Labeled sections (Qwen/Flux renderer), location cleared by the exclusion rule because the room is slotted:
      "- Mia (the person in <ref 1>), red hair, wearing a green coat."
      "- Kai (the person in <ref 3>), tall man, wearing a blue shirt."
      "Each person appears once."            (exactly once, as the last line of Characters)
      "Setting: the place shown in <ref 2>."
      "Objects: the lamp from <ref 4>."
    The keywords renderer: "Mia (the person in <ref 1>), red hair, green coat" … "the place in <ref 2>", "the lamp
    from <ref 4>", "each person appears once".
    A style that already says "each person appears exactly once" gets no second rule.
[3] 1 slot (Flux2-9B): only Mia is slotted -> "- Mia (the person in <ref 1>)", "- Kai, tall man" (no token), the
    location stays in the text ("Setting: a small cafe."), no "Objects:" line.
[4] normalise on the 4-slot prompt: P-H3 (picture_edit) -> starts "Edit <Picture 1>.", holds
    "Mia (the person in <Picture 1>)", "Kai (the person in <Picture 3>)", "the place shown in <Picture 2>",
    "the lamp from <Picture 4>", no "unused" note; Qwen2.1 (image_tag) -> "<image1>", "<image3>", "<image2>",
    "<image4>", no "role_missing" note (the manifest has no canvas: a new composition); Flux (ordinal) on the 1-slot
    prompt -> "Mia (the person in the image)". No output holds "<ref".
[5] strip_refs (the STORED prompt): strip_refs(the 4-slot render) == the render of the same variables without a
    plan (the text before this change plus the once-rule) — i.e. no "<ref", no "Setting:" line, no "Objects:" line.
    "a lamp (brass; as in <ref 4>)" -> "a lamp (brass)"; "a lamp (as in <ref 4>)" -> "a lamp"; text without a token
    comes back byte-identical.
[6] The enhancer guard (_keep_reference_tokens): an answer that lost "<ref 3>" -> the template, method "template";
    an answer with every token -> the answer and its method.
[7] Portrait (_portrait_character): set_profile, person_slot {1: 1}, block "34 year old man" ->
    "the same person as in <ref 1>, 34 year old man"; no slot -> unchanged; not a portrait -> unchanged.
[8] generate_on_backend end to end (auto_enhance, the builder's detection stubbed to the fixture): a capture
    backend with model "P-H3-Image" and 4 slots receives params["reference_images"] = mia/room/kai/lamp in that
    order, params["reference_roles"] = the manifest of [1], and a final prompt (after the normaliser) holding
    "Mia (the person in <Picture 1>)" and "Kai (the person in <Picture 3>)"; the STORED prompt
    (last_enhanced_prompt) holds no "<ref" and no "<Picture".
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="chat-photo-slots-"))
    os.environ["STORAGE_DIR"] = str(tmp / "world")
    os.environ["INSTANCE_DIR"] = str(tmp / "instance")
    from app.core import paths
    paths.init(str(tmp / "world"))
    paths.init_instance(str(tmp / "instance"))

    import copy
    from app.core.prompt_builder import Person, PromptBuilder, PromptVariables
    from app.core import prompt_adapters as pa
    from app.imagegen import edit_prompt as ep
    from app.imagegen import service as svc

    files = {}
    for n in ("mia", "kai", "room", "lamp"):
        files[n] = tmp / f"{n}.png"
        files[n].write_bytes(b"\x89PNG\r\n\x1a\n" + n.encode())

    def fixture(style="photorealistic"):
        return PromptVariables(
            persons=[Person("Mia", "red hair", "female", actor_label="Mia", is_agent=True),
                     Person("Kai", "tall man", "male", actor_label="Kai")],
            prompt_persons={1: "Mia, red hair", 2: "Kai, tall man"},
            prompt_outfits={1: "Mia is wearing a green coat", 2: "Kai is wearing a blue shirt"},
            ref_images={1: str(files["mia"]), 2: str(files["kai"])},
            ref_image_room=str(files["room"]),
            items=[{"name": "lamp", "image": str(files["lamp"])}],
            prompt_location="a small cafe", prompt_style=style, scene_prompt="Mia and Kai drink tea")

    b = PromptBuilder("Mia")
    print("[1] plan")
    pv = fixture()
    b.apply_exclusion_rules(pv, max_slots=4)
    b.apply_slot_plan(pv, 4)
    check("person_slot", pv.person_slot, {1: 1, 2: 3})
    check("room_slot", pv.room_slot, 2)
    check("item_slot_of", pv.item_slot_of, {"lamp": 4})
    res = b.resolve_reference_slots(pv, max_slots=4)
    check("reference_images", res["reference_images"],
          {f"input_reference_image_{i}": str(files[n]) for i, n in enumerate(("mia", "room", "kai", "lamp"), 1)})
    manifest = {"input_reference_image_1": {"role": "identity", "label": "Mia"},
                "input_reference_image_2": {"role": "room", "label": "the room"},
                "input_reference_image_3": {"role": "identity", "label": "Kai"},
                "input_reference_image_4": {"role": "item", "label": "lamp"}}
    check("reference_roles", res["reference_roles"], manifest)
    check("a plan of another slot count is not reused",
          b.resolve_reference_slots(pv, max_slots=1)["reference_images"],
          {"input_reference_image_1": str(files["mia"])})

    print("[2] renderers")
    text = pa.render(pv, "qwen")["input_prompt_positiv"]
    for line in ("- Mia (the person in <ref 1>), red hair, wearing a green coat.",
                 "- Kai (the person in <ref 3>), tall man, wearing a blue shirt.",
                 "Setting: the place shown in <ref 2>.", "Objects: the lamp from <ref 4>."):
        check(f"line {line[:30]!r}", line in text.split("\n"), True)
    check("once-rule exactly once", text.count(pa.ONCE_RULE), 1)
    check("once-rule ends Characters", text.split("\n\n")[1].split("\n")[-1], pa.ONCE_RULE)
    kw = pa.render(pv, "z_image")["input_prompt_positiv"]
    for bit in ("Mia (the person in <ref 1>), red hair, Mia is wearing a green coat", "the place in <ref 2>",
                "the lamp from <ref 4>", "each person appears once"):
        check(f"keywords {bit[:30]!r}", bit in kw, True)
    said = fixture(style="photorealistic, each person appears exactly once")
    b.apply_slot_plan(said, 4)
    check("no second once-rule", pa.ONCE_RULE in pa.render(said, "qwen")["input_prompt_positiv"], False)

    print("[3] one slot")
    one = fixture()
    b.apply_exclusion_rules(one, max_slots=1)
    b.apply_slot_plan(one, 1)
    t1 = pa.render(one, "flux")["input_prompt_positiv"]
    check("Mia token", "- Mia (the person in <ref 1>), red hair" in t1, True)
    check("Kai without token", "- Kai, tall man, wearing a blue shirt." in t1.split("\n"), True)
    check("location stays", "Setting: a small cafe." in t1.split("\n"), True)
    check("no Objects line", "Objects:" in t1, False)

    print("[4] normalise")

    class Stub:
        def __init__(self, name, model):
            self.name, self.model, self.prompt_dialect_setting = name, model, "auto"
    params = {"reference_images": res["reference_images"], "reference_roles": res["reference_roles"]}
    out, meta = ep.normalise(text, params, Stub("P-H3-Image", "P-H3-Image"))
    check("P-H3 prefix", out.startswith("Edit <Picture 1>."), True)
    for bit in ("Mia (the person in <Picture 1>)", "Kai (the person in <Picture 3>)",
                "the place shown in <Picture 2>", "the lamp from <Picture 4>"):
        check(f"P-H3 {bit[:28]!r}", bit in out, True)
    check("P-H3 no unused", "unused" in meta["notes"], False)
    check("P-H3 roles in meta", meta["roles"], manifest)
    qout, qmeta = ep.normalise(text, params, Stub("Qwen2.1", "Qwen2.1"))
    check("Qwen tags", [t in qout for t in ("<image1>", "<image2>", "<image3>", "<image4>")], [True] * 4)
    check("Qwen no role_missing", "role_missing" in qmeta["notes"], False)
    fout, _ = ep.normalise(t1, {"reference_images": {"input_reference_image_1": str(files["mia"])}},
                           Stub("Flux2-9B Normal", "Flux2-9B"))
    check("Flux 1 slot", "Mia (the person in the image)" in fout, True)
    check("no <ref left", any("<ref" in o for o in (out, qout, fout)), False)

    print("[5] strip_refs")
    plain = copy.deepcopy(pv)
    plain.reference_plan, plain.person_slot, plain.room_slot, plain.item_slot_of = None, {}, 0, {}
    check("stored == render without a plan", ep.strip_refs(text), pa.render(plain, "qwen")["input_prompt_positiv"])
    check("paren part", ep.strip_refs("a lamp (brass; as in <ref 4>)"), "a lamp (brass)")
    check("paren whole", ep.strip_refs("a lamp (as in <ref 4>)"), "a lamp")
    check("no token byte-identical", ep.strip_refs("Kai (tall), at home.\n\nStyle: x."), "Kai (tall), at home.\n\nStyle: x.")

    print("[6] enhancer guard")
    check("lost token", svc._keep_reference_tokens("A (<ref 1>) B (<ref 3>)", "A (<ref 1>) B", "template+llm"),
          ("A (<ref 1>) B (<ref 3>)", "template"))
    check("kept tokens", svc._keep_reference_tokens("A (<ref 1>)", "nice A (<ref 1>)", "template+llm"),
          ("nice A (<ref 1>)", "template+llm"))

    print("[7] portrait")
    pp = PromptVariables(set_profile=True, person_slot={1: 1})
    check("lead", svc._portrait_character(pp, "34 year old man"), "the same person as in <ref 1>, 34 year old man")
    check("no slot", svc._portrait_character(PromptVariables(set_profile=True), "x"), "x")
    check("not a portrait", svc._portrait_character(PromptVariables(person_slot={1: 1}), "x"), "x")

    print("[8] generate_on_backend")
    from app.imagegen.base import ImageBackend

    class Reached(Exception):
        pass

    class Capture(ImageBackend):
        def __init__(self):
            super().__init__("P-H3-Image", "http://unused", 0, "fake", "CHAT_SLOTS_")
            self.model = "P-H3-Image"
            self.ref_slot_count = 4
            self.image_family = "natural"
            self._available = True
            self.seen = {}

        def check_availability(self):
            return True

        def _generate(self, prompt, negative_prompt, params):
            self.seen.update(prompt=prompt, params=dict(params))
            raise Reached()

    def collect(self, persons, config, **kw):
        return fixture()
    with patch.object(svc.ImageService, "_load_instances", return_value=[]):
        service = svc.ImageService()
    backend = Capture()
    payload = {"prompt": "Mia and Kai drink tea", "agent_name": "Mia", "auto_enhance": True, "skip_gallery": True,
               "occasion": "photo"}
    with (patch.object(service, "_get_instance_config", return_value={}),
          patch.object(service, "run_on_backend_channel", side_effect=lambda b, fn, **k: fn()),
          patch.object(PromptBuilder, "detect_persons", lambda self, *a, **k: fixture().persons),
          patch.object(PromptBuilder, "apply_photographer_filter", lambda self, persons, **k: persons),
          patch.object(PromptBuilder, "collect_context", collect),
          patch.object(PromptBuilder, "sanitize_scene_prompt", lambda self, s, pv: s),
          patch("app.core.prompt_adapters.maybe_enhance_via_llm", lambda t, pv, **k: (t, "template"))):
        try:
            service.generate_on_backend(backend, service._parse_input(json.dumps(payload)), explicit=True)
        except Exception as e:  # noqa: BLE001 — the capture ends the render
            if not backend.seen:
                raise
    sent = backend.seen.get("params", {})
    check("sent pictures in plan order", sent.get("reference_images"), res["reference_images"])
    check("sent manifest", sent.get("reference_roles"), manifest)
    fp = backend.seen.get("prompt", "")
    check("final prompt binds Mia", "Mia (the person in <Picture 1>)" in fp, True)
    check("final prompt binds Kai", "Kai (the person in <Picture 3>)" in fp, True)
    stored = getattr(service._meta_tls, "last_enhanced_prompt", "")
    check("stored prompt without tokens", ("<ref" in stored, "<Picture" in stored, bool(stored)), (False, False, True))

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    import shutil
    _tmp_before = set(Path(tempfile.gettempdir()).glob("chat-photo-slots-*"))
    try:
        code = main()
    finally:
        for d in set(Path(tempfile.gettempdir()).glob("chat-photo-slots-*")) - _tmp_before:
            shutil.rmtree(d, ignore_errors=True)
    sys.exit(code)
