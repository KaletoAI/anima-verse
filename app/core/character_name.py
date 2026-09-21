"""The ONE rule for what a character name may be.

Dependency-free on purpose: every path that CREATES a character imports this
module, including the model layer (``app.models.character``) and the auth gate
(``app.core.auth_dependency``), so it must not pull anything from ``app`` at
import time.

Scope — creation and import ONLY. An existing character is never re-validated:
nothing here runs on a load, nothing renames, and a name that is already in the
world keeps working even when it would be rejected today.

The rule
    * Unicode letters of any script (``str.isalpha`` on the NFC-composed name),
      digits, space (U+0020), hyphen ``-``, apostrophe ``'`` (the typographic
      ``’`` U+2019 is accepted too, and kept as written — a name is never
      rewritten), and period ``.``.
    * Everything else is forbidden: ``/ \\ < > [ ] " ? # % : * |``, control
      characters, tabs, newlines, any other whitespace.
    * No leading/trailing space or period (surrounding whitespace is stripped
      first, as every caller did before), no two spaces in a row, no ``..``.
    * 1..60 characters, at least one letter or digit.
    * Not a reserved name (case-insensitive) — see the sets below.

This module is also the single source of truth for the reserved-name sets:
``app.models.character``, ``app.models.account`` and ``app.core.auth_dependency``
import them from here, and there is deliberately no second copy of any of these
lists in the codebase.
"""
from __future__ import annotations

import unicodedata
from typing import Dict, Optional, Set

#: Maximum length of a character name, in NFC-composed characters.
MAX_NAME_LENGTH = 60

#: Punctuation a character name may carry besides letters, digits and spaces.
#: The typographic apostrophe is accepted as written — names are never
#: normalized into the ASCII one (feedback_no_name_resolution: nothing in this
#: project silently alters a name).
#: The underscore is ordinary inside a name; a LEADING underscore is reserved
#: for internal system characters (``character._is_real_character``).
ALLOWED_PUNCTUATION = frozenset("-'’._")

#: JS-stringified null values. They appear whenever some frontend path
#: interpolates ``${value}`` on an undefined/null/NaN value; without this guard
#: they create a ghost character named "undefined".
JS_NULL_NAMES: Set[str] = {"undefined", "null", "none", "nan"}

#: The legacy placeholder of the pre-2026 UI, where the single chat partner was
#: literally called "KI" (German for "AI"). It is not an in-world name but the
#: leftover of an uninitialized frontend, so it must never become a character
#: directory. ``app.models.character.get_character_dir`` guards on this exact
#: spelling; the validator rejects it case-insensitively like every other
#: reserved name.
LEGACY_PLACEHOLDER_NAME = "KI"

#: Login/role names that must NEVER leak into the world as a character or
#: speaker — they would show up in ``chat_messages.partner``, in
#: ``relationships.from_char`` and in prompts as "what admin said...".
#: Imported by ``app.models.account`` as ``_RESERVED_LOGIN_NAMES``.
RESERVED_LOGIN_NAMES: Set[str] = {
    "user", "admin", "system", "default", "player", "",
}

#: Names that belong to the account/system layer, not to a character: the login
#: roles above plus the JS nulls. Imported by ``app.models.character`` as
#: ``_RESERVED_NAMES`` — the roster rule, every save path and the relationship
#: model read it from there.
RESERVED_NAMES: Set[str] = RESERVED_LOGIN_NAMES | JS_NULL_NAMES

#: First path segment after ``/characters/`` that is a COLLECTION endpoint, not
#: a character name (``/characters/list``, ``/characters/at-location``, ...).
#: Imported by ``app.core.auth_dependency`` as ``_RESERVED_CHARACTER_NAMES``:
#: a character carrying one of these names would make its own URLs ambiguous.
RESERVED_ROUTE_SEGMENTS: Set[str] = {
    "list", "chatbots", "at-location", "animate", "available-models",
    "outfit-rules", "outfit-lora-options", "skills", "create", "import",
    "graph", "migrate", "backfill", "",
}

