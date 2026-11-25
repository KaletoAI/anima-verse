#!/usr/bin/env python3
"""Smoke: a narrated action right after a respond turn started folds into it;
a spoken line never does. Plus the long-wait line of the respond queue.

Usage:  ./.venv/bin/python scripts/smoke_respond_fold.py

Throwaway storage (paths.init on a temp dir BEFORE any world-DB import), no
server, no LLM: the respond turn itself (_run_respond_turn) is a stub that
sleeps 0.5 s, eligibility, the pool lookup and the lane check are stubbed.

Background (log 2026-11-25): the player takes off two pieces one second
apart. Each piece is announced (perception.announce_action) and dispatched
WITHOUT an utterance id, as an opportunity for the one chime — Kira. The
first bump starts Kira's answer; the second used to queue a second answer
(and a second tool step) behind it. A spoken line is always dispatched with
the id of its recorded utterance (/play/say, the AI cascade, npc lines).

Hand-derived expectations (_RESPOND_MERGE_SECONDS = 5):
[1] Through the real dispatcher: bump 1 (Kai, narrated, opportunity) starts
    a turn; bump 2 (Kai, narrated, opportunity) 0.1 s after the start ->
    folded: bump_respond returns True, the queue stays [], and the turn ran
    ONCE in total. After the turn, _respond_started is empty again.
[2] Direct, with a turn of Kira answering Kai started 1 s ago (state set by
    hand as the dispatcher sets it), each of these is QUEUED (queue == ["Kira"]):
    (a) a spoken chime: utterance_id 7;  (b) obligatory;  (c) on_demand;
    (d) another speaker (Mara);  (e) the turn started 6 s ago (> 5);
    (f) no turn running for Kira.
    And (g) the narrated opportunity of Kai -> folded (queue == []).
[3] Long wait: an entry queued 11 s ago whose last wait reason was "no_lane"
    starts -> one INFO line "respond lane: Kira starts after 11.0s in the queue
    (last wait reason: no_lane)" (seconds rounded to one decimal; 11 > 10).
    An entry queued 2 s ago -> no such line.
"""
import asyncio
import logging
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = Path(tempfile.mkdtemp(prefix="respond-fold-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(TMP / "rig.fbx")

from app.core import paths  # noqa: E402
paths.init(TMP / "world")
from app.core import config, db  # noqa: E402
config.load(paths.get_config_path())
db.init_schema()

from app.core import agent_loop as al  # noqa: E402
from app.core.timeutils import utc_now  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402

for _name in ("Kira", "Kai", "Mara"):
    save_character_profile(_name, {"character_name": _name, "template": "human-roleplay"},
                           create_new=True)

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


COMMON = [patch.object(al, "_is_respond_eligible", return_value=True),
          patch.object(al, "_respond_pool_of", return_value="pool"),
          patch.object(al, "_chat_llm_available", return_value=True),
          patch.object(al, "_is_paused", return_value=False),
          patch.object(al, "_BOOT_GRACE_SECONDS", 0),
          patch.object(al.AgentLoop, "_respond_lane_free", return_value=True)]
for p in COMMON:
    p.start()

RUNS = []


async def _turn(self, name, respond):
    RUNS.append((name, respond.get("content")))
    await asyncio.sleep(0.5)
    return {"preview": "", "tools": [], "intents": []}


async def dispatcher_case():
    loop = al.AgentLoop()
    with patch.object(al.AgentLoop, "_run_respond_turn", _turn):
        task = asyncio.create_task(loop._respond_dispatcher())
        loop.bump_respond("Kira", speaker="Kai", content="Kai takes off the jacket.",
                          obligatory=False)
        for _ in range(100):
            await asyncio.sleep(0.02)
            if "Kira" in loop._respond_active:
                break
        await asyncio.sleep(0.1)
        folded = loop.bump_respond("Kira", speaker="Kai", content="Kai takes off the scarf.",
                                   obligatory=False)
        queue_after = list(loop._respond_queue)
        for _ in range(100):
            await asyncio.sleep(0.05)
            if not loop._respond_active and not loop._respond_queue:
                break
        await asyncio.sleep(0.6)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    return folded, queue_after, loop


print("[1] a narrated action right after the start folds into the running turn")
folded, queue_after, loop = asyncio.run(dispatcher_case())
check("[1] bump 2 reports success", folded, True)
check("[1] nothing queued behind the running turn", queue_after, [])
check("[1] one turn in total", RUNS, [("Kira", "Kai takes off the jacket.")])
check("[1] the start record is gone after the turn", loop._respond_started, {})


def running_loop(age_s=1.0, speaker="Kai", active=True):
    loop = al.AgentLoop()
    if active:
        loop._respond_active["Kira"] = object()
    loop._respond_started["Kira"] = (speaker, utc_now() - timedelta(seconds=age_s))
    return loop


print("[2] what must never fold")
cases = {
    "(a) spoken chime (utterance id)": dict(kw=dict(obligatory=False, utterance_id=7)),
    "(b) obligatory": dict(kw=dict(obligatory=True)),
    "(c) on demand": dict(kw=dict(obligatory=False, on_demand=True)),
    "(d) another speaker": dict(kw=dict(obligatory=False), speaker="Mara"),
    "(e) the turn started 6 s ago": dict(kw=dict(obligatory=False), age=6.0),
    "(f) no turn running": dict(kw=dict(obligatory=False), active=False),
}
for label, case in cases.items():
    loop = running_loop(age_s=case.get("age", 1.0), active=case.get("active", True))
    loop.bump_respond("Kira", speaker=case.get("speaker", "Kai"), content="x", **case["kw"])
    check(f"[2] {label} is queued", loop._respond_queue, ["Kira"])
loop = running_loop()
loop.bump_respond("Kira", speaker="Kai", content="x", obligatory=False)
check("[2] (g) the narrated opportunity folds", loop._respond_queue, [])

print("[3] a long wait in the queue is logged with its reason")
lines = []


class _Grab(logging.Handler):
    def emit(self, record):
        lines.append(record.getMessage())


handler = _Grab(level=logging.INFO)
logging.getLogger(al.logger.name).addHandler(handler)
for age, expected in ((11.0, 1), (2.0, 0)):
    lines.clear()
    loop = al.AgentLoop()
    loop.bump_respond("Kira", speaker="Kai", content="x", obligatory=True)
    loop._respond_queued_at["Kira"] = utc_now() - timedelta(seconds=age)
    loop._respond_wait_reason["Kira"] = "no_lane"
    payload = loop._respond_to["Kira"]
    with patch.object(al.AgentLoop, "_hand_over_respond_reservation", return_value=None), \
            patch.object(al.AgentLoop, "_sync_respond_reservations", return_value=None):
        got = loop._pop_next_respond(False, verdicts={"Kira": {
            "eligible": True, "payload": payload, "pool": "pool", "room": None}})
    waits = [m for m in lines if m.startswith("respond lane: Kira starts after")]
    check(f"[3] popped after {age}s", got[0] if got else None, "Kira")
    check(f"[3] {age}s: long-wait lines", len(waits), expected)
    if expected:
        check("[3] the line names the reason", waits[0].endswith("(last wait reason: no_lane)"), True)
        check("[3] the line names the wait", waits[0].split("after ")[1].split("s")[0], "11.0")

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
print("ALL CHECKS PASSED")
