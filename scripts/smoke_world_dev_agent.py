#!/usr/bin/env python3
"""Smoke: World Dev free mode — agent loop and run manager.

Usage:  ./.venv/bin/python scripts/smoke_world_dev_agent.py

Plan docs/superpowers/plans/2026-11-22-world-dev-free-mode.md, Task 7 (run
state machine + Review Focus 1-4). A temp world (paths.init BEFORE any
world-DB import); no server, no real LLM: `RunManager.llm_factory` returns a
FakeLLM that plays a script of replies, and the LLM-queue registration is
replaced by two counters (every registration must be closed again).

A reply is a string, a ``(text, finish)`` tuple (streams ``text`` and then
yields a terminal ``LLMChunk(content="", finish_reason=finish)``), an Exception
(raised from astream = provider error), or a callable (run inside astream,
returns the string — used for a foreign edit "while the model thinks"). The
tool tag is the project's tag format: <tool name="X">{json}</tool>.

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Fixture: place P "Demo Pond" (description "calm", room Shore).

(a) [create_location "Demo A1", final "Built A1."] -> awaiting_review (turn 1
    ended without a tool call after 1 step), note "Built A1.", world frozen
    (start froze it, was_frozen False), entries(run) = 1 write row.
    subscribe(run, 0) yields at least one "step" and one "status" event;
    every "step" event carries the journal `seq` of its row, so the set of
    step-event seqs equals the set of steps(run) seqs ({1}: the one create
    row) — the Game-Admin panel merges its live rows into the journal list
    by that number (Task 9);
    subscribe(run, 999) (a counter beyond this process's buffer of a few
    events) yields {"ev": 0, "type": "reset"} followed by exactly that list.
    accept -> accepted, world unfrozen (was_frozen False), open_run() None.
(b) world frozen BEFORE start: [create "Demo B1", final] -> accept ->
    accepted and still frozen. Second run [create "Demo B2", final] ->
    discard -> rolled_back, "Demo B2" gone, still frozen.
(c) [bad JSON, world_overview{}, final] -> awaiting_review (one bad body is
    answered "error: body is not a JSON object (JSON error: …" — the
    position and fix hint of case (y2) follow the prefix), the run goes on; the bad
    call is journaled as a "refused" step -> steps(run) has 2 rows; the two
    step events carry seq 1 (refused) and 2 (the read), in that order).
    [bad, bad, bad] -> 3 in a row = hard failure in turn 1 -> rolled_back,
    note names "JSON".
(d) turn 1 [create "Demo D1", final]; turn 2 (message) [create "Demo D2",
    RuntimeError("provider down")] -> hard failure in turn 2: only turn 2 is
    undone -> D1 exists, D2 gone, status awaiting_review, note contains
    "provider down". The history then tells the truth (Run state machine:
    a rolled-back turn's writes are gone): a third message ["Nothing more."]
    -> its LLM call carries no message naming "Demo D2" (neither the call
    nor its result) and one assistant message "[turn 2 was rolled back: ..."
    -> awaiting_review again. discard -> D1 gone too, rolled_back.
    Before the third message: turn_summaries with this manager's outcomes =
    [turn 1 kept 1 write 0 undone; turn 2 rolled_back, reason "LLM error:
    provider down" (the _fail note), 1 write 1 undone]; without outcomes (a
    restart) turn 2 is derived rolled_back from its undone write, reason =
    the run note.
(e) budgets are PER TURN and a cut turn keeps its work. max_steps=3,
    [create E1, E2, E3, E4]: calls 1-3 write E1-E3 (turn steps 1, 2, 3); the
    4th reply asks for create E4, but the check after the call finds 3 >= 3
    -> the turn is CUT, not rolled back: awaiting_review, note starts
    "budget reached (tool calls: 3 of 3 this turn)" and names the follow-up,
    4 LLM calls, E1-E3 exist with 3 write rows none undone, E4 never written,
    world frozen. Follow-up "continue" [create E4, create E5, "E5 done."]:
    turn 2 measures from its own start (3 calls) -> 1, 2, final ->
    awaiting_review "E5 done.", run total steps 5 while max_steps stays 3
    (a cumulative budget would have refused turn 2's first call). Turn 2's
    first LLM call (call 5) carries the assistant line "[turn 1 was cut off:
    budget reached (tool calls..." and never names "Demo E4" (the refused reply
    was not kept). turn_summaries = [turn 1 cut_by_budget, reason = the note,
    3 writes, 0 undone; turn 2 kept, 2 writes]. discard -> E1-E5 gone.
    Real failure + foreign edit: [update_location P description "agent",
    (foreign edit P -> "foreign", then create E6), RuntimeError("provider
    down")] -> LLM error = hard failure in turn 1 -> undo turn 1: E6 removed,
    P's update skipped "changed since" -> rollback_incomplete, P keeps
    "foreign", world unfrozen, open_run() None.
(f) [create "Demo F1", a reply that blocks forever] -> the turn task is
    cancelled (process death); a NEW RunManager's mark_interrupted_on_boot()
    -> interrupted; steps(run) identical before/after (nothing written).
    accept -> accepted, F1 stays, world unfrozen. Second fixture (F2): the
    same, then discard -> rolled_back, F2 gone, world unfrozen.
(g) [create "Demo G1", add_terrain_area water square, final] -> discard ->
    G1 gone, terrain area gone, rolled_back, unfrozen.
(h) [update_location P description "agent2", create "Demo H1", final] ->
    awaiting_review; foreign edit P -> "foreign2"; discard ->
    rollback_incomplete (the update is skipped), H1 gone, P keeps "foreign2",
    unfrozen, open_run() None, and a new run can start.
(i) create_location wrapped to wait on an event: [create "Demo I1", final]
    -> stop() while the tool runs; the tool is awaited to completion (its
    write is journaled: one write row), then the stop flag fails turn 1 ->
    rolled_back, I1 gone, the write row is marked undone.
(j) [final only] -> turn 1 without any tool call -> rolled_back, the note
    names "tool-capable".
(k) [world_overview x6, final]: in the 7th LLM call the history holds 6
    world_overview results; the newest 4 are unshrunk, the 2 older ones read
    "[result world_overview] (shrunk — call again if needed)".
(l) the system prompt renders with every tool signature and manual section;
    read_manual renders each of the 5 sections (text starts "# Manual").
(m) a tool raising a non-refusal exception (world_overview patched to raise
    RuntimeError("boom")): [create "Demo M1", world_overview{}] -> hard
    failure in turn 1 -> rolled_back, note names "world_overview", M1 gone;
    the one failed step event says kind "read" (world_overview is a read
    tool, TOOLS[...].write False).
(n) token budget: max_tokens_total=50. The system prompt alone is far over
    200 characters (= 50 tokens at 4 characters a token), so the check after
    the first call stops turn 1 before its tool runs; turn 1 has no step yet,
    nothing to keep -> a hard failure -> rolled_back, note names "token
    budget" and "before the first tool call", "Demo N1" never written.
(o) RunStateError: on the rolled_back run of (n) accept, discard, message
    and stop each raise RunStateError, and the status stays rolled_back.
(p) restart follow-up: start with max_tokens=1234 -> the run row stores
    max_tokens 1234; [create "Demo P1", "P1 done."] -> awaiting_review;
    a NEW RunManager (no in-memory history) gets message "more" -> its first
    LLM call is rebuilt from the journal: system, user = the task "build
    something", assistant naming create_location and the note, user "more".
    A third RunManager that never saw the run: stop() raises RunStateError
    and subscribe(run, 0) still yields the stored status (awaiting_review).
    The new manager resolved the model ONCE with ("fake-model", "fake",
    1234) — the stored cap, not None. subscribe(run, 1) yields nothing (ev 1
    already seen); subscribe(run, 17) yields reset (ev 0) + the status (ev 1).
(q) Stop while the provider sends nothing: [create "Demo Q1", BLOCK] -> stop
    once the second call is waiting -> the stream is abandoned, turn 1 ->
    rolled_back, Q1 gone, note names the stop.
(r) unclosed tag: ['<tool name="world_overview">{}' (no close), world_overview
    {}, "Looked."] -> the first is refused with 'error: tool call not closed'
    and the run goes on -> awaiting_review, step kinds [refused, read].
(r2) unclosed tag cut off at output limit: [('<tool name="world_overview">'
    '{"x": "aaaa', 'length'), world_overview{}, "Looked."]. Reply length by
    hand: '<tool name="world_overview">' is 12 + 14 + 2 = 28 characters,
    '{"x": "aaaa' is 7 + 4 = 11 characters -> n = 39 characters. Because the
    terminal chunk carries finish_reason='length' and no complete JSON object
    could be decoded, step 0 is refused with CUT_OFF_LINE (starts
    "error: your reply hit the model's output limit after 39 characters" and
    names "one room per call"); awaiting_review, step kinds [refused, read].
(r3) same 39-character incomplete reply WITHOUT finish_reason (plain string)
    -> step 0 still starts with "error: tool call not closed";
    awaiting_review, step kinds [refused, read].
(s) the end-of-turn transition raises (wr.set_status patched to raise once
    for "awaiting_review"): [create "Demo S1", "ok"] -> the run does not stay
    running without a task: interrupted, not busy, note names the failure;
    discard -> rolled_back, S1 gone, unfrozen.
(t) estimate_cost patched to 60 in + 40 out = 100 tokens a call,
    max_tokens_total=150: [create "Demo T1", "T1 done."]. Call 1 -> 100 < 150,
    the tool runs; the top-of-loop check 100 < 150 allows call 2 -> 200 >=
    150, but that reply is final -> awaiting_review, note "T1 done.", T1
    kept (2 calls, 200 tokens).
(y) estimate_cost patched to 100 tokens a call, max_tokens_total=150:
    [create Y1, create Y2]. Call 1 -> 100 < 150, Y1 written; call 2 -> 200
    >= 150 and the reply asks for a tool -> turn 1 cut (it has 1 step):
    awaiting_review, note "budget reached (tokens: 200 of 150 this turn)..."
    (a limit under 1,000 tokens prints raw counts: in thousands both would
    read "0k" — _k(200) = 700 // 1000 = 0, _k(150) = 650 // 1000 = 0),
    Y1 kept, Y2 never written. Follow-up [create Y2, "Y2 done."]: turn 2
    counts from 200 -> call 3: turn 100 (total 300) < 150, Y2 written; call 4:
    turn 200 (total 400), final -> awaiting_review "Y2 done.". Turn-2 usage
    events carry (turn_tokens, total, turn_steps) = (100, 300, 0) after LLM
    call 3, (100, 300, 1) emitted at once when call 3's tool call is counted
    (count_call: one more step, tokens unchanged), (200, 400, 1) after LLM
    call 4 (the final reply, no tool call, no count); turn_usage =
    {turn 2, steps 1, tokens 200}; run total 400.
(u) defaults 200 / 2000000 (DEFAULT_MAX_STEPS / DEFAULT_MAX_TOKENS_TOTAL, plan
    2026-11-25 complete-characters-budget B2); message(max_steps=10,
    max_tokens_total=1000) keeps (200, 2000000) = max of each;
    message(max_steps=250) -> (250, 2000000) — the raise must exceed the
    default 200 to prove raising.
(v) world frozen before; set_was_frozen raises "disk full" right after
    create_run -> start raises it, the newest run is rolled_back with
    "disk full" in its note, no LLM call, the world stays frozen (the
    pre-run state was never recorded, so nothing is restored), no open run;
    a new run then starts.
(w) set_status raises once for "awaiting_review" and the following
    thread-pool get_run (_interrupt's own read) raises once: _interrupt can
    neither mark nor emit. A subscriber waiting beside the turn still ends
    within 2 s; no "interrupted" event, the stored status stays "running";
    a new manager's boot sweep -> interrupted, discard -> rolled_back, W1
    gone, unfrozen.
(x) like (h) with P -> "foreign3", but wr.set_skipped raises during discard:
    the run still closes rollback_incomplete, X1 gone, P keeps "foreign3",
    unfrozen, no open run.
(z) pinned reads through the loop (plan 2026-11-25 Task 10): turn 1
    [read_manual{characters}, read_manual{homes}, "Read."] -> awaiting_review;
    the 3rd LLM call holds two read_manual results, both whole (start
    "[result read_manual] # Manual"), no stub — so _loop passes the parsed
    args (with one key "read_manual" + "null" the homes read would supersede
    the characters read). Turn 2 [read_manual{characters},
    RuntimeError("down")] -> rolled back (awaiting_review); turn 3 ["ok."]:
    its LLM call holds exactly two read_manual results again, both whole,
    none "superseded" (_fail restored the turn-1 copy whose newer copy was
    cut away).
The budget counts MODEL TOOL CALLS (plan 2026-11-25
complete-characters-budget Task 1, its cases (w), (x), (z) — named (w2),
(x2), (z2) here because (w), (x), (z) were taken):
(w2) one call, several rows: max_steps=2, [create_character "Demo Rows"
     (human-roleplay, no outfits: one write row), update_character{Demo
     Rows, patch {soul:character_presence "Text A", age 30}} (two groups:
     restore_soul + restore_character = two write rows, as in
     smoke_world_dev_tools (ae)), world_overview{}]: call 1 -> used 1,
     call 2 -> used 1 < 2 runs -> used 2; the 3rd reply finds 2 >= 2 -> cut,
     note starts "budget reached (tool calls: 2 of 2 this turn)", run.steps
     2, 3 write rows (create + 2 groups). On 8962e4d04 begin counted journal
     rows: after call 2 the counter read 3 (1 + 2 rows), the note said
     "steps: 3 of 2".
(x2) refusals count: ['<tool name="get_character">bad json</tool>',
     '<tool name="no_such_tool">{}</tool>', "done"] -> both calls refused
     (bad body; unknown tool), the final reply ends turn 1 ->
     awaiting_review, run.steps == 2, 2 refused journal rows.
(z2) token note in k: _k(2_000_123) = (2000123 + 500) // 1000 = 2000 ->
     "2,000k"; _k(1_499) = 1999 // 1000 = 1 -> "1k"; _k(1_500) = 2000 //
     1000 = 2 -> "2k"; _k(0) = 500 // 1000 = 0 -> "0k". estimate_cost
     patched to 600 + 400 = 1000 tokens a call, max_tokens_total=1500,
     [create Z1, create Z2, create Z3]: top check 0 < 1500 -> call 1 -> 1000,
     1000 < 1500 -> Z1 written; top check 1000 < 1500 -> call 2 -> 2000, the
     reply asks for a tool and 2000 >= 1500 -> cut (the plan text said "the
     third reply"; by this arithmetic it is the second) -> 2 LLM calls,
     note == "budget reached (tokens: 2k of 2k this turn) — the turn's work
     is kept; send a follow-up to continue" (2000 -> "2k", 1500 -> "2k"),
     Z1 kept, Z2 never written.
(y2) a refused JSON body tells the model how to fix it (plan 2026-11-25
    complete-characters-budget Task 8, C6 — its case (y), named (y2) here
    because (y) was taken): turn 1 [update_character with
    the body {"name": "X", "patch": {"soul:a": "he said "hi""}}, the body
    [1], "done"] -> awaiting_review, two refused rows. Column by hand: the
    prefix {"name": "X", "patch": {"soul:a": "he said " is 1 + 6 ("name")
    + 2 (": ") + 3 ("X") + 2 (", ") + 7 ("patch") + 2 + 1 ({) + 8
    ("soul:a") + 2 + 10 ("he said ") = 44 characters, so the stray h sits
    at 0-based position 44 = column 45; json names it "Expecting ','
    delimiter". Row 1's line == 'error: body is not a JSON object (JSON
    error: Expecting ',' delimiter at line 1 column 45) — inside a string
    write a double quote as \\" and a line break as \\n; split a very long
    text into several calls' — the two-character sequences backslash+quote
    and backslash+n, never a real line break. Row 2 (parses, not an
    object): 'error: body is not a JSON object (got list)'. On 8962e4d04
    both rows read the bare "error: body is not a JSON object".
    The rendered system prompt names check_character (tool list) and the
    step-5 sentence "For a task that asks to fill, complete or check
    existing characters, call `check_character` for each of them".
Last: every LLM-queue registration was closed (active == done).
"""
import asyncio
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="smoke_wd_agent_clips_")

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_agent_"))
paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import world_dev_agent as wa  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import llm_cost  # noqa: E402
from app.core.llm_client import LLMChunk  # noqa: E402
from app.models import terrain  # noqa: E402
from app.models.world import (add_location, get_location_by_id,  # noqa: E402
                              is_world_frozen, list_locations,
                              set_world_frozen, upsert_location)

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


