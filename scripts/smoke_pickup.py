#!/usr/bin/env python3
"""Smoke run for PICKING ITEMS UP — room -> inventory (decision "Punkt 6").

Runs against a THROWAWAY storage directory — never touches a real world, never
needs the server.

THE HOLE THIS CLOSES. A player could DROP an item (``/play/drop``) and nothing
could ever take it back: the only pickup code was ``POST
/inventory/characters/{n}/pickup``, which no client called, and that path had
not run for months. Read as of commit f548ed5f, ``inventory.pick_up_item``
did, in this order:

    room_items = get_room_items(...)      # 1 read
    if not in_room: ...                   # 2 check
    add_to_inventory(...)                 # 3 hand over
    remove_item_from_room(...)            # 4 remove, RESULT IGNORED

Steps 1–2 and step 4 are three separate critical sections, so two characters
reaching for the same LAST piece both passed the check and both got it: one
item in the room became two in two inventories, and the second removal
returned False into nothing. Since this fix the ROOM SIDE IS THE CLAIM —
check and removal happen together under ``world_write_lock`` — and the
inventory write follows under ``keyed_lock("character_profile", …)``, the
places lock before the profile lock, never nested.

Hand-derived expectations — statements about the contract, not recordings of
current output:

  [1] HAPPY PATH. A room holds 3 of an item; the character picks 1 up.
      Afterwards: room 3-1 = 2, inventory 0+1 = 1, and the result names the
      item and the quantity. A second pickup of 2 empties the room: the entry
      is GONE from the room list (not a zero-quantity ghost), the inventory
      holds 1+2 = 3.

  [2] REFUSALS, each a failure with an error and NO state change:
      2a  an item that is not in this room,
      2b  an item id that does not exist at all,
      2c  a HIDDEN room item — undiscovered, so it is neither listed by
          /play/belongings -> items_here nor pickable,
      2d  more than lies there (room has 1, ask for 2),
      2e  quantity 0 / negative is normalised to 1 by the route, and the
          model clamps it the same way, so 0 picks up exactly 1.

  [3] NO DUPLICATION UNDER LOAD. The room holds exactly 1 piece; 8 threads
      reach for it at once with 4 different characters. EXACTLY ONE call
      succeeds, the sum over all inventories is 1, and the room is empty.
      Conservation: room_before + inv_before == room_after + inv_after == 1.
      With the pre-fix order (reproduced literally in this script as the
      CONTROL, from the code quoted above) more than one call succeeds and
      the sum exceeds 1 — the bug is demonstrated with running code, not
      asserted. The control is a RACE, so it gets several attempts and has to
      duplicate in at least one of them; the fixed path is run the same number
      of times and must be clean in EVERY one.

  [4] A FULL INVENTORY PUTS THE CLAIM BACK. The carrying limit is max_slots
      (default 20, counted over everything that is not an outfit_piece). A
      character carrying 20 tries to pick up the 21st: the call fails AND the
      item still lies in the room, with its discovery_difficulty and note
      unchanged. Without the rollback it would be gone from the world —
      removed from the room by the claim and refused by the inventory.

  [5] RESTRICTIONS EQUAL DROP'S. ``_play_pickup_sync`` is built on exactly
      the gate ``_play_drop_sync`` uses — an avatar, nothing else. Checked at
      the source: both call ``_require_avatar`` and resolve location/room from
      the avatar, and NEITHER consults the party engine, ``_party_block`` or
      ``_require_present_target``. A follower may pick things up for the same
      reason it may put them down: a party restricts MOVEMENT, not the hands.
      Both also raise on a missing avatar rather than guessing one.

  [6] items_here LISTS WHAT CAN BE PICKED UP. The visible entries of the
      avatar's room, hidden ones skipped — the same rule
      ``thought_context._build_room_items_block`` applies for the NPC prompt.

  [7] mark_all_read RESPECTS THE WHITELIST. Three unread notifications for
      three characters; marking all read for ["Alpha"] leaves the other two
      unread. Before this fix the call had no whitelist parameter at all and
      cleared notifications of characters the caller may not even see.

The route table (``/play/pickup`` present, ``/inventory/.../pickup`` and
``/play/journal`` gone) is pinned in scripts/smoke_admin_controls.py, which
owns the hand-written DELETED/KEPT lists.

Usage:  ./.venv/bin/python scripts/smoke_pickup.py
"""
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="pickup-smoke-"))
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="pickup-smoke-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.models.inventory import (  # noqa: E402
    add_item, add_item_to_room, add_to_inventory, get_character_inventory,
    get_room_items, pick_up_item, remove_item_from_room)
