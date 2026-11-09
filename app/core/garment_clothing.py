"""Clothing as its own mesh — an outfit piece flagged ``outfit_piece.own_mesh``
on a base-body character (plan
``docs/superpowers/plans/2026-11-09-base-body-phase5-mesh-items.md``, Task 2;
spec ``2026-11-08-base-body-outfits-design.md``).

The kind module of garment kind ``clothing`` (``garment_set.CLOTHING``), the
same protocol as ``garment_hair``: ``EDIT_STEPS``, ``edit_prompt``, ``gate``,
``fsig_inputs`` and the pair hooks the orchestration (``garments``) calls —
``PAIR_STEP``, ``pair_agree``, ``pair_reason``, ``PAIR_REFUSED``,
``front_hints`` — plus ``SUBJECT`` for messages.

The image chain of the S1 spike (``claude-out/s1-base-body/src/dress_edit.py``),
shortened and said positively (Qwen2.1-Turbo ignores negatives):

- ``worn``: an edit of the bald, bare base view — the figure now wears only
  the piece (its ``prompt_fragment``, owned by the user, never derived);
- ``ghost``: an edit of the accepted worn image — the piece alone, as if on
  an invisible body, the inside visible at the openings.

Unlike hair, nothing about the piece is derived from the character: the item
is the same for every wearer, the fit is per wearer (``garment_store``).
"""
import re
from typing import Any, Dict, Optional, Tuple

KIND = "clothing"
#: What the messages call the thing in the images ("No garment found …").
SUBJECT = "garment"

#: The edit steps and what each edits (no character LoRAs, like hair).
EDIT_STEPS: Dict[str, Dict[str, str]] = {"worn": {"source": "base"},
                                         "ghost": {"source": "worn"}}

WORN = "Keep the image exactly as it is. Only change their clothing: they now wear only {fragment}."
GHOST = ("The same {noun} alone, as if worn by an invisible person (ghost mannequin): no head, no arms, no "
         "hands, no legs, no feet, no skin; where the neck opening, sleeves and hem are, the inside of the "
         "garment is visible. Same position, size and framing, plain grey background.")
#: The noun of a piece without a name.
DEFAULT_NOUN = "garment"
#: The ghost's extra negative terms (spike ``NEG_GHOST``); the use case
#: ``garment_edit`` adds the shared part. Kept for backends that read
#: negatives — the prompts say everything positively.
GHOST_NEGATIVE = ("person", "skin", "head", "arms", "hands", "legs", "feet", "mannequin", "hanger")
#: The pair check: the front ghost against the accepted back ghost.
PAIR_STEP = "ghost"
PAIR_REFUSED = "front and back garment end at different heights"


