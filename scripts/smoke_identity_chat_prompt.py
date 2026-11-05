#!/usr/bin/env python3
"""Smoke: the chat prompt names and describes people from the RESPONDER's
view — a transformed partner / present person is the alias plus the persona
description for a non-knower, "<alias> (<name>)" with the real appearance for
a knower, and the bearer herself learns which persona she wears in the scene
state only.

Usage:  ./.venv/bin/python scripts/smoke_identity_chat_prompt.py

Throwaway storage + instance (``STORAGE_DIR``/``INSTANCE_DIR`` point at temp
dirs, ``paths.init`` runs BEFORE any world-DB module is imported). No server,
no LLM, no real world. The transformation package is loaded the way the
server loads it (``packages.enabled = "transformation"``,
``discover_packages()``); it is the provider of ``identity.*``. The builder is
``app.routes.chat._build_chat_prompt``, called directly.

FIXTURE
    Location "Inn", room "taproom": Cara (bearer of "amulet", appearance
    "freckled redhead with a crooked smile"), Kim (knower of Cara), Obs
    (knows nothing). Persona p1: item amulet, alias "Moonveil", description
    "A figure in moonlit silver.", no suit, no condition, max 0, cooldown 0.
    Cara is transformed through ``engine.transform``. Forms of address:
    Obs -> "Moonveil" = "silver one", Obs -> "Cara" = "darling" (both create
    a relationship row: neutral, strength 10, sentiment 0 -> "Known
    (closeness 10/100, feeling: neutral)"). The relationships section is the
    real one: Obs's rows are (Obs, Moonveil) and (Obs, Cara); the persona row
    reads "- Moonveil:" for the non-knower, the real-name row of a person
    who wears a persona Obs is not in on is left out while she wears it.

THE RULES (task brief) and what follows BY HAND
    The observer is the responder. shown_name(Obs, Cara) = "Moonveil",
    shown_name(Kim, Cara) = "Moonveil (Cara)"; masked_description(Obs, Cara)
    = "A figure in moonlit silver.", masked_description(Kim, Cara) = None
    (real appearance). The partner block carries the label as its name and,
    for a non-knower, the persona description as its appearance; the present
    list and present details use the label; the form of address is keyed by
    identity_key(Cara) = "Moonveil" -> "silver one". A non-knower gets no
    plugin identity line, the knower "Moonveil here is actually Cara. …", the
    bearer "You are currently Moonveil. …" — scene state only.
[A] Obs, 1:1 with Cara (partner_override, no present list, partner_mode
    "character"): "Cara" in neither system nor moment; "freckled" in neither;
    system has "Name: Moonveil" and "Appearance: A figure in moonlit silver."
[B] Obs, room mode (present Cara, Kim, Obs; Cara spoke to Obs and Kim):
    "Cara" and "freckled" in neither part; moment has
    "Others present: Moonveil, Kim."; a present-details line starting
    "- Moonveil: A figure in moonlit silver."; "Moonveil spoke to YOU
    directly"; "How you address Moonveil: silver one."; "darling" absent;
    the reply shape reads "Relationship with Moonveil:" (the (Obs, Moonveil)
    row exists through set_address); the relationships section (scene
    state, chat_moment.md) has "- Moonveil: Known (closeness 10/100" and no
    "- Cara:" anywhere.
[C] Obs, room mode, Cara spoke to Kim only (addressed_to ["Kim"]): moment
    has "Moonveil was speaking to Kim, not to you."; Kim spoke to Cara
    (partner Kim, addressed_to ["Cara"]): "Kim was speaking to Moonveil,
    not to you."; "Cara" absent in both.
[D] Kim, room mode (present Cara, Kim, Obs): moment has
    "Others present: Moonveil (Cara), Obs."; a present-details line starting
    "- Moonveil (Cara): freckled redhead"; "Moonveil here is actually Cara."
[E] Cara as responder, partner Obs, room mode: "You are currently Moonveil"
    in moment, NOT in system (cache contract).
[F] Not transformed (``engine.revert``, reason "admin"): Obs room mode -> "Others present:
    Cara, Kim."; details "- Cara: freckled redhead"; the 1:1 system prompt
    has "Name: Cara" and "Appearance: freckled redhead with a crooked smile",
    and the 1:1 moment's relationships section lists both rows: "- Cara: Known" and
    "- Moonveil: Known" (nobody wears the persona: the bare alias).
[G] person_description without observer (image prompts) keeps the real
    appearance while Cara is transformed: contains "freckled"; with
    observer "Obs" it starts "A figure in moonlit silver." and has no
    "freckled".
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="identity-chat-prompt-smoke-"))
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
    check(label, needle in text, expected)


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
        assert save_character_profile(_name, _p)

inventory.add_item("Amulet", item_id="amulet")
assert inventory.add_to_inventory("Cara", "amulet")

from app.models.relationship import set_address  # noqa: E402
assert set_address("Obs", "Moonveil", "silver one")
assert set_address("Obs", "Cara", "darling")

from app.plugins import loader, registry  # noqa: E402
loader.discover_packages()
check("package loaded", "transformation" in {p.id for p in registry.packages()}, True)

from app.core import identity_view  # noqa: E402
from app.core.prompt_builder import person_description  # noqa: E402
from app.routes.chat import _build_chat_prompt  # noqa: E402
from plugins.transformation import engine, knowers  # noqa: E402

engine.tick()
check("Kim made a knower", knowers.add("Kim", "Cara", "p1"), True)
check("transform ok", engine.transform("Cara", "p1", source="smoke"),
      {"ok": True, "reason": "", "alias": "Moonveil"})
check("Obs sees the alias", identity_view.shown_name("Obs", "Cara"), "Moonveil")
check("Kim sees both", identity_view.shown_name("Kim", "Cara"), "Moonveil (Cara)")

PRESENT = ["Cara", "Kim", "Obs"]


def one_on_one(responder, partner):
    p = _build_chat_prompt(responder, "", "", partner_override=partner)
    return p.system, p.moment


def room(responder, partner, addressed_to):
    p = _build_chat_prompt(responder, "", "", partner_override=partner,
                           present_characters=PRESENT, addressed_to=addressed_to,
                           incoming_text="Hello there.")
    return p.system, p.moment


def detail_line(moment, prefix):
    return any(line.startswith(prefix) for line in moment.splitlines())


# ── [A] non-knower, 1:1 ─────────────────────────────────────────────────────
print("[A] Obs 1:1 with transformed Cara")
_sys, _mom = one_on_one("Obs", "Cara")
has("no real name", _sys + _mom, "Cara", False)
has("no real appearance", _sys + _mom, "freckled", False)
has("partner block name", _sys, "Name: Moonveil")
has("partner block appearance", _sys, "Appearance: A figure in moonlit silver.")

# ── [B] non-knower, room mode ───────────────────────────────────────────────
print("[B] Obs in the room, Cara spoke to Obs and Kim")
_sys, _mom = room("Obs", "Cara", ["Obs", "Kim"])
has("no real name", _sys + _mom, "Cara", False)
has("no real appearance", _sys + _mom, "freckled", False)
has("present list", _mom, "Others present: Moonveil, Kim.")
check("present details line", detail_line(_mom, "- Moonveil: A figure in moonlit silver."), True)
has("partner named by alias", _mom, "Moonveil spoke to YOU directly")
has("address keyed by identity", _mom, "How you address Moonveil: silver one.")
has("real-name address absent", _mom, "darling", False)
has("reply shape names the alias", _mom, "Relationship with Moonveil:")
has("relationships: persona row", _mom, "- Moonveil: Known (closeness 10/100")
has("relationships: no real-name row", _sys + _mom, "- Cara:", False)

# ── [C] addressed names ─────────────────────────────────────────────────────
print("[C] Obs overhears")
_sys, _mom = room("Obs", "Cara", ["Kim"])
has("overheard partner", _mom, "Moonveil was speaking to Kim, not to you.")
has("no real name", _sys + _mom, "Cara", False)
_sys, _mom = room("Obs", "Kim", ["Cara"])
has("addressee by alias", _mom, "Kim was speaking to Moonveil, not to you.")
has("no real name", _sys + _mom, "Cara", False)

# ── [D] knower ──────────────────────────────────────────────────────────────
print("[D] Kim in the room")
_sys, _mom = room("Kim", "Obs", ["Kim"])
has("present list", _mom, "Others present: Moonveil (Cara), Obs.")
check("present details real appearance",
      detail_line(_mom, "- Moonveil (Cara): freckled redhead"), True)
has("plugin knower line", _mom, "Moonveil here is actually Cara.")

# ── [E] bearer ──────────────────────────────────────────────────────────────
print("[E] Cara answers Obs")
_sys, _mom = room("Cara", "Obs", ["Cara"])
has("bearer line in moment", _mom, "You are currently Moonveil")
has("bearer line not in system", _sys, "You are currently Moonveil", False)

# ── [G] person_description ──────────────────────────────────────────────────
print("[G] person_description")
has("image prompt keeps real appearance", person_description("Cara"), "freckled")
_masked = person_description("Cara", include_outfit=True, observer="Obs")
check("observer view starts with persona", _masked.startswith("A figure in moonlit silver."), True)
has("observer view hides appearance", _masked, "freckled", False)
has("knower view real", person_description("Cara", observer="Kim"), "freckled")

# ── [F] reverted ────────────────────────────────────────────────────────────
print("[F] Cara reverted")
check("revert ok", engine.revert("Cara", reason="admin"), True)
_sys, _mom = room("Obs", "Cara", ["Obs"])
has("present list real", _mom, "Others present: Cara, Kim.")
check("details real", detail_line(_mom, "- Cara: freckled redhead"), True)
_sys, _mom = one_on_one("Obs", "Cara")
has("1:1 name real", _sys, "Name: Cara")
has("1:1 appearance real", _sys, f"Appearance: {APPEARANCE}")
has("relationships: real-name row back", _mom, "- Cara: Known")
has("relationships: persona row stays", _mom, "- Moonveil: Known")

print()
if FAILURES:
    print(f"FAIL — {len(FAILURES)} of {CHECKED} checks failed: {FAILURES}")
    sys.exit(1)
print(f"PASS — {CHECKED} checks")
