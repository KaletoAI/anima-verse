#!/usr/bin/env python3
"""Ruling A125: every dressed view is an EDIT of the base view of the same direction (input 1), the outfit's
reference picture only as a SECOND picture where the backend takes one, then composited back onto the base view —
the base outside the change mask, the edit inside, the alpha always the base's.

Usage:
    ./.venv/bin/python scripts/smoke_dressed_edit_a125.py

Runs without the server and without a world: no paths.init, no DB. Every socket connect is refused for the whole
run (``socket.socket.connect`` raises), so a hub / image / LLM request would fail the smoke — and the stubs record
that none was attempted.

Fixtures (PIL, in a temp dir that stands for ``model_refs``): BASE = 100 x 200 RGBA, figure = columns 40..59, rows
20..179, colour (200, 160, 130), alpha 255, background alpha 0. OUTFIT = 64 x 64 RGB (10, 200, 10).

Expected, by hand:
[1] Slot plan (``PromptBuilder._resolve_qwen_slots``): the creating character's reference BASE at position 1,
    ``extra_ref_images`` = [OUTFIT]. 10 slots (Qwen2.1) -> {input_reference_image_1: BASE, input_reference_image_2:
    OUTFIT}, in that order. 4 slots (P-H3) -> the same two. 1 slot (CivitAI img2img, a Flux2 entry) ->
    {input_reference_image_1: BASE} only. A plan WITHOUT the character's own reference gets no extra either
    (an extra is never input 1).
[2] ``service._with_extra_reference_prompt("P", …)``: both slotted -> "P " + sentence; 1 slot -> "P" unchanged.
[3] The built request of an ``openai_diffusion`` img2img entry (requests.post stubbed, never sent): JSON
    ``ref_images`` = [b64(BASE bytes), b64(OUTFIT bytes)] — two entries, the base first.
[4] ``base_body.render_view_edit("Demo", "back", …)`` with ``render_character_image`` stubbed: reference_image = the
    base view centred on a grey square (``square_frame``: side = max(100, 200) = 200 rounded up to SIZE_STEP 16 =
    208, offset ((208-100)//2, (208-200)//2) = (54, 4)) -> pixel row 4+100, column 54+50 = the figure colour
    (200, 160, 130); require_reference True;
    extra_reference_images = one file whose pixels are OUTFIT's; extra_reference_prompt = EDIT_SECOND_PICTURE with
    ", as it looks from behind"; image_use_case "outfit_edit"; crop_back_to (208, (54, 4), (100, 200)); sidecar
    draft_method "base_edit". Without ``second``: no extra picture and no sentence.
[5] ``view_composite.compose(BASE, EDIT, base_alpha=True)``. EDIT = BASE with a garment: rows 90..129 of the figure
    painted (30, 40, 160) AND widened to columns 34..65 (a flare outside the base silhouette). Then:
    - alpha of the result == BASE alpha at every pixel (byte-identical);
    - RGB == BASE RGB at every pixel farther than 4 px from rows 90..129 (the feather of ``_blend`` reaches 1.2 px
      Gaussian inside a 2 px dilation; the seam band is measured on the mask, so 4 px is the bound) — i.e. rows
      0..85 and 134..199 byte-identical;
    - inside the garment core (rows 95..124, columns 44..55) the RGB is the garment's, every channel within 12 of
      (30, 40, 160);
    - the record says alpha "base".
"""
import base64
import io
import socket
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILS = []
CONNECTS = []


def check(label, ok, detail=""):
    print(f"{'ok ' if ok else 'FAIL'} {label} {detail}")
    if not ok:
        FAILS.append(label)


def _refuse(self, *a, **k):  # noqa: ANN001
    CONNECTS.append(a)
    raise OSError("outbound connection refused by the smoke")


socket.socket.connect = _refuse

FIG = (200, 160, 130)
GARMENT = (30, 40, 160)


def base_rgba():
    a = np.zeros((200, 100, 4), dtype=np.uint8)
    a[20:180, 40:60, :3] = FIG
    a[20:180, 40:60, 3] = 255
    return a


