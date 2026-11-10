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
``base_body_negative`` "spot", ``base_body_prompt`` "pale spot") and the slot
``tail`` (attribute length, NOT flagged ``base_body``, ``base_body_prompt``
"  {length} tail  ") and the slots ``frag_a`` / ``frag_b`` (attribute text,
NOT flagged, ``base_body_prompt`` "{text}", neutral stand-ins for a pack's
undressed-body fragments); Demo stores shade "faint", no tail length and no
frag text — an unfilled placeholder drops the fragment.

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
    never used) nor "marking" (unflagged pack slot) nor "tail" (its
    ``base_body_prompt`` has no length value -> dropped) nor "spot" (male only).
[2] Front (user directive 2026-11-09, "character details always first").
    base_prompt(front) = what follows the style:
        POSE_FRONT + ", " + BALD + ", " + BODY
    POSE_FRONT = model_refs.BASE_FRONT_POSE_PROMPT, the A-pose front WITHOUT
    "palms facing the thighs" and without the hair clause:
        "standing upright facing the camera, A-pose, arms straight and angled
        about 45 degrees down and away from the body, not touching the body,
        all five fingers straight, relaxed and slightly apart, each finger
        clearly separated and visible, hands in natural proportion to the
        body, legs clearly apart with open space visible between them"
    BALD = "completely bald, smooth clean-shaven head with no hair at all,
    the bare scalp and the bare back of the head fully visible, natural
    eyebrows" (no ears clause), BODY = "a smooth, featureless mannequin-like
    body without anatomical detail" ("sfw, no clothing" moved into the block),
    no framing sentence. base_character(front) = "sfw, no clothing, " + [1].
    The word "hair" occurs once in the prompt (BALD's "with no hair at all").
[3] Back (user test 2026-11-09: the long texts made Qwen invent things):
    base_prompt = VIEW_BACK, the whole prompt of the edit, written out
    below; no character block (base_character -> None).
[4] Left/right: VIEW_LEFT / VIEW_RIGHT (written out below), no block;
    use cases base_front / base_view_back / base_view_side / base_view_side.
[5] Negative (all views) = BASE = HAIR_NEG + ", clothing, underwear,
    jewellery, detailed anatomy, " + POSE_NEG, then the ``base_body_negative``
    of every slot that APPLIES to Demo (flag irrelevant): marking applies
    (no applies_to) -> ", visible marking" (the loader strips the blanks);
    spot is male-only -> nothing. human declares none. So
    negative = BASE + ", visible marking".
[6] base_signature: "base" + 8 hex = 12 chars, no "-"/"_"; identical on a
    second call; changes when the profile image file changes (other name and
    size) and when the skin tone changes (olive -> fair) — the tone only
    sits in the character block, so the block is hashed.
[7] Admin pose overrides: the base FRONT is a constant, so an override of
    image_generation.tpose_prompt changes neither the front prompt nor the
    signature. The base back is a constant too: tpose_back_prompt = "custom
    back pose, arms down, hair tied back" leaves base_prompt(back) ==
    VIEW_BACK and the signature unchanged; the back DRAFT follows the
    override with hair-clause removal: "custom back pose, arms down, " +
    BALD_BACK + ", " + OUTFIT.
[8] is_base_pipeline: False by default; True with model_pipeline "base_body";
    False for an animal-template profile with the same field.
[9] base_body_negative: the parsed slot spec carries "visible marking"; a
    male profile (same slots) gets BASE + ", visible marking, spot"; the base
    signature changes when the marking's text changes ("visible marking" ->
    "bold marking") and is back to the old value once restored — the
    signature hashes the negatives.
[10] base_body_prompt: the parsed tail spec carries "{length} tail" (the
    loader strips the blanks), marking/human slots carry "". Demo with tail
    length "long": appearance = APPEARANCE + ", long tail" (appended after the
    flagged fragments, though tail is not flagged), the front BLOCK ends
    ", long tail" (the prompt does not contain "long tail"), and the base
    signature differs from the one without a length; length "short" ->
    APPEARANCE + ", short tail" and yet another signature. A male profile
    with length "long": the description ends ", pale spot, long tail" (slot
    order marking, spot, tail; spot applies to males and has no
    placeholder) — the female one has no "spot".
