#!/usr/bin/env python3
"""Check for the turn trace (app/core/turn_trace.py) and its logger hand-off.

Usage:
    ./.venv/bin/python scripts/test_turn_trace.py

Runs without a server and without a world DB. Writes only into a temp dir
(the JSONL logger's LOG_DIR/LOG_FILE are redirected).

Expected values, derived by hand from the contract:

(a) begin_trace("chat", "Demo") returns {"id": <10 hex chars>, "kind": "chat",
    "who": "Demo"}; current_trace() in the SAME context returns exactly that
    dict. id is uuid4().hex[:10] -> len 10, all chars in [0-9a-f].

(b) contextvars propagate through asyncio.to_thread (it runs the callable via
    contextvars.copy_context().run in the worker thread), so a trace set in
    the coroutine is readable inside the thread: current_trace()["id"] there
    == the id from begin_trace.

(c) asyncio.create_task copies the context at creation time; a begin_trace
    INSIDE the task writes into that copy only. Two parallel workers that each
    begin their own trace therefore see only their own id — after an await
    that lets the other worker run, worker A still reads id_A and worker B
    id_B, and id_A != id_B. The parent context keeps the value it had before
    (here: None).

(d) log_llm_call writes one JSONL line per call. Inside a trace the line
    carries trace_id == the active id and trace_kind == the active kind;
    without a trace NEITHER key is present in the entry (they are only
    written when set). An explicitly passed trace_id wins over the ambient
    one, PER FIELD: passing only trace_id keeps that id and still takes the
    kind from the ambient trace. Four calls in this check -> 4 lines.
    NOTE: contextvars.copy_context() COPIES the current values, it does not
    clear them — a genuinely trace-free context is only reachable in a new
    thread (see (e)), which is what ``run_fresh`` below uses.

(e) A plain threading.Thread starts with a FRESH context (contextvars are
    per-thread; PEP 567 gives a new thread an empty top-level context), so
    current_trace() inside such a thread is None even when the spawning
    thread has a trace. That is exactly why LLMTask carries trace_id/
    trace_kind as VALUES: the provider-queue worker thread cannot read the
    submitter's context. Expected: LLMTask(...).trace_id == "" by default and
    the thread sees None.

(f) End-to-end shape of one turn (stubs, no server): a root like
    AgentLoop._respond_worker calls begin_trace ONCE, then the work fans out
    over the three hand-off kinds this code base uses:
      1. asyncio.to_thread (chat_engine.run_chat_turn in the respond lane) —
         propagates on its own,
      2. a queue submit that captures the trace as a VALUE (ProviderQueue),
      3. a plain threading.Thread for the follow-up jobs (tool phase,
         post-processing) — wrapped in bind_trace,
      4. an executor hand-off, loop.run_in_executor (relationship summary /
         chat-state extraction inside post_process_response) — bind_trace too.
    Expected: all four stations report the id of the root's trace, i.e. the
    set of observed ids has exactly ONE element. bind_trace additionally
    RESTORES the previous value, so a pooled executor thread does not keep the
    trace for the next, unrelated job: the same worker thread reads None again
    after the job returned.

    The check also pins the EXCLUSION property that distinguishes bind_trace
    from contextvars.copy_context().run: a second, unrelated ContextVar set in
    the worker (stand-in for perception_shadow.suppressed(), which the chat
    follow-ups must NOT inherit — chat_engine.py comment at the _bg_after_reply
    spawn) must read its DEFAULT inside the bound jobs. asyncio.to_thread does
    copy the whole context, so there the stand-in is visible — that asymmetry
    is the point and is asserted in both directions.
"""
import asyncio
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.turn_trace import (  # noqa: E402
    begin_trace, bind_trace, current_trace, set_trace)

_failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"  ({detail})" if detail else ""))
    if not ok:
        _failures.append(name)


def run_fresh(fn, *args):
    """Runs ``fn`` in a NEW thread, i.e. in an empty contextvars context.

    Every check starts trace-free this way; copy_context() would carry the
    values of the previous check along.
    """
    box = {}

    def _target():
        try:
            box["result"] = fn(*args)
        except BaseException as err:  # re-raised in the caller
            box["error"] = err

    th = threading.Thread(target=_target)
    th.start()
    th.join()
    if "error" in box:
        raise box["error"]
    return box.get("result")


# --- (a) begin_trace + read in the same context -----------------------------
def test_same_context():
    print("(a) begin_trace + current_trace in the same context")
    t = begin_trace("chat", "Demo")
    cur = current_trace()
    check("returned dict has id/kind/who", set(t) == {"id", "kind", "who"}, str(sorted(t)))
    check("kind/who as passed", t["kind"] == "chat" and t["who"] == "Demo")
    check("id is 10 hex chars",
          len(t["id"]) == 10 and all(c in "0123456789abcdef" for c in t["id"]), t["id"])
    check("current_trace returns the same trace", cur == t, f"{cur} vs {t}")
    t2 = begin_trace("thought", "Demo")
    check("begin_trace overwrites the inherited trace",
          current_trace() == t2 and t2["id"] != t["id"])


