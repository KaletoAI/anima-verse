#!/usr/bin/env python3
"""Smoke: ONE character-name rule, used by every path that CREATES a character.

Usage:
    ./.venv/bin/python scripts/smoke_character_name.py

Throwaway storage (tempfile + ``paths.init`` BEFORE any world-DB module is
imported), no server, no real world DB, no LLM. ``ANIMATION_CLIPS_DIR`` is
redirected before the app modules load.

WHY
---
"Character name" used to mean something different in every creator: the create
route checked "empty" plus the four JS nulls, the ZIP import checked "/", ".."
and a leading dot, World Dev and the NPC spawn checked nothing at all. A name
became a directory name, a DB key and a URL segment, so "a/b", "At-Location"
or a name with a newline in it were creatable and broke a different thing each
time. ``app/core/character_name.py`` is now the one rule; this check pins it,
including that it applies ONLY on creation.

THE RULE (as implemented, restated here so the table below is derivable)
    * allowed: Unicode letters (``str.isalpha`` after NFC composition), digits,
      space U+0020, ``-``, ``'``, ``’`` (U+2019), ``.``
    * everything else forbidden, incl. control characters and other whitespace
    * surrounding whitespace is stripped first; afterwards no leading/trailing
      space or period, no "  ", no ".."
    * 1..60 characters, at least one letter or digit
    * not reserved (case-insensitive): the account/system names, the JS nulls,
      the legacy "KI" placeholder, the /characters/ collection segments

EXPECTED, derived BY HAND from that rule (not from current output)
------------------------------------------------------------------

[1] ACCEPTED — input -> returned (normalized) name

  input (python source)                      | returned          | why
  -------------------------------------------+-------------------+----------------------------
  "Anna"                                     | "Anna"            | letters only
  "  Anna  "                                 | "Anna"            | surrounding space stripped
  "Jorg Grosse"  (o-umlaut, sharp s)         | same              | Unicode letters are letters
  "Rene"  written as R + e + U+0301 + ne     | NFC "René..."| decomposed -> composed, 1 char
  "O'Malley"                                 | "O'Malley"        | ASCII apostrophe
  "O’Malley"                            | unchanged         | typographic apostrophe kept
  "Dr. Vale"                                 | "Dr. Vale"        | interior period + space
  "Anne-Marie"                               | "Anne-Marie"      | hyphen
  "Agent 47"                                 | "Agent 47"        | digits
  "A" * 60                                   | same, len 60      | the limit itself is allowed
  "林小龍" (CJK)                 | unchanged         | isalpha() is script-agnostic

  Counting for the decomposed case: "R","e",U+0301,"n","e" is 5 code points;
  NFC composes e+U+0301 into one, so the result is "René" (4 characters)
  and it is NOT the 5-code-point string that went in.

[2] REJECTED — input -> CharacterNameError.code

  ""                          -> empty          (and "   " -> empty after strip)
  "A"*61                      -> too_long       (61 > 60)
  "a/b"                       -> forbidden_char (char "/")
  "a\\\\b" "a<b" "a>b" "a[b" "a]b" 'a"b' "a?b" "a#b" "a%b" "a:b" "a*b" "a|b"
                              -> forbidden_char (one per character class member)
  "Anna\\tLee", "Anna\\nLee"    -> forbidden_char (tab/newline are not spaces)
  "Anna\\x00Lee"               -> forbidden_char (control character)
  "Anna\\u00a0Lee"             -> forbidden_char (NBSP is other whitespace)
  "Anna_Lee"                  -> accepted       (an inner underscore is ordinary)
  "_Anna"                     -> edge           (a LEADING underscore marks an
                                                internal system character)
  ".Anna"                     -> edge           (leading period after stripping)
  "Anna."                     -> edge           (trailing period)
  "Anna  Lee"                 -> double_space   (two spaces in a row)
  "Anna..Lee"                 -> double_dot     ("..")
  "-'-"                       -> no_alnum       (punctuation only, no edge/dot hit)
  "Undefined","NULL","None","NaN","User","Admin","System","Default","Player"
                              -> reserved       (case-insensitive)
  "Ki"                        -> reserved       (the legacy "KI" placeholder)
  "At-Location","List","Create","Import"
                              -> reserved       (route collection segments)

  Order matters where two rules could fire: ".Anna." is checked for forbidden
  characters first (none), then edges -> ``edge``; "-'-" reaches ``no_alnum``
  because it neither starts/ends with space or period nor contains "..".

[3] ONE SOURCE OF TRUTH for the reserved names
    ``app.models.character._RESERVED_NAMES`` IS
    ``app.core.character_name.RESERVED_NAMES`` (same object), and
    ``app.core.auth_dependency._RESERVED_CHARACTER_NAMES`` IS
    ``app.core.character_name.RESERVED_ROUTE_SEGMENTS``. Identity, not
    equality — a copy would drift.

[4] THE MODEL LAYER IS THE LAST LINE OF DEFENCE
    save_character_profile("bad/name", {...}, create_new=True) -> False,
    no row in ``characters`` and NO directory under <storage>/characters/.
    save_character_profile("Mira Vale", {...}, create_new=True) -> True.

[5] EXISTING CHARACTERS ARE NOT TOUCHED
    A character whose name would be rejected today (created here by neutering
    the validator for exactly one call, which is how such a row got into an
    older world) can still be READ (get_character_profile returns its stored
    field) and SAVED with create_new=False -> True. Nothing renames it.

[6] THE ZIP IMPORT USES THE SAME RULE
    A v2 manifest naming "bad/name" makes import_character_from_zip raise
    ValueError whose text carries the validator's message ("must not contain").
    The route maps ValueError -> HTTP 400, so the message reaches the user.

[7] THE NPC FIELD CHECK REJECTS, IT DOES NOT SANITIZE
    validate_npc_fields({"character_name": "Bad/Name"}) yields a gap line
    starting with "character_name", and the dict still holds "Bad/Name" —
    the repair turn asks for a different name, nothing rewrites it.
"""
import os
import sys
import tempfile
import zipfile
import io
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="charname-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="charname-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core.character_name import (  # noqa: E402
    CharacterNameError, MAX_NAME_LENGTH, RESERVED_NAMES,
    RESERVED_ROUTE_SEGMENTS, character_name_problem, validate_character_name)

