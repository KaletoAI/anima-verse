#!/usr/bin/env python3
"""Smoke: an NPC's answer to a pair invitation (``InteractWith`` called back).

Usage:  ./.venv/bin/python scripts/smoke_interact_answer.py

Background — the bug this pins down: when an NPC accepted by calling the verb
back and ``interaction_engine.resolve_invite`` returned
``{"status": "started", "interaction": {...}}``, the reply read
``interaction["duration_s"]``. The dict ``start_interaction`` stores carries
``clip_duration_s`` and ``loop`` — no ``duration_s`` — so a KeyError fell into
the generic handler and the NPC was told "Error in InteractWith: 'duration_s'"
although the pair had already started.

Everything the verb reaches is stubbed at module level (character list, pose
catalog, the interaction engine's invite functions), so no LLM, no world data.
Storage is a throwaway dir initialised before any app import.

EXPECTATIONS, DERIVED BY HAND
(Kira answers Halvard's open "shaking hands" invitation i1.)
1  started, loop False, clip_duration_s 2.533 -> "%.0f" of 2.533 is "3":
   reply contains "for about 3 seconds", not "Error".
2  started, loop True -> the clip repeats until someone stops it:
   reply contains "until one of them stops", not "Error".
3  answer "no" -> resolve_invite called with ("i1", False); reply is the
   refusal sentence "Kira turns Halvard down — no shaking hands. ...",
   so it contains "turns" and "down".
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP = Path(tempfile.mkdtemp(prefix="smoke_interact_answer_"))
from app.core import paths  # noqa: E402
paths.init(str(_TMP))

import app.models.character as C  # noqa: E402
import app.core.pose_catalog as PC  # noqa: E402
from app.core import interaction_engine as IE  # noqa: E402
from app.plugins.context import PluginContext  # noqa: E402
from plugins.interact.skill import InteractSkill  # noqa: E402

ACTOR, PARTNER, KEY = "Kira", "Halvard", "shaking hands"

C.list_available_characters = lambda *a, **k: [ACTOR, PARTNER]
PC.resolve_to_catalog = lambda *a, **k: (KEY, "exact")
IE.partner_poses = lambda *a, **k: [(KEY, "handshake")]
IE.find_pending_invite = lambda *a, **k: {
    "invite_id": "i1", "actor": PARTNER, "partner": ACTOR, "pose_key": KEY}

RESOLVE_CALLS = []
RESOLVE_RESULT = {}


def _resolve(invite_id, accept, *a, **k):
    RESOLVE_CALLS.append((invite_id, accept))
    return RESOLVE_RESULT


IE.resolve_invite = _resolve

SKILL = InteractSkill({}, PluginContext("interact"))

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + ("" if ok else f" — got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(name)


def answer(**extra):
    RESOLVE_CALLS.clear()
    return SKILL.execute(json.dumps({
        "agent_name": ACTOR, "partner": PARTNER, "action": KEY, **extra}))


print("1 started, one-shot clip")
RESOLVE_RESULT = {"status": "started",
                  "interaction": {"clip_duration_s": 2.533, "loop": False}}
r = answer()
print(f"     reply: {r}")
check("resolve_invite(i1, True)", RESOLVE_CALLS, [("i1", True)])
check("contains 'for about 3 seconds'", "for about 3 seconds" in r, True)
check("no 'Error'", "Error" in r, False)

print("2 started, looping clip")
RESOLVE_RESULT = {"status": "started",
                  "interaction": {"clip_duration_s": 2.533, "loop": True}}
r = answer()
print(f"     reply: {r}")
check("contains 'until one of them stops'", "until one of them stops" in r, True)
check("no 'Error'", "Error" in r, False)

print("3 refusal")
RESOLVE_RESULT = {}
r = answer(answer="no")
print(f"     reply: {r}")
check("resolve_invite(i1, False)", RESOLVE_CALLS, [("i1", False)])
check("contains 'turns' and 'down'", ("turns" in r, "down" in r), (True, True))

print()
if FAILS:
    print(f"FAILED: {len(FAILS)} — {', '.join(FAILS)}")
    sys.exit(1)
print("OK")
