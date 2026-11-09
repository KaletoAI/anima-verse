"""Hair as its own mesh — the hair garment of a humanoid on the base-body
pipeline (plan ``docs/superpowers/plans/2026-11-09-base-body-phase4-hair.md``,
spec ``2026-11-08-base-body-outfits-design.md`` § C/D).

The base body is bald; its hair is ONE item per character:
category ``garment``, ``owner`` = the character, ``garment = {kind: "hair",
slot: "hair", body_slot: <slot id>}``, worn through the profile state key
``equipped_mesh_pieces`` (never ``equipped_pieces`` — R2: no 2D prompt, outfit
signature, outfit preset or LLM unequip ever sees it).

Which body slot is "the hair" is declared by the species package (body-slot
key ``mesh_item: hair``); the core names no slot id. The description is
DERIVED, never edited on the item (R3): the slot's ``always`` fragment plus
every clause of the free-text appearance that mentions hair. The item's
``prompt_fragment`` is refreshed from it whenever ``ensure_hair_item`` runs,
so the 2D body slot and the 3D item never diverge.
"""
import re
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("garment_hair")

HAIR_KIND = "hair"
HAIR_ITEM_NAME = "Hair"

_HAIR_WORD = re.compile(r"\bhair\b", re.IGNORECASE)
# A clause that denies hair ("no hair", "bald") must not become a hair item.
_NO_HAIR = re.compile(r"\b(?:no|without|bald|hairless)\b", re.IGNORECASE)
# Comma and sentence clauses of the appearance text.
_CLAUSE_SPLIT = re.compile(r"[,;.!?\n]+")


def _profile_of(character_name: str, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if profile is not None:
        return profile
    from app.models.character import get_character_profile
    return get_character_profile(character_name) or {}


def _hair_slot(character_name: str, profile: Dict[str, Any]):
    from app.core.body_slots import mesh_item_slots
    return mesh_item_slots(character_name, profile=profile).get(HAIR_KIND)


def _appearance_hair_clauses(text: str) -> List[str]:
    """Every comma/sentence clause of ``text`` that names hair. A clause with
    an unresolved ``{placeholder}`` is left out (its value depends on state
    the hair does not), and so is one that denies hair."""
    out = []
    for clause in _CLAUSE_SPLIT.split(text or ""):
        clause = " ".join(clause.split())
        if clause and "{" not in clause and _HAIR_WORD.search(clause) and not _NO_HAIR.search(clause):
            out.append(clause)
    return out


def hair_description(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> str:
    """The hair text of the character (R3): the ``always`` fragment of its
    hair body slot (human: ``"{length} {color} hair"``), then every clause of
    ``character_appearance`` matching ``\\bhair\\b``, de-duplicated
    (case-insensitive). "" = no hair text at all — a bald character."""
    profile = _profile_of(character_name, profile)
    parts: List[str] = []
    slot = _hair_slot(character_name, profile)
    if slot is not None:
        from app.core.body_slots import slot_fragment
        always, _ = slot_fragment(character_name, slot.id, profile=profile)
        if always:
            parts.append(always)
    parts.extend(_appearance_hair_clauses(str(profile.get("character_appearance") or "")))
    seen, unique = set(), []
    for part in parts:
        key = part.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(part)
    return ", ".join(unique)


def hair_behind_shoulders(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the hair falls behind the shoulders: the hair slot has a
    mesh-input line for its current value (human: medium and longer)."""
    profile = _profile_of(character_name, profile)
    slot = _hair_slot(character_name, profile)
    if slot is None:
        return False
    from app.core.body_slots import slot_fragment
    return bool(slot_fragment(character_name, slot.id, profile=profile, mesh_input=True)[1])


def _is_own_hair(item: Optional[Dict[str, Any]], character_name: str) -> bool:
    return bool(item and item.get("category") == "garment"
                and (item.get("owner") or "").strip() == character_name
                and (item.get("garment") or {}).get("kind") == HAIR_KIND)


def _find_hair_item(character_name: str, profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The character's hair item: the one worn in the hair slot, else the
    first (by id) item it owns whose garment kind is hair."""
    from app.models import inventory
    worn = (profile.get("equipped_mesh_pieces") or {}).get(HAIR_KIND)
    if worn:
        item = inventory.get_item(worn)
        if _is_own_hair(item, character_name):
            return item
    owned = [item for item in inventory.list_items() if _is_own_hair(item, character_name)]
    return min(owned, key=lambda item: item.get("id") or "") if owned else None


def _new_item_id(character_name: str) -> str:
    """``hair_<name slug>`` with a numeric suffix when taken."""
    from app.models import inventory
    slug = re.sub(r"[^a-z0-9]+", "_", character_name.lower()).strip("_")[:96]
    base = f"{HAIR_KIND}_{slug}" if slug else HAIR_KIND
    candidate, suffix = base, 2
    while inventory.get_item(candidate) is not None:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def ensure_hair_item(character_name: str) -> str:
    """Create (if missing), refresh and wear the character's hair item;
    returns its id.

    ValueError for a non-humanoid, a character off the base-body pipeline, a
    species without a hair mesh-item slot, or no hair text at all. The
    inventory is not touched — the item is worn, never carried."""
    from app.core.base_body import is_base_pipeline
    from app.core.keyed_lock import keyed_lock
    from app.core.model_refs import is_humanoid
    from app.models import inventory
    from app.models.character import get_character_profile
    # One creation per character at a time (two concurrent calls must not
    # mint two items). Lock order: garment_item -> character_profile (taken
    # inside equip_mesh_piece); nothing here waits on I/O beyond the DB.
    with keyed_lock("garment_item", character_name):
        profile = get_character_profile(character_name) or {}
        if not is_humanoid(character_name, profile=profile):
            raise ValueError("Hair as its own mesh is for humanoid characters only")
        if not is_base_pipeline(character_name, profile=profile):
            raise ValueError(f"{character_name} is not on the base-body pipeline")
        slot = _hair_slot(character_name, profile)
        if slot is None:
            raise ValueError(f"No hair slot is declared for {character_name}")
        description = hair_description(character_name, profile=profile)
        if not description:
            raise ValueError("No hair set — fill in the hair in Appearance; a bald character gets no hair item")
        garment = {"kind": HAIR_KIND, "slot": HAIR_KIND, "body_slot": slot.id}
        item = _find_hair_item(character_name, profile)
        if item is None:
            item = inventory.add_item(
                name=HAIR_ITEM_NAME, category="garment", owner=character_name,
                prompt_fragment=description, garment=garment, item_id=_new_item_id(character_name),
                transferable=False, portable=False)
            logger.info("hair item created for %s: %s", character_name, item["id"])
        else:
            updates: Dict[str, Any] = {}
            if (item.get("prompt_fragment") or "") != description:
                updates["prompt_fragment"] = description
            if item.get("garment") != garment:
                updates["garment"] = garment
            if updates and inventory.update_item(item["id"], updates) is None:
                raise RuntimeError(f"Could not refresh the hair item {item['id']}")
        if not inventory.equip_mesh_piece(character_name, item["id"]):
            raise RuntimeError(f"Could not store the worn hair item of {character_name}")
        return item["id"]
