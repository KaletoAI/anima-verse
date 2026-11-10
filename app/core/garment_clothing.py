"""Clothing as its own mesh — an outfit piece flagged ``outfit_piece.own_mesh``
on a base-body character (plan
``docs/superpowers/plans/2026-11-09-base-body-phase5-mesh-items.md``, Task 2;
spec ``2026-11-08-base-body-outfits-design.md``).

The kind module of garment kind ``clothing`` (``garment_set.CLOTHING``), the
same protocol as ``garment_hair``: ``EDIT_STEPS``, ``edit_prompt``, ``gate``,
``position_reference``, ``fsig_inputs`` and the pair hooks the orchestration (``garments``) calls —
``PAIR_STEP``, ``pair_agree``, ``pair_reason``, ``PAIR_REFUSED``,
``front_hints`` — plus ``SUBJECT`` for messages.

The image chain of the S1 spike (``claude-out/s1-base-body/src/dress_edit.py``),
shortened and said positively (Qwen2.1-Turbo ignores negatives):

- ``worn``: an edit of the bald, bare base view — the figure now wears only
  the piece (its ``prompt_fragment``, owned by the user, never derived). The
  FRONT first; the BACK in the outfit's two steps (``base_body`` draft + fit,
  shared through ``garment_images``): a DRAFT from the accepted worn front
  (``draft_prompt``: the base back prompt wearing only the piece), then the
  FIT of the draft onto the base back. A single edit of the back view turned
  the body toward the camera (S1 spike; live "Black Blazer" 2026-11-09:
  lapels, buttons and the open V on a back view under a back-of-head), and
  ``back_reasons`` refuses a back that does not follow its front;
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
#: ``views``: the render order of a step's views (default
#: ``garments.EDIT_VIEW_ORDER``, the back first); ``back: "draft"``: the
#: back is drafted from the step's accepted front and fitted onto the base
#: back (``garment_images.run_edit_step``) — so the front renders first.
EDIT_STEPS: Dict[str, Dict[str, Any]] = {"worn": {"source": "base", "views": ("front", "back"),
                                                  "back": "draft"},
                                         "ghost": {"source": "worn"}}

WORN = "Keep the image exactly as it is. Only change their clothing: they now wear only {fragment}."
#: The body text of the worn back's draft (``base_body.draft_prompt``): the
#: piece alone in the text, the same fragment as the front — the reference
#: (the accepted worn front) shows how it looks.
DRAFT = ("wearing only {fragment}, the same garment as on the person in the reference image, with the same "
         "length, cut and colour")
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
    (``garment_store.garment_fsig``): its prompt fragment, its noun (the
    lower-cased name the ghost prompt says — a rename re-renders the ghost),
    slots, covers, partially covers and the pronouns of the character's
    profile."""
    from app.core.garment_hair import pronouns
    item = _item_of(item)
    piece = item.get("outfit_piece") or {}
    return {"prompt_fragment": fragment(item), "noun": garment_noun(item),
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

    ``worn`` FRONT (the base view): "Keep the image exactly as it is. Only
    change their clothing: they now wear only {prompt_fragment}." — the worn
    BACK is no edit (``draft_prompt``, then ``base_body.FIT_PROMPT``).
    ``ghost`` (the worn image): the piece alone (``GHOST`` with the item's
    name as the noun), both views alike. ValueError for an unknown step or
    view, the worn back, a missing item, or a piece without a prompt
    fragment."""
    if step not in EDIT_STEPS:
        raise ValueError(f"no clothing edit step {step!r}")
    if view not in ("front", "back"):
        raise ValueError(f"no clothing edit view {view!r}")
    if step == "worn" and view == "back":
        raise ValueError("the worn back is drafted from the worn front — draft_prompt, then the fit")
    item = _item_of(item_id)
    text = _fragment_of(item)
    if step == "worn":
        return WORN.format(fragment=text), _worn_negative(text)
    negative = ", ".join(t for t in (_worn_negative(text), *GHOST_NEGATIVE) if t)
    return GHOST.format(noun=garment_noun(item)), negative


def _fragment_of(item: Dict[str, Any]) -> str:
    text = fragment(item)
    if not text:
        raise ValueError(f"{item.get('name') or item.get('id')} has no prompt fragment — fill it in under Items")
    return text


def draft_prompt(character_name: str, step: str, *, profile: Optional[Dict[str, Any]] = None,
                 item_id: Optional[str] = None) -> Tuple[str, str]:
    """``(prompt, negative)`` of the DRAFT of the worn back
    (``base_body.draft_prompt`` with ``DRAFT`` as the body text — the base
    back prompt, the bald head, wearing only the piece); negative: the
    draft's + the worn negative (the garment words the fragment does not
    name). ValueError for another step, a missing item or no fragment."""
    from app.core import base_body
    if EDIT_STEPS.get(step, {}).get("back") != "draft":
        raise ValueError(f"the clothing step {step!r} has no drafted back")
    text = _fragment_of(_item_of(item_id))
    prompt, negative = base_body.draft_prompt(character_name, "back", profile=_profile_of(character_name, profile),
                                              outfit_text=DRAFT.format(fragment=text))
    return prompt, ", ".join(p for p in (negative, _worn_negative(text)) if p)


def back_reasons(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> list:
    """The reasons a worn back attempt does not follow the accepted worn
    front (``garment_gates.back_follows_front``: the front opening on the
    back)."""
    from app.core.garment_gates import back_follows_front
    return back_follows_front(front_gate, back_gate)


def gate(step: str, view: str, *, base_rgb, base_mask, source_rgb, source_mask,
         edit_rgb, edit_mask, item_id: Optional[str] = None, fitted: bool = False) -> Dict[str, Any]:
    """The gate record of one attempt (``garment_gates``): ``worn`` against
    the base view — the zones the piece is worn on (its slots,
    ``garment_gates.occupied_zones``: a hat frees the head) are not checked;
    a ``fitted`` view (the drafted back) has the outline limits
    ``garment_gates.FIT_OUTSIDE_XOR_MAX`` / ``FIT_OUTSIDE_DRIFT_PX``;
    ``ghost`` against the garment region of the accepted worn image
    (``source``). All arrays share the base view's size."""
    from app.core import garment_gates
    if step == "worn":
        slots = ((_item_of(item_id).get("outfit_piece") or {}).get("slots") or []) if item_id else []
        return garment_gates.worn_gate(base_rgb, base_mask, edit_rgb, edit_mask, view=view,
                                       occupied=garment_gates.occupied_zones(slots),
                                       xor_max=(garment_gates.FIT_OUTSIDE_XOR_MAX if fitted
                                                else garment_gates.OUTSIDE_XOR_MAX),
                                       drift_px=(garment_gates.FIT_OUTSIDE_DRIFT_PX if fitted
                                                 else garment_gates.OUTSIDE_DRIFT_PX))
    if step == "ghost":
        region = garment_gates.garment_region(base_rgb, base_mask, source_rgb, source_mask)
        return garment_gates.ghost_clothing_gate(base_rgb, base_mask, region, edit_rgb, edit_mask, view=view)
    raise ValueError(f"no clothing edit step {step!r}")


def position_reference(step: str, *, base_rgb, base_mask, source_rgb, source_mask):
    """The mask an attempt of ``step`` is registered onto before its gate
    (``garment_gates.register``): for ``ghost`` the garment region of the
    accepted worn image — the region its position gate measures against;
    None for ``worn`` (an edit of the base view, nothing to register)."""
    from app.core import garment_gates
    if step != "ghost":
        return None
    return garment_gates.garment_region(base_rgb, base_mask, source_rgb, source_mask)


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
