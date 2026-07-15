"""Character height — one number, two consumers.

Height used to be a body-slot attribute of the ``human`` package: a word from
a fixed list (petite / short / average height / tall / giant). That works for
image prompts but says nothing a 3D client can scale by.

It is now a STANDARD profile field in CENTIMETRES (``height``, Identity, under
Age). Both consumers are served from that single number:

* prompts get a DESCRIPTIVE phrase — ``{height}`` still resolves, and still to
  the same vocabulary as before, so the human package's ``"{height}, {type}
  build"`` keeps working unchanged;
* the 3D client gets the raw centimetres and scales the figures against each
  other (a 155 cm character must not tower over a 190 cm one).

What "tall" means depends on the figure: the buckets are gender-aware for
humanoids, and a non-humanoid simply reports its centimetres.
"""
from typing import Any, Dict, Optional, Tuple

from app.core.log import get_logger

logger = get_logger(__name__)

# Same vocabulary the human package's build slot used before the move — the
# prompts keep rendering exactly what they used to.
_BUCKETS = {
    "female": ((153, "petite"), (160, "short"), (172, "average height"),
               (181, "tall"), (999, "giant")),
    "male": ((163, "petite"), (171, "short"), (183, "average height"),
             (193, "tall"), (999, "giant")),
}
# Anything that is not clearly female/male uses the midpoint of the two.
_BUCKETS_NEUTRAL = ((158, "petite"), (166, "short"), (178, "average height"),
                    (187, "tall"), (999, "giant"))

# Attraction aliases for the height word — surfaced through the core attraction
# tables (body_slots.interest_alias_tables / slot_attr_values). Height left the
# human package for a core profile field, so core carries these now (R1: a core
# field, not a pack detail); the exact lists the deleted build.height slot
# declared, keyed by the words describe() produces.
HEIGHT_INTEREST_ALIASES = {
    "tall": ["gross", "groß", "große", "grosse", "großer", "grosser", "tall"],
    "giant": ["gross", "groß", "große", "grosse", "großer", "grosser", "tall"],
    "short": ["klein", "kleine", "kleiner", "short", "petite", "zierlich",
              "zierliche"],
    "petite": ["klein", "kleine", "kleiner", "short", "petite", "zierlich",
               "zierliche"],
}


def parse_cm(value: Any) -> Optional[int]:
    """Height in centimetres from a profile value ("172", 172, "172 cm")."""
    if value is None:
        return None
    try:
        text = str(value).strip().lower().replace("cm", "").strip()
        if not text:
            return None
        cm = int(round(float(text.replace(",", "."))))
    except (TypeError, ValueError):
        return None
    return cm if 20 <= cm <= 300 else None


def describe(cm: int, gender: str = "", humanoid: bool = True) -> str:
    """The descriptive phrase for a height — the vocabulary the image prompts
    have always used. A non-humanoid gets its plain centimetres (a "tall" dog
    means nothing to an image model, "60 cm tall" does)."""
    if not humanoid:
        return f"{cm} cm tall"
    table = _BUCKETS.get((gender or "").strip().lower(), _BUCKETS_NEUTRAL)
    for limit, word in table:
        if cm < limit:
            return word
    return table[-1][1]


def height_cm(profile: Dict[str, Any]) -> Optional[int]:
    """The character's height in cm, or None when unset."""
    return parse_cm((profile or {}).get("height"))


def _is_humanoid(profile: Dict[str, Any], character_name: str = "") -> bool:
    """Humanoid check for the height buckets: the template feature when a name
    is known, otherwise inferred from the profile's template (an animal template
    is the only non-humanoid case)."""
    if character_name:
        try:
            from app.core.model_refs import is_humanoid
            return bool(is_humanoid(character_name))
        except Exception:
            return True
    return "animal" not in str((profile or {}).get("template", "")).lower()


def height_phrase(profile: Dict[str, Any], character_name: str = "") -> str:
    """``{height}`` for prompts: the descriptive phrase, "" when unset (the
    fragment then drops the token — ``"{height}, {type} build"`` degrades to
    "athletic build")."""
    cm = height_cm(profile)
    if cm is None:
        return ""
    gender = str((profile or {}).get("gender") or "").strip().lower()
    return describe(cm, gender, _is_humanoid(profile, character_name))


