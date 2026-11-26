#!/usr/bin/env python3
"""World Dev free mode — place_character / restore_placement and the occupant
simulation of discard_preview (plan
docs/superpowers/plans/2026-11-25-world-dev-free-p3-world-systems.md, Task 8,
decision E5).

Usage: ./.venv/bin/python scripts/smoke_world_dev_place_character.py
Runs in a temp world (STORAGE_DIR / INSTANCE_DIR / ANIMATION_CLIPS_DIR temp,
paths.init before any world-DB import), no server, no LLM. Tool calls go
through world_dev_tools.run_tool exactly as the agent loop calls them.

WHAT IS CHECKED, and where every expected value comes from:

World config: game.discovery_range_m 0 (discovery by sight off — no place
becomes known by a write this smoke does not name).

Fixture (written with the core writers, no run):
  Demo Gate  id demo_gate, pos (0, 0), rooms Gatehouse (id gate_house) and
             Tower (id gate_tower), entry_room gate_house — so the arrival room
             (models.world.get_arrival_room_id: the declared entry room) is
             gate_house. No layout: the rooms have no stand geometry
             (room_stand.room_geometry needs a hull), so free_stand_point
             answers None and the tool falls back to the location centre
             (0, 0) — inside the seed square ±5 m around the pin.
  Demo Inn   id demo_inn, pos (100, 0), rooms Taproom (inn_tap) and Kitchen
             (inn_kitchen), no entry room.
  Demo Guard in demo_inn / inn_tap, pose_key "sitting_idle", position
             (101, 2) with yaw 0.5 and origin ("s1", 7) — all five position
             columns non-null, so the exact restore of each is visible.
             Known places [demo_inn].
  Demo Cook  in demo_inn / inn_kitchen, position (99, 1).
  Demo Leader + Demo Follower in demo_inn / inn_tap, one party
             (party_engine.add_to_party).
  Demo Sitter in demo_inn / inn_tap with profile.place {"id": "bench"} (seated).
  Demo Avatar in demo_inn / inn_tap, the active character of a users row
             (account.get_all_avatars reads users.settings.active_character).
  Demo Sleeper in demo_inn / inn_tap with is_sleeping True.
  Demo Flagged in demo_inn / inn_tap with profile key demo_place_flag True,
             and registry.flag_specs patched to return one FlagSpec
             (flag demo_place_flag, reset_on_location_change True).

(a) place_character{Demo Guard, demo_gate} -> ok. Profile current_location
    demo_gate, current_room gate_house, pose_key "" (the arrival rule: the
    pose belonged to the old place). Position (0, 0) (centre fallback, see
    fixture) — checked as |x| <= 5 and |z| <= 5. Known places contain
    demo_gate. state_history rows of Demo Guard unchanged and
    count_messages_involving("Demo Guard") unchanged (E5: no movement trace,
    no history). The line starts "placed Demo Guard in Demo Gate / Gatehouse
    at (0,0) — now in that room: nobody else". Journal: one write row,
    target ("character", "Demo Guard"), inverse op restore_placement.
(b) the same call again -> refused "already there".
(c) room "Attic" -> refused, the line names Gatehouse and Tower; Demo
    Follower (party) -> refused "party"; Demo Sitter -> refused "seated";
    Demo Avatar -> refused "player"; no new write row.
(d) undo(run) -> complete; read_placement("Demo Guard") equals the fixture's
    read (profile keys incl. pose_key "sitting_idle", the five pos columns);
    known places [demo_inn] again.
(e) new run: place Demo Guard in demo_gate (arrival gate_house), then
    write_placement("Demo Guard", {"current_room": "gate_tower"}, <same pos>)
    directly -> undo: not complete, one "changed since" skip with keys
    ["current_room", "known_places"]; Demo Guard stays in demo_gate /
    gate_tower (the unit rule: current_location is NOT restored) and
    demo_gate stays known (he still stands there). Cleaned up by hand.
(f) new run: create_location Demo Shed at (300, 0) (no rooms -> the arrival
    room is the ground), place Demo Cook there -> discard_preview has no line
    'stands in location <shed>'; undo complete, no occupant record, Demo Cook
    in demo_inn / inn_kitchen, the shed gone.
(f2) new run: create Demo Shack (350, 0), place Demo Cook there, then
    write_placement(Demo Cook, {"pose_key": "leaning"}, <same pos>) directly ->
    the undo will skip the placement (changed since, keys ["pose_key",
    "known_places"]: he still stands in the shack), so discard_preview HAS
    the line 'character "Demo Cook" stands in location <shack>' and the undo
    reports him as an occupant of the removed shack. Cleaned up by hand.
(g) new run: create Demo Hut (400, 0) and Demo Barn (500, 0); place Demo Cook
    into the hut (turn 1), then into the barn (turn 2) -> discard_preview has
    no "stands in" line; undo complete, Demo Cook in demo_inn / inn_kitchen.
(h) new run: update_location demo_inn adding room Cellar (the kept rooms sent
    with their ids), place Demo Guard into demo_inn / Cellar ->
    discard_preview has no "stands in room" line; undo complete, no room
    Cellar, Demo Guard in demo_inn / inn_tap.
(i) Demo Sleeper -> refused "asleep"; Demo Flagged -> refused, the line names
    demo_place_flag; under-lock re-check: _Step.writing patched so that on
    entry it sets Demo Cook's profile.place (between the up-front checks and
    the write) -> refused "seated", read_placement unchanged, newest journal
    row kind "refused".
(j) Demo Plain (a character whose stored config_json is set to "{}" — the
    column default) placed into demo_gate, then undo(run): the whole
    ``characters`` row (config_json "{}" and updated_at included) and the
    whole ``character_state`` row are equal to their reads before the call —
    the known-places writer and its undo patch only the stored
    known_locations key (character.write_known_locations), so no default
    config is written and updated_at is not bumped. Between call and undo
    the stored config_json is exactly {"known_locations": ["demo_gate"]}.
(k) the under-lock re-check also covers control and world presence:
    _Step.writing patched to make Demo Cook the active character of a
    users row on entry -> refused "player"; patched to set his status to
    character.POOLED_STATUS -> refused "not in the world"; both times
    read_placement unchanged and the newest step kind "refused".
(l) write_placement is ONE transaction: a position whose x is a dict (no
    SQLite binding) makes the single UPDATE fail -> False, and the profile
    keys given with it (current_room "inn_tap") are NOT stored either —
    read_placement equals the read before.
(m) a partial position is restored exactly: Demo Cook's row set to pos_x 99,
    pos_z NULL, pos_yaw NULL, pos_session "s9", pos_seq NULL -> read_placement
    pos == {"x": 99.0, "z": None, "yaw": None, "session": "s9", "seq": None}
    (pos is None only when all five are NULL); placed into demo_gate and
    undone -> the whole character_state row equals its read before.
(n) a character WITHOUT a character_state row (Demo Rowless: its row deleted
    after creation) -> read_placement row False; placed into demo_gate ->
    a row exists (write_placement inserts it); undo complete -> no row again.
    Second time, with current_activity "waiting" written into the inserted
    row between call and undo -> undo complete, the row is KEPT (someone
    wrote into it) with all ten placement columns NULL and current_activity
    "waiting".
(o) a player takes the character over after the placement: new run, create
    Demo Lodge (600, 0), place Demo Cook there, then make him the active
    character of a users row -> discard_preview HAS the line 'character
    "Demo Cook" stands in location <lodge>' (the simulation leaves him like
    the undo) and the undo skips the placement changed since with keys
    ["state", "known_places"]; he stays in the lodge. Cleaned up by hand.
"""
import atexit
import contextlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="smoke_wd_place_char_"))
atexit.register(shutil.rmtree, ROOT, True)
STORAGE = ROOT / "world"
STORAGE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")
(STORAGE / "config.json").write_text(json.dumps({"game": {"discovery_range_m": 0}}),
                                     encoding="utf-8")

