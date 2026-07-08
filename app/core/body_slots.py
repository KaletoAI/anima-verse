"""Body-slot engine — executes species-package slot declarations.

The core owns only the PRINCIPLE that a character has appearance and
anatomy (plan-body-slots.md, user decision): storage, visibility rules,
prompt integration and topology resolution live here — WHICH slots,
attributes, clothing-slot topology and UI silhouette exist is declared by
species packages (plugin.yaml ``body_slots`` / ``piece_slots`` /
``silhouette``, scoped by the package-level ``apply_to`` template
selector). This code knows no slot, attribute or species name; a new
species (e.g. a talking dragon) is a new content package, zero core change.

Decisions wired in (dialog 2026-07-08):
- F1: binary visibility. ``always``/``covered`` fragments flow into the
  GENERAL person description ("Woman with large breasts, …" — carries
  clothed anatomy differences); ``exposed`` renders only while uncovered.
- F2: species packages define the FULL slot topology, including which
  clothing slots exist (``piece_slots_for_character``; core
  ``VALID_PIECE_SLOTS`` is only the fallback without a species package).
- F3: slot fragments are sent along even when a reference image is
  attached (callers do not filter them out).
"""
from string import Formatter
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("body_slots")


# ---------------------------------------------------------------------------
# Species resolution
# ---------------------------------------------------------------------------

def _template_matches(pkg, template_name: str, tmpl: Dict[str, Any]) -> bool:
    """Whether a package's species content applies to a template.

    Package-level ``apply_to`` wins; without it the package's character
    fragments decide (same selector semantics)."""
    from app.models.character_template import fragment_applies
    if pkg.apply_to is not None:
        return fragment_applies({"apply_to": pkg.apply_to}, template_name, tmpl)
    return any(fragment_applies(f, template_name, tmpl)
               for f in pkg.character_fragments)


def _species_packages_for(profile: Dict[str, Any]) -> List[Any]:
    """Packages whose species content (slots/silhouette/topology) applies
    to this character's template."""
    tmpl_name = (profile.get("template") or "").strip()
    if not tmpl_name:
        return []
    try:
        from app.plugins.registry import packages
        from app.models.character_template import get_template
    except Exception:
        return []
    tmpl = get_template(tmpl_name) or {}
    out = []
    for pkg in packages():
        if not (pkg.body_slots or pkg.piece_slots or pkg.silhouette):
            continue
        try:
            if _template_matches(pkg, tmpl_name, tmpl):
                out.append(pkg)
        except Exception as e:
            logger.debug("species match failed for package %s: %s", pkg.id, e)
    return out


def _slot_applies(spec, profile: Dict[str, Any]) -> bool:
    """Per-slot ``applies_to`` filter (profile-field conditions, e.g.
    gender) — case-insensitive string comparison."""
    for field_name, allowed in (spec.applies_to or {}).items():
        val = str(profile.get(field_name, "") or "").strip().lower()
        if val not in [str(a).strip().lower() for a in allowed]:
            return False
    return True


def slots_for_character(character_name: str) -> List[Any]:
    """All BodySlotSpecs that apply to this character (species + applies_to)."""
    try:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    except Exception:
        return []
    specs: List[Any] = []
    for pkg in _species_packages_for(profile):
        for spec in pkg.body_slots:
            if _slot_applies(spec, profile):
                specs.append(spec)
    return specs


# ---------------------------------------------------------------------------
# Values (per character, in the profile — master data, not runtime state)
# ---------------------------------------------------------------------------

def slot_values(character_name: str) -> Dict[str, Dict[str, Any]]:
    """Stored attribute values: ``{slot_id: {attr: value}}``."""
    try:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    except Exception:
        return {}
    vals = profile.get("body_slots")
    return dict(vals) if isinstance(vals, dict) else {}


def set_slot_value(character_name: str, slot_id: str, attr: str, value: Any) -> None:
    """Editor API: store one attribute value (empty value removes it)."""
    from app.models.character import get_character_profile, save_character_profile
    profile = get_character_profile(character_name) or {}
    vals = dict(profile.get("body_slots") or {})
    slot = dict(vals.get(slot_id) or {})
    if value in (None, ""):
        slot.pop(attr, None)
    else:
        slot[attr] = value
    if slot:
        vals[slot_id] = slot
    else:
        vals.pop(slot_id, None)
    profile["body_slots"] = vals
    save_character_profile(character_name, profile)


# ---------------------------------------------------------------------------
# Visibility & prompt fragments
# ---------------------------------------------------------------------------

def _is_exposed(spec, profile: Dict[str, Any]) -> bool:
    """Exposed = none of the covering clothing slots holds a piece.
    Slots without ``covered_by`` count as exposed (always visible)."""
    if not spec.covered_by:
        return True
    equipped = dict(profile.get("equipped_pieces") or {})
    return not any(equipped.get(slot) for slot in spec.covered_by)


def _format_if_complete(text: str, values: Dict[str, str]) -> str:
    """Render ``{attr}`` placeholders; empty result when any referenced
    attribute has no value (a half-filled fragment is worse than none)."""
    if not text:
        return ""
    try:
        fields = [f for _, f, _, _ in Formatter().parse(text) if f]
    except ValueError:
        return ""
    if any(not (values.get(f) or "").strip() for f in fields):
        return ""
    try:
        return text.format(**values).strip()
    except (KeyError, IndexError):
        return ""


