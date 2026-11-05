#!/usr/bin/env python3
"""Smoke: end to end, nothing the system renders for an observer who is not in
on the secret names a transformed character by her real name or describes her
real appearance — and with the transformation package absent every surface
names her plainly again (the deletion test).

Usage:  ./.venv/bin/python scripts/smoke_transformation_leaks.py

Two runs, each in its own throwaway storage + instance (``STORAGE_DIR`` /
``INSTANCE_DIR`` point at temp dirs, ``paths.init`` runs BEFORE any world-DB
module is imported). No server, no LLM, no real world.

  * The main run loads the package the way the server does
    (``packages.enabled = "transformation"``, ``discover_packages()``).
  * The deletion half runs this same file again in a FRESH SUBPROCESS with
    ``--absent``: a new temp world, the same characters, items and lines, the
    package NOT enabled (``packages.enabled = ""``, no persona rows). The
    package also registers EVENT listeners (``character.prompt_context``,
    ``character.thought_context``, ``world_tick``) and ``hooks`` cannot
    unregister those, so dropping its providers in-process would not model a
    deleted package — a process that never loaded it does.

FIXTURE (both runs)
    Location "Inn", room "taproom" (entry). Cara (bearer of "amulet",
    appearance "freckled redhead with a crooked smile"), Kim, Obs, all in the
    taproom. Obs is the avatar (``account.set_active_character``; no users →
    the account profile is the avatar source of ``get_all_avatars``).
    Main run only: persona p1 = item amulet, alias "Moonveil", description
    "A figure in moonlit silver.", no suit, no condition, max 0, cooldown 0;
    ``engine.tick()`` seeds the bearer's secret, Kim becomes a knower of
    Cara/p1, Cara is transformed through ``engine.transform``.
    Then, identically in both runs (written through the identity-aware core
    paths, so each run stores what that run's view dictates):
      - ``record_interaction("Obs", "Cara", "talkto", strength_delta=3)``
      - ``add_memory("Obs", "<key> smiled at me.", related_character=<key>)``
        with <key> = ``identity_key("Cara")``
      - room lines (``perception.record_utterance``): Cara → [Obs] "Good
        evening."; Kim → [Cara] "Welcome back."; Storyteller "Cara sets a cup
        down." (anchor Cara)
      - pairwise in-person chat in Obs's history (``chat.save_message``),
        partner Cara, role user, speaker Cara: "Silver greetings."

THE RULES and what follows BY HAND
    Main run: shown_name(Obs, Cara) = "Moonveil" (Obs knows nothing),
    shown_name(Kim, Cara) = "Moonveil (Cara)" (knower), identity_key(Cara) =
    "Moonveil", masked_description(Obs, Cara) = "A figure in moonlit
    silver.". So the relationship row is (Obs, Moonveil), the memory is
    "Moonveil smiled at me." about "Moonveil", the pairwise line is stamped
    {Cara: Moonveil}, Obs's perception rows carry speaker_shown /
    addressees_shown "Moonveil" and the storyteller line reads "Moonveil
    sets a cup down." for Obs.
    Absent run: no provider → every shown name / key is the real name, so the
    row is (Obs, Cara), the memory "Cara smiled at me." about "Cara", rows
    and lines unchanged.

    SURFACES rendered for observer Obs (text = the whole rendered string):
      chat 1:1      ``_build_chat_prompt("Obs", partner_override="Cara")``,
                    system + moment
      chat room     the same with present [Cara, Kim, Obs], addressed_to
                    ["Obs"], incoming "Hello there."
      thought       ``build_thought_context("Obs")`` rendered through
                    chat/agent_thought.md, chat/agent_thought_in_chat.md and
                    chat/thought_presence.md
      tool step     ``build_tool_step_prompt("Obs", mode="thought", …)`` and
                    mode "respond" with partner Cara, system + user
      npc_action    ``npc_actions.prompt_vars("Obs")`` rendered through
                    ``render_task("npc_action")``. Its partner list offers
                    temporary NPCs only; the filter
                    (``character.is_temporary_npc``) is patched to say yes
                    for Cara so the partner labels are exercised — the label
                    code itself is real. talk is allowed: conversation mode
                    "turns" (default) and an avatar (Obs) at the place.
      room stream   ``chat_engine._messages_from_room_stream`` over Obs's
                    room stream, contents joined
      relationships ``build_relationship_prompt_section("Obs")``
      memories      ``build_memory_prompt_section("Obs")``
      photo         ``scene_photo._room_transcript("Obs", Inn, taproom)``
      payloads      ``play.play_scene``, ``play.play_others`` and
                    ``build_worldmap_payload("Obs", show_all=True)`` — the
                    leak walk of smoke_identity_play_payload: string values
                    outside the technical keys name, character, inviter,
                    invitee, partner, leader, members, participants, present,
                    speaker, addressees and every ``*_url``; dict keys are
                    not values.
    Main run, every text surface: no "Cara", no "freckled" (the distinctive
    appearance token), and "Moonveil" present (the surface really names her —
    otherwise "no Cara" proves nothing). Payloads: no leak path; Cara's
    display_name is "Moonveil" in play_scene present_detail, play_others and
    the worldmap row.
    Main run, knower: ``_build_chat_prompt("Kim", …)`` room mode → the moment
    has "Moonveil (Cara)" (the present list "Others present: Moonveil (Cara),
    Obs.").
    Absent run (deletion test), every text surface: "Cara" present,
    "Moonveil" absent; "freckled" present in chat 1:1 (the partner block's
    real appearance — the positive control of the appearance check);
    payloads: Cara's display_name "Cara", no "Moonveil" anywhere in them,
    and the leak walk DOES find "Cara" (display_name is not a technical key —
    the positive control of the walk).
    Main run, chat room also has the present-details line "- Moonveil: A
    figure in moonlit silver." (the persona description stands in).
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ABSENT = "--absent" in sys.argv[1:]

ROOT = Path(tempfile.mkdtemp(prefix="transformation-leaks-smoke-"))
STORAGE = ROOT / "world"
STORAGE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")

PERSONAS = [
    {"id": "p1", "item_id": "amulet", "alias": "Moonveil",
     "description": "A figure in moonlit silver.",
     "max_duration_minutes": 0, "cooldown_minutes": 0},
]
_cfg = ({"packages": {"enabled": ""}} if ABSENT else
        {"packages": {"enabled": "transformation"}})
(STORAGE / "config.json").write_text(json.dumps(_cfg), encoding="utf-8")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(ROOT / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

if not ABSENT:   # the personas live in the package's own table (Characters → Skills panel)
    from plugins.transformation import store as tstore  # noqa: E402
    tstore.ensure_schema()
    for _p in PERSONAS:
        tstore.create_definition({k: v for k, v in _p.items() if k != "id"}, persona_id=_p["id"])

from app.core import embedding  # noqa: E402
embedding.embed = lambda text: None   # no model: the catalog default answers

from app.core.game_time import GameTime  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models import inventory  # noqa: E402
from app.models.character import get_character_profile, save_character_profile  # noqa: E402
from app.models.world import _load_world_data, _save_world_data, add_location  # noqa: E402

FAILURES = []
CHECKED = 0
APPEARANCE = "freckled redhead with a crooked smile"
TAG = "absent" if ABSENT else "main"


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} [{TAG}] {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(f"{TAG}: {label}")


def has(label, text, needle, expected=True):
    global CHECKED
    CHECKED += 1
    ok = (needle in text) == expected
    print(f"  {'OK ' if ok else 'FAIL'} [{TAG}] {label}: {needle!r} "
          f"{'in' if expected else 'not in'} text")
    if not ok:
        FAILURES.append(f"{TAG}: {label}")
        hit = text.find(needle)
        if hit >= 0:
            print("      …" + text[max(0, hit - 200):hit + 80].replace("\n", "\n      ") + "…")


TECH_KEYS = {"name", "character", "inviter", "invitee", "partner", "leader",
             "members", "participants", "present", "speaker", "addressees"}


def leaks(node, needle, path="$", under_tech=False):
    """Paths of string values containing ``needle`` outside technical keys
    and URL fields. Dict keys are not inspected (they are keys)."""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            tech = under_tech or k in TECH_KEYS or k.endswith("_url")
            out += leaks(v, needle, f"{path}.{k}", tech)
    elif isinstance(node, (list, tuple)):
        for i, v in enumerate(node):
            out += leaks(v, needle, f"{path}[{i}]", under_tech)
    elif isinstance(node, str) and needle in node and not under_tech:
        out.append(path)
    return out


def entry(rows, name):
    return next((r for r in rows or [] if r.get("name") == name), None) or {}


# ── fixture ─────────────────────────────────────────────────────────────────
set_game_factor(0.0)
set_game_time(GameTime.parse("Y0002-D100T12:00:00"))

INN = add_location("Inn", "A stone house.")["id"]
ROOM = "taproom"
_data = _load_world_data()
for _loc in _data.get("locations", []):
    if _loc.get("id") == INN:
        _loc["rooms"] = [{"id": ROOM, "name": "Taproom", "description": "Benches."}]
        _loc["entry_room"] = ROOM
_save_world_data(_data)

for _name in ("Cara", "Kim", "Obs"):
    assert save_character_profile(_name, {"character_name": _name, "template": "human-roleplay"},
                                  create_new=True), _name
    with keyed_lock("character_profile", _name):
        _p = get_character_profile(_name)
        _p["current_location"] = INN
        _p["current_room"] = ROOM
        if _name == "Cara":
            _p["character_appearance"] = APPEARANCE
        assert save_character_profile(_name, _p), _name

inventory.add_item("Amulet", item_id="amulet")
assert inventory.add_to_inventory("Cara", "amulet")

from app.models.account import set_active_character  # noqa: E402
set_active_character("Obs")

from app.plugins import loader, registry  # noqa: E402
loader.discover_packages()
check("package loaded", "transformation" in {p.id for p in registry.packages()}, not ABSENT)

from app.core import identity_view, perception, prompt_templates  # noqa: E402
from app.core import thought_context as tc  # noqa: E402

if not ABSENT:
    from plugins.transformation import engine, knowers  # noqa: E402
    engine.tick()
    check("Kim made a knower", knowers.add("Kim", "Cara", "p1"), True)
    check("transform ok", engine.transform("Cara", "p1", source="smoke"),
          {"ok": True, "reason": "", "alias": "Moonveil"})

KEY = identity_view.identity_key("Cara")
check("identity key", KEY, "Cara" if ABSENT else "Moonveil")
check("Obs's view", identity_view.shown_name("Obs", "Cara"), "Cara" if ABSENT else "Moonveil")

from app.models import chat  # noqa: E402
from app.models.memory import add_memory, build_memory_prompt_section  # noqa: E402
from app.models.relationship import build_relationship_prompt_section, record_interaction  # noqa: E402

record_interaction("Obs", "Cara", "talkto", strength_delta=3)
assert add_memory("Obs", f"{KEY} smiled at me.", memory_type="semantic", related_character=KEY)
for _speaker, _content, _to, _kw in (
        ("Cara", "Good evening.", ["Obs"], {}),
        ("Kim", "Welcome back.", ["Cara"], {}),
        (perception.STORYTELLER_SPEAKER, "Cara sets a cup down.", None, {"anchor": "Cara"})):
    assert perception.record_utterance(speaker=_speaker, content=_content, addressees=_to,
                                       location_id=INN, room_id=ROOM, **_kw), _content
assert chat.save_message({"content": "Silver greetings.", "role": "user", "speaker": "Cara",
                          "medium": "in_person", "timestamp": "2026-01-01T00:00:01+00:00"},
                         character_name="Obs", partner_name="Cara")

# ── render every surface for Obs ────────────────────────────────────────────
from app.core.chat_engine import _messages_from_room_stream  # noqa: E402
from app.core.npc_actions import prompt_vars as npc_prompt_vars  # noqa: E402
from app.core.scene_photo import _room_transcript  # noqa: E402
from app.core.streaming import tool_step_presence  # noqa: E402
from app.core.tool_step_prompt import build_tool_step_prompt  # noqa: E402
from app.core.world_ops import build_worldmap_payload  # noqa: E402
from app.models import perception_store  # noqa: E402
from app.routes import play  # noqa: E402
from app.routes.chat import _build_chat_prompt  # noqa: E402
from app.skills.base import TurnFacts  # noqa: E402

PRESENT = ["Cara", "Kim", "Obs"]


def chat_one_on_one(responder):
    p = _build_chat_prompt(responder, "", "", partner_override="Cara")
    return p.system + "\n" + p.moment


def chat_room(responder):
    p = _build_chat_prompt(responder, "", "", partner_override="Cara",
                           present_characters=PRESENT, addressed_to=[responder],
                           incoming_text="Hello there.")
    return p.system + "\n" + p.moment, p.moment


def thought(observer):
    ctx = tc.build_thought_context(observer)
    return "\n".join(prompt_templates.render(t, **ctx) for t in (
        "chat/agent_thought.md", "chat/agent_thought_in_chat.md", "chat/thought_presence.md"))


def tool_step(observer):
    present = tool_step_presence(observer)
    out = []
    for mode, partner, user_input in (("thought", "", ""), ("respond", "Cara", "Hello.")):
        p = build_tool_step_prompt(observer, mode=mode, rp_response="I look around.",
                                   user_input=user_input, tools=[],
                                   facts=TurnFacts(observer, mode, present, partner=partner),
                                   tool_format="tag")
        out.append(p.system + "\n" + p.user)
    return "\n".join(out)


def npc_action(observer):
    from app.models import character as character_model
    real = character_model.is_temporary_npc
    with patch.object(character_model, "is_temporary_npc",
                      lambda n: n == "Cara" or real(n)):
        variables = npc_prompt_vars(observer)
    check("npc_action: talk allowed", variables.get("talk_allowed"), True)
    check("npc_action: Cara offered as partner",
          [p.get("name") for p in variables.get("present") or []], ["Cara"])
    system, user = prompt_templates.render_task("npc_action", **variables)
    return system + "\n" + user


def room_stream(observer):
    rows = perception_store.get_character_room_stream(observer, INN, ROOM, 100)
    return "\n".join(m["content"] for m in _messages_from_room_stream(observer, rows))


TEXT = {
    "chat 1:1": chat_one_on_one("Obs"),
    "chat room": chat_room("Obs")[0],
    "thought": thought("Obs"),
    "tool step": tool_step("Obs"),
    "npc_action": npc_action("Obs"),
    "room stream": room_stream("Obs"),
    "relationships": build_relationship_prompt_section("Obs"),
    "memories": build_memory_prompt_section("Obs"),
    "photo transcript": _room_transcript("Obs", INN, ROOM),
}
PAYLOADS = {
    "play_scene": play.play_scene(user=None),
    "play_others": play.play_others(user=None),
    "worldmap": build_worldmap_payload("Obs", show_all=True),
}
check("avatar is Obs", PAYLOADS["play_scene"].get("avatar"), "Obs")
SHOWN = {
    "play_scene": entry(PAYLOADS["play_scene"].get("present_detail"), "Cara").get("display_name"),
    "play_others": entry(PAYLOADS["play_others"].get("characters"), "Cara").get("display_name"),
    "worldmap": entry(PAYLOADS["worldmap"].get("characters"), "Cara").get("display_name"),
}

if not ABSENT:
    print("[A] observer Obs, Cara transformed — nothing names or describes her")
    for _label, _text in TEXT.items():
        has(f"{_label}: no real name", _text, "Cara", False)
        has(f"{_label}: no real appearance", _text, "freckled", False)
        has(f"{_label}: names the alias", _text, "Moonveil")
    has("chat room: the persona description stands in", TEXT["chat room"],
        "- Moonveil: A figure in moonlit silver.")
    for _label, _payload in PAYLOADS.items():
        check(f"{_label}: leak walk (Cara)", leaks(_payload, "Cara"), [])
        check(f"{_label}: leak walk (freckled)", leaks(_payload, "freckled"), [])
        check(f"{_label}: Cara's display_name", SHOWN[_label], "Moonveil")

    print("[B] knower Kim")
    _full, _moment = chat_room("Kim")
    has("Kim's chat moment names both", _moment, "Moonveil (Cara)")
    has("Kim's present list", _moment, "Others present: Moonveil (Cara), Obs.")

    print("[C] deletion test — fresh subprocess, package not enabled")
    _env = {k: v for k, v in os.environ.items()
            if k not in ("STORAGE_DIR", "INSTANCE_DIR", "ANIMATION_CLIPS_DIR",
                         "ANIMATION_RIG_FILE")}
    _proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--absent"],
                           capture_output=True, text=True, env=_env, timeout=600)
    for _line in (_proc.stdout or "").splitlines():
        if _line.startswith("  ") or _line.startswith("[") or _line.startswith("PASS") \
                or _line.startswith("FAIL"):
            print("    " + _line)
    if _proc.returncode != 0:
        print("    --- subprocess stderr (tail) ---")
        for _line in (_proc.stderr or "").splitlines()[-30:]:
            print("    " + _line)
    check("absent-package run passes", _proc.returncode, 0)
else:
    print("[absent] no package — every surface names Cara again")
    for _label, _text in TEXT.items():
        has(f"{_label}: real name", _text, "Cara")
        has(f"{_label}: no alias", _text, "Moonveil", False)
    has("chat 1:1: real appearance (positive control)", TEXT["chat 1:1"], "freckled")
    for _label, _payload in PAYLOADS.items():
        check(f"{_label}: no alias anywhere", leaks(_payload, "Moonveil"), [])
        check(f"{_label}: the leak walk sees the real name (positive control)",
              bool(leaks(_payload, "Cara")), True)
        check(f"{_label}: Cara's display_name", SHOWN[_label], "Cara")

print()
if FAILURES:
    print(f"FAIL — {len(FAILURES)} of {CHECKED} checks failed: {FAILURES}")
    sys.exit(1)
print(f"PASS — {CHECKED} checks")
