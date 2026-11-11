"""Base body — the bald, unclothed A-pose figure of a humanoid character.

A humanoid character on the ``base_body`` model pipeline (profile field
``model_pipeline: "base_body"``) gets ONE base body: four A-pose views
(front/back/left/right) of a bald, anatomically neutral figure, rendered from
the character's profile image, and one model built from them. Outfits are
painted onto that body later (spec
``docs/superpowers/specs/2026-11-08-base-body-outfits-design.md`` § A).

This module holds the description, the view prompts with their negative, the
base signature that keys every stored base image and model, the rendering of
the four views (``generate_base_images``, the front through the hand-pose
gate of ``base_body_gates``), the rigged base model built from
them (``generate_base_model``), the per-character pipeline switch
(``set_pipeline``) and the UI info (``base_info``).

Outfits (spec § B, phase 3): every outfit combination of a character on the
pipeline gets two DRESSED images (``dressed_views``; four with the world
setting ``base_body.dressed_side_views``) — the front an edit of the base
front, the back (and the sides) a draft from the dressed front fitted onto
the base view (``generate_dressed_images``, ``dress_prompt`` /
``draft_prompt`` / ``FIT_PROMPT``) stored as the usual ``tpose[_<view>]_<sig>``
refs — and an
outfit model that is the rigged base
with the outfit painted on by the local GLBBodyRetexture worker
(``build_outfit_model``, base colour swapped by ``replace_base_color``).
With the per-character ``outfit_body_mode: "mesh"`` a dressed combination
gets an OUTFIT BODY instead — its dressed views meshed and rigged through the
old path's staged chain, one per texture signature (section "Outfit body as
mesh": ``prepare_outfit_body``, ``outfit_body_id``, storage and parent record).

What describes the body:

* gender and age through the template's ``character_appearance`` replacement
  tokens, in the ``"{gender}, {age} years old"`` phrasing World-Dev asks for;
* the ``always`` fragments of the body slots a species package flags
  ``base_body: true`` (human: eyes, skin, build — the build fragment carries
  the height phrase). Never the free-text ``character_appearance`` (it names
  clothes and hair), never hair, never a slot without the flag — anatomy
  packs stay out unless they opt in.

The prompt layout (user directive 2026-11-09, "character details always
first"): the front's style (``base_front``) opens with its subject
clause, then its ``{character}`` slot takes the CHARACTER BLOCK
(``base_character``: "sfw, no clothing, " + ``base_appearance``), then the rest
of the style; the base prompt (``base_prompt``: pose, bald head, body text)
follows after a comma. The image service fills the slot
(``config.fill_character_slot``, payload key ``style_character``).

The pose texts: the front is ``model_refs.BASE_FRONT_POSE_PROMPT`` (the
A-pose front without the palms and hair clauses). Back/left/right are edits
of the front and carry ONE short sentence each (``BASE_VIEW_PROMPTS``), no
style and no character block (use cases ``base_view_back`` /
``base_view_side``; user test 2026-11-09: the long texts made Qwen invent
things). The outfit drafts keep the mesh-input view texts of
``app/core/model_refs.py`` (admin overrides included) with their hair
clauses taken out, under the long ``base_back`` / ``base_side`` styles
(``DRAFT_USE_CASES``).
"""
import hashlib
import json
import os
import re
import threading
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

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
BODY_TEXT = "a smooth featureless mannequin-like unclothed body with plain smooth skin"
#: Opens the character block of the base front ("no clothing" is carried by
#: BODY_TEXT's "unclothed" since 2026-11-11).
BASE_BLOCK_HEAD = "sfw"
#: Use case (style, negative) per base view — their own, so the whole-body
#: T-pose path keeps "tpose" / "tpose_back" / "tpose_side" untouched. The
#: edit views' use cases carry no style: their whole prompt is the short
#: ``BASE_VIEW_PROMPTS`` text.
BASE_USE_CASES = {"front": "base_front", "back": "base_view_back", "left": "base_view_side",
                  "right": "base_view_side"}
