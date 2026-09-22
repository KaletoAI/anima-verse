#!/usr/bin/env python3
"""Smoke: chat retention deletes only what a summary already preserved.

Usage:
    ./.venv/bin/python scripts/smoke_chat_retention.py

Throwaway storage (tempfile + ``paths.init`` BEFORE any DB import), no server,
no real world DB, no LLM. Rows are inserted straight into the throwaway
``chat_messages`` / ``summaries`` tables.

WHY
---
``chat_messages`` grew without bound: nothing pruned it except
``delete_character``, the NPC-pool cleanup and the admin rewind, none of which
is about age. ``app/core/chat_retention.py`` adds the age rule, with the guard
that makes it safe: a message may only go once the GAME day it belongs to has
been rolled up into a summary, so the pruner can never delete the only record
of something the world never summarized.

THE CLOCK. The horizon is SYSTEM time (``memory.chat_retention_days`` = real
days, like ``scene_manager.WILDERNESS_RETENTION_DAYS``); the day a row belongs
to is GAME time. The fixture drives the clock through the project API
(``timeutils.set_game_factor`` / ``set_game_time``) and pins the FACTOR AT
1.0, so exactly one game day passes per real day and "N real days ago" is the
game day ``anchor - N days``. That is the only assumption the expected day
keys below rest on.

THE FIXTURE, and every expected number derived from it by hand
--------------------------------------------------------------
Game clock: factor 1.0, anchored NOW at game day index 400, 12:00:00.
So a row stamped N real days ago falls on game day index ``400 - N``, at
12:00 — never near a day boundary, so no rounding can move it.

Rows (all in the pair Ann <-> Bob), with their system age:

    dayA = 120 real days ago   Ann: 2 rows    Ann HAS a daily summary
    dayB = 100 real days ago   Ann: 3 rows    Ann has NO summary at all
    dayC =  95 real days ago   Ann: 2 rows    Ann HAS a daily summary
                               Bob: 1 row     Bob has NO summary
                               (one of Ann's two dayC rows and Bob's single
                                row are the SAME TalkTo utterance, written
                                into both buckets: same ts, same content,
                                opposite role)
    dayD =   5 real days ago   Ann: 4 rows    Ann HAS a daily summary

Retention horizon for the run: 90 days. Cutoff = now - 90 days, so dayA, dayB
and dayC are older than the cutoff and dayD is not.

  [2] RETENTION 0 = keep forever. Nothing is even examined:
      {examined: 0, deleted: 0, kept_unsummarized: 0}, table size unchanged
      (2+3+2+4 Ann + 1 Bob = 12 rows).

  [3] RETENTION 90, the counts, by hand:
      examined            = Ann 2+3+2 (dayD is inside the horizon and is never
                            read) + Bob 1                      =  8
      deleted             = Ann dayA 2 + Ann dayC 2            =  4
      kept_unsummarized   = Ann dayB 3 + Bob dayC 1            =  4
      Bob's copy of the TalkTo line is judged by BOB's summaries, which do not
      exist — so it stays although Ann's copy of the very same utterance goes.
      That is the point of per-character processing.

  [4] WHAT SURVIVES: Ann has 3 + 4 = 7 rows left (dayB and dayD), Bob 1.
      No dayA or dayC row of Ann is left.

  [5] THE RECENT TAIL IS UNTOUCHED: the last four entries of
      ``get_chat_history("Ann", partner_name="Bob")`` — contents, roles and
      timestamps — are byte-identical before and after the prune.

  [6] IDEMPOTENT: a second run at 90 days deletes 0. It still EXAMINES the 4
      rows that stayed (Ann dayB 3 + Bob dayC 1) and keeps them.

  [7] THE ROLLUP LADDER. ``memory_service._consolidate_daily_to_weekly``
      DELETES the day summaries it folds into a week (``delete_daily_summaries``),
      and the weekly fold in turn goes into a season — so by the time a day is
      old enough to prune, its daily row is usually gone. A day is therefore
      "rolled up" when a daily OR the weekly OR the seasonal summary covers
      it. Checked with a third character, Cid:
          110 days ago: 2 rows, no daily summary, but a WEEKLY summary for
                        ``_week_key`` of that day          -> both deleted
           96 days ago: 2 rows, no summary of any tier     -> both kept
      The pass walks every character, so Ann's dayB (3) and Bob's TalkTo copy
      (1) are examined and kept again alongside Cid's four rows:
      Expected {examined: 8, deleted: 2, kept_unsummarized: 6}.
      Without the weekly/seasonal tiers this check deletes 0 — it is what
      distinguishes a pruner that works from one that never fires.

  [1] THE INDEX ``idx_chat_char_ts (character_name, ts)`` — the rollup's
      ``character_name`` + ts-range filter and this pruner's cutoff scan both
      want it. It must exist after ``init_schema()``, and an EXISTING world
      must get it at boot: the index is dropped and ``init_schema()`` re-run
      (every statement is ``IF NOT EXISTS``), after which it is back.
"""
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="chat-retention-smoke-"))

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import timeutils  # noqa: E402
from app.core.chat_retention import prune_chat_messages  # noqa: E402
from app.core.game_time import DAY_SECONDS, GameDuration, GameTime  # noqa: E402
from app.core.memory_service import _week_key  # noqa: E402
from app.models.chat import get_chat_history  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(label)


