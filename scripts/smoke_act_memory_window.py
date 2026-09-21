#!/usr/bin/env python3
"""act_engine cooldown/dedup: the two memory windows must be answered by SQL,
with exactly the answers the old full-table scan gave.

Usage:  ./.venv/bin/python scripts/smoke_act_memory_window.py

No server, no real world DB — throwaway storage via ``paths.init`` plus a
freshly created schema, filled with 200 memory rows placed BY HAND around both
window edges.

Review 2026-09-20, finding SIM-6: ``_sender_on_cooldown`` and
``_recipient_recently_perceived`` called ``memory.load_memories``, i.e.
``SELECT * FROM memories WHERE character_name=?`` — the COMPLETE memory of a
character, every row turned into a dict — only to keep a 2- resp. 30-minute
window. The sender check runs once per act, the recipient check once per
recipient (up to RECIPIENT_CAP = 30), synchronously inside an LLM turn.

THE ORACLE
  Part B re-implements the OLD Python filter literally (``ORACLE_sender`` /
  ``ORACLE_recipient``, copied from the pre-fix source) and compares it with
  the new implementation over every case. "Identical results" is therefore not
  asserted against remembered numbers but against the old code itself, on the
  same 200 rows.

EXPECTED VALUES, DERIVED BY HAND
  SENDER_COOLDOWN_MIN = 2, RECIPIENT_DEDUP_MIN = 30 (act_engine constants).
  The cutoff is ``utc_now() - window``; the old loop skipped a row with
  ``ts < cutoff``, so a row exactly ON the cutoff still counts. Offsets below
  are in minutes before now.

  A) sender, scope "here" -> tag "action_performed:here"
    A1  tagged row at -1 min                    -> True  (inside 2 min)
    A2  newest tagged row at -3 min             -> False (outside 2 min)
    A3  tagged "action_performed:location" only
        at -1 min, asked for scope "here"       -> False (wrong tag)
    A4  no memories at all                      -> False

  B) recipient, actor "Ada_Lu" -> tag "action_witnessed:Ada_Lu"
    B1  tagged row at -10 min whose content
        contains the text                       -> True
    B2  same row at -40 min                     -> False (outside 30 min)
    B3  tagged row at -10 min, different text   -> False
    B4  row tagged for another actor at -10 min -> False
    B5  empty action text                       -> False (the dedup has
                                                  nothing to compare)
    B6  decoy tagged "action_witnessed:AdaXLu"
        at -10 min with matching content        -> False. The underscore in
                                                  "Ada_Lu" is a SQL LIKE
                                                  wildcard; without the ESCAPE
                                                  the decoy would match.

  C) equivalence + edges on 200 rows: one row per minute at -0.5 .. -199.5 min,
     every third row carrying the sender tag, every fourth the recipient tag,
     plus four rows placed 5 seconds either side of both cutoffs (2 min and
     30 min). New answer == old answer for: sender scope here/location, and
     recipient for three different texts. 8 comparisons.

  D) the full-table read is really gone: with ``memory.load_memories`` replaced
     by a raiser, both helpers still answer correctly. Fails before the fix by
     construction — the old code called exactly that function.
"""
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STORAGE = Path(tempfile.mkdtemp(prefix="actmem-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="actmem-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import act_engine  # noqa: E402
from app.core.timeutils import utc_now  # noqa: E402
from app.models import memory as memory_model  # noqa: E402

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


NOW = utc_now()


def ago(minutes):
    return (NOW - timedelta(minutes=minutes)).isoformat()


def entry(minutes_ago, tags, content):
    return {"timestamp": ago(minutes_ago), "memory_type": "episodic",
            "content": content, "tags": list(tags), "importance": 3}


def seed(name, entries):
    memory_model.save_memories(name, [])
    memory_model.save_memories(name, entries)


# ---------------------------------------------------------------------------
# The ORACLE — the pre-fix implementation, copied literally.
# ---------------------------------------------------------------------------
def ORACLE_sender(actor, scope):
    cutoff = (utc_now() - timedelta(minutes=act_engine.SENDER_COOLDOWN_MIN)).isoformat()
    target_tag = f"action_performed:{scope}"
    for m in memory_model.load_memories(actor):
        ts = m.get("timestamp") or ""
        if ts < cutoff:
            continue
        if target_tag in (m.get("tags") or []):
            return True
    return False


def ORACLE_recipient(recipient, actor, text):
    cutoff = (utc_now() - timedelta(minutes=act_engine.RECIPIENT_DEDUP_MIN)).isoformat()
    target_tag = f"action_witnessed:{actor}"
    text_norm = (text or "").strip().lower()[:80]
    if not text_norm:
        return False
    for m in memory_model.load_memories(recipient):
        ts = m.get("timestamp") or ""
        if ts < cutoff:
            continue
        tags = m.get("tags") or []
        if target_tag not in tags:
            continue
        content = (m.get("content") or "").strip().lower()
        if text_norm in content:
            return True
    return False


ACTOR = "Ada_Lu"
RECIPIENT = "Bo"
TEXT = "lifts the lantern"

# ``memories.character_name`` has a foreign key onto ``characters`` — two bare
# rows are enough, nothing here reads a profile.
with db.transaction() as conn:
    for _n in (ACTOR, RECIPIENT):
        conn.execute(
            "INSERT OR IGNORE INTO characters "
            "(name, template, profile_json, config_json, created_at, updated_at) "
            "VALUES (?, '', '{}', '{}', ?, ?)",
            (_n, NOW.isoformat(), NOW.isoformat()))

# ---------------------------------------------------------------------------
print("A) sender cooldown (2 minutes)")
# ---------------------------------------------------------------------------
seed(ACTOR, [entry(1, ["action_performed", "action_performed:here"], "acted")])
check("A1 tagged row 1 min ago", act_engine._sender_on_cooldown(ACTOR, "here"), True)

seed(ACTOR, [entry(3, ["action_performed", "action_performed:here"], "acted"),
             entry(9, ["action_performed", "action_performed:here"], "acted")])
check("A2 newest tagged row 3 min ago",
      act_engine._sender_on_cooldown(ACTOR, "here"), False)

seed(ACTOR, [entry(1, ["action_performed", "action_performed:location"], "acted")])
check("A3 wrong scope tag", act_engine._sender_on_cooldown(ACTOR, "here"), False)
check("A3 right scope tag", act_engine._sender_on_cooldown(ACTOR, "location"), True)

seed(ACTOR, [])
check("A4 no memories at all", act_engine._sender_on_cooldown(ACTOR, "here"), False)

# ---------------------------------------------------------------------------
print("B) recipient dedup (30 minutes)")
# ---------------------------------------------------------------------------
WIT = f"action_witnessed:{ACTOR}"
seed(RECIPIENT, [entry(10, ["action_witnessed", WIT], f"Ada_Lu {TEXT} slowly")])
check("B1 matching row 10 min ago",
      act_engine._recipient_recently_perceived(RECIPIENT, ACTOR, TEXT), True)

seed(RECIPIENT, [entry(40, ["action_witnessed", WIT], f"Ada_Lu {TEXT} slowly")])
check("B2 matching row 40 min ago",
      act_engine._recipient_recently_perceived(RECIPIENT, ACTOR, TEXT), False)

seed(RECIPIENT, [entry(10, ["action_witnessed", WIT], "Ada_Lu slams the door")])
check("B3 tagged but different text",
      act_engine._recipient_recently_perceived(RECIPIENT, ACTOR, TEXT), False)

seed(RECIPIENT, [entry(10, ["action_witnessed", "action_witnessed:Cy"],
                       f"Cy {TEXT} slowly")])
check("B4 another actor's row",
      act_engine._recipient_recently_perceived(RECIPIENT, ACTOR, TEXT), False)

seed(RECIPIENT, [entry(10, ["action_witnessed", WIT], f"Ada_Lu {TEXT} slowly")])
check("B5 empty action text",
      act_engine._recipient_recently_perceived(RECIPIENT, ACTOR, ""), False)

seed(RECIPIENT, [entry(10, ["action_witnessed", "action_witnessed:AdaXLu"],
                       f"AdaXLu {TEXT} slowly")])
check("B6 underscore is not a wildcard",
      act_engine._recipient_recently_perceived(RECIPIENT, ACTOR, TEXT), False)

# ---------------------------------------------------------------------------
print("C) 200 rows around both window edges: new answer == old answer")
# ---------------------------------------------------------------------------
bulk = []
for i in range(196):
    minutes = i + 0.5
    tags = ["noise"]
    if i % 3 == 0:
        tags += ["action_performed", "action_performed:here"]
    if i % 4 == 0:
        tags += ["action_witnessed", WIT]
    bulk.append(entry(minutes, tags, f"Ada_Lu {TEXT} — take {i}"))
# Four hand-placed edge rows, 5 seconds either side of the two cutoffs.
for mins, label in ((2 - 5 / 60.0, "just inside 2 min"),
                    (2 + 5 / 60.0, "just outside 2 min"),
                    (30 - 5 / 60.0, "just inside 30 min"),
                    (30 + 5 / 60.0, "just outside 30 min")):
    bulk.append(entry(mins, ["action_performed", "action_performed:location",
                             "action_witnessed", WIT],
                      f"Ada_Lu {TEXT} — edge {label}"))
seed(ACTOR, bulk)
seed(RECIPIENT, bulk)
check("C0 row count", len(memory_model.load_memories(ACTOR)), 200)

for scope in ("here", "location"):
    check(f"C sender scope={scope} matches the old filter",
          act_engine._sender_on_cooldown(ACTOR, scope),
          ORACLE_sender(ACTOR, scope))
for text in (TEXT, "take 8", "nothing like this"):
    check(f"C recipient text={text!r} matches the old filter",
          act_engine._recipient_recently_perceived(RECIPIENT, ACTOR, text),
          ORACLE_recipient(RECIPIENT, ACTOR, text))

# ---------------------------------------------------------------------------
print("D) the full-table read is gone")
# ---------------------------------------------------------------------------
_orig_load = memory_model.load_memories


def _raiser(name):
    raise AssertionError("load_memories must not be called any more")


memory_model.load_memories = _raiser
try:
    check("D1 sender check works without load_memories",
          act_engine._sender_on_cooldown(ACTOR, "location"), True)
    check("D2 recipient check works without load_memories",
          act_engine._recipient_recently_perceived(RECIPIENT, ACTOR, "take 8"),
          True)
finally:
    memory_model.load_memories = _orig_load

print()
print(f"(throwaway storage: {STORAGE})")
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