FAILURES = []
CHECKED = 0


def check(label: str, got, want) -> None:
    global CHECKED
    CHECKED += 1
    ok = got == want
    print(f"  {'[ok]' if ok else '[FAIL]'} {label}"
          + ("" if ok else f" — got {got!r}, want {want!r}"))
    if not ok:
        FAILURES.append(label)


# ---------------------------------------------------------------------------
print("\n[1] Accepted names")
# ---------------------------------------------------------------------------

DECOMPOSED = "Réne"          # R + e + COMBINING ACUTE + n + e
COMPOSED = "Réne"             # R + e-acute + n + e

ACCEPTED = [
    ("plain letters", "Anna", "Anna"),
    ("surrounding whitespace is stripped", "  Anna  ", "Anna"),
    ("umlauts and sharp s", "Jörg Große", "Jörg Große"),
    ("decomposed acute comes back NFC-composed", DECOMPOSED, COMPOSED),
    ("ASCII apostrophe", "O'Malley", "O'Malley"),
    ("typographic apostrophe is kept as written",
     "O’Malley", "O’Malley"),
    ("interior period", "Dr. Vale", "Dr. Vale"),
    ("hyphen", "Anne-Marie", "Anne-Marie"),
    ("inner underscore", "Anna_Lee", "Anna_Lee"),
    ("digits", "Agent 47", "Agent 47"),
    ("exactly 60 characters", "A" * 60, "A" * 60),
    ("CJK letters", "林小龍", "林小龍"),
]
for label, raw, want in ACCEPTED:
    try:
        check(label, validate_character_name(raw), want)
    except CharacterNameError as err:
        check(label, f"rejected({err.code})", want)

check("the decomposed input really was 5 code points", len(DECOMPOSED), 5)
check("and the returned name is 4", len(COMPOSED), 4)
check("MAX_NAME_LENGTH is 60", MAX_NAME_LENGTH, 60)


# ---------------------------------------------------------------------------
print("\n[2] Rejected names and their codes")
# ---------------------------------------------------------------------------

REJECTED = [
    ("empty string", "", "empty"),
    ("only whitespace", "   ", "empty"),
    ("61 characters", "A" * 61, "too_long"),
    ("slash", "a/b", "forbidden_char"),
    ("backslash", "a\\b", "forbidden_char"),
    ("less-than", "a<b", "forbidden_char"),
    ("greater-than", "a>b", "forbidden_char"),
    ("bracket open", "a[b", "forbidden_char"),
    ("bracket close", "a]b", "forbidden_char"),
    ("double quote", 'a"b', "forbidden_char"),
    ("question mark", "a?b", "forbidden_char"),
    ("hash", "a#b", "forbidden_char"),
    ("percent", "a%b", "forbidden_char"),
    ("colon", "a:b", "forbidden_char"),
    ("asterisk", "a*b", "forbidden_char"),
    ("pipe", "a|b", "forbidden_char"),
    ("leading underscore", "_Anna", "edge"),
    ("tab inside", "Anna\tLee", "forbidden_char"),
    ("newline inside", "Anna\nLee", "forbidden_char"),
    ("NUL control character", "Anna\x00Lee", "forbidden_char"),
    ("non-breaking space", "Anna Lee", "forbidden_char"),
    ("leading period", ".Anna", "edge"),
    ("trailing period", "Anna.", "edge"),
    ("two spaces in a row", "Anna  Lee", "double_space"),
    ("the sequence ..", "Anna..Lee", "double_dot"),
    ("punctuation only", "-'-", "no_alnum"),
]
for label, raw, want_code in REJECTED:
    err = character_name_problem(raw)
    check(label, err.code if err else "accepted", want_code)