from app.core import paths  # noqa: E402

paths.init(STORAGE)
paths.init_instance(ROOT / "instance")

from app.core import config, db  # noqa: E402

config.load(STORAGE / "config.json")
db.init_schema()

from app.core import party_engine  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core.db import get_connection, transaction  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.models import character as ch  # noqa: E402
from app.models.chat import count_messages_involving  # noqa: E402
from app.models.world import get_location_by_id, list_locations, upsert_location  # noqa: E402
from app.plugins import registry  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


GATE, INN = "demo_gate", "demo_inn"
upsert_location({"id": GATE, "name": "Demo Gate", "pos_x": 0.0, "pos_z": 0.0,
                 "entry_room": "gate_house",
                 "rooms": [{"id": "gate_house", "name": "Gatehouse"},
                           {"id": "gate_tower", "name": "Tower"}]}, sync_world=False)
upsert_location({"id": INN, "name": "Demo Inn", "pos_x": 100.0, "pos_z": 0.0,
                 "rooms": [{"id": "inn_tap", "name": "Taproom"},
                           {"id": "inn_kitchen", "name": "Kitchen"}]}, sync_world=False)
from app.models.world import get_arrival_room_id  # noqa: E402

check("fixture: gate arrival room is gate_house",
      get_arrival_room_id(get_location_by_id(GATE)) == "gate_house",
      get_location_by_id(GATE))

