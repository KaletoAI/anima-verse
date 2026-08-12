#!/usr/bin/env python3
"""Check: the provider's finish_reason survives from the SDK response to the log.

No server, no world DB, no network — the OpenAI SDK call is replaced by a
hand-built fake response, and the JSONL logger writes into a temp directory so
the real logs/llm_calls.jsonl is never touched.

Covered:
  1. finish_reason="stop"      -> LLMResponse.finish_reason == "stop", no warning
  2. finish_reason="length"    -> field arrives AND a warning is logged
  3. provider sends none       -> field is None, no warning, no crash
  4. _log_task_result          -> JSONL line carries "finish_reason" exactly when known
  5. LLMResponse(content=...)  -> existing callers still construct it positionally
  6. astream                   -> terminal chunk carries the reason, adds no text
  7. StreamingAgent (SSE path) -> reason reaches the JSONL line, text unchanged

Usage:  ./.venv/bin/python scripts/test_finish_reason.py
"""
import asyncio
import json
import logging
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import llm_client as lc          # noqa: E402
from app.core import provider_queue as pq      # noqa: E402
from app.core import streaming                 # noqa: E402
from app.core.llm_queue import LLMTask         # noqa: E402
from app.utils import llm_logger               # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK ' if ok else 'FAIL'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(f"{label}: {detail}" if detail else label)