def prompt_fragments(character_name: str,
                     face_only: bool = False,
                     profile: Optional[Dict[str, Any]] = None) -> Dict[str, List[str]]:
    """Prompt fragments for all applicable slots.

    Returns ``{"general": [...], "exposed": [...]}`` — general carries
    ``always`` plus (while covered) ``covered`` fragments and belongs into
    the person description (F1); exposed renders only while uncovered.
    ``face_only`` keeps only slots declared ``face: true`` (portrait/
    expression prompts — hair/eyes/skin, never body or NSFW slots).
    """
    specs = slots_for_character(character_name)
    if face_only:
        specs = [s for s in specs if getattr(s, "face", False)]
    if not specs:
        return {"general": [], "exposed": []}
    if profile is None:
        try:
            from app.models.character import get_character_profile
            profile = get_character_profile(character_name) or {}
        except Exception:
            return {"general": [], "exposed": []}
    stored = profile.get("body_slots")
    stored = dict(stored) if isinstance(stored, dict) else {}

    general: List[str] = []
    exposed: List[str] = []
    for spec in specs:
        vals = {attr: str((stored.get(spec.id) or {}).get(attr, "") or "")
                for attr in spec.attributes}
        frag = _format_if_complete(spec.prompt.get("always", ""), vals)
        if frag:
            general.append(frag)
        if _is_exposed(spec, profile):
            frag = _format_if_complete(spec.prompt.get("exposed", ""), vals)
            if frag:
                exposed.append(frag)
        else:
            frag = _format_if_complete(spec.prompt.get("covered", ""), vals)
            if frag:
                general.append(frag)
    return {"general": general, "exposed": exposed}


def exposed_slot_loras(character_name: str,
                       profile: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """LoRAs of currently EXPOSED body slots (lora_select attribute values,
    e.g. the NSFW anatomy LoRAs) — merged into image-generation inputs by
    the variant/expression path. Replaces the former per-clothing-slot
    override LoRAs."""
    specs = slots_for_character(character_name)
    if not specs:
        return []
    if profile is None:
        try:
            from app.models.character import get_character_profile
            profile = get_character_profile(character_name) or {}
        except Exception:
            return []
    stored = profile.get("body_slots")
    stored = dict(stored) if isinstance(stored, dict) else {}
    out: List[Dict[str, Any]] = []
    seen = set()
    for spec in specs:
        if not _is_exposed(spec, profile):
            continue
        for attr, decl in spec.attributes.items():
            if str(decl.get("type", "")) != "lora_select":
                continue
            name = str((stored.get(spec.id) or {}).get(attr, "") or "").strip()
            if name and name.lower() != "none" and name not in seen:
                out.append({"name": name, "strength": 1.0})
                seen.add(name)
    return out


def being_for_character(character_name: str) -> str:
    """Prompt noun for what kind of being the character is ('person',
    'animal', ...) — declared by the species package (manifest ``being``);
    default 'person'. Used by scene composition to phrase subject counts
    correctly ('exactly one person and one animal')."""
    try:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
        for pkg in _species_packages_for(profile):
            if getattr(pkg, "being", ""):
                return pkg.being
    except Exception:
        pass
    return "person"


def appearance_suffix(character_name: str, face_only: bool = False,
                      profile: Optional[Dict[str, Any]] = None) -> str:
    """Combined fragment text appended to the character's appearance
    (PromptBuilder; face_only for portrait/expression prompts; ``profile``
    overrides the stored profile for dry-run previews). Empty without
    species packages — safe no-op."""
    frags = prompt_fragments(character_name, face_only=face_only,
                             profile=profile)
    parts = frags["general"] + frags["exposed"]
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Topology & silhouette
# ---------------------------------------------------------------------------

def declared_piece_slots(character_name: str) -> Optional[Tuple[Tuple[str, ...], Dict[str, str]]]:
    """Species-declared clothing topology as ``(slot_ids, labels)`` — or
    None when no species package declares one (callers keep their core
    default, including its own display order/labels)."""
    try:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
        for pkg in _species_packages_for(profile):
            if pkg.piece_slots:
                return tuple(pkg.piece_slots), dict(pkg.piece_slot_labels)
    except Exception as e:
        logger.debug("piece slots for %s failed: %s", character_name, e)
    return None


def piece_slots_for_character(character_name: str) -> Tuple[str, ...]:
    """Effective clothing-slot topology: the species package's
    ``piece_slots`` when declared, otherwise the core default
    (inventory.VALID_PIECE_SLOTS)."""
    declared = declared_piece_slots(character_name)
    if declared:
        return declared[0]
    from app.models.inventory import VALID_PIECE_SLOTS
    return tuple(VALID_PIECE_SLOTS)


def silhouette_for_character(character_name: str) -> Optional[Dict[str, Any]]:
    """Silhouette declaration of the character's species package (or None).
    Returns ``{"package_id", "asset", "dir"}`` — the UI route resolves the
    asset file relative to the package dir."""
    try:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    except Exception:
        return None
    for pkg in _species_packages_for(profile):
        if pkg.silhouette.get("asset"):
            return {"package_id": pkg.id,
                    "asset": pkg.silhouette["asset"],
                    "dir": str(pkg.dir),
                    **{k: v for k, v in pkg.silhouette.items() if k != "asset"}}
    return None