RESERVED_MIXED = ["Undefined", "NULL", "None", "NaN", "User", "Admin",
                  "System", "Default", "Player", "Ki",
                  "At-Location", "List", "Create", "Import"]
for word in RESERVED_MIXED:
    err = character_name_problem(word)
    check(f"reserved in mixed case: {word!r}",
          err.code if err else "accepted", "reserved")

_slash = character_name_problem("a/b")
check("the error names the offending character", _slash.char, "/")
check("and says so in English", '"/"' in _slash.message, True)
_tab = character_name_problem("Anna\tLee")
check("an unprintable character is shown escaped", "\\t" in _tab.message, True)


# ---------------------------------------------------------------------------
print("\n[3] One source of truth for the reserved names")
# ---------------------------------------------------------------------------

from app.models import character as ch  # noqa: E402
from app.core import auth_dependency as authdep  # noqa: E402

check("app.models.character._RESERVED_NAMES IS RESERVED_NAMES",
      ch._RESERVED_NAMES is RESERVED_NAMES, True)
check("auth_dependency._RESERVED_CHARACTER_NAMES IS RESERVED_ROUTE_SEGMENTS",
      authdep._RESERVED_CHARACTER_NAMES is RESERVED_ROUTE_SEGMENTS, True)


# ---------------------------------------------------------------------------
print("\n[4] save_character_profile is the last line of defence")
# ---------------------------------------------------------------------------

BAD = "bad/name"
GOOD = "Mira Vale"

check("create_new with an invalid name returns False",
      ch.save_character_profile(BAD, {"character_name": BAD}, create_new=True),
      False)
_row = db.get_connection().execute(
    "SELECT 1 FROM characters WHERE name=?", (BAD,)).fetchone()
check("and writes no row", bool(_row), False)
check("and creates no directory",
      (STORAGE / "characters" / "bad").exists()
      or (STORAGE / "characters" / BAD).exists(), False)

check("a valid name is created",
      ch.save_character_profile(GOOD, {"character_name": GOOD,
                                       "character_personality": "Dry."},
                                create_new=True), True)
check("and its directory exists",
      (STORAGE / "characters" / GOOD).is_dir(), True)


# ---------------------------------------------------------------------------
print("\n[5] Existing characters are not touched")
# ---------------------------------------------------------------------------

LEGACY = "Old:Name"          # colon: creatable before the rule, not now
check("the legacy name would be rejected today",
      (character_name_problem(LEGACY) or None) is not None, True)

# How such a row got into an older world: the creator of the day did not
# validate. Neutralize the validator for exactly this one write.
_real = ch.character_name_problem
ch.character_name_problem = lambda _n: None
try:
    created = ch.save_character_profile(
        LEGACY, {"character_name": LEGACY,
                 "character_personality": "Been here forever."},
        create_new=True)
finally:
    ch.character_name_problem = _real
check("the legacy character exists", created, True)

check("it still loads",
      ch.get_character_profile(LEGACY).get("character_personality"),
      "Been here forever.")
check("and an ordinary save (create_new=False) still works",
      ch.save_character_profile(LEGACY, {"character_name": LEGACY,
                                         "character_personality": "Still here."}),
      True)
check("with the new value stored",
      ch.get_character_profile(LEGACY).get("character_personality"),
      "Still here.")


# ---------------------------------------------------------------------------
print("\n[6] The ZIP import uses the same rule")
# ---------------------------------------------------------------------------

from app.core.character_io import (MANIFEST_VERSION,  # noqa: E402
                                   import_character_from_zip)


def _zip_with_name(name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "version": MANIFEST_VERSION,
            "character_name": name,
            "db_tables": [],
            "files": [],
        }))
    return buf.getvalue()


_import_error = ""
try:
    import_character_from_zip(_zip_with_name("bad/name"))
except ValueError as e:
    _import_error = str(e)
except Exception as e:  # noqa: BLE001
    _import_error = f"WRONG EXCEPTION {type(e).__name__}: {e}"
check("a bad manifest name raises ValueError",
      _import_error.startswith("invalid character_name in manifest"), True)
check("carrying the validator's message",
      "must not contain" in _import_error, True)


# ---------------------------------------------------------------------------
print("\n[7] The NPC field check rejects instead of sanitizing")
# ---------------------------------------------------------------------------

from app.core.npc_ops import validate_npc_fields  # noqa: E402

_draft = {"character_name": "Bad/Name"}
_gaps = validate_npc_fields(_draft)
check("an invalid LLM name becomes a gap",
      any(g.startswith("character_name") and "must not contain" in g
          for g in _gaps), True)
check("and the draft keeps the name it proposed",
      _draft["character_name"], "Bad/Name")


# ---------------------------------------------------------------------------
print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("OK")
