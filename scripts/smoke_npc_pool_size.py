"""Smoke: the recycling pool has its OWN size (spec-npc-heimat-zeitfenster § E1).

The pool used to be the living cap in disguise — ``max_pool_size()`` returned
``npc_spawn.max_alive()``, so a world that keeps 10 NPCs alive could keep only
10 sheets in stock. The two numbers answer different questions: the living cap
is "how crowded is the world", the pool size is "how much finished work do I
keep for re-use". This run proves they are separate.

Hand-derived expectations:

  [1] With NO ``npc`` section in the config at all (a fresh throwaway world is
      loaded from a config.json that does not exist, so ``config.get`` finds
      nothing), ``max_pool_size()`` is the schema default 50 and
      ``max_alive()`` is its own schema default 10. 50 != 10 is the whole
      point of the change: before E1 both answers were 10.

  [2] ``max_pool_size=2`` with ``max_alive=10``: three temporary NPCs are
      pooled one after the other. ``pool_npc`` enforces the cap on every way
      in, so the pool holds 1, then 2, then — on the third — 2 again, with the
      LONGEST-pooled sheet deleted for good. The FIFO order is
      ``list_pooled_characters()`` (``ORDER BY updated_at ASC, name ASC``);
      the three names are chosen in alphabetical order so the tiebreak inside
      one clock second gives the same order as the pooling did. So after the
      third pooling: pool == [demo_pool_b, demo_pool_c] and demo_pool_a is
      gone from the world (``delete_character`` swept the row). "Gone" is
      asked at the ROSTER, not at ``get_character_profile`` — that one answers
      an empty skeleton dict for a name it does not know, so it can never
      prove a deletion.

  [3] The living cap is untouched by all of this: ``max_alive()`` still
      answers 10 and ``cap_reached()`` stays False — the three NPCs are in
      the pool, so 0 of 10 seats are taken. A pool of 2 does not shrink the
      world to 2 living NPCs.

Usage:  ./.venv/bin/python scripts/smoke_npc_pool_size.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="npcpool-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="npcpool-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import npc_spawn  # noqa: E402
from app.core.npc_pool import max_pool_size, pool_npc  # noqa: E402
from app.core.task_queue import get_task_queue  # noqa: E402
from app.models.character import (list_available_characters,  # noqa: E402
                                  list_pooled_characters,
                                  save_character_profile)

# No worker threads in a smoke — nothing here submits a task, but the pool
# would auto-start on the first one.
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


def set_npc_config(**values) -> None:
    cfg = config.get_all()
    cfg.setdefault("npc", {}).update(values)
    config.save(cfg, STORAGE / "config.json")


def make_npc(name: str) -> str:
    """A living temporary NPC, the way the apply path leaves one."""
    save_character_profile(name, {
        "character_name": name, "template": "npc-temporary",
        "character_personality": "Dry, economical with words.",
        "standing_task": "tends the bar",
        "outfit_description": "grey linen apron",
        "expires_at": "",
    }, create_new=True)
    return name


# ---------------------------------------------------------------------------
print("[1] Without any config the pool has its own default")
check("no npc section in this world", config.get("npc.max_pool_size", None), None)
check("the pool default is 50", max_pool_size(), 50)
check("the living cap keeps its own default 10", npc_spawn.max_alive(), 10)

# ---------------------------------------------------------------------------
print("\n[2] A pool of 2 drops the longest-pooled sheet")
set_npc_config(max_pool_size=2, max_alive=10)
check("the configured pool size is read", max_pool_size(), 2)

A, B, C = (make_npc("demo_pool_a"), make_npc("demo_pool_b"),
           make_npc("demo_pool_c"))

check("first in", (pool_npc(A, reason="smoke"), list_pooled_characters()),
      (True, [A]))
check("second in", (pool_npc(B, reason="smoke"), list_pooled_characters()),
      (True, [A, B]))
check("third in, oldest out",
      (pool_npc(C, reason="smoke"), list_pooled_characters()), (True, [B, C]))
check("the dropped sheet is gone for good, the other two are still there",
      sorted(list_available_characters(include_pooled=True)), [B, C])

# ---------------------------------------------------------------------------
print("\n[3] The living cap is unaffected")
check("max_alive is still 10", npc_spawn.max_alive(), 10)
check("nothing living, so the cap is not reached", npc_spawn.cap_reached(), False)
check("…and the count agrees", npc_spawn.alive_npc_count(), 0)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
