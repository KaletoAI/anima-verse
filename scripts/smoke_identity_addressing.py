#!/usr/bin/env python3
"""Smoke: a name an observer's LLM call hands back — the alias of a
transformed character, or a knower's label "<alias> (<name>)" — resolves to
the real character in every name resolver; a non-knower cannot reach the
bearer in person by her real name while she is transformed; a remote message
to the alias is refused; every "available: …" list shows labels.

Usage:  ./.venv/bin/python scripts/smoke_identity_addressing.py

Throwaway storage + instance (``STORAGE_DIR``/``INSTANCE_DIR`` point at temp
dirs, ``paths.init`` runs BEFORE any world-DB module is imported). No server,
no LLM, no real world. The transformation package is loaded the way the
server loads it (``packages.enabled`` = transformation, party, interact,
``talk_to``, ``send_message``, movement;
``discover_packages()``) and is the provider of ``identity.*``. The verbs are
instantiated directly (``TalkToSkill``, ``SendMessageSkill``,
``GoToCharacterSkill``, ``PartySkill``, ``InteractSkill``); the agent loop
and the task queue are replaced by recorders (``get_agent_loop`` /
``get_task_queue`` patched), so nothing runs in the background.

FIXTURE
    Location "Inn", rooms "taproom" (entry) and "cellar". Cara (bearer of
    "amulet"), Kim (knower of Cara), Obs (knows nothing), all in the
    taproom. Persona p1: item amulet, alias "Moonveil", no suit, no
    condition, max 0, cooldown 0. Cara is transformed through
    ``engine.transform``. Roster order is the DB's ``ORDER BY name``:
    Cara, Kim, Obs.

THE RULES (task brief + rulings) and what follows BY HAND
    shown_name(Obs, Cara) = "Moonveil", shown_name(Kim, Cara) =
    "Moonveil (Cara)"; so Obs's label list of the roster is
    "Moonveil, Kim, Obs" and an "Available:" list never says "Cara" to Obs.
    In-person resolver (resolve_present): roster name or active alias
    (casefold); a "<head> (<inner>)" token by its head; the REAL name of a
    transformed bearer only for a knower (R4) — else None.
    Remote resolver (resolve_remote): a real name (also the inner part of a
    label) → itself for anyone; an active alias alone → the refusal
    "Error: Moonveil cannot be reached that way."; else (None, "").
[A] resolve_present: Obs "Moonveil"/"moonveil"/"Moonveil (avatar)" → Cara;
    Obs "Cara" → None; Obs "Kim" → Kim; Kim "Cara" → Cara; Kim
    "Moonveil (Cara)" → Cara; Cara "Cara" → Cara; Obs "Nobody" → None.
    resolve_remote: Obs "Moonveil" → (None, refusal); Kim "Moonveil" →
    (None, refusal); Obs "Cara" → ("Cara", ""); Kim "Moonveil (Cara)" →
    ("Cara", ""); Obs "Nobody" → (None, "").
[B] talk_to: Obs → "Moonveil": answer "Spoke to Moonveil. They will reply
    when they get to it."; the utterance's addressees ["Cara"]; the respond
    bump goes to "Cara"; Cara's history with Obs has the line. Kim →
    "Moonveil (Cara)": "Spoke to Moonveil (Cara). …", addressees ["Cara"].
    Obs → "Cara": "Character 'Cara' not found. Available: Moonveil, Kim,
    Obs" (the echo is Obs's own word; the list names no Cara).
[C] send_message: Obs → "Moonveil": exactly "Error: Moonveil cannot be
    reached that way."; nothing stored for Cara from Obs on the phone. Obs →
    "Cara": "Message sent to Cara. They will reply when they get to it."
    (she is messaged as herself). Obs → "Nobody": "Character 'Nobody' not
    found. Available: Moonveil, Kim, Obs".
[D] go_to_character (everyone in the taproom): Obs "Moonveil" → "You are
    already in the same room as Moonveil."; Kim "Cara" → "… as Moonveil
    (Cara)."; Obs "Cara" → starts "You do not know where Cara is right now"
    (R4: the not-present path, never "no character called"); Obs "Nobody"
    → starts "There is no character called 'Nobody'".
[E] party: Obs invites "Cara" → "Cara is not at your location. You can
    only invite someone who is here with you." (R4), no invite stored.
    Obs invites "Moonveil" (consent request stubbed) → "Obs invites
    Moonveil to come along — pending." and an Obs→Cara invite is stored;
    cleared again. Cara invites Obs (real consent request, agent loop
    recorded): the hint handed to Obs's bump says "Moonveil invites you to
    travel together", "The explicitly included group is: Moonveil, Obs.",
    "leader=Moonveil", no "Cara". Obs's open question line starts
    "Moonveil invited Obs to go together. Yes: JoinParty {\"leader\":
    \"Moonveil\"". Obs JoinParty {"leader": "Moonveil", "invite_id": <id>}
    → "Obs joins Moonveil's party."; Obs's party block says "You travel
    with Moonveil's party. Moonveil chooses", no "Cara". Obs leaves.
[F] interact (no pair clips in the temp world → "Known: none"; a refusal
    reads with the verb's "Error: " prefix): Obs → "Moonveil", action
    "hugging" → "Error: 'hugging' is not a two-person action. Known: none."
    (the partner resolved); Obs → "Cara" → "Error: Character 'Cara' not
    found. Available: Moonveil, Kim, Obs". With a pending pair
    invitation from Cara and a furniture invitation from Cara (stubbed):
    Obs's decision menu lines start "invitation from Moonveil: hugging - to
    answer: {\"partner\": \"Moonveil\"" and "furniture invitation from
    Moonveil: Sit"; open_questions lines start "Moonveil invited Obs to
    \"Sit\"" and "Moonveil invited Obs to \"hugging\""; no line has "Cara".
    Obs answers {"partner": "Moonveil", "answer": "yes"}: the furniture run
    of Cara is found (the stubbed run id is unknown to the store → "Cannot:
    this exact prop invitation is not addressed to you."), not the generic
    'pass {"partner": …}' refusal.
[G] npc_actions._apply_talk (present = Cara, Kim; talk allowed): Obs says
    to "Moonveil" → {"said_to": "Cara"}, addressees ["Cara"]; Obs says to
    "Cara" → {} (R4); Kim says to "Moonveil (Cara)" → {"said_to": "Cara"}.
    present_partners(Obs) with every character a temp NPC (patched): the
    entries carry "shown" = "Moonveil" for Cara and "Kim" for Kim.
[H] play._require_present_target (the HUD posts REAL names as keys —
    display-only secrecy, so the real name stays accepted there): Obs
    "Moonveil" → "Cara"; Obs "Cara" → "Cara"; Obs "Nobody" → 400 whose
    detail lists "Moonveil" and has no "Cara".
[I] prop_actions._named_request: Obs naming partner "Cara" for a pair
    offer with Cara as available target → refused "partner_not_available"
    and nothing executed (R4); Kim naming "Cara" → members ["Cara"].
[J] After ``engine.revert``: the alias names nobody —
    resolve_present(Obs, "Moonveil") = None and Obs's talk_to "Moonveil"
    takes the ordinary unknown path: starts "Character 'Moonveil' not
    found." (Cara is herself again, so the list may name her). Re-transformed
    afterwards for [K].
[K] Providers unregistered (deletion test): resolve_present(Obs, "Cara") =
    "Cara", resolve_present(Obs, "Moonveil") = None, resolve_remote(Obs,
    "Moonveil") = (None, "").
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="identity-addressing-smoke-"))
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
(STORAGE / "config.json").write_text(json.dumps({
    "packages": {"enabled": "transformation,party,interact,talk_to,send_message,movement"},
    "skills": {"transformation_personas": PERSONAS},
}), encoding="utf-8")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(ROOT / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

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


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def has(label, text, needle, expected=True):
    global CHECKED
    CHECKED += 1
    ok = (needle in text) == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {needle!r} {'in' if expected else 'not in'} "
          f"{text[:160]!r}")
    if not ok:
        FAILURES.append(label)


set_game_factor(0.0)
set_game_time(GameTime.parse("Y0002-D100T12:00:00"))

INN = add_location("Inn", "A stone house.")["id"]
ROOM, CELLAR = "taproom", "cellar"
_data = _load_world_data()
for _loc in _data.get("locations", []):
    if _loc.get("id") == INN:
        _loc["rooms"] = [{"id": ROOM, "name": "Taproom", "description": "Benches."},
                         {"id": CELLAR, "name": "Cellar", "description": "Barrels."}]
        _loc["entry_room"] = ROOM
_save_world_data(_data)

for _name in ("Cara", "Kim", "Obs"):
    assert save_character_profile(_name, {"character_name": _name, "template": "human-roleplay"},
                                  create_new=True), _name
    with keyed_lock("character_profile", _name):
        _p = get_character_profile(_name)
        _p["current_location"] = INN
        _p["current_room"] = ROOM
        assert save_character_profile(_name, _p), _name

inventory.add_item("Amulet", item_id="amulet")
assert inventory.add_to_inventory("Cara", "amulet")

from app.plugins import loader, registry  # noqa: E402
loader.discover_packages()
check("package loaded", "transformation" in {p.id for p in registry.packages()}, True)

from app.core import hooks  # noqa: E402
from app.core import identity_view as IV  # noqa: E402
from app.plugins.context import PluginContext  # noqa: E402
from plugins.transformation import engine, knowers  # noqa: E402

engine.tick()
check("Kim made a knower", knowers.add("Kim", "Cara", "p1"), True)
check("transform ok", engine.transform("Cara", "p1", source="smoke"),
      {"ok": True, "reason": "", "alias": "Moonveil"})
REFUSAL = "Error: Moonveil cannot be reached that way."


class FakeLoop:
    """Records what the verbs hand the agent loop; runs nothing."""

    def __init__(self):
        self.calls = []

    def bump_respond(self, name, **kw):
        self.calls.append(("respond", name, kw))
        return True

    def bump(self, name, **kw):
        self.calls.append(("bump", name, kw))
        return True

    def reset_room_energy(self, *a, **kw):
        pass

    def dispatch_room_reactions(self, *a, **kw):
        self.calls.append(("dispatch", kw.get("addressees")))


class FakeQueue:
    def is_paused(self, _name):
        return False


LOOP = FakeLoop()
_loop_patch = patch("app.core.agent_loop.get_agent_loop", lambda: LOOP)
_loop_patch.start()
_queue_patch = patch("app.core.task_queue.get_task_queue", lambda: FakeQueue())
_queue_patch.start()

from app.core import perception  # noqa: E402
UTTERANCES = []
_real_record = perception.record_utterance


def _recording(*a, **kw):
    UTTERANCES.append(list(kw.get("addressees") or []))
    return _real_record(*a, **kw)


perception.record_utterance = _recording

# ── [A] the two helpers ─────────────────────────────────────────────────────
print("[A] resolve_present / resolve_remote")
for obs, tok, want in (("Obs", "Moonveil", "Cara"), ("Obs", "moonveil", "Cara"),
                       ("Obs", "Moonveil (avatar)", "Cara"), ("Obs", "Cara", None),
                       ("Obs", "Kim", "Kim"), ("Kim", "Cara", "Cara"),
                       ("Kim", "Moonveil (Cara)", "Cara"), ("Cara", "Cara", "Cara"),
                       ("Obs", "Nobody", None)):
    check(f"present {obs}/{tok!r}", IV.resolve_present(obs, tok), want)
for obs, tok, want in (("Obs", "Moonveil", (None, REFUSAL)), ("Kim", "Moonveil", (None, REFUSAL)),
                       ("Obs", "Cara", ("Cara", "")), ("Kim", "Moonveil (Cara)", ("Cara", "")),
                       ("Obs", "Nobody", (None, ""))):
    check(f"remote {obs}/{tok!r}", IV.resolve_remote(obs, tok), want)

# ── [B] talk_to ─────────────────────────────────────────────────────────────
print("[B] talk_to")
from plugins.talk_to.skill import TalkToSkill  # noqa: E402
TALK = TalkToSkill({"enabled": True}, PluginContext("talk_to"))


def talk(sender, target, message):
    UTTERANCES.clear()
    LOOP.calls.clear()
    return TALK.execute(json.dumps({"agent_name": sender, "name": target, "message": message}))


check("Obs -> Moonveil", talk("Obs", "Moonveil", "Who are you?"),
      "Spoke to Moonveil. They will reply when they get to it.")
check("utterance addressee real", UTTERANCES, [["Cara"]])
check("respond bump reaches Cara", [c[1] for c in LOOP.calls if c[0] == "respond"], ["Cara"])
from app.models import chat  # noqa: E402
check("Cara's history has the line",
      any(m["content"] == "Who are you?" for m in chat.get_chat_history("Cara", partner_name="Obs")),
      True)
check("Kim -> label", talk("Kim", "Moonveil (Cara)", "Hi."),
      "Spoke to Moonveil (Cara). They will reply when they get to it.")
check("label addressee real", UTTERANCES, [["Cara"]])
check("Obs -> real name (R4)", talk("Obs", "Cara", "Cara?"),
      "Character 'Cara' not found. Available: Moonveil, Kim, Obs")
check("R4 nothing recorded", UTTERANCES, [])

# ── [C] send_message ────────────────────────────────────────────────────────
print("[C] send_message")
from plugins.send_message.skill import SendMessageSkill  # noqa: E402
SEND = SendMessageSkill({"enabled": True}, PluginContext("send_message"))


def send(sender, target, message):
    return SEND.execute(json.dumps({"agent_name": sender, "to": target, "message": message}))


check("Obs -> Moonveil refused", send("Obs", "Moonveil", "Hello stranger."), REFUSAL)
check("nothing stored for Cara",
      any(m["content"] == "Hello stranger." for m in chat.get_chat_history("Cara", partner_name="Obs")),
      False)
check("Obs -> Cara (as herself)", send("Obs", "Cara", "Where are you?"),
      "Message sent to Cara. They will reply when they get to it.")
check("Obs -> unknown", send("Obs", "Nobody", "Hi."),
      "Character 'Nobody' not found. Available: Moonveil, Kim, Obs")

# ── [D] go_to_character ─────────────────────────────────────────────────────
print("[D] go_to_character")
from plugins.movement.skill_go_to_character import GoToCharacterSkill  # noqa: E402
GO = GoToCharacterSkill({"enabled": True}, PluginContext("movement"))


def go(actor, who):
    return GO.execute(json.dumps({"agent_name": actor, "character": who}))


check("Obs -> Moonveil", go("Obs", "Moonveil"), "You are already in the same room as Moonveil.")
check("Kim -> Cara", go("Kim", "Cara"), "You are already in the same room as Moonveil (Cara).")
check("Obs -> Cara (R4)", go("Obs", "Cara").startswith("You do not know where Cara is right now"), True)
check("Obs -> unknown", go("Obs", "Nobody").startswith("There is no character called 'Nobody'"), True)

# ── [E] party ───────────────────────────────────────────────────────────────
print("[E] party")
from app.core import party_engine as P  # noqa: E402
from plugins.party import trip_intents  # noqa: E402
from plugins.party.blocks import party_section  # noqa: E402
from plugins.party.skill import PartySkill  # noqa: E402
_pctx = PluginContext("party")
INVITE, JOIN, LEAVE = (PartySkill({}, _pctx, v) for v in ("invite", "join", "leave"))


def party(skill, actor, **kw):
    return skill.execute(json.dumps({"agent_name": actor, **kw}))


check("Obs invites Cara (R4)", party(INVITE, "Obs", target="Cara"),
      "Cara is not at your location. You can only invite someone who is here with you.")
check("no invite stored", P.find_pending_invite("Obs", "Cara"), None)
with patch.object(trip_intents, "request_consent", lambda invite_id: True):
    check("Obs invites Moonveil", party(INVITE, "Obs", target="Moonveil"),
          "Obs invites Moonveil to come along — pending.")
check("invite stored for Cara", bool(P.find_pending_invite("Obs", "Cara")), True)
P.clear_invites_for("Obs")
LOOP.calls.clear()
party(INVITE, "Cara", target="Obs")
_inv = P.find_pending_invite("Cara", "Obs")
check("Cara's invite stored", bool(_inv), True)
_hints = [c[2].get("hint", "") for c in LOOP.calls if c[1] == "Obs"]
check("consent request reached Obs", len(_hints), 1)
_hint = _hints[0] if _hints else ""
has("consent: inviter label", _hint, "Moonveil invites you to travel together")
has("consent: group labels", _hint, "The explicitly included group is: Moonveil, Obs.")
has("consent: leader label", _hint, "leader=Moonveil")
has("consent: no real name", _hint, "Cara", False)
_q = trip_intents.open_questions("Obs", ["JoinParty"])
check("open question by label",
      bool(_q) and _q[0].startswith('Moonveil invited Obs to go together. Yes: JoinParty {"leader": "Moonveil"'),
      True)
has("open question no real name", " ".join(_q), "Cara", False)
check("Obs joins by alias", party(JOIN, "Obs", leader="Moonveil", invite_id=(_inv or {}).get("invite_id", "")),
      "Obs joins Moonveil's party.")
check("party leader is Cara", (P.get_party_of("Obs") or {}).get("leader"), "Cara")
_block = party_section("Obs")
has("party block label", _block, "You travel with Moonveil's party. Moonveil chooses")
has("party block no real name", _block, "Cara", False)
check("Obs leaves", party(LEAVE, "Obs").startswith("Obs leaves the party"), True)

# ── [F] interact ────────────────────────────────────────────────────────────
print("[F] interact")
from app.core import interaction_engine as IE  # noqa: E402
from app.core import prop_action_engine, prop_actions  # noqa: E402
from plugins.interact import register as interact_register  # noqa: E402
from plugins.interact.skill import InteractSkill  # noqa: E402
INTERACT = InteractSkill({}, PluginContext("interact"))


def interact(actor, **kw):
    return str(INTERACT.execute(json.dumps({"agent_name": actor, **kw})))


check("Obs -> Moonveil resolves", interact("Obs", partner="Moonveil", action="hugging"),
      "Error: 'hugging' is not a two-person action. Known: none.")
check("Obs -> Cara (R4)", interact("Obs", partner="Cara", action="hugging"),
      "Error: Character 'Cara' not found. Available: Moonveil, Kim, Obs")
_invites = [{"inviter": "Cara", "pose_key": "hugging", "invite_id": "i1"}]
_run = {"actor": "Cara", "label": "Sit", "can_respond": True, "execution_id": "e1",
        "target": {"location_id": INN, "room_id": ROOM, "placement_id": "x"}}
with patch.object(IE, "pending_invites_for", lambda name: _invites if name == "Obs" else []), \
     patch.object(prop_action_engine, "state_for",
                  lambda name: {"incoming": [_run] if name == "Obs" else []}), \
     patch.object(prop_actions, "piece_label", lambda target, lang="en": ""):
    _menu = INTERACT.decision_menu("Obs")
    check("menu: pair invitation by label",
          bool(_menu) and _menu[0].startswith('invitation from Moonveil: hugging - to answer: {"partner": "Moonveil"'),
          True)
    check("menu: furniture invitation by label",
          len(_menu) > 1 and _menu[1].startswith("furniture invitation from Moonveil: Sit"), True)
    has("menu: no real name", " ".join(_menu), "Cara", False)
    _oq = interact_register.open_questions("Obs", ["InteractWith"])
    check("open questions by label",
          [line.split(".")[0] for line in _oq],
          ['Moonveil invited Obs to "Sit"', 'Moonveil invited Obs to "hugging"'])
    has("open questions: no real name", " ".join(_oq), "Cara", False)
    check("answer by alias finds Cara's run", interact("Obs", partner="Moonveil", answer="yes"),
          "Cannot: this exact prop invitation is not addressed to you.")

# ── [G] npc_actions ─────────────────────────────────────────────────────────
print("[G] npc_actions")
from app.core import npc_actions  # noqa: E402
_vars = {"talk_allowed": True,
         "present": [{"name": "Cara", "shown": "Moonveil", "role": "", "task": "", "activity": ""},
                     {"name": "Kim", "shown": "Kim", "role": "", "task": "", "activity": ""}]}
UTTERANCES.clear()
check("Obs says to Moonveil",
      npc_actions._apply_talk("Obs", {"say": {"to": "Moonveil", "line": "Hello."}}, _vars, moved=False),
      {"said_to": "Cara"})
check("npc line addressee real", UTTERANCES, [["Cara"]])
check("Obs says to Cara (R4)",
      npc_actions._apply_talk("Obs", {"say": {"to": "Cara", "line": "Cara?"}}, _vars, moved=False), {})
_kvars = {**_vars, "present": [{"name": "Cara", "shown": "Moonveil (Cara)", "role": "", "task": "",
                                "activity": ""}]}
check("Kim says to label",
      npc_actions._apply_talk("Kim", {"say": {"to": "Moonveil (Cara)", "line": "Hi."}}, _kvars, moved=False),
      {"said_to": "Cara"})
with patch("app.models.character.is_temporary_npc", lambda name: True):
    _pp = npc_actions.present_partners("Obs")
check("present_partners carry the label",
      sorted((p["name"], p.get("shown")) for p in _pp), [("Cara", "Moonveil"), ("Kim", "Kim")])

# ── [H] play._require_present_target ────────────────────────────────────────
print("[H] play target gate")
from fastapi import HTTPException  # noqa: E402
from app.routes import play  # noqa: E402
check("alias -> Cara", play._require_present_target("Obs", "Moonveil"), "Cara")
check("HUD real key -> Cara", play._require_present_target("Obs", "Cara"), "Cara")
try:
    play._require_present_target("Obs", "Nobody")
    _detail = ""
except HTTPException as e:
    _detail = str(e.detail)
has("unknown: list by label", _detail, "Moonveil")
has("unknown: no real name", _detail, "Cara", False)

# ── [I] prop_actions._named_request ─────────────────────────────────────────
print("[I] furniture request by name")
_offer = {"prop_label": "Bench", "label": "Cuddle", "participants": 2, "required_partner": True,
          "enabled": False, "reason": "partner_required", "distance_m": 1.0, "action_id": "a1",
          "definition_revision": 1, "target": {},
          "available_targets": [{"partner": "Cara", "enabled": True, "reason": ""}]}
_sent = []
with patch.object(prop_actions, "offers", lambda actor, **kw: [_offer]), \
     patch.object(prop_actions, "execute",
                  lambda actor, exact: _sent.append(exact) or {"status": "requested"}):
    _res = prop_actions._named_request("Obs", {"furniture": "Bench", "action": "Cuddle",
                                               "partner": "Cara"})
    check("Obs naming Cara refused (R4)", (_res.get("status"), _res.get("reason")),
          ("refused", "partner_not_available"))
    check("nothing executed", _sent, [])
    prop_actions._named_request("Kim", {"furniture": "Bench", "action": "Cuddle", "partner": "Cara"})
    check("Kim naming Cara reaches her", [e.get("members") for e in _sent], [["Cara"]])

# ── [J] reverted: the alias is no longer anyone ─────────────────────────────
print("[J] reverted")
check("revert ok", engine.revert("Cara", reason="admin"), True)
check("stale alias resolves to nobody", IV.resolve_present("Obs", "Moonveil"), None)
_r = talk("Obs", "Moonveil", "Hello?")
check("stale alias: not found", _r.startswith("Character 'Moonveil' not found."), True)
check("transform again", engine.transform("Cara", "p1", source="smoke")["ok"], True)

# ── [K] package absent ──────────────────────────────────────────────────────
print("[K] providers unregistered")
hooks.unregister_owned_providers("transformation")
check("real name works again", IV.resolve_present("Obs", "Cara"), "Cara")
check("alias is nobody", IV.resolve_present("Obs", "Moonveil"), None)
check("remote alias is nobody", IV.resolve_remote("Obs", "Moonveil"), (None, ""))

perception.record_utterance = _real_record
_loop_patch.stop()
_queue_patch.stop()
print()
if FAILURES:
    print(f"FAIL — {len(FAILURES)} of {CHECKED} checks failed: {FAILURES}")
    sys.exit(1)
print(f"PASS — {CHECKED} checks")
