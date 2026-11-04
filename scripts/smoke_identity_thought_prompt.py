#!/usr/bin/env python3
"""Smoke: the autonomous thought prompt and the rp_first tool-step prompt name
and describe people from the THINKING character's view — a transformed person
is the alias (and the persona description) for a non-knower, "<alias> (<name>)"
for a knower; pairwise chat lines spoken while a persona was worn keep reading
with that persona, also after the bearer reverted.

Usage:  ./.venv/bin/python scripts/smoke_identity_thought_prompt.py

Throwaway storage + instance (``STORAGE_DIR``/``INSTANCE_DIR`` point at temp
dirs, ``paths.init`` runs BEFORE any world-DB module is imported). No server,
no LLM, no real world. The transformation package is loaded the way the
server loads it (``packages.enabled = "transformation"``,
``discover_packages()``); it is the provider of ``identity.*``. Builders called
directly: ``thought_context.build_thought_context`` rendered through
``chat/agent_thought.md``, ``chat/agent_thought_in_chat.md`` and
``chat/thought_presence.md`` (the user-turn presence line), and
``tool_step_prompt.build_tool_step_prompt`` (no tools offered — the presence
and partner lines are the surface here).

FIXTURE
    Location "Inn", rooms "taproom" (entry) and "cellar". Cara (bearer of
    "amulet", appearance "freckled redhead with a crooked smile"), Kim
    (knower of Cara), Obs (knows nothing), all in the taproom. Persona p1:
    item amulet, alias "Moonveil", description "A figure in moonlit
    silver.", no suit, no condition, max 0, cooldown 0. Cara is transformed
    through ``engine.transform``. Nobody is the avatar unless a section says
    so (``account.get_active_character`` patched). The relationships section
    is not on these templates; the memory section neither — nothing to stub.

    Pairwise in-person chat (``chat.save_message``, explicit timestamps T1 <
    T2 < … so the order is fixed):
      T1 (BEFORE the transformation) Obs's history, Cara (role user):
         "Old words." — unstamped (nobody was transformed at T1).
      T2 Obs's history, Cara (user): "Silver greetings."   — stamped
      T3 Obs's history, Obs (assistant): "Who are you?"   — stamped
      T4 Kim's history, Cara (user): "It is me, Kim."     — stamped
    The stamp rule (identity_view.pair_stamp): a message between A and B
    saved while A wears a persona carries ``identity = {A: alias}`` and
    ``identity_shown = {A: shown_name(B, A)}`` — so T2/T3 carry
    {Cara: "Moonveil"} / {Cara: "Moonveil"} and T4 {Cara: "Moonveil"} /
    {Cara: "Moonveil (Cara)"} (Kim is a knower). A phone message (medium
    "messaging") is never stamped — the persona has no remote contact.

THE RULES (task brief) and what follows BY HAND
    shown_name(Obs, Cara) = "Moonveil", shown_name(Kim, Cara) = "Moonveil
    (Cara)", masked_description(Obs, Cara) = "A figure in moonlit silver.".
    The recent-chat block shows the LAST 3 messages with the latest partner
    (Obs: partner Cara). T5 (Obs (assistant) "Fine.", stamped) pushes the
    unstamped T1 out of that window, so the window is T2, T3, T5.
[A] Obs, Cara transformed in the taproom: recent-chat block exactly
    "  Moonveil: Silver greetings.\n  Obs: Who are you?\n  Obs: Fine."
    (the subject herself is never relabelled — Obs reads "Obs"). Rendered
    agent_thought.md, agent_thought_in_chat.md and thought_presence.md:
    no "Cara", no "freckled", "Moonveil" present; a present-details line
    starting "- Moonveil: A figure in moonlit silver."; the presence names
    handed to thought_presence.md are the labels {"Kim", "Moonveil"}
    (compared sorted — the order is addressable_for's).
    absent_named_people(Obs, …, ["Cara was here"]) = [] — a present masked
    person is never printed as absent (she is in the real-name "here" set).
[B] Obs, rp_first tool step (thought mode, present = tool_step_presence(Obs)
    real names = {Cara, Kim}): user part has "Present in your room:" with
    "Moonveil" and "Kim", no "Cara" in system+user; tool_step_presence(Obs)
    still has "Cara" (real names for its non-prompt callers);
    tool_step_presence_labels(Obs) = shown names {"Moonveil", "Kim"}.
    Respond mode, partner Cara: "Talking with: Moonveil".
[C] Kim: thought prompt present-details line starting "- Moonveil (Cara):
    freckled redhead"; recent chat (partner Cara, T4 only) "  Moonveil
    (Cara): It is me, Kim."; tool step respond partner Cara →
    "Talking with: Moonveil (Cara)"; present line has "Moonveil (Cara)".
[D] Elsewhere: Cara moved to the cellar (still transformed) → Obs's
    elsewhere block "- Moonveil — in: Cellar", no "Cara"; moved back.
[E] Avatar = Cara (patched): the present line is "- Moonveil (avatar)…"
    (the label keeps the caller's " (avatar)" suffix); "Cara" nowhere in
    the three renders. (The suit-less fixture gives Cara no outfit, so the
    "Avatar outfit (<label>)" block is empty here.)
[F] Tracker: Obs carries "compass" (tracks_character "Cara") → while Cara
    is masked for Obs: "- Your Compass reaches for Cara, but cannot find
    them right now." (never "here with you", never "Moonveil" in that
    block). Kim carrying the same compass sees "- Your Compass hums softly:
    Cara is here with you." (a knower). The compass goes again after.
[J] (runs before [G], Cara still transformed) The place offer and the
    furniture lines name people from the viewer's view: a seat held by Cara
    → Obs "- Seat (occupied by Moonveil)", Kim "- Seat (occupied by
    Moonveil (Cara))"; a pair action with partner Cara → Obs "- Bench:
    Cuddle (with Moonveil)", Kim "… (with Moonveil (Cara))". A furniture
    request by Obs naming partner "Moonveil" reaches Cara (members
    ["Cara"] handed to execute) and the tool answer names "Moonveil".
[G] After ``engine.revert`` (reason "admin"): Obs's recent chat still reads
    "  Moonveil: Silver greetings." (stamped, persona no longer worn → the
    stamped label); Kim's "  Moonveil (Cara): It is me, Kim."; a NEW message
    T6 (Cara user "Back again.") is unstamped → "  Cara: Back again."; the
    present line has "Cara" again; present details "- Cara: freckled".
[H] A phone message (save_direct_message Cara→Obs) while Cara is
    transformed again: its stored metadata has no "identity" key.
[I] Package providers unregistered (``unregister_owned_providers
    ("transformation")``) — Cara still transformed in the store: Obs's
    thought prompt has "Cara" in the present details and no "Moonveil" in
    presence line; stamped_name(Obs, Cara, <T2 metadata>) = "Cara"
    (stamps are ignored without a provider: real names).
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="identity-thought-prompt-smoke-"))
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
    "packages": {"enabled": "transformation"},
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
APPEARANCE = "freckled redhead with a crooked smile"


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
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {needle!r} {'in' if expected else 'not in'} text")
    if not ok:
        FAILURES.append(label)
        hit = text.find(needle)
        if hit >= 0:
            print("      …" + text[max(0, hit - 160):hit + 80].replace("\n", "\n      ") + "…")


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


def place(name, room):
    with keyed_lock("character_profile", name):
        p = get_character_profile(name)
        p["current_location"] = INN
        p["current_room"] = room
        assert save_character_profile(name, p), name


for _name in ("Cara", "Kim", "Obs"):
    assert save_character_profile(_name, {"character_name": _name, "template": "human-roleplay"},
                                  create_new=True), _name
    place(_name, ROOM)
    if _name == "Cara":
        with keyed_lock("character_profile", _name):
            _p = get_character_profile(_name)
            _p["character_appearance"] = APPEARANCE
            assert save_character_profile(_name, _p)

inventory.add_item("Amulet", item_id="amulet")
assert inventory.add_to_inventory("Cara", "amulet")
inventory.add_item("Compass", item_id="compass")
assert inventory.update_item("compass", {"tracks_character": "Cara"})

from app.plugins import loader, registry  # noqa: E402
loader.discover_packages()
check("package loaded", "transformation" in {p.id for p in registry.packages()}, True)

from app.core import hooks, identity_view, prompt_templates  # noqa: E402
from app.core import thought_context as tc  # noqa: E402
from app.core.streaming import tool_step_presence  # noqa: E402
from app.core.tool_step_prompt import build_tool_step_prompt  # noqa: E402
from app.models import chat  # noqa: E402
from app.skills.base import TurnFacts  # noqa: E402
from plugins.transformation import engine, knowers  # noqa: E402

engine.tick()


def say(owner, partner, role, speaker, text, ts):
    msg = {"content": text, "role": role, "speaker": speaker, "medium": "in_person",
           "timestamp": f"2026-01-01T00:00:{ts:02d}+00:00"}
    assert chat.save_message(msg, character_name=owner, partner_name=partner), text


say("Obs", "Cara", "user", "Cara", "Old words.", 1)
check("Kim made a knower", knowers.add("Kim", "Cara", "p1"), True)
check("transform ok", engine.transform("Cara", "p1", source="smoke"),
      {"ok": True, "reason": "", "alias": "Moonveil"})
say("Obs", "Cara", "user", "Cara", "Silver greetings.", 2)
say("Obs", "Cara", "assistant", "Obs", "Who are you?", 3)
say("Kim", "Cara", "user", "Cara", "It is me, Kim.", 4)
say("Obs", "Cara", "assistant", "Obs", "Fine.", 5)


def thought(observer):
    ctx = tc.build_thought_context(observer)
    full = prompt_templates.render("chat/agent_thought.md", **ctx)
    in_chat = prompt_templates.render("chat/agent_thought_in_chat.md", **ctx)
    presence = prompt_templates.render("chat/thought_presence.md", **ctx)
    return ctx, full, in_chat, presence


def tool_step(observer, mode, partner=""):
    present = tool_step_presence(observer)
    p = build_tool_step_prompt(observer, mode=mode, rp_response="I look around.",
                               user_input="Hello." if mode == "respond" else "",
                               tools=[], facts=TurnFacts(observer, mode, present, partner=partner),
                               tool_format="tag")
    return p.system + "\n" + p.user


def line_starts(text, prefix):
    return any(line.strip().startswith(prefix) for line in text.splitlines())


# ── [A] non-knower thought prompt ───────────────────────────────────────────
print("[A] Obs thinks, Cara transformed in the room")
ctx, full, in_chat, presence = thought("Obs")
check("recent chat block", ctx["recent_chat_block"],
      "  Moonveil: Silver greetings.\n  Obs: Who are you?\n  Obs: Fine.")
for label, text in (("agent_thought", full), ("agent_thought_in_chat", in_chat),
                    ("thought_presence", presence)):
    has(f"{label}: no real name", text, "Cara", False)
    has(f"{label}: no real appearance", text, "freckled", False)
    has(f"{label}: alias", text, "Moonveil")
check("present details line", line_starts(full, "- Moonveil: A figure in moonlit silver."), True)
check("presence names are labels", sorted(ctx["room_presence_names"]), ["Kim", "Moonveil"])
check("absent list never names a present masked person",
      tc.absent_named_people("Obs", INN, ROOM, ["Cara was here"]), [])

# ── [B] non-knower tool step ────────────────────────────────────────────────
print("[B] Obs tool step")
check("tool_step_presence stays real", sorted(tool_step_presence("Obs")), ["Cara", "Kim"])
from app.core.streaming import tool_step_presence_labels  # noqa: E402
check("tool_step_presence_labels", sorted(tool_step_presence_labels("Obs")), ["Kim", "Moonveil"])
_ts = tool_step("Obs", "thought")
has("thought: no real name", _ts, "Cara", False)
has("thought: present line", _ts, "Present in your room:")
has("thought: alias present", _ts, "Moonveil")
_ts = tool_step("Obs", "respond", partner="Cara")
has("respond: partner alias", _ts, "Talking with: Moonveil\n")
has("respond: no real name", _ts, "Cara", False)

# ── [C] knower ──────────────────────────────────────────────────────────────
print("[C] Kim")
ctx, full, in_chat, presence = thought("Kim")
check("knower details real appearance", line_starts(full, "- Moonveil (Cara): freckled redhead"), True)
check("knower recent chat", ctx["recent_chat_block"], "  Moonveil (Cara): It is me, Kim.")
has("knower presence line", presence, "Moonveil (Cara)")
_ts = tool_step("Kim", "respond", partner="Cara")
has("knower partner label", _ts, "Talking with: Moonveil (Cara)")

# ── [D] elsewhere ───────────────────────────────────────────────────────────
print("[D] Cara in the cellar")
place("Cara", CELLAR)
ctx, full, _, presence = thought("Obs")
check("elsewhere block", ctx["elsewhere_block"], "- Moonveil — in: Cellar")
has("no real name", full + presence, "Cara", False)
place("Cara", ROOM)

# ── [E] avatar ──────────────────────────────────────────────────────────────
print("[E] Cara is the avatar")
with patch("app.models.account.get_active_character", return_value="Cara"):
    ctx, full, in_chat, presence = thought("Obs")
    has("no real name", full + in_chat + presence, "Cara", False)
    check("avatar marked by alias", line_starts(full, "- Moonveil (avatar)"), True)

# ── [F] tracker ─────────────────────────────────────────────────────────────
print("[F] tracker")
assert inventory.add_to_inventory("Obs", "compass")
check("masked target cannot be found", tc._build_tracker_block("Obs", INN),
      "- Your Compass reaches for Cara, but cannot find them right now.")
assert inventory.remove_from_inventory("Obs", "compass")
assert inventory.add_to_inventory("Kim", "compass")
check("knower tracker", tc._build_tracker_block("Kim", INN),
      "- Your Compass hums softly: Cara is here with you.")
assert inventory.remove_from_inventory("Kim", "compass")

# ── [J] place offer + furniture actions name the occupants / partners ──────
print("[J] place offer and furniture lines")
from app.core import places, prop_actions  # noqa: E402
_seat = {"id": "s1", "group": "seat", "label": "Seat", "capacity": 1, "slots": [[0.0, 0.0]],
         "facing": 0.0, "y_world": 0.0, "root_offset": 0.4, "source": "room", "room_id": ROOM}
with patch.object(places, "room_places", lambda loc, room: [_seat]), \
     patch.object(places, "occupancy", lambda loc, room, exclude="": {"s1": [("Cara", 0)]}):
    check("occupant by alias (Obs)", places._group_lines(INN, ROOM, "Obs")[0],
          ["- Seat (occupied by Moonveil)"])
    check("occupant by label (Kim)", places._group_lines(INN, ROOM, "Kim")[0],
          ["- Seat (occupied by Moonveil (Cara))"])
_rows = [{"prop_label": "Bench", "label": "Cuddle", "partners": ["Cara"]}]
check("pair partner by alias", prop_actions._piece_lines(_rows, "Obs"),
      ["- Bench: Cuddle (with Moonveil)"])
check("pair partner by label (knower)", prop_actions._piece_lines(_rows, "Kim"),
      ["- Bench: Cuddle (with Moonveil (Cara))"])
_offer = {"prop_label": "Bench", "label": "Cuddle", "participants": 2, "required_partner": True,
          "enabled": False, "reason": "partner_required", "distance_m": 1.0, "action_id": "a1",
          "definition_revision": 1, "target": {},
          "available_targets": [{"partner": "Cara", "enabled": True, "reason": ""}]}
_sent = []
with patch.object(prop_actions, "offers", lambda actor, **kw: [_offer]), \
     patch.object(prop_actions, "execute",
                  lambda actor, exact: _sent.append(exact) or {"status": "requested"}):
    _res = prop_actions._named_request("Obs", {"furniture": "Bench", "action": "Cuddle",
                                               "partner": "Moonveil"})
check("alias request reaches the bearer", [e.get("members") for e in _sent], [["Cara"]])
check("tool answer names the alias", _res.get("partner"), "Moonveil")

# ── [G] reverted ────────────────────────────────────────────────────────────
print("[G] Cara reverted")
check("revert ok", engine.revert("Cara", reason="admin"), True)
check("stamped line keeps the persona (Obs)", tc._build_recent_chat_block("Obs"),
      "  Moonveil: Silver greetings.\n  Obs: Who are you?\n  Obs: Fine.")
check("stamped line keeps the knower label (Kim)", tc._build_recent_chat_block("Kim"),
      "  Moonveil (Cara): It is me, Kim.")
say("Obs", "Cara", "user", "Cara", "Back again.", 6)
check("new message real", tc._build_recent_chat_block("Obs"),
      "  Obs: Who are you?\n  Obs: Fine.\n  Cara: Back again.")
ctx, full, _, presence = thought("Obs")
has("presence real", presence, "Cara")
check("details real", line_starts(full, "- Cara: freckled"), True)

# ── [H] phone messages are never stamped ────────────────────────────────────
print("[H] phone message")
check("transform again", engine.transform("Cara", "p1", source="smoke")["ok"], True)
_eid = chat.save_direct_message("Cara", "Obs", "Call me.")
check("direct message saved", bool(_eid), True)
from app.core.db import get_connection  # noqa: E402
_meta = json.loads(get_connection().execute(
    "SELECT metadata FROM chat_messages WHERE content='Call me.' LIMIT 1").fetchone()[0])
check("no identity stamp on a phone message", "identity" in json.dumps(_meta), False)

# ── [I] package absent ──────────────────────────────────────────────────────
print("[I] providers unregistered")
hooks.unregister_owned_providers("transformation")
check("shown_name real", identity_view.shown_name("Obs", "Cara"), "Cara")
ctx, full, _, presence = thought("Obs")
check("details real", line_starts(full, "- Cara: freckled"), True)
has("presence real", presence, "Cara")
has("no alias in presence", presence, "Moonveil", False)
_hist = chat.get_chat_history("Obs", partner_name="Cara")
_t2 = next(m for m in _hist if m["content"] == "Silver greetings.")
_label = identity_view.stamped_name("Obs", "Cara", _t2.get("metadata"))
check("stamp ignored without a provider", _label, "Cara")
has("thought present details real", full, "Cara")

print()
if FAILURES:
    print(f"FAIL — {len(FAILURES)} of {CHECKED} checks failed: {FAILURES}")
    sys.exit(1)
print(f"PASS — {CHECKED} checks")
