"""Clothing as its own mesh — an outfit piece in mode ``own_mesh`` (``outfit_piece.mesh_mode``)
on a base-body character (plan
``docs/superpowers/plans/2026-11-09-base-body-phase5-mesh-items.md``, Task 2;
spec ``2026-11-08-base-body-outfits-design.md``).

The kind module of garment kind ``clothing`` (``garment_set.CLOTHING``) —
the image-chain protocol of ``garment_images.kind_module``: ``EDIT_STEPS``, ``edit_prompt``, ``gate``,
``position_reference``, ``fsig_inputs`` and the pair hooks the orchestration (``garments``) calls —
``PAIR_STEP``, ``pair_agree``, ``pair_reason``, ``PAIR_REFUSED``,
``front_hints`` — plus ``SUBJECT`` for messages and ``register_estimate``
(the ghost of a waistband piece is registered by its waistband).

The image chain of the S1 spike (``claude-out/s1-base-body/src/dress_edit.py``),
shortened and said positively (Qwen2.1-Turbo ignores negatives):

- ``worn``: an edit of the bald, bare base view — the figure now wears only
  the piece (its ``prompt_fragment``, owned by the user, never derived). The
  FRONT first; the BACK in the outfit's two steps (``base_body`` draft + fit,
  shared through ``garment_images``): a DRAFT from the accepted worn front
  (``draft_prompt``: the base back prompt wearing only the piece), then the
  FIT of the draft onto the base back (``fit_prompt``: the piece's dress
  text, no other clothing). A single edit of the back view turned
  the body toward the camera (S1 spike; live "Black Blazer" 2026-11-09:
  lapels, buttons and the open V on a back view under a back-of-head), and
  ``back_reasons`` refuses a back that does not follow its front;
- ``ghost``: an edit of the accepted worn image — the piece alone, as if on
  an invisible body, the inside visible at the openings.

Unlike hair, nothing about the piece is derived from the character: the item
is the same for every wearer, the fit is per wearer (``garment_store``).

Open / closed (plan ``2026-11-12-unified-worn-pieces.md`` Task 11b, spec
Addendum A "two meshes in the same piece"): a closable piece worn OPEN is
another garment — its fragment says ``", worn open"`` (``fragment``), its
fingerprint inputs carry ``state: "open"`` (``fsig_inputs``), so it has its
own image group, mesh and fit. Closed is the identity state: its texts and
inputs are those of before the option (ruling A1). Every text reads the
state from the profile it is given (``outfit_options.piece_state_of``: a
garment run hands in its run's profile, ``outfit_options.with_item_state``).
"""
from typing import Any, Dict, Optional, Tuple

from app.core.garment_gates import GHOST_GATE_VERSION, WORN_GATE_VERSION

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
DRAFT = ("wearing only {fragment} exactly as on the person in the reference image, the same length, cut and "
         "colour, and nothing else")
#: The FIT of the worn back (``base_body.render_fit``): what the piece puts
#: on, in its own dress text (``fit_text``), and nothing else. The outfit's
#: ``base_body.FIT_PROMPT`` alone let the edit model dress the bare draft of
#: a small piece (Black Stilettos 2026-11-10: a body suit or a top and briefs
#: in 5 of 5 fits). Never the item NAME: a name may be in any language or a
#: shorthand for several garments (Kai's "Black Lederjacket", 2026-11-10:
#: the fit put nothing on in 4 of 4 attempts).
FIT = ("edit the first image with the clothes from the second image: the person wears only {fragment}, "
       "add no other clothing beyond that, the rest of the body stays exactly as in the first image")
