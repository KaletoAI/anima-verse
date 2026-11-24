#!/usr/bin/env python3
"""Smoke: the AgentLoop reads storage in its own pool, never on the event loop.

Usage:  /path/to/.venv/bin/python scripts/smoke_agent_loop_off_loop.py

Throwaway storage and world DB, initialised before any world-DB module is
imported. No server, no LLM, no HTTP: the LLM boundary (routing, the queue
registration, the streaming agent, post-processing, run_chat_turn) is stubbed.
Every scenario runs on an event loop registered with
``loop_guard.register_server_loop()`` in strict mode, and every one ends with
``loop_guard.violations == []`` — many predicates swallow exceptions, so "no
exception" alone would prove nothing.

Seed: location "Smoke Inn", rooms "hall" and "attic".
  Kira   human-roleplay, awake, in hall                     -> due
  Lena   human-roleplay, sleeping (set_is_sleeping), attic  -> not eligible
  Mara   human-roleplay, the active character of user "demo", hall -> avatar
  Ben    human-roleplay, awake, attic — created only after [1]

Hand-derived expectations:

[1] One pick round from an EMPTY round. The refill reads every character:
    eligible are only Kira (Lena sleeps, Mara is player-controlled), each
    eligible character has importance 1 x factor 1.0 = one ticket, so the
    round is ["Kira"]. The pick returns "Kira" and spends that ticket:
    _tickets == []. violations == [].
[2] A bump that arrives WHILE the verdicts are read: _tickets = ["Kira"]; the
    eligibility read of Kira (in the pool thread) bumps Ben. Ben has no
    verdict in this pick, so he counts as not due and stays queued:
    pick 1 == "Kira", _bump_queue == ["Ben"]. Pick 2 reads Ben's verdict
    (eligible) and returns "Ben", _bump_queue == []. violations == [].
[3] A respond turn that STARTS while the verdicts are read: _tickets =
    ["Kira"]; Kira's eligibility read puts Kira into _respond_active through
    the loop (call_soon_threadsafe, as the dispatcher would). Kira's verdict
    says eligible, but the respond check runs on the loop AFTER the read, so
    Kira is not due; her ticket is spent, the round refills with Kira and Ben
    (one ticket each), Kira is still active -> the pick is "Ben", never
    "Kira". violations == [].
[4] Teeth: scenario [1] again with the loop's pool hop replaced by an inline
    call (_off_loop runs the function on the loop thread). The very first
    read (the pause gate / the eligibility read) reaches the world DB on the
    loop: violations >= 1. A pick that stayed on the loop is caught.
[5] One full thought turn for Kira (_run_turn), LLM stubbed to answer
    "Kira hums quietly while thinking about the evening." (> 10 characters):
    outcome "ok", the stub stream ran once, the thought journal holds one
    entry for Kira, game_ts is filled in. violations == [].
[6] One full respond turn through the real dispatcher: Mara (avatar) says
    "Hello Kira" to Kira -> bump_respond (called from a thread, as tools do)
    queues Kira; the dispatcher starts the worker; run_chat_turn is stubbed
    to publish "Hello Mara." through publish_reply. Outcome "respond", one
    run_chat_turn call, _respond_queue == [] and _respond_active == {}
    afterwards; the cascade asks the others in earshot — only Mara, an
    avatar, so nobody is bumped. violations == [].
[5b] [6b] Teeth for the turns: [5] and [6] again with the agent loop's pool
    hop inline. The thought turn's first read (the active-conversation check
    reads Kira's place) and the respond tick's first read (the pause gate)
    then reach the DB on the loop: violations >= 1 each.

What this does NOT prove: the reads inside thoughts.run_thought_turn go
through asyncio.to_thread, not the agent loop's pool, so [5b] has no teeth
for them — [5] only shows that they stay off the loop today.
"""
import asyncio
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="agent-loop-off-loop-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="agent-loop-off-loop-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import agent_loop as al  # noqa: E402
from app.core import loop_guard  # noqa: E402
from app.core.users import create_user, update_user  # noqa: E402
from app.models import world  # noqa: E402
from app.models.character import (save_character_current_location,  # noqa: E402
                                  save_character_current_room,
                                  save_character_profile, set_is_sleeping)

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


def clean(label):
    """Every strict scenario ends here: nothing reached the DB on the loop."""
    check(f"{label}: no world-DB access on the loop", list(loop_guard.violations), [])
    loop_guard.clear_violations()


