"""Hairstyles — the hair of a humanoid on the base-body pipeline (plan
``docs/superpowers/plans/2026-11-09-base-body-phase4-hair.md``, spec
``2026-11-08-base-body-outfits-design.md`` § C/D; hairstyles: plan
``2026-11-12-unified-worn-pieces`` Task 13, decisions D1–D5).

A hairstyle is an item: category ``garment``, ``owner`` = the character,
``garment = {kind: "hair", slot: "hair", body_slot: <slot id>, mesh_mode,
description, <settings>}`` (section "Hairstyles" below). A character owns
several and wears one through the profile state key ``equipped_mesh_pieces``
(never ``equipped_pieces`` — R2: no 2D prompt, outfit signature or LLM unequip
ever sees it; a saved outfit set may name one, D5).

Which body slot is "the hair" is declared by the species package (body-slot
key ``mesh_item: hair``); the core names no slot id. A hairstyle's text is its
own (``garment.description``); the Appearance's hair text
(``appearance_hair_text``: the slot's ``always`` fragment plus every clause of
the free-text appearance that mentions hair) is what a character's first
hairstyle starts from.
"""
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("garment_hair")

HAIR_KIND = "hair"
#: The name of a hairstyle whose description gives none.
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


def appearance_hair_text(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> str:
    """The hair text of the character's Appearance (R3): the ``always``
    fragment of its hair body slot (human: ``"{length} {color} hair"``), then
    every clause of ``character_appearance`` matching ``\\bhair\\b``,
    de-duplicated (case-insensitive). "" = no hair text at all — a bald
    character. What a character's first hairstyle starts from."""
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


def hair_description(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
                     item: Optional[Dict[str, Any]] = None) -> str:
    """The text of the hairstyle ``item`` (``hairstyle_description``), None →
    the worn hairstyle's; "" without one — no hair."""
    if item is None:
        item = worn_hairstyle(character_name, _profile_of(character_name, profile))
    return hairstyle_description(item)


def _text_of(character_name: str, profile: Dict[str, Any], text: Optional[str]) -> str:
    return hair_description(character_name, profile=profile) if text is None else " ".join(str(text).split())


def _is_appearance_hair(character_name: str, profile: Dict[str, Any], text: str) -> bool:
    """Whether ``text`` is the Appearance's hair text — then the hair slot's
    values describe that hair (its length, ``hair_behind_shoulders``)."""
    return bool(text) and text == appearance_hair_text(character_name, profile=profile)


def hair_behind_shoulders(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
                          text: Optional[str] = None) -> bool:
    """Whether the hair ``text`` (None: the worn hairstyle's) falls behind the
    shoulders: for the Appearance's hair (``_is_appearance_hair``) the hair
    slot has a mesh-input line for its current value (human: medium and
    longer); for any other text its length class (``hair_length_class``) is
    medium or longer."""
    profile = _profile_of(character_name, profile)
    text = _text_of(character_name, profile, text)
    if _is_appearance_hair(character_name, profile, text):
        slot = _hair_slot(character_name, profile)
        if slot is None:
            return False
        from app.core.body_slots import slot_fragment
        return bool(slot_fragment(character_name, slot.id, profile=profile, mesh_input=True)[1])
    return hair_length_class(character_name, profile=profile, text=text) in LENGTH_CLASSES[2:]


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


# --- Hairstyles (plan 2026-11-12-unified-worn-pieces Task 13, decisions D1-D5) --
#
# A hairstyle is a hair item (module docstring) whose ``garment`` also holds
# ``mesh_mode`` (how the hair reaches the figure, ``HAIR_MODES``) and
# ``description`` (the hairstyle's text). A character owns several and wears
# one (``equipped_mesh_pieces["hair"]``); the hair mode IS the worn
# hairstyle's mode. The plain body is the body of ONE hairstyle — the
# profile key ``BASE_HAIRSTYLE_KEY`` names it: under the mode ``body`` the
# base views are rendered with its description (``plain_hair_text``), under
# any other mode bald. Wearing another hairstyle never rebuilds the plain
# body: a body hairstyle with another text, or a HairDeck one on a haired
# plain body, makes a body SHAPE (``shape_hair``, D4). The HairDeck settings
# (colour, placement, Swing, Stiffness) are per hairstyle, stored under the
# ``SETTING_KEYS`` of its ``garment`` (``hairstyle_settings``).

#: How a hairstyle reaches the figure: HairDeck (one profile picture -> hair
#: cards -> fit), HAAR (the hairstyle's text -> strands, one hub job per seed ->
#: fit) or ``body`` (the hair is part of the body mesh — no hair mesh, no hair job).
HAIRDECK_MODE, HAAR_MODE, BODY_MODE = "hairdeck", "haar", "body"
HAIR_MODES: Tuple[str, ...] = (HAIRDECK_MODE, HAAR_MODE, BODY_MODE)
#: The modes a hairstyle can be made with today.
BUILT_MODES: Tuple[str, ...] = (HAIRDECK_MODE, HAAR_MODE, BODY_MODE)
#: The world default of a new hairstyle when the world names no valid one.
DEFAULT_HAIR_MODE = BODY_MODE
#: Why a ``body`` hairstyle has no hair run.
HAIR_IN_BODY = "Hair comes from the body mesh"
#: Profile key: the id of the hairstyle the plain body is the body of (D3).
BASE_HAIRSTYLE_KEY = "base_hairstyle"
#: ``shape_hair`` of a hairstyle that needs a bald body (D4).
BALD = "bald"
#: The per-hairstyle settings, keys of the item's ``garment`` (they kept the
#: names the profile keys had, so their readers read either mapping).
SETTING_KEYS: Tuple[str, ...] = ("hair_colour", "hair_forward_m", "hair_tilt_deg", "hair_width_scale",
                                 "hair_up_m", "hair_swing", "hair_stiffness", "haar_seed", "hair_cut")
#: The longest hairstyle name ``create_hairstyle`` derives from a description.
NAME_MAX = 48
_HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{6}")


def default_mode() -> str:
    """The world setting ``base_body.hairstyle_default_mode`` — the mode a
    new hairstyle gets when none is named (an unknown value =
    ``DEFAULT_HAIR_MODE``)."""
    from app.core import config
    from app.core.config_schema import field_default
    value = str(config.get("base_body.hairstyle_default_mode",
                           field_default("base_body", "hairstyle_default_mode")) or "")
    return value if value in BUILT_MODES else DEFAULT_HAIR_MODE


def is_hairstyle(item: Optional[Dict[str, Any]], character_name: str) -> bool:
    """Whether ``item`` is a hairstyle of the character: a garment of kind
    hair it owns."""
    return _is_own_hair(item, character_name)


def hairstyle_mode(item: Optional[Dict[str, Any]]) -> str:
    """The hairstyle's ``garment.mesh_mode`` (one of ``HAIR_MODES``). An item
    that names none was made for HairDeck — the only method hair items were
    made for before hairstyles (the boot migration names every mode)."""
    mode = str(((item or {}).get("garment") or {}).get("mesh_mode") or "")
    return mode if mode in HAIR_MODES else HAIRDECK_MODE


def hairstyle_description(item: Optional[Dict[str, Any]]) -> str:
    """The hairstyle's text (``garment.description``), "" without one."""
    return " ".join(str(((item or {}).get("garment") or {}).get("description") or "").split())


def hairstyle_settings(item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The hairstyle's HairDeck settings (``SETTING_KEYS`` of its
    ``garment``; a missing key = automatic / the default) — the mapping
    ``hair_colour_override``, ``hair_placement`` and ``hair_motion.settings``
    read."""
    garment = (item or {}).get("garment") or {}
    return {key: garment[key] for key in SETTING_KEYS if key in garment}


def hairstyles(character_name: str) -> List[Dict[str, Any]]:
    """Every hairstyle the character owns, by id."""
    from app.models import inventory
    return sorted((item for item in inventory.list_items() if _is_own_hair(item, character_name)),
                  key=lambda item: str(item.get("id") or ""))


def worn_hairstyle(character_name: str, profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The hairstyle the character wears (``worn_hair_id``), None without one."""
    item_id = worn_hair_id(character_name, profile)
    if not item_id:
        return None
    from app.models import inventory
    return inventory.get_item(item_id)


def hair_mode(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> str:
    """The character's hair mode: the worn hairstyle's (``hairstyle_mode``),
    "" without a worn hairstyle (no hair at all)."""
    item = worn_hairstyle(character_name, profile)
    return hairstyle_mode(item) if item is not None else ""


def hair_in_body(character_name: str, profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the worn hairstyle is part of the body mesh (mode ``body``)."""
    return hair_mode(character_name, profile=profile) == BODY_MODE


def plain_hairstyle(character_name: str, profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The hairstyle the plain body is the body of (profile key
    ``BASE_HAIRSTYLE_KEY``), None when it names none of the character's
    hairstyles."""
    profile = _profile_of(character_name, profile)
    item_id = str(profile.get(BASE_HAIRSTYLE_KEY) or "")
    if not item_id:
        return None
    from app.models import inventory
    item = inventory.get_item(item_id)
    return item if _is_own_hair(item, character_name) else None


def plain_hair_text(character_name: str, profile: Optional[Dict[str, Any]] = None) -> str:
    """The hair text the plain body is rendered with: the description of the
    plain hairstyle (``plain_hairstyle``) when its mode is ``body``, else ""
    — a bald plain body."""
    item = plain_hairstyle(character_name, profile)
    return hairstyle_description(item) if item is not None and hairstyle_mode(item) == BODY_MODE else ""


def shape_hair(character_name: str, profile: Optional[Dict[str, Any]] = None) -> str:
    """What the worn hairstyle adds to the body SHAPE (D4): "" when the plain
    body already has its hair (a ``body`` hairstyle whose text is the plain
    body's, or no hair in the body on a bald plain body); the hairstyle's
    text for a ``body`` hairstyle with another text; ``BALD`` when the plain
    body is haired but the worn hair is not in the body (HairDeck, HAAR, or
    no hairstyle worn)."""
    profile = _profile_of(character_name, profile)
    plain = plain_hair_text(character_name, profile)
    worn = worn_hairstyle(character_name, profile)
    if worn is not None and hairstyle_mode(worn) == BODY_MODE:
        text = hairstyle_description(worn)
        return "" if text == plain else (text or BALD)
    return BALD if plain else ""


def hair_style_id(character_name: str, profile: Optional[Dict[str, Any]] = None) -> str:
    """The worn hairstyle's id when it is NOT the plain body's hairstyle, ""
    otherwise — what tells two figures apart that differ only in the worn
    HairDeck hairstyle (``figure.Figure.hair_style``)."""
    profile = _profile_of(character_name, profile)
    worn = worn_hair_id(character_name, profile)
    return "" if not worn or worn == str(profile.get(BASE_HAIRSTYLE_KEY) or "") else worn


def hair_colour_override(settings: Optional[Dict[str, Any]]) -> str:
    """The manual hair colour of a hairstyle's settings (``hairstyle_settings``,
    key ``hair_colour``) as ``"#rrggbb"`` (lower case), ``""`` = automatic
    (HairDeck's own vertex colours). A value that is no ``#rrggbb`` counts as
    automatic."""
    value = str((settings or {}).get("hair_colour") or "").strip()
    return value.lower() if _HEX_COLOUR.fullmatch(value) else ""


def _own_hairstyle(character_name: str, item_id: str) -> Dict[str, Any]:
    """The character's hairstyle ``item_id``; ValueError when it is none."""
    from app.models import inventory
    item = inventory.get_item(str(item_id or ""))
    if not _is_own_hair(item, character_name):
        raise ValueError(f"{str(item_id)[:80]!r} is no hairstyle of {character_name}")
    return item


def set_hairstyle_settings(character_name: str, item_id: str, values: Dict[str, Any]) -> bool:
    """Store settings of one hairstyle (``SETTING_KEYS``; ``""`` / None =
    automatic, the key is dropped) in ONE read-modify-write of the item under
    ``keyed_lock("garment_item", character_name)``. ValueError for a key that
    is no setting or an item that is no hairstyle of the character. The
    update result; True without a write when unchanged."""
    from app.core.keyed_lock import keyed_lock
    from app.models import inventory
    unknown = sorted(set(values) - set(SETTING_KEYS))
    if unknown:
        raise ValueError(f"no hairstyle setting: {', '.join(unknown)}")
    with keyed_lock("garment_item", character_name):
        item = _own_hairstyle(character_name, item_id)
        garment = dict(item.get("garment") or {})
        for key, value in values.items():
            if value is None or value == "":
                garment.pop(key, None)
            else:
                garment[key] = value
        if garment == (item.get("garment") or {}):
            return True
        return inventory.update_item(item["id"], {"garment": garment}) is not None


def set_hairstyle_mode(character_name: str, item_id: str, mode: str) -> bool:
    """Set a hairstyle's mode (``""`` = the world's ``default_mode``).
    ValueError for an unknown mode or an item that is no hairstyle of the character. Starts nothing: a mode
    change of the plain body's hairstyle changes the base prompts (the plain
    body shows "older prompts" until a Build), of another hairstyle its
    shape (ruling P1)."""
    from app.core.keyed_lock import keyed_lock
    from app.models import inventory
    mode = _checked_mode(mode)
    with keyed_lock("garment_item", character_name):
        item = _own_hairstyle(character_name, item_id)
        garment = dict(item.get("garment") or {})
        if garment.get("mesh_mode") == mode:
            return True
        garment["mesh_mode"] = mode
        return inventory.update_item(item["id"], {"garment": garment}) is not None


def _checked_mode(mode: str) -> str:
    mode = str(mode or "").strip() or default_mode()
    if mode not in BUILT_MODES:
        raise ValueError(f"hair mode must be one of: {', '.join(BUILT_MODES)}")
    return mode


def set_haar_seed(character_name: str, item_id: str, seed: Optional[int]) -> bool:
    """Store the HAAR seed a hairstyle serves (``haar_seed``; None = automatic: the best passing seed) in ONE
    read-modify-write of the item under its lock (``set_hairstyle_settings``). Runs nothing: the fsig names the
    served seed, so the fit step reads due and its CPU refit (no hub job) applies it. ValueError for a seed that
    is no positive integer or an item that is no hairstyle of the character. The update result."""
    if seed is not None:
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 1:
            raise ValueError("HAAR seed must be a positive integer or empty")
    return set_hairstyle_settings(character_name, item_id, {"haar_seed": seed})


def hair_cut(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The HAAR cut of a hairstyle's settings (key ``hair_cut``, Ruling A71) as ``hair_cut.normalise`` gives it:
    ``{max_cm?, at?, ends_cm?}``, ``{}`` = automatic (the whole length, Auto ends). A stored value that no longer
    normalises (a limit changed) counts as automatic."""
    from app.core import hair_cut as cut_rule
    try:
        return cut_rule.normalise((settings or {}).get("hair_cut"))
    except ValueError:
        return {}


def set_hair_cut(character_name: str, item_id: str, value: Any) -> bool:
    """Store a hairstyle's HAAR cut (``hair_cut``: ``hair_cut.normalise``d; ``{}`` / None = automatic, the key is
    dropped) in ONE read-modify-write of the item (``set_hairstyle_settings``). Runs nothing: the cut is in the HAAR
    fit fingerprint, so the fit step reads due and its CPU refit (no hub job) applies it. ValueError for a value
    ``normalise`` refuses or an item that is no hairstyle of the character. The update result."""
    from app.core import hair_cut as cut_rule
    cut = cut_rule.normalise(value)
    return set_hairstyle_settings(character_name, item_id, {"hair_cut": cut or None})


def set_hairstyle_description(character_name: str, item_id: str, description: str) -> bool:
    """Store a hairstyle's text (``garment.description`` and the item's ``prompt_fragment``; a name that was made
    from the old text, ``hairstyle_name``, follows the new one) in ONE read-modify-write of the item under
    ``keyed_lock("garment_item", character_name)``. Runs nothing: what the text feeds reads due — HAAR's strands
    (``garment_store.garment_ssig``), a HairDeck fit, the plain body's prompts of hair in the body. ValueError for
    an empty text or an item that is no hairstyle of the character. The update result; True without a write when
    unchanged."""
    from app.core.keyed_lock import keyed_lock
    from app.models import inventory
    text = " ".join(str(description or "").split())
    if not text:
        raise ValueError("Describe the hairstyle")
    with keyed_lock("garment_item", character_name):
        item = _own_hairstyle(character_name, item_id)
        old = hairstyle_description(item)
        if text == old:
            return True
        garment = {**(item.get("garment") or {}), "description": text}
        changes: Dict[str, Any] = {"garment": garment, "prompt_fragment": text}
        if str(item.get("name") or "") in ("", hairstyle_name(old)):
            changes["name"] = hairstyle_name(text)
        return inventory.update_item(item["id"], changes) is not None


# --- The HAAR prompt from the profile picture (Ruling A105) -------------------------------------------------------
# A HAAR hairstyle's text (``garment.description``) IS the HAAR prompt (``garment_store.haar_prompt``). The
# Hairstyles tab's "Describe from profile picture" asks the vision task ``HAAR_PROMPT_TASK`` (template
# ``tasks/haar_hair_prompt.md``) to write that text off the character's profile picture; the answer is only a
# suggestion — the route saves nothing, the user edits it and saves it through ``set_hairstyle_description``.

#: The LLM task (``llm_tasks.TASK_TYPES``, unrouted → ``image_recognition``) and its template.
HAAR_PROMPT_TASK = "haar_hair_prompt"
#: The completion budget: one line of phrases — a cap against a model that rambles or loops.
HAAR_PROMPT_MAX_TOKENS = 200
#: The longest suggestion kept: HAAR's text encoder reads about 60 words; a longer answer is cut at the last
#: comma inside the cap (never mid-phrase).
HAAR_PROMPT_MAX_CHARS = 350

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_ANSWER_LABEL = re.compile(r"^\s*(?:hair(?:style)?(?:\s+description)?|description|prompt|answer)\s*:\s*",
                           re.IGNORECASE)
_REFUSAL = re.compile(r"\b(?:i\s*(?:'|’)?m\s+sorry|i\s+am\s+sorry|i\s+can(?:not|'t|’t)|i\s+(?:am|'m)\s+unable|"
                      r"unable\s+to|as\s+an\s+ai|cannot\s+(?:help|assist|describe|see)|no\s+(?:image|picture)\s+"
                      r"(?:was\s+)?(?:attached|provided)|i\s+don(?:'|’)t\s+see)\b", re.IGNORECASE)


def clean_haar_prompt(answer: Any) -> str:
    """The usable HAAR text of an LLM answer: no ``<think>`` block, no markdown (``*``/``_``/backticks/headings/
    bullets), no label ("Description:"), no surrounding quotes, one line, no trailing full stop, cut at the last
    comma inside ``HAAR_PROMPT_MAX_CHARS``. ValueError for an empty answer or a refusal."""
    text = _THINK_BLOCK.sub("", str(answer or ""))
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:#+|[-*•]|\d+[.)])\s+", "", line)
        line = _ANSWER_LABEL.sub("", line.replace("**", "").replace("__", "").replace("`", ""))
        line = line.strip().strip("\"'“”‘’").strip()
        if line:
            lines.append(line)
    text = ", ".join(lines)
    text = " ".join(text.split()).strip(" ,;").rstrip(".").strip().strip("\"'“”‘’").strip()
    if not text:
        raise ValueError("the LLM answered nothing usable")
    if _REFUSAL.search(text):
        raise ValueError(f"the LLM refused or saw no picture: {text[:120]!r}")
    if len(text) > HAAR_PROMPT_MAX_CHARS:
        cut = text[:HAAR_PROMPT_MAX_CHARS]
        text = (cut[:cut.rfind(",")] if "," in cut else cut.rsplit(" ", 1)[0]).strip(" ,;")
    return text


def suggest_haar_prompt(character_name: str, item_id: str) -> str:
    """A HAAR text for hairstyle ``item_id`` of ``character_name`` read off the character's current profile picture
    (``model_refs.current_profile_image``) by ONE queued vision call (``llm_router.llm_call`` with the picture
    attached; task ``HAAR_PROMPT_TASK``). Saves nothing. ValueError for an item that is no hairstyle of the
    character or a character without a profile picture; RuntimeError when the LLM is not routed, fails or answers
    unusably (empty, a refusal)."""
    from app.core.llm_router import llm_call
    from app.core.model_refs import current_profile_image
    from app.core.prompt_templates import render_task
    item = _own_hairstyle(character_name, item_id)
    picture = current_profile_image(character_name)
    if picture is None:
        raise ValueError(f"{character_name} has no profile picture — set one in the Images tab first")
    system, user = render_task(HAAR_PROMPT_TASK, hairstyle_name=" ".join(str(item.get("name") or "").split()),
                               current_text=hairstyle_description(item))
    response = llm_call(task=HAAR_PROMPT_TASK, system_prompt=system, user_prompt=user, agent_name=character_name,
                        max_tokens=HAAR_PROMPT_MAX_TOKENS, label=f"haar_hair_prompt:{item['id']}",
                        image_path=picture)
    try:
        return clean_haar_prompt(getattr(response, "content", "") or "")
    except ValueError as e:
        raise RuntimeError(str(e)) from e


def set_hair_colour(character_name: str, item_id: str, hex_colour: str) -> bool:
    """Store a hairstyle's manual hair colour (``hair_colour``, lower-case
    ``#rrggbb``); ``""`` = automatic (HairDeck's own colours). ValueError for
    anything else. Only the HairDeck fit fingerprint changes: the next run
    re-fits from the cached HairDeck job."""
    value = str(hex_colour or "").strip()
    if value and not _HEX_COLOUR.fullmatch(value):
        raise ValueError("hair colour must be #rrggbb or empty")
    return set_hairstyle_settings(character_name, item_id, {"hair_colour": value.lower()})


#: The setting keys of the HairDeck placement correction (``garment_hairdeck.fit_hairdeck``'s ``forward_m`` /
#: ``tilt_deg`` / ``width_scale`` / ``up_m``); empty = automatic (width: ``garment_hairdeck.auto_width_scale``; up/down:
#: no shift, Ruling A85).
PLACEMENT_KEYS: Dict[str, str] = {"forward_m": "hair_forward_m", "tilt_deg": "hair_tilt_deg",
                                  "width_scale": "hair_width_scale", "up_m": "hair_up_m"}
#: Placement values that enter ``hair_placement`` (and so the fit fingerprint) only when set: a hair without a
#: width or an up/down keeps the fingerprint it had before they existed (the CPU refit sweep only re-fits a stale fit
#: under its unchanged fingerprint, ``garment_refit.outdated_fits``).
_PLACEMENT_WHEN_SET = ("width_scale", "up_m")


def _placement_range(name: str) -> Tuple[float, float]:
    from app.core import garment_hairdeck as gh
    return {"width_scale": tuple(gh.WIDTH_SCALE_LIMITS),
            "forward_m": (-gh.FORWARD_LIMIT_M, gh.FORWARD_LIMIT_M),
            "tilt_deg": (-gh.TILT_BACK_LIMIT_DEG, gh.TILT_FORWARD_LIMIT_DEG),
            "up_m": (-gh.UP_LIMIT_M, gh.UP_LIMIT_M)}[name]


def placement_limits() -> Dict[str, Any]:
    """The bounds of the manual values for the hair placement (``HairDeckPlacement``): ``|forward_m|``,
    ``|up_m|`` and ``[lo, hi]`` of ``tilt_deg`` (asymmetric since Ruling A85: back 15, forward 30) and of
    ``width_scale``."""
    from app.core import garment_hairdeck as gh
    return {"forward_m": gh.FORWARD_LIMIT_M, "tilt_deg": list(_placement_range("tilt_deg")),
            "up_m": gh.UP_LIMIT_M, "width_scale": list(gh.WIDTH_SCALE_LIMITS)}


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


def hair_placement(settings: Optional[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    """``{forward_m, tilt_deg[, width_scale][, up_m]}``: the manual HairDeck placement of a hairstyle's settings
    (``hairstyle_settings``, keys ``hair_forward_m`` — metres along +z —, ``hair_tilt_deg`` — forward pitch,
    degrees —, ``hair_width_scale`` — the sides' reach beyond the head, ``garment_hairdeck.narrow_sides`` — and
    ``hair_up_m`` — metres along +y, Ruling A85); None = automatic (forward ``garment_hairdeck.DEFAULT_FORWARD_M``,
    tilt solved to the brow line, no up/down). ``width_scale`` and ``up_m`` are present only when set
    (``_PLACEMENT_WHEN_SET``). A stored value that is no number or lies
    beyond its range counts as automatic."""
    out: Dict[str, Optional[float]] = {}
    for name, key in PLACEMENT_KEYS.items():
        try:
            value = _placement_value(name, (settings or {}).get(key))
        except ValueError:
            value = None
        if value is not None or name not in _PLACEMENT_WHEN_SET:
            out[name] = value
    return out


def set_hair_placement(character_name: str, item_id: str, forward_m: Any, tilt_deg: Any,
                       width_scale: Any = None, up_m: Any = None) -> bool:
    """Store a hairstyle's manual HairDeck placement (``hair_forward_m`` / ``hair_tilt_deg`` /
    ``hair_width_scale`` / ``hair_up_m``; None or "" = automatic, the key is dropped). ValueError for a non-number
    or a value beyond its range (``_placement_range``) — nothing is stored then. All keys are written in ONE read-modify-write of the item (``set_hairstyle_settings``). Only the
    HairDeck fit fingerprint changes: the next run re-fits from the cached HairDeck job."""
    values = {"forward_m": _placement_value("forward_m", forward_m),
              "tilt_deg": _placement_value("tilt_deg", tilt_deg),
              "width_scale": _placement_value("width_scale", width_scale),
              "up_m": _placement_value("up_m", up_m)}
    return set_hairstyle_settings(character_name, item_id,
                                  {PLACEMENT_KEYS[name]: value for name, value in values.items()})


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


def hair_length_class(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
                      text: Optional[str] = None) -> Optional[str]:
    """The length class (``LENGTH_CLASSES``) of the hair ``text`` (None: the worn hairstyle's) or None: for the
    Appearance's hair (``_is_appearance_hair``) the value of the attribute the hair slot declares for its
    mesh-input line (the human pack: ``length``) when it is a class; else the first class word of the text
    ("short brunette hair" -> "short")."""
    profile = _profile_of(character_name, profile)
    text = _text_of(character_name, profile, text)
    slot = _hair_slot(character_name, profile) if _is_appearance_hair(character_name, profile, text) else None
    if slot is not None and getattr(slot, "mesh_input_prompt", None):
        from app.core.body_slots import slot_values
        key = slot.mesh_input_prompt.get("attribute")
        value = str((slot_values(character_name, profile=profile).get(slot.id) or {}).get(key) or "")
        if " ".join(value.lower().split()) in LENGTH_CLASSES:
            return " ".join(value.lower().split())
    match = _LENGTH_CLASS_WORD.search(text)
    return " ".join(match.group(1).lower().split()) if match else None


def hair_colour_name(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
                     text: Optional[str] = None) -> Optional[str]:
    """The named colour of the hair ``text`` (None: the worn hairstyle's; a ``HAIR_COLOURS`` key) or None: per
    clause, the colour word nearest before a "hair" within ``_COLOUR_REACH_WORDS`` words ("brown eyes and black
    hair" -> black); the first clause with one wins."""
    for clause in _text_of(character_name, _profile_of(character_name, profile), text).lower().split(","):
        for hair in _HAIR_AT.finditer(clause):
            window = " ".join(clause[:hair.start()].split()[-_COLOUR_REACH_WORDS:])
            found = list(_COLOUR_WORD.finditer(window))
            if found:
                return found[-1].group(1)
    return None


def profile_hair_colour(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
                        text: Optional[str] = None) -> Optional[Dict[str, str]]:
    """``{name, hex}`` of the hair text's named colour (``hair_colour_name``), None without one."""
    name = hair_colour_name(character_name, profile=profile, text=text)
    return {"name": name, "hex": HAIR_COLOURS[name]} if name else None


def colour_target(hex_colour: str) -> Optional[Tuple[float, float, float]]:
    """``"#rrggbb"`` -> sRGB 0..1 (``garment_hairdeck.fit_hairdeck``'s
    ``colour_target``); ``""`` -> None (keep HairDeck's colours)."""
    if not hex_colour:
        return None
    if not _HEX_COLOUR.fullmatch(hex_colour):
        raise ValueError(f"no #rrggbb colour: {hex_colour[:20]!r}")
    return tuple(int(hex_colour[i:i + 2], 16) / 255.0 for i in (1, 3, 5))  # type: ignore[return-value]


def fsig_inputs(character_name: str, item_id: str, *, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What a hairstyle contributes to the garment fingerprint
    (``garment_store.garment_fsig``, R10): its description, whether that hair
    falls behind the shoulders, and the pronouns the prompts use. A migrated
    hairstyle carries the text the fingerprint was made of, so its fits stay
    current."""
    profile = _profile_of(character_name, profile)
    from app.models import inventory
    text = hairstyle_description(inventory.get_item(str(item_id or "")))
    return {"description": text,
            "behind_shoulders": hair_behind_shoulders(character_name, profile=profile, text=text),
            "pronouns": list(pronouns(profile))}


def _is_own_hair(item: Optional[Dict[str, Any]], character_name: str) -> bool:
    return bool(item and item.get("category") == "garment"
                and (item.get("owner") or "").strip() == character_name
                and (item.get("garment") or {}).get("kind") == HAIR_KIND)


def worn_hair_id(character_name: str, profile: Optional[Dict[str, Any]] = None) -> str:
    """The id of the hairstyle the character wears in the hair slot of
    ``equipped_mesh_pieces`` (a garment of kind hair it owns, any mode), ""
    without one."""
    profile = _profile_of(character_name, profile)
    worn = profile.get("equipped_mesh_pieces")
    item_id = worn.get(HAIR_KIND) if isinstance(worn, dict) else None
    if not item_id:
        return ""
    from app.models import inventory
    return str(item_id) if _is_own_hair(inventory.get_item(str(item_id)), character_name) else ""


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


def hairstyle_name(description: str) -> str:
    """The name a new hairstyle gets: its description, capitalised, cut at a
    word to ``NAME_MAX`` characters; ``HAIR_ITEM_NAME`` for an empty one."""
    text = " ".join(str(description or "").split())
    if not text:
        return HAIR_ITEM_NAME
    if len(text) > NAME_MAX:
        cut = text[:NAME_MAX].rsplit(" ", 1)[0].rstrip(" ,;")
        text = (cut or text[:NAME_MAX]) + "…"
    return text[:1].upper() + text[1:]


def _check_hairstyle_owner(character_name: str, profile: Dict[str, Any]):
    """The hair body slot of a humanoid; ValueError for a non-humanoid or a
    species without a hair mesh-item slot."""
    from app.core.model_refs import is_humanoid
    if not is_humanoid(character_name, profile=profile):
        raise ValueError("Hairstyles are for humanoid characters only")
    slot = _hair_slot(character_name, profile)
    if slot is None:
        raise ValueError(f"No hair slot is declared for {character_name}")
    return slot


def _mint_hairstyle(character_name: str, slot_id: str, description: str, mode: str,
                    settings: Optional[Dict[str, Any]] = None, *, item_id: str = "") -> Dict[str, Any]:
    """Add a hairstyle item (the caller holds ``keyed_lock("garment_item",
    character_name)``). Worn nowhere, carried by nobody."""
    from app.models import inventory
    garment = {"kind": HAIR_KIND, "slot": HAIR_KIND, "body_slot": slot_id, "mesh_mode": mode,
               "description": description,
               **{k: v for k, v in (settings or {}).items() if k in SETTING_KEYS and v not in (None, "")}}
    item = inventory.add_item(
        name=hairstyle_name(description), category="garment", owner=character_name,
        prompt_fragment=description, garment=garment, item_id=item_id or _new_item_id(character_name),
        transferable=False, portable=False)
    logger.info("hairstyle created for %s: %s (%s)", character_name, item["id"], mode)
    return item


def _claim_first(character_name: str, item_id: str) -> None:
    """A character's first hairstyle becomes the plain body's hairstyle and is
    worn — when the profile names no plain hairstyle / wears none yet (one
    read-modify-write under the profile lock). Wearing it asks for the
    garment assembly, as every mesh-item equip does."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        changed = worn_now = False
        if plain_hairstyle(character_name, profile) is None:
            profile[BASE_HAIRSTYLE_KEY] = item_id
            changed = True
        worn = dict(profile.get("equipped_mesh_pieces") or {}) if isinstance(
            profile.get("equipped_mesh_pieces"), dict) else {}
        if not worn_hair_id(character_name, profile):
            worn[HAIR_KIND] = item_id
            profile["equipped_mesh_pieces"] = worn
            changed = worn_now = True
        if changed and not save_character_profile(character_name, profile):
            raise RuntimeError(f"Could not store the first hairstyle of {character_name}")
    if worn_now:
        try:
            from app.core import garment_assembly
            garment_assembly.schedule(character_name)
        except Exception as e:  # noqa: BLE001 — a failed schedule must not undo the stored state
            logger.warning("garment assembly schedule for %s failed: %s", character_name, e)


def create_hairstyle(character_name: str, description: str, mode: str = "") -> str:
    """Create a hairstyle of the character; returns its item id.

    ``description`` the hairstyle's text (empty: the Appearance's hair text,
    ``appearance_hair_text``); ``mode`` one of ``BUILT_MODES`` (``""``: the
    world's ``default_mode``). ValueError for an unknown mode, a non-humanoid, a species without a hair slot, or no
    text at all. Starts nothing; the new hairstyle is not worn — except the
    character's FIRST one, which is worn and becomes the plain body's
    hairstyle (``BASE_HAIRSTYLE_KEY``)."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile
    mode = _checked_mode(mode)
    with keyed_lock("garment_item", character_name):
        profile = get_character_profile(character_name) or {}
        slot = _check_hairstyle_owner(character_name, profile)
        text = " ".join(str(description or "").split()) or appearance_hair_text(character_name, profile=profile)
        if not text:
            raise ValueError("No hair set — describe the hairstyle, or fill in the hair in Appearance")
        item = _mint_hairstyle(character_name, slot.id, text, mode)
        _claim_first(character_name, item["id"])
    return item["id"]


def ensure_hairstyle(character_name: str) -> str:
    """The worn hairstyle's id; a humanoid that owns none gets its first one
    made from its Appearance (``create_hairstyle`` with the world's
    ``default_mode``) — before a plain body is rendered for it, so the plain
    body is that hairstyle's body. "" for a character that wears none but
    owns some (one was taken off), and for a character without any hair text
    (bald). ValueError like ``create_hairstyle`` otherwise.

    Check and create run under ``keyed_lock("garment_item", name)`` — the lock every hairstyle mint holds
    (``create_hairstyle``, the boot migration), taken before the profile lock as they do — so two concurrent
    callers never both mint a first hairstyle. Nothing in it waits on a render or an LLM."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile
    with keyed_lock("garment_item", character_name):
        profile = get_character_profile(character_name) or {}
        worn = worn_hair_id(character_name, profile)
        if worn:
            return worn
        if hairstyles(character_name):
            return ""
        if not appearance_hair_text(character_name, profile=profile):
            return ""
        return create_hairstyle(character_name, "", "")


def wear_hairstyle(character_name: str, item_id: str, *, request: bool = True) -> bool:
    """Wear the character's hairstyle ``item_id`` (``equipped_mesh_pieces
    ["hair"]``, read-modify-write under the profile lock). ValueError for an
    item that is no hairstyle of the character. The save result; True
    without a save when it is already worn. Builds nothing: a changed
    hairstyle is an outfit change (D5) — ``figure_build.request(name,
    "outfit_change")`` decides (Build automatically, else a pending change);
    ``request=False`` leaves that request to the caller (an outfit set
    applies pieces and hairstyle, then requests once)."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    _own_hairstyle(character_name, item_id)
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        worn = dict(profile.get("equipped_mesh_pieces") or {}) if isinstance(
            profile.get("equipped_mesh_pieces"), dict) else {}
        if worn.get(HAIR_KIND) == item_id:
            return True
        worn[HAIR_KIND] = item_id
        profile["equipped_mesh_pieces"] = worn
        saved = bool(save_character_profile(character_name, profile))
    if saved:
        logger.info("hairstyle worn by %s: %s", character_name, item_id)
        from app.core import figure, figure_build
        figure.invalidate()
        if request:
            figure_build.request(character_name, "outfit_change")
    return saved


def request_outfit_build(character_name: str) -> None:
    """The ONE Build request of an outfit set that changed the hairstyle
    (``wear_outfit_hairstyle`` True): the debounce timer its pieces may have
    armed is disarmed (``model_refs.cancel_build_timer``) and the Build is
    requested now (``figure_build.request(name, "outfit_change")``) — it
    sees the pieces and the hairstyle together."""
    from app.core import figure_build, model_refs
    model_refs.cancel_build_timer(character_name)
    figure_build.request(character_name, "outfit_change")


def wear_outfit_hairstyle(character_name: str, outfit: Dict[str, Any]) -> bool:
    """Wear the hairstyle a saved outfit set names (``outfit["hairstyle"]``,
    D5) without requesting the Build (``wear_hairstyle(request=False)``).
    True when the worn hairstyle changed — the caller then asks the Build
    once (``request_outfit_build``). A set without one, or naming an item that is no hairstyle of the
    character any more (deleted), changes nothing (a WARNING for the
    latter)."""
    item_id = str((outfit or {}).get("hairstyle") or "").strip()
    if not item_id:
        return False
    from app.models.character import get_character_profile
    if worn_hair_id(character_name, get_character_profile(character_name) or {}) == item_id:
        return False
    try:
        return wear_hairstyle(character_name, item_id, request=False)
    except ValueError as e:
        logger.warning("outfit set of %s: hairstyle %s not worn — %s", character_name, item_id, e)
        return False


def wear_estimate(character_name: str, item_id: str, *,
                  profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """What wearing the hairstyle ``item_id`` spends after the click (the Hairstyles tab's Wear button, the
    user's rule "every button names the hub jobs it causes"): ``{hub_jobs, due_now, extra, automatic, note}`` —
    ``hub_jobs`` the Build plan
    of the profile with ``item_id`` worn instead (``figure_build.plan`` of that profile, ``figure_build.cost``):
    an automatic Build when "Build automatically" is on (``automatic`` True: the Build starts by itself), else
    the manual Build the user starts later; ``due_now`` the same plan's cost for the profile as it is (due anyway),
    ``extra`` what wearing adds (``hub_jobs - due_now``, at least 0). Each None when a step's cost is unknown. None off the
    figure pipeline, for the worn hairstyle, or when the plan cannot be made. Read-only: the profile is copied,
    nothing is stored or started."""
    from app.core import figure_build
    profile = _profile_of(character_name, profile)
    try:
        if not figure_build.on_pipeline(character_name, profile=profile):
            return None
        worn = profile.get("equipped_mesh_pieces")
        worn = dict(worn) if isinstance(worn, dict) else {}
        if worn.get(HAIR_KIND) == item_id:
            return None
        automatic = bool(figure_build.auto_build_on(character_name, profile=profile))
        trial = {**profile, "equipped_mesh_pieces": {**worn, HAIR_KIND: item_id}}
        steps = figure_build.plan(character_name, profile=trial, explicit=not automatic)
        cost = figure_build.cost(character_name, steps)
        # What is due WITHOUT the change (the same kind of plan of the profile as it is): the button names only
        # the difference, the rest is the Build that is due anyway.
        now = figure_build.cost(character_name, figure_build.plan(character_name, profile=profile,
                                                                   explicit=not automatic))
    except Exception:  # noqa: BLE001 — a label, never a failure of the list
        logger.exception("Wear estimate of %s for %s failed", item_id, character_name)
        return None
    total, due = cost["hub_jobs"], now["hub_jobs"]
    extra = max(0, total - due) if total is not None and due is not None else None
    return {"hub_jobs": total, "due_now": due, "extra": extra, "automatic": automatic, "note": cost["note"]}


def hairstyle_list(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """The Hairstyles tab's list: per owned hairstyle ``{id, name,
    description, mode, worn, plain, freshness}`` — worn first, then by id.
    ``plain``: the plain body is this hairstyle's body; ``freshness``
    (``model_overview.freshness`` shape ``{state, reason}``): a ``body``
    hairstyle is ``current`` when it is the plain body's (its hair is in the
    plain body) and ``missing`` otherwise (its body shape is made by a
    Build); a HairDeck or HAAR one is ``current`` with an accepted fit on the
    current base model, ``stale`` with an older fit only, ``missing``
    without. Read-only."""
    from app.core import base_body, garment_store
    from app.core.model_overview import CURRENT, MISSING, STALE, freshness
    profile = _profile_of(character_name, profile)
    worn = worn_hair_id(character_name, profile)
    plain = str(profile.get(BASE_HAIRSTYLE_KEY) or "")
    base = base_body.current_base(character_name, profile=profile)
    out: List[Dict[str, Any]] = []
    for item in hairstyles(character_name):
        item_id = str(item.get("id") or "")
        mode = hairstyle_mode(item)
        if mode == BODY_MODE:
            fresh = freshness(CURRENT) if item_id == plain else freshness(MISSING, "Body shape made by a Build")
        else:
            try:
                served = (garment_store.accepted_fit(character_name, item_id, base_model_sha=base[1],
                                                     profile=profile) if base and base[1] else None)
                newest = garment_store.newest_accepted_fits(character_name, item_id).get(mode)
            except ValueError:
                served = newest = None
            name = "HairDeck" if mode == HAIRDECK_MODE else "HAAR"
            fresh = (freshness(CURRENT) if served else freshness(STALE, "Fitted on an older body") if newest
                     else freshness(MISSING, f"No {name} fit yet"))
        out.append({"id": item_id, "name": str(item.get("name") or item_id),
                    "description": hairstyle_description(item), "mode": mode,
                    "worn": item_id == worn, "plain": item_id == plain, "freshness": fresh})
    out.sort(key=lambda e: not e["worn"])
    return out