#: Use case per two-step draft (back, left, right): the empty style of the
#: base edit views (``base_view_*``, keeping their view negatives) — a draft
#: is an edit of the dressed front and carries one short sentence
#: (``DRAFT_PROMPTS``), no style and no character block (review 2026-11-11:
#: the long base style and the 60-word A-pose text put the only new
#: information, the outfit clause, at word 168 of 188).
DRAFT_USE_CASES = {"back": "base_view_back", "left": "base_view_side", "right": "base_view_side"}
#: The WHOLE prompt of a two-step draft per view, with the outfit clause in
#: its slot (``draft_prompt``): the base view sentence, the outfit right
#: after the turn, the frame last.
DRAFT_PROMPTS = {
    "back": ("The same person turned around, seen directly from behind, back view, same A-pose, same "
             "framing, completely bald, {outfit}, the whole figure from head to feet in the frame."),
    "left": ("The same person turned to a strict left side profile view, same A-pose, same framing, "
             "completely bald, {outfit}, the whole figure from head to feet in the frame."),
    "right": ("The same person turned to a strict right side profile view, same A-pose, same framing, "
              "completely bald, {outfit}, the whole figure from head to feet in the frame."),
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
BODY_NEGATIVE = "clothing, underwear, jewellery, detailed anatomy"
POSE_NEGATIVE = ("hands touching body, fists, curled fingers, fused fingers, mitten hands, cropped feet, "
                 "feet cut off, cropped legs, close-up, portrait crop")
BASE_NEGATIVE = ", ".join((HAIR_NEGATIVE, BODY_NEGATIVE, POSE_NEGATIVE))

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


def base_character(character_name: str, view: str, *,
                   profile: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """The CHARACTER BLOCK of one base view, for the style's ``{character}``
    slot: on the front ``BASE_BLOCK_HEAD``, ``BALD_HEAD``, ``BODY_TEXT`` and
    ``base_appearance`` — the words that shape the figure, right after the
    style's subject sentence (review 2026-11-11). None on back/left/right —
    an edit of the front takes the body from the image, and its prompt is the
    short ``BASE_VIEW_PROMPTS`` text alone (user test 2026-11-09: the block
    changed nothing)."""
    if view not in BASE_VIEWS:
        raise ValueError(f"unknown base-body view: {view!r}")
    if view != "front":
        return None
    appearance = base_appearance(character_name, profile=_profile_of(character_name, profile),
                                 base_fragments=True)
    return ", ".join(p for p in (BASE_BLOCK_HEAD, BALD_HEAD, BODY_TEXT, appearance) if p)


def base_prompt(character_name: str, view: str, *,
                profile: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """``(prompt, negative)`` of one base-body view. Front: the pose text —
    what follows the style (``base_character`` is the block inside it).
    Back/left/right: the ``BASE_VIEW_PROMPTS`` text, the whole prompt of the
    edit. The negative is ``base_negative`` (``BASE_NEGATIVE`` + the slots'
    texts)."""
    if view not in BASE_VIEWS:
        raise ValueError(f"unknown base-body view: {view!r}")
    profile = _profile_of(character_name, profile)
    prompt = _pose_text("front") if view == "front" else BASE_VIEW_PROMPTS[view]
    return prompt, base_negative(character_name, profile=profile)


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


def prompt_fingerprint(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> str:
    """12 hex over the four views' character blocks, prompts and negatives —
    the texts a base render is made with. Stored in every base view's
    sidecar; a stored base whose fingerprint differs from the current one is
    current but carries the ``OLDER_PROMPTS`` note."""
    profile = _profile_of(character_name, profile)
    payload = {view: [base_character(character_name, view, profile=profile),
                      *base_prompt(character_name, view, profile=profile)] for view in BASE_VIEWS}
    return hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def _front_sidecar(character_name: str, signature: str) -> Dict[str, Any]:
    """The base front's sidecar (``model_refs/tpose_<sig>.json``), {} without one."""
    from app.core.model_refs import get_model_refs_dir
    path = get_model_refs_dir(character_name) / f"tpose_{signature}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _stored_base_for(character_name: str, identity: str, profile_image: str) -> Optional[str]:
    """The signature of the stored base set that belongs to ``identity``:
    the newest front sidecar that names it (``base_identity``), else — a set
    rendered before identities were recorded (no ``base_identity`` key) —
    the newest one whose reference was the current profile image. None when
    nothing stored fits. Read-only: nothing is renamed or rewritten."""
    from app.core.model_refs import get_model_refs_dir
    refs = get_model_refs_dir(character_name)
    try:
        names = [n for n in os.listdir(refs) if _BASE_FRONT_SIDECAR.match(n)]
    except OSError:
        return None
    named: List[Tuple[str, str]] = []
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
            continue
        refs_used = meta.get("reference_images")
        first = refs_used.get("input_reference_image_1") if isinstance(refs_used, dict) else None
        if profile_image and first == profile_image:
            legacy.append((stamp, signature))
    for pool in (named, legacy):
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
    stored = _stored_base_for(character_name, identity, _profile_image_id(character_name, profile)[0])
    return stored or identity


def prompts_current(character_name: str, signature: str, *, profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the stored base ``signature`` was rendered with the current
    prompt texts (its front sidecar's ``prompt_fingerprint``)."""
    meta = _front_sidecar(character_name, signature)
    return bool(meta) and meta.get("prompt_fingerprint") == prompt_fingerprint(character_name, profile=profile)


def is_base_pipeline(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the character is on the base-body pipeline: the profile switch
    is set AND the character is humanoid (an animal never is)."""
    profile = _profile_of(character_name, profile)
    if profile.get("model_pipeline") != "base_body":
        return False
    from app.core.model_refs import is_humanoid
    return bool(is_humanoid(character_name, profile=profile))


# --- Rendering the four views ---------------------------------------------

# Status per (character, view), in memory like the model-refs status: the
# count of reservations still holding the view (a route thread waiting on the
# character lock counts — it WILL render), since when, and the last failure.
_status_lock = threading.Lock()
_running: Dict[Tuple[str, str], Tuple[datetime, int]] = {}
_failed: Dict[Tuple[str, str], Dict[str, Any]] = {}
# One base render per character at a time: the views edit the front, and a
# second run would race the same files.
_char_locks: Dict[str, threading.Lock] = {}


def _char_lock(character_name: str) -> threading.Lock:
    with _status_lock:
        return _char_locks.setdefault(character_name, threading.Lock())


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat(timespec="seconds") if dt else None


def reserve_views(character_name: str, views: Iterable[str]) -> None:
    """Mark views running (counted, so nested and queued runs stack)."""
    from app.core.timeutils import utc_now
    with _status_lock:
        for view in views:
            key = (character_name, view)
            started, count = _running.get(key, (utc_now(), 0))
            _running[key] = (started, count + 1)


def release_views(character_name: str, views: Iterable[str]) -> None:
    with _status_lock:
        for view in views:
            key = (character_name, view)
            started, count = _running.get(key, (None, 0))
            if count <= 1:
                _running.pop(key, None)
            else:
                _running[key] = (started, count - 1)


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
    path), or no profile image (the identity of the base body comes from
    it — ``MissingInput``), or a single view without its front
    (``MissingFront``)."""
    if view is not None and view not in BASE_VIEWS:
        raise ValueError(f"unknown base-body view: {view!r}")
    profile = _profile_of(character_name, profile)
    from app.core.model_refs import current_profile_image, find_ref_image, is_humanoid
    if not is_humanoid(character_name, profile=profile):
        raise ValueError("The base body is for humanoid characters only")
    if current_profile_image(character_name, profile=profile) is None:
        raise MissingInput("No profile picture. Set a profile picture, then render the base body")
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
                         force: bool = False) -> Dict[str, Optional[str]]:
    """Render the base-body views. Blocking — call from a worker thread.

    Front first (the ``tpose`` render path: use case ``base_front``, occasion
    ``base_front``, the profile image as identity reference), then
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
    with what was rendered. Back/left/right edit the chosen front.

    Cached per base signature: a view that exists is skipped unless
    ``force``. ``view`` renders that one view only (a non-front view needs
    the front). The prompts carry no use-case style — the image service
    adds the style (with the character block in its slot) before the prompt
    and the use case's negative; ``base_prompt``'s negative
    is APPENDED to it (``extra_negative``), never a replacement.

    Returns ``{view: path | None}`` for every view it rendered (None =
    failed); a front that fails stops the run — the views need it."""
    import tempfile
    from app.core import base_body_gates, expression_regen
    from app.core.model_refs import _tpose_size, find_ref_image, get_model_refs_dir, neutral_view_reference
    with _char_lock(character_name):
        # Read at run time: a run queued behind another one renders the
        # profile (image, body slots) current when it starts.
        profile = check_renderable(character_name, view=view)
        bsig = base_signature(character_name, profile=profile)
        identity = base_identity(character_name, profile=profile)
        fingerprint = prompt_fingerprint(character_name, profile=profile)
        refs_dir = get_model_refs_dir(character_name)
        wanted = BASE_VIEWS if view is None else (view,)
        todo = [v for v in wanted
                if force or find_ref_image(character_name, _kind(v), bsig) is None]
        if not todo:
            logger.info("Base body %s (%s): already rendered", character_name, bsig)
            return {}
        width, height = _tpose_size()
        mesh_profile = deepcopy(profile)
        mesh_profile["equipped_pieces"] = {}
        mesh_profile["equipped_items"] = []
        results: Dict[str, Optional[str]] = {}

        def draw(v: str, stem: Path, reference: Optional[Path]) -> Optional[Path]:
            prompt, negative = base_prompt(character_name, v, profile=profile)
            character = base_character(character_name, v, profile=profile)
            return expression_regen.render_character_image(
                character_name,
                output_stem=stem,
                equipped_pieces={}, equipped_items=[],
                pose_prompt="", expression_prompt="",
                bare_prompt=prompt, extra_negative=negative,
                image_use_case=BASE_USE_CASES[v],
                style_character=character,
                occasion="base_front" if v == "front" else "base_view",
                override_width=width, override_height=height,
                apply_state_modifiers=False,
                mesh_input_profile=mesh_profile,
                back_view=v == "back",
                reference_image=reference,
                sidecar_extra={"base_signature": bsig, "base_identity": identity,
                               "prompt_fingerprint": fingerprint},
                # The character's identity/pose LoRAs as on its tpose
                # render (tpose_loras, else loras); no slot LoRAs.
                character_loras=True)

        def draw_front(final: Path) -> Tuple[Optional[Path], Optional[str]]:
            """``(stored path, warning)`` of the gated front attempts."""
            attempts: List[Tuple[Path, Dict[str, Any]]] = []
            with tempfile.TemporaryDirectory(prefix=".handgate_", dir=refs_dir,
                                             ignore_cleanup_errors=True) as staging:
                for n in range(1, HAND_GATE_ATTEMPTS + 1):
                    stem = Path(staging) / f"attempt{n}" / final.name
                    stem.parent.mkdir()
                    try:
                        path = draw("front", stem, None)
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
                else:
                    path = draw(v, final, reference)
                error = None if path else "render failed"
            except Exception as e:  # noqa: BLE001 — one view never kills the run
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
            # them with the current ones for the OLDER_PROMPTS note).
            tile["prompt_fingerprint"] = str(_view_sidecar(path).get("prompt_fingerprint") or "")
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
    return {"pipeline": pipeline, "humanoid": humanoid,
            "signature": signature, "images": images, "image_meta": image_meta,
            "prompt_fingerprint": prompt_fingerprint(character_name, profile=profile) if humanoid else "",
            "status": base_status(character_name),
            "model": base_model_info(character_name, signature),
            "outfit": outfit_info(character_name, base_sig=signature) if pipeline else None,
            "hair": hair,
            "now": _iso(utc_now())}


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


def generate_base_model(character_name: str, *, force: bool = False) -> Dict[str, Any]:
    """Build the rigged base model from the base images. Blocking (minutes)
    — call from a worker thread.

    The staged mesh run of ``model3d.generate_for_current_outfit`` with
    ``signature=<bsig>`` and ``base=True`` (frozen into the hub-op inputs):
    source ``tpose_<bsig>``, every stored base view, the character's mesh
    occasion; after the rig no anatomy parts and no distance tier, the
    sidecar records ``"base": true`` and the unrigged checkpoint
    ``model3d/unrigged/<bsig>.glb`` stays. Cached per base signature unless
    ``force``."""
    from app.core import model3d
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


def set_pipeline(character_name: str, enabled: bool) -> bool:
    """Switch the character onto (``model_pipeline: "base_body"``) or off the
    base-body pipeline. ValueError for a non-humanoid on switching on — the
    profile stays untouched. Returns the save result."""
    from app.core.keyed_lock import keyed_lock
    from app.core.model_refs import is_humanoid
    from app.models.character import get_character_profile, save_character_profile
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        if enabled:
            if not is_humanoid(character_name, profile=profile):
                raise ValueError("The base-body pipeline is for humanoid characters only")
            if profile.get("model_pipeline") == "base_body":
                return True
            profile["model_pipeline"] = "base_body"
        else:
            if "model_pipeline" not in profile:
                return True
            profile.pop("model_pipeline")
        return bool(save_character_profile(character_name, profile))


# --- Outfits on the base body (spec § B) -----------------------------------

# The edit form of the S1 spike (claude-out/s1-base-body/kleidung_real/
# front.json): keep everything, change only the clothing.
DRESS_KEEP = ("Keep the image exactly as it is: the same person, same body shape, same pose, same arm and hand "
              "position, same framing and background.")
DRESS_STYLE_NEGATIVE = ("illustration, anime, cgi, 3d render, painting, airbrushed skin, plastic skin, smooth "
                        "flawless skin, overexposed, glossy, fantasy, studio lighting, cartoon, drawing, sketch, "
                        "watermark, signature, text, logo, deformed, blurry, low quality")
# The spike's garment words, each with the words that mean the outfit itself
# names it — such a term leaves the negative (a skirt must not be forbidden
# from an outfit that IS a skirt). "hair": the base body is bald until the
# hair mesh (phase 4); the edit must not grow any.
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
#: Views made in two steps (a draft from the dressed front, then a fit onto
#: the base view): everything dressed but the front.
DRAFT_VIEWS = ("back", "left", "right")
#: ``(draft occasion, fit occasion)`` per two-step view.
DRESS_OCCASIONS = {"back": ("outfit_back_draft", "outfit_back"),
                   "left": ("outfit_side_draft", "outfit_side"),
                   "right": ("outfit_side_draft", "outfit_side")}
#: Default of ``base_body.side_arm_margin`` and its bounds (fraction of the
#: body height the worker skips around the arm in a side view).
SIDE_ARM_MARGIN_DEFAULT = 0.03
SIDE_ARM_MARGIN_MAX = 0.2
SIDE_VIEW_NOT_DRESSED = ("On the base-body pipeline only the front and the back are dressed — "
                         "the side views belong to the base body (Base body tab)")
DRESSED_FRONT_FIRST = "Render the dressed front first — the back draft is made from it"


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
# run): a DRAFT rendered fresh from the dressed front with the base back
# prompt, the body text replaced by the outfit of the reference — then the FIT,
# an edit of the base back with the draft as second reference. Dressed side
# views (``dressed_views``) go the same way with the base side prompt.
# DRAFT_OUTFIT_TEXT and FIT_PROMPT are the ONE wording each: a backend that
# addresses its references differently gets its own wording beside them.
DRAFT_OUTFIT_TEXT = ("wearing exactly the same outfit as the person in the reference image, the same "
                     "garments, lengths, cut, colours and shoes")
#: Use case of the dressed front edit: empty style and negative (config) —
#: the ``DRESS_KEEP`` sentence is the whole prompt, like the base views.
DRESS_USE_CASE = "outfit_edit"
#: The draft keeps the base negative minus its no-clothing words.
DRAFT_NEGATIVE = ", ".join((HAIR_NEGATIVE, "detailed anatomy", POSE_NEGATIVE))
#: The whole fit prompt — no style, view sentence, outfit text or negative
#: (measured 2026-11-09: silhouette IoU vs the base back 0.92-0.93 against
#: 0.905 with the long edit prompt).
FIT_PROMPT = "edit the first image with the clothes from the second image"
#: Use case of the fit: empty style and negative (config).
FIT_USE_CASE = "outfit_fit"
#: Alpha from which a pixel belongs to the figure of a fit reference.
FIT_FIGURE_ALPHA = 16
#: Fit renders per view at most; each attempt is a fresh render (new seed).
FIT_ATTEMPTS = 2
#: The back's ``unchanged_delta_e`` in the retexture proof (Lab dE between
#: the registered dressed back and the base back on the regions the edit did
#: not change) above which the outfit build renders the back fit once more
#: and keeps the better one (finding 2026-11-09: front 2.9, back 5.9).
BACK_REFIT_DELTA_E = 4.0
#: Where the drafts live: a subdirectory of model_refs, so no reader of
#: the stored refs (find_ref_image, mesh inputs, the outfit scans) parses
#: them as refs of their own; the reference gate still accepts them.
DRAFT_DIR = "drafts"

BASE_IMAGES_MISSING = "Base body images missing — render them in the Base body tab"
BASE_MODEL_MISSING = "Base body model missing — generate it in the 3D tab"
DRESSED_IMAGES_MISSING = "Dressed images missing — render the outfit's pose images"
OLDER_BASE = "Built on an older base body"
BEFORE_PIPELINE = "Built before the base body pipeline"
DETAIL_CHANGED = "Built for another body detail under the clothing"
COVERED_MISSING = ("The base body has no current covered variant — the outfit was built from the full base; "
                   "rebuild the base body's extension bones")
#: An outfit model built while an own-mesh piece it wears had no fit — now it has one.
MESH_ITEM_READY = "An own-mesh piece painted on here has its garment mesh now"
#: The ``garment_warnings`` entry of an own-mesh piece left painted on.
MESH_ITEM_PAINTED = "{item} stays painted on: {reason}"
#: ... for a piece whose garment chain failed: no automatic trigger retries
#: that fsig (``garments.cached_failure``), only Regenerate does.
MESH_ITEM_FAILED = "{item} stays painted on: {reason} — Regenerate in the Wardrobe"
NO_MESH_FIT = "no accepted fit on the current base model"
#: Outfit body mode ``mesh`` (ruling 2026-11-10): a flagged piece without an
#: accepted fit is never painted (meshed) into the outfit body — it is
#: missing from the outfit model until its mesh is accepted. The same English
#: text is a React key (Outfit body tab, Wardrobe), built there from the parts.
MESH_ITEM_NOT_READY = "{item}: own mesh not ready — not shown until its mesh is accepted ({reason})"
#: ... the reason of a piece whose garment chain failed for its fsig (only
#: Regenerate in the Wardrobe retries it, ``garments.cached_failure``).
MESH_ITEM_CHAIN_FAILED = "{step} — {error} — Regenerate in the Wardrobe"
#: A dressed view / outfit model of the mesh mode built while the old rule
#: painted an own-mesh piece without a fit into it (the outfit body).
MESH_ITEM_PAINTED_IN = "An own-mesh piece is painted on here — the mesh mode leaves it out"


def dress_text(character_name: str, view: str, *, pieces: Optional[Dict[str, str]],
               items: Optional[list], profile: Optional[Dict[str, Any]] = None,
               mesh_items: Iterable[str] = ()) -> str:
    """What the dressed edit says the figure now wears — "" for an undressed
    combination (nothing worn, or an undressed free-text wardrobe).

    The outfit text of the mesh-input render (``render_outfit(mesh_input=
    True, back_view=view == "back")``), composed as
    ``expression_regen.render_character_image`` composes its "is wearing"
    layer: the pieces, else (nothing structured worn) a dressed free-text
    wardrobe's text; the items follow with their own verb ("holding …").

    ``mesh_items``: own-mesh pieces left out of the texture on this outfit
    (``mesh_items_unpainted`` of ``resolve_mesh_items``' record: the
    effective set, in mesh mode every flagged piece) — left out of the pieces
    BEFORE the renderer resolves ``covers`` / ``partially_covers``, so what
    lies under them is painted (plan 2026-11-09-base-body-phase5 Task 4).
    Pieces that are ALL mesh items leave nothing to paint: "" (never the
    free-text wardrobe)."""
    from app.core.outfit_renderer import render_outfit
    meshed = {str(i) for i in mesh_items or ()}
    worn = {slot: iid for slot, iid in (pieces or {}).items() if iid and str(iid) not in meshed}
    profile = dict(_profile_of(character_name, profile))
    profile["equipped_pieces"] = dict(worn)
    profile["equipped_items"] = list(items or [])
    rendered = render_outfit(profile=profile, equipped_pieces=dict(worn),
                             equipped_items=list(items or []), back_view=view == "back",
                             mesh_input=True)
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


def dress_negative(text: str) -> str:
    """The spike's negative minus the garment terms ``text`` names."""
    kept = [term for term, pattern in DRESS_GARMENT_NEGATIVE
            if not re.search(rf"\b(?:{pattern})\b", text or "", re.IGNORECASE)]
    return ", ".join([DRESS_STYLE_NEGATIVE, *kept])


def dress_prompt(character_name: str, view: str, *, pieces: Optional[Dict[str, str]],
                 items: Optional[list], profile: Optional[Dict[str, Any]] = None,
                 mesh_items: Iterable[str] = (), bald: bool = False) -> Tuple[str, str]:
    """``(prompt, negative)`` of the dressed edit of one base view: the
    spike's edit form "Keep the image exactly as it is: … Only change their
    clothing: they now wear {outfit}." — opened by the view sentence
    ``DRESS_VIEW[view]`` for back/left/right — and its negative without the
    garment words the outfit names. ValueError for an undressed combination
    (that one copies the base images, there is nothing to edit).
    ``mesh_items`` as in ``dress_text``. ``bald`` (``outfit_body_bald``: the
    mesh mode under an own hair mesh) closes the edit with the base body's
    bald head (``BALD_HEAD``) and adds its hair negative (``HAIR_NEGATIVE``)."""
    if view not in BASE_VIEWS:
        raise ValueError(f"unknown base-body view: {view!r}")
    text = dress_text(character_name, view, pieces=pieces, items=items, profile=profile,
                      mesh_items=mesh_items)
    if not text:
        raise ValueError("An undressed combination has no dressed edit")
    negative = dress_negative(text)
    return _edit_prompt(view, text, bald=bald), (f"{negative}, {HAIR_NEGATIVE}" if bald else negative)


def _edit_prompt(view: str, text: str, *, bald: bool = False) -> str:
    """The dressed edit's prompt of one view for the dress text ``text``;
    ``bald`` appends the base body's bald head (``BALD_HEAD``, the same
    words the base front is rendered with)."""
    edit = f"{DRESS_KEEP} Only change their clothing: {text}."
    if bald:
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


def _outfit_end(character_name: str, signature: str, stage: str, error: Optional[str]) -> None:
    """End a stage: a failure is stored for the signature; a success clears
    a failure of the same stage (a model success clears every failure)."""
    from app.core.timeutils import utc_now
    with _status_lock:
        if _outfit_running.get((character_name, stage)) == signature:
            _outfit_running.pop((character_name, stage), None)
        key = (character_name, signature)
        if error is not None:
            _outfit_failed[key] = {"stage": stage, "error": error, "failed_at": utc_now()}
        elif stage == "model" or (_outfit_failed.get(key) or {}).get("stage") == stage:
            _outfit_failed.pop(key, None)


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


# --- Own-mesh outfit pieces (plan 2026-11-09-base-body-phase5-mesh-items, Task 4) ---
#
# The record (sidecar ``mesh_items`` of every dressed view and outfit model,
# ``resolve_mesh_items``): ``intended`` = the flagged worn pieces,
# ``effective`` = those with an accepted fit when it was made, ``warnings``,
# ``mode`` = the outfit body mode it was made under (``mesh_items_mode``),
# ``unpainted`` = the pieces the dress text LEFT OUT (``mesh_items_unpainted``)
# and ``missing`` = item -> reason for the left-out pieces without a fit.
# Which pieces are left out depends on the mode:
#
# * ``retexture`` (ruling P1: never a bare body where it belongs, never
#   painted AND a mesh): the effective set — a CLOTHING piece without a fit
#   is painted on until its mesh is accepted (painting is one cheap texture
#   step) — plus every FOOTWEAR piece (spec 2026-11-10-footwear-rigid-shoes
#   § 9.1: footwear is never painted, in this mode too; without an accepted
#   fit it is missing, bare feet, until the fit is accepted). A record from
#   before Task 16 of that plan has no ``mode``/``unpainted`` key: its
#   unpainted set is ``effective``.
# * ``mesh`` (ruling 2026-11-10): EVERY intended piece (``unpainted`` =
#   ``intended``) — painting a piece there would mesh it into an outfit body
#   (mesh + rig hub jobs) that is thrown away once the piece's own mesh is
#   accepted. A piece without a fit is MISSING from the outfit model until
#   then (``missing``: item -> reason, ``MESH_ITEM_NOT_READY``); the tsig and
#   the body id do not change when it gets one, so its acceptance only
#   assembles it onto the existing body (``after_mesh_item_ready``).
#
# The missing pieces are judged NOW, never from the record alone
# (``mesh_items_missing``): a piece whose fit landed since is simply grafted.

def mesh_items_intended(record: Dict[str, Any]) -> List[str]:
    """The own-mesh pieces a dressed view / outfit model was made for
    (sidecar ``mesh_items.intended``), [] when it records none."""
    mesh = record.get("mesh_items") if isinstance(record, dict) else None
    if not isinstance(mesh, dict):
        return []
    return [str(i) for i in mesh.get("intended") or [] if isinstance(i, str) and i]


def mesh_items_unpainted(record: Optional[Dict[str, Any]]) -> List[str]:
    """The own-mesh pieces a dressed view / outfit model LEFT OUT of its dress
    text (block above): the recorded ``unpainted``, else ``effective`` (a
    retexture-mode record from before footwear was left out); sorted, []
    when it records none."""
    mesh = record.get("mesh_items") if isinstance(record, dict) else None
    if not isinstance(mesh, dict):
        return []
    key = "unpainted" if isinstance(mesh.get("unpainted"), list) else "effective"
    return sorted({str(i) for i in mesh.get(key) or [] if isinstance(i, str) and i})


def mesh_items_mode(record: Optional[Dict[str, Any]]) -> str:
    """The outfit body mode a dressed view / outfit model handled its own-mesh
    pieces under: the recorded ``mesh_items.mode``; a record without one is
    from before the mode was written — ``mesh`` when it carries an
    ``unpainted`` list (only mesh-mode records did), else ``retexture``."""
    mesh = record.get("mesh_items") if isinstance(record, dict) else None
    if not isinstance(mesh, dict):
        return RETEXTURE_MODE
    mode = mesh.get("mode")
    if mode in OUTFIT_BODY_MODES:
        return str(mode)
    return MESH_MODE if isinstance(mesh.get("unpainted"), list) else RETEXTURE_MODE


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
    return base_model_sha256(character_name, bsig) if bsig else ""


def mesh_items_ready(character_name: str, record: Dict[str, Any], *, bsig: Optional[str] = None,
                     base_sha: Optional[str] = None) -> List[str]:
    """The pieces a dressed view / outfit model (its sidecar ``record``) left
    painted on that now HAVE an accepted fit on the current base model
    (``base_sha``, else the stored model of ``bsig``, else of the record's
    ``base_signature``) — such a record is stale (``MESH_ITEM_READY``): a
    rebuild drops them from the texture. [] when none (cheap: no fit is read
    without a pending piece)."""
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
    accepted. Judged under the RECORD's mode (``mesh_items_mode``): a
    mesh-mode record's every unpainted piece (ruling 2026-11-10), a
    retexture-mode record's unpainted FOOTWEAR only (spec § 9.1 — its other
    unpainted pieces had a fit when it was made; a clothing piece without
    one was painted on). ``[(item_id, reason)]``, the reason the build
    recorded (``mesh_items.missing``), else ``NO_MESH_FIT`` /
    ``BASE_MODEL_MISSING``. [] for a retexture-mode record without footwear
    left out (one from before Task 16 of the footwear plan too)."""
    mesh = record.get("mesh_items") if isinstance(record, dict) else None
    if not isinstance(mesh, dict):
        return []
    unpainted = mesh_items_unpainted(record)
    if unpainted and mesh_items_mode(record) != MESH_MODE:
        unpainted = _footwear_items(unpainted)
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


def mesh_items_off_rule(character_name: str, record: Dict[str, Any], *, bsig: Optional[str] = None,
                        base_sha: Optional[str] = None, profile: Optional[Dict[str, Any]] = None) -> List[str]:
    """The own-mesh pieces a dressed view / outfit model handled under the
    OTHER outfit body mode's rule (block above) — such a record is stale. In
    mesh mode: the pieces it painted on (``_mesh_items_pending``; made in
    retexture mode, or in mesh mode before the ruling of 2026-11-10 — they
    are in its outfit body's mesh). In retexture mode: the CLOTHING pieces a
    mesh-mode record left out that still have no fit (``mesh_items_missing``;
    they belong painted on) and the FOOTWEAR pieces any record painted on
    (footwear is never painted, spec § 9.1 / § 12: a model that painted the
    heels before Task 16 is rebuilt without them, once — the record it makes
    leaves them out, so it is never off-rule again). [] when none (cheap: no
    profile is read for a record without own-mesh pieces)."""
    if not mesh_items_intended(record):
        return []
    pending = _mesh_items_pending(record)
    if outfit_body_mode(character_name, profile=profile) == MESH_MODE:
        return pending
    footwear = set(_footwear_items(pending))
    missing = [item_id for item_id, _reason in mesh_items_missing(character_name, record, bsig=bsig,
                                                                  base_sha=base_sha)]
    return sorted(footwear | (set(missing) - set(_footwear_items(missing))))


def _own_mesh_kinds(character_name: str, pieces: Optional[Dict[str, str]], *,
                    profile: Dict[str, Any]) -> Dict[str, str]:
    """``{item id: garment kind}`` of the flagged worn own-mesh pieces of
    ``pieces`` (``garment_set.worn_garments`` ∩ ``OWN_MESH_PIECE_KINDS``), in
    worn order — the ``intended`` set of ``resolve_mesh_items``."""
    from app.core import garment_set
    from app.models.inventory import get_item
    kinds = {item_id: garment_set.garment_kind_of(get_item(item_id))
             for item_id in garment_set.worn_garments(character_name, profile=profile, pieces=dict(pieces or {}))}
    return {item_id: kind for item_id, kind in kinds.items() if kind in garment_set.OWN_MESH_PIECE_KINDS}


def _unpainted_rule(kinds: Dict[str, str], effective: Iterable[str], *, mesh_mode: bool) -> List[str]:
    """The pieces the dress text leaves out (block above): every intended
    piece in mesh mode; in retexture mode the effective ones plus every
    footwear piece."""
    from app.core import garment_set
    if mesh_mode:
        return list(kinds)
    return sorted(set(effective) | {i for i, kind in kinds.items() if kind == garment_set.FOOTWEAR})


def predicted_mesh_items(character_name: str, pieces: Optional[Dict[str, str]], *, mode: str,
                         profile: Optional[Dict[str, Any]] = None, bsig: Optional[str] = None) -> Dict[str, Any]:
    """``resolve_mesh_items`` READ-ONLY, for the outfit body ``mode``: no
    garment chain runs, ``effective`` = the intended pieces with an accepted
    fit on the base model of ``bsig`` NOW. ``{intended, effective, mode,
    unpainted}``, ``{}`` without own-mesh pieces. What a build of ``pieces``
    would record if no chain changed anything meanwhile — the artefact GC's
    prediction of an outfit's texture (``predicted_texture_signatures``)."""
    from app.core import garment_store
    profile = _profile_of(character_name, profile)
    kinds = _own_mesh_kinds(character_name, pieces, profile=profile)
    if not kinds:
        return {}
    base_sha = base_model_sha256(character_name, bsig or base_signature(character_name, profile=profile))
    effective = [item_id for item_id in kinds if base_sha
                 and garment_store.accepted_fit(character_name, item_id, base_model_sha=base_sha) is not None]
    return {"intended": list(kinds), "effective": effective, "mode": mode,
            "unpainted": _unpainted_rule(kinds, effective, mesh_mode=mode == MESH_MODE)}


def resolve_mesh_items(character_name: str, pieces: Optional[Dict[str, str]], *,
                       profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Which worn own-mesh pieces an outfit of ``pieces`` gets as their own
    garment mesh — ``{}`` without any (off the pipeline too: the token and
    every record stay as before).

    Runs the garment chain of every flagged worn piece through the
    character's FIFO and waits (``garments.run_queued``; cached by fsig, a
    finished chain returns at once; footwear runs its shoe chain there,
    spec § 12). ``intended`` = the flagged worn pieces
    (``garment_set.worn_garments``, ``garment_set.OWN_MESH_PIECE_KINDS``),
    ``effective`` = those with an accepted fit on the current base model
    (``garment_store.accepted_fit``), ``mode`` = the outfit body mode,
    ``unpainted`` = the pieces the dress text leaves out, ``missing`` = item
    -> reason for the left-out pieces without a fit.

    Retexture mode: a CLOTHING piece left out of ``effective`` stays painted
    on, one ``MESH_ITEM_PAINTED`` warning each with the chain's error (ruling
    P1: never a bare body where it belongs, never painted AND a mesh). A
    FOOTWEAR piece is never painted (spec 2026-11-10-footwear-rigid-shoes
    § 9.1): ``unpainted`` = ``effective`` + the intended footwear, and a
    footwear piece without a fit is ``missing`` — no warning is recorded for
    it, ``_mesh_warnings`` judges it live (``MESH_ITEM_NOT_READY``).

    Mesh mode (``outfit_body_mode``, ruling 2026-11-10): no flagged piece is
    painted — ``unpainted`` = ``intended``, so the dress text, the tsig and
    the outfit body hold the painted pieces only and stay the same when a
    piece's mesh is accepted later (then it is only assembled onto that
    body, ``after_mesh_item_ready``: no second body, no hub job). A piece
    without a fit is missing from the outfit model meanwhile: ``missing``
    (item -> reason) and one ``MESH_ITEM_NOT_READY`` warning each.

    A chain that failed for its current fsig is not run again here
    (``garments.run_queued`` skips it, fix round 1): the warning says to
    Regenerate in the Wardrobe (``MESH_ITEM_FAILED`` /
    ``MESH_ITEM_CHAIN_FAILED``)."""
    from app.core import garment_set, garment_store, garments
    from app.models.inventory import get_item
    profile = _profile_of(character_name, profile)
    kinds = _own_mesh_kinds(character_name, pieces, profile=profile)
    intended = list(kinds)
    if not intended:
        return {}
    mode = outfit_body_mode(character_name, profile=profile)
    mesh_mode = mode == MESH_MODE
    grafted = [item_id for item_id in intended if kinds[item_id] in garment_set.GRAFTED_PIECE_KINDS]
    results = garments.run_queued(character_name, grafted) if grafted else {}
    base_sha = base_model_sha256(character_name, base_signature(character_name, profile=profile))
    effective: List[str] = []
    warnings: List[str] = []
    missing: Dict[str, str] = {}
    for item_id in intended:
        fit = garment_store.accepted_fit(character_name, item_id, base_model_sha=base_sha) if base_sha else None
        if fit is not None:
            effective.append(item_id)
            continue
        result = results.get(item_id) or {}
        reason = str(result.get("error") or "") or (NO_MESH_FIT if base_sha else BASE_MODEL_MISSING)
        name = str((get_item(item_id) or {}).get("name") or item_id)
        failed = bool(result.get("step") and result.get("error"))
        footwear = kinds[item_id] == garment_set.FOOTWEAR
        if mesh_mode or footwear:
            # The chain failed for this fsig: cached, only Regenerate retries.
            missing[item_id] = (MESH_ITEM_CHAIN_FAILED.format(step=result["step"], error=reason) if failed
                                else reason)
            if mesh_mode:
                warnings.append(MESH_ITEM_NOT_READY.format(item=name, reason=missing[item_id]))
        elif failed:
            warnings.append(MESH_ITEM_FAILED.format(item=name, reason=f"{result['step']} — {reason}"))
        else:
            warnings.append(MESH_ITEM_PAINTED.format(item=name, reason=reason))
    unpainted = _unpainted_rule(kinds, effective, mesh_mode=mesh_mode)
    logger.info("Own-mesh pieces of %s (%s mode): intended %s, effective %s, missing %s", character_name,
                mode, intended, effective, sorted(missing))
    return {"intended": intended, "effective": effective, "warnings": warnings, "mode": mode,
            "unpainted": unpainted, "missing": missing}


def after_mesh_item_ready(character_name: str, item_id: str) -> bool:
    """A garment run accepted a fit of the own-mesh piece ``item_id``.

    Mesh mode (ruling 2026-11-10): when the CURRENT outfit model stands on
    an outfit body and left that piece out (``mesh_items_unpainted``), the
    body stays — the piece is only assembled onto it
    (``garment_assembly.schedule``: its fit on the body, CPU, then the
    graft). No dressed view, no body rebuild, no hub job. A FOOTWEAR piece
    the current model left out is assembled the same way in EITHER mode
    (spec § 9.1: it is never painted, so the model is current without it).

    Otherwise, when the CURRENT outfit's dressed front (or its model) left
    that piece painted on, the outfit's mesh inputs are rendered again
    (``dressed_image`` now calls them stale, ``MESH_ITEM_READY``) and the
    model is rebuilt after them (``model_refs`` →
    ``model3d.maybe_auto_generate_for_outfit``).
    True when either was asked for. Never raises."""
    try:
        from app.core import model3d
        from app.core.model_refs import current_outfit_state, find_ref_image, trigger_now
        profile = _profile_of(character_name, None)
        if not is_base_pipeline(character_name, profile=profile):
            return False
        signature = current_outfit_state(character_name)[2]
        bsig = base_signature(character_name, profile=profile)
        base_sha = base_model_sha256(character_name, bsig)
        path = model3d.find_model3d(character_name, signature, include_stale=True)
        model_meta = model3d._read_sidecar(path) if path is not None else {}
        if item_id in mesh_items_unpainted(model_meta) and _footwear_items([item_id]):
            from app.core import garment_assembly
            logger.info("Footwear %s of %s has a fit now: assembled onto the model of outfit %s (never painted, "
                        "no rebuild)", item_id, character_name, signature)
            garment_assembly.schedule(character_name, signature)
            return True
        if (outfit_body_mode(character_name, profile=profile) == MESH_MODE
                and model_meta.get("outfit_body_mode") == MESH_MODE
                and item_id in mesh_items_unpainted(model_meta)
                and not _mesh_items_pending(model_meta)):
            from app.core import garment_assembly
            logger.info("Own-mesh piece %s of %s has a fit now: assembled onto outfit body %s of outfit %s "
                        "(no body rebuild)", item_id, character_name, model_meta.get("body_id"), signature)
            garment_assembly.schedule(character_name, signature)
            return True
        records = [_ref_sidecar(find_ref_image(character_name, "tpose", signature))]
        if path is not None:
            records.append(model_meta)
        if not any(item_id in mesh_items_ready(character_name, r, base_sha=base_sha) for r in records):
            return False
        logger.info("Own-mesh piece %s of %s has a fit now: outfit %s is rendered again without it",
                    item_id, character_name, signature)
        trigger_now(character_name, kinds=("tpose",), force=False)
        return True
    except Exception:  # noqa: BLE001 — a trigger never breaks the garment run
        logger.exception("Outfit rebuild after the fit of %s/%s failed", character_name, item_id)
        return False


def after_piece_detail_change(item_id: str) -> List[str]:
    """A piece's ``exposed_detail`` changed: every character on the pipeline
    wearing it gets its outfit model rebuilt (``variant_current`` now calls
    the stored one stale; ``model3d.maybe_auto_generate_for_outfit``). 2D
    renders stay. Returns the characters whose rebuild was asked for."""
    from app.core import model3d
    from app.models.character import get_character_profile, list_available_characters
    started = []
    for name in list_available_characters():
        try:
            profile = get_character_profile(name) or {}
            if item_id not in (profile.get("equipped_pieces") or {}).values():
                continue
            if not is_base_pipeline(name, profile=profile):
                continue
            model3d.maybe_auto_generate_for_outfit(name)
            started.append(name)
        except Exception as e:  # noqa: BLE001 — one character never blocks the rest
            logger.warning("Outfit rebuild after a detail change failed for %s: %s", name, e)
    return started


def _draft_view(view: str) -> str:
    if view not in DRAFT_VIEWS:
        raise ValueError(f"no draft for the base-body view {view!r}")
    return view


def draft_prompt(character_name: str, view: str, *, profile: Optional[Dict[str, Any]] = None,
                 outfit_text: str = DRAFT_OUTFIT_TEXT) -> Tuple[str, str]:
    """``(prompt, negative)`` of the DRAFT of a two-step view (back, left,
    right): the view's ``DRAFT_PROMPTS`` sentence with ``outfit_text`` in its
    slot (an outfit: ``DRAFT_OUTFIT_TEXT``; an own-mesh piece's worn back:
    ``garment_clothing.DRAFT``) — the whole prompt of the edit, no style and
    no character block (the dressed front is the reference). Negative:
    ``DRAFT_NEGATIVE`` + the slots' ``base_body_negative`` texts."""
    profile = _profile_of(character_name, profile)
    text = (outfit_text or "").strip().rstrip(".").strip()
    return (DRAFT_PROMPTS[_draft_view(view)].format(outfit=text),
            base_negative(character_name, profile=profile, head=DRAFT_NEGATIVE))


def cut_out(path: Path):
    """The RGBA cut-out of an image: as stored when it already carries a
    matte (some alpha below ``FIT_FIGURE_ALPHA``), else the mesh-input matte
    (BiRefNet-DIS, ``character.MESH_INPUT_REMBG_MODEL``)."""
    import io
    from PIL import Image
    from app.models.character import MESH_INPUT_REMBG_MODEL, run_rembg
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    if image.getchannel("A").getextrema()[0] < FIT_FIGURE_ALPHA:
        return image
    with Image.open(io.BytesIO(run_rembg(path.read_bytes(), MESH_INPUT_REMBG_MODEL))) as matted:
        return matted.convert("RGBA")


def fit_canvas(base, draft, size: Tuple[int, int]):
    """``(base canvas, draft canvas)`` of the fit: two transparent RGBA
    images of one size — height = the base cut-out's, width = the wider of
    the base cut-out and that height at the render's aspect ``size`` — the
    base pasted centred, the draft's figure (alpha >= ``FIT_FIGURE_ALPHA``)
    cropped, scaled to the base figure's height and pasted with its centre on
    the base figure's centre. A cut-out without a figure: ValueError."""
    from PIL import Image
    base_box = base.getchannel("A").point(lambda a: 255 if a >= FIT_FIGURE_ALPHA else 0).getbbox()
    draft_box = draft.getchannel("A").point(lambda a: 255 if a >= FIT_FIGURE_ALPHA else 0).getbbox()
    if base_box is None or draft_box is None:
        raise ValueError("fit reference without a figure")
    height = base.height
    figure = draft.crop(draft_box)
    scale = (base_box[3] - base_box[1]) / figure.height
    figure = figure.resize((max(1, round(figure.width * scale)), base_box[3] - base_box[1]), Image.LANCZOS)
    width = max(base.width, round(height * size[0] / size[1]), figure.width)
    left = (width - base.width) // 2
    base_canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    base_canvas.paste(base, (left, 0), base)
    centre_x = left + (base_box[0] + base_box[2]) / 2
    draft_canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draft_canvas.paste(figure, (round(centre_x - figure.width / 2), base_box[1]), figure)
    return base_canvas, draft_canvas


@contextmanager
def fit_references(base_back: Path, draft: Path, refs_dir: Path, size: Tuple[int, int], *,
                   background: Optional[Tuple[int, int, int]] = None):
    """``(base reference, draft reference, canvas size)``: the ``fit_canvas``
    pair of the cut-outs, saved under their own names in a private
    ``.fitref_*`` dir inside ``refs_dir`` (the reference containment gate
    accepts it; the fit's sidecar records the references by name). The fit
    renders at the canvas size — the base back's height — because the
    retexture worker registers it pixel-wise against the base back.
    ``background``: both canvases flattened onto that colour (the garment
    chain keeps its images on neutral grey); None = transparent, as the
    outfit fit was measured."""
    import tempfile
    from PIL import Image
    base_canvas, draft_canvas = fit_canvas(cut_out(base_back), cut_out(draft), size)
    if background is not None:
        def flat(image):
            out = Image.new("RGBA", image.size, tuple(background) + (255,))
            out.alpha_composite(image)
            return out.convert("RGB")
        base_canvas, draft_canvas = flat(base_canvas), flat(draft_canvas)
    with tempfile.TemporaryDirectory(prefix=".fitref_", dir=refs_dir, ignore_cleanup_errors=True) as tmp:
        base_out = Path(tmp) / "base" / f"{base_back.stem}.png"
        draft_out = Path(tmp) / "draft" / f"{draft.stem}.png"
        for out, image in ((base_out, base_canvas), (draft_out, draft_canvas)):
            out.parent.mkdir()
            image.save(out)
        yield base_out, draft_out, base_canvas.size


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


def dressed_image(character_name: str, view: str, signature: str, bsig: str) -> Optional[Path]:
    """The stored dressed image of one view of an outfit, or None — only one
    edited from the CURRENT base view counts (base signature ``bsig`` and
    the base view file's content; an edit of an older base body, or of a
    re-rendered one, does not line up with it). Only ``dressed_views()`` are
    dressed; a side view is None while the side views are off. A view that
    left an own-mesh piece painted on which has an accepted fit now
    (``mesh_items_ready``) does not count either, nor one whose own-mesh
    pieces follow the other outfit body mode's rule (``mesh_items_off_rule``:
    in mesh mode a piece painted on, in retexture mode a mesh-mode view that
    left out a piece still without a fit)."""
    from app.core.model_refs import find_ref_image
    if view not in dressed_views():
        return None
    path = find_ref_image(character_name, _kind(view), signature)
    if path is None:
        return None
    meta = _ref_sidecar(path)
    if (meta.get("base_signature") != bsig or meta.get("base_image_sha256")
            != file_sha256(find_ref_image(character_name, _kind(view), bsig))):
        return None
    if mesh_items_ready(character_name, meta, bsig=bsig):
        return None  # an own-mesh piece painted on here has its garment mesh now
    if mesh_items_off_rule(character_name, meta, bsig=bsig):
        return None  # made under the other mode's own-mesh rule
    return path


def fit_gate_warning(attempts: int, record: Dict[str, Any], view: str = "back") -> str:
    """The status warning of a dressed two-step view kept although no
    attempt passed; ``record`` is the kept attempt's ``{"guard", "noise"}``."""
    reasons = []
    if not (record.get("guard") or {}).get("ok", True):
        reasons.append("turned toward the camera")
    if not (record.get("noise") or {}).get("ok", True):
        reasons.append("grainy")
    what = " and ".join(reasons) or "off"
    return (f"Dressed {view} may be {what} ({view} check failed after {attempts} "
            f"attempt{'' if attempts == 1 else 's'})")


def best_fit_attempt(results: List[Dict[str, Any]]) -> Tuple[int, bool]:
    """``(index, passed)``: the first attempt passing both checks, else the
    one that keeps its view (guard) with the lowest noise score."""
    for i, result in enumerate(results):
        if result["ok"]:
            return i, True

    def rank(i: int):
        result = results[i]
        noise = (result.get("noise") or {}).get("score")
        return (not (result.get("guard") or {}).get("ok", True),
                noise if noise is not None else float("inf"), i)
    return min(range(len(results)), key=rank), False


def _dress_common(view: str, *, pieces: Optional[Dict[str, str]], items: Optional[list],
                  profile: Dict[str, Any], size: Tuple[int, int]) -> Dict[str, Any]:
    """The render arguments a two-step view's draft and fit share."""
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
    no character block), occasion ``DRESS_OCCASIONS[view][0]``, the render
    arguments ``common`` (``_dress_common``). None when the render returned
    nothing; render errors propagate. Shared by the outfit's dressed views
    (``_dress_view``) and an own-mesh piece's worn back
    (``garment_images``)."""
    from app.core import expression_regen
    from app.core.model_refs import neutral_view_reference
    text, negative = prompt
    with neutral_view_reference(front, refs_dir) as reference:
        return expression_regen.render_character_image(
            character_name, output_stem=stem, bare_prompt=text, extra_negative=negative,
            occasion=DRESS_OCCASIONS[view][0], reference_image=reference,
            sidecar_extra=sidecar_extra, **common)


def render_fit(character_name: str, view: str, *, stem: Path, base_reference: Path,
               draft_reference: Path, canvas: Tuple[int, int], extra: Dict[str, Any],
               common: Dict[str, Any], postprocess: bool = True, prompt: str = FIT_PROMPT,
               prompt_keywords: Optional[str] = None) -> Optional[Path]:
    """One FIT render of a two-step view into ``stem``: ``prompt`` (the
    outfit's ``FIT_PROMPT``; an own-mesh piece's worn back names the piece,
    ``garment_clothing.fit_prompt``) on the base reference (image 1) with
    the draft reference (image 2), use case ``FIT_USE_CASE``, occasion
    ``DRESS_OCCASIONS[view][1]``, at the canvas size. ``prompt_keywords``:
    the tag form a keywords-family backend gets instead (None = ``prompt``
    everywhere). ``postprocess=False`` keeps the backend's full frame (the
    garment chain crops it back onto the base view). None when the render
    returned nothing; render errors propagate."""
    from app.core import expression_regen
    return expression_regen.render_character_image(
        character_name, output_stem=stem, bare_prompt=prompt,
        **({"bare_prompt_keywords": prompt_keywords} if prompt_keywords else {}),
        occasion=DRESS_OCCASIONS[view][1], reference_image=base_reference,
        extra_reference_images=[draft_reference], sidecar_extra=extra,
        **{**common, "image_use_case": FIT_USE_CASE,
           "override_width": canvas[0], "override_height": canvas[1], "postprocess": postprocess})


def _fit_attempt(character_name: str, view: str, *, stem: Path, base_reference: Path,
                 draft_reference: Path, canvas: Tuple[int, int], extra: Dict[str, Any],
                 common: Dict[str, Any], base_views: Dict[str, Optional[Path]]
                 ) -> Optional[Tuple[Path, Dict[str, Any]]]:
    """One FIT render of a two-step view into ``stem`` (``render_fit``) and
    its gate result ``{"ok", "guard", "noise"}`` (head ``view_guard`` against
    the base views, ``base_body_gates.noise_gate`` against the base view) —
    None when the render returned nothing. Render errors propagate."""
    from app.core import base_body_gates
    path = render_fit(character_name, view, stem=stem, base_reference=base_reference,
                      draft_reference=draft_reference, canvas=canvas, extra=extra, common=common)
    if path is None:
        return None
    guard = view_guard(view, path, base_views)
    noise = base_body_gates.noise_gate(path, base_views[view])
    return path, {"ok": bool(guard["ok"] and noise["ok"]), "guard": guard, "noise": noise}


def _fit_extra(view: str, bsig: str, base_view: Path, draft: Path,
               mesh_items: Optional[Dict[str, Any]] = None,
               texture: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The sidecar fields of a fit: the base it was fitted onto, its draft —
    the own-mesh record of its outfit (``mesh_items``, the front's) and its
    texture (``texture_signature``, ``dress_text``)."""
    extra = {"base_signature": bsig, "dressed": True, "base_image_sha256": file_sha256(base_view),
             f"{view}_draft": draft.name, f"{view}_draft_sha256": file_sha256(draft)}
    if mesh_items:
        extra["mesh_items"] = mesh_items
    extra.update(texture or {})
    return extra


def _dress_view(character_name: str, view: str, *, signature: str, bsig: str,
                pieces: Optional[Dict[str, str]], items: Optional[list], profile: Dict[str, Any],
                front: Path, base_views: Dict[str, Optional[Path]], refs_dir: Path,
                size: Tuple[int, int], mesh_items: Optional[Dict[str, Any]] = None,
                texture: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Path], Optional[str]]:
    """A dressed back or side view in two steps. ``(stored path, warning)``;
    raises ``OutfitError`` with the step that failed. The view follows the
    dressed front, own-mesh pieces included: what the front left out (its
    ``mesh_items``) is not in the draft's reference either — no outfit text
    is sent — and the record goes into the draft's and the fit's sidecar.

    1. DRAFT (occasion ``DRESS_OCCASIONS[view][0]``: ``outfit_back_draft`` /
       ``outfit_side_draft``): an edit of the dressed ``front`` (on grey, the
       only reference) with ``draft_prompt`` (the view's ``DRAFT_PROMPTS``
       sentence, empty style ``DRAFT_USE_CASES``, no character block); stored
       as ``model_refs/drafts/tpose_<view>_<sig>``.
    2. FIT (occasion ``outfit_back`` / ``outfit_side``, use case
       ``FIT_USE_CASE``): an edit of the cut-out base view (image 1) with the
       cut-out draft scaled onto it (image 2, ``fit_references``), prompt
       ``FIT_PROMPT`` and nothing else (user decision 2026-11-09), rendered
       at the canvas size (the base view's height, not the T-pose default;
       the draft renders at the dressed front's size). The render comes back
       on black and gets the mesh-input matte. Up to ``FIT_ATTEMPTS``
       renders (``_fit_attempt``), each staged in a private ``.fitgate_*``
       dir inside ``model_refs`` and checked by the head ``view_guard`` (a
       fit that turned toward the camera) and ``base_body_gates.noise_gate``
       against the base view (a grainy seed); the first passing attempt —
       else ``best_fit_attempt`` — is moved onto ``tpose_<view>_<sig>`` with
       every attempt's numbers in its sidecar (``fit_gate``, with
       ``warning`` when none passed)."""
    import tempfile
    from app.core import base_body_gates
    kind = _kind(view)
    drafts = refs_dir / DRAFT_DIR
    drafts.mkdir(exist_ok=True)
    common = _dress_common(view, pieces=pieces, items=items, profile=profile, size=size)
    draft = render_draft(
        character_name, view, stem=drafts / f"{kind}_{signature}", front=front, refs_dir=refs_dir,
        prompt=draft_prompt(character_name, view, profile=profile), profile=profile, common=common,
        sidecar_extra={"base_signature": bsig, "dressed": True, f"{view}_draft": True,
                       "front_sha256": file_sha256(front),
                       **({"mesh_items": mesh_items} if mesh_items else {}), **(texture or {})})
    if draft is None:
        raise OutfitError(f"Dressed {view} draft failed")
    base_view = base_views[view]
    extra = _fit_extra(view, bsig, base_view, draft, mesh_items, texture)
    final = refs_dir / f"{kind}_{signature}"
    attempts: List[Tuple[Path, Dict[str, Any]]] = []
    with tempfile.TemporaryDirectory(prefix=".fitgate_", dir=refs_dir, ignore_cleanup_errors=True) as staging, \
            fit_references(base_view, draft, refs_dir, size) as (base_reference, draft_reference, canvas):
        for n in range(1, FIT_ATTEMPTS + 1):
            stem = Path(staging) / f"attempt{n}" / final.name
            stem.parent.mkdir()
            try:
                attempt = _fit_attempt(character_name, view, stem=stem, base_reference=base_reference,
                                       draft_reference=draft_reference, canvas=canvas, extra=extra,
                                       common=common, base_views=base_views)
            except Exception as e:  # noqa: BLE001 — keep what was rendered
                if not attempts:
                    raise
                logger.warning("Dressed %s %s (%s): fit attempt %d failed: %s", view, character_name,
                               signature, n, e)
                break
            if attempt is None:
                if not attempts:
                    raise OutfitError(f"Dressed {view} edit failed")
                break
            attempts.append(attempt)
            result = attempt[1]
            logger.info("Dressed %s %s (%s): fit attempt %d %s (guard %s, noise %s/%s)", view, character_name,
                        signature, n, "passed" if result["ok"] else "failed", result["guard"].get("best"),
                        result["noise"].get("score"), result["noise"].get("limit"))
            if result["ok"]:
                break
        chosen, passed = best_fit_attempt([r for _p, r in attempts])
        warning = None if passed else fit_gate_warning(len(attempts), attempts[chosen][1], view)
        record = {"ok": passed, "chosen": chosen + 1, "noise_limit": base_body_gates.NOISE_LIMIT,
                  "attempts": [r for _p, r in attempts], "warning": warning}
        stored = _publish_staged(attempts[chosen][0], final, record, key="fit_gate")
    return stored, warning


def view_delta_e(proof: Optional[Dict[str, Any]], view: str) -> Optional[float]:
    """``views.<view>.dressed_alignment.unchanged_delta_e`` of a retexture
    proof (Lab dE between the registered dressed view and its base view on
    the regions the edit left unchanged), None when the proof has none."""
    try:
        value = proof["views"][view]["dressed_alignment"]["unchanged_delta_e"]  # type: ignore[index]
    except (KeyError, TypeError):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return float(value)


def _refit_back(character_name: str, *, signature: str, bsig: str, back: Path, profile: Dict[str, Any],
                base_views: Dict[str, Optional[Path]], first_proof: Dict[str, Any],
                retexture) -> Tuple[Dict[str, Any], Optional[Tuple[Dict[str, Any], Path]]]:
    """A second fit of the dressed back after the worker registered it
    poorly (``view_delta_e(first_proof, "back") > BACK_REFIT_DELTA_E``).

    One more ``_fit_attempt`` from the STORED draft (it must still be the one
    the back was fitted from: ``back_draft_sha256`` of the back's sidecar),
    staged in a private ``.fitgate_*`` dir. A fit that turned toward the
    camera (``view_guard``) is dropped without a worker run. Otherwise
    ``retexture(fit path) -> (proof, out glb)`` runs the worker with that
    back; the refit is kept only when its back ``unchanged_delta_e`` is
    lower — then it is published onto ``tpose_back_<sig>`` (sidecar
    ``fit_gate`` = the back's attempts plus this one, chosen = this one;
    ``back_refit`` = the record below).

    Returns ``(record, better)``: ``record`` = ``{"limit", "attempts":
    [{"unchanged_delta_e"}, {"unchanged_delta_e"?, "gate"?, "error"?}],
    "chosen": 1|2, "skipped"?}``; ``better`` = the refit's ``(proof, out
    glb)`` when it was kept, else None. Never raises for a failed render or
    worker run — the first result stands."""
    import tempfile
    from app.core import base_body_gates
    from app.core.model3d import _ref_manifest
    from app.core.model_refs import _tpose_size
    first = view_delta_e(first_proof, "back")
    record: Dict[str, Any] = {"limit": BACK_REFIT_DELTA_E, "attempts": [{"unchanged_delta_e": first}],
                              "chosen": 1}
    meta = _ref_sidecar(back)
    draft = draft_path(character_name, "back", signature)
    if draft is None or not meta.get("back_draft_sha256") or file_sha256(draft) != meta["back_draft_sha256"]:
        record["skipped"] = "the back's draft is missing or changed"
        return record, None
    base_back = base_views.get("back")
    if base_back is None:
        record["skipped"] = "base back missing"
        return record, None
    manifest = _ref_manifest(back) or {}
    pieces, items = manifest.get("pieces") or {}, manifest.get("items") or []
    mesh_profile = deepcopy(profile)
    mesh_profile["equipped_pieces"] = dict(pieces)
    mesh_profile["equipped_items"] = list(items)
    size = _tpose_size()
    common = _dress_common("back", pieces=pieces, items=items, profile=mesh_profile, size=size)
    refs_dir = back.parent
    final = refs_dir / f"tpose_back_{signature}"
    entry: Dict[str, Any] = {}
    record["attempts"].append(entry)
    try:
        with tempfile.TemporaryDirectory(prefix=".fitgate_", dir=refs_dir, ignore_cleanup_errors=True) as staging, \
                fit_references(base_back, draft, refs_dir, size) as (base_reference, draft_reference, canvas):
            stem = Path(staging) / "refit" / final.name
            stem.parent.mkdir()
            attempt = _fit_attempt(character_name, "back", stem=stem, base_reference=base_reference,
                                   draft_reference=draft_reference, canvas=canvas,
                                   extra=_fit_extra("back", bsig, base_back, draft,
                                                    meta.get("mesh_items") if isinstance(
                                                        meta.get("mesh_items"), dict) else None,
                                                    {k: meta[k] for k in ("texture_signature", "dress_text")
                                                     if k in meta}),
                                   common=common, base_views=base_views)
            if attempt is None:
                entry["error"] = "the refit rendered nothing"
                return record, None
            path, gate = attempt
            entry["gate"] = gate
            if not gate["guard"].get("ok", True):
                entry["error"] = "turned toward the camera"
                return record, None
            proof, out = retexture(path)
            second = view_delta_e(proof, "back")
            entry["unchanged_delta_e"] = second
            logger.info("Dressed back %s (%s): refit after dE %s -> dE %s", character_name, signature,
                        first, second)
            if second is None or (first is not None and second >= first):
                return record, None
            record["chosen"] = 2
            previous = meta.get("fit_gate") or {}
            gates = [*(previous.get("attempts") or []), gate]
            fit_gate = {"ok": bool(gate["ok"]), "chosen": len(gates),
                        "noise_limit": base_body_gates.NOISE_LIMIT, "attempts": gates,
                        "warning": None if gate["ok"] else fit_gate_warning(len(gates), gate)}
            sidecar = path.with_suffix(".json")
            staged = _ref_sidecar(path)
            staged["fit_gate"] = fit_gate
            sidecar.write_text(json.dumps(staged, ensure_ascii=False, indent=2), encoding="utf-8")
            if _publish_staged(path, final, record, key="back_refit") is None:
                record["chosen"] = 1
                entry["error"] = "model_refs is gone"
                return record, None
            return record, (proof, out)
    except Exception as e:  # noqa: BLE001 — the first back stands
        entry["error"] = str(e) or type(e).__name__
        record["chosen"] = 1
        logger.warning("Dressed back %s (%s): refit failed: %s", character_name, signature, e)
        return record, None


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
                     "texture_signature", "created_at")


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
    return (record.get("base_signature") == bsig and bool(record.get("base_image_sha256"))
            and record.get("base_image_sha256") == file_sha256(base_view))


