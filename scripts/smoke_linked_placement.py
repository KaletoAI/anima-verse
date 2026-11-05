"""Smoke: a linked family has ONE place — the place of the member standing
in the world; a dormant member never gets one of its own.

Usage:
    ./.venv/bin/python scripts/smoke_linked_placement.py

Runs against a temp world (no server, no real world DB).

Derivation (docs/superpowers/specs/2026-11-05-linked-characters-design.md,
"Dormant status": only one family member stands in the world, the others
stand nowhere; user ruling 2026-11-06: "the location of linked characters
must be in sync"):

Fixture: locations Inn (rooms taproom [entry], cellar) and Mill (room yard
[entry]); Tilda in Inn/cellar; Glut = create_linked(Tilda, "Glut") — dormant,
unplaced. Obs (unlinked) in Inn/taproom.

[A] placement_owner: (Glut) "Tilda" (dormant body -> the member standing),
    (Tilda) "Tilda", (Obs) "Obs". With Tilda raw-dormant too (nobody
    stands): (Glut) "" and (Tilda) "".
[B] The admin view of Glut is the family's place:
    build_current_location_payload(Glut) current_location_id = Inn,
    current_room "cellar", synced_with "Tilda"; of Tilda: synced_with "".
[C] Setting the place of the dormant member moves the one standing:
    save_character_current_location(Glut, Mill) -> Tilda's location Mill,
    Glut's raw location "" and status still "dormant".
    save_character_current_room(Glut, "yard") -> Tilda's room "yard",
    Glut's raw room "".
[D] The admin routes: apply_place_on_map(Glut, {location_id: Inn,
    current_room: cellar}) -> response character "Tilda"; Tilda in
    Inn/cellar, Glut raw "". apply_current_location(Glut, {current_location:
    Mill}) -> character "Tilda"; Tilda in Mill.
[E] A whole-profile save never gives the dormant member a place:
    edit(Glut, current_location=Inn, current_room=taproom) -> Glut's raw
    location "" and room "", Tilda still in Mill.
[F] Nobody of the family stands in the world (Tilda raw-dormant):
    apply_place_on_map(Glut, Inn) -> 409 "Nobody of Glut's linked family
    stands in the world." and Glut stays unplaced; the payload of Glut has
    current_location_id "" and synced_with "".
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="linked-placement-smoke-"))
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

from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.models import character as ch  # noqa: E402
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


def edit(name, **values):
    with keyed_lock("character_profile", name):
        p = ch.get_character_profile(name)
        p.update(values)
        assert ch.save_character_profile(name, p), name


def raw(name):
    row = db.get_connection().execute(
        "SELECT current_location, current_room FROM character_state WHERE character_name=?",
        (name,)).fetchone()
    return (row[0] or "", row[1] or "") if row else ("", "")


def raw_status(name, status):
    with db.transaction() as conn:
        conn.execute("UPDATE characters SET status=? WHERE name=?", (status, name))


class Req:
    cookies: dict = {}
    headers: dict = {}

    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


# ── fixture ─────────────────────────────────────────────────────────────────
INN = add_location("Inn", "A stone house.")["id"]
MILL = add_location("Mill", "A water mill.")["id"]
_data = _load_world_data()
for _loc in _data.get("locations", []):
    if _loc.get("id") == INN:
        _loc["rooms"] = [{"id": "taproom", "name": "Taproom", "description": "Benches."},
                         {"id": "cellar", "name": "Cellar", "description": "Barrels."}]
        _loc["entry_room"] = "taproom"
    if _loc.get("id") == MILL:
        _loc["rooms"] = [{"id": "yard", "name": "Yard", "description": "Mud."}]
        _loc["entry_room"] = "yard"
_save_world_data(_data)

for _name in ("Tilda", "Obs"):
    assert ch.save_character_profile(_name, {"character_name": _name,
                                             "template": "human-roleplay"},
                                     create_new=True), _name
edit("Tilda", current_location=INN, current_room="cellar")
edit("Obs", current_location=INN, current_room="taproom")

from app.core import linked_characters as lc  # noqa: E402
assert lc.create_linked("Tilda", "Glut")["ok"]
assert ch.get_character_status("Glut") == "dormant"

# ── [A] ─────────────────────────────────────────────────────────────────────
print("[A] placement_owner")
check("owner(Glut)", lc.placement_owner("Glut"), "Tilda")
check("owner(Tilda)", lc.placement_owner("Tilda"), "Tilda")
check("owner(Obs)", lc.placement_owner("Obs"), "Obs")
raw_status("Tilda", "dormant")
check("owner(Glut) nobody stands", lc.placement_owner("Glut"), "")
check("owner(Tilda) nobody stands", lc.placement_owner("Tilda"), "")
raw_status("Tilda", "")

# ── [B] ─────────────────────────────────────────────────────────────────────
print("[B] admin view")
from app.core import character_ops  # noqa: E402
_p = character_ops.build_current_location_payload("Glut")
check("Glut payload location", _p.get("current_location_id"), INN)
check("Glut payload room", _p.get("current_room"), "cellar")
check("Glut payload synced_with", _p.get("synced_with"), "Tilda")
check("Tilda payload synced_with",
      character_ops.build_current_location_payload("Tilda").get("synced_with"), "")

# ── [C] ─────────────────────────────────────────────────────────────────────
print("[C] setters")
ch.save_character_current_location("Glut", MILL)
check("Tilda moved to Mill", raw("Tilda")[0], MILL)
check("Glut unplaced", raw("Glut")[0], "")
check("Glut still dormant", ch.get_character_status("Glut"), "dormant")
ch.save_character_current_room("Glut", "yard")
check("Tilda room yard", raw("Tilda")[1], "yard")
check("Glut room empty", raw("Glut")[1], "")

# ── [D] ─────────────────────────────────────────────────────────────────────
print("[D] admin routes")
_r = asyncio.run(character_ops.apply_place_on_map("Glut", {"location_id": INN,
                                                           "current_room": "cellar"}))
check("place-on-map answers for Tilda", _r.get("character"), "Tilda")
check("Tilda in Inn/cellar", raw("Tilda"), (INN, "cellar"))
check("Glut unplaced after place-on-map", raw("Glut"), ("", ""))
_r = asyncio.run(character_ops.apply_current_location("Glut", Req({"current_location": MILL})))
check("current-location answers for Tilda", _r.get("character"), "Tilda")
check("Tilda in Mill", raw("Tilda")[0], MILL)
check("Glut unplaced after current-location", raw("Glut"), ("", ""))

# ── [E] ─────────────────────────────────────────────────────────────────────
print("[E] profile save")
edit("Glut", current_location=INN, current_room="taproom")
check("Glut no place from a profile save", raw("Glut"), ("", ""))
check("Tilda unchanged", raw("Tilda")[0], MILL)

# ── [F] ─────────────────────────────────────────────────────────────────────
print("[F] nobody stands")
raw_status("Tilda", "dormant")
try:
    asyncio.run(character_ops.apply_place_on_map("Glut", {"location_id": INN}))
    check("place-on-map refused", "no error", 409)
except HTTPException as e:
    check("place-on-map refused", (e.status_code, e.detail),
          (409, "Nobody of Glut's linked family stands in the world."))
check("Glut still unplaced", raw("Glut"), ("", ""))
_p = character_ops.build_current_location_payload("Glut")
check("payload nobody: location", _p.get("current_location_id"), "")
check("payload nobody: synced_with", _p.get("synced_with"), "")

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
