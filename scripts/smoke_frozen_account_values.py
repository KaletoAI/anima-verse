#!/usr/bin/env python3
"""Smoke: the two frozen account values are gone — the AVATAR is the player.

Usage:  ./.venv/bin/python scripts/smoke_frozen_account_values.py

No server, no network, no real world: a throwaway storage root and three
characters created by hand.

THE RULE
---------------------------------------------------------------------------
The old web UI had settings for the human player; those routes are gone, and
with them the only writers of ``account.user_name`` (the player's display
name) and of the account's ``chat_partner`` (the one character the player was
chatting with 1:1). The readers stayed, so an existing world kept acting on a
value frozen years ago and a new world on an empty one.

Today the player is the AVATAR (``account.get_active_character``) and a
conversation is the ROOM (the perception stream), not a fixed pair. So:

  * no avatar  ->  there is no person to draw, and no name that "is" the
                   player;
  * "we are talking"  ->  a fact of the TURN (who is being answered) or of the
                   PLACE (who is within earshot), never a stored pair.

HAND-DERIVED EXPECTATIONS
---------------------------------------------------------------------------
World: ``Demo NPC`` (male, "a tall innkeeper with grey hair"), ``Demo Avatar``
(female, "a young traveller in a green coat"), ``Demo Guest`` (a third NPC).
The account row carries the frozen junk an existing world would still hold:
``user_name`` = "stalelogin", ``gender`` = "male", ``user_appearance`` =
"STALE ACCOUNT APPEARANCE", ``profile_image`` = "stale.png".

[1] NO AVATAR (``active_character`` empty). Nothing about the player exists:
      get_active_character()      == ""
      get_user_appearance()       == ""     (not the stale account text)
      get_user_gender()           == ""     (not "male")
      get_user_profile_image()    == ""     (not "stale.png")
      PromptBuilder._avatar_name()          == ""
      PromptBuilder._is_avatar_name("stalelogin") is False
    and the three person paths of the image prompt produce NO user person for
    that name:
      detect_persons("stalelogin steht am Tresen")
        -> the AGENT alone. Not because the text names it, but through the
           auto-detect fallback "nobody recognised -> the agent is the
           default" (prompt_builder._auto_detect step 4) — which is the proof
           that the stale login name recognised NOBODY.
      detect_persons(..., character_names=["stalelogin"]) -> no person at all
        (that path has no agent fallback; a name that is neither the avatar
        nor a character has no appearance)
      _create_user_person()                               -> None
    The agent's own person is unaffected — "Demo NPC" in the text still yields
    exactly one person, is_agent=True.

[2] AVATAR ACTIVE ("Demo Avatar"), the SAME frozen junk still in the row:
      _avatar_name()                        == "Demo Avatar"
      _is_avatar_name("Demo Avatar") is True
      _is_avatar_name("stalelogin")  is False   (the login name is not a person)
      get_user_appearance() == "a young traveller in a green coat"
      get_user_gender()     == "female"          (the AVATAR's gender, not the
                                                  account's frozen "male")
    and the person list of an image prompt names the avatar with its own
    appearance and ``is_user=True``:
      detect_persons("Demo Avatar steht am Tresen")
        -> [Person(name="Demo Avatar",
                   appearance="a young traveller in a green coat",
                   gender="female", is_user=True)]
      detect_persons("egal", character_names=["Demo Avatar"])   -> the same
      detect_persons("egal", explicit_appearances=[{"name": "Demo Avatar",
                     "appearance": "X"}]) -> is_user, appearance "X" (the
                     caller's text wins), gender "female"
      _create_user_person() -> the same person
    "Avatar nicht auto-ergaenzt" is untouched: a text that names NEITHER the
    avatar nor a user pronoun ("Demo NPC poliert Glaeser") yields exactly one
    person and it is the agent — the avatar is not added because it exists.

[3] The account has no chat partner any more:
      ``app.models.account`` has no attribute ``get_chat_partner``
      ``app.routes.chat`` has no attribute ``_get_chat_partner``
      ``app.models.account`` has no attribute ``get_user_name``
    The data is NOT deleted: the account row still carries its old keys, so
    ``get_user_profile()["user_name"]`` still reads "stalelogin" — nothing
    acts on it any more.

[4] TalkTo's "do not talk to the one you are already answering" comes from the
    TURN. ``initiator`` is what the tool executor puts into the call
    (chat_engine.build_chat_context: the speaker of the triggering utterance,
    the avatar's name when the player spoke). Demo NPC, Demo Avatar and Demo
    Guest all stand in the same room of the same location, so the earshot gate
    passes for everyone and only the initiator rule can refuse:
      initiator="Demo Avatar", target="Demo Avatar" -> refused, the answer
        contains "the one you are answering right now"
      initiator="Demo Avatar", target="Demo Guest"  -> NOT refused (a third
        character in earshot is exactly what TalkTo is for)
      NO initiator at all (an autonomous thought turn), target="Demo Avatar"
        -> NOT refused: there the verb is the only way spoken words reach
        anyone, the avatar included (the room-entry greeting runs this way)
    A stale stored partner cannot influence any of the three — there is none.

[5] The chat turn runs without a stored partner: ``build_chat_context`` resolves
    ``user_display_name`` from the avatar alone.
      avatar "Demo Avatar" -> "Demo Avatar"
      no avatar            -> "user" (the sentinel the extraction filters)
    Checked on the pure helper the value comes from,
    ``account.get_player_identity``, plus an AST check that
    ``chat_engine.build_chat_context`` names no chat partner at all.

FAILS BEFORE / PASSES AFTER
---------------------------------------------------------------------------
Section [0] pins the pre-fix revision 6f4fc14e and asserts the removed
expressions are still in ITS blobs — that is what made [1]-[5] fail there.
Measured against 6f4fc14e with exactly the world above and no avatar,
``_avatar_name()`` answered "stalelogin", ``_is_avatar_name("stalelogin")``
was True and ``detect_persons("stalelogin steht am Tresen")`` returned
``[('stalelogin', is_user=True, 'STALE ACCOUNT APPEARANCE')]`` — a person who
exists nowhere in the world, drawn into the picture. With the avatar active,
``_is_avatar_name("stalelogin")`` was True as well, folding the login name
onto the avatar.
"""
import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Storage + clip library FIRST: without a storage root every world access
# raises StorageNotInitialised — there is no default world any more, so
# nothing here can land in the tracked worlds/demo.
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="frozen-account-clips-")

