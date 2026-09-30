#!/usr/bin/env python3
"""Smoke: re-rendering fallback images (improvement type fallback_rerender).

Usage:  ./.venv/bin/python scripts/smoke_fallback_rerender.py

Spec: development_instructions/plan-image-routing.md § 5 + review notes
("Verbesserungstyp"): candidates come from the image meta on every scan
(images with `fallback_from`), nothing is listed; while the intended spec does
not resolve, `apply` raises CandidateBusy (step stays pending); `apply`
renders EXPLICITLY on the backend the intended spec resolves to (no further
fallback, no new marker); done = a replacement with `source_file` = the
candidate and WITHOUT `fallback_from` (portrait: the current profile image
carries no `fallback_from`). Throwaway storage + world DB, fake producers.

PART A — the subject helpers
A1 character "Mara": images a.png (fallback_from {occasion photo,
   intended_spec "Big*", position 0}, prompt "a harbour photo"), b.png (no
   marker, prompt "b"), p.png (the profile image, with a marker) ->
   character_gallery_images("Mara") lists a.png and b.png (not the profile),
   a.png with its fallback_from, b.png with fallback_from None.
A2 character_profile("Mara")["fallback_from"] == p.png's marker.
A3 regenerate_character_gallery_image("Mara", "a.png", "Big A") calls the
   regenerate producer with backend_name "Big A", create_new True and the
   stored prompt; the new file's meta has source_file "a.png".
A4 gallery_images(<loc>) carries each image's fallback_from.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
STORAGE = Path(tempfile.mkdtemp(prefix="fallback-rerender-"))
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="fallback-rerender-clips-")
from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core.improvements.types import subjects  # noqa: E402
from app.models import world  # noqa: E402
from app.models.character import (add_character_image_metadata,  # noqa: E402
                                  add_character_image_prompt, get_character_images_dir,
                                  get_single_image_meta, save_character_profile,
                                  set_character_profile_image)
from app.skills import image_regenerate  # noqa: E402

FAILS = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILS.append(label)


MARK = {"occasion": "photo", "intended_spec": "Big*", "position": 0}
REGEN_CALLS = []


def fake_regenerate_image(character_name, output_path, original_prompt, **kw):
    REGEN_CALLS.append({"name": character_name, "path": Path(output_path).name,
                        "prompt": original_prompt, "backend_name": kw.get("backend_name"),
                        "create_new": kw.get("create_new")})
    new = Path(output_path).with_name(Path(output_path).stem + "_v1.png")
    new.write_bytes(b"\x89PNG fake")
    add_character_image_metadata(character_name, new.name,
                                 {"backend": kw.get("backend_name"), "prompt": original_prompt,
                                  "routing": None, "fallback_from": None})
    return True, original_prompt, str(new)


image_regenerate.regenerate_image = fake_regenerate_image


def make_images():
    save_character_profile("Mara", {"name": "Mara", "appearance": "a tall woman"},
                           create_new=True)
    d = get_character_images_dir("Mara")
    d.mkdir(parents=True, exist_ok=True)
    for fn, prompt, marker in (("a.png", "a harbour photo", MARK), ("b.png", "b", None),
                               ("p.png", "a portrait", MARK)):
        (d / fn).write_bytes(b"\x89PNG fake")
        add_character_image_prompt("Mara", fn, prompt)
        add_character_image_metadata("Mara", fn, {"backend": "Cheap", "fallback_from": marker})
    set_character_profile_image("Mara", "p.png")


def part_a():
    print("A) subject helpers")
    make_images()
    rows = {r["filename"]: r for r in subjects.character_gallery_images("Mara")}
    check("A1 listed", sorted(rows), ["a.png", "b.png"])
    check("A1 markers", (rows["a.png"]["fallback_from"], rows["b.png"]["fallback_from"]),
          (MARK, None))
    check("A2 profile marker", (subjects.character_profile("Mara") or {}).get("fallback_from"), MARK)
    subjects.regenerate_character_gallery_image("Mara", "a.png", "Big A")
    call = REGEN_CALLS[-1]
    check("A3 producer call", (call["path"], call["backend_name"], call["create_new"], call["prompt"]),
          ("a.png", "Big A", True, "a harbour photo"))
    check("A3 source_file", get_single_image_meta("Mara", "a_v1.png").get("source_file"), "a.png")
    loc = world.add_location("Harbour", "A small harbour.")["id"]
    g = world.get_gallery_dir(loc)
    g.mkdir(parents=True, exist_ok=True)
    (g / "x.png").write_bytes(b"\x89PNG fake")
    world.save_gallery_prompt(loc, "x.png", "a harbour")
    world.set_gallery_image_meta(loc, "x.png", {"backend": "Cheap", "fallback_from": MARK})
    check("A4 gallery marker", [i["fallback_from"] for i in subjects.gallery_images(loc)], [MARK])


if __name__ == "__main__":
    part_a()
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) failed: {FAILS}")
        sys.exit(1)
    print("all checks passed")
