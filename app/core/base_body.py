"""Base body — the bald, unclothed A-pose figure of a humanoid character.

Every humanoid character is on the ``base_body`` model pipeline
(``is_base_pipeline``; an animal never is) and gets ONE base body: four A-pose views
(front/back/left/right) of a bald, unclothed figure, rendered from
the character's profile image, and one model built from them. Outfits are
painted onto that body later (spec
``docs/superpowers/specs/2026-11-08-base-body-outfits-design.md`` § A).

This module holds the description, the view prompts with their negative, the
base signature that keys every stored base image and model, the rendering of
the four views (``generate_base_images``, the front through the hand-pose
gate of ``base_body_gates``), the rigged base model built from
them (``generate_base_model``) and the UI info (``base_info``). A humanoid
without a base body yet keeps serving the model it has until a manual Build
makes the base body (``figure_build``, ruling 8a: automatic Builds never do).

Outfits (spec § B, phase 3): every outfit combination of a character on the
pipeline gets two DRESSED images (``dressed_views``; four with the world
setting ``base_body.dressed_side_views``) — the front an edit of the base
front, the back (and the sides) a draft from the dressed front composited
onto the base view on the CPU (``generate_dressed_images``, ``dress_prompt`` /
``draft_prompt``, ``view_composite``) stored as the usual ``tpose[_<view>]_<sig>``
refs — and an
outfit model that is the rigged base
with the outfit painted on by the local GLBBodyRetexture worker
(``build_outfit_model``, base colour swapped by ``replace_base_color``).
A figure with a worn piece in the body stands on a MESHED SHAPE instead —
its own views (the plain body wearing the in-body pieces) meshed and rigged
through the old path's staged chain, one per shape key, the painted pieces
painted onto it (section "Meshed shapes": ``prepare_shape``, storage and
parent record; the figure itself is ``app/core/figure.py``).

What describes the body:

* gender and age through the template's ``character_appearance`` replacement
  tokens, in the ``"{gender}, {age} years old"`` phrasing World-Dev asks for;
* the ``always`` fragments of the body slots a species package flags
  ``base_body: true`` (human: eyes, skin, build — the build fragment carries
  the height phrase). Never the free-text ``character_appearance`` (it names
  clothes and hair), never hair, never a slot without the flag — anatomy
  packs stay out unless they opt in.

Hair (spec ``docs/superpowers/specs/2026-11-11-hair-from-body-design.md``;
hairstyles: plan 2026-11-12-unified-worn-pieces Task 13): the plain body is
the body of ONE hairstyle (``garment_hair.plain_hairstyle``). When its mode
is ``body`` the base is NOT bald — the views carry that hairstyle's text
(``hair_text``) where the bald head stood, the front keeps
the hair off the chest (``model_refs.TPOSE_FRONT_HAIR_CLAUSE``), hair that
falls behind the shoulders says so (``HAIR_BEHIND_SHOULDERS``), and the
negatives forbid headwear only (``HEADWEAR_NEGATIVE``). The outfit drafts and
the dressed edits keep that hair. Every other mode — and a character
without a hairstyle — keeps the bald wording byte for byte. The hairstyle is
not part of ``base_identity``: a mode change of the plain body's hairstyle
only changes ``prompt_fingerprint`` (the ``OLDER_PROMPTS`` note), never
renames a base; WEARING another hairstyle never touches the plain body — it
makes a body shape (``figure.shape_inputs`` ``hair``, D4) whose views are
the plain views edited to that hair (``dress_prompt(hair=…)``). A front
made as an EDIT of a picture never re-describes the hair it shows: it keeps
the face, the hair and the facial hair of the picture, and its edit views
take them from the front (Ruling A94, ``edit_character`` /
``base_prompt(picture=True)``).

The prompt layout (user directive 2026-11-09, "character details always
first"): the front's style (``base_front``) opens with its subject
clause, then its ``{character}`` slot takes the CHARACTER BLOCK
(``base_character``: the head, ``BODY_TEXT`` and ``base_appearance``), then the rest
of the style; the base prompt (``base_prompt``: pose, bald head, body text)
follows after a comma. The image service fills the slot
(``config.fill_character_slot``, payload key ``style_character``).

The pose texts: the front is ``model_refs.BASE_FRONT_POSE_PROMPT`` (the
A-pose front without the palms and hair clauses). Back/left/right are edits
of the front and carry ONE short sentence each (``BASE_VIEW_PROMPTS``), no
style and no character block (use cases ``base_view_back`` /
``base_view_side``; user test 2026-11-09: the long texts made Qwen invent
things). The outfit drafts (and an own-mesh piece's worn back draft) carry
the same kind of sentence (``DRAFT_PROMPTS``) under the empty styles of the
edit views (``DRAFT_USE_CASES``) — a view change that never names the
clothing (Ruling A29): the dressed front it is an edit of shows it.
"""
import hashlib
import json
import os
import re
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from app.core import view_facing
from app.core.log import get_logger

logger = get_logger("base_body")

BASE_VIEWS = ("front", "back", "left", "right")
# Part of the signature: bump when the composition below changes in a way
# that must re-render every base body.
BASE_BODY_VERSION = 2

# Head and body layers (wording from the S1 spike,
# claude-out/s1-base-body/src/bald_tpose.py, shortened by the user 2026-11-09:
# no framing sentence, no ears clause; shortened again in the prompt review
# of 2026-11-11 and moved INTO the character block, so the two clauses that
# shape the figure stand in the first 30 words of the base front instead of
# at word 167 and 191 of 199). Positive wording only — a CFG-free model
# draws what a negation names ("no hair", "without anatomical detail").
BALD_HEAD = "completely bald with a smooth bare scalp"
#: Natural skin: the spike text of 2026-11-12 10:50 (hub job 10c82251)
#: without its "fine natural body hair" — the bald/haired base must not name
#: hair. The earlier "smooth featureless" wording made every base front a
#: pale plastic doll (user report 2026-11-13). Ruling A74a (2026-11-14): the
#: body text no longer asks for a plain surface, and the block no longer
#: opens with a safe-content tag — the base front shows the body as the
#: character's description and the active packs' slots make it.
BODY_TEXT = "an unclothed body with realistic natural skin, visible pores, subtle skin tone variation, matte skin"
#: Use case (style, negative) per base view — their own, so the whole-body
#: T-pose path keeps "tpose" / "tpose_back" / "tpose_side" untouched. The
#: edit views' use cases carry no style: their whole prompt is the short
#: ``BASE_VIEW_PROMPTS`` text.
BASE_USE_CASES = {"front": "base_front", "back": "base_view_back", "left": "base_view_side",
                  "right": "base_view_side"}
#: Use case per two-step draft (back, left, right): the empty style of the
#: base edit views (``base_view_*``, keeping their view negatives) — a draft
#: is an edit of the dressed front and carries one short sentence
#: (``DRAFT_PROMPTS``), no style and no character block (review 2026-11-11).
DRAFT_USE_CASES = {"back": "base_view_back", "left": "base_view_side", "right": "base_view_side"}
#: The WHOLE prompt of a two-step draft per view (``draft_prompt``) — an
#: outfit's dressed back/side and an own-mesh piece's worn back alike.
#: Ruling A29 (user, 2026-11-13): a draft only CHANGES THE VIEW of the dressed
#: front it is an edit of, so it never names the clothing — no outfit text,
#: no ``prompt_fragment``, no piece name; the reference shows it. Naming it
#: made the model invent garments (Ylva's own-mesh blouse: "wearing only
#: cream off-shoulder linen blouse …" drew a skirt on one try and culottes on
#: another). The back is the user's validated sentence VERBATIM (the blouse
#: alone, bare legs); each side keeps that wording and only says its own
#: turn. ``scripts/smoke_view_prompts_no_clothing.py`` pins it.
DRAFT_PROMPTS = {
    "back": ("The same person turned around, seen directly from behind, back view, same A-pose, same "
             "framing, completely bald, exactly as on the person in the reference image, the same length, "
             "cut and colour, and nothing else, the whole figure from head to feet in the frame."),
    "left": ("The same person turned to a strict left side profile view, same A-pose, same framing, "
             "completely bald, exactly as on the person in the reference image, the same length, cut and "
             "colour, and nothing else, the whole figure from head to feet in the frame."),
    "right": ("The same person turned to a strict right side profile view, same A-pose, same framing, "
              "completely bald, exactly as on the person in the reference image, the same length, cut and "
              "colour, and nothing else, the whole figure from head to feet in the frame."),
}
#: The WHOLE prompt of each edit view of the base front (user test
#: 2026-11-09: the long pose texts and the style made Qwen invent things; a
#: short sentence that names the turn and keeps the rest from the front does
#: not). No character block, no style, no admin override — one text per view.
BASE_VIEW_PROMPTS = {
    "back": ("The same person turned around, seen directly from behind, back view, same A-pose, same "
             "framing, completely bald, the whole figure from head to feet in the frame."),
    "left": ("The same person turned to a strict left side profile view, same A-pose, same framing, "
             "completely bald, the whole figure from head to feet in the frame."),
    "right": ("The same person turned to a strict right side profile view, same A-pose, same framing, "
              "completely bald, the whole figure from head to feet in the frame."),
}

HAIR_NEGATIVE = ("hair, long hair, short hair, ponytail, braid, bun, fringe, bangs, wig, headscarf, hat, hood, "
                 "stubble on the scalp, hair on the shoulders, hair on the back")
#: Ruling A74a: no anatomy words — what a pack's slots describe is the pack's
#: business (``base_body_negative``), and the base front is no longer kept plain.
BODY_NEGATIVE = "clothing, underwear, jewellery"
POSE_NEGATIVE = ("hands touching body, fists, curled fingers, fused fingers, mitten hands, cropped feet, "
                 "feet cut off, cropped legs, close-up, portrait crop")
BASE_NEGATIVE = ", ".join((HAIR_NEGATIVE, BODY_NEGATIVE, POSE_NEGATIVE))

# Hair from the body mesh (module docstring "Hair"). The words of the bald
# head in BASE_VIEW_PROMPTS / DRAFT_PROMPTS that a haired edit replaces with
# the hair text and the reference clause.
_BALD_WORDS = "completely bald"
#: Said only of hair that falls behind the shoulders
#: (``garment_hair.hair_behind_shoulders``) — said to short hair, a direction
#: tempts the model into growing it (``model_refs``, 2026-10-25).
HAIR_BEHIND_SHOULDERS = "the hair falls behind the shoulders"
#: The hair negative of a haired base view: headwear only.
HEADWEAR_NEGATIVE = "hat, hood, headscarf, wig"
#: ``BASE_NEGATIVE`` of a haired base.
HAIRED_BASE_NEGATIVE = ", ".join((HEADWEAR_NEGATIVE, BODY_NEGATIVE, POSE_NEGATIVE))

# Ruling A94 (user, 2026-11-15: "the reference image has different hair than
# the front view"): a front that is an EDIT of a picture (``front_reference``
# method "reference") keeps the face, the hair and the facial hair FROM THAT
# PICTURE instead of re-describing them — the precedent of Ruling A29 for
# clothing. Rurik's front re-described his hair from the text ("short auburn
# hair, …"): the edit recoloured the hair, dropped the beard (nothing named
# it) and drifted the face. So the edit block (``edit_character``) names what
# stays (``picture_identity``) and, for hair in the body whose text is the
# Appearance's (``hair_from_picture`` — the picture shows that hair), never the
# hair text; the views of such a front (``base_prompt(picture=True)``) take
# the hair and the facial hair from the front they edit. Facial hair is
# Appearance text (the human ``facial_hair`` slot, a ``character_appearance``
# clause — ``garment_beard.has_facial_hair``), named only when the character
# has some: a named beard is a drawn beard. It stays in the body mesh (the base
# body keeps the beard; only the HairDeck input loses it, ``garment_beard``).
# A front made from text alone keeps every text of before, byte for byte.

#: What the front edit keeps from its picture, in naming order (``picture_identity``).
PICTURE_FACE, PICTURE_HAIR, PICTURE_FACIAL_HAIR = "face", "hair", "facial hair"
#: An edit view's hair of a base whose hair came from the picture: from the front, colour included.
VIEW_HAIR_FROM_REFERENCE = "the same hairstyle, hair length, hair volume and hair colour as the reference"
#: An edit view's facial hair of a base made from a picture, for a character with facial hair.
VIEW_FACIAL_HAIR_FROM_REFERENCE = "the same facial hair as the reference"
#: ``HAIR_NEGATIVE`` without its bare "hair" term: the head negative of a BALD
#: base made from a picture of a character with facial hair — the bare term
#: forbids the beard the picture shows.
FACIAL_HAIR_SAFE_HAIR_NEGATIVE = ("long hair, short hair, ponytail, braid, bun, fringe, bangs, wig, headscarf, hat, "
                                  "hood, stubble on the scalp, hair on the shoulders, hair on the back")


def picture_identity(*, hair: bool, facial_hair: bool) -> str:
    """The clause of a front edit that keeps the person of the picture:
    "the same face[, hair][ and facial hair] as the person in the picture"."""
    things = [PICTURE_FACE] + ([PICTURE_HAIR] if hair else []) + ([PICTURE_FACIAL_HAIR] if facial_hair else [])
    named = things[0] if len(things) == 1 else ", ".join(things[:-1]) + " and " + things[-1]
    return f"the same {named} as the person in the picture"


