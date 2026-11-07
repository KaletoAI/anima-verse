#!/usr/bin/env python3
"""Smoke run: the room roster reads every place in ONE query, same answer.

``room_entry.characters_in_room`` used to ask ``get_character_current_location``
and ``get_character_current_room`` for every roster character — a full
``get_character_profile`` each (JSON parse, config overlay, linked-character
overlay, soul files) for two values that live in ``character_state``. Its
default path now reads them all through ``character.list_character_places``.
This check pins that the answer did not change.

Runs against a THROWAWAY storage + instance directory — never a real world,
no server, no LLM/image call.

The seed (metres; INN and MARKET are 10 m squares):

    INN    at (0, 0)    rooms  lounge "Lounge", kitchen "Kitchen"
    MARKET at (100, 0)  room   stall "Stall"

    ann      INN/lounge                       (real setters)
    ben      INN, room stored as the NAME "Lounge" (historical value, raw SQL)
    cid      INN/kitchen
    dee      MARKET/stall
    eve      INN/lounge, the player's AVATAR (set_active_character)
    fin      INN/lounge, then a journey to MARKET; one ticker pass at t = 2 s
             puts its point at (0, 2) — inside INN, so INN stays its nearest
             cell and the ticker writes no new location (room untouched)
    gus      INN/lounge, the same route started 28 s earlier: at t = 30 s its
             point is (0, 30), outside every footprint -> location "" and,
             with the location change, room ""
    hal      linked LEADER, status 'dormant', a stale INN/lounge state row
    hal_fox  linked BODY of hal (linked_to), standing in INN/lounge
    ivy      status 'pooled', a stale INN/lounge state row
    _frame   internal system row, INN/lounge state
    admin    reserved name, INN/lounge state
    jon      profile_json '{broken' (not JSON), INN/lounge state row
    kim      profile_json '[1]' (JSON, but no object), INN/lounge state row
    lou      profile_json '{"mood": NaN}' (Python's json reads NaN), INN/lounge
    max      NO state row; profile_json claims INN/lounge
    ned      INN, room stored as " kitchen " (padded, raw SQL)

Hand-derived expectations
-------------------------

Rules the expectations come from (``get_character_profile``): the state row
OVERWRITES the profile's ``current_location``/``current_room``, and an absent
state row overwrites them with ""; a ``profile_json`` that does not parse to
a JSON object yields the empty default profile, which has no place at all.
The roster is ``list_available_characters()``: no ``_`` names, no reserved
names, no pooled, no dormant row, ordered by name (SQLite BINARY).

[1] Roster = ann ben cid dee eve fin gus hal_fox jon kim lou max ned
    (hal dormant, ivy pooled, _frame internal, admin reserved).
    ``list_character_places()`` equals, value for value,
        ann (INN, lounge)      ben (INN, "Lounge")   cid (INN, kitchen)
        dee (MARKET, stall)    eve (INN, lounge)     fin (INN, lounge)
        gus ("", "")           hal_fox (INN, lounge) jon ("", "")
        kim ("", "")           lou (INN, lounge)     max ("", "")
        ned (INN, " kitchen ")
    and equals ``{n: (get_character_current_location(n),
    get_character_current_room(n)) for n in list_available_characters()}``
    — the per-character readers' own answer, in the same order.

[2] ``characters_in_room`` (room ids and names both match; rooms stripped):
        (INN, "lounge")             -> ann ben eve fin hal_fox lou
        (INN, "Lounge")  (by name)  -> the same six
        (INN, "kitchen")            -> cid ned
        (INN, "")  whole location   -> ann ben cid eve fin hal_fox lou ned
        (MARKET, "")                -> dee
        (INN, "lounge", exclude=eve)-> ann ben fin hal_fox lou
        ("", "")   "no location"    -> gus jon kim max
        (INN, "attic")  no such room-> []

[3] The default path of ``characters_in_room`` loads NO profile: 0
    ``get_character_profile`` calls for each query of [2] (counted by
    replacing the function on ``app.models.character``). The d27a616f
    revision of ``app/core/room_entry.py`` (before the bulk reader), loaded
    from git as a second module, gives the identical lists for every query
    of [2] and loads at least one profile per roster character for the
    first query (>= 13). Skipped with a notice when git is unavailable.

The per-character readers log jon and kim at ERROR with a traceback — that is
their documented reaction to an unreadable profile, not a failure here.

Usage:  ./.venv/bin/python scripts/smoke_room_occupancy_bulk.py
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

STORAGE = Path(tempfile.mkdtemp(prefix="room-occupancy-smoke-"))
INSTANCE = Path(tempfile.mkdtemp(prefix="room-occupancy-instance-"))
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(INSTANCE)
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="room-occupancy-clips-")

from app.core import paths  # noqa: E402

paths.init(STORAGE)
paths.init_instance(INSTANCE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import linked_characters, room_entry, timeutils, travel_engine  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models import character as character_mod  # noqa: E402
from app.models.account import get_active_character, set_active_character  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_current_location, get_character_current_room,
    get_character_profile, list_available_characters, list_character_places,
    save_character_current_location, save_character_current_room,
    save_character_profile)
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location, update_location_position)

FAILURES = []
CHECKED = 0
BASE = "d27a616f"


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


# ── clocks: motion pinned (the ticker's input), calendar standing still ──
START = 1000.0
_MOTION = [START]
timeutils.motion_time = lambda: _MOTION[0]
timeutils.motion_rate = lambda: 1.0
set_game_factor(0.0)
set_game_time(GameTime.parse("Y0001-D001T12:00:00"))


def square(loc_id: str) -> None:
    """A drawn, centred 10 m square with one passage south (edge 2)."""
    data = _load_world_data()
    for loc in data["locations"]:
        if loc["id"] == loc_id:
            map3d = dict(loc.get("map3d") or {})
            map3d.update({"plan_width_m": 10.0,
                          "boundary": [[-5, -5], [5, -5], [5, 5], [-5, 5]],
                          "boundary_openings": [{"edge": 2, "at": 0.5,
                                                 "width_m": 4.0,
                                                 "type": "passage"}]})
            loc["map3d"] = map3d
    _save_world_data(data)


INN = add_location(name="Occupancy Inn", description="room roster smoke",
                   rooms=[{"id": "lounge", "name": "Lounge"},
                          {"id": "kitchen", "name": "Kitchen"}])["id"]
update_location_position(INN, 0.0, 0.0)
square(INN)
MARKET = add_location(name="Occupancy Market", description="the other place",
                      rooms=[{"id": "stall", "name": "Stall"}])["id"]
update_location_position(MARKET, 100.0, 0.0)
square(MARKET)


def person(name: str, location: str = "", room: str = "") -> None:
    save_character_profile(name, {"current_location": ""}, create_new=True)
    if location:
        save_character_current_location(name, location)
    if room:
        save_character_current_room(name, room)


def raw(sql: str, *args) -> None:
    with db.transaction() as conn:
        conn.execute(sql, args)


def raw_character(name: str, profile_json: str, location: str = "",
                  room: str = "", status: str = "") -> None:
    """A row the setters would never write: inserted straight into the DB."""
    raw("INSERT INTO characters (name, profile_json, config_json, status, "
        "created_at, updated_at) VALUES (?, ?, '{}', ?, '', '')",
        name, profile_json, status)
    if location or room:
        raw("INSERT INTO character_state (character_name, current_location, "
            "current_room) VALUES (?, ?, ?)", name, location, room)


for _n in ("ann", "eve", "fin", "gus", "hal", "hal_fox", "ivy"):
    person(_n, INN, "lounge")
person("ben", INN, "lounge")
raw("UPDATE character_state SET current_room='Lounge' WHERE character_name='ben'")
person("cid", INN, "kitchen")
person("ned", INN, "kitchen")
raw("UPDATE character_state SET current_room=' kitchen ' WHERE character_name='ned'")
person("dee", MARKET, "stall")
person("lou", INN, "lounge")
raw("""UPDATE characters SET profile_json='{"mood": NaN}' WHERE name='lou'""")

set_active_character("eve")
check("eve is the avatar", get_active_character(), "eve")

# The linked family: hal_fox stands in the world, its leader hal is dormant
# (with the state row it had before the swap — a stale row the roster hides).
raw("""UPDATE characters SET profile_json=json_set(profile_json, '$.linked_to', 'hal')
       WHERE name='hal_fox'""")
raw("UPDATE characters SET status='dormant' WHERE name='hal'")
raw("UPDATE characters SET status='pooled' WHERE name='ivy'")
linked_characters.invalidate()
check("hal_fox's mind is hal", linked_characters.mind_of("hal_fox"), "hal")

# Two travellers on the same hand-written route out of INN's south passage.
ROUTE = [[0.0, 0.0, 0.0], [0.0, 5.0, 5.0], [0.0, 30.0, 30.0],
         [60.0, 30.0, 90.0], [60.0, 0.0, 120.0], [95.0, 0.0, 155.0]]
for _n, _started in (("fin", START), ("gus", START - 28.0)):
    _prof = get_character_profile(_n)
    _prof["movement_target"] = MARKET
    _prof["journey"] = {"target": MARKET, "waypoints": [list(w) for w in ROUTE],
                        "started_at_s": _started, "speed_m_s": 1.0,
                        "entry_edge": 2}
    save_character_profile(_n, _prof)
_MOTION[0] = START + 2.0
travel_engine.advance_all_journeys()
check("fin still on its journey", bool(get_character_profile("fin").get("journey")), True)
check("gus still on its journey", bool(get_character_profile("gus").get("journey")), True)

# The rows no setter writes come LAST: ``list_active_journeys`` (the ticker's
# "who travels" query) runs ``json_extract`` over every ``profile_json``, and
# a malformed one fails that whole query — with jon already in the table the
# travellers above would not move at all.
raw_character("_frame", "{}", INN, "lounge")
raw_character("admin", "{}", INN, "lounge")
raw_character("jon", "{broken", INN, "lounge")
raw_character("kim", "[1]", INN, "lounge")
raw_character("max", '{"current_location": "%s", "current_room": "lounge"}' % INN)


# ── [1] the bulk reader ─────────────────────────────────────────────────
print("[1] list_character_places")
ROSTER = ["ann", "ben", "cid", "dee", "eve", "fin", "gus", "hal_fox",
          "jon", "kim", "lou", "max", "ned"]
check("roster", list_available_characters(), ROSTER)
EXPECTED_PLACES = {
    "ann": (INN, "lounge"), "ben": (INN, "Lounge"), "cid": (INN, "kitchen"),
    "dee": (MARKET, "stall"), "eve": (INN, "lounge"), "fin": (INN, "lounge"),
    "gus": ("", ""), "hal_fox": (INN, "lounge"), "jon": ("", ""),
    "kim": ("", ""), "lou": (INN, "lounge"), "max": ("", ""),
    "ned": (INN, " kitchen "),
}
places = list_character_places()
check("places (hand-derived)", places, EXPECTED_PLACES)
check("order = roster order", list(places), ROSTER)
per_reader = {n: (get_character_current_location(n), get_character_current_room(n))
              for n in list_available_characters()}
check("places == the per-character readers", places, per_reader)
check("same order as the per-character readers", list(places), list(per_reader))

# ── [2] characters_in_room ──────────────────────────────────────────────
print("[2] characters_in_room")
LOUNGE = ["ann", "ben", "eve", "fin", "hal_fox", "lou"]
QUERIES = [
    ("INN/lounge", (INN, "lounge"), {}, LOUNGE),
    ("INN/Lounge by name", (INN, "Lounge"), {}, LOUNGE),
    ("INN/kitchen", (INN, "kitchen"), {}, ["cid", "ned"]),
    ("INN whole location", (INN, ""), {},
     ["ann", "ben", "cid", "eve", "fin", "hal_fox", "lou", "ned"]),
    ("MARKET whole location", (MARKET, ""), {}, ["dee"]),
    ("INN/lounge without eve", (INN, "lounge"), {"exclude": "eve"},
     ["ann", "ben", "fin", "hal_fox", "lou"]),
    ("no location", ("", ""), {}, ["gus", "jon", "kim", "max"]),
    ("INN/attic (no such room)", (INN, "attic"), {}, []),
]
for label, args, kwargs, expected in QUERIES:
    check(label, room_entry.characters_in_room(*args, **kwargs), expected)

# ── [3] no profile loads, and the old revision agrees ───────────────────
print("[3] profile loads + the pre-bulk revision")
_real_gcp = character_mod.get_character_profile
_calls = {"n": 0}


def _counting_gcp(*args, **kwargs):
    _calls["n"] += 1
    return _real_gcp(*args, **kwargs)


def counted(fn, *args, **kwargs):
    character_mod.get_character_profile = _counting_gcp
    _calls["n"] = 0
    try:
        return fn(*args, **kwargs), _calls["n"]
    finally:
        character_mod.get_character_profile = _real_gcp


for label, args, kwargs, _ in QUERIES:
    _, n = counted(room_entry.characters_in_room, *args, **kwargs)
    check(f"profile loads, {label}", n, 0)

try:
    source = subprocess.run(
        ["git", "-C", str(REPO), "show", f"{BASE}:app/core/room_entry.py"],
        capture_output=True, text=True, check=True).stdout
except Exception as exc:  # no git / no history: not a defect of the fix
    print(f"  --  SKIP old-revision comparison: {exc}")
else:
    old_path = Path(tempfile.mkdtemp(prefix="room-occupancy-old-")) / "room_entry_old.py"
    old_path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("room_entry_old", old_path)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    for i, (label, args, kwargs, _) in enumerate(QUERIES):
        old_out, old_n = counted(old.characters_in_room, *args, **kwargs)
        check(f"{BASE} agrees, {label}", room_entry.characters_in_room(*args, **kwargs),
              old_out)
        if i == 0:
            CHECKED += 1
            ok = old_n >= len(ROSTER)
            print(f"  {'OK ' if ok else 'FAIL'} {BASE} profile loads, {label}: "
                  f"{old_n} (expected >= {len(ROSTER)})")
            if not ok:
                FAILURES.append(f"{BASE} profile loads")

print()
if FAILURES:
    print(f"FAIL: {len(FAILURES)} of {CHECKED} checks failed: {FAILURES}")
    sys.exit(1)
print(f"OK: all {CHECKED} checks passed")