#: ``FIT`` as comma tags, for a keywords-family backend.
FIT_KEYWORDS = "{fragment}, only these clothes, no other clothing, body unchanged from the first image"
#: The longest dress text a fit prompt names (``fit_text``).
FIT_FRAGMENT_MAX = 120
#: Position, size and width first — they are what the ghost gates measure
#: (centre / width ratio) and they stood as the last clause of 49 words
#: before the review of 2026-11-11; the removed person is said once,
#: positively, through the ghost-mannequin picture. Front and back get the
#: same text and one reference (the worn view of that side). Trousers
#: (clone, Kai, item_750811f7, 2026-11-11): the ghost BACK came out as a
#: centred product shot, ×1.59 / ×1.45 tall, attempt 1 showing the FRONT
#: (fly placket) — corrected by the waistband registration
#: (``register_estimate``), the straight legs still refuse (width 0.85).
#: Since ruling 13e ``GHOST`` is the FRONT of a piece without a waistband
#: only; the other ghosts say ``GHOST_KEEP``.
GHOST = ("The same {noun} in exactly the same position, size, width and framing, keeping its worn "
         "three-dimensional shape as if on an invisible body (ghost mannequin product photo): the person is "
         "removed, the inside of the garment is visible at the neck opening, sleeves and hem, plain grey "
         "background.")
#: The ghost of a waistband piece (both views) and the ghost BACK of every
#: other piece (ruling 13e): keep the piece as it is, name the side once,
#: then the stance (``GHOST_STANCE``), then the openings
#: (``GHOST_OPENINGS``). Measured on Qwen2.1 Turbo (clone, 2026-11-11,
#: gated after the waistband registration, ``~/claude-out/footwear/p3b/
#: ghost_back_wording.jpg``): Kai's trousers back 3 of 4 accepted — w_ratio
#: 1.021 / 1.067 (refused) / 1.015 / 0.991, outside <= 0.0144, all a real
#: back (welt pockets, legs apart); as rendered top -0.350 / -0.024 /
#: -0.030 / -0.066 Hb, so the waistband registration still does the
#: framing. ``GHOST`` there: 0 of 2 (width 0.850 / 0.844 after registration,
#: straight legs, the front's fly). Kai's leather jacket back, one seed:
#: ``GHOST_KEEP`` a real back, top +0.0187 / centre -0.0094 / width 1.002
#: (refused, outline registration 0.928 just beyond its cap); ``GHOST`` an
#: open FRONT with the lining shown, +0.0259 / -0.0130 / 0.941 (refused) —
#: worse on every number, so tops take it for the back. The trousers FRONT
#: (never rendered before): ``GHOST_KEEP`` with "seen from the front" ×1.19
#: wide, top -0.142 Hb (``GHOST`` ×1.37, -0.323) — refused under the capped
#: outline registration; with the waistband registration it would pass
#: (w_ratio 1.003, outside 0.023) — so it registers the front too (ruling 13f).
GHOST_KEEP = ("Keep the {noun} exactly as it is, {side}: the same position, outer outline, width and framing, "
              "{stance}, the same background. Remove the person completely so the {noun} keeps its worn "
              "three-dimensional shape on an invisible body (ghost mannequin product photo); the inside is "
              "visible at {openings}.")
GHOST_SIDE = {"front": "seen from the front", "back": "seen from behind"}
#: Per kind of piece: waistband pieces (``garment_gates.waistband_piece``) / the rest.
GHOST_STANCE = {True: "the legs apart at exactly the same angle as in the image",
                False: "the sleeves at exactly the same angle as in the image"}
GHOST_OPENINGS = {True: "the waistband and the leg openings", False: "the neck opening, sleeves and hem"}
#: The noun of a piece without a name.
DEFAULT_NOUN = "garment"
#: The ghost's extra negative terms (spike ``NEG_GHOST``); the use case
#: ``garment_edit`` adds the shared part. Kept for backends that read
#: negatives — the prompts say everything positively.
GHOST_NEGATIVE = ("person", "skin", "head", "arms", "hands", "legs", "feet", "mannequin", "hanger")
#: The gate version per step whose gate changed since attempts were stored
#: (``garment_images``: a refused view re-gates its stored attempts of an
#: older version before it renders again). ``ghost`` 2 (2026-11-12): the
#: position is recorded, the width widened, skin sampled on the thighs —
#: a refused ghost view whose stored attempts pass now is published from
#: its files on the next run (Retry), without an image job. ``worn`` 3 /
#: ``ghost`` 3 (2026-11-12, the gate audit): the worn piece share and an
#: edit's outline drift widened, the ghost's ``outside`` counts only parts
#: beyond 0.02·Hb and the waistband hem leaves strands out; a registered
#: ghost attempt is re-gated from its raw sibling (``garment_images``).
GATE_VERSIONS: Dict[str, int] = {"worn": WORN_GATE_VERSION, "ghost": GHOST_GATE_VERSION}
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


