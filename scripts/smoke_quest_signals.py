#!/usr/bin/env python3
"""Smoke: the two quest signals and the item quantity reader (quest stage 1, Task 3).

Usage:  ./.venv/bin/python scripts/smoke_quest_signals.py

Throwaway storage only: ``paths.init(<tmpdir>)`` runs before any world-DB module is
imported. No server, no LLM, no real world.

THE WORLD, by hand: one location "inn" with the rooms "hall" and "cellar"; the
avatar "Wren" (the active character of user "demo") and the character "Mira"
both stand in inn/hall, "Osric" stands in inn/cellar. One stackable item
"Coin" (max_stack 99). Events are captured with ``hooks.register``.

Hand-derived expectations:

  [a] add_to_inventory(Wren, coin, 2) on an empty inventory creates a stack of 2
      -> exactly one ``inventory.changed`` {character: Wren, item_id: coin,
      delta: +2}; get_item_quantity(Wren, coin) == 2.
  [b] remove_from_inventory(Wren, coin, 1): 2 - 1 = 1 left -> one event with
      delta -1; quantity 1.
  [c] update_inventory_entry(Wren, coin, {"quantity": 5}): 5 - 1 = 4 -> one event
      with delta +4; quantity 5. A notes-only update applies no quantity -> no
      event.
  [d] get_item_quantity of an item Wren does not hold -> 0 (no row, not an error).
  [e] An add of 3 inside ``with keyed_lock("character_profile", "Wren")``: while
      the lock is held no event has arrived; the event arrives when the ``with``
      exits, so the timeline reads ["add returned under lock", "event"] and the
      listener sees this thread's lock depth 0. Its delta is +3 (5 + 3 = 8).
  [f] A failed write: with the DB transaction raising, add_to_inventory and
      remove_from_inventory return False and NO event is emitted; the quantity
      stays 8. (This and [m] log three expected "_save_inventory DB error" lines.)
  [g] Wren (avatar) says a line in inn/hall at normal volume: the room members
      are Wren and Mira; Osric is in another room and an unaddressed normal line
      does not reach him. The speaker is not a listener of its own line, so
      exactly one ``utterance.heard`` with heard_by == ["Mira"], avatars == []
      (Mira is no avatar), speaker_is_avatar True, location_id "inn",
      room_id "hall", source "play", utterance_id == the returned id.
  [h] Mira answers Wren (addressees ["Wren"]) -> one event, heard_by ["Wren"],
      avatars ["Wren"], speaker_is_avatar False, addressees ["Wren"].
  [i] A storyteller line, a display-only line and a dedupe hit (the same
      speaker/ts/content again with dedupe=True, which stores nothing) -> no
      event at all.

  Fix round 1 (all on Mira, whose inventory is empty before [j]):
  [j] Non-stackable "Key": the first add creates the row, delta +1, quantity 1.
      A second add takes the new-entry path; the second entry with the same
      item_id is upserted over the row (UNIQUE(character_name, item_id)), so
      the stored quantity stays 1 -> 1 - 1 = 0 -> True, but NO event.
  [k] A locked add onto a stack: add 5 coins -> +5. add(..., 1, locked=True)
      skips the stack path, the new entry of 1 replaces the stored 5, so
      1 - 5 = -4 -> one event with delta -4, quantity 1.
  [l] Max-stack cap: "Pebble" stackable, max_stack 3. add 2 -> +2. add 5 ->
      min(2 + 5, 3) = 3, so only 3 - 2 = +1 landed -> delta +1. add 1 more ->
      min(3 + 1, 3) = 3, delta 0 -> no event, add still returns True.
  [m] update_inventory_entry(Mira, pebble, {"quantity": 3}) on a stored 3 ->
      3 - 3 = 0 -> no event. The same update to 2 with the DB transaction
      raising -> False and no event; quantity stays 3.
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILURES = []
SECTION = [""]


def check(label, actual, expected):
    label = f"{SECTION[0]} {label}".strip()
    ok = actual == expected
    print(f"  {'PASS' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" -- expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="quest-signals-")
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
    from app.core import paths
    paths.init(tmp)
    import app
    here = Path(__file__).resolve().parents[1]
    assert Path(app.__file__).resolve().is_relative_to(here), app.__file__
    from app.core import db, hooks, keyed_lock as kl
    db.init_schema()
    from app.core.keyed_lock import keyed_lock
    from app.core.perception import STORYTELLER_SPEAKER, record_utterance
    from app.core.users import create_user, update_user
    from app.models import character as chars, inventory, world

    world.upsert_location({"id": "inn", "name": "Inn", "entry_room": "hall",
                           "rooms": [{"id": "hall", "name": "Hall"},
                                     {"id": "cellar", "name": "Cellar"}]},
                          sync_world=False)
    for name, room in (("Wren", "hall"), ("Mira", "hall"), ("Osric", "cellar")):
        assert chars.save_character_profile(
            name, {"current_location": "inn", "current_room": room},
            create_new=True), name
    uid = create_user("demo", "smoke-password", allowed_characters=["Wren"])
    update_user(uid, settings={"active_character": "Wren"})
    coin = inventory.add_item("Coin", stackable=True, max_stack=99)["id"]

    inv_events, heard, timeline = [], [], []

    def on_inv(**kw):
        inv_events.append(kw)
        timeline.append("event")
        kw["_depth"] = getattr(kl._LOCAL, "depth", 0)

    hooks.register("inventory.changed", on_inv, tag="smoke_quest_signals")
    hooks.register("utterance.heard", lambda **kw: heard.append(kw),
                   tag="smoke_quest_signals")
    quantity = getattr(inventory, "get_item_quantity", None)
    if quantity is None:
        print("  FAIL inventory.get_item_quantity is missing")
        FAILURES.append("get_item_quantity")
        quantity = lambda *a, **k: None  # noqa: E731

    def strip(ev):
        return {k: v for k, v in ev.items() if not k.startswith("_")}

    SECTION[0] = "[a]"
    print("[a] add 2")
    check("add returns", inventory.add_to_inventory("Wren", coin, 2), True)
    check("events", [strip(e) for e in inv_events],
          [{"character": "Wren", "item_id": coin, "delta": 2}])
    check("quantity", quantity("Wren", coin), 2)

    SECTION[0] = "[b]"
    print("[b] remove 1")
    inv_events.clear()
    check("remove returns", inventory.remove_from_inventory("Wren", coin, 1), True)
    check("events", [strip(e) for e in inv_events],
          [{"character": "Wren", "item_id": coin, "delta": -1}])
    check("quantity", quantity("Wren", coin), 1)

    SECTION[0] = "[c]"
    print("[c] update quantity to 5")
    inv_events.clear()
    check("update returns",
          inventory.update_inventory_entry("Wren", coin, {"quantity": 5}), True)
    check("events", [strip(e) for e in inv_events],
          [{"character": "Wren", "item_id": coin, "delta": 4}])
    check("quantity", quantity("Wren", coin), 5)
    inv_events.clear()
    inventory.update_inventory_entry("Wren", coin, {"notes": "lucky"})
    check("notes-only update emits nothing", inv_events, [])

    SECTION[0] = "[d]"
    print("[d] not held")
    check("quantity of an unheld item", quantity("Wren", "no_such_item"), 0)
    check("quantity for another character", quantity("Mira", coin), 0)

    SECTION[0] = "[e]"
    print("[e] add under a caller-held profile lock")
    inv_events.clear()
    timeline.clear()
    with keyed_lock("character_profile", "Wren"):
        inventory.add_to_inventory("Wren", coin, 3)
        check("no event while the lock is held", len(inv_events), 0)
        timeline.append("add returned under lock")
    check("timeline", timeline, ["add returned under lock", "event"])
    check("events", [strip(e) for e in inv_events],
          [{"character": "Wren", "item_id": coin, "delta": 3}])
    check("listener lock depth", [e["_depth"] for e in inv_events], [0])
    check("quantity", quantity("Wren", coin), 8)

    SECTION[0] = "[f]"
    print("[f] failed write")
    inv_events.clear()

    def broken_transaction(*a, **k):
        raise RuntimeError("disk gone")

    with patch.object(inventory, "transaction", broken_transaction):
        check("add returns False", inventory.add_to_inventory("Wren", coin, 1), False)
        check("remove returns False",
              inventory.remove_from_inventory("Wren", coin, 1), False)
    check("no event", inv_events, [])
    check("quantity unchanged", quantity("Wren", coin), 8)

    SECTION[0] = "[g]"
    print("[g] avatar line heard by the room")
    uid1 = record_utterance(speaker="Wren", content="Good evening.", source="play")
    check("events", len(heard), 1)
    if heard:
        check("payload", heard[0], {
            "utterance_id": uid1, "speaker": "Wren", "speaker_is_avatar": True,
            "heard_by": ["Mira"], "avatars": [], "addressees": [],
            "location_id": "inn", "room_id": "hall", "source": "play"})

    SECTION[0] = "[h]"
    print("[h] the reply")
    heard.clear()
    uid2 = record_utterance(speaker="Mira", content="Evening, Wren.",
                            addressees=["Wren"], source="loop")
    check("events", len(heard), 1)
    if heard:
        check("payload", heard[0], {
            "utterance_id": uid2, "speaker": "Mira", "speaker_is_avatar": False,
            "heard_by": ["Wren"], "avatars": ["Wren"], "addressees": ["Wren"],
            "location_id": "inn", "room_id": "hall", "source": "loop"})

    SECTION[0] = "[i]"
    print("[i] lines that are no conversation")
    heard.clear()
    record_utterance(speaker=STORYTELLER_SPEAKER, content="The fire crackles.",
                     location_id="inn", room_id="hall", source="narration")
    record_utterance(speaker="Mira", content="(Mira nods.)",
                     perception_meta={"display_only": True})
    check("storyteller and display-only lines emit nothing", heard, [])
    stamp = "2026-11-25T12:00:00+00:00"
    record_utterance(speaker="Mira", content="Once.", ts=stamp, dedupe=True)
    check("first dedupe write emits", len(heard), 1)
    heard.clear()
    check("dedupe hit stores nothing",
          record_utterance(speaker="Mira", content="Once.", ts=stamp, dedupe=True),
          None)
    check("no event", heard, [])

    def last_deltas():
        return [e["delta"] for e in inv_events]

    key = inventory.add_item("Key", stackable=False)["id"]
    pebble = inventory.add_item("Pebble", stackable=True, max_stack=3)["id"]

    SECTION[0] = "[j]"
    print("[j] non-stackable item added twice")
    inv_events.clear()
    check("first add", inventory.add_to_inventory("Mira", key), True)
    check("first delta", last_deltas(), [1])
    inv_events.clear()
    check("second add returns", inventory.add_to_inventory("Mira", key), True)
    check("second add emits nothing", inv_events, [])
    check("quantity", quantity("Mira", key), 1)

    SECTION[0] = "[k]"
    print("[k] locked add onto a stack")
    inv_events.clear()
    inventory.add_to_inventory("Mira", coin, 5)
    check("stack delta", last_deltas(), [5])
    inv_events.clear()
    check("locked add returns",
          inventory.add_to_inventory("Mira", coin, 1, locked=True), True)
    check("delta", last_deltas(), [-4])
    check("quantity", quantity("Mira", coin), 1)

    SECTION[0] = "[l]"
    print("[l] max-stack cap")
    inv_events.clear()
    inventory.add_to_inventory("Mira", pebble, 2)
    inventory.add_to_inventory("Mira", pebble, 5)
    check("deltas", last_deltas(), [2, 1])
    inv_events.clear()
    check("add at the cap returns", inventory.add_to_inventory("Mira", pebble, 1), True)
    check("zero delta emits nothing", inv_events, [])
    check("quantity", quantity("Mira", pebble), 3)

    SECTION[0] = "[m]"
    print("[m] update_inventory_entry without a change / with a failed write")
    inv_events.clear()
    check("same quantity returns",
          inventory.update_inventory_entry("Mira", pebble, {"quantity": 3}), True)
    check("same quantity emits nothing", inv_events, [])
    with patch.object(inventory, "transaction", broken_transaction):
        check("failed update returns False",
              inventory.update_inventory_entry("Mira", pebble, {"quantity": 2}), False)
    check("failed update emits nothing", inv_events, [])
    check("quantity unchanged", quantity("Mira", pebble), 3)

    if FAILURES:
        print(f"FAIL smoke_quest_signals: {len(FAILURES)} failed: {FAILURES}")
        return 1
    print("PASS smoke_quest_signals: [a]-[m]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
