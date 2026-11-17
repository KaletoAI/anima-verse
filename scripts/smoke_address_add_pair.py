#!/usr/bin/env python3
"""Smoke: Game-Admin → Relationships "Add pair" never erases a stored form of address.

Usage:  ./.venv/bin/python scripts/smoke_address_add_pair.py

Throwaway storage + instance (``STORAGE_DIR`` / ``INSTANCE_DIR`` temp dirs,
``paths.init`` BEFORE any world-DB module), no server, no LLM.

THE CONTRACT the panel relies on (frontend/src/tabs/characters/RelationshipAddresses.tsx,
``addPair``; server ``character_ops.set_relationship_address`` + ``relationship.set_address``):
  * any address write creates the pair, an EMPTY text clears that direction, a missing
    direction stays untouched;
  * a linked body's own direction is its leader's, read and written on the leader row.
So "Add pair" on body B for character X must not send B's own direction (that would be
the leader's stored address); it writes X's direction with the value X already has —
read from X's own address list (``build_relationship_addresses(X)``, X's ``outgoing``
toward B, "" when X has no row with B).

FIXTURE
    Tilda, Obs, Wren, Hans (human-roleplay). create_linked(Tilda, "Glut") and
    swap_presence(Tilda, Glut) -> Glut is Tilda's active body. create_linked(Hans,
    "Ember") -> Ember is Hans's (dormant) body.
    set_address(Tilda, Obs, "Captain"); set_address(Tilda, Wren, "Sir");
    set_address(Ember, Glut, "Sparky") (lands on Hans's row toward Glut, mind_only
    ["Hans"] — invisible to Glut, so Hans is addable on Glut's panel).

WHAT FOLLOWS BY HAND
[A] Glut's list has no Obs, Wren or Hans (no visible row with Glut) -> all three addable.
[B] New add flow for Obs: Obs's list has no Glut row -> current "" ->
    set_relationship_address(Glut, Obs, incoming="") -> set_address(Obs, Glut, "")
    creates the (Glut, Obs) row; Tilda's "Captain" for Obs is untouched.
    Glut's list then holds Obs with outgoing "Captain" (from Tilda), incoming "".
[C] New add flow for Hans: Hans's list shows Glut (the mind_only row is Hans's own
    side) with outgoing "Sparky" -> set_relationship_address(Glut, Hans,
    incoming="Sparky") -> unchanged: get_address(Hans, Glut) stays "Sparky"
    (an empty incoming would have cleared it).
[D] The OLD request body {outgoing: "", incoming: ""} for Wren:
    set_address(Glut, Wren, "") resolves Glut to Tilda and pops Tilda's "Sir"
    -> get_address(Tilda, Wren) == "" — the defect the panel no longer triggers.
[E] Why X's value is read first: a bare {incoming: ""} for Hans would run
    set_address(Hans, Glut, "") and pop "Sparky" -> get_address(Hans, Glut) == "".
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="address-add-pair-smoke-"))
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

from app.core import character_ops  # noqa: E402
from app.core import linked_characters as lc  # noqa: E402
from app.models import character as ch  # noqa: E402
from app.models import relationship as R  # noqa: E402

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


def others(name):
    return [i["other"] for i in character_ops.build_relationship_addresses(name)["items"]]


def add_pair(character, picked):
    """The panel's addPair: X's direction, written with the value it already has."""
    theirs = character_ops.build_relationship_addresses(picked)["items"]
    current = next((i["outgoing"] for i in theirs if i["other"] == character), "")
    character_ops.set_relationship_address(character, picked, incoming=current)


# ── fixture ─────────────────────────────────────────────────────────────────
for _name in ("Tilda", "Obs", "Wren", "Hans"):
    assert ch.save_character_profile(
        _name, {"character_name": _name, "template": "human-roleplay"}, create_new=True)
assert lc.create_linked("Tilda", "Glut")["ok"]
assert lc.swap_presence("Tilda", "Glut", reason="smoke")["ok"]
assert lc.create_linked("Hans", "Ember")["ok"]
assert R.set_address("Tilda", "Obs", "Captain")
assert R.set_address("Tilda", "Wren", "Sir")
assert R.set_address("Ember", "Glut", "Sparky")

print("[A] addable on Glut's panel")
_glut = others("Glut")
check("Obs, Wren, Hans not listed for Glut",
      [n for n in ("Obs", "Wren", "Hans") if n in _glut], [])

print("[B] add Obs (new flow)")
add_pair("Glut", "Obs")
check("Tilda's address for Obs kept", R.get_address("Tilda", "Obs"), "Captain")
_items = {i["other"]: i for i in character_ops.build_relationship_addresses("Glut")["items"]}
check("Glut's row for Obs (outgoing, from, incoming)",
      tuple((_items.get("Obs") or {}).get(k) for k in ("outgoing", "outgoing_from", "incoming")),
      ("Captain", "Tilda", ""))

print("[C] add Hans (new flow, his body addressed Glut)")
add_pair("Glut", "Hans")
check("Hans's address for Glut kept", R.get_address("Hans", "Glut"), "Sparky")

print("[D] the old request body clears the leader's address")
character_ops.set_relationship_address("Glut", "Wren", outgoing="", incoming="")
check("old body: Tilda's address for Wren", R.get_address("Tilda", "Wren"), "")

print("[E] a bare empty incoming clears X's own address")
character_ops.set_relationship_address("Glut", "Hans", incoming="")
check("bare empty incoming: Hans's address for Glut", R.get_address("Hans", "Glut"), "")

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
