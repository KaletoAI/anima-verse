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

#: How the hair mesh is made: the edit chain (haired -> ghost -> cutout ->
#: mesh -> fit) or HairDeck (one profile picture -> hair cards -> fit).
HAIR_METHODS: Tuple[str, ...] = ("edit_chain", "hairdeck")
DEFAULT_HAIR_METHOD = "edit_chain"
_HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{6}")


def world_hair_method() -> str:
    """The world default ``base_body.hair_method`` (an unknown value = ``edit_chain``)."""
    from app.core import config
    from app.core.config_schema import field_default
    value = str(config.get("base_body.hair_method", field_default("base_body", "hair_method")) or "")
    return value if value in HAIR_METHODS else DEFAULT_HAIR_METHOD


def hair_method_source(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """``(method, source)``: the character's own ``hair_method`` when it names
    a method (source ``"character"``), else the world's
    ``base_body.hair_method`` (source ``"world"``; an unknown world value is
    the default ``edit_chain``). ``""`` or an unknown profile value = the world."""
    profile = _profile_of(character_name, profile)
    own = str(profile.get("hair_method") or "")
    if own in HAIR_METHODS:
        return own, "character"
    return world_hair_method(), "world"


def hair_method(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> str:
    """``"edit_chain"`` or ``"hairdeck"`` — see ``hair_method_source``."""
    return hair_method_source(character_name, profile=profile)[0]


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
#: ``tilt_deg``); empty = automatic.
PLACEMENT_KEYS: Dict[str, str] = {"forward_m": "hair_forward_m", "tilt_deg": "hair_tilt_deg"}


def _placement_limit(name: str) -> float:
    from app.core import garment_hairdeck
    return garment_hairdeck.FORWARD_LIMIT_M if name == "forward_m" else garment_hairdeck.TILT_LIMIT_DEG


def _placement_value(name: str, raw: Any) -> Optional[float]:
    """A manual placement value as float, None for empty. ValueError for a non-number or one beyond its limit."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if isinstance(raw, bool):
        raise ValueError(f"hair {name} must be a number or empty")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"hair {name} must be a number or empty") from None
    limit = _placement_limit(name)
    if not math.isfinite(value) or abs(value) > limit:
        raise ValueError(f"hair {name} must be within +-{limit:g}")
    return value


def hair_placement(profile: Optional[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    """``{forward_m, tilt_deg}``: the manual HairDeck placement of the profile keys ``hair_forward_m`` (metres
    along +z) and ``hair_tilt_deg`` (forward pitch, degrees); None = automatic (forward
    ``garment_hairdeck.DEFAULT_FORWARD_M``, tilt solved to the brow line). A stored value that is no number or
    lies beyond its limit counts as automatic."""
    out: Dict[str, Optional[float]] = {}
    for name, key in PLACEMENT_KEYS.items():
        try:
            out[name] = _placement_value(name, (profile or {}).get(key))
        except ValueError:
            out[name] = None
    return out


def set_hair_placement(character_name: str, forward_m: Any, tilt_deg: Any) -> bool:
    """Store the manual HairDeck placement (profile keys ``hair_forward_m`` / ``hair_tilt_deg``; None or "" =
    automatic, stored as ""). ValueError for a non-number or a value beyond ``garment_hairdeck.FORWARD_LIMIT_M`` /
    ``TILT_LIMIT_DEG`` — nothing is stored then. Both keys are written in ONE read-modify-write under the profile
    lock. Only the HairDeck fit fingerprint changes: the next run re-fits from the cached HairDeck job."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    values = {"forward_m": _placement_value("forward_m", forward_m),
              "tilt_deg": _placement_value("tilt_deg", tilt_deg)}
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
#: the HairDeck fit gates it differently (``garment_hairdeck.gates_for``) and the edit chain's length sentence
#: names no chin for it (``length_phrase``).
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


# --- The image chain (Task 4): edit prompts, negatives, gates -----------------

#: The edit steps of the hair chain and what each edits: the base view, or the
#: accepted image of an earlier step. No step carries character LoRAs (ruling:
#: the spike edits that gave the gate numbers ran without any).
EDIT_STEPS: Dict[str, Dict[str, str]] = {"haired": {"source": "base"},
                                         "ghost": {"source": "haired"}}

# The spike's sentences (hair_edit.py, keys ("haired", view) and ("ghost",
# view)), verbatim apart from the pronouns. {p} = possessive, {s} = subject,
# {has} = "has"/"have".
_KEEP_FRONT = ("Keep the image exactly as it is: the same person, same face, same body shape, same pose, same arm "
               "and hand position, same framing and background.")
_KEEP_BACK = ("Keep the image exactly as it is: the same person seen from behind, same body shape, same pose, same "
              "arm and hand position, same framing and background.")
_CHANGE = "Only change {p} head: {s} now {has} {hair}."
# Only for hair that falls behind the shoulders (hair_behind_shoulders).
_BEHIND = {
    "front": ("All of the hair falls behind {p} shoulders onto {p} upper back; the face, the neck, the collarbones, "
              "the chest and the front of the shoulders stay completely free of hair."),
    "back": ("The hair covers the back of {p} head and falls straight down onto {p} upper back between the "
             "shoulder blades; the arms and the shoulders stay free of hair."),
}
_GHOST = {
    "front": ("Keep the image exactly as it is: the same hair in exactly the same position, size, shape, strands "
              "and framing, the same background. Remove the person completely: no face, no head, no neck, no ears, "
              "no skin, no body, no arms. The hair keeps its worn, three-dimensional shape as if on an invisible "
              "head (ghost mannequin product photo of a wig); where the face and the head were, the inner side of "
              "the hair is visible."),
    "back": ("Keep the image exactly as it is: the same hair in exactly the same position, size, shape, strands "
             "and framing, the same background. Remove the person completely: no head, no neck, no ears, no skin, "
             "no body, no arms. The hair keeps its worn, three-dimensional shape as if on an invisible head (ghost "
             "mannequin product photo of a wig)."),
}
# Where the hair ends, as a share t of the base figure height below its top
# (garment_gates.hair_length, measured on the haired BACK view): upper band
# edges and the phrase. Landmarks of the 8-head canon the gates use (chin
# 0.125 ~ CHIN_ROW 0.13, shoulder line SHOULDER_ROW 0.19), shoulder blades
# ~0.27, middle of the back ~0.33, waist ~0.40; each edge lies between two of
# them. {p} = possessive ("her"; "the" in the hair-only prompt). Wording
# tuned on the clone (2026-11-09, Kira, back end t 0.233, front bottoms vs
# back 0.2474 H, limit ±0.011 H): no phrase 0.305..0.337 (0/3), "just below
# the shoulders" 0.216..0.226 (0/2), "at the middle of the shoulder blades"
# 0.279..0.314 (0/2), "at the top of the shoulder blades" 0.213..0.243 (1/4).
LENGTH_BANDS: Tuple[Tuple[float, str], ...] = (
    (0.16, "at {p} chin"),
    (0.205, "at {p} shoulders"),
    (0.25, "at the top of {p} shoulder blades"),
    (0.30, "at the middle of {p} shoulder blades"),
    (0.36, "at the middle of {p} back"),
    (0.44, "at {p} waist"),
)
LENGTH_BELOW = "below {p} waist"
# Short hair by its length class, whatever ``t`` says: its back end sits at
# the nape, the chin's height (Kai 2026-11-09: t 0.12 -> "at the chin", and
# the hair-only front became a chin-length bob, width +18 %).
SHORT_LENGTH_PHRASES: Dict[str, str] = {
    "very short": "close to {p} scalp, well above {p} ears",
    "short": "above {p} ears and at the nape of {p} neck",
}
# The length sentence of the hair-only FRONT prompt (the front hides the
# ends behind the body; without it the edit invents the length).
_GHOST_LENGTH = "The hair ends {where}."


def length_phrase(t: Optional[float], possessive: str = "the", length_class: Optional[str] = None) -> str:
    """``"just below her shoulders"`` for a hair end at ``t`` (``LENGTH_BANDS``);
    "" without a measurement. A short ``length_class`` (``SHORT_LENGTH_PHRASES``)
    names its own end instead of a band."""
    if t is None:
        return ""
    if length_class in SHORT_LENGTH_PHRASES:
        return SHORT_LENGTH_PHRASES[length_class].format(p=possessive)
    for edge, phrase in LENGTH_BANDS:
        if t < edge:
            return phrase.format(p=possessive)
    return LENGTH_BELOW.format(p=possessive)


# The step terms of the spike's negatives; the shared part (spike NEG) is the
# negative of the use case ``garment_edit`` and is prepended by the service.
_STEP_NEGATIVE = {
    ("haired", "front"): ("hair over the chest", "hair in front of the shoulders", "bangs over the eyes",
                          "ponytail", "bun", "braid", "hat", "headband", "clothing", "jewelry"),
    ("haired", "back"): ("hair over the arms", "ponytail", "bun", "braid", "hat", "headband", "clothing",
                         "jewelry", "face"),
    ("ghost", "front"): ("person", "face", "skin", "neck", "ears", "body", "shoulders", "arms", "mannequin head",
                         "wig stand", "styrofoam head"),
    ("ghost", "back"): ("person", "face", "skin", "neck", "ears", "body", "shoulders", "arms", "mannequin head",
                        "wig stand", "styrofoam head"),
}
# A negative term leaves the negative when the hair description names it
# (a ponytail must not be forbidden from hair that IS a ponytail) — the
# pattern table of base_body.DRESS_GARMENT_NEGATIVE.
HAIR_STYLE_NEGATIVE = (
    ("ponytail", r"pony ?tails?"),
    ("bun", r"buns?"),
    ("braid", r"braid(?:s|ed)?|plait(?:s|ed)?"),
    ("bangs over the eyes", r"bangs|fringe"),
    ("headband", r"head ?bands?"),
)


def _negative(step: str, view: str, description: str) -> str:
    dropped = {term for term, pattern in HAIR_STYLE_NEGATIVE
               if re.search(rf"\b(?:{pattern})\b", description or "", re.IGNORECASE)}
    return ", ".join(term for term in _STEP_NEGATIVE[(step, view)] if term not in dropped)


def edit_prompt(character_name: str, step: str, view: str, *,
                profile: Optional[Dict[str, Any]] = None, length_t: Optional[float] = None,
                item_id: Optional[str] = None) -> Tuple[str, str]:
    """``(prompt, extra negative)`` of one hair edit (spike wording).

    ``haired``: the base view with the character's hair added — pronouns from
    the profile gender ("they now have" for anything but female/male); the
    sentence that puts the hair behind the shoulders only when
    ``hair_behind_shoulders``. ``ghost``: the hair alone on an invisible
    head. The negative is the step's own terms minus every hair-style term the
    description names; the use case ``garment_edit`` adds the shared part.

    ``length_t`` (where the hair of the accepted haired BACK view ends,
    ``garment_gates.hair_length``) gives the hair-only FRONT prompt the length
    the front cannot show: "The hair ends just below the shoulders." The
    haired front leaves it out: its hair falls behind the shoulders, the
    length is not visible there, and on the clone (2026-11-09, Kira) the
    phrase turned it into a shoulder-length bob with the body outline moving
    (XOR 0.0161..0.0261 in 4 of 4 attempts against 0.0125 without it).
    ``item_id`` is the kind protocol's (``garment_images``); hair reads the
    profile, not the item."""
    if step not in EDIT_STEPS:
        raise ValueError(f"no hair edit step {step!r}")
    if view not in _GHOST:
        raise ValueError(f"no hair edit view {view!r}")
    profile = _profile_of(character_name, profile)
    description = hair_description(character_name, profile=profile)
    if step == "ghost":
        where = length_phrase(length_t if view == "front" else None,
                              length_class=hair_length_class(character_name, profile=profile))
        if not where:
            return _GHOST[view], _negative(step, view, description)
        keep, rest = _GHOST[view].split(". ", 1)
        return f"{keep}. {_GHOST_LENGTH.format(where=where)} {rest}", _negative(step, view, description)
    if not description:
        raise ValueError("No hair set — fill in the hair in Appearance")
    possessive, subject = pronouns(profile)
    words = {"p": possessive, "s": subject, "has": "have" if subject == "they" else "has",
             "hair": description}
    parts = [_KEEP_FRONT if view == "front" else _KEEP_BACK, _CHANGE.format(**words)]
    if hair_behind_shoulders(character_name, profile=profile):
        parts.append(_BEHIND[view].format(**words))
    return " ".join(parts), _negative(step, view, description)


def gate(step: str, view: str, *, base_rgb, base_mask, source_rgb, source_mask,
         edit_rgb, edit_mask, item_id: Optional[str] = None) -> Dict[str, Any]:
    """The gate record of one attempt (``garment_gates``): ``haired`` against
    the base view; ``ghost`` against the hair of the accepted haired image
    (``source``). All arrays share the base view's size. ``item_id`` is the
    kind protocol's; the hair gates do not need it."""
    from app.core import garment_gates
    if step == "haired":
        return garment_gates.haired_gate(base_rgb, base_mask, edit_rgb, edit_mask, view=view)
    if step == "ghost":
        ref = garment_gates.hair_ref(base_rgb, base_mask, source_rgb, source_mask)
        return garment_gates.ghost_gate(base_rgb, base_mask, ref, edit_rgb, edit_mask, view=view)
    raise ValueError(f"no hair edit step {step!r}")


def position_reference(step: str, *, base_rgb, base_mask, source_rgb, source_mask):
    """The mask an attempt of ``step`` is registered onto before its gate
    (``garment_gates.register``): for ``ghost`` the hair of the accepted
    haired image (``garment_gates.hair_ref``) — what its position gate
    measures against; None for ``haired`` (an edit of the base view)."""
    from app.core import garment_gates
    if step != "ghost":
        return None
    return garment_gates.hair_ref(base_rgb, base_mask, source_rgb, source_mask)


# --- The pair hooks of the orchestration (``garments``) -----------------------

#: What the messages call the thing in the images ("No hair found …").
SUBJECT = "hair"
#: The step whose front is gated against the accepted back.
PAIR_STEP = "ghost"
PAIR_REFUSED = "front and back hair end at different heights"


def pair_agree(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> bool:
    """Front and back hair-only images end at the same height
    (``garment_gates.bottoms_agree``)."""
    from app.core.garment_gates import bottoms_agree
    return bottoms_agree(front_gate, back_gate)


def pair_reason(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> Optional[str]:
    """The refusal reason of a hair-only front attempt against the accepted
    back (``garment_gates.bottoms_reason``)."""
    from app.core.garment_gates import bottoms_reason
    return bottoms_reason(front_gate, back_gate)


def front_hints(character_name: str, item_id: str, fsig: str, step: str, view: str) -> Optional[Dict[str, Any]]:
    """The prompt hints of the hair-only FRONT edit: ``{"length_t": t}`` from
    the accepted haired back (``garment_images.haired_length``); None for any
    other step or view, or without a measurement (no length named)."""
    from app.core import garment_images
    if step != "ghost" or view != "front":
        return None
    measured = garment_images.haired_length(character_name, item_id, fsig, "back")
    logger.info("Garment %s/%s hair length from the back view: %s", character_name, item_id, measured)
    return {"length_t": measured["t"]} if measured else None


def _is_own_hair(item: Optional[Dict[str, Any]], character_name: str) -> bool:
    return bool(item and item.get("category") == "garment"
                and (item.get("owner") or "").strip() == character_name
                and (item.get("garment") or {}).get("kind") == HAIR_KIND)


def find_hair_item(character_name: str, profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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
