"""Outfit renderer: the central source of outfit descriptions.

Plan: development_instructions/plan-outfit-system-rethink.md §4

One source, one cover computation, one render path. Used by the chat
appearance AND by image prompt generation (expression_regen,
image_generation).

Key design decisions:
- Per-slot colour overrides do not exist. Items are unambiguous — the colour
  sits in the item's own prompt_fragment. Plan §5, decision 2026-05-13.
- Multi-slot pieces are rendered only ONCE (at the first slot in
  VALID_PIECE_SLOTS order).
- Cover logic: `covers` swallows slots entirely, `partially_covers` phrases
  "X underneath Y".
"""
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.log import get_logger

logger = get_logger("outfit_renderer")


def _get_item(iid: str) -> Optional[Dict[str, Any]]:
    """Lazy item lookup."""
    if not iid:
        return None
    from app.models.inventory import get_item
    return get_item(iid)


#: What an undressed character wears — the text that REPLACES the wardrobe
#: description once `outfit_worn` is off (see render_outfit step 5). A
#: species package may declare its own (``undressed_prompt``, see
#: :func:`undressed_text`).
NO_CLOTHES_TEXT = "no clothes"


def is_free_text_wardrobe(profile: Optional[Dict[str, Any]]) -> bool:
    """Whether the character dresses by free text only: its template has no
    outfit system (``features.outfit_system_enabled: false``, e.g.
    npc-temporary). Its wardrobe is ``outfit_description`` + ``outfit_worn``."""
    name = str((profile or {}).get("template") or "").strip()
    if not name:
        return False
    try:
        from app.models.character_template import get_template
        tmpl = get_template(name) or {}
    except Exception:
        return False
    return (tmpl.get("features") or {}).get("outfit_system_enabled") is False


def undressed_text(profile: Optional[Dict[str, Any]]) -> str:
    """What an undressed character wears in every prompt: the
    ``undressed_prompt`` of a species package applying to its template, else
    ``NO_CLOTHES_TEXT``."""
    try:
        from app.core.body_slots import undressed_prompt
        return undressed_prompt(profile or {}) or NO_CLOTHES_TEXT
    except Exception:
        return NO_CLOTHES_TEXT


def is_outfit_worn(profile: Optional[Dict[str, Any]]) -> bool:
    """The binary dressed state of a free-text wardrobe (``outfit_worn``).

    THE one reading of that field — every consumer imports it from here
    instead of repeating the shapes. Both shapes really occur: the template
    field is a ``select`` whose option values are the STRINGS "true"/"false"
    (npc-temporary), while the NPC pipeline and the undress verbs write a real
    bool. A profile without the key is dressed (fail-open: an existing
    ``outfit_description`` is worn until someone says otherwise).
    """
    worn = (profile or {}).get("outfit_worn", True)
    if isinstance(worn, str):
        return worn.strip().lower() not in ("false", "0", "no", "nein", "")
    return bool(worn)


def free_text_outfit(profile: Optional[Dict[str, Any]]) -> str:
    """What a free-text wardrobe WEARS right now, as ``render_outfit`` says it.

    :func:`undressed_text` for an undressed character, ``"wearing: <text>"`` for
    a dressed one, "" when no ``outfit_description`` is set. It is the string
    the per-outfit caches sign (``model_refs.outfit_signature_raw``), so
    "did this save re-dress the character" is asked of THIS and not of the
    description alone — the dressed state changes the picture just as much
    (``npc_assets.on_outfit_description_changed``).
    """
    if not is_outfit_worn(profile):
        return undressed_text(profile)
    described = str((profile or {}).get("outfit_description") or "").strip()
    return "wearing: " + described if described else ""


def collect_covered_slots(equipped_pieces: Dict[str, str]) -> Set[str]:
    """All slots another piece hides entirely via `covers`."""
    covered: Set[str] = set()
    for slot, iid in (equipped_pieces or {}).items():
        if not iid:
            continue
        item = _get_item(iid)
        if not item:
            continue
        op = item.get("outfit_piece") or {}
        for c in (op.get("covers") or []):
            cs = str(c).strip().lower()
            if cs:
                covered.add(cs)
    return covered


def visible_equipped_pieces(equipped_pieces: Dict[str, str]) -> Dict[str, str]:
    """The VISUALLY EFFECTIVE subset of an equipped-piece set.

    Slots fully hidden via ``covers`` are dropped — a piece nobody can see
    contributes nothing to a render, so two sets differing only in covered
    pieces produce the identical image. ``partially_covers`` targets STAY:
    they appear as an "underneath" fragment and do change the image.

    This is the normalisation the render cache keys on
    (``_equipped_signature``): boxers under trousers and no boxers at all
    are ONE cache entry, one T-pose render, one mesh.
    """
    covered = collect_covered_slots(equipped_pieces)
    return {slot: iid for slot, iid in (equipped_pieces or {}).items()
            if iid and slot not in covered}


