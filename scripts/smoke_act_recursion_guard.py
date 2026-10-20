#!/usr/bin/env python3
"""Smoke check: an act cannot trigger another act of the same actor.

The outage (trace 770c955c01, 2026-10-20): a thought fired Act; the
storyteller narrated it and its tool LLM handed the same action straight
back to Act (``act`` was enabled in the storyteller's skill list). The
nested storyteller waited for the one Infermatic lane its outer turn still
held — stalled 660 s until the stale-chat cleanup, then the same again,
44 storyteller calls in 2h20 for one cat tapping a fridge.

``perform_act`` now admits one running action per actor. The pipeline body
(``_perform_act``) is replaced by a fake, so no LLM, DB or server is needed.
The fake re-enters ``perform_act`` exactly the way the Act verb does
(``plugins/act/skill.py``: a pool thread running ``asyncio.run``), which is
the path a lock bound to one event loop would miss.

Hand-derived expectations:

  [1] outer act of "Spoty", whose narration fires a nested act of "Spoty"
      → the nested call returns busy=True, the pipeline body ran ONCE
        (the outer one), the outer result is the fake's normal result.
  [2] inside that same outer act, an act of ANOTHER actor ("Kira")
      → not refused: the guard is per actor, the body ran for Kira too.
  [3] after the outer act returned → "Spoty" may act again (body runs).
  [4] the body raises → the actor is released anyway (a following act
      runs instead of being refused forever).

Usage:
    ./.venv/bin/python scripts/smoke_act_recursion_guard.py

Exit code 0 = pass.
"""
import asyncio
import concurrent.futures
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import act_engine  # noqa: E402

FAILS = []
calls = []


def check(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def act_like_the_verb(actor):
    """Drives perform_act the way ActSkill.execute does from inside a
    running loop: a fresh event loop in a pool thread."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run,
                           act_engine.perform_act(actor, "x", "here")).result()


nested = {}


async def fake_body(actor, text, scope):
    calls.append(actor)
    if text == "outer":
        nested["same"] = act_like_the_verb(actor)
        nested["other"] = act_like_the_verb("Kira")
    if text == "boom":
        raise RuntimeError("pipeline failed")
    return {"narration": f"{actor} acts", "resolved": False,
            "event_id": None, "tools_fired": [], "summary": "ok"}


act_engine._perform_act = fake_body

# [1] + [2]
outer = asyncio.run(act_engine.perform_act("Spoty", "outer", "here"))
check("[1] nested act of the same actor is refused",
      nested["same"].get("busy") is True and nested["same"]["narration"] == "")
check("[1] outer act completes normally",
      outer.get("summary") == "ok" and not outer.get("busy"))
check("[2] act of another actor inside it runs",
      nested["other"].get("summary") == "ok")
check("[1][2] body ran for Spoty once and Kira once",
      calls == ["Spoty", "Kira"])

# [3]
calls.clear()
again = asyncio.run(act_engine.perform_act("Spoty", "plain", "here"))
check("[3] the actor may act again afterwards",
      again.get("summary") == "ok" and calls == ["Spoty"])

# [4]
try:
    asyncio.run(act_engine.perform_act("Spoty", "boom", "here"))
except RuntimeError:
    pass
calls.clear()
after = asyncio.run(act_engine.perform_act("Spoty", "plain", "here"))
check("[4] a failed act releases the actor",
      after.get("summary") == "ok" and calls == ["Spoty"])

print(f"\n{len(FAILS)} failure(s)")
sys.exit(1 if FAILS else 0)