GUARD, COOK = "Demo Guard", "Demo Cook"


def make(name, room, extra=None, pos=(100.0, 0.0)):
    prof = {"template": "human-roleplay", "current_location": INN, "current_room": room}
    prof.update(extra or {})
    ok = ch.save_character_profile(name, prof, create_new=True)
    check(f"fixture: {name} created", ok)
    ch._write_character_pos(name, pos[0], pos[1])


make(GUARD, "inn_tap", {"pose_key": "sitting_idle"})
ch._write_character_pos(GUARD, 101.0, 2.0, origin=("s1", 7), yaw=0.5)
ch.set_known_locations(GUARD, [INN])
make(COOK, "inn_kitchen", pos=(99.0, 1.0))
make("Demo Leader", "inn_tap")
make("Demo Follower", "inn_tap")
check("fixture: party", bool(party_engine.add_to_party("Demo Leader", "Demo Follower")))
make("Demo Sitter", "inn_tap", {"place": {"id": "bench"}})
make("Demo Avatar", "inn_tap")
with transaction() as conn:
    conn.execute("INSERT INTO users (id, username, password_hash, role, settings, created_at) "
                 "VALUES ('u1', 'demo', 'x', 'user', ?, '2026-01-01T00:00:00')",
                 (json.dumps({"active_character": "Demo Avatar"}),))
make("Demo Sleeper", "inn_tap", {"is_sleeping": True})
make("Demo Flagged", "inn_tap", {"demo_place_flag": True})
_real_specs = registry.flag_specs
registry.flag_specs = lambda: [*_real_specs(), registry.FlagSpec(
    flag="demo_place_flag", package_id="demo", reset_on_location_change=True)]

GUARD_FIXTURE = ch.read_placement(GUARD)
check("fixture: guard placement read",
      GUARD_FIXTURE["profile"]["current_location"] == INN
      and GUARD_FIXTURE["profile"]["current_room"] == "inn_tap"
      and GUARD_FIXTURE["profile"]["pose_key"] == "sitting_idle"
      and GUARD_FIXTURE["pos"] == {"x": 101.0, "z": 2.0, "yaw": 0.5,
                                   "session": "s1", "seq": 7}, GUARD_FIXTURE)
COOK_FIXTURE = ch.read_placement(COOK)


def new_run(label):
    open_ = wr.open_run()
    if open_:
        wr.set_status(open_["id"], "accepted")
    return wr.create_run(label, "m", "p", "u", 80, 300000)


run = new_run("place 1")


def call(tool, args, turn=1):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


def writes():
    return [e for e in wr.entries(run, include_undone=True) if e.get("kind") == "write"]


def history_rows(name):
    return get_connection().execute(
        "SELECT COUNT(*) FROM state_history WHERE character_name=?", (name,)).fetchone()[0]


def place_of(name):
    p = ch.read_placement(name)["profile"]
    return (p.get("current_location"), p.get("current_room"))


def loc_id(name):
    return next((l["id"] for l in list_locations() if l.get("name") == name), "")


# ── (a) ──────────────────────────────────────────────────────────────────
print("(a) place_character")
hist0, chats0 = history_rows(GUARD), count_messages_involving(GUARD)
r = call("place_character", {"name": GUARD, "location_id": GATE})
check("(a) ok", r.ok and r.wrote, r)
check("(a) line", (r.line or "").startswith(
    "placed Demo Guard in Demo Gate / Gatehouse at (0,0) — now in that room: nobody else"),
    r.line)
pl = ch.read_placement(GUARD)
check("(a) location / room / pose", (pl["profile"]["current_location"],
                                     pl["profile"]["current_room"],
                                     pl["profile"]["pose_key"]) == (GATE, "gate_house", ""), pl)