def main():
    from app.core import base_body, view_composite
    from app.core.prompt_builder import Person, PromptBuilder, PromptVariables
    from app.imagegen import service

    with tempfile.TemporaryDirectory() as tmp:
        refs = Path(tmp) / "model_refs"
        refs.mkdir()
        base_path = refs / "tpose_back_base.png"
        Image.fromarray(base_rgba(), "RGBA").save(base_path)
        outfit_path = refs / "outfit.png"
        Image.new("RGB", (64, 64), (10, 200, 10)).save(outfit_path)
        base_s, outfit_s = str(base_path), str(outfit_path)

        # [1] slot plan
        def plan(slots, own=True):
            pv = PromptVariables()
            pv.persons = [Person(name="Demo", appearance="", gender="", is_agent=True)]
            if own:
                pv.ref_images[1] = base_s
            pv.extra_ref_images = [outfit_s]
            return PromptBuilder("Demo").resolve_reference_slots(pv, max_slots=slots)["reference_images"]
        for slots in (10, 4):
            got = plan(slots)
            check(f"[1] {slots} slots: base 1, outfit 2", list(got.items()) == [
                ("input_reference_image_1", base_s), ("input_reference_image_2", outfit_s)], got)
        check("[1] 1 slot: base only", plan(1) == {"input_reference_image_1": base_s}, plan(1))
        check("[1] no own reference: no extra", plan(10, own=False) == {}, plan(10, own=False))

        # [2] the sentence only where every extra is slotted
        sentence = base_body.edit_second_picture("back")
        data = {"extra_reference_images": [outfit_s], "extra_reference_prompt": sentence}
        pv = PromptVariables()
        pv.extra_ref_images = [outfit_s]

        class B:
            name, ref_slot_count = "stub", 1
        check("[2] slotted -> sentence appended",
              service._with_extra_reference_prompt("P", data, pv, plan(10), B()) == f"P {sentence}")
        check("[2] one slot -> unchanged", service._with_extra_reference_prompt("P", data, pv, plan(1), B()) == "P")

        # [3] the built request of an openai_diffusion img2img entry
        from app.imagegen.backends import openai_diffusion as od
        sent = {}

        class Resp:
            status_code = 200
            text = ""

            def json(self):
                buf = io.BytesIO()
                Image.new("RGB", (8, 8)).save(buf, format="PNG")
                return {"data": [{"b64_json": base64.b64encode(buf.getvalue()).decode()}]}

        def post(url, json=None, **kw):  # noqa: A002
            sent["url"], sent["json"] = url, json
            return Resp()
        real_post = od.requests.post
        od.requests.post = post
        try:
            backend = od.OpenAIDiffusionBackend("Qwen2.1", "http://gateway.invalid", 0.0, "A125_SMOKE_",
                                                model="Qwen2.1")
            backend.category = "img2img"
            backend._generate("P", "", {"reference_images": plan(10), "width": 512, "height": 512})
        finally:
            od.requests.post = real_post
        refs_sent = (sent.get("json") or {}).get("ref_images") or []
        check("[3] request: two pictures, base first",
              refs_sent == [base64.b64encode(base_path.read_bytes()).decode(),
                            base64.b64encode(outfit_path.read_bytes()).decode()], f"{len(refs_sent)} sent")

        # [4] render_view_edit hands base view (input 1) and the second picture to the render
        from app.core import expression_regen
        calls = []

        def fake_render(character_name, **kw):
            ref = np.asarray(Image.open(kw["reference_image"]).convert("RGB"))
            extras = [np.asarray(Image.open(p).convert("RGB")) for p in kw.get("extra_reference_images") or []]
            calls.append({**kw, "_ref": ref, "_extras": extras})
            return None
        real = expression_regen.render_character_image
        expression_regen.render_character_image = fake_render
        try:
            prompt = ("Keep the image exactly as it is … Only change their clothing: a blue tunic.", "neg")
            common = {"equipped_pieces": {}, "equipped_items": [], "image_use_case": "base_view_back"}
            base_body.render_view_edit("Demo", "back", stem=refs / "drafts" / "x", base_view=base_path,
                                       second=outfit_path, refs_dir=refs, prompt=prompt,
                                       occasion="outfit_back_draft", common=common, sidecar_extra={"k": 1})
            base_body.render_view_edit("Demo", "back", stem=refs / "drafts" / "x", base_view=base_path,
                                       second=None, refs_dir=refs, prompt=prompt,
                                       occasion="outfit_back_draft", common=common, sidecar_extra={})
        finally:
            expression_regen.render_character_image = real
        c = calls[0]
        check("[4] input 1 = base view on its square", c["_ref"].shape[:2] == (208, 208)
              and tuple(c["_ref"][104, 104]) == FIG, f"{c['_ref'].shape} {tuple(c['_ref'][104, 104])}")
        check("[4] require_reference", c["require_reference"] is True)
        check("[4] input 2 = the outfit picture", len(c["_extras"]) == 1
              and (c["_extras"][0] == np.array([10, 200, 10])).all())
        check("[4] sentence", c["extra_reference_prompt"] == base_body.EDIT_SECOND_PICTURE.format(
            seen=", as it looks from behind"), c["extra_reference_prompt"])
        check("[4] use case outfit_edit, prompt kept", c["image_use_case"] == "outfit_edit"
              and c["bare_prompt"] == prompt[0] and c["extra_negative"] == "neg")
        check("[4] crop back", c["crop_back_to"] == (208, (54, 4), (100, 200)), c["crop_back_to"])
        check("[4] sidecar method", c["sidecar_extra"].get("draft_method") == "base_edit")
        check("[4] without a second picture", calls[1]["extra_reference_images"] == []
              and calls[1]["extra_reference_prompt"] == "")

        # [5] composite: base outside the change, edit inside, alpha the base's
        edit = base_rgba()
        edit[90:130, 34:66, :3] = GARMENT
        edit[90:130, 34:66, 3] = 255
        edit_path = refs / "edit.png"
        Image.fromarray(edit, "RGBA").save(edit_path)
        out_path = refs / "out.png"
        record = view_composite.compose(base_path, edit_path, out_path, rule="outfit", base_alpha=True)
        out = np.asarray(Image.open(out_path).convert("RGBA"))
        base = base_rgba()
        check("[5] alpha byte-identical to the base", (out[..., 3] == base[..., 3]).all(),
              f"differs at {int((out[..., 3] != base[..., 3]).sum())} px")
        far = np.ones(200, bool)
        far[86:134] = False
        same = (out[far, :, :] == base[far, :, :]).all()
        check("[5] RGBA byte-identical outside the change (rows 0..85, 134..199)", same,
              f"differs at {int((out[far] != base[far]).any(-1).sum())} px")
        core = out[95:125, 44:56, :3].astype(int)
        check("[5] garment inside", (np.abs(core - np.array(GARMENT)) <= 12).all(),
              f"max dev {int(np.abs(core - np.array(GARMENT)).max())}")
        check("[5] record alpha base", record.get("alpha") == "base", record.get("alpha"))
        print("composite record:", view_composite.summary(record))

    check("no outbound connection", not CONNECTS, CONNECTS)
    print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'all ok'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