def by_name(name):
    return [loc for loc in list_locations() if loc.get("name") == name]


def call(tool, body):
    return f'<tool name="{tool}">{body}</tool>'


def create(name):
    return ('Next step. ' + call("create_location", '{"data": {"name": "%s", '
            '"rooms": [{"name": "Main"}]}}' % name) + " trailing text is dropped")


BAD = call("world_overview", "{oops")

# ── LLM fakes ────────────────────────────────────────────────────────────
COUNTS = {"active": 0, "done": 0}


async def fake_active(llm_instance):
    COUNTS["active"] += 1
    return f"t{COUNTS['active']}"


def fake_done(task_id):
    if task_id:
        COUNTS["done"] += 1


wa._chat_active = fake_active
wa._chat_done = fake_done


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def astream(self, messages):
        self.calls.append([dict(m) for m in messages])
        reply = self.replies.pop(0) if self.replies else "Done."
        if callable(reply):
            reply = reply()
        if isinstance(reply, BaseException):
            raise reply
        finish = None
        if isinstance(reply, tuple):
            reply, finish = reply
        if reply == "BLOCK":
            await asyncio.Event().wait()
        half = len(reply) // 2
        yield LLMChunk(content=reply[:half])
        yield LLMChunk(content=reply[half:])
        if finish is not None:
            yield LLMChunk(content="", finish_reason=finish)