pos = pl["pos"] or {}
check("(a) inside the gate outline", pos and abs(pos["x"]) <= 5 and abs(pos["z"]) <= 5, pos)
check("(a) gate known", GATE in ch.get_known_locations(GUARD), ch.get_known_locations(GUARD))
check("(a) no state_history row", history_rows(GUARD) == hist0, history_rows(GUARD))
check("(a) no chat row", count_messages_involving(GUARD) == chats0)
w = writes()
check("(a) one write row", len(w) == 1, w)
if w:
    check("(a) target", (w[0].get("target_kind"), w[0].get("target_id")) == ("character", GUARD), w[0])
    check("(a) inverse op", (w[0].get("inverse") or {}).get("op") == "restore_placement",
          w[0].get("inverse"))

# ── (b) / (c) ────────────────────────────────────────────────────────────
print("(b)/(c) refusals")
n = len(writes())
r = call("place_character", {"name": GUARD, "location_id": GATE})
check("(b) already there", not r.ok and "already there" in r.line, r.line)
r = call("place_character", {"name": GUARD, "location_id": INN, "room": "Attic"})
check("(c) unknown room lists rooms", not r.ok and "Taproom" in r.line and "Kitchen" in r.line,
      r.line)
r = call("place_character", {"name": GUARD, "location_id": GATE, "room": "Attic"})
check("(c) unknown room lists gate rooms",
      not r.ok and "Gatehouse" in r.line and "Tower" in r.line, r.line)
for who, needle in (("Demo Follower", "party"), ("Demo Sitter", "seated"),
                    ("Demo Avatar", "player")):
    r = call("place_character", {"name": who, "location_id": GATE})
    check(f"(c) {who} refused ({needle})", not r.ok and needle in r.line, r.line)
check("(c) no new write rows", len(writes()) == n, len(writes()))

# ── (d) ──────────────────────────────────────────────────────────────────
print("(d) undo")
u = wu.undo(run)
check("(d) complete", u["complete"], u)
check("(d) placement as in the fixture", wu._norm(ch.read_placement(GUARD)) == wu._norm(GUARD_FIXTURE),
      ch.read_placement(GUARD))
check("(d) known places [inn]", ch.get_known_locations(GUARD) == [INN], ch.get_known_locations(GUARD))

# ── (e) ──────────────────────────────────────────────────────────────────
print("(e) changed since")
run = new_run("place e")
r = call("place_character", {"name": GUARD, "location_id": GATE})
check("(e) ok", r.ok, r.line)
same_pos = ch.read_placement(GUARD)["pos"]
ch.write_placement(GUARD, {"current_room": "gate_tower"}, same_pos)
u = wu.undo(run)
sk = [s for s in u["skipped"] if s.get("reason") == wu.REASON_CHANGED]
check("(e) not complete", not u["complete"], u)
check("(e) keys", len(sk) == 1 and sk[0].get("keys") == ["current_room", "known_places"],
      u["skipped"])
check("(e) stays in the tower", place_of(GUARD) == (GATE, "gate_tower"), place_of(GUARD))
check("(e) gate stays known", GATE in ch.get_known_locations(GUARD),
      ch.get_known_locations(GUARD))
ch.write_placement(GUARD, GUARD_FIXTURE["profile"], GUARD_FIXTURE["pos"])
ch.set_known_locations(GUARD, [INN])
check("(e) cleaned up", wu._norm(ch.read_placement(GUARD)) == wu._norm(GUARD_FIXTURE))

# ── (f) ──────────────────────────────────────────────────────────────────
print("(f) placed into a created place")
run = new_run("place f")
r = call("create_location", {"data": {"name": "Demo Shed"}, "x": 300, "z": 0})
SHED = loc_id("Demo Shed")
check("(f) shed", r.ok and SHED, r.line)
r = call("place_character", {"name": COOK, "location_id": SHED})
check("(f) placed", r.ok, r.line)
pv = wu.discard_preview(run)
check("(f) preview: no occupant line", not any("stands in" in l for l in pv), pv)
check("(f) preview names the shed", any(f"location {SHED}" in l for l in pv), pv)
u = wu.undo(run)
check("(f) complete", u["complete"], u)
check("(f) no occupant record", not any("occupant" in s for s in u["skipped"]), u)
check("(f) cook back", place_of(COOK) == (INN, "inn_kitchen"), place_of(COOK))
check("(f) cook placement exact", wu._norm(ch.read_placement(COOK)) == wu._norm(COOK_FIXTURE))
check("(f) shed gone", get_location_by_id(SHED) is None)

