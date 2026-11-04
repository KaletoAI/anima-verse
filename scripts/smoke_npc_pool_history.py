"""Smoke: a pooled temporary NPC comes back as a stranger — its OWN history goes.

Before 2026-11-05 ``pool_npc`` cut only the conversation rows (chat, own
utterances, own perceptions). The NPC's own daily/weekly summaries and its
explored map stayed on the sheet, so a recycled NPC carried last week's
summary straight back into its prompt. Found live: a pooled tavern guest still
held one weekly summary and 128 explored cells after the world's fresh start.

Hand-derived expectations (throwaway world, one temporary NPC ``demo_pool_n``
and one ordinary character ``demo``):

  [1] Seeded history of ``demo_pool_n``: 2 own summaries (one daily, one
      weekly), 3 explored cells, 1 chat row with ``demo``, 1 own utterance.
      Plus ``demo``'s own 2 explored cells, which are NOT the NPC's history
      and must survive.
  [2] ``pool_npc`` → True, and afterwards: own summaries 0, own explored
      cells 0, chat 0, own utterances 0. ``demo``'s explored cells are still
      2 (the sweep is by ``character_id``, not a LIKE).
  [3] The boot sweep ``forget_pooled_history`` on a sheet pooled the OLD way
      (history written back AFTER pooling, which is exactly the state an
      old pool left behind): it reports ``{demo_pool_n: {summaries: 1,
      explored_cells: 4}}`` and leaves 0 / 0. A second run reports ``{}`` —
      idempotent, so running it on every start is safe.
  [4] A LIVING temporary NPC is not touched by the boot sweep: ``demo_live``
      keeps its 1 summary and 1 explored cell.

Usage:  ./.venv/bin/python scripts/smoke_npc_pool_history.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="npcpool-history-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="npcpool-history-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core.npc_pool import forget_pooled_history, pool_npc  # noqa: E402
from app.core.task_queue import get_task_queue  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402

get_task_queue()._started = True

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def make_npc(name: str) -> str:
    save_character_profile(name, {
        "character_name": name, "template": "npc-temporary",
        "character_personality": "Dry, economical with words.",
        "standing_task": "tends the bar", "expires_at": "",
    }, create_new=True)
    return name


def count(sql, *args):
    return db.get_connection().execute(sql, args).fetchone()[0]


def own_summaries(name):
    return count("SELECT COUNT(*) FROM summaries WHERE character_name=?", name)


def own_cells(name):
    return count("SELECT COUNT(*) FROM explored_cells WHERE character_id=?", name)


NPC = make_npc("demo_pool_n")
LIVE = make_npc("demo_live")
save_character_profile("demo", {"character_name": "demo", "height": 170},
                       create_new=True)

print("[1] Seed the NPC's own history and the rows that are not its own")
with db.transaction() as c:
    c.execute("INSERT INTO summaries (character_name, kind, date_key, partner, content) "
              "VALUES (?,?,?,?,?)", (NPC, "daily", "Y0001-D001", "demo", "A day at the bar."))
    c.execute("INSERT INTO summaries (character_name, kind, date_key, partner, content) "
              "VALUES (?,?,?,?,?)", (NPC, "weekly", "Y0001-W001", "", "A week at the bar."))
    for cx in range(3):
        c.execute("INSERT INTO explored_cells (character_id, cx, cz) VALUES (?,?,?)", (NPC, cx, 0))
    for cx in range(2):
        c.execute("INSERT INTO explored_cells (character_id, cx, cz) VALUES (?,?,?)", ("demo", cx, 0))
    c.execute("INSERT INTO chat_messages (character_name, partner, ts, role, content) "
              "VALUES (?,?,?,?,?)", (NPC, "demo", "2026-01-01T10:00:00", "user", "hi"))
    c.execute("INSERT INTO utterances (ts, speaker, volume, content) VALUES (?,?,?,?)",
              ("2026-01-01T10:00:00", NPC, "normal", "Another round?"))
check("own summaries seeded", own_summaries(NPC), 2)
check("own explored cells seeded", own_cells(NPC), 3)

print("\n[2] pool_npc cuts the own history")
check("pooled", pool_npc(NPC, reason="smoke"), True)
check("own summaries gone", own_summaries(NPC), 0)
check("own explored cells gone", own_cells(NPC), 0)
check("chat gone", count("SELECT COUNT(*) FROM chat_messages WHERE character_name=? "
                         "OR partner=?", NPC, NPC), 0)
check("own utterances gone", count("SELECT COUNT(*) FROM utterances WHERE speaker=?", NPC), 0)
check("demo's own explored cells untouched", own_cells("demo"), 2)

print("\n[3] The boot sweep cleans a sheet the OLD pool left behind")
with db.transaction() as c:
    c.execute("INSERT INTO summaries (character_name, kind, date_key, partner, content) "
              "VALUES (?,?,?,?,?)", (NPC, "weekly", "Y0001-W002", "", "Left over."))
    for cx in range(4):
        c.execute("INSERT INTO explored_cells (character_id, cx, cz) VALUES (?,?,?)", (NPC, cx, 9))
    c.execute("INSERT INTO summaries (character_name, kind, date_key, partner, content) "
              "VALUES (?,?,?,?,?)", (LIVE, "daily", "Y0001-D001", "", "Alive and well."))
    c.execute("INSERT INTO explored_cells (character_id, cx, cz) VALUES (?,?,?)", (LIVE, 0, 0))
check("first sweep reports exactly the leftovers", forget_pooled_history(),
      {NPC: {"summaries": 1, "explored_cells": 4}})
check("own summaries gone", own_summaries(NPC), 0)
check("own explored cells gone", own_cells(NPC), 0)
check("second sweep finds nothing (idempotent)", forget_pooled_history(), {})

print("\n[4] A living temporary NPC is not swept")
check("living NPC keeps its summary", own_summaries(LIVE), 1)
check("living NPC keeps its explored cell", own_cells(LIVE), 1)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
import shutil  # noqa: E402
for d in (STORAGE, Path(os.environ["ANIMATION_CLIPS_DIR"])):
    shutil.rmtree(d, ignore_errors=True)
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
