#!/usr/bin/env python3
"""Smoke: quest storage — templates, runs and facts (`app/models/quests.py`).

Quest system stage 1, Task 1. A temp world (`paths.init` BEFORE any world-DB
import); no server, no LLM, no engine. Every expectation below is derived by
hand from the plan's Task 1 interface, not recorded from a run.

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

  (a) SCHEMA. After `db.init_schema()` the tables `quest_templates`,
      `quest_runs`, `quest_facts` exist (appended to SCHEMA_STATEMENTS), and
      the story player's `stories` table still exists (D1: the name is taken,
      the quest tables must not collide with it). `quest_runs` has NO column
      named `character_name` (the delete sweep would remove a run whose giver
      is deleted; the engine has to see it and mark it broken).

  (b) TEMPLATE ROUND TRIP. `create_template` with two roles and two steps →
      `get_template` returns the SAME lists (JSON columns decode to lists of
      dicts), revision 1, origin "admin", state "draft", id "qt_" + 12 hex.

  (c) REVISION. `update_template(id, {"title": "T2"}, base_revision=1)` →
      revision 2, title "T2". A second call with `base_revision=1` raises
      `StaleRevision`; the title stays "T2" and the revision stays 2.
      A non-editable key ("origin") raises ValueError.

  (d) STEP RECORD (Review Focus 1). A run of the 2-step snapshot, state
      "open": `record_step_done(run, 0, ...)` → current_step 1, state "open",
      step_log has 1 entry naming the avatar and the mind. The SAME call
      again (a second avatar fulfilling step 0 at the same moment) → None,
      and the stored step_log still has exactly 1 entry.
      `record_step_done(run, 1, ...)` → state "done" (step 1 is the last of
      2), `ended_game_ts` parses with `GameTime.parse`, ended_at set.
      `create_run(..., state="open")` stamped `started_game_ts` itself (parses).

  (e) ENDED IS FINAL. `set_run_state(done_run, "open")` → False, state stays
      "done".

  (f) CHECK CONSTRAINTS. `create_run(state="bogus")` and
      `create_template(state="bogus")` → sqlite3.IntegrityError.

  (g) EXPIRY. now = game_time() + 2 days (so "one hour before" stays above
      the epoch). Two open runs with expires_at = now - 1 h and now + 1 h:
      `expire_runs(now)` returns exactly [first id]; the first is "failed"
      with `ended_game_ts == now` (the passed stamp), the second stays
      "open". Runs with expires_at '' are never expired.

  (g2) OPEN FROM HIDDEN. A "hidden" run: `open_run(id, started_game_ts=S,
      expires_at=E)` → True, state "open", both stamps stored as given.
      `open_run` again (now open) → False. `set_run_state(run, "cancelled")`
      → True, ended_game_ts parses.

  (h) FACTS. `add_fact(m, k, s)` → True, the same again → False (UNIQUE);
      `has_fact` → True; a different subject → False.

  (i) DELETE. Character "Gone" is the MIND of one fact and the SUBJECT of a
      second; a third fact names neither. A run's bindings name "Gone".
      `delete_character("Gone")` → True; facts 1 and 2 are gone, fact 3
      stays (count 1), and the run row still exists with its bindings.

Usage:
    ./.venv/bin/python scripts/smoke_quest_store.py
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="smoke_quest_store_clips_")

import app  # noqa: E402

assert Path(app.__file__).resolve().is_relative_to(ROOT), \
    f"app imported from {app.__file__}, not from {ROOT}"

from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="smoke_quest_store_"))

from app.core import db  # noqa: E402

db.init_schema()

from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.timeutils import game_time  # noqa: E402

failures = []


def check(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(label)


def parses(stamp):
    try:
        GameTime.parse(stamp)
        return True
    except Exception:
        return False


def raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    except Exception as e:  # noqa: BLE001
        print(f"       (raised {type(e).__name__}: {e})")
        return False
    return False


print("(a) schema")
tables = {r[0] for r in db.get_connection().execute(
    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
for t in ("quest_templates", "quest_runs", "quest_facts", "stories"):
    check(f"table {t} exists", t in tables)
run_cols = {c[1] for c in db.get_connection().execute("PRAGMA table_info(quest_runs)")}
check("quest_runs has no character_name column", "character_name" not in run_cols)

from app.models import quests  # noqa: E402

print("(b) template round trip")
ROLES = [{"key": "giver", "kind": "character", "description": "who asks"},
         {"key": "place", "kind": "room", "description": "where"}]
STEPS = [{"id": "s1", "text": "Talk.", "hint": "", "condition": {"type": "spoke_with",
                                                                 "params": {"character": "giver"}}},
         {"id": "s2", "text": "Go.", "hint": "", "condition": {"type": "at_place",
                                                              "params": {"place": "place"}}}]
tpl = quests.create_template(title="Errand", summary="S", gm_notes="GM", roles=ROLES, steps=STEPS)
got = quests.get_template(tpl["id"])
check("id is qt_ + 12 hex", got["id"].startswith("qt_") and len(got["id"]) == 15)
check("roles round trip", got["roles"] == ROLES)
check("steps round trip", got["steps"] == STEPS)
check("revision 1, origin admin, state draft",
      (got["revision"], got["origin"], got["state"]) == (1, "admin", "draft"))
check("list_templates finds it", [t["id"] for t in quests.list_templates(origin="admin")] == [tpl["id"]])

print("(c) revision")
upd = quests.update_template(tpl["id"], {"title": "T2"}, base_revision=1)
check("update → revision 2, title T2", (upd["revision"], upd["title"]) == (2, "T2"))
check("stale base_revision raises StaleRevision",
      raises(quests.StaleRevision,
             lambda: quests.update_template(tpl["id"], {"title": "T3"}, base_revision=1)))
after = quests.get_template(tpl["id"])
check("stale update changed nothing", (after["revision"], after["title"]) == (2, "T2"))
check("non-editable key raises ValueError",
      raises(ValueError, lambda: quests.update_template(tpl["id"], {"origin": "auto"},
                                                        base_revision=2)))

print("(d) step record")
snap = quests.get_template(tpl["id"])
run = quests.create_run(template=snap, bindings={"giver": {"name": "Gone"}}, state="open")
check("run id is qr_ + 12 hex", run["id"].startswith("qr_") and len(run["id"]) == 15)
check("create_run(open) stamps started_game_ts", parses(run["started_game_ts"]))
check("snapshot stored", run["template_snapshot"]["steps"] == STEPS)
r0 = quests.record_step_done(run["id"], 0, avatar="Ava", mind="Ava")
check("step 0 → current_step 1, open", r0 and (r0["current_step"], r0["state"]) == (1, "open"))
check("step_log entry names avatar and mind",
      r0 and r0["step_log"][0]["avatar"] == "Ava" and r0["step_log"][0]["mind"] == "Ava"
      and r0["step_log"][0]["step"] == 0 and parses(r0["step_log"][0]["game_ts"]))
again = quests.record_step_done(run["id"], 0, avatar="Bea", mind="Bea")
check("second record of step 0 → None", again is None)
check("step_log still has 1 entry", len(quests.get_run(run["id"])["step_log"]) == 1)
r1 = quests.record_step_done(run["id"], 1, avatar="Ava", mind="Ava")
check("last step → done", r1 and r1["state"] == "done")
check("ended_game_ts parses, ended_at set", r1 and parses(r1["ended_game_ts"]) and bool(r1["ended_at"]))

print("(e) ended is final")
check("set_run_state(done → open) is False", quests.set_run_state(run["id"], "open") is False)
check("state stays done", quests.get_run(run["id"])["state"] == "done")

print("(f) check constraints")
check("create_run(state=bogus) → IntegrityError",
      raises(sqlite3.IntegrityError,
             lambda: quests.create_run(template=snap, bindings={}, state="bogus")))
check("create_template(state=bogus) → IntegrityError",
      raises(sqlite3.IntegrityError, lambda: quests.create_template(title="X", state="bogus")))

print("(g) expiry")
now = game_time() + GameDuration.of(days=2)
now_c = now.canonical()
early = quests.create_run(template=snap, bindings={}, state="open",
                          expires_at=(now - GameDuration.of(hours=1)).canonical())
late = quests.create_run(template=snap, bindings={}, state="open",
                         expires_at=(now + GameDuration.of(hours=1)).canonical())
no_limit = quests.create_run(template=snap, bindings={}, state="open")
expired = quests.expire_runs(now_c)
check("expire_runs returns exactly the early id", expired == [early["id"]], str(expired))
e = quests.get_run(early["id"])
check("early run failed, ended_game_ts == now", (e["state"], e["ended_game_ts"]) == ("failed", now_c))
check("early run ended_at set", bool(e["ended_at"]))
check("late run still open", quests.get_run(late["id"])["state"] == "open")
check("run without limit still open", quests.get_run(no_limit["id"])["state"] == "open")

print("(g2) open from hidden")
hidden = quests.create_run(template=snap, bindings={}, state="hidden")
check("hidden run has no started_game_ts", hidden["started_game_ts"] == "")
S = game_time().canonical()
E = (game_time() + GameDuration.of(hours=5)).canonical()
check("open_run(hidden) → True", quests.open_run(hidden["id"], started_game_ts=S, expires_at=E) is True)
h = quests.get_run(hidden["id"])
check("state open, both stamps stored", (h["state"], h["started_game_ts"], h["expires_at"]) == ("open", S, E))
check("open_run(open) → False", quests.open_run(hidden["id"], started_game_ts=S) is False)
check("set_run_state(cancelled) → True", quests.set_run_state(hidden["id"], "cancelled") is True)
check("cancelled ended_game_ts parses", parses(quests.get_run(hidden["id"])["ended_game_ts"]))
check("count_runs(open) = late + no_limit", quests.count_runs(("open",)) == 2)
check("list_runs newest first", quests.list_runs(limit=1)[0]["id"] == hidden["id"])

print("(h) facts")
check("add_fact first → True", quests.add_fact("Ava", "spoke_with", "Bea") is True)
check("add_fact again → False", quests.add_fact("Ava", "spoke_with", "Bea") is False)
check("has_fact → True", quests.has_fact("Ava", "spoke_with", "Bea") is True)
check("has_fact other subject → False", quests.has_fact("Ava", "spoke_with", "Cid") is False)

print("(i) delete_character")
from app.models.character import delete_character, save_character_profile  # noqa: E402

save_character_profile("Gone", {"character_name": "Gone", "template": "human-default"},
                       create_new=True)
quests.add_fact("Gone", "spoke_with", "Ava")
quests.add_fact("Ava", "spoke_with", "Gone")
check("delete_character(Gone) → True", delete_character("Gone") is True)
facts = [tuple(r) for r in db.get_connection().execute(
    "SELECT mind, kind, subject FROM quest_facts ORDER BY id").fetchall()]
check("only the fact naming neither survives", facts == [("Ava", "spoke_with", "Bea")], str(facts))
kept = quests.get_run(run["id"])
check("run row naming Gone in bindings survives",
      kept is not None and kept["bindings"] == {"giver": {"name": "Gone"}})

print()
if failures:
    print(f"FAIL — {len(failures)} check(s): {failures}")
    sys.exit(1)
print("PASS — quest storage")