# ── (f2) ─────────────────────────────────────────────────────────────────
print("(f2) a placement changed since: the occupant line appears")
run = new_run("place f2")
call("create_location", {"data": {"name": "Demo Shack"}, "x": 350, "z": 0})
SHACK = loc_id("Demo Shack")
r = call("place_character", {"name": COOK, "location_id": SHACK})
check("(f2) placed", r.ok, r.line)
ch.write_placement(COOK, {"pose_key": "leaning"}, ch.read_placement(COOK)["pos"])
pv = wu.discard_preview(run)
check("(f2) preview: occupant line",
      any(l.startswith(f'character "{COOK}" stands in location {SHACK}') for l in pv), pv)
u = wu.undo(run)
sk = [s for s in u["skipped"] if s.get("reason") == wu.REASON_CHANGED]
check("(f2) changed since, keys [pose_key, known_places]",
      len(sk) == 1 and sk[0].get("keys") == ["pose_key", "known_places"], u["skipped"])
check("(f2) occupant record", any(s.get("occupant") == COOK for s in u["skipped"]), u)
ch.write_placement(COOK, COOK_FIXTURE["profile"], COOK_FIXTURE["pos"])
ch.set_known_locations(COOK, [k for k in ch.get_known_locations(COOK) if k != SHACK])
check("(f2) cleaned up", wu._norm(ch.read_placement(COOK)) == wu._norm(COOK_FIXTURE))

# ── (g) ──────────────────────────────────────────────────────────────────
print("(g) chained placements")
run = new_run("place g")
call("create_location", {"data": {"name": "Demo Hut"}, "x": 400, "z": 0})
call("create_location", {"data": {"name": "Demo Barn"}, "x": 500, "z": 0})
HUT, BARN = loc_id("Demo Hut"), loc_id("Demo Barn")
r1 = call("place_character", {"name": COOK, "location_id": HUT})
r2 = call("place_character", {"name": COOK, "location_id": BARN}, turn=2)
check("(g) both placed", r1.ok and r2.ok, (r1.line, r2.line))
pv = wu.discard_preview(run)
check("(g) preview: no occupant line", not any("stands in" in l for l in pv), pv)
u = wu.undo(run)
check("(g) complete", u["complete"], u)
check("(g) cook back", place_of(COOK) == (INN, "inn_kitchen"), place_of(COOK))
check("(g) cook placement exact", wu._norm(ch.read_placement(COOK)) == wu._norm(COOK_FIXTURE))

# ── (h) ──────────────────────────────────────────────────────────────────
print("(h) room the run added")
run = new_run("place h")
r = call("update_location", {"id": INN, "patch": {"rooms": [
    {"id": "inn_tap", "name": "Taproom"}, {"id": "inn_kitchen", "name": "Kitchen"},
    {"name": "Cellar"}]}})
check("(h) cellar added", r.ok, r.line)
r = call("place_character", {"name": GUARD, "location_id": INN, "room": "Cellar"})
check("(h) placed in the cellar", r.ok, r.line)
pv = wu.discard_preview(run)
check("(h) preview: no occupant line", not any("stands in" in l for l in pv), pv)
u = wu.undo(run)
check("(h) complete", u["complete"], u)
check("(h) cellar gone", not any(rm.get("name") == "Cellar"
                                 for rm in get_location_by_id(INN).get("rooms") or []))
check("(h) guard back", wu._norm(ch.read_placement(GUARD)) == wu._norm(GUARD_FIXTURE),
      ch.read_placement(GUARD))

# ── (i) ──────────────────────────────────────────────────────────────────
print("(i) runtime state")
run = new_run("place i")
r = call("place_character", {"name": "Demo Sleeper", "location_id": GATE})
check("(i) asleep refused", not r.ok and "asleep" in r.line, r.line)
r = call("place_character", {"name": "Demo Flagged", "location_id": GATE})
check("(i) reset flag refused", not r.ok and "demo_place_flag" in r.line, r.line)
_real_writing = wt._Step.writing