FACTORY_CALLS = []  # (model, provider, max_tokens) of every resolve


def manager(replies):
    rm = wa.RunManager()
    fake = FakeLLM(replies)

    def factory(model, provider, max_tokens):
        FACTORY_CALLS.append((model, provider, max_tokens))
        return fake, None

    rm.llm_factory = factory
    return rm, fake


def collect(rm, run_id, after=0):
    """A subscriber running beside the turn; its task returns the events."""
    async def run():
        return [e async for e in rm.subscribe(run_id, after)]
    return asyncio.ensure_future(run())


async def settle(rm, run_id, timeout=20.0):
    """Wait until the run is no longer running."""
    for _ in range(int(timeout / 0.02)):
        run = wr.get_run(run_id)
        if run["status"] != "running" and not rm.is_busy(run_id):
            return run
        await asyncio.sleep(0.02)
    raise AssertionError(f"run {run_id} still running")


async def start(rm, **kw):
    return await rm.start("build something", "fake-model", "fake", "u1", **kw)


# ── Fixture ──────────────────────────────────────────────────────────────
pond = add_location("Demo Pond", "calm", rooms=[{"name": "Shore"}])
P = pond["id"]


def set_pond(desc):
    loc = get_location_by_id(P)
    loc["description"] = desc
    upsert_location(loc, sync_world=False)


