#!/usr/bin/env python3
"""Smoke run for the multi-view mesh input: view detection + slot mapping.

No world, no DB, no server, no gateway — the two pure mappings of
``OpenAIMeshBackend`` are called as static/class methods, without an instance.

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
"""
import sys
from pathlib import Path

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


print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
    sys.exit(1)
print("all mesh-multiview checks passed")