def _store_texture_views(character_name: str, signature: str, tsig: str, views: Iterable[str],
                         texts: Optional[Dict[str, str]] = None) -> List[str]:
    """Publish the outfit's dressed views ``views`` (and their drafts) into
    the texture store under ``tsig`` — the store copy drops the outfit's
    own keys (``_OUTFIT_VIEW_KEYS``) and names the ``texture_signature`` and,
    when given, the view's ``dress_text``. Returns the views stored."""
    from app.core.model_refs import find_ref_image
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
                         base_views: Dict[str, Optional[Path]]) -> Optional[Path]:
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
    from app.core.model_refs import get_model_refs_dir
    front_text = texts.get("front") or ""
    if not front_text:
        return None
    prompt = _edit_prompt("front", front_text)
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
    logger.info("Texture %s of %s: adopting the dressed views %s of outfit %s", tsig, character_name, views, key)
    _store_texture_views(character_name, key, tsig, views, texts)
    return _store_front(character_name, tsig, bsig, base_views.get("front"))


def _reuse_texture_views(character_name: str, *, signature: str, tsig: str, bsig: str, todo: List[str],
                         texts: Dict[str, str], base_views: Dict[str, Optional[Path]],
                         pieces: Optional[Dict[str, str]], items: Optional[list], profile: Dict[str, Any],
                         mesh: Dict[str, Any]) -> Dict[str, Path]:
    """Copy the views of ``todo`` the texture store holds for ``tsig`` into
    the outfit (``tpose[_<view>]_<signature>`` + drafts), filling the store
    from other outfits first when it has no front (``_adopt_texture_views``).
    A back/side is copied only when it follows the store's front and the
    outfit's front IS that front (copied now or the same content). No image
    job. Returns ``{view: outfit path}`` of the copied views."""
    from app.core.model_refs import find_ref_image, get_model_refs_dir
    front = (_store_front(character_name, tsig, bsig, base_views.get("front"))
             or _adopt_texture_views(character_name, tsig=tsig, bsig=bsig, texts=texts, base_views=base_views))
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