def fragment(item: Dict[str, Any], *, state: str = "closed") -> str:
    """The piece's ``prompt_fragment``, whitespace-normalised, without a
    trailing full stop ("" when unset); ``state`` ``open`` appends
    ``", worn open"`` (``outfit_options.OPEN_WORDS``) to a set fragment,
    closed is the fragment alone (ruling A1)."""
    from app.core.outfit_options import OPEN, OPEN_WORDS
    text = " ".join(str(item.get("prompt_fragment") or "").split()).rstrip(".").strip()
    return f"{text}, {OPEN_WORDS}" if text and state == OPEN else text


def state_of(item: Dict[str, Any], profile: Optional[Dict[str, Any]], state: Optional[str] = None) -> str:
    """The state a clothing piece is made in: ``state`` when given (``open`` / ``closed``), else the profile's
    worn state (``outfit_options.piece_state_of``); always ``closed`` for an item that is not closable
    (``garment_set.closable_of``). ValueError for another state."""
    from app.core.garment_set import closable_of
    from app.core.outfit_options import CLOSED, normalise_piece_state, piece_state_of
    if not closable_of(item):
        return CLOSED
    if state is not None:
        return normalise_piece_state(state)
    return piece_state_of(profile or {}, str(item.get("id") or ""))


def garment_noun(item: Dict[str, Any]) -> str:
    """The noun of the ghost prompt: the item's name in lower case
    ("Green Dress" -> "green dress"), ``"garment"`` without a name."""
    name = " ".join(str(item.get("name") or "").split())
    return name.lower() if name else DEFAULT_NOUN


def fsig_inputs(character_name: str, item: Dict[str, Any], *,
                profile: Optional[Dict[str, Any]] = None, state: Optional[str] = None) -> Dict[str, Any]:
    """What a clothing piece contributes to the garment fingerprint
    (``garment_store.garment_fsig``): its prompt fragment, its noun (the
    lower-cased name the ghost prompt says — a rename re-renders the ghost),
    slots, covers, partially covers and the pronouns of the character's
    profile. Worn OPEN (``state``, None → the profile's worn state,
    ``state_of``) the fragment says ``", worn open"`` and ``state: "open"``
    is added; closed inputs are those of before the option, byte for byte."""
    from app.core.garment_hair import pronouns
    from app.core.outfit_options import OPEN
    item = _item_of(item)
    piece = item.get("outfit_piece") or {}
    prof = _profile_of(character_name, profile)
    worn = state_of(item, prof, state)
    out = {"prompt_fragment": fragment(item, state=worn), "noun": garment_noun(item),
           "slots": sorted(str(s) for s in piece.get("slots") or []),
           "covers": sorted(str(s) for s in piece.get("covers") or []),
           "partially_covers": sorted(str(s) for s in piece.get("partially_covers") or []),
           "pronouns": list(pronouns(prof))}
    if worn == OPEN:
        out["state"] = OPEN
    return out


def _worn_negative(text: str, *, keep_hair: bool = False) -> str:
    """The spike's garment terms (``base_body.DRESS_GARMENT_NEGATIVE``) minus
    the ones the piece's text names; ``keep_hair`` (the worn edit of a haired
    base, ``base_body.hair_text``) leaves "hair" out too."""
    from app.core.base_body import dress_garment_terms
    return ", ".join(dress_garment_terms(text, keep_hair=keep_hair))