class WarningCollector(logging.Handler):
    """Collects WARNING records of the llm_client logger (caplog equivalent)."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def fake_response(content: str, finish, with_attr: bool = True):
    """An OpenAI-shaped chat completion. with_attr=False omits finish_reason
    entirely — some gateways leave the key out instead of sending null."""
    choice_fields = {"message": SimpleNamespace(content=content)}
    if with_attr:
        choice_fields["finish_reason"] = finish
    return SimpleNamespace(
        choices=[SimpleNamespace(**choice_fields)],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7))


def build_client(resp):
    """LLMClient whose SDK call is replaced — the constructor opens no socket."""
    client = lc.LLMClient(model="fake-model", api_key="none",
                          api_base="http://127.0.0.1:9/v1")
    client._sync.chat.completions.create = lambda **kwargs: resp
    return client


def run_invoke(resp):
    """Returns (LLMResponse, [warning messages])."""
    collector = WarningCollector()
    logger = logging.getLogger("llm_client")
    logger.addHandler(collector)
    try:
        return build_client(resp).invoke([{"role": "user", "content": "hi"}]), \
            collector.messages
    finally:
        logger.removeHandler(collector)


@contextmanager
def temp_log(tmp_dir: Path):
    """Redirects the JSONL logger into a temp dir — the real logs/ stay shut."""
    orig_dir, orig_file = llm_logger.LOG_DIR, llm_logger.LOG_FILE
    llm_logger.LOG_DIR = tmp_dir
    llm_logger.LOG_FILE = tmp_dir / "llm_calls.jsonl"
    if llm_logger.LOG_FILE.exists():
        llm_logger.LOG_FILE.unlink()
    try:
        yield llm_logger.LOG_FILE
    finally:
        llm_logger.LOG_DIR, llm_logger.LOG_FILE = orig_dir, orig_file


def last_entry(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").strip().splitlines() if path.exists() else []
    return json.loads(lines[-1]) if lines else {}


def log_line_for(response, tmp_dir: Path) -> dict:
    """Runs _log_task_result against a temp log file and returns the JSON line."""
    with temp_log(tmp_dir) as log_file:
        task = LLMTask(task_id="t1", task_type="thought", priority=2,
                       agent_name="demo", created_at="2026-08-02T00:00:00+00:00")
        task._messages = [{"role": "user", "content": "hi"}]
        task.duration_s = 0.0  # keeps llm_stats.record_call out of this check
        pq._log_task_result(task, "fake-model", 0, response)
        return last_entry(log_file)


def stream_client(pieces, finish):
    """LLMClient whose async SDK call yields ``pieces``, then — like the real
    SDK — one chunk with an empty delta carrying ``finish`` (None = none sent)."""
    client = lc.LLMClient(model="fake-model", api_key="none",
                          api_base="http://127.0.0.1:9/v1")

    def sdk_chunk(text, reason):
        return SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content=text), finish_reason=reason)])

    async def create(**kwargs):
        async def gen():
            for p in pieces:
                yield sdk_chunk(p, None)
            if finish is not None:
                yield sdk_chunk(None, finish)
        return gen()

    client._async.chat.completions.create = create
    return client


async def collect_stream(pieces, finish):
    """All LLMChunks of one astream run."""
    return [c async for c in stream_client(pieces, finish).astream(
        [{"role": "user", "content": "hi"}])]


async def run_sse(pieces, finish, tmp_dir: Path):
    """Drives the real SSE path (StreamingAgent._stream_llm_response) with a
    faked SDK stream. Returns (text sent to the client, LoopInfoEvent chunk
    count, JSONL entry)."""
    client = stream_client(pieces, finish)
    agent = streaming.StreamingAgent(
        llm=client, tool_format="xml", tools_dict={}, agent_name="demo",
        log_task="chat_stream", mode="no_tools")
    state = streaming._StreamState()
    sent, chunks = [], -1
    with temp_log(tmp_dir) as log_file:
        async for ev in agent._stream_llm_response(
                state, client, "system prompt", [], "hi"):
            if isinstance(ev, streaming.ContentEvent):
                sent.append(ev.content)
            elif isinstance(ev, streaming.LoopInfoEvent):
                chunks = ev.chunks
        return "".join(sent), chunks, last_entry(log_file), state.response


def main() -> int:
    print("1. finish_reason='stop'")
    resp, warnings = run_invoke(fake_response("Done.", "stop"))
    check("field arrives as 'stop'", resp.finish_reason == "stop",
          repr(resp.finish_reason))
    check("no warning for a clean stop", not warnings, str(warnings))
    check("content untouched", resp.content == "Done.", repr(resp.content))
    check("usage untouched",
          resp.usage == {"prompt_tokens": 11, "completion_tokens": 7},
          repr(resp.usage))

    print("2. finish_reason='length'")
    resp, warnings = run_invoke(fake_response("Cut off mid-sen", "length"))
    check("field arrives as 'length'", resp.finish_reason == "length",
          repr(resp.finish_reason))
    check("exactly one warning", len(warnings) == 1, str(warnings))
    msg = warnings[0] if warnings else ""
    check("warning names finish_reason=", "finish_reason=" in msg, msg)
    check("warning quotes the value", "'length'" in msg, msg)
    check("warning matches the stream wording",
          msg.startswith("Call on fake-model ended with finish_reason=")
          and "truncated" in msg, msg)

    print("3. provider sends no finish_reason")
    resp, warnings = run_invoke(fake_response("Fine.", None))
    check("null value -> None", resp.finish_reason is None, repr(resp.finish_reason))
    check("no warning on an unknown reason", not warnings, str(warnings))
    resp, warnings = run_invoke(fake_response("Fine.", None, with_attr=False))
    check("missing attribute -> None", resp.finish_reason is None,
          repr(resp.finish_reason))
    check("missing attribute logs nothing", not warnings, str(warnings))

    print("4. JSONL line")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        entry = log_line_for(lc.LLMResponse(content="x", finish_reason="length"), tmp)
        check("field written when known", entry.get("finish_reason") == "length",
              repr(entry.get("finish_reason")))
        check("line still carries its usual fields",
              entry.get("task") == "thought" and "tokens" in entry,
              str(sorted(entry)))
        entry = log_line_for(lc.LLMResponse(content="x"), tmp)
        check("field omitted when unknown", "finish_reason" not in entry,
              str(sorted(entry)))
        entry = log_line_for(None, tmp)
        check("failed task (response=None) logs no field",
              "finish_reason" not in entry, str(sorted(entry)))
    check("real log path restored",
          llm_logger.LOG_FILE == Path("./logs") / "llm_calls.jsonl",
          str(llm_logger.LOG_FILE))

    print("5. existing callers")
    plain = lc.LLMResponse("just content")
    check("positional construction works", plain.content == "just content",
          repr(plain.content))
    check("defaults stay None",
          plain.usage is None and plain.finish_reason is None,
          f"usage={plain.usage!r} finish={plain.finish_reason!r}")
    stripped = pq._strip_thinking(
        lc.LLMResponse(content="<think>x</think>real", finish_reason="stop"))
    check("_strip_thinking keeps the field",
          stripped.content == "real" and stripped.finish_reason == "stop",
          f"{stripped.content!r} / {stripped.finish_reason!r}")

    print("6. astream terminal chunk")
    pieces = ["Hello ", "world", ", cut off mid-sen"]
    expected = "".join(pieces)
    chunks = asyncio.run(collect_stream(pieces, "length"))
    check("one extra chunk only", len(chunks) == len(pieces) + 1, str(len(chunks)))
    check("terminal chunk carries the reason",
          chunks[-1].finish_reason == "length", repr(chunks[-1].finish_reason))
    check("terminal chunk is contentless", chunks[-1].content == "",
          repr(chunks[-1].content))
    check("content chunks carry no reason",
          all(c.finish_reason is None for c in chunks[:-1]),
          str([c.finish_reason for c in chunks[:-1]]))
    check("assembled text adds no character",
          "".join(c.content for c in chunks) == expected,
          repr("".join(c.content for c in chunks)))
    chunks_none = asyncio.run(collect_stream(pieces, None))
    check("no reason -> no extra chunk", len(chunks_none) == len(pieces),
          str(len(chunks_none)))
    check("text identical without the marker",
          "".join(c.content for c in chunks_none) == expected,
          repr("".join(c.content for c in chunks_none)))

    # The other two astream consumers, replayed as they are written:
    # routes/world_dev.py:1532 (accumulate, skipping falsy content) and
    # llm_router.py:212 (preload ping, breaks after the first chunk).
    async def world_dev_pattern():
        full = ""
        async for chunk in stream_client(pieces, "length").astream([]):
            content = getattr(chunk, "content", None)
            if not content:
                continue
            full += content
        return full

    async def preload_ping():
        async for _ in stream_client(pieces, "length").astream([]):
            break
        return True

    check("world_dev consumer sees the same text",
          asyncio.run(world_dev_pattern()) == expected)
    check("preload ping still terminates", asyncio.run(preload_ping()))

    print("7. SSE path (StreamingAgent)")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        sent, n_chunks, entry, response = asyncio.run(
            run_sse(pieces, "length", tmp))
        check("JSONL line carries the reason",
              entry.get("finish_reason") == "length",
              repr(entry.get("finish_reason")))
        check("task is the SSE task", entry.get("task") == "chat_stream",
              repr(entry.get("task")))
        check("client text unchanged", sent == expected, repr(sent))
        check("logged response unchanged", entry.get("response") == expected,
              repr(entry.get("response")))
        check("state.response unchanged", response == expected, repr(response))
        check("marker not counted as a chunk", n_chunks == len(pieces),
              str(n_chunks))

        sent2, n2, entry2, _ = asyncio.run(run_sse(pieces, None, tmp))
        check("no reason -> field omitted", "finish_reason" not in entry2,
              str(sorted(entry2)))
        check("text identical with and without a reason", sent2 == sent,
              repr(sent2))
        check("chunk count identical", n2 == n_chunks, f"{n2} vs {n_chunks}")
    check("real log path restored after the SSE run",
          llm_logger.LOG_FILE == Path("./logs") / "llm_calls.jsonl",
          str(llm_logger.LOG_FILE))

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("all checks green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