@contextlib.contextmanager
def _sitting_down(self, reconcile):
    with keyed_lock("character_profile", COOK):
        prof = ch.get_character_profile(COOK)
        prof["place"] = {"id": "stool"}
        ch.save_character_profile(COOK, prof)
    with _real_writing(self, reconcile):
        yield


wt._Step.writing = _sitting_down
try:
    r = call("place_character", {"name": COOK, "location_id": GATE})
finally:
    wt._Step.writing = _real_writing
check("(i) re-check under the lock refused", not r.ok and "seated" in r.line, r.line)
check("(i) placement unchanged", wu._norm(ch.read_placement(COOK)) == wu._norm(COOK_FIXTURE),
      ch.read_placement(COOK))
steps = wr.steps(run)
check("(i) journal row refused", steps and steps[-1].get("kind") == "refused", steps[-1:])
registry.flag_specs = _real_specs


def row_of(table, key, name):
    r = get_connection().execute(f"SELECT * FROM {table} WHERE {key}=?", (name,)).fetchone()
    return None if r is None else tuple(r)


# ── (j) ──────────────────────────────────────────────────────────────────
print("(j) sparse config: byte-exact undo")
PLAIN = "Demo Plain"
make(PLAIN, "inn_tap")
with transaction() as conn:
    conn.execute("UPDATE characters SET config_json='{}' WHERE name=?", (PLAIN,))
char_before = row_of("characters", "name", PLAIN)
state_before = row_of("character_state", "character_name", PLAIN)
run = new_run("place j")
r = call("place_character", {"name": PLAIN, "location_id": GATE})
check("(j) placed", r.ok, r.line)
cfg_mid = get_connection().execute("SELECT config_json FROM characters WHERE name=?",
                                   (PLAIN,)).fetchone()[0]
check("(j) only the known places stored", json.loads(cfg_mid) == {"known_locations": [GATE]},
      cfg_mid)
u = wu.undo(run)
check("(j) complete", u["complete"], u)
check("(j) characters row exact", row_of("characters", "name", PLAIN) == char_before,
      (row_of("characters", "name", PLAIN), char_before))
check("(j) character_state row exact",
      row_of("character_state", "character_name", PLAIN) == state_before,
      (row_of("character_state", "character_name", PLAIN), state_before))

# ── (k) ──────────────────────────────────────────────────────────────────
print("(k) under-lock re-check: control and world presence")


def _patched_writing(effect):
    @contextlib.contextmanager
    def _w(self, reconcile):
        effect()
        with _real_writing(self, reconcile):
            yield
    return _w


def _take_over():
    with transaction() as conn:
        conn.execute("INSERT INTO users (id, username, password_hash, role, settings, "
                     "created_at) VALUES ('u2', 'demo2', 'x', 'user', ?, "
                     "'2026-01-01T00:00:00')", (json.dumps({"active_character": COOK}),))


def _release():
    with transaction() as conn:
        conn.execute("DELETE FROM users WHERE id='u2'")


def _pool():
    with transaction() as conn:
        conn.execute("UPDATE characters SET status=? WHERE name=?", (ch.POOLED_STATUS, COOK))


run = new_run("place k")
with keyed_lock("character_profile", COOK):  # the place.stool of (i) goes first
    prof = ch.get_character_profile(COOK)
    prof.pop("place", None)
    ch.save_character_profile(COOK, prof)
cook_before = ch.read_placement(COOK)
for effect, needle, undo_effect in ((_take_over, "player", _release),
                                    (_pool, "not in the world", None)):
    status_before = ch.get_character_status(COOK)
    wt._Step.writing = _patched_writing(effect)
    try:
        r = call("place_character", {"name": COOK, "location_id": GATE})
    finally:
        wt._Step.writing = _real_writing
    check(f"(k) refused ({needle})", not r.ok and needle in r.line, r.line)
    check(f"(k) placement unchanged ({needle})",
          wu._norm(ch.read_placement(COOK)) == wu._norm(cook_before), ch.read_placement(COOK))
    steps = wr.steps(run)
    check(f"(k) journal row refused ({needle})",
          steps and steps[-1].get("kind") == "refused", steps[-1:])
    if undo_effect:
        undo_effect()
    else:
        with transaction() as conn:
            conn.execute("UPDATE characters SET status=? WHERE name=?", (status_before, COOK))

