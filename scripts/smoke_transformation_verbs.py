#!/usr/bin/env python3
"""Smoke: the transformation verbs, the avatar's phrases and the secrecy line
(``plugins/transformation/skill.py``, ``intercept.py``, ``prompt_lines.py``).

Usage:  ./.venv/bin/python scripts/smoke_transformation_verbs.py

Throwaway storage + instance (``STORAGE_DIR``/``INSTANCE_DIR`` point at temp
dirs, ``paths.init`` runs BEFORE any world-DB module is imported). No server,
no LLM, no real world. The embedding is stubbed to "no model" so the
transform activity resolves through the catalog default; the package is
loaded the way the server loads it (``packages.enabled = "transformation"``,
``discover_packages()``), the verbs through the skill manager.

THE SPEC (``docs/superpowers/specs/2026-11-05-linked-characters-design.md`` →
"Transformation package", "Prompts", Goals 2 and 6): transform/revert are a
body swap — for NPCs through the verbs, for the player through the avatar
phrase (the leader says the activation phrase, the BODY says the revert
phrase). Knowers: per (body, observer) "<body> is secretly <leader>.", a
record secret of the mind (stored at the leader, ``body`` = the body) whose
known_by list holds the knowers; the reveal verb adds one. The secrecy text
("nobody may learn that you are <leader>, except …") is the package's own
scene-state line for the present body.

FIXTURE
    Location "Inn", room "taproom": Tilda (leader, carries "amulet"), Kim,
    Obs, Ava (leader, carries "ring"; the ACTIVE character of user "play").
    Glut = create_linked(Tilda), Star = create_linked(Ava) (both dormant).
    Definition "glut": Tilda -> Glut, item amulet, no phrases, max 0, cooldown 0.
    Definition "star": Ava -> Star, item ring, activation_phrase
    "by the moonlight", revert_phrase "Moon, rest", max 0, cooldown 0.
    Kim knows that Glut is Tilda (knowers.add). Game clock pinned (factor 0).

THE RULES, and what follows BY HAND
[A] Visibility: transform visible for Tilda and Ava (they lead a definition
    and carry its item), hidden for Kim, Obs and Glut; reveal_identity
    likewise visible for Tilda and Ava; revert visible for nobody (no body is
    present). The thought tool round for Tilda offers Transform, not Revert;
    revert is the clearing verb of is_transformed (unset -> inactive).
[B] execute transform '{"agent_name":"Tilda"}' -> no "Error"; Tilda dormant,
    Glut present in the taproom; flag is_transformed on Glut. Revert visible
    for Glut and offered in Glut's round; transform hidden for Glut; revert
    hidden for Tilda.
[C] Secrecy lines while Glut stands in the taproom (present: Kim, Obs, Ava):
    - Glut, chat event (character.prompt_context): one block
      "You are Glut, and secretly Tilda. Nobody may learn that you are Tilda,
      except Kim. Ava and Obs do not know — never reveal it in front of them."
    - Kim: "Glut here is secretly Tilda. Ava and Obs do not know — do not call
      Glut "Tilda" in front of them."
    - Obs: no block naming Tilda. Thought event for Glut: one section
      "=== Secret identity ===\\n- <the Glut line>" (the render trims the end).
    - The knower secret: one record secret of Tilda's mind with source_ref
      "transformation:Glut", content "Glut is secretly Tilda.", body "Glut",
      known_by ["Kim"]; Kim's known-about-others block contains
      "About Glut: Glut is secretly Tilda.".
    - reveal_identity for Glut: menu = present non-knowers sorted
      ["Ava", "Obs"]; state line "Glut is secretly Tilda. Already in on it:
      Kim. Not in on it: Ava, Obs."; transform has no menu for Tilda (one body).
[D] Avatar phrases (say_intercept, through play._run_say_intercepts):
    - Ava says "By the  Moonlight!" -> normalized "by the moonlight" contains
      the activation phrase -> consumed {"kind": "transformation", "ok": True,
      "reason": "", "body": "Star", "error": ""}; Ava dormant, Star present;
      user play's active character is now Star. Obs and Kim perceive nothing
      containing "moonlight".
    - Star says "What a moonlight night" -> None (not a phrase of hers).
    - Obs says "by the moonlight" -> None (Obs leads nothing).
    - Star says "by the moonlight" -> consumed, ok False, reason
      "already_transformed"; the phrase line + a storyteller hint reach Star
      only (+2 rows for Star, 0 for the others).
    - Star says "Moon... rest." -> "moon rest" == the revert phrase ->
      consumed, ok True, body "Star"; Ava present again, Star dormant, user
      play controls Ava.
[E] reveal_identity by Glut (still present): target "obs" -> no "Error";
    knowers.knows("Obs", "Glut") True; the line "Glut reveals to Obs: Glut is
    Tilda." reaches exactly {Glut, Obs}; again -> "Error"; "Nobody" -> "Error".
[F] revert verb by Glut -> no "Error"; Tilda present, Glut dormant; revert
    not visible for Glut any more; a second revert -> "Error".
[G] Secrecy while the LEADER stands in the world (after [F]: Tilda present in
    the taproom with Kim, Obs, Ava; Kim and Obs know Glut; nobody knows Star):
    - Tilda: "You are Tilda, and secretly also Glut. Nobody may learn that you
      are Glut, except Kim and Obs. Ava does not know — never reveal it in
      front of them."
    - Kim (and Obs alike): 'Tilda here is secretly Glut. Ava does not know —
      do not call Tilda "Glut" in front of them.'
    - Ava (leads Star, nobody in on it): "You are Ava, and secretly also Star.
      Nobody may learn that you are Star. Kim, Obs and Tilda do not know —
      never reveal it in front of them."; Ava gets no line naming Glut.
    - Thought event for Tilda: "=== Secret identity ===\n- <the Tilda line>".
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="transformation-verbs-smoke-"))
STORAGE = ROOT / "world"
STORAGE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")
(STORAGE / "config.json").write_text(json.dumps({
    "packages": {"enabled": "transformation"},
}), encoding="utf-8")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(ROOT / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import embedding  # noqa: E402
embedding.embed = lambda text: None   # no model: the catalog default answers

from app.core import linked_characters as lc  # noqa: E402
from app.core import users  # noqa: E402
from app.core.db import get_connection  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models import inventory, secrets  # noqa: E402
from app.models import character as ch  # noqa: E402
from app.models.world import _load_world_data, _save_world_data, add_location  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


set_game_factor(0.0)
set_game_time(GameTime.parse("Y0002-D100T12:00:00"))

INN = add_location("Inn", "A stone house.")["id"]
_data = _load_world_data()
for _loc in _data.get("locations", []):
    if _loc.get("id") == INN:
        _loc["rooms"] = [{"id": "taproom", "name": "Taproom", "description": "Benches."}]
        _loc["entry_room"] = "taproom"
_save_world_data(_data)

for _name in ("Tilda", "Kim", "Obs", "Ava"):
    assert ch.save_character_profile(_name, {"character_name": _name,
                                             "template": "human-roleplay"},
                                     create_new=True), _name
    with keyed_lock("character_profile", _name):
        _p = ch.get_character_profile(_name)
        _p["current_location"] = INN
        _p["current_room"] = "taproom"
        assert ch.save_character_profile(_name, _p)
PLAY = users.create_user("play", "play-password-1", allowed_characters=["Ava"])
users.update_user(PLAY, settings={"active_character": "Ava"})
assert lc.create_linked("Tilda", "Glut")["ok"]
assert lc.create_linked("Ava", "Star")["ok"]

inventory.add_item("Amulet", item_id="amulet")
inventory.add_item("Ring", item_id="ring")
assert inventory.add_to_inventory("Tilda", "amulet")
assert inventory.add_to_inventory("Ava", "ring")

from plugins.transformation import store as tstore  # noqa: E402
tstore.ensure_schema()
tstore.create_definition({"leader": "Tilda", "body": "Glut", "item_id": "amulet",
                          "max_duration_minutes": 0, "cooldown_minutes": 0})
tstore.create_definition({"leader": "Ava", "body": "Star", "item_id": "ring",
                          "activation_phrase": "by the moonlight", "revert_phrase": "Moon, rest",
                          "max_duration_minutes": 0, "cooldown_minutes": 0})

from app.plugins import loader, registry  # noqa: E402
loader.discover_packages()
check("package loaded", "transformation" in {p.id for p in registry.packages()}, True)

from app.core import hooks, perception  # noqa: E402
from app.core.dependencies import get_skill_manager  # noqa: E402
from app.core.streaming import turn_tools  # noqa: E402
from app.skills.base import TurnFacts  # noqa: E402
from plugins.transformation import knowers  # noqa: E402

manager = get_skill_manager()
transform = manager.get_skill("transform")
revert = manager.get_skill("revert")
reveal = manager.get_skill("reveal_identity")
check("three verbs loaded", [s is not None for s in (transform, revert, reveal)],
      [True, True, True])
check("Kim made a knower of Glut", knowers.add("Kim", "Glut"), True)


def offered(name):
    tools = manager.get_agent_tools(name, check_limits=False, turn="thought")
    present = tuple(perception.addressable_for(name))
    got, hidden = turn_tools(tools, TurnFacts(name, "thought", present), rp_first=False)
    return {getattr(t, "name", t) for t in got}, hidden


def rows_containing(perceiver, needle):
    conn = get_connection()
    return [r[0] for r in conn.execute(
        "SELECT p.content FROM perceptions p JOIN utterances u ON u.id = p.utterance_id "
        "WHERE p.perceiver=?", (perceiver,))
        if needle.casefold() in (r[0] or "").casefold()]


def line_rows(content):
    conn = get_connection()
    ids = [r[0] for r in conn.execute("SELECT id FROM utterances WHERE content=?", (content,))]
    out = set()
    for uid in ids:
        out.update(r[0] for r in conn.execute(
            "SELECT perceiver FROM perceptions WHERE utterance_id=?", (uid,)))
    return ids, out


def is_error(text):
    return str(text).startswith("Error")


def active_of(user_id):
    return (users.get_user_by_id(user_id).get("settings") or {}).get("active_character")


# ── [A] visibility ──────────────────────────────────────────────────────────
print("[A] visibility")
for _name, _vis in (("Tilda", True), ("Ava", True), ("Kim", False), ("Obs", False),
                    ("Glut", False)):
    check(f"transform visible for {_name}", transform.visible_for(_name), _vis)
for _name, _vis in (("Tilda", True), ("Ava", True), ("Kim", False), ("Obs", False)):
    check(f"reveal_identity visible for {_name}", reveal.visible_for(_name), _vis)
for _name in ("Tilda", "Glut", "Ava", "Star", "Kim"):
    check(f"revert hidden for {_name}", revert.visible_for(_name), False)
_got, _hidden = offered("Tilda")
check("Transform offered", transform.name in _got, True)
check("Revert not offered", revert.name in _got, False)
from app.core.flag_lifecycle import inactive_clearing_tools  # noqa: E402
check("revert is the clearing verb of is_transformed",
      inactive_clearing_tools("Glut", [revert.name]), {revert.name})

# ── [B] transform verb ──────────────────────────────────────────────────────
print("[B] transform verb")
_res = transform.execute('{"agent_name":"Tilda"}')
check("transform result is no error", is_error(_res), False)
check("Tilda dormant", ch.get_character_status("Tilda"), "dormant")
check("Glut present", (ch.get_character_status("Glut"),
                       ch.get_character_profile("Glut").get("current_room")), ("", "taproom"))
check("flag on Glut", ch.get_character_profile("Glut").get("is_transformed"), True)
check("revert visible for Glut", revert.visible_for("Glut"), True)
check("revert hidden for Tilda", revert.visible_for("Tilda"), False)
check("transform hidden for Glut", transform.visible_for("Glut"), False)
_got, _hidden = offered("Glut")
check("Revert offered to Glut", revert.name in _got, True)
check("flag set -> revert's state active", inactive_clearing_tools("Glut", [revert.name]), set())

# ── [C] secrecy lines + the knower secret ───────────────────────────────────
print("[C] secrecy lines")
GLUT_LINE = ("You are Glut, and secretly Tilda. Nobody may learn that you are Tilda, except "
             "Kim. Ava and Obs do not know — never reveal it in front of them.")
KIM_LINE = ('Glut here is secretly Tilda. Ava and Obs do not know — do not call Glut '
            '"Tilda" in front of them.')
for _who, _want in (("Glut", [GLUT_LINE]), ("Kim", [KIM_LINE]), ("Obs", [])):
    _blocks = []
    hooks.emit("character.prompt_context", character_name=_who, mode="chat", blocks=_blocks)
    check(f"chat event for {_who}", [b for b in _blocks if "Tilda" in str(b)], _want)
_sections = []
hooks.emit("character.thought_context", character_name="Glut", blocks=_sections)
check("thought event for Glut", [s for s in _sections if "Tilda" in str(s)],
      ["=== Secret identity ===\n- " + GLUT_LINE])
_sec = [s for s in secrets.list_secrets("Tilda") if s.get("source_ref") == "transformation:Glut"]
check("one knower secret at the mind", len(_sec), 1)
check("secret content/body/knowers",
      (_sec[0].get("content"), _sec[0].get("body"), _sec[0].get("known_by")) if _sec else None,
      ("Glut is secretly Tilda.", "Glut", ["Kim"]))
check("Kim's known-about block", "About Glut: Glut is secretly Tilda."
      in secrets.known_about_others_block("Kim"), True)
check("reveal menu for Glut", reveal.decision_menu("Glut"), ["Ava", "Obs"])
check("reveal state line for Glut", reveal.tool_decision_context("Glut"),
      "Glut is secretly Tilda. Already in on it: Kim. Not in on it: Ava, Obs.")
check("transform menu with one body", transform.decision_menu("Tilda"), [])

# ── [D] avatar phrases ──────────────────────────────────────────────────────
print("[D] avatar phrases")
from app.routes import play  # noqa: E402


def say(avatar, content):
    return play._run_say_intercepts(avatar=avatar, content=content, volume="normal",
                                    addressees=[], location_id=INN, room_id="taproom")


check("activation phrase consumed", say("Ava", "By the  Moonlight!"),
      {"kind": "transformation", "ok": True, "reason": "", "body": "Star", "error": ""})
check("Ava dormant, Star present", (ch.get_character_status("Ava"),
                                    ch.get_character_status("Star")), ("dormant", ""))
check("play controls Star", active_of(PLAY), "Star")
check("Obs heard nothing of the phrase", rows_containing("Obs", "moonlight"), [])
check("Kim heard nothing of the phrase", rows_containing("Kim", "moonlight"), [])
check("not a phrase -> not consumed", say("Star", "What a moonlight night"), None)
check("Obs leads nothing -> not consumed", say("Obs", "by the moonlight"), None)
_before = {n: len(rows_containing(n, "")) for n in ("Star", "Obs", "Kim", "Glut")}
_again = say("Star", "by the moonlight")
check("phrase again consumed, refused", (_again or {}).get("ok"), False)
check("refusal reason", (_again or {}).get("reason"), "already_transformed")
_after = {n: len(rows_containing(n, "")) for n in ("Star", "Obs", "Kim", "Glut")}
check("refusal hint (+ phrase line) for Star only",
      {n: _after[n] - _before[n] for n in _after}, {"Star": 2, "Obs": 0, "Kim": 0, "Glut": 0})
check("revert phrase consumed", say("Star", "Moon... rest."),
      {"kind": "transformation", "ok": True, "reason": "", "body": "Star", "error": ""})
check("Ava present, Star dormant", (ch.get_character_status("Ava"),
                                    ch.get_character_status("Star")), ("", "dormant"))
check("play controls Ava again", active_of(PLAY), "Ava")

# ── [E] reveal_identity ─────────────────────────────────────────────────────
print("[E] reveal_identity")
_res = reveal.execute('{"agent_name":"Glut","target":"obs"}')
check("reveal to Obs is no error", is_error(_res), False)
check("Obs knows now", knowers.knows("Obs", "Glut"), True)
_ids, _who = line_rows("Glut reveals to Obs: Glut is Tilda.")
check("one reveal line", len(_ids), 1)
check("reveal line reaches Glut + Obs only", _who, {"Glut", "Obs"})
check("reveal again -> error", is_error(reveal.execute('{"agent_name":"Glut","target":"Obs"}')),
      True)
check("absent target -> error",
      is_error(reveal.execute('{"agent_name":"Glut","target":"Nobody"}')), True)

# ── [F] revert verb ─────────────────────────────────────────────────────────
print("[F] revert verb")
_res = revert.execute('{"agent_name":"Glut"}')
check("revert result is no error", is_error(_res), False)
check("Tilda present, Glut dormant", (ch.get_character_status("Tilda"),
                                      ch.get_character_status("Glut")), ("", "dormant"))
check("revert hidden for Glut again", revert.visible_for("Glut"), False)
check("revert of nobody -> error", is_error(revert.execute('{"agent_name":"Glut"}')), True)

# ── [G] secrecy while the leader stands ─────────────────────────────────────
print("[G] leader secrecy")
TILDA_LINE = ("You are Tilda, and secretly also Glut. Nobody may learn that you are Glut, "
              "except Kim and Obs. Ava does not know — never reveal it in front of them.")
KNOWER_LINE = ('Tilda here is secretly Glut. Ava does not know — do not call Tilda "Glut" '
               'in front of them.')
AVA_LINE = ("You are Ava, and secretly also Star. Nobody may learn that you are Star. "
            "Kim, Obs and Tilda do not know — never reveal it in front of them.")
for _who, _want in (("Tilda", [TILDA_LINE]), ("Kim", [KNOWER_LINE]), ("Obs", [KNOWER_LINE]),
                    ("Ava", [])):
    _blocks = []
    hooks.emit("character.prompt_context", character_name=_who, mode="chat", blocks=_blocks)
    check(f"leader-present line for {_who}", [b for b in _blocks if "Glut" in str(b)], _want)
_blocks = []
hooks.emit("character.prompt_context", character_name="Ava", mode="chat", blocks=_blocks)
check("Ava's own leader line", [b for b in _blocks if "Star" in str(b)], [AVA_LINE])
_sections = []
hooks.emit("character.thought_context", character_name="Tilda", blocks=_sections)
check("thought event for Tilda", [s for s in _sections if "Glut" in str(s)],
      ["=== Secret identity ===\n- " + TILDA_LINE])

print()
print(f"{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAIL:", ", ".join(FAILURES))
    sys.exit(1)
print("PASS")