LOC_ID = world.add_location(
    "Smoke Inn", "Wood and lamplight.",
    rooms=[{"id": "hall", "name": "Hall", "description": "A long table."},
           {"id": "attic", "name": "Attic", "description": "Dusty beams."}])["id"]


def make(name, room):
    save_character_profile(name, {"character_name": name,
                                  "template": "human-roleplay"}, create_new=True)
    save_character_current_location(name, LOC_ID)
    save_character_current_room(name, room)


make("Kira", "hall")
make("Lena", "attic")
set_is_sleeping("Lena", True)
make("Mara", "hall")
_uid = create_user("demo", "smoke-password", allowed_characters=["Mara"])
update_user(_uid, settings={"active_character": "Mara"})
al._ticket_credit.clear()


def strict_on():
    loop_guard.register_server_loop()
    loop_guard.strict(True)
    loop_guard.clear_violations()


def strict_off():
    loop_guard.strict(False)
    loop_guard.unregister()


# ── [1] [2] [3] [4] the pick ────────────────────────────────────────────────
async def picks():
    strict_on()
    try:
        print("[1] one pick round: sleeper, avatar and a due character")
        loop = al.AgentLoop()
        picked = await loop._pick_next_agent_async()
        check("[1] the due character is picked", picked, "Kira")
        check("[1] its only ticket is spent", loop._tickets, [])
        clean("[1]")

        strict_off()
        make("Ben", "attic")
        strict_on()

        print("[2] a bump arriving during the verdict read is kept")
        loop = al.AgentLoop()
        loop._tickets = ["Kira"]
        real = al._is_agent_eligible
        fired = []

        def bumping(name):
            if name == "Kira" and not fired:
                fired.append(threading.get_ident())
                loop.bump("Ben")          # a worker thread bumps mid-read
            return real(name)

        with patch.object(al, "_is_agent_eligible", side_effect=bumping):
            first = await loop._pick_next_agent_async()
            queued = list(loop._bump_queue)
            second = await loop._pick_next_agent_async()
        check("[2] the bump fired inside the pool thread",
              bool(fired) and fired[0] != threading.get_ident(), True)
        check("[2] pick 1 is the due character", first, "Kira")
        check("[2] the late bump is still queued", queued, ["Ben"])
        check("[2] pick 2 is the bumped character", second, "Ben")
        check("[2] the bump queue is empty again", loop._bump_queue, [])
        clean("[2]")

        print("[3] a respond turn starting during the read blocks the pick")
        loop = al.AgentLoop()
        loop._tickets = ["Kira"]
        aloop = asyncio.get_running_loop()
        started = threading.Event()
        marker = object()

        def respond_starts(name):
            if name == "Kira" and not started.is_set():
                def _start():
                    loop._respond_active["Kira"] = marker
                    started.set()
                aloop.call_soon_threadsafe(_start)
                started.wait(5)
            return real(name)

        with patch.object(al, "_is_agent_eligible", side_effect=respond_starts):
            picked = await loop._pick_next_agent_async()
        check("[3] the respond turn started during the read", started.is_set(), True)
        check("[3] the character in a respond turn is not picked", picked, "Ben")
        loop._respond_active.pop("Kira", None)
        clean("[3]")

        print("[4] teeth: the same pick with the read forced onto the loop")

        async def inline(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        loop = al.AgentLoop()
        with patch.object(al, "_off_loop", side_effect=inline):
            try:
                await loop._pick_next_agent_async()
            except loop_guard.LoopBlockingCall:
                pass
        check("[4] a read on the loop is caught (violations >= 1)",
              len(loop_guard.violations) >= 1, True)
        loop_guard.clear_violations()
    finally:
        strict_off()


asyncio.run(picks())


# ── [5] a full thought turn ─────────────────────────────────────────────────
THOUGHT_TEXT = "Kira hums quietly while thinking about the evening."


class _Inst:
    provider_name = "stub"
    model = "stub"
    temperature = 0.7
    repetition_penalty = None

    def create_llm(self, **_kw):
        return object()


class _Queue:
    async def register_chat_active_async(self, *_a, **kw):
        return ("t1", _Inst()) if kw.get("overflow") else "t1"

    def register_chat_done(self, *_a, **_kw):
        pass


STREAMS = []


class _Agent:
    def __init__(self, **_kw):
        self.tool_executor = None
        self.chat_task_id = ""
        self.last_tool_response = ""

    async def stream(self, *_a, **_kw):
        from app.core.streaming import ContentEvent
        STREAMS.append(1)
        yield ContentEvent(content=THOUGHT_TEXT)


async def _inline(fn, *args, **kwargs):
    """The pool hop replaced by a call on the loop thread (the teeth runs)."""
    return fn(*args, **kwargs)


def _hops(inline):
    return (patch.object(al, "_off_loop", side_effect=_inline) if inline
            else patch.object(al, "_BOOT_GRACE_SECONDS", al._BOOT_GRACE_SECONDS))


async def _resolve_async(*_a, **_kw):
    return _Inst()


async def thought_turn_on_loop():
    """[5b] teeth: the same turn with the agent loop's hops inline."""
    from app.core import thoughts
    thoughts.set_thought_runner(thoughts.ThoughtRunner())
    loop = al.AgentLoop()
    strict_on()
    try:
        with _hops(True), \
                patch("app.core.llm_router.resolve_llm_async", side_effect=_resolve_async), \
                patch("app.core.llm_router.resolve_llm", return_value=None), \
                patch("app.core.llm_queue.get_llm_queue", return_value=_Queue()), \
                patch("app.core.streaming.StreamingAgent", _Agent), \
                patch("app.core.chat_engine.post_process_response", return_value={}):
            try:
                await loop._run_turn("Kira")
            except loop_guard.LoopBlockingCall:
                pass
        print("[5b] teeth: the thought turn with its reads forced onto the loop")
        check("[5b] a read on the loop is caught (violations >= 1)",
              len(loop_guard.violations) >= 1, True)
        loop_guard.clear_violations()
    finally:
        strict_off()


async def thought_turn():
    from app.core import thoughts
    thoughts.set_thought_runner(thoughts.ThoughtRunner())
    loop = al.AgentLoop()

    strict_on()
    try:
        with patch("app.core.llm_router.resolve_llm_async", side_effect=_resolve_async), \
                patch("app.core.llm_router.resolve_llm", return_value=None), \
                patch("app.core.llm_queue.get_llm_queue", return_value=_Queue()), \
                patch("app.core.streaming.StreamingAgent", _Agent), \
                patch("app.core.chat_engine.post_process_response", return_value={}):
            await loop._run_turn("Kira")
        print("[5] one full thought turn")
        last = loop._recent[-1]
        check("[5] outcome", last["outcome"], "ok")
        check("[5] the stub stream ran once", len(STREAMS), 1)
        check("[5] game_ts filled in", bool(last["game_ts"]), True)
        clean("[5]")
    finally:
        strict_off()
    from app.models.thought_store import list_thoughts
    check("[5] one journal entry for Kira", len(list_thoughts("Kira", limit=10)), 1)


asyncio.run(thought_turn())
asyncio.run(thought_turn_on_loop())


# ── [6] a full respond turn through the dispatcher ──────────────────────────
CALLS = []


def _chat_turn(_owner, name, speaker, content, *_a, publish_reply=None, **_kw):
    CALLS.append((name, speaker, content))
    text = "Hello Mara."
    if publish_reply is not None:
        publish_reply(text)
    return text


async def respond_turn(inline=False):
    loop = al.AgentLoop()
    CALLS.clear()
    strict_on()
    try:
        with _hops(inline), patch.object(al, "_BOOT_GRACE_SECONDS", 0), \
                patch.object(al, "_chat_llm_available", return_value=True), \
                patch("app.core.llm_router.resolve_llm", return_value=None), \
                patch("app.core.chat_engine.run_chat_turn", side_effect=_chat_turn):
            queued = await asyncio.to_thread(
                loop.bump_respond, "Kira", speaker="Mara", content="Hello Kira")
            task = asyncio.create_task(loop._respond_dispatcher())
            for _ in range(100):
                await asyncio.sleep(0.05)
                if loop._recent and not loop._respond_active and not loop._respond_queue:
                    break
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if inline:
            print("[6b] teeth: the respond turn with its reads forced onto the loop")
            check("[6b] a read on the loop is caught (violations >= 1)",
                  len(loop_guard.violations) >= 1, True)
            loop_guard.clear_violations()
            return
        print("[6] one full respond turn")
        check("[6] bump_respond queued Kira", queued, True)
        check("[6] run_chat_turn ran once for Kira", CALLS, [("Kira", "Mara", "Hello Kira")])
        check("[6] outcome", loop._recent[-1]["outcome"] if loop._recent else None, "respond")
        check("[6] queue drained", (loop._respond_queue, dict(loop._respond_active)), ([], {}))
        clean("[6]")
    finally:
        strict_off()


asyncio.run(respond_turn())
asyncio.run(respond_turn(inline=True))

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
print("ALL CHECKS PASSED")