async def main():
    set_world_frozen(False)

    print("(a) create + final -> awaiting_review -> accept")
    rm, _ = manager([create("Demo A1"), "Built A1."])
    run_id = await start(rm)
    run = await settle(rm, run_id)
    check("(a) awaiting_review", run["status"] == "awaiting_review", run["status"])
    check("(a) note = final reply", run["note"] == "Built A1.", run["note"])
    check("(a) frozen during review", is_world_frozen())
    check("(a) one write row", len(wr.entries(run_id)) == 1, wr.entries(run_id))
    evs = [e async for e in rm.subscribe(run_id, 0)]
    types = {e["type"] for e in evs}
    check("(a) events carry step + status", {"step", "status"} <= types, types)
    ev_seqs = {e.get("seq") for e in evs if e["type"] == "step"}
    row_seqs = {s["seq"] for s in wr.steps(run_id)}
    check("(a) step events carry the journal seq", ev_seqs == row_seqs == {1},
          (ev_seqs, row_seqs))
    stale = [e async for e in rm.subscribe(run_id, 999)]
    check("(a) after beyond the buffer -> reset, then the buffer from its start",
          stale == [{"ev": 0, "type": "reset"}] + evs, stale[:2])
    await rm.accept(run_id)
    check("(a) accepted", wr.get_run(run_id)["status"] == "accepted")
    check("(a) unfrozen after accept", not is_world_frozen())
    check("(a) no open run", wr.open_run() is None)
    check("(a) A1 kept", len(by_name("Demo A1")) == 1)

    print("(b) frozen before -> still frozen after accept and discard")
    set_world_frozen(True)
    rm, _ = manager([create("Demo B1"), "ok"])
    run_id = await start(rm)
    await settle(rm, run_id)
    await rm.accept(run_id)
    check("(b) frozen after accept", is_world_frozen())
    rm, _ = manager([create("Demo B2"), "ok"])
    run_id = await start(rm)
    await settle(rm, run_id)
    await rm.discard(run_id)
    run = wr.get_run(run_id)
    check("(b) rolled_back", run["status"] == "rolled_back", run["status"])
    check("(b) B2 gone", not by_name("Demo B2"))
    check("(b) frozen after discard", is_world_frozen())
    set_world_frozen(False)

    print("(c) malformed JSON")
    rm, _ = manager([BAD, call("world_overview", "{}"), "Looked."])
    run_id = await start(rm)
    run = await settle(rm, run_id)
    check("(c) one bad body does not fail", run["status"] == "awaiting_review",
          (run["status"], run["note"]))
    steps = wr.steps(run_id)
    check("(c) bad call journaled refused + one read", [s["kind"] for s in steps]
          == ["refused", "read"], [(s["kind"], s["line"]) for s in steps])
    check("(c) bad line", steps and steps[0]["line"].startswith(
              "error: body is not a JSON object (JSON error: "),
          steps and steps[0]["line"])
    c_evs = [e async for e in rm.subscribe(run_id, 0) if e["type"] == "step"]
    check("(c) refused + read step events carry their journal seq",
          [(e.get("kind", "read"), e.get("seq")) for e in c_evs]
          == [("refused", 1), ("read", 2)], c_evs)
    await rm.discard(run_id)
    rm, _ = manager([BAD, BAD, BAD, "never"])
    run_id = await start(rm)
    run = await settle(rm, run_id)
    check("(c) 3 bad in a row = hard failure, turn 1 -> rolled_back",
          run["status"] == "rolled_back", (run["status"], run["note"]))
    check("(c) note names JSON", "JSON" in (run["note"] or ""), run["note"])
    check("(c) unfrozen", not is_world_frozen())

    print("(d) turn 2 failure undoes only turn 2")
    rm, fake = manager([create("Demo D1"), "D1 done."])
    run_id = await start(rm)
    await settle(rm, run_id)
    fake.replies += [create("Demo D2"), RuntimeError("provider down")]
    await rm.message(run_id, "one more")
    run = await settle(rm, run_id)
    check("(d) awaiting_review after turn-2 failure", run["status"] == "awaiting_review",
          run["status"])
    check("(d) note names the error", "provider down" in (run["note"] or ""), run["note"])
    check("(d) D1 kept", len(by_name("Demo D1")) == 1)
    check("(d) D2 undone", not by_name("Demo D2"))
    check("(d) still frozen", is_world_frozen())
    run_d = wr.get_run(run_id)
    summ = wa.turn_summaries(run_d, wr.steps(run_id), rm.turn_outcomes(run_id))
    check("(d) turn summaries: turn 1 kept, turn 2 rolled_back with its reason",
          summ == [{"turn": 1, "status": "kept", "reason": "", "writes": 1, "undone": 0},
                   {"turn": 2, "status": "rolled_back", "reason": "LLM error: provider down",
                    "writes": 1, "undone": 1}], summ)
    derived = wa.turn_summaries(run_d, wr.steps(run_id))
    check("(d) derived after a restart (no outcomes): the undone turn is rolled_back, "
          "reason = the run note",
          [(r["status"], r["reason"]) for r in derived]
          == [("kept", ""), ("rolled_back", run_d["note"])], derived)
    fake.replies += ["Nothing more."]
    await rm.message(run_id, "raise the budget, continue")
    run = await settle(rm, run_id)
    last = fake.calls[-1]
    check("(d) turn 3 awaiting_review", run["status"] == "awaiting_review", run["status"])
    check("(d) turn-3 history never names D2",
          not any("Demo D2" in m["content"] for m in last),
          [m["content"][:80] for m in last if "Demo D2" in m["content"]])
    check("(d) turn-3 history carries the rollback note",
          any(m["role"] == "assistant"
              and m["content"].startswith("[turn 2 was rolled back:") for m in last),
          [m["content"][:80] for m in last])
    await rm.discard(run_id)
    check("(d) discard -> rolled_back", wr.get_run(run_id)["status"] == "rolled_back")
    check("(d) D1 gone", not by_name("Demo D1"))
    check("(d) unfrozen", not is_world_frozen())

    print("(e) step budget per turn: the cut turn keeps its work")
    rm, fake = manager([create("Demo E1"), create("Demo E2"), create("Demo E3"),
                        create("Demo E4")])
    run_id = await start(rm, max_steps=3)
    run = await settle(rm, run_id)
    note1 = run["note"] or ""
    check("(e) awaiting_review, not rolled back", run["status"] == "awaiting_review",
          (run["status"], run["note"]))
    check("(e) note: budget reached (tool calls: 3 of 3 this turn)",
          note1.startswith("budget reached (tool calls: 3 of 3 this turn)")
          and "follow-up" in note1, note1)
    check("(e) 4 LLM calls", len(fake.calls) == 4, len(fake.calls))
    check("(e) E1/E2/E3 kept, E4 never written",
          all(len(by_name(n)) == 1 for n in ("Demo E1", "Demo E2", "Demo E3"))
          and not by_name("Demo E4"))
    check("(e) 3 write rows, none undone",
          [bool(s.get("undone_at")) for s in wr.entries(run_id, include_undone=True)]
          == [False] * 3, wr.entries(run_id, include_undone=True))
    check("(e) frozen during review", is_world_frozen())
    fake.replies += [create("Demo E4"), create("Demo E5"), "E5 done."]
    await rm.message(run_id, "continue")
    run = await settle(rm, run_id)
    check("(e) turn 2 gets the full budget again: 2 more writes, final",
          run["status"] == "awaiting_review" and run["note"] == "E5 done.",
          (run["status"], run["note"]))
    check("(e) run total 5 steps > max_steps 3 (the budget is per turn)",
          (run["steps"], run["max_steps"]) == (5, 3), (run["steps"], run["max_steps"]))
    check("(e) E4/E5 written", len(by_name("Demo E4")) == 1 and len(by_name("Demo E5")) == 1)
    first2 = fake.calls[4] if len(fake.calls) > 4 else []
    check("(e) turn 2 history says turn 1 was cut off",
          any(m["role"] == "assistant"
              and m["content"].startswith("[turn 1 was cut off: budget reached (tool calls")
              for m in first2), [m["content"][:80] for m in first2])
    check("(e) the call the budget refused is not in the history",
          not any("Demo E4" in m["content"] for m in first2),
          [m["content"][:80] for m in first2 if "Demo E4" in m["content"]])
    summ = wa.turn_summaries(run, wr.steps(run_id), rm.turn_outcomes(run_id))
    check("(e) turn summaries: cut_by_budget 3 writes, kept 2 writes",
          summ == [{"turn": 1, "status": "cut_by_budget", "reason": note1,
                    "writes": 3, "undone": 0},
                   {"turn": 2, "status": "kept", "reason": "", "writes": 2, "undone": 0}],
          summ)
    await rm.discard(run_id)
    check("(e) discard -> rolled_back, E1-E5 gone",
          wr.get_run(run_id)["status"] == "rolled_back"
          and not any(by_name(f"Demo E{i}") for i in range(1, 6)))
    check("(e) unfrozen", not is_world_frozen())

    def foreign_then_create():
        set_pond("foreign")
        return create("Demo E6")

    rm, _ = manager([call("update_location", '{"id": "%s", "patch": {"description": '
                          '"agent"}}' % P), foreign_then_create,
                     RuntimeError("provider down")])
    run_id = await start(rm)
    run = await settle(rm, run_id)
    check("(e) real failure + foreign edit -> rollback_incomplete",
          run["status"] == "rollback_incomplete", (run["status"], run["note"]))
    check("(e) skipped names changed since",
          any(s.get("reason") == "changed since" for s in run["skipped"]), run["skipped"])
    check("(e) P keeps the foreign edit", get_location_by_id(P)["description"] == "foreign")
    check("(e) E6 removed", not by_name("Demo E6"))
    check("(e) unfrozen", not is_world_frozen())
    check("(e) no open run", wr.open_run() is None)

    print("(f) server restart mid-turn")
    for variant, name in (("accept", "Demo F1"), ("discard", "Demo F2")):
        rm, fk = manager([create(name), "BLOCK"])
        run_id = await start(rm)
        for _ in range(500):
            if len(wr.steps(run_id)) == 1 and len(fk.calls) >= 2:
                break
            await asyncio.sleep(0.02)
        rm._states[run_id].task.cancel()  # what a process shutdown does
        await asyncio.sleep(0.05)
        before = wr.steps(run_id)
        rm2 = wa.RunManager()
        rm2.mark_interrupted_on_boot()
        run = wr.get_run(run_id)
        check(f"(f/{variant}) interrupted", run["status"] == "interrupted", run["status"])
        check(f"(f/{variant}) journal untouched", wr.steps(run_id) == before)
        check(f"(f/{variant}) still frozen", is_world_frozen())
        if variant == "accept":
            await rm2.accept(run_id)
            check("(f/accept) accepted", wr.get_run(run_id)["status"] == "accepted")
            check("(f/accept) F1 kept", len(by_name(name)) == 1)
        else:
            await rm2.discard(run_id)
            check("(f/discard) rolled_back", wr.get_run(run_id)["status"] == "rolled_back")
            check("(f/discard) F2 gone", not by_name(name))
        check(f"(f/{variant}) unfrozen", not is_world_frozen())

    print("(g) discard undoes everything")
    sq = "[[0, -400], [100, -400], [100, -300], [0, -300]]"
    areas_before = len(terrain.list_areas())
    rm, _ = manager([create("Demo G1"), call("add_terrain_area",
                                             '{"kind": "water", "polygon": %s}' % sq), "ok"])
    run_id = await start(rm)
    await settle(rm, run_id)
    check("(g) area added", len(terrain.list_areas()) == areas_before + 1)
    report = await rm.discard(run_id)
    check("(g) rolled_back", wr.get_run(run_id)["status"] == "rolled_back")
    check("(g) report complete, 2 reversed", report["complete"]
          and len(report["reversed"]) == 2, report)
    check("(g) G1 gone", not by_name("Demo G1"))
    check("(g) area gone", len(terrain.list_areas()) == areas_before)
    check("(g) unfrozen", not is_world_frozen())

    print("(h) discard with a foreign edit")
    rm, _ = manager([call("update_location", '{"id": "%s", "patch": {"description": '
                          '"agent2"}}' % P), create("Demo H1"), "ok"])
    run_id = await start(rm)
    await settle(rm, run_id)
    set_pond("foreign2")
    await rm.discard(run_id)
    run = wr.get_run(run_id)
    check("(h) rollback_incomplete", run["status"] == "rollback_incomplete", run["status"])
    check("(h) H1 gone", not by_name("Demo H1"))
    check("(h) P keeps foreign2", get_location_by_id(P)["description"] == "foreign2")
    check("(h) unfrozen", not is_world_frozen())
    check("(h) no open run", wr.open_run() is None)
    rm, _ = manager([create("Demo H2"), "ok"])
    run_id = await start(rm)
    await settle(rm, run_id)
    check("(h) a new run starts", wr.get_run(run_id)["status"] == "awaiting_review")
    await rm.discard(run_id)

    print("(i) stop during a slow tool")
    entered, release = threading.Event(), threading.Event()
    spec = wt.TOOLS["create_location"]
    original = spec.fn

    def slow(step, args):
        entered.set()
        release.wait(10)
        return original(step, args)

    spec.fn = slow
    try:
        rm, _ = manager([create("Demo I1"), "ok"])
        run_id = await start(rm)
        await asyncio.to_thread(entered.wait, 10)
        await rm.stop(run_id)
        release.set()
        run = await settle(rm, run_id)
    finally:
        spec.fn = original
    check("(i) rolled_back", run["status"] == "rolled_back", (run["status"], run["note"]))
    check("(i) note names the stop", "stop" in (run["note"] or "").lower(), run["note"])
    writes = [s for s in wr.steps(run_id) if s["kind"] == "write"]
    check("(i) the tool's write was journaled", len(writes) == 1, writes)
    check("(i) and undone", writes and writes[0]["undone_at"])
    check("(i) I1 gone", not by_name("Demo I1"))
    check("(i) unfrozen", not is_world_frozen())

    print("(j) turn 1 without a tool call")
    rm, _ = manager(["I would build a lake."])
    run_id = await start(rm)
    run = await settle(rm, run_id)
    check("(j) rolled_back", run["status"] == "rolled_back", run["status"])
    check("(j) note names tool-capable", "tool-capable" in (run["note"] or ""), run["note"])
    check("(j) unfrozen", not is_world_frozen())

    print("(k) history shrinking")
    rm, fake = manager([call("world_overview", "{}")] * 6 + ["Looked around."])
    run_id = await start(rm)
    await settle(rm, run_id)
    last = fake.calls[-1] if len(fake.calls) == 7 else []
    results = [m["content"] for m in last
               if m["content"].startswith("[result world_overview]")]
    shrunk = [c for c in results if "(shrunk" in c]
    check("(k) 7 LLM calls", len(fake.calls) == 7, len(fake.calls))
    check("(k) 6 results, 2 shrunk", len(results) == 6 and len(shrunk) == 2,
          (len(results), len(shrunk)))
    check("(k) the 2 oldest are the shrunk ones", results[:2] == shrunk,
          results[:2])
    check("(k) messages are plain role/content",
          all(set(m) == {"role", "content"} for m in last))
    await rm.discard(run_id)

    print("(l) templates")
    system = wa._render_system()
    check("(l) system prompt lists the tools", "create_location{" in system
          and "read_manual{section}" in system, system[:200])
    check("(l) system prompt names every manual section",
          all(s in system for s in wt.MANUAL_SECTIONS))
    run_id = wr.create_run("manual", "m", "p", "u", 40, 300000)
    for section in wt.MANUAL_SECTIONS:
        res = wt.run_tool(wt.ToolCtx(run_id=run_id, turn=1), "read_manual",
                          {"section": section})
        check(f"(l) read_manual {section}", res.ok and res.line.startswith("# Manual"),
              res.line[:80])
    wr.set_status(run_id, "accepted")

    print("(m) a tool raising")
    ov = wt.TOOLS["world_overview"]
    ov_fn = ov.fn

    def boom(step, args):
        raise RuntimeError("boom")

    ov.fn = boom
    try:
        rm, _ = manager([create("Demo M1"), call("world_overview", "{}"), "x"])
        run_id = await start(rm)
        sub = collect(rm, run_id)
        run = await settle(rm, run_id)
        m_events = await asyncio.wait_for(sub, 5)
    finally:
        ov.fn = ov_fn
    failed = [e for e in m_events if e["type"] == "step" and not e["ok"]]
    check("(m) the raising read tool's step event has kind read",
          [e.get("kind") for e in failed] == ["read"], failed)
    check("(m) rolled_back", run["status"] == "rolled_back", (run["status"], run["note"]))
    check("(m) note names the tool", "world_overview" in (run["note"] or ""), run["note"])
    check("(m) M1 gone", not by_name("Demo M1"))
    check("(m) unfrozen", not is_world_frozen())

    print("(n) token budget hit in turn 1 before the first tool call")
    rm, _ = manager([create("Demo N1"), "x"])
    run_id = await start(rm, max_tokens_total=50)
    run = await settle(rm, run_id)
    check("(n) rolled_back", run["status"] == "rolled_back", (run["status"], run["note"]))
    check("(n) note names the token budget", "token budget" in (run["note"] or ""),
          run["note"])
    check("(n) note says before the first tool call",
          "before the first tool call" in (run["note"] or ""),
          run["note"])
    check("(n) N1 never written", not by_name("Demo N1")
          and not [s for s in wr.steps(run_id) if s["kind"] == "write"])

    print("(o) RunStateError")
    for label, action in (("accept", lambda: rm.accept(run_id)),
                          ("discard", lambda: rm.discard(run_id)),
                          ("message", lambda: rm.message(run_id, "more")),
                          ("stop", lambda: rm.stop(run_id))):
        try:
            await action()
            raised = False
        except wa.RunStateError:
            raised = True
        check(f"(o) {label} on rolled_back raises RunStateError", raised)
    check("(o) still rolled_back", wr.get_run(run_id)["status"] == "rolled_back")

    print("(p) follow-up after a restart")
    rm, _ = manager([create("Demo P1"), "P1 done."])
    run_id = await start(rm, max_tokens=1234)
    await settle(rm, run_id)
    check("(p) max_tokens stored on the run", wr.get_run(run_id)["max_tokens"] == 1234,
          wr.get_run(run_id)["max_tokens"])
    rm2, fake2 = manager(["Nothing to add."])
    FACTORY_CALLS.clear()
    await rm2.message(run_id, "more")
    run = await settle(rm2, run_id)
    check("(p) the restart re-resolve keeps max_tokens 1234",
          FACTORY_CALLS == [("fake-model", "fake", 1234)], FACTORY_CALLS)
    first = fake2.calls[0] if fake2.calls else []
    check("(p) awaiting_review", run["status"] == "awaiting_review", run["status"])
    check("(p) rebuilt history shape",
          [m["role"] for m in first] == ["system", "user", "assistant", "user"],
          [m["role"] for m in first])
    check("(p) task, journal + note, message",
          len(first) == 4 and first[1]["content"] == "build something"
          and "create_location" in first[2]["content"]
          and "P1 done." in first[2]["content"] and first[3]["content"] == "more",
          [m["content"][:80] for m in first])
    rm3 = wa.RunManager()
    try:
        await rm3.stop(run_id)
        raised = False
    except wa.RunStateError:
        raised = True
    check("(p) stop on a foreign idle run raises", raised)
    evs = [e async for e in rm3.subscribe(run_id, 0)]
    check("(p) subscribe still yields the stored status",
          [e.get("status") for e in evs] == ["awaiting_review"], evs)
    evs = [e async for e in rm3.subscribe(run_id, 1)]
    check("(p) after=1 (the stored status already seen) yields nothing", evs == [], evs)
    evs = [e async for e in rm3.subscribe(run_id, 17)]
    check("(p) after=17 from an earlier process -> reset + stored status",
          [(e["ev"], e["type"], e.get("status")) for e in evs]
          == [(0, "reset", None), (1, "status", "awaiting_review")], evs)
    await rm2.discard(run_id)
    check("(p) P1 gone", not by_name("Demo P1"))

    print("(q) stop while the provider sends nothing")
    rm, fk = manager([create("Demo Q1"), "BLOCK"])
    run_id = await start(rm)
    for _ in range(500):
        if len(fk.calls) >= 2:
            break
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.05)
    await rm.stop(run_id)
    run = await settle(rm, run_id, timeout=5.0)
    check("(q) rolled_back", run["status"] == "rolled_back", (run["status"], run["note"]))
    check("(q) note names the stop", "stop" in (run["note"] or "").lower(), run["note"])
    check("(q) Q1 gone", not by_name("Demo Q1"))
    check("(q) unfrozen", not is_world_frozen())

    print("(r) unclosed tool tag with an incomplete body")
    # A COMPLETE body after an unclosed tag runs anyway (smoke_world_dev_json_repair);
    # an incomplete one is still refused.
    rm, _ = manager(['Look: <tool name="world_overview">{"x":', call("world_overview", "{}"),
                     "Looked."])
    run_id = await start(rm)
    run = await settle(rm, run_id)
    steps = wr.steps(run_id)
    check("(r) awaiting_review", run["status"] == "awaiting_review",
          (run["status"], run["note"]))
    check("(r) refused + read", [s["kind"] for s in steps] == ["refused", "read"],
          [(s["kind"], s["line"]) for s in steps])
    check("(r) not-closed line", steps and (steps[0]["line"] or "").startswith(
        "error: tool call not closed"), steps and steps[0]["line"])
    await rm.discard(run_id)

    print("(r2) unclosed tool tag cut off at output limit (finish_reason='length')")
    cut_reply = '<tool name="world_overview">{"x": "aaaa'
    rm, _ = manager([(cut_reply, "length"), call("world_overview", "{}"), "Looked."])
    run_id = await start(rm)
    run = await settle(rm, run_id)
    steps = wr.steps(run_id)
    check("(r2) awaiting_review", run["status"] == "awaiting_review",
          (run["status"], run["note"]))
    check("(r2) refused + read", [s["kind"] for s in steps] == ["refused", "read"],
          [(s["kind"], s["line"]) for s in steps])
    line0 = (steps[0]["line"] or "") if steps else ""
    check("(r2) cut-off line with char count and split hint",
          line0.startswith("error: your reply hit the model's output limit after 39 characters")
          and "one room per call" in line0, line0)
    await rm.discard(run_id)

    print("(r3) same incomplete reply without finish_reason")
    rm, _ = manager([cut_reply, call("world_overview", "{}"), "Looked."])
    run_id = await start(rm)
    run = await settle(rm, run_id)
    steps = wr.steps(run_id)
    check("(r3) awaiting_review", run["status"] == "awaiting_review",
          (run["status"], run["note"]))
    check("(r3) refused + read", [s["kind"] for s in steps] == ["refused", "read"],
          [(s["kind"], s["line"]) for s in steps])
    line0 = (steps[0]["line"] or "") if steps else ""
    check("(r3) not-closed line", line0.startswith("error: tool call not closed"), line0)
    await rm.discard(run_id)

    print("(s) the end-of-turn transition raises")
    real_set_status = wr.set_status
    tripped = {"n": 0}

    def flaky(run_id_, status, note=None):
        if status == "awaiting_review" and not tripped["n"]:
            tripped["n"] += 1
            raise RuntimeError("db locked")
        return real_set_status(run_id_, status, note)

    wr.set_status = flaky
    try:
        rm, _ = manager([create("Demo S1"), "ok"])
        run_id = await start(rm)
        run = await settle(rm, run_id)
    finally:
        wr.set_status = real_set_status
    check("(s) interrupted", run["status"] == "interrupted", (run["status"], run["note"]))
    check("(s) not busy", not rm.is_busy(run_id))
    check("(s) note names the failure", "db locked" in (run["note"] or ""), run["note"])
    await rm.discard(run_id)
    check("(s) discard -> rolled_back", wr.get_run(run_id)["status"] == "rolled_back")
    check("(s) S1 gone", not by_name("Demo S1"))
    check("(s) unfrozen", not is_world_frozen())

    print("(t) a final reply that crosses the token budget")
    real_estimate = llm_cost.estimate_cost
    llm_cost.estimate_cost = lambda *a, **k: (60, 40, 0.0)
    try:
        rm, fake = manager([create("Demo T1"), "T1 done."])
        run_id = await start(rm, max_tokens_total=150)
        run = await settle(rm, run_id)
    finally:
        llm_cost.estimate_cost = real_estimate
    check("(t) 2 LLM calls", len(fake.calls) == 2, len(fake.calls))
    check("(t) 200 tokens used", run["tokens_in"] + run["tokens_out"] == 200,
          (run["tokens_in"], run["tokens_out"]))
    check("(t) awaiting_review, the final reply is kept",
          run["status"] == "awaiting_review" and run["note"] == "T1 done.",
          (run["status"], run["note"]))
    check("(t) T1 kept", len(by_name("Demo T1")) == 1)
    await rm.discard(run_id)

    print("(y) token budget per turn: cut, kept, next turn starts at 0")
    llm_cost.estimate_cost = lambda *a, **k: (60, 40, 0.0)
    try:
        rm, fake = manager([create("Demo Y1"), create("Demo Y2")])
        run_id = await start(rm, max_tokens_total=150)
        run = await settle(rm, run_id)
        check("(y) turn 1 cut by tokens, Y1 kept, Y2 never written",
              run["status"] == "awaiting_review"
              and (run["note"] or "").startswith("budget reached (tokens: 200 of 150 this turn)")
              and len(by_name("Demo Y1")) == 1 and not by_name("Demo Y2"),
              (run["status"], run["note"]))
        fake.replies += [create("Demo Y2"), "Y2 done."]
        await rm.message(run_id, "continue")
        run = await settle(rm, run_id)
        y_evs = [e async for e in rm.subscribe(run_id, 0)
                 if e["type"] == "usage" and e.get("turn") == 2]
    finally:
        llm_cost.estimate_cost = real_estimate
    check("(y) turn 2 final, Y2 written", run["status"] == "awaiting_review"
          and run["note"] == "Y2 done." and len(by_name("Demo Y2")) == 1,
          (run["status"], run["note"]))
    check("(y) run total 400 tokens", run["tokens_in"] + run["tokens_out"] == 400,
          (run["tokens_in"], run["tokens_out"]))
    # By hand: LLM call 1 of turn 2 -> 100 turn tokens (300 total), 0 calls;
    # its tool call is counted -> a usage event at once, turn_steps 1, tokens
    # unchanged; LLM call 2 (the final reply) -> 200 (400 total), still 1.
    check("(y) turn-2 usage: (turn_tokens, total, turn_steps) per event",
          [(e["turn_tokens"], e["tokens_in"] + e["tokens_out"], e["turn_steps"])
           for e in y_evs]
          == [(100, 300, 0), (100, 300, 1), (200, 400, 1)], y_evs)
    check("(y) turn_usage of the newest turn", rm.turn_usage(run_id)
          == {"turn": 2, "steps": 1, "tokens": 200}, rm.turn_usage(run_id))
    await rm.discard(run_id)

    print("(u) budgets are only raised")
    rm, fake = manager([create("Demo U1"), "U1 done.", "ok.", "ok."])
    run_id = await start(rm)
    await settle(rm, run_id)
    await rm.message(run_id, "lower", max_steps=10, max_tokens_total=1000)
    run = await settle(rm, run_id)
    check("(u) lowering keeps 200 / 2000000",
          (run["max_steps"], run["max_tokens_total"]) == (200, 2000000),
          (run["max_steps"], run["max_tokens_total"]))
    await rm.message(run_id, "raise", max_steps=250)
    run = await settle(rm, run_id)
    check("(u) raising steps -> 250 / 2000000",
          (run["max_steps"], run["max_tokens_total"]) == (250, 2000000),
          (run["max_steps"], run["max_tokens_total"]))
    await rm.discard(run_id)

    print("(v) start fails after the run was created")
    set_world_frozen(True)
    real_was = wr.set_was_frozen

    def disk_full(run_id_, was):
        raise RuntimeError("disk full")

    wr.set_was_frozen = disk_full
    try:
        rm, fake = manager([create("Demo V1"), "ok"])
        try:
            await start(rm)
            raised = None
        except RuntimeError as e:
            raised = str(e)
    finally:
        wr.set_was_frozen = real_was
    run = wr.list_runs(1)[0]
    check("(v) start raises the error", raised == "disk full", raised)
    check("(v) the run is closed rolled_back", run["status"] == "rolled_back"
          and "disk full" in (run["note"] or ""), (run["status"], run["note"]))
    check("(v) no LLM call", fake.calls == [], len(fake.calls))
    check("(v) the freeze state is untouched (still frozen)", is_world_frozen())
    check("(v) no open run", wr.open_run() is None)
    set_world_frozen(False)
    rm, _ = manager([create("Demo V2"), "ok"])
    run_id = await start(rm)
    check("(v) a new run starts",
          (await settle(rm, run_id))["status"] == "awaiting_review")
    await rm.discard(run_id)

    print("(w) a waiting subscriber wakes when _interrupt cannot reach the store")
    real_set_status, real_get_run = wr.set_status, wr.get_run
    arm = {"status": 1, "get_run": 0}

    def flaky_status(run_id_, status, note=None):
        if status == "awaiting_review" and arm["status"]:
            arm["status"], arm["get_run"] = 0, 1
            raise RuntimeError("db locked")
        return real_set_status(run_id_, status, note)

    def flaky_get_run(run_id_):
        # Only _interrupt's own read (in the thread pool) right after the trip.
        if arm["get_run"] and threading.current_thread() is not threading.main_thread():
            arm["get_run"] = 0
            raise RuntimeError("db gone")
        return real_get_run(run_id_)

    wr.set_status, wr.get_run = flaky_status, flaky_get_run
    try:
        rm, _ = manager([create("Demo W1"), "ok"])
        run_id = await start(rm)
        sub = collect(rm, run_id)
        for _ in range(500):
            if not rm.is_busy(run_id):
                break
            await asyncio.sleep(0.02)
        try:
            w_events = await asyncio.wait_for(sub, 2)
            woke = True
        except asyncio.TimeoutError:
            w_events, woke = [], False
    finally:
        wr.set_status, wr.get_run = real_set_status, real_get_run
    check("(w) the get_run failure was hit", arm == {"status": 0, "get_run": 0}, arm)
    check("(w) the subscriber ended", woke)
    check("(w) no interrupted event (the store was unreachable)",
          not any(e.get("status") == "interrupted" for e in w_events), w_events[-1:])
    check("(w) the run is still running (the boot sweep is the backstop)",
          wr.get_run(run_id)["status"] == "running")
    rm2 = wa.RunManager()
    rm2.mark_interrupted_on_boot()
    await rm2.discard(run_id)
    check("(w) boot sweep + discard -> rolled_back",
          wr.get_run(run_id)["status"] == "rolled_back")
    check("(w) W1 gone", not by_name("Demo W1"))
    check("(w) unfrozen", not is_world_frozen())

    print("(x) discard closes even when recording the skips fails")
    rm, _ = manager([call("update_location", '{"id": "%s", "patch": {"description": '
                          '"agent3"}}' % P), create("Demo X1"), "ok"])
    run_id = await start(rm)
    await settle(rm, run_id)
    set_pond("foreign3")
    real_skipped = wr.set_skipped

    def skip_fails(run_id_, skipped):
        raise RuntimeError("db locked")

    wr.set_skipped = skip_fails
    try:
        await rm.discard(run_id)
    finally:
        wr.set_skipped = real_skipped
    run = wr.get_run(run_id)
    check("(x) rollback_incomplete", run["status"] == "rollback_incomplete", run["status"])
    check("(x) X1 gone", not by_name("Demo X1"))
    check("(x) P keeps foreign3", get_location_by_id(P)["description"] == "foreign3")
    check("(x) unfrozen", not is_world_frozen())
    check("(x) no open run", wr.open_run() is None)

    print("(z) pinned reads through the loop")
    man_c = call("read_manual", '{"section": "characters"}')
    man_h = call("read_manual", '{"section": "homes"}')
    rm, fake = manager([man_c, man_h, "Read.", man_c,
                        RuntimeError("down"), "ok."])
    run_id = await start(rm)
    run = await settle(rm, run_id)
    check("(z) turn 1 awaiting_review", run["status"] == "awaiting_review", run["status"])

    def man_results(msgs):
        return [m["content"] for m in msgs
                if m["content"].startswith("[result read_manual]")]

    z1 = man_results(fake.calls[2]) if len(fake.calls) >= 3 else []
    check("(z) call 3: two whole manual reads",
          len(z1) == 2 and all(c.startswith("[result read_manual] # Manual") for c in z1),
          [c[:60] for c in z1])
    await rm.message(run_id, "again")
    run = await settle(rm, run_id)
    check("(z) turn 2 rolled back to review", run["status"] == "awaiting_review"
          and "down" in (run["note"] or ""), (run["status"], run["note"]))
    await rm.message(run_id, "go on")
    await settle(rm, run_id)
    z3 = man_results(fake.calls[-1]) if len(fake.calls) == 6 else []
    check("(z) 6 LLM calls", len(fake.calls) == 6, len(fake.calls))
    check("(z) turn 3: both turn-1 reads whole, none superseded",
          len(z3) == 2 and all(c.startswith("[result read_manual] # Manual") for c in z3),
          [c[:60] for c in z3])
    await rm.discard(run_id)

    print("(w2) one call with several journal rows counts once")
    rows_create = call("create_character", '{"data": {"character_name": "Demo Rows", '
                       '"template": "human-roleplay"}}')
    rows_update = call("update_character", '{"name": "Demo Rows", "patch": '
                       '{"soul:character_presence": "Text A", "age": 30}}')
    rm, fake = manager([rows_create, rows_update, call("world_overview", "{}")])
    run_id = await start(rm, max_steps=2)
    run = await settle(rm, run_id)
    w_writes = [s for s in wr.steps(run_id) if s["kind"] == "write"]
    check("(w2) cut: budget reached (tool calls: 2 of 2 this turn)",
          run["status"] == "awaiting_review"
          and (run["note"] or "").startswith("budget reached (tool calls: 2 of 2 this turn)"),
          (run["status"], run["note"]))
    check("(w2) run.steps == 2", run["steps"] == 2, run["steps"])
    check("(w2) 3 write rows (create + 2 groups)", len(w_writes) == 3,
          [(s["tool"], (s.get("inverse") or {}).get("op")) for s in w_writes])
    check("(w2) 3 LLM calls", len(fake.calls) == 3, len(fake.calls))
    await rm.discard(run_id)

    print("(x2) refused calls count")
    rm, fake = manager(['<tool name="get_character">bad json</tool>',
                        '<tool name="no_such_tool">{}</tool>', "done"])
    run_id = await start(rm)
    run = await settle(rm, run_id)
    check("(x2) awaiting_review", run["status"] == "awaiting_review",
          (run["status"], run["note"]))
    check("(x2) run.steps == 2", run["steps"] == 2, run["steps"])
    check("(x2) 2 refused journal rows",
          [s["kind"] for s in wr.steps(run_id)] == ["refused", "refused"],
          [(s["kind"], s["line"]) for s in wr.steps(run_id)])
    await rm.discard(run_id)

    print("(z2) token note in thousands")
    check("(z2) _k by hand",
          [wa._k(2_000_123), wa._k(1_499), wa._k(1_500), wa._k(0)]
          == ["2,000k", "1k", "2k", "0k"],
          [wa._k(n) for n in (2_000_123, 1_499, 1_500, 0)])
    llm_cost.estimate_cost = lambda *a, **k: (600, 400, 0.0)
    try:
        rm, fake = manager([create("Demo Z1"), create("Demo Z2"), create("Demo Z3")])
        run_id = await start(rm, max_tokens_total=1500)
        run = await settle(rm, run_id)
    finally:
        llm_cost.estimate_cost = real_estimate
    check("(z2) note in k", run["note"] == ("budget reached (tokens: 2k of 2k this turn) "
                                           "— the turn's work is kept; send a follow-up "
                                           "to continue"), run["note"])
    check("(z2) 2 LLM calls, Z1 kept, Z2 never written",
          len(fake.calls) == 2 and len(by_name("Demo Z1")) == 1 and not by_name("Demo Z2"),
          (len(fake.calls), by_name("Demo Z2")))
    await rm.discard(run_id)

    print("(y2) a bad JSON body carries the parse position and the escape hint")
    rm, fake = manager([call("update_character",
                             '{"name": "X", "patch": {"soul:a": "he said "hi""}}'),
                        call("update_character", "[1]"), "done"])
    run_id = await start(rm)
    run = await settle(rm, run_id)
    y_rows = [s for s in wr.steps(run_id) if s["kind"] == "refused"]
    y_lines = [s.get("line") or "" for s in y_rows]
    check("(y2) awaiting_review, 2 refused rows",
          run["status"] == "awaiting_review" and len(y_rows) == 2,
          (run["status"], y_lines))
    y1 = y_lines[0] if y_lines else ""
    check("(y2) row 1: JSON error position",
          y1.startswith("error: body is not a JSON object (JSON error: Expecting ',' "
                        "delimiter at line 1 column 45)"), y1)
    check("(y2) row 1: exact hint", y1 == (
        "error: body is not a JSON object (JSON error: Expecting ',' delimiter at "
        "line 1 column 45) — inside a string write a double quote as \\\" and a "
        "line break as \\n; split a very long text into several calls"), y1)
    check("(y2) row 1: literal backslash escapes, no real line break",
          '\\"' in y1 and '\\n' in y1 and "\n" not in y1, y1)
    check("(y2) row 2: not an object", len(y_lines) == 2
          and y_lines[1] == "error: body is not a JSON object (got list)", y_lines)
    await rm.discard(run_id)
    system = wa._render_system()
    check("(y2) system prompt lists check_character", "check_character{name}" in system)
    check("(y2) system prompt step 5 names check_character for fill tasks",
          "For a task that asks to fill, complete or check existing characters, call "
          "`check_character` for each of them" in " ".join(system.split()))

    check("every LLM registration closed", COUNTS["active"] == COUNTS["done"]
          and COUNTS["active"] > 0, COUNTS)


asyncio.run(main())
print()
if failures:
    print(f"FAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("all checks passed")