[11] Back DRAFT (user decisions 2026-11-09; it keeps the long view text,
    unlike the base back): prompt = POSE_BACK, BALD_BACK, OUTFIT — POSE_BACK
    the mesh-input back text minus "the same hairstyle, hair length and hair
    volume as the reference" (ends "...legs clearly apart with open space
    visible between them"), BALD_BACK = BALD minus "natural eyebrows"
    (strip_face_terms), OUTFIT = "wearing exactly the same outfit as the
    person in the reference image, the same garments, lengths, cut, colours
    and shoes" in BODY's place; block = "sfw, " + APPEARANCE_BACK — no "no clothing",
    no ``base_body_prompt`` text. For the long-tail profile of [10] the same
    block (its "long tail" is a base_body_prompt fragment), and neither
    "long tail" nor "mannequin" appears in prompt or block. Negative = HAIR_NEG +
    ", detailed anatomy, " + POSE_NEG (BASE without "clothing, underwear,
    jewellery") + ", visible marking".
[12] The FINAL front prompt — what the image service sends: the base_front
    natural style with the block in its {character} slot
    (config.get_use_case_prompts(..., clothed=False, character=block); the
    undressed base renders with clothed False, so "{fabric}" is empty), then
    base_prompt after ", " (config.join_style_prompt). Fixture ``Target``
    (human-default, female, 26, height 168, eyes blue, skin light, build
    athletic, plus two neutral fixture slots frag_a/frag_b whose
    base_body_prompt "{text}" renders "slot fragment a" / "slot fragment b"):
    appearance "female, 26 years old, blue eyes, light skin, average height,
    athletic build, slot fragment a, slot fragment b", and the final prompt
    is exactly TARGET below (written out by hand: the user's shortened text
    of 2026-11-09 with clean ", " separators, plus FEET = "both feet
    entirely inside the frame, with empty margin above the head and below
    the feet" right after "shown from head to toe against a plain neutral
    background" — without it the feet were cut off, user test 2026-11-09).
    Order checks: the block follows the subject clause directly, the pose
    follows "sharp focus, ". Back/left/right final prompt: the use cases
    base_view_back / base_view_side have an EMPTY style in both families,
    no block is sent, so the service sends VIEW_BACK / VIEW_LEFT /
    VIEW_RIGHT verbatim. Keywords family of the front: the block also
    follows "lifelike skin textures, ", FEET follows "head to toe, ".
    base_back / base_side (the outfit drafts) carry no feet/margin clause.
    Slot mechanics (config.fill_character_slot): no block (None) on a style
    without the slot -> unchanged; a slot without a block -> removed with
    its separator ("a, {character}, b" -> "a, b"); a block for a style
    WITHOUT the slot (admin override) -> the block opens the style
    ("blk, a, b"). join_style_prompt without a block = the historic
    f"{style} {prompt}" (single space), with one = ", ".
[13] The old whole-body T-pose path is byte-identical to commit bda7bd17
    (before this change): config.py of bda7bd17 executed as a separate
    module (``git show bda7bd17:app/core/config.py``, its own empty config ->
    built-in styles) gives the same get_use_case_prompts result as today's
    for EVERY use case it shipped × family × clothed — the new use cases
    (base_back, base_front, base_side, base_view_back, base_view_side, plus
    footwear_source — the empty-shoe edit of occasion footwear_empty, footwear
    plan 2026-11-10 Task 2) are additions only — and the T-pose pose constants of model_refs.py at
    bda7bd17 (TPOSE_PROMPT_DEFAULT, TPOSE_VIEW_PROMPT_DEFAULTS, read from the
    old source by exec of their assignments) equal today's. A tpose payload
    without "style_character" joins as f"{style} {prompt}".
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
        "base_body_prompt": "pale spot",
    }, {
        "id": "tail",
        "attributes": {"length": {"type": "select", "options": ["short", "long"]}},
        "base_body_prompt": "  {length} tail  ",
    }, {
        "id": "frag_a",
        "attributes": {"text": {"type": "select", "options": ["slot fragment a"]}},
        "base_body_prompt": "{text}",
    }, {
        "id": "frag_b",
        "attributes": {"text": {"type": "select", "options": ["slot fragment b"]}},
        "base_body_prompt": "{text}",
    }],
}

