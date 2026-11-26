#!/usr/bin/env python3
"""World Dev free mode — add_event / delete_event, and the location delete
refused while an event names the place (plan
docs/superpowers/plans/2026-11-25-world-dev-free-p3-world-systems.md, Task 6).

Usage: ./.venv/bin/python scripts/smoke_world_dev_events.py
Runs in a temp world (STORAGE_DIR / INSTANCE_DIR temp), no server.

WHAT IS CHECKED, and where every expected value comes from:

Fixture: the place Demo Square (id "demo_square", no rooms, written with
app.models.world.upsert_location, no run). The clock is frozen
(set_game_factor(0.0)) at year 1, day 1, 12:00 (set_game_time), so the game
stamp at write time is GameTime.from_parts(1, 1, 12, 0, 0). An event id of the
writer is "evt_" + 8 hex digits (events.add_event: f"evt_{uuid4().hex[:8]}") —
read at runtime from the result line, which names it. The four categories are
the keys of random_events.CATEGORIES: ambient, social, disruption, danger.

Run 1:
  (a) add_event{text "A travelling merchant sets up in the square.",
      location_id demo_square, category social, ttl_hours 6} -> ok, line
      'added event <A> at "Demo Square" (demo_square) (social, 6 game hours):
      "A travelling merchant sets up in the square."'. events.get_event(A):
      text / location_id / category / ttl_hours as sent; expires_at =
      (game_ts + GameDuration.of(hours=6)).canonical() (events.add_event), and
      with game_ts = 12:00 of day 1 that is GameTime.from_parts(1, 1, 18, 0, 0),
      compared through GameTime.parse. One write journal row, target
      ("event", A), inverse {"op": "delete_event", "id": A}.
  (b) refusals (each adds no write row and no event): category "heist" (the
      line names all four categories); ttl_hours 721 (limit 720, plan E10);
      ttl_hours 1.5 (whole hours only); location_id "nope"; text "" ;
      text "  padded  " (stored stripped -> refused, "blanks"); text of 501
      characters (limit 500); an unknown key "when".
  (c) add_event{text "Thunder rolls over the land."} (no location, no
      category, no ttl) -> ok, the line contains 'at everywhere
      (uncategorized, 24 game hours)' (events.DEFAULT_TTL_HOURS = 24);
      get_event(G)["location_id"] is None. ttl_hours 0 -> the line says
      "never expires" and expires_at is None (the writer's rule, ttl 0).
  (d) events.record_attempt(A, "Demo Someone", "haggles", "fail") directly ->
      discard_preview(run) == ['event <A> was changed since — the discard
      leaves it alone', 'event <G> "Thunder rolls over the land."',
      'event <Z> "A quiet hour."'] (creation order: A, G, Z); undo -> not
      complete, exactly one "changed since" skip whose keys are
      ["resolution"] (the key record_attempt adds); A stays, G and Z gone.
      A removed by hand.
Run 2 (clean):
  (e) two events E1 (at demo_square) and E2 (global) -> discard_preview ==
      ['event <E1> "<text>"', 'event <E2> "<text>"']; undo -> complete;
      events.get_all_events() == [].
      delete_created{event, E3} in the turn that made E3 -> ok, gone; E4 made
      in turn 1, delete_created in turn 2 -> refused "created in an earlier
      turn" (E2, same-turn only); E4 stays until the undo.
Run 3 / 4 (references, same turn and earlier-turn path):
  (f) create_location Demo Fair (turn create_turn), add_event at it (turn
      event_turn) -> delete_created{location, fair} refused "still named by"
      and "event <V>"; delete_created{event, V} -> ok; then the location delete
      -> ok; undo -> complete, nothing left.
Run 5 (singular, strict read):
  (g) add_event ttl_hours 1 -> line ends "(uncategorized, 1 game hour): ..."
      (singular, no "hours"). With events.event_exists patched to None (the
      events table cannot be read): discard_preview raises RuntimeError naming
      "could not be read" (a read error is never "already gone"); undo -> not
      complete, exactly one skip whose reason starts "undo failed", the event
      H still stored. Patch removed, H removed by hand.
Run 6 (strict reference read):
  (h) create_location Demo Booth -> ok. With events.get_connection patched
      to raise sqlite3.OperationalError: events.get_all_events() still
      returns a list (its JSON fallback; no events file -> []) but
      events.get_all_events_strict() raises; delete_created{location,
      booth} -> refused, the line has "events could not be read"; the booth
      is still there. Patch removed -> delete_created ok; undo -> complete.
  (i) add_stat_hit takes keyed_lock("world_event", id): an event K added by
      events.add_event; while the main thread holds that lock, a thread
      running add_stat_hit(K, "Demo Hit") is still alive after join(0.2) and
      get_event(K)["metadata"] has no stat_hit yet; after the release the
      thread ends (join(5)) and stat_hit == ["Demo Hit"]. K removed by hand.
"""
import atexit
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="smoke_wd_events_"))
atexit.register(shutil.rmtree, ROOT, True)
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