def eq(label: str, got, want) -> None:
    check(label, got == want, f"got {got!r}, want {want!r}")


INDEX = "idx_chat_char_ts"


def index_names():
    return {r[0] for r in db.get_connection().execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND tbl_name='chat_messages'").fetchall()}


def row_count(name: str) -> int:
    return db.get_connection().execute(
        "SELECT COUNT(*) FROM chat_messages WHERE character_name=?",
        (name,)).fetchone()[0]


# ---------------------------------------------------------------------------
print("[1] the index, and the migration of an existing world")
from app.core import world_db_schema  # noqa: E402
check("declared in SCHEMA_STATEMENTS",
      any(INDEX in s for s in world_db_schema.SCHEMA_STATEMENTS
          if isinstance(s, str)))
check("present after init_schema", INDEX in index_names())
with db.transaction() as _c:
    _c.execute(f"DROP INDEX {INDEX}")
check("dropped (simulating a world from the old schema)", INDEX not in index_names())
db.init_schema()
check("re-created by a plain init_schema (= at boot)", INDEX in index_names())

# ---------------------------------------------------------------------------
print("the fixture")
with db.transaction() as _c:
    _c.executemany(
        "INSERT INTO characters (name, template, profile_json, config_json, "
        "created_at, updated_at) VALUES (?, '', '{}', '{}', 'T00', 'T00')",
        [("Ann",), ("Bob",), ("Cid",)])

# Game clock: exactly one game day per real day, anchored at day index 400.
timeutils.set_game_factor(1.0)
ANCHOR = GameTime(400 * DAY_SECONDS + 12 * 3600)
timeutils.set_game_time(ANCHOR)
NOW = timeutils.utc_now()


def stamp(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat(timespec="seconds")


def day_key(days_ago: int) -> str:
    return (ANCHOR - GameDuration.of(days=days_ago)).day_key()


check("the clock runs at factor 1.0", timeutils.game_speed_factor() == 1.0,
      str(timeutils.game_speed_factor()))
check("a stamp N real days back lands on game day anchor-N",
      timeutils.game_time_at(stamp(120)).day_key() == day_key(120),
      f"{timeutils.game_time_at(stamp(120)).day_key()} vs {day_key(120)}")


def add(character: str, partner: str, days_ago: int, role: str, content: str,
        ts: str = "") -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO chat_messages (character_name, partner, ts, role, "
            "content, channel, metadata) VALUES (?, ?, ?, ?, ?, 'web', '{}')",
            (character, partner, ts or stamp(days_ago), role, content))


def add_summary(character: str, kind: str, date_key: str) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO summaries (character_name, kind, date_key, partner, "
            "content) VALUES (?, ?, ?, 'Bob', 'rolled up')",
            (character, kind, date_key))


add("Ann", "Bob", 120, "user", "a1")
add("Ann", "Bob", 120, "assistant", "a2")
for i in (1, 2, 3):
    add("Ann", "Bob", 100, "user" if i % 2 else "assistant", f"b{i}")
add("Ann", "Bob", 95, "user", "c1")
# The TalkTo double-write: one utterance, both buckets, same ts + content.
TALKTO_TS = stamp(95)
add("Ann", "Bob", 95, "assistant", "c-talkto", ts=TALKTO_TS)
add("Bob", "Ann", 95, "user", "c-talkto", ts=TALKTO_TS)
for i in (1, 2, 3, 4):
    add("Ann", "Bob", 5, "user" if i % 2 else "assistant", f"d{i}")

add_summary("Ann", "daily", day_key(120))
add_summary("Ann", "daily", day_key(95))
add_summary("Ann", "daily", day_key(5))
eq("fixture: Ann rows", row_count("Ann"), 11)
eq("fixture: Bob rows", row_count("Bob"), 1)

TAIL_BEFORE = [(m.get("content"), m.get("role"), m.get("timestamp"))
               for m in (get_chat_history("Ann", partner_name="Bob") or [])][-4:]
eq("fixture: the recent tail is the four dayD lines",
   [t[0] for t in TAIL_BEFORE], ["d1", "d2", "d3", "d4"])

# ---------------------------------------------------------------------------
print("[2] retention 0 keeps everything and examines nothing")
eq("counts", prune_chat_messages(0),
   {"examined": 0, "deleted": 0, "kept_unsummarized": 0})
eq("table untouched", row_count("Ann") + row_count("Bob"), 12)

# ---------------------------------------------------------------------------
print("[3] retention 90 — the counts derived by hand")
eq("counts", prune_chat_messages(90),
   {"examined": 8, "deleted": 4, "kept_unsummarized": 4})

# ---------------------------------------------------------------------------
print("[4] what survives")
eq("Ann keeps dayB + dayD", row_count("Ann"), 7)
eq("Bob keeps its own copy of the TalkTo line", row_count("Bob"), 1)
left = {r[0] for r in db.get_connection().execute(
    "SELECT content FROM chat_messages WHERE character_name='Ann'").fetchall()}
eq("Ann's remaining contents", sorted(left),
   ["b1", "b2", "b3", "d1", "d2", "d3", "d4"])
eq("Bob's copy is still there",
   db.get_connection().execute(
       "SELECT content FROM chat_messages WHERE character_name='Bob'"
   ).fetchone()[0], "c-talkto")

# ---------------------------------------------------------------------------
print("[5] the recent tail of get_chat_history is unchanged")
tail_after = [(m.get("content"), m.get("role"), m.get("timestamp"))
              for m in (get_chat_history("Ann", partner_name="Bob") or [])][-4:]
eq("tail identical", tail_after, TAIL_BEFORE)

# ---------------------------------------------------------------------------
print("[6] a second run deletes nothing")
eq("counts", prune_chat_messages(90),
   {"examined": 4, "deleted": 0, "kept_unsummarized": 4})
eq("table size unchanged", row_count("Ann") + row_count("Bob"), 8)

# ---------------------------------------------------------------------------
print("[7] a day folded into a WEEK summary counts as rolled up")
add("Cid", "Ann", 110, "user", "e1")
add("Cid", "Ann", 110, "assistant", "e2")
add("Cid", "Ann", 96, "user", "f1")
add("Cid", "Ann", 96, "assistant", "f2")
week_of_110 = _week_key(ANCHOR - GameDuration.of(days=110))
check("the two Cid days are in different weeks",
      week_of_110 != _week_key(ANCHOR - GameDuration.of(days=96)),
      f"{week_of_110} vs {_week_key(ANCHOR - GameDuration.of(days=96))}")
with db.transaction() as _c:
    _c.execute("INSERT INTO summaries (character_name, kind, date_key, "
               "partner, content) VALUES ('Cid', 'weekly', ?, '', 'week')",
               (week_of_110,))
eq("counts", prune_chat_messages(90),
   {"examined": 8, "deleted": 2, "kept_unsummarized": 6})
eq("only the unsummarized day of Cid is left",
   sorted(r[0] for r in db.get_connection().execute(
       "SELECT content FROM chat_messages WHERE character_name='Cid'"
   ).fetchall()), ["f1", "f2"])

# ---------------------------------------------------------------------------
print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print(f"OK (throwaway storage: {STORAGE})")