POSE_FRONT = ("standing upright facing the camera, A-pose, arms straight and angled about 45 degrees down and "
              "away from the body, not touching the body, all five fingers straight, relaxed and slightly apart, "
              "each finger clearly separated and visible, hands in natural proportion to the body, legs clearly "
              "apart with open space visible between them")
POSE_BACK = ("the same figure turned around, back view, seen directly from behind, the back of the head, the upper "
             "back and the shoulder blades facing the camera, the head facing straight away from the camera in the "
             "same direction as the body, standing upright in A-pose, arms straight and angled about 45 degrees "
             "down and away from the body, not touching the body, palms facing the thighs, hands in natural "
             "proportion to the body, all five fingers straight, relaxed and slightly apart, legs clearly apart "
             "with open space visible between them")
VIEW_BACK = ("The same person turned around, seen directly from behind, back view, same A-pose, same framing, "
             "completely bald, the whole figure from head to feet in the frame.")
VIEW_LEFT = ("The same person turned to a strict left side profile view, same A-pose, same framing, completely "
             "bald, the whole figure from head to feet in the frame.")
VIEW_RIGHT = ("The same person turned to a strict right side profile view, same A-pose, same framing, completely "
              "bald, the whole figure from head to feet in the frame.")
FEET = "both feet entirely inside the frame, with empty margin above the head and below the feet"
BALD = ("completely bald, smooth clean-shaven head with no hair at all, the bare scalp and the bare back of the "
        "head fully visible, natural eyebrows")
BALD_BACK = ("completely bald, smooth clean-shaven head with no hair at all, the bare scalp and the bare back of "
             "the head fully visible")
BODY = "a smooth, featureless mannequin-like body without anatomical detail"
APPEARANCE = "female, 30 years old, green eyes, olive skin, average height, athletic build"
APPEARANCE_BACK = "female, 30 years old, olive skin, average height, athletic build"
HAIR_NEG = ("hair, long hair, short hair, ponytail, braid, bun, fringe, bangs, wig, headscarf, hat, hood, "
            "stubble on the scalp, hair on the shoulders, hair on the back")
POSE_NEG = ("hands touching body, fists, curled fingers, fused fingers, mitten hands, cropped feet, feet cut off, "
            "cropped legs, close-up, portrait crop")
BASE = HAIR_NEG + ", clothing, underwear, jewellery, detailed anatomy, " + POSE_NEG
NEGATIVE = BASE + ", visible marking"
OUTFIT = ("wearing exactly the same outfit as the person in the reference image, the same garments, lengths, cut, "
          "colours and shoes")
# [12] The user's shortened base front (2026-11-09), written out by hand with
# clean separators and the neutral stand-in fragments of frag_a / frag_b.
TARGET = ("a full-body render of the character as a realistic 3D figure with lifelike skin textures, sfw, no "
          "clothing, female, 26 years old, blue eyes, light skin, average height, athletic build, slot fragment a, "
          "slot fragment b, shown from head to toe against a plain neutral background, both feet entirely inside the "
          "frame, with empty margin above the head and below the feet, the full arm span visible "
          "with both hands entirely inside the frame, flat even shadowless lighting, the face evenly lit from the "
          "front by soft diffuse light with no shadows on it, relit instead of keeping the lighting and shadows of "
          "the reference image, uniform illumination, sharp focus, standing upright facing the camera, A-pose, "
          "arms straight and angled about 45 degrees down and away from the body, not touching the body, all five "
          "fingers straight, relaxed and slightly apart, each finger clearly separated and visible, hands in "
          "natural proportion to the body, legs clearly apart with open space visible between them, completely "
          "bald, smooth clean-shaven head with no hair at all, the bare scalp and the bare back of the head fully "
          "visible, natural eyebrows, a smooth, featureless mannequin-like body without anatomical detail")
