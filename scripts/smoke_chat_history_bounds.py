#!/usr/bin/env python3
"""Smoke: the chat history has an index for its hot reads and a bounded read.

Usage:
    ./.venv/bin/python scripts/smoke_chat_history_bounds.py

Throwaway storage (tempfile + ``paths.init``), no server, no real world DB, no
LLM. Rows are inserted straight into the throwaway ``chat_messages`` table.

WHY (DATA-12 of the 2026-09-20 review)
--------------------------------------
``chat_messages`` is never pruned (deliberately — it is user data), and
``UnifiedChatManager.get_chat_history`` read ALL of it on every chat turn and
built a ``Message`` object per row for a prompt that keeps the last ~100.
Two things were missing:

  (a) THE INDEX. Only ``(character_name, partner, ts)`` and ``(ts)`` existed.
      The partner-less read (``WHERE character_name=? ORDER BY ts``) and the
      day rollups of ``history_manager._get_day_messages``
      (``WHERE character_name=? AND ts>=? AND ts<?``) can use only the FIRST
      column of that composite and then scan every row of the character.
      ``idx_chat_char_ts (character_name, ts)`` is what those two want.

  (b) THE BOUND. ``limit`` existed but was a Python tail applied AFTER every
      row had been read, parsed and object-ified.

WHAT IS CHECKED, and where every expected value comes from
-----------------------------------------------------------
  [1] THE INDEX EXISTS after ``db.init_schema()`` — and an EXISTING world gets
      it at boot: the index is dropped again and ``init_schema()`` is re-run
      (it executes every statement of ``SCHEMA_STATEMENTS``, all
      ``IF NOT EXISTS``), after which it is back. That is the migration path
      for worlds created by the old schema.

  [2] EXPLAIN QUERY PLAN. SQLite must NAME ``idx_chat_char_ts`` for both hot
      reads — the bounded partner-less read
      (``WHERE character_name=? ORDER BY ts DESC, id DESC LIMIT ?``) and the
      day window (``WHERE character_name=? AND ts>=? AND ts<?``). Without the
      index the plan says ``SEARCH ... USING INDEX idx_chat_char_partner_ts
      (character_name=?)`` plus a temp B-tree for the ORDER BY; the check is
      on the index NAME, so it fails on the old schema.

  [3] THE FIXTURE, and the pair history derived from it by hand.
      Direction (Ann, partner=Bob), ts T01…T10, roles alternating
      user/assistant starting with user, contents a01…a10.
      Direction (Bob, partner=Ann): first the TalkTo double-write of a06…a10
      (same ts, same content, the OPPOSITE role — which the reader flips back,
      so they collide with the originals on the dedup key (ts, role, content)),
      then three own messages b11…b13 at T11…T13.
      Finally two more messages of Ann in the same pair bucket, c14 at
      T14 and c15 at T15.
      => the merged, deduped, chronological history of Ann↔Bob is exactly
         a01 … a10, b11, b12, b13, c14, c15  =  15 messages.

  [4] THE BOUND IS EXACT. For every limit in 1, 2, 5, 12, 13, 14, 50 the
      bounded read returns exactly the last ``limit`` entries of the unbounded
      one — same contents, same roles, same timestamps. That covers the
      dedup boundary (the duplicates sit at a06…a10, i.e. limits 4…8 cut right
      through them) and both ends (fewer rows than asked for).

  [5] THE BOUND IS IN SQL, not in Python. The connection's trace callback
      records the statements; only the ones touching ``chat_messages`` are
      looked at. With a limit the reader issues a statement carrying "LIMIT"
      (the partner-less tail, and for the pair the ``UNION`` cutoff probe),
      without one it issues none. Fails on the old code, where the limit was
      a Python slice and no statement ever carried a LIMIT.

  [6] DEFAULT UNCHANGED: without ``limit`` the full history comes back, and
      the statement carries no LIMIT.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="chat-bounds-smoke-"))

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import world_db_schema  # noqa: E402
from app.models.unified_chat import UnifiedChatManager as UCM  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


INDEX = "idx_chat_char_ts"


def index_names():
    return {r[0] for r in db.get_connection().execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='chat_messages'"
    ).fetchall()}


print("[1] the index, and the migration of an existing world")
check("declared in SCHEMA_STATEMENTS",
      any(INDEX in s for s in world_db_schema.SCHEMA_STATEMENTS
          if isinstance(s, str)))
check("present after init_schema", INDEX in index_names(), str(sorted(index_names())))
with db.transaction() as conn:
    conn.execute(f"DROP INDEX {INDEX}")
check("dropped (simulating a world from the old schema)", INDEX not in index_names())
db.init_schema()
check("re-created by a plain init_schema (= at boot)", INDEX in index_names())

print("[2] EXPLAIN QUERY PLAN names it")
conn = db.get_connection()
plan_tail = " ".join(str(r[-1]) for r in conn.execute(
    "EXPLAIN QUERY PLAN SELECT id, ts, role, content FROM chat_messages "
    "WHERE character_name=? ORDER BY ts DESC, id DESC LIMIT ?",
    ("Ann", 5)).fetchall())
check("bounded partner-less read uses it", INDEX in plan_tail, plan_tail)
plan_day = " ".join(str(r[-1]) for r in conn.execute(
    "EXPLAIN QUERY PLAN SELECT role, content FROM chat_messages "
    "WHERE character_name=? AND ts >= ? AND ts < ? ORDER BY ts ASC",
    ("Ann", "a", "b")).fetchall())
check("day-window read uses it", INDEX in plan_day, plan_day)

print("[3] the fixture")
# chat_messages.character_name is a FK on characters(name) — two bare rows.
with db.transaction() as c:
    c.executemany(
        "INSERT INTO characters (name, template, profile_json, config_json, "
        "created_at, updated_at) VALUES (?, '', '{}', '{}', 'T00', 'T00')",
        [("Ann",), ("Bob",)])
ROWS = []
for i in range(1, 11):
    ROWS.append(("Ann", "Bob", f"T{i:02d}", "user" if i % 2 else "assistant", f"a{i:02d}", "web"))
# TalkTo double-write: the same five messages in the other bucket, roles as the
# other side stored them (the reader flips them back).
for i in range(6, 11):
    flipped = "assistant" if (i % 2) else "user"
    ROWS.append(("Bob", "Ann", f"T{i:02d}", flipped, f"a{i:02d}", "web"))
for i in range(11, 14):
    ROWS.append(("Bob", "Ann", f"T{i:02d}", "user" if i % 2 else "assistant", f"b{i:02d}", "web"))
# Two more messages of Ann in the same pair bucket.
ROWS.append(("Ann", "Bob", "T14", "user", "c14", "web"))
ROWS.append(("Ann", "Bob", "T15", "assistant", "c15", "web"))
with db.transaction() as c:
    c.executemany(
        "INSERT INTO chat_messages (character_name, partner, ts, role, content, "
        "channel, metadata) VALUES (?, ?, ?, ?, ?, ?, '{}')", ROWS)

full = UCM.get_chat_history("Ann", partner_name="Bob")
contents = [m.content for m in full]
expected = [f"a{i:02d}" for i in range(1, 11)] + ["b11", "b12", "b13", "c14", "c15"]
check("merged, deduped, chronological pair history",
      contents == expected, str(contents))

print("[4] the bound is exact")
for limit in (1, 2, 5, 12, 13, 14, 50):
    got = UCM.get_chat_history("Ann", partner_name="Bob", limit=limit)
    want = full[-limit:]
    same = ([(m.role, m.content, m.timestamp) for m in got]
            == [(m.role, m.content, m.timestamp) for m in want])
    check(f"limit={limit} == full[-{limit}:]", same,
          f"{[m.content for m in got]}")

print("[5] the bound is in SQL")
seen = []


def chat_sql(**kw):
    """The statements one ``get_chat_history`` call issues against
    ``chat_messages`` — everything else (the account probe of
    ``_resolve_partner_key``) is noise here."""
    seen.clear()
    conn.set_trace_callback(seen.append)
    try:
        UCM.get_chat_history("Ann", **kw)
    finally:
        conn.set_trace_callback(None)
    return [q for q in seen if "chat_messages" in q]


pair_bounded = chat_sql(partner_name="Bob", limit=5)
pair_plain = chat_sql(partner_name="Bob")
solo_bounded = chat_sql(partner_name="", limit=5)
solo_plain = chat_sql(partner_name="")
check("pair read with limit issues a LIMIT",
      any("LIMIT" in q.upper() for q in pair_bounded), str(len(pair_bounded)))
check("pair read with limit probes the dedup cutoff (UNION)",
      any("UNION" in q.upper() for q in pair_bounded))
check("pair read without limit issues none",
      not any("LIMIT" in q.upper() for q in pair_plain))
check("partner-less read with limit issues a LIMIT",
      any("LIMIT" in q.upper() for q in solo_bounded), str(len(solo_bounded)))
check("partner-less read without limit issues none",
      not any("LIMIT" in q.upper() for q in solo_plain))

print("[6] default unchanged")
check("no limit -> the full history",
      [m.content for m in UCM.get_chat_history("Ann", partner_name="Bob")] == expected)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
for f in FAILURES:
    print(f"  FAILED: {f}")
sys.exit(1 if FAILURES else 0)