from app.core import paths  # noqa: E402

paths.init(Path(tempfile.mkdtemp(prefix="frozen-account-storage-")))

from app.core import db  # noqa: E402

db.init_schema()

FAILURES = []
CHECKED = 0

PINNED = "6f4fc14e45bb339000429c0a04c90a41cd6e8fd2"


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_true(label, cond, detail=""):
    global CHECKED
    CHECKED += 1
    ok = bool(cond)
    print(f"  {'OK ' if ok else 'FAIL'} {label}" + (f": {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def persons(builder, *args, **kwargs):
    return [(p.name, p.appearance, p.gender, p.is_user, p.is_agent)
            for p in builder.detect_persons(*args, **kwargs)]


# --- [0] the pinned pre-fix revision ---------------------------------------
print("[0] pre-fix revision", PINNED[:8], "still carries the removed readers")
_old = {}
try:
    for rel in ("app/core/prompt_builder.py", "app/models/account.py",
                "app/core/chat_engine.py", "plugins/talk_to/skill.py"):
        _old[rel] = subprocess.run(
            ["git", "show", f"{PINNED}:{rel}"], cwd=REPO,
            capture_output=True, text=True, check=True).stdout
except Exception as exc:  # noqa: BLE001
    check_true(f"git show {PINNED[:8]} works", False, str(exc))
else:
    check_true("prompt_builder._avatar_name fell back to the login name",
               'get_user_profile().get("user_name", "")'
               in _old["app/core/prompt_builder.py"])
    check_true("account.get_chat_partner existed",
               "def get_chat_partner()" in _old["app/models/account.py"])
    check_true("account.get_user_name existed",
               "def get_user_name()" in _old["app/models/account.py"])
    check_true("chat_engine used get_chat_partner",
               "get_chat_partner()" in _old["app/core/chat_engine.py"])
    check_true("talk_to used get_chat_partner",
               "get_chat_partner" in _old["plugins/talk_to/skill.py"])

# --- the world -------------------------------------------------------------
from app.models.account import (  # noqa: E402
    get_active_character, get_player_identity, get_user_appearance,
    get_user_gender, get_user_profile, get_user_profile_image,
    save_user_profile)
from app.models.character import (  # noqa: E402
    save_character_config, save_character_current_location,
    save_character_current_room, save_character_profile)
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location)


def patch_location(location_id: str, **fields) -> None:
    """Merge top-level fields into a stored location (rooms, entry_room)."""
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            loc.update(fields)
    _save_world_data(data)


for name, gender, look in (("Demo NPC", "male", "a tall innkeeper with grey hair"),
                           ("Demo Avatar", "female", "a young traveller in a green coat"),
                           ("Demo Guest", "male", "a broad-shouldered carter")):
    save_character_profile(name, {"name": name, "character_appearance": look,
                                  "gender": gender, "template": "human-default"},
                           create_new=True)
    save_character_config(name, {"name": name})

INN = add_location("Demo Inn", "A stone house at the fork.")["id"]
patch_location(INN, rooms=[{"id": "taproom", "name": "Taproom",
                            "description": "Benches."}],
               entry_room="taproom")
for name in ("Demo NPC", "Demo Avatar", "Demo Guest"):
    save_character_current_location(name, INN)
    save_character_current_room(name, "taproom")


def set_frozen(active: str) -> None:
    """The junk an existing world still carries, plus the avatar selection."""
    prof = get_user_profile()
    prof["user_name"] = "stalelogin"
    prof["gender"] = "male"
    prof["user_appearance"] = "STALE ACCOUNT APPEARANCE"
    prof["profile_image"] = "stale.png"
    prof["active_character"] = active
    prof["current_character"] = active
    save_user_profile(prof)


from app.core.prompt_builder import PromptBuilder  # noqa: E402

AGENT_PERSON = ("Demo NPC", "a tall innkeeper with grey hair", "male",
                False, True)

# --- [1] no avatar ---------------------------------------------------------
print("[1] no avatar — a stale login name is nobody")
set_frozen("")
check("get_active_character()", get_active_character(), "")
check("get_user_appearance()", get_user_appearance(), "")
check("get_user_gender()", get_user_gender(), "")
check("get_user_profile_image()", get_user_profile_image(), "")

b = PromptBuilder("Demo NPC")
check("_avatar_name()", b._avatar_name(), "")
check("_is_avatar_name('stalelogin')", b._is_avatar_name("stalelogin"), False)
check("_create_user_person()", b._create_user_person(), None)
check("auto-detect 'stalelogin steht am Tresen'",
      persons(b, "stalelogin steht am Tresen"), [AGENT_PERSON])
check("by-name ['stalelogin']",
      persons(b, "egal", character_names=["stalelogin"]), [])
check("the agent itself is unaffected",
      persons(b, "Demo NPC poliert Glaeser"), [AGENT_PERSON])

# --- [2] avatar active -----------------------------------------------------
print("[2] avatar active — the avatar IS the player")
set_frozen("Demo Avatar")
check("get_active_character()", get_active_character(), "Demo Avatar")
check("get_user_appearance()", get_user_appearance(),
      "a young traveller in a green coat")
check("get_user_gender()", get_user_gender(), "female")

b = PromptBuilder("Demo NPC")
check("_avatar_name()", b._avatar_name(), "Demo Avatar")
check("_is_avatar_name('Demo Avatar')", b._is_avatar_name("Demo Avatar"), True)
check("_is_avatar_name('stalelogin')", b._is_avatar_name("stalelogin"), False)

AVATAR_PERSON = ("Demo Avatar", "a young traveller in a green coat",
                 "female", True, False)
check("auto-detect 'Demo Avatar steht am Tresen'",
      persons(b, "Demo Avatar steht am Tresen"), [AVATAR_PERSON])
check("by-name ['Demo Avatar']",
      persons(b, "egal", character_names=["Demo Avatar"]), [AVATAR_PERSON])
check("by-appearance [{'Demo Avatar': 'X'}]",
      persons(b, "egal", explicit_appearances=[{"name": "Demo Avatar",
                                                "appearance": "X"}]),
      [("Demo Avatar", "X", "female", True, False)])
_up = b._create_user_person()
check("_create_user_person()",
      (_up.name, _up.appearance, _up.gender, _up.is_user) if _up else None,
      ("Demo Avatar", "a young traveller in a green coat", "female", True))
check("the avatar is NOT auto-added when nothing names it",
      persons(b, "Demo NPC poliert Glaeser"), [AGENT_PERSON])

# --- [3] the readers are gone, the data is not -----------------------------
print("[3] the frozen readers are gone, the stored keys are not")
import app.models.account as _account  # noqa: E402
import app.routes.chat as _chat_routes  # noqa: E402

check_true("account.get_chat_partner removed",
           not hasattr(_account, "get_chat_partner"))
check_true("account.get_user_name removed",
           not hasattr(_account, "get_user_name"))
check_true("routes.chat._get_chat_partner removed",
           not hasattr(_chat_routes, "_get_chat_partner"))
check("the account row keeps its key",
      get_user_profile().get("user_name"), "stalelogin")

# --- [4] TalkTo takes the exclusion from the turn --------------------------
print("[4] TalkTo: the one you are answering comes from the turn")
import json  # noqa: E402

from app.plugins.loader import discover_packages, load_plugin  # noqa: E402

_pkg = next(p for p in discover_packages(force=True) if p.id == "talk_to")
_skill = dict(load_plugin(_pkg))["talk_to"]

REFUSED = "the one you are answering right now"


def talk(target, initiator=None):
    payload = {"agent_name": "Demo NPC", "user_id": "",
               "name": target, "message": "Hallo"}
    if initiator is not None:
        payload["initiator"] = initiator
    return _skill.execute(json.dumps(payload))


_r = talk("Demo Avatar", initiator="Demo Avatar")
check_true("answering the avatar -> TalkTo back at it is refused",
           REFUSED in _r, _r[:90])
_r = talk("Demo Guest", initiator="Demo Avatar")
check_true("a third character in earshot is NOT refused",
           REFUSED not in _r, _r[:90])
_r = talk("Demo Avatar")
check_true("an autonomous turn may TalkTo the avatar",
           REFUSED not in _r, _r[:90])

# --- [5] the chat turn's player name ---------------------------------------
print("[5] the chat turn names the player from the avatar alone")
set_frozen("Demo Avatar")
check("get_player_identity() with an avatar", get_player_identity("user"),
      "Demo Avatar")
set_frozen("")
check("get_player_identity() without one", get_player_identity("user"), "user")

_src = (REPO / "app/core/chat_engine.py").read_text()
_tree = ast.parse(_src)
_fn = next(n for n in ast.walk(_tree)
           if isinstance(n, ast.FunctionDef) and n.name == "build_chat_context")
_names = {n.id for n in ast.walk(_fn) if isinstance(n, ast.Name)} | \
         {n.attr for n in ast.walk(_fn) if isinstance(n, ast.Attribute)} | \
         {a.name for n in ast.walk(_fn) if isinstance(n, ast.ImportFrom)
          for a in n.names}
check_true("build_chat_context names no chat partner",
           "get_chat_partner" not in _names)

print()
print(f"{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    for f in FAILURES:
        print(f"  FAILED: {f}")
    sys.exit(1)
print("OK  the frozen account values are retired — the avatar is the player")
