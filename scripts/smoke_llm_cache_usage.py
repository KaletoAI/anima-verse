#!/usr/bin/env python3
"""Checks that prompt-cache hits are read from every backend dialect and logged.

Usage:
    ./.venv/bin/python scripts/smoke_llm_cache_usage.py

Runs without the server, without a world and without any network: the
OpenAI stream is a stub that yields SDK chunk objects, and the JSONL log is
redirected to a temp directory.

WHY these expectations

The backend behind the gateway is not ours to choose, so the reader must
understand every dialect a real backend speaks, and it must keep "the backend
said nothing" apart from "the backend said 0". Each case below names the
dialect and derives its expected dict by hand.

1. OpenAI / vLLM / LiteLLM / current llama.cpp:
   usage = {prompt_tokens: 4902, completion_tokens: 120,
            prompt_tokens_details: {cached_tokens: 3904}}
   -> {prompt_tokens: 4902, completion_tokens: 120, cached_tokens: 3904}

2. Gateway passing Anthropic words through:
   usage = {prompt_tokens: 5000, completion_tokens: 80,
            cache_read_input_tokens: 4096}
   -> cached_tokens 4096 (rule 2, rule 1 has no field)

3. llama.cpp timings only (no details in usage):
   usage = {prompt_tokens: 3000, completion_tokens: 50}, timings = {cache_n: 2048}
   -> cached_tokens 2048 (rule 3)

4. Rule order: details 100 AND cache_read 200 AND cache_n 300 -> 100 (first wins).

5. Details present but its cached_tokens is null (vLLM with details off):
   -> no cached_tokens key; rules 2/3 absent too -> key stays OUT.

6. Nothing reported: usage = {prompt_tokens: 10, completion_tokens: 2}
   -> {prompt_tokens: 10, completion_tokens: 2} — NO cached_tokens key.
   A reported zero (details.cached_tokens = 0) -> cached_tokens 0, key present.

7. Anthropic native: input_tokens 300 (after the breakpoint),
   cache_read_input_tokens 4000, cache_creation_input_tokens 700, output 90
   -> prompt_tokens = 300 + 4000 + 700 = 5000, cached_tokens 4000.

8. Stream: chunk A carries text and finish "stop" plus llama.cpp timings
   {cache_n: 1500}; chunk B has no choices and usage {prompt_tokens: 2000,
   completion_tokens: 30}. Merged terminal usage must be
   {prompt_tokens: 2000, completion_tokens: 30, cached_tokens: 1500}:
   chunk A's prompt_tokens 0 must not survive B, and B's missing cache field
   must not wipe A's 1500. Exactly one terminal chunk, contentless.

9. A server that answers stream_options with a 400: the stream is retried
   WITHOUT the field (second create call has no stream_options), text still
   arrives, and a later stream to the same (base_url, model) does not send
   the field again (third call: absent from the start, one call only).

10. Log line: tokens_cached=3904 -> entry.tokens.cached == 3904;
    tokens_cached=None -> "cached" not in entry.tokens.
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openai.types.chat import ChatCompletionChunk  # noqa: E402

from app.core import llm_client  # noqa: E402
from app.core.llm_client import LLMClient, _anthropic_usage, usage_from_openai  # noqa: E402
from app.utils import llm_logger  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: got {got!r}, want {want!r}")
    else:
        print(f"ok  {name}")


# --- 1-6: usage_from_openai ------------------------------------------------
check("1 openai details",
      usage_from_openai({"prompt_tokens": 4902, "completion_tokens": 120,
                         "prompt_tokens_details": {"cached_tokens": 3904}}),
      {"prompt_tokens": 4902, "completion_tokens": 120, "cached_tokens": 3904})
check("2 cache_read passthrough",
      usage_from_openai({"prompt_tokens": 5000, "completion_tokens": 80,
                         "cache_read_input_tokens": 4096})["cached_tokens"],
      4096)
check("3 llama.cpp timings",
      usage_from_openai({"prompt_tokens": 3000, "completion_tokens": 50},
                        {"cache_n": 2048})["cached_tokens"],
      2048)
check("4 rule order",
      usage_from_openai({"prompt_tokens": 1, "completion_tokens": 1,
                         "prompt_tokens_details": {"cached_tokens": 100},
                         "cache_read_input_tokens": 200},
                        {"cache_n": 300})["cached_tokens"],
      100)
check("5 details null -> no key",
      "cached_tokens" in usage_from_openai(
          {"prompt_tokens": 1, "completion_tokens": 1,
           "prompt_tokens_details": {"cached_tokens": None}}),
      False)
check("6a nothing reported",
      usage_from_openai({"prompt_tokens": 10, "completion_tokens": 2}),
      {"prompt_tokens": 10, "completion_tokens": 2})
check("6b reported zero stays",
      usage_from_openai({"prompt_tokens": 10, "completion_tokens": 2,
                         "prompt_tokens_details": {"cached_tokens": 0}}).get("cached_tokens"),
      0)

# --- 7: Anthropic ----------------------------------------------------------
check("7 anthropic totals",
      _anthropic_usage({"input_tokens": 300, "cache_read_input_tokens": 4000,
                        "cache_creation_input_tokens": 700, "output_tokens": 90}),
      {"prompt_tokens": 5000, "completion_tokens": 90, "cached_tokens": 4000})


# --- 8/9: streaming ----------------------------------------------------------
def _chunk(**kw):
    base = {"id": "c", "object": "chat.completion.chunk", "created": 0,
            "model": "m", "choices": []}
    base.update(kw)
    return ChatCompletionChunk.model_validate(base)


CHUNK_A = _chunk(choices=[{"index": 0, "delta": {"content": "Hallo"},
                           "finish_reason": "stop"}],
                 timings={"cache_n": 1500})
CHUNK_B = _chunk(usage={"prompt_tokens": 2000, "completion_tokens": 30,
                        "total_tokens": 2030})


class _BadRequest(Exception):
    status_code = 400

    def __str__(self):
        return "Unrecognized request argument supplied: stream_options"


class _Completions:
    def __init__(self, refuse_stream_options):
        self.refuse = refuse_stream_options
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.refuse and "stream_options" in kwargs:
            raise _BadRequest()

        async def gen():
            for c in (CHUNK_A, CHUNK_B):
                yield c
        return gen()


def _stub_client(refuse, base_url):
    client = LLMClient(model="m", api_key="x", api_base=base_url)
    comp = _Completions(refuse)
    client._async = type("A", (), {"chat": type("C", (), {"completions": comp})()})()
    return client, comp


async def _collect(client):
    return [c async for c in client.astream([{"role": "user", "content": "hi"}])]


client, comp = _stub_client(False, "http://stub-a/v1")
chunks = asyncio.run(_collect(client))
terminal = [c for c in chunks if not c.content]
check("8 one terminal chunk", len(terminal), 1)
check("8 merged usage", terminal[0].usage,
      {"prompt_tokens": 2000, "completion_tokens": 30, "cached_tokens": 1500})
check("8 finish kept", terminal[0].finish_reason, "stop")
check("8 include_usage requested", comp.calls[0].get("stream_options"),
      {"include_usage": True})

client, comp = _stub_client(True, "http://stub-b/v1")
chunks = asyncio.run(_collect(client))
check("9 retried without field", ["stream_options" in c for c in comp.calls],
      [True, False])
check("9 text still arrives", "".join(c.content for c in chunks), "Hallo")
client2, comp2 = _stub_client(True, "http://stub-b/v1")
asyncio.run(_collect(client2))
check("9 remembered per backend", ["stream_options" in c for c in comp2.calls],
      [False])
llm_client._NO_STREAM_USAGE.discard(("http://stub-b/v1", "m"))

# --- 10: log line ------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    llm_logger.LOG_DIR = Path(tmp)
    llm_logger.LOG_FILE = Path(tmp) / "llm_calls.jsonl"
    # tokens_output=0 keeps llm_stats.record_call (a world-side store) out.
    llm_logger.log_llm_call(task="smoke", model="m", tokens_input=4902,
                            tokens_output=0, tokens_cached=3904)
    llm_logger.log_llm_call(task="smoke", model="m", tokens_input=10,
                            tokens_output=0, tokens_cached=None)
    lines = [json.loads(x) for x in llm_logger.LOG_FILE.read_text().splitlines()]
check("10 cached written", lines[0]["tokens"].get("cached"), 3904)
check("10 absent when unreported", "cached" in lines[1]["tokens"], False)

if failures:
    print("\nFAILED:")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("\nall checks passed")