# --- (b) propagation through asyncio.to_thread ------------------------------
def test_to_thread():
    print("(b) propagation through asyncio.to_thread")

    def _in_thread():
        return current_trace(), threading.current_thread().name

    async def _main():
        t = begin_trace("respond", "Demo")
        seen, thread_name = await asyncio.to_thread(_in_thread)
        return t, seen, thread_name

    t, seen, thread_name = asyncio.run(_main())
    check("thread is not the main thread", thread_name != "MainThread", thread_name)
    check("trace readable inside the thread",
          seen is not None and seen["id"] == t["id"], f"{seen} vs {t}")


# --- (c) isolation between two parallel create_task workers -----------------
def test_task_isolation():
    print("(c) isolation of two parallel asyncio.create_task workers")

    async def _worker(kind: str, gate: asyncio.Event, out: dict):
        t = begin_trace(kind, kind)
        out[kind + "_own"] = t["id"]
        gate.set()
        # Yield control so the other worker sets ITS trace in between.
        await asyncio.sleep(0.02)
        seen = current_trace()
        out[kind + "_after"] = seen["id"] if seen else None

    async def _main():
        out: dict = {}
        gate_a, gate_b = asyncio.Event(), asyncio.Event()
        a = asyncio.create_task(_worker("respond", gate_a, out))
        b = asyncio.create_task(_worker("thought", gate_b, out))
        await asyncio.gather(a, b)
        out["parent"] = current_trace()
        return out

    out = asyncio.run(_main())
    check("worker A keeps its own trace", out["respond_own"] == out["respond_after"],
          f"{out['respond_own']} vs {out['respond_after']}")
    check("worker B keeps its own trace", out["thought_own"] == out["thought_after"],
          f"{out['thought_own']} vs {out['thought_after']}")
    check("the two traces differ", out["respond_own"] != out["thought_own"])
    check("parent context untouched (None)", out["parent"] is None, str(out["parent"]))


# --- (d) log_llm_call writes trace_id ---------------------------------------
def test_logger():
    print("(d) log_llm_call writes trace_id/trace_kind into the JSONL")
    from app.utils import llm_logger

    tmpdir = Path(tempfile.mkdtemp(prefix="turn_trace_check_"))
    orig_dir, orig_file = llm_logger.LOG_DIR, llm_logger.LOG_FILE
    llm_logger.LOG_DIR = tmpdir
    llm_logger.LOG_FILE = tmpdir / "llm_calls.jsonl"
    try:
        def _run():
            t = begin_trace("respond", "Demo")
            llm_logger.log_llm_call(task="character_talk", model="m", response="x")
            llm_logger.log_llm_call(task="intent", model="m", response="x",
                                    trace_id="explicit01", trace_kind="manual")
            llm_logger.log_llm_call(task="extraction_chat_state", model="m",
                                    response="x", trace_id="explicit02")
            return t

        t = _run()
        # ... and a call with NO trace at all, in a genuinely fresh context.
        run_fresh(llm_logger.log_llm_call, "summarize", "m")

        lines = [json.loads(ln) for ln in
                 llm_logger.LOG_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()]
        check("4 entries written", len(lines) == 4, str(len(lines)))
        e_amb, e_expl, e_half, e_none = lines
        check("ambient trace_id in the entry", e_amb.get("trace_id") == t["id"],
              f"{e_amb.get('trace_id')} vs {t['id']}")
        check("ambient trace_kind in the entry", e_amb.get("trace_kind") == "respond",
              str(e_amb.get("trace_kind")))
        check("explicit trace_id wins", e_expl.get("trace_id") == "explicit01",
              str(e_expl.get("trace_id")))
        check("explicit trace_kind wins", e_expl.get("trace_kind") == "manual",
              str(e_expl.get("trace_kind")))
        check("explicit id only: id kept", e_half.get("trace_id") == "explicit02",
              str(e_half.get("trace_id")))
        check("explicit id only: kind from ambient trace",
              e_half.get("trace_kind") == "respond", str(e_half.get("trace_kind")))
        check("without a trace: trace_id key absent", "trace_id" not in e_none,
              str(e_none.get("trace_id")))
        check("without a trace: trace_kind key absent", "trace_kind" not in e_none,
              str(e_none.get("trace_kind")))
    finally:
        llm_logger.LOG_DIR, llm_logger.LOG_FILE = orig_dir, orig_file
        for p in tmpdir.glob("*"):
            p.unlink()
        os.rmdir(tmpdir)


# --- (e) plain threads need the value on the task ---------------------------
def test_plain_thread_needs_value():
    print("(e) plain threading.Thread sees no trace -> LLMTask carries the value")
    from app.core.llm_queue import LLMTask

    begin_trace("respond", "Demo")
    seen = {}

    def _in_thread():
        seen["trace"] = current_trace()

    th = threading.Thread(target=_in_thread)
    th.start()
    th.join()
    check("plain thread has no ambient trace", seen["trace"] is None, str(seen["trace"]))

    task = LLMTask(task_id="t", task_type="x", priority=20, agent_name="", created_at="")
    check("LLMTask.trace_id defaults to empty", task.trace_id == "", repr(task.trace_id))
    check("LLMTask.trace_kind defaults to empty", task.trace_kind == "", repr(task.trace_kind))