def _resolve_partial_covers(
    equipped_pieces: Dict[str, str],
    slot_order: List[str],
) -> Tuple[Dict[str, Tuple[str, str]], Set[str]]:
    """Returns (partially_covered_map, suppressed_slots).

    - partially_covered_map: {target_slot → (covering_fragment, covering_slot)}
      means "covering_slot partially covers target_slot, its fragment reads ..."
    - suppressed_slots: slots whose fragment already sits in the "underneath"
      part of another slot — not rendered twice.
    """
    partial: Dict[str, Tuple[str, str]] = {}
    seen_items: Set[str] = set()
    for slot in slot_order:
        iid = (equipped_pieces or {}).get(slot)
        if not iid or iid in seen_items:
            continue
        seen_items.add(iid)
        item = _get_item(iid)
        if not item:
            continue
        op = item.get("outfit_piece") or {}
        cov_frag = (item.get("prompt_fragment") or "").strip()
        for c in (op.get("partially_covers") or []):
            cs = str(c).strip().lower()
            if cs and cov_frag:
                partial[cs] = (cov_frag, slot)
    suppressed: Set[str] = set()
    for target, (_frag, cov_slot) in partial.items():
        if (equipped_pieces or {}).get(target):
            suppressed.add(cov_slot)
    return partial, suppressed


def _iter_visible_pieces(
    equipped_pieces: Dict[str, str],
    slot_order: List[str],
    covered: Set[str],
    suppressed: Set[str],
) -> List[Tuple[str, str, Dict[str, Any]]]:
    """Iterates the visible pieces in slot order, de-duplicating
    multi-slot pieces. Returns a list of (slot, item_id, item_dict).
    """
    out: List[Tuple[str, str, Dict[str, Any]]] = []
    rendered: Set[str] = set()
    for slot in slot_order:
        if slot in covered or slot in suppressed:
            continue
        iid = (equipped_pieces or {}).get(slot)
        if not iid or iid in rendered:
            continue
        item = _get_item(iid)
        if not item:
            continue
        rendered.add(iid)
        out.append((slot, iid, item))
    return out


def render_outfit(
    profile: Optional[Dict[str, Any]] = None,
    *,
    character_name: str = "",
    equipped_pieces: Optional[Dict[str, str]] = None,
    equipped_items: Optional[List[str]] = None,
    back_view: bool = False,
) -> Dict[str, str]:
    """Builds the outfit description — pieces + items + fallback for empty slots.

    Inputs:
        profile: character profile. When None and character_name is given,
            it is loaded via get_character_profile.
        equipped_pieces / equipped_items: overrides — for set previews or
            other places that must NOT show the current state.
            None → from the profile.
        back_view: a render seen from behind — only LoRAs of body slots
            that declare `back: true` (see app/core/body_slots.py).

    Returns:
        {
            "pieces":   str,   # "white bustier, jeans, sneakers"
            "items":    str,   # "holding hammer, wearing aviator sunglasses"
            "fallback": str,   # "topless, bottomless" — empty slots
            "full":     str,   # assembled as the old build_equipped_outfit_prompt did
        }

    With neither pieces nor items nor fallback filled, `full=""`. Callers
    treat that as "no outfit" and may fall back to a free text. An undressed
    character (`outfit_worn` off) is NOT an empty case: `fallback` and
    `full` then carry :func:`undressed_text`, so every prompt states the
    condition instead of leaving it out.
    """
    from app.models.inventory import VALID_PIECE_SLOTS
    if profile is None and character_name:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    profile = profile or {}

    pieces = equipped_pieces if equipped_pieces is not None else (
        profile.get("equipped_pieces") or {})
    items = equipped_items if equipped_items is not None else (
        profile.get("equipped_items") or [])

    # A template without an outfit system (features.outfit_system_enabled:
    # false — e.g. npc-temporary) dresses via ``outfit_description`` ONLY.
    # Structured leftovers (pieces minted by a mis-templated edit and still
    # equipped) must never override that text — the wardrobe UI is hidden
    # for these templates, so stray pieces would be uncorrectable and the
    # rendered image would contradict the description.
    if is_free_text_wardrobe(profile):
        pieces, items = {}, []

    covered = collect_covered_slots(pieces)
    partial, suppressed = _resolve_partial_covers(pieces, list(VALID_PIECE_SLOTS))

    # 1) Piece fragments
    piece_fragments: List[str] = []
    for slot, iid, item in _iter_visible_pieces(
        pieces, list(VALID_PIECE_SLOTS), covered, suppressed,
    ):
        frag = (item.get("prompt_fragment") or "").strip()
        if not frag:
            continue
        if slot in partial:
            frag = f"{frag} underneath {partial[slot][0]}"
        piece_fragments.append(frag)

    # 2) Item fragments (equipped_items — hand-held / accessories)
    item_fragments: List[str] = []
    seen_iids: Set[str] = set()
    for iid in items or []:
        if not iid or iid in seen_iids:
            continue
        seen_iids.add(iid)
        item = _get_item(iid)
        if not item:
            continue
        frag = (item.get("prompt_fragment") or "").strip()
        if frag:
            item_fragments.append(frag)

    # 3) Fallback parts: empty and uncovered slots. Note: underwear_top/
    #    underwear_bottom do NOT count as visible while the outer slot is
    #    occupied — otherwise the prompt describes bare skin that trousers
    #    or a top actually hide.
    def _outer_layer_covers(slot: str) -> bool:
        if slot == "underwear_top":
            return bool(pieces.get("top")) or "underwear_top" in covered
        if slot == "underwear_bottom":
            return bool(pieces.get("bottom")) or "underwear_bottom" in covered
        return False

    # Exposed-anatomy prompts come from the body-slot packages now
    # (appearance_suffix exposed fragments in the person description);
    # their LoRAs are collected here so the variant/expression path keeps
    # its single merge point.
    slot_loras: List[Dict[str, Any]] = []
    try:
        from app.core.body_slots import exposed_slot_loras
        # profile + effective pieces: the variant path calls render_outfit
        # WITHOUT character_name and may override the equipped state
        # (outfit-set previews) — exposure must follow what is RENDERED.
        slot_loras = exposed_slot_loras(character_name or "",
                                        profile=profile,
                                        equipped_pieces=dict(pieces or {}),
                                        back_view=back_view)
    except Exception:
        slot_loras = []

    fallback_parts: List[str] = []
    for slot in VALID_PIECE_SLOTS:
        if pieces.get(slot):
            continue
        if slot in covered:
            continue
        if _outer_layer_covers(slot):
            continue
        # Exposed anatomy comes from the body-slot packages
        # (appearance_suffix exposed fragments) — the pre-override legacy
        # fields no_outfit_prompt_top/bottom are retired.

    pieces_text = ", ".join(piece_fragments)
    items_text = ", ".join(item_fragments)
    fallback_text = ", ".join(fallback_parts)

    # 4) Full assembly (format of the old build_equipped_outfit_prompt):
    #    "<fallback>. wearing: <pieces>. <items>"
    if not pieces and not items:
        full = ""
    else:
        full_parts: List[str] = []
        if fallback_text:
            full_parts.append(fallback_text)
        if piece_fragments:
            full_parts.append("wearing: " + pieces_text)
        if item_fragments:
            full_parts.append(items_text)
        full = ". ".join(full_parts)

    # 5) Free-text wardrobe: a character whose profile carries an
    #    `outfit_description` wears exactly that — no slots, no pieces, no
    #    inventory. `outfit_worn` is the binary dressed state (default: yes).
    #    Only used when nothing structured is equipped, so it can never fight
    #    a real wardrobe. Every consumer of `full` (chat "You are wearing",
    #    image prompts, 3D) inherits it from this one place.
    if not full:
        full = free_text_outfit(profile)
        if not is_outfit_worn(profile):
            # Undressed is a STATEMENT, not the absence of one. Dropping the
            # wardrobe text used to leave nothing in its place, and an image
            # prompt with no clothing line at all renders whatever the model
            # feels like putting on. It goes through `fallback` as well, so
            # the image path phrases it WITHOUT an "is wearing".
            fallback_text = full

    return {
        "pieces": pieces_text,
        "items": items_text,
        "fallback": fallback_text,
        "full": full,
        "loras": slot_loras,
    }


