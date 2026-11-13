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
import math
import re
from typing import Any, Dict, List, Optional, Tuple

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


def pronouns(profile: Dict[str, Any]) -> Tuple[str, str]:
    """``(possessive, subject)`` for the edit prompts, from the profile gender:
    female -> ("her", "she"), male -> ("his", "he"), anything else ->
    ("their", "they")."""
    gender = str((profile or {}).get("gender") or "").strip().lower()
    if gender in ("female", "woman", "f"):
        return "her", "she"
    if gender in ("male", "man", "m"):
        return "his", "he"
    return "their", "they"


# --- The hair method (plan 2026-11-09-hairdeck-hair, Task 4) -------------------

#: How the hair mesh is made: ``body`` (no hair mesh at all — the base views
#: are rendered WITH the character's hair, so the hair is part of the base
#: body and of every outfit body; spec 2026-11-11-hair-from-body, the world
#: default) or HairDeck (one profile picture -> hair cards -> fit). Any other
#: stored value (a removed method) resolves to the default.
HAIR_METHODS: Tuple[str, ...] = ("body", "hairdeck")
#: The method whose hair lives inside the body mesh (``hair_in_body``).
BODY_METHOD = "body"
DEFAULT_HAIR_METHOD = BODY_METHOD
#: Why a ``body`` character has no hair item and no hair run.
HAIR_IN_BODY = "Hair comes from the body mesh"
_HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{6}")


def world_hair_method() -> str:
    """The world default ``base_body.hair_method`` (an unknown or removed value = ``DEFAULT_HAIR_METHOD``)."""
    from app.core import config
    from app.core.config_schema import field_default
    value = str(config.get("base_body.hair_method", field_default("base_body", "hair_method")) or "")
    return value if value in HAIR_METHODS else DEFAULT_HAIR_METHOD


