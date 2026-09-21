#!/usr/bin/env python3
"""Smoke: the room census of ``places`` is ONE query, not one profile per character.

Usage:
    ./.venv/bin/python scripts/smoke_places_census.py

Throwaway storage (tempfile + ``paths.init``), no server, no world DB of a real
world, no LLM. ``places.room_places`` is stubbed, so nothing here needs scene
geometry — this file is about WHO is in the room, not about where the chairs are.

WHY (DATA-10 of the 2026-09-20 review)
--------------------------------------
``places._present`` used to loop over ``list_available_characters()`` and load a
FULL profile per name just to keep the ones whose ``current_location`` /
``current_room`` match. ``assign`` calls that from INSIDE
``keyed_lock("places", loc)``, and ``room_offer`` runs it once per chat turn, so
a 40-character world paid 40 profile loads (2 SELECTs + a template deepcopy +
the soul files each) for a single character sitting down — while holding the
lock every other sitter in that location waits on.

The three fields live in two places, which is why the replacement is a join:
``current_location``/``current_room`` are COLUMNS of ``character_state``
(``character._STATE_COLS``), ``place`` is an ordinary ``profile_json`` key (it
is NOT in ``character._STATE_META_KEYS`` — checked in [4] below, because the
whole query is wrong if that ever moves).

THE FIXTURE, and every expectation derived from it by hand
----------------------------------------------------------
One location ``house`` with the rooms ``lounge`` and ``kitchen``, plus a second
location ``shed``. Eight rows in ``characters``:

    Ann      house/lounge    place {id s1, slot 0, room_id lounge}
    Bob      house/lounge    place {id s2, slot 1, room_id lounge}
    Cid      house/lounge    NO place key at all          (standing)
    Dee      house/lounge    place null                   (stood up)
    Eve      house/kitchen   place {id s1, slot 0, room_id kitchen}
    Fay      shed/lounge     place {id s1, slot 0, room_id lounge}
    Pia      house/lounge    place {id s2, slot 0, …}     status = 'pooled'
    _sys     house/lounge    place {id s2, slot 0, …}     underscore name

Expected, by hand:

  [1] ``_present(house, lounge)`` == exactly [Ann, Bob, Cid, Dee], in name
      order. Eve is in another ROOM, Fay in another LOCATION, Pia is pooled
      (``list_available_characters`` gate — a pooled NPC stands nowhere) and
      ``_sys`` is no character (leading underscore). Each entry carries the
      ``place`` dict it was given, and ``current_location``/``current_room``
      of the room asked for. Cid's and Dee's place is None.

  [2] The OLD loop, re-implemented in this file exactly as it stood
      (``list_available_characters`` + ``get_character_profile`` + the two
      string comparisons), returns the SAME names and the SAME place dicts.
      That is the "same results" half of the fix: the reference is the old
      code, not a snapshot of the new one.

  [3] The LOAD COUNTER. ``character.get_character_profile`` is wrapped with a
      counter and ``places.occupancy(house, lounge)`` is called once.
        * expected AFTER the fix:  0 profile loads
        * the old loop needs one per ROSTER character = 6 (Ann, Bob, Cid, Dee,
          Eve, Fay — pooled and underscore names are filtered before the load)
      The check asserts 0, and the same counter is asserted to be 6 for the
      re-implemented old loop in the very same fixture — so this file fails on
      the old code by construction and states the number it saves.
      ``occupancy`` itself is checked to be unchanged: {s1: [(Ann, 0)],
      s2: [(Bob, 1)]} — Cid/Dee hold nothing, Eve's lounge-looking place is in
      the kitchen, Fay's is in another house.

  [4] ``place`` is a ``profile_json`` key, not ``character_state``: the raw
      row of ``characters`` has it and ``character_state.meta`` does not, and
      ``"place" not in character._STATE_META_KEYS``.

  [5] ``location_occupancy(house)`` — the whole-location variant — is
      {lounge: {s1: [(Ann, 0)], s2: [(Bob, 1)]}, kitchen: {s1: [(Eve, 0)]}}
      and costs 0 profile loads as well. Fay (other location), Pia, _sys are
      absent; Cid/Dee hold nothing.

  [6] Robustness: a row whose ``profile_json`` is not JSON at all does not
      abort the census — the other characters are still found. (``json_valid``
      guards the ``json_extract``; without it SQLite aborts the statement and
      NOBODY is in the room any more.)
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="places-census-smoke-"))

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import places  # noqa: E402
from app.models import character as ch  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


# ── fixture ─────────────────────────────────────────────────────────────
HOUSE, SHED = "house", "shed"
LOUNGE, KITCHEN = "lounge", "kitchen"

PEOPLE = [
    ("Ann", HOUSE, LOUNGE, {"id": "s1", "slot": 0, "room_id": LOUNGE}, ""),
    ("Bob", HOUSE, LOUNGE, {"id": "s2", "slot": 1, "room_id": LOUNGE}, ""),
    ("Cid", HOUSE, LOUNGE, "MISSING", ""),
    ("Dee", HOUSE, LOUNGE, None, ""),
    ("Eve", HOUSE, KITCHEN, {"id": "s1", "slot": 0, "room_id": KITCHEN}, ""),
    ("Fay", SHED, LOUNGE, {"id": "s1", "slot": 0, "room_id": LOUNGE}, ""),
    ("Pia", HOUSE, LOUNGE, {"id": "s2", "slot": 0, "room_id": LOUNGE}, "pooled"),
    ("_sys", HOUSE, LOUNGE, {"id": "s2", "slot": 0, "room_id": LOUNGE}, ""),
]

for name, loc, room, place, status in PEOPLE:
    ch.save_character_profile(name, {"character_name": name}, create_new=True)
    # Location and room FIRST: a room change stands the character up
    # (``save_character_current_room`` -> ``places.release``), so a place
    # written before the move would be cleared again.
    ch.save_character_current_location(name, loc)
    ch.save_character_current_room(name, room)
    if place != "MISSING":
        profile = ch.get_character_profile(name) or {}
        profile["place"] = place
        ch.save_character_profile(name, profile)
    if status:
        ch.set_character_status(name, status)

# The room inventory is irrelevant for the census — stub it so this file needs
# no scene geometry. s1 has one slot, s2 two.
PLACES = {
    "s1": {"id": "s1", "group": "seat", "label": "Seat", "capacity": 1,
           "slots": [[0.0, 0.0]], "facing": 0.0, "y_world": 0.0,
           "root_offset": 0.0, "source": "room", "room_id": ""},
    "s2": {"id": "s2", "group": "seat", "label": "Seat", "capacity": 2,
           "slots": [[1.0, 0.0], [2.0, 0.0]], "facing": 0.0, "y_world": 0.0,
           "root_offset": 0.0, "source": "room", "room_id": ""},
}


def _stub_room_places(location_id: str, room_id: str):
    if location_id not in (HOUSE, SHED) or room_id not in (LOUNGE, KITCHEN):
        return []
    return [dict(p, room_id=room_id) for p in PLACES.values()]


places.room_places = _stub_room_places


# ── the OLD loop, as it stood before the fix (the reference) ────────────
def old_present(location_id: str, room_id: str):
    """``places._present`` verbatim as of commit 1a578a48 — the reference
    this fix has to reproduce."""
    out = []
    for n in ch.list_available_characters():
        prof = ch.get_character_profile(n) or {}
        if (prof.get("current_location") or "") == location_id \
                and (prof.get("current_room") or "") == room_id:
            out.append((n, prof))
    return out


# ── the load counter ────────────────────────────────────────────────────
_real_get_profile = ch.get_character_profile
LOADS = {"n": 0}


def counting_get_profile(name):
    LOADS["n"] += 1
    return _real_get_profile(name)


ch.get_character_profile = counting_get_profile
places.get_character_profile = counting_get_profile   # in case it is rebound


print("[1] _present: the room roster")
rows = places._present(HOUSE, LOUNGE)
names = [n for n, _ in rows]
check("names in the lounge", names == ["Ann", "Bob", "Cid", "Dee"], str(names))
by_name = dict(rows)
check("Ann's place", by_name.get("Ann", {}).get("place")
      == {"id": "s1", "slot": 0, "room_id": LOUNGE})
check("Bob's place", by_name.get("Bob", {}).get("place")
      == {"id": "s2", "slot": 1, "room_id": LOUNGE})
check("Cid has no place key -> None", by_name.get("Cid", {}).get("place") is None)
check("Dee's place is null -> None", by_name.get("Dee", {}).get("place") is None)
check("location/room carried", all(
    s.get("current_location") == HOUSE and s.get("current_room") == LOUNGE
    for _, s in rows))

print("[2] same result as the old loop")
LOADS["n"] = 0
old_rows = old_present(HOUSE, LOUNGE)
old_loads = LOADS["n"]
check("old loop finds the same names",
      [n for n, _ in old_rows] == names, str([n for n, _ in old_rows]))
check("old loop finds the same places",
      [(p.get("place") or None) for _, p in old_rows]
      == [(s.get("place") or None) for _, s in rows])
check("old loop costs one profile load per roster character (6)",
      old_loads == 6, f"{old_loads} loads")

print("[3] the new census costs no profile load")
LOADS["n"] = 0
occ = places.occupancy(HOUSE, LOUNGE)
check("occupancy unchanged",
      occ == {"s1": [("Ann", 0)], "s2": [("Bob", 1)]}, str(occ))
check("0 profile loads for one occupancy()", LOADS["n"] == 0, f"{LOADS['n']} loads")

print("[4] where the fields live")
conn = db.get_connection()
blob = conn.execute("SELECT profile_json FROM characters WHERE name='Ann'").fetchone()[0]
meta = conn.execute(
    "SELECT meta FROM character_state WHERE character_name='Ann'").fetchone()[0]
check("place is in profile_json", "place" in json.loads(blob or "{}"))
check("place is NOT in character_state.meta", "place" not in json.loads(meta or "{}"))
check("place is not a _STATE_META_KEY", "place" not in ch._STATE_META_KEYS)

print("[5] location_occupancy: whole location, still one query")
LOADS["n"] = 0
loc_occ = places.location_occupancy(HOUSE)
check("location_occupancy content",
      loc_occ == {LOUNGE: {"s1": [("Ann", 0)], "s2": [("Bob", 1)]},
                  KITCHEN: {"s1": [("Eve", 0)]}}, str(loc_occ))
check("0 profile loads for location_occupancy", LOADS["n"] == 0, f"{LOADS['n']} loads")

print("[6] a malformed profile_json does not empty the room")
with db.transaction() as c:
    c.execute("UPDATE characters SET profile_json='{not json' WHERE name='Dee'")
rows2 = [n for n, _ in places._present(HOUSE, LOUNGE)]
check("the other three are still present",
      rows2 == ["Ann", "Bob", "Cid", "Dee"], str(rows2))
occ2 = places.occupancy(HOUSE, LOUNGE)
check("occupancy survives it",
      occ2 == {"s1": [("Ann", 0)], "s2": [("Bob", 1)]}, str(occ2))

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
for f in FAILURES:
    print(f"  FAILED: {f}")
sys.exit(1 if FAILURES else 0)
