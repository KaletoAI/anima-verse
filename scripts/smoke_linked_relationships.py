#!/usr/bin/env python3
"""Smoke: linked characters — the relationship split (ruling R1, task 6).

Usage:  ./.venv/bin/python scripts/smoke_linked_relationships.py

Throwaway storage + instance (``STORAGE_DIR`` / ``INSTANCE_DIR`` temp dirs,
``paths.init`` BEFORE any world-DB module), no server, no LLM.

THE SPEC (docs/superpowers/specs/2026-11-05-linked-characters-design.md,
ruling R1 + the Relationship rows of "The decided split"):
  * the LEADER row (leader, X) carries the mind's own side: leader->X
    sentiment and the leader's form of address toward X. A body's interaction
    with X writes the body's OUTGOING delta to that direction and touches the
    leader row's ``last_interaction_game`` — nothing else on it;
  * everything else goes to the BODY row (body, X): X->body sentiment,
    strength, interaction_count, history, romantic_tension; the body->X field
    is never written (stays 0) and never read: ``classify_type`` of a body row
    uses ``own_sentiment(body, X)`` (the leader value);
  * the prompt section of ANY family member lists the union of the family's
    partners: the own feeling (leader row) and per body row "as <body>:
    type, closeness, their view of you";
  * Game-Admin -> Relationships on a body shows the body row; its own
    direction shows and edits the leader value, marked "from <leader>".
Session decisions: members of ONE family never get a row (record_interaction
and set_address are no-ops between them); ``own_sentiment(speaker, other)``
maps only the speaker to its mind. Implementation detail checked here: a
leader row that only exists because a body acted is marked ``mind_only`` with
the mind's name — it is the mind's side alone, so X's own views (prompt, Mind
panel, relation map) do not list the leader as somebody X has met.

ORIENTATION (``_sort_pair`` lower-cases): (Glut, Luna) a=Glut; (Luna, Tilda)
a=Luna, so Tilda->Luna is ``sentiment_b_to_a``; (Obs, Tilda) a=Obs;
(Ember, Glut) a=Ember; (Ember, Tilda) a=Ember; (Glut, Hans) a=Glut.

FIXTURE
    Location "Inn" (room taproom). Tilda, Luna, Obs, Hans (human-roleplay) in
    Inn/taproom. create_linked(Tilda, "Glut"), swap_presence(Tilda, Glut)
    -> Tilda DORMANT. create_linked(Hans, "Ember") -> Ember dormant. Game
    clock set to Y0001-D020T12:00:00 (the decay step [I] needs a past).

WHAT FOLLOWS BY HAND
[A] record_interaction(Glut, Luna, talkto, delta_a 0.3, delta_b 0.2,
    strength 2, romantic 0.1):
    leader row (Luna, Tilda) created: Tilda->Luna (b_to_a) 0.3, Luna->Tilda
    0.0, strength 10, interaction_count 0, history [], type neutral, tension
    0, mind_only ["Tilda"], last_interaction_game set.
    body row (Glut, Luna): Glut->Luna (a_to_b) 0.0, Luna->Glut 0.2, strength
    10 + 2 = 12 (avg delta 0.25 is not negative), count 1, one history entry
    (initiator Glut, sentiment_delta 0.25), tension 0.1, type: strength 12
    < 15 -> neutral.
[B] Raw preset: leader row Tilda->Luna := -0.8 and its
    last_interaction_game := "Y0001-D001T00:00:00";
    update_relationship_manual(Glut, Luna, strength 45).
    record_interaction(Luna, Glut, talkto, delta_a 0.1 (Luna->Glut), delta_b
    0.1 (Glut's own -> leader), strength 2):
    leader: Tilda->Luna = -0.8 + 0.1 = -0.7, last_interaction_game now >
    "Y0001-D001T00:00:00" (= the clock, D020), strength 10, count 0, history
    [] (untouched); body: strength 47, Luna->Glut 0.3, Glut->Luna 0.0,
    count 2; type = classify_type(47, own -0.7, 0.3, 0.1): avg -0.2 <= -0.1
    and strength >= 20 -> "rival" (the stored body->X 0.0 would give avg
    0.15 -> "acquaintance"; the old code, writing 0.4 there, "friend").
    own_sentiment: (Glut, Luna) -0.7, (Tilda, Luna) -0.7, (Luna, Glut) 0.3,
    (Luna, Tilda) 0.0.
[C] Same family: record_interaction(Glut, Tilda, ...) -> {} and no row;
    set_address(Glut, Tilda, "x") and set_address(Tilda, Glut, "x") -> False;
    own_sentiment(Glut, Tilda) 0.0.
[D] Addresses: set_address(Glut, Luna, "informal, calls her Moon") lands on
    the leader row's Tilda->Luna (address_b_to_a), body row has no
    address_a_to_b; get_address(Glut, Luna) == get_address(Tilda, Luna) ==
    that text. set_address(Luna, Glut, "calls him Sparks") lands on the body
    row (address_b_to_a, Luna is b), leader row has no address_a_to_b;
    get_address(Luna, Tilda) "".
[E] Obs meets Tilda in person: record_interaction(Tilda, Obs, talkto, 0.4,
    0.5, strength 2) -> row (Obs, Tilda) Tilda->Obs 0.4, Obs->Tilda 0.5,
    strength 12, type neutral ("Known"), no mind_only.
[F] Two bodies of two families: record_interaction(Glut, Ember, talkto, 0.2,
    -0.4, strength 1) -> (Ember, Tilda) Tilda->Ember 0.2 mind_only ["Tilda"];
    (Glut, Hans) Hans->Glut -0.4 mind_only ["Hans"]; body row (Ember, Glut):
    both sentiments 0.0; avg delta (0.2 - 0.4)/2 = -0.1 < -0.01 -> effective
    strength delta min(1, -0.1 * 10) = -1.0 -> strength 9, count 1;
    own_sentiment(Ember, Glut) -0.4, (Glut, Ember) 0.2.
[G] Prompts. Family union, identical for Tilda and Glut; partners by best
    visible strength: Luna 47 (body row), Obs 12 (Tilda row), Ember 9 (Glut
    row); (Glut, Hans) is Hans's mind_only row -> hidden. Lines:
      "- Luna (feeling: very negative)"            (-0.7, no own meeting)
      "  - as Glut: Rival (closeness 47/100), their view of you: positive"
      "- Obs: Known (closeness 12/100, feeling: positive)"   (0.4)
      "- Ember (feeling: positive)"                 (0.2)
      "  - as Glut: Known (closeness 9/100), their view of you: neutral"
    Luna (unlinked, today's format): only "- Glut: Rival (closeness 47/100,
    feeling: positive)" — the mind_only (Luna, Tilda) row is not hers.
[H] Admin + direction picks.
    build_relationship_addresses(Glut) -> Glut's visible rows Ember ("" / ""
    / outgoing_from "Tilda") and Luna (outgoing "informal, calls her Moon",
    incoming "calls him Sparks", outgoing_from "Tilda") — not Hans, whose
    (Glut, Hans) row is Hans's mind_only side; payload family ["Tilda",
    "Glut"]. build_relationship_addresses(Tilda)
    (DORMANT) answers (no 404) with others [Ember, Luna, Obs], outgoing_from
    "". set_relationship_address(Glut, Luna, outgoing "formal") -> leader
    row Tilda->Luna address "formal", reply outgoing "formal",
    outgoing_from "Tilda". set_relationship_address(Glut, Tilda, ...) -> 400.
    set_relationship_address(Luna, Tilda, incoming "Tilly") -> no 404,
    get_address(Tilda, Luna) "Tilly".
    build_memory_relationships(Glut): Luna self->other -0.7, other->self 0.3;
    build_memory_relationships(Luna): partners [Glut] (no Tilda).
    world_ops.build_relation_map(Glut)["Luna"]["sentiment"] -0.7;
    build_relation_map(Luna) has Glut, not Tilda.
    decision_points._relationship_line(Glut, Luna) == "Glut toward Luna:
    rival, moderate bond (47/100), feels very negative about Luna."
    reply_shape: facts relationship feeling for (Glut, Luna) "very negative".
[I] Decay reclassifies a body row with the leader value: body row (Glut,
    Luna) last_interaction_game = last_decay_game = "Y0001-D001T00:00:00",
    clock D020 -> 19 idle days >= grace 7, weeks = min(19/7, 2) = 2 ->
    strength 47 - 2 = 45, type classify(45, -0.7, 0.3) -> "rival" (with the
    stored 0.0: avg 0.15 -> "acquaintance").
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="linked-rel-smoke-"))
STORAGE = ROOT / "world"
STORAGE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")
(STORAGE / "config.json").write_text("{}", encoding="utf-8")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(ROOT / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from fastapi import HTTPException  # noqa: E402

from app.core.game_time import GameTime  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.core.timeutils import set_game_time  # noqa: E402
from app.models import character as ch  # noqa: E402
from app.models import relationship as R  # noqa: E402
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


def guarded(label, fn, expected):
    """check() around a call that may raise on the old code."""
    try:
        actual = fn()
    except Exception as e:  # noqa: BLE001
        actual = f"raised {type(e).__name__}: {e}"
    check(label, actual, expected)


def edit(name, **values):
    with keyed_lock("character_profile", name):
        p = ch.get_character_profile(name)
        p.update(values)
        assert ch.save_character_profile(name, p), name


def row(a, b):
    """The stored pair row as a dict (content + meta merged), or None."""
    return R.get_relationship(a, b)


def r6(v):
    return round(float(v or 0.0), 6)


def pick(rel, *keys):
    return None if rel is None else tuple(
        r6(rel.get(k)) if k.startswith(("sentiment", "romantic", "strength"))
        else rel.get(k) for k in keys)


def own(a, b):
    return r6(R.own_sentiment(a, b))


# ── fixture ─────────────────────────────────────────────────────────────────
set_game_time(GameTime.parse("Y0001-D020T12:00:00"))
INN = add_location("Inn", "A stone house.")["id"]
_data = _load_world_data()
for _loc in _data.get("locations", []):
    if _loc.get("id") == INN:
        _loc["rooms"] = [{"id": "taproom", "name": "Taproom", "description": "Benches."}]
        _loc["entry_room"] = "taproom"
_save_world_data(_data)
for _name in ("Tilda", "Luna", "Obs", "Hans"):
    assert ch.save_character_profile(
        _name, {"character_name": _name, "template": "human-roleplay"}, create_new=True)
    edit(_name, current_location=INN, current_room="taproom")

from app.core import linked_characters as lc  # noqa: E402
assert lc.create_linked("Tilda", "Glut")["ok"]
_swap = lc.swap_presence("Tilda", "Glut", reason="smoke")
assert _swap["ok"], _swap
assert ch.get_character_status("Tilda") == ch.DORMANT_STATUS
assert lc.create_linked("Hans", "Ember")["ok"]

OLD = "Y0001-D001T00:00:00"

# ── [A] first body interaction ──────────────────────────────────────────────
print("[A] a body's interaction")
R.record_interaction("Glut", "Luna", "talkto", "hello", sentiment_delta_a=0.3,
                     sentiment_delta_b=0.2, strength_delta=2.0, romantic_delta=0.1)
lead = row("Tilda", "Luna")
check("leader row exists", lead is not None, True)
check("leader row (Tilda->Luna, Luna->Tilda, strength, count, history, type, tension)",
      pick(lead, "sentiment_b_to_a", "sentiment_a_to_b", "strength",
           "interaction_count", "history", "type", "romantic_tension"),
      (0.3, 0.0, 10.0, 0, [], "neutral", 0.0))
check("leader row is the mind's side only", (lead or {}).get("mind_only"), ["Tilda"])
check("leader row last_interaction_game set",
      bool((lead or {}).get("last_interaction_game")), True)
body = row("Glut", "Luna")
check("body row (Glut->Luna, Luna->Glut, strength, count, tension, type)",
      pick(body, "sentiment_a_to_b", "sentiment_b_to_a", "strength",
           "interaction_count", "romantic_tension", "type"),
      (0.0, 0.2, 12.0, 1, 0.1, "neutral"))
check("body row history",
      [(h.get("initiator"), h.get("sentiment_delta")) for h in (body or {}).get("history", [])],
      [("Glut", 0.25)])

# ── [B] second interaction, classification by the leader value ──────────────
print("[B] classification of a body row")
lead = row("Tilda", "Luna")
lead["sentiment_b_to_a"] = -0.8
lead["last_interaction_game"] = OLD
R.save_relationships([lead])
R.update_relationship_manual("Glut", "Luna", strength=45)
R.record_interaction("Luna", "Glut", "talkto", "again", sentiment_delta_a=0.1,
                     sentiment_delta_b=0.1, strength_delta=2.0)
lead = row("Tilda", "Luna")
check("leader Tilda->Luna += Glut's delta; strength/count/history untouched",
      pick(lead, "sentiment_b_to_a", "sentiment_a_to_b", "strength",
           "interaction_count", "history"),
      (-0.7, 0.0, 10.0, 0, []))
check("leader row last_interaction_game touched",
      str((lead or {}).get("last_interaction_game") or "") > OLD, True)
body = row("Glut", "Luna")
check("body row (strength, Luna->Glut, Glut->Luna, count, type)",
      pick(body, "strength", "sentiment_b_to_a", "sentiment_a_to_b",
           "interaction_count", "type"),
      (47.0, 0.3, 0.0, 2, "rival"))
guarded("own_sentiment(Glut, Luna)", lambda: own("Glut", "Luna"), -0.7)
guarded("own_sentiment(Tilda, Luna)", lambda: own("Tilda", "Luna"), -0.7)
guarded("own_sentiment(Luna, Glut)", lambda: own("Luna", "Glut"), 0.3)
guarded("own_sentiment(Luna, Tilda)", lambda: own("Luna", "Tilda"), 0.0)

# ── [C] one family never gets a row ─────────────────────────────────────────
print("[C] one family")
check("record_interaction(Glut, Tilda) is a no-op",
      R.record_interaction("Glut", "Tilda", "talkto", "", 0.5, 0.5), {})
check("no Glut/Tilda row", row("Glut", "Tilda"), None)
check("set_address(Glut, Tilda)", R.set_address("Glut", "Tilda", "x"), False)
check("set_address(Tilda, Glut)", R.set_address("Tilda", "Glut", "x"), False)
check("still no Glut/Tilda row", row("Glut", "Tilda"), None)
guarded("own_sentiment(Glut, Tilda)", lambda: own("Glut", "Tilda"), 0.0)

# ── [D] form of address ─────────────────────────────────────────────────────
print("[D] form of address")
R.set_address("Glut", "Luna", "informal, calls her Moon")
check("leader row carries Tilda->Luna address",
      (row("Tilda", "Luna") or {}).get("address_b_to_a"), "informal, calls her Moon")
check("body row has no Glut->Luna address",
      "address_a_to_b" in (row("Glut", "Luna") or {}), False)
check("get_address(Glut, Luna)", R.get_address("Glut", "Luna"), "informal, calls her Moon")
check("get_address(Tilda, Luna)", R.get_address("Tilda", "Luna"), "informal, calls her Moon")
R.set_address("Luna", "Glut", "calls him Sparks")
check("body row carries Luna->Glut address",
      (row("Glut", "Luna") or {}).get("address_b_to_a"), "calls him Sparks")
check("leader row has no Luna->Tilda address",
      "address_a_to_b" in (row("Tilda", "Luna") or {}), False)
check("get_address(Luna, Tilda)", R.get_address("Luna", "Tilda"), "")

# ── [E] the leader meets Obs in person ──────────────────────────────────────
print("[E] the leader in person")
R.record_interaction("Tilda", "Obs", "talkto", "", 0.4, 0.5, strength_delta=2.0)
check("(Obs, Tilda) row",
      pick(row("Obs", "Tilda"), "sentiment_b_to_a", "sentiment_a_to_b", "strength", "type"),
      (0.4, 0.5, 12.0, "neutral"))
check("no mind_only on an in-person row", (row("Obs", "Tilda") or {}).get("mind_only"), None)

# ── [F] two bodies of two families ──────────────────────────────────────────
print("[F] two bodies")
R.record_interaction("Glut", "Ember", "talkto", "", 0.2, -0.4, strength_delta=1.0)
check("(Ember, Tilda) Tilda->Ember",
      pick(row("Tilda", "Ember"), "sentiment_b_to_a", "sentiment_a_to_b", "mind_only"),
      (0.2, 0.0, ["Tilda"]))
check("(Glut, Hans) Hans->Glut",
      pick(row("Hans", "Glut"), "sentiment_b_to_a", "sentiment_a_to_b", "mind_only"),
      (-0.4, 0.0, ["Hans"]))
check("(Ember, Glut) body row",
      pick(row("Ember", "Glut"), "sentiment_a_to_b", "sentiment_b_to_a", "strength",
           "interaction_count"),
      (0.0, 0.0, 9.0, 1))
guarded("own_sentiment(Ember, Glut)", lambda: own("Ember", "Glut"), -0.4)
guarded("own_sentiment(Glut, Ember)", lambda: own("Glut", "Ember"), 0.2)

# ── [G] prompts ─────────────────────────────────────────────────────────────
print("[G] prompts")
FAMILY = "\n".join([
    "",
    "Your relationships with other characters:",
    "- Luna (feeling: very negative)",
    "  - as Glut: Rival (closeness 47/100), their view of you: positive",
    "- Obs: Known (closeness 12/100, feeling: positive)",
    "- Ember (feeling: positive)",
    "  - as Glut: Known (closeness 9/100), their view of you: neutral",
])
check("Tilda's section", R.build_relationship_prompt_section("Tilda"), FAMILY)
check("Glut's section", R.build_relationship_prompt_section("Glut"), FAMILY)
check("Luna's section", R.build_relationship_prompt_section("Luna"),
      "\nYour relationships with other characters:\n"
      "- Glut: Rival (closeness 47/100, feeling: positive)")

# ── [H] admin + direction picks ─────────────────────────────────────────────
print("[H] admin and direction picks")
from app.core import character_ops  # noqa: E402
_glut = character_ops.build_relationship_addresses("Glut")
check("Glut's address editor",
      [(i["other"], i["outgoing"], i["incoming"], i.get("outgoing_from"))
       for i in _glut["items"]],
      [("Ember", "", "", "Tilda"),
       ("Luna", "informal, calls her Moon", "calls him Sparks", "Tilda")])
check("address payload family", _glut.get("family"), ["Tilda", "Glut"])
guarded("dormant Tilda's address editor",
        lambda: [(i["other"], i.get("outgoing_from")) for i in
                 character_ops.build_relationship_addresses("Tilda")["items"]],
        [("Ember", ""), ("Luna", ""), ("Obs", "")])
_set = character_ops.set_relationship_address("Glut", "Luna", outgoing="formal")
check("set via the body lands on the leader",
      (row("Tilda", "Luna") or {}).get("address_b_to_a"), "formal")
check("set reply", (_set.get("outgoing"), _set.get("outgoing_from")), ("formal", "Tilda"))


def _same_family():
    try:
        character_ops.set_relationship_address("Glut", "Tilda", outgoing="x")
    except HTTPException as e:
        return e.status_code
    return "no error"


check("address inside one family refused", _same_family(), 400)
guarded("address toward a dormant character",
        lambda: character_ops.set_relationship_address(
            "Luna", "Tilda", incoming="Tilly")["incoming"], "Tilly")
check("get_address(Tilda, Luna)", R.get_address("Tilda", "Luna"), "Tilly")
_mind = {i["partner"]: i for i in character_ops.build_memory_relationships("Glut")["items"]}
check("Mind panel of Glut: Luna sentiments",
      (r6(_mind.get("Luna", {}).get("sentiment_self_to_other")),
       r6(_mind.get("Luna", {}).get("sentiment_other_to_self"))), (-0.7, 0.3))
check("Mind panel of Luna: partners",
      sorted(i["partner"] for i in character_ops.build_memory_relationships("Luna")["items"]),
      ["Glut"])
from app.core import world_ops  # noqa: E402
check("relation map of Glut: Luna", world_ops.build_relation_map("Glut").get("Luna"),
      {"type": "rival", "strength": 47.0, "sentiment": -0.7})
check("relation map of Luna", sorted(world_ops.build_relation_map("Luna")), ["Glut"])
from app.core import decision_points  # noqa: E402
check("invite relationship line", decision_points._relationship_line("Glut", "Luna"),
      "Glut toward Luna: rival, moderate bond (47/100), feels very negative about Luna.")
from app.core import reply_shape  # noqa: E402
_captured = {}
_orig_compose = reply_shape.compose_reply_shape
reply_shape.compose_reply_shape = lambda facts: _captured.update(facts) or ""
try:
    reply_shape.build_reply_shape_section("Glut", "Luna", "Hello?")
finally:
    reply_shape.compose_reply_shape = _orig_compose
check("reply shape feeling", (_captured.get("relationship") or {}).get("feeling"),
      "very negative")

# ── [I] decay ───────────────────────────────────────────────────────────────
print("[I] decay")
body = row("Glut", "Luna")
body["last_interaction_game"] = OLD
body["last_decay_game"] = OLD
R.save_relationships([body])
from app.core.relationship_decay import handle_relationship_decay  # noqa: E402
handle_relationship_decay({})
check("decayed body row (strength, type)",
      pick(row("Glut", "Luna"), "strength", "type"), (45.0, "rival"))

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