def edit_prompt(character_name: str, step: str, view: str, *,
                profile: Optional[Dict[str, Any]] = None, item_id: Optional[str] = None) -> Tuple[str, str]:
    """``(prompt, extra negative)`` of one clothing edit.

    ``worn`` FRONT (the base view): "Keep the image exactly as it is. Only
    change their clothing: they now wear only {prompt_fragment}." — the
    fragment in the state ``profile`` wears the piece in (``state_of``: open
    adds ", worn open"); the worn
    BACK is no edit (``draft_prompt``, then ``fit_prompt``).
    ``ghost`` (the worn image): the piece alone, the item's name as the
    noun — ``ghost_prompt``. ValueError for an unknown step or
    view, the worn back, a missing item, or a piece without a prompt
    fragment."""
    if step not in EDIT_STEPS:
        raise ValueError(f"no clothing edit step {step!r}")
    if view not in ("front", "back"):
        raise ValueError(f"no clothing edit view {view!r}")
    if step == "worn" and view == "back":
        raise ValueError("the worn back is drafted from the worn front — draft_prompt, then the fit")
    item = _item_of(item_id)
    prof = _profile_of(character_name, profile)
    text = _fragment_of(item, state=state_of(item, prof))
    if step == "worn":
        from app.core.base_body import hair_text
        haired = bool(hair_text(character_name, profile=prof))
        return WORN.format(fragment=text), _worn_negative(text, keep_hair=haired)
    negative = ", ".join(t for t in (_worn_negative(text), *GHOST_NEGATIVE) if t)
    slots = (item.get("outfit_piece") or {}).get("slots") or []
    return ghost_prompt(garment_noun(item), slots, view), negative


def ghost_prompt(noun: str, slots, view: str) -> str:
    """The ghost prompt of a piece with ``slots`` for ``view``: ``GHOST_KEEP``
    for a waistband piece (both views) and for every back (the side, the
    stance and the openings of its kind), ``GHOST`` for the front of a piece
    without a waistband."""
    from app.core.garment_gates import waistband_piece
    waist = waistband_piece(slots)
    if view == "front" and not waist:
        return GHOST.format(noun=noun)
    return GHOST_KEEP.format(noun=noun, side=GHOST_SIDE[view], stance=GHOST_STANCE[waist],
                             openings=GHOST_OPENINGS[waist])


def _fragment_of(item: Dict[str, Any], *, state: str = "closed") -> str:
    text = fragment(item, state=state)
    if not text:
        raise ValueError(f"{item.get('name') or item.get('id')} has no prompt fragment — fill it in under Items")
    return text


def draft_prompt(character_name: str, step: str, *, profile: Optional[Dict[str, Any]] = None,
                 item_id: Optional[str] = None) -> Tuple[str, str]:
    """``(prompt, negative)`` of the DRAFT of the worn back
    (``base_body.draft_prompt`` with ``DRAFT`` as the body text — the base
    back prompt, the bald head, wearing only the piece); negative: the
    draft's + the worn negative (the garment words the fragment does not
    name; the fragment in the state ``profile`` wears the piece in,
    ``state_of``). ValueError for another step, a missing item or no
    fragment."""
    from app.core import base_body
    if EDIT_STEPS.get(step, {}).get("back") != "draft":
        raise ValueError(f"the clothing step {step!r} has no drafted back")
    item = _item_of(item_id)
    prof = _profile_of(character_name, profile)
    text = _fragment_of(item, state=state_of(item, prof))
    prompt, negative = base_body.draft_prompt(character_name, "back", profile=prof,
                                              outfit_text=DRAFT.format(fragment=text))
    return prompt, ", ".join(p for p in (negative, _worn_negative(text)) if p)


def fit_text(text: str, limit: int = FIT_FRAGMENT_MAX) -> str:
    """The dress text a fit names: ``text`` (the piece's fragment, as the
    worn front says it) when it has at most ``limit`` characters, else its
    leading comma-separated parts that fit — at least the first part, cut
    at a word boundary when it alone is longer."""
    if len(text) <= limit:
        return text
    kept = ""
    for part in (p.strip() for p in text.split(",")):
        joined = f"{kept}, {part}" if kept else part
        if len(joined) > limit:
            break
        kept = joined
    if kept:
        return kept
    return text[:limit + 1].rsplit(" ", 1)[0].rstrip(" ,;")


def fit_prompt(step: str, *, item_id: Optional[str] = None, state: str = "closed") -> Tuple[str, str]:
    """``(prompt, keywords prompt)`` of the FIT of the worn back: ``FIT`` /
    ``FIT_KEYWORDS`` with the piece's dress text (``fit_text`` of its
    fragment in ``state``: open adds ", worn open" for a closable piece).
    ValueError for a step without a drafted back, a missing item or a piece
    without a prompt fragment."""
    if EDIT_STEPS.get(step, {}).get("back") != "draft":
        raise ValueError(f"the clothing step {step!r} has no drafted back")
    item = _item_of(item_id)
    text = fit_text(_fragment_of(item, state=state_of(item, None, state)))
    return FIT.format(fragment=text), FIT_KEYWORDS.format(fragment=text)