# --- (f) one whole turn: root + the three hand-off kinds ---------------------
def test_turn_flow():
    print("(f) one turn: root -> to_thread, queue submit, thread, executor")
    import contextvars
    from concurrent.futures import ThreadPoolExecutor

    # Stand-in for perception_shadow.suppressed(): an unrelated context var
    # that the background follow-ups must NOT inherit.
    shadow: contextvars.ContextVar = contextvars.ContextVar(
        "shadow_stub", default=False)

    seen: dict = {}

    def _submit_stub() -> str:
        """Stands in for ProviderQueue.submit: reads the trace at SUBMIT time
        and puts it on the task as a value (the queue worker thread has a
        context of its own and could not read it later)."""
        t = current_trace()
        return t["id"] if t else ""

    def _chat_turn():
        # asyncio.to_thread — like run_chat_turn in the respond lane. This one
        # DOES copy the whole context, shadow stand-in included.
        t = current_trace()
        seen["chat_turn"] = t["id"] if t else None
        seen["chat_turn_shadow"] = shadow.get()
        seen["queue"] = _submit_stub()

    def _follow_up():
        # plain threading.Thread — like _bg_after_reply in chat_engine.
        t = current_trace()
        seen["follow_up"] = t["id"] if t else None
        seen["follow_up_shadow"] = shadow.get()

    def _extraction():
        # executor job — like _background_extraction in post_process_response.
        t = current_trace()
        seen["extraction"] = t["id"] if t else None
        seen["extraction_shadow"] = shadow.get()

    def _unrelated_pool_job():
        # Same pool thread, a LATER job that belongs to no turn.
        t = current_trace()
        seen["pool_after"] = t["id"] if t else None

    async def _worker():
        # What AgentLoop._respond_worker does: its own trace, first thing in
        # the coroutine body.
        t = begin_trace("respond", "Demo")
        shadow.set(True)  # e.g. the respond turn suppresses the shadow write
        await asyncio.to_thread(_chat_turn)
        th = threading.Thread(target=bind_trace(_follow_up), daemon=True)
        th.start()
        th.join()
        # max_workers=1: the unrelated job below provably runs in the SAME
        # thread as the bound one.
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            pool.submit(bind_trace(_extraction)).result()
            pool.submit(_unrelated_pool_job).result()
        finally:
            pool.shutdown()
        return t

    t = asyncio.run(_worker())
    ids = {seen.get(k) for k in ("chat_turn", "queue", "follow_up", "extraction")}
    for station in ("chat_turn", "queue", "follow_up", "extraction"):
        check(f"{station} sees the root trace", seen.get(station) == t["id"],
              f"{seen.get(station)} vs {t['id']}")
    check("all stations share ONE id", ids == {t["id"]}, str(sorted(map(str, ids))))
    check("bind_trace leaves no trace in the pool thread",
          seen.get("pool_after") is None, str(seen.get("pool_after")))
    # Exclusion: bind_trace hands over the trace ONLY — a copy_context().run
    # would drag the shadow stand-in along and turn these two green→red.
    check("to_thread does copy the unrelated context var",
          seen.get("chat_turn_shadow") is True, str(seen.get("chat_turn_shadow")))
    check("bound thread does NOT inherit the unrelated context var",
          seen.get("follow_up_shadow") is False, str(seen.get("follow_up_shadow")))
    check("bound executor job does NOT inherit the unrelated context var",
          seen.get("extraction_shadow") is False, str(seen.get("extraction_shadow")))


# --- (g) set_trace clears an inherited trace ---------------------------------
def test_set_trace_clear():
    print("(g) set_trace(None) clears a trace set by an awaited coroutine")

    async def _turn():
        # Like AgentLoop._run_turn: begin_trace writes into the CALLER's
        # context, because await does not copy it.
        begin_trace("thought", "Demo")

    async def _loop():
        before = current_trace()
        await _turn()
        during = current_trace()
        set_trace(None)
        return before, during, current_trace()

    before, during, after = asyncio.run(_loop())
    check("caller starts trace-free", before is None, str(before))
    check("awaited coroutine sets the caller's trace",
          during is not None and during["kind"] == "thought", str(during))
    check("set_trace(None) clears it again", after is None, str(after))


def main() -> int:
    # Each check runs in its own fresh context (see run_fresh) so no trace
    # of an earlier check leaks into the next one.
    for fn in (test_same_context, test_to_thread, test_task_isolation,
               test_logger, test_plain_thread_needs_value, test_turn_flow,
               test_set_trace_clear):
        run_fresh(fn)
    print()
    if _failures:
        print("FAIL — %d check(s) failed: %s" % (len(_failures), ", ".join(_failures)))
        return 1
    print("PASS — turn trace, propagation, isolation, logger and turn-flow "
          "hand-offs OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