from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models import events  # noqa: E402
from app.models.world import get_location_by_id, list_locations, upsert_location  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


set_game_factor(0.0)
set_game_time(GameTime.from_parts(1, 1, 12, 0, 0))
SQUARE = "demo_square"
upsert_location({"id": SQUARE, "name": "Demo Square", "rooms": []}, sync_world=False)

EID = re.compile(r"event (evt_[0-9a-f]{8})")


def new_run(label):
    open_ = wr.open_run()
    if open_:
        wr.set_status(open_["id"], "accepted")
    return wr.create_run(label, "m", "p", "u", 80, 300000)


run = new_run("events")


def call(tool, args, turn=1):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


def writes():
    return [e for e in wr.entries(run, include_undone=True) if e.get("kind") == "write"]


def eid_of(res):
    m = EID.search(res.line or "")
    return m.group(1) if m else ""


MERCHANT = "A travelling merchant sets up in the square."
BASE = {"text": MERCHANT, "location_id": SQUARE, "category": "social", "ttl_hours": 6}

# ── (a) ──────────────────────────────────────────────────────────────────
print("(a) add_event")
r = call("add_event", dict(BASE))
check("(a) ok", r.ok and r.wrote, r)
A = eid_of(r)
check("(a) line", r.line == (f'added event {A} at "Demo Square" (demo_square) '
                             f'(social, 6 game hours): "{MERCHANT}"'), r.line)
row = events.get_event(A) if A else None
check("(a) stored fields", row is not None and (row.get("text"), row.get("location_id"),
                                                row.get("category"), row.get("ttl_hours"))
      == (MERCHANT, SQUARE, "social", 6), row)
try:
    exp = GameTime.parse((row or {}).get("expires_at") or "")
except (ValueError, TypeError):
    exp = None
check("(a) expires 6 game hours later", exp == GameTime.from_parts(1, 1, 18, 0, 0), row)
w = writes()
check("(a) one write row", len(w) == 1, w)
if w:
    check("(a) target", (w[0].get("target_kind"), w[0].get("target_id")) == ("event", A), w[0])
    check("(a) inverse", w[0].get("inverse") == {"op": "delete_event", "id": A},
          w[0].get("inverse"))

# ── (b) ──────────────────────────────────────────────────────────────────
print("(b) refusals")
n_writes = len(writes())
n_events = len(events.get_all_events())
for label, patch, needles in (
        ("unknown category", {"category": "heist"},
         ("heist", "ambient", "social", "disruption", "danger")),
        ("ttl 721", {"ttl_hours": 721}, ("720",)),
        ("ttl 1.5", {"ttl_hours": 1.5}, ("ttl_hours",)),
        ("unknown location", {"location_id": "nope"}, ("nope",)),
        ("empty text", {"text": ""}, ("text",)),
        ("padded text", {"text": "  padded  "}, ("blanks",)),
        ("long text", {"text": "x" * 501}, ("500",)),
        ("unknown key", {"when": "now"}, ("when",))):
    res = call("add_event", {**BASE, **patch})
    check(f"(b) {label} refused",
          not res.ok and not res.wrote and all(n in res.line for n in needles), res.line)