from app.models.world import add_location, add_room  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def inv_qty(character, item_id):
    for e in (get_character_inventory(character) or {}).get("inventory", []):
        if e.get("item_id") == item_id:
            return int(e.get("quantity", 1) or 1)
    return 0


def room_qty(loc_id, room_id, item_id):
    for ri in get_room_items(loc_id, room_id) or []:
        if ri.get("item_id") == item_id:
            return int(ri.get("quantity", 1) or 1)
    return 0


def room_has_entry(loc_id, room_id, item_id):
    return any(ri.get("item_id") == item_id
               for ri in get_room_items(loc_id, room_id) or [])


def ensure_character(*names):
    """inventory_items and memories carry a FOREIGN KEY on characters(name);
    a bare row is all these checks need."""
    from app.core.db import transaction
    from app.core.timeutils import utc_now_iso
    now = utc_now_iso()
    with transaction() as conn:
        for name in names:
            conn.execute(
                "INSERT OR IGNORE INTO characters (name, created_at, updated_at) "
                "VALUES (?, ?, ?)", (name, now, now))


ensure_character("Alpha", "Beta", "Gamma", "Bounded", "A1", "A2", "A3", "A4")

LOC = add_location(name="Warehouse", description="a shed")["id"]
ROOM = (add_room(LOC, "Floor", "the floor") or {}).get("id") or "floor"

STONE = add_item(name="Stone", description="a grey stone", stackable=True,
                 max_stack=99)["id"]
COIN = add_item(name="Coin", description="a coin", stackable=True, max_stack=99)["id"]
GEM = add_item(name="Gem", description="a hidden gem")["id"]
ELSEWHERE = add_item(name="Elsewhere", description="not in this room")["id"]


print("\n[1] happy path — the item leaves the room and enters the inventory")
add_item_to_room(LOC, ROOM, STONE, quantity=3)
check("room seeded with 3", room_qty(LOC, ROOM, STONE), 3)
res = pick_up_item("Alpha", LOC, ROOM, STONE, quantity=1)
check("pickup succeeds", res.get("success"), True)
check("result names the item", res.get("item_name"), "Stone")
check("result names the quantity", res.get("quantity"), 1)
check("room is down to 2", room_qty(LOC, ROOM, STONE), 2)
check("inventory holds 1", inv_qty("Alpha", STONE), 1)

res = pick_up_item("Alpha", LOC, ROOM, STONE, quantity=2)
check("the rest comes along", res.get("success"), True)
check("the room ENTRY is gone, not a zero ghost", room_has_entry(LOC, ROOM, STONE), False)
check("inventory holds 3", inv_qty("Alpha", STONE), 3)


print("\n[2] refusals — each one a failure with an error and no state change")
r = pick_up_item("Alpha", LOC, ROOM, ELSEWHERE)
check("2a not in this room fails", r.get("success"), False)
check("2a has an error", bool(r.get("error")), True)
check("2a nothing entered the inventory", inv_qty("Alpha", ELSEWHERE), 0)

r = pick_up_item("Alpha", LOC, ROOM, "no_such_item_at_all")
check("2b unknown item fails", r.get("success"), False)

add_item_to_room(LOC, ROOM, GEM, quantity=1, hidden=True, discovery_difficulty=3,
                 note="under the plank")
