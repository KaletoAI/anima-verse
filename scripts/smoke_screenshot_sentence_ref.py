#!/usr/bin/env python3
"""Change plan point 0: the scene photo's screenshot sentence names its picture by slot (``<ref 1>``).

Usage: ./.venv/bin/python scripts/smoke_screenshot_sentence_ref.py

Since the edit-prompt normaliser (f54ec1651 / 53ded0ca3) "The reference image gives only composition …" was left as it
was with two or more slots — the model could not tell which picture is the screenshot. The sentence now says
``<ref 1>`` (the screenshot is ``input_reference_image_1``, the people follow from slot 2), and the normaliser renders
it per dialect (``edit_prompt.render_ref``). Expected, by hand from ``render_ref``:

[1] screenshot + 2 people (3 slots), P-H3 (picture_edit): "<Picture 1> gives only composition, …" — and the whole
    prompt opens with the engine prefix "Edit <Picture 1>." (the normaliser writes it, docs/edit-prompts.md §2).
[2] the same on MiniMax (picture_subject): "<Picture 1> gives only".
[3] the same on Qwen2.1 (image_tag, >= 2 images): "<image1> gives only".
[4] the same on an ordinal backend (Flux): "The first image gives only" (sentence start capitalised).
[5] ONE slot (the screenshot alone) on Qwen: "The image gives only" (one image is "the image", capitalised).
[6] ``with_screenshot_sentence`` of a stored prompt that carries the OLD spelling ("The reference image gives only …")
    and an already rendered one ("<Picture 1> gives only …"): both removed, the current sentence once at the end —
    the regenerate never doubles it (``image_regenerate`` and ``scene_photo.take`` both call it).
[7] the sentence carries no other spelling: no "reference image", exactly one ``<ref 1>``.
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TEMP = tempfile.TemporaryDirectory(prefix="smoke-screenshot-ref-")
os.environ["STORAGE_DIR"] = TEMP.name
os.environ["INSTANCE_DIR"] = TEMP.name
from app.core import paths  # noqa: E402

paths.init(TEMP.name)
from app.core import scene_photo  # noqa: E402
from app.imagegen.edit_prompt import normalise  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def backend(model):
    return SimpleNamespace(model=model, prompt_dialect_setting="auto", name=model)


def slots(n):
    return {"reference_images": {f"input_reference_image_{k}": f"/tmp/ref{k}.png" for k in range(1, n + 1)}}


BASE = "A photo of Ann and Bob in the kitchen, laughing."
prompt = scene_photo.with_screenshot_sentence(BASE)
TAIL = " gives only composition, camera angle and poses; its 3D/CGI look must not be copied."

out, _ = normalise(prompt, slots(3), backend("p-h3-image"))
check("[1] P-H3 3 slots", "<Picture 1>" + TAIL in out, True)
check("[1] P-H3 prefix", out.startswith("Edit <Picture 1>."), True)
out, _ = normalise(prompt, slots(3), backend("minimax-h3-image"))
check("[2] MiniMax 3 slots", "<Picture 1>" + TAIL in out, True)
out, _ = normalise(prompt, slots(3), backend("qwen2.1"))
check("[3] Qwen 3 slots", "<image1>" + TAIL in out, True)
out, _ = normalise(prompt, slots(3), backend("flux2-9b"))
check("[4] ordinal 3 slots", "The first image" + TAIL in out, True)
out, _ = normalise(prompt, slots(1), backend("qwen2.1"))
check("[5] Qwen 1 slot", "The image" + TAIL in out, True)

stored = (BASE + "\nThe reference image" + TAIL + "\n<Picture 1>" + TAIL)
again = scene_photo.with_screenshot_sentence(stored)
check("[6] old spellings removed, one sentence", again, BASE + "\n" + scene_photo._SCREENSHOT_SENTENCE)
check("[6] idempotent", scene_photo.with_screenshot_sentence(again), again)
check("[7] no 'reference image'", "reference image" in scene_photo._SCREENSHOT_SENTENCE.lower(), False)
check("[7] one <ref 1>", scene_photo._SCREENSHOT_SENTENCE.count("<ref 1>"), 1)

print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
