#!/usr/bin/env python3
"""Smoke run: a render's person reference falls back to the closest variant
of the SAME outfit before it falls back to the profile portrait.

Symptom (2026-10-24): a scene photo of the avatar (undressed, on the bed)
sent the profile portrait — a head shot in a grey T-shirt — as the person
reference, because no expression variant existed yet for the avatar's
current mood + pose. A variant of the very same outfit (another pose) was on
disk and showed the body as it actually was.

The chain in ``PromptBuilder._resolve_person_ref_image`` is now:
  1) the exact variant (mood + pose + outfit + state)
  1b) ``find_same_outfit_expression`` — same outfit, closest moment
  2) the profile image

Expectations derived by hand from the rule in ``find_same_outfit_expression``:
"same outfit" = re-keying the variant with the CURRENT outfit reproduces its
file stem (``variant_stem``); ranking = equal state, then equal pose key,
then equal expression key, then the newest file.

  outfits:  A = {"top": "smoke-shirt"}    B = {"top": "smoke-coat"}
  variants on disk (file stems via variant_stem, the cache-key rule):
    V1  A  neutral  standing  state ""        mtime 1000
    V2  A  happy    lying     state ""        mtime 2000
    V3  B  happy    kneeling  state ""        mtime 3000  (other outfit)
    V4  A  happy    kneeling  state "deadbeef" mtime 4000 (other state)
    V5  A  sidecar without expression_key     mtime 5000  (legacy)
  The character's live state fingerprint is "" (no image modifier active).

  [1] A, happy,   kneeling -> V2   (V3 matches pose+expression but is outfit
                                     B; V4 matches both but its state differs;
                                     V2 has the expression)
  [2] A, neutral, lying    -> V2   (pose beats expression: V1 has neutral)
  [3] A, neutral, sitting  -> V1   (no pose match, expression decides)
  [4] A, sad,     sitting  -> V2   (nothing matches, the newer file; V4 is
                                     newer still but loses on state, V5 is
                                     never a candidate)
  [5] outfit C (nothing rendered)  -> None
  [6] the chain: A, happy, kneeling, profile image set -> V2's file
  [7] the chain: outfit C            -> the profile image (unchanged rung 2)
  [8] the chain: equipped state unreadable -> the profile image, NOT the
      variant of "nothing equipped"

Runs against a THROWAWAY storage directory — it never touches a real world.

Usage:  ./.venv/bin/python scripts/smoke_expression_same_outfit.py
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="same-outfit-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="same-outfit-clips-")

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import config, db  # noqa: E402

config.load(STORAGE / "config.json")
db.init_schema()

from app.core import embedding  # noqa: E402
from app.core import expression_regen as er  # noqa: E402
from app.core import prompt_builder as pb  # noqa: E402
from app.core.model_refs import outfit_signature_raw  # noqa: E402
from app.models import inventory  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_images_dir, save_character_profile)

embedding.embed = lambda text: None

FAILURES = []
CHECKED = 0
CHAR = "Smoke Avatar"
A = {"top": "smoke-shirt"}
B = {"top": "smoke-coat"}
C = {"top": "smoke-cloak"}


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def put_variant(label, pieces, expression, pose, state, mtime, legacy=False):
    """A variant image + sidecar under the stem the cache-key rule gives."""
    stem = er.variant_stem(CHAR, expression, er._canonical_pose_key(pose),
                           outfit_signature_raw(pieces, [], CHAR), state)
    out = er._get_expressions_dir(CHAR)
    img = out / f"{stem}.png"
    img.write_bytes(b"fake png")
    meta = {"label": label, "equipped_pieces": pieces, "equipped_items": [],
            "pose_key": pose, "state_fingerprint": state}
    if not legacy:
        meta["expression_key"] = expression
    img.with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")
    os.utime(img, (mtime, mtime))
    return img.name


def nearest(pieces, mood, pose):
    p = er.find_same_outfit_expression(CHAR, mood, pose, pieces, [])
    return p.name if p else None


def main() -> int:
    save_character_profile(CHAR, {"character_name": CHAR,
                                  "template": "human-roleplay"}, create_new=True)
    er._get_expressions_dir(CHAR).mkdir(parents=True, exist_ok=True)
    happy = er.resolve_expression_key("happy")
    neutral = er.resolve_expression_key("")
    sad = er.resolve_expression_key("sad")
    check("precondition: happy, neutral and sad are distinct catalog keys",
          len({happy, neutral, sad}), 3)
    for pose in ("standing", "lying", "kneeling", "sitting"):
        check(f"precondition: '{pose}' is a pose catalog key",
              er._canonical_pose_key(pose), pose)

    v1 = put_variant("V1", A, neutral, "standing", "", 1000)
    v2 = put_variant("V2", A, happy, "lying", "", 2000)
    put_variant("V3", B, happy, "kneeling", "", 3000)
    put_variant("V4", A, happy, "kneeling", "deadbeef", 4000)
    put_variant("V5", A, happy, "sitting", "", 5000, legacy=True)

    print("\n[1] other outfit and other state never win")
    check("A happy kneeling", nearest(A, "happy", "kneeling"), v2)
    print("\n[2] pose beats expression")
    check("A neutral lying", nearest(A, "", "lying"), v2)
    print("\n[3] expression decides without a pose match")
    check("A neutral sitting", nearest(A, "", "sitting"), v1)
    print("\n[4] newest file decides when nothing matches")
    check("A sad sitting", nearest(A, "sad", "sitting"), v2)
    print("\n[5] an outfit without any variant")
    check("C", nearest(C, "happy", "kneeling"), None)

    # The chain in the prompt builder, with the live state stubbed.
    images = get_character_images_dir(CHAR)
    images.mkdir(parents=True, exist_ok=True)
    (images / "profile.png").write_bytes(b"fake png")
    pb.get_character_profile_image = lambda name: "profile.png"
    pb.get_character_current_feeling = lambda name: "happy"
    pb.get_effective_pose_key = lambda name: "kneeling"
    inventory.get_equipped_items = lambda name: []
    person = pb.Person(name=CHAR, appearance="", gender="")

    def ref():
        return Path(pb.PromptBuilder(CHAR)._resolve_person_ref_image(person)).name

    print("\n[6] the chain takes the same-outfit variant")
    inventory.get_equipped_pieces = lambda name: dict(A)
    check("chain, outfit A", ref(), v2)

    print("\n[7] no variant of this outfit -> profile image")
    inventory.get_equipped_pieces = lambda name: dict(C)
    check("chain, outfit C", ref(), "profile.png")

    print("\n[8] unreadable equipped state -> profile image")

    def broken(name):
        raise RuntimeError("inventory unreadable")
    inventory.get_equipped_pieces = broken
    check("chain, broken inventory", ref(), "profile.png")

    print(f"\n{CHECKED} checks, {len(FAILURES)} deviation(s)")
    if FAILURES:
        print("FAILED: " + ", ".join(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
        shutil.rmtree(os.environ["ANIMATION_CLIPS_DIR"], ignore_errors=True)