def undressed_line(character_name: str = "",
                   profile: Optional[Dict[str, Any]] = None) -> str:
    """What an LLM is told about an UNDRESSED free-text wardrobe — "" for
    anyone dressed or dressed by pieces/items.

    :func:`undressed_text` followed by the exposed body-slot fragments
    ("<undressed text>, <exposed fragment>, …"): the image path carries those fragments in the
    person description already (``appearance_suffix``), the LLM prompts
    that name the outfit only did not — they said what is missing and not
    what is there. The clothing description is left out on purpose."""
    if profile is None and character_name:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    profile = profile or {}
    if is_outfit_worn(profile):
        return ""
    out = render_outfit(profile, character_name=character_name)
    if out.get("pieces") or out.get("items"):
        return ""
    parts = [out.get("full") or undressed_text(profile)]
    try:
        from app.core.body_slots import prompt_fragments
        parts += prompt_fragments(character_name, profile=profile)["exposed"]
    except Exception:
        pass
    return ", ".join(p for p in parts if p)


def render_unworn_slots(
    profile: Optional[Dict[str, Any]] = None,
    *,
    character_name: str = "",
) -> str:
    """Collects prompt fragments for empty AND uncovered slots.

    Unlike render_outfit().fallback this holds ALL uncovered/empty slots
    (underwear slots too while the outer one is empty), because the chat
    path extends the appearance line — a character wearing nothing should
    show the LLM prompt "topless, no panties".

    Returns a comma-separated list of the fragments.
    """
    from app.models.inventory import VALID_PIECE_SLOTS
    if profile is None and character_name:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    profile = profile or {}

    pieces = profile.get("equipped_pieces") or {}
    covered = collect_covered_slots(pieces)

    # Exposed-anatomy fragments come from the body-slot packages
    # (appearance_suffix exposed prompts) — only the legacy underwear
    # fallback fields remain here.
    parts: List[str] = []
    for slot in VALID_PIECE_SLOTS:
        if pieces.get(slot):
            continue
        if slot in covered:
            continue
        # Exposed anatomy comes from the body-slot packages — the legacy
        # underwear fallback fields are retired.
    return ", ".join(parts)