r = pick_up_item("Alpha", LOC, ROOM, GEM)
check("2c a hidden item cannot be picked up", r.get("success"), False)
check("2c the hidden item still lies there", room_qty(LOC, ROOM, GEM), 1)
check("2c it did not enter the inventory", inv_qty("Alpha", GEM), 0)

add_item_to_room(LOC, ROOM, COIN, quantity=1)
r = pick_up_item("Alpha", LOC, ROOM, COIN, quantity=2)
check("2d more than lies there fails", r.get("success"), False)
check("2d the coin still lies there", room_qty(LOC, ROOM, COIN), 1)
r = pick_up_item("Alpha", LOC, ROOM, COIN, quantity=0)
check("2e quantity 0 is clamped to 1 and succeeds", r.get("success"), True)
check("2e exactly one coin moved", inv_qty("Alpha", COIN), 1)


print("\n[3] no duplication under load — 8 threads, 1 piece, 4 characters")


def contended(picker, rounds=8, characters=("A1", "A2", "A3", "A4")):
    """Run `rounds` pickers of the LAST piece at once and report
    (successes, total quantity across all inventories, quantity left in room).
    """
    item = add_item(name=f"Prize-{picker.__name__}", description="one of a kind")["id"]
    add_item_to_room(LOC, ROOM, item, quantity=1)
    wins = []
    lock = threading.Lock()
    start = threading.Event()

    def run(i):
        who = characters[i % len(characters)]
        start.wait()
        ok = picker(who, item)
        if ok:
            with lock:
                wins.append(who)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(rounds)]
    for t in threads:
        t.start()
    start.set()
    for t in threads:
        t.join()
    total = sum(inv_qty(c, item) for c in characters)
    return len(wins), total, room_qty(LOC, ROOM, item)


def fixed_picker(who, item):
    return bool(pick_up_item(who, LOC, ROOM, item, quantity=1).get("success"))


def legacy_picker(who, item):
    """The pre-fix body, quoted from commit f548ed5f: read, check, add, then
    remove with the result thrown away."""
    from app.models.inventory import get_item
    if not get_item(item):
        return False
    in_room = next((ri for ri in get_room_items(LOC, ROOM)
                    if ri.get("item_id") == item), None)
    if not in_room:
        return False
    if int(in_room.get("quantity", 1)) < 1:
        return False
    if not add_to_inventory(who, item, quantity=1, obtained_from=f"{LOC}/{ROOM}",
                            obtained_method="found"):
        return False
    remove_item_from_room(LOC, ROOM, item, quantity=1)
    return True


ROUNDS = 6
ctl = [contended(legacy_picker) for _ in range(ROUNDS)]
print("  (control, pre-fix order: "
      + ", ".join(f"{w} winners/{tot} held" for w, tot, _ in ctl) + ")")
check("the control DOES duplicate — the bug is real",
      any(w > 1 or tot > 1 for w, tot, _ in ctl), True)

fixed = [contended(fixed_picker) for _ in range(ROUNDS)]
check("exactly one thread wins, every round",
      sorted({w for w, _, _ in fixed}), [1])
check("exactly one piece exists afterwards, every round",
      sorted({tot for _, tot, _ in fixed}), [1])
check("the room is empty, every round",
      sorted({left for _, _, left in fixed}), [0])
check("conservation: 1 in == 1 out, every round",
      sorted({tot + left for _, tot, left in fixed}), [1])


print("\n[4] a full inventory puts the claim back")
# The carrying limit is max_slots, default 20, counting everything that is not
# an outfit_piece (inventory.add_to_inventory). Fill it exactly.
FILLERS = [add_item(name=f"Ballast {i}", description="fills a slot")["id"]
           for i in range(20)]
for iid in FILLERS:
    add_to_inventory("Bounded", iid, quantity=1)
check("the character carries a full load",
      len((get_character_inventory("Bounded") or {}).get("inventory", [])), 20)
SECOND = add_item(name="Second", description="one too many")["id"]
add_item_to_room(LOC, ROOM, SECOND, quantity=1, hidden=False,
                 discovery_difficulty=2, note="on the shelf")
