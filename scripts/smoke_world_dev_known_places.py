#!/usr/bin/env python3
"""Smoke: World Dev free mode — known places (gap 4, review finding 2).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p1-characters.md, Task 5.
A temp world (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM. The world config sets
game.discovery_range_m 0 (discovery.get_discovery_range_m: zero switches
discovery by sight off), so placing a new character at its home does not
also make the neighbouring places known — every known place below comes
from the home, the schedule or known_places. Tool calls go through
``world_dev_tools.run_tool`` exactly as the agent loop calls them.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_known_places.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Fixture (turn 1 of one run): create_location "Demo Hut" (A), "Demo Square"
(B), "Demo Market" (C), "Demo Well" (D, only used by (k)), each placed with a 10 m square boundary — their ids
are read back by name (the tool assigns them). "Demo Old" is saved directly
with config known_locations [A]; "Demo Keyless" is saved directly and its
config has no known_locations key (asserted on the fixture).

  (a0) create_character{data: {name: "Demo Homebody"}, home: "Demo Hut"} ->
      known == [A] exactly (home only; with discovery on, Demo Square 30 m
      away would be in sight and (a) could not tell the schedule place apart).
  (a) create_character{data: {name: "Demo Fisher"}, home: "Demo Hut",
      schedule: [{hour 9, location "Demo Square", role "fishing"}],
      known_places: ["Demo Market"]} -> ok; get_known_locations == [A, B, C]:
      apply_character (new character) sets [home, schedule place] = [A, B]
      (world_dev_apply._apply_home_and_schedule), the tool appends C.
      The result line says "knows 3 place(s)". get_character overview line
      "known places: 3 (Demo Hut, Demo Square, Demo Market)".
      data.known_places AND the argument together -> refused "given twice".
  (b) known_places ["Nowhere"] -> refused, line names "'Nowhere' is no place
      of this world"; no character "Demo Nowhere"; journal kind refused.
  (e) known_places [] -> refused "must not be empty"; known_places "Demo
      Hut" (a string, no list) -> refused; no character.
  (f) delete_created{kind: location, id: C} in the same run -> refused, the
      line names "Demo Fisher" (_references_to_location counts known places).
Turn 2 (c): update_character{Demo Old, patch: {known_places: [B, "Demo
      Market"]}} -> ok, line "known places added: Demo Square, Demo Market;
      knows 3 place(s)"; [A, B, C] (A kept, add only, order: stored first,
      then the new ones in the order sent). Its journal row's inverse is
      {op: remove_known_places, name: Demo Old, ids: [B, C], had_key: True}
      (B and C were not known before; the key existed).
      discard_preview(run) names "Demo Old" in no line (it is not created by
      the run, and undo leaves its row) and "Demo Fisher" in one line.
      undo(run, 2) -> complete; [A] again.
      update known_places [A] (already known) -> ok, "known places
      unchanged; knows 1 place(s)"; inverse ids [].
Turn 3 (d): update Demo Keyless known_places [B] -> [B], inverse had_key
      False; undo(run, 3) -> complete; the config has no known_locations
      key again (None in wu.home_schedule_state).
Turn 4 (h): models.character.write_known_locations (the one writer of the
      known places the tools use; it patches only that config key) is
      replaced by one that returns False when the list it is handed
      contains C. create_character{"Demo Failer",
      known_places: ["Demo Market"]} -> not ok; the journal line starts with
      "failed:" and names "known places"; the inverse is delete_character,
      claimed. undo(run, 4) -> complete, no "Demo Failer" row.
Turn 5 (h): same patch; update Demo Old known_places [C] -> not ok, the
      line names "known places"; known_locations stays [A].
Turn 6 (j) combined, the known-places save fails after the home write: same
      patch; "Demo Combo" (saved directly, keyless) gets update{home: "Demo
      Hut", known_places: ["Demo Market"]} -> not ok, line names "known
      places". The home write is its own done row (restore_home_schedule);
      the known-places row is refused (nothing of it stored). undo(run, 6)
      -> complete; wu.home_schedule_state(Demo Combo) equals the state
      before the call (home ABSENT, known_locations None).
Turn 7 (i) a foreign discovery between write and undo: update Demo Old
      known_places [B] -> [A, B]; then models.character.add_known_location
      (Demo Old, C) — the in-game discovery path — -> [A, B, C]; undo(run, 7)
      -> complete (no skip: the inverse removes B only) and known == [A, C]
      (the foreign C stays, nothing clobbered). C is removed again by hand
      afterwards for (g).
Turn 8 (k) a SUCCESSFUL combined update: "Demo Mover" (saved directly, no
      home, known_locations [D]) gets update{home: "Demo Hut", schedule:
      [{hour 9, location "Demo Square", role "fishing"}], known_places:
      ["Demo Square", "Demo Market"]} -> ok. The home step (apply of an
      existing character) appends home and schedule place: [D, A, B]; the
      known-places step then adds only C (B is already known) -> stored
      [D, A, B, C]. Turn-8 rows oldest first: restore_home_schedule, then
      remove_known_places{ids: [C], had_key: True}. undo(run, 8) -> complete,
      known [D], wu.home_schedule_state equal to the state before the call.
Turn 9 (l) a pending remove_known_places row whose write never happened
      (process ended between begin and the save): wr.begin(..., inverse
      {op: remove_known_places, name: Demo Old, ids: [B], had_key: True}) on
      Demo Old ([A]) -> undo(run, 9) complete, nothing skipped, still [A]
      (B is not in the list: nothing to remove).
Turn 10 (m) a stored non-list: Demo Keyless gets config known_locations
      "Demo Hut" (a string), then JSON null; update{known_places: [B]} is
      refused each time ("are no list"), no write row in turn 10, the stored
      value unchanged.
  (g) travel: travel_engine.start_journey(Demo Fisher, C) does not answer
      "unknown_target" (C is known); start_journey(Demo Old, C) does (its
      known places are [A] after (c)'s undo).
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_kp_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_kp_"))
paths.init(STORAGE)
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)
paths.get_config_path().write_text(json.dumps({"game": {"discovery_range_m": 0}}))

from app.core import config, db  # noqa: E402

config.load(paths.get_config_path())
db.init_schema()

from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
import app.models.character as mchar  # noqa: E402
from app.models.character import (character_row_exists,  # noqa: E402
                                  get_character_config, get_known_locations,
                                  save_character_config, save_character_profile)
from app.models.world import list_locations  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


run = wr.create_run("known places", "m", "p", "u", 40, 300000)


def call(turn, tool, args):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


def newest():
    return wr.steps(run)[-1]


SQUARE = [[-5, -5], [5, -5], [5, 5], [-5, 5]]
ids = {}
for i, nm in enumerate(("Demo Hut", "Demo Square", "Demo Market", "Demo Well")):
    res = call(1, "create_location", {"data": {"name": nm}, "x": 40 * i, "z": 0,
                                      "boundary": SQUARE})
    check(f"fixture {nm} created", res.ok, res)
    ids[nm] = next((l["id"] for l in list_locations() if l.get("name") == nm), "")
A, B, C, D = ids["Demo Hut"], ids["Demo Square"], ids["Demo Market"], ids["Demo Well"]

OLD, KEYLESS = "Demo Old", "Demo Keyless"
for nm in (OLD, KEYLESS):
    save_character_profile(nm, {"template": "human-roleplay"}, create_new=True)
c = dict(get_character_config(OLD) or {})
c["known_locations"] = [A]
save_character_config(OLD, c)
c = dict(get_character_config(KEYLESS) or {})
c.pop("known_locations", None)
save_character_config(KEYLESS, c)
check("fixture Demo Old knows [A]", get_known_locations(OLD) == [A], get_known_locations(OLD))
check("fixture Demo Keyless has no known_locations key",
      "known_locations" not in (get_character_config(KEYLESS) or {}))

from app.core.discovery import get_discovery_range_m  # noqa: E402

check("fixture discovery off", get_discovery_range_m() == 0, get_discovery_range_m())

# ── (a0) ───────────────────────────────────────────────────────────────
res = call(1, "create_character", {"data": {"name": "Demo Homebody"}, "home": "Demo Hut"})
check("(a0) create ok", res.ok and res.wrote, res)
check("(a0) home only -> known [A]", get_known_locations("Demo Homebody") == [A],
      get_known_locations("Demo Homebody"))

# ── (a) ────────────────────────────────────────────────────────────────
FISHER = "Demo Fisher"
res = call(1, "create_character", {
    "data": {"name": FISHER}, "home": "Demo Hut",
    "schedule": [{"hour": 9, "location": "Demo Square", "role": "fishing"}],
    "known_places": ["Demo Market"]})
check("(a) create ok", res.ok and res.wrote, res)
check("(a) known [A, B, C]", get_known_locations(FISHER) == [A, B, C],
      get_known_locations(FISHER))
check("(a) line says knows 3 place(s)", "knows 3 place(s)" in res.line, res.line)
res = call(1, "get_character", {"name": FISHER})
check("(a) overview known places line",
      "known places: 3 (Demo Hut, Demo Square, Demo Market)" in res.line, res.line)
res = call(1, "create_character", {"data": {"name": "Demo Twice", "known_places": [B]},
                                   "known_places": [C]})
check("(a) given twice refused", not res.ok and "given twice" in res.line, res)
check("(a) given twice: no row", not character_row_exists("Demo Twice"))

# ── (b) / (e) ──────────────────────────────────────────────────────────
res = call(1, "create_character", {"data": {"name": "Demo Nowhere"},
                                   "known_places": ["Nowhere"]})
check("(b) unknown place refused", not res.ok and not res.wrote, res)
check("(b) line names the place",
      "'Nowhere' is no place of this world" in res.line, res.line)
check("(b) journal kind refused", newest()["kind"] == "refused", newest())
check("(b) no row", not character_row_exists("Demo Nowhere"))
res = call(1, "create_character", {"data": {"name": "Demo Empty"}, "known_places": []})
check("(e) empty list refused", not res.ok and "must not be empty" in res.line, res)
res = call(1, "create_character", {"data": {"name": "Demo Empty"},
                                   "known_places": "Demo Hut"})
check("(e) a string refused", not res.ok and not res.wrote, res)
check("(e) no row", not character_row_exists("Demo Empty"))

# ── (f) ────────────────────────────────────────────────────────────────
res = call(1, "delete_created", {"kind": "location", "id": C})
check("(f) delete of a known place refused",
      not res.ok and FISHER in res.line, res)

# ── (c) ────────────────────────────────────────────────────────────────
res = call(2, "update_character", {"name": OLD,
                                   "patch": {"known_places": [B, "Demo Market"]}})
check("(c) update ok", res.ok and res.wrote, res)
check("(c) line known places added",
      "known places added: Demo Square, Demo Market; knows 3 place(s)" in res.line,
      res.line)
check("(c) inverse remove_known_places [B, C], had_key",
      newest()["inverse"] == {"op": "remove_known_places", "name": OLD,
                              "ids": [B, C], "had_key": True}, newest()["inverse"])
check("(c) known [A, B, C]", get_known_locations(OLD) == [A, B, C],
      get_known_locations(OLD))
prev = wu.discard_preview(run)
check("(c) discard_preview: no line for Demo Old",
      not any(f'"{OLD}"' in line for line in prev), prev)
check("(c) discard_preview: one line for Demo Fisher",
      sum(1 for line in prev if f'"{FISHER}"' in line) == 1, prev)
rep = wu.undo(run, turn=2)
check("(c) undo complete", rep["complete"], rep)
check("(c) known [A] again", get_known_locations(OLD) == [A], get_known_locations(OLD))
res = call(2, "update_character", {"name": OLD, "patch": {"known_places": [A]}})
check("(c) already known -> known places unchanged",
      res.ok and "known places unchanged; knows 1 place(s)" in res.line, res)
check("(c) already known: inverse ids []", newest()["inverse"].get("ids") == [],
      newest()["inverse"])
rep = wu.undo(run, turn=2)
check("(c) second undo complete", rep["complete"], rep)

# ── (d) ────────────────────────────────────────────────────────────────
res = call(3, "update_character", {"name": KEYLESS, "patch": {"known_places": [B]}})
check("(d) update ok", res.ok, res)
check("(d) known [B]", get_known_locations(KEYLESS) == [B], get_known_locations(KEYLESS))
check("(d) inverse had_key False", newest()["inverse"].get("had_key") is False,
      newest()["inverse"])
rep = wu.undo(run, turn=3)
check("(d) undo complete", rep["complete"], rep)
check("(d) no known_locations key again",
      "known_locations" not in (get_character_config(KEYLESS) or {})
      and wu.home_schedule_state(KEYLESS)["known_locations"] is None,
      get_character_config(KEYLESS))

# ── (h) failed save ────────────────────────────────────────────────────
_real_write_known = mchar.write_known_locations


def _fail_on_c(name, value, *a, **k):
    # The known-places writer the tools use (patches only that config key).
    if C in (value or []):
        return False
    return _real_write_known(name, value, *a, **k)


mchar.write_known_locations = _fail_on_c
try:
    res = call(4, "create_character", {"data": {"name": "Demo Failer"},
                                       "known_places": ["Demo Market"]})
finally:
    mchar.write_known_locations = _real_write_known
check("(h) create not ok", not res.ok, res)
row = newest()
check("(h) journal line failed: ... known places",
      str(row.get("line") or "").startswith("failed:")
      and "known places" in str(row.get("line")), row.get("line"))
inv = row.get("inverse") or {}
check("(h) inverse delete_character, claimed",
      inv.get("op") == "delete_character" and inv.get("claimed") is True, inv)
rep = wu.undo(run, turn=4)
check("(h) undo complete", rep["complete"], rep)
check("(h) no Demo Failer row", not character_row_exists("Demo Failer"))

mchar.write_known_locations = _fail_on_c
try:
    res = call(5, "update_character", {"name": OLD, "patch": {"known_places": [C]}})
finally:
    mchar.write_known_locations = _real_write_known
check("(h) update not ok", not res.ok and "known places" in res.line, res)
check("(h) update: known stays [A]", get_known_locations(OLD) == [A],
      get_known_locations(OLD))

# ── (j) combined home + known places, the known-places save fails ─────
COMBO = "Demo Combo"
save_character_profile(COMBO, {"template": "human-roleplay"}, create_new=True)
c = dict(get_character_config(COMBO) or {})
c.pop("known_locations", None)
c.pop("home_location", None)
c.pop("home_room", None)
save_character_config(COMBO, c)
combo_before = wu.home_schedule_state(COMBO)
check("(j) fixture: no home, no known_locations key",
      combo_before["known_locations"] is None
      and wu.is_absent(combo_before["home_location"]), combo_before)
mchar.write_known_locations = _fail_on_c
try:
    res = call(6, "update_character", {"name": COMBO,
                                       "patch": {"home": "Demo Hut",
                                                 "known_places": ["Demo Market"]}})
finally:
    mchar.write_known_locations = _real_write_known
check("(j) not ok, line names known places",
      not res.ok and "known places" in res.line, res)
rows6 = [e for e in wr.steps(run) if e.get("turn") == 6]  # oldest-first, refused rows too
check("(j) rows: home write done, then the known-places row refused",
      [(e.get("kind"), (e.get("inverse") or {}).get("op")) for e in rows6][:1]
      == [("write", "restore_home_schedule")]
      and len(rows6) == 2 and rows6[1].get("kind") == "refused", rows6)
check("(j) home stored before the failure",
      get_character_config(COMBO).get("home_location") == A,
      get_character_config(COMBO))
rep = wu.undo(run, turn=6)
check("(j) undo complete", rep["complete"], rep)
check("(j) home/schedule/known state as before",
      wu.home_schedule_state(COMBO) == combo_before, wu.home_schedule_state(COMBO))

# ── (i) a foreign discovery between write and undo ─────────────────────
res = call(7, "update_character", {"name": OLD, "patch": {"known_places": [B]}})
check("(i) update ok", res.ok and get_known_locations(OLD) == [A, B],
      (res, get_known_locations(OLD)))
mchar.add_known_location(OLD, C)
check("(i) foreign discovery -> [A, B, C]", get_known_locations(OLD) == [A, B, C],
      get_known_locations(OLD))
rep = wu.undo(run, turn=7)
check("(i) undo complete, nothing skipped", rep["complete"] and not rep["skipped"], rep)
check("(i) known [A, C] (B removed, the foreign C kept)",
      get_known_locations(OLD) == [A, C], get_known_locations(OLD))
c = dict(get_character_config(OLD) or {})
c["known_locations"] = [A]
save_character_config(OLD, c)

# ── (k) a successful combined home + schedule + known places update ──
MOVER = "Demo Mover"
save_character_profile(MOVER, {"template": "human-roleplay"}, create_new=True)
c = dict(get_character_config(MOVER) or {})
c.pop("home_location", None)
c.pop("home_room", None)
c["known_locations"] = [D]
save_character_config(MOVER, c)
mover_before = wu.home_schedule_state(MOVER)
check("(k) fixture: known [D], no home",
      get_known_locations(MOVER) == [D] and wu.is_absent(mover_before["home_location"]),
      mover_before)
res = call(8, "update_character", {"name": MOVER, "patch": {
    "home": "Demo Hut",
    "schedule": [{"hour": 9, "location": "Demo Square", "role": "fishing"}],
    "known_places": ["Demo Square", "Demo Market"]}})
check("(k) update ok", res.ok and res.wrote, res)
check("(k) stored [D, A, B, C]", get_known_locations(MOVER) == [D, A, B, C],
      get_known_locations(MOVER))
rows8 = [e for e in wr.steps(run) if e.get("turn") == 8]
check("(k) rows: restore_home_schedule, then remove_known_places",
      [(e.get("inverse") or {}).get("op") for e in rows8]
      == ["restore_home_schedule", "remove_known_places"], rows8)
check("(k) known-places inverse ids [C], had_key True",
      rows8[-1].get("inverse") == {"op": "remove_known_places", "name": MOVER,
                                   "ids": [C], "had_key": True},
      rows8[-1].get("inverse"))
check("(k) line known places added: Demo Market; knows 4 place(s)",
      "known places added: Demo Market; knows 4 place(s)" in res.line, res.line)
rep = wu.undo(run, turn=8)
check("(k) undo complete", rep["complete"] and not rep["skipped"], rep)
check("(k) known [D] again", get_known_locations(MOVER) == [D], get_known_locations(MOVER))
check("(k) home/schedule/known state as before",
      wu.home_schedule_state(MOVER) == mover_before, wu.home_schedule_state(MOVER))

# ── (l) a pending remove_known_places row, nothing written ─────────────
wr.begin(run, 9, "write", "update_character",
         {"name": OLD, "patch": {"known_places": [B]}}, "character", OLD,
         {"op": "remove_known_places", "name": OLD, "ids": [B], "had_key": True})
check("(l) fixture: Demo Old knows [A]", get_known_locations(OLD) == [A],
      get_known_locations(OLD))
rep = wu.undo(run, turn=9)
check("(l) undo complete, nothing skipped", rep["complete"] and not rep["skipped"], rep)
check("(l) list untouched [A]", get_known_locations(OLD) == [A], get_known_locations(OLD))
check("(l) key still a list", (get_character_config(OLD) or {}).get("known_locations") == [A],
      get_character_config(OLD))

# ── (m) a stored non-list is refused ───────────────────────────────────
for bad in ("Demo Hut", None):
    c = dict(get_character_config(KEYLESS) or {})
    c["known_locations"] = bad
    save_character_config(KEYLESS, c)
    res = call(10, "update_character", {"name": KEYLESS, "patch": {"known_places": [B]}})
    check(f"(m) {bad!r}: refused, are no list",
          not res.ok and not res.wrote and "are no list" in res.line, res)
    check(f"(m) {bad!r}: stored value unchanged",
          "known_locations" in (get_character_config(KEYLESS) or {})
          and get_character_config(KEYLESS)["known_locations"] == bad,
          get_character_config(KEYLESS))
check("(m) no write row in turn 10",
      not [e for e in wr.steps(run) if e.get("turn") == 10 and e.get("kind") == "write"],
      [e for e in wr.steps(run) if e.get("turn") == 10])
c = dict(get_character_config(KEYLESS) or {})
c.pop("known_locations", None)
save_character_config(KEYLESS, c)

# ── (n) broken stored entries stay as they are ─────────────────────────
# By hand: stored [A, 5, ""] (a non-string and an empty entry). Adding B
# appends to the RAW list -> [A, 5, "", B]; the undo removes exactly B ->
# [A, 5, ""] again (a normalised copy [A, B] would lose 5 and "").
c = dict(get_character_config(KEYLESS) or {})
c["known_locations"] = [A, 5, ""]
save_character_config(KEYLESS, c)
res = call(11, "update_character", {"name": KEYLESS, "patch": {"known_places": [B]}})
check("(n) add B ok", res.ok and res.wrote, res)
check("(n) raw list kept, B appended",
      (get_character_config(KEYLESS) or {}).get("known_locations") == [A, 5, "", B],
      get_character_config(KEYLESS))
rep = wu.undo(run, turn=11)
check("(n) undo complete, nothing skipped", rep["complete"] and not rep["skipped"], rep)
check("(n) undo restores [A, 5, \"\"]",
      (get_character_config(KEYLESS) or {}).get("known_locations") == [A, 5, ""],
      get_character_config(KEYLESS))
c = dict(get_character_config(KEYLESS) or {})
c.pop("known_locations", None)
save_character_config(KEYLESS, c)

# ── (g) travel ─────────────────────────────────────────────────────────
from app.core import travel_engine  # noqa: E402

_j, reason = travel_engine.start_journey(FISHER, C)
check("(g) Demo Fisher -> C is no unknown_target", reason != "unknown_target", reason)
_j, reason = travel_engine.start_journey(OLD, C)
check("(g) Demo Old -> C is unknown_target", reason == "unknown_target", reason)

print()
if failures:
    print(f"FAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("all ok")
