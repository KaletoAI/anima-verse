"""Clothing as its own mesh — an outfit piece in mode ``own_mesh`` (``outfit_piece.mesh_mode``)
on a base-body character (plan
``docs/superpowers/plans/2026-11-09-base-body-phase5-mesh-items.md``, Task 2;
spec ``2026-11-08-base-body-outfits-design.md``).

The kind module of garment kind ``clothing`` (``garment_set.CLOTHING``) —
the image-chain protocol of ``garment_images.kind_module``: ``EDIT_STEPS``, ``edit_prompt``, ``gate``,
``position_reference``, ``fsig_inputs`` and the pair hooks the orchestration (``garments``) calls —
``PAIR_STEP``, ``pair_agree``, ``pair_reason``, ``pair_repair_reason``,
``pair_redo``, ``PAIR_REFUSED``, ``front_hints``, ``REGATE_ACCEPTED_STEPS``
(Ruling A17) — plus ``SUBJECT`` for messages and ``register_estimate``
(the ghost of a waistband piece is registered by its waistband).

The image chain of the S1 spike (``claude-out/s1-base-body/src/dress_edit.py``),
shortened and said positively (Qwen2.1-Turbo ignores negatives):

- ``worn``: an edit of the bald, bare base view — the figure now wears only
  the piece (its ``prompt_fragment``, owned by the user, never derived). The
  FRONT first; the BACK in the outfit's two steps (``base_body`` draft +
  composite, shared through ``garment_images``): a DRAFT from the accepted
  worn front (``draft_prompt``: the outfit's back draft sentence — a view
  change, so it never names the piece, Ruling A29), then the CPU COMPOSITE
  of the draft's piece onto the base back
  (``view_composite``, rule "piece"; Task 11g, Ruling C1 — it replaced the
  model FIT and its prompt). A single edit of the back view turned
  the body toward the camera (S1 spike; live "Black Blazer" 2026-11-09:
  lapels, buttons and the open V on a back view under a back-of-head), and
  ``back_reasons`` refuses a back that does not follow its front;
- ``ghost``: an edit of the accepted worn image — the piece alone, as if on
  an invisible mannequin, the inside visible at the openings (the user's
  wording, Ruling A57).

Unlike hair, nothing about the piece is derived from the character: the item
is the same for every wearer, the mesh fit is per wearer (``garment_store``).

Back text (Task 11e, Ruling V1): the BACK texts of the chain — the worn
back draft's negative, the ghost back's negative — are built from the
piece's back description (``piece_back_text.back_text``: the optional item
field ``prompt_fragment_back``, else the front text as before); the worn
back draft's PROMPT names no clothing at all (Ruling A29). The fingerprint names the back text
only when it is set and differs from the front (``fsig_inputs``): a piece
without one keeps its keys. The worn FRONT and the ghost front are unchanged.

Open / closed (plan ``2026-11-12-unified-worn-pieces.md`` Task 11b, spec
Addendum A "two meshes in the same piece"): a closable piece worn OPEN is
another garment — its fragment says it is worn open at the front
(``fragment``, ``outfit_options.OPEN_IMAGE_WORDS``), its
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
#: back is drafted from the step's accepted front and composited onto the
#: base back (``garment_images.run_edit_step``) — so the front renders first.
EDIT_STEPS: Dict[str, Dict[str, Any]] = {"worn": {"source": "base", "views": ("front", "back"),
                                                  "back": "draft"},
                                         "ghost": {"source": "worn"}}

WORN = "Keep the image exactly as it is. Only change their clothing: they now wear only {fragment}."
#: Ruling A147: a closable piece (``garment_set.closable_of``) worn CLOSED says so in its worn FRONT edit — the
#: piece is worn alone, and "they now wear only <cardigan>" let the edit model hang it wide open over the bare
#: body (hub job 529572e5). Only the front CLOSURE is named: an intended V neckline / lapel opening stays (A51).
#: Not added when the fragment already names a state (``outfit_options.fragment_names_state``: "worn open" in
#: the item text wins) nor in the fingerprint (``fragment``): closed inputs stay byte for byte, nothing re-renders.
WORN_CLOSED = ("worn closed, its fronts fastened together at the centre (buttoned / zipped / wrapped shut), "
               "any designed neckline or lapel opening kept as it is")
#: The ghost texts (Ruling A57, 2026-11-14). The base text of EVERY ghost
#: view is the USER'S OWN prompt, word for word (hub job 29e09f8a, Qwen
#: image edit: an off-shoulder blouse, the person removed, the inside of the
#: neckline and hem shown, pose and position kept) — do not "improve" it;
#: change it only on the user's word. The older wording ("The same {noun} …"
#: / ``GHOST_KEEP`` "Keep the {noun} exactly as it is …", see git history) was
#: measured on 2026-11-11: a back without its side drew a front and waistband
#: legs came out straight — hence the side and stance lines after the user's text.
#: User decision 2026-11-17 (A183): the first sentence alone is the text of a piece without a collar, sleeves or
#: hem to reconstruct (a bra, gloves, arm / leg warmers, a belt, a harness …) — the user's tested hub jobs ae52d455
#: (bra back) and fb597ef6 (opera gloves back) used exactly it plus the side line.
GHOST_PLAIN = ("Remove the person completely, leaving only the clothes in the exact same position, pose, and shape "
               "as if worn by an invisible mannequin.")
GHOST = (GHOST_PLAIN + " Reconstruct the inside of the collar, sleeves, and hem "
         "naturally, and fill in the background behind the removed body parts seamlessly.")
#: A waistband piece (``garment_gates.waistband_piece``, both views): its openings in place of the collar's.
GHOST_WAISTBAND = GHOST.replace("the collar, sleeves, and hem", "the waistband and the leg openings")
#: The ghost text classes (A183), ``ghost_text_class``: the stored choice ``outfit_piece.ghost_text`` when it names
#: one, else by the slots — a waistband piece, a piece on ``COLLAR_SLOTS``, every other piece ``plain``.
GHOST_TEXTS = {"collar": GHOST, "waistband": GHOST_WAISTBAND, "plain": GHOST_PLAIN}
#: The slots whose pieces have a collar, sleeves and a hem by default (tops, dresses, jackets, coats, shirts). A bra
#: slotted ``top`` or gloves slotted ``outer`` say so with the piece's "Piece-only text" choice (``ghost_text``).
COLLAR_SLOTS = frozenset({"top", "outer"})
#: After the user's text on every BACK view — and (A185) on the side views of a shell piece with "Side views for the
#: shell", each naming the way the figure faces as the base view of that name does ("left" = profile facing the left
#: edge of the frame, ``base_body.DRAFT_PROMPTS``).
GHOST_SIDE = {"back": "Seen from behind; the back view stays a back view.",
              "left": "Seen from the side, facing left; the side view stays a side view.",
              "right": "Seen from the side, facing right; the side view stays a side view."}
#: The views a clothing edit knows (A185: the side views of a shell piece).
EDIT_VIEWS = ("front", "back", "left", "right")
#: After the user's text (and the side) on both views of a waistband piece.
GHOST_STANCE = "The legs stay apart at exactly the same angle as in the image."
#: The noun of a piece without a name (``garment_noun``).
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
#: ``ghost`` 5 (Ruling A27, 2026-11-13): a ghost refused by its hem alone
#: within ``garment_gates.HEM_SNAP_MAX`` is snapped to the worn hem
#: (``hem_snap``) — the attempts refused under 4 are judged again first.
#: ``ghost`` 6 (Ruling A32, 2026-11-13): ``skin_left`` counts a pixel as skin
#: only when it is nearer the skin than the piece in the same light, off the
#: ghost's outline (``garment_gates.skin_pixels``) — the attempts refused
#: under 5 are judged again first.
#: ``ghost`` 7 (Ruling A46, 2026-11-14): a part the ghost adds beyond the
#: worn piece is refused by its reach (``garment_gates.added_parts``: a
#: strap drawn on a strapless piece) — an ACCEPTED ghost re-gated so is stale.
GATE_VERSIONS: Dict[str, int] = {"worn": WORN_GATE_VERSION, "ghost": GHOST_GATE_VERSION}
#: The steps whose ACCEPTED images are re-gated from their files when their
#: record predates the step's gate version (``garment_images.regate_accepted``,
#: Ruling A17 d), each with the record keys that make such an image STALE
#: (rendered again, not reused): ``ghost`` 4 gates the hem against the worn
#: piece (``hem_refused``: a stored ghost back that hangs below its worn back)
#: and a closable front's open / closed look (``look_refused``). A re-gated
#: image refused for an older rule only records it and stays in use.
#: ``ghost`` 7 adds ``added_refused`` (Ruling A46: a strap the worn piece does not have).
REGATE_ACCEPTED_STEPS: Dict[str, Tuple[str, ...]] = {"ghost": ("hem_refused", "look_refused", "added_refused")}
#: The pair check (Ruling A17): a front ghost attempt against the WORN back's
#: hem (``pair_reason``), the accepted ghost pair against each other
#: (``pair_agree``), and the view farther from its worn view rendered again
#: when they disagree (``pair_redo``).
PAIR_STEP = "ghost"
#: Ruling A46: the step whose views can be made from the worn view minus the base view instead of rendered
#: (``garment_from_worn``; the Wardrobe's "Piece-only views from" setting per view).
FROM_WORN_STEP = "ghost"
#: Ruling A60: the cut-out is made transparent where the worn view shows the body through an enclosed opening of the
#: piece (``garment_openings``; the Wardrobe's "Openings from the worn view" setting per view).
CUTOUT_OPENINGS = True
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
    trailing full stop ("" when unset); ``state`` ``open`` appends the
    explicit open phrase of the image edits (``outfit_options.
    OPEN_IMAGE_WORDS``, ruling F15 i-2: "worn open at the front …, its front
    edges apart …") to a set fragment, closed is the fragment alone (rulings
    A1 / A7). Only the front says it: the open state's backs are rendered
    from the closed texts (``garment_images``, ruling F15 i-1)."""
    from app.core.outfit_options import OPEN, OPEN_IMAGE_WORDS
    text = " ".join(str(item.get("prompt_fragment") or "").split()).rstrip(".").strip()
    return f"{text}, {OPEN_IMAGE_WORDS}" if text and state == OPEN else text


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
    """The piece's noun: the item's name in lower case ("Green Dress" ->
    "green dress"), ``"garment"`` without a name. The ghost prompt said it
    until Ruling A57; it stays a fingerprint input (``fsig_inputs``)."""
    name = " ".join(str(item.get("name") or "").split())
    return name.lower() if name else DEFAULT_NOUN


