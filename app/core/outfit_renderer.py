"""Outfit-Renderer: zentrale Quelle für Outfit-Beschreibungen.

Plan: development_instructions/plan-outfit-system-rethink.md §4

Eine Quelle, eine Cover-Berechnung, ein Render-Pfad. Wird von Chat-
Appearance UND Bild-Prompt-Generation (expression_regen, image_generation)
genutzt.

Wichtige Designentscheidungen:
- equipped_pieces_meta (Pro-Slot Farb-Override) wird NICHT mehr gelesen.
  Items sind eindeutig — Farbe steckt im prompt_fragment des Items selbst.
  Plan §5, Entscheidung 2026-05-13.
- Multi-Slot-Pieces werden nur EINMAL gerendert (am ersten Slot in
  VALID_PIECE_SLOTS-Reihenfolge).
- Cover-Logik: `covers` schluckt Slots komplett, `partially_covers`
  formuliert "X underneath Y".
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


def _resolve_tokens(raw: str, profile: Dict[str, Any]) -> str:
    """Resolve {placeholder}-Tokens gegen das Profil. Robust gegen Fehler."""
    s = (raw or "").strip()
    if not s or "{" not in s:
        return s
    try:
        from app.models.character_template import (
            get_template, resolve_profile_tokens,
        )
        tmpl = get_template(profile.get("template", "")) if profile else None
        return resolve_profile_tokens(s, profile, template=tmpl,
                                       target_key="character_appearance")
    except Exception:
        return s


def collect_covered_slots(equipped_pieces: Dict[str, str]) -> Set[str]:
    """Alle Slots, die durch ein anderes Piece via `covers` verdeckt werden."""
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


def _resolve_partial_covers(
    equipped_pieces: Dict[str, str],
    slot_order: List[str],
) -> Tuple[Dict[str, Tuple[str, str]], Set[str]]:
    """Liefert (partially_covered_map, suppressed_slots).

    - partially_covered_map: {target_slot → (covering_fragment, covering_slot)}
      bedeutet "covering_slot deckt target_slot teilweise, fragment lautet ..."
    - suppressed_slots: Slots deren Fragment im "underneath"-Teil eines
      anderen Slots steckt — nicht doppelt rendern.
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
    """Iteriert sichtbare Pieces in Slot-Reihenfolge mit Dedup fuer
    Multi-Slot-Pieces. Returns Liste (slot, item_id, item_dict).
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
) -> Dict[str, str]:
    """Baut Outfit-Beschreibung — Pieces + Items + Fallback fuer leere Slots.

    Inputs:
        profile: Character-Profile. Wenn None und character_name gegeben,
            wird via get_character_profile geladen.
        equipped_pieces / equipped_items: Overrides — fuer Set-Vorschauen
            oder andere Stelle, die NICHT den aktuellen Status zeigen sollen.
            None → aus dem Profil.

    Returns:
        {
            "pieces":   str,   # "white bustier, jeans, sneakers"
            "items":    str,   # "holding hammer, wearing aviator sunglasses"
            "fallback": str,   # "topless, bottomless" — leere Slots
            "full":     str,   # zusammengesetzt fuer "altes" build_equipped_outfit_prompt
        }

    Wenn weder Pieces noch Items noch Fallback befuellt sind, ist `full=""`.
    Aufrufer behandeln das als "outfit-frei" und greifen ggf. auf Freitext-
    Fallback zurueck.
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

    covered = collect_covered_slots(pieces)
    partial, suppressed = _resolve_partial_covers(pieces, list(VALID_PIECE_SLOTS))

    # 1) Piece-Fragmente
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

    # 2) Item-Fragmente (equipped_items — Hand/Akzessoires)
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

    # 3) Fallback-Parts: leere + nicht-verdeckte Slots (Slot-Override
    #    oder no_outfit_prompt_top/bottom Legacy). Achtung: underwear_top/
    #    underwear_bottom werden NICHT als sichtbar betrachtet, wenn der
    #    Outer-Slot belegt ist — sonst beschreibt der Prompt freiliegende
    #    Haut, obwohl Hose/Top sie verdecken.
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
                                        equipped_pieces=dict(pieces or {}))
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

    # 4) Full-Zusammenbau (Format wie altes build_equipped_outfit_prompt):
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

    return {
        "pieces": pieces_text,
        "items": items_text,
        "fallback": fallback_text,
        "full": full,
        "loras": slot_loras,
    }


def render_unworn_slots(
    profile: Optional[Dict[str, Any]] = None,
    *,
    character_name: str = "",
) -> str:
    """Sammelt prompt-Fragmente fuer leere UND nicht-verdeckte Slots.

    Im Gegensatz zu render_outfit().fallback enthaelt das hier ALLE
    unbedeckten/leeren Slots (auch underwear-Slots wenn outer leer ist),
    weil der Chat-Pfad die Appearance-Zeile erweitert — wenn der Char
    nichts traegt, soll der LLM-Prompt sehen "topless, no panties".

    Returns kommaseparierte Liste der Fragmente.
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
