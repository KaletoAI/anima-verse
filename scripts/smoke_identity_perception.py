#!/usr/bin/env python3
"""Smoke: the perception stream is observer-relative — every perceiver row of
``perception.record_utterance`` carries that perceiver's view of the speaker
and the addressees, and storyteller text names a transformed character the
way the perceiver sees her.

Usage:  ./.venv/bin/python scripts/smoke_identity_perception.py

Throwaway storage + instance (``STORAGE_DIR``/``INSTANCE_DIR`` point at temp
dirs, ``paths.init`` runs BEFORE any world-DB module is imported). No server,
no LLM, no real world. The transformation package is loaded the way the
server loads it (``packages.enabled = "transformation"``,
``discover_packages()``); it is the provider of ``identity.*``.

FIXTURE
    Location "Inn", room "taproom": Cara (bearer of "amulet"), Kim (knower of
    Cara), Obs (knows nothing). Persona p1: item amulet, alias "Moonveil",
    no suit, no condition, max 0 (until reverted), cooldown 0. Game clock
    pinned. Cara is transformed through ``engine.transform`` before [A].

THE RULES (task brief) and what follows BY HAND
    shown_name(O, Cara): Obs -> "Moonveil", Kim -> "Moonveil (Cara)",
    Cara herself -> "Cara". ``meta.speaker`` / ``meta.addressees`` stay REAL;
    ``speaker_shown`` / ``addressees_shown`` are written only where they
    differ from the real value. The utterance meta carries
    ``identity = {subject: alias}`` for the speaker, the addressees, the
    anchor and everyone who perceives the line — here {"Cara": "Moonveil"}
    whenever Cara is among them. Storyteller content is rewritten per
    perceiver (whole word, case-sensitive); a character's speech never is.
[A] Cara says "hello":
    Obs row speaker_shown "Moonveil", Kim row "Moonveil (Cara)", both rows
    meta.speaker "Cara"; Cara's own row has no speaker_shown; utterance meta
    identity {"Cara": "Moonveil"}.
[B] Obs says "hi" to Cara (addressees ["Cara"]):
    Kim row addressees ["Cara"], addressees_shown ["Moonveil (Cara)"];
    Obs's own row addressees_shown ["Moonveil"]; Cara's row has no
    addressees_shown (she sees herself); no row has speaker_shown (Obs wears
    no persona).
[C] movement line masked — storyteller "Cara leaves the hall." anchored on
    Cara: Obs content "Moonveil leaves the hall.", Kim "Moonveil (Cara)
    leaves the hall.", Cara "Cara leaves the hall."; the canonical utterance
    content stays "Cara leaves the hall." (public view = Task 10).
[D] Kim says "Cara is brave": Obs content "Cara is brave" (speech is never
    rewritten), Kim's own row is unchanged too.
[E] Renderers over Obs's room stream (oldest first; the transform line of the
    engine is private to Cara + Kim, Obs has none):
    _messages_from_room_stream("Obs") ==
      user "Moonveil: hello", assistant "hi",
      user "Storyteller: Moonveil leaves the hall.", user "Kim: Cara is brave".
    For Kim: contains user "Moonveil (Cara): hello" and
      "Obs (to Moonveil (Cara)): hi". For Cara: contains "Obs (to you): hi".
    npc_actions._recent_conversation("Obs") skips source "movement" rows,
      so its speakers == ["Moonveil", "Obs", "Kim"].
    scene_photo._room_transcript("Obs", Inn, taproom) contains
      "Moonveil: hello" and not "Cara: hello".
[F] Package not loaded — ``unregister_owned_providers("transformation")``:
    Cara says "bye" -> Obs row has no speaker_shown, utterance meta has no
    identity; storyteller "Cara sits down." -> Obs content unchanged; the
    renderer prints "Cara: bye".
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="identity-perception-smoke-"))
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
}), encoding="utf-8")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(ROOT / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

# The personas live in the package's own table (Characters → Skills panel).
from plugins.transformation import store as tstore  # noqa: E402
tstore.ensure_schema()
for _p in PERSONAS:
    tstore.create_definition({k: v for k, v in _p.items() if k != "id"}, persona_id=_p["id"])

from app.core import embedding  # noqa: E402
embedding.embed = lambda text: None   # no model: the catalog default answers

from app.core.db import get_connection  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models import inventory, perception_store  # noqa: E402
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
        assert save_character_profile(_name, _p)

inventory.add_item("Amulet", item_id="amulet")
assert inventory.add_to_inventory("Cara", "amulet")

from app.plugins import loader, registry  # noqa: E402
loader.discover_packages()
check("package loaded", "transformation" in {p.id for p in registry.packages()}, True)

from app.core import hooks, identity_view, perception  # noqa: E402
from app.core.chat_engine import _messages_from_room_stream  # noqa: E402
from app.core.npc_actions import _recent_conversation  # noqa: E402
from app.core.scene_photo import _room_transcript  # noqa: E402
from plugins.transformation import engine, knowers  # noqa: E402

engine.tick()
check("Kim made a knower", knowers.add("Kim", "Cara", "p1"), True)
check("transform ok", engine.transform("Cara", "p1", source="smoke"),
      {"ok": True, "reason": "", "alias": "Moonveil"})
check("Obs sees the alias", identity_view.shown_name("Obs", "Cara"), "Moonveil")
check("Kim sees both", identity_view.shown_name("Kim", "Cara"), "Moonveil (Cara)")


def say(speaker, content, addressees=None, **kw):
    uid = perception.record_utterance(speaker=speaker, content=content,
                                      addressees=addressees, location_id=INN,
                                      room_id=ROOM, **kw)
    assert uid, (speaker, content)
    return uid


def rows_of(uid):
    """{perceiver: {"content", "meta"}} of one utterance."""
    conn = get_connection()
    out = {}
    for perceiver, content, meta in conn.execute(
            "SELECT perceiver, content, meta FROM perceptions WHERE utterance_id=?", (uid,)):
        out[perceiver] = {"content": content, "meta": json.loads(meta or "{}")}
    return out


def utterance(uid):
    row = get_connection().execute(
        "SELECT content, meta FROM utterances WHERE id=?", (uid,)).fetchone()
    return row[0], json.loads(row[1] or "{}")


def stream(name):
    return perception_store.get_character_room_stream(name, INN, ROOM, 100)


# ── [A] the bearer speaks ───────────────────────────────────────────────────
print("[A] Cara says hello")
_uid = say("Cara", "hello")
_rows = rows_of(_uid)
check("perceivers", sorted(_rows), ["Cara", "Kim", "Obs"])
check("Obs speaker_shown", _rows["Obs"]["meta"].get("speaker_shown"), "Moonveil")
check("Kim speaker_shown", _rows["Kim"]["meta"].get("speaker_shown"), "Moonveil (Cara)")
check("Obs meta.speaker stays real", _rows["Obs"]["meta"].get("speaker"), "Cara")
check("Kim meta.speaker stays real", _rows["Kim"]["meta"].get("speaker"), "Cara")
check("Cara's own row has no speaker_shown", "speaker_shown" in _rows["Cara"]["meta"], False)
check("Obs content is the speech", _rows["Obs"]["content"], "hello")
check("utterance identity snapshot", utterance(_uid)[1].get("identity"), {"Cara": "Moonveil"})

# ── [B] someone speaks TO the bearer ────────────────────────────────────────
print("[B] Obs says hi to Cara")
_uid = say("Obs", "hi", addressees=["Cara"])
_rows = rows_of(_uid)
check("Kim addressees stay real", _rows["Kim"]["meta"].get("addressees"), ["Cara"])
check("Kim addressees_shown", _rows["Kim"]["meta"].get("addressees_shown"), ["Moonveil (Cara)"])
check("Obs own row addressees_shown", _rows["Obs"]["meta"].get("addressees_shown"), ["Moonveil"])
check("Cara's row has no addressees_shown", "addressees_shown" in _rows["Cara"]["meta"], False)
check("no row has speaker_shown",
      [p for p, r in _rows.items() if "speaker_shown" in r["meta"]], [])
check("utterance identity snapshot (addressee)", utterance(_uid)[1].get("identity"),
      {"Cara": "Moonveil"})

# ── [C] storyteller text ────────────────────────────────────────────────────
print("[C] storyteller line")
_uid = say(perception.STORYTELLER_SPEAKER, "Cara leaves the hall.", source="movement",
           anchor="Cara")
_rows = rows_of(_uid)
check("movement line masked", _rows.get("Obs", {}).get("content"), "Moonveil leaves the hall.")
check("knower reads both names", _rows.get("Kim", {}).get("content"),
      "Moonveil (Cara) leaves the hall.")
check("bearer reads her own name", _rows.get("Cara", {}).get("content"), "Cara leaves the hall.")
check("canonical content untouched", utterance(_uid)[0], "Cara leaves the hall.")
check("storyteller meta.speaker", _rows.get("Obs", {}).get("meta", {}).get("speaker"),
      perception.STORYTELLER_SPEAKER)

# ── [D] speech is never rewritten ───────────────────────────────────────────
print("[D] Kim says 'Cara is brave'")
_uid = say("Kim", "Cara is brave")
_rows = rows_of(_uid)
check("Obs content unchanged", _rows["Obs"]["content"], "Cara is brave")
check("Kim own content unchanged", _rows["Kim"]["content"], "Cara is brave")

# ── [E] renderers ───────────────────────────────────────────────────────────
print("[E] renderers")
check("Obs transcript", _messages_from_room_stream("Obs", stream("Obs")), [
    {"role": "user", "content": "Moonveil: hello"},
    {"role": "assistant", "content": "hi"},
    {"role": "user", "content": "Storyteller: Moonveil leaves the hall."},
    {"role": "user", "content": "Kim: Cara is brave"},
])
_kim = [m["content"] for m in _messages_from_room_stream("Kim", stream("Kim"))]
check("Kim transcript names the alias with the name", "Moonveil (Cara): hello" in _kim, True)
check("Kim transcript addressee shown", "Obs (to Moonveil (Cara)): hi" in _kim, True)
_cara = [m["content"] for m in _messages_from_room_stream("Cara", stream("Cara"))]
check("Cara transcript says 'you'", "Obs (to you): hi" in _cara, True)
check("npc recent conversation speakers", [r["speaker"] for r in _recent_conversation("Obs")],
      ["Moonveil", "Obs", "Kim"])
_photo = _room_transcript("Obs", INN, ROOM)
check("photo transcript names the alias", "Moonveil: hello" in _photo, True)
check("photo transcript hides the name", "Cara: hello" in _photo, False)

# ── [F] package absent ──────────────────────────────────────────────────────
print("[F] providers unregistered")
hooks.unregister_owned_providers("transformation")
check("no persona without provider", identity_view.active_persona("Cara"), None)
_uid = say("Cara", "bye")
_rows = rows_of(_uid)
check("Obs row has no speaker_shown", "speaker_shown" in _rows["Obs"]["meta"], False)
check("utterance has no identity", "identity" in utterance(_uid)[1], False)
_uid = say(perception.STORYTELLER_SPEAKER, "Cara sits down.", anchor="Cara")
check("storyteller line real", rows_of(_uid).get("Obs", {}).get("content"), "Cara sits down.")
check("renderer prints the real name",
      {"role": "user", "content": "Cara: bye"} in _messages_from_room_stream("Obs", stream("Obs")),
      True)

print()
print(f"{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAIL:", ", ".join(FAILURES))
    sys.exit(1)
print("PASS")