check("(b) no new write rows", len(writes()) == n_writes, len(writes()))
check("(b) no new events", len(events.get_all_events()) == n_events)

# ── (c) ──────────────────────────────────────────────────────────────────
print("(c) global event, ttl 0")
THUNDER = "Thunder rolls over the land."
r = call("add_event", {"text": THUNDER})
G = eid_of(r)
check("(c) ok", r.ok and G, r.line)
check("(c) at everywhere", "at everywhere (uncategorized, 24 game hours)" in (r.line or ""),
      r.line)
check("(c) global", G and (events.get_event(G) or {"location_id": "x"}).get("location_id") is None)
r = call("add_event", {"text": "A quiet hour.", "ttl_hours": 0})
Z = eid_of(r)
check("(c) ttl 0 ok", r.ok and Z and "never expires" in r.line, r.line)
check("(c) ttl 0 has no expiry", Z and "expires_at" in (events.get_event(Z) or {})
      and events.get_event(Z)["expires_at"] is None, events.get_event(Z) if Z else None)

# ── (d) ──────────────────────────────────────────────────────────────────
print("(d) changed since")
if A:
    events.record_attempt(A, "Demo Someone", "haggles", "fail")
pv = wu.discard_preview(run)
check("(d) preview", pv == [f"event {A} was changed since — the discard leaves it alone",
                            f'event {G} "{THUNDER}"', f'event {Z} "A quiet hour."'], pv)
u = wu.undo(run)
check("(d) not complete", not u["complete"], u)
sk = [s for s in u["skipped"] if s.get("reason") == wu.REASON_CHANGED]
check("(d) changed since, keys [resolution]",
      len(sk) == 1 and sk[0].get("keys") == ["resolution"], u["skipped"])
check("(d) A stays", A and events.get_event(A) is not None)
check("(d) G and Z gone", events.get_event(G or "x") is None and events.get_event(Z or "x") is None)
if A:
    events.delete_event(A)

# ── (e) ──────────────────────────────────────────────────────────────────
print("(e) clean run, delete_created")
run = new_run("events 2")
r = call("add_event", {"text": "Bells ring at the square.", "location_id": SQUARE})
E1 = eid_of(r)
r = call("add_event", {"text": "A cold wind blows.", "category": "ambient"})
E2 = eid_of(r)
check("(e) both ok", E1 and E2)
r = call("add_event", {"text": "Third."})
E3 = eid_of(r)
r = call("delete_created", {"kind": "event", "id": E3})
check("(e) same-turn delete ok", r.ok, r.line)
check("(e) E3 gone", E3 and events.get_event(E3) is None)
r = call("add_event", {"text": "Fourth."})
E4 = eid_of(r)
r = call("delete_created", {"kind": "event", "id": E4}, turn=2)
check("(e) earlier turn refused", not r.ok and "created in an earlier turn" in r.line, r.line)
check("(e) E4 stays", E4 and events.get_event(E4) is not None)
pv = wu.discard_preview(run)
check("(e) preview", pv == [f'event {E1} "Bells ring at the square."',
                            f'event {E2} "A cold wind blows."', f'event {E4} "Fourth."'], pv)
u = wu.undo(run)
check("(e) complete", u["complete"], u)
check("(e) no events left", events.get_all_events() == [], events.get_all_events())


# ── (f) ──────────────────────────────────────────────────────────────────
def loc_id(name):
    return next((l["id"] for l in list_locations() if l.get("name") == name), "")