def height_word(profile: Dict[str, Any], character_name: str = "") -> str:
    """The height BUCKET word (petite/short/average height/tall/giant) for
    attraction matching, or "" when unset or non-humanoid (a non-humanoid
    reports centimetres, which is not one of the attraction buckets)."""
    cm = height_cm(profile)
    if cm is None or not _is_humanoid(profile, character_name):
        return ""
    gender = str((profile or {}).get("gender") or "").strip().lower()
    return describe(cm, gender, True)


# ---------------------------------------------------------------------------
# One-time migration: the old body-slot word -> centimetres
# ---------------------------------------------------------------------------

# Typical centimetres for the words the build slot used to store. Rough by
# nature — the point is that nobody starts from zero; the exact number is one
# edit away in the Identity tab.
_WORD_TO_CM = {
    "female": {"petite": 152, "short": 158, "average height": 166,
               "average": 166, "tall": 176, "giant": 188},
    "male": {"petite": 162, "short": 168, "average height": 178,
             "average": 178, "tall": 188, "giant": 198},
}
# Mirror of _BUCKETS_NEUTRAL: anything that is not clearly female/male gets
# the midpoint of the two tables, so word -> cm -> describe() round-trips to
# the SAME word (176 from the female table would render "average height"
# through the neutral buckets).
_WORD_TO_CM_NEUTRAL = {"petite": 157, "short": 163, "average height": 172,
                       "average": 172, "tall": 182, "giant": 193}


def migrate_profile_height(profile: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Convert one profile's legacy ``body_slots.build.height`` word into the cm
    field, IN PLACE. Same tables and neutral-midpoint rule as the one-time
    migration; never overwrites an existing height.

    Returns ``(changed, unconverted_word)``:
      * ``changed`` — the profile was modified (converted, or the stale word was
        dropped next to an existing height);
      * ``unconverted_word`` — a custom word with no cm mapping was found and
        LEFT in place (not destroyed — the attribute left the package, so it no
        longer renders; the admin re-enters it as cm), else None.
    """
    slots = profile.get("body_slots") or {}
    word = str(((slots.get("build") or {}).get("height") or "")).strip().lower()
    if not word:
        return False, None
    if height_cm(profile) is None:
        # Same table selection as describe(): unknown gender -> neutral.
        gender = str(profile.get("gender") or "").strip().lower()
        table = _WORD_TO_CM.get(gender, _WORD_TO_CM_NEUTRAL)
        cm = table.get(word)
        if not cm:
            return False, word
        profile["height"] = cm
    # Converted (or redundant next to an existing height) — the word itself is
    # gone from the package, drop the stale value.
    build = dict(slots.get("build") or {})
    build.pop("height", None)
    slots = dict(slots)
    if build:
        slots["build"] = build
    else:
        slots.pop("build", None)
    profile["body_slots"] = slots
    return True, None


def migrate_height_to_profile_once() -> None:
    """Moves the human package's ``build.height`` word into the new profile
    field, as centimetres. Idempotent, world_kv-marked; never overwrites a
    height a character already has."""
    try:
        from app.models.world import get_world_setting, set_world_setting
        from app.models.character import (list_available_characters,
                                          get_character_profile,
                                          save_character_profile)
        if get_world_setting("migrated_height_cm"):
            return
        moved = 0
        unconverted = []
        for name in list_available_characters():
            profile = get_character_profile(name) or {}
            changed, unconverted_word = migrate_profile_height(profile)
            if unconverted_word:
                unconverted.append(f"{name} ({unconverted_word!r})")
            if changed:
                save_character_profile(name, profile)
                moved += 1
        set_world_setting("migrated_height_cm", "1")
        if moved:
            logger.info("Height migration: %d character(s) migrated to cm", moved)
        if unconverted:
            logger.warning(
                "Height migration: %d height word(s) had no cm mapping and were "
                "left in body_slots.build.height — set Height (cm) manually in "
                "the Identity tab: %s", len(unconverted), ", ".join(unconverted))
    except Exception as e:
        logger.warning("Height migration failed: %s", e)
