"""Smoke: part items (plan-anhaenger Task 2, design G) — a part is an outfit piece without a slot, links are checked on
save, and a part never lands on a slot, in an inventory or in a room.

Usage: ./.venv/bin/python scripts/smoke_accessory_parts.py   (no server; a temp world, a temp shared library)

Expected, by hand from the plan's interfaces:

[1] ``add_item(outfit_piece={"slots": [], "jewellery": {"kind": "charm"}})`` → stored with ``slots == []`` and
    ``mesh_mode == "accessory"``; the same with kind ``belt`` → ValueError "needs non-empty 'slots'".
[2] a part saved with ``slots: ["neck"]`` keeps ``slots == []`` (a part has no slot).
[3] host A (belt, ``buckle.item = P``) and host B (necklace, ``pendant.item = P``) → ``used_by(P)`` =
    [{A, buckle}, {B, pendant}] (sorted by item id: "host_a" < "host_b").
[4] ``update_item(A, buckle.item = <tool item>)`` → ValueError "is not a part item"; ``buckle.item = A`` → ValueError
    (itself); a missing item → "does not exist".
[5] ``apply_equipped_pieces(name, pieces={"neck": P})`` skips P (reason ``part_item``); ``equip_piece`` with P →
    error ``part_item``; the equip route answers 400 "A part item is worn through its chain or belt".
[6] ``add_to_inventory("demo", P)`` → False and the inventory has no P; ``give_item`` with P → False, no entry;
    ``add_item_to_room(loc, room, P)`` → False; the admin routes answer 400 with the same words as [5].
[7] P written straight into demo's inventory (``_save_inventory``, past the guard) next to A: ``get_character_inventory``
    lists A, not P. The same for ``get_room_items`` with a room entry written straight into the location.
[8] ``resolve_item_id(<P's name>)`` is None, ``resolve_item_id(<A's name>) == A``.
[9] a part's ``prompt_fragment`` change invalidates the renders of each host once (``_invalidate_renders_for_item``
    called for host_a and host_b), the host's own link change invalidates the host (link ids are render-relevant).
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
STORAGE = Path(tempfile.mkdtemp(prefix="parts-smoke-"))
SHARED = Path(tempfile.mkdtemp(prefix="parts-smoke-shared-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="parts-smoke-clips-")
from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()
from app.models import inventory as inv  # noqa: E402
inv._get_shared_dir = lambda: SHARED     # never the repo's shared library
from app.core import accessory_parts as parts  # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (expected {want!r})"))
    if not ok:
        FAIL.append(name)


def raises(name, fn, words):
    try:
        fn()
    except ValueError as e:
        check(name, words in str(e), True)
        return
    check(name, "no ValueError", words)


# [1]
P = inv.add_item("Oak Buckle", category="outfit_piece", item_id="item_p", prompt_fragment="a copper oak-leaf buckle",
                 outfit_piece={"slots": [], "jewellery": {"kind": "charm"}})
check("[1] part slots", P["outfit_piece"]["slots"], [])
check("[1] part mode", P["outfit_piece"].get("mesh_mode"), "accessory")
check("[1] part charm block", P["outfit_piece"]["jewellery"].get("charm"), {"size_mm": 30.0, "mount": "flat",
                                                                            "flip": False})
raises("[1] belt without slot", lambda: inv.add_item("Belt X", category="outfit_piece",
                                                      outfit_piece={"slots": [], "jewellery": {"kind": "belt"}}),
       "needs non-empty 'slots'")
# [2]
Q = inv.add_item("Bell", category="outfit_piece", item_id="item_q", prompt_fragment="a silver bell",
                 outfit_piece={"slots": ["neck"], "jewellery": {"kind": "charm"}})
check("[2] slot dropped", Q["outfit_piece"]["slots"], [])
check("[2] slot dropped (update)", inv.update_item("item_q", {"outfit_piece": {"slots": ["neck"], "jewellery": {
    "kind": "charm"}}})["outfit_piece"]["slots"], [])
check("[2] is_part", (parts.is_part(inv.get_item("item_q")), parts.is_part_id("item_p")), (True, True))
# [3]
A = inv.add_item("Copper Belt", category="outfit_piece", item_id="host_a", prompt_fragment="copper belt",
                 outfit_piece={"slots": ["outer"], "mesh_mode": "accessory",
                               "jewellery": {"kind": "belt", "buckle": {"item": "item_p"}}})
B = inv.add_item("Gold Chain", category="outfit_piece", item_id="host_b", prompt_fragment="gold necklace",
                 outfit_piece={"slots": ["neck"], "mesh_mode": "accessory",
                               "jewellery": {"kind": "necklace", "pendant": {"item": "item_p"}}})
check("[3] used_by", [(u["item_id"], u["role"]) for u in parts.used_by("item_p")],
      [("host_a", "buckle"), ("host_b", "pendant")])
check("[3] host keeps link", inv.get_item("host_a")["outfit_piece"]["jewellery"]["buckle"], {"item": "item_p"})
# [4]
inv.add_item("Hammer", category="tool", item_id="item_tool")
piece_a = inv.get_item("host_a")["outfit_piece"]


def relink(target):
    return lambda: inv.update_item("host_a", {"outfit_piece": {**piece_a, "jewellery": {
        "kind": "belt", "buckle": {"item": target}}}})


raises("[4] not a part", relink("item_tool"), "is not a part item")
raises("[4] itself", relink("host_a"), "itself")
raises("[4] missing", relink("item_nope"), "does not exist")
check("[4] link unchanged after refusals", inv.get_item("host_a")["outfit_piece"]["jewellery"]["buckle"],
      {"item": "item_p"})
raises("[4] add_item refuses a bad link", lambda: inv.add_item(
    "Belt Y", category="outfit_piece", outfit_piece={"slots": ["outer"], "jewellery": {
        "kind": "belt", "buckle": {"item": "item_tool"}}}), "is not a part item")

# [5]
from app.models.character import save_character_profile  # noqa: E402
save_character_profile("demo", {"name": "demo"}, create_new=True)
save_character_profile("someone", {"name": "someone"}, create_new=True)
inv._save_inventory("demo", {"inventory": [{"item_id": "host_a", "quantity": 1}, {"item_id": "item_p", "quantity": 1}]})
res = inv.apply_equipped_pieces("demo", pieces={"neck": "item_p"}, source="smoke")
check("[5] apply_equipped skips the part", [(s["item_id"], s["reason"]) for s in res["skipped"]],
      [("item_p", "part_item")])
check("[5] equip_piece refuses", inv.equip_piece("demo", "item_p").get("reason"), "part_item")
from fastapi import HTTPException  # noqa: E402
from app.routes import inventory as inv_route  # noqa: E402
for label, fn in (("equip", lambda: inv_route._equip_route_sync("demo", {"item_id": "item_p"})),
                  ("add to inventory", lambda: inv_route._add_inventory_item_route_sync("demo", {"item_id": "item_p"})),
                  ("add to room", lambda: inv_route._add_room_item_route_sync("loc1", "r1", {"item_id": "item_p"}))):
    try:
        fn()
        check(f"[5/6] {label} route", "no error", 400)
    except HTTPException as e:
        check(f"[5/6] {label} route", (e.status_code, e.detail), (400, parts.REFUSED_WEAR))

# [6]
inv._save_inventory("demo", {"inventory": [{"item_id": "host_a", "quantity": 1}]})
check("[6] add_to_inventory", inv.add_to_inventory("demo", "item_p"), False)
check("[6] not stored", [e["item_id"] for e in inv._load_inventory("demo")["inventory"]], ["host_a"])
check("[6] give_item", inv.give_item("someone", "demo", "item_p"), False)
check("[6] still not stored", [e["item_id"] for e in inv._load_inventory("demo")["inventory"]], ["host_a"])
from app.models.world import upsert_location, get_location_by_id  # noqa: E402
upsert_location({"id": "loc1", "name": "Hut", "rooms": [{"id": "r1", "name": "Room", "items": []}]}, sync_world=False)
check("[6] add_item_to_room", inv.add_item_to_room("loc1", "r1", "item_p"), False)
check("[6] add host to room", inv.add_item_to_room("loc1", "r1", "host_a"), True)

# [7]
inv._save_inventory("demo", {"inventory": [{"item_id": "host_a", "quantity": 1}, {"item_id": "item_p", "quantity": 1}]})
check("[7] inventory hides the part", [e["item_id"] for e in inv.get_character_inventory("demo")["inventory"]],
      ["host_a"])
check("[7] stored entry kept (no cleanup)", sorted(e["item_id"] for e in inv._load_inventory("demo")["inventory"]),
      ["host_a", "item_p"])
loc = get_location_by_id("loc1")
loc["rooms"][0]["items"].append({"item_id": "item_p", "quantity": 1})
upsert_location(loc, sync_world=False)
check("[7] room hides the part", [e["item_id"] for e in inv.get_room_items("loc1", "r1")], ["host_a"])

# [8]
check("[8] resolve part", inv.resolve_item_id("Oak Buckle"), None)
check("[8] resolve part id", inv.resolve_item_id("item_p"), None)
check("[8] resolve host", inv.resolve_item_id("Copper Belt"), "host_a")

# [9]
calls = []
inv._invalidate_renders_for_item = lambda iid: calls.append(iid)
inv.update_item("item_p", {"prompt_fragment": "a copper buckle with an oak leaf"})
check("[9] part text invalidates its hosts", sorted(calls), ["host_a", "host_b", "item_p"])
calls.clear()
inv.update_item("item_p", {"description": "only the description"})
check("[9] other part fields invalidate nothing", calls, [])
calls.clear()
inv.update_item("host_a", {"outfit_piece": {**piece_a, "jewellery": {"kind": "belt", "buckle": {"item": "item_q"}}}})
check("[9] host relink invalidates the host", calls, ["host_a"])

if FAIL:
    print(f"\n{len(FAIL)} check(s) failed: {FAIL}")
    sys.exit(1)
print("\nall checks passed")