#: Everything a new character may NOT be called, case-folded.
_RESERVED_ALL: Set[str] = (
    {n.casefold() for n in RESERVED_NAMES}
    | {n.casefold() for n in RESERVED_ROUTE_SEGMENTS}
    | {LEGACY_PLACEHOLDER_NAME.casefold()}
)


class CharacterNameError(ValueError):
    """A name that may not be given to a NEW character.

    ``code`` is the machine-readable reason (``empty``, ``too_long``,
    ``forbidden_char``, ``edge``, ``double_space``, ``double_dot``,
    ``reserved``, ``no_alnum``), ``char`` the offending character where one
    exists. ``template`` is the English source string with ``{}`` placeholders
    and ``params`` its values, so a caller with a UI language can render it as
    ``t(err.template, lang).format(**err.params)`` — see
    :func:`localized_message`.
    """

    def __init__(self, code: str, template: str,
                 params: Optional[Dict[str, object]] = None,
                 char: str = "") -> None:
        self.code = code
        self.template = template
        self.params: Dict[str, object] = dict(params or {})
        self.char = char
        self.message = template.format(**self.params)
        super().__init__(self.message)


def _display(ch: str) -> str:
    """A printable stand-in for the offending character (``\\t``, ``\\n``, ...)."""
    if ch.isprintable():
        return ch
    return repr(ch)[1:-1]


def validate_character_name(name: str) -> str:
    """Return the normalized name, or raise :class:`CharacterNameError`.

    Normalization is NFC composition plus stripping surrounding whitespace —
    nothing else. The returned string is what the caller must store.
    """
    raw = "" if name is None else str(name)
    normalized = unicodedata.normalize("NFC", raw).strip()

    if not normalized:
        raise CharacterNameError("empty", "Character name must not be empty.")

    if len(normalized) > MAX_NAME_LENGTH:
        raise CharacterNameError(
            "too_long",
            "Character name must be at most {max} characters (it has {length}).",
            {"max": MAX_NAME_LENGTH, "length": len(normalized)})

    for ch in normalized:
        if ch.isalpha() or ch.isdigit() or ch == " " or ch in ALLOWED_PUNCTUATION:
            continue
        raise CharacterNameError(
            "forbidden_char",
            'Character name must not contain "{char}".',
            {"char": _display(ch)}, char=ch)

    if normalized[0] in " ." or normalized[-1] in " .":
        raise CharacterNameError(
            "edge",
            "Character name must not start or end with a space or a period.")

    if normalized[0] == "_":
        raise CharacterNameError(
            "edge",
            "Character name must not start with an underscore "
            "(reserved for internal system characters).")

    if "  " in normalized:
        raise CharacterNameError(
            "double_space",
            "Character name must not contain two spaces in a row.")

    if ".." in normalized:
        raise CharacterNameError(
            "double_dot", 'Character name must not contain "..".')

    if not any(ch.isalpha() or ch.isdigit() for ch in normalized):
        raise CharacterNameError(
            "no_alnum",
            "Character name must contain at least one letter or digit.")

    if normalized.casefold() in _RESERVED_ALL:
        raise CharacterNameError(
            "reserved",
            '"{name}" is a reserved name and cannot be used for a character.',
            {"name": normalized})

    return normalized


def character_name_problem(name: str) -> Optional[CharacterNameError]:
    """Same rule as :func:`validate_character_name`, without raising.

    Returns the error for callers that report rather than abort (the model
    layer's last line of defence, the NPC field check).
    """
    try:
        validate_character_name(name)
    except CharacterNameError as err:
        return err
    return None


def localized_message(err: CharacterNameError, lang: str = "") -> str:
    """The error text in ``lang`` (English source string + ``t()``).

    Imported lazily so this module stays dependency-free at import time.
    """
    from app.core.i18n import t
    return t(err.template, lang).format(**err.params)