def hair_method_source(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """``(method, source)``: the character's own ``hair_method`` when it names
    a method (source ``"character"``), else the world's
    ``base_body.hair_method`` (source ``"world"``; an unknown world value is
    ``DEFAULT_HAIR_METHOD``). ``""`` or an unknown profile value = the world."""
    profile = _profile_of(character_name, profile)
    own = str(profile.get("hair_method") or "")
    if own in HAIR_METHODS:
        return own, "character"
    return world_hair_method(), "world"


def hair_method(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> str:
    """One of ``HAIR_METHODS`` — see ``hair_method_source``."""
    return hair_method_source(character_name, profile=profile)[0]


def hair_in_body(character_name: str, profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the character's hair is part of its body mesh (method ``body``):
    the base views are rendered with the hair (``base_body.base_character`` /
    ``base_prompt``), and no hair item is ever created or run."""
    return hair_method(character_name, profile=profile) == BODY_METHOD


def hair_colour_override(profile: Optional[Dict[str, Any]]) -> str:
    """The manual hair colour of the profile key ``hair_colour`` as
    ``"#rrggbb"`` (lower case), ``""`` = automatic (HairDeck's own vertex
    colours). A value that is no ``#rrggbb`` counts as automatic."""
    value = str((profile or {}).get("hair_colour") or "").strip()
    return value.lower() if _HEX_COLOUR.fullmatch(value) else ""


def _set_profile_key(character_name: str, key: str, value: str) -> bool:
    """Store one hair key of the profile (read-modify-write under the
    profile lock). The save result; True without a save when unchanged."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        if str(profile.get(key) or "") == value:
            return True
        profile[key] = value
        return bool(save_character_profile(character_name, profile))


def set_hair_method(character_name: str, method: str) -> bool:
    """Store the character's own hair method (profile key ``hair_method``);
    ``""`` = the world default. ValueError for anything else than ``""`` or a
    ``HAIR_METHODS`` entry. Returns the save result. Starts no run: the
    served hair follows the method's newest accepted fit (Task 4)."""
    if method not in ("", *HAIR_METHODS):
        raise ValueError(f"hair method must be one of: \"\", {', '.join(HAIR_METHODS)}")
    return _set_profile_key(character_name, "hair_method", method)


def set_hair_colour(character_name: str, hex_colour: str) -> bool:
    """Store the manual hair colour (profile key ``hair_colour``, lower-case
    ``#rrggbb``); ``""`` = automatic (HairDeck's own colours). ValueError for
    anything else. Only the HairDeck fit fingerprint changes: the next run
    re-fits from the cached HairDeck job."""
    value = str(hex_colour or "").strip()
    if value and not _HEX_COLOUR.fullmatch(value):
        raise ValueError("hair colour must be #rrggbb or empty")
    return _set_profile_key(character_name, "hair_colour", value.lower())


#: The profile keys of the HairDeck placement correction (``garment_hairdeck.fit_hairdeck``'s ``forward_m`` /
#: ``tilt_deg`` / ``width_scale``); empty = automatic (width: 1, HairDeck's own).
PLACEMENT_KEYS: Dict[str, str] = {"forward_m": "hair_forward_m", "tilt_deg": "hair_tilt_deg",
                                  "width_scale": "hair_width_scale"}
#: Placement values that enter ``hair_placement`` (and so the fit fingerprint) only when set: a hair without a
#: width keeps the fingerprint it had before the width existed (the CPU refit sweep only re-fits a stale fit under
#: its unchanged fingerprint, ``garment_refit.outdated_fits``).
_PLACEMENT_WHEN_SET = ("width_scale",)


def _placement_range(name: str) -> Tuple[float, float]:
    from app.core import garment_hairdeck
    if name == "width_scale":
        return garment_hairdeck.WIDTH_SCALE_LIMITS
    limit = garment_hairdeck.FORWARD_LIMIT_M if name == "forward_m" else garment_hairdeck.TILT_LIMIT_DEG
    return -limit, limit


def placement_limits() -> Dict[str, Any]:
    """The bounds of the manual values for the hair placement (``HairDeckPlacement``): ``|forward_m|``, ``|tilt_deg|`` and ``[lo, hi]`` of
    ``width_scale``."""
    from app.core import garment_hairdeck
    return {"forward_m": garment_hairdeck.FORWARD_LIMIT_M, "tilt_deg": garment_hairdeck.TILT_LIMIT_DEG,
            "width_scale": list(garment_hairdeck.WIDTH_SCALE_LIMITS)}


def _placement_value(name: str, raw: Any) -> Optional[float]:
    """A manual placement value as float, None for empty. ValueError for a non-number or one beyond its range."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if isinstance(raw, bool):
        raise ValueError(f"hair {name} must be a number or empty")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"hair {name} must be a number or empty") from None
    lo, hi = _placement_range(name)
    if not math.isfinite(value) or not lo <= value <= hi:
        if lo == -hi:
            raise ValueError(f"hair {name} must be within +-{hi:g}")
        raise ValueError(f"hair {name} must be within {lo:g}..{hi:g}")
    return value


def hair_placement(profile: Optional[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    """``{forward_m, tilt_deg[, width_scale]}``: the manual HairDeck placement of the profile keys
    ``hair_forward_m`` (metres along +z), ``hair_tilt_deg`` (forward pitch, degrees) and ``hair_width_scale``
    (the sides' reach beyond the head, ``garment_hairdeck.narrow_sides``); None = automatic (forward
    ``garment_hairdeck.DEFAULT_FORWARD_M``, tilt solved to the brow line). ``width_scale`` is present only when
    set (``_PLACEMENT_WHEN_SET``). A stored value that is no number or lies beyond its range counts as
    automatic."""
    out: Dict[str, Optional[float]] = {}
    for name, key in PLACEMENT_KEYS.items():
        try:
            value = _placement_value(name, (profile or {}).get(key))
        except ValueError:
            value = None
        if value is not None or name not in _PLACEMENT_WHEN_SET:
            out[name] = value
    return out


def set_hair_placement(character_name: str, forward_m: Any, tilt_deg: Any, width_scale: Any = None) -> bool:
    """Store the manual HairDeck placement (profile keys ``hair_forward_m`` / ``hair_tilt_deg`` /
    ``hair_width_scale``; None or "" = automatic, stored as ""). ValueError for a non-number or a value beyond
    ``garment_hairdeck.FORWARD_LIMIT_M`` / ``TILT_LIMIT_DEG`` / ``WIDTH_SCALE_LIMITS`` — nothing is stored then.
    All keys are written in ONE read-modify-write under the profile lock. Only the HairDeck fit fingerprint
    changes: the next run re-fits from the cached HairDeck job."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    values = {"forward_m": _placement_value("forward_m", forward_m),
              "tilt_deg": _placement_value("tilt_deg", tilt_deg),
              "width_scale": _placement_value("width_scale", width_scale)}
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        changed = False
        for name, key in PLACEMENT_KEYS.items():
            wanted = "" if values[name] is None else values[name]
            if profile.get(key, "") != wanted:
                profile[key] = wanted
                changed = True
        return bool(save_character_profile(character_name, profile)) if changed else True


# --- Length class and named colour of the hair ---------------------------------

#: Hair length classes, shortest first (the human pack's hair ``length`` options). Short hair lies on the scalp:
#: the HairDeck fit gates it differently (``garment_hairdeck.gates_for``).
LENGTH_CLASSES: Tuple[str, ...] = ("very short", "short", "medium", "long", "very long")
SHORT_LENGTH_CLASSES: Tuple[str, ...] = ("very short", "short")
_LENGTH_CLASS_WORD = re.compile(r"\b(very short|very long|short|medium|long)\b", re.IGNORECASE)
#: Named hair colours -> sRGB the hair's MEDIAN vertex colour is matched to (``garment_hairdeck._transfer_colours``):
#: a shaded-hair median, darker than the highlights. "blonde" is the colour the user picked for Kira's medium
#: blonde (2026-11-09); "brunette" a medium brown (Kai's HairDeck median (58, 50, 43) is ΔE 17 from it — the
#: near-black of finding 1.3b). The human pack's options plus common free-text words; longest phrases match first.
HAIR_COLOURS: Dict[str, str] = {
    "platinum blonde": "#e2d8c3", "strawberry blonde": "#c98d62", "dirty blonde": "#a68a62",
    "light brown": "#7d5a3e", "dark brown": "#3d2a1e",
    "blonde": "#d3b497", "blond": "#d3b497", "brunette": "#5c3b26", "brown": "#5c3b26", "chestnut": "#61392a",
    "black": "#231f1d", "red": "#8f3a1f", "ginger": "#a5532b", "copper": "#9e5530", "auburn": "#6d2f20",
    "gray": "#8b8986", "grey": "#8b8986", "silver": "#b9b8b5", "white": "#e5e2dc", "pink": "#d68aa6",
    "blue": "#3b5b9b", "green": "#3b7a4b", "purple": "#6b3b8b",
}
_COLOUR_WORD = re.compile(r"\b(" + "|".join(re.escape(name) for name in sorted(HAIR_COLOURS, key=len, reverse=True))
                          + r")\b")
_HAIR_AT = re.compile(r"\bhair\b")
#: How many words before "hair" a colour word may stand ("short dark brunette hair").
_COLOUR_REACH_WORDS = 4


def hair_length_class(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """The hair's length class (``LENGTH_CLASSES``) or None: the value of the attribute the hair slot declares
    for its mesh-input line (the human pack: ``length``) when it is a class, else the first class word of
    ``hair_description`` ("short brunette hair" -> "short")."""
    profile = _profile_of(character_name, profile)
    slot = _hair_slot(character_name, profile)
    if slot is not None and getattr(slot, "mesh_input_prompt", None):
        from app.core.body_slots import slot_values
        key = slot.mesh_input_prompt.get("attribute")
        value = str((slot_values(character_name, profile=profile).get(slot.id) or {}).get(key) or "")
        if " ".join(value.lower().split()) in LENGTH_CLASSES:
            return " ".join(value.lower().split())
    match = _LENGTH_CLASS_WORD.search(hair_description(character_name, profile=profile))
    return " ".join(match.group(1).lower().split()) if match else None


def hair_colour_name(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """The named hair colour of ``hair_description`` (a ``HAIR_COLOURS`` key) or None: per clause, the colour
    word nearest before a "hair" within ``_COLOUR_REACH_WORDS`` words ("brown eyes and black hair" -> black);
    the first clause with one wins."""
    for clause in hair_description(character_name, profile=profile).lower().split(","):
        for hair in _HAIR_AT.finditer(clause):
            window = " ".join(clause[:hair.start()].split()[-_COLOUR_REACH_WORDS:])
            found = list(_COLOUR_WORD.finditer(window))
            if found:
                return found[-1].group(1)
    return None


def profile_hair_colour(character_name: str, *,
                        profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, str]]:
    """``{name, hex}`` of the profile's named hair colour (``hair_colour_name``), None without one."""
    name = hair_colour_name(character_name, profile=profile)
    return {"name": name, "hex": HAIR_COLOURS[name]} if name else None


def colour_target(hex_colour: str) -> Optional[Tuple[float, float, float]]:
    """``"#rrggbb"`` -> sRGB 0..1 (``garment_hairdeck.fit_hairdeck``'s
    ``colour_target``); ``""`` -> None (keep HairDeck's colours)."""
    if not hex_colour:
        return None
    if not _HEX_COLOUR.fullmatch(hex_colour):
        raise ValueError(f"no #rrggbb colour: {hex_colour[:20]!r}")
    return tuple(int(hex_colour[i:i + 2], 16) / 255.0 for i in (1, 3, 5))  # type: ignore[return-value]


def fsig_inputs(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What the hair kind contributes to the garment fingerprint
    (``garment_store.garment_fsig``, R10): the derived description, whether
    the hair falls behind the shoulders, and the pronouns the prompts use."""
    profile = _profile_of(character_name, profile)
    return {"description": hair_description(character_name, profile=profile),
            "behind_shoulders": hair_behind_shoulders(character_name, profile=profile),
            "pronouns": list(pronouns(profile))}


def _is_own_hair(item: Optional[Dict[str, Any]], character_name: str) -> bool:
    return bool(item and item.get("category") == "garment"
                and (item.get("owner") or "").strip() == character_name
                and (item.get("garment") or {}).get("kind") == HAIR_KIND)


def worn_hair_id(character_name: str, profile: Optional[Dict[str, Any]] = None) -> str:
    """The id of the character's OWN hair item it wears in the hair slot of
    ``equipped_mesh_pieces`` (a garment of kind hair owned by it), "" without
    one — the hair that is its own mesh, whatever its method or fit state."""
    profile = _profile_of(character_name, profile)
    worn = profile.get("equipped_mesh_pieces")
    item_id = worn.get(HAIR_KIND) if isinstance(worn, dict) else None
    if not item_id:
        return ""
    from app.models import inventory
    return str(item_id) if _is_own_hair(inventory.get_item(str(item_id)), character_name) else ""


def find_hair_item(character_name: str, profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The character's hair item: the one worn in the hair slot, else the
    first (by id) item it owns whose garment kind is hair."""
    from app.models import inventory
    worn = worn_hair_id(character_name, profile)
    if worn:
        return inventory.get_item(worn)
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

    ValueError for a non-humanoid (the one character off the base-body
    pipeline since Task 11h, Ruling A13), a species without a hair mesh-item
    slot, or no hair text at all. The
    inventory is not touched — the item is worn, never carried."""
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
        if hair_in_body(character_name, profile):
            raise ValueError(f"{HAIR_IN_BODY} — no hair item for the method {BODY_METHOD!r}")
        slot = _hair_slot(character_name, profile)
        if slot is None:
            raise ValueError(f"No hair slot is declared for {character_name}")
        description = hair_description(character_name, profile=profile)
        if not description:
            raise ValueError("No hair set — fill in the hair in Appearance; a bald character gets no hair item")
        garment = {"kind": HAIR_KIND, "slot": HAIR_KIND, "body_slot": slot.id}
        item = find_hair_item(character_name, profile)
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