def back_reasons(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> list:
    """The reasons a worn back attempt does not follow the accepted worn
    front (``garment_gates.back_follows_front``: the front opening on the
    back, a garment the front does not have)."""
    from app.core.garment_gates import back_follows_front
    return back_follows_front(front_gate, back_gate)


def gate(step: str, view: str, *, base_rgb, base_mask, source_rgb, source_mask,
         edit_rgb, edit_mask, item_id: Optional[str] = None, fitted: bool = False,
         front_gate: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The gate record of one attempt (``garment_gates``): ``worn`` against
    the base view — the zones the piece is worn on (its slots,
    ``garment_gates.occupied_zones``: a hat frees the head) are not checked;
    a ``fitted`` view (the drafted back) has the outline limits
    ``garment_gates.FIT_OUTSIDE_XOR_MAX`` / ``FIT_OUTSIDE_DRIFT_PX``, and
    with the accepted front's record ``front_gate`` it measures what it puts
    on outside the front garment's rows (``extra_part``, ``back_reasons``);
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
                                                 else garment_gates.OUTSIDE_DRIFT_PX),
                                       front_rows=(garment_gates.garment_rows(front_gate)
                                                   if front_gate else None))
    if step == "ghost":
        region = garment_gates.garment_region(base_rgb, base_mask, source_rgb, source_mask)
        return garment_gates.ghost_clothing_gate(base_rgb, base_mask, region, edit_rgb, edit_mask, view=view,
                                                 length_free=_waistband_ghost(step, item_id))
    raise ValueError(f"no clothing edit step {step!r}")


def _waistband_ghost(step: str, item_id: Any) -> bool:
    """A ghost (either view) of a piece whose top edge is a waistband
    (``garment_gates.waistband_piece`` of its slots; ``item_id`` an id or the
    item itself). Ruling 13d registered the back, 13f the front too: the
    trousers front reframed the same way (×1.19..1.37 wide)."""
    if step != "ghost" or not item_id:
        return False
    from app.core.garment_gates import waistband_piece
    return waistband_piece((_item_of(item_id).get("outfit_piece") or {}).get("slots") or [])


def register_estimate(step: str, view: str, reference, ghost_mask, *, body_h: int,
                      item_id: Any = None) -> Optional[Dict[str, Any]]:
    """The correction ``garment_images._register`` applies before the gate:
    the ghost of a waistband piece (both views) by its waistband
    (``garment_gates.register_waistband``: one uniform scale, the top and
    the waistband centre aligned, no outline caps (a scale outside
    ``WAIST_SCALE_RANGE`` is a failed measurement) — ruling 13d: the edit model
    turned the trousers' back into a centred product shot, ×1.45..1.59 tall;
    13f: the front, too);
    everything else by its outline (``garment_gates.register``, capped)."""
    from app.core import garment_gates
    if _waistband_ghost(step, item_id):
        return garment_gates.register_waistband(reference, ghost_mask, body_h=body_h)
    return garment_gates.register(reference, ghost_mask, body_h=body_h)


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
    """Front and back ghost end at the same height (``garment_gates.hems_agree``)
    — always True against a back registered by its waistband (``registered``):
    its hem is the edit's length scaled by the waistband, not a measurement
    (ruling 13d: the length does not matter)."""
    from app.core.garment_gates import hems_agree
    return bool(back_gate.get("registered")) or hems_agree(front_gate, back_gate)


def pair_reason(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> Optional[str]:
    """The refusal reason of a front ghost attempt against the accepted back
    (``garment_gates.hems_reason``); None against a back registered by its
    waistband (``pair_agree``)."""
    from app.core.garment_gates import hems_reason
    return None if back_gate.get("registered") else hems_reason(front_gate, back_gate)


def front_hints(character_name: str, item_id: str, fsig: str, step: str, view: str) -> Optional[Dict[str, Any]]:
    """No prompt hints: the worn and ghost prompts need nothing from the back."""
    return None