def fsig_inputs(character_name: str, item: Dict[str, Any], *,
                profile: Optional[Dict[str, Any]] = None, state: Optional[str] = None) -> Dict[str, Any]:
    """What a clothing piece contributes to the garment fingerprint
    (``garment_store.garment_fsig``): its prompt fragment, its noun (the
    lower-cased name; the ghost prompt no longer says it since Ruling A57,
    but it stays here so no stored fingerprint changes — a rename still
    re-renders the ghost),
    slots, covers, partially covers and the pronouns of the character's
    profile. Worn OPEN (``state``, None → the profile's worn state,
    ``state_of``) the fragment says the open phrase (``fragment``) and
    ``state: "open"`` is added; closed inputs are those of before the
    option, byte for byte. A back text that is set and differs from the
    front (``piece_back_text.distinct_back``) adds ``prompt_fragment_back``
    — without one the inputs are those of before Task 11e."""
    from app.core.garment_hair import pronouns
    from app.core.outfit_options import OPEN
    from app.core.piece_back_text import FIELD, distinct_back
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
    back = distinct_back(item)
    if back:
        out[FIELD] = back
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
    adds the open phrase); the worn
    BACK is no edit (``draft_prompt``, then the composite).
    ``ghost`` (the worn image): the piece alone — ``ghost_prompt``
    (no noun, Ruling A57); the BACK's negative is built from the back
    text (``_back_text_of``). ValueError for an unknown step or
    view, the worn back, a missing item, or a piece without a prompt
    fragment."""
    if step not in EDIT_STEPS:
        raise ValueError(f"no clothing edit step {step!r}")
    if view not in EDIT_VIEWS:
        raise ValueError(f"no clothing edit view {view!r}")
    if step == "worn" and view != "front":
        raise ValueError(f"the worn {view} is drafted from the worn front — draft_prompt, then the composite")
    item = _item_of(item_id)
    prof = _profile_of(character_name, profile)
    text = _fragment_of(item, state=state_of(item, prof))
    if step == "worn":
        from app.core.base_body import hair_text
        haired = bool(hair_text(character_name, profile=prof))
        return WORN.format(fragment=worn_text(item, text, state_of(item, prof))), \
            _worn_negative(text, keep_hair=haired)
    if view == "back":
        text = _back_text_of(item)
    negative = ", ".join(t for t in (_worn_negative(text), *GHOST_NEGATIVE) if t)
    return ghost_prompt(item.get("outfit_piece") or {}, view), negative


def worn_text(item: Dict[str, Any], text: str, state: str) -> str:
    """The worn front's piece text (Ruling A147): ``text`` plus ``WORN_CLOSED`` for a closable piece worn closed
    whose text names no state of its own; ``text`` alone otherwise (open state, not closable, "worn open" in it)."""
    from app.core.garment_set import closable_of
    from app.core.outfit_options import CLOSED, fragment_names_state
    if state == CLOSED and closable_of(item) and not fragment_names_state(text):
        return f"{text}, {WORN_CLOSED}"
    return text


def ghost_text_class(piece: Optional[Dict[str, Any]]) -> str:
    """The ghost text class of an ``outfit_piece`` (A183): its stored ``ghost_text`` when that names a class of
    ``GHOST_TEXTS``; else ``waistband`` for a waistband piece (``garment_gates.waistband_piece``), ``collar`` for a
    piece on a ``COLLAR_SLOTS`` slot, ``plain`` for every other piece."""
    from app.core.garment_gates import waistband_piece
    piece = piece if isinstance(piece, dict) else {}
    chosen = piece.get("ghost_text")
    if chosen in GHOST_TEXTS:
        return str(chosen)
    slots = {str(s) for s in piece.get("slots") or ()}
    if waistband_piece(slots):
        return "waistband"
    return "collar" if slots & COLLAR_SLOTS else "plain"


GHOST_TEXT_AUTO = "auto"


def ghost_text_info(item: Dict[str, Any]) -> Dict[str, Any]:
    """The piece dialog's "Piece-only text" (A183): ``{choice, auto, effective, texts}`` — ``choice`` the stored
    class or ``auto``, ``auto`` the class the slots give, ``effective`` the class the next ghost render says,
    ``texts`` ``{class: {front, back}}`` the prompt of each class per view."""
    piece = (item or {}).get("outfit_piece") or {}
    stored = piece.get("ghost_text")
    choice = stored if stored in GHOST_TEXTS else GHOST_TEXT_AUTO
    auto = ghost_text_class({k: v for k, v in piece.items() if k != "ghost_text"})
    return {"choice": choice, "auto": auto, "effective": ghost_text_class(piece),
            "texts": {cls: {view: ghost_prompt({"ghost_text": cls}, view) for view in EDIT_VIEWS}
                      for cls in GHOST_TEXTS}}


def set_ghost_text(character_name: str, item_id: str, choice: str) -> Dict[str, Any]:
    """Store the piece's "Piece-only text" (A183; ``auto`` drops the key) in ONE read-modify-write under
    ``keyed_lock("garment_item", character_name)``. Runs nothing and ages nothing: the text is no fingerprint
    input, the next ghost render of the piece says it. ``ghost_text_info`` now. ValueError for a bad choice or an
    item that is no outfit piece."""
    from app.core.keyed_lock import keyed_lock
    from app.models import inventory
    if choice != GHOST_TEXT_AUTO and choice not in GHOST_TEXTS:
        raise ValueError(f"choice must be one of {', '.join((GHOST_TEXT_AUTO, *GHOST_TEXTS))}")
    with keyed_lock("garment_item", character_name):
        item = inventory.get_item(item_id)
        if not isinstance(item, dict) or item.get("category") != "outfit_piece":
            raise ValueError(f"{str(item_id)[:80]!r} is no outfit piece")
        piece = dict(item.get("outfit_piece") or {})
        # None, not a missing key: ``update_item`` keeps a stored value the update does not name.
        piece["ghost_text"] = None if choice == GHOST_TEXT_AUTO else choice
        saved = inventory.update_item(item_id, {"outfit_piece": piece})
        if saved is None:
            raise ValueError(f"{str(item_id)[:80]!r} could not be saved")
    return ghost_text_info(saved if isinstance(saved, dict) else inventory.get_item(item_id) or {})


def ghost_prompt(piece: Optional[Dict[str, Any]], view: str) -> str:
    """The ghost prompt of an ``outfit_piece`` for ``view`` (Ruling A57, A183):
    the user's text of the piece's class (``ghost_text_class``: ``GHOST``,
    ``GHOST_WAISTBAND`` or ``GHOST_PLAIN``), then the side on a back
    (``GHOST_SIDE``), then the stance of a waistband piece
    (``GHOST_STANCE``). The text is no fingerprint input: changing it ages
    no stored view."""
    cls = ghost_text_class(piece)
    parts = [GHOST_TEXTS[cls]]
    if view in GHOST_SIDE:
        parts.append(GHOST_SIDE[view])
    if cls == "waistband":
        parts.append(GHOST_STANCE)
    return " ".join(parts)


def _fragment_of(item: Dict[str, Any], *, state: str = "closed") -> str:
    text = fragment(item, state=state)
    if not text:
        raise ValueError(f"{item.get('name') or item.get('id')} has no prompt fragment — fill it in under Items")
    return text


def _back_text_of(item: Dict[str, Any]) -> str:
    """The piece's back text (``piece_back_text.back_text``: its back field,
    else its front text) — never the open words (ruling F15 i-1: from behind
    an open piece looks like a closed one). ValueError without either text."""
    from app.core.piece_back_text import back_text
    text = back_text(item)
    if not text:
        raise ValueError(f"{item.get('name') or item.get('id')} has no prompt fragment — fill it in under Items")
    return text


def draft_prompt(character_name: str, step: str, *, profile: Optional[Dict[str, Any]] = None,
                 item_id: Optional[str] = None, view: str = "back") -> Tuple[str, str]:
    """``(prompt, negative)`` of the DRAFT of the worn back: the prompt is
    ``base_body.draft_prompt``'s back sentence as it is — the draft only turns
    the accepted worn front around, so it never names the piece (Ruling A29:
    "wearing only <fragment>" made the model invent a skirt or culottes under
    a blouse; the reference shows the piece). Negative: the draft's + the
    worn negative (the garment words the piece's back text,
    ``_back_text_of``, does not name). ValueError for another step, a missing
    item or no fragment. ``view`` (A185): ``back`` or a side view of a shell piece — the base draft's sentence of
    that view; a side's negative reads the front text (the side shows the front's edges)."""
    from app.core import base_body
    if EDIT_STEPS.get(step, {}).get("back") != "draft":
        raise ValueError(f"the clothing step {step!r} has no drafted back")
    item = _item_of(item_id)
    prof = _profile_of(character_name, profile)
    text = _back_text_of(item) if view == "back" else _fragment_of(item, state=state_of(item, prof))
    prompt, negative = base_body.draft_prompt(character_name, view, profile=prof)
    return prompt, ", ".join(p for p in (negative, _worn_negative(text)) if p)


def back_reasons(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> list:
    """The reasons a worn back attempt does not follow the accepted worn
    front (``garment_gates.back_follows_front``: the front opening on the
    back, a garment the front does not have)."""
    from app.core.garment_gates import back_follows_front
    return back_follows_front(front_gate, back_gate)


def gate(step: str, view: str, *, base_rgb, base_mask, source_rgb, source_mask,
         edit_rgb, edit_mask, item_id: Optional[str] = None,
         front_gate: Optional[Dict[str, Any]] = None, composite_support=None) -> Dict[str, Any]:
    """The gate record of one attempt (``garment_gates``): ``worn`` against
    the base view — the zones the piece is worn on (its slots,
    ``garment_gates.occupied_zones``: a hat frees the head) are not checked;
    the drafted back (a CPU composite, Task 11g) has an edit's outline
    limits; with the accepted front's record ``front_gate`` it measures what it puts
    on outside the front garment's rows (``extra_part``, ``back_reasons``)
    and, with its ``composite_support``, a head share outside the support
    (``garment_gates.worn_gate``); ``ghost`` against the garment region of the accepted worn image
    (``source``) — its hem against the worn view's and, for a closable
    piece's front, its open / closed look against the worn view's (Ruling
    A17, ``garment_gates.ghost_clothing_gate``). All arrays share the base
    view's size."""
    from app.core import garment_gates
    if step == "worn":
        slots = ((_item_of(item_id).get("outfit_piece") or {}).get("slots") or []) if item_id else []
        return garment_gates.worn_gate(base_rgb, base_mask, edit_rgb, edit_mask, view=view,
                                       occupied=garment_gates.occupied_zones(slots),
                                       xor_max=garment_gates.OUTSIDE_XOR_MAX,
                                       drift_px=garment_gates.OUTSIDE_DRIFT_PX,
                                       front_rows=(garment_gates.garment_rows(front_gate)
                                                   if front_gate else None),
                                       composite_support=composite_support)
    if step == "ghost":
        from app.core.garment_set import closable_of
        region = garment_gates.garment_region(base_rgb, base_mask, source_rgb, source_mask)
        return garment_gates.ghost_clothing_gate(base_rgb, base_mask, region, edit_rgb, edit_mask, view=view,
                                                 length_free=_waistband_ghost(step, item_id),
                                                 worn_rgb=source_rgb,
                                                 closable=bool(item_id) and closable_of(_item_of(item_id)))
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