def _sync_texture_views(character_name: str, *, signature: str, tsig: str, bsig: str,
                        base_views: Dict[str, Optional[Path]], texts: Dict[str, str],
                        manifest: Dict[str, Any], profile: Dict[str, Any]) -> None:
    """Before a build of a DRESSED outfit: its views and the store's views
    of ``tsig`` become one set, view by view, the NEWER file winning where
    the contents differ — a view rendered again for another outfit of the
    same texture reaches this one (copied from the store), one rendered
    for this outfit reaches the store. Without a store front the outfit's
    views become the store's. A back/side of the store is taken only while
    it follows the front the outfit then has (``follows_front``)."""
    outfit = {v: dressed_image(character_name, v, signature, bsig) for v in dressed_views()}
    if outfit.get("front") is None:
        return
    store_front = _store_front(character_name, tsig, bsig, base_views.get("front"))
    own = [v for v, p in outfit.items() if p is not None]
    if store_front is None:
        _store_texture_views(character_name, signature, tsig, own, texts)
        return
    kwargs = dict(signature=signature, tsig=tsig, bsig=bsig, texts=texts, base_views=base_views,
                  pieces=manifest.get("pieces") or {}, items=manifest.get("items") or [], profile=profile,
                  mesh=_dict_of(manifest.get("mesh_items")))
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
        if theirs is not None and not (_view_current(_ref_sidecar(theirs), bsig, base_views.get(v)) and follows_front(
                v, _ref_sidecar(theirs), _texture_draft(character_name, v, tsig), front_sha)):
            theirs = None
        if mine is not None and (theirs is None or (file_sha256(mine) != file_sha256(theirs)
                                                    and _newer(mine, theirs))):
            _store_texture_views(character_name, signature, tsig, [v], texts)
        elif theirs is not None and (mine is None or file_sha256(mine) != file_sha256(theirs)):
            _reuse_texture_views(character_name, todo=[v], **kwargs)


