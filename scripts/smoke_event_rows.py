#!/usr/bin/env python3
"""Events are written row by row: a read never deletes, a concurrent add is
never lost, and expiry happens in the periodic tick.

Usage:
    ./.venv/bin/python scripts/smoke_event_rows.py

No server: a THROWAWAY storage directory (tempfile + ``paths.init``) holds the
world DB, the game clock is moved with ``set_game_time``.

Why this exists (review 2026-09-20, DATA-2): ``_save_events`` wrote the WHOLE
table and deleted every row whose id was missing from the list it was handed.
``list_events()`` — a read path that ``/play`` polls — called it via
``_cleanup_expired``. An event created by another thread between that load and
that save was deleted seconds after its creation.

Checks and their hand-derived expectations:

  1 add/list race: 4 writer threads x 15 events = 60 events, 4 reader threads
    calling ``list_events()`` 40x each while an ALREADY EXPIRED event sits in
    the table. Expected: exactly 60 live events afterwards. Pre-fix, every
    reader rewrote the table from a stale snapshot and deleted whatever had
    been inserted in between.
  2 the read path writes nothing: with an expired event present, the number of
    rows in the table is the same before and after ``list_events()``, and the
    expired event is NOT in the result.
  3 ``expire_events()`` deletes exactly the expired rows and returns their
    count; a live event stays.
  4 the block rule coupled to a danger event is gone after the expiry tick
    (it used to be cleaned up from the read path).
  5 ``resolve_event`` touches exactly one row: the other events keep their
    payload, the resolved one gets ``resolved`` plus an ``expires_at`` of
    now + RESOLVED_TTL_HOURS (2 GAME hours).
  6 ``delete_event`` removes exactly one row (3 -> 2) and returns False for an
    unknown id.

A TTL is GAME hours: an event created at Y0002-D100T12:00 with ttl_hours=1
expires at Y0002-D100T13:00, so setting the clock to 14:00 expires it and
13:00 does not (``_is_expired`` compares strictly greater).
"""
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="eventrows-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="eventrows-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core.db import get_connection  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models.events import (RESOLVED_TTL_HOURS, add_event,  # noqa: E402
                               delete_event, expire_events, get_event,
                               list_events, resolve_event)
from app.models.rules import add_event_rule, load_rules  # noqa: E402

CHECKED = 0
FAILURES = []


def check(label, got, expected):
    global CHECKED
    CHECKED += 1
    if got != expected:
        FAILURES.append(f"{label}: got {got!r}, expected {expected!r}")
        print(f"  FAIL {label}: {got!r} != {expected!r}")
    else:
        print(f"  ok   {label}: {got}")


def row_count():
    return get_connection().execute(
        "SELECT COUNT(*) FROM events WHERE kind='world_event'").fetchone()[0]


def clear_events():
    with db.transaction() as conn:
        conn.execute("DELETE FROM events WHERE kind='world_event'")


def set_clock(hour, minute=0):
    set_game_time(GameTime.from_parts(2, 100, hour, minute, 0))


# The clock must not run away under us while the threads work.
set_game_factor(0.0)
set_clock(12)

print("1) a concurrent add is never lost while readers poll")
clear_events()
# One event that is already expired, so the old read path had a reason to
# rewrite the whole table on every single list_events() call.
add_event("an old notice fades", location_id="loc1", ttl_hours=1,
          category="ambient")
set_clock(14)          # the notice expired at 13:00
check("1 the expired event is filtered out of the read",
      [e["text"] for e in list_events()], [])

WRITERS, PER_WRITER, READERS, READS = 4, 15, 4, 40
errors = []


def writer(n):
    try:
        for i in range(PER_WRITER):
            add_event(f"writer {n} event {i}", location_id="loc1",
                      ttl_hours=24, category="ambient")
    except Exception as e:      # pragma: no cover - surfaced as a failure
        errors.append(f"writer {n}: {e}")


def reader():
    try:
        for _ in range(READS):
            list_events(location_id="loc1")
    except Exception as e:      # pragma: no cover
        errors.append(f"reader: {e}")


threads = ([threading.Thread(target=writer, args=(n,)) for n in range(WRITERS)]
           + [threading.Thread(target=reader) for _ in range(READERS)])
for t in threads:
    t.start()
for t in threads:
    t.join()

check("1 no thread errors", errors, [])
live = [e for e in list_events(location_id="loc1")
        if e["text"].startswith("writer ")]
check("1 every concurrently added event survived", len(live),
      WRITERS * PER_WRITER)

print("2) the read path does not write")
clear_events()
set_clock(12)
evt_old = add_event("a puddle dries up", location_id="loc1", ttl_hours=1,
                    category="ambient")
evt_live = add_event("the market is busy", location_id="loc1", ttl_hours=12,
                     category="social")
set_clock(14)
before = row_count()
listed = [e["id"] for e in list_events(location_id="loc1")]
check("2 rows untouched by the read", row_count(), before)
check("2 only the live event is listed", listed, [evt_live["id"]])
check("2 the expired row is still in the table", row_count(), 2)

print("3) expire_events() removes exactly the expired rows")
check("3 one row expired", expire_events(), 1)
check("3 the live row stayed", row_count(), 1)
check("3 the expired event is gone", get_event(evt_old["id"]), None)
check("3 a second tick finds nothing", expire_events(), 0)

print("4) the block rule of a danger event dies with it")
clear_events()
set_clock(12)
evt_danger = add_event("a rockslide blocks the path", location_id="loc1",
                       ttl_hours=1, category="danger")
add_event_rule(evt_danger["id"], "loc1", "The path is blocked.",
               action="leave")
check("4 rule created",
      len([r for r in load_rules() if r.get("event_id") == evt_danger["id"]]), 1)
set_clock(14)
check("4 the expiry tick removed the event", expire_events(), 1)
check("4 the coupled rule is gone",
      len([r for r in load_rules() if r.get("event_id") == evt_danger["id"]]), 0)

print("5) resolve_event touches exactly one row")
clear_events()
set_clock(12)
a = add_event("a fight breaks out", location_id="loc1", ttl_hours=8,
              category="disruption")
b = add_event("someone is singing", location_id="loc1", ttl_hours=8,
              category="social")
c = add_event("a dog barks", location_id="loc1", ttl_hours=8,
              category="ambient")
resolved = resolve_event(a["id"], resolved_by="Ada", resolved_text="broke it up")
check("5 resolve returned the event", bool(resolved and resolved.get("resolved")),
      True)
check("5 resolved flag persisted", get_event(a["id"]).get("resolved"), True)
check("5 resolved expiry = now + 2 game hours",
      get_event(a["id"]).get("expires_at"),
      GameTime.from_parts(2, 100, 12 + RESOLVED_TTL_HOURS, 0, 0).canonical())
check("5 the other rows are untouched",
      [bool(get_event(x["id"]).get("resolved")) for x in (b, c)], [False, False])
check("5 row count unchanged", row_count(), 3)
check("5 an ambient event cannot be resolved", resolve_event(c["id"]), None)

print("6) delete_event removes exactly one row")
check("6 delete returns True", delete_event(b["id"]), True)
check("6 two rows left", row_count(), 2)
check("6 the deleted event is gone", get_event(b["id"]), None)
check("6 the others are still there",
      [get_event(x["id"]) is not None for x in (a, c)], [True, True])
check("6 deleting an unknown id returns False", delete_event("evt_nope"), False)

print()
print(f"(throwaway storage: {STORAGE})")
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