r = pick_up_item("Bounded", LOC, ROOM, SECOND)
check("the pickup fails", r.get("success"), False)
check("the item is STILL in the room", room_qty(LOC, ROOM, SECOND), 1)
entry = next(ri for ri in get_room_items(LOC, ROOM) if ri.get("item_id") == SECOND)
check("its discovery_difficulty survived the rollback",
      int(entry.get("discovery_difficulty", 0) or 0), 2)
check("its note survived the rollback", entry.get("note"), "on the shelf")
check("it did not enter the inventory", inv_qty("Bounded", SECOND), 0)


print("\n[5] the route's restrictions are exactly drop's")
import inspect  # noqa: E402
from app.routes import play as play_routes  # noqa: E402

drop_src = inspect.getsource(play_routes._play_drop_sync)
pick_src = inspect.getsource(play_routes._play_pickup_sync)
GATES = ("_require_avatar", "get_character_current_location",
         "get_character_current_room")
FORBIDDEN = ("_party_block", "party_engine", "_require_present_target",
             "get_party_of", "is_follower")
for g in GATES:
    check(f"drop uses {g}", g in drop_src, True)
    check(f"pickup uses {g}", g in pick_src, True)
for f in FORBIDDEN:
    check(f"drop does not consult {f}", f in drop_src, False)
    check(f"pickup does not consult {f}", f in pick_src, False)
check("pickup refuses without an avatar, like drop",
      "_require_avatar()" in pick_src and "_require_avatar()" in drop_src, True)


print("\n[6] items_here lists the visible room items only")
VISIBLE = add_item(name="Bucket", description="a wooden bucket")["id"]
HIDDEN = add_item(name="Key", description="a small key")["id"]
add_item_to_room(LOC, ROOM, VISIBLE, quantity=2)
add_item_to_room(LOC, ROOM, HIDDEN, quantity=1, hidden=True)


class _Where:
    """Pin the avatar into the seeded room without a character profile: the
    helper asks these two readers and nothing else about the place."""

    def __enter__(self):
        import app.models.character as ch
        self._ch = ch
        self._old_loc, self._old_room = (ch.get_character_current_location,
                                         ch.get_character_current_room)
        ch.get_character_current_location = lambda *a, **k: LOC
        ch.get_character_current_room = lambda *a, **k: ROOM
        return self

    def __exit__(self, *exc):
        self._ch.get_character_current_location = self._old_loc
        self._ch.get_character_current_room = self._old_room
        return False


with _Where():
    here = play_routes._items_here("Alpha")
names = {e["item_id"]: e for e in here}
check("the visible item is listed", VISIBLE in names, True)
check("its quantity is the room's", names.get(VISIBLE, {}).get("quantity"), 2)
check("it carries the image flag", "image" in names.get(VISIBLE, {}), True)
check("the HIDDEN item is not listed", HIDDEN in names, False)
check("no avatar means no list", play_routes._items_here(""), [])


print("\n[7] mark_all_read respects the character whitelist")
from app.models.notifications import (  # noqa: E402
    create_notification, get_unread_count, mark_all_read)

for who in ("Alpha", "Beta", "Gamma"):
    create_notification(who, f"a message for {who}", notification_type="message")
check("three unread to start with", get_unread_count(), 3)
marked = mark_all_read(character_whitelist=["Alpha"])
check("exactly one was marked", marked, 1)
check("Alpha has none left", get_unread_count(character_whitelist=["Alpha"]), 0)
check("Beta still has one", get_unread_count(character_whitelist=["Beta"]), 1)
check("two are still unread overall", get_unread_count(), 2)
check("an EMPTY whitelist marks nothing", mark_all_read(character_whitelist=[]), 0)
check("no whitelist still sweeps everything", mark_all_read(), 2)
check("nothing unread afterwards", get_unread_count(), 0)


print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    for f in FAILURES:
        print(f"  FAILED: {f}")
    sys.exit(1)
print("OK")