SUBJECT = "a full-body render of the character as a realistic 3D figure with lifelike skin textures"
#: The commit before the prompt-layout change ([13]) — never HEAD.
BEFORE = "bda7bd17"


def final_prompt(config, use_case, family, block, prompt):
    """What ImageService.generate_on_backend sends for a caller-built render."""
    style = config.get_use_case_prompts(use_case, family, clothed=False, character=block)["prompt_style"]
    return config.join_style_prompt(style, prompt, block) if style else prompt


def old_source(path: str) -> str:
    import subprocess
    return subprocess.run(["git", "show", f"{BEFORE}:{path}"], cwd=ROOT, capture_output=True, text=True,
                          check=True).stdout


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
        check("no tail without a length", "tail" in appearance, False)
        check("no spot for a female", "spot" in appearance, False)
        check("no frag without a text", "fragment" in appearance, False)
        check("stored profile path", base_body.base_appearance(name), APPEARANCE)

        print("[2] front")
        prompt, negative = base_body.base_prompt(name, "front", profile=stored)
        check("front prompt", prompt, ", ".join([POSE_FRONT, BALD, BODY]))
        check("front block", base_body.base_character(name, "front", profile=stored),
              "sfw, no clothing, " + APPEARANCE)
        check("pose constant", __import__("app.core.model_refs", fromlist=["x"]).BASE_FRONT_POSE_PROMPT, POSE_FRONT)
        check("hair only in BALD", prompt.count("hair"), 1)
        check("no palms clause", "palms" in prompt, False)
        check("no framing sentence", "soles of the feet" in prompt, False)
        check("no ears clause", "ears" in prompt, False)
        check("negative", negative, NEGATIVE)

        print("[3] back")
        prompt, negative = base_body.base_prompt(name, "back", profile=stored)
        check("back prompt", prompt, VIEW_BACK)
        check("back: no block", base_body.base_character(name, "back", profile=stored), None)
        check("back negative", negative, NEGATIVE)

        print("[4] left / right")
        prompt, _ = base_body.base_prompt(name, "left", profile=stored)
        check("left prompt", prompt, VIEW_LEFT)
        prompt, _ = base_body.base_prompt(name, "right", profile=stored)
        check("right prompt", prompt, VIEW_RIGHT)
        check("sides: no block", {v: base_body.base_character(name, v, profile=stored) for v in ("left", "right")},
              {"left": None, "right": None})
        check("views", base_body.BASE_VIEWS, ("front", "back", "left", "right"))
        check("use cases", base_body.BASE_USE_CASES,
              {"front": "base_front", "back": "base_view_back", "left": "base_view_side",
               "right": "base_view_side"})

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

        print("[7] admin pose overrides")
        # The admin overrides are read through model_refs._cfg — patched for
        # this section only (the config module has no in-memory setter).
        from app.core import model_refs
        real_cfg = model_refs._cfg
        overrides = {"tpose_prompt": "custom pose, arms down"}
        model_refs._cfg = lambda key, default=None: overrides.get(key) or real_cfg(key, default)
        try:
            check("front ignores tpose_prompt", base_body.base_prompt(name, "front", profile=stored)[0],
                  ", ".join([POSE_FRONT, BALD, BODY]))
            check("signature unchanged", base_body.base_signature(name, profile=stored), sig)
            overrides["tpose_back_prompt"] = "custom back pose, arms down, hair tied back"
            check("base back ignores the override", base_body.base_prompt(name, "back", profile=stored)[0],
                  VIEW_BACK)
            check("signature still unchanged", base_body.base_signature(name, profile=stored), sig)
            check("draft follows the override", base_body.draft_prompt(name, "back", profile=stored)[0],
                  ", ".join(["custom back pose, arms down", BALD_BACK, OUTFIT]))
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

        print("[10] base_body_prompt")
        specs = {s.id: s for s in slots_for_character(name, profile=stored)}
        check("parsed + stripped", specs["tail"].base_body_prompt, "{length} tail")
        check("default empty", (specs["marking"].base_body_prompt, specs["skin"].base_body_prompt), ("", ""))
        long_tail = json.loads(json.dumps(stored))
        long_tail["body_slots"]["tail"] = {"length": "long"}
        check("long tail appearance", base_body.base_appearance(name, profile=long_tail),
              APPEARANCE + ", long tail")
        check("front block ends with it",
              base_body.base_character(name, "front", profile=long_tail).endswith(", long tail"), True)
        check("front prompt without it", "long tail" in base_body.base_prompt(name, "front", profile=long_tail)[0],
              False)
        sig_none = base_body.base_signature(name, profile=stored)
        sig_long = base_body.base_signature(name, profile=long_tail)
        check("value changes signature", sig_long != sig_none, True)
        short_tail = json.loads(json.dumps(stored))
        short_tail["body_slots"]["tail"] = {"length": "short"}
        check("short tail appearance", base_body.base_appearance(name, profile=short_tail),
              APPEARANCE + ", short tail")
        check("short vs long signature", base_body.base_signature(name, profile=short_tail)
              not in (sig_none, sig_long), True)
        male_tail = dict(long_tail, gender="male")
        check("male: spot then tail",
              base_body.base_appearance(name, profile=male_tail).endswith(", pale spot, long tail"), True)

        print("[11] back draft")
        draft_want = ", ".join([POSE_BACK, BALD_BACK, OUTFIT])
        prompt, negative = base_body.draft_prompt(name, "back", profile=stored)
        check("draft prompt", prompt, draft_want)
        check("draft block", base_body.draft_character(name, "back", profile=stored), "sfw, " + APPEARANCE_BACK)
        check("draft negative", negative, HAIR_NEG + ", detailed anatomy, " + POSE_NEG + ", visible marking")
        prompt, _ = base_body.draft_prompt(name, "back", profile=long_tail)
        block = base_body.draft_character(name, "back", profile=long_tail)
        check("draft drops base_body_prompt", (prompt, block), (draft_want, "sfw, " + APPEARANCE_BACK))
        check("no 'no clothing' in the draft", "no clothing" in block + prompt, False)
        check("no tail, no mannequin", ("long tail" in block + prompt, "mannequin" in block + prompt), (False, False))

        print("[12] final prompt")
        target = {"template": "human-default", "gender": "female", "age": 26, "height": 168,
                  "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                 "build": {"type": "athletic"},
                                 "frag_a": {"text": "slot fragment a"}, "frag_b": {"text": "slot fragment b"}}}
        check("create Target", save_character_profile("Target", target, create_new=True), True)
        target = get_character_profile("Target")
        t_appearance = ("female, 26 years old, blue eyes, light skin, average height, athletic build, "
                        "slot fragment a, slot fragment b")
        check("Target appearance", base_body.base_appearance("Target", profile=target), t_appearance)
        front_block = base_body.base_character("Target", "front", profile=target)
        front_final = final_prompt(config, "base_front", "natural", front_block,
                                   base_body.base_prompt("Target", "front", profile=target)[0])
        check("front final == TARGET", front_final, TARGET)
        check("block right after the subject", front_final.startswith(SUBJECT + ", sfw, no clothing, female"), True)
        check("pose right after the style", ", sharp focus, standing upright facing the camera" in front_final, True)
        for view, want in (("back", VIEW_BACK), ("left", VIEW_LEFT), ("right", VIEW_RIGHT)):
            for family in ("natural", "keywords"):
                final = final_prompt(config, base_body.BASE_USE_CASES[view], family,
                                     base_body.base_character("Target", view, profile=target),
                                     base_body.base_prompt("Target", view, profile=target)[0])
                check(f"{view}/{family} final", final, want)
        draft_final = final_prompt(config, "base_back", "natural",
                                   base_body.draft_character("Target", "back", profile=target),
                                   base_body.draft_prompt("Target", "back", profile=target)[0])
        check("draft final", draft_final.startswith(SUBJECT + ", sfw, female, 26 years old, light skin, average "
                                                    "height, athletic build, shown from head to toe")
              and draft_final.endswith(", ".join([POSE_BACK, BALD_BACK, OUTFIT])), True)
        kw = config.get_use_case_prompts("base_front", "sdxl", clothed=False, character=front_block)["prompt_style"]
        check("keywords: block after the subject", kw.startswith(
            "render of a realistic 3D character model, lifelike skin textures, " + front_block + ", full body view"),
            True)
        check("keywords: feet after head to toe", ", head to toe, " + FEET + ", full arm span" in kw, True)
        check("natural: feet after the background", "against a plain neutral background, " + FEET + ", the full "
              "arm span" in front_final, True)
        for uc in ("base_front", "base_back", "base_side", "base_view_back", "base_view_side"):
            for family in ("natural", "keywords"):
                style = config.get_use_case_prompts(uc, family, clothed=False)["prompt_style"]
                check(f"{uc}/{family}: no raw slot without a block",
                      ("{character}" in style, ", ," in style), (False, False))
                check(f"{uc}/{family}: feet clause only on the front", FEET in style, uc == "base_front")
                if uc.startswith("base_view_"):
                    check(f"{uc}/{family}: empty style", style, "")
        fill, join = config.fill_character_slot, config.join_style_prompt
        check("no block, no slot", fill("a, b", None), "a, b")
        check("slot without block", fill("a, {character}, b", None), "a, b")
        check("slot with empty block", fill("a, {character}, b", ""), "a, b")
        check("block without slot opens the style", fill("a, b", "blk"), "blk, a, b")
        check("block in slot", fill("a, {character}, b", "blk"), "a, blk, b")
        check("join without block", join("style", "prompt", None), "style prompt")
        check("join with block", join("style", "prompt", "blk"), "style, prompt")

        print("[13] old T-pose path unchanged (vs " + BEFORE + ")")
        import types
        old_cfg = types.ModuleType("config_" + BEFORE)
        old_cfg.__file__ = "config_" + BEFORE + ".py"
        exec(compile(old_source("app/core/config.py"), old_cfg.__file__, "exec"), old_cfg.__dict__)
        old_ucs = sorted(old_cfg._DEFAULT_IMAGE_USE_CASES)
        check("old use cases are all still shipped", set(old_ucs) <= set(config._DEFAULT_IMAGE_USE_CASES), True)
        check("new use cases are additions",
              sorted(set(config._DEFAULT_IMAGE_USE_CASES) - set(old_ucs)),
              ["base_back", "base_front", "base_side", "base_view_back", "base_view_side",
               "footwear_source"])
        diffs = [(uc, fam, clothed) for uc in old_ucs for fam in ("natural", "keywords") for clothed in (True, False)
                 if old_cfg.get_use_case_prompts(uc, fam, clothed=clothed)
                 != config.get_use_case_prompts(uc, fam, clothed=clothed)]
        check("every old use case resolves byte-identically", diffs, [])
        import ast
        tree = ast.parse(old_source("app/core/model_refs.py"))
        wanted = ("TPOSE_FRONT_HAIR_CLAUSE", "TPOSE_CHEST_HAIR_CLAUSE", "TPOSE_REFERENCE_HAIR_CLAUSE",
                  "TPOSE_PROMPT_DEFAULT", "TPOSE_BACK_PROMPT_DEFAULT", "TPOSE_SIDE_PROMPT_TEMPLATE",
                  "TPOSE_LEFT_PROMPT_DEFAULT", "TPOSE_RIGHT_PROMPT_DEFAULT")
        old_ns = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") in wanted for t in node.targets):
                exec(compile(ast.Module([node], []), "model_refs_" + BEFORE, "exec"), old_ns)
        check("old pose constants read", sorted(old_ns.keys() - {"__builtins__"}), sorted(wanted))
        check("T-pose pose texts unchanged", [old_ns[k] == getattr(model_refs, k) for k in wanted],
              [True] * len(wanted))
        style = config.get_use_case_prompts("tpose", "natural", clothed=False)["prompt_style"]
        old_style = old_cfg.get_use_case_prompts("tpose", "natural", clothed=False)["prompt_style"]
        tpose_prompt = model_refs.get_tpose_prompt()
        check("tpose join is the historic one", config.join_style_prompt(style, tpose_prompt, None),
              f"{old_style} {tpose_prompt}")

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