def refs_case(tag, create_turn, event_turn):
    global run
    run = new_run(f"events {tag}")
    r = call("create_location", {"data": {"name": "Demo Fair"}, "x": 60, "z": 0},
             turn=create_turn)
    check(f"({tag}) fair", r.ok, r.line)
    fair = loc_id("Demo Fair")
    r = call("add_event", {"text": "Jugglers perform.", "location_id": fair}, turn=event_turn)
    v = eid_of(r)
    check(f"({tag}) event ok", r.ok and v, r.line)
    r = call("delete_created", {"kind": "location", "id": fair}, turn=event_turn)
    check(f"({tag}) location delete refused",
          not r.ok and "still named by" in r.line and f"event {v}" in r.line, r.line)
    check(f"({tag}) fair still there", get_location_by_id(fair) is not None)
    r = call("delete_created", {"kind": "event", "id": v}, turn=event_turn)
    check(f"({tag}) event delete ok", r.ok, r.line)
    r = call("delete_created", {"kind": "location", "id": fair}, turn=event_turn)
    check(f"({tag}) location delete ok", r.ok, r.line)
    u = wu.undo(run)
    check(f"({tag}) undo complete", u["complete"], u)
    check(f"({tag}) nothing left", loc_id("Demo Fair") == "" and events.get_all_events() == [])


print("(f) references, same turn")
refs_case("f", 1, 1)
print("(f2) references, earlier turn")
refs_case("f2", 1, 2)

print("(g) singular hour, strict read")
run = new_run("events-g")
r = call("add_event", {"text": "A short bell.", "ttl_hours": 1})
H = eid_of(r)
check("(g) ok", r.ok and H, r.line)
check("(g) singular", (r.line or "").endswith('(uncategorized, 1 game hour): "A short bell."'),
      r.line)
_real_exists = events.event_exists
events.event_exists = lambda _eid: None
try:
    try:
        wu.discard_preview(run)
        prev_err = ""
    except RuntimeError as e:
        prev_err = str(e)
    check("(g) preview raises on a read error", "could not be read" in prev_err, prev_err)
    u = wu.undo(run)
    skips = u.get("skipped") or []
    check("(g) undo not complete", not u["complete"], u)
    check("(g) one 'undo failed' skip", len(skips) == 1
          and str(skips[0].get("reason") or "").startswith("undo failed"), skips)
finally:
    events.event_exists = _real_exists
check("(g) H still stored", H and events.get_event(H) is not None)
if H:
    events.delete_event(H)

# ── (h) ──────────────────────────────────────────────────────────────────
print("(h) strict reference read")
import sqlite3  # noqa: E402
import threading  # noqa: E402

from app.core.keyed_lock import keyed_lock  # noqa: E402

run = new_run("events-h")
r = call("create_location", {"data": {"name": "Demo Booth"}, "x": 90, "z": 0})
check("(h) booth", r.ok, r.line)
booth = loc_id("Demo Booth")
_real_conn = events.get_connection


def _broken_conn():
    raise sqlite3.OperationalError("disk I/O error")


events.get_connection = _broken_conn
try:
    check("(h) lenient reader falls back", isinstance(events.get_all_events(), list))
    try:
        events.get_all_events_strict()
        strict_err = ""
    except sqlite3.OperationalError as e:
        strict_err = str(e)
    check("(h) strict reader raises", "disk I/O" in strict_err, strict_err)
    r = call("delete_created", {"kind": "location", "id": booth})
    check("(h) delete refused on a read error",
          not r.ok and "events could not be read" in (r.line or ""), r.line)
finally:
    events.get_connection = _real_conn
check("(h) booth still there", get_location_by_id(booth) is not None)
r = call("delete_created", {"kind": "location", "id": booth})
check("(h) delete ok after the patch", r.ok, r.line)
u = wu.undo(run)
check("(h) undo complete", u["complete"], u)

# ── (i) ──────────────────────────────────────────────────────────────────
print("(i) add_stat_hit takes the event lock")
K = events.add_event("Demo lock check.")["id"]
with keyed_lock("world_event", K):
    th = threading.Thread(target=events.add_stat_hit, args=(K, "Demo Hit"))
    th.start()
    th.join(0.2)
    check("(i) blocked while the lock is held", th.is_alive())
    check("(i) no hit yet",
          not ((events.get_event(K) or {}).get("metadata") or {}).get("stat_hit"))
th.join(5)
check("(i) ends after the release", not th.is_alive())
check("(i) hit stored",
      ((events.get_event(K) or {}).get("metadata") or {}).get("stat_hit") == ["Demo Hit"],
      events.get_event(K))
events.delete_event(K)

print()
if failures:
    print(f"FAILED ({len(failures)}):")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("all checks passed")