def _profile_of(character_name: str, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if profile is not None:
        return profile
    from app.models.character import get_character_profile
    return get_character_profile(character_name) or {}


def _item_of(item: Any) -> Dict[str, Any]:
    if isinstance(item, dict):
        return item
    from app.models.inventory import get_item
    found = get_item(item) if isinstance(item, str) and item else None
    if not found:
        raise ValueError(f"{str(item)[:80]!r} is no item")
    return found


def fragment(item: Dict[str, Any]) -> str:
    """The piece's ``prompt_fragment``, whitespace-normalised, without a
    trailing full stop ("" when unset)."""
    return " ".join(str(item.get("prompt_fragment") or "").split()).rstrip(".").strip()


def garment_noun(item: Dict[str, Any]) -> str:
    """The noun of the ghost prompt: the item's name in lower case
    ("Green Dress" -> "green dress"), ``"garment"`` without a name."""
    name = " ".join(str(item.get("name") or "").split())
    return name.lower() if name else DEFAULT_NOUN


def fsig_inputs(character_name: str, item: Dict[str, Any], *,
                profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What a clothing piece contributes to the garment fingerprint
    (``garment_store.garment_fsig``): its prompt fragment, slots, covers,
    partially covers and the pronouns of the character's profile."""
    from app.core.garment_hair import pronouns
    item = _item_of(item)
    piece = item.get("outfit_piece") or {}
    return {"prompt_fragment": fragment(item),
            "slots": sorted(str(s) for s in piece.get("slots") or []),
            "covers": sorted(str(s) for s in piece.get("covers") or []),
            "partially_covers": sorted(str(s) for s in piece.get("partially_covers") or []),
            "pronouns": list(pronouns(_profile_of(character_name, profile)))}


def _worn_negative(text: str) -> str:
    """The spike's garment terms (``base_body.DRESS_GARMENT_NEGATIVE``) minus
    the ones the piece's text names."""
    from app.core.base_body import DRESS_GARMENT_NEGATIVE
    return ", ".join(term for term, pattern in DRESS_GARMENT_NEGATIVE
                     if not re.search(rf"\b(?:{pattern})\b", text or "", re.IGNORECASE))


def edit_prompt(character_name: str, step: str, view: str, *,
                profile: Optional[Dict[str, Any]] = None, item_id: Optional[str] = None) -> Tuple[str, str]:
    """``(prompt, extra negative)`` of one clothing edit.

    ``worn`` (the base view): "Keep the image exactly as it is. Only change
    their clothing: they now wear only {prompt_fragment}." — the back opened
    by ``base_body.DRESS_VIEW["back"]``. ``ghost`` (the worn image): the
    piece alone (``GHOST`` with the item's name as the noun), both views
    alike. ValueError for an unknown step or view, a missing item, or a piece
    without a prompt fragment."""
    from app.core.base_body import DRESS_VIEW
    if step not in EDIT_STEPS:
        raise ValueError(f"no clothing edit step {step!r}")
    if view not in ("front", "back"):
        raise ValueError(f"no clothing edit view {view!r}")
    item = _item_of(item_id)
    text = fragment(item)
    if not text:
        raise ValueError(f"{item.get('name') or item.get('id')} has no prompt fragment — fill it in under Items")
    if step == "worn":
        prompt = WORN.format(fragment=text)
        if view == "back":
            prompt = f"{DRESS_VIEW['back']} {prompt}"
        return prompt, _worn_negative(text)
    negative = ", ".join(t for t in (_worn_negative(text), *GHOST_NEGATIVE) if t)
    return GHOST.format(noun=garment_noun(item)), negative


def gate(step: str, view: str, *, base_rgb, base_mask, source_rgb, source_mask,
         edit_rgb, edit_mask) -> Dict[str, Any]:
    """The gate record of one attempt (``garment_gates``): ``worn`` against
    the base view; ``ghost`` against the garment region of the accepted worn
    image (``source``). All arrays share the base view's size."""
    from app.core import garment_gates
    if step == "worn":
        return garment_gates.worn_gate(base_rgb, base_mask, edit_rgb, edit_mask, view=view)
    if step == "ghost":
        region = garment_gates.garment_region(base_rgb, base_mask, source_rgb, source_mask)
        return garment_gates.ghost_clothing_gate(base_rgb, base_mask, region, edit_rgb, edit_mask, view=view)
    raise ValueError(f"no clothing edit step {step!r}")


def pair_agree(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> bool:
    """Front and back ghost end at the same height (``garment_gates.hems_agree``)."""
    from app.core.garment_gates import hems_agree
    return hems_agree(front_gate, back_gate)


def pair_reason(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> Optional[str]:
    """The refusal reason of a front ghost attempt against the accepted back
    (``garment_gates.hems_reason``)."""
    from app.core.garment_gates import hems_reason
    return hems_reason(front_gate, back_gate)


def front_hints(character_name: str, item_id: str, fsig: str, step: str, view: str) -> Optional[Dict[str, Any]]:
    """No prompt hints: the worn and ghost prompts need nothing from the back."""
    return None
