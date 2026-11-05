#!/usr/bin/env python3
"""Smoke: the presence swap of linked characters, its refusals, the family
repair, the avatar switch and the dormancy gates (task 4 of the
linked-characters plan).

Usage:  ./.venv/bin/python scripts/smoke_dormant_swap.py

Throwaway storage + instance (``STORAGE_DIR`` / ``INSTANCE_DIR`` temp dirs,
``paths.init`` BEFORE any world-DB module), no server, no LLM.

THE SPEC (docs/superpowers/specs/2026-11-05-linked-characters-design.md:
Anti-goals, "Core: dormant status and the swap", "Swap rules (refusals)";
task-4 brief and its decisions):
  * ``swap_presence(from, to, items=…)``: one family, ``from`` present, ``to``
    dormant. ``to`` gets ``from``'s location, room, point, yaw, activity,
    pose key/flavor, feeling and seat; ``from`` becomes dormant with no
    location, room, point, seat or off-map marker and keeps its last
    placement under ``dormant_from`` (for the repair). Both statuses and
    placements are written in ONE transaction. The listed items move with
    force (``transferable`` does not block), equipped clothing never moves,
    an equipped non-clothing item is unequipped first. Every user whose
    ``settings.active_character`` is ``from`` now controls ``to`` and is
    allowed it. ``location_changed`` + ``sync_topics.moved`` are published for
    both.
  * Refused while ``from`` travels, sleeps, is in an interaction, runs a prop
    action, reads, or is in a party — the error is ``SWAP_REFUSAL_TEXT[code]``.
  * Gates: a dormant character is not agent-eligible (no bump, no hint, no
    respond turn), its scheduler job is skipped and stays stored, it is in no
    worldmap payload and in no room, the off-map wake and the takeover
    appearance leave it where it is (nowhere).
  * ``repair_families()``: none present -> the expected member (provider
    ``linked.expected_present``, absent = the leader) stands at its own stored
    placement, else at the most recent stored placement of any member, else
    nothing happens; two present -> every present member except the expected
    one (else the leader) becomes dormant; a user controlling a dormant member
    is switched to the present one. Returns the number of repaired families.

FIXTURE
    Location "Inn" (rooms taproom = entry room, cellar).
    Tilda (leader, human-roleplay) in Inn/taproom at point (1.5, 2.5), yaw
    0.75, activity "warming her hands", pose_key "sitting", pose_flavor
    "cross-legged", feeling "calm", seat {"id": "bench", "slot": 1,
    "room_id": "taproom"}, a stale off-map marker "_offmap_return_location".
    Obs (human-roleplay) in Inn/taproom. Glut + Kim: bodies of Tilda
    (create_linked -> dormant).
    Items: "ember" (transferable False) carried by Tilda; "lamp" (tool)
    carried AND equipped (equipped_items) by Tilda; "cloak" (outfit piece)
    carried AND worn (equipped_pieces outer) by Tilda.
    Users: "play" (role user) allowed [Tilda] -> [Tilda, Glut, Kim] after
    create_linked, active Tilda; "boss" (role admin) allowed [], active
    Tilda.

WHAT FOLLOWS BY HAND
[A] Each refusal state on Tilda, one at a time: swap_presence(Tilda, Glut)
    -> ok False, refusal <code>, error SWAP_REFUSAL_TEXT[code]; Glut stays
    dormant. journey (movement_target), sleeping (is_sleeping), interaction
    (a running pair interaction blob), prop_action (a running prop_action_runs
    row with actor Tilda), reading (an item-reading session at Tilda's
    place), party (Tilda leads Obs).
[B] Validation: (Tilda, Obs) -> "Tilda and Obs are not linked characters of
    one family."; (Glut, Tilda) -> "Glut does not stand in the world.";
    (Tilda, Tilda) -> "Pick two different characters of one family.".
[C] One transaction: the second presence write raises -> ok False, error
    "The swap could not be stored."; Tilda status "" at Inn, Glut "dormant"
    with no location — neither status changed.
[D] swap_presence(Tilda, Glut, items=[ember, lamp, cloak]) -> ok True.
    Glut: status "", Inn/taproom, point (1.5, 2.5), yaw 0.75, activity, pose
    key/flavor, feeling as Tilda's; seat {"id": "bench", "slot": 1,
    "room_id": "taproom"}; no dormant_from; knows Inn.
    Tilda: status "dormant", location "", room "", point None, yaw None, seat
    None, no "_offmap_return_location"; dormant_from = {location: Inn, room:
    taproom, pos_x 1.5, pos_z 2.5, pos_yaw 0.75} (+ a stamp "at").
    Items: ember and lamp with Glut, not with Tilda; lamp no longer equipped
    on Tilda; cloak stays with Tilda and stays worn.
    Users: play active Glut, allowed [Tilda, Glut, Kim]; boss active Glut,
    allowed [Glut].
    Events: location_changed Tilda (Inn -> ""), Glut ("" -> Inn, room
    taproom); moved Tilda (Inn, ""), Glut ("", Inn).
    places census of Inn/taproom: Glut on the bench, Obs; no Tilda.
[E] Gates (Tilda dormant): _is_agent_eligible(Obs) True (control) ->
    raw-dormant Obs False, bump False, add_hint False, respond-eligible False;
    Obs present again -> True. _is_agent_eligible(Tilda) False.
    Scheduler: a notify job of Tilda -> status "skipped", reason
    "character_dormant", the notify action never ran, the job still stored for
    Tilda; the same job shape for Obs -> "success", the action ran once.
    Worldmap (admin view) names: Glut and Obs, no Tilda.
    room_entry.characters_in_room(Inn, taproom) = [Glut, Obs] (sorted).
    A raw off-map marker on dormant Tilda: wake_from_offmap(Tilda) False and
    appear_in_world(Tilda) False; Tilda still has no location.
[F] Back: swap_presence(Glut, Tilda, items=[ember]) -> ok; Tilda at Inn/
    taproom (1.5, 2.5) yaw 0.75 with the bench seat, no dormant_from; Glut
    dormant with dormant_from Inn/taproom; ember with Tilda; play/boss active
    Tilda again.
[G] repair_families():
    G1 nothing broken -> 0.
    G2 none present, Tilda's own dormant_from {Inn, cellar, 3.0, 4.0, 1.25}
       -> 1; Tilda "" at Inn/cellar (3.0, 4.0) yaw 1.25, no dormant_from.
    G3 none present, Tilda without a stored placement; Glut's at "…T01",
       Kim's {Inn, taproom, 5.0, 6.0, 0.5} at "…T02" (newer) -> 1; Tilda at
       Inn/taproom (5.0, 6.0) yaw 0.5.
    G4 none present and no stored placement anywhere -> 0, everybody still
       dormant (a location is never invented).
    G5 two present (Tilda + Glut), no provider -> 1; Glut dormant with no
       location, Tilda present.
    G6 two present, provider answers "Glut" -> 1; Tilda dormant, Glut present;
       play (active Tilda) is switched to Glut.
    G7 two present, provider answers None -> 1; Glut dormant, Tilda present.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="dormant-swap-smoke-"))
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


def section(title):
    print(title)


def edit(name, **values):
    with keyed_lock("character_profile", name):
        p = ch.get_character_profile(name)
        for k, v in values.items():
            if v is None:
                p.pop(k, None)
            else:
                p[k] = v
        assert ch.save_character_profile(name, p), name


def stored_blob(name):
    row = db.get_connection().execute(
        "SELECT profile_json FROM characters WHERE name=?", (name,)).fetchone()
    return json.loads(row[0]) if row else None


def blob_set(name, **values):
    blob = stored_blob(name) or {}
    for k, v in values.items():
        if v is None:
            blob.pop(k, None)
        else:
            blob[k] = v
    with db.transaction() as conn:
        conn.execute("UPDATE characters SET profile_json=? WHERE name=?",
                     (json.dumps(blob), name))


def raw_state(name, **cols):
    sets = ", ".join(f"{k}=?" for k in cols)
    with db.transaction() as conn:
        conn.execute(f"UPDATE character_state SET {sets} WHERE character_name=?",
                     (*cols.values(), name))


def raw_status(name, status):
    with db.transaction() as conn:
        conn.execute("UPDATE characters SET status=? WHERE name=?", (status, name))


def point(name):
    row = db.get_connection().execute(
        "SELECT pos_x, pos_z, pos_yaw FROM character_state WHERE character_name=?",
        (name,)).fetchone()
    return tuple(row) if row else None


def where(name):
    p = ch.get_character_profile(name)
    return (ch.get_character_status(name), p.get("current_location", ""),
            p.get("current_room", ""))


# ── fixture ─────────────────────────────────────────────────────────────────
INN = add_location("Inn", "A stone house.")["id"]
_data = _load_world_data()
for _loc in _data.get("locations", []):
    if _loc.get("id") == INN:
        _loc["rooms"] = [{"id": "taproom", "name": "Taproom", "description": "Benches."},
                         {"id": "cellar", "name": "Cellar", "description": "Barrels."}]
        _loc["entry_room"] = "taproom"
_save_world_data(_data)

for _name in ("Tilda", "Obs"):
    assert ch.save_character_profile(_name, {"character_name": _name,
                                             "template": "human-roleplay"},
                                     create_new=True), _name
SEAT = {"id": "bench", "slot": 1, "room_id": "taproom"}
edit("Tilda", current_location=INN, current_room="taproom",
     current_activity="warming her hands", pose_key="sitting",
     pose_flavor="cross-legged", current_feeling="calm", place=SEAT,
     _offmap_return_location=INN)
ch._write_character_pos("Tilda", 1.5, 2.5, yaw=0.75)
edit("Obs", current_location=INN, current_room="taproom")

from app.core import users  # noqa: E402
PLAY = users.create_user("play", "play-password-1", allowed_characters=["Tilda"])
users.update_user(PLAY, settings={"active_character": "Tilda"})
BOSS = users.create_user("boss", "boss-password-1", role="admin", allowed_characters=[])
users.update_user(BOSS, settings={"active_character": "Tilda"})

from app.core import linked_characters as lc  # noqa: E402
assert lc.create_linked("Tilda", "Glut")["ok"]
assert lc.create_linked("Tilda", "Kim")["ok"]

from app.models import inventory as inv  # noqa: E402
inv.add_item("Ember", category="tool", transferable=False, item_id="ember")
inv.add_item("Lamp", category="tool", item_id="lamp")
inv.add_item("Cloak", category="outfit_piece", item_id="cloak",
             outfit_piece={"slots": ["outer"]})
for _iid in ("ember", "lamp", "cloak"):
    assert inv.add_to_inventory("Tilda", _iid), _iid
edit("Tilda", equipped_items=["lamp"], equipped_pieces={"outer": "cloak"})

# ── [A] refusals ────────────────────────────────────────────────────────────
section("[A] refusals")


def refused(code):
    res = lc.swap_presence("Tilda", "Glut")
    check(f"{code}: refused", (res.get("ok"), res.get("refusal"), res.get("error")),
          (False, code, lc.SWAP_REFUSAL_TEXT.get(code)))
    check(f"{code}: Glut still dormant", ch.get_character_status("Glut"), "dormant")


edit("Tilda", movement_target="somewhere")
refused("journey")
edit("Tilda", movement_target="")
edit("Tilda", is_sleeping=True)
refused("sleeping")
edit("Tilda", is_sleeping=False)
edit("Tilda", interaction={"id": "i1", "kind": "hug", "role": "a",
                           "started_at_game": "Y0001-D001T10:00:00",
                           "members": {"a": "Tilda", "b": "Obs"}})
refused("interaction")
edit("Tilda", interaction=None)
with db.transaction() as _c:
    _c.execute("INSERT INTO prop_action_runs (execution_id, actor, members, request_id, "
               "request_fingerprint, action_id, definition_revision, status, target, "
               "definition, data, created_at, updated_at) VALUES "
               "('r1', 'Tilda', '[]', 'q1', 'f', 'sit', '1', 'active', '{}', '{}', '{}', 'x', 'x')")
refused("prop_action")
with db.transaction() as _c:
    _c.execute("DELETE FROM prop_action_runs WHERE execution_id='r1'")
from app.core import item_reading  # noqa: E402
item_reading.start_session("Tilda", "ember", INN, "taproom")
refused("reading")
item_reading.end_session("Tilda", "done")
from app.core import party_engine  # noqa: E402
check("party formed", bool(party_engine.add_to_party("Tilda", "Obs")), True)
refused("party")
party_engine.leave_party("Obs")
check("no refusal left", lc.swap_refusal("Tilda"), "")

# ── [B] validation ──────────────────────────────────────────────────────────
section("[B] validation")
check("not one family", lc.swap_presence("Tilda", "Obs")["error"],
      "Tilda and Obs are not linked characters of one family.")
check("from dormant", lc.swap_presence("Glut", "Tilda")["error"],
      "Glut does not stand in the world.")
check("same name", lc.swap_presence("Tilda", "Tilda")["error"],
      "Pick two different characters of one family.")

# ── [C] one transaction ─────────────────────────────────────────────────────
section("[C] one transaction")
_orig_write = getattr(lc, "_write_presence", None)
_calls = {"n": 0}


def _second_raises(*a, **kw):
    _calls["n"] += 1
    if _calls["n"] == 2:
        raise RuntimeError("disk on fire")
    return _orig_write(*a, **kw)


if _orig_write is None:
    check("_write_presence exists", False, True)
else:
    lc._write_presence = _second_raises
    try:
        res = lc.swap_presence("Tilda", "Glut")
    finally:
        lc._write_presence = _orig_write
    check("failed swap", (res.get("ok"), res.get("error")),
          (False, "The swap could not be stored."))
    check("Tilda unchanged", where("Tilda"), ("", INN, "taproom"))
    check("Glut unchanged", where("Glut"), ("dormant", "", ""))
    check("Tilda point unchanged", point("Tilda"), (1.5, 2.5, 0.75))

# ── [D] the swap ────────────────────────────────────────────────────────────
section("[D] swap Tilda -> Glut")
from app.core import state_events, sync_topics  # noqa: E402
EVENTS = []
_orig_publish = state_events.publish
_orig_moved = sync_topics.moved
state_events.publish = lambda t, c, **f: EVENTS.append(("event", t, c, f.get("from_id"),
                                                        f.get("to_id"), f.get("room_id")))
sync_topics.moved = lambda c, a, b: EVENTS.append(("moved", c, a, b))
try:
    res = lc.swap_presence("Tilda", "Glut", items=["ember", "lamp", "cloak"],
                           reason="smoke")
finally:
    state_events.publish = _orig_publish
    sync_topics.moved = _orig_moved
check("swap ok", (res.get("ok"), res.get("error")), (True, ""))
_g = ch.get_character_profile("Glut")
check("Glut placed", where("Glut"), ("", INN, "taproom"))
check("Glut point + yaw", point("Glut"), (1.5, 2.5, 0.75))
check("Glut activity/pose/feeling",
      (_g.get("current_activity"), _g.get("pose_key"), _g.get("pose_flavor"),
       _g.get("current_feeling")),
      ("warming her hands", "sitting", "cross-legged", "calm"))
check("Glut seat", _g.get("place"), SEAT)
check("Glut no dormant_from", "dormant_from" in (stored_blob("Glut") or {}), False)
check("Glut knows Inn", INN in ch.get_known_locations("Glut"), True)
_t = ch.get_character_profile("Tilda")
check("Tilda dormant", where("Tilda"), ("dormant", "", ""))
check("Tilda point", point("Tilda"), (None, None, None))
check("Tilda seat", _t.get("place"), None)
check("Tilda off-map marker", "_offmap_return_location" in (stored_blob("Tilda") or {}), False)
_df = dict((stored_blob("Tilda") or {}).get("dormant_from") or {})
check("Tilda dormant_from has a stamp", bool(_df.pop("at", "")), True)
check("Tilda dormant_from", _df, {"location": INN, "room": "taproom",
                                  "pos_x": 1.5, "pos_z": 2.5, "pos_yaw": 0.75})
check("ember moved (not transferable)",
      (inv.has_item("Glut", "ember"), inv.has_item("Tilda", "ember")), (True, False))
check("lamp moved", (inv.has_item("Glut", "lamp"), inv.has_item("Tilda", "lamp")), (True, False))
check("lamp unequipped on Tilda", inv.get_equipped_items("Tilda"), [])
check("cloak stays worn", (inv.has_item("Tilda", "cloak"), inv.has_item("Glut", "cloak"),
                           inv.get_equipped_pieces("Tilda")), (True, False, {"outer": "cloak"}))
_play = users.get_user_by_id(PLAY)
check("play active", _play["settings"].get("active_character"), "Glut")
check("play allowed", _play["allowed_characters"], ["Tilda", "Glut", "Kim"])
_boss = users.get_user_by_id(BOSS)
check("boss active", _boss["settings"].get("active_character"), "Glut")
check("boss allowed", _boss["allowed_characters"], ["Glut"])
check("events", sorted(EVENTS, key=repr), sorted([
    ("event", "location_changed", "Tilda", INN, "", ""),
    ("event", "location_changed", "Glut", "", INN, "taproom"),
    ("moved", "Tilda", INN, ""),
    ("moved", "Glut", "", INN)], key=repr))
from app.core import places  # noqa: E402
check("census", [(n, r, p) for n, r, p in places._census(INN, "taproom")],
      [("Glut", "taproom", SEAT), ("Obs", "taproom", None)])

# ── [E] gates ───────────────────────────────────────────────────────────────
section("[E] dormancy gates")
from app.core import agent_loop as al  # noqa: E402
check("Obs eligible (control)", al._is_agent_eligible("Obs"), True)
raw_status("Obs", "dormant")
check("dormant Obs not eligible", al._is_agent_eligible("Obs"), False)
_loop = al.AgentLoop()
check("bump dormant", _loop.bump("Obs", hint="hello"), False)
check("add_hint dormant", _loop.add_hint("Obs", "hello"), False)
check("respond dormant", al._is_respond_eligible("Obs"), False)
raw_status("Obs", "")
check("Obs eligible again", al._is_agent_eligible("Obs"), True)
check("dormant Tilda not eligible", al._is_agent_eligible("Tilda"), False)

from app.scheduler.scheduler_manager import SchedulerManager  # noqa: E402
MANAGER = SchedulerManager.__new__(SchedulerManager)
RAN = []
MANAGER._action_notify = lambda action, agent: (RAN.append(agent), {"success": True})[1]
MANAGER.jobs_data = {"jobs": [], "metadata": {}}
for _who in ("Tilda", "Obs"):
    _job = {"id": f"job-{_who}", "character": _who, "enabled": True,
            "trigger": {"type": "interval", "minutes": 60},
            "action": {"type": "notify", "message": "hi"}}
    MANAGER.jobs_data["jobs"].append(_job)
    ch.save_character_scheduler_jobs(_who, [_job])
_r = MANAGER._execute_job(MANAGER.jobs_data["jobs"][0])
check("dormant job skipped", (_r.get("status"), _r.get("reason")),
      ("skipped", "character_dormant"))
check("dormant job action not run", RAN, [])
check("dormant job still stored",
      [j.get("id") for j in ch.get_character_scheduler_jobs("Tilda")], ["job-Tilda"])
_r = MANAGER._execute_job(MANAGER.jobs_data["jobs"][1])
check("present job runs (control)", (_r.get("status"), RAN), ("success", ["Obs"]))

try:
    from app.core.world_ops import build_worldmap_payload
    _names = sorted(c.get("name") for c in build_worldmap_payload(None, show_all=True)
                    .get("characters", []))
except Exception as _we:  # noqa: BLE001
    _names = f"error: {_we}"
check("worldmap characters", _names, ["Glut", "Obs"])
from app.core.room_entry import characters_in_room  # noqa: E402
check("characters_in_room", sorted(characters_in_room(INN, "taproom")), ["Glut", "Obs"])
blob_set("Tilda", _offmap_return_location=INN, _offmap_return_room="taproom")
check("wake_from_offmap dormant", ch.wake_from_offmap("Tilda"), False)
check("appear_in_world dormant", ch.appear_in_world("Tilda"), False)
check("Tilda still nowhere", where("Tilda"), ("dormant", "", ""))
blob_set("Tilda", _offmap_return_location=None, _offmap_return_room=None)

# ── [F] back ────────────────────────────────────────────────────────────────
section("[F] swap Glut -> Tilda")
res = lc.swap_presence("Glut", "Tilda", items=["ember"])
check("back ok", (res.get("ok"), res.get("error")), (True, ""))
check("Tilda placed", where("Tilda"), ("", INN, "taproom"))
check("Tilda point + yaw", point("Tilda"), (1.5, 2.5, 0.75))
check("Tilda seat", ch.get_character_profile("Tilda").get("place"), SEAT)
check("Tilda no dormant_from", "dormant_from" in (stored_blob("Tilda") or {}), False)
check("Glut dormant", where("Glut"), ("dormant", "", ""))
_gdf = dict((stored_blob("Glut") or {}).get("dormant_from") or {})
check("Glut dormant_from", (_gdf.get("location"), _gdf.get("room")), (INN, "taproom"))
check("ember back", (inv.has_item("Tilda", "ember"), inv.has_item("Glut", "ember")),
      (True, False))
check("play/boss back", (users.get_user_by_id(PLAY)["settings"].get("active_character"),
                         users.get_user_by_id(BOSS)["settings"].get("active_character")),
      ("Tilda", "Tilda"))

# ── [G] repair ──────────────────────────────────────────────────────────────
section("[G] repair_families")


def unplace_raw(name):
    raw_status(name, "dormant")
    raw_state(name, current_location="", current_room="", pos_x=None, pos_z=None,
              pos_yaw=None)
    blob_set(name, place=None)


check("G1 nothing broken", lc.repair_families(), 0)
unplace_raw("Tilda")
blob_set("Tilda", dormant_from={"location": INN, "room": "cellar", "pos_x": 3.0,
                                "pos_z": 4.0, "pos_yaw": 1.25, "at": "2026-11-05T10:00:00"})
check("G2 repaired", lc.repair_families(), 1)
check("G2 Tilda placed", where("Tilda"), ("", INN, "cellar"))
check("G2 Tilda point", point("Tilda"), (3.0, 4.0, 1.25))
check("G2 no dormant_from", "dormant_from" in (stored_blob("Tilda") or {}), False)

unplace_raw("Tilda")
blob_set("Glut", dormant_from={"location": INN, "room": "cellar", "pos_x": 9.0,
                               "pos_z": 9.0, "pos_yaw": 0.0, "at": "2026-11-05T10:00:01"})
blob_set("Kim", dormant_from={"location": INN, "room": "taproom", "pos_x": 5.0,
                              "pos_z": 6.0, "pos_yaw": 0.5, "at": "2026-11-05T10:00:02"})
check("G3 repaired", lc.repair_families(), 1)
check("G3 Tilda at the newest", (where("Tilda"), point("Tilda")),
      (("", INN, "taproom"), (5.0, 6.0, 0.5)))

unplace_raw("Tilda")
for _m in ("Glut", "Kim"):
    blob_set(_m, dormant_from=None)
check("G4 nothing to place", lc.repair_families(), 0)
check("G4 all dormant", [ch.get_character_status(m) for m in ("Tilda", "Glut", "Kim")],
      ["dormant", "dormant", "dormant"])

raw_status("Tilda", "")
raw_state("Tilda", current_location=INN, current_room="taproom", pos_x=1.0, pos_z=1.0)
raw_status("Glut", "")
raw_state("Glut", current_location=INN, current_room="cellar", pos_x=2.0, pos_z=2.0)
check("G5 repaired", lc.repair_families(), 1)
check("G5 Glut out", where("Glut"), ("dormant", "", ""))
check("G5 Tilda stays", where("Tilda"), ("", INN, "taproom"))

from app.core import hooks  # noqa: E402
hooks.register_provider("linked.expected_present",
                        lambda leader: "Glut" if leader == "Tilda" else None,
                        owner="smoke")
raw_status("Glut", "")
raw_state("Glut", current_location=INN, current_room="cellar", pos_x=2.0, pos_z=2.0)
check("G6 repaired", lc.repair_families(), 1)
check("G6 Tilda out", where("Tilda"), ("dormant", "", ""))
check("G6 Glut stays", where("Glut"), ("", INN, "cellar"))
check("G6 play switched", users.get_user_by_id(PLAY)["settings"].get("active_character"),
      "Glut")
hooks.unregister_owned_providers("smoke")
hooks.register_provider("linked.expected_present", lambda leader: None, owner="smoke")
raw_status("Tilda", "")
raw_state("Tilda", current_location=INN, current_room="taproom", pos_x=1.0, pos_z=1.0)
check("G7 repaired", lc.repair_families(), 1)
check("G7 Glut out", where("Glut"), ("dormant", "", ""))
check("G7 Tilda stays", where("Tilda"), ("", INN, "taproom"))
hooks.unregister_owned_providers("smoke")

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
