#!/usr/bin/env python3
"""Smoke: World Dev free mode — create takes every settable field, stats go to
status_effects, per-stat undo (gaps 10, 11; review findings 1 and 4).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p1-characters.md, Task 2.
A temp world (paths.init BEFORE any world-DB import) whose config.json enables
the tracked ``rp`` package (packages.enabled = "rp"), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM. Tool calls go through
``world_dev_tools.run_tool`` exactly as the agent loop calls them.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_char_fields.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Template facts (read by hand from the files, not at runtime):
plugins/rp/templates/character/rp.json gives human-roleplay three number
fields with store "status_effects": attention default 50, courage default 50,
stamina default 80, all llm_generable; and courage_baseline (number, store
config, NOT llm_generable). shared/templates/character/base-character.json:
importance is a config select with options 1 / 2 / 3 (numbers), chat_mode a
config select with options "" / "rp_first"; motion_gravity_scale is a profile
number field that is NOT llm_generable. human-default has no rp fragment, so
no status_effects field.

Run 1, turn 1 (create_character):
  (a) {name: "Demo Baker", importance: 3, chat_mode: "", courage: 70,
      courage_baseline: 60, motion_gravity_scale: 1.2} -> ok.
      config importance == 3 and is an int (written raw, never str(3));
      config chat_mode == "" (the explicit value beats the rp_first default);
      config courage_baseline == 60 (int), profile motion_gravity_scale == 1.2
      (non-generable fields are accepted at creation);
      profile status_effects == {"attention": 50, "courage": 70,
      "stamina": 80} (the two template defaults + the sent value); no
      top-level attention / courage / stamina key in the profile.
      get_character{fields: ["courage"]} reads "courage:\n70" (a stat is
      read from status_effects, where it was written); the overview's
      "profile fields:" line names attention, courage and stamina and not
      "status_effects" (no writable key).
  (b) build_status_effects("Demo Baker")["status_effects"]["courage"] == 70.
  (c) create with courage 120 -> refused, the line says "0-100", no row;
      courage 40.5 -> refused (not whole); courage "70" -> refused (no
      number); courage 10**400 -> refused the same way (the range is tested
      before float(), which would overflow). Each leaves only a journal row
      of kind "refused".
  (d) create "Demo Plain" without chat_mode -> config chat_mode ==
      "rp_first" (the new-character default of apply_character, unchanged).
Turn 2: update_character{Demo Baker, importance: 2} -> config importance == 2,
      an int (same JSON type as at creation).
      update courage 120 -> refused ("0-100"), status_effects unchanged;
      update courage 10**400 -> refused ("0-100"), no OverflowError.
Turn 3 (e): update courage 40 -> ok, line names "stats courage";
      status_effects {"attention": 50, "courage": 40, "stamina": 80}; no
      top-level courage. (e6) discard_preview(run) now names "Demo Baker" in
      exactly one line (its creating entry; the new op maps to the same
      character target). undo(run, 3) -> complete, courage 70 again.
Turn 4 (e2): update courage 30; then adjust_status_effects(stamina -5) ->
      stamina 75 (80 - 5). undo(run, 4) -> complete; courage 70 (the value
      before turn 4), stamina 75 (the foreign change is kept), attention 50.
Turn 5 (e3): update courage 30; then adjust_status_effects(courage +5) -> 35.
      undo(run, 5) -> NOT complete, one skip "changed since" with key
      "status_effects.courage"; courage stays 35.
Turn 6 (e4): a PENDING stats entry is begun through the journal helpers
      (wr.begin, never completed: the crash path) with inverse
      restore_status_effects{before: {courage: 70}, had_key: True}; stamina
      is then changed by adjust_status_effects(-15) -> 60 (75 - 15).
      undo(run, 6) -> complete; courage 70 (a pending entry restores the
      stats of its before map), stamina stays 60 (never touched).
Turn 7 (e5): "Demo Bare" saved directly (create_new=True, human-roleplay)
      with NO status_effects key; update courage 40 -> status_effects
      {"courage": 40}; undo(run, 7) -> complete, the profile has no
      status_effects key again and equals the pre-update snapshot.
      (status_effects lives in character_state.meta, which a profile save
      MERGES — the undo removes the key through
      models.character.remove_state_meta_key.)
      (e) also compares a dump of every world.db table (journal tables
      world_dev_* left out) before turn 3 and after its undo: equal.
      (e) changed_at is called with recipient "Demo Baker" and topics
      ("presence", "self") once by the stats write and once by its undo
      (open clients refresh; no history row is written).
Turn 8 (e7): Demo Bare's courage is stored as 70.0 (a float, saved
      directly); update courage 70 -> ok, line "stats unchanged", journal
      before map {} (nothing written), courage still 70.0 AND a float;
      undo(run, 8) -> complete, still 70.0.
Regular path (no run):
  (f) apply_character({character_name: "Demo Apply", template:
      human-roleplay, courage: 65}) -> status_effects courage 65, attention
      50, stamina 80; no top-level courage. "Demo Apply2" with courage 150 ->
      courage 50 (the default) and exactly one warning naming "courage".
      "Demo Apply3" with courage 40.5 -> courage 50 (the default; a
      fractional value is skipped like the free tool refuses it, never
      truncated to 40) and exactly one warning naming "courage".
      "Demo Apply4" with courage 10**400 -> courage 50 and exactly one
      warning naming "courage" (no OverflowError).
  (g) apply_character({character_name: "Demo Default", template:
      human-default, age: 30}) -> the profile has no status_effects key.
  (h) discard_preview(run) before undo(run, 1) lists exactly the characters
      the run created: "Demo Baker" and "Demo Plain" (Demo Bare existed
      before). undo(run, 1) -> complete; both rows gone.
Turn 9 (i): a failed save. models.character.save_character_config is
      replaced by one returning False; create_character{"Demo Fail",
      importance: 3} -> not ok, the line names "was not stored"; the
      journal entry carries the delete_character inverse with claimed True
      (the apply had stored the row). undo(run, 9) -> complete; no
      "Demo Fail" row, and the world.db dump (world_dev_* left out) equals
      the one taken before the call.
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_cf_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_cf_"))
paths.init(STORAGE)
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)
paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "rp"}}))

from app.core import config, db  # noqa: E402

config.load(paths.get_config_path())
db.init_schema()

from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core.character_ops import build_status_effects  # noqa: E402
from app.core.world_dev_apply import apply_character  # noqa: E402
from app.models.character import (adjust_status_effects,  # noqa: E402
                                  character_row_exists, get_character_config,
                                  get_character_profile, save_character_profile)

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


STATS = ("attention", "courage", "stamina")
BAKER = "Demo Baker"


def prof(name):
    return get_character_profile(name) or {}


def cfg(name):
    return get_character_config(name) or {}


def stats(name):
    return prof(name).get("status_effects")


def dump_db():
    """Every world.db table except the run journal, rows sorted."""
    con = sqlite3.connect(str(db.get_db_path()))
    try:
        out = {}
        for (tname,) in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            if tname.startswith("world_dev") or tname.startswith("sqlite_"):
                continue
            cur = con.execute(f'SELECT * FROM "{tname}"')
            # updated_at is a wall-clock stamp: an undo in a later second
            # restores every value but not the stamp, so it is left out.
            keep = [i for i, d in enumerate(cur.description) if d[0] != "updated_at"]
            out[tname] = sorted(repr(tuple(r[i] for i in keep)) for r in cur.fetchall())
        return out
    finally:
        con.close()


def diff_dump(a, b):
    return {t: (sorted(set(a.get(t, [])) - set(b.get(t, []))),
                sorted(set(b.get(t, [])) - set(a.get(t, []))))
            for t in set(a) | set(b) if a.get(t) != b.get(t)}


from app.core import sync_topics  # noqa: E402

notified = []
_real_changed_at = sync_topics.changed_at


def _record_changed_at(character, loc_id=None, topics=("presence",)):
    notified.append((character, tuple(topics)))
    return _real_changed_at(character, loc_id, topics=topics)


sync_topics.changed_at = _record_changed_at

run = wr.create_run("char fields", "m", "p", "u", 40, 300000)


def call(turn, tool, args):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


def newest_kind():
    return wr.steps(run)[-1]["kind"]


# ── (a) ────────────────────────────────────────────────────────────────
res = call(1, "create_character", {"data": {
    "name": BAKER, "importance": 3, "chat_mode": "", "courage": 70,
    "courage_baseline": 60, "motion_gravity_scale": 1.2}})
check("(a) create ok", res.ok and res.wrote, res)
c = cfg(BAKER)
check("(a) config importance == 3", c.get("importance") == 3, c.get("importance"))
check("(a) config importance is an int", type(c.get("importance")) is int,
      type(c.get("importance")))
check("(a) config chat_mode == \"\" (explicit beats default)",
      c.get("chat_mode") == "", c.get("chat_mode"))
check("(a) config courage_baseline == 60 (int)",
      c.get("courage_baseline") == 60 and type(c.get("courage_baseline")) is int,
      c.get("courage_baseline"))
p = prof(BAKER)
check("(a) profile motion_gravity_scale == 1.2",
      p.get("motion_gravity_scale") == 1.2, p.get("motion_gravity_scale"))
check("(a) status_effects", p.get("status_effects")
      == {"attention": 50, "courage": 70, "stamina": 80}, p.get("status_effects"))
check("(a) no top-level stat keys", not any(k in p for k in STATS),
      {k: p.get(k) for k in STATS if k in p})
# A stat reads back from status_effects under its own key (where it was
# written), and the overview names the stats, not "status_effects".
res = call(1, "get_character", {"name": BAKER, "fields": ["courage"]})
check("(a) get_character fields [courage] -> 70",
      res.ok and res.line.split("\n")[1:] == ["courage:", "70"], res.line)
res = call(1, "get_character", {"name": BAKER})
_pf = next((l for l in res.line.splitlines() if l.startswith("profile fields: ")), "")
check("(a) overview names the stats, not status_effects",
      res.ok and "status_effects" not in _pf
      and all(s in _pf.split(": ", 1)[1].split(", ") for s in ("attention", "courage", "stamina")),
      _pf)

# ── (b) ────────────────────────────────────────────────────────────────
se = build_status_effects(BAKER)
check("(b) build_status_effects courage 70",
      (se.get("status_effects") or {}).get("courage") == 70, se)

# ── (c) ────────────────────────────────────────────────────────────────
for bad in (120, 40.5, "70", 10**400):
    res = call(1, "create_character", {"data": {"name": "Demo Bad", "courage": bad}})
    check(f"(c) courage {bad!r} refused", not res.ok and not res.wrote, res)
    check(f"(c) courage {bad!r}: line says 0-100", "0-100" in res.line, res.line)
    check(f"(c) courage {bad!r}: journal kind refused", newest_kind() == "refused")
    check(f"(c) courage {bad!r}: no row", not character_row_exists("Demo Bad"))

# ── (d) ────────────────────────────────────────────────────────────────
res = call(1, "create_character", {"data": {"name": "Demo Plain"}})
check("(d) create ok", res.ok, res)
check("(d) chat_mode rp_first", cfg("Demo Plain").get("chat_mode") == "rp_first",
      cfg("Demo Plain").get("chat_mode"))

# ── turn 2: update importance ─────────────────────────────────────────
res = call(2, "update_character", {"name": BAKER, "patch": {"importance": 2}})
check("(a) update importance ok", res.ok, res)
check("(a) update importance == 2, int",
      cfg(BAKER).get("importance") == 2 and type(cfg(BAKER).get("importance")) is int,
      cfg(BAKER).get("importance"))
before = stats(BAKER)
res = call(2, "update_character", {"name": BAKER, "patch": {"courage": 120}})
check("update courage 120 refused", not res.ok and "0-100" in res.line, res)
check("update courage 120: status_effects unchanged", stats(BAKER) == before)
try:
    res = call(2, "update_character", {"name": BAKER, "patch": {"courage": 10**400}})
    check("update courage 10**400 refused", not res.ok and "0-100" in res.line, res)
except OverflowError as exc:
    check("update courage 10**400 refused (no OverflowError)", False, exc)
check("update courage 10**400: status_effects unchanged", stats(BAKER) == before)

# ── (e) / (e6) ─────────────────────────────────────────────────────────
dump_e = dump_db()
notified.clear()
res = call(3, "update_character", {"name": BAKER, "patch": {"courage": 40}})
check("(e) update courage ok", res.ok and res.wrote, res)
check("(e) line names stats courage", "stats courage" in res.line, res.line)
check("(e) status_effects", stats(BAKER)
      == {"attention": 50, "courage": 40, "stamina": 80}, stats(BAKER))
check("(e) no top-level courage", "courage" not in prof(BAKER))
check("(e) journal inverse op restore_status_effects",
      (wr.steps(run)[-1].get("inverse") or {}).get("op") == "restore_status_effects",
      wr.steps(run)[-1].get("inverse"))
prev = wu.discard_preview(run)
check("(e6) discard_preview names Demo Baker once",
      sum(1 for line in prev if f'"{BAKER}"' in line) == 1, prev)
rep = wu.undo(run, turn=3)
check("(e) undo complete", rep["complete"], rep)
check("(e) courage 70 again", stats(BAKER)
      == {"attention": 50, "courage": 70, "stamina": 80}, stats(BAKER))
want_note = (BAKER, ("presence", "self"))
check("(e) changed_at for Demo Baker by the write and by the undo",
      notified.count(want_note) == 2, notified)
check("(e) world.db equals the pre-turn-3 dump", dump_db() == dump_e,
      diff_dump(dump_e, dump_db()))

# ── (e2) foreign change of another stat ────────────────────────────────
res = call(4, "update_character", {"name": BAKER, "patch": {"courage": 30}})
check("(e2) update ok", res.ok, res)
adjust_status_effects(BAKER, {"stamina": -5})
check("(e2) stamina 75", stats(BAKER).get("stamina") == 75, stats(BAKER))
rep = wu.undo(run, turn=4)
check("(e2) undo complete", rep["complete"], rep)
check("(e2) courage 70, stamina 75 kept, attention 50",
      stats(BAKER) == {"attention": 50, "courage": 70, "stamina": 75}, stats(BAKER))

# ── (e3) the written stat itself changed ───────────────────────────────
res = call(5, "update_character", {"name": BAKER, "patch": {"courage": 30}})
check("(e3) update ok", res.ok, res)
adjust_status_effects(BAKER, {"courage": 5})
check("(e3) courage 35", stats(BAKER).get("courage") == 35, stats(BAKER))
rep = wu.undo(run, turn=5)
check("(e3) undo not complete", not rep["complete"], rep)
keys = [k for s in rep["skipped"] for k in s.get("keys") or []]
check("(e3) skipped key status_effects.courage",
      keys == ["status_effects.courage"]
      and all(s.get("reason") == wu.REASON_CHANGED for s in rep["skipped"]), rep)
check("(e3) courage stays 35", stats(BAKER).get("courage") == 35, stats(BAKER))

# ── (e4) pending entry ─────────────────────────────────────────────────
wr.begin(run, 6, "write", "update_character",
         {"name": BAKER, "patch": {"courage": 35}}, "character", BAKER,
         {"op": "restore_status_effects", "name": BAKER,
          "before": {"courage": 70}, "had_key": True})
adjust_status_effects(BAKER, {"stamina": -15})
check("(e4) stamina 60", stats(BAKER).get("stamina") == 60, stats(BAKER))
rep = wu.undo(run, turn=6)
check("(e4) undo complete", rep["complete"], rep)
check("(e4) courage 70, stamina stays 60",
      stats(BAKER) == {"attention": 50, "courage": 70, "stamina": 60}, stats(BAKER))

# ── (e5) had_key ───────────────────────────────────────────────────────
BARE = "Demo Bare"
save_character_profile(BARE, {"template": "human-roleplay"}, create_new=True)
check("(e5) fixture has no status_effects", "status_effects" not in prof(BARE),
      prof(BARE).get("status_effects"))
snap_bare = (prof(BARE), cfg(BARE))
res = call(7, "update_character", {"name": BARE, "patch": {"courage": 40}})
check("(e5) update ok", res.ok, res)
check("(e5) status_effects {courage: 40}", stats(BARE) == {"courage": 40}, stats(BARE))
rep = wu.undo(run, turn=7)
check("(e5) undo complete", rep["complete"], rep)
check("(e5) no status_effects key again", "status_effects" not in prof(BARE),
      prof(BARE).get("status_effects"))
check("(e5) profile + config equal the snapshot", (prof(BARE), cfg(BARE)) == snap_bare)

# ── (e7) a stat stored as a float ──────────────────────────────────────
p = prof(BARE)
p["status_effects"] = {"courage": 70.0}
save_character_profile(BARE, p)
check("(e7) fixture courage 70.0 float", type(stats(BARE).get("courage")) is float,
      stats(BARE))
res = call(8, "update_character", {"name": BARE, "patch": {"courage": 70}})
check("(e7) update ok, stats unchanged", res.ok and "stats unchanged" in res.line, res)
inv = wr.steps(run)[-1].get("inverse") or {}
check("(e7) journal before map empty", inv.get("op") == "restore_status_effects"
      and inv.get("before") == {}, inv)
check("(e7) courage still 70.0, a float",
      type(stats(BARE).get("courage")) is float and stats(BARE)["courage"] == 70.0,
      stats(BARE))
rep = wu.undo(run, turn=8)
check("(e7) undo complete", rep["complete"], rep)
check("(e7) still 70.0 float after undo",
      type(stats(BARE).get("courage")) is float, stats(BARE))

# ── (f) / (g) regular apply path ───────────────────────────────────────
out = apply_character({"character_name": "Demo Apply", "template": "human-roleplay",
                       "courage": 65})
p = prof("Demo Apply")
check("(f) status_effects courage 65 + defaults", p.get("status_effects")
      == {"attention": 50, "courage": 65, "stamina": 80}, p.get("status_effects"))
check("(f) no top-level stat keys", not any(k in p for k in STATS),
      {k: p.get(k) for k in STATS if k in p})
out = apply_character({"character_name": "Demo Apply2", "template": "human-roleplay",
                       "courage": 150})
p = prof("Demo Apply2")
check("(f) courage 150 -> default 50", (p.get("status_effects") or {}).get("courage") == 50,
      p.get("status_effects"))
warns = [w for w in out.get("warnings") or [] if "courage" in str(w)]
check("(f) one warning naming courage", len(warns) == 1, out.get("warnings"))
out = apply_character({"character_name": "Demo Apply3", "template": "human-roleplay",
                       "courage": 40.5})
p = prof("Demo Apply3")
check("(f) courage 40.5 -> default 50 (not truncated)",
      (p.get("status_effects") or {}).get("courage") == 50, p.get("status_effects"))
warns = [w for w in out.get("warnings") or [] if "courage" in str(w)]
check("(f) 40.5: one warning naming courage", len(warns) == 1, out.get("warnings"))
try:
    out = apply_character({"character_name": "Demo Apply4", "template": "human-roleplay",
                           "courage": 10**400})
    p = prof("Demo Apply4")
    check("(f) courage 10**400 -> default 50",
          (p.get("status_effects") or {}).get("courage") == 50, p.get("status_effects"))
    warns = [w for w in out.get("warnings") or [] if "courage" in str(w)]
    check("(f) 10**400: one warning naming courage", len(warns) == 1, out.get("warnings"))
except OverflowError as exc:
    check("(f) courage 10**400 (no OverflowError)", False, exc)
apply_character({"character_name": "Demo Default", "template": "human-default", "age": 30})
check("(g) human-default: no status_effects key",
      "status_effects" not in prof("Demo Default"), prof("Demo Default"))

# ── (h) ────────────────────────────────────────────────────────────────
prev = wu.discard_preview(run)
named = sorted(line.split('"')[1] for line in prev if line.startswith("character "))
check("(h) discard_preview lists exactly the created characters",
      named == [BAKER, "Demo Plain"], prev)
rep = wu.undo(run, turn=1)
check("(h) undo of the create turn complete", rep["complete"], rep)
check("(h) both created characters gone",
      not character_row_exists(BAKER) and not character_row_exists("Demo Plain"))

# ── (i) a failed save during create ───────────────────────────────────
import app.models.character as mchar  # noqa: E402

dump_i = dump_db()
_real_save_cfg = mchar.save_character_config
mchar.save_character_config = lambda *a, **k: False
try:
    res = call(9, "create_character", {"data": {"name": "Demo Fail", "importance": 3}})
finally:
    mchar.save_character_config = _real_save_cfg
check("(i) create not ok", not res.ok, res)
check("(i) line names was not stored", "was not stored" in res.line, res.line)
inv = wr.steps(run)[-1].get("inverse") or {}
check("(i) inverse delete_character, claimed",
      inv.get("op") == "delete_character" and inv.get("claimed") is True, inv)
rep = wu.undo(run, turn=9)
check("(i) undo complete", rep["complete"], rep)
check("(i) no Demo Fail row", not character_row_exists("Demo Fail"))
check("(i) world.db equals the pre-call dump", dump_db() == dump_i,
      diff_dump(dump_i, dump_db()))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("all ok")
