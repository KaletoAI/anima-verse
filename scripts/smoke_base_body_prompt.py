#!/usr/bin/env python3
"""Base body: description, view prompts, negative and signature (app/core/base_body.py).

Usage:
    ./.venv/bin/python scripts/smoke_base_body_prompt.py

Runs against a THROWAWAY storage directory with a copy of the repo's ``human``
package plus ONE fixture package — no real world, no private pack, no server.
Every expectation is derived by hand below from the human manifest, the fixture
and the rules of ``app/core/base_body.py``.

Fixture character ``Demo`` (template human-default): gender female, age 30,
height 168, body slots skin.tone olive, eyes.color green, build.type athletic,
hair long brunette, character_appearance "wears a red scarf". Fixture package
``fixture_marks`` (apply_to human-default) declares the slot ``marking``
(always "{shade} marking", NOT flagged ``base_body``, ``base_body_negative``
"  visible marking  ") and the slot ``spot`` (applies_to gender male only,
``base_body_negative`` "spot"); Demo stores shade "faint".

[1] base_appearance. Gender/age through the template's character_appearance
    replacement tokens, in the "{gender}, {age} years old" phrasing World-Dev
    asks for: "female, 30 years old". Then the ``always`` fragments of the
    slots flagged ``base_body: true`` in package/slot order — packages sort by
    id (fixture_marks before human), fixture_marks has no flagged slot; human:
    hair (not flagged) skipped, eyes "{color} eyes" -> "green eyes", skin
    "{tone} skin" -> "olive skin", build "{height}, {type} build" with height
    168 cm female (160 <= 168 < 172 -> "average height") -> "average height,
    athletic build", facial_hair (male only, not flagged) skipped. The height
    is carried by the build fragment, so it is not added a second time:
        "female, 30 years old, green eyes, olive skin, average height, athletic build"
    It contains neither "hair" (hair slot unflagged) nor "scarf" (free text
    never used) nor "marking" (unflagged pack slot).
[2] Front prompt. A-pose front text of model_refs without its hair clause
    ("no hair on the chest or in front of the shoulders, chest, collarbones
    and front of the shoulders fully uncovered"):
        POSE_FRONT = "standing upright facing the camera, A-pose, arms straight and
        angled about 45 degrees down and away from the body, not touching the body,
        palms facing the thighs, all five fingers straight, relaxed and slightly
        apart, each finger clearly separated and visible, hands in natural
        proportion to the body, legs clearly apart with open space visible between
        them"
    prompt = POSE_FRONT + ", " + FULL + ", " + BALD + ", " + BODY + ", " + [1]
    with BODY = "a smooth, featureless mannequin-like body without anatomical
    detail, no clothing". It therefore starts with POSE_FRONT, contains
    "completely bald" and "mannequin-like body without anatomical detail", and
    the word "hair" only inside BALD ("with no hair at all").
[3] Back prompt. Back text minus "the same hairstyle, hair length and hair
    volume as the reference" -> ends "...legs clearly apart with open space
    visible between them". Back view drops face segments from the body layer
    (prompt_builder.strip_face_terms): "natural eyebrows" and "green eyes" go.
[4] Left prompt. Side text with side=left minus "the same hairstyle, hair
    length and hair volume as the reference" and "no hair on the chest or in
    front of the shoulders" -> ends "...relaxed and slightly apart, legs
    clearly apart"; then FULL, BALD, BODY, [1] (face terms kept, a profile shows
    the face).
[5] Negative (all views) = BASE = HAIR_NEG + ", clothing, underwear,
    jewellery, detailed anatomy, " + POSE_NEG, then the ``base_body_negative``
    of every slot that APPLIES to Demo (flag irrelevant): marking applies
    (no applies_to) -> ", visible marking" (the loader strips the blanks);
    spot is male-only -> nothing. human declares none. So
    negative = BASE + ", visible marking".
[6] base_signature: "base" + 8 hex = 12 chars, no "-"/"_"; identical on a
    second call; changes when the profile image file changes (other name and
    size) and when the skin tone changes (olive -> fair).
[7] Hair-clause removal tolerates an admin override without the clauses
    (image_generation.tpose_prompt = "custom pose, arms down, hair tied back"):
    the "hair tied back" clause is dropped, the rest kept verbatim:
    front prompt starts "custom pose, arms down, " + FULL.
[8] is_base_pipeline: False by default; True with model_pipeline "base_body";
    False for an animal-template profile with the same field.
[9] base_body_negative: the parsed slot spec carries "visible marking"; a
    male profile (same slots) gets BASE + ", visible marking, spot"; the base
    signature changes when the marking's text changes ("visible marking" ->
    "bold marking") and is back to the old value once restored — the
    signature hashes the negatives.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


FIXTURE = {
    "name": "fixture_marks",
    "apply_to": ["human-default"],
    "body_slots": [{
        "id": "marking",
        "attributes": {"shade": {"type": "select", "options": ["faint", "bold"]}},
        "prompt": {"always": "{shade} marking"},
        "base_body_negative": "  visible marking  ",
    }, {
        "id": "spot",
        "applies_to": {"gender": ["male"]},
        "base_body_negative": "spot",
    }],
}

POSE_FRONT = ("standing upright facing the camera, A-pose, arms straight and angled about 45 degrees down and "
              "away from the body, not touching the body, palms facing the thighs, all five fingers straight, "
              "relaxed and slightly apart, each finger clearly separated and visible, hands in natural proportion "
              "to the body, legs clearly apart with open space visible between them")
POSE_BACK = ("the same figure turned around, back view, seen directly from behind, the back of the head, the upper "
             "back and the shoulder blades facing the camera, the head facing straight away from the camera in the "
             "same direction as the body, standing upright in A-pose, arms straight and angled about 45 degrees "
             "down and away from the body, not touching the body, palms facing the thighs, hands in natural "
             "proportion to the body, all five fingers straight, relaxed and slightly apart, legs clearly apart "
             "with open space visible between them")
POSE_LEFT = ("the same figure turned sideways, strict left side profile view, the whole body in profile facing the "
             "left edge of the frame, standing upright in A-pose, the far arm partly hidden behind the body, the "
             "near arm straight and angled down and away from the body, not touching the body, not foreshortened "
             "toward the camera, palms facing the thighs, hands in natural proportion to the body, all five "
             "fingers straight, relaxed and slightly apart, legs clearly apart")
FULL = ("full body shot from the top of the head to the soles of the feet, the entire figure inside the frame "
        "with empty margin above the head and below the feet")
BALD = ("completely bald, smooth clean-shaven head with no hair at all, the bare scalp and the bare back of the "
        "head fully visible, the ears fully visible, natural eyebrows")
BALD_BACK = ("completely bald, smooth clean-shaven head with no hair at all, the bare scalp and the bare back of "
             "the head fully visible, the ears fully visible")
BODY = "a smooth, featureless mannequin-like body without anatomical detail, no clothing"
APPEARANCE = "female, 30 years old, green eyes, olive skin, average height, athletic build"
APPEARANCE_BACK = "female, 30 years old, olive skin, average height, athletic build"
HAIR_NEG = ("hair, long hair, short hair, ponytail, braid, bun, fringe, bangs, wig, headscarf, hat, hood, "
            "stubble on the scalp, hair on the shoulders, hair on the back")
POSE_NEG = ("hands touching body, fists, curled fingers, fused fingers, mitten hands, cropped feet, feet cut off, "
            "cropped legs, close-up, portrait crop")
BASE = HAIR_NEG + ", clothing, underwear, jewellery, detailed anatomy, " + POSE_NEG
NEGATIVE = BASE + ", visible marking"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="base-body-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human,fixture_marks"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        (plugins / "fixture_marks").mkdir(parents=True)
        (plugins / "fixture_marks" / "plugin.yaml").write_text(json.dumps(FIXTURE))
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import base_body
        from app.models.character import (get_character_images_dir, get_character_profile,
                                          save_character_profile)

        name = "Demo"
        profile = {"template": "human-default", "gender": "female", "age": 30, "height": 168,
                   "character_appearance": "wears a red scarf",
                   "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                  "build": {"type": "athletic"},
                                  "hair": {"length": "long", "color": "brunette"},
                                  "marking": {"shade": "faint"}}}
        check("create", save_character_profile(name, profile, create_new=True), True)
        images = get_character_images_dir(name)
        images.mkdir(parents=True, exist_ok=True)
        (images / "Demo_1.png").write_bytes(b"\x89PNG" + b"a" * 100)
        (images / "Demo_2.png").write_bytes(b"\x89PNG" + b"b" * 200)
        stored = get_character_profile(name)
        stored["profile_image"] = "Demo_1.png"
        check("save image", save_character_profile(name, stored), True)
        stored = get_character_profile(name)

        print("[1] base_appearance")
        appearance = base_body.base_appearance(name, profile=stored)
        check("appearance", appearance, APPEARANCE)
        check("no hair", "hair" in appearance, False)
        check("no scarf", "scarf" in appearance, False)
        check("no marking", "marking" in appearance, False)
        check("stored profile path", base_body.base_appearance(name), APPEARANCE)

        print("[2] front")
        prompt, negative = base_body.base_prompt(name, "front", profile=stored)
        check("front prompt", prompt, ", ".join([POSE_FRONT, FULL, BALD, BODY, APPEARANCE]))
        check("starts with A-pose front", prompt.startswith(POSE_FRONT), True)
        check("completely bald", "completely bald" in prompt, True)
        check("mannequin body", "mannequin-like body without anatomical detail" in prompt, True)
        check("hair only in BALD", prompt.count("hair"), 1)
        check("negative", negative, NEGATIVE)

        print("[3] back")
        prompt, negative = base_body.base_prompt(name, "back", profile=stored)
        check("back prompt", prompt, ", ".join([POSE_BACK, FULL, BALD_BACK, BODY, APPEARANCE_BACK]))
        check("back negative", negative, NEGATIVE)

        print("[4] left / right")
        prompt, _ = base_body.base_prompt(name, "left", profile=stored)
        check("left prompt", prompt, ", ".join([POSE_LEFT, FULL, BALD, BODY, APPEARANCE]))
        prompt, _ = base_body.base_prompt(name, "right", profile=stored)
        check("right prompt", prompt,
              ", ".join([POSE_LEFT.replace("left", "right"), FULL, BALD, BODY, APPEARANCE]))
        check("views", base_body.BASE_VIEWS, ("front", "back", "left", "right"))

        print("[6] signature")
        sig = base_body.base_signature(name, profile=stored)
        check("length", len(sig), 12)
        check("prefix", sig.startswith("base"), True)
        check("hex tail", all(c in "0123456789abcdef" for c in sig[4:]), True)
        check("stable", base_body.base_signature(name, profile=stored), sig)
        other_image = dict(stored, profile_image="Demo_2.png")
        check("profile image changes it", base_body.base_signature(name, profile=other_image) != sig, True)
        fair = json.loads(json.dumps(stored))
        fair["body_slots"]["skin"]["tone"] = "fair"
        check("skin tone changes it", base_body.base_signature(name, profile=fair) != sig, True)

        print("[7] override without hair clauses")
        # The admin override is read through model_refs._cfg — patched for this
        # section only (the config module has no in-memory setter).
        from app.core import model_refs
        real_cfg = model_refs._cfg
        model_refs._cfg = lambda key, default=None: (
            "custom pose, arms down, hair tied back" if key == "tpose_prompt" else real_cfg(key, default))
        try:
            prompt, _ = base_body.base_prompt(name, "front", profile=stored)
            check("override front", prompt.startswith("custom pose, arms down, " + FULL), True)
            check("override changes signature", base_body.base_signature(name, profile=stored) != sig, True)
        finally:
            model_refs._cfg = real_cfg

        print("[8] is_base_pipeline")
        check("default", base_body.is_base_pipeline(name, profile=stored), False)
        check("switched on", base_body.is_base_pipeline(name, profile=dict(stored, model_pipeline="base_body")),
              True)
        animal = {"template": "animal-default", "model_pipeline": "base_body"}
        check("animal", base_body.is_base_pipeline("", profile=animal), False)

        print("[9] base_body_negative")
        from app.core.body_slots import slots_for_character
        marking = next(s for s in slots_for_character(name, profile=stored) if s.id == "marking")
        check("parsed + stripped", marking.base_body_negative, "visible marking")
        check("BASE_NEGATIVE constant", base_body.BASE_NEGATIVE, BASE)
        male = dict(stored, gender="male")
        check("male negative", base_body.base_negative(name, profile=male), BASE + ", visible marking, spot")
        sig = base_body.base_signature(name, profile=stored)
        marking.base_body_negative = "bold marking"
        try:
            check("text change changes signature", base_body.base_signature(name, profile=stored) != sig, True)
            check("changed negative", base_body.base_prompt(name, "front", profile=stored)[1],
                  BASE + ", bold marking")
        finally:
            marking.base_body_negative = "visible marking"
        check("restored signature", base_body.base_signature(name, profile=stored), sig)

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