# ── (l) ──────────────────────────────────────────────────────────────────
print("(l) write_placement is one transaction")
before_l = ch.read_placement(GUARD)
ok = ch.write_placement(GUARD, {"current_room": "inn_kitchen"}, {"x": {"bad": 1}, "z": 0.0})
check("(l) refused", ok is False, ok)
check("(l) nothing stored", wu._norm(ch.read_placement(GUARD)) == wu._norm(before_l),
      ch.read_placement(GUARD))

# ── (m) ──────────────────────────────────────────────────────────────────
print("(m) partial position")
with transaction() as conn:
    conn.execute("UPDATE character_state SET pos_x=99.0, pos_z=NULL, pos_yaw=NULL, "
                 "pos_session='s9', pos_seq=NULL WHERE character_name=?", (COOK,))
pm = ch.read_placement(COOK)
check("(m) raw pos", pm["pos"] == {"x": 99.0, "z": None, "yaw": None, "session": "s9",
                                   "seq": None}, pm["pos"])
state_m = row_of("character_state", "character_name", COOK)
run = new_run("place m")
r = call("place_character", {"name": COOK, "location_id": GATE})
check("(m) placed", r.ok, r.line)
u = wu.undo(run)
check("(m) complete", u["complete"], u)
check("(m) character_state row exact",
      row_of("character_state", "character_name", COOK) == state_m,
      (row_of("character_state", "character_name", COOK), state_m))
ch.write_placement(COOK, COOK_FIXTURE["profile"], COOK_FIXTURE["pos"])

# ── (n) ──────────────────────────────────────────────────────────────────
print("(n) no character_state row")
ROWLESS = "Demo Rowless"
make(ROWLESS, "inn_tap")


def _drop_row():
    with transaction() as conn:
        conn.execute("DELETE FROM character_state WHERE character_name=?", (ROWLESS,))


_drop_row()
check("(n) row flag False", ch.read_placement(ROWLESS)["row"] is False,
      ch.read_placement(ROWLESS))
run = new_run("place n")
r = call("place_character", {"name": ROWLESS, "location_id": GATE})
check("(n) placed", r.ok, r.line)
check("(n) row inserted", row_of("character_state", "character_name", ROWLESS) is not None)
u = wu.undo(run)
check("(n) complete", u["complete"], u)
check("(n) no row again", row_of("character_state", "character_name", ROWLESS) is None,
      row_of("character_state", "character_name", ROWLESS))
run = new_run("place n2")
r = call("place_character", {"name": ROWLESS, "location_id": GATE})
check("(n2) placed", r.ok, r.line)
with transaction() as conn:
    conn.execute("UPDATE character_state SET current_activity='waiting' "
                 "WHERE character_name=?", (ROWLESS,))
u = wu.undo(run)
check("(n2) complete", u["complete"], u)
kept = get_connection().execute(
    "SELECT current_location, current_room, location_changed_at, pose_key, pose_flavor, "
    "pos_x, pos_z, pos_yaw, pos_session, pos_seq, current_activity FROM character_state "
    "WHERE character_name=?", (ROWLESS,)).fetchone()
check("(n2) row kept, placement NULL",
      kept is not None and tuple(kept) == (None,) * 10 + ("waiting",),
      None if kept is None else tuple(kept))

# ── (o) ──────────────────────────────────────────────────────────────────
print("(o) taken over after the placement")
run = new_run("place o")
call("create_location", {"data": {"name": "Demo Lodge"}, "x": 600, "z": 0})
LODGE = loc_id("Demo Lodge")
r = call("place_character", {"name": COOK, "location_id": LODGE})
check("(o) placed", r.ok, r.line)
_take_over()
pv = wu.discard_preview(run)
check("(o) preview: occupant line",
      any(l.startswith(f'character "{COOK}" stands in location {LODGE}') for l in pv), pv)
u = wu.undo(run)
sk = [s for s in u["skipped"] if s.get("reason") == wu.REASON_CHANGED]
check("(o) changed since, keys [state, known_places]",
      len(sk) == 1 and sk[0].get("keys") == ["state", "known_places"], u["skipped"])
check("(o) stays in the lodge", place_of(COOK)[0] == LODGE, place_of(COOK))
_release()
ch.write_placement(COOK, COOK_FIXTURE["profile"], COOK_FIXTURE["pos"])
ch.set_known_locations(COOK, [k for k in ch.get_known_locations(COOK) if k != LODGE])

print()
if failures:
    print(f"FAILED ({len(failures)}):")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("all checks passed")