def has_facial_hair(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the character's Appearance names facial hair (``garment_beard.has_facial_hair``)."""
    from app.core import garment_beard
    return garment_beard.has_facial_hair(character_name, profile=_profile_of(character_name, profile))


def hair_from_picture(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether a picture edit takes the plain body's hair from the picture:
    the hair is in the body (``hair_text``) and its text is the Appearance's
    hair text (``garment_hair.appearance_hair_text``) — the hair the profile
    image and the full-body reference show. A plain hairstyle whose text was
    rewritten is no hair of the picture: its text is named as before."""
    from app.core import garment_hair
    profile = _profile_of(character_name, profile)
    hair = hair_text(character_name, profile=profile)
    return bool(hair) and hair == garment_hair.appearance_hair_text(character_name, profile=profile)

_HAIR_RE = re.compile(r"\bhair", re.IGNORECASE)
# The shape of ``base_signature`` — never an outfit signature (pure hex).
BASE_SIG_RE = re.compile(r"base[0-9a-f]{8}")


def is_base_signature(signature: Optional[str]) -> bool:
    """Whether a model/ref signature is a base-body one (by its shape)."""
    return bool(signature) and BASE_SIG_RE.fullmatch(signature) is not None


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


def base_appearance(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
                    base_fragments: bool = True) -> str:
    """Gender/age words + height phrase + the ``always`` fragments of the
    character's body slots flagged ``base_body: true``, in slot order, then
    the ``base_body_prompt`` texts of every slot that applies to the
    character (``body_slots.base_body_fragments``, flag irrelevant) — left
    out with ``base_fragments=False`` (they describe the undressed body)."""
    profile = _profile_of(character_name, profile)
    from app.core.body_slots import base_body_fragments, prompt_fragments
    from app.core.height import height_phrase
    fragments = (prompt_fragments(character_name, profile=profile, base_body=True)["general"]
                 + (base_body_fragments(character_name, profile=profile) if base_fragments else []))
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
    """The pose text of the base FRONT (``model_refs.BASE_FRONT_POSE_PROMPT``);
    the other views are edits and carry their ``BASE_VIEW_PROMPTS`` /
    ``DRAFT_PROMPTS`` sentence instead."""
    if view != "front":
        raise ValueError(f"no pose text for the base-body view {view!r}")
    from app.core.model_refs import BASE_FRONT_POSE_PROMPT
    return BASE_FRONT_POSE_PROMPT


def base_negative(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
                  head: str = BASE_NEGATIVE) -> str:
    """``BASE_NEGATIVE`` (or ``head``) plus the ``base_body_negative`` text of
    every body slot that applies to the character
    (``body_slots.slots_for_character``, in slot order; the ``base_body`` flag
    does not matter) — a package keeps what its slots describe out of the
    base views."""
    profile = _profile_of(character_name, profile)
    from app.core.body_slots import slots_for_character
    extra = [text for text in (str(getattr(spec, "base_body_negative", "") or "").strip()
                               for spec in slots_for_character(character_name, profile=profile)) if text]
    return ", ".join([head, *extra])


def hair_text(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> str:
    """The hair text the plain body is rendered with: the description of the
    plain body's hairstyle when its mode is ``body``
    (``garment_hair.plain_hair_text``); "" under any other mode or without a
    hairstyle — the bald wording."""
    from app.core import garment_hair
    return garment_hair.plain_hair_text(character_name, _profile_of(character_name, profile))


def _haired_head(character_name: str, hair: str, profile: Dict[str, Any]) -> str:
    """What stands in an edit view's prompt where ``_BALD_WORDS`` stood: the
    hair text, the reference clause, and ``HAIR_BEHIND_SHOULDERS`` when that
    hair falls behind them."""
    from app.core.garment_hair import hair_behind_shoulders
    from app.core.model_refs import TPOSE_REFERENCE_HAIR_CLAUSE
    parts = [hair, TPOSE_REFERENCE_HAIR_CLAUSE]
    if hair_behind_shoulders(character_name, profile=profile, text=hair):
        parts.append(HAIR_BEHIND_SHOULDERS)
    return ", ".join(parts)


def _haired_front_pose(character_name: str, hair: str, profile: Dict[str, Any]) -> str:
    """The base front's pose text of a base haired with ``hair``: the A-pose,
    then the hair off the chest (``TPOSE_FRONT_HAIR_CLAUSE``: the extension
    rig must not weight hair to the chest), then ``HAIR_BEHIND_SHOULDERS``
    when it falls behind them."""
    from app.core.garment_hair import hair_behind_shoulders
    from app.core.model_refs import TPOSE_FRONT_HAIR_CLAUSE
    parts = [_pose_text("front"), TPOSE_FRONT_HAIR_CLAUSE]
    if hair_behind_shoulders(character_name, profile=profile, text=hair):
        parts.append(HAIR_BEHIND_SHOULDERS)
    return ", ".join(parts)


def base_character(character_name: str, view: str, *,
                   profile: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """The CHARACTER BLOCK of one base view, for the style's ``{character}``
    slot: on the front ``BALD_HEAD``, ``BODY_TEXT`` and
    ``base_appearance`` — the words that shape the figure, right after the
    style's subject sentence (review 2026-11-11). None on back/left/right —
    an edit of the front takes the body from the image, and its prompt is the
    short ``BASE_VIEW_PROMPTS`` text alone (user test 2026-11-09: the block
    changed nothing). A haired base (``hair_text``) names its hair in
    ``BALD_HEAD``'s place."""
    if view not in BASE_VIEWS:
        raise ValueError(f"unknown base-body view: {view!r}")
    if view != "front":
        return None
    profile = _profile_of(character_name, profile)
    appearance = base_appearance(character_name, profile=profile, base_fragments=True)
    head = hair_text(character_name, profile=profile) or BALD_HEAD
    return ", ".join(p for p in (head, BODY_TEXT, appearance) if p)


def _picture_head(character_name: str, hair: str, profile: Dict[str, Any]) -> str:
    """What stands in an edit view's prompt where ``_BALD_WORDS`` stood when
    the front is an edit of a picture (Ruling A94): hair from the picture →
    ``VIEW_HAIR_FROM_REFERENCE`` (and ``HAIR_BEHIND_SHOULDERS`` when that hair
    falls behind them), other hair in the body → ``_haired_head``, bald →
    ``_BALD_WORDS``; then ``VIEW_FACIAL_HAIR_FROM_REFERENCE`` for a character
    with facial hair."""
    from app.core.garment_hair import hair_behind_shoulders
    if not hair:
        parts = [_BALD_WORDS]
    elif hair_from_picture(character_name, profile=profile):
        parts = [VIEW_HAIR_FROM_REFERENCE]
        if hair_behind_shoulders(character_name, profile=profile, text=hair):
            parts.append(HAIR_BEHIND_SHOULDERS)
    else:
        parts = [_haired_head(character_name, hair, profile)]
    if has_facial_hair(character_name, profile=profile):
        parts.append(VIEW_FACIAL_HAIR_FROM_REFERENCE)
    return ", ".join(parts)


def base_prompt(character_name: str, view: str, *,
                profile: Optional[Dict[str, Any]] = None, picture: bool = False) -> Tuple[str, str]:
    """``(prompt, negative)`` of one base-body view. Front: the pose text —
    what follows the style (``base_character`` is the block inside it).
    Back/left/right: the ``BASE_VIEW_PROMPTS`` text, the whole prompt of the
    edit. The negative is ``base_negative`` (``BASE_NEGATIVE`` + the slots'
    texts). A haired base (``hair_text``): the front's pose text keeps the
    hair off the chest (``_haired_front_pose``), an edit view names the hair
    where it said "completely bald" (``_haired_head``), and the negative
    starts with ``HAIRED_BASE_NEGATIVE``.

    ``picture`` (Ruling A94): the front is (or, for the front, will be) an
    edit of a picture — the edit views say ``_picture_head`` where "completely
    bald" stood, and a bald base of a character with facial hair starts its
    negative with ``FACIAL_HAIR_SAFE_HAIR_NEGATIVE``. False (a front made from
    text) keeps every text of before."""
    if view not in BASE_VIEWS:
        raise ValueError(f"unknown base-body view: {view!r}")
    profile = _profile_of(character_name, profile)
    hair = hair_text(character_name, profile=profile)
    if picture:
        if view != "front":
            prompt = BASE_VIEW_PROMPTS[view].replace(_BALD_WORDS, _picture_head(character_name, hair, profile), 1)
        elif hair:
            prompt = _haired_front_pose(character_name, hair, profile)
        else:
            prompt = _pose_text("front")
        if hair:
            head = HAIRED_BASE_NEGATIVE
        elif has_facial_hair(character_name, profile=profile):
            head = ", ".join((FACIAL_HAIR_SAFE_HAIR_NEGATIVE, BODY_NEGATIVE, POSE_NEGATIVE))
        else:
            head = BASE_NEGATIVE
        return prompt, base_negative(character_name, profile=profile, head=head)
    if not hair:
        prompt = _pose_text("front") if view == "front" else BASE_VIEW_PROMPTS[view]
        return prompt, base_negative(character_name, profile=profile)
    if view == "front":
        prompt = _haired_front_pose(character_name, hair, profile)
    else:
        prompt = BASE_VIEW_PROMPTS[view].replace(_BALD_WORDS, _haired_head(character_name, hair, profile), 1)
    return prompt, base_negative(character_name, profile=profile, head=HAIRED_BASE_NEGATIVE)


#: The freshness note of a base view rendered with other prompt texts than
#: the shipped ones (``prompt_fingerprint``): usable, not regenerated.
OLDER_PROMPTS = "Built with older prompts — Regenerate to use the new ones"
_BASE_FRONT_SIDECAR = re.compile(r"^tpose_base[0-9a-f]{8}\.json$")


def _profile_image_id(character_name: str, profile: Dict[str, Any]) -> List[Any]:
    from app.core.model_refs import current_profile_image
    image = current_profile_image(character_name, profile=profile)
    try:
        return [image.name, image.stat().st_size] if image else ["", 0]
    except OSError:
        return ["", 0]


def base_identity(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> str:
    """``"base" + 8 hex`` over what the base body IS: the character's base
    appearance (gender, age, height, the body slots' base fragments), the
    current profile image (file name and size) and ``BASE_BODY_VERSION`` —
    never the prompt wording (pose text, bald head, body text, negatives,
    styles). A stored base keeps its identity when the prompts are reworded
    (incident 2026-11-11: the signature used to hash the prompt texts, and
    one wording change orphaned every base body and every outfit model on
    it); a wording change only shows as the ``OLDER_PROMPTS`` note."""
    profile = _profile_of(character_name, profile)
    payload = {"version": BASE_BODY_VERSION,
               "appearance": base_appearance(character_name, profile=profile, base_fragments=True),
               "profile_image": _profile_image_id(character_name, profile)}
    digest = hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return "base" + digest[:8]


def prompt_fingerprint(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
                       source: Optional[str] = None, picture: Optional[bool] = None) -> str:
    """12 hex over the four views' character blocks, prompts and negatives —
    the texts a base render is made with — and, while the world switch
    ``base_body.skin_detail_step`` is on, the front's skin detail step
    (``base_skin.fingerprint_part``: prompt, occasion, transfer parameters;
    left out while off, so a base without the step stays current then).
    Stored in every base view's sidecar; a stored base whose fingerprint
    differs from the current one is current but carries the
    ``OLDER_PROMPTS`` note.

    Ruling A92: the skin part is also left out for a front made from the
    full-body reference (``source`` ``SOURCE_FULL_BODY`` — the step does not
    run there). ``source`` None = the source of the stored front of the
    current base (the front a comparison judges), else what the front is made
    from now; a front made from the profile image or from text keeps the
    fingerprint it had before the ruling, byte for byte.

    Ruling A94: the views' texts are those of ``picture`` (``base_prompt``) —
    None = whether the stored front of the current base is an edit of a
    picture (``front_from_picture``), else what the front is made from now."""
    profile = _profile_of(character_name, profile)
    if picture is None:
        picture = front_from_picture(character_name, profile=profile)
    payload: Dict[str, Any] = {view: [base_character(character_name, view, profile=profile),
                                      *base_prompt(character_name, view, profile=profile, picture=picture)]
                               for view in BASE_VIEWS}
    from app.core import base_skin
    if source is None and base_skin.enabled():
        source = base_skin.front_source(character_name, profile=profile)
    skin = base_skin.fingerprint_part(profile, source=source or "")
    if skin is not None:
        payload["skin_step"] = skin
    return hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


# --- Ruling A74a carry-over --------------------------------------------------
# Ruling A74a (2026-11-14) dropped clauses from the base prompts — the block's
# safe-content tag, the plain-surface clause of ``BODY_TEXT``, the anatomy
# word of ``BODY_NEGATIVE`` / ``DRAFT_NEGATIVE`` and, in the packs, the "no …"
# clause of a ``base_body_prompt`` and the ``base_body_negative`` terms. That
# changes every ``prompt_fingerprint`` and, through ``base_appearance``, the
# ``base_identity`` of a character whose slot rendered such a clause: every
# stored base would have turned ``OLDER_PROMPTS`` (the Build and the
# ``base_refresh`` improvement re-render it) or gone missing. So a base view
# rendered BEFORE the ruling — its sidecar has no ``prompt_rules`` — stays
# current while today's texts only DROP comma clauses from the ones it
# recorded (``prompt``, ``final_prompt``, ``negative_prompt``, the front's
# ``skin_step``); a real change (a hair text, another appearance word, the
# skin step switched) adds or rewrites a clause and ages it as before. A view
# rendered since records ``PROMPT_RULES`` and goes by its fingerprint alone,
# so a later wording change ages bases as it always did. The comparison reads
# the view's own record — the old wording is nowhere in the code.

#: Recorded in every base view's sidecar (``prompt_rules``) since Ruling A74a.
PROMPT_RULES = "a74a"
#: The ``BASE_BODY_VERSION`` of the carry-over: a bump re-renders every base
#: on purpose, so it ends the carry-over of identities (``_carried_front``).
_CARRY_BODY_VERSION = 2


def _clauses(text: Any) -> set:
    return {c.strip() for c in str(text or "").split(",") if c.strip()}


def _drops_only(current: Optional[str], recorded: Any) -> bool:
    """Whether ``current`` names no comma clause that ``recorded`` lacks."""
    return _clauses(current) <= _clauses(recorded)


def _view_carried(character_name: str, view: str, meta: Dict[str, Any], profile: Dict[str, Any]) -> bool:
    """Whether a base ``view`` whose sidecar is ``meta`` was rendered before
    Ruling A74a with today's texts plus clauses since dropped: no
    ``prompt_rules``, the same prompt, today's negative clauses all in its
    recorded negative and — on the front — today's character block all in its
    recorded final prompt and the same skin step (``base_skin.fingerprint_part``
    against its ``skin_step`` record; none while the switch is off)."""
    if not meta or meta.get("prompt_rules"):
        return False
    prompt, negative = base_prompt(character_name, view, profile=profile)
    if str(meta.get("prompt") or "") != prompt or not _drops_only(negative, meta.get("negative_prompt")):
        return False
    if view != "front":
        return True
    if not _drops_only(base_character(character_name, view, profile=profile), meta.get("final_prompt")):
        return False
    from app.core import base_skin
    made_from = meta.get("front_reference") if isinstance(meta.get("front_reference"), dict) else {}
    skin = base_skin.fingerprint_part(profile, source=str(made_from.get("source") or ""))
    record = meta.get("skin_step") if isinstance(meta.get("skin_step"), dict) else {}
    if skin is None:
        return not record.get("version")
    return all(record.get(key) == value for key, value in skin.items())


def recorded_fingerprint(character_name: str, signature: str, view: str, meta: Dict[str, Any], *,
                         current: str, profile: Optional[Dict[str, Any]] = None) -> str:
    """The ``prompt_fingerprint`` a stored base view counts as rendered with:
    its sidecar's (``meta``), or ``current`` when the Ruling A74a carry-over
    holds for it — the front by ``_view_carried``; another view by its own
    texts, with the front's recorded fingerprint (one render's global inputs,
    the skin step among them) and a front that is carried itself."""
    recorded = str(meta.get("prompt_fingerprint") or "")
    if not recorded or recorded == current:
        return recorded
    if _full_body_skin_carried(character_name, signature, recorded, profile):
        return current
    if meta.get("prompt_rules"):
        return recorded
    profile = _profile_of(character_name, profile)
    if view != "front":
        front = _front_sidecar(character_name, signature)
        if recorded != str(front.get("prompt_fingerprint") or ""):
            return recorded
        if not _view_carried(character_name, "front", front, profile):
            return recorded
    return current if _view_carried(character_name, view, meta, profile) else recorded


def _full_body_skin_carried(character_name: str, signature: str, recorded: str,
                            profile: Optional[Dict[str, Any]]) -> bool:
    """Ruling A92: whether a view of the stored base ``signature`` whose front
    was made from the full-body reference — and rendered WITH the skin detail
    step, before the ruling — counts as current: its recorded fingerprint is
    today's with the skin part in it (``source`` "", the switch on). The step
    only added fine skin detail the full-body picture already has; the front
    is not older for it, and nothing re-renders it (the ``base_refresh``
    improvement would, at idle time)."""
    from app.core import base_skin
    if not base_skin.enabled():
        return False
    stored = stored_front_reference(character_name, signature) or {}
    if stored.get("source") != SOURCE_FULL_BODY:
        return False
    return recorded == prompt_fingerprint(character_name, profile=profile, source="", picture=True)


def _carried_front(meta: Dict[str, Any], appearance: str, profile_image: str) -> bool:
    """Whether a stored front sidecar ``meta`` whose recorded ``base_identity``
    is not today's stands for today's identity by the Ruling A74a carry-over:
    rendered before the ruling, ``BASE_BODY_VERSION`` unchanged, from the
    current profile image, and today's base appearance only drops clauses
    from its recorded final prompt (a changed attribute value, height, age
    or gender adds one — a new body, as before)."""
    if meta.get("prompt_rules") or BASE_BODY_VERSION != _CARRY_BODY_VERSION or not profile_image:
        return False
    refs_used = meta.get("reference_images")
    first = refs_used.get("input_reference_image_1") if isinstance(refs_used, dict) else None
    return first == profile_image and _drops_only(appearance, meta.get("final_prompt"))


def _front_sidecar(character_name: str, signature: str) -> Dict[str, Any]:
    """The base front's sidecar (``model_refs/tpose_<sig>.json``), {} without one."""
    from app.core.model_refs import get_model_refs_dir
    path = get_model_refs_dir(character_name) / f"tpose_{signature}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _stored_base_for(character_name: str, identity: str, profile_image: str,
                     appearance: str = "") -> Optional[str]:
    """The signature of the stored base set that belongs to ``identity``:
    the newest front sidecar that names it (``base_identity``), else the
    newest one rendered before Ruling A74a that stands for it by the carry-over
    (``_carried_front`` with today's ``appearance``), else — a set rendered
    before identities were recorded (no ``base_identity`` key) — the newest
    one whose reference was the current profile image. None when nothing
    stored fits. Read-only: nothing is renamed or rewritten."""
    from app.core.model_refs import get_model_refs_dir
    refs = get_model_refs_dir(character_name)
    try:
        names = [n for n in os.listdir(refs) if _BASE_FRONT_SIDECAR.match(n)]
    except OSError:
        return None
    named: List[Tuple[str, str]] = []
    carried: List[Tuple[str, str]] = []
    legacy: List[Tuple[str, str]] = []
    for name in names:
        signature = name[len("tpose_"):-len(".json")]
        meta = _front_sidecar(character_name, signature)
        if not meta or not (refs / f"tpose_{signature}.png").is_file():
            continue
        stamp = str(meta.get("created_at") or "")
        if meta.get("base_identity"):
            if meta.get("base_identity") == identity:
                named.append((stamp, signature))
            elif appearance and _carried_front(meta, appearance, profile_image):
                carried.append((stamp, signature))
            continue
        refs_used = meta.get("reference_images")
        first = refs_used.get("input_reference_image_1") if isinstance(refs_used, dict) else None
        if profile_image and first == profile_image:
            legacy.append((stamp, signature))
    for pool in (named, carried, legacy):
        if pool:
            return max(pool)[1]
    return None


def base_signature(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> str:
    """The signature of the base set the character stands on — the key of
    its files (``model_refs/tpose*_<sig>``, ``model3d/<sig>.glb``, the outfit
    models' ``base_signature``): the stored set that belongs to the current
    ``base_identity`` (``_stored_base_for``), else the identity itself (the
    name the next render gets). Prompt wording is NOT part of it."""
    profile = _profile_of(character_name, profile)
    identity = base_identity(character_name, profile=profile)
    from app.core.model_refs import find_ref_image
    if find_ref_image(character_name, "tpose", identity) is not None:
        return identity
    stored = _stored_base_for(character_name, identity, _profile_image_id(character_name, profile)[0],
                              base_appearance(character_name, profile=profile, base_fragments=True))
    return stored or identity


def prompts_current(character_name: str, signature: str, *, profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the stored base ``signature`` was rendered with the current
    prompt texts (its front sidecar's ``prompt_fingerprint``, through the
    Ruling A74a carry-over: ``recorded_fingerprint``)."""
    meta = _front_sidecar(character_name, signature)
    if not meta:
        return False
    made_from = meta.get("front_reference") if isinstance(meta.get("front_reference"), dict) else {}
    current = prompt_fingerprint(character_name, profile=profile, source=str(made_from.get("source") or ""),
                                 picture=made_from.get("method") == FRONT_FROM_REFERENCE)
    return recorded_fingerprint(character_name, signature, "front", meta, current=current,
                                profile=profile) == current


def stored_base_haired(character_name: str, bsig: str) -> Optional[bool]:
    """Whether the stored base front of ``bsig`` was rendered with hair: its
    sidecar ``prompt`` does not name the bald head — ``_BALD_WORDS``, the
    words every wording of it starts with, so a front rendered with an
    OLDER bald text ("completely bald, smooth clean-shaven head") reads as
    bald too (fix round T12-F1: it read as haired, and a switch to hair in
    the body served the bald body as "hair in the body"). None without a
    stored front. The delivered figure shows HairDeck hair without a fit as
    this body has it (``figure`` rule 3)."""
    from app.core.model_refs import find_ref_image
    if find_ref_image(character_name, _kind("front"), bsig) is None:
        return None
    return _BALD_WORDS not in str(_front_sidecar(character_name, bsig).get("prompt") or "")


def base_prompts_freshness(character_name: str, *,
                           profile: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """``{state, reason}`` of the stored base front against the current
    prompt texts (the Wardrobe's hair row of a character whose hair is in
    the body mesh): ``missing`` without a stored front, ``stale`` with
    ``OLDER_PROMPTS`` when it was rendered with other texts
    (``prompts_current``), else ``current``."""
    from app.core.model_overview import CURRENT, MISSING, STALE, freshness
    from app.core.model_refs import find_ref_image
    profile = _profile_of(character_name, profile)
    signature = base_signature(character_name, profile=profile)
    if find_ref_image(character_name, _kind("front"), signature) is None:
        return freshness(MISSING, BASE_IMAGES_MISSING)
    if not prompts_current(character_name, signature, profile=profile):
        return freshness(STALE, OLDER_PROMPTS)
    return freshness(CURRENT)


# --- The base front from a reference image (Ruling A74b) -------------------
#
# The user, 2026-11-14: the text-only front gave every character nearly the
# same build. While the character HAS a profile image the base front is an
# EDIT of it (use case ``BASE_FRONT_EDIT_USE_CASE``: the edit instruction,
# then ``edit_character``, then the framing and light of the base front, then
# the pose text — the prompt of the user's validated hub job c265fd78); the
# build, the face and the proportions come from the picture. Without one the
# front is the text render as before. ``front_reference`` is what the front
# is made from NOW and is recorded in the front's sidecar; a stored front
# whose record differs (another picture, the same name with other content,
# another edit text — or no record: made from text) is OUTDATED with
# ``front_reference_state``'s reason. That is a separate axis from
# ``prompt_fingerprint`` on purpose: an ``OLDER_PROMPTS`` base is something
# the ``base_refresh`` improvement re-renders by itself at idle time; a front
# made from another reference is re-rendered only by a person's click (the
# Base body tab's Regenerate / Run all, a manual Build — ``base_refresh_plan``
# reason ``reference`` only with ``missing=True``). Nothing runs because the
# method changed.

#: The use case of the front made from a reference image (``config``: style,
#: negative). Also the outfit's dressed front made from its own reference
#: (``outfit_references``).
BASE_FRONT_EDIT_USE_CASE = "base_front_edit"
#: ``front_reference["method"]``.
FRONT_FROM_REFERENCE = "reference"
FRONT_FROM_TEXT = "text"
#: The front tile's reasons (``front_reference_state``), plain words for the UI. They name no button (Ruling A86):
#: they are also written where the front's Regenerate is not right beside them (the Figure tab's change).
FRONT_MADE_FROM_TEXT = "Made from text alone — regenerating the front makes it from the profile image"
FRONT_OTHER_REFERENCE = "Made from another profile image — regenerating the front makes it from the current one"
FRONT_OTHER_EDIT_TEXT = "Made with an older edit text — regenerating the front makes it with the current one"
FRONT_NO_PROFILE_NOW = "Made from a profile image there is none of now — regenerating the front makes it from text"
#: The Base body tab's line when there is no profile image (decision 2 of the brief).
NO_PROFILE_IMAGE_NOTE = "No profile image — the front is made from text alone. Set a profile image to make it from that picture."
# Ruling A87: the front is an edit of the FULL-BODY REFERENCE when one is set
# (``full_body_reference``), else of the profile image as before. A front made
# from the profile image keeps a record WITHOUT ``source`` (byte-identical to
# A74b's, so no stored front turns due on deploy); one made from the full-body
# reference records ``source: "full_body"``.
#: ``front_reference["source"]`` of a front made from the full-body reference.
SOURCE_FULL_BODY = "full_body"
FRONT_PROFILE_NOT_FULL_BODY = ("Made from the profile image — regenerating the front makes it from the full-body "
                               "reference")
FRONT_TEXT_NOT_FULL_BODY = "Made from text alone — regenerating the front makes it from the full-body reference"
FRONT_OTHER_FULL_BODY = ("Made from another full-body reference — regenerating the front makes it from the current "
                         "one")
FRONT_NO_FULL_BODY_NOW = ("Made from a full-body reference there is none of now — regenerating the front makes it "
                          "from the profile image")
FRONT_NO_FULL_BODY_TEXT = ("Made from a full-body reference there is none of now — regenerating the front makes it "
                           "from text")
#: The Base body tab's line when no full-body reference is set (Ruling A87).
NO_FULL_BODY_NOTE = "No full-body reference — the front is made from the profile image"


def edit_character(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> str:
    """The character block of the front made from a picture (the full-body
    reference or the profile image): the head, ``BODY_TEXT`` and the
    packages' base-body texts (``body_slots.base_body_fragments`` — what a
    clothed picture cannot show). Never gender, age, height or the build
    slots of ``base_appearance``: the picture shows them, and naming them is
    what made every front the same build (user 2026-11-14; the validated job
    c265fd78 names none of them).

    The head (Ruling A94) keeps the person of the picture
    (``picture_identity``): hair from the picture (``hair_from_picture``) →
    "the same face, hair[ and facial hair] as the person in the picture" and
    no hair text; other hair in the body → its text, then the identity
    clause; bald → ``BALD_HEAD``, then the identity clause. Facial hair is
    named only when the character has some (``has_facial_hair``)."""
    from app.core.body_slots import base_body_fragments
    profile = _profile_of(character_name, profile)
    hair = hair_text(character_name, profile=profile)
    facial = has_facial_hair(character_name, profile=profile)
    if hair and hair_from_picture(character_name, profile=profile):
        head = [picture_identity(hair=True, facial_hair=facial)]
    else:
        head = [hair or BALD_HEAD, picture_identity(hair=False, facial_hair=facial)]
    return ", ".join(p for p in (*head, BODY_TEXT, *base_body_fragments(character_name, profile=profile)) if p)


def _edit_fingerprint(character_name: str, profile: Dict[str, Any]) -> str:
    """12 hex over the texts the front edit is made with (block, pose text,
    negative) — part of ``front_reference``."""
    prompt, negative = base_prompt(character_name, "front", profile=profile, picture=True)
    raw = json.dumps([edit_character(character_name, profile=profile), prompt, negative], ensure_ascii=False)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def front_source_image(character_name: str, *, profile: Optional[Dict[str, Any]] = None
                       ) -> Tuple[Optional[Path], str]:
    """``(picture, source)`` the base front is an edit of NOW (Ruling A87):
    the full-body reference's gallery file (``SOURCE_FULL_BODY``) while one is
    set and its file is there, else the current profile image (source ""),
    else ``(None, "")`` — the text path."""
    from app.core import full_body_reference
    from app.core.model_refs import current_profile_image
    profile = _profile_of(character_name, profile)
    full_body = full_body_reference.base_image(character_name, profile=profile)
    if full_body is not None:
        return full_body, SOURCE_FULL_BODY
    return current_profile_image(character_name, profile=profile), ""


def front_reference(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What the base front is made from NOW: ``{"method": "reference",
    "image": <file name>, "sha256": <its content>, "prompt": <edit text
    fingerprint>}`` while there is a picture to edit (``front_source_image``:
    the full-body reference — then with ``"source": "full_body"`` — else the
    profile image), else ``{"method": "text"}``."""
    profile = _profile_of(character_name, profile)
    image, source = front_source_image(character_name, profile=profile)
    sha = file_sha256(image)
    if image is None or not sha:
        return {"method": FRONT_FROM_TEXT}
    record = {"method": FRONT_FROM_REFERENCE, "image": image.name, "sha256": sha,
              "prompt": _edit_fingerprint(character_name, profile)}
    if source:
        record["source"] = source
    return record


def stored_front_reference(character_name: str, bsig: str) -> Optional[Dict[str, Any]]:
    """The ``front_reference`` record of the stored base front of ``bsig``
    (``{"method": "text"}`` for a front rendered before the record existed —
    every such front was made from text), None without a stored front."""
    from app.core.model_refs import find_ref_image
    if find_ref_image(character_name, _kind("front"), bsig) is None:
        return None
    record = _front_sidecar(character_name, bsig).get("front_reference")
    return dict(record) if isinstance(record, dict) and record.get("method") else {"method": FRONT_FROM_TEXT}


def front_from_picture(character_name: str, bsig: Optional[str] = None, *,
                       profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the base front of ``bsig`` (the current base when None) is an
    edit of a picture (Ruling A94 — what ``base_prompt``'s ``picture`` says):
    the stored front's record (``stored_front_reference``, method
    "reference"), else — without a stored front — whether a front would be
    made from a picture now (``front_source_image``)."""
    profile = _profile_of(character_name, profile)
    bsig = bsig or base_signature(character_name, profile=profile)
    stored = stored_front_reference(character_name, bsig)
    if stored is not None:
        return stored.get("method") == FRONT_FROM_REFERENCE
    return front_source_image(character_name, profile=profile)[0] is not None


def front_reference_state(character_name: str, bsig: Optional[str] = None, *,
                          profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """``{wanted, stored, current, reason}`` of the stored base front against
    ``front_reference`` (module section above). ``current`` True without a
    stored front (that one is missing, not outdated); ``reason`` "" when
    current, else one of ``FRONT_MADE_FROM_TEXT`` / ``FRONT_OTHER_REFERENCE``
    / ``FRONT_OTHER_EDIT_TEXT`` / ``FRONT_NO_PROFILE_NOW``. Read-only."""
    profile = _profile_of(character_name, profile)
    bsig = bsig or base_signature(character_name, profile=profile)
    wanted = front_reference(character_name, profile=profile)
    stored = stored_front_reference(character_name, bsig)
    reason = ""
    if stored is not None and stored != wanted:
        stored_full = stored.get("source") == SOURCE_FULL_BODY
        wanted_full = wanted.get("source") == SOURCE_FULL_BODY
        if wanted["method"] == FRONT_FROM_TEXT:
            reason = FRONT_NO_FULL_BODY_TEXT if stored_full else FRONT_NO_PROFILE_NOW
        elif stored.get("method") != FRONT_FROM_REFERENCE:
            reason = FRONT_TEXT_NOT_FULL_BODY if wanted_full else FRONT_MADE_FROM_TEXT
        elif stored_full != wanted_full:
            reason = FRONT_PROFILE_NOT_FULL_BODY if wanted_full else FRONT_NO_FULL_BODY_NOW
        elif (stored.get("image"), stored.get("sha256")) != (wanted["image"], wanted["sha256"]):
            reason = FRONT_OTHER_FULL_BODY if wanted_full else FRONT_OTHER_REFERENCE
        else:
            reason = FRONT_OTHER_EDIT_TEXT
    return {"wanted": wanted, "stored": stored, "current": not reason, "reason": reason}


def _frozen_reference(path: Path, refs_dir: Path):
    """A private copy of the reference picture ``path`` for the length of a
    run (every hand-gate attempt edits the same bytes): in a temp dir inside
    ``refs_dir`` (the reference containment gate accepts it), the file name
    kept (the sidecar records the reference by name), a transparent picture
    flattened onto the neutral grey of ``model_refs.neutral_view_reference``.
    Yields ``(copy, sha256 of the ORIGINAL bytes copied)`` — the content the
    run edits, as ``front_reference`` / the outfit record name it."""
    import contextlib
    import io
    import tempfile

    @contextlib.contextmanager
    def frozen():
        from PIL import Image
        from app.core.model_refs import VIEW_REFERENCE_BACKGROUND
        data = path.read_bytes()
        with tempfile.TemporaryDirectory(prefix=".editref_", dir=refs_dir) as tmp:
            out = Path(tmp) / path.name
            with Image.open(io.BytesIO(data)) as im:
                if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
                    rgba = im.convert("RGBA")
                    flat = Image.new("RGBA", rgba.size, VIEW_REFERENCE_BACKGROUND + (255,))
                    flat.alpha_composite(rgba)
                    out = out.with_suffix(".png")
                    flat.convert("RGB").save(out)
                else:
                    out.write_bytes(data)
            yield out, hashlib.sha256(data).hexdigest()

    return frozen()


def is_base_pipeline(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the character is on the base-body pipeline: every humanoid is
    (Ruling A13 — the per-character switch and its ``model_pipeline`` profile
    key are gone), except a temporary NPC (Ruling A13a: no user ever starts a
    Build for one, so it keeps the direct T-pose path that finishes it —
    ``npc_assets``); an animal never is."""
    from app.core.model_refs import is_humanoid
    from app.models.character import is_temporary_npc
    profile = _profile_of(character_name, profile)
    return bool(is_humanoid(character_name, profile=profile)) and not is_temporary_npc(character_name,
                                                                                         profile=profile)


# --- Rendering the four views ---------------------------------------------

# Status per (character, view), in memory like the model-refs status: the
# count of reservations still holding the view (a route thread waiting on the
# character lock counts — it WILL render), since when, and the last failure.
_status_lock = threading.Lock()
_running: Dict[Tuple[str, str], Tuple[datetime, int]] = {}
# What the first reservation still holding a view is (Ruling A26: a Build refused beside it names it):
# ``RENDER_STEP`` (a view's render), ``SKIN_STEP`` (the skin step on the front), ``RUN_ALL_STEP``.
_running_step: Dict[Tuple[str, str], str] = {}
_failed: Dict[Tuple[str, str], Dict[str, Any]] = {}
# One base render per character at a time: the views edit the front, and a
# second run would race the same files.
_char_locks: Dict[str, threading.Lock] = {}


def _char_lock(character_name: str) -> threading.Lock:
    with _status_lock:
        return _char_locks.setdefault(character_name, threading.Lock())


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat(timespec="seconds") if dt else None


#: What reserves a base view (``reserve_views``' ``step``; Ruling A26 names it).
RENDER_STEP = "render"
SKIN_STEP = "skin step"
RUN_ALL_STEP = "Run all"


def reserve_views(character_name: str, views: Iterable[str], *, step: str = RENDER_STEP) -> None:
    """Mark views running (counted, so nested and queued runs stack); ``step`` is what reserves them — the
    first reservation of a view names it until the view is free again."""
    from app.core.timeutils import utc_now
    with _status_lock:
        for view in views:
            key = (character_name, view)
            started, count = _running.get(key, (utc_now(), 0))
            _running[key] = (started, count + 1)
            if count == 0:
                _running_step[key] = step


def release_views(character_name: str, views: Iterable[str]) -> None:
    with _status_lock:
        for view in views:
            key = (character_name, view)
            started, count = _running.get(key, (None, 0))
            if count <= 1:
                _running.pop(key, None)
                _running_step.pop(key, None)
            else:
                _running[key] = (started, count - 1)


def base_steps_running(character_name: str) -> List[str]:
    """The base-body steps of the character queued or running now, by name (Ruling A26 — a Build does not
    start beside one): "Base body skin step", "Base body front view render", "Base body Run all" (from the
    views' reservations, which a step takes from its click on) and "Base body model (mesh + rig)" (a base model
    run, ``start_base_model`` from its click on). [] when none."""
    out: List[str] = []
    with _status_lock:
        steps = {view: _running_step.get((character_name, view), RENDER_STEP)
                 for view in BASE_VIEWS if (character_name, view) in _running}
        model = character_name in _model_running
    for view, step in steps.items():
        name = (f"Base body {view} view render" if step == RENDER_STEP else f"Base body {step}")
        if name not in out:
            out.append(name)
    if model:
        out.append("Base body model (mesh + rig)")
    return out


def _record(character_name: str, view: str, error: Optional[str], *, warning: bool = False) -> None:
    """The outcome of one view: ``error`` None = fine; with ``warning`` the
    text is a caveat on a view that WAS stored (``base_status`` reports it
    as ``warning``, not as ``failed``)."""
    from app.core.timeutils import utc_now
    with _status_lock:
        if error is None:
            _failed.pop((character_name, view), None)
        else:
            _failed[(character_name, view)] = {"error": error, "warning": warning, "failed_at": utc_now()}


def base_status(character_name: str) -> Dict[str, Dict[str, Any]]:
    """Per view: ``{running, started_at, failed, error, failed_at, warning}``
    — SYSTEM stamps (``utc_now``), shaped like
    ``model_refs.get_render_status``; ``warning`` is the caveat of a view
    that was stored anyway (the hand gate), None otherwise."""
    out: Dict[str, Dict[str, Any]] = {}
    with _status_lock:
        for view in BASE_VIEWS:
            started, _count = _running.get((character_name, view), (None, 0))
            failure = _failed.get((character_name, view)) or {}
            warned = bool(failure.get("warning"))
            out[view] = {"running": started is not None, "started_at": _iso(started),
                         "failed": bool(failure) and not warned,
                         "error": None if warned else failure.get("error"),
                         "failed_at": None if warned else _iso(failure.get("failed_at")),
                         "warning": failure.get("error") if warned else None}
    return out


class MissingInput(ValueError):
    """A precondition the user can fix (a profile picture, the front image)
    — a route answers 409, unlike a request that can never work (400)."""


class MissingFront(MissingInput):
    """A single side/back view was asked for before its front exists."""


def _kind(view: str) -> str:
    return "tpose" if view == "front" else f"tpose_{view}"


def check_renderable(character_name: str, *, view: Optional[str] = None,
                     profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The profile, or ValueError when no base body can be rendered: an
    unknown view, a non-humanoid character (animals keep the whole-body
    path) or a single view without its front (``MissingFront``). No profile
    image is no refusal (Ruling A74b): the front is then made from text
    alone (``front_reference``)."""
    if view is not None and view not in BASE_VIEWS:
        raise ValueError(f"unknown base-body view: {view!r}")
    profile = _profile_of(character_name, profile)
    from app.core.model_refs import find_ref_image, is_humanoid
    if not is_humanoid(character_name, profile=profile):
        raise ValueError("The base body is for humanoid characters only")
    if view not in (None, "front") and find_ref_image(
            character_name, "tpose", base_signature(character_name, profile=profile)) is None:
        raise MissingFront("A base-body view requires the front image")
    return profile


#: Front renders per run at most: the first one plus two re-renders when the
#: hand gate (``base_body_gates.hand_pose_gate``) fails. Each is a fresh
#: render — the backend picks a new seed.
HAND_GATE_ATTEMPTS = 3


def hand_gate_warning(attempts: int) -> str:
    """The status warning of a front kept although no attempt passed."""
    return (f"Palms may face the camera (hand check failed after {attempts} "
            f"attempt{'' if attempts == 1 else 's'})")


def _publish_staged(staged: Path, final_stem: Path, record: Dict[str, Any],
                    key: str = "hand_gate") -> Optional[Path]:
    """Move a staged attempt (image + sidecar, the gate ``record`` written
    into the sidecar under ``key``) onto the view's stem in ``model_refs``. A stored image
    of the stem with another extension goes, like ``render_character_image``
    drops it. None when ``model_refs`` is gone (the character was deleted
    during the render)."""
    import shutil
    if not final_stem.parent.is_dir():
        return None
    sidecar = staged.with_suffix(".json")
    try:
        meta = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else {}
    except (OSError, ValueError):
        meta = {}
    meta[key] = record
    sidecar.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    target = final_stem.parent / f"{final_stem.name}{staged.suffix}"
    for old in final_stem.parent.glob(f"{final_stem.name}.*"):
        if old.suffix.lower() != ".json" and old != target:
            old.unlink()
    shutil.move(str(staged), str(target))
    shutil.move(str(sidecar), str(target.with_suffix(".json")))
    return target


def generate_base_images(character_name: str, *, view: Optional[str] = None,
                         force: bool = False, raise_load: bool = False) -> Dict[str, Optional[str]]:
    """Render the base-body views. Blocking — call from a worker thread.

    Front first (the ``tpose`` render path, occasion ``base_front``): with a
    profile image an EDIT of it (Ruling A74b — use case
    ``BASE_FRONT_EDIT_USE_CASE``, ``edit_character`` in the style's slot,
    the profile image frozen for the run as ``reference_image`` with
    ``require_reference``: a routed backend without a reference slot is not
    applicable, never a silent text render), without one the text render
    (use case ``base_front``); the front's sidecar records
    ``front_reference``. Then
    back/left/right as edits of the front on grey (occasion ``base_view``,
    use cases ``base_view_back`` / ``base_view_side``; ``BASE_USE_CASES``).
    The front hands its ``base_character`` block to the style's
    ``{character}`` slot (``style_character``); the edit views send their
    ``BASE_VIEW_PROMPTS`` text alone (no style, no block). Stored as ``tpose_<bsig>`` and
    ``tpose_<view>_<bsig>`` in ``model_refs/``; every sidecar records
    ``base_signature``. The mesh-input matte applies because the occasion
    is a mesh-input one (``render_character_image``).

    Hand gate on the front: the palms should face the thighs, and whether
    they do depends on the seed. Each front attempt renders into a private
    staging dir inside ``model_refs`` (``.handgate_*``, one subdir per
    attempt) and is measured by ``base_body_gates.hand_pose_gate``; the
    first passing attempt — else, after ``HAND_GATE_ATTEMPTS``, the one with
    the lowest score — is moved onto the front's stem with the gate numbers
    of every attempt in its sidecar (``hand_gate``). Attempt files never sit
    beside the stored refs: ``find_ref_image``, the cache GC and the outfit
    scans parse every file name there as a signature of its own. A front
    kept without a pass records ``hand_gate_warning`` as a status warning;
    the run goes on. A later attempt that fails to render ends the attempts
    with what was rendered.

    Skin detail step (``base_skin``, world switch
    ``base_body.skin_detail_step``): the chosen front is kept as the neutral
    front (``tpose_neutral_<bsig>``), ONE edit (occasion ``outfit_front``)
    plus a CPU frequency transfer puts real skin detail on it, and the result
    replaces ``tpose_<bsig>`` — the front everything reads, the mesher
    included; ``skin_step`` in its sidecar says what happened. Busy, refused
    or failed: the neutral front stays the front, the run goes on. Back/left/
    right edit the chosen front — the skin-detailed one, so they inherit
    the skin (one texture over the mesh; the back-fit noise gate measured
    for it, ``base_body_gates`` section note).

    Cached per base signature: a view that exists is skipped unless
    ``force``. ``view`` renders that one view only (a non-front view needs
    the front). The prompts carry no use-case style — the image service
    adds the style (with the character block in its slot) before the prompt
    and the use case's negative; ``base_prompt``'s negative
    is APPENDED to it (``extra_negative``), never a replacement.

    Returns ``{view: path | None}`` for every view it rendered (None =
    failed); a front that fails stops the run — the views need it.

    ``raise_load`` (the improvements queue's ``base_refresh``): a
    ``BackendBusyError`` or ``MediaGenerationDisabled`` of a render is RAISED
    (``_is_load``) instead of becoming the view's failure — the run stops
    there, nothing is recorded as failed, the views rendered before it stay
    stored. A front re-render of the hand gate that meets load ends the
    attempts with what was rendered, as any later attempt's error does."""
    import tempfile
    from app.core import base_body_gates, expression_regen
    from app.core.model_refs import _tpose_size, find_ref_image, get_model_refs_dir, neutral_view_reference
    from app.core.garment_hair import ensure_hairstyle
    try:
        # Hairstyles (plan Task 13): the plain body is the body of the character's first hairstyle — made from
        # its Appearance before the first plain body is rendered.
        ensure_hairstyle(character_name)
    except ValueError as e:
        logger.info("Base body %s: no hairstyle (%s)", character_name, e)
    except Exception as e:  # noqa: BLE001 — a hairstyle that cannot be made never blocks the plain body
        logger.warning("Base body %s: the first hairstyle was not made: %s", character_name, e)
    with _char_lock(character_name):
        # Read at run time: a run queued behind another one renders the
        # profile (image, body slots) current when it starts.
        profile = check_renderable(character_name, view=view)
        bsig = base_signature(character_name, profile=profile)
        identity = base_identity(character_name, profile=profile)
        front_ref = front_reference(character_name, profile=profile)
        refs_dir = get_model_refs_dir(character_name)
        wanted = BASE_VIEWS if view is None else (view,)
        todo = [v for v in wanted
                if force or find_ref_image(character_name, _kind(v), bsig) is None]
        # Ruling A92: a new front is made from ``front_ref`` (its skin step follows that source); views
        # rendered on the stored front record the fingerprint of that front's source.
        # Ruling A94: the views edit the front of this run (made from ``front_ref``) or the stored one.
        picture = (front_ref.get("method") == FRONT_FROM_REFERENCE if "front" in todo
                   else front_from_picture(character_name, bsig, profile=profile))
        fingerprint = prompt_fingerprint(character_name, profile=profile,
                                         source=str(front_ref.get("source") or "") if "front" in todo else None,
                                         picture=picture)
        if not todo:
            logger.info("Base body %s (%s): already rendered", character_name, bsig)
            return {}
        width, height = _tpose_size()
        mesh_profile = deepcopy(profile)
        mesh_profile["equipped_pieces"] = {}
        mesh_profile["equipped_items"] = []
        results: Dict[str, Optional[str]] = {}

        def draw(v: str, stem: Path, reference: Optional[Path]) -> Optional[Path]:
            # Ruling A74b: the front with a profile image is an edit of it (``reference`` = its frozen copy).
            edit = v == "front" and reference is not None
            prompt, negative = base_prompt(character_name, v, profile=profile,
                                           picture=edit if v == "front" else picture)
            character = (edit_character(character_name, profile=profile) if edit
                         else base_character(character_name, v, profile=profile))
            extra = {"base_signature": bsig, "base_identity": identity, "prompt_fingerprint": fingerprint,
                     "prompt_rules": PROMPT_RULES}
            if v == "front":
                extra["front_reference"] = front_ref
            return expression_regen.render_character_image(
                character_name,
                output_stem=stem,
                equipped_pieces={}, equipped_items=[],
                pose_prompt="", expression_prompt="",
                bare_prompt=prompt, extra_negative=negative,
                image_use_case=BASE_FRONT_EDIT_USE_CASE if edit else BASE_USE_CASES[v],
                style_character=character,
                occasion="base_front" if v == "front" else "base_view",
                override_width=width, override_height=height,
                apply_state_modifiers=False,
                mesh_input_profile=mesh_profile,
                back_view=v == "back",
                reference_image=reference,
                require_reference=edit,
                sidecar_extra=extra,
                # The character's identity/pose LoRAs as on its tpose
                # render (tpose_loras, else loras); no slot LoRAs.
                character_loras=True, **({"raise_load": True} if raise_load else {}))

        def draw_front(final: Path) -> Tuple[Optional[Path], Optional[str]]:
            """``(stored path, warning)`` of the gated front attempts — each an
            edit of the frozen profile image while there is one (Ruling A74b)."""
            import contextlib
            # Ruling A87: the full-body reference while one is set, else the profile image.
            profile_image, source = (front_source_image(character_name, profile=profile)
                                     if front_ref["method"] == FRONT_FROM_REFERENCE else (None, ""))
            if profile_image is not None and (profile_image.name, source) != (front_ref.get("image"),
                                                                              front_ref.get("source", "")):
                # Another picture than the read above (one was set or cleared meanwhile): record what is edited.
                front_ref.update(image=profile_image.name)
                if source:
                    front_ref["source"] = source
                else:
                    front_ref.pop("source", None)
            if profile_image is None and front_ref["method"] == FRONT_FROM_REFERENCE:
                front_ref.clear()   # the picture went since the read above: the text render, recorded so
                front_ref["method"] = FRONT_FROM_TEXT
            with contextlib.ExitStack() as stack:
                reference: Optional[Path] = None
                if profile_image is not None:
                    reference, frozen_sha = stack.enter_context(_frozen_reference(profile_image, refs_dir))
                    # The picture changed between the read above and the copy: record what is edited.
                    front_ref["sha256"] = frozen_sha
                return gated_front(final, reference)

        def gated_front(final: Path, reference: Optional[Path]) -> Tuple[Optional[Path], Optional[str]]:
            attempts: List[Tuple[Path, Dict[str, Any]]] = []
            with tempfile.TemporaryDirectory(prefix=".handgate_", dir=refs_dir,
                                             ignore_cleanup_errors=True) as staging:
                for n in range(1, HAND_GATE_ATTEMPTS + 1):
                    stem = Path(staging) / f"attempt{n}" / final.name
                    stem.parent.mkdir()
                    try:
                        path = draw("front", stem, reference)
                    except Exception as e:  # noqa: BLE001 — keep what was rendered
                        if not attempts:
                            raise
                        logger.warning("Base body %s (%s): front attempt %d failed: %s",
                                       character_name, bsig, n, e)
                        break
                    if not path:
                        if not attempts:
                            return None, None
                        logger.warning("Base body %s (%s): front attempt %d rendered nothing",
                                       character_name, bsig, n)
                        break
                    gate = base_body_gates.hand_pose_gate(path)
                    attempts.append((path, gate))
                    logger.info("Base body %s (%s): front attempt %d hand gate %s (score %s, limit %s)",
                                character_name, bsig, n, "passed" if gate["ok"] else "failed",
                                gate.get("score"), gate.get("limit"))
                    if gate["ok"]:
                        break
                chosen, passed = base_body_gates.best_attempt([g for _p, g in attempts])
                record = {"ok": passed, "chosen": chosen + 1, "limit": base_body_gates.HAND_LIMIT,
                          "attempts": [g for _p, g in attempts]}
                stored = _publish_staged(attempts[chosen][0], final, record)
            if stored is None:
                return None, None
            return stored, None if passed else hand_gate_warning(len(attempts))

        def render(v: str, reference: Optional[Path]) -> Optional[Path]:
            final = refs_dir / f"{_kind(v)}_{bsig}"
            warning = None
            reserve_views(character_name, (v,))
            try:
                if v == "front":
                    path, warning = draw_front(final)
                    if path is not None:
                        from app.core import base_skin
                        path = base_skin.after_front_render(character_name, path, bsig=bsig, profile=profile,
                                                            source=str(front_ref.get("source") or ""))
                else:
                    path = draw(v, final, reference)
                    if path is not None and v in view_facing.SIDE_VIEWS:
                        # Ruling A91: a side view the detector is sure faces the wrong way is mirrored on the CPU.
                        view_facing.auto_correct(v, Path(path))
                error = None if path else "render failed"
            except Exception as e:  # noqa: BLE001 — one view never kills the run
                if raise_load and _is_load(e):
                    raise  # load: no failure record (the finally releases the view)
                path, error = None, str(e) or type(e).__name__
                logger.warning("Base body %s %s (%s) failed: %s", character_name, v, bsig, e)
            finally:
                release_views(character_name, (v,))
            _record(character_name, v, error or warning, warning=error is None and warning is not None)
            results[v] = str(path) if path else None
            return path

        front = find_ref_image(character_name, "tpose", bsig)
        if "front" in todo:
            front = render("front", None)
            if front is None:
                logger.warning("Base body %s (%s): front failed, views skipped", character_name, bsig)
                for v in todo:
                    if v != "front":
                        _record(character_name, v, "front render failed")
                return results
        views = [v for v in todo if v != "front"]
        if views and front is None:
            raise MissingFront("A base-body view requires the front image")
        if views:
            # Every view edits the front, on neutral grey (an RGBA cut-out
            # turns black at the backend).
            with neutral_view_reference(front, refs_dir) as reference:
                for v in views:
                    render(v, reference)
        logger.info("Base body %s (%s): %s", character_name, bsig,
                    {k: bool(p) for k, p in results.items()})
        if any(results.values()):
            # New base views: what hangs from an older base goes (artefact_graph).
            from app.core import artefact_graph
            artefact_graph.collect_quietly(character_name, "base images rendered")
        return results


def start_base_images(character_name: str, *, view: Optional[str] = None,
                      force: bool = False) -> None:
    """Run ``generate_base_images`` in a worker thread. The requested views
    count as running from THIS moment (the UI polls ``base_info``), and an
    error that ends the whole run is recorded on them."""
    views = BASE_VIEWS if view is None else (view,)
    reserve_views(character_name, views)

    def run() -> None:
        try:
            generate_base_images(character_name, view=view, force=force)
        except Exception as e:  # noqa: BLE001 — a worker thread reports, never raises
            logger.error("Base body render for %s failed: %s", character_name, e)
            for v in views:
                _record(character_name, v, str(e) or type(e).__name__)
        finally:
            release_views(character_name, views)

    threading.Thread(target=run, daemon=True, name=f"base-body-{character_name}").start()


def base_info(character_name: str) -> Dict[str, Any]:
    """UI info: ``{pipeline, humanoid, signature, images: {view: url|None},
    image_meta: {view: {model?, created_at?}|None}, status: {view: ...},
    model, outfit, hair}`` (``image_meta``: ``model_refs.image_tile_meta``
    of each stored view; ``model``: see
    ``base_model_info``; ``outfit``: the CURRENT outfit's model on the
    pipeline, see ``outfit_info`` — None off the pipeline; ``hair``:
    ``garments.hair_summary`` ``{item_id, status}`` — None without a worn
    hair item or off the pipeline); the image URLs
    carry the file's mtime so a re-render is fetched anew."""
    from app.core.model_refs import find_ref_image, image_tile_meta, is_humanoid
    profile = _profile_of(character_name, None)
    humanoid = bool(is_humanoid(character_name, profile=profile))
    signature = base_signature(character_name, profile=profile) if humanoid else ""
    images: Dict[str, Optional[str]] = {}
    image_meta: Dict[str, Optional[Dict[str, Any]]] = {}
    current = prompt_fingerprint(character_name, profile=profile) if humanoid else ""
    for view in BASE_VIEWS:
        path = find_ref_image(character_name, _kind(view), signature) if signature else None
        try:
            stamp = path.stat().st_mtime_ns if path else None
        except OSError:
            stamp = None
        images[view] = (f"/characters/{quote(character_name, safe='')}/base-body/images/{view}?v={stamp}"
                        if stamp is not None else None)
        if stamp is not None:
            tile = image_tile_meta(path)
            # The texts this view was rendered with (model_overview compares
            # them with the current ones for the OLDER_PROMPTS note; the
            # Ruling A74a carry-over through ``recorded_fingerprint``).
            tile["prompt_fingerprint"] = recorded_fingerprint(character_name, signature, view, _view_sidecar(path),
                                                              current=current, profile=profile)
            if view in view_facing.SIDE_VIEWS:
                tile["facing"] = _facing_tile(character_name, view, signature, path)
            image_meta[view] = tile
        else:
            image_meta[view] = None
    from app.core.timeutils import utc_now
    pipeline = is_base_pipeline(character_name, profile=profile)
    hair = None
    if pipeline and humanoid:
        try:
            from app.core import garments
            hair = garments.hair_summary(character_name, profile=profile)
        except Exception:  # noqa: BLE001 — the summary never breaks the poll
            logger.exception("Hair summary of %s failed", character_name)
    sides = {v: find_ref_image(character_name, _kind(v), signature) if signature else None
             for v in view_facing.SIDE_VIEWS}
    return {"pipeline": pipeline, "humanoid": humanoid,
            "signature": signature, "images": images, "image_meta": image_meta,
            "facing_pair": view_facing.pair_state(sides["left"], sides["right"]),
            "front_reference": _front_reference_info(character_name, signature, profile) if humanoid else None,
            "prompt_fingerprint": current,
            "skin": _skin_info(character_name, signature) if humanoid else None,
            "status": base_status(character_name),
            "model": base_model_info(character_name, signature),
            "outfit": outfit_info(character_name, base_sig=signature) if pipeline else None,
            "hair": hair,
            "now": _iso(utc_now())}


def _front_reference_info(character_name: str, signature: str,
                          profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The Base body tab's reference line (Ruling A74b): ``{method, source,
    image, url (the picture the front is an edit of, its mtime as cache key —
    "" without one), current, reason, note}``; ``source`` "full_body" when
    that picture is the full-body reference (Ruling A87), "" for the profile
    image; None when it cannot be read."""
    try:
        state = front_reference_state(character_name, signature or None, profile=profile)
        wanted = state["wanted"]
        image = (front_source_image(character_name, profile=profile)[0]
                 if wanted["method"] == FRONT_FROM_REFERENCE else None)
        try:
            stamp = image.stat().st_mtime_ns if image else None
        except OSError:
            stamp = None
        url = (f"/characters/{quote(character_name, safe='')}/images/{quote(image.name, safe='')}?v={stamp}"
               if image is not None and stamp is not None else "")
        source = str(wanted.get("source") or "")
        note = (NO_PROFILE_IMAGE_NOTE if wanted["method"] == FRONT_FROM_TEXT
                else "" if source == SOURCE_FULL_BODY else NO_FULL_BODY_NOTE)
        return {"method": wanted["method"], "source": source, "image": wanted.get("image", ""), "url": url,
                "current": state["current"], "reason": state["reason"], "note": note}
    except Exception:  # noqa: BLE001 — the poll never fails on it
        logger.exception("Front reference info of %s failed", character_name)
        return None


def _skin_info(character_name: str, signature: str) -> Optional[Dict[str, Any]]:
    """``base_skin.info`` for the front tile; None when it cannot be read."""
    try:
        from app.core import base_skin
        return base_skin.info(character_name, signature)
    except Exception:  # noqa: BLE001 — the poll never fails on it
        logger.exception("Skin step info of %s failed", character_name)
        return None


def _view_sidecar(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def base_image_path(character_name: str, view: str) -> Optional[Path]:
    """The stored image of one view for the CURRENT base signature."""
    if view not in BASE_VIEWS:
        return None
    from app.core.model_refs import find_ref_image
    return find_ref_image(character_name, _kind(view), base_signature(character_name))


# --- Facing of the side views (Ruling A91, ``view_facing``) -----------------

class MirrorRefused(RuntimeError):
    """A mirror that must wait (a step works on the views now) — a route answers 409."""


#: ``mirror_followup`` kinds: what a Mirror click makes due besides the view itself (the tile's button title).
FOLLOWUP_NO_MODEL = "no_model"          # no base model yet: nothing else changes
FOLLOWUP_UNUSED = "unused"              # the base model was built without this view
FOLLOWUP_RESTORES = "restores"          # turning back restores the view the base model was built from
FOLLOWUP_STALE = "stale"                # the base model becomes out of date: the next Build rebuilds it
FOLLOWUP_ALREADY_STALE = "already_stale"  # the base model is out of date already (the same rebuild)

MIRROR_BUSY = "A base-body step works on the views right now — mirror when it is done"
MIRROR_SIDES_ONLY = "Only the left and right views can be mirrored"


def _mesh_stage_count(character_name: str, signature: str) -> Optional[int]:
    """Hub jobs of a fresh mesh run of ``signature`` (``model3d.mesh_hub_stages``); None when unknown."""
    try:
        from app.core import model3d
        return len(model3d.mesh_hub_stages(character_name, signature))
    except Exception:  # noqa: BLE001 — an estimate, never a failure
        logger.debug("Mesh stages of %s %s unknown", character_name, signature, exc_info=True)
        return None


def mirror_followup(character_name: str, view: str, bsig: str, path: Path) -> Dict[str, Any]:
    """What mirroring (or turning back) the base ``view`` stored at ``path`` makes due: ``{kind, jobs,
    dressed}`` — ``kind`` one of the ``FOLLOWUP_*`` (judged against the base model's recorded
    ``view_images_sha256``, the same record ``model_overview.base_model_freshness`` compares), ``jobs`` the hub
    jobs of the base model's rebuild at the next Build (0 when nothing is rebuilt, None unknown), ``dressed``
    whether dressed side views are composited onto this view (``side_views_dressed``) — they follow it.
    The mirror itself costs no image job. Read-only."""
    from app.core import model3d
    dressed = side_views_dressed()
    model = model3d.find_model3d(character_name, bsig)
    if model is None:
        return {"kind": FOLLOWUP_NO_MODEL, "jobs": 0, "dressed": dressed}
    recorded = str((model3d._read_sidecar(model).get("view_images_sha256") or {}).get(view) or "")
    if not recorded:
        return {"kind": FOLLOWUP_UNUSED, "jobs": 0, "dressed": dressed}
    record = view_facing.mirror_record(path)
    if record and view_facing.restorable(path) and record.get("original_sha256") == recorded:
        return {"kind": FOLLOWUP_RESTORES, "jobs": 0, "dressed": dressed}
    kind = FOLLOWUP_STALE if recorded == file_sha256(path) else FOLLOWUP_ALREADY_STALE
    return {"kind": kind, "jobs": _mesh_stage_count(character_name, bsig), "dressed": dressed}


def _facing_tile(character_name: str, view: str, bsig: str, path: Path) -> Optional[Dict[str, Any]]:
    """``view_facing.tile_state`` of a base side view with its ``followup`` (``mirror_followup``); None when
    it cannot be read (the poll never fails on it)."""
    try:
        tile = view_facing.tile_state(view, path)
        if tile is not None:
            tile["followup"] = mirror_followup(character_name, view, bsig, path)
        return tile
    except Exception:  # noqa: BLE001
        logger.exception("Facing of %s %s view failed", character_name, view)
        return None


def mirror_base_view(character_name: str, view: str) -> Dict[str, Any]:
    """The Base body tab's "Mirror" of a side view (Ruling A91): ``view_facing.toggle_mirror`` of the stored
    view of the CURRENT base signature — mirrored, or turned back to its original. No image job; the base
    model built from the old bytes is then stale (``mirror_followup``). Returns ``{mirrored, facing}``
    (``facing`` = the tile's new state). Raises ``ValueError`` for another view, ``FileNotFoundError``
    without a stored view, ``MirrorRefused`` while a base-body step or a 3D run of the character goes
    (``base_steps_running``, ``model3d.generation_running``, the base render lock)."""
    from app.core import model3d
    from app.core.model_refs import find_ref_image
    if view not in view_facing.SIDE_VIEWS:
        raise ValueError(MIRROR_SIDES_ONLY)
    if base_steps_running(character_name) or model3d.generation_running(character_name):
        raise MirrorRefused(MIRROR_BUSY)
    lock = _char_lock(character_name)   # a base render holds it for its whole run
    if not lock.acquire(blocking=False):
        raise MirrorRefused(MIRROR_BUSY)
    try:
        bsig = base_signature(character_name)
        path = find_ref_image(character_name, _kind(view), bsig)
        if path is None:
            raise FileNotFoundError(f"No stored {view} view")
        result = view_facing.toggle_mirror(path)
    finally:
        lock.release()
    return {"mirrored": result["mirrored"], "facing": _facing_tile(character_name, view, bsig, path)}


# --- The base model ---------------------------------------------------------

# Base model runs in memory, like the image status: character -> base
# signature of the run in progress, and the last failed run per character.
# Runs of one character are serial (model3d's generation guard).
_model_running: Dict[str, str] = {}
_model_failed: Dict[str, Dict[str, Any]] = {}


def check_model_ready(character_name: str, *,
                      profile: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], str]:
    """``(profile, base signature)`` when a base model can be built: the
    preconditions of the images (``check_renderable``) plus the stored front
    image of the CURRENT base signature (``MissingInput`` without it)."""
    profile = check_renderable(character_name, profile=profile)
    bsig = base_signature(character_name, profile=profile)
    from app.core.model_refs import find_ref_image
    if find_ref_image(character_name, "tpose", bsig) is None:
        raise MissingInput("No base-body images. Render the base-body images first")
    return profile, bsig


def generate_base_model(character_name: str, *, force: bool = False,
                        raise_load: bool = False) -> Dict[str, Any]:
    """Build the rigged base model from the base images. Blocking (minutes)
    — call from a worker thread.

    The staged mesh run of ``model3d.generate_for_current_outfit`` with
    ``signature=<bsig>`` and ``base=True`` (frozen into the hub-op inputs):
    source ``tpose_<bsig>``, every stored base view, the character's mesh
    occasion; after the rig the parts its unclothed views were rendered for
    (Ruling A49) and no distance tier, the sidecar records ``"base": true``
    and the mesh variant of its front, and the unrigged checkpoint
    ``model3d/unrigged/<bsig>.glb`` stays. Cached per base signature unless
    ``force``.

    ``raise_load`` (the improvements queue's ``base_refresh``): load — a
    ``BackendBusyError`` / ``MediaGenerationDisabled`` (``_is_load``) or a
    ``HubOpBusy`` (the target in flight) — propagates WITHOUT the failure
    record, so the stored base model stays ``ready`` and the step comes back
    later; every other caller records load like any error."""
    from app.core import model3d
    from app.core.hub_ops import HubOpBusy
    from app.core.timeutils import utc_now
    bsig = ""
    error: Optional[str] = None
    try:
        _profile, bsig = check_model_ready(character_name)
        with _status_lock:
            _model_running[character_name] = bsig
            _model_failed.pop(character_name, None)
        result = model3d.generate_for_current_outfit(character_name, force=force,
                                                     signature=bsig, base=True)
        if not result.get("ok"):
            error = str(result.get("error") or "Base model generation failed")
        else:
            # R14: a worn garment whose fit is not on this base model starts
            # its chain (fit only when just the model bytes changed).
            from app.core import garments
            garments.after_base_model(character_name)
            # The chains of an older base go now (app/core/artefact_graph.py, ruling "base regenerated").
            from app.core import artefact_graph
            artefact_graph.collect_quietly(character_name, "base model generated")
        return result
    except Exception as e:
        if not (raise_load and (_is_load(e) or isinstance(e, HubOpBusy))):
            error = str(e) or type(e).__name__
        raise
    finally:
        with _status_lock:
            _model_running.pop(character_name, None)
            if error is not None:
                _model_failed[character_name] = {"signature": bsig, "error": error,
                                                 "failed_at": utc_now()}


def start_base_model(character_name: str, *, force: bool = False) -> bool:
    """Run ``generate_base_model`` in a worker thread under model3d's
    per-character generation guard and lock. False when a 3D model
    generation already runs for the character. The run counts as running
    from THIS moment (the UI polls ``base_info``)."""
    from app.core import model3d
    bsig = base_signature(character_name)
    with _status_lock:
        reserved = character_name not in _model_running
        if reserved:
            _model_running[character_name] = bsig
    started = model3d.trigger_generation(character_name, force=force, base=True)
    if not started and reserved:
        with _status_lock:
            _model_running.pop(character_name, None)
    return started


def base_model_info(character_name: str, signature: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """``{signature, url, created_at, status, error}`` of the base model of
    the CURRENT base signature, or None when none is stored, running or
    failed. ``status``: ``running``; ``failed`` (the last run ended with an
    error, or the stored model is the static checkpoint whose rig failed —
    its sidecar ``rig_error``); ``unrigged`` (a static checkpoint without a
    run, e.g. one interrupted by a restart); ``ready``. ``url`` serves the
    stored model (``/characters/<name>/model3d/file?signature=<bsig>``)."""
    from app.core import model3d
    if signature is None:
        from app.core.model_refs import is_humanoid
        signature = base_signature(character_name) if is_humanoid(character_name) else ""
    if not signature:
        return None
    with _status_lock:
        running = _model_running.get(character_name)
        failure = dict(_model_failed.get(character_name) or {})
    path = model3d.find_model3d(character_name, signature)
    meta = model3d._read_sidecar(path) if path else {}
    if running == signature:
        status, error = "running", ""
    elif failure.get("signature") == signature:
        status, error = "failed", failure.get("error") or ""
    elif path is None:
        return None
    elif meta.get("rig_error"):
        status, error = "failed", str(meta["rig_error"])
    elif meta.get("rig") in (None, "", "none"):
        status, error = "unrigged", ""
    else:
        status, error = "ready", ""
    return {"signature": signature,
            "url": model3d.signature_model_url(character_name, signature) if path else None,
            "created_at": meta.get("created_at") or None,
            "status": status, "error": error}


# --- Outfits on the base body (spec § B) -----------------------------------

# The edit form of the S1 spike (claude-out/s1-base-body/kleidung_real/
# front.json): keep everything, change only the clothing.
DRESS_KEEP = ("Keep the image exactly as it is: the same person, same body shape, same pose, same arm and hand "
              "position, same framing and background.")
#: ``DRESS_KEEP`` of a haired base (``hair_text``): the hair is named, so the
#: retexture worker never paints skin onto the hair geometry.
DRESS_KEEP_HAIR = ("Keep the image exactly as it is: the same person, same hair, same body shape, same pose, same "
                   "arm and hand position, same framing and background.")
DRESS_STYLE_NEGATIVE = ("illustration, anime, cgi, 3d render, painting, airbrushed skin, plastic skin, smooth "
                        "flawless skin, overexposed, glossy, fantasy, studio lighting, cartoon, drawing, sketch, "
                        "watermark, signature, text, logo, deformed, blurry, low quality")
# The spike's garment words, each with the words that mean the outfit itself
# names it — such a term leaves the negative (a skirt must not be forbidden
# from an outfit that IS a skirt). "hair": the base body is bald until the
# hair mesh (phase 4); the edit must not grow any — a haired base
# (``hair_text``) leaves it out (``dress_negative(keep_hair=True)``).
DRESS_GARMENT_NEGATIVE = (
    ("loose clothing", r"loose"),
    ("baggy", r"baggy"),
    ("skirt", r"skirts?"),
    ("dress", r"dress(?:es)?"),
    ("jacket", r"jackets?|coats?|blazers?"),
    ("shoes", r"shoes?|boots?|sandals?|sneakers?|heels|slippers?|loafers?|footwear"),
    ("socks", r"socks?|stockings?|tights"),
    ("hair", r"hair"),
)

# The view sentence that opens a dressed edit of a non-front view: without
# it, back and side edits came out turned toward the camera (end-to-end run
# 2026-11-09; the left wording verified there). The front needs none.
DRESS_VIEW = {
    "back": ("This is a back view seen directly from behind, the figure faces away from the camera; keep it a "
             "back view, do not turn the figure toward the camera."),
    "left": ("This is a strict left side profile view, the whole body in profile facing the left edge of the "
             "frame; keep it a side profile view, do not turn the figure toward the camera."),
    "right": ("This is a strict right side profile view, the whole body in profile facing the right edge of the "
              "frame; keep it a side profile view, do not turn the figure toward the camera."),
}

#: The views every outfit dresses and hands to the body-retexture worker.
CORE_DRESSED_VIEWS = ("front", "back")
#: The side views an outfit dresses too when the world setting
#: ``base_body.dressed_side_views`` is on (``dressed_views``). Off by default:
#: unmasked side views put cloth on the arm in profile (measured
#: 2026-11-09); the worker now skips the arm in them (``--side-arm-margin``,
#: plan-side-views-arm-mask.md in the worker repo), but the hips still land
#: slightly below front+back alone. Off, the base body's left/right views
#: stay mesh inputs of the base model only.
SIDE_DRESSED_VIEWS = ("left", "right")
#: Views made in two steps (a draft from the dressed front, then the CPU
#: composite of its clothing onto the base view, ``view_composite``):
#: everything dressed but the front.
DRAFT_VIEWS = ("back", "left", "right")
#: The draft's occasion per two-step view — the only hub job of such a view
#: (Task 11g, Ruling C1: the model fit and its occasions outfit_back /
#: outfit_side are gone).
DRAFT_OCCASIONS = {"back": "outfit_back_draft", "left": "outfit_side_draft", "right": "outfit_side_draft"}
#: Default of ``base_body.side_arm_margin`` and its bounds (fraction of the
#: body height the worker skips around the arm in a side view).
SIDE_ARM_MARGIN_DEFAULT = 0.03
SIDE_ARM_MARGIN_MAX = 0.2
SIDE_VIEW_NOT_DRESSED = ("On the base-body pipeline only the front and the back are dressed — "
                         "the side views belong to the base body (Base body tab)")
DRESSED_FRONT_FIRST = "Render the dressed front first — the back draft is made from it"
#: ``DRESSED_FRONT_FIRST`` when the dressed front IS stored but was edited from a base front replaced since
#: (Ruling A26 c — the skin step rewrote the base front while the dressed front rendered).
DRESSED_FRONT_STALE = "The dressed front is stale — the base front changed; the back draft is not made from it"


def side_views_dressed() -> bool:
    """The world setting ``base_body.dressed_side_views`` (read live)."""
    from app.core import config
    from app.core.config_schema import field_default
    return config.get("base_body.dressed_side_views",
                      field_default("base_body", "dressed_side_views")) is True


def dressed_views() -> Tuple[str, ...]:
    """The views an outfit dresses and hands to the worker: front and back,
    plus left and right with ``side_views_dressed``."""
    return CORE_DRESSED_VIEWS + SIDE_DRESSED_VIEWS if side_views_dressed() else CORE_DRESSED_VIEWS


def dressed_view_jobs() -> int:
    """Hub jobs of ONE set of dressed views on its first attempts: the front
    edit plus a draft per other ``dressed_views()`` view — the composite onto
    the base view is CPU work (Task 11g) — 2 with front + back, 4 with the
    side views on (``rebuild_cost`` and the Build's plan, ``figure_build``,
    count with it)."""
    return 1 + (len(dressed_views()) - 1)


def side_arm_margin() -> float:
    """The world setting ``base_body.side_arm_margin``, clamped to
    0..``SIDE_ARM_MARGIN_MAX``; an unreadable value is the default."""
    from app.core import config
    raw = config.get("base_body.side_arm_margin", SIDE_ARM_MARGIN_DEFAULT)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return SIDE_ARM_MARGIN_DEFAULT
    if value != value:  # NaN
        return SIDE_ARM_MARGIN_DEFAULT
    return min(max(value, 0.0), SIDE_ARM_MARGIN_MAX)

# The back is two steps (user decision 2026-11-09, measured on the end-to-end
# run): a DRAFT rendered fresh from the dressed front with ``DRAFT_PROMPTS``
# (the turn only, never the clothing — Ruling A29) — then the
# COMPOSITE of the draft's clothing onto the base back on the CPU
# (``view_composite``, Task 11g, Ruling C1; it replaced the model fit, which
# put nothing on, moved the figure or invented clothing). Dressed side views
# (``dressed_views``) go the same way with their side sentence.
#: Use case of the dressed front edit: empty style and negative (config) —
#: the ``DRESS_KEEP`` sentence is the whole prompt, like the base views.
DRESS_USE_CASE = "outfit_edit"
#: The draft keeps the base negative minus its no-clothing words.
DRAFT_NEGATIVE = ", ".join((HAIR_NEGATIVE, POSE_NEGATIVE))
#: ``DRAFT_NEGATIVE`` of a haired base (``hair_text``): headwear only.
HAIRED_DRAFT_NEGATIVE = ", ".join((HEADWEAR_NEGATIVE, POSE_NEGATIVE))
#: An image whose alpha never drops below this carries no matte (``cut_out``).
CUTOUT_ALPHA = 16
#: Drafts per two-step view at most: a draft whose composite fails its
#: checks (``view_composite.check``) or the view's gates is rendered once
#: more (new seed); the composite itself is deterministic.
DRAFT_ATTEMPTS = 2
#: Where the drafts live: a subdirectory of model_refs, so no reader of
#: the stored refs (find_ref_image, mesh inputs, the outfit scans) parses
#: them as refs of their own; the reference gate still accepts them.
DRAFT_DIR = "drafts"

BASE_IMAGES_MISSING = "Base body images missing — render them in the Base body tab"
BASE_MODEL_MISSING = "Base body model missing — generate it in the 3D tab"
DRESSED_IMAGES_MISSING = "Dressed images missing — render the outfit's pose images"
OLDER_BASE = "Built on an older base body"
BEFORE_PIPELINE = "Made without the base body"
DETAIL_CHANGED = "Built for another body detail under the clothing"
COVERED_MISSING = ("The base body has no current covered variant — the outfit was built from the full base; "
                   "rebuild the base body's extension bones")
#: An outfit model built while an own-mesh piece it wears had no fit — now it has one.
MESH_ITEM_READY = "An own-mesh piece painted on here has its garment mesh now"
#: The ``garment_warnings`` entry of an own-mesh piece in the body shape until its mesh is ready (ruling A11);
#: ``reason``: why it has no mesh — ``NO_MESH_FIT`` or its chain's failure (``MESH_ITEM_CHAIN_FAILED``: no
#: automatic trigger retries that fsig, ``garments.cached_failure``).
MESH_ITEM_IN_BODY = "{item} is in the body until its own mesh is ready: {reason}"
NO_MESH_FIT = "no accepted fit on the current base model"
#: Outfit body mode ``mesh`` (ruling 2026-11-10): a flagged piece without an
#: accepted fit is never painted (meshed) into the outfit body — it is
#: missing from the outfit model until its mesh is accepted. The same English
#: text is a React key (Wardrobe), built there from the parts.
MESH_ITEM_NOT_READY = "{item}: own mesh not ready — not shown until its mesh is accepted ({reason})"
#: ... the reason of a piece whose garment chain failed for its fsig (only
#: Regenerate in the Wardrobe retries it, ``garments.cached_failure``).
MESH_ITEM_CHAIN_FAILED = "{step} — {error} — Regenerate in the Wardrobe"


def dress_text(character_name: str, view: str, *, pieces: Optional[Dict[str, str]],
               items: Optional[list], profile: Optional[Dict[str, Any]] = None,
               mesh_items: Iterable[str] = (), piece_state: Optional[Dict[str, str]] = None) -> str:
    """What the dressed edit says the figure now wears — "" for an undressed
    combination (nothing worn, or an undressed free-text wardrobe).

    The outfit text of the mesh-input render (``render_outfit(mesh_input=
    True, back_view=view == "back")``), composed as
    ``expression_regen.render_character_image`` composes its "is wearing"
    layer: the pieces, else (nothing structured worn) a dressed free-text
    wardrobe's text; the items follow with their own verb ("holding …").

    ``mesh_items``: own-mesh pieces left out of the texture on this outfit
    (``mesh_items_unpainted`` of ``mesh_record``: the grafted pieces) — left
    out of the pieces
    BEFORE the renderer resolves ``covers`` / ``partially_covers``, so what
    lies under them is painted (plan 2026-11-09-base-body-phase5 Task 4).
    Pieces that are ALL mesh items leave nothing to paint: "" (never the
    free-text wardrobe).

    ``piece_state``: the open pieces (``{item_id: "open"}``); None → the
    profile's (``outfit_options.piece_states``). An open piece says
    ``", worn open"``; a closed one adds nothing (mesh input, D-A1)."""
    from app.core.outfit_renderer import render_outfit
    meshed = {str(i) for i in mesh_items or ()}
    worn = {slot: iid for slot, iid in (pieces or {}).items() if iid and str(iid) not in meshed}
    profile = dict(_profile_of(character_name, profile))
    profile["equipped_pieces"] = dict(worn)
    profile["equipped_items"] = list(items or [])
    state = None if piece_state is None else {i: s for i, s in piece_state.items() if i in set(worn.values())}
    rendered = render_outfit(profile=profile, equipped_pieces=dict(worn),
                             equipped_items=list(items or []), back_view=view == "back",
                             mesh_input=True, piece_state=state)
    wear = (rendered.get("pieces") or "").strip()
    if not wear and not (pieces or items):
        free = rendered.get("full") or ""
        if free.startswith("wearing: "):
            wear = free[len("wearing: "):].strip()
    held = (rendered.get("items") or "").strip()
    if wear and held:
        return f"they now wear {wear}, {held}"
    if wear:
        return f"they now wear {wear}"
    if held:
        return f"they are now {held}"
    return ""


def dress_garment_terms(text: str, *, keep_hair: bool = False) -> List[str]:
    """The ``DRESS_GARMENT_NEGATIVE`` terms ``text`` does not name;
    ``keep_hair`` (a haired base) leaves "hair" out as well."""
    return [term for term, pattern in DRESS_GARMENT_NEGATIVE
            if not (keep_hair and term == "hair")
            and not re.search(rf"\b(?:{pattern})\b", text or "", re.IGNORECASE)]


def dress_negative(text: str, *, keep_hair: bool = False) -> str:
    """The spike's negative minus the garment terms ``text`` names
    (``dress_garment_terms``)."""
    return ", ".join([DRESS_STYLE_NEGATIVE, *dress_garment_terms(text, keep_hair=keep_hair)])


def dress_prompt(character_name: str, view: str, *, pieces: Optional[Dict[str, str]],
                 items: Optional[list], profile: Optional[Dict[str, Any]] = None,
                 mesh_items: Iterable[str] = (), bald: bool = False,
                 text: Optional[str] = None, hair: Optional[str] = None,
                 hair_edit: bool = False) -> Tuple[str, str]:
    """``(prompt, negative)`` of the dressed edit of one view: the spike's
    edit form "Keep the image exactly as it is: … Only change their
    clothing: they now wear {outfit}." — opened by the view sentence
    ``DRESS_VIEW[view]`` for back/left/right — and its negative without the
    garment words the outfit names. ValueError for an undressed combination
    (that one copies the views, there is nothing to edit). The outfit text
    is ``text`` when given (``figure_texts``), else ``dress_text`` with
    ``mesh_items`` left out. ``bald`` (``_bald_edit``: a meshed shape under
    an own hair mesh) closes the edit with the base body's bald head
    (``BALD_HEAD``) and adds its hair negative (``HAIR_NEGATIVE``). A haired
    base (``hair_text``) keeps its hair: ``DRESS_KEEP_HAIR`` and no "hair"
    in the negative.

    ``hair`` (hairstyles, D4): the hair of the body edited when it is not the
    plain body's — a hairstyle's text, or ``garment_hair.BALD`` — None = the
    plain body's (``hair_text``). ``hair_edit``: the edit puts that hair ON
    (a body shape's own views, made from the plain body's): the text then
    says so (``_edit_prompt``), and an edit without clothing text is a hair
    edit alone. ValueError for an edit that changes nothing."""
    from app.core.garment_hair import BALD
    if view not in BASE_VIEWS:
        raise ValueError(f"unknown base-body view: {view!r}")
    profile = _profile_of(character_name, profile)
    if text is None:
        text = dress_text(character_name, view, pieces=pieces, items=items, profile=profile,
                          mesh_items=mesh_items)
    worn_hair = hair_text(character_name, profile=profile) if hair is None else ("" if hair == BALD else hair)
    new_hair = worn_hair if hair_edit and hair is not None else ""
    if not text and not new_hair and not (hair_edit and bald):
        raise ValueError("An undressed combination has no dressed edit")
    haired = bool(worn_hair)
    negative = dress_negative(text, keep_hair=haired)
    return (_edit_prompt(view, text, bald=bald, haired=haired, new_hair=new_hair),
            (f"{negative}, {HAIR_NEGATIVE}" if bald else negative))


def _edit_prompt(view: str, text: str, *, bald: bool = False, haired: bool = False, new_hair: str = "") -> str:
    """The dressed edit's prompt of one view for the dress text ``text``;
    ``bald`` appends the base body's bald head (``BALD_HEAD``, the same
    words the base front is rendered with); ``haired`` opens with
    ``DRESS_KEEP_HAIR`` instead of ``DRESS_KEEP``. ``new_hair`` (a body
    shape of another hairstyle, D4): the edit changes the hair to it too —
    with no dress text it changes the hair alone (to ``BALD_HEAD`` with
    ``bald``). Without ``new_hair`` and with a dress text the prompt is the
    one before hairstyles, byte for byte."""
    if not text:
        hair = new_hair or (BALD_HEAD if bald else "")
        edit = f"{DRESS_KEEP} Only change their hair: {hair}."
    elif new_hair:
        edit = f"{DRESS_KEEP} Only change their clothing and their hair: {text}. Their hair: {new_hair}."
    else:
        edit = f"{DRESS_KEEP_HAIR if haired else DRESS_KEEP} Only change their clothing: {text}."
    if bald and text:
        edit = f"{edit} {BALD_HEAD[:1].upper()}{BALD_HEAD[1:]}."
    view_sentence = DRESS_VIEW.get(view)
    return f"{view_sentence} {edit}" if view_sentence else edit


# Outfit status, in memory like the base status: (character, stage) ->
# signature of the run in progress (stage "images" or "model"), and the last
# failure per (character, signature).
_outfit_running: Dict[Tuple[str, str], str] = {}
_outfit_failed: Dict[Tuple[str, str], Dict[str, Any]] = {}


def _outfit_start(character_name: str, signature: str, stage: str) -> None:
    with _status_lock:
        _outfit_running[(character_name, stage)] = signature


def outfit_running(character_name: str) -> bool:
    """Whether a stage of an outfit model of the character (its dressed views, its body shape or its model — any
    signature) runs now. Never base-body work (Ruling A55, ``figure_build.base_activity``)."""
    with _status_lock:
        return any(name == character_name for name, _stage in _outfit_running)


def _outfit_end(character_name: str, signature: str, stage: str, error: Optional[str], *,
                interrupted: bool = False, refused: bool = False) -> None:
    """End a stage: a failure is stored for the signature; a success clears
    a failure of the same stage (a model success clears every failure).
    ``interrupted`` (load or the media switch stopped the stage): the stage
    ends without touching any failure record — neither stored nor cleared.
    ``refused`` (Ruling A61): the failure is one the same inputs repeat
    (``outfit_refusal``)."""
    from app.core.timeutils import utc_now
    with _status_lock:
        if _outfit_running.get((character_name, stage)) == signature:
            _outfit_running.pop((character_name, stage), None)
        if interrupted and error is None:
            return
        key = (character_name, signature)
        if error is not None:
            _outfit_failed[key] = {"stage": stage, "error": error, "failed_at": utc_now(), "refused": refused}
        elif stage == "model" or (_outfit_failed.get(key) or {}).get("stage") == stage:
            _outfit_failed.pop(key, None)


def outfit_failure(character_name: str, signature: str) -> str:
    """The last recorded failure of a dressed-view (or model) run of
    ``signature`` — an outfit or a shape key — or "" (the Build's reason
    when a view stays missing, Ruling C4)."""
    with _status_lock:
        return str((_outfit_failed.get((character_name, signature)) or {}).get("error") or "")


def outfit_refusal(character_name: str, signature: str) -> str:
    """The last failure of the outfit MODEL of ``signature`` when it is one the same inputs repeat (Ruling A61:
    not a missing worker, a timeout or load), else ""."""
    with _status_lock:
        record = dict(_outfit_failed.get((character_name, signature)) or {})
    return str(record.get("error") or "") if record.get("stage") == "model" and record.get("refused") else ""


def _is_load(e: BaseException) -> bool:
    """Whether ``e`` (or an exception in its ``__cause__`` / ``__context__``
    chain) is load or the media switch: ``BackendBusyError`` /
    ``MediaGenerationDisabled`` — what a ``raise_load`` caller gets back
    instead of a failure."""
    from app.imagegen.base import BackendBusyError, MediaGenerationDisabled
    seen = set()
    while e is not None and id(e) not in seen:
        if isinstance(e, (BackendBusyError, MediaGenerationDisabled)):
            return True
        seen.add(id(e))
        e = e.__cause__ or e.__context__
    return False


def _ref_sidecar(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {}
    try:
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


# path -> ((size, mtime_ns, inode), sha256): content identity of base files,
# hashed again only when the file's stat changes (a copied world rehashes
# once and keeps its outfits current).
_hash_cache: Dict[str, Tuple[Tuple[int, int, int], str]] = {}


def file_sha256(path: Optional[Path]) -> str:
    """sha256 of a file's content, "" when it does not exist."""
    if path is None:
        return ""
    try:
        stat = path.stat()
    except OSError:
        return ""
    key = (stat.st_size, stat.st_mtime_ns, stat.st_ino)
    with _status_lock:
        cached = _hash_cache.get(str(path))
    if cached and cached[0] == key:
        return cached[1]
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""
    with _status_lock:
        _hash_cache[str(path)] = (key, digest)
    return digest


def base_model_sha256(character_name: str, bsig: str) -> str:
    """Content identity of the stored rigged base model of ``bsig`` (the
    REAL model directory, also from inside a staged run), "" without one.
    An outfit model records it: a regenerated base under the same signature
    makes every outfit model built on the old one stale."""
    from app.models.character import get_character_dir
    return file_sha256(get_character_dir(character_name) / "model3d" / f"{bsig}.glb")


def current_base(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Optional[Tuple[str, str]]:
    """``(base signature, base model sha256)`` of a character on the
    pipeline — what an outfit model must have been built on to be current —
    or None off the pipeline."""
    profile = _profile_of(character_name, profile)
    if not is_base_pipeline(character_name, profile=profile):
        return None
    bsig = base_signature(character_name, profile=profile)
    return bsig, base_model_sha256(character_name, bsig)


def built_on_current_base(meta: Dict[str, Any], base: Tuple[str, str]) -> bool:
    """Whether an outfit model's sidecar names the current base body."""
    return (meta.get("base_signature") == base[0]
            and meta.get("base_model_sha256") == base[1])


def outfit_variant(character_name: str, pieces: Optional[Dict[str, str]], *,
                   profile: Optional[Dict[str, Any]] = None) -> str:
    """Which base model an outfit of ``pieces`` (``{clothing slot: item
    id}``) is built from: ``"covered"`` (``model3d/covered/<bsig>.glb``,
    without the ``exposed_only`` extension groups) when a worn piece hides
    them (``extension_rig.hides_exposed_detail``: it covers their slot and
    does not set ``outfit_piece.exposed_detail``), else ``"rigged"``."""
    from app.core.extension_rig import exposed_only_slots, hides_exposed_detail, rig_groups_for
    from app.core.motion_item_cache import item_snapshot
    if not pieces:
        return "rigged"
    # Cheap first pass (this runs inside model lookups): without any piece
    # hiding a slot of ANY package's exposed-only rig, no profile is read.
    slots = exposed_only_slots()
    items = item_snapshot()
    if not slots or not hides_exposed_detail([{"exposed_only": True, "covered_by": slots}], pieces, items):
        return "rigged"
    profile = _profile_of(character_name, profile)
    groups = rig_groups_for(character_name, profile=profile, mesh_variant="")
    return "covered" if hides_exposed_detail(groups, pieces, items) else "rigged"


def variant_current(character_name: str, meta: Dict[str, Any], *,
                    profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether a pipeline outfit model was built from the base model its
    pieces call for now (``outfit_variant``). A sidecar without
    ``base_variant`` was built from the full base (``"rigged"``); an
    undressed combination always is. A build that wanted the covered variant
    but found none (``covered_missing``) stays current until a covered
    variant newer than it exists — no rebuild on every trigger while the
    base has none. An undressed copy of an outfit whose pieces are all own
    meshes still calls for the variant its pieces decide (the garment meshes
    cover the body like painted pieces would)."""
    wanted = ("rigged" if meta.get("dressed") is False and not mesh_items_intended(meta)
              else outfit_variant(character_name, meta.get("pieces") or {}, profile=profile))
    built = meta.get("base_variant") or "rigged"
    if built == wanted:
        return True
    if wanted == "covered" and meta.get("covered_missing") and meta.get("base_signature"):
        from app.core.model3d import COVERED_DIR, _read_sidecar, get_model3d_dir
        covered = get_model3d_dir(character_name) / COVERED_DIR / f"{meta['base_signature']}.glb"
        made = _read_sidecar(covered).get("created_at") if covered.is_file() else None
        return not (made and made > str(meta.get("created_at") or ""))
    return False


# --- Own-mesh outfit pieces (plan 2026-11-09-base-body-phase5-mesh-items, Task 4;
# since plan 2026-11-12-unified-worn-pieces Task 6 decided by the delivered figure) ---
#
# The record (sidecar ``mesh_items`` of every dressed view and outfit model,
# ``mesh_record``): ``intended`` = the own-mesh pieces worn outside the body
# (item mode ``own_mesh``), ``effective`` = those grafted
# (``figure.Figure.own``: a fit on the delivered shape), ``unpainted`` = the
# pieces the dress text LEFT OUT (``mesh_items_unpainted``: the grafted ones,
# and ``left_out`` of a figure recorded before ruling A11), ``in_body`` = the
# own-mesh pieces in the body shape (ruling A11, ``figure.Figure.in_body_own``:
# their mesh is missing or not taken out yet — the dress text keeps them; the
# assembly grafts each once its fit exists, ``mesh_items_in_body``),
# ``missing`` = item -> reason for left-out pieces, ``warnings`` = the pieces
# in the body until their mesh is ready (``MESH_ITEM_IN_BODY``) and
# ``figure`` = the delivered figure the views were made for
# (``figure.Figure.as_dict``).
#
# The pieces are judged NOW, never from the record alone
# (``mesh_items_missing``): a piece whose fit landed since is simply grafted.

def mesh_items_intended(record: Dict[str, Any]) -> List[str]:
    """The own-mesh pieces a dressed view / outfit model was made for
    (sidecar ``mesh_items.intended``), [] when it records none."""
    mesh = record.get("mesh_items") if isinstance(record, dict) else None
    if not isinstance(mesh, dict):
        return []
    return [str(i) for i in mesh.get("intended") or [] if isinstance(i, str) and i]


def mesh_items_in_body(record: Optional[Dict[str, Any]]) -> List[str]:
    """The own-mesh pieces a dressed view / outfit model keeps IN its body
    shape until their mesh is ready (sidecar ``mesh_items.in_body``, ruling
    A11), sorted; [] when it records none."""
    mesh = record.get("mesh_items") if isinstance(record, dict) else None
    if not isinstance(mesh, dict):
        return []
    return sorted({str(i) for i in mesh.get("in_body") or [] if isinstance(i, str) and i})


def mesh_items_unpainted(record: Optional[Dict[str, Any]]) -> List[str]:
    """The own-mesh pieces a dressed view / outfit model LEFT OUT of its dress
    text (block above): the recorded ``unpainted``, else ``effective`` (a
    record from before footwear was left out); sorted, [] when it records
    none."""
    mesh = record.get("mesh_items") if isinstance(record, dict) else None
    if not isinstance(mesh, dict):
        return []
    key = "unpainted" if isinstance(mesh.get("unpainted"), list) else "effective"
    return sorted({str(i) for i in mesh.get(key) or [] if isinstance(i, str) and i})


def _mesh_items_pending(record: Dict[str, Any]) -> List[str]:
    """Intended but not left out: the pieces painted on."""
    return sorted(set(mesh_items_intended(record)) - set(mesh_items_unpainted(record)))


def _footwear_items(item_ids: Iterable[str]) -> List[str]:
    """The footwear pieces (``garment_set.FOOTWEAR``, judged now) among ``item_ids``, sorted."""
    from app.core import garment_set
    from app.models.inventory import get_item
    return sorted(i for i in set(item_ids) if garment_set.garment_kind_of(get_item(i)) == garment_set.FOOTWEAR)


def _record_base_sha(character_name: str, record: Dict[str, Any], bsig: Optional[str],
                     base_sha: Optional[str]) -> str:
    if base_sha is not None:
        return base_sha
    bsig = bsig or str(record.get("base_signature") or "")
    if not is_base_signature(bsig):
        bsig = base_signature(character_name)   # a view edited from a meshed shape
    return base_model_sha256(character_name, bsig)


def mesh_items_ready(character_name: str, record: Dict[str, Any], *, bsig: Optional[str] = None,
                     base_sha: Optional[str] = None) -> List[str]:
    """The pieces a dressed view / outfit model (its sidecar ``record``) left
    painted on that now HAVE an accepted fit on the current base model
    (``base_sha``, else the stored model of ``bsig``, else of the record's
    ``base_signature``) — shown on the view's tile (``MESH_ITEM_READY``); the
    view itself is judged by the delivered figure (``dressed_image``). []
    when none (cheap: no fit is read without a pending piece)."""
    pending = _mesh_items_pending(record)
    if not pending:
        return []
    base_sha = _record_base_sha(character_name, record, bsig, base_sha)
    if not base_sha:
        return []
    from app.core import garment_store
    return [item_id for item_id in pending
            if garment_store.accepted_fit(character_name, item_id, base_model_sha=base_sha) is not None]


def mesh_items_missing(character_name: str, record: Dict[str, Any], *, bsig: Optional[str] = None,
                       base_sha: Optional[str] = None) -> List[Tuple[str, str]]:
    """The pieces a dressed view / outfit model left out that have NO accepted
    fit on the current base model now (``base_sha`` / ``bsig`` as in
    ``mesh_items_ready``) — missing from the outfit model until their fit is
    accepted. ``[(item_id, reason)]``, the reason the build recorded
    (``mesh_items.missing``), else ``NO_MESH_FIT`` / ``BASE_MODEL_MISSING``."""
    mesh = record.get("mesh_items") if isinstance(record, dict) else None
    if not isinstance(mesh, dict):
        return []
    unpainted = mesh_items_unpainted(record)
    if not unpainted:
        return []
    base_sha = _record_base_sha(character_name, record, bsig, base_sha)
    recorded = mesh.get("missing") if isinstance(mesh.get("missing"), dict) else {}
    from app.core import garment_store
    out: List[Tuple[str, str]] = []
    for item_id in unpainted:
        if base_sha and garment_store.accepted_fit(character_name, item_id, base_model_sha=base_sha) is not None:
            continue
        out.append((item_id, str(recorded.get(item_id) or "") or (NO_MESH_FIT if base_sha else BASE_MODEL_MISSING)))
    return out


def mesh_item_warnings(missing: Iterable[Tuple[str, str]]) -> List[str]:
    """``MESH_ITEM_NOT_READY`` per ``(item_id, reason)`` of ``mesh_items_missing``."""
    from app.models.inventory import get_item
    return [MESH_ITEM_NOT_READY.format(item=str((get_item(item_id) or {}).get("name") or item_id), reason=reason)
            for item_id, reason in missing]


def mesh_record(character_name: str, fig) -> Dict[str, Any]:
    """The ``mesh_items`` record of a delivered figure ``fig`` (block above),
    ``{}`` when no own-mesh piece is worn. A piece in the body shape until
    its mesh is ready gets a warning with why it has none: its chain's
    persisted failure (``garments.cached_failure``) or ``NO_MESH_FIT``."""
    from app.core import figure
    from app.models.inventory import get_item
    in_body = sorted(fig.in_body_own)
    intended = sorted({*fig.own, *fig.left_out})
    if not intended and not in_body:
        return {}
    warnings: List[str] = []
    profile = _profile_of(character_name, None)
    base_sha = base_model_sha256(character_name, fig.bsig)
    for item_id in in_body:
        if fig.interim.get(item_id) != figure.INTERIM_IN_BODY:
            continue  # its mesh is ready: grafted, the shape keeps it until the next Build
        name = str((get_item(item_id) or {}).get("name") or item_id)
        state = "open" if item_id in fig.open else "closed"
        reason = figure._not_fitted_reason(character_name, item_id, base_sha=base_sha, profile=profile, state=state)
        warnings.append(MESH_ITEM_IN_BODY.format(item=name, reason=reason))
    record = {"intended": intended, "effective": list(fig.own), "unpainted": sorted({*fig.own, *fig.left_out}),
              "missing": dict(fig.left_out), "warnings": warnings, "figure": fig.as_dict()}
    if in_body:
        record["in_body"] = in_body
    return record


def resolve_figure(character_name: str, pieces: Optional[Dict[str, str]], *, items: Optional[list] = None,
                   profile: Optional[Dict[str, Any]] = None):
    """The figure an outfit of ``pieces`` / ``items`` is built as NOW:
    ``(figure.delivered_figure, mesh_items record)``. No garment chain runs
    here (ruling A14): an own-mesh piece without its mesh is in the body
    shape meanwhile (ruling A11), so the dressed views never wait for a
    chain — the Build's ``pieces`` step runs them. Off the pipeline the
    figure is the plain body and the record ``{}``."""
    from app.core import figure
    profile = _profile_of(character_name, profile)
    fig = figure.delivered_figure(character_name, profile=profile, pieces=dict(pieces or {}),
                                  items=list(items or []))
    record = mesh_record(character_name, fig)
    if record:
        logger.info("Own-mesh pieces of %s: grafted %s, in the body %s (shape %s)", character_name,
                    list(fig.own), list(fig.in_body_own), fig.shape)
    return fig, record


def after_mesh_item_ready(character_name: str, item_id: str) -> bool:
    """A garment run accepted a fit of the own-mesh piece ``item_id``: when
    the character on the pipeline wears it, a "piece ready" request of its
    Build (``figure_build.request(name, "piece_ready")``, plan
    2026-11-12-unified-worn-pieces Task 8). The Build plans from the figure
    delivered now: a model whose shape and texture stay gets the piece
    assembled on (no dressed view, no hub job); a piece that was painted
    meanwhile (interim rule) changes the texture, so its views come first.
    With "Build automatically" off the piece only shows as a pending change.
    True when a Build was started or kept as the follow-up. Never raises."""
    try:
        from app.core import figure_build
        from app.core.model_refs import current_outfit_state
        profile = _profile_of(character_name, None)
        if not is_base_pipeline(character_name, profile=profile):
            return False
        pieces, _items, _signature = current_outfit_state(character_name)
        if item_id not in (pieces or {}).values():
            return False
        if figure_build.runs_chain(character_name, item_id):
            # Ruling A25: the Build ran this chain itself — its own fits and assembly follow, no follow-up.
            logger.info("Fit of %s/%s accepted inside its Build — no piece_ready follow-up", character_name, item_id)
            return False
        return figure_build.request(character_name, "piece_ready")
    except Exception:  # noqa: BLE001 — a trigger never breaks the garment run
        logger.exception("Build request after the fit of %s/%s failed", character_name, item_id)
        return False


def after_piece_detail_change(item_id: str) -> List[str]:
    """A piece's ``exposed_detail`` changed: every character on the pipeline
    wearing it (``figure_build.wearers``) gets a "detail change" request of
    its Build (``variant_current`` calls the stored outfit model stale now).
    2D renders stay. Returns the characters whose Build was started or kept."""
    from app.core import figure_build
    started = []
    for name in figure_build.wearers(item_id):
        if figure_build.request(name, "detail_change"):
            started.append(name)
    return started


def _draft_view(view: str) -> str:
    if view not in DRAFT_VIEWS:
        raise ValueError(f"no draft for the base-body view {view!r}")
    return view


def draft_prompt(character_name: str, view: str, *, profile: Optional[Dict[str, Any]] = None,
                 hair: Optional[str] = None) -> Tuple[str, str]:
    """``(prompt, negative)`` of the DRAFT of a two-step view (back, left,
    right): the view's ``DRAFT_PROMPTS`` sentence — the whole prompt of the
    edit, no style, no character block and never the clothing (Ruling A29:
    the dressed front, the reference, shows it); the same text for an
    outfit's dressed view and an own-mesh piece's worn back. Negative:
    ``DRAFT_NEGATIVE`` + the slots' ``base_body_negative`` texts. A haired
    base (``hair_text``) keeps the reference's hair where the sentence said
    "completely bald" (``_haired_head``), negative ``HAIRED_DRAFT_NEGATIVE``.
    ``hair``: the hair of the body shape the draft is for when it is not the
    plain body's (``dress_prompt``'s ``hair``: a text or
    ``garment_hair.BALD``), None = the plain body's."""
    from app.core.garment_hair import BALD
    profile = _profile_of(character_name, profile)
    prompt = DRAFT_PROMPTS[_draft_view(view)]
    hair = hair_text(character_name, profile=profile) if hair is None else ("" if hair == BALD else hair)
    if not hair:
        return prompt, base_negative(character_name, profile=profile, head=DRAFT_NEGATIVE)
    return (prompt.replace(_BALD_WORDS, _haired_head(character_name, hair, profile), 1),
            base_negative(character_name, profile=profile, head=HAIRED_DRAFT_NEGATIVE))


def cut_out(path: Path):
    """The RGBA cut-out of an image: as stored when it already carries a
    matte (some alpha below ``CUTOUT_ALPHA``), else the mesh-input matte
    (BiRefNet-DIS, ``character.MESH_INPUT_REMBG_MODEL``)."""
    import io
    from PIL import Image
    from app.models.character import MESH_INPUT_REMBG_MODEL, run_rembg
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    if image.getchannel("A").getextrema()[0] < CUTOUT_ALPHA:
        return image
    with Image.open(io.BytesIO(run_rembg(path.read_bytes(), MESH_INPUT_REMBG_MODEL))) as matted:
        return matted.convert("RGBA")


def draft_path(character_name: str, view: str, signature: str) -> Optional[Path]:
    """The stored draft of a two-step view of an outfit (``model_refs/drafts/
    tpose_<view>_<signature>.*``), or None."""
    from app.core.model_refs import _IMAGE_EXTS
    from app.models.character import get_character_dir
    if view not in DRAFT_VIEWS:
        return None
    directory = get_character_dir(character_name) / "model_refs" / DRAFT_DIR
    for ext in _IMAGE_EXTS:
        path = directory / f"{_kind(view)}_{signature}{ext}"
        if path.is_file():
            return path
    return None


def dressed_image(character_name: str, view: str, signature: str, bsig: str, *, fig=None) -> Optional[Path]:
    """The stored dressed image of one view of an outfit, or None — only one
    that belongs to the figure delivered NOW counts (``figure.
    delivered_figure`` of the view's pieces / items, or ``fig`` when the
    caller holds it): it was edited from the views of that figure's SHAPE
    (sidecar ``base_signature`` = the plain body ``bsig`` or the meshed shape
    ``ob…``, and ``base_image_sha256`` = that view's content — an edit of an
    older or re-rendered body does not line up with it) and it left out of
    its text exactly the own-mesh pieces that figure leaves unpainted
    (``mesh_items_unpainted`` == grafted + left out). A view made for another
    figure — a piece in the body shape that has its mesh now and was taken
    out, a mode changed, a shape built since — does not count. The texture KEY is not
    compared: it also names the base variant, which changes the body under
    the paint, never the view. Only ``dressed_views()`` are dressed; a side
    view is None while the side views are off."""
    from app.core import figure as figure_mod
    from app.core.model_refs import find_ref_image
    if view not in dressed_views():
        return None
    path = find_ref_image(character_name, _kind(view), signature)
    if path is None:
        return None
    meta = _ref_sidecar(path)
    if is_model_fit(meta):
        return None  # Ruling C2: a model fit of before Task 11g is stale, never served
    on = str(meta.get("base_signature") or "")
    if not on or (on != bsig and not is_outfit_body_signature(on)):
        return None
    if not meta.get("base_image_sha256") or meta.get("base_image_sha256") != file_sha256(
            find_ref_image(character_name, _kind(view), on)):
        return None
    if fig is None:
        from app.core.model3d import _ref_manifest
        manifest = _ref_manifest(path)
        fig = figure_mod.delivered_figure_cached(character_name, pieces=dict(manifest.get("pieces") or {}),
                                                 items=list(manifest.get("items") or []),
                                                 piece_state=dict(manifest.get("piece_state") or {}))
    if fig.bsig != bsig or fig.shape != on or mesh_items_unpainted(meta) != sorted({*fig.own, *fig.left_out}):
        return None  # made for another figure
    if is_outfit_body_signature(on) and (meta.get("dressed") is not False) != bool(getattr(fig, "texture", "")):
        # Ruling A50: on a meshed shape a figure paints something exactly when it has a texture — an edit made for a
        # painted figure is no view of one that paints nothing (a copy of the shape's view), nor the other way round.
        return None
    if getattr(fig, "texture", "") and composite_outdated(meta):
        return None  # Ruling A24: composited by older rules — re-composited from its stored draft
    if meta.get("dressed") is not False:
        # Ruling A74b: an edit made for another outfit reference picture (or for none, or without the one set now)
        # is no view of this outfit — a copy of the shape's view never uses a reference.
        from app.core import outfit_references
        if str(meta.get("outfit_reference_sha256") or "") != outfit_references.wanted_sha(
                character_name, getattr(fig, "pieces", None) or {}, getattr(fig, "open", ()) or ()):
            return None
    return path


def is_model_fit(record: Any) -> bool:
    """Whether a dressed back/side view's sidecar (``record``) is a MODEL fit
    of before Task 11g (Ruling C2, fix round 2): a ``fit_gate`` record
    without the composite's ``fit: "composite"``. Such a view is STALE — the
    old fits came back nude and were accepted (live test, 2026-11-13) — and never
    counts: ``dressed_image``, ``shape_view_shas`` and the texture store's
    ``_view_current`` refuse it; ``model_fit_remake`` re-makes it from its
    stored draft once at boot."""
    return isinstance(record, dict) and "fit_gate" in record and record.get("fit") != "composite"


def composite_outdated(record: Any) -> bool:
    """Ruling A24 (T15-F1): whether a dressed back/side view's sidecar (``record``) is a composite of an older
    ``view_composite.VERSION`` — its draft composited and checked by rules that changed since (A16's face check,
    A21's head) — or one recorded as passing whose numbers fail today's checks (``view_composite.check``). Such
    a view is re-composited from its stored draft at its next use (no hub job; without a stored
    draft following its front it is rendered again, counted in the estimate): a meshed shape's view before the
    shape is meshed (``shape_view`` — a shape already meshed from it keeps it, ``shape_view_shas``), a painted
    figure's view (``dressed_image`` / the texture store's ``_view_current``); a view copied from its shape (a
    figure with nothing painted) follows the shape's."""
    if not isinstance(record, dict) or record.get("fit") != "composite":
        return False
    composite = record.get("composite")
    if not isinstance(composite, dict):
        return False
    from app.core import view_composite
    try:
        if int(composite.get("version") or 0) < view_composite.VERSION:
            return True
    except (TypeError, ValueError):
        return True
    return bool(composite.get("ok")) and bool(view_composite.check(composite))


def stored_draft(character_name: str, view: str, signature: str, front: Optional[Path]) -> Optional[Path]:
    """The stored draft of a two-step view (``draft_path``) while it was made
    from ``front`` as it is now (its sidecar's ``front_sha256``) — the draft
    a view is composited from again without a new hub job (Ruling C2); None
    when there is none or it follows another front."""
    draft = draft_path(character_name, view, signature)
    if draft is None or front is None:
        return None
    sha = _ref_sidecar(draft).get("front_sha256")
    return draft if sha and sha == file_sha256(front) else None


# --- Refused views (Ruling FR-I3) ---------------------------------------------------------
#
# A dressed back/side view whose composite was refused (no draft's composite passed its checks,
# ``view_composite.refusal``) is a cached failure keyed by its inputs, like a refused fit (Ruling A23 b):
# the dressed front it follows, the base view it is composited onto and ``view_composite.VERSION``. While
# they are the same, an automatic Build does not plan the view again (``figure_build.plan`` lists its step
# as "failed — Retry"); a manual Build clears the record and retries the view once — counted as one draft
# (``shape_view_jobs`` / ``dressed_view_estimate``). The record lives beside the view's draft
# (``model_refs/drafts/refused/<kind>_<signature>.json``) and goes with its signature
# (``outfit_cache_gc._ref_files``); a published view drops it.

#: Subfolder of ``DRAFT_DIR`` that holds the refusal records of the dressed views.
VIEW_REFUSED_DIR = "refused"


def _view_refusal_path(character_name: str, view: str, signature: str) -> Path:
    from app.models.character import get_character_dir
    return get_character_dir(character_name) / "model_refs" / DRAFT_DIR / VIEW_REFUSED_DIR / \
        f"{_kind(view)}_{signature}.json"


def _view_inputs(front: Optional[Path], base_view: Optional[Path]) -> Dict[str, Any]:
    """What a view's composite depends on beyond its draft (Ruling FR-I3)."""
    from app.core import view_composite
    return {"front_sha256": file_sha256(front), "base_image_sha256": file_sha256(base_view),
            "composite_version": view_composite.VERSION}


def record_view_refusal(character_name: str, view: str, signature: str, *, front: Optional[Path],
                        base_view: Optional[Path], error: str) -> None:
    """Persist the refusal of the dressed ``view`` of ``signature`` (Ruling FR-I3). Never raises."""
    from app.core.timeutils import utc_now_iso
    path = _view_refusal_path(character_name, view, signature)
    if not path.parent.parent.parent.is_dir():
        return  # never mint the folders of a vanished character
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, json.dumps({"view": view, "signature": signature, "error": error,
                                        "inputs": _view_inputs(front, base_view), "refused_at": utc_now_iso()},
                                       ensure_ascii=False, indent=2).encode("utf-8"))
    except OSError:
        logger.warning("Refusal of the dressed %s %s (%s) not recorded", view, character_name, signature,
                       exc_info=True)


def clear_view_refusals(character_name: str, signature: str, views: Optional[Iterable[str]] = None) -> None:
    """Drop the refusal records of ``views`` (default: every draft view) of ``signature`` — a published view,
    or a manual Build that retries them (Ruling FR-I3)."""
    for view in views or DRAFT_VIEWS:
        try:
            _view_refusal_path(character_name, view, signature).unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


def refused_views(character_name: str, signature: str, on: str, *, current) -> Dict[str, str]:
    """``{view: reason}`` of the dressed draft views of ``signature`` that are not current (``current(view)``
    None) and whose recorded refusal still holds: the same dressed front (``tpose_<signature>``), the same view
    of the shape ``on`` it is composited onto and the same ``view_composite.VERSION`` (Ruling FR-I3).
    Read-only."""
    from app.core.model_refs import find_ref_image
    out: Dict[str, str] = {}
    front: Optional[Path] = None
    for view in (v for v in dressed_views() if v in DRAFT_VIEWS):
        path = _view_refusal_path(character_name, view, signature)
        if not path.is_file():
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict) or not record.get("error") or current(view) is not None:
            continue
        if front is None:
            front = find_ref_image(character_name, "tpose", signature)
        if record.get("inputs") == _view_inputs(front, find_ref_image(character_name, _kind(view), on)):
            out[view] = str(record["error"])
    return out


def shape_view_refusals(character_name: str, shape: str, bsig: str) -> Dict[str, str]:
    """``refused_views`` of the meshed shape ``shape`` on the plain body ``bsig`` (Ruling FR-I3)."""
    return refused_views(character_name, shape, bsig, current=lambda v: shape_view(character_name, v, shape, bsig))


def dressed_view_refusals(character_name: str, fig, signature: str) -> Dict[str, str]:
    """``refused_views`` of the outfit ``signature`` as the figure ``fig`` (its views are composited onto the
    views of ``fig.shape``; Ruling FR-I3)."""
    return refused_views(character_name, signature, fig.shape,
                         current=lambda v: dressed_image(character_name, v, signature, fig.bsig, fig=fig))


# --- Refusals of the outfit model's paint step (Ruling A61) -------------------------------------------------------
#
# The body retexture worker fits each registration view (the body's own view, ``tpose[_<view>]_<body>``) onto a
# render of the body's unrigged mesh BEFORE it looks at the dressed image (GLBBodyRetexture ``_prepare_view``:
# ``affine_registration(render mask, registration mask)``). When it refuses that fit ("<view> view: the image
# silhouette does not match the mesh render …" / "… dense registration failed …"), the MESH does not show what its
# own views show (Kira 2026-11-14: the base mesh had gone back to the 2026-11-12 mesh, Finding A38) — no dressed view
# can fix it, re-rendering the view cannot either; only a new mesh from the current views can. Such a refusal is
# recorded per body (``model_refs/drafts/refused/mesh/<body>.json``) with what it depends on: the body's unrigged
# source and that registration view. While both are the same, the body counts as due (the plain body:
# ``base_refresh_plan`` reason ``mesh_mismatch``; a meshed shape: ``figure_build`` plans its rebuild) — a manual Build
# makes the mesh again, an automatic one never spends on it.
#
# Every other refusal of the paint step (any ``build_outfit_model`` error that is not load, a missing worker or a
# timeout) is recorded for its figure with the fingerprint of its inputs (``assemble_inputs``,
# ``model_refs/drafts/refused/assemble/<signature>.json``): an automatic Build does not run the assembly again while
# the inputs are the same (``figure_build.plan`` lists it "failed — Retry"); a manual Build retries it once.

#: Subfolders of ``VIEW_REFUSED_DIR`` (subfolders: the outfit cache GC lists only the folder's own files).
MESH_REFUSED_DIR = "mesh"
ASSEMBLE_REFUSED_DIR = "assemble"
#: The worker's refusals of a registration fit (GLBBodyRetexture ``_prepare_view``): the view, then the cause.
_REGISTRATION_REFUSAL = re.compile(
    r"\b(front|back|left|right) view: (?:the image silhouette does not match the mesh render"
    r"|dense registration failed)")


def registration_refusal_view(error: str) -> str:
    """The view whose registration fit the body retexture worker refused in ``error`` ("" for any other error)."""
    match = _REGISTRATION_REFUSAL.search(error or "")
    return match.group(1) if match else ""


def _refusal_dir(character_name: str, kind: str) -> Path:
    from app.models.character import get_character_dir
    return get_character_dir(character_name) / "model_refs" / DRAFT_DIR / VIEW_REFUSED_DIR / kind


def _body_source(character_name: str, body: str) -> Path:
    """The unrigged source of the body ``body`` (the plain body's signature or a shape id) in the REAL model
    directory — what the worker renders."""
    from app.models.character import get_character_dir
    return get_character_dir(character_name) / "model3d" / "unrigged" / f"{body}.glb"


def _mesh_inputs(character_name: str, body: str, view: str) -> Dict[str, str]:
    from app.core.model_refs import find_ref_image
    return {"body_source_sha256": file_sha256(_body_source(character_name, body)),
            "registration_sha256": file_sha256(find_ref_image(character_name, _kind(view), body))}


def _write_record(path: Path, record: Dict[str, Any]) -> bool:
    if not path.parents[3].is_dir():   # characters/<name>: never mint the folders of a vanished character
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8"))
        return True
    except OSError:
        logger.warning("Refusal record %s not written", path, exc_info=True)
        return False


def _read_record(path: Path) -> Optional[Dict[str, Any]]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def record_mesh_mismatch(character_name: str, body: str, view: str, error: str) -> None:
    """Record that the worker refused the registration fit of ``view`` on the body ``body`` (block above). Never
    raises."""
    from app.core.timeutils import utc_now_iso
    if not body or view not in BASE_VIEWS:
        return
    path = _refusal_dir(character_name, MESH_REFUSED_DIR) / f"{body}.json"
    if _write_record(path, {"body": body, "view": view, "error": error, "inputs": _mesh_inputs(character_name, body, view),
                            "refused_at": utc_now_iso()}):
        logger.warning("Outfit model %s: the mesh of %s does not match its %s view — the body is due for a new mesh",
                       character_name, body, view)
        _invalidate_figure()


def mesh_view_mismatch(character_name: str, body: str) -> Optional[Dict[str, str]]:
    """``{body, view, error, refused_at}`` while a recorded registration refusal of the body ``body`` still holds:
    the same unrigged source and the same registration view (block above); None otherwise. Read-only."""
    if not body:
        return None
    record = _read_record(_refusal_dir(character_name, MESH_REFUSED_DIR) / f"{body}.json")
    view = str((record or {}).get("view") or "")
    if not record or view not in BASE_VIEWS or not record.get("error"):
        return None
    inputs = _mesh_inputs(character_name, body, view)
    if not inputs["body_source_sha256"] or record.get("inputs") != inputs:
        return None
    return {"body": body, "view": view, "error": str(record["error"]), "refused_at": str(record.get("refused_at") or "")}


def assemble_inputs(character_name: str, signature: str, fig) -> Dict[str, Any]:
    """What the outfit model of ``signature`` as the figure ``fig`` is painted from (Ruling A61): the figure, the
    plain body's model, the body's model and unrigged source, the body's registration views, the dressed views
    (when something is painted) and the worker. Read-only (content hashes, memoised by ``file_sha256``)."""
    from app.core import config
    from app.core.model_refs import find_ref_image
    from app.models.character import get_character_dir
    root = get_character_dir(character_name) / "model3d"
    body = fig.shape
    return {"figure": fig.as_dict(), "base_model_sha256": base_model_sha256(character_name, fig.bsig),
            "body_sha256": file_sha256(root / f"{body}.glb"),
            "body_source_sha256": file_sha256(_body_source(character_name, body)),
            "registrations": {v: file_sha256(find_ref_image(character_name, _kind(v), body)) for v in dressed_views()},
            "views": texture_view_shas(character_name, signature, fig.bsig, fig=fig) if fig.texture else {},
            "worker": str(config.get("body_retexture.worker_dir", "") or "")}


def record_assemble_refusal(character_name: str, signature: str, fig, error: str) -> None:
    """Record that the outfit model of ``signature`` as ``fig`` was refused with ``error`` (block above). Never
    raises."""
    from app.core.timeutils import utc_now_iso
    try:
        inputs = assemble_inputs(character_name, signature, fig)
    except Exception:  # noqa: BLE001 — without its inputs there is no record (the next Build tries again)
        logger.warning("Assembly refusal of %s (%s) not recorded", character_name, signature, exc_info=True)
        return
    path = _refusal_dir(character_name, ASSEMBLE_REFUSED_DIR) / f"{signature}.json"
    if _write_record(path, {"signature": signature, "error": error, "inputs": inputs, "refused_at": utc_now_iso()}):
        _invalidate_figure()


def clear_assemble_refusal(character_name: str, signature: str) -> None:
    try:
        (_refusal_dir(character_name, ASSEMBLE_REFUSED_DIR) / f"{signature}.json").unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def assemble_refusal(character_name: str, signature: str, fig) -> Optional[Dict[str, str]]:
    """``{error, refused_at}`` while the recorded refusal of the outfit model of ``signature`` holds for ``fig``:
    every input of ``assemble_inputs`` is the same; None otherwise. Read-only."""
    record = _read_record(_refusal_dir(character_name, ASSEMBLE_REFUSED_DIR) / f"{signature}.json")
    if not record or not record.get("error"):
        return None
    try:
        if record.get("inputs") != assemble_inputs(character_name, signature, fig):
            return None
    except Exception:  # noqa: BLE001 — inputs unreadable: no verdict, the Build may try
        return None
    return {"error": str(record["error"]), "refused_at": str(record.get("refused_at") or "")}


def _invalidate_figure() -> None:
    try:
        from app.core import figure
        figure.invalidate()
    except Exception:  # noqa: BLE001 — a memo, never a failure
        logger.debug("Figure memo not invalidated", exc_info=True)


def fit_gate_warning(attempts: int, record: Dict[str, Any], view: str = "back") -> str:
    """The status warning of a dressed two-step view kept although no
    attempt passed its gates; ``record`` is the kept attempt's ``{"guard",
    "noise", "framing"}`` (the sidecar key ``fit_gate`` keeps its name: the
    views made by the model fit before Task 11g carry it too)."""
    reasons = []
    if not (record.get("guard") or {}).get("ok", True):
        reasons.append("turned toward the camera")
    if not (record.get("noise") or {}).get("ok", True):
        reasons.append("grainy")
    if not (record.get("framing") or {}).get("ok", True):
        reasons.append("re-framed")
    what = " and ".join(reasons) or "off"
    return (f"Dressed {view} may be {what} ({view} check failed after {attempts} "
            f"attempt{'' if attempts == 1 else 's'})")


def best_fit_attempt(results: List[Dict[str, Any]]) -> Tuple[int, bool]:
    """``(index, passed)``: the first attempt passing every check, else the
    one that keeps its view (guard), then its frame (``framing``), with the
    lowest noise score."""
    for i, result in enumerate(results):
        if result["ok"]:
            return i, True

    def rank(i: int):
        result = results[i]
        noise = (result.get("noise") or {}).get("score")
        return (not (result.get("guard") or {}).get("ok", True),
                not (result.get("framing") or {}).get("ok", True),
                noise if noise is not None else float("inf"), i)
    return min(range(len(results)), key=rank), False


def _dress_common(view: str, *, pieces: Optional[Dict[str, str]], items: Optional[list],
                  profile: Dict[str, Any], size: Tuple[int, int]) -> Dict[str, Any]:
    """The render arguments of a two-step view's draft."""
    return dict(equipped_pieces=dict(pieces or {}), equipped_items=list(items or []),
                pose_prompt="", expression_prompt="", image_use_case=DRAFT_USE_CASES[view],
                override_width=size[0], override_height=size[1], apply_state_modifiers=False,
                mesh_input_profile=profile, back_view=view == "back", character_loras=True)


def render_draft(character_name: str, view: str, *, stem: Path, front: Path, refs_dir: Path,
                 prompt: Tuple[str, str], profile: Dict[str, Any], common: Dict[str, Any],
                 sidecar_extra: Dict[str, Any]) -> Optional[Path]:
    """The DRAFT render of a two-step view into ``stem``: an edit of the
    dressed ``front`` (on neutral grey, the only reference) with ``prompt`` =
    ``(text, negative)`` (``draft_prompt`` — the whole prompt, no style and
    no character block), occasion ``DRAFT_OCCASIONS[view]``, the render
    arguments ``common`` (``_dress_common``). None when the render returned
    nothing; render errors propagate. Shared by the outfit's dressed views
    (``_dress_view``) and an own-mesh piece's worn back
    (``garment_images``). The front goes out centred on a square canvas and
    the render is cut back to the front's frame
    (``garment_images.square_reference`` / ``crop_back``, ruling F14 g) —
    the canvas size replaces ``common``'s."""
    from app.core import expression_regen
    from app.core.garment_images import square_reference
    text, negative = prompt
    with square_reference(front, refs_dir) as (reference, side, offset, source_size):
        return expression_regen.render_character_image(
            character_name, output_stem=stem, bare_prompt=text, extra_negative=negative,
            occasion=DRAFT_OCCASIONS[view], reference_image=reference,
            sidecar_extra=sidecar_extra,
            **{**common, "override_width": side, "override_height": side,
               "crop_back_to": (side, offset, source_size)})


#: Sidecar keys of a draft that describe ITS render, not the composite made
#: from it (``composite_sidecar``): the composite is no render.
_DRAFT_RENDER_KEYS = ("prompt", "final_prompt", "negative_prompt", "reference_images", "seed", "duration_s",
                      "provider", "service", "model", "loras", "routing", "fallback_from", "overflow_from",
                      "front_sha256", "hub_job", "job_id")


def composite_sidecar(draft: Path, view: str, extra: Dict[str, Any], record: Dict[str, Any]) -> Dict[str, Any]:
    """The sidecar of a composite made from ``draft``: the draft's own
    sidecar (its manifest — pieces, items, mesh variant / token, piece
    state, character) without the keys of its render (``_DRAFT_RENDER_KEYS``)
    and its ``<view>_draft`` flag, plus ``extra`` (``_composite_extra``),
    ``created_at``, ``fit: "composite"`` and the composite's ``record``
    (``view_composite.composite_arrays``) under ``composite`` — an EMPTY
    composite (the base view unchanged) as ``composite: "empty"`` with the
    record under ``composite_record`` (``view_composite.sidecar_fields``)."""
    from app.core import view_composite
    from app.core.timeutils import utc_now_iso
    meta = {k: v for k, v in _ref_sidecar(draft).items() if k not in _DRAFT_RENDER_KEYS and k != f"{view}_draft"}
    meta.update(extra)
    meta.update({"created_at": utc_now_iso(), **view_composite.sidecar_fields(record)})
    return meta


def _composite_extra(view: str, bsig: str, base_view: Path, draft: Path,
                     mesh_items: Optional[Dict[str, Any]] = None,
                     texture: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The sidecar fields of a dressed view's composite: the base it was
    composited onto, its draft — the own-mesh record of its outfit
    (``mesh_items``, the front's) and its texture (``texture_signature``,
    ``dress_text``)."""
    extra = {"base_signature": bsig, "dressed": True, "base_image_sha256": file_sha256(base_view),
             f"{view}_draft": draft.name, f"{view}_draft_sha256": file_sha256(draft)}
    if mesh_items:
        extra["mesh_items"] = mesh_items
    extra.update(texture or {})
    return extra


def _composite_attempt(character_name: str, view: str, *, stem: Path, draft: Path,
                       base_views: Dict[str, Optional[Path]], extra: Dict[str, Any],
                       front: Optional[Path] = None) -> Tuple[Path, Dict[str, Any]]:
    """The composite of ``draft`` onto the base view into ``stem.png``
    (``view_composite.compose``, rule "outfit", RGBA in the base view's
    frame) with its sidecar (``composite_sidecar``) and its result
    ``{"ok", "composite", "guard", "noise", "framing"}``: ``ok`` = the
    composite's checks (alignment IoU, coverage) and the view's gates — the
    head ``view_guard`` against the base views (``front``: the dressed
    front the draft was made from — a head that differs from the base
    front's is judged by the face cue, Ruling A16), ``base_body_gates.
    noise_gate`` and ``framing_gate`` against the base view. A composite
    that failed its checks is not gated (``guard`` etc. are ``{}``).
    A head that differs (``head_match`` of ``front`` below
    ``HEAD_MATCH_MIN``) is taken from the draft as well
    (``view_composite.compose(head=True)``, Ruling A21) — never a bald head
    on the haired plain back."""
    from app.core import base_body_gates, view_composite
    base_view = base_views[view]
    path = stem.with_suffix(".png")
    match = head_match(front, base_views.get("front")) if front is not None else None
    other_head = {"head": True} if match is not None and match < HEAD_MATCH_MIN else {}
    record = view_composite.compose(base_view, draft, path, rule="outfit", **other_head)
    path.with_suffix(".json").write_text(json.dumps(composite_sidecar(draft, view, extra, record),
                                                    ensure_ascii=False, indent=2), encoding="utf-8")
    if not record["ok"]:
        return path, {"ok": False, "composite": record, "guard": {}, "noise": {}, "framing": {}}
    guard = view_guard(view, path, base_views, front=front)
    noise = base_body_gates.noise_gate(path, base_view)
    framing = base_body_gates.framing_gate(path, base_view)
    return path, {"ok": bool(guard["ok"] and noise["ok"] and framing["ok"]), "composite": record,
                  "guard": guard, "noise": noise, "framing": framing}


def _dress_view(character_name: str, view: str, *, signature: str, bsig: str,
                pieces: Optional[Dict[str, str]], items: Optional[list], profile: Dict[str, Any],
                front: Path, base_views: Dict[str, Optional[Path]], refs_dir: Path,
                size: Tuple[int, int], mesh_items: Optional[Dict[str, Any]] = None,
                texture: Optional[Dict[str, Any]] = None,
                raise_load: bool = False, reuse_draft: bool = True,
                hair: Optional[str] = None) -> Tuple[Optional[Path], Optional[str]]:
    """A dressed back or side view in two steps (Task 11g, Ruling C1).
    ``(stored path, warning)``; raises ``OutfitError`` with the step that
    failed. ``raise_load``: the draft render raises ``BackendBusyError`` /
    ``MediaGenerationDisabled`` instead of ending in None
    (``generate_dressed_images``). The view follows the dressed front,
    own-mesh pieces included: what the front left out (its ``mesh_items``)
    is not in the draft's reference either — no outfit text is sent — and
    the record goes into the draft's and the view's sidecar.

    1. DRAFT (occasion ``DRAFT_OCCASIONS[view]``: ``outfit_back_draft`` /
       ``outfit_side_draft`` — the view's only hub job): an edit of the
       dressed ``front`` (on grey, the only reference) with ``draft_prompt``
       (the view's ``DRAFT_PROMPTS`` sentence, empty style
       ``DRAFT_USE_CASES``, no character block), rendered on the front's
       square canvas and cut back to its frame; stored as
       ``model_refs/drafts/tpose_<view>_<sig>``.
    2. COMPOSITE (``view_composite``, CPU, no hub job, no model fallback):
       the draft's clothing put onto the shape's base view, staged in a
       private ``.composite_*`` dir inside ``model_refs``
       (``_composite_attempt``), then the view's gates: the head
       ``view_guard``, ``base_body_gates.noise_gate`` and ``framing_gate``
       against the base view.

    The STORED draft of the view comes first (Ruling C2, fix round 2): while
    it was made from this ``front`` (``stored_draft``) it is composited again
    — no hub job — and only a composite of it that fails its checks or a
    gate makes ONE new draft; ``reuse_draft`` False (a forced re-render, the
    Regenerate button) always drafts anew. Each new draft renders into the staging dir; only the chosen one is moved
    onto ``drafts/tpose_<view>_<sig>`` (the view records its content,
    ``follows_front``). Up to ``DRAFT_ATTEMPTS`` drafts: a composite that fails its checks
    (alignment IoU below ``view_composite.IOU_MIN``, coverage below
    ``COVERAGE_MIN``) or a gate makes a new draft. A draft that lines up but
    wears nothing that shows in this view is no failure: the composite is
    EMPTY — the base view unchanged, sidecar ``composite: "empty"`` (fix
    round 1). When no draft's composite passed its checks, nothing is published
    — the stored view (if any) stays, the texture never takes it — and
    ``OutfitError`` carries the numbers (``view_composite.refusal``). Among
    composites that passed their checks the first passing every gate is
    published onto ``tpose_<view>_<sig>`` — else ``best_fit_attempt`` of
    them, with the warning (``fit_gate_warning``) — sidecar ``fit:
    "composite"``, ``composite`` = its record and ``fit_gate`` = every
    attempt's numbers."""
    import tempfile
    from app.core import base_body_gates, view_composite
    kind = _kind(view)
    drafts = refs_dir / DRAFT_DIR
    drafts.mkdir(exist_ok=True)
    common = _dress_common(view, pieces=pieces, items=items, profile=profile, size=size)
    if raise_load:
        common["raise_load"] = True
    base_view = base_views[view]
    final = refs_dir / f"{kind}_{signature}"
    attempts: List[Tuple[Path, Dict[str, Any]]] = []
    # Ruling A24: a view composited by older rules is re-composited from its stored draft — no hub job: a
    # composite that passes its checks is published (the gates' warning kept) without a new draft.
    remake = composite_outdated(_ref_sidecar(final))
    with tempfile.TemporaryDirectory(prefix=".composite_", dir=refs_dir, ignore_cleanup_errors=True) as staging:
        first = 1
        render_failed = False   # a draft that did not render: no refusal is recorded for it (Ruling FR-I3)
        kept = stored_draft(character_name, view, signature, front) if reuse_draft else None
        if kept is not None and view in view_facing.SIDE_VIEWS:
            # Ruling A91: the draft is composited onto the base view — it faces the way that view faces.
            view_facing.match_facing(view, kept, base_view)
        if kept is not None:
            # Ruling C2: the stored draft made from this front is composited again first — no hub job; a
            # composite that fails its checks or a gate makes ONE new draft (attempt 2).
            stem = Path(staging) / "attempt1" / final.name
            stem.parent.mkdir()
            attempt = _composite_attempt(character_name, view, stem=stem, draft=kept, base_views=base_views,
                                         extra=_composite_extra(view, bsig, base_view, kept, mesh_items, texture),
                                         front=front)
            attempts.append(attempt)
            first = 2
            logger.info("Dressed %s %s (%s): stored draft composite %s (%s; guard %s, noise %s)", view,
                        character_name, signature, "passed" if attempt[1]["ok"] else "failed",
                        view_composite.summary(attempt[1]["composite"]), attempt[1]["guard"].get("best"),
                        attempt[1]["noise"].get("score"))
        for n in range(first, DRAFT_ATTEMPTS + 1):
            if attempts and attempts[-1][1]["ok"]:
                break
            if remake and kept is not None and attempts and (attempts[0][1]["composite"] or {}).get("ok"):
                logger.info("Dressed %s %s (%s): re-composited from its stored draft (Ruling A24) — no new draft",
                            view, character_name, signature)
                break
            draft_stem = Path(staging) / f"draft{n}" / f"{kind}_{signature}"
            draft_stem.parent.mkdir()
            try:
                draft = render_draft(
                    character_name, view, stem=draft_stem, front=front, refs_dir=refs_dir,
                    prompt=draft_prompt(character_name, view, profile=profile, hair=hair), profile=profile,
                    common=common,
                    sidecar_extra={"base_signature": bsig, "dressed": True, f"{view}_draft": True,
                                   "front_sha256": file_sha256(front),
                                   **({"mesh_items": mesh_items} if mesh_items else {}), **(texture or {})})
            except Exception as e:  # noqa: BLE001 — a later draft never loses an earlier composite
                if not attempts or (raise_load and _is_load(e)):
                    raise
                logger.warning("Dressed %s %s (%s): draft %d failed: %s", view, character_name, signature, n, e)
                render_failed = True
                break
            if draft is None:
                if not attempts:
                    raise OutfitError(f"Dressed {view} draft failed")
                render_failed = True
                break
            if view in view_facing.SIDE_VIEWS:
                view_facing.match_facing(view, Path(draft), base_view)   # Ruling A91
            stem = Path(staging) / f"attempt{n}" / final.name
            stem.parent.mkdir()
            attempt = _composite_attempt(character_name, view, stem=stem, draft=Path(draft), base_views=base_views,
                                         extra=_composite_extra(view, bsig, base_view, Path(draft), mesh_items,
                                                                texture), front=front)
            attempts.append(attempt)
            result = attempt[1]
            logger.info("Dressed %s %s (%s): draft %d composite %s (%s; guard %s, noise %s)", view, character_name,
                        signature, n, "passed" if result["ok"] else "failed",
                        view_composite.summary(result["composite"]), result["guard"].get("best"),
                        result["noise"].get("score"))
            if result["ok"]:
                break
        usable = [i for i, (_p, r) in enumerate(attempts) if r["composite"].get("ok")]
        if not usable:
            error = view_composite.refusal(f"Dressed {view}", [r["composite"] for _p, r in attempts])
            if not render_failed:
                # Ruling FR-I3: every draft was composited and refused — a cached failure of these inputs.
                record_view_refusal(character_name, view, signature, front=front, base_view=base_view, error=error)
            raise OutfitError(error)
        pick, passed = best_fit_attempt([attempts[i][1] for i in usable])
        chosen = usable[pick]
        warning = None if passed else fit_gate_warning(len(attempts), attempts[chosen][1], view)
        record = {"ok": passed, "chosen": chosen + 1, "noise_limit": base_body_gates.NOISE_LIMIT,
                  "attempts": [r for _p, r in attempts], "warning": warning}
        chosen_draft = Path(staging) / f"draft{chosen + 1}"
        for staged in sorted(chosen_draft.glob(f"{kind}_{signature}.*")):
            if staged.suffix.lower() != ".json":
                _publish_staged(staged, drafts / f"{kind}_{signature}", {"chosen": chosen + 1}, key="composite_draft")
        stored = _publish_staged(attempts[chosen][0], final, record, key="fit_gate")
    if stored is not None:
        clear_view_refusals(character_name, signature, (view,))
    return stored, warning


# --- Texture bodies (plan 2026-11-10-texture-body-reuse-and-layering, Task 1) ---
#
# An outfit model on the pipeline = a PAINTED BODY + the outfit's garment
# assembly. The painted body depends only on what is painted: the texture
# signature ``tsig`` (``texture_signature``) keys it, never the outfit
# signature (which carries the own-mesh token). Outfits that differ only in
# a worn own-mesh piece share one painted body — no image job, no worker run.
#
# Store (real directories, never a staged one):
#   model_refs/texture/tpose[_<view>]_<tsig>.*   the dressed views (+ sidecar)
#   model_refs/texture/drafts/tpose_<view>_<tsig>.*   their drafts
#   model3d/texture/<tsig>.glb (+ .json)          the painted body
# An outfit keeps its own copies ``tpose[_<view>]_<sig>`` (every reader of the
# outfit's mesh inputs stays as it is); their sidecars name the
# ``texture_signature`` and carry the outfit's own manifest.

TEXTURE_DIR = "texture"
#: Bumped when the dressed pipeline paints differently for the same inputs.
TEXTURE_BODY_VERSION = 1
TEXTURE_SIG_RE = re.compile(r"tex[0-9a-f]{12}")
#: Sidecar keys of a dressed view that describe its OUTFIT, not its texture:
#: left out of the store's copy, written per outfit.
_OUTFIT_VIEW_KEYS = ("equipped_pieces", "equipped_items", "mesh_variant", "mesh_token", "mesh_items",
                     "texture_signature", "created_at", "piece_state")


def is_texture_signature(value: Optional[str]) -> bool:
    return bool(value) and bool(TEXTURE_SIG_RE.fullmatch(str(value)))


def texture_variant(character_name: str, pieces: Optional[Dict[str, str]], *, dressed: bool,
                    mesh: Optional[Dict[str, Any]], profile: Optional[Dict[str, Any]] = None) -> str:
    """The base variant a painted body of ``pieces`` is built from — the
    build's rule: ``outfit_variant`` for a dressed combination or one with
    own-mesh pieces (their meshes cover the body like painted pieces
    would), else ``"rigged"``."""
    if dressed or mesh_items_intended({"mesh_items": mesh or {}}):
        return outfit_variant(character_name, pieces, profile=profile)
    return "rigged"


def texture_inputs(character_name: str, *, pieces: Optional[Dict[str, str]], items: Optional[list],
                   variant: str, mesh_effective: Iterable[str] = (), bsig: Optional[str] = None,
                   profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What a painted body is made of (the ``tsig`` inputs): the base
    signature, the base variant, the effective dress text of every dressed
    view (``dress_text(mesh_items=<unpainted>)``, ``mesh_items_unpainted``;
    ``dressed_views()``), the
    side-view switch and ``TEXTURE_BODY_VERSION``. NOT the outfit
    signature, NOT the own-mesh token: a piece that is its own garment mesh
    is not painted, so it changes nothing here."""
    profile = _profile_of(character_name, profile)
    meshed = sorted({str(i) for i in mesh_effective or ()})
    return {"version": TEXTURE_BODY_VERSION,
            "base_signature": bsig or base_signature(character_name, profile=profile),
            "base_variant": variant,
            "side_views": side_views_dressed(),
            "dress_text": {v: dress_text(character_name, v, pieces=pieces, items=items, profile=profile,
                                         mesh_items=meshed) for v in dressed_views()}}


def texture_signature(inputs: Dict[str, Any]) -> str:
    """``"tex"`` + the first 12 hex of sha256 over the canonical JSON of
    ``texture_inputs`` (keys sorted, separators ``,`` ``:``, UTF-8)."""
    raw = json.dumps(inputs, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "tex" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def texture_refs_dir(character_name: str) -> Path:
    from app.models.character import get_character_dir
    return get_character_dir(character_name) / "model_refs" / TEXTURE_DIR


def texture_body_path(character_name: str, tsig: str) -> Path:
    """``model3d/texture/<tsig>.glb`` of the REAL model directory (also
    from inside a staged outfit run: the body is shared, never staged)."""
    from app.models.character import get_character_dir
    if not is_texture_signature(tsig):
        raise ValueError(f"not a texture signature: {tsig!r}")
    return get_character_dir(character_name) / "model3d" / TEXTURE_DIR / f"{tsig}.glb"


def _image_at(stem: Path) -> Optional[Path]:
    from app.core.model_refs import _IMAGE_EXTS
    for ext in _IMAGE_EXTS:
        path = Path(f"{stem}{ext}")
        if path.is_file():
            return path
    return None


def _texture_view(character_name: str, view: str, tsig: str) -> Optional[Path]:
    return _image_at(texture_refs_dir(character_name) / f"{_kind(view)}_{tsig}")


def _texture_draft(character_name: str, view: str, tsig: str) -> Optional[Path]:
    return _image_at(texture_refs_dir(character_name) / DRAFT_DIR / f"{_kind(view)}_{tsig}")


def _atomic_write(target: Path, data: bytes) -> None:
    import os
    import tempfile
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, staged = tempfile.mkstemp(dir=target.parent, prefix=".tex-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(staged, target)
    except BaseException:
        Path(staged).unlink(missing_ok=True)
        raise
    finally:
        from app.core import figure
        figure.invalidate()   # a ref or a stored body: delivered figures may change


def _copy_ref(source: Path, stem: Path, meta: Dict[str, Any]) -> Path:
    """Copy an image to ``stem`` + its suffix (another stored extension of
    the same stem goes) and write ``meta`` as its sidecar; atomic each."""
    from app.core.model_refs import _IMAGE_EXTS
    target = Path(f"{stem}{source.suffix}")
    data = source.read_bytes()
    for ext in _IMAGE_EXTS:
        other = Path(f"{stem}{ext}")
        if other != target and other.is_file():
            other.unlink()
    _atomic_write(target, data)
    _atomic_write(target.with_suffix(".json"), json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
    return target


def follows_front(view: str, record: Dict[str, Any], draft: Optional[Path], front_sha: str) -> bool:
    """Whether a dressed back/side view (sidecar ``record``) was fitted from
    a draft made from the front of content ``front_sha``: its
    ``<view>_draft_sha256`` is the draft's content and the draft's sidecar
    names ``front_sha256`` = ``front_sha``."""
    if not front_sha or draft is None:
        return False
    return (bool(record.get(f"{view}_draft_sha256")) and record[f"{view}_draft_sha256"] == file_sha256(draft)
            and _ref_sidecar(draft).get("front_sha256") == front_sha)


def _view_current(record: Dict[str, Any], bsig: str, base_view: Optional[Path]) -> bool:
    return (record.get("base_signature") == bsig and bool(record.get("base_image_sha256")) and not is_model_fit(record)
            and not composite_outdated(record) and record.get("base_image_sha256") == file_sha256(base_view))


def _store_texture_views(character_name: str, signature: str, tsig: str, views: Iterable[str],
                         texts: Optional[Dict[str, str]] = None) -> List[str]:
    """Publish the outfit's dressed views ``views`` (and their drafts) into
    the texture store under ``tsig`` — the store copy drops the outfit's
    own keys (``_OUTFIT_VIEW_KEYS``) and names the ``texture_signature`` and,
    when given, the view's ``dress_text``. Returns the views stored
    (nothing for ``""``: a meshed shape with nothing painted has no store)."""
    from app.core.model_refs import find_ref_image
    if not is_texture_signature(tsig):
        return []
    store = texture_refs_dir(character_name)
    stored = []
    for v in views:
        source = find_ref_image(character_name, _kind(v), signature)
        if source is None:
            continue
        meta = {k: val for k, val in _ref_sidecar(source).items() if k not in _OUTFIT_VIEW_KEYS}
        meta["texture_signature"] = tsig
        if texts and v in texts:
            meta["dress_text"] = texts[v]
        if v in DRAFT_VIEWS:
            draft = draft_path(character_name, v, signature)
            if draft is not None:
                draft_meta = {k: val for k, val in _ref_sidecar(draft).items() if k not in _OUTFIT_VIEW_KEYS}
                copied = _copy_ref(draft, store / DRAFT_DIR / f"{_kind(v)}_{tsig}",
                                   {**draft_meta, "texture_signature": tsig})
                meta[f"{v}_draft"] = copied.name
        _copy_ref(source, store / f"{_kind(v)}_{tsig}", meta)
        stored.append(v)
    return stored


def _outfit_view_meta(character_name: str, record: Dict[str, Any], *, pieces: Optional[Dict[str, str]],
                      items: Optional[list], profile: Dict[str, Any], mesh: Dict[str, Any],
                      tsig: str) -> Dict[str, Any]:
    """The sidecar of a dressed view copied from the store into an outfit:
    the store's record + the outfit's own manifest (what the render would
    have written: pieces, items, ``mesh_variant``, ``mesh_token``,
    ``mesh_items``) + ``texture_signature``."""
    from app.core.model_refs import mesh_items_token, mesh_variant
    from app.core.timeutils import utc_now_iso
    meta = {k: v for k, v in record.items() if k not in _OUTFIT_VIEW_KEYS}
    meta.update({"created_at": utc_now_iso(), "equipped_pieces": dict(pieces or {}),
                 "equipped_items": list(items or []),
                 "mesh_variant": mesh_variant(character_name, dict(pieces or {}), profile),
                 "texture_signature": tsig})
    token = mesh_items_token(character_name, dict(pieces or {}), profile)
    if token:
        meta["mesh_token"] = token
    # The outfit's open pieces (plan 2026-11-12-unified-worn-pieces D-A1) — only when one is open.
    from app.core.model_refs import live_piece_state
    open_state = live_piece_state(character_name, dict(pieces or {}), profile)
    if open_state:
        meta["piece_state"] = open_state
    if mesh:
        meta["mesh_items"] = mesh
    return meta


def _store_front(character_name: str, tsig: str, bsig: str, base_front: Optional[Path]) -> Optional[Path]:
    """The store's dressed front of ``tsig`` when it was made from the
    current base front, else None."""
    path = _texture_view(character_name, "front", tsig)
    if path is None:
        return None
    meta = _ref_sidecar(path)
    if meta.get("dressed") is False or not _view_current(meta, bsig, base_front):
        return None
    return path


def _adopt_texture_views(character_name: str, *, tsig: str, bsig: str, texts: Dict[str, str],
                         base_views: Dict[str, Optional[Path]], reference_sha: str = "") -> Optional[Path]:
    """Fill the store of ``tsig`` from dressed views of OTHER outfits that
    prove the same texture: a front made from the current base front whose
    sidecar names the same ``dress_text`` — or, recorded before the store
    existed, whose ``prompt`` is exactly the front edit of that text
    (``_edit_prompt``; the front sidecar has always recorded the prompt it
    was sent) — plus each back/side of that outfit made from the current
    base view and fitted from a draft of THAT front (``follows_front``). The
    back is never sent an outfit text (its draft follows the front), so the
    front's text decides. The newest matching front wins. Returns the
    store's front, or None when nothing matches."""
    found = _adoptable_texture_views(character_name, bsig=bsig, texts=texts, base_views=base_views,
                                     reference_sha=reference_sha)
    if found is None:
        return None
    key, views = found
    logger.info("Texture %s of %s: adopting the dressed views %s of outfit %s", tsig, character_name, views, key)
    _store_texture_views(character_name, key, tsig, views, texts)
    return _store_front(character_name, tsig, bsig, base_views.get("front"))


def _adoptable_texture_views(character_name: str, *, bsig: str, texts: Dict[str, str],
                             base_views: Dict[str, Optional[Path]],
                             reference_sha: str = "") -> Optional[Tuple[str, List[str]]]:
    """``(outfit signature, views)`` ``_adopt_texture_views`` would adopt
    (its docstring), or None — read-only (the Build's estimate counts those
    views as copies, ``dressed_view_estimate``). Only a front made from the
    same outfit reference picture (``outfit_reference_sha256``, "" = none;
    Ruling A74b) proves the same texture."""
    from app.core.model_refs import get_model_refs_dir
    front_text = texts.get("front") or ""
    if not front_text:
        return None
    prompt = _edit_prompt("front", front_text, haired=bool(hair_text(character_name)))
    refs = get_model_refs_dir(character_name)
    best: Optional[Tuple[str, str, Path]] = None
    for sidecar in refs.glob("tpose_*.json"):
        key = sidecar.stem[len("tpose_"):]
        if not key or "_" in key or is_base_signature(key) or is_outfit_body_signature(key):
            continue  # an extra view, a base body view, an outfit body's input
        meta = _ref_sidecar(sidecar)
        if meta.get("dressed") is not True or not _view_current(meta, bsig, base_views.get("front")):
            continue
        recorded = meta.get("dress_text")
        if not (recorded == front_text if isinstance(recorded, str) else meta.get("prompt") == prompt):
            continue
        if str(meta.get("outfit_reference_sha256") or "") != reference_sha:
            continue  # Ruling A74b: made from another outfit reference picture (or none)
        image = _image_at(refs / f"tpose_{key}")
        if image is None:
            continue
        stamp = str(meta.get("created_at") or "")
        if best is None or stamp > best[0]:
            best = (stamp, key, image)
    if best is None:
        return None
    _stamp, key, front = best
    front_sha = file_sha256(front)
    views = ["front"]
    for v in dressed_views():
        if v == "front":
            continue
        path = _image_at(refs / f"{_kind(v)}_{key}")
        record = _ref_sidecar(path)
        if (path is not None and _view_current(record, bsig, base_views.get(v))
                and follows_front(v, record, draft_path(character_name, v, key), front_sha)):
            views.append(v)
    return key, views


def dressed_view_estimate(character_name: str, fig, signature: str, *,
                          profile: Optional[Dict[str, Any]] = None) -> int:
    """Hub jobs a dressed-image pass (``generate_dressed_images``) of the
    delivered figure ``fig`` for ``signature`` spends on its first attempts —
    the Build's estimate (fix round T12-F1, ruling F13 c). Per
    ``dressed_views()`` view that is not stored (``dressed_image``): 0 when
    the pass COPIES it from the texture store of ``fig.texture``
    (``_reuse_texture_views``: the store's front made from the current base
    front, or one ``_adopt_texture_views`` would adopt; a back/side the
    store holds — or the adopted outfit has — following that front), else
    the front 1 job (the edit) and every other view 1 (the draft; its
    composite onto the base view is CPU work, Task 11g) — 0 while the stored
    front stays and the view's stored draft follows it (``stored_draft``,
    Ruling C2: composited again, no job). A figure without a
    texture copies its views from the shape: 0. A retry (the view guard's
    re-render, a re-draft after a refused composite) is not counted — the UI
    says "estimate, retries extra". Read-only."""
    from app.core.model_refs import find_ref_image
    missing = [v for v in dressed_views()
               if dressed_image(character_name, v, signature, fig.bsig, fig=fig) is None]
    if not missing or not fig.texture:
        return 0
    jobs = {v: 1 for v in missing}
    if "front" not in missing:
        # Ruling C2: a back/side whose stored draft follows the outfit's front is composited from it again.
        front_now = find_ref_image(character_name, "tpose", signature)
        # Ruling FR-I3: a view whose composite was refused for these inputs is drafted anew on its retry.
        refused = dressed_view_refusals(character_name, fig, signature)
        for v in list(jobs):
            if v not in refused and stored_draft(character_name, v, signature, front_now) is not None:
                jobs[v] = 0
    tsig = fig.texture
    if not is_texture_signature(tsig):
        return sum(jobs.values())
    on = fig.shape
    base_views = {v: find_ref_image(character_name, _kind(v), on) for v in BASE_VIEWS}
    source_front = _store_front(character_name, tsig, on, base_views.get("front"))
    adopted: Optional[Tuple[str, List[str]]] = None
    if source_front is None:
        if "front" not in missing:
            return sum(jobs.values())
        profile = _profile_of(character_name, profile)
        texts = figure_texts(character_name, fig, list(profile.get("equipped_items") or []), profile=profile)
        from app.core import outfit_references
        adopted = _adoptable_texture_views(character_name, bsig=on, texts=texts, base_views=base_views,
                                           reference_sha=outfit_references.wanted_sha(
                                               character_name, fig.pieces, fig.open, profile=profile))
        if adopted is None:
            return sum(jobs.values())
        source_front = find_ref_image(character_name, "tpose", adopted[0])
        if source_front is None:
            return sum(jobs.values())
    jobs.pop("front", None)
    # A back/side is copied only while the outfit's front is (or becomes) the source's front.
    front_sha = file_sha256(source_front)
    if "front" not in missing:
        outfit_front = find_ref_image(character_name, "tpose", signature)
        if outfit_front is None or file_sha256(outfit_front) != front_sha:
            return sum(jobs.values())
    for v in list(jobs):
        if adopted is not None:
            if v in adopted[1]:
                jobs[v] = 0
            continue
        source = _texture_view(character_name, v, tsig)
        record = _ref_sidecar(source)
        if (source is not None and _view_current(record, on, base_views.get(v))
                and follows_front(v, record, _texture_draft(character_name, v, tsig), front_sha)):
            jobs[v] = 0
    return sum(jobs.values())


def _reuse_texture_views(character_name: str, *, signature: str, tsig: str, bsig: str, todo: List[str],
                         texts: Dict[str, str], base_views: Dict[str, Optional[Path]],
                         pieces: Optional[Dict[str, str]], items: Optional[list], profile: Dict[str, Any],
                         mesh: Dict[str, Any], reference_sha: str = "") -> Dict[str, Path]:
    """Copy the views of ``todo`` the texture store holds for ``tsig`` into
    the outfit (``tpose[_<view>]_<signature>`` + drafts), filling the store
    from other outfits first when it has no front (``_adopt_texture_views``).
    A back/side is copied only when it follows the store's front and the
    outfit's front IS that front (copied now or the same content). No image
    job. Returns ``{view: outfit path}`` of the copied views."""
    from app.core.model_refs import find_ref_image, get_model_refs_dir
    front = (_store_front(character_name, tsig, bsig, base_views.get("front"))
             or _adopt_texture_views(character_name, tsig=tsig, bsig=bsig, texts=texts, base_views=base_views,
                                     reference_sha=reference_sha))
    if front is None:
        return {}
    refs = get_model_refs_dir(character_name)
    front_sha = file_sha256(front)
    copied: Dict[str, Path] = {}

    def copy(v: str, source: Path) -> None:
        record = _ref_sidecar(source)
        meta = _outfit_view_meta(character_name, record, pieces=pieces, items=items, profile=profile,
                                 mesh=mesh, tsig=tsig)
        if v in DRAFT_VIEWS:
            draft = _texture_draft(character_name, v, tsig)
            if draft is not None:
                draft_meta = _outfit_view_meta(character_name, _ref_sidecar(draft), pieces=pieces, items=items,
                                               profile=profile, mesh=mesh, tsig=tsig)
                meta[f"{v}_draft"] = _copy_ref(draft, refs / DRAFT_DIR / f"{_kind(v)}_{signature}",
                                               draft_meta).name
        copied[v] = _copy_ref(source, refs / f"{_kind(v)}_{signature}", meta)

    if "front" in todo:
        copy("front", front)
    outfit_front = find_ref_image(character_name, "tpose", signature)
    if outfit_front is None or file_sha256(outfit_front) != front_sha:
        return copied
    for v in todo:
        if v == "front":
            continue
        source = _texture_view(character_name, v, tsig)
        record = _ref_sidecar(source)
        if (source is not None and _view_current(record, bsig, base_views.get(v))
                and follows_front(v, record, _texture_draft(character_name, v, tsig), front_sha)):
            copy(v, source)
    if copied:
        logger.info("Dressed images %s (%s): %s copied from texture %s — no render", character_name, signature,
                    sorted(copied), tsig)
    return copied


def _newer(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_mtime_ns > b.stat().st_mtime_ns
    except OSError:
        return False


def _sync_texture_views(character_name: str, *, signature: str, tsig: str, fig,
                        base_views: Dict[str, Optional[Path]], texts: Dict[str, str],
                        manifest: Dict[str, Any], profile: Dict[str, Any]) -> None:
    """Before a build of a DRESSED outfit: its views and the store's views
    of ``tsig`` become one set, view by view, the NEWER file winning where
    the contents differ — a view rendered again for another outfit of the
    same texture reaches this one (copied from the store), one rendered
    for this outfit reaches the store. Without a store front the outfit's
    views become the store's. A back/side of the store is taken only while
    it follows the front the outfit then has (``follows_front``). ``fig``:
    the delivered figure the views belong to; ``base_views`` are the views
    of its shape (the plain body's or the meshed shape's)."""
    on = fig.shape
    outfit = {v: dressed_image(character_name, v, signature, fig.bsig, fig=fig) for v in dressed_views()}
    if outfit.get("front") is None:
        return
    store_front = _store_front(character_name, tsig, on, base_views.get("front"))
    own = [v for v, p in outfit.items() if p is not None]
    if store_front is None:
        _store_texture_views(character_name, signature, tsig, own, texts)
        return
    from app.core import outfit_references
    kwargs = dict(signature=signature, tsig=tsig, bsig=on, texts=texts, base_views=base_views,
                  pieces=manifest.get("pieces") or {}, items=manifest.get("items") or [], profile=profile,
                  mesh=_dict_of(manifest.get("mesh_items")),
                  reference_sha=outfit_references.wanted_sha(character_name, fig.pieces, fig.open))
    front_sha = file_sha256(store_front)
    if file_sha256(outfit["front"]) != front_sha:
        if _newer(outfit["front"], store_front):
            _store_texture_views(character_name, signature, tsig, own, texts)
        else:
            _reuse_texture_views(character_name, todo=list(outfit), **kwargs)
        return
    for v in outfit:
        if v == "front":
            continue
        mine = outfit[v]
        theirs = _texture_view(character_name, v, tsig)
        if theirs is not None and not (_view_current(_ref_sidecar(theirs), on, base_views.get(v)) and follows_front(
                v, _ref_sidecar(theirs), _texture_draft(character_name, v, tsig), front_sha)):
            theirs = None
        if mine is not None and (theirs is None or (file_sha256(mine) != file_sha256(theirs)
                                                    and _newer(mine, theirs))):
            _store_texture_views(character_name, signature, tsig, [v], texts)
        elif theirs is not None and (mine is None or file_sha256(mine) != file_sha256(theirs)):
            _reuse_texture_views(character_name, todo=[v], **kwargs)


def texture_view_shas(character_name: str, signature: str, bsig: str, *, fig=None) -> Dict[str, str]:
    """``{view: sha256}`` of the outfit's current dressed views
    (``dressed_image``; "" for a missing one) — what a painted body was
    made from."""
    return {v: file_sha256(dressed_image(character_name, v, signature, bsig, fig=fig)) for v in dressed_views()}


def shape_view_shas(character_name: str, shape: str, bsig: str) -> Dict[str, str]:
    """``{view: sha256}`` of the stored views of the meshed shape ``shape``
    (``model_refs/tpose[_<view>]_<shape>``, ``dressed_views()``) that were
    edited from the CURRENT plain body ``bsig`` (sidecar ``base_signature``
    and ``base_image_sha256`` = that base view's content); "" for a missing
    or outdated one — what ``figure.stored_shape`` compares with the
    shape's recorded ``views``. Read-only."""
    from app.core.model_refs import find_ref_image
    out: Dict[str, str] = {}
    for v in dressed_views():
        path = find_ref_image(character_name, _kind(v), shape)
        meta = _ref_sidecar(path)
        current = (path is not None and meta.get("base_signature") == bsig and not is_model_fit(meta)
                   and meta.get("base_image_sha256") == file_sha256(find_ref_image(character_name, _kind(v), bsig)))
        out[v] = file_sha256(path) if current else ""
    return out


def _source_sha(base: Dict[str, Any], variant: str) -> str:
    source = base.get("covered") if variant == "covered" else base.get("rigged")
    return hashlib.sha256(source).hexdigest() if source else ""


def stored_texture_body(character_name: str, tsig: str, *, base: Dict[str, Any],
                        view_shas: Dict[str, str]) -> Optional[Tuple[bytes, Dict[str, Any]]]:
    """``(glb bytes, sidecar)`` of the painted body of ``tsig`` when it
    is current for the base snapshot ``base`` (``_snapshot_base_model``)
    and the dressed views ``view_shas``, else None:
    its sidecar names ``tsig``, the base model's content
    (``base_model_sha256``) and the content of the model it was painted
    into (``source_model_sha256``: the rigged base or its covered variant);
    a body built without the covered variant it wanted (``covered_missing``)
    is not current once the base has one; its ``views`` are ``view_shas``
    exactly; the GLB is the one the sidecar describes (``body_sha256``)."""
    path = texture_body_path(character_name, tsig)
    meta = _ref_sidecar(path)
    if not meta or meta.get("texture_signature") != tsig or not path.is_file():
        return None
    if meta.get("base_model_sha256") != hashlib.sha256(base["rigged"]).hexdigest():
        return None
    variant = str(meta.get("base_variant") or "rigged")
    if meta.get("source_model_sha256") != _source_sha(base, variant):
        return None
    if meta.get("covered_missing") and base.get("covered") is not None:
        return None
    if meta.get("views") != view_shas:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if hashlib.sha256(data).hexdigest() != meta.get("body_sha256"):
        return None
    return data, meta


def _store_texture_body(character_name: str, tsig: str, data: bytes, record: Dict[str, Any]) -> None:
    """Write the painted body of ``tsig`` (GLB, then its sidecar — a reader
    checks ``body_sha256``, so a half-written pair is never reused). A
    failure only costs the reuse: the outfit model is built anyway."""
    try:
        path = texture_body_path(character_name, tsig)
        _atomic_write(path, data)
        _atomic_write(path.with_suffix(".json"), json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning("Painted body %s of %s not stored: %s", tsig, character_name, e)


def texture_users(character_name: str) -> Dict[str, List[str]]:
    """``{tsig: [outfit signature, ...]}`` of the stored outfit models
    (top-level ``model3d/<sig>.json`` naming a ``texture_signature``)."""
    from app.models.character import get_character_dir
    out: Dict[str, List[str]] = {}
    directory = get_character_dir(character_name) / "model3d"
    if not directory.is_dir():
        return out
    for sidecar in sorted(directory.glob("*.json")):
        tsig = _ref_sidecar(sidecar).get("texture_signature")
        if is_texture_signature(tsig) and not is_base_signature(sidecar.stem):
            out.setdefault(str(tsig), []).append(sidecar.stem)
    return out


#: A meshed shape whose stored views are gone (``generate_dressed_images`` on it).
SHAPE_VIEWS_MISSING = "The body shape's views are missing — build the figure again"


def _bald_edit(character_name: str, profile: Dict[str, Any], *, meshed: bool) -> bool:
    """Whether a dressed edit closes with the bald head (``dress_prompt(bald=
    True)``, controller ruling 2026-11-10): the views of a meshed shape and
    the edits painted on one, of a character on the pipeline whose hair is
    NOT in the body and who wears its own hair item — those bodies are bald
    under the hair mesh by construction, the words only make it robust. A
    prompt detail, never part of a key. The plain body's painted views keep
    the base front's head as it is."""
    if not meshed or not is_base_pipeline(character_name, profile=profile):
        return False
    from app.core.garment_hair import BALD, hair_in_body, shape_hair, worn_hair_id
    shape = shape_hair(character_name, profile)
    if shape:
        return shape == BALD  # the worn hairstyle's own shape (D4): bald, or another hairstyle's hair
    if hair_in_body(character_name, profile):
        return False  # the hair is in the body
    return bool(worn_hair_id(character_name, profile))


def _shape_hair(character_name: str, profile: Dict[str, Any], *, meshed: bool) -> Optional[str]:
    """The hair of the meshed shape an edit works on when it is not the plain
    body's (``garment_hair.shape_hair``: another hairstyle's text or
    ``garment_hair.BALD``, D4); None on the plain body, off the pipeline or
    for the plain body's own hair — ``dress_prompt`` / ``draft_prompt``
    ``hair``."""
    if not meshed or not is_base_pipeline(character_name, profile=profile):
        return None
    from app.core.garment_hair import shape_hair
    return shape_hair(character_name, profile) or None


def _worn_profile(profile: Dict[str, Any], pieces: Optional[Dict[str, str]], items: Optional[list]) -> Dict[str, Any]:
    out = deepcopy(profile)
    out["equipped_pieces"] = dict(pieces or {})
    out["equipped_items"] = list(items or [])
    return out


def figure_texts(character_name: str, fig, items: Optional[list], *,
                 profile: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """``{view: text}`` of the dressed edits of the delivered figure ``fig``
    (``dress_text`` of its pieces and ``items`` with every own-mesh piece
    that is not painted — grafted or left out — left out). On the plain body
    this is the tsig's dress text (``texture_inputs``); on a meshed shape the
    in-body pieces stay in the text: the edit keeps what the shape wears and
    only paints the rest on (the texture KEY names the painted pieces alone,
    ``figure.texture_key``)."""
    profile = _worn_profile(_profile_of(character_name, profile), fig.pieces, items)
    left = sorted({*fig.own, *fig.left_out})
    state = {i: "open" for i in fig.open}
    return {v: dress_text(character_name, v, pieces=dict(fig.pieces), items=list(items or []), profile=profile,
                          mesh_items=left, piece_state=state) for v in dressed_views()}


#: Where the dressed views of a figure come from (``dressed_view_source``, Ruling A70).
VIEW_SOURCE_PAINTED = "painted"
VIEW_SOURCE_SHAPE = "shape"
VIEW_SOURCE_PLAIN = "plain"


def _paints(fig, texts: Dict[str, str]) -> bool:
    """Whether the dressed views of the figure ``fig`` are edits (something is painted) or copies of its shape's
    views: on a meshed shape exactly when the figure has a texture (Ruling A50), on the plain body when the dress
    text of the front is not empty (``figure_texts``). THE decision of ``generate_dressed_images``."""
    from app.core import figure as figure_mod
    return bool(fig.texture) if not figure_mod.is_plain(fig.shape) else bool(texts.get("front"))


def dressed_view_source(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Where a render of a dressed view of the worn outfit comes from now (Ruling A70) — the branch
    ``generate_dressed_images`` takes for the figure delivered NOW (``_paints``):

    * ``painted`` — an edit of the shape's front, a back / side view a draft composited onto the shape's view:
      ONE image job per view (a forced render skips the texture store and the stored draft);
    * ``shape`` — nothing is painted on the meshed body shape (its pieces are in the body or have their own
      mesh): the view is a COPY of the body shape's own view (``tpose[_<view>]_<ob…>``), no job;
    * ``plain`` — nothing worn is painted on the plain body: a copy of the plain body's view, no job.

    ``{source, shape, jobs}`` — ``jobs`` of one view's render; a painted figure adds ``reference: True`` when the outfit
    has its own reference image, so its FRONT is an edit of that picture (Ruling A74b). Read-only (the memoised
    figure, polled by the views' info)."""
    from app.core import figure as figure_mod
    from app.core.model_refs import current_outfit_state
    profile = _profile_of(character_name, profile)
    pieces, items, _signature = current_outfit_state(character_name)
    fig = figure_mod.delivered_figure_cached(character_name, profile=profile, pieces=dict(pieces or {}),
                                             items=list(items or []))
    texts = {} if not figure_mod.is_plain(fig.shape) else figure_texts(character_name, fig, items, profile=profile)
    if _paints(fig, texts):
        # Ruling A74b: with the outfit's own reference image the front is an edit of that picture.
        from app.core import outfit_references
        out = {"source": VIEW_SOURCE_PAINTED, "shape": fig.shape, "jobs": 1}
        if outfit_references.wanted_sha(character_name, fig.pieces, fig.open, profile=profile):
            out["reference"] = True
        return out
    source = VIEW_SOURCE_PLAIN if figure_mod.is_plain(fig.shape) else VIEW_SOURCE_SHAPE
    return {"source": source, "shape": fig.shape, "jobs": 0}


def generate_dressed_images(character_name: str, *, pieces: Optional[Dict[str, str]],
                            items: Optional[list], signature: str, force: bool = False,
                            view: Optional[str] = None, raise_load: bool = False) -> Dict[str, Optional[str]]:
    """The outfit's mesh-input images on the base-body pipeline: the views of
    the figure delivered NOW (``figure.delivered_figure``; plan
    2026-11-12-unified-worn-pieces Task 6). Blocking — called from
    ``model_refs.generate_model_ref_images`` (kind ``tpose``), serial per
    character on its tpose lane, and before an outfit model that needs a
    shape built since its views were made (``ensure_figure_views``).

    Only ``dressed_views()`` (or ``view`` alone — a side view while the side
    views are off is a ValueError with ``SIDE_VIEW_NOT_DRESSED``). The views
    are edits of the views of the figure's SHAPE: the plain body's
    (``tpose[_<view>]_<bsig>``) or the meshed shape's
    (``tpose[_<view>]_<ob…>``, ``prepare_shape``):

    * front: an EDIT of the shape's front (``reference_image`` = it on grey,
      ``bare_prompt`` = ``dress_prompt`` of ``figure_texts``, occasion
      ``outfit_front``, use case ``DRESS_USE_CASE``);
    * back, then left/right when on: ``_dress_view`` — a draft from the
      dressed front (occasion ``outfit_back_draft``, for the sides
      ``outfit_side_draft``), then its CPU composite onto the shape's view
      (``view_composite``, gated); each needs the dressed front (rendered in
      the same pass, or the stored one — else the status error
      ``DRESSED_FRONT_FIRST``). A composite refused twice leaves the view
      unrendered with the numbers as its error.

    Nothing to paint (an undressed combination on the plain body, or a
    meshed shape with nothing painted on it — texture ``""``) copies the
    shape's views instead (no GPU run; ``dressed: false``). Stored as
    ``tpose_<sig>`` / ``tpose_<view>_<sig>``, sidecar ``base_signature`` =
    the shape, ``base_image_sha256`` (the edited view's content),
    ``texture_signature`` = the figure's texture and the own-mesh record
    ``mesh_items`` (``mesh_record``, with the figure). A view current for
    the figure (``dressed_image``) is skipped unless ``force``. A kept gate
    warning (``fit_gate_warning``) is in the view's sidecar and in
    ``outfit_info``'s warnings.

    Own-mesh pieces: the delivered figure decides, NO garment chain runs
    here (ruling A14 — the views never wait for a chain; the Build's
    ``pieces`` step runs them): a grafted piece is left out of the text
    BEFORE the outfit text resolves ``covers`` (a piece hidden under a mesh
    dress is painted); a piece without its mesh is in the body shape
    meanwhile (ruling A11) — it stays in the text, and the views are edits
    of that interim shape's views. The front records ``mesh_record``; the
    views after the front take the front's record.

    Texture reuse (plan 2026-11-10-texture-body-reuse, Task 1): the views
    belong to the texture ``figure.texture``. Unless ``force``, a view the
    texture store holds for it (or adopts from another outfit's views that
    prove the same dress text on the same shape, ``_adopt_texture_views``)
    is COPIED into the outfit — no image job; only the rest is rendered and
    then published into the store.

    Missing shape views: the status error ``BASE_IMAGES_MISSING`` /
    ``SHAPE_VIEWS_MISSING``, nothing rendered. Returns ``{kind: path | None}``
    for every view it produced.

    ``raise_load`` (the improvements queue's ``outfit_rebuild``): a busy
    backend or the media switch off (``BackendBusyError`` /
    ``MediaGenerationDisabled``) during a render is RAISED instead of
    becoming a view error, and the pass ends without a failure record —
    load is busy, never a failure. Every other caller keeps the error."""
    from app.core import figure as figure_mod
    from app.core.model_refs import find_ref_image
    if view is not None and view not in BASE_VIEWS:
        raise ValueError(f"unknown base-body view: {view!r}")
    views = dressed_views()
    if view is not None and view not in views:
        raise ValueError(SIDE_VIEW_NOT_DRESSED)
    profile = _profile_of(character_name, None)
    bsig = base_signature(character_name, profile=profile)
    wanted = views if view is None else (view,)
    mesh_profile = _worn_profile(profile, pieces, items)
    fig = figure_mod.delivered_figure(character_name, profile=profile, pieces=dict(pieces or {}),
                                      items=list(items or []))
    todo = [v for v in wanted if force or dressed_image(character_name, v, signature, bsig, fig=fig) is None]
    if not todo:
        _outfit_end(character_name, signature, "images", None)
        return {}
    # Own-mesh pieces: the figure delivered now decides — no chain runs first (ruling A14: a piece without its
    # mesh is in the body shape meanwhile, A11); the other views follow the stored front's record.
    front_now = None if "front" in todo else dressed_image(character_name, "front", signature, bsig, fig=fig)
    if front_now is not None:
        recorded = _ref_sidecar(front_now).get("mesh_items")
        mesh = recorded if isinstance(recorded, dict) else {}
    else:
        mesh = mesh_record(character_name, fig)
    on = fig.shape
    meshed = not figure_mod.is_plain(on)
    registrations = {v: find_ref_image(character_name, _kind(v), on) for v in BASE_VIEWS}
    if any(registrations[v] is None for v in todo):
        logger.warning("Dressed images %s (%s): views of %s missing", character_name, signature, on)
        _outfit_end(character_name, signature, "images", SHAPE_VIEWS_MISSING if meshed else BASE_IMAGES_MISSING)
        return {}
    texts = figure_texts(character_name, fig, items, profile=profile)
    dressed = _paints(fig, texts)
    # Ruling A74b: the outfit's own reference picture — its dressed front is an edit of it while something is painted.
    from app.core import outfit_references
    record = outfit_references.record_for(character_name, fig.pieces, fig.open, profile=profile) if dressed else None
    reference = ({"path": outfit_references.image_path(character_name, record), "sha256": record["sha256"]}
                 if record else None)
    return _render_views(character_name, signature=signature, pieces=pieces, items=items, todo=todo, force=force,
                         on=on, registrations=registrations, texts=texts, tsig=fig.texture, mesh=mesh,
                         dressed=dressed, bald=_bald_edit(character_name, profile, meshed=meshed),
                         profile=mesh_profile, raise_load=raise_load,
                         current=lambda v: dressed_image(character_name, v, signature, bsig, fig=fig),
                         hair=_shape_hair(character_name, profile, meshed=meshed), reference=reference)


#: The character block of an outfit's dressed front made from its reference
#: picture (Ruling A74b), after the head words: the clothing is the
#: picture's — never named (Ruling A29: a view change never names it).
OUTFIT_REFERENCE_BODY = "wearing exactly the clothing of the person in the picture and nothing else"


def outfit_edit_prompt(character_name: str, *, text: str, bald: bool, hair: Optional[str],
                       profile: Optional[Dict[str, Any]] = None) -> Tuple[str, str, str]:
    """``(character block, prompt, negative)`` of an outfit's dressed front
    made from its reference picture: the block is the head of the body the
    outfit is painted on (``BALD_HEAD`` for a bald one or under an own hair
    mesh — ``bald`` —, else its hair text; ``hair`` as ``dress_prompt``'s)
    and ``OUTFIT_REFERENCE_BODY``, for ``BASE_FRONT_EDIT_USE_CASE``'s slot;
    the prompt is the base front's pose text (with the hair clauses of a
    haired body); the negative is the dressed front's (``dress_negative`` of
    the outfit text ``text``, ``HAIR_NEGATIVE`` when bald) and
    ``POSE_NEGATIVE``."""
    from app.core.garment_hair import BALD
    profile = _profile_of(character_name, profile)
    worn_hair = hair_text(character_name, profile=profile) if hair is None else ("" if hair == BALD else hair)
    haired = bool(worn_hair) and not bald
    block = ", ".join((worn_hair if haired else BALD_HEAD, OUTFIT_REFERENCE_BODY))
    prompt = _haired_front_pose(character_name, worn_hair, profile) if haired else _pose_text("front")
    negative = dress_negative(text, keep_hair=haired)
    if bald:
        negative = f"{negative}, {HAIR_NEGATIVE}"
    return block, prompt, f"{negative}, {POSE_NEGATIVE}"


def _reference_front(character_name: str, *, signature: str, reference: Dict[str, Any], refs_dir: Path,
                     pieces: Optional[Dict[str, str]], items: Optional[list], profile: Dict[str, Any], text: str,
                     bald: bool, hair: Optional[str], on: str, registration: Optional[Path],
                     extra: Dict[str, Any], load_kwargs: Dict[str, Any]) -> Optional[Path]:
    """The dressed front of ``signature`` as an EDIT of the outfit's reference
    picture (Ruling A74b): ``reference`` = ``{path, sha256}``; the picture is
    frozen for the render (``_frozen_reference``), the edit is
    ``outfit_edit_prompt`` under ``BASE_FRONT_EDIT_USE_CASE`` on the dressed
    front's routing (occasion ``outfit_front``) with ``require_reference`` —
    a routed backend without a reference slot is not applicable, never a text
    render. The sidecar records the shape ``on`` and its front's content
    (``base_image_sha256`` — the view belongs to that body like an edit of
    it), ``outfit_reference_sha256`` / ``outfit_reference_image`` and
    ``extra``. ``OutfitError`` when the picture is gone or changed since it
    was picked."""
    from app.core import expression_regen
    from app.core.model_refs import _tpose_size
    from app.core.outfit_references import REFERENCE_GONE
    source = reference.get("path")
    if source is None:
        raise OutfitError(REFERENCE_GONE)
    block, prompt, negative = outfit_edit_prompt(character_name, text=text, bald=bald, hair=hair, profile=profile)
    width, height = _tpose_size()
    with _frozen_reference(Path(source), refs_dir) as (frozen, sha):
        if sha != reference.get("sha256"):
            raise OutfitError("The outfit's full-body reference changed since it was picked — pick it again")
        return expression_regen.render_character_image(
            character_name,
            output_stem=refs_dir / f"tpose_{signature}",
            equipped_pieces=dict(pieces or {}), equipped_items=list(items or []),
            pose_prompt="", expression_prompt="",
            bare_prompt=prompt, extra_negative=negative,
            image_use_case=BASE_FRONT_EDIT_USE_CASE, style_character=block,
            occasion="outfit_front",
            override_width=width, override_height=height,
            apply_state_modifiers=False,
            mesh_input_profile=profile,
            reference_image=frozen, require_reference=True,
            sidecar_extra={"base_signature": on, "dressed": True, "base_image_sha256": file_sha256(registration),
                           "outfit_reference_sha256": sha, "outfit_reference_image": Path(source).name, **extra},
            character_loras=True, **load_kwargs)


def _render_views(character_name: str, *, signature: str, pieces: Optional[Dict[str, str]], items: Optional[list],
                  todo: List[str], force: bool, on: str, registrations: Dict[str, Optional[Path]],
                  texts: Dict[str, str], tsig: str, mesh: Dict[str, Any], dressed: bool, bald: bool,
                  profile: Dict[str, Any], raise_load: bool, current, hair: Optional[str] = None,
                  hair_edit: bool = False, reference: Optional[Dict[str, Any]] = None) -> Dict[str, Optional[str]]:
    """The render pass of ``generate_dressed_images`` (and of a shape's own
    views, ``prepare_shape``): the views ``todo`` of ``signature`` edited
    from the views ``registrations`` of the shape ``on`` with the dress
    texts ``texts`` (or copied from them when not ``dressed``), recorded
    under the texture ``tsig`` and the own-mesh record ``mesh``. ``profile``
    wears ``pieces`` / ``items``; ``current(view)`` is the stored view that
    counts now (the dressed front the back is drafted from). ``hair`` /
    ``hair_edit``: ``dress_prompt``'s (the shape's hair when it is not the
    plain body's; a shape's own views put it on). ``reference`` (Ruling
    A74b, an outfit's own picture: ``{path, sha256}``, ``path`` None when it
    is gone): the dressed front is an EDIT of that picture
    (``_reference_front``) instead of the shape's front, and every view
    written records ``outfit_reference_sha256``."""
    import shutil
    from app.core import expression_regen
    from app.core.garment_images import square_reference
    from app.core.model_refs import _tpose_size, get_model_refs_dir, mesh_items_token, mesh_variant
    refs_dir = get_model_refs_dir(character_name)
    results: Dict[str, Optional[str]] = {}
    errors = []
    load_kwargs = {"raise_load": True} if raise_load else {}
    interrupted = False
    mesh_extra = {"mesh_items": mesh} if mesh else {}
    ref_extra = {"outfit_reference_sha256": reference["sha256"]} if reference else {}
    _outfit_start(character_name, signature, "images")
    try:
        if not dressed:
            from app.core.timeutils import utc_now_iso
            variant = mesh_variant(character_name, dict(pieces or {}), profile)
            token = mesh_items_token(character_name, dict(pieces or {}), profile)
            for v in todo:
                source = registrations[v]
                target = refs_dir / f"{_kind(v)}_{signature}{source.suffix}"
                shutil.copyfile(source, target)
                meta = {k: val for k, val in _ref_sidecar(source).items() if k != "outfit_body"}
                meta.update({"created_at": utc_now_iso(),
                             "equipped_pieces": dict(pieces or {}), "equipped_items": list(items or []),
                             "mesh_variant": variant, "base_signature": on,
                             "base_image_sha256": file_sha256(source), "dressed": False, **mesh_extra,
                             "texture_signature": tsig})
                if token:
                    meta["mesh_token"] = token
                target.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                                       encoding="utf-8")
                results[_kind(v)] = str(target)
        else:
            width, height = _tpose_size()
            if not force and is_texture_signature(tsig):
                reused = _reuse_texture_views(character_name, signature=signature, tsig=tsig, bsig=on,
                                              todo=todo, texts=texts, base_views=registrations, pieces=pieces,
                                              items=items, profile=profile, mesh=mesh,
                                              reference_sha=reference["sha256"] if reference else "")
                for v, path in reused.items():
                    results[_kind(v)] = str(path)
                todo = [v for v in todo if v not in reused]
            if "front" in todo and reference is not None:
                try:
                    path = _reference_front(character_name, signature=signature, reference=reference,
                                            refs_dir=refs_dir, pieces=pieces, items=items, profile=profile,
                                            text=texts.get("front", ""), bald=bald, hair=hair, on=on,
                                            registration=registrations["front"],
                                            extra={**mesh_extra, "texture_signature": tsig,
                                                   "dress_text": texts.get("front", "")},
                                            load_kwargs=load_kwargs)
                    if path is None:
                        errors.append("Dressed front edit of the outfit's full-body reference failed")
                except Exception as e:  # noqa: BLE001 — one view never kills the pass
                    if raise_load and _is_load(e):
                        interrupted = True
                        raise
                    path = None
                    errors.append(str(e) if isinstance(e, OutfitError)
                                  else f"Dressed front edit of the outfit's full-body reference failed: {e}")
                    logger.warning("Dressed %s front (%s) from its reference failed: %s", character_name, signature, e)
                results["tpose"] = str(path) if path else None
            elif "front" in todo:
                prompt, negative = dress_prompt(character_name, "front", pieces=pieces, items=items,
                                                profile=profile, text=texts.get("front", ""), bald=bald,
                                                hair=hair, hair_edit=hair_edit)
                try:
                    # The base front centred on a square canvas, the edit
                    # cut back to its frame (ruling F14 g: a narrow source
                    # gets re-framed by the edit model).
                    with square_reference(registrations["front"], refs_dir) as (reference, side, offset,
                                                                                 source_size):
                        path = expression_regen.render_character_image(
                            character_name,
                            output_stem=refs_dir / f"tpose_{signature}",
                            equipped_pieces=dict(pieces or {}), equipped_items=list(items or []),
                            pose_prompt="", expression_prompt="",
                            bare_prompt=prompt, extra_negative=negative,
                            # No style: the edit instruction is the whole
                            # prompt (review 2026-11-11 — the tpose style
                            # stood in front of "Keep the image exactly as
                            # it is" and put the outfit at word 110).
                            image_use_case=DRESS_USE_CASE,
                            occasion="outfit_front",
                            override_width=side, override_height=side,
                            crop_back_to=(side, offset, source_size),
                            apply_state_modifiers=False,
                            mesh_input_profile=profile,
                            reference_image=reference,
                            sidecar_extra={"base_signature": on, "dressed": True,
                                           "base_image_sha256": file_sha256(registrations["front"]),
                                           **mesh_extra, "texture_signature": tsig,
                                           "dress_text": texts.get("front", "")},
                            character_loras=True, **load_kwargs)
                    if path is None:
                        errors.append("Dressed front edit failed")
                except Exception as e:  # noqa: BLE001 — one view never kills the pass
                    if raise_load and _is_load(e):
                        interrupted = True
                        raise
                    path = None
                    errors.append(f"Dressed front edit failed: {e}")
                    logger.warning("Dressed %s front (%s) failed: %s", character_name, signature, e)
                results["tpose"] = str(path) if path else None
            for v in (v for v in DRAFT_VIEWS if v in todo):
                front = current("front")
                path = None
                if front is None:
                    errors.append(DRESSED_FRONT_STALE if stale_views(character_name, signature, ("front",))
                                  else DRESSED_FRONT_FIRST)
                else:
                    try:
                        path, warning = _dress_view(
                            character_name, v, signature=signature, bsig=on, pieces=pieces, items=items,
                            profile=profile, front=front, base_views=registrations, refs_dir=refs_dir,
                            size=(width, height), mesh_items=_ref_sidecar(front).get("mesh_items") or None,
                            texture={"texture_signature": tsig, "dress_text": texts.get(v, ""), **ref_extra},
                            reuse_draft=not force, hair=hair, **load_kwargs)
                        if warning:
                            logger.warning("Dressed %s %s (%s): %s", v, character_name, signature, warning)
                    except Exception as e:  # noqa: BLE001 — the front stays
                        if raise_load and _is_load(e):
                            interrupted = True
                            raise
                        errors.append(str(e) if isinstance(e, OutfitError) else f"Dressed {v} edit failed: {e}")
                        logger.warning("Dressed %s %s (%s) failed: %s", character_name, v, signature, e)
                results[_kind(v)] = str(path) if path else None
            rendered = [v for v in todo if results.get(_kind(v))]
            if rendered:
                _store_texture_views(character_name, signature, tsig, rendered, texts)
    finally:
        _outfit_end(character_name, signature, "images", errors[0] if errors else None,
                    interrupted=interrupted)
        from app.core import figure
        figure.invalidate()   # rendered views (a shape's own ones among them)
    logger.info("Dressed images %s (%s on %s): %s", character_name, signature, on,
                {k: bool(p) for k, p in results.items()})
    return results


# --- View guard -------------------------------------------------------------

# An edit can turn the figure toward the camera while keeping its outline —
# the worker's framing check then lets it through. The guard compares the
# HEAD region of a dressed view with the four base views: it must be most
# similar to its own. Tuned on the end-to-end run of 2026-11-09 (head = top
# 12 % of the figure, 64x64 grey, zero-mean normalized cross-correlation):
# good front 0.982 (next 0.657), good left 0.888 (next 0.654); the turned
# left/right edits 0.567/0.412 against 0.750/0.495 for the front.
VIEW_GUARD_HEAD_SHARE = 0.12
VIEW_GUARD_SIZE = 64

# Ruling A16 (Task 11g-fix4): the head likeness above only tells the views
# apart while the dressed figure carries the SAME head as the plain views. A
# bald shape on a haired plain body (D4: a HairDeck hair worn on a haired
# base) or another hair in the body does not: a test character's bald back of the head
# correlated best with the haired FRONT (0.35 against -0.09 for the back,
# 2026-11-13 — three correct back renders refused). Whether the head differs
# is measured on the dressed FRONT of the same figure against the base front
# (``head_match``): on the 14 stored dressed fronts of a live world copy
# (2026-11-13) every haired front over its haired base 0.832 .. 0.988, the
# bald front of that character's shape oba9471e94 0.222 — limit ``HEAD_MATCH_MIN``.
# Such a figure is judged by a cue that does not depend on the hair: a
# frontal FACE in its head region (``face_found``, the LBP frontal-face
# cascade scikit-image ships). Measured on the same world's 328 stored views
# (head = top ``FACE_HEAD_SHARE`` of the figure at ``FACE_WORK_WIDTH`` px, a
# face at least ``FACE_MIN_SHARE`` of that wide, ``FACE_NEIGHBORS``
# neighbours, centred within ``FACE_CENTRE_TOL``): a face on 147 of 154
# fronts, on 0 of 115 backs and 0 of 59 side views; on the bald front,
# none on its three bald back renders, their draft or their composites. No
# plain views "edited to the same head" are stored (a bald shape's views are
# edits of the haired plain views), so the face is the cue the check uses.
HEAD_MATCH_MIN = 0.6
FACE_HEAD_SHARE = 0.16
FACE_WORK_WIDTH = 128
FACE_MIN_SHARE = 0.3
FACE_NEIGHBORS = 4
FACE_CENTRE_TOL = 0.2


def _head_image(path: Path, share: float):
    """The head region of a matted figure as a greyscale image on neutral
    grey, or None when it cannot be measured (unreadable, no transparent
    pixel = no matte, no figure). The figure is cropped to its alpha box,
    the top ``share`` of it cropped again to its own alpha box (the head,
    not the arm span)."""
    from PIL import Image
    try:
        with Image.open(path) as opened:
            image = opened.convert("RGBA")
    except (OSError, ValueError):
        return None
    alpha = image.getchannel("A")
    if alpha.getextrema()[0] == 255:
        return None
    box = alpha.getbbox()
    if box is None:
        return None
    figure = image.crop(box)
    head = figure.crop((0, 0, figure.width, max(1, round(figure.height * share))))
    box = head.getchannel("A").getbbox()
    if box is None:
        return None
    head = head.crop(box)
    flat = Image.new("RGBA", head.size, (128, 128, 128, 255))
    flat.alpha_composite(head)
    return flat.convert("L")


def _head_vector(path: Path):
    """The head region (``_head_image`` of the top ``VIEW_GUARD_HEAD_SHARE``)
    resized to ``VIEW_GUARD_SIZE`` squared as a unit, zero-mean vector, or
    None when it cannot be measured (also a flat head region)."""
    import numpy as np
    from PIL import Image
    grey = _head_image(path, VIEW_GUARD_HEAD_SHARE)
    if grey is None:
        return None
    grey = grey.resize((VIEW_GUARD_SIZE, VIEW_GUARD_SIZE), Image.BILINEAR)
    vector = np.asarray(grey, dtype=np.float64).ravel()
    vector = vector - vector.mean()
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 1e-9 else None


def head_match(front: Optional[Path], base_front: Optional[Path]) -> Optional[float]:
    """The head likeness (``_head_vector`` correlation) of a dressed front
    and the base front it was edited from; None when either cannot be
    measured. Below ``HEAD_MATCH_MIN`` the figure wears another head than
    the plain views (Ruling A16)."""
    if front is None or base_front is None:
        return None
    a, b = _head_vector(front), _head_vector(base_front)
    if a is None or b is None:
        return None
    return round(float(a @ b), 4)


_FACE_LOCK = threading.Lock()
_face_cascade = None


def face_found(path: Path) -> Optional[bool]:
    """Whether the head region of a matted figure shows a frontal face
    (Ruling A16): the top ``FACE_HEAD_SHARE`` of the figure (``_head_image``)
    at ``FACE_WORK_WIDTH`` px wide, scikit-image's LBP frontal-face cascade;
    a face counts when it is at least ``FACE_MIN_SHARE`` of the head wide,
    backed by ``FACE_NEIGHBORS`` detections and centred within
    ``FACE_CENTRE_TOL`` of the head's width (a profile's eye sits off the
    middle). None when the head cannot be measured."""
    global _face_cascade
    import numpy as np
    from PIL import Image
    grey = _head_image(path, FACE_HEAD_SHARE)
    if grey is None:
        return None
    width = FACE_WORK_WIDTH
    grey = grey.resize((width, max(1, round(grey.height * width / grey.width))), Image.BILINEAR)
    pixels = np.asarray(grey, dtype=np.float64) / 255.0
    side = max(1, int(width * FACE_MIN_SHARE))
    if pixels.shape[0] < side:
        return False
    with _FACE_LOCK:
        if _face_cascade is None:
            from skimage import data
            from skimage.feature import Cascade
            _face_cascade = Cascade(data.lbp_frontal_face_cascade_filename())
        found = _face_cascade.detect_multi_scale(img=pixels, scale_factor=1.1, step_ratio=1, min_size=(side, side),
                                                 max_size=(width, width), min_neighbor_number=FACE_NEIGHBORS)
    return any(abs((f["c"] + f["width"] / 2) / width - 0.5) <= FACE_CENTRE_TOL for f in found)


def view_guard(view: str, dressed: Path, base_views: Dict[str, Optional[Path]], *,
               front: Optional[Path] = None) -> Dict[str, Any]:
    """Whether a dressed view kept its view: ``{"ok", "scores": {base view:
    correlation}, "best"}`` — ``ok`` when the dressed head region correlates
    best with the base view of the same name. ``{"ok": True, "skipped":
    <reason>}`` when it cannot be measured (an image without a matte, the
    own base view missing): the guard never blocks what it cannot judge.

    ``front``: the dressed front of the same figure (the view itself for
    the front). When its head differs from the base front's (``head_match``
    below ``HEAD_MATCH_MIN``, Ruling A16 — a bald shape on haired plain
    views) the head likeness is no measure and the face cue judges instead:
    ``{"ok", "cue": "face", "face", "head_match", "best"}`` — a back or side
    view showing a frontal face (``face_found``) faces the camera (``best``
    "front"), one without keeps its view; a front showing a face is a front,
    one without falls back to the head likeness (a front turned away shows
    no face either)."""
    match = head_match(front, base_views.get("front")) if front is not None else None
    if match is not None and match < HEAD_MATCH_MIN:
        face = face_found(dressed)
        if view != "front":
            if face is None:
                return {"ok": True, "skipped": "dressed image without a measurable head region",
                        "cue": "face", "head_match": match}
            return {"ok": not face, "cue": "face", "face": face, "head_match": match,
                    "best": "front" if face else view}
        if face:
            return {"ok": True, "cue": "face", "face": True, "head_match": match, "best": "front"}
    vector = _head_vector(dressed)
    if vector is None:
        return {"ok": True, "skipped": "dressed image without a measurable head region"}
    scores: Dict[str, float] = {}
    for name, path in base_views.items():
        reference = _head_vector(path) if path is not None else None
        if reference is not None:
            scores[name] = round(float(vector @ reference), 4)
    if view not in scores:
        return {"ok": True, "skipped": "base view without a measurable head region"}
    best = max(scores, key=lambda name: scores[name])
    return {"ok": best == view, "scores": scores, "best": best}


def dressed_view_check(view: str, dressed: Path, base_views: Dict[str, Optional[Path]], *,
                       front: Optional[Path] = None) -> Dict[str, Any]:
    """``view_guard`` of a dressed view (``front``: see there) plus its
    ``framing`` record (``base_body_gates.framing_gate`` against the base
    view of the same name, ruling F14 h): ``ok`` only when the view kept its
    view AND its frame."""
    from app.core import base_body_gates
    result = view_guard(view, dressed, base_views, front=front)
    framing = base_body_gates.framing_gate(dressed, base_views.get(view))
    return {**result, "framing": framing, "ok": bool(result["ok"] and framing["ok"])}


def _guard_message(view: str, result: Dict[str, Any]) -> str:
    framing = result.get("framing") or {}
    if not framing.get("ok", True) and (result.get("best") in (None, view)):
        from app.core.base_body_gates import framing_message
        return framing_message(framing, view)
    if not result.get("best"):
        return f"{view} view: the dressed image does not keep its view ({result.get('skipped') or 'unchecked'})"
    if result.get("cue") == "face":
        return f"{view} view: the dressed image does not keep its view (a face is visible — it faces the camera)"
    return (f"{view} view: the dressed image does not keep its view (its head looks most like the "
            f"{result['best']} base view)")


# --- GLB base colour --------------------------------------------------------

_MIME_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}


def _part_materials(gltf: Dict[str, Any]) -> set:
    """Indices of the materials of procedural parts (``attached_part`` /
    ``inset_part`` Blender scripts): marked by the extra ``attached_part`` on
    the material, or used only by meshes whose node carries that extra. Each
    has its own baked texture, which is not the body's base colour."""
    materials = gltf.get("materials") or []
    marked = {index for index, material in enumerate(materials)
              if "attached_part" in ((material or {}).get("extras") or {})}
    part_meshes = {node["mesh"] for node in gltf.get("nodes") or []
                   if "mesh" in node and "attached_part" in (node.get("extras") or {})}
    used_by_part, used_by_body = set(), set()
    for index, mesh in enumerate(gltf.get("meshes") or []):
        for primitive in mesh.get("primitives") or []:
            if isinstance(primitive.get("material"), int):
                (used_by_part if index in part_meshes else used_by_body).add(primitive["material"])
    return marked | (used_by_part - used_by_body)


def _base_color_targets(gltf: Dict[str, Any]) -> Tuple[int, Dict[int, str]]:
    """``(primary, {image index: role})`` of a document's base colour: every
    image a body material's ``baseColorTexture`` resolves to — the preferred
    one (``model_validate.texture_image_index``: an EXT_texture_webp source,
    else the core source) is ``primary`` and must be the same for every body
    material; a WebP texture's core fallback is replaced too (role
    ``core``). A procedural part's material (``_part_materials``) is not the
    body: its baked texture is neither read nor replaced."""
    from app.core.model_validate import texture_image_index
    textures = gltf.get("textures") or []
    primaries, targets = set(), {}
    parts = _part_materials(gltf)
    for index, material in enumerate(gltf.get("materials") or []):
        if index in parts:
            continue
        info = ((material or {}).get("pbrMetallicRoughness") or {}).get("baseColorTexture")
        if not isinstance(info, dict):
            continue
        texture = textures[info["index"]]
        primary = texture_image_index(gltf, texture)
        primaries.add(primary)
        targets[primary] = "webp" if "EXT_texture_webp" in (texture.get("extensions") or {}) else "core"
        if targets[primary] == "webp" and isinstance(texture.get("source"), int):
            targets[texture["source"]] = "core"
    if len(primaries) != 1:
        raise ValueError(f"Expected exactly one base-colour image, found {len(primaries)}")
    return next(iter(primaries)), targets


def base_color_image(glb: bytes) -> Tuple[bytes, str]:
    """``(bytes, mime)`` of a GLB's one base-colour image."""
    from app.core.model_validate import parse_glb
    parsed = parse_glb(glb)
    gltf, binary = parsed["gltf"], parsed["bin"]
    primary, _targets = _base_color_targets(gltf)
    image = gltf["images"][primary]
    view = (gltf.get("bufferViews") or [])[image["bufferView"]] if "bufferView" in image else None
    if view is None or view.get("buffer", 0) != 0:
        raise ValueError("The base-colour image is not embedded in the GLB")
    start = int(view.get("byteOffset", 0))
    return bytes(binary[start:start + int(view["byteLength"])]), image.get("mimeType", "")


def _encode(image: bytes, mime: str, target: str) -> bytes:
    if mime == target:
        return image
    import io
    from PIL import Image
    with Image.open(io.BytesIO(image)) as decoded:
        decoded.load()
        out = io.BytesIO()
        if target == "image/jpeg":
            decoded.convert("RGB").save(out, format="JPEG", quality=95)
        elif target == "image/webp":
            decoded.save(out, format="WEBP", lossless=True, exact=True, quality=100)
        else:
            decoded.save(out, format="PNG")
    return out.getvalue()


def replace_base_color(glb: bytes, image: bytes, mime: str) -> bytes:
    """The GLB with ``image`` as its base colour; nodes, skins, meshes,
    accessors, materials and textures stay as they are.

    The image entries the base colour resolves to get the new bytes: a
    core (PNG/JPEG) source takes ``image`` as given when it is PNG or JPEG
    (its ``mimeType`` follows), a WebP source of EXT_texture_webp gets it
    re-encoded as lossless WebP. The BIN chunk is repacked in bufferView
    order (4-byte aligned) — only the bufferViews' offsets/lengths and the
    buffer length change. ValueError for anything this cannot rewrite
    safely: not exactly one base-colour image, an image outside the BIN
    chunk or sharing its bufferView, a second buffer, a bufferView with
    extensions (meshopt names raw buffer offsets)."""
    import struct
    from app.core.model_validate import parse_glb
    if mime not in _MIME_FORMATS:
        raise ValueError(f"Unsupported base-colour image type: {mime!r}")
    parsed = parse_glb(glb)
    gltf, binary = parsed["gltf"], parsed["bin"]
    _primary, targets = _base_color_targets(gltf)
    images, views = gltf.get("images") or [], gltf.get("bufferViews") or []
    if len(gltf.get("buffers") or []) != 1:
        raise ValueError("Base-colour replacement needs a single-buffer GLB")
    used = {}
    for i, img in enumerate(images):
        if "bufferView" in img:
            used.setdefault(img["bufferView"], []).append(("image", i))
    for i, accessor in enumerate(gltf.get("accessors") or []):
        if "bufferView" in accessor:
            used.setdefault(accessor["bufferView"], []).append(("accessor", i))
    replaced: Dict[int, bytes] = {}
    for index, role in targets.items():
        img = images[index]
        if "bufferView" not in img or "uri" in img:
            raise ValueError("The base-colour image is not embedded in the GLB")
        if used.get(img["bufferView"]) != [("image", index)]:
            raise ValueError("The base-colour image shares its bufferView")
        target = "image/webp" if role == "webp" else (mime if mime != "image/webp" else "image/png")
        replaced[img["bufferView"]] = _encode(image, mime, target)
        img["mimeType"] = target
    packed = bytearray()
    for i, view in enumerate(views):
        if view.get("buffer", 0) != 0 or view.get("extensions"):
            raise ValueError("Base-colour replacement cannot repack this bufferView")
        start, length = int(view.get("byteOffset", 0)), int(view["byteLength"])
        if start < 0 or length < 0 or start + length > len(binary):
            raise ValueError("Invalid bufferView in the GLB")
        raw = replaced.get(i, binary[start:start + length])
        packed.extend(b"\0" * (-len(packed) % 4))
        view["byteOffset"] = len(packed)
        view["byteLength"] = len(raw)
        packed.extend(raw)
    packed.extend(b"\0" * (-len(packed) % 4))
    gltf["buffers"][0]["byteLength"] = len(packed)
    document = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    document += b" " * (-len(document) % 4)
    return (struct.pack("<III", 0x46546C67, 2, 28 + len(document) + len(packed))
            + struct.pack("<I4s", len(document), b"JSON") + document
            + struct.pack("<I4s", len(packed), b"BIN\0") + bytes(packed))


def restore_face_texels(atlas: bytes, atlas_mime: str, base_image: bytes,
                        base_meta: Dict[str, Any]) -> Tuple[bytes, str, Dict[str, Any]]:
    """Put the base model's face back into a retextured outfit atlas.

    The dressed front is an image edit, and the face may drift in it; the
    worker would then paint that drift over the corrected face. Every texel
    of the base's face mask (``face_retexture.baked.face_mask``, the texels
    the face bake replaced) is copied from the base colour ``base_image``
    into ``atlas`` (both decoded as RGBA). Returns ``(bytes, mime, record)``:
    the atlas re-encoded as PNG when a texel changed (else the input
    unchanged) and ``{"face_texels_restored": <texels that differed>,
    "face_mask_texels": <mask size>}`` — or ``{"face_texels_restored": 0,
    "face_texels_skipped": <reason>}`` without a usable mask (no face
    correction, a mask of another size)."""
    import io
    import numpy as np
    from PIL import Image
    from app.core.face_retexture import face_mask_array
    face = (base_meta.get("face_retexture") or {})
    baked = face.get("baked") or {}
    if face.get("status") != "applied" or not baked.get("face_mask"):
        return atlas, atlas_mime, {"face_texels_restored": 0, "face_texels_skipped": "no face mask"}
    with Image.open(io.BytesIO(base_image)) as decoded:
        base_px = np.asarray(decoded.convert("RGBA"))
    with Image.open(io.BytesIO(atlas)) as decoded:
        atlas_px = np.asarray(decoded.convert("RGBA")).copy()
    height, width = base_px.shape[:2]
    mask = face_mask_array(baked, width, height)
    if mask is None or atlas_px.shape != base_px.shape:
        return atlas, atlas_mime, {"face_texels_restored": 0,
                                   "face_texels_skipped": "face mask does not match the atlas size"}
    differs = mask & np.any(atlas_px != base_px, axis=2)
    count = int(differs.sum())
    record = {"face_texels_restored": count, "face_mask_texels": int(mask.sum())}
    if not count:
        return atlas, atlas_mime, record
    atlas_px[mask] = base_px[mask]
    out = io.BytesIO()
    Image.fromarray(atlas_px).save(out, "PNG")
    return out.getvalue(), "image/png", record


# --- The outfit model -------------------------------------------------------

class OutfitError(RuntimeError):
    """A precondition of the outfit model is missing (base model, images)."""


# Base sidecar keys that describe the base run itself, never the outfit
# model copied from it.
_BASE_ONLY_META = ("base", "created_at", "signature", "source", "lod_error", "diagnosis", "measured",
                   "rig_error", "source_image", "source_image_sha256", "view_images",
                   "view_images_sha256", "job_id", "source_filename", "pieces", "items",
                   "mesh_variant", "refined", "retexture_proof", "base_signature",
                   "base_model_sha256", "dressed", "covered_variant", "base_variant",
                   "mesh_token", "mesh_items", "garment_warnings", "texture_signature", "texture_reused")


def _snapshot_base_model(character_name: str, bsig: str) -> Dict[str, Any]:
    """The current base model's files, read under the publication lock of
    the REAL model directory (the outfit run is staged on its own
    signature): rigged GLB + sidecar, the unrigged checkpoint, the clean
    prerig source + sidecar when it exists, and the covered variant
    (``model3d/covered/<bsig>.glb`` + sidecar) when it was built from THAT
    prerig source (``source_sha256``) — else ``covered`` is None."""
    from app.core.keyed_lock import keyed_lock
    from app.core.model3d import _read_sidecar
    from app.models.character import get_character_dir
    directory = get_character_dir(character_name) / "model3d"
    with keyed_lock("model3d_publication", str(directory)):
        rigged = directory / f"{bsig}.glb"
        meta = _read_sidecar(rigged)
        if not rigged.is_file() or not meta.get("base") or meta.get("rig") != "mixamo" or meta.get("rig_error"):
            raise OutfitError(BASE_MODEL_MISSING)
        unrigged = directory / "unrigged" / f"{bsig}.glb"
        if not unrigged.is_file():
            raise OutfitError("Base body model has no unrigged source — regenerate the base model")
        prerig = directory / "prerig" / f"{bsig}.glb"
        prerig_bytes = prerig.read_bytes() if prerig.is_file() else None
        covered_path = directory / "covered" / f"{bsig}.glb"
        covered_meta = _read_sidecar(covered_path) if covered_path.is_file() else {}
        covered = (covered_path.read_bytes() if prerig_bytes is not None and covered_meta.get("source_sha256")
                   == hashlib.sha256(prerig_bytes).hexdigest() else None)
        return {"rigged": rigged.read_bytes(), "meta": meta, "unrigged": unrigged.read_bytes(),
                "prerig": prerig_bytes,
                "prerig_meta": _read_sidecar(prerig) if prerig.is_file() else {},
                "covered": covered, "covered_meta": covered_meta if covered is not None else {}}


def _guard_dressed_views(character_name: str, signature: str, bsig: str,
                         dressed_views: Dict[str, Optional[Path]],
                         registrations: Dict[str, Optional[Path]], *,
                         rerender=None) -> Tuple[Dict[str, Any], list]:
    """Run ``dressed_view_check`` (``view_guard`` + the framing gate) on
    every dressed view of a DRESSED combination (an undressed one is the
    shape's views themselves). A failing view is
    re-rendered ONCE — ``rerender(view) -> path | None`` when given (a
    shape's own views, ``prepare_shape``), else
    ``generate_dressed_images(view=…, force=True)`` with the pieces/items of
    its sidecar and the view that counts then (``dressed_image``, of the
    plain body ``bsig``) — and checked again; still failing, it
    is dropped from ``dressed_views`` (set None) with a warning naming the
    view — except the front, which fails the build (``OutfitError``).
    Returns ``(guard record per view, warnings)``; the record keeps the
    scores of both attempts (``first`` = the replaced image's). A view
    kept with a framing drift above ``FRAMING_WARN`` adds its warning.

    The dressed front of the build (``dressed_views["front"]``) goes with
    every check (``view_guard``'s ``front``: a head that differs from the
    plain views' is judged by the face cue, Ruling A16 a). One retry budget
    per view (Ruling A16 b): a two-step view whose draft loop already
    retried it for the same orientation reason (``orientation_retried``) is
    NOT re-rendered — the stored view is the best of those drafts; it is
    kept (record ``kept``) with a warning naming the attempts."""
    from app.core.model3d import _ref_manifest
    if _ref_sidecar(dressed_views["front"]).get("dressed") is False:
        return {}, []
    record: Dict[str, Any] = {}
    warnings = []
    # The views the build froze (``dressed_views()`` when it started).
    for v in list(dressed_views):
        path = dressed_views.get(v)
        if path is None or registrations.get(v) is None:
            continue
        result = dressed_view_check(v, path, registrations, front=dressed_views.get("front"))
        retried = 0 if result["ok"] else orientation_retried(v, path, result)
        if retried:
            message = (f"{_guard_message(v, result)}; kept — its drafts were already re-tried for this "
                       f"({retried} attempts)")
            logger.warning("Outfit model %s (%s): %s", character_name, signature, message)
            record[v] = {**result, "kept": True, "draft_attempts": retried}
            warnings.append(message)
            continue
        if not result["ok"]:
            logger.warning("Outfit model %s (%s): %s — rendering it once more", character_name, signature,
                           _guard_message(v, result))
            manifest = _ref_manifest(path) or _ref_manifest(dressed_views["front"])
            retry: Dict[str, Any] = {"ok": False, "skipped": "no outfit manifest to re-render from"}
            if rerender is not None:
                try:
                    path = rerender(v)
                except Exception as e:  # noqa: BLE001 — the old verdict stands
                    logger.warning("Dressed %s %s re-render failed: %s", character_name, v, e)
                    path = None
                retry = (dressed_view_check(v, path, registrations) if path is not None
                         else {"ok": False, "skipped": "re-render failed"})
            elif manifest:
                try:
                    generate_dressed_images(character_name, pieces=manifest.get("pieces"),
                                            items=manifest.get("items"), signature=signature,
                                            force=True, view=v)
                except Exception as e:  # noqa: BLE001 — the old verdict stands
                    logger.warning("Dressed %s %s re-render failed: %s", character_name, v, e)
                path = dressed_image(character_name, v, signature, bsig)
                retry = (dressed_view_check(v, path, registrations) if path is not None
                         else {"ok": False, "skipped": "re-render failed"})
            result = {**retry, "rerendered": True, "first": result}
            if not result["ok"] and "best" not in result:
                result["best"] = result["first"].get("best")
        record[v] = result
        if result["ok"]:
            dressed_views[v] = path
            drift = (result.get("framing") or {}).get("warning")
            if drift:
                warnings.append(f"{v} view: {drift}")
            continue
        if v == "front":
            raise OutfitError(_guard_message(v, result))
        warnings.append(_guard_message(v, result) + "; left out of the outfit model")
        dressed_views[v] = None
    return record, warnings


def orientation_retried(view: str, path: Path, result: Dict[str, Any]) -> int:
    """How many draft attempts of the stored two-step view ``path`` failed
    the orientation check (``fit_gate`` sidecar record of ``_dress_view``:
    each attempt's ``guard``) when ``result`` (``dressed_view_check``) fails
    for its orientation too (``best`` names another view) and the draft
    loop already retried it (two attempts or more failed it) — else 0
    (Ruling A16 b: one retry budget per view; a framing failure alone, a
    front, a view without a draft record keep the guard's re-render)."""
    if result.get("best") in (None, view):
        return 0
    attempts = (_ref_sidecar(path).get("fit_gate") or {}).get("attempts") or []
    turned = sum(1 for a in attempts if isinstance(a, dict) and (a.get("guard") or {}).get("ok") is False)
    return turned if turned >= 2 else 0


def _dict_of(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _assemble_garments(character_name: str, signature: str, path: Path, meta: Dict[str, Any]) -> None:
    """The eager assembly of a freshly built outfit model (R11): built INSIDE
    the model's stage, so its publication carries bare file and assembly
    together. A failure never blocks the bare model — it is published with
    the reason in ``garment_warnings`` (and served bare)."""
    from app.core import garment_assembly, model3d
    try:
        result = garment_assembly.assemble(character_name, signature, tiers=(garment_assembly.FULL,))
        warning = "" if result.get("ok") else str(result.get("error") or "Garment assembly failed")
    except Exception as e:  # noqa: BLE001 — the bare model stays published
        warning = f"Garment assembly failed: {e}"
    if warning:
        logger.warning("Outfit model %s (%s): %s", character_name, signature, warning)
        meta["garment_warnings"] = [*(meta.get("garment_warnings") or []), warning]
        model3d._publish_sidecar(path, meta)


def build_outfit_model(character_name: str, signature: str, *, force: bool = False) -> Dict[str, Any]:
    """Build the outfit model ``model3d/<signature>.glb`` of a character on
    the pipeline from the figure delivered NOW (``figure.delivered_figure``
    of the outfit's dressed front manifest; plan 2026-11-12-unified-worn-
    pieces Task 6). Called by ``model3d._generate_for_current_outfit``
    INSTEAD of the img2mesh stages, inside its staging (writes go to the
    stage of ``signature``; the base and the shapes are read from the real
    directory). Blocking; CPU only.

    The figure's SHAPE is the body: the plain body (the rigged base model) or
    a meshed shape (``model3d/<ob…>.glb``, built before this staged run by
    ``prepare_shape`` — missing or not current it fails with
    ``OUTFIT_BODY_MISSING`` / ``OUTFIT_BODY_OUTDATED``). Its TEXTURE is
    painted onto a copy of it — on a meshed shape only with
    ``figure.PAINT_ON_SHAPE`` (the refusal branch paints nothing there); a
    meshed shape with nothing painted (texture ``""``) is copied as it is
    (``_build_on_shape``). Own-mesh pieces and the hair are grafted by the
    assembly; the sidecar records the delivered ``figure``.

    Inputs, frozen when the run starts: the paint source (plain body: the
    rigged base model, the unrigged checkpoint ``model3d/unrigged/<bsig>.glb``,
    the clean prerig source, the covered variant; meshed shape: the same
    files of the shape), the dressed views ``tpose[_<view>]_<signature>``
    made from that shape's views and their registration images
    ``tpose[_<view>]_<shape>`` — only ``dressed_views()`` reach the worker.
    With side views among them the worker also gets the world's
    ``side_arm_margin`` and the rigged source as ``arm_rig_glb``.
    Before the worker runs, every dressed view passes the view guard
    (``_guard_dressed_views``: a turned view is re-rendered once, then left
    out with a warning; a turned front fails the build); the per-view
    record and the warnings go into the sidecar (``view_guard``,
    ``view_warnings``). The worker gets the unrigged geometry carrying the
    rigged source's CURRENT base-colour image (same UV layout) and writes the
    dressed GLB; the source's face texels are put back into its atlas
    (``restore_face_texels``, proof ``face_texels_restored``) and that atlas
    goes into a copy of the model the outfit calls for: on the plain body
    the rigged base or its covered variant ``model3d/covered/<bsig>.glb``
    without the exposed-only extension groups when a worn piece hides them
    (``outfit_variant``; a missing or outdated variant falls back to the
    rigged base with the warning ``COVERED_MISSING``), on a meshed shape the
    rigged shape. Sidecar ``base_variant``. An undressed combination is the
    rigged base copy without a worker run.
    Then the usual post-steps: texture re-encode, the extension rig
    (``model3d._auto_extension_rig`` — the copied state makes it a no-op
    unless this outfit's ``mesh_variant`` declares other groups; then every
    group is rebuilt once from the source's clean prerig WITH ITS BASE
    COLOUR, so colour markers place the bones as on the source, and the
    outfit colour is put back afterwards), measurement, sidecar
    (``base_signature``, ``base_model_sha256`` of the PLAIN body,
    ``retexture_proof``, ``source: "base_body"``, ``figure``; on a meshed
    shape ``body_id`` + ``body_sha256``; the source's ``collision`` capsule
    set is copied with its meta, ``collision.refresh``), distance tier, and
    the eager garment assembly ``model3d/assembled/<signature>.glb``
    (``_assemble_garments``; a failure only adds ``garment_warnings``). The
    dressed front's own-mesh record (``mesh_items``, ``mesh_token``) is
    copied into the sidecar with the manifest — the assembly grafts the
    pieces it left out and the ones it keeps in the body shape until their
    mesh is ready (``garment_assembly._wanted``) — and its warnings (pieces
    in the body until their mesh is ready) open ``garment_warnings``.

    Painted body (plan 2026-11-10-texture-body-reuse, Task 1): everything up
    to the validated retextured GLB is the body of the texture
    (``figure.texture``). The outfit's views and the store's are made one set
    first (``_sync_texture_views``); a current stored body
    (``stored_texture_body``: same base model and paint source, same view
    contents) is reused without guard or worker run — its guard, refit and
    proof records come along — else the body is painted as described and
    stored (``model3d/texture/<tex>.glb``; on a meshed shape with
    ``shape`` + ``shape_sha256``). ``force`` (an explicit regeneration)
    paints the body again even when a current one is stored.

    Errors (worker unavailable/refused, missing base model or images, an
    output that cannot be read) → ``{"ok": False, "error": <message>}``,
    recorded for the outfit status; nothing is written, so the previous
    model of the signature stays."""
    import tempfile
    from app.core import body_retexture, figure as figure_mod, model3d
    from app.core.extension_rig import extension_metadata
    from app.core.model_refs import find_ref_image
    from app.core.task_queue import get_task_queue
    from app.core.timeutils import utc_now_iso
    _outfit_start(character_name, signature, "model")
    error: Optional[str] = None
    refused = False
    fig = None
    task_id = ""
    try:
        try:
            task_id = get_task_queue().track_start(
                "model3d_generation", f"Outfit retexture: {character_name}",
                agent_name=character_name, start_running=True)
        except Exception:  # noqa: BLE001 — tracking is display only
            task_id = ""
        profile = _profile_of(character_name, None)
        if not is_base_pipeline(character_name, profile=profile):
            raise OutfitError("The character is not on the base-body pipeline")
        bsig = base_signature(character_name, profile=profile)
        base = _snapshot_base_model(character_name, bsig)
        if find_ref_image(character_name, _kind("front"), bsig) is None:
            raise OutfitError(BASE_IMAGES_MISSING)
        front_now = dressed_image(character_name, "front", signature, bsig)
        if front_now is None:
            raise OutfitError(DRESSED_IMAGES_MISSING)
        first = model3d._ref_manifest(front_now)
        pieces, items = dict(first.get("pieces") or {}), list(first.get("items") or [])
        fig = figure_mod.delivered_figure(character_name, profile=profile, pieces=pieces, items=items)
        if fig.fit_refused:
            # Ruling A23 a: a wanted piece's fit on the body shape is refused — nothing lacking it is published.
            from app.models.inventory import get_item
            from app.core.fit_attempts import strip_prefix
            raise OutfitError(FIT_REFUSED_NOT_PUBLISHED.format(items=", ".join(
                f"{(get_item(i) or {}).get('name') or i} ({strip_prefix(r)})"
                for i, r in sorted(fig.fit_refused.items()))))
        on = fig.shape
        meshed = not figure_mod.is_plain(on)
        registrations = {v: find_ref_image(character_name, _kind(v), on) for v in BASE_VIEWS}
        if registrations["front"] is None:
            raise OutfitError(SHAPE_VIEWS_MISSING if meshed else BASE_IMAGES_MISSING)
        mesh_profile = _worn_profile(profile, pieces, items)
        wanted_variant = figure_mod.predicted_variant(
            character_name, figure_mod.worn_sets(character_name, pieces=pieces, profile=profile), items,
            profile=profile)
        texts = figure_texts(character_name, fig, items, profile=profile)
        tsig = fig.texture
        # Ruling A50: on a meshed shape the FIGURE says whether anything is painted (its texture key), never a
        # stored view — a figure with no texture needs is the shape itself and asks the texture store nothing.
        dressed_now = (bool(tsig) if meshed else _ref_sidecar(front_now).get("dressed") is not False)
        if meshed:
            source = _snapshot_shape(character_name, on, bsig)
            if dressed_now and source["unrigged"] is None:
                raise OutfitError("Outfit body has no unrigged source — regenerate the outfit body")
        else:
            source = base
        if dressed_now:
            _sync_texture_views(character_name, signature=signature, tsig=tsig, fig=fig,
                                base_views=registrations, texts=texts, manifest=first, profile=mesh_profile)
        if meshed and not dressed_now:
            # Nothing painted on the shape: the outfit model IS the shape.
            return _build_on_shape(character_name, signature, fig=fig, base=base, shape=source,
                                   variant=wanted_variant, profile=profile)
        if meshed:
            inputs: Dict[str, Any] = {"shape": on, "dress_text": texts, "figure": fig.as_dict()}
        else:
            inputs = texture_inputs(character_name, pieces=pieces, items=items, variant=wanted_variant,
                                    mesh_effective=sorted({*fig.own, *fig.left_out}), bsig=bsig,
                                    profile=mesh_profile)
        view_shas = texture_view_shas(character_name, signature, bsig, fig=fig)
        stored = None if force else stored_texture_body(character_name, tsig, base=source, view_shas=view_shas)
        if stored is not None:
            # Reused: the views are the body's (same content), so are its
            # view guard and proof; no worker run.
            outfit, body = stored
            front_path = dressed_image(character_name, "front", signature, bsig, fig=fig)
            front_meta = _ref_sidecar(front_path)
            manifest = model3d._ref_manifest(front_path)
            names = {}
            for v in body.get("used_views") or ["front"]:
                used = dressed_image(character_name, v, signature, bsig, fig=fig) if v in BASE_VIEWS else None
                if used is not None:
                    names[v] = used.name
            if "front" not in names:
                raise OutfitError(DRESSED_IMAGES_MISSING)
            guard = _dict_of(body.get("view_guard"))
            warnings = [w for w in body.get("view_warnings") or [] if isinstance(w, str)]
            variant = str(body.get("base_variant") or "rigged")
            proof = body.get("retexture_proof")
            source_state = body.get("source_state")
            source_blender = body.get("source_blender")
            logger.info("Outfit model %s (%s): painted body %s reused", character_name, signature, tsig)
        else:
            dressed_paths = {v: dressed_image(character_name, v, signature, bsig, fig=fig) for v in dressed_views()}
            if dressed_paths["front"] is None:
                raise OutfitError(DRESSED_IMAGES_MISSING)
            guard, warnings = _guard_dressed_views(
                character_name, signature, bsig, dressed_paths, registrations,
                rerender=lambda v: (generate_dressed_images(character_name, pieces=pieces, items=items,
                                                            signature=signature, force=True, view=v),
                                    dressed_image(character_name, v, signature, bsig, fig=fig))[1])
            with tempfile.TemporaryDirectory(prefix="body-retexture-") as tmp:
                work = Path(tmp)
                views: Dict[str, Tuple[Path, Path]] = {}
                front_meta: Dict[str, Any] = {}
                manifest: Dict[str, Any] = {}
                names: Dict[str, str] = {}
                # Only the dressed views go to the worker (dressed_views()); the
                # other registrations scored the view guard above.
                for v in dressed_paths:
                    dressed = dressed_paths[v]
                    registration = registrations[v]
                    if v == "front" and dressed is None:
                        raise OutfitError(DRESSED_IMAGES_MISSING)
                    if dressed is None or registration is None:
                        continue
                    # Frozen copies: a re-render while the worker runs must not
                    # change its input.
                    frozen = (work / f"dressed_{v}{dressed.suffix}", work / f"registration_{v}{registration.suffix}")
                    frozen[0].write_bytes(dressed.read_bytes())
                    frozen[1].write_bytes(registration.read_bytes())
                    views[v] = frozen
                    names[v] = dressed.name
                    if v == "front":
                        front_meta = _ref_sidecar(dressed)
                        manifest = model3d._ref_manifest(dressed)
                proof: Optional[Dict[str, Any]] = None
                # The model this outfit is painted onto: on the plain body the
                # covered variant when a worn piece hides the exposed-only
                # extension groups (an undressed copy of pieces that are all
                # own meshes too: the garment meshes cover the body like
                # painted pieces would); on a meshed shape the shape itself.
                variant = "rigged" if meshed else wanted_variant
                source_model, source_state, source_blender = source["rigged"], None, None
                if variant == "covered" and not meshed:
                    if base["covered"] is not None:
                        source_model = base["covered"]
                        source_state = base["covered_meta"].get("extension_rig")
                        source_blender = base["covered_meta"].get("blender")
                    else:
                        variant = "rigged"
                        warnings = [*warnings, COVERED_MISSING]
                        logger.warning("Outfit model %s (%s): %s", character_name, signature, COVERED_MISSING)
                outfit = source_model
                if front_meta.get("dressed") is not False:
                    image, mime = base_color_image(source["rigged"])
                    worker_in = work / "base_in.glb"
                    worker_in.write_bytes(replace_base_color(source["unrigged"], image, mime))
                    side: Dict[str, Any] = {}
                    if any(v in views for v in SIDE_DRESSED_VIEWS):
                        arm_rig = work / "arm_rig.glb"
                        arm_rig.write_bytes(source["rigged"])
                        side = {"side_arm_margin": side_arm_margin(), "arm_rig_glb": arm_rig}

                    out_glb = work / "dressed.glb"
                    proof = body_retexture.retexture(worker_in, views, out_glb, proof=work / "proof.json",
                                                     atlas=work / "atlas.png", **side)
                    if not out_glb.is_file():
                        raise OutfitError("Body retexture worker wrote no GLB")
                    atlas, atlas_mime = base_color_image(out_glb.read_bytes())
                    atlas, atlas_mime, restored = restore_face_texels(atlas, atlas_mime, image, source["meta"])
                    proof = {**(proof or {}), **restored}
                    outfit = replace_base_color(source_model, atlas, atlas_mime)
                verdict = model3d._validator_for("mixamo", character_name)(outfit)
                if not verdict.get("ok"):
                    raise OutfitError("Retextured model is invalid: " + "; ".join(verdict.get("errors") or []))
            if front_meta.get("dressed") is not False:
                # The guard may have rendered a view again.
                _store_texture_views(character_name, signature, tsig,
                                     [v for v in dressed_views()
                                      if dressed_image(character_name, v, signature, bsig, fig=fig)], texts)
            record = {
                "texture_signature": tsig, "texture_inputs": inputs, "created_at": utc_now_iso(),
                "character": character_name, "built_for": signature, "base_signature": bsig,
                "base_model_sha256": hashlib.sha256(source["rigged"]).hexdigest(),
                "source_model_sha256": _source_sha(source, variant), "base_variant": variant,
                "covered_missing": COVERED_MISSING in warnings, "dressed": front_meta.get("dressed") is not False,
                "views": texture_view_shas(character_name, signature, bsig, fig=fig),
                "used_views": [v for v in BASE_VIEWS if v in names], "retexture_proof": proof,
                "view_guard": guard, "view_warnings": warnings,
                "source_state": deepcopy(source_state), "source_blender": deepcopy(source_blender),
                "body_sha256": hashlib.sha256(outfit).hexdigest()}
            if meshed:
                record.update(shape=on, shape_sha256=hashlib.sha256(source["rigged"]).hexdigest())
            _store_texture_body(character_name, tsig, outfit, record)
        out_dir = model3d.get_model3d_dir(character_name)
        path = out_dir / f"{signature}.glb"
        meta = {k: v for k, v in deepcopy(source["meta"]).items()
                if k not in _BASE_ONLY_META and k != "outfit_body"}
        if source_state is not None:
            # The covered variant's own extension state (and the Blender
            # record of its file): with it the extension rig below is a no-op.
            meta["extension_rig"] = deepcopy(source_state)
            meta["blender"] = deepcopy(source_blender or meta.get("blender") or {})
        meta.update({"created_at": utc_now_iso(), "source": "base_body", "signature": signature,
                     "base_variant": wanted_variant if meshed else variant,
                     "covered_missing": COVERED_MISSING in warnings,
                     "character": character_name, "format": "glb", "rig": "mixamo",
                     "base_signature": bsig,
                     "base_model_sha256": hashlib.sha256(base["rigged"]).hexdigest(),
                     "retexture_proof": proof,
                     "dressed": True if meshed else front_meta.get("dressed") is not False,
                     "source_image": names["front"],
                     "view_images": {v: n for v, n in names.items() if v != "front"},
                     "view_guard": guard, "view_warnings": warnings,
                     "texture_signature": tsig, "texture_reused": stored is not None})
        if meshed:
            meta.update(body_id=on, body_sha256=hashlib.sha256(source["rigged"]).hexdigest())
        meta.update(manifest)
        meta["figure"] = fig.as_dict()
        # Own-mesh pieces in the body until their mesh is ready: the assembly's own warning, if
        # any, follows.
        mesh_warnings = [w for w in (_dict_of(manifest.get("mesh_items")).get("warnings") or [])
                         if isinstance(w, str) and w]
        if meshed:
            # Ruling A23 a: fitted onto the shape BEFORE anything is published — a grafted piece refused there
            # raises, the model built before stays.
            not_fitted = _refuse_partial(character_name, fig, meta, profile)
            if not_fitted:
                mesh_warnings.append(not_fitted)
        if mesh_warnings:
            meta["garment_warnings"] = mesh_warnings
        model3d._purge_combination(out_dir, signature, keep_model=path)
        model3d._publish_model_bytes(path, outfit)
        model3d._auto_retexture(character_name, path, meta)
        colour = base_color_image(path.read_bytes())
        prerig = out_dir / "prerig" / path.name
        if source["prerig"] is not None:
            # The extension rig (only when the copied state is not current,
            # e.g. parts declared for this outfit) runs on the SOURCE's clean
            # prerig with its base colour, so colour markers hidden by the
            # painted outfit still place the bones exactly as on the source —
            # never a geometry fallback under clothing; the outfit colour
            # goes back on afterwards.
            prerig.parent.mkdir(parents=True, exist_ok=True)
            model3d._publish_model_bytes(prerig, source["prerig"])
            model3d._publish_sidecar(prerig, {k: v for k, v in source["prerig_meta"].items() if k != "outfit_body"})
        model3d._auto_extension_rig(character_name, path, meta)
        if base_color_image(path.read_bytes()) != colour:
            model3d._publish_model_bytes(path, replace_base_color(path.read_bytes(), *colour))
        if source["prerig"] is not None:
            # The clean source then carries the same texture as the model.
            clean = source["prerig"]
            if base_color_image(clean) != colour:
                clean = replace_base_color(clean, *colour)
            model3d._publish_model_bytes(prerig, clean)
        model3d._attach_measurement(meta, path)
        meta.setdefault("extension_rig", extension_metadata(character_name, signature=path.stem))
        model3d._publish_sidecar(path, meta)
        model3d.request_lod(character_name, path)
        _assemble_garments(character_name, signature, path, meta)
        logger.info("Outfit model %s (%s on %s, texture %s): %s", character_name, signature, on, tsig or "-",
                    "retextured" if proof is not None else "undressed copy")
        return {"ok": True, "cached": False, "path": str(path), "filename": path.name, "proof": proof,
                **({"body_id": on} if meshed else {})}
    except (OutfitError, body_retexture.RetextureUnavailable, body_retexture.RetextureFailed,
            ValueError) as e:
        error = str(e) or type(e).__name__
        logger.warning("Outfit model %s (%s) failed: %s", character_name, signature, error)
        # Ruling A61: a refusal that the same inputs would repeat — not a worker that is missing or ran out of time.
        refused = not isinstance(e, body_retexture.RetextureUnavailable) and not error.startswith(
            body_retexture.TIMED_OUT)
        view = registration_refusal_view(error) if isinstance(e, body_retexture.RetextureFailed) else ""
        if view and fig is not None:
            record_mesh_mismatch(character_name, fig.shape, view, error)
        return {"ok": False, "error": error}
    except Exception as e:
        error = str(e) or type(e).__name__
        raise
    finally:
        _outfit_end(character_name, signature, "model", error, refused=refused)
        if task_id:
            try:
                get_task_queue().track_finish(task_id, error=error or "")
            except Exception:  # noqa: BLE001
                pass


# --- Meshed shapes (outfit bodies; plan 2026-11-10-outfit-body-mesh-mode,
# since plan 2026-11-12-unified-worn-pieces Task 6 the shape of a figure) ----
#
# A figure whose worn pieces include ``in_body`` pieces (item mode) stands on
# a MESHED SHAPE (``figure.Figure.shape`` = ``"ob…"``) instead of the plain
# body: its own views — edits of the plain body's views wearing the in-body
# pieces ONLY (``figure.shape_inputs`` dress text) — meshed and rigged
# through the staged chain of the old whole-body path
# (``model3d.generate_for_current_outfit`` with ``outfit_body=…``: img2mesh
# via the character's mesh occasion → face cleanup (per-character switch)
# → face retexture before the rig when the character has it on → rig via the
# ``rig_humanoid`` chain → texture re-encode → normalize (posture restore from
# the retained unrigged source) → extension rig (no part batches) → collision
# capsules). Routing per step as on the old path,
# per-character overrides included.
#
# Body id = SHAPE KEY (``figure.shape_key_of`` over ``figure.shape_inputs``):
# the fit key of an own-mesh garment on that body (``garments.body_fit``).
# Same inputs → same body, no hub job. The painted pieces worn with it are
# painted ONTO the shape (``figure.PAINT_ON_SHAPE``, ``build_outfit_model``);
# the refusal branch meshes them into it instead (``figure._refused_sets``).
# Until the shape is stored the figure is delivered on the plain body with
# the in-body pieces painted meanwhile (interim rule, ``figure._delivered``).
#
# Storage: the body is a model signature of its own in the character's model
# store, laid out like the base body (``base<8hex>``) so every signature-keyed
# step of the old path (staging, publication, re-rig, face retexture, LOD
# skip, purge) applies unchanged:
#   model_refs/tpose[_<view>]_<body id>.*        the mesher inputs: the
#                                                 shape's own views (edits
#                                                 of the plain body's views)
#   model3d/<body id>.glb + .json                 the rigged body
#   model3d/unrigged/<body id>.glb + .json        retained source (re-rig,
#                                                 posture restore, paint
#                                                 source of its textures)
#   model3d/prerig|raw|facefix|rollback/<body id>.*  the chain's usual files
# PARENT RECORD: every one of these sidecars carries ``outfit_body`` =
# ``{body_id, shape_key (== body_id), version (figure.SHAPE_VERSION),
# shape_inputs, base_signature, base_variant, built_for, views, used_views,
# view_guard, view_warnings}`` (``views``: the content sha256 of every view
# the body was meshed from — its freshness, ``shape_view_shas`` /
# ``figure.stored_shape``); an outfit model on a shape names ``body_id``,
# ``body_sha256`` and its ``figure``. The reachability GC walks these. The
# own-mesh garments and the hair on a body are fitted per body
# (``garments.body_fit``: ``garments/bodies/<body id>/``).

OUTFIT_BODY_RE = re.compile(r"ob[0-9a-f]{8}")
OUTFIT_BODY_MISSING = "Outfit body missing — rebuild the outfit model"
OUTFIT_BODY_OUTDATED = "The outfit body does not match its views — rebuild the outfit model"
#: An outfit body is meshed from EVERY view (``dressed_views()``) or not at
#: all (ruling 2026-11-10) — a missing view is rendered first in the same
#: run; one that cannot be rendered stops the build.
VIEWS_MISSING = "{views} {noun} missing — not meshed from the {have} alone"
#: ``VIEWS_MISSING`` when no view of the set is there at all.
VIEWS_NONE = "{views} {noun} missing — nothing to mesh from"
#: Ruling A26 c: a dressed view that IS stored but was edited from base view content replaced since (the skin
#: step rewrote the base front while the dressed front rendered) — stale, never "missing".
VIEWS_STALE = "Dressed {views} {verb} stale — the base {views} changed"
#: The figure a shape was asked for is not the one its pieces call for now.
SHAPE_CHANGED = "The worn pieces changed — the body shape was not built"
#: The in-body pieces of a shape name no text to edit the views with.
SHAPE_EMPTY = "The pieces in the body name nothing to dress the body shape with"
#: ``prepare_shape`` stopped before the mesh: the caller's ``model3d.shape_guard`` says the shape is no longer
#: wanted (Ruling A18) — no failure, nothing recorded.
SHAPE_NOT_WANTED = "Not meshed: the body shape {shape} is no longer wanted — the follow-up builds the one wanted now"
OUTFIT_BODY_CHANGED = "Built on an older body shape"
#: An outfit model built as another figure than the one delivered now.
FIGURE_CHANGED = "Built for another figure"
NOT_FITTED_ON_BODY = "Not fitted on this outfit body, served without: {items}"
#: Ruling A23 a (T15-F1): an outfit model is never published lacking a piece its figure grafts whose fit on the
#: body shape was refused — the model built before stays served (and stays the delivered figure, ``figure``).
FIT_REFUSED_NOT_PUBLISHED = ("Not published: {items} fit the plain body but not the body shape. The figure built "
                             "before stays shown.")


def _refuse_partial(character_name: str, fig, meta: Dict[str, Any], profile: Optional[Dict[str, Any]]) -> str:
    """Before an outfit model on a meshed shape is published: fit every garment it carries onto the shape
    (``garment_assembly.body_fit_left_off``, CPU) and raise ``OutfitError(FIT_REFUSED_NOT_PUBLISHED)`` when a
    piece the figure ``fig`` grafts (its own-mesh pieces, its HairDeck hair) was left off (Ruling A23 a);
    else the ``NOT_FITTED_ON_BODY`` warning of the others left off ("" when none)."""
    from app.core import figure as figure_mod
    from app.core.garment_assembly import body_fit_left_off
    from app.models.inventory import get_item
    left_off = body_fit_left_off(character_name, meta, profile=profile)
    grafted = set(fig.own)
    if fig.hair == figure_mod.HAIR_HAIRDECK:
        from app.core.garment_hair import worn_hair_id
        hair_id = worn_hair_id(character_name, _profile_of(character_name, profile))
        if hair_id:
            grafted.add(hair_id)
    missing = sorted(set(left_off) & grafted)
    if missing:
        from app.core.fit_attempts import strip_prefix
        names = [f"{(get_item(i) or {}).get('name') or i} ({strip_prefix(left_off[i])})" for i in missing]
        logger.warning("Outfit model %s on %s not published: %s", character_name, fig.shape, "; ".join(names))
        raise OutfitError(FIT_REFUSED_NOT_PUBLISHED.format(items=", ".join(names)))
    if not left_off:
        return ""
    names = [f"{(get_item(i) or {}).get('name') or i} ({reason})" for i, reason in sorted(left_off.items())]
    return NOT_FITTED_ON_BODY.format(items=", ".join(names))


def is_outfit_body_signature(value: Optional[str]) -> bool:
    return bool(value) and OUTFIT_BODY_RE.fullmatch(str(value)) is not None


def outfit_body_path(character_name: str, body_id: str) -> Path:
    """``model3d/<body id>.glb`` of the REAL model directory."""
    from app.models.character import get_character_dir
    if not is_outfit_body_signature(body_id):
        raise ValueError(f"not an outfit body id: {body_id!r}")
    return get_character_dir(character_name) / "model3d" / f"{body_id}.glb"


def _outfit_manifest(character_name: str, signature: str) -> Dict[str, Any]:
    """``{pieces, items, piece_state}`` of the outfit ``signature``: the worn
    state when it is the worn combination, else what its stored T-pose /
    model records (``model3d._stored_manifest``; ``piece_state`` ``{}`` when
    it records none = all closed); ``{}`` when nothing knows."""
    from app.core import model3d
    from app.core.model_refs import current_outfit_state, live_piece_state
    pieces, items, worn = current_outfit_state(character_name)
    if worn and worn == signature:
        return {"pieces": dict(pieces or {}), "items": list(items or []),
                "piece_state": live_piece_state(character_name, dict(pieces or {}))}
    return dict(model3d._stored_manifest(character_name, signature) or {})


def front_texture_signature(character_name: str, signature: str, *, bsig: str,
                            profile: Optional[Dict[str, Any]] = None) -> str:
    """The texture (``tex…``) the outfit's model is painted with from its
    stored dressed front while that front is current for the figure
    delivered now (``dressed_image``): that figure's texture — "" otherwise
    (none stored, made for another figure, nothing painted). Read-only."""
    from app.core import figure, model3d
    from app.core.model_refs import find_ref_image
    front = find_ref_image(character_name, _kind("front"), signature)
    if front is None:
        return ""
    manifest = model3d._ref_manifest(front)
    fig = figure.delivered_figure(character_name, profile=_profile_of(character_name, profile),
                                  pieces=dict(manifest.get("pieces") or {}), items=list(manifest.get("items") or []),
                                  piece_state=dict(manifest.get("piece_state") or {}))
    if dressed_image(character_name, "front", signature, bsig, fig=fig) is None:
        return ""
    return fig.texture if is_texture_signature(fig.texture) else ""


def outfit_body_of_outfit(character_name: str, signature: str, *,
                          profile: Optional[Dict[str, Any]] = None) -> str:
    """The meshed shape the outfit ``signature`` WANTS now
    (``figure.wanted_figure`` of its pieces) — "" when it stands on the plain
    body, nothing records its pieces, or on any error. Read-only; the Outfit
    body tab asks it to find an outfit to regenerate a body from."""
    try:
        from app.core import figure
        manifest = _outfit_manifest(character_name, signature)
        if not manifest:
            return ""
        fig = figure.wanted_figure(character_name, profile=_profile_of(character_name, profile),
                                   pieces=dict(manifest.get("pieces") or {}),
                                   items=list(manifest.get("items") or []),
                                   piece_state=dict(manifest.get("piece_state") or {}))
        return "" if figure.is_plain(fig.shape) else fig.shape
    except Exception:  # noqa: BLE001 — a lookup, never a failure
        logger.debug("Outfit body of %s / %s not computable", character_name, signature, exc_info=True)
        return ""


def figure_stale(character_name: str, meta: Dict[str, Any], *,
                 profile: Optional[Dict[str, Any]] = None) -> str:
    """Why an outfit model on the pipeline is not current for the figure
    delivered NOW (Ruling 4a — the mesh-input signature stays mode-blind, the
    model's recorded ``figure`` decides): ``"figure"`` (built as another
    shape or texture than ``figure.delivered_figure`` of its pieces now — a
    mode changed, a shape or an own mesh was built since, or it records no
    figure: built before the figure), ``"outfit_body"`` (its meshed shape
    was rebuilt or is gone — ``body_sha256``), else ``""``. A model from
    before the pipeline is judged elsewhere."""
    from app.core import figure
    if not meta.get("base_signature"):
        return ""
    built = figure.built_figure(meta)
    if built is None:
        return "figure"
    now = figure.delivered_figure_cached(character_name, profile=profile, pieces=dict(meta.get("pieces") or {}),
                                         items=list(meta.get("items") or []),
                                         piece_state={i: "open" for i in built.open})
    if (built.shape, built.texture) != (now.shape, now.texture):
        return "figure"
    if not figure.is_plain(built.shape) and (
            not is_outfit_body_signature(meta.get("body_id"))
            or file_sha256(outfit_body_path(character_name, built.shape)) != meta.get("body_sha256")):
        return "outfit_body"
    return ""


def _join_views(views: Iterable[str]) -> str:
    """``front``, ``front and back``, ``back, left and right``."""
    views = list(views)
    return views[0] if len(views) == 1 else ", ".join(views[:-1]) + " and " + views[-1]


def stale_views(character_name: str, signature: str, views: Iterable[str]) -> List[str]:
    """Of ``views``, the dressed views stored for ``signature`` (an outfit or a meshed shape) that were edited
    from base view content that is not there any more (Ruling A26 c): the sidecar's ``base_image_sha256`` is
    not the content of the view it names (``base_signature``) now — stale, not missing. A model fit of before
    Task 11g is outdated by rule, never "stale" here. Read-only."""
    from app.core.model_refs import find_ref_image
    out: List[str] = []
    for v in views:
        path = find_ref_image(character_name, _kind(v), signature)
        if path is None:
            continue
        meta = _ref_sidecar(path)
        on = str(meta.get("base_signature") or "")
        recorded = str(meta.get("base_image_sha256") or "")
        if is_model_fit(meta) or not on or not recorded:
            continue
        if recorded != file_sha256(find_ref_image(character_name, _kind(v), on)):
            out.append(v)
    return out


def views_missing_message(missing: List[str], have: List[str], reason: str = "", *,
                          stale: Iterable[str] = ()) -> str:
    """``VIEWS_MISSING`` for the views a shape still lacks, ``reason`` (the
    render's error) appended in brackets. A view of ``missing`` that is
    in ``stale`` (``stale_views``: stored, but edited from a base view replaced
    since) is named stale instead (``VIEWS_STALE``, Ruling A26 c); with no view
    there at all the text says so (``VIEWS_NONE``)."""
    stale = set(stale)
    old = [v for v in missing if v in stale]
    gone = [v for v in missing if v not in stale]
    parts: List[str] = []
    if old:
        label = _join_views(old)
        parts.append(VIEWS_STALE.format(views=label, verb="is" if len(old) == 1 else "are"))
    if gone:
        label = _join_views(gone)
        noun = "view" if len(gone) == 1 else "views"
        if have:
            parts.append(VIEWS_MISSING.format(views=label, noun=noun, have=_join_views(have)))
        elif old:
            parts.append(f"{label} {noun} missing")
        else:
            parts.append(VIEWS_NONE.format(views=label, noun=noun))
    text = "; ".join(parts)
    text = text[:1].upper() + text[1:]
    return f"{text} ({reason})" if reason else text


def outfit_body_op_partial(inputs: Dict[str, Any]) -> str:
    """Why the frozen inputs of a ``character_mesh`` hub operation of an
    OUTFIT BODY (manifest ``outfit_body``) are not what a fresh build would
    send — the views it sends (``front`` + ``view_images``) lack one of
    ``dressed_views()`` (a body meshed before the ruling from the front
    alone) — or "". The resume drops such an operation instead of
    submitting it again."""
    manifest = inputs.get("manifest") if isinstance(inputs.get("manifest"), dict) else {}
    if "outfit_body" not in manifest:
        return ""
    extra = inputs.get("view_images") if isinstance(inputs.get("view_images"), dict) else {}
    sent = ["front", *[v for v in BASE_VIEWS if v != "front" and v in extra]]
    missing = [v for v in dressed_views() if v not in sent]
    if not missing:
        return ""
    return views_missing_message(missing, sent) + " — its mesh job from before the restart was dropped"


def shape_view(character_name: str, view: str, shape: str, bsig: str) -> Optional[Path]:
    """The stored view of the shape that is current for the plain body
    ``bsig`` (``shape_view_shas``) and — the shape is meshed from it — not a
    composite of older rules (``composite_outdated``, Ruling A24: re-composited
    from its stored draft first), else None."""
    from app.core.model_refs import find_ref_image
    if not shape_view_shas(character_name, shape, bsig).get(view):
        return None
    path = find_ref_image(character_name, _kind(view), shape)
    return None if path is None or composite_outdated(_ref_sidecar(path)) else path


def shape_view_jobs(character_name: str, shape: str, bsig: str) -> int:
    """Hub jobs of refreshing the views of the meshed shape ``shape`` on the
    plain body ``bsig`` before it is meshed (Ruling C4; ``prepare_shape``
    renders what ``shape_view`` misses): 0 when every ``dressed_views()``
    view is current; a missing front = the whole set
    (``dressed_view_jobs`` — the others are drafted from the new front);
    else 1 per missing back/side, 0 when its stored draft follows the stored
    front (``stored_draft``, Ruling C2: composited again on the CPU). First
    attempts only. Read-only."""
    from app.core.model_refs import find_ref_image
    missing = [v for v in dressed_views() if shape_view(character_name, v, shape, bsig) is None]
    if not missing:
        return 0
    if "front" in missing:
        return dressed_view_jobs()
    front = find_ref_image(character_name, "tpose", shape)
    # Ruling FR-I3: a view whose composite was refused for these inputs is drafted anew on its retry (1 job).
    refused = shape_view_refusals(character_name, shape, bsig)
    return sum(0 if v not in refused and stored_draft(character_name, v, shape, front) is not None else 1
               for v in missing)


def render_shape_views(character_name: str, fig, views: List[str], *, items: Optional[list] = None,
                       force: bool = True) -> Dict[str, Any]:
    """Render ``views`` of the meshed shape of the WANTED figure ``fig``
    (``model_refs/tpose[_<view>]_<shape>``): edits of the plain body's views
    wearing ``fig.in_body`` only (``figure.shape_inputs`` dress text, the
    bald head under an own hair mesh). Image jobs only, never the mesh; a
    view current for the plain body is kept unless ``force``. ``{ok,
    error}`` — ``SHAPE_CHANGED`` when the pieces call for another shape
    now, ``SHAPE_EMPTY`` / ``BASE_IMAGES_MISSING`` when there is nothing to
    edit, else the render's error for a view still missing (then also
    ``missing`` — the views still missing — and ``reason``, the recorded
    failure or "")."""
    from app.core import figure as figure_mod
    from app.core.model_refs import find_ref_image
    profile = _profile_of(character_name, None)
    shape, bsig = fig.shape, fig.bsig
    sets, _variant, inputs = figure_mod.shape_plan(character_name, fig, items, profile=profile)
    if inputs is None or figure_mod.shape_key_of(inputs) != shape:
        return {"ok": False, "error": SHAPE_CHANGED}
    registrations = {v: find_ref_image(character_name, _kind(v), bsig) for v in BASE_VIEWS}
    if registrations["front"] is None or any(registrations.get(v) is None for v in views):
        return {"ok": False, "error": BASE_IMAGES_MISSING}
    texts = dict(inputs["dress_text"])
    hair = str(inputs.get("hair") or "")   # the worn hairstyle's own shape (D4): its hair goes on
    if not texts.get("front") and not hair:
        return {"ok": False, "error": SHAPE_EMPTY}
    todo = [v for v in views if force or shape_view(character_name, v, shape, bsig) is None]
    if todo:
        _render_views(character_name, signature=shape, pieces=sets.pieces, items=[], todo=todo, force=force,
                      on=bsig, registrations=registrations, texts=texts, tsig="", mesh={}, dressed=True,
                      bald=_bald_edit(character_name, profile, meshed=True),
                      profile=_worn_profile(profile, sets.pieces, []), raise_load=False,
                      current=lambda v: shape_view(character_name, v, shape, bsig),
                      hair=hair or None, hair_edit=bool(hair))
    missing = [v for v in views if shape_view(character_name, v, shape, bsig) is None]
    if not missing:
        return {"ok": True, "error": ""}
    with _status_lock:
        failure = dict(_outfit_failed.get((character_name, shape)) or {})
    reason = str(failure.get("error") or "")
    stale = stale_views(character_name, shape, missing)
    if reason == DRESSED_FRONT_STALE and "front" in stale:
        reason = ""   # the message names the stale front itself
    return {"ok": False, "error": reason or views_missing_message(missing, [v for v in views if v not in missing],
                                                                  stale=stale),
            "missing": missing, "reason": reason, "stale": stale}


def _mark_shape_views(character_name: str, shape: str, parent: Dict[str, Any]) -> None:
    """The parent record into every stored view of the shape; the outfit
    keys of the render go (the views are the shape's, not an outfit's)."""
    from app.core.model_refs import find_ref_image
    for v in BASE_VIEWS:
        path = find_ref_image(character_name, _kind(v), shape)
        if path is None:
            continue
        meta = {k: val for k, val in _ref_sidecar(path).items() if k not in _OUTFIT_VIEW_KEYS}
        meta["outfit_body"] = parent
        _atomic_write(path.with_suffix(".json"), json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))


def prepare_shape(character_name: str, fig, *, items: Optional[list] = None, rebuild: bool = False,
                  signature: str = "") -> Optional[Dict[str, Any]]:
    """Make sure the meshed shape of the figure ``fig`` (``figure.
    wanted_figure`` of the outfit ``signature`` and its held ``items``) is
    stored BEFORE the outfit's views and model are made — called by
    ``model3d.generate_for_current_outfit`` outside any model stage (the
    shape is a publication of its own; ``build_outfit_model`` copies it or
    paints on it).

    None when there is nothing to do: off the pipeline, or the figure stands
    on the plain body. Otherwise, serial per (character, shape)
    (``keyed_lock("outfit_body", …)``): a current stored shape
    (``figure.stored_shape`` of its views) is reused — ``{ok, cached: True,
    body_id}``, no job (a shape from before the posture match gets its
    base's posture first, CPU only); ``rebuild`` (an explicit body
    regeneration) meshes it again. Else EVERY view of ``dressed_views()``
    must exist for it (ruling 2026-11-10 — never meshed from a partial set):
    a missing one is rendered first — an edit of the plain body's view
    wearing ``fig.in_body`` only (``figure.shape_inputs`` dress text; the
    bald head under an own hair mesh, ``_bald_edit``); one that still misses
    stops here with ``VIEWS_MISSING`` — ``{ok: False, error, body_id}``, no
    mesh job. The views pass the view guard (a turned view is re-rendered
    once; still turned, it stops the build; a turned front fails), carry
    the parent record (``_mark_shape_views``) and the staged chain runs on
    the body id (``generate_for_current_outfit(signature=<body id>,
    force=True, outfit_body=…)``). The outfit's status counts as running
    meanwhile (stage ``body``); a failure is recorded for the outfit and
    returned ``{ok: False, error, body_id}``.

    Ruling A18: a caller that registered ``model3d.shape_guard`` for the
    shape is asked before the mesh (here, after the views) and before each
    further hub stage (``model3d._character_mesh_stages``); a shape no longer
    wanted stops there — ``{ok: False, superseded: True, error, body_id}``,
    no failure recorded for the outfit."""
    from app.core import figure as figure_mod, model3d
    from app.core.keyed_lock import keyed_lock
    from app.core.model_refs import find_ref_image
    profile = _profile_of(character_name, None)
    if figure_mod.is_plain(fig.shape) or not is_base_pipeline(character_name, profile=profile):
        return None
    shape, bsig = fig.shape, fig.bsig
    _sets, variant, inputs = figure_mod.shape_plan(character_name, fig, items, profile=profile)
    if inputs is None or figure_mod.shape_key_of(inputs) != shape:
        return {"ok": False, "error": SHAPE_CHANGED, "body_id": shape}
    status_sig = signature or shape
    with keyed_lock("outfit_body", f"{character_name}:{shape}"):
        if not rebuild and figure_mod.stored_shape(
                character_name, shape, view_shas=shape_view_shas(character_name, shape, bsig)) is not None:
            from app.core.outfit_body_posture import is_stale
            if is_stale(character_name, shape):
                matched = model3d.match_outfit_body_posture(character_name, shape)
                if not matched.get("ok"):
                    logger.warning("Outfit body %s of %s: posture match failed (%s) — built on it as it is",
                                   shape, character_name, matched.get("error"))
            return {"ok": True, "cached": True, "body_id": shape}
        registrations = {v: find_ref_image(character_name, _kind(v), bsig) for v in BASE_VIEWS}
        if registrations["front"] is None:
            return {"ok": False, "error": BASE_IMAGES_MISSING, "body_id": shape}

        _outfit_start(character_name, status_sig, "body")
        error: Optional[str] = None
        try:
            missing = [v for v in dressed_views() if shape_view(character_name, v, shape, bsig) is None]
            if missing:
                logger.info("Outfit body %s of %s: rendering its %s first — never meshed from a partial set",
                            shape, character_name, missing)
                rendered = render_shape_views(character_name, fig, missing, items=items, force=False)
                if not rendered["ok"]:
                    still = rendered.get("missing")
                    if not still:
                        raise OutfitError(rendered["error"])
                    raise OutfitError(views_missing_message(
                        still, [v for v in dressed_views() if v not in still], rendered.get("reason") or "",
                        stale=rendered.get("stale") or ()))
            paths = {v: shape_view(character_name, v, shape, bsig) for v in dressed_views()}

            def rerender(v: str) -> Optional[Path]:
                render_shape_views(character_name, fig, [v], items=items, force=True)
                return shape_view(character_name, v, shape, bsig)

            guard, warnings = _guard_dressed_views(character_name, shape, bsig, paths, registrations,
                                                   rerender=rerender)
            used = {v: p for v, p in paths.items() if p is not None}
            left_out = [v for v in dressed_views() if v not in used]
            if left_out:
                # The guard left a turned view out: never meshed without it.
                raise OutfitError(views_missing_message(
                    left_out, [v for v in BASE_VIEWS if v in used],
                    "; ".join(w.replace("; left out of the outfit model", "") for w in warnings)))
            parent = {"body_id": shape, "shape_key": shape, "version": figure_mod.SHAPE_VERSION,
                      "shape_inputs": inputs, "base_signature": bsig, "base_variant": variant,
                      "built_for": signature, "views": shape_view_shas(character_name, shape, bsig),
                      "used_views": [v for v in BASE_VIEWS if v in used], "view_guard": guard,
                      "view_warnings": warnings}
            _mark_shape_views(character_name, shape, parent)
            if not model3d.shape_still_wanted(character_name, shape):
                # Ruling A18: the views stay (they are the shape's); no mesh job for a shape nobody wants now.
                logger.info("Outfit body %s of %s: no longer wanted — not meshed", shape, character_name)
                return {"ok": False, "superseded": True, "error": SHAPE_NOT_WANTED.format(shape=shape),
                        "body_id": shape}
            logger.info("Outfit body %s of %s (in the body: %s, outfit %s): meshing %s", shape, character_name,
                        list(fig.in_body), signature or "-", parent["used_views"])
            result = model3d.generate_for_current_outfit(
                character_name, force=True, signature=shape,
                outfit_body={"outfit_body": parent, "base_variant": variant})
            if result.get("superseded"):
                return {**result, "body_id": shape}   # Ruling A18: stopped between stages, not a failure
            if not result.get("ok"):
                error = str(result.get("error") or "Outfit body generation failed")
            return {**result, "body_id": shape, **({"error": error} if error else {})}
        except OutfitError as e:
            error = str(e) or type(e).__name__
            logger.warning("Outfit body %s of %s failed: %s", shape, character_name, error)
            return {"ok": False, "error": error, "body_id": shape}
        except Exception as e:
            error = str(e) or type(e).__name__
            raise
        finally:
            _outfit_end(character_name, status_sig, "body", error)


def ensure_figure_views(character_name: str, signature: str) -> Optional[Dict[str, Any]]:
    """Before the outfit model of ``signature`` is built: its views are made
    for the figure delivered NOW — a shape stored since they were rendered
    makes them stale (``dressed_image``) — so the missing ones are rendered
    first (``generate_dressed_images`` without ``force``; image jobs only, a
    view the texture store holds is copied). None when nothing was missing;
    else ``{ok, error}`` of the render (the build reports a view that is
    still missing)."""
    manifest = _outfit_manifest(character_name, signature)
    if not manifest:
        return None
    bsig = base_signature(character_name)
    if all(dressed_image(character_name, v, signature, bsig) for v in dressed_views()):
        return None
    try:
        generate_dressed_images(character_name, pieces=manifest.get("pieces") or {},
                                items=manifest.get("items") or [], signature=signature)
    except Exception as e:  # noqa: BLE001 — the build reports what is still missing
        logger.warning("Views of outfit %s of %s failed: %s", signature, character_name, e)
        return {"ok": False, "error": str(e) or type(e).__name__}
    return {"ok": True}


def prepare_outfit_figure(character_name: str, signature: Optional[str] = None, *,
                          force: bool = False) -> Optional[Dict[str, Any]]:
    """Before an outfit model run (``model3d.generate_for_current_outfit``,
    outside its stage): the WANTED figure of the outfit ``signature``
    (default: the worn one) gets its meshed shape (``prepare_shape``) — the
    DELIVERED one instead while own-mesh pieces wait in the body on an
    interim shape (ruling A11: taking them out is a manual Build's ``shape``
    step, never this automatic path), and
    when the outfit has views of an earlier figure (made on the plain body
    meanwhile) they are made for the figure delivered then
    (``ensure_figure_views``). None when there is nothing to do — off the
    pipeline, the outfit model stored and current (unless ``force``), the
    figure on the plain body, nothing records the outfit's pieces — or when
    it went through; the shape's failure ``{ok: False, error, body_id}``
    otherwise (this run's result).

    Ruling A15 b (as in the Build, ``figure_build._interim_waits``): no
    interim shape while the outfit has a figure to show — a stored model of
    this outfit (stale ones too) or, for the worn outfit, any served model —
    then nothing is meshed and the run's result is ``{ok: False, error:
    figure_build.INTERIM_WAITS, waits: True}``: the figure shown stays
    served until the own mesh is ready."""
    from app.core import figure, model3d
    from app.core.model_refs import current_outfit_state, find_ref_image
    profile = _profile_of(character_name, None)
    if not is_base_pipeline(character_name, profile=profile):
        return None
    if signature is None:
        signature = current_outfit_state(character_name)[2]
    if not signature or (not force and model3d.find_model3d(character_name, signature)):
        return None
    manifest = _outfit_manifest(character_name, signature)
    if not manifest:
        return None
    items = list(manifest.get("items") or [])
    outfit = {"pieces": dict(manifest.get("pieces") or {}), "items": items,
              "piece_state": dict(manifest.get("piece_state") or {})}
    wanted, delivered = figure._delivered(character_name, profile=profile, **outfit)
    from app.core import figure_build
    if figure_build._interim_waits(character_name, delivered, figure_build._model_figure(character_name, signature),
                                   signature=signature):
        # Ruling A15 b: no interim shape while a figure is shown — it stays served until the own mesh is ready.
        logger.info("Outfit %s of %s: an own mesh is not ready and a figure is shown — no interim body shape",
                    signature, character_name)
        return {"ok": False, "error": figure_build.INTERIM_WAITS, "waits": True}
    # Ruling A11: while own-mesh pieces wait in the delivered (interim) shape, that shape is the one served —
    # stored already (reused, no job) or not; the wanted shape takes them out on a manual Build only.
    target = delivered if delivered.in_body_own and not figure.is_plain(delivered.shape) else wanted
    prepared = prepare_shape(character_name, target, items=items, signature=signature)
    if prepared is None:
        return None
    if not prepared.get("ok"):
        return prepared
    # The interim shape's outfit views could not be rendered before it existed (they are edits of its views).
    if target is delivered or find_ref_image(character_name, _kind("front"), signature) is not None:
        ensure_figure_views(character_name, signature)
    return None


def _snapshot_shape(character_name: str, shape: str, bsig: str) -> Dict[str, Any]:
    """The stored meshed shape's files, read under the publication lock of
    the REAL model directory, in the layout of ``_snapshot_base_model``
    (``covered`` None — a shape has no covered variant): rigged GLB +
    sidecar, the unrigged source (the paint source of its textures), the
    clean prerig source + sidecar when it exists.
    ``OutfitError(OUTFIT_BODY_MISSING)`` without a rigged shape or its
    unrigged source, ``OUTFIT_BODY_OUTDATED`` when it is not current for its
    views (``figure.stored_shape``)."""
    from app.core import figure
    from app.core.keyed_lock import keyed_lock
    from app.core.model3d import _read_sidecar
    path = outfit_body_path(character_name, shape)
    with keyed_lock("model3d_publication", str(path.parent)):
        meta = _read_sidecar(path)
        if (not path.is_file() or meta.get("rig") != "mixamo" or meta.get("rig_error")
                or not isinstance(meta.get("outfit_body"), dict)):
            raise OutfitError(OUTFIT_BODY_MISSING)
        if figure.stored_shape(character_name, shape,
                               view_shas=shape_view_shas(character_name, shape, bsig)) is None:
            raise OutfitError(OUTFIT_BODY_OUTDATED)
        unrigged = path.parent / "unrigged" / path.name
        prerig = path.parent / "prerig" / path.name
        return {"rigged": path.read_bytes(), "meta": meta,
                "unrigged": unrigged.read_bytes() if unrigged.is_file() else None,
                "prerig": prerig.read_bytes() if prerig.is_file() else None,
                "prerig_meta": _read_sidecar(prerig) if prerig.is_file() else {},
                "covered": None, "covered_meta": {}}


def _build_on_shape(character_name: str, signature: str, *, fig, base: Dict[str, Any], shape: Dict[str, Any],
                    variant: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    """``build_outfit_model`` of a figure on a meshed shape with nothing
    painted on it (texture ``""``), inside the outfit's stage: the outfit
    model is a copy of the CURRENT shape (``_snapshot_shape``; its clean
    prerig source becomes the outfit's, so an outfit that declares other
    extension groups rebuilds them on the shape's geometry). No worker run,
    no hub job. The shape's chain records (mesh/rig backends, face
    cleanup/retexture, Blender steps, extension state, collision set) come
    along; the sidecar adds ``body_id``, ``body_sha256``, ``figure``,
    ``base_signature`` / ``base_model_sha256`` (the outfit model is stale on
    another base model — the shape is reused then) and the outfit's
    manifest. The own-mesh pieces it carries and the worn hair are fitted
    onto THIS shape before the sidecar is published
    (``garment_assembly.body_fit_warning`` → ``garments.body_fit``, CPU from
    the cached garment sources) and grafted by the eager assembly — BEFORE
    anything is published: a piece the figure grafts refused on the shape
    raises ``OutfitError(FIT_REFUSED_NOT_PUBLISHED)`` and the model built
    before stays (Ruling A23 a); another garment left off is named in
    ``garment_warnings`` (``NOT_FITTED_ON_BODY``)."""
    from app.core import model3d
    from app.core.extension_rig import extension_metadata
    from app.core.timeutils import utc_now_iso
    bsig = fig.bsig
    record = shape["meta"]["outfit_body"]
    front = dressed_image(character_name, "front", signature, bsig, fig=fig)
    if front is None:
        raise OutfitError(DRESSED_IMAGES_MISSING)
    manifest = model3d._ref_manifest(front)
    names = {}
    for v in record.get("used_views") or ["front"]:
        used = dressed_image(character_name, v, signature, bsig, fig=fig) if v in BASE_VIEWS else None
        if used is not None:
            names[v] = used.name
    out_dir = model3d.get_model3d_dir(character_name)
    path = out_dir / f"{signature}.glb"
    meta = {k: v for k, v in deepcopy(shape["meta"]).items() if k not in _BASE_ONLY_META and k != "outfit_body"}
    meta.update({"created_at": utc_now_iso(), "source": "base_body", "signature": signature,
                 "base_variant": variant, "covered_missing": False, "character": character_name,
                 "format": "glb", "rig": "mixamo", "base_signature": bsig,
                 "base_model_sha256": hashlib.sha256(base["rigged"]).hexdigest(),
                 "retexture_proof": None, "dressed": True, "source_image": names.get("front") or front.name,
                 "view_images": {v: n for v, n in names.items() if v != "front"},
                 "view_guard": _dict_of(record.get("view_guard")),
                 "view_warnings": [w for w in record.get("view_warnings") or [] if isinstance(w, str)],
                 "texture_signature": "", "texture_reused": False, "body_id": fig.shape,
                 "body_sha256": hashlib.sha256(shape["rigged"]).hexdigest()})
    meta.update(manifest)
    meta["figure"] = fig.as_dict()
    warnings = [w for w in (_dict_of(manifest.get("mesh_items")).get("warnings") or []) if isinstance(w, str) and w]
    # Ruling A23 a: fitted onto the shape BEFORE anything is published — a grafted piece refused there raises.
    not_fitted = _refuse_partial(character_name, fig, meta, profile)
    if not_fitted:
        warnings.append(not_fitted)
    if warnings:
        meta["garment_warnings"] = warnings
    model3d._purge_combination(out_dir, signature, keep_model=path)
    model3d._publish_model_bytes(path, shape["rigged"])
    if shape["prerig"] is not None:
        prerig = out_dir / "prerig" / path.name
        prerig.parent.mkdir(parents=True, exist_ok=True)
        model3d._publish_model_bytes(prerig, shape["prerig"])
        model3d._publish_sidecar(prerig, {k: v for k, v in shape["prerig_meta"].items() if k != "outfit_body"})
    model3d._auto_extension_rig(character_name, path, meta)
    model3d._attach_measurement(meta, path)
    meta.setdefault("extension_rig", extension_metadata(character_name, signature=path.stem))
    model3d._publish_sidecar(path, meta)
    model3d.request_lod(character_name, path)
    _assemble_garments(character_name, signature, path, meta)
    logger.info("Outfit model %s (%s on shape %s, nothing painted)", character_name, signature, fig.shape)
    return {"ok": True, "cached": False, "path": str(path), "filename": path.name, "proof": None,
            "body_id": fig.shape}


def dressed_warnings(character_name: str, signature: str, bsig: str) -> List[str]:
    """The caveats of the stored dressed images of an outfit made from the
    current base: the ``fit_gate`` warning of each fitted view (back, then
    the sides when dressed; kept although no fit attempt passed)."""
    warnings = []
    for view in dressed_views():
        if view == "front" or not bsig:
            continue
        path = dressed_image(character_name, view, signature, bsig)
        warning = (_ref_sidecar(path).get("fit_gate") or {}).get("warning") if path else None
        if warning:
            warnings.append(warning)
    return warnings


def _mesh_warnings(character_name: str, meta: Dict[str, Any], base_sha: str) -> List[str]:
    """The own-mesh warnings of a stored outfit model: the pieces it keeps in
    the body shape that still have no mesh, judged NOW (``MESH_ITEM_IN_BODY``
    with today's reason — a piece whose mesh is ready since warns no more;
    a record without ``in_body`` keeps its recorded warnings), then the
    pieces it left out that still have no fit (``mesh_items_missing`` —
    ``MESH_ITEM_NOT_READY``)."""
    from app.core import figure, garment_set
    from app.models.inventory import get_item
    mesh = _dict_of(meta.get("mesh_items"))
    live = mesh_item_warnings(mesh_items_missing(character_name, meta, base_sha=base_sha))
    if "in_body" not in mesh:
        return [w for w in (mesh.get("warnings") or []) if isinstance(w, str)] + live
    built = figure.built_figure(meta)
    opened = set(built.open) if built is not None else set()
    profile = _profile_of(character_name, None)
    waiting = []
    for item_id in mesh_items_in_body(meta):
        item = get_item(item_id) or {}
        kind = garment_set.garment_kind_of(item) or ""
        if figure._mesh_delivered(character_name, item_id, kind, open_=item_id in opened, base_sha=base_sha,
                                  profile=profile)[0]:
            continue  # its mesh is ready: grafted, the shape keeps it until the next Build
        reason = figure._not_fitted_reason(character_name, item_id, base_sha=base_sha, profile=profile,
                                           state="open" if item_id in opened else "closed")
        waiting.append(MESH_ITEM_IN_BODY.format(item=str(item.get("name") or item_id), reason=reason))
    return waiting + live


def outfit_info(character_name: str, *, base_sig: Optional[str] = None,
                signature: Optional[str] = None) -> Dict[str, Any]:
    """``{signature, status, error, proof, url}`` of an outfit model on the
    pipeline (default: the CURRENT outfit). ``status``: ``running`` (views,
    body or model in progress), ``failed`` (the last run's error),
    ``stale`` (the stored model was built on an older base body — or before
    the pipeline, or from the other base variant than its pieces call for
    now (``variant_current``), or as another figure than the one delivered
    now (``figure_stale``) — and is rebuilt on the next trigger; ``error``
    says so, ``stale_reason`` ``older_base`` / ``before_pipeline`` /
    ``detail_changed`` / ``figure`` / ``outfit_body``), ``ready``,
    ``missing``. ``warnings``: the stored model's view-guard warnings
    (dressed views left out because they turned around) and its own-mesh
    warnings (``_mesh_warnings``), then the dressed images' own
    (``dressed_warnings``). ``proof``: the worker's proof of the stored
    model (None for a copy)."""
    from app.core import model3d
    from app.core.model_refs import current_outfit_state
    if signature is None:
        signature = current_outfit_state(character_name)[2]
    if base_sig is None:
        base_sig = base_signature(character_name)
    current = (base_sig, base_model_sha256(character_name, base_sig))
    with _status_lock:
        running = any(sig == signature for (name, _stage), sig in _outfit_running.items()
                      if name == character_name)
        failure = dict(_outfit_failed.get((character_name, signature)) or {})
    path = model3d.find_model3d(character_name, signature, include_stale=True)
    meta = model3d._read_sidecar(path) if path else {}
    reason = None
    if running:
        status, error = "running", ""
    elif failure:
        status, error = "failed", failure.get("error") or ""
    elif path is None:
        status, error = "missing", ""
    elif not built_on_current_base(meta, current):
        status, error = "stale", (OLDER_BASE if meta.get("base_signature") else BEFORE_PIPELINE)
        reason = "older_base" if meta.get("base_signature") else "before_pipeline"
    elif not variant_current(character_name, meta):
        status, error, reason = "stale", DETAIL_CHANGED, "detail_changed"
    elif reason := figure_stale(character_name, meta) or None:
        status, error = "stale", FIGURE_CHANGED if reason == "figure" else OUTFIT_BODY_CHANGED
    else:
        status, error = "ready", ""
    return {"signature": signature, "status": status, "error": error, "stale_reason": reason,
            "warnings": (list(meta.get("view_warnings") or []) + _mesh_warnings(character_name, meta, current[1])
                         if path else []) + dressed_warnings(character_name, signature, base_sig),
            "proof": meta.get("retexture_proof") if path else None,
            "url": model3d.signature_model_url(character_name, signature) if status == "ready" else None}


# --- Rebuild cost (improvements: ``outfit_rebuild``) -------------------------

#: A stale outfit model's ``stale_reason`` (``outfit_info``) in a rebuild
#: note or an improvement label.
STALE_REASON_TEXT = {"older_base": "older base", "before_pipeline": "made without the base body",
                     "detail_changed": "other body detail", "figure": "other figure",
                     "outfit_body": "older body shape"}
#: The img2mesh + rig jobs of one outfit body (meshed shape).
OUTFIT_BODY_JOBS = 2


def rebuild_cost(character_name: str, signature: str, *, profile: Optional[Dict[str, Any]] = None,
                 stale_reason: Optional[str] = None) -> Dict[str, Any]:
    """The hub cost of rebuilding the outfit model ``signature`` on the
    current base (``model_refs.trigger_now`` of its views, then
    ``model3d.generate_for_current_outfit(force=True)``: the wanted shape,
    the views of the figure then delivered, the model), counted in FIRST
    attempts — a re-draft after a refused composite (``DRAFT_ATTEMPTS``) and
    the view guard's one re-render may each add one per view: ``{image_jobs,
    mesh_jobs, hub_jobs, note, views_needed, body_needed}``. Read-only. One
    set of views costs the front edit plus a draft per other view — the
    composite onto the base view is CPU work: 2 with front + back, 4 with
    the side views on (``dressed_view_jobs``; a view the texture store holds
    is copied, no job: the estimate stays an upper bound for first
    attempts).

    * ``body_needed``: the WANTED figure (``figure.wanted_figure`` of the
      outfit's pieces) stands on a meshed shape that is not stored
      (``figure.stored_shape``) → img2mesh + rig = 2, plus one set of views
      for the shape when its own views are not all current.
    * ``views_needed``: a ``dressed_views()`` view has no ``dressed_image``
      for the figure delivered now, or the shape is built first (the
      outfit's views are then edits of the new shape) — one set of views,
      none when nothing is painted on a meshed shape (copies).
    * Views and shape current: Blender on the CPU, 0.

    ``stale_reason`` (``outfit_info``'s; None = asked here) opens the note.
    The base body itself is never rebuilt, nor judged by its prompt wording.
    Anything unreadable answers ``hub_jobs`` None (unknown, never a silent 0)."""
    try:
        from app.core import figure
        profile = _profile_of(character_name, profile)
        bsig = base_signature(character_name, profile=profile)
        if stale_reason is None:
            stale_reason = outfit_info(character_name, base_sig=bsig, signature=signature).get("stale_reason")
        views = dressed_views()
        manifest = _outfit_manifest(character_name, signature)
        pieces, items = dict(manifest.get("pieces") or {}), list(manifest.get("items") or [])
        wanted = figure.wanted_figure(character_name, profile=profile, pieces=pieces, items=items)
        meshed = not figure.is_plain(wanted.shape)
        shape_views = shape_view_shas(character_name, wanted.shape, bsig) if meshed else {}
        body_needed = meshed and figure.stored_shape(character_name, wanted.shape, view_shas=shape_views) is None
        shape_views_needed = body_needed and not all(shape_views.values())
        if body_needed:
            views_needed = bool(wanted.texture)
        else:
            now = figure.delivered_figure(character_name, profile=profile, pieces=pieces, items=items)
            # On a meshed shape with nothing painted the views are copies of the shape's (no job).
            views_needed = (bool(now.texture) or figure.is_plain(now.shape)) and any(
                dressed_image(character_name, v, signature, bsig, fig=now) is None for v in views)
    except Exception as e:  # noqa: BLE001 — an estimate, never a failure
        logger.warning("Rebuild cost %s / %s not computable: %s", character_name, signature, e)
        return {"image_jobs": None, "mesh_jobs": None, "hub_jobs": None, "views_needed": None,
                "body_needed": None, "note": f"cost unknown — {e}"}
    image_jobs = dressed_view_jobs() * (int(views_needed) + int(shape_views_needed))
    mesh_jobs = OUTFIT_BODY_JOBS if body_needed else 0
    parts = ([f"views {image_jobs}"] if image_jobs else []) + ([f"body {mesh_jobs}"] if mesh_jobs else [])
    what = (" + ".join(parts) + " (first attempts)" if parts
            else "body shape stored, CPU only" if meshed else "repaint on the CPU")
    reason = STALE_REASON_TEXT.get(str(stale_reason or ""), "")
    return {"image_jobs": image_jobs, "mesh_jobs": mesh_jobs, "hub_jobs": image_jobs + mesh_jobs,
            "views_needed": views_needed, "body_needed": body_needed,
            "note": f"{reason}: {what}" if reason else what}


# --- Base refresh (the improvements type ``base_refresh``) -----------------
# Spec docs/superpowers/specs/2026-11-11-hair-from-body-design.md § Design 5:
# a base rendered with older prompt texts (``OLDER_PROMPTS`` — e.g. a bald
# base of a character whose hair is now in the body mesh) is rebuilt at idle
# time by the same calls the Figure tab's plain-body actions make: the views
# (``generate_base_images``, force) and the model (``generate_base_model``,
# force). The base signature stays (prompts are not identity), so every file
# is replaced in place under its own name.

#: ``base_refresh_plan`` reason → the text the improvement step shows.
REFRESH_REASON_TEXT = {"older_prompts": "older prompts",
                       "reference": "made from another reference",
                       "views": "views not refreshed yet",
                       "model": "model built from older views",
                       "mesh_mismatch": "the mesh does not match its views",
                       "missing": "missing"}
#: Hub jobs of one base view render on its first attempt (the front's hand
#: gate may render it up to ``HAND_GATE_ATTEMPTS`` times).
BASE_VIEW_JOBS = 1
#: Hub jobs of the front's skin detail step (``base_skin``: one edit).
SKIN_STEP_JOBS = 1


def base_view_states(character_name: str, *, profile: Optional[Dict[str, Any]] = None
                     ) -> Dict[str, Dict[str, str]]:
    """``{view: freshness}`` of the stored base views — what the Base body
    tab shows on each tile (``model_overview.base_view_freshness`` with the
    view's recorded ``prompt_fingerprint`` — ``recorded_fingerprint``, the
    Ruling A74a carry-over — against the current one, as
    ``annotate_base_info`` calls it); ``missing`` for a view without a file."""
    from app.core import model_overview
    from app.core.model_refs import find_ref_image, image_tile_meta
    profile = _profile_of(character_name, profile)
    bsig = base_signature(character_name, profile=profile)
    current = prompt_fingerprint(character_name, profile=profile)
    tiles: Dict[str, Optional[Tuple[str, str]]] = {}
    for view in BASE_VIEWS:
        path = find_ref_image(character_name, _kind(view), bsig)
        tiles[view] = ((str(image_tile_meta(path).get("created_at") or ""),
                        recorded_fingerprint(character_name, bsig, view, _view_sidecar(path), current=current,
                                             profile=profile)) if path else None)
    front_created = (tiles.get("front") or ("", ""))[0]
    out: Dict[str, Dict[str, str]] = {}
    for view, tile in tiles.items():
        out[view] = (model_overview.freshness(model_overview.MISSING) if tile is None else
                     model_overview.base_view_freshness(view, tile[0], front_created, prompts=(tile[1], current)))
    return out


def base_refresh_plan(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
                      missing: bool = False) -> Dict[str, Any]:
    """What a base refresh of the character runs now: ``{signature, views,
    model, reason}`` (``views`` in ``BASE_VIEWS`` order). Read-only.

    * ``missing`` (only with ``missing=True`` — the Build's plain-body step,
      ``figure_build``; the ``base_refresh`` improvement never builds a
      missing base): no stored front → every view, then the model; every
      view current but no base model → the model alone.

    * ``older_prompts`` — the stored front carries ``OLDER_PROMPTS``
      (``base_prompts_freshness``, the hair row's note): every view, then
      the model (each view's and the model's "Regenerate" in the Figure
      tab's plain-body details).
    * ``views`` — the front is current, another view is not
      (``base_view_states``: older prompts, older than the front, missing):
      those views, then the model. A refresh that stopped between the views
      (load) goes on where it stopped.
    * ``model`` — every view current, the stored base model not built from
      them (``model_overview.base_model_freshness`` stale): the model alone
      — a refresh that stopped before the model.
    * ``reference`` (only with ``missing=True`` — the Build and the Base
      body tab's Run all, a person's click; the ``base_refresh`` improvement
      never spends on it, Ruling A74b): the stored front was made from
      another reference than ``front_reference`` names now (or from text
      while there is a profile image): every view, then the model.
    * ``mesh_mismatch`` (only with ``missing=True`` — the Build and the Base
      body tab's Run all, a person's click; the improvement never spends on
      it, Ruling A61): every view current, but the body retexture worker
      refused the stored base mesh against one of them
      (``mesh_view_mismatch``): the model alone, a fresh mesh from the
      current views.
    * ``""`` — nothing to do, or (without ``missing``) no stored front (a
      missing base is not an older one)."""
    from app.core import model3d, model_overview
    profile = _profile_of(character_name, profile)
    bsig = base_signature(character_name, profile=profile)
    plan: Dict[str, Any] = {"signature": bsig, "views": [], "model": False, "reason": ""}
    prompts = base_prompts_freshness(character_name, profile=profile)
    if prompts["state"] == model_overview.MISSING:
        return {**plan, "views": list(BASE_VIEWS), "model": True, "reason": "missing"} if missing else plan
    if prompts["state"] == model_overview.STALE:
        return {**plan, "views": list(BASE_VIEWS), "model": True, "reason": "older_prompts"}
    if missing and not front_reference_state(character_name, bsig, profile=profile)["current"]:
        return {**plan, "views": list(BASE_VIEWS), "model": True, "reason": "reference"}
    states = base_view_states(character_name, profile=profile)
    views = [v for v in BASE_VIEWS if v != "front" and states[v]["state"] != model_overview.CURRENT]
    if views:
        return {**plan, "views": views, "model": True, "reason": "views"}
    path = model3d.find_model3d(character_name, bsig)
    if missing and (path is None or not base_model_sha256(character_name, bsig)):
        return {**plan, "model": True, "reason": "missing"}
    if path is not None and model_overview.base_model_freshness(
            model3d._read_sidecar(path),
            model_overview._base_view_shas(character_name, bsig))["state"] == model_overview.STALE:
        return {**plan, "model": True, "reason": "model"}
    if missing and path is not None and mesh_view_mismatch(character_name, bsig) is not None:
        return {**plan, "model": True, "reason": "mesh_mismatch"}
    return plan


def base_rebuild_steps(character_name: str, plan: Dict[str, Any]) -> List[Tuple[str, int]]:
    """``(step, hub jobs on the first attempt)`` of what ``plan``
    (``base_refresh_plan``) runs, in run order: ``view <name>`` per view to
    render — with the front, while the world switch is on and the front is
    not made from the full-body reference (``base_skin.applies``, Ruling
    A92), its ``skin front`` step right after it (one edit) — then, with the
    model, the hub stages of a fresh base mesh run
    (``model3d.mesh_hub_stages``: mesh, [upscale, face], rig; normalize and
    the other Blender steps are CPU work)."""
    from app.core import base_skin, model3d
    steps: List[Tuple[str, int]] = []
    for v in plan.get("views") or ():
        steps.append((f"view {v}", BASE_VIEW_JOBS))
        if v == "front" and base_skin.applies(character_name):
            steps.append(("skin front", SKIN_STEP_JOBS))
    if plan.get("model"):
        steps += [(stage, 1) for stage in model3d.mesh_hub_stages(character_name, plan["signature"])]
    return steps


def base_rebuild_cost(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
                      plan: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The hub cost of the base refresh ``plan`` (``base_refresh_plan`` when
    None), counted in FIRST attempts over ``base_rebuild_steps`` — the list
    the refresh runs, so the count cannot drift from it: ``{hub_jobs, steps,
    note, plan}``. The hand gate may render the front up to
    ``HAND_GATE_ATTEMPTS - 1`` more times, the dark-face gate retry the face
    once — the note says so where it applies. Anything unreadable answers
    ``hub_jobs`` None (unknown, never a silent 0)."""
    try:
        plan = plan if plan is not None else base_refresh_plan(character_name, profile=profile)
        steps = base_rebuild_steps(character_name, plan)
    except Exception as e:  # noqa: BLE001 — an estimate, never a failure
        logger.warning("Base rebuild cost %s not computable: %s", character_name, e)
        return {"hub_jobs": None, "steps": [], "note": f"cost unknown — {e}", "plan": plan or {}}
    total = sum(jobs for _step, jobs in steps)
    views = sum(jobs for step, jobs in steps if step.startswith("view "))
    parts = ([f"views {views}"] if views else []) + [step for step, _jobs in steps if not step.startswith("view ")]
    extra = ([f"the hand gate may render the front up to {HAND_GATE_ATTEMPTS - 1} more times"] if "front" in (plan.get("views") or ()) else []) \
        + (["the dark-face gate may retry the face once"] if any(step == "face" for step, _jobs in steps) else [])
    reason = REFRESH_REASON_TEXT.get(str(plan.get("reason") or ""), "")
    what = (" + ".join(parts) + f" = {total} hub jobs (first attempts"
            + ("; " + "; ".join(extra) if extra else "") + ")") if steps else "nothing to rebuild"
    return {"hub_jobs": total, "steps": steps, "note": f"{reason}: {what}" if reason else what, "plan": plan}