def texture_view_shas(character_name: str, signature: str, bsig: str) -> Dict[str, str]:
    """``{view: sha256}`` of the outfit's current dressed views
    (``dressed_image``; "" for a missing one) — what a painted body was
    made from."""
    return {v: file_sha256(dressed_image(character_name, v, signature, bsig)) for v in dressed_views()}


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


def generate_dressed_images(character_name: str, *, pieces: Optional[Dict[str, str]],
                            items: Optional[list], signature: str, force: bool = False,
                            view: Optional[str] = None) -> Dict[str, Optional[str]]:
    """The outfit's mesh-input images on the base-body pipeline. Blocking —
    called from ``model_refs.generate_model_ref_images`` (kind ``tpose``),
    serial per character on its tpose lane.

    Only ``dressed_views()`` (or ``view`` alone — a side view while the side
    views are off is a ValueError with ``SIDE_VIEW_NOT_DRESSED``):

    * front: an EDIT of the base front of the current base signature
      (``reference_image`` = the base front on grey, ``bare_prompt`` =
      ``dress_prompt``, occasion ``outfit_front``, use case ``tpose``);
    * back, then left/right when on: ``_dress_view`` — a draft from the
      dressed front, then a gated fit onto the base view (occasions
      ``outfit_back_draft`` / ``outfit_back``, for the sides
      ``outfit_side_draft`` / ``outfit_side``; use cases ``base_back`` /
      ``base_side`` / ``FIT_USE_CASE``); each needs the dressed front
      (rendered in the same pass, or the stored one — else the status error
      ``DRESSED_FRONT_FIRST``).

    The character's own LoRAs, the dressed negative APPENDED to the use
    case's. Stored as ``tpose_<sig>`` / ``tpose_<view>_<sig>``, sidecar
    ``base_signature``, ``dressed: true`` and ``base_image_sha256`` (the
    edited base view's content, ``dressed_image``). An undressed combination
    copies the base views instead (no GPU run; ``dressed: false``). A
    view that exists for the current base signature is skipped unless
    ``force``. A kept fit warning (``fit_gate_warning``) is in the view's
    sidecar and in ``outfit_info``'s warnings.

    Own-mesh outfit pieces (plan 2026-11-09-base-body-phase5 Task 4): when
    the front is rendered, ``resolve_mesh_items`` first runs the garment
    chain of every flagged worn piece (FIFO per character, cached by fsig)
    and the UNPAINTED set (``mesh_items_unpainted``: in retexture mode the
    effective set — an accepted fit on the current base model —, in mesh
    mode every flagged piece, ruling 2026-11-10) is left out of the pieces
    before the outfit text resolves ``covers`` (``dress_text(mesh_items=…)``)
    — a piece hidden under a mesh dress is painted. Pieces that are all
    mesh items copy the base views (``dressed: false``). Every view's
    sidecar records ``mesh_items: {intended, effective, warnings}`` (mesh
    mode adds ``unpainted`` and ``missing``; the views after the front take
    the front's record); the mesh-input sidecars also carry ``mesh_token``
    (``model_refs.mesh_items_token``). In retexture mode a failed chain
    leaves its piece in the text with a warning (ruling P1); in mesh mode
    the piece is missing from the outfit model until its fit is accepted.

    Texture reuse (plan 2026-11-10-texture-body-reuse, Task 1): the views
    belong to the texture ``tsig`` (``texture_inputs`` — the effective dress
    texts, not the outfit signature). Unless ``force``, a view the texture
    store holds for it (or adopts from another outfit's views that prove the
    same dress text, ``_adopt_texture_views``) is COPIED into the outfit —
    no image job; only the rest is rendered and then published into the
    store. Every view's sidecar names ``texture_signature`` (rendered ones
    also their ``dress_text``).

    Missing base images: the status error ``BASE_IMAGES_MISSING``, nothing
    rendered. Returns ``{kind: path | None}`` for every view it produced."""
    import shutil
    from app.core import expression_regen
    from app.core.model_refs import (_tpose_size, find_ref_image, get_model_refs_dir, mesh_items_token,
                                     mesh_variant, neutral_view_reference)
    if view is not None and view not in BASE_VIEWS:
        raise ValueError(f"unknown base-body view: {view!r}")
    views = dressed_views()
    if view is not None and view not in views:
        raise ValueError(SIDE_VIEW_NOT_DRESSED)
    profile = _profile_of(character_name, None)
    bsig = base_signature(character_name, profile=profile)
    wanted = views if view is None else (view,)
    # Every base view: the wanted ones are edited, all four score the back's
    # view guard.
    base_views = {v: find_ref_image(character_name, _kind(v), bsig) for v in BASE_VIEWS}
    if any(base_views[v] is None for v in wanted):
        logger.warning("Dressed images %s (%s): base images of %s missing", character_name, signature, bsig)
        _outfit_end(character_name, signature, "images", BASE_IMAGES_MISSING)
        return {}
    todo = [v for v in wanted if force or dressed_image(character_name, v, signature, bsig) is None]
    if not todo:
        _outfit_end(character_name, signature, "images", None)
        return {}
    refs_dir = get_model_refs_dir(character_name)
    mesh_profile = deepcopy(profile)
    mesh_profile["equipped_pieces"] = dict(pieces or {})
    mesh_profile["equipped_items"] = list(items or [])
    results: Dict[str, Optional[str]] = {}
    errors = []
    _outfit_start(character_name, signature, "images")
    try:
        # Own-mesh pieces: the front settles them (their chains run first);
        # the other views follow the stored front's record.
        front_now = None if "front" in todo else dressed_image(character_name, "front", signature, bsig)
        if front_now is not None:
            recorded = _ref_sidecar(front_now).get("mesh_items")
            mesh = recorded if isinstance(recorded, dict) else {}
        else:
            mesh = resolve_mesh_items(character_name, pieces, profile=mesh_profile)
        meshed = mesh_items_unpainted({"mesh_items": mesh})
        dressed = bool(dress_text(character_name, "front", pieces=pieces, items=items, profile=mesh_profile,
                                  mesh_items=meshed))
        mesh_extra = {"mesh_items": mesh} if mesh else {}
        # The painted body this outfit shares with every outfit of the same
        # texture (``texture_inputs``): views of it are copied, not rendered.
        inputs = texture_inputs(character_name, pieces=pieces, items=items, mesh_effective=meshed, bsig=bsig,
                                variant=texture_variant(character_name, pieces, dressed=dressed, mesh=mesh,
                                                        profile=profile), profile=mesh_profile)
        tsig = texture_signature(inputs)
        texts = inputs["dress_text"]
        if not dressed:
            from app.core.timeutils import utc_now_iso
            variant = mesh_variant(character_name, dict(pieces or {}), mesh_profile)
            token = mesh_items_token(character_name, dict(pieces or {}), mesh_profile)
            for v in todo:
                source = base_views[v]
                target = refs_dir / f"{_kind(v)}_{signature}{source.suffix}"
                shutil.copyfile(source, target)
                meta = {**_ref_sidecar(source), "created_at": utc_now_iso(),
                        "equipped_pieces": dict(pieces or {}), "equipped_items": list(items or []),
                        "mesh_variant": variant, "base_signature": bsig,
                        "base_image_sha256": file_sha256(source), "dressed": False, **mesh_extra,
                        "texture_signature": tsig}
                if token:
                    meta["mesh_token"] = token
                target.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                                       encoding="utf-8")
                results[_kind(v)] = str(target)
        else:
            width, height = _tpose_size()
            if not force:
                reused = _reuse_texture_views(character_name, signature=signature, tsig=tsig, bsig=bsig,
                                              todo=todo, texts=texts, base_views=base_views, pieces=pieces,
                                              items=items, profile=mesh_profile, mesh=mesh)
                for v, path in reused.items():
                    results[_kind(v)] = str(path)
                todo = [v for v in todo if v not in reused]
            if "front" in todo:
                prompt, negative = dress_prompt(character_name, "front", pieces=pieces, items=items,
                                                profile=mesh_profile, mesh_items=meshed,
                                                bald=outfit_body_bald(character_name, profile=profile))
                try:
                    with neutral_view_reference(base_views["front"], refs_dir) as reference:
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
                            override_width=width, override_height=height,
                            apply_state_modifiers=False,
                            mesh_input_profile=mesh_profile,
                            reference_image=reference,
                            sidecar_extra={"base_signature": bsig, "dressed": True,
                                           "base_image_sha256": file_sha256(base_views["front"]),
                                           **mesh_extra, "texture_signature": tsig,
                                           "dress_text": texts.get("front", "")},
                            character_loras=True)
                    if path is None:
                        errors.append("Dressed front edit failed")
                except Exception as e:  # noqa: BLE001 — one view never kills the pass
                    path = None
                    errors.append(f"Dressed front edit failed: {e}")
                    logger.warning("Dressed %s front (%s) failed: %s", character_name, signature, e)
                results["tpose"] = str(path) if path else None
            for v in (v for v in DRAFT_VIEWS if v in todo):
                front = dressed_image(character_name, "front", signature, bsig)
                path = None
                if front is None:
                    errors.append(DRESSED_FRONT_FIRST)
                else:
                    try:
                        path, warning = _dress_view(
                            character_name, v, signature=signature, bsig=bsig, pieces=pieces, items=items,
                            profile=mesh_profile, front=front, base_views=base_views, refs_dir=refs_dir,
                            size=(width, height), mesh_items=_ref_sidecar(front).get("mesh_items") or None,
                            texture={"texture_signature": tsig, "dress_text": texts.get(v, "")})
                        if warning:
                            logger.warning("Dressed %s %s (%s): %s", v, character_name, signature, warning)
                    except Exception as e:  # noqa: BLE001 — the front stays
                        errors.append(str(e) if isinstance(e, OutfitError) else f"Dressed {v} edit failed: {e}")
                        logger.warning("Dressed %s %s (%s) failed: %s", character_name, v, signature, e)
                results[_kind(v)] = str(path) if path else None
            rendered = [v for v in todo if results.get(_kind(v))]
            if rendered:
                _store_texture_views(character_name, signature, tsig, rendered, texts)
    finally:
        _outfit_end(character_name, signature, "images", errors[0] if errors else None)
    logger.info("Dressed images %s (%s on %s): %s", character_name, signature, bsig,
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


def _head_vector(path: Path):
    """The head region of a matted figure as a unit, zero-mean vector, or
    None when it cannot be measured (no transparent pixel = no matte, no
    figure, a flat head region). The figure is cropped to its alpha box,
    the top ``VIEW_GUARD_HEAD_SHARE`` of it cropped again to its own alpha
    box (the head, not the arm span), put on neutral grey, greyscaled and
    resized to ``VIEW_GUARD_SIZE`` squared."""
    import numpy as np
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
    head = figure.crop((0, 0, figure.width, max(1, round(figure.height * VIEW_GUARD_HEAD_SHARE))))
    box = head.getchannel("A").getbbox()
    if box is None:
        return None
    head = head.crop(box)
    flat = Image.new("RGBA", head.size, (128, 128, 128, 255))
    flat.alpha_composite(head)
    grey = flat.convert("L").resize((VIEW_GUARD_SIZE, VIEW_GUARD_SIZE), Image.BILINEAR)
    vector = np.asarray(grey, dtype=np.float64).ravel()
    vector = vector - vector.mean()
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 1e-9 else None


def view_guard(view: str, dressed: Path, base_views: Dict[str, Optional[Path]]) -> Dict[str, Any]:
    """Whether a dressed view kept its view: ``{"ok", "scores": {base view:
    correlation}, "best"}`` — ``ok`` when the dressed head region correlates
    best with the base view of the same name. ``{"ok": True, "skipped":
    <reason>}`` when it cannot be measured (an image without a matte, the
    own base view missing): the guard never blocks what it cannot judge."""
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


def _guard_message(view: str, result: Dict[str, Any]) -> str:
    if not result.get("best"):
        return f"{view} view: the dressed image does not keep its view ({result.get('skipped') or 'unchecked'})"
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
                         registrations: Dict[str, Optional[Path]]) -> Tuple[Dict[str, Any], list]:
    """Run ``view_guard`` on every dressed view of a DRESSED combination
    (an undressed one is the base images themselves). A failing view is
    re-rendered ONCE (``generate_dressed_images(view=…, force=True)`` with
    the pieces/items of its sidecar) and checked again; still failing, it
    is dropped from ``dressed_views`` (set None) with a warning naming the
    view — except the front, which fails the build (``OutfitError``).
    Returns ``(guard record per view, warnings)``; the record keeps the
    scores of both attempts (``first`` = the replaced image's)."""
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
        result = view_guard(v, path, registrations)
        if not result["ok"]:
            logger.warning("Outfit model %s (%s): %s — rendering it once more", character_name, signature,
                           _guard_message(v, result))
            manifest = _ref_manifest(path) or _ref_manifest(dressed_views["front"])
            retry: Dict[str, Any] = {"ok": False, "skipped": "no outfit manifest to re-render from"}
            if manifest:
                try:
                    generate_dressed_images(character_name, pieces=manifest.get("pieces"),
                                            items=manifest.get("items"), signature=signature,
                                            force=True, view=v)
                except Exception as e:  # noqa: BLE001 — the old verdict stands
                    logger.warning("Dressed %s %s re-render failed: %s", character_name, v, e)
                path = dressed_image(character_name, v, signature, bsig)
                retry = (view_guard(v, path, registrations) if path is not None
                         else {"ok": False, "skipped": "re-render failed"})
            result = {**retry, "rerendered": True, "first": result}
            if not result["ok"] and "best" not in result:
                result["best"] = result["first"].get("best")
        record[v] = result
        if result["ok"]:
            dressed_views[v] = path
            continue
        if v == "front":
            raise OutfitError(_guard_message(v, result))
        warnings.append(_guard_message(v, result) + "; left out of the outfit model")
        dressed_views[v] = None
    return record, warnings


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
    the pipeline: the rigged base model with the outfit painted on. Called by
    ``model3d._generate_for_current_outfit`` INSTEAD of the img2mesh stages,
    inside its staging (writes go to the stage of ``signature``; the base is
    read from the real directory). Blocking; CPU only.

    Inputs, frozen when the run starts: the current base model (rigged GLB,
    unrigged checkpoint ``model3d/unrigged/<bsig>.glb``, clean prerig
    source), the dressed views ``tpose[_<view>]_<signature>`` made from
    the current base and their registration images ``tpose[_<view>]_<bsig>``
    — only ``dressed_views()`` reach the worker. With side views among them
    the worker also gets the world's ``side_arm_margin`` and the rigged base
    as ``arm_rig_glb`` (its skin weights define the arm the side views skip;
    same UV layout as the unrigged input).
    Before the worker runs, every dressed view passes the view guard
    (``_guard_dressed_views``: a turned view is re-rendered once, then left
    out with a warning; a turned front fails the build); the per-view
    record and the warnings go into the sidecar (``view_guard``,
    ``view_warnings``). The worker gets the unrigged geometry carrying the rigged base's CURRENT
    base-colour image (same UV layout) and writes the dressed GLB; the base's
    face texels are put back into its atlas (``restore_face_texels``, proof
    ``face_texels_restored``) and that atlas goes into a copy of the base
    model the outfit calls for (``outfit_variant``): the rigged base, or its
    covered variant ``model3d/covered/<bsig>.glb`` without the exposed-only
    extension groups when a worn piece hides them (its own extension state
    is copied; a missing or outdated variant falls back to the rigged base
    with the warning ``COVERED_MISSING``). Sidecar ``base_variant``. An
    undressed combination is the rigged base copy without a worker run.
    A back whose ``unchanged_delta_e`` in the proof exceeds
    ``BACK_REFIT_DELTA_E`` is fitted once more and the worker run again
    (``_refit_back``); the better back by that number is kept, the attempts
    are in the sidecar (``back_refit``).
    Then the usual post-steps: texture re-encode, the extension rig
    (``model3d._auto_extension_rig`` — the copied state makes it a no-op
    unless this outfit's ``mesh_variant`` declares other groups, e.g.
    anatomy parts; then every group is rebuilt once from the base's clean
    prerig source WITH THE BASE COLOUR, so colour markers place the bones as
    on the base, and the outfit colour is put back afterwards — never on top
    of the base's extension bones), measurement,
    sidecar (``base_signature``, ``base_model_sha256``, ``retexture_proof``,
    ``source: "base_body"``; the base's ``collision`` capsule set is copied
    with its meta and kept as the inherited set, ``collision.refresh``), distance tier, and the eager garment assembly
    ``model3d/assembled/<signature>.glb`` (``_assemble_garments``; a failure
    only adds ``garment_warnings`` to the sidecar). The dressed front's
    own-mesh record (``mesh_items``, ``mesh_token``) is copied into the
    sidecar with the manifest — the assembly grafts the EFFECTIVE pieces of
    THIS model (``garment_assembly._wanted``) — and its warnings (pieces
    left painted on) open ``garment_warnings``.

    Painted body (plan 2026-11-10-texture-body-reuse, Task 1): everything up
    to the validated retextured GLB is the body of the texture ``tsig``
    (``texture_inputs`` of the dressed front's manifest and own-mesh record).
    The outfit's views and the store's are made one set first
    (``_sync_texture_views``); a current stored body
    (``stored_texture_body``: same base model, same source model, same view
    contents) is reused without guard or worker run — its guard, refit and
    proof records come along — else the body is painted as described and
    stored (``model3d/texture/<tsig>.glb``). The outfit's sidecar names
    ``texture_signature`` and ``texture_reused``; the post-steps and the
    assembly stay per outfit. ``force`` (an explicit regeneration) paints
    the body again even when a current one is stored.

    Outfit body mode ``mesh`` (``outfit_body_mode``, plan
    2026-11-10-outfit-body-mesh-mode): a dressed combination is NOT painted —
    after the store sync its model is the outfit body of ``tsig``
    (``_build_on_outfit_body``), which ``prepare_outfit_body`` built before
    this staged run; missing or not matching the views it fails with
    ``OUTFIT_BODY_MISSING`` / ``OUTFIT_BODY_OUTDATED``. An undressed
    combination stays the rigged base copy.

    Errors (worker unavailable/refused, missing base model or images, an
    output that cannot be read) → ``{"ok": False, "error": <message>}``,
    recorded for the outfit status; nothing is written, so the previous
    model of the signature stays."""
    import tempfile
    from app.core import body_retexture, model3d
    from app.core.extension_rig import extension_metadata
    from app.core.model_refs import find_ref_image
    from app.core.task_queue import get_task_queue
    from app.core.timeutils import utc_now_iso
    _outfit_start(character_name, signature, "model")
    error: Optional[str] = None
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
        registrations = {v: find_ref_image(character_name, _kind(v), bsig) for v in BASE_VIEWS}
        if registrations["front"] is None:
            raise OutfitError(BASE_IMAGES_MISSING)
        front_now = dressed_image(character_name, "front", signature, bsig)
        if front_now is None:
            raise OutfitError(DRESSED_IMAGES_MISSING)
        # The painted body (``texture_inputs``): one per texture, shared by
        # every outfit of it — painted here only when none is current.
        texture = _outfit_texture(character_name, front_now, bsig=bsig, profile=profile)
        first, dressed_now, wanted_variant = texture["manifest"], texture["dressed"], texture["variant"]
        inputs, tsig, mesh_profile = texture["inputs"], texture["tsig"], texture["mesh_profile"]
        if dressed_now:
            _sync_texture_views(character_name, signature=signature, tsig=tsig, bsig=bsig,
                                base_views=registrations, texts=inputs["dress_text"], manifest=first,
                                profile=mesh_profile)
            if outfit_body_mode(character_name, profile=profile) == MESH_MODE:
                # Mesh mode: the body is the outfit body of ``tsig``, built
                # beforehand by ``prepare_outfit_body`` (never in this stage).
                return _build_on_outfit_body(character_name, signature, bsig=bsig, base=base, tsig=tsig,
                                             variant=wanted_variant, profile=profile)
        stored = None if force else stored_texture_body(
            character_name, tsig, base=base, view_shas=texture_view_shas(character_name, signature, bsig))
        back_refit: Optional[Dict[str, Any]] = None
        if stored is not None:
            # Reused: the views are the body's (same content), so are its
            # view guard, refit and proof; no worker run.
            outfit, body = stored
            front_path = dressed_image(character_name, "front", signature, bsig)
            front_meta = _ref_sidecar(front_path)
            manifest = model3d._ref_manifest(front_path)
            names = {}
            for v in body.get("used_views") or ["front"]:
                used = dressed_image(character_name, v, signature, bsig) if v in BASE_VIEWS else None
                if used is not None:
                    names[v] = used.name
            if "front" not in names:
                raise OutfitError(DRESSED_IMAGES_MISSING)
            guard = _dict_of(body.get("view_guard"))
            warnings = [w for w in body.get("view_warnings") or [] if isinstance(w, str)]
            variant = str(body.get("base_variant") or "rigged")
            proof = body.get("retexture_proof")
            back_refit = body.get("back_refit") if isinstance(body.get("back_refit"), dict) else None
            source_state = body.get("source_state")
            source_blender = body.get("source_blender")
            logger.info("Outfit model %s (%s): painted body %s reused", character_name, signature, tsig)
        else:
            dressed_paths = {v: dressed_image(character_name, v, signature, bsig) for v in dressed_views()}
            if dressed_paths["front"] is None:
                raise OutfitError(DRESSED_IMAGES_MISSING)
            guard, warnings = _guard_dressed_views(character_name, signature, bsig, dressed_paths, registrations)
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
                # The base model this outfit is painted onto: the covered variant
                # when a worn piece hides the exposed-only extension groups.
                # (An undressed copy of pieces that are all own meshes too: the
                # garment meshes cover the body like painted pieces would.)
                variant = wanted_variant  # outfit_variant, or "rigged" for an undressed copy (texture_variant)
                source_model, source_state, source_blender = base["rigged"], None, None
                if variant == "covered":
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
                    image, mime = base_color_image(base["rigged"])
                    worker_in = work / "base_in.glb"
                    worker_in.write_bytes(replace_base_color(base["unrigged"], image, mime))
                    side: Dict[str, Any] = {}
                    if any(v in views for v in SIDE_DRESSED_VIEWS):
                        arm_rig = work / "arm_rig.glb"
                        arm_rig.write_bytes(base["rigged"])
                        side = {"side_arm_margin": side_arm_margin(), "arm_rig_glb": arm_rig}

                    def run_worker(run_views: Dict[str, Tuple[Path, Path]], tag: str = ""):
                        out = work / f"dressed{tag}.glb"
                        result = body_retexture.retexture(worker_in, run_views, out, proof=work / f"proof{tag}.json",
                                                          atlas=work / f"atlas{tag}.png", **side)
                        if not out.is_file():
                            raise OutfitError("Body retexture worker wrote no GLB")
                        return result, out

                    proof, out_glb = run_worker(views)
                    delta = view_delta_e(proof, "back")
                    if "back" in views and delta is not None and delta > BACK_REFIT_DELTA_E:
                        back_refit, better = _refit_back(
                            character_name, signature=signature, bsig=bsig, back=dressed_paths["back"],
                            profile=profile, base_views=registrations, first_proof=proof,
                            retexture=lambda fit: run_worker({**views, "back": (fit, views["back"][1])}, "_refit"))
                        if better is not None:
                            proof, out_glb = better
                    atlas, atlas_mime = base_color_image(out_glb.read_bytes())
                    atlas, atlas_mime, restored = restore_face_texels(atlas, atlas_mime, image, base["meta"])
                    proof = {**(proof or {}), **restored}
                    outfit = replace_base_color(source_model, atlas, atlas_mime)
                verdict = model3d._validator_for("mixamo", character_name)(outfit)
                if not verdict.get("ok"):
                    raise OutfitError("Retextured model is invalid: " + "; ".join(verdict.get("errors") or []))
            if front_meta.get("dressed") is not False:
                # The guard or the back refit may have rendered a view again.
                _store_texture_views(character_name, signature, tsig,
                                     [v for v in dressed_views() if dressed_image(character_name, v, signature, bsig)],
                                     inputs["dress_text"])
            _store_texture_body(character_name, tsig, outfit, {
                "texture_signature": tsig, "texture_inputs": inputs, "created_at": utc_now_iso(),
                "character": character_name, "built_for": signature, "base_signature": bsig,
                "base_model_sha256": hashlib.sha256(base["rigged"]).hexdigest(),
                "source_model_sha256": _source_sha(base, variant), "base_variant": variant,
                "covered_missing": COVERED_MISSING in warnings, "dressed": front_meta.get("dressed") is not False,
                "views": texture_view_shas(character_name, signature, bsig),
                "used_views": [v for v in BASE_VIEWS if v in names], "retexture_proof": proof,
                "back_refit": back_refit, "view_guard": guard, "view_warnings": warnings,
                "source_state": deepcopy(source_state), "source_blender": deepcopy(source_blender),
                "body_sha256": hashlib.sha256(outfit).hexdigest()})
        out_dir = model3d.get_model3d_dir(character_name)
        path = out_dir / f"{signature}.glb"
        model3d._purge_combination(out_dir, signature, keep_model=path)
        model3d._publish_model_bytes(path, outfit)
        meta = {k: v for k, v in deepcopy(base["meta"]).items() if k not in _BASE_ONLY_META}
        if source_state is not None:
            # The covered variant's own extension state (and the Blender
            # record of its file): with it the extension rig below is a no-op.
            meta["extension_rig"] = deepcopy(source_state)
            meta["blender"] = deepcopy(source_blender or meta.get("blender") or {})
        meta.update({"created_at": utc_now_iso(), "source": "base_body", "signature": signature,
                     "base_variant": variant, "covered_missing": COVERED_MISSING in warnings,
                     "character": character_name, "format": "glb", "rig": "mixamo",
                     "base_signature": bsig,
                     "base_model_sha256": hashlib.sha256(base["rigged"]).hexdigest(),
                     "retexture_proof": proof,
                     "dressed": front_meta.get("dressed") is not False,
                     "source_image": names["front"],
                     "view_images": {v: n for v, n in names.items() if v != "front"},
                     "view_guard": guard, "view_warnings": warnings,
                     "texture_signature": tsig, "texture_reused": stored is not None})
        if back_refit is not None:
            meta["back_refit"] = back_refit
        meta.update(manifest)
        # Own-mesh pieces left painted on (their chain failed): the
        # assembly's own warning, if any, follows.
        mesh_warnings = [w for w in (_dict_of(manifest.get("mesh_items")).get("warnings") or [])
                         if isinstance(w, str) and w]
        if mesh_warnings:
            meta["garment_warnings"] = mesh_warnings
        model3d._auto_retexture(character_name, path, meta)
        colour = base_color_image(path.read_bytes())
        prerig = out_dir / "prerig" / path.name
        if base["prerig"] is not None:
            # The extension rig (only when the copied state is not current,
            # e.g. parts declared for this outfit) runs on the BASE's clean
            # source with the base colour, so colour markers hidden by the
            # painted outfit still place the bones exactly as on the base —
            # never a geometry fallback under clothing; the outfit colour
            # goes back on afterwards.
            prerig.parent.mkdir(parents=True, exist_ok=True)
            model3d._publish_model_bytes(prerig, base["prerig"])
            model3d._publish_sidecar(prerig, base["prerig_meta"])
        model3d._auto_extension_rig(character_name, path, meta)
        if base_color_image(path.read_bytes()) != colour:
            model3d._publish_model_bytes(path, replace_base_color(path.read_bytes(), *colour))
        if base["prerig"] is not None:
            # The clean source then carries the same texture as the model.
            source = base["prerig"]
            if base_color_image(source) != colour:
                source = replace_base_color(source, *colour)
            model3d._publish_model_bytes(prerig, source)
        model3d._attach_measurement(meta, path)
        meta.setdefault("extension_rig", extension_metadata(character_name, signature=path.stem))
        model3d._publish_sidecar(path, meta)
        model3d.request_lod(character_name, path)
        _assemble_garments(character_name, signature, path, meta)
        logger.info("Outfit model %s (%s on %s): %s", character_name, signature, bsig,
                    "retextured" if proof is not None else "undressed base copy")
        return {"ok": True, "cached": False, "path": str(path), "filename": path.name, "proof": proof}
    except (OutfitError, body_retexture.RetextureUnavailable, body_retexture.RetextureFailed,
            ValueError) as e:
        error = str(e) or type(e).__name__
        logger.warning("Outfit model %s (%s) failed: %s", character_name, signature, error)
        return {"ok": False, "error": error}
    except Exception as e:
        error = str(e) or type(e).__name__
        raise
    finally:
        _outfit_end(character_name, signature, "model", error)
        if task_id:
            try:
                get_task_queue().track_finish(task_id, error=error or "")
            except Exception:  # noqa: BLE001
                pass


# --- Outfit body as mesh (plan 2026-11-10-outfit-body-mesh-mode, Task 1) ----
#
# Per character (profile/template field ``outfit_body_mode``) the body under
# the own-mesh garments is either the base body with the painted pieces
# retextured onto it (``retexture``, the default — everything above) or an
# OUTFIT BODY (``mesh``): the dressed views of the texture ``tsig`` meshed
# and rigged through the staged chain of the old whole-body path
# (``model3d.generate_for_current_outfit`` with ``outfit_body=…``: img2mesh
# via the character's mesh occasion → face cleanup (per-character switch)
# → face retexture before the rig when the character has it on → rig via the
# ``rig_humanoid`` chain → texture re-encode → normalize (posture restore from
# the retained unrigged source) → extension rig (no anatomy-part batches, like
# the base) → collision capsules). Routing per step as on the old path,
# per-character overrides included.
#
# Body id: ``"ob"`` + the first 8 hex of sha256 over the canonical JSON of
# ``{"mode": "mesh", "texture_signature": tsig, "version": OUTFIT_BODY_VERSION}``
# (``outfit_body_id``) — stable for the same painted pieces on the same base
# signature/variant/side-view switch, the fit key of an own-mesh garment on
# that body (Task 2). Same tsig → same body, no hub job. An outfit whose
# effective dress text is empty (``dressed: false``) is the base body itself
# in both modes.
#
# Ruling 2026-11-10: in this mode the dress text leaves out EVERY flagged
# own-mesh piece (``resolve_mesh_items``: ``unpainted`` = ``intended``), not
# only those with an accepted fit — a piece without one is never meshed into
# a body (that body would be thrown away with its hub jobs once the piece's
# mesh is accepted). It is missing from the outfit model until then
# (``MESH_ITEM_NOT_READY``); its acceptance only assembles it onto the same
# body (``after_mesh_item_ready``). A model built before the ruling with
# such a piece painted in is stale (``outfit_body_stale``: "outfit_body") and
# rebuilt on the body of its painted pieces alone.
#
# Storage: the body is a model signature of its own in the character's model
# store, laid out like the base body (``base<8hex>``) so every signature-keyed
# step of the old path (staging, publication, re-rig, face retexture, LOD
# skip, purge) applies unchanged:
#   model_refs/tpose[_<view>]_<body id>.*        the mesher inputs: copies of
#                                                 the tsig's dressed views
#                                                 (outfit keys stripped)
#   model3d/<body id>.glb + .json                 the rigged body
#   model3d/unrigged/<body id>.glb + .json        retained source (re-rig,
#                                                 posture restore)
#   model3d/prerig|raw|facefix|rollback/<body id>.*  the chain's usual files
# PARENT RECORD: every one of these sidecars carries ``outfit_body`` =
# ``{body_id, mode, version, texture_signature, base_signature, base_variant,
# built_for, views, used_views, view_guard, view_warnings}`` (``views``: the
# content sha256 of every dressed view of the tsig the body was meshed from —
# its freshness); an outfit model on a body names ``outfit_body_mode: "mesh"``,
# ``body_id``, ``body_sha256``, ``texture_signature`` and
# ``base_signature``. Task 3's reachability GC walks these. The own-mesh
# garments and the hair on a body are fitted per body (Task 2,
# ``garments.body_fit``: ``garments/bodies/<body id>/``).

OUTFIT_BODY_MODES = ("retexture", "mesh")
RETEXTURE_MODE, MESH_MODE = OUTFIT_BODY_MODES
#: Bumped when an outfit body is meshed differently for the same inputs.
OUTFIT_BODY_VERSION = 1
OUTFIT_BODY_RE = re.compile(r"ob[0-9a-f]{8}")
OUTFIT_BODY_MISSING = "Outfit body missing — rebuild the outfit model"
OUTFIT_BODY_OUTDATED = "The outfit body does not match the dressed views — rebuild the outfit model"
#: Mesh mode (ruling 2026-11-10): an outfit body is meshed from EVERY dressed
#: view (``dressed_views()``) or not at all — a missing view is rendered
#: first in the same run; one that cannot be rendered stops the build.
VIEWS_MISSING = "{views} {noun} missing — not meshed from the {have} alone"
#: How long the build waits for a dressed render of the same outfit that
#: runs elsewhere (the T-pose lane) before it renders the missing views itself.
DRESSED_RENDER_WAIT_S = 1800.0
BODY_MODE_CHANGED = "Built for the other outfit body mode"
OUTFIT_BODY_CHANGED = "Built on an older outfit body"
NOT_FITTED_ON_BODY = "Not fitted on this outfit body, served without: {items}"

# Bald dressed views under an own hair mesh (controller ruling 2026-11-10).
# The mesh-mode outfit body views are edits of the BALD base views, so they
# are bald by construction; for robustness the dressed front edit of a
# character in the mesh mode that wears its OWN hair item
# (``garment_hair.worn_hair_id``) also closes with the base front's
# ``BALD_HEAD`` and carries its ``HAIR_NEGATIVE`` (``dress_prompt(bald=True)``;
# the back/side drafts already use the base view prompt with the bald head).
# The rule is a prompt detail only: NOT part of the texture inputs, the tsig
# or the body id — existing bodies keep their keys and nothing becomes stale.


def outfit_body_bald(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the dressed edit carries the bald head (block above): on the
    pipeline, in the mesh mode, wearing its own hair item."""
    profile = _profile_of(character_name, profile)
    if outfit_body_mode(character_name, profile=profile) != MESH_MODE:
        return False
    if not is_base_pipeline(character_name, profile=profile):
        return False
    from app.core.garment_hair import worn_hair_id
    return bool(worn_hair_id(character_name, profile))


def is_outfit_body_signature(value: Optional[str]) -> bool:
    return bool(value) and OUTFIT_BODY_RE.fullmatch(str(value)) is not None


def outfit_body_mode(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> str:
    """The character's ``outfit_body_mode`` (``retexture`` for anything else)."""
    mode = _profile_of(character_name, profile).get("outfit_body_mode")
    return mode if mode in OUTFIT_BODY_MODES else RETEXTURE_MODE


def outfit_body_id(tsig: str) -> str:
    """The outfit body of the texture ``tsig`` in mesh mode (block above)."""
    if not is_texture_signature(tsig):
        raise ValueError(f"not a texture signature: {tsig!r}")
    raw = json.dumps({"mode": MESH_MODE, "texture_signature": tsig, "version": OUTFIT_BODY_VERSION},
                     sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "ob" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]


def outfit_body_path(character_name: str, body_id: str) -> Path:
    """``model3d/<body id>.glb`` of the REAL model directory."""
    from app.models.character import get_character_dir
    if not is_outfit_body_signature(body_id):
        raise ValueError(f"not an outfit body id: {body_id!r}")
    return get_character_dir(character_name) / "model3d" / f"{body_id}.glb"


def _outfit_texture(character_name: str, front: Path, *, bsig: str,
                    profile: Dict[str, Any]) -> Dict[str, Any]:
    """The texture an outfit's dressed front stands for: ``{manifest,
    dressed, variant, inputs, tsig, mesh_profile}`` (``texture_inputs`` of
    the front's manifest and own-mesh record)."""
    from app.core import model3d
    manifest = model3d._ref_manifest(front)
    mesh = _dict_of(manifest.get("mesh_items"))
    dressed = _ref_sidecar(front).get("dressed") is not False
    mesh_profile = deepcopy(profile)
    mesh_profile["equipped_pieces"] = dict(manifest.get("pieces") or {})
    mesh_profile["equipped_items"] = list(manifest.get("items") or [])
    variant = texture_variant(character_name, manifest.get("pieces") or {}, dressed=dressed, mesh=mesh,
                              profile=profile)
    inputs = texture_inputs(character_name, pieces=manifest.get("pieces") or {}, items=manifest.get("items") or [],
                            variant=variant, mesh_effective=mesh_items_unpainted({"mesh_items": mesh}), bsig=bsig,
                            profile=mesh_profile)
    return {"manifest": manifest, "dressed": dressed, "variant": variant, "inputs": inputs,
            "tsig": texture_signature(inputs), "mesh_profile": mesh_profile}


def predicted_texture_signatures(character_name: str, pieces: Optional[Dict[str, str]], items: Optional[list], *,
                                 bsig: str, profile: Optional[Dict[str, Any]] = None,
                                 modes: Iterable[str] = OUTFIT_BODY_MODES) -> Dict[str, str]:
    """``{mode: tsig}`` — the tsig a build of the outfit ``pieces`` /
    ``items`` would paint NOW in each outfit body mode:
    ``generate_dressed_images``' computation with ``predicted_mesh_items``
    (read-only: no garment chain, no image). The artefact GC asks it for
    every live outfit in BOTH modes (a mode switch must not orphan the other
    mode's painted bodies); modes that leave out the same pieces share one
    computation."""
    profile = _profile_of(character_name, profile)
    mesh_profile = deepcopy(profile)
    mesh_profile["equipped_pieces"] = dict(pieces or {})
    mesh_profile["equipped_items"] = list(items or [])
    out: Dict[str, str] = {}
    done: Dict[Tuple[Tuple[str, ...], Tuple[str, ...]], str] = {}
    for mode in modes:
        mesh = predicted_mesh_items(character_name, pieces, mode=mode,
                                    profile={**mesh_profile, "outfit_body_mode": mode}, bsig=bsig)
        meshed = mesh_items_unpainted({"mesh_items": mesh})
        key = (tuple(meshed), tuple(mesh_items_intended({"mesh_items": mesh})))
        if key not in done:
            dressed = bool(dress_text(character_name, "front", pieces=pieces, items=items, profile=mesh_profile,
                                      mesh_items=meshed))
            variant = texture_variant(character_name, pieces, dressed=dressed, mesh=mesh, profile=profile)
            done[key] = texture_signature(texture_inputs(character_name, pieces=pieces, items=items,
                                                         mesh_effective=meshed, bsig=bsig, variant=variant,
                                                         profile=mesh_profile))
        out[mode] = done[key]
    return out


def front_texture_signature(character_name: str, signature: str, *, bsig: str,
                            profile: Optional[Dict[str, Any]] = None,
                            modes: Iterable[str] = OUTFIT_BODY_MODES) -> str:
    """The tsig the outfit's stored dressed front stands for
    (``_outfit_texture``) while that front is current for the base
    (``dressed_image`` without the mode rule: base signature + base view
    content, no painted piece that has its fit now), follows the own-mesh
    rule of at least one of ``modes`` (default: both), and was made for the own-mesh
    flags its pieces carry NOW (recorded ``mesh_items.intended`` = the
    flagged worn pieces today: a flag set or removed since makes the outfit
    a new signature, so this front is never built from again) — "" otherwise.
    Read-only."""
    from app.core import model3d
    from app.core.model_refs import find_ref_image
    profile = _profile_of(character_name, profile)
    front = find_ref_image(character_name, _kind("front"), signature)
    if front is None:
        return ""
    meta = _ref_sidecar(front)
    base_front = find_ref_image(character_name, _kind("front"), bsig)
    if base_front is None or meta.get("base_signature") != bsig \
            or meta.get("base_image_sha256") != file_sha256(base_front):
        return ""
    if mesh_items_ready(character_name, meta, bsig=bsig):
        return ""
    if all(mesh_items_off_rule(character_name, meta, bsig=bsig, profile={**profile, "outfit_body_mode": mode})
           for mode in modes):
        return ""
    pieces = model3d._ref_manifest(front).get("pieces") or {}
    mesh_profile = {**profile, "equipped_pieces": dict(pieces)}
    if sorted(mesh_items_intended(meta)) != sorted(_own_mesh_kinds(character_name, pieces, profile=mesh_profile)):
        return ""
    return str(_outfit_texture(character_name, front, bsig=bsig, profile=profile)["tsig"])


def outfit_body_of_outfit(character_name: str, signature: str, *,
                          profile: Optional[Dict[str, Any]] = None) -> str:
    """The outfit body id the outfit ``signature`` stands on NOW in mesh
    mode — computed from its dressed front of the current base (the tsig
    ``prepare_outfit_body`` would build) — or "" (no dressed front of the
    current base, an undressed combination, or any error). Read-only; the
    Outfit body tab asks it to find an outfit to regenerate a body from."""
    try:
        profile = _profile_of(character_name, profile)
        bsig = base_signature(character_name, profile=profile)
        front = dressed_image(character_name, "front", signature, bsig)
        if front is None:
            return ""
        texture = _outfit_texture(character_name, front, bsig=bsig, profile=profile)
        return outfit_body_id(texture["tsig"]) if texture["dressed"] else ""
    except Exception:  # noqa: BLE001 — a lookup, never a failure
        logger.debug("Outfit body of %s / %s not computable", character_name, signature, exc_info=True)
        return ""


def stored_outfit_body(character_name: str, body_id: str, *, tsig: str,
                       view_shas: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """The sidecar of the stored outfit body ``body_id`` when it is current:
    a rigged humanoid GLB without ``rig_error`` whose parent record names
    ``body_id``, ``tsig`` and exactly the dressed view contents
    ``view_shas`` (``texture_view_shas``); else None."""
    path = outfit_body_path(character_name, body_id)
    meta = _ref_sidecar(path)
    record = _dict_of(meta.get("outfit_body"))
    if not path.is_file() or meta.get("rig") != "mixamo" or meta.get("rig_error"):
        return None
    if (record.get("body_id") != body_id or record.get("texture_signature") != tsig
            or record.get("version") != OUTFIT_BODY_VERSION or record.get("views") != view_shas):
        return None
    return meta


def outfit_body_stale(character_name: str, meta: Dict[str, Any], *,
                      profile: Optional[Dict[str, Any]] = None) -> str:
    """Why a dressed outfit model on the pipeline is not current for the
    character's body mode: ``"body_mode"`` (built in the other mode),
    ``"outfit_body"`` (mesh mode: its outfit body was rebuilt or is gone —
    ``body_sha256`` —, or it was built before the ruling of 2026-11-10 with
    an own-mesh piece without a fit painted into its body: the body of its
    painted pieces alone is another one), else ``""``. An undressed copy is
    the base body in both modes; a model from before the pipeline is judged
    elsewhere."""
    if meta.get("dressed") is False or not meta.get("base_signature"):
        return ""
    built = meta.get("outfit_body_mode") or RETEXTURE_MODE
    if built != outfit_body_mode(character_name, profile=profile):
        return "body_mode"
    if built == MESH_MODE:
        body_id = meta.get("body_id")
        if (not is_outfit_body_signature(body_id)
                or file_sha256(outfit_body_path(character_name, str(body_id))) != meta.get("body_sha256")):
            return "outfit_body"
        if _mesh_items_pending(meta):
            return "outfit_body"
    return ""


def _write_body_refs(character_name: str, body_id: str, views: Dict[str, Path],
                     parent: Dict[str, Any]) -> None:
    """The mesher inputs of an outfit body: ``model_refs/tpose[_<view>]_<body
    id>`` = copies of ``views`` (the outfit's dressed views of its tsig, the
    outfit's own sidecar keys dropped), each sidecar naming the parent
    record. A view not in ``views`` (left out by the guard) goes."""
    from app.core.model_refs import _IMAGE_EXTS, get_model_refs_dir
    refs = get_model_refs_dir(character_name)
    for v in BASE_VIEWS:
        if v in views:
            continue
        for ext in _IMAGE_EXTS + (".json",):
            Path(f"{refs / f'{_kind(v)}_{body_id}'}{ext}").unlink(missing_ok=True)
    for v, source in views.items():
        meta = {k: val for k, val in _ref_sidecar(source).items() if k not in _OUTFIT_VIEW_KEYS}
        meta.update({"texture_signature": parent["texture_signature"], "outfit_body": parent})
        _copy_ref(source, refs / f"{_kind(v)}_{body_id}", meta)


def _join_views(views: Iterable[str]) -> str:
    """``front``, ``front and back``, ``back, left and right``."""
    views = list(views)
    return views[0] if len(views) == 1 else ", ".join(views[:-1]) + " and " + views[-1]


def views_missing_message(missing: List[str], have: List[str], reason: str = "") -> str:
    """``VIEWS_MISSING`` for the dressed views an outfit body still lacks,
    ``reason`` (the render's error) appended in brackets."""
    label = _join_views(missing)
    text = VIEWS_MISSING.format(views=label[:1].upper() + label[1:], noun="view" if len(missing) == 1 else "views",
                                have=_join_views(have) if have else "nothing")
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


def _wait_dressed_render(character_name: str, signature: str, timeout: float = DRESSED_RENDER_WAIT_S) -> None:
    """Wait while a dressed render of the outfit ``signature`` runs
    elsewhere (its ``images`` stage, e.g. the T-pose lane), so the build
    does not render the same missing view a second time. Bounded."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _status_lock:
            if _outfit_running.get((character_name, "images")) != signature:
                return
        time.sleep(1.0)


def _complete_dressed_views(character_name: str, signature: str, bsig: str,
                            manifest: Dict[str, Any]) -> Tuple[Dict[str, Optional[Path]], str]:
    """Mesh mode: the dressed views of the outfit ``signature``
    (``dressed_views()``), every missing one rendered FIRST
    (``generate_dressed_images`` without ``force`` with the pieces/items of
    the dressed front's ``manifest`` — image jobs only; a view the texture
    store holds is copied). Returns ``({view: path | None}, reason)`` —
    ``reason`` is the render's error when a view is still missing."""
    def current() -> Dict[str, Optional[Path]]:
        return {v: dressed_image(character_name, v, signature, bsig) for v in dressed_views()}

    paths = current()
    if all(paths.values()):
        return paths, ""
    _wait_dressed_render(character_name, signature)
    paths = current()
    missing = [v for v, p in paths.items() if p is None]
    if not missing:
        return paths, ""
    logger.info("Outfit body of %s (outfit %s): rendering the dressed %s first — never meshed from a partial set",
                character_name, signature, missing)
    reason = ""
    try:
        generate_dressed_images(character_name, pieces=manifest.get("pieces") or {},
                                items=manifest.get("items") or [], signature=signature, force=False)
    except Exception as e:  # noqa: BLE001 — the missing view stops the build below
        reason = str(e) or type(e).__name__
        logger.warning("Dressed %s of %s (%s) failed: %s", missing, character_name, signature, reason)
    paths = current()
    if not reason and not all(paths.values()):
        with _status_lock:
            failure = dict(_outfit_failed.get((character_name, signature)) or {})
        if failure.get("stage") == "images":
            reason = str(failure.get("error") or "")
    return paths, reason


def prepare_outfit_body(character_name: str, signature: Optional[str] = None, *,
                        force: bool = False, rebuild: bool = False) -> Optional[Dict[str, Any]]:
    """Mesh mode: make sure the outfit body of the outfit ``signature``
    (default: the worn one) exists BEFORE its outfit model is built — called
    by ``model3d.generate_for_current_outfit`` outside any model stage (the
    body is a publication of its own; ``build_outfit_model`` only copies it).

    None when there is nothing to do: off the pipeline, ``retexture`` mode,
    the outfit model is stored and current (unless ``force``), no dressed
    front of the current base yet (the build reports it), or an undressed
    combination (the base body itself). Otherwise, serial per (character,
    body): the outfit's views and the texture store become one set
    (``_sync_texture_views``); then EVERY view of ``dressed_views()`` must
    exist for it (ruling 2026-11-10 — never meshed from a partial set): a
    missing one is rendered first, in this run (``_complete_dressed_views``);
    one that still misses (refused, failed) stops here with
    ``VIEWS_MISSING`` as the outfit's ``body`` status — ``{ok: False, error,
    body_id}``, no mesh job. A current body (``stored_outfit_body``) is
    reused — ``{ok, cached: True, body_id}``, no job; ``force`` (an outfit
    rebuild) never rebuilds a current body, ``rebuild`` (an explicit body
    regeneration) does. Else the dressed views pass the view guard (a turned
    view is re-rendered once; still turned, it stops the build like a
    missing one; a turned front fails), the
    views become the body's refs (``_write_body_refs``) and the staged chain
    runs on the body id (``generate_for_current_outfit(signature=<body id>,
    force=True, outfit_body=…)``). The outfit's status counts as running
    meanwhile (stage ``body``); a failure is recorded for the outfit and
    returned ``{ok: False, error, body_id}``."""
    from app.core import model3d
    from app.core.keyed_lock import keyed_lock
    from app.core.model_refs import current_outfit_state, find_ref_image
    profile = _profile_of(character_name, None)
    if not is_base_pipeline(character_name, profile=profile) or outfit_body_mode(
            character_name, profile=profile) != MESH_MODE:
        return None
    if signature is None:
        signature = current_outfit_state(character_name)[2]
    if not signature or (not force and not rebuild and model3d.find_model3d(character_name, signature)):
        return None
    bsig = base_signature(character_name, profile=profile)
    registrations = {v: find_ref_image(character_name, _kind(v), bsig) for v in BASE_VIEWS}
    front = dressed_image(character_name, "front", signature, bsig)
    if registrations["front"] is None or front is None:
        return None
    texture = _outfit_texture(character_name, front, bsig=bsig, profile=profile)
    if not texture["dressed"]:
        return None
    tsig, inputs = texture["tsig"], texture["inputs"]
    body_id = outfit_body_id(tsig)
    with keyed_lock("outfit_body", f"{character_name}:{body_id}"):
        _sync_texture_views(character_name, signature=signature, tsig=tsig, bsig=bsig, base_views=registrations,
                            texts=inputs["dress_text"], manifest=texture["manifest"],
                            profile=texture["mesh_profile"])
        if not all(dressed_image(character_name, v, signature, bsig) for v in dressed_views()):
            # Every dressed view or no mesh (ruling 2026-11-10): the missing
            # ones are rendered BEFORE the stored body is judged — a body
            # meshed from a partial set must not count as current.
            _outfit_start(character_name, signature, "body")
            missing_error: Optional[str] = None
            try:
                paths, reason = _complete_dressed_views(character_name, signature, bsig, texture["manifest"])
                missing = [v for v, p in paths.items() if p is None]
                if missing:
                    missing_error = views_missing_message(missing, [v for v, p in paths.items() if p], reason)
            except Exception as e:
                missing_error = str(e) or type(e).__name__
                raise
            finally:
                _outfit_end(character_name, signature, "body", missing_error)
            if missing_error:
                logger.warning("Outfit body %s of %s: %s", body_id, character_name, missing_error)
                return {"ok": False, "error": missing_error, "body_id": body_id}
        if not rebuild and stored_outfit_body(character_name, body_id, tsig=tsig, view_shas=texture_view_shas(
                character_name, signature, bsig)) is not None:
            # A body from before the posture match (or matched to another base model) gets
            # its base's posture first — CPU only; the outfit model then copies the turned body.
            from app.core.outfit_body_posture import is_stale
            if is_stale(character_name, body_id):
                matched = model3d.match_outfit_body_posture(character_name, body_id)
                if not matched.get("ok"):
                    logger.warning("Outfit body %s of %s: posture match failed (%s) — built on it as it is",
                                   body_id, character_name, matched.get("error"))
            return {"ok": True, "cached": True, "body_id": body_id}
        _outfit_start(character_name, signature, "body")
        error: Optional[str] = None
        try:
            paths = {v: dressed_image(character_name, v, signature, bsig) for v in dressed_views()}
            if paths["front"] is None:
                raise OutfitError(DRESSED_IMAGES_MISSING)
            guard, warnings = _guard_dressed_views(character_name, signature, bsig, paths, registrations)
            # The guard may have rendered a view again: the store follows.
            _store_texture_views(character_name, signature, tsig,
                                 [v for v in dressed_views() if dressed_image(character_name, v, signature, bsig)],
                                 inputs["dress_text"])
            used = {v: p for v, p in paths.items() if p is not None}
            left_out = [v for v in dressed_views() if v not in used]
            if left_out:
                # The guard left a turned view out: never meshed without it.
                raise OutfitError(views_missing_message(
                    left_out, [v for v in BASE_VIEWS if v in used],
                    "; ".join(w.replace("; left out of the outfit model", "") for w in warnings)))
            parent = {"body_id": body_id, "mode": MESH_MODE, "version": OUTFIT_BODY_VERSION,
                      "texture_signature": tsig, "base_signature": bsig, "base_variant": texture["variant"],
                      "built_for": signature, "views": texture_view_shas(character_name, signature, bsig),
                      "used_views": [v for v in BASE_VIEWS if v in used], "view_guard": guard,
                      "view_warnings": warnings}
            _write_body_refs(character_name, body_id, used, parent)
            logger.info("Outfit body %s of %s (texture %s, outfit %s): meshing %s", body_id, character_name, tsig,
                        signature, parent["used_views"])
            result = model3d.generate_for_current_outfit(
                character_name, force=True, signature=body_id,
                outfit_body={"outfit_body": parent, "base_variant": texture["variant"]})
            if not result.get("ok"):
                error = str(result.get("error") or "Outfit body generation failed")
            return {**result, "body_id": body_id, **({"error": error} if error else {})}
        except OutfitError as e:
            error = str(e) or type(e).__name__
            logger.warning("Outfit body %s of %s failed: %s", body_id, character_name, error)
            return {"ok": False, "error": error, "body_id": body_id}
        except Exception as e:
            error = str(e) or type(e).__name__
            raise
        finally:
            _outfit_end(character_name, signature, "body", error)


def _snapshot_outfit_body(character_name: str, body_id: str) -> Dict[str, Any]:
    """The stored outfit body's files, read under the publication lock of
    the REAL model directory: rigged GLB + sidecar, the clean prerig source
    + sidecar when it exists. ``OutfitError(OUTFIT_BODY_MISSING)`` without a
    rigged body."""
    from app.core.keyed_lock import keyed_lock
    from app.core.model3d import _read_sidecar
    path = outfit_body_path(character_name, body_id)
    with keyed_lock("model3d_publication", str(path.parent)):
        meta = _read_sidecar(path)
        if (not path.is_file() or meta.get("rig") != "mixamo" or meta.get("rig_error")
                or not isinstance(meta.get("outfit_body"), dict)):
            raise OutfitError(OUTFIT_BODY_MISSING)
        prerig = path.parent / "prerig" / path.name
        return {"rigged": path.read_bytes(), "meta": meta,
                "prerig": prerig.read_bytes() if prerig.is_file() else None,
                "prerig_meta": _read_sidecar(prerig) if prerig.is_file() else {}}


def _build_on_outfit_body(character_name: str, signature: str, *, bsig: str, base: Dict[str, Any], tsig: str,
                          variant: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    """``build_outfit_model`` in mesh mode, inside the outfit's stage: the
    outfit model is a copy of the CURRENT outfit body of ``tsig`` (rigged
    GLB; its clean prerig source becomes the outfit's, so an outfit that
    declares other extension groups rebuilds them on the body's geometry).
    No worker run, no hub job. The body's chain records (mesh/rig backends,
    face cleanup/retexture, Blender steps, extension state, collision set)
    come along; the sidecar adds ``outfit_body_mode: "mesh"``, ``body_id``,
    ``body_sha256``, ``texture_signature``, ``base_signature`` /
    ``base_model_sha256`` (the outfit model is stale on another base model,
    as in retexture mode — the body is reused then) and the outfit's
    manifest. The own-mesh pieces it carries and the worn hair are fitted
    onto THIS body before the sidecar is published (plan Task 2:
    ``garment_assembly.body_fit_warning`` → ``garments.body_fit``, CPU from
    the cached garment sources, keyed ``(item, fsig, body id)``) and grafted
    by the eager assembly; a garment refused on the body is left off and
    named in ``garment_warnings`` (``NOT_FITTED_ON_BODY``)."""
    from app.core import model3d
    from app.core.extension_rig import extension_metadata
    from app.core.timeutils import utc_now_iso
    body_id = outfit_body_id(tsig)
    body = _snapshot_outfit_body(character_name, body_id)
    record = body["meta"]["outfit_body"]
    if (record.get("texture_signature") != tsig or record.get("version") != OUTFIT_BODY_VERSION
            or record.get("views") != texture_view_shas(character_name, signature, bsig)):
        raise OutfitError(OUTFIT_BODY_OUTDATED)
    front = dressed_image(character_name, "front", signature, bsig)
    if front is None:
        raise OutfitError(DRESSED_IMAGES_MISSING)
    manifest = model3d._ref_manifest(front)
    names = {}
    for v in record.get("used_views") or ["front"]:
        used = dressed_image(character_name, v, signature, bsig) if v in BASE_VIEWS else None
        if used is not None:
            names[v] = used.name
    out_dir = model3d.get_model3d_dir(character_name)
    path = out_dir / f"{signature}.glb"
    model3d._purge_combination(out_dir, signature, keep_model=path)
    model3d._publish_model_bytes(path, body["rigged"])
    meta = {k: v for k, v in deepcopy(body["meta"]).items() if k not in _BASE_ONLY_META and k != "outfit_body"}
    meta.update({"created_at": utc_now_iso(), "source": "base_body", "signature": signature,
                 "base_variant": variant, "covered_missing": False, "character": character_name,
                 "format": "glb", "rig": "mixamo", "base_signature": bsig,
                 "base_model_sha256": hashlib.sha256(base["rigged"]).hexdigest(),
                 "retexture_proof": None, "dressed": True, "source_image": names.get("front") or front.name,
                 "view_images": {v: n for v, n in names.items() if v != "front"},
                 "view_guard": _dict_of(record.get("view_guard")),
                 "view_warnings": [w for w in record.get("view_warnings") or [] if isinstance(w, str)],
                 "texture_signature": tsig, "outfit_body_mode": MESH_MODE, "body_id": body_id,
                 "body_sha256": hashlib.sha256(body["rigged"]).hexdigest()})
    meta.update(manifest)
    mesh = _dict_of(manifest.get("mesh_items"))
    # A mesh-mode record's "not ready" warnings are judged live (outfit_info,
    # mesh_items_missing): an accepted fit later must not leave them behind.
    warnings = ([] if isinstance(mesh.get("unpainted"), list)
                else [w for w in (mesh.get("warnings") or []) if isinstance(w, str) and w])
    from app.core.garment_assembly import body_fit_warning
    not_fitted = body_fit_warning(character_name, meta, profile=profile)
    if not_fitted:
        warnings.append(not_fitted)
    if warnings:
        meta["garment_warnings"] = warnings
    if body["prerig"] is not None:
        prerig = out_dir / "prerig" / path.name
        prerig.parent.mkdir(parents=True, exist_ok=True)
        model3d._publish_model_bytes(prerig, body["prerig"])
        model3d._publish_sidecar(prerig, {k: v for k, v in body["prerig_meta"].items() if k != "outfit_body"})
    model3d._auto_extension_rig(character_name, path, meta)
    model3d._attach_measurement(meta, path)
    meta.setdefault("extension_rig", extension_metadata(character_name, signature=path.stem))
    model3d._publish_sidecar(path, meta)
    model3d.request_lod(character_name, path)
    _assemble_garments(character_name, signature, path, meta)
    logger.info("Outfit model %s (%s on outfit body %s, texture %s)", character_name, signature, body_id, tsig)
    return {"ok": True, "cached": False, "path": str(path), "filename": path.name, "proof": None,
            "body_id": body_id}


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
    """The own-mesh warnings of a stored outfit model: the pieces it left out
    that still have no fit, judged NOW (``mesh_items_missing`` —
    ``MESH_ITEM_NOT_READY``; a mesh-mode record's every piece, a
    retexture-mode record's footwear), after the recorded ones of a
    retexture-mode record (painted on, ``MESH_ITEM_PAINTED``)."""
    mesh = _dict_of(meta.get("mesh_items"))
    live = mesh_item_warnings(mesh_items_missing(character_name, meta, base_sha=base_sha))
    if mesh_items_mode(meta) == MESH_MODE:
        return live
    return [w for w in (mesh.get("warnings") or []) if isinstance(w, str)] + live


def outfit_info(character_name: str, *, base_sig: Optional[str] = None,
                signature: Optional[str] = None) -> Dict[str, Any]:
    """``{signature, status, error, proof, url}`` of an outfit model on the
    pipeline (default: the CURRENT outfit). ``status``: ``running`` (dressed
    images or model in progress), ``failed`` (the last run's error),
    ``stale`` (the stored model was built on an older base body — or before
    the pipeline, or from the other base variant than its pieces call for
    now (``variant_current``) — and is rebuilt on the next trigger; ``error``
    says so, ``stale_reason`` ``older_base`` / ``before_pipeline`` /
    ``detail_changed`` / ``body_mode`` / ``outfit_body``
    (``outfit_body_stale``) / ``mesh_item_ready`` — an own-mesh piece it left
    painted on has its garment mesh now), ``ready``,
    ``missing``. ``warnings``: the stored model's view-guard warnings
    (dressed views left out because they turned around) and own-mesh pieces
    it left painted on (``MESH_ITEM_PAINTED``) — in mesh mode the ones it is
    missing because they have no accepted fit yet (``MESH_ITEM_NOT_READY``,
    judged now: ``_mesh_warnings``) —, then the dressed
    images' own (``dressed_warnings``). ``proof``: the
    worker's proof of the stored model (None for an undressed base copy)."""
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
    if running:
        status, error = "running", ""
    elif failure:
        status, error = "failed", failure.get("error") or ""
    elif path is None:
        status, error = "missing", ""
    elif not built_on_current_base(meta, current):
        status, error = "stale", (OLDER_BASE if meta.get("base_signature") else BEFORE_PIPELINE)
    elif not variant_current(character_name, meta):
        status, error = "stale", DETAIL_CHANGED
    elif body_reason := outfit_body_stale(character_name, meta):
        status, error = "stale", BODY_MODE_CHANGED if body_reason == "body_mode" else OUTFIT_BODY_CHANGED
    elif mesh_items_ready(character_name, meta, base_sha=current[1]):
        status, error = "stale", MESH_ITEM_READY
    else:
        status, error = "ready", ""
    return {"signature": signature, "status": status, "error": error,
            "stale_reason": (("before_pipeline" if not meta.get("base_signature")
                              else "detail_changed" if error == DETAIL_CHANGED
                              else "body_mode" if error == BODY_MODE_CHANGED
                              else "outfit_body" if error == OUTFIT_BODY_CHANGED
                              else "mesh_item_ready" if error == MESH_ITEM_READY else "older_base")
                             if status == "stale" else None),
            "warnings": (list(meta.get("view_warnings") or []) + _mesh_warnings(character_name, meta, current[1])
                         if path else []) + dressed_warnings(character_name, signature, base_sig),
            "proof": meta.get("retexture_proof") if path else None,
            "url": model3d.signature_model_url(character_name, signature) if status == "ready" else None}
