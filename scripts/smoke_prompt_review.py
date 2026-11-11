#!/usr/bin/env python3
"""Prompt review 2026-11-11: the pins of the reworked image prompts and of the negative handling.

Usage:
    ./.venv/bin/python scripts/smoke_prompt_review.py

No server, no backend, no world: an empty throwaway storage so the config
module resolves the SHIPPED use-case styles. Every expectation below is
derived by hand from the constants (word positions counted on the text as
written, 1-based, split on whitespace).

[1] Negative handling (app/imagegen/negation_fold.py, app/imagegen/occasions.py,
    app/imagegen/base.py).
    negative_mode: "yes" -> send; "no" -> fold; "ignored" -> ignored; "auto"
    with a natural family -> fold, with a keywords family -> send;
    backend_supports_negative("ignored") is False (nothing reaches the engine).
    folds_negative is False for every mesh-input occasion and the two edit
    occasions (tpose, tpose_view, base_front, base_view, outfit_front,
    outfit_back_draft, outfit_back, outfit_side_draft, outfit_side,
    garment_view, footwear_empty) and True for photo, profile, "" and an
    unknown id.
    ImageBackend.generate with a stub engine, prompt "p", negative "a, b":
      setting "ignored"            -> engine gets ("p", "")           (dropped)
      setting "no", occasion photo -> engine gets ("p. No a, no b.", "") (folded, natural family)
      setting "no", occasion base_view -> engine gets ("p", "")        (dropped, no fold)
      setting "yes", occasion base_view -> engine gets ("p", "a, b")   (sent)
    The Venice case that broke (review): the 27-word base view sentence with
    the negative _NEG_TPOSE_BACK + BASE_NEGATIVE (246 words with a pack's slot
    negatives in the log, 346 words after the fold) would fold to more than
    300 words — with the no-fold rule it stays 27 words.
[2] Reference wording (prompt_adapters.reference_wording): on a model whose
    id contains "p-h3" the ordinals become <Picture N> ("edit the first image
    with the clothes from the second image" -> "edit <Picture 1> with the
    clothes from <Picture 2>", "the reference image" -> "<Picture 1>"); on
    "Qwen2.1-Turbo" the text is unchanged.
[3] Style join: join_style_prompt("style", "prompt", None) == "style, prompt"
    (the historic single space is gone).
[4] Base front: the natural style of use case base_front with the block
    "BLOCK" has "{character}" filled at word 16 ("a full-body render of the
    character as a realistic 3D figure with lifelike skin textures" is 15
    words); the keywords style at word 11 ("render of a realistic 3D
    character model, lifelike skin textures" is 10 words). The natural style
    names "lighting" once and neither "relit" nor "uniform illumination".
    base_body.BALD_HEAD == "completely bald with a smooth bare scalp",
    BODY_TEXT == "a smooth featureless mannequin-like unclothed body with
    plain smooth skin", BASE_BLOCK_HEAD == "sfw"; none of the three contains
    "no " or "without". model_refs.BASE_FRONT_POSE_PROMPT is 40 words.
[5] Dressed front: DRESS_USE_CASE == "outfit_edit", whose style and negative
    are empty in both families; base_body._edit_prompt("front", "they now
    wear a red dress") starts with "Keep the image exactly as it is" and
    its outfit text starts at word 29 (DRESS_KEEP is 24 words, "Only change
    their clothing:" 4).
[6] Drafts: DRAFT_USE_CASES == {back: base_view_back, left: base_view_side,
    right: base_view_side}; DRAFT_PROMPTS["back"] filled with
    DRAFT_OUTFIT_TEXT: 47 words (17 + 20 + 10), starts with "The same person
    turned around", the outfit clause starts at word 18 ("The same person
    turned around, seen directly from behind, back view, same A-pose, same
    framing, completely bald," is 17 words), ends with "in the frame."; a trailing
    full stop of the outfit text is dropped. garment_clothing.DRAFT with
    fragment "a red dress" reads "wearing only a red dress exactly as on the
    person in the reference image, the same length, cut and colour, and
    nothing else".
[7] Ghosts: garment_clothing.GHOST with noun "red dress": "position" is word
    9 and "width" word 11 of 49, no "no " in it; garment_hair._GHOST["front"]
    starts "Keep the hair exactly as it is: the same position, outer outline,
    width", contains neither "inner side" nor "no "; the back ends "seen
    from behind.". garment_hair.length insertion: the front with length_t ->
    "Keep the hair exactly as it is: …, the same background. The hair ends
    <where>. Remove the person …" (sentence 2).
[8] Face view: the face_view style is "" in both families;
    FACE_VIEW_PROMPT_DEFAULT is at most 90 words, "completely bald" starts at
    word 16 ("a realistic 3D portrait of the head only of the same person as
    the reference," is 15 words), "relit" and "equally bright" in it, "NOT"
    not in it.
[9] Profile: get_use_case_prompts("profile", "qwen", character="BLOCK")
    ["prompt_style"] starts with the shipped subject sentence
    "a photorealistic portrait, soft even lighting, sharp focus, BLOCK, head
    and neck only"; the part after BLOCK contains no "no " and no "without";
    with character=None the slot is gone and the rules follow the style.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def words(text):
    return text.split()


def word_at(text, needle):
    """1-based word index at which ``needle`` starts (-1 when absent)."""
    i = text.find(needle)
    return -1 if i < 0 else len(text[:i].split()) + 1


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="prompt-review-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.get_config_path().write_text(json.dumps({}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")

        print("[1] negative handling")
        from app.imagegen.negation_fold import backend_supports_negative, negative_mode
        from app.imagegen.occasions import NO_FOLD_OCCASIONS, folds_negative
        check("yes -> send", negative_mode("yes"), "send")
        check("no -> fold", negative_mode("no"), "fold")
        check("ignored -> ignored", negative_mode("ignored"), "ignored")
        check("auto natural -> fold", negative_mode("auto", "natural", "Qwen2.1-Turbo"), "fold")
        check("auto keywords -> send", negative_mode("auto", "keywords", "SD1.5"), "send")
        check("ignored never reaches the engine", backend_supports_negative("ignored", "natural"), False)
        pipeline = ("tpose", "tpose_view", "base_front", "base_view", "outfit_front", "outfit_back_draft",
                    "outfit_back", "outfit_side_draft", "outfit_side", "garment_view", "footwear_empty")
        check("no fold on the pipeline occasions", [folds_negative(o) for o in pipeline], [False] * len(pipeline))
        check("NO_FOLD_OCCASIONS is exactly that set", sorted(NO_FOLD_OCCASIONS), sorted(pipeline))
        check("fold elsewhere", [folds_negative(o) for o in ("photo", "profile", "", "unknown")], [True] * 4)

        from app.imagegen.base import ImageBackend

        class Stub(ImageBackend):
            def __init__(self, setting):
                super().__init__(name="stub", api_url="http://stub", cost=0.0, api_type="openai_diffusion",
                                 env_prefix="STUB_")
                self.negative_prompt_setting = setting
                self.image_family = "natural"
                self.model = "Qwen2.1-Turbo"
                self.calls = []

            def _generate(self, prompt, negative_prompt, params):
                self.calls.append((prompt, negative_prompt))
                return []

            def check_availability(self):
                return True

        def run(setting, occasion):
            b = Stub(setting)
            b.generate("p", "a, b", {"occasion": occasion}, log_meta=None)
            return b.calls[-1]
        check("ignored: dropped", run("ignored", "photo"), ("p", ""))
        check("no + photo: folded", run("no", "photo"), ("p. No a, no b.", ""))
        check("no + base_view: dropped", run("no", "base_view"), ("p", ""))
        check("yes + base_view: sent", run("yes", "base_view"), ("p", "a, b"))
        from app.core import base_body
        from app.core.config import _NEG_TPOSE_BACK
        b = Stub("no")
        neg = _NEG_TPOSE_BACK + ", " + base_body.BASE_NEGATIVE
        b.generate(base_body.BASE_VIEW_PROMPTS["back"], neg, {"occasion": "base_view"}, log_meta=None)
        check("the Venice case stays 27 words", len(words(b.calls[-1][0])), 27)
        from app.imagegen.negation_fold import fold_negatives
        folded, items = fold_negatives(base_body.BASE_VIEW_PROMPTS["back"], neg, "natural")
        check("a fold would have made it >= 300 words", len(words(folded)) >= 300, True)

        print("[2] reference wording")
        from app.core.prompt_adapters import reference_wording
        check("P-H3 fit", reference_wording(base_body.FIT_PROMPT, "P-H3-Image"),
              "edit <Picture 1> with the clothes from <Picture 2>")
        check("P-H3 reference image", reference_wording("as in the reference image, the third image", "p-h3-x"),
              "as in <Picture 1>, <Picture 3>")
        check("Qwen untouched", reference_wording(base_body.FIT_PROMPT, "Qwen2.1-Turbo"), base_body.FIT_PROMPT)

        print("[3] style join")
        check("comma join", config.join_style_prompt("style", "prompt", None), "style, prompt")
        check("comma join with block", config.join_style_prompt("style", "prompt", "blk"), "style, prompt")

        print("[4] base front")
        nat = config.get_use_case_prompts("base_front", "qwen", clothed=False, character="BLOCK")["prompt_style"]
        kw = config.get_use_case_prompts("base_front", "z_image", clothed=False, character="BLOCK")["prompt_style"]
        check("natural: block at word 16", word_at(nat, "BLOCK"), 16)
        check("keywords: block at word 11", word_at(kw, "BLOCK"), 11)
        check("natural: lighting once, no relit, no uniform illumination",
              (nat.count("lighting"), "relit" in nat, "uniform illumination" in nat), (1, False, False))
        check("BALD_HEAD", base_body.BALD_HEAD, "completely bald with a smooth bare scalp")
        check("BODY_TEXT", base_body.BODY_TEXT,
              "a smooth featureless mannequin-like unclothed body with plain smooth skin")
        check("BASE_BLOCK_HEAD", base_body.BASE_BLOCK_HEAD, "sfw")
        check("no negation in the block words",
              any(w in t for t in (base_body.BALD_HEAD, base_body.BODY_TEXT, base_body.BASE_BLOCK_HEAD)
                  for w in ("no ", "without")), False)
        from app.core import model_refs
        check("pose text 40 words", len(words(model_refs.BASE_FRONT_POSE_PROMPT)), 40)

        print("[5] dressed front")
        check("use case", base_body.DRESS_USE_CASE, "outfit_edit")
        for fam in ("qwen", "z_image"):
            ucp = config.get_use_case_prompts("outfit_edit", fam)
            check(f"outfit_edit/{fam} empty", (ucp["prompt_style"], ucp["prompt_negative"]), ("", ""))
        edit = base_body._edit_prompt("front", "they now wear a red dress")
        check("starts with Keep", edit.startswith("Keep the image exactly as it is"), True)
        check("outfit at word 29", word_at(edit, "they now wear a red dress"), 29)

        print("[6] drafts")
        check("draft use cases", base_body.DRAFT_USE_CASES,
              {"back": "base_view_back", "left": "base_view_side", "right": "base_view_side"})
        draft = base_body.DRAFT_PROMPTS["back"].format(outfit=base_body.DRAFT_OUTFIT_TEXT)
        check("47 words", len(words(draft)), 47)
        check("starts with the turn", draft.startswith("The same person turned around"), True)
        check("outfit at word 18", word_at(draft, "wearing exactly the same outfit"), 18)
        check("ends with the frame", draft.endswith("in the frame."), True)
        profile = {"template": "", "gender": "female"}
        check("draft_prompt drops a trailing full stop",
              base_body.draft_prompt("Demo", "back", profile=profile, outfit_text="wearing a hat.")[0],
              base_body.DRAFT_PROMPTS["back"].format(outfit="wearing a hat"))
        from app.core import garment_clothing
        check("clothing DRAFT", garment_clothing.DRAFT.format(fragment="a red dress"),
              "wearing only a red dress exactly as on the person in the reference image, the same length, cut "
              "and colour, and nothing else")

        print("[7] ghosts")
        ghost = garment_clothing.GHOST.format(noun="red dress")
        check("position at word 9, width at word 11, 49 words",
              (word_at(ghost, "position"), word_at(ghost, "width"), len(words(ghost))), (9, 11, 49))
        check("no negation", "no " in ghost, False)
        from app.core import garment_hair
        front, back = garment_hair._GHOST["front"], garment_hair._GHOST["back"]
        check("hair front opening",
              front.startswith("Keep the hair exactly as it is: the same position, outer outline, width"), True)
        check("hair front: no inner side, no negation", ("inner side" in front, "no " in front), (False, False))
        check("hair back ends seen from behind", back.endswith("seen from behind."), True)
        keep, rest = front.split(". ", 1)
        check("length sentence slot", keep.endswith("the same background") and rest.startswith("Remove the person"),
              True)

        print("[8] face view")
        for fam in ("qwen", "z_image"):
            check(f"face_view/{fam} style empty", config.get_use_case_prompts("face_view", fam)["prompt_style"], "")
        face = model_refs.FACE_VIEW_PROMPT_DEFAULT
        check("<= 90 words", len(words(face)) <= 90, True)
        check("bald at word 16", word_at(face, "completely bald"), 16)
        check("relit + equally bright, no NOT", ("relit" in face, "equally bright" in face, "NOT" in face),
              (True, True, False))

        print("[9] profile")
        style = config.get_use_case_prompts("profile", "qwen", character="BLOCK")["prompt_style"]
        check("subject, block, rules",
              style.startswith("a photorealistic portrait, soft even lighting, sharp focus, BLOCK, head and neck only"),
              True)
        after = style.split("BLOCK, ", 1)[1]
        check("rules positive", ("no " in after, "without" in after), (False, False))
        bare = config.get_use_case_prompts("profile", "qwen")["prompt_style"]
        check("no block: slot removed", ("{character}" in bare, bare.startswith(
            "a photorealistic portrait, soft even lighting, sharp focus, head and neck only")), (False, True))

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
