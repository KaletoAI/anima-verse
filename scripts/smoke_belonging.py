"""Smoke: the free bed and "standing nowhere" (``app/core/belonging.py``).

Usage:
    ./.venv/bin/python scripts/smoke_belonging.py

Runs against a temp world (no server, no real world DB). The beds are given
by replacing ``places.room_places`` (the scene composer is not under test):
a room "has a bed" when its fixture lists a place of group ``lie``.

Fixture (world metres, rooms in this order):
  near  at (10, 0):  nhall (entry, no bed), nbed (bed), __ground__ (bed!)
  far   at (100, 0): fhall (entry, no bed), fbed (bed)
  hidden at (5, 0):  hbed (bed) — known to nobody
  near carries the slot {"role": "Gast", "room": "nhall"}.
Everyone knows [far, near] (that order), never "hidden".

Derivation, by hand from the rules in the module docstring:
[A] demo-s stands at (0, 0) in the open. Distances: hidden 5 m (unknown, out),
    near 10 m, far 100 m. near's rooms in order: nhall no bed, nbed bed and
    empty, so -> ("near", "nbed"). The ground's lie place never counts.
[B] demo-o stands in near/nbed -> nbed is taken; next is far: fhall no bed,
    fbed -> ("far", "fbed").
[C] and somebody walks to far/fbed -> nothing free -> None.
[D] rules._find_nearest_sleep(demo-s) with nbed free again -> ("near", "nbed").
[E] place_where_they_belong, each from "no location, room, point, journey":
    demo-npc  slot near/Gast            -> "slot",     near/nhall
    demo-home home_location far         -> "home",     far/fhall (entry room)
    demo-plan schedule: every hour far  -> "schedule", far/fhall
    demo-bed  nothing                   -> "bed",      far/fbed
              (no point and no return place: no distance, so the order of
              its known locations decides — far before near)
    demo-away avatar_only_presence, uncontrolled -> "" and still nowhere
    demo-o    stands in near already    -> ""
[F] enter_offmap_sleep from the open (point, no location):
    demo-wild without home, at (0, 0) -> near/nbed (10 m; demo-bed lies in
    far/fbed); demo-wild2 with home far -> far/fhall.
[G] Fresh start (reinit) of demo-npc drops its state row and puts it back
    into its slot: result "reset, placed: slot", location near.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="belonging-smoke-"))
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

from app.core import belonging, places  # noqa: E402
from app.models import character as ch  # noqa: E402
from app.models import world  # noqa: E402

FAILURES = []


def check(label, actual, expected):
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


BEDS = {("near", "nbed"), ("near", world.GROUND_ROOM_ID),
        ("far", "fbed"), ("hidden", "hbed")}
places.room_places = lambda loc, room: (
    [{"id": f"{loc}-{room}", "group": "lie"}] if (loc, room) in BEDS else [])

for loc_id, x, rooms, entry, extra in (
        ("near", 10.0, ["nhall", "nbed"], "nhall",
         {"npc_slots": [{"role": "Gast", "room": "nhall"}]}),
        ("far", 100.0, ["fhall", "fbed"], "fhall", {}),
        ("hidden", 5.0, ["hbed"], "hbed", {})):
    assert world.upsert_location({
        "id": loc_id, "name": loc_id, "pos_x": x, "pos_z": 0.0,
        "entry_room": entry, "rooms": [{"id": r, "name": r} for r in rooms],
        **extra}, sync_world=True), loc_id


def make(name, template="human-roleplay", profile=None, cfg=None):
    assert ch.save_character_profile(name, {"character_name": name,
                                            "template": template,
                                            **(profile or {})},
                                     create_new=True), name
    assert ch.save_character_config(name, {"known_locations": ["far", "near"],
                                           **(cfg or {})}), name
    with db.transaction() as conn:
        conn.execute("DELETE FROM character_state WHERE character_name=?", (name,))


def at(name):
    return (ch.get_character_current_location(name) or "",
            ch.get_character_current_room(name) or "")


for name in ("demo-s", "demo-o", "demo-wild", "demo-wild2"):
    make(name, cfg={"home_location": "far"} if name == "demo-wild2" else None)
for name in ("demo-s", "demo-wild", "demo-wild2"):
    ch._write_character_pos(name, 0.0, 0.0)

print("[A] nearest known bed room, never the ground")
check("demo-s", belonging.find_free_bed("demo-s"), ("near", "nbed"))

print("[B] a room somebody is in is taken")
ch.save_character_current_location("demo-o", "near")
ch.save_character_current_room("demo-o", "nbed")
check("demo-o in nbed", at("demo-o"), ("near", "nbed"))
check("demo-s", belonging.find_free_bed("demo-s"), ("far", "fbed"))

print("[C] a room somebody walks to is taken")
_walking = belonging._walking_targets
belonging._walking_targets = lambda exclude: {("far", "fbed")}
check("demo-s", belonging.find_free_bed("demo-s"), None)
belonging._walking_targets = _walking

print("[D] the rules' sleep spot without a home is the free bed")
ch.save_character_current_room("demo-o", "nhall")
from app.models.rules import _find_nearest_sleep  # noqa: E402
check("demo-s", _find_nearest_sleep("demo-s"), ("near", "nbed"))

print("[E] standing nowhere -> where it belongs")
make("demo-npc", template="npc-temporary",
     profile={"npc_slot_location": "near", "npc_slot_role": "gast"})
make("demo-home", cfg={"home_location": "far"})
make("demo-plan")
assert ch.save_character_daily_schedule("demo-plan", {
    "enabled": True,
    "slots": [{"hour": h, "location": "far", "role": "", "sleep": False}
              for h in range(24)]}), "schedule"
make("demo-bed")
make("demo-away", cfg={"avatar_only_presence": "true"})
for name, how, where in (("demo-npc", "slot", ("near", "nhall")),
                         ("demo-home", "home", ("far", "fhall")),
                         ("demo-plan", "schedule", ("far", "fhall")),
                         ("demo-bed", "bed", ("far", "fbed")),
                         ("demo-away", "", ("", "")),
                         ("demo-o", "", ("near", "nhall"))):
    check(f"{name} how", belonging.place_where_they_belong(name), how)
    check(f"{name} at", at(name), where)

print("[F] leaving the map from the open keeps a way back")
check("demo-wild leaves", ch.enter_offmap_sleep("demo-wild"), True)
_p = ch.get_character_profile("demo-wild")
check("demo-wild return", (_p.get("_offmap_return_location"),
                           _p.get("_offmap_return_room")), ("near", "nbed"))
check("demo-wild2 leaves", ch.enter_offmap_sleep("demo-wild2"), True)
_p = ch.get_character_profile("demo-wild2")
check("demo-wild2 return", (_p.get("_offmap_return_location"),
                            _p.get("_offmap_return_room")), ("far", "fhall"))

print("[G] a fresh start puts the character back")
from app.core.character_reset import reset_character  # noqa: E402
_r = reset_character("demo-npc", "reinit")
check("reset result", _r.get("character_state"), "reset, placed: slot")
check("demo-npc at", at("demo-npc")[0], "near")

if FAILURES:
    print(f"FAIL: {len(FAILURES)} check(s): {', '.join(FAILURES)}")
    sys.exit(1)
print("PASS: free bed, standing nowhere, offmap return, fresh start")
