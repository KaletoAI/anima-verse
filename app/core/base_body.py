"""Base body — the bald, unclothed A-pose figure of a humanoid character.

A humanoid character on the ``base_body`` model pipeline (profile field
``model_pipeline: "base_body"``) gets ONE base body: four A-pose views
(front/back/left/right) of a bald, anatomically neutral figure, rendered from
the character's profile image, and one model built from them. Outfits are
painted onto that body later (spec
``docs/superpowers/specs/2026-11-08-base-body-outfits-design.md`` § A).

This module holds only the pure parts: the description, the view prompts with
their negative, and the base signature that keys every stored base image and
model. Rendering lives elsewhere.

What describes the body:

* gender and age through the template's ``character_appearance`` replacement
  tokens, in the ``"{gender}, {age} years old"`` phrasing World-Dev asks for;
* the ``always`` fragments of the body slots a species package flags
  ``base_body: true`` (human: eyes, skin, build — the build fragment carries
  the height phrase). Never the free-text ``character_appearance`` (it names
  clothes and hair), never hair, never a slot without the flag — anatomy
  packs stay out unless they opt in.

The pose texts are the mesh-input A-pose texts of ``app/core/model_refs.py``
(admin overrides included) with their hair clauses taken out: a bald figure
has no hair to keep off the chest or to match to the reference.
"""
import hashlib
import json
import re
from typing import Any, Dict, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("base_body")

BASE_VIEWS = ("front", "back", "left", "right")
# Part of the signature: bump when the composition below changes in a way
# that must re-render every base body.
BASE_BODY_VERSION = 1

# Framing, head and body layers (wording verified in the S1 spike,
# claude-out/s1-base-body/src/bald_tpose.py).
FULL_FRAMING = ("full body shot from the top of the head to the soles of the feet, the entire figure inside the "
                "frame with empty margin above the head and below the feet")
BALD_HEAD = ("completely bald, smooth clean-shaven head with no hair at all, the bare scalp and the bare back of "
             "the head fully visible, the ears fully visible, natural eyebrows")
BODY_TEXT = "a smooth, featureless mannequin-like body without anatomical detail, no clothing"

HAIR_NEGATIVE = ("hair, long hair, short hair, ponytail, braid, bun, fringe, bangs, wig, headscarf, hat, hood, "
                 "stubble on the scalp, hair on the shoulders, hair on the back")
BODY_NEGATIVE = "clothing, underwear, jewellery, detailed anatomy"
POSE_NEGATIVE = ("hands touching body, fists, curled fingers, fused fingers, mitten hands, cropped feet, "
                 "feet cut off, cropped legs, close-up, portrait crop")
BASE_NEGATIVE = ", ".join((HAIR_NEGATIVE, BODY_NEGATIVE, POSE_NEGATIVE))

_HAIR_RE = re.compile(r"\bhair", re.IGNORECASE)


def _profile_of(character_name: str, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if profile is not None:
        return profile
    from app.models.character import get_character_profile
    return get_character_profile(character_name) or {}


def _without_hair(text: str) -> str:
    """The pose text without its hair clauses. The shipped clauses go by exact
    text; an admin override that words hair differently loses every comma
    clause that mentions hair, and one without any keeps everything."""
    from app.core.model_refs import TPOSE_HAIR_CLAUSES
    for clause in TPOSE_HAIR_CLAUSES:
        text = text.replace(clause, "")
    segments = [seg.strip() for seg in (text or "").split(",")]
    return ", ".join(seg for seg in segments if seg and not _HAIR_RE.search(seg))


def _identity_words(profile: Dict[str, Any]) -> str:
    """Gender and age as the character's template renders them into the
    appearance tokens ({gender} -> "female", {age} -> "30")."""
    from app.models.character_template import build_replacement_map, get_template
    template = get_template(profile.get("template", "")) if profile.get("template") else None
    if not template:
        return ""
    tokens = build_replacement_map(template, profile, "character_appearance")
    parts = []
    if tokens.get("gender"):
        parts.append(tokens["gender"])
    if tokens.get("age"):
        parts.append(f"{tokens['age']} years old")
    return ", ".join(parts)


def base_appearance(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> str:
    """Gender/age words + height phrase + the ``always`` fragments of the
    character's body slots flagged ``base_body: true``, in slot order."""
    profile = _profile_of(character_name, profile)
    from app.core.body_slots import prompt_fragments
    from app.core.height import height_phrase
    fragments = prompt_fragments(character_name, profile=profile, base_body=True)["general"]
    parts = []
    identity = _identity_words(profile)
    if identity:
        parts.append(identity)
    # The human build slot carries the height ("{height}, {type} build"); only
    # when no flagged fragment rendered it does the phrase stand on its own.
    height = height_phrase(profile, character_name)
    if height and not any(height in fragment for fragment in fragments):
        parts.append(height)
    parts.extend(fragments)
    return ", ".join(parts)


def _pose_text(view: str) -> str:
    from app.core.model_refs import get_tpose_prompt, get_tpose_view_prompt
    return _without_hair(get_tpose_prompt() if view == "front" else get_tpose_view_prompt(view))


def base_prompt(character_name: str, view: str, *,
                profile: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """``(prompt, negative)`` of one base-body view. Front and the extra
    views share the framing and body layers; a back view drops every facial
    segment of them (``prompt_builder.strip_face_terms``), like the outfit
    back view does — a facial word pulls the head around to the camera."""
    if view not in BASE_VIEWS:
        raise ValueError(f"unknown base-body view: {view!r}")
    profile = _profile_of(character_name, profile)
    body = ", ".join(p for p in (BALD_HEAD, BODY_TEXT, base_appearance(character_name, profile=profile)) if p)
    if view == "back":
        from app.core.prompt_builder import strip_face_terms
        body = strip_face_terms(body)
    prompt = ", ".join(p for p in (_pose_text(view), FULL_FRAMING, body) if p)
    return prompt, BASE_NEGATIVE


def base_signature(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> str:
    """``"base" + 8 hex`` over everything that shapes the base body: the four
    view prompts and negatives, the current profile image (file name and
    size) and ``BASE_BODY_VERSION``."""
    profile = _profile_of(character_name, profile)
    from app.core.model_refs import current_profile_image
    image = current_profile_image(character_name, profile=profile)
    try:
        image_id = [image.name, image.stat().st_size] if image else ["", 0]
    except OSError:
        image_id = ["", 0]
    payload = {
        "version": BASE_BODY_VERSION,
        "views": {view: list(base_prompt(character_name, view, profile=profile)) for view in BASE_VIEWS},
        "profile_image": image_id,
    }
    digest = hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return "base" + digest[:8]


def is_base_pipeline(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the character is on the base-body pipeline: the profile switch
    is set AND the character is humanoid (an animal never is)."""
    profile = _profile_of(character_name, profile)
    if profile.get("model_pipeline") != "base_body":
        return False
    from app.core.model_refs import is_humanoid
    return bool(is_humanoid(character_name, profile=profile))
