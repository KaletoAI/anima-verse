#!/usr/bin/env python3
"""Smoke: a persona is a person of its own for relationships and memories,
and a shared scene summary is written in the PUBLIC view.

Usage:  ./.venv/bin/python scripts/smoke_identity_relations_memory.py

Throwaway storage + instance (``STORAGE_DIR``/``INSTANCE_DIR`` point at temp
dirs, ``paths.init`` runs BEFORE any world-DB module is imported). No server,
no real LLM (``app.core.llm_router.llm_call`` is replaced by a recorder that
answers canned JSON / a canned summary), no real world. The transformation
package is loaded the way the server loads it (``packages.enabled =
"transformation"``, ``discover_packages()``); it provides ``identity.*``.

FIXTURE
    Location "Inn", room "taproom": Cara (bearer of "amulet"), Kim (knower of
    Cara), Obs (knows nothing), Ava (the avatar's character; knows nothing).
    Persona p1: item amulet, alias "Moonveil", no suit, max 0, cooldown 0.

THE RULES (task brief) and the arithmetic, BY HAND
    record_interaction keys BOTH sides by identity_key (the alias while
    transformed). A fresh pair starts at strength 10; ``strength_delta`` adds
    to it (sentiment deltas 0 -> no reduction); classify_type with sentiment
    0 and strength < 15 -> "neutral" -> label "Known", feeling "neutral".
    Before the transform: Obs->Cara (+2) -> (Obs, Cara) 12; Cara->Ava (+2) ->
    (Ava, Cara) 12. Transformed: Obs->Cara (+3) -> (Obs, Moonveil) 13;
    Kim->Cara (+3) -> (Kim, Moonveil) 13; Cara->Ava (+4) -> (Ava, Moonveil) 14.
[A] rows: (Obs, Moonveil) strength 13, count 1, history initiator "Obs";
    (Obs, Cara) unchanged at 12, count 1; (Kim, Moonveil) 13;
    (Ava, Moonveil) 14; (Ava, Cara) unchanged at 12. A self-pair through the
    alias (Cara -> Cara) records nothing.
[B] relationship section (transformed):
    Obs: "- Moonveil: Known (closeness 13/100, feeling: neutral)"; no "Cara"
    at all (the real-name row of a person in a persona Obs is not in on is
    left out). Kim: "- Moonveil (Cara): Known (closeness 13/100". Cara (her
    persona's rows): "- Obs: Known (closeness 13/100", "- Kim: Known
    (closeness 13/100", "- Ava: Known (closeness 14/100"; "closeness 12/100"
    absent (her own rows wait).
[C] /play/others relation map of Ava: {"Cara": strength 14} — the
    (Ava, Moonveil) row, under the real name the caller looks up; no
    "Moonveil" key. Mind panel of Obs lists the partners {"Cara", "Moonveil"}
    (a persona row passes the ghost filter).
[D] memory extraction (llm_call recorded):
    exchange Obs <- Cara ("Hello.", "Hi there."), the model names nobody:
    related_character = identity_key(Cara) = "Moonveil"; the rendered prompt
    says "Moonveil:" and never "Cara". Kim's model answers related_character
    "Moonveil (Cara)" (a knower's label) -> stored "Moonveil". A thought of
    Obs (monologue): "Who was really in the room" lists the alias, no "Cara".
[E] memory section: Obs memory related "Moonveil" -> "(about Moonveil)";
    Kim memory related "Moonveil" -> "(about Moonveil (Cara))".
[F] scene consolidation with Cara transformed throughout: utterances
    Cara "Good evening." (to Obs), Storyteller "Cara lifts a lantern."
    (anchor Cara), Obs "Hello there." -> the consolidation_scene prompt has
    "Moonveil: Good evening.", "Storyteller: Moonveil lifts a lantern.",
    "Obs: Hello there.", "Participants: Moonveil, Obs." and no "Cara"; the
    scene row keeps the REAL participants (Cara gets the episodic memory).
[G] reverted (engine.revert): Cara's section shows her own rows
    "- Obs: Known (closeness 12/100", "- Ava: Known (closeness 12/100", no
    "closeness 14/100"; Obs's section shows both "- Cara: Known (closeness
    12/100" and "- Moonveil: Known (closeness 13/100"; Kim's persona row is the
    bare alias "- Moonveil: Known" (nobody wears it); Ava's relation map gives
    "Cara" strength 12.
[H] package absent (providers unregistered): Obs->Cara (+2) lands on
    (Obs, Cara) -> 14; a scene line whose utterance still carries the stale
    identity snapshot {"Cara": "Moonveil"} is transcribed "Cara: ..." —
    real names everywhere.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="identity-relations-smoke-"))
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
embedding.embed = lambda text: None

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
    check(label, needle in (text or ""), expected)


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

for _name in ("Cara", "Kim", "Obs", "Ava"):
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

from app.core import hooks, identity_view, llm_router  # noqa: E402
from app.core import scene_manager  # noqa: E402
from app.core.character_ops import build_memory_relationships  # noqa: E402
from app.core.memory_service import extract_memories_from_exchange  # noqa: E402
from app.core.perception import STORYTELLER_SPEAKER, record_utterance  # noqa: E402
from app.core.world_ops import build_relation_map  # noqa: E402
from app.core.db import get_connection, transaction  # noqa: E402
from app.models import scene_store  # noqa: E402
from app.models.memory import add_memory, build_memory_prompt_section, load_memories  # noqa: E402
from app.models.relationship import (build_relationship_prompt_section,  # noqa: E402
                                     get_relationship, record_interaction)
from plugins.transformation import engine, knowers  # noqa: E402

CALLS = []
ANSWERS = []


def fake_llm_call(*, task, system_prompt, user_prompt, **kw):
    CALLS.append({"task": task, "system": system_prompt, "user": user_prompt})
    return SimpleNamespace(content=ANSWERS.pop(0) if ANSWERS else "")


llm_router.llm_call = fake_llm_call


def strength(a, b):
    rel = get_relationship(a, b)
    return None if rel is None else rel.get("strength")


# ── before the transform ────────────────────────────────────────────────────
record_interaction("Obs", "Cara", "talkto", strength_delta=2)
record_interaction("Cara", "Ava", "talkto", strength_delta=2)
check("pre: (Obs, Cara) 12", strength("Obs", "Cara"), 12)
check("pre: (Ava, Cara) 12", strength("Ava", "Cara"), 12)

engine.tick()
check("Kim made a knower", knowers.add("Kim", "Cara", "p1"), True)
check("transform ok", engine.transform("Cara", "p1", source="smoke"),
      {"ok": True, "reason": "", "alias": "Moonveil"})

# ── [A] rows keyed by identity ──────────────────────────────────────────────
print("[A] record_interaction keys the persona")
record_interaction("Obs", "Cara", "talkto", strength_delta=3)
record_interaction("Kim", "Cara", "talkto", strength_delta=3)
record_interaction("Cara", "Ava", "talkto", strength_delta=4)
_r = get_relationship("Obs", "Moonveil") or {}
check("(Obs, Moonveil) strength", _r.get("strength"), 13)
check("(Obs, Moonveil) count", _r.get("interaction_count"), 1)
check("(Obs, Moonveil) initiator", [h.get("initiator") for h in _r.get("history", [])], ["Obs"])
check("(Obs, Cara) unchanged", strength("Obs", "Cara"), 12)
check("(Obs, Cara) count unchanged", (get_relationship("Obs", "Cara") or {}).get("interaction_count"), 1)
check("(Kim, Moonveil) strength", strength("Kim", "Moonveil"), 13)
check("(Ava, Moonveil) strength", strength("Ava", "Moonveil"), 14)
check("(Ava, Cara) unchanged", strength("Ava", "Cara"), 12)
check("no self-pair through the alias", record_interaction("Cara", "Moonveil", "talkto"), {})
check("no (Cara, Moonveil) row", get_relationship("Cara", "Moonveil"), None)

# ── [B] relationship sections ───────────────────────────────────────────────
print("[B] relationship sections while transformed")
_obs = build_relationship_prompt_section("Obs")
has("Obs persona row", _obs, "- Moonveil: Known (closeness 13/100, feeling: neutral)")
has("Obs no real name", _obs, "Cara", False)
_kim = build_relationship_prompt_section("Kim")
has("Kim knower label", _kim, "- Moonveil (Cara): Known (closeness 13/100")
_cara = build_relationship_prompt_section("Cara")
has("Cara persona rows: Obs", _cara, "- Obs: Known (closeness 13/100")
has("Cara persona rows: Kim", _cara, "- Kim: Known (closeness 13/100")
has("Cara persona rows: Ava", _cara, "- Ava: Known (closeness 14/100")
has("Cara own rows wait", _cara, "closeness 12/100", False)

# ── [C] relation map + Mind panel ───────────────────────────────────────────
print("[C] relation map and Mind panel")
_map = build_relation_map("Ava")
check("Ava map: Cara from the persona row", (_map.get("Cara") or {}).get("strength"), 14)
check("Ava map: no alias key", "Moonveil" in _map, False)
_mind = {it["partner"] for it in build_memory_relationships("Obs")["items"]}
check("Obs Mind panel partners", _mind, {"Cara", "Moonveil"})

# ── [D] memory extraction ───────────────────────────────────────────────────
print("[D] memory extraction")
CALLS.clear()
ANSWERS[:] = [json.dumps({"memories": [{"memory_type": "semantic",
                                        "content": "Moonveil greeted Obs.",
                                        "importance": 3, "tags": []}]})]
_got = extract_memories_from_exchange("Obs", "Cara", "Hello.", "Hi there.", None, plans=False)
check("Obs related = identity key", [m.get("related_character") for m in _got], ["Moonveil"])
_prompt = CALLS[-1]["system"] + CALLS[-1]["user"] if CALLS else ""
has("exchange prompt names the alias", _prompt, 'Moonveil: "Hello."')
has("exchange prompt hides the name", _prompt, "Cara", False)
ANSWERS[:] = [json.dumps({"memories": [{"memory_type": "semantic",
                                        "content": "Moonveil is Cara in disguise.",
                                        "related_character": "Moonveil (Cara)",
                                        "importance": 3, "tags": []}]})]
_got = extract_memories_from_exchange("Kim", "Cara", "Hello.", "Hi there.", None, plans=False)
check("Kim label stored as key", [m.get("related_character") for m in _got], ["Moonveil"])
CALLS.clear()
ANSWERS[:] = [json.dumps({"memories": []})]
extract_memories_from_exchange("Obs", "", "", "The silver figure smiled at me.", None, plans=False)
_prompt = CALLS[-1]["system"] + CALLS[-1]["user"] if CALLS else ""
has("thought prompt lists the alias as present", _prompt, "Moonveil")
has("thought prompt hides the name", _prompt, "Cara", False)

# ── [E] memory section ──────────────────────────────────────────────────────
print("[E] memory section labels")
add_memory("Obs", "Moonveil smiled.", memory_type="semantic", related_character="Moonveil")
add_memory("Kim", "Moonveil waved.", memory_type="semantic", related_character="Moonveil")
has("Obs memory about the alias", build_memory_prompt_section("Obs"), "(about Moonveil) ")
has("Kim memory about the knower label", build_memory_prompt_section("Kim"),
    "(about Moonveil (Cara)) ")

# ── [F] scene consolidation, public view ────────────────────────────────────
print("[F] scene consolidation")
record_utterance(speaker="Cara", content="Good evening.", addressees=["Obs"],
                 location_id=INN, room_id=ROOM)
record_utterance(speaker=STORYTELLER_SPEAKER, content="Cara lifts a lantern.",
                 location_id=INN, room_id=ROOM, anchor="Cara")
record_utterance(speaker="Obs", content="Hello there.", addressees=["Cara"],
                 location_id=INN, room_id=ROOM)
_scenes = scene_store.get_idle_open_scenes("9999")
check("one open scene", len(_scenes), 1)
_scene = _scenes[0] if _scenes else {}
check("stored participants stay real",
      [p for p in _scene.get("participants", []) if p != STORYTELLER_SPEAKER], ["Cara", "Obs"])
CALLS.clear()
ANSWERS[:] = ["Moonveil greeted Obs in the taproom."]
_before = len(load_memories("Cara"))
scene_manager.consolidate_scene(_scene)
_sum = next((c for c in CALLS if "Scene transcript" in c["user"]), {"user": ""})["user"]
has("transcript: persona speaker", _sum, "Moonveil: Good evening.")
has("transcript: storyteller rewritten", _sum, f"{STORYTELLER_SPEAKER}: Moonveil lifts a lantern.")
has("transcript: Obs", _sum, "Obs: Hello there.")
has("participants: public labels", _sum, "Participants: Moonveil, Obs.")
has("summary input hides the name", _sum, "Cara", False)
check("Cara got the episodic memory", len(load_memories("Cara")) - _before, 1)

# ── [G] reverted ────────────────────────────────────────────────────────────
print("[G] reverted")
check("revert ok", engine.revert("Cara", reason="admin"), True)
_cara = build_relationship_prompt_section("Cara")
has("Cara own rows: Obs", _cara, "- Obs: Known (closeness 12/100")
has("Cara own rows: Ava", _cara, "- Ava: Known (closeness 12/100")
has("Cara persona rows gone", _cara, "closeness 14/100", False)
_obs = build_relationship_prompt_section("Obs")
has("Obs real row back", _obs, "- Cara: Known (closeness 12/100")
has("Obs persona row stays", _obs, "- Moonveil: Known (closeness 13/100")
has("Kim bare alias (nobody wears it)", build_relationship_prompt_section("Kim"),
    "- Moonveil: Known (closeness 13/100")
check("Ava map: real row", (build_relation_map("Ava").get("Cara") or {}).get("strength"), 12)

# ── [H] package absent ──────────────────────────────────────────────────────
print("[H] providers unregistered")
check("transform again", engine.transform("Cara", "p1", source="smoke")["ok"], True)
hooks.unregister_owned_providers("transformation")
check("no persona without provider", identity_view.active_persona("Cara"), None)
record_interaction("Obs", "Cara", "talkto", strength_delta=2)
check("(Obs, Cara) gets it", strength("Obs", "Cara"), 14)
check("(Obs, Moonveil) untouched", strength("Obs", "Moonveil"), 13)
_uid = record_utterance(speaker="Cara", content="Still here.", addressees=["Obs"],
                        location_id=INN, room_id=ROOM)
with transaction() as _conn:
    _conn.execute("UPDATE utterances SET meta=json_set(meta, '$.identity', json(?)) WHERE id=?",
                  (json.dumps({"Cara": "Moonveil"}), _uid))
check("stale snapshot stored",
      json.loads(get_connection().execute("SELECT meta FROM utterances WHERE id=?",
                                          (_uid,)).fetchone()[0]).get("identity"),
      {"Cara": "Moonveil"})
_scene = (scene_store.get_idle_open_scenes("9999") or [{}])[0]
CALLS.clear()
ANSWERS[:] = ["Cara was still there."]
scene_manager.consolidate_scene(_scene)
_sum = next((c for c in CALLS if "Scene transcript" in c["user"]), {"user": ""})["user"]
has("transcript real without provider", _sum, "Cara: Still here.")
has("no alias without provider", _sum, "Moonveil", False)

print()
if FAILURES:
    print(f"FAIL — {len(FAILURES)} of {CHECKED} checks failed: {FAILURES}")
    sys.exit(1)
print(f"PASS — {CHECKED} checks")