def hem_snap_due(step: str, record: Dict[str, Any]) -> bool:
    """Ruling A27: whether a ``ghost`` gate record is refused by its hem
    alone within ``garment_gates.HEM_SNAP_MAX`` (``garment_gates.
    hem_snap_due``) — read from the record only, no image (the estimate's
    view of a stored attempt the chain judges again)."""
    from app.core import garment_gates
    return step == "ghost" and garment_gates.hem_snap_due(record)


def hem_snap(step: str, view: str, record: Dict[str, Any], *, ghost_mask, region,
             base_mask) -> Optional[Dict[str, Any]]:
    """Ruling A27: the hem snap of a ``ghost`` attempt refused by its hem
    alone (``garment_gates.hem_snap``: its rows below the underarm line of
    the worn ``region`` rescaled so its hem meets the worn hem); None for
    another step or when nothing is due. ``garment_images`` applies it,
    gates the corrected image again and keeps it only when it passes."""
    from app.core import garment_gates
    if step != "ghost" or region is None:
        return None
    return garment_gates.hem_snap(record, ghost_mask, region, base_mask)


def pair_agree(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> bool:
    """Front and back ghost end at the same height (``garment_gates.hems_agree``,
    the centre hems) — always True against a back registered by its waistband
    (``registered``): its hem is the edit's length scaled by the waistband,
    not a measurement (ruling 13d: the length does not matter)."""
    from app.core.garment_gates import hems_agree
    return bool(back_gate.get("registered")) or hems_agree(front_gate, back_gate)


def pair_reason(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> Optional[str]:
    """The refusal reason of a front ghost attempt against the WORN back's hem
    (Ruling A17 b, ``garment_gates.worn_hems_reason``: ``worn_hem_c`` of the
    accepted back ghost's record — never its ghost hem); None for a waistband
    piece (``registered`` back or ``length_free`` front: the length is free)."""
    from app.core.garment_gates import worn_hems_reason
    if back_gate.get("registered") or front_gate.get("length_free"):
        return None
    return worn_hems_reason(front_gate, back_gate)


def pair_repair_reason(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> Optional[str]:
    """The reason a front rendered again to repair a disagreeing pair is
    refused (``garments``): ``pair_reason`` and, since the back stays, the
    ghost pair's own rule (``garment_gates.hems_reason``)."""
    from app.core.garment_gates import hems_reason
    reason = pair_reason(front_gate, back_gate)
    if reason or back_gate.get("registered"):
        return reason
    return hems_reason(front_gate, back_gate)


def pair_redo(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> str:
    """The view a disagreeing ghost pair renders again (Ruling A17 c):
    ``"back"`` when the back's hem is farther from its worn back than the
    front's from its worn front (``garment_gates.hem_deviation``), else
    ``"front"`` (also when either is unmeasured)."""
    from app.core.garment_gates import hem_deviation
    back, front = hem_deviation(back_gate), hem_deviation(front_gate)
    return "back" if back is not None and front is not None and back > front else "front"


def front_hints(character_name: str, item_id: str, fsig: str, step: str, view: str) -> Optional[Dict[str, Any]]:
    """No prompt hints: the worn and ghost prompts need nothing from the back."""
    return None
